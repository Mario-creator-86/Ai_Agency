import './style.css';
import { initSettings } from './settings.js';
import { acceptSnapshot } from './projection.js';
import { OfficeEngine } from './office_engine.js';
import { OfficeState } from './office_state.js';

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

function notify(message) {
  element('message').textContent = message;
  element('message').hidden = !message;
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      headers: { Authorization: `Bearer ${ownerToken}`, 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(path.startsWith('/settings') ? 45000 : 10000),
      cache: 'no-store',
    });
  } catch {
    throw new Error('Conexiune indisponibilă. Datele afișate nu mai sunt actualizate.');
  }
  if (!response.ok) {
    const error = new Error(
      response.status === 401
        ? 'Cheia Owner nu este validă.'
        : response.status === 409
        ? 'Starea s-a schimbat. Datele au fost reîncărcate; repetă comanda.'
        : 'Conexiunea nu a putut fi verificată. Încearcă din nou.'
    );
    if (path.startsWith('/settings')) {
      const detail = await response.json().catch(() => ({}));
      if (typeof detail.detail === 'string') error.message = detail.detail;
    }
    Object.assign(error, { status: response.status });
    throw error;
  }
  return response.json();
}

const settingsUI = initSettings(api);

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
        (officeContainer && officeContainer.classList.contains('is-fullscreen'))
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
      if (e.key === 'Escape' && officeContainer && officeContainer.classList.contains('is-fullscreen')) {
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
    }
  } catch (err) {
    console.error('Failed to load office layout', err);
  }
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
          // Update activity log
          addEventToLog(eventData);
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

function addEventToLog(event) {
  const eventList = element('events');
  const eventLabels = {
    'studio.created': 'Studioul a fost inițializat',
    'office.room_created': 'Spațiul de lucru a fost creat',
    'autonomy.stopped': 'Owner a activat oprirea autonomiei',
    'autonomy.stop_cleared': 'Owner a eliberat oprirea · modul rămâne Manual',
    'agent.paused': 'Agentul a fost pus pe pauză',
    'agent.resumed': 'Agentul a fost reactivat',
    'agent.run_completed': 'Sarcină finalizată cu succes',
    'agent.message_sent': 'Agentul a răspuns',
    'workflow.created': 'Flux de producție creat',
    'provider.model_discovered': 'Model nou descoperit prin provider',
  };
  const item = document.createElement('li');
  const dot = document.createElement('span');
  dot.className = 'event-dot';
  const label = document.createElement('div');
  label.textContent = eventLabels[event.event_type] || event.event_type;
  const id = document.createElement('small');
  id.textContent = `EVENT ${event.event_id || ''}`;
  label.append(id);
  const time = document.createElement('time');
  time.textContent = new Date(event.timestamp || Date.now()).toLocaleTimeString('ro-RO');
  item.append(dot, label, time);
  eventList.prepend(item);
  if (event.sequence) {
    element('cursor').textContent = `CURSOR ${event.sequence}`;
  }
}

function showInspector(agent) {
  element('inspector-name').textContent = agent.display_name || 'Agent';
  element('inspector-role').textContent = (agent.role_name || 'Agent').toUpperCase();
  element('inspector-state').textContent = agent.runtime_state || 'IDLE';
  element('inspector-lifecycle').textContent = agent.lifecycle || 'ACTIVE';
  element('inspector-id').textContent = agent.id || agent.agent_id || '—';
  element('agent-run-output').hidden = true;
  element('agent-run-output').textContent = '';
  inspector.showModal();
}

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
    const command = {
      schema_version: 1,
      command_id: crypto.randomUUID(),
      task_type: 'direct_task',
      objective: objectiveInput.value,
      prompt_template_version: 'v1',
    };
    const result = await api(`/agents/${agentId}/run`, {
      method: 'POST',
      body: JSON.stringify(command),
    });
    outputDiv.textContent = `Status: ${result.status}\n${result.output_text || result.error_detail || 'Niciun răspuns.'}`;
    objectiveInput.value = '';
    await refresh();
  } catch (err) {
    outputDiv.textContent = `Eroare: ${err.message}`;
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

bindPanelToggle('open-research-btn', researchModal);

function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;',
  })[c]);
}

async function loadTopics() {
  const listEl = element('topics-list');
  try {
    const data = await api('/factual/topics');
    const topics = data.topics || [];
    if (topics.length === 0) {
      listEl.innerHTML = '<div class="topics-loading">Niciun subiect propus încă.</div>';
      return;
    }
    listEl.innerHTML = topics.map(t => {
      const cardClass = t.novelty_score >= 0.8 ? 'topic-card topic-card-high' : 'topic-card topic-card-low';
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
    }).join('');
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">Eroare la încărcare: ${escapeHtml(err.message)}</div>`;
  }
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
      setTimeout(() => { statusDiv.hidden = true; }, 3000);
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
  refreshMediaBtn.addEventListener('click', loadMediaStoryboards);
}

async function loadCharacterBibles() {
  const listEl = element('characters-list');
  try {
    const data = await api('/media/character-bible');
    const chars = data.characters || [];
    if (chars.length === 0) {
      listEl.innerHTML = '<div class="topics-loading">Niciun caracter înregistrat în Character Bible.</div>';
      return;
    }
    listEl.innerHTML = chars.map(c => {
      const vis = c.visual_profile_json || {};
      const voice = c.voice_profile_json || {};
      return `
        <div class="character-card">
          <div class="char-header">
            <span class="char-name">${escapeHtml(c.canonical_name)}</span>
            <span class="char-archetype">${escapeHtml(vis.archetype || 'Specialist')}</span>
          </div>
          <p class="char-desc">${escapeHtml(vis.appearance_notes || 'Design canonic studio.')}</p>
          <div class="char-voice">Voce: ${escapeHtml(voice.voice_id || 'default')} (${escapeHtml(voice.pace || 'normal')})</div>
        </div>
      `;
    }).join('');
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">Eroare la încărcarea caracterelor: ${escapeHtml(err.message)}</div>`;
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

    const itemsHtml = await Promise.all(storyboards.map(async (sb) => {
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

      const scenesHtml = scenes.map(s => `
        <div class="scene-card">
          <div class="scene-card-header">
            <span class="scene-badge">Scena #${s.scene_index}</span>
            <span class="scene-duration">${s.duration_seconds}s</span>
          </div>
          <div class="scene-shot">${escapeHtml(s.shot_type)} · ${escapeHtml(s.visual_type)}</div>
          <p class="scene-prompt">${escapeHtml(s.visual_prompt)}</p>
          <p class="scene-audio">" ${escapeHtml(s.voiceover_segment)} "</p>
        </div>
      `).join('');

      let renderHtml = '';
      if (sb.status === 'RENDERED') {
        const qcPassed = qcReport && qcReport.status === 'PASSED';
        const qcBadge = qcReport
          ? `<span class="${qcPassed ? 'qc-badge-pass' : 'qc-badge-fail'}">QC: ${escapeHtml(qcReport.status)}</span>`
          : '<span class="tag">QC: Neefectuat</span>';

        const checks = qcReport ? (qcReport.checks_json || {}) : {};
        const techPassed = Boolean(checks.technical_qc && checks.technical_qc.passed);
        const factualPassed = Boolean(checks.factual_qc && checks.factual_qc.passed);
        // null means "not implemented"; it is deliberately not coerced to false.
        const charDrift = checks.character_drift_qc ? checks.character_drift_qc.passed : null;
        const rightsPassed = Boolean(checks.rights_qc && checks.rights_qc.passed);

        // A check that was never implemented must not be scored: an em dash says
        // "not evaluated", whereas 0% would claim a failed measurement.
        const scoreCell = (label, passed) => {
          const value = passed === null || passed === undefined ? '—' : (passed ? '100%' : '0%');
          return `<div class="qc-score-item"><div>${label}</div><div class="qc-score-num">${value}</div></div>`;
        };
        const tech = checks.technical_qc || {};
        const qcScoresHtml = qcReport ? `
          <div class="qc-scores-grid">
            ${scoreCell('Tehnic', techPassed)}
            ${scoreCell('Factual', factualPassed)}
            ${scoreCell('Continuitate', charDrift)}
            ${scoreCell('Drepturi', rightsPassed)}
          </div>
        ` : '';

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
    }));

    listEl.innerHTML = itemsHtml.join('');

    listEl.querySelectorAll('.btn-render-video').forEach(btn => {
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

    listEl.querySelectorAll('.btn-qc-video').forEach(btn => {
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
    mediaStatusMsg.textContent = 'Creare fixture demo (topic, scenariu și afirmație NEVERIFICATĂ)...';
    try {
      const fixture = await api('/media/storyboards/demo-fixture', { method: 'POST' });
      mediaStatusMsg.textContent = fixture.next_step || 'Fixture creat. Verifică afirmațiile în panoul Cercetare.';
      setTimeout(() => { mediaStatusMsg.hidden = true; }, 8000);
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

if (refreshPublishingBtn) {
  refreshPublishingBtn.addEventListener('click', loadPublishingHub);
}

async function loadPublishingHub() {
  const channelsEl = element('channels-list');
  const pubListEl = element('publications-list');

  try {
    const [chData, pubData] = await Promise.all([
      api('/publishing/channels'),
      api('/publishing/publications'),
    ]);

    const channels = chData.channels || [];
    if (publisherBanner) {
      if (chData.publisher_configured) {
        publisherBanner.className = 'dialog-status-msg';
        publisherBanner.textContent = 'Credențiale YouTube prezente. Publicarea folosește API-ul oficial.';
      } else {
        publisherBanner.className = 'dialog-status-msg text-error';
        publisherBanner.textContent = 'Nicio credențială YouTube configurată: publicarea este dezactivată. Setează STUDIO_YOUTUBE_CLIENT_ID, STUDIO_YOUTUBE_CLIENT_SECRET și STUDIO_YOUTUBE_REFRESH_TOKEN în .env. Studioul nu simulează publicări.';
      }
      publisherBanner.hidden = false;
    }
    if (channels.length === 0) {
      channelsEl.innerHTML = '<div class="topics-loading">Niciun canal de distribuție configurat.</div>';
    } else {
      channelsEl.innerHTML = channels.map(c => `
        <div class="channel-item">
          <div class="channel-info">
            <h4>${escapeHtml(c.channel_name)}</h4>
            <div class="channel-meta">Tip: <strong>${escapeHtml(c.channel_type)}</strong> · ID la distanță: <code>${escapeHtml(c.remote_channel_id || 'nesetat')}</code></div>
            <div class="channel-meta">${escapeHtml(CHANNEL_STATUS_HINT[c.status] || 'Stare necunoscută.')}</div>
          </div>
          <span class="channel-status-tag ${c.status === 'AUTHENTICATED' ? 'channel-status-ok' : 'channel-status-warn'}">${escapeHtml(CHANNEL_STATUS_LABEL[c.status] || c.status)}</span>
        </div>
      `).join('');
    }

    const publications = pubData.publications || [];
    if (publications.length === 0) {
      pubListEl.innerHTML = '<div class="topics-loading">Nicio publicație înregistrată încă. Folosește butonul de mai sus pentru a publica un video aprobat.</div>';
    } else {
      pubListEl.innerHTML = publications.map(p => {
        const isSimulated = p.status === 'PUBLISHED_SIMULATED';
        const isPub = p.status === 'PUBLISHED';
        const badgeClass = isPub ? 'pub-status-published' : (p.status === 'VALIDATED' ? 'pub-status-validated' : 'pub-status-blocked');
        // Only a real platform URL becomes a link. A simulated upload has no address.
        const isRealYoutubeUrl = typeof p.remote_url === 'string' && /^https:\/\/(www\.)?youtube\.com\//.test(p.remote_url);
        const remoteLink = (!isSimulated && isRealYoutubeUrl)
          ? `<a href="${escapeHtml(p.remote_url)}" target="_blank" rel="noopener" class="pub-remote-link">Vezi pe YouTube</a>`
          : (isSimulated ? '<span class="pub-sim-note">Simulare locală — niciun video pe YouTube</span>' : '');
        const privacyBadge = p.privacy_status === 'private' ? '<span class="privacy-badge privacy-badge-private">Privat</span>' : '<span class="privacy-badge privacy-badge-public">Public</span>';

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
      }).join('');
    }
  } catch (err) {
    if (channelsEl) channelsEl.innerHTML = `<div class="text-error">Eroare canale: ${escapeHtml(err.message)}</div>`;
    if (pubListEl) pubListEl.innerHTML = `<div class="text-error">Eroare publicații: ${escapeHtml(err.message)}</div>`;
  }
}

if (triggerQuickPublishBtn) {
  triggerQuickPublishBtn.addEventListener('click', async () => {
    publishingStatusMsg.hidden = false;
    publishingStatusMsg.className = 'dialog-status-msg';
    publishingStatusMsg.textContent = 'Verificare pipeline media și identificare cel mai recent video aprobat QC...';
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
        publishingStatusMsg.textContent = 'Nu a fost găsit niciun video cu raport QC PASSED. Generează mai întâi un storyboard și randare 9:16 din panoul Producție Media!';
        return;
      }

      publishingStatusMsg.textContent = `Validare Content Gate și încărcare privată pentru MediaAsset ${targetAssetId}...`;
      const pubRes = await api(`/publishing/publish-asset/${targetAssetId}`, { method: 'POST' });

      if (pubRes.status === 'PUBLISHED') {
        publishingStatusMsg.className = 'dialog-status-msg';
        publishingStatusMsg.textContent = `Video încărcat privat pe YouTube. ID la distanță: ${pubRes.remote_video_id}`;
      } else if (pubRes.status === 'PUBLISHED_SIMULATED') {
        publishingStatusMsg.className = 'dialog-status-msg text-error';
        publishingStatusMsg.textContent = 'Încărcare SIMULATĂ: nu există niciun video pe YouTube. Configurează credențialele reale.';
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
  element('snapshot-time').textContent = `Actualizat ${new Date(data.captured_at).toLocaleTimeString('ro-RO', { timeZone: data.studio.timezone })}`;
  element('stop-status').textContent = data.policy.autonomy_stopped ? 'ACTIVĂ' : 'ELIBERATĂ';
  stopButton.textContent = pendingCommand
    ? 'Reverifică ultima comandă'
    : data.policy.autonomy_stopped
    ? 'Eliberează oprirea · rămâne Manual'
    : 'STOP AUTONOMY';
  element('cursor').textContent = `CURSOR ${data.cursor}`;

  const eventList = element('events');
  eventList.replaceChildren();
  const eventLabels = {
    'studio.created': 'Studioul a fost inițializat',
    'office.room_created': 'Spațiul de lucru a fost creat',
    'autonomy.stopped': 'Owner a activat oprirea autonomiei',
    'autonomy.stop_cleared': 'Owner a eliberat oprirea · modul rămâne Manual',
    'agent.paused': 'Agentul a fost pus pe pauză',
    'agent.resumed': 'Agentul a fost reactivat',
    'agent.run_completed': 'Sarcină finalizată cu succes',
    'agent.message_sent': 'Agentul a răspuns',
    'storyboard.created': 'Storyboard generat din scenariu',
    'media.video_rendered': 'Video 9:16 asamblat cu succes',
    'media.qc_evaluated': 'Control Calitate (QC) evaluat',
    'channel.created': 'Slot de canal creat (neconfigurat)',
    'channel.configured': 'Configurație canal actualizată',
    'publishing.intent_created': 'Intenție de publicare validată',
    'publishing.started': 'Încărcare video pornită',
    'publishing.video_published': 'Video publicat pe YouTube Shorts (Mod PRIVAT)',
    'publishing.video_published_simulated': 'Publicare SIMULATĂ (niciun video real)',
    'publishing.retry_reconciled': 'Reîncercare oprită: încărcarea anterioară există deja',
    'media.render_failed': 'Randare video eșuată',
    'factual.demo_fixture_created': 'Fixture demo creat (afirmații NEVERIFICATE)',
    'publishing.gate_failed': 'Publicare blocată de Content Gate',
  };
  for (const event of [...data.events].reverse()) {
    const item = document.createElement('li');
    const dot = document.createElement('span');
    dot.className = 'event-dot';
    const label = document.createElement('div');
    label.textContent = eventLabels[event.event_type] || event.event_type;
    const id = document.createElement('small');
    id.textContent = `EVENT ${event.event_id}`;
    label.append(id);
    const time = document.createElement('time');
    time.dateTime = event.timestamp;
    time.textContent = new Date(event.timestamp).toLocaleTimeString('ro-RO', { timeZone: data.studio.timezone });
    item.append(dot, label, time);
    eventList.append(item);
  }

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
  element('events').replaceChildren();
  element('modules').replaceChildren();
  element('studio-name').textContent = 'Studioul tău';
  element('connection').textContent = 'Neconectat';
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
    await api('/owner/autonomy-stop', { method: 'POST', body: JSON.stringify(pendingCommand) });
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
