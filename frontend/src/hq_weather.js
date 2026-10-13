/**
 * WeatherManager: the live Bucharest weather, read through the studio's own backend.
 *
 * The page may only talk to its own origin (CSP connect-src 'self'), so the backend fetches the
 * observation and this manager polls `/api/v1/office/weather`. When the backend has no weather
 * configured or cannot reach the service, the scene shows no weather at all and the label says
 * the weather is unavailable: rain that is not falling is never drawn.
 */

export const CONDITIONS = ['clear', 'partly_cloudy', 'cloudy', 'fog', 'drizzle', 'rain', 'snow', 'storm'];

/** The weather's sign on the glass, by day and by night (glossary W25: no sun in a night's sign). */
const SIGNS = {
  day: { clear: '☀', partly_cloudy: '⛅', cloudy: '☁', fog: '🌫', drizzle: '🌦', rain: '🌧', snow: '❄', storm: '⛈' },
  night: { clear: '☾', partly_cloudy: '☁', cloudy: '☁', fog: '🌫', drizzle: '🌧', rain: '🌧', snow: '❄', storm: '⛈' },
};

/**
 * The sign before the weather's name (W25): the observation's own day or night (`is_day`), and when
 * the studio does not say, the real sun (above -0.833 deg, the horizon with refraction). At 03:00
 * the glass read «☀ Senin», a sun over a night with none. '' for an unknown weather.
 * @param {string} condition @param {boolean|null|undefined} isDay @param {number} elevation degrees
 */
export function weatherSign(condition, isDay, elevation) {
  const day = typeof isDay === 'boolean' ? isDay : !(Number.isFinite(elevation) && elevation < -0.833);
  const signs = /** @type {Record<string, string>} */ (day ? SIGNS.day : SIGNS.night);
  return Object.prototype.hasOwnProperty.call(signs, condition) ? signs[condition] : '';
}

/** @param {any} data */
export function normalizeWeather(data) {
  if (!data || data.available !== true || !CONDITIONS.includes(data.condition)) {
    return {
      available: false,
      condition: 'unknown',
      intensity: 0,
      temperatureC: null,
      windKph: null,
      isDay: null,
      observedAt: null,
      reason: (data && data.reason) || 'unavailable',
    };
  }
  const number = (/** @type {any} */ v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
  return {
    available: true,
    condition: data.condition,
    intensity: Math.min(1, Math.max(0, number(data.intensity) ?? 0.5)),
    temperatureC: number(data.temperature_c),
    windKph: number(data.wind_kph),
    isDay: typeof data.is_day === 'boolean' ? data.is_day : null,
    observedAt: typeof data.observed_at === 'string' ? data.observed_at : null,
    reason: null,
  };
}

/**
 * What the scene draws for a weather state. All zero when the weather is unknown.
 * @param {ReturnType<typeof normalizeWeather>} w
 */
export function weatherEffects(w) {
  const none = { cloudiness: 0, rain: 0, snow: 0, fog: 0, storm: false, wet: 0, wind: 0 };
  if (!w.available) return none;
  const k = w.intensity;
  const wind = Math.min(1, (w.windKph ?? 0) / 50);
  switch (w.condition) {
    case 'clear':
      return { ...none, cloudiness: 0.05, wind };
    case 'partly_cloudy':
      return { ...none, cloudiness: 0.35 + 0.2 * k, wind };
    case 'cloudy':
      return { ...none, cloudiness: 0.75 + 0.25 * k, wind };
    case 'fog':
      return { ...none, cloudiness: 0.6, fog: 0.45 + 0.45 * k, wet: 0.2, wind };
    case 'drizzle':
      return { ...none, cloudiness: 0.8, rain: 0.2 + 0.2 * k, wet: 0.6, wind };
    case 'rain':
      return { ...none, cloudiness: 0.9, rain: 0.45 + 0.55 * k, wet: 1, wind };
    case 'snow':
      return { ...none, cloudiness: 0.85, snow: 0.35 + 0.65 * k, wet: 0.3, wind };
    case 'storm':
      return { ...none, cloudiness: 1, rain: 0.85, wet: 1, storm: true, wind: Math.max(wind, 0.6) };
    default:
      return none;
  }
}

/** What the scene draws for a weather it does not know: nothing (the replay of a past day, W15). */
export const NO_WEATHER = Object.freeze(weatherEffects(normalizeWeather(null)));

export const WEATHER_LABELS = {
  clear: 'Senin',
  partly_cloudy: 'Parțial înnorat',
  cloudy: 'Înnorat',
  fog: 'Ceață',
  drizzle: 'Burniță',
  rain: 'Ploaie',
  snow: 'Ninsoare',
  storm: 'Furtună',
  unknown: 'Vremea indisponibilă',
};

export class WeatherManager {
  /**
   * @param {() => Promise<any>} fetchWeather
   * @param {{refreshMs?: number}} [options]
   */
  constructor(fetchWeather, options = {}) {
    this.fetchWeather = fetchWeather;
    this.refreshMs = options.refreshMs ?? 10 * 60 * 1000;
    this.state = normalizeWeather(null);
    this.state.reason = 'loading';
    this.effects = weatherEffects(this.state);
    this._last = -Infinity;
    this._pending = false;
  }

  async refresh() {
    try {
      this.state = normalizeWeather(await this.fetchWeather());
    } catch {
      this.state = normalizeWeather({ available: false, reason: 'unreachable' });
    }
    this.effects = weatherEffects(this.state);
    return this.state;
  }

  /**
   * Read the weather now, and count the regular refresh from here. The street is dressed for the
   * first reading (umbrellas, fewer walkers) before anyone sees it.
   * @param {number} nowMs
   */
  first(nowMs) {
    this._last = nowMs;
    this._pending = true;
    return this.refresh().finally(() => {
      this._pending = false;
    });
  }

  /** @param {number} nowMs */
  update(nowMs) {
    if (this._pending || nowMs - this._last < this.refreshMs) return;
    this._last = nowMs;
    this._pending = true;
    this.refresh().finally(() => {
      this._pending = false;
    });
  }

  label() {
    const s = this.state;
    const name = WEATHER_LABELS[/** @type {keyof typeof WEATHER_LABELS} */ (s.condition)] || WEATHER_LABELS.unknown;
    return s.available && s.temperatureC !== null ? `${name} ${Math.round(s.temperatureC)}°C` : name;
  }
}
