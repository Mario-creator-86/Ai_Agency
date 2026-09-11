/**
 * Office sprite atlas — the Blender-rendered pixel art (art-source/blender) as loadable sprites.
 *
 * Two catalogues:
 *   assets/pixel/office/atlas.json        props: finished, palette-exact sprites with an anchor
 *                                         (the pixel that lands on the placement point), an
 *                                         optional cast-shadow layer and named points (screen
 *                                         rectangles, lamp positions).
 *   assets/sprites/characters/parts.json  character parts rendered in KEY colours; the renderer
 *                                         composites and recolours them per agent look, so the
 *                                         deterministic appearance rules in office_characters.js
 *                                         stay the only source of who looks like what.
 *
 * Nothing here reads backend state. If the atlas is missing or still loading, callers fall
 * back to the procedural drawings, so the page never shows a hole.
 */

import { PixelGrid } from './pixel_sprites.js';
import { AMBIENT } from './office_palette.js';

/** Codes a decoded key pixel can carry. */
export const CODE = {
  CLEAR: -1,
  SKIN: 0,      // 0..4
  HAIR: 8,      // 8..12
  GARMENT: 16,  // 16..20
  SECOND: 24,   // 24..28
  TRIM: 32,     // 32..36
  EYE_WHITE: 40,
  EYE_DARK: 41,
  FIXED: 48,    // 48 + index into the part's fixed-colour table
};

const EYE_WHITE_COLOR = '#f6f2ea';
const TONE_STEPS = [0, 32, 64, 96, 128];

/**
 * Decode one key-colour pixel into a code (pure; exported for tests).
 * skin = red with equal g/b, hair = green, garment = blue, second = yellow, trim = magenta.
 */
export function decodeKey(r, g, b) {
  const tone = (v) => TONE_STEPS.indexOf(v);
  if (r === 255 && g === 255 && b === 255) return CODE.EYE_WHITE;
  if (r === 0 && g === 0 && b === 0) return CODE.EYE_DARK;
  if (r === 255 && g === b && tone(g) >= 0) return CODE.SKIN + tone(g);
  if (g === 255 && r === b && tone(r) >= 0) return CODE.HAIR + tone(r);
  if (b === 255 && r === g && tone(r) >= 0) return CODE.GARMENT + tone(r);
  if (r === 255 && g === 255 && tone(b) >= 0) return CODE.SECOND + tone(b);
  if (r === 255 && b === 255 && tone(g) >= 0) return CODE.TRIM + tone(g);
  return null;
}

/** Colour for a code under a look. `fixed` is the part's own colour table. */
export function colorForCode(code, look, fixed) {
  if (code < 0) return null;
  if (code < 8) return look.skin[code];
  if (code < 16) return look.hair[code - 8];
  if (code < 24) return look.garment[code - 16];
  if (code < 32) return look.second[code - 24];
  if (code < 40) return look.trim[code - 32];
  if (code === CODE.EYE_WHITE) return EYE_WHITE_COLOR;
  if (code === CODE.EYE_DARK) return AMBIENT.shadow;
  return fixed[code - CODE.FIXED] || null;
}

const hex = (r, g, b) => `#${[r, g, b].map((v) => v.toString(16).padStart(2, '0')).join('')}`;

/** Decode an image's pixels into codes. Runs once per part. */
export function decodeImageData(data, w, h) {
  const codes = new Int16Array(w * h).fill(CODE.CLEAR);
  const fixed = [];
  const fixedIndex = new Map();
  for (let i = 0; i < w * h; i += 1) {
    const a = data[i * 4 + 3];
    if (a < 128) continue;
    const r = data[i * 4];
    const g = data[i * 4 + 1];
    const b = data[i * 4 + 2];
    let code = decodeKey(r, g, b);
    if (code === null) {
      const c = hex(r, g, b);
      let idx = fixedIndex.get(c);
      if (idx === undefined) {
        idx = fixed.length;
        fixed.push(c);
        fixedIndex.set(c, idx);
      }
      code = CODE.FIXED + idx;
    }
    codes[i] = code;
  }
  return { w, h, codes, fixed };
}

/* ------------------------------------------------------------------ loading */

export const atlas = {
  ready: false,
  props: /** @type {Record<string, any>} */ ({}),
  parts: /** @type {Record<string, any>} */ ({}),
  images: new Map(),
  decoded: new Map(),
  shadowAlpha: 0.34,
  base: '/',
};

let loading = null;

function loadImage(url) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = url;
  });
}

/**
 * Load both catalogues and every image. Resolves true when sprites can be used.
 * Safe to call without a DOM (tests): resolves false.
 */
export function loadAtlas(base) {
  if (loading) return loading;
  if (typeof document === 'undefined' || typeof fetch === 'undefined') return Promise.resolve(false);
  atlas.base = base || (typeof window !== 'undefined' && /** @type {any} */ (window).__ATLAS_BASE) || '/';
  loading = (async () => {
    try {
      const [propsRes, partsRes] = await Promise.all([
        fetch(`${atlas.base}assets/pixel/office/atlas.json`),
        fetch(`${atlas.base}assets/sprites/characters/parts.json`),
      ]);
      if (!propsRes.ok || !partsRes.ok) return false;
      const propsJson = await propsRes.json();
      const partsJson = await partsRes.json();
      atlas.props = propsJson.sprites || {};
      atlas.parts = partsJson.parts || {};
      atlas.shadowAlpha = propsJson.shadow_alpha || 0.34;
      const jobs = [];
      for (const [name, e] of Object.entries(atlas.props)) {
        const file = e.path || `pixel/office/${e.file}`;
        jobs.push(loadImage(`${atlas.base}assets/${file}`).then((img) => atlas.images.set(`prop:${name}`, img)));
        if (e.shadow) {
          const shadowFile = e.shadow_path || `pixel/office/${e.shadow}`;
          jobs.push(loadImage(`${atlas.base}assets/${shadowFile}`).then((img) => atlas.images.set(`shadow:${name}`, img)));
        }
      }
      for (const [name, e] of Object.entries(atlas.parts)) {
        jobs.push(loadImage(`${atlas.base}assets/sprites/characters/${e.file}`).then((img) => atlas.images.set(`part:${name}`, img)));
      }
      await Promise.all(jobs);
      atlas.ready = Object.keys(atlas.props).length > 0;
      return atlas.ready;
    } catch (err) {
      console.warn('office atlas unavailable, using procedural art', err);
      return false;
    }
  })();
  return loading;
}

/* ------------------------------------------------------------------- props */

export function propReady(name) {
  return atlas.ready && Boolean(atlas.props[name]) && Boolean(atlas.images.get(`prop:${name}`));
}

export function propEntry(name) {
  return atlas.props[name] || null;
}

/**
 * Draw a prop with its anchor at world (x, y). Floor props anchor at (x, floorLine), wall props
 * at their top-left. The cast-shadow layer, if any, is blended first.
 */
export function drawProp(ctx, name, x, y, { shadow = true } = {}) {
  const e = atlas.props[name];
  const img = atlas.images.get(`prop:${name}`);
  if (!e || !img) return null;
  const dx = Math.round(x - e.anchor.x);
  const dy = Math.round(y - e.anchor.y);
  const sh = shadow && e.shadow ? atlas.images.get(`shadow:${name}`) : null;
  if (sh) {
    ctx.save();
    ctx.globalAlpha = atlas.shadowAlpha;
    ctx.drawImage(sh, dx, dy);
    ctx.restore();
  }
  ctx.drawImage(img, dx, dy);
  return { x: dx, y: dy, w: e.w, h: e.h, entry: e };
}

/** Repeat a tile prop horizontally from x0 to x1 (clipped), anchored at y. */
export function tileProp(ctx, name, x0, x1, y) {
  const e = atlas.props[name];
  const img = atlas.images.get(`prop:${name}`);
  if (!e || !img) return false;
  ctx.save();
  ctx.beginPath();
  ctx.rect(Math.round(x0), Math.round(y - e.anchor.y), Math.round(x1 - x0), e.h);
  ctx.clip();
  for (let x = Math.round(x0); x < x1; x += e.w) ctx.drawImage(img, x - e.anchor.x, Math.round(y - e.anchor.y));
  ctx.restore();
  return true;
}

/** A named point or rectangle of a prop, in world coordinates for an anchor at (x, y). */
export function propPoint(name, key, x, y) {
  const e = atlas.props[name];
  const p = e && e.points ? e.points[key] : null;
  if (!p) return null;
  const out = { x: Math.round(x - e.anchor.x + p.x), y: Math.round(y - e.anchor.y + p.y) };
  if (p.w !== undefined) {
    out.w = p.w;
    out.h = p.h;
  }
  return out;
}

/* ------------------------------------------------------------------- parts */

export function partsReady() {
  return atlas.ready && Boolean(atlas.parts.body_open) && Boolean(atlas.images.get('part:body_open'));
}

/** Decoded key codes for a part (cached). */
export function partCodes(name) {
  let d = atlas.decoded.get(name);
  if (d) return d;
  const e = atlas.parts[name];
  const img = atlas.images.get(`part:${name}`);
  if (!e || !img) return null;
  const c = document.createElement('canvas');
  c.width = e.w;
  c.height = e.h;
  const g = c.getContext('2d');
  g.drawImage(img, 0, 0);
  d = { ...decodeImageData(g.getImageData(0, 0, e.w, e.h).data, e.w, e.h), anchor: e.anchor };
  atlas.decoded.set(name, d);
  return d;
}

/**
 * Composite parts (in order) for a look into one outlined sprite. Every part shares the
 * anchor (seat centre x, desk plane y); `dx`/`dy` shift a part in world pixels (y down).
 * Returns { canvas, ax, ay }: draw at (cx - ax, deskTop - ay).
 */
export function compositeParts(list, look, outlineColor = AMBIENT.shadow) {
  const parts = list.map((p) => ({ ...p, d: partCodes(p.name) })).filter((p) => p.d);
  if (!parts.length) return null;
  let left = 0, right = 0, top = 0, bottom = 0;
  for (const p of parts) {
    const dx = p.dx || 0;
    const dy = p.dy || 0;
    left = Math.max(left, p.d.anchor.x - dx);
    right = Math.max(right, p.d.w - p.d.anchor.x + dx);
    top = Math.max(top, p.d.anchor.y - dy);
    bottom = Math.max(bottom, p.d.h - p.d.anchor.y + dy);
  }
  const OUT = 1;
  const grid = new PixelGrid(left + right + OUT * 2, top + bottom + OUT * 2);
  for (const p of parts) {
    const ox = left - p.d.anchor.x + (p.dx || 0) + OUT;
    const oy = top - p.d.anchor.y + (p.dy || 0) + OUT;
    const { w, h, codes, fixed } = p.d;
    for (let y = 0; y < h; y += 1) {
      for (let x = 0; x < w; x += 1) {
        const code = codes[y * w + x];
        if (code < 0) continue;
        grid.plot(ox + x, oy + y, colorForCode(code, look, fixed));
      }
    }
  }
  if (outlineColor) grid.outline(outlineColor);
  return { canvas: grid.toCanvas(), ax: left + OUT, ay: top + OUT };
}
