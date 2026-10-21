import { PIXEL_LAYOUT } from './pixel_desks.js';
import { drawOutdoorLight, drawOutdoorWeather } from './pixel_environment.js';
import { drawOutdoorSky } from './pixel_sky.js';

const caches = new WeakMap();

/** Indoor plants overlap the glass. Joinery is protected by traced geometry. */
export function windowFoliagePixel(r, g, b) {
  return g > r * 1.04 && g > b * 1.05;
}

function makeCanvas(image, width, height) {
  const canvas = image.ownerDocument.createElement('canvas');
  canvas.width = width; canvas.height = height;
  return canvas;
}

function windowCache(background) {
  if (!background?.complete || !background.naturalWidth) return null;
  if (caches.has(background)) return caches.get(background);
  // Classify once at the artwork's native resolution so fine frames and foliage
  // remain the original pixels even when the scene is enlarged.
  const mask = makeCanvas(background, background.naturalWidth, background.naturalHeight);
  const m = mask.getContext('2d'); m.drawImage(background, 0, 0);
  const pixels = m.getImageData(0, 0, mask.width, mask.height);
  const sx = mask.width / PIXEL_LAYOUT.world.width, sy = mask.height / PIXEL_LAYOUT.world.height;
  for (let y = 0; y < mask.height; y++) for (let x = 0; x < mask.width; x++) {
    const wx = (x + .5) / sx, wy = (y + .5) / sy, offset = (y * mask.width + x) * 4;
    const pane = PIXEL_LAYOUT.outdoors.windows.find(p => wx >= p.x && wx < p.x + p.width && wy >= p.y && wy < p.y + p.height);
    const r = pixels.data[offset], g = pixels.data[offset + 1], b = pixels.data[offset + 2];
    const inRect = p => wx >= p.x && wx < p.x + p.width && wy >= p.y && wy < p.y + p.height;
    const frame = pane?.frame_bars.some(inRect);
    const covered = pane?.occluders.some(p => {
      if (wx < p.x || wx >= p.x + p.width || wy < p.y || wy >= p.y + p.height) return false;
      if (p.shape === 'solid') return true;
      if (p.shape === 'ellipse') return ((wx - p.x - p.width / 2) / (p.width / 2)) ** 2 + ((wy - p.y - p.height / 2) / (p.height / 2)) ** 2 <= 1;
      // Lamp bounds include glass around their silhouette; don't retain an orange box.
      return Math.max(r, g, b) < 155 || (r > 190 && g > r * .76 && b < g * .8);
    });
    pixels.data[offset + 3] = pane && !frame && !covered && !windowFoliagePixel(r, g, b) ? 255 : 0;
  }
  m.putImageData(pixels, 0, 0);
  const cache = { mask, exterior: makeCanvas(background, PIXEL_LAYOUT.world.width, PIXEL_LAYOUT.world.height), view: makeCanvas(background, mask.width, mask.height), key: '' };
  caches.set(background, cache);
  return cache;
}

/** Reuse the current exterior, including its actual sky and weather. No new art,
 * repeated painted sunset, or separately invented window clock/palette. */
export function drawWindowViews(ctx, background, moment, weather, elapsed = 0, weatherElapsed = 0) {
  const cache = windowCache(background);
  if (!cache) return;
  const layout = PIXEL_LAYOUT, { width, height } = layout.world;
  const drift = Math.round(Math.sin(elapsed / layout.life.cloud_cycle_ms) * layout.life.cloud_drift_px);
  const key = JSON.stringify([moment.daylight, moment.dusk, moment.elevation, weather, drift, weather.available ? Math.floor(weatherElapsed / 150) : 0]);
  if (cache.key !== key) {
    const exterior = cache.exterior.getContext('2d');
    exterior.clearRect(0, 0, width, height); exterior.imageSmoothingEnabled = false;
    exterior.drawImage(background, 0, 0, width, height);
    drawOutdoorLight(exterior, moment, weather);
    drawOutdoorSky(exterior, background, moment, weather, elapsed);
    drawOutdoorWeather(exterior, weather, weatherElapsed);
    const view = cache.view.getContext('2d');
    view.setTransform(1, 0, 0, 1, 0, 0); view.clearRect(0, 0, cache.view.width, cache.view.height);
    view.save(); view.scale(cache.view.width / width, cache.view.height / height); view.imageSmoothingEnabled = false;
    for (const p of layout.outdoors.windows) {
      const s = p.source;
      view.drawImage(cache.exterior, s.x, s.y, s.width, s.height, p.x, p.y, p.width, p.height);
    }
    view.restore(); view.globalCompositeOperation = 'destination-in'; view.drawImage(cache.mask, 0, 0); view.globalCompositeOperation = 'source-over';
    cache.key = key;
  }
  ctx.save(); ctx.imageSmoothingEnabled = false; ctx.drawImage(cache.view, 0, 0, width, height); ctx.restore();
}
