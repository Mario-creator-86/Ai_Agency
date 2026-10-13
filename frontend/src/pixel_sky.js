import { mixHex, smoothstep } from './hq_time.js';
import { weatherEffects } from './hq_weather.js';
import { PIXEL_LAYOUT } from './pixel_desks.js';

const SKY = PIXEL_LAYOUT.outdoors.sky;
const W = PIXEL_LAYOUT.world.width;
const caches = new WeakMap();

/** Stylised celestial bodies follow solar twilight, not an invented lunar ephemeris. */
export function skyAppearance(moment, weather) {
  const p = SKY.palette, effects = weatherEffects(weather);
  const warm = moment.dusk;
  const colours = p.night.map((colour, i) => mixHex(mixHex(colour, p.day[i], moment.daylight), p.dusk[i], warm));
  const cloud = mixHex(mixHex(p.cloud_night, p.cloud_day, moment.daylight), p.cloud_dusk, warm);
  const visibility = Math.max(0, 1 - effects.cloudiness * 0.8 - effects.fog * 0.7);
  return { colours, cloud, moon: (1 - smoothstep(-8, -1, moment.elevation)) * visibility,
    stars: (1 - smoothstep(-14, -5, moment.elevation)) * visibility,
    sun: smoothstep(-1.2, 0.5, moment.elevation) * visibility, cloudiness: effects.cloudiness };
}

/** Only the connected, warm sky in this illustration. Roof, plants and city stay painted. */
export function skyPixel(x, y, r, g, b) {
  const slope = Math.max(0, y - SKY.roof_y) * SKY.roof_slope;
  return y < SKY.height && (y < SKY.roof_y || x < Math.max(SKY.left_horizon_edge, SKY.left_edge - slope) || x > SKY.right_edge + slope * 0.3)
    && !PIXEL_LAYOUT.outdoors.interiors.some(region => x >= region.x && x < region.x + region.width && y >= region.y && y < region.y + region.height)
    && r > 95 && r > g + 5 && r > b * 0.82;
}

function canvasFor(ctx) {
  const canvas = ctx.canvas.ownerDocument.createElement('canvas'); canvas.width = W; canvas.height = SKY.height;
  return canvas;
}

function skyCache(ctx, background) {
  if (!background?.complete || !background.naturalWidth) return null;
  if (caches.has(background)) return caches.get(background);
  const sample = canvasFor(ctx), s = sample.getContext('2d'); s.imageSmoothingEnabled = false;
  s.drawImage(background, 0, 0, PIXEL_LAYOUT.world.width, PIXEL_LAYOUT.world.height);
  const source = s.getImageData(0, 0, W, SKY.height).data;
  const count = W * SKY.height, visited = new Uint8Array(count), queue = new Int32Array(count);
  let tail = 0;
  const visit = index => {
    if (visited[index]) return;
    visited[index] = 1;
    const i = index * 4;
    if (skyPixel(index % W, Math.floor(index / W), source[i], source[i + 1], source[i + 2])) queue[tail++] = index;
  };
  for (let x = 0; x < W; x++) visit(x);
  const mask = canvasFor(ctx), clouds = canvasFor(ctx), m = mask.getContext('2d'), c = clouds.getContext('2d');
  const pixels = m.createImageData(W, SKY.height), shades = c.createImageData(W, SKY.height);
  for (let head = 0; head < tail; head++) {
    const index = queue[head], x = index % W, i = index * 4;
    pixels.data.set([255, 255, 255, 255], i);
    // Retain the original clouds' pixel contours and varying density.
    const opacity = Math.min(255, Math.max(0, (source[i + 2] - source[i + 1] - 3) * 7));
    shades.data.set([255, 255, 255, opacity], i);
    if (x > 0) visit(index - 1); if (x < W - 1) visit(index + 1);
    if (index >= W) visit(index - W); if (index < count - W) visit(index + W);
  }
  m.putImageData(pixels, 0, 0); c.putImageData(shades, 0, 0);
  const cache = { mask, clouds, layer: canvasFor(ctx), cloudLayer: canvasFor(ctx), output: canvasFor(ctx), key: '' };
  caches.set(background, cache); return cache;
}

function disc(ctx, x, y, radius) {
  for (let row = -radius; row <= radius; row++) {
    const half = Math.floor(Math.sqrt(Math.max(0, radius * radius - row * row)));
    ctx.fillRect(Math.round(x) - half, Math.round(y) + row, half * 2 + 1, 1);
  }
}

/** Cached world-pixel layers; no image readback or masks rebuilt during animation. */
export function drawOutdoorSky(ctx, background, moment, weather, elapsed = 0) {
  const cache = skyCache(ctx, background);
  const appearance = skyAppearance(moment, weather);
  if (!cache) return appearance;
  const key = JSON.stringify([appearance, moment.elevation]);
  if (cache.key !== key) {
    const c = cache.layer.getContext('2d'); c.clearRect(0, 0, W, SKY.height);
    const gradient = c.createLinearGradient(0, 0, 0, SKY.height);
    appearance.colours.forEach((colour, i) => gradient.addColorStop(i / 2, colour));
    c.fillStyle = gradient; c.fillRect(0, 0, W, SKY.height);
    c.fillStyle = SKY.palette.star; c.globalAlpha = appearance.stars;
    for (let i = 0; i < SKY.star_count; i++) {
      const x = (i * 137 + 29) % W, y = (i * 43 + 9) % 112;
      c.fillRect(x, y, 1 + (i % 7 === 0 ? 1 : 0), 1);
      if (i % 9 === 0) { c.fillRect(x - 1, y + 1, 3, 1); c.fillRect(x, y - 1, 1, 3); }
    }
    const moon = SKY.moon;
    c.globalAlpha = appearance.moon * 0.04; c.fillStyle = SKY.palette.moon;
    for (let r = moon.radius + 12; r > moon.radius; r -= 3) disc(c, moon.x, moon.y, r);
    c.globalAlpha = appearance.moon;
    disc(c, moon.x, moon.y, moon.radius);
    c.fillStyle = SKY.palette.moon_shade;
    for (const [x, y, r] of [[-5, -3, 3], [4, 4, 2], [3, -6, 1], [-3, 6, 1]]) disc(c, moon.x + x, moon.y + y, r);
    // At dawn/dusk the sun sits near the horizon; it rises with the computed elevation.
    const sun = SKY.sun, sunY = Math.round(sun.y - Math.min(105, Math.max(0, moment.elevation) * 2));
    c.globalAlpha = appearance.sun * 0.06; c.fillStyle = '#ffd59b';
    for (let r = sun.radius + 14; r > sun.radius; r -= 4) disc(c, sun.x, sunY, r);
    c.globalAlpha = appearance.sun; c.fillStyle = '#ffe3ad'; disc(c, sun.x, sunY, sun.radius);
    c.globalAlpha = 1;
    const cloud = cache.cloudLayer.getContext('2d'); cloud.clearRect(0, 0, W, SKY.height);
    cloud.globalCompositeOperation = 'source-over'; cloud.fillStyle = appearance.cloud; cloud.fillRect(0, 0, W, SKY.height);
    cloud.globalCompositeOperation = 'destination-in'; cloud.drawImage(cache.clouds, 0, 0);
    cache.key = key;
  }
  const out = cache.output.getContext('2d'); out.clearRect(0, 0, W, SKY.height);
  out.globalCompositeOperation = 'source-over'; out.drawImage(cache.layer, 0, 0);
  const drift = Math.round(Math.sin(elapsed / PIXEL_LAYOUT.life.cloud_cycle_ms) * PIXEL_LAYOUT.life.cloud_drift_px);
  out.drawImage(cache.cloudLayer, drift, 0);
  out.globalCompositeOperation = 'destination-in'; out.drawImage(cache.mask, 0, 0); out.globalCompositeOperation = 'source-over';
  ctx.drawImage(cache.output, 0, 0); return appearance;
}
