/**
 * RandomEventManager: the configurable engine behind everything that happens by chance outside.
 *
 * Events are data (frontend/public/assets/hq/world_events.json), never code paths chosen by a
 * scattered Math.random(). Each event declares its rarity, weight, cooldown, how many may run at
 * once, the weather and time of day it may happen in, how long it lasts, its priority and how far
 * its reaction reaches. The manager rolls with the world's seeded random source, so a QA seed
 * reproduces a sequence exactly. Nothing here touches the studio's work: an event is scenery.
 */

/** Expected starts per minute for an event of weight 1, by rarity. */
export const RARITY_RATE = { common: 0.9, uncommon: 0.22, rare: 0.035, very_rare: 0.0012 };

/**
 * @typedef {{eventId:string, category:string, rarity:keyof typeof RARITY_RATE, probabilityWeight:number,
 *   minimumCooldown:number, maximumConcurrentEvents:number, allowedWeather:string[], allowedTimeOfDay:string[],
 *   duration:[number, number], priority:number, reactionRadius:number, enabled:boolean}} EventDefinition
 */

/** @param {any} raw @returns {EventDefinition|null} */
export function validateEvent(raw) {
  if (!raw || typeof raw.eventId !== 'string' || !(raw.rarity in RARITY_RATE)) return null;
  const duration = Array.isArray(raw.duration) ? raw.duration : [raw.duration, raw.duration];
  return {
    eventId: raw.eventId,
    category: String(raw.category || 'ambient'),
    rarity: raw.rarity,
    probabilityWeight: Math.max(0, Number(raw.probabilityWeight ?? 1)),
    minimumCooldown: Math.max(0, Number(raw.minimumCooldown ?? 60)),
    maximumConcurrentEvents: Math.max(1, Number(raw.maximumConcurrentEvents ?? 1)),
    allowedWeather: Array.isArray(raw.allowedWeather) ? raw.allowedWeather : ['any'],
    allowedTimeOfDay: Array.isArray(raw.allowedTimeOfDay) ? raw.allowedTimeOfDay : ['any'],
    duration: [Number(duration[0] ?? 10), Number(duration[1] ?? duration[0] ?? 10)],
    priority: Number(raw.priority ?? 1),
    reactionRadius: Math.max(0, Number(raw.reactionRadius ?? 0)),
    enabled: raw.enabled !== false,
  };
}

export class RandomEventManager {
  /**
   * @param {any} config world_events.json
   * @param {() => number} rng seeded random source
   */
  constructor(config, rng) {
    this.rng = rng;
    this.checkEvery = Number(config?.checkIntervalSeconds ?? 4);
    this.maxActive = Number(config?.maximumActiveEvents ?? 4);
    /** @type {EventDefinition[]} */
    this.definitions = (config?.events || []).map(validateEvent).filter((/** @type {any} */ e) => e && e.enabled);
    /** @type {Array<{key:string, def:EventDefinition, startedAt:number, duration:number, seed:number, data:any}>} */
    this.active = [];
    /** @type {Map<string, number>} */
    this.lastStarted = new Map();
    this.clock = 0;
    this._acc = 0;
    this._serial = 0;
    /** @type {Set<(kind:string, event:any) => void>} */
    this.listeners = new Set();
  }

  /** @param {(kind:string, event:any) => void} fn */
  on(fn) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  /**
   * @param {EventDefinition} def
   * @param {{weather:string, phase:string}} context
   */
  eligible(def, context) {
    const last = this.lastStarted.get(def.eventId);
    if (last !== undefined && this.clock - last < def.minimumCooldown) return false;
    if (this.active.filter((e) => e.def.eventId === def.eventId).length >= def.maximumConcurrentEvents) return false;
    const weatherOk = def.allowedWeather.includes('any') || def.allowedWeather.includes(context.weather);
    const timeOk = def.allowedTimeOfDay.includes('any') || def.allowedTimeOfDay.includes(context.phase);
    return weatherOk && timeOk;
  }

  /**
   * @param {number} dt seconds
   * @param {{weather:string, phase:string}} context
   */
  update(dt, context) {
    this.clock += dt;
    for (const event of [...this.active]) {
      if (this.clock - event.startedAt >= event.duration) {
        this.active.splice(this.active.indexOf(event), 1);
        this.emit('end', event);
      }
    }
    this._acc += dt;
    while (this._acc >= this.checkEvery) {
      this._acc -= this.checkEvery;
      this.roll(context);
    }
  }

  /** @param {{weather:string, phase:string}} context */
  roll(context) {
    const candidates = this.definitions
      .filter((def) => this.eligible(def, context))
      .sort((a, b) => b.priority - a.priority);
    for (const def of candidates) {
      if (this.active.length >= this.maxActive) break;
      const p = RARITY_RATE[def.rarity] * def.probabilityWeight * (this.checkEvery / 60);
      if (this.rng() < p) this.start(def);
    }
  }

  /** @param {EventDefinition} def */
  start(def) {
    const [lo, hi] = def.duration;
    const event = {
      key: `${def.eventId}#${(this._serial += 1)}`,
      def,
      startedAt: this.clock,
      duration: lo + (hi - lo) * this.rng(),
      seed: Math.floor(this.rng() * 1e9),
      data: {},
    };
    this.active.push(event);
    this.lastStarted.set(def.eventId, this.clock);
    this.emit('start', event);
    return event;
  }

  /** Start an event now, for QA from the console; ignores chance, keeps every other rule. */
  /** @param {string} eventId @param {{weather:string, phase:string}} [context] */
  trigger(eventId, context) {
    const def = this.definitions.find((d) => d.eventId === eventId);
    if (!def) return null;
    if (context && !this.eligible(def, context)) return null;
    return this.start(def);
  }

  /** @param {string} kind @param {any} event */
  emit(kind, event) {
    for (const fn of this.listeners) fn(kind, event);
  }

  /** @param {string} eventId */
  isActive(eventId) {
    return this.active.some((e) => e.def.eventId === eventId);
  }

  /** @param {any} event */
  progress(event) {
    return Math.min(1, (this.clock - event.startedAt) / Math.max(0.001, event.duration));
  }
}
