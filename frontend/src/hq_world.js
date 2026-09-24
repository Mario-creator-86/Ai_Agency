import { TimeOfDayManager, timeOfDay } from './hq_time.js';
import { NO_WEATHER, WeatherManager } from './hq_weather.js';
import { RandomEventManager, streetRule } from './hq_events.js';
import { TrafficManager, EMERGENCY } from './hq_traffic.js';
import { PedestrianManager } from './hq_pedestrians.js';
import { AgentVisualStateManager, spriteFor, stateOf } from './hq_agents.js';
import { SkyRenderer } from './hq_sky.js';
import { bubbleFrame } from './speech_bubble.js';
import { scenePalette, withAlpha } from './hq_palette.js';
import { stageLabel, runtimeLabel } from './ledger.js';
import {
  PANES, EXTRA_SCREENS, DESK_MONITOR, deskPane, WALL, NOTES, FaceCache, paneMode, roomOccupancy, roomShade, screenLight,
  renderBayFace, treasuryFace, runSignFace, factCheckFace, writersFace, publishFace, tokensFace,
  drawPane, paintTreasury, paintRunSign, paintFactCheck, paintNote, paintWriters, paintPublish, paintInfra, paintRenderBay,
} from './hq_screens.js';
import { surfaceRects, GlintTracker, lastTaskLine, unionRect } from './hq_readouts.js';
import { Arrivals, arrivalAccent } from './hq_arrivals.js';
import { runStageWord } from './hud_charts.js';

/**
 * WorldSimulationManager owns every manager of the living headquarters and advances them in one
 * place; HQRenderer paints the plates and the live actors in the order the Blender build defined.
 *
 * Randomness comes from one seeded source (mulberry32), so a seed reproduces a street exactly.
 * What the studio is doing comes only from backend state handed in by the engine. How full the
 * street is, and what may happen on it, is hq_events.js `streetRule`: the real hour, day and
 * weather in Bucharest, and whether the page still has the studio's data.
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
  // the desks and their monitors stand in building_front, in front of the employees; the shell
  // (floors, frame, façade) is its own group so a room's light can fall on the desks but not on it
  ['building_front', ['building_front']],
  ['building_shell', ['building_shell']],
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

/**
 * What outdoor light multiplies a street sprite by: white by day, a cool dim blue at dusk and at
 * night, a little greyer under cloud. Sprites are rendered under neutral light; without this a
 * white bus glows against a dusk street.
 * @param {{daylight:number}} time
 * @param {{cloudiness?:number}} fx
 * @returns {[number, number, number]}
 */
export function streetLight(time, fx) {
  // dusk is closer to night than to day on the street: the picture's cars show only their lamps
  const d = Math.max(0, Math.min(1, time.daylight)) ** 1.6;
  const grey = 1 - 0.18 * Math.max(0, Math.min(1, fx.cloudiness || 0));
  const [r, g, b] = [0.4, 0.44, 0.62].map((n) => Math.round((n + (1 - n) * d) * grey * 100) / 100);
  return [r, g, b];
}

/**
 * How much of the day plates to show over the night plates. Daylight starts rising while the sun
 * is still below the horizon (the sky needs that); sunlit plates must not, or dusk looks half day.
 * @param {number} daylight 0 night .. 1 full day
 */
export function plateDayMix(daylight) {
  return Math.max(0, Math.min(1, daylight)) ** 2.2;
}

/** People are rendered at true size (build_people.py), sitting on the chairs the plates model. */
const SPRITE_SCALE = 1;
const SEATED_LIFT = 0;
const PEDESTRIAN_SCALE = 1;

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

/**
 * What the weather draws in a world: nothing while a day is replayed (W15), else the live weather.
 * @param {{replayAt?: number|null, weather: {effects: any}}} world
 */
function effectsOf(world) {
  return world.replayAt != null ? NO_WEATHER : world.weather.effects;
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
    /** The replayed moment the world is lit by, or null for the real hour (setReplayMoment). @type {number|null} */
    this.replayAt = null;
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
    this.sky = new SkyRenderer({ worldWidth: this.worldW, worldHeight: this.worldH, horizonRow: HORIZON_ROW, rng: this.rng, assets });
    /** @type {any[]} */
    this.agentList = [];
    /** What streetRule said on the last step: for the readouts and for QA. @type {any} */
    this.rule = null;
    this.events.on((kind, event) => this.onEvent(kind, event));
    // A street is never empty on arrival: the simulation is warmed up for a minute of city time.
    // It waits for the first weather reading, so on a rainy afternoon the minute is a rainy one
    // (fewer walkers, umbrellas up) rather than a dry one that the rain then has to thin out.
    // The engine is built while the title screen is up, so this happens before anyone looks.
    this.warm = false;
    this._unwarmed = 0;
    const warmUp = () => this.warmUp();
    this.weather.first(this.time.now().getTime()).then(warmUp, warmUp);
  }

  /**
   * «Reluarea zilei» (W15): while a day is replayed, the world is lit by the replayed moment's own
   * sun over Bucharest (hq_time.js, at the record's instant), not today's; the weather of that
   * night is not known to the page, so none is drawn. null gives the world back to the real
   * hour and the real weather at once. Re-read only when the moment moves a second or more.
   * @param {number|null} ms
   */
  setReplayMoment(ms) {
    if (ms === null || !Number.isFinite(ms)) {
      if (this.replayAt === null) return;
      this.replayAt = null;
      this.time.state = timeOfDay(this.time.now(), this.time.location);
      return;
    }
    if (this.replayAt !== null && Math.abs(ms - this.replayAt) < 1000) return;
    this.replayAt = ms;
    this.time.state = timeOfDay(new Date(ms), this.time.location);
  }

  /** What the weather draws: nothing while a day is replayed (its weather is not known). */
  get effects() {
    return effectsOf(this);
  }

  /** The minute of city time the street is warmed up with, once. */
  warmUp() {
    if (this.warm) return;
    this.warm = true;
    for (let i = 0; i < 240; i += 1) this.step(0.25, 0);
  }

  /** @param {string} kind @param {any} event */
  onEvent(kind, event) {
    if (kind !== 'start') return;
    const id = event.def.eventId;
    if (id === 'bus_arrives' || id in EMERGENCY) this.traffic.spawnForEvent(id);
    else if (id === 'pedestrians_cross') this.pedestrians.startCrossing();
    else if (id === 'jogger_group') this.pedestrians.startJoggers(3);
    // Passers-by may look up at the street's own spectacle. The employees may not: what an
    // employee does is the backend's state and nothing else, and an invented event outside is
    // not a reason for anyone inside to be seen talking.
    if (event.def.reactionRadius >= 1000) this.pedestrians.reactAll(5);
  }

  /**
   * @param {number} dt @param {number} nowMs
   * @param {boolean} [still] the visitor asked for reduced motion: the clock, the sun and the
   *   weather are still read (they are information), but nothing is moved. The street, the sky's
   *   drift and the employees' loops hold the frame they are on; what each employee is doing
   *   stays readable from their pose, their screen and their bubble.
   * @param {boolean} [live] the page still has the studio's data (hq_events.js `streetMoves`).
   *   When it has lost it the picture holds exactly as it does under reduced motion, so nothing
   *   outside goes on living while the corner of the render says it is reconnecting.
   */
  step(dt, nowMs, still = false, live = true) {
    // A weather service that never answers does not keep the street empty: after three seconds
    // of frames the street is warmed up with what is known.
    if (!this.warm && (this._unwarmed += dt) > 3) this.warmUp();
    const replaying = this.replayAt != null;
    const time = replaying ? this.time.state : this.time.update(dt);
    if (nowMs) this.weather.update(nowMs);
    const fx = effectsOf(this);
    // No backend state says there is an emergency, so `emergency` is not passed and no siren
    // drives. Wire it here the day the backend has one.
    const rule = streetRule({ hour: time.hour, day: time.day, ymd: time.ymd, effects: fx, live, still });
    this.rule = rule;
    const move = rule.moving ? dt : 0;
    this.events.update(move, { weather: replaying ? 'unknown' : this.weather.state.condition, phase: time.phase, emergency: rule.sirens, buses: rule.buses });
    this.traffic.crosswalkBusy = this.pedestrians.crosswalkBusy;
    this.traffic.waitingAtShelter = this.pedestrians.waitingAtShelter;
    this.traffic.update(move, { hour: time.hour, day: rule.day, effects: fx });
    this.pedestrians.update(move, { hour: time.hour, day: rule.day, effects: fx, busAtShelter: this.traffic.busAtShelter });
    this.agents.update(move);
    this.ambient.update(move);
    this.sky.update(move, time, fx);
    if (this.time.state.daylight > 0.001) this.assets.loadVariant('day');
  }
}

export class HQRenderer {
  /** @param {WorldSimulationManager} world */
  constructor(world) {
    this.world = world;
    this.assets = world.assets;
    this.m = world.assets.manifest;
    /** @type {Array<{agent:any, x0:number, y0:number, x1:number, y1:number, surface?: string, room?: string|null, desk?: boolean}>} */
    this.hits = [];
    /** @type {Map<string, {canvas: HTMLCanvasElement, x:number, y:number, w:number, h:number}>} */
    this.caches = new Map();
    this.cacheKey = '';
    /** The light the caches were composed for, and a change of light being composed a group a frame (W15). */
    this._cacheLight = -1;
    /** @type {{key: string, light: number, queue: Array<[string, string[]]>, map: Map<string, any>}|null} */
    this._staging = null;
    /** The previous light's canvases, reused by the next change of light. @type {Map<string, any>|null} */
    this._spare = null;
    /** A light composed ahead of its first frame (prepareLight). @type {{key: string, light: number, map: Map<string, any>}|null} */
    this._prepared = null;
    this._wantedScale = 0;
    this._scaleSince = 0;
    /** @type {Map<string, {tag: string, canvas: HTMLCanvasElement}>} */
    this.tints = new Map();
    /** The screens' faces, each drawn once per value and scale (hq_screens.js). */
    this.faces = new FaceCache();
    /** @type {any} */
    this.facts = {};
    /** The screens lit on the last frame. @type {Array<{r: number[], rgb: string, strength: number, zone: string|null}>} */
    this.lit = [];
    /** Each seated room's occupancy and shade on the last frame, for QA. @type {Record<string, any>} */
    this.roomStates = {};
    /** A face whose value changed while the page watched glints once (hq_readouts.js). */
    this.glints = new GlintTracker();
    /** Whether the visitor asked for less motion, as of the frame being drawn. */
    this.reduced = false;
    /** Glints drawn so far, for QA. */
    this.glintCount = 0;
    /** What a live event brings up for a few seconds: a tag, a room at full light (W12). */
    this.arrivals = new Arrivals();
  }

  /**
   * A street sprite sheet multiplied by the outdoor light, cached until that light changes.
   * @param {string} key
   * @param {HTMLImageElement | HTMLCanvasElement} img
   * @param {[number, number, number]} light
   */
  litSheet(key, img, light) {
    if (typeof document === 'undefined' || light.every((c) => c >= 0.999)) return img;
    const tag = light.join(',');
    const hit = this.tints.get(key);
    if (hit && hit.tag === tag) return hit.canvas;
    const canvas = hit ? hit.canvas : document.createElement('canvas');
    canvas.width = img.width;
    canvas.height = img.height;
    const c = canvas.getContext('2d');
    if (!c) return img;
    c.drawImage(img, 0, 0);
    c.globalCompositeOperation = 'multiply';
    c.fillStyle = `rgb(${light.map((v) => Math.round(v * 255)).join(',')})`;
    c.fillRect(0, 0, canvas.width, canvas.height);
    c.globalCompositeOperation = 'destination-in';
    c.drawImage(img, 0, 0);
    this.tints.set(key, { tag, canvas });
    return canvas;
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
   *
   * A small change of light (the real sun's step, W15) is composed one group per frame into a
   * second set of canvases, which replaces the first whole once every group is done: the frames
   * between keep the previous light, never a mix. A jump of light (a replay's own hour) is composed
   * ahead of its first frame (prepareLight) when entering a replay, and at once when leaving it;
   * a change of scale is composed at once.
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
    if (key === this.cacheKey || !settled) {
      this._staging = null;
      return this.caches.size > 0;
    }
    // a light composed ahead of time (prepareLight) is taken whole
    if (this._prepared && this._prepared.key === key) {
      this._spare = this.caches;
      this.caches = this._prepared.map;
      this.cacheKey = key;
      this._cacheLight = this._prepared.light;
      this._prepared = null;
      this._staging = null;
      return true;
    }
    // one prepared for another scale or light is not kept
    this._prepared = null;
    // Only the sun's own small steps are composed a group a frame: the sky is drawn every frame
    // with the new light, and a jump (back to live from a replayed night) kept on the old plates
    // for seven frames read as a night building under a noon sky. A jump is composed at once.
    const lightOnly = this.caches.size > 0 && this.cacheKey === `${bucket}|${this._cacheLight}|${loaded}` && Math.abs(light - this._cacheLight) <= 2;
    if (lightOnly) {
      if (!this._staging || this._staging.key !== key) this._staging = { key, light, queue: PLATE_GROUPS.slice(), map: new Map() };
      const staging = this._staging;
      const next = staging.queue.shift();
      if (next) this.composeGroup(staging.map, next[0], next[1], bucket, time, this._spare);
      if (!staging.queue.length) {
        this._spare = this.caches;
        this.caches = staging.map;
        this.cacheKey = key;
        this._cacheLight = light;
        this._staging = null;
      }
      return true;
    }
    this._staging = null;
    this.cacheKey = key;
    this._cacheLight = light;
    for (const [group, layers] of PLATE_GROUPS) this.composeGroup(this.caches, group, layers, bucket, time, null);
    return true;
  }

  /**
   * Compose every plate group now, for this scale and light, whatever was composed before: the
   * engine's prewarm, under the title, does it for both lights (W15).
   * @param {number} displayScale @param {any} time
   */
  composeNow(displayScale, time) {
    this._staging = null;
    this.cacheKey = '';
    this._cacheLight = -1;
    this._scaleSince = -Infinity;
    return this.ensureCaches(displayScale, time);
  }

  /**
   * Compose the plates for a light ahead of its first frame (W15): a group at a time, a pause
   * between, into a set of canvases that the frame lit by that light then takes whole. Entering a
   * replayed night from a live noon composed them in the frames of the switch: one 64-158 ms frame.
   * @param {number} displayScale @param {any} time @param {number} [gapMs]
   */
  async prepareLight(displayScale, time, gapMs = 40) {
    if (typeof document === 'undefined') return false;
    const bucket = Math.min(2.5, Math.max(0.2, Math.round(displayScale * 1000) / 1000));
    const light = Math.round(time.daylight * 40);
    const loaded = `${Object.keys(this.assets.layers.night).length}/${Object.keys(this.assets.layers.day).length}`;
    const key = `${bucket}|${light}|${loaded}`;
    if (key === this.cacheKey) return true;
    /** @type {Map<string, any>} */
    const map = new Map();
    for (const [group, layers] of PLATE_GROUPS) {
      await new Promise((ok) => setTimeout(ok, gapMs));
      await new Promise((ok) => requestAnimationFrame(() => ok(undefined)));
      this.composeGroup(map, group, layers, bucket, time, null);
    }
    this._prepared = { key, light, map };
    return true;
  }

  /**
   * Compose one plate group into `target`, reusing its canvas (or a spare one of the same size).
   * @param {Map<string, any>} target @param {string} group @param {string[]} layers
   * @param {number} bucket @param {any} time @param {Map<string, any>|null|undefined} spare
   */
  composeGroup(target, group, layers, bucket, time, spare) {
    const rect = this.groupRect(layers);
    if (!rect) return;
    const cw = Math.max(1, Math.round(rect.w * bucket));
    const ch = Math.max(1, Math.round(rect.h * bucket));
    const fits = (/** @type {any} */ e) => e && e.canvas.width === cw && e.canvas.height === ch;
    let entry = target.get(group);
    if (!fits(entry)) entry = spare && fits(spare.get(group)) ? spare.get(group) : null;
    if (!entry) {
      const canvas = document.createElement('canvas');
      canvas.width = cw;
      canvas.height = ch;
      entry = { canvas, ...rect };
    }
    if (spare && spare.get(group) === entry) spare.delete(group);
    target.set(group, entry);
    Object.assign(entry, rect);
    const c = entry.canvas.getContext('2d');
    if (!c) return;
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
   * @param {{agents:any[], bubbles:any[], tokens:any[], lift:any, trip:any, selectedId:any, hoverId:any, liftStops:any, scale?:number, skyTop?:number, surfaceId?: string|null, surfaceVia?: string, reduced?: boolean, replay?: boolean}} state
   */
  draw(ctx, state) {
    const w = this.world;
    const time = w.time.state;
    const fx = effectsOf(w);
    w.agentList = state.agents;
    this.reduced = Boolean(state.reduced);
    this.useCaches = this.ensureCaches(state.scale || 1, time);
    // the real sun and the real cloud cover: an overcast noon is grey, a clear night is clear
    const skyTop = Math.min(0, state.skyTop || 0);
    w.sky.drawSky(ctx, time, fx, skyTop);
    w.sky.drawSkyEvents(ctx, w.events, time);
    this.plate(ctx, 'back', time);
    this.drawBillboard(ctx);
    this.drawRoadLights(ctx, time, fx);
    this.plate(ctx, 'building_back', time);
    this.drawScreens(ctx, state.agents, state.scale || 1);
    this.drawLift(ctx, state);
    this.drawAgents(ctx, state);
    this.plate(ctx, 'building_front', time);
    this.drawDeskMonitors(ctx, state.agents);
    this.drawRoomLights(ctx, state.agents, time);
    this.drawScreenLight(ctx, time);
    this.drawRoomFlares(ctx, time);
    this.plate(ctx, 'building_shell', time);
    this.drawFacade(ctx, state.scale || 1);
    // In the replay the rooms' chips are words, drawn after the replay's grade (below)
    this.drawRoomRims(ctx, state, state.replay ? 'rim' : 'all');
    w.sky.drawSkyEvents(ctx, w.events, time, 'near');
    this.drawTokens(ctx, state);
    this.plate(ctx, 'street_props', time);
    this.drawShelter(ctx, time, Boolean(state.replay));
    this.drawPedestrians(ctx, fx, time);
    this.plate(ctx, 'street_kerb', time);
    this.drawVehicles(ctx, time, fx);
    this.plate(ctx, 'street_front', time);
    w.sky.drawWeather(ctx, time, fx, skyTop);
    this.drawNightGrade(ctx, time, skyTop);
    // «Reluarea zilei» (W13): the world played back from the record wears a grade no one can take
    // for live; the words drawn over it (chips, captions, tags, marks) are drawn after it, clear.
    if (state.replay) {
      this.drawReplayGrade(ctx, skyTop);
      this.drawRoomRims(ctx, state, 'label');
    }
    this.drawBubbles(ctx, state);
    this.drawArrivals(ctx, state);
    this.drawSelection(ctx, state);
  }

  /** @param {CanvasRenderingContext2D} ctx @param {string} name @param {any} time */
  layer(ctx, name, time) {
    const night = this.assets.layer('night', name);
    const day = this.assets.layer('day', name);
    const d = plateDayMix(time.daylight);
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
    // each street lamp leaves a long warm streak on the road, as the picture's wet street does
    for (const lamp of this.m.street.lamps || []) {
      const streak = ctx.createLinearGradient(0, road.top, 0, road.bottom + 20);
      streak.addColorStop(0, `rgba(255,196,120,${0.24 * dark * wet})`);
      streak.addColorStop(1, 'rgba(255,196,120,0)');
      ctx.fillStyle = streak;
      ctx.fillRect(lamp.x - 5, road.top, 10, road.bottom - road.top + 20);
    }
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

  /**
   * What the page knows about the studio beyond its employees, for the screens (hq_screens.js):
   * the newest run and its track, the treasury, the budget, the serial, the newest film's frame.
   * @param {any} facts
   */
  setFacts(facts) {
    this.facts = facts || {};
  }

  /**
   * A cached face, laid on its surface.
   * @param {CanvasRenderingContext2D} ctx @param {string} id @param {string} key
   * @param {number[]} r @param {number} scale @param {(c: CanvasRenderingContext2D, w: number, h: number) => void} paint
   */
  blitFace(ctx, id, key, r, scale, paint) {
    const [x, y, w, h] = r;
    const canvas = this.faces.get(id, key, w, h, scale, paint);
    if (canvas) ctx.drawImage(canvas, x, y, w, h);
    else {
      // no document (tests): draw straight into the world
      ctx.save();
      ctx.translate(x, y);
      paint(ctx, w, h);
      ctx.restore();
    }
  }

  /**
   * A face laid on its surface, and, when its value has just changed live, the one glint that
   * says so (off under reduced motion). The glint is a pale band crossing the glass once and a
   * rim that fades: an honest cue that something real arrived, not motion for its own sake.
   * @param {CanvasRenderingContext2D} ctx @param {string} id @param {string} key
   * @param {number[]} r @param {number} scale @param {(c: CanvasRenderingContext2D, w: number, h: number) => void} paint
   */
  faceBlit(ctx, id, key, r, scale, paint) {
    this.blitFace(ctx, id, key, r, scale, paint);
    this.glintOn(ctx, id, key, r);
  }

  /** @param {CanvasRenderingContext2D} ctx @param {string} id @param {string} key @param {number[]} r */
  glintOn(ctx, id, key, r) {
    const now = typeof performance !== 'undefined' ? performance.now() : 0;
    if (this.glints.note(id, key, now)) this.glintCount += 1;
    const t = this.reduced ? null : this.glints.progress(id, now);
    if (t === null) return;
    const [x, y, w, h] = r;
    ctx.save();
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.clip();
    ctx.globalCompositeOperation = 'lighter';
    // the band crosses in the first 70% of the glint, eased out
    const sweep = Math.min(1, t / 0.7);
    const eased = 1 - (1 - sweep) ** 3;
    const band = Math.max(8, Math.min(w, h) * 0.9);
    const along = -band + (w + h * 0.6 + band * 2) * eased;
    const g = ctx.createLinearGradient(x + along - band, y + h * 0.6, x + along, y);
    const peak = 0.42 * (1 - sweep * 0.5);
    g.addColorStop(0, 'rgba(235,244,255,0)');
    g.addColorStop(0.5, `rgba(235,244,255,${peak})`);
    g.addColorStop(1, 'rgba(235,244,255,0)');
    ctx.fillStyle = g;
    ctx.fillRect(x, y, w, h);
    ctx.restore();
    // the rim: the glass catching the light, fading over the whole glint
    ctx.save();
    ctx.strokeStyle = `rgba(235,244,255,${0.55 * (1 - t)})`;
    ctx.lineWidth = 0.8;
    ctx.strokeRect(x + 0.4, y + 0.4, w - 0.8, h - 0.8);
    ctx.restore();
  }

  /**
   * Every screen and board inside the building, bound to what the page really holds
   * (hq_screens.js). Lit screens are remembered for the room light and the glow.
   * @param {CanvasRenderingContext2D} ctx @param {any[]} agents @param {number} scale
   */
  drawScreens(ctx, agents, scale) {
    const clock = this.world.ambient.clock;
    const facts = this.facts || {};
    /** @type {Array<{r: number[], rgb: string, strength: number, zone: string|null}>} */
    const lit = [];
    const screens = { ...(this.m.screens || {}), ...EXTRA_SCREENS };
    let seed = 0;
    for (const [name, screen] of Object.entries(screens)) {
      seed += 1;
      const r = /** @type {[number, number, number, number]} */ (screen.rect);
      if (screen.kind === 'render_status') {
        this.drawRenderBay(ctx, r, this.agentAt(agents, 'desk_video'), clock, scale);
        lit.push({ r, rgb: '120,170,255', strength: 0.4, zone: screen.zone });
        continue;
      }
      if (DESK_MONITOR.test(name)) continue;
      const agent = screen.desk ? this.agentAt(agents, screen.desk) : agents.find((a) => this.zoneOf(a) === screen.zone) || null;
      const mode = paneMode(agent);
      const accent = name.includes('audio') ? '192,132,252' : name.includes('radar') ? '74,222,128' : name.includes('treasury') ? '163,230,53' : '120,170,255';
      if (name === 'publish_radar' && mode !== 'work' && mode !== 'think' && mode !== 'dark') {
        const face = publishFace(facts.run);
        this.faceBlit(ctx, name, face.key, r, scale, (c, w, h) => paintPublish(c, w, h, face));
        lit.push({ r, rgb: accent, strength: 0.3, zone: screen.zone });
        continue;
      }
      const panes = PANES[name] || [r];
      panes.forEach((pane, i) => drawPane(ctx, pane, mode, accent, clock, seed * 3 + i));
      if (name === 'publish_radar' && (mode === 'work' || mode === 'think')) {
        ctx.strokeStyle = 'rgba(74,222,128,0.8)';
        ctx.lineWidth = 0.8;
        ctx.beginPath();
        const cx = r[0] + r[2] / 2;
        const cy = r[1] + r[3] / 2;
        const a = clock * (mode === 'work' ? 3 : 1);
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + Math.cos(a) * r[2] * 0.45, cy + Math.sin(a) * r[3] * 0.45);
        ctx.stroke();
      }
      if (mode !== 'dark') {
        const strength = mode === 'work' ? 0.4 : mode === 'think' ? 0.28 : mode === 'error' ? 0.3 : 0.14;
        for (const pane of panes) lit.push({ r: pane, rgb: mode === 'error' ? '239,68,68' : accent, strength, zone: screen.zone });
      }
    }

    // the Treasury's wall ticker
    const treasury = treasuryFace(facts.treasury, facts.budget, facts.replay ? 'atunci' : 'azi');
    this.faceBlit(ctx, 'treasury_board', treasury.key, WALL.treasury_board, scale, (c, w, h) => paintTreasury(c, w, h, treasury));
    lit.push({ r: WALL.treasury_board, rgb: '163,230,53', strength: 0.3, zone: 'accounting_office' });
    // the fact-check whiteboard (a board, not a screen: it takes the room's light)
    const check = factCheckFace(facts.run);
    this.faceBlit(ctx, 'factcheck_board', check.key, WALL.factcheck_board, scale, (c, w, h) => paintFactCheck(c, w, h, check));
    // the research board's notes
    const topics = facts.topics || { titles: [], key: '' };
    NOTES.forEach((note, i) => {
      const title = topics.titles[i] || '';
      this.blitFace(ctx, `note${i}`, `n|${title}`, note, scale, (c, w, h) => paintNote(c, w, h, title));
    });
    this.glintOn(ctx, 'research_board', topics.key, BOARD);
    // the writers' room wall screen
    const writers = writersFace(facts.episodes);
    this.faceBlit(ctx, 'writers_screen', writers.key, WALL.writers_screen, scale, (c, w, h) => paintWriters(c, w, h, writers));
    lit.push({ r: WALL.writers_screen, rgb: '95,212,192', strength: 0.3, zone: 'script_room' });
    this.lit = lit;

    // The server racks: their lamps blink while someone in the studio works, and hold steady
    // while nobody does (a blinking rack in an idle building would be work nobody is doing).
    const racks = this.m.displays?.server_racks?.rects || [];
    const working = agents.filter((a) => {
      const m = paneMode(a);
      return m === 'work' || m === 'think';
    }).length;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    racks.forEach((/** @type {number[]} */ r, ri) => {
      for (let i = 0; i < 18; i += 1) {
        const on = working ? Math.sin(clock * (1.5 + working * 1.2) + i * 1.7 + ri) > 0.55 : (i * 7 + ri * 3) % 5 === 0;
        if (!on) continue;
        ctx.fillStyle = i % 5 === 0 ? 'rgba(251,191,36,0.9)' : working ? 'rgba(74,222,128,0.9)' : 'rgba(74,222,128,0.45)';
        ctx.fillRect(r[0] + 3 + ((i * 7) % Math.max(4, r[2] - 6)), r[1] + 4 + ((i * 11) % Math.max(4, r[3] - 8)), 1.5, 1.5);
      }
    });
    ctx.restore();
  }

  /**
   * The monitor on each desk stands in the desks' plate, in front of the employee; it is drawn
   * after that plate, on its own quad (the monitor is turned towards the employee).
   * @param {CanvasRenderingContext2D} ctx @param {any[]} agents
   */
  drawDeskMonitors(ctx, agents) {
    const clock = this.world.ambient.clock;
    let seed = 0;
    for (const [name, screen] of Object.entries(this.m.screens || {})) {
      seed += 1;
      if (!DESK_MONITOR.test(name)) continue;
      const agent = screen.desk ? this.agentAt(agents, screen.desk) : null;
      const mode = paneMode(agent);
      const quad = deskPane(screen.rect);
      const xs = quad.map((p) => p[0]);
      const ys = quad.map((p) => p[1]);
      const r = /** @type {[number, number, number, number]} */ ([Math.min(...xs), Math.min(...ys), Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys)]);
      ctx.save();
      ctx.beginPath();
      quad.forEach(([px, py], i) => (i ? ctx.lineTo(px, py) : ctx.moveTo(px, py)));
      ctx.closePath();
      ctx.clip();
      drawPane(ctx, r, mode, name.includes('audio') ? '192,132,252' : name.includes('accounting') ? '163,230,53' : '120,170,255', clock, seed * 5);
      ctx.restore();
      if (mode !== 'dark') {
        this.lit.push({ r, rgb: mode === 'error' ? '239,68,68' : '120,170,255', strength: mode === 'work' ? 0.3 : mode === 'think' ? 0.2 : 0.1, zone: screen.zone });
      }
    }
  }

  /**
   * Each room's light follows whether anyone works there, within the building's day or night
   * (hq_screens.js roomShade). Lit screens are cut out of the shade, so they glow in a dim room.
   * @param {CanvasRenderingContext2D} ctx @param {any[]} agents @param {any} time
   */
  drawRoomLights(ctx, agents, time) {
    const rooms = this.m.rooms || {};
    const seats = this.m.seats || {};
    const seated = new Set(Object.values(seats).map((/** @type {any} */ s) => s.zone));
    this.roomStates = {};
    // a stage that started live brings its room up to full light for a few seconds (W12)
    const flares = new Map((this.reduced ? [] : this.arrivals.rooms(nowMs())).map((f) => [f.zone, f.strength]));
    for (const [zone, room] of Object.entries(rooms)) {
      if (!seated.has(zone)) continue;
      const inRoom = agents.filter((a) => this.zoneOf(a) === zone);
      const occupancy = roomOccupancy(inRoom);
      const alpha = roomShade(occupancy, time.daylight) * (1 - (flares.get(zone) || 0));
      this.roomStates[zone] = { occupancy, alpha, flare: flares.get(zone) || 0 };
      if (alpha <= 0.001) continue;
      ctx.save();
      ctx.beginPath();
      ctx.rect(room.x, room.y, room.w, room.h);
      for (const s of this.lit || []) {
        if (s.zone !== zone) continue;
        const [x, y, w, h] = s.r;
        // the opposite winding, so the screen is a hole in the shade
        ctx.moveTo(x, y);
        ctx.lineTo(x, y + h);
        ctx.lineTo(x + w, y + h);
        ctx.lineTo(x + w, y);
        ctx.closePath();
      }
      ctx.fillStyle = `rgba(4,6,14,${alpha})`;
      ctx.fill('evenodd');
      ctx.restore();
    }
  }

  /**
   * A lit screen by day is washed by the sun and casts nothing; at night it glows onto its wall.
   * @param {CanvasRenderingContext2D} ctx @param {any} time
   */
  drawScreenLight(ctx, time) {
    const { washout, bloom } = screenLight(time.daylight);
    const lit = this.lit || [];
    if (washout > 0.001) {
      ctx.fillStyle = `rgba(214,224,240,${washout})`;
      for (const s of lit) ctx.fillRect(s.r[0], s.r[1], s.r[2], s.r[3]);
    }
    if (bloom <= 0.01) return;
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    for (const s of lit) {
      const sprite = flareSprite(s.rgb);
      if (!sprite) continue;
      const [x, y, w, h] = s.r;
      const radius = Math.max(w, h) * 0.9 + 6;
      ctx.globalAlpha = Math.min(1, bloom * s.strength);
      ctx.drawImage(sprite, x + w / 2 - radius, y + h / 2 - radius, radius * 2, radius * 2);
    }
    ctx.restore();
  }

  /**
   * THE ROOM THAT STARTS A STAGE, AT FULL LIGHT (W12). A live runbook.stage_started lifts the
   * shade off the rooms that do that stage's work (drawRoomLights) and pours the room's own
   * ceiling light down it for ROOM_FLARE_MS (hq_arrivals.js), softer by day, when the rooms are
   * lit already. Off under reduced motion.
   * @param {CanvasRenderingContext2D} ctx @param {any} time
   */
  drawRoomFlares(ctx, time) {
    if (this.reduced) return;
    const flares = this.arrivals.rooms(nowMs());
    if (!flares.length) return;
    const rooms = this.m.rooms || {};
    const lift = 0.34 - 0.14 * Math.max(0, Math.min(1, time.daylight));
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    for (const f of flares) {
      const room = rooms[f.zone];
      if (!room) continue;
      const k = f.strength * lift;
      const g = ctx.createLinearGradient(0, room.y, 0, room.y + room.h);
      g.addColorStop(0, `rgba(255,238,206,${k})`);
      g.addColorStop(0.4, `rgba(255,238,206,${k * 0.45})`);
      g.addColorStop(1, `rgba(255,238,206,${k * 0.16})`);
      ctx.fillStyle = g;
      ctx.fillRect(room.x, room.y, room.w, room.h);
    }
    ctx.restore();
  }

  /**
   * The flared room's soft edge, over the shell so it reads from across the room: a lit line on
   * the room's frame with a halo that fades outward, and one chip on the room's floor, right, with the
   * stage's own words («acum: documentare și verificare», hud_charts.js runStageWord), the same
   * words the slate and the sign say. Constant size on the screen, like every mark.
   * @param {CanvasRenderingContext2D} ctx @param {any} state
   * @param {'all'|'rim'|'label'} [part] the rim, the chip, or both (the replay draws its chips
   *   after its grade, so the words are never tinted)
   */
  drawRoomRims(ctx, state, part = 'all') {
    if (this.reduced) return;
    const flares = this.arrivals.rooms(nowMs());
    if (!flares.length) return;
    const rooms = this.m.rooms || {};
    const zoom = state.scale && state.scale > 0 ? state.scale : 1;
    const px = (/** @type {number} */ n) => n / zoom;
    const c = scenePalette();
    // the replay's violet in «Reluarea zilei», the register's green live (hq_arrivals.js arrivalAccent)
    const accent = c[arrivalAccent(Boolean(state.replay))];
    const labelled = new Set();
    for (const f of flares) {
      const room = rooms[f.zone];
      if (!room) continue;
      const k = f.strength;
      if (part !== 'label') {
        ctx.save();
        ctx.globalCompositeOperation = 'lighter';
        const halo = [[0, 1.6, 0.62], [px(3), 3, 0.2], [px(7), 4, 0.09], [px(12), 5, 0.04]];
        for (const [pad, width, alpha] of halo) {
          ctx.lineWidth = px(width);
          ctx.strokeStyle = `rgba(255,238,206,${alpha * k})`;
          ctx.strokeRect(room.x - pad, room.y - pad, room.w + pad * 2, room.h + pad * 2);
        }
        ctx.restore();
      }
      if (part === 'rim' || labelled.has(f.stage)) continue;
      labelled.add(f.stage);
      const text = `acum: ${runStageWord(f.stage)}`;
      ctx.save();
      ctx.globalAlpha = k;
      ctx.font = `600 ${px(12)}px "Segoe UI", system-ui, sans-serif`;
      const padX = px(9);
      const dot = px(7);
      const tw = ctx.measureText(text).width + padX * 2 + dot + px(6);
      const th = px(24);
      // A narrow room at a small zoom (1280) would be half covered by its own chip: the lit room
      // and the sign's «acum: …» say it there.
      if (tw > room.w * 0.62) {
        ctx.restore();
        continue;
      }
      // the room's floor, right: its name plate and its boards are along the top, and the
      // arriving employee's tag stands under the desks
      const x = room.x + room.w - tw - px(8);
      const y = room.y + room.h - th - px(6);
      ctx.fillStyle = withAlpha(c.scene, 0.92);
      roundRect(ctx, x, y, tw, th, px(5));
      ctx.fill();
      ctx.lineWidth = px(1);
      ctx.strokeStyle = withAlpha(accent, 0.7);
      ctx.stroke();
      ctx.fillStyle = accent;
      ctx.beginPath();
      ctx.arc(x + padX + dot / 2, y + th / 2, dot / 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = c.chromeInk;
      ctx.textBaseline = 'middle';
      ctx.fillText(text, x + padX + dot + px(6), y + th / 2 + px(0.5));
      ctx.restore();
    }
    ctx.textBaseline = 'alphabetic';
  }

  /**
   * THE LIVE ARRIVAL'S TAG (W12): an employee who starts to work, live, wears their world tag
   * under their desk for about four seconds («Dr. Aris (Researcher) · lucrează · idei de
   * subiect») at 13 screen pixels, and one ring widens from their desk twice, so a visitor
   * looking at the other side of the building sees where. The words are the event's own
   * (hq_arrivals.js). The employee under the pointer or the keyboard, or chosen, already wears a
   * tag: theirs is not doubled. Off under reduced motion.
   * @param {CanvasRenderingContext2D} ctx @param {any} state
   */
  drawArrivals(ctx, state) {
    if (this.reduced) return;
    const tags = this.arrivals.tags(nowMs());
    if (!tags.length) return;
    const c = scenePalette();
    const accent = c[arrivalAccent(Boolean(state.replay))];
    const zoom = state.scale && state.scale > 0 ? state.scale : 1;
    const px = (/** @type {number} */ n) => n / zoom;
    for (const tag of tags) {
      const hit = this.hits.find((/** @type {any} */ h) => !h.surface && h.agent && String(h.agent.id || h.agent.agent_id) === tag.id);
      if (!hit) continue;
      const k = tag.strength;
      // the rings: two, 380 ms apart, widening from the figure's box and fading as they go
      for (const delay of [0, 380]) {
        const t = (tag.age - delay) / 1100;
        if (t < 0 || t >= 1) continue;
        const grow = 1 - (1 - t) ** 3;
        const pad = px(3) + px(30) * grow;
        ctx.save();
        ctx.lineWidth = px(2.2 * (1 - t) + 0.8);
        ctx.strokeStyle = withAlpha(accent, 0.9 * (1 - t));
        roundRect(ctx, hit.x0 - pad, hit.y0 - pad, hit.x1 - hit.x0 + pad * 2, hit.y1 - hit.y0 + pad * 2, px(6) + pad * 0.3);
        ctx.stroke();
        ctx.restore();
      }
      if (tag.id === String(state.hoverId || '') || tag.id === String(state.selectedId || '')) continue;
      const parts = tag.words.split(' · ');
      const name = parts[0] || '';
      const verb = parts[1] || '';
      const task = parts.slice(2).join(' · ');
      ctx.save();
      ctx.globalAlpha = k;
      const bold = `600 ${px(13)}px "Segoe UI", system-ui, sans-serif`;
      const plain = `500 ${px(13)}px "Segoe UI", system-ui, sans-serif`;
      const sep = ' · ';
      ctx.font = bold;
      const wName = ctx.measureText(name).width;
      const wVerb = ctx.measureText(verb).width;
      ctx.font = plain;
      const wSep = ctx.measureText(sep).width;
      const wTask = task ? ctx.measureText(task).width : 0;
      const padX = px(10);
      const bar = px(3);
      const tw = bar + padX + wName + wSep + wVerb + (task ? wSep + wTask : 0) + padX;
      const th = px(28);
      const mid = (hit.x0 + hit.x1) / 2;
      const x = Math.min(this.world.worldW - tw - px(2), Math.max(px(2), mid - tw / 2));
      // under the desk, where the pointer's own tag stands: above the head it lay over the
      // room's boards and the render bay's screen
      const y = hit.y1 + px(6) + px(6) * (1 - k);
      ctx.fillStyle = withAlpha(c.scene, 0.94);
      roundRect(ctx, x, y, tw, th, px(5));
      ctx.fill();
      ctx.lineWidth = px(1);
      ctx.strokeStyle = withAlpha(accent, 0.55);
      ctx.stroke();
      ctx.fillStyle = accent;
      ctx.fillRect(x + px(1), y + px(5), bar, th - px(10));
      ctx.textBaseline = 'middle';
      let at = x + bar + padX;
      const line = y + th / 2 + px(0.5);
      ctx.font = bold;
      ctx.fillStyle = c.chromeInk;
      ctx.fillText(name, at, line);
      at += wName;
      ctx.font = plain;
      ctx.fillStyle = c.chromeMuted;
      ctx.fillText(sep, at, line);
      at += wSep;
      ctx.font = bold;
      ctx.fillStyle = verb === 'lucrează' ? accent : c.chromeInk;
      ctx.fillText(verb, at, line);
      at += wVerb;
      if (task) {
        ctx.font = plain;
        ctx.fillStyle = c.chromeMuted;
        ctx.fillText(sep, at, line);
        at += wSep;
        ctx.fillStyle = c.chromeInk;
        ctx.fillText(task, at, line);
      }
      ctx.restore();
    }
    ctx.textBaseline = 'alphabetic';
  }

  /**
   * The façade: the day's run on the sign, and the tokens used today on the server room's plate.
   * @param {CanvasRenderingContext2D} ctx @param {number} scale
   */
  drawFacade(ctx, scale) {
    const facts = this.facts || {};
    const sign = runSignFace(facts.track, { today: facts.today, live: facts.live, next: facts.nextRun || '', read: facts.reads ? facts.reads.runs : undefined });
    const palette = scenePalette();
    this.blitFace(ctx, 'run_sign', `${sign.key}|${palette.okInk}`, WALL.run_sign, scale, (c, w, h) => paintRunSign(c, w, h, sign, palette));
    // the glint follows the day's own words, not the next-run line (which follows the scheduler)
    this.glintOn(ctx, 'run_sign', `${sign.title}|${sign.tally}|${sign.segments.join(',')}`, WALL.run_sign);
    if (sign.running >= 0 && sign.segments.length) {
      // the running stage breathes, with the world's clock (still under reduced motion)
      const [x, y, w] = WALL.run_sign;
      const n = sign.segments.length;
      const gap = 1.6;
      const sw = (w - 4 - gap * (n - 1)) / n;
      const pulse = 0.25 + 0.25 * Math.sin(this.world.ambient.clock * 3);
      ctx.fillStyle = withAlpha('#ffffff', Math.max(0, pulse));
      ctx.fillRect(x + 2 + sign.running * (sw + gap), y + 13.5, sw, 5);
    }
    const tokens = tokensFace(facts.budget, facts.replay ? 'atunci' : 'azi');
    this.faceBlit(ctx, 'infra_plate', tokens.key, WALL.infra_plate, scale, (c, w, h) => paintInfra(c, w, h, tokens));
  }

  /** @param {any} agent */
  zoneOf(agent) {
    const seat = this.m.seats?.[agent?.desk_id];
    return seat ? seat.zone : null;
  }

  /**
   * The render bay's wall display: the render while the Video Editor works, else a frame of the
   * newest rendered film, else his state in words. Never a number nobody measured.
   * @param {CanvasRenderingContext2D} ctx @param {[number, number, number, number]} r
   */
  drawRenderBay(ctx, r, agent, clock, scale) {
    const film = (this.facts && this.facts.film) || null;
    const face = renderBayFace({ agent, film });
    const poster = film && film.canvas ? film.canvas : null;
    // Drawn at twice the display's pixels: the film's frame is the one picture in the building,
    // and at fit zoom a face cached at the display's own scale smeared it into a dark square.
    this.faceBlit(ctx, 'render_bay', face.key, r, scale * 2, (c, w, h) => paintRenderBay(c, w, h, face, poster));
    if (face.kind !== 'rendering') return;
    const [x, y, dw] = r;
    ctx.save();
    ctx.beginPath();
    ctx.rect(x + 8.5, y + 33.5, dw - 17, 5);
    ctx.clip();
    ctx.fillStyle = '#38bdf8';
    const band = (dw - 18) * 0.35;
    const pos = ((clock * 30) % (dw - 18 + band)) - band;
    ctx.fillRect(x + 9 + pos, y + 34, band, 4);
    ctx.restore();
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

  /**
   * The employees' hit boxes without painting them: while the Unreal stream covers the canvas, a
   * click on the video still finds who sits at the desk under the pointer.
   * @param {any[]} agents
   */
  keepHits(agents) {
    this.drawAgents(null, { agents, bubbles: [] });
  }

  /**
   * Every street sprite sheet laid under the hour's light now (litSheet), rather than each one the
   * first time its vehicle or passer-by appears: that first tint is a canvas the size of a sheet,
   * and at the entry into the building it cost a frame.
   * @param {any} time @param {any} fx
   */
  warmTints(time, fx) {
    const outdoor = streetLight(time, fx);
    for (const kind of Object.keys(this.assets.vehicles?.vehicles || {})) {
      const img = this.assets.sheet(`veh:${kind}`);
      if (img) this.litSheet(`veh:${kind}`, img, outdoor);
    }
    for (const key of Object.keys(this.assets.pedestrians?.characters || {})) {
      const img = this.assets.sheet(`ped:${key}`);
      if (img) this.litSheet(`ped:${key}`, img, outdoor);
    }
  }

  /** @param {CanvasRenderingContext2D|null} ctx null keeps the hit boxes and paints nothing @param {any} state */
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
      if (ctx) ctx.drawImage(img, (f.index % cols) * sw, Math.floor(f.index / cols) * sh, sw, sh, dx, dy, frame.w * s, frame.h * s);
      this.hits.push({ agent, x0: seat.x - 16, y0: seat.y - SEATED_LIFT - 44, x1: seat.x + 16, y1: seat.y + 2 });
    }
    // The bound faces, after the employees (so hits[0] is still an employee): each wall, and the
    // monitor on every occupied desk. A pointer takes the smallest box under it (hq_readouts.js
    // hitAt), so a desk's monitor is found in front of its employee.
    for (const s of surfaceRects(this.m, state.agents)) {
      const [x, y, w, h] = s.rect;
      this.hits.push({ agent: s.agent, surface: s.id, room: s.room, desk: s.desk, x0: x, y0: y, x1: x + w, y1: y + h });
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
      ctx.fillText(stageLabel(String(token.stage || '')), x, y - 3);
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
   * @param {[number, number, number]} [light] outdoor light for people on the street; the courier
   *   inside is lit by the building and passes none
   */
  drawWalker(ctx, sheetKey, x, row, dir, phase, walking, light) {
    const atlas = this.assets.pedestrians;
    const entry = atlas?.characters?.[sheetKey];
    const img = this.assets.sheet(`ped:${sheetKey}`);
    if (!entry || !img) return;
    const sheet = light ? this.litSheet(`ped:${sheetKey}`, img, light) : img;
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
    ctx.drawImage(sheet, (index % entry.columns) * sw, Math.floor(index / entry.columns) * sh, sw, sh, -fr.pivot[0] * s, -fr.pivot[1] * s, fr.w * s, fr.h * s);
    ctx.restore();
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} fx @param {any} time */
  drawPedestrians(ctx, fx, time) {
    const atlas = this.assets.pedestrians;
    if (!atlas) return;
    const outdoor = streetLight(time, fx);
    for (const p of this.world.pedestrians.paintOrder()) {
      ctx.fillStyle = 'rgba(0,0,0,0.22)';
      ctx.beginPath();
      ctx.ellipse(p.x, p.row, 7, 2, 0, 0, Math.PI * 2);
      ctx.fill();
      const walking = p.react <= 0 && (p.state === 'walk' || p.state === 'cross');
      this.drawWalker(ctx, p.sheet, p.x, p.row, p.dir, p.frame, walking, outdoor);
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
    const outdoor = streetLight(time, fx);
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
      ctx.drawImage(this.litSheet(`veh:${v.kind}`, img, outdoor), col * cellW, sy, d.w * scale, d.h * scale, dx, dy, d.w, d.h);
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

  /**
   * The bus shelter's clock. In «Reluarea zilei» the world is lit by the replayed moment, so the
   * street's clock shows that moment's time under the replay's mark, ATUNCI, never the live time
   * inside the replayed world (W15).
   * @param {CanvasRenderingContext2D} ctx @param {any} time @param {boolean} [replay]
   */
  drawShelter(ctx, time, replay = false) {
    const clock = this.m.street.shelter_clock?.rect;
    if (clock) {
      const [x, y, cw, ch] = clock;
      ctx.fillStyle = '#071c22';
      ctx.fillRect(x, y, cw, ch);
      ctx.fillStyle = '#9fd8d0';
      ctx.font = '600 5.5px "Segoe UI", system-ui, sans-serif';
      ctx.fillText(replay ? 'ATUNCI' : 'BUCUREȘTI', x + 4, y + 8);
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

  /** @param {CanvasRenderingContext2D} ctx @param {any} time @param {number} [skyTop] the row of sky above the world */
  drawNightGrade(ctx, time, skyTop = 0) {
    const deep = Math.max(0, Math.min(1, (-time.elevation - 8) / 10));
    if (deep <= 0) return;
    ctx.save();
    ctx.globalCompositeOperation = 'multiply';
    ctx.fillStyle = `rgba(70,84,130,${0.45 * deep})`;
    ctx.beginPath();
    ctx.rect(0, skyTop, this.world.worldW, this.world.worldH - skyTop);
    // The building keeps its own light. Its hole starts under the roof railing, so the sky seen
    // through the railing is graded as the sky above it is, except for the lift tower's head,
    // which reaches the world's top edge.
    ctx.moveTo(415, 10);
    ctx.lineTo(415, 676);
    ctx.lineTo(1352, 676);
    ctx.lineTo(1352, 0);
    ctx.lineTo(1187, 0);
    ctx.lineTo(1187, 10);
    ctx.closePath();
    ctx.fill('evenodd');
    ctx.restore();
  }

  /**
   * THE REPLAY'S GRADE (W13). The world played back from the record is taken most of the way to
   * grey and washed with the replay's own violet (--replay-grade, --replay-tone), sky and street
   * included, so no one can take it for the live building; with the letterbox the page lays over
   * the frame (office_scene.css) and the «RELUARE» chip in place of «Live». Two fills of the
   * world's rectangle, composited on the GPU.
   * @param {CanvasRenderingContext2D} ctx @param {number} skyTop
   */
  drawReplayGrade(ctx, skyTop) {
    const c = scenePalette();
    const h = this.world.worldH - skyTop;
    ctx.save();
    ctx.globalCompositeOperation = 'saturation';
    ctx.fillStyle = c.replayGrade;
    ctx.fillRect(0, skyTop, this.world.worldW, h);
    ctx.globalCompositeOperation = 'soft-light';
    ctx.fillStyle = c.replayTone;
    ctx.fillRect(0, skyTop, this.world.worldW, h);
    ctx.restore();
  }

  /**
   * A replayed caption (W13): the words the record says the employee spoke, in their own case,
   * two lines at most (day_replay.js captionLines), at a constant 12 screen px like every mark,
   * with its label «RELUARE · 23:51:02» over it, so a caption of the replay is never read as said
   * now.
   * @param {CanvasRenderingContext2D} ctx @param {any} state @param {any} bubble @param {number} x @param {number} y
   */
  drawReplayCaption(ctx, state, bubble, x, y) {
    const c = scenePalette();
    const zoom = state.scale && state.scale > 0 ? state.scale : 1;
    const px = (/** @type {number} */ n) => n / zoom;
    const lines = Array.isArray(bubble.lines) ? bubble.lines : [];
    if (!lines.length) return;
    ctx.save();
    ctx.font = `600 ${px(12)}px "Segoe UI", system-ui, sans-serif`;
    const tw = Math.max(...lines.map((l) => ctx.measureText(l).width));
    ctx.font = `700 ${px(9.5)}px "Segoe UI", system-ui, sans-serif`;
    const lw = ctx.measureText(bubble.label).width;
    const padX = px(9);
    const bw = Math.max(tw, lw) + padX * 2;
    const bh = px(26) + px(16) * lines.length;
    const bx = Math.min(this.world.worldW - bw - px(2), Math.max(px(2), x - bw / 2));
    const by = y - bh - px(6);
    ctx.fillStyle = withAlpha(c.scene, 0.94);
    ctx.strokeStyle = withAlpha(c.replayInk, 0.7);
    ctx.lineWidth = px(1);
    roundRect(ctx, bx, by, bw, bh, px(5));
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(x - px(4), by + bh);
    ctx.lineTo(x, by + bh + px(5));
    ctx.lineTo(x + px(4), by + bh);
    ctx.fill();
    ctx.textBaseline = 'middle';
    ctx.fillStyle = c.replayInk;
    ctx.fillText(bubble.label, bx + padX, by + px(12));
    ctx.font = `600 ${px(12)}px "Segoe UI", system-ui, sans-serif`;
    ctx.fillStyle = c.chromeInk;
    lines.forEach((line, i) => ctx.fillText(line, bx + padX, by + px(28) + i * px(16)));
    ctx.restore();
    ctx.textBaseline = 'alphabetic';
  }

  /** @param {CanvasRenderingContext2D} ctx @param {any} state */
  drawBubbles(ctx, state) {
    const now = Date.now();
    for (const bubble of state.bubbles) {
      const agent = state.agents.find((/** @type {any} */ a) => (a.id || a.agent_id) === bubble.agentId);
      const seat = agent ? this.m.seats?.[agent.desk_id] : null;
      const x = seat ? seat.x : bubble.x;
      const y = seat ? seat.y - 42 : bubble.y;
      if (bubble.label) {
        this.drawReplayCaption(ctx, state, bubble, x, y);
        continue;
      }
      const frame = bubbleFrame(bubble.pages || [], (now - bubble.createdAt) / 1000);
      if (!frame.lines.length) continue;
      ctx.font = '600 6px "Segoe UI", system-ui, sans-serif';
      const widest = Math.max(40, ...frame.lines.map((l) => ctx.measureText(l).width));
      const bw = widest + 12;
      const bh = frame.lines.length * 8 + 9;
      const bx = Math.min(this.world.worldW - bw - 4, Math.max(4, x - bw / 2));
      const by = y - bh;
      // The caption is interface, not art: it is drawn on the same plate the readouts on the
      // bezel are drawn on, in the scene's own chrome tokens rather than in a slate of its own.
      const c = scenePalette();
      ctx.fillStyle = withAlpha(c.scene, 0.92);
      ctx.strokeStyle = withAlpha(c.chromeEdge, 0.9);
      ctx.lineWidth = 0.8;
      roundRect(ctx, bx, by, bw, bh, 4);
      ctx.fill();
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(x - 3, by + bh);
      ctx.lineTo(x, by + bh + 4);
      ctx.lineTo(x + 3, by + bh);
      ctx.fill();
      ctx.fillStyle = c.chromeInk;
      frame.lines.forEach((line, i) => ctx.fillText(line, bx + 6, by + 10 + i * 8));
      if (frame.pageCount > 1) {
        ctx.fillStyle = c.chromeMuted;
        ctx.font = '600 4.5px "Segoe UI", system-ui, sans-serif';
        ctx.fillText(`${frame.pageIndex + 1}/${frame.pageCount}`, bx + bw - 14, by + bh - 3);
      }
    }
  }

  /**
   * THE POINTER AND THE SELECTION, 2026-09-23.
   *
   * What stood here drew a name tag 6.5 world-pixels tall under the seat, in a teal that was not
   * the page's teal. The Owner looks at this scene at fit zoom, where the world is drawn at about
   * 0.86 of its size at 1920 and at about 0.55 in the wide spread: a 6.5px tag arrives as five
   * screen pixels of type, and the figure itself was given no mark at all, so "which one is under
   * my hand" and "which one did I open" were both unanswerable at the zoom he actually uses.
   *
   * Now every mark is drawn at a CONSTANT SIZE ON THE SCREEN — measured in screen pixels and
   * divided by the live zoom into world units — so the ring and the tag are the same size at fit
   * zoom, at 1:1 and at 4x, exactly like the chrome around the render. The selected employee wears
   * the page's own focus colour (--teal, the same ring every button on the page answers the
   * keyboard with); the employee merely under the pointer wears the scene's chrome, which is the
   * same plate the readouts on the bezel are drawn on. Both come from the token block.
   *
   * @param {CanvasRenderingContext2D} ctx @param {any} state
   */
  drawSelection(ctx, state) {
    const c = scenePalette();
    const zoom = state.scale && state.scale > 0 ? state.scale : 1;
    /** screen pixels, in world units at the zoom being drawn @param {number} n */
    const px = (n) => n / zoom;
    for (const id of new Set([state.hoverId, state.selectedId])) {
      if (!id) continue;
      const agent = state.agents.find((/** @type {any} */ a) => (a.id || a.agent_id) === id);
      const seat = agent ? this.m.seats?.[agent.desk_id] : null;
      if (!seat) continue;
      const chosen = id === state.selectedId;
      const hit = this.hits.find((/** @type {any} */ h) => !h.surface && h.agent && (h.agent.id || h.agent.agent_id) === id);

      // The mark on the figure. A ring the pointer can see from across the room, drawn round the
      // same box a click is tested against, so what lights is exactly what is clickable.
      if (hit) {
        const pad = px(3);
        ctx.save();
        ctx.lineWidth = px(chosen ? 2 : 1.5);
        ctx.strokeStyle = chosen ? c.teal : withAlpha(c.chromeInk, 0.65);
        roundRect(ctx, hit.x0 - pad, hit.y0 - pad, hit.x1 - hit.x0 + pad * 2, hit.y1 - hit.y0 + pad * 2, px(4));
        if (chosen) {
          // The selected one also carries the page's focus geometry: a dark ring outside the
          // bright one, so the mark survives a bright wall behind it exactly as --focus-ring does.
          ctx.save();
          ctx.lineWidth = px(4);
          ctx.strokeStyle = withAlpha(c.sceneDeep, 0.75);
          ctx.stroke();
          ctx.restore();
        }
        ctx.stroke();
        ctx.restore();
      }

      // The name tag, at a size that can be read: 11 screen pixels, the page's --fs-meta. Under
      // it, fainter, the employee's last real task in the register (hq_readouts.js lastTasks):
      // shown only on the one under the pointer or the keyboard, never as a label on every desk.
      const name = String(agent.display_name || agent.role_name || 'Agent');
      const status = stateOf(agent);
      const text = `${name} · ${runtimeLabel(status)}`;
      const tasks = (this.facts && this.facts.tasks && this.facts.tasks.tasks) || {};
      const second = lastTaskLine(tasks[id], Date.now());
      ctx.save();
      ctx.font = `500 ${px(10)}px "Segoe UI", system-ui, sans-serif`;
      const secondW = ctx.measureText(second).width;
      ctx.font = `600 ${px(11)}px "Segoe UI", system-ui, sans-serif`;
      const padX = px(8);
      const tw = Math.max(ctx.measureText(text).width, secondW) + padX * 2;
      const th = px(34);
      const x = Math.min(this.world.worldW - tw - px(2), Math.max(px(2), seat.x - tw / 2));
      const y = (hit ? hit.y1 : seat.y) + px(5);
      ctx.fillStyle = chosen ? c.teal : withAlpha(c.scene, 0.92);
      roundRect(ctx, x, y, tw, th, px(4));
      ctx.fill();
      if (!chosen) {
        ctx.lineWidth = px(1);
        ctx.strokeStyle = withAlpha(c.chromeEdge, 0.9);
        ctx.stroke();
      }
      // On the teal plate the label is the page's deepest ground, as it is on every teal the page
      // fills; on the chrome plate it is the chrome's own ink.
      ctx.fillStyle = chosen ? c.sceneDeep : c.chromeInk;
      ctx.textBaseline = 'middle';
      ctx.fillText(text, x + padX, y + px(11));
      ctx.font = `500 ${px(10)}px "Segoe UI", system-ui, sans-serif`;
      ctx.fillStyle = chosen ? c.sceneDeep : c.chromeMuted;
      ctx.fillText(second, x + padX, y + px(25));
      ctx.restore();
    }
    ctx.textBaseline = 'alphabetic';
    this.drawSurfaceMark(ctx, state, px);
  }

  /**
   * The mark on a face under the pointer or the keyboard: the same ring an employee wears, at a
   * constant size on screen. Under the keyboard it is the page's focus ring (--teal over a dark
   * ring), under the pointer the scene's chrome.
   * @param {CanvasRenderingContext2D} ctx @param {any} state @param {(n: number) => number} px
   */
  drawSurfaceMark(ctx, state, px) {
    if (!state.surfaceId) return;
    const hit = this.hits.find((/** @type {any} */ h) => h.surface === state.surfaceId);
    if (!hit) return;
    const c = scenePalette();
    const keyboard = state.surfaceVia === 'keyboard';
    const pad = px(4);
    ctx.save();
    roundRect(ctx, hit.x0 - pad, hit.y0 - pad, hit.x1 - hit.x0 + pad * 2, hit.y1 - hit.y0 + pad * 2, px(4));
    if (keyboard) {
      ctx.lineWidth = px(4);
      ctx.strokeStyle = withAlpha(c.sceneDeep, 0.75);
      ctx.stroke();
    }
    ctx.lineWidth = px(keyboard ? 2 : 1.5);
    ctx.strokeStyle = keyboard ? c.teal : withAlpha(c.chromeInk, 0.65);
    ctx.stroke();
    ctx.restore();
  }
}

/** The research board's notes, as one surface. */
const BOARD = unionRect(NOTES);

/** The frame clock the flourishes are timed on (performance.now; 0 without it, in tests). */
function nowMs() {
  return typeof performance !== 'undefined' ? performance.now() : 0;
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
