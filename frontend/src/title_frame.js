import { timeOfDay } from './hq_time.js';
import { plateDayMix } from './hq_world.js';

/**
 * THE TITLE SCREEN'S ARITHMETIC. Pure, so the node tests can hold the composition, the light and
 * the entry to their rules without a browser.
 *
 * The frame is the studio's own world: the Blender plates the office renderer composites
 * (public/assets/hq/plates/plates.json), laid out as depth layers behind the sign-in. Nothing in it
 * is invented for the title: the sky is the office's own sky renderer at the real Bucharest sun,
 * the plates are the office's plates crossfaded by the same plateDayMix, and the only motion is
 * the pointer's (parallax) and the camera's on a real sign-in (the entry).
 */

/** The plate world, in world px (plates.json "world"). */
export const WORLD = { width: 1600, height: 840 };

/** The headquarters' outer shell in world px (plates.json building_shell). */
export const BUILDING = { x: 412.5, y: 0, w: 943, h: 669.5 };

/**
 * The depth layers, far to near, and how far each one follows the pointer (0 the sky, 1 the
 * kerb-side foreground). The grouping is the renderer's (hq_world.js PLATE_GROUPS) with the city
 * and the far street split, so the skyline sits behind the street as it does in the world.
 * @type {Array<{name: string, layers: string[], depth: number, grade: boolean}>}
 */
export const TITLE_LAYERS = [
  { name: 'city', layers: ['city'], depth: 0.1, grade: true },
  { name: 'street_far', layers: ['street_back', 'street_ground'], depth: 0.3, grade: true },
  { name: 'building', layers: ['building_back', 'building_front', 'building_shell'], depth: 0.5, grade: false },
  { name: 'street_props', layers: ['street_props'], depth: 0.72, grade: true },
  { name: 'street_kerb', layers: ['street_kerb'], depth: 0.86, grade: true },
  { name: 'street_front', layers: ['street_front'], depth: 1, grade: true },
];

/** The foot of the kerb (plates.json street_kerb, y 683 + 35): the street a frame must keep. */
export const KERB_FOOT = 720;

/** The most a layer at depth 1 travels from its rest, in screen px, at the frame's edge. */
export const PARALLAX_MAX = 14;
/** Screen px of world kept beyond every edge, so a layer at full travel never shows its edge. */
export const OVERSCAN = PARALLAX_MAX + 4;

/**
 * Where the world sits on a screen of vw x vh, as a key-art frame: the headquarters stands in the
 * right of the frame with a band of sky above its roof, and the left of the frame is kept for the
 * brand and the key. The city always runs off both sides of the screen (the scale never drops
 * below the screen's width), and the world's foot never lifts off the bottom edge. On a narrow,
 * tall screen the building is centred at the foot of the screen and the words stand above it.
 * @param {number} vw
 * @param {number} vh
 * @returns {{scale: number, x: number, y: number, layout: 'side'|'stacked', building: {x:number, y:number, w:number, h:number}}}
 */
export function titleFrame(vw, vh) {
  const width = Math.max(1, vw);
  const height = Math.max(1, vh);
  const stacked = width < 900 || width / height < 1.1;
  // the city runs off both sides, with room for the parallax
  const cover = (width + 2 * OVERSCAN) / WORLD.width;
  // the roof keeps a margin of sky above it
  const roof = height * (stacked ? 0.06 : 0.08);
  // and the kerb (world y 720) stays on screen under a roof held at that margin
  const tallest = (height - roof) / KERB_FOOT;
  const wanted = stacked
    ? Math.min((width * 0.92) / BUILDING.w, (height * 0.5) / BUILDING.h)
    : (width * 0.94) / (BUILDING.x + BUILDING.w); // the right wall a little inside the edge
  const scale = Math.max(cover, Math.min(wanted, tallest));
  const centred = width / 2 - (BUILDING.x + BUILDING.w / 2) * scale;
  // the world never leaves a gap on either side
  const x = Math.min(-OVERSCAN, Math.max(width + OVERSCAN - WORLD.width * scale, stacked ? centred : -OVERSCAN));
  // the world stands on the floor of the screen, unless that would cut the roof: then the roof
  // keeps its margin and the street runs off the bottom instead
  const standing = height + OVERSCAN - WORLD.height * scale;
  const y = Math.max(standing, roof);
  return {
    scale,
    x,
    y,
    layout: stacked ? 'stacked' : 'side',
    building: { x: x + BUILDING.x * scale, y: y + BUILDING.y * scale, w: BUILDING.w * scale, h: BUILDING.h * scale },
  };
}

/**
 * How far a layer at `depth` is moved for a pointer at (px, py) on a vw x vh screen: toward the
 * side the pointer is on, far layers less than near ones, never more than PARALLAX_MAX.
 * @param {{x:number, y:number}} pointer in screen px
 * @param {number} depth 0..1
 * @param {number} vw @param {number} vh
 */
export function parallaxOffset(pointer, depth, vw, vh) {
  const nx = Math.max(-1, Math.min(1, (pointer.x / Math.max(1, vw)) * 2 - 1));
  const ny = Math.max(-1, Math.min(1, (pointer.y / Math.max(1, vh)) * 2 - 1));
  // the far city moves least; vertical travel is half the horizontal, as a head moves
  return { x: -nx * PARALLAX_MAX * depth, y: -ny * PARALLAX_MAX * 0.5 * depth };
}

/**
 * One step of the lag a layer follows the pointer with: it closes a fixed share of the distance
 * each frame, time-corrected, and stops once it is within a tenth of a pixel. Returns null when
 * it has arrived, so the loop can stop drawing.
 * @param {{x:number, y:number}} current @param {{x:number, y:number}} target @param {number} dtMs
 */
export function followPointer(current, target, dtMs) {
  const k = 1 - Math.pow(0.001, Math.max(0, dtMs) / 900);
  const x = current.x + (target.x - current.x) * k;
  const y = current.y + (target.y - current.y) * k;
  if (Math.abs(target.x - x) < 0.1 && Math.abs(target.y - y) < 0.1) return null;
  return { x, y };
}

/**
 * The title's light for a real instant, from the same sun the office uses (hq_time.js timeOfDay)
 * and the same plate crossfade (hq_world.js plateDayMix). `grade` is the renderer's deep-night
 * multiply (drawNightGrade): 0 until the sun is 8 degrees down, 1 at 18 degrees down.
 * @param {Date} date
 */
export function titleLight(date) {
  const time = timeOfDay(date);
  const dayMix = plateDayMix(time.daylight);
  const grade = Math.max(0, Math.min(1, (-time.elevation - 8) / 10));
  // the renderer multiplies by rgba(70,84,130, .45*grade) outside the building
  const multiply = [70, 84, 130].map((c) => Math.round((1 - 0.45 * grade * (1 - c / 255)) * 1000) / 1000);
  return {
    time,
    dayMix,
    grade,
    multiply,
    needsNight: dayMix < 0.999,
    needsDay: dayMix > 0.001,
  };
}

/** How long the camera takes to go into the building, and how the panels arrive after it. */
export const ENTRY = {
  /** the whole entry, from the accepted key to the last panel at rest (--arrive-first + 4 steps + --dur-arrive) */
  totalMs: 820,
  /** the camera's push into the headquarters (--dur-push) */
  pushMs: 700,
  /** when the first panel starts to arrive (--arrive-first) */
  firstPanelMs: 260,
  /** between one panel and the next (--arrive-step) */
  stepMs: 60,
  /** how long one panel takes to arrive (--dur-arrive) */
  panelMs: 320,
  /** how far into the building the camera goes (--push-scale) */
  pushScale: 1.9,
};

/**
 * Whether the camera may move on this sign-in. It moves only for a key the backend accepted, and
 * never for a visitor who asked the system for less motion: they get the same workspace at once.
 * @param {{accepted: boolean, reducedMotion: boolean, titleShown: boolean}} state
 */
export function entryPlays(state) {
  return Boolean(state.accepted && state.titleShown && !state.reducedMotion);
}

/**
 * The point the camera pushes toward, in screen px: the middle of the headquarters' floors (the
 * office floors, not the roof sign), which is where the render the workspace opens on is.
 * @param {ReturnType<typeof titleFrame>} frame
 */
export function entryOrigin(frame) {
  return { x: frame.building.x + frame.building.w * 0.5, y: frame.building.y + frame.building.h * 0.56 };
}

/**
 * The line under the key-art, stating the one thing the picture claims: the light is the real
 * hour in Bucharest. The hour is the one the office's clock uses (office_clock.js).
 * @param {{text: string, phase: string}} time
 */
export function titleCaption(time) {
  const phase = { day: 'zi', dawn: 'zori', dusk: 'amurg', night: 'noapte' }[time.phase] || '';
  return `Sediul AMN-AI, București · ${time.text}${phase ? ` · ${phase}` : ''}, în lumina reală a orei`;
}
