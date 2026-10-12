// The Owner's RunPod GPU switch (2026-10-08): what the GPU is doing, and «Oprește GPU acum».
// The state comes from GET /api/v1/runpod/gpu (the guard's last reading); the button sends
// POST /api/v1/runpod/gpu/off. Off is always safe (it spends nothing, under STOP AUTONOMIE
// too), so there is no confirmation; a double press sends one command. Hidden when the studio
// has no RunPod connection.
//
// GPU_STOP_REACHABLE (WP4, 2026-10-09): the stop lived only in the camera toolbar, and every paid
// RunPod step is approved from the shooting sheet, a modal <dialog> that stays open while it buys.
// A modal makes the page behind it inert: his press landed on the sheet's backdrop, not on the
// stop, exactly while the GPU billed (about 0.07 USD for every minute he cannot reach it). The
// Decisions window and Settings are modal too. So the switch is now one control with many places:
// one reading, one poll, one press promise and one command id, shown in the toolbar and, while a
// GPU session is live, in the header of whichever modal dialog is open. The dialogs are found by
// watching the `open` attribute of every <dialog>, not by a list of names, so a modal added later
// carries the stop without anyone remembering to mount it.
//
// While a session is live the reading asks for `fresh=1` (one live read of RunPod per endpoint,
// at most every 10 s, the backend's own cap), and the words separate «GPU permis, 0 workeri — nu se
// plătește» from «worker activ»: the 2026-10-08 indicator said «GPU pornit» while the endpoint was
// paused and no worker ran. A reading that is missing says «necitită», never «neverificată».
//
// The review of 2026-10-09 found four ways this could still fail him, each closed here:
// - FOCUS: the stop sat first in a reopened dialog's header, so showModal() gave it the focus and
//   one Enter or Space after reopening the sheet or the inspector switched the GPU off in the
//   middle of his paid round. The focus goes where the dialog would have put it without the stop.
// - REBUILT: Settings re-renders with replaceChildren() after its /settings read and on every
//   click, and the stop came back only with the next poll (up to 10 s). The open modals' contents
//   are watched too; a dialog that lost its stop gets it back in the same microtask.
// - FRESH: a fresh read the page abandoned (its 10 s timeout) keeps a backend thread on a live
//   RunPod read of up to minutes, and asking fresh again every 10 s stacked them in the shared
//   pool where his own off POST waits. After a failed fresh read the next one waits twice as
//   long each time (up to 5 min). The cached reading served meanwhile is NOT current: the guard
//   skips an endpoint a session uses, so nothing refreshes it (see STALE READING).
// - QUEUE: «nu se plătește» was said with a job queued, while RunPod starts (and bills) a worker
//   for it; the studio's own OFF needs inQueue == 0. A queued job now says so, in the billing
//   colour, unless the backend says the wait is the unbilled model download.
//
// EVERY STOP LEAVES A RECEIPT (WP4, row 5, 2026-10-09): the only proof that the GPU stopped right
// after a round was the developer polling copies of the database; the page had «Ultima oprire …:
// verificată/neverificată» in a hover title, with no time, and kept «neverificată» after the
// guard's later OFF read proved the stop. The stopped switch now says when, and how the stop was
// read, on its face: «GPU oprit la 21:14:03 (verificat)», «(confirmat de paznic)» once the guard
// read OFF what the close could not, «(necitit)» for a stop nobody read. The backend's receipt
// (`last_off.off_state`, `last_off.words_ro`: the last job's finish, the billed seconds) is the
// detail; a backend without them is read from `verified`, as before.
//
// The adversarial review of 2026-10-10 found four more, each closed here:
// - STALE READING: every paid round began with the sheet's stop saying «GPU oprit, 0 workeri —
//   nu se plătește» while RunPod started a billed worker. Opening a session caches no reading and
//   the guard skips an endpoint in use, so /runpod/gpu served the guard's last OFF reading from
//   before the round; the page asked fresh only a poll later, and after a failed fresh read the
//   frozen cache spoke for minutes. A live session's endpoint read before it opened, without a
//   time, or longer ago than STALE_READING_MS now proves nothing billless: «necitită» (a worker
//   it saw still counts as billing), and the first reading that learns of a session is followed
//   by the fresh one at once.
// - LIVE DETAIL: the hover detail repeated the backend's live words (they ignore the queue and the
//   reading's age), «nu se plătește» under a label saying a queued job can start a paid worker.
//   While live the detail leads with the label's own words; after a failed read it says so.
// - KEPT ENABLED: Settings disables every button of its dialog while it saves (settings.js
//   run()), the dialog's stop with them, for the whole request. The stop is re-enabled at once.
// - PHONE INSPECTOR (style.css): the stop among the inspector's header keys pushed the close key
//   out of the dialog at 375 px.

/**
 * @typedef {{purpose: string, endpoint_id: string, state: string, workers_max?: number|null,
 *   running?: number|null, in_progress?: number|null, in_queue?: number|null,
 *   initializing?: number|null, model_wait_ro?: string|null, read_at?: string|null}} GpuEndpoint
 * @typedef {{id: string, purpose: string, step: string, storyboard_id?: string|null,
 *   endpoint_id?: string|null, opened_at?: string|null, words_ro?: string|null}} GpuSession
 * @typedef {{at: string, reason: string, verified: boolean|null, off_state?: string|null,
 *   off_confirmed_at?: string|null, confirmed_by?: string|null, session_id?: string|null,
 *   words_ro?: string|null}} GpuLastOff
 * @typedef {{configured: boolean, mock?: boolean, rate_usd_per_hour?: string,
 *   endpoints?: GpuEndpoint[], sessions?: GpuSession[],
 *   last_off?: GpuLastOff|null, words_ro?: string,
 *   model_wait_ro?: string|null, owner_hold?: boolean}} GpuStatus
 * @typedef {'off'|'on'|'armed'|'unknown'} GpuTone
 * @typedef {'VERIFIED'|'CONFIRMED'|'UNVERIFIED'|'UNREAD'|'SIMULATED'} GpuOffState
 * @typedef {{now?: number, timeZone?: string}} GpuClock when the words are read, and on which
 *   clock (the page's own zone, his PC's, unless one is named)
 * @typedef {{container: any, label: any, button: any, said: any|null, dialog: boolean}} GpuMount
 */

/** While a session is live, one fresh reading at most this often (ms); the backend caps it too. */
export const FRESH_EVERY_MS = 10000;
/** After failed fresh readings the next one waits 2x, 4x, ... `FRESH_EVERY_MS`, at most this (ms). */
export const FRESH_BACKOFF_MAX_MS = 300000;
/** His answer stays in a dialog's stop this long after the press, though the session closed (ms). */
export const SAID_KEEP_MS = 60000;
/**
 * A live session's endpoint reading older than this (ms) says nothing about now (STALE READING).
 * While fresh reads succeed the backend re-reads at most every 10 s and the page asks every 10 s,
 * so a reading it paints is at most about 20 s old plus RunPod's own read time; older means a
 * fresh cycle was missed and the cache froze.
 */
export const STALE_READING_MS = 3 * FRESH_EVERY_MS;
/** The detail after a reading that failed: the label says «necitită», the detail never more. */
const READ_FAILED_DETAIL = 'GPU: stare necitită — ultima citire a stării a eșuat; reîncerc la următoarea verificare.';

const OFF_REASONS = /** @type {Record<string, string>} */ ({
  STEP_DONE: 'după ultimul rezultat',
  STEP_FAILED: 'după un pas oprit',
  OWNER_OFF: 'de tine',
  GUARD_ORPHAN: 'de paznic, la pornire',
  GUARD_STALE: 'de paznic',
  GUARD_TTL: 'de paznic, după limita de timp',
  SHUTDOWN: 'la oprirea studioului',
  LAUNCHER_STOP: 'la închiderea studioului',
});

/** @param {unknown} value */
const known = (value) => typeof value === 'number' && Number.isFinite(value);

/**
 * Whether a GPU session is open or an endpoint can bill: the stop must then be in front of him.
 * @param {GpuStatus|null|undefined} status
 */
export function gpuLive(status) {
  if (!status || !status.configured || status.mock) return false;
  return Boolean((status.sessions || []).length) || (status.endpoints || []).some((e) => e.state === 'ON');
}

/**
 * What RunPod's workers are doing, from its own counts (never from the session's wall time).
 * An endpoint read OFF has no worker by definition; one never read is «necitită». «nu se
 * plătește» only when nothing runs, starts or waits in the queue of an endpoint allowed a worker:
 * RunPod starts a worker for a queued job and bills it from its start (QUEUE, 2026-10-09).
 * `active` counts the workers known to bill.
 * @param {GpuEndpoint[]} endpoints
 * @returns {{words: string, tone: GpuTone, active: number}}
 */
export function workerWords(endpoints) {
  let active = 0;
  let queued = 0;
  let unread = false;
  let permitted = false;
  for (const e of endpoints) {
    if (e.state === 'OFF') continue;
    const running = known(e.running) ? Number(e.running) : null;
    const working = known(e.in_progress) ? Number(e.in_progress) : null;
    if (running === null && working === null) {
      unread = true;
      continue;
    }
    // a job in progress runs on a worker even when the health count lags behind it; a worker
    // RunPod is still starting (initializing) bills from its start, so it counts as one
    active += Math.max(running || 0, working ? 1 : 0) + (known(e.initializing) ? Number(e.initializing) : 0);
    if (running === null || !known(e.workers_max)) {
      unread = true;
      continue;
    }
    if (Number(e.workers_max) > 0) {
      permitted = true;
      // an endpoint allowed a worker is unbilled only with its queue read empty
      if (known(e.in_queue)) queued += Number(e.in_queue);
      else unread = true;
    }
  }
  if (active === 1) return { words: 'GPU pornit, worker activ', tone: 'on', active };
  if (active > 1) return { words: `GPU pornit, ${active} workeri activi`, tone: 'on', active };
  if (unread) return { words: 'GPU: stare necitită', tone: 'unknown', active };
  if (queued > 0) {
    const jobs = queued === 1 ? 'o lucrare' : `${queued} lucrări`;
    return { words: `GPU permis, ${jobs} la coadă — poate porni un worker plătit`, tone: 'on', active };
  }
  if (permitted) return { words: 'GPU permis, 0 workeri — nu se plătește', tone: 'armed', active };
  return { words: 'GPU oprit, 0 workeri — nu se plătește', tone: 'armed', active };
}

/** How a stop was read, about «oprirea» (feminine) and about «GPU oprit» (masculine). */
const OFF_READ = /** @type {Record<GpuOffState, [string, string]>} */ ({
  VERIFIED: ['verificată', 'verificat'],
  CONFIRMED: ['confirmată de paznic', 'confirmat de paznic'],
  UNVERIFIED: ['neverificată', 'neverificat'],
  UNREAD: ['necitită', 'necitit'],
  SIMULATED: ['simulată', 'simulare'],
});

/**
 * How the last stop was read (WP4): the backend's own `off_state` when it sends one; else, from
 * an older backend, `verified` (true: its close read it OFF; false: read and not off; null:
 * never read). A stop the guard confirmed later is CONFIRMED, never «neverificată» again.
 * @param {Partial<GpuLastOff>|null|undefined} last
 * @returns {GpuOffState}
 */
export function offStateOf(last) {
  const state = last && typeof last.off_state === 'string' ? last.off_state.toUpperCase() : '';
  if (Object.prototype.hasOwnProperty.call(OFF_READ, state)) return /** @type {GpuOffState} */ (state);
  if (last && last.verified === true) return 'VERIFIED';
  if (last && last.verified === false) return 'UNVERIFIED';
  return 'UNREAD';
}

/**
 * How the last stop was read: verified, confirmed by the guard, read and not off, or never read.
 * @param {boolean|null|undefined} verified
 * @param {string|null} [state] the backend's `off_state`, which wins when it is known
 */
export function offReadWords(verified, state = null) {
  return OFF_READ[offStateOf({ verified, off_state: state })][0];
}

/** @param {number} moment @param {string|undefined} timeZone */
function clockParts(moment, timeZone) {
  /** @type {Record<string, string>} */
  const parts = {};
  const format = new Intl.DateTimeFormat('ro-RO', {
    timeZone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
  for (const part of format.formatToParts(moment)) parts[part.type] = part.value;
  return parts;
}

/**
 * A stop's moment on his clock: «21:14:03», with its day («08.10 21:14:03») when it was not
 * today, so yesterday's stop never reads as a minute ago. '' when the moment cannot be read.
 * @param {string|null|undefined} at an ISO moment
 * @param {GpuClock} [clock]
 */
export function stopClock(at, { now = Date.now(), timeZone } = {}) {
  const moment = at ? Date.parse(at) : Number.NaN;
  if (!Number.isFinite(moment)) return '';
  let when;
  let today;
  try {
    when = clockParts(moment, timeZone);
    today = clockParts(now, timeZone);
  } catch {
    // a zone this browser does not know: his PC's own clock
    when = clockParts(moment, undefined);
    today = clockParts(now, undefined);
  }
  const time = `${when.hour}:${when.minute}:${when.second}`;
  const sameDay = when.year === today.year && when.month === today.month && when.day === today.day;
  return sameDay ? time : `${when.day}.${when.month} ${time}`;
}

/**
 * The stopped switch's face: when the last stop was, and how it was read (the receipt, row 5).
 * Facts only, as the backend's receipt words: `at` is when the close sent the stop. A stop the
 * close could not read and the guard read OFF later is dated by the guard's reading, the first
 * moment anyone saw it off (the guard may have found the GPU on and switched it off itself), so
 * «oprit la» never names a moment nobody read it off.
 * @param {GpuLastOff|null|undefined} last @param {GpuClock} clock
 */
export function stoppedLabel(last, clock) {
  if (!last) return 'GPU oprit';
  const state = offStateOf(last);
  const confirmed = state === 'CONFIRMED' ? stopClock(last.off_confirmed_at, clock) : '';
  if (confirmed) return `GPU oprit (confirmat de paznic la ${confirmed})`;
  const at = stopClock(last.at, clock);
  if (!at) return 'GPU oprit';
  return `GPU oprit la ${at} (${OFF_READ[state][1]})`;
}

/**
 * The last stop in the detail: the backend's receipt words when it sends them, else who stopped
 * it and how the stop was read.
 * @param {GpuLastOff} last
 */
function lastOffDetail(last) {
  if (typeof last.words_ro === 'string' && last.words_ro.trim()) return `Ultima oprire: ${last.words_ro.trim()}`;
  const how = OFF_REASONS[last.reason] || last.reason;
  return `Ultima oprire ${how}: ${offReadWords(last.verified, last.off_state)}.`;
}

/**
 * The switch's words: label, tone and the longer detail.
 * @param {GpuStatus|null|undefined} status
 * @param {GpuClock} [clock] when they are read (tests name the moment and the zone)
 * @returns {{label: string, tone: GpuTone, detail: string}}
 */
export function gpuWords(status, clock = {}) {
  if (!status || !status.configured) return { label: '', tone: 'unknown', detail: '' };
  const parts = [];
  if (status.words_ro) parts.push(status.words_ro);
  if (status.rate_usd_per_hour) parts.push(`Buget ${status.rate_usd_per_hour} USD/oră, cel mult 1 GPU.`);
  const last = status.last_off;
  if (last && last.at) parts.push(lastOffDetail(last));
  const detail = parts.join(' ');
  if (status.mock) return { label: 'GPU: simulare', tone: 'off', detail };
  const sessions = status.sessions || [];
  const endpoints = status.endpoints || [];
  if (gpuLive(status)) {
    // What is being made, in words: the film, the scene, the take (2026-10-12, the Owner: «Ce
    // lucrează? Pentru ce film, ce cadru?» over «pas: scene_redo»). A session without words
    // (an older backend) says its step as before.
    const said = sessions.map((s) => s.words_ro || '').filter(Boolean);
    const steps = said.length
      ? [...new Set(said)].join('; ')
      : sessions.length
        ? `pas: ${[...new Set(sessions.map((s) => s.step))].join(', ')}`
        : 'pas: niciunul';
    const workers = workerWords(endpoints);
    // RunPod has not started the worker yet (a cache miss downloads the model): unbilled, though
    // the job waits in the queue; a worker already counted bills whatever the wait says.
    if (status.model_wait_ro && !workers.active) {
      return { label: `GPU: ${status.model_wait_ro} · ${steps}`, tone: 'armed', detail };
    }
    return { label: `${workers.words} · ${steps}`, tone: workers.tone, detail };
  }
  if (status.owner_hold) {
    // His «Oprește GPU acum» holds until he allows it again on its card.
    return { label: 'GPU oprit de tine · nu pornește până permiți din nou (Decizii)', tone: 'off', detail };
  }
  if (endpoints.length && endpoints.every((e) => e.state === 'OFF')) {
    return { label: stoppedLabel(last, clock), tone: 'off', detail };
  }
  return { label: 'GPU: stare necitită', tone: 'unknown', detail };
}

/**
 * @param {string} commandId
 * @returns {{schema_version: 1, command_id: string}}
 */
export function offCommand(commandId) {
  return { schema_version: 1, command_id: commandId };
}

/**
 * What the Owner reads after his press.
 * @param {{verified?: boolean, words_ro?: string, readings?: unknown[]}|null|undefined} result
 * @returns {string}
 */
export function offAnswer(result) {
  if (result && result.words_ro) return result.words_ro;
  if (result && result.verified) return 'GPU-ul RunPod este oprit și verificat.';
  return 'Am trimis oprirea GPU-ului RunPod, dar nu a confirmat încă; paznicul verifică din nou la fiecare minut.';
}

/** @param {any} node @param {string} name */
const hasClass = (node, name) => Boolean(node && node.classList && node.classList.contains(name));

/**
 * Where a dialog carries the stop: first among its header's actions (the inspector), else just
 * before its header's close key (the sheet, «Decizii», Settings), else first in the dialog (a
 * question box without a header).
 * @param {any} dialog @param {any} node
 */
export function placeInDialog(dialog, node) {
  const header = Array.from(/** @type {any[]} */ (dialog.children || [])).find((c) => hasClass(c, 'dialog-header'));
  if (!header) {
    dialog.prepend(node);
    return;
  }
  const inHeader = /** @type {any[]} */ (Array.from(header.children || []));
  const actions = inHeader.find((c) => hasClass(c, 'dialog-header-actions'));
  if (actions) {
    actions.prepend(node);
    return;
  }
  const close = inHeader.find((c) => hasClass(c, 'dialog-close'));
  if (close) header.insertBefore(node, close);
  else header.append(node);
}

/** A modal dialog hides the page; a non-modal one does not. @param {any} dialog */
function isModal(dialog) {
  try {
    return typeof dialog.matches === 'function' ? Boolean(dialog.matches(':modal')) : true;
  } catch {
    // a browser without :modal: treat the dialog as modal, so the stop is never missing
    return true;
  }
}

const FOCUSABLE_TAGS = new Set(['BUTTON', 'INPUT', 'SELECT', 'TEXTAREA']);

/** @param {any} node */
function focusableHere(node) {
  if (FOCUSABLE_TAGS.has(node.tagName)) return !node.disabled;
  if (node.tagName === 'A') return node.hasAttribute('href');
  return typeof node.hasAttribute === 'function' && node.hasAttribute('tabindex');
}

/** A control laid out on the page (a fake DOM without layout counts every node). @param {any} node */
const rendered = (node) => typeof node.getClientRects !== 'function' || node.getClientRects().length > 0;

/**
 * What a dialog's opening would have focused without the stop (FOCUS, 2026-10-09), best first:
 * its [autofocus] controls, then its focusable controls in tree order; the stop's box and every
 * hidden part are left out.
 * @param {any} dialog @param {any} box the stop's box
 * @returns {any[]}
 */
export function focusCandidates(dialog, box) {
  /** @type {any[]} */
  const auto = [];
  /** @type {any[]} */
  const plain = [];
  /** @param {any} node */
  const visit = (node) => {
    for (const child of Array.from(/** @type {any[]} */ (node.children || []))) {
      if (child === box || child.hidden) continue;
      if (typeof child.hasAttribute === 'function' && child.hasAttribute('autofocus')) auto.push(child);
      if (focusableHere(child) && rendered(child)) plain.push(child);
      visit(child);
    }
  };
  visit(dialog);
  return [...auto, ...plain.filter((node) => !auto.includes(node))];
}

/**
 * The page's one GPU stop: one reading, one press, any number of places.
 * @param {{api: (path: string, options?: any) => Promise<any>, notify: (message: string) => void,
 *   intervalMs?: number, freshEveryMs?: number, uuid?: () => string, now?: () => number,
 *   timeZone?: string}} options `timeZone`: the receipt's clock (default: the page's own)
 */
export function createGpuSwitch({ api, notify, intervalMs = 15000, freshEveryMs = FRESH_EVERY_MS, uuid, now = () => Date.now(), timeZone }) {
  const newId = uuid || (() => crypto.randomUUID());
  /** @type {Set<GpuMount>} */
  const mounts = new Set();
  /** @type {WeakMap<object, GpuMount>} */
  const byDialog = new WeakMap();
  /** @type {GpuStatus|null} */
  let status = null;
  let readFailed = false;
  /** @type {Promise<void>|null} */
  let reading = null;
  /** the next fresh reading not before this moment (ms, `now()`) */
  let freshAfter = Number.NEGATIVE_INFINITY;
  /** fresh readings failed in a row: each one doubles the wait before the next (FRESH) */
  let freshFailures = 0;
  /** @type {Promise<void>|null} */
  let pressing = null;
  /** the command id of the press in flight, the same for every place it was pressed from */
  let commandId = '';
  /**
   * His answer, and the GPU sessions open when he pressed: the answer is about those.
   * @type {{text: string, alert: boolean, at: number, sessions: Set<string>}|null}
   */
  let said = null;
  /** @type {ReturnType<typeof setTimeout>|null} */
  let timer = null;
  let stopped = false;
  /** @type {any} */
  let doc = null;
  /** @type {{disconnect(): void}|null} */
  let watcher = null;
  /** the MutationObserver class `watch` was given, for the open modals' contents */
  /** @type {any} */
  let Watcher = null;
  /** @type {{observe(target: any, options: any): void, disconnect(): void, takeRecords?: () => any[]}|null} */
  let inside = null;
  /** @type {WeakMap<object, {since: number, count: number}>} */
  const putBack = new WeakMap();

  /** @param {any} node @param {string} text */
  const say = (node, text) => {
    // an unchanged text is not written again: each write is a mutation the dialog watcher sees
    if (node.textContent !== text) node.textContent = text;
  };

  /** @param {GpuMount} mount */
  function paintOne(mount) {
    const words = gpuWords(status, { now: now(), timeZone });
    const configured = Boolean(status && status.configured);
    if (mount.dialog) {
      const recent = Boolean(said && now() - said.at < SAID_KEEP_MS);
      // a reading that failed while the GPU was live keeps the stop where it was
      const live = gpuLive(status) || Boolean(pressing) || recent;
      mount.container.hidden = !(configured && !(status && status.mock) && live);
      if (mount.said) {
        say(mount.said, recent && said ? said.text : '');
        mount.said.hidden = !recent;
        mount.said.dataset.tone = said && said.alert ? 'alert' : 'ok';
      }
    } else {
      mount.container.hidden = !configured;
    }
    say(mount.label, readFailed && configured ? 'GPU: stare necitită' : words.label);
    mount.label.title = words.detail;
    mount.container.title = words.detail;
    mount.container.dataset.tone = readFailed ? 'unknown' : words.tone;
    mount.button.disabled = Boolean(pressing);
  }

  function paint() {
    if (doc) sweep();
    for (const mount of mounts) {
      // a dialog that rebuilt its header (Settings) dropped the stop; the next sweep puts it back
      if (mount.dialog && mount.container.isConnected === false) {
        mounts.delete(mount);
        continue;
      }
      paintOne(mount);
    }
  }

  function schedule() {
    if (stopped || intervalMs <= 0) return;
    if (timer) clearTimeout(timer);
    const every = gpuLive(status) ? Math.min(intervalMs, freshEveryMs) : intervalMs;
    timer = setTimeout(() => { void refresh(); }, every);
  }

  /**
   * One reading at a time; fresh (a live RunPod read) only while live, at most every 10 s, and
   * after a failed fresh one only once its doubled wait has passed (FRESH).
   */
  function refresh() {
    if (reading) return reading;
    const fresh = gpuLive(status) && now() >= freshAfter;
    if (fresh) freshAfter = now() + freshEveryMs;
    const read = async () => {
      try {
        status = /** @type {GpuStatus} */ (await api(fresh ? '/runpod/gpu?fresh=1' : '/runpod/gpu'));
        readFailed = false;
        if (fresh) freshFailures = 0;
        // STALE ANSWER (2026-10-10): his answer stays a minute in the dialogs' stops, and a paid
        // round opened in that minute showed «GPU-ul RunPod este oprit și verificat.» under «GPU
        // permis … pas: motion». A session he did not stop makes the answer about another GPU
        // round: it goes; an answer about a stop still unconfirmed on his own session stays.
        const answered = said;
        if (answered && ((status && status.sessions) || []).some((s) => !answered.sessions.has(s.id))) said = null;
      } catch {
        readFailed = true;
        if (fresh) {
          // the backend may still be on that live read: do not start another beside it soon
          freshFailures += 1;
          freshAfter = now() + Math.min(freshEveryMs * 2 ** freshFailures, FRESH_BACKOFF_MAX_MS);
        }
      }
    };
    // `.then` runs after `reading` is set, even when the read failed at once
    reading = read().then(() => {
      reading = null;
      if (stopped) return;
      paint();
      schedule();
    });
    return reading;
  }

  /** «Oprește GPU acum», from any of its places: one POST, one command id. */
  function press() {
    if (pressing) return pressing;
    commandId = newId();
    const sessions = new Set(((status && status.sessions) || []).map((s) => s.id));
    const send = async () => {
      try {
        const result = await api('/runpod/gpu/off', {
          method: 'POST',
          body: JSON.stringify(offCommand(commandId)),
          timeoutMs: 180000,
        });
        return { text: offAnswer(result), alert: !(result && result.verified), at: now(), sessions };
      } catch (failure) {
        return { text: failure instanceof Error ? failure.message : String(failure), alert: true, at: now(), sessions };
      }
    };
    pressing = send().then(async (answer) => {
      said = answer;
      pressing = null;
      // the toolbar's line is on the page; a modal dialog hides it, so its stop says it too
      notify(answer.text);
      // a reading begun before the stop landed would show the GPU still on: read after it
      if (reading) await reading;
      if (!stopped) await refresh();
    });
    paint();
    return pressing;
  }

  /**
   * Shows the switch in ``container``.
   * @param {any} container
   * @param {{dialog?: boolean}} [where] a dialog's stop shows only while the GPU is live
   * @returns {GpuMount}
   */
  function mount(container, { dialog = false } = {}) {
    const owner = container.ownerDocument || document;
    const label = owner.createElement('span');
    label.className = dialog ? 'gpu-switch-state' : 'switch-state gpu-switch-state';
    const button = owner.createElement('button');
    button.type = 'button';
    button.className = dialog ? 'gpu-switch-off' : 'cam-btn cam-worded gpu-switch-off';
    button.textContent = 'Oprește GPU acum';
    button.addEventListener('click', () => press());
    container.append(label, button);
    let line = null;
    if (dialog) {
      line = owner.createElement('span');
      line.className = 'gpu-switch-said';
      line.setAttribute('role', 'status');
      line.setAttribute('aria-live', 'polite');
      line.hidden = true;
      container.append(line);
    }
    /** @type {GpuMount} */
    const placed = { container, label, button, said: line, dialog };
    mounts.add(placed);
    if (status || readFailed) paintOne(placed);
    return placed;
  }

  /** Whether the dialog's stop is in it. @param {any} dialog */
  function inPlace(dialog) {
    const had = byDialog.get(dialog);
    return Boolean(had && had.container.isConnected !== false && dialog.contains(had.container));
  }

  /**
   * The stop of one modal dialog, made once and found again on every sweep; a dialog that rebuilt
   * its content gets the same box back.
   * @param {any} dialog
   */
  function ensureIn(dialog) {
    const had = byDialog.get(dialog);
    if (had) {
      if (!inPlace(dialog)) placeInDialog(dialog, had.container);
      if (!mounts.has(had)) mounts.add(had);
      return had;
    }
    const owner = dialog.ownerDocument || doc;
    const box = owner.createElement('div');
    box.className = 'gpu-switch gpu-switch-dialog';
    box.setAttribute('role', 'group');
    box.setAttribute('aria-label', 'GPU RunPod');
    box.dataset.gpuSwitchMount = '';
    box.hidden = true;
    placeInDialog(dialog, box);
    const placed = mount(box, { dialog: true });
    byDialog.set(dialog, placed);
    return placed;
  }

  /** @returns {any[]} the open modal dialogs */
  function openModals() {
    if (!doc) return [];
    return Array.from(/** @type {any[]} */ (doc.querySelectorAll('dialog[open]'))).filter(isModal);
  }

  /** Every open modal dialog carries the stop. */
  function sweep() {
    for (const dialog of openModals()) ensureIn(dialog);
  }

  /**
   * A dialog that just opened with its stop already in it (a reopened sheet, inspector or door)
   * gave the stop the focus, being its first control: one Enter or Space would switch the GPU off
   * (FOCUS, 2026-10-09). The focus goes where the dialog would have put it without the stop; an
   * opener that already moved it (Decizii focuses its tab) is left alone.
   * @param {any} dialog @param {GpuMount} placed
   */
  function keepFocusOff(dialog, placed) {
    const owner = dialog.ownerDocument || doc;
    const active = owner ? owner.activeElement : null;
    if (!active || !placed.container.contains(active)) return;
    for (const node of focusCandidates(dialog, placed.container)) {
      if (typeof node.focus !== 'function') continue;
      node.focus({ preventScroll: true });
      if (owner.activeElement === node) return;
    }
    if (typeof active.blur === 'function') active.blur();
  }

  /** @param {any} node @returns {any} the dialog the node is in */
  function dialogOf(node) {
    for (let n = node; n; n = n.parentNode) if (n.tagName === 'DIALOG') return n;
    return null;
  }

  /**
   * A modal that rebuilt its content (Settings: replaceChildren on every render) gets its stop
   * back at once, not at the next poll (REBUILT, 2026-10-09). Only a dialog whose stop is missing
   * is touched, so the stop's own words never wake this again; and a page that kept removing it
   * (a dialog re-rendering on its own mutations) is left to the poll's sweep after a few tries in
   * a second rather than spun forever.
   * @param {any[]} records
   */
  function onInside(records) {
    if (stopped) return;
    const seen = new Set();
    for (const record of records) {
      const dialog = dialogOf(record.target);
      if (!dialog || seen.has(dialog)) continue;
      seen.add(dialog);
      if (!dialog.hasAttribute('open') || !isModal(dialog) || inPlace(dialog)) continue;
      const tries = putBack.get(dialog);
      const at = now();
      if (tries && at - tries.since < 1000 && tries.count >= 10) continue;
      putBack.set(dialog, tries && at - tries.since < 1000 ? { since: tries.since, count: tries.count + 1 } : { since: at, count: 1 });
      paintOne(ensureIn(dialog));
    }
  }

  /** The contents of every open modal are watched; only theirs, never the whole page's. */
  function watchInside() {
    if (!Watcher || !doc || stopped) return;
    if (inside) {
      const pending = typeof inside.takeRecords === 'function' ? inside.takeRecords() : [];
      inside.disconnect();
      if (pending.length) onInside(pending);
    } else {
      inside = new Watcher(onInside);
    }
    const watching = inside;
    if (!watching) return;
    for (const dialog of openModals()) watching.observe(dialog, { childList: true, subtree: true });
  }

  /**
   * Watches the document's dialogs: the one that opens gets the stop and a reading at once.
   * @param {any} target the document
   * @param {any} [Observer] MutationObserver (tests pass their own)
   */
  function watch(target, Observer = globalThis.MutationObserver) {
    if (!target || !target.body || typeof Observer !== 'function' || watcher) return;
    doc = target;
    Watcher = Observer;
    const observer = new Observer((/** @type {any[]} */ records) => {
      let opened = false;
      let moved = false;
      for (const record of records) {
        const node = record.target;
        if (!node || node.tagName !== 'DIALOG') continue;
        moved = true;
        if (!node.hasAttribute('open') || !isModal(node)) continue;
        const placed = ensureIn(node);
        paintOne(placed);
        keepFocusOff(node, placed);
        opened = true;
      }
      if (moved) watchInside();
      if (opened && !stopped) void refresh();
    });
    observer.observe(target.body, { subtree: true, attributes: true, attributeFilter: ['open'] });
    watcher = observer;
    sweep();
    watchInside();
  }

  return {
    mount,
    refresh,
    press,
    watch,
    /** @returns {GpuMount[]} */
    mounts: () => [...mounts],
    /** the command id of the press in flight ('' between presses) */
    commandId: () => (pressing ? commandId : ''),
    stop() {
      stopped = true;
      if (timer) clearTimeout(timer);
      if (watcher) watcher.disconnect();
      if (inside) inside.disconnect();
    },
  };
}

/**
 * Mount the switch in ``container`` (a <div id="gpu-switch" hidden>), and in every modal dialog
 * that opens while the GPU is live (GPU_STOP_REACHABLE).
 * @param {any} container
 * @param {{api: (path: string, options?: any) => Promise<any>, notify: (message: string) => void,
 *   intervalMs?: number, freshEveryMs?: number, uuid?: () => string, now?: () => number,
 *   timeZone?: string, document?: any, MutationObserver?: any, dialogs?: boolean}} options
 */
export function mountGpuSwitch(container, options) {
  const hub = createGpuSwitch(options);
  hub.mount(container);
  if (options.dialogs !== false) {
    const doc = options.document || container.ownerDocument || (typeof document === 'undefined' ? null : document);
    hub.watch(doc, options.MutationObserver);
  }
  if ((options.intervalMs ?? 15000) > 0) void hub.refresh();
  return hub;
}
