import { TimeOfDayManager } from './hq_time.js';
import { WeatherManager } from './hq_weather.js';
import { RandomEventManager } from './hq_events.js';
import { TrafficManager, EMERGENCY } from './hq_traffic.js';
import { PedestrianManager } from './hq_pedestrians.js';
import { AgentVisualStateManager, spriteFor, screenModeFor, stateOf } from './hq_agents.js';
import { SkyRenderer } from './hq_sky.js';
import { bubbleFrame } from './speech_bubble.js';

/**
 * WorldSimulationManager owns every manager of the living headquarters and advances them in one
 * place; HQRenderer paints the plates and the live actors in the order the Blender build defined.
 *
 * Randomness comes from one seeded source (mulberry32), so a seed reproduces a street exactly.
 * What the studio is doing comes only from backend state handed in by the engine.
 */

/** @param {number} seed */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function random() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const SHELTER_ADS = [
  { title: 'AMN-AI', lines: ['BETTER', 'TOMORROW', 'TOGETHER.'], accent: '#5eead4', top: '#0d2344', bottom: '#1d4b8a', mark: true },
  { title: 'NEXUS', lines: ['CURIOSITY', 'SCIENCE STORIES', 'ON YOUTUBE'], accent: '#f0abfc', top: '#1d0f3a', bottom: '#46237e', mark: false },
  { title: 'INSIDE', lines: ['THE NEXUS', 'HOW IT IS MADE', 'ON YOUTUBE'], accent: '#5eead4', top: '#07161a', bottom: '#11474d', mark: false },
];

const SHELTER_STOP_X = 1462;
const HORIZON_ROW = 350;
/**
 * Plate layers are grouped by what is drawn between them; each group is composed once at the
 * scale it is shown at (world px x zoom x device pixels), so a frame is a few 1:1 blits instead
 * of a dozen large resamplings. A group is rebuilt when the zoom settles on a new scale or the
 * daylight crossfade moves on.
 */
/** @type {Array<[string, string[]]>} */
const PLATE_GROUPS = [
  ['back', ['city', 'street_back', 'street_ground']],
  ['building_back', ['building_back']],
  ['building_front', ['building_front', 'building_shell']],
  ['street_props', ['street_props']],
  ['street_kerb', ['street_kerb']],
  ['street_front', ['street_front']],
];
/** @type {Map<string, HTMLCanvasElement>} */
const FLARES = new Map();

/**
 * A soft round glow for a lamp, drawn once per colour and reused by every vehicle.
 * @param {string} rgb "r,g,b"
 */
function flareSprite(rgb) {
  let sprite = FLARES.get(rgb);
  if (!sprite && typeof document !== 'undefined') {
    sprite = document.createElement('canvas');
    sprite.width = 64;
    sprite.height = 64;
    const c = sprite.getContext('2d');
    if (c) {
      const g = c.createRadialGradient(32, 32, 0, 32, 32, 32);
      g.addColorStop(0, `rgba(${rgb},1)`);
      g.addColorStop(0.18, `rgba(${rgb},0.55)`);
      g.addColorStop(0.5, `rgba(${rgb},0.12)`);
      g.addColorStop(1, `rgba(${rgb},0)`);
      c.fillStyle = g;
      c.fillRect(0, 0, 64, 64);
    }
    FLARES.set(rgb, sprite);
  }
  return sprite;
}

const SPRITE_SCALE = 1.1;
/** Seated employees sit up above their consoles, as in the reference, not sunk behind them. */
const SEATED_LIFT = 6;
const PEDESTRIAN_SCALE = 0.86;

export class AmbientAnimationManager {
  constructor() {
    this.clock = 0;
    this.adIndex = 0;
    this._adTimer = 0;
  }

  /** @param {number} dt */
  update(dt) {
    this.clock += dt;
    this._adTimer += dt;
    if (this._adTimer > 14) {
      this._adTimer = 0;
      this.adIndex = (this.adIndex + 1) % SHELTER_ADS.length;
    }
  }
}

export class WorldSimulationManager {
  /**
   * @param {{assets:any, fetchWeather:() => Promise<any>, seed?:number, now?:() => Date}} options
   */
  constructor(options) {
    const assets = options.assets;
    const m = assets.manifest;
    this.assets = assets;
    this.rng = mulberry32(options.seed ?? Date.now());
    this.worldW = m.world.width;
    this.worldH = m.world.height;
    this.time = new TimeOfDayManager({ now: options.now });
    this.weather = new WeatherManager(options.fetchWeather);
    this.events = new RandomEventManager(assets.events, this.rng);
    const street = m.street;
    this.traffic = new TrafficManager({
      lanes: street.lanes,
      catalogue: assets.vehicles,
      worldWidth: this.worldW,
      rng: this.rng,
      pixelsPerMetre: m.camera.pixels_per_metre,
      crosswalk: street.crosswalk,
      shelterX: SHELTER_STOP_X,
    });
    this.pedestrians = new PedestrianManager({
      rows: street.walk,
      crosswalk: street.crosswalk,
      road: street.road,
      nearWalkRow: street.near_walk_row,
      shelterX: SHELTER_STOP_X,
      worldWidth: this.worldW,
      sheets: Object.keys(assets.pedestrians?.characters || {}),
      rng: this.rng,
    });
    this.agents = new AgentVisualStateManager(this.rng);
    this.ambient = new AmbientAnimationManager();
    this.sky = new SkyRenderer({ worldWidth: this.worldW, worldHeight: this.worldH, horizonRow: HORIZON_ROW, rng: this.rng });
    /** @type {any[]} */
    this.agentList = [];
    this.events.on((kind, event) => this.onEvent(kind, event));
    // a street is never empty on arrival: warm the simulation up for a minute of city time
    for (let i = 0; i < 240; i += 1) this.step(0.25, 0);
  }

  /** @param {string} kind @param {any} event */
  onEvent(kind, event) {
    if (kind !== 'start') return;
    const id = event.def.eventId;
    if (id === 'bus_arrives' || id in EMERGENCY) this.traffic.spawnForEvent(id);
    else if (id === 'pedestrians_cross') this.pedestrians.startCrossing();
    else if (id === 'jogger_group') this.pedestrians.startJoggers(3);
    if (event.def.reactionRadius >= 1000) {
      this.agents.react(this.agentList, 6);
      this.pedestrians.reactAll(5);
    }
  }

  /** @param {number} dt @param {number} nowMs */
  step(dt, nowMs) {
    const time = this.time.update(dt);
    if (nowMs) this.weather.update(nowMs);
    const fx = this.weather.effects;
    this.events.update(dt, { weather: this.weather.state.condition, phase: time.phase });
    this.traffic.crosswalkBusy = this.pedestrians.crosswalkBusy;
    this.traffic.waitingAtShelter = this.pedestrians.waitingAtShelter;
    this.traffic.update(dt, { hour: time.hour, day: time.day, effects: fx });
    this.pedestrians.update(dt, { hour: time.hour, day: time.day, effects: fx, busAtShelter: this.traffic.busAtShelter });
    this.agents.update(dt);
    this.ambient.update(dt);
    this.sky.update(dt, time, fx);
    if (time.daylight > 0.001) this.assets.loadVariant('day');
  }
}

export class HQRenderer {
  /** @param {WorldSimulationManager} world */
  constructor(world) {
    this.world = world;
    this.assets = world.assets;
    this.m = world.assets.manifest;
    /** @type {Array<{agent:any, x0:number, y0:number, x1:number, y1:number}>} */
    this.hits = [];
    /** @type {Map<string, {canvas: HTMLCanvasElement, x:number, y:number, w:number, h:number}>} */
    this.caches = new Map();
    this.cacheKey = '';
    this._wantedScale = 0;
    this._scaleSince = 0;
  }

  /** The union of the rects the group's layers cover, in world px. @param {string[]} layers */
  groupRect(layers) {
    let x0 = Infinity;
    let y0 = Infinity;
    let x1 = -Infinity;
    let y1 = -Infinity;
    for (const name of layers) {
      for (const variant of /** @type {Array<'night'|'day'>} */ (['night', 'day'])) {
        const l = this.assets.layer(variant, name);
        if (!l) continue;
        x0 = Math.min(x0, l.x);
        y0 = Math.min(y0, l.y);
        x1 = Math.max(x1, l.x + l.w);
        y1 = Math.max(y1, l.y + l.h);
      }
    }
    return Number.isFinite(x0) ? { x: Math.floor(x0), y: Math.floor(y0), w: Math.ceil(x1 - x0), h: Math.ceil(y1 - y0) } : null;
  }

  /**
   * Compose the plate groups for this display scale and light, when either has changed.
   * @param {number} displayScale canvas px per world px
   * @param {any} time
   */
  ensureCaches(displayScale, time) {
    if (typeof document === 'undefined') return false;
    const bucket = Math.min(2.5, Math.max(0.2, Math.round(displayScale * 1000) / 1000));
    const now = performance.now();
    if (bucket !== this._wantedScale) {
      this._wantedScale = bucket;
      this._scaleSince = now;
    }
    const settled = now - this._scaleSince > 220 || !this.caches.size;
    const light = Math.round(time.daylight * 40);
    const loaded = `${Object.keys(this.assets.layers.night).length}/${Object.keys(this.assets.layers.day).length}`;
    const key = `${bucket}|${light}|${loaded}`;
    if (key === this.cacheKey || !settled) return this.caches.size > 0;
    this.cacheKey = key;
    for (const [group, layers] of PLATE_GROUPS) {
      const rect = this.groupRect(layers);
      if (!rect) continue;
      let entry = this.caches.get(group);
      const cw = Math.max(1, Math.round(rect.w * bucket));
      const ch = Math.max(1, Math.round(rect.h * bucket));
      if (!entry || entry.canvas.width !== cw || entry.canvas.height !== ch) {
        const canvas = document.createElement('canvas');
        canvas.width = cw;
        canvas.height = ch;
        entry = { canvas, ...rect };
        this.caches.set(group, entry);
      }
      Object.assign(entry, rect);
      const c = entry.canvas.getContext('2d');
      if (!c) continue;
      c.setTransform(1, 0, 0, 1, 0, 0);
      c.clearRect(0, 0, cw, ch);
      c.imageSmoothingEnabled = true;
      c.imageSmoothingQuality = 'high';
      c.setTransform(bucket, 0, 0, bucket, -rect.x * bucket, -rect.y * bucket);
      for (const name of layers) {
        this.layer(c, name, time);
        if (name === 'city') this.drawSkySlogan(c, time);
      }
    }
    return true;
  }

  /** @param {CanvasRenderingContext2D} ctx @param {string} group @param {any} time */
  plate(ctx, group, time) {
    const entry = this.useCaches ? this.caches.get(group) : null;
    if (entry) {
      ctx.drawImage(entry.canvas, entry.x, entry.y, entry.w, entry.h);
      return;
    }
    const layers = PLATE_GROUPS.find(([g]) => g === group)?.[1] || [];
    for (const name of layers) {
      this.layer(ctx, name, time);
      if (name === 'city') this.drawSkySlogan(ctx, time);
    }
  }

  /**
   * @param {CanvasRenderingContext2D} ctx
   * @param {{agents:any[], bubbles:any[], tokens:any[], lift:any, trip:any, selectedId:any, hoverId:any, liftStops:any, scale?:number}} state
   */
  draw(ctx, state) {
    const w = this.world;
    const time = w.time.state;
    const fx = w.weather.effects;
    w.agentList = state.agents;
    this.useCaches = this.ensureCaches(state.scale || 1, time);
    w.sky.drawSky(ctx, time, fx);
    w.sky.drawSkyEvents(ctx, w.events, time);
    this.plate(ctx, 'back', time);
    this.drawBillboard(ctx);
    this.drawRoadLights(ctx, time, fx);
    this.plate(ctx, 'building_back', time);
    this.drawScreens(ctx, state.agents);
    this.drawLift(ctx, state);
    this.drawAgents(ctx, state);
    this.plate(ctx, 'building_front', time);
    w.sky.drawSkyEvents(ctx, w.events, time, 'near');
    this.drawTokens(ctx, state);
    this.plate(ctx, 'street_props', time);
    this.drawShelter(ctx, time);
    this.drawPedestrians(ctx, fx);
    this.plate(ctx, 'street_kerb', time);
    this.drawVehicles(ctx, time, fx);
    this.plate(ctx, 'street_front', time);
    w.sky.drawWeather(ctx, time, fx);
    this.drawNightGrade(ctx, time);
    this.drawBubbles(ctx, state);
    this.drawSelection(ctx, state);
  }

  /** @param {CanvasRenderingContext2D} ctx @param {string} name @param {any} time */
  layer(ctx, name, time) {
    const night = this.assets.layer('night', name);
    const day = this.assets.layer('day', name);
    const d = time.daylight;
    if (night && (d < 0.999 || !day)) ctx.drawImage(night.img, night.x, night.y, night.w, night.h);
    if (day && d > 0.001) {
      ctx.globalAlpha = night ? d : 1;
      ctx.drawImage(day.img, day.x, day.y, day.w, day.h);
      ctx.globalAlpha = 1;
    }
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} time */
  drawSkySlogan(ctx, time) {
    ctx.font = '600 8px "Segoe UI", system-ui, sans-serif';
    ctx.textAlign = 'right';
    ctx.fillStyle = time.daylight > 0.6 ? 'rgba(30,40,60,0.55)' : 'rgba(222,230,244,0.7)';
    letterSpaced(ctx, 'PEOPLE BUILD TOOLS.', 1582, 56, 1.6);
    letterSpaced(ctx, 'AI BUILDS TOMORROW.', 1582, 70, 1.6);
    ctx.textAlign = 'left';
  }

  /** @param {CanvasRenderingContext2D} ctx */
  drawBillboard(ctx) {
    const ev = this.world.events.active.find((e) => e.def.eventId === 'billboard_studio_ad');
    const rect = this.m.street.billboard?.rect;
    if (!ev || !rect) return;
    const [x, y, bw, bh] = rect;
    const p = this.world.events.progress(ev);
    const fade = Math.min(1, p * 8, (1 - p) * 8);
    ctx.globalAlpha = fade;
    const g = ctx.createLinearGradient(0, y, 0, y + bh);
    g.addColorStop(0, '#0b1430');
    g.addColorStop(1, '#16325e');
    ctx.fillStyle = g;
    ctx.fillRect(x, y, bw, bh);
    drawMark(ctx, x + 6, y + 9, 20, '#5eead4');
    ctx.fillStyle = '#f5f7ff';
    ctx.font = '700 13px "Segoe UI", system-ui, sans-serif';
    ctx.fillText('AMN-AI', x + 32, y + 21);
    ctx.font = '600 6px "Segoe UI", system-ui, sans-serif';
    ctx.fillStyle = '#5eead4';
    ctx.fillText('AUTONOMOUS MACHINE NEXUS', x + 32, y + 31);
    ctx.globalAlpha = 1;
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} time @param {any} fx */
  drawRoadLights(ctx, time, fx) {
    const dark = 1 - time.daylight;
    const wet = Math.max(fx.wet, 0.35);
    if (dark < 0.1) return;
    const road = this.m.street.road;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    for (const v of this.world.traffic.vehicles) {
      const nose = v.x + (v.dir * v.length) / 2;
      const tail = v.x - (v.dir * v.length) / 2;
      const beam = ctx.createLinearGradient(nose, 0, nose + v.dir * 150, 0);
      beam.addColorStop(0, `rgba(255,240,200,${0.16 * dark})`);
      beam.addColorStop(1, 'rgba(255,240,200,0)');
      ctx.fillStyle = beam;
      ctx.beginPath();
      ctx.moveTo(nose, v.row - 4);
      ctx.lineTo(nose + v.dir * 150, v.row - 12);
      ctx.lineTo(nose + v.dir * 150, v.row + 8);
      ctx.lineTo(nose, v.row + 2);
      ctx.fill();
      const refl = ctx.createLinearGradient(0, v.row, 0, Math.min(road.bottom + 30, v.row + 50));
      refl.addColorStop(0, `rgba(255,70,60,${0.22 * dark * wet})`);
      refl.addColorStop(1, 'rgba(255,70,60,0)');
      ctx.fillStyle = refl;
      ctx.fillRect(tail - 4, v.row, 8, 50);
      const head = ctx.createLinearGradient(0, v.row, 0, v.row + 60);
      head.addColorStop(0, `rgba(255,236,190,${0.3 * dark * wet})`);
      head.addColorStop(1, 'rgba(255,236,190,0)');
      ctx.fillStyle = head;
      ctx.fillRect(nose - 5, v.row, 10, 60);
    }
    ctx.restore();
  }

  /** @param {any[]} agents @param {string} desk */
  agentAt(agents, desk) {
    return agents.find((a) => a.desk_id === desk) || null;
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any[]} agents */
  drawScreens(ctx, agents) {
    const clock = this.world.ambient.clock;
    const screens = this.m.screens || {};
    for (const [name, screen] of Object.entries(screens)) {
      const [x, y, sw, sh] = screen.rect;
      if (screen.kind === 'render_status') {
        this.drawRenderDisplay(ctx, x, y, sw, sh, this.agentAt(agents, 'desk_video'), clock);
        continue;
      }
      const agent = screen.desk ? this.agentAt(agents, screen.desk) : agents.find((a) => this.zoneOf(a) === screen.zone);
      const mode = agent ? screenModeFor(agent) : 'idle';
      if (mode === 'off') {
        ctx.fillStyle = 'rgba(2,4,10,0.78)';
        ctx.fillRect(x, y, sw, sh);
      } else if (mode === 'active' || mode === 'thinking') {
        ctx.save();
        ctx.beginPath();
        ctx.rect(x, y, sw, sh);
        ctx.clip();
        ctx.globalCompositeOperation = 'lighter';
        const speed = mode === 'active' ? 14 : 3;
        const accent = name.includes('audio') ? '192,132,252' : name.includes('radar') ? '74,222,128' : name.includes('treasury') ? '163,230,53' : '120,170,255';
        for (let i = 0; i < 5; i += 1) {
          const yy = y + (((clock * speed + i * sh * 0.23) % (sh + 4)) - 2);
          ctx.fillStyle = `rgba(${accent},${mode === 'active' ? 0.35 : 0.18})`;
          ctx.fillRect(x + 1 + ((i * 7) % 5), yy, sw * (0.35 + ((i * 37) % 50) / 100), 1.2);
        }
        ctx.fillStyle = `rgba(${accent},${0.08 + 0.05 * Math.sin(clock * 3)})`;
        ctx.fillRect(x, y, sw, sh);
        if (name === 'publish_radar') {
          ctx.strokeStyle = 'rgba(74,222,128,0.8)';
          ctx.beginPath();
          const cx = x + sw / 2;
          const cy = y + sh / 2;
          const a = clock * (mode === 'active' ? 3 : 1);
          ctx.moveTo(cx, cy);
          ctx.lineTo(cx + Math.cos(a) * sw * 0.45, cy + Math.sin(a) * sh * 0.45);
          ctx.stroke();
        }
        ctx.restore();
      } else if (mode === 'error') {
        ctx.fillStyle = `rgba(239,68,68,${0.25 + 0.2 * Math.sin(clock * 6)})`;
        ctx.fillRect(x, y, sw, sh);
      }
    }
    const racks = this.m.displays?.server_racks?.rects || [];
    const working = agents.filter((a) => stateOf(a) === 'WORKING' || stateOf(a) === 'THINKING').length;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    racks.forEach((/** @type {number[]} */ r, ri) => {
      for (let i = 0; i < 18; i += 1) {
        const on = Math.sin(clock * (1.5 + working * 1.2) + i * 1.7 + ri) > 0.55;
        if (!on) continue;
        ctx.fillStyle = i % 5 === 0 ? 'rgba(251,191,36,0.9)' : 'rgba(74,222,128,0.9)';
        ctx.fillRect(r[0] + 3 + ((i * 7) % Math.max(4, r[2] - 6)), r[1] + 4 + ((i * 11) % Math.max(4, r[3] - 8)), 1.5, 1.5);
      }
    });
    ctx.restore();
  }

  /** @param {any} agent */
  zoneOf(agent) {
    const seat = this.m.seats?.[agent?.desk_id];
    return seat ? seat.zone : null;
  }

  /**
   * The render bay's wall display shows what the video editor is really doing, never a number
   * nobody measured.
   * @param {CanvasRenderingContext2D} ctx
   */
  drawRenderDisplay(ctx, x, y, dw, dh, agent, clock) {
    const state = agent ? stateOf(agent) : 'IDLE';
    const working = state === 'WORKING';
    ctx.fillStyle = working ? '#071a2c' : '#050a12';
    ctx.fillRect(x, y, dw, dh);
    ctx.fillStyle = '#9fb4cc';
    ctx.font = '600 6px "Segoe UI", system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('RENDER BAY', x + dw / 2, y + 12);
    ctx.font = '700 9px "Segoe UI", system-ui, sans-serif';
    ctx.fillStyle = working ? '#e6f1ff' : state === 'ERROR' || state === 'BLOCKED' ? '#fca5a5' : '#56708c';
    ctx.fillText(working ? 'WORKING' : state, x + dw / 2, y + 27);
    if (working) {
      ctx.strokeStyle = '#38bdf8';
      ctx.strokeRect(x + 8, y + 36, dw - 16, 6);
      ctx.save();
      ctx.beginPath();
      ctx.rect(x + 9, y + 37, dw - 18, 4);
      ctx.clip();
      ctx.fillStyle = '#38bdf8';
      const band = (dw - 18) * 0.35;
      const pos = ((clock * 30) % (dw - 18 + band)) - band;
      ctx.fillRect(x + 9 + pos, y + 37, band, 4);
      ctx.restore();
      const detail = String(agent.detail || agent.task_type || '').slice(0, 22);
      if (detail) {
        ctx.font = '500 5px "Segoe UI", system-ui, sans-serif';
        ctx.fillStyle = '#9fb4cc';
        ctx.fillText(detail, x + dw / 2, y + 52);
      }
    }
    ctx.textAlign = 'left';
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} state */
  drawLift(ctx, state) {
    const lift = this.m.lift;
    if (!lift || !state.lift) return;
    const floorRow = state.lift.y;
    const x = lift.shaft.x + 3;
    const cw = lift.shaft.w - 6;
    const ch = 62;
    const top = floorRow - ch;
    ctx.fillStyle = 'rgba(255,214,150,0.18)';
    ctx.fillRect(x, top, cw, ch);
    ctx.strokeStyle = 'rgba(40,34,30,0.9)';
    ctx.lineWidth = 2;
    ctx.strokeRect(x, top, cw, ch);
    ctx.fillStyle = 'rgba(255,236,200,0.8)';
    ctx.fillRect(x + cw / 2 - 8, top + 3, 16, 2);
    ctx.fillStyle = '#2b2522';
    ctx.fillRect(x, floorRow - 3, cw, 3);
    const trip = state.trip;
    if (trip && trip.phase === 'travel') this.drawWalker(ctx, 'ped03', x + cw / 2, floorRow - 2, 1, 0, true);
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} state */
  drawAgents(ctx, state) {
    this.hits = [];
    const atlas = this.assets.characters;
    if (!atlas) return;
    const frame = atlas.frame;
    for (const agent of state.agents) {
      const seat = this.m.seats?.[agent.desk_id];
      if (!seat) continue;
      const key = spriteFor(agent, atlas);
      const entry = key ? atlas.characters[key] : null;
      const img = key ? this.assets.sheet(`char:${key}`) : null;
      if (!entry || !img) continue;
      const id = agent.id || agent.agent_id;
      const talking = state.bubbles.some((/** @type {any} */ b) => b.agentId === id);
      const f = this.world.agents.frame(agent, entry, seat.facing, talking);
      if (!f) continue;
      const s = SPRITE_SCALE;
      const cols = entry.columns;
      const sw = frame.w * frame.scale;
      const sh = frame.h * frame.scale;
      const dx = seat.x - frame.pivot[0] * s;
      const dy = seat.y - SEATED_LIFT - frame.pivot[1] * s;
      ctx.drawImage(img, (f.index % cols) * sw, Math.floor(f.index / cols) * sh, sw, sh, dx, dy, frame.w * s, frame.h * s);
      this.hits.push({ agent, x0: seat.x - 16, y0: seat.y - SEATED_LIFT - 44, x1: seat.x + 16, y1: seat.y + 2 });
    }
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} state */
  drawTokens(ctx, state) {
    const clock = this.world.ambient.clock;
    const inTransit = state.trip ? state.trip.tokenId : null;
    for (const token of state.tokens) {
      if (token.id === inTransit) continue;
      const bob = Math.sin(clock * 2 + token.x) * 1.5;
      const x = token.x + 18;
      const y = token.y - 30 + bob;
      ctx.fillStyle = 'rgba(94,234,212,0.18)';
      ctx.beginPath();
      ctx.arc(x, y + 4, 9, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#fef3c7';
      ctx.fillRect(x - 4, y, 8, 9);
      ctx.fillStyle = '#f59e0b';
      ctx.fillRect(x - 4, y, 8, 2);
      ctx.font = '600 5px "Segoe UI", system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.fillStyle = 'rgba(230,240,255,0.9)';
      ctx.fillText(String(token.stage || '').replace(/_/g, ' '), x, y - 3);
      ctx.textAlign = 'left';
    }
    const trip = state.trip;
    if (trip && trip.phase !== 'travel') {
      const onOrigin = trip.phase === 'summon' || trip.phase === 'board';
      const line = onOrigin ? trip.boardLine : trip.exitLine;
      const target = onOrigin ? trip.doorX : trip.exitX;
      const facing = Math.abs(target - trip.x) < 0.5 ? 0 : Math.sign(target - trip.x);
      this.drawWalker(ctx, 'ped03', trip.x, line, facing || 1, clock * 9, facing !== 0);
    }
  }

  /**
   * @param {CanvasRenderingContext2D} ctx
   * @param {string} sheetKey
   */
  drawWalker(ctx, sheetKey, x, row, dir, phase, walking) {
    const atlas = this.assets.pedestrians;
    const entry = atlas?.characters?.[sheetKey];
    const img = this.assets.sheet(`ped:${sheetKey}`);
    if (!entry || !img) return;
    const frames = entry.animations[walking ? 'walk_right' : 'stand_idle'] || [];
    if (!frames.length) return;
    const index = frames[Math.floor(Math.abs(phase)) % frames.length];
    const fr = atlas.frame;
    const s = PEDESTRIAN_SCALE;
    const sw = fr.w * fr.scale;
    const sh = fr.h * fr.scale;
    ctx.save();
    ctx.translate(x, row);
    if (dir < 0) ctx.scale(-1, 1);
    ctx.drawImage(img, (index % entry.columns) * sw, Math.floor(index / entry.columns) * sh, sw, sh, -fr.pivot[0] * s, -fr.pivot[1] * s, fr.w * s, fr.h * s);
    ctx.restore();
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} fx */
  drawPedestrians(ctx, fx) {
    const atlas = this.assets.pedestrians;
    if (!atlas) return;
    for (const p of this.world.pedestrians.paintOrder()) {
      ctx.fillStyle = 'rgba(0,0,0,0.22)';
      ctx.beginPath();
      ctx.ellipse(p.x, p.row, 7, 2, 0, 0, Math.PI * 2);
      ctx.fill();
      const walking = p.react <= 0 && (p.state === 'walk' || p.state === 'cross');
      this.drawWalker(ctx, p.sheet, p.x, p.row, p.dir, p.frame, walking);
      if (p.umbrella && fx.rain > 0) {
        const hx = p.x + p.dir * 1;
        const hy = p.row - 40;
        ctx.fillStyle = p.umbrella;
        ctx.beginPath();
        ctx.arc(hx, hy + 4, 11, Math.PI, 0);
        ctx.fill();
        ctx.strokeStyle = '#1b1b1f';
        ctx.lineWidth = 0.8;
        ctx.beginPath();
        ctx.moveTo(hx, hy + 4);
        ctx.lineTo(hx, hy + 18);
        ctx.stroke();
      }
    }
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} time @param {any} fx */
  drawVehicles(ctx, time, fx) {
    const cat = this.assets.vehicles;
    if (!cat) return;
    const scale = cat.scale;
    const lamps = Math.min(1, Math.max(0, (1 - time.daylight) * 1.4 + fx.rain * 0.6 + fx.fog * 0.8));
    const clock = this.world.ambient.clock;
    for (const v of this.world.traffic.paintOrder()) {
      const entry = cat.vehicles[v.kind];
      const img = this.assets.sheet(`veh:${v.kind}`);
      if (!entry || !img) continue;
      const dirName = v.dir > 0 ? 'right' : 'left';
      const d = entry.directions[dirName];
      const cellW = entry.cell.w * scale;
      const cellH = entry.cell.h * scale;
      const sy = d.row * cellH;
      const dx = v.x - d.pivot[0];
      const dy = v.row - d.pivot[1];
      ctx.fillStyle = 'rgba(0,0,0,0.3)';
      ctx.beginPath();
      ctx.ellipse(v.x, v.row, v.length * 0.48, 4, 0, 0, Math.PI * 2);
      ctx.fill();
      const col = Math.floor(v.wheel) % 3;
      ctx.drawImage(img, col * cellW, sy, d.w * scale, d.h * scale, dx, dy, d.w, d.h);
      ctx.save();
      ctx.globalCompositeOperation = 'lighter';
      const lightsCol = entry.columns.indexOf('lights');
      if (lamps > 0.02 && lightsCol >= 0) {
        ctx.globalAlpha = lamps;
        ctx.drawImage(img, lightsCol * cellW, sy, d.w * scale, d.h * scale, dx, dy, d.w, d.h);
        this.drawLampFlares(ctx, d.lamps, dx, dy, lamps);
      }
      if (v.siren) {
        const phase = Math.floor(clock * 5) % 2;
        const sirenCol = entry.columns.indexOf(`siren${phase}`);
        if (sirenCol >= 0) {
          ctx.globalAlpha = 1;
          ctx.drawImage(img, sirenCol * cellW, sy, d.w * scale, d.h * scale, dx, dy, d.w, d.h);
          const glow = ctx.createRadialGradient(v.x, dy + 6, 1, v.x, dy + 6, 46);
          glow.addColorStop(0, phase ? 'rgba(80,120,255,0.45)' : 'rgba(255,60,60,0.45)');
          glow.addColorStop(1, 'rgba(0,0,0,0)');
          ctx.fillStyle = glow;
          ctx.fillRect(v.x - 46, dy - 40, 92, 92);
        }
      }
      ctx.restore();
    }
  }

  /**
   * Bloom on the lamps the vehicle render found visible: a round glow with a faint horizontal
   * streak for headlights, a smaller red glow for tail lamps.
   * @param {CanvasRenderingContext2D} ctx
   * @param {{head?: number[][], tail?: number[][]} | undefined} anchors frame px
   * @param {number} dx @param {number} dy @param {number} strength
   */
  drawLampFlares(ctx, anchors, dx, dy, strength) {
    if (!anchors) return;
    const head = flareSprite('255,244,214');
    const tail = flareSprite('255,50,40');
    if (head) {
      for (const [ax, ay] of anchors.head || []) {
        ctx.globalAlpha = 0.9 * strength;
        ctx.drawImage(head, dx + ax - 11, dy + ay - 11, 22, 22);
        ctx.globalAlpha = 0.35 * strength;
        ctx.drawImage(head, dx + ax - 28, dy + ay - 3, 56, 6);
      }
    }
    if (tail) {
      for (const [ax, ay] of anchors.tail || []) {
        ctx.globalAlpha = 0.8 * strength;
        ctx.drawImage(tail, dx + ax - 7, dy + ay - 7, 14, 14);
      }
    }
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} time */
  drawShelter(ctx, time) {
    const clock = this.m.street.shelter_clock?.rect;
    if (clock) {
      const [x, y, cw, ch] = clock;
      ctx.fillStyle = '#071c22';
      ctx.fillRect(x, y, cw, ch);
      ctx.fillStyle = '#9fd8d0';
      ctx.font = '600 5.5px "Segoe UI", system-ui, sans-serif';
      ctx.fillText('BUCHAREST', x + 4, y + 8);
      ctx.fillStyle = '#5eead4';
      ctx.font = '600 17px "Cascadia Mono", Consolas, monospace';
      ctx.shadowColor = 'rgba(94,234,212,0.8)';
      ctx.shadowBlur = 6;
      ctx.fillText(time.text, x + 5, y + ch - 5);
      ctx.shadowBlur = 0;
    }
    const adRect = this.m.street.shelter_ad?.rect;
    if (adRect) {
      const ad = SHELTER_ADS[this.world.ambient.adIndex];
      const [x, y, aw, ah] = adRect;
      const g = ctx.createLinearGradient(0, y, 0, y + ah);
      g.addColorStop(0, ad.top);
      g.addColorStop(1, ad.bottom);
      ctx.fillStyle = g;
      ctx.fillRect(x, y, aw, ah);
      if (ad.mark) drawMark(ctx, x + aw / 2 - 9, y + 12, 18, ad.accent);
      ctx.textAlign = 'center';
      ctx.fillStyle = '#f8fafc';
      ctx.font = '700 7px "Segoe UI", system-ui, sans-serif';
      ctx.fillText(ad.title, x + aw / 2, y + (ad.mark ? 44 : 30));
      ctx.font = '600 5.5px "Segoe UI", system-ui, sans-serif';
      ad.lines.forEach((line, i) => {
        ctx.fillStyle = i === 0 ? '#e2e8f0' : ad.accent;
        ctx.fillText(line, x + aw / 2, y + (ad.mark ? 56 : 42) + i * 9);
      });
      ctx.textAlign = 'left';
      ctx.fillStyle = 'rgba(255,255,255,0.06)';
      ctx.fillRect(x, y, aw * 0.4, ah);
    }
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} time */
  drawNightGrade(ctx, time) {
    const deep = Math.max(0, Math.min(1, (-time.elevation - 8) / 10));
    if (deep <= 0) return;
    ctx.save();
    ctx.globalCompositeOperation = 'multiply';
    ctx.fillStyle = `rgba(70,84,130,${0.45 * deep})`;
    ctx.beginPath();
    ctx.rect(0, 0, this.world.worldW, this.world.worldH);
    ctx.rect(1352, 0, -937, 676);
    ctx.fill('evenodd');
    ctx.restore();
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} state */
  drawBubbles(ctx, state) {
    const now = Date.now();
    for (const bubble of state.bubbles) {
      const agent = state.agents.find((/** @type {any} */ a) => (a.id || a.agent_id) === bubble.agentId);
      const seat = agent ? this.m.seats?.[agent.desk_id] : null;
      const x = seat ? seat.x : bubble.x;
      const y = seat ? seat.y - 42 : bubble.y;
      const frame = bubbleFrame(bubble.pages || [], (now - bubble.createdAt) / 1000);
      if (!frame.lines.length) continue;
      ctx.font = '600 6px "Segoe UI", system-ui, sans-serif';
      const widest = Math.max(40, ...frame.lines.map((l) => ctx.measureText(l).width));
      const bw = widest + 12;
      const bh = frame.lines.length * 8 + 9;
      const bx = Math.min(this.world.worldW - bw - 4, Math.max(4, x - bw / 2));
      const by = y - bh;
      ctx.fillStyle = 'rgba(12,18,34,0.92)';
      ctx.strokeStyle = 'rgba(148,163,184,0.6)';
      ctx.lineWidth = 0.8;
      roundRect(ctx, bx, by, bw, bh, 4);
      ctx.fill();
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(x - 3, by + bh);
      ctx.lineTo(x, by + bh + 4);
      ctx.lineTo(x + 3, by + bh);
      ctx.fill();
      ctx.fillStyle = '#e2e8f0';
      frame.lines.forEach((line, i) => ctx.fillText(line, bx + 6, by + 10 + i * 8));
      if (frame.pageCount > 1) {
        ctx.fillStyle = '#64748b';
        ctx.font = '600 4.5px "Segoe UI", system-ui, sans-serif';
        ctx.fillText(`${frame.pageIndex + 1}/${frame.pageCount}`, bx + bw - 14, by + bh - 3);
      }
    }
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} state */
  drawSelection(ctx, state) {
    for (const id of new Set([state.selectedId, state.hoverId])) {
      if (!id) continue;
      const agent = state.agents.find((/** @type {any} */ a) => (a.id || a.agent_id) === id);
      const seat = agent ? this.m.seats?.[agent.desk_id] : null;
      if (!seat) continue;
      const name = String(agent.display_name || agent.role_name || 'Agent');
      const status = stateOf(agent);
      const text = `${name} · ${status}`;
      ctx.font = '600 6.5px "Segoe UI", system-ui, sans-serif';
      const tw = ctx.measureText(text).width + 12;
      const x = seat.x - tw / 2;
      const y = seat.y + 4;
      ctx.fillStyle = id === state.selectedId ? 'rgba(20,184,166,0.92)' : 'rgba(12,18,34,0.88)';
      roundRect(ctx, x, y, tw, 11, 5);
      ctx.fill();
      ctx.fillStyle = '#f8fafc';
      ctx.fillText(text, x + 6, y + 8);
    }
  }
}

/** @param {CanvasRenderingContext2D} ctx */
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

/** @param {CanvasRenderingContext2D} ctx */
function letterSpaced(ctx, text, rightX, y, spacing) {
  let width = 0;
  for (const ch of text) width += ctx.measureText(ch).width + spacing;
  let x = rightX - width;
  ctx.textAlign = 'left';
  for (const ch of text) {
    ctx.fillText(ch, x, y);
    x += ctx.measureText(ch).width + spacing;
  }
}

/** The AMN-AI 'A' mark. @param {CanvasRenderingContext2D} ctx */
export function drawMark(ctx, x, y, h, colour) {
  const w = h * 1.05;
  const t = h * 0.22;
  ctx.fillStyle = colour;
  ctx.beginPath();
  ctx.moveTo(x, y + h);
  ctx.lineTo(x + t, y + h);
  ctx.lineTo(x + w / 2 + t * 0.2, y + t * 0.9);
  ctx.lineTo(x + w / 2 - t * 0.35, y);
  ctx.closePath();
  ctx.fill();
  ctx.beginPath();
  ctx.moveTo(x + w - t, y + h);
  ctx.lineTo(x + w, y + h);
  ctx.lineTo(x + w / 2 + t * 0.35, y);
  ctx.lineTo(x + w / 2 - t * 0.2, y + t * 0.9);
  ctx.closePath();
  ctx.fill();
  ctx.fillRect(x + w * 0.6, y + h * 0.84, w * 0.12, h * 0.16);
}
