/**
 * THE GLASS READOUT OVER THE RENDER (W10).
 *
 * One card of the drawers' glass, laid beside the bound face the pointer or the keyboard stands
 * on (hq_readouts.js surfaceReadout), inside the room the drawers, the sky row and the slate
 * leave, and never over the face it describes (hq_readouts.js placeReadout). Its words are
 * spoken once into a polite live region; the card itself is hidden from assistive technology,
 * so nothing is read twice. Nothing here is fetched: the card is written from the page's facts.
 *
 * Writes to the document only when what it says or where it stands has changed.
 */

import { SURFACES, placeReadout, readoutSentence } from './hq_readouts.js';

export class SceneReadout {
  /**
   * @param {{card: HTMLElement, announce: HTMLElement, host: HTMLElement, canvas: HTMLElement,
   *          slate?: HTMLElement|null, reducedMotion?: () => boolean}} parts
   */
  constructor(parts) {
    this.card = parts.card;
    this.announceEl = parts.announce;
    this.host = parts.host;
    this.canvas = parts.canvas;
    this.slate = parts.slate || null;
    this.reducedMotion = parts.reducedMotion || (() => false);
    const q = (/** @type {string} */ sel) => /** @type {HTMLElement} */ (this.card.querySelector(sel));
    this.parts = {
      eyebrow: q('.face-card-eyebrow'),
      value: q('.face-card-value'),
      line: q('.face-card-line'),
      context: q('.face-card-context'),
      action: q('.face-card-action'),
      poster: /** @type {HTMLCanvasElement} */ (this.card.querySelector('.face-card-poster')),
    };
    this.key = '';
    this.placeKey = '';
    this.spoken = '';
    this.size = { w: 0, h: 0 };
    /** @type {any} */
    this.target = null;
    this._speakTimer = 0;
    this._pending = '';
  }

  /**
   * Show the readout for a target the engine names, or hide it.
   * @param {any} target the engine's onReadout argument (null hides)
   * @param {import('./hq_readouts.js').Readout|null} readout the words, when the target is a face
   * @param {{poster?: HTMLCanvasElement|null, speech?: string}} [extra]
   */
  show(target, readout, extra = {}) {
    this.target = target;
    if (!target) {
      this.hide();
      return;
    }
    if (target.kind === 'agent' && !readout) {
      // An employee reached by the keyboard: the ring and the name tag are drawn in the world;
      // the page says who it is. Under the Unreal stream the world's marks are not seen, and the
      // page gives a card as well (W18, hq_readouts.js agentReadout).
      this.hide();
      if (extra.speech) this.speak(extra.speech, true);
      return;
    }
    if (!readout) {
      this.hide();
      return;
    }
    if (readout.key !== this.key) {
      this.key = readout.key;
      this.write(readout, extra.poster || null);
      this.size = { w: this.card.offsetWidth, h: this.card.offsetHeight };
      this.placeKey = '';
    }
    this.place(target);
    this.speak(extra.speech || readoutSentence(readout), target.via === 'keyboard');
  }

  /** @param {import('./hq_readouts.js').Readout} r @param {HTMLCanvasElement|null} poster */
  write(r, poster) {
    const p = this.parts;
    p.eyebrow.textContent = r.eyebrow;
    p.value.textContent = r.value;
    p.line.textContent = r.line;
    p.line.hidden = !r.line;
    p.context.textContent = r.context;
    p.context.hidden = !r.context;
    p.action.textContent = r.action;
    p.action.hidden = !r.action;
    this.card.dataset.tone = r.tone;
    this.card.dataset.surface = r.id.startsWith('desk:') ? 'desk' : r.id.startsWith('agent:') ? 'agent' : r.id;
    const showPoster = Boolean(r.poster && poster && p.poster);
    if (p.poster) {
      p.poster.hidden = !showPoster;
      if (showPoster && poster) {
        p.poster.width = poster.width;
        p.poster.height = poster.height;
        const c = p.poster.getContext('2d');
        if (c) c.drawImage(poster, 0, 0);
      }
    }
    this.card.hidden = false;
  }

  /** @param {any} target */
  place(target) {
    const host = this.host.getBoundingClientRect();
    const box = this.canvas.getBoundingClientRect();
    const ox = box.left - host.left;
    const oy = box.top - host.top;
    let bottom = oy + target.room.bottom;
    if (this.slate) {
      const slate = this.slate.getBoundingClientRect();
      if (slate.height) bottom = Math.min(bottom, slate.top - host.top);
    }
    const inset = 8;
    const room = { left: ox + target.room.left + inset, top: oy + target.room.top + inset, right: ox + target.room.right - inset, bottom: bottom - inset };
    const rect = { x: ox + target.rect.x, y: oy + target.rect.y, w: target.rect.w, h: target.rect.h };
    // a face may ask for a side first: the façade sign's card stands under it, off the lettering
    const surface = SURFACES.find((s) => s.id === target.id);
    const at = placeReadout(rect, this.size, room, 14, surface ? surface.prefer : undefined);
    const key = `${at.x},${at.y},${at.side}`;
    if (key === this.placeKey) return;
    this.placeKey = key;
    this.card.style.transform = `translate(${at.x}px, ${at.y}px)`;
    this.card.dataset.side = at.side;
    this.card.dataset.via = target.via;
  }

  /**
   * Say it once, politely. What the keyboard reached is said at once; what the pointer passes
   * over is said only once it rests there, so a sweep across the building is not a stream of
   * words. @param {string} text @param {boolean} now
   */
  speak(text, now) {
    if (text === this.spoken) return;
    // the same words already waiting to be said keep their place in the wait
    if (!now && text === this._pending) return;
    window.clearTimeout(this._speakTimer);
    this._pending = text;
    const say = () => {
      this._pending = '';
      this.spoken = text;
      this.announceEl.textContent = text;
    };
    if (now) say();
    else this._speakTimer = window.setTimeout(say, 600);
  }

  hide() {
    window.clearTimeout(this._speakTimer);
    this._pending = '';
    if (!this.card.hidden) this.card.hidden = true;
    this.key = '';
    this.placeKey = '';
    this.spoken = '';
  }
}
