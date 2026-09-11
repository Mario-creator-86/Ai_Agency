import { loadAgentDetails } from './agent_details.js';
import { escapeHtml } from './html.js';
import './style.css';
import { initSettings } from './settings.js';
import { acceptSnapshot } from './projection.js';
import { OfficeEngine } from './office_engine.js';
import { OfficeState } from './office_state.js';
import { Ledger } from './ledger.js';

/** @param {string} id @returns {HTMLElement} */
function element(id) {
  const node = document.getElementById(id);
  if (!node) throw new Error(`Missing UI element ${id}`);
  return node;
}

const login = element('login');
const workspace = element('workspace');
const input = /** @type {HTMLInputElement} */ (element('owner-token'));
const stopButton = /** @type {HTMLButtonElement} */ (element('stop-toggle'));
const inspector = /** @type {HTMLDialogElement} */ (element('agent-inspector'));

let ownerToken = '';
let state = null;
let pendingCommand = null;
let epoch = 0;
let busy = false;
let connected = false;
let socket = null;

// 2D Office Engine & State
const officeCanvas = /** @type {HTMLCanvasElement} */ (element('office-canvas'));
const officeState = new OfficeState();
let officeEngine = null;
let currentSelectedAgent = null;
let inspectorRequest = 0;

/** Everything the studio does and says, read from its own events. */
const ledger = new Ledger({
  list: element('ledger-list'),
  now: element('ledger-now'),
  filters: element('ledger-filters'),
  escape: escapeHtml,
});

function notify(message) {
  element('message').textContent = message;
  element('message').hidden = !message;
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      headers: {
        Authorization: `Bearer ${ownerToken}`,
        'Content-Type': 'application/json',
      },
      signal: AbortSignal.timeout(
        path.startsWith('/settings') || path.startsWith('/providers') ? 45000 : 10000,
      ),
      cache: 'no-store',
    });
  } catch {
    throw new Error('Conexiune indisponibilă. Datele afișate nu mai sunt actualizate.');
  }
  if (!response.ok) {
    // Prefer what the server said. Every refusal this backend writes is a sentence meant for
    // the Owner — which host is not authorised, why a provider did not answer, what is missing
    // before a publication can proceed — and replacing it with "try again" would throw away
    // exactly the part that tells them what to do. The generic wording is the fallback for a
    // response that carries no explanation of its own.
    let message =
      response.status === 401
        ? 'Cheia Owner nu este validă.'
        : response.status === 409
          ? 'Starea s-a schimbat. Datele au fost reîncărcate; repetă comanda.'
          : 'Conexiunea nu a putut fi verificată. Încearcă din nou.';
    const body = await response.json().catch(() => ({}));
    if (typeof body.detail === 'string' && body.detail.trim()) {
      message = body.detail;
    } else if (body.detail && typeof body.detail.error === 'string') {
      message = body.detail.message || body.detail.error;
    }
    const error = new Error(message);
    Object.assign(error, { status: response.status, detail: body.detail });
    throw error;
  }
  return response.json();
}

// A model assignment or a provider check changes what the office should be showing, so the
// layout is reloaded whenever Settings changes something.
const settingsUI = initSettings(api, { onChange: async () => {
  await loadOfficeLayout();
  if(inspector.open && currentSelectedAgent) await showInspector(currentSelectedAgent);
} });

function initOffice() {
  if (!officeEngine) {
    officeEngine = new OfficeEngine(officeCanvas, {
      onSelectAgent: (agent) => {
        currentSelectedAgent = agent;
        if (agent) {
          showInspector(agent);
        } else {
          inspector.close();
        }
      },
    });
    publishSceneHandle();

    // Wire camera zoom buttons
    element('zoom-in').addEventListener('click', () => {
      officeEngine.viewport.setZoom(officeEngine.viewport.zoom * 1.25);
    });
    element('zoom-out').addEventListener('click', () => {
      officeEngine.viewport.setZoom(officeEngine.viewport.zoom * 0.8);
    });
    element('zoom-fit').addEventListener('click', () => {
      if (officeState.layout) {
        officeEngine.viewport.fitToOffice(officeState.layout.width, officeState.layout.height);
      }
    });
    element('zoom-reset').addEventListener('click', () => {
      officeEngine.viewport.setZoom(1.0);
    });

    // Wire Fullscreen & Exit Fullscreen buttons
    const officeContainer = element('office-scene-container');
    const fsBtn = element('fullscreen-btn');
    const exitFsBtn = element('exit-fullscreen-btn');

    const doc = /** @type {any} */ (document);
    const container = /** @type {any} */ (officeContainer);

    const updateFullscreenUI = () => {
      const isFs = Boolean(
        doc.fullscreenElement ||
        doc.webkitFullscreenElement ||
        doc.mozFullScreenElement ||
        doc.msFullscreenElement ||
        (officeContainer && officeContainer.classList.contains('is-fullscreen')),
      );
      if (fsBtn && exitFsBtn) {
        if (isFs) {
          fsBtn.classList.add('hidden');
          exitFsBtn.classList.remove('hidden');
        } else {
          fsBtn.classList.remove('hidden');
          exitFsBtn.classList.add('hidden');
        }
      }
      // Resize after the browser has applied the new layout, then once more on the next
      // frame: leaving fullscreen settles the container size a tick after the event fires.
      const resizeScene = () => officeEngine && officeEngine.resize();
      requestAnimationFrame(() => {
        resizeScene();
        requestAnimationFrame(resizeScene);
      });
      setTimeout(resizeScene, 150);
    };

    if (fsBtn && officeContainer) {
      fsBtn.addEventListener('click', async () => {
        try {
          if (container.requestFullscreen) {
            await container.requestFullscreen();
          } else if (container.webkitRequestFullscreen) {
            await container.webkitRequestFullscreen();
          } else if (container.msRequestFullscreen) {
            await container.msRequestFullscreen();
          } else {
            officeContainer.classList.add('is-fullscreen');
            updateFullscreenUI();
          }
        } catch (err) {
          console.warn('Native requestFullscreen failed, using fallback', err);
          officeContainer.classList.add('is-fullscreen');
          updateFullscreenUI();
        }
      });
    }

    if (exitFsBtn) {
      exitFsBtn.addEventListener('click', async () => {
        try {
          if (
            doc.fullscreenElement ||
            doc.webkitFullscreenElement ||
            doc.mozFullScreenElement ||
            doc.msFullscreenElement
          ) {
            if (doc.exitFullscreen) {
              await doc.exitFullscreen();
            } else if (doc.webkitExitFullscreen) {
              await doc.webkitExitFullscreen();
            } else if (doc.msExitFullscreen) {
              await doc.msExitFullscreen();
            }
          }
        } catch (err) {
          console.warn('Exit fullscreen error', err);
        } finally {
          if (officeContainer) {
            officeContainer.classList.remove('is-fullscreen');
          }
          updateFullscreenUI();
        }
      });
    }

    document.addEventListener('fullscreenchange', () => {
      if (!doc.fullscreenElement && officeContainer) {
        officeContainer.classList.remove('is-fullscreen');
      }
      updateFullscreenUI();
    });
    document.addEventListener('webkitfullscreenchange', () => {
      if (!doc.webkitFullscreenElement && officeContainer) {
        officeContainer.classList.remove('is-fullscreen');
      }
      updateFullscreenUI();
    });
    window.addEventListener('keydown', (e) => {
      if (
        e.key === 'Escape' &&
        officeContainer &&
        officeContainer.classList.contains('is-fullscreen')
      ) {
        officeContainer.classList.remove('is-fullscreen');
        updateFullscreenUI();
      }
    });
  }
}

async function loadOfficeLayout() {
  try {
    const layout = await api('/office/layout');
    officeState.initFromLayout(layout);
    if (officeEngine) {
      officeEngine.setLayout(layout);
      updateOfficeCanvas();
      await loadOfficeCharacterBible();
    }
  } catch (err) {
    console.error('Failed to load office layout', err);
  }
}

/**
 * The Character Bible drives how each recurring employee is drawn (hair, glasses, headset,
 * outfit colours). Read-only; the office falls back to its deterministic looks if the read fails.
 */
async function loadOfficeCharacterBible() {
  if (!officeEngine) return;
  try {
    const data = await api('/media/character-bible');
    officeEngine.setCharacterBible(data.characters || []);
  } catch (err) {
    console.warn('Character bible unavailable for the office', err);
  }
}

/**
 * The office scene, exposed for automated verification.
 *
 * The scene is driven entirely by backend events, so the only way to check that the lift
 * moves when — and only when — the backend says work changed floor is to read the engine's
 * own state back. Read-only inspection handle; nothing in the app reads it.
 */
function publishSceneHandle() {
  /** @type {any} */ (window).__studio = {
    engine: officeEngine,
    state: officeState,
  };
}

function updateOfficeCanvas() {
  if (!officeEngine) return;
  officeState.cleanupExpiredBubbles();
  officeEngine.setAgents(officeState.agents);
  officeEngine.setSpeechBubbles(officeState.speechBubbles);
  officeEngine.setProjectTokens(officeState.projectTokens);
}

function connectWebSocket() {
  if (socket) {
    socket.close();
    socket = null;
  }
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${location.host}/api/v1/ws?token=${encodeURIComponent(ownerToken)}`;

  try {
    socket = new WebSocket(url);
    socket.onopen = () => {
      console.log('WebSocket connected to Studio events gateway');
      // Request missed events replay from current snapshot cursor
      const cursor = state ? state.cursor : 0;
      socket.send(JSON.stringify({ type: 'replay', after_sequence: cursor, limit: 100 }));
    };
    socket.onmessage = (msg) => {
      try {
        const payload = JSON.parse(msg.data);
        if (payload.type === 'event' || payload.type === 'replay_event') {
          const eventData = payload.data;
          officeState.handleDomainEvent(eventData);
          updateOfficeCanvas();
          ledger.add(eventData);
          element('ledger-count').textContent = `${ledger.events.size} înregistrări`;
        }
      } catch (e) {
        console.error('Malformed WS message', e);
      }
    };
    socket.onerror = () => {
      console.warn('WebSocket connection error');
    };
    socket.onclose = () => {
      console.log('WebSocket closed');
    };
  } catch (e) {
    console.error('WS init failed', e);
  }
}

/**
 * Show what the backend says about this agent.
 *
 * The model field used to be a fixed string written into the page, so every agent appeared to
 * be running glm-5.2:cloud no matter what the Owner had assigned in Settings. It is now filled
 * from the agent's own record, and it distinguishes the three states that actually exist: no
 * model assigned, a model assigned on a provider that has never answered, and a model the
 * provider confirmed. Only the last one can run.
 */
async function showInspector(agent) {
  const request=++inspectorRequest, session=epoch;
  const id=agent.id||agent.agent_id;
  renderInspector({...agent,model_loading:true,model_is_available:false});
  try {
    const details=await loadAgentDetails(api,id);
    if(request!==inspectorRequest||session!==epoch||!inspector.open) return;
    currentSelectedAgent={...agent,...details,model_loading:false,model_error:null};
    officeState.setAgents([details]);
    renderInspector(currentSelectedAgent);
  } catch(error) {
    if(request!==inspectorRequest||session!==epoch||!inspector.open) return;
    renderInspector({...agent,model_error:error instanceof Error?error.message:'Datele modelului nu pot fi încărcate.',model_is_available:false});
  }
  try {
    const identity = await api(`/agents/${encodeURIComponent(id)}/identity`);
    if(request!==inspectorRequest||session!==epoch||!inspector.open) return;
    renderIdentity(identity);
    await loadAgentHistory(id);
  } catch(error) {
    if(request!==inspectorRequest||session!==epoch||!inspector.open) return;
    element('inspector-mission').textContent = error instanceof Error ? error.message : 'Identitatea nu a putut fi încărcată.';
  }
}

const TIMELINE_LABEL = {
  run: 'Sarcină',
  owner_chat: 'Întrebare',
  message: 'Mesaj',
  memory: 'Memorie',
  AGENT_OPINION: 'Decizie',
  HISTORICAL_EVENT: 'Eveniment',
  TEMP_CONTEXT: 'Context',
  OWNER_POLICY: 'Politică',
  VERIFIED_FACT: 'Fapt verificat',
  STRATEGY: 'Strategie',
};

function timelineTime(iso) {
  return iso ? new Date(iso).toLocaleString('ro-RO', { dateStyle: 'short', timeStyle: 'short' }) : '';
}

/** One line of history: what was asked and answered, or sent, or remembered. */
function timelineItem(item) {
  if (item.kind === 'run') {
    const label = item.task_type === 'owner_chat' ? TIMELINE_LABEL.owner_chat : `${TIMELINE_LABEL.run} · ${item.task_type}`;
    const answer = item.answered
      ? `<div class="chat-answer">${escapeHtml(item.answered)}</div>`
      : `<div class="chat-answer text-error">${escapeHtml(item.error || item.status)}</div>`;
    const meta = [item.model, item.memory_used ? `${item.memory_used} amintiri folosite` : '', item.cost_vr ? `${item.cost_vr} VR$` : '']
      .filter(Boolean).join(' · ');
    return `<div class="chat-item chat-run"><div class="chat-meta"><span class="policy-tag policy-flexible">${escapeHtml(label)}</span> <small>${escapeHtml(timelineTime(item.at))}${meta ? ` · ${escapeHtml(meta)}` : ''}</small></div><div class="chat-asked">${escapeHtml(item.asked || '')}</div>${answer}</div>`;
  }
  if (item.kind === 'message') {
    const direction = item.from_name ? `de la ${item.from_name}` : '';
    const to = item.to_name ? `către ${item.to_name}` : '';
    return `<div class="chat-item chat-message"><div class="chat-meta"><span class="policy-tag policy-locked">${escapeHtml(item.intent)}</span> <small>${escapeHtml(timelineTime(item.at))} ${escapeHtml([direction, to].filter(Boolean).join(' '))} · ${escapeHtml(item.status)}</small></div><div>${escapeHtml(item.subject)}</div>${item.resolution ? `<div class="helper">${escapeHtml(item.resolution)}</div>` : ''}</div>`;
  }
  return `<div class="chat-item chat-memory"><div class="chat-meta"><span class="policy-tag">${escapeHtml(TIMELINE_LABEL[item.memory_class] || item.memory_class)}</span> <small>${escapeHtml(timelineTime(item.at))}</small></div><div>${escapeHtml(item.content)}</div></div>`;
}

async function loadAgentHistory(agentId) {
  const box = element('agent-history');
  try {
    const data = await api(`/agents/${encodeURIComponent(agentId)}/history`);
    const items = (data.timeline || []).slice().reverse();
    box.innerHTML = items.length
      ? items.map(timelineItem).join('')
      : '<div class="helper">Nimic încă: nicio sarcină, niciun mesaj, nicio decizie înregistrată.</div>';
    box.scrollTop = box.scrollHeight;
  } catch (error) {
    box.innerHTML = `<div class="text-error">${escapeHtml(error instanceof Error ? error.message : 'Istoricul nu a putut fi încărcat.')}</div>`;
  }
}

/** Who the agent is, as the model is told: contract, character, memory, open messages. */
function renderIdentity(identity) {
  const contract = identity.contract || {};
  const work = contract.work_contract_json || {};
  const who = identity.character ? `${identity.display_name} este ${identity.character.canonical_name}.` : identity.display_name;
  element('inspector-mission').textContent = `${who} Misiune: ${contract.mission || 'nedefinită'}. Raportează către ${work.reports_to || '—'}.`;
  const sections = [['watch_for', 'Este atent la'], ['investigate', 'Investighează'], ['correct', 'Corectează'], ['let_pass', 'Lasă să treacă'], ['never_let_pass', 'Nu lasă niciodată'], ['escalate_when', 'Escaladează când'], ['deliverables', 'Livrabile']];
  element('inspector-contract').innerHTML = sections
    .filter(([key]) => Array.isArray(work[key]) && work[key].length)
    .map(([key, label]) => `<div class="identity-block"><span class="stat-label">${escapeHtml(label)}</span><ul>${work[key].map((item) => `<li>${escapeHtml(String(item))}</li>`).join('')}</ul></div>`)
    .join('') || '<p class="helper">Rolul nu are încă un contract de lucru. Rulează bootstrap-ul pentru a-l însămânța.</p>';
  element('inspector-system-prompt').textContent = identity.system_prompt || '';
  const memory = identity.memory || [];
  element('inspector-memory').innerHTML = memory.length
    ? memory.map((m) => `<li><span class="policy-tag policy-flexible">${escapeHtml(m.memory_class)}</span> ${escapeHtml(m.content)}</li>`).join('')
    : '<li class="helper">Nu își amintește nimic încă: nicio verificare, decizie sau publicare înregistrată.</li>';
  const messages = (identity.messages || []).filter((m) => m.status !== 'RESOLVED').slice(0, 8);
  element('inspector-messages').innerHTML = messages.length
    ? messages.map((m) => `<li><span class="policy-tag policy-locked">${escapeHtml(m.intent)}</span> ${escapeHtml(m.subject)}${m.from_name ? ` <small>· de la ${escapeHtml(m.from_name)}</small>` : ''}</li>`).join('')
    : '<li class="helper">Niciun mesaj deschis.</li>';
}

function renderInspector(agent) {
  element('inspector-name').textContent = agent.display_name || 'Agent';
  element('inspector-role').textContent = (agent.role_name || 'Agent').toUpperCase();
  element('inspector-state').textContent = agent.runtime_state || 'IDLE';
  element('inspector-lifecycle').textContent = agent.lifecycle || 'ACTIVE';
  element('inspector-id').textContent = agent.id || agent.agent_id || '—';

  const modelEl = element('inspector-model');
  const runBtn = /** @type {HTMLButtonElement} */ (
    element('agent-run-form').querySelector('button[type="submit"]')
  );
  if(agent.model_loading) {
    modelEl.textContent='Se verifică modelul alocat…';
    modelEl.className='stat-value';modelEl.title='Se citesc datele actuale ale agentului.';
  } else if(agent.model_error) {
    modelEl.textContent='Alocarea nu a putut fi verificată';
    modelEl.className='stat-value text-error';modelEl.title=agent.model_error;
  } else if (!agent.model_name) {
    modelEl.textContent = 'Niciun model alocat';
    modelEl.className = 'stat-value text-error';
    modelEl.title = 'Alocă un model acestui agent din Settings › Agenți.';
  } else if (agent.model_is_available) {
    modelEl.textContent = agent.model_name;
    modelEl.className = 'stat-value text-success';
    modelEl.title = `Furnizor: ${agent.provider_name || 'necunoscut'}`;
  } else {
    modelEl.textContent = `${agent.model_name} · neverificat`;
    modelEl.className = 'stat-value text-warn';
    modelEl.title =
      `Modelul este alocat, dar furnizorul ${agent.provider_name || ''} nu a fost verificat. ` +
      'Verifică-l în Settings înainte de a rula o sarcină.';
  }
  runBtn.disabled = !agent.model_is_available;
  runBtn.title = agent.model_is_available
    ? ''
    : 'Rularea are nevoie de un model verificat. Alocă și verifică unul în Settings.';

  element('agent-run-output').hidden = true;
  element('agent-run-output').textContent = '';
  if(!inspector.open) inspector.showModal();
}

// A queued close event from the previous agent must not cancel a newly opened inspector.
inspector.addEventListener('close',()=>{if(!inspector.open) inspectorRequest++;});

element('inspector-close').addEventListener('click', () => {
  inspector.close();
  if (officeEngine) officeEngine.setSelectedAgent(null);
});

element('agent-pause-btn').addEventListener('click', async () => {
  if (!currentSelectedAgent) return;
  const agentId = currentSelectedAgent.id || currentSelectedAgent.agent_id;
  try {
    const updated = await api(`/agents/${agentId}/pause`, { method: 'POST' });
    currentSelectedAgent.lifecycle = updated.lifecycle;
    element('inspector-lifecycle').textContent = updated.lifecycle;
    updateOfficeCanvas();
  } catch (err) {
    alert(err.message);
  }
});

element('agent-resume-btn').addEventListener('click', async () => {
  if (!currentSelectedAgent) return;
  const agentId = currentSelectedAgent.id || currentSelectedAgent.agent_id;
  try {
    const updated = await api(`/agents/${agentId}/resume`, { method: 'POST' });
    currentSelectedAgent.lifecycle = updated.lifecycle;
    element('inspector-lifecycle').textContent = updated.lifecycle;
    updateOfficeCanvas();
  } catch (err) {
    alert(err.message);
  }
});

element('agent-run-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!currentSelectedAgent) return;
  const agentId = currentSelectedAgent.id || currentSelectedAgent.agent_id;
  const objectiveInput = /** @type {HTMLInputElement} */ (element('agent-run-objective'));
  const outputDiv = element('agent-run-output');
  outputDiv.hidden = false;
  outputDiv.textContent = 'Trimitere comandă către model...';

  try {
    const message = objectiveInput.value;
    const item = await api(`/agents/${agentId}/chat`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    });
    objectiveInput.value = '';
    outputDiv.hidden = true;
    const box = element('agent-history');
    if (box.querySelector('.helper') && !box.querySelector('.chat-item')) box.innerHTML = '';
    box.insertAdjacentHTML('beforeend', timelineItem({ ...item, asked: message }));
    box.scrollTop = box.scrollHeight;
  } catch (err) {
    outputDiv.textContent = `Eroare: ${err instanceof Error ? err.message : err}`;
  }
});

// Factual Research & Verification Modal logic
const researchModal = /** @type {HTMLDialogElement} */ (element('research-modal'));
const openResearchBtn = element('open-research-btn');
const closeResearchBtn = element('close-research-btn');
const topicProposeForm = element('topic-propose-form');
const refreshTopicsBtn = element('refresh-topics-btn');

/**
 * Keep a toolbar button highlighted only while its panel is open.
 * The highlight was previously hard-coded in the markup, so "Cercetare" looked selected
 * permanently even with every panel closed.
 */
function bindPanelToggle(buttonId, dialog) {
  const button = document.getElementById(buttonId);
  if (!button || !dialog) return;
  const sync = () => button.classList.toggle('cam-btn-active', dialog.open);
  dialog.addEventListener('close', sync);
  dialog.addEventListener('cancel', () => setTimeout(sync, 0));
  button.addEventListener('click', () => setTimeout(sync, 0));
  sync();
}

if (openResearchBtn) {
  openResearchBtn.addEventListener('click', () => {
    researchModal.showModal();
    loadTopics();
    loadSources();
    loadScripts();
  });
}

if (closeResearchBtn) {
  closeResearchBtn.addEventListener('click', () => {
    researchModal.close();
  });
}

if (refreshTopicsBtn) {
  refreshTopicsBtn.addEventListener('click', loadTopics);
}

const refreshSourcesBtn = document.getElementById('refresh-sources-btn');
if (refreshSourcesBtn) {
  refreshSourcesBtn.addEventListener('click', loadSources);
}

const refreshScriptsBtn = document.getElementById('refresh-scripts-btn');
if (refreshScriptsBtn) {
  refreshScriptsBtn.addEventListener('click', loadScripts);
}

bindPanelToggle('open-research-btn', researchModal);

async function loadTopics() {
  const listEl = element('topics-list');
  try {
    const data = await api('/factual/topics');
    const topics = data.topics || [];
    if (topics.length === 0) {
      listEl.innerHTML = '<div class="topics-loading">Niciun subiect propus încă.</div>';
      return;
    }
    listEl.innerHTML = topics
      .map((t) => {
        const cardClass =
          t.novelty_score >= 0.8 ? 'topic-card topic-card-high' : 'topic-card topic-card-low';
        const pct = Math.round((t.novelty_score || 0) * 100);
        return `
        <div class="${cardClass}">
          <div class="topic-card-header">
            <strong class="topic-card-title">${escapeHtml(t.title)}</strong>
            <span class="topic-card-novelty">Noutate: ${pct}%</span>
          </div>
          <p class="topic-card-subject">${escapeHtml(t.topic)}</p>
          <div class="topic-card-meta">
            <span>Public: ${escapeHtml(t.target_audience)}</span> · <span>Status: <strong class="topic-card-status">${escapeHtml(t.status)}</strong></span>
          </div>
        </div>
      `;
      })
      .join('');
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">Eroare la încărcare: ${escapeHtml(err.message)}</div>`;
  }
}

/* ---------------------------------------------------------------------------
 * Sources and claims.
 *
 * This is the Phase 4 loop the Owner has to be able to drive: fetch a page from a site they
 * authorised, have the research agent read it, then verify each claim before anything can be
 * scripted. Every status shown here comes from the backend — a claim is UNVERIFIED until a
 * verification actually ran, and nothing on this screen can change that.
 * ------------------------------------------------------------------------- */

const CLAIM_STATUS_LABEL = {
  UNVERIFIED: 'Neverificată',
  SUPPORTED: 'Susținută de sursă',
  REFUTED: 'Contrazisă de sursă',
  UNCERTAIN: 'Sursa nu spune',
  DISPUTED: 'Disputată',
};

/** Short, readable provenance: enough of the digest to compare, not a wall of hex. */
function shortHash(hash) {
  return String(hash || '').slice(0, 12);
}

function claimCountsSummary(counts) {
  const entries = Object.entries(counts || {});
  if (!entries.length) return 'Nicio afirmație extrasă încă';
  return entries.map(([status, n]) => `${n} ${CLAIM_STATUS_LABEL[status] || status}`).join(' · ');
}

const HOST_TEST_LABEL = { PASSED: 'citibil', FAILED: 'nu poate fi citit' };

/**
 * The authorised sites, each with the result of its last connectivity test. A site is a
 * source only if the studio can actually read it, so the test is next to the entry, and a
 * site that never passed is marked as such rather than assumed fine.
 */
function renderAllowedHosts(rows) {
  const box = element('allowed-hosts');
  const allowEl = element('sources-allowlist');
  if (!rows.length) {
    allowEl.textContent = 'Niciun site autorizat. Adaugă unul mai jos și testează-l; până atunci preluarea surselor este oprită.';
    allowEl.className = 'helper-note helper-warn';
    box.innerHTML = '';
    return;
  }
  const passed = rows.filter((r) => r.last_test_status === 'PASSED').length;
  allowEl.textContent = `${rows.length} site-uri autorizate, ${passed} testate cu succes. Doar Owner-ul poate schimba lista; agenții nu au nicio unealtă pentru asta.`;
  allowEl.className = passed ? 'helper-note' : 'helper-note helper-warn';
  box.innerHTML = rows
    .map((r) => {
      const status = r.last_test_status
        ? `<span class="host-test host-test-${escapeHtml(r.last_test_status.toLowerCase())}" title="${escapeHtml(r.last_test_detail || '')}">${escapeHtml(HOST_TEST_LABEL[r.last_test_status] || r.last_test_status)}${r.last_test_at ? ` · ${escapeHtml(new Date(r.last_test_at).toLocaleString('ro-RO'))}` : ''}</span>`
        : '<span class="host-test host-test-untested">netestat</span>';
      const origin = r.source === 'env' ? '<span class="host-origin">.env</span>' : '';
      const remove = r.source === 'owner'
        ? `<button class="quiet btn-host-remove" data-host="${escapeHtml(r.host)}">Șterge</button>`
        : '';
      return `
        <div class="allowed-host-row" data-host="${escapeHtml(r.host)}">
          <code class="allowed-host-name">${escapeHtml(r.host)}</code> ${origin} ${status}
          <span class="allowed-host-actions">
            <button class="quiet btn-host-test" data-host="${escapeHtml(r.host)}">Testează</button>
            ${remove}
          </span>
          ${r.last_test_status === 'FAILED' && r.last_test_detail ? `<div class="host-test-detail text-error">${escapeHtml(r.last_test_detail)}</div>` : ''}
        </div>`;
    })
    .join('');
  box.querySelectorAll('.btn-host-test').forEach((btn) => {
    btn.addEventListener('click', () => testAllowedHost(btn.getAttribute('data-host'), btn));
  });
  box.querySelectorAll('.btn-host-remove').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try {
        await api(`/factual/sources/allowed-hosts/${encodeURIComponent(btn.getAttribute('data-host') || '')}`, { method: 'DELETE' });
        await loadSources();
      } catch (err) {
        showSourceStatus(err.message, true);
      }
    });
  });
}

function showSourceStatus(text, isError) {
  const status = element('source-retrieve-status');
  status.hidden = false;
  status.textContent = text;
  status.className = `dialog-status-msg ${isError ? 'text-error' : 'text-success'}`;
}

async function testAllowedHost(host, btn) {
  if (!host) return;
  const button = /** @type {HTMLButtonElement | null} */ (btn);
  if (button) { button.disabled = true; button.textContent = 'Se testează…'; }
  try {
    const result = await api(`/factual/sources/allowed-hosts/${encodeURIComponent(host)}/test`, { method: 'POST' });
    showSourceStatus(
      result.status === 'PASSED'
        ? `${host}: poate fi citit. ${result.detail}`
        : `${host}: nu poate fi folosit ca sursă. ${result.detail}`,
      result.status !== 'PASSED',
    );
  } catch (err) {
    showSourceStatus(err.message, true);
  } finally {
    await loadSources();
  }
}

element('allowed-host-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const input = /** @type {HTMLInputElement} */ (element('allowed-host-input'));
  const host = input.value.trim().toLowerCase().replace(/^https?:\/\//, '').replace(/\/.*$/, '');
  if (!host) return;
  try {
    await api(`/factual/sources/allowed-hosts/${encodeURIComponent(host)}`, { method: 'PUT' });
    input.value = '';
    await loadSources();
    await testAllowedHost(host, null);
  } catch (err) {
    showSourceStatus(err.message, true);
  }
});

async function loadSources() {
  const listEl = element('sources-list');
  try {
    const data = await api('/factual/sources');
    renderAllowedHosts(data.allowed_host_rows || []);

    const sources = data.sources || [];
    if (!sources.length) {
      listEl.innerHTML = '<div class="topics-loading">Nicio sursă preluată încă.</div>';
      return;
    }
    listEl.innerHTML = sources
      .map(
        (src) => `
        <div class="topic-card source-card" data-source-id="${escapeHtml(src.id)}">
          <div class="topic-card-header">
            <strong class="topic-card-title">${escapeHtml(src.title)}</strong>
            <span class="topic-card-novelty">${escapeHtml(src.publisher)}</span>
          </div>
          <p class="topic-card-subject source-url">${escapeHtml(src.url)}</p>
          <div class="topic-card-meta">
            <span>${src.characters} caractere</span>
            · <span>amprentă ${escapeHtml(shortHash(src.content_hash))}</span>
            · <span>${escapeHtml(new Date(src.fetched_at).toLocaleString('ro-RO'))}</span>
          </div>
          <div class="topic-card-meta">${escapeHtml(claimCountsSummary(src.claim_counts))}</div>
          <div class="source-actions">
            <button class="secondary btn-extract-claims" data-source-id="${escapeHtml(src.id)}">Extrage afirmații cu agentul</button>
            <button class="quiet btn-show-claims" data-source-id="${escapeHtml(src.id)}">Vezi afirmațiile</button>
          </div>
          <div class="claims-list" id="claims-${escapeHtml(src.id)}" hidden></div>
        </div>`,
      )
      .join('');

    listEl.querySelectorAll('.btn-extract-claims').forEach((btn) => {
      btn.addEventListener('click', () => extractClaims(btn.getAttribute('data-source-id'), btn));
    });
    listEl.querySelectorAll('.btn-show-claims').forEach((btn) => {
      btn.addEventListener('click', () => loadClaims(btn.getAttribute('data-source-id')));
    });
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">Eroare la încărcare: ${escapeHtml(err.message)}</div>`;
  }
}

async function loadClaims(sourceId) {
  const box = element(`claims-${sourceId}`);
  box.hidden = false;
  box.innerHTML = '<div class="topics-loading">Se încarcă afirmațiile…</div>';
  try {
    const data = await api(`/factual/claims?source_id=${encodeURIComponent(sourceId)}`);
    const claims = data.claims || [];
    if (!claims.length) {
      box.innerHTML =
        '<div class="topics-loading">Nicio afirmație extrasă din această sursă.</div>';
      return;
    }
    box.innerHTML = claims.map((c) => renderClaim(c, sourceId)).join('');
    box.querySelectorAll('.btn-agent-verify').forEach((btn) => {
      btn.addEventListener('click', () => agentVerify(btn, sourceId));
    });
    box.querySelectorAll('.btn-owner-verdict').forEach((btn) => {
      btn.addEventListener('click', () => {
        const form = /** @type {HTMLFormElement | null} */ (
          box.querySelector(`#verdict-${btn.getAttribute('data-claim-id')}`)
        );
        if (form) form.hidden = !form.hidden;
      });
    });
    box.querySelectorAll('.owner-verdict-form').forEach((form) => {
      form.addEventListener('submit', (e) => submitOwnerVerdict(e, form, sourceId));
    });
  } catch (err) {
    box.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
  }
}

/**
 * One claim, with the two honest ways it can stop being unverified.
 *
 * A fact-check by a second agent, which has to quote the source, or the Owner's own recorded
 * judgement. There is no single button that just marks something true — that would be a verdict
 * with nothing behind it.
 */
function renderClaim(claim, sourceId) {
  const status = String(claim.status || 'UNVERIFIED');
  const unverified = status === 'UNVERIFIED';
  const evidence = claim.evidence_text
    ? `<blockquote class="claim-evidence">„${escapeHtml(claim.evidence_text)}"</blockquote>`
    : '';
  const notes = claim.verifier_notes
    ? `<div class="claim-notes">${escapeHtml(claim.verifier_notes)}</div>`
    : '';
  const by = claim.verified_by_agent_id
    ? ' · verificat de un agent'
    : claim.verified_at
      ? ' · verificat de Owner'
      : '';

  const actions = unverified
    ? `<button class="quiet btn-agent-verify" data-claim-id="${escapeHtml(claim.id)}">Verifică cu un al doilea agent</button>
       <button class="quiet btn-owner-verdict" data-claim-id="${escapeHtml(claim.id)}">Verdict propriu…</button>`
    : '';

  const form = unverified
    ? `<form class="owner-verdict-form" id="verdict-${escapeHtml(claim.id)}" data-claim-id="${escapeHtml(claim.id)}" hidden>
         <select name="status" aria-label="Verdict">
           <option value="SUPPORTED">Susținută de sursă</option>
           <option value="REFUTED">Contrazisă de sursă</option>
           <option value="UNCERTAIN">Sursa nu spune</option>
         </select>
         <input name="evidence" placeholder="Fragment din sursă (opțional)" maxlength="4000" />
         <input name="notes" placeholder="De ce? (obligatoriu)" minlength="3" maxlength="2000" required />
         <button type="submit" class="secondary">Înregistrează verdictul</button>
       </form>`
    : '';

  return `
    <div class="claim-row claim-${escapeHtml(status.toLowerCase())}">
      <div class="claim-text">${escapeHtml(claim.claim_text)}</div>
      ${evidence}
      ${notes}
      <div class="claim-meta">
        <span class="claim-status">${escapeHtml(CLAIM_STATUS_LABEL[status] || status)}</span>
        · <span>${escapeHtml(claim.importance)}</span>${escapeHtml(by)}
        ${actions}
      </div>
      ${form}
    </div>`;
}

/** Ask the research agent to read the source. Claims land UNVERIFIED, by design. */
async function extractClaims(sourceId, button) {
  claimStatusBox('Agentul citește sursa… poate dura până la un minut.', false);
  button.disabled = true;
  try {
    const result = await api(`/factual/sources/${sourceId}/extract-with-agent`, {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID() }),
    });
    const n = (result.claims || []).length;
    claimStatusBox(
      `${n} afirmații extrase, toate NEVERIFICATE — un al doilea agent trebuie să le confirme din sursă înainte de scenarizare.`,
      false,
    );
    // The source cards are re-rendered first: reopening the claims before that would fill a
    // box that is about to be replaced, and the list would vanish under the Owner.
    await loadSources();
    await loadClaims(sourceId);
  } catch (err) {
    claimStatusBox(`Extragerea nu a reușit: ${err.message}`, true);
  } finally {
    button.disabled = false;
  }
}

function claimStatusBox(message, isError) {
  const statusDiv = element('source-retrieve-status');
  statusDiv.hidden = false;
  statusDiv.className = isError ? 'dialog-status-msg text-error' : 'dialog-status-msg';
  statusDiv.textContent = message;
}

/** Ask a second agent to check the claim against its source. */
async function agentVerify(button, sourceId) {
  const claimId = button.getAttribute('data-claim-id');
  button.disabled = true;
  button.textContent = 'Se verifică…';
  claimStatusBox('Un al doilea agent citește sursa…', false);
  try {
    const result = await api(`/factual/claims/${claimId}/verify-with-agent`, {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID() }),
    });
    claimStatusBox(
      `Verdict: ${CLAIM_STATUS_LABEL[result.claim.status] || result.claim.status}.`,
      false,
    );
    await loadSources();
    await loadClaims(sourceId);
  } catch (err) {
    // A rejected verdict is the system working, not a malfunction: the claim stays unverified.
    claimStatusBox(err.message, true);
    button.disabled = false;
    button.textContent = 'Verifică cu un al doilea agent';
  }
}

/** Record the Owner's own judgement. The Owner is the final authority in this studio. */
async function submitOwnerVerdict(event, form, sourceId) {
  event.preventDefault();
  const claimId = form.getAttribute('data-claim-id');
  const data = new FormData(form);
  const submit = /** @type {HTMLButtonElement} */ (form.querySelector('button[type="submit"]'));
  submit.disabled = true;
  try {
    await api(`/factual/claims/${claimId}/verify`, {
      method: 'POST',
      body: JSON.stringify({
        command_id: crypto.randomUUID(),
        status: data.get('status'),
        confidence: 1.0,
        verifier_notes: String(data.get('notes') || '').trim(),
        evidence_text: String(data.get('evidence') || '').trim() || null,
      }),
    });
    claimStatusBox('Verdictul tău a fost înregistrat.', false);
    await loadSources();
    await loadClaims(sourceId);
  } catch (err) {
    claimStatusBox(err.message, true);
    submit.disabled = false;
  }
}

const sourceRetrieveForm = document.getElementById('source-retrieve-form');
if (sourceRetrieveForm) {
  sourceRetrieveForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const urlInput = /** @type {HTMLInputElement} */ (element('source-url'));
    const statusDiv = element('source-retrieve-status');
    const submit = /** @type {HTMLButtonElement} */ (
      sourceRetrieveForm.querySelector('button[type="submit"]')
    );

    statusDiv.hidden = false;
    statusDiv.className = 'dialog-status-msg';
    statusDiv.textContent = 'Se preia sursa…';
    submit.disabled = true;
    try {
      const result = await api('/factual/sources/retrieve', {
        method: 'POST',
        body: JSON.stringify({
          command_id: crypto.randomUUID(),
          url: urlInput.value,
        }),
      });
      const receipt = result.receipt || {};
      statusDiv.textContent = `Preluat: „${result.source.title}" — amprenta conținutului ${shortHash(receipt.content_sha256)}. Nimic nu este considerat adevărat până la verificare.`;
      urlInput.value = '';
      await loadSources();
    } catch (err) {
      statusDiv.textContent = err.message;
      statusDiv.className = 'dialog-status-msg text-error';
    } finally {
      submit.disabled = false;
    }
  });
}

/* ---------------------------------------------------------------------------
 * Scripts.
 *
 * The end of the Phase 4 chain. A draft is written only from claims a second agent confirmed
 * against their source, and approval re-runs the factual gate — so a script that passed once
 * cannot slip through later on claims that have since been refuted.
 * ------------------------------------------------------------------------- */

const SCRIPT_STATUS_LABEL = {
  DRAFT: 'Ciornă',
  VERIFIED_PASS: 'Trecut de poarta factuală',
  APPROVED: 'Aprobat',
  BLOCKED_UNVERIFIED_CLAIMS: 'Blocat — afirmații neverificate',
};

function scriptStatusBox(message, isError) {
  const box = element('script-status');
  box.hidden = false;
  box.className = isError ? 'dialog-status-msg text-error' : 'dialog-status-msg';
  box.textContent = message;
}

async function loadScripts() {
  const listEl = element('scripts-list');
  const picker = /** @type {HTMLSelectElement} */ (element('script-topic'));
  try {
    const [topicsData, scriptsData] = await Promise.all([
      api('/factual/topics'),
      api('/factual/scripts'),
    ]);

    const previous = picker.value;
    picker.replaceChildren();
    const topics = topicsData.topics || [];
    if (!topics.length) {
      picker.append(new Option('Propune întâi un subiect', ''));
    } else {
      picker.append(new Option('Alege subiectul…', ''));
      for (const topic of topics) picker.append(new Option(topic.title, topic.id));
      if (previous) picker.value = previous;
    }

    const scripts = scriptsData.scripts || [];
    if (!scripts.length) {
      listEl.innerHTML = '<div class="topics-loading">Niciun scenariu încă.</div>';
      return;
    }
    listEl.innerHTML = scripts.map(renderScript).join('');
    listEl.querySelectorAll('.btn-approve-script').forEach((btn) => {
      btn.addEventListener('click', () => approveScript(btn));
    });
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
  }
}

function renderScript(script) {
  const status = String(script.status || 'DRAFT');
  const blocked = status === 'BLOCKED_UNVERIFIED_CLAIMS';
  const scenes = (script.scenes_json || [])
    .map(
      (scene) => `
        <div class="scene-row">
          <div class="scene-narration">${escapeHtml(scene.narration || '')}</div>
          <div class="scene-meta">Scena ${scene.scene_number || '?'} · ${(scene.claim_ids || []).length} afirmații citate${scene.visual_description ? ` · ${escapeHtml(scene.visual_description)}` : ''}</div>
        </div>`,
    )
    .join('');

  return `
    <div class="topic-card script-card script-${escapeHtml(status.toLowerCase())}" data-script-id="${escapeHtml(script.id)}">
      <div class="topic-card-header">
        <strong class="topic-card-title">${escapeHtml(script.title)}</strong>
        <span class="topic-card-novelty">v${script.version} · ${escapeHtml(SCRIPT_STATUS_LABEL[status] || status)}</span>
      </div>
      <div class="topic-card-meta">
        <span>${script.target_duration_seconds}s</span>
        · <span>${(script.claim_ids_json || []).length} afirmații</span>
        · <span>${(script.scenes_json || []).length} scene</span>
      </div>
      ${blocked ? `<p class="helper-warn helper-note">Blocat: ${(script.unverified_claim_ids_json || []).length} afirmații citate nu sunt susținute de o sursă.</p>` : ''}
      <div class="script-scenes">${scenes}</div>
      ${status === 'VERIFIED_PASS' ? `<div class="source-actions"><button class="secondary btn-approve-script" data-script-id="${escapeHtml(script.id)}">Aprobă scenariul</button></div>` : ''}
    </div>`;
}

async function approveScript(button) {
  const scriptId = button.getAttribute('data-script-id');
  button.disabled = true;
  scriptStatusBox('Se re-verifică poarta factuală…', false);
  try {
    await api(`/factual/scripts/${scriptId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID() }),
    });
    scriptStatusBox('Scenariu aprobat. Apare acum în Producție media, gata de storyboard.', false);
    await loadScripts();
    await loadAwaitingStoryboard();
  } catch (err) {
    scriptStatusBox(err.message, true);
    button.disabled = false;
  }
}

const scriptWriteForm = document.getElementById('script-write-form');
if (scriptWriteForm) {
  scriptWriteForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const picker = /** @type {HTMLSelectElement} */ (element('script-topic'));
    const submit = /** @type {HTMLButtonElement} */ (
      scriptWriteForm.querySelector('button[type="submit"]')
    );
    if (!picker.value) {
      scriptStatusBox('Alege un subiect.', true);
      return;
    }
    submit.disabled = true;
    scriptStatusBox('Scenaristul scrie din afirmațiile verificate…', false);
    try {
      const result = await api('/factual/scripts/write-with-agent', {
        method: 'POST',
        body: JSON.stringify({
          command_id: crypto.randomUUID(),
          topic_id: picker.value,
        }),
      });
      const script = result.script;
      scriptStatusBox(
        `„${script.title}" — ${(script.scenes_json || []).length} scene, ${(script.claim_ids_json || []).length} afirmații citate.`,
        false,
      );
      await loadScripts();
    } catch (err) {
      scriptStatusBox(err.message, true);
    } finally {
      submit.disabled = false;
    }
  });
}

if (topicProposeForm) {
  topicProposeForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    const titleInput = /** @type {HTMLInputElement} */ (element('topic-title'));
    const subjectInput = /** @type {HTMLInputElement} */ (element('topic-subject'));
    const angleInput = /** @type {HTMLInputElement} */ (element('topic-angle'));
    const audienceInput = /** @type {HTMLInputElement} */ (element('topic-audience'));
    const statusDiv = element('topic-propose-status');

    statusDiv.hidden = false;
    statusDiv.textContent = 'Trimitere subiect spre analiză...';

    try {
      const payload = {
        command_id: crypto.randomUUID(),
        title: titleInput.value,
        topic: subjectInput.value,
        angle: angleInput.value,
        target_audience: audienceInput.value || 'general',
      };
      await api('/factual/topics', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      statusDiv.textContent = 'Subiect înregistrat cu succes!';
      statusDiv.className = 'dialog-status-msg';
      titleInput.value = '';
      subjectInput.value = '';
      angleInput.value = '';
      setTimeout(() => {
        statusDiv.hidden = true;
      }, 3000);
      await loadTopics();
      await refresh();
    } catch (err) {
      statusDiv.textContent = `Eroare: ${err.message}`;
      statusDiv.className = 'dialog-status-msg text-error';
    }
  });
}

// Phase 5: Media Production & Assembly Modal logic
const mediaModal = /** @type {HTMLDialogElement} */ (element('media-modal'));
const openMediaBtn = element('open-media-btn');
const closeMediaBtn = element('close-media-btn');
const tabStoryboardsBtn = element('tab-storyboards-btn');
const tabCharactersBtn = element('tab-characters-btn');
const mediaStoryboardsSection = element('media-storyboards-section');
const mediaCharactersSection = element('media-characters-section');
const generateDemoStoryboardBtn = element('generate-demo-storyboard-btn');
const refreshMediaBtn = element('refresh-media-btn');
const mediaStatusMsg = element('media-status-msg');

if (openMediaBtn) {
  openMediaBtn.addEventListener('click', () => {
    mediaModal.showModal();
    loadMediaProviderNote();
    loadAwaitingStoryboard();
    loadMediaStoryboards();
  });
}

if (closeMediaBtn) {
  closeMediaBtn.addEventListener('click', () => {
    mediaModal.close();
  });
}

if (tabStoryboardsBtn && tabCharactersBtn) {
  tabStoryboardsBtn.addEventListener('click', () => {
    tabStoryboardsBtn.classList.add('media-tab-active');
    tabCharactersBtn.classList.remove('media-tab-active');
    mediaStoryboardsSection.classList.remove('hidden');
    mediaCharactersSection.classList.add('hidden');
    loadMediaProviderNote();
    loadAwaitingStoryboard();
    loadMediaStoryboards();
  });

  tabCharactersBtn.addEventListener('click', () => {
    tabCharactersBtn.classList.add('media-tab-active');
    tabStoryboardsBtn.classList.remove('media-tab-active');
    mediaCharactersSection.classList.remove('hidden');
    mediaStoryboardsSection.classList.add('hidden');
    loadCharacterBibles();
  });
}

if (refreshMediaBtn) {
  refreshMediaBtn.addEventListener('click', () => {
    loadMediaProviderNote();
    loadAwaitingStoryboard();
    loadMediaStoryboards();
  });
}

/** One line of a bible entry, omitted entirely when the record does not carry it. */
function charRow(label, value) {
  const text = Array.isArray(value) ? value.filter(Boolean).join(' · ') : value;
  if (!text) return '';
  return `<div class="char-row"><span class="char-label">${escapeHtml(label)}</span>${escapeHtml(String(text))}</div>`;
}

/**
 * A Character Bible card. Every line shows what the record actually holds; a field the bible
 * has not been given is left out rather than filled with a plausible default, because the
 * bible is what the office renderer and the story engine read as canon.
 */
function characterCard(c) {
  const voice = c.voice_profile_json || {};
  const personality = c.personality_json || {};
  const speech = c.speech_style_json || {};
  const expressions = c.expressions_json || {};
  const behavior = c.behavior_json || {};
  const references = c.reference_assets_json || {};
  const slots = Object.keys(references);
  const present = slots.filter((slot) => references[slot]);
  const voiceLine = [voice.voice_id, voice.style, voice.speed ? `x${voice.speed}` : '']
    .filter(Boolean)
    .join(' · ');
  const greeting = expressions.greeting || expressions.agreement;
  return `
    <div class="character-card">
      <div class="char-header">
        <span class="char-name">${escapeHtml(c.canonical_name)}</span>
        ${c.role_symbols ? `<span class="char-archetype">${escapeHtml(String(c.role_symbols).split(',')[0])}</span>` : ''}
      </div>
      <p class="char-desc">${escapeHtml([c.face_hair_desc, c.outfit_desc].filter(Boolean).join(' '))}</p>
      ${charRow('Personalitate', personality.traits)}
      ${charRow('Vorbire', [speech.register, speech.cadence].filter(Boolean))}
      ${greeting ? `<div class="char-row"><span class="char-label">Expresie</span><em>„${escapeHtml(greeting)}”</em></div>` : ''}
      ${charRow('Comportament', behavior.work_rituals)}
      ${charRow('Nu devia', c.forbidden_deviations)}
      ${voiceLine ? `<div class="char-voice">Voce: ${escapeHtml(voiceLine)}</div>` : ''}
      ${identityLine(c)}
      ${slots.length ? `<div class="char-voice">Referințe vizuale: ${present.length}/${slots.length}${present.length ? '' : ' · niciuna produsă încă'}</div>` : ''}
    </div>
  `;
}

/** Persistent production identity: the bound voice, which fields are locked, and the status. */
function identityLine(c) {
  const binding = c.voice_binding_json || {};
  const locks = c.identity_locks_json || {};
  const lockedFields = Object.keys(locks).filter((k) => locks[k]);
  const parts = [];
  if (binding.voice_id) parts.push(`Voce legată: ${escapeHtml(binding.voice_id)}${binding.model_id ? ` · model ${escapeHtml(binding.model_id)}` : ''}`);
  if (lockedFields.length) parts.push(`Blocat: ${escapeHtml(lockedFields.join(', '))}`);
  if (c.consistency_status) parts.push(`Consistență: ${escapeHtml(c.consistency_status)}`);
  if ((c.approved_fallbacks_json || []).length) parts.push(`${c.approved_fallbacks_json.length} modele aprobate`);
  return parts.length ? `<div class="char-voice">${parts.join(' · ')}</div>` : '';
}

async function loadCharacterBibles() {
  const listEl = element('characters-list');
  try {
    const data = await api('/media/character-bible');
    const chars = data.characters || [];
    if (chars.length === 0) {
      listEl.innerHTML =
        '<div class="topics-loading">Niciun caracter înregistrat în Character Bible.</div>';
      return;
    }
    listEl.innerHTML = chars.map(characterCard).join('');
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">Eroare la încărcarea caracterelor: ${escapeHtml(err.message)}</div>`;
  }
}

/**
 * What a render would actually use right now.
 *
 * Stated before the Owner presses "Randare 9:16", not after: without a verified image provider
 * the output is placeholder content that QC will block, and finding that out from a failed QC
 * report is a worse way to learn it.
 */
async function loadMediaProviderNote() {
  const note = element('media-provider-note');
  try {
    const info = await api('/media/providers');
    if (info.renders_are_publishable) {
      const voice = info.voice_provider ? ` · voce: ${info.voice_provider}` : ' · voce: substitut';
      note.textContent = `Imagini: ${info.image_provider}${voice}. Randările pot fi publicate.`;
      note.className = 'helper-note';
    } else {
      note.textContent = info.note;
      note.className = 'helper-note helper-warn';
    }
  } catch (err) {
    note.textContent = err.message;
    note.className = 'helper-note text-error';
  }
}

/** Approved scripts that production has not picked up yet — the handover from research. */
async function loadAwaitingStoryboard() {
  const block = element('awaiting-storyboard');
  const listEl = element('awaiting-list');
  try {
    const data = await api('/media/scripts/awaiting-storyboard');
    const scripts = data.scripts || [];
    block.hidden = scripts.length === 0;
    if (!scripts.length) return;

    listEl.innerHTML = scripts
      .map(
        (script) => `
        <div class="topic-card script-card">
          <div class="topic-card-header">
            <strong class="topic-card-title">${escapeHtml(script.title)}</strong>
            <span class="topic-card-novelty">v${script.version}</span>
          </div>
          <div class="topic-card-meta">
            <span>${script.target_duration_seconds}s</span>
            · <span>${script.scene_count} scene</span>
            · <span>${script.claim_count} afirmații verificate</span>
          </div>
          <div class="source-actions">
            <button class="secondary btn-make-storyboard" data-script-id="${escapeHtml(script.id)}">Creează storyboard</button>
          </div>
        </div>`,
      )
      .join('');

    listEl.querySelectorAll('.btn-make-storyboard').forEach((btn) => {
      btn.addEventListener('click', () => makeStoryboard(btn));
    });
  } catch (err) {
    block.hidden = false;
    listEl.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
  }
}

async function makeStoryboard(button) {
  const scriptId = button.getAttribute('data-script-id');
  button.disabled = true;
  mediaStatusMsg.hidden = false;
  mediaStatusMsg.className = 'dialog-status-msg';
  mediaStatusMsg.textContent = 'Se construiește storyboard-ul din scenariul aprobat…';
  try {
    const storyboard = await api(`/media/storyboards/from-script/${scriptId}`, {
      method: 'POST',
      body: JSON.stringify({
        visual_style: 'MOTION_GRAPHIC',
        aspect_ratio: '9:16',
      }),
    });
    mediaStatusMsg.textContent = `Storyboard creat: „${storyboard.title}" — ${storyboard.total_scenes} scene.`;
    await loadAwaitingStoryboard();
    await loadMediaStoryboards();
  } catch (err) {
    // The factual gate runs again here; a refusal is the system working.
    mediaStatusMsg.className = 'dialog-status-msg text-error';
    mediaStatusMsg.textContent = err.message;
    button.disabled = false;
  }
}

async function loadMediaStoryboards() {
  const listEl = element('storyboards-list');
  try {
    const data = await api('/media/storyboards');
    const storyboards = data.storyboards || [];
    if (storyboards.length === 0) {
      listEl.innerHTML = `
        <div class="topics-loading">
          Niciun storyboard disponibil în pipeline.
          <br>Apasă pe "Creează Storyboard Demonstrativ" pentru a genera automat un scenariu 9:16 verificat.
        </div>
      `;
      return;
    }

    const itemsHtml = await Promise.all(
      storyboards.map(async (sb) => {
        let scenes = [];
        let qcReport = null;
        try {
          const detail = await api(`/media/storyboards/${sb.id}`);
          scenes = detail.scenes || [];
        } catch (_) {}

        if (sb.status === 'RENDERED') {
          try {
            qcReport = await api(`/media/qc/${sb.id}`);
          } catch (_) {}
        }

        const scenesHtml = scenes
          .map(
            (s) => `
        <div class="scene-card">
          <div class="scene-card-header">
            <span class="scene-badge">Scena #${s.scene_index}</span>
            <span class="scene-duration">${s.duration_seconds}s</span>
          </div>
          <div class="scene-shot">${escapeHtml(s.shot_type)} · ${escapeHtml(s.visual_type)}</div>
          <p class="scene-prompt">${escapeHtml(s.visual_prompt)}</p>
          <p class="scene-audio">" ${escapeHtml(s.voiceover_segment)} "</p>
        </div>
      `,
          )
          .join('');

        let renderHtml = '';
        if (sb.status === 'RENDERED') {
          const qcPassed = qcReport && qcReport.status === 'PASSED';
          const qcBadge = qcReport
            ? `<span class="${qcPassed ? 'qc-badge-pass' : 'qc-badge-fail'}">QC: ${escapeHtml(qcReport.status)}</span>`
            : '<span class="tag">QC: Neefectuat</span>';

          const checks = qcReport ? qcReport.checks_json || {} : {};
          const techPassed = Boolean(checks.technical_qc && checks.technical_qc.passed);
          const factualPassed = Boolean(checks.factual_qc && checks.factual_qc.passed);
          // null means "not implemented"; it is deliberately not coerced to false.
          const charDrift = checks.character_drift_qc ? checks.character_drift_qc.passed : null;
          const rightsPassed = Boolean(checks.rights_qc && checks.rights_qc.passed);

          // A check that was never implemented must not be scored: an em dash says
          // "not evaluated", whereas 0% would claim a failed measurement.
          const scoreCell = (label, passed) => {
            const value = passed === null || passed === undefined ? '—' : passed ? '100%' : '0%';
            return `<div class="qc-score-item"><div>${label}</div><div class="qc-score-num">${value}</div></div>`;
          };
          const tech = checks.technical_qc || {};
          const qcScoresHtml = qcReport
            ? `
          <div class="qc-scores-grid">
            ${scoreCell('Tehnic', techPassed)}
            ${scoreCell('Factual', factualPassed)}
            ${scoreCell('Continuitate', charDrift)}
            ${scoreCell('Drepturi', rightsPassed)}
          </div>
        `
            : '';

          renderHtml = `
          <div class="video-preview-card">
            <div class="video-container-9-16">
              <div class="tag">9:16 Video</div>
            </div>
            <div class="video-details">
              <div><strong>Format măsurat:</strong> ${
                tech.measured_width
                  ? `${tech.measured_width}x${tech.measured_height} · ${tech.measured_duration_seconds}s · ${escapeHtml(String(tech.video_codec || '—'))}`
                  : 'nemăsurat'
              }</div>
              <div>${qcBadge}</div>
              ${qcScoresHtml}
              <div><strong>Amprentă SHA-256 a fișierului:</strong></div>
              <div class="provenance-badge">${escapeHtml(tech.provenance_sha256 || 'indisponibilă')}</div>
            </div>
          </div>
        `;
        }

        return `
        <div class="storyboard-card" data-id="${sb.id}">
          <div class="storyboard-header">
            <div>
              <h4 class="storyboard-title">${escapeHtml(sb.title)}</h4>
              <div class="storyboard-meta">
                <span>Aspect: <strong>9:16</strong></span>
                <span>Scene: <strong>${scenes.length}</strong></span>
                <span>Status: <strong class="text-accent">${escapeHtml(sb.status)}</strong></span>
              </div>
            </div>
            <div class="storyboard-actions">
              <button class="btn-render-video" data-id="${sb.id}">Randare 9:16</button>
              <button class="btn-qc-video" data-id="${sb.id}">Verifică QC</button>
            </div>
          </div>

          <div class="storyboard-scenes-grid">
            ${scenesHtml}
          </div>

          ${renderHtml}
        </div>
      `;
      }),
    );

    listEl.innerHTML = itemsHtml.join('');

    listEl.querySelectorAll('.btn-render-video').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        if (!id) return;
        btn.textContent = 'Randare în curs...';
        // @ts-ignore
        btn.disabled = true;
        try {
          await api(`/media/render/${id}`, { method: 'POST' });
          await loadMediaStoryboards();
          await refresh();
        } catch (err) {
          alert(`Eroare la randare: ${err.message}`);
          btn.textContent = 'Randare 9:16';
          // @ts-ignore
          btn.disabled = false;
        }
      });
    });

    listEl.querySelectorAll('.btn-qc-video').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        if (!id) return;
        btn.textContent = 'Evaluare QC...';
        // @ts-ignore
        btn.disabled = true;
        try {
          await api(`/media/qc/${id}`, { method: 'POST' });
          await loadMediaStoryboards();
          await refresh();
        } catch (err) {
          alert(`Eroare la QC: ${err.message}`);
          btn.textContent = 'Verifică QC';
          // @ts-ignore
          btn.disabled = false;
        }
      });
    });
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">Eroare la încărcarea producției media: ${escapeHtml(err.message)}</div>`;
  }
}

if (generateDemoStoryboardBtn) {
  generateDemoStoryboardBtn.addEventListener('click', async () => {
    mediaStatusMsg.hidden = false;
    mediaStatusMsg.className = 'dialog-status-msg';
    mediaStatusMsg.textContent =
      'Creare fixture demo (topic, scenariu și afirmație NEVERIFICATĂ)...';
    try {
      const fixture = await api('/media/storyboards/demo-fixture', {
        method: 'POST',
      });
      mediaStatusMsg.textContent =
        fixture.next_step || 'Fixture creat. Verifică afirmațiile în panoul Cercetare.';
      setTimeout(() => {
        mediaStatusMsg.hidden = true;
      }, 8000);
      await loadMediaStoryboards();
      await refresh();
    } catch (err) {
      mediaStatusMsg.className = 'dialog-status-msg text-error';
      mediaStatusMsg.textContent = `Eroare: ${err.message}`;
    }
  });
}

// Phase 6: Autonomous Publishing & Distribution Modal logic
const publishingModal = /** @type {HTMLDialogElement} */ (element('publishing-modal'));
const openPublishingBtn = element('open-publishing-btn');
const closePublishingBtn = element('close-publishing-btn');
const refreshPublishingBtn = element('refresh-publishing-btn');
const triggerQuickPublishBtn = element('trigger-quick-publish-btn');
const publishingStatusMsg = element('publishing-status-msg');
bindPanelToggle('open-media-btn', mediaModal);
bindPanelToggle('open-publishing-btn', publishingModal);
const publisherBanner = document.getElementById('publisher-config-banner');

const CHANNEL_STATUS_LABEL = {
  NOT_CONFIGURED: 'NECONFIGURAT',
  AUTH_REQUIRED: 'NEAUTENTIFICAT',
  AUTHENTICATED: 'AUTENTIFICAT',
};

const CHANNEL_STATUS_HINT = {
  NOT_CONFIGURED: 'Slot de canal. Nu are ID real de canal YouTube și nu poate publica.',
  AUTH_REQUIRED: 'ID de canal setat, dar fără credențiale verificate. Nu poate publica.',
  AUTHENTICATED: 'ID de canal și credențiale prezente.',
};

if (openPublishingBtn) {
  openPublishingBtn.addEventListener('click', () => {
    publishingModal.showModal();
    loadPublishingHub();
  });
}

if (closePublishingBtn) {
  closePublishingBtn.addEventListener('click', () => {
    publishingModal.close();
  });
}

const budgetForm = document.getElementById('budget-form');
if (budgetForm) {
  budgetForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    const status = element('budget-status');
    status.hidden = false;
    status.className = 'dialog-status-msg';
    try {
      const result = await api('/economy/budget', {
        method: 'PUT',
        body: JSON.stringify({
          period: /** @type {HTMLSelectElement} */ (element('budget-period')).value,
          limit_usd: /** @type {HTMLInputElement} */ (element('budget-limit')).value.trim(),
        }),
      });
      status.textContent = result.active === false ? 'Bugetul a fost retras.' : `Buget ${result.period === 'DAILY' ? 'zilnic' : 'lunar'} de ${result.limit_usd} USD stabilit.`;
      await loadBudget();
    } catch (error) {
      status.className = 'dialog-status-msg text-error';
      status.textContent = error instanceof Error ? error.message : 'Bugetul nu a putut fi salvat.';
    }
  });
}
const closeBooksBtn = document.getElementById('close-books-btn');
if (closeBooksBtn) {
  closeBooksBtn.addEventListener('click', async () => {
    const status = element('budget-status');
    status.hidden = false;
    status.className = 'dialog-status-msg';
    status.textContent = 'Contabilul închide ziua…';
    try {
      const result = await api('/economy/books/close', { method: 'POST' });
      status.textContent = `${result.headline}. ${result.report ? result.report.summary : result.blocked || ''}`;
      await loadBudget();
    } catch (error) {
      status.className = 'dialog-status-msg text-error';
      status.textContent = error instanceof Error ? error.message : 'Închiderea a eșuat.';
    }
  });
}

if (refreshPublishingBtn) {
  refreshPublishingBtn.addEventListener('click', loadPublishingHub);
}

/** Labels for the stored production policy; the value itself lives on the channel row. */
const PRODUCTION_POLICY_LABEL = {
  FLEXIBLE: 'FLEXIBILĂ · tehnologia se alege per video',
  CONSISTENCY_LOCKED: 'CONSISTENȚĂ BLOCATĂ · identitatea personajelor nu se schimbă',
};

async function loadPublishingHub() {
  const channelsEl = element('channels-list');
  const pubListEl = element('publications-list');

  try {
    const [chData, pubData] = await Promise.all([
      api('/publishing/channels'),
      api('/publishing/publications'),
    ]);

    const channels = chData.channels || [];
    const accounts = (chData.youtube_accounts || []).filter((a) => a.status === 'CONNECTED');
    if (publisherBanner) {
      if (chData.binding_hint) {
        publisherBanner.className = 'dialog-status-msg text-error';
        publisherBanner.textContent = chData.binding_hint;
      } else if (chData.publisher_configured) {
        publisherBanner.className = 'dialog-status-msg';
        publisherBanner.textContent =
          'Credențiale YouTube prezente. Publicarea folosește API-ul oficial.';
      } else {
        publisherBanner.className = 'dialog-status-msg text-error';
        publisherBanner.textContent =
          'Nicio credențială YouTube configurată: publicarea este dezactivată. Setează STUDIO_YOUTUBE_CLIENT_ID, STUDIO_YOUTUBE_CLIENT_SECRET și STUDIO_YOUTUBE_REFRESH_TOKEN în .env. Studioul nu simulează publicări.';
      }
      publisherBanner.hidden = false;
    }
    if (channels.length === 0) {
      channelsEl.innerHTML =
        '<div class="topics-loading">Niciun canal de distribuție configurat.</div>';
    } else {
      channelsEl.innerHTML = channels
        .map(
          (c) => `
        <div class="channel-item">
          <div class="channel-info">
            <h4>${escapeHtml(c.channel_name)}</h4>
            <div class="channel-meta">Tip: <strong>${escapeHtml(c.channel_type)}</strong> · ID la distanță: <code>${escapeHtml(c.remote_channel_id || 'nesetat')}</code></div>
            <div class="channel-meta">${escapeHtml(CHANNEL_STATUS_HINT[c.status] || 'Stare necunoscută.')}</div>
            <div class="channel-meta">Politică de producție: <span class="policy-tag ${c.production_policy === 'CONSISTENCY_LOCKED' ? 'policy-locked' : 'policy-flexible'}">${escapeHtml(PRODUCTION_POLICY_LABEL[c.production_policy] || 'nesetată')}</span>${c.allow_production_override === false ? ' · suprascrieri per episod dezactivate' : ''}</div>
          </div>
          <div class="channel-meta channel-bind">
            <label>Cont YouTube
              <select data-bind-select="${escapeHtml(c.id)}" aria-label="Cont YouTube pentru ${escapeHtml(c.channel_name)}">
                <option value="">Nelegat</option>
                ${accounts.map((a) => `<option value="${escapeHtml(a.id)}" ${a.id === c.youtube_connection_id ? 'selected' : ''}>${escapeHtml(a.name)}${a.channel_title ? ` · ${escapeHtml(a.channel_title)}` : ''}</option>`).join('')}
              </select>
            </label>
            <button class="secondary" data-bind-channel="${escapeHtml(c.id)}" data-event="${escapeHtml(c.event_id || '')}">Leagă</button>
            <span class="helper">${c.publisher_ready ? `Publică pe ${escapeHtml(c.youtube_channel_title || c.youtube_connection_name || '')}` : 'Fără legătură, acest slot nu publică și nu are analytics.'}</span>
          </div>
        </div>
        <span class="channel-status-tag ${c.status === 'AUTHENTICATED' ? 'channel-status-ok' : 'channel-status-warn'}">${escapeHtml(CHANNEL_STATUS_LABEL[c.status] || c.status)}</span>
      </div>
    `,
        )
        .join('');
      // Binding is what tells publishing and analytics which account a slot belongs to;
      // without it the studio refuses rather than guess between two connected channels.
      channelsEl.querySelectorAll('[data-bind-channel]').forEach((button) => {
        button.addEventListener('click', async () => {
          const id = /** @type {HTMLElement} */ (button).dataset.bindChannel;
          const select = /** @type {HTMLSelectElement} */ (
            channelsEl.querySelector(`[data-bind-select="${id}"]`)
          );
          const expected = /** @type {HTMLElement} */ (button).dataset.event || null;
          try {
            await api(`/settings/channels/${id}`, {
              method: 'PUT',
              body: JSON.stringify({ connection_id: select.value || null, expected_event_id: expected }),
            });
            await loadPublishingHub();
          } catch (err) {
            publishingStatusMsg.hidden = false;
            publishingStatusMsg.className = 'dialog-status-msg text-error';
            publishingStatusMsg.textContent = err instanceof Error ? err.message : 'Legarea a eșuat.';
          }
        });
      });
    }

    const publications = pubData.publications || [];
    if (publications.length === 0) {
      pubListEl.innerHTML =
        '<div class="topics-loading">Nicio publicație înregistrată încă. Folosește butonul de mai sus pentru a publica un video aprobat.</div>';
    } else {
      pubListEl.innerHTML = publications
        .map((p) => {
          const isSimulated = p.status === 'PUBLISHED_SIMULATED';
          const isPub = p.status === 'PUBLISHED';
          const badgeClass = isPub
            ? 'pub-status-published'
            : p.status === 'VALIDATED'
              ? 'pub-status-validated'
              : 'pub-status-blocked';
          // Only a real platform URL becomes a link. A simulated upload has no address.
          const isRealYoutubeUrl =
            typeof p.remote_url === 'string' &&
            /^https:\/\/(www\.)?youtube\.com\//.test(p.remote_url);
          const remoteLink =
            !isSimulated && isRealYoutubeUrl
              ? `<a href="${escapeHtml(p.remote_url)}" target="_blank" rel="noopener" class="pub-remote-link">Vezi pe YouTube</a>`
              : isSimulated
                ? '<span class="pub-sim-note">Simulare locală — niciun video pe YouTube</span>'
                : '';
          const privacyBadge =
            p.privacy_status === 'private'
              ? '<span class="privacy-badge privacy-badge-private">Privat</span>'
              : '<span class="privacy-badge privacy-badge-public">Public</span>';

          return `
          <div class="pub-item-card">
            <div class="pub-item-details">
              <h4>${escapeHtml(p.title)}</h4>
              <div class="pub-item-meta">
                <span>Stare: <strong class="pub-status-badge ${isSimulated ? 'pub-status-simulated' : badgeClass}">${escapeHtml(isSimulated ? 'SIMULAT (nepublicat)' : p.status)}</strong></span>
                ${privacyBadge}
                <span>ID la distanță: <code>${escapeHtml(p.remote_video_id || '—')}</code></span>
                <span>Data: ${new Date(p.created_at).toLocaleString('ro-RO')}</span>
              </div>
            </div>
            <div>
              ${remoteLink}
            </div>
          </div>
        `;
        })
        .join('');
    }
  } catch (err) {
    if (channelsEl)
      channelsEl.innerHTML = `<div class="text-error">Eroare canale: ${escapeHtml(err.message)}</div>`;
    if (pubListEl)
      pubListEl.innerHTML = `<div class="text-error">Eroare publicații: ${escapeHtml(err.message)}</div>`;
  }
}

if (triggerQuickPublishBtn) {
  triggerQuickPublishBtn.addEventListener('click', async () => {
    publishingStatusMsg.hidden = false;
    publishingStatusMsg.className = 'dialog-status-msg';
    publishingStatusMsg.textContent =
      'Verificare pipeline media și identificare cel mai recent video aprobat QC...';
    try {
      // Find a storyboard with an assembled and QC passed video via /media/qc/{sb.id}
      const sbData = await api('/media/storyboards');
      const storyboards = sbData.storyboards || [];
      let targetAssetId = null;

      for (const sb of storyboards) {
        try {
          const qc = await api(`/media/qc/${sb.id}`);
          if (qc && qc.status === 'PASSED' && qc.media_asset_id) {
            targetAssetId = qc.media_asset_id;
            break;
          }
        } catch (_) {}
      }

      if (!targetAssetId) {
        publishingStatusMsg.className = 'dialog-status-msg text-error';
        publishingStatusMsg.textContent =
          'Nu a fost găsit niciun video cu raport QC PASSED. Generează mai întâi un storyboard și randare 9:16 din panoul Producție Media!';
        return;
      }

      publishingStatusMsg.textContent = `Validare Content Gate și încărcare privată pentru MediaAsset ${targetAssetId}...`;
      const pubRes = await api(`/publishing/publish-asset/${targetAssetId}`, {
        method: 'POST',
      });

      if (pubRes.status === 'PUBLISHED') {
        publishingStatusMsg.className = 'dialog-status-msg';
        publishingStatusMsg.textContent = `Video încărcat privat pe YouTube. ID la distanță: ${pubRes.remote_video_id}`;
      } else if (pubRes.status === 'PUBLISHED_SIMULATED') {
        publishingStatusMsg.className = 'dialog-status-msg text-error';
        publishingStatusMsg.textContent =
          'Încărcare SIMULATĂ: nu există niciun video pe YouTube. Configurează credențialele reale.';
      } else {
        publishingStatusMsg.className = 'dialog-status-msg text-error';
        publishingStatusMsg.textContent = `Publicare neterminată. Stare: ${pubRes.status}. ${pubRes.error_detail || ''}`;
      }
      await loadPublishingHub();
      await refresh();
    } catch (err) {
      publishingStatusMsg.className = 'dialog-status-msg text-error';
      publishingStatusMsg.textContent = `Eroare publicare: ${err.message}`;
    }
  });
}

function render(data) {
  element('studio-name').textContent = data.studio.name;
  element('connection').textContent = 'Conectat · Owner';
  element('office-status').textContent = 'Live Renderer 60fps';
  element('room-caption').textContent = `${data.office.rooms.length} cameră · Studioul 2D Activ`;
  element('snapshot-time').textContent =
    `Actualizat ${new Date(data.captured_at).toLocaleTimeString('ro-RO', { timeZone: data.studio.timezone })}`;
  renderSwitch(data.policy.autonomy_stopped);
  ledger.timezone = data.studio.timezone;
  ledger.setNames(Object.fromEntries(officeState.agents.map((a) => [a.id || a.agent_id, a.display_name])));
  ledger.add(data.events || []);
  element('ledger-count').textContent = `${ledger.events.size} înregistrări`;

  const labels = {
    agents: 'Agenți',
    providers: 'Furnizori AI',
    workflows: 'Automatizare',
    research: 'Cercetare factuală',
    media: 'Producție media',
    publishing: 'Publicare',
    story: 'Office Serial',
    treasury: 'Trezorerie VR$',
    procurement: 'VendorShop',
    financing: 'Finanțare',
  };
  const modules = element('modules');
  modules.replaceChildren();
  for (const [name, status] of Object.entries(data.modules)) {
    const item = document.createElement('li');
    item.textContent = labels[name] || name;
    const badge = document.createElement('span');
    badge.textContent = status === 'NOT_IMPLEMENTED' ? 'Neimplementat' : String(status);
    item.append(badge);
    modules.append(item);
  }
}

/**
 * The autonomy switch in the office frame: one control, ON or OFF, in the scene's chrome.
 * OFF is the persistent stop the Owner sets; ON means the studio may work on its own.
 */
function renderSwitch(stopped) {
  const on = !stopped;
  stopButton.classList.toggle('is-on', on);
  stopButton.classList.toggle('is-pending', Boolean(pendingCommand));
  element('switch-state').textContent = pendingCommand ? '…' : on ? 'ON' : 'OFF';
  stopButton.setAttribute('aria-pressed', String(on));
  stopButton.title = pendingCommand
    ? 'Ultima comandă nu a fost confirmată; apasă pentru a o reverifica.'
    : on
      ? 'Autonomia este pornită. Apasă pentru oprire persistentă.'
      : 'Autonomia este oprită. Apasă pentru a o porni; modul rămâne Manual.';
}

async function refresh() {
  const generation = epoch;
  try {
    const incoming = await api('/snapshot');
    if (generation !== epoch) return false;
    state = acceptSnapshot(state, incoming);
    if (!connected) notify('');
    connected = true;
    render(state);
    stopButton.disabled = busy;
    // Everything recorded since the ledger last looked, not only the twenty in the snapshot.
    try {
      await ledger.sync(api, state.cursor);
      element('ledger-count').textContent = `${ledger.events.size} înregistrări`;
    } catch (error) {
      console.warn('ledger sync failed', error);
    }
    return true;
  } catch (error) {
    if (generation !== epoch) return false;
    connected = false;
    element('connection').textContent = 'Deconectat';
    element('office-status').textContent = 'Date neactualizate';
    stopButton.disabled = true;
    notify(error.message);
    return false;
  }
}

element('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (busy) return;
  busy = true;
  ownerToken = input.value;
  epoch++;
  state = null;
  notify('');
  const success = await refresh();
  if (success) {
    login.hidden = true;
    workspace.hidden = false;
    element('logout').hidden = false;
    input.value = '';
    initOffice();
    await loadOfficeLayout();
    connectWebSocket();
  } else {
    ownerToken = '';
  }
  busy = false;
  stopButton.disabled = !connected;
});

element('logout').addEventListener('click', () => {
  inspectorRequest++;
  inspector.close();
  currentSelectedAgent=null;
  settingsUI.reset();
  epoch++;
  ownerToken = '';
  state = null;
  pendingCommand = null;
  connected = false;
  busy = false;
  if (socket) {
    socket.close();
    socket = null;
  }
  workspace.hidden = true;
  login.hidden = false;
  input.value = '';
  notify('');
  ledger.clear();
  element('modules').replaceChildren();
  element('studio-name').textContent = 'AMN-AI';
  element('connection').textContent = 'Neconectat';
  element('logout').hidden = true;
});

stopButton.addEventListener('click', async () => {
  if (busy || !connected || !state) return;
  busy = true;
  stopButton.disabled = true;
  notify('');
  const generation = epoch;
  pendingCommand ||= {
    schema_version: 1,
    command_id: crypto.randomUUID(),
    expected_version: state.policy.version,
    stopped: !state.policy.autonomy_stopped,
  };
  try {
    await api('/owner/autonomy-stop', {
      method: 'POST',
      body: JSON.stringify(pendingCommand),
    });
    if (generation !== epoch) return;
    pendingCommand = null;
  } catch (error) {
    if (generation !== epoch) return;
    if (error.status === 409 || error.status === 422) pendingCommand = null;
    notify(error.message);
  } finally {
    if (generation === epoch) {
      busy = false;
      await refresh();
    }
  }
});

async function poll() {
  if (ownerToken && !busy && !workspace.hidden && !document.hidden) {
    busy = true;
    await refresh();
    busy = false;
    stopButton.disabled = !connected;
  }
  setTimeout(poll, 5000);
}
setTimeout(poll, 5000);

/* ---------------------------------------------------------------------------
 * Phase 8: workforce.
 *
 * The most consequential thing the studio can recommend, so the panel shows the numbers a
 * proposal was built from rather than only its conclusion. Every figure here was counted from
 * the studio's own runs and queue; nothing is an opinion about an employee. Approving is the
 * Owner's act — the studio never carries out a staffing change on its own.
 * ------------------------------------------------------------------------- */

const workforceModal = /** @type {HTMLDialogElement} */ (element('workforce-modal'));
const openWorkforceBtn = element('open-workforce-btn');

const PROPOSAL_TYPE_LABEL = {
  SUSPEND_AGENT: 'Suspendare',
  TERMINATE_AGENT: 'Încetare',
  HIRE_ROLE: 'Angajare',
  REASSIGN_AGENT: 'Realocare',
};

function workforceStatus(message, isError) {
  const box = element('workforce-status');
  box.hidden = false;
  box.className = isError ? 'dialog-status-msg text-error' : 'dialog-status-msg';
  box.textContent = message;
}

/** A failure rate over no runs is unknown, not zero — and the panel has to say so. */
function rateLabel(agent) {
  if (agent.runs === 0) return 'nicio rulare în fereastră';
  return `${agent.runs} rulări · ${Math.round(agent.failure_rate * 100)}% eșecuri`;
}

async function loadWorkforce() {
  const summaryEl = element('workforce-summary');
  const agentsEl = element('workforce-agents');
  try {
    const data = await api('/workforce/measurements');
    summaryEl.innerHTML = `
      <div class="wf-stat"><span class="wf-stat-value">${data.active_agents}</span><span class="wf-stat-label">agenți activi</span></div>
      <div class="wf-stat"><span class="wf-stat-value">${data.queue_backlog}</span><span class="wf-stat-label">sarcini în coadă</span></div>
      <div class="wf-stat"><span class="wf-stat-value">${data.dead_letter_tasks}</span><span class="wf-stat-label">sarcini abandonate</span></div>
      <div class="wf-stat"><span class="wf-stat-value">${data.idle_agents.length}</span><span class="wf-stat-label">fără nicio rulare</span></div>`;
    summaryEl.insertAdjacentHTML(
      'beforeend',
      `<p class="helper-note wf-window">Măsurat pe ultimele ${data.window_days} de zile, din rulările înregistrate.</p>`,
    );

    agentsEl.innerHTML = (data.agents || [])
      .map(
        (agent) => `
        <div class="topic-card wf-agent-card">
          <div class="topic-card-header">
            <strong class="topic-card-title">${escapeHtml(agent.display_name)}</strong>
            <span class="topic-card-novelty">${escapeHtml(agent.lifecycle)}</span>
          </div>
          <div class="topic-card-meta">
            <span>${escapeHtml(agent.role_name)}</span> · <span>${escapeHtml(rateLabel(agent))}</span>
          </div>
        </div>`,
      )
      .join('');
  } catch (err) {
    summaryEl.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
  }
}

async function loadProposals() {
  const listEl = element('workforce-proposals');
  try {
    const data = await api('/workforce/proposals');
    const proposals = data.proposals || [];
    if (!proposals.length) {
      listEl.innerHTML =
        '<div class="topics-loading">Nicio propunere. Măsurătorile nu susțin o schimbare de personal acum.</div>';
      return;
    }
    listEl.innerHTML = proposals.map(renderProposal).join('');
    listEl.querySelectorAll('.btn-decide').forEach((btn) => {
      btn.addEventListener('click', () => decideProposal(btn));
    });
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
  }
}

function renderProposal(proposal) {
  const open = proposal.status === 'PROPOSED';
  // The evidence is shown, not summarised away: a staffing decision has to be checkable.
  const evidence = Object.entries(proposal.evidence || {})
    .filter(([, value]) => typeof value !== 'object')
    .map(
      ([key, value]) =>
        `<span>${escapeHtml(key)}: <strong>${escapeHtml(String(value))}</strong></span>`,
    )
    .join(' · ');

  return `
    <div class="topic-card wf-proposal wf-${escapeHtml(String(proposal.status).toLowerCase())}" data-id="${escapeHtml(proposal.id)}">
      <div class="topic-card-header">
        <strong class="topic-card-title">${escapeHtml(PROPOSAL_TYPE_LABEL[proposal.proposal_type] || proposal.proposal_type)}</strong>
        <span class="topic-card-novelty">${escapeHtml(proposal.status)}</span>
      </div>
      <p class="topic-card-subject">${escapeHtml(proposal.summary)}</p>
      <div class="wf-evidence">${evidence}</div>
      ${proposal.decision_notes ? `<div class="claim-notes">${escapeHtml(proposal.decision_notes)}</div>` : ''}
      ${
        open
          ? `<div class="source-actions">
               <input class="wf-notes" placeholder="Motiv (obligatoriu la respingere)" maxlength="2000" />
               <button class="secondary btn-decide" data-id="${escapeHtml(proposal.id)}" data-approve="true">Aprobă</button>
               <button class="quiet btn-decide" data-id="${escapeHtml(proposal.id)}" data-approve="false">Respinge</button>
             </div>`
          : ''
      }
    </div>`;
}

async function decideProposal(button) {
  const id = button.getAttribute('data-id');
  const approve = button.getAttribute('data-approve') === 'true';
  const card = button.closest('.wf-proposal');
  const notes = /** @type {HTMLInputElement | null} */ (card?.querySelector('.wf-notes'));
  const reason = notes ? notes.value.trim() : '';
  if (!approve && !reason) {
    workforceStatus('Scrie de ce respingi propunerea; motivul rămâne în istoric.', true);
    return;
  }
  card?.querySelectorAll('button').forEach((b) => {
    /** @type {HTMLButtonElement} */ (b).disabled = true;
  });
  try {
    const result = await api(`/workforce/proposals/${id}/decide`, {
      method: 'POST',
      body: JSON.stringify({
        command_id: crypto.randomUUID(),
        approve,
        notes: reason,
      }),
    });
    workforceStatus(
      approve
        ? `Aprobat și aplicat: ${PROPOSAL_TYPE_LABEL[result.proposal_type] || result.proposal_type}.`
        : 'Propunere respinsă; motivul a fost înregistrat.',
      false,
    );
    await loadWorkforce();
    await loadProposals();
    await loadOfficeLayout();
  } catch (err) {
    // A hire is approved but carried out in Settings; that refusal is informative, not a fault.
    workforceStatus(err.message, true);
    await loadProposals();
  }
}

if (openWorkforceBtn) {
  openWorkforceBtn.addEventListener('click', () => {
    workforceModal.showModal();
    loadWorkforce();
    loadProposals();
  });
}
element('close-workforce-btn').addEventListener('click', () => workforceModal.close());
element('refresh-workforce-btn').addEventListener('click', () => {
  loadWorkforce();
  loadProposals();
});
element('generate-proposals-btn').addEventListener('click', async () => {
  workforceStatus('Se recitesc măsurătorile…', false);
  try {
    const result = await api('/workforce/proposals/generate', {
      method: 'POST',
    });
    workforceStatus(result.message, false);
    await loadProposals();
  } catch (err) {
    workforceStatus(err.message, true);
  }
});
bindPanelToggle('open-workforce-btn', workforceModal);

/* ---------------------------------------------------------------------------
 * Phase 9: the daily log and the Office Serial.
 *
 * Two layers, kept visibly apart. A log is what the event stream contained — counted, never
 * narrated. An episode is a dramatisation of one log, and each beat shows how many real events
 * it cites, because that citation is the only thing separating a serial about this studio from
 * a serial about an imaginary one.
 * ------------------------------------------------------------------------- */

/* ---------------------------------------------------------------------------
 * Phase 11: the VR$ treasury.
 *
 * The panel's whole job is to keep four kinds of number apart, because adding them together is
 * exactly how a virtual company starts believing it is richer than it is:
 *
 *   VR VIRTUAL   what the ledger actually holds, and the only thing that could ever be spent
 *   PENDING      earned outside, not settled — reported, never spendable
 *   FORECAST     an estimate — reported, never spendable
 *   ESTIMAT      a provider cost that has not become an invoice yet
 *
 * Every figure below is rendered from the backend's own labels rather than from a guess made
 * here, so the page cannot quietly promote a forecast into cash.
 * ------------------------------------------------------------------------- */

const treasuryModal = /** @type {HTMLDialogElement} */ (element('treasury-modal'));
const openTreasuryBtn = element('open-treasury-btn');

const MONEY_CLASS_LABEL = {
  VR_CASH: 'Numerar VR$ (cheltuibil)',
  VR_RESTRICTED: 'Rezervat',
  VR_RECEIVABLE: 'De încasat',
  VR_DEBT: 'Datorie',
  PENDING_EXTERNAL: 'Încasat, nedecontat',
  FORECAST: 'Estimare',
};

const LEDGER_KIND_LABEL = {
  MINT: 'Emisiune VR$',
  REVERSAL: 'Stornare',
  OWNER_CAPITAL: 'Aport Owner',
  OWNER_LOAN: 'Împrumut Owner',
  PROVIDER_COST: 'Cost furnizor',
  ADJUSTMENT: 'Ajustare',
};

/** One figure with the label the backend gave it, so nothing is re-classified on the way out. */
function treasuryTile(row, extraClass = '') {
  const tile = document.createElement('div');
  tile.className = `wf-stat treasury-tile ${extraClass}`.trim();
  const value = document.createElement('span');
  value.className = 'wf-stat-value';
  value.textContent = `${row.amount} VR$`;
  const label = document.createElement('span');
  label.className = 'wf-stat-label';
  label.textContent = MONEY_CLASS_LABEL[row.money_class] || row.money_class;
  const badge = document.createElement('span');
  badge.className = row.spendable ? 'tag live-badge' : 'tag';
  badge.textContent = row.spendable ? `${row.label} · CHELTUIBIL` : `${row.label} · NECHELTUIBIL`;
  tile.append(value, label, badge);
  return tile;
}

function budgetCard(period) {
  const label = period.period === 'DAILY' ? 'Zilnic' : 'Lunar';
  return `<div class="budget-card budget-${escapeHtml(period.state)}"><span class="stat-label">${escapeHtml(label)} · ${escapeHtml(period.state)}</span><strong>${escapeHtml(period.spent_usd)} / ${escapeHtml(period.limit_usd)} USD</strong><span>rămas ${escapeHtml(period.remaining_usd)} USD · ${Math.round(period.ratio * 100)}%</span>${period.unpriced_agent_runs ? `<div class="helper">${period.unpriced_agent_runs} rulări fără preț înregistrat</div>` : ''}</div>`;
}

async function loadBudget() {
  const cards = element('budget-cards');
  try {
    const data = await api('/economy/budget');
    const spend = `<div class="budget-card"><span class="stat-label">Cheltuit</span><strong>azi ${escapeHtml(data.today.spent_usd)} USD</strong><span>luna aceasta ${escapeHtml(data.month.spent_usd)} USD · ${data.month.agent_runs} rulări de agenți, ${data.month.unpriced_agent_runs} fără preț</span></div>`;
    const providers = data.month.by_provider.map((p) => `<div class="budget-card"><span class="stat-label">${escapeHtml(p.provider)}</span><strong>${escapeHtml(((p.estimated_usd_micros + p.billed_usd_micros) / 1e6).toFixed(2))} USD</strong><span>${p.records} înregistrări · facturat ${escapeHtml((p.billed_usd_micros / 1e6).toFixed(2))}</span></div>`).join('');
    cards.innerHTML = spend + (data.budgets.length ? data.budgets.map(budgetCard).join('') : '<div class="budget-card"><span class="stat-label">Buget</span><strong>nesetat</strong><span>fără limită, nimic nu oprește cheltuiala</span></div>') + providers;
  } catch (error) {
    cards.innerHTML = `<div class="text-error">${escapeHtml(error instanceof Error ? error.message : 'Bugetul nu a putut fi citit.')}</div>`;
  }
}

async function loadTreasury() {
  loadBudget();
  const summary = element('treasury-summary');
  const accountsBox = element('treasury-accounts');
  const ledgerBox = element('treasury-ledger');
  try {
    const [treasury, ledger] = await Promise.all([
      api('/economy/treasury'),
      api('/economy/ledger?limit=25'),
    ]);

    summary.replaceChildren();
    summary.append(treasuryTile(treasury.spendable, 'treasury-tile-primary'));
    for (const row of treasury.positions) {
      if (row.money_class === 'VR_CASH') continue;
      summary.append(treasuryTile(row));
    }
    for (const row of treasury.not_spendable) summary.append(treasuryTile(row));

    const unbilled = treasury.unbilled_provider_costs;
    if (unbilled) {
      summary.append(
        treasuryTile({
          amount: unbilled.amount,
          money_class: 'Costuri furnizor neînfacturate',
          label: unbilled.label,
          spendable: false,
        }),
      );
    }

    // The trial balance is the one number that says whether any of the rest can be trusted.
    const balance = document.createElement('div');
    const tb = treasury.trial_balance;
    balance.className = `runbook-verdict ${tb.balanced ? 'rb-ready' : 'rb-blocked'}`;
    const verdict = document.createElement('strong');
    verdict.textContent = tb.balanced ? 'REGISTRU ECHILIBRAT' : 'REGISTRU DEZECHILIBRAT';
    const detail = document.createElement('span');
    detail.textContent = tb.balanced
      ? `Debite ${tb.total_debits} = credite ${tb.total_credits}.${treasury.in_deficit ? ' Numerarul VR$ este negativ: trezoreria e în deficit.' : ''}`
      : `Diferență ${tb.difference}. Nicio cifră de mai sus nu e de încredere până nu se lămurește.`;
    balance.append(verdict, detail);
    summary.append(balance);

    element('treasury-disclaimer').textContent = treasury.disclaimer;

    accountsBox.replaceChildren();
    if (!treasury.accounts.length) {
      const empty = document.createElement('div');
      empty.className = 'topics-loading';
      empty.textContent = 'Niciun cont nu are sold. Registrul e gol.';
      accountsBox.append(empty);
    }
    for (const account of treasury.accounts) {
      const row = document.createElement('div');
      row.className = 'topic-card';
      const head = document.createElement('div');
      head.className = 'topic-card-header';
      const name = document.createElement('span');
      name.className = 'topic-card-title';
      name.textContent = `${account.code} · ${account.name}`;
      const value = document.createElement('span');
      value.className = 'topic-card-novelty';
      value.textContent = `${account.balance} VR$`;
      head.append(name, value);
      const meta = document.createElement('div');
      meta.className = 'topic-card-meta';
      meta.textContent = account.money_class
        ? `${account.type} · ${MONEY_CLASS_LABEL[account.money_class] || account.money_class}`
        : account.type;
      row.append(head, meta);
      accountsBox.append(row);
    }

    ledgerBox.replaceChildren();
    if (!ledger.transactions.length) {
      const empty = document.createElement('div');
      empty.className = 'topics-loading';
      empty.textContent = 'Nicio înregistrare încă. Nimic nu s-a emis și nimic nu s-a cheltuit.';
      ledgerBox.append(empty);
    }
    for (const item of ledger.transactions) {
      const card = document.createElement('div');
      card.className = `topic-card ${item.kind === 'REVERSAL' ? 'topic-card-low' : ''}`.trim();
      const head = document.createElement('div');
      head.className = 'topic-card-header';
      const title = document.createElement('span');
      title.className = 'topic-card-title';
      title.textContent = LEDGER_KIND_LABEL[item.kind] || item.kind;
      const amount = document.createElement('span');
      amount.className = 'topic-card-novelty';
      amount.textContent = `${item.amount} VR$`;
      head.append(title, amount);
      const memo = document.createElement('p');
      memo.className = 'topic-card-subject';
      memo.textContent = item.memo;
      const meta = document.createElement('div');
      meta.className = 'topic-card-meta';
      meta.textContent = item.lines
        .map((line) =>
          Number(line.debit) ? `D ${line.account} ${line.debit}` : `C ${line.account} ${line.credit}`,
        )
        .join(' · ');
      card.append(head, memo, meta);
      ledgerBox.append(card);
    }
  } catch (err) {
    summary.replaceChildren();
    const failure = document.createElement('div');
    failure.className = 'dialog-status-msg text-error';
    failure.textContent = `Trezoreria nu a putut fi citită: ${err.message}`;
    summary.append(failure);
  }
}

/* ---------------------------------------------------------------------------
 * Owner funding.
 *
 * Two kinds of money that must not blur into each other: a contribution is equity and is never
 * repaid, a loan is a liability with a rate and a maturity. The backend refuses the wrong
 * combination, and the form mirrors that by only showing the fields the chosen kind allows.
 *
 * Amounts are typed, not parsed loosely. A comma is refused rather than guessed at: "1,000" is a
 * thousand to one reader and one to another, and money is the last place to be accommodating
 * about ambiguity. A rate is entered as a percentage because that is how people think about it,
 * and converted to the basis points the API stores.
 * ------------------------------------------------------------------------- */

const AMOUNT_PATTERN = /^\d{1,12}(\.\d{1,6})?$/;
const MICROS = 1000000n;

/**
 * Decimal text -> integer micros, rounding half away from zero.
 *
 * Deliberately the same arithmetic as `to_micros` in the backend, in BigInt rather than floats:
 * 500 * 1.08 is 540.0000000000001 in IEEE doubles, and a preview that disagrees with the ledger
 * by a fraction teaches the Owner to distrust both.
 */
function amountToMicros(text) {
  const [whole, frac = ''] = String(text).split('.');
  const padded = (frac + '0000000').slice(0, 7);
  let micros = BigInt(whole || '0') * MICROS + BigInt(padded.slice(0, 6));
  if (Number(padded[6]) >= 5) micros += 1n;
  return micros;
}

function microsToAmount(micros) {
  const text = `${micros / MICROS}.${(micros % MICROS).toString().padStart(6, '0')}`;
  return text.replace(/\.?0+$/, '') || '0';
}

/**
 * Say, before anything is written, exactly how many VR$ the entry will create.
 *
 * The ledger has no currency column: everything posted is VR$. The currency on this form belongs
 * to the real money that justifies the entry, and this line is where the two are reconciled in
 * front of the Owner instead of behind them.
 */
function updateFundingPreview() {
  const box = element('funding-preview');
  const amount = /** @type {HTMLInputElement} */ (element('funding-amount')).value.trim();
  const currency = /** @type {HTMLInputElement} */ (element('funding-currency')).value
    .trim()
    .toUpperCase();
  if (!AMOUNT_PATTERN.test(amount)) {
    box.textContent = 'Scrie suma ca să vezi câți VR$ intră în registru.';
    return;
  }
  if (currency === 'USD') {
    box.textContent = `${amount} USD verificați → ${amount} VR$ în registru (1 USD = 1 VR$).`;
    return;
  }
  if (currency.length !== 3) {
    box.textContent = 'Moneda are trei litere, ex. USD sau EUR.';
    return;
  }
  const rate = /** @type {HTMLInputElement} */ (element('funding-fx-rate')).value.trim();
  if (!AMOUNT_PATTERN.test(rate) || Number(rate) <= 0) {
    box.textContent = `Scrie cursul ${currency} → USD ca să vezi câți VR$ rezultă.`;
    return;
  }
  const vr = (amountToMicros(amount) * amountToMicros(rate) + MICROS / 2n) / MICROS;
  box.textContent = `${amount} ${currency} × ${rate} → ${microsToAmount(vr)} VR$ în registru.`;
}

function fundingStatus(message, isError) {
  const box = element('funding-status');
  box.hidden = false;
  box.className = isError ? 'dialog-status-msg text-error' : 'dialog-status-msg';
  box.textContent = message;
}

/** Show only the fields the chosen kind of funding is allowed to carry. */
function syncFundingFields() {
  const isLoan = /** @type {HTMLSelectElement} */ (element('funding-type')).value === 'OWNER_LOAN';
  const currency = /** @type {HTMLInputElement} */ (element('funding-currency')).value
    .trim()
    .toUpperCase();
  element('funding-loan-fields').hidden = !isLoan;
  element('funding-fx-fields').hidden = currency === 'USD' || currency.length !== 3;
}

/** Percentage as a person writes it -> basis points as the ledger stores them. 7.25 -> 725. */
function percentToBasisPoints(text) {
  const value = Number(text);
  if (!Number.isFinite(value) || value < 0 || value > 1000) return null;
  return Math.round(value * 100);
}

async function loadFundingHistory() {
  const box = element('funding-history');
  try {
    const { funding } = await api('/economy/owner-funding');
    box.replaceChildren();
    if (!funding.length) {
      const empty = document.createElement('div');
      empty.className = 'topics-loading';
      empty.textContent = 'Nicio finanțare înregistrată încă.';
      box.append(empty);
      return;
    }
    for (const item of funding) {
      const card = document.createElement('div');
      const isLoan = item.funding_type === 'OWNER_LOAN';
      card.className = `topic-card ${isLoan ? 'topic-card-low' : 'topic-card-high'}`;
      const head = document.createElement('div');
      head.className = 'topic-card-header';
      const title = document.createElement('span');
      title.className = 'topic-card-title';
      title.textContent = isLoan ? 'Împrumut Owner' : 'Aport de capital';
      const value = document.createElement('span');
      value.className = 'topic-card-novelty';
      value.textContent = `${item.vr} VR$`;
      head.append(title, value);
      const meta = document.createElement('div');
      meta.className = 'topic-card-meta';
      const parts = [`${item.amount} ${item.currency}`];
      if (isLoan) {
        parts.push(`${(item.annual_rate_bps / 100).toFixed(2)}% pe an`);
        parts.push(`scadență ${item.maturity_date}`);
      } else {
        parts.push('fără dobândă, nu se restituie');
      }
      meta.textContent = parts.join(' · ');
      card.append(head, meta);
      if (item.note) {
        const note = document.createElement('p');
        note.className = 'topic-card-subject';
        note.textContent = item.note;
        card.append(note);
      }
      box.append(card);
    }
  } catch (err) {
    box.replaceChildren();
    const failure = document.createElement('div');
    failure.className = 'dialog-status-msg text-error';
    failure.textContent = `Istoricul finanțărilor nu a putut fi citit: ${err.message}`;
    box.append(failure);
  }
}

element('funding-type').addEventListener('change', syncFundingFields);
for (const id of ['funding-currency', 'funding-amount', 'funding-fx-rate']) {
  element(id).addEventListener('input', () => {
    syncFundingFields();
    updateFundingPreview();
  });
}

element('funding-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const type = /** @type {HTMLSelectElement} */ (element('funding-type')).value;
  const amount = /** @type {HTMLInputElement} */ (element('funding-amount')).value.trim();
  const currency = /** @type {HTMLInputElement} */ (element('funding-currency')).value
    .trim()
    .toUpperCase();
  const note = /** @type {HTMLInputElement} */ (element('funding-note')).value.trim();
  const isLoan = type === 'OWNER_LOAN';

  if (amount.includes(',')) {
    fundingStatus('Scrie suma cu punct pentru zecimale și fără separator de mii: 5000.50', true);
    return;
  }
  if (!AMOUNT_PATTERN.test(amount)) {
    fundingStatus('Suma trebuie să fie un număr pozitiv, cu cel mult 6 zecimale.', true);
    return;
  }
  if (currency.length !== 3) {
    fundingStatus('Moneda are trei litere, ex. USD sau EUR.', true);
    return;
  }

  const payload = {
    command_id: crypto.randomUUID(),
    funding_type: type,
    amount,
    currency,
    note,
  };

  if (isLoan) {
    const rate = percentToBasisPoints(
      /** @type {HTMLInputElement} */ (element('funding-rate')).value.trim(),
    );
    const maturity = /** @type {HTMLInputElement} */ (element('funding-maturity')).value;
    if (rate === null) {
      fundingStatus('Dobânda se scrie în procente pe an, între 0 și 1000. Ex: 7 sau 7.25', true);
      return;
    }
    if (!maturity) {
      fundingStatus('Un împrumut are nevoie de o scadență; altfel înregistrează-l ca aport.', true);
      return;
    }
    payload.annual_rate_bps = rate;
    payload.maturity_date = maturity;
  }

  try {
    // A non-USD amount needs a rate that was observed somewhere, not one the page invented, so
    // the snapshot is recorded first and the funding cites it.
    if (currency !== 'USD') {
      const fxRate = /** @type {HTMLInputElement} */ (element('funding-fx-rate')).value.trim();
      const fxSource = /** @type {HTMLInputElement} */ (element('funding-fx-source')).value.trim();
      if (!AMOUNT_PATTERN.test(fxRate) || Number(fxRate) <= 0) {
        fundingStatus(`Scrie cursul ${currency} către USD, ex. 1.08`, true);
        return;
      }
      if (!fxSource) {
        fundingStatus('Scrie de unde ai luat cursul; studioul nu inventează cursuri.', true);
        return;
      }
      fundingStatus('Se înregistrează cursul…', false);
      const snapshot = await api('/economy/fx', {
        method: 'POST',
        body: JSON.stringify({
          command_id: crypto.randomUUID(),
          base_currency: currency,
          quote_currency: 'USD',
          rate: fxRate,
          source: fxSource,
          observed_at: new Date().toISOString(),
        }),
      });
      payload.fx_snapshot_id = snapshot.id;
    }

    fundingStatus('Se înregistrează finanțarea…', false);
    const result = await api('/economy/owner-funding', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    fundingStatus(
      `Înregistrat: ${result.vr} VR$ ${isLoan ? 'ca datorie' : 'în capitalul propriu'}. ` +
        'Niciun ban real nu s-a mișcat.',
      false,
    );
    /** @type {HTMLFormElement} */ (element('funding-form')).reset();
    /** @type {HTMLInputElement} */ (element('funding-currency')).value = 'USD';
    syncFundingFields();
    updateFundingPreview();
    await Promise.all([loadTreasury(), loadFundingHistory()]);
  } catch (err) {
    fundingStatus(err.message, true);
  }
});

if (openTreasuryBtn) {
  openTreasuryBtn.addEventListener('click', () => {
    treasuryModal.showModal();
    syncFundingFields();
    updateFundingPreview();
    loadTreasury();
    loadFundingHistory();
  });
}
element('close-treasury-btn').addEventListener('click', () => treasuryModal.close());
element('refresh-treasury-btn').addEventListener('click', () => {
  loadTreasury();
  loadFundingHistory();
});
bindPanelToggle('open-treasury-btn', treasuryModal);

const storyModal = /** @type {HTMLDialogElement} */ (element('story-modal'));

function storyStatus(message, isError) {
  const box = element('story-status');
  box.hidden = false;
  box.className = isError ? 'dialog-status-msg text-error' : 'dialog-status-msg';
  box.textContent = message;
}

async function loadStoryLogs() {
  const listEl = element('story-logs');
  try {
    const data = await api('/story/logs');
    const logs = data.logs || [];
    if (!logs.length) {
      listEl.innerHTML =
        '<div class="topics-loading">Nicio zi închisă încă. Închide ziua ca să numeri ce s-a întâmplat.</div>';
      return;
    }
    listEl.innerHTML = logs
      .map(
        (log) => `
        <div class="topic-card story-log-card" data-log-id="${escapeHtml(log.id)}">
          <div class="topic-card-header">
            <strong class="topic-card-title">${escapeHtml(log.business_date)}</strong>
            <span class="topic-card-novelty">${log.total_events} evenimente</span>
          </div>
          <div class="topic-card-meta">
            <span>${(log.roster || []).length} în distribuție</span>
            · <span>${(log.notable_events || []).length} evenimente de povestit</span>
          </div>
          <div class="source-actions">
            ${
              (log.notable_events || []).length
                ? `<button class="secondary btn-write-episode" data-log-id="${escapeHtml(log.id)}">Scrie episodul</button>`
                : '<span class="helper-note">Zi liniștită — nu există material pentru un episod.</span>'
            }
          </div>
        </div>`,
      )
      .join('');
    listEl.querySelectorAll('.btn-write-episode').forEach((btn) => {
      btn.addEventListener('click', () => writeEpisode(btn));
    });
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
  }
}

async function loadEpisodes() {
  const listEl = element('story-episodes');
  try {
    const data = await api('/story/episodes');
    const episodes = data.episodes || [];
    if (!episodes.length) {
      listEl.innerHTML = '<div class="topics-loading">Niciun episod încă.</div>';
      return;
    }
    listEl.innerHTML = episodes
      .map(
        (episode) => `
        <div class="topic-card story-episode wf-${escapeHtml(String(episode.status).toLowerCase())}" data-id="${escapeHtml(episode.id)}">
          <div class="topic-card-header">
            <strong class="topic-card-title">${escapeHtml(episode.title)}</strong>
            <span class="topic-card-novelty">${escapeHtml(episode.status)}</span>
          </div>
          <div class="topic-card-meta">
            <span>${(episode.beats || []).length} beat-uri</span>
            · <span>${(episode.grounded_event_ids || []).length} evenimente reale citate</span>
          </div>
          <div class="story-beats">
            ${(episode.beats || [])
              .map(
                (beat) => `
              <div class="scene-row">
                <div class="scene-narration"><strong>${escapeHtml(beat.scene || '')}</strong> — ${escapeHtml(beat.dialogue || '')}</div>
                <div class="scene-meta">Beat ${beat.beat_number} · ${(beat.event_ids || []).length} evenimente citate${(beat.characters || []).length ? ` · ${escapeHtml((beat.characters || []).join(', '))}` : ''}</div>
              </div>`,
              )
              .join('')}
          </div>
          ${episode.notes ? `<div class="claim-notes">${escapeHtml(episode.notes)}</div>` : ''}
          <div class="source-actions">
            <button class="quiet btn-check-grounding" data-id="${escapeHtml(episode.id)}">Verifică ancorarea</button>
            ${
              episode.status === 'DRAFT'
                ? `<input class="wf-notes" placeholder="Motiv (obligatoriu la respingere)" maxlength="2000" />
                   <button class="secondary btn-decide-episode" data-id="${escapeHtml(episode.id)}" data-approve="true">Aprobă</button>
                   <button class="quiet btn-decide-episode" data-id="${escapeHtml(episode.id)}" data-approve="false">Respinge</button>`
                : ''
            }
          </div>
        </div>`,
      )
      .join('');
    listEl.querySelectorAll('.btn-check-grounding').forEach((btn) => {
      btn.addEventListener('click', () => checkGrounding(btn));
    });
    listEl.querySelectorAll('.btn-decide-episode').forEach((btn) => {
      btn.addEventListener('click', () => decideEpisode(btn));
    });
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
  }
}

async function writeEpisode(button) {
  const logId = button.getAttribute('data-log-id');
  button.disabled = true;
  storyStatus('Showrunner-ul scrie din evenimentele zilei…', false);
  try {
    const result = await api('/story/episodes/write', {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID(), log_id: logId }),
    });
    const episode = result.episode;
    storyStatus(
      `„${episode.title}" — ${(episode.beats || []).length} beat-uri, ${(episode.grounded_event_ids || []).length} evenimente reale citate.`,
      false,
    );
    await loadEpisodes();
  } catch (err) {
    // A rejected episode, or a quiet day, is the system working.
    storyStatus(err.message, true);
  } finally {
    button.disabled = false;
  }
}

/** Re-check a stored episode against its day, so the claim is audited rather than trusted. */
async function checkGrounding(button) {
  const id = button.getAttribute('data-id');
  try {
    const report = await api(`/story/episodes/${id}/grounding`);
    storyStatus(
      report.grounded
        ? `Ancorat: toate cele ${report.cited_events} evenimente citate există în jurnalul din ${report.business_date}.`
        : `NEANCORAT: ${report.citations_not_in_the_log.length} citări nu există în jurnalul zilei.`,
      !report.grounded,
    );
  } catch (err) {
    storyStatus(err.message, true);
  }
}

async function decideEpisode(button) {
  const id = button.getAttribute('data-id');
  const approve = button.getAttribute('data-approve') === 'true';
  const card = button.closest('.story-episode');
  const notes = /** @type {HTMLInputElement | null} */ (card?.querySelector('.wf-notes'));
  const reason = notes ? notes.value.trim() : '';
  if (!approve && !reason) {
    storyStatus('Scrie de ce respingi episodul; motivul rămâne în istoric.', true);
    return;
  }
  try {
    await api(`/story/episodes/${id}/decide`, {
      method: 'POST',
      body: JSON.stringify({
        command_id: crypto.randomUUID(),
        approve,
        notes: reason,
      }),
    });
    storyStatus(approve ? 'Episod aprobat.' : 'Episod respins; motivul a fost înregistrat.', false);
    await loadEpisodes();
  } catch (err) {
    storyStatus(err.message, true);
  }
}

element('open-story-btn').addEventListener('click', () => {
  storyModal.showModal();
  loadStoryLogs();
  loadEpisodes();
});
element('close-story-btn').addEventListener('click', () => storyModal.close());
element('close-day-btn').addEventListener('click', async () => {
  storyStatus('Se numără evenimentele zilei…', false);
  try {
    const log = await api('/story/logs/close', {
      method: 'POST',
      body: JSON.stringify({
        command_id: crypto.randomUUID(),
        business_date: null,
      }),
    });
    storyStatus(
      `${log.business_date}: ${log.total_events} evenimente, ${(log.notable_events || []).length} de povestit.`,
      false,
    );
    await loadStoryLogs();
  } catch (err) {
    storyStatus(err.message, true);
  }
});
bindPanelToggle('open-story-btn', storyModal);

/* ---------------------------------------------------------------------------
 * Phase 10: the daily runbook.
 *
 * Two honesty problems have a shape here. The preflight must not round a missing capability up
 * to "ready", so every check is listed with what it found rather than summarised into a colour.
 * And a run must not read as more than it did: every stage of the runbook is shown, including
 * the ones that were skipped and the ones that never got the chance to run, each with its
 * reason. A page listing three stages when the runbook has twelve would mislead by its shape
 * alone, without a single false sentence on it.
 * ------------------------------------------------------------------------- */

const runbookModal = /** @type {HTMLDialogElement} */ (element('runbook-modal'));

const RUNBOOK_STAGE_LABELS = {
  preflight: 'Preflight',
  performance_intake: 'Preluare performanță',
  idea_generation: 'Generare idei',
  research_and_verification: 'Cercetare și verificare',
  selection: 'Selecție',
  script_and_storyboard: 'Scenariu și storyboard',
  media: 'Media',
  edit_and_qc: 'Montaj și QC',
  publish: 'Publicare',
  post_run: 'După rulare',
  daily_log: 'Jurnalul zilei',
  serial_queue: 'Coada serialului',
};

/** Preflight check names, as the Owner would say them. */
const RUNBOOK_CHECK_LABELS = {
  stop_autonomy: 'STOP autonomie',
  llm_provider: 'Model de limbaj',
  agents: 'Agenți disponibili',
  render_engine: 'Motor de randare (FFmpeg)',
  media_inspection: 'Inspecție media (FFprobe)',
  research_sources: 'Site-uri autorizate pentru surse',
  image_provider: 'Furnizor de imagine',
  voice_provider: 'Furnizor de voce',
  publishing: 'Publicare',
};

function runbookStatus(message, isError) {
  const box = element('runbook-status');
  box.hidden = false;
  box.className = isError ? 'dialog-status-msg text-error' : 'dialog-status-msg';
  box.textContent = message;
}

function stageLabel(name) {
  return RUNBOOK_STAGE_LABELS[name] || name;
}

function checkLabel(name) {
  return RUNBOOK_CHECK_LABELS[name] || name;
}

async function loadPreflight() {
  const summaryEl = element('runbook-preflight-summary');
  const checksEl = element('runbook-checks');
  try {
    const data = await api('/runbook/preflight');
    const status = String(data.status || '');
    summaryEl.innerHTML = `
      <div class="runbook-verdict rb-${escapeHtml(status.toLowerCase())}">
        <strong>${escapeHtml(status)}</strong>
        <span>${escapeHtml(data.summary || '')}</span>
      </div>`;
    // Every check is shown, passing ones included: the value of a preflight is that the Owner
    // can see what it actually looked at, not only what it complained about.
    checksEl.innerHTML = (data.checks || [])
      .map(
        (check) => `
        <div class="runbook-check ${check.ok ? 'rb-ok' : `rb-fail rb-${escapeHtml(String(check.severity).toLowerCase())}`}">
          <div class="topic-card-header">
            <strong class="topic-card-title">${escapeHtml(checkLabel(check.name))}</strong>
            <span class="topic-card-novelty">${check.ok ? 'OK' : escapeHtml(check.severity === 'BLOCKING' ? 'BLOCANT' : 'DEGRADEAZĂ')}</span>
          </div>
          <div class="topic-card-meta">${escapeHtml(check.message || '')}${check.detail ? ` · ${escapeHtml(check.detail)}` : ''}</div>
        </div>`,
      )
      .join('');
    // The button says what will happen rather than letting the Owner discover the refusal.
    const startBtn = /** @type {HTMLButtonElement} */ (element('start-run-btn'));
    startBtn.disabled = status === 'BLOCKED';
    startBtn.title =
      status === 'BLOCKED'
        ? 'Preflight blocant: rezolvă punctele blocante înainte de a porni rularea.'
        : 'Rulează etapele zilei și consemnează ce a făcut fiecare.';
  } catch (err) {
    summaryEl.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
    checksEl.innerHTML = '';
  }
}

async function loadSafeMode() {
  const box = element('runbook-safe-mode');
  try {
    const state = await api('/runbook/safe-mode');
    if (!state.active) {
      box.hidden = true;
      return;
    }
    box.hidden = false;
    element('runbook-safe-since').textContent = state.entered_at
      ? new Date(state.entered_at).toLocaleString('ro-RO')
      : '—';
    element('runbook-safe-reason').textContent = state.reason || '—';
  } catch {
    box.hidden = true;
  }
}

function renderRunCard(run) {
  const stages = run.stages || [];
  return `
    <div class="topic-card runbook-run rb-${escapeHtml(String(run.status).toLowerCase())}">
      <div class="topic-card-header">
        <strong class="topic-card-title">${escapeHtml(run.business_date || '')}</strong>
        <span class="topic-card-novelty">${escapeHtml(run.status)}</span>
      </div>
      <div class="topic-card-meta">
        <span>${run.stages_completed}/${run.stages_total} etape încheiate</span>
        · <span>preflight ${escapeHtml(run.preflight_status || '—')}</span>
        ${run.stopped_at_stage ? ` · <span>oprit la «${escapeHtml(stageLabel(run.stopped_at_stage))}»</span>` : ''}
      </div>
      ${run.stop_reason ? `<div class="claim-notes">${escapeHtml(run.stop_reason)}</div>` : ''}
      <div class="runbook-stages">
        ${stages
          .map(
            (stage) => `
          <div class="runbook-stage rb-${escapeHtml(String(stage.status).toLowerCase())}">
            <span class="runbook-stage-name">${escapeHtml(stageLabel(stage.stage))}</span>
            <span class="runbook-stage-status">${escapeHtml(stage.status)}</span>
            <span class="runbook-stage-reason">${escapeHtml(stage.reason || '')}</span>
          </div>`,
          )
          .join('')}
      </div>
    </div>`;
}

async function loadRuns() {
  const listEl = element('runbook-runs');
  try {
    const data = await api('/runbook/runs');
    const runs = data.runs || [];
    if (!runs.length) {
      listEl.innerHTML = '<div class="topics-loading">Nicio rulare încă.</div>';
      return;
    }
    listEl.innerHTML = runs.map(renderRunCard).join('');
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
  }
}

/**
 * The schedule behind the button. A studio that runs itself has a job that fires the day; the
 * panel says when, and says plainly that it will not fire while autonomy is stopped, because
 * a "next run" time shown beside a stopped studio would promise something that cannot happen.
 */
async function loadRunbookSchedule() {
  const box = element('runbook-schedule');
  try {
    const [jobs, snapshot] = await Promise.all([api('/scheduler/jobs'), api('/snapshot')]);
    const daily = (jobs || []).find((job) => job.workflow_type === 'DAILY_RUN');
    if (!daily) {
      box.innerHTML = `<p class="runbook-note">Niciun job zilnic programat. Worker-ul de fundal îl creează la pornire când este activ.</p>`;
      return;
    }
    const stopped = Boolean(snapshot?.policy?.autonomy_stopped);
    const when = (iso) => (iso ? new Date(iso).toLocaleString('ro-RO') : '—');
    box.innerHTML = `
      <div class="runbook-check ${stopped ? 'rb-fail rb-degrading' : 'rb-ok'}">
        <div class="topic-card-header">
          <strong class="topic-card-title">${escapeHtml(daily.name)}</strong>
          <span class="topic-card-novelty">${daily.is_active ? 'ACTIV' : 'INACTIV'}</span>
        </div>
        <div class="topic-card-meta">Următoarea rulare: ${escapeHtml(when(daily.next_run_at))} · ultima: ${escapeHtml(when(daily.last_run_at))} · la ${escapeHtml(String(Math.round(daily.interval_seconds / 3600)))} ore · rulări ratate: ${escapeHtml(daily.missed_policy === 'CATCH_UP' ? 'o singură recuperare, apoi cadența inițială' : 'sărite')}</div>
        ${stopped ? `<p class="runbook-note">Autonomia este oprită: jobul nu va porni nimic până nu o repornești.</p>` : ''}
        ${daily.is_active ? '' : `<p class="runbook-note">Programarea este oprită: studioul nu începe nicio zi singur. Pornirea ei este o decizie a ta și rămâne în istoric.</p>`}
        <div class="settings-actions">
          <button id="toggle-daily-job-btn" class="${daily.is_active ? 'quiet' : 'secondary'}" data-job-id="${escapeHtml(daily.id)}" data-active="${daily.is_active ? 'true' : 'false'}">${daily.is_active ? 'Oprește programarea' : 'Pornește programarea zilnică'}</button>
        </div>
      </div>`;
    element('toggle-daily-job-btn').addEventListener('click', async (event) => {
      const button = /** @type {HTMLButtonElement} */ (event.currentTarget);
      button.disabled = true;
      try {
        await api(`/scheduler/jobs/${button.dataset.jobId}/active`, {
          method: 'POST',
          body: JSON.stringify({ command_id: crypto.randomUUID(), active: button.dataset.active !== 'true' }),
        });
        await loadRunbookSchedule();
      } catch (err) {
        runbookStatus(err.message, true);
        button.disabled = false;
      }
    });
  } catch (err) {
    box.innerHTML = `<p class="runbook-note text-error">Programarea nu a putut fi citită: ${escapeHtml(err.message)}</p>`;
  }
}

element('open-runbook-btn').addEventListener('click', () => {
  runbookModal.showModal();
  loadPreflight();
  loadSafeMode();
  loadRuns();
  loadRunbookSchedule();
});
element('close-runbook-btn').addEventListener('click', () => runbookModal.close());
element('refresh-preflight-btn').addEventListener('click', () => loadPreflight());

element('start-run-btn').addEventListener('click', async (event) => {
  const button = /** @type {HTMLButtonElement} */ (event.currentTarget);
  button.disabled = true;
  runbookStatus('Rularea zilei este în curs…', false);
  try {
    const run = await api('/runbook/runs', {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID() }),
    });
    runbookStatus(
      `${run.status}: ${run.stages_completed}/${run.stages_total} etape încheiate` +
        (run.stopped_at_stage ? `, oprit la «${stageLabel(run.stopped_at_stage)}».` : '.'),
      run.status === 'FAILED' || run.status === 'BLOCKED',
    );
    await loadRuns();
    await loadSafeMode();
  } catch (err) {
    // Safe mode and a blocking preflight both refuse here; the refusal is the message.
    runbookStatus(err.message, true);
  } finally {
    button.disabled = false;
    await loadPreflight();
  }
});

element('clear-safe-mode-btn').addEventListener('click', async () => {
  const field = /** @type {HTMLTextAreaElement} */ (element('runbook-safe-notes'));
  const notes = field.value.trim();
  if (!notes) {
    runbookStatus('Scrie ce ai verificat înainte de a ieși din modul sigur.', true);
    return;
  }
  try {
    const result = await api('/runbook/safe-mode/clear', {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID(), notes }),
    });
    field.value = '';
    runbookStatus(result.note, false);
    await loadSafeMode();
    await loadPreflight();
  } catch (err) {
    runbookStatus(err.message, true);
  }
});

bindPanelToggle('open-runbook-btn', runbookModal);
