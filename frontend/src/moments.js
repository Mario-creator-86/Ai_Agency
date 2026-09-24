/**
 * MILESTONE MOMENTS (W8).
 *
 * A moment marks something the studio really did, as it happens, and nothing else:
 *
 *  - an episode of the serial drafted or approved → a chapter card over the render,
 *    «Inside The Nexus · Ep N» over the episode's own title;
 *  - a film rendered → a quiet toast carrying the film's real first frame;
 *  - a film published → a quiet toast with its title;
 *  - a request waiting for the Owner → the gold mark on the register glows once (the mark itself
 *    is state, drawn from the approvals the backend lists, and stays while they wait).
 *
 * Only an event the socket delivered as it happened (`{type: 'event'}`) can play one. The replay
 * that fills the page when it opens, the register's REST backfill and a reconnect's catch-up are
 * history, and history plays nothing. An event is also refused when its own timestamp is older
 * than MOMENT_FRESH_MS: an outbox that flushes a backlog after a restart delivers old news as
 * `event`, and old news is not a moment. Each event plays at most once (by event_id).
 */

/** How old an event may be, by its own timestamp, and still be news. */
export const MOMENT_FRESH_MS = 10 * 60 * 1000;

/** How long each kind stays up, in ms, entry and exit included (1–3 s). */
export const MOMENT_TIMING = {
  in: 320,
  out: 240,
  chapter: 2800,
  toast: 3000,
  mark: 1200,
};

/** The most moments waiting their turn; older ones are dropped rather than played late. */
export const MOMENT_QUEUE = 3;

/**
 * @typedef {{
 *   kind: 'chapter'|'film'|'published'|'approval',
 *   id: string,
 *   eyebrow?: string, title?: string, line?: string,
 *   episodeId?: string, episodeNumber?: number|null, approved?: boolean,
 *   assetId?: string, storyboardId?: string|null, seconds?: number|null,
 * }} Moment
 */

/**
 * Whether an event may play a moment, and which. Pure: the page supplies `live` (the socket said
 * `event`, not `replay_event`), `now`, and the ids already played.
 *
 * @param {{event_id?: string, event_type?: string, timestamp?: string, aggregate_id?: string, payload?: any}|null|undefined} event
 * @param {{live: boolean, now: number, seen?: Set<string>}} context
 * @returns {Moment|null}
 */
export function momentFor(event, context) {
  if (!event || !context || context.live !== true) return null;
  const id = String(event.event_id || '');
  if (!id || (context.seen && context.seen.has(id))) return null;
  const at = Date.parse(String(event.timestamp || ''));
  if (!Number.isFinite(at) || context.now - at > MOMENT_FRESH_MS || at - context.now > MOMENT_FRESH_MS) return null;
  const type = String(event.event_type || '');
  const p = (event.payload && typeof event.payload === 'object') ? event.payload : {};
  switch (type) {
    case 'story.episode_drafted':
      return {
        kind: 'chapter',
        id,
        episodeId: String(event.aggregate_id || ''),
        episodeNumber: Number.isFinite(Number(p.episode_number)) && Number(p.episode_number) > 0 ? Number(p.episode_number) : null,
        approved: false,
        line: 'Episod scris · așteaptă decizia',
      };
    case 'story.episode_approved':
      return {
        kind: 'chapter',
        id,
        episodeId: String(event.aggregate_id || ''),
        episodeNumber: null,
        approved: true,
        line: p.reviewed_by === 'director' ? 'Episod aprobat de Directoare' : 'Episod aprobat de Proprietar',
      };
    case 'media.video_rendered':
      return {
        kind: 'film',
        id,
        assetId: String(event.aggregate_id || ''),
        storyboardId: p.storyboard_id ? String(p.storyboard_id) : null,
        seconds: Number.isFinite(Number(p.duration_seconds)) ? Number(p.duration_seconds) : null,
        eyebrow: 'FILM RANDAT',
      };
    case 'publishing.video_published':
      return {
        kind: 'published',
        id,
        eyebrow: 'FILM PUBLICAT',
        title: String(p.title || ''),
        line: p.privacy_status ? `pe YouTube · ${String(p.privacy_status) === 'private' ? 'privat' : String(p.privacy_status)}` : 'pe YouTube',
      };
    case 'governance.approval_requested':
      return { kind: 'approval', id };
    default:
      return null;
  }
}

/**
 * The chapter card's words, from the episode the backend lists and the number its draft event
 * carried. A missing title or number is left out, never guessed.
 *
 * @param {Moment} moment
 * @param {{series?: string|null, episode?: {title?: string}|null, number?: number|null}} facts
 */
export function chapterWords(moment, facts) {
  const series = String((facts && facts.series) || 'Office Serial');
  const number = (facts && facts.number) || moment.episodeNumber || null;
  const title = String((facts && facts.episode && facts.episode.title) || '').trim();
  return {
    eyebrow: [series, number ? `Ep ${number}` : null].filter(Boolean).join(' · '),
    title,
    line: moment.line || '',
    label: [series, number ? `episodul ${number}` : null, title || null, moment.line || null].filter(Boolean).join(' · '),
  };
}

/** «Film de 45 s», from the render's own measured duration. */
export function filmSeconds(seconds) {
  if (!Number.isFinite(seconds) || /** @type {number} */ (seconds) <= 0) return '';
  const s = Math.round(/** @type {number} */ (seconds));
  return `${s} s`;
}

/**
 * The queue: one moment on screen at a time, at most MOMENT_QUEUE waiting, the oldest waiting
 * dropped first. Pure bookkeeping, so its rules have a test.
 */
export class MomentQueue {
  constructor(limit = MOMENT_QUEUE) {
    this.limit = limit;
    /** @type {Moment[]} */
    this.waiting = [];
    /** @type {Moment|null} */
    this.current = null;
    /** @type {Set<string>} */
    this.seen = new Set();
  }

  /** @param {Moment} moment @returns {boolean} whether it was accepted */
  push(moment) {
    if (!moment || this.seen.has(moment.id)) return false;
    this.seen.add(moment.id);
    if (this.seen.size > 500) this.seen = new Set([...this.seen].slice(-250));
    this.waiting.push(moment);
    while (this.waiting.length > this.limit) this.waiting.shift();
    return true;
  }

  /** @returns {Moment|null} the next moment to show, or null while one is up or none waits */
  next() {
    if (this.current || !this.waiting.length) return null;
    this.current = /** @type {Moment} */ (this.waiting.shift());
    return this.current;
  }

  done() {
    this.current = null;
  }

  clear() {
    this.waiting = [];
    this.current = null;
  }
}

/**
 * The moments on the page. It owns two places: the chapter card, set into the render's viewport
 * above the slate, and the toast, in the page's bottom-right corner. Both are announced politely
 * to a screen reader through the region's own live text, both close on their button, both hold
 * while the pointer or the keyboard is on them, and under reduced motion they appear and leave
 * without moving (the same words, for the same time).
 */
export class Moments {
  /**
   * @param {{
   *   chapter: HTMLElement, toast: HTMLElement, announce: HTMLElement,
   *   reducedMotion: () => boolean,
   *   facts: (moment: Moment) => Promise<any>,
   *   poster?: (moment: Moment) => Promise<HTMLCanvasElement|null>,
   *   timers?: {setTimeout: typeof setTimeout, clearTimeout: typeof clearTimeout},
   *   now?: () => number,
   * }} parts
   */
  constructor(parts) {
    this.parts = parts;
    this.queue = new MomentQueue();
    this.timers = parts.timers || { setTimeout: (fn, ms) => window.setTimeout(fn, ms), clearTimeout: (id) => window.clearTimeout(id) };
    this.now = parts.now || (() => Date.now());
    this.hideTimer = 0;
    this.goneTimer = 0;
    this.generation = 0;
    /** @type {HTMLElement|null} */
    this.shown = null;
    this.remaining = 0;
    this.shownAt = 0;
    this.paused = false;
    for (const host of [parts.chapter, parts.toast]) {
      host.addEventListener('pointerenter', () => this._pause());
      host.addEventListener('pointerleave', () => this._resume());
      host.addEventListener('focusin', () => this._pause());
      host.addEventListener('focusout', () => this._resume());
      host.addEventListener('click', (event) => {
        const target = event.target instanceof Element ? event.target.closest('[data-moment-close]') : null;
        if (target) this.dismiss();
      });
      host.addEventListener('keydown', (event) => {
        if (/** @type {KeyboardEvent} */ (event).key === 'Escape') this.dismiss();
      });
    }
  }

  /**
   * One event from the socket.
   * @param {any} event
   * @param {boolean} live
   * @returns {Moment|null} the moment it made, if any
   */
  offer(event, live) {
    const moment = momentFor(event, { live, now: this.now(), seen: this.queue.seen });
    if (!moment) return null;
    if (moment.kind === 'approval') {
      // The mark is the approvals panel's; this only says a new one just arrived.
      this.queue.seen.add(moment.id);
      return moment;
    }
    if (this.queue.push(moment)) this._pump();
    return moment;
  }

  /** Sign-out: nothing plays for the next visitor. */
  reset() {
    this.generation += 1;
    this.queue.clear();
    this.queue.seen.clear();
    this._clearTimers();
    for (const host of [this.parts.chapter, this.parts.toast]) {
      host.hidden = true;
      host.classList.remove('is-in', 'is-out');
      host.replaceChildren();
    }
    this.shown = null;
  }

  dismiss() {
    if (!this.shown) return;
    this._leave(this.generation);
  }

  async _pump() {
    const moment = this.queue.next();
    if (!moment) return;
    const generation = this.generation;
    let facts = null;
    try {
      facts = await this.parts.facts(moment);
    } catch {
      facts = null;
    }
    let poster = null;
    if (moment.kind === 'film' && this.parts.poster) {
      try {
        poster = await this.parts.poster(moment);
      } catch {
        poster = null;
      }
    }
    if (generation !== this.generation) return;
    this._show(moment, facts, poster);
  }

  /**
   * @param {Moment} moment
   * @param {any} facts
   * @param {HTMLCanvasElement|null} poster
   */
  _show(moment, facts, poster) {
    const host = moment.kind === 'chapter' ? this.parts.chapter : this.parts.toast;
    host.replaceChildren();
    host.dataset.kind = moment.kind;
    let label = '';
    if (moment.kind === 'chapter') {
      const words = chapterWords(moment, facts || {});
      label = words.label;
      host.append(
        textNode('p', 'moment-eyebrow', words.eyebrow),
        ...(words.title ? [textNode('p', 'moment-title', words.title)] : []),
        ...(words.line ? [textNode('p', 'moment-line', words.line)] : []),
      );
    } else {
      const body = document.createElement('div');
      body.className = 'moment-body';
      const title = moment.kind === 'film' ? String((facts && facts.title) || '') : String(moment.title || '');
      const line = moment.kind === 'film'
        ? [filmSeconds(moment.seconds ?? NaN) ? `film de ${filmSeconds(moment.seconds ?? NaN)}` : null, '9:16'].filter(Boolean).join(' · ')
        : String(moment.line || '');
      body.append(
        textNode('p', 'moment-eyebrow', String(moment.eyebrow || '')),
        ...(title ? [textNode('p', 'moment-title', title)] : []),
        ...(line ? [textNode('p', 'moment-line', line)] : []),
      );
      if (poster) {
        poster.classList.add('moment-poster');
        poster.setAttribute('aria-hidden', 'true');
        host.append(poster);
      }
      host.append(body);
      label = [moment.eyebrow === 'FILM RANDAT' ? 'Film randat' : 'Film publicat', title || null, line || null].filter(Boolean).join(' · ');
    }
    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'moment-close';
    close.dataset.momentClose = '';
    close.setAttribute('aria-label', 'Închide');
    close.innerHTML = '<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M6.4 6.4l11.2 11.2M17.6 6.4L6.4 17.6"/></svg>';
    host.append(close);
    this.parts.announce.textContent = label;
    host.hidden = false;
    host.classList.remove('is-out');
    // One frame at rest before the entry, so the transition has a start to run from.
    void host.offsetWidth;
    host.classList.add('is-in');
    this.shown = host;
    this.remaining = moment.kind === 'chapter' ? MOMENT_TIMING.chapter : MOMENT_TIMING.toast;
    this._arm();
  }

  _arm() {
    this._clearTimers();
    this.shownAt = this.now();
    const generation = this.generation;
    const hold = Math.max(0, this.remaining - MOMENT_TIMING.out);
    this.hideTimer = this.timers.setTimeout(() => this._leave(generation), hold);
  }

  _pause() {
    if (!this.shown || this.paused) return;
    this.paused = true;
    this.remaining = Math.max(MOMENT_TIMING.out + 400, this.remaining - (this.now() - this.shownAt));
    this._clearTimers();
  }

  _resume() {
    if (!this.shown || !this.paused) return;
    const active = this.shown.matches(':hover') || this.shown.contains(document.activeElement);
    if (active) return;
    this.paused = false;
    this._arm();
  }

  /** @param {number} generation */
  _leave(generation) {
    if (generation !== this.generation || !this.shown) return;
    const host = this.shown;
    this._clearTimers();
    host.classList.remove('is-in');
    host.classList.add('is-out');
    const out = this.parts.reducedMotion() ? 0 : MOMENT_TIMING.out;
    this.goneTimer = this.timers.setTimeout(() => {
      if (generation !== this.generation) return;
      host.hidden = true;
      host.classList.remove('is-out');
      host.replaceChildren();
      this.shown = null;
      this.paused = false;
      this.queue.done();
      this._pump();
    }, out);
  }

  _clearTimers() {
    this.timers.clearTimeout(this.hideTimer);
    this.timers.clearTimeout(this.goneTimer);
    this.hideTimer = 0;
    this.goneTimer = 0;
  }
}

/**
 * @param {string} tag
 * @param {string} className
 * @param {string} text
 */
function textNode(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}
