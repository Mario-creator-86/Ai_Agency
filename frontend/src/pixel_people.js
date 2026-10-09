// Original layered pixel characters. Identity is independent of pose and working state.
import { PIXEL_LAYOUT } from './pixel_desks.js';
import { paintSeated, paintDeskHands } from './pixel_seated_art.js';
import { drawStaffAtlas } from './pixel_actor_atlas.js';
export { shade } from './pixel_art.js';
const LIFE = PIXEL_LAYOUT.life;
const COATS = ['#749b9e', '#b27668', '#c5a46d', '#8c7fa0', '#7b9870', '#62789c'];
const HAIR = ['#352f3e', '#724736', '#b48558', '#545260'];
const SKIN = ['#dfae89', '#c38e6c', '#af765c', '#edc29b'];
const INK = '#282b38';
const frames = new Map();

export function identitySeed(id) {
  let n = 2166136261;
  for (const c of String(id)) n = Math.imul(n ^ c.charCodeAt(0), 16777619);
  return n >>> 0;
}

function ink(value, fallback) { return /^#[0-9a-f]{6}$/i.test(String(value)) ? value : fallback; }
function first(palette, keys, fallback) { return ink(keys.map(k => palette[k]).find(Boolean), fallback); }
/** Only the Bible's employee_id binds appearance; similar names never replace someone's identity. */
export function characterProfile(agent, character = null) {
  const seed = identitySeed(agent.id || agent.agent_id);
  const palette = character?.palette_json || {};
  const description = String(character?.face_hair_desc || '').toLowerCase();
  const props = String(character?.props_desc || '').toLowerCase();
  const role = String(agent.role_name || '').toLowerCase();
  const hairStyle = /bun/.test(description) ? 'bun' : /bob/.test(description) ? 'bob'
    : /sleek|streak/.test(description) ? 'long' : /spiky|tousled|wavy/.test(description) ? 'wavy'
    : ['short', 'bob', 'wavy', 'long'][seed % 4];
  const profile = {
    seed, hairStyle, employeeId: String(agent.id || agent.agent_id),
    skin: first(palette, ['skin'], SKIN[(seed >>> 4) % SKIN.length]),
    coat: first(palette, ['coat', 'suit', 'vest', 'hoodie', 'sweater', 'shirt', 'blazer', 'cardigan'], COATS[(seed >>> 8) % COATS.length]),
    shirt: first(palette, ['shirt', 'tie'], '#e8ddbd'),
    hair: first(palette, ['hair', 'bun'], HAIR[seed % HAIR.length]),
    accent: first(palette, ['headphones', 'headset', 'tie', 'glasses'], '#c9aa72'),
    glasses: Boolean(palette.glasses || /spectacles|glasses/.test(description)),
    headset: Boolean(palette.headphones || palette.headset || /headset|headphone|microphone/.test(description + props)),
    streak: /streak/.test(description),
    silver: /silver/.test(description),
    beard: /shadow|beard/.test(description),
    ledger: /ledger/.test(props) || role === 'accountant',
    role,
    desk: first(palette, ['desk'], '#9b6343'),
  };
  return { ...profile, key: JSON.stringify(profile) };
}

/** A pose decorates the actual backend state; it never writes or randomly changes that state. */
export function characterMotion(agent, time = 0, live = false, reduced = false, replay = false) {
  const lifecycle = String(agent.lifecycle || 'UNKNOWN').toUpperCase();
  const runtime = String(agent.runtime_state || 'UNKNOWN').toUpperCase();
  const mode = ['PAUSED', 'SUSPENDED'].includes(lifecycle) ? 'PAUSED'
    : ['WORKING', 'EXECUTING', 'RUNNING'].includes(runtime) ? 'WORKING'
    : ['THINKING', 'PLANNING'].includes(runtime) ? 'THINKING'
    : runtime === 'REVIEWING' ? 'REVIEWING'
    : ['ERROR', 'FAILED'].includes(runtime) ? 'ERROR'
    : runtime === 'BLOCKED' ? 'BLOCKED' : runtime === 'IDLE' ? 'IDLE' : 'UNKNOWN';
  const animate = Boolean(live && !reduced && !replay && lifecycle === 'ACTIVE' && ['IDLE', 'WORKING', 'THINKING', 'REVIEWING'].includes(mode));
  const seed = identitySeed(agent.id || agent.agent_id);
  const elapsed = animate ? Math.max(0, time) + seed % (LIFE.gesture_cycle_ms + seed % 7000) : 0;
  const cycle = elapsed % (LIFE.gesture_cycle_ms + seed % 7000);
  const workPhase = Math.floor((elapsed % LIFE.work_cycle_ms) / (LIFE.work_cycle_ms / 4));
  const role = String(agent.role_name || '').toLowerCase();
  const primary = /accountant/.test(role) ? 'write' : /editor|publisher/.test(role) ? 'mouse'
    : /research|fact/.test(role) ? 'read' : /voice/.test(role) ? 'headset' : 'type';
  let gesture = 'rest';
  if (mode === 'WORKING') gesture = [primary, primary, 'mouse', 'read'][workPhase];
  else if (mode === 'THINKING') gesture = workPhase < 2 ? 'chin' : 'look';
  else if (mode === 'REVIEWING') gesture = workPhase < 3 ? 'read' : 'write';
  else if (mode === 'IDLE' && animate) gesture = cycle > 28500 ? 'stretch' : cycle > 23500 ? 'sip' : cycle > 18000 ? 'look' : 'rest';
  const glance = animate && gesture === 'look' ? (workPhase % 2 ? -1 : 1) : 0;
  return {
    mode, animate,
    gesture, gestureFrame: animate ? Math.floor(elapsed / 240) % 4 : 0,
    sway: animate && ['look', 'stretch'].includes(gesture) ? (Math.floor(elapsed / 900) % 3) - 1 : 0,
    frame: animate ? Math.floor(elapsed / (mode === 'WORKING' ? 180 : 650)) % 4 : 0,
    breath: animate ? [0, 1, 2, 1][Math.floor(elapsed / (LIFE.breath_cycle_ms / 4)) % 4] : 0,
    blink: animate && elapsed % (6800 + seed % 1400) < 140,
    glance,
    color: mode === 'ERROR' ? '#dc847b' : ['BLOCKED', 'PAUSED'].includes(mode) ? '#d4b273'
      : mode === 'THINKING' ? '#ada1cc' : mode === 'WORKING' ? '#78bbaf'
      : mode === 'REVIEWING' ? '#a1b985' : mode === 'UNKNOWN' ? '#aaa0a2' : '#dfd4bc',
  };
}

/** Cache compact sprite frames; device scaling stays crisp and repeated poses allocate no canvas. */
export function drawSeatedPerson(ctx, profile, motion, center, floor, scale = 1.6, portrait = false, orientation = 'side', seating = null) {
  if(drawStaffAtlas(ctx,profile,motion,center,floor,scale,portrait,false,seating))return;
  const back = orientation === 'back' && !portrait;
  const key = `${profile.key}:${motion.mode}:${motion.frame}:${motion.breath}:${motion.blink}:${motion.glance}:${motion.gesture}:${motion.gestureFrame}:${motion.sway}:${portrait}:${back}`;
  let sprite = frames.get(key);
  if (!sprite && typeof document !== 'undefined') {
    sprite = document.createElement('canvas'); sprite.width = 48; sprite.height = 60;
    paintSeated(sprite.getContext('2d'), profile, motion, portrait, back);
    if (frames.size >= 512) frames.delete(frames.keys().next().value);
    frames.set(key, sprite);
  }
  const left = Math.round(center - 16 * scale);
  const top = Math.round(floor - 40 * scale);
  ctx.imageSmoothingEnabled = false;
  if (sprite) ctx.drawImage(sprite, left, top, 32 * scale, 40 * scale);
  else { ctx.save(); ctx.translate(left, top); ctx.scale(scale * 2 / 3, scale * 2 / 3); paintSeated(ctx, profile, motion, portrait, back); ctx.restore(); }
}

/** Hands and small tools belong above the chair's foreground, while the body stays seated. */
export function drawDeskGesture(ctx, profile, motion, center, floor, scale = 1.5, seating = null) {
  if(drawStaffAtlas(ctx,profile,motion,center,floor,scale,false,true,seating))return;
  ctx.save(); ctx.translate(Math.round(center - 16 * scale), Math.round(floor - 40 * scale));
  ctx.scale(scale * 2 / 3, scale * 2 / 3); paintDeskHands(ctx, profile, motion); ctx.restore();
}
