/**
 * Office rooms — the cutaway floors: walls, slabs, light, furniture and the fittings that
 * make each department recognisable.
 *
 * Everything drawn here is static architecture and is rasterised once into the cached
 * scene layer. Anything that moves (screens, LEDs, steam, meters) is not drawn: it is
 * described in the `live` list the engine paints every frame. Geometry comes from the
 * backend layout (zone boxes and desk positions); nothing here invents a desk or a person.
 *
 * Light model: one warm ceiling light per bay. Walls are brightest just under the ceiling
 * and fall off towards the floor; every object has its lit face on top, its shadow face at
 * the bottom, and a contact shadow where it meets the floor.
 */

import { department, MAT, FACADE, UI, AMBIENT, SKY, CITY, rgba, withAlpha, mix } from './office_palette.js';
import { glow, contactShadow, cachedSprite, PixelGrid, drawSprite } from './pixel_sprites.js';
import { drawChair, characterMetrics } from './office_characters.js';
import { drawText, textWidth } from './pixel_font.js';
import { atlas, propReady, drawProp, propPoint, tileProp } from './office_atlas.js';

const TAU = Math.PI * 2;

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
const pick = (list, rnd) => list[Math.floor(rnd() * list.length) % list.length];

/* ------------------------------------------------------------------- atlas */

/**
 * Floors drawn from the Blender sprite atlas (art-source/blender). Empty on purpose: the
 * Owner compared the atlas RESEARCH floor with the hand-drawn floors on 2026-09-11 and judged
 * the hand-drawn rooms and furniture the better art, so every floor draws the procedural art
 * below. The pipeline and its assets stay in the repository; adding a zone type here turns the
 * atlas back on for that floor.
 */
export const ATLAS_ZONES = new Set();

export function usesAtlas(zone) {
  return atlas.ready && ATLAS_ZONES.has(zone.zone_type);
}

/**
 * Floors whose *people* come from the Blender character parts. Empty on purpose: the Owner
 * judged the rendered characters a regression against the hand-drawn sprites (boxier heads,
 * hair reading as a cap), so every floor draws the hand-drawn characters while the atlas
 * still supplies rooms and furniture. Add a zone type here to compare again.
 */
export const ATLAS_CHARACTER_ZONES = new Set();

export function usesAtlasCharacters(zone) {
  return atlas.ready && ATLAS_CHARACTER_ZONES.has(zone.zone_type);
}

/** A floor-standing atlas prop with a contact shadow, anchored at (x, floorY). */
function placeProp(ctx, name, x, floorY) {
  const e = atlas.props[name];
  if (!e) return null;
  contactShadow(ctx, x - e.anchor.x + e.w / 2, floorY + 2, e.w / 2 + 1, 2, 0.4);
  return drawProp(ctx, name, x, floorY);
}

/* --------------------------------------------------------------- primitives */

export function px(ctx, x, y, w, h, color) {
  ctx.fillStyle = color;
  ctx.fillRect(Math.round(x), Math.round(y), Math.max(1, Math.round(w)), Math.max(1, Math.round(h)));
}

/**
 * A bevelled block from a ramp: base fill, lit top edge, lit left edge, shadow bottom and
 * right edges, dark outline. The signature shape of everything solid in the scene.
 */
export function slab(ctx, x, y, w, h, ramp, { outline = true, lit = true } = {}) {
  x = Math.round(x); y = Math.round(y); w = Math.round(w); h = Math.round(h);
  if (outline) px(ctx, x - 1, y - 1, w + 2, h + 2, AMBIENT.shadow);
  px(ctx, x, y, w, h, ramp[2]);
  if (lit) {
    px(ctx, x, y, w, 1, ramp[4]);
    px(ctx, x, y, 1, h, ramp[3]);
  }
  px(ctx, x, y + h - 1, w, 1, ramp[0]);
  px(ctx, x + w - 1, y, 1, h, ramp[1]);
}

export function outlineRect(ctx, x, y, w, h, color) {
  px(ctx, x, y, w, 1, color);
  px(ctx, x, y + h - 1, w, 1, color);
  px(ctx, x, y, 1, h, color);
  px(ctx, x + w - 1, y, 1, h, color);
}

/** Vertical gradient band, drawn as pixel rows so it stays crisp. */
function vband(ctx, x, y, w, h, top, bottom, steps = 6) {
  const rows = Math.max(1, Math.round(h / steps));
  for (let i = 0; i < steps; i += 1) {
    const t = i / Math.max(1, steps - 1);
    px(ctx, x, y + i * rows, w, i === steps - 1 ? h - i * rows : rows, mix(top, bottom, t));
  }
}

/* ============================================================================
   Room shell
   ========================================================================== */

export const SLAB_H = 12;        // floor slab thickness the backend's zone box includes
export const FLOOR_SURFACE = 7;  // visible floor surface depth (top of the slab)
export const PREMIUM_FLOOR_SURFACE = 10;  // atlas floors show a deeper 3/4 floor plane
export const CEILING_H = 7;      // ceiling band at the top of each zone

export function floorLine(zone) {
  return zone.y + zone.height - SLAB_H;
}

/** Ceiling light fixture positions for a zone. */
export function fixtures(zone) {
  const list = [];
  const step = 118;
  const count = Math.max(1, Math.round((zone.width - 40) / step));
  for (let i = 0; i < count; i += 1) {
    list.push(Math.round(zone.x + (zone.width * (i + 0.5)) / count));
  }
  return list;
}

export function drawZoneShell(ctx, zone) {
  const dept = department(zone.zone_type);
  const { x, y, width: w, height: h } = zone;
  const floorY = floorLine(zone);
  const rnd = mulberry32(hash32(zone.id));
  const wallTop = y + CEILING_H;
  const wallH = floorY - wallTop;

  // Back wall: lit under the ceiling, falling into shadow at the floor.
  vband(ctx, x, wallTop, w, wallH, dept.wall[3], dept.wall[1], 14);
  const wallTile = `wall_${zone.zone_type}_h${wallH}`;
  if (usesAtlas(zone) && propReady(wallTile)) {
    // Plaster speckle from the procedural finish, then the moulded wainscot and rails.
    for (let i = 0; i < w * wallH * 0.004; i += 1) {
      px(ctx, x + rnd() * w, wallTop + 4 + rnd() * (wallH - 8), 1, 1, withAlpha(AMBIENT.light, 0.04));
    }
    tileProp(ctx, wallTile, x, x + w, floorY);
  } else {
    drawWallFinish(ctx, zone, dept, wallTop, wallH, rnd);
  }

  // Ambient occlusion where the wall meets the ceiling and the floor.
  px(ctx, x, wallTop, w, 1, withAlpha(AMBIENT.shadow, 0.55));
  px(ctx, x, wallTop + 1, w, 1, withAlpha(AMBIENT.shadow, 0.25));
  px(ctx, x, floorY - 3, w, 3, withAlpha(AMBIENT.shadow, 0.22));
  px(ctx, x, floorY - 1, w, 1, withAlpha(AMBIENT.shadow, 0.45));
  // Side walls in shadow at the cutaway edges.
  px(ctx, x, wallTop, 3, wallH, withAlpha(AMBIENT.shadow, 0.35));
  px(ctx, x + w - 3, wallTop, 3, wallH, withAlpha(AMBIENT.shadow, 0.35));

  // Ceiling: a dark band with a lit rim, and the recessed fixtures.
  px(ctx, x, y, w, CEILING_H, FACADE.roof[1]);
  px(ctx, x, y + CEILING_H - 1, w, 1, FACADE.roof[3]);
  px(ctx, x, y, w, 1, AMBIENT.shadow);
  for (const fx of fixtures(zone)) {
    px(ctx, fx - 13, y + 3, 26, 4, MAT.steel[1]);
    px(ctx, fx - 12, y + 6, 24, 2, '#fff6dc');
    px(ctx, fx - 10, y + 7, 20, 1, dept.lamp);
  }

  // Tall street-level volumes show their services: ducting, a pipe run, pendant drops.
  if (h >= 180) drawTallVolume(ctx, zone, wallTop, rnd);

  // Skirting board where a finished wall meets the floor (not in the server room or the booth).
  if (dept.wallStyle === 'plaster' || dept.wallStyle === 'panelled' || dept.wallStyle === 'brick') {
    px(ctx, x, floorY - 4, w, 4, dept.trim[2]);
    px(ctx, x, floorY - 4, w, 1, dept.trim[4]);
    px(ctx, x, floorY - 1, w, 1, dept.trim[0]);
    px(ctx, x, floorY - 5, w, 1, withAlpha(AMBIENT.shadow, 0.35));
  }

  // Floor slab: surface pattern on top, concrete edge below.
  drawFloor(ctx, zone, dept, floorY, rnd);

  // Department sign on the wall (the shopfront carries its own).
  if (zone.zone_type !== 'SHOP') drawWallSign(ctx, zone, dept);
}

function drawWallFinish(ctx, zone, dept, wallTop, wallH, rnd) {
  const { x, width: w } = zone;
  const floorY = wallTop + wallH;
  const dado = floorY - 25;

  switch (dept.wallStyle) {
    case 'panelled': {
      // Timber wall panels with a rail; each panel has a lit left edge and a shadow right.
      const panelW = 40;
      for (let px0 = x + 4; px0 < x + w - 4; px0 += panelW) {
        const pw = Math.min(panelW, x + w - 4 - px0);
        px(ctx, px0, wallTop + 3, 1, wallH - 3, withAlpha(AMBIENT.light, 0.06));
        px(ctx, px0 + pw - 1, wallTop + 3, 1, wallH - 3, withAlpha(AMBIENT.shadow, 0.3));
      }
      px(ctx, x, dado, w, 2, dept.trim[3]);
      px(ctx, x, dado + 2, w, 1, dept.trim[0]);
      vband(ctx, x, dado + 3, w, floorY - dado - 3, dept.wall[2], dept.wall[0], 3);
      for (let px0 = x + 4; px0 < x + w - 4; px0 += 20) {
        px(ctx, px0, dado + 6, 1, floorY - dado - 10, withAlpha(AMBIENT.shadow, 0.35));
        px(ctx, px0 + 1, dado + 6, 1, floorY - dado - 10, withAlpha(AMBIENT.light, 0.05));
      }
      break;
    }
    case 'plaster': {
      // Smooth plaster with a picture rail and a painted dado in the darker wall tone.
      for (let i = 0; i < w * wallH * 0.004; i += 1) {
        px(ctx, x + rnd() * w, wallTop + 4 + rnd() * (wallH - 8), 1, 1, withAlpha(AMBIENT.light, 0.04));
      }
      px(ctx, x, wallTop + 14, w, 1, withAlpha(dept.trim[4], 0.35));
      px(ctx, x, dado, w, 2, dept.trim[3]);
      px(ctx, x, dado + 2, w, 1, dept.trim[0]);
      vband(ctx, x, dado + 3, w, floorY - dado - 3, dept.wall[1], dept.wall[0], 3);
      break;
    }
    case 'foam': {
      // Acoustic foam wedges across the whole wall, staggered.
      for (let fy = wallTop + 4; fy < floorY - 6; fy += 8) {
        for (let fx = x + 4 + ((fy / 8) % 2) * 4; fx < x + w - 6; fx += 8) {
          const t = rnd();
          px(ctx, fx, fy, 7, 7, t > 0.5 ? MAT.foam[2] : MAT.foam[1]);
          px(ctx, fx, fy, 7, 1, MAT.foam[3]);
          px(ctx, fx, fy, 1, 7, MAT.foam[3]);
          px(ctx, fx + 3, fy + 3, 1, 1, MAT.foam[4]);
          px(ctx, fx + 6, fy, 1, 7, MAT.foam[0]);
          px(ctx, fx, fy + 6, 7, 1, MAT.foam[0]);
        }
      }
      break;
    }
    case 'brick': {
      // Exposed brick in warm courses with pale mortar.
      for (let by = wallTop + 4, row = 0; by < floorY - 2; by += 6, row += 1) {
        for (let bx = x + 2 - (row % 2) * 8; bx < x + w - 2; bx += 16) {
          const bw = Math.min(15, x + w - 2 - bx);
          if (bw <= 0) continue;
          const tone = rnd();
          px(ctx, Math.max(x + 2, bx), by, bw - (bx < x + 2 ? x + 2 - bx : 0), 5, tone > 0.7 ? dept.wall[3] : tone > 0.3 ? dept.wall[2] : dept.wall[1]);
          px(ctx, Math.max(x + 2, bx), by, bw - (bx < x + 2 ? x + 2 - bx : 0), 1, withAlpha(AMBIENT.light, 0.08));
        }
      }
      break;
    }
    case 'steel': {
      // Server-room cladding: metal panels with rivets and a cable tray under the ceiling.
      for (let px0 = x + 2; px0 < x + w - 2; px0 += 48) {
        px(ctx, px0, wallTop + 3, 1, wallH - 3, MAT.steel[3]);
        px(ctx, px0 + 1, wallTop + 3, 1, wallH - 3, MAT.steel[0]);
        for (let ry = wallTop + 8; ry < floorY - 6; ry += 16) px(ctx, px0 + 4, ry, 2, 2, MAT.steel[4]);
      }
      px(ctx, x + 4, wallTop + 6, w - 8, 6, MAT.steel[1]);
      px(ctx, x + 4, wallTop + 6, w - 8, 1, MAT.steel[3]);
      for (let cx = x + 10; cx < x + w - 10; cx += 14) px(ctx, cx, wallTop + 8, 1, 3, pick(['#5c8a7a', '#8a6a4a', '#5a6a9a'], rnd));
      break;
    }
    default:
      break;
  }
}

function drawFloor(ctx, zone, dept, floorY, rnd) {
  const { x, width: w } = zone;
  const f = dept.floor;
  const bottom = zone.y + zone.height;
  const floorTile = `floor_${zone.zone_type}`;
  if (usesAtlas(zone) && propReady(floorTile)) {
    // 3/4 floor strip from the atlas, then the remaining slab edge in concrete.
    const surface = PREMIUM_FLOOR_SURFACE;
    tileProp(ctx, floorTile, x, x + w, floorY);
    const edgeTop = floorY + surface + 2;
    px(ctx, x, edgeTop, w, bottom - edgeTop, FACADE.slab[2]);
    px(ctx, x, bottom - 1, w, 1, FACADE.slab[0]);
    return;
  }
  // Surface (seen from a little above), then the slab's front edge.
  px(ctx, x, floorY, w, FLOOR_SURFACE, f[2]);
  px(ctx, x, floorY, w, 1, f[4]);
  switch (dept.floorStyle) {
    case 'planks':
      for (let py = floorY + 1; py < floorY + FLOOR_SURFACE; py += 3) px(ctx, x, py, w, 1, f[1]);
      for (let sx = x + 8 + Math.floor(rnd() * 20); sx < x + w; sx += 28 + Math.floor(rnd() * 24)) {
        px(ctx, sx, floorY + 1 + (Math.floor(rnd() * 2)) * 3, 1, 2, f[0]);
      }
      break;
    case 'herringbone':
      for (let sx = x; sx < x + w; sx += 6) {
        px(ctx, sx, floorY + 1, 3, 3, f[3]);
        px(ctx, sx + 3, floorY + 4, 3, 3, f[1]);
      }
      break;
    case 'tiles':
      for (let sx = x; sx < x + w; sx += 14) px(ctx, sx, floorY + 1, 1, FLOOR_SURFACE - 1, f[1]);
      px(ctx, x, floorY + 4, w, 1, f[1]);
      for (let sx = x + 2; sx < x + w; sx += 14) px(ctx, sx, floorY + 1, 11, 1, f[3]);
      break;
    case 'raised':
      for (let sx = x; sx < x + w; sx += 24) {
        px(ctx, sx, floorY + 1, 1, FLOOR_SURFACE - 1, f[1]);
        px(ctx, sx + 2, floorY + 1, 20, 1, f[3]);
      }
      break;
    case 'checker':
      for (let sx = x, i = 0; sx < x + w; sx += 8, i += 1) px(ctx, sx, floorY + 1, 8, FLOOR_SURFACE - 1, i % 2 ? f[3] : f[1]);
      break;
    case 'carpet':
      for (let i = 0; i < w * 0.3; i += 1) px(ctx, x + rnd() * w, floorY + 1 + rnd() * (FLOOR_SURFACE - 1), 1, 1, f[3]);
      break;
    case 'rubber':
      for (let sx = x + 2; sx < x + w; sx += 4) px(ctx, sx, floorY + 3, 1, 1, f[3]);
      break;
    default:
      px(ctx, x, floorY + 3, w, 1, f[1]);
      break;
  }
  px(ctx, x, floorY + FLOOR_SURFACE - 1, w, 1, f[0]);
  // Slab edge: concrete with a lit lip and a shadow underside.
  px(ctx, x, floorY + FLOOR_SURFACE, w, bottom - floorY - FLOOR_SURFACE, FACADE.slab[2]);
  px(ctx, x, floorY + FLOOR_SURFACE, w, 1, FACADE.slab[4]);
  px(ctx, x, bottom - 1, w, 1, FACADE.slab[0]);
}

function drawTallVolume(ctx, zone, wallTop, rnd) {
  const { x, width: w } = zone;
  // Duct run with hanger straps.
  px(ctx, x + 4, wallTop + 22, w - 8, 12, AMBIENT.shadow);
  px(ctx, x + 5, wallTop + 23, w - 10, 10, MAT.steel[2]);
  px(ctx, x + 5, wallTop + 23, w - 10, 2, MAT.steel[4]);
  px(ctx, x + 5, wallTop + 31, w - 10, 2, MAT.steel[0]);
  for (let hx = x + 16; hx < x + w - 12; hx += 36) {
    px(ctx, hx, wallTop, 2, 23, MAT.steel[1]);
    px(ctx, hx + 8, wallTop + 26, 10, 4, MAT.steel[1]);
  }
  // A pipe below the duct with valves.
  px(ctx, x + 5, wallTop + 38, w - 10, 3, MAT.terracotta[1]);
  px(ctx, x + 5, wallTop + 38, w - 10, 1, MAT.terracotta[3]);
  for (let vx = x + 30 + Math.floor(rnd() * 20); vx < x + w - 20; vx += 70) {
    px(ctx, vx, wallTop + 36, 5, 7, MAT.terracotta[0]);
    px(ctx, vx + 1, wallTop + 34, 3, 2, MAT.brass[3]);
  }
  // Pendant lamps dropping into the volume.
  const lamps = Math.max(1, Math.round(w / 110));
  for (let i = 0; i < lamps; i += 1) {
    const lx = Math.round(x + (w * (i + 0.5)) / lamps);
    px(ctx, lx, wallTop + 41, 1, 22, MAT.black[3]);
    px(ctx, lx - 8, wallTop + 63, 17, 6, AMBIENT.shadow);
    px(ctx, lx - 7, wallTop + 63, 15, 5, MAT.black[2]);
    px(ctx, lx - 7, wallTop + 63, 15, 1, MAT.black[4]);
    px(ctx, lx - 5, wallTop + 68, 11, 1, '#fff0c8');
  }
}

function drawWallSign(ctx, zone, dept) {
  const label = dept.name;
  const w = textWidth(label, 1, 1) + 14;
  const x = zone.x + 12;
  const y = zone.y + CEILING_H + 6;
  px(ctx, x - 1, y - 1, w + 2, 13, AMBIENT.shadow);
  px(ctx, x, y, w, 11, UI.chip);
  px(ctx, x, y, w, 1, UI.chipEdge);
  px(ctx, x + 4, y + 3, 3, 5, dept.accent);
  drawText(ctx, label, x + 10, y + 3, UI.chipText, 1, 1);
  if (zone.isFloorLead && zone.width >= 300) {
    const fl = `LEVEL ${zone.floor}`;
    const fw = textWidth(fl, 1, 1) + 12;
    const right = zone.floorRight !== undefined ? zone.floorRight : zone.x + zone.width;
    const fx = right - fw - 48;
    px(ctx, fx - 1, y - 1, fw + 2, 13, AMBIENT.shadow);
    px(ctx, fx, y, fw, 11, UI.chip);
    px(ctx, fx, y, fw, 1, UI.chipEdge);
    drawText(ctx, fl, fx + 6, y + 3, withAlpha(UI.chipText, 0.7), 1, 1);
  }
}

/** Light baked into the static layer: a soft cone from each fixture and a pool on the floor. */
export function bakeRoomLight(ctx, zone, daylight = 0) {
  const dept = department(zone.zone_type);
  const floorY = floorLine(zone);
  const top = zone.y + CEILING_H;
  // By day the fixtures only fill in what the windows light; at night they carry the room.
  const dim = 1 - daylight * 0.55;
  if (zone.height >= 180) {
    const lamps = Math.max(1, Math.round(zone.width / 110));
    for (let i = 0; i < lamps; i += 1) {
      const lx = Math.round(zone.x + (zone.width * (i + 0.5)) / lamps);
      glow(ctx, lx, top + 70, 58, rgba(dept.lamp, 0.34), dim);
    }
  }
  for (const fx of fixtures(zone)) {
    const cone = ctx.createLinearGradient(0, top, 0, floorY);
    cone.addColorStop(0, rgba(dept.lamp, 0.16 * dim));
    cone.addColorStop(0.5, rgba(dept.lamp, 0.05 * dim));
    cone.addColorStop(1, rgba(dept.lamp, 0.0));
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.fillStyle = cone;
    ctx.beginPath();
    ctx.moveTo(fx - 14, top);
    ctx.lineTo(fx + 14, top);
    ctx.lineTo(fx + 62, floorY + 2);
    ctx.lineTo(fx - 62, floorY + 2);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
    glow(ctx, fx, top + 2, 30, rgba('#fff3d0', 0.45), 0.9 * dim);
    // Pool on the floor surface.
    ctx.save();
    ctx.globalCompositeOperation = 'lighter';
    ctx.globalAlpha = 0.16 * dim;
    ctx.fillStyle = dept.lamp;
    ctx.beginPath();
    ctx.ellipse(fx, floorY + 3, 46, 4, 0, 0, TAU);
    ctx.fill();
    ctx.restore();
  }
}

/** Light from a window falling down the wall onto the floor: warm by day, cool blue at night. */
function drawWindowSpill(ctx, x, y, w, h, daylight, floorY) {
  const color = daylight > 0.5 ? '#ffe9b4' : '#8fb8e0';
  const strength = 0.05 + daylight * 0.09;
  ctx.save();
  ctx.globalCompositeOperation = 'lighter';
  const g = ctx.createLinearGradient(0, y + h, 0, floorY + FLOOR_SURFACE);
  g.addColorStop(0, rgba(color, strength));
  g.addColorStop(1, rgba(color, strength * 0.35));
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.moveTo(x, y + h);
  ctx.lineTo(x + w, y + h);
  ctx.lineTo(x + w + 12, floorY + FLOOR_SURFACE);
  ctx.lineTo(x - 12, floorY + FLOOR_SURFACE);
  ctx.closePath();
  ctx.fill();
  ctx.globalAlpha = strength * 1.6;
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.ellipse(x + w / 2, floorY + 3, w / 2 + 10, 3, 0, 0, TAU);
  ctx.fill();
  ctx.restore();
}

/**
 * The view through a window. With a backdrop (the scene's own sky-and-skyline layer) the
 * window is a hole: it shows exactly what stands behind the building at these world
 * coordinates, so a penthouse looks out on sky and tower tops and a low floor on the roofs
 * and lit windows across the street. Without a backdrop (the standalone room preview) a
 * plausible view is drawn, with towers shrinking on higher floors.
 */
export function drawWindowView(ctx, gx, gy, gw, gh, daylight = 0, backdrop = null, floor = 0) {
  if (backdrop) {
    ctx.drawImage(backdrop, gx, gy, gw, gh, gx, gy, gw, gh);
    // Glazing: a faint cool tint and reflection of the room light so the hole reads as glass.
    ctx.save();
    ctx.globalAlpha = 0.08;
    ctx.fillStyle = mix(SKY.upper, '#ffffff', 0.6);
    ctx.fillRect(gx, gy, gw, gh);
    ctx.restore();
    return;
  }
  const towerScale = Math.max(0.12, 1 - floor * 0.24);
  const g = ctx.createLinearGradient(0, gy, 0, gy + gh);
  g.addColorStop(0, mix(SKY.upper, SKY.dayUpper, daylight));
  g.addColorStop(1, mix(SKY.dusk, SKY.dayBand, daylight));
  ctx.fillStyle = g;
  ctx.fillRect(gx, gy, gw, gh);
  const rnd = mulberry32(hash32(`win${gx}${gy}`));
  let tx = gx;
  while (tx < gx + gw) {
    const tw = 5 + Math.floor(rnd() * 8);
    const th = Math.max(2, Math.floor((6 + rnd() * (gh * 0.5)) * towerScale));
    px(ctx, tx, gy + gh - th, Math.min(tw, gx + gw - tx), th, CITY.mid);
    for (let wy = gy + gh - th + 2; wy < gy + gh - 2; wy += 3) {
      if (rnd() > 0.55) px(ctx, tx + 1 + Math.floor(rnd() * Math.max(1, tw - 3)), wy, 1, 1, rnd() > 0.5 ? CITY.windowWarm : CITY.windowCool);
    }
    tx += tw + 1;
  }
}

/** A window punched through the back wall, showing the night outside. */
export function drawWindow(ctx, x, y, w, h, daylight = 0, premium = false, floorY = null, view = null) {
  if (floorY !== null) drawWindowSpill(ctx, x, y, w, h, daylight, floorY);
  const backdrop = view ? view.backdrop : null;
  const floor = view ? view.floor : 0;
  const spriteName = `window_${w}x${h}`;
  if (premium && propReady(spriteName)) {
    drawWindowView(ctx, x, y, w, h, daylight, backdrop, floor);
    drawProp(ctx, spriteName, x, y);
    return;
  }
  px(ctx, x - 2, y - 2, w + 4, h + 4, AMBIENT.shadow);
  px(ctx, x - 1, y - 1, w + 2, h + 2, FACADE.mullion[3]);
  px(ctx, x, y, w, h, FACADE.mullion[1]);
  const gx = x + 1, gy = y + 1, gw = w - 2, gh = h - 2;
  drawWindowView(ctx, gx, gy, gw, gh, daylight, backdrop, floor);
  // Mullions and a glass sheen.
  px(ctx, x + Math.floor(w / 2) - 1, y, 2, h, FACADE.mullion[2]);
  px(ctx, x, y + Math.floor(h / 2), w, 1, FACADE.mullion[2]);
  ctx.save();
  ctx.globalAlpha = 0.14;
  ctx.fillStyle = '#ffffff';
  ctx.beginPath();
  ctx.moveTo(gx, gy);
  ctx.lineTo(gx + gw * 0.45, gy);
  ctx.lineTo(gx, gy + gh * 0.7);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
  // Sill.
  px(ctx, x - 3, y + h + 2, w + 6, 2, FACADE.mullion[4]);
  px(ctx, x - 3, y + h + 4, w + 6, 1, AMBIENT.shadow);
}

/* ============================================================================
   Furniture
   ========================================================================== */

/**
 * A workstation at desk x, drawn in two passes so the seated character can sit behind it:
 *   desk.back(): the chair (call before the character)
 *   desk.front(): the desk itself, keyboard and clutter (call after the character)
 * Returns the geometry the engine needs to place screens and hands.
 */
export function workstation(zone, dept, deskX, variant = 0, premium = false) {
  const floorY = floorLine(zone);
  const deskTop = floorY - 24;
  const w = 76;
  const x = deskX - w / 2;
  const wood = variant % 2 === 0 ? MAT.walnut : MAT.oak;
  const seatX = deskX + 8;
  const propName = `workstation_${variant % 2 === 0 ? 'walnut' : 'oak'}`;
  if (premium && propReady(propName) && propReady(`${propName}_back`)) {
    // Sprite workstation: same desk plane and seat, so characters and hit-tests are unchanged.
    const screen = propPoint(propName, 'screen', deskX, floorY);
    const lamp = propPoint(propName, 'lamp', deskX, floorY);
    return {
      deskTop,
      seatX,
      monitorX: x + 4,
      premium: true,
      screen: screen ? { mx: screen.x, my: screen.y, w: screen.w, h: screen.h } : null,
      lamp,
      back(ctx) {
        drawProp(ctx, `${propName}_back`, deskX, floorY);
      },
      front(ctx) {
        contactShadow(ctx, deskX, floorY + 4, w / 2 + 4, 2, 0.45);
        drawProp(ctx, propName, deskX, floorY);
      },
    };
  }
  return {
    deskTop,
    seatX,
    monitorX: x + 4,
    back(ctx) {
      drawChair(ctx, seatX, deskTop, dept.trim, MAT.fabricBlue);
    },
    front(ctx) {
      // Contact shadow on the floor plane under the whole desk.
      contactShadow(ctx, deskX, floorY + 4, w / 2 + 4, 2, 0.45);
      // Legs: slim steel frame standing on the floor surface, with feet.
      const legH = floorY + 3 - (deskTop + 9);
      for (const lx of [x + 4, x + w - 7]) {
        px(ctx, lx - 1, deskTop + 9, 5, legH + 1, AMBIENT.shadow);
        px(ctx, lx, deskTop + 9, 3, legH, MAT.steel[1]);
        px(ctx, lx, deskTop + 9, 1, legH, MAT.steel[3]);
        px(ctx, lx - 1, floorY + 2, 5, 1, MAT.steel[0]);
      }
      // Drawer pedestal down to the floor, with a shadow gap under the top.
      const drawerX = variant % 2 === 0 ? x + w - 30 : x + 8;
      const pedH = floorY + 2 - (deskTop + 10);
      slab(ctx, drawerX, deskTop + 10, 22, pedH, wood.map((c, i) => (i < 2 ? c : mix(c, AMBIENT.shadow, 0.25))));
      px(ctx, drawerX + 1, deskTop + 10, 20, 1, withAlpha(AMBIENT.shadow, 0.4));
      px(ctx, drawerX + 2, deskTop + 10 + Math.floor(pedH / 2), 18, 1, wood[0]);
      px(ctx, drawerX + 7, deskTop + 14, 8, 1, MAT.brass[3]);
      px(ctx, drawerX + 7, deskTop + 14 + Math.floor(pedH / 2), 8, 1, MAT.brass[3]);
      // Top: a thick plane seen from slightly above, lit on top, a bevelled front lip.
      px(ctx, x - 1, deskTop - 1, w + 2, 12, AMBIENT.shadow);
      px(ctx, x, deskTop, w, 7, wood[3]);
      px(ctx, x, deskTop, w, 1, wood[4]);
      px(ctx, x, deskTop, 1, 7, wood[4]);
      px(ctx, x + w - 1, deskTop + 1, 1, 6, wood[2]);
      px(ctx, x, deskTop + 7, w, 1, wood[2]);
      px(ctx, x, deskTop + 8, w, 2, wood[1]);
      px(ctx, x, deskTop + 10, w, 1, wood[0]);
      // Grain.
      for (let gx = x + 6; gx < x + w - 6; gx += 17) px(ctx, gx, deskTop + 3, 9, 1, wood[2]);
      // Mousepad, keyboard in front of the seat, mouse to its right, a cable to the floor.
      px(ctx, seatX + 12, deskTop + 2, 10, 5, mix(wood[1], AMBIENT.shadow, 0.35));
      px(ctx, seatX - 11, deskTop + 2, 22, 4, MAT.black[1]);
      px(ctx, seatX - 11, deskTop + 2, 22, 1, MAT.black[3]);
      for (let kx = seatX - 9; kx < seatX + 10; kx += 2) px(ctx, kx, deskTop + 4, 1, 1, MAT.black[4]);
      px(ctx, seatX + 14, deskTop + 3, 4, 3, MAT.chrome[3]);
      px(ctx, seatX + 14, deskTop + 3, 4, 1, MAT.chrome[4]);
      px(ctx, x + w - 12, deskTop + 11, 1, legH - 3, MAT.black[1]);
    },
  };
}

/** Monitor on a desk: bezel and stand. The screen area is returned for the live painter. */
export function monitor(ctx, x, deskTop, w = 30, h = 22, variant = 0) {
  const top = deskTop - h - 4;
  // Stand
  px(ctx, x + w / 2 - 2, deskTop - 4, 4, 5, MAT.black[2]);
  px(ctx, x + w / 2 - 7, deskTop + 1, 14, 2, MAT.black[3]);
  px(ctx, x + w / 2 - 7, deskTop + 3, 14, 1, AMBIENT.shadow);
  // Bezel with a lit top edge; slight 3/4 by lighting the left side.
  px(ctx, x - 1, top - 1, w + 2, h + 2, AMBIENT.shadow);
  px(ctx, x, top, w, h, MAT.black[2]);
  px(ctx, x, top, w, 1, MAT.black[4]);
  px(ctx, x, top, 1, h, MAT.black[3]);
  px(ctx, x + w - 1, top + h - 1, 1, 1, variant ? UI.green : UI.amber);
  return { mx: x + 2, my: top + 2, w: w - 4, h: h - 4 };
}

export function laptop(ctx, x, deskTop, w = 22) {
  const h = 14;
  const top = deskTop - h - 1;
  px(ctx, x - 1, top - 1, w + 2, h + 2, AMBIENT.shadow);
  px(ctx, x, top, w, h, MAT.chrome[1]);
  px(ctx, x, top, w, 1, MAT.chrome[3]);
  px(ctx, x - 2, deskTop - 1, w + 4, 3, MAT.chrome[2]);
  px(ctx, x - 2, deskTop - 1, w + 4, 1, MAT.chrome[4]);
  px(ctx, x - 3, deskTop + 2, w + 6, 1, AMBIENT.shadow);
  return { mx: x + 2, my: top + 2, w: w - 4, h: h - 4 };
}

export function deskLamp(ctx, x, deskTop, color, live, dir = 1) {
  px(ctx, x - 4, deskTop - 1, 9, 3, MAT.black[2]);
  px(ctx, x - 4, deskTop - 1, 9, 1, MAT.black[4]);
  px(ctx, x, deskTop - 16, 2, 15, MAT.black[2]);
  px(ctx, x + 1, deskTop - 16, 1, 15, MAT.black[3]);
  px(ctx, x + (dir > 0 ? 0 : -10), deskTop - 20, 12, 5, MAT.black[2]);
  px(ctx, x + (dir > 0 ? 0 : -10), deskTop - 20, 12, 1, MAT.black[4]);
  px(ctx, x + (dir > 0 ? 2 : -8), deskTop - 15, 8, 1, '#fff2c8');
  live.lamps.push({ x: x + (dir > 0 ? 6 : -4), y: deskTop - 12, r: 34, color: rgba(color, 0.35) });
}

export function mug(ctx, x, deskTop, color) {
  px(ctx, x - 1, deskTop - 7, 8, 8, AMBIENT.shadow);
  px(ctx, x, deskTop - 6, 6, 6, color);
  px(ctx, x, deskTop - 6, 6, 1, mix(color, AMBIENT.light, 0.45));
  px(ctx, x + 6, deskTop - 5, 2, 3, color);
  px(ctx, x + 7, deskTop - 6, 1, 5, AMBIENT.shadow);
}

export function papers(ctx, x, deskTop, count = 3) {
  for (let i = 0; i < count; i += 1) {
    px(ctx, x + i, deskTop - 1 - i, 14, 1, i === count - 1 ? MAT.paper[4] : MAT.paper[2]);
  }
  px(ctx, x + count - 1, deskTop - count, 14, 1, MAT.paper[3]);
  px(ctx, x + count + 2, deskTop - count, 6, 1, MAT.paper[1]);
}

export function plant(ctx, x, floorY, seed, size = 1) {
  const rnd = mulberry32(seed);
  const potW = Math.round(14 * size);
  const potH = Math.round(12 * size);
  contactShadow(ctx, x, floorY + 2, potW / 2 + 2, 2, 0.4);
  // Ceramic pot with a rim.
  px(ctx, x - potW / 2 - 1, floorY - potH - 1, potW + 2, potH + 2, AMBIENT.shadow);
  px(ctx, x - potW / 2, floorY - potH, potW, potH, MAT.terracotta[2]);
  px(ctx, x - potW / 2, floorY - potH, potW, 2, MAT.terracotta[4]);
  px(ctx, x - potW / 2, floorY - potH + 2, 2, potH - 2, MAT.terracotta[3]);
  px(ctx, x + potW / 2 - 3, floorY - potH + 2, 3, potH - 2, MAT.terracotta[1]);
  px(ctx, x - potW / 2, floorY - 2, potW, 2, MAT.terracotta[0]);
  // Leaves: pointed blades fanning out from the pot on thin stems; the back ones sit in
  // shade, the front ones catch the ceiling light along their upper edge and a pale vein.
  const top = floorY - potH;
  const leaves = 6 + Math.floor(rnd() * 3);
  const spread = Math.round(13 * size);
  const height = Math.round(26 * size);
  const blades = [];
  for (let i = 0; i < leaves; i += 1) {
    const a = 0.25 + (i / (leaves - 1)) * (Math.PI - 0.5) + (rnd() - 0.5) * 0.3;
    const len = height * (0.55 + rnd() * 0.45);
    blades.push({ a, len, depth: rnd(), lean: Math.cos(a) });
  }
  blades.sort((p, q) => p.depth - q.depth);
  const segments = (b) => {
    const dx = Math.cos(b.a) * spread * 1.1;
    const tipY = top - Math.round(Math.sin(b.a) * b.len) - 2;
    const steps = Math.max(4, Math.round(Math.hypot(dx, top - tipY)));
    const out = [];
    for (let sIdx = 0; sIdx <= steps; sIdx += 1) {
      const t = sIdx / steps;
      const w = t < 0.85 ? (t < 0.45 ? 2 + Math.round(size) : 3 + Math.round(size)) : 1;
      out.push({ t, w, x: Math.round(x + dx * (0.35 + t * 0.65)), y: Math.round(top - (top - tipY) * (0.35 + t * 0.65)) });
    }
    return { dx, tipY, out };
  };
  // Pass 1: stems and the outline of every blade, so no blade's outline cuts another's fill.
  for (const b of blades) {
    const { dx, tipY, out } = segments(b);
    for (let sIdx = 0; sIdx <= 6; sIdx += 1) {
      const t = sIdx / 6;
      px(ctx, Math.round(x + dx * t * 0.35), Math.round(top - (top - tipY) * t * 0.35), 1, 1, MAT.plant[1]);
    }
    for (const seg of out) px(ctx, seg.x - Math.floor(seg.w / 2) - 1, seg.y - 2, seg.w + 2, 4, AMBIENT.shadow);
  }
  // Pass 2: fills, back blades in shade, front blades lit along the top with a pale vein.
  for (const b of blades) {
    const base = b.depth > 0.6 ? MAT.plant[3] : b.depth > 0.3 ? MAT.plant[2] : MAT.plant[1];
    for (const seg of segments(b).out) {
      const left = seg.x - Math.floor(seg.w / 2);
      px(ctx, left, seg.y - 1, seg.w, 2, base);
      if (seg.t > 0.85) px(ctx, left, seg.y - 1, seg.w, 1, MAT.plant[4]);
      else if (b.depth > 0.3 && seg.w >= 3) px(ctx, left + (b.lean < 0 ? 0 : seg.w - 1), seg.y - 1, 1, 1, MAT.plant[4]);
      if (seg.t > 0.2 && seg.t < 0.8 && seg.w >= 3) px(ctx, seg.x, seg.y, 1, 1, b.depth > 0.3 ? MAT.plant[4] : MAT.plant[2]);
    }
  }
}

export function bookshelf(ctx, x, floorY, w, h, seed, wood = MAT.walnut) {
  const rnd = mulberry32(seed);
  contactShadow(ctx, x + w / 2, floorY + 2, w / 2 + 2, 2, 0.4);
  slab(ctx, x, floorY - h, w, h, wood);
  const shelves = Math.max(2, Math.floor(h / 18));
  for (let s = 0; s < shelves; s += 1) {
    const shelfY = floorY - h + 4 + s * ((h - 6) / shelves);
    const shelfBottom = shelfY + (h - 6) / shelves - 3;
    px(ctx, x + 2, shelfY, w - 4, shelfBottom - shelfY, wood[0]);
    let bx = x + 4;
    while (bx < x + w - 6) {
      const bw = 3 + Math.floor(rnd() * 4);
      const bh = 8 + Math.floor(rnd() * 6);
      const c = pick(['#b84a3a', '#2f7a6a', '#d8a44a', '#5a5a9a', '#8a3a5a', '#e8dcc0', '#4a7ab0', '#c07a3a'], rnd);
      px(ctx, bx, shelfBottom - bh, bw, bh, c);
      px(ctx, bx, shelfBottom - bh, bw, 1, mix(c, AMBIENT.light, 0.4));
      px(ctx, bx + bw - 1, shelfBottom - bh, 1, bh, mix(c, AMBIENT.shadow, 0.4));
      if (rnd() > 0.7) { px(ctx, bx, shelfBottom - 1, bw, 1, mix(c, AMBIENT.shadow, 0.6)); }
      bx += bw + (rnd() > 0.85 ? 4 : 1);
    }
    px(ctx, x + 2, shelfBottom, w - 4, 2, wood[3]);
    px(ctx, x + 2, shelfBottom + 2, w - 4, 1, wood[0]);
  }
}

export function wallShelf(ctx, x, y, seed) {
  const rnd = mulberry32(seed);
  px(ctx, x - 1, y + 11, 42, 4, AMBIENT.shadow);
  px(ctx, x, y + 11, 40, 3, MAT.oak[3]);
  px(ctx, x, y + 11, 40, 1, MAT.oak[4]);
  let bx = x + 3;
  while (bx < x + 34) {
    const bw = 3 + Math.floor(rnd() * 3);
    const bh = 7 + Math.floor(rnd() * 4);
    const c = pick(['#b84a3a', '#2f7a6a', '#d8a44a', '#5a5a9a', '#e8dcc0'], rnd);
    px(ctx, bx, y + 11 - bh, bw, bh, c);
    px(ctx, bx, y + 11 - bh, bw, 1, mix(c, AMBIENT.light, 0.4));
    bx += bw + 1;
  }
  // A small plant at the end of the shelf.
  px(ctx, x + 34, y + 5, 5, 6, MAT.terracotta[2]);
  px(ctx, x + 33, y + 1, 7, 4, MAT.plant[2]);
  px(ctx, x + 35, y, 3, 2, MAT.plant[4]);
}

export function filingCabinet(ctx, x, floorY, accent) {
  contactShadow(ctx, x + 12, floorY + 2, 14, 2, 0.4);
  slab(ctx, x, floorY - 36, 24, 36, MAT.steel);
  for (let i = 0; i < 3; i += 1) {
    px(ctx, x + 2, floorY - 33 + i * 11, 20, 9, MAT.steel[1]);
    px(ctx, x + 2, floorY - 33 + i * 11, 20, 1, MAT.steel[3]);
    px(ctx, x + 8, floorY - 29 + i * 11, 8, 2, MAT.chrome[3]);
  }
  px(ctx, x + 4, floorY - 30, 6, 3, accent);
}

export function whiteboard(ctx, x, y, w, h, accent, seed) {
  const rnd = mulberry32(seed);
  px(ctx, x - 2, y - 2, w + 4, h + 4, AMBIENT.shadow);
  px(ctx, x - 1, y - 1, w + 2, h + 2, MAT.chrome[2]);
  px(ctx, x - 1, y - 1, w + 2, 1, MAT.chrome[4]);
  px(ctx, x, y, w, h, MAT.ceramic[3]);
  px(ctx, x, y + h - 1, w, 1, MAT.ceramic[2]);
  // Marker notes: a few lines, a box diagram, a sticky note.
  for (let i = 0; i < 5; i += 1) {
    const lx = x + 6 + Math.floor(rnd() * 10);
    const ly = y + 7 + i * Math.floor((h - 14) / 5);
    px(ctx, lx, ly, 14 + Math.floor(rnd() * 26), 2, i % 2 ? '#3a6a9a' : mix(accent, AMBIENT.shadow, 0.35));
  }
  outlineRect(ctx, x + w - 34, y + 8, 24, 16, '#c04a4a');
  px(ctx, x + w - 30, y + 13, 16, 2, '#c04a4a');
  px(ctx, x + w - 30, y + 18, 10, 2, '#3a6a9a');
  px(ctx, x + w - 46, y + h - 16, 10, 10, '#f4d86a');
  px(ctx, x + w - 46, y + h - 16, 10, 1, '#fff3b0');
  // Marker tray.
  px(ctx, x + 6, y + h + 1, w - 12, 3, MAT.chrome[2]);
  px(ctx, x + 10, y + h - 1, 6, 2, '#c04a4a');
  px(ctx, x + 18, y + h - 1, 6, 2, '#3a6a9a');
}

export function poster(ctx, x, y, seed, accent) {
  const rnd = mulberry32(seed);
  const w = 24 + Math.floor(rnd() * 12);
  const h = 32 + Math.floor(rnd() * 10);
  px(ctx, x - 1, y - 1, w + 2, h + 2, AMBIENT.shadow);
  px(ctx, x, y, w, h, MAT.black[2]);
  const art = pick([['#28405a', '#4a7a9a', '#c8d8e0'], ['#4a2a40', '#a05a80', '#f0c8d0'], ['#2a4a34', '#5a9a60', '#e0f0c0'], ['#5a3a20', '#c08040', '#f0e0b0']], rnd);
  px(ctx, x + 2, y + 2, w - 4, h - 4, art[0]);
  // A simple bold composition: a horizon, a sun, a title band.
  px(ctx, x + 2, y + h * 0.55, w - 4, h * 0.45 - 2, art[1]);
  px(ctx, x + w * 0.55, y + 8, 6, 6, art[2]);
  px(ctx, x + 5, y + h - 9, w - 10, 2, art[2]);
  px(ctx, x + 5, y + h - 5, (w - 10) * 0.6, 1, accent);
}

export function coatStand(ctx, x, floorY, seed) {
  const rnd = mulberry32(seed);
  contactShadow(ctx, x, floorY + 2, 7, 1, 0.35);
  px(ctx, x - 1, floorY - 64, 3, 64, MAT.walnut[1]);
  px(ctx, x, floorY - 64, 1, 64, MAT.walnut[3]);
  px(ctx, x - 7, floorY - 3, 15, 3, MAT.walnut[1]);
  px(ctx, x - 6, floorY - 66, 13, 3, MAT.walnut[2]);
  px(ctx, x - 7, floorY - 63, 3, 2, MAT.walnut[3]);
  px(ctx, x + 5, floorY - 63, 3, 2, MAT.walnut[3]);
  const coat = pick([MAT.fabricRed, MAT.fabricOlive, MAT.fabricBlue, MAT.leather], rnd);
  px(ctx, x - 11, floorY - 61, 8, 22, coat[2]);
  px(ctx, x - 11, floorY - 61, 8, 1, coat[3]);
  px(ctx, x - 11, floorY - 40, 8, 1, coat[0]);
  px(ctx, x - 12, floorY - 61, 1, 22, AMBIENT.shadow);
  const scarf = pick([MAT.fabricRed, MAT.fabricOlive, MAT.brass], rnd);
  px(ctx, x + 4, floorY - 60, 4, 14, scarf[2]);
  px(ctx, x + 4, floorY - 60, 4, 1, scarf[3]);
}

export function bin(ctx, x, floorY) {
  contactShadow(ctx, x + 6, floorY + 2, 7, 1, 0.35);
  px(ctx, x - 1, floorY - 14, 14, 15, AMBIENT.shadow);
  px(ctx, x, floorY - 13, 12, 13, MAT.steel[2]);
  px(ctx, x, floorY - 13, 12, 1, MAT.steel[4]);
  px(ctx, x + 10, floorY - 12, 1, 12, MAT.steel[0]);
  px(ctx, x + 3, floorY - 16, 5, 3, MAT.paper[3]);
}

export function extinguisher(ctx, x, floorY) {
  px(ctx, x - 1, floorY - 29, 9, 20, AMBIENT.shadow);
  px(ctx, x, floorY - 28, 7, 18, '#c8483a');
  px(ctx, x, floorY - 28, 2, 18, '#e86a58');
  px(ctx, x + 2, floorY - 32, 3, 4, MAT.black[2]);
  px(ctx, x - 1, floorY - 24, 9, 2, MAT.chrome[3]);
  px(ctx, x - 3, floorY - 36, 2, 16, MAT.black[1]);
}

export function exitSign(ctx, x, y) {
  px(ctx, x - 1, y - 1, 24, 12, AMBIENT.shadow);
  px(ctx, x, y, 22, 10, '#173a26');
  px(ctx, x, y, 22, 1, '#2e6a44');
  drawText(ctx, 'EXIT', x + 3, y + 2, '#8ff0a8', 1, 1);
}

export function wallClockFace(ctx, live, x, y) {
  px(ctx, x - 9, y - 9, 18, 18, AMBIENT.shadow);
  px(ctx, x - 8, y - 8, 16, 16, MAT.black[2]);
  px(ctx, x - 8, y - 8, 16, 1, MAT.black[4]);
  px(ctx, x - 6, y - 6, 12, 12, MAT.paper[4]);
  live.clocks.push({ x, y });
}

export function sofa(ctx, x, floorY, w, fabric) {
  contactShadow(ctx, x + w / 2, floorY + 2, w / 2 + 2, 2, 0.45);
  // Back, seat cushions, arms.
  px(ctx, x - 1, floorY - 31, w + 2, 32, AMBIENT.shadow);
  px(ctx, x, floorY - 30, w, 30, fabric[2]);
  px(ctx, x, floorY - 30, w, 1, fabric[4]);
  px(ctx, x + 2, floorY - 18, w - 4, 8, fabric[3]);
  px(ctx, x + 2, floorY - 18, w - 4, 1, fabric[4]);
  px(ctx, x + 2, floorY - 10, w - 4, 1, fabric[0]);
  const cushions = Math.max(2, Math.round(w / 32));
  for (let i = 1; i < cushions; i += 1) px(ctx, x + (w * i) / cushions, floorY - 18, 1, 8, fabric[1]);
  px(ctx, x, floorY - 22, 6, 18, fabric[1]);
  px(ctx, x + w - 6, floorY - 22, 6, 18, fabric[1]);
  px(ctx, x, floorY - 22, 6, 1, fabric[4]);
  px(ctx, x + w - 6, floorY - 22, 6, 1, fabric[4]);
  px(ctx, x, floorY - 4, w, 4, fabric[0]);
  px(ctx, x + 3, floorY - 2, 3, 2, MAT.walnut[1]);
  px(ctx, x + w - 6, floorY - 2, 3, 2, MAT.walnut[1]);
}

export function rug(ctx, x, floorY, w, colors) {
  px(ctx, x, floorY + 1, w, 5, colors[0]);
  px(ctx, x + 2, floorY + 2, w - 4, 3, colors[1]);
  for (let sx = x + 6; sx < x + w - 6; sx += 10) px(ctx, sx, floorY + 3, 4, 1, colors[2]);
}

/** Low table with a couple of items on it. */
export function coffeeTable(ctx, x, floorY, w) {
  contactShadow(ctx, x + w / 2, floorY + 2, w / 2, 1, 0.35);
  px(ctx, x - 1, floorY - 15, w + 2, 6, AMBIENT.shadow);
  px(ctx, x, floorY - 14, w, 4, MAT.oak[3]);
  px(ctx, x, floorY - 14, w, 1, MAT.oak[4]);
  px(ctx, x, floorY - 10, w, 1, MAT.oak[1]);
  px(ctx, x + 3, floorY - 9, 2, 9, MAT.oak[1]);
  px(ctx, x + w - 5, floorY - 9, 2, 9, MAT.oak[1]);
  px(ctx, x + 8, floorY - 17, 10, 3, MAT.paper[3]);
  px(ctx, x + w - 16, floorY - 18, 6, 4, '#c9573f');
}

/* ============================================================================
   Screen content, painted per frame by the engine.
   ========================================================================== */

export function drawScreenContent(ctx, kind, mx, my, w, h, time, seed, accent, active) {
  const rnd = mulberry32(seed);
  const speed = active ? 1 : 0.25;
  ctx.save();
  ctx.beginPath();
  ctx.rect(mx, my, w, h);
  ctx.clip();

  if (kind === 'chart') {
    px(ctx, mx, my, w, h, MAT.screen[1]);
    const bars = 8;
    const bw = Math.max(1, Math.floor((w - 4) / bars) - 1);
    for (let i = 0; i < bars; i += 1) {
      const base = 0.25 + rnd() * 0.6;
      const wob = Math.sin(time * speed * 1.7 + i) * 0.14;
      const bh = Math.max(1, Math.min(1, base + wob) * (h - 5));
      px(ctx, mx + 2 + i * (bw + 1), my + h - 2 - bh, bw, bh, i % 3 === 0 ? accent : MAT.screen[4]);
    }
    px(ctx, mx, my + h - 2, w, 1, MAT.screen[3]);
  } else if (kind === 'doc') {
    px(ctx, mx, my, w, h, '#1a1e2a');
    px(ctx, mx + 2, my + 2, w - 4, h - 4, MAT.paper[3]);
    const lines = Math.floor((h - 8) / 3);
    const caret = Math.floor((time * speed * 3) % Math.max(1, lines));
    for (let i = 0; i < lines; i += 1) {
      const lw = (0.35 + rnd() * 0.55) * (w - 8);
      px(ctx, mx + 4, my + 4 + i * 3, lw, 1, i === caret && active ? mix(accent, AMBIENT.shadow, 0.4) : MAT.paper[0]);
    }
    if (active && Math.sin(time * 6) > 0) px(ctx, mx + 4 + (0.35 + rnd() * 0.55) * (w - 8), my + 4 + caret * 3, 2, 2, AMBIENT.shadow);
  } else if (kind === 'timeline') {
    px(ctx, mx, my, w, h, MAT.screen[0]);
    px(ctx, mx + 2, my + 2, w - 4, h * 0.42, MAT.screen[2]);
    for (let i = 0; i < 6; i += 1) px(ctx, mx + 3 + i * 6, my + 4, 5, h * 0.34, i % 2 ? '#3a6a80' : '#2a5064');
    const trackY = my + h * 0.55;
    px(ctx, mx + 2, trackY, w - 4, 3, '#2a4a5c');
    px(ctx, mx + 2, trackY + 5, w - 4, 3, '#24404e');
    px(ctx, mx + 4, trackY, (w - 8) * 0.6, 3, accent);
    const play = ((time * speed * 0.22) % 1) * (w - 6);
    px(ctx, mx + 3 + play, my + 2, 1, h - 4, '#ffffff');
  } else if (kind === 'waveform') {
    px(ctx, mx, my, w, h, '#16101e');
    const mid = my + h / 2;
    for (let i = 0; i < w - 2; i += 2) {
      const amp = (Math.sin(i * 0.5 + time * speed * 5) * 0.5 + Math.sin(i * 0.19 - time * speed * 3) * 0.5) * (h / 2 - 2);
      const a = Math.abs(amp) * (active ? 1 : 0.35);
      px(ctx, mx + 1 + i, mid - a, 1, a * 2 + 1, i % 6 === 0 ? accent : '#8a5c98');
    }
  } else if (kind === 'graph') {
    px(ctx, mx, my, w, h, MAT.screen[1]);
    for (let gx = mx + 4; gx < mx + w; gx += 7) px(ctx, gx, my + 2, 1, h - 4, MAT.screen[2]);
    let prev = null;
    for (let i = 0; i <= 10; i += 1) {
      const nx = mx + 2 + (i * (w - 4)) / 10;
      const ny = my + h - 3 - (Math.sin(i * 0.7 + time * speed * 0.9) * 0.35 + 0.5) * (h - 8);
      if (prev) {
        const steps = 6;
        for (let s = 1; s < steps; s += 1) px(ctx, prev[0] + ((nx - prev[0]) * s) / steps, prev[1] + ((ny - prev[1]) * s) / steps, 1, 1, MAT.screen[4]);
      }
      px(ctx, nx, ny, 2, 2, accent);
      prev = [nx, ny];
    }
  } else if (kind === 'upload') {
    px(ctx, mx, my, w, h, '#1e1512');
    drawText(ctx, 'QUEUE', mx + 3, my + 3, '#7a6a5a', 1, 1);
    for (let i = 0; i < 3; i += 1) {
      const p = active ? (time * speed * 0.18 + i * 0.31) % 1 : 0.2 + i * 0.1;
      px(ctx, mx + 3, my + 12 + i * 6, w - 8, 3, '#3a2a24');
      px(ctx, mx + 3, my + 12 + i * 6, (w - 8) * p, 3, i === 0 ? accent : '#a05a48');
    }
  } else if (kind === 'code') {
    px(ctx, mx, my, w, h, '#0e1420');
    const lines = Math.floor((h - 4) / 3);
    const scroll = Math.floor(time * speed * 2);
    for (let i = 0; i < lines; i += 1) {
      const r = mulberry32(seed + ((i + scroll) % 40));
      const indent = Math.floor(r() * 3) * 3;
      px(ctx, mx + 3 + indent, my + 3 + i * 3, (0.2 + r() * 0.5) * (w - 8), 1, pick(['#6aa0d8', '#c88ad8', '#7fd8a8', '#c8c8d8'], r));
    }
  } else if (kind === 'video') {
    px(ctx, mx, my, w, h, '#0c0c14');
    const t = (time * speed * 0.3) % 1;
    px(ctx, mx + 2, my + 2, w - 4, h - 6, mix('#2a4a6a', '#6a3a4a', t));
    px(ctx, mx + 4 + t * (w - 12), my + 5, 6, h - 12, mix(accent, '#ffffff', 0.3));
    px(ctx, mx + 2, my + h - 3, (w - 4) * t, 1, accent);
  } else {
    px(ctx, mx, my, w, h, MAT.screen[1]);
    for (let i = 0; i < 4; i += 1) px(ctx, mx + 3, my + 4 + i * 4, (0.4 + rnd() * 0.5) * (w - 8), 2, MAT.screen[4]);
  }

  // Glass: a diagonal sheen and a thin vignette that ties every screen together.
  ctx.globalAlpha = 0.09;
  ctx.fillStyle = '#ffffff';
  ctx.beginPath();
  ctx.moveTo(mx, my);
  ctx.lineTo(mx + w * 0.5, my);
  ctx.lineTo(mx, my + h * 0.8);
  ctx.closePath();
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.restore();
}

/* ============================================================================
   Department interiors.
   Static parts are drawn now; moving parts are registered in `live`.
   ========================================================================== */

export function interiorFor(zone, ctx, live, daylight = 0, backdrop = null) {
  const dept = department(zone.zone_type);
  const view = { backdrop, floor: zone.floor || 0 };
  const floorY = floorLine(zone);
  const seed = hash32(zone.id);
  const rnd = mulberry32(seed);
  const desks = zone.desks || [];
  const wallTop = zone.y + CEILING_H;

  const addScreen = (kind, area, deskId) =>
    live.screens.push({ kind, ...area, seed: hash32(`${zone.id}${area.mx}${area.my}`), accent: dept.accent, zoneId: zone.id, deskId });

  const stations = new Map();
  /** Wall spans taken by fixed props, so fillers never overlap them. */
  const occupied = desks.map((d) => [d.x - 48, d.x + 48]);
  const reserve = (x0, w) => occupied.push([x0 - 6, x0 + w + 6]);
  const premium = usesAtlas(zone);
  const useProp = (name) => premium && propReady(name);
  const station = (d, variant) => {
    const s = workstation(zone, dept, d.x, variant, premium);
    stations.set(d.id || d.x, s);
    return s;
  };

  switch (zone.zone_type) {
    case 'RESEARCH': {
      // Evidence wall between the two desks, archive shelving, reference books.
      // Each prop comes from the sprite atlas when it is loaded, else from the drawing below.
      const cx = zone.x + zone.width / 2;
      if (useProp('evidence_board')) drawProp(ctx, 'evidence_board', cx - 70, wallTop + 12);
      else evidenceBoard(ctx, cx - 70, wallTop + 12, 140, 52, rnd);
      reserve(cx - 72, 144);
      drawWindow(ctx, zone.x + 100, wallTop + 14, 46, 38, daylight, premium, floorY, view);
      reserve(zone.x + 96, 54);
      drawWindow(ctx, zone.x + zone.width - 150, wallTop + 14, 46, 38, daylight, premium, floorY, view);
      reserve(zone.x + zone.width - 154, 54);
      if (useProp('bookshelf_ash')) placeProp(ctx, 'bookshelf_ash', zone.x + 16, floorY);
      else bookshelf(ctx, zone.x + 16, floorY, 66, 72, seed + 3, MAT.ash);
      reserve(zone.x + 14, 70);
      if (useProp('lab_bench')) placeProp(ctx, 'lab_bench', zone.x + zone.width - 236, floorY);
      else labBench(ctx, zone.x + zone.width - 236, floorY, rnd, live, zone.id);
      reserve(zone.x + zone.width - 240, 96);
      if (useProp('archive_boxes')) placeProp(ctx, 'archive_boxes', zone.x + zone.width - 72, floorY);
      else archiveBoxes(ctx, zone.x + zone.width - 72, floorY, rnd);
      reserve(zone.x + zone.width - 76, 62);
      if (useProp('plant_large')) placeProp(ctx, 'plant_large', zone.x + zone.width - 20, floorY);
      else plant(ctx, zone.x + zone.width - 20, floorY, seed + 7, 1.1);
      desks.forEach((d, i) => {
        const s = station(d, i);
        s.back(ctx);
      });
      break;
    }
    case 'DIRECTOR': {
      bookshelf(ctx, zone.x + 16, floorY, 84, 74, seed + 3, MAT.walnut);
      reserve(zone.x + 14, 88);
      drawWindow(ctx, zone.x + 150, wallTop + 12, 74, 44, daylight, false, floorY, view);
      reserve(zone.x + 146, 82);
      drawWindow(ctx, zone.x + zone.width - 300, wallTop + 12, 74, 44, daylight, false, floorY, view);
      reserve(zone.x + zone.width - 304, 82);
      awardsShelf(ctx, zone.x + zone.width - 150, wallTop + 30, 70);
      reserve(zone.x + zone.width - 154, 78);
      wallClockFace(ctx, live, zone.x + zone.width - 60, wallTop + 40);
      plant(ctx, zone.x + 124, floorY, seed + 5, 1.3);
      reserve(zone.x + 108, 32);
      rug(ctx, zone.x + zone.width - 210, floorY, 190, [MAT.fabricRed[0], MAT.fabricRed[1], MAT.brass[2]]);
      coffeeTable(ctx, zone.x + zone.width - 196, floorY, 44);
      sofa(ctx, zone.x + zone.width - 136, floorY, 96, MAT.leather);
      reserve(zone.x + zone.width - 200, 170);
      plant(ctx, zone.x + zone.width - 22, floorY, seed + 8, 0.9);
      desks.forEach((d, i) => station(d, 0).back(ctx));
      break;
    }
    case 'SCRIPT': {
      storyboardWall(ctx, zone.x + 110, wallTop + 10, 180, 56, rnd);
      reserve(zone.x + 106, 188);
      drawWindow(ctx, zone.x + zone.width - 230, wallTop + 12, 50, 40, daylight, false, floorY, view);
      reserve(zone.x + zone.width - 234, 58);
      bookshelf(ctx, zone.x + zone.width - 150, floorY, 64, 52, seed + 9, MAT.oak);
      reserve(zone.x + zone.width - 154, 70);
      floorLamp(ctx, zone.x + zone.width - 48, floorY, live, dept.lamp);
      reserve(zone.x + zone.width - 64, 30);
      plant(ctx, zone.x + 20, floorY, seed + 4, 0.9);
      typewriterCorner(ctx, zone.x + 40, floorY);
      reserve(zone.x + 10, 80);
      desks.forEach((d, i) => station(d, 1).back(ctx));
      break;
    }
    case 'AUDIO': {
      vocalBooth(ctx, zone, live, wallTop, floorY, rnd);
      reserve(zone.x + zone.width - 176, 176);
      speakerStand(ctx, zone.x + 18, floorY);
      speakerStand(ctx, zone.x + 62, floorY);
      reserve(zone.x + 12, 74);
      guitarOnWall(ctx, zone.x + 102, wallTop + 26);
      reserve(zone.x + 96, 20);
      plant(ctx, zone.x + 40, floorY, seed + 11, 0.7);
      desks.forEach((d, i) => station(d, i).back(ctx));
      break;
    }
    case 'VIDEO': {
      shortsPoster(ctx, zone.x + 24, wallTop + 24, dept.accent);
      reserve(zone.x + 20, 64);
      driveStack(ctx, zone.x + zone.width - 62, floorY, live, dept.accent);
      reserve(zone.x + zone.width - 66, 52);
      drawWindow(ctx, zone.x + 110, wallTop + 14, 46, 36, daylight, false, floorY, view);
      reserve(zone.x + 106, 54);
      plant(ctx, zone.x + zone.width - 96, floorY, seed + 5, 0.9);
      lightStand(ctx, zone.x + zone.width - 126, floorY, live);
      reserve(zone.x + zone.width - 140, 58);
      desks.forEach((d, i) => station(d, i).back(ctx));
      break;
    }
    case 'SERVER': {
      serverRoom(ctx, zone, live, desks, wallTop, floorY, rnd);
      break;
    }
    case 'LOUNGE': {
      lounge(ctx, zone, live, wallTop, floorY, rnd, seed);
      break;
    }
    case 'PUBLISH': {
      dispatchBoard(ctx, zone, live, wallTop, rnd, dept);
      crateShelf(ctx, zone.x + 6, floorY);
      wallClockFace(ctx, live, zone.x + zone.width - 28, wallTop + 60);
      desks.forEach((d, i) => {
        const s = station(d, i);
        s.back(ctx);
      });
      break;
    }
    case 'SHOP': {
      shopFront(ctx, zone, live, wallTop, floorY, rnd, dept);
      break;
    }
    default: {
      desks.forEach((d, i) => station(d, i).back(ctx));
    }
  }

  return { stations, addScreen, dept, occupied };
}

/**
 * Second pass, after the characters: desks and what stands on them. Registers the screens.
 * Called by the engine right after the body sprites of that zone are drawn.
 */
export function drawDeskFronts(ctx, zone, interior, live) {
  const { stations, addScreen, dept } = interior;
  const desks = zone.desks || [];
  desks.forEach((d, i) => {
    const s = stations.get(d.id || d.x);
    if (!s) return;
    s.front(ctx);
    const deskTop = s.deskTop;
    switch (zone.zone_type) {
      case 'RESEARCH': {
        if (s.premium) {
          // The sprite already carries monitor, papers, mug and lamp; register the live parts.
          if (s.screen) addScreen(i === 0 ? 'doc' : 'graph', s.screen, d.id);
          if (s.lamp) live.lamps.push({ x: s.lamp.x, y: s.lamp.y, r: 34, color: rgba(dept.lamp, 0.35) });
          break;
        }
        const m1 = monitor(ctx, s.monitorX, deskTop, 28, 22, i);
        addScreen(i === 0 ? 'doc' : 'graph', m1, d.id);
        papers(ctx, s.seatX + 20, deskTop + 2, 3);
        mug(ctx, s.seatX + 26, deskTop - 1, '#3f8a7a');
        deskLamp(ctx, s.seatX + 34, deskTop, dept.lamp, live, -1);
        break;
      }
      case 'DIRECTOR': {
        const m1 = monitor(ctx, s.monitorX, deskTop, 32, 24, 0);
        addScreen('chart', m1, d.id);
        const lp = laptop(ctx, s.seatX + 16, deskTop + 1, 20);
        addScreen('graph', lp, d.id);
        mug(ctx, s.seatX - 34, deskTop - 1, '#c9573f');
        deskPhone(ctx, s.seatX + 26, deskTop + 2);
        deskLamp(ctx, s.monitorX - 2, deskTop, dept.lamp, live, 1);
        break;
      }
      case 'SCRIPT': {
        const m1 = monitor(ctx, s.monitorX, deskTop, 34, 24, i);
        addScreen('doc', m1, d.id);
        papers(ctx, s.seatX + 18, deskTop + 2, 5);
        mug(ctx, s.seatX + 30, deskTop - 1, '#b8873f');
        deskLamp(ctx, s.seatX + 34, deskTop, dept.lamp, live, -1);
        break;
      }
      case 'AUDIO': {
        mixingDesk(ctx, s, live, zone.id);
        const m1 = monitor(ctx, s.monitorX, deskTop, 30, 22, i);
        addScreen('waveform', m1, d.id);
        boomMic(ctx, s.seatX + 20, deskTop);
        break;
      }
      case 'VIDEO': {
        const m0 = monitor(ctx, s.monitorX - 26, deskTop, 24, 20, 1);
        const m1 = monitor(ctx, s.monitorX + 1, deskTop, 34, 26, 0);
        addScreen('video', m1, d.id);
        addScreen('timeline', m0, d.id);
        gradingPanel(ctx, s.seatX + 14, deskTop + 2);
        break;
      }
      case 'PUBLISH': {
        const m1 = monitor(ctx, s.monitorX, deskTop, 30, 22, 0);
        addScreen('upload', m1, d.id);
        const m2 = monitor(ctx, s.seatX + 14, deskTop, 24, 20, 1);
        live.radars.push({ ...m2, zoneId: zone.id });
        deskLamp(ctx, s.monitorX - 2, deskTop, dept.lamp, live, 1);
        break;
      }
      default: {
        const m1 = monitor(ctx, s.monitorX, deskTop, 30, 22, i);
        addScreen('doc', m1, d.id);
      }
    }
  });
}

/* ------------------------------------------------------------ department props */

function evidenceBoard(ctx, x, y, w, h, rnd) {
  px(ctx, x - 2, y - 2, w + 4, h + 4, AMBIENT.shadow);
  px(ctx, x - 1, y - 1, w + 2, h + 2, MAT.walnut[3]);
  px(ctx, x, y, w, h, '#8a6a48');
  for (let i = 0; i < w * h * 0.02; i += 1) px(ctx, x + rnd() * w, y + rnd() * h, 1, 1, '#7a5c3e');
  const cards = [];
  for (let i = 0; i < 6; i += 1) {
    const cx = x + 8 + (i % 3) * 44 + Math.floor(rnd() * 4);
    const cy = y + 7 + Math.floor(i / 3) * 24 + Math.floor(rnd() * 2);
    const tone = pick([MAT.paper[3], '#dfe6cf', '#f2dfb0', '#d9e6ee'], rnd);
    px(ctx, cx + 1, cy + 1, 28, 17, withAlpha(AMBIENT.shadow, 0.35));
    px(ctx, cx, cy, 28, 17, tone);
    px(ctx, cx + 3, cy + 4, 20, 1, '#6a6a70');
    px(ctx, cx + 3, cy + 8, 16, 1, '#6a6a70');
    px(ctx, cx + 3, cy + 12, 18, 1, '#6a6a70');
    if (i % 2) px(ctx, cx + 18, cy + 3, 6, 6, pick(['#c04a4a', '#3a7ab0', '#3a9a6a'], rnd));
    px(ctx, cx + 13, cy - 1, 2, 2, '#e04a4a');
    cards.push([cx + 14, cy]);
  }
  ctx.strokeStyle = 'rgba(224,74,74,0.7)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let i = 0; i < cards.length - 1; i += 1) {
    ctx.moveTo(cards[i][0] + 0.5, cards[i][1] + 0.5);
    ctx.lineTo(cards[i + 1][0] + 0.5, cards[i + 1][1] + 0.5);
  }
  ctx.stroke();
}

function labBench(ctx, x, floorY, rnd, live = null, zoneId = null) {
  // A steel bench with instruments: flasks, a microscope, a notebook.
  contactShadow(ctx, x + 44, floorY + 2, 46, 2, 0.4);
  px(ctx, x + 3, floorY - 24, 3, 24, MAT.steel[1]);
  px(ctx, x + 82, floorY - 24, 3, 24, MAT.steel[1]);
  px(ctx, x + 3, floorY - 24, 1, 24, MAT.steel[3]);
  px(ctx, x - 1, floorY - 31, 90, 8, AMBIENT.shadow);
  px(ctx, x, floorY - 30, 88, 6, MAT.ceramic[2]);
  px(ctx, x, floorY - 30, 88, 1, MAT.ceramic[4]);
  px(ctx, x, floorY - 25, 88, 1, MAT.ceramic[0]);
  // Flasks.
  for (let i = 0; i < 3; i += 1) {
    const fx = x + 8 + i * 12;
    const c = pick(['#5ee0c8', '#ffb35c', '#e08ae4'], rnd);
    px(ctx, fx - 1, floorY - 45, 8, 16, AMBIENT.shadow);
    px(ctx, fx + 2, floorY - 44, 2, 6, MAT.glass[3]);
    px(ctx, fx, floorY - 38, 6, 8, MAT.glass[2]);
    px(ctx, fx, floorY - 35, 6, 5, c);
    px(ctx, fx, floorY - 38, 1, 8, MAT.glass[4]);
    if (live) live.bubbles.push({ x: fx + 2, y: floorY - 36, zoneId, color: c });
  }
  // Microscope.
  px(ctx, x + 50, floorY - 52, 12, 23, AMBIENT.shadow);
  px(ctx, x + 51, floorY - 33, 10, 3, MAT.black[2]);
  px(ctx, x + 58, floorY - 51, 3, 18, MAT.black[2]);
  px(ctx, x + 54, floorY - 50, 5, 3, MAT.chrome[2]);
  px(ctx, x + 55, floorY - 47, 2, 8, MAT.chrome[3]);
  px(ctx, x + 53, floorY - 39, 6, 2, MAT.black[3]);
  // Notebook.
  px(ctx, x + 68, floorY - 33, 14, 3, MAT.paper[3]);
  px(ctx, x + 70, floorY - 34, 12, 1, MAT.paper[4]);
}

function archiveBoxes(ctx, x, floorY, rnd) {
  const boxes = [[0, 0], [30, 0], [15, -18]];
  for (const [dx, dy] of boxes) {
    const bx = x + dx;
    const by = floorY + dy;
    contactShadow(ctx, bx + 14, by + 2, 15, 1, 0.35);
    slab(ctx, bx, by - 18, 28, 18, MAT.oak.map((c) => mix(c, '#c8a060', 0.2)));
    px(ctx, bx + 4, by - 13, 20, 1, MAT.oak[0]);
    px(ctx, bx + 10, by - 10, 8, 3, MAT.oak[0]);
    px(ctx, bx + 6, by - 7, 16, 1, withAlpha(MAT.paper[3], 0.6));
  }
}

function awardsShelf(ctx, x, y, w) {
  px(ctx, x - 1, y + 14, w + 2, 4, AMBIENT.shadow);
  px(ctx, x, y + 14, w, 3, MAT.walnut[3]);
  px(ctx, x, y + 14, w, 1, MAT.walnut[4]);
  for (let i = 0; i < 3; i += 1) {
    const ax = x + 10 + i * 22;
    px(ctx, ax - 1, y - 1, 10, 16, AMBIENT.shadow);
    px(ctx, ax, y, 8, 9, MAT.brass[3]);
    px(ctx, ax, y, 3, 9, MAT.brass[4]);
    px(ctx, ax + 6, y, 2, 9, MAT.brass[1]);
    px(ctx, ax + 2, y + 9, 4, 3, MAT.brass[2]);
    px(ctx, ax - 1, y + 12, 10, 2, MAT.black[2]);
  }
}

function deskPhone(ctx, x, y) {
  px(ctx, x - 1, y - 6, 16, 7, AMBIENT.shadow);
  px(ctx, x, y - 5, 14, 5, MAT.black[2]);
  px(ctx, x, y - 5, 14, 1, MAT.black[4]);
  px(ctx, x + 1, y - 8, 12, 3, MAT.black[3]);
  px(ctx, x + 2, y - 3, 3, 2, UI.green);
}

function storyboardWall(ctx, x, y, w, h, rnd) {
  px(ctx, x - 2, y - 2, w + 4, h + 4, AMBIENT.shadow);
  px(ctx, x - 1, y - 1, w + 2, h + 2, MAT.oak[3]);
  px(ctx, x, y, w, h, '#9c7a52');
  for (let i = 0; i < w * h * 0.02; i += 1) px(ctx, x + rnd() * w, y + rnd() * h, 1, 1, '#8a6a44');
  const frames = 5;
  for (let i = 0; i < frames; i += 1) {
    const fx = x + 8 + i * 34;
    const fy = y + 8 + (i % 2) * 22;
    px(ctx, fx + 1, fy + 1, 28, 18, withAlpha(AMBIENT.shadow, 0.35));
    px(ctx, fx, fy, 28, 18, MAT.paper[4]);
    px(ctx, fx + 2, fy + 2, 24, 10, pick([['#3a5a8a', '#8ab0d0'], ['#5a3a4a', '#c08a9a'], ['#3a5a3a', '#8ac08a']], rnd)[i % 2 ? 1 : 0]);
    px(ctx, fx + 2, fy + 8, 24, 4, '#5a4a3a');
    px(ctx, fx + 3, fy + 14, 18, 1, '#8a8070');
    px(ctx, fx + 13, fy - 1, 2, 2, '#e04a4a');
  }
  ctx.strokeStyle = 'rgba(224,74,74,0.6)';
  ctx.beginPath();
  for (let i = 0; i < frames - 1; i += 1) {
    ctx.moveTo(x + 22 + i * 34 + 0.5, y + 8 + (i % 2) * 22 + 0.5);
    ctx.lineTo(x + 22 + (i + 1) * 34 + 0.5, y + 8 + ((i + 1) % 2) * 22 + 0.5);
  }
  ctx.stroke();
}

function floorLamp(ctx, x, floorY, live, color) {
  contactShadow(ctx, x, floorY + 2, 8, 1, 0.35);
  px(ctx, x - 8, floorY - 3, 16, 3, MAT.brass[1]);
  px(ctx, x - 1, floorY - 78, 3, 76, MAT.brass[1]);
  px(ctx, x, floorY - 78, 1, 76, MAT.brass[3]);
  px(ctx, x - 12, floorY - 92, 25, 15, AMBIENT.shadow);
  px(ctx, x - 11, floorY - 91, 23, 13, '#c8a074');
  px(ctx, x - 11, floorY - 91, 23, 1, '#e8c898');
  px(ctx, x - 11, floorY - 79, 23, 1, '#8a6a4a');
  px(ctx, x - 9, floorY - 78, 19, 1, '#fff0c8');
  live.lamps.push({ x, y: floorY - 76, r: 70, color: rgba(color, 0.3) });
}

function typewriterCorner(ctx, x, floorY) {
  // A small side table with a typewriter and a stack of drafts.
  contactShadow(ctx, x + 18, floorY + 2, 20, 1, 0.35);
  px(ctx, x - 1, floorY - 21, 38, 4, AMBIENT.shadow);
  px(ctx, x, floorY - 20, 36, 3, MAT.oak[3]);
  px(ctx, x, floorY - 20, 36, 1, MAT.oak[4]);
  px(ctx, x + 2, floorY - 17, 2, 17, MAT.oak[1]);
  px(ctx, x + 32, floorY - 17, 2, 17, MAT.oak[1]);
  px(ctx, x + 5, floorY - 33, 20, 14, AMBIENT.shadow);
  px(ctx, x + 6, floorY - 32, 18, 12, MAT.fabricOlive[2]);
  px(ctx, x + 6, floorY - 32, 18, 1, MAT.fabricOlive[4]);
  px(ctx, x + 8, floorY - 36, 14, 4, MAT.paper[4]);
  for (let k = 0; k < 4; k += 1) px(ctx, x + 8 + k * 4, floorY - 25, 2, 1, MAT.paper[3]);
  px(ctx, x + 26, floorY - 24, 8, 4, MAT.paper[3]);
  px(ctx, x + 27, floorY - 26, 8, 2, MAT.paper[4]);
}

function vocalBooth(ctx, zone, live, wallTop, floorY, rnd) {
  const bw = 156;
  const bx = zone.x + zone.width - bw - 14;
  const by = wallTop + 6;
  const bh = floorY - by;
  // Glass-fronted booth: dark interior, foam already on the wall, a glazed panel.
  px(ctx, bx - 2, by - 2, bw + 4, bh + 2, AMBIENT.shadow);
  px(ctx, bx, by, bw, bh, MAT.foam[0]);
  for (let fy = by + 4; fy < floorY - 6; fy += 8) {
    for (let fx = bx + 4; fx < bx + bw - 6; fx += 8) {
      px(ctx, fx, fy, 7, 7, rnd() > 0.5 ? MAT.foam[1] : MAT.foam[0]);
      px(ctx, fx, fy, 7, 1, MAT.foam[2]);
    }
  }
  // Window frame with the glass.
  const gx = bx + 14;
  px(ctx, gx - 2, by + 10, 60, bh - 40, MAT.steel[1]);
  ctx.save();
  ctx.globalAlpha = 0.28;
  px(ctx, gx, by + 12, 56, bh - 44, MAT.glass[3]);
  ctx.globalAlpha = 0.12;
  ctx.fillStyle = '#ffffff';
  ctx.beginPath();
  ctx.moveTo(gx, by + 12);
  ctx.lineTo(gx + 26, by + 12);
  ctx.lineTo(gx, by + 40);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
  // ON AIR sign above the booth door.
  live.onAir.push({ x: bx + bw - 60, y: by + 6, zoneId: zone.id });
  // Booth door frame on the room side.
  px(ctx, bx, by, 4, bh, MAT.steel[2]);
  px(ctx, bx, by, 1, bh, MAT.steel[4]);
}

function speakerStand(ctx, x, floorY) {
  contactShadow(ctx, x + 10, floorY + 2, 10, 1, 0.35);
  px(ctx, x + 8, floorY - 30, 4, 30, MAT.steel[1]);
  px(ctx, x + 9, floorY - 30, 1, 30, MAT.steel[3]);
  px(ctx, x + 2, floorY - 2, 16, 2, MAT.steel[1]);
  slab(ctx, x, floorY - 52, 20, 22, MAT.black);
  px(ctx, x + 4, floorY - 47, 12, 12, MAT.black[0]);
  px(ctx, x + 7, floorY - 44, 6, 6, MAT.black[3]);
  px(ctx, x + 8, floorY - 43, 2, 2, MAT.black[4]);
  px(ctx, x + 7, floorY - 33, 6, 2, MAT.black[0]);
}

function guitarOnWall(ctx, x, y) {
  px(ctx, x + 5, y, 3, 30, MAT.walnut[2]);
  px(ctx, x + 6, y, 1, 30, MAT.walnut[3]);
  px(ctx, x + 1, y + 28, 11, 14, AMBIENT.shadow);
  px(ctx, x + 2, y + 29, 9, 12, '#c04a3a');
  px(ctx, x + 2, y + 29, 9, 1, '#e87a60');
  px(ctx, x + 5, y + 33, 3, 3, MAT.black[1]);
}

function shortsPoster(ctx, x, y, accent) {
  px(ctx, x - 2, y - 2, 60, 66, AMBIENT.shadow);
  px(ctx, x - 1, y - 1, 58, 64, MAT.steel[3]);
  px(ctx, x, y, 56, 62, '#141a2a');
  px(ctx, x + 4, y + 4, 48, 54, '#1c2a44');
  px(ctx, x + 4, y + 34, 48, 24, '#2c3a5c');
  drawText(ctx, 'SHORTS', x + 8, y + 8, '#8ab8e0', 1, 1);
  drawText(ctx, '9:16', x + 10, y + 18, accent, 2, 1);
  px(ctx, x + 10, y + 38, 36, 14, '#0e1420');
  px(ctx, x + 14, y + 41, 28, 8, mix(accent, '#ffffff', 0.2));
  px(ctx, x + 4, y + 56, 48, 2, accent);
}

function driveStack(ctx, x, floorY, live, accent) {
  contactShadow(ctx, x + 22, floorY + 2, 24, 2, 0.4);
  for (let i = 0; i < 4; i += 1) {
    const dy = floorY - 2 - i * 10;
    slab(ctx, x, dy - 9, 44, 9, MAT.steel);
    px(ctx, x + 4, dy - 6, 24, 3, MAT.steel[0]);
    live.leds.push({ x: x + 36, y: dy - 6, color: accent, phase: i * 0.7, rate: 2.4 });
  }
}

function lightStand(ctx, x, floorY, live) {
  contactShadow(ctx, x, floorY + 2, 8, 1, 0.35);
  px(ctx, x - 1, floorY - 86, 3, 84, MAT.steel[1]);
  px(ctx, x, floorY - 86, 1, 84, MAT.steel[3]);
  px(ctx, x - 9, floorY - 3, 19, 3, MAT.steel[1]);
  px(ctx, x - 12, floorY - 100, 26, 16, AMBIENT.shadow);
  px(ctx, x - 11, floorY - 99, 24, 14, MAT.steel[2]);
  px(ctx, x - 9, floorY - 97, 20, 10, '#fff8e0');
  px(ctx, x - 9, floorY - 97, 20, 1, '#ffffff');
  live.lamps.push({ x, y: floorY - 88, r: 60, color: 'rgba(255,248,224,0.32)' });
}

function serverRoom(ctx, zone, live, desks, wallTop, floorY, rnd) {
  // Racks from the backend desk list. Each rack: a steel cabinet, glass door, blade rows.
  for (const d of desks) {
    const rx = d.x - 26;
    const rh = 92;
    const ry = floorY - rh;
    contactShadow(ctx, d.x, floorY + 2, 30, 2, 0.5);
    slab(ctx, rx, ry, 52, rh, MAT.steel);
    px(ctx, rx + 3, ry + 3, 46, rh - 6, MAT.black[1]);
    for (let u = 0; u < 10; u += 1) {
      const uy = ry + 6 + u * 8;
      px(ctx, rx + 5, uy, 42, 6, MAT.black[2]);
      px(ctx, rx + 5, uy, 42, 1, MAT.black[3]);
      for (let l = 0; l < 4; l += 1) {
        live.leds.push({
          x: rx + 8 + l * 4, y: uy + 2,
          color: l === 0 ? UI.green : l === 3 ? UI.amber : '#4ac0a0',
          phase: (u * 4 + l) * 0.37 + d.x, rate: 3.1 + (l % 3) * 1.4,
        });
      }
      px(ctx, rx + 28, uy + 2, 16, 2, MAT.black[0]);
    }
    // Glass door sheen.
    ctx.save();
    ctx.globalAlpha = 0.1;
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.moveTo(rx + 3, ry + 3);
    ctx.lineTo(rx + 24, ry + 3);
    ctx.lineTo(rx + 3, ry + 40);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
    const caption = String(d.name || '').replace(/[^A-Za-z0-9 ]/g, '').slice(0, 9).toUpperCase();
    const cw = textWidth(caption, 1, 1) + 8;
    px(ctx, d.x - cw / 2 - 1, ry - 13, cw + 2, 12, AMBIENT.shadow);
    px(ctx, d.x - cw / 2, ry - 12, cw, 10, UI.chip);
    drawText(ctx, caption, d.x - cw / 2 + 4, ry - 10, UI.green, 1, 1);
    live.fans.push({ x: d.x, y: ry - 20, r: 6, rate: 4 + (d.x % 3) });
    live.lamps.push({ x: d.x, y: ry + 40, r: 50, color: 'rgba(127,240,138,0.14)' });
  }
  // Overhead cable trays and a cooling unit on the wall.
  px(ctx, zone.x + zone.width - 60, wallTop + 46, 44, 26, AMBIENT.shadow);
  px(ctx, zone.x + zone.width - 59, wallTop + 47, 42, 24, MAT.steel[2]);
  px(ctx, zone.x + zone.width - 59, wallTop + 47, 42, 1, MAT.steel[4]);
  for (let vy = wallTop + 51; vy < wallTop + 68; vy += 3) px(ctx, zone.x + zone.width - 55, vy, 34, 1, MAT.steel[0]);
  live.leds.push({ x: zone.x + zone.width - 22, y: wallTop + 67, color: UI.green, phase: 0, rate: 1 });
  // Raised-floor vent tiles.
  for (let vx = zone.x + 12; vx < zone.x + zone.width - 12; vx += 48) px(ctx, vx, floorY + 3, 12, 2, MAT.steel[0]);
}

function lounge(ctx, zone, live, wallTop, floorY, rnd, seed) {
  const x = zone.x;
  rug(ctx, x + 6, floorY, 96, [MAT.fabricRed[0], MAT.fabricRed[2], MAT.brass[3]]);
  sofa(ctx, x + 12, floorY, 80, MAT.felt);
  // Espresso bar along the wall: counter, machine, cups, a neon-ish menu board.
  const bar = x + zone.width - 100;
  px(ctx, bar - 1, floorY - 31, 90, 32, AMBIENT.shadow);
  px(ctx, bar, floorY - 30, 88, 30, MAT.walnut[2]);
  px(ctx, bar, floorY - 30, 88, 3, MAT.ceramic[3]);
  px(ctx, bar, floorY - 30, 88, 1, MAT.ceramic[4]);
  px(ctx, bar, floorY - 27, 88, 1, MAT.walnut[0]);
  for (let sx = bar + 6; sx < bar + 84; sx += 12) px(ctx, sx, floorY - 24, 1, 22, MAT.walnut[1]);
  const eX = bar + 8;
  slab(ctx, eX, floorY - 58, 34, 28, MAT.chrome);
  px(ctx, eX + 4, floorY - 52, 26, 10, MAT.black[1]);
  px(ctx, eX + 8, floorY - 42, 6, 8, MAT.chrome[4]);
  px(ctx, eX + 22, floorY - 48, 8, 4, '#e04a4a');
  live.steam.push({ x: eX + 11, y: floorY - 44, zoneId: zone.id });
  for (let i = 0; i < 4; i += 1) px(ctx, bar + 50 + i * 8, floorY - 36, 6, 5, MAT.ceramic[3]);
  // Menu board.
  px(ctx, bar + 12, wallTop + 44, 60, 34, AMBIENT.shadow);
  px(ctx, bar + 13, wallTop + 45, 58, 32, MAT.black[1]);
  drawText(ctx, 'CAFE', bar + 18, wallTop + 49, '#ffcf7a', 1, 1);
  for (let i = 0; i < 3; i += 1) px(ctx, bar + 18, wallTop + 59 + i * 5, 30 + i * 6, 1, '#8a8aa0');
  // Water cooler and plants.
  const wX = x + zone.width - 124;
  slab(ctx, wX, floorY - 46, 20, 46, MAT.steel);
  px(ctx, wX + 2, floorY - 62, 16, 18, MAT.glass[3]);
  px(ctx, wX + 2, floorY - 62, 16, 1, MAT.glass[4]);
  px(ctx, wX + 3, floorY - 61, 3, 16, MAT.glass[4]);
  live.bubbles.push({ x: wX + 10, y: floorY - 54, zoneId: zone.id });
  plant(ctx, x + zone.width - 134, floorY, seed + 2, 1.1);
  // Pinboard and a wall clock.
  pinboard(ctx, x + 24, wallTop + 46, 80, 40, rnd);
  wallClockFace(ctx, live, x + 124, wallTop + 60);
}

function pinboard(ctx, x, y, w, h, rnd) {
  px(ctx, x - 2, y - 2, w + 4, h + 4, AMBIENT.shadow);
  px(ctx, x - 1, y - 1, w + 2, h + 2, MAT.oak[3]);
  px(ctx, x, y, w, h, '#8a6a48');
  for (let i = 0; i < 6; i += 1) {
    const nx = x + 6 + (i % 3) * 24;
    const ny = y + 6 + Math.floor(i / 3) * 18;
    px(ctx, nx, ny, 18, 13, pick(['#f4d86a', '#8ad8b0', '#f0a0a0', MAT.paper[4]], rnd));
    px(ctx, nx + 8, ny - 1, 2, 2, '#e04a4a');
  }
}

function dispatchBoard(ctx, zone, live, wallTop, rnd, dept) {
  const bw = Math.min(zone.width - 40, 120);
  const bx = zone.x + zone.width / 2 - bw / 2;
  const by = wallTop + 46;
  px(ctx, bx - 2, by - 2, bw + 4, 50, AMBIENT.shadow);
  px(ctx, bx - 1, by - 1, bw + 2, 48, MAT.steel[3]);
  px(ctx, bx, by, bw, 46, MAT.black[1]);
  px(ctx, bx + 4, by + 4, bw - 8, 9, MAT.black[2]);
  drawText(ctx, 'DISPATCH', bx + 8, by + 6, dept.accent, 1, 1);
  for (let r = 0; r < 3; r += 1) {
    const ry = by + 17 + r * 9;
    px(ctx, bx + 6, ry, bw - 44, 6, MAT.black[2]);
    px(ctx, bx + bw - 34, ry, 26, 6, MAT.black[2]);
    live.leds.push({ x: bx + bw - 14, y: ry + 2, color: UI.amber, phase: r * 1.1, rate: 1.4 });
  }
}

function crateShelf(ctx, x, floorY) {
  contactShadow(ctx, x + 28, floorY + 2, 30, 2, 0.4);
  slab(ctx, x, floorY - 44, 56, 44, MAT.steel);
  for (let r = 0; r < 2; r += 1) {
    for (let c = 0; c < 2; c += 1) {
      const cx = x + 4 + c * 26;
      const cy = floorY - 40 + r * 20;
      px(ctx, cx, cy, 22, 16, r === c ? MAT.oak[2] : MAT.oak[1]);
      px(ctx, cx, cy, 22, 1, MAT.oak[4]);
      px(ctx, cx + 4, cy + 6, 14, 3, MAT.oak[0]);
      if (r === 0 && c === 0) px(ctx, cx + 6, cy + 3, 8, 2, '#e04a4a');
    }
  }
}

function shopFront(ctx, zone, live, wallTop, floorY, rnd, dept) {
  const x = zone.x;
  const w = zone.width;
  // Awning across the top, a glazed front behind it, a counter and rate boards.
  const glassTop = wallTop + 22;
  const glassH = floorY - glassTop - 8;
  px(ctx, x + 8, glassTop - 2, w - 16, glassH + 4, AMBIENT.shadow);
  px(ctx, x + 10, glassTop, w - 20, glassH, MAT.glass[1]);
  ctx.save();
  ctx.globalAlpha = 0.18;
  ctx.fillStyle = MAT.glass[4];
  ctx.beginPath();
  ctx.moveTo(x + 10, glassTop);
  ctx.lineTo(x + 10 + (w - 20) * 0.5, glassTop);
  ctx.lineTo(x + 10, glassTop + glassH * 0.9);
  ctx.closePath();
  ctx.fill();
  ctx.restore();
  px(ctx, x + w / 2 - 2, glassTop, 4, glassH, FACADE.mullion[3]);
  px(ctx, x + 10, glassTop, w - 20, 2, FACADE.mullion[4]);
  for (let i = 0; i < Math.floor((w - 16) / 22); i += 1) {
    const ax = x + 8 + i * 22;
    px(ctx, ax, wallTop + 6, 22, 14, i % 2 ? '#c8483a' : MAT.paper[3]);
    px(ctx, ax, wallTop + 6, 22, 1, i % 2 ? '#e87a60' : MAT.paper[4]);
    px(ctx, ax, wallTop + 18, 22, 2, i % 2 ? '#7a2a22' : MAT.paper[1]);
  }
  px(ctx, x + 8, wallTop + 20, w - 16, 1, AMBIENT.shadow);
  const sign = 'AD SPACE';
  const sw = textWidth(sign, 2, 1);
  px(ctx, x + (w - sw) / 2 - 8, glassTop + 6, sw + 16, 20, AMBIENT.shadow);
  px(ctx, x + (w - sw) / 2 - 7, glassTop + 7, sw + 14, 18, MAT.black[1]);
  drawText(ctx, sign, x + (w - sw) / 2, glassTop + 11, dept.accent, 2, 1);
  live.lamps.push({ x: x + w / 2, y: glassTop + 16, r: 60, color: rgba(dept.accent, 0.22) });
  for (let i = 0; i < 3; i += 1) {
    const bx = x + 22 + i * 46;
    slab(ctx, bx, glassTop + 36, 36, 46, MAT.steel);
    px(ctx, bx + 3, glassTop + 40, 30, 20, pick(['#4a5c88', '#8a4a5a', '#4f8a5a'], rnd));
    px(ctx, bx + 3, glassTop + 63, 24, 3, MAT.paper[3]);
    px(ctx, bx + 3, glassTop + 69, 18, 3, MAT.paper[1]);
    px(ctx, bx + 3, glassTop + 75, 12, 3, dept.accent);
  }
  // Counter with a till and a stool.
  contactShadow(ctx, x + 56, floorY + 2, 42, 2, 0.4);
  px(ctx, x + 17, floorY - 33, 80, 34, AMBIENT.shadow);
  px(ctx, x + 18, floorY - 32, 78, 32, MAT.walnut[2]);
  px(ctx, x + 18, floorY - 32, 78, 3, MAT.ceramic[3]);
  px(ctx, x + 18, floorY - 32, 78, 1, MAT.ceramic[4]);
  px(ctx, x + 18, floorY - 29, 78, 1, MAT.walnut[0]);
  slab(ctx, x + 62, floorY - 46, 22, 12, MAT.black);
  px(ctx, x + 65, floorY - 43, 16, 6, '#7fd8b0');
  plant(ctx, x + w - 26, floorY, hash32(zone.id) + 21, 1);
}

function mixingDesk(ctx, s, live, zoneId) {
  const y = s.deskTop;
  const x = s.seatX - 6;
  px(ctx, x - 1, y - 1, 46, 8, AMBIENT.shadow);
  px(ctx, x, y, 44, 6, MAT.black[2]);
  px(ctx, x, y, 44, 1, MAT.black[4]);
  for (let f = 0; f < 8; f += 1) {
    px(ctx, x + 3 + f * 5, y + 1, 1, 4, MAT.black[0]);
    px(ctx, x + 2 + f * 5, y + 1 + (f % 3), 3, 1, f % 2 ? '#e0e0e8' : '#ff9a5c');
  }
  live.vuMeters.push({ x: x + 2, y: y - 9, w: 40, h: 7, zoneId });
}

function boomMic(ctx, x, deskTop) {
  px(ctx, x, deskTop - 40, 2, 40, MAT.black[2]);
  px(ctx, x + 1, deskTop - 40, 1, 40, MAT.black[3]);
  px(ctx, x - 18, deskTop - 40, 20, 2, MAT.black[2]);
  px(ctx, x - 22, deskTop - 39, 6, 12, AMBIENT.shadow);
  px(ctx, x - 21, deskTop - 38, 4, 10, MAT.chrome[2]);
  px(ctx, x - 21, deskTop - 38, 1, 10, MAT.chrome[4]);
  px(ctx, x - 21, deskTop - 34, 4, 1, MAT.chrome[0]);
  px(ctx, x - 26, deskTop - 37, 2, 8, MAT.black[3]);
}

function gradingPanel(ctx, x, y) {
  px(ctx, x - 1, y - 1, 34, 6, AMBIENT.shadow);
  px(ctx, x, y, 32, 4, MAT.black[2]);
  px(ctx, x, y, 32, 1, MAT.black[4]);
  for (let t = 0; t < 3; t += 1) {
    px(ctx, x + 4 + t * 10, y, 6, 3, MAT.chrome[2]);
    px(ctx, x + 5 + t * 10, y, 2, 1, MAT.chrome[4]);
  }
}

/* ============================================================================
   Fillers: wall runs between fixed props, seeded per zone so floors differ but never shuffle.
   ========================================================================== */

export function fillZone(ctx, zone, live, interior = null) {
  const dept = department(zone.zone_type);
  const floorY = floorLine(zone);
  const rnd = mulberry32(hash32(`fill${zone.id}`));
  const occupied = (interior && interior.occupied) || (zone.desks || []).map((d) => [d.x - 64, d.x + 64]);
  const clear = (x, w) => occupied.every(([a, b]) => x + w < a || x > b);
  const wallTop = zone.y + CEILING_H;
  const exitX = (zone.floorRight ?? zone.x + zone.width) - 34;
  const premium = usesAtlas(zone);
  const useProp = (name) => premium && propReady(name);

  if (zone.zone_type === 'SERVER' || zone.zone_type === 'SHOP' || zone.zone_type === 'LOUNGE') {
    if (zone.isFloorLead) exitSign(ctx, exitX, wallTop + 6);
    return;
  }

  // Scan the wall in small steps; drop a prop wherever a 40px span is free.
  let placed = 0;
  for (let x = zone.x + 96; x < zone.x + zone.width - 76 && placed < 7; x += 8) {
    if (!clear(x, 40)) continue;
    if (rnd() > 0.55) { x += 16; continue; }
    occupied.push([x - 6, x + 46]);
    placed += 1;
    const roll = rnd();
    if (roll < 0.2) {
      if (useProp('filing_cabinet')) placeProp(ctx, 'filing_cabinet', x, floorY);
      else filingCabinet(ctx, x, floorY, dept.accent);
    } else if (roll < 0.35) {
      const size = 0.8 + rnd() * 0.5;
      if (useProp('plant_small')) placeProp(ctx, size > 1.05 ? 'plant_large' : 'plant_small', x + 12, floorY);
      else plant(ctx, x + 12, floorY, hash32(`p${zone.id}${x}`), size);
    } else if (roll < 0.45) {
      if (useProp('coat_stand')) placeProp(ctx, 'coat_stand', x + 10, floorY);
      else coatStand(ctx, x + 10, floorY, hash32(`c${zone.id}${x}`));
    } else if (roll < 0.58) {
      if (useProp('bin')) placeProp(ctx, 'bin', x + 6, floorY);
      else bin(ctx, x + 6, floorY);
    } else if (roll < 0.68) {
      if (useProp('extinguisher')) placeProp(ctx, 'extinguisher', x + 8, floorY);
      else extinguisher(ctx, x + 8, floorY);
    } else if (roll < 0.9) {
      const py = wallTop + 14 + Math.floor(rnd() * 10);
      const which = hash32(`po${zone.id}${x}`) % 2 ? 'poster_a' : 'poster_b';
      if (useProp(which)) drawProp(ctx, which, x, py);
      else poster(ctx, x, py, hash32(`po${zone.id}${x}`), dept.accent);
    } else if (useProp('wall_shelf')) {
      drawProp(ctx, 'wall_shelf', x, wallTop + 30);
    } else {
      wallShelf(ctx, x, wallTop + 30, hash32(`sh${zone.id}${x}`));
    }
  }

  // A whiteboard on the right of most floors, where the wall is free.
  const wbX = zone.x + zone.width - 150;
  if (clear(wbX, 110) && zone.zone_type !== 'AUDIO' && zone.zone_type !== 'DIRECTOR' && zone.zone_type !== 'SCRIPT') {
    if (useProp('whiteboard')) drawProp(ctx, 'whiteboard', wbX, wallTop + 14);
    else whiteboard(ctx, wbX, wallTop + 14, 104, 48, dept.accent, hash32(`wb${zone.id}`));
  }
  if (zone.isFloorLead) exitSign(ctx, exitX, wallTop + 6);

  // Sockets along the skirting (the atlas wall tile carries its own).
  if (premium && propReady(`wall_${zone.zone_type}_h${floorY - wallTop}`)) return;
  for (let x = zone.x + 40; x < zone.x + zone.width - 30; x += 96) {
    px(ctx, x, floorY - 8, 5, 4, MAT.ceramic[2]);
    px(ctx, x + 1, floorY - 7, 1, 2, MAT.black[1]);
    px(ctx, x + 3, floorY - 7, 1, 2, MAT.black[1]);
  }
}
