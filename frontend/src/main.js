import { amount } from './numbers.js';
import { loadAgentDetails } from './agent_details.js';
import { icon } from './icons.js';
import { escapeHtml } from './html.js';
import {
  approvalCaveat,
  checkClassName,
  checkLabel,
  checkVerdictWord,
} from './readiness.js';
import { firstStop, runClassName, runHeadline, stageClassName, stageProducedWord } from './day_outcome.js';
import { attachRail } from './dialog_rail.js';
import './style.css';
import './serial_room.css';
import { approvalMessage, daysClosedNote, episodeHtml, serialBoardHtml, serialStageNotes } from './serial_room.js';
import { initSettings } from './settings.js';
import { acceptSnapshot } from './projection.js';
import { OfficeEngine, BUILDING, WORLD_W, WORLD_H } from './office_engine.js';
import { streamTransform } from './game_frame.js';
import { Drawers } from './drawers.js';
import { OfficeState } from './office_state.js';
import { Ledger, entryCountLabel, productionStatus, taskLabel } from './ledger.js';
import { streetMoves } from './hq_events.js';
import { budgetRing, budgetRingSvg, channelFilmsHtml, dayTrack, dayTrackFromRun, dayTrackGeometry, dayTrackWords, newerTrack, pipelineSvg } from './hud_charts.js';
import { Moments } from './moments.js';
import { filmPoster } from './film_poster.js';
import { latestFilm, boardTopics } from './hq_screens.js';
import { studioReadout } from './side_readout.js';
import { friendlyAnswer } from './friendly_text.js';
import { LiveWindows, eventMatchesAgent } from './live_window.js';
import { MailThread } from './mail_thread.js';
import { LiveStream } from './hq_stream.js';
import { liveStreamSettings, relayUrl } from './hq_stream_config.js';
import { EventsLink, connectionLabel, roomCaption, sceneReadout } from './live_claims.js';
import { TitleScreen } from './title_screen.js';
import { ENTRY, entryPlays } from './title_frame.js';
import { KeyLight } from './key_light.js';
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

/**
 * What the page knows is happening, from which every «live» it prints is decided
 * (live_claims.js): the Unreal stream, the events socket, the last snapshot read, and the two
 * frame rates, each under its own name.
 * @type {import('./live_claims.js').LiveSignals}
 */
const liveSignals = { stream: 'pending', hasStill: false, socket: 'closed', data: 'fresh', streamFps: null, pageFps: null };
let liveReadoutKey = '';

/** Writes the corner readout, the masthead chip and the slate caption from liveSignals. */
function renderLiveSignals() {
  const readout = sceneReadout(liveSignals);
  const staff = officeState.agents.length;
  const caption = roomCaption(staff, readout.live);
  const chip = connectionLabel(liveSignals);
  const key = JSON.stringify([readout.state, readout.parts, caption, chip]);
  if (key === liveReadoutKey) return;
  liveReadoutKey = key;
  const pill = element('office-status');
  pill.dataset.state = readout.state;
  pill.title = readout.title;
  pill.setAttribute('aria-hidden', readout.hidden ? 'true' : 'false');
  element('office-fps').replaceChildren(...readout.parts.map(([name, text]) => {
    const span = document.createElement('span');
    span.className = name;
    span.textContent = text;
    return span;
  }));
  element('room-caption').textContent = caption;
  officeCanvas.setAttribute(
    'aria-label',
    `Sediul AMN-AI${readout.live ? ', live' : ''}. Folosește tastele-săgeți ca să treci de la un angajat la altul și Enter ca să deschizi unul.`,
  );
  if (ownerToken) element('connection').textContent = chip;
}

/** The backend's events, reconnected after a drop; see EventsLink. */
const eventsLink = new EventsLink({
  url: () => {
    const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    return `${proto}//${location.host}/api/v1/ws?token=${encodeURIComponent(ownerToken)}`;
  },
  open: (url) => new WebSocket(url),
  // Everything after the newest event the page holds: the snapshot's cursor, or further on when
  // the register has already read past it.
  afterSequence: () => Math.max(state ? Number(state.cursor) || 0 : 0, ledger.cursor || 0),
  onEvent: (eventData, live) => {
    officeState.handleDomainEvent(eventData, live);
    updateOfficeCanvas();
    ledger.add(eventData);
    element('ledger-count').textContent = entryCountLabel(ledger.events.size);
    // A milestone plays only when the socket delivered it as it happened (moments.js).
    const moment = moments.offer(eventData, live);
    if (moment && moment.kind === 'approval') loadApprovals(true).then(() => markArrived());
  },
  onState: (socketState) => {
    liveSignals.socket = socketState;
    renderLiveSignals();
  },
  // Back after a drop: read the studio again, so the switches and the panels are not the ones
  // from before the gap. The register has its replay already.
  onReconnected: () => { if (ownerToken) refresh(); },
});

// 2D Office Engine & State
const officeCanvas = /** @type {HTMLCanvasElement} */ (element('office-canvas'));

/** Whether the visitor asked the system for less motion; read at the moment it matters. */
function reducedMotion() {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * The title screen: the sign-in standing in the studio's own world, lit by the real sun
 * (title_screen.js). It is the first thing on screen, before any key.
 */
const titleScreen = new TitleScreen({
  stage: element('title-stage'),
  caption: element('title-caption'),
  reducedMotion,
});
titleScreen.start();

/**
 * The page's key light, taken from the frame the visitor is looking at: the stream's kept frame
 * while the stream has one, the page's own renderer otherwise (key_light.js).
 */
const keyLight = new KeyLight({
  target: document.documentElement,
  source: () => (liveStream && liveStream.hasStill ? liveStream.still : officeCanvas),
});
const officeState = new OfficeState();
let officeEngine = null;
/** Whether the camera keys, fullscreen and the stream have been wired (once per page). */
let officeWired = false;
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
  if (active) indicator.textContent = `${currentSelectedAgent.display_name || 'Angajatul'} lucrează… răspunsul apare aici.`;
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
    noteWorldEvents(events);
    if (events.some((event) => String(event.event_type || '').startsWith('runbook.'))) scheduleDayTrack();
    // A day that closes is re-read from the runbook's own record.
    if (events.some((event) => event.event_type === 'runbook.daily_run_finished')) loadDayRecord();
  },
  onThread: (threadId) => mailThread.open(threadId),
});
// «Acum» must go quiet when the register has been silent past RUN_QUIET_MS even if no event
// arrives to trigger a render, so the head line is read again once a minute. It touches one
// paragraph; the list is not redrawn. The day tracker's words follow the same clock.
window.setInterval(() => {
  // past midnight the day headings («Azi», «Ieri») are re-read with the list
  if (ledger.dayTurned()) ledger.render();
  else ledger.renderNow();
  renderDayTrack();
}, 60000);

/* ---------------------------------------------------------------------------
 * THE DAY TRACKER on the slate: one segment per stage of the newest daily run, from the
 * runbook's own events in the register (hud_charts.js). The segments are kept from one render
 * to the next, so a segment changes colour only when a real stage event changes it, and the
 * first drawing is at rest: nothing counts up from nothing.
 * ------------------------------------------------------------------------- */
const dayTrackBox = element('day-track');
const dayTrackBar = /** @type {SVGSVGElement} */ (/** @type {unknown} */ (dayTrackBox.querySelector('.day-track-bar')));
const dayTrackLabel = /** @type {HTMLElement} */ (dayTrackBox.querySelector('.day-track-label'));
const SVG_NS = 'http://www.w3.org/2000/svg';
let dayTrackKey = '';
let dayTrackQueued = false;
/** @type {import('./hud_charts.js').DayTrack|null} the newest finished day, as the runbook recorded it */
let dayRecord = null;

/* ---------------------------------------------------------------------------
 * THE BUILDING'S SCREENS (hq_screens.js): what the page already reads, handed to the renderer.
 * Nothing is fetched per frame. The newest run comes with the day record; the treasury and the
 * budget are read once at the key and again only when the register says money moved or a run
 * ended (at most every 15 s); the serial once at the key and when a story event arrives; the
 * newest film's frame once per film. A value the page does not hold stays null, and its screen
 * says «—».
 * ------------------------------------------------------------------------- */
/** @type {{run: any, track: any, today: string|null, live: boolean, treasury: any, budget: any, episodes: any, topics: {titles: string[], key: string}, film: any, jobs: any[]|null}} */
const worldFacts = { run: null, track: null, today: null, live: true, treasury: null, budget: null, episodes: null, topics: { titles: [], key: '' }, film: null, jobs: null };

function pushWorldFacts() {
  if (officeEngine) officeEngine.setFacts({ ...worldFacts });
  renderStudioReadout();
}

/**
 * The foot of the side drawer on a tall screen (side_readout.js): the day's run, the treasury and
 * the next scheduled run, from the same facts the building's screens show. Written only when a
 * line changes.
 */
let studioReadoutKey = '';
function renderStudioReadout() {
  const list = document.getElementById('studio-readout-list');
  if (!list) return;
  const policy = state && state.policy ? state.policy : null;
  const readout = studioReadout({
    track: worldFacts.track,
    today: worldFacts.today,
    live: worldFacts.live,
    treasury: worldFacts.treasury,
    budget: worldFacts.budget,
    jobs: worldFacts.jobs,
    stopped: policy ? Boolean(policy.autonomy_stopped) : null,
    timeZone: state && state.studio ? state.studio.timezone : undefined,
  });
  if (readout.key === studioReadoutKey) return;
  studioReadoutKey = readout.key;
  list.innerHTML = readout.rows
    .map((row) => `<div class="readout-row" data-tone="${escapeHtml(row.tone || 'quiet')}"><dt>${escapeHtml(row.label)}</dt><dd><span class="readout-value">${escapeHtml(row.value)}</span>${row.note ? `<span class="readout-note">${escapeHtml(row.note)}</span>` : ''}</dd></div>`)
    .join('');
}

let filmAsset = '';

function resetWorldFacts() {
  Object.assign(worldFacts, { run: null, track: null, today: null, live: true, treasury: null, budget: null, episodes: null, topics: { titles: [], key: '' }, film: null, jobs: null });
  filmAsset = '';
  pushWorldFacts();
}

/**
 * The newest rendered film's own frame, decoded once per film from the file (film_poster.js),
 * with the Owner's key, the way the film toast decodes it.
 * @param {{assetId: string, date: string|null}|null} film
 */
async function loadFilmFrame(film) {
  if (!film || !ownerToken || film.assetId === filmAsset) return;
  filmAsset = film.assetId;
  const session = epoch;
  const canvas = await filmPoster({ url: `/api/v1/media/assets/${encodeURIComponent(film.assetId)}/stream`, token: ownerToken, width: 90, height: 160, timeoutMs: 6000 }).catch(() => null);
  if (session !== epoch || filmAsset !== film.assetId) return;
  worldFacts.film = canvas ? { ...film, canvas } : null;
  pushWorldFacts();
}

let figuresTimer = 0;
async function loadWorldFigures() {
  if (!ownerToken) return;
  const session = epoch;
  const [treasury, budget, jobs] = await Promise.all([api('/economy/treasury').catch(() => null), api('/economy/budget').catch(() => null), api('/scheduler/jobs').catch(() => null)]);
  if (session !== epoch) return;
  // A failed read keeps the last figures read; the corner already says the data is not fresh.
  if (treasury) worldFacts.treasury = treasury;
  if (budget) worldFacts.budget = budget;
  if (Array.isArray(jobs)) worldFacts.jobs = jobs;
  pushWorldFacts();
}

let serialTimer = 0;
async function loadSerialFacts() {
  if (!ownerToken) return;
  const session = epoch;
  const episodes = await api('/story/episodes').catch(() => null);
  if (session !== epoch || !episodes) return;
  worldFacts.episodes = episodes;
  pushWorldFacts();
}

/** One read after a quiet 15 s, however many events asked for it. @param {'figures'|'serial'} which */
function soon(which) {
  if (which === 'figures') {
    if (figuresTimer) return;
    figuresTimer = window.setTimeout(() => { figuresTimer = 0; loadWorldFigures(); }, 15000);
  } else {
    if (serialTimer) return;
    serialTimer = window.setTimeout(() => { serialTimer = 0; loadSerialFacts(); }, 15000);
  }
}

/** What the register's new rows change on the building's screens. @param {any[]} events */
function noteWorldEvents(events) {
  const types = events.map((event) => String((event && event.event_type) || ''));
  if (types.includes('factual.topic_proposed')) {
    const topics = boardTopics(ledger.sorted());
    if (topics.key !== worldFacts.topics.key) {
      worldFacts.topics = topics;
      pushWorldFacts();
    }
  }
  if (!ownerToken) return;
  // A finished run moves the scheduler's next time too (the side drawer's foot reads it).
  if (types.some((t) => t.startsWith('economy.') || t === 'agent.run_completed' || t === 'runbook.daily_run_finished')) soon('figures');
  if (types.some((t) => t.startsWith('story.'))) soon('serial');
}

/** Reads the runbook's newest recorded day; the events of a day under way stay the newer. */
async function loadDayRecord() {
  if (!ownerToken) return;
  try {
    const data = await api('/runbook/runs');
    const newest = (data.runs || [])[0];
    dayRecord = dayTrackFromRun(newest);
    worldFacts.run = newest || null;
    pushWorldFacts();
    loadFilmFrame(latestFilm(data.runs));
    // «Acum» reads the same record: a stage that started before the day's recorded finish is
    // not running, even when the register has lost the finish behind newer rows.
    const closed = newest ? Date.parse(String(newest.finished_at || '')) : NaN;
    ledger.closedAt = Number.isFinite(closed) ? closed : null;
  } catch {
    dayRecord = null;
  }
  ledger.renderNow();
  renderDayTrack();
}

function scheduleDayTrack() {
  if (dayTrackQueued) return;
  dayTrackQueued = true;
  requestAnimationFrame(() => {
    dayTrackQueued = false;
    renderDayTrack();
  });
}

/** The studio's business date today, in its own time zone, as the runbook writes it. */
function studioToday() {
  const zone = state && state.studio ? state.studio.timezone : undefined;
  try {
    return new Date().toLocaleDateString('sv-SE', { timeZone: zone });
  } catch {
    return new Date().toLocaleDateString('sv-SE');
  }
}

function renderDayTrack() {
  const events = ledger.sorted();
  const track = newerTrack(dayTrack(events), dayRecord);
  const live = productionStatus(events, Date.now(), ledger.closedAt).live;
  // the façade sign shows the same day, in the same words (hq_screens.js runSignFace)
  worldFacts.track = track;
  worldFacts.today = studioToday();
  worldFacts.live = live;
  pushWorldFacts();
  const words = dayTrackWords(track, { today: studioToday(), live });
  const geometry = dayTrackGeometry(track);
  const key = JSON.stringify([words.label, geometry.rects.map((r) => r.state)]);
  if (key === dayTrackKey) return;
  dayTrackKey = key;
  dayTrackBox.setAttribute('aria-label', words.sentence);
  dayTrackBox.dataset.state = track.empty ? 'empty' : track.finished ? 'finished' : 'running';
  const long = document.createElement('span');
  long.className = 'day-track-long';
  long.textContent = words.label;
  const brief = document.createElement('span');
  brief.className = 'day-track-short';
  brief.textContent = words.short;
  dayTrackLabel.replaceChildren(long, brief);
  // The same number of segments: recolour them in place. A new day with another count: redraw.
  if (dayTrackBar.childElementCount !== geometry.rects.length) {
    dayTrackBar.replaceChildren(
      ...geometry.rects.map((r) => {
        const rect = document.createElementNS(SVG_NS, 'rect');
        rect.setAttribute('x', String(r.x));
        rect.setAttribute('y', String(r.y));
        rect.setAttribute('width', String(r.w));
        rect.setAttribute('height', String(r.h));
        rect.setAttribute('rx', '1');
        return rect;
      }),
    );
    dayTrackBar.setAttribute('width', String(geometry.width));
    dayTrackBar.setAttribute('height', String(geometry.height));
    dayTrackBar.setAttribute('viewBox', `0 0 ${geometry.width || 1} ${geometry.height}`);
  }
  geometry.rects.forEach((r, i) => {
    const rect = dayTrackBar.children[i];
    if (rect) rect.setAttribute('class', `track-seg seg-${r.state}`);
  });
}

/* ---------------------------------------------------------------------------
 * MOMENTS: a chapter card, a film toast, the gold mark's one glow (moments.js). Each comes
 * from one live event and reads the rest of what it says from the backend.
 * ------------------------------------------------------------------------- */
const moments = new Moments({
  chapter: element('moment-chapter'),
  toast: element('moment-toast'),
  announce: element('moment-announce'),
  reducedMotion: () => reducedMotion(),
  facts: async (moment) => {
    if (moment.kind === 'chapter') {
      const [episodes, channels] = await Promise.all([
        api('/story/episodes').catch(() => null),
        api('/publishing/channels').catch(() => null),
      ]);
      const episode = ((episodes && episodes.episodes) || []).find((row) => row.id === moment.episodeId) || null;
      const serial = ((channels && channels.channels) || []).find((row) => row.channel_type === 'OFFICE_SERIAL');
      // The number is the draft's own (story.episode_drafted carries it); an approval reads it
      // from the draft event when the register still holds it.
      const drafted = ledger.sorted().find((e) => e.event_type === 'story.episode_drafted' && e.aggregate_id === moment.episodeId);
      const number = moment.episodeNumber || (drafted && drafted.payload && Number(drafted.payload.episode_number)) || null;
      return { series: serial ? serial.youtube_connection_name || serial.youtube_channel_title || null : null, episode, number };
    }
    if (moment.kind === 'film' && moment.storyboardId) {
      const storyboard = await api(`/media/storyboards/${encodeURIComponent(moment.storyboardId)}`).catch(() => null);
      return { title: storyboard ? storyboard.title : '' };
    }
    return {};
  },
  poster: async (moment) => {
    if (!moment.assetId) return null;
    const canvas = await filmPoster({ url: `/api/v1/media/assets/${encodeURIComponent(moment.assetId)}/stream`, token: ownerToken });
    // The film just rendered is now the newest: the render bay shows the same frame, decoded once.
    if (canvas) {
      filmAsset = moment.assetId;
      worldFacts.film = { assetId: moment.assetId, date: studioToday(), canvas };
      pushWorldFacts();
    }
    return canvas;
  },
});
// The scene script and the tests reach the moments through the page's handle.
Object.assign(window, { __moments: moments });

/** «1 cerere așteaptă decizia ta», «3 cereri…», «20 de cereri…». */
function waitingWords(n) {
  if (n === 1) return '1 cerere așteaptă decizia ta';
  const rest = n % 100;
  return `${n} ${n >= 20 && (rest === 0 || rest >= 20) ? 'de cereri' : 'cereri'} așteaptă decizia ta`;
}

const ownerMark = /** @type {HTMLButtonElement} */ (element('owner-mark'));
/** @param {number} pending how many requests the approvals route lists as waiting */
function renderOwnerMark(pending) {
  ownerMark.hidden = !(pending > 0);
  element('owner-mark-text').textContent = pending > 0 ? waitingWords(pending) : '';
  drawers.setPending(pending);
  ownerMark.title = pending > 0 ? 'Du-mă la cererile de aprobare' : '';
}
/** A request arrived as it happened: the mark glows once, for MOMENT_TIMING.mark. */
function markArrived() {
  if (ownerMark.hidden || reducedMotion()) return;
  ownerMark.classList.remove('is-arriving');
  void ownerMark.offsetWidth;
  ownerMark.classList.add('is-arriving');
}
ownerMark.addEventListener('animationend', () => ownerMark.classList.remove('is-arriving'));
ownerMark.addEventListener('click', () => {
  // In the game frame the approvals are in the side drawer: it opens first.
  drawers.showApprovals();
  const heading = document.querySelector('.approvals-heading');
  if (heading) heading.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' });
  const first = /** @type {HTMLButtonElement|null} */ (approvalsList.querySelector('.btn-approval'));
  if (first) first.focus({ preventScroll: true });
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
    throw new Error('Conexiunea nu este disponibilă. Ce se vede nu mai este la zi.');
  }
  if (!response.ok) {
    // Prefer what the server said. Every refusal this backend writes is a sentence meant for
    // the Owner — which host is not authorised, why a provider did not answer, what is missing
    // before a publication can proceed — and replacing it with "try again" would throw away
    // exactly the part that tells them what to do. The generic wording is the fallback for a
    // response that carries no explanation of its own.
    let message =
      response.status === 401
        ? 'Cheia Proprietarului nu este valabilă.'
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
    liveSignals.stream = 'off';
    renderLiveSignals();
    return;
  }
  const signallingUrl = relayUrl(window.location, String(relay.relay), ownerToken);
  liveStream = new LiveStream(viewport, { ...settings, signallingUrl }, {
    onStatus: (status) => {
      viewport.dataset.stream = status;
      // Once a stream is configured its layer covers the canvas in every state -- the video, the
      // frozen frame or the "starting" plate -- so the canvas keeps only its hit boxes.
      if (officeEngine) officeEngine.setCovered(true);
      liveSignals.stream = status;
      liveSignals.hasStill = Boolean(liveStream && liveStream.hasStill);
      renderLiveSignals();
    },
    // Unreal's frames, as the page receives them: the figure beside «Live» while the stream plays.
    onFrameRate: (fps) => {
      liveSignals.streamFps = fps;
      renderLiveSignals();
    },
  });
  if (officeEngine) {
    const view = officeEngine.view();
    const t = streamTransform(view);
    liveStream.setView({ k: t.k, tx: t.tx / view.dpr, ty: t.ty / view.dpr });
  }
  liveStream.start();
}

/**
 * THE GAME FRAME'S DRAWERS (drawers.js): the register on the left, governance on the right, each
 * open where the building still fits beside it. Whatever they cover, the camera is told, and it
 * centres the building in the room they leave.
 */
const drawers = new Drawers({
  onInsets: (insets, options) => {
    if (officeEngine) officeEngine.setInsets(insets, options);
  },
  world: () => ({
    worldW: officeEngine ? officeEngine.worldW : WORLD_W,
    worldH: officeEngine ? officeEngine.worldH : WORLD_H,
    focus: officeEngine && officeEngine.building ? officeEngine.building : BUILDING,
  }),
});

/**
 * The office engine, built parked while the title screen is up: its art is fetched and decoded,
 * and one frame is composed at the size the render will have, so the key's entry into the
 * building does not stop for the first upload of the plates (office_engine.js prewarm).
 */
function buildOfficeEngine() {
  if (officeEngine) return officeEngine;
  officeEngine = new OfficeEngine(officeCanvas, {
    parked: true,
    // The page may only call its own origin; the backend reads the live weather for the scene.
    fetchWeather: () => api('/office/weather'),
    infoElement: element('scene-info'),
    // Reduced motion holds the street, the sky's drift and the employees' loops still.
    reducedMotion: () => reducedMotion(),
    // So does a page that has lost the studio's data: nothing outside lives on while the corner
    // of the render says it is reconnecting.
    dataLive: () => streetMoves(liveSignals),
    // The page's own renderer: shown under its own name, and only while it is what is seen.
    onFrameRate: (fps) => {
      liveSignals.pageFps = fps;
      renderLiveSignals();
    },
    // The streamed picture follows the page's camera, so zoom and pan act on what is seen.
    onView: (view) => {
      if (!liveStream) return;
      const t = streamTransform(view);
      liveStream.setView({ k: t.k, tx: t.tx / view.dpr, ty: t.ty / view.dpr });
    },
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
  pushWorldFacts();
  return officeEngine;
}

/**
 * The box the render will have once the workspace is shown, read from the real layout: the
 * workspace is laid out for one synchronous read, unseen, and hidden again before any paint.
 */
function stagedSceneBox() {
  const viewport = element('scene-viewport');
  if (!workspace.hidden) return viewport.getBoundingClientRect();
  workspace.classList.add('is-staged');
  workspace.hidden = false;
  const box = viewport.getBoundingClientRect();
  workspace.hidden = true;
  workspace.classList.remove('is-staged');
  return box;
}

/** While the title is up and nothing moves: build the engine and draw its first frame, unseen. */
async function warmOffice() {
  const engine = buildOfficeEngine();
  const [ok] = await Promise.all([engine.ready, engine.themeReady]);
  if (!ok || !workspace.hidden || engine.warmed) return;
  const box = stagedSceneBox();
  engine.prewarm(box.width, box.height);
  // The drawers' widths are measured now too, so the key does not wait for that layout either.
  drawers.prime();
  warmWorkspacePaint();
}

/**
 * THE GPU'S FIRST SIGHT OF THE WORKSPACE, spent under the title (W8).
 *
 * In a fresh browser profile the first frame that paints the workspace stopped for 208-243ms,
 * 330-390ms after the key: the GPU compiling, once per profile, the programs for what the
 * workspace draws and the title never does -- rounded and bordered rects, the glass's blur and
 * gradients, the icons' path fills, the rails' turned text. Here the workspace is shown for three
 * frames while the title stands, at 1% opacity above it, with a handful of sample rows in its
 * empty lists (the register's, the modules', the day's track) so the rows' shapes are among them.
 * Nothing is read and nothing is said: the page is inert and hidden from assistive technology for
 * those frames, the samples are taken out again, and the workspace is hidden as it was. An
 * accepted key ends it at once (endWorkspacePaintWarm).
 */
let paintWarm = /** @type {{done: boolean, added: Element[], chrome?: HTMLElement[]}|null} */ (null);
function warmWorkspacePaint() {
  if (paintWarm || !workspace.hidden || ownerToken || busy) return;
  const warm = { done: false, added: /** @type {Element[]} */ ([]), chrome: /** @type {HTMLElement[]} */ ([]) };
  paintWarm = warm;
  const fill = (/** @type {string} */ id, /** @type {string} */ markup) => {
    const host = document.getElementById(id);
    if (!host || host.children.length) return;
    const holder = document.createElement('template');
    holder.innerHTML = markup;
    for (const node of Array.from(holder.content.children)) {
      host.append(node);
      warm.added.push(node);
    }
  };
  const item = (/** @type {string} */ kind, /** @type {string} */ extra) => `<li class="ledger-item ledger-${kind}"><time>00:00:00</time><div><div class="ledger-head"><strong>Aaaa</strong> <span class="ledger-arrow">→</span> <strong>Aaaa</strong> · aaaa${extra}</div><div class="ledger-text">aaaa aaaa</div><div class="ledger-open">Aaaa ↗</div></div></li>`;
  fill('ledger-filters', '<button type="button" class="ledger-chip is-active" tabindex="-1">Aaaa</button><button type="button" class="ledger-chip" tabindex="-1">Aaaa</button>');
  fill('ledger-list', `<li class="ledger-day">aaaa</li>${item('system', '<span class="ledger-repeat">×2</span>')}${item('owner', '')}${item('talk', '')}<li class="ledger-item ledger-system is-repeat"><time>00:00:00</time><div><div class="ledger-head">aaaa</div><span class="ledger-span">00:00:00 – 00:00:00</span></div></li>`);
  fill('modules', '<li data-status="IMPLEMENTED">Aaaa<span class="module-state">Aaaa</span></li><li data-status="PARTIAL">Aaaa<span class="module-state">Aaaa</span></li><li data-status="NOT_IMPLEMENTED">Aaaa<span class="module-state">Aaaa</span></li>');
  const bar = document.querySelector('#day-track .day-track-bar');
  if (bar && !bar.children.length) {
    const ns = 'http://www.w3.org/2000/svg';
    for (const [x, seg] of /** @type {Array<[number, string]>} */ ([[0, 'seg-done'], [17, 'seg-running'], [34, 'seg-pending']])) {
      const rect = document.createElementNS(ns, 'rect');
      for (const [k, v] of Object.entries({ x: String(x), y: '0', width: '14', height: '6', rx: '1', class: `track-seg ${seg}` })) rect.setAttribute(k, v);
      bar.append(rect);
      warm.added.push(rect);
    }
  }
  // The masthead and the footer strip are the frame's too (the rooms' menu, the Owner's keys):
  // they are painted with it. The drawers are laid out as the key will find them, so the rails,
  // the menu in the masthead and the drawers' own state are among what is painted.
  const chrome = /** @type {HTMLElement[]} */ (Array.from(document.querySelectorAll('.topbar, .site-footer')));
  for (const el of chrome) {
    el.inert = true;
    el.setAttribute('aria-hidden', 'true');
  }
  warm.chrome = chrome;
  workspace.inert = true;
  workspace.setAttribute('aria-hidden', 'true');
  workspace.classList.add('is-warming');
  document.body.classList.add('is-paint-warm');
  workspace.hidden = false;
  if (!drawers.started && drawers.isFramed()) drawers.start();
  let frames = 0;
  const tick = () => {
    if (warm.done) return;
    frames += 1;
    if (frames < 4) {
      requestAnimationFrame(tick);
      return;
    }
    endWorkspacePaintWarm({ hide: true });
  };
  requestAnimationFrame(tick);
}

/** Take the warm-up away: its samples, its class, and (unless a key is entering) the workspace. @param {{hide: boolean}} options */
function endWorkspacePaintWarm(options) {
  const warm = paintWarm;
  if (!warm || warm.done) return;
  warm.done = true;
  for (const node of warm.added) node.remove();
  warm.added = [];
  workspace.classList.remove('is-warming');
  document.body.classList.remove('is-paint-warm');
  for (const el of warm.chrome || []) {
    el.inert = false;
    el.removeAttribute('aria-hidden');
  }
  workspace.inert = false;
  workspace.removeAttribute('aria-hidden');
  if (options.hide) workspace.hidden = true;
}

function whenIdle(/** @type {() => void} */ run) {
  const idle = /** @type {any} */ (window).requestIdleCallback;
  if (typeof idle === 'function') idle(run, { timeout: 1500 });
  else window.setTimeout(run, 200);
}
// After the title has had its first frames, not in their way.
window.addEventListener('load', () => whenIdle(() => { warmOffice().catch(() => {}); }), { once: true });

function initOffice() {
  buildOfficeEngine();
  officeEngine.unpark();
  if (!officeWired) {
    officeWired = true;
    startLiveStream();

    // The camera keys zoom about the middle of the room the drawers leave; «Încadrează» stands
    // the camera where the frame puts it, with the building whole.
    element('zoom-in').addEventListener('click', () => {
      officeEngine.zoomBy(1.25);
    });
    element('zoom-out').addEventListener('click', () => {
      officeEngine.zoomBy(0.8);
    });
    element('zoom-fit').addEventListener('click', () => {
      officeEngine.fitView({ glide: true });
    });
    element('zoom-reset').addEventListener('click', () => {
      officeEngine.zoomTo(1.0);
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
        // In the game frame the whole frame goes full screen -- the render with its drawers, its
        // dock and the studio's menu -- the way a game does; on a narrow page, the render alone.
        const target = drawers.isFramed() ? /** @type {any} */ (document.documentElement) : container;
        try {
          if (target.requestFullscreen) {
            await target.requestFullscreen();
          } else if (target.webkitRequestFullscreen) {
            await target.webkitRequestFullscreen();
          } else if (target.msRequestFullscreen) {
            await target.msRequestFullscreen();
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
  eventsLink.start();
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
    renderInspector({...agent,model_error:error instanceof Error?error.message:'Detaliile modelului nu au putut fi încărcate.',model_is_available:false});
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

/** What a run without an answer means, in words. */
const RUN_STATUS = {
  EMPTY_OUTPUT: 'Modelul nu a returnat text utilizabil.',
  // Runs recorded before an empty answer counted as a failure.
  SUCCEEDED: 'Niciun text în răspuns.',
  BLOCKED_POLICY: 'Blocat de politică.',
  BLOCKED_PROVIDER: 'Blocat: furnizorul sau modelul nu este disponibil.',
  // The day's token ceiling, not a spending budget: the run never reached a model, so it
  // cost nothing. Without this line the status printed as the raw word BLOCKED_BUDGET.
  BLOCKED_BUDGET: 'Blocat: s-a atins plafonul de tokeni al zilei pentru angajați.',
  FAILED: 'Eșuat.',
};

/**
 * A count and the noun after it, as a Romanian speaker says them.
 *
 * One is singular («1 eveniment»), and a numeral takes «de» when its last two digits are 00 or
 * 20 and above — «19 evenimente», «92 de evenimente», «101 evenimente», «120 de evenimente».
 * The panels used to print the plural against every figure, so a day with one notable event
 * read «1 evenimente de povestit» (measured 2026-09-23, the closed day of 2026-09-12).
 * `entryCountLabel` in `ledger.js` says the same thing for the register's own entries.
 *
 * @param {number} count @param {string} one the noun phrase after 1
 * @param {string} many the noun phrase after every other number
 */
function countLabel(count, one, many) {
  const n = Number(count) || 0;
  const rest = Math.abs(n) % 100;
  if (Math.abs(n) === 1) return `1 ${one}`;
  return `${n}${Math.abs(n) >= 20 && (rest === 0 || rest >= 20) ? ' de' : ''} ${many}`;
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
      ? `<details class="chat-prompt"><summary>Cererea completă</summary><pre>${escapeHtml(full)}</pre></details>`
      : '';
    return `<div class="chat-item chat-run${isChat ? ' is-chat' : ''}"><div class="chat-meta"><span class="policy-tag policy-flexible">${escapeHtml(label)}</span> <small>${escapeHtml(timelineTime(item.at))}${meta ? ` · ${escapeHtml(meta)}` : ''}</small></div>${line ? `<div class="chat-asked">${escapeHtml(line)}</div>` : ''}${answer}${prompt}</div>`;
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
      : '<div class="helper">Nimic încă: nicio sarcină, niciun mesaj și nicio decizie înregistrată.</div>';
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
  const sections = [['watch_for', 'Urmărește'], ['investigate', 'Investighează'], ['correct', 'Corectează'], ['let_pass', 'Lasă să treacă'], ['never_let_pass', 'Nu lasă să treacă niciodată'], ['escalate_when', 'Escaladează când'], ['deliverables', 'Livrabile']];
  element('inspector-contract').innerHTML = sections
    .filter(([key]) => Array.isArray(work[key]) && work[key].length)
    .map(([key, label]) => `<div class="identity-block"><span class="stat-label">${escapeHtml(label)}</span><ul>${work[key].map((item) => `<li>${escapeHtml(String(item))}</li>`).join('')}</ul></div>`)
    .join('') || '<p class="helper">Rolul nu are încă un contract de muncă. Rulează bootstrap-ul ca să fie creat.</p>';
  element('inspector-system-prompt').textContent = identity.system_prompt || '';
  const memory = identity.memory || [];
  element('inspector-memory').innerHTML = memory.length
    ? memory.map((m) => `<li><span class="policy-tag policy-flexible">${escapeHtml(m.memory_class)}</span> ${escapeHtml(m.content)}</li>`).join('')
    : '<li class="helper">Nu ține minte nimic încă: nicio verificare, decizie sau publicare înregistrată.</li>';
  const messages = (identity.messages || []).filter((m) => m.status !== 'RESOLVED').slice(0, 8);
  element('inspector-messages').innerHTML = messages.length
    ? messages.map((m) => `<li class="inspector-mail" data-thread="${escapeHtml(m.thread_id || m.id)}" title="Deschide firul de corespondență"><span class="policy-tag policy-locked">${escapeHtml(m.intent)}</span> ${escapeHtml(m.subject)}${m.from_name ? ` <small>· de la ${escapeHtml(m.from_name)}</small>` : ''} <small class="ledger-open">fir ↗</small></li>`).join('')
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
    modelEl.className='stat-value';modelEl.title='Se citesc datele curente ale angajatului.';
  } else if(agent.model_error) {
    modelEl.textContent='Alocarea nu a putut fi verificată';
    modelEl.className='stat-value text-error';modelEl.title=agent.model_error;
  } else if (!agent.model_name) {
    modelEl.textContent = 'Niciun model alocat';
    modelEl.className = 'stat-value text-error';
    modelEl.title = 'Alocă un model acestui angajat în Setări › Angajați.';
  } else if (agent.model_is_available) {
    modelEl.textContent = agent.model_name;
    modelEl.className = 'stat-value text-success';
    modelEl.title = `Furnizor: ${agent.provider_name || 'necunoscut'}`;
  } else {
    modelEl.textContent = `${agent.model_name} · neverificat`;
    modelEl.className = 'stat-value text-warn';
    modelEl.title =
      `Modelul este alocat, dar furnizorul ${agent.provider_name || ''} nu a fost verificat. ` +
      'Verifică-l în Setări înainte de a porni o sarcină.';
  }
  runBtn.disabled = !agent.model_is_available;
  runBtn.title = agent.model_is_available
    ? ''
    : 'Pornirea are nevoie de un model verificat. Alocă și verifică unul în Setări.';

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
  btn.innerHTML = icon(inspectorExpanded ? 'collapse' : 'expand');
  btn.title = inspectorExpanded
    ? 'Strânge fereastra la mărimea obișnuită'
    : 'Extinde: toată discuția și istoricul, de sus până jos';
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
    notify('Browserul a blocat fereastra live. Permite pop-up-urile pentru această pagină și apasă din nou.');
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
  typing.textContent = `Întrebarea a fost trimisă. ${currentSelectedAgent.display_name || 'Angajatul'} scrie…`;

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
    outputDiv.textContent = `Eroare: ${err instanceof Error ? err.message : err}`;
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
        `${tested.length} site-uri testate, ${tested.length - failed.length} citibile${failed.length ? `. Nu pot fi citite: ${failed.map((t) => `${t.host} (${t.reason})`).join(', ')}` : '.'}`,
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
      list.innerHTML = '<li class="helper">Tendințele sunt oprite în configurație (STUDIO_TRENDS_ENABLED).</li>';
      return;
    }
    list.innerHTML = data.items.length
      ? data.items.map((t) => `<li title="${escapeHtml((t.news || []).join(' · '))}"><span>${escapeHtml(t.title)}</span><small>${t.approx_traffic ? `~${Number(t.approx_traffic).toLocaleString('ro-RO')}` : '—'}</small></li>`).join('')
      : `<li class="helper">Nimic citit încă pentru ${escapeHtml(data.geo)}. Apasă «Citește tendințele».</li>`;
  } catch (error) {
    list.innerHTML = `<li class="text-error">${escapeHtml(error instanceof Error ? error.message : 'Tendințele nu au putut fi citite.')}</li>`;
  }
}
element('open-research-btn').addEventListener('click', () => { loadTrends(); });
element('trends-refresh').addEventListener('click', async (event) => {
  const button = /** @type {HTMLButtonElement} */ (event.currentTarget);
  button.disabled = true;
  try {
    const result = await api('/analytics/trends/refresh', { method: 'POST' });
    notify(result.status === 'COMPLETED'
      ? `Tendințe citite (${result.geo}): ${result.count} noi din ${result.seen}.`
      : `Tendințele nu au putut fi citite: ${result.reason || result.status}`);
    await loadTrends();
  } catch (error) {
    notify(error instanceof Error ? error.message : 'Tendințele nu au putut fi citite.');
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
            <span>Public: ${escapeHtml(t.target_audience)}</span> · <span>Stare: <strong class="topic-card-status">${escapeHtml(t.status)}</strong></span>
          </div>
        </div>
      `;
      })
      .join('');
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">Încărcarea a eșuat: ${escapeHtml(err.message)}</div>`;
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
  REFUTED: 'Infirmată de sursă',
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
 * Why the last test failed, in the closed vocabulary the backend records. A site behind a
 * bot wall and a site that is an empty shell until its scripts run are two different jobs
 * for the Owner, and the reason code is what tells them apart without reading the detail.
 */
const HOST_REASON_LABEL = {
  HTTP_403: 'a refuzat studioul (403)',
  HTTP_ERROR: 'a răspuns cu o eroare',
  RATE_LIMITED: 'limitează cererile',
  SCRIPT_ONLY: 'nu arată nimic fără JavaScript',
  NETWORK: 'nu a răspuns',
  OTHER: 'a răspuns cu nimic utilizabil',
};

/** Whose search address is in force: the Owner's is a decision, a discovered one a finding. */
const TEMPLATE_ORIGIN_LABEL = { OWNER: 'căutarea ta', DISCOVERED: 'căutarea proprie' };

/**
 * The authorised sites, each with the result of its last connectivity test. A site is a
 * source only if the studio can actually read it, so the test is next to the entry, and a
 * site that never passed is marked as such rather than assumed fine.
 */
function renderAllowedHosts(rows, health) {
  const box = element('allowed-hosts');
  const allowEl = element('sources-allowlist');
  if (!rows.length) {
    allowEl.textContent = 'Niciun site autorizat. Adaugă unul mai jos și testează-l; până atunci preluarea surselor este oprită.';
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
    `${rows.length} site-uri autorizate, ${passed} testate cu succes, ${searchable} cu adresă de căutare.`,
  ];
  if (health) {
    line.push(health.search_provider === 'VERIFIED' ? 'Un motor de căutare web este conectat.' : 'Niciun motor de căutare web nu este conectat.');
    line.push(`${health.claims_available} afirmații verificate în evidență.`);
    if (health.status === 'DEGRADED') line.push(...(health.degraded_reasons || []));
  }
  line.push('Numai Proprietarul poate schimba lista; angajații nu au niciun instrument pentru ea.');
  allowEl.textContent = line.join(' ');
  allowEl.className = (health ? health.status === 'DEGRADED' : !passed) ? 'helper-note helper-warn' : 'helper-note';
  box.innerHTML = rows
    .map((r) => {
      const status = r.last_test_status
        ? `<span class="host-test host-test-${escapeHtml(r.last_test_status.toLowerCase())}" title="${escapeHtml(r.last_test_detail || '')}">${escapeHtml(HOST_TEST_LABEL[r.last_test_status] || r.last_test_status)}${r.last_test_at ? ` · ${escapeHtml(new Date(r.last_test_at).toLocaleString('ro-RO'))}` : ''}</span>`
        : '<span class="host-test host-test-untested">netestat</span>';
      const origin = r.source === 'env' ? '<span class="host-origin">.env</span>' : '';
      const remove = r.source === 'owner'
        ? `<button class="quiet btn-host-remove" data-host="${escapeHtml(r.host)}">Șterge</button>`
        : '';
      // The site's own search address: with one, the studio finds pages that exist instead
      // of the Researcher guessing addresses that 404. Only a row the Owner added holds it.
      // "Try it" runs whichever address is in force, the Owner's or the one the studio
      // found, because the search resolves the same way. Typing one in belongs to the
      // Owner's own rows: a site that comes from .env has no entry of his to edit, but its
      // own search address still works and is still worth trying.
      const tryIt = r.search_template_origin
        ? `<button class="quiet btn-host-search-try" data-host="${escapeHtml(r.host)}">Încearcă</button>`
        : '';
      const search = r.source === 'owner'
        ? `<div class="host-search">
            <input class="host-search-template" data-host="${escapeHtml(r.host)}" value="${escapeHtml(r.search_template || '')}" placeholder="adresa de căutare a site-ului, cu {query} unde intră cuvintele (OpenSearch JSON)" title="De exemplu, pentru o enciclopedie MediaWiki: https://${escapeHtml(r.host)}/w/api.php?action=opensearch&search={query}&limit=5&namespace=0&format=json">
            <button class="quiet btn-host-search-save" data-host="${escapeHtml(r.host)}">Salvează căutarea</button>
            ${tryIt}
          </div>`
        : tryIt ? `<div class="host-search">${tryIt}</div>` : '';
      // The address the studio found on the site itself, when a test read one. It is shown
      // even where the Owner typed his own, which supersedes it: the point is that he can
      // see what the studio would search this site with, and when it last saw it.
      const found = r.discovered_search_template
        ? `<div class="host-test-detail">${escapeHtml(TEMPLATE_ORIGIN_LABEL.DISCOVERED)}${r.discovered_at ? ` · ${escapeHtml(new Date(r.discovered_at).toLocaleString('ro-RO'))}` : ''}: <code>${escapeHtml(r.discovered_search_template)}</code>${r.search_template ? ' — nefolosită, a ta are prioritate' : ''}</div>`
        : '';
      const badge = r.search_template_origin
        ? ` <span class="host-search-badge" title="${escapeHtml(r.search_template || r.discovered_search_template || '')}">${escapeHtml(TEMPLATE_ORIGIN_LABEL[r.search_template_origin] || r.search_template_origin)}</span>`
        : '';
      // The reason code first, then the site's own words for it: the code is the same on
      // every host and can be compared, the detail is what actually came back.
      const why = r.last_test_status === 'FAILED'
        ? `<div class="host-test-detail text-error">${escapeHtml(HOST_REASON_LABEL[r.last_test_reason] || r.last_test_reason || 'nu poate fi citit')}${r.last_test_detail ? ` · ${escapeHtml(r.last_test_detail)}` : ''}</div>`
        : '';
      return `
        <div class="allowed-host-row" data-host="${escapeHtml(r.host)}">
          <code class="allowed-host-name">${escapeHtml(r.host)}</code> ${origin} ${status}${badge}
          <span class="allowed-host-actions">
            <button class="quiet btn-host-test" data-host="${escapeHtml(r.host)}">Testează</button>
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
        showSourceStatus(input && input.value.trim() ? `Adresa de căutare pentru ${host} a fost salvată.` : `Adresa de căutare pentru ${host} a fost ștearsă.`, false);
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
            ? `${host} a găsit ${found.length} pagini pentru «history of science»: ${found.map((f) => f.title).join('; ')}`
            : `${host} nu a returnat nicio pagină pentru «history of science»; verifică adresa de căutare.`,
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
  if (button) { button.disabled = true; button.textContent = 'Se testează…'; }
  try {
    const result = await api(`/factual/sources/allowed-hosts/${encodeURIComponent(host)}/test`, { method: 'POST' });
    showSourceStatus(
      result.status === 'PASSED'
        ? `${host}: citibil. ${result.detail}`
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
            · <span>fingerprint ${escapeHtml(shortHash(src.content_hash))}</span>
            · <span>${escapeHtml(new Date(src.fetched_at).toLocaleString('ro-RO'))}</span>
          </div>
          <div class="topic-card-meta">${escapeHtml(claimCountsSummary(src.claim_counts))}</div>
          <div class="source-actions">
            <button class="secondary btn-extract-claims" data-source-id="${escapeHtml(src.id)}">Extrage afirmațiile cu angajatul</button>
            <button class="quiet btn-show-claims" data-source-id="${escapeHtml(src.id)}">Arată afirmațiile</button>
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
    listEl.innerHTML = `<div class="text-error">Încărcarea a eșuat: ${escapeHtml(err.message)}</div>`;
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
    ? `<blockquote class="claim-evidence">„${escapeHtml(claim.evidence_text)}”</blockquote>`
    : '';
  const notes = claim.verifier_notes
    ? `<div class="claim-notes">${escapeHtml(claim.verifier_notes)}</div>`
    : '';
  const by = claim.verified_by_agent_id
    ? ' · verificată de un angajat'
    : claim.verified_at
      ? ' · verificată de Proprietar'
      : '';

  const actions = unverified
    ? `<button class="quiet btn-agent-verify" data-claim-id="${escapeHtml(claim.id)}">Verifică cu un al doilea angajat</button>
       <button class="quiet btn-owner-verdict" data-claim-id="${escapeHtml(claim.id)}">Verdict propriu…</button>`
    : '';

  const form = unverified
    ? `<form class="owner-verdict-form" id="verdict-${escapeHtml(claim.id)}" data-claim-id="${escapeHtml(claim.id)}" hidden>
         <select name="status" aria-label="Verdict">
           <option value="SUPPORTED">Susținută de sursă</option>
           <option value="REFUTED">Infirmată de sursă</option>
           <option value="UNCERTAIN">Sursa nu spune</option>
         </select>
         <input name="evidence" placeholder="Citat din sursă (opțional)" maxlength="4000" />
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
  claimStatusBox('Angajatul citește sursa… poate dura până la un minut.', false);
  button.disabled = true;
  try {
    const result = await api(`/factual/sources/${sourceId}/extract-with-agent`, {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID() }),
    });
    const n = (result.claims || []).length;
    claimStatusBox(
      `${countLabel(n, 'afirmație extrasă', 'afirmații extrase')}, toate UNVERIFIED — un al doilea angajat trebuie să le confirme din sursă înainte de scenariu.`,
      false,
    );
    // The source cards are re-rendered first: reopening the claims before that would fill a
    // box that is about to be replaced, and the list would vanish under the Owner.
    await loadSources();
    await loadClaims(sourceId);
  } catch (err) {
    claimStatusBox(`Extragerea a eșuat: ${err.message}`, true);
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
  claimStatusBox('Un al doilea angajat citește sursa…', false);
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
    button.textContent = 'Verifică cu un al doilea angajat';
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
      statusDiv.textContent = `Preluată: „${result.source.title}” — amprenta conținutului ${shortHash(receipt.content_sha256)}. Nimic nu contează ca adevărat până nu este verificat.`;
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
  VERIFIED_PASS: 'A trecut poarta factuală',
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
      picker.append(new Option('Alege un subiect…', ''));
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
          <div class="scene-meta">Scena ${scene.scene_number || '?'} · ${countLabel((scene.claim_ids || []).length, 'afirmație citată', 'afirmații citate')}${scene.visual_description ? ` · ${escapeHtml(scene.visual_description)}` : ''}</div>
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
        · <span>${countLabel((script.claim_ids_json || []).length, 'afirmație', 'afirmații')}</span>
        · <span>${countLabel((script.scenes_json || []).length, 'scenă', 'scene')}</span>
      </div>
      ${blocked ? `<p class="helper-warn helper-note">Blocat: ${countLabel((script.unverified_claim_ids_json || []).length, 'afirmație citată nu este susținută', 'afirmații citate nu sunt susținute')} de o sursă.</p>` : ''}
      <div class="script-scenes">${scenes}</div>
      ${status === 'VERIFIED_PASS' ? `<div class="source-actions"><button class="secondary btn-approve-script" data-script-id="${escapeHtml(script.id)}">Aprobă scenariul</button></div>` : ''}
    </div>`;
}

async function approveScript(button) {
  const scriptId = button.getAttribute('data-script-id');
  button.disabled = true;
  scriptStatusBox('Se reverifică poarta factuală…', false);
  try {
    await api(`/factual/scripts/${scriptId}/approve`, {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID() }),
    });
    scriptStatusBox('Scenariu aprobat. Apare acum în Producție media, gata pentru un storyboard.', false);
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
        `„${script.title}” — ${countLabel((script.scenes_json || []).length, 'scenă', 'scene')}, ${countLabel((script.claim_ids_json || []).length, 'afirmație citată', 'afirmații citate')}.`,
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
    statusDiv.textContent = 'Se trimite subiectul spre analiză…';

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
      statusDiv.textContent = 'Subiect înregistrat.';
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
  if (binding.voice_id) parts.push(`Voce alocată: ${escapeHtml(binding.voice_id)}${binding.model_id ? ` · model ${escapeHtml(binding.model_id)}` : ''}`);
  if (lockedFields.length) parts.push(`Blocate: ${escapeHtml(lockedFields.join(', '))}`);
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
        '<div class="topics-loading">Niciun personaj înregistrat în Character Bible.</div>';
      return;
    }
    listEl.innerHTML = chars.map(characterCard).join('');
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">Încărcarea personajelor a eșuat: ${escapeHtml(err.message)}</div>`;
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
            · <span>${countLabel(script.scene_count, 'scenă', 'scene')}</span>
            · <span>${countLabel(script.claim_count, 'afirmație verificată', 'afirmații verificate')}</span>
          </div>
          ${storyReviewBlock(reviews[index])}
          <div class="source-actions">
            <button class="quiet btn-story-review" data-script-id="${escapeHtml(script.id)}">Citește povestea</button>
            <button class="secondary btn-make-storyboard" data-script-id="${escapeHtml(script.id)}">Creează storyboard</button>
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
    return `<div class="story-review is-none">Povestea nu a fost citită încă. Nimic nu intră
      în producție înainte de asta.</div>`;
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
        <span>${amount(Number(review.estimated_seconds || 0).toFixed(1))}s de narațiune</span>
      </div>
      ${failed.length ? `<div class="story-review-failed">Nu trece: ${failed.map(escapeHtml).join(', ')}</div>` : ''}
      ${curve ? `<div class="story-review-curve">Retenție estimată — ${escapeHtml(curve)}</div>` : ''}
      ${retention.collapse_at ? `<div class="story-review-curve">Se pierde la ${escapeHtml(String(retention.collapse_at))}s: ${escapeHtml(String(retention.why || ''))}</div>` : ''}
      ${(review.notes || []).slice(0, 3).map((note) => `<div class="motion-reason">${escapeHtml(String(note))}</div>`).join('')}
    </div>`;
}

async function runStoryReview(button) {
  const scriptId = button.getAttribute('data-script-id');
  button.disabled = true;
  mediaStatusMsg.hidden = false;
  mediaStatusMsg.className = 'dialog-status-msg';
  mediaStatusMsg.textContent = 'Directorul citește povestea înainte de producție…';
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
  mediaStatusMsg.textContent = 'Se construiește storyboardul din scenariul aprobat…';
  try {
    const storyboard = await api(`/media/storyboards/from-script/${scriptId}`, {
      method: 'POST',
      body: JSON.stringify({
        visual_style: 'MOTION_GRAPHIC',
        aspect_ratio: '9:16',
      }),
    });
    mediaStatusMsg.textContent = `Storyboard creat: „${storyboard.title}” — ${storyboard.total_scenes} scene.`;
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
      <summary>De ce acest film</summary>
      ${line('Faptul', why.core_fact)}
      ${line('De ce contează', why.why_it_matters)}
      ${line('Mesajul', pack.core_message)}
      ${line('Deschiderea', pack.hook)}
      ${line('Răsplata', why.payoff)}
      ${line('Îndemn', `${(pack.cta || {}).text || ''} (${(pack.cta || {}).kind || '—'})`)}
      ${line('Analiza poveștii', (pack.approval || {}).story_review)}
      ${line('Durată estimată', `${amount(Number(pack.expected_duration_seconds || 0).toFixed(1))}s`)}
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
          ? `<div><strong>Surse:</strong> ${(pack.trusted_sources || [])
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
        motion.estimated_usd != null ? `${amount(Number(motion.estimated_usd).toFixed(2))} USD` : 'cost nemăsurat'
      }${motion.from_prompt ? ' · din text, fără cadru plătit' : ''}</span></div>`
    : '';
  const rows = (scenes || [])
    .map((scene) => {
      const decision = scene.decision || {};
      const price =
        scene.quoted_usd != null
          ? `${amount(Number(scene.quoted_usd).toFixed(2))} USD (cotat de vendor)`
          : decision.price_usd != null
            ? `${amount(Number(decision.price_usd).toFixed(2))} USD (preț înregistrat)`
            : 'preț necunoscut';
      const outcome = scene.refused
        ? `<span class="text-error">nefilmată: ${escapeHtml(String(scene.refused))}</span>`
        : `${scene.bytes ? 'filmată' : 'niciun clip'}`;
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
      <summary>De ce aceste modele</summary>
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
          Niciun storyboard în flux.
          <br>Apasă «Creează un caz demo» ca să se genereze automat un scenariu verificat 9:16.
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
                  ? `<button class="video-play" data-asset="${escapeHtml(assetId)}" title="Redă filmul">${icon('play')}Redă</button>`
                  : '<div class="tag">Video 9:16</div>'
              }
            </div>
            <div class="video-details">
              ${
                assetId
                  ? `<div class="video-actions"><a class="quiet" href="#" data-download="${escapeHtml(assetId)}">Descarcă fișierul</a></div>`
                  : ''
              }
              <div><strong>Format măsurat:</strong> ${
                tech.measured_width
                  ? `${tech.measured_width}x${tech.measured_height} · ${tech.measured_duration_seconds}s · ${escapeHtml(String(tech.video_codec || '—'))}`
                  : 'nemăsurat'
              }</div>
              <div>${qcBadge}</div>
              ${qcScoresHtml}
              ${motionExplanation(motion, motionScenes, motionNotes)}
              <div><strong>Amprenta SHA-256 a fișierului:</strong></div>
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
                <span>Stare: <strong class="text-accent">${escapeHtml(sb.status)}</strong></span>
              </div>
            </div>
            <div class="storyboard-actions">
              <button class="btn-render-video" data-id="${sb.id}">Randare 9:16</button>
              <button class="btn-qc-video" data-id="${sb.id}">Verifică QC</button>
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
      if (button) { button.disabled = true; button.textContent = 'Se încarcă…'; }
      try {
        const response = await fetch(`/api/v1/media/assets/${assetId}/stream`, {
          headers: { Authorization: `Bearer ${ownerToken}` },
          cache: 'no-store',
        });
        if (!response.ok) throw new Error(`Fișierul nu a putut fi citit (${response.status}).`);
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
        if (button) { button.disabled = false; button.innerHTML = `${icon('play')}Redă`; }
        alert(`Filmul nu a putut fi redat: ${err.message}`);
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
          if (!response.ok) throw new Error(`Fișierul nu a putut fi citit (${response.status}).`);
          const url = URL.createObjectURL(await response.blob());
          const save = document.createElement('a');
          save.href = url;
          save.download = `short_9_16_${assetId.slice(0, 8)}.mp4`;
          save.click();
          setTimeout(() => URL.revokeObjectURL(url), 30000);
        } catch (err) {
          alert(`Filmul nu a putut fi descărcat: ${err.message}`);
        }
      });
    });

    listEl.querySelectorAll('.btn-render-video').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const id = btn.getAttribute('data-id');
        if (!id) return;
        btn.textContent = 'Se randează…';
        // @ts-ignore
        btn.disabled = true;
        try {
          await api(`/media/render/${id}`, { method: 'POST' });
          await loadMediaStoryboards();
          await refresh();
        } catch (err) {
          alert(`Randarea a eșuat: ${err.message}`);
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
        btn.textContent = 'Se evaluează QC…';
        // @ts-ignore
        btn.disabled = true;
        try {
          await api(`/media/qc/${id}`, { method: 'POST' });
          await loadMediaStoryboards();
          await refresh();
        } catch (err) {
          alert(`QC a eșuat: ${err.message}`);
          btn.textContent = 'Verifică QC';
          // @ts-ignore
          btn.disabled = false;
        }
      });
    });
  } catch (err) {
    listEl.innerHTML = `<div class="text-error">Încărcarea producției media a eșuat: ${escapeHtml(err.message)}</div>`;
  }
}

if (generateDemoStoryboardBtn) {
  generateDemoStoryboardBtn.addEventListener('click', async () => {
    mediaStatusMsg.hidden = false;
    mediaStatusMsg.className = 'dialog-status-msg';
    mediaStatusMsg.textContent =
      'Se creează cazul demo (subiect, scenariu și afirmație UNVERIFIED)…';
    try {
      const fixture = await api('/media/storyboards/demo-fixture', {
        method: 'POST',
      });
      mediaStatusMsg.textContent =
        fixture.next_step || 'Cazul demo a fost creat. Verifică afirmațiile în panoul Cercetare.';
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
  NOT_CONFIGURED: 'Slot de canal. Nu are un ID real de canal YouTube și nu poate publica.',
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
      status.textContent = result.active === false ? 'Bugetul a fost retras.' : `Buget ${result.period === 'DAILY' ? 'zilnic' : 'lunar'} de ${amount(result.limit_usd)} USD setat.`;
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
  FLEXIBLE: 'FLEXIBIL · tehnologia se alege pentru fiecare film',
  CONSISTENCY_LOCKED: 'CONSISTENȚĂ BLOCATĂ · identitatea personajelor nu se schimbă niciodată',
};

async function loadPublishingHub() {
  const channelsEl = element('channels-list');
  const pubListEl = element('publications-list');

  try {
    const [chData, pubData, performance] = await Promise.all([
      api('/publishing/channels'),
      api('/publishing/publications'),
      // One bar per film each channel published, from what YouTube measured (hud_charts.js).
      api('/analytics/performance').catch(() => null),
    ]);
    const films = (channelId) =>
      performance && Array.isArray(performance.videos)
        ? channelFilmsHtml(performance.videos, channelId)
        : '<p class="chart-empty">Măsurătorile filmelor nu au putut fi citite.</p>';

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
          'Nicio credențială YouTube configurată: publicarea este oprită. Setează STUDIO_YOUTUBE_CLIENT_ID, STUDIO_YOUTUBE_CLIENT_SECRET și STUDIO_YOUTUBE_REFRESH_TOKEN în .env. Studioul nu simulează niciodată publicarea.';
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
            <div class="channel-meta">Tip: <strong>${escapeHtml(c.channel_type)}</strong> · ID extern: <code>${escapeHtml(c.remote_channel_id || 'nesetat')}</code></div>
            <div class="channel-meta">${escapeHtml(CHANNEL_STATUS_HINT[c.status] || 'Stare necunoscută.')}</div>
            <div class="channel-meta">Politica de producție: <span class="policy-tag ${c.production_policy === 'CONSISTENCY_LOCKED' ? 'policy-locked' : 'policy-flexible'}">${escapeHtml(PRODUCTION_POLICY_LABEL[c.production_policy] || 'nesetată')}</span>${c.allow_production_override === false ? ' · fără excepții pe episod' : ''}</div>
            ${films(c.id)}
          </div>
          <div class="channel-meta channel-bind">
            <label>Cont YouTube
              <select data-bind-select="${escapeHtml(c.id)}" aria-label="Cont YouTube pentru ${escapeHtml(c.channel_name)}">
                <option value="">Nelegat</option>
                ${accounts.map((a) => `<option value="${escapeHtml(a.id)}" ${a.id === c.youtube_connection_id ? 'selected' : ''}>${escapeHtml(a.name)}${a.channel_title ? ` · ${escapeHtml(a.channel_title)}` : ''}</option>`).join('')}
              </select>
            </label>
            <button class="secondary" data-bind-channel="${escapeHtml(c.id)}" data-event="${escapeHtml(c.event_id || '')}">Leagă</button>
            <span class="helper">${c.publisher_ready ? `Publică pe ${escapeHtml(c.youtube_channel_title || c.youtube_connection_name || '')}` : 'Nelegat: slotul nu publică și nu are analytics.'}</span>
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
        '<div class="topics-loading">Nicio publicare înregistrată. Folosește butonul de mai sus ca să publici un film aprobat.</div>';
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
                <span>ID extern: <code>${escapeHtml(p.remote_video_id || '—')}</code></span>
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
      channelsEl.innerHTML = `<div class="text-error">Canalele nu au putut fi încărcate: ${escapeHtml(err.message)}</div>`;
    if (pubListEl)
      pubListEl.innerHTML = `<div class="text-error">Publicările nu au putut fi încărcate: ${escapeHtml(err.message)}</div>`;
  }
}

if (triggerQuickPublishBtn) {
  triggerQuickPublishBtn.addEventListener('click', async () => {
    publishingStatusMsg.hidden = false;
    publishingStatusMsg.className = 'dialog-status-msg';
    publishingStatusMsg.textContent =
      'Se verifică fluxul media și se caută cel mai recent film aprobat de QC…';
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
          'Nu s-a găsit niciun film cu raport QC PASSED. Creează întâi un storyboard și o randare 9:16 în Producție media.';
        return;
      }

      publishingStatusMsg.textContent = `Verificarea porții de conținut și încărcare privată pentru MediaAsset ${targetAssetId}…`;
      const pubRes = await api(`/publishing/publish-asset/${targetAssetId}`, {
        method: 'POST',
      });

      if (pubRes.status === 'PUBLISHED') {
        publishingStatusMsg.className = 'dialog-status-msg';
        publishingStatusMsg.textContent = `Filmul a fost încărcat privat pe YouTube. ID extern: ${pubRes.remote_video_id}`;
      } else if (pubRes.status === 'PUBLISHED_SIMULATED') {
        publishingStatusMsg.className = 'dialog-status-msg text-error';
        publishingStatusMsg.textContent =
          'Încărcare SIMULATĂ: nu există niciun video pe YouTube. Configurează credențiale reale.';
      } else {
        publishingStatusMsg.className = 'dialog-status-msg text-error';
        publishingStatusMsg.textContent = `Publicarea nu s-a încheiat. Stare: ${pubRes.status}. ${pubRes.error_detail || ''}`;
      }
      await loadPublishingHub();
      await refresh();
    } catch (err) {
      publishingStatusMsg.className = 'dialog-status-msg text-error';
      publishingStatusMsg.textContent = `Eroare la publicare: ${err.message}`;
    }
  });
}

function render(data) {
  element('studio-name').textContent = data.studio.name;
  // The masthead chip and the slate caption say «live» only while it is (live_claims.js).
  renderLiveSignals();
  element('snapshot-time').textContent =
    `Actualizat ${new Date(data.captured_at).toLocaleTimeString('ro-RO', { timeZone: data.studio.timezone })}`;
  renderSwitch(data.policy.autonomy_stopped);
  renderEnvironment(data.policy.environment);
  renderStudioReadout();
  renderAutonomyMode(data.policy);
  ledger.timezone = data.studio.timezone;
  const agentNames = Object.fromEntries(officeState.agents.map((a) => [a.id || a.agent_id, a.display_name]));
  ledger.setNames(agentNames);
  liveWindows.timezone = data.studio.timezone;
  mailThread.timezone = data.studio.timezone;
  liveWindows.setNames(agentNames);
  ledger.add(data.events || []);
  element('ledger-count').textContent = entryCountLabel(ledger.events.size);
  renderDayTrack();

  const labels = {
    agents: 'Angajați',
    providers: 'Furnizori AI',
    workflows: 'Automatizare',
    research: 'Cercetare factuală',
    media: 'Producție media',
    publishing: 'Publicare',
    story: 'Office Serial',
    treasury: 'Trezorerie VR$',
    procurement: 'VendorShop',
    financing: 'Finanțare',
    settings: 'Setări',
    analytics: 'Analitice',
  };
  // The three readings this panel has ever shown, in the Owner's language. `NOT_IMPLEMENTED`
  // was already said in Romanian and the other two were not, so one column read in two
  // languages. A reading this page has never heard of is still shown, exactly as it came.
  const moduleState = { IMPLEMENTED: 'Implementat', PARTIAL: 'Parțial', NOT_IMPLEMENTED: 'Neimplementat' };
  const modules = element('modules');
  modules.replaceChildren();
  for (const [name, status] of Object.entries(data.modules)) {
    const item = document.createElement('li');
    item.textContent = labels[name] || name;
    // The status the stylesheet reads stays exactly as it was; the data attribute only lets
    // the stylesheet draw a three-step meter beside it, so a column of words reads
    // as a reading of the studio rather than as a list.
    item.dataset.status = String(status);
    const badge = document.createElement('span');
    badge.className = 'module-state';
    badge.textContent = moduleState[String(status)] || String(status);
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
  banner.textContent = test ? 'MEDIU DE TEST' : 'PRODUCTION';
  banner.classList.toggle('is-test', test);
  banner.classList.toggle('is-production', !test);
  banner.title = test
    ? 'Se randează minimul, pe cel mai ieftin model compatibil, cu plafoane de cost pe generare și pe secundă.'
    : 'Randarea folosește cel mai ieftin model care atinge calitatea de care are nevoie fiecare scenă.';
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
  element('switch-state').textContent = pendingCommand ? '…' : on ? 'PORNIT' : 'OPRIT';
  stopButton.setAttribute('aria-pressed', String(on));
  stopButton.title = pendingCommand
    ? 'Ultima comandă nu a fost confirmată; apasă ca să fie verificată din nou.'
    : on
      ? 'Autonomia este pornită. Apasă pentru o oprire care rămâne.'
      : 'Autonomia este oprită. Apasă ca să o pornești; modul rămâne Manual.';
}

async function refresh() {
  const generation = epoch;
  try {
    const incoming = await api('/snapshot');
    if (generation !== epoch) return false;
    state = acceptSnapshot(state, incoming);
    if (!connected) notify('');
    connected = true;
    liveSignals.data = 'fresh';
    render(state);
    stopButton.disabled = busy;
    // Everything recorded since the ledger last looked, not only the twenty in the snapshot.
    try {
      await ledger.sync(api, state.cursor);
      element('ledger-count').textContent = entryCountLabel(ledger.events.size);
    } catch (error) {
      console.warn('ledger sync failed', error);
    }
    // The approvals have their own, slower clock; this only lets them ride the same poll.
    await loadApprovals();
    return true;
  } catch (error) {
    if (generation !== epoch) return false;
    connected = false;
    liveSignals.data = 'stale';
    renderLiveSignals();
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
  // The events socket is opened as soon as the workspace is up; until then the chip and the
  // corner say the page is connecting, not that it is live.
  liveSignals.socket = 'connecting';
  const success = await refresh();
  if (success) {
    // The camera goes into the building only here, on a key the backend has just accepted, and
    // never for a visitor who asked for less motion: they get the same workspace at once.
    const plays = entryPlays({ accepted: true, reducedMotion: reducedMotion(), titleShown: titleScreen.visible });
    endWorkspacePaintWarm({ hide: false });
    workspace.hidden = false;
    element('logout').hidden = false;
    input.value = '';
    // The key field is about to disappear; without a new home the keyboard would resume after
    // the whole title, somewhere inside the register. It lands on the register's heading, the
    // first thing the workspace says, and a screen reader hears where it now is.
    const arrival = /** @type {HTMLElement|null} */ (document.querySelector('.ledger-panel h2'));
    if (arrival) {
      arrival.tabIndex = -1;
      arrival.focus({ preventScroll: true });
    }
    // The frame's drawers and the menu are laid out before anything arrives, so the entry plays
    // into the frame as it will stay.
    if (drawers.started) drawers.layout({ glide: false });
    else drawers.start();
    if (plays) {
      // THE FIRST FRAME OF THE WORKSPACE IS HEAVY: its whole style and layout, about 55ms at 1920.
      // It is spent here, under a title that is still standing and a workspace that is not yet
      // seen, and the camera starts its push on the frame after it, so the push itself has no
      // dropped frame at its start.
      document.body.classList.add('is-arming');
      requestAnimationFrame(() => requestAnimationFrame(() => {
        document.body.classList.remove('is-arming');
        if (!ownerToken) return;
        titleScreen.enter().then((finished) => { if (finished && ownerToken) login.hidden = true; });
      }));
    } else {
      login.hidden = true;
      titleScreen.hide();
    }
    initOffice();
    // The key light's first reading copies a frame back from the GPU (18ms measured at the key);
    // it waits until the building has been entered, and then reads the frame the visitor sees.
    if (plays) window.setTimeout(() => { if (ownerToken) keyLight.start(); }, ENTRY.totalMs + 80);
    else keyLight.start();
    loadDayRecord();
    loadWorldFigures();
    loadSerialFacts();
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
  eventsLink.stop();
  liveSignals.data = 'fresh';
  keyLight.stop();
  if (officeEngine) officeEngine.park();
  document.body.classList.remove('is-arming');
  workspace.hidden = true;
  login.hidden = false;
  titleScreen.show();
  input.value = '';
  notify('');
  ledger.clear();
  pendingMode = null;
  approvalsRouteMissing = false;
  approvalsLastRead = 0;
  approvalsList.replaceChildren();
  element('approvals-count').textContent = '—';
  renderOwnerMark(0);
  moments.reset();
  dayRecord = null;
  ledger.closedAt = null;
  dayTrackKey = '';
  window.clearTimeout(figuresTimer);
  window.clearTimeout(serialTimer);
  figuresTimer = 0;
  serialTimer = 0;
  resetWorldFacts();
  renderDayTrack();
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
    renderOwnerMark(pending.length);
    approvalsList.innerHTML = pending.length
      ? pending.map((request) => approvalCard(request, Date.now())).join('')
      : '<div class="topics-loading">Nicio cerere nu așteaptă decizia Proprietarului.</div>';
  } catch (err) {
    if (err.status === 404) {
      approvalsRouteMissing = true;
      element('approvals-count').textContent = '—';
      renderOwnerMark(0);
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
  TERMINATE_AGENT: 'Concediere',
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
  if (agent.runs === 0) return 'nicio rulare în perioadă';
  return `${countLabel(agent.runs, 'rulare', 'rulări')} · ${Math.round(agent.failure_rate * 100)}% eșecuri`;
}

async function loadWorkforce() {
  const summaryEl = element('workforce-summary');
  const agentsEl = element('workforce-agents');
  try {
    const data = await api('/workforce/measurements');
    summaryEl.innerHTML = `
      <div class="wf-stat"><span class="wf-stat-value">${data.active_agents}</span><span class="wf-stat-label">angajați activi</span></div>
      <div class="wf-stat"><span class="wf-stat-value">${data.queue_backlog}</span><span class="wf-stat-label">sarcini în coadă</span></div>
      <div class="wf-stat"><span class="wf-stat-value">${data.dead_letter_tasks}</span><span class="wf-stat-label">sarcini abandonate</span></div>
      <div class="wf-stat"><span class="wf-stat-value">${data.idle_agents.length}</span><span class="wf-stat-label">fără nicio rulare</span></div>`;
    summaryEl.insertAdjacentHTML(
      'beforeend',
      `<p class="helper-note wf-window">Măsurat pe ultimele ${data.window_days} zile, din rulările înregistrate.</p>`,
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
        '<div class="topics-loading">Nicio propunere. Măsurătorile nu susțin acum o schimbare de personal.</div>';
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
        ? `Aprobată și aplicată: ${PROPOSAL_TYPE_LABEL[result.proposal_type] || result.proposal_type}.`
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
  OWNER_CAPITAL: 'Aport al Proprietarului',
  OWNER_LOAN: 'Împrumut de la Proprietar',
  PROVIDER_COST: 'Cost de furnizor',
  ADJUSTMENT: 'Ajustare',
};

/** One figure with the label the backend gave it, so nothing is re-classified on the way out. */
function treasuryTile(row, extraClass = '') {
  const tile = document.createElement('div');
  tile.className = `wf-stat treasury-tile ${extraClass}`.trim();
  const value = document.createElement('span');
  value.className = 'wf-stat-value';
  value.textContent = `${amount(row.amount)} VR$`;
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
  const label = period.period === 'DAILY' ? 'Zilnic' : 'Lunar';
  const reserved = period.reserved_usd_micros
    ? `<div class="helper">${escapeHtml(amount(period.reserved_usd))} USD reținuți pentru filmele în producție</div>`
    : '';
  // The ring draws the same row: spent, then held, against the limit, with the warning line
  // where the Accountant escalates (hud_charts.js budgetRing).
  const ring = budgetRing(period);
  const ringLabel = ring.empty
    ? ''
    : `${label}: ${amount(period.spent_usd)} USD cheltuiți${period.reserved_usd_micros ? ` și ${amount(period.reserved_usd)} USD reținuți` : ''} din ${amount(period.limit_usd)} USD, ${ring.percent}%; linia de avertizare la ${Math.round((ring.warnFrac || 0) * 100)}%`;
  return `<div class="budget-card budget-ring-card budget-${escapeHtml(period.state)}"><div class="budget-ring-words"><span class="stat-label">${escapeHtml(label)} · ${escapeHtml(period.state)}</span><strong>${escapeHtml(amount(period.spent_usd))} / ${escapeHtml(amount(period.limit_usd))} USD</strong><span>rămân ${escapeHtml(amount(period.remaining_usd))} USD · ${Math.round(period.ratio * 100)}%</span>${reserved}${period.unpriced_agent_runs ? `<div class="helper">${period.unpriced_agent_runs} rulări fără preț înregistrat</div>` : ''}</div>${budgetRingSvg(period, ringLabel)}</div>`;
}

async function loadBudget() {
  const cards = element('budget-cards');
  try {
    const data = await api('/economy/budget');
    worldFacts.budget = data;
    pushWorldFacts();
    // Money held apart from money spent, and the two figures that say the total is
    // incomplete: a render paid for that delivered nothing, and the runs whose model has no
    // stored price. An unpriced run is real usage the books cannot value, so it is named
    // rather than counted as zero.
    const today = data.today;
    const held = today.reserved_usd_micros
      ? `<div class="helper">${escapeHtml(amount(today.reserved_usd))} USD reținuți azi pentru filmele în producție, încă necheltuiți</div>`
      : '';
    const wasted = today.failed_render_usd_micros
      ? `<div class="helper">${escapeHtml(amount(today.failed_render_usd))} USD pentru randări care au picat la jumătate</div>`
      : '';
    const unpriced = today.unpriced_agent_runs
      ? `<div class="helper">${today.unpriced_agent_runs} rulări azi fără preț înregistrat — totalul este mai mic decât cheltuiala reală</div>`
      : '';
    const spend = `<div class="budget-card"><span class="stat-label">Cheltuit</span><strong>azi ${escapeHtml(amount(today.spent_usd))} USD</strong><span>luna asta ${escapeHtml(amount(data.month.spent_usd))} USD · ${data.month.agent_runs} rulări de angajați, ${data.month.unpriced_agent_runs} fără preț</span>${held}${wasted}${unpriced}</div>`;
    const providers = data.month.by_provider.map((p) => `<div class="budget-card"><span class="stat-label">${escapeHtml(p.provider)}</span><strong>${escapeHtml(amount(((p.estimated_usd_micros + p.billed_usd_micros) / 1e6).toFixed(2)))} USD</strong><span>${countLabel(p.records, 'înregistrare', 'înregistrări')} · facturat ${escapeHtml(amount((p.billed_usd_micros / 1e6).toFixed(2)))}</span></div>`).join('');
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
    worldFacts.treasury = treasury;
    pushWorldFacts();

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
          money_class: 'Costuri de furnizor nefacturate',
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
    verdict.textContent = tb.balanced ? 'REGISTRU ECHILIBRAT' : 'REGISTRU NEECHILIBRAT';
    const detail = document.createElement('span');
    detail.textContent = tb.balanced
      ? `Debite ${amount(tb.total_debits)} = credite ${amount(tb.total_credits)}.${treasury.in_deficit ? ' Numerarul VR$ este negativ: trezoreria este în deficit.' : ''}`
      : `Diferență ${amount(tb.difference)}. Nicio cifră de mai sus nu poate fi crezută până nu se rezolvă.`;
    balance.append(verdict, detail);
    summary.append(balance);

    element('treasury-disclaimer').textContent = treasury.disclaimer;

    accountsBox.replaceChildren();
    if (!treasury.accounts.length) {
      const empty = document.createElement('div');
      empty.className = 'topics-loading';
      empty.textContent = 'Niciun cont nu are saldo. Registrul este gol.';
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
      value.textContent = `${amount(account.balance)} VR$`;
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
      empty.textContent = 'Nicio înregistrare. Nimic emis, nimic cheltuit.';
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
      const figure = document.createElement('span');
      figure.className = 'topic-card-novelty';
      figure.textContent = `${amount(item.amount)} VR$`;
      head.append(title, figure);
      const memo = document.createElement('p');
      memo.className = 'topic-card-subject';
      memo.textContent = item.memo;
      const meta = document.createElement('div');
      meta.className = 'topic-card-meta';
      meta.textContent = item.lines
        .map((line) =>
          Number(line.debit) ? `D ${line.account} ${amount(line.debit)}` : `C ${line.account} ${amount(line.credit)}`,
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
  const typed = /** @type {HTMLInputElement} */ (element('funding-amount')).value.trim();
  const currency = /** @type {HTMLInputElement} */ (element('funding-currency')).value
    .trim()
    .toUpperCase();
  if (!AMOUNT_PATTERN.test(typed)) {
    box.textContent = 'Scrie suma ca să vezi câți VR$ intră în registru.';
    return;
  }
  if (currency === 'USD') {
    box.textContent = `${amount(typed)} USD verificați → ${amount(typed)} VR$ în registru (1 USD = 1 VR$).`;
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
  const vr = (amountToMicros(typed) * amountToMicros(rate) + MICROS / 2n) / MICROS;
  box.textContent = `${amount(typed)} ${currency} × ${amount(rate)} → ${amount(microsToAmount(vr))} VR$ în registru.`;
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
      empty.textContent = 'Nicio finanțare înregistrată.';
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
      title.textContent = isLoan ? 'Împrumut de la Proprietar' : 'Aport de capital';
      const value = document.createElement('span');
      value.className = 'topic-card-novelty';
      value.textContent = `${amount(item.vr)} VR$`;
      head.append(title, value);
      const meta = document.createElement('div');
      meta.className = 'topic-card-meta';
      const parts = [`${amount(item.amount)} ${item.currency}`];
      if (isLoan) {
        parts.push(`${amount((item.annual_rate_bps / 100).toFixed(2))}% pe an`);
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
    fundingStatus('Suma trebuie să fie un număr pozitiv cu cel mult 6 zecimale.', true);
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
      fundingStatus('Dobânda este un procent anual între 0 și 1000, ex: 7 sau 7.25', true);
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
        fundingStatus(`Scrie cursul ${currency} → USD, ex: 1.08`, true);
        return;
      }
      if (!fxSource) {
        fundingStatus('Scrie de unde ai luat cursul; studioul nu inventează niciodată cursuri.', true);
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
      `Înregistrat: ${result.vr} VR$ ${isLoan ? 'ca datorie' : 'în capital'}. ` +
        'Nu s-au mișcat bani reali.',
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
        '<div class="topics-loading">Nicio zi închisă. Închide ziua ca să se numere ce s-a întâmplat.</div>';
      return;
    }
    listEl.innerHTML = logs
      .map(
        (log) => `
        <div class="topic-card story-log-card" data-log-id="${escapeHtml(log.id)}">
          <div class="topic-card-header">
            <strong class="topic-card-title">${escapeHtml(log.business_date)}</strong>
            <span class="topic-card-novelty">${countLabel(log.total_events, 'eveniment', 'evenimente')}</span>
          </div>
          <div class="topic-card-meta">
            <span>${(log.roster || []).length} în distribuție</span>
            · <span>${countLabel((log.notable_events || []).length, 'eveniment de povestit', 'evenimente de povestit')}</span>
          </div>
          <div class="source-actions">
            ${
              (log.notable_events || []).length
                ? `<button class="secondary btn-write-episode" data-log-id="${escapeHtml(log.id)}">Scrie episodul</button>`
                : '<span class="helper-note">O zi liniștită — nu este material pentru un episod.</span>'
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

/**
 * The episodes as script pages, newest open, with the serial's memory above them
 * (serial_room.js). A title map lets a rewrite and a judged plan name the episode they point
 * at instead of printing its id.
 */
async function loadEpisodes() {
  const listEl = element('story-episodes');
  const boardEl = element('story-serial-board');
  try {
    const [data, continuity] = await Promise.all([
      api('/story/episodes'),
      api('/story/continuity').catch(() => null),
    ]);
    boardEl.innerHTML = serialBoardHtml(continuity);
    worldFacts.episodes = data;
    pushWorldFacts();
    const episodes = data.episodes || [];
    if (!episodes.length) {
      listEl.innerHTML = '<div class="topics-loading">Niciun episod încă.</div>';
      return;
    }
    const titles = new Map(episodes.map((episode) => [String(episode.id), String(episode.title || '')]));
    listEl.innerHTML = episodes.map((episode, index) => episodeHtml(episode, { open: index === 0, titles })).join('');
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

// A card on the beat board goes to its beat on the script page, inside the dialog: the anchor
// would leave a fragment in the address bar, and a scripted glide ignores the CSS that zeroes
// motion, so the preference is read here as the section rail reads it.
element('story-episodes').addEventListener('click', (event) => {
  const link = /** @type {HTMLElement} */ (event.target).closest('a.beat-card');
  if (!link) return;
  const target = document.getElementById(String(link.getAttribute('href') || '').slice(1));
  if (!target) return;
  event.preventDefault();
  const still = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  // Only the dialog's body scrolls. `scrollIntoView` also scrolls every ancestor that can be
  // scrolled by script, the dialog itself included: a late beat that cannot come to the top of
  // the body pushed the dialog's own header off and left a blank band under the body.
  const scroller = target.closest('.dialog-body');
  if (scroller) {
    const top = target.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
    scroller.scrollTo({ top: Math.max(0, top - 16), behavior: still ? 'auto' : 'smooth' });
  }
  target.focus({ preventScroll: true });
});

async function writeEpisode(button) {
  const logId = button.getAttribute('data-log-id');
  button.disabled = true;
  storyStatus('Showrunnerul scrie din evenimentele zilei…', false);
  try {
    const result = await api('/story/episodes/write', {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID(), log_id: logId }),
    });
    const episode = result.episode;
    storyStatus(
      `„${episode.title}” — ${countLabel((episode.beats || []).length, 'beat', 'beat-uri')}, ${countLabel((episode.grounded_event_ids || []).length, 'eveniment real citat', 'evenimente reale citate')}.`,
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
        ? `Ancorat: toate cele ${countLabel(report.cited_events, 'eveniment citat', 'evenimente citate')} există în jurnalul din ${report.business_date}.`
        : `NEANCORAT: ${countLabel(report.citations_not_in_the_log.length, 'citare nu este', 'citări nu sunt')} în jurnalul zilei.`,
      !report.grounded,
    );
  } catch (err) {
    storyStatus(err.message, true);
  }
}

async function decideEpisode(button) {
  const id = button.getAttribute('data-id');
  const approve = button.getAttribute('data-approve') === 'true';
  const card = button.closest('.script-episode');
  const notes = /** @type {HTMLInputElement | null} */ (card?.querySelector('.wf-notes'));
  const reason = notes ? notes.value.trim() : '';
  if (!approve && !reason) {
    storyStatus('Scrie de ce respingi episodul; motivul rămâne în istoric.', true);
    return;
  }
  try {
    const decided = await api(`/story/episodes/${id}/decide`, {
      method: 'POST',
      body: JSON.stringify({
        command_id: crypto.randomUUID(),
        approve,
        notes: reason,
      }),
    });
    // His approval builds the storyboard at once (rows, no vendor); the answer says whether it
    // did, and what the next run will do with it (serial_room.js approvalMessage).
    const said = approve ? approvalMessage(decided) : { text: 'Episod respins; motivul a fost înregistrat.', error: false };
    storyStatus(said.text, said.error);
    await loadEpisodes();
    // The status line sits at the dialog's top, a screen above the button he pressed: the same
    // sentence is also written under the episode's own actions, where his eyes are.
    const actions = document.querySelector(`#ep-${CSS.escape(String(id))} .episode-actions`);
    if (actions) {
      const note = document.createElement('p');
      note.className = `decide-result${said.error ? ' is-error' : ''}`;
      note.setAttribute('role', 'status');
      note.textContent = said.text;
      actions.append(note);
    }
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
      `${log.business_date}: ${countLabel(log.total_events, 'eveniment', 'evenimente')}, ${(log.notable_events || []).length} de povestit.`,
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
  preflight: 'Verificare preliminară',
  performance_intake: 'Preluarea performanței',
  idea_generation: 'Generarea de idei',
  research_and_verification: 'Documentare și verificare',
  selection: 'Alegerea subiectului',
  script_and_storyboard: 'Scenariu și storyboard',
  media: 'Producție media',
  edit_and_qc: 'Montaj și controlul calității',
  publish: 'Publicare',
  post_run: 'Raportare și închiderea zilei',
  daily_log: 'Jurnalul zilei',
  serial_queue: 'Episodul din serial',
  serial_next: 'Scenariul de mâine',
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
    // The first check that stops or empties the day, above the list: on the rehearsal's copy
    // «Studioul poate rula» stood above the one line that foresaw the day losing its film, and
    // it was the ninth of nineteen. The words are the check's own message.
    const stop = firstStop(data);
    const stopLine = stop
      ? `<div class="runbook-first-stop ${stop.blocking ? 'rb-blocking' : 'rb-degrading'}">
          <span class="runbook-label">${stop.blocking ? 'Primul punct blocant' : 'Ziua nu ajunge întreagă'}</span>
          <strong>${escapeHtml(stop.label)}</strong>
          ${stop.message ? `<span>${escapeHtml(stop.message)}</span>` : ''}
        </div>`
      : '';
    checksEl.innerHTML = stopLine + (data.checks || [])
      .map(
        (check) => `
        <div class="${escapeHtml(checkClassName(check))}${stop && check.name === stop.name ? ' rb-first-stop' : ''}">
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
        ? 'Verificare preliminară blocantă: rezolvă punctele blocante înainte de a porni rularea.'
        : 'Rulează etapele zilei și înregistrează ce a făcut fiecare.';
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

/** The serial's facts and the days closed before the run, under a stage's own reason. */
function stageNotesHtml(stage) {
  const notes = [daysClosedNote(stage), ...serialStageNotes(stage)].filter(Boolean);
  return notes.length
    ? `<span class="runbook-stage-notes">${notes.map((note) => `<span class="runbook-stage-note">${escapeHtml(note)}</span>`).join('')}</span>`
    : '';
}

function renderRunCard(run) {
  const stages = run.stages || [];
  // What the day made, not only how far it got: the backend's sentence under the header and,
  // per stage, its count. A COMPLETED day that produced nothing loses its green (`rb-empty`).
  const headline = runHeadline(run);
  return `
    <div class="${escapeHtml(runClassName(run))}">
      <div class="topic-card-header">
        <strong class="topic-card-title">${escapeHtml(run.business_date || '')}</strong>
        <span class="topic-card-novelty">${escapeHtml(run.status)}</span>
      </div>
      <div class="topic-card-meta">
        <span>${run.stages_completed}/${run.stages_total} etape încheiate</span>
        · <span>verificare preliminară ${escapeHtml(run.preflight_status || '—')}</span>
        ${run.stopped_at_stage ? ` · <span>oprită la «${escapeHtml(stageLabel(run.stopped_at_stage))}»</span>` : ''}
      </div>
      ${headline.text ? `<div class="runbook-run-summary${headline.empty ? ' rb-empty' : ''}">${escapeHtml(headline.text)}</div>` : ''}
      ${run.stop_reason ? `<div class="claim-notes">${escapeHtml(run.stop_reason)}</div>` : ''}
      <div class="runbook-stages">
        ${stages
          .map(
            (stage) => `
          <div class="${escapeHtml(stageClassName(stage))}">
            <span class="runbook-stage-name">${escapeHtml(stageLabel(stage.stage))}</span>
            <span class="runbook-stage-status">${escapeHtml(stage.status)}${stageProducedWord(stage) ? `<span class="runbook-stage-produced">${escapeHtml(stageProducedWord(stage))}</span>` : ''}</span>
            <span class="runbook-stage-reason">${escapeHtml(stage.reason || '')}${stageNotesHtml(stage)}</span>
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
            <strong class="topic-card-title">Rularea de azi</strong>
            <span class="topic-card-novelty">ÎN CURS</span>
          </div>
          <div class="topic-card-meta">În coadă de la ${escapeHtml(timelineTime(data.pending.created_at))}</div>
          <div class="claim-notes">Etapele apar în registrul din stânga pe măsură ce se întâmplă.</div>
        </div>`
      : '';
    listEl.innerHTML = pending + (runs.length ? runs.map(renderRunCard).join('') : (pending ? '' : '<div class="topics-loading">Nicio rulare încă.</div>'));
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
    if (Array.isArray(jobs)) {
      worldFacts.jobs = jobs;
      renderStudioReadout();
    }
    const daily = (jobs || []).find((job) => job.workflow_type === 'DAILY_RUN');
    if (!daily) {
      box.innerHTML = `<p class="runbook-note">Nicio treabă zilnică programată. Lucrătorul de fundal o creează la pornire, când este activ.</p>`;
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
        ${stopped ? `<p class="runbook-note">Autonomia este oprită: treaba nu va porni nimic până nu o repornești.</p>` : ''}
        ${daily.is_active ? '' : `<p class="runbook-note">Programarea este oprită: studioul nu pornește nicio zi de la sine. Pornirea este decizia ta și rămâne în istoric.</p>`}
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

// The long reports carry a section rail. It marks what he is reading as he scrolls;
// the links repeat the headings already on the page and change nothing else. Research is
// the longest body in the product — 6284px against the daily run's 2197 — so it carries
// one too; it had none because the specification only named the other three.
attachRail(runbookModal.querySelector('.dialog-body'));
attachRail(treasuryModal.querySelector('.dialog-body'));
attachRail(researchModal.querySelector('.dialog-body'));

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
      COLD_START: 'start la rece — nimic măsurat încă',
      EARLY_DATA: 'primele date',
      MATURE: 'date suficiente',
    }[state.maturity] || state.maturity;
    const channels = (state.channels || [])
      .map((channel) => {
        const change =
          typeof channel.views_change_percentage === 'number'
            ? `${channel.views_change_percentage > 0 ? '+' : ''}${channel.views_change_percentage}% față de săptămâna trecută`
            : 'nicio comparație încă';
        const views =
          typeof channel.views_last_7_days === 'number'
            ? `${channel.views_last_7_days} vizualizări în 7 zile`
            : 'nimic măsurat în 7 zile';
        return `<div class="runbook-check ${channel.measured ? 'rb-ok' : ''}">
          <strong>${escapeHtml(channel.channel_name)}</strong>
          <div>${channel.published} publicate · ${channel.measured} măsurate</div>
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
        <strong>${state.autonomy_stopped ? 'Autonomia este oprită' : 'Autonomia este pornită'}</strong>
        <div>Mediu: ${escapeHtml(state.environment)} · ${escapeHtml(maturity)}</div>
      </div>
      ${channels}
      <div class="runbook-check runbook-flux">
        <strong>Flux</strong>
        ${pipelineSvg(pipe.stages, { bottleneck: pipe.bottleneck })}
        <div>${pipe.in_flight || 0} în lucru${
          pipe.bottleneck
            ? ` · <span class="text-error">blocaj la ${escapeHtml(pipe.bottleneck.stage)}: ${pipe.bottleneck.waiting} în așteptare</span>`
            : ''
        }</div>
      </div>
      <div class="runbook-check">
        <strong>Angajați</strong>
        <div>${state.agents?.active || 0} activi · ${(state.agents?.idle || []).length} fără rulări ·
          ${state.agents?.queue_backlog || 0} în coadă · ${state.agents?.dead_letter_tasks || 0} sarcini abandonate</div>
      </div>
      ${growth ? `<div class="runbook-check"><strong>Ce limitează creșterea</strong>${growth}</div>` : ''}
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
          <div><strong>De făcut:</strong> ${escapeHtml(row.action)}${row.owner_role ? ` — ${escapeHtml(row.owner_role)}` : ''}</div>
          ${row.review_after_videos ? `<div class="motion-reason">Revizuire după ${row.review_after_videos} filme.</div>` : ''}
          ${row.outcome ? `<div class="motion-reason">Rezultat: ${escapeHtml(row.outcome)}</div>` : ''}
        </div>`,
          )
          .join('')
      : '<div class="topics-loading">Nicio decizie strategică încă.</div>';
  } catch (err) {
    box.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
  }
}

const directCompanyBtn = /** @type {HTMLButtonElement} */ (element('direct-company-btn'));
if (directCompanyBtn) {
  directCompanyBtn.addEventListener('click', async () => {
    directCompanyBtn.disabled = true;
    runbookStatus('Directorul citește starea companiei…', false);
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
  runbookStatus('Se pornește rularea de azi…', false);
  try {
    const started = await api('/runbook/runs', {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID() }),
    });
    runbookStatus(started.message || 'Rularea de azi a pornit.', false);
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
  runbookStatus('Se dă analiza săptămânală Directorului…', false);
  try {
    const started = await api('/runbook/weekly-review', {
      method: 'POST',
      body: JSON.stringify({ command_id: crypto.randomUUID() }),
    });
    runbookStatus(started.message || 'Analiza săptămânală a pornit.', false);
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
