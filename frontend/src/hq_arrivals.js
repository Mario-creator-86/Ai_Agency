/**
 * THE LIVE ARRIVAL, SEEN FROM ACROSS THE ROOM (W12).
 *
 * Four strangers in a row said the same thing: at rest nothing inside moves — the truth, since
 * every employee is IDLE in the Owner's data — and when something real does arrive, it is real
 * but small at fit zoom. A monitor that starts to scroll is nine screen pixels.
 *
 * So a live arrival now says itself at the size of the building, for a few seconds, and only
 * when the backend sent it as it happened (the socket's `event`, never a `replay_event`, and
 * never old news an outbox flushed after a restart):
 *
 *   - an employee who starts to work (agent.state_changed to WORKING, or THINKING, which the
 *     register also words «lucrează») wears their world tag for ARRIVAL_TAG_MS —
 *     «Dr. Aris (Researcher) · lucrează · idei de subiect» — and one ring widens from their desk;
 *   - a stage of the day's run that starts (runbook.stage_started) brings the room that does
 *     that stage's work up to full light for ROOM_FLARE_MS, with a soft edge, and the façade
 *     sign glints once.
 *
 * Nothing here is new information: the words are the event's own (its employee, its task type
 * in the register's words), the room is the one whose employees run that stage in the backend
 * (runbook/stages.py). Nothing is fetched. Under reduced motion none of this is offered; the
 * state still changes, as it always did, without the flourish.
 *
 * Pure: the page offers events, the renderer asks what is on at a time. Node-tested.
 */

import { taskLabel } from './ledger.js';

/** How long an employee's tag stays up after the live event that started their work. */
export const ARRIVAL_TAG_MS = 4000;
/** How long a room stays at full light after the live start of a stage it works. */
export const ROOM_FLARE_MS = 3200;

/**
 * The stage whose room chip says «acum: …» (W25): the newest lit room's. A run's stages follow one
 * another, so of the rooms still fading only one is now; at 16× the end of the replay showed five
 * «acum:» chips at once beside «rularea s-a încheiat». The older rooms keep their light, without words.
 * @param {Array<{stage: string, age: number, quiet?: boolean}>|null|undefined} flares
 * @returns {string|null}
 */
export function chipStage(flares) {
  let best = null;
  // W26: a room lit before the replay's end keeps its light without words (Arrivals.quietChips)
  for (const f of flares || []) if (!f.quiet && (!best || f.age < best.age)) best = f;
  return best ? best.stage : null;
}
/** An event older (or further in the future) than this is history, not an arrival. */
export const ARRIVAL_FRESH_MS = 2 * 60 * 1000;

/** How the register words the end of work (ledger.js STATE_CHANGE_LABEL); other states end the tag. */
const ENDED = { IDLE: 'a terminat', ERROR: 'stare: eroare', FAILED: 'stare: eroare', BLOCKED: 'stare: blocaj' };

/** The states the register words «lucrează» (ledger.js STATE_CHANGE_LABEL). */
const WORK = new Set(['WORKING', 'THINKING', 'EXECUTING', 'RUNNING', 'PLANNING']);

/**
 * The rooms that do each stage's work, from who runs it in the backend (runbook/stages.py):
 * the Researcher proposes, the Researcher and the Fact Checker verify, the Director chooses and
 * reports, the Script Writer writes the film and the serial, the Voice Artist and the Video
 * Editor make the film, the Publisher reads the channels and publishes, the Accountant closes
 * the day's books. The preflight and the day's log have no runner and no room: the sign alone
 * says they started.
 * @type {Record<string, string[]>}
 */
export const STAGE_ROOMS = {
  preflight: [],
  performance_intake: ['publish_desk'],
  idea_generation: ['research_lab'],
  research_and_verification: ['research_lab', 'factcheck_room'],
  selection: ['director_suite'],
  script_and_storyboard: ['script_room'],
  serial_queue: ['script_room'],
  media: ['audio_booth', 'video_studio'],
  edit_and_qc: ['video_studio'],
  publish: ['publish_desk'],
  post_run: ['director_suite', 'accounting_office'],
  daily_log: [],
  serial_next: ['script_room'],
};

/**
 * The words on an arriving employee's tag: their name as the data gives it, «lucrează», and
 * the task in the register's words, or «—» when the event names none.
 * @param {any} agent @param {string|null|undefined} taskType
 */
export function arrivalWords(agent, taskType) {
  const name = String((agent && (agent.display_name || agent.role_name)) || 'Angajat');
  const task = taskType ? taskLabel(String(taskType)) : '—';
  return `${name} · lucrează · ${task}`;
}

/**
 * The palette key an arrival's marks are drawn in: the ring, the tag's bar and edge, the verb
 * «lucrează» and the room chip's dot. Live arrivals are the register's green (--ok-ink); in
 * «Reluarea zilei» they are the replay's violet (--replay-ink), so a tag cropped out of its
 * frame is still not a live one (W14: a stranger read the replayed tags as live).
 * @param {boolean} replay
 * @returns {'replayInk'|'okInk'}
 */
export function arrivalAccent(replay) {
  return replay ? 'replayInk' : 'okInk';
}

/**
 * The strength of a flourish at a moment of its life, 0..1: it rises, holds and falls.
 * @param {number} elapsed ms since it began @param {number} total ms
 * @param {number} [rise] ms @param {number} [fall] ms
 */
export function envelope(elapsed, total, rise = 280, fall = 700) {
  if (!Number.isFinite(elapsed) || elapsed < 0 || elapsed >= total) return 0;
  const up = rise > 0 ? Math.min(1, elapsed / rise) : 1;
  const down = fall > 0 ? Math.min(1, (total - elapsed) / fall) : 1;
  // eased at both ends, so it neither pops on nor snaps off
  const ease = (/** @type {number} */ t) => t * t * (3 - 2 * t);
  return Math.min(ease(up), ease(down));
}

/**
 * What is arriving now: the tags and the rooms, offered one live event at a time.
 */
export class Arrivals {
  constructor() {
    /** @type {Map<string, {id: string, words: string, start: number, end: number}>} */
    this.tagsById = new Map();
    /** @type {Map<string, {zone: string, stage: string, start: number, end: number, quiet?: boolean}>} */
    this.roomsByZone = new Map();
    /** A stage started live, for the façade's one glint: the id of the last one. */
    this.signBeat = 0;
    /** Flourishes offered so far, for QA. */
    this.count = { tags: 0, rooms: 0 };
  }

  /**
   * One event from the socket. Only a live one, fresh, starts anything.
   * @param {any} event the backend's event
   * @param {{live: boolean, now: number, wallNow?: number, agents?: any[], replay?: boolean}} context
   *   `now`: the page's frame clock (performance.now), `wallNow`: Date.now() for freshness.
   *   `replay`: the event comes from «Reluarea zilei» (W13, day_replay.js), played forward from
   *   the record under the replay's own grade and chip: it is not live and not fresh, and it
   *   still says itself in the world, labelled by everything around it as the replay's.
   * @returns {'tag'|'room'|null} what it started
   */
  offer(event, context) {
    if (!event) return null;
    const at = Date.parse(String(event.timestamp || ''));
    if (!Number.isFinite(at)) return null;
    if (context.replay !== true) {
      if (context.live !== true) return null;
      const wall = Number.isFinite(context.wallNow) ? Number(context.wallNow) : Date.now();
      if (Math.abs(wall - at) > ARRIVAL_FRESH_MS) return null;
    }
    const type = String(event.event_type || '');
    const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
    const now = context.now;
    if (type === 'agent.state_changed') {
      const state = String(payload.runtime_state || '').toUpperCase();
      if (!WORK.has(state)) {
        // Work that ends changes the tag's words at once: it never says «lucrează» of someone
        // who has stopped. It says what the register says (ledger.js), and stays up long
        // enough to be read.
        const id = String(payload.agent_id || event.aggregate_id || '');
        const tag = this.tagsById.get(id);
        if (tag && tag.end > now) {
          const said = /** @type {Record<string, string>} */ (ENDED)[state];
          if (said) {
            tag.words = tag.words.replace(/ · lucrează · /, ` · ${said} · `);
            tag.end = Math.max(Math.min(tag.end, now + ARRIVAL_TAG_MS), now + 1600);
          } else {
            tag.end = Math.min(tag.end, now + 450);
          }
        }
        return null;
      }
      const id = String(payload.agent_id || event.aggregate_id || '');
      const agent = (context.agents || []).find((a) => a && String(a.id || a.agent_id) === id);
      if (!id || !agent) return null;
      const words = arrivalWords(agent, payload.task_type);
      const held = this.tagsById.get(id);
      if (held && held.end > now && held.words.replace(/ · (a terminat|stare: eroare|stare: blocaj) · /, ' · lucrează · ') === words) {
        // the same work said again (a run of claims, one after another): the tag stays up and
        // says «lucrează» again, it does not arrive again
        held.words = words;
        held.end = now + ARRIVAL_TAG_MS;
        return null;
      }
      this.tagsById.set(id, { id, words, start: now, end: now + ARRIVAL_TAG_MS });
      this.count.tags += 1;
      return 'tag';
    }
    if (type === 'runbook.stage_started') {
      const stage = String(payload.stage || '');
      this.signBeat += 1;
      const zones = STAGE_ROOMS[stage] || [];
      for (const zone of zones) this.roomsByZone.set(zone, { zone, stage, start: now, end: now + ROOM_FLARE_MS });
      this.count.rooms += zones.length;
      return 'room';
    }
    return null;
  }

  /**
   * The tags up at `now`, each with its strength.
   * @param {number} now
   * @returns {Array<{id: string, words: string, strength: number, age: number}>}
   */
  tags(now) {
    const out = [];
    for (const [id, tag] of this.tagsById) {
      if (now >= tag.end) {
        this.tagsById.delete(id);
        continue;
      }
      out.push({ id, words: tag.words, strength: envelope(now - tag.start, tag.end - tag.start, 220, 500), age: now - tag.start });
    }
    return out;
  }

  /**
   * The rooms at full light at `now`, each with its strength.
   * @param {number} now
   * @returns {Array<{zone: string, stage: string, strength: number, age: number, quiet: boolean}>}
   */
  rooms(now) {
    const out = [];
    for (const [zone, room] of this.roomsByZone) {
      if (now >= room.end) {
        this.roomsByZone.delete(zone);
        continue;
      }
      out.push({ zone, stage: room.stage, strength: envelope(now - room.start, ROOM_FLARE_MS, 320, 1100), age: now - room.start, quiet: Boolean(room.quiet) });
    }
    return out;
  }

  /** Whether anything is on, so the renderer can skip the pass. @param {number} now */
  active(now) {
    return this.tags(now).length > 0 || this.rooms(now).length > 0;
  }

  /**
   * The replay reached its end (W26): nothing is «now» any more. The rooms still lit keep their
   * fading light, and none of them says «acum: …» beside «rularea s-a încheiat». A stage offered
   * after this (the replay played again) speaks as before.
   */
  quietChips() {
    for (const room of this.roomsByZone.values()) room.quiet = true;
  }

  /** Sign-out, or reduced motion turned on mid-flourish: nothing stays up. */
  clear() {
    this.tagsById.clear();
    this.roomsByZone.clear();
  }
}
