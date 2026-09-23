import { HQAssets } from './hq_assets.js';
import { WorldSimulationManager, HQRenderer } from './hq_world.js';
import { scenePalette } from './hq_palette.js';

/**
 * AMN-AI headquarters — the living office.
 *
 * WHAT THIS FILE MAY AND MAY NOT DO
 * ---------------------------------
 * The backend is the only source of truth for the studio. Which rooms and desks exist, who sits
 * where, and what each agent is doing (runtime state, lifecycle, the detail of the task) come
 * from the API and the event stream. An agent types only while the backend says WORKING, sleeps
 * only while PAUSED; the lift moves only when a workflow token really changes floor.
 *
 * The city outside — sky, weather, traffic, pedestrians, random events — is scenery driven by
 * the time in Bucharest, the live weather the backend reads, and one seeded random source. It
 * never emits studio events and nothing in it stands for studio data.
 *
 * RENDERING MODEL
 * ---------------
 * The building, street and skyline are plates rendered in Blender (art-source/blender/hq) in
 * layers; employees, pedestrians and vehicles are sprite sheets from the same camera. The canvas
 * draws the layers in their build order with the live actors in between, directly through the
 * viewport transform, so art stays sharp at every zoom.
 */

const clamp = (/** @type {number} */ v, /** @type {number} */ lo, /** @type {number} */ hi) => (v < lo ? lo : v > hi ? hi : v);

export class Viewport {
  /** @param {{width:number, height:number}} canvas */
  constructor(canvas) {
    this.canvas = canvas;
    this.panX = 0;
    this.panY = 0;
    this.zoom = 1;
    this.minZoom = 0.1;
    this.bottomInset = 0;
    this.maxZoom = 4;
  }

  /** @param {number} next @param {number} [anchorX] @param {number} [anchorY] */
  setZoom(next, anchorX, anchorY) {
    const clamped = clamp(next, this.minZoom, this.maxZoom);
    const ax = anchorX ?? this.canvas.width / 2;
    const ay = anchorY ?? this.canvas.height / 2;
    const before = this.screenToWorld(ax, ay);
    this.zoom = clamped;
    const after = this.screenToWorld(ax, ay);
    this.panX += (after.x - before.x) * this.zoom;
    this.panY += (after.y - before.y) * this.zoom;
  }

  /** @param {number} x @param {number} y */
  worldToScreen(x, y) {
    return { x: x * this.zoom + this.panX, y: y * this.zoom + this.panY };
  }

  /** @param {number} x @param {number} y */
  screenToWorld(x, y) {
    return { x: (x - this.panX) / this.zoom, y: (y - this.panY) / this.zoom };
  }

  /** @param {number} worldWidth @param {number} worldHeight */
  fitToOffice(worldWidth, worldHeight) {
    const cw = this.canvas.width || 1;
    const ch = Math.max(1, (this.canvas.height || 1) - this.bottomInset);
    const scale = Math.min(cw / worldWidth, ch / worldHeight);
    this.zoom = clamp(scale, this.minZoom, this.maxZoom);
    this.panX = (cw - worldWidth * this.zoom) / 2;
    this.panY = (ch - worldHeight * this.zoom) / 2;
  }
}

export const WORLD_W = 1600;
export const WORLD_H = 840;

/** Where a floor's cab top and walk line sit when no manifest has been loaded (tests, early frames). */
const LEGACY_CAB_OFFSET = 66;
const LEGACY_FLOOR_OFFSET = 12;

/**
 * WHAT THE SCENE SAYS WHEN IT HAS NOTHING TO SHOW.
 *
 * These two sentences are the product's own and are unchanged, word for word, from when they were
 * painted straight onto the canvas in a grey nobody chose. They are now laid over the viewport as
 * real elements, so they take the same shape every other empty, loading and error state on the
 * page takes (style.css, "3 STATES"): a calm plate with a rail at its edge, the product's words on
 * it, and for a failure the alert triple. A screen reader can read them, which a fill of text on a
 * canvas can never be.
 */
const SCENE_NOTES = {
  loading: 'Loading the AMN-AI headquarters…',
  error: 'The headquarters art could not be loaded.',
};

const WEATHER_ICONS = { clear: '☀', partly_cloudy: '⛅', cloudy: '☁', fog: '🌫', drizzle: '🌦', rain: '🌧', snow: '❄', storm: '⛈', unknown: '' };

export class OfficeEngine {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {{onSelectAgent?: (agent:any) => void, fetchWeather?: () => Promise<any>, infoElement?: HTMLElement|null, fpsElement?: HTMLElement|null, seed?: number}} [options]
   */
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.onSelectAgent = options.onSelectAgent || (() => {});
    this.fetchWeather = options.fetchWeather || (async () => ({ available: false, reason: 'not_configured' }));
    this.infoElement = options.infoElement || null;
    this.fpsElement = options.fpsElement || null;

    /** @type {any} */
    this.layout = null;
    /** @type {any[]} */
    this.agents = [];
    /** @type {any[]} */
    this.speechBubbles = [];
    /** @type {any[]} */
    this.projectTokens = [];
    /** @type {any} */
    this.selectedAgentId = null;
    /** @type {any} */
    this.hoverAgentId = null;
    /** @type {any[]} */
    this.bibles = [];
    this.worldW = WORLD_W;
    this.worldH = WORLD_H;
    this.dpr = 1;

    /**
     * The lift is parked unless the backend gives it a reason to move: a workflow token arriving
     * at a stage on another floor. With no workflow running, the cab stands still.
     * @type {any}
     */
    this.lift = { y: 0, target: 0, moving: false, restUntil: 0, homeY: undefined, trip: null };
    /** @type {Map<string, any>} */
    this.tokenPlaces = new Map();
    /** @type {any} */
    this.shaft = null;
    /** @type {any} */
    this.building = null;
    /** @type {Record<string, number>|null} */
    this.liftStops = null;

    this.viewport = new Viewport(canvas);
    this.animTime = 0;
    this.lastFrame = typeof performance !== 'undefined' ? performance.now() : 0;
    this.running = true;
    this.fps = 0;
    this._fpsFrames = 0;
    this._fpsStart = this.lastFrame;
    this.assets = new HQAssets();
    /** @type {WorldSimulationManager|null} */
    this.world = null;
    /** @type {HQRenderer|null} */
    this.renderer = null;
    this.assetsFailed = false;
    /** The element laid over the viewport while the scene is loading or its art failed. @type {HTMLElement|null} */
    this._note = null;
    /** @type {'loading'|'error'|null|undefined} */
    this._noteKind = undefined;

    if (typeof document !== 'undefined' && !document.getElementById('office-scene-theme')) {
      const theme = document.createElement('link');
      theme.id = 'office-scene-theme';
      theme.rel = 'stylesheet';
      theme.href = new URL('./office_scene.css?no-inline', import.meta.url).href;
      theme.addEventListener('load', () => this.resize());
      document.head.append(theme);
    }

    this._bindInput();
    this.resize();
    this._loop = this._loop.bind(this);
    requestAnimationFrame(this._loop);
    this.assets.load().then((ok) => {
      if (!this.running) return;
      if (!ok) {
        this.assetsFailed = true;
        return;
      }
      this.world = new WorldSimulationManager({ assets: this.assets, fetchWeather: this.fetchWeather, seed: options.seed });
      this.renderer = new HQRenderer(this.world);
      this._applyManifest(this.assets.manifest);
      this.resize();
    });
  }

  /** @param {any} m */
  _applyManifest(m) {
    this.worldW = m.world.width;
    this.worldH = m.world.height;
    this.shaft = { ex: m.lift.shaft.x, ew: m.lift.shaft.w };
    this.building = { x: 415, y: 10, width: 937, height: 665 };
    this.liftStops = m.lift.stops;
    const home = Number(m.lift.stops['0']);
    if (!this.lift.moving && !this.lift.trip) {
      this.lift.y = home;
      this.lift.target = home;
    }
    this.lift.homeY = home;
  }

  /* ------------------------------------------------------------ data in -- */

  /** @param {any} layout */
  setLayout(layout) {
    this.layout = layout;
    this.resize();
  }

  /** @param {any[]} agents */
  setAgents(agents) {
    this.agents = agents || [];
  }

  /** The Character Bible from the backend; sprites are matched to it by the employee's name. @param {any[]} bibles */
  setCharacterBible(bibles) {
    this.bibles = Array.isArray(bibles) ? bibles : [];
  }

  /** @param {any[]} bubbles */
  setSpeechBubbles(bubbles) {
    this.speechBubbles = bubbles || [];
  }

  /** @param {any[]} tokens */
  setProjectTokens(tokens) {
    this.projectTokens = tokens || [];
  }

  /** @param {any} agentId */
  setSelectedAgent(agentId) {
    this.selectedAgentId = agentId;
  }

  /* ------------------------------------------------------------- layout -- */

  resize() {
    const parent = this.canvas.parentElement;
    if (!parent || typeof window === 'undefined') return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cssW = parent.clientWidth;
    const cssH = parent.clientHeight;
    if (cssW <= 0 || cssH <= 0) return;
    this.canvas.width = Math.round(cssW * dpr);
    this.canvas.height = Math.round(cssH * dpr);
    this.dpr = dpr;
    // The control bar sits below the scene; only an older layout that overlays it needs an inset.
    const toolbar = parent.querySelector('.camera-toolbar');
    this.viewport.bottomInset = toolbar ? (toolbar.getBoundingClientRect().height + 24) * dpr : 0;
    this.viewport.fitToOffice(this.worldW, this.worldH);
  }

  /* --------------------------------------------------------------- input -- */

  _bindInput() {
    const c = this.canvas;
    if (!c.addEventListener) return;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let moved = 0;
    const localPoint = (/** @type {MouseEvent} */ e) => {
      const rect = c.getBoundingClientRect();
      const scale = c.width / rect.width;
      return { x: (e.clientX - rect.left) * scale, y: (e.clientY - rect.top) * scale };
    };
    c.addEventListener('mousedown', (e) => {
      dragging = true;
      moved = 0;
      const p = localPoint(e);
      lastX = p.x;
      lastY = p.y;
    });
    window.addEventListener('mouseup', (e) => {
      if (dragging && moved < 5) this._handleClick(e);
      dragging = false;
    });
    c.addEventListener('mousemove', (e) => {
      const p = localPoint(e);
      if (!dragging) {
        const hit = this._hitAt(p.x, p.y);
        this.hoverAgentId = hit ? hit.id || hit.agent_id : null;
        c.style.cursor = hit ? 'pointer' : 'grab';
        return;
      }
      const dx = p.x - lastX;
      const dy = p.y - lastY;
      moved += Math.abs(dx) + Math.abs(dy);
      this.viewport.panX += dx;
      this.viewport.panY += dy;
      lastX = p.x;
      lastY = p.y;
    });
    c.addEventListener('mouseleave', () => {
      this.hoverAgentId = null;
    });
    c.addEventListener(
      'wheel',
      (e) => {
        e.preventDefault();
        const p = localPoint(e);
        this.viewport.setZoom(this.viewport.zoom * (e.deltaY < 0 ? 1.12 : 0.89), p.x, p.y);
      },
      { passive: false },
    );

    /*
     * THE KEYBOARD IN THE SCENE.
     *
     * Every employee in the headquarters was reachable with a pointer and with nothing else: the
     * canvas took no focus, so a keyboard walked straight past the largest, most important object
     * on the page. It is now a stop on the tab walk (tabindex in index.html) and it answers the
     * arrows the way the pointer answers a move — the mark travels from employee to employee,
     * reading the floor left to right and then down, and it is exactly the mark the pointer
     * leaves. Enter and Space then do what a click does, through the same one call; nothing new
     * is opened and no new request is made.
     */
    c.addEventListener('keydown', (e) => {
      const key = e.key;
      if (key === 'ArrowRight' || key === 'ArrowDown' || key === 'ArrowLeft' || key === 'ArrowUp') {
        const order = this._seatOrder();
        if (!order.length) return;
        e.preventDefault();
        const step = key === 'ArrowRight' || key === 'ArrowDown' ? 1 : -1;
        const at = order.findIndex((a) => (a.id || a.agent_id) === this.hoverAgentId);
        const next = at < 0 ? (step > 0 ? 0 : order.length - 1) : (at + step + order.length) % order.length;
        this.hoverAgentId = order[next].id || order[next].agent_id;
        return;
      }
      if (key === 'Enter' || key === ' ' || key === 'Spacebar') {
        const order = this._seatOrder();
        const agent = order.find((a) => (a.id || a.agent_id) === this.hoverAgentId);
        if (!agent) return;
        e.preventDefault();
        this.selectedAgentId = agent.id || agent.agent_id;
        this.onSelectAgent(agent);
        return;
      }
      if (key === 'Escape' && this.hoverAgentId) {
        e.preventDefault();
        this.hoverAgentId = null;
      }
    });
    c.addEventListener('blur', () => {
      this.hoverAgentId = null;
    });
  }

  /**
   * The employees the keyboard walks, in the order a reader takes the building: each floor left
   * to right, floors from the top down. Seats come from the renderer's own hit boxes, so what the
   * arrows reach is exactly what a click can reach.
   * @returns {any[]}
   */
  _seatOrder() {
    const hits = this.renderer ? this.renderer.hits : [];
    if (!hits || !hits.length) return this.agents.filter((a) => a && (a.id || a.agent_id));
    return hits
      .slice()
      .sort((a, b) => (Math.round(a.y1 / 40) - Math.round(b.y1 / 40)) || (a.x0 - b.x0))
      .map((h) => h.agent);
  }

  /** @param {number} sx @param {number} sy */
  _hitAt(sx, sy) {
    if (!this.renderer) return null;
    const { x, y } = this.viewport.screenToWorld(sx, sy);
    const hit = this.renderer.hits.find((h) => x >= h.x0 && x <= h.x1 && y >= h.y0 && y <= h.y1);
    return hit ? hit.agent : null;
  }

  /** @param {MouseEvent} e */
  _handleClick(e) {
    const rect = this.canvas.getBoundingClientRect();
    const scale = this.canvas.width / rect.width;
    const hit = this._hitAt((e.clientX - rect.left) * scale, (e.clientY - rect.top) * scale);
    this.selectedAgentId = hit ? hit.id || hit.agent_id : null;
    this.onSelectAgent(hit);
  }

  /* ---------------------------------------------------------------- loop -- */

  /** @param {number} now */
  _loop(now) {
    if (!this.running) return;
    const dt = Math.min(0.05, Math.max(0, (now - this.lastFrame) / 1000));
    this.lastFrame = now;
    this.animTime += dt;
    this._updateLift(dt);
    if (this.world) this.world.step(dt, Date.now());
    this._draw();
    this._measure(now);
    requestAnimationFrame(this._loop);
  }

  /** Frames actually drawn in the last second, and the scene's clock and weather, for the header pills. @param {number} now */
  _measure(now) {
    this._fpsFrames += 1;
    if (now - this._fpsStart < 1000) return;
    this.fps = Math.round((this._fpsFrames * 1000) / (now - this._fpsStart));
    this._fpsFrames = 0;
    this._fpsStart = now;
    // "Live Renderer 144fps" — the same four words and the same figure. The live state carries
    // the weight; what it is and how fast it runs are the standing label and the telemetry.
    if (this.fpsElement) {
      this._setParts(this.fpsElement, [
        ['scene-live', 'Live'],
        ['scene-label', ' Renderer '],
        ['scene-figure', `${this.fps}fps`],
      ]);
    }
    if (this.infoElement && this.world) {
      const time = this.world.time.state;
      const weather = this.world.weather;
      const icon = /** @type {Record<string,string>} */ (WEATHER_ICONS)[weather.state.condition] || '';
      const separator = '  •  ';
      this._setParts(this.infoElement, [
        ['scene-figure', time.text],
        ['scene-sep', separator],
        ['scene-label', 'BUCHAREST'],
        ['scene-sep', separator],
        ['scene-weather', `${icon ? `${icon} ` : ''}${weather.label()}`],
      ]);
    }
  }

  _draw() {
    const ctx = this.ctx;
    if (!ctx) return;
    const w = this.canvas.width;
    const h = this.canvas.height;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    // The empty viewport is the page's own --scene, read from the token block rather than
    // repeated here: the ground behind the render and the ground of the render are one colour.
    ctx.fillStyle = scenePalette().scene;
    ctx.fillRect(0, 0, w, h);
    if (!this.renderer) {
      this._setNote(this.assetsFailed ? 'error' : 'loading');
      return;
    }
    this._setNote(null);
    const { zoom, panX, panY } = this.viewport;
    ctx.setTransform(zoom, 0, 0, zoom, panX, panY);
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, this.worldW, this.worldH);
    ctx.clip();
    ctx.imageSmoothingEnabled = true;
    // Plates arrive pre-composed at this scale; sprites are small, so a cheaper filter suffices.
    ctx.imageSmoothingQuality = 'medium';
    this.renderer.draw(ctx, {
      agents: this.agents,
      bubbles: this.speechBubbles,
      tokens: this.projectTokens,
      lift: this.lift,
      trip: this.lift.trip,
      selectedId: this.selectedAgentId,
      hoverId: this.hoverAgentId,
      liftStops: this.liftStops,
      scale: zoom,
    });
    ctx.restore();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }

  /* ------------------------------------------------------- what it says -- */

  /**
   * Lay the scene's own state over the viewport, or take it away. One element, reused, so the
   * note does not flicker in and out of the document on every frame. The words are SCENE_NOTES's
   * and the shape is the page's.
   * @param {'loading'|'error'|null} kind
   */
  _setNote(kind) {
    if (this._noteKind === kind) return;
    const parent = this.canvas.parentElement;
    if (!parent || typeof document === 'undefined') return;
    this._noteKind = kind;
    if (!kind) {
      if (this._note) this._note.remove();
      this._note = null;
      return;
    }
    if (!this._note) {
      this._note = document.createElement('div');
      // A status, not an alert: it is read when the reader next pauses, and never interrupts.
      this._note.setAttribute('role', 'status');
      parent.append(this._note);
    }
    this._note.className = `scene-note scene-note-${kind}`;
    this._note.textContent = SCENE_NOTES[kind];
  }

  /**
   * THE TWO READOUTS ON THE BEZEL.
   *
   * Both say exactly the words they said before, character for character — `textContent` of each
   * element is unchanged and every test that reads it still reads it. What is new is that the
   * words are handed to the stylesheet in pieces, so the figure can be set in the page's mono
   * with tabular figures (a clock whose seconds do not shove the city name sideways) and the
   * standing label can be set as a label. Built with real elements rather than markup in a
   * string: the page is served under a Content-Security-Policy.
   *
   * @param {HTMLElement} host @param {Array<[string, string]>} parts class name, then its text
   */
  _setParts(host, parts) {
    if (typeof document === 'undefined' || typeof host.replaceChildren !== 'function') {
      host.textContent = parts.map(([, text]) => text).join('');
      return;
    }
    host.replaceChildren(...parts.map(([name, text]) => {
      const span = document.createElement('span');
      if (name) span.className = name;
      span.textContent = text;
      return span;
    }));
  }

  /* ---------------------------------------------------------------- lift -- */

  /** @param {any} zone */
  _cabRow(zone) {
    return this.liftStops ? Number(this.liftStops[String(zone.floor)]) : zone.y + zone.height - LEGACY_CAB_OFFSET;
  }

  /** @param {any} zone */
  _walkRow(zone) {
    return this.liftStops ? Number(this.liftStops[String(zone.floor)]) : zone.y + zone.height - LEGACY_FLOOR_OFFSET;
  }

  /** Decide whether the lift has a job, then move it. Does nothing without a token trip. @param {number} dt */
  _updateLift(dt) {
    if (!this.layout || !this.building || !this.shaft) return;
    const zones = this.layout.zones || [];

    for (const token of this.projectTokens) {
      const zone = zones.find((/** @type {any} */ z) => token.y >= z.y && token.y <= z.y + z.height);
      if (!zone) continue;
      const previous = this.tokenPlaces.get(token.id);
      if (previous && previous.floor !== zone.floor && !this.lift.trip) {
        const from = zones.find((/** @type {any} */ z) => z.id === previous.zoneId) || zone;
        this.lift.trip = {
          tokenId: token.id,
          phase: 'summon',
          fromY: this._cabRow(from),
          toY: this._cabRow(zone),
          boardLine: this._walkRow(from),
          exitLine: this._walkRow(zone),
          startX: previous.x,
          x: previous.x,
          exitX: token.x,
          doorX: this.shaft.ex - 8,
          dwell: 0,
        };
        this.lift.target = this._cabRow(from);
        this.lift.moving = Math.abs(this.lift.y - this.lift.target) > 1;
        this.lift.restUntil = 0;
      }
      this.tokenPlaces.set(token.id, { floor: zone.floor, zoneId: zone.id, x: token.x, y: token.y });
    }

    this._advanceCourier(dt);

    if (!this.lift.moving) {
      const idle = !this.lift.trip;
      if (idle && this.lift.restUntil && this.animTime > this.lift.restUntil && this.lift.homeY !== undefined) {
        this.lift.target = this.lift.homeY;
        this.lift.moving = true;
        this.lift.restUntil = 0;
      }
      return;
    }

    const speed = 90;
    const delta = this.lift.target - this.lift.y;
    const stepSize = speed * dt;
    if (Math.abs(delta) <= stepSize) {
      this.lift.y = this.lift.target;
      this.lift.moving = false;
      if (!this.lift.trip && this.lift.homeY !== undefined && Math.abs(this.lift.y - this.lift.homeY) > 1) {
        this.lift.restUntil = this.animTime + 6;
      }
    } else {
      this.lift.y += Math.sign(delta) * stepSize;
    }
  }

  /** Walk the courier through summon -> board -> travel -> alight. @param {number} dt */
  _advanceCourier(dt) {
    const trip = this.lift.trip;
    if (!trip || !this.shaft) return;

    const doorX = this.shaft.ex - 8;
    const insideX = this.shaft.ex + this.shaft.ew / 2;
    const walk = 78 * dt;

    const stepToward = (/** @type {number} */ target) => {
      const gap = target - trip.x;
      if (Math.abs(gap) <= walk) {
        trip.x = target;
        return true;
      }
      trip.x += Math.sign(gap) * walk;
      return false;
    };

    if (trip.phase === 'summon') {
      const atDoors = stepToward(doorX);
      const cabHere = !this.lift.moving && Math.abs(this.lift.y - trip.fromY) <= 1;
      if (atDoors && cabHere) {
        trip.phase = 'board';
        trip.dwell = 0;
      }
      return;
    }
    if (trip.phase === 'board') {
      trip.dwell += dt;
      stepToward(insideX);
      if (trip.dwell > 1.1) {
        trip.phase = 'travel';
        this.lift.target = trip.toY;
        this.lift.moving = Math.abs(this.lift.y - trip.toY) > 1;
        if (!this.lift.moving) trip.phase = 'alight';
      }
      return;
    }
    if (trip.phase === 'travel') {
      if (!this.lift.moving && Math.abs(this.lift.y - trip.toY) <= 1) {
        trip.phase = 'alight';
        trip.dwell = 0;
        trip.x = insideX;
      }
      return;
    }
    trip.dwell += dt;
    const delivered = stepToward(trip.exitX);
    if (delivered && trip.dwell > 0.8) {
      this.lift.trip = null;
      this.lift.restUntil = this.animTime + 4;
    }
  }

  destroy() {
    this.running = false;
  }
}
