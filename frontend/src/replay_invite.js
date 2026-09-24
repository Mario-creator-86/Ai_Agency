/**
 * THE REPLAY OFFERED (W15): an invitation to «Reluarea zilei», once, when the studio truly rests.
 *
 * A stranger said the replay was the first thing on the page that amazed him, and that nothing
 * invited him to it: it sat behind a dock key and the last line of the façade's card. When the
 * visitor has entered the building, the entry has settled, and the studio is at rest by its own
 * record (no run under way, nobody at work, a finished run to replay), a pane of the drawers'
 * glass stands in the free room under the building for this browser session, once:
 *
 *   «Studioul se odihnește acum. Ultima rulare încheiată: sâmbătă 12.09, 23:48–23:59 · 12 etape ·
 *   1 film publicat.»  [Vezi reluarea] [Nu acum]
 *
 * Every word of the second line is the runbook's record of that run. It never loops and never
 * starts the replay by itself; «Nu acum» and Esc put it away for the session; a live event, or
 * the studio starting to work, takes it away at once. It is said once in the polite region.
 *
 * The rules are pure and node-tested; ReplayInvite is their hands on the page.
 */

import { shortDate } from './hud_charts.js';

/** The states the register words «lucrează»: the studio is not at rest while anyone is in one. */
const WORK = new Set(['WORKING', 'THINKING', 'EXECUTING', 'RUNNING', 'PLANNING', 'REVIEWING']);

/** How long after the entry has settled the invitation waits: the building is seen first. */
export const INVITE_DELAY_MS = 1500;

/** Where the page remembers, for this browser session, that the invitation was offered. */
export const INVITE_KEY = 'amn.replay.invite';
/**
 * After the visitor's camera (zoom, drag, a drawer's glide) has rested this long, the invitation is
 * placed again under the building where it now is (W18: zoomed in, it stayed over L1).
 */
export const INVITE_RELAYOUT_MS = 180;

const WEEKDAYS = ['duminică', 'luni', 'marți', 'miercuri', 'joi', 'vineri', 'sâmbătă'];

/** Publication states that count as a film out (as the runbook's recount counts a legacy run). */
const OUT = new Set(['PUBLISHED', 'REMOTE_CONFIRMED', 'SCHEDULED']);

/** @param {number} n @param {string} one @param {string} many */
function counted(n, one, many) {
  if (n === 1) return `1 ${one}`;
  const rest = n % 100;
  return `${n} ${n >= 20 && (rest === 0 || rest >= 20) ? 'de ' : ''}${many}`;
}

/** @param {number} ms @param {string|undefined} timeZone */
function hourText(ms, timeZone) {
  const options = /** @type {Intl.DateTimeFormatOptions} */ ({ hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  try {
    return new Intl.DateTimeFormat('ro-RO', { ...options, timeZone }).format(ms);
  } catch {
    return new Intl.DateTimeFormat('ro-RO', options).format(ms);
  }
}

/**
 * How many films the run published, from its own publish stage: the backend's own count
 * (`produced`), else its list, else a legacy run's single publication. A finished run with no
 * publish stage published nothing. null when there is no run.
 * @param {any} run
 * @returns {number|null}
 */
export function publishedCount(run) {
  if (!run) return null;
  const stage = Array.isArray(run.stages) ? run.stages.find((/** @type {any} */ s) => s && s.stage === 'publish') : null;
  if (!stage) return 0;
  if (Number.isFinite(Number(stage.produced)) && stage.produced !== null) return Math.max(0, Math.floor(Number(stage.produced)));
  const artefacts = stage.artefacts && typeof stage.artefacts === 'object' ? stage.artefacts : {};
  if (Array.isArray(artefacts.published)) return artefacts.published.length;
  return typeof artefacts.publication_id === 'string' && artefacts.publication_id && OUT.has(String(artefacts.publication_status)) ? 1 : 0;
}

/**
 * The invitation's words, from the run's record only; null when the record lacks its times.
 * @param {any} run a finished run (day_replay.js replayableRun)
 * @param {{timeZone?: string}} [context]
 * @returns {{lead: string, line: string, sentence: string, day: string}|null}
 */
export function inviteWords(run, context = {}) {
  if (!run) return null;
  const start = Date.parse(String(run.started_at || ''));
  const end = Date.parse(String(run.finished_at || ''));
  if (!Number.isFinite(start) || !Number.isFinite(end)) return null;
  const date = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(run.business_date || ''));
  const day = shortDate(String(run.business_date || ''));
  const weekday = date ? WEEKDAYS[new Date(Date.UTC(Number(date[1]), Number(date[2]) - 1, Number(date[3]))).getUTCDay()] : '';
  const when = `${[weekday, day].filter(Boolean).join(' ')}${day ? ', ' : ''}${hourText(start, context.timeZone)}–${hourText(end, context.timeZone)}`;
  const parts = [when];
  const done = Number(run.stages_completed);
  const total = Number(run.stages_total);
  if (Number.isFinite(done) && Number.isFinite(total) && total > 0) {
    parts.push(done === total ? counted(total, 'etapă', 'etape') : `${done} din ${counted(total, 'etapă', 'etape')}`);
  }
  const films = publishedCount(run);
  if (films !== null) parts.push(films === 0 ? 'niciun film publicat' : counted(films, 'film publicat', 'filme publicate'));
  const lead = 'Studioul se odihnește acum.';
  const line = `Ultima rulare încheiată: ${parts.join(' · ')}.`;
  return {
    lead,
    line,
    day,
    sentence: `${lead} ${line} «Vezi reluarea» o redă din registrul studioului; Esc închide invitația.`,
  };
}

/**
 * Whether the studio truly rests, by its own record: a finished run to replay, no run under way,
 * and nobody at work.
 * @param {{run: any, live: boolean, agents: any[]}} facts
 */
export function restingNow(facts) {
  if (!facts || !facts.run || facts.live) return false;
  const agents = Array.isArray(facts.agents) ? facts.agents : [];
  return !agents.some((a) => a && WORK.has(String(a.runtime_state || '').toUpperCase()));
}

/** Where the building's ground floor begins, as a share of its height from the roof (the plates). */
export const GROUND_FLOOR = 0.78;

/**
 * @typedef {{left: number, top: number, right: number, bottom: number}} Box
 * @typedef {{x: number, y: number, w: number, h: number}} Rect
 */

/**
 * Where the invitation stands, in the render's CSS px: centred in the room the drawers leave,
 * under the building on the street when it fits there, else as low as the room allows. It never
 * rises over the building's middle (its floors of work): if the room leaves no such place, null.
 * @param {{room: Box, building: Rect, card: {w: number, h: number}, gap?: number}} input
 * @returns {{x: number, y: number}|null}
 */
export function invitePlacement(input) {
  const { room, building, card } = input;
  const gap = input.gap ?? 12;
  const width = room.right - room.left;
  if (!(width > card.w + 2 * gap)) return null;
  const centre = room.left + width / 2;
  const x = Math.round(Math.min(room.right - gap - card.w, Math.max(room.left + gap, centre - card.w / 2)));
  const lowest = room.bottom - gap - card.h;
  const under = building.y + building.h + gap;
  // the floors of work end about four fifths down (L1's floor); the ground floor's glass and the
  // street are the free room
  const floor = building.y + building.h * GROUND_FLOOR;
  const y = Math.round(Math.min(lowest, Math.max(under, room.top + gap)));
  if (y < floor || y < room.top) return null;
  return { x, y };
}

/**
 * Read and write the session's memory of the invitation; a storage that throws (a private
 * window, blocked site data) reads as «not offered» and writes nothing.
 * @param {() => Storage|null} storage
 */
export function inviteMemory(storage) {
  return {
    seen() {
      try {
        const s = storage();
        return Boolean(s && s.getItem(INVITE_KEY));
      } catch {
        return false;
      }
    },
    remember() {
      try {
        const s = storage();
        if (s) s.setItem(INVITE_KEY, '1');
      } catch {
        // the invitation is then offered again in this session's next page; nothing breaks
      }
    },
  };
}

/**
 * Whether a click came from the keyboard (Enter or Space on a button, or assistive technology):
 * the browser gives such a click no pointer press, so its `detail` is 0 (W17).
 * @param {{detail?: number}|null|undefined} event
 */
export function fromKeyboard(event) {
  return Boolean(event) && event.detail === 0;
}

/**
 * WHERE THE KEYBOARD GOES (W17). The page moves focus by itself only for a visitor who started
 * the replay from the keyboard: onto the replay's play key when it starts, and back where they
 * were when it ends. A pointer visitor's focus is left alone, so the dock key's focus label
 * («RELUARE») never ends up standing over the live building after a mouse visit; the one
 * exception is a focus that sits on the replay's own controls when they go (it would otherwise
 * be lost with them).
 * @param {{keyboard: boolean, inControls: boolean}} how
 * @returns {{onStart: boolean, onExit: boolean}}
 */
export function replayFocus({ keyboard, inControls }) {
  return { onStart: Boolean(keyboard), onExit: Boolean(keyboard) || Boolean(inControls) };
}

/**
 * @typedef {{
 *   card: HTMLElement, lead: HTMLElement, line: HTMLElement, go: HTMLButtonElement, later: HTMLButtonElement,
 *   say: (text: string) => void, reduced: () => boolean, place: (card: {w: number, h: number}) => {x: number, y: number}|null,
 *   storage: () => Storage|null, onGo: (keyboard: boolean) => void, recheck: () => void,
 * }} InviteDeps
 */

export class ReplayInvite {
  /** @param {InviteDeps} deps */
  constructor(deps) {
    this.deps = deps;
    this.memory = inviteMemory(deps.storage);
    /** When the entry has settled plus the wait (performance.now ms); 0 while no entry. */
    this.readyAt = 0;
    this.shown = false;
    /** Offered already in this page (or this session): never again. */
    this.done = this.memory.seen();
    this.timer = 0;
    deps.go.addEventListener('click', (e) => {
      this.hide('go');
      deps.onGo(fromKeyboard(e));
    });
    deps.later.addEventListener('click', () => this.hide('later'));
    window.addEventListener('keydown', (e) => {
      if (!this.shown || e.key !== 'Escape' || e.defaultPrevented) return;
      if (document.querySelector('dialog[open]')) return;
      e.preventDefault();
      this.hide('later');
    });
  }

  /** The workspace was entered; its entry settles in `settleMs`. @param {number} settleMs */
  entered(settleMs) {
    this.readyAt = performance.now() + Math.max(0, settleMs) + INVITE_DELAY_MS;
  }

  /** Signed out: nothing pending, nothing shown (the session's memory stays). */
  reset() {
    window.clearTimeout(this.timer);
    this.timer = 0;
    this.readyAt = 0;
    if (this.shown) this.hide('reset');
  }

  /**
   * Asked whenever the facts change: shows the invitation once the studio rests and the entry
   * has settled; takes it away as soon as the studio does not rest.
   * @param {{resting: boolean, replaying: boolean, words: ReturnType<typeof inviteWords>}} now
   */
  consider(now) {
    if (this.shown) {
      if (!now.resting || now.replaying) this.hide('busy');
      return;
    }
    if (this.done || !this.readyAt || !now.resting || now.replaying || !now.words) return;
    const wait = this.readyAt - performance.now();
    if (wait > 0) {
      if (!this.timer) this.timer = window.setTimeout(() => { this.timer = 0; this.deps.recheck(); }, wait + 20);
      return;
    }
    this.show(now.words);
  }

  /** @param {NonNullable<ReturnType<typeof inviteWords>>} words */
  show(words) {
    const { card, lead, line } = this.deps;
    lead.textContent = words.lead;
    line.textContent = words.line;
    card.hidden = false;
    card.dataset.motion = this.deps.reduced() ? 'still' : 'enter';
    const spot = this.deps.place({ w: card.offsetWidth, h: card.offsetHeight });
    if (!spot) {
      // no free room under the building on this screen: the dock's key and the façade still offer it
      card.hidden = true;
      return;
    }
    card.style.left = `${spot.x}px`;
    card.style.top = `${spot.y}px`;
    this.shown = true;
    this.done = true;
    this.memory.remember();
    this.deps.say(words.sentence);
  }

  /** The frame changed (a drawer, the window): the invitation stands where the room now is. */
  relayout() {
    if (!this.shown) return;
    const { card } = this.deps;
    const spot = this.deps.place({ w: card.offsetWidth, h: card.offsetHeight });
    if (!spot) {
      this.hide('busy');
      return;
    }
    card.style.left = `${spot.x}px`;
    card.style.top = `${spot.y}px`;
  }

  /** A live event arrived: the building is live news now, not an invitation. */
  liveArrived() {
    if (this.shown) this.hide('live');
  }

  /** @param {'go'|'later'|'busy'|'live'|'reset'} why */
  hide(why) {
    const { card } = this.deps;
    const hadFocus = card.contains(document.activeElement);
    card.hidden = true;
    this.shown = false;
    this.hideReason = why;
    // the keyboard is not left on a control that has gone
    if (hadFocus && why !== 'go') {
      const canvas = document.getElementById('office-canvas');
      if (canvas) canvas.focus({ preventScroll: true });
    }
  }
}
