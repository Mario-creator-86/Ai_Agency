import { bucharestTime } from './office_clock.js';

/**
 * TimeOfDayManager: where the sun is over Bucharest right now, and what that means for the scene.
 *
 * Day and night are not an hour table: the sun's elevation is computed for the real date and
 * place, so a December afternoon is dark at five and a June evening is still light at nine. The
 * scene reads three numbers from it — daylight (0 night .. 1 full day), dusk (how warm the
 * horizon is) and a phase name the random events are allowed or forbidden by.
 */

export const BUCHAREST = { lat: 44.4268, lon: 26.1025 };

const RAD = Math.PI / 180;

/**
 * Solar elevation in degrees (NOAA's simplified solar position), good to a fraction of a degree.
 * @param {Date} date
 * @param {number} [lat]
 * @param {number} [lon]
 */
export function solarElevation(date, lat = BUCHAREST.lat, lon = BUCHAREST.lon) {
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
 * @param {{lat:number, lon:number}} [location]
 */
export function timeOfDay(date, location = BUCHAREST) {
  const clock = bucharestTime(date);
  const elevation = solarElevation(date, location.lat, location.lon);
  const daylight = smoothstep(-8, 7, elevation);
  const dusk = Math.exp(-(((elevation - 1) / 6.5) ** 2));
  let phase = 'day';
  if (elevation < -8) phase = 'night';
  else if (elevation < 7) phase = clock.hour < 12 ? 'dawn' : 'dusk';
  return { date, text: clock.text, hour: clock.hour, day: clock.day, elevation, daylight, dusk, phase, night: phase === 'night' };
}

/** The picture's light: the sun a few degrees under the horizon. */
export const REFERENCE_DUSK_ELEVATION = -2.5;

/**
 * The moment the scene is lit by. In 'reference_dusk' the office always has the light of the
 * Owner's headquarters picture, while the clock text stays real; 'live' lights it by the real sun.
 * @param {ReturnType<typeof timeOfDay>} real
 * @param {string} mode 'live' | 'reference_dusk'
 */
export function litTime(real, mode) {
  if (mode !== 'reference_dusk') return real;
  const elevation = REFERENCE_DUSK_ELEVATION;
  return {
    ...real,
    elevation,
    daylight: smoothstep(-8, 7, elevation),
    dusk: Math.exp(-(((elevation - 1) / 6.5) ** 2)),
    phase: 'dusk',
    night: false,
    // the afterglow sits on the evening side of the sky, where the picture's sunset is
    hour: 19,
  };
}

export class TimeOfDayManager {
  /** @param {{now?: () => Date, location?: {lat:number, lon:number}, light?: string}} [options] */
  constructor(options = {}) {
    this.now = options.now || (() => new Date());
    this.location = options.location || BUCHAREST;
    this.light = options.light === 'reference_dusk' ? 'reference_dusk' : 'live';
    this.real = timeOfDay(this.now(), this.location);
    this.state = litTime(this.real, this.light);
    this._elapsed = 0;
  }

  /**
   * Advance the clock. Returns the real moment (the street's rhythm and the random events follow
   * it); `state` is the moment the scene is lit by.
   * @param {number} dt seconds
   */
  update(dt) {
    this._elapsed += dt;
    if (this._elapsed >= 1) {
      this._elapsed = 0;
      this.real = timeOfDay(this.now(), this.location);
      this.state = litTime(this.real, this.light);
    }
    return this.real;
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
