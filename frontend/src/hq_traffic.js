import { dailyRhythm, weightedChoice } from './street_schedule.js';

/**
 * TrafficManager: vehicles that enter the street at one edge and leave at the other.
 *
 * Right-hand traffic, as in Bucharest: the lane by the headquarters flows left, the near lane
 * flows right. How many vehicles and which kinds follow the real hour and day in Bucharest and
 * the real weather the backend reads (`trafficDensity`, `vehicleMix`); buses stop at the shelter
 * when someone is waiting or on schedule, everyone stops for people on the crosswalk, and
 * traffic yields to a siren. A siren only ever drives when the backend says there is an
 * emergency (hq_events.js `eventAllowed`); today nothing does. Vehicles never pass through each
 * other: a follower slows to its leader and is clamped behind it if it would overlap.
 */

export const BUS_LIVERIES = { bus: 55, bus_amn: 25, bus_curiosity: 10, bus_nexus: 10 };
export const EMERGENCY = { ambulance_siren: 'ambulance', police_patrol: 'police', fire_truck_siren: 'firetruck' };

/** @param {number} x */
const clamp01 = (x) => Math.min(1, Math.max(0, x));

/**
 * How full the road is, 0..1, from the hour's rhythm and the real weather. Rain does not empty a
 * Bucharest road: people who would have walked drive, so there are a few more cars, only slower
 * (the `slow` factor in update). Snow and thick fog keep drivers at home.
 * @param {{traffic:number}} rhythm dailyRhythm for the real hour and day
 * @param {{rain?:number, snow?:number, fog?:number}} fx weatherEffects of the real weather
 */
export function trafficDensity(rhythm, fx) {
  return clamp01(rhythm.traffic * (1 + (fx.rain || 0) * 0.1) * (1 - (fx.snow || 0) * 0.45) * (1 - (fx.fog || 0) * 0.2));
}

/**
 * Map the schedule's vehicle weights onto the rendered catalogue. Two-wheelers stay home in the
 * rain and the snow.
 * @param {any} w @param {{rain?:number, snow?:number}} [fx]
 */
export function vehicleMix(w, fx = {}) {
  const g = (/** @type {string} */ k) => Number(w?.[k] || 0);
  const dry = clamp01(1 - (fx.rain || 0) * 1.4) * clamp01(1 - (fx.snow || 0) * 1.6);
  return {
    sedan: g('sedan') + g('wagon'),
    coupe: g('coupe'),
    hatchback: g('hatchback'),
    suv: g('suv') + g('pickup'),
    taxi: g('taxi'),
    ev: (g('sedan') + g('hatchback')) * 0.3,
    van: g('van') * 0.6 + g('minibus'),
    delivery: g('van') * 0.45,
    truck: g('van') * 0.22,
    bus: g('bus') + g('minibus') * 0.3,
    motorcycle: 2.5 * dry,
    scooter: 2.5 * dry,
    bicycle: 3 * dry,
  };
}

export function isBus(/** @type {string} */ kind) {
  return kind.startsWith('bus');
}

/**
 * Buses, trucks and fire engines stand taller than the lane gap: two of them passing in opposite
 * lanes are drawn one over the other, so the street holds tall vehicles in one lane at a time.
 * @param {string} kind
 */
export function isTall(kind) {
  return isBus(kind) || kind === 'truck' || kind === 'firetruck';
}

export class TrafficManager {
  /**
   * @param {{lanes: Array<{id:string,row:number,direction:number}>, catalogue:any, worldWidth:number, rng:() => number,
   *   pixelsPerMetre?:number, crosswalk?:{x:number,w:number}, shelterX?:number}} options
   */
  constructor(options) {
    this.lanes = options.lanes;
    this.catalogue = options.catalogue || { vehicles: {} };
    this.worldWidth = options.worldWidth;
    this.rng = options.rng;
    this.ppm = options.pixelsPerMetre ?? 28;
    this.crosswalk = options.crosswalk || null;
    this.shelterX = options.shelterX ?? null;
    /** @type {any[]} */
    this.vehicles = [];
    /** @type {Map<string, number>} */
    this.timers = new Map(this.lanes.map((l) => [l.id, 0]));
    this.clock = 0;
    this.serial = 0;
    this.crosswalkBusy = false;
    this.waitingAtShelter = 0;
    /** @type {any} */
    this.busAtShelter = null;
  }

  /** The lane by the building, where buses serve the shelter. */
  get shelterLane() {
    return this.lanes.reduce((a, b) => (a.row < b.row ? a : b));
  }

  /** @param {string} kind */
  has(kind) {
    return Boolean(this.catalogue.vehicles?.[kind]);
  }

  /** @param {string} kind */
  lengthPx(kind) {
    const v = this.catalogue.vehicles?.[kind];
    return v ? Number(v.length_m) * this.ppm : 120;
  }

  /** @param {string} kind */
  cruise(kind) {
    const base = isBus(kind) ? 62 : kind === 'truck' || kind === 'firetruck' ? 70 : kind === 'bicycle' ? 42 : kind === 'scooter' ? 58 : kind === 'motorcycle' ? 115 : 92;
    return base * (0.88 + this.rng() * 0.24);
  }

  /**
   * @param {string} kind
   * @param {{id:string,row:number,direction:number}} lane
   * @param {{siren?:boolean, stopAtShelter?:boolean}} [options]
   */
  spawn(kind, lane, options = {}) {
    if (!this.has(kind)) return null;
    if (isTall(kind) && this.tallElsewhere(lane.id)) return null;
    const length = this.lengthPx(kind);
    const x = lane.direction > 0 ? -length / 2 - 8 : this.worldWidth + length / 2 + 8;
    for (const v of this.vehicles) {
      if (v.lane === lane.id && Math.abs(v.x - x) < (v.length + length) / 2 + 36) return null;
    }
    const cruise = options.siren ? 150 : this.cruise(kind);
    const vehicle = {
      id: (this.serial += 1),
      kind,
      lane: lane.id,
      row: lane.row,
      dir: lane.direction,
      x,
      length,
      speed: cruise,
      cruise,
      wheel: 0,
      siren: Boolean(options.siren),
      stopAtShelter: Boolean(options.stopAtShelter),
      served: false,
      stopUntil: 0,
    };
    this.vehicles.push(vehicle);
    return vehicle;
  }

  /** Whether a tall vehicle is on the street in another lane than this one. @param {string} laneId */
  tallElsewhere(laneId) {
    return this.vehicles.some((v) => v.lane !== laneId && isTall(v.kind));
  }

  /** Pick a kind for the hour and the weather, choosing a bus livery when a bus comes up. @param {any} rhythm @param {any} [fx] */
  pickKind(rhythm, fx) {
    let kind = weightedChoice(vehicleMix(rhythm.vehicles, fx), this.rng);
    if (kind === 'bus') kind = weightedChoice(BUS_LIVERIES, this.rng);
    return this.has(kind) ? kind : 'sedan';
  }

  /** @param {string} eventId */
  spawnForEvent(eventId) {
    if (eventId === 'bus_arrives') {
      return this.spawn(weightedChoice(BUS_LIVERIES, this.rng), this.shelterLane, { stopAtShelter: true });
    }
    const kind = /** @type {Record<string,string>} */ (EMERGENCY)[eventId];
    if (!kind) return null;
    const lane = this.lanes[Math.floor(this.rng() * this.lanes.length)];
    return this.spawn(kind, lane, { siren: true });
  }

  /**
   * @param {number} dt
   * @param {{hour:number, day:number, effects:{rain:number, snow:number, wet:number, fog:number}}} context
   */
  update(dt, context) {
    this.clock += dt;
    const rhythm = dailyRhythm(context.hour, context.day);
    const fx = context.effects;
    const density = trafficDensity(rhythm, fx);
    for (const lane of this.lanes) {
      const t = (this.timers.get(lane.id) ?? 0) - dt;
      if (t <= 0) {
        this.timers.set(lane.id, 2.2 + (1 - density) * 7 + this.rng() * 3);
        if (this.rng() < 0.25 + density * 0.75) {
          const kind = this.pickKind(rhythm, fx);
          this.spawn(isTall(kind) && this.tallElsewhere(lane.id) ? 'sedan' : kind, lane);
        }
      } else {
        this.timers.set(lane.id, t);
      }
    }
    const slow = 1 - fx.wet * 0.12 - fx.snow * 0.3 - fx.fog * 0.15;
    const sirens = this.vehicles.filter((v) => v.siren);
    this.busAtShelter = null;
    for (const lane of this.lanes) {
      const list = this.vehicles.filter((v) => v.lane === lane.id).sort((a, b) => (b.x - a.x) * lane.direction);
      for (let i = 0; i < list.length; i += 1) {
        const v = list[i];
        const leader = i > 0 ? list[i - 1] : null;
        let target = v.siren ? v.cruise : v.cruise * slow;
        if (!v.siren && sirens.some((s) => Math.abs(s.x - v.x) < 420)) target *= 0.45;
        if (this.shelterX !== null && lane.id === this.shelterLane.id && isBus(v.kind) && !v.served) {
          const wants = v.stopAtShelter || this.waitingAtShelter > 0;
          const ahead = (this.shelterX - v.x) * v.dir;
          if (wants && ahead > -4 && ahead < 180) {
            target = Math.min(target, Math.max(0, ahead * 0.9));
            if (ahead < 6 && v.speed < 8) {
              v.served = true;
              v.stopUntil = this.clock + 5 + this.rng() * 3;
            }
          }
        }
        if (v.stopUntil > this.clock) {
          target = 0;
          if (isBus(v.kind)) this.busAtShelter = v;
        }
        if (this.crosswalk && this.crosswalkBusy && !v.siren) {
          const edge = v.dir > 0 ? this.crosswalk.x - 10 : this.crosswalk.x + this.crosswalk.w + 10;
          const nose = v.x + (v.dir * v.length) / 2;
          const gap = (edge - nose) * v.dir;
          if (gap > -6 && gap < 160) target = Math.min(target, Math.max(0, gap * 1.2));
        }
        if (leader) {
          const gap = (leader.x - v.x) * v.dir - (leader.length + v.length) / 2;
          const safe = 16 + v.speed * 0.55;
          if (gap < safe) target = Math.min(target, Math.max(0, leader.speed * Math.max(0, gap - 6) / safe));
        }
        const delta = target - v.speed;
        v.speed += Math.max(-300 * dt, Math.min(100 * dt, delta));
        v.speed = Math.max(0, v.speed);
        v.x += v.speed * v.dir * dt;
        if (leader) {
          const limit = leader.x - v.dir * ((leader.length + v.length) / 2 + 4);
          if ((v.x - limit) * v.dir > 0) {
            v.x = limit;
            v.speed = Math.min(v.speed, leader.speed);
          }
        }
        v.wheel = (v.wheel + (v.speed * dt) / 18) % 3;
      }
    }
    this.vehicles = this.vehicles.filter((v) => {
      const margin = v.length / 2 + 20;
      return v.dir > 0 ? v.x < this.worldWidth + margin : v.x > -margin;
    });
  }

  /** Vehicles in painting order: the far lane first, then nearer lanes. */
  paintOrder() {
    const rows = new Map(this.lanes.map((l) => [l.id, l.row]));
    return [...this.vehicles].sort((a, b) => (rows.get(a.lane) ?? 0) - (rows.get(b.lane) ?? 0) || a.x - b.x);
  }
}
