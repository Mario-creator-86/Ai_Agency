/**
 * Autonomous AI Studio — 2D office renderer.
 *
 * WHAT THIS FILE MAY AND MAY NOT DO
 * ---------------------------------
 * The backend is the only source of truth. This renderer draws what the API and the event
 * stream report: which zones and desks exist, which agents are assigned where, and each
 * agent's runtime_state and lifecycle. A character types only when the backend says it is
 * WORKING, and sleeps only when the backend says it is PAUSED.
 *
 * Everything outside the building — sky, traffic, trees, pedestrians — is stage scenery. It is
 * deliberately disconnected from any data so it cannot be mistaken for activity: a passing car
 * means nothing happened. Scenery is drawn from a fixed seed, not from events.
 *
 * RENDERING MODEL
 * ---------------
 * The world is drawn at a fixed 1:1 resolution into an offscreen buffer and then blitted to the
 * visible canvas with image smoothing disabled. That keeps pixel art crisp at every zoom level
 * instead of resampling it into mush, and it makes the cost of a frame independent of how large
 * the canvas is on screen.
 *
 * Static scenery (skyline, building shell, furniture) is rasterised once into a second buffer
 * and reused; only things that actually move are redrawn each frame.
 */

/* ============================================================================
   Deterministic randomness
   Every varied detail — a face, a lit window, a tree's lean — is derived from a seed so the
   studio looks the same on every reload. Nothing here uses Math.random().
   ========================================================================== */

function hash32(input) {
  const str = String(input);
  let h = 2166136261;
  for (let i = 0; i < str.length; i += 1) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function mulberry32(seed) {
  let a = seed >>> 0;
  return function next() {
    a += 0x6d2b79f5;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Pick from a list deterministically. */
function pick(list, rnd) {
  return list[Math.floor(rnd() * list.length) % list.length];
}

const TAU = Math.PI * 2;
const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
const lerp = (a, b, t) => a + (b - a) * t;

/* ============================================================================
   Palette — mirrors the CSS design tokens so the scene belongs to the same studio.
   ========================================================================== */

const PAL = {
  skyTop: '#0b1a20',
  skyMid: '#123039',
  skyWarm: '#3d4a3a',
  skyHorizon: '#7d6a44',
  star: '#e8e4cf',
  moon: '#efe7c8',

  cityFar: '#152a2a',
  cityMid: '#122421',
  cityNear: '#0e1d1b',
  windowLit: '#ffd79a',
  windowDim: '#6d6a4a',

  ground: '#101c19',
  road: '#161f1d',
  roadLine: '#c8b478',
  sidewalk: '#20302b',
  kerb: '#2a3a33',

  trunk: '#33291f',
  leafDark: '#1d3a2a',
  leafMid: '#28503a',
  leafLight: '#356b4b',

  lampPost: '#2c3a34',
  lampGlow: '#ffcf8a',

  shell: '#1b2b26',
  shellLight: '#243a33',
  shellDark: '#121f1c',
  slab: '#2b3f37',
  slabEdge: '#3a5348',
  glass: '#16302f',
  glassLit: '#2a4b45',

  ink: '#dfe8dc',
  inkDim: '#8fa294',
  gold: '#ddae6a',
  teal: '#4ec5ab',
  amber: '#f0a65a',
  red: '#d9705a',
  green: '#6fbf7a',
  blue: '#6aa9d8',
  magenta: '#c07ab0',
  white: '#f4f2e6',
};

/** Zone accents. Each department reads differently at a glance, inside one warm family. */
const ZONE_STYLE = {
  DIRECTOR: { accent: PAL.gold, wall: '#22332c', name: 'EXECUTIVE' },
  RESEARCH: { accent: PAL.teal, wall: '#1b3230', name: 'RESEARCH' },
  SCRIPT: { accent: PAL.amber, wall: '#2a2f26', name: 'WRITING' },
  AUDIO: { accent: PAL.magenta, wall: '#252a30', name: 'AUDIO' },
  VIDEO: { accent: PAL.blue, wall: '#1e2b31', name: 'VIDEO' },
  SERVER: { accent: PAL.green, wall: '#182722', name: 'INFRA' },
  LOUNGE: { accent: PAL.amber, wall: '#2b2622', name: 'COMMONS' },
  PUBLISH: { accent: PAL.red, wall: '#26251f', name: 'DISTRIBUTION' },
  SHOP: { accent: PAL.gold, wall: '#2a2318', name: 'AD SPACE' },
  DEFAULT: { accent: PAL.inkDim, wall: '#1f2b26', name: 'STUDIO' },
};

const zoneStyle = (type) => ZONE_STYLE[type] || ZONE_STYLE.DEFAULT;

/* ============================================================================
   Pixel drawing helpers.
   Everything snaps to whole world pixels: half-pixel rectangles are what make canvas
   "pixel art" look soft and accidental.
   ========================================================================== */

function px(ctx, x, y, w, h, color) {
  ctx.fillStyle = color;
  ctx.fillRect(Math.round(x), Math.round(y), Math.max(1, Math.round(w)), Math.max(1, Math.round(h)));
}

/** Rectangle with a lighter top edge and darker bottom edge — cheap volume. */
function block(ctx, x, y, w, h, base, top, bottom) {
  px(ctx, x, y, w, h, base);
  if (top) px(ctx, x, y, w, 1, top);
  if (bottom) px(ctx, x, y + h - 1, w, 1, bottom);
}

function outline(ctx, x, y, w, h, color) {
  px(ctx, x, y, w, 1, color);
  px(ctx, x, y + h - 1, w, 1, color);
  px(ctx, x, y, 1, h, color);
  px(ctx, x + w - 1, y, 1, h, color);
}

/** Soft radial light pool. Used sparingly: it is the most expensive thing we draw. */
function glow(ctx, x, y, radius, color, alpha) {
  const g = ctx.createRadialGradient(x, y, 0, x, y, radius);
  g.addColorStop(0, color);
  g.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.globalCompositeOperation = 'lighter';
  ctx.fillStyle = g;
  ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2);
  ctx.restore();
}

/** Tiny 5x7 pixel font for signage and labels — no webfont, no CSP surprises. */
const GLYPHS = {
  A: ['01110', '10001', '10001', '11111', '10001', '10001', '10001'],
  B: ['11110', '10001', '11110', '10001', '10001', '10001', '11110'],
  C: ['01111', '10000', '10000', '10000', '10000', '10000', '01111'],
  D: ['11110', '10001', '10001', '10001', '10001', '10001', '11110'],
  E: ['11111', '10000', '11110', '10000', '10000', '10000', '11111'],
  F: ['11111', '10000', '11110', '10000', '10000', '10000', '10000'],
  G: ['01111', '10000', '10000', '10011', '10001', '10001', '01111'],
  H: ['10001', '10001', '11111', '10001', '10001', '10001', '10001'],
  I: ['111', '010', '010', '010', '010', '010', '111'],
  J: ['00111', '00010', '00010', '00010', '10010', '10010', '01100'],
  K: ['10001', '10010', '11100', '10010', '10001', '10001', '10001'],
  L: ['10000', '10000', '10000', '10000', '10000', '10000', '11111'],
  M: ['10001', '11011', '10101', '10101', '10001', '10001', '10001'],
  N: ['10001', '11001', '10101', '10011', '10001', '10001', '10001'],
  O: ['01110', '10001', '10001', '10001', '10001', '10001', '01110'],
  P: ['11110', '10001', '11110', '10000', '10000', '10000', '10000'],
  Q: ['01110', '10001', '10001', '10001', '10101', '10010', '01101'],
  R: ['11110', '10001', '11110', '10100', '10010', '10001', '10001'],
  S: ['01111', '10000', '01110', '00001', '00001', '10001', '01110'],
  T: ['11111', '00100', '00100', '00100', '00100', '00100', '00100'],
  U: ['10001', '10001', '10001', '10001', '10001', '10001', '01110'],
  V: ['10001', '10001', '10001', '10001', '10001', '01010', '00100'],
  W: ['10001', '10001', '10001', '10101', '10101', '10101', '01010'],
  X: ['10001', '10001', '01010', '00100', '01010', '10001', '10001'],
  Y: ['10001', '10001', '01010', '00100', '00100', '00100', '00100'],
  Z: ['11111', '00010', '00100', '01000', '10000', '10000', '11111'],
  0: ['01110', '10001', '10011', '10101', '11001', '10001', '01110'],
  1: ['00100', '01100', '00100', '00100', '00100', '00100', '01110'],
  2: ['01110', '10001', '00001', '00110', '01000', '10000', '11111'],
  3: ['11110', '00001', '01110', '00001', '00001', '10001', '01110'],
  4: ['00010', '00110', '01010', '10010', '11111', '00010', '00010'],
  5: ['11111', '10000', '11110', '00001', '00001', '10001', '01110'],
  6: ['01110', '10000', '11110', '10001', '10001', '10001', '01110'],
  7: ['11111', '00001', '00010', '00100', '01000', '01000', '01000'],
  8: ['01110', '10001', '01110', '10001', '10001', '10001', '01110'],
  9: ['01110', '10001', '10001', '01111', '00001', '00001', '01110'],
  '.': ['0', '0', '0', '0', '0', '0', '1'],
  '-': ['000', '000', '000', '111', '000', '000', '000'],
  '·': ['0', '0', '0', '1', '0', '0', '0'],
  '/': ['00001', '00010', '00010', '00100', '01000', '01000', '10000'],
  ':': ['0', '1', '0', '0', '0', '1', '0'],
  '&': ['01100', '10010', '01100', '01101', '10010', '10010', '01101'],
  ' ': ['0', '0', '0', '0', '0', '0', '0'],
};

function textWidth(str, scale = 1, tracking = 1) {
  let w = 0;
  for (const ch of String(str).toUpperCase()) {
    const g = GLYPHS[ch] || GLYPHS[' '];
    w += (g[0].length + tracking) * scale;
  }
  return w - tracking * scale;
}

function drawText(ctx, str, x, y, color, scale = 1, tracking = 1) {
  let cx = Math.round(x);
  ctx.fillStyle = color;
  for (const ch of String(str).toUpperCase()) {
    const g = GLYPHS[ch] || GLYPHS[' '];
    for (let row = 0; row < g.length; row += 1) {
      const bits = g[row];
      for (let col = 0; col < bits.length; col += 1) {
        if (bits[col] === '1') {
          ctx.fillRect(cx + col * scale, Math.round(y) + row * scale, scale, scale);
        }
      }
    }
    cx += (g[0].length + tracking) * scale;
  }
}

/* ============================================================================
   Viewport — pan/zoom. Kept API-compatible with the previous engine.
   ========================================================================== */

export class Viewport {
  constructor(canvas) {
    this.canvas = canvas;
    this.panX = 0;
    this.panY = 0;
    this.zoom = 1;
    this.minZoom = 0.4;
    this.maxZoom = 2.5;
  }

  setZoom(next, anchorX, anchorY) {
    const clamped = clamp(next, this.minZoom, this.maxZoom);
    if (anchorX !== undefined && anchorY !== undefined) {
      const before = this.screenToWorld(anchorX, anchorY);
      this.zoom = clamped;
      const after = this.screenToWorld(anchorX, anchorY);
      this.panX += (after.x - before.x) * this.zoom;
      this.panY += (after.y - before.y) * this.zoom;
    } else {
      const cx = this.canvas.width / 2;
      const cy = this.canvas.height / 2;
      const before = this.screenToWorld(cx, cy);
      this.zoom = clamped;
      const after = this.screenToWorld(cx, cy);
      this.panX += (after.x - before.x) * this.zoom;
      this.panY += (after.y - before.y) * this.zoom;
    }
  }

  worldToScreen(x, y) {
    return { x: x * this.zoom + this.panX, y: y * this.zoom + this.panY };
  }

  screenToWorld(x, y) {
    return { x: (x - this.panX) / this.zoom, y: (y - this.panY) / this.zoom };
  }

  fitToOffice(worldWidth, worldHeight) {
    const cw = this.canvas.width || 1;
    const ch = this.canvas.height || 1;
    const scale = Math.min(cw / worldWidth, ch / worldHeight);
    this.zoom = clamp(scale, this.minZoom, this.maxZoom);
    this.panX = (cw - worldWidth * this.zoom) / 2;
    this.panY = (ch - worldHeight * this.zoom) / 2;
  }
}

/* ============================================================================
   Scenery: sky, skyline, street.
   None of this reflects backend state. It exists so the building sits in a world.
   ========================================================================== */

const WORLD_W = 1200;
const WORLD_H = 800;

/**
 * Ground line. The building stands on it, so it is derived from the backend building box
 * rather than fixed: the street must never be drawn through the ground floor.
 */
let HORIZON = 750;
const STREET_DEPTH = 250;
const PLINTH_H = 22;    // building base course, below the ground-floor slab
const WALK_H = 52;      // pavement depth; deep enough that a 34px person clears the base
const ROAD_H = 118;     // two lanes sized for full-scale vehicles // sky-to-world padding kept below the horizon for the street

function setHorizon(y) {
  HORIZON = Math.round(y);
}

function drawSky(ctx, w, h) {
  const g = ctx.createLinearGradient(0, 0, 0, HORIZON);
  g.addColorStop(0, PAL.skyTop);
  g.addColorStop(0.45, PAL.skyMid);
  g.addColorStop(0.78, PAL.skyWarm);
  g.addColorStop(1, PAL.skyHorizon);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, HORIZON);

  // Stars, thinning towards the warm horizon.
  const rnd = mulberry32(0xa17c);
  for (let i = 0; i < 190; i += 1) {
    const x = Math.floor(rnd() * w);
    const y = Math.floor(rnd() * 420);
    const bright = rnd();
    if (bright > 0.86) {
      px(ctx, x, y, 2, 2, PAL.star);
    } else {
      ctx.globalAlpha = 0.25 + bright * 0.5;
      px(ctx, x, y, 1, 1, PAL.star);
      ctx.globalAlpha = 1;
    }
  }

  // Moon with a soft halo and a couple of maria.
  const mx = 985;
  const my = 96;
  glow(ctx, mx, my, 62, 'rgba(239,231,200,0.5)', 0.5);
  px(ctx, mx - 15, my - 15, 30, 30, PAL.moon);
  px(ctx, mx - 17, my - 11, 2, 22, PAL.moon);
  px(ctx, mx + 15, my - 11, 2, 22, PAL.moon);
  px(ctx, mx - 11, my - 17, 22, 2, PAL.moon);
  px(ctx, mx - 11, my + 15, 22, 2, PAL.moon);
  px(ctx, mx - 8, my - 6, 6, 5, '#ddd3ae');
  px(ctx, mx + 2, my + 3, 8, 6, '#ddd3ae');
  px(ctx, mx - 4, my + 9, 4, 3, '#ddd3ae');
}

/** Two skyline bands. The far one is flatter and bluer; the near one carries detail. */
function drawSkyline(ctx, w) {
  const bands = [
    { seed: 0x51ee, color: PAL.cityFar, base: HORIZON - 40, min: 60, max: 190, width: [26, 64], lit: 0.16, step: 0 },
    { seed: 0x7c31, color: PAL.cityMid, base: HORIZON - 18, min: 90, max: 260, width: [34, 78], lit: 0.3, step: 1 },
  ];

  for (const band of bands) {
    const rnd = mulberry32(band.seed);
    let x = -30;
    while (x < w + 40) {
      const bw = Math.round(lerp(band.width[0], band.width[1], rnd()));
      const bh = Math.round(lerp(band.min, band.max, rnd() * rnd() + 0.15));
      const top = band.base - bh;
      px(ctx, x, top, bw, bh, band.color);
      px(ctx, x, top, bw, 2, band.step ? PAL.cityFar : '#1b3230');

      // Roof furniture on the nearer band.
      if (band.step && rnd() > 0.55) {
        const tw = 6 + Math.floor(rnd() * 10);
        px(ctx, x + 6, top - 5, tw, 5, band.color);
      }
      if (band.step && rnd() > 0.82) {
        px(ctx, x + bw - 8, top - 16, 2, 16, band.color);
        px(ctx, x + bw - 9, top - 18, 4, 3, PAL.red);
      }

      // Window grid.
      for (let wy = top + 8; wy < band.base - 8; wy += 10) {
        for (let wx = x + 5; wx < x + bw - 6; wx += 9) {
          const r = rnd();
          if (r < band.lit) px(ctx, wx, wy, 4, 5, PAL.windowLit);
          else if (r < band.lit + 0.2) px(ctx, wx, wy, 4, 5, PAL.windowDim);
        }
      }
      x += bw + 2 + Math.floor(rnd() * 8);
    }
  }
}

/** Ground plane, road, kerb, markings, plus the studio's own forecourt. */
function drawGround(ctx, w) {
  const plinthY = HORIZON;
  const walkY = HORIZON + PLINTH_H;          // top of the pavement
  const roadY = walkY + WALK_H;              // top of the carriageway
  const roadBottom = roadY + ROAD_H;

  // Base course the building stands on.
  px(ctx, 0, plinthY, w, PLINTH_H, '#22322b');
  px(ctx, 0, plinthY, w, 2, '#33473d');

  // Pavement with slab joints.
  px(ctx, 0, walkY, w, WALK_H, PAL.sidewalk);
  px(ctx, 0, walkY, w, 2, '#33473d');
  for (let x = 0; x < w; x += 34) px(ctx, x, walkY + 3, 1, WALK_H - 6, '#1a2924');
  // Kerb.
  px(ctx, 0, roadY - 5, w, 5, PAL.kerb);
  px(ctx, 0, roadY - 5, w, 1, '#3d5147');

  // Carriageway with a centre line and a pedestrian crossing.
  px(ctx, 0, roadY, w, ROAD_H, PAL.road);
  px(ctx, 0, roadY, w, 2, '#2b3a34');
  for (let x = 10; x < w; x += 78) px(ctx, x, roadY + ROAD_H / 2 - 3, 38, 5, PAL.roadLine);
  const crossX = 430;
  for (let i = 0; i < 7; i += 1) px(ctx, crossX + i * 17, roadY + 4, 11, ROAD_H - 8, '#3a4a42');

  // Far kerb and foreground pavement.
  px(ctx, 0, roadBottom, w, 6, PAL.kerb);
  px(ctx, 0, roadBottom + 6, w, WORLD_H, PAL.ground);
  for (let x = 20; x < w; x += 180) {
    px(ctx, x, roadBottom + 20, 30, 11, '#1a2724');
    for (let i = 0; i < 5; i += 1) px(ctx, x + 4 + i * 6, roadBottom + 23, 3, 5, '#233029');
  }
  for (let x = 120; x < w; x += 260) {
    block(ctx, x, roadBottom + 12, 72, 26, '#2a3a33', '#3b4d44', '#16241f');
    const rnd2 = mulberry32(hash32(`planter${x}`));
    for (let i = 0; i < 10; i += 1) {
      px(ctx, x + 4 + i * 7, roadBottom + 4 + rnd2() * 6, 8, 10, rnd2() > 0.5 ? PAL.leafMid : PAL.leafDark);
    }
  }
}

/** Everything that stands on the pavement shares this baseline. */
/** Tallest pedestrian drawn on the pavement, in world pixels. */
export const PEDESTRIAN_HEIGHT = 34 * 1.1;

/**
 * Street geometry derived from where the building meets the ground.
 *
 * Exported so the invariant that matters can be asserted in tests: a person standing on the
 * pavement must be completely below the building base, otherwise pedestrians appear to walk
 * through the ground floor.
 */
export function streetGeometry(buildingBase) {
  const plinthTop = buildingBase;
  const pavementTop = buildingBase + PLINTH_H;
  const standLine = buildingBase + PLINTH_H + 26;
  const road = buildingBase + PLINTH_H + WALK_H;
  return {
    plinthTop,
    pavementTop,
    standLine,
    roadTop: road,
    roadBottom: road + ROAD_H,
    worldHeight: buildingBase + STREET_DEPTH,
    headroom: standLine - PEDESTRIAN_HEIGHT - buildingBase,
  };
}

function walkLine() {
  return streetGeometry(HORIZON).standLine;
}

function roadTop() {
  return HORIZON + PLINTH_H + WALK_H;
}

/* ============================================================================
   Trees — trunks are static, foliage sways per frame.
   ========================================================================== */

function makeTrees(seed, w) {
  const rnd = mulberry32(seed);
  const trees = [];
  // Only outside the building footprint: a tree in front of the cutaway would hide the studio.
  const spots = [14, 58, 100, 1104, 1148, 1188];
  for (const x of spots) {
    if (x > w) continue;
    trees.push({
      x,
      height: 92 + Math.floor(rnd() * 46),
      spread: 34 + Math.floor(rnd() * 16),
      phase: rnd() * TAU,
      lean: rnd() * 0.6 - 0.3,
      tone: rnd(),
    });
  }
  return trees;
}

function drawTrunk(ctx, tree) {
  const baseY = walkLine();
  px(ctx, tree.x - 3, baseY - tree.height, 6, tree.height, PAL.trunk);
  px(ctx, tree.x - 3, baseY - tree.height, 2, tree.height, '#43362a');
  // Roots
  px(ctx, tree.x - 7, baseY - 3, 5, 3, PAL.trunk);
  px(ctx, tree.x + 2, baseY - 3, 5, 3, PAL.trunk);
  // Two branches
  px(ctx, tree.x + 2, baseY - tree.height + 16, 9, 3, PAL.trunk);
  px(ctx, tree.x - 10, baseY - tree.height + 28, 8, 3, PAL.trunk);
}

function drawFoliage(ctx, tree, time) {
  const baseY = walkLine();
  const topY = baseY - tree.height;
  const sway = Math.sin(time * 0.9 + tree.phase) * 3 + tree.lean * 2;
  const rnd = mulberry32(hash32(`leaf${tree.x}`));
  const clusters = 13;
  for (let i = 0; i < clusters; i += 1) {
    const a = (i / clusters) * TAU + tree.phase;
    const rx = Math.cos(a) * tree.spread * (0.55 + rnd() * 0.5);
    const ry = Math.sin(a) * tree.spread * 0.62 * (0.55 + rnd() * 0.5);
    const size = 9 + Math.floor(rnd() * 9);
    const depth = rnd();
    const color = depth > 0.66 ? PAL.leafLight : depth > 0.33 ? PAL.leafMid : PAL.leafDark;
    px(ctx, tree.x + rx + sway * (0.4 + depth * 0.8) - size / 2, topY + ry - 6, size, size, color);
  }
  // Crown highlight catching the street lamp.
  px(ctx, tree.x - 6 + sway, topY - 16, 12, 7, PAL.leafLight);
}

/* ============================================================================
   Street furniture and traffic.
   ========================================================================== */

// Only outside the building footprint: a column across the cutaway would hide the studio.
const LAMP_POSTS = [46, 1148];

function drawLampPost(ctx, x) {
  const baseY = walkLine();
  // A lamp column is about four people tall.
  px(ctx, x - 3, baseY - 118, 6, 118, PAL.lampPost);
  px(ctx, x - 8, baseY - 3, 17, 4, '#26332d');
  px(ctx, x - 3, baseY - 122, 28, 5, PAL.lampPost);
  px(ctx, x + 20, baseY - 118, 8, 9, '#39493f');
}

function drawLampLight(ctx, x, time, i) {
  const baseY = walkLine();
  const flicker = 0.86 + Math.sin(time * 2.6 + i * 1.7) * 0.05 + Math.sin(time * 11 + i) * 0.02;
  px(ctx, x + 21, baseY - 110, 6, 6, PAL.lampGlow);
  glow(ctx, x + 24, baseY - 107, 104, 'rgba(255,207,138,0.42)', 0.5 * flicker);
  // Light pool on the pavement.
  ctx.save();
  ctx.globalAlpha = 0.16 * flicker;
  ctx.fillStyle = PAL.lampGlow;
  ctx.beginPath();
  ctx.ellipse(x + 24, baseY + 12, 68, 13, 0, 0, TAU);
  ctx.fill();
  ctx.restore();
}

const CAR_STYLES = [
  { body: '#8d5a4a', roof: '#6d4438', w: 90, h: 30, kind: 'sedan' },
  { body: '#3f6d63', roof: '#2f544c', w: 86, h: 29, kind: 'sedan' },
  { body: '#6a6a86', roof: '#4e4e68', w: 94, h: 31, kind: 'sedan' },
  { body: '#a08243', roof: '#7c6432', w: 112, h: 40, kind: 'van' },
  { body: '#4a5c78', roof: '#38485e', w: 168, h: 50, kind: 'bus' },
  { body: '#7c4550', roof: '#5e343d', w: 88, h: 29, kind: 'sedan' },
];

// The road is a loop: cars travel from -180 to WORLD_W + 120 and wrap around.
const TRAFFIC_LOOP_PAD_START = -180;
const TRAFFIC_LOOP_PAD_END = 120;
const TRAFFIC_MIN_GAP = 24;   // bumper-to-bumper distance a follower never crosses
const TRAFFIC_SLOW_GAP = 90;  // within this, a follower matches the leader's speed

export function makeTraffic(seed) {
  const rnd = mulberry32(seed);
  const cars = [];
  const loopLength = WORLD_W + TRAFFIC_LOOP_PAD_END - TRAFFIC_LOOP_PAD_START;
  // One lane per direction, three vehicles rightward and two leftward as before.
  // Each car spawns in its own stretch of the loop so no lane ever starts overlapped.
  for (const dir of [1, -1]) {
    const count = dir > 0 ? 3 : 2;
    const stretch = loopLength / count;
    for (let i = 0; i < count; i += 1) {
      cars.push({
        style: CAR_STYLES[Math.floor(rnd() * CAR_STYLES.length)],
        dir,
        // Near lane travels right, far lane travels left.
        laneOffset: dir > 0 ? 0.78 : 0.34,
        x: TRAFFIC_LOOP_PAD_START + i * stretch + rnd() * (stretch - 200),
        speed: (52 + rnd() * 48) * dir,
        bobPhase: rnd() * TAU,
      });
    }
  }
  return cars;
}

/**
 * Lane-aware traffic step. Vehicles in one lane travel at different preferred speeds,
 * so without a rule the fast ones eventually drive straight through the slow ones.
 * Each lane is processed front-to-back as a platoon: a follower within TRAFFIC_SLOW_GAP
 * of its leader adopts the leader's speed, and a hard clamp holds TRAFFIC_MIN_GAP so
 * bumper overlap is impossible — including across the loop seam, where the frontmost
 * car treats the rearmost car as its leader.
 */
export function updateTraffic(cars, worldW, dt) {
  const loopLength = worldW + TRAFFIC_LOOP_PAD_END - TRAFFIC_LOOP_PAD_START;
  for (const dir of [1, -1]) {
    const lane = cars.filter((c) => c.dir === dir);
    // Front of the lane first, so the leader's speed is known to every follower.
    lane.sort((a, b) => (b.x - a.x) * dir);
    for (let i = 0; i < lane.length; i += 1) {
      const car = lane[i];
      let v = Math.abs(car.speed);
      if (lane.length > 1) {
        const leader = i === 0 ? lane[lane.length - 1] : lane[i - 1];
        let ahead = (leader.x - car.x) * dir; // distance to the leader along the lane
        if (i === 0) ahead += loopLength;     // our leader sits across the wrap seam
        // Rightward the follower's nose leads (own width); leftward the leader's tail does.
        const gap = dir > 0 ? ahead - car.style.w : ahead - leader.style.w;
        if (gap < TRAFFIC_SLOW_GAP) v = Math.min(v, leader.v ?? Math.abs(leader.speed));
        car.x += v * dir * dt;
        if (gap < TRAFFIC_MIN_GAP) {
          car.x = dir > 0 ? leader.x - car.style.w - TRAFFIC_MIN_GAP
                          : leader.x + leader.style.w + TRAFFIC_MIN_GAP;
        }
      } else {
        car.x += v * dir * dt;
      }
      car.v = v;
    }
  }
  for (const car of cars) {
    if (car.dir > 0 && car.x > worldW + TRAFFIC_LOOP_PAD_END) car.x = TRAFFIC_LOOP_PAD_START;
    if (car.dir < 0 && car.x < TRAFFIC_LOOP_PAD_START) car.x = worldW + TRAFFIC_LOOP_PAD_END;
  }
}

function drawCar(ctx, car, time) {
  const s = car.style;
  const lane = roadTop() + ROAD_H * car.laneOffset;
  const y = lane - s.h;
  const x = car.x;
  const bob = Math.sin(time * 9 + car.bobPhase) * 0.6;
  const flip = car.dir < 0;
  const wheelR = Math.round(s.h * 0.32);

  ctx.save();
  ctx.translate(Math.round(x), Math.round(y + bob));
  if (flip) {
    ctx.translate(s.w, 0);
    ctx.scale(-1, 1);
  }

  ctx.globalAlpha = 0.32;
  px(ctx, 4, s.h - 2, s.w - 8, 5, '#0a1210');
  ctx.globalAlpha = 1;

  if (s.kind === 'bus') {
    block(ctx, 0, 0, s.w, s.h, s.body, '#5f7189', '#26313f');
    px(ctx, 0, s.h * 0.34, s.w, 2, '#33445a');
    for (let wx = 8; wx < s.w - 16; wx += 22) px(ctx, wx, 8, 16, 18, '#9fc6d8');
    px(ctx, s.w - 14, 7, 11, 20, '#c9dfe8');
    px(ctx, 6, s.h - 16, 10, 14, '#2c3a48');   // door
  } else if (s.kind === 'van') {
    block(ctx, 0, 8, s.w, s.h - 8, s.body, '#b89a55', '#5d4a24');
    px(ctx, s.w - 42, 0, 42, 12, s.roof);
    px(ctx, s.w - 36, 3, 27, 12, '#9fc6d8');
    px(ctx, 8, 16, 54, 14, '#8a7238');          // livery panel
    px(ctx, 12, 20, 46, 3, '#d8c58a');
  } else {
    // Bonnet, cabin and boot read as one silhouette.
    block(ctx, 0, s.h * 0.42, s.w, s.h * 0.58, s.body, null, '#2a1c17');
    px(ctx, s.w * 0.2, s.h * 0.05, s.w * 0.5, s.h * 0.4, s.roof);
    px(ctx, s.w * 0.24, s.h * 0.12, s.w * 0.2, s.h * 0.26, '#9fc6d8');
    px(ctx, s.w * 0.47, s.h * 0.12, s.w * 0.2, s.h * 0.26, '#8fb9cc');
    px(ctx, 0, s.h * 0.6, s.w, 2, '#00000033');
  }

  // Wheels with a hub, sized to the body.
  const wy = s.h - wheelR - 1;
  for (const wx of [s.w * 0.16, s.w * 0.74]) {
    px(ctx, wx, wy, wheelR * 2, wheelR * 2, '#141a18');
    px(ctx, wx + 2, wy + 2, wheelR * 2 - 4, wheelR * 2 - 4, '#2c3733');
    px(ctx, wx + wheelR - 2, wy + wheelR - 2, 4, 4, '#4a5a54');
  }

  px(ctx, s.w - 3, s.h * 0.5, 3, 5, '#ffe9b4');
  px(ctx, 0, s.h * 0.52, 3, 5, '#c4483a');
  ctx.restore();

  const beamX = flip ? x - 8 : x + s.w + 8;
  glow(ctx, beamX, y + s.h * 0.55, 66, 'rgba(255,226,164,0.30)', 0.55);
  ctx.save();
  ctx.globalAlpha = 0.09;
  ctx.fillStyle = '#ffe9b4';
  ctx.beginPath();
  ctx.moveTo(beamX, y + s.h * 0.5);
  ctx.lineTo(beamX + (flip ? -120 : 120), y + s.h + 16);
  ctx.lineTo(beamX + (flip ? -120 : 120), y + s.h - 10);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

/* ============================================================================
   Pedestrians — scenery only.
   ========================================================================== */

const WALKER_COLORS = ['#8a6b4a', '#4f6b7a', '#7a5a6b', '#5c6b4f', '#6b5a4a'];

function makeWalkers(seed) {
  const rnd = mulberry32(seed);
  const walkers = [];
  for (let i = 0; i < 6; i += 1) {
    walkers.push({
      x: rnd() * WORLD_W,
      dir: rnd() > 0.5 ? 1 : -1,
      speed: 16 + rnd() * 14,
      coat: WALKER_COLORS[Math.floor(rnd() * WALKER_COLORS.length)],
      trousers: pick(['#2a3138', '#33302a', '#293530'], rnd),
      skin: pick(SKIN_TONES, rnd),
      hair: pick(HAIR_COLORS, rnd),
      hat: rnd() > 0.66,
      bag: rnd() > 0.55,
      dog: rnd() > 0.82,
      phase: rnd() * TAU,
      scale: 0.94 + rnd() * 0.16,
    });
  }
  return walkers;
}

/**
 * Pedestrians are drawn at the same human scale as the staff inside the building, and they
 * walk on the pavement below the base course — never across the studio floor.
 */
function drawWalker(ctx, wkr, time) {
  const baseY = walkLine();
  const s = wkr.scale;
  const step = Math.sin(time * 5 + wkr.phase);
  const bob = Math.abs(Math.cos(time * 5 + wkr.phase)) * 1.8;
  const x = Math.round(wkr.x);
  const height = 34 * s;
  const y = Math.round(baseY - height - bob);

  ctx.save();
  ctx.globalAlpha = 0.3;
  px(ctx, x - 7, baseY - 2, 16, 3, '#0a1210');
  ctx.globalAlpha = 1;

  // Legs
  px(ctx, x - 4 + step * 3, y + height * 0.62, 5, height * 0.36, wkr.trousers);
  px(ctx, x + 1 - step * 3, y + height * 0.62, 5, height * 0.36, '#1c2522');
  px(ctx, x - 5 + step * 3, y + height * 0.96, 7, 3, '#141c19');
  px(ctx, x + step * -3, y + height * 0.96, 7, 3, '#141c19');

  // Coat
  px(ctx, x - 7, y + height * 0.3, 15, height * 0.36, wkr.coat);
  px(ctx, x - 7, y + height * 0.3, 15, 1, '#ffffff26');
  px(ctx, x - 2, y + height * 0.34, 2, height * 0.28, '#00000033');

  // Arms swinging opposite the legs
  px(ctx, x - 9, y + height * 0.33 + step * 2, 3, height * 0.26, wkr.coat);
  px(ctx, x + 8, y + height * 0.33 - step * 2, 3, height * 0.26, wkr.coat);
  px(ctx, x - 9, y + height * 0.58 + step * 2, 3, 4, wkr.skin);
  px(ctx, x + 8, y + height * 0.58 - step * 2, 3, 4, wkr.skin);

  if (wkr.bag) {
    px(ctx, x + 9, y + height * 0.6 - step * 2, 8, 9, '#4a3a2a');
    px(ctx, x + 11, y + height * 0.57 - step * 2, 4, 3, '#3a2c20');
  }

  // Head
  const headW = 11;
  px(ctx, x - 5, y + height * 0.06, headW, 11, wkr.skin);
  px(ctx, x - 5, y + height * 0.04, headW, 3, wkr.hair);
  px(ctx, x - 6, y + height * 0.1, 1, 4, wkr.hair);
  px(ctx, x - 2, y + height * 0.16, 2, 2, '#2a211c');
  px(ctx, x + 2, y + height * 0.16, 2, 2, '#2a211c');
  if (wkr.hat) px(ctx, x - 7, y + height * 0.01, 15, 4, '#2c3a34');
  ctx.restore();

  if (wkr.dog) {
    const dx = x + (wkr.dir > 0 ? -22 : 22);
    const dstep = Math.sin(time * 8 + wkr.phase) * 2;
    px(ctx, dx - 7, baseY - 13, 15, 8, '#6b563f');
    px(ctx, dx + (wkr.dir > 0 ? -10 : 6), baseY - 18, 7, 7, '#6b563f');
    px(ctx, dx + (wkr.dir > 0 ? -11 : 11), baseY - 18, 3, 3, '#54432f');
    px(ctx, dx - 5, baseY - 5 + dstep * 0.3, 3, 5, '#5a4834');
    px(ctx, dx + 4, baseY - 5 - dstep * 0.3, 3, 5, '#5a4834');
    px(ctx, dx + (wkr.dir > 0 ? 7 : -9), baseY - 15, 4, 2, '#6b563f');
  }
}

/* ============================================================================
   Clouds and birds.
   ========================================================================== */

function makeClouds(seed) {
  const rnd = mulberry32(seed);
  const clouds = [];
  for (let i = 0; i < 7; i += 1) {
    clouds.push({
      x: rnd() * (WORLD_W + 300) - 150,
      y: 40 + rnd() * 240,
      scale: 0.6 + rnd() * 1.5,
      speed: 3 + rnd() * 7,
      alpha: 0.08 + rnd() * 0.14,
      seed: Math.floor(rnd() * 9999),
    });
  }
  return clouds;
}

function drawCloud(ctx, cloud) {
  const rnd = mulberry32(cloud.seed);
  ctx.save();
  ctx.globalAlpha = cloud.alpha;
  const puffs = 6;
  for (let i = 0; i < puffs; i += 1) {
    const w = (26 + rnd() * 34) * cloud.scale;
    const h = (10 + rnd() * 10) * cloud.scale;
    const ox = (i * 20 - puffs * 7) * cloud.scale + rnd() * 8;
    const oy = (rnd() * 10 - 5) * cloud.scale;
    px(ctx, cloud.x + ox, cloud.y + oy, w, h, '#9fb0a4');
  }
  ctx.restore();
}

function makeBirds(seed) {
  const rnd = mulberry32(seed);
  return Array.from({ length: 3 }, () => ({
    x: rnd() * WORLD_W,
    y: 90 + rnd() * 150,
    speed: 26 + rnd() * 22,
    phase: rnd() * TAU,
    dir: rnd() > 0.5 ? 1 : -1,
  }));
}

function drawBird(ctx, bird, time) {
  const flap = Math.sin(time * 7 + bird.phase);
  const y = bird.y + Math.sin(time * 0.8 + bird.phase) * 6;
  ctx.fillStyle = '#2c3a34';
  const w = 3;
  ctx.fillRect(bird.x, y, 2, 1);
  ctx.fillRect(bird.x - w, y - Math.round(flap * 2), w, 1);
  ctx.fillRect(bird.x + 2, y - Math.round(flap * 2), w, 1);
}

/* ============================================================================
   The building.
   Geometry comes from the backend layout: building box, zones (floors) and desks.
   ========================================================================== */

function drawBuildingShell(ctx, b) {
  const { x, y, width: w, height: h } = b;

  // Ground shadow.
  ctx.save();
  ctx.globalAlpha = 0.35;
  px(ctx, x - 10, y + h, w + 20, 10, '#070f0d');
  ctx.restore();

  // Outer shell with a lit left edge and a dark right edge.
  px(ctx, x - 12, y - 26, w + 24, h + 26, PAL.shell);
  px(ctx, x - 12, y - 26, 5, h + 26, PAL.shellLight);
  px(ctx, x + w + 7, y - 26, 5, h + 26, PAL.shellDark);
  px(ctx, x - 12, y - 26, w + 24, 4, PAL.shellLight);

  // Structural columns between floors.
  const rnd = mulberry32(0x5511);
  for (let cx = x + 26; cx < x + w - 20; cx += 96) {
    px(ctx, cx, y - 18, 5, h + 16, '#16241f');
    px(ctx, cx, y - 18, 1, h + 16, '#2b3f37');
    if (rnd() > 0.6) px(ctx, cx - 2, y + 40, 9, 3, '#16241f');
  }

  // Parapet and roof plant.
  px(ctx, x - 18, y - 34, w + 36, 9, PAL.shellLight);
  px(ctx, x - 18, y - 34, w + 36, 2, '#31493f');
  px(ctx, x + 60, y - 58, 74, 24, '#22342d');
  px(ctx, x + 60, y - 58, 74, 2, '#31493f');
  px(ctx, x + 150, y - 50, 40, 16, '#22342d');
  px(ctx, x + 210, y - 46, 22, 12, '#22342d');
  // Antenna mast.
  px(ctx, x + w - 120, y - 96, 3, 62, '#2b3f37');
  px(ctx, x + w - 132, y - 74, 27, 2, '#2b3f37');
  px(ctx, x + w - 126, y - 84, 15, 2, '#2b3f37');
  // Satellite dish.
  px(ctx, x + w - 210, y - 54, 4, 20, '#2b3f37');
  ctx.fillStyle = '#33493f';
  ctx.beginPath();
  ctx.arc(x + w - 208, y - 58, 15, Math.PI * 0.15, Math.PI * 1.15);
  ctx.fill();
}

/** Roof fans and the beacon are animated, so they are drawn per frame. */
function drawRoofDetails(ctx, b, time) {
  const { x, y, width: w } = b;
  // Two extractor fans.
  const fans = [[x + 78, y - 46], [x + 116, y - 46]];
  for (let i = 0; i < fans.length; i += 1) {
    const [fx, fy] = fans[i];
    const a = time * (i === 0 ? 3.2 : -2.4);
    ctx.save();
    ctx.translate(fx, fy);
    ctx.rotate(a);
    ctx.fillStyle = '#3b544a';
    for (let bl = 0; bl < 4; bl += 1) {
      ctx.rotate(Math.PI / 2);
      ctx.fillRect(0, -2, 11, 4);
    }
    ctx.restore();
    px(ctx, fx - 2, fy - 2, 4, 4, '#577466');
  }
  // Aircraft warning beacon.
  const beat = (Math.sin(time * 2.4) + 1) / 2;
  if (beat > 0.55) {
    px(ctx, x + w - 122, y - 99, 5, 4, PAL.red);
    glow(ctx, x + w - 120, y - 97, 20, 'rgba(217,112,90,0.85)', beat * 0.6);
  }
}

/** The studio's neon sign above the cutaway. */
function drawSignage(ctx, b, time) {
  const label = 'AUTONOMOUS AI STUDIO';
  const scale = 2;
  const w = textWidth(label, scale, 1);
  const sx = b.x + (b.width - w) / 2;
  const sy = b.y - 22;
  const pulse = 0.72 + Math.sin(time * 1.6) * 0.08 + Math.sin(time * 5.3) * 0.03;

  px(ctx, sx - 12, sy - 6, w + 24, 24, '#101c19');
  outline(ctx, sx - 12, sy - 6, w + 24, 24, '#2b3f37');
  drawText(ctx, label, sx, sy, PAL.gold, scale, 1);
  ctx.save();
  ctx.globalAlpha = 0.5 * pulse;
  drawText(ctx, label, sx, sy, '#fff0cf', scale, 1);
  ctx.restore();
  glow(ctx, b.x + b.width / 2, sy + 6, 130, 'rgba(221,174,106,0.30)', 0.45 * pulse);
}

/** Glass elevator shaft. The cabin position is scenery, not a backend signal. */
function drawElevatorShaft(ctx, b, zones) {
  const ex = b.x + (b.elevator_x !== undefined ? b.elevator_x - b.x : b.width - 100);
  const ew = b.elevator_width || 90;
  px(ctx, ex, b.y - 18, ew, b.height + 16, '#101f1c');
  outline(ctx, ex, b.y - 18, ew, b.height + 16, '#2b3f37');
  // Guide rails.
  px(ctx, ex + 6, b.y - 14, 2, b.height + 8, '#24382f');
  px(ctx, ex + ew - 8, b.y - 14, 2, b.height + 8, '#24382f');
  // Floor markers taken from the real zones.
  for (const z of zones) {
    const cy = z.y + z.height - 12;
    px(ctx, ex + 2, cy, ew - 4, 1, '#1d2d27');
    drawText(ctx, `FL ${z.floor}`, ex + 12, cy - 9, '#3f5a4e', 1, 1);
  }
  return { ex, ew };
}

function drawElevatorCab(ctx, b, shaft, time, lift) {
  const cy = lift.y;
  const { ex, ew } = shaft;
  const cw = ew - 20;
  const cx = ex + 10;

  px(ctx, cx + cw / 2 - 1, b.y - 14, 2, cy - b.y + 14, '#3a5147');
  block(ctx, cx, cy, cw, 54, '#23372f', '#3c5649', '#16241f');
  px(ctx, cx + 3, cy + 4, cw - 6, 42, lift.moving ? PAL.glassLit : '#1c332f');
  ctx.save();
  ctx.globalAlpha = lift.moving ? 0.5 : 0.22;
  px(ctx, cx + 3, cy + 4, cw - 6, 12, '#6f9b8c');
  ctx.restore();

  // Someone inside, seen through the glass while the cab travels.
  const trip = lift.trip;
  if (trip && trip.phase === 'travel') {
    drawCourier(ctx, cx + cw / 2, cy + 48, time, 0, true);
  }

  // Doors part only while the cab is standing at a floor with someone stepping through;
  // a travelling lift keeps them shut, as a real one does.
  const dwelling = Boolean(trip && (trip.phase === 'board' || trip.phase === 'alight'));
  const gap = dwelling ? 7 : 1;
  px(ctx, cx + cw / 2 - gap - 1, cy + 4, 2, 42, '#1a2a25');
  px(ctx, cx + cw / 2 + gap - 1, cy + 4, 2, 42, '#1a2a25');

  // Direction lamp only when travelling.
  if (lift.moving) {
    const up = lift.target < cy;
    px(ctx, cx + cw / 2 - 2, cy - 5, 4, 4, up ? PAL.green : PAL.amber);
    glow(ctx, cx + cw / 2, cy + 26, 46, 'rgba(110,190,170,0.35)', 0.4);
  } else {
    px(ctx, cx + cw / 2 - 2, cy - 5, 4, 4, '#2b3f37');
  }
  const caption = dwelling ? 'DOORS' : lift.moving ? 'MOVING' : 'IDLE';
  const lit = dwelling || lift.moving;
  drawText(
    ctx,
    caption,
    cx + (cw - textWidth(caption, 1, 1)) / 2,
    cy + 46,
    lit ? '#8fd8c4' : '#4d6b5c',
    1,
    1,
  );
}

/* ============================================================================
   Lift courier: the visible carrier of a workflow token between floors.
   ========================================================================== */

/** Runner colours, fixed so the same figure is recognisable on every trip. */
const COURIER_LOOK = {
  coat: '#3f6b5c',
  trousers: '#25352f',
  skin: '#c8a284',
  hair: '#2f2620',
  crate: '#8a6a3a',
  crateTop: '#d8b06a',
};

/**
 * A runner walking a workflow token to or from the lift.
 *
 * This figure is not an agent and never carries a name: it is the token's own journey drawn
 * as movement. It exists only while the backend says a token changed floor, and it is holding
 * the same crate `drawProjectToken` draws, so what the viewer follows across the building is
 * the work itself.
 */
function drawCourier(ctx, cx, floorY, time, facing, carrying) {
  const height = 34;
  const y = floorY - height;
  const step = Math.sin(time * 9) * (facing === 0 ? 0 : 1);
  const s = facing < 0 ? -1 : 1;

  ctx.save();
  ctx.globalAlpha = 0.32;
  px(ctx, cx - 7, floorY - 2, 15, 3, '#070f0d');
  ctx.restore();

  // Legs, mid-stride.
  px(ctx, cx - 4 + step * 3, y + height * 0.6, 5, height * 0.36, COURIER_LOOK.trousers);
  px(ctx, cx + 1 - step * 3, y + height * 0.6, 5, height * 0.36, '#1b2622');
  px(ctx, cx - 5 + step * 3, y + height * 0.95, 7, 3, '#131c19');
  px(ctx, cx - step * 3, y + height * 0.95, 7, 3, '#131c19');

  // Torso and the trailing arm.
  px(ctx, cx - 7, y + height * 0.28, 15, height * 0.35, COURIER_LOOK.coat);
  px(ctx, cx - 7, y + height * 0.28, 15, 1, '#ffffff22');
  px(ctx, cx - 8 * s, y + height * 0.31 + step * 2, 3, height * 0.24, COURIER_LOOK.coat);

  // Head.
  px(ctx, cx - 5, y + height * 0.05, 11, 11, COURIER_LOOK.skin);
  px(ctx, cx - 5, y + height * 0.03, 11, 3, COURIER_LOOK.hair);
  px(ctx, cx - 2 + s, y + height * 0.15, 2, 2, '#2a211c');

  // The crate, held out in front — the same object the token itself is drawn as.
  if (carrying) {
    const bx = cx + s * 9;
    const by = y + height * 0.42;
    px(ctx, cx + s * 5, y + height * 0.34, 4, 3, COURIER_LOOK.skin);
    block(ctx, bx - 6, by - 6, 12, 12, COURIER_LOOK.crate, '#b08a4a', '#5c4626');
    px(ctx, bx - 6, by - 1, 12, 2, COURIER_LOOK.crateTop);
    px(ctx, bx - 1, by - 6, 2, 12, COURIER_LOOK.crateTop);
  }
}

/* ============================================================================
   Interior shells: floor slabs, back walls, windows, signage per zone.
   ========================================================================== */

function drawZoneShell(ctx, zone, b) {
  const st = zoneStyle(zone.zone_type);
  const { x, y, width: w, height: h } = zone;

  // Back wall with a subtle vertical gradient and panel seams.
  const g = ctx.createLinearGradient(0, y, 0, y + h);
  g.addColorStop(0, st.wall);
  g.addColorStop(1, '#101c19');
  ctx.fillStyle = g;
  ctx.fillRect(x, y, w, h);

  const rnd = mulberry32(hash32(zone.id));
  for (let sx = x + 20; sx < x + w; sx += 60) {
    ctx.globalAlpha = 0.25;
    px(ctx, sx, y + 4, 1, h - 12, '#0c1614');
    ctx.globalAlpha = 1;
  }
  // Skirting and floor slab.
  px(ctx, x, y + h - 12, w, 12, PAL.slab);
  px(ctx, x, y + h - 12, w, 2, PAL.slabEdge);
  px(ctx, x, y + h - 3, w, 3, '#1c2b25');
  // Floor reflection strip.
  ctx.globalAlpha = 0.12;
  px(ctx, x, y + h - 10, w, 4, st.accent);
  ctx.globalAlpha = 1;

  // Ceiling fixtures: housing here, the light cone is painted per frame.
  for (let lx = x + 44; lx < x + w - 30; lx += 116) {
    px(ctx, lx + 14, y, 4, 4, '#33453c');
    block(ctx, lx, y + 4, 34, 4, '#48604f', '#5c7867', '#26332d');
    px(ctx, lx + 2, y + 8, 30, 1, '#e8f0d8');
  }

  // Floor label. Several zones can share a floor, so only the first one carries the number.
  drawText(ctx, st.name, x + 8, y + 8, '#4d6b5c', 1, 1);
  if (zone.isFloorLead) {
    const fl = `FLOOR ${zone.floor}`;
    const right = zone.floorRight !== undefined ? zone.floorRight : x + w;
    drawText(ctx, fl, right - textWidth(fl, 1, 1) - 8, y + 8, '#3d584b', 1, 1);
  }

  // A couple of windows punched into the back wall on the upper floors.
  if (zone.floor >= 2) {
    for (let i = 0; i < 2; i += 1) {
      const wx = x + 30 + i * (w - 150) + rnd() * 20;
      px(ctx, wx, y + 22, 54, 44, PAL.glass);
      outline(ctx, wx, y + 22, 54, 44, '#31493f');
      px(ctx, wx + 26, y + 22, 2, 44, '#31493f');
      px(ctx, wx, y + 42, 54, 2, '#31493f');
      ctx.globalAlpha = 0.35;
      px(ctx, wx + 2, y + 24, 22, 16, '#4d7a72');
      ctx.globalAlpha = 1;
    }
  }
}

/* ---------------------------------------------------------------- furniture */

function drawDeskUnit(ctx, dx, dy, accent, variant) {
  // Desk top, legs and cable tray. dy is the floor line the desk stands on.
  const topY = dy - 26;
  block(ctx, dx - 34, topY, 68, 6, '#5a4632', '#755c42', '#3a2c20');
  px(ctx, dx - 30, topY + 6, 4, 20, '#3f3226');
  px(ctx, dx + 26, topY + 6, 4, 20, '#3f3226');
  px(ctx, dx - 26, topY + 18, 52, 2, '#2f2519');
  // Drawers on one side.
  if (variant % 2 === 0) {
    block(ctx, dx + 8, topY + 6, 22, 20, '#4a3a2a', '#5d4934', '#2e2419');
    px(ctx, dx + 12, topY + 11, 14, 2, '#7d654a');
    px(ctx, dx + 12, topY + 18, 14, 2, '#7d654a');
  } else {
    block(ctx, dx - 30, topY + 6, 20, 20, '#4a3a2a', '#5d4934', '#2e2419');
    px(ctx, dx - 26, topY + 12, 12, 2, '#7d654a');
  }
  // Chair
  px(ctx, dx - 6, dy - 16, 14, 3, '#2b3a33');
  px(ctx, dx - 1, dy - 13, 3, 10, '#243128');
  px(ctx, dx - 7, dy - 3, 15, 2, '#243128');
  px(ctx, dx + 6, dy - 26, 4, 12, '#2b3a33');
  // Accent cable
  px(ctx, dx - 2, topY + 20, 2, 6, accent);
}

function drawMonitor(ctx, mx, my, w, h, accent) {
  block(ctx, mx, my, w, h, '#111d1a', '#2a3d35', '#0a1210');
  px(ctx, mx + 2, my + 2, w - 4, h - 4, '#0d1a20');
  px(ctx, mx + w / 2 - 3, my + h, 6, 4, '#2a3d35');
  px(ctx, mx + w / 2 - 8, my + h + 4, 16, 2, '#2a3d35');
  px(ctx, mx, my, w, 1, accent);
}

/** Animated screen content. Each screen kind gets its own motion so nothing looks cloned. */
function drawScreenContent(ctx, kind, mx, my, w, h, time, seed, accent, active) {
  const rnd = mulberry32(seed);
  const ix = mx + 2;
  const iy = my + 2;
  const iw = w - 4;
  const ih = h - 4;
  const speed = active ? 1 : 0.25;

  ctx.save();
  ctx.beginPath();
  ctx.rect(ix, iy, iw, ih);
  ctx.clip();

  if (kind === 'chart') {
    px(ctx, ix, iy, iw, ih, '#0b1a1f');
    const bars = 9;
    for (let i = 0; i < bars; i += 1) {
      const base = 0.25 + rnd() * 0.6;
      const wob = Math.sin(time * speed * 1.7 + i) * 0.14;
      const bh = clamp(base + wob, 0.08, 1) * (ih - 6);
      px(ctx, ix + 2 + i * (iw - 4) / bars, iy + ih - 2 - bh, (iw - 6) / bars - 1, bh, i % 3 === 0 ? accent : '#3d6f63');
    }
    px(ctx, ix, iy + ih - 2, iw, 1, '#2b4f47');
  } else if (kind === 'doc') {
    px(ctx, ix, iy, iw, ih, '#141d17');
    const lines = Math.floor(ih / 4);
    const caret = Math.floor((time * speed * 3) % lines);
    for (let i = 0; i < lines; i += 1) {
      const lw = (0.35 + rnd() * 0.6) * (iw - 8);
      px(ctx, ix + 3, iy + 3 + i * 4, lw, 1, i === caret && active ? accent : '#4c6b5c');
    }
    if (active && Math.sin(time * 6) > 0) px(ctx, ix + 3, iy + 3 + caret * 4, 3, 2, PAL.white);
  } else if (kind === 'timeline') {
    px(ctx, ix, iy, iw, ih, '#0d1922');
    px(ctx, ix + 2, iy + 3, iw - 4, ih * 0.42, '#16303a');
    for (let i = 0; i < 6; i += 1) {
      px(ctx, ix + 3 + i * 6, iy + 5, 5, ih * 0.34, i % 2 ? '#2a5566' : '#22485a');
    }
    const trackY = iy + ih * 0.55;
    px(ctx, ix + 2, trackY, iw - 4, 3, '#20404c');
    px(ctx, ix + 2, trackY + 5, iw - 4, 3, '#1b3742');
    const play = ((time * speed * 0.22) % 1) * (iw - 6);
    px(ctx, ix + 3 + play, iy + 3, 1, ih - 6, accent);
  } else if (kind === 'waveform') {
    px(ctx, ix, iy, iw, ih, '#160f1a');
    const mid = iy + ih / 2;
    for (let i = 0; i < iw - 4; i += 2) {
      const amp = (Math.sin(i * 0.5 + time * speed * 5) * 0.5 + Math.sin(i * 0.19 - time * speed * 3) * 0.5) * (ih / 2 - 2);
      const a = Math.abs(amp) * (active ? 1 : 0.35);
      px(ctx, ix + 2 + i, mid - a, 1, a * 2 + 1, i % 6 === 0 ? accent : '#7d5a86');
    }
  } else if (kind === 'graph') {
    px(ctx, ix, iy, iw, ih, '#0b1c1a');
    for (let gx = ix + 4; gx < ix + iw; gx += 7) px(ctx, gx, iy + 2, 1, ih - 4, '#16302b');
    let prev = null;
    for (let i = 0; i <= 10; i += 1) {
      const nx = ix + 2 + (i * (iw - 4)) / 10;
      const ny = iy + ih - 3 - (Math.sin(i * 0.7 + time * speed * 0.9) * 0.35 + 0.5) * (ih - 8);
      px(ctx, nx, ny, 2, 2, accent);
      if (prev) {
        const steps = 6;
        for (let s = 1; s < steps; s += 1) {
          px(ctx, lerp(prev[0], nx, s / steps), lerp(prev[1], ny, s / steps), 1, 1, '#3f7d70');
        }
      }
      prev = [nx, ny];
    }
  } else if (kind === 'upload') {
    px(ctx, ix, iy, iw, ih, '#1c1512');
    drawText(ctx, 'QUEUE', ix + 3, iy + 3, '#6d5a4a', 1, 1);
    for (let i = 0; i < 3; i += 1) {
      const p = active ? ((time * speed * 0.18 + i * 0.31) % 1) : 0.2 + i * 0.1;
      px(ctx, ix + 3, iy + 12 + i * 7, iw - 8, 4, '#2b211c');
      px(ctx, ix + 3, iy + 12 + i * 7, (iw - 8) * p, 4, i === 0 ? accent : '#8a5a48');
    }
  } else {
    px(ctx, ix, iy, iw, ih, '#0f1b18');
    for (let i = 0; i < 5; i += 1) {
      px(ctx, ix + 3, iy + 4 + i * 5, (0.4 + rnd() * 0.5) * (iw - 8), 2, '#3d6152');
    }
  }

  // Scanline + glass sheen.
  ctx.globalAlpha = 0.12;
  for (let sy = iy; sy < iy + ih; sy += 3) px(ctx, ix, sy, iw, 1, '#000000');
  ctx.globalAlpha = 0.08;
  px(ctx, ix, iy, iw, Math.max(2, ih / 3), '#ffffff');
  ctx.globalAlpha = 1;
  ctx.restore();
}

function drawPlant(ctx, x, y, seed) {
  const rnd = mulberry32(seed);
  block(ctx, x - 7, y - 12, 14, 12, '#8a5a3c', '#a67049', '#5c3b26');
  px(ctx, x - 7, y - 12, 14, 2, '#b07b52');
  for (let i = 0; i < 7; i += 1) {
    const lean = (rnd() - 0.5) * 16;
    const hgt = 12 + rnd() * 16;
    px(ctx, x + lean * 0.4, y - 12 - hgt, 3, hgt, rnd() > 0.5 ? PAL.leafMid : PAL.leafLight);
    px(ctx, x + lean, y - 14 - hgt, 6, 5, PAL.leafLight);
  }
}

function drawMug(ctx, x, y, color) {
  px(ctx, x, y - 5, 7, 5, color);
  px(ctx, x + 7, y - 4, 2, 3, color);
  px(ctx, x, y - 5, 7, 1, '#ffffff33');
}

function drawDeskPhone(ctx, x, y, accent) {
  block(ctx, x, y - 5, 13, 5, '#22302a', '#33463d', '#141f1b');
  px(ctx, x + 1, y - 8, 11, 3, '#2b3b34');
  px(ctx, x + 2, y - 7, 3, 1, accent);
  px(ctx, x + 10, y - 4, 3, 3, '#1a2621');
}

function drawWallClock(ctx, x, y, time) {
  px(ctx, x - 8, y - 8, 16, 16, '#22322b');
  outline(ctx, x - 8, y - 8, 16, 16, '#3c5649');
  px(ctx, x - 5, y - 5, 10, 10, '#dfe8dc');
  const hh = time * 0.05;
  const mm = time * 0.6;
  px(ctx, x + Math.cos(hh) * 2, y + Math.sin(hh) * 2, 2, 2, '#233b37');
  px(ctx, x + Math.cos(mm) * 3, y + Math.sin(mm) * 3, 1, 1, '#9a573c');
}

/* ============================================================================
   Department interiors.
   Each zone_type gets its own props so no two floors read the same. Static parts go into
   the cached buffer; anything that moves is listed in the returned "live" descriptors and
   redrawn every frame.
   ========================================================================== */

/**
 * Fill the upper half of a double-height ground-floor unit.
 *
 * The ground floor is 200px tall against 130px upstairs, so furniture that stops at desk
 * height leaves the top two thirds bare — the floor read as emptier than the ones above it
 * even though it holds more departments. This draws what a tall street-level volume actually
 * has above head height: a service mezzanine with a railing, pendant lights on their drops,
 * exposed ducting, and one piece of wall furniture chosen per department.
 *
 * All of it is architecture, not activity: nothing here depends on or implies any agent state.
 */
function drawTallVolume(ctx, zone, st, live, seed) {
  const rnd = mulberry32(seed ^ 0x5eed);
  const x = zone.x;
  const w = zone.width;
  const railY = zone.y + Math.round(zone.height * 0.40);

  // Exposed ducting under the slab above, with hanger straps.
  px(ctx, x + 6, zone.y + 12, w - 12, 10, '#243530');
  px(ctx, x + 6, zone.y + 12, w - 12, 2, '#33473d');
  px(ctx, x + 6, zone.y + 20, w - 12, 2, '#1a2723');
  for (let hx = x + 18; hx < x + w - 16; hx += 34) {
    px(ctx, hx, zone.y + 6, 2, 7, '#2c403700');
    px(ctx, hx, zone.y + 4, 2, 9, '#2c4037');
    px(ctx, hx + 10, zone.y + 22, 12, 2, '#1f2e29');
  }

  // Service mezzanine: a walkway slab with a railing, the way a tall lobby is serviced.
  px(ctx, x + 4, railY, w - 8, 5, '#22322c');
  px(ctx, x + 4, railY, w - 8, 1, '#354a40');
  px(ctx, x + 4, railY + 5, w - 8, 2, '#16241f');
  px(ctx, x + 6, railY - 14, w - 12, 2, st.accent + '55');
  for (let bx = x + 10; bx < x + w - 8; bx += 16) {
    px(ctx, bx, railY - 13, 2, 13, '#2e433a');
  }

  // Pendant lights hanging from the ceiling into the volume.
  const lamps = Math.max(2, Math.round(w / 90));
  for (let i = 0; i < lamps; i += 1) {
    const lx = Math.round(x + (w * (i + 0.5)) / lamps);
    const drop = 26 + Math.round(rnd() * 10);
    px(ctx, lx, zone.y + 22, 1, drop, '#2c4037');
    px(ctx, lx - 7, zone.y + 22 + drop, 15, 4, '#33473d');
    px(ctx, lx - 5, zone.y + 26 + drop, 11, 3, '#e8d9a8');
    live.lamps.push({
      x: lx,
      y: zone.y + 28 + drop,
      r: 74,
      color: 'rgba(232,217,168,0.16)',
    });
  }
  return railY;
}

/**
 * One piece of wall furniture per ground-floor department, mounted above the mezzanine rail.
 *
 * Each is a fixture a real unit of that kind would have — a rack status wall, a canteen clock
 * and noticeboard, a dispatch board, a hoarding. None of them display live figures: a board
 * that showed numbers here would be asserting something the backend has not said.
 */
function drawTallVolumeSign(ctx, zone, st, live, railY, seed) {
  const rnd = mulberry32(seed ^ 0x51a6);
  const cx = Math.round(zone.x + zone.width / 2);
  const top = railY - 62;

  switch (zone.zone_type) {
    case 'SERVER': {
      // Rack status wall: a grid of indicator tiles and a cable ladder climbing to it.
      const gw = Math.min(zone.width - 40, 132);
      const gx = Math.round(cx - gw / 2);
      block(ctx, gx, top, gw, 44, '#1a2a25', '#2a3f37', '#101c18');
      for (let r = 0; r < 3; r += 1) {
        for (let c = 0; c < Math.floor(gw / 22); c += 1) {
          const tx = gx + 6 + c * 22;
          const ty = top + 6 + r * 13;
          px(ctx, tx, ty, 16, 9, '#12201c');
          live.leds.push({
            x: tx + 3,
            y: ty + 3,
            color: PAL.green,
            phase: (r * 7 + c) * 0.6,
            rate: 0.9 + rnd() * 0.6,
          });
        }
      }
      for (let ly = railY + 8; ly < zone.y + zone.height - 40; ly += 12) {
        px(ctx, zone.x + 14, ly, 18, 2, '#2a3a33');
      }
      px(ctx, zone.x + 14, railY + 8, 2, zone.height * 0.4, '#243530');
      px(ctx, zone.x + 30, railY + 8, 2, zone.height * 0.4, '#243530');
      break;
    }

    case 'LOUNGE': {
      // Canteen wall: a clock, a corkboard of pinned notes, and hanging planters.
      const clockX = cx - 46;
      px(ctx, clockX - 13, top + 6, 26, 26, '#2a3a33');
      px(ctx, clockX - 10, top + 9, 20, 20, '#d8e0cf');
      px(ctx, clockX - 1, top + 13, 2, 8, '#2a3a33');
      px(ctx, clockX - 1, top + 19, 7, 2, '#2a3a33');
      block(ctx, cx + 4, top, 74, 46, '#5a4632', '#755c42', '#3a2c20');
      px(ctx, cx + 8, top + 4, 66, 38, '#7b6448');
      for (let i = 0; i < 5; i += 1) {
        const nx = cx + 12 + (i % 3) * 22;
        const ny = top + 8 + Math.floor(i / 3) * 18;
        px(ctx, nx, ny, 18, 14, pick(['#cfc5a4', '#c9d8c0', '#e0cfa8'], rnd));
        px(ctx, nx + 8, ny - 1, 2, 2, PAL.red);
      }
      for (let i = 0; i < 2; i += 1) {
        const hx = zone.x + 22 + i * (zone.width - 52);
        px(ctx, hx + 5, zone.y + 24, 1, 20, '#2c4037');
        px(ctx, hx, zone.y + 44, 12, 7, '#6a4f38');
        px(ctx, hx - 2, zone.y + 44, 5, 12, PAL.leafDark);
        px(ctx, hx + 9, zone.y + 44, 5, 15, PAL.leafDark);
      }
      break;
    }

    case 'PUBLISH': {
      // Dispatch board: slot rows with no numbers on them, and a wall clock.
      const bw = Math.min(zone.width - 36, 128);
      const bx = Math.round(cx - bw / 2);
      block(ctx, bx, top, bw, 48, '#1e2a24', '#2f4239', '#131e1a');
      px(ctx, bx + 4, top + 4, bw - 8, 9, '#26332c');
      drawText(ctx, 'DISPATCH', bx + 8, top + 6, st.accent, 1, 1);
      for (let r = 0; r < 3; r += 1) {
        const ry = top + 17 + r * 10;
        px(ctx, bx + 6, ry, bw - 44, 6, '#22302a');
        px(ctx, bx + bw - 34, ry, 26, 6, '#22302a');
        live.leds.push({ x: bx + bw - 14, y: ry + 1, color: PAL.amber, phase: r * 1.1, rate: 1.4 });
      }
      break;
    }

    case 'SHOP': {
      // Hoarding above the shopfront: the slot the studio is selling, empty until sold.
      const bw = zone.width - 30;
      const bx = zone.x + 15;
      block(ctx, bx, top + 6, bw, 40, '#241d14', '#38301f', '#161009');
      px(ctx, bx + 4, top + 10, bw - 8, 32, '#2e2618');
      outline(ctx, bx + 4, top + 10, bw - 8, 32, PAL.gold + '66');
      const label = 'YOUR AD HERE';
      const lw = textWidth(label, 1, 1);
      drawText(ctx, label, Math.round(cx - lw / 2), top + 24, PAL.gold, 1, 1);
      live.lamps.push({ x: cx, y: top + 26, r: 62, color: 'rgba(221,174,106,0.18)' });
      break;
    }

    default:
      break;
  }
}

function interiorFor(zone, ctx, live) {
  const st = zoneStyle(zone.zone_type);
  const floorY = zone.y + zone.height - 12;
  const seed = hash32(zone.id);
  const rnd = mulberry32(seed);
  const desks = zone.desks || [];

  const addScreen = (kind, mx, my, w, h) =>
    live.screens.push({ kind, mx, my, w, h, seed: hash32(`${zone.id}${mx}${my}`), accent: st.accent, zoneId: zone.id, deskX: mx + w / 2 });

  // The ground floor is double height; anything that tall needs its upper volume built.
  const railY = zone.height >= 180 ? drawTallVolume(ctx, zone, st, live, seed) : null;
  if (railY !== null) drawTallVolumeSign(ctx, zone, st, live, railY, seed);

  switch (zone.zone_type) {
    case 'DIRECTOR': {
      // Bookshelf, awards, city map, executive desk with a laptop and a phone.
      block(ctx, zone.x + 24, floorY - 74, 74, 74, '#4a3a2a', '#5d4934', '#2e2419');
      for (let s = 0; s < 4; s += 1) {
        const shelfY = floorY - 68 + s * 17;
        px(ctx, zone.x + 26, shelfY + 14, 70, 2, '#2e2419');
        let bx = zone.x + 28;
        while (bx < zone.x + 92) {
          const bw = 4 + Math.floor(rnd() * 4);
          const bh = 9 + Math.floor(rnd() * 5);
          px(ctx, bx, shelfY + 14 - bh, bw, bh, pick(['#8a4a3c', '#3f6d63', '#a08243', '#6a6a86', '#7c4550'], rnd));
          bx += bw + 1;
        }
      }
      drawPlant(ctx, zone.x + 128, floorY, seed + 3);
      // Awards on a plinth.
      block(ctx, zone.x + zone.width - 96, floorY - 30, 56, 30, '#3a4a40', '#4d6155', '#20302a');
      for (let i = 0; i < 3; i += 1) {
        const ax = zone.x + zone.width - 88 + i * 17;
        px(ctx, ax, floorY - 44, 8, 10, PAL.gold);
        px(ctx, ax + 2, floorY - 34, 4, 4, '#a5803f');
        px(ctx, ax - 1, floorY - 30, 10, 2, '#a5803f');
      }
      drawWallClockPlaceholder(ctx, live, zone.x + zone.width - 150, zone.y + 34);

      for (const d of desks) {
        drawDeskUnit(ctx, d.x, floorY, st.accent, 0);
        drawMonitor(ctx, d.x - 26, floorY - 54, 34, 24, st.accent);
        addScreen('chart', d.x - 26, floorY - 54, 34, 24);
        // Laptop
        block(ctx, d.x + 4, floorY - 34, 22, 3, '#2a3a33', '#3d5449', '#16241f');
        px(ctx, d.x + 6, floorY - 46, 18, 12, '#111d1a');
        addScreen('graph', d.x + 6, floorY - 46, 18, 12);
        drawDeskPhone(ctx, d.x + 12, floorY - 26, PAL.green);
        drawMug(ctx, d.x - 34, floorY - 26, '#b8593f');
        live.lamps.push({ x: d.x - 20, y: floorY - 56, r: 62, color: 'rgba(221,174,106,0.30)' });
      }
      break;
    }

    case 'RESEARCH': {
      // Evidence board with pinned cards and string, archive boxes, lab desks.
      const bx = zone.x + zone.width / 2 - 66;
      const by = zone.y + 24;
      block(ctx, bx, by, 132, 60, '#2f3a2c', '#43503c', '#1c241a');
      outline(ctx, bx, by, 132, 60, '#54634a');
      const pins = [];
      for (let i = 0; i < 6; i += 1) {
        const cardX = bx + 8 + (i % 3) * 42 + rnd() * 4;
        const cardY = by + 8 + Math.floor(i / 3) * 26;
        px(ctx, cardX, cardY, 26, 18, pick(['#d8d2b8', '#c9d8c0', '#e0cfa8'], rnd));
        px(ctx, cardX + 2, cardY + 3, 20, 1, '#6a7060');
        px(ctx, cardX + 2, cardY + 7, 16, 1, '#6a7060');
        px(ctx, cardX + 2, cardY + 11, 18, 1, '#6a7060');
        px(ctx, cardX + 12, cardY - 1, 2, 2, PAL.red);
        pins.push([cardX + 13, cardY]);
      }
      ctx.strokeStyle = 'rgba(217,112,90,0.55)';
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let i = 0; i < pins.length - 1; i += 1) {
        ctx.moveTo(pins[i][0] + 0.5, pins[i][1] + 0.5);
        ctx.lineTo(pins[i + 1][0] + 0.5, pins[i + 1][1] + 0.5);
      }
      ctx.stroke();

      // Archive boxes
      for (let i = 0; i < 3; i += 1) {
        const boxX = zone.x + 26 + i * 30;
        block(ctx, boxX, floorY - 22 - (i % 2) * 20, 26, 20, '#7a6244', '#96794f', '#4e3e2a');
        px(ctx, boxX + 6, floorY - 14 - (i % 2) * 20, 14, 3, '#5c4a30');
      }
      drawPlant(ctx, zone.x + zone.width - 40, floorY, seed + 7);

      desks.forEach((d, i) => {
        drawDeskUnit(ctx, d.x, floorY, st.accent, i);
        drawMonitor(ctx, d.x - 30, floorY - 56, 26, 20, st.accent);
        drawMonitor(ctx, d.x - 2, floorY - 58, 30, 22, st.accent);
        addScreen(i === 0 ? 'doc' : 'graph', d.x - 30, floorY - 56, 26, 20);
        addScreen(i === 0 ? 'graph' : 'doc', d.x - 2, floorY - 58, 30, 22);
        // Desk lamp with a warm pool.
        px(ctx, d.x + 26, floorY - 40, 2, 14, '#3c5044');
        px(ctx, d.x + 22, floorY - 44, 10, 4, '#4d6155');
        live.lamps.push({ x: d.x + 27, y: floorY - 38, r: 52, color: 'rgba(120,220,200,0.22)' });
        drawMug(ctx, d.x + 14, floorY - 26, '#4f8a7a');
        // Paper stack
        px(ctx, d.x - 34, floorY - 30, 14, 4, '#d8d2b8');
        px(ctx, d.x - 33, floorY - 32, 12, 2, '#e6e0c6');
      });
      break;
    }

    case 'SCRIPT': {
      // Storyboard wall, floor lamp, bookshelf, typewriter-ish desk.
      const bx = zone.x + 30;
      const by = zone.y + 26;
      block(ctx, bx, by, 176, 62, '#7a5a34', '#96703f', '#4e3a20');
      outline(ctx, bx, by, 176, 62, '#a07b45');
      const cards = [];
      for (let i = 0; i < 5; i += 1) {
        const cx = bx + 10 + i * 33;
        const cy = by + 12 + (i % 2) * 22;
        px(ctx, cx, cy, 26, 18, '#efe6cc');
        px(ctx, cx + 2, cy + 2, 22, 9, '#c7ba99');
        px(ctx, cx + 2, cy + 13, 16, 1, '#8a7f66');
        cards.push([cx + 13, cy + 9]);
      }
      ctx.strokeStyle = 'rgba(217,112,90,0.6)';
      ctx.beginPath();
      for (let i = 0; i < cards.length - 1; i += 1) {
        ctx.moveTo(cards[i][0] + 0.5, cards[i][1] + 0.5);
        ctx.lineTo(cards[i + 1][0] + 0.5, cards[i + 1][1] + 0.5);
      }
      ctx.stroke();

      // Floor lamp
      px(ctx, zone.x + zone.width - 60, floorY - 78, 3, 78, '#3c5044');
      px(ctx, zone.x + zone.width - 70, floorY - 90, 23, 13, '#8a6b45');
      px(ctx, zone.x + zone.width - 66, floorY - 3, 15, 3, '#3c5044');
      live.lamps.push({ x: zone.x + zone.width - 58, y: floorY - 80, r: 78, color: 'rgba(240,166,90,0.26)' });

      // Bookshelf + crumpled paper
      block(ctx, zone.x + zone.width - 130, floorY - 46, 46, 46, '#4a3a2a', '#5d4934', '#2e2419');
      for (let s = 0; s < 2; s += 1) {
        let sx = zone.x + zone.width - 126;
        while (sx < zone.x + zone.width - 90) {
          const bw = 4 + Math.floor(rnd() * 3);
          px(ctx, sx, floorY - 40 + s * 20 - 8, bw, 10, pick(['#8a4a3c', '#a08243', '#3f6d63'], rnd));
          sx += bw + 1;
        }
      }
      for (let i = 0; i < 4; i += 1) {
        px(ctx, zone.x + 220 + rnd() * 120, floorY - 4, 5, 4, '#cfc5a4');
      }

      desks.forEach((d, i) => {
        drawDeskUnit(ctx, d.x, floorY, st.accent, i);
        drawMonitor(ctx, d.x - 24, floorY - 56, 40, 26, st.accent);
        addScreen('doc', d.x - 24, floorY - 56, 40, 26);
        drawMug(ctx, d.x + 20, floorY - 26, '#a8763f');
        px(ctx, d.x - 34, floorY - 29, 16, 3, '#d8d2b8');
        live.lamps.push({ x: d.x - 4, y: floorY - 54, r: 58, color: 'rgba(240,166,90,0.22)' });
      });
      break;
    }

    case 'AUDIO': {
      // Vocal booth with foam, boom mic, mixing desk, monitor speakers, ON AIR sign.
      const boothX = zone.x + 24;
      const boothW = 150;
      px(ctx, boothX, zone.y + 18, boothW, zone.height - 30, '#241e2a');
      outline(ctx, boothX, zone.y + 18, boothW, zone.height - 30, '#3a3046');
      const foamRnd = mulberry32(hash32(`foam${zone.id}`));
      for (let fy = zone.y + 22; fy < floorY - 8; fy += 11) {
        for (let fx = boothX + 4; fx < boothX + boothW - 8; fx += 11) {
          const tone = foamRnd();
          px(ctx, fx, fy, 5, 5, tone > 0.6 ? '#332a3d' : '#2b2434');
          px(ctx, fx + 5, fy + 5, 5, 5, tone > 0.3 ? '#282133' : '#221b2b');
        }
      }
      // Bass traps in the corners.
      px(ctx, boothX + 2, zone.y + 20, 7, zone.height - 34, '#3a3046');
      px(ctx, boothX + boothW - 11, zone.y + 20, 7, zone.height - 34, '#3a3046');
      // Booth glass
      px(ctx, boothX + boothW - 6, zone.y + 26, 4, zone.height - 46, '#4a6f77');
      live.onAir = live.onAir || [];
      live.onAir.push({ x: boothX + boothW / 2 - 24, y: zone.y + 6, zoneId: zone.id });

      // Monitor speakers on stands
      for (const sxp of [zone.x + zone.width - 74, zone.x + zone.width - 34]) {
        px(ctx, sxp + 8, floorY - 30, 3, 30, '#2c3a34');
        block(ctx, sxp, floorY - 50, 20, 22, '#26332d', '#3a4a41', '#141d19');
        px(ctx, sxp + 4, floorY - 45, 12, 12, '#171f1c');
        px(ctx, sxp + 7, floorY - 42, 6, 6, '#2e3d36');
        px(ctx, sxp + 6, floorY - 30, 8, 2, '#171f1c');
      }
      drawPlant(ctx, zone.x + zone.width - 106, floorY, seed + 11);

      desks.forEach((d, i) => {
        // Mixing desk instead of a plain table.
        block(ctx, d.x - 40, floorY - 26, 80, 8, '#3a3040', '#4e4256', '#241d2a');
        px(ctx, d.x - 36, floorY - 18, 72, 18, '#2c2434');
        for (let f = 0; f < 10; f += 1) {
          px(ctx, d.x - 33 + f * 7, floorY - 24, 2, 5, '#6b5a78');
        }
        drawMonitor(ctx, d.x - 22, floorY - 54, 36, 24, st.accent);
        addScreen('waveform', d.x - 22, floorY - 54, 36, 24);
        // Boom arm + mic + pop filter
        px(ctx, d.x + 26, floorY - 64, 2, 40, '#3c3348');
        px(ctx, d.x + 8, floorY - 64, 20, 2, '#3c3348');
        px(ctx, d.x + 6, floorY - 62, 5, 11, '#6f6280');
        px(ctx, d.x + 7, floorY - 61, 3, 8, '#8d7f9e');
        px(ctx, d.x + 1, floorY - 60, 2, 8, '#4a3f57');
        live.lamps.push({ x: d.x, y: floorY - 46, r: 60, color: 'rgba(192,122,176,0.22)' });
        live.vuMeters.push({ x: d.x - 36, y: floorY - 16, w: 72, h: 12, zoneId: zone.id });
      });
      break;
    }

    case 'VIDEO': {
      // Edit bay: three monitors, colour panel, drive stack, poster.
      block(ctx, zone.x + 20, zone.y + 26, 58, 74, '#243038', '#33454f', '#141c21');
      px(ctx, zone.x + 24, zone.y + 30, 50, 66, '#1b2830');
      drawText(ctx, 'SHORTS', zone.x + 30, zone.y + 40, '#5c8296', 1, 1);
      drawText(ctx, '9:16', zone.x + 36, zone.y + 54, '#7ba6bd', 2, 1);
      px(ctx, zone.x + 30, zone.y + 74, 38, 14, '#22333c');

      // Drive stack with LEDs
      for (let i = 0; i < 4; i += 1) {
        const dy2 = floorY - 10 - i * 9;
        block(ctx, zone.x + zone.width - 56, dy2 - 8, 40, 8, '#26323a', '#394a55', '#151d22');
        live.leds.push({ x: zone.x + zone.width - 22, y: dy2 - 5, color: PAL.blue, phase: i * 0.7, rate: 2.4 });
      }
      drawPlant(ctx, zone.x + zone.width - 92, floorY, seed + 5);

      desks.forEach((d, i) => {
        drawDeskUnit(ctx, d.x, floorY, st.accent, i);
        drawMonitor(ctx, d.x - 46, floorY - 52, 30, 22, st.accent);
        drawMonitor(ctx, d.x - 14, floorY - 58, 42, 28, st.accent);
        drawMonitor(ctx, d.x + 30, floorY - 52, 26, 22, st.accent);
        addScreen('timeline', d.x - 14, floorY - 58, 42, 28);
        addScreen('graph', d.x - 46, floorY - 52, 30, 22);
        addScreen('chart', d.x + 30, floorY - 52, 26, 22);
        // Colour grading panel with trackballs
        px(ctx, d.x - 20, floorY - 30, 36, 6, '#2a3740');
        for (let t = 0; t < 3; t += 1) px(ctx, d.x - 16 + t * 12, floorY - 29, 6, 4, '#4a6a7c');
        live.lamps.push({ x: d.x, y: floorY - 48, r: 72, color: 'rgba(106,169,216,0.24)' });
      });
      break;
    }

    case 'SERVER': {
      // Racks from the backend desk list, cable tray, floor tiles, cooling fans.
      for (let tx = zone.x; tx < zone.x + zone.width; tx += 24) {
        px(ctx, tx, floorY - 12, 23, 11, '#1b2924');
        px(ctx, tx, floorY - 12, 23, 1, '#243a32');
      }
      px(ctx, zone.x + 10, zone.y + 16, zone.width - 20, 4, '#2a3a33');
      for (let cx = zone.x + 16; cx < zone.x + zone.width - 20; cx += 18) {
        px(ctx, cx, zone.y + 20, 2, 6, pick(['#4a6a5c', '#6a5a4a', '#4a5a6a'], rnd));
      }

      desks.forEach((d, i) => {
        const rackX = d.x - 24;
        const rackY = floorY - 78;
        block(ctx, rackX, rackY, 48, 78, '#1e2b26', '#31463c', '#101a17');
        outline(ctx, rackX, rackY, 48, 78, '#3a5348');
        for (let u = 0; u < 9; u += 1) {
          const uy = rackY + 5 + u * 8;
          px(ctx, rackX + 4, uy, 40, 6, '#16231e');
          px(ctx, rackX + 5, uy + 1, 38, 1, '#20342c');
          for (let l = 0; l < 4; l += 1) {
            live.leds.push({
              x: rackX + 8 + l * 5,
              y: uy + 2,
              color: l === 0 ? PAL.green : l === 3 ? PAL.amber : '#3f7d70',
              phase: (u * 4 + l) * 0.37 + i,
              rate: 3.1 + (l % 3) * 1.4,
            });
          }
          px(ctx, rackX + 32, uy + 2, 9, 3, '#22362e');
        }
        const caption = String(d.name || '').replace(/[^A-Za-z0-9 ]/g, '').slice(0, 8);
        px(ctx, rackX + 4, rackY - 12, 40, 9, '#16241f');
        drawText(ctx, caption, rackX + 7, rackY - 10, '#6f9b8c', 1, 1);
        live.fans.push({ x: rackX + 24, y: rackY - 6, r: 7, rate: 4 + i });
        live.lamps.push({ x: rackX + 24, y: rackY + 40, r: 54, color: 'rgba(111,191,122,0.16)' });
      });
      break;
    }

    case 'LOUNGE': {
      // Sofa, table, espresso machine, water cooler, dartboard, rug.
      px(ctx, zone.x + 16, floorY - 6, 130, 6, '#5a4034');
      px(ctx, zone.x + 16, floorY - 6, 130, 1, '#6e5040');
      block(ctx, zone.x + 24, floorY - 30, 84, 24, '#3d5a4c', '#4f715f', '#22362d');
      px(ctx, zone.x + 28, floorY - 36, 76, 8, '#456552');
      px(ctx, zone.x + 30, floorY - 26, 22, 10, '#4f715f');
      px(ctx, zone.x + 58, floorY - 26, 22, 10, '#4f715f');
      block(ctx, zone.x + 118, floorY - 16, 40, 6, '#6a4f38', '#83634a', '#42301f');
      px(ctx, zone.x + 122, floorY - 10, 3, 10, '#42301f');
      px(ctx, zone.x + 151, floorY - 10, 3, 10, '#42301f');
      px(ctx, zone.x + 126, floorY - 20, 14, 4, '#cfc5a4');

      // Espresso machine
      const eX = zone.x + 186;
      block(ctx, eX, floorY - 40, 34, 40, '#3a4a42', '#4e6357', '#1f2a25');
      px(ctx, eX + 4, floorY - 34, 26, 12, '#22302a');
      px(ctx, eX + 8, floorY - 22, 6, 8, '#8fa294');
      px(ctx, eX + 20, floorY - 30, 8, 4, PAL.red);
      live.steam.push({ x: eX + 11, y: floorY - 24, zoneId: zone.id });

      // Water cooler
      const wX = zone.x + 236;
      block(ctx, wX, floorY - 44, 20, 44, '#3a4a52', '#4c6069', '#1e2a30');
      px(ctx, wX + 2, floorY - 60, 16, 18, '#5f8fa0');
      live.bubbles.push({ x: wX + 10, y: floorY - 52, zoneId: zone.id });
      px(ctx, wX + 6, floorY - 26, 8, 3, '#22302a');

      drawPlant(ctx, zone.x + 168, floorY, seed + 2);
      // Dartboard
      const dX = zone.x + 290;
      px(ctx, dX - 11, zone.y + 34, 22, 22, '#2a3a33');
      px(ctx, dX - 8, zone.y + 37, 16, 16, '#c9d8c0');
      px(ctx, dX - 5, zone.y + 40, 10, 10, '#8a4a3c');
      px(ctx, dX - 2, zone.y + 43, 4, 4, '#e0cfa8');
      break;
    }

    case 'PUBLISH': {
      // Broadcast console with a radar map and upload monitors.
      desks.forEach((d, i) => {
        block(ctx, d.x - 44, floorY - 30, 88, 10, '#3a3428', '#4f4736', '#221e17');
        px(ctx, d.x - 40, floorY - 20, 80, 20, '#2c2820');
        for (let b2 = 0; b2 < 8; b2 += 1) {
          live.leds.push({ x: d.x - 34 + b2 * 9, y: floorY - 27, color: b2 % 3 === 0 ? PAL.red : PAL.amber, phase: b2 * 0.5 + i, rate: 2.2 });
        }
        drawMonitor(ctx, d.x - 34, floorY - 58, 30, 24, st.accent);
        drawMonitor(ctx, d.x - 2, floorY - 60, 38, 26, st.accent);
        addScreen('upload', d.x - 34, floorY - 58, 30, 24);
        live.radars.push({ x: d.x + 17, y: floorY - 47, r: 12, mx: d.x - 2, my: floorY - 60, w: 38, h: 26 });
        live.lamps.push({ x: d.x, y: floorY - 48, r: 66, color: 'rgba(217,112,90,0.20)' });
      });
      // Shelf with shipping crates, kept clear of the console.
      const shelfX = zone.x + 16;
      block(ctx, shelfX, floorY - 40, 54, 40, '#4a3a2a', '#5d4934', '#2e2419');
      px(ctx, shelfX + 4, floorY - 34, 20, 14, '#7a6244');
      px(ctx, shelfX + 28, floorY - 34, 20, 14, '#6a5438');
      px(ctx, shelfX + 4, floorY - 18, 20, 14, '#6a5438');
      px(ctx, shelfX + 28, floorY - 18, 20, 14, '#7a6244');
      px(ctx, shelfX + 10, floorY - 30, 8, 3, PAL.red);
      break;
    }


    case 'SHOP': {
      // Street-facing unit: a glazed front, a counter, and boards showing the advertising
      // slots the studio has to sell. No desk is assigned to it by the backend, so nobody
      // is drawn behind the counter.
      const glassTop = zone.y + 26;
      const glassH = zone.height - 52;
      px(ctx, zone.x + 10, glassTop, zone.width - 20, glassH, '#16302f');
      ctx.save();
      ctx.globalAlpha = 0.22;
      px(ctx, zone.x + 14, glassTop + 4, (zone.width - 28) * 0.45, glassH - 8, '#7fb8ac');
      ctx.restore();
      outline(ctx, zone.x + 10, glassTop, zone.width - 20, glassH, '#3f5a4e');
      px(ctx, zone.x + zone.width / 2 - 2, glassTop, 4, glassH, '#2b3f37');

      // Awning over the pavement side.
      for (let i = 0; i < 7; i += 1) {
        px(ctx, zone.x + 8 + i * 24, zone.y + 12, 24, 13, i % 2 ? '#8a4a3c' : '#c9b48a');
      }
      px(ctx, zone.x + 8, zone.y + 25, zone.width - 16, 3, '#5a3a30');

      // Shop sign.
      const sign = 'AD SPACE';
      const sw = textWidth(sign, 2, 1);
      px(ctx, zone.x + (zone.width - sw) / 2 - 8, zone.y + 32, sw + 16, 18, '#1b2b26');
      outline(ctx, zone.x + (zone.width - sw) / 2 - 8, zone.y + 32, sw + 16, 18, PAL.gold);
      drawText(ctx, sign, zone.x + (zone.width - sw) / 2, zone.y + 37, PAL.gold, 2, 1);

      // Rate boards in the window.
      for (let i = 0; i < 3; i += 1) {
        const bx2 = zone.x + 22 + i * 46;
        block(ctx, bx2, glassTop + 34, 36, 46, '#2c3a33', '#3e5147', '#18241f');
        px(ctx, bx2 + 3, glassTop + 38, 30, 20, pick(['#4a5c78', '#7c4550', '#4f7a52'], rnd));
        px(ctx, bx2 + 3, glassTop + 61, 24, 3, '#a8b8a4');
        px(ctx, bx2 + 3, glassTop + 67, 18, 3, '#7d8f7c');
        px(ctx, bx2 + 3, glassTop + 73, 12, 3, PAL.gold);
      }

      // Counter, till and a stool.
      block(ctx, zone.x + 18, floorY - 34, 78, 12, '#5a4632', '#755c42', '#3a2c20');
      px(ctx, zone.x + 22, floorY - 22, 70, 22, '#4a3a2a');
      px(ctx, zone.x + 62, floorY - 46, 22, 12, '#22302a');
      px(ctx, zone.x + 65, floorY - 43, 16, 6, '#6f9b8c');
      px(ctx, zone.x + 104, floorY - 20, 14, 4, '#3a4a42');
      px(ctx, zone.x + 109, floorY - 16, 4, 16, '#3a4a42');
      px(ctx, zone.x + 104, floorY - 2, 14, 3, '#3a4a42');
      drawPlant(ctx, zone.x + zone.width - 26, floorY, seed + 21);
      live.lamps.push({ x: zone.x + zone.width / 2, y: glassTop + 30, r: 96, color: 'rgba(221,174,106,0.26)' });
      break;
    }

    default: {
      desks.forEach((d, i) => {
        drawDeskUnit(ctx, d.x, floorY, st.accent, i);
        drawMonitor(ctx, d.x - 20, floorY - 52, 32, 22, st.accent);
        addScreen('doc', d.x - 20, floorY - 52, 32, 22);
      });
    }
  }
}


/* ----------------------------------------------------------------- fillers --
   Generic office furniture used to break up empty wall runs. Placement is seeded per
   zone so the floors differ from each other but never shuffle between reloads.
   ------------------------------------------------------------------------- */

function drawFilingCabinet(ctx, x, floorY, accent) {
  block(ctx, x, floorY - 34, 26, 34, '#3c4a42', '#4f6156', '#1f2a25');
  for (let i = 0; i < 3; i += 1) {
    px(ctx, x + 3, floorY - 30 + i * 11, 20, 9, '#33413a');
    px(ctx, x + 9, floorY - 26 + i * 11, 8, 2, '#6d8073');
  }
  px(ctx, x + 4, floorY - 40, 18, 6, '#5a4a32');
  px(ctx, x + 6, floorY - 42, 6, 3, accent);
}

function drawWhiteboard(ctx, x, y, w, h, accent, seed) {
  const rnd = mulberry32(seed);
  block(ctx, x, y, w, h, '#9fa896', '#b6bfab', '#6c7566');
  outline(ctx, x, y, w, h, '#5c6b5a');
  for (let i = 0; i < 5; i += 1) {
    const lx = x + 6 + rnd() * (w - 40);
    const ly = y + 8 + i * ((h - 16) / 5);
    px(ctx, lx, ly, 12 + rnd() * 24, 2, i % 2 ? '#4d6b5c' : accent);
  }
  // A little diagram in the corner.
  outline(ctx, x + w - 30, y + 8, 20, 14, '#7a5a4a');
  px(ctx, x + w - 26, y + 12, 12, 2, '#7a5a4a');
  px(ctx, x + 4, y + h - 5, w - 8, 2, '#7d8874');
}

function drawPoster(ctx, x, y, seed, accent) {
  const rnd = mulberry32(seed);
  const w = 26 + Math.floor(rnd() * 14);
  const h = 32 + Math.floor(rnd() * 12);
  block(ctx, x, y, w, h, '#2a3a33', '#3c5045', '#16241f');
  px(ctx, x + 2, y + 2, w - 4, h - 4, pick(['#3b4a5c', '#4a3b52', '#3f5245', '#52453b'], rnd));
  for (let i = 0; i < 3; i += 1) {
    px(ctx, x + 4, y + 6 + i * 7, (w - 10) * (0.4 + rnd() * 0.6), 3, i === 1 ? accent : '#8fa294');
  }
  px(ctx, x + 4, y + h - 8, w - 8, 4, '#1c2a24');
}

function drawCoatRack(ctx, x, floorY, seed) {
  const rnd = mulberry32(seed);
  px(ctx, x, floorY - 62, 3, 62, '#3a2c20');
  px(ctx, x - 6, floorY - 4, 15, 3, '#3a2c20');
  px(ctx, x - 7, floorY - 62, 17, 3, '#3a2c20');
  px(ctx, x - 8, floorY - 58, 8, 18, pick(['#7c4550', '#3f6d63', '#4a5c78'], rnd));
  px(ctx, x + 5, floorY - 56, 7, 14, pick(['#8a6a3a', '#55607a'], rnd));
}

function drawWaterBottle(ctx, x, floorY) {
  px(ctx, x, floorY - 14, 8, 14, '#3a4a52');
  px(ctx, x + 1, floorY - 26, 6, 12, '#5f8fa0');
  px(ctx, x + 2, floorY - 28, 4, 2, '#8fb9cc');
}

function drawBin(ctx, x, floorY) {
  px(ctx, x, floorY - 13, 13, 13, '#2c3a34');
  px(ctx, x - 1, floorY - 15, 15, 2, '#3e5147');
  px(ctx, x + 3, floorY - 18, 5, 4, '#cfc5a4');
}

function drawWallShelf(ctx, x, y, seed) {
  const rnd = mulberry32(seed);
  px(ctx, x, y, 52, 3, '#5a4632');
  let bx = x + 3;
  while (bx < x + 46) {
    const bw = 4 + Math.floor(rnd() * 3);
    const bh = 8 + Math.floor(rnd() * 5);
    px(ctx, bx, y - bh, bw, bh, pick(['#8a4a3c', '#3f6d63', '#a08243', '#6a6a86'], rnd));
    bx += bw + 1;
  }
}

function drawExitSign(ctx, x, y) {
  px(ctx, x, y, 22, 10, '#1d3a2a');
  outline(ctx, x, y, 22, 10, '#356b4b');
  drawText(ctx, 'EXIT', x + 3, y + 2, '#8fe0a8', 1, 1);
}

function drawExtinguisher(ctx, x, floorY) {
  px(ctx, x, floorY - 30, 8, 16, '#9a3f34');
  px(ctx, x + 2, floorY - 34, 4, 4, '#3a2c20');
  px(ctx, x - 1, floorY - 24, 10, 2, '#c25a48');
}

/** Fill the wall spans a zone leaves empty between its desks. */
function fillZone(ctx, zone, live) {
  const st = zoneStyle(zone.zone_type);
  const floorY = zone.y + zone.height - 12;
  const rnd = mulberry32(hash32(`fill${zone.id}`));
  const occupied = (zone.desks || []).map((d) => [d.x - 60, d.x + 60]);
  const clear = (x, w) => occupied.every(([a, b]) => x + w < a || x > b);

  const anchors = [];
  for (let x = zone.x + 16; x < zone.x + zone.width - 60; x += 46) anchors.push(x);

  for (const x of anchors) {
    if (!clear(x, 40) || rnd() > 0.55) continue;
    const roll = rnd();
    if (roll < 0.17) drawFilingCabinet(ctx, x, floorY, st.accent);
    else if (roll < 0.3) drawPlant(ctx, x + 10, floorY, hash32(`p${zone.id}${x}`));
    else if (roll < 0.4) drawCoatRack(ctx, x + 8, floorY, hash32(`c${zone.id}${x}`));
    else if (roll < 0.5) drawWaterBottle(ctx, x + 6, floorY);
    else if (roll < 0.6) drawBin(ctx, x + 6, floorY);
    else if (roll < 0.7) drawExtinguisher(ctx, x + 6, floorY);
    else if (roll < 0.85) drawPoster(ctx, x, zone.y + 26 + rnd() * 10, hash32(`po${zone.id}${x}`), st.accent);
    else drawWallShelf(ctx, x, zone.y + 44, hash32(`sh${zone.id}${x}`));
  }

  // One whiteboard per floor where there is room for it.
  const wbX = zone.x + zone.width - 150;
  if (clear(wbX, 120) && zone.zone_type !== 'SERVER' && zone.zone_type !== 'LOUNGE') {
    drawWhiteboard(ctx, wbX, zone.y + 24, 110, 54, st.accent, hash32(`wb${zone.id}`));
  }
  if (zone.isFloorLead) {
    const right = zone.floorRight !== undefined ? zone.floorRight : zone.x + zone.width;
    drawExitSign(ctx, right - 30, zone.y + 22);
  }

  // Tall floors (the double-height ground level) get wall sconces: a single ceiling run
  // cannot light a 200px room.
  if (zone.height > 160) {
    for (let x = zone.x + 60; x < zone.x + zone.width - 40; x += 120) {
      px(ctx, x, zone.y + zone.height * 0.5, 5, 12, '#3c5044');
      px(ctx, x - 2, zone.y + zone.height * 0.5 - 4, 9, 4, '#4d6155');
      live.lamps.push({ x: x + 2, y: zone.y + zone.height * 0.5 + 4, r: 72, color: 'rgba(240,212,160,0.20)' });
    }
  }

  // Wall socket runs and a floor rug tie the room together.
  for (let x = zone.x + 30; x < zone.x + zone.width - 20; x += 74) {
    px(ctx, x, floorY - 16, 5, 4, '#2b3a33');
    px(ctx, x + 1, floorY - 15, 1, 2, '#4d6155');
  }
  live.ceilingLights.push({ zone });
}

/** Wall clocks need the frame time, so the interior only records where one hangs. */
function drawWallClockPlaceholder(ctx, live, x, y) {
  px(ctx, x - 9, y - 9, 18, 18, '#1a2621');
  live.clocks.push({ x, y });
}

/* ============================================================================
   Characters.

   Appearance is derived from the agent id, so every employee looks distinct and looks the
   same on every reload. Posture and gesture are derived from backend state only:

     lifecycle PAUSED / SUSPENDED  -> asleep at the desk
     runtime_state WORKING          -> typing, screen light on the face
     runtime_state THINKING         -> hand to chin, thought bubble
     everything else                -> idle: breathing, blinking, the occasional sip

   The small idle motions are cosmetic and apply to everyone; they never imply that work is
   happening, which is why an IDLE agent never types.
   ========================================================================== */

const SKIN_TONES = ['#f0c8a0', '#e0ab80', '#c68b62', '#a06a46', '#7c4f33', '#5c3a26'];
const HAIR_COLORS = ['#2b1d16', '#4a2f1e', '#6b4a2a', '#8a6a3a', '#3a3a42', '#7a3f3f', '#b08a4a', '#2a3340'];
const SHIRT_COLORS = ['#3f6d63', '#8a5a4a', '#4a5c78', '#6a6a86', '#7c5560', '#4f7a52', '#8a7440', '#55607a'];
const HAIR_STYLES = ['short', 'bun', 'long', 'curly', 'cap', 'bald', 'ponytail', 'mohawk'];

function agentLook(agentId, roleName) {
  const rnd = mulberry32(hash32(`${agentId}|${roleName || ''}`));
  return {
    skin: pick(SKIN_TONES, rnd),
    hair: pick(HAIR_COLORS, rnd),
    style: pick(HAIR_STYLES, rnd),
    shirt: pick(SHIRT_COLORS, rnd),
    trousers: pick(['#2a3138', '#33302a', '#293530', '#3a3038'], rnd),
    glasses: rnd() > 0.62,
    headset: rnd() > 0.72,
    build: 0.92 + rnd() * 0.2,
    phase: rnd() * TAU,
    blinkOffset: rnd() * 6,
    fidget: rnd(),
  };
}

function drawHair(ctx, style, hx, hy, hw, color) {
  switch (style) {
    case 'bun':
      px(ctx, hx, hy - 2, hw, 4, color);
      px(ctx, hx - 1, hy, 2, 5, color);
      px(ctx, hx + hw - 1, hy, 2, 5, color);
      px(ctx, hx + hw / 2 - 3, hy - 7, 6, 6, color);
      break;
    case 'long':
      px(ctx, hx - 1, hy - 2, hw + 2, 5, color);
      px(ctx, hx - 2, hy, 2, 13, color);
      px(ctx, hx + hw, hy, 2, 13, color);
      break;
    case 'curly':
      px(ctx, hx - 1, hy - 4, hw + 2, 6, color);
      px(ctx, hx - 2, hy - 2, 3, 4, color);
      px(ctx, hx + hw - 1, hy - 2, 3, 4, color);
      px(ctx, hx + 1, hy - 6, 4, 3, color);
      px(ctx, hx + hw - 5, hy - 6, 4, 3, color);
      break;
    case 'cap':
      px(ctx, hx - 1, hy - 3, hw + 2, 4, '#3a4a52');
      px(ctx, hx - 4, hy - 1, 6, 2, '#2e3c43');
      break;
    case 'bald':
      px(ctx, hx + 1, hy - 1, hw - 2, 2, color);
      break;
    case 'ponytail':
      px(ctx, hx, hy - 2, hw, 4, color);
      px(ctx, hx + hw, hy + 1, 2, 9, color);
      px(ctx, hx + hw + 1, hy + 7, 2, 4, color);
      break;
    case 'mohawk':
      px(ctx, hx + hw / 2 - 2, hy - 6, 4, 8, color);
      px(ctx, hx, hy - 1, hw, 2, color);
      break;
    default:
      px(ctx, hx - 1, hy - 3, hw + 2, 5, color);
      px(ctx, hx - 1, hy, 2, 4, color);
      px(ctx, hx + hw - 1, hy, 2, 4, color);
  }
}

/**
 * @param mode 'work' | 'think' | 'sleep' | 'idle'
 */
function drawCharacter(ctx, cx, floorY, look, mode, time, selected) {
  const s = look.build;
  const breathe = Math.sin(time * 1.7 + look.phase) * 0.8;
  const sleeping = mode === 'sleep';
  const slump = sleeping ? 5 : 0;

  // Seat height: characters sit at their desks.
  const hipY = floorY - 20;
  const headH = 12 * s;
  const headW = 12 * s;
  const headY = hipY - 26 * s + breathe + slump;
  const headX = cx - headW / 2;

  // Shadow under the chair.
  ctx.save();
  ctx.globalAlpha = 0.3;
  px(ctx, cx - 10, floorY - 2, 20, 3, '#070f0d');
  ctx.restore();

  if (selected) {
    glow(ctx, cx, headY + 6, 46, 'rgba(221,174,106,0.42)', 0.55);
  }

  // Legs under the desk.
  px(ctx, cx - 6, hipY, 5, 12 * s, look.trousers);
  px(ctx, cx + 2, hipY, 5, 12 * s, look.trousers);
  px(ctx, cx - 7, hipY + 11 * s, 7, 3, '#1c231f');
  px(ctx, cx + 1, hipY + 11 * s, 7, 3, '#1c231f');

  // Torso
  const torsoY = headY + headH;
  const torsoH = hipY - torsoY + 2;
  px(ctx, cx - 8 * s, torsoY, 16 * s, torsoH, look.shirt);
  px(ctx, cx - 8 * s, torsoY, 16 * s, 1, '#ffffff26');
  px(ctx, cx - 8 * s, torsoY + torsoH - 2, 16 * s, 2, '#00000033');
  // Collar
  px(ctx, cx - 4, torsoY, 8, 2, '#00000033');

  // Arms + hands. Typing only when the backend says the agent is working.
  const typing = mode === 'work';
  const tick = Math.floor(time * 11 + look.phase * 3);
  const leftUp = typing ? (tick % 2 === 0 ? 1 : 0) : 0;
  const rightUp = typing ? (tick % 2 === 1 ? 1 : 0) : 0;

  if (mode === 'think') {
    // One arm folded, the other propping the chin.
    px(ctx, cx - 11 * s, torsoY + 3, 4, 9, look.shirt);
    px(ctx, cx + 7 * s, torsoY + 2, 4, 7, look.shirt);
    px(ctx, cx + 5, headY + headH - 3, 4, 4, look.skin);
  } else if (sleeping) {
    px(ctx, cx - 11 * s, torsoY + 5, 5, 7, look.shirt);
    px(ctx, cx + 7 * s, torsoY + 5, 5, 7, look.shirt);
    px(ctx, cx - 12, hipY - 4, 24, 3, look.skin);
  } else {
    // Idle loop: every character cycles slowly through resting, a sip and a stretch, each
    // on its own offset so the room never moves in unison.
    const cycle = (time * 0.16 + look.fidget * 3) % 3;
    const sipping = mode === 'idle' && cycle > 1.1 && cycle < 1.7;
    const stretching = mode === 'idle' && cycle > 2.35 && cycle < 2.75;

    if (stretching) {
      const reach = Math.sin((cycle - 2.35) / 0.4 * Math.PI);
      px(ctx, cx - 11 * s, torsoY - 2 - reach * 6, 4, 12, look.shirt);
      px(ctx, cx + 7 * s, torsoY - 2 - reach * 6, 4, 12, look.shirt);
      px(ctx, cx - 12 * s, torsoY - 5 - reach * 6, 5, 4, look.skin);
      px(ctx, cx + 7 * s, torsoY - 5 - reach * 6, 5, 4, look.skin);
    } else if (sipping) {
      const lift = Math.sin((cycle - 1.1) / 0.6 * Math.PI);
      px(ctx, cx - 11 * s, torsoY + 2, 4, 10, look.shirt);
      px(ctx, cx + 7 * s, torsoY + 4 - lift * 5, 4, 8, look.shirt);
      px(ctx, cx - 12 * s, torsoY + 11, 5, 4, look.skin);
      px(ctx, cx + 7 * s, torsoY + 11 - lift * 7, 5, 4, look.skin);
      drawMug(ctx, cx + 7 * s, torsoY + 12 - lift * 7, '#b8593f');
    } else {
      px(ctx, cx - 11 * s, torsoY + 2, 4, 10 - leftUp, look.shirt);
      px(ctx, cx + 7 * s, torsoY + 2, 4, 10 - rightUp, look.shirt);
      px(ctx, cx - 12 * s, torsoY + 11 - leftUp, 5, 4, look.skin);
      px(ctx, cx + 7 * s, torsoY + 11 - rightUp, 5, 4, look.skin);
    }
  }

  // Head
  const idleCycle = (time * 0.16 + look.fidget * 3) % 3;
  const headLift = mode === 'idle' && idleCycle > 2.35 && idleCycle < 2.75
    ? -Math.sin((idleCycle - 2.35) / 0.4 * Math.PI) * 2
    : 0;
  const tilt = mode === 'think' ? 2 : sleeping ? 3 : mode === 'idle' && idleCycle > 1.1 && idleCycle < 1.7 ? -1 : 0;
  px(ctx, headX + tilt, headY + headLift, headW, headH, look.skin);
  px(ctx, headX + tilt, headY + headH - 1, headW, 1, '#00000022');
  // Ears
  px(ctx, headX + tilt - 1, headY + 5, 1, 3, look.skin);
  px(ctx, headX + tilt + headW, headY + 5, 1, 3, look.skin);

  // Eyes: blink on a per-character cycle.
  const blinkT = (time + look.blinkOffset) % 4.4;
  const blinking = sleeping || blinkT < 0.13;
  const eyeY = headY + 5;
  if (blinking) {
    px(ctx, headX + tilt + 2, eyeY + 1, 3, 1, '#2a211c');
    px(ctx, headX + tilt + 7, eyeY + 1, 3, 1, '#2a211c');
  } else {
    px(ctx, headX + tilt + 2, eyeY, 2, 2, '#2a211c');
    px(ctx, headX + tilt + 8, eyeY, 2, 2, '#2a211c');
  }
  // Mouth
  if (sleeping) {
    px(ctx, headX + tilt + 5, headY + 9, 3, 2, '#3a2a22');
  } else if (mode === 'work') {
    px(ctx, headX + tilt + 4, headY + 9, 4, 1, '#6a4a3c');
  } else {
    px(ctx, headX + tilt + 4, headY + 9, 4, 1, '#7a5a4a');
  }

  drawHair(ctx, look.style, headX + tilt, headY, headW, look.hair);

  if (look.glasses) {
    px(ctx, headX + tilt + 1, eyeY - 1, 4, 4, '#00000000');
    outline(ctx, headX + tilt + 1, eyeY - 1, 4, 4, '#c9d8c0');
    outline(ctx, headX + tilt + 7, eyeY - 1, 4, 4, '#c9d8c0');
    px(ctx, headX + tilt + 5, eyeY, 2, 1, '#c9d8c0');
  }
  if (look.headset) {
    px(ctx, headX + tilt - 2, headY + 2, 2, 6, '#2c3a34');
    px(ctx, headX + tilt + headW, headY + 2, 2, 6, '#2c3a34');
    px(ctx, headX + tilt - 1, headY - 3, headW + 2, 2, '#2c3a34');
  }

  return { headX: headX + tilt, headY, headW, headH, torsoY };
}

/** Status marks above the head — again, only for states the backend reports. */
function drawStateMark(ctx, cx, topY, mode, time, accent) {
  if (mode === 'think') {
    const bob = Math.sin(time * 2.2) * 2;
    const bx = cx + 12;
    const by = topY - 30 + bob;
    px(ctx, bx - 5, by - 6, 12, 10, '#22322b');
    outline(ctx, bx - 5, by - 6, 12, 10, '#3f5a4e');
    // Filament bulb
    px(ctx, bx - 2, by - 4, 6, 6, PAL.gold);
    px(ctx, bx - 1, by + 2, 4, 2, '#8a6a3a');
    glow(ctx, bx + 1, by - 1, 22, 'rgba(221,174,106,0.6)', 0.5);
    px(ctx, bx - 8, by - 10, 2, 2, '#3f5a4e');
    px(ctx, bx - 11, by - 13, 2, 2, '#3f5a4e');
  } else if (mode === 'sleep') {
    for (let i = 0; i < 3; i += 1) {
      const t = (time * 0.7 + i * 0.33) % 1;
      const zx = cx + 8 + t * 12;
      const zy = topY - 27 - t * 14;
      ctx.globalAlpha = 1 - t;
      drawText(ctx, 'Z', zx, zy, '#8fa294', 1 + Math.round(t), 1);
      ctx.globalAlpha = 1;
    }
  } else if (mode === 'work') {
    // Faint activity ticks over the keyboard, in the department accent.
    const t = Math.sin(time * 8);
    if (t > 0.4) px(ctx, cx - 14, topY + 2, 2, 2, accent);
    if (t < -0.4) px(ctx, cx + 12, topY + 4, 2, 2, accent);
  }
}

/**
 * Runtime-state tag above the head. The card at the feet says who this is; this tag says
 * what the backend last reported (IDLE, WORKING…), in the department accent on a dark
 * chip so it stays readable over any wall, screen or window behind it.
 */
function drawStateTag(ctx, cx, headTop, state, accent) {
  const label = String(state || 'IDLE').trim().toUpperCase().slice(0, 12);
  const w = textWidth(label, 1, 1) + 12;
  const h = 11;
  const x = Math.round(cx - w / 2);
  const top = Math.round(headTop) - 20;

  ctx.save();
  ctx.globalAlpha = 0.35;
  px(ctx, x + 2, top + 2, w, h, '#060d0b');
  ctx.restore();
  px(ctx, x, top, w, h, '#101c19');
  outline(ctx, x, top, w, h, '#2c443a');
  px(ctx, x + 1, top + 1, w - 2, 1, '#24382f');
  drawText(ctx, label, x + 6, top + 2, accent, 1, 1);
}

/**
 * Nameplate on the floor slab. A small paper card, in the same register as the speech
 * bubbles: light board with dark ink stays readable over the night-time floors, where
 * the old dark-on-dark plate washed into the furniture. It carries the name only —
 * the runtime state lives in the tag above the character's head.
 */
function drawNamePlate(ctx, cx, y, name, accent, selected) {
  let label = String(name || '').trim().toUpperCase();
  if (label.length > 15) {
    const cut = label.slice(0, 15);
    const space = cut.lastIndexOf(' ');
    label = (space > 5 ? cut.slice(0, space) : cut).trim();
  }
  const w = textWidth(label, 1, 1) + 22;
  const h = 13;
  const x = Math.round(cx - w / 2);
  const top = Math.round(y);

  // Paper card with a soft shadow, so it never fights the furniture behind it.
  ctx.save();
  ctx.globalAlpha = 0.35;
  px(ctx, x + 2, top + 2, w, h, '#060d0b');
  ctx.restore();
  px(ctx, x, top, w, h, selected ? '#f2e2b6' : PAL.white);
  outline(ctx, x, top, w, h, selected ? PAL.gold : '#2b3f37');
  px(ctx, x + 1, top + 1, w - 2, 1, '#fffbef');

  // Department dot, then the name.
  px(ctx, x + 6, top + 5, 4, 4, accent);
  drawText(ctx, label, x + 14, top + 4, '#1c2a24', 1, 1);
}

/** Speech bubble raised by a backend agent.message_sent event. */
function drawSpeechBubble(ctx, x, y, text, time) {
  const words = String(text).toUpperCase().split(/\s+/);
  const maxChars = 22;
  const lines = [];
  let line = '';
  for (const word of words) {
    if ((line + ' ' + word).trim().length > maxChars) {
      lines.push(line.trim());
      line = word;
    } else {
      line = `${line} ${word}`;
    }
    if (lines.length >= 3) break;
  }
  if (line && lines.length < 3) lines.push(line.trim());

  const w = Math.max(...lines.map((l) => textWidth(l, 1, 1))) + 16;
  const h = lines.length * 10 + 12;
  const bx = Math.round(x - w / 2);
  const by = Math.round(y - h - 10 + Math.sin(time * 1.6) * 1.5);

  ctx.save();
  ctx.globalAlpha = 0.94;
  px(ctx, bx, by, w, h, '#f4f2e6');
  outline(ctx, bx, by, w, h, '#2b3f37');
  px(ctx, bx + w / 2 - 3, by + h, 6, 3, '#f4f2e6');
  px(ctx, bx + w / 2 - 2, by + h + 3, 4, 3, '#f4f2e6');
  ctx.restore();
  lines.forEach((l, i) => drawText(ctx, l, bx + 8, by + 7 + i * 10, '#233b37', 1, 1));
}

/** Workflow token: a small parcel that sits at the stage the backend reports. */
function drawProjectToken(ctx, token, time) {
  const bob = Math.sin(time * 2 + token.x * 0.01) * 3;
  const x = Math.round(token.x);
  const y = Math.round(token.y + bob);
  glow(ctx, x, y, 26, 'rgba(221,174,106,0.35)', 0.5);
  block(ctx, x - 9, y - 9, 18, 18, '#8a6a3a', '#b08a4a', '#5c4626');
  px(ctx, x - 9, y - 2, 18, 3, '#d8b06a');
  px(ctx, x - 2, y - 9, 4, 18, '#d8b06a');
  const label = String(token.stage || '').slice(0, 12);
  const w = textWidth(label, 1, 1);
  px(ctx, x - w / 2 - 4, y + 12, w + 8, 9, '#16241f');
  drawText(ctx, label, x - w / 2, y + 14, PAL.gold, 1, 1);
}

/* ============================================================================
   Engine
   ========================================================================== */

const STATE_MODE = {
  WORKING: 'work',
  EXECUTING: 'work',
  RUNNING: 'work',
  THINKING: 'think',
  PLANNING: 'think',
  WAITING: 'idle',
  IDLE: 'idle',
};

function modeForAgent(agent) {
  const lifecycle = String(agent.lifecycle || '').toUpperCase();
  if (lifecycle === 'PAUSED' || lifecycle === 'SUSPENDED' || lifecycle === 'TERMINATED') return 'sleep';
  const rs = String(agent.runtime_state || 'IDLE').toUpperCase();
  return STATE_MODE[rs] || 'idle';
}

export class OfficeEngine {
  constructor(canvas, options = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.onSelectAgent = options.onSelectAgent || (() => {});

    this.layout = null;
    this.agents = [];
    this.speechBubbles = [];
    this.projectTokens = [];
    this.selectedAgentId = null;
    this.looks = new Map();

    this.worldW = WORLD_W;
    this.worldH = WORLD_H;

    // Offscreen buffers: one for the composed frame, one for cached static art.
    this.world = document.createElement('canvas');
    this.world.width = this.worldW;
    this.world.height = this.worldH;
    this.wctx = this.world.getContext('2d');

    this.staticLayer = document.createElement('canvas');
    this.staticLayer.width = this.worldW;
    this.staticLayer.height = this.worldH;
    this.sctx = this.staticLayer.getContext('2d');

    this.bgLayer = document.createElement('canvas');
    this.bgLayer.width = this.worldW;
    this.bgLayer.height = this.worldH;
    this.bgCtx = this.bgLayer.getContext('2d');

    this.live = this._emptyLive();
    this.scenery = {
      trees: makeTrees(0x7ee1, this.worldW),
      cars: makeTraffic(0x33aa),
      walkers: makeWalkers(0x9c41),
      clouds: makeClouds(0x1f77),
      birds: makeBirds(0x60d2),
      dust: Array.from({ length: 40 }, (_, i) => {
        const rnd = mulberry32(0x4411 + i);
        return { x: rnd() * WORLD_W, y: rnd() * WORLD_H, s: 0.2 + rnd() * 0.7, p: rnd() * TAU };
      }),
    };

    /**
     * The lift is parked unless the backend gives it a reason to move. A workflow token
     * arriving at a stage on another floor is such a reason: the project physically moves
     * between departments. With no workflow running, the cab stands still with its doors
     * shut — the studio must not animate activity that is not happening.
     */
    this.lift = { y: 0, target: 0, moving: false, restUntil: 0, parkedFloorY: null, trip: null };
    //: tokenId -> the zone the token was last seen in, so a floor change knows where the
    //: journey starts as well as where it ends.
    this.tokenPlaces = new Map();

    this.viewport = new Viewport(canvas);
    this.animTime = 0;
    this.lastFrame = performance.now();
    this.running = true;

    this._bindInput();
    this._renderStatic();
    this.resize();
    this._loop = this._loop.bind(this);
    requestAnimationFrame(this._loop);
  }

  _emptyLive() {
    return { screens: [], leds: [], lamps: [], fans: [], vuMeters: [], steam: [], bubbles: [], radars: [], clocks: [], onAir: [], ceilingLights: [] };
  }

  /* ------------------------------------------------------------ data in -- */

  setLayout(layout) {
    this.layout = layout;
    if (layout && layout.width && layout.height) {
      const b = layout.building || { y: 60, height: layout.height - 110 };
      // The building must stand on the pavement, so the world is taller than the layout:
      // the extra band below the building base is the street.
      setHorizon(b.y + b.height);
      const w = Math.round(layout.width);
      const h = Math.round(HORIZON + STREET_DEPTH);
      if (w !== this.worldW || h !== this.worldH) {
        this.worldW = w;
        this.worldH = h;
        for (const c of [this.world, this.staticLayer, this.bgLayer]) {
          c.width = w;
          c.height = h;
        }
      }
    }
    this._renderStatic();
    this.resize();
  }

  setAgents(agents) {
    this.agents = agents || [];
    for (const a of this.agents) {
      const id = a.id || a.agent_id;
      if (!this.looks.has(id)) this.looks.set(id, agentLook(id, a.role_name));
    }
  }

  setSpeechBubbles(bubbles) {
    this.speechBubbles = bubbles || [];
  }

  setProjectTokens(tokens) {
    this.projectTokens = tokens || [];
  }

  setSelectedAgent(agentId) {
    this.selectedAgentId = agentId;
  }

  /* ------------------------------------------------------------- layout -- */

  resize() {
    const parent = this.canvas.parentElement;
    if (!parent) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const cssW = parent.clientWidth;
    const cssH = parent.clientHeight;
    if (cssW <= 0 || cssH <= 0) return;
    this.canvas.width = Math.round(cssW * dpr);
    this.canvas.height = Math.round(cssH * dpr);
    this.dpr = dpr;
    this.viewport.fitToOffice(this.worldW, this.worldH);
  }

  /* --------------------------------------------------------------- input -- */

  _bindInput() {
    const c = this.canvas;
    let dragging = false;
    let lastX = 0;
    let lastY = 0;
    let moved = 0;

    const localPoint = (e) => {
      const rect = c.getBoundingClientRect();
      const scale = c.width / rect.width;
      return { x: (e.clientX - rect.left) * scale, y: (e.clientY - rect.top) * scale };
    };

    c.addEventListener('mousedown', (e) => {
      dragging = true;
      moved = 0;
      const p = localPoint(e);
      lastX = p.x;
      lastY = p.y;
    });
    window.addEventListener('mouseup', (e) => {
      if (dragging && moved < 5) this._handleClick(e);
      dragging = false;
    });
    c.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      const p = localPoint(e);
      const dx = p.x - lastX;
      const dy = p.y - lastY;
      moved += Math.abs(dx) + Math.abs(dy);
      this.viewport.panX += dx;
      this.viewport.panY += dy;
      lastX = p.x;
      lastY = p.y;
    });
    c.addEventListener('wheel', (e) => {
      e.preventDefault();
      const p = localPoint(e);
      const factor = e.deltaY < 0 ? 1.12 : 0.89;
      this.viewport.setZoom(this.viewport.zoom * factor, p.x, p.y);
    }, { passive: false });
  }

  _handleClick(e) {
    const rect = this.canvas.getBoundingClientRect();
    const scale = this.canvas.width / rect.width;
    const sx = (e.clientX - rect.left) * scale;
    const sy = (e.clientY - rect.top) * scale;
    const { x, y } = this.viewport.screenToWorld(sx, sy);

    let hit = null;
    for (const agent of this.agents) {
      const dx = agent.x - x;
      const dy = agent.y - y;
      if (Math.abs(dx) <= 34 && dy >= -70 && dy <= 26) {
        hit = agent;
        break;
      }
    }
    this.selectedAgentId = hit ? hit.id || hit.agent_id : null;
    this.onSelectAgent(hit);
  }

  /* --------------------------------------------------- static rasterising -- */

  _renderStatic() {
    const w = this.worldW;
    const h = this.worldH;
    this.live = this._emptyLive();

    // Sky and skyline live on their own layer so that clouds can drift *behind* the
    // building instead of floating through the offices.
    const bg = this.bgCtx;
    bg.clearRect(0, 0, w, h);
    drawSky(bg, w, h);
    drawSkyline(bg, w);

    const ctx = this.sctx;
    ctx.clearRect(0, 0, w, h);
    drawGround(ctx, w);

    for (const t of this.scenery.trees) drawTrunk(ctx, t);
    for (const x of LAMP_POSTS) drawLampPost(ctx, x);

    // Bus stop and bench, so the street is not just posts.
    const wl = walkLine();
    // Bus shelter, sized so a person fits under it.
    // Height is capped so the shelter stays under the building base course.
    px(ctx, 176, wl - 44, 96, 5, '#2c3a34');
    px(ctx, 178, wl - 39, 4, 39, '#2c3a34');
    px(ctx, 266, wl - 39, 4, 39, '#2c3a34');
    px(ctx, 184, wl - 20, 80, 4, '#22322b');
    px(ctx, 184, wl - 16, 4, 16, '#22322b');
    px(ctx, 260, wl - 16, 4, 16, '#22322b');
    px(ctx, 186, wl - 43, 74, 3, '#3d5147');
    drawText(ctx, 'BUS', 208, wl - 38, '#7fa08a', 1, 1);
    // Bench and litter bin.
    px(ctx, 620, wl - 20, 66, 5, '#4a3a2a');
    px(ctx, 620, wl - 34, 66, 4, '#4a3a2a');
    px(ctx, 623, wl - 15, 4, 15, '#3a2c20');
    px(ctx, 679, wl - 15, 4, 15, '#3a2c20');
    px(ctx, 706, wl - 24, 14, 24, '#2c3a34');
    px(ctx, 704, wl - 27, 18, 3, '#3e5147');
    // Fire hydrant.
    px(ctx, 980, wl - 20, 9, 20, '#8a4a3c');
    px(ctx, 977, wl - 23, 15, 4, '#a05a48');

    if (!this.layout) {
      this.staticReady = true;
      return;
    }

    const b = this.layout.building || { x: 120, y: 60, width: 960, height: 690 };
    drawBuildingShell(ctx, b);

    const zones = this.layout.zones || [];
    const seenFloors = new Set();
    const floorRight = new Map();
    for (const zone of zones) {
      const edge = zone.x + zone.width;
      floorRight.set(zone.floor, Math.max(floorRight.get(zone.floor) || 0, edge));
    }
    for (const zone of zones) {
      zone.isFloorLead = !seenFloors.has(zone.floor);
      zone.floorRight = floorRight.get(zone.floor);
      seenFloors.add(zone.floor);
    }
    for (const zone of zones) {
      drawZoneShell(ctx, zone, b);
      fillZone(ctx, zone, this.live);
      interiorFor(zone, ctx, this.live);
    }

    this.shaft = drawElevatorShaft(ctx, b, zones);
    this.building = b;
    const ground = zones.reduce((lo, z) => (z.y > (lo ? lo.y : -1) ? z : lo), null);
    const restY = ground ? ground.y + ground.height - 66 : b.y + b.height - 70;
    if (!this.lift.moving) {
      this.lift.y = restY;
      this.lift.target = restY;
    }
    this.lift.homeY = restY;
    this.staticReady = true;
  }

  /* ---------------------------------------------------------------- loop -- */

  _loop(now) {
    if (!this.running) return;
    const dt = Math.min(0.05, (now - this.lastFrame) / 1000);
    this.lastFrame = now;
    this.animTime += dt;
    this._update(dt);
    this._draw();
    requestAnimationFrame(this._loop);
  }

  _update(dt) {
    this._updateLift(dt);
    const w = this.worldW;
    updateTraffic(this.scenery.cars, this.worldW, dt);
    for (const wkr of this.scenery.walkers) {
      wkr.x += wkr.speed * wkr.dir * dt;
      if (wkr.x > w + 40) wkr.x = -30;
      if (wkr.x < -40) wkr.x = w + 30;
    }
    for (const cloud of this.scenery.clouds) {
      cloud.x += cloud.speed * dt;
      if (cloud.x > w + 200) cloud.x = -220;
    }
    for (const bird of this.scenery.birds) {
      bird.x += bird.speed * bird.dir * dt;
      if (bird.x > w + 30) bird.x = -20;
      if (bird.x < -30) bird.x = w + 20;
    }
  }

  /**
   * Decide whether the lift has a job, then move it. Called every frame; does nothing at all
   * while the backend reports no workflow movement.
   */
  _updateLift(dt) {
    if (!this.layout || !this.building) return;
    const zones = this.layout.zones || [];
    const cabTop = (zone) => zone.y + zone.height - 66;
    const floorLine = (zone) => zone.y + zone.height - 12;

    // A token that changed floor is a trip request: the work itself has to be carried to
    // another department. Nothing else starts the lift.
    for (const token of this.projectTokens) {
      const zone = zones.find((z) => token.y >= z.y && token.y <= z.y + z.height);
      if (!zone) continue;
      const previous = this.tokenPlaces.get(token.id);
      if (previous && previous.floor !== zone.floor && !this.lift.trip) {
        const from = zones.find((z) => z.id === previous.zoneId) || zone;
        this.lift.trip = {
          tokenId: token.id,
          phase: 'summon',
          fromY: cabTop(from),
          toY: cabTop(zone),
          boardLine: floorLine(from),
          exitLine: floorLine(zone),
          // The runner starts where the work was and ends where the work now is.
          startX: previous.x,
          x: previous.x,
          exitX: token.x,
          dwell: 0,
        };
        this.lift.target = cabTop(from);
        this.lift.moving = Math.abs(this.lift.y - this.lift.target) > 1;
        this.lift.restUntil = 0;
      }
      this.tokenPlaces.set(token.id, {
        floor: zone.floor,
        zoneId: zone.id,
        x: token.x,
        y: token.y,
      });
    }

    this._advanceCourier(dt);

    if (!this.lift.moving) {
      // Parked. After a delay at a delivery floor, return to the ground floor and stop.
      const idle = !this.lift.trip;
      if (
        idle &&
        this.lift.restUntil &&
        this.animTime > this.lift.restUntil &&
        this.lift.homeY !== undefined
      ) {
        this.lift.target = this.lift.homeY;
        this.lift.moving = true;
        this.lift.restUntil = 0;
      }
      return;
    }

    const speed = 90; // world pixels per second
    const delta = this.lift.target - this.lift.y;
    const stepSize = speed * dt;
    if (Math.abs(delta) <= stepSize) {
      this.lift.y = this.lift.target;
      this.lift.moving = false;
      // Wait at the floor before returning home, so arrivals are readable.
      if (
        !this.lift.trip &&
        this.lift.homeY !== undefined &&
        Math.abs(this.lift.y - this.lift.homeY) > 1
      ) {
        this.lift.restUntil = this.animTime + 6;
      }
    } else {
      this.lift.y += Math.sign(delta) * stepSize;
    }
  }

  /**
   * Walk the courier through the stages of one delivery.
   *
   * summon  the cab comes to the floor the work is on while the runner walks to the doors
   * board   doors open, the runner steps into the shaft
   * travel  doors shut, the cab carries the runner to the destination floor
   * alight  doors open, the runner steps out and walks the work to where the token now sits
   *
   * Every stage is driven by the same single backend fact — a token changed floor — so the
   * whole sequence is a rendering of that fact and not an animation invented to fill the eye.
   */
  _advanceCourier(dt) {
    const trip = this.lift.trip;
    if (!trip || !this.shaft) return;

    const doorX = this.shaft.ex - 8;
    const insideX = this.shaft.ex + this.shaft.ew / 2;
    const walk = 78 * dt; // world pixels per second, a purposeful indoor pace

    const stepToward = (target) => {
      const gap = target - trip.x;
      if (Math.abs(gap) <= walk) {
        trip.x = target;
        return true;
      }
      trip.x += Math.sign(gap) * walk;
      return false;
    };

    if (trip.phase === 'summon') {
      const atDoors = stepToward(doorX);
      const cabHere = !this.lift.moving && Math.abs(this.lift.y - trip.fromY) <= 1;
      if (atDoors && cabHere) {
        trip.phase = 'board';
        trip.dwell = 0;
      }
      return;
    }

    if (trip.phase === 'board') {
      trip.dwell += dt;
      stepToward(insideX);
      if (trip.dwell > 1.1) {
        trip.phase = 'travel';
        this.lift.target = trip.toY;
        this.lift.moving = Math.abs(this.lift.y - trip.toY) > 1;
        if (!this.lift.moving) trip.phase = 'alight';
      }
      return;
    }

    if (trip.phase === 'travel') {
      if (!this.lift.moving && Math.abs(this.lift.y - trip.toY) <= 1) {
        trip.phase = 'alight';
        trip.dwell = 0;
        trip.x = insideX;
      }
      return;
    }

    // alight
    trip.dwell += dt;
    const delivered = stepToward(trip.exitX);
    if (delivered && trip.dwell > 0.8) {
      this.lift.trip = null;
      // The cab waits, doors shut, then goes home by itself.
      this.lift.restUntil = this.animTime + 4;
    }
  }

  _draw() {
    const ctx = this.wctx;
    const time = this.animTime;
    const w = this.worldW;
    const h = this.worldH;

    ctx.clearRect(0, 0, w, h);

    // Sky first, then the things that pass in front of it, then the solid world. Clouds
    // drawn after the building would sail through the offices.
    if (this.staticReady) ctx.drawImage(this.bgLayer, 0, 0);
    for (const cloud of this.scenery.clouds) drawCloud(ctx, cloud);
    for (const bird of this.scenery.birds) drawBird(ctx, bird, time);
    if (this.staticReady) ctx.drawImage(this.staticLayer, 0, 0);

    // --- street -----------------------------------------------------------
    for (const t of this.scenery.trees) drawFoliage(ctx, t, time);
    for (let i = 0; i < LAMP_POSTS.length; i += 1) drawLampLight(ctx, LAMP_POSTS[i], time, i);
    for (const car of this.scenery.cars) drawCar(ctx, car, time);
    for (const wkr of this.scenery.walkers) drawWalker(ctx, wkr, time);

    if (!this.layout) {
      this._blit();
      return;
    }

    const b = this.building;

    // --- building furniture that moves -------------------------------------
    // Ceiling light cones give each floor a lit-from-above feel.
    for (const entry of this.live.ceilingLights) {
      const z = entry.zone;
      const st = zoneStyle(z.zone_type);
      const floorY = z.y + z.height - 12;
      let fixture = 0;
      for (let lx = z.x + 44; lx < z.x + z.width - 30; lx += 116) {
        const cx = lx + 17;
        fixture += 1;
        const jitter = 0.7 + ((hash32(`${z.id}${fixture}`) % 100) / 100) * 0.6;
        const cone = ctx.createLinearGradient(0, z.y + 9, 0, floorY);
        cone.addColorStop(0, `rgba(232,240,216,${(0.05 * jitter).toFixed(3)})`);
        cone.addColorStop(0.55, `rgba(232,240,216,${(0.016 * jitter).toFixed(3)})`);
        cone.addColorStop(1, 'rgba(232,240,216,0)');
        ctx.save();
        ctx.globalCompositeOperation = 'lighter';
        ctx.fillStyle = cone;
        ctx.beginPath();
        ctx.moveTo(cx - 16, z.y + 9);
        ctx.lineTo(cx + 16, z.y + 9);
        ctx.lineTo(cx + 46, floorY);
        ctx.lineTo(cx - 46, floorY);
        ctx.closePath();
        ctx.fill();
        ctx.restore();
        glow(ctx, cx, z.y + 10, 34, 'rgba(232,240,216,0.18)', 0.32 * jitter);
        ctx.save();
        ctx.globalAlpha = 0.04 * jitter;
        ctx.fillStyle = st.accent;
        ctx.beginPath();
        ctx.ellipse(cx, floorY - 4, 40, 5, 0, 0, TAU);
        ctx.fill();
        ctx.restore();
      }
    }
    for (const lamp of this.live.lamps) glow(ctx, lamp.x, lamp.y, lamp.r, lamp.color, 0.5);
    for (const clock of this.live.clocks) drawWallClock(ctx, clock.x, clock.y, time);
    for (const fan of this.live.fans) {
      ctx.save();
      ctx.translate(fan.x, fan.y);
      ctx.rotate(time * fan.rate);
      ctx.fillStyle = '#3b544a';
      for (let bl = 0; bl < 3; bl += 1) {
        ctx.rotate((Math.PI * 2) / 3);
        ctx.fillRect(0, -1, fan.r, 2);
      }
      ctx.restore();
    }
    for (const led of this.live.leds) {
      const on = Math.sin(time * led.rate + led.phase) > -0.1;
      px(ctx, led.x, led.y, 3, 2, on ? led.color : '#1b2a24');
    }

    // Zone activity is derived from the agents the backend placed in that zone.
    const activeZones = new Set();
    for (const agent of this.agents) {
      if (modeForAgent(agent) === 'work') {
        const zone = (this.layout.zones || []).find(
          (z) => agent.y >= z.y && agent.y <= z.y + z.height,
        );
        if (zone) activeZones.add(zone.id);
      }
    }

    for (const scr of this.live.screens) {
      drawScreenContent(ctx, scr.kind, scr.mx, scr.my, scr.w, scr.h, time, scr.seed, scr.accent, activeZones.has(scr.zoneId));
      // Screen light spilling onto the desk.
      ctx.save();
      ctx.globalAlpha = activeZones.has(scr.zoneId) ? 0.16 : 0.08;
      ctx.globalCompositeOperation = 'lighter';
      ctx.fillStyle = scr.accent;
      ctx.fillRect(scr.mx - 4, scr.my + scr.h + 2, scr.w + 8, 6);
      ctx.restore();
    }

    for (const vu of this.live.vuMeters) {
      const active = activeZones.has(vu.zoneId);
      for (let i = 0; i < 12; i += 1) {
        const level = active
          ? (Math.sin(time * 7 + i * 0.6) * 0.5 + 0.5) * (1 - i / 16)
          : 0.06;
        const bh = Math.max(1, level * vu.h);
        px(ctx, vu.x + i * 6, vu.y + vu.h - bh, 4, bh, i > 8 ? PAL.red : i > 5 ? PAL.amber : PAL.green);
      }
    }

    for (const sign of this.live.onAir) {
      const live = activeZones.has(sign.zoneId);
      px(ctx, sign.x, sign.y, 48, 13, live ? '#4a1f1c' : '#1e2a25');
      outline(ctx, sign.x, sign.y, 48, 13, live ? PAL.red : '#2b3f37');
      drawText(ctx, 'ON AIR', sign.x + 6, sign.y + 3, live ? '#ffb9a6' : '#3f5a4e', 1, 1);
      if (live) glow(ctx, sign.x + 24, sign.y + 6, 40, 'rgba(217,112,90,0.5)', 0.45);
    }

    for (const st of this.live.steam) {
      for (let i = 0; i < 4; i += 1) {
        const t = (time * 0.5 + i * 0.25) % 1;
        ctx.globalAlpha = (1 - t) * 0.5;
        px(ctx, st.x + Math.sin(t * 6 + i) * 3, st.y - t * 22, 3, 3, '#c9d8c0');
      }
      ctx.globalAlpha = 1;
    }
    for (const bub of this.live.bubbles) {
      for (let i = 0; i < 3; i += 1) {
        const t = (time * 0.4 + i * 0.33) % 1;
        ctx.globalAlpha = 0.6 - t * 0.4;
        px(ctx, bub.x + Math.sin(t * 8 + i) * 2, bub.y - t * 14, 2, 2, '#bfe4ef');
      }
      ctx.globalAlpha = 1;
    }
    for (const radar of this.live.radars) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(radar.mx + 2, radar.my + 2, radar.w - 4, radar.h - 4);
      ctx.clip();
      px(ctx, radar.mx + 2, radar.my + 2, radar.w - 4, radar.h - 4, '#101d18');
      ctx.strokeStyle = '#2f5a4a';
      for (let r = 4; r <= radar.r; r += 4) {
        ctx.beginPath();
        ctx.arc(radar.x, radar.y, r, 0, TAU);
        ctx.stroke();
      }
      const a = time * 1.5;
      ctx.strokeStyle = PAL.green;
      ctx.beginPath();
      ctx.moveTo(radar.x, radar.y);
      ctx.lineTo(radar.x + Math.cos(a) * radar.r, radar.y + Math.sin(a) * radar.r);
      ctx.stroke();
      ctx.restore();
    }

    // A whisper of warm light inside the shell: the offices are lived in, the night is not.
    ctx.save();
    ctx.globalAlpha = 0.085;
    ctx.globalCompositeOperation = 'lighter';
    ctx.fillStyle = '#d8b070';
    ctx.fillRect(b.x, b.y, b.width, b.height);
    ctx.restore();

    drawElevatorCab(ctx, b, this.shaft, time, this.lift);
    drawRoofDetails(ctx, b, time);
    drawSignage(ctx, b, time);

    // --- people ------------------------------------------------------------
    const zones = this.layout.zones || [];
    for (const agent of this.agents) {
      const id = agent.id || agent.agent_id;
      const look = this.looks.get(id) || agentLook(id, agent.role_name);
      const zone = zones.find((z) => agent.y >= z.y && agent.y <= z.y + z.height);
      const st = zoneStyle(zone ? zone.zone_type : 'DEFAULT');
      const floorY = zone ? zone.y + zone.height - 12 : agent.y;
      const mode = modeForAgent(agent);
      const selected = this.selectedAgentId === id;

      const body = drawCharacter(ctx, agent.x, floorY, look, mode, time, selected);
      drawStateMark(ctx, agent.x, body.headY, mode, time, st.accent);
      drawStateTag(
        ctx,
        agent.x,
        body.headY,
        mode === 'sleep' ? 'PAUSED' : String(agent.runtime_state || 'IDLE'),
        st.accent,
      );
      drawNamePlate(
        ctx,
        agent.x,
        floorY - 1,
        agent.display_name || agent.name || agent.role_name || 'AGENT',
        st.accent,
        selected,
      );
    }

    // --- workflow tokens and speech ---------------------------------------
    // A token in transit is drawn in the courier's hands, not twice.
    const inTransit = this.lift.trip ? this.lift.trip.tokenId : null;
    for (const token of this.projectTokens) {
      if (token.id === inTransit) continue;
      drawProjectToken(ctx, token, time);
    }

    // The courier, on the floor it is currently walking along. While riding it is drawn
    // inside the cab instead, by drawElevatorCab.
    const trip = this.lift.trip;
    if (trip && trip.phase !== 'travel') {
      const onOrigin = trip.phase === 'summon' || trip.phase === 'board';
      const line = onOrigin ? trip.boardLine : trip.exitLine;
      const target = onOrigin ? this.shaft.ex - 8 : trip.exitX;
      const facing = Math.abs(target - trip.x) < 0.5 ? 0 : Math.sign(target - trip.x);
      drawCourier(ctx, Math.round(trip.x), line, time, facing, true);
    }
    for (const bubble of this.speechBubbles) {
      const agent = this.agents.find((a) => (a.id || a.agent_id) === bubble.agentId);
      const zone = agent ? zones.find((z) => agent.y >= z.y && agent.y <= z.y + z.height) : null;
      const y = zone ? zone.y + zone.height - 58 : bubble.y;
      drawSpeechBubble(ctx, agent ? agent.x : bubble.x, y, bubble.text, time);
    }

    // --- atmosphere --------------------------------------------------------
    ctx.save();
    ctx.globalAlpha = 0.4;
    for (const d of this.scenery.dust) {
      const dx = d.x + Math.sin(time * 0.35 + d.p) * 14;
      const dy = (d.y + time * 5 * d.s) % h;
      ctx.globalAlpha = 0.10 * d.s;
      px(ctx, dx, dy, 1, 1, '#d8e4d2');
    }
    ctx.restore();

    const vig = ctx.createRadialGradient(w / 2, h / 2, h * 0.35, w / 2, h / 2, h * 0.85);
    vig.addColorStop(0, 'rgba(0,0,0,0)');
    vig.addColorStop(1, 'rgba(4,10,8,0.34)');
    ctx.fillStyle = vig;
    ctx.fillRect(0, 0, w, h);

    this._blit();
  }

  /** Scale the world buffer onto the visible canvas without smoothing the pixels. */
  _blit() {
    const ctx = this.ctx;
    ctx.imageSmoothingEnabled = false;
    // Beyond the world edges, continue the night rather than showing a black band.
    if (!this._backdrop || this._backdropH !== this.canvas.height) {
      const g = ctx.createLinearGradient(0, 0, 0, this.canvas.height);
      g.addColorStop(0, PAL.skyTop);
      g.addColorStop(0.6, '#0d1a18');
      g.addColorStop(1, PAL.ground);
      this._backdrop = g;
      this._backdropH = this.canvas.height;
    }
    ctx.fillStyle = this._backdrop;
    ctx.fillRect(0, 0, this.canvas.width, this.canvas.height);
    const { panX, panY, zoom } = this.viewport;
    ctx.drawImage(
      this.world,
      Math.round(panX),
      Math.round(panY),
      Math.round(this.worldW * zoom),
      Math.round(this.worldH * zoom),
    );
  }

  destroy() {
    this.running = false;
  }
}
