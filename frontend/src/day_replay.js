/**
 * «RELUAREA ZILEI»: THE NEWEST REAL WORKING DAY, PLAYED BACK FROM ITS RECORD (W13).
 *
 * A visitor who arrives while the studio rests sees a still building, and that is the truth:
 * every employee is idle in the data. A game would let him watch the last match. This is that,
 * honest by construction:
 *
 *   - THE SOURCE is the studio's own record. The run is the newest finished one the runbook
 *     recorded (/runbook/runs); its events are the ones the studio wrote while it ran
 *     (/events), read once, in pages, when the replay starts. The run's window is cut by the
 *     run's own start and finish events (their aggregate id is the run's id). Nothing is added,
 *     reordered or invented: the replay is the record, time-compressed, with the real
 *     timestamps shown.
 *   - THE WORLD AT A MOMENT is a reducer over the events up to that moment (frameAt): who was
 *     working on what, the day's track as the sign showed it, the run as far as it had got
 *     (runAt: the stages recorded by then, and its summary only once it ended), the topics
 *     proposed, each employee's last task. A value the events do not carry is not shown: the
 *     page's live treasury is not the treasury of that night, so the replay's treasury is «—».
 *   - THE CLOCK plays the record in order at one steady rate, the busy part of the run fitted
 *     into about a minute at 1× (buildSchedule), and 4× and 16× faster than that. A stretch of
 *     QUIET_MS or more with nothing recorded passes in QUIET_PAGE_MS and says so, with its real
 *     times. Under reduced motion nothing animates: the replay steps from one stage to the next.
 *   - LIVE WINS: a live event that changes the world (interruptsReplay) ends the replay; the
 *     world is never live and replayed at once.
 *
 * Pure: the page gives it the record and asks what the world was at a time. Node-tested.
 */

import { dayTrack, runStageWord, shortDate } from './hud_charts.js';
import { lastTasks } from './hq_readouts.js';
import { boardTopics } from './hq_screens.js';
import { isBookkeeping, runDoneLine } from './ledger.js';

/** How long the whole run lasts on the page at 1×: about a minute, whatever its real length. */
export const REPLAY_TARGET_MS = 60000;
/** The speeds offered, as multiples of that. */
export const REPLAY_SPEEDS = Object.freeze([1, 4, 16]);
/** One page of the record (the backend's own cap for /events). */
export const REPLAY_PAGE = 300;
/** The most pages one replay reads: 12 000 events, far more than any run has written. */
export const REPLAY_MAX_PAGES = 40;
/** Past the run's recorded finish, how far the read still looks for its finish event. */
export const REPLAY_TAIL_MS = 5000;
/** A live event ends the replay by itself this long after it arrives (the prompt's countdown). */
export const LIVE_WINS_MS = 6000;
/** Under reduced motion, how long each stage holds before the next one, at 1×. */
export const REPLAY_STEP_MS = 3500;
/** How long a replayed speech caption stays up, at most, on the page. */
export const REPLAY_BUBBLE_MS = 3200;

/** The states the register words «lucrează» (ledger.js, hq_arrivals.js). */
const WORK = new Set(['WORKING', 'THINKING', 'EXECUTING', 'RUNNING', 'PLANNING']);

/** @param {any} event */
const stamp = (event) => Date.parse(String((event && event.timestamp) || ''));

/**
 * The run a replay plays: the newest run the runbook recorded as finished (a start and a finish
 * time, the finish after the start). A run still under way is not a replay: it is live.
 * @param {any[]|null|undefined} runs /runbook/runs -> runs
 * @returns {any|null}
 */
export function replayableRun(runs) {
  let best = null;
  let bestAt = -Infinity;
  for (const run of Array.isArray(runs) ? runs : []) {
    if (!run || !run.id) continue;
    const start = Date.parse(String(run.started_at || ''));
    const end = Date.parse(String(run.finished_at || ''));
    if (!Number.isFinite(start) || !Number.isFinite(end) || end < start) continue;
    if (start > bestAt) {
      best = run;
      bestAt = start;
    }
  }
  return best;
}

/**
 * Where to look for the first event at or after `t`, narrowed by events the page already holds.
 * The answer is the smallest `after` whose first following event is at or after `t`:
 * an event held from before `t` means the answer is at least its sequence; one from `t` on means
 * it is at most its sequence less one. `cursor` is the newest sequence the studio has written.
 * @param {any[]} known events the page holds (any order)
 * @param {number} t ms
 * @param {number} cursor
 * @returns {{lo: number, hi: number}}
 */
export function searchBounds(known, t, cursor) {
  let lo = 0;
  let hi = Math.max(0, Math.floor(Number(cursor) || 0));
  for (const event of Array.isArray(known) ? known : []) {
    const seq = Number(event && event.sequence);
    const at = stamp(event);
    if (!Number.isFinite(seq) || !Number.isFinite(at)) continue;
    if (at < t) lo = Math.max(lo, seq);
    else hi = Math.min(hi, seq - 1);
  }
  return { lo: Math.min(lo, hi), hi };
}

/**
 * The smallest `after` whose first following event is at or after `t`, by bisection over the
 * record: `probe(k)` answers the first event after sequence k (or null). A probe that lands in a
 * gap jumps to the event it found, so a sparse record is crossed in fewer reads.
 * @param {(after: number) => Promise<any|null>} probe
 * @param {number} t ms
 * @param {{lo: number, hi: number}} bounds
 * @returns {Promise<{after: number, requests: number}>}
 */
export async function locateStart(probe, t, bounds) {
  let { lo, hi } = bounds;
  let requests = 0;
  while (lo < hi) {
    const mid = Math.floor((lo + hi) / 2);
    const first = await probe(mid);
    requests += 1;
    const at = first ? stamp(first) : Infinity;
    if (!(at < t)) hi = mid;
    else lo = Math.min(hi, Math.max(mid + 1, Number(first.sequence) || mid + 1));
  }
  return { after: lo, requests };
}

/**
 * The run's events, read from the studio's record once. A studio that reads its log by time
 * (`/events?since=`, W15) gives the run's first page in one request: `options.since(iso, limit)`
 * asks from a moment before the run's recorded start, and the page is believed only when it
 * names the instant it was read from (an older studio ignores the parameter and answers from the
 * log's beginning). Otherwise the start is located by bisection. Then pages forward until the
 * run's own finish event (or its recorded finish time) is passed.
 * @param {(after: number, limit: number) => Promise<{events?: any[], next_cursor?: number, has_more?: boolean}>} get
 * @param {any} run a replayableRun
 * @param {{cursor?: number, known?: any[], since?: (iso: string, limit: number) => Promise<any>}} [options]
 * @returns {Promise<{events: any[], requests: number, complete: boolean, method: 'since'|'bisect'}>}
 */
export async function readRecord(get, run, options = {}) {
  const start = Date.parse(String(run.started_at));
  const end = Date.parse(String(run.finished_at));
  let requests = 0;
  /** @type {any} */
  let firstPage = null;
  let method = /** @type {'since'|'bisect'} */ ('bisect');
  let after = 0;
  if (options.since) {
    const from = new Date(start - REPLAY_TAIL_MS).toISOString();
    requests += 1;
    const page = await options.since(from, REPLAY_PAGE).catch(() => null);
    if (page && typeof page.since === 'string' && Array.isArray(page.events)) {
      firstPage = page;
      method = 'since';
    }
  }
  if (!firstPage) {
    const bounds = searchBounds(options.known || [], start, options.cursor || 0);
    const probe = async (/** @type {number} */ k) => {
      const page = await get(k, 1);
      return (page && Array.isArray(page.events) && page.events[0]) || null;
    };
    const located = await locateStart(probe, start, bounds);
    requests += located.requests;
    after = located.after;
  }
  /** @type {any[]} */
  const events = [];
  let pages = 0;
  let complete = false;
  while (!complete && pages < REPLAY_MAX_PAGES) {
    const page = firstPage || (await get(after, REPLAY_PAGE));
    if (!firstPage) requests += 1;
    firstPage = null;
    pages += 1;
    const rows = page && Array.isArray(page.events) ? page.events : [];
    for (const event of rows) {
      if (stamp(event) > end + REPLAY_TAIL_MS) {
        complete = true;
        break;
      }
      events.push(event);
      if (event.event_type === 'runbook.daily_run_finished' && String(event.aggregate_id) === String(run.id)) {
        complete = true;
        break;
      }
    }
    if (complete || !page || !page.has_more || !rows.length) {
      // the record ends here: everything the studio wrote was read
      if (!complete && page && !page.has_more) complete = true;
      break;
    }
    after = Number(page.next_cursor) || Number(rows[rows.length - 1].sequence) || after + rows.length;
  }
  return { events, requests, complete, method };
}

/** The most moments one read of the books asks about (the backend's own cap). */
export const FIGURES_MAX = 240;
/**
 * The most reads of the books one replay makes, all of them when it starts (W17): 8 x 240 moments.
 * A run that moved its figures more often than that shows «—» on its walls after the last moment
 * read, never a stale figure.
 */
export const FIGURES_READS_MAX = 8;
/** A reading is taken this long after the event that moved a figure, and shown from its event on. */
export const FIGURE_STEP_MS = 1;

/**
 * The moments at which the replay asks the books what the Treasury and the tokens plate said
 * (/economy/as-of, W15): the run's start and end, and every event after which a figure can have
 * changed: a finished agent run (its tokens and price are counted when it finishes) and every
 * economy event (a cost recorded or billed, a hold, a budget, money in). The books' rows are
 * stamped before the event that announces them, so a reading a millisecond after the event's own
 * stamp (FIGURE_STEP_MS: the page's clock counts whole milliseconds, the record microseconds)
 * holds it. Between two such moments nothing the walls show can change. Sorted, without repeats,
 * every one of them (W17: it was cut at 240, and the walls then kept the 239th moment's figures to
 * the run's end).
 * @param {Timeline} timeline
 * @returns {string[]} ISO instants
 */
export function figureMoments(timeline) {
  const times = new Set([timeline.start]);
  for (const event of timeline.events) {
    const type = String(event.event_type || '');
    if (type === 'agent.run_completed' || type.startsWith('economy.')) {
      const at = stamp(event);
      if (Number.isFinite(at)) times.add(at + FIGURE_STEP_MS);
    }
  }
  const last = timeline.end + FIGURE_STEP_MS;
  const sorted = [...times].filter((t) => Number.isFinite(t) && t < last).sort((a, b) => a - b);
  sorted.push(last);
  return sorted.map((t) => new Date(t).toISOString());
}

/**
 * The books' reads for a replay, or null when the studio cannot answer them (W16). /events?since
 * and /economy/as-of came with the same backend (migration 0047): a studio whose log did not
 * name the instant asked (readRecord's method 'bisect') predates both, so the books are not
 * asked at all, rather than answered with a 404 the browser logs as an error. Its walls say «—».
 *
 * W17: every moment is asked, in reads of at most FIGURES_MAX moments, all made when the replay
 * starts (nothing is read per frame), at most FIGURES_READS_MAX of them. `until` is the first
 * moment not asked (ms), or null when all were: from it on the walls say «—» (figuresAt).
 * @param {Timeline|null} timeline
 * @param {'since'|'bisect'|string|null|undefined} method how readRecord read the run's events
 * @returns {{reads: Array<{path: string, moments: string[]}>, moments: string[], until: number|null}|null}
 */
export function figuresQuery(timeline, method) {
  if (!timeline || method !== 'since') return null;
  const all = figureMoments(timeline);
  const cap = FIGURES_MAX * FIGURES_READS_MAX;
  const moments = all.slice(0, cap);
  const until = all.length > cap ? Date.parse(all[cap]) : null;
  const reads = [];
  for (let i = 0; i < moments.length; i += FIGURES_MAX) {
    const chunk = moments.slice(i, i + FIGURES_MAX);
    reads.push({ path: `/economy/as-of?${chunk.map((m) => `at=${encodeURIComponent(m)}`).join('&')}`, moments: chunk });
  }
  return { reads, moments, until };
}

/**
 * The books' reading that held at `t`: the newest one taken at or before it; null before the
 * first (a replayed wall then says «—»), and null from `until` on (W17: the first moment the
 * books were not asked about; what the walls said then is not known).
 * @param {Array<{at: string}>|null|undefined} readings sorted by `at`
 * @param {number} t ms
 * @param {number|null} [until] ms
 */
export function figuresAt(readings, t, until = null) {
  if (!Array.isArray(readings)) return null;
  if (until !== null && Number.isFinite(until) && t + FIGURE_STEP_MS >= until) return null;
  let found = null;
  for (const reading of readings) {
    const at = Date.parse(String(reading && reading.at));
    if (!Number.isFinite(at) || at > t + FIGURE_STEP_MS) break;
    found = reading;
  }
  return found;
}

/**
 * The books' answer, believed only when it answers the moments asked, in order: an older studio
 * answers 404 (the page's read fails) and nothing else would do. The readings, sorted by moment.
 * @param {any} answer /economy/as-of
 * @param {string[]} asked
 * @returns {any[]|null}
 */
export function acceptFigures(answer, asked) {
  const readings = answer && Array.isArray(answer.readings) ? answer.readings : null;
  if (!readings || readings.length !== asked.length) return null;
  for (let i = 0; i < asked.length; i += 1) {
    const r = readings[i];
    if (!r || Date.parse(String(r.at)) !== Date.parse(asked[i]) || !r.treasury || !r.budget) return null;
  }
  return readings.slice().sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
}

/**
 * @typedef {{stage: string, index: number, total: number, at: number, word: string}} ReplayStage
 * @typedef {{runtime_state: string, task_type: string, detail: string, lifecycle: string}} ReplayAgent
 * @typedef {{
 *   run: any, runId: string, date: string|null, start: number, end: number, duration: number,
 *   events: any[], times: number[], stages: ReplayStage[], initial: Record<string, ReplayAgent>,
 *   complete: boolean,
 * }} Timeline
 */

/**
 * Each employee's state as the run began, from the record alone. Someone whose first recorded
 * change in the run ends work (a change to a state that is not work, or a finished task) was at
 * work when the run began, on that task; everyone else was not working. Nothing else is assumed.
 * @param {any[]} events the run's events, oldest first
 * @returns {Record<string, ReplayAgent>}
 */
export function initialStates(events) {
  /** @type {Record<string, ReplayAgent>} */
  const out = {};
  const seen = new Set();
  for (const event of events) {
    const type = String(event.event_type || '');
    const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
    let id = '';
    if (type === 'agent.state_changed') id = String(payload.agent_id || event.aggregate_id || '');
    else if (type === 'agent.run_completed') id = String(payload.agent_id || '');
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const ends = type === 'agent.run_completed' || !WORK.has(String(payload.runtime_state || '').toUpperCase());
    out[id] = ends
      ? { runtime_state: 'WORKING', task_type: String(payload.task_type || ''), detail: '', lifecycle: 'ACTIVE' }
      : { runtime_state: 'IDLE', task_type: '', detail: '', lifecycle: 'ACTIVE' };
  }
  return out;
}

/**
 * The replay's timeline: the run and its events, oldest first, cut to the run's own window.
 * @param {any} run a replayableRun
 * @param {any[]} events what readRecord read
 * @param {{complete?: boolean}} [options]
 * @returns {Timeline}
 */
export function buildTimeline(run, events, options = {}) {
  const startRec = Date.parse(String(run.started_at));
  const endRec = Date.parse(String(run.finished_at));
  const sorted = (Array.isArray(events) ? events : [])
    .filter((e) => e && Number.isFinite(stamp(e)))
    .slice()
    .sort((a, b) => Number(a.sequence) - Number(b.sequence));
  const id = String(run.id);
  const i0 = sorted.findIndex((e) => e.event_type === 'runbook.daily_run_started' && String(e.aggregate_id) === id);
  const i1 = sorted.findIndex((e) => e.event_type === 'runbook.daily_run_finished' && String(e.aggregate_id) === id);
  // The run's own start and finish events bound it; without them, the times the runbook recorded.
  const inside = i0 >= 0 && i1 >= i0 ? sorted.slice(i0, i1 + 1) : sorted.filter((e) => stamp(e) >= startRec && stamp(e) <= endRec + 1000);
  /** @type {number[]} */
  const times = [];
  for (const e of inside) times.push(Math.max(times.length ? times[times.length - 1] : -Infinity, stamp(e)));
  const start = Math.min(startRec, times.length ? times[0] : startRec);
  const end = Math.max(endRec, times.length ? times[times.length - 1] : endRec);
  /** @type {ReplayStage[]} */
  const stages = [];
  const opening = inside.find((e) => e.event_type === 'runbook.daily_run_started');
  if (opening) {
    const total = Number(opening.payload && opening.payload.stages) || 0;
    stages.push({ stage: 'preflight', index: 1, total, at: stamp(opening), word: runStageWord('preflight') });
  }
  for (const e of inside) {
    if (e.event_type !== 'runbook.stage_started' || !e.payload || !e.payload.stage) continue;
    stages.push({ stage: String(e.payload.stage), index: Number(e.payload.index) || stages.length + 1, total: Number(e.payload.total) || 0, at: stamp(e), word: runStageWord(e.payload.stage) });
  }
  return {
    run,
    runId: id,
    date: typeof run.business_date === 'string' ? run.business_date : null,
    start,
    end,
    duration: Math.max(0, end - start),
    events: inside,
    times,
    stages,
    initial: initialStates(inside),
    complete: options.complete !== false,
  };
}

/**
 * How many of the timeline's events had happened by `t` (inclusive).
 * @param {Timeline} timeline @param {number} t
 */
export function indexAt(timeline, t) {
  const times = timeline.times;
  let lo = 0;
  let hi = times.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= t) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/**
 * The run as the runbook's record stood at `t`: the stages it had recorded by then, and its
 * status, finish and summary only once it had finished.
 * @param {any} run @param {number} t
 */
export function runAt(run, t) {
  const end = Date.parse(String(run.finished_at || ''));
  const finished = Number.isFinite(end) && t >= end;
  const stages = (Array.isArray(run.stages) ? run.stages : []).filter((/** @type {any} */ s) => {
    const at = Date.parse(String((s && s.at) || ''));
    return Number.isFinite(at) && at <= t;
  });
  return {
    ...run,
    stages,
    stages_completed: stages.length,
    status: finished ? run.status : 'RUNNING',
    finished_at: finished ? run.finished_at : null,
    summary: finished ? run.summary : null,
    stopped_at_stage: finished ? run.stopped_at_stage : null,
    stop_reason: finished ? run.stop_reason : null,
  };
}

/**
 * @typedef {{
 *   index: number, t: number, agents: Record<string, ReplayAgent>,
 *   track: import('./hud_charts.js').DayTrack, stage: string|null, run: any,
 *   tasks: {tasks: Record<string, any>, key: string}, topics: {titles: string[], key: string},
 * }} ReplayFrame
 */

/**
 * THE WORLD AT A MOMENT OF THE RUN: the reducer. The same rules the live page follows
 * (office_state.js handleDomainEvent), applied to the events up to `t`.
 * @param {Timeline} timeline @param {number} t
 * @returns {ReplayFrame}
 */
export function frameAt(timeline, t) {
  const n = indexAt(timeline, t);
  /** @type {Record<string, ReplayAgent>} */
  const agents = {};
  for (const [id, s] of Object.entries(timeline.initial)) agents[id] = { ...s };
  const slice = timeline.events.slice(0, n);
  for (const event of slice) {
    const type = String(event.event_type || '');
    const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
    if (type === 'agent.state_changed') {
      const id = String(payload.agent_id || event.aggregate_id || '');
      const a = agents[id] || (agents[id] = { runtime_state: 'IDLE', task_type: '', detail: '', lifecycle: 'ACTIVE' });
      a.runtime_state = String(payload.runtime_state || a.runtime_state);
      a.detail = a.runtime_state === 'IDLE' ? '' : String(payload.detail || a.detail || '');
      a.task_type = String(payload.task_type || (a.runtime_state === 'IDLE' ? '' : a.task_type));
    } else if (type === 'agent.run_completed') {
      const id = String(payload.agent_id || '');
      if (agents[id]) agents[id].runtime_state = 'IDLE';
    } else if (type === 'agent.paused' || type === 'agent.resumed') {
      const id = String(event.aggregate_id || '');
      const a = agents[id] || (agents[id] = { runtime_state: 'IDLE', task_type: '', detail: '', lifecycle: 'ACTIVE' });
      a.lifecycle = type === 'agent.paused' ? 'PAUSED' : 'ACTIVE';
    }
  }
  const newestFirst = slice.slice().reverse();
  const track = dayTrack(newestFirst);
  return {
    index: n,
    t,
    agents,
    track,
    stage: track.running,
    run: runAt(timeline.run, t),
    tasks: lastTasks(newestFirst),
    topics: boardTopics(newestFirst),
  };
}

/**
 * The page's agents (the layout's people, at their desks) as they were at the frame: the same
 * people, each with the state the record gives them then.
 * @param {any[]} agents officeState.agents @param {ReplayFrame} frame
 */
export function agentsAt(agents, frame) {
  return (Array.isArray(agents) ? agents : []).map((agent) => {
    const id = String(agent.id || agent.agent_id || '');
    const s = frame.agents[id] || { runtime_state: 'IDLE', task_type: '', detail: '', lifecycle: 'ACTIVE' };
    return { ...agent, runtime_state: s.runtime_state, task_type: s.task_type, detail: s.detail, lifecycle: s.lifecycle };
  });
}

/* ------------------------------------------------------------------------------------------
 * THE CLOCK
 * ---------------------------------------------------------------------------------------- */

/** A stretch of the record at least this long with no event in it is a quiet stretch… */
export const QUIET_MS = 30000;
/** …and passes in this long on the page at 1×, saying that it does (replayWords). */
export const QUIET_PAGE_MS = 2000;

/**
 * @typedef {{t0: number, t1: number, p0: number, p1: number, quiet: boolean}} ScheduleSegment
 * @typedef {{segments: ScheduleSegment[], pageDuration: number, factor: number, start: number, end: number}} Schedule
 */

/**
 * The replay's schedule: which moment of the record is on the page at each moment of the page,
 * at 1×. The record is played in its own order at one steady rate, `factor` (the busy part of
 * the run fitted into about a minute, never slower than the run itself), except where nothing
 * was recorded for QUIET_MS or longer: such a stretch passes in QUIET_PAGE_MS, and the replay
 * says so with its real times. Nothing is skipped: every event is crossed, in order.
 * @param {{start: number, end: number, times: number[]}} timeline
 * @param {{target?: number, quietMs?: number, quietPageMs?: number}} [options]
 * @returns {Schedule}
 */
export function buildSchedule(timeline, options = {}) {
  const target = options.target || REPLAY_TARGET_MS;
  const quietMs = options.quietMs || QUIET_MS;
  const quietPageMs = options.quietPageMs || QUIET_PAGE_MS;
  const points = [timeline.start];
  for (const t of timeline.times) if (t > points[points.length - 1] && t < timeline.end) points.push(t);
  if (timeline.end > points[points.length - 1]) points.push(timeline.end);
  /** @type {Array<{t0: number, t1: number, quiet: boolean}>} */
  const spans = [];
  for (let i = 1; i < points.length; i += 1) {
    const quiet = points[i] - points[i - 1] >= quietMs;
    const last = spans[spans.length - 1];
    // neighbouring busy stretches play at one rate: they are one segment
    if (last && !last.quiet && !quiet) last.t1 = points[i];
    else spans.push({ t0: points[i - 1], t1: points[i], quiet });
  }
  const quietCount = spans.filter((s) => s.quiet).length;
  const busy = spans.filter((s) => !s.quiet).reduce((sum, s) => sum + (s.t1 - s.t0), 0);
  const budget = Math.max(target / 2, target - quietCount * quietPageMs);
  const factor = Math.max(1, busy / budget);
  /** @type {ScheduleSegment[]} */
  const segments = [];
  let p = 0;
  for (const s of spans) {
    const length = s.quiet ? Math.min(quietPageMs, s.t1 - s.t0) : (s.t1 - s.t0) / factor;
    segments.push({ t0: s.t0, t1: s.t1, p0: p, p1: p + length, quiet: s.quiet });
    p += length;
  }
  return { segments, pageDuration: p, factor, start: timeline.start, end: timeline.end };
}

/** The segment a page moment falls in. @param {Schedule} schedule @param {number} p */
function segmentAtPage(schedule, p) {
  const list = schedule.segments;
  for (const s of list) if (p < s.p1) return s;
  return list[list.length - 1] || null;
}

/** The segment a record moment falls in. @param {Schedule} schedule @param {number} t */
export function segmentAt(schedule, t) {
  const list = schedule.segments;
  for (const s of list) if (t < s.t1) return s;
  return list[list.length - 1] || null;
}

/** The record's moment at a page moment (1× page ms from the start). @param {Schedule} schedule @param {number} p */
export function recordAt(schedule, p) {
  const s = segmentAtPage(schedule, p);
  if (!s) return schedule.start;
  if (p <= s.p0) return s.t0;
  if (p >= s.p1) return s.t1;
  return s.t0 + ((p - s.p0) / (s.p1 - s.p0)) * (s.t1 - s.t0);
}

/** The page moment at which the record's moment `t` is shown. @param {Schedule} schedule @param {number} t */
export function pageAt(schedule, t) {
  const s = segmentAt(schedule, t);
  if (!s) return 0;
  if (t <= s.t0) return s.p0;
  if (t >= s.t1) return s.p1;
  return s.p0 + ((t - s.t0) / (s.t1 - s.t0)) * (s.p1 - s.p0);
}

/** The replay's clock: a moment of the record, playing or paused, at a speed. */
export class ReplayClock {
  /**
   * @param {{start: number, end: number, times: number[]}} timeline
   * @param {{target?: number, quietMs?: number, quietPageMs?: number}} [options]
   */
  constructor(timeline, options = {}) {
    this.schedule = buildSchedule(timeline, options);
    this.start = timeline.start;
    this.end = timeline.end;
    /** The steady rate of the busy record at 1×. */
    this.factor = this.schedule.factor;
    /** Where the page is in the schedule, in 1× page ms. */
    this.p = 0;
    this.speed = 1;
    this.playing = false;
  }

  /** The record's moment on the page now. */
  get t() {
    return recordAt(this.schedule, this.p);
  }

  get ended() {
    return this.p >= this.schedule.pageDuration;
  }

  /** The stretch of the record being shown, quiet or busy. */
  get segment() {
    return segmentAt(this.schedule, this.t);
  }

  /** Record ms shown per page ms here, at the current speed. */
  get rate() {
    const s = this.segment;
    const k = s && s.p1 > s.p0 ? (s.t1 - s.t0) / (s.p1 - s.p0) : this.factor;
    return k * this.speed;
  }

  /** @param {number} dtMs page ms since the last frame @returns {number} the record's moment */
  advance(dtMs) {
    if (!this.playing) return this.t;
    this.p = Math.min(this.schedule.pageDuration, this.p + Math.max(0, dtMs) * this.speed);
    if (this.ended) this.playing = false;
    return this.t;
  }

  /** @param {number} t a moment of the record */
  seek(t) {
    const clamped = Math.max(this.start, Math.min(this.end, Number.isFinite(Number(t)) ? Number(t) : this.start));
    this.p = pageAt(this.schedule, clamped);
    return this.t;
  }

  /** @param {number} speed one of REPLAY_SPEEDS */
  setSpeed(speed) {
    if (REPLAY_SPEEDS.includes(speed)) this.speed = speed;
  }

  play() {
    if (this.ended) this.p = 0;
    this.playing = true;
  }

  pause() {
    this.playing = false;
  }

  /** Where the page is along the replay, 0..1 (the scrubber's axis). */
  get fraction() {
    return this.schedule.pageDuration ? this.p / this.schedule.pageDuration : 1;
  }

  /** @param {number} f 0..1 along the replay */
  seekFraction(f) {
    this.p = Math.max(0, Math.min(1, Number(f) || 0)) * this.schedule.pageDuration;
    return this.t;
  }
}

/**
 * The next stage's start after `t` (the end of the run after the last one).
 * @param {Timeline} timeline @param {number} t
 */
export function nextStageTime(timeline, t) {
  const next = timeline.stages.find((s) => s.at > t + 1);
  return next ? next.at : timeline.end;
}

/**
 * The stage before: the start of the one under way, or, within 1.5 s of that start, the one
 * before it, so a second press goes further back. The run's start before the first.
 * @param {Timeline} timeline @param {number} t
 */
export function prevStageTime(timeline, t) {
  const earlier = timeline.stages.filter((s) => s.at < t - 1500);
  return earlier.length ? earlier[earlier.length - 1].at : timeline.start;
}

/**
 * The events crossed between two moments while playing forward: what the world announces (a
 * tag, a room, a caption). A seek crosses nothing.
 * @param {Timeline} timeline @param {number} from @param {number} to
 */
export function crossed(timeline, from, to) {
  if (!(to > from)) return [];
  return timeline.events.slice(indexAt(timeline, from), indexAt(timeline, to));
}

/* ------------------------------------------------------------------------------------------
 * THE WORDS
 * ---------------------------------------------------------------------------------------- */

/** @type {Map<string, Intl.DateTimeFormat>} */
const CLOCKS = new Map();
/** @param {number} ms @param {string|undefined} timeZone @param {boolean} seconds */
function clockText(ms, timeZone, seconds) {
  const key = `${timeZone || ''}|${seconds}`;
  let f = CLOCKS.get(key);
  if (!f) {
    try {
      f = new Intl.DateTimeFormat('ro-RO', { timeZone, hour: '2-digit', minute: '2-digit', second: seconds ? '2-digit' : undefined, hourCycle: 'h23' });
    } catch {
      f = new Intl.DateTimeFormat('ro-RO', { hour: '2-digit', minute: '2-digit', second: seconds ? '2-digit' : undefined, hourCycle: 'h23' });
    }
    CLOCKS.set(key, f);
  }
  return f.format(ms);
}

/** A span of the run as minutes and seconds: «5:06». @param {number} ms */
export function spanText(ms) {
  const s = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = String(s % 60).padStart(2, '0');
  return h ? `${h}:${String(m).padStart(2, '0')}:${sec}` : `${m}:${sec}`;
}

/** «de 12 ori mai repede», the rate as the Owner reads it. @param {number} rate */
export function rateWords(rate) {
  const n = Math.max(1, Math.round(Number(rate) || 1));
  // «de 20 de ori»: the «de» a Romanian speaker cannot leave out from twenty on
  return n === 1 ? 'în timp real' : `de ${n}${n % 100 >= 20 || n % 100 === 0 ? ' de' : ''} ori mai repede decât rularea`;
}

/**
 * W24: the pace keys, each saying the replay's pace against the run at that key, the same number
 * the line beside them says (rateWords): the busy record's factor times 1, 4 and 16, rounded. The
 * keys were «1× · 4× · 16×» of the replay's own pace, and «1×» pressed beside «de 4 ori mai repede
 * decât rularea» read as a contradiction.
 * @param {number} factor the busy record's rate at 1× (ReplayClock.factor)
 * @returns {Array<{speed: number, label: string, name: string}>}
 */
export function paceKeys(factor) {
  const f = Number(factor) > 0 ? Number(factor) : 1;
  return REPLAY_SPEEDS.map((speed) => {
    const n = Math.max(1, Math.round(f * speed));
    return { speed, label: `${n}×`, name: rateWords(n) };
  });
}

/**
 * W24: how long a quiet stretch of the record is on the page at this key: «trece în 2 s», «trece
 * în 0,5 s» (the decimal comma), never under a tenth.
 * @param {{p0: number, p1: number}} segment @param {number} [speed]
 */
export function quietSpan(segment, speed = 1) {
  const s = Math.max(0.1, (Number(segment.p1) - Number(segment.p0)) / (Number(speed) > 0 ? Number(speed) : 1) / 1000);
  const text = String(Math.round(s * 10) / 10).replace('.', ',');
  return `trece în ${text} s`;
}

/**
 * W24: what the bar shows of a moment, as one key: the bar is rewritten when it changes. Keyed on
 * the clock's second alone, the run's own «11:38 din 11:39» stayed beside «rularea s-a încheiat»
 * when the run's start was not on a whole second.
 * @param {{clock: string, progress: string}} words
 */
export function barTick(words) {
  return `${words.clock}|${words.progress}`;
}

/**
 * Everything the replay says of a moment, in the studio's own time zone. In a quiet stretch
 * (`quiet`, a schedule segment) the line says so, with the stretch's real times, and how long it is
 * on the page at this key (`speed`, W24).
 * @param {Timeline} timeline @param {number} t
 * @param {{timeZone?: string, stage?: string|null, rate?: number, staff?: number, speed?: number, quiet?: {t0: number, t1: number, p0?: number, p1?: number}|null}} [context]
 */
export function replayWords(timeline, t, context = {}) {
  const tz = context.timeZone;
  const day = shortDate(timeline.date || '') || '';
  const startHour = clockText(timeline.start, tz, false);
  const clock = clockText(t, tz, true);
  const ended = t >= timeline.end;
  const stage = ended ? 'rularea s-a încheiat' : context.stage ? `acum: ${runStageWord(context.stage)}` : t <= timeline.start ? 'începutul rulării' : 'între două etape';
  const progress = `${spanText(t - timeline.start)} din ${spanText(timeline.duration)}`;
  const staff = Number(context.staff) || 0;
  const who = staff ? `${staff}${staff >= 20 ? ' de' : ''} ${staff === 1 ? 'angajat' : 'angajați'}` : 'Sediul AMN-AI';
  return {
    chip: `RELUARE · ${day ? `${day} · ` : ''}${startHour}`,
    clock,
    clockLabel: 'ATUNCI',
    stage,
    progress,
    rate: context.quiet
      ? `nicio schimbare în registru ${clockText(context.quiet.t0, tz, true)}–${clockText(context.quiet.t1, tz, true)} · ${quietSpan({ p0: Number(context.quiet.p0) || 0, p1: Number(context.quiet.p1) || QUIET_PAGE_MS }, context.speed || 1)}`
      : rateWords(context.rate || 1),
    caption: `${who} · reluarea rulării din ${day || 'registru'}, ${startHour}`,
    captionShort: `${who} · reluare`,
    sentence: `Reluare, rularea din ${day || 'registru'}: ora ${clock}, ${stage}.`,
    title: `Reluarea rulării din ${day || 'registru'}, pornită la ${startHour}: evenimentele înregistrate de studio, redate în ordine, ${rateWords(context.rate || 1)}. Nu este live.`,
  };
}

/**
 * The tick marks on the scrubber: where each stage started, along the replay (the scrubber's
 * axis is the replay's own time, so a quiet stretch is as short on it as it is on the page).
 * @param {Timeline} timeline @param {Schedule} schedule
 */
export function stageTicks(timeline, schedule) {
  const span = schedule.pageDuration || 1;
  return timeline.stages.map((s) => ({ ...s, p: Math.max(0, Math.min(1, pageAt(schedule, s.at) / span)) }));
}

/**
 * The quiet stretches, for the scrubber: where each lies along the replay, and its real times.
 * @param {Schedule} schedule
 */
export function quietSpans(schedule) {
  const span = schedule.pageDuration || 1;
  return schedule.segments.filter((s) => s.quiet).map((s) => ({ from: s.p0 / span, to: s.p1 / span, t0: s.t0, t1: s.t1 }));
}

/* ------------------------------------------------------------------------------------------
 * WHAT THE REPLAY SAYS IN THE WORLD, AND WHAT ENDS IT
 * ---------------------------------------------------------------------------------------- */

/**
 * A replayed speech caption: what the employee said (agent.message_sent) or the line a finished
 * task speaks (agent.run_completed, SUCCEEDED), the same words the live page uses, labelled as
 * the replay's with the moment it was said. null when the event says nothing.
 * @param {any} event @param {{timeZone?: string}} [context]
 * @returns {{agentId: string, text: string, label: string}|null}
 */
export function replayBubble(event, context = {}) {
  const type = String((event && event.event_type) || '');
  const payload = event && event.payload && typeof event.payload === 'object' ? event.payload : {};
  const label = `RELUARE · ${clockText(stamp(event), context.timeZone, true)}`;
  if (type === 'agent.message_sent') {
    const said = payload.text || payload.content;
    return said ? { agentId: String(event.aggregate_id || ''), text: String(said), label } : null;
  }
  if (type === 'agent.run_completed' && payload.status === 'SUCCEEDED' && payload.agent_id) {
    return { agentId: String(payload.agent_id), text: `${runDoneLine(payload)} ✓`, label };
  }
  return null;
}

/**
 * A replayed caption's lines: the words as the record wrote them, in their own case, wrapped at
 * `width` characters, at most `max` lines; what does not fit ends in «…» at a word's end (the
 * register holds the whole text). A word longer than a line is cut, never dropped.
 * @param {string} text @param {number} [width] @param {number} [max]
 * @returns {string[]}
 */
export function captionLines(text, width = 56, max = 2) {
  const words = String(text || '').trim().split(/\s+/).filter(Boolean);
  /** @type {string[]} */
  const lines = [];
  let line = '';
  let i = 0;
  for (; i < words.length; i += 1) {
    let word = words[i];
    if (word.length > width) word = `${word.slice(0, width - 1)}…`;
    const next = line ? `${line} ${word}` : word;
    if (next.length <= width) {
      line = next;
      continue;
    }
    lines.push(line);
    line = word;
    if (lines.length === max) break;
  }
  if (i >= words.length) {
    // everything fit
    if (line) lines.push(line);
    return lines;
  }
  // more words than lines: the last line ends in «…», within the width
  let last = lines[max - 1] || '';
  while (last.length + 1 > width && last.includes(' ')) last = last.slice(0, last.lastIndexOf(' '));
  lines[max - 1] = `${last.replace(/[\s,;:.–—-]+$/, '')}…`;
  return lines.slice(0, max);
}

/**
 * Whether a live event changes the world, and so ends a replay: an employee's state, speech or
 * task, a stage of a run, a workflow that moves to a stage, a film, a publication, the serial,
 * a fact, a review, money. The watchdog's routine rows and a catalogue refresh do not, nor does
 * the studio closing its own stale asks (ledger.js isBookkeeping): it changes nothing he sees.
 * @param {any} event
 */
export function interruptsReplay(event) {
  const type = String((event && event.event_type) || '');
  if (!type) return false;
  if (isBookkeeping(event)) return false;
  if (type.startsWith('workflow.')) return Boolean(event.payload && event.payload.current_stage);
  return /^(agent|runbook|media|publishing|story|factual|director|economy)\./.test(type);
}
