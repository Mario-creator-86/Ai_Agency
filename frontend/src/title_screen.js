import { SkyRenderer } from './hq_sky.js';
import { skyStops } from './hq_time.js';
import { mulberry32 } from './hq_world.js';
import {
  ENTRY,
  TITLE_LAYERS,
  WORLD,
  entryOrigin,
  followPointer,
  keptEdges,
  keptPlacement,
  parallaxOffset,
  skyRow,
  placementTransform,
  titleCaption,
  titleFrame,
  titleKeptCaption,
  titleLight,
} from './title_frame.js';

/**
 * THE TITLE SCREEN. The sign-in stands in the studio's own world: the office's sky renderer at the
 * real Bucharest sun, and the office's Blender plates as depth layers, framed as key art
 * (title_frame.js). Three things move, and each one answers something real:
 * - the layers follow the pointer, a few pixels by depth, and stop when it stops;
 * - the light is re-read from the real sun once a minute (the sky and the day/night plates);
 * - on a key the backend accepted, the camera goes into the building (enter()).
 * With reduced motion the frame is held still and the key opens the workspace at once.
 *
 * Before the key is given the page has no weather: /office/weather needs the Owner, so the sky
 * is drawn as the office draws an unknown sky, with no cloud and no rain it would have to invent.
 *
 * ONE BUILDING (W22). When this browser keeps a real frame of the Unreal building and the stream
 * is configured (main.js titleKept), the title stands on that frame instead of the plates: the
 * Owner's chosen face is the one a visitor meets first. The caption names it as the plate's badge
 * does («ultimul cadru live · azi 00:47») beside the real hour, and never says the light is the
 * hour's. The entry then carries the frame onto the place the workspace shows the stream
 * (enter(landing)), dimmed as the plate dims it, where the live video takes over.
 */

/** How long the title waits for the kept frame before it stands on the plates (W22). */
export const KEPT_WAIT_MS = 600;

const BASE = '/assets/hq/plates';
/** How often the real sun is read again. It moves a quarter of a degree a minute. */
const LIGHT_MS = 60000;
/** The weather the title may claim before the key: none (hq_weather.js weatherEffects). */
const NO_WEATHER = { cloudiness: 0, rain: 0, snow: 0, fog: 0, storm: false, wet: 0, wind: 0 };

export class TitleScreen {
  /**
   * @param {{stage: HTMLElement, caption?: HTMLElement|null, now?: () => Date, reducedMotion?: () => boolean,
   *          kept?: Promise<{image: CanvasImageSource & {width: number, height: number}, at: number}|null>|null,
   *          keptCaption?: (at: number) => string, keptStillTrue?: (at: number) => boolean}} options
   */
  constructor(options) {
    this.stage = options.stage;
    this.caption = options.caption || null;
    this.now = options.now || (() => new Date());
    this.reducedMotion = options.reducedMotion || (() => false);
    this.sky = /** @type {HTMLCanvasElement} */ (this.stage.querySelector('.title-sky'));
    this.world = /** @type {HTMLElement} */ (this.stage.querySelector('.title-world'));
    this.grade = this.stage.querySelector('#title-night-grade feColorMatrix');
    /** @type {any} */
    this.plates = null;
    /** @type {Array<{def: typeof TITLE_LAYERS[number], el: HTMLElement, rect: {x:number,y:number,w:number,h:number}, night: HTMLElement, day: HTMLElement}>} */
    this.groups = [];
    this.frame = titleFrame(1, 1);
    this.light = titleLight(this.now());
    this.skyRenderer = new SkyRenderer({ worldWidth: WORLD.width, worldHeight: WORLD.height, horizonRow: 350, rng: mulberry32(20260913) });
    this.pointer = { x: 0, y: 0 };
    this.target = { x: 0, y: 0 };
    this.current = { x: 0, y: 0 };
    this.raf = 0;
    this.last = 0;
    this.lightTimer = 0;
    this.visible = !this.stage.hidden;
    this.entering = false;
    this.generation = 0;
    this._onResize = () => this.layout();
    this._onPointer = (/** @type {PointerEvent} */ event) => this.follow(event);
    /** W22: the kept real frame the title stands on, or null for the plates. */
    this.keptPromise = options.kept || null;
    this.keptCaptionOf = options.keptCaption || (() => '');
    /** W24: whether the kept frame's light is still the hour's (studio_frame.js lightMatches) */
    this.keptStillTrue = options.keptStillTrue || (() => true);
    /** @type {{image: CanvasImageSource & {width: number, height: number}, at: number}|null} */
    this.kept = null;
    /** @type {HTMLCanvasElement|null} */
    this.keptEl = null;
    this.keptTop = '';
    this.keptTopClear = '';
    /** @type {HTMLCanvasElement|null} */
    this.keptTopRow = null;
    /** @type {Animation|null} the entry's landing (W22) */
    this.landing = null;
    /** W36: the end of a cold entry's push, when the stream's picture may show (is-pushing). */
    this.pushTimer = 0;
  }

  /** The kept frame, if it is known within KEPT_WAIT_MS; the title does not wait longer for it. */
  async firstKept() {
    if (!this.keptPromise) return null;
    let timer = 0;
    const late = new Promise((resolve) => { timer = window.setTimeout(() => resolve(null), KEPT_WAIT_MS); });
    try {
      return await Promise.race([this.keptPromise.catch(() => null), late]);
    } finally {
      window.clearTimeout(timer);
    }
  }

  /**
   * Stand the title on a kept real frame of the Unreal building (W22): one canvas the size of the
   * world, framed as the plates are; the sky above the world is the frame's own top colour.
   * @param {{image: CanvasImageSource & {width: number, height: number}, at: number}|null} kept
   * @returns {boolean} whether the title stands on it
   */
  useKept(kept) {
    if (!kept || !kept.image || !(kept.image.width > 0) || !(kept.image.height > 0)) return false;
    const el = this.keptEl || document.createElement('canvas');
    el.className = 'title-kept';
    el.width = kept.image.width;
    el.height = kept.image.height;
    const context = el.getContext('2d');
    if (!context) return false;
    context.drawImage(kept.image, 0, 0);
    try {
      // W34: the frame's top row as sky only (the building that touches the edge is filled from the
      // sky beside it), kept as a one-row canvas the band above the world is drawn from; averaged,
      // it is the sky's own colour far above the roof
      const row = skyRow(context.getImageData(0, 0, el.width, 1).data, el.width);
      const strip = document.createElement('canvas');
      strip.width = el.width;
      strip.height = 1;
      const img = new ImageData(el.width, 1);
      img.data.set(row);
      strip.getContext('2d')?.putImageData(img, 0, 0);
      this.keptTopRow = strip;
      let r = 0;
      let g = 0;
      let b = 0;
      const n = row.length / 4;
      for (let i = 0; i < row.length; i += 4) { r += row[i]; g += row[i + 1]; b += row[i + 2]; }
      this.keptTop = `rgb(${Math.round(r / n)}, ${Math.round(g / n)}, ${Math.round(b / n)})`;
      this.keptTopClear = `rgba(${Math.round(r / n)}, ${Math.round(g / n)}, ${Math.round(b / n)}, 0)`;
    } catch {
      this.keptTop = '';
      this.keptTopClear = '';
    }
    if (!this.keptEl) {
      this.keptEl = el;
      this.world.after(el);
    }
    this.kept = kept;
    this.stage.dataset.kept = 'true';
    this.place();
    this.drawSky();
    this.relight();
    return true;
  }

  /**
   * W24: the title leaves a kept frame whose light is no longer the hour's (or none is offered on
   * a return to the title) and stands on the plates again, lit by the real sun.
   */
  dropKept() {
    if (!this.kept || this.entering) return;
    this.kept = null;
    this.keptTop = '';
    this.keptTopClear = '';
    this.keptTopRow = null;
    if (this.keptEl) this.keptEl.remove();
    this.keptEl = null;
    delete this.stage.dataset.kept;
    this.place();
    this.relight();
  }

  async start() {
    const plates = (async () => {
      try {
        const response = await fetch(`${BASE}/plates.json`);
        return response.ok ? await response.json() : null;
      } catch {
        return null;
      }
    })();
    const [read, kept] = await Promise.all([plates, this.firstKept()]);
    this.plates = read;
    this.build();
    // W22: a kept real frame of the Unreal building, when the browser has one: the plates are not
    // downloaded for the title then (relight loads them only without it)
    if (kept) this.useKept(kept);
    window.addEventListener('resize', this._onResize, { passive: true });
    window.addEventListener('pointermove', this._onPointer, { passive: true });
    this.layout();
    this.relight();
    this.lightTimer = window.setInterval(() => this.relight(), LIGHT_MS);
  }

  /** The layer groups, each sized to the union of its plates, with a night and a day film. */
  build() {
    this.world.replaceChildren();
    this.groups = [];
    const variants = this.plates?.variants;
    if (!variants) return;
    for (const def of TITLE_LAYERS) {
      let x0 = Infinity;
      let y0 = Infinity;
      let x1 = -Infinity;
      let y1 = -Infinity;
      for (const variant of ['night', 'day']) {
        for (const name of def.layers) {
          const l = variants[variant]?.[name];
          if (!l) continue;
          x0 = Math.min(x0, l.x);
          y0 = Math.min(y0, l.y);
          x1 = Math.max(x1, l.x + l.w);
          y1 = Math.max(y1, l.y + l.h);
        }
      }
      if (!Number.isFinite(x0)) continue;
      const rect = { x: Math.floor(x0), y: Math.floor(y0), w: Math.ceil(x1 - Math.floor(x0)), h: Math.ceil(y1 - Math.floor(y0)) };
      const el = document.createElement('div');
      el.className = `title-layer title-layer-${def.name}`;
      el.style.width = `${rect.w}px`;
      el.style.height = `${rect.h}px`;
      const films = /** @type {Record<string, HTMLElement>} */ ({});
      for (const variant of ['night', 'day']) {
        const film = document.createElement('div');
        film.className = `title-film title-${variant}`;
        for (const name of def.layers) {
          const l = variants[variant]?.[name];
          if (!l) continue;
          const img = document.createElement('img');
          img.alt = '';
          img.decoding = 'async';
          img.draggable = false;
          img.dataset.src = `${BASE}/${l.file}`;
          img.style.left = `${l.x - rect.x}px`;
          img.style.top = `${l.y - rect.y}px`;
          img.style.width = `${l.w}px`;
          img.style.height = `${l.h}px`;
          film.append(img);
        }
        el.append(film);
        films[variant] = film;
      }
      this.world.append(el);
      this.groups.push({ def, el, rect, night: films.night, day: films.day });
    }
  }

  /** Frames the world for the screen it is on. */
  layout() {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    this.frame = titleFrame(vw, vh);
    this.stage.dataset.layout = this.frame.layout;
    const origin = entryOrigin(this.frame);
    this.stage.style.setProperty('--title-origin-x', `${Math.round(origin.x)}px`);
    this.stage.style.setProperty('--title-origin-y', `${Math.round(origin.y)}px`);
    this.place();
    this.drawSky();
  }

  /** Writes every layer's transform: the frame, plus its share of the pointer's offset. */
  place() {
    if (this.keptEl && this.kept) this.keptEl.style.transform = placementTransform(keptPlacement(this.frame, this.current));
    const { scale, x, y } = this.frame;
    for (const group of this.groups) {
      const dx = this.current.x * group.def.depth;
      const dy = this.current.y * group.def.depth;
      const tx = x + group.rect.x * scale + dx;
      const ty = y + group.rect.y * scale + dy;
      group.el.style.transform = `translate3d(${tx.toFixed(2)}px, ${ty.toFixed(2)}px, 0) scale(${scale.toFixed(4)})`;
    }
  }

  /** The real sun, read again: the day plates' share, the deep-night grade, the sky, the caption. */
  relight() {
    this.light = titleLight(this.now());
    // W24: a kept frame stands only in its own light; the plates take over once the sun has moved on
    if (this.kept && !this.entering && !this.keptStillTrue(this.kept.at)) {
      this.dropKept();
      return;
    }
    const { dayMix, grade, multiply, needsNight, needsDay } = this.light;
    this.stage.style.setProperty('--title-day', dayMix.toFixed(3));
    this.stage.dataset.phase = this.light.time.phase;
    if (this.kept) {
      // W22: the frame carries its own light; the caption says whose hour it is, beside the real one
      this.drawSky();
      if (this.caption) this.caption.textContent = titleKeptCaption(this.light.time, this.keptCaptionOf(this.kept.at));
      return;
    }
    for (const group of this.groups) {
      // a film that is not shown is not downloaded: a night visit does not pay for the day plates
      if (needsNight) this.load(group.night);
      if (needsDay) this.load(group.day);
      group.night.hidden = !needsNight;
      group.day.hidden = !needsDay;
      group.el.classList.toggle('is-graded', group.def.grade && grade > 0);
    }
    if (this.grade) {
      const [r, g, b] = multiply;
      this.grade.setAttribute('values', `${r} 0 0 0 0  0 ${g} 0 0 0  0 0 ${b} 0 0  0 0 0 1 0`);
    }
    this.drawSky();
    if (this.caption) this.caption.textContent = titleCaption(this.light.time);
  }

  /** @param {HTMLElement} film */
  load(film) {
    for (const img of /** @type {HTMLImageElement[]} */ (Array.from(film.querySelectorAll('img[data-src]')))) {
      img.src = img.dataset.src || '';
      img.removeAttribute('data-src');
    }
  }

  /** The office's own sky at the real sun, drawn once per light reading, at half resolution. */
  drawSky() {
    const canvas = this.sky;
    if (!canvas) return;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const k = 0.5;
    const w = Math.max(1, Math.round(vw * k));
    const h = Math.max(1, Math.round(vh * k));
    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
    }
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    if (this.kept) {
      // W22: above and around the kept frame, its own sky's colour
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.fillStyle = this.keptTop || String(skyStops(this.light.time, NO_WEATHER)[0][1]);
      ctx.fillRect(0, 0, w, h);
      this.drawKeptEdges(ctx, k, vw, vh);
      return;
    }
    const { scale, x, y } = this.frame;
    const time = this.light.time;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    // above the world's top edge the sky is its own top colour
    ctx.fillStyle = String(skyStops(time, NO_WEATHER)[0][1]);
    ctx.fillRect(0, 0, w, h);
    ctx.setTransform(k * scale, 0, 0, k * scale, k * x, k * y);
    this.skyRenderer.drawSky(ctx, time, NO_WEATHER);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }

  /**
   * W34: the returning title's sky continues the kept frame's own edge rows, so no flat colour meets
   * the frame in a seam. Each strip the frame leaves (keptEdges: in practice the band above the roof)
   * is the frame's outermost rows stretched across it, a little under the frame too so the pointer's
   * parallax never opens a gap, softened, and fading into the rows' average colour away from the
   * frame. Drawn with the sky, once per light reading or resize; nothing per frame.
   * @param {CanvasRenderingContext2D} ctx @param {number} k the sky canvas's scale @param {number} vw @param {number} vh
   */
  drawKeptEdges(ctx, k, vw, vh) {
    const src = this.keptEl;
    if (!src || !this.frame || !(src.width > 0) || !(src.height > 0)) return;
    const place = keptPlacement(this.frame, { x: 0, y: 0 });
    const edges = keptEdges(place, vw, vh);
    const W = src.width;
    const H = src.height;
    const under = 24; // px under the frame: more than the parallax moves it
    const rows = Math.max(1, Math.round(H / 336)); // three frame rows at 1008 px
    ctx.save();
    ctx.imageSmoothingEnabled = true;
    ctx.filter = 'blur(6px)';
    if (edges.top) {
      const e = edges.top;
      const top = this.keptTopRow;
      if (top) ctx.drawImage(top, 0, 0, top.width, 1, k * e.x, -k * 12, k * e.w, k * (e.h + under + 12));
      else ctx.drawImage(src, 0, 0, W, rows, k * e.x, -k * 12, k * e.w, k * (e.h + under + 12));
    }
    if (edges.bottom) {
      const e = edges.bottom;
      ctx.drawImage(src, 0, H - rows, W, rows, k * e.x, k * (e.y - under), k * e.w, k * (e.h + under + 12));
    }
    ctx.filter = 'none';
    if (edges.top && this.keptTop && this.keptTopClear) {
      // away from the frame, the rows' own average: the sky reads as one sky above the roof
      const e = edges.top;
      const g = ctx.createLinearGradient(0, 0, 0, k * e.h);
      g.addColorStop(0, this.keptTop);
      g.addColorStop(0.35, this.keptTop);
      g.addColorStop(1, this.keptTopClear);
      ctx.fillStyle = g;
      ctx.fillRect(0, 0, k * vw, k * e.h);
    }
    ctx.restore();
  }

  /** @param {PointerEvent} event */
  follow(event) {
    if (!this.visible || this.entering || event.pointerType !== 'mouse' || this.reducedMotion()) return;
    const offset = parallaxOffset({ x: event.clientX, y: event.clientY }, 1, window.innerWidth, window.innerHeight);
    this.target = offset;
    if (!this.raf) {
      this.last = performance.now();
      this.raf = requestAnimationFrame((t) => this.tick(t));
    }
  }

  /** @param {number} now */
  tick(now) {
    const next = followPointer(this.current, this.target, now - this.last);
    this.last = now;
    this.current = next || { ...this.target };
    this.place();
    this.raf = next ? requestAnimationFrame((t) => this.tick(t)) : 0;
  }

  /**
   * The camera goes into the building and the frame resolves into the workspace. The stylesheet
   * plays it (style.css, "THE ENTRY"); this sets where the camera aims and when it is over.
   * W22: standing on a kept frame, with the place the workspace will show the stream (`landing`),
   * the frame itself is carried there and dimmed as the plate dims it, so it lands on the same
   * building the stream then shows live; the rest of the title fades around it.
   * Resolves true when the entry finished, false when a sign-out came back to the title first.
   * @param {(() => ({x: number, y: number, scale: number}|null))|null} [landing] where the workspace
   *   shows the stream (title_frame.js landingPlacement), asked once the workspace is laid out
   * @returns {Promise<boolean>}
   */
  enter(landing = null) {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.entering = true;
    const generation = ++this.generation;
    this.layout();
    document.body.classList.remove('is-title');
    // W22: the landing is read once the workspace stands as it will (the masthead shown, the
    // render's panel not rising: is-landing), so the frame lands where the stream is drawn;
    // read with the title still up, it missed by the masthead's 64 px
    const lands = Boolean(landing && this.kept && this.keptEl);
    if (lands) document.body.classList.add('is-landing');
    document.body.classList.add('is-entering');
    this.land(lands && landing ? landing() : null);
    // W36: a cold entry pushes into the plates. The live stream's picture, which comes up in the
    // render's panel as it arrives, waited for nothing: the plates and the stream showed at once,
    // offset, for ~300 ms of the push (w36 entry36.mjs, a stand-in stream frame). Its picture is
    // held until the plates have all but gone and then fades in (style.css is-pushing), as the
    // returning entry's panel appears only once its kept frame has landed. W37: the hold ends at
    // ENTRY.streamMs, not at the push's end: held to the end, the panel showed its own ground for
    // ~60 ms between the plates' last frame and the picture's first (a dark beat).
    window.clearTimeout(this.pushTimer);
    if (!lands) {
      document.body.classList.add('is-pushing', 'is-cold-entry');
      this.pushTimer = window.setTimeout(() => { this.pushTimer = 0; document.body.classList.remove('is-pushing'); }, ENTRY.streamMs);
    }
    return new Promise((resolve) => {
      window.setTimeout(() => {
        if (generation !== this.generation) {
          resolve(false);
          return;
        }
        this.hide();
        document.body.classList.remove('is-entering');
        this.entering = false;
        resolve(true);
      }, ENTRY.totalMs);
    });
  }

  /**
   * W22: the kept frame carried from where the title stands it to where the workspace shows the
   * stream, over the push's duration and ease, dimmed on the way as the plate's kept frame is.
   * @param {{x: number, y: number, scale: number}|null} landing
   */
  land(landing) {
    this.stage.classList.remove('lands');
    document.body.classList.remove('is-landing');
    if (this.landing) this.landing.cancel();
    this.landing = null;
    if (!landing || !this.kept || !this.keptEl || typeof this.keptEl.animate !== 'function') return;
    const root = getComputedStyle(document.documentElement);
    const dim = root.getPropertyValue('--kept-dim').trim() || 'none';
    const ease = root.getPropertyValue('--ease-push').trim() || 'ease';
    this.stage.classList.add('lands');
    // the render's panel appears only once the frame has landed on it (style.css): measured, a panel
    // fading in under a frame still in flight showed the building twice (W22, entry_0600)
    document.body.classList.add('is-landing');
    this.landing = this.keptEl.animate([
      { transform: placementTransform(keptPlacement(this.frame, this.current)), filter: 'none' },
      { transform: placementTransform(landing), filter: dim },
    ], { duration: ENTRY.pushMs, easing: ease, fill: 'forwards' });
  }

  /** Put away without a camera move (reduced motion, or the end of the entry). */
  hide() {
    this.stage.classList.remove('lands');
    document.body.classList.remove('is-landing');
    window.clearTimeout(this.pushTimer);
    this.pushTimer = 0;
    document.body.classList.remove('is-pushing', 'is-cold-entry');
    if (this.landing) this.landing.cancel();
    this.landing = null;
    this.visible = false;
    this.stage.hidden = true;
    document.body.classList.remove('is-title');
    window.clearInterval(this.lightTimer);
    this.lightTimer = 0;
  }

  /** Back to the title after sign-out: the light is read again, the frame held at rest. */
  show() {
    this.generation += 1;
    this.visible = true;
    this.entering = false;
    this.current = { x: 0, y: 0 };
    this.target = { x: 0, y: 0 };
    window.clearTimeout(this.pushTimer);
    this.pushTimer = 0;
    document.body.classList.remove('is-entering', 'is-pushing', 'is-cold-entry');
    document.body.classList.add('is-title');
    this.stage.hidden = false;
    this.layout();
    this.relight();
    window.clearInterval(this.lightTimer);
    this.lightTimer = window.setInterval(() => this.relight(), LIGHT_MS);
  }
}
