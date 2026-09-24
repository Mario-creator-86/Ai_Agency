import { HQAssets } from './hq_assets.js';
import { WorldSimulationManager, HQRenderer } from './hq_world.js';
import { scenePalette } from './hq_palette.js';
import { NO_INSETS, between, easeOut, frameFit } from './game_frame.js';

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
    /** What the frame's drawers cover, in canvas px (game_frame.js). @type {import('./game_frame.js').Insets} */
    this.insets = NO_INSETS;
    /** What the frame always covers: the rails and the row of sky over the roof (game_frame.js frameFloor). @type {import('./game_frame.js').Insets} */
    this.floor = NO_INSETS;
    /** The part of the world the camera keeps whole and centred: the building. @type {import('./game_frame.js').Rect|null} */
    this.focus = null;
  }

  /**
   * The camera of the game frame: the world covers the viewport and the focus is centred in the
   * room the drawers leave (game_frame.js frameFit).
   * @param {number} worldWidth @param {number} worldHeight
   * @returns {{zoom: number, panX: number, panY: number}}
   */
  frameStand(worldWidth, worldHeight) {
    const cw = this.canvas.width || 1;
    const ch = Math.max(1, (this.canvas.height || 1) - this.bottomInset);
    const stand = frameFit({ cw, ch, worldW: worldWidth, worldH: worldHeight, focus: this.focus, insets: this.insets, floor: this.floor });
    stand.zoom = clamp(stand.zoom, this.minZoom, this.maxZoom);
    return stand;
  }

  /** The frame's camera once the building is known; before it, the whole-world fit. @param {number} worldWidth @param {number} worldHeight */
  fitFrame(worldWidth, worldHeight) {
    if (!this.focus) {
      this.fitToOffice(worldWidth, worldHeight);
      return;
    }
    Object.assign(this, this.frameStand(worldWidth, worldHeight));
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

/**
 * The top of the canvas in world units when it lies above the world's top edge (a negative
 * number), else 0: how far up the page paints its own sky.
 * @param {{zoom: number, panY: number}} vp
 */
export function skyTopOf(vp) {
  const z = vp.zoom > 0 ? vp.zoom : 1;
  const top = -vp.panY / z;
  return top < 0 ? top : 0;
}

export const WORLD_W = 1600;
export const WORLD_H = 840;
/** The building in the world, from the Blender camera: what the frame's camera keeps whole. */
export const BUILDING = Object.freeze({ x: 415, y: 10, width: 937, height: 665 });

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
  loading: 'Se încarcă sediul AMN-AI…',
  error: 'Grafica sediului nu a putut fi încărcată.',
};

/** How long the camera takes to re-centre when a drawer opens or closes. */
const GLIDE_MS = 420;

const WEATHER_ICONS = { clear: '☀', partly_cloudy: '⛅', cloudy: '☁', fog: '🌫', drizzle: '🌦', rain: '🌧', snow: '❄', storm: '⛈', unknown: '' };

export class OfficeEngine {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {{onSelectAgent?: (agent:any) => void, fetchWeather?: () => Promise<any>, infoElement?: HTMLElement|null, onFrameRate?: (fps: number) => void, seed?: number, reducedMotion?: () => boolean, dataLive?: () => boolean, parked?: boolean, onView?: (view: any) => void}} [options]
   */
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.onSelectAgent = options.onSelectAgent || (() => {});
    this.fetchWeather = options.fetchWeather || (async () => ({ available: false, reason: 'not_configured' }));
    this.infoElement = options.infoElement || null;
    // The renderer measures its own frame rate and hands it on; what the page calls it (and
    // whether it is shown at all) is decided with the other live signals, in live_claims.js.
    this.onFrameRate = typeof options.onFrameRate === 'function' ? options.onFrameRate : null;
    // Asked on every frame, so a visitor who turns reduced motion on mid-visit is obeyed at once.
    this.reducedMotion = typeof options.reducedMotion === 'function' ? options.reducedMotion : () => false;
    // Whether the page still has the studio's data; asked on every frame like reduced motion.
    // Without it the street and the employees' loops hold their frame (hq_events.js streetMoves).
    this.dataLive = typeof options.dataLive === 'function' ? options.dataLive : () => true;

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
    /** @type {any} */
    this.facts = {};
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
    /**
     * PARKED: built, its art loaded and one frame drawn, but not running. The page builds the
     * engine while the title screen is up, so the plates are composed and on the GPU before the
     * key is given, and the entry into the building does not wait for them (prewarm).
     */
    this.parked = options.parked === true;
    /**
     * HITS ONLY: while the Unreal stream (or its frozen frame, or its "starting" plate) lies over
     * the canvas, nothing the canvas paints can be seen. It then keeps only the employees' hit
     * boxes, so a click on the video still finds who sits there, and paints nothing.
     */
    this.hitsOnly = false;
    /** Told whenever the camera or the box changes: the stream follows it (game_frame.js). */
    this.onView = typeof options.onView === 'function' ? options.onView : null;
    this._viewKey = '';
    /** A camera move under way: from, to, start, duration. @type {any} */
    this.glide = null;
    /** The drawers' cover in CSS px, kept so a resize can restate it in canvas px. @type {any} */
    this._cssInsets = null;
    /** A prewarm asked for before the art arrived. @type {{width:number, height:number}|null} */
    this._warmWanted = null;
    this.warmed = false;
    this._looping = false;
    /** @type {ResizeObserver|null} */
    this._sizeWatch = null;
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

    /** Settles once the scene's stylesheet has loaded (or could not be). @type {Promise<void>} */
    this.themeReady = Promise.resolve();
    if (typeof document !== 'undefined' && !document.getElementById('office-scene-theme')) {
      const theme = document.createElement('link');
      theme.id = 'office-scene-theme';
      theme.rel = 'stylesheet';
      theme.href = new URL('./office_scene.css?no-inline', import.meta.url).href;
      this.themeReady = new Promise((settle) => {
        theme.addEventListener('load', () => settle(), { once: true });
        theme.addEventListener('error', () => settle(), { once: true });
      });
      theme.addEventListener('load', () => this.resize());
      document.head.append(theme);
    }

    this._bindInput();
    this.resize();
    this._loop = this._loop.bind(this);
    if (!this.parked) this._startLoop();
    // The box the canvas fills changes with the window, the fullscreen and the frame; the canvas
    // follows it so it is never stretched.
    if (typeof ResizeObserver === 'function' && canvas.parentElement) {
      let last = '';
      this._sizeWatch = new ResizeObserver((entries) => {
        const box = entries[0] && entries[0].contentRect;
        const key = box ? `${Math.round(box.width)}x${Math.round(box.height)}` : '';
        if (!key || key === last || !box.width) return;
        last = key;
        if (!this.parked) this.resize();
      });
      this._sizeWatch.observe(canvas.parentElement);
    }
    /** Settles true once the art is loaded and the world is built, false when it could not be. @type {Promise<boolean>} */
    this.ready = this.assets.load().then((ok) => {
      if (!this.running) return false;
      if (!ok) {
        this.assetsFailed = true;
        return false;
      }
      this.world = new WorldSimulationManager({ assets: this.assets, fetchWeather: this.fetchWeather, seed: options.seed });
      this.renderer = new HQRenderer(this.world);
      this.renderer.setFacts(this.facts);
      this._applyManifest(this.assets.manifest);
      this.resize();
      if (this._warmWanted) this.prewarm(this._warmWanted.width, this._warmWanted.height);
      return true;
    });
  }

  /* -------------------------------------------------------------- parking -- */

  _startLoop() {
    if (this._looping || !this.running) return;
    this._looping = true;
    this.lastFrame = typeof performance !== 'undefined' ? performance.now() : 0;
    this._fpsStart = this.lastFrame;
    this._fpsFrames = 0;
    requestAnimationFrame(this._loop);
  }

  /** Stop drawing (the workspace is hidden); the art and the caches stay. */
  park() {
    this.parked = true;
  }

  /** Start drawing into the canvas as it is laid out now. */
  unpark() {
    this.parked = false;
    this.resize();
    this._startLoop();
  }

  /**
   * Draw one frame, now, at the size the canvas will have once the workspace is shown, while the
   * visitor is still on the title screen. The frame composes the plate groups at the scale the
   * entry will use, lays the street's sprite sheets under the hour's light and puts all of it on
   * the GPU. Measured before this: a 90-146ms frame at the key, the first upload of the plates
   * and the first vehicle tints, in the middle of the entry into the building.
   * @param {number} cssWidth @param {number} cssHeight the scene viewport's box once shown
   */
  prewarm(cssWidth, cssHeight) {
    if (!this.renderer || !this.world) {
      this._warmWanted = { width: cssWidth, height: cssHeight };
      return false;
    }
    this._warmWanted = null;
    if (!(cssWidth > 0 && cssHeight > 0) || typeof window === 'undefined') return false;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    this.canvas.width = Math.round(cssWidth * dpr);
    this.canvas.height = Math.round(cssHeight * dpr);
    this.dpr = dpr;
    this.viewport.bottomInset = 0;
    if (this._cssInsets) this._restateInsets();
    this.viewport.fitFrame(this.worldW, this.worldH);
    this.renderer.warmTints(this.world.time.state, this.world.weather.effects);
    this._draw(true);
    // Reading one pixel back makes the browser carry out the queued drawing now, while nothing
    // is moving, rather than at the first frame after the key.
    try {
      if (this.ctx) this.ctx.getImageData(0, 0, 1, 1);
    } catch {
      // a lost canvas: the frame is simply drawn on the first real one
    }
    this.warmed = true;
    return true;
  }

  /* --------------------------------------------------------------- camera -- */

  _restateInsets() {
    const dpr = this.dpr || 1;
    const scaled = (/** @type {any} */ i) => ({
      left: Math.max(0, (i && i.left) || 0) * dpr,
      right: Math.max(0, (i && i.right) || 0) * dpr,
      top: Math.max(0, (i && i.top) || 0) * dpr,
      bottom: Math.max(0, (i && i.bottom) || 0) * dpr,
    });
    this.viewport.insets = scaled(this._cssInsets);
    this.viewport.floor = scaled(this._cssFloor);
  }

  /**
   * What the frame's drawers cover of the render, in CSS pixels. The camera re-centres the
   * building in the room left, gliding there unless the visitor asked for less motion.
   * The floor is what the frame covers whatever the drawers do (the rails, the row of sky above
   * the roof); the zoom is chosen against it, so a drawer only moves the camera.
   * @param {import('./game_frame.js').Insets} insets
   * @param {{glide?: boolean, floor?: import('./game_frame.js').Insets}} [options]
   */
  setInsets(insets, options = {}) {
    const before = { insets: this.viewport.insets, floor: this.viewport.floor };
    this._cssInsets = { ...insets };
    this._cssFloor = options.floor ? { ...options.floor } : null;
    this._restateInsets();
    const keys = /** @type {Array<'left'|'right'|'top'|'bottom'>} */ (['left', 'right', 'top', 'bottom']);
    const same = keys.every((k) => Math.abs(before.insets[k] - this.viewport.insets[k]) < 0.5 && Math.abs(before.floor[k] - this.viewport.floor[k]) < 0.5);
    if (same) return;
    this.fitView({ glide: options.glide !== false });
  }

  /**
   * Stand the camera where the frame puts it (the «Încadrează» key, a drawer opening or closing).
   * @param {{glide?: boolean}} [options]
   */
  fitView(options = {}) {
    const vp = this.viewport;
    if (!vp.focus) {
      vp.fitToOffice(this.worldW, this.worldH);
      return;
    }
    const to = vp.frameStand(this.worldW, this.worldH);
    const glide = Boolean(options.glide) && !this.reducedMotion() && !this.parked;
    if (!glide) {
      this.glide = null;
      Object.assign(vp, to);
      return;
    }
    const now = typeof performance !== 'undefined' ? performance.now() : 0;
    this.glide = { from: { zoom: vp.zoom, panX: vp.panX, panY: vp.panY }, to, start: now, ms: GLIDE_MS };
  }

  /** The middle of the room the drawers leave, in canvas px: where the zoom keys zoom about. */
  focusPoint() {
    const vp = this.viewport;
    const w = this.canvas.width;
    return { x: vp.insets.left + (w - vp.insets.left - vp.insets.right) / 2, y: this.canvas.height / 2 };
  }

  /** @param {number} factor */
  zoomBy(factor) {
    this.glide = null;
    const p = this.focusPoint();
    this.viewport.setZoom(this.viewport.zoom * factor, p.x, p.y);
  }

  /** @param {number} zoom */
  zoomTo(zoom) {
    this.glide = null;
    const p = this.focusPoint();
    this.viewport.setZoom(zoom, p.x, p.y);
  }

  /**
   * While the stream (its video, its frozen frame or its "starting" plate) covers the canvas, the
   * canvas keeps only its hit boxes.
   * @param {boolean} covered
   */
  setCovered(covered) {
    this.hitsOnly = Boolean(covered);
  }

  /** The camera and the box, for whatever follows them (the stream). */
  view() {
    const vp = this.viewport;
    return {
      cw: this.canvas.width,
      ch: this.canvas.height,
      dpr: this.dpr || 1,
      worldW: this.worldW,
      worldH: this.worldH,
      zoom: vp.zoom,
      panX: vp.panX,
      panY: vp.panY,
    };
  }

  _emitView() {
    if (!this.onView) return;
    const v = this.view();
    const key = `${v.cw}|${v.ch}|${v.zoom.toFixed(5)}|${v.panX.toFixed(2)}|${v.panY.toFixed(2)}`;
    if (key === this._viewKey) return;
    this._viewKey = key;
    this.onView(v);
  }

  /** @param {number} now */
  _advanceGlide(now) {
    const g = this.glide;
    if (!g) return;
    const t = (now - g.start) / g.ms;
    Object.assign(this.viewport, between(g.from, g.to, easeOut(t)));
    if (t >= 1) this.glide = null;
  }

  /** @param {any} m */
  _applyManifest(m) {
    this.worldW = m.world.width;
    this.worldH = m.world.height;
    this.shaft = { ex: m.lift.shaft.x, ew: m.lift.shaft.w };
    this.building = { ...BUILDING };
    this.viewport.focus = this.building;
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

  /**
   * What the page knows of the studio beyond its employees, for the building's screens: the
   * newest run and the day's track, the treasury and budget, the serial, the topics, the newest
   * film's frame (hq_screens.js). Nothing is redrawn unless what a screen shows has changed.
   * @param {any} facts
   */
  setFacts(facts) {
    this.facts = facts || {};
    if (this.renderer) this.renderer.setFacts(this.facts);
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
    if (this._cssInsets) this._restateInsets();
    this.glide = null;
    this.viewport.fitFrame(this.worldW, this.worldH);
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
    if (!this.running || this.parked) {
      this._looping = false;
      return;
    }
    const dt = Math.min(0.05, Math.max(0, (now - this.lastFrame) / 1000));
    this.lastFrame = now;
    this.animTime += dt;
    this._updateLift(dt);
    if (this.world) this.world.step(dt, Date.now(), this.reducedMotion(), this.dataLive());
    this._advanceGlide(now);
    this._draw();
    this._emitView();
    this._measure(now);
    requestAnimationFrame(this._loop);
  }

  /** Frames this renderer actually drew in the last second, and the scene's clock and weather, for the readouts. @param {number} now */
  _measure(now) {
    this._fpsFrames += 1;
    if (now - this._fpsStart < 1000) return;
    this.fps = Math.round((this._fpsFrames * 1000) / (now - this._fpsStart));
    this._fpsFrames = 0;
    this._fpsStart = now;
    if (this.onFrameRate) this.onFrameRate(this.fps);
    if (this.infoElement && this.world) {
      const time = this.world.time.state;
      const weather = this.world.weather;
      const icon = /** @type {Record<string,string>} */ (WEATHER_ICONS)[weather.state.condition] || '';
      const separator = '  •  ';
      this._setParts(this.infoElement, [
        ['scene-figure', time.text],
        ['scene-sep', separator],
        ['scene-label', 'BUCUREȘTI'],
        ['scene-sep', separator],
        ['scene-weather', `${icon ? `${icon} ` : ''}${weather.label()}`],
      ]);
    }
  }

  /** @param {boolean} [force] draw even while the stream covers the canvas (the prewarm) */
  _draw(force = false) {
    const ctx = this.ctx;
    if (!ctx) return;
    if (this.hitsOnly && !force && this.renderer) {
      this._setNote(null);
      this.renderer.keepHits(this.agents);
      return;
    }
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
    // Above the world's top edge is sky: the page paints its own sky up to the canvas's top, so
    // the roof stands under open sky rather than against the frame's edge (hq_sky.js drawSky).
    const skyTop = skyTopOf(this.viewport);
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, skyTop, this.worldW, this.worldH - skyTop);
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
      skyTop,
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
    if (this._sizeWatch) this._sizeWatch.disconnect();
  }
}
