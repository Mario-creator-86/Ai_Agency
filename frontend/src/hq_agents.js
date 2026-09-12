/**
 * AgentVisualStateManager: what each employee is seen doing, from backend state and nothing else.
 *
 * The sprite follows the agent's runtime state and lifecycle: WORKING types, THINKING thinks,
 * PAUSED sleeps at the desk, ERROR and BLOCKED hold their head, IDLE sits back. A speech bubble
 * from a real message makes the agent talk. A big event outside (fireworks, the UFO) turns the
 * head of an agent who is idle; an agent at work keeps working, because the work is real.
 * The employee's look comes from the Character Bible the backend serves.
 */

/** @param {any} agent */
export function stateOf(agent) {
  const lifecycle = String(agent?.lifecycle || '').toUpperCase();
  if (lifecycle === 'PAUSED' || lifecycle === 'SUSPENDED') return 'PAUSED';
  return String(agent?.runtime_state || 'IDLE').toUpperCase();
}

/**
 * @param {any} agent
 * @param {boolean} talking
 */
export function animationFor(agent, talking) {
  const state = stateOf(agent);
  if (state === 'PAUSED') return 'sit_sleep';
  if (state === 'ERROR' || state === 'BLOCKED' || state === 'FAILED') return 'sit_error';
  if (talking) return 'sit_talk';
  if (state === 'WORKING' || state === 'EXECUTING' || state === 'RUNNING') return 'sit_type';
  if (state === 'THINKING' || state === 'PLANNING' || state === 'REVIEWING') return 'sit_think';
  return 'sit_idle';
}

/** Frames per second per animation; idle frames hold, typing moves. */
export const ANIMATION_FPS = { sit_type: 7, sit_think: 0.8, sit_talk: 3, sit_sleep: 0.6, sit_error: 2.5, sit_idle: 0.35, stand_idle: 0.4, stand_react: 2, walk_right: 9 };

/** Which sprite a desk seats when no Bible record names the agent (the seed's roles). */
export const DESK_SPRITES = {
  desk_director: 'sarah',
  desk_research_1: 'aris',
  desk_research_2: 'elena',
  desk_script: 'marcus',
  desk_audio: 'lyra',
  desk_video: 'kael',
  desk_publish: 'vera',
  desk_accounting: 'nadia',
};

/**
 * The sprite for an agent: the Bible record whose first name the agent carries, then the role,
 * then the desk the backend assigned.
 * @param {any} agent
 * @param {any} atlas characters.json
 */
export function spriteFor(agent, atlas) {
  const characters = atlas?.characters || {};
  const name = String(agent?.display_name || '').trim().split(/[\s(]+/)[0].toLowerCase();
  for (const [key, c] of Object.entries(characters)) {
    const canonical = String(/** @type {any} */ (c).canonical_name || '').split(/\s+/)[0].toLowerCase().replace(/[^a-z]/g, '');
    if (name && canonical && name.replace(/[^a-z]/g, '') === canonical) return key;
  }
  const role = String(agent?.role_name || '').toLowerCase();
  for (const [key, c] of Object.entries(characters)) {
    const r = String(/** @type {any} */ (c).role || '').toLowerCase();
    if (role && r && (r === role || r.includes(role) || role.includes(r))) return key;
  }
  const desk = /** @type {Record<string,string>} */ (DESK_SPRITES)[agent?.desk_id];
  return desk && characters[desk] ? desk : null;
}

/** What an agent's screen shows: the same state, seen on the monitor. @param {any} agent */
export function screenModeFor(agent) {
  const state = stateOf(agent);
  if (state === 'PAUSED') return 'off';
  if (state === 'WORKING' || state === 'EXECUTING' || state === 'RUNNING') return 'active';
  if (state === 'THINKING' || state === 'PLANNING') return 'thinking';
  if (state === 'ERROR' || state === 'BLOCKED') return 'error';
  return 'idle';
}

export class AgentVisualStateManager {
  /** @param {() => number} rng */
  constructor(rng) {
    this.rng = rng;
    this.clock = 0;
    /** @type {Map<string, number>} */
    this.phase = new Map();
    /** @type {Map<string, number>} */
    this.reactUntil = new Map();
  }

  /** @param {number} dt */
  update(dt) {
    this.clock += dt;
  }

  /** Idle agents look up for a moment; working agents do not stop. @param {any[]} agents @param {number} seconds */
  react(agents, seconds) {
    for (const agent of agents) {
      if (animationFor(agent, false) === 'sit_idle') this.reactUntil.set(agent.id || agent.agent_id, this.clock + seconds);
    }
  }

  /**
   * The animation and frame index to draw.
   * @param {any} agent
   * @param {any} atlasEntry one entry of characters.json
   * @param {string} facing 'front' | 'back'
   * @param {boolean} talking
   */
  frame(agent, atlasEntry, facing, talking) {
    const id = agent.id || agent.agent_id;
    if (!this.phase.has(id)) this.phase.set(id, this.rng() * 10);
    let anim = animationFor(agent, talking);
    const reacting = (this.reactUntil.get(id) ?? 0) > this.clock && anim === 'sit_idle';
    if (reacting) anim = 'sit_talk';
    const key = `${anim}_${facing}`;
    const frames = atlasEntry?.animations?.[key] || atlasEntry?.animations?.[`sit_idle_${facing}`] || [];
    if (!frames.length) return null;
    const fps = /** @type {Record<string,number>} */ (ANIMATION_FPS)[anim] ?? 1;
    const t = this.clock + (this.phase.get(id) ?? 0);
    let index;
    if (anim === 'sit_idle') {
      // eyes open most of the time; a blink is the second frame for a fraction of a second
      index = (t % 4.2) < 0.16 ? 1 : 0;
    } else {
      index = Math.floor(t * fps) % frames.length;
    }
    return { anim, key, index: frames[Math.min(index, frames.length - 1)] };
  }
}
