import { dailyRhythm, weightedChoice } from './street_schedule.js';

/**
 * PedestrianManager: the people on the pavement in front of the headquarters.
 *
 * How many there are and what they do follows the city's daily rhythm and the live weather
 * (fewer and faster in rain, umbrellas up). People walk in from one edge and out at the other;
 * commuters wait at the shelter and board the bus that stops there; now and then a group crosses
 * at the zebra and the traffic waits. They are scenery: no person here stands for studio data.
 */

const UMBRELLAS = ['#1f2937', '#b91c1c', '#1d4ed8', '#047857', '#7c3aed', '#f59e0b', '#0f766e'];

export class PedestrianManager {
  /**
   * @param {{rows:{far:number, near:number}, crosswalk?:{x:number,w:number}, road?:{top:number,bottom:number},
   *   nearWalkRow?:number, shelterX?:number, worldWidth:number, sheets:string[], rng:() => number}} options
   */
  constructor(options) {
    this.rows = options.rows;
    this.crosswalk = options.crosswalk || null;
    this.road = options.road || null;
    this.nearWalkRow = options.nearWalkRow ?? null;
    this.shelterX = options.shelterX ?? null;
    this.worldWidth = options.worldWidth;
    this.sheets = options.sheets;
    this.rng = options.rng;
    /** @type {any[]} */
    this.people = [];
    this.clock = 0;
    this.serial = 0;
    this._spawnTimer = 0;
    this.maxPeople = 18;
  }

  get crosswalkBusy() {
    return this.people.some((p) => p.state === 'cross' && this.road && p.row > this.road.top - 14 && p.row < this.road.bottom + 10);
  }

  get waitingAtShelter() {
    return this.people.filter((p) => p.state === 'wait').length;
  }

  /**
   * @param {{activity?:string, dir?:number, x?:number, row?:number, speed?:number, sheet?:string, umbrella?:boolean}} [options]
   */
  spawn(options = {}) {
    if (!this.sheets.length) return null;
    const dir = options.dir ?? (this.rng() < 0.5 ? 1 : -1);
    const onFar = this.rng() < 0.5;
    const row = options.row ?? (onFar ? this.rows.far : this.rows.near) + (this.rng() - 0.5) * 4;
    const activity = options.activity || 'walk';
    const run = activity === 'run';
    const person = {
      id: (this.serial += 1),
      sheet: options.sheet || this.sheets[Math.floor(this.rng() * this.sheets.length)],
      row,
      x: options.x ?? (dir > 0 ? -20 : this.worldWidth + 20),
      dir,
      speed: options.speed ?? (run ? 62 + this.rng() * 18 : 24 + this.rng() * 12),
      activity,
      state: 'walk',
      frame: this.rng() * 8,
      until: 0,
      umbrella: options.umbrella ? UMBRELLAS[Math.floor(this.rng() * UMBRELLAS.length)] : null,
      react: 0,
    };
    if (activity === 'commute' && this.shelterX !== null) person.goal = this.shelterX + (this.rng() - 0.5) * 50;
    this.people.push(person);
    return person;
  }

  /** A few people cross the road at the zebra. */
  startCrossing() {
    if (!this.crosswalk || !this.road || this.nearWalkRow === null) return;
    const count = 1 + Math.floor(this.rng() * 3);
    for (let i = 0; i < count; i += 1) {
      const p = this.spawn({ x: this.crosswalk.x + 30 + this.rng() * (this.crosswalk.w - 60), row: this.rows.far + 2 });
      if (!p) continue;
      p.state = 'cross';
      p.crossDelay = i * 0.6;
      p.speed = 22 + this.rng() * 6;
    }
  }

  /** @param {number} count */
  startJoggers(count = 3) {
    const dir = this.rng() < 0.5 ? 1 : -1;
    for (let i = 0; i < count; i += 1) {
      this.spawn({ activity: 'run', dir, x: dir > 0 ? -30 - i * 26 : this.worldWidth + 30 + i * 26, row: this.rows.near + (i % 2) * 3, speed: 70 });
    }
  }

  /** @param {number} seconds */
  reactAll(seconds) {
    for (const p of this.people) if (p.state !== 'cross') p.react = seconds * (0.6 + this.rng() * 0.4);
  }

  /**
   * @param {number} dt
   * @param {{hour:number, day:number, effects:{rain:number, snow:number, storm:boolean}, busAtShelter:any}} context
   */
  update(dt, context) {
    this.clock += dt;
    const rhythm = dailyRhythm(context.hour, context.day);
    const fx = context.effects;
    const target = Math.min(this.maxPeople, Math.round(rhythm.people * (1 - fx.rain * 0.5) * (1 - fx.snow * 0.35) * (fx.storm ? 0.3 : 1)));
    this._spawnTimer -= dt;
    if (this._spawnTimer <= 0) {
      this._spawnTimer = 1.5 + this.rng() * 3.5;
      const walking = this.people.filter((p) => p.state !== 'board').length;
      if (walking < target) {
        const activity = weightedChoice(rhythm.activities, this.rng);
        const umbrella = fx.rain > 0.15 && this.rng() < 0.8;
        if (activity === 'friends') {
          const dir = this.rng() < 0.5 ? 1 : -1;
          const row = this.rows.near;
          for (let i = 0; i < 2; i += 1) this.spawn({ dir, row: row + i * 3, x: dir > 0 ? -20 - i * 18 : this.worldWidth + 20 + i * 18, umbrella });
        } else {
          this.spawn({ activity: activity === 'run' ? 'run' : activity === 'commute' ? 'commute' : 'walk', umbrella });
        }
      }
    }
    const rainPace = 1 + fx.rain * 0.35;
    for (const p of this.people) {
      if (p.react > 0) {
        p.react -= dt;
        continue;
      }
      if (p.state === 'cross') {
        if ((p.crossDelay ?? 0) > 0) {
          p.crossDelay -= dt;
          continue;
        }
        p.row += p.speed * 0.55 * dt;
        p.frame = (p.frame + dt * 9) % 8;
        if (this.nearWalkRow !== null && p.row >= this.nearWalkRow + 30) p.gone = true;
        continue;
      }
      if (p.state === 'wait') {
        if (context.busAtShelter && Math.abs(context.busAtShelter.x - p.x) < 90) {
          p.state = 'board';
          p.gone = true;
        } else if (this.clock > p.until) {
          p.state = 'walk';
        }
        continue;
      }
      if (p.goal !== undefined && p.state === 'walk' && Math.abs(p.goal - p.x) < 3) {
        p.state = 'wait';
        p.until = this.clock + 50 + this.rng() * 40;
        p.goal = undefined;
        continue;
      }
      if (p.goal !== undefined) p.dir = Math.sign(p.goal - p.x) || p.dir;
      p.x += p.dir * p.speed * rainPace * dt;
      p.frame = (p.frame + dt * (p.activity === 'run' ? 14 : 8)) % 8;
      if (p.x < -40 || p.x > this.worldWidth + 40) p.gone = true;
    }
    this.people = this.people.filter((p) => !p.gone);
  }

  /** Far pavement first, so people nearer the road are painted over those behind them. */
  paintOrder() {
    return [...this.people].sort((a, b) => a.row - b.row);
  }
}
