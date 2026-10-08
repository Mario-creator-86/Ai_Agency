import { studioTime } from './office_clock.js';
import { timeOfDay } from './hq_time.js';
import { normalizeWeather, weatherEffects, WEATHER_LABELS } from './hq_weather.js';
import { PIXEL_LAYOUT } from './pixel_desks.js';

export const OUTDOORS = PIXEL_LAYOUT.outdoors;
const W = PIXEL_LAYOUT.world.width;
const H = PIXEL_LAYOUT.world.height;

/** Fresh provider data only. A replay has no observed historical weather.
 * @param {any} state
 * @param {number} receivedAt
 * @param {number} now
 * @param {string|null} [observedUtc]
 */
export function outdoorWeather(state, receivedAt, now, observedUtc = null, replay = false) {
  const observed = typeof observedUtc === 'string' ? Date.parse(observedUtc) : NaN;
  const expired = !Number.isFinite(receivedAt) || receivedAt <= 0
    || now - receivedAt > OUTDOORS.weather_max_age_ms
    || (Number.isFinite(observed) && (now - observed > OUTDOORS.weather_max_age_ms || observed - now > OUTDOORS.weather_future_tolerance_ms));
  if (replay || expired || !state?.available) return normalizeWeather(null);
  return state;
}

/** Quantised once per minute: time stays real without a distracting second-hand loop. */
export function outdoorMoment(date = new Date(), location) {
  const minute = new Date(Math.floor(date.getTime() / 60000) * 60000);
  return timeOfDay(minute, location);
}

export function outdoorsAt(x, y, regions = OUTDOORS.interiors) {
  return !regions.some(r => x >= r.x && x <= r.x + r.width && y >= r.y && y <= r.y + r.height);
}

function exteriorClip(ctx, regions = OUTDOORS.interiors) {
  ctx.beginPath();
  ctx.rect(0, 0, W, H);
  for (const r of regions) ctx.rect(r.x, r.y, r.width, r.height);
  ctx.clip('evenodd');
}

/** Recolour only the outside of the existing illustration; indoor furniture stays intact. */
export function drawOutdoorLight(ctx, moment, weather) {
  const p = OUTDOORS.palette;
  const effects = weatherEffects(weather);
  const night = 1 - moment.daylight;
  const day = moment.daylight * (1 - moment.dusk);
  ctx.save();
  exteriorClip(ctx);
  ctx.globalCompositeOperation = 'multiply';
  ctx.fillStyle = '#53618f';
  ctx.globalAlpha = night * 0.75;
  ctx.fillRect(0, 0, W, H);
  ctx.globalCompositeOperation = 'source-over';
  ctx.globalAlpha = night * 0.36;
  ctx.fillStyle = '#171d3f';
  ctx.fillRect(0, 0, W, H);
  ctx.globalAlpha = day * 0.08;
  ctx.fillStyle = '#eceddf';
  ctx.fillRect(0, 0, W, H);
  ctx.globalAlpha = effects.cloudiness * 0.12;
  ctx.fillStyle = '#63678b';
  ctx.fillRect(0, 0, W, H);
  // Existing exterior lamps keep a modest warm halo when the actual sun is down.
  ctx.globalCompositeOperation = 'screen';
  for (const lamp of OUTDOORS.lamps) {
    for (let radius = 18; radius > 0; radius -= 3) {
      ctx.globalAlpha = night * 0.018;
      ctx.fillStyle = p.gold;
      pixelDisc(ctx, lamp.x, lamp.y, radius);
    }
    ctx.globalAlpha = night * 0.8;
    ctx.fillStyle = p.gold;
    ctx.fillRect(lamp.x - 2, lamp.y - 4, 4, 9);
    ctx.fillStyle = p.cream;
    ctx.fillRect(lamp.x - 1, lamp.y - 3, 2, 6);
  }
  ctx.restore();
}

function pixelDisc(ctx, x, y, radius) {
  for (let row = -radius; row <= radius; row++) {
    const half = Math.floor(Math.sqrt(Math.max(0, radius * radius - row * row)));
    ctx.fillRect(Math.round(x) - half, Math.round(y) + row, half * 2 + 1, 1);
  }
}

function pixelLine(ctx, x0, y0, x1, y1, width = 1) {
  let x = Math.round(x0), y = Math.round(y0);
  const endX = Math.round(x1), endY = Math.round(y1);
  const dx = Math.abs(endX - x), dy = -Math.abs(endY - y);
  const sx = x < endX ? 1 : -1, sy = y < endY ? 1 : -1;
  let error = dx + dy;
  for (;;) {
    ctx.fillRect(x, y, width, width);
    if (x === endX && y === endY) break;
    const twice = error * 2;
    if (twice >= dy) { error += dy; x += sx; }
    if (twice <= dx) { error += dx; y += sy; }
  }
}

const GLYPHS = {
  '0': ['111', '101', '101', '101', '111'], '1': ['010', '110', '010', '010', '111'],
  '2': ['111', '001', '111', '100', '111'], '3': ['111', '001', '111', '001', '111'],
  '4': ['101', '101', '111', '001', '001'], '5': ['111', '100', '111', '001', '111'],
  '6': ['111', '100', '111', '101', '111'], '7': ['111', '001', '010', '010', '010'],
  '8': ['111', '101', '111', '101', '111'], '9': ['111', '101', '111', '001', '111'],
  ':': ['0', '1', '0', '1', '0'], A: ['010', '101', '111', '101', '101'],
  M: ['101', '111', '111', '101', '101'], N: ['101', '111', '111', '111', '101'],
};

function bitmapText(ctx, text, x, y, scale = 1) {
  let cursor = x;
  for (const letter of text) {
    const glyph = GLYPHS[letter];
    if (!glyph) continue;
    glyph.forEach((row, dy) => Array.from(row).forEach((bit, dx) => {
      if (bit === '1') ctx.fillRect(cursor + dx * scale, y + dy * scale, scale, scale);
    }));
    cursor += (glyph[0].length + 1) * scale;
  }
}

/** Brass street clock, rasterised in scene pixels. Both displays use the same local instant. */
export function drawOutdoorClock(ctx, date = new Date(), timeZone) {
  const { x, y, radius, base_y: base } = OUTDOORS.clock;
  const p = OUTDOORS.palette;
  const reading = studioTime(date, timeZone);
  const [hour, minute] = reading.text.split(':').map(Number);
  ctx.save();
  ctx.fillStyle = '#15203260'; ctx.fillRect(x - 18, base + 6, 40, 3);
  ctx.fillStyle = p.iron; ctx.fillRect(x - 4, y + radius, 9, base - y - radius);
  ctx.fillRect(x - 11, base - 4, 23, 9); ctx.fillRect(x - 15, base + 3, 31, 3);
  ctx.fillStyle = p.iron_light; ctx.fillRect(x - 2, y + radius, 2, base - y - radius - 5);
  ctx.fillStyle = p.gold; ctx.fillRect(x - 5, base - 8, 11, 2);
  ctx.fillStyle = p.bronze; pixelDisc(ctx, x + 1, y + 2, radius + 3);
  ctx.fillStyle = p.iron; pixelDisc(ctx, x, y, radius + 2);
  ctx.fillStyle = p.gold; pixelDisc(ctx, x, y, radius);
  ctx.fillStyle = p.bronze; pixelDisc(ctx, x, y, radius - 2);
  ctx.fillStyle = p.cream; pixelDisc(ctx, x, y, radius - 4);
  ctx.fillStyle = p.gold;
  ctx.fillRect(x - 2, y - radius - 9, 5, 7); ctx.fillRect(x - 4, y - radius - 6, 9, 2);
  ctx.fillStyle = p.ink;
  for (let tick = 0; tick < 12; tick++) {
    const angle = tick * Math.PI / 6;
    ctx.fillRect(Math.round(x + Math.sin(angle) * (radius - 7)) - 1,
      Math.round(y - Math.cos(angle) * (radius - 7)) - 1, 2, 2);
  }
  const hand = (angle, length, width) => pixelLine(ctx, x, y,
    x + Math.sin(angle) * length, y - Math.cos(angle) * length, width);
  hand(((hour % 12) + minute / 60) * Math.PI / 6, radius * 0.42, 2);
  hand(minute * Math.PI / 30, radius * 0.65, 1);
  ctx.fillStyle = p.gold; pixelDisc(ctx, x, y, 2);
  ctx.fillStyle = p.bronze; bitmapText(ctx, 'AMN', x - 5, y + 6);
  ctx.fillStyle = p.bronze; ctx.fillRect(x - 28, y + radius + 5, 57, 20);
  ctx.fillStyle = p.gold; ctx.fillRect(x - 27, y + radius + 6, 55, 18);
  ctx.fillStyle = p.iron; ctx.fillRect(x - 25, y + radius + 8, 51, 14);
  ctx.fillStyle = p.cream; bitmapText(ctx, reading.text, x - 17, y + radius + 10, 2);
  ctx.restore();
  return reading.text;
}

/** Original, bounded pixel particles. No rain, snow or fog reaches an interior rectangle. */
export function drawOutdoorWeather(ctx, weather, elapsedMs = 0) {
  const effect = weatherEffects(weather);
  if (!weather.available) return;
  const p = OUTDOORS.palette;
  ctx.save();
  exteriorClip(ctx);
  if (effect.wet && effect.rain) {
    ctx.fillStyle = p.rain; ctx.globalAlpha = 0.1 * effect.wet;
    for (let i = 0; i < 18; i++) ctx.fillRect(17 + i * 53, 570 + (i % 4) * 7, 14 + i % 17, 1);
  }
  if (effect.fog) {
    ctx.fillStyle = p.fog;
    for (let band = 0; band < 14; band++) {
      ctx.globalAlpha = effect.fog * (0.07 + band / 150);
      const drift = Math.round(Math.sin(elapsedMs / 11000 + band) * 18);
      ctx.fillRect(drift - 20, 145 + band * 31, W + 40, 38);
    }
  }
  if (effect.rain) {
    ctx.fillStyle = p.rain;
    const count = Math.ceil(OUTDOORS.max_rain_drops * effect.rain);
    for (let i = 0; i < count; i++) {
      ctx.globalAlpha = 0.24 + (i % 4) * 0.1;
      const speed = 0.28 + (i % 3) * 0.08;
      const x = (i * 173 + elapsedMs * effect.wind * 0.035) % W;
      const y = (i * 97 + elapsedMs * speed) % H;
      pixelLine(ctx, x, y, x + 2 + effect.wind * 4, y + 6 + i % 5);
    }
  }
  if (effect.snow) {
    ctx.fillStyle = p.snow;
    const count = Math.ceil(OUTDOORS.max_snowflakes * effect.snow);
    for (let i = 0; i < count; i++) {
      ctx.globalAlpha = 0.4 + (i % 3) * 0.22;
      const x = (i * 157 + Math.sin(elapsedMs / 2200 + i) * 12 + W) % W;
      const y = (i * 83 + elapsedMs * (0.024 + (i % 4) * 0.013)) % H;
      ctx.fillRect(Math.round(x), Math.round(y), 2, 2);
      if (i % 5 === 0) { ctx.fillRect(Math.round(x) - 1, Math.round(y) + 1, 4, 1); }
    }
  }
  ctx.restore();
}

export function outdoorReadout(clock, weather, replay = false) {
  if (replay) return `${clock} · Vremea de atunci: necunoscută`;
  const name = WEATHER_LABELS[weather.condition] || WEATHER_LABELS.unknown;
  const temperature = weather.available && Number.isFinite(weather.temperatureC)
    ? ` ${Math.round(weather.temperatureC)}°C` : '';
  return `${clock} · ${name}${temperature}`;
}

export function weatherMoves(weather, { live, reduced, replay, parked, hidden }) {
  const effects = weatherEffects(weather);
  return Boolean(live && !reduced && !replay && !parked && !hidden
    && weather.available && (effects.rain || effects.snow || effects.fog));
}
