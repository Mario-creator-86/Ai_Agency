/**
 * PAID WORK UNDER WAY (2026-10-12): what the studio has at RunPod right now, read from the
 * register's own events; never from the clock alone, never invented.
 *
 * The register's head line said «Nicio producție în lucru.» and every name tag «în așteptare»
 * while a film's continuation had a scene's image or motion at RunPod for eight to thirty-seven
 * minutes: `productionStatus` read only the daily run's stages and the workflow's stage, and the
 * employees' states say nothing while the editor waits for a provider. The signals of that work
 * are all in the events the page already receives (backend/app/providers/runpod/gpu_session.py,
 * backend/app/runbook/stages.py, backend/app/media/assembler.py, worded by
 * backend/app/events_feed.py):
 *
 *  - `runpod.gpu_session_opened` (payload.purpose image|video, payload.step, payload.storyboard_id;
 *    the actor is the editor who opened it) until a newer `runpod.gpu_off_verified` or
 *    `runpod.gpu_forced_off` for the same session (its aggregate_id) or the same endpoint
 *    (payload.endpoint_id). `runpod.gpu_off_unverified` ends the work too: the studio asked for
 *    the off; whether the GPU billed on after that is the GPU switch's question, not this line's;
 *  - `media.scene_take_recorded` with status SUBMITTED until the same take (aggregate_id) is
 *    recorded again (PAID, REFUSED, LOST, or any later status);
 *  - `runbook.qc_paid_redo`: a scene's redo bought (scene_index, kinds, open_motion);
 *  - `runbook.film_continued`: a continuation ended (status COMPLETED / SKIPPED / BLOCKED).
 *
 * The words come from the events: the film's title (`film_title`), the purpose and the step as
 * the backend wrote them, and the backend's own sentence (`words_ro`) wherever one serves. The
 * register keeps its newest 400 events, so a very old open could stand with its off scrolled out:
 * a session or a take older than its cap is not claimed as work.
 *
 * Pure, so what the head line and the name tags say is node-tested.
 */

/** A GPU session with no off event this old is not claimed as work (the register may have lost the off). */
export const SESSION_MAX_MS = 3 * 60 * 60 * 1000;
/** A take submitted this long ago with no result recorded is not claimed as a wait. */
export const SUBMITTED_MAX_MS = 2 * 60 * 60 * 1000;
/** How long after a continuation ended the studio is still said to be at that film. */
export const CONTINUATION_RECENT_MS = 5 * 60 * 1000;
/** How long after a paid redo was bought, with no session yet, the redo is the work under way. */
export const REDO_RECENT_MS = 10 * 60 * 1000;

/** A session's step, as the head line says it (the backend's codes, gpu_session.py). */
const STEP_WORDS = {
  stills: 'imaginile scenelor',
  test_shot: 'cadrul de probă',
  motion: 'mișcarea scenelor',
  scene_redo: 'refacerea unei scene',
  assemble: 'asamblarea',
  render: 'randarea',
};
/** What one scene's take is called, by the session's purpose. */
const PURPOSE_WHAT = { image: 'imaginea', video: 'clipul' };
/** The same, for a whole step. */
const PURPOSE_PLURAL = { image: 'imaginile', video: 'clipurile' };
/** What the editor waits for from RunPod, on the name tag. */
const WAIT_WHAT = { image: 'imaginile', video: 'clipul' };
/** One take's kind in words (`media.scene_take_recorded` payload.kind). */
const KIND_WORDS = { still: 'imaginea', test_shot: 'cadrul de probă', motion: 'clipul', narration: 'narațiunea' };
/** Where a continuation ended, in words (events_feed.py _WALK_RO), for an event without words. */
const WALK_WORDS = { COMPLETED: 'a mers până la capăt', BLOCKED: 's-a oprit', SKIPPED: 'n-a putut porni', WAITING: 'așteaptă', INTERRUPTED: 'a fost întreruptă' };

/**
 * @typedef {{id: string, endpoint: string, purpose: string, step: string, storyboardId: string, title: string,
 *   since: number|null, actorId: string, actorName: string, words: string}} GpuSession
 * @typedef {{take: string, scene: number|string|null, kind: string, storyboardId: string, title: string,
 *   since: number|null, actorId: string, words: string}} SubmittedTake
 * @typedef {{scene: number|string|null, kinds: string[], openMotion: boolean, storyboardId: string, title: string,
 *   at: number|null, words: string, recent: boolean}} PaidRedo
 * @typedef {{status: string, reason: string, storyboardId: string, title: string, at: number|null, words: string,
 *   recent: boolean}} Continuation
 * @typedef {{sessions: GpuSession[], submitted: SubmittedTake[], redo: PaidRedo|null, continuation: Continuation|null,
 *   busy: boolean, text: string|null, since: number|null}} PaidWork
 */

/** @param {any} event */
function timeOf(event) {
  const ms = Date.parse(String((event && event.timestamp) || ''));
  return Number.isFinite(ms) ? ms : null;
}

/** @param {any} event */
function payloadOf(event) {
  return event && event.payload && typeof event.payload === 'object' ? event.payload : {};
}

/**
 * The film's title as the backend named it beside the event, or ''. A storyboard's title carries
 * the record's «Storyboard:» label («Storyboard: The Zero Script Club»); the head line says the
 * film, as the goal does (backend/app/goal.py _title).
 * @param {any} event
 */
function titleOf(event) {
  const title = event && typeof event.film_title === 'string' ? event.film_title.trim() : '';
  return title.replace(/^storyboard:\s*/i, '').trim();
}

/** The backend's sentence for the event, or ''. @param {any} event */
function wordsOf(event) {
  return event && typeof event.words_ro === 'string' ? event.words_ro.trim() : '';
}

/** @param {any} event @returns {{id: string, name: string}} */
function actorOf(event) {
  const actor = event && event.actor && typeof event.actor === 'object' ? event.actor : null;
  return { id: actor && actor.agent_id ? String(actor.agent_id) : '', name: actor && actor.name ? String(actor.name) : '' };
}

/** «The Zero Script Club» in guillemets, or «…» when the record has no title (as events_feed.py writes it). @param {string} title */
function quoted(title) {
  return `«${title || '…'}»`;
}

/** «de 12 min», «de sub un minut», or '' without a clock. @param {number|null} now @param {number|null} since */
export function forMinutes(now, since) {
  if (now === null || since === null) return '';
  const minutes = Math.floor(Math.max(0, now - since) / 60000);
  return minutes < 1 ? 'de sub un minut' : `de ${minutes} min`;
}

/**
 * What is at RunPod now, from the register's events (newest first).
 * @param {any[]} events newest first
 * @param {number|null} [now] epoch ms; without it the clock is not consulted (the tests of the wording)
 * @returns {PaidWork}
 */
export function paidWork(events, now = null) {
  const list = Array.isArray(events) ? events : [];
  /** @type {GpuSession[]} */
  const sessions = [];
  /** session ids and endpoint ids a newer off event closed */
  const closed = new Set();
  /** @type {SubmittedTake[]} */
  const submitted = [];
  /** takes recorded again after their submission */
  const settled = new Set();
  /** @type {PaidRedo|null} */
  let redo = null;
  /** @type {Continuation|null} */
  let continuation = null;
  for (const event of list) {
    const type = String((event && event.event_type) || '');
    if (!type.startsWith('runpod.') && !type.startsWith('runbook.') && type !== 'media.scene_take_recorded') continue;
    const payload = payloadOf(event);
    const when = timeOf(event);
    const age = now !== null && when !== null ? now - when : null;
    if (type === 'runpod.gpu_off_verified' || type === 'runpod.gpu_forced_off' || type === 'runpod.gpu_off_unverified') {
      if (event.aggregate_id) closed.add(String(event.aggregate_id));
      if (payload.endpoint_id) closed.add(String(payload.endpoint_id));
    } else if (type === 'runpod.gpu_session_opened') {
      const id = String(event.aggregate_id || '');
      const endpoint = String(payload.endpoint_id || '');
      if ((id && closed.has(id)) || (endpoint && closed.has(endpoint))) continue;
      if (age !== null && age > SESSION_MAX_MS) continue;
      const actor = actorOf(event);
      sessions.push({ id, endpoint, purpose: String(payload.purpose || ''), step: String(payload.step || ''), storyboardId: String(payload.storyboard_id || ''), title: titleOf(event), since: when, actorId: actor.id, actorName: actor.name, words: wordsOf(event) });
    } else if (type === 'media.scene_take_recorded') {
      const take = String(event.aggregate_id || '');
      if (String(payload.status || '').toUpperCase() !== 'SUBMITTED') {
        if (take) settled.add(take);
        continue;
      }
      if ((take && settled.has(take)) || (age !== null && age > SUBMITTED_MAX_MS)) continue;
      submitted.push({ take, scene: payload.scene_number ?? null, kind: String(payload.kind || ''), storyboardId: String(payload.storyboard_id || ''), title: titleOf(event), since: when, actorId: actorOf(event).id, words: wordsOf(event) });
    } else if (type === 'runbook.qc_paid_redo' && !redo) {
      redo = {
        scene: payload.scene_index ?? null,
        kinds: Array.isArray(payload.kinds) ? payload.kinds.map(String) : [],
        openMotion: Boolean(payload.open_motion),
        storyboardId: String(payload.storyboard_id || event.aggregate_id || ''),
        title: titleOf(event),
        at: when,
        words: wordsOf(event),
        recent: age === null || age <= REDO_RECENT_MS,
      };
    } else if (type === 'runbook.film_continued' && !continuation) {
      continuation = {
        status: String(payload.status || '').toUpperCase(),
        reason: String(payload.reason || ''),
        storyboardId: String(event.aggregate_id || payload.storyboard_id || ''),
        title: titleOf(event),
        at: when,
        words: wordsOf(event),
        recent: age === null || age <= CONTINUATION_RECENT_MS,
      };
    }
  }
  // a continuation of the same film that ended after a session opened: that session's work is
  // over, whatever the register kept of its off
  const over = continuation && continuation.at !== null ? continuation : null;
  const open = over
    ? sessions.filter((s) => !(s.storyboardId && s.storyboardId === over.storyboardId && s.since !== null && over.at !== null && over.at > s.since))
    : sessions;
  // a redo bought before the newest continuation ended belongs to that finished walk
  const redoLive = Boolean(redo && redo.recent && (!continuation || redo.at === null || continuation.at === null || redo.at > continuation.at));
  const newest = open[0] || null;
  let text = null;
  let since = null;
  let busy = false;
  if (newest) {
    busy = true;
    since = newest.since;
    const minutes = forMinutes(now, newest.since);
    const inBrackets = minutes ? ` (${minutes})` : '';
    const what = PURPOSE_WHAT[/** @type {keyof typeof PURPOSE_WHAT} */ (newest.purpose)] || 'lucrarea';
    // the redo this session works on: bought for the same film, recorded since the session opened
    const redoHere = redo && redoLive && (!newest.storyboardId || redo.storyboardId === newest.storyboardId) && redo.at !== null && newest.since !== null && redo.at >= newest.since ? redo : null;
    if (redoHere && redoHere.scene !== null && redoHere.scene !== '') {
      const take = redoHere.openMotion && newest.purpose === 'video' ? 'clipul' : what;
      text = `Se reface scena ${redoHere.scene} a filmului ${quoted(newest.title || redoHere.title)}: ${take} e la RunPod${inBrackets}`;
    } else if (newest.step === 'scene_redo') {
      text = `Se reface o scenă a filmului ${quoted(newest.title)}: ${what} e la RunPod${inBrackets}`;
    } else {
      const step = STEP_WORDS[/** @type {keyof typeof STEP_WORDS} */ (newest.step)] || PURPOSE_PLURAL[/** @type {keyof typeof PURPOSE_PLURAL} */ (newest.purpose)] || 'lucrarea';
      const gpu = `(GPU pornit${minutes ? ` ${minutes}` : ''})`;
      // without a title the backend's own sentence says whose GPU and for what
      text = newest.title || !newest.words ? `Se filmează ${quoted(newest.title)}: ${step} ${gpu}` : `${newest.words.replace(/\.$/, '')} ${gpu}`;
    }
  } else if (submitted.length) {
    const take = submitted[0];
    busy = true;
    since = take.since;
    const minutes = forMinutes(now, take.since);
    const inBrackets = minutes ? ` (${minutes})` : '';
    if (take.words) {
      text = `${take.words.replace(/\.$/, '')}; se așteaptă rezultatul${inBrackets}`;
    } else {
      const what = KIND_WORDS[/** @type {keyof typeof KIND_WORDS} */ (take.kind)] || 'înregistrarea';
      const where = take.scene !== null && take.scene !== '' ? ` scenei ${take.scene}` : '';
      text = `Se așteaptă ${what}${where}${take.title ? ` a filmului «${take.title}»` : ''} de la furnizor${inBrackets}`;
    }
  } else if (continuation && continuation.recent) {
    busy = true;
    since = continuation.at;
    text = continuation.words || `Filmul ${quoted(continuation.title)} ${WALK_WORDS[/** @type {keyof typeof WALK_WORDS} */ (continuation.status)] || 'a continuat'}`;
  } else if (redo && redoLive) {
    busy = true;
    since = redo.at;
    text = redo.words || `Refacerea plătită a scenei ${redo.scene ?? '…'} a filmului ${quoted(redo.title)} a fost cumpărată`;
  }
  return { sessions: open, submitted, redo, continuation, busy, text, since };
}

/**
 * The name tag of the employee whose GPU session is open: «așteaptă imaginile de la RunPod»
 * (purpose image) or «așteaptă clipul de la RunPod» (purpose video) instead of «în așteptare».
 * A real state of their own (working, thinking, an error) is said as itself.
 * @param {PaidWork|null|undefined} work
 * @param {string} agentId
 * @param {string} [runtimeState]
 * @returns {string|null}
 */
export function gpuWaitWord(work, agentId, runtimeState = 'IDLE') {
  const state = String(runtimeState || 'IDLE').toUpperCase();
  if (state !== 'IDLE' && state !== 'UNKNOWN') return null;
  const sessions = work && Array.isArray(work.sessions) ? work.sessions : [];
  const session = sessions.find((s) => s.actorId && s.actorId === String(agentId));
  if (!session) return null;
  return `așteaptă ${WAIT_WHAT[/** @type {keyof typeof WAIT_WHAT} */ (session.purpose)] || 'rezultatele'} de la RunPod`;
}

/**
 * What the office shows of the paid work, as one key: the name tags redraw only when it changes.
 * @param {PaidWork} work
 */
export function paidWorkKey(work) {
  return [work.busy ? 'busy' : 'rest', work.text || '', ...work.sessions.map((s) => `${s.id}:${s.actorId}:${s.purpose}`)].join('|');
}
