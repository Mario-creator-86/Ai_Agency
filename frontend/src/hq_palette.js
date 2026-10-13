/**
 * THE RENDERER'S INTERFACE PALETTE (2026-09-23)
 *
 * The page draws the headquarters itself whenever the Unreal stream is not running, and what it
 * draws is two different things at once:
 *
 *   THE ART — the building, the city, the street, the sky, the light, the screens on the walls,
 *   the vehicles, the billboard. That is the Owner's art direction. Its colours live where they
 *   are painted, in hq_world.js and hq_sky.js, and nothing in this file touches them.
 *
 *   THE INTERFACE — the marks the page lays over the art so the Owner can work with it: the ring
 *   round the employee under his pointer, the ring round the one he has selected, the name tag
 *   under each, the speech captions, and the note the scene shows while it is loading or when its
 *   art could not be read. Those are chrome, and before this pass they carried their own literals
 *   (a teal that was not the page's teal, a slate that was not the page's ink) — a second colour
 *   system inside the hero of the page.
 *
 * This module is the one place the renderer asks the page what its colours are. It reads the token
 * block at the top of frontend/src/style.css through the live custom properties, so a token that
 * changes there changes the scene's chrome in the same commit and there is nothing to keep in
 * step by hand. The FALLBACK values below are the same tokens written out, for the tests and for
 * any frame drawn before the stylesheet has arrived; they are a copy, and if a token named here
 * is edited in style.css it must be edited here too.
 */

/** The tokens the scene's chrome uses, and their value in style.css on 2026-09-23. */
const FALLBACK = {
  teal: '#4fd6b4',
  ink: '#eaf0fb',
  ink3: '#8a98b2',
  bg: '#05080e',
  scene: '#060a14',
  sceneDeep: '#03060c',
  sceneFrame: '#1c2740',
  chromeInk: '#dfe7f5',
  chromeMuted: '#8496b8',
  chromeEdge: '#26334f',
  surfaceSunk: '#111826',
  lineStrong: '#2d3b53',
  alertInk: '#ff9d8f',
  okInk: '#6fd9ab',
  warnInk: '#f0c887',
  gold: '#e0b062',
  segPending: 'rgba(150, 180, 230, .18)',
  segUnrun: 'rgba(150, 180, 230, .08)',
  replayInk: '#c9b8ff',
  replayGrade: 'rgba(128, 128, 128, .66)',
  replayTone: 'rgba(120, 96, 200, .34)',
};

/** Which custom property each name reads. */
const TOKENS = {
  teal: '--teal',
  ink: '--ink',
  ink3: '--ink-3',
  bg: '--bg',
  scene: '--scene',
  sceneDeep: '--scene-deep',
  sceneFrame: '--scene-frame',
  chromeInk: '--scene-chrome-ink',
  chromeMuted: '--scene-chrome-muted',
  chromeEdge: '--scene-chrome-edge',
  surfaceSunk: '--surface-sunk',
  lineStrong: '--line-strong',
  alertInk: '--alert-ink',
  // the day's segments, painted on the façade sign exactly as the slate paints them
  okInk: '--ok-ink',
  warnInk: '--warn-ink',
  gold: '--gold',
  segPending: '--seg-pending',
  segUnrun: '--seg-unrun',
  // «Reluarea zilei» (W13): the replay's ink, and the grade laid over the world it plays back
  replayInk: '--replay-ink',
  replayGrade: '--replay-grade',
  replayTone: '--replay-tone',
};

/** @type {Record<string, string>|null} */
let cached = null;

/**
 * The scene's chrome colours, read from the page's tokens once and kept.
 * Without a document (the tests, a worker) the written-out copy is returned.
 * @returns {Record<string, string>}
 */
export function scenePalette() {
  if (cached) return cached;
  /** @type {Record<string, string>} */
  const out = { ...FALLBACK };
  if (typeof document === 'undefined' || typeof getComputedStyle !== 'function') return out;
  const root = document.documentElement;
  if (!root) return out;
  const style = getComputedStyle(root);
  let seen = false;
  for (const [name, property] of Object.entries(TOKENS)) {
    const value = String(style.getPropertyValue(property) || '').trim();
    if (value) {
      out[name] = value;
      seen = true;
    }
  }
  // Nothing was read: the stylesheet has not arrived yet. Do not keep this frame's answer.
  if (seen) cached = out;
  return out;
}

/** Forgets the read values, so the next frame asks the page again. For tests and theme changes. */
export function resetScenePalette() {
  cached = null;
}

/**
 * A token colour at an alpha. Canvas has no colour-mix, and the alternative — setting
 * globalAlpha around every fill — leaks into whatever is drawn next if a return is ever added
 * between the save and the restore. #rrggbb and rgb()/rgba() are both understood; anything else
 * is handed back unchanged, so a token that becomes a gradient or a named colour still paints.
 * @param {string} colour @param {number} alpha
 */
export function withAlpha(colour, alpha) {
  const value = String(colour).trim();
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value);
  if (hex) {
    const d = hex[1];
    const full = d.length === 3 ? d[0] + d[0] + d[1] + d[1] + d[2] + d[2] : d;
    const r = parseInt(full.slice(0, 2), 16);
    const g = parseInt(full.slice(2, 4), 16);
    const b = parseInt(full.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }
  const rgb = /^rgba?\(([^)]+)\)$/i.exec(value);
  if (rgb) {
    const parts = rgb[1].split(/[,/\s]+/).filter(Boolean);
    if (parts.length >= 3) return `rgba(${parts[0]},${parts[1]},${parts[2]},${alpha})`;
  }
  return value;
}
