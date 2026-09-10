/**
 * Pixel sprite toolkit.
 *
 * Sprites are authored as rows of characters (one character per world pixel) and compiled
 * once into small offscreen canvases. A compiled sprite is then a single drawImage per frame,
 * which is what lets a floor full of animated people stay well under a millisecond.
 *
 * Two things make sprites read as finished art rather than as coloured rectangles:
 *   - a one-pixel outline in a hue-shifted dark (never black), added automatically around the
 *     silhouette so every figure separates from any wall behind it;
 *   - ramps instead of flat colour, provided by the palette module and mapped to letters.
 *
 * Pure drawing; no state from the backend reaches this file.
 */

import { AMBIENT } from './office_palette.js';

/** A tiny mutable pixel grid. Colours are CSS strings or null for transparent. */
export class PixelGrid {
  constructor(w, h) {
    this.w = w;
    this.h = h;
    this.data = new Array(w * h).fill(null);
  }

  plot(x, y, color) {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h || !color) return;
    this.data[y * this.w + x] = color;
  }

  at(x, y) {
    if (x < 0 || y < 0 || x >= this.w || y >= this.h) return null;
    return this.data[y * this.w + x];
  }

  /** Blit rows of letters through a letter->colour map at an offset. '.' and ' ' are clear. */
  blit(rows, map, dx = 0, dy = 0) {
    for (let y = 0; y < rows.length; y += 1) {
      const row = rows[y];
      for (let x = 0; x < row.length; x += 1) {
        const ch = row[x];
        if (ch === '.' || ch === ' ') continue;
        const color = map[ch];
        if (color) this.plot(x + dx, y + dy, color);
      }
    }
    return this;
  }

  /** Fill a rectangle. */
  rect(x, y, w, h, color) {
    for (let yy = y; yy < y + h; yy += 1) for (let xx = x; xx < x + w; xx += 1) this.plot(xx, yy, color);
    return this;
  }

  /** Add a 1px outline around every opaque pixel that touches a transparent one (4-connected). */
  outline(color = AMBIENT.shadow) {
    const src = this.data.slice();
    const idx = (x, y) => y * this.w + x;
    for (let y = 0; y < this.h; y += 1) {
      for (let x = 0; x < this.w; x += 1) {
        if (src[idx(x, y)]) continue;
        const touch =
          (x > 0 && src[idx(x - 1, y)]) ||
          (x < this.w - 1 && src[idx(x + 1, y)]) ||
          (y > 0 && src[idx(x, y - 1)]) ||
          (y < this.h - 1 && src[idx(x, y + 1)]);
        if (touch) this.data[idx(x, y)] = color;
      }
    }
    return this;
  }

  /** Mirror horizontally in place. */
  flip() {
    for (let y = 0; y < this.h; y += 1) {
      const row = this.data.slice(y * this.w, (y + 1) * this.w).reverse();
      for (let x = 0; x < this.w; x += 1) this.data[y * this.w + x] = row[x];
    }
    return this;
  }

  toCanvas() {
    const canvas = document.createElement('canvas');
    canvas.width = Math.max(1, this.w);
    canvas.height = Math.max(1, this.h);
    const ctx = canvas.getContext('2d');
    const img = ctx.createImageData(canvas.width, canvas.height);
    const cache = new Map();
    for (let i = 0; i < this.data.length; i += 1) {
      const c = this.data[i];
      if (!c) continue;
      let rgba = cache.get(c);
      if (!rgba) {
        rgba = parseColor(c);
        cache.set(c, rgba);
      }
      img.data[i * 4] = rgba[0];
      img.data[i * 4 + 1] = rgba[1];
      img.data[i * 4 + 2] = rgba[2];
      img.data[i * 4 + 3] = rgba[3];
    }
    ctx.putImageData(img, 0, 0);
    return canvas;
  }
}

function parseColor(c) {
  if (c[0] === '#') {
    const h = c.slice(1);
    if (h.length === 6 || h.length === 8) {
      return [
        parseInt(h.slice(0, 2), 16),
        parseInt(h.slice(2, 4), 16),
        parseInt(h.slice(4, 6), 16),
        h.length === 8 ? parseInt(h.slice(6, 8), 16) : 255,
      ];
    }
    if (h.length === 3) {
      return [parseInt(h[0] + h[0], 16), parseInt(h[1] + h[1], 16), parseInt(h[2] + h[2], 16), 255];
    }
  }
  const m = /rgba?\(([^)]+)\)/.exec(c);
  if (m) {
    const p = m[1].split(',').map((v) => parseFloat(v));
    return [p[0], p[1], p[2], p.length > 3 ? Math.round(p[3] * 255) : 255];
  }
  return [255, 0, 255, 255];
}

/** Compiled-sprite cache: key -> canvas. Bounded so a long session cannot grow without limit. */
const cache = new Map();
const CACHE_LIMIT = 600;

export function cachedSprite(key, build) {
  let sprite = cache.get(key);
  if (sprite) return sprite;
  sprite = build();
  if (cache.size >= CACHE_LIMIT) cache.delete(cache.keys().next().value);
  cache.set(key, sprite);
  return sprite;
}

/** Draw a compiled sprite with its top-left at (x, y), snapped to whole pixels. */
export function drawSprite(ctx, sprite, x, y) {
  ctx.drawImage(sprite, Math.round(x), Math.round(y));
}

/**
 * Radial glow sprite cache. Gradients are expensive to build per frame, so each
 * (radius, colour) pair is rasterised once and reused as an image.
 */
const glowCache = new Map();

export function glowSprite(radius, color) {
  const key = `${radius}|${color}`;
  let c = glowCache.get(key);
  if (c) return c;
  const size = radius * 2;
  c = document.createElement('canvas');
  c.width = size;
  c.height = size;
  const g = c.getContext('2d');
  const grad = g.createRadialGradient(radius, radius, 0, radius, radius, radius);
  grad.addColorStop(0, color);
  grad.addColorStop(0.45, color.replace(/,([^,]+)\)$/, (m, a) => `,${(parseFloat(a) * 0.45).toFixed(3)})`));
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  g.fillStyle = grad;
  g.fillRect(0, 0, size, size);
  glowCache.set(key, c);
  return c;
}

/** Additive glow centred at (x, y). Colour must be an rgba() string. */
export function glow(ctx, x, y, radius, color, alpha = 1) {
  const s = glowSprite(Math.max(2, Math.round(radius)), color);
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.globalCompositeOperation = 'lighter';
  ctx.drawImage(s, Math.round(x - s.width / 2), Math.round(y - s.height / 2));
  ctx.restore();
}

/** Soft elliptical contact shadow on the floor under an object. */
export function contactShadow(ctx, cx, y, halfW, halfH = 3, alpha = 0.34) {
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.fillStyle = AMBIENT.shadow;
  const rows = Math.max(1, Math.round(halfH));
  for (let i = -rows; i <= rows; i += 1) {
    const t = i / (rows + 0.5);
    const w = Math.round(halfW * Math.sqrt(Math.max(0, 1 - t * t)));
    ctx.fillRect(Math.round(cx) - w, Math.round(y) + i, w * 2, 1);
  }
  ctx.restore();
}
