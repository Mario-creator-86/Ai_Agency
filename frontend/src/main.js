import { newestFirst, replaceActivityHtml } from './activity_lists.js';
import { amount } from './numbers.js';
import { loadAgentDetails } from './agent_details.js';
import { icon } from './icons.js';
import { escapeHtml } from './html.js';
import {
  approvalCaveat,
  checklistHtml,
  preflightChecklist,
  scheduleNextRun,
  SCHEDULE_TITLE,
} from './readiness.js';
import { runClassName, runHeadline, stageClassName, stageProducedWord } from './day_outcome.js';
import { attachRail } from './dialog_rail.js';
import './style.css';
import './office_scene.css';
import './serial_room.css';
import './owner_decisions.css';
import { approvalMessage, daysClosedNote, episodeHtml, journalCoverHtml, serialBoardHtml, serialStageNotes } from './serial_room.js';
import { initSettings } from './settings.js';
import { mountGpuSwitch } from './gpu_switch.js';
import { acceptSnapshot } from './projection.js';
import { OfficeEngine, PixelTitle, BUILDING, WORLD_W, WORLD_H } from './pixel_office.js';
import './pixel_studio.css';
import { autonomyOverview } from './autonomy_overview.js';
import { Drawers } from './drawers.js';
import { OfficeState } from './office_state.js';
import { Ledger, entryCountLabel, mailIntentLabel, productionStatus, runtimeLabel, taskLabel } from './ledger.js';
import { streetMoves } from './hq_events.js';
import { budgetRing, budgetRingSvg, channelFilmsHtml, dayTrack, dayTrackFromRun, dayTrackGeometry, dayTrackWords, newerTrack, pipelineSvg } from './hud_charts.js';
import { Moments } from './moments.js';
import { copyCanvas, filmPoster, PosterCache, POSTER_SAMPLES } from './film_poster.js';
import { WALL, latestFilm, boardTopics } from './hq_screens.js';
import { REPLAY_ACTION, agentReadout, canvasLabel, lastTasks, lastTaskLine, newerTasks, nextRunSign, SURFACES, surfaceReadout, tasksFromRecord } from './hq_readouts.js';
import { interruptsReplay } from './day_replay.js';
import { DayReplayPlayer } from './replay_player.js';
import { INVITE_RELAYOUT_MS, ReplayInvite, invitePlacement, inviteWords, restingNow } from './replay_invite.js';
import { SceneReadout } from './scene_readout.js';
import { studioReadout } from './side_readout.js';
import { friendlyAnswer } from './friendly_text.js';
import {
  accountTypeWord, budgetStateWord, channelTypeWord, confidenceWord, consistencyWord, constraintWord, decisionStateWord,
  accountLine, decisionWord, frameSize, isoDay, providerName, letterStateWord, lifecycleWord, lifecycleActs, matterWords, moneyTagWord, ownerName, pipelineStageWord,
  preflightWord, publicationStatus, qcWord, runStatusWord, seconds, shotWords, storyboardStatus, storyboardTone, topicStatus, workWord,
  deskPlace, sharedTail, hostFailureWords, promptFirstSentence, voiceWords,
} from './dialog_words.js';
import {
  PRICES_MEANING, PRICE_BOTH, channelFacts, checkNewModel, knownModels, priceAnswer, priceCommands, priceInput, providerMark, providerWideRows,
  paidMediaFormHtml, savePaidMediaRule, tokenPriceRows, usdWords,
  RESOLVABLE_STATES, demoCaseShown, gateChecksHtml, privacyBadgeHtml, privacyWord, quickPublishQuestion, resolvePublicationCommand,
} from './owner_controls.js';
import {
  ASSEMBLE_STEP, SHEET_TITLE, approveAssemble, approveRedo, approveStep, buyingNotice, redoKey, requestRender, sceneModelPath, sheetHtml,
  sheetKeyFor, sheetPath, sheetStatusText, takeDecisionPath, withdrawnWords,
} from './shooting_sheet.js';
import { bannersKey, pageBanners } from './build_banner.js';
import { apiErrorMessage, fetchFailure } from './api_errors.js';
import { MediaCache, ObjectUrls, PICTURE_CAPACITY } from './media_cache.js';
import { countWords } from './plurals.js';
import { CANCEL_QUESTION, QUEUE_PATH, queueHtml, retryQuestion, stuckWords } from './work_queue.js';
import { RETIRE_QUESTION, budgetCommand, retireCommand } from './budget_form.js';
import { DecisionsWindow } from './decisions_window.js';
import { OWNER_LETTERS_PATH, inboxHtml, lettersWord, ownerMarkWords, readLetters, resolveCommand, resolvePath } from './owner_inbox.js';
import { LiveWindows, eventMatchesAgent } from './live_window.js';
import { MailThread } from './mail_thread.js';
import { authMessage, eventsUrl } from './hq_stream_config.js';
import { EventsLink, connectionLabel, liveScope, roomCaption, roomCaptionShort, sceneReadout } from './live_claims.js';
import { ENTRY, entryPlays, landingPlacement } from './title_frame.js';
import { setStudioPlace } from './office_clock.js';
import { askLocalKey, LocalEntry } from './local_entry.js';
import { STREAM_ROOMS } from './replay_still.js';
import { attachDoor, doorLanded, doorNeedsRead, doorTiming, doorWorldRect, revealInSteps, roomOnScreen } from './dialog_doors.js';
import { applyMeters, requesterPerson, rosterCards, rosterHtml, rosterKey } from './roster.js';
import {
  APPROVALS_PATH,
  APPROVAL_DECISION_PATH,
  REFERENCE_CREDIT_WARNING,
  APPROVAL_FOOTNOTE,
  approvalCardHtml,
  approvalCostText,
  approvalDecisionCommand,
  autonomyModeCommand,
  autonomyModeLabel,
  autonomyModeMeaning,
  consequenceWords,
  dayWillWords,
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
 * «Reluarea zilei» (W13, replay_player.js): the newest finished day played back from its record.
 * While it is active the world is the replay's alone; the page's live path keeps its state and
 * gives it back when the replay ends. Assigned once the pieces it needs exist (below).
 * @type {DayReplayPlayer|null}
 */
let replay = null;
const replaying = () => Boolean(replay && replay.active);
/** The invitation to the replay (W15, replay_invite.js); assigned with the player. @type {ReplayInvite|null} */
let replayInvite = null;

/**
 * What the page knows is happening, from which every «live» it prints is decided
 * (live_claims.js): the events socket and the last snapshot read. Legacy stream fields remain
 * inert for the shared freshness helper; this illustrated scene reports no frame rate.
 * @type {import('./live_claims.js').LiveSignals}
 */
const liveSignals = { stream: 'off', hasStill: false, socket: 'closed', data: 'fresh', streamFps: null, pageFps: null, streamHeld: false };
let liveReadoutKey = '';

/** Writes the corner readout, the masthead chip and the slate caption from liveSignals. */
function renderLiveSignals() {
  const words = replay ? replay.words() : null;
  if (words) {
    const key = JSON.stringify(['replay', words.chip, words.caption]);
    if (key === liveReadoutKey) return;
    liveReadoutKey = key;
    const pill = element('office-status');
    pill.dataset.state = 'replay';
    pill.title = words.title;
    pill.setAttribute('aria-hidden', 'false');
    const [word, ...rest] = words.chip.split(' · ');
    const live = document.createElement('span');
    live.className = 'scene-live';
    live.textContent = word;
    const when = document.createElement('span');
    when.className = 'scene-label';
    when.textContent = ` · ${rest.join(' · ')}`;
    element('office-fps').replaceChildren(live, when);
    const long = document.createElement('span');
    long.className = 'room-caption-long';
    long.textContent = words.caption;
    const brief = document.createElement('span');
    brief.className = 'room-caption-short';
    brief.textContent = words.captionShort;
    element('room-caption').replaceChildren(long, brief);
    element('room-caption').title = words.title;
    officeCanvas.setAttribute('aria-label', `Studioul AMN-AI în reluare: ${words.caption}. Săgețile selectează angajații, Enter deschide conversația. Esc iese din reluare.`);
    return;
  }
  const fresh = liveSignals.data === 'fresh';
  const live = fresh && liveSignals.socket === 'open';
  const label = !fresh ? 'Date vechi' : live ? 'Date live' : 'Reconectare';
  const pill = element('office-status');
  pill.dataset.state = !fresh ? 'stale' : live ? 'live' : 'reconnecting';
  pill.setAttribute('aria-hidden', 'false');
  pill.title = 'Decor ilustrat. Stările angajaților vin din studioul conectat.';
  element('office-fps').textContent = label;
  const caption = `${officeState.agents.length} angajați · studio pixelat`;
  element('room-caption').textContent = caption;
  officeCanvas.setAttribute('aria-label', 'Studioul AMN-AI. Săgețile selectează angajații, Enter deschide conversația. ' + label);
  if (ownerToken) element('connection').textContent = label;

}

/** The backend's events, reconnected after a drop; see EventsLink. */
const eventsLink = new EventsLink({
  // the key is always the socket's first message, never its URL (SEC-02)
  url: () => eventsUrl(location),
  firstMessage: () => (ownerToken ? authMessage(ownerToken) : null),
  open: (url) => new WebSocket(url),
  // Everything after the newest event the page holds: the snapshot's cursor, or further on when
  // the register has already read past it.
  afterSequence: () => Math.max(state ? Number(state.cursor) || 0 : 0, ledger.cursor || 0),
  onEvent: (eventData, live) => {
    officeState.handleDomainEvent(eventData, live);
    updateOfficeCanvas();
    if (['agent.hired', 'agent.terminated', 'agent.suspended', 'agent.reactivated'].includes(eventData.event_type)) void loadOfficeLayout();
    // A live arrival says itself from across the room for a few seconds (hq_arrivals.js): the
    // same socket, the same event, nothing fetched; never a replay, never under reduced motion.
    // a live event takes the invitation away: the building is live news now (W15)
    if (live && interruptsReplay(eventData) && replayInvite) replayInvite.liveArrived();
    if (replay && replay.active) {
      if (live && interruptsReplay(eventData)) replay.liveArrived(eventData);
    } else if (officeEngine) {
      officeEngine.offerArrival(eventData, live);
    }
    ledger.add(eventData);
    element('ledger-count').textContent = entryCountLabel(ledger.events.size);
    // DECISIONS_WINDOW: a decision, an approval, a letter or his policy moved: his window reads again
    decisions.onEvent(eventData);
    // A milestone plays only when the socket delivered it as it happened (moments.js).
    const moment = moments.offer(eventData, live);
    if (moment && moment.kind === 'approval') loadApprovals(true).then(() => markArrived());
  },
  onState: (socketState) => {
    liveSignals.socket = socketState;
    renderLiveSignals();
    officeEngine?.draw();
    officeEngine?.schedule();
  },
  // Back after a drop: read the studio again, so the switches and the panels are not the ones
  // from before the gap. The register has its replay already.
  onReconnected: () => { if (ownerToken) { refresh(); void loadOfficeLayout(); } },
});

// 2D Office Engine & State
const officeCanvas = /** @type {HTMLCanvasElement} */ (element('office-canvas'));
/**
 * W28, THE DOORS' READS: what each door reads from the studio when it opens (dialog id → reader),
 * and when it last read. The reader runs on the menu's hover or focus, so the door opens on its
 * content; else once its pane has landed, so no answer is laid out while the pane moves.
 * @type {Map<string, () => void>}
 */
const doorReads = new Map();
/** @type {Map<string, number>} */
const doorReadAt = new Map();
/** How long a door's content counts as just read (ms): a hover and then a click reads once. */
const DOOR_FRESH_MS = 10000;

/** Whether the visitor asked the system for less motion; read at the moment it matters. */
function reducedMotion() {
  return typeof window.matchMedia === 'function' && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * THE LAST LIVE FRAME (W19, stream_keep.js): read from this browser while the title is up, so the
 * starting plate can show it the moment the key enters. Null when none is kept or storage refuses.
 * @returns {Promise<{image: ImageBitmap, at: number}|null>}
 */
const titleScreen = new PixelTitle({ stage: element('title-stage'), caption: element('title-caption') });
titleScreen.start();

const officeState = new OfficeState();
let officeEngine = null;
/** Whether the camera keys, fullscreen and the stream have been wired (once per page). */
let officeWired = false;
/** @type {any} */
/** Legacy replay compatibility; the pixel scene needs no video overlays. @type {any} */
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
  // W30: the letters are laid out once the window has landed, not while it grows
  landed: () => doorLanded(/** @type {HTMLDialogElement} */ (element('mail-modal'))),
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
 * Nothing is fetched per frame. The newest run comes with the day record; the budget and the
 * budget are read once at the key and again only when the register says money moved or a run
 * ended (at most every 15 s); the serial once at the key and when a story event arrives; the
 * newest film's frame once per film. A value the page does not hold stays null, and its screen
 * says «—».
 * ------------------------------------------------------------------------- */
/**
 * `reads` says how each list behind the faces was read (W12): 'pending' until the first answer,
 * 'ok' once it answered, 'failed' when it could not be read (a 404, a timeout) and nothing had
 * been read before. A face says its record is empty only when the record was read and is; a
 * record not read is «—», or «registrul nu a putut fi citit». `film`: 'none' (the record names
 * no film), 'pending', 'ok', or 'failed' (the film is named but its frame could not be read).
 * @typedef {{runs: string, episodes: string, figures: string, ledger: string, film: string}} WorldReads
 */
/** @returns {WorldReads} */
const freshReads = () => ({ runs: 'pending', episodes: 'pending', figures: 'pending', ledger: 'pending', film: 'none' });
/** @type {{run: any, track: any, today: string|null, live: boolean, budget: any, episodes: any, topics: {titles: string[], key: string}, film: any, jobs: any[]|null, tasks: {tasks: Record<string, any>, key: string}, nextRun: string, stopped: boolean|null, timeZone: string|undefined, reads: WorldReads, replayOffer: boolean}} */
const worldFacts = { run: null, track: null, today: null, live: true, budget: null, episodes: null, topics: { titles: [], key: '' }, film: null, jobs: null, tasks: { tasks: {}, key: '' }, nextRun: '', stopped: null, timeZone: undefined, reads: freshReads(), replayOffer: false };

/** A read that failed: 'failed', unless an earlier read of the same list succeeded. @param {keyof WorldReads} list */
function readFailed(list) {
  if (worldFacts.reads[list] !== 'ok') worldFacts.reads[list] = 'failed';
}

/**
 * Each employee's last task: the register's live events and the studio's own record of runs
 * (the snapshot's last_tasks), the newer of the two per employee (W12).
 */
function refreshLastTasks() {
  const tasks = newerTasks(lastTasks(ledger.sorted()), tasksFromRecord(state ? state.last_tasks : null));
  if (tasks.key === worldFacts.tasks.key) return;
  worldFacts.tasks = tasks;
  pushWorldFacts();
  rosterMayChange();
}

function pushWorldFacts() {
  // The façade sign's next run, in the scheduler's own words, only while no run is under way
  // (hq_readouts.js nextRunSign): the same rule the side drawer's foot follows.
  worldFacts.stopped = state && state.policy ? Boolean(state.policy.autonomy_stopped) : null;
  worldFacts.timeZone = state && state.studio ? state.studio.timezone : undefined;
  worldFacts.nextRun = nextRunSign(worldFacts.jobs, { stopped: worldFacts.stopped, timeZone: worldFacts.timeZone });
  // while the day is replayed the world's facts are the record's (replay_player.js); the drawers
  // and the readouts outside the world keep the live ones
  if (officeEngine && !replaying()) officeEngine.setFacts({ ...worldFacts });
  renderStudioReadout();
  renderDayWill();
  refreshSceneReadout();
  considerInvite();
}

/**
 * THE STUDIO'S NUMBERS OVER THE LIVE VIDEO (W19, stream_plaques.js): shown while the live stream is
 * what the visitor sees (not a frozen or kept frame, not the replay), laid where the camera shows
 * their objects, off the employees' desks. From the same facts store; nothing fetched.
 */

/* ---------------------------------------------------------------------------
 * THE FACES MADE LEGIBLE (W10): the glass readout beside the face the pointer or the keyboard
 * stands on, written from the same facts the faces are drawn from (hq_readouts.js).
 * ------------------------------------------------------------------------- */
const faceReadout = new SceneReadout({
  card: element('face-card'),
  announce: element('face-card-announce'),
  host: element('scene-viewport'),
  canvas: element('office-canvas'),
  slate: /** @type {HTMLElement|null} */ (document.querySelector('.scene-viewport .scene-slate')),
  reducedMotion: () => reducedMotion(),
});
/** @type {any} what the engine last said the visitor stands on */
let readoutTarget = null;

function refreshSceneReadout() {
  const target = readoutTarget;
  if (!target) {
    faceReadout.show(null, null);
    return;
  }
  // In the replay the glass says what the replayed world shows, and says that it is the replay's.
  const world = replay ? replay.world() : null;
  const facts = world ? world.facts : worldFacts;
  const agents = world ? world.agents : officeState ? officeState.agents : [];
  const now = world ? world.now : Date.now();
  if (target.kind === 'agent') {
    const agent = agents.find((a) => (a.id || a.agent_id) === target.id) || target.agent;
    const status = String(agent.lifecycle || '').toUpperCase() === 'PAUSED' ? 'PAUSED' : String(agent.runtime_state || 'IDLE');
    const speech = `${world ? 'Reluare: ' : ''}${agent.display_name || agent.role_name || 'Angajat'} · ${runtimeLabel(status)} · ${lastTaskLine(facts.tasks.tasks[target.id], now)}. Enter deschide fișa.`;
    // under the Unreal stream the world's ring is not seen: the glass says who it is (W18)
    faceReadout.show(target, target.covered ? agentReadout(agent, { facts, now }) : null, { speech });
    return;
  }
  let readout = surfaceReadout(target.id, { facts, agents, now });
  if (readout && world) readout = { ...readout, eyebrow: `RELUARE · ${readout.eyebrow}`, key: `replay|${readout.key}` };
  faceReadout.show(target, readout, { poster: facts.film && facts.film.canvas ? facts.film.canvas : null });
}

/**
 * The foot of the side drawer on a tall screen (side_readout.js): the day's run, the budget and
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
    budget: worldFacts.budget,
    jobs: worldFacts.jobs,
    reads: worldFacts.reads,
    stopped: policy ? Boolean(policy.autonomy_stopped) : null,
    timeZone: state && state.studio ? state.studio.timezone : undefined,
    // PAGE-14: «Filmul zilei», from the newest run's stages
    run: worldFacts.run,
  });
  if (readout.key === studioReadoutKey) return;
  studioReadoutKey = readout.key;
  list.innerHTML = readout.rows
    .map((row) => `<div class="readout-row" data-tone="${escapeHtml(row.tone || 'quiet')}"><dt>${escapeHtml(row.label)}</dt><dd><span class="readout-value">${escapeHtml(row.value)}</span>${row.note ? `<span class="readout-note">${escapeHtml(row.note)}</span>` : ''}${row.sheet ? `<button type="button" class="quiet readout-key" data-sheet-open="${escapeHtml(row.sheet)}">Foaia de filmare</button>` : ''}</dd></div>`)
    .join('');
}

let filmAsset = '';

/**
 * Each film's frame is decoded once, whoever shows it (film_poster.js PosterCache): five key
 * frames across the film, read once; the brightest that is a picture is kept (pickBrightest),
 * at twice the render bay's pixels (180x320). The render bay and the film toast show the same
 * frame (W12; the toast used to take the single early one).
 */
const posters = new PosterCache((assetId) => filmPoster({ url: `/api/v1/media/assets/${encodeURIComponent(assetId)}/stream`, token: ownerToken, width: 90, height: 160, scale: 2, samples: POSTER_SAMPLES, timeoutMs: 8000 }));

/*
 * «RELUAREA ZILEI» (W13): the player, with what it needs from the page. The record is read once
 * when a replay starts; the film's frame is the render bay's own decode (PosterCache).
 */
replay = new DayReplayPlayer({
  api: (path) => api(path),
  engine: () => officeEngine,
  agents: () => officeState.agents,
  known: () => ledger.sorted(),
  cursor: () => Math.max(state ? Number(state.cursor) || 0 : 0, ledger.cursor || 0),
  timeZone: () => (state && state.studio ? state.studio.timezone : undefined),
  today: () => worldFacts.today,
  reduced: () => reducedMotion(),
  names: () => Object.fromEntries(officeState.agents.map((a) => [a.id || a.agent_id, a.display_name || a.role_name || ''])),
  poster: (assetId) => posters.get(assetId),
  onEnter: () => {
    // the live picture fades into the replay (W19); a cut under reduced motion
    // W22: while a stream is configured, the replay plays over the real building's still, the frame
    // the door just copied (else the frozen or kept one), graded; without one, the page's renderer
    enterReplayLook();
    renderLiveSignals();
    refreshSceneReadout();
    scheduleDayTrack();
  },
  onExit: (liveEvents) => {
    // and back: the live video fades in over the replay's last graded frame (W19)
    leaveReplayLook();
    // the world is the live one again, and a live arrival that ended the replay is still seen
    updateOfficeCanvas();
    pushWorldFacts();
    renderLiveSignals();
    scheduleDayTrack();
    if (officeEngine) for (const event of liveEvents) officeEngine.offerArrival(event, true);
  },
  onChange: () => {
    renderLiveSignals();
    scheduleDayTrack();
    if (readoutTarget) refreshSceneReadout();
    // W22: over the Unreal still, the plaques carry the replayed moment's words
  },
  lookNote: () => replayLookNote,
  onOffer: (offered) => {
    if (worldFacts.replayOffer === offered) return;
    worldFacts.replayOffer = offered;
    pushWorldFacts();
  },
});

/** The replay's weather line as the page wrote it (index.html), restored when the replay ends. */
const REPLAY_WEATHER_WORDS = element('replay-weather').textContent || '';
/** W22: said once when the replay starts over the Unreal still (replay_still.js stillSentence). */
let replayLookNote = '';

/**
 * W22, THE REPLAY IN THE UNREAL BUILDING (replay_still.js): with a stream configured and a real
 * picture of the building in hand, the engine plays the replay over it; the line under ATUNCI says
 * what the picture is and that its light and weather are not those of then.
 */
function enterReplayLook() {
  element('scene-viewport').dataset.replayLook = 'pixel';
  replayLookNote = 'Decor ilustrat; activitatea reluată vine din registru.';
}

function leaveReplayLook() {
  delete element('scene-viewport').dataset.replayLook;
  element('replay-weather').textContent = REPLAY_WEATHER_WORDS;
  replayLookNote = '';
}

/*
 * THE REPLAY OFFERED (W15, replay_invite.js): once per browser session, after the entry has
 * settled, while the studio rests by its own record, an invitation under the building offers the
 * last working day. It is asked again whenever the facts or the people change; nothing is fetched.
 */
replayInvite = new ReplayInvite({
  card: element('replay-invite'),
  lead: element('replay-invite-lead'),
  line: element('replay-invite-line'),
  go: /** @type {HTMLButtonElement} */ (element('replay-invite-go')),
  later: /** @type {HTMLButtonElement} */ (element('replay-invite-later')),
  say: (text) => { element('replay-announce').textContent = text; },
  reduced: () => reducedMotion(),
  place: (card) => placeInvite(card),
  storage: () => window.sessionStorage,
  // a keyboard visitor returns to the dock's key when the replay ends, as if it had been pressed;
  // a pointer visitor's focus is left where it is (W17)
  onGo: (keyboard) => { if (replay) replay.start(/** @type {HTMLElement} */ (element('replay-toggle')), { keyboard }); },
  recheck: () => considerInvite(),
});

let inviteRelayoutTimer = 0;
/** The camera moved: the invitation is placed again once it has rested for a moment. */
function relayoutInviteSoon() {
  window.clearTimeout(inviteRelayoutTimer);
  inviteRelayoutTimer = window.setTimeout(() => {
    inviteRelayoutTimer = 0;
    if (replayInvite) replayInvite.relayout();
  }, INVITE_RELAYOUT_MS);
}

/** @param {{w: number, h: number}} card */
function placeInvite(card) {
  if (!officeEngine || !officeEngine.renderer) return null;
  const box = officeEngine.frameBox();
  const slate = /** @type {HTMLElement|null} */ (document.querySelector('.scene-viewport .scene-slate'));
  const room = { ...box.room, bottom: box.room.bottom - (slate ? slate.offsetHeight : 0) };
  return invitePlacement({ room, building: box.building, card });
}

function considerInvite() {
  if (!replay || !replayInvite) return;
  const run = replay.run;
  const known = worldFacts.reads.runs === 'ok' && worldFacts.reads.ledger === 'ok';
  replayInvite.consider({
    resting: Boolean(ownerToken) && !workspace.hidden && known && restingNow({ run, live: worldFacts.live, agents: officeState.agents }),
    replaying: replaying() || replay.loading,
    words: inviteWords(run, { timeZone: worldFacts.timeZone }),
  });
}

function resetWorldFacts() {
  Object.assign(worldFacts, { run: null, track: null, today: null, live: true, budget: null, episodes: null, topics: { titles: [], key: '' }, film: null, jobs: null, tasks: { tasks: {}, key: '' }, nextRun: '', reads: freshReads() });
  filmAsset = '';
  posters.clear();
  pushWorldFacts();
}

/**
 * The newest rendered film's own frame, decoded once per film from the file (film_poster.js),
 * with the Owner's key, the way the film toast decodes it.
 * @param {{assetId: string, date: string|null}|null} film
 */
async function loadFilmFrame(film) {
  if (!film) {
    // the record was read and names no film
    if (worldFacts.reads.film !== 'ok') worldFacts.reads.film = 'none';
    return;
  }
  if (!ownerToken || film.assetId === filmAsset) return;
  filmAsset = film.assetId;
  const session = epoch;
  if (!worldFacts.film) {
    worldFacts.reads.film = 'pending';
    pushWorldFacts();
  }
  const canvas = await posters.get(film.assetId);
  if (session !== epoch || filmAsset !== film.assetId) return;
  worldFacts.film = canvas ? { ...film, canvas } : null;
  worldFacts.reads.film = canvas ? 'ok' : 'failed';
  // a frame that could not be read is asked again with the next record, not remembered as none
  if (!canvas) filmAsset = '';
  pushWorldFacts();
}

let figuresTimer = 0;
async function loadWorldFigures() {
  if (!ownerToken) return;
  const session = epoch;
  const [budget, jobs] = await Promise.all([api('/economy/budget').catch(() => null), api('/scheduler/jobs').catch(() => null)]);
  if (session !== epoch) return;
  // A failed read keeps the last figures read; the corner already says the data is not fresh.
  if (budget) worldFacts.budget = budget;
  if (Array.isArray(jobs)) worldFacts.jobs = jobs;
  if (budget) worldFacts.reads.figures = 'ok';
  else readFailed('figures');
  pushWorldFacts();
}

let serialTimer = 0;
async function loadSerialFacts() {
  if (!ownerToken) return;
  const session = epoch;
  const episodes = await api('/story/episodes').catch(() => null);
  if (session !== epoch) return;
  if (!episodes) {
    readFailed('episodes');
    pushWorldFacts();
    return;
  }
  worldFacts.episodes = episodes;
  worldFacts.reads.episodes = 'ok';
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
  // Each employee's last real task, for the faint line under a name and the desk's readout.
  if (types.some((t) => t === 'agent.run_completed' || t === 'agent.state_changed')) refreshLastTasks();
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
    // the newest finished day is what «Reluarea zilei» plays; with none, it is not offered
    if (replay) replay.setRuns(data.runs);
    worldFacts.run = newest || null;
    worldFacts.reads.runs = 'ok';
    pushWorldFacts();
    loadFilmFrame(latestFilm(data.runs));
    // «Acum» reads the same record: a stage that started before the day's recorded finish is
    // not running, even when the register has lost the finish behind newer rows.
    const closed = newest ? Date.parse(String(newest.finished_at || '')) : NaN;
    ledger.closedAt = Number.isFinite(closed) ? closed : null;
  } catch {
    // Not read is not empty (W12): a 404 or a timeout is «—» or «registrul nu a putut fi
    // citit» on the faces, never «nicio rulare în registru».
    if (worldFacts.reads.runs !== 'ok') dayRecord = null;
    readFailed('runs');
    pushWorldFacts();
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
  // W14: the slate lies inside the replay's letterbox, beside «reluarea rulării din …»: while the
  // day is replayed it shows the replayed run as the record stood then, as the façade sign does
  // (it said 12/12 under a sign at 5/12). Nothing live is lost: a live runbook event ends the
  // replay (day_replay.js interruptsReplay). The live facts above are kept as they are.
  const frame = replaying() && replay ? replay.frame : null;
  const shown = frame ? frame.track : track;
  const words = dayTrackWords(shown, { today: studioToday(), live: frame ? true : live });
  const geometry = dayTrackGeometry(shown);
  const key = JSON.stringify([words.label, geometry.rects.map((r) => r.state)]);
  if (key === dayTrackKey) return;
  dayTrackKey = key;
  dayTrackBox.setAttribute('aria-label', words.sentence);
  dayTrackBox.dataset.state = shown.empty ? 'empty' : shown.finished ? 'finished' : 'running';
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
    // The brightest real frame of the film, the render bay's own (PosterCache: one read of the
    // file for both). The film just rendered is now the newest, so the bay takes it too.
    const canvas = await posters.get(moment.assetId);
    if (canvas) loadFilmFrame({ assetId: moment.assetId, date: studioToday() });
    return canvas ? copyCanvas(canvas) : null;
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
/** The requests last counted, and the open letters to him (PAGE-07, owner_inbox.js). */
let pendingRequests = 0;
let openLetters = 0;
/** @param {number} [pending] how many requests the approvals route lists as waiting; kept when omitted */
function renderOwnerMark(pending) {
  if (pending !== undefined) pendingRequests = pending;
  const waiting = pendingRequests + openLetters;
  ownerMark.hidden = !(waiting > 0);
  // «1 cerere așteaptă decizia ta», «1 cerere și 13 scrisori te așteaptă» (owner_inbox.js); the
  // older waitingWords stays the words for requests alone
  element('owner-mark-text').textContent = !waiting ? '' : openLetters ? ownerMarkWords(pendingRequests, openLetters) : waitingWords(pendingRequests);
  drawers.setPending(waiting);
  ownerMark.title = !waiting ? '' : pendingRequests ? 'Du-mă la cererile de aprobare' : 'Du-mă la scrisorile pentru tine';
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
  // DECISIONS_WINDOW: what waits for him (the requests, the letters, the recommendations) is
  // answered in his own window; the approvals and the letters stay listed in the drawer too.
  void decisions.open('waiting');
});

function notify(message) {
  element('message').textContent = message;
  element('message').hidden = !message;
}

async function api(path, options = {}) {
  // A caller that knows its request runs long says so (a paid step of the shooting sheet buys
  // every still or clip before it answers); a timeout here would not stop the server's work.
  const timeoutMs = Number(/** @type {any} */ (options).timeoutMs) || 0;
  let response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      headers: {
        Authorization: `Bearer ${ownerToken}`,
        'Content-Type': 'application/json',
      },
      signal: AbortSignal.timeout(
        timeoutMs || (path.startsWith('/settings') || path.startsWith('/providers') ? 45000 : 10000),
      ),
      cache: 'no-store',
    });
  } catch (failure) {
    // PAGE-06: marked, so a paid press whose answer never arrived says the purchase may still
    // be running on the server (shooting_sheet.js NETWORK_STEP_WORDS), never that it was refused.
    // PAGE-11: a request that took too long has its own sentence (api_errors.js).
    throw fetchFailure(failure);
  }
  if (!response.ok) {
    // Prefer what the server said. Every refusal this backend writes is a sentence meant for
    // the Owner — which host is not authorised, why a provider did not answer, what is missing
    // before a publication can proceed — and replacing it with "try again" would throw away
    // exactly the part that tells them what to do. PAGE-11: what is said when it wrote none,
    // or wrote a list (422) or the catch-all 500, is decided in api_errors.js.
    const body = await response.json().catch(() => ({}));
    const message = apiErrorMessage(response.status, body);
    const error = new Error(message);
    Object.assign(error, { status: response.status, detail: body.detail });
    throw error;
  }
  return response.json();
}

// A model assignment or a provider check changes what the office should be showing, so the
// layout is reloaded whenever Settings changes something.
/** W34: the module list the server reports, shown in Setări → Despre studio (not on the main screen). */
let latestModules = /** @type {Record<string, string>|null} */ (null);
mountGpuSwitch(element('gpu-switch'), { api, notify });
const settingsUI = initSettings(api, {
  onChange: async () => {
    await loadOfficeLayout();
    if (inspector.open && currentSelectedAgent) await showInspector(currentSelectedAgent);
  },
  onAutonomy: () => element('open-autonomy-btn').click(),
  modules: () => latestModules,
});
document.getElementById('studio-about-btn')?.addEventListener('click', () => { void settingsUI.open('about'); });

/**
 * DECISIONS_WINDOW (2026-10-03): «Decizii», the Owner's own window (decisions_window.js). The key
 * in the top bar counts what waits for him; the window answers each card through the route it
 * names. A guided card opens its Settings place; a letter its thread; his answer reloads the
 * approvals, the letters and the snapshot, so the rest of the page says the same.
 */
const decisions = new DecisionsWindow({
  api,
  button: /** @type {HTMLButtonElement} */ (element('decisions-button')),
  badge: element('decisions-badge'),
  openSettings: (tab) => { void settingsUI.open(tab); },
  openThread: (threadId) => { void mailThread.open(threadId); },
  threadOf: (letterId) => {
    const letter = lettersShown.find((l) => l.id === letterId);
    return letter ? letter.thread_id : null;
  },
  timezone: () => (state && state.studio ? state.studio.timezone : undefined),
  onAnswered: async () => {
    await loadApprovals(true);
    await loadOwnerLetters(true);
    await refresh();
  },
  // a backend older than the window (404): the requests and the letters the page already counts
  fallbackCount: () => pendingRequests + openLetters,
});

/**
 * The Unreal headquarters, streamed over the page's own renderer while it runs. The viewport's
 * data-stream attribute says which one the Owner is looking at.
 */
const drawers = new Drawers({
  onInsets: (insets, options) => {
    if (officeEngine) officeEngine.setInsets(insets, options);
    // the invitation keeps its place under the building once the camera has settled
    if (replayInvite && replayInvite.shown) window.setTimeout(() => { if (replayInvite) replayInvite.relayout(); }, options && options.glide ? 460 : 0);
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
    infoElement: element('scene-info'),
    fetchWeather: () => api('/office/weather', { timeoutMs: 12000 }),
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
    // W21: the window's resize event can come a frame after the box changed; the drawers are laid
    // out for the new size before the camera is planned for it
    beforePlan: () => drawers.syncToWindow(),
    // W22: a replay over the Unreal still composes no plates for the replayed hour
    // W22: a replayed caption over the still takes its room; a plaque in its way steps aside
    // The streamed picture follows the page's camera, so zoom and pan act on what is seen.
    onView: (view) => {
      // the visitor's zoom and drag move the building: the invitation follows it once the camera
      // rests, or steps aside when the zoomed building leaves no free room under it (W18)
      if (replayInvite && replayInvite.shown) relayoutInviteSoon();
    },
    onSelectAgent: (agent) => {
      currentSelectedAgent = agent;
      if (agent) {
        showInspector(agent);
      } else {
        inspector.close();
      }
    },
    // A face opens its room: the same dialog the masthead's menu opens.
    onSelectSurface: (id, room) => {
      // the idle façade offers the last working day (W13): its card says so, and its click plays it
      if (id === 'run_sign' && replay && !replay.active) {
        const card = surfaceReadout('run_sign', { facts: worldFacts, agents: officeState.agents });
        if (card && card.action === REPLAY_ACTION) {
          replay.start(officeCanvas, { keyboard: officeEngine.surfaceVia === 'keyboard' });
          return;
        }
      }
      const opener = room ? document.getElementById(room) : null;
      if (opener) opener.click();
    },
    onReadout: (target) => {
      readoutTarget = target;
      // W28: a face of the building under the pointer or the keyboard reads its door ahead
      if (target && target.kind === 'surface') {
        const face = SURFACES.find((f) => f.id === target.id);
        const door = face ? DOOR_KEYS[/** @type {keyof typeof DOOR_KEYS} */ (face.room)] : undefined;
        if (door) readDoorAhead(door);
      }
      refreshSceneReadout();
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
function whenIdle(/** @type {() => void} */ run) {
  const idle = /** @type {any} */ (window).requestIdleCallback;
  if (typeof idle === 'function') idle(run, { timeout: 1500 });
  else window.setTimeout(run, 200);
}
/**
 * W23: the codecs' first enumeration (hq_stream_config.js warmVideoCodecs), about one second on a
 * first visit, spent while the title stands idle instead of in the middle of the entry; only when
 * the stream is configured and no key has been given yet.
 */
window.addEventListener('load', () => whenIdle(() => { warmOffice().catch(() => {}); }), { once: true });

function initOffice() {
  buildOfficeEngine();
  drawers.layout({ glide: false });
  officeEngine.unpark();
  if (!officeWired) {
    officeWired = true;

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

let officeLastRead = 0;
async function loadOfficeLayout({ characters = true } = {}) {
  const session = epoch;
  try {
    const layout = await api('/office/layout');
    if (session !== epoch || !ownerToken) return;
    officeState.initFromLayout(layout);
    officeLastRead = Date.now();
    // a request's asker becomes a person of the building once the office is known (W30)
    if (approvalsShown.length) renderApprovals();
    if (officeEngine) {
      officeEngine.setLayout(layout);
      updateOfficeCanvas();
      if (characters) await loadOfficeCharacterBible();
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
 * The scene projects backend state; this handle lets browser checks inspect positions
 * and selection without writing production data. Read-only inspection handle; nothing in the app reads it.
 */
function publishSceneHandle() {
  /** @type {any} */ (window).__studio = {
    engine: officeEngine,
    state: officeState,
    replay,
  };
}

function updateOfficeCanvas() {
  if (readoutTarget) refreshSceneReadout();
  if (!officeEngine) return;
  officeState.cleanupExpiredBubbles();
  // while the day is replayed the world is the record's; the live state is given back at the end
  if (replaying()) return;
  considerInvite();
  officeEngine.setAgents(officeState.agents);
  syncInspectorState();
  rosterMayChange();
  officeEngine.setSpeechBubbles(officeState.speechBubbles);
  officeEngine.setProjectTokens(officeState.projectTokens);
}

async function connectWebSocket() {
  if (!ownerToken) return;
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
  // W30: a fresh opening shows no one else's contract or history while it grows: the heavy parts
  // wait, empty, and are laid out once the pane has landed (below)
  if (!inspector.open) clearInspectorBody();
  renderInspector({...agent,model_loading:true,model_is_available:false});
  try {
    const details=await loadAgentDetails(api,id);
    if(request!==inspectorRequest||session!==epoch||!inspector.open) return;
    officeState.setAgents([details]);
    currentSelectedAgent={...agent,...details,model_loading:false,model_error:null};
    renderInspector(currentSelectedAgent);
    syncInspectorState();
  } catch(error) {
    if(request!==inspectorRequest||session!==epoch||!inspector.open) return;
    renderInspector({...agent,model_error:error instanceof Error?error.message:'Detaliile modelului nu au putut fi încărcate.',model_is_available:false});
  }
  try {
    const identity = await api(`/agents/${encodeURIComponent(id)}/identity`);
    await doorLanded(inspector);
    if(request!==inspectorRequest||session!==epoch||!inspector.open) return;
    // the contract, the memory and the history come in over a few frames, not in one
    revealInSteps(INSPECTOR_HEAVY.map((part) => element(part)));
    renderIdentity(identity);
    await loadAgentHistory(id);
  } catch(error) {
    if(request!==inspectorRequest||session!==epoch||!inspector.open) return;
    element('inspector-mission').textContent = error instanceof Error ? error.message : 'Identitatea nu a putut fi încărcată.';
  }
}

/** W30: the inspector's heavy parts: laid out after the pane has landed, one per frame. */
const INSPECTOR_HEAVY = ['inspector-identity', 'inspector-memory-section', 'inspector-chat-section'];

/** The inspector's heavy parts, emptied to their loading words (a new opening). */
function clearInspectorBody() {
  // W32: a fresh opening paints the portrait again (the stream's frame may be newer)
  delete element('inspector-copy-id').dataset.agent;
  element('inspector-mission').textContent = 'Se încarcă identitatea…';
  element('inspector-contract').replaceChildren();
  element('inspector-system-prompt').textContent = '';
  element('inspector-memory').replaceChildren();
  element('inspector-messages').replaceChildren();
  const history = element('agent-history');
  const loading = document.createElement('div');
  loading.className = 'helper';
  loading.textContent = 'Se încarcă istoricul…';
  history.replaceChildren(loading);
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
    const meta = [item.model, item.memory_used ? `${item.memory_used} amintiri folosite` : '']
      .filter(Boolean).join(' · ');
    const summarised = Boolean(item.prompt) && item.prompt !== item.asked;
    const line = isChat || summarised ? item.asked || '' : '';
    const full = item.prompt || item.asked || '';
    const prompt = !isChat && full
      ? `<details class="chat-prompt"><summary>Cererea completă</summary><pre>${escapeHtml(full)}</pre></details>`
      : '';
    return `<div data-card-key="${escapeHtml(item.id)}" class="chat-item chat-run${isChat ? ' is-chat' : ''}"><div class="chat-meta"><span class="policy-tag policy-flexible">${escapeHtml(label)}</span> <small>${escapeHtml(timelineTime(item.at))}${meta ? ` · ${escapeHtml(meta)}` : ''}</small></div>${line ? `<div class="chat-asked">${escapeHtml(line)}</div>` : ''}${answer}${prompt}</div>`;
  }
  if (item.kind === 'message') {
    const direction = item.from_name ? `de la ${ownerName(item.from_name)}` : '';
    const to = item.to_name ? `către ${ownerName(item.to_name)}` : '';
    return `<div data-card-key="${escapeHtml(item.id)}" class="chat-item chat-message"><div class="chat-meta"><span class="policy-tag policy-locked" title="${escapeHtml(item.intent)}">${escapeHtml(mailIntentLabel(item.intent))}</span> <small>${escapeHtml(timelineTime(item.at))} ${escapeHtml([direction, to].filter(Boolean).join(' '))} · ${escapeHtml(letterStateWord(item.status))}</small></div><div>${escapeHtml(item.subject)}</div>${item.resolution ? `<div class="helper">${escapeHtml(item.resolution)}</div>` : ''}</div>`;
  }
  return `<div data-card-key="${escapeHtml(item.id)}" class="chat-item chat-memory"><div class="chat-meta"><span class="policy-tag">${escapeHtml(TIMELINE_LABEL[item.memory_class] || item.memory_class)}</span> <small>${escapeHtml(timelineTime(item.at))}</small></div><div>${escapeHtml(item.content)}</div></div>`;
}

async function loadAgentHistory(agentId) {
  const box = element('agent-history');
  try {
    const data = await api(`/agents/${encodeURIComponent(agentId)}/history`);
    const items = newestFirst(data.timeline || [], { oldestFirst: true });
    replaceActivityHtml(box, items.length
      ? items.map(timelineItem).join('')
      : '<div class="helper">Nimic încă: nicio sarcină, niciun mesaj și nicio decizie înregistrată.</div>');

  } catch (error) {
    replaceActivityHtml(box, `<div class="text-error">${escapeHtml(error instanceof Error ? error.message : 'Istoricul nu a putut fi încărcat.')}</div>`);
  }
}

/** Who the agent is, as the model is told: contract, character, memory, open messages. */
function renderIdentity(identity) {
  const contract = identity.contract || {};
  const work = contract.work_contract_json || {};
  const who = identity.character ? `${identity.display_name} este ${identity.character.canonical_name}.` : identity.display_name;
  element('inspector-mission').textContent = `${who} Misiune: ${contract.mission || 'nedefinită'}. Raportează către ${ownerName(work.reports_to) || '—'}.`;
  const sections = [['watch_for', 'Urmărește'], ['investigate', 'Investighează'], ['correct', 'Corectează'], ['let_pass', 'Lasă să treacă'], ['never_let_pass', 'Nu lasă să treacă niciodată'], ['escalate_when', 'Escaladează când'], ['deliverables', 'Livrabile']];
  element('inspector-contract').innerHTML = sections
    .filter(([key]) => Array.isArray(work[key]) && work[key].length)
    .map(([key, label]) => `<div class="identity-block"><span class="stat-label">${escapeHtml(label)}</span><ul>${work[key].map((item) => `<li>${escapeHtml(String(item))}</li>`).join('')}</ul></div>`)
    .join('') || '<p class="helper">Rolul nu are încă un contract de muncă. Rulează bootstrap-ul ca să fie creat.</p>';
  element('inspector-system-prompt').textContent = identity.system_prompt || '';
  const memory = identity.memory || [];
  element('inspector-memory').innerHTML = memory.length
    ? memory.map((m) => `<li><span class="policy-tag policy-flexible" title="${escapeHtml(m.memory_class)}">${escapeHtml(TIMELINE_LABEL[m.memory_class] || m.memory_class)}</span> ${escapeHtml(m.content)}</li>`).join('')
    : '<li class="helper">Nu ține minte nimic încă: nicio verificare, decizie sau publicare înregistrată.</li>';
  const messages = (identity.messages || []).filter((m) => m.status !== 'RESOLVED').slice(0, 8);
  element('inspector-messages').innerHTML = messages.length
    ? messages.map((m) => `<li class="inspector-mail" data-thread="${escapeHtml(m.thread_id || m.id)}" title="Deschide firul de corespondență"><span class="policy-tag policy-locked" title="${escapeHtml(m.intent)}">${escapeHtml(mailIntentLabel(m.intent))}</span> ${escapeHtml(m.subject)}${m.from_name ? ` <small>· de la ${escapeHtml(m.from_name)}</small>` : ''} <small class="ledger-open">fir ↗</small></li>`).join('')
    : '<li class="helper">Niciun mesaj deschis.</li>';
}

/**
 * The inspector's two state cells, in the words the name tag and the register use (glossary W26);
 * the enum stays in the cell's data-state and title. Null leaves a cell as it is.
 * @param {string|null} work @param {string|null} standing
 */
function showInspectorStates(work, standing) {
  /** @param {string} id @param {string|null} raw @param {string} words */
  const set = (id, raw, words) => {
    if (raw === null) return;
    const cell = element(id);
    cell.textContent = words;
    cell.dataset.state = raw;
    cell.title = raw;
  };
  set('inspector-state', work, work === null ? '' : workWord(work));
  set('inspector-lifecycle', standing, standing === null ? '' : lifecycleWord(standing));
  // W32: and worn on the header's portrait, as the roster's card wears it
  const head = element('inspector-head');
  if (work !== null) {
    head.dataset.state = String(work).toUpperCase();
    element('inspector-state-chip').textContent = workWord(work);
  }
  if (standing !== null) head.dataset.standing = String(standing).toUpperCase();
  if (standing !== null) {
    const acts = lifecycleActs(standing);
    /** @type {HTMLButtonElement} */ (element('agent-pause-btn')).disabled = !acts.pause;
    /** @type {HTMLButtonElement} */ (element('agent-resume-btn')).disabled = !acts.resume;
  }
}

/** Keep an open inspector on the same versioned state as the employee at the desk. */
function syncInspectorState() {
  if (!inspector.open || !currentSelectedAgent) return;
  const id = currentSelectedAgent.id || currentSelectedAgent.agent_id;
  const agent = officeState.agents.find(a => a.id === id);
  if (!agent) return;
  Object.assign(currentSelectedAgent, { runtime_state: agent.runtime_state, lifecycle: agent.lifecycle, version: agent.version });
  showInspectorStates(agent.runtime_state, agent.lifecycle);
  const key = `${id}:${agent.runtime_state}:${agent.lifecycle}`;
  if (element('inspector-portrait').dataset.pose !== key) {
    element('inspector-portrait').dataset.pose = key;
    paintPortrait(element('inspector-portrait'), agent);
  }
}

/** W32: the employee's id, copied for him; the key says what happened, then its name again. */
let copyIdReset = 0;
element('inspector-copy-id').addEventListener('click', async (event) => {
  const key = /** @type {HTMLButtonElement} */ (event.currentTarget);
  const id = key.dataset.agent || '';
  if (!id) return;
  let copied = false;
  try {
    await navigator.clipboard.writeText(id);
    copied = true;
  } catch {
    copied = false;
  }
  key.textContent = copied ? 'Identificator copiat' : 'Nu s-a putut copia';
  clearTimeout(copyIdReset);
  copyIdReset = window.setTimeout(() => { key.textContent = 'Copiază identificatorul'; }, 2000);
});

function renderInspector(agent) {
  element('inspector-name').textContent = agent.display_name || 'Agent';
  // W28: the eyebrow names the employee's place in the building; the name already says the role,
  // whose code stays in the tooltip (glossary W28)
  const roleEl = element('inspector-role');
  roleEl.textContent = deskPlace(officeEngine && officeEngine.assets ? officeEngine.assets.manifest : null, agent.desk_id);
  roleEl.title = agent.role_name || '';
  showInspectorStates(agent.runtime_state || 'IDLE', agent.lifecycle || 'ACTIVE');
  // W32: the header wears the roster's portrait of this employee and the state now; the raw id is a
  // copy key's tooltip, no longer a headline fact
  const id = String(agent.id || agent.agent_id || '');
  const copyKey = /** @type {HTMLButtonElement} */ (element('inspector-copy-id'));
  copyKey.title = id;
  copyKey.hidden = !id;
  if (copyKey.dataset.agent !== id) {
    copyKey.dataset.agent = id;
    copyKey.textContent = 'Copiază identificatorul';
    paintPortrait(element('inspector-portrait'), officeState.agents.find((a) => (a.id || a.agent_id) === id) || agent);
  }

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
// However it closes (the button, Escape, the backdrop), the employee is no longer chosen: the
// teal mark and tag in the world mean «open in the inspector», not «was opened once» (W11).
inspector.addEventListener('close',()=>{if(!inspector.open){inspectorRequest++; if(officeEngine) officeEngine.setSelectedAgent(null);} updateTypingIndicator();});

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
    showInspectorStates(null, updated.lifecycle);
    updateOfficeCanvas();
  } catch (err) {
    notify(err.message);
  }
});

element('agent-resume-btn').addEventListener('click', async () => {
  if (!currentSelectedAgent) return;
  const agentId = currentSelectedAgent.id || currentSelectedAgent.agent_id;
  try {
    const updated = await api(`/agents/${agentId}/resume`, { method: 'POST' });
    currentSelectedAgent.lifecycle = updated.lifecycle;
    showInspectorStates(null, updated.lifecycle);
    updateOfficeCanvas();
  } catch (err) {
    notify(err.message);
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

doorReads.set('research-modal', () => { loadTopics(); loadSources(); loadScripts(); });
if (openResearchBtn) {
  openResearchBtn.addEventListener('click', () => {
    openDoor(researchModal);
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
    const topics = newestFirst(data.topics || []);
    if (topics.length === 0) {
      replaceActivityHtml(listEl, '<div class="topics-loading">Niciun subiect propus încă.</div>');
      return;
    }
    replaceActivityHtml(listEl, topics
      .map((t) => {
        const cardClass =
          t.novelty_score >= 0.8 ? 'topic-card topic-card-high' : 'topic-card topic-card-low';
        const pct = Math.round((t.novelty_score || 0) * 100);
        return `
        <div class="${cardClass}" data-card-key="${escapeHtml(t.id)}">
          <div class="topic-card-header">
            <strong class="topic-card-title">${escapeHtml(t.title)}</strong>
            <span class="topic-card-novelty">Noutate: ${pct}%</span>
          </div>
          <p class="topic-card-subject" lang="en">${escapeHtml(t.topic)}</p>
          <div class="topic-card-meta">
            <span>Public: ${escapeHtml(t.target_audience)}</span> · <span>Stare: <strong class="topic-card-status" data-status="${escapeHtml(t.status)}" title="${escapeHtml(t.status)}">${escapeHtml(topicStatus(t.status))}</strong></span>
          </div>
        </div>
      `;
      })
      .join(''));
  } catch (err) {
    replaceActivityHtml(listEl, `<div class="text-error">Încărcarea a eșuat: ${escapeHtml(err.message)}</div>`);
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
  OTHER: 'nu a răspuns cu nimic utilizabil',
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
    line.push(`${countWords(health.claims_available, 'afirmație verificată', 'afirmații verificate')} în evidență.`);
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
      const editor = `<div class="host-search">
            <input class="host-search-template" data-host="${escapeHtml(r.host)}" value="${escapeHtml(r.search_template || '')}" placeholder="adresa de căutare a site-ului, cu {query} unde intră cuvintele (OpenSearch JSON)" title="De exemplu, pentru o enciclopedie MediaWiki: https://${escapeHtml(r.host)}/w/api.php?action=opensearch&search={query}&limit=5&namespace=0&format=json">
            <button class="quiet btn-host-search-save" data-host="${escapeHtml(r.host)}">Salvează căutarea</button>
            ${tryIt}
          </div>`;
      // W33: an empty search field on each of the 36 rows read as a form nobody filled. A row
      // with an address shows it to edit; a row without one keeps the field behind a key.
      const search = r.source === 'owner'
        ? (r.search_template
          ? editor
          : `<details class="host-search-edit"><summary class="host-search-key">Adaugă adresa de căutare</summary>${editor}</details>`)
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
      // W33: said once. The backend's sentence when it wrote one (it names the reason itself),
      // the reason's label otherwise; the label stays the line's tooltip, to compare hosts.
      const why = r.last_test_status === 'FAILED'
        ? `<div class="host-test-detail text-error" title="${escapeHtml(HOST_REASON_LABEL[r.last_test_reason] || r.last_test_reason || '')}">${escapeHtml(hostFailureWords(r.last_test_reason, r.last_test_detail, HOST_REASON_LABEL))}</div>`
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

    const sources = newestFirst(data.sources || []);
    if (!sources.length) {
      replaceActivityHtml(listEl, '<div class="topics-loading">Nicio sursă preluată încă.</div>');
      return;
    }
    replaceActivityHtml(listEl, sources
      .map(
        (src) => `
        <div data-card-key="${escapeHtml(src.id)}" class="topic-card source-card" data-source-id="${escapeHtml(src.id)}">
          <div class="topic-card-header">
            <strong class="topic-card-title">${escapeHtml(src.title)}</strong>
            <span class="topic-card-novelty">${escapeHtml(src.publisher)}</span>
          </div>
          <p class="topic-card-subject source-url">${escapeHtml(src.url)}</p>
          <div class="topic-card-meta">
            <span>${src.characters} caractere</span>
            · <span title="${escapeHtml(src.content_hash || '')}">amprentă ${escapeHtml(shortHash(src.content_hash))}</span>
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
      .join(''));

    listEl.querySelectorAll('.btn-extract-claims').forEach((btn) => {
      btn.addEventListener('click', () => extractClaims(btn.getAttribute('data-source-id'), btn));
    });
    listEl.querySelectorAll('.btn-show-claims').forEach((btn) => {
      btn.addEventListener('click', () => loadClaims(btn.getAttribute('data-source-id')));
    });
  } catch (err) {
    replaceActivityHtml(listEl, `<div class="text-error">Încărcarea a eșuat: ${escapeHtml(err.message)}</div>`);
  }
}

async function loadClaims(sourceId) {
  const box = element(`claims-${sourceId}`);
  box.hidden = false;
  replaceActivityHtml(box, '<div class="topics-loading">Se încarcă afirmațiile…</div>');
  try {
    const data = await api(`/factual/claims?source_id=${encodeURIComponent(sourceId)}`);
    const claims = newestFirst(data.claims || []);
    if (!claims.length) {
      replaceActivityHtml(box, '<div class="topics-loading">Nicio afirmație extrasă din această sursă.</div>');
      return;
    }
    replaceActivityHtml(box, claims.map((c) => renderClaim(c, sourceId)).join(''));
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
    replaceActivityHtml(box, `<div class="text-error">${escapeHtml(err.message)}</div>`);
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
      `${countLabel(n, 'afirmație extrasă', 'afirmații extrase')}, toate neverificate — un al doilea angajat trebuie să le confirme din sursă înainte de scenariu.`,
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
      replaceActivityHtml(listEl, '<div class="topics-loading">Niciun scenariu încă.</div>');
      return;
    }
    replaceActivityHtml(listEl, scripts.map(renderScript).join(''));
    listEl.querySelectorAll('.btn-approve-script').forEach((btn) => {
      /** @type {HTMLElement} */ (btn).onclick = () => approveScript(btn);
    });
  } catch (err) {
    replaceActivityHtml(listEl, `<div class="text-error">${escapeHtml(err.message)}</div>`);
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
        <span>${escapeHtml(seconds(script.target_duration_seconds))}</span>
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
/**
 * PAGE-11: the media room's status line, instead of a blocking browser alert: what failed stays
 * on screen beside the films until the next action replaces it.
 * @param {string} text @param {boolean} [error]
 */
function mediaStatus(text, error = false) {
  mediaStatusMsg.hidden = !text;
  mediaStatusMsg.className = error ? 'dialog-status-msg text-error' : 'dialog-status-msg';
  mediaStatusMsg.textContent = text;
}

doorReads.set('media-modal', () => { loadMediaProviderNote(); loadAwaitingStoryboard(); loadMediaStoryboards(); });
if (openMediaBtn) {
  openMediaBtn.addEventListener('click', () => {
    openDoor(mediaModal);
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
/**
 * W34: a scene's picture prompt by its first sentence; the rest behind «Tot promptul», word for word
 * (dialog_words.js promptFirstSentence). A short prompt is shown whole.
 * @param {string} text
 */
function scenePrompt(text) {
  const { first, rest } = promptFirstSentence(text);
  if (!rest) return `<p class="scene-prompt" lang="en">${escapeHtml(first)}</p>`;
  return `<div class="scene-prompt-wrap"><p class="scene-prompt" lang="en">${escapeHtml(first)}</p><details class="scene-prompt-more"><summary>Tot promptul</summary><p class="scene-prompt" lang="en">${escapeHtml(rest)}</p></details></div>`;
}

function characterCard(c) {
  const voice = c.voice_profile_json || {};
  const personality = c.personality_json || {};
  const speech = c.speech_style_json || {};
  const expressions = c.expressions_json || {};
  const behavior = c.behavior_json || {};
  // W34: the voice's style and pace; its id is the tooltip (glossary W34)
  const voiceLine = voiceWords(voice);
  const greeting = expressions.greeting || expressions.agreement;
  return `
    <div class="character-card">
      <div class="char-header">
        <span class="char-name">${escapeHtml(c.canonical_name)}</span>
        ${c.role_symbols ? `<span class="char-archetype" title="${escapeHtml(String(c.role_symbols).split(',')[0])}">${escapeHtml(String(c.role_symbols).split(',')[0])}</span>` : ''}
      </div>
      <p class="char-desc">${escapeHtml([c.face_hair_desc, c.outfit_desc].filter(Boolean).join(' '))}</p>
      ${charRow('Personalitate', personality.traits)}
      ${charRow('Vorbire', [speech.register, speech.cadence].filter(Boolean))}
      ${greeting ? `<div class="char-row"><span class="char-label">Expresie</span><em>„${escapeHtml(greeting)}”</em></div>` : ''}
      ${charRow('Comportament', behavior.work_rituals)}
      ${charRow('Nu devia', c.forbidden_deviations)}
      ${voiceLine.text ? `<div class="char-voice"${voiceLine.title ? ` title="${escapeHtml(voiceLine.title)}"` : ''}>Voce: ${escapeHtml(voiceLine.text)}</div>` : ''}
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
  // W34: «Voce alocată», the voice's id its tooltip
  if (binding.voice_id) parts.push(`<span class="char-voice-bound" title="${escapeHtml(`Identificatorul vocii: ${binding.voice_id}`)}">Voce alocată</span>${binding.model_id ? ` · model ${escapeHtml(binding.model_id)}` : ''}`);
  if (lockedFields.length) parts.push(`Blocate: ${escapeHtml(lockedFields.join(', '))}`);
  if (c.consistency_status) parts.push(`Consistență: ${escapeHtml(consistencyWord(c.consistency_status))}`);
  if ((c.approved_fallbacks_json || []).length) parts.push(countWords(c.approved_fallbacks_json.length, 'model aprobat', 'modele aprobate'));
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
    const scripts = newestFirst(data.scripts || []);
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
        <div data-card-key="${escapeHtml(script.id)}" class="topic-card script-card">
          <div class="topic-card-header">
            <strong class="topic-card-title">${escapeHtml(script.title)}</strong>
            <span class="topic-card-novelty">v${script.version}</span>
          </div>
          <div class="topic-card-meta">
            <span>${escapeHtml(seconds(script.target_duration_seconds))}</span>
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
      /** @type {HTMLElement} */ (btn).onclick = () => makeStoryboard(btn);
    });
    listEl.querySelectorAll('.btn-story-review').forEach((btn) => {
      /** @type {HTMLElement} */ (btn).onclick = () => runStoryReview(btn);
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
    mediaStatusMsg.textContent = `Storyboard creat: „${storyboard.title}” — ${countWords(storyboard.total_scenes, 'scenă', 'scene')}.`;
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
      }</span> <span>filmate: ${motion.clips || 0} din ${countWords(motion.scenes || 0, 'scenă', 'scene')} · ${
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

/* ------------------------------------------------------------- Foaia de filmare (2026-10-01) */

/**
 * The shooting sheet's drawer (shooting_sheet.js builds every word of it). Opened from a storyboard's
 * «Foaia de filmare» button, and by the render button when the studio answers 409 «Folosește foaia
 * de filmare» (PRODUCTION). Reading it costs 0 credits; only a step's «Da, aprob și cumpăr» buys.
 */
const sheetDrawer = {
  /** @type {HTMLDialogElement|null} */ dialog: null,
  /** @type {string|null} */ id: null,
  /** @type {any} */ sheet: null,
  /** @type {string|null} */ confirm: null,
  notice: '',
  noticeError: false,
  /** The refusal's code (FILM_BUSY …) behind a failed notice, or null. @type {string|null} */
  noticeCode: null,
  /** PAGE-06: a purchase of the film on screen is in flight (sheetBusy, kept per storyboard). */
  get busy() { return Boolean(this.id && sheetBusy.has(this.id)); },
  /** What the assembly answered last (its QC and the letter), for this storyboard. @type {any} */ assembled: null,
  /** Whether «Schimbă regula» is open, kept across repaints. */
  ruleOpen: false,
  /** TAKE_CHOICE_SEEN: the take button pressed, while the studio answers. @type {{take: string, decision: string}|null} */
  pressed: null,
  /**
   * TAKE_CHOICE_SEEN: the answer to his last look at a take, shown in the scene he pressed.
   * @type {{scene: number, take: string, decision: string, failed: boolean, network?: boolean, message: string}|null}
   */
  choice: null,
};
/**
 * PAGE-06: the presses still running, by storyboard, with what they buy in words. Kept apart
 * from the drawer: reopening a film's sheet (or another film's and back) never re-enables the
 * buttons of a purchase the server is still making.
 * @type {Map<string, string>}
 */
const sheetBusy = new Map();
/**
 * The pictures already read with the Owner's key, as data: URLs (the page's img-src takes data:,
 * not blob:). PAGE-17: at most PICTURE_CAPACITY of them, the least recently shown let go first.
 */
const sheetPictures = new MediaCache(PICTURE_CAPACITY);
/** The clips played in the open sheet; a repaint or a close removes them, and they are revoked. */
const sheetClips = new ObjectUrls();
/** Remembered across presses: once the studio said «use the sheet», the render button opens it. */
const renderState = { sheetFirst: false };

function sheetDialog() {
  if (sheetDrawer.dialog) return sheetDrawer.dialog;
  const dialog = document.createElement('dialog');
  dialog.id = 'shooting-sheet-drawer';
  dialog.className = 'studio-dialog sheet-drawer';
  dialog.setAttribute('aria-label', SHEET_TITLE);
  dialog.innerHTML = '<div class="dialog-header"><div>'
    + `<h2 class="dialog-title">${escapeHtml(SHEET_TITLE)}</h2>`
    + '<p class="dialog-desc">Urmărește scenele și pornește următorul pas. Verifică prețul înainte de orice cumpărare.</p></div>'
    + '<button type="button" class="dialog-close" data-sheet-action="close" aria-label="Închide">'
    + '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6.4 6.4l11.2 11.2M17.6 6.4L6.4 17.6"/></svg></button></div>'
    // PAGE-19: one status line for the whole drawer, outside the body a repaint replaces, so
    // assistive technology hears each notice as a change of one live region
    + '<p class="sheet-notice sheet-status" role="status" aria-live="polite" data-sheet-status hidden></p>'
    + '<div class="dialog-body sheet-body" data-sheet-body></div>';
  document.body.append(dialog);
  dialog.addEventListener('click', (event) => { void onSheetClick(event); });
  // PAGE-06: Esc does not hide a purchase in flight; the drawer says it is still buying.
  dialog.addEventListener('cancel', (event) => {
    if (!sheetDrawer.busy) return;
    event.preventDefault();
    sheetNotice(sheetBusy.get(String(sheetDrawer.id)) || buyingNotice('stills'));
    paintSheet();
  });
  // «Schimbă regula» stays open across the repaints that follow a press (toggle does not bubble).
  dialog.addEventListener('toggle', (event) => {
    const box = event.target;
    if (box instanceof HTMLDetailsElement && box.classList.contains('sheet-rule-box')) sheetDrawer.ruleOpen = box.open;
  }, true);
  dialog.addEventListener('close', () => { sheetClips.revokeAll(); });
  sheetDrawer.dialog = dialog;
  return dialog;
}

/**
 * A take's picture or a card's preview, read with the Owner's key.
 * @param {string} src
 * @returns {Promise<string>}
 */
async function sheetPicture(src) {
  const kept = sheetPictures.get(src);
  if (kept) return kept;
  if (!src.startsWith('/api/v1/media/')) throw new Error('Adresa imaginii nu este a studioului.');
  const response = await fetch(src, { headers: { Authorization: `Bearer ${ownerToken}` }, cache: 'no-store' });
  if (!response.ok) throw new Error(`Imaginea nu a putut fi citită (${response.status}).`);
  const blob = await response.blob();
  /** @type {string} */
  const url = await new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ''));
    reader.onerror = () => reject(new Error('Imaginea nu a putut fi citită.'));
    reader.readAsDataURL(blob);
  });
  sheetPictures.set(src, url);
  return url;
}

/**
 * PAGE-19: the key that had keyboard focus, as a selector of its data attributes, so the same key
 * can be focused again after a repaint replaced it.
 * @param {Element|null} element @param {Element} body
 */
function focusKey(element, body) {
  if (!(element instanceof HTMLElement) || !body.contains(element)) return '';
  const attrs = Array.from(element.attributes).filter((a) => a.name.startsWith('data-'));
  if (!attrs.length && !element.id) return '';
  return element.tagName.toLowerCase()
    + (element.id ? `#${CSS.escape(element.id)}` : '')
    + attrs.map((a) => `[${a.name}="${CSS.escape(a.value)}"]`).join('');
}

/** @param {Element} body @param {string} key */
function restoreFocus(body, key) {
  if (!key) return;
  const again = /** @type {HTMLElement|null} */ (body.querySelector(key));
  if (again && !(/** @type {HTMLButtonElement} */ (again).disabled)) again.focus({ preventScroll: true });
  else /** @type {HTMLElement|null} */ (sheetDialog().querySelector('[data-sheet-action="close"]'))?.focus({ preventScroll: true });
}

/**
 * The drawer's one status line. SHEET_BUSY_ONCE: a press refused because the film is at work is
 * answered with a pointer to the bar that already says so (sheetStatusText), not the same sentence.
 */
function sheetStatus() {
  const line = /** @type {HTMLElement|null} */ (sheetDialog().querySelector('[data-sheet-status]'));
  if (!line) return;
  const { text, tone } = sheetStatusText(sheetDrawer.notice, sheetDrawer.noticeCode, sheetDrawer.noticeError, sheetDrawer.sheet);
  if (line.textContent !== text) line.textContent = text;
  line.hidden = !text;
  line.classList.toggle('sheet-blocked', Boolean(text && tone === 'error'));
  line.classList.toggle('sheet-waiting', Boolean(text && tone === 'waiting'));
}

function paintSheet() {
  const body = sheetDialog().querySelector('[data-sheet-body]');
  if (!body) return;
  const focused = focusKey(document.activeElement, body);
  // the repaint removes every clip the body held: their object URLs go with them (PAGE-17)
  sheetClips.revokeAll();
  sheetStatus();
  if (!sheetDrawer.sheet) {
    body.innerHTML = sheetDrawer.noticeError ? '' : '<p class="topics-loading">Se citește foaia de filmare (0 credite)…</p>';
    return;
  }
  body.innerHTML = sheetHtml(sheetDrawer.sheet, {
    escape: escapeHtml,
    confirm: sheetDrawer.confirm,
    // the notice is the drawer's status line, outside the body (PAGE-19)
    notice: '',
    noticeError: sheetDrawer.noticeError,
    // his rule and its version as the snapshot read them (the command is sent against that version)
    policy: state?.policy || null,
    assembled: sheetDrawer.assembled,
    ruleOpen: sheetDrawer.ruleOpen,
    pressed: sheetDrawer.pressed,
    choice: sheetDrawer.choice,
  });
  body.querySelectorAll('img[data-sheet-src]').forEach((node) => {
    const img = /** @type {HTMLImageElement} */ (node);
    const src = img.dataset.sheetSrc || '';
    sheetPicture(src).then((url) => { img.src = url; }).catch(() => { img.alt = `${img.alt} — nu a putut fi citită`; });
  });
  if (sheetDrawer.busy) body.querySelectorAll('button').forEach((b) => { /** @type {HTMLButtonElement} */ (b).disabled = true; });
  restoreFocus(body, focused);
}

async function loadSheet() {
  if (!sheetDrawer.id) return;
  try {
    sheetDrawer.sheet = await api(sheetPath(sheetDrawer.id), { timeoutMs: 60000 });
  } catch (error) {
    sheetDrawer.sheet = null;
    sheetNotice(`Foaia de filmare nu a putut fi citită: ${error.message}`, true);
  }
  paintSheet();
}

/**
 * @param {string} storyboardId
 * @param {string} [message] the studio's 409, when it sent the Owner here
 */
async function openShootingSheet(storyboardId, message = '') {
  const dialog = sheetDialog();
  if (sheetDrawer.id !== storyboardId) Object.assign(sheetDrawer, { sheet: null, assembled: null });
  // A purchase still in flight for this film keeps its notice and its disabled buttons.
  const buying = sheetBusy.get(storyboardId);
  Object.assign(sheetDrawer, { id: storyboardId, confirm: null, notice: buying || message, noticeError: false, noticeCode: null, choice: null });
  if (!dialog.open) dialog.showModal();
  paintSheet();
  await loadSheet();
}

/** @param {string} text @param {boolean} [failed] @param {string|null} [code] the refusal's code */
function sheetNotice(text, failed = false, code = null) {
  sheetDrawer.notice = text;
  sheetDrawer.noticeError = failed;
  sheetDrawer.noticeCode = failed ? code : null;
}

/** @param {HTMLElement} node */
async function playSheetClip(node) {
  const src = node.dataset.sheetSrc || '';
  if (!src.startsWith('/api/v1/media/')) return;
  try {
    const response = await fetch(src, { headers: { Authorization: `Bearer ${ownerToken}` }, cache: 'no-store' });
    if (!response.ok) throw new Error(`Clipul nu a putut fi citit (${response.status}).`);
    const video = document.createElement('video');
    video.src = sheetClips.add(URL.createObjectURL(await response.blob()));
    video.controls = true;
    video.playsInline = true;
    video.className = 'sheet-video';
    node.replaceWith(video);
  } catch (error) {
    sheetNotice(error.message, true);
    paintSheet();
  }
}

/** The Owner's note and his consent over the day's budget, from the open question. */
function sheetAnswer() {
  const dialog = sheetDialog();
  return {
    note: /** @type {HTMLTextAreaElement|null} */ (dialog.querySelector('[data-sheet-note]'))?.value || '',
    over: /** @type {HTMLInputElement|null} */ (dialog.querySelector('[data-sheet-over-budget]'))?.checked || false,
  };
}

/**
 * A refusal or a wait, in the backend's own words, each scene it names once.
 * @param {{message?: string, scenes?: string[]}} result @param {string} fallback
 */
function sheetRefusal(result, fallback) {
  const lines = [result.message || fallback, ...(result.scenes || [])].map((line) => String(line).trim()).filter(Boolean);
  return [...new Set(lines)].join(' ');
}

/**
 * A refusal as an error that keeps the backend's code (FILM_BUSY …) for the status line.
 * @param {{message?: string, scenes?: string[], code?: string|null}} result @param {string} fallback
 */
function refusalError(result, fallback) {
  return Object.assign(new Error(sheetRefusal(result, fallback)), { code: result.code || null });
}

/** «(1 întrebare veche retrasă …)» after a notice, when the press withdrew older questions. @param {{withdrawn?: string[]}} result */
function withdrawnNote(result) {
  const n = Array.isArray(result.withdrawn) ? result.withdrawn.length : 0;
  return n ? ` (${withdrawnWords(n)}: erau pentru o foaie mai veche.)` : '';
}

/** The redo plan a press names, as the sheet on screen carries it. @param {string} kind @param {string} scene */
function sheetRedoPlan(kind, scene) {
  const sheet = sheetDrawer.sheet;
  if (kind === 'audio') return sheet?.footer?.audio_redo || null;
  const found = (sheet?.scenes || []).find((/** @type {any} */ s) => String(s.scene_index) === scene);
  return found?.redo?.[kind] || null;
}

/** The redo's notice, once it is done. @param {string} kind @param {string} scene */
function redoDoneWords(kind, scene) {
  if (kind === 'still') return `Imaginea scenei ${scene} a fost refăcută cu aprobarea ta: alege varianta nouă pe foaie; celelalte scene nu s-au atins.`;
  if (kind === 'motion') return `Mișcarea scenei ${scene} a fost refăcută cu aprobarea ta: privește clipul nou pe foaie; celelalte scene nu s-au atins.`;
  if (kind === 'card') return `Cardul scenei ${scene} a fost recompus local, iar filmul reasamblat din celelalte cadre: 0 credite.`;
  return 'Sunetul filmului a fost remasterizat sub aceeași imagine: 0 credite.';
}

/**
 * What a press on the sheet does, as one call that answers the Owner's notice; null when the press
 * is only the drawer's own (open a question, close it).
 * @param {HTMLElement} node @param {string} id
 * @returns {(() => Promise<string>) | null}
 */
function sheetCommand(node, id) {
  const action = node.dataset.sheetAction;
  if (action === 'confirm-step') {
    const step = node.dataset.step || '';
    const { note, over } = sheetAnswer();
    const planHash = String(sheetDrawer.sheet?.sheet_hash || '');
    if (step === ASSEMBLE_STEP) {
      return async () => {
        const result = await approveAssemble(api, { storyboardId: id, planHash, note, allowOverBudget: over, commandId: crypto.randomUUID(), purchaseId: crypto.randomUUID() });
        if (result.status !== 'ASSEMBLED') throw refusalError(result, 'Filmul nu a fost asamblat.');
        sheetDrawer.assembled = result.result;
        const verdict = result.result?.qc?.status === 'PASSED' ? 'a trecut controlul calității' : 'nu a trecut controlul calității: motivele și scrisoarea sunt mai jos';
        return `Filmul a fost asamblat din cadrele acceptate și ${verdict}.${withdrawnNote(result)}`;
      };
    }
    return async () => {
      const result = await approveStep(api, { storyboardId: id, step, planHash, note, allowOverBudget: over, commandId: crypto.randomUUID(), purchaseId: crypto.randomUUID() });
      if (result.status !== 'BOUGHT') throw refusalError(result, 'Pasul nu a cumpărat nimic.');
      return `Pasul a fost cumpărat cu aprobarea ta, pentru foaia pe care ai văzut-o. Foaia de mai jos arată ce s-a cumpărat.${withdrawnNote(result)}`;
    };
  }
  if (action === 'confirm-redo') {
    const kind = node.dataset.kind || '';
    const scene = node.dataset.scene || '';
    const { note, over } = sheetAnswer();
    const plan = sheetRedoPlan(kind, scene);
    return async () => {
      const result = await approveRedo(api, {
        storyboardId: id,
        kind,
        sceneIndex: scene ? Number(scene) : null,
        planHash: plan?.plan_hash || null,
        note,
        allowOverBudget: over,
        commandId: crypto.randomUUID(),
        purchaseId: crypto.randomUUID(),
      });
      if (result.status !== 'DONE') throw refusalError(result, 'Nimic nu a fost refăcut.');
      // a redone film is a new film: the QC shown was the old one's
      sheetDrawer.assembled = null;
      return `${redoDoneWords(kind, scene)}${withdrawnNote(result)}`;
    };
  }
  if (action === 'take') {
    const decision = node.dataset.decision === 'APPROVED' ? 'APPROVED' : 'REJECTED';
    return async () => {
      // the decision builds the sheet before it answers (to name the next step): it is given as
      // long as the sheet's own read, so a slow answer is not taken for a refused choice
      const result = await api(takeDecisionPath(node.dataset.take || ''), { method: 'POST', body: JSON.stringify({ decision, note: null }), timeoutMs: 60000 });
      // TAKE_CHOICE_SEEN (2026-10-04): the server says what his choice set going (the film's
      // continuation and what it buys under his rule); the page never guesses what was bought.
      const said = result?.outcome?.message_ro;
      if (said) return String(said);
      return decision === 'APPROVED'
        ? 'Aprobat. Foaia are o amprentă nouă: o aprobare dată altei foi nu cumpără nimic pe aceasta; ce cumpără filmul mai departe urmează regula ta pentru pașii plătiți.'
        : 'Respins: nu se mai folosește în film.';
    };
  }
  if (action === 'model') {
    const scene = node.dataset.scene || '';
    const model = node.dataset.model || '';
    const named = model === 'LOCAL_MOVE' ? 'imagine fixă animată local' : model || 'alegerea studioului';
    return async () => {
      await api(sceneModelPath(id, scene), { method: 'PUT', body: JSON.stringify({ model_id: model || null, note: null }) });
      return `Scena ${scene}: ${named}. Foaia are o amprentă nouă; o aprobare dată altei foi nu cumpără nimic pe aceasta.`;
    };
  }
  return null;
}

/** @param {Event} event */
async function onSheetClick(event) {
  const target = event.target instanceof Element ? event.target.closest('[data-sheet-action]') : null;
  if (!target || sheetDrawer.busy) return;
  const node = /** @type {HTMLElement} */ (target);
  const action = node.dataset.sheetAction;
  const id = sheetDrawer.id;
  if (action === 'close') { sheetDialog().close(); return; }
  if (!id || !sheetDrawer.sheet) return;
  if (action === 'step') { sheetDrawer.confirm = node.dataset.step || null; sheetNotice(''); paintSheet(); return; }
  if (action === 'redo') { sheetDrawer.confirm = redoKey(node.dataset.kind || '', node.dataset.scene || null); sheetNotice(''); paintSheet(); return; }
  if (action === 'cancel-step') { sheetDrawer.confirm = null; paintSheet(); return; }
  if (action === 'to-steps') {
    sheetDialog().querySelector('#sheet-steps')?.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' });
    return;
  }
  if (action === 'to-scene') {
    const index = Number(node.dataset.scene);
    const scene = Array.from(sheetDialog().querySelectorAll('[data-scene-index]')).find((card) => Number(/** @type {HTMLElement} */ (card).dataset.sceneIndex) === index);
    scene?.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' });
    /** @type {HTMLElement|null} */ (scene?.querySelector('.sheet-scene-line'))?.focus({ preventScroll: true });
    return;
  }
  if (action === 'play') { await playSheetClip(node); return; }
  if (action === 'paid-media-save') {
    // His rule, sent against the policy version the page read; a 409 means it moved meanwhile.
    const dialog = sheetDialog();
    const choice = /** @type {HTMLInputElement|null} */ (dialog.querySelector('input[name="paid-media"]:checked'))?.value || '';
    const amount = /** @type {HTMLInputElement|null} */ (dialog.querySelector('[data-paid-media-amount]'))?.value || '';
    sheetBusy.set(id, 'Se salvează regula ta…');
    sheetDrawer.ruleOpen = true;
    paintSheet();
    try {
      const saved = await savePaidMediaRule(api, { choice, amount, version: state?.policy?.version, commandId: crypto.randomUUID() });
      // saved or stale: the page reads the policy again, so he looks at the rule as it is now
      if (saved.reload) await refresh();
      sheetNotice(saved.message, saved.status !== 'SAVED');
      if (saved.status === 'SAVED') sheetDrawer.ruleOpen = false;
    } finally {
      sheetBusy.delete(id);
      await loadSheet();
    }
    return;
  }
  const run = sheetCommand(node, id);
  if (!run) return;
  // PAGE-06: say what is being bought and that a second press is not needed; the purchase is
  // kept busy for this film until the server answers, whatever the drawer shows meanwhile.
  // TAKE_CHOICE_SEEN: a look at a take is answered where he clicked: the pressed button says it
  // is working, and the answer goes to that scene's card (and to the status line, as always).
  const card = /** @type {HTMLElement|null} */ (node.closest('[data-scene-index]'));
  const choiceScene = action === 'take' && card ? Number(card.dataset.sceneIndex) : null;
  const take = { take: node.dataset.take || '', decision: node.dataset.decision === 'APPROVED' ? 'APPROVED' : 'REJECTED' };
  sheetDrawer.choice = null;
  sheetDrawer.pressed = action === 'take' ? take : null;
  let buying = 'Se trimite…';
  if (action === 'confirm-step') buying = buyingNotice(node.dataset.step || '');
  else if (action === 'confirm-redo') buying = buyingNotice(redoKey(node.dataset.kind || '', node.dataset.scene || null));
  else if (choiceScene !== null) buying = `Se trimite alegerea ta pentru scena ${choiceScene}…`;
  sheetBusy.set(id, buying);
  sheetNotice(buying);
  paintSheet();
  let said = '';
  let failed = false;
  // no answer arrived (fetchFailure): the server may have done it; the card never says it failed
  let network = false;
  /** @type {string|null} */
  let code = null;
  try {
    said = await run();
    if (sheetDrawer.id === id) sheetDrawer.confirm = null;
  } catch (error) {
    said = error.message;
    failed = true;
    network = Boolean(error?.network);
    code = typeof error?.code === 'string' ? error.code : null;
  } finally {
    sheetBusy.delete(id);
    sheetDrawer.pressed = null;
    // the answer belongs to its film: shown only while that film's sheet is the one open
    if (sheetDrawer.id === id) {
      sheetNotice(said, failed, code);
      if (choiceScene !== null) sheetDrawer.choice = { scene: choiceScene, ...take, failed, network, message: said };
      await loadSheet();
      if (choiceScene !== null && sheetDrawer.id === id) keepSceneInView(choiceScene);
    }
  }
}

/**
 * TAKE_CHOICE_SEEN: after the answer's repaint, the scene he pressed stays in view (its chosen
 * picture and the note of what his choice did), and the note takes the keyboard focus the pressed
 * button had (that button is gone: the chosen picture is the scene's still now).
 * @param {number} scene
 */
function keepSceneInView(scene) {
  const card = sheetDialog().querySelector(`[data-scene-index="${CSS.escape(String(scene))}"]`);
  if (!card) return;
  card.querySelector('[data-sheet-choice]')?.scrollIntoView({ behavior: 'auto', block: 'nearest' });
  const note = /** @type {HTMLElement|null} */ (card.querySelector('.sheet-choice-note'));
  (note || card).scrollIntoView({ behavior: 'auto', block: 'nearest' });
  if (note) {
    note.tabIndex = -1;
    note.focus({ preventScroll: true });
  }
}

/**
 * PAGE-17: the media room reads one page of summary rows (GET /media/storyboards?limit=&offset=,
 * newest first: the scene count, the QC verdict and the film's asset id) and loads a card's
 * production package, scenes and QC only when he opens «Detalii». It used to fetch all three for
 * every storyboard on every opening: 3N+1 requests.
 */
const MEDIA_PAGE = 10;
/** @type {any[]} the summary rows read so far */
let mediaRows = [];
/** @type {number|null} where the next page starts, or null when every row is read */
let mediaNext = null;
let mediaTotal = 0;
/** The films played in the media room, revoked when the list is read again or the room closes. */
const filmUrls = new ObjectUrls();

/** @param {any} sb a summary row */
function storyboardSummaryHtml(sb) {
  const qc = sb.qc_status
    ? `<span class="${sb.qc_status === 'PASSED' ? 'qc-badge-pass' : 'qc-badge-fail'}">QC: ${escapeHtml(qcWord(sb.qc_status))}</span>`
    : (sb.asset_id ? '<span class="tag">QC: Neefectuat</span>' : '');
  return `
        <div class="storyboard-card" data-id="${escapeHtml(sb.id)}" data-door-steps>
          <div class="storyboard-header">
            <div>
              <h4 class="storyboard-title">${escapeHtml(sb.title)}</h4>
              <div class="storyboard-meta">
                <span>Aspect: <strong>${escapeHtml(sb.aspect_ratio || '9:16')}</strong></span>
                <span>${escapeHtml(countWords(sb.scene_count, 'scenă', 'scene'))}</span>
                <span>Stare: <strong class="${storyboardTone(sb.status)}" data-status="${escapeHtml(sb.status)}" title="${escapeHtml(sb.status)}">${escapeHtml(storyboardStatus(sb.status))}</strong></span>
                ${qc}
              </div>
            </div>
            <div class="storyboard-actions">
              <button type="button" class="quiet" data-media-detail="${escapeHtml(sb.id)}" aria-expanded="false" aria-controls="media-detail-${escapeHtml(sb.id)}">Detalii</button>
              <button type="button" class="quiet btn-shooting-sheet" data-id="${escapeHtml(sb.id)}" title="Prompturile, modelul fiecărei scene, creditele și plafonul, înainte de orice cumpărare (0 credite)">Foaia de filmare</button>
              <button type="button" class="btn-render-video" data-id="${escapeHtml(sb.id)}">Randare 9:16</button>
              <button type="button" class="btn-qc-video" data-id="${escapeHtml(sb.id)}">Verifică QC</button>
            </div>
          </div>
          <div class="storyboard-detail" id="media-detail-${escapeHtml(sb.id)}" hidden></div>
        </div>`;
}

/**
 * A card's detail, read when he opens it: the production package, the scenes and, for a rendered
 * film, its QC report and the film itself.
 * @param {any} sb a summary row
 */
async function storyboardDetailHtml(sb) {
  const [pack, detail, qcReport] = await Promise.all([
    api(`/media/storyboards/${sb.id}/production-package`).catch(() => null),
    api(`/media/storyboards/${sb.id}`).catch(() => null),
    sb.asset_id ? api(`/media/qc/${sb.id}`).catch(() => null) : Promise.resolve(null),
  ]);
  const scenes = (detail && detail.scenes) || [];
  const motion = (detail && detail.motion) || null;
  const motionScenes = (detail && detail.motion_scenes) || [];
  const motionNotes = (detail && detail.motion_notes) || [];
  // W28: the directions every scene's prompt ends with are said once, under the scenes
  const shared = sharedTail(scenes.map((/** @type {any} */ s) => s.visual_prompt));
  const scenesHtml = scenes
    .map(
      (/** @type {any} */ s, /** @type {number} */ i) => `
        <div class="scene-card">
          <div class="scene-card-header">
            <span class="scene-badge">Scena #${s.scene_index}</span>
            <span class="scene-duration">${escapeHtml(seconds(s.duration_seconds))}</span>
          </div>
          <div class="scene-shot" title="${escapeHtml(`${s.shot_type} · ${s.visual_type}`)}">${escapeHtml(shotWords(s.shot_type, s.visual_type))}</div>
          ${scenePrompt(shared.heads[i])}
          ${String(s.voiceover_segment || '').trim() ? `<p class="scene-audio"><q lang="en">${escapeHtml(s.voiceover_segment)}</q></p>` : '<p class="scene-audio scene-audio-none" title="Scena nu are narațiune">—</p>'}
        </div>
      `,
    )
    .join('');

  let renderHtml = '';
  if (sb.asset_id || sb.status === 'RENDERED') {
    const qcPassed = qcReport && qcReport.status === 'PASSED';
    const qcBadge = qcReport
      ? `<span class="${qcPassed ? 'qc-badge-pass' : 'qc-badge-fail'}">QC: ${escapeHtml(qcWord(qcReport.status))}</span>`
      : '<span class="tag">QC: Neefectuat</span>';
    const checks = qcReport ? qcReport.checks_json || {} : {};
    const techPassed = Boolean(checks.technical_qc && checks.technical_qc.passed);
    const factualPassed = Boolean(checks.factual_qc && checks.factual_qc.passed);
    // null means "not implemented"; it is deliberately not coerced to false.
    const charDrift = checks.character_drift_qc ? checks.character_drift_qc.passed : null;
    const rightsPassed = Boolean(checks.rights_qc && checks.rights_qc.passed);
    // A check that was never implemented must not be scored: an em dash says
    // "not evaluated", whereas 0% would claim a failed measurement.
    const scoreCell = (/** @type {string} */ label, /** @type {any} */ passed) => {
      const value = passed === null || passed === undefined ? '—' : passed ? '100%' : '0%';
      return `<div class="qc-score-item"><div>${label}</div><div class="qc-score-num">${value}</div></div>`;
    };
    const tech = checks.technical_qc || {};
    // The film itself: the asset quality control measured is the one to watch.
    const assetId = qcReport ? qcReport.media_asset_id : sb.asset_id;
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
                  ? `<button type="button" class="video-play" data-asset="${escapeHtml(assetId)}" title="Redă filmul">${icon('play')}Redă</button>`
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
                  ? `${frameSize(tech.measured_width, tech.measured_height)} · ${escapeHtml(seconds(tech.measured_duration_seconds))} · ${escapeHtml(String(tech.video_codec || '—'))}`
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
          ${productionPackageBlock(pack)}
          <div class="storyboard-scenes-grid">
            ${scenesHtml}
          </div>
          ${shared.tail ? `<div class="scene-common"><p class="scene-common-label">Aceleași indicații, la sfârșitul fiecărei scene</p><p class="scene-prompt scene-common-text" lang="en">${escapeHtml(shared.tail)}</p></div>` : ''}
          ${renderHtml}`;
}

/** @param {boolean} [more] read the next page and add it, instead of reading the first again */
async function loadMediaStoryboards(more = false) {
  const listEl = element('storyboards-list');
  if (!more) filmUrls.revokeAll();
  try {
    const offset = more && mediaNext !== null ? mediaNext : 0;
    const data = await api(`/media/storyboards?limit=${MEDIA_PAGE}&offset=${offset}`);
    const rows = Array.isArray(data.storyboards) ? data.storyboards : [];
    mediaRows = more ? mediaRows.concat(rows) : rows;
    mediaNext = data.next_offset ?? null;
    mediaTotal = Number(data.total) || mediaRows.length;
    if (mediaRows.length === 0) {
      replaceActivityHtml(listEl, `
        <div class="topics-loading">
          Niciun storyboard în flux.
          ${demoCaseShown(state?.policy) ? '<br>Apasă «Creează un caz demo» pentru un caz de test: un subiect, un scenariu și o afirmație neverificată, de verificat în Cercetare.' : ''}
        </div>
      `);
      return;
    }
    const left = mediaTotal - mediaRows.length;
    replaceActivityHtml(listEl, newestFirst(mediaRows).map(storyboardSummaryHtml).join('')
      + (mediaNext !== null && left > 0
        ? `<div class="source-actions"><button type="button" class="quiet" data-media-more>Încă ${escapeHtml(countWords(Math.min(left, MEDIA_PAGE), 'storyboard', 'storyboarduri'))} (din ${escapeHtml(String(left))} rămase)</button></div>`
        : ''));
  } catch (err) {
    replaceActivityHtml(listEl, `<div class="text-error">Încărcarea producției media a eșuat: ${escapeHtml(err.message)}</div>`);
  }
}

// The film plays where the film is. The Owner's key travels in a header, so the bytes are
// fetched once and played from a blob rather than handed to <video src>, which could not
// authenticate. The same bytes are what the download link saves.
/** @param {string} assetId @param {HTMLElement} container @param {HTMLButtonElement|null} button */
async function playFilm(assetId, container, button) {
  if (button) { button.disabled = true; button.textContent = 'Se încarcă…'; }
  try {
    const response = await fetch(`/api/v1/media/assets/${assetId}/stream`, {
      headers: { Authorization: `Bearer ${ownerToken}` },
      cache: 'no-store',
    });
    if (!response.ok) throw new Error(`Fișierul nu a putut fi citit (${response.status}).`);
    const url = filmUrls.add(URL.createObjectURL(await response.blob()));
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
    mediaStatus(`Filmul nu a putut fi redat: ${err.message}`, true);
    return null;
  }
}

/** @param {string} assetId */
async function downloadFilm(assetId) {
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
    mediaStatus(`Filmul nu a putut fi descărcat: ${err.message}`, true);
  }
}

/** @param {HTMLButtonElement} btn */
async function toggleMediaDetail(btn) {
  const id = btn.dataset.mediaDetail || '';
  const box = document.getElementById(`media-detail-${id}`);
  const row = mediaRows.find((r) => r.id === id);
  if (!box || !row) return;
  const open = btn.getAttribute('aria-expanded') === 'true';
  if (open) {
    box.hidden = true;
    btn.setAttribute('aria-expanded', 'false');
    btn.textContent = 'Detalii';
    return;
  }
  btn.setAttribute('aria-expanded', 'true');
  btn.textContent = 'Ascunde detaliile';
  box.hidden = false;
  if (!box.dataset.loaded) {
    box.innerHTML = '<div class="topics-loading">Se încarcă detaliile…</div>';
    box.innerHTML = await storyboardDetailHtml(row);
    box.dataset.loaded = '1';
  }
}

/** One listener for the whole list: the cards are repainted, the listener stays. */
element('storyboards-list').addEventListener('click', async (event) => {
  const target = /** @type {HTMLElement} */ (event.target);
  const more = target.closest('[data-media-more]');
  if (more) { /** @type {HTMLButtonElement} */ (more).disabled = true; await loadMediaStoryboards(true); return; }
  const detail = /** @type {HTMLButtonElement|null} */ (target.closest('[data-media-detail]'));
  if (detail) { await toggleMediaDetail(detail); return; }
  const play = /** @type {HTMLButtonElement|null} */ (target.closest('.video-play'));
  if (play) {
    const assetId = play.getAttribute('data-asset');
    const container = play.parentElement;
    if (assetId && container) await playFilm(assetId, container, play);
    return;
  }
  const download = /** @type {HTMLElement|null} */ (target.closest('[data-download]'));
  if (download) {
    event.preventDefault();
    const assetId = download.getAttribute('data-download');
    if (assetId) await downloadFilm(assetId);
    return;
  }
  const sheet = target.closest('.btn-shooting-sheet');
  if (sheet) {
    const id = sheet.getAttribute('data-id');
    if (id) void openShootingSheet(id);
    return;
  }
  // In PRODUCTION the studio answers 409 «Folosește foaia de filmare»: the button opens the sheet
  // instead, and from then on goes straight to it (shooting_sheet.js requestRender).
  const renderKey = /** @type {HTMLButtonElement|null} */ (target.closest('.btn-render-video'));
  if (renderKey) {
    const id = renderKey.getAttribute('data-id');
    if (!id) return;
    renderKey.textContent = 'Se randează…';
    renderKey.disabled = true;
    try {
      const answer = await requestRender(api, id, renderState, openShootingSheet);
      if (answer.opened) {
        renderKey.textContent = 'Randare 9:16';
        renderKey.disabled = false;
        return;
      }
      await loadMediaStoryboards();
      await refresh();
    } catch (err) {
      mediaStatus(`Randarea a eșuat: ${err.message}`, true);
      renderKey.textContent = 'Randare 9:16';
      renderKey.disabled = false;
    }
    return;
  }
  const qcButton = /** @type {HTMLButtonElement|null} */ (target.closest('.btn-qc-video'));
  if (qcButton) {
    const id = qcButton.getAttribute('data-id');
    if (!id) return;
    qcButton.textContent = 'Se evaluează QC…';
    qcButton.disabled = true;
    try {
      await api(`/media/qc/${id}`, { method: 'POST' });
      await loadMediaStoryboards();
      await refresh();
    } catch (err) {
      mediaStatus(`QC a eșuat: ${err.message}`, true);
      qcButton.textContent = 'Verifică QC';
      qcButton.disabled = false;
    }
  }
});
mediaModal.addEventListener('close', () => { filmUrls.revokeAll(); });

if (generateDemoStoryboardBtn) {
  generateDemoStoryboardBtn.addEventListener('click', async () => {
    mediaStatusMsg.hidden = false;
    mediaStatusMsg.className = 'dialog-status-msg';
    mediaStatusMsg.textContent =
      'Se creează cazul demo (subiect, scenariu și o afirmație neverificată)…';
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

doorReads.set('publishing-modal', () => { loadPublishingHub(); });
if (openPublishingBtn) {
  openPublishingBtn.addEventListener('click', () => {
    openDoor(publishingModal);
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
      // PAGE-05: a positive sum or nothing is sent; an empty field never retires the budget
      const built = budgetCommand({
        period: /** @type {HTMLSelectElement} */ (element('budget-period')).value,
        limit: /** @type {HTMLInputElement} */ (element('budget-limit')).value,
        status: worldFacts.budget,
        commandId: crypto.randomUUID(),
      });
      if ('error' in built) throw new Error(built.error);
      const result = await api('/economy/budget', { method: 'PUT', body: JSON.stringify(built.command) });
      status.textContent = result.active === false ? 'Bugetul a fost retras.' : `Buget ${result.period === 'DAILY' ? 'zilnic' : 'lunar'} de ${amount(result.limit_usd)} USD setat.`;
      await loadBudget();
    } catch (error) {
      status.className = 'dialog-status-msg text-error';
      status.textContent = error instanceof Error ? error.message : 'Bugetul nu a putut fi salvat.';
    }
  });
}
/** PAGE-05: «Retrage bugetul zilnic», its own key, asked first. */
document.getElementById('budget-retire')?.addEventListener('click', async () => {
  const status = element('budget-status');
  const yes = await confirmDialog({ question: 'Retragi bugetul zilnic?', words: RETIRE_QUESTION, yes: 'Da, retrage bugetul zilnic' });
  if (!yes) return;
  status.hidden = false;
  status.className = 'dialog-status-msg';
  try {
    const built = retireCommand({ period: 'DAILY', status: worldFacts.budget, commandId: crypto.randomUUID() });
    if ('error' in built) throw new Error(built.error);
    await api('/economy/budget', { method: 'PUT', body: JSON.stringify(built.command) });
    status.textContent = 'Bugetul zilnic a fost retras: nimic din buget nu mai oprește un film al zilei.';
    await loadBudget();
  } catch (error) {
    status.className = 'dialog-status-msg text-error';
    status.textContent = error instanceof Error ? error.message : 'Bugetul nu a putut fi retras.';
  }
});
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
        // Channels are connected from the page (OAuth), not by editing .env (PAGE-13).
        publisherBanner.textContent =
          'Niciun cont YouTube conectat: publicarea este oprită. Conectează contul canalului din Setări → Conturi și e-mail, apoi leagă-l de canal din Distribuție → Sloturi de canal. Studioul nu simulează niciodată publicarea.';
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
        <div class="channel-item" data-door-steps>
          <div class="channel-info" data-door-steps>
            <h4>${escapeHtml(c.channel_name)}</h4>
            <div class="channel-meta">Tip: <strong title="${escapeHtml(c.channel_type)}">${escapeHtml(channelTypeWord(c.channel_type))}</strong> · Canal YouTube: <span class="distribution-account" title="${escapeHtml(channelFacts(c).accountTitle)}">${escapeHtml(c.remote_channel_id ? (c.youtube_channel_title || 'nelegat') : 'nesetat')}</span></div>
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

    void loadPublishingGate();
    const publications = pubData.publications || [];
    if (publications.length === 0) {
      replaceActivityHtml(pubListEl, '<div class="topics-loading">Nicio publicare înregistrată. Folosește butonul de mai sus ca să publici un film aprobat.</div>');
    } else {
      replaceActivityHtml(pubListEl, publications
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
              ? `<a href="${escapeHtml(p.remote_url)}" target="_blank" rel="noopener" class="pub-remote-link"${p.remote_video_id ? ` title="${escapeHtml(`ID extern: ${p.remote_video_id}`)}"` : ''}>Vezi pe YouTube</a>`
              : isSimulated
                ? '<span class="pub-sim-note">Simulare locală — niciun video pe YouTube</span>'
                : '';
          // PAGE-10: private, unlisted and public are three words; an «unlisted» upload read «Public»
          const privacyBadge = privacyBadgeHtml(p.privacy_status, p.remote_privacy_status);

          return `
          <div class="pub-item-card">
            <div class="pub-item-details">
              <h4>${escapeHtml(p.title)}</h4>
              <div class="pub-item-meta">
                <span>Stare: <strong class="pub-status-badge ${isSimulated ? 'pub-status-simulated' : badgeClass}">${escapeHtml(isSimulated ? 'SIMULAT (nepublicat)' : publicationStatus(p.status))}</strong></span>
                ${privacyBadge}
                <span>Data: ${new Date(p.created_at).toLocaleString('ro-RO')}</span>
              </div>
              ${p.error_detail && p.status !== 'PUBLISHED' ? `<p class="claim-notes">${escapeHtml(p.error_detail)}</p>` : ''}
              ${resolveFormHtml(p)}
            </div>
            <div>
              ${remoteLink}
            </div>
          </div>
        `;
        })
        .join(''));
    }
  } catch (err) {
    if (channelsEl)
      channelsEl.innerHTML = `<div class="text-error">Canalele nu au putut fi încărcate: ${escapeHtml(err.message)}</div>`;
    if (pubListEl)
      replaceActivityHtml(pubListEl, `<div class="text-error">Publicările nu au putut fi încărcate: ${escapeHtml(err.message)}</div>`);
  }
}

/**
 * PAGE-10: the film quick publish would upload, chosen by the studio in one query (the newest
 * storyboard whose newest film passed QC), and the channel it goes to. Used by the gate card and
 * by the question «Publică privat» asks before anything is sent.
 * @returns {Promise<{asset: string, title: string, channel: any|null}|null>}
 */
async function quickPublishTarget() {
  const [films, chData] = await Promise.all([
    api('/media/storyboards?qc_status=PASSED&limit=1'),
    api('/publishing/channels'),
  ]);
  const film = (films.storyboards || [])[0];
  if (!film || !film.asset_id) return null;
  const channel = (chData.channels || []).find((/** @type {any} */ c) => c.channel_type === 'MAIN_FACTUAL') || null;
  return { asset: film.asset_id, title: film.title, channel };
}

/** The gate card: the backend's own evaluation of the film quick publish would send. */
async function loadPublishingGate() {
  const box = document.getElementById('pub-gate-checks');
  if (!box) return;
  try {
    const target = await quickPublishTarget();
    if (!target || !target.channel) { box.innerHTML = gateChecksHtml(null); return; }
    const evaluation = await api(`/publishing/gate/evaluate/${target.asset}/${target.channel.id}`);
    box.innerHTML = `<p class="pub-gate-note">Pentru «${escapeHtml(target.title)}» pe «${escapeHtml(target.channel.channel_name)}»:</p>${gateChecksHtml(evaluation)}`;
  } catch (err) {
    box.innerHTML = `<p class="text-error">Poarta de publicare nu a putut fi citită: ${escapeHtml(err.message)}</p>`;
  }
}

/** @param {string} text @param {boolean} [error] */
function publishingStatus(text, error = false) {
  publishingStatusMsg.hidden = !text;
  publishingStatusMsg.className = error ? 'dialog-status-msg text-error' : 'dialog-status-msg';
  publishingStatusMsg.textContent = text;
}

/** @param {any} pubRes the publication the studio answered with */
function quickPublishAnswer(pubRes) {
  if (pubRes.status === 'PUBLISHED') {
    publishingStatus(`Filmul a fost încărcat privat pe YouTube. ID extern: ${pubRes.remote_video_id}`);
  } else if (pubRes.status === 'PUBLISHED_SIMULATED') {
    publishingStatus('Încărcare SIMULATĂ: nu există niciun video pe YouTube. Configurează credențiale reale.', true);
  } else {
    publishingStatus(`Publicarea nu s-a încheiat. Stare: ${publicationStatus(pubRes.status)}. ${pubRes.error_detail || ''}`, true);
  }
}

if (triggerQuickPublishBtn) {
  // PAGE-10: the first press only asks, naming the film, the channel and the privacy; nothing is
  // uploaded until «Da, încarcă». The film is the studio's choice (one query), not the page's.
  triggerQuickPublishBtn.addEventListener('click', async () => {
    publishingStatus('Se caută cel mai nou film care a trecut QC…');
    const ask = element('quick-publish-confirm');
    ask.hidden = true;
    try {
      const target = await quickPublishTarget();
      if (!target) {
        publishingStatus('Nu s-a găsit niciun film care să fi trecut QC. Creează întâi un storyboard și o randare 9:16 în Producție media.', true);
        return;
      }
      if (!target.channel) {
        publishingStatus('Canalul A nu este configurat; nu există unde să se încarce filmul.', true);
        return;
      }
      publishingStatus('');
      ask.innerHTML = `<p class="owner-confirm-question">${escapeHtml(quickPublishQuestion({ title: target.title, channel: target.channel.channel_name, privacy: 'private' }))}</p>
        <div class="owner-confirm-keys">
          <button type="button" class="primary owner-confirm-yes" data-quick-publish-yes="${escapeHtml(target.asset)}">Da, încarcă</button>
          <button type="button" class="quiet" data-quick-publish-no>Nu acum</button>
        </div>
        <p class="decision-confirm-note">Până nu apeși Da, nu se încarcă nimic.</p>`;
      ask.hidden = false;
      /** @type {HTMLElement|null} */ (ask.querySelector('[data-quick-publish-yes]'))?.focus();
    } catch (err) {
      publishingStatus(`Eroare la publicare: ${err.message}`, true);
    }
  });
  element('quick-publish-confirm').addEventListener('click', async (event) => {
    const target = /** @type {HTMLElement} */ (event.target);
    const ask = element('quick-publish-confirm');
    if (target.closest('[data-quick-publish-no]')) {
      ask.hidden = true;
      triggerQuickPublishBtn.focus();
      return;
    }
    const yes = /** @type {HTMLButtonElement|null} */ (target.closest('[data-quick-publish-yes]'));
    if (!yes) return;
    const assetId = yes.dataset.quickPublishYes || '';
    ask.querySelectorAll('button').forEach((b) => { b.disabled = true; });
    publishingStatus('Verificarea porții de publicare și încărcarea privată…');
    try {
      quickPublishAnswer(await api(`/publishing/publish-asset/${assetId}`, { method: 'POST', timeoutMs: 600000 }));
      ask.hidden = true;
      await loadPublishingHub();
      await refresh();
    } catch (err) {
      ask.hidden = true;
      publishingStatus(`Eroare la publicare: ${err.message}`, true);
    }
  });
}

/**
 * PUB-12: a publication the studio could not settle (NEEDS_RECONCILIATION, REMOTE_UNKNOWN) is
 * settled by his answer: «Există», with the video's id or link, or «Nu există». Each answer
 * carries its own command id; the backend refuses a state it cannot settle in its own words.
 * @param {any} p
 */
function resolveFormHtml(p) {
  if (!RESOLVABLE_STATES.includes(p.status)) return '';
  const id = escapeHtml(p.id);
  return `<div class="pub-resolve" data-resolve-box="${id}">
      <p class="helper">Studioul nu știe sigur dacă filmul a ajuns pe canal. Uită-te pe YouTube Studio și spune-i ce ai găsit.</p>
      <label for="resolve-video-${id}">ID-ul sau linkul videoclipului găsit</label>
      <input id="resolve-video-${id}" type="text" autocomplete="off" spellcheck="false" placeholder="https://www.youtube.com/shorts/…">
      <div class="owner-confirm-keys">
        <button type="button" class="secondary" data-resolve-found="${id}">Există</button>
        <button type="button" class="quiet" data-resolve-missing="${id}">Nu există</button>
      </div>
      <p class="owner-answer" role="status" data-resolve-answer="${id}"></p>
    </div>`;
}

element('publications-list').addEventListener('click', async (event) => {
  const target = /** @type {HTMLElement} */ (event.target);
  const found = /** @type {HTMLElement|null} */ (target.closest('[data-resolve-found]'));
  const missing = /** @type {HTMLElement|null} */ (target.closest('[data-resolve-missing]'));
  if (!found && !missing) return;
  const id = String((found || missing)?.dataset.resolveFound || (found || missing)?.dataset.resolveMissing || '');
  const box = document.querySelector(`[data-resolve-box="${id}"]`);
  const said = document.querySelector(`[data-resolve-answer="${id}"]`);
  const video = /** @type {HTMLInputElement|null} */ (document.getElementById(`resolve-video-${id}`));
  const built = resolvePublicationCommand({ found: Boolean(found), video: video ? video.value : '', commandId: crypto.randomUUID() });
  if ('error' in built) { if (said) { said.textContent = built.error; said.classList.add('settings-error'); } return; }
  box?.querySelectorAll('button, input').forEach((el) => { /** @type {HTMLButtonElement} */ (el).disabled = true; });
  try {
    const answer = await api(`/publishing/publications/${id}/resolve`, { method: 'POST', body: JSON.stringify(built.command) });
    publishingStatus(`Răspunsul tău a fost înregistrat: ${publicationStatus(answer.status)}.`);
    await loadPublishingHub();
  } catch (err) {
    if (said) { said.textContent = err.message; said.classList.add('settings-error'); }
    box?.querySelectorAll('button, input').forEach((el) => { /** @type {HTMLButtonElement} */ (el).disabled = false; });
  }
});

function render(data) {
  element('studio-name').textContent = data.studio.name;
  // The clock, the sun, the street and the labels follow the studio's own place (SELL-08):
  // the snapshot serves it from the settings; Bucharest is only the fallback.
  setStudioPlace({ ...(data.studio.location || {}), timezone: data.studio.timezone, studioName: data.studio.name });
  renderDemoBanner(data.demo);
  // PAGE-01 and REL-07: the page older than the studio, and what keeps the studio running
  renderPageBanners(data);
  // PAGE-04: his rule for the paid steps, under the mode it combines with
  renderGovernanceRule();
  // PAGE-09: the demo case writes a topic of its own (status DEMO); offered only in TEST
  if (generateDemoStoryboardBtn) generateDemoStoryboardBtn.hidden = !demoCaseShown(data.policy);
  // The masthead chip and the slate caption say «live» only while it is (live_claims.js).
  renderLiveSignals();
  element('snapshot-time').textContent =
    `Actualizat ${new Date(data.captured_at).toLocaleTimeString('ro-RO', { timeZone: data.studio.timezone })}`;
  renderSwitch(data.policy.autonomy_stopped);
  renderEnvironment(data.policy.environment);
  pushWorldFacts();
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

  // W34: the module list (a developer's checklist, judged NO at full weight on the main screen) is
  // kept for Setări → Despre studio, with the words and meters it had (settings.js renderAbout)
  latestModules = data.modules && typeof data.modules === 'object' ? data.modules : null;
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
    // A periodic authoritative read repairs missed events and discovers staff hired elsewhere.
    if (officeEngine && Date.now() - officeLastRead > 15000) await loadOfficeLayout({ characters: false });
    // Everything recorded since the ledger last looked, not only the twenty in the snapshot.
    // the name tags' last tasks: the studio's own record of runs rides this snapshot (W12)
    refreshLastTasks();
    try {
      await ledger.sync(api, state.cursor);
      element('ledger-count').textContent = entryCountLabel(ledger.events.size);
      if (worldFacts.reads.ledger !== 'ok') {
        worldFacts.reads.ledger = 'ok';
        pushWorldFacts();
      }
    } catch (error) {
      console.warn('ledger sync failed', error);
      if (!ledger.events.size && worldFacts.reads.ledger !== 'failed') {
        readFailed('ledger');
        pushWorldFacts();
      }
    }
    // The approvals have their own, slower clock; this only lets them ride the same poll.
    await loadApprovals();
    await loadOwnerLetters();
    decisions.refreshCount();
    return true;
  } catch (error) {
    if (generation !== epoch) return false;
    connected = false;
    liveSignals.data = 'stale';
    renderLiveSignals();
    stopButton.disabled = true;
    notify(error.message);
    // LOCAL_AUTO_LOGIN: a key the studio no longer accepts (a new key in .env, then a restart)
    // takes the page back to the title, and this machine may hand the new key over: once per
    // page load (local_entry.js), never in a loop.
    if (error && /** @type {any} */ (error).status === 401 && !workspace.hidden) {
      signOut();
      notify(error.message);
      void localEntry.afterRefusal();
    }
    return false;
  }
}

/**
 * LOCAL_AUTO_LOGIN (2026-10-08, the Owner: «Te rog sa elimini pagina de logare, nu trebuie
 * momentan»). On his own machine the studio hands the page his key and it enters without the form;
 * from anywhere else the form shows as before. The key stays only in this page's memory.
 */
const loginForm = element('login-form');
const loginWait = element('login-wait');
const loginLocal = element('login-local');
const localEntry = new LocalEntry({
  ask: () => askLocalKey(),
  enter: (key) => enterStudio(key),
  view: {
    waiting: () => {
      loginForm.hidden = true;
      loginWait.hidden = false;
    },
    form: (offer) => {
      loginWait.hidden = true;
      loginForm.hidden = false;
      // offered: an empty field and «Intră în studio» enter with the key this machine hands over
      loginLocal.hidden = !offer;
      input.required = !offer;
    },
  },
});

element('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!input.value && localEntry.available) {
    await localEntry.again();
    return;
  }
  await enterStudio(input.value);
});

/**
 * The page's one way in: the key typed in the form, or the one this machine handed over
 * (local_entry.js). Resolves true when the studio accepted it and the workspace is up.
 * @param {string} key
 * @returns {Promise<boolean>}
 */
async function enterStudio(key) {
  if (busy) return false;
  busy = true;
  ownerToken = key;
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
    const plays = false;
    workspace.hidden = false;
    element('logout').hidden = false;
    decisions.signedIn();
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
        titleScreen.enter(titleLanding).then((finished) => { if (finished && ownerToken) login.hidden = true; });
      }));
    } else {
      login.hidden = true;
      titleScreen.hide();
    }
    initOffice();
    // The key light's first reading copies a frame back from the GPU (18ms measured at the key);
    // it waits until the building has been entered, and then reads the frame the visitor sees.
    // W15: the invitation to the replay waits for the entry to settle
    if (replayInvite) replayInvite.entered(plays ? ENTRY.totalMs : 0);
    // The faces' first values are the page arriving, not news: no glint for them (hq_readouts.js).
    if (officeEngine) officeEngine.resetGlints();
    loadDayRecord();
    loadWorldFigures();
    loadSerialFacts();
    await loadOfficeLayout();
    await connectWebSocket();
  } else {
    ownerToken = '';
  }
  busy = false;
  stopButton.disabled = !connected;
  return success;
}

/**
 * W22: where the workspace shows the world (and the stream's video, to the pixel), for the title's
 * kept frame to land on. Null before the engine has a camera.
 */
function titleLanding() {
  if (!officeEngine) return null;
  try {
    return landingPlacement(officeCanvas.getBoundingClientRect(), officeEngine.view());
  } catch {
    return null;
  }
}

element('logout').addEventListener('click', () => {
  signOut();
  // LOCAL_AUTO_LOGIN: the form shows, offering to enter again without the key on this machine
  localEntry.offer();
});

/** Leaves the studio: the workspace closes and the title (with the form) is shown again. */
function signOut() {
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
  // the next key may meet another backend: it is asked again how its sockets take the key
  liveSignals.data = 'fresh';
  if (officeEngine) officeEngine.park();
  document.body.classList.remove('is-arming');
  workspace.hidden = true;
  login.hidden = false;
  titleScreen.show();
  // W22: the frame kept during this visit is the title's now; W24: or the studio's, by the hour's light
  input.value = '';
  notify('');
  ledger.clear();
  if (replay) replay.reset();
  if (replayInvite) replayInvite.reset();
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
  latestModules = null;
  element('studio-name').textContent = 'AMN-AI';
  element('connection').textContent = 'Neconectat';
  element('logout').hidden = true;
  decisions.reset();
}

environmentButton.addEventListener('click', async () => {
  if (busy || !connected || !state) return;
  const next = state.policy.environment === 'TEST' ? 'PRODUCTION' : 'TEST';
  // PAGE-08: PRODUCTION is where the paid vendors are bought from; back to TEST asks nothing.
  if (!(await askConsequence({ environment: next }))) return;
  if (busy || !connected || !state) return;
  busy = true;
  environmentButton.disabled = true;
  notify('');
  const generation = epoch;
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
  // PAGE-08: a promotion lets the studio do more alone; he reads what the next run will do and
  // says yes first. Lowering the mode asks nothing (consequenceWords answers null).
  if (!(await askConsequence({ mode }))) return;
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

/** PAGE-03: the T3/T4 request whose «Aprobă» opened its question, or null. */
let approvalConfirming = /** @type {string|null} */ (null);

/** @param {ReturnType<typeof readApprovals>[number]} request @param {number} now */
function approvalCard(request, now) {
  // Beside the figure and not under it in the evidence line: the Owner answers the number, so
  // a figure that priced only part of the film has to say so where the number is read.
  return approvalCardHtml(request, {
    now,
    escape: escapeHtml,
    caveat: approvalCaveat(request.evidence),
    tierMeaning: riskTierMeaning(request.risk_tier || '—'),
    person: requesterPerson(request.requester, officeState.agents),
    confirming: approvalConfirming === request.id,
  });
}

/** The pending requests last read, drawn again when the office's record arrives (who asked). @type {ReturnType<typeof readApprovals>} */
let approvalsShown = [];
function renderApprovals() {
  replaceActivityHtml(approvalsList, approvalsShown.length
    ? `${newestFirst(approvalsShown).map((request) => approvalCard(request, Date.now())).join('')}<p class="approval-footnote">${escapeHtml(APPROVAL_FOOTNOTE)}</p>`
    : '<div class="topics-loading">Nicio cerere nu așteaptă decizia Proprietarului.</div>');
  // who asked, at their desk: the scene's own portrait (roster.js)
  if (approvalsShown.length) drawPortraits(approvalsList);
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
    approvalsShown = pending;
    renderApprovals();
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
  const id = button.dataset.id || '';
  const decision = button.dataset.decision || '';
  // PAGE-03: a T3/T4 «Aprobă» only opens its question; «Nu acum» closes it. Nothing is sent.
  if (decision === 'CONFIRM' || decision === 'CANCEL') {
    approvalConfirming = decision === 'CONFIRM' ? id : null;
    renderApprovals();
    if (approvalConfirming) /** @type {HTMLTextAreaElement|null} */ (approvalsList.querySelector('[data-approval-note]'))?.focus();
    return;
  }
  const note = /** @type {HTMLTextAreaElement|null} */ (card?.querySelector('[data-approval-note]'))?.value.trim() || undefined;
  card?.querySelectorAll('button').forEach((node) => {
    /** @type {HTMLButtonElement} */ (node).disabled = true;
  });
  busy = true;
  const generation = epoch;
  try {
    const command = approvalDecisionCommand(id, decision, crypto.randomUUID(), note);
    approvalConfirming = null;
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

/**
 * W30, THE EMPLOYEES AS PEOPLE (roster.js). The last measurements read, and the key of the cards
 * shown: the roster is laid out again only when a card would say something else (a state, a
 * standing, a task), from the socket's events, never per frame.
 * @type {any}
 */
let rosterMeasured = null;
let rosterShownKey = '';
/** The size of a portrait's canvas, device px: the world window at six px per world px (three per
 * plate px), so the largest portrait (192 CSS px at 2560) is drawn down, never up. */
const PORTRAIT_PX = { w: 264, h: 198 };

/** @param {boolean} [force] */
function renderRoster(force) {
  if (!rosterMeasured) return;
  const box = element('workforce-agents');
  const cards = rosterCards({
    measurements: rosterMeasured,
    office: officeState.agents,
    tasks: worldFacts.tasks.tasks,
    manifest: officeEngine && officeEngine.assets ? officeEngine.assets.manifest : null,
    now: Date.now(),
  });
  const key = rosterKey(cards);
  if (!force && key === rosterShownKey) return;
  rosterShownKey = key;
  box.classList.add('roster');
  box.innerHTML = rosterHtml(cards, escapeHtml);
  applyMeters(box);
  drawPortraits(box);
}

/** Each portrait, from the scene's own plates and figure (hq_world.js drawPortrait); dark when none. @param {ParentNode} root */
function drawPortraits(root) {
  for (const slot of /** @type {HTMLElement[]} */ (Array.from(root.querySelectorAll('[data-portrait]')))) {
    const id = slot.dataset.portrait;
    paintPortrait(slot, officeState.agents.find((a) => (a.id || a.agent_id) === id) || null);
  }
}

/**
 * W32: the real picture of the Unreal building the page holds while the stream is what is seen
 * (the video's frame copied every 2 s, a frozen or held frame, or an earlier visit's kept frame on
 * the starting plate); null while the page's own renderer is what is seen.
 * @returns {{image: HTMLCanvasElement, at: number}|null}
 */
/** @param {HTMLElement} slot @param {any} agent */
function paintPortrait(slot, agent) {
  const renderer = officeEngine && officeEngine.renderer;
  const canvas = /** @type {HTMLCanvasElement|null} */ (slot.querySelector('canvas'));
  let drawn = false;
  if (renderer && agent && canvas) {
    canvas.width = PORTRAIT_PX.w;
    canvas.height = PORTRAIT_PX.h;
    const ctx = canvas.getContext('2d');
    if (ctx) drawn = renderer.drawPortrait(ctx, agent);
  }
  slot.classList.toggle('is-empty', !drawn);
  slot.dataset.source = drawn ? 'pixel' : '';
}

/** The roster follows the office's record while its door is open. */
function rosterMayChange() {
  // by id: the socket's first events can arrive before this part of the module has run
  const door = /** @type {HTMLDialogElement|null} */ (document.getElementById('workforce-modal'));
  if (door && door.open) renderRoster(false);
}

/**
 * A card opens that employee's inspector through its own door: the roster goes back into the
 * lobby, and the inspector grows out of the desk, the employee chosen in the building as a click
 * on the desk would choose them. An employee with no desk opens the inspector from the card.
 * @param {string} id
 */
function openPerson(id) {
  const seated = officeState.agents.find((a) => (a.id || a.agent_id) === id);
  const measured = rosterMeasured && Array.isArray(rosterMeasured.agents) ? rosterMeasured.agents.find((/** @type {any} */ a) => a.agent_id === id) : null;
  const agent = seated || (measured ? { ...measured, id } : null);
  if (!agent) return;
  if (seated) workforceModal.close();
  currentSelectedAgent = agent;
  inspectorFromRoster = true;
  if (officeEngine) officeEngine.setSelectedAgent(id);
  showInspector(agent);
}
let inspectorFromRoster = false;

async function loadWorkforce() {
  const summaryEl = element('workforce-summary');
  try {
    const data = await api('/workforce/measurements');
    summaryEl.innerHTML = `
      <div class="wf-stat"><span class="wf-stat-value">${data.active_agents}</span><span class="wf-stat-label">angajați activi</span></div>
      <div class="wf-stat"><span class="wf-stat-value">${data.queue_backlog}</span><span class="wf-stat-label">sarcini în coadă</span></div>
      <div class="wf-stat"><span class="wf-stat-value">${data.dead_letter_tasks}</span><span class="wf-stat-label">sarcini abandonate</span></div>
      <div class="wf-stat"><span class="wf-stat-value">${data.idle_agents.length}</span><span class="wf-stat-label">fără nicio rulare</span></div>`;
    summaryEl.insertAdjacentHTML(
      'beforeend',
      `<p class="helper-note wf-window">Măsurat pe ${Number(data.window_days) === 1 ? 'ultima zi' : `ultimele ${countWords(data.window_days, 'zi', 'zile')}`}, din rulările înregistrate.</p>`,
    );

    rosterMeasured = data;
    renderRoster(true);
  } catch (err) {
    summaryEl.innerHTML = `<div class="text-error">${escapeHtml(err.message)}</div>`;
  }
}

async function loadProposals() {
  const listEl = element('workforce-proposals');
  try {
    const data = await api('/workforce/proposals');
    const proposals = newestFirst(data.proposals || []);
    if (!proposals.length) {
      replaceActivityHtml(listEl, '<div class="topics-loading">Nicio propunere. Măsurătorile nu susțin acum o schimbare de personal.</div>');
      return;
    }
    replaceActivityHtml(listEl, proposals.map(renderProposal).join(''));
    listEl.querySelectorAll('.btn-decide').forEach((btn) => {
      /** @type {HTMLElement} */ (btn).onclick = () => decideProposal(btn);
    });
  } catch (err) {
    replaceActivityHtml(listEl, `<div class="text-error">${escapeHtml(err.message)}</div>`);
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

doorReads.set('workforce-modal', () => { loadWorkforce(); loadProposals(); });
element('workforce-agents').addEventListener('click', (event) => {
  const card = event.target instanceof Element ? event.target.closest('.person-card') : null;
  if (card instanceof HTMLElement && card.dataset.agent) openPerson(card.dataset.agent);
});
// back from an employee opened from the roster, the keyboard stands on the door he came by
inspector.addEventListener('close', () => {
  if (!inspectorFromRoster || inspector.open) return;
  inspectorFromRoster = false;
  if (openWorkforceBtn && document.activeElement === document.body) openWorkforceBtn.focus({ preventScroll: true });
});
if (openWorkforceBtn) {
  openWorkforceBtn.addEventListener('click', () => {
    openDoor(workforceModal);
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

/** Real USD cost limits and autonomy configuration. */

const autonomyModal = /** @type {HTMLDialogElement} */ (element('autonomy-modal'));

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
  return `<div class="budget-card budget-ring-card budget-${escapeHtml(period.state)}"><div class="budget-ring-words"><span class="stat-label" title="${escapeHtml(period.state)}">${escapeHtml(label)} · ${escapeHtml(budgetStateWord(period.state))}</span><strong>${escapeHtml(amount(period.spent_usd))} / ${escapeHtml(amount(period.limit_usd))} USD</strong><span>rămân ${escapeHtml(amount(period.remaining_usd))} USD · ${Math.round(period.ratio * 100)}%</span>${reserved}${period.unpriced_agent_runs ? `<div class="helper">${period.unpriced_agent_runs} rulări fără preț înregistrat</div>` : ''}</div>${budgetRingSvg(period, ringLabel)}</div>`;
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
    const providers = data.month.by_provider.map((p) => `<div class="budget-card"><span class="stat-label budget-vendor">${escapeHtml(providerName(p.provider))}</span><strong>${escapeHtml(amount(((p.estimated_usd_micros + p.billed_usd_micros) / 1e6).toFixed(2)))} USD</strong><span>${countLabel(p.records, 'înregistrare', 'înregistrări')} · facturat ${escapeHtml(amount((p.billed_usd_micros / 1e6).toFixed(2)))}</span></div>`).join('');
    cards.innerHTML = spend + (data.budgets.length ? data.budgets.map(budgetCard).join('') : '<div class="budget-card"><span class="stat-label">Buget</span><strong>nesetat</strong><span>Setează limita zilnică; pașii plătiți urmează politica și plafoanele tale.</span></div>') + providers;
  } catch (error) {
    cards.innerHTML = `<div class="text-error">${escapeHtml(error instanceof Error ? error.message : 'Bugetul nu a putut fi citit.')}</div>`;
  }
}

/**
 * W34, Autonomie → Prețurile modelelor: a price per million tokens, read and written, for each
 * model the preflight found without one and each the books price per token (owner_controls.js).
 * The Owner types it; the page never proposes a figure.
 * W36: one plate per model, with its provider's mark, its state, the two fields and its key; a plate
 * per provider for the backend's «*» (every model of it without a price of its own); and a model the
 * preflight does not name can be put in the list, if the studio knows it (GET /settings).
 */
let priceRows = /** @type {import('./owner_controls.js').PriceRow[]} */ ([]);
/** The last answer, said in the row it answers (the list is drawn again after a save). */
let priceSaid = /** @type {{key: string, text: string, error: boolean}|null} */ (null);
/**
 * W36: the models listed this visit: the ones the Owner put in the list (checkNewModel) and the ones
 * the preflight named. A model stays where it was when a provider's price then covers it and the
 * recomputed preflight stops naming it (the W35 rule: nothing moves under his hand).
 */
const priceAdded = /** @type {{kind: string, model: string}[]} */ ([]);
/** W36: the models the studio knows, from the last read of /settings; null when it could not be read. */
let priceKnown = /** @type {{kind: string, model: string, available: boolean}[]|null} */ (null);
/** W36: what the add form last said, kept across the list's redraw. */
let priceAddSaid = /** @type {{text: string, error: boolean}|null} */ (null);
const priceKey = (/** @type {{kind: string, model: string}} */ r) => `${r.kind}\u0000${r.model}`;
/** The same key as an attribute can carry it (no NUL: a kind never holds a colon, so the first one splits it). */
const priceDomKey = (/** @type {{kind: string, model: string}} */ r) => `${r.kind}:${r.model}`;

/** A provider's mark: its first letter on the page's hexagon (owner_controls.js providerMark). @param {string} kind */
function providerMarkHtml(kind) {
  const m = providerMark(kind);
  return `<span class="provider-mark" data-tone="${m.tone}" aria-hidden="true">${icon('hexagon')}<span class="provider-mark-letter">${escapeHtml(m.letter)}</span></span>`;
}

async function loadPrices(preflightRead = null) {
  const list = element('prices-list');
  element('prices-meaning').textContent = PRICES_MEANING;
  const [preflight, prices, settings] = await Promise.allSettled([preflightRead || api('/runbook/preflight'), api('/economy/prices'), api('/settings')]);
  if (prices.status === 'rejected') {
    list.innerHTML = `<div class="text-error">${escapeHtml(prices.reason instanceof Error ? prices.reason.message : 'Prețurile nu au putut fi citite.')}</div>`;
    return;
  }
  const read = preflight.status === 'fulfilled' ? preflight.value : null;
  priceKnown = settings.status === 'fulfilled' ? knownModels(settings.value) : null;
  const books = prices.value && prices.value.prices;
  const models = tokenPriceRows(read, books, priceAdded);
  for (const r of models) if (!priceAdded.some((a) => a.kind === r.kind && a.model === r.model)) priceAdded.push({ kind: r.kind, model: r.model });
  const kinds = [...new Set([...(priceKnown || []).map((k) => k.kind), ...models.map((r) => r.kind)])];
  const wide = providerWideRows(books, kinds);
  priceRows = [...wide, ...models];
  const wideOf = new Map(wide.map((r) => [r.kind, r]));
  const line = read && Array.isArray(read.checks) ? read.checks.find((/** @type {any} */ c) => c && c.name === 'model_prices') : null;
  const source = !read
    ? '<p class="helper-note prices-source">—<br>Verificarea preliminară nu a putut fi citită.</p>'
    : line && line.ok
      ? '<p class="helper-note prices-source">Toate modelele pe care rulează angajații au preț pe tokenuri.</p>'
      : '<p class="helper-note prices-source">Modelele fără preț sunt cele pe care verificarea preliminară a zilei le-a găsit fără preț.</p>';
  const field = (/** @type {number} */ i, /** @type {'input'|'output'} */ side, /** @type {any} */ now) => `
      <label class="price-field"><span class="price-field-label">${side === 'input' ? 'Intrare' : 'Ieșire'} · USD / 1M tokenuri</span>
        <span class="price-well"><span class="price-unit" aria-hidden="true">USD</span><input class="dialog-input" name="${side}" inputmode="decimal" autocomplete="off" spellcheck="false" maxlength="20" value="${now ? escapeHtml(usdWords(now.usd_micros)) : ''}" aria-describedby="price-error-${i}" /></span></label>`;
  const plate = (/** @type {import('./owner_controls.js').PriceRow} */ row, /** @type {number} */ i) => {
    const version = Math.max(row.input ? row.input.version : 0, row.output ? row.output.version : 0);
    const provider = providerName(row.kind);
    const name = row.wide
      ? `<strong class="price-name">Toate modelele ${escapeHtml(provider)}</strong>`
      : `<strong class="price-name" lang="en">${escapeHtml(row.model)}</strong>`;
    const note = row.wide ? `<span class="price-note">Îl ia orice model ${escapeHtml(provider)} fără un preț al lui; un model cu prețul lui îl păstrează pe al lui.</span>` : '';
    // a model with no price of its own, costed by its provider's «*» (backend prices.price_row)
    const covered = !row.wide && !row.priced && Boolean(wideOf.get(row.kind)?.priced);
    const state = row.priced
      ? `<span class="price-state" data-tone="ok">preț pus · versiunea ${version}</span>`
      : covered
        ? '<span class="price-state" data-tone="info">ia prețul furnizorului</span>'
        : '<span class="price-state" data-tone="warn">fără preț</span>';
    return `
    <form class="price-row price-plate${row.wide ? ' is-wide' : ''}${row.priced ? ' is-priced' : ''}${covered ? ' is-covered' : ''}" data-row="${i}" data-key="${escapeHtml(priceDomKey(row))}"${row.wide ? ' title="Prețul cu resursa «*» pentru tot furnizorul"' : ''} novalidate>
      ${providerMarkHtml(row.kind)}
      <div class="price-model"><span class="price-provider" lang="en">${escapeHtml(provider)}</span>${name}
        ${state}${note}</div>
      ${field(i, 'input', row.input)}
      ${field(i, 'output', row.output)}
      <button type="submit" class="secondary price-save">Salvează prețul</button>
      <p class="price-error" id="price-error-${i}" role="alert" hidden></p>
      ${priceSaid && priceSaid.key === priceKey(row) ? `<p class="price-answer${priceSaid.error ? ' is-error' : ''}" role="status">${escapeHtml(priceSaid.text)}</p>` : ''}
    </form>`;
  };
  const groups = [];
  if (wide.length) groups.push(`<h4 class="prices-group">Pentru tot furnizorul</h4>${wide.map((r, i) => plate(r, i)).join('')}`);
  if (models.length) groups.push(`<h4 class="prices-group">Pe model</h4>${models.map((r, i) => plate(r, wide.length + i)).join('')}`);
  // the add form keeps what was being typed across the redraw that a save makes
  const was = /** @type {HTMLFormElement|null} */ (list.querySelector('form.price-add'));
  const wasKind = was ? /** @type {HTMLSelectElement} */ (was.elements.namedItem('kind')).value : '';
  const wasModel = was ? /** @type {HTMLInputElement} */ (was.elements.namedItem('model')).value : '';
  let add = '';
  if (!priceKnown) {
    add = '<p class="helper-note prices-known-missing">Lista modelelor studioului nu a putut fi citită; poți pune prețuri doar modelelor de mai sus.</p>';
  } else if (priceKnown.length) {
    const addKinds = [...new Set(priceKnown.map((k) => k.kind))];
    const kindNow = addKinds.includes(wasKind) ? wasKind : addKinds[0];
    const listed = new Set(models.map(priceKey));
    add = `
    <form class="price-add" novalidate>
      <h4 class="prices-group">Adaugă un model</h4>
      <p class="helper-note">Pune în listă un model pe care studioul îl cunoaște. Prețul se salvează abia când apeși Salvează prețul.</p>
      <div class="price-add-row">
        <label class="price-field"><span class="price-field-label">Furnizor</span>
          <select class="dialog-input" name="kind">${addKinds.map((k) => `<option value="${escapeHtml(k)}"${k === kindNow ? ' selected' : ''}>${escapeHtml(providerName(k))}</option>`).join('')}</select></label>
        <label class="price-field price-add-model"><span class="price-field-label">Model</span>
          <input class="dialog-input" name="model" list="price-known-models" autocomplete="off" spellcheck="false" maxlength="200" value="${escapeHtml(wasModel)}" aria-describedby="price-add-said" /></label>
        <button type="submit" class="secondary price-add-key">Adaugă în listă</button>
      </div>
      <datalist id="price-known-models">${priceKnown.filter((k) => k.kind === kindNow && !listed.has(priceKey(k))).map((k) => `<option value="${escapeHtml(k.model)}"></option>`).join('')}</datalist>
      <p class="price-add-said${priceAddSaid && priceAddSaid.error ? ' is-error' : ''}" id="price-add-said" role="status"${priceAddSaid ? '' : ' hidden'}>${priceAddSaid ? escapeHtml(priceAddSaid.text) : ''}</p>
    </form>`;
  }
  list.innerHTML = source + groups.join('') + add;
}
element('prices-list').addEventListener('change', (event) => {
  // the provider picked in the add form: its own models are the ones suggested
  const select = /** @type {HTMLElement} */ (event.target);
  if (!(select instanceof HTMLSelectElement) || select.name !== 'kind' || !priceKnown) return;
  const listed = new Set(priceRows.filter((r) => !r.wide).map(priceKey));
  const options = priceKnown.filter((k) => k.kind === select.value && !listed.has(priceKey(k)));
  const datalist = element('price-known-models');
  datalist.replaceChildren(...options.map((k) => new Option('', k.model)));
});
element('prices-list').addEventListener('submit', async (event) => {
  event.preventDefault();
  const adding = /** @type {HTMLFormElement|null} */ (/** @type {HTMLElement} */ (event.target).closest('form.price-add'));
  if (adding) {
    const kind = /** @type {HTMLSelectElement} */ (adding.elements.namedItem('kind')).value;
    const input = /** @type {HTMLInputElement} */ (adding.elements.namedItem('model'));
    const checked = checkNewModel(kind, input.value, priceKnown || [], priceRows.filter((r) => !r.wide));
    if (!checked.ok) {
      const said = element('price-add-said');
      priceAddSaid = { text: /** @type {any} */ (checked).error, error: true };
      said.textContent = priceAddSaid.text;
      said.classList.add('is-error');
      said.hidden = false;
      input.setAttribute('aria-invalid', 'true');
      input.focus();
      return;
    }
    priceAdded.push(/** @type {any} */ (checked).row);
    priceAddSaid = null;
    input.value = '';
    await loadPrices();
    const key = priceDomKey(/** @type {any} */ (checked).row);
    const row = /** @type {HTMLElement|null} */ (Array.from(element('prices-list').querySelectorAll('form.price-row')).find((f) => /** @type {HTMLElement} */ (f).dataset.key === key) || null);
    row?.scrollIntoView({ block: 'nearest' });
    /** @type {HTMLInputElement|null} */ (row?.querySelector('input[name="input"]') || null)?.focus();
    return;
  }
  const form = /** @type {HTMLFormElement} */ (/** @type {HTMLElement} */ (event.target).closest('form.price-row'));
  if (!form) return;
  const row = priceRows[Number(form.dataset.row)];
  if (!row) return;
  const status = element('prices-status');
  const error = /** @type {HTMLElement} */ (form.querySelector('.price-error'));
  const inputs = /** @type {HTMLInputElement[]} */ (Array.from(form.querySelectorAll('input')));
  const [inEl, outEl] = inputs;
  for (const el of inputs) el.removeAttribute('aria-invalid');
  error.hidden = true;
  const refuse = (/** @type {string} */ words, /** @type {HTMLInputElement[]} */ bad) => {
    error.textContent = words;
    error.hidden = false;
    for (const el of bad) el.setAttribute('aria-invalid', 'true');
    bad[0]?.focus();
  };
  const empty = inputs.filter((el) => !el.value.trim());
  if (empty.length) { refuse(PRICE_BOTH, empty); return; }
  const a = priceInput(inEl.value);
  const b = priceInput(outEl.value);
  if (!a.ok || !b.ok) {
    refuse(/** @type {any} */ (!a.ok ? a : b).error, [!a.ok ? inEl : null, !b.ok ? outEl : null].filter(/** @returns {el is HTMLInputElement} */ (el) => Boolean(el)));
    return;
  }
  const save = /** @type {HTMLButtonElement} */ (form.querySelector('.price-save'));
  save.disabled = true;
  status.hidden = true;
  const key = priceKey(row);
  save.textContent = 'Se salvează…';
  const [cin, cout] = priceCommands(row, a.usd, b.usd, [crypto.randomUUID(), crypto.randomUUID()]);
  const said = (/** @type {any} */ e) => (e && e.status === 422 ? 'Studioul a refuzat valorile trimise; verifică prețurile și încearcă din nou.' : e instanceof Error ? e.message : String(e));
  let first;
  try {
    first = await api('/economy/prices', { method: 'PUT', body: JSON.stringify(cin) });
  } catch (e) {
    priceSaid = { key, text: said(e), error: true };
    await loadPrices();
    return;
  }
  try {
    const second = await api('/economy/prices', { method: 'PUT', body: JSON.stringify(cout) });
    const readable = first && second && Number.isFinite(Number(first.usd_micros)) && Number.isFinite(Number(second.usd_micros));
    priceSaid = readable
      ? { key, text: priceAnswer(row, first, second), error: false }
      : { key, text: 'Studioul nu a trimis un răspuns pe care pagina să-l poată citi. Reîncarcă și verifică prețurile.', error: true };
  } catch (e) {
    priceSaid = { key, text: `Prețul de intrare s-a salvat (versiunea ${Number(first && first.version) || 1}); cel de ieșire nu: ${said(e)}`, error: true };
  }
  await loadPrices();
  /** @type {HTMLElement|null} */ (element('prices-list').querySelector('.price-answer'))?.scrollIntoView({ block: 'nearest' });
});

async function loadAutonomy() {
  const preflight = api('/runbook/preflight');
  await Promise.all([loadBudget(), loadPrices(preflight), loadAutonomyOverview(preflight)]);
}
async function loadAutonomyOverview(preflightRead) {
  const host = element('autonomy-overview');
  try {
    const data = await preflightRead;
    const checks = checklistHtml(preflightChecklist(data), escapeHtml);
    host.innerHTML = autonomyOverview(state, worldFacts.jobs, escapeHtml)
      + `<details class="autonomy-checks"><summary>Verificări și ce mai trebuie configurat</summary>${checks}</details>`;
  } catch (error) {
    host.textContent = error instanceof Error ? error.message : 'Setările nu au putut fi citite.';
  }
}
doorReads.set('autonomy-modal', () => { void loadAutonomy(); });
element('open-autonomy-btn').addEventListener('click', () => { openDoor(autonomyModal); });
element('close-autonomy-btn').addEventListener('click', () => autonomyModal.close());
element('refresh-autonomy-btn').addEventListener('click', () => { void loadAutonomy(); });
bindPanelToggle('open-autonomy-btn', autonomyModal);

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
    const logs = newestFirst(data.logs || []);
    if (!logs.length) {
      replaceActivityHtml(listEl, '<div class="topics-loading">Nicio zi închisă. Închide ziua ca să se numere ce s-a întâmplat.</div>');
      return;
    }
    replaceActivityHtml(listEl, logs
      .map(
        (log) => `
        <div data-card-key="${escapeHtml(log.id)}" class="topic-card story-log-card" data-log-id="${escapeHtml(log.id)}">
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
      .join(''));
    listEl.querySelectorAll('.btn-write-episode').forEach((btn) => {
      /** @type {HTMLElement} */ (btn).onclick = () => writeEpisode(btn);
    });
  } catch (err) {
    replaceActivityHtml(listEl, `<div class="text-error">${escapeHtml(err.message)}</div>`);
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
    replaceActivityHtml(boardEl, serialBoardHtml(continuity));
    worldFacts.episodes = data;
    worldFacts.reads.episodes = 'ok';
    pushWorldFacts();
    const episodes = newestFirst(data.episodes || []);
    // the newest episode as the Journal's cover (W12); the list below opens on the same one
    replaceActivityHtml(element('story-cover'), journalCoverHtml(episodes[0] || null, continuity));
    if (!episodes.length) {
      replaceActivityHtml(listEl, '<div class="topics-loading">Niciun episod încă.</div>');
      return;
    }
    const titles = new Map(episodes.map((episode) => [String(episode.id), String(episode.title || '')]));
    replaceActivityHtml(listEl, episodes.map((episode, index) => episodeHtml(episode, { open: index === 0, titles })).join(''));
    listEl.querySelectorAll('.btn-check-grounding').forEach((btn) => {
      /** @type {HTMLElement} */ (btn).onclick = () => checkGrounding(btn);
    });
    listEl.querySelectorAll('.btn-decide-episode').forEach((btn) => {
      /** @type {HTMLElement} */ (btn).onclick = () => decideEpisode(btn);
    });
  } catch (err) {
    // not read is not empty: the cover says nothing it did not read
    replaceActivityHtml(element('story-cover'), '');
    readFailed('episodes');
    pushWorldFacts();
    replaceActivityHtml(listEl, `<div class="text-error">${escapeHtml(err.message)}</div>`);
  }
}

// The cover's «Citește scenariul» goes to the newest episode's script, inside the dialog, the
// way a beat card goes to its beat (below).
element('story-cover').addEventListener('click', (event) => {
  const link = /** @type {HTMLElement} */ (event.target).closest('a.cover-read');
  if (!link) return;
  const target = document.getElementById(String(link.getAttribute('href') || '').slice(1));
  if (!target) return;
  event.preventDefault();
  if (target instanceof HTMLDetailsElement) target.open = true;
  const still = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const scroller = target.closest('.dialog-body');
  if (scroller) {
    const top = target.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop;
    scroller.scrollTo({ top: Math.max(0, top - 16), behavior: still ? 'auto' : 'smooth' });
  }
  const summary = target.querySelector('summary');
  if (summary) summary.focus({ preventScroll: true });
});

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

doorReads.set('story-modal', () => { loadStoryLogs(); loadEpisodes(); });
element('open-story-btn').addEventListener('click', () => openDoor(storyModal));
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
    lastPreflight = data;
    const status = String(data.status || '');
    summaryEl.innerHTML = `
      <div class="runbook-verdict rb-${escapeHtml(status.toLowerCase())}">
        <strong title="${escapeHtml(status)}">${escapeHtml(preflightWord(status))}</strong>
        <span>${escapeHtml(data.summary || '')}</span>
      </div>`;
    // Every check is shown, passing ones included: the value of a preflight is that the Owner
    // can see what it actually looked at, not only what it complained about. W32: as a game's
    // checklist (readiness.js preflightChecklist): the lines that fail first, the backend's first
    // stop at their head, each with its state in words, colour and shape and a key to the place
    // that fixes it; the passing lines one quiet row each; every detail behind «Detalii». The
    // order, state and place come from each check's code and severity, never from its sentence.
    checksEl.innerHTML = checklistHtml(preflightChecklist(data), escapeHtml);
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
  // PAGE-02: a day that waits for him at a film's paid step opens that film's sheet
  const sheet = sheetKeyFor(run);
  return `
    <div class="${escapeHtml(runClassName(run))}" data-card-key="${escapeHtml(run.id)}">
      <div class="topic-card-header">
        <strong class="topic-card-title">${escapeHtml(isoDay(run.business_date))}</strong>
        <span class="topic-card-novelty" title="${escapeHtml(run.status)}">${escapeHtml(runStatusWord(run.status))}</span>
      </div>
      <div class="topic-card-meta">
        <span>${run.stages_completed} din ${countWords(run.stages_total, 'etapă încheiată', 'etape încheiate')}</span>
        · <span>verificare preliminară: ${escapeHtml(run.preflight_status ? preflightWord(run.preflight_status) : '—')}</span>
        ${run.stopped_at_stage ? ` · <span>oprită la «${escapeHtml(stageLabel(run.stopped_at_stage))}»</span>` : ''}
      </div>
      ${headline.text ? `<div class="runbook-run-summary${headline.empty ? ' rb-empty' : ''}">${escapeHtml(headline.text)}</div>` : ''}
      ${run.stop_reason ? `<div class="claim-notes">${escapeHtml(run.stop_reason)}</div>` : ''}
      ${sheet ? `<div class="source-actions"><button type="button" class="secondary" data-sheet-open="${escapeHtml(sheet)}">Deschide foaia de filmare</button></div>` : ''}
      <div class="runbook-stages">
        ${stages
          .map(
            (stage) => `
          <div class="${escapeHtml(stageClassName(stage))}">
            <span class="runbook-stage-name">${escapeHtml(stageLabel(stage.stage))}</span>
            <span class="runbook-stage-status" title="${escapeHtml(stage.status)}">${escapeHtml(runStatusWord(stage.status))}${stageProducedWord(stage) ? `<span class="runbook-stage-produced">${escapeHtml(stageProducedWord(stage))}</span>` : ''}</span>
            <span class="runbook-stage-reason">${escapeHtml(stage.reason || '')}${stageNotesHtml(stage)}</span>
          </div>`,
          )
          .join('')}
      </div>
    </div>`;
}

/**
 * PAGE-12: «Coada de lucru». The worker's tasks with their kind, age, attempts and last error;
 * a dead task can be queued again and a task's workflow cancelled, each only after a question
 * that names what it does (work_queue.js).
 * @type {any[]}
 */
let queueTasks = [];
async function loadWorkQueue() {
  const box = element('work-queue');
  try {
    const tasks = await api(QUEUE_PATH);
    queueTasks = Array.isArray(tasks) ? tasks : [];
    replaceActivityHtml(box, queueHtml(queueTasks, Date.now()));
  } catch (err) {
    replaceActivityHtml(box, `<div class="text-error">${escapeHtml(err.message)}</div>`);
  }
}

/** @param {string} text @param {boolean} [error] */
function queueStatus(text, error = false) {
  const line = element('queue-status');
  line.hidden = !text;
  line.className = error ? 'dialog-status-msg text-error' : 'dialog-status-msg';
  line.textContent = text;
}

element('refresh-queue-btn').addEventListener('click', () => { void loadWorkQueue(); });
element('work-queue').addEventListener('click', async (event) => {
  const target = /** @type {HTMLElement} */ (event.target);
  const retry = /** @type {HTMLButtonElement|null} */ (target.closest('[data-queue-retry]'));
  const cancel = /** @type {HTMLButtonElement|null} */ (target.closest('[data-workflow-cancel]'));
  if (retry) {
    const task = queueTasks.find((t) => t.id === retry.dataset.queueRetry);
    if (!task) return;
    const yes = await confirmDialog({ question: retryQuestion(task), words: 'Sarcina pornește din nou de la prima încercare, când lucrătorul ajunge la ea.', yes: 'Da, reîncearcă' });
    if (!yes) return;
    retry.disabled = true;
    try {
      await api(`/tasks/${encodeURIComponent(task.id)}/retry`, { method: 'POST' });
      queueStatus('Sarcina este din nou în coadă.');
    } catch (err) {
      queueStatus(err.message, true);
    }
    await loadWorkQueue();
    return;
  }
  if (cancel) {
    const yes = await confirmDialog({ question: CANCEL_QUESTION, words: 'Sarcinile fluxului nu mai pornesc după anulare.', yes: 'Da, anulează fluxul' });
    if (!yes) return;
    cancel.disabled = true;
    try {
      await api(`/workflows/${encodeURIComponent(cancel.dataset.workflowCancel || '')}/cancel`, { method: 'POST' });
      queueStatus('Fluxul a fost anulat.');
    } catch (err) {
      queueStatus(err.message, true);
    }
    await loadWorkQueue();
  }
});

/** Renders the runs and returns whether one is still on its way. */
async function loadRuns() {
  const listEl = element('runbook-runs');
  try {
    const data = await api('/runbook/runs');
    const runs = newestFirst(data.runs || []);
    const pending = data.pending
      ? `<div class="topic-card runbook-run rb-running">
          <div class="topic-card-header">
            <strong class="topic-card-title">Rularea de azi</strong>
            <span class="topic-card-novelty">ÎN CURS</span>
            ${stuckWords(data.pending, Date.now()) ? `<span class="topic-card-novelty rb-stuck" title="Ziua așteaptă mai mult decât îi permit reîncercările și nu mai ține lucrătorul ocupat. Vezi Coada de lucru.">${escapeHtml(stuckWords(data.pending, Date.now()))}</span>` : ''}
          </div>
          <div class="topic-card-meta">În coadă de la ${escapeHtml(timelineTime(data.pending.created_at))}</div>
          <div class="claim-notes">Etapele apar în registrul din stânga pe măsură ce se întâmplă.</div>
        </div>`
      : '';
    replaceActivityHtml(listEl, pending + (runs.length ? runs.map(renderRunCard).join('') : (pending ? '' : '<div class="topics-loading">Nicio rulare încă.</div>')));
    return Boolean(data.pending);
  } catch (err) {
    replaceActivityHtml(listEl, `<div class="text-error">${escapeHtml(err.message)}</div>`);
    return false;
  }
}

/**
 * The schedule behind the button. A studio that runs itself has a job that fires the day; the
 * panel says when, and says plainly that it will not fire while autonomy is stopped, because
 * a "next run" time shown beside a stopped studio would promise something that cannot happen.
 */
/**
 * The demo's permanent banner (SELL-03): a studio started with `scripts/start.py --demo` runs on
 * simulated vendors and publishes nothing, and the page says so on every screen.
 * @param {{active?: boolean, banner_ro?: string}|null|undefined} demo
 */
function renderDemoBanner(demo) {
  let banner = document.getElementById('demo-banner');
  if (!demo || !demo.active) {
    if (banner) banner.hidden = true;
    return;
  }
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'demo-banner';
    banner.className = 'demo-banner';
    banner.setAttribute('role', 'status');
    // set through the CSSOM (the page's policy refuses inline style attributes, not this), so the
    // banner needs no rule of its own in the shared stylesheet
    Object.assign(banner.style, {
      position: 'sticky', top: '0', zIndex: '1000', padding: '6px 12px', textAlign: 'center',
      font: '600 14px/1.4 system-ui, sans-serif', background: '#7c2d12', color: '#fff7ed',
    });
    document.body.prepend(banner);
  }
  banner.textContent = demo.banner_ro || 'DEMO — furnizori simulați, nimic nu se publică';
  banner.hidden = false;
}

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
          <strong class="topic-card-title" title="${escapeHtml(daily.name)}">${escapeHtml(SCHEDULE_TITLE)}</strong>
          <span class="topic-card-novelty">${daily.is_active ? 'ACTIV' : 'INACTIV'}</span>
        </div>
        <div class="topic-card-meta">Ora rulării zilnice: ${escapeHtml(daily.run_at_local || '—')}${daily.timezone ? ` (${escapeHtml(daily.timezone)})` : ''} · se schimbă cu STUDIO_DAILY_RUN_HOUR_LOCAL și STUDIO_TIMEZONE</div>
        <div class="topic-card-meta">Următoarea rulare: ${escapeHtml(when(scheduleNextRun(daily)))} · ultima: ${escapeHtml(when(daily.last_run_at))} · la ${escapeHtml(countWords(Math.round(daily.interval_seconds / 3600), 'oră', 'ore'))} · rulări ratate: ${escapeHtml(daily.missed_policy === 'CATCH_UP' ? 'o singură recuperare, apoi cadența inițială' : 'sărite')}</div>
        ${stopped ? `<p class="runbook-note">Autonomia este oprită: treaba nu va porni nimic până nu o repornești.</p>` : ''}
        ${daily.is_active ? '' : `<p class="runbook-note">Programarea este oprită: studioul nu pornește nicio zi de la sine. Pornirea este decizia ta și rămâne în istoric.</p>`}
        <div class="settings-actions">
          <button id="toggle-daily-job-btn" class="${daily.is_active ? 'quiet' : 'secondary'}" data-job-id="${escapeHtml(daily.id)}" data-active="${daily.is_active ? 'true' : 'false'}">${daily.is_active ? 'Oprește programarea' : 'Pornește programarea zilnică'}</button>
        </div>
      </div>`;
    element('toggle-daily-job-btn').addEventListener('click', async (event) => {
      const button = /** @type {HTMLButtonElement} */ (event.currentTarget);
      // PAGE-08: switching the schedule on asks first; switching it off is one click
      if (button.dataset.active !== 'true' && !(await askConsequence({ dailyJob: true }))) return;
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
attachRail(autonomyModal.querySelector('.dialog-body'));
attachRail(researchModal.querySelector('.dialog-body'));
attachRail(storyModal.querySelector('.dialog-body'));

doorReads.set('runbook-modal', () => { loadCompanyState(); loadPreflight(); loadSafeMode(); loadRuns(); loadRunbookSchedule(); loadWorkQueue(); });
element('open-runbook-btn').addEventListener('click', () => openDoor(runbookModal));

// Where the company stands, and what the Director decided about it. A channel with nothing
// measured says so: a zero here would read as a measurement, and the studio has published
// nothing yet. Numbers come with their change, because a total on its own decides nothing.
/** Who holds a role, by the role's code: the employee's own name, or the code when nobody does. @param {string} role */
function roleHolder(role) {
  const holder = officeState.agents.find((a) => a.role_name === role);
  return holder && holder.display_name ? holder.display_name : role;
}

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
          <div>${escapeHtml(countWords(channel.published, 'film publicat', 'filme publicate'))} · ${escapeHtml(countWords(channel.measured, 'măsurat', 'măsurate'))}</div>
          <div>${escapeHtml(views)} · ${escapeHtml(change)}</div>
          <div class="motion-reason">${escapeHtml(channel.baseline?.note || '')}</div>
        </div>`;
      })
      .join('');
    const growth = (state.growth || [])
      .map(
        (item) =>
          `<div class="motion-reason"><strong title="${escapeHtml(item.constraint)}">${escapeHtml(constraintWord(item.constraint))}</strong> (încredere ${escapeHtml(confidenceWord(item.confidence))}): ${escapeHtml(item.reason)}</div>`,
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
            ? ` · <span class="text-error">blocaj la ${escapeHtml(pipelineStageWord(pipe.bottleneck.stage))}: ${pipe.bottleneck.waiting} în așteptare</span>`
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

    // The decision's matter names a channel by the first 8 of its id; the state names them all.
    const channelNames = new Map((state.channels || []).map((c) => [String(c.channel_id || '').slice(0, 8), String(c.channel_name || '')]));
    const rows = (decisions.decisions || []).slice(0, 8);
    list.innerHTML = rows.length
      ? rows
          .map(
            (row) => `
        <div class="topic-card">
          <div class="topic-card-header">
            <strong class="topic-card-title" title="${escapeHtml(`${row.decision} — ${row.matter_key}`)}">${escapeHtml(decisionWord(row.decision))} — ${escapeHtml(matterWords(row.matter_key, channelNames))}</strong>
            <span class="topic-card-novelty" title="${escapeHtml(row.state)}">${escapeHtml(decisionStateWord(row.state))}</span>
          </div>
          <div class="motion-reason">${escapeHtml(row.observation)}</div>
          <div class="motion-reason">Interpretare (încredere ${escapeHtml(confidenceWord(row.confidence))}): ${escapeHtml(row.interpretation)}</div>
          <div><strong>De făcut:</strong> ${escapeHtml(row.action)}${row.owner_role ? ` — ${escapeHtml(roleHolder(row.owner_role))}` : ''}</div>
          ${row.review_after_videos ? `<div class="motion-reason">Revizuire după ${countWords(row.review_after_videos, 'film', 'filme')}.</div>` : ''}
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
 * W32: a checklist line's key opens the place that fixes it, through that place's own door: the
 * daily run's door goes back into the façade and the other grows out of its room (Settings from the
 * opened at the tab or brought to the section that fixes it.
 * The dock's AUTONOMIE switch is not a door: it is brought into view and given the focus.
 * @param {{door?: string, tab?: string, section?: string}} place (readiness.js fixPlaceOf, as the key's data)
 */
function openFixPlace(place) {
  if (!place.door) return;
  runbookModal.close();
  if (autonomyModal.open && place.door !== 'autonomy-modal') autonomyModal.close();
  if (place.door === 'settings') {
    settingsUI.open(place.tab || 'llm');
    return;
  }
  if (place.door === 'autonomy_switch') {
    const toggle = /** @type {HTMLButtonElement|null} */ (document.getElementById('stop-toggle'));
    if (toggle) {
      toggle.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'nearest' });
      toggle.focus({ preventScroll: true });
    }
    return;
  }
  const opener = /** @type {Record<string, string>} */ ({
    'research-modal': 'open-research-btn',
    'media-modal': 'open-media-btn',
    'publishing-modal': 'open-publishing-btn',
    'workforce-modal': 'open-workforce-btn',
    'story-modal': 'open-story-btn',
    'autonomy-modal': 'open-autonomy-btn',
  })[place.door];
  const button = opener ? document.getElementById(opener) : null;
  const dialog = /** @type {HTMLDialogElement|null} */ (document.getElementById(place.door));
  if (!button || !dialog) return;
  if (!dialog.open) button.click();
  if (place.tab === 'characters') tabCharactersBtn.click();
  const section = place.section ? document.getElementById(place.section) : null;
  if (section && place.tab !== 'characters') {
    // the door reads its content once the pane has landed, and what arrives above the section moves
    // it: it is brought to the top once it has stood still for a moment (at most about 2 s)
    const timing = doorTiming(reducedMotion(), (name) => getComputedStyle(document.documentElement).getPropertyValue(name));
    let last = NaN;
    let tries = 0;
    const settle = () => {
      if (!dialog.open) return;
      const top = section.getBoundingClientRect().top;
      if (Math.abs(top - last) < 1 || ++tries > 16) {
        section.scrollIntoView({ behavior: reducedMotion() ? 'auto' : 'smooth', block: 'start' });
        return;
      }
      last = top;
      window.setTimeout(settle, 120);
    };
    window.setTimeout(settle, timing.open + 60);
  }
}
element('runbook-checks').addEventListener('click', (event) => {
  const key = /** @type {HTMLElement} */ (event.target).closest('.pf-fix');
  if (key instanceof HTMLElement) openFixPlace({ door: key.dataset.door, tab: key.dataset.tab, section: key.dataset.section });
});

element('autonomy-overview').addEventListener('click', async (event) => {
  const action = event.target instanceof HTMLElement ? event.target.closest('[data-autonomy-go]') : null;
  if (action instanceof HTMLElement) {
    const closed = new Promise((resolve) => autonomyModal.addEventListener('close', resolve, { once: true }));
    autonomyModal.close();
    await closed;
    if (action.dataset.autonomyGo === 'providers') { void settingsUI.open('llm'); return; }
    if (action.dataset.autonomyGo === 'schedule') { element('open-runbook-btn').click(); return; }
    drawers.set('side', true);
    element('autonomy-mode-buttons').scrollIntoView({ block: 'center' });
    element('autonomy-mode-buttons').querySelector('button')?.focus();
    return;
  }
  const key = event.target instanceof HTMLElement ? event.target.closest('.pf-fix') : null;
  if (key instanceof HTMLElement) openFixPlace({ door: key.dataset.door, tab: key.dataset.tab, section: key.dataset.section });
});

/**
 * A day takes minutes — agents think, a render is waited on, quality control reads the file.
 * The Owner's click asks for it to start, and that is what is answered: the studio queues the
 * day and says so at once. Where it has got to is in the ledger, stage by stage, and the runs
 * list below fills in as soon as the day closes.
 */
element('start-run-btn').addEventListener('click', async (event) => {
  const button = /** @type {HTMLButtonElement} */ (event.currentTarget);
  // PAGE-08: what today's run will buy alone, before it starts
  if (!(await askConsequence({ runNow: true }))) return;
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

/* ==========================================================================================
 * W28 — THE DOORS OPEN FROM THEIR ROOMS (dialog_doors.js)
 * ======================================================================================== */

/** The masthead's key for each door: its hover or focus reads the door's content ahead. */
const DOOR_KEYS = {
  'open-research-btn': 'research-modal',
  'open-media-btn': 'media-modal',
  'open-publishing-btn': 'publishing-modal',
  'open-workforce-btn': 'workforce-modal',
  'open-story-btn': 'story-modal',
  'open-runbook-btn': 'runbook-modal',
  'open-autonomy-btn': 'autonomy-modal',
};

/** Read a door's content now (the studio's own API), and remember when. @param {string} id */
function readDoor(id) {
  const read = doorReads.get(id);
  if (!read) return;
  doorReadAt.set(id, Date.now());
  read();
}

/** Read ahead on the menu's hover or focus, unless the content is fresh or the door is open. @param {string} id */
function readDoorAhead(id) {
  const dialog = document.getElementById(id);
  if (!dialog || /** @type {HTMLDialogElement} */ (dialog).open) return;
  if (doorNeedsRead(doorReadAt.get(id), Date.now(), DOOR_FRESH_MS)) readDoor(id);
}

/**
 * Open a door. Its content was read on the hover or the focus that led here, or it is read once
 * the pane has landed.
 * @param {HTMLDialogElement} dialog
 */
function openDoor(dialog) {
  if (!dialog.open) dialog.showModal();
  if (!doorNeedsRead(doorReadAt.get(dialog.id), Date.now(), DOOR_FRESH_MS)) return;
  const timing = doorTiming(reducedMotion(), (name) => getComputedStyle(document.documentElement).getPropertyValue(name));
  doorReadAt.set(dialog.id, Date.now());
  window.setTimeout(() => { if (dialog.open) readDoor(dialog.id); }, timing.open);
}

/** The part of the scene a visitor sees, page px: the viewport between the drawers, on screen. */
function sceneClip() {
  const vp = element('scene-viewport').getBoundingClientRect();
  const box = officeCanvas.getBoundingClientRect();
  const engine = officeEngine;
  const dpr = (engine && engine.dpr) || 1;
  const ins = (engine && engine.viewport && engine.viewport.insets) || { left: 0, right: 0, top: 0, bottom: 0 };
  return {
    left: Math.max(vp.left, box.left + (ins.left || 0) / dpr, 0),
    top: Math.max(vp.top, box.top + (ins.top || 0) / dpr, 0),
    right: Math.min(vp.right, box.right - (ins.right || 0) / dpr, window.innerWidth),
    bottom: Math.min(vp.bottom, window.innerHeight),
  };
}

/** A world rectangle on the page now, through the engine's camera (the stream follows it). @param {number[]|null} world */
function worldOnPage(world) {
  if (!world || !officeEngine || workspace.hidden) return null;
  const box = officeCanvas.getBoundingClientRect();
  if (!(box.width > 0)) return null;
  return roomOnScreen(world, officeEngine.viewport, officeEngine.dpr || 1, box, sceneClip());
}

/** A door's room on the page: the stream's measured rooms while it covers the renderer. @param {string} id */
function doorRoomOnPage(id) {
  if (!officeEngine) return null;
  const manifest = officeEngine.assets && officeEngine.assets.manifest;
  return worldOnPage(doorWorldRect(id, {
    rooms: manifest ? manifest.rooms : undefined,
    streamRooms: STREAM_ROOMS,
    faces: WALL,
    stream: Boolean(officeEngine.hitsOnly),
  }));
}

/** The chosen employee's place on the page: the desk, the chair and the figure (the hit box). */
function inspectorDoorOnPage() {
  if (!officeEngine || !officeEngine.renderer || !currentSelectedAgent) return null;
  const id = currentSelectedAgent.id || currentSelectedAgent.agent_id;
  const hit = (officeEngine.renderer.hits || []).find((/** @type {any} */ h) => !h.surface && h.agent && (h.agent.id || h.agent.agent_id) === id);
  return hit ? worldOnPage([hit.x0, hit.y0, hit.x1 - hit.x0, hit.y1 - hit.y0]) : null;
}

const doorLight = document.getElementById('door-light');
let doorLightHide = 0;
/**
 * The room lit while its door is open: the page's mark of what he opened, laid over the room's
 * rectangle in the scene (under the stream's plaques' words and the readouts).
 * @param {{x: number, y: number, w: number, h: number}|null} rect page px
 * @param {boolean} on
 * @param {number} ms
 */
function lightDoor(rect, on, ms) {
  if (!doorLight) return;
  clearTimeout(doorLightHide);
  doorLight.style.setProperty('--door-light-ms', `${Math.round(ms)}ms`);
  if (!on || !rect) {
    doorLight.classList.remove('is-on');
    doorLightHide = window.setTimeout(() => { doorLight.hidden = true; }, ms + 40);
    return;
  }
  const vp = element('scene-viewport').getBoundingClientRect();
  doorLight.style.left = `${Math.round(rect.x - vp.left)}px`;
  doorLight.style.top = `${Math.round(rect.y - vp.top)}px`;
  doorLight.style.width = `${Math.round(rect.w)}px`;
  doorLight.style.height = `${Math.round(rect.h)}px`;
  if (doorLight.hidden) {
    doorLight.hidden = false;
    void doorLight.offsetWidth;
  }
  doorLight.classList.add('is-on');
}

for (const id of [...Object.values(DOOR_KEYS), 'settings-dialog']) {
  const dialog = /** @type {HTMLDialogElement|null} */ (document.getElementById(id));
  if (dialog) attachDoor(dialog, { roomRect: () => doorRoomOnPage(id), light: lightDoor, reduced: reducedMotion });
}
attachDoor(inspector, { roomRect: inspectorDoorOnPage, light: lightDoor, reduced: reducedMotion });
attachDoor(mailThread.dialog, { roomRect: () => null, reduced: reducedMotion });

for (const [key, id] of Object.entries(DOOR_KEYS)) {
  const button = document.getElementById(key);
  if (!button) continue;
  let rest = 0;
  // a pointer resting on the key for a moment, not one passing over it on its way elsewhere
  button.addEventListener('pointerenter', () => { clearTimeout(rest); rest = window.setTimeout(() => readDoorAhead(id), 120); });
  button.addEventListener('pointerleave', () => clearTimeout(rest));
  button.addEventListener('focus', () => readDoorAhead(id));
}

/* ---------------------------------------------------------------------------
 * PAGE_OWNER_DAY (2026-10-02): what the Owner sees and decides about the autonomous day.
 * Every word comes from the pure modules (build_banner.js, governance.js, owner_inbox.js,
 * budget_form.js, shooting_sheet.js); this only wires them to the page.
 * ------------------------------------------------------------------------- */

/** The newest preflight read in Rularea zilei, for the consequence of starting a run. @type {any} */
let lastPreflight = null;

/**
 * PAGE-01 / REL-07: the banners at the top of every screen, from the snapshot.
 * @param {any} data the snapshot
 */
let pageBannersKey = '';
function renderPageBanners(data) {
  const banners = pageBanners(data);
  const key = bannersKey(banners);
  if (key === pageBannersKey) return;
  pageBannersKey = key;
  let box = document.getElementById('page-banners');
  if (!banners.length) {
    if (box) box.hidden = true;
    return;
  }
  if (!box) {
    box = document.createElement('div');
    box.id = 'page-banners';
    box.className = 'page-banners';
    box.setAttribute('role', 'status');
    document.body.prepend(box);
  }
  box.innerHTML = banners.map((b) => `<p class="page-banner" data-kind="${escapeHtml(b.kind)}" data-tone="${escapeHtml(b.tone)}">${escapeHtml(b.text)}</p>`).join('');
  box.hidden = false;
}

/**
 * A question asked before a switch that lets the studio spend (PAGE-08) or retires the daily
 * budget (PAGE-05): what it is, what follows, «Da, …» and «Nu acum». Resolves true on his yes.
 * @param {{question: string, words: string, yes: string}} q
 * @returns {Promise<boolean>}
 */
function confirmDialog(q) {
  let dialog = /** @type {HTMLDialogElement|null} */ (document.getElementById('consequence-dialog'));
  if (!dialog) {
    dialog = document.createElement('dialog');
    dialog.id = 'consequence-dialog';
    dialog.className = 'studio-dialog consequence-dialog';
    document.body.append(dialog);
  }
  const box = dialog;
  box.innerHTML = '<div class="dialog-body consequence-body">'
    + `<h2 class="dialog-title consequence-question">${escapeHtml(q.question)}</h2>`
    + `<p class="consequence-words">${escapeHtml(q.words)}</p>`
    + '<div class="source-actions">'
    + `<button type="button" class="secondary" data-consequence="yes">${escapeHtml(q.yes)}</button>`
    + '<button type="button" class="quiet" data-consequence="no">Nu acum</button>'
    + '</div></div>';
  return new Promise((resolve) => {
    /** @param {boolean} answer */
    const done = (answer) => {
      box.removeEventListener('click', onClick);
      box.removeEventListener('cancel', onCancel);
      if (box.open) box.close();
      resolve(answer);
    };
    /** @param {Event} event */
    const onClick = (event) => {
      const key = event.target instanceof Element ? event.target.closest('[data-consequence]') : null;
      if (key) done(key.getAttribute('data-consequence') === 'yes');
    };
    /** @param {Event} event */
    const onCancel = (event) => { event.preventDefault(); done(false); };
    box.addEventListener('click', onClick);
    box.addEventListener('cancel', onCancel);
    box.showModal();
    /** @type {HTMLButtonElement|null} */ (box.querySelector('[data-consequence="no"]'))?.focus();
  });
}

/**
 * PAGE-08: the switch's question with what the next run will do once it is on; true at once for a
 * change that makes the studio safer (consequenceWords answers null).
 * @param {{mode?: string, environment?: string, dailyJob?: boolean, runNow?: boolean}} change
 */
async function askConsequence(change) {
  const q = consequenceWords({ policy: state ? state.policy : null, budget: worldFacts.budget, job: worldFacts.jobs, preflight: lastPreflight }, change);
  return q ? confirmDialog(q) : true;
}

/**
 * PAGE-04: his rule for the paid steps under «Mod de autonomie», and what the next run will do
 * with it, from the policy the snapshot read. The form is drawn again only when the policy's
 * version or the rule moves, so a choice he is making is not wiped by the five-second snapshot.
 * The sheet keeps its own copy.
 */
let governanceRuleKey = '';
function renderGovernanceRule() {
  const form = document.getElementById('paid-media-governance');
  if (!form || !state || !state.policy) return;
  const policy = state.policy;
  const key = `${policy.version}|${policy.paid_media_approval}|${policy.paid_media_approval_over_usd}`;
  if (key !== governanceRuleKey && !form.contains(document.activeElement)) {
    governanceRuleKey = key;
    form.innerHTML = paidMediaFormHtml(state.policy, { escape: escapeHtml });
  }
  renderDayWill();
}

function renderDayWill() {
  const line = document.getElementById('day-will');
  if (!line || !state || !state.policy) return;
  line.textContent = dayWillWords(state.policy, worldFacts.budget, worldFacts.jobs);
}

const governanceRuleForm = /** @type {HTMLFormElement|null} */ (document.getElementById('paid-media-governance'));
if (governanceRuleForm) {
  // the amount field's Enter would submit the form: the rule is saved by its key only
  governanceRuleForm.addEventListener('submit', (event) => event.preventDefault());
  governanceRuleForm.addEventListener('click', async (event) => {
    const key = event.target instanceof Element ? event.target.closest('[data-sheet-action="paid-media-save"]') : null;
    if (!key || busy || !state) return;
    const choice = /** @type {HTMLInputElement|null} */ (governanceRuleForm.querySelector('input[name="paid-media"]:checked'))?.value || '';
    const amount = /** @type {HTMLInputElement|null} */ (governanceRuleForm.querySelector('[data-paid-media-amount]'))?.value || '';
    /** @type {HTMLButtonElement} */ (key).disabled = true;
    const saved = await savePaidMediaRule(api, { choice, amount, version: state.policy.version, commandId: crypto.randomUUID() });
    governanceNote(saved.message, saved.status !== 'SAVED');
    // saved or stale: the policy is read again, so he looks at the rule as it is now
    governanceRuleKey = '';
    if (saved.reload) await refresh();
    else /** @type {HTMLButtonElement} */ (key).disabled = false;
  });
}

/* PAGE-07: «Scrisori pentru tine», under the approvals. */
let lettersLastRead = 0;
let lettersRead = /** @type {'pending'|'ok'|'failed'} */ ('pending');
/** @type {ReturnType<typeof readLetters>} */
let lettersShown = [];

function renderOwnerLetters() {
  const list = document.getElementById('owner-inbox-list');
  if (!list) return;
  replaceActivityHtml(list, inboxHtml(lettersShown, { escape: escapeHtml, read: lettersRead, timezone: state && state.studio ? state.studio.timezone : undefined }));
  const count = document.getElementById('owner-inbox-count');
  if (count) count.textContent = lettersRead === 'ok' ? (lettersShown.length ? lettersWord(lettersShown.length) : 'niciuna') : '—';
}

/** @param {boolean} [force] read now, whatever the interval says */
async function loadOwnerLetters(force) {
  if (!ownerToken || !connected) return;
  const now = Date.now();
  if (!force && now - lettersLastRead < APPROVALS_INTERVAL_MS) return;
  lettersLastRead = now;
  try {
    lettersShown = readLetters(await api(OWNER_LETTERS_PATH));
    lettersRead = 'ok';
    openLetters = lettersShown.length;
  } catch {
    lettersRead = 'failed';
  }
  renderOwnerLetters();
  renderOwnerMark();
}

document.getElementById('owner-inbox-list')?.addEventListener('click', async (event) => {
  const target = event.target instanceof Element ? event.target : null;
  const thread = target?.closest('[data-inbox-thread]');
  if (thread) {
    void mailThread.open(thread.getAttribute('data-inbox-thread'));
    return;
  }
  const resolve = target?.closest('[data-inbox-resolve]');
  if (!resolve) return;
  /** @type {HTMLButtonElement} */ (resolve).disabled = true;
  try {
    await api(resolvePath(resolve.getAttribute('data-inbox-resolve') || ''), { method: 'POST', body: JSON.stringify(resolveCommand()) });
  } catch (error) {
    governanceNote(error instanceof Error ? error.message : 'Scrisoarea nu a putut fi marcată rezolvată.', true);
  }
  await loadOwnerLetters(true);
});
document.getElementById('refresh-inbox-btn')?.addEventListener('click', () => loadOwnerLetters(true));

/**
 * PAGE-02: every «Deschide foaia de filmare» on the page (a letter, a paid question, the day's run,
 * the readout, the inbox) opens the film's sheet in its drawer; the key carries only the film's id.
 */
document.addEventListener('click', (event) => {
  const key = event.target instanceof Element ? event.target.closest('[data-sheet-open]') : null;
  const id = key ? key.getAttribute('data-sheet-open') : null;
  if (!id || !/^[0-9a-f-]{36}$/i.test(id)) return;
  event.preventDefault();
  void openShootingSheet(id);
});

// LOCAL_AUTO_LOGIN: once the page is wired, ask this machine for the Owner's key; the form shows
// only when it is not handed over (local_entry.js).
void localEntry.start();
