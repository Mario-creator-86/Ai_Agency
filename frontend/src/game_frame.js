/**
 * THE GAME FRAME. On a wide screen the render is the whole first viewport, edge to edge under the
 * masthead, and the register and the approvals are glass drawers over its two edges. This module
 * holds the arithmetic of that frame, free of the page, so it can be tested:
 *
 * - where the camera stands (frameFit): the world covers the viewport, and the building -- the
 *   part of the picture every figure in it belongs to -- is centred in the room the open drawers
 *   leave. The world may run short of the viewport's edge only where a drawer covers it, never in
 *   the open picture. Above the world's top edge is sky: the page paints its own sky there
 *   (hq_sky.js), so the camera keeps a row of it over the roof for the instruments (the floor's
 *   top), and the roof is never under a chip;
 * - which drawers a first visit opens (drawerDefaults): each one only if the building still fits
 *   beside it, so the render is never covered by more than it can spare;
 * - how the streamed picture follows the camera (streamTransform): the Unreal video is a fixed
 *   camera laid in its box whole, like `object-fit: contain` (W8: with `cover` the box cut the
 *   video's top rows, the roof's railing among them, before the camera moved it under the row of
 *   sky); the page's zoom and pan are applied to it as a transform, so the visitor zooms and drags
 *   what they see, and the page's hit boxes, which stay under the video, keep landing on the
 *   employee the pointer is on.
 *
 * Every length here is in one unit, whichever the caller uses (canvas pixels in the engine).
 */

/** @typedef {{left: number, right: number, top: number, bottom: number}} Insets */
/** @typedef {{x: number, y: number, width: number, height: number}} Rect */

/** @type {Insets} */
export const NO_INSETS = Object.freeze({ left: 0, right: 0, top: 0, bottom: 0 });

/**
 * One axis of the camera: the pan that centres `centre` (a world coordinate, already scaled) in the
 * free span [lead, view - trail], held so that bare ground beyond the world's edge appears only
 * under a drawer.
 * @param {number} view the viewport's length
 * @param {number} span the world's length at this zoom
 * @param {number} centre the focus centre at this zoom
 * @param {number} lead the drawer at the start of the axis
 * @param {number} trail the drawer at its end
 */
function axis(view, span, centre, lead, trail) {
  const free = Math.max(0, view - lead - trail);
  // A world shorter than the free span cannot cover it: it is centred in it, and says so.
  if (span <= free) return lead + (free - span) / 2;
  const wanted = lead + free / 2 - centre;
  // The world's near edge may come in no further than the leading drawer's inner edge, and its
  // far edge no further than the trailing drawer's.
  const lo = view - trail - span;
  const hi = lead;
  return wanted < lo ? lo : wanted > hi ? hi : wanted;
}

/**
 * What the frame always covers, whatever the drawers do: a closed drawer's rail on each side, and
 * the row of sky the instruments stand in above the roof. The camera's zoom is chosen against
 * this floor, so opening or closing a drawer only moves the camera, and never resizes the house.
 * @param {{railW?: number, hudTop?: number}} widths
 * @returns {Insets}
 */
export function frameFloor({ railW = 0, hudTop = 0 } = {}) {
  return { left: railW, right: railW, top: hudTop, bottom: 0 };
}

/**
 * Where the camera stands. The zoom is the smallest that covers the viewport with the world,
 * less the floor (frameFloor): the rails at the sides are glass and the top row is sky, so the
 * world needs to reach only the rails and the bottom edge. It is held down only where the
 * building would not fit the viewport at all (a tall narrow box): the building is always seen
 * whole. The world's top edge comes down to the floor's top and no further, so the roof stands
 * under the row of sky.
 * @param {{cw: number, ch: number, worldW: number, worldH: number, focus?: Rect|null, insets?: Insets, floor?: Insets}} frame
 * @returns {{zoom: number, panX: number, panY: number}}
 */
export function frameFit({ cw, ch, worldW, worldH, focus = null, insets = NO_INSETS, floor = NO_INSETS }) {
  const w = Math.max(1, cw);
  const h = Math.max(1, ch);
  const f = focus || { x: 0, y: 0, width: worldW, height: worldH };
  const freeW = Math.max(1, w - floor.left - floor.right);
  const freeH = Math.max(1, h - floor.top - floor.bottom);
  const cover = Math.max(freeW / worldW, freeH / worldH);
  const whole = Math.min(freeW / f.width, freeH / f.height);
  const zoom = Math.min(cover, whole);
  const edge = (/** @type {'left'|'right'|'top'|'bottom'} */ k) => Math.max(insets[k] || 0, floor[k] || 0);
  return {
    zoom,
    panX: axis(w, worldW * zoom, (f.x + f.width / 2) * zoom, edge('left'), edge('right')),
    panY: axis(h, worldH * zoom, (f.y + f.height / 2) * zoom, edge('top'), edge('bottom')),
  };
}

/**
 * Which drawers a first visit opens. The register is opened when the building fits beside it and
 * the other drawer's rail; the approvals too when it fits beside both. `breathe` is the ground
 * kept on each side of the building so it never touches a drawer's edge.
 * @param {{cw: number, ch: number, worldW: number, worldH: number, focus: Rect, registerW: number, sideW: number, railW: number, hudTop?: number, breathe?: number}} frame
 * @returns {{register: boolean, side: boolean}}
 */
export function drawerDefaults({ cw, ch, worldW, worldH, focus, registerW, sideW, railW, hudTop = 0, breathe = 24 }) {
  const { zoom } = frameFit({ cw, ch, worldW, worldH, focus, floor: frameFloor({ railW, hudTop }) });
  const need = focus.width * zoom + 2 * breathe;
  if (need <= cw - registerW - sideW) return { register: true, side: true };
  if (need <= cw - registerW - railW) return { register: true, side: false };
  return { register: false, side: false };
}

/**
 * What the drawers take from the render's edges, from their state and their widths, and the row
 * of sky the instruments stand in at the top.
 * @param {{register: boolean, side: boolean}} open
 * @param {{registerW: number, sideW: number, railW: number, hudTop?: number}} widths
 * @returns {Insets}
 */
export function drawerInsets(open, { registerW, sideW, railW, hudTop = 0 }) {
  return { left: open.register ? registerW : railW, right: open.side ? sideW : railW, top: hudTop, bottom: 0 };
}

/**
 * The transform that lays the streamed picture where the page's camera says the world is. The
 * video is laid in its box whole, the way `object-fit: contain` does, centred, so no row of it is
 * cut before the camera places it; the transform (origin at the box's top-left corner) is
 * `translate(tx, ty) scale(k)`.
 * @param {{cw: number, ch: number, worldW: number, worldH: number, zoom: number, panX: number, panY: number}} view
 * @returns {{k: number, tx: number, ty: number}}
 */
export function streamTransform({ cw, ch, worldW, worldH, zoom, panX, panY }) {
  const native = Math.min(cw / worldW, ch / worldH);
  const k = native > 0 ? zoom / native : 1;
  const nx = (cw - worldW * native) / 2;
  const ny = (ch - worldH * native) / 2;
  return { k, tx: panX - k * nx, ty: panY - k * ny };
}

/**
 * The camera between two stands, for a glide of `t` in [0, 1] (already eased).
 * @param {{zoom: number, panX: number, panY: number}} from
 * @param {{zoom: number, panX: number, panY: number}} to
 * @param {number} t
 */
export function between(from, to, t) {
  const u = t < 0 ? 0 : t > 1 ? 1 : t;
  return {
    zoom: from.zoom + (to.zoom - from.zoom) * u,
    panX: from.panX + (to.panX - from.panX) * u,
    panY: from.panY + (to.panY - from.panY) * u,
  };
}

/** The ease the page's own motion uses, cubic-bezier(.22, .7, .3, 1), close enough for a camera. @param {number} t */
export function easeOut(t) {
  const u = t < 0 ? 0 : t > 1 ? 1 : t;
  return 1 - (1 - u) ** 3;
}

/**
 * The drawers as a visitor finds them: what they chose last time on this browser, and where they
 * never chose, what fits (drawerDefaults).
 * @param {{register?: unknown, side?: unknown}|null} stored
 * @param {{register: boolean, side: boolean}} defaults
 */
export function resolveDrawers(stored, defaults) {
  const pick = (/** @type {unknown} */ v, /** @type {boolean} */ d) => (typeof v === 'boolean' ? v : d);
  return { register: pick(stored?.register, defaults.register), side: pick(stored?.side, defaults.side) };
}

/**
 * What a drawer's rail says when it is closed: the panel's own count, word for word.
 * @param {string|null|undefined} tagText the panel's count tag
 */
export function railCount(tagText) {
  const text = String(tagText ?? '').trim();
  return text === '—' ? '' : text;
}
