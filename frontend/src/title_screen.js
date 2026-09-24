import { SkyRenderer } from './hq_sky.js';
import { skyStops } from './hq_time.js';
import { mulberry32 } from './hq_world.js';
import {
  ENTRY,
  TITLE_LAYERS,
  WORLD,
  entryOrigin,
  followPointer,
  parallaxOffset,
  titleCaption,
  titleFrame,
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
 */

const BASE = '/assets/hq/plates';
/** How often the real sun is read again. It moves a quarter of a degree a minute. */
const LIGHT_MS = 60000;
/** The weather the title may claim before the key: none (hq_weather.js weatherEffects). */
const NO_WEATHER = { cloudiness: 0, rain: 0, snow: 0, fog: 0, storm: false, wet: 0, wind: 0 };

export class TitleScreen {
  /**
   * @param {{stage: HTMLElement, caption?: HTMLElement|null, now?: () => Date, reducedMotion?: () => boolean}} options
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
  }

  async start() {
    try {
      const response = await fetch(`${BASE}/plates.json`);
      this.plates = response.ok ? await response.json() : null;
    } catch {
      this.plates = null;
    }
    this.build();
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
    const { dayMix, grade, multiply, needsNight, needsDay } = this.light;
    this.stage.style.setProperty('--title-day', dayMix.toFixed(3));
    this.stage.dataset.phase = this.light.time.phase;
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
   * Resolves true when the entry finished, false when a sign-out came back to the title first.
   * @returns {Promise<boolean>}
   */
  enter() {
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.entering = true;
    const generation = ++this.generation;
    this.layout();
    document.body.classList.remove('is-title');
    document.body.classList.add('is-entering');
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

  /** Put away without a camera move (reduced motion, or the end of the entry). */
  hide() {
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
    document.body.classList.remove('is-entering');
    document.body.classList.add('is-title');
    this.stage.hidden = false;
    this.layout();
    this.relight();
    window.clearInterval(this.lightTimer);
    this.lightTimer = window.setInterval(() => this.relight(), LIGHT_MS);
  }
}
