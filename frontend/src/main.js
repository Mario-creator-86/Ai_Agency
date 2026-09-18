import { loadAgentDetails } from './agent_details.js';
import { escapeHtml } from './html.js';
import {
  approvalCaveat,
  checkClassName,
  checkLabel,
  checkVerdictWord,
} from './readiness.js';
import './style.css';
import { initSettings } from './settings.js';
import { acceptSnapshot } from './projection.js';
import { OfficeEngine } from './office_engine.js';
import { OfficeState } from './office_state.js';
import { Ledger } from './ledger.js';
import { friendlyAnswer } from './friendly_text.js';
import { LiveWindows, eventMatchesAgent } from './live_window.js';
import { MailThread } from './mail_thread.js';
import { LiveStream } from './hq_stream.js';
import { liveStreamSettings, relayUrl } from './hq_stream_config.js';
import {
  APPROVALS_PATH,
  APPROVAL_DECISION_PATH,
  REFERENCE_CREDIT_WARNING,
  approvalCostText,
  approvalDecisionCommand,
  approvalExpiryText,
  autonomyModeCommand,
  autonomyModeLabel,
  autonomyModeMeaning,
  promotionBlockedReason,
  readApprovals,
  referenceSetSummary,
  riskTierMeaning,
} from './governance.js';

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
const environmentButton = /** @type {HTMLButtonElement} */ (element('environment-toggle'));
const inspector = /** @type {HTMLDialogElement} */ (element('agent-inspector'));

let ownerToken = '';
let state = null;
let pendingCommand = null;
let pendingEnvironment = null;
let epoch = 0;
let busy = false;
let connected = false;
let socket = null;

// 2D Office Engine & State
const officeCanvas = /** @type {HTMLCanvasElement} */ (element('office-canvas'));
const officeState = new OfficeState();
let officeEngine = null;
/** @type {LiveStream|null} the Unreal headquarters over the renderer, when scene.json turns it on */
let liveStream = null;
let currentSelectedAgent = null;
let inspectorRequest = 0;

// Standalone live windows ("what is this employee doing right now"), fed by the same
// event flow the ledger reads.
const liveWindows = new LiveWindows();

/** Employees currently THINKING/WORKING, from their own events; drives the chat indicator. */
const thinkingAgents = new Set();
let historyRefreshTimer = 0;

/**
 * One funnel for every newly recorded event, from whichever source it arrived: the live
 * windows hear about it, the chat's "scrie…" indicator follows the employee's state, and an
 * open conversation refreshes itself so an answer that lands while the Owner reads is not
 * missed. Runs fired from outside the page (the daily run, another panel) appear here too.
 */
function noteAgentEvent(event) {
  liveWindows.broadcast(event);
  const type = String(event.event_type || '');
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  if (type === 'agent.state_changed') {
    const id = payload.agent_id || event.aggregate_id;
    if (payload.runtime_state === 'THINKING' || payload.runtime_state === 'WORKING') {
      thinkingAgents.add(id);
    } else {
      thinkingAgents.delete(id);
    }
    updateTypingIndicator();
  } else if (type === 'agent.run_completed') {
    thinkingAgents.delete(payload.agent_id);
    updateTypingIndicator();
  }
  const current = currentSelectedAgent && (currentSelectedAgent.id || currentSelectedAgent.agent_id);
  const refreshTypes = [
    'agent.message_sent',
    'agent.message_posted',
    'agent.message_answered',
    'agent.run_completed',
  ];
  if (current && refreshTypes.includes(type) && eventMatchesAgent(event, current)) {
    scheduleHistoryRefresh(current);
  }
}

function updateTypingIndicator() {
  const indicator = element('agent-typing');
  const current = currentSelectedAgent && (currentSelectedAgent.id || currentSelectedAgent.agent_id);
  const active = Boolean(current && inspector.open && thinkingAgents.has(current));
  indicator.hidden = !active;
  if (active) indicator.textContent = `${currentSelectedAgent.display_name || 'The agent'} is working… the answer appears here.`;
}

function scheduleHistoryRefresh(agentId) {
  clearTimeout(historyRefreshTimer);
  historyRefreshTimer = window.setTimeout(() => {
    const current = currentSelectedAgent && (currentSelectedAgent.id || currentSelectedAgent.agent_id);
    if (inspector.open && current === agentId) loadAgentHistory(agentId);
  }, 600);
}

/** One exchange of letters, opened from the ledger or from an employee's inbox. */
const mailThread = new MailThread({
  dialog: /** @type {HTMLDialogElement} */ (element('mail-modal')),
  title: element('mail-title'),
  body: element('mail-thread'),
  form: /** @type {HTMLFormElement} */ (element('mail-reply-form')),
  input: /** @type {HTMLTextAreaElement} */ (element('mail-reply-text')),
  status: element('mail-status'),
  api: (path, options) => api(path, options),
  escape: escapeHtml,
});
element('mail-close').addEventListener('click', () => mailThread.dialog.close());

/** Everything the studio does and says, read from its own events. */
const ledger = new Ledger({
  list: element('ledger-list'),
  now: element('ledger-now'),
  filters: element('ledger-filters'),
  escape: escapeHtml,
  onEvents: (events) => {
    for (const event of events) noteAgentEvent(event);
  },
  onThread: (threadId) => mailThread.open(threadId),
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
    throw new Error('Connection unavailable. The data shown is no longer up to date.');
  }
  if (!response.ok) {
    // Prefer what the server said. Every refusal this backend writes is a sentence meant for
    // the Owner — which host is not authorised, why a provider did not answer, what is missing
    // before a publication can proceed — and replacing it with "try again" would throw away
    // exactly the part that tells them what to do. The generic wording is the fallback for a
    // response that carries no explanation of its own.
    let message =
      response.status === 401
        ? 'The Owner key is not valid.'
        : response.status === 409
          ? 'The state changed. The data was reloaded; repeat the command.'
          : 'The connection could not be verified. Try again.';
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

/**
 * The Unreal headquarters, streamed over the page's own renderer while it runs. The viewport's
 * data-stream attribute says which one the Owner is looking at.
 */
async function startLiveStream() {
  if (liveStream) return;
  const viewport = element('scene-viewport');
  let scene = null;
  let relay = null;
  try {
    const response = await fetch('/assets/hq/scene.json');
    scene = response.ok ? await response.json() : null;
    if (liveStreamSettings(scene).enabled) relay = await api('/office/stream');
  } catch {
    relay = null;
  }
  const settings = liveStreamSettings(scene);
  if (!settings.enabled || !relay || relay.available !== true) {
    viewport.dataset.stream = 'off';
    return;
  }
  const signallingUrl = relayUrl(window.location, String(relay.relay), ownerToken);
  liveStream = new LiveStream(viewport, { ...settings, signallingUrl }, {
    onStatus: (status) => { viewport.dataset.stream = status; },
  });
  liveStream.start();
}

function initOffice() {
  if (!officeEngine) {
    officeEngine = new OfficeEngine(officeCanvas, {
      // The page may only call its own origin; the backend reads the live weather for the scene.
      fetchWeather: () => api('/office/weather'),
      infoElement: element('scene-info'),
      fpsElement: element('office-fps'),
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
    startLiveStream();

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
          element('ledger-count').textContent = `${ledger.events.size} entries`;
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
    renderInspector({...agent,model_error:error instanceof Error?error.message:'The model details could not be loaded.',model_is_available:false});
  }
  try {
    const identity = await api(`/agents/${encodeURIComponent(id)}/identity`);
    if(request!==inspectorRequest||session!==epoch||!inspector.open) return;
    renderIdentity(identity);
    await loadAgentHistory(id);
  } catch(error) {
    if(request!==inspectorRequest||session!==epoch||!inspector.open) return;
    element('inspector-mission').textContent = error instanceof Error ? error.message : 'The identity could not be loaded.';
  }
}

const TIMELINE_LABEL = {
  run: 'Task',
  owner_chat: 'Question',
  message: 'Mesaj',
  memory: 'Memorie',
  AGENT_OPINION: 'Decision',
  HISTORICAL_EVENT: 'Eveniment',
  TEMP_CONTEXT: 'Context',
  OWNER_POLICY: 'Policy',
  VERIFIED_FACT: 'Verified fact',
  STRATEGY: 'Strategie',
};

/** Task types as the Owner would name them. Unknown types read as their own words. */
const TASK_LABEL = {
  propose_topics: 'idei de subiect',
  gather_sources: 'finding sources',
  extract_claims: 'extracting claims',
  verify_claim: 'fact check',
  choose_topic: 'alegerea subiectului',
  write_script: 'script',
  write_episode: 'the serial episode',
  review_narration: 'narration review',
  review_failed_render: 'render diagnosis',
  prepare_publication: 'publication preparation',
  director_review: 'revizuirea Directorului',
  reconcile_day: 'closing the day',
  direct_task: 'direct task',
  TEST_CONNECTIVITY: 'connection test',
};

/** What a run without an answer means, in words. */
const RUN_STATUS = {
  EMPTY_OUTPUT: 'The model returned no usable text.',
  // Runs recorded before an empty answer counted as a failure.
  SUCCEEDED: 'No text in the answer.',
  BLOCKED_POLICY: 'Blocked by policy.',
  BLOCKED_PROVIDER: 'Blocked: the provider or the model is unavailable.',
  // The day's token ceiling, not a spending budget: the run never reached a model, so it
  // cost nothing. Without this line the status printed as the raw word BLOCKED_BUDGET.
  BLOCKED_BUDGET: "Blocked: the day's token ceiling for employees was reached.",
  FAILED: 'Failed.',
};

function taskLabel(type) {
  return TASK_LABEL[type] || String(type || '').replace(/_/g, ' ');
}

function timelineTime(iso) {
  return iso ? new Date(iso).toLocaleString('ro-RO', { dateStyle: 'short', timeStyle: 'short' }) : '';
}

/**
 * One line of history: what was asked and answered, or sent, or remembered.
 *
 * The answer the Owner reads is written for a person. Structured pipelines consume the
 * model's output as JSON — chosen pages, extracted claims, written scenes — and that JSON is
 * exactly what used to be printed here; `friendlyAnswer` turns it into sentences and lists,
 * with the model's exact output collapsed underneath. Nothing is lost: the run stores the
 * full text either way.
 *
 * The task line is the employee's own sentence about the job — "Verific afirmația «…»" — not
 * the prompt it was given. Runs recorded before employees summarised their tasks only carry
 * the engineered prompt; that prompt is not something a person should have to read as the
 * headline, so the chip above says what kind of job it was and the whole prompt stays under
 * «Cererea completă».
 */
function timelineItem(item) {
  if (item.kind === 'run') {
    const isChat = item.task_type === 'owner_chat';
    const label = isChat ? TIMELINE_LABEL.owner_chat : `${TIMELINE_LABEL.run} · ${taskLabel(item.task_type)}`;
    const answer = item.answered
      ? `<div class="chat-answer">${friendlyAnswer(item.answered)}</div>`
      : `<div class="chat-answer text-error">${escapeHtml(item.error || RUN_STATUS[item.status] || item.status)}</div>`;
    const meta = [item.model, item.memory_used ? `${item.memory_used} amintiri folosite` : '', item.cost_vr ? `${item.cost_vr} VR$` : '']
      .filter(Boolean).join(' · ');
    const summarised = Boolean(item.prompt) && item.prompt !== item.asked;
    const line = isChat || summarised ? item.asked || '' : '';
    const full = item.prompt || item.asked || '';
    const prompt = !isChat && full
      ? `<details class="chat-prompt"><summary>The full request</summary><pre>${escapeHtml(full)}</pre></details>`
      : '';
    return `<div class="chat-item chat-run${isChat ? ' is-chat' : ''}"><div class="chat-meta"><span class="policy-tag policy-flexible">${escapeHtml(label)}</span> <small>${escapeHtml(timelineTime(item.at))}${meta ? ` · ${escapeHtml(meta)}` : ''}</small></div>${line ? `<div class="chat-asked">${escapeHtml(line)}</div>` : ''}${answer}${prompt}</div>`;
  }
  if (item.kind === 'message') {
    const direction = item.from_name ? `de la ${item.from_name}` : '';
    const to = item.to_name ? `to ${item.to_name}` : '';
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
      : '<div class="helper">Nothing yet: no task, message or decision recorded.</div>';
    box.scrollTop = box.scrollHeight;
  } catch (error) {
    box.innerHTML = `<div class="text-error">${escapeHtml(error instanceof Error ? error.message : 'The history could not be loaded.')}</div>`;
  }
}

/** Who the agent is, as the model is told: contract, character, memory, open messages. */
function renderIdentity(identity) {
  const contract = identity.contract || {};
  const work = contract.work_contract_json || {};
  const who = identity.character ? `${identity.display_name} is ${identity.character.canonical_name}.` : identity.display_name;
  element('inspector-mission').textContent = `${who} Mission: ${contract.mission || 'not defined'}. Reports to ${work.reports_to || '—'}.`;
  const sections = [['watch_for', 'Watches for'], ['investigate', 'Investigates'], ['correct', 'Corrects'], ['let_pass', 'Lets pass'], ['never_let_pass', 'Never lets pass'], ['escalate_when', 'Escalates when'], ['deliverables', 'Livrabile']];
  element('inspector-contract').innerHTML = sections
    .filter(([key]) => Array.isArray(work[key]) && work[key].length)
    .map(([key, label]) => `<div class="identity-block"><span class="stat-label">${escapeHtml(label)}</span><ul>${work[key].map((item) => `<li>${escapeHtml(String(item))}</li>`).join('')}</ul></div>`)
    .join('') || '<p class="helper">The role has no work contract yet. Run the bootstrap to seed it.</p>';
  element('inspector-system-prompt').textContent = identity.system_prompt || '';
  const memory = identity.memory || [];
  element('inspector-memory').innerHTML = memory.length
    ? memory.map((m) => `<li><span class="policy-tag policy-flexible">${escapeHtml(m.memory_class)}</span> ${escapeHtml(m.content)}</li>`).join('')
    : '<li class="helper">Remembers nothing yet: no check, decision or publication recorded.</li>';
  const messages = (identity.messages || []).filter((m) => m.status !== 'RESOLVED').slice(0, 8);
  element('inspector-messages').innerHTML = messages.length
    ? messages.map((m) => `<li class="inspector-mail" data-thread="${escapeHtml(m.thread_id || m.id)}" title="Open the thread"><span class="policy-tag policy-locked">${escapeHtml(m.intent)}</span> ${escapeHtml(m.subject)}${m.from_name ? ` <small>· de la ${escapeHtml(m.from_name)}</small>` : ''} <small class="ledger-open">fir ↗</small></li>`).join('')
    : '<li class="helper">No open message.</li>';
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
    modelEl.textContent='Checking the assigned model…';
    modelEl.className='stat-value';modelEl.title='Reading the current agent data.';
  } else if(agent.model_error) {
    modelEl.textContent='The assignment could not be checked';
    modelEl.className='stat-value text-error';modelEl.title=agent.model_error;
  } else if (!agent.model_name) {
    modelEl.textContent = 'No model assigned';
    modelEl.className = 'stat-value text-error';
    modelEl.title = 'Assign a model to this agent in Settings › Agents.';
  } else if (agent.model_is_available) {
    modelEl.textContent = agent.model_name;
    modelEl.className = 'stat-value text-success';
    modelEl.title = `Provider: ${agent.provider_name || 'unknown'}`;
  } else {
    modelEl.textContent = `${agent.model_name} · not verified`;
    modelEl.className = 'stat-value text-warn';
    modelEl.title =
      `The model is assigned, but the provider ${agent.provider_name || ''} has not been verified. ` +
      'Verify it in Settings before running a task.';
  }
  runBtn.disabled = !agent.model_is_available;
  runBtn.title = agent.model_is_available
    ? ''
    : 'Running needs a verified model. Assign and verify one in Settings.';

  element('agent-run-output').hidden = true;
  element('agent-run-output').textContent = '';
  applyInspectorExpanded();
  if(!inspector.open) inspector.showModal();
}

// A queued close event from the previous agent must not cancel a newly opened inspector.
inspector.addEventListener('close',()=>{if(!inspector.open) inspectorRequest++; updateTypingIndicator();});

// Expanded mode: the inspector fills the screen and the whole history reads as one long
// page — nothing cropped by the inner scroll box. The choice survives closing and reopening
// the inspector during the session.
let inspectorExpanded = false;
function applyInspectorExpanded() {
  inspector.classList.toggle('dialog-max', inspectorExpanded);
  const btn = element('inspector-expand');
  btn.textContent = inspectorExpanded ? '⤡' : '⛶';
  btn.title = inspectorExpanded
    ? 'Shrink the window back to its usual size'
    : 'Expand: the whole chat and history, top to bottom';
}
element('inspector-expand').addEventListener('click', () => {
  inspectorExpanded = !inspectorExpanded;
  applyInspectorExpanded();
});

element('inspector-messages').addEventListener('click', (event) => {
  const target = event.target instanceof Element ? event.target.closest('[data-thread]') : null;
  if (target) mailThread.open(target.getAttribute('data-thread'));
});

element('inspector-close').addEventListener('click', () => {
  inspector.close();
  if (officeEngine) officeEngine.setSelectedAgent(null);
});

// The live window keeps streaming after the inspector closes — that is its purpose.
element('agent-live-btn').addEventListener('click', () => {
  if (!currentSelectedAgent) return;
  const id = currentSelectedAgent.id || currentSelectedAgent.agent_id;
  const known = officeState.agents.find((a) => (a.id || a.agent_id) === id);
  const opened = liveWindows.open(currentSelectedAgent, {
    events: ledger.sorted(),
    runtimeState: known ? known.runtime_state : currentSelectedAgent.runtime_state,
    timezone: state ? state.studio.timezone : undefined,
  });
  if (!opened) {
    notify('The browser blocked the live window. Allow pop-ups for this page and press again.');
  }
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
  const typing = element('agent-typing');
  const submit = /** @type {HTMLButtonElement} */ (
    element('agent-run-form').querySelector('button[type="submit"]')
  );
  const message = objectiveInput.value.trim();
  if (!message) return;

  outputDiv.hidden = true;
  submit.disabled = true;
  // A chat turn takes seconds; the question asked is already saved the moment the employee
  // starts on it, and its answer joins it in the history when it lands.
  typing.hidden = false;
  typing.textContent = `Question sent. ${currentSelectedAgent.display_name || 'The agent'} is writing…`;

  try {
    await api(`/agents/${agentId}/chat`, {
      method: 'POST',
      body: JSON.stringify({ message }),
    });
    objectiveInput.value = '';
    // Reload instead of appending: the answer arrives rendered like every other entry, and
    // anything the employee filed while answering is in the same pass.
    await loadAgentHistory(agentId);
  } catch (err) {
    outputDiv.hidden = false;
    outputDiv.textContent = `Error: ${err instanceof Error ? err.message : err}`;
  } finally {
    submit.disabled = false;
    typing.hidden = true;
    updateTypingIndicator();
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

/**
 * Test every authorised site now. The daily run retests one only after seven days, which is
 * right for the sites and wrong for the Owner who has just fixed something; this is the
 * "now". One front page per site, through the studio's own retriever, stored as no source.
 */
const retestHostsBtn = document.getElementById('retest-hosts-btn');
if (retestHostsBtn) {
  retestHostsBtn.addEventListener('click', async () => {
    const button = /** @type {HTMLButtonElement} */ (retestHostsBtn);
    button.disabled = true;
    try {
      const result = await api('/factual/research/allowed-hosts/retest', { method: 'POST' });
      const tested = Array.isArray(result.tested) ? result.tested : [];
      const failed = tested.filter((t) => t.status !== 'PASSED');
      showSourceStatus(
        `${tested.length} sites tested, ${tested.length - failed.length} readable${failed.length ? `. Cannot be read: ${failed.map((t) => `${t.host} (${t.reason})`).join(', ')}` : '.'}`,
        failed.length > 0,
      );
    } catch (err) {
      showSourceStatus(err.message, true);
    } finally {
      button.disabled = false;
      await loadSources();
    }
  });
}

const refreshScriptsBtn = document.getElementById('refresh-scripts-btn');
if (refreshScriptsBtn) {
  refreshScriptsBtn.addEventListener('click', loadScripts);
}

bindPanelToggle('open-research-btn', researchModal);

/** What people search for now, as the studio last read it; the button reads it again. */
async function loadTrends() {
  const list = element('trends-list');
  try {
    const data = await api('/analytics/trends');
    if (!data.enabled) {
      list.innerHTML = '<li class="helper">Trends are turned off in the configuration (STUDIO_TRENDS_ENABLED).</li>';
      return;
    }
    list.innerHTML = data.items.length
      ? data.items.map((t) => `<li title="${escapeHtml((t.news || []).join(' · '))}"><span>${escapeHtml(t.title)}</span><small>${t.approx_traffic ? `~${Number(t.approx_traffic).toLocaleString('ro-RO')}` : '—'}</small></li>`).join('')
      : `<li class="helper">Nothing read yet for ${escapeHtml(data.geo)}. Press «Read trends».</li>`;
  } catch (error) {
    list.innerHTML = `<li class="text-error">${escapeHtml(error instanceof Error ? error.message : 'Trends could not be read.')}</li>`;
  }
}
element('open-research-btn').addEventListener('click', () => { loadTrends(); });
element('trends-refresh').addEventListener('click', async (event) => {
  const button = /** @type {HTMLButtonElement} */ (event.currentTarget);
  button.disabled = true;
  try {
    const result = await api('/analytics/trends/refresh', { method: 'POST' });
    notify(result.status === 'COMPLETED'
      ? `Trends read (${result.geo}): ${result.count} new of ${result.seen}.`
      : `Trends could not be read: ${result.reason || result.status}`);
    await loadTrends();
  } catch (error) {
    notify(error instanceof Error ? error.message : 'Trends could not be read.');
  } finally {
    button.disabled = false;
  }
});

async function loadTopics() {
  const listEl = element('topics-list');
  try {
    const data = await api('/factual/topics');
    const topics = data.topics || [];
    if (topics.length === 0) {
      listEl.innerHTML = '<div class="topics-loading">No topic proposed yet.</div>';
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
    listEl.innerHTML = `<div class="text-error">Loading failed: ${escapeHtml(err.message)}</div>`;
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
  UNVERIFIED: 'Unverified',
  SUPPORTED: 'Supported by the source',
  REFUTED: 'Refuted by the source',
  UNCERTAIN: 'The source does not say',
  DISPUTED: 'Disputed',
};

/** Short, readable provenance: enough of the digest to compare, not a wall of hex. */
function shortHash(hash) {
  return String(hash || '').slice(0, 12);
}

function claimCountsSummary(counts) {
  const entries = Object.entries(counts || {});
  if (!entries.length) return 'No claim extracted yet';
  return entries.map(([status, n]) => `${n} ${CLAIM_STATUS_LABEL[status] || status}`).join(' · ');
}

const HOST_TEST_LABEL = { PASSED: 'readable', FAILED: 'cannot be read' };

/**
 * Why the last test failed, in the closed vocabulary the backend records. A site behind a
 * bot wall and a site that is an empty shell until its scripts run are two different jobs
 * for the Owner, and the reason code is what tells them apart without reading the detail.
 */
const HOST_REASON_LABEL = {
  HTTP_403: 'refused the studio (403)',
  HTTP_ERROR: 'answered with an error',
  RATE_LIMITED: 'limits the requests',
  SCRIPT_ONLY: 'shows nothing without JavaScript',
  NETWORK: 'did not answer',
  OTHER: 'answered with nothing usable',
};

/** Whose search address is in force: the Owner's is a decision, a discovered one a finding. */
const TEMPLATE_ORIGIN_LABEL = { OWNER: 'your search', DISCOVERED: 'its own search' };

/**
 * The authorised sites, each with the result of its last connectivity test. A site is a
 * source only if the studio can actually read it, so the test is next to the entry, and a
 * site that never passed is marked as such rather than assumed fine.
 */
function renderAllowedHosts(rows, health) {
  const box = element('allowed-hosts');
  const allowEl = element('sources-allowlist');
  if (!rows.length) {
    allowEl.textContent = 'No authorised site. Add one below and test it; until then source intake is off.';
    allowEl.className = 'helper-note helper-warn';
    box.innerHTML = '';
    return;
  }
  const passed = rows.filter((r) => r.last_test_status === 'PASSED').length;
  const searchable = rows.filter((r) => r.search_template_origin).length;
  // A count of rows says nothing about whether the studio can work today. The health report
  // answers that: how it would find pages, and how many verified claims a film could rest
  // on. Its reasons are the studio's own words and are shown as they are.
  const line = [
    `${rows.length} authorised sites, ${passed} tested successfully, ${searchable} with a search address.`,
  ];
  if (health) {
    line.push(health.search_provider === 'VERIFIED' ? 'A web search engine is connected.' : 'No web search engine is connected.');
    line.push(`${health.claims_available} verified claims on record.`);
    if (health.status === 'DEGRADED') line.push(...(health.degraded_reasons || []));
  }
  line.push('Only the Owner can change the list; the agents have no tool for it.');
  allowEl.textContent = line.join(' ');
  allowEl.className = (health ? health.status === 'DEGRADED' : !passed) ? 'helper-note helper-warn' : 'helper-note';
  box.innerHTML = rows
    .map((r) => {
      const status = r.last_test_status
        ? `<span class="host-test host-test-${escapeHtml(r.last_test_status.toLowerCase())}" title="${escapeHtml(r.last_test_detail || '')}">${escapeHtml(HOST_TEST_LABEL[r.last_test_status] || r.last_test_status)}${r.last_test_at ? ` · ${escapeHtml(new Date(r.last_test_at).toLocaleString('ro-RO'))}` : ''}</span>`
        : '<span class="host-test host-test-untested">netestat</span>';
      const origin = r.source === 'env' ? '<span class="host-origin">.env</span>' : '';
      const remove = r.source === 'owner'
        ? `<button class="quiet btn-host-remove" data-host="${escapeHtml(r.host)}">Remove</button>`
        : '';
      // The site's own search address: with one, the studio finds pages that exist instead
      // of the Researcher guessing addresses that 404. Only a row the Owner added holds it.
      // "Try it" runs whichever address is in force, the Owner's or the one the studio
      // found, because the search resolves the same way. Typing one in belongs to the
      // Owner's own rows: a site that comes from .env has no entry of his to edit, but its
      // own search address still works and is still worth trying.
      const tryIt = r.search_template_origin
        ? `<button class="quiet btn-host-search-try" data-host="${escapeHtml(r.host)}">Try it</button>`
        : '';
      const search = r.source === 'owner'
        ? `<div class="host-search">
            <input class="host-search-template" data-host="${escapeHtml(r.host)}" value="${escapeHtml(r.search_template || '')}" placeholder="the site's search address, with {query} where the words go (OpenSearch JSON)" title="For example, for a MediaWiki encyclopedia: https://${escapeHtml(r.host)}/w/api.php?action=opensearch&search={query}&limit=5&namespace=0&format=json">
            <button class="quiet btn-host-search-save" data-host="${escapeHtml(r.host)}">Save search</button>
            ${tryIt}
          </div>`
        : tryIt ? `<div class="host-search">${tryIt}</div>` : '';
      // The address the studio found on the site itself, when a test read one. It is shown
      // even where the Owner typed his own, which supersedes it: the point is that he can
      // see what the studio would search this site with, and when it last saw it.
      const found = r.discovered_search_template
        ? `<div class="host-test-detail">${escapeHtml(TEMPLATE_ORIGIN_LABEL.DISCOVERED)}${r.discovered_at ? ` · ${escapeHtml(new Date(r.discovered_at).toLocaleString('ro-RO'))}` : ''}: <code>${escapeHtml(r.discovered_search_template)}</code>${r.search_template ? ' — not used, yours wins' : ''}</div>`
        : '';
      const badge = r.search_template_origin
        ? ` <span class="host-search-badge" title="${escapeHtml(r.search_template || r.discovered_search_template || '')}">${escapeHtml(TEMPLATE_ORIGIN_LABEL[r.search_template_origin] || r.search_template_origin)}</span>`
        : '';
      // The reason code first, then the site's own words for it: the code is the same on
      // every host and can be compared, the detail is what actually came back.
      const why = r.last_test_status === 'FAILED'
        ? `<div class="host-test-detail text-error">${escapeHtml(HOST_REASON_LABEL[r.last_test_reason] || r.last_test_reason || 'cannot be read')}${r.last_test_detail ? ` · ${escapeHtml(r.last_test_detail)}` : ''}</div>`
        : '';
      return `
        <div class="allowed-host-row" data-host="${escapeHtml(r.host)}">
          <code class="allowed-host-name">${escapeHtml(r.host)}</code> ${origin} ${status}${badge}
          <span class="allowed-host-actions">
            <button class="quiet btn-host-test" data-host="${escapeHtml(r.host)}">Test</button>
            ${remove}
          </span>
          ${why}
          ${found}
          ${search}
        </div>`;
    })
    .join('');
  box.querySelectorAll('.btn-host-search-save').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const host = btn.getAttribute('data-host') || '';
      const input = /** @type {HTMLInputElement | null} */ (box.querySelector(`.host-search-template[data-host="${CSS.escape(host)}"]`));
      try {
        await api(`/factual/sources/allowed-hosts/${encodeURIComponent(host)}/search`, {
          method: 'PUT',
          body: JSON.stringify({ template: input && input.value.trim() ? input.value.trim() : null }),
        });
        showSourceStatus(input && input.value.trim() ? `Search address for ${host} saved.` : `Search address for ${host} removed.`, false);
        await loadSources();
      } catch (err) {
        showSourceStatus(err.message, true);
      }
    });
  });
  box.querySelectorAll('.btn-host-search-try').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const host = btn.getAttribute('data-host') || '';
      const button = /** @type {HTMLButtonElement} */ (btn);
      button.disabled = true;
      try {
        const result = await api(`/factual/sources/allowed-hosts/${encodeURIComponent(host)}/search/test`, {
          method: 'POST',
          body: JSON.stringify({ query: 'history of science' }),
        });
        const found = Array.isArray(result.found) ? result.found : [];
        showSourceStatus(
          found.length
            ? `${host} found ${found.length} pages for «history of science»: ${found.map((f) => f.title).join('; ')}`
            : `${host} returned no pages for «history of science»; check the search address.`,
          !found.length,
        );
      } catch (err) {
        showSourceStatus(err.message, true);
      } finally {
        button.disabled = false;
      }
    });
  });
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
  if (button) { button.disabled = true; button.textContent = 'Testing…'; }
  try {
    const result = await api(`/factual/sources/allowed-hosts/${encodeURIComponent(host)}/test`, { method: 'POST' });
    showSourceStatus(
      result.status === 'PASSED'
        ? `${host}: readable. ${result.detail}`
        : `${host}: cannot be used as a source. ${result.detail}`,
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
    // The report is computed from the record and probes nothing, so asking for it on every
    // refresh costs the sites nothing. The list is still shown if it cannot be read.
    let health = null;
    try {
      health = await api('/factual/research/health');
    } catch {
      health = null;
    }
    renderAllowedHosts(data.allowed_host_rows || [], health);

    const sources = data.sources || [];
    if (!sources.length) {
      listEl.innerHTML = '<div class="topics-loading">No source taken in yet.</div>';
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
            · <span>fingerprint ${escapeHtml(shortHash(src.content_hash))}</span>
            · <span>${escapeHtml(new Date(src.fetched_at).toLocaleString('ro-RO'))}</span>
          </div>
          <div class="topic-card-meta">${escapeHtml(claimCountsSummary(src.claim_counts))}</div>
          <div class="source-actions">
            <button class="secondary btn-extract-claims" data-source-id="${escapeHtml(src.id)}">Extract claims with the agent</button>
            <button class="quiet btn-show-claims" data-source-id="${escapeHtml(src.id)}">Show claims</button>
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
    listEl.innerHTML = `<div class="text-error">Loading failed: ${escapeHtml(err.message)}</div>`;
  }
}

async function loadClaims(sourceId) {
  const box = element(`claims-${sourceId}`);
  box.hidden = false;
  box.innerHTML = '<div class="topics-loading">Loading claims…</div>';
  try {
    const data = await api(`/factual/claims?source_id=${encodeURIComponent(sourceId)}`);
    const claims = data.claims || [];
    if (!claims.length) {
      box.innerHTML =
        '<div class="topics-loading">No claim extracted from this source.</div>';
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
    ? ' · verified by an agent'
    : claim.verified_at
      ? ' · verified by the Owner'
      : '';

  const actions = unverified
    ? `<button class="quiet btn-agent-verify" data-claim-id="${escapeHtml(claim.id)}">Verify with a second agent</button>
       <button class="quiet btn-owner-verdict" data-claim-id="${escapeHtml(claim.id)}">Verdict propriu…</button>`
    : '';

  const form = unverified
    ? `<form class="owner-verdict-form" id="verdict-${escapeHtml(claim.id)}" data-claim-id="${escapeHtml(claim.id)}" hidden>
         <select name="status" aria-label="Verdict">
           <option value="SUPPORTED">Supported by the source</option>
           <option value="REFUTED">Refuted by the source</option>
           <option value="UNCERTAIN">The source does not say</option>
         </select>
         <input name="evidence" placeholder="Excerpt from the source (optional)" maxlength="4000" />
         <input name="notes" placeholder="De ce? (obligatoriu)" minlength="3" maxlength="2000" required />
         <button type="submit" class="secondary">Record verdict</button>
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
  claimStatusBox('The agent is reading the source… this can take up to a minute.', false);
  button.disabled = true;
  try {
    const result = await api(`/factual/sources/${sourceId}/extract-with-agent`, {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID() }),
    });
    const n = (result.claims || []).length;
    claimStatusBox(
      `${n} claims extracted, all UNVERIFIED — a second agent must confirm them from the source before scripting.`,
      false,
    );
    // The source cards are re-rendered first: reopening the claims before that would fill a
    // box that is about to be replaced, and the list would vanish under the Owner.
    await loadSources();
    await loadClaims(sourceId);
  } catch (err) {
    claimStatusBox(`Extraction failed: ${err.message}`, true);
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
  button.textContent = 'Checking…';
  claimStatusBox('A second agent is reading the source…', false);
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
    button.textContent = 'Verify with a second agent';
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
    claimStatusBox('Your verdict was recorded.', false);
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
    statusDiv.textContent = 'Fetching the source…';
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
      statusDiv.textContent = `Taken in: "${result.source.title}" — content fingerprint ${shortHash(receipt.content_sha256)}. Nothing counts as true until it is verified.`;
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
  DRAFT: 'Draft',
  VERIFIED_PASS: 'Passed the factual gate',
  APPROVED: 'Approved',
  BLOCKED_UNVERIFIED_CLAIMS: 'Blocked — unverified claims',
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
      picker.append(new Option('Propose a topic first', ''));
    } else {
      picker.append(new Option('Choose a topic…', ''));
      for (const topic of topics) picker.append(new Option(topic.title, topic.id));
      if (previous) picker.value = previous;
    }

    const scripts = scriptsData.scripts || [];
    if (!scripts.length) {
      listEl.innerHTML = '<div class="topics-loading">No script yet.</div>';
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
          <div class="scene-meta">Scene ${scene.scene_number || '?'} · ${(scene.claim_ids || []).length} cited claims${scene.visual_description ? ` · ${escapeHtml(scene.visual_description)}` : ''}</div>
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
        · <span>${(script.claim_ids_json || []).length} claims</span>
        · <span>${(script.scenes_json || []).length} scene</span>
      </div>
      ${blocked ? `<p class="helper-warn helper-note">Blocked: ${(script.unverified_claim_ids_json || []).length} cited claims are not supported by a source.</p>` : ''}
      <div class="script-scenes">${scenes}</div>
      ${status === 'VERIFIED_PASS' ? `<div class="source-actions"><button class="secondary btn-approve-script" data-script-id="${escapeHtml(script.id)}">Approve script</button></div>` : ''}
    </div>`;
}

async function approveScript(button) {
  const scriptId = button.getAttribute('data-script-id');
  button.disabled = true;
  scriptStatusBox('Re-checking the factual gate…', false);
  try {
    await api(`/factual/scripts/${scriptId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID() }),
    });
    scriptStatusBox('Script approved. It now appears in Media Production, ready for a storyboard.', false);
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
      scriptStatusBox('Choose a topic.', true);
      return;
    }
    submit.disabled = true;
    scriptStatusBox('The script writer is writing from the verified claims…', false);
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
        `"${script.title}" — ${(script.scenes_json || []).length} scenes, ${(script.claim_ids_json || []).length} cited claims.`,
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
    statusDiv.textContent = 'Sending the topic for analysis...';

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
      statusDiv.textContent = 'Topic recorded.';
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
      statusDiv.textContent = `Error: ${err.message}`;
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
      ${voiceLine ? `<div class="char-voice">Voice: ${escapeHtml(voiceLine)}</div>` : ''}
      ${identityLine(c)}
      ${referenceBlock(c)}
    </div>
  `;
}

/**
 * Which reference pictures this character has, and the one button that produces them.
 *
 * The set is what a locked face is drawn from, so an empty slot is shown empty rather than
 * summed away in a ratio: "3/5" does not tell the Owner that the profile is the one missing.
 * Producing them spends image credits at the configured image provider, so the button says so
 * and produces nothing until it is pressed a second time — the Owner's deliberate act, which
 * is also why nothing in the daily run calls this route.
 *
 * @param {any} c a Character Bible record
 */
function referenceBlock(c) {
  const summary = referenceSetSummary(c);
  const chips = summary.slots
    .map(
      (slot) =>
        `<span class="ref-chip ${slot.filled ? 'is-filled' : 'is-empty'}" title="${slot.filled ? 'Produsă' : 'Lipsește'}">${escapeHtml(slot.label)}</span>`,
    )
    .join('');
  return `
    <div class="char-references" data-character="${escapeHtml(c.id || '')}">
      <div class="char-row"><span class="char-label">Referințe vizuale</span>${summary.filled}/${summary.total}${summary.complete ? ' · set complet' : summary.filled ? '' : ' · niciuna produsă'}</div>
      <div class="ref-chips">${chips}</div>
      <div class="ref-actions">
        <button class="quiet btn-references" type="button" data-id="${escapeHtml(c.id || '')}">Produ setul de referință</button>
      </div>
      <p class="ref-status" hidden></p>
    </div>`;
}

/**
 * The two presses.
 *
 * The first one only says what the second one will spend; nothing is generated in between and
 * nothing is generated if the Owner walks away. A set already complete is produced again only
 * if he asks for it, so the warning names that too.
 *
 * @param {HTMLElement} block the `.char-references` of one card
 * @param {string} characterId
 */
function armReferenceSet(block, characterId) {
  const status = /** @type {HTMLElement} */ (block.querySelector('.ref-status'));
  const actions = /** @type {HTMLElement} */ (block.querySelector('.ref-actions'));
  status.hidden = false;
  status.className = 'ref-status helper-note helper-warn';
  status.textContent = REFERENCE_CREDIT_WARNING;
  actions.innerHTML =
    `<button class="secondary btn-references-confirm" type="button" data-id="${escapeHtml(characterId)}">Confirmă</button>` +
    '<button class="quiet btn-references-cancel" type="button">Renunță</button>';
}

/** @param {HTMLElement} block @param {string} characterId */
async function produceReferenceSet(block, characterId) {
  const status = /** @type {HTMLElement} */ (block.querySelector('.ref-status'));
  const actions = /** @type {HTMLElement} */ (block.querySelector('.ref-actions'));
  actions.querySelectorAll('button').forEach((node) => {
    /** @type {HTMLButtonElement} */ (node).disabled = true;
  });
  status.className = 'ref-status helper-note';
  status.textContent = 'Se produc referințele la furnizorul de imagini…';
  try {
    const result = await api(`/media/characters/${encodeURIComponent(characterId)}/reference-set`, {
      method: 'POST',
    });
    const produced = Object.keys(result.slots || {}).filter((slot) => result.slots[slot]);
    const failed = Array.isArray(result.failed) ? result.failed : [];
    const cost = result.cost && typeof result.cost === 'object' ? result.cost.usd : null;
    status.className = failed.length ? 'ref-status helper-note helper-warn' : 'ref-status helper-note';
    status.textContent =
      `Setul are acum ${produced.length}/${Object.keys(result.slots || {}).length} sloturi cu ` +
      `referință · cost: ${approvalCostText(cost)}` +
      (failed.length
        ? ` · nereușite: ${failed.map((f) => `${f.slot} (${f.reason})`).join('; ')}`
        : '');
    await loadCharacterBibles();
  } catch (err) {
    status.className = 'ref-status text-error';
    status.textContent = err.message;
    actions.innerHTML = `<button class="quiet btn-references" type="button" data-id="${escapeHtml(characterId)}">Produ setul de referință</button>`;
  }
}

/** Persistent production identity: the bound voice, which fields are locked, and the status. */
function identityLine(c) {
  const binding = c.voice_binding_json || {};
  const locks = c.identity_locks_json || {};
  const lockedFields = Object.keys(locks).filter((k) => locks[k]);
  const parts = [];
  if (binding.voice_id) parts.push(`Bound voice: ${escapeHtml(binding.voice_id)}${binding.model_id ? ` · model ${escapeHtml(binding.model_id)}` : ''}`);
  if (lockedFields.length) parts.push(`Locked: ${escapeHtml(lockedFields.join(', '))}`);
  if (c.consistency_status) parts.push(`Consistency: ${escapeHtml(c.consistency_status)}`);
  if ((c.approved_fallbacks_json || []).length) parts.push(`${c.approved_fallbacks_json.length} approved models`);
  return parts.length ? `<div class="char-voice">${parts.join(' · ')}</div>` : '';
}

async function loadCharacterBibles() {
  const listEl = element('characters-list');
  try {
    const data = await api('/media/character-bible');
    const chars = data.characters || [];
    if (chars.length === 0) {
      listEl.innerHTML =
        '<div class="topics-loading">No character recorded in the Character Bible.</div>';
      return;
    }
    listEl.innerHTML = chars.map(characterCard).join('');
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">Loading characters failed: ${escapeHtml(err.message)}</div>`;
  }
}

// One listener for a list that is rewritten on every read. Producing a reference set spends
// credits, so the path from a click to a generation is short enough to read in one place.
element('characters-list').addEventListener('click', (event) => {
  const target = event.target instanceof Element ? event.target : null;
  if (!target) return;
  const block = /** @type {HTMLElement|null} */ (target.closest('.char-references'));
  if (!block) return;
  const ask = target.closest('.btn-references');
  const confirmed = target.closest('.btn-references-confirm');
  const cancelled = target.closest('.btn-references-cancel');
  const characterId = block.dataset.character || '';
  if (ask) {
    armReferenceSet(block, characterId);
  } else if (confirmed) {
    produceReferenceSet(block, characterId);
  } else if (cancelled) {
    loadCharacterBibles();
  }
});

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
      const voice = info.voice_provider ? ` · voice: ${info.voice_provider}` : ' · voice: substitute';
      note.textContent = `Images: ${info.image_provider}${voice}. Renders can be published.`;
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

    // The story is read before anything is generated. What the review said is the first
    // thing on the card, because it decides whether this film may be produced at all.
    const reviews = await Promise.all(
      scripts.map((script) =>
        api(`/factual/scripts/${script.id}/story-review`).catch(() => ({ verdict: 'NONE' })),
      ),
    );

    listEl.innerHTML = scripts
      .map(
        (script, index) => `
        <div class="topic-card script-card">
          <div class="topic-card-header">
            <strong class="topic-card-title">${escapeHtml(script.title)}</strong>
            <span class="topic-card-novelty">v${script.version}</span>
          </div>
          <div class="topic-card-meta">
            <span>${script.target_duration_seconds}s</span>
            · <span>${script.scene_count} scene</span>
            · <span>${script.claim_count} verified claims</span>
          </div>
          ${storyReviewBlock(reviews[index])}
          <div class="source-actions">
            <button class="quiet btn-story-review" data-script-id="${escapeHtml(script.id)}">Read the story</button>
            <button class="secondary btn-make-storyboard" data-script-id="${escapeHtml(script.id)}">Create storyboard</button>
          </div>
        </div>`,
      )
      .join('');

    listEl.querySelectorAll('.btn-make-storyboard').forEach((btn) => {
      btn.addEventListener('click', () => makeStoryboard(btn));
    });
    listEl.querySelectorAll('.btn-story-review').forEach((btn) => {
      btn.addEventListener('click', () => runStoryReview(btn));
    });
  } catch (err) {
    block.hidden = false;
    listEl.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
  }
}

// The verdict, the checks that failed, and where the Director expects to lose the viewer.
// A verdict of NONE is not a complaint: it means nobody has read this story yet.
function storyReviewBlock(review) {
  if (!review || review.verdict === 'NONE') {
    return `<div class="story-review is-none">The story has not been read yet. Nothing goes
      into production before that.</div>`;
  }
  const failed = (review.failed || []).slice(0, 4);
  const marks = ['at_0', 'at_3', 'at_5', 'at_10', 'at_15', 'at_20', 'at_25', 'at_end'];
  const retention = review.retention || {};
  const curve = marks
    .filter((mark) => typeof retention[mark] === 'number')
    .map((mark) => `${mark.replace('at_', '')}: ${retention[mark]}%`)
    .join(' · ');
  const state = review.verdict === 'PASS' ? 'is-pass' : 'is-hold';
  return `
    <div class="story-review ${state}">
      <div class="story-review-head">
        <strong>${escapeHtml(review.verdict)}</strong>
        <span>${Number(review.estimated_seconds || 0).toFixed(1)}s of narration</span>
      </div>
      ${failed.length ? `<div class="story-review-failed">Nu trece: ${failed.map(escapeHtml).join(', ')}</div>` : ''}
      ${curve ? `<div class="story-review-curve">Estimated retention — ${escapeHtml(curve)}</div>` : ''}
      ${retention.collapse_at ? `<div class="story-review-curve">Se pierde la ${escapeHtml(String(retention.collapse_at))}s: ${escapeHtml(String(retention.why || ''))}</div>` : ''}
      ${(review.notes || []).slice(0, 3).map((note) => `<div class="motion-reason">${escapeHtml(String(note))}</div>`).join('')}
    </div>`;
}

async function runStoryReview(button) {
  const scriptId = button.getAttribute('data-script-id');
  button.disabled = true;
  mediaStatusMsg.hidden = false;
  mediaStatusMsg.className = 'dialog-status-msg';
  mediaStatusMsg.textContent = 'The Director is reading the story before production…';
  try {
    const review = await api(`/factual/scripts/${scriptId}/story-review`, { method: 'POST' });
    mediaStatusMsg.textContent = `Verdict: ${review.verdict}. ${(review.notes || [])[0] || ''}`;
    await loadAwaitingStoryboard();
  } catch (err) {
    mediaStatusMsg.className = 'dialog-status-msg text-error';
    mediaStatusMsg.textContent = err.message;
  } finally {
    button.disabled = false;
  }
}

async function makeStoryboard(button) {
  const scriptId = button.getAttribute('data-script-id');
  button.disabled = true;
  mediaStatusMsg.hidden = false;
  mediaStatusMsg.className = 'dialog-status-msg';
  mediaStatusMsg.textContent = 'Building the storyboard from the approved script…';
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

// Why this film exists, in the studio's own words: the idea's argument, the one message,
// the hook, the closing question, and the look every shot inherits. Folded away by default.
function productionPackageBlock(pack) {
  if (!pack) return '';
  const why = pack.why_this_video_should_exist || {};
  const bible = pack.master_visual_bible || {};
  const shots = pack.shot_list || [];
  const line = (label, value) =>
    value ? `<div><strong>${label}:</strong> ${escapeHtml(String(value))}</div>` : '';
  return `
    <details class="motion-explain">
      <summary>Why this film</summary>
      ${line('Faptul', why.core_fact)}
      ${line('Why it matters', why.why_it_matters)}
      ${line('Mesajul', pack.core_message)}
      ${line('Hook', pack.hook)}
      ${line('Payoff', why.payoff)}
      ${line('Call to action', `${(pack.cta || {}).text || ''} (${(pack.cta || {}).kind || '—'})`)}
      ${line('Story review', (pack.approval || {}).story_review)}
      ${line('Expected duration', `${Number(pack.expected_duration_seconds || 0).toFixed(1)}s`)}
      ${line('Privirea filmului', [bible.style, bible.palette, bible.lighting].filter(Boolean).join(' · '))}
      ${
        shots.length
          ? `<div><strong>Cadre:</strong> ${shots
              .map((shot) => `#${shot.scene_index} ${escapeHtml(String(shot.story_purpose || '—'))}`)
              .join(', ')}</div>`
          : ''
      }
      ${
        (pack.trusted_sources || []).length
          ? `<div><strong>Sources:</strong> ${(pack.trusted_sources || [])
              .slice(0, 4)
              .map((source) => escapeHtml(String(source.publisher || source.url)))
              .join(', ')}</div>`
          : ''
      }
    </details>`;
}

// Why each scene was filmed the way it was. The router states what the scene required and
// what it chose; this only reads it back. A studio that cannot say why it spent three
// dollars on a shot cannot be asked whether the shot was worth it.
function motionExplanation(motion, scenes, notes) {
  if (!motion && (!scenes || scenes.length === 0)) return '';
  const test = motion && motion.environment === 'TEST';
  const head = motion
    ? `<div class="motion-head"><span class="${test ? 'env-banner is-test' : 'env-banner is-production'}">${
        test ? 'TEST' : 'PRODUCTION'
      }</span> <span>${motion.clips || 0} din ${motion.scenes || 0} scene filmate · ${
        motion.estimated_usd != null ? `${Number(motion.estimated_usd).toFixed(2)} USD` : 'cost not measured'
      }${motion.from_prompt ? ' · from text, no paid frame' : ''}</span></div>`
    : '';
  const rows = (scenes || [])
    .map((scene) => {
      const decision = scene.decision || {};
      const price =
        scene.quoted_usd != null
          ? `${Number(scene.quoted_usd).toFixed(2)} USD (cotat de vendor)`
          : decision.price_usd != null
            ? `${Number(decision.price_usd).toFixed(2)} USD (recorded price)`
            : 'unknown price';
      const outcome = scene.refused
        ? `<span class="text-error">not filmed: ${escapeHtml(String(scene.refused))}</span>`
        : `${scene.bytes ? 'filmed' : 'no clip'}`;
      return `
        <li>
          <strong>Scena #${scene.scene_index}</strong> · ${escapeHtml(String(scene.tier || '—'))} ·
          ${escapeHtml(String(scene.model || decision.model_id || '—'))} · ${escapeHtml(price)} · ${outcome}
          ${decision.reason ? `<div class="motion-reason">${escapeHtml(String(decision.reason))}</div>` : ''}
        </li>`;
    })
    .join('');
  const noteList = (notes || [])
    .map((note) => `<li class="motion-reason">${escapeHtml(String(note))}</li>`)
    .join('');
  return `
    <details class="motion-explain">
      <summary>Why these models</summary>
      ${head}
      <ul class="motion-scenes">${rows}${noteList}</ul>
    </details>`;
}

async function loadMediaStoryboards() {
  const listEl = element('storyboards-list');
  try {
    const data = await api('/media/storyboards');
    const storyboards = data.storyboards || [];
    if (storyboards.length === 0) {
      listEl.innerHTML = `
        <div class="topics-loading">
          No storyboard in the pipeline yet.
          <br>Press "Create demo fixture" to generate a verified 9:16 script automatically.
        </div>
      `;
      return;
    }

    const itemsHtml = await Promise.all(
      storyboards.map(async (sb) => {
        let scenes = [];
        let qcReport = null;
        let motion = null;
        let motionScenes = [];
        let motionNotes = [];
        let pack = null;
        try {
          pack = await api(`/media/storyboards/${sb.id}/production-package`);
        } catch (_) {}
        try {
          const detail = await api(`/media/storyboards/${sb.id}`);
          scenes = detail.scenes || [];
          motion = detail.motion || null;
          motionScenes = detail.motion_scenes || [];
          motionNotes = detail.motion_notes || [];
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
          // The film itself: the asset quality control measured is the one to watch.
          const assetId = qcReport ? qcReport.media_asset_id : null;
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
              ${
                assetId
                  ? `<button class="video-play" data-asset="${escapeHtml(assetId)}" title="Play the film">▶ Play</button>`
                  : '<div class="tag">9:16 Video</div>'
              }
            </div>
            <div class="video-details">
              ${
                assetId
                  ? `<div class="video-actions"><a class="quiet" href="#" data-download="${escapeHtml(assetId)}">Download the file</a></div>`
                  : ''
              }
              <div><strong>Measured format:</strong> ${
                tech.measured_width
                  ? `${tech.measured_width}x${tech.measured_height} · ${tech.measured_duration_seconds}s · ${escapeHtml(String(tech.video_codec || '—'))}`
                  : 'not measured'
              }</div>
              <div>${qcBadge}</div>
              ${qcScoresHtml}
              ${motionExplanation(motion, motionScenes, motionNotes)}
              <div><strong>File SHA-256 fingerprint:</strong></div>
              <div class="provenance-badge">${escapeHtml(tech.provenance_sha256 || 'unavailable')}</div>
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
              <button class="btn-qc-video" data-id="${sb.id}">Check QC</button>
            </div>
          </div>

          ${productionPackageBlock(pack)}

          <div class="storyboard-scenes-grid">
            ${scenesHtml}
          </div>

          ${renderHtml}
        </div>
      `;
      }),
    );

    listEl.innerHTML = itemsHtml.join('');

    // The film plays where the film is. The Owner's key travels in a header, so the bytes
    // are fetched once and played from a blob rather than handed to <video src>, which
    // could not authenticate. The same bytes are what the download link saves.
    const playFilm = async (assetId, container, trigger) => {
      const button = /** @type {HTMLButtonElement | null} */ (trigger);
      if (button) { button.disabled = true; button.textContent = 'Loading…'; }
      try {
        const response = await fetch(`/api/v1/media/assets/${assetId}/stream`, {
          headers: { Authorization: `Bearer ${ownerToken}` },
          cache: 'no-store',
        });
        if (!response.ok) throw new Error(`The file could not be read (${response.status}).`);
        const url = URL.createObjectURL(await response.blob());
        const video = document.createElement('video');
        video.src = url;
        video.controls = true;
        video.autoplay = true;
        video.playsInline = true;
        video.className = 'video-player-9-16';
        container.innerHTML = '';
        container.append(video);
        return url;
      } catch (err) {
        if (button) { button.disabled = false; button.textContent = '▶ Play'; }
        alert(`Could not play the film: ${err.message}`);
        return null;
      }
    };

    listEl.querySelectorAll('.video-play').forEach((btn) => {
      btn.addEventListener('click', () => {
        const assetId = btn.getAttribute('data-asset');
        const container = btn.parentElement;
        if (assetId && container) playFilm(assetId, container, btn);
      });
    });

    listEl.querySelectorAll('[data-download]').forEach((link) => {
      link.addEventListener('click', async (event) => {
        event.preventDefault();
        const assetId = link.getAttribute('data-download');
        if (!assetId) return;
        try {
          const response = await fetch(`/api/v1/media/assets/${assetId}/stream`, {
            headers: { Authorization: `Bearer ${ownerToken}` },
            cache: 'no-store',
          });
          if (!response.ok) throw new Error(`The file could not be read (${response.status}).`);
          const url = URL.createObjectURL(await response.blob());
          const save = document.createElement('a');
          save.href = url;
          save.download = `short_9_16_${assetId.slice(0, 8)}.mp4`;
          save.click();
          setTimeout(() => URL.revokeObjectURL(url), 30000);
        } catch (err) {
          alert(`Could not download the film: ${err.message}`);
        }
      });
    });

    listEl.querySelectorAll('.btn-render-video').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        if (!id) return;
        btn.textContent = 'Rendering...';
        // @ts-ignore
        btn.disabled = true;
        try {
          await api(`/media/render/${id}`, { method: 'POST' });
          await loadMediaStoryboards();
          await refresh();
        } catch (err) {
          alert(`Render failed: ${err.message}`);
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
          alert(`QC failed: ${err.message}`);
          btn.textContent = 'Check QC';
          // @ts-ignore
          btn.disabled = false;
        }
      });
    });
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">Loading media production failed: ${escapeHtml(err.message)}</div>`;
  }
}

if (generateDemoStoryboardBtn) {
  generateDemoStoryboardBtn.addEventListener('click', async () => {
    mediaStatusMsg.hidden = false;
    mediaStatusMsg.className = 'dialog-status-msg';
    mediaStatusMsg.textContent =
      'Creating demo fixture (topic, script and UNVERIFIED claim)...';
    try {
      const fixture = await api('/media/storyboards/demo-fixture', {
        method: 'POST',
      });
      mediaStatusMsg.textContent =
        fixture.next_step || 'Fixture created. Verify the claims in the Research panel.';
      setTimeout(() => {
        mediaStatusMsg.hidden = true;
      }, 8000);
      await loadMediaStoryboards();
      await refresh();
    } catch (err) {
      mediaStatusMsg.className = 'dialog-status-msg text-error';
      mediaStatusMsg.textContent = `Error: ${err.message}`;
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
  NOT_CONFIGURED: 'Channel slot. It has no real YouTube channel ID and cannot publish.',
  AUTH_REQUIRED: 'Channel ID set, but no verified credentials. It cannot publish.',
  AUTHENTICATED: 'Channel ID and credentials present.',
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
      status.textContent = result.active === false ? 'The budget was retired.' : `${result.period === 'DAILY' ? 'Daily' : 'Monthly'} budget of ${result.limit_usd} USD set.`;
      await loadBudget();
    } catch (error) {
      status.className = 'dialog-status-msg text-error';
      status.textContent = error instanceof Error ? error.message : 'The budget could not be saved.';
    }
  });
}
const closeBooksBtn = document.getElementById('close-books-btn');
if (closeBooksBtn) {
  closeBooksBtn.addEventListener('click', async () => {
    const status = element('budget-status');
    status.hidden = false;
    status.className = 'dialog-status-msg';
    status.textContent = 'The Accountant is closing the day…';
    try {
      const result = await api('/economy/books/close', { method: 'POST' });
      status.textContent = `${result.headline}. ${result.report ? result.report.summary : result.blocked || ''}`;
      await loadBudget();
    } catch (error) {
      status.className = 'dialog-status-msg text-error';
      status.textContent = error instanceof Error ? error.message : 'Closing failed.';
    }
  });
}

if (refreshPublishingBtn) {
  refreshPublishingBtn.addEventListener('click', loadPublishingHub);
}

/** Labels for the stored production policy; the value itself lives on the channel row. */
const PRODUCTION_POLICY_LABEL = {
  FLEXIBLE: 'FLEXIBLE · technology chosen per video',
  CONSISTENCY_LOCKED: 'CONSISTENCY LOCKED · character identity never changes',
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
          'YouTube credentials present. Publishing uses the official API.';
      } else {
        publisherBanner.className = 'dialog-status-msg text-error';
        publisherBanner.textContent =
          'No YouTube credentials configured: publishing is off. Set STUDIO_YOUTUBE_CLIENT_ID, STUDIO_YOUTUBE_CLIENT_SECRET and STUDIO_YOUTUBE_REFRESH_TOKEN in .env. The studio never simulates publishing.';
      }
      publisherBanner.hidden = false;
    }
    if (channels.length === 0) {
      channelsEl.innerHTML =
        '<div class="topics-loading">No distribution channel configured.</div>';
    } else {
      channelsEl.innerHTML = channels
        .map(
          (c) => `
        <div class="channel-item">
          <div class="channel-info">
            <h4>${escapeHtml(c.channel_name)}</h4>
            <div class="channel-meta">Type: <strong>${escapeHtml(c.channel_type)}</strong> · Remote ID: <code>${escapeHtml(c.remote_channel_id || 'not set')}</code></div>
            <div class="channel-meta">${escapeHtml(CHANNEL_STATUS_HINT[c.status] || 'Unknown state.')}</div>
            <div class="channel-meta">Production policy: <span class="policy-tag ${c.production_policy === 'CONSISTENCY_LOCKED' ? 'policy-locked' : 'policy-flexible'}">${escapeHtml(PRODUCTION_POLICY_LABEL[c.production_policy] || 'not set')}</span>${c.allow_production_override === false ? ' · per-episode overrides off' : ''}</div>
          </div>
          <div class="channel-meta channel-bind">
            <label>Cont YouTube
              <select data-bind-select="${escapeHtml(c.id)}" aria-label="YouTube account for ${escapeHtml(c.channel_name)}">
                <option value="">Nelegat</option>
                ${accounts.map((a) => `<option value="${escapeHtml(a.id)}" ${a.id === c.youtube_connection_id ? 'selected' : ''}>${escapeHtml(a.name)}${a.channel_title ? ` · ${escapeHtml(a.channel_title)}` : ''}</option>`).join('')}
              </select>
            </label>
            <button class="secondary" data-bind-channel="${escapeHtml(c.id)}" data-event="${escapeHtml(c.event_id || '')}">Bind</button>
            <span class="helper">${c.publisher_ready ? `Publishes to ${escapeHtml(c.youtube_channel_title || c.youtube_connection_name || '')}` : 'Not bound: this slot does not publish and has no analytics.'}</span>
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
            publishingStatusMsg.textContent = err instanceof Error ? err.message : 'Binding failed.';
          }
        });
      });
    }

    const publications = pubData.publications || [];
    if (publications.length === 0) {
      pubListEl.innerHTML =
        '<div class="topics-loading">No publication recorded yet. Use the button above to publish an approved video.</div>';
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
                ? '<span class="pub-sim-note">Local simulation — no video on YouTube</span>'
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
                <span>Remote ID: <code>${escapeHtml(p.remote_video_id || '—')}</code></span>
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
      channelsEl.innerHTML = `<div class="text-error">Channels failed to load: ${escapeHtml(err.message)}</div>`;
    if (pubListEl)
      pubListEl.innerHTML = `<div class="text-error">Publications failed to load: ${escapeHtml(err.message)}</div>`;
  }
}

if (triggerQuickPublishBtn) {
  triggerQuickPublishBtn.addEventListener('click', async () => {
    publishingStatusMsg.hidden = false;
    publishingStatusMsg.className = 'dialog-status-msg';
    publishingStatusMsg.textContent =
      'Checking the media pipeline and finding the latest QC-approved video...';
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
          'No video with a QC PASSED report was found. Create a storyboard and a 9:16 render in Media Production first.';
        return;
      }

      publishingStatusMsg.textContent = `Content Gate check and private upload for MediaAsset ${targetAssetId}...`;
      const pubRes = await api(`/publishing/publish-asset/${targetAssetId}`, {
        method: 'POST',
      });

      if (pubRes.status === 'PUBLISHED') {
        publishingStatusMsg.className = 'dialog-status-msg';
        publishingStatusMsg.textContent = `Video uploaded privately to YouTube. Remote ID: ${pubRes.remote_video_id}`;
      } else if (pubRes.status === 'PUBLISHED_SIMULATED') {
        publishingStatusMsg.className = 'dialog-status-msg text-error';
        publishingStatusMsg.textContent =
          'SIMULATED upload: there is no video on YouTube. Configure real credentials.';
      } else {
        publishingStatusMsg.className = 'dialog-status-msg text-error';
        publishingStatusMsg.textContent = `Publication not finished. State: ${pubRes.status}. ${pubRes.error_detail || ''}`;
      }
      await loadPublishingHub();
      await refresh();
    } catch (err) {
      publishingStatusMsg.className = 'dialog-status-msg text-error';
      publishingStatusMsg.textContent = `Publishing error: ${err.message}`;
    }
  });
}

function render(data) {
  element('studio-name').textContent = data.studio.name;
  element('connection').textContent = 'Connected · Owner';
  const staff = officeState.agents.length;
  element('room-caption').textContent = staff
    ? `${staff} ${staff === 1 ? 'employee' : 'employees'} at their desks · AMN-AI headquarters, live`
    : 'AMN-AI headquarters, live';
  element('snapshot-time').textContent =
    `Updated ${new Date(data.captured_at).toLocaleTimeString('en-GB', { timeZone: data.studio.timezone })}`;
  renderSwitch(data.policy.autonomy_stopped);
  renderEnvironment(data.policy.environment);
  renderAutonomyMode(data.policy);
  ledger.timezone = data.studio.timezone;
  const agentNames = Object.fromEntries(officeState.agents.map((a) => [a.id || a.agent_id, a.display_name]));
  ledger.setNames(agentNames);
  liveWindows.timezone = data.studio.timezone;
  mailThread.timezone = data.studio.timezone;
  liveWindows.setNames(agentNames);
  ledger.add(data.events || []);
  element('ledger-count').textContent = `${ledger.events.size} entries`;

  const labels = {
    agents: 'Agents',
    providers: 'AI providers',
    workflows: 'Automatizare',
    research: 'Fact research',
    media: 'Media production',
    publishing: 'Publishing',
    story: 'Office Serial',
    treasury: 'Trezorerie VR$',
    procurement: 'VendorShop',
    financing: 'Financing',
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
// The studio's environment is its own state, read from the policy the server owns: the
// page displays it and asks for a change, it never decides it. A test that looks like a
// production run is how an experiment buys eight generated shots.
function renderEnvironment(environment) {
  const value = environment === 'PRODUCTION' ? 'PRODUCTION' : 'TEST';
  const test = value === 'TEST';
  const banner = element('environment-banner');
  banner.hidden = false;
  banner.textContent = test ? 'TEST ENVIRONMENT' : 'PRODUCTION';
  banner.classList.toggle('is-test', test);
  banner.classList.toggle('is-production', !test);
  banner.title = test
    ? 'The minimum is rendered, on the cheapest compatible model, with cost caps per generation and per second.'
    : 'Rendering uses the cheapest model that reaches the quality each scene needs.';
  environmentButton.disabled = false;
  environmentButton.classList.toggle('is-test', test);
  environmentButton.classList.toggle('is-production', !test);
  element('environment-state').textContent = pendingEnvironment ? '…' : test ? 'TEST' : 'PROD';
  environmentButton.setAttribute('aria-pressed', String(!test));
}

function renderSwitch(stopped) {
  const on = !stopped;
  stopButton.classList.toggle('is-on', on);
  stopButton.classList.toggle('is-pending', Boolean(pendingCommand));
  element('switch-state').textContent = pendingCommand ? '…' : on ? 'ON' : 'OFF';
  stopButton.setAttribute('aria-pressed', String(on));
  stopButton.title = pendingCommand
    ? 'The last command was not confirmed; press to check it again.'
    : on
      ? 'Autonomy is on. Press for a persistent stop.'
      : 'Autonomy is off. Press to turn it on; the mode stays Manual.';
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
      element('ledger-count').textContent = `${ledger.events.size} entries`;
    } catch (error) {
      console.warn('ledger sync failed', error);
    }
    // The approvals have their own, slower clock; this only lets them ride the same poll.
    await loadApprovals();
    return true;
  } catch (error) {
    if (generation !== epoch) return false;
    connected = false;
    element('connection').textContent = 'Disconnected';
    element('office-fps').textContent = 'Data not refreshed';
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
  liveWindows.closeAll();
  thinkingAgents.clear();
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
  pendingMode = null;
  approvalsRouteMissing = false;
  approvalsLastRead = 0;
  approvalsList.replaceChildren();
  element('approvals-count').textContent = '—';
  element('autonomy-mode-tag').textContent = '—';
  element('autonomy-mode-meaning').textContent = '—';
  governanceNote('');
  element('modules').replaceChildren();
  element('studio-name').textContent = 'AMN-AI';
  element('connection').textContent = 'Neconectat';
  element('logout').hidden = true;
});

environmentButton.addEventListener('click', async () => {
  if (busy || !connected || !state) return;
  busy = true;
  environmentButton.disabled = true;
  notify('');
  const generation = epoch;
  const next = state.policy.environment === 'TEST' ? 'PRODUCTION' : 'TEST';
  pendingEnvironment ||= {
    schema_version: 1,
    command_id: crypto.randomUUID(),
    expected_version: state.policy.version,
    environment: next,
  };
  try {
    await api('/owner/environment', {
      method: 'POST',
      body: JSON.stringify(pendingEnvironment),
    });
    if (generation !== epoch) return;
    pendingEnvironment = null;
  } catch (error) {
    if (generation !== epoch) return;
    if (error.status === 409 || error.status === 422) pendingEnvironment = null;
    notify(error.message);
  } finally {
    if (generation === epoch) {
      busy = false;
      await refresh();
    }
  }
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

/* ---------------------------------------------------------------------------
 * Governance: the mode the studio is in, and what a supervised studio stopped to ask.
 *
 * `policy.autonomy_mode` has been a real value since migration 0043 and nothing on this page
 * read it, so a studio that had been running whole days unattended looked, to its Owner,
 * exactly like one that asks before every step. The panel shows the mode, says in one sentence
 * what it means for the day — the sentence every agent is given when the mode moves — and
 * offers the other two. The mode decides what the studio may *attempt*; it never decides what
 * a gate *concludes*, and the footnote under every request says so.
 * ------------------------------------------------------------------------- */

const modeButtons = element('autonomy-mode-buttons');
const modeNote = element('autonomy-mode-note');
const approvalsList = element('approvals-list');
/** The mode command already sent and not yet confirmed; a retry repeats it, never a second one. */
let pendingMode = null;

/** @param {string} message @param {boolean} [bad] */
function governanceNote(message, bad) {
  modeNote.hidden = !message;
  modeNote.textContent = message || '';
  modeNote.className = bad ? 'helper-note helper-warn' : 'helper-note';
}

/** @param {{autonomy_mode?: string, autonomy_stopped?: boolean, version?: number}} policy */
function renderAutonomyMode(policy) {
  const mode = policy.autonomy_mode;
  element('autonomy-mode-tag').textContent = pendingMode ? '…' : autonomyModeLabel(mode);
  element('autonomy-mode-meaning').textContent = autonomyModeMeaning(mode);
  modeButtons.querySelectorAll('.mode-btn').forEach((node) => {
    const button = /** @type {HTMLButtonElement} */ (node);
    const current = button.dataset.mode === mode;
    button.classList.toggle('is-current', current);
    button.setAttribute('aria-pressed', String(current));
    // Only the mode the studio is already in is dead; a blocked promotion stays pressable so
    // that pressing it answers *why* instead of leaving the Owner with a grey button.
    button.disabled = current;
  });
}

modeButtons.addEventListener('click', async (event) => {
  const target = event.target instanceof Element ? event.target.closest('.mode-btn') : null;
  if (!target || !state || !connected) return;
  const mode = /** @type {HTMLElement} */ (target).dataset.mode || '';
  if (mode === state.policy.autonomy_mode) return;
  const blocked = promotionBlockedReason(state.policy, mode);
  if (blocked) {
    // The stop is in the snapshot, so this refusal is said here rather than spent on a request
    // the server would refuse anyway. SAFE_MODE is not in the snapshot: that refusal arrives
    // from the server below, in its own words.
    governanceNote(blocked, true);
    return;
  }
  if (busy) return;
  busy = true;
  governanceNote('');
  const generation = epoch;
  try {
    // A command that was not confirmed is repeated with its own id, so a slow network is one
    // decision; a command for a *different* mode replaces it, so an unconfirmed press never
    // becomes the mode the Owner has since changed his mind about.
    if (!pendingMode || pendingMode.autonomy_mode !== mode) {
      pendingMode = autonomyModeCommand(state.policy, mode, crypto.randomUUID());
    }
    await api('/owner/autonomy-mode', { method: 'POST', body: JSON.stringify(pendingMode) });
    if (generation !== epoch) return;
    pendingMode = null;
    governanceNote(`Modul de autonomie este acum ${autonomyModeLabel(mode)}.`, false);
  } catch (error) {
    if (generation !== epoch) return;
    if (error.status === 409 || error.status === 422) pendingMode = null;
    governanceNote(error.message, true);
  } finally {
    if (generation === epoch) {
      busy = false;
      await refresh();
      await loadApprovals(true);
    }
  }
});

/**
 * The requests a SUPERVISED studio wrote instead of acting.
 *
 * Read at most twice a minute rather than with every five-second snapshot: an approval is a
 * decision that stands for a day, and a list nobody answered does not become more true by
 * being fetched sixty times. A build whose backend has no such route says so once and stops
 * asking, because a panel that repeats a 404 every poll teaches its Owner to ignore it.
 */
const APPROVALS_INTERVAL_MS = 30000;
let approvalsLastRead = 0;
let approvalsRouteMissing = false;

/** @param {ReturnType<typeof readApprovals>[number]} request @param {number} now */
function approvalCard(request, now) {
  const tier = request.risk_tier || '—';
  // Beside the figure and not under it in the evidence line: the Owner answers the number, so
  // a figure that priced only part of the film has to say so where the number is read.
  const caveat = approvalCaveat(request.evidence);
  return `
    <article class="approval-card">
      <div class="approval-head">
        <span class="approval-action" title="${escapeHtml(request.action)}">${escapeHtml(request.action_label || 'acțiune nenumită')}</span>
        <span class="tag approval-tier" title="${escapeHtml(riskTierMeaning(tier))}">${escapeHtml(tier)}</span>
      </div>
      ${request.subject ? `<div class="approval-meta">Despre: ${escapeHtml(request.subject)}</div>` : ''}
      <div class="approval-meta">Cost: ${escapeHtml(request.cost_label)}${caveat ? ` <span class="approval-caveat">(${escapeHtml(caveat)})</span>` : ''} · ${escapeHtml(approvalExpiryText(request.expires_at, now))} · ${request.reversible ? 'reversibilă' : 'ireversibilă'}</div>
      ${request.requester ? `<div class="approval-meta">Cerută de ${escapeHtml(request.requester)}</div>` : ''}
      ${request.evidence ? `<p class="approval-evidence">${escapeHtml(request.evidence)}</p>` : ''}
      <div class="source-actions">
        <button class="secondary btn-approval" data-id="${escapeHtml(request.id)}" data-decision="APPROVED">Aprobă</button>
        <button class="quiet btn-approval" data-id="${escapeHtml(request.id)}" data-decision="REFUSED">Refuză</button>
      </div>
      <p class="approval-footnote">Aprobarea lasă o acțiune permisă să se întâmple; nu transformă refuzul unei porți dure în trecere.</p>
    </article>`;
}

/** @param {boolean} [force] read now, whatever the interval says */
async function loadApprovals(force) {
  if (!ownerToken || !connected) return;
  if (approvalsRouteMissing && !force) return;
  const now = Date.now();
  if (!force && now - approvalsLastRead < APPROVALS_INTERVAL_MS) return;
  approvalsLastRead = now;
  try {
    const data = await api(APPROVALS_PATH);
    approvalsRouteMissing = false;
    const pending = readApprovals(data).filter((request) => request.pending);
    element('approvals-count').textContent = pending.length
      ? `${pending.length} în așteptare`
      : 'niciuna';
    approvalsList.innerHTML = pending.length
      ? pending.map((request) => approvalCard(request, Date.now())).join('')
      : '<div class="topics-loading">Nicio cerere nu așteaptă decizia Proprietarului.</div>';
  } catch (err) {
    if (err.status === 404) {
      approvalsRouteMissing = true;
      element('approvals-count').textContent = '—';
      approvalsList.innerHTML =
        '<div class="topics-loading">Backend-ul acestui build nu răspunde încă la ' +
        '/owner/approvals. Cererile există în baza de date; ruta care le arată și le ' +
        'răspunde nu este instalată.</div>';
      return;
    }
    approvalsList.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
  }
}

approvalsList.addEventListener('click', async (event) => {
  const target = event.target instanceof Element ? event.target.closest('.btn-approval') : null;
  if (!target || busy) return;
  const button = /** @type {HTMLButtonElement} */ (target);
  const card = button.closest('.approval-card');
  card?.querySelectorAll('button').forEach((node) => {
    /** @type {HTMLButtonElement} */ (node).disabled = true;
  });
  const id = button.dataset.id || '';
  const decision = button.dataset.decision || '';
  busy = true;
  const generation = epoch;
  try {
    const command = approvalDecisionCommand(id, decision, crypto.randomUUID());
    await api(APPROVAL_DECISION_PATH, {
      method: 'POST',
      body: JSON.stringify(command),
    });
    if (generation !== epoch) return;
    governanceNote(
      decision === 'APPROVED'
        ? 'Cererea a fost aprobată; studioul poate relua acțiunea permisă.'
        : 'Cererea a fost refuzată; refuzul rămâne în registru.',
      false,
    );
  } catch (error) {
    if (generation !== epoch) return;
    governanceNote(error.message, true);
  } finally {
    if (generation === epoch) {
      busy = false;
      await loadApprovals(true);
      await refresh();
    }
  }
});

element('refresh-approvals-btn').addEventListener('click', () => loadApprovals(true));

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

// The live windows are the main page's dependents: when it goes away, they go with it.
window.addEventListener('pagehide', () => liveWindows.closeAll());

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
  TERMINATE_AGENT: 'Termination',
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
  if (agent.runs === 0) return 'no run in the window';
  return `${agent.runs} runs · ${Math.round(agent.failure_rate * 100)}% failures`;
}

async function loadWorkforce() {
  const summaryEl = element('workforce-summary');
  const agentsEl = element('workforce-agents');
  try {
    const data = await api('/workforce/measurements');
    summaryEl.innerHTML = `
      <div class="wf-stat"><span class="wf-stat-value">${data.active_agents}</span><span class="wf-stat-label">active agents</span></div>
      <div class="wf-stat"><span class="wf-stat-value">${data.queue_backlog}</span><span class="wf-stat-label">queued tasks</span></div>
      <div class="wf-stat"><span class="wf-stat-value">${data.dead_letter_tasks}</span><span class="wf-stat-label">abandoned tasks</span></div>
      <div class="wf-stat"><span class="wf-stat-value">${data.idle_agents.length}</span><span class="wf-stat-label">without any run</span></div>`;
    summaryEl.insertAdjacentHTML(
      'beforeend',
      `<p class="helper-note wf-window">Measured over the last ${data.window_days} days, from recorded runs.</p>`,
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
        '<div class="topics-loading">No proposal. The measurements do not support a staffing change now.</div>';
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
               <input class="wf-notes" placeholder="Reason (required to reject)" maxlength="2000" />
               <button class="secondary btn-decide" data-id="${escapeHtml(proposal.id)}" data-approve="true">Approve</button>
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
    workforceStatus('Write why you reject the proposal; the reason stays in the history.', true);
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
        ? `Approved and applied: ${PROPOSAL_TYPE_LABEL[result.proposal_type] || result.proposal_type}.`
        : 'Proposal rejected; the reason was recorded.',
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
  workforceStatus('Re-reading the measurements…', false);
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
  VR_RECEIVABLE: 'Receivable',
  VR_DEBT: 'Datorie',
  PENDING_EXTERNAL: 'Collected, not settled',
  FORECAST: 'Estimare',
};

const LEDGER_KIND_LABEL = {
  MINT: 'Emisiune VR$',
  REVERSAL: 'Stornare',
  OWNER_CAPITAL: 'Aport Owner',
  OWNER_LOAN: 'Owner loan',
  PROVIDER_COST: 'Provider cost',
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

/**
 * One budget against its period. The percentage is of spent plus held, not of spent alone,
 * which is why the held sum is printed beside it: a film in production has taken that money
 * out of what is still free to spend, and a card that showed only what was paid would tell
 * the Owner the day has room it does not have.
 */
function budgetCard(period) {
  const label = period.period === 'DAILY' ? 'Daily' : 'Monthly';
  const reserved = period.reserved_usd_micros
    ? `<div class="helper">${escapeHtml(period.reserved_usd)} USD held for films in production</div>`
    : '';
  return `<div class="budget-card budget-${escapeHtml(period.state)}"><span class="stat-label">${escapeHtml(label)} · ${escapeHtml(period.state)}</span><strong>${escapeHtml(period.spent_usd)} / ${escapeHtml(period.limit_usd)} USD</strong><span>remaining ${escapeHtml(period.remaining_usd)} USD · ${Math.round(period.ratio * 100)}%</span>${reserved}${period.unpriced_agent_runs ? `<div class="helper">${period.unpriced_agent_runs} runs with no recorded price</div>` : ''}</div>`;
}

async function loadBudget() {
  const cards = element('budget-cards');
  try {
    const data = await api('/economy/budget');
    // Money held apart from money spent, and the two figures that say the total is
    // incomplete: a render paid for that delivered nothing, and the runs whose model has no
    // stored price. An unpriced run is real usage the books cannot value, so it is named
    // rather than counted as zero.
    const today = data.today;
    const held = today.reserved_usd_micros
      ? `<div class="helper">${escapeHtml(today.reserved_usd)} USD held today for films in production, not yet spent</div>`
      : '';
    const wasted = today.failed_render_usd_micros
      ? `<div class="helper">${escapeHtml(today.failed_render_usd)} USD for renders that failed midway</div>`
      : '';
    const unpriced = today.unpriced_agent_runs
      ? `<div class="helper">${today.unpriced_agent_runs} runs today with no recorded price — the total is lower than the real spend</div>`
      : '';
    const spend = `<div class="budget-card"><span class="stat-label">Spent</span><strong>today ${escapeHtml(today.spent_usd)} USD</strong><span>this month ${escapeHtml(data.month.spent_usd)} USD · ${data.month.agent_runs} agent runs, ${data.month.unpriced_agent_runs} unpriced</span>${held}${wasted}${unpriced}</div>`;
    const providers = data.month.by_provider.map((p) => `<div class="budget-card"><span class="stat-label">${escapeHtml(p.provider)}</span><strong>${escapeHtml(((p.estimated_usd_micros + p.billed_usd_micros) / 1e6).toFixed(2))} USD</strong><span>${p.records} entries · billed ${escapeHtml((p.billed_usd_micros / 1e6).toFixed(2))}</span></div>`).join('');
    cards.innerHTML = spend + (data.budgets.length ? data.budgets.map(budgetCard).join('') : '<div class="budget-card"><span class="stat-label">Budget</span><strong>not set</strong><span>no limit, nothing stops spending</span></div>') + providers;
  } catch (error) {
    cards.innerHTML = `<div class="text-error">${escapeHtml(error instanceof Error ? error.message : 'The budget could not be read.')}</div>`;
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
          money_class: 'Uninvoiced provider costs',
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
    verdict.textContent = tb.balanced ? 'LEDGER BALANCED' : 'LEDGER UNBALANCED';
    const detail = document.createElement('span');
    detail.textContent = tb.balanced
      ? `Debits ${tb.total_debits} = credits ${tb.total_credits}.${treasury.in_deficit ? ' VR$ cash is negative: the treasury is in deficit.' : ''}`
      : `Difference ${tb.difference}. No figure above can be trusted until it is resolved.`;
    balance.append(verdict, detail);
    summary.append(balance);

    element('treasury-disclaimer').textContent = treasury.disclaimer;

    accountsBox.replaceChildren();
    if (!treasury.accounts.length) {
      const empty = document.createElement('div');
      empty.className = 'topics-loading';
      empty.textContent = 'No account has a balance. The ledger is empty.';
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
      empty.textContent = 'No entry yet. Nothing issued, nothing spent.';
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
    failure.textContent = `The treasury could not be read: ${err.message}`;
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
    box.textContent = 'Enter the amount to see how many VR$ enter the ledger.';
    return;
  }
  if (currency === 'USD') {
    box.textContent = `${amount} verified USD → ${amount} VR$ in the ledger (1 USD = 1 VR$).`;
    return;
  }
  if (currency.length !== 3) {
    box.textContent = 'Moneda are trei litere, ex. USD sau EUR.';
    return;
  }
  const rate = /** @type {HTMLInputElement} */ (element('funding-fx-rate')).value.trim();
  if (!AMOUNT_PATTERN.test(rate) || Number(rate) <= 0) {
    box.textContent = `Enter the ${currency} → USD rate to see how many VR$ result.`;
    return;
  }
  const vr = (amountToMicros(amount) * amountToMicros(rate) + MICROS / 2n) / MICROS;
  box.textContent = `${amount} ${currency} × ${rate} → ${microsToAmount(vr)} VR$ in the ledger.`;
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
      empty.textContent = 'No funding recorded yet.';
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
      title.textContent = isLoan ? 'Owner loan' : 'Capital contribution';
      const value = document.createElement('span');
      value.className = 'topic-card-novelty';
      value.textContent = `${item.vr} VR$`;
      head.append(title, value);
      const meta = document.createElement('div');
      meta.className = 'topic-card-meta';
      const parts = [`${item.amount} ${item.currency}`];
      if (isLoan) {
        parts.push(`${(item.annual_rate_bps / 100).toFixed(2)}% pe an`);
        parts.push(`maturity ${item.maturity_date}`);
      } else {
        parts.push('no interest, not repaid');
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
    failure.textContent = `The funding history could not be read: ${err.message}`;
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
    fundingStatus('Write the amount with a dot for decimals and no thousands separator: 5000.50', true);
    return;
  }
  if (!AMOUNT_PATTERN.test(amount)) {
    fundingStatus('The amount must be a positive number with at most 6 decimals.', true);
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
      fundingStatus('Interest is a yearly percentage between 0 and 1000, e.g. 7 or 7.25', true);
      return;
    }
    if (!maturity) {
      fundingStatus('A loan needs a maturity date; otherwise record it as a contribution.', true);
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
        fundingStatus(`Enter the ${currency} to USD rate, e.g. 1.08`, true);
        return;
      }
      if (!fxSource) {
        fundingStatus('Write where you took the rate from; the studio never invents rates.', true);
        return;
      }
      fundingStatus('Recording the rate…', false);
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

    fundingStatus('Recording the funding…', false);
    const result = await api('/economy/owner-funding', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    fundingStatus(
      `Recorded: ${result.vr} VR$ ${isLoan ? 'as debt' : 'in equity'}. ` +
        'No real money moved.',
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
        '<div class="topics-loading">No closed day yet. Close the day to count what happened.</div>';
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
            <span>${(log.roster || []).length} in the cast</span>
            · <span>${(log.notable_events || []).length} evenimente de povestit</span>
          </div>
          <div class="source-actions">
            ${
              (log.notable_events || []).length
                ? `<button class="secondary btn-write-episode" data-log-id="${escapeHtml(log.id)}">Write the episode</button>`
                : '<span class="helper-note">A quiet day — no material for an episode.</span>'
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
      listEl.innerHTML = '<div class="topics-loading">No episode yet.</div>';
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
            <button class="quiet btn-check-grounding" data-id="${escapeHtml(episode.id)}">Check grounding</button>
            ${
              episode.status === 'DRAFT'
                ? `<input class="wf-notes" placeholder="Reason (required to reject)" maxlength="2000" />
                   <button class="secondary btn-decide-episode" data-id="${escapeHtml(episode.id)}" data-approve="true">Approve</button>
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
  storyStatus("The showrunner is writing from the day's events…", false);
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
        ? `Grounded: all ${report.cited_events} cited events exist in the journal of ${report.business_date}.`
        : `NOT GROUNDED: ${report.citations_not_in_the_log.length} citations are not in the day's journal.`,
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
    storyStatus('Write why you reject the episode; the reason stays in the history.', true);
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
    storyStatus(approve ? 'Episode approved.' : 'Episode rejected; the reason was recorded.', false);
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
  storyStatus("Counting the day's events…", false);
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
  performance_intake: 'Performance intake',
  idea_generation: 'Generare idei',
  research_and_verification: 'Research and verification',
  selection: 'Selection',
  script_and_storyboard: 'Script and storyboard',
  media: 'Media',
  edit_and_qc: 'Edit and QC',
  publish: 'Publishing',
  post_run: 'After the run',
  daily_log: "The day's journal",
  serial_queue: 'Coada serialului',
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
    // can see what it actually looked at, not only what it complained about. The word and the
    // colour come from `readiness.js`, because a failing check is not always a fault: an
    // INFORMATIONAL one — a serial channel he has not created, a character he has not locked —
    // used to print as a red "DEGRADES" about a day it does not degrade.
    checksEl.innerHTML = (data.checks || [])
      .map(
        (check) => `
        <div class="${escapeHtml(checkClassName(check))}">
          <div class="topic-card-header">
            <strong class="topic-card-title">${escapeHtml(checkLabel(check.name))}</strong>
            <span class="topic-card-novelty">${escapeHtml(checkVerdictWord(check))}</span>
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
        ? 'Blocking preflight: resolve the blocking items before starting the run.'
        : "Runs the day's stages and records what each one did.";
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
        <span>${run.stages_completed}/${run.stages_total} stages finished</span>
        · <span>preflight ${escapeHtml(run.preflight_status || '—')}</span>
        ${run.stopped_at_stage ? ` · <span>stopped at «${escapeHtml(stageLabel(run.stopped_at_stage))}»</span>` : ''}
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

/** Renders the runs and returns whether one is still on its way. */
async function loadRuns() {
  const listEl = element('runbook-runs');
  try {
    const data = await api('/runbook/runs');
    const runs = data.runs || [];
    const pending = data.pending
      ? `<div class="topic-card runbook-run rb-running">
          <div class="topic-card-header">
            <strong class="topic-card-title">Today’s run</strong>
            <span class="topic-card-novelty">IN PROGRESS</span>
          </div>
          <div class="topic-card-meta">Queued at ${escapeHtml(timelineTime(data.pending.created_at))}</div>
          <div class="claim-notes">The stages appear in the ledger on the left as they happen.</div>
        </div>`
      : '';
    listEl.innerHTML = pending + (runs.length ? runs.map(renderRunCard).join('') : (pending ? '' : '<div class="topics-loading">No run yet.</div>'));
    return Boolean(data.pending);
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
    return false;
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
      box.innerHTML = `<p class="runbook-note">No daily job scheduled. The background worker creates it at start-up when it is active.</p>`;
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
        <div class="topic-card-meta">Next run: ${escapeHtml(when(daily.next_run_at))} · last: ${escapeHtml(when(daily.last_run_at))} · la ${escapeHtml(String(Math.round(daily.interval_seconds / 3600)))} hours · missed runs: ${escapeHtml(daily.missed_policy === 'CATCH_UP' ? 'o singură recuperare, apoi cadența inițială' : 'sărite')}</div>
        ${stopped ? `<p class="runbook-note">Autonomy is off: the job will start nothing until you turn it back on.</p>` : ''}
        ${daily.is_active ? '' : `<p class="runbook-note">Scheduling is off: the studio starts no day on its own. Turning it on is your decision and stays in the history.</p>`}
        <div class="settings-actions">
          <button id="toggle-daily-job-btn" class="${daily.is_active ? 'quiet' : 'secondary'}" data-job-id="${escapeHtml(daily.id)}" data-active="${daily.is_active ? 'true' : 'false'}">${daily.is_active ? 'Stop scheduling' : 'Start daily scheduling'}</button>
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
    box.innerHTML = `<p class="runbook-note text-error">The schedule could not be read: ${escapeHtml(err.message)}</p>`;
  }
}

element('open-runbook-btn').addEventListener('click', () => {
  runbookModal.showModal();
  loadCompanyState();
  loadPreflight();
  loadSafeMode();
  loadRuns();
  loadRunbookSchedule();
});

// Where the company stands, and what the Director decided about it. A channel with nothing
// measured says so: a zero here would read as a measurement, and the studio has published
// nothing yet. Numbers come with their change, because a total on its own decides nothing.
async function loadCompanyState() {
  const box = element('company-state');
  const list = element('company-decisions');
  try {
    const [state, decisions] = await Promise.all([
      api('/runbook/company-state'),
      api('/runbook/decisions'),
    ]);
    const pipe = state.pipeline || {};
    const stages = pipe.stages || {};
    const maturity = {
      COLD_START: 'cold start — nothing measured yet',
      EARLY_DATA: 'primele date',
      MATURE: 'date suficiente',
    }[state.maturity] || state.maturity;
    const channels = (state.channels || [])
      .map((channel) => {
        const change =
          typeof channel.views_change_percentage === 'number'
            ? `${channel.views_change_percentage > 0 ? '+' : ''}${channel.views_change_percentage}% vs. the previous week`
            : 'no comparison yet';
        const views =
          typeof channel.views_last_7_days === 'number'
            ? `${channel.views_last_7_days} views in 7 days`
            : 'nothing measured in 7 days';
        return `<div class="runbook-check ${channel.measured ? 'rb-ok' : ''}">
          <strong>${escapeHtml(channel.channel_name)}</strong>
          <div>${channel.published} published · ${channel.measured} measured</div>
          <div>${escapeHtml(views)} · ${escapeHtml(change)}</div>
          <div class="motion-reason">${escapeHtml(channel.baseline?.note || '')}</div>
        </div>`;
      })
      .join('');
    const growth = (state.growth || [])
      .map(
        (item) =>
          `<div class="motion-reason"><strong>${escapeHtml(item.constraint)}</strong> (${escapeHtml(item.confidence)}): ${escapeHtml(item.reason)}</div>`,
      )
      .join('');
    const anomalyList = (state.anomalies || [])
      .map((item) => `<div class="motion-reason">${escapeHtml(item.kind)}: ${escapeHtml(item.detail)}</div>`)
      .join('');
    box.innerHTML = `
      <div class="runbook-check ${state.autonomy_stopped ? 'rb-fail' : 'rb-ok'}">
        <strong>${state.autonomy_stopped ? 'Autonomy is off' : 'Autonomy is on'}</strong>
        <div>Mediu: ${escapeHtml(state.environment)} · ${escapeHtml(maturity)}</div>
      </div>
      ${channels}
      <div class="runbook-check">
        <strong>Pipeline</strong>
        <div>${stages.topics_proposed || 0} teme propuse · ${stages.topics_selected || 0} selectate ·
          ${stages.scripts_approved || 0} scenarii aprobate · ${stages.storyboards_approved || 0} storyboard-uri ·
          ${stages.renders_completed || 0} randate · ${stages.published || 0} publicate</div>
        <div>${pipe.in_flight || 0} in progress${
          pipe.bottleneck
            ? ` · <span class="text-error">bottleneck at ${escapeHtml(pipe.bottleneck.stage)}: ${pipe.bottleneck.waiting} waiting</span>`
            : ''
        }</div>
      </div>
      <div class="runbook-check">
        <strong>Agents</strong>
        <div>${state.agents?.active || 0} active · ${(state.agents?.idle || []).length} without runs ·
          ${state.agents?.queue_backlog || 0} queued · ${state.agents?.dead_letter_tasks || 0} dead-letter tasks</div>
      </div>
      ${growth ? `<div class="runbook-check"><strong>What limits growth</strong>${growth}</div>` : ''}
      ${anomalyList ? `<div class="runbook-check"><strong>Anomalii</strong>${anomalyList}</div>` : ''}`;

    const rows = (decisions.decisions || []).slice(0, 8);
    list.innerHTML = rows.length
      ? rows
          .map(
            (row) => `
        <div class="topic-card">
          <div class="topic-card-header">
            <strong class="topic-card-title">${escapeHtml(row.decision)} — ${escapeHtml(row.matter_key)}</strong>
            <span class="topic-card-novelty">${escapeHtml(row.state)}</span>
          </div>
          <div class="motion-reason">${escapeHtml(row.observation)}</div>
          <div class="motion-reason">Interpretare (${escapeHtml(row.confidence)}): ${escapeHtml(row.interpretation)}</div>
          <div><strong>To do:</strong> ${escapeHtml(row.action)}${row.owner_role ? ` — ${escapeHtml(row.owner_role)}` : ''}</div>
          ${row.review_after_videos ? `<div class="motion-reason">Review after ${row.review_after_videos} films.</div>` : ''}
          ${row.outcome ? `<div class="motion-reason">Rezultat: ${escapeHtml(row.outcome)}</div>` : ''}
        </div>`,
          )
          .join('')
      : '<div class="topics-loading">No strategic decision yet.</div>';
  } catch (err) {
    box.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
  }
}

const directCompanyBtn = /** @type {HTMLButtonElement} */ (element('direct-company-btn'));
if (directCompanyBtn) {
  directCompanyBtn.addEventListener('click', async () => {
    directCompanyBtn.disabled = true;
    runbookStatus("The Director is reading the company's state…", false);
    try {
      const result = await api('/runbook/direct', { method: 'POST' });
      runbookStatus(
        `${result.reason}${result.note ? ` — ${result.note}` : ''}`,
        result.status === 'SKIPPED',
      );
      await loadCompanyState();
    } catch (err) {
      runbookStatus(err.message, true);
    } finally {
      directCompanyBtn.disabled = false;
    }
  });
}
element('close-runbook-btn').addEventListener('click', () => runbookModal.close());
element('refresh-preflight-btn').addEventListener('click', () => loadPreflight());

/**
 * A day takes minutes — agents think, a render is waited on, quality control reads the file.
 * The Owner's click asks for it to start, and that is what is answered: the studio queues the
 * day and says so at once. Where it has got to is in the ledger, stage by stage, and the runs
 * list below fills in as soon as the day closes.
 */
element('start-run-btn').addEventListener('click', async (event) => {
  const button = /** @type {HTMLButtonElement} */ (event.currentTarget);
  button.disabled = true;
  runbookStatus('Starting today’s run…', false);
  try {
    const started = await api('/runbook/runs', {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID() }),
    });
    runbookStatus(started.message || "Today's run was started.", false);
    watchTheRun();
  } catch (err) {
    // Safe mode, a stopped autonomy and a run already on its way all refuse here; the
    // refusal is the message.
    runbookStatus(err.message, true);
  } finally {
    button.disabled = false;
    await loadPreflight();
  }
});

// The Director's weekly performance review, on demand: the same queued task the standing
// schedule fires, so the outcome lands in the ledger and in the departments' inboxes the
// same way. A week with nothing published reports exactly that, at no token cost.
element('start-weekly-review-btn').addEventListener('click', async (event) => {
  const button = /** @type {HTMLButtonElement} */ (event.currentTarget);
  button.disabled = true;
  runbookStatus('Handing the weekly review to the Director…', false);
  try {
    const started = await api('/runbook/weekly-review', {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID() }),
    });
    runbookStatus(started.message || 'The weekly review was started.', false);
    watchTheRun();
  } catch (err) {
    runbookStatus(err.message, true);
  } finally {
    button.disabled = false;
  }
});

/** While a day is on its way, the panel refreshes itself; it stops when the day is closed. */
let runWatcher = null;
function watchTheRun() {
  if (runWatcher) clearInterval(runWatcher);
  const started = Date.now();
  const tick = async () => {
    const pending = await loadRuns();
    // Two hours is longer than any day the studio has had; past that the panel stops
    // polling and the runs list stays the record.
    if (!pending || Date.now() - started > 2 * 60 * 60 * 1000) {
      clearInterval(runWatcher);
      runWatcher = null;
      await loadSafeMode();
    }
  };
  runWatcher = setInterval(tick, 5000);
  tick();
}

element('clear-safe-mode-btn').addEventListener('click', async () => {
  const field = /** @type {HTMLTextAreaElement} */ (element('runbook-safe-notes'));
  const notes = field.value.trim();
  if (!notes) {
    runbookStatus('Write what you checked before leaving safe mode.', true);
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
