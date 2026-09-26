/**
 * THE DOORS (W28). Each dialog is a room of the headquarters, and it now opens from that room:
 * the pane grows out of the room's rectangle on screen into its place, and on close it goes back
 * into it. The room is lit while its door is open — the page's own mark of what the Owner chose,
 * like the teal ring of a chosen employee; it says nothing about the room's state.
 *
 * The rectangles are the building's own, in world px: the manifest's rooms under the page's
 * renderer, the rooms measured on the Unreal frame (replay_still.js STREAM_ROOMS) while the
 * stream covers it, and the façade sign's face (hq_screens.js WALL). They are turned into screen
 * px with the engine's camera, the one the stream follows (game_frame.js streamTransform).
 *
 * Nothing here fetches anything. The motion is one WAAPI animation on the way in (so its first
 * painted frame is already the room's rectangle) and the stylesheet's discrete exit on the way
 * out (so Escape, the close button and the backdrop all leave the same way, and focus returns at
 * once, as before). Under reduced motion the pane only fades.
 */

/**
 * Which room each door belongs to: a manifest room (zone) or a named face of the building.
 * The dialog's gold eyebrow names the same place (index.html, glossary W26).
 * @type {Record<string, {zone?: string, face?: string}>}
 */
export const DOOR_ROOMS = {
  'research-modal': { zone: 'research_lab' }, // CERCETARE · L3
  'media-modal': { zone: 'video_studio' }, // RANDARE · L1
  'publishing-modal': { zone: 'publish_desk' }, // DISTRIBUȚIE · L2
  'story-modal': { zone: 'script_room' }, // JURNAL · OFFICE SERIAL (the writers' screen, L2)
  'runbook-modal': { face: 'run_sign' }, // FAȚADA · RULAREA ZILEI
  'treasury-modal': { zone: 'accounting_office' }, // TREZORERIE · S2
  'workforce-modal': { zone: 'lobby' }, // SEDIUL · ANGAJAȚI: the reception they come in by
  'settings-dialog': { zone: 'server_corner' }, // STUDIO · CONEXIUNI: the servers, S1
};

/** The smallest a pane is scaled to on either axis: a thinner start reads as a line, not a room. */
export const DOOR_MIN_SCALE = 0.04;

/**
 * The move that lays a pane over a room: CSS `translate` and `scale` about the pane's centre (the
 * dialog's transform-origin), in px and as factors. Null when either box is empty.
 * @param {{x: number, y: number, w: number, h: number}} pane the dialog's box on screen
 * @param {{x: number, y: number, w: number, h: number}|null} room the room's box on screen
 * @returns {{tx: number, ty: number, sx: number, sy: number}|null}
 */
export function doorMove(pane, room) {
  if (!pane || !room || !(pane.w > 0) || !(pane.h > 0) || !(room.w > 0) || !(room.h > 0)) return null;
  const clamp = (/** @type {number} */ v) => Math.min(1, Math.max(DOOR_MIN_SCALE, v));
  return {
    tx: Math.round((room.x + room.w / 2 - (pane.x + pane.w / 2)) * 10) / 10,
    ty: Math.round((room.y + room.h / 2 - (pane.y + pane.h / 2)) * 10) / 10,
    sx: Math.round(clamp(room.w / pane.w) * 1000) / 1000,
    sy: Math.round(clamp(room.h / pane.h) * 1000) / 1000,
  };
}

/**
 * A world rectangle [x, y, w, h] on screen: through the camera (zoom and pan in canvas px), the
 * canvas's device ratio, and the canvas's own box on the page. Then cut to what the visitor can
 * see of the scene (the box between the drawers, `clip`); null when nothing of it is left, or
 * less than a sliver (a door from a room nobody can see is no door).
 * @param {number[]} rect world px
 * @param {{zoom: number, panX: number, panY: number}} view the engine's camera
 * @param {number} dpr the canvas's device px per CSS px
 * @param {{left: number, top: number}} canvasBox the canvas's box on the page
 * @param {{left: number, top: number, right: number, bottom: number}} clip what is seen, page px
 * @returns {{x: number, y: number, w: number, h: number}|null}
 */
export function roomOnScreen(rect, view, dpr, canvasBox, clip) {
  if (!rect || rect.length < 4 || !view || !(view.zoom > 0)) return null;
  const d = dpr || 1;
  const x0 = canvasBox.left + (rect[0] * view.zoom + view.panX) / d;
  const y0 = canvasBox.top + (rect[1] * view.zoom + view.panY) / d;
  const x1 = x0 + (rect[2] * view.zoom) / d;
  const y1 = y0 + (rect[3] * view.zoom) / d;
  const l = Math.max(x0, clip.left);
  const t = Math.max(y0, clip.top);
  const r = Math.min(x1, clip.right);
  const b = Math.min(y1, clip.bottom);
  if (r - l < 8 || b - t < 8) return null;
  return { x: Math.round(l * 10) / 10, y: Math.round(t * 10) / 10, w: Math.round((r - l) * 10) / 10, h: Math.round((b - t) * 10) / 10 };
}

/**
 * The world rectangle of a door's room: the stream's measured rooms while the stream covers the
 * renderer, else the manifest's; a face from the named faces.
 * @param {string} dialogId
 * @param {{rooms?: Record<string, any>, streamRooms?: Record<string, number[]>, faces?: Record<string, number[]>, stream?: boolean}} world
 * @returns {number[]|null}
 */
export function doorWorldRect(dialogId, world) {
  const place = DOOR_ROOMS[dialogId];
  if (!place) return null;
  if (place.face) {
    const f = world.faces && world.faces[place.face];
    return f ? [...f] : null;
  }
  const zone = place.zone || '';
  if (world.stream && world.streamRooms && world.streamRooms[zone]) return [...world.streamRooms[zone]];
  const r = world.rooms && world.rooms[zone];
  return r ? [r.x, r.y, r.w, r.h] : null;
}

/**
 * How long each half of a door takes, read from the page's tokens, and what moves.
 * @param {boolean} reduced
 * @param {(name: string) => string} token reads a custom property of :root
 */
export function doorTiming(reduced, token) {
  const ms = (/** @type {string} */ name, /** @type {number} */ fallback) => {
    const raw = String(token(name) || '').trim();
    const v = raw.endsWith('ms') ? parseFloat(raw) : raw.endsWith('s') ? parseFloat(raw) * 1000 : parseFloat(raw);
    return Number.isFinite(v) && v >= 0 ? v : fallback;
  };
  if (reduced) return { open: ms('--dur-room-fade', 180), close: ms('--dur-room-fade', 180), ease: String(token('--ease') || 'ease').trim(), move: false };
  return {
    open: ms('--dur-room-open', 340),
    close: ms('--dur-room-close', 300),
    ease: String(token('--ease-push') || 'ease-in-out').trim(),
    move: true,
  };
}

/**
 * The opening's keyframes for the pane and for its content: the pane (the glass) grows out of the
 * room, the words come up as it lands, so nothing is read squeezed.
 * The pane leaves the room as the room's own light: a warm edge and halo (the pane's ::after,
 * style.css), nearly clear glass that becomes the pane as it grows. Only what the compositor moves
 * is animated (translate, scale, opacity): nothing is painted again while the door moves.
 * @param {{tx: number, ty: number, sx: number, sy: number}|null} move
 * @param {boolean} reduced
 */
export function doorKeyframes(move, reduced) {
  if (reduced || !move) {
    return {
      pane: [{ opacity: 0 }, { opacity: 1 }],
      content: [{ opacity: 0 }, { opacity: 1 }],
      edge: null,
    };
  }
  return {
    pane: [
      { translate: `${move.tx}px ${move.ty}px`, scale: `${move.sx} ${move.sy}`, opacity: 0.25, offset: 0 },
      { opacity: 1, offset: 0.35 },
      { translate: '0px 0px', scale: '1 1', opacity: 1, offset: 1 },
    ],
    content: [{ opacity: 0, offset: 0 }, { opacity: 0, offset: 0.5 }, { opacity: 1, offset: 1 }],
    edge: [{ opacity: 1, offset: 0 }, { opacity: 0.8, offset: 0.4 }, { opacity: 0, offset: 1 }],
  };
}

/**
 * Freshness of what a door shows: a door whose content was read at most `freshMs` ago (on the
 * menu's hover or focus, or at its last opening) opens on it and reads nothing; otherwise it
 * reads once its pane has landed, so no answer is laid out while the pane moves.
 * @param {number|undefined} readAt when the content was last read (ms), or undefined
 * @param {number} now
 * @param {number} freshMs
 */
export function doorNeedsRead(readAt, now, freshMs) {
  return !(typeof readAt === 'number' && now - readAt >= 0 && now - readAt <= freshMs);
}

/**
 * W30: when a door's parts start to be laid out, ms after it starts to open. Its words are
 * invisible for the first half of the opening (doorKeyframes: the content fades in from 50 %), so
 * nothing needs laying out before they begin to show; the first frames then only move the glass.
 * Under reduced motion the words fade in from the start, and the parts come at once.
 * @param {{open: number, move: boolean}} timing doorTiming's
 */
export function doorRevealAt(timing) {
  return timing.move ? Math.round(timing.open * DOOR_REVEAL_SHARE) : 0;
}
/** The share of the opening before the parts are laid out (a little ahead of the words' fade). */
export const DOOR_REVEAL_SHARE = 0.4;

/**
 * The steps a door's body is laid out in, one per frame: its parts, and inside a part that says
 * `data-door-steps` (a heavy one: the Journal's episodes, the newest episode's slate and room)
 * its children instead, so no single frame lays out a whole heavy part.
 * @param {Element[]} parts
 * @returns {Element[]}
 */
export function doorSteps(parts) {
  /** @type {Element[]} */
  const out = [];
  const walk = (/** @type {Element} */ el, /** @type {number} */ depth) => {
    const kids = Array.from(el.children);
    // W36: six levels, so Distribuție's channel slot (area → overview → card → list → slot) is itself
    // stepped through: its first layout (the chart, the account picker) cost 12 ms in one frame
    if (depth < 6 && el.hasAttribute('data-door-steps') && kids.length) for (const k of kids) walk(k, depth + 1);
    else out.push(el);
  };
  for (const p of parts) walk(p, 0);
  return out;
}

/** Each door's running opening, so the page can wait for its landing (doorLanded). @type {WeakMap<HTMLDialogElement, Animation>} */
const landing = new WeakMap();
/** The door whose room is lit now: a door that closes turns the light off only if it is still its own. @type {HTMLDialogElement|null} */
let lightOwner = null;

/**
 * W30: resolves once the door's pane has landed (its opening is over, or cancelled), at once when
 * it is not moving. The mail and the inspector lay out their content then, not while the pane
 * grows.
 * @param {HTMLDialogElement} dialog
 * @returns {Promise<void>}
 */
export function doorLanded(dialog) {
  const a = landing.get(dialog);
  if (!a || a.playState === 'finished' || a.playState === 'idle') return Promise.resolve();
  return a.finished.then(() => undefined, () => undefined);
}

/**
 * Lay out a set of a door's parts one per frame (content-visibility, style.css [data-door-wait]):
 * content that arrives after the pane has landed comes in over a few frames, not in one.
 * @param {Element[]} parts
 * @param {number} [delayMs] wait before the first
 */
export function revealInSteps(parts, delayMs = 0) {
  const steps = doorSteps(parts);
  if (!steps.length) return;
  for (const p of steps) p.setAttribute('data-door-wait', '');
  let i = 0;
  const step = () => {
    if (i >= steps.length) return;
    steps[i++].removeAttribute('data-door-wait');
    requestAnimationFrame(step);
  };
  if (delayMs > 0) setTimeout(() => requestAnimationFrame(step), delayMs);
  else requestAnimationFrame(step);
}

/**
 * Bind one dialog to its room.
 * @param {HTMLDialogElement} dialog
 * @param {{roomRect: () => ({x: number, y: number, w: number, h: number}|null), light?: (rect: any, on: boolean, ms: number) => void, reduced: () => boolean}} o
 */
export function attachDoor(dialog, o) {
  if (!dialog || dialog.dataset.door === 'on') return;
  dialog.dataset.door = 'on';
  dialog.classList.add('has-door');
  const nativeShow = HTMLDialogElement.prototype.showModal;
  const nativeClose = HTMLDialogElement.prototype.close;
  const token = (/** @type {string} */ name) => getComputedStyle(document.documentElement).getPropertyValue(name);
  /** @type {Animation[]} */
  let running = [];
  let lightOff = 0;

  /** The room's box now, else the key that opened the door, else nothing (the pane only fades). */
  const origin = () => {
    const room = o.roomRect();
    if (room) return { rect: room, room: true };
    const key = document.activeElement;
    if (key && key !== document.body && !dialog.contains(key) && key instanceof HTMLElement) {
      const b = key.getBoundingClientRect();
      if (b.width > 0 && b.height > 0 && b.bottom > 0 && b.top < innerHeight) return { rect: { x: b.left, y: b.top, w: b.width, h: b.height }, room: false };
    }
    return null;
  };
  let from = /** @type {{rect: any, room: boolean}|null} */ (null);

  /** The closed pane's place: where the exit transition takes it (style.css .has-door). */
  const setExit = () => {
    const box = dialog.getBoundingClientRect();
    const pane = { x: box.left, y: box.top, w: box.width, h: box.height };
    const now = origin() || from;
    const move = now ? doorMove(pane, now.rect) : null;
    dialog.style.setProperty('--door-tx', `${move ? move.tx : 0}px`);
    dialog.style.setProperty('--door-ty', `${move ? move.ty : 8}px`);
    dialog.style.setProperty('--door-sx', String(move ? move.sx : 0.96));
    dialog.style.setProperty('--door-sy', String(move ? move.sy : 0.96));
    return now;
  };

  const play = () => {
    for (const a of running) a.cancel();
    running = [];
    if (!dialog.open) return;
    const reduced = o.reduced();
    const timing = doorTiming(reduced, token);
    from = origin();
    const box = dialog.getBoundingClientRect();
    const move = from && timing.move ? doorMove({ x: box.left, y: box.top, w: box.width, h: box.height }, from.rect) : null;
    const frames = doorKeyframes(move, reduced);
    const pane = dialog.animate(frames.pane, { duration: timing.open, easing: timing.ease });
    running.push(pane);
    landing.set(dialog, pane);
    // the pane's own blur is taken off while it moves (it is 90 % opaque: the blur is a finish, and
    // re-blurring a moving, scaling pane every frame cost the compositor its frame); on at rest
    dialog.classList.add('is-moving');
    pane.finished.then(() => dialog.classList.remove('is-moving'), () => {});
    if (frames.edge) running.push(dialog.animate(frames.edge, { duration: timing.open, easing: 'linear', pseudoElement: '::after' }));
    for (const child of Array.from(dialog.children)) {
      running.push(child.animate(frames.content, { duration: timing.open, easing: 'linear' }));
    }
    setExit();
    clearTimeout(lightOff);
    if (o.light && from && from.room) {
      lightOwner = dialog;
      o.light(from.rect, true, timing.open);
    }
  };

  /**
   * THE FIRST FRAME (W28). A door's words are invisible for the first part of its opening (the
   * content fades in from 40 %), so they need not all be laid out in its first frame: each part
   * of the body waits, its place kept by its last height, and one part more is laid out per frame
   * (content-visibility, style.css). Research's first frame laid out its whole 6000 px.
   */
  const stagger = () => {
    const parts = /** @type {HTMLElement[]} */ (Array.from(dialog.querySelectorAll(':scope > .dialog-body > .dialog-pane > *, :scope > .dialog-body:not(.dialog-body-railed) > *')));
    // W32: a door whose pane is one wrapper (Media, Distribuție) is stepped through its heavy parts
    if (doorSteps(parts).length < 2) return;
    // W30: none before the words begin to show; then one step per frame, heavy parts in pieces
    revealInSteps(parts, doorRevealAt(doorTiming(o.reduced(), token)));
  };

  dialog.showModal = function showModal() {
    stagger();
    nativeShow.call(dialog);
    // after the opener's own synchronous work (Settings builds its content right after), before
    // the first frame is painted
    queueMicrotask(play);
  };
  dialog.close = function close(value) {
    if (dialog.open) setExit();
    nativeClose.call(dialog, value);
  };
  dialog.addEventListener('cancel', () => { if (dialog.open) setExit(); });
  dialog.addEventListener('close', () => {
    dialog.classList.remove('is-moving');
    for (const a of running) a.cancel();
    running = [];
    const timing = doorTiming(o.reduced(), token);
    // another door has lit its own room since (a card of the roster opens the inspector at the
    // desk as the roster goes back into the lobby): the light is that door's now
    if (o.light && lightOwner === dialog) {
      const rect = (from && from.room) ? (o.roomRect() || from.rect) : null;
      if (rect) o.light(rect, true, 0);
      clearTimeout(lightOff);
      lightOff = window.setTimeout(() => {
        if (!dialog.open && o.light && lightOwner === dialog) {
          lightOwner = null;
          o.light(null, false, timing.close);
        }
      }, timing.close);
    }
  });
}
