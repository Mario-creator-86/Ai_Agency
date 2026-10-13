import { DEFAULT_PLACE, studioPlace, studioTime } from './office_clock.js';

/**
 * TimeOfDayManager: where the sun is over the studio right now, and what that means for the scene.
 *
 * Day and night are not an hour table: the sun's elevation is computed for the real date and
 * place, so a December afternoon is dark at five and a June evening is still light at nine. The
 * scene reads three numbers from it — daylight (0 night .. 1 full day), dusk (how warm the
 * horizon is) and a phase name the random events are allowed or forbidden by.
 */

/**
 * The first studio's place, kept as the fallback: the page draws the place the snapshot names
 * (office_clock.js setStudioPlace), and this one only when it names none.
 */
export const BUCHAREST = { lat: DEFAULT_PLACE.lat, lon: DEFAULT_PLACE.lon, timeZone: DEFAULT_PLACE.timeZone };

const RAD = Math.PI / 180;

/**
 * Solar elevation in degrees (NOAA's simplified solar position), good to a fraction of a degree.
 * @param {Date} date
 * @param {number} [lat]
 * @param {number} [lon]
 */
export function solarElevation(date, lat = studioPlace().lat, lon = studioPlace().lon) {
  const n = date.getTime() / 86400000 + 2440587.5 - 2451545.0;
  const meanLongitude = (280.46 + 0.9856474 * n) % 360;
  const anomaly = ((357.528 + 0.9856003 * n) % 360) * RAD;
  const lambda = (meanLongitude + 1.915 * Math.sin(anomaly) + 0.02 * Math.sin(2 * anomaly)) * RAD;
  const epsilon = (23.439 - 0.0000004 * n) * RAD;
  const declination = Math.asin(Math.sin(epsilon) * Math.sin(lambda));
  const rightAscension = Math.atan2(Math.cos(epsilon) * Math.sin(lambda), Math.cos(lambda));
  const gmstHours = (((18.697374558 + 24.06570982441908 * n) % 24) + 24) % 24;
  const hourAngle = (gmstHours * 15 + lon) * RAD - rightAscension;
  const elevation = Math.asin(
    Math.sin(lat * RAD) * Math.sin(declination) + Math.cos(lat * RAD) * Math.cos(declination) * Math.cos(hourAngle),
  );
  return elevation / RAD;
}

/** @param {number} a @param {number} b @param {number} x */
export function smoothstep(a, b, x) {
  const t = Math.min(1, Math.max(0, (x - a) / (b - a)));
  return t * t * (3 - 2 * t);
}

/**
 * The scene's reading of a moment.
 * @param {Date} date
 * @param {{lat:number, lon:number, timeZone?: string}} [location] the studio's place when not given
 */
export function timeOfDay(date, location = studioPlace()) {
  const clock = studioTime(date, location.timeZone || studioPlace().timeZone);
  const elevation = solarElevation(date, location.lat, location.lon);
  const daylight = smoothstep(-8, 7, elevation);
  const dusk = Math.exp(-(((elevation - 1) / 6.5) ** 2));
  let phase = 'day';
  if (elevation < -8) phase = 'night';
  else if (elevation < 7) phase = clock.hour < 12 ? 'dawn' : 'dusk';
  return { date, text: clock.text, hour: clock.hour, day: clock.day, ymd: clock.ymd, elevation, daylight, dusk, phase, night: phase === 'night' };
}

export class TimeOfDayManager {
  /**
   * The scene is lit by the real sun over the studio's place, always. It once had a second mode that held
   * the office at the dusk of the 2026-09-13 reference picture whatever the hour; the Owner ruled
   * on 2026-09-18/19 that the sky and the light follow the real outside conditions, never "always
   * dusk", so that mode is gone and there is nothing left to switch back on.
   * @param {{now?: () => Date, location?: {lat:number, lon:number, timeZone?: string}}} [options] without a
   *   location the manager follows the studio's place, read again on every update, so a snapshot
   *   that arrives after the scene was built still moves the sun
   */
  constructor(options = {}) {
    this.now = options.now || (() => new Date());
    this.fixedLocation = options.location || null;
    this.state = timeOfDay(this.now(), this.location);
    this._elapsed = 0;
  }

  /** The place the sun is computed for: the one given, else the studio's. */
  get location() {
    return this.fixedLocation || studioPlace();
  }

  /**
   * Advance the clock: once a second the moment is read again from the real clock. The street's
   * rhythm, the random events and the light all follow it.
   * @param {number} dt seconds
   */
  update(dt) {
    this._elapsed += dt;
    if (this._elapsed >= 1) {
      this._elapsed = 0;
      this.state = timeOfDay(this.now(), this.location);
    }
    return this.state;
  }
}

/** @param {string} hex */
export function hexToRgb(hex) {
  const h = hex.replace('#', '');
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}

/** @param {string} a @param {string} b @param {number} t */
export function mixHex(a, b, t) {
  const x = hexToRgb(a);
  const y = hexToRgb(b);
  const k = Math.min(1, Math.max(0, t));
  const c = x.map((v, i) => Math.round(v + (y[i] - v) * k));
  return `#${c.map((v) => v.toString(16).padStart(2, '0')).join('')}`;
}

const SKY = {
  night: ['#070b1a', '#0f1630', '#1a2244', '#232a4a'],
  dusk: ['#1b2644', '#3b4a7c', '#d0806c', '#7a5c70'],
  day: ['#3f78c8', '#79a9e0', '#cfe2f3', '#b9cde2'],
  overcastDay: ['#8a93a3', '#a3abb8', '#c4c9d2', '#b3b9c3'],
  overcastNight: ['#15171f', '#1d2029', '#2a2d38', '#262933'],
};

/**
 * Sky gradient stops (top, upper, horizon, below horizon) for the time and the weather.
 * @param {{daylight:number, dusk:number}} time
 * @param {{cloudiness:number, fog:number}} weather
 */
export function skyStops(time, weather) {
  const pick = (/** @type {number} */ i) => {
    const base = mixHex(SKY.night[i], SKY.day[i], time.daylight);
    const warm = mixHex(base, SKY.dusk[i], Math.min(1, time.dusk * 0.95));
    const grey = mixHex(SKY.overcastNight[i], SKY.overcastDay[i], time.daylight);
    return mixHex(warm, grey, Math.min(0.85, weather.cloudiness * 0.75 + weather.fog * 0.5));
  };
  // The warm band sits behind the tower tops, where the reference's sunset glow is.
  return [
    [0, pick(0)],
    [0.24, pick(1)],
    [0.4, pick(2)],
    [0.62, pick(3)],
  ];
}
