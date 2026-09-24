/**
 * THE STUDIO'S NUMBERS OVER THE LIVE VIDEO (W19).
 *
 * The page draws the studio's figures on its own building (hq_screens.js): the façade's run, the
 * fact-check board, the distribution screen, the Treasury; since W21 also the serial's board, the
 * render screen and the servers' tokens. Over the Unreal stream those faces lie
 * under the video, and a visitor saw the figures only by hovering. Four of them — the ones a
 * visitor reads first at fit zoom — now stand as small plaques of the drawers' glass, always
 * visible, anchored to a real object of the streamed building, following the camera with the
 * video. Their words come from the same facts store the faces are drawn from; nothing is fetched.
 *
 * The Unreal building's objects do not stand exactly where the plates' faces are. Each plaque's
 * anchor is the real object's rectangle, measured on a frame of the live stream (1920x1008, which
 * the page lays exactly over the world's 1600x840 px; game_frame.js streamTransform), and used only
 * while the stream plays. `streamOffset` gives how far that object stands from the plate's face.
 *
 * A plaque never covers an employee (the desks' boxes: monitor, chair and figure), stays inside the
 * room the drawers leave, steps aside for the glass readout of its own face, shows its value only
 * where the building is small, and is not shown at all where it would clutter.
 */

import { factCheckFace, publishFace, runSignFace, treasuryFace, tokensFace, paneMode } from './hq_screens.js';
import { surfaceReadout } from './hq_readouts.js';

/**
 * @typedef {{id: string, object: string, anchor: [number, number, number, number], sides: Array<'on'|'above'|'below'|'left'|'right'>, from?: 'full'}} PlaqueDef
 * @typedef {{eyebrow: string, value: string, tone: 'quiet'|'ok'|'alert', key: string}} PlaqueWords
 */

/**
 * The four plaques, in the order they claim room. `anchor` is the real object in the streamed
 * building, world px, measured 2026-09-24 22:53 on the live stream's own frame (scratchpad
 * ui/w19/probe: raw.png, over.png). `sides` are tried in order.
 * @type {PlaqueDef[]}
 */
export const PLAQUES = [
  // the façade's sign band right of «AUTONOMOUS MACHINE NEXUS»: empty and dark in Unreal
  { id: 'run_sign', object: 'banda firmei, la dreapta literelor AMN-AI', anchor: [1050, 37, 154, 42], sides: ['on'] },
  // the paper board on the fact-check wall, above the bottles; the plaque stands beside it
  { id: 'factcheck_board', object: 'tabla de hârtie din Verificare', anchor: [970, 208, 32, 42], sides: ['right', 'above', 'left'] },
  // the dark wall screen of distribution, right of the bookcase: empty in Unreal
  { id: 'publish_radar', object: 'ecranul de perete din Distribuție', anchor: [1100, 318, 42, 32], sides: ['on', 'above', 'below'] },
  // the wall of lockers in the Treasury, left of the accountant's desk
  { id: 'treasury_board', object: 'peretele de casete din Trezorerie', anchor: [910, 573, 54, 64], sides: ['above', 'on', 'left'] },
  // W21, measured 2026-09-24 22:53 on the same frame (scratchpad ui/w21: crop_content, crop_l1, crop_infra).
  // Conținut's empty wall screen, right of the frames, above the writer's desk: the serial's board
  { id: 'writers_screen', object: 'ecranul gol de perete din Conținut', anchor: [777, 301, 58, 28], sides: ['on', 'above'], from: 'full' },
  // the light bar of Unreal's own «RENDER» screen in L1: the plaque lies on it, under the word
  { id: 'render_bay', object: 'bara de lumină a ecranului RENDER', anchor: [887, 459, 46, 11], sides: ['on'], from: 'full' },
  // the dark band above the racks of S1, right of «S1 INFRA»
  { id: 'infra_plate', object: 'banda întunecată de deasupra rafturilor din S1', anchor: [549, 522, 84, 13], sides: ['on'], from: 'full' },
];

/**
 * How far each real object stands from the plate's own face (world px, centre to centre), for the
 * record: the plates' faces are hq_readouts.js SURFACES; the anchors above are what is used.
 * @param {PlaqueDef} def @param {number[]} face [x, y, w, h] of the plate's face
 */
export function streamOffset(def, face) {
  const [ax, ay, aw, ah] = def.anchor;
  const [fx, fy, fw, fh] = face;
  return { dx: Math.round(ax + aw / 2 - (fx + fw / 2)) || 0, dy: Math.round(ay + ah / 2 - (fy + fh / 2)) || 0 };
}

/** Below this many CSS px per world px the plaques would clutter the building: none is shown. */
export const PLAQUE_HIDE_BELOW = 0.55;
/** Below this, a plaque shows its value alone (the eyebrow returns when the building is larger). */
export const PLAQUE_FULL_FROM = 0.9;
/** From this scale (2560 at fit: 1.55) the plaque's words are set one step larger, in proportion to the building. */
export const PLAQUE_LARGE_FROM = 1.35;

/**
 * How much a plaque says at a scale, and how large.
 * @param {number} k CSS px per world px
 * @returns {'large'|'full'|'compact'|'none'}
 */
export function plaqueLevel(k) {
  if (!(k >= PLAQUE_HIDE_BELOW)) return 'none';
  if (k >= PLAQUE_LARGE_FROM) return 'large';
  return k >= PLAQUE_FULL_FROM ? 'full' : 'compact';
}

/**
 * Whether a plaque is shown at a level. W21: the three newer plaques (the serial's board, the render
 * screen, the servers) say little without their eyebrow («EP — · Ciornă»), so they are shown only
 * from the level that carries it; the small building (1280 at fit) keeps the four.
 * @param {PlaqueDef} def @param {'large'|'full'|'compact'|'none'} level
 */
export function plaqueShownAt(def, level) {
  if (level === 'none') return false;
  return def.from === 'full' ? level === 'full' || level === 'large' : true;
}

/** @param {string} n a figure as the face writes it @param {string} one @param {string} many */
const agree = (n, one, many) => (n === '1' ? one : many);

/**
 * A plaque's words, from the facts the faces are drawn from. A value the page does not hold is «—».
 * @param {string} id @param {any} facts the page's facts store (main.js worldFacts) @param {any[]} [agents]
 * @returns {PlaqueWords|null}
 */
export function plaqueWords(id, facts, agents = []) {
  const f = facts || {};
  const reads = f.reads || {};
  if (id === 'run_sign') {
    const face = runSignFace(f.track, { today: f.today, live: f.live, read: reads.runs });
    const known = face.tally !== '—';
    const state = known ? String(face.state || '').split(' · ')[0] : '';
    const value = known ? [face.tally, state].filter(Boolean).join(' · ') : '—';
    return { eyebrow: known ? face.title : 'RULAREA ZILEI', value, tone: face.underWay ? 'ok' : 'quiet', key: `rs|${face.title}|${value}` };
  }
  if (id === 'factcheck_board') {
    const face = factCheckFace(f.run);
    const none = face.verified === '—' && face.refused === '—';
    const value = none ? '—' : `${face.verified} ${agree(face.verified, 'verificată', 'verificate')} · ${face.refused} ${agree(face.refused, 'respins', 'respinse')}`;
    const eyebrow = face.date ? `VERIFICARE · ${face.date}` : 'VERIFICARE';
    return { eyebrow, value, tone: 'quiet', key: `fc|${eyebrow}|${value}` };
  }
  if (id === 'publish_radar') {
    const desk = (agents || []).find((a) => a && a.desk_id === 'desk_publish') || null;
    const mode = paneMode(desk);
    if (mode === 'work' || mode === 'think') return { eyebrow: 'DISTRIBUȚIE', value: 'ÎN LUCRU', tone: 'ok', key: 'pb|busy' };
    const face = publishFace(f.run);
    const value = face.word === '—' ? '—' : face.date ? `${face.word} · ${face.date}` : face.word;
    return { eyebrow: 'DISTRIBUȚIE', value, tone: face.word === 'EȘUAT' ? 'alert' : 'quiet', key: `pb|${value}` };
  }
  if (id === 'treasury_board') {
    const face = treasuryFace(f.treasury, f.budget, f.replay ? 'atunci' : 'azi');
    // W21: the face card's own phrase; the same record holds a VR_DEBT of 50.000, so the bare
    // number read as the studio's whole money
    const value = face.balance === '—' ? '—' : `${face.balance} VR$ cheltuibili`;
    // W22: over the replay the balance is the books' as-of reading, and says so
    const eyebrow = f.replay ? 'TREZORERIE · ATUNCI' : 'TREZORERIE';
    return { eyebrow, value, tone: face.deficit ? 'alert' : 'quiet', key: `tr|${eyebrow}|${value}|${face.deficit}` };
  }
  // W21: the face card's own value, word for word (hq_readouts.js surfaceReadout)
  if (id === 'writers_screen') {
    const card = surfaceReadout(id, { facts: f, agents });
    const value = card && card.value !== 'EP —' ? card.value : '—';
    return { eyebrow: 'OFFICE SERIAL', value, tone: 'quiet', key: `ws|${value}` };
  }
  if (id === 'render_bay') {
    const card = surfaceReadout(id, { facts: f, agents });
    const value = card ? card.value : '—';
    const tone = card && (card.tone === 'ok' || card.tone === 'alert') ? card.tone : 'quiet';
    return { eyebrow: 'RANDARE', value, tone, key: `rb|${value}|${tone}` };
  }
  if (id === 'infra_plate') {
    // not read is «—», not the face's «tokenuri azi —»
    const face = tokensFace(f.budget, f.replay ? 'atunci' : 'azi');
    const value = face.key.startsWith('tk|none') ? '—' : face.text;
    return { eyebrow: 'SERVERE', value, tone: 'quiet', key: `ip|${value}` };
  }
  return null;
}

/**
 * @typedef {{x: number, y: number, w: number, h: number}} Box
 */

/** @param {Box} a @param {Box} b */
function overlaps(a, b) {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** The gap between a plaque and the object it names, CSS px. */
export const PLAQUE_GAP = 6;

/**
 * Where a plaque stands: the first of its sides that keeps it inside the room, off every employee
 * and off the plaques already placed. Null when none does: the plaque is not shown there.
 * @param {Box} anchor the real object on screen @param {{w: number, h: number}} size
 * @param {PlaqueDef['sides']} sides @param {{left: number, top: number, right: number, bottom: number}} room
 * @param {Box[]} blocked employees' boxes and plaques already placed
 * @returns {{x: number, y: number, side: string}|null}
 */
export function placePlaque(anchor, size, sides, room, blocked) {
  const cx = anchor.x + anchor.w / 2;
  const cy = anchor.y + anchor.h / 2;
  for (const side of sides) {
    let x = cx - size.w / 2;
    let y = cy - size.h / 2;
    if (side === 'above') y = anchor.y - PLAQUE_GAP - size.h;
    else if (side === 'below') y = anchor.y + anchor.h + PLAQUE_GAP;
    else if (side === 'left') x = anchor.x - PLAQUE_GAP - size.w;
    else if (side === 'right') x = anchor.x + anchor.w + PLAQUE_GAP;
    const box = { x, y, w: size.w, h: size.h };
    if (x < room.left || y < room.top || x + size.w > room.right || y + size.h > room.bottom) continue;
    if (blocked.some((b) => overlaps(box, b))) continue;
    return { x: Math.round(x), y: Math.round(y), side };
  }
  return null;
}

/**
 * The plaques in the document: one glass pane each, inside one layer over the stream. Written only
 * when a word, a place or a visibility changes.
 */
export class StreamPlaques {
  /**
   * @param {HTMLElement} host the scene's viewport
   */
  constructor(host) {
    this.host = host;
    this.layer = document.createElement('div');
    this.layer.className = 'stream-plaques';
    this.layer.setAttribute('aria-hidden', 'true');
    this.layer.hidden = true;
    /** @type {Map<string, {el: HTMLElement, eyebrow: HTMLElement, value: HTMLElement, key: string, level: string, size: {w: number, h: number}|null, place: string}>} */
    this.items = new Map();
    for (const def of PLAQUES) {
      const el = document.createElement('div');
      el.className = 'stream-plaque';
      el.dataset.surface = def.id;
      el.dataset.shown = 'false';
      const eyebrow = document.createElement('span');
      eyebrow.className = 'stream-plaque-eyebrow';
      const value = document.createElement('span');
      value.className = 'stream-plaque-value';
      el.append(eyebrow, value);
      this.layer.append(el);
      this.items.set(def.id, { el, eyebrow, value, key: '', level: '', size: null, place: '' });
    }
    host.append(this.layer);
    this.on = false;
    /** W22: laid over the replay in the Unreal building, with the books as they stood */
    this.replay = false;
    /** the face whose glass readout is up: its plaque steps aside */
    this.suppressed = '';
  }

  /** Shown while the live stream is what the visitor sees. @param {boolean} on */
  setOn(on) {
    if (this.on === on) return;
    this.on = on;
    this.layer.hidden = !on;
    if (on) for (const item of this.items.values()) item.size = null;
  }

  /**
   * W22: the plaques stand over the replay played in the Unreal building (replay_still.js), in the
   * replay's ink, with the replayed moment's words.
   * @param {boolean} on
   */
  setReplay(on) {
    if (this.replay === Boolean(on)) return;
    this.replay = Boolean(on);
    if (this.replay) this.layer.dataset.replay = 'on';
    else delete this.layer.dataset.replay;
    for (const item of this.items.values()) item.size = null;
  }

  /** @param {string} id */
  suppress(id) {
    this.suppressed = id || '';
  }

  /**
   * Writes the words and lays the plaques where the camera shows their objects.
   * @param {{facts: any, agents: any[], k: number, toScreen: (x: number, y: number) => {x: number, y: number},
   *          room: {left: number, top: number, right: number, bottom: number}, desks: Box[]}} scene
   */
  update(scene) {
    if (!this.on) return;
    const level = plaqueLevel(scene.k);
    const blocked = scene.desks.map((d) => ({ x: d.x - 2, y: d.y - 2, w: d.w + 4, h: d.h + 4 }));
    for (const def of PLAQUES) {
      const item = this.items.get(def.id);
      if (!item) continue;
      const words = plaqueWords(def.id, scene.facts, scene.agents);
      let at = null;
      if (words && plaqueShownAt(def, level) && this.suppressed !== def.id) {
        if (words.key !== item.key) {
          item.key = words.key;
          item.eyebrow.textContent = words.eyebrow;
          item.value.textContent = words.value;
          item.el.dataset.tone = words.tone;
          item.size = null;
        }
        if (level !== item.level) {
          item.level = level;
          item.el.dataset.level = level;
          item.size = null;
        }
        if (!item.size) item.size = { w: item.el.offsetWidth, h: item.el.offsetHeight };
        const [x, y, w, h] = def.anchor;
        const a = scene.toScreen(x, y);
        const b = scene.toScreen(x + w, y + h);
        at = placePlaque({ x: a.x, y: a.y, w: b.x - a.x, h: b.y - a.y }, item.size, def.sides, scene.room, blocked);
        if (at) blocked.push({ x: at.x - 4, y: at.y - 4, w: item.size.w + 8, h: item.size.h + 8 });
      }
      const place = at ? `${at.x},${at.y},${at.side}` : 'none';
      if (place === item.place) continue;
      item.place = place;
      item.el.dataset.shown = at ? 'true' : 'false';
      if (at) {
        item.el.style.transform = `translate(${at.x}px, ${at.y}px)`;
        item.el.dataset.side = at.side;
      }
    }
  }
}
