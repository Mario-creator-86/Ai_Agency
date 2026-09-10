import { drawHuman, drawAnimal } from './street_actor.js';
import { drawDigitalTime } from './office_clock.js';
import { refreshVehicle, mixColor, streetClock, randomSource, randomVehicle, depthSortedTraffic, pixelDisc, StreetLife } from './street_life.js';
import { drawText, textWidth } from './pixel_font.js';
import { SKY, CITY, STREET, FACADE, MAT, UI, AMBIENT, department, rgba, withAlpha, mix } from './office_palette.js';
import { glow, contactShadow, cachedSprite, PixelGrid, drawSprite } from './pixel_sprites.js';
import {
  px, slab, outlineRect, drawZoneShell, bakeRoomLight, interiorFor, drawDeskFronts, fillZone,
  drawScreenContent, floorLine, SLAB_H, CEILING_H,
} from './office_rooms.js';
import {
  agentLook, modeForAgent, drawCharacterBody, drawCharacterHands, drawStateMark, characterMetrics,
} from './office_characters.js';

/**
 * AMN-AI (Autonomous Machine Nexus) — 2D office renderer.
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
 * means nothing happened. Street randomness and local time do not emit operational events.
 *
 * RENDERING MODEL
 * ---------------
 * The world is drawn at a fixed 1:1 resolution into an offscreen buffer and then blitted to the
 * visible canvas with image smoothing disabled, so the pixel art stays crisp at every zoom.
 *
 * Static art is rasterised once into cached layers and reused every frame:
 *   bg       sky and skyline (repainted when the local clock changes)
 *   layer A  street, facade, room shells, back-of-room furniture, chairs, baked room light
 *   layer B  desk fronts, monitors, desk lamps — everything that stands in front of a seated
 *            person, so a character can sit *behind* their desk
 * Only things that move are painted per frame, and characters are compiled sprites, so a frame
 * costs a handful of drawImage calls plus the screens and LEDs.
 */

/* ============================================================================
   Deterministic randomness
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

const TAU = Math.PI * 2;
const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
const lerp = (a, b, t) => a + (b - a) * t;

/* ============================================================================
   Viewport — pan/zoom.
   ========================================================================== */

export class Viewport {
  constructor(canvas) {
    this.canvas = canvas;
    this.panX = 0;
    this.panY = 0;
    this.zoom = 1;
    this.minZoom = 0.1;
    this.bottomInset = 0;
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
    const ch = Math.max(1, (this.canvas.height || 1) - this.bottomInset);
    const scale = Math.min(cw / worldWidth, ch / worldHeight);
    this.zoom = clamp(scale, this.minZoom, this.maxZoom);
    this.panX = (cw - worldWidth * this.zoom) / 2;
    this.panY = (ch - worldHeight * this.zoom) / 2;
  }
}

/* ============================================================================
   Scenery: sky, skyline, street. None of this reflects backend state.
   ========================================================================== */

const WORLD_W = 1200;
const WORLD_H = 800;

let HORIZON = 750;
const STREET_DEPTH = 250;
const PLINTH_H = 22;    // building base course, below the ground-floor slab
const WALK_H = 52;      // pavement depth; deep enough that a 34px person clears the base
const ROAD_H = 118;     // two lanes sized for full-scale vehicles

function setHorizon(y) {
  HORIZON = Math.round(y);
}

function drawSky(ctx, w, h, daylight = 0) {
  const g = ctx.createLinearGradient(0, 0, 0, HORIZON);
  g.addColorStop(0, mixColor(SKY.zenith, SKY.dayZenith, daylight));
  g.addColorStop(0.42, mixColor(SKY.upper, SKY.dayUpper, daylight));
  g.addColorStop(0.7, mixColor(SKY.band, SKY.dayBand, daylight));
  g.addColorStop(0.88, mixColor(SKY.dusk, SKY.dayBand, daylight));
  g.addColorStop(1, mixColor(SKY.horizon, SKY.dayHorizon, daylight));
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, w, HORIZON);

  if (daylight > 0.5) {
    pixelDisc(ctx, 985, 96, 18, '#fff4c0');
    glow(ctx, 985, 96, 90, 'rgba(255,240,190,0.5)', 0.6);
    return;
  }
  // Stars, thinning towards the warm horizon; a few twinkle brighter.
  const rnd = mulberry32(0xa17c);
  for (let i = 0; i < 220; i += 1) {
    const x = Math.floor(rnd() * w);
    const y = Math.floor(rnd() * 420);
    const bright = rnd();
    if (bright > 0.9) {
      px(ctx, x, y, 2, 2, SKY.star);
      px(ctx, x - 1, y, 1, 2, withAlpha(SKY.star, 0.3));
      px(ctx, x + 2, y, 1, 2, withAlpha(SKY.star, 0.3));
    } else {
      ctx.globalAlpha = 0.2 + bright * 0.55;
      px(ctx, x, y, 1, 1, SKY.star);
      ctx.globalAlpha = 1;
    }
  }
  // Moon: a soft halo and a couple of maria.
  const mx = 985;
  const my = 96;
  glow(ctx, mx, my, 70, 'rgba(245,236,210,0.45)', 0.7);
  pixelDisc(ctx, mx, my, 17, SKY.moon);
  pixelDisc(ctx, mx - 4, my - 3, 5, SKY.moonSea);
  pixelDisc(ctx, mx + 5, my + 4, 4, SKY.moonSea);
  px(ctx, mx - 8, my + 9, 4, 3, SKY.moonSea);
  px(ctx, mx - 15, my - 6, 2, 8, SKY.moon);
}

/** Three skyline bands: the far one is flat and blue; the near one carries detail. */
function drawSkyline(ctx, w, daylight = 0) {
  const bands = [
    { seed: 0x33aa, color: mixColor(CITY.far, '#8fb0cc', daylight * 0.7), top: mixColor(CITY.farTop, '#a8c4da', daylight * 0.7), base: HORIZON - 60, min: 40, max: 150, width: [22, 50], lit: 0.12, step: 0 },
    { seed: 0x51ee, color: mixColor(CITY.mid, '#6d8aa8', daylight * 0.7), top: mixColor(CITY.midTop, '#87a2bc', daylight * 0.7), base: HORIZON - 34, min: 70, max: 210, width: [28, 66], lit: 0.2, step: 0 },
    { seed: 0x7c31, color: mixColor(CITY.near, '#4a5d78', daylight * 0.7), top: mixColor(CITY.mid, '#5c6f8a', daylight * 0.7), base: HORIZON - 12, min: 90, max: 270, width: [34, 80], lit: 0.32, step: 1 },
  ];
  const lit = daylight > 0.5 ? 0.25 : 1;
  for (const band of bands) {
    const rnd = mulberry32(band.seed);
    let x = -30;
    while (x < w + 40) {
      const bw = Math.round(lerp(band.width[0], band.width[1], rnd()));
      const bh = Math.round(lerp(band.min, band.max, rnd() * rnd() + 0.15));
      const top = band.base - bh;
      px(ctx, x, top, bw, bh, band.color);
      px(ctx, x, top, bw, 2, band.top);
      px(ctx, x, top, 1, bh, band.top);
      // Roof furniture and beacons on the nearer band.
      if (band.step && rnd() > 0.5) {
        const tw = 6 + Math.floor(rnd() * 10);
        px(ctx, x + 6, top - 5, tw, 5, band.color);
        px(ctx, x + 6, top - 5, tw, 1, band.top);
      }
      if (band.step && rnd() > 0.8) {
        px(ctx, x + bw - 8, top - 18, 2, 18, band.color);
        px(ctx, x + bw - 9, top - 20, 4, 3, CITY.beacon);
      }
      // Window grid: warm and cool lights, some floors dark.
      for (let wy = top + 8; wy < band.base - 8; wy += 9) {
        const floorDark = rnd() < 0.2;
        for (let wx = x + 4; wx < x + bw - 5; wx += 7) {
          const r = rnd();
          if (floorDark) continue;
          if (r < band.lit * lit) px(ctx, wx, wy, 3, 4, r < band.lit * 0.35 ? CITY.windowCool : CITY.windowWarm);
          else if (r < band.lit + 0.25) px(ctx, wx, wy, 3, 4, CITY.windowDim);
        }
      }
      x += bw + 2 + Math.floor(rnd() * 8);
    }
  }
}

/** Ground plane, road, kerb, markings, plus the studio's own forecourt. */
function drawGround(ctx, w) {
  const plinthY = HORIZON;
  const walkY = HORIZON + PLINTH_H;
  const roadY = walkY + WALK_H;
  const roadBottom = roadY + ROAD_H;

  // Base course the building stands on.
  px(ctx, 0, plinthY, w, PLINTH_H, STREET.plinth[2]);
  px(ctx, 0, plinthY, w, 2, STREET.plinth[4]);
  px(ctx, 0, plinthY + PLINTH_H - 2, w, 2, STREET.plinth[0]);
  for (let x = 0; x < w; x += 46) px(ctx, x, plinthY + 3, 1, PLINTH_H - 6, STREET.plinth[1]);

  // Pavement with slab joints and a lit lip.
  px(ctx, 0, walkY, w, WALK_H, STREET.pavement[2]);
  px(ctx, 0, walkY, w, 2, STREET.pavement[4]);
  for (let x = 0; x < w; x += 34) px(ctx, x, walkY + 3, 1, WALK_H - 6, STREET.pavement[1]);
  px(ctx, 0, walkY + WALK_H / 2, w, 1, STREET.pavement[1]);
  // Kerb.
  px(ctx, 0, roadY - 5, w, 5, STREET.kerb[2]);
  px(ctx, 0, roadY - 5, w, 1, STREET.kerb[4]);
  px(ctx, 0, roadY - 1, w, 1, STREET.kerb[0]);

  // Carriageway with a centre line and a pedestrian crossing.
  px(ctx, 0, roadY, w, ROAD_H, STREET.asphalt[2]);
  px(ctx, 0, roadY, w, 3, STREET.asphalt[1]);
  const rnd = mulberry32(0x0ad5);
  for (let i = 0; i < 260; i += 1) px(ctx, rnd() * w, roadY + 4 + rnd() * (ROAD_H - 8), 1, 1, rnd() > 0.5 ? STREET.asphalt[3] : STREET.asphalt[1]);
  for (let x = 10; x < w; x += 78) px(ctx, x, roadY + ROAD_H / 2 - 2, 38, 4, STREET.line);
  const crossX = 430;
  for (let i = 0; i < 7; i += 1) px(ctx, crossX + i * 17, roadY + 4, 11, ROAD_H - 8, STREET.crossing);

  // Far kerb and foreground pavement with drains and planters.
  px(ctx, 0, roadBottom, w, 6, STREET.kerb[2]);
  px(ctx, 0, roadBottom, w, 1, STREET.kerb[4]);
  px(ctx, 0, roadBottom + 6, w, WORLD_H, STREET.pavement[1]);
  px(ctx, 0, roadBottom + 6, w, 1, STREET.pavement[3]);
  for (let x = 20; x < w; x += 180) {
    px(ctx, x, roadBottom + 20, 30, 10, STREET.asphalt[0]);
    for (let i = 0; i < 5; i += 1) px(ctx, x + 4 + i * 6, roadBottom + 23, 3, 4, STREET.asphalt[3]);
  }
  for (let x = 120; x < w; x += 260) {
    slab(ctx, x, roadBottom + 12, 72, 26, STREET.planter);
    const rnd2 = mulberry32(hash32(`planter${x}`));
    for (let i = 0; i < 10; i += 1) {
      const lh = 8 + Math.floor(rnd2() * 6);
      px(ctx, x + 4 + i * 7, roadBottom + 12 - lh, 6, lh, rnd2() > 0.5 ? STREET.leaf[2] : STREET.leaf[1]);
      px(ctx, x + 4 + i * 7, roadBottom + 12 - lh, 6, 1, STREET.leaf[3]);
    }
  }
}

/** Tallest pedestrian drawn on the pavement, in world pixels. */
export const PEDESTRIAN_HEIGHT = 34 * 1.1;

/**
 * Street geometry derived from where the building meets the ground.
 * Exported so the invariant that matters can be asserted in tests: a person standing on the
 * pavement must be completely below the building base.
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

/* ---------------------------------------------------------------- trees */

function makeTrees(seed, w) {
  const rnd = mulberry32(seed);
  const trees = [];
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
  contactShadow(ctx, tree.x, baseY + 1, 9, 1, 0.4);
  px(ctx, tree.x - 4, baseY - tree.height, 8, tree.height, STREET.trunk[1]);
  px(ctx, tree.x - 3, baseY - tree.height, 2, tree.height, STREET.trunk[3]);
  px(ctx, tree.x + 3, baseY - tree.height, 1, tree.height, STREET.trunk[0]);
  px(ctx, tree.x - 8, baseY - 3, 6, 3, STREET.trunk[1]);
  px(ctx, tree.x + 2, baseY - 3, 6, 3, STREET.trunk[1]);
  px(ctx, tree.x + 3, baseY - tree.height + 16, 10, 3, STREET.trunk[1]);
  px(ctx, tree.x - 12, baseY - tree.height + 28, 9, 3, STREET.trunk[1]);
}

function drawFoliage(ctx, tree, time) {
  const baseY = walkLine();
  const topY = baseY - tree.height;
  const sway = Math.sin(time * 0.9 + tree.phase) * 3 + tree.lean * 2;
  const rnd = mulberry32(hash32(`leaf${tree.x}`));
  const clusters = 14;
  for (let i = 0; i < clusters; i += 1) {
    const a = (i / clusters) * TAU + tree.phase;
    const rx = Math.cos(a) * tree.spread * (0.55 + rnd() * 0.5);
    const ry = Math.sin(a) * tree.spread * 0.62 * (0.55 + rnd() * 0.5);
    const size = 10 + Math.floor(rnd() * 9);
    const depth = rnd();
    const color = depth > 0.66 ? STREET.leaf[3] : depth > 0.33 ? STREET.leaf[2] : STREET.leaf[1];
    const lx = Math.round(tree.x + rx + sway * (0.4 + depth * 0.8) - size / 2);
    const ly = Math.round(topY + ry - 6);
    px(ctx, lx + 1, ly - 1, size - 2, size + 2, STREET.leaf[0]);
    px(ctx, lx - 1, ly + 2, size + 2, size - 4, STREET.leaf[0]);
    px(ctx, lx + 2, ly, size - 4, size, color);
    px(ctx, lx, ly + 3, size, size - 6, color);
    px(ctx, lx + 3, ly + 1, size - 6, 2, depth > 0.5 ? STREET.leaf[4] : STREET.leaf[3]);
    px(ctx, lx + 2, ly + size - 2, size - 4, 2, STREET.leaf[0]);
  }
  px(ctx, Math.round(tree.x - 6 + sway), topY - 16, 12, 7, STREET.leaf[3]);
  px(ctx, Math.round(tree.x - 4 + sway), topY - 17, 8, 2, STREET.leaf[4]);
}

/* ------------------------------------------------------ street furniture */

const LAMP_POSTS = [46, 1148];

function drawLampPost(ctx, x) {
  const baseY = walkLine();
  contactShadow(ctx, x, baseY + 1, 9, 1, 0.4);
  px(ctx, x - 4, baseY - 118, 8, 118, STREET.lampPost[1]);
  px(ctx, x - 3, baseY - 118, 2, 118, STREET.lampPost[3]);
  px(ctx, x - 9, baseY - 4, 18, 5, STREET.lampPost[1]);
  px(ctx, x - 9, baseY - 4, 18, 1, STREET.lampPost[3]);
  px(ctx, x - 4, baseY - 123, 30, 5, STREET.lampPost[1]);
  px(ctx, x - 4, baseY - 123, 30, 1, STREET.lampPost[3]);
  px(ctx, x + 19, baseY - 119, 10, 10, STREET.lampPost[2]);
  px(ctx, x + 19, baseY - 119, 10, 1, STREET.lampPost[4]);
}

function drawLampLight(ctx, x, time, i) {
  const baseY = walkLine();
  const flicker = 0.86 + Math.sin(time * 2.6 + i * 1.7) * 0.05 + Math.sin(time * 11 + i) * 0.02;
  px(ctx, x + 21, baseY - 111, 6, 6, STREET.lampGlow);
  glow(ctx, x + 24, baseY - 108, 104, 'rgba(255,207,138,0.42)', 0.55 * flicker);
  ctx.save();
  ctx.globalAlpha = 0.16 * flicker;
  ctx.fillStyle = STREET.lampGlow;
  ctx.beginPath();
  ctx.ellipse(x + 24, baseY + 12, 68, 13, 0, 0, TAU);
  ctx.fill();
  ctx.restore();
}

/* --------------------------------------------------------------- traffic */

const TRAFFIC_LOOP_PAD_START = -180;
const TRAFFIC_LOOP_PAD_END = 120;
const TRAFFIC_MIN_GAP = 24;
const TRAFFIC_SLOW_GAP = 90;

/** @param {number} seed @param {boolean | {vehicles: Record<string, number>}} night */
export function makeTraffic(seed, night = false) {
  const rnd = mulberry32(seed);
  const cars = [];
  const loopLength = WORLD_W + TRAFFIC_LOOP_PAD_END - TRAFFIC_LOOP_PAD_START;
  for (const dir of [1, -1]) {
    const count = dir > 0 ? 3 : 2;
    const stretch = loopLength / count;
    for (let i = 0; i < count; i += 1) {
      cars.push({
        style: randomVehicle(rnd, night),
        dir,
        laneOffset: dir > 0 ? 0.78 : 0.34,
        x: TRAFFIC_LOOP_PAD_START + i * stretch + rnd() * (stretch - 200),
        speed: (52 + rnd() * 48) * dir,
        bobPhase: rnd() * TAU,
        visible: undefined,
        previousX: 0,
      });
    }
  }
  return cars;
}

/**
 * Lane-aware traffic step. Each lane is a platoon: a follower within TRAFFIC_SLOW_GAP of its
 * leader adopts the leader's speed, and a hard clamp holds TRAFFIC_MIN_GAP, including across
 * the loop seam.
 */
export function updateTraffic(cars, worldW, dt) {
  const loopLength = worldW + TRAFFIC_LOOP_PAD_END - TRAFFIC_LOOP_PAD_START;
  for (const dir of [1, -1]) {
    const lane = cars.filter((c) => c.dir === dir);
    lane.sort((a, b) => (b.x - a.x) * dir);
    for (let i = 0; i < lane.length; i += 1) {
      const car = lane[i];
      let v = Math.abs(car.speed);
      if (lane.length > 1) {
        const leader = i === 0 ? lane[lane.length - 1] : lane[i - 1];
        let ahead = (leader.x - car.x) * dir;
        if (i === 0) ahead += loopLength;
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

function drawCar(ctx, car, time, daylight = 0) {
  const s = car.style;
  const lane = roadTop() + ROAD_H * car.laneOffset;
  const y = lane - s.h - Math.max(4, Math.round(s.h * 0.23));
  const x = car.x;
  const bob = Math.sin(time * 9 + car.bobPhase) * 0.6;
  const flip = car.dir < 0;
  const wheelR = Math.max(4, Math.round(s.h * 0.23));
  const body = s.body;
  const bodyLight = mix(body, AMBIENT.light, 0.35);
  const bodyDark = mix(body, AMBIENT.shadow, 0.45);
  const glassC = '#9fc6d8';

  ctx.save();
  ctx.translate(Math.round(x), Math.round(y + bob));
  if (flip) {
    ctx.translate(s.w, 0);
    ctx.scale(-1, 1);
  }

  contactShadow(ctx, s.w / 2, s.h + 2, s.w / 2 - 2, 2, 0.45);

  if (s.kind === 'bus' || s.kind === 'minibus') {
    px(ctx, -1, -1, s.w + 2, s.h + 2, AMBIENT.shadow);
    px(ctx, 0, 0, s.w, s.h, body);
    px(ctx, 0, 0, s.w, 2, bodyLight);
    px(ctx, 0, s.h * 0.34, s.w, 2, bodyDark);
    px(ctx, 0, s.h - 4, s.w, 4, bodyDark);
    for (let wx = 8; wx < s.w - 16; wx += 22) {
      px(ctx, wx, 8, 16, 18, glassC);
      px(ctx, wx, 8, 16, 1, '#dbeef5');
      px(ctx, wx + 12, 8, 4, 18, '#7ba6bb');
    }
    px(ctx, s.w - 14, 7, 11, 20, '#c9dfe8');
    px(ctx, 6, s.h - 16, 10, 14, bodyDark);
  } else if (s.kind === 'van' || s.kind === 'pickup') {
    px(ctx, -1, 7, s.w + 2, s.h - 6, AMBIENT.shadow);
    px(ctx, 0, 8, s.w, s.h - 8, body);
    px(ctx, 0, 8, s.w, 1, bodyLight);
    px(ctx, 0, s.h - 4, s.w, 4, bodyDark);
    px(ctx, s.w - 43, -1, 44, 13, AMBIENT.shadow);
    px(ctx, s.w - 42, 0, 42, 12, s.roof);
    px(ctx, s.w - 42, 0, 42, 1, bodyLight);
    px(ctx, s.w - 36, 3, 27, 12, glassC);
    px(ctx, s.w - 36, 3, 27, 1, '#dbeef5');
    if (s.kind === 'pickup') { px(ctx, 0, 4, 57, 14, MAT.steel[1]); px(ctx, 0, 16, 57, 3, body); }
    else { px(ctx, 8, 16, 54, 14, bodyDark); px(ctx, 12, 20, 46, 3, bodyLight); }
  } else {
    px(ctx, -1, s.h * 0.42 - 1, s.w + 2, s.h * 0.58 + 2, AMBIENT.shadow);
    px(ctx, 0, s.h * 0.42, s.w, s.h * 0.58, body);
    px(ctx, 0, s.h * 0.42, s.w, 1, bodyLight);
    px(ctx, 0, s.h - 4, s.w, 4, bodyDark);
    const cabin = ['wagon', 'suv', 'hatchback'].includes(s.kind) ? 0.64 : 0.5;
    px(ctx, s.w * 0.16 - 1, s.h * 0.05 - 1, s.w * cabin + 2, s.h * 0.4 + 2, AMBIENT.shadow);
    px(ctx, s.w * 0.16, s.h * 0.05, s.w * cabin, s.h * 0.4, s.roof);
    px(ctx, s.w * 0.16, s.h * 0.05, s.w * cabin, 1, bodyLight);
    if (s.kind === 'taxi') { px(ctx, s.w * 0.43, -4, 13, 5, '#f4da7b'); px(ctx, s.w * 0.43, -4, 13, 1, '#fff0b3'); }
    px(ctx, s.w * 0.24, s.h * 0.12, s.w * 0.2, s.h * 0.26, glassC);
    px(ctx, s.w * 0.47, s.h * 0.12, s.w * 0.2, s.h * 0.26, '#8fb9cc');
    px(ctx, s.w * 0.24, s.h * 0.12, s.w * 0.2, 1, '#dbeef5');
  }

  // Chrome beltline, door seams, handles and bumpers.
  px(ctx, 5, s.h * 0.48, s.w - 10, 1, withAlpha('#f7edd3', 0.5));
  if (s.kind !== 'bus') {
    px(ctx, s.w * 0.46, s.h * 0.44, 1, s.h * 0.37, withAlpha(AMBIENT.shadow, 0.5));
    px(ctx, s.w * 0.39, s.h * 0.5, 6, 2, MAT.chrome[3]);
    px(ctx, s.w * 0.68, s.h * 0.5, 5, 2, MAT.chrome[3]);
  }
  px(ctx, 0, s.h - 6, 6, 2, MAT.chrome[2]);
  px(ctx, s.w - 6, s.h - 6, 6, 2, MAT.chrome[3]);
  const wheelY = s.h - 1;
  for (const wheelX of [s.w * 0.2, s.w * 0.8]) {
    pixelDisc(ctx, wheelX, wheelY, wheelR + 1, AMBIENT.shadow);
    pixelDisc(ctx, wheelX, wheelY, wheelR - 1, MAT.black[2]);
    pixelDisc(ctx, wheelX, wheelY, Math.max(2, wheelR - 3), MAT.chrome[2]);
    pixelDisc(ctx, wheelX, wheelY, 2, MAT.black[3]);
    const angle = time * car.dir * 3;
    px(ctx, wheelX + Math.cos(angle) * (wheelR - 4), wheelY + Math.sin(angle) * (wheelR - 4), 1, 1, MAT.chrome[4]);
  }
  px(ctx, s.w - 3, s.h * 0.5, 3, 5, '#ffe9b4');
  px(ctx, 0, s.h * 0.52, 3, 5, '#e0483a');
  ctx.restore();

  if (daylight > 0.6) return;
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
  // Tail light glow.
  glow(ctx, flip ? x + s.w + 2 : x - 2, y + s.h * 0.55, 14, 'rgba(255,90,70,0.5)', 0.6);
}

/* ------------------------------------------------------------ pedestrians */

function drawWalker(ctx, wkr, time) {
  const baseY = walkLine() - (wkr.depth || 0);
  if (wkr.activity === 'cat') { drawAnimal(ctx, wkr, baseY); return; }
  const human = drawHuman(ctx, wkr, baseY);
  if (wkr.dog) {
    const collar = drawAnimal(ctx, wkr, baseY, true);
    ctx.strokeStyle = '#bba77a'; ctx.lineWidth = 1; ctx.beginPath();
    ctx.moveTo(human.hand.x, human.hand.y);
    ctx.quadraticCurveTo((human.hand.x + collar.x) / 2, baseY - 4, collar.x, collar.y); ctx.stroke();
  }
  if (wkr.activity === 'phone' && wkr.age < wkr.talkUntil) {
    const label = wkr.speech, bw = textWidth(label, 1, 0) + 12;
    const bx = clamp(wkr.x + 15, 4, WORLD_W - bw - 4), by = HORIZON + PLINTH_H + 2;
    px(ctx, bx - 1, by - 1, bw + 2, 24, AMBIENT.shadow);
    px(ctx, bx, by, bw, 22, UI.paper);
    px(ctx, bx, by, bw, 1, '#ffffff');
    drawText(ctx, 'DECOR', bx + 5, by + 3, '#8a7d5a', 1, 0);
    drawText(ctx, label, bx + 5, by + 12, UI.ink, 1, 0);
  }
}

/* ---------------------------------------------------------- clouds, birds */

function makeClouds(seed) {
  const rnd = mulberry32(seed);
  const clouds = [];
  for (let i = 0; i < 7; i += 1) {
    clouds.push({
      x: rnd() * (WORLD_W + 300) - 150,
      y: 40 + rnd() * 240,
      scale: 0.6 + rnd() * 1.5,
      speed: 3 + rnd() * 7,
      alpha: 0.07 + rnd() * 0.12,
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
    px(ctx, cloud.x + ox, cloud.y + oy, w, h, '#b8c4d8');
    px(ctx, cloud.x + ox + 2, cloud.y + oy - 2, w - 4, 2, '#d8e0ec');
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
  ctx.fillStyle = '#2c3048';
  const w = 3;
  ctx.fillRect(bird.x, y, 2, 1);
  ctx.fillRect(bird.x - w, y - Math.round(flap * 2), w, 1);
  ctx.fillRect(bird.x + 2, y - Math.round(flap * 2), w, 1);
}

/* ============================================================================
   The building: facade, roof, signage, lift.
   Geometry comes from the backend layout: building box, zones (floors) and desks.
   ========================================================================== */

const PIER_W = 16;

function drawBuildingShell(ctx, b, zones) {
  const { x, y, width: w, height: h } = b;
  const stone = FACADE.stone;

  // Ground shadow and the plinth the building sits on.
  ctx.save();
  ctx.globalAlpha = 0.4;
  px(ctx, x - PIER_W - 6, y + h, w + PIER_W * 2 + 12, 8, AMBIENT.shadow);
  ctx.restore();

  // Piers: warm limestone with a lit left face and a shadow right face.
  const pier = (px0, lit) => {
    px(ctx, px0 - 1, y - 30, PIER_W + 2, h + 32, AMBIENT.shadow);
    px(ctx, px0, y - 29, PIER_W, h + 30, stone[2]);
    px(ctx, px0, y - 29, 3, h + 30, lit ? stone[4] : stone[3]);
    px(ctx, px0 + PIER_W - 3, y - 29, 3, h + 30, stone[0]);
    // Stone courses.
    for (let cy = y - 20; cy < y + h; cy += 18) {
      px(ctx, px0 + 1, cy, PIER_W - 2, 1, stone[1]);
      px(ctx, px0 + 1, cy + 1, PIER_W - 2, 1, withAlpha(stone[4], 0.35));
    }
  };
  pier(x - PIER_W, true);
  pier(x + w, false);

  // Slab ends project through the piers at every floor line, catching the light.
  const floorLines = new Set();
  for (const z of zones) floorLines.add(z.y + z.height);
  for (const fy of floorLines) {
    for (const px0 of [x - PIER_W - 3, x + w]) {
      px(ctx, px0, fy - SLAB_H, PIER_W + 3, SLAB_H, FACADE.slab[2]);
      px(ctx, px0, fy - SLAB_H, PIER_W + 3, 1, FACADE.slab[4]);
      px(ctx, px0, fy - 1, PIER_W + 3, 1, FACADE.slab[0]);
    }
  }

  // Roof: parapet slab, plant room, water tank, a mast and dish.
  px(ctx, x - PIER_W - 8, y - 42, w + PIER_W * 2 + 16, 12, AMBIENT.shadow);
  px(ctx, x - PIER_W - 7, y - 41, w + PIER_W * 2 + 14, 10, FACADE.roof[2]);
  px(ctx, x - PIER_W - 7, y - 41, w + PIER_W * 2 + 14, 2, FACADE.roof[4]);
  px(ctx, x - PIER_W - 7, y - 33, w + PIER_W * 2 + 14, 2, FACADE.roof[0]);
  // Roof deck between parapet and the top zone's ceiling.
  px(ctx, x - PIER_W, y - 31, w + PIER_W * 2, 31, FACADE.roof[1]);
  slab(ctx, x + 40, y - 74, 90, 32, FACADE.roof);
  px(ctx, x + 48, y - 66, 20, 16, FACADE.roof[0]);
  px(ctx, x + 76, y - 66, 46, 6, FACADE.roof[3]);
  for (let vx = x + 78; vx < x + 120; vx += 5) px(ctx, vx, y - 58, 3, 12, FACADE.roof[0]);
  // Water tank on legs.
  px(ctx, x + 160, y - 60, 3, 18, FACADE.roof[0]);
  px(ctx, x + 195, y - 60, 3, 18, FACADE.roof[0]);
  slab(ctx, x + 154, y - 90, 50, 32, MAT.steel);
  px(ctx, x + 158, y - 96, 42, 6, MAT.steel[3]);
  px(ctx, x + 158, y - 96, 42, 1, MAT.steel[4]);
  // Antenna mast and dish.
  px(ctx, x + w - 120, y - 118, 3, 78, MAT.steel[2]);
  px(ctx, x + w - 120, y - 118, 1, 78, MAT.steel[4]);
  px(ctx, x + w - 132, y - 96, 27, 2, MAT.steel[3]);
  px(ctx, x + w - 126, y - 106, 15, 2, MAT.steel[3]);
  px(ctx, x + w - 210, y - 62, 4, 22, MAT.steel[2]);
  ctx.fillStyle = MAT.steel[3];
  ctx.beginPath();
  ctx.arc(x + w - 208, y - 66, 15, Math.PI * 0.15, Math.PI * 1.15);
  ctx.fill();
  ctx.fillStyle = MAT.steel[4];
  ctx.beginPath();
  ctx.arc(x + w - 208, y - 66, 12, Math.PI * 0.25, Math.PI * 0.9);
  ctx.fill();
  // Sign board that the neon sits on.
  const label = 'AMN-AI · AUTONOMOUS MACHINE NEXUS';
  const sw = textWidth(label, 2, 1) + 40;
  const sx = x + (w - sw) / 2;
  px(ctx, sx - 1, y - 33, sw + 2, 30, AMBIENT.shadow);
  px(ctx, sx, y - 32, sw, 28, FACADE.signBoard[1]);
  px(ctx, sx, y - 32, sw, 1, FACADE.signBoard[3]);
  px(ctx, sx, y - 5, sw, 1, FACADE.signBoard[0]);
  for (let bx = sx + 6; bx < sx + sw - 4; bx += 12) px(ctx, bx, y - 30, 1, 24, FACADE.signBoard[2]);
}

/** Roof fans and the beacon are animated, so they are drawn per frame. */
function drawRoofDetails(ctx, b, time) {
  const { x, y, width: w } = b;
  const fans = [[x + 92, y - 74], [x + 112, y - 74]];
  for (let i = 0; i < fans.length; i += 1) {
    const [fx, fy] = fans[i];
    const a = time * (i === 0 ? 3.2 : -2.4);
    ctx.save();
    ctx.translate(fx, fy);
    ctx.rotate(a);
    ctx.fillStyle = FACADE.roof[4];
    for (let bl = 0; bl < 4; bl += 1) {
      ctx.rotate(Math.PI / 2);
      ctx.fillRect(0, -1, 7, 2);
    }
    ctx.restore();
  }
  const beat = (Math.sin(time * 2.4) + 1) / 2;
  if (beat > 0.55) {
    px(ctx, x + w - 122, y - 121, 5, 4, CITY.beacon);
    glow(ctx, x + w - 120, y - 119, 20, 'rgba(255,106,90,0.85)', beat * 0.6);
  }
}

/** Freestanding street clock. */
function drawStreetClock(ctx, building, worldWidth, label) {
  const x = Math.min(worldWidth - 102, building.x + building.width + PIER_W + 20);
  const base = walkLine() + 12, top = base - 124;
  contactShadow(ctx, x + 64, base + 1, 30, 2, 0.4);
  slab(ctx, x + 38, base - 5, 55, 5, STREET.kerb);
  for (let i = 0; i < 14; i += 1) {
    const sy = top + 35 + i * 6;
    const sx = x + 64 + Math.round(Math.sin((i / 13) * Math.PI) * 17);
    px(ctx, sx - 1, sy - 1, 11, 8, AMBIENT.shadow);
    px(ctx, sx, sy, 9, 7, FACADE.stone[3]);
    px(ctx, sx, sy, 2, 7, FACADE.stone[4]);
    px(ctx, sx + 7, sy, 2, 7, FACADE.stone[1]);
  }
  slab(ctx, x, top, 93, 43, FACADE.stone);
  px(ctx, x + 3, top + 4, 86, 34, '#0e1a24');
  outlineRect(ctx, x + 4, top + 5, 84, 32, '#2a4a5c');
  drawText(ctx, 'BUCURESTI', x + 17, top + 8, '#8fb0c0', 1, 0);
  drawDigitalTime(ctx, x + 16, top + 18, label);
}

/** The studio's neon sign above the cutaway. */
function drawSignage(ctx, b, time) {
  const label = 'AMN-AI · AUTONOMOUS MACHINE NEXUS';
  const scale = 2;
  const w = textWidth(label, scale, 1);
  const sx = b.x + (b.width - w) / 2;
  const sy = b.y - 26;
  const pulse = 0.78 + Math.sin(time * 1.6) * 0.06 + Math.sin(time * 5.3) * 0.02;
  glow(ctx, b.x + b.width / 2, sy + 8, 150, 'rgba(255,207,122,0.28)', 0.5 * pulse);
  drawText(ctx, label, sx + 1, sy + 1, withAlpha(AMBIENT.shadow, 0.6), scale, 1);
  drawText(ctx, label, sx, sy, FACADE.neon, scale, 1);
  ctx.save();
  ctx.globalAlpha = 0.55 * pulse;
  drawText(ctx, label, sx, sy, FACADE.neonCore, scale, 1);
  ctx.restore();
}

/** Glass lift shaft: steel frame, floor markers from the real zones. */
function drawElevatorShaft(ctx, b, zones) {
  const ex = b.x + (b.elevator_x !== undefined ? b.elevator_x - b.x : b.width - 100);
  const ew = b.elevator_width || 90;
  px(ctx, ex - 1, b.y - 19, ew + 2, b.height + 18, AMBIENT.shadow);
  const g = ctx.createLinearGradient(0, b.y, 0, b.y + b.height);
  g.addColorStop(0, FACADE.glass[2]);
  g.addColorStop(1, FACADE.glass[0]);
  ctx.fillStyle = g;
  ctx.fillRect(ex, b.y - 18, ew, b.height + 16);
  // Sheen and frame.
  ctx.save();
  ctx.globalAlpha = 0.12;
  ctx.fillStyle = FACADE.glass[4];
  ctx.fillRect(ex + 4, b.y - 16, 8, b.height + 12);
  ctx.restore();
  px(ctx, ex, b.y - 18, 3, b.height + 16, FACADE.mullion[3]);
  px(ctx, ex + ew - 3, b.y - 18, 3, b.height + 16, FACADE.mullion[1]);
  px(ctx, ex + 8, b.y - 14, 2, b.height + 8, FACADE.mullion[2]);
  px(ctx, ex + ew - 10, b.y - 14, 2, b.height + 8, FACADE.mullion[2]);
  for (const z of zones) {
    const cy = z.y + z.height - SLAB_H;
    px(ctx, ex, cy, ew, SLAB_H, FACADE.slab[2]);
    px(ctx, ex, cy, ew, 1, FACADE.slab[4]);
    px(ctx, ex, cy + SLAB_H - 1, ew, 1, FACADE.slab[0]);
    const tag = `L${z.floor}`;
    px(ctx, ex + ew - 26, cy - 14, 20, 11, UI.chip);
    drawText(ctx, tag, ex + ew - 22, cy - 12, withAlpha(UI.chipText, 0.75), 1, 1);
  }
  return { ex, ew };
}

function drawElevatorCab(ctx, b, shaft, time, lift) {
  const cy = lift.y;
  const { ex, ew } = shaft;
  const cw = ew - 24;
  const cx = ex + 12;
  // Cable.
  px(ctx, cx + cw / 2 - 1, b.y - 14, 2, cy - b.y + 14, MAT.steel[3]);
  // Cab: steel frame, warm lit interior, glass front.
  px(ctx, cx - 1, cy - 1, cw + 2, 56, AMBIENT.shadow);
  px(ctx, cx, cy, cw, 54, MAT.steel[2]);
  px(ctx, cx, cy, cw, 1, MAT.steel[4]);
  px(ctx, cx + 3, cy + 4, cw - 6, 42, lift.moving ? '#4a3a30' : '#3a2e2c');
  px(ctx, cx + 3, cy + 4, cw - 6, 1, '#ffe6b0');
  ctx.save();
  ctx.globalAlpha = lift.moving ? 0.45 : 0.25;
  px(ctx, cx + 3, cy + 5, cw - 6, 14, '#ffd8a0');
  ctx.restore();
  glow(ctx, cx + cw / 2, cy + 24, 40, 'rgba(255,214,150,0.35)', lift.moving ? 0.9 : 0.5);

  const trip = lift.trip;
  if (trip && trip.phase === 'travel') drawCourier(ctx, cx + cw / 2, cy + 48, time, 0, true);

  const dwelling = Boolean(trip && (trip.phase === 'board' || trip.phase === 'alight'));
  const gap = dwelling ? 8 : 1;
  px(ctx, cx + cw / 2 - gap - 1, cy + 4, 2, 42, MAT.steel[1]);
  px(ctx, cx + cw / 2 + gap - 1, cy + 4, 2, 42, MAT.steel[1]);
  px(ctx, cx + 3, cy + 46, cw - 6, 2, MAT.steel[0]);

  if (lift.moving) {
    const up = lift.target < cy;
    px(ctx, cx + cw / 2 - 2, cy - 5, 4, 4, up ? UI.green : UI.amber);
  } else {
    px(ctx, cx + cw / 2 - 2, cy - 5, 4, 4, MAT.steel[1]);
  }
  const caption = dwelling ? 'DOORS' : lift.moving ? 'MOVING' : 'IDLE';
  const lit = dwelling || lift.moving;
  drawText(ctx, caption, cx + (cw - textWidth(caption, 1, 1)) / 2, cy + 48, lit ? '#8fd8c4' : '#6a7a9a', 1, 1);
}

/* ------------------------------------------------------------- courier */

const COURIER_LOOK = {
  coat: '#3f6b5c',
  coatLight: '#5a8a78',
  trousers: '#25352f',
  skin: '#c8a284',
  hair: '#2f2620',
  crate: '#8a6a3a',
  crateTop: '#d8b06a',
};

/** A runner walking a workflow token to or from the lift. Not an agent; never named. */
function drawCourier(ctx, cx, floorY, time, facing, carrying) {
  const height = 36;
  const y = floorY - height;
  const step = Math.sin(time * 9) * (facing === 0 ? 0 : 1);
  const s = facing < 0 ? -1 : 1;

  contactShadow(ctx, cx, floorY + 1, 8, 1, 0.35);
  px(ctx, cx - 5 + step * 3, y + height * 0.6, 6, height * 0.36, COURIER_LOOK.trousers);
  px(ctx, cx + 1 - step * 3, y + height * 0.6, 6, height * 0.36, mix(COURIER_LOOK.trousers, AMBIENT.shadow, 0.4));
  px(ctx, cx - 6 + step * 3, y + height * 0.95, 8, 3, AMBIENT.shadow);
  px(ctx, cx - step * 3, y + height * 0.95, 8, 3, AMBIENT.shadow);
  px(ctx, cx - 8, y + height * 0.28, 17, height * 0.35, AMBIENT.shadow);
  px(ctx, cx - 7, y + height * 0.29, 15, height * 0.33, COURIER_LOOK.coat);
  px(ctx, cx - 7, y + height * 0.29, 15, 1, COURIER_LOOK.coatLight);
  px(ctx, cx - 8 * s, y + height * 0.31 + step * 2, 3, height * 0.24, COURIER_LOOK.coat);
  px(ctx, cx - 6, y + height * 0.04, 13, 12, AMBIENT.shadow);
  px(ctx, cx - 5, y + height * 0.05, 11, 11, COURIER_LOOK.skin);
  px(ctx, cx - 5, y + height * 0.03, 11, 3, COURIER_LOOK.hair);
  px(ctx, cx - 2 + s, y + height * 0.15, 2, 2, AMBIENT.shadow);
  if (carrying) {
    const bx = cx + s * 9;
    const by = y + height * 0.42;
    px(ctx, cx + s * 5, y + height * 0.34, 4, 3, COURIER_LOOK.skin);
    slab(ctx, bx - 6, by - 6, 12, 12, MAT.oak);
    px(ctx, bx - 6, by - 1, 12, 2, COURIER_LOOK.crateTop);
    px(ctx, bx - 1, by - 6, 2, 12, COURIER_LOOK.crateTop);
  }
}

/* ============================================================================
   Labels: state chip above the head, name card at the desk, speech bubbles, tokens.
   ========================================================================== */

const STATE_COLOR = { work: UI.working, think: UI.thinking, idle: UI.idle, sleep: UI.paused };

/**
 * Runtime-state chip above the head: what the backend last reported, on a dark chip so it
 * stays readable over any wall or window.
 */
function drawStateTag(ctx, cx, headTop, state, mode) {
  const label = String(state || 'IDLE').trim().toUpperCase().slice(0, 12);
  const w = textWidth(label, 1, 1) + 16;
  const h = 11;
  const x = Math.round(cx - w / 2);
  const top = Math.round(headTop) - 18;
  const color = STATE_COLOR[mode] || UI.idle;
  px(ctx, x - 1, top - 1, w + 2, h + 2, AMBIENT.shadow);
  px(ctx, x, top, w, h, UI.chip);
  px(ctx, x, top, w, 1, UI.chipEdge);
  px(ctx, x + 5, top + 4, 3, 3, color);
  if (mode === 'work') px(ctx, x + 4, top + 3, 5, 5, withAlpha(color, 0.35));
  drawText(ctx, label, x + 11, top + 2, UI.chipText, 1, 1);
  // Pointer.
  px(ctx, cx - 1, top + h, 3, 1, UI.chip);
  px(ctx, cx, top + h + 1, 1, 1, UI.chip);
}

/** Name card on the front of the desk. */
function drawNamePlate(ctx, cx, y, name, accent, selected) {
  let label = String(name || '').trim().toUpperCase();
  if (label.length > 16) {
    const cut = label.slice(0, 16);
    const space = cut.lastIndexOf(' ');
    label = (space > 5 ? cut.slice(0, space) : cut).trim();
  }
  const w = textWidth(label, 1, 1) + 20;
  const h = 12;
  const x = Math.round(cx - w / 2);
  const top = Math.round(y);
  px(ctx, x - 1, top - 1, w + 2, h + 2, AMBIENT.shadow);
  px(ctx, x, top, w, h, selected ? UI.selected : UI.paper);
  px(ctx, x, top, w, 1, '#ffffff');
  px(ctx, x, top + h - 1, w, 1, UI.paperShade);
  px(ctx, x + 5, top + 4, 4, 4, accent);
  px(ctx, x + 5, top + 4, 4, 1, mix(accent, '#ffffff', 0.4));
  drawText(ctx, label, x + 13, top + 3, UI.ink, 1, 1);
}

/** Speech bubble raised by a backend agent.message_sent event. */
function drawSpeechBubble(ctx, x, y, text, time) {
  const words = String(text).toUpperCase().split(/\s+/);
  const maxChars = 24;
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
  const by = Math.round(y - h - 12 + Math.sin(time * 1.6) * 1.5);

  px(ctx, bx - 1, by - 1, w + 2, h + 2, AMBIENT.shadow);
  px(ctx, bx, by, w, h, UI.paper);
  px(ctx, bx, by, w, 1, '#ffffff');
  px(ctx, bx, by + h - 1, w, 1, UI.paperShade);
  // Tail.
  px(ctx, bx + w / 2 - 4, by + h, 8, 1, AMBIENT.shadow);
  px(ctx, bx + w / 2 - 3, by + h, 6, 1, UI.paper);
  px(ctx, bx + w / 2 - 3, by + h + 1, 5, 1, AMBIENT.shadow);
  px(ctx, bx + w / 2 - 2, by + h + 1, 3, 1, UI.paper);
  px(ctx, bx + w / 2 - 2, by + h + 2, 3, 1, AMBIENT.shadow);
  px(ctx, bx + w / 2 - 1, by + h + 2, 1, 1, UI.paper);
  px(ctx, bx + w / 2 - 1, by + h + 3, 1, 1, AMBIENT.shadow);
  lines.forEach((l, i) => drawText(ctx, l, bx + 8, by + 7 + i * 10, UI.ink, 1, 1));
}

/** Workflow token: a small parcel that sits at the stage the backend reports. */
function drawProjectToken(ctx, token, time) {
  const bob = Math.sin(time * 2 + token.x * 0.01) * 3;
  const x = Math.round(token.x);
  const y = Math.round(token.y + bob);
  glow(ctx, x, y, 26, 'rgba(255,207,122,0.4)', 0.6);
  slab(ctx, x - 9, y - 9, 18, 18, MAT.oak);
  px(ctx, x - 9, y - 2, 18, 3, MAT.brass[3]);
  px(ctx, x - 2, y - 9, 4, 18, MAT.brass[3]);
  px(ctx, x - 2, y - 2, 4, 3, MAT.brass[4]);
  const label = String(token.stage || '').slice(0, 12);
  const w = textWidth(label, 1, 1);
  px(ctx, x - w / 2 - 5, y + 12, w + 10, 11, AMBIENT.shadow);
  px(ctx, x - w / 2 - 4, y + 13, w + 8, 9, UI.chip);
  drawText(ctx, label, x - w / 2, y + 15, FACADE.neon, 1, 1);
}

function drawWallClock(ctx, x, y, time) {
  const hh = time * 0.05;
  const mm = time * 0.6;
  px(ctx, x + Math.cos(hh) * 2, y + Math.sin(hh) * 2, 2, 2, UI.ink);
  px(ctx, x + Math.cos(mm) * 3, y + Math.sin(mm) * 3, 1, 1, '#c04a3a');
  px(ctx, x, y, 1, 1, UI.ink);
}

/* ============================================================================
   Engine
   ========================================================================== */

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

    // Offscreen buffers: the composed frame and the cached static layers.
    this.world = this._buffer();
    this.wctx = this.world.getContext('2d');
    this.staticLayer = this._buffer();
    this.sctx = this.staticLayer.getContext('2d');
    this.frontLayer = this._buffer();
    this.fctx = this.frontLayer.getContext('2d');
    this.bgLayer = this._buffer();
    this.bgCtx = this.bgLayer.getContext('2d');

    this.live = this._emptyLive();
    this.interiors = new Map();
    this.clock = streetClock();
    const streetSeed = crypto.getRandomValues(new Uint32Array(1))[0];
    this.streetRandom = randomSource(streetSeed);
    this.streetLife = new StreetLife(streetSeed, this.worldW, this.clock);
    // Own the scene's presentation independently of concurrent dashboard markup changes.
    if (!document.getElementById('office-scene-theme')) {
      const theme = document.createElement('link');
      theme.id = 'office-scene-theme';
      theme.rel = 'stylesheet';
      theme.href = new URL('./office_scene.css?no-inline', import.meta.url).href;
      theme.addEventListener('load', () => { if (this.viewport) this.resize(); });
      document.head.append(theme);
    }
    this.clockLabel = this.canvas.parentElement?.querySelector('.street-clock');
    if (!this.clockLabel && this.canvas.parentElement) {
      this.clockLabel = document.createElement('span');
      this.clockLabel.className = 'street-clock';
      this.clockLabel.setAttribute('title', 'Decor fictiv adaptat la ora și ziua din București.');
      this.canvas.parentElement.append(this.clockLabel);
    }
    this._updateClockLabel();
    this.scenery = {
      trees: makeTrees(0x7ee1, this.worldW),
      cars: makeTraffic(streetSeed, this.clock),
      clouds: makeClouds(0x1f77),
      birds: makeBirds(0x60d2),
      dust: Array.from({ length: 40 }, (_, i) => {
        const rnd = mulberry32(0x4411 + i);
        return { x: rnd() * WORLD_W, y: rnd() * WORLD_H, s: 0.2 + rnd() * 0.7, p: rnd() * TAU };
      }),
    };

    /**
     * The lift is parked unless the backend gives it a reason to move: a workflow token
     * arriving at a stage on another floor. With no workflow running, the cab stands still.
     */
    this.lift = { y: 0, target: 0, moving: false, restUntil: 0, parkedFloorY: null, trip: null };
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

  _buffer() {
    const c = document.createElement('canvas');
    c.width = this.worldW;
    c.height = this.worldH;
    return c;
  }

  _emptyLive() {
    return { screens: [], leds: [], lamps: [], fans: [], vuMeters: [], steam: [], bubbles: [], radars: [], clocks: [], onAir: [], ceilingLights: [] };
  }

  /* ------------------------------------------------------------ data in -- */

  setLayout(layout) {
    this.layout = layout;
    if (layout && layout.width && layout.height) {
      const b = layout.building || { y: 60, height: layout.height - 110 };
      setHorizon(b.y + b.height);
      const w = Math.round(layout.width);
      const h = Math.round(HORIZON + STREET_DEPTH);
      if (w !== this.worldW || h !== this.worldH) {
        this.worldW = w;
        this.worldH = h;
        for (const c of [this.world, this.staticLayer, this.frontLayer, this.bgLayer]) {
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
    const toolbar = parent.querySelector('.camera-toolbar');
    this.viewport.bottomInset = ((toolbar?.getBoundingClientRect().height || 0) + 24) * dpr;
    this.viewport.fitToOffice(this.worldW, this.worldH);
    this._backdrop = null;
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
      const place = this._placeFor(agent);
      const ax = place ? place.seatX : agent.x;
      const ay = place ? place.deskTop : agent.y;
      const dx = ax - x;
      const dy = ay - y;
      if (Math.abs(dx) <= 40 && dy >= -60 && dy <= 30) {
        hit = agent;
        break;
      }
    }
    this.selectedAgentId = hit ? hit.id || hit.agent_id : null;
    this.onSelectAgent(hit);
  }

  /** The zone and workstation an agent sits at, from the backend's desk assignment. */
  _placeFor(agent) {
    if (!this.layout) return null;
    const zones = this.layout.zones || [];
    const zone = zones.find((z) => agent.y >= z.y && agent.y <= z.y + z.height && agent.x >= z.x && agent.x <= z.x + z.width)
      || zones.find((z) => agent.y >= z.y && agent.y <= z.y + z.height);
    if (!zone) return null;
    const interior = this.interiors.get(zone.id);
    if (!interior) return null;
    let station = agent.desk_id ? interior.stations.get(agent.desk_id) : null;
    if (!station) {
      const desk = (zone.desks || []).find((d) => d.x === agent.x) || (zone.desks || [])[0];
      if (desk) station = interior.stations.get(desk.id || desk.x);
    }
    if (!station) return null;
    return { zone, station, seatX: station.seatX, deskTop: station.deskTop };
  }

  /* --------------------------------------------------- static rasterising -- */

  _renderStatic() {
    const w = this.worldW;
    const h = this.worldH;
    this.live = this._emptyLive();
    this.interiors = new Map();

    const bg = this.bgCtx;
    bg.clearRect(0, 0, w, h);
    drawSky(bg, w, h, this.clock.daylight);
    drawSkyline(bg, w, this.clock.daylight);

    const ctx = this.sctx;
    ctx.clearRect(0, 0, w, h);
    const front = this.fctx;
    front.clearRect(0, 0, w, h);
    drawGround(ctx, w);

    for (const t of this.scenery.trees) drawTrunk(ctx, t);
    for (const x of LAMP_POSTS) drawLampPost(ctx, x);

    // Bus shelter, bench, bin, hydrant: the street is not just posts.
    const wl = walkLine();
    px(ctx, 175, wl - 45, 98, 6, AMBIENT.shadow);
    px(ctx, 176, wl - 44, 96, 5, STREET.lampPost[2]);
    px(ctx, 176, wl - 44, 96, 1, STREET.lampPost[4]);
    px(ctx, 178, wl - 39, 4, 39, STREET.lampPost[1]);
    px(ctx, 266, wl - 39, 4, 39, STREET.lampPost[1]);
    ctx.save();
    ctx.globalAlpha = 0.18;
    px(ctx, 182, wl - 39, 84, 22, FACADE.glass[4]);
    ctx.restore();
    px(ctx, 184, wl - 20, 80, 4, STREET.lampPost[1]);
    px(ctx, 184, wl - 20, 80, 1, STREET.lampPost[3]);
    px(ctx, 184, wl - 16, 4, 16, STREET.lampPost[0]);
    px(ctx, 260, wl - 16, 4, 16, STREET.lampPost[0]);
    px(ctx, 186, wl - 43, 74, 3, STREET.lampPost[3]);
    drawText(ctx, 'BUS', 208, wl - 38, '#8fb0c0', 1, 1);
    // Bench.
    slab(ctx, 620, wl - 21, 66, 5, MAT.oak);
    slab(ctx, 620, wl - 35, 66, 4, MAT.oak);
    px(ctx, 623, wl - 15, 4, 15, MAT.steel[1]);
    px(ctx, 679, wl - 15, 4, 15, MAT.steel[1]);
    // Bin and hydrant.
    slab(ctx, 706, wl - 24, 14, 24, MAT.steel);
    px(ctx, 704, wl - 27, 18, 3, MAT.steel[3]);
    px(ctx, 979, wl - 21, 11, 21, AMBIENT.shadow);
    px(ctx, 980, wl - 20, 9, 20, '#b04a3c');
    px(ctx, 980, wl - 20, 3, 20, '#d06a58');
    px(ctx, 977, wl - 23, 15, 4, '#c85a48');
    px(ctx, 977, wl - 23, 15, 1, '#e88a78');

    if (!this.layout) {
      this.staticReady = true;
      return;
    }

    const b = this.layout.building || { x: 120, y: 60, width: 960, height: 690 };
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

    drawBuildingShell(ctx, b, zones);
    for (const zone of zones) {
      drawZoneShell(ctx, zone);
      const interior = interiorFor(zone, ctx, this.live, this.clock.daylight);
      fillZone(ctx, zone, this.live, interior);
      bakeRoomLight(ctx, zone);
      this.interiors.set(zone.id, interior);
      // Party walls between departments that share a floor.
      if (!zone.isFloorLead) {
        px(ctx, zone.x - 6, zone.y, 6, zone.height - SLAB_H, FACADE.stone[1]);
        px(ctx, zone.x - 6, zone.y, 1, zone.height - SLAB_H, FACADE.stone[3]);
        px(ctx, zone.x - 1, zone.y, 1, zone.height - SLAB_H, AMBIENT.shadow);
      }
    }
    // Front layer: desks and everything on them, painted over the seated characters.
    for (const zone of zones) {
      drawDeskFronts(front, zone, this.interiors.get(zone.id), this.live);
    }
    // Desk and floor lamps are static: bake their pools into the front layer once.
    for (const lamp of this.live.lamps) glow(front, lamp.x, lamp.y, lamp.r, lamp.color, 1);

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

  _updateClockLabel() {
    if (this.clockLabel) this.clockLabel.textContent = this.clock.text + ' · BUCUREȘTI · STRADĂ DECORATIVĂ';
  }

  _update(dt) {
    this._updateLift(dt);
    if (Math.floor(Date.now() / 60000) !== this.clock.minute) {
      const wasDaylight = this.clock.daylight;
      this.clock = streetClock();
      this._backdrop = null;
      this._updateClockLabel();
      drawSky(this.bgCtx, this.worldW, this.worldH, this.clock.daylight);
      drawSkyline(this.bgCtx, this.worldW, this.clock.daylight);
      // Windows show the sky: repaint the static layers when the light outside changes.
      if (Math.abs(wasDaylight - this.clock.daylight) > 0.05) this._renderStatic();
    }
    this.streetLife.update(dt, this.clock);
    const w = this.worldW;
    for (const car of this.scenery.cars) {
      if (car.visible === undefined) car.visible = this.streetRandom() < this.clock.traffic;
      car.previousX = car.x;
    }
    updateTraffic(this.scenery.cars, this.worldW, dt);
    for (const car of this.scenery.cars) {
      if (Math.abs(car.x - car.previousX) > w / 2) {
        refreshVehicle(car, this.scenery.cars, w, this.streetRandom, this.clock);
      }
    }
    for (const cloud of this.scenery.clouds) {
      cloud.x += cloud.speed * dt;
      if (cloud.x > w + 200) cloud.x = -220;
    }
    for (const bird of this.scenery.birds) {
      bird.x += bird.speed * bird.dir * dt;
      if (bird.x > w + 30 || bird.x < -30) {
        bird.dir = this.streetRandom() < 0.5 ? 1 : -1;
        bird.x = bird.dir > 0 ? -20 : w + 20;
        bird.y = 25 + this.streetRandom() * 250;
        bird.speed = 18 + this.streetRandom() * 35;
      }
    }
  }

  /** Decide whether the lift has a job, then move it. Does nothing without a token trip. */
  _updateLift(dt) {
    if (!this.layout || !this.building) return;
    const zones = this.layout.zones || [];
    const cabTop = (zone) => zone.y + zone.height - 66;
    const floorLineOf = (zone) => zone.y + zone.height - 12;

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
          boardLine: floorLineOf(from),
          exitLine: floorLineOf(zone),
          startX: previous.x,
          x: previous.x,
          exitX: token.x,
          dwell: 0,
        };
        this.lift.target = cabTop(from);
        this.lift.moving = Math.abs(this.lift.y - this.lift.target) > 1;
        this.lift.restUntil = 0;
      }
      this.tokenPlaces.set(token.id, { floor: zone.floor, zoneId: zone.id, x: token.x, y: token.y });
    }

    this._advanceCourier(dt);

    if (!this.lift.moving) {
      const idle = !this.lift.trip;
      if (idle && this.lift.restUntil && this.animTime > this.lift.restUntil && this.lift.homeY !== undefined) {
        this.lift.target = this.lift.homeY;
        this.lift.moving = true;
        this.lift.restUntil = 0;
      }
      return;
    }

    const speed = 90;
    const delta = this.lift.target - this.lift.y;
    const stepSize = speed * dt;
    if (Math.abs(delta) <= stepSize) {
      this.lift.y = this.lift.target;
      this.lift.moving = false;
      if (!this.lift.trip && this.lift.homeY !== undefined && Math.abs(this.lift.y - this.lift.homeY) > 1) {
        this.lift.restUntil = this.animTime + 6;
      }
    } else {
      this.lift.y += Math.sign(delta) * stepSize;
    }
  }

  /** Walk the courier through summon -> board -> travel -> alight. */
  _advanceCourier(dt) {
    const trip = this.lift.trip;
    if (!trip || !this.shaft) return;

    const doorX = this.shaft.ex - 8;
    const insideX = this.shaft.ex + this.shaft.ew / 2;
    const walk = 78 * dt;

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
    trip.dwell += dt;
    const delivered = stepToward(trip.exitX);
    if (delivered && trip.dwell > 0.8) {
      this.lift.trip = null;
      this.lift.restUntil = this.animTime + 4;
    }
  }

  _draw() {
    const ctx = this.wctx;
    const time = this.animTime;
    const w = this.worldW;
    const h = this.worldH;

    ctx.clearRect(0, 0, w, h);

    if (this.staticReady) ctx.drawImage(this.bgLayer, 0, 0);
    for (const cloud of this.scenery.clouds) drawCloud(ctx, cloud);
    if (this.clock.birds) for (const bird of this.scenery.birds) drawBird(ctx, bird, time);
    if (this.staticReady) ctx.drawImage(this.staticLayer, 0, 0);

    ctx.save();
    ctx.globalAlpha = this.clock.daylight * 0.16;
    px(ctx, 0, HORIZON, w, h - HORIZON, '#e3d8aa');
    ctx.restore();

    // --- street -----------------------------------------------------------
    for (const t of this.scenery.trees) drawFoliage(ctx, t, time);
    if (this.clock.daylight < 0.65) for (let i = 0; i < LAMP_POSTS.length; i += 1) drawLampLight(ctx, LAMP_POSTS[i], time, i);
    for (const car of depthSortedTraffic(this.scenery.cars)) drawCar(ctx, car, time, this.clock.daylight);
    for (const wkr of [...this.streetLife.people].sort((a, b) => b.depth - a.depth)) drawWalker(ctx, wkr, time);
    if (this.building) drawStreetClock(ctx, this.building, this.worldW, this.clock.text);

    if (!this.layout) {
      this._blit();
      return;
    }

    const b = this.building;
    const zones = this.layout.zones || [];

    // Zone activity is derived from the agents the backend placed in that zone.
    const activeZones = new Set();
    for (const agent of this.agents) {
      if (modeForAgent(agent) === 'work') {
        const zone = zones.find((z) => agent.y >= z.y && agent.y <= z.y + z.height);
        if (zone) activeZones.add(zone.id);
      }
    }

    // --- people, seated behind their desks ---------------------------------
    const placed = [];
    for (const agent of this.agents) {
      const id = agent.id || agent.agent_id;
      const look = this.looks.get(id) || agentLook(id, agent.role_name);
      const place = this._placeFor(agent);
      const mode = modeForAgent(agent);
      const selected = this.selectedAgentId === id;
      const talking = this.speechBubbles.some((bub) => bub.agentId === id);
      if (place) {
        const body = drawCharacterBody(ctx, place.seatX, place.deskTop, look, mode, time, selected, talking);
        placed.push({ agent, id, look, place, mode, selected, body });
      } else {
        // No desk for this agent in the layout: stand them on the floor of their zone.
        const zone = zones.find((z) => agent.y >= z.y && agent.y <= z.y + z.height);
        const deskTop = zone ? floorLine(zone) - 20 : agent.y;
        const body = drawCharacterBody(ctx, agent.x, deskTop, look, mode, time, selected, talking);
        placed.push({ agent, id, look, place: { seatX: agent.x, deskTop, zone }, mode, selected, body });
      }
    }

    if (this.staticReady) ctx.drawImage(this.frontLayer, 0, 0);

    for (const p of placed) {
      drawCharacterHands(ctx, p.place.seatX, p.place.deskTop, p.look, p.mode, time);
    }

    // --- desk equipment that moves -----------------------------------------
    for (const clock of this.live.clocks) drawWallClock(ctx, clock.x, clock.y, time);
    for (const fan of this.live.fans) {
      ctx.save();
      ctx.translate(fan.x, fan.y);
      ctx.rotate(time * fan.rate);
      ctx.fillStyle = MAT.steel[4];
      for (let bl = 0; bl < 3; bl += 1) {
        ctx.rotate((Math.PI * 2) / 3);
        ctx.fillRect(0, -1, fan.r, 2);
      }
      ctx.restore();
    }
    for (const led of this.live.leds) {
      const on = Math.sin(time * led.rate + led.phase) > -0.1;
      px(ctx, led.x, led.y, 2, 2, on ? led.color : MAT.black[1]);
    }
    for (const scr of this.live.screens) {
      const active = activeZones.has(scr.zoneId);
      drawScreenContent(ctx, scr.kind, scr.mx, scr.my, scr.w, scr.h, time, scr.seed, scr.accent, active);
      ctx.save();
      ctx.globalAlpha = active ? 0.18 : 0.09;
      ctx.globalCompositeOperation = 'lighter';
      ctx.fillStyle = scr.accent;
      ctx.fillRect(scr.mx - 4, scr.my + scr.h + 2, scr.w + 8, 5);
      ctx.restore();
    }
    for (const vu of this.live.vuMeters) {
      const active = activeZones.has(vu.zoneId);
      px(ctx, vu.x - 1, vu.y - 1, vu.w + 2, vu.h + 2, AMBIENT.shadow);
      px(ctx, vu.x, vu.y, vu.w, vu.h, MAT.black[1]);
      for (let i = 0; i < 12; i += 1) {
        const level = active ? (Math.sin(time * 7 + i * 0.6) * 0.5 + 0.5) * (1 - i / 16) : 0.08;
        const bh = Math.max(1, level * (vu.h - 2));
        px(ctx, vu.x + 2 + i * 3, vu.y + vu.h - 1 - bh, 2, bh, i > 8 ? UI.red : i > 5 ? UI.amber : UI.green);
      }
    }
    for (const sign of this.live.onAir) {
      const live = activeZones.has(sign.zoneId);
      px(ctx, sign.x - 1, sign.y - 1, 50, 15, AMBIENT.shadow);
      px(ctx, sign.x, sign.y, 48, 13, live ? '#5a1c1c' : MAT.black[1]);
      px(ctx, sign.x, sign.y, 48, 1, live ? '#8a3a3a' : MAT.black[3]);
      drawText(ctx, 'ON AIR', sign.x + 7, sign.y + 3, live ? '#ffb9a6' : '#4a4a68', 1, 1);
      if (live) glow(ctx, sign.x + 24, sign.y + 6, 40, 'rgba(255,106,90,0.5)', 0.5);
    }
    for (const st of this.live.steam) {
      for (let i = 0; i < 4; i += 1) {
        const t = (time * 0.5 + i * 0.25) % 1;
        ctx.globalAlpha = (1 - t) * 0.5;
        px(ctx, st.x + Math.sin(t * 6 + i) * 3, st.y - t * 22, 3, 3, '#e8e2d8');
      }
      ctx.globalAlpha = 1;
    }
    for (const bub of this.live.bubbles) {
      for (let i = 0; i < 3; i += 1) {
        const t = (time * 0.4 + i * 0.33) % 1;
        ctx.globalAlpha = 0.6 - t * 0.4;
        px(ctx, bub.x + Math.sin(t * 8 + i) * 2, bub.y - t * 14, 2, 2, '#cdeaf4');
      }
      ctx.globalAlpha = 1;
    }
    for (const radar of this.live.radars) {
      ctx.save();
      ctx.beginPath();
      ctx.rect(radar.mx, radar.my, radar.w, radar.h);
      ctx.clip();
      px(ctx, radar.mx, radar.my, radar.w, radar.h, '#0c1a14');
      const rx = radar.mx + radar.w / 2;
      const ry = radar.my + radar.h / 2;
      const r = Math.min(radar.w, radar.h) / 2 - 1;
      ctx.strokeStyle = '#1e4a3a';
      for (let rr = 3; rr <= r; rr += 3) {
        ctx.beginPath();
        ctx.arc(rx, ry, rr, 0, TAU);
        ctx.stroke();
      }
      const a = time * 1.5;
      ctx.strokeStyle = UI.green;
      ctx.beginPath();
      ctx.moveTo(rx, ry);
      ctx.lineTo(rx + Math.cos(a) * r, ry + Math.sin(a) * r);
      ctx.stroke();
      ctx.restore();
    }

    drawElevatorCab(ctx, b, this.shaft, time, this.lift);
    drawRoofDetails(ctx, b, time);
    drawSignage(ctx, b, time);

    // --- labels ------------------------------------------------------------
    for (const p of placed) {
      const zone = p.place.zone || zones.find((z) => p.agent.y >= z.y && p.agent.y <= z.y + z.height);
      const dept = department(zone ? zone.zone_type : 'DEFAULT');
      const hairTop = p.body.headY - 6;
      drawStateMark(ctx, p.place.seatX, hairTop, p.mode, time);
      drawStateTag(ctx, p.place.seatX, hairTop, p.mode === 'sleep' ? 'PAUSED' : String(p.agent.runtime_state || 'IDLE'), p.mode);
      drawNamePlate(
        ctx,
        p.place.seatX,
        p.place.deskTop + 11,
        p.agent.display_name || p.agent.name || p.agent.role_name || 'AGENT',
        dept.accent,
        p.selected,
      );
    }

    // --- workflow tokens and speech ---------------------------------------
    const inTransit = this.lift.trip ? this.lift.trip.tokenId : null;
    for (const token of this.projectTokens) {
      if (token.id === inTransit) continue;
      drawProjectToken(ctx, token, time);
    }
    const trip = this.lift.trip;
    if (trip && trip.phase !== 'travel') {
      const onOrigin = trip.phase === 'summon' || trip.phase === 'board';
      const line = onOrigin ? trip.boardLine : trip.exitLine;
      const target = onOrigin ? this.shaft.ex - 8 : trip.exitX;
      const facing = Math.abs(target - trip.x) < 0.5 ? 0 : Math.sign(target - trip.x);
      drawCourier(ctx, Math.round(trip.x), line, time, facing, true);
    }
    for (const bubble of this.speechBubbles) {
      const p = placed.find((q) => q.id === bubble.agentId);
      const x = p ? p.place.seatX : bubble.x;
      const y = p ? p.body.headY - 22 : bubble.y;
      drawSpeechBubble(ctx, x, y, bubble.text, time);
    }

    // --- atmosphere --------------------------------------------------------
    ctx.save();
    for (const d of this.scenery.dust) {
      const dx = d.x + Math.sin(time * 0.35 + d.p) * 14;
      const dy = (d.y + time * 5 * d.s) % h;
      ctx.globalAlpha = 0.1 * d.s;
      px(ctx, dx, dy, 1, 1, '#d8e4f0');
    }
    ctx.restore();

    const vig = ctx.createRadialGradient(w / 2, h / 2, h * 0.4, w / 2, h / 2, h * 0.9);
    vig.addColorStop(0, 'rgba(0,0,0,0)');
    vig.addColorStop(1, 'rgba(8,8,20,0.32)');
    ctx.fillStyle = vig;
    ctx.fillRect(0, 0, w, h);

    this._blit();
  }

  /** Scale the world buffer onto the visible canvas without smoothing the pixels. */
  _blit() {
    const ctx = this.ctx;
    ctx.imageSmoothingEnabled = false;
    if (!this._backdrop || this._backdropH !== this.canvas.height) {
      const g = ctx.createLinearGradient(0, 0, 0, this.canvas.height);
      g.addColorStop(0, mixColor(SKY.zenith, SKY.dayZenith, this.clock.daylight));
      g.addColorStop(0.6, '#0b1020');
      g.addColorStop(1, STREET.pavement[0]);
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
