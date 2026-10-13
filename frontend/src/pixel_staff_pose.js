import { PIXEL_LAYOUT } from './pixel_desks.js';
const SETTINGS = PIXEL_LAYOUT.life.staff_motion;

/** Whole person-and-chair asset, uniformly scaled and anchored to the room floor. */
export function seatedGeometry(frame, center, floor, height, seating = null) {
  const scale = (seating?.ensemble_height ?? height) * PIXEL_LAYOUT.life.character_scale / frame.height;
  const feetY = seating?.floor_y ?? floor;
  return { scale, left: (seating?.ensemble_x ?? center) - frame.anchor_x * scale,
    top: feetY - frame.height * scale, width: frame.width * scale,
    height: frame.height * scale, feetY };
}

/** Joint motion decorates actual states; chair, hips, legs and shoes stay rigid. */
export function poseTarget(motion) {
  if (!motion.animate) return { head: 0, hand: 0, breath: 1 };
  const t = motion.elapsed;
  const work = ['WORKING', 'REVIEWING'].includes(motion.mode);
  const bias = motion.mode === 'THINKING' ? SETTINGS.thinking_head_radians
    : motion.mode === 'REVIEWING' ? SETTINGS.review_head_radians : 0;
  return {
    head: SETTINGS.head_radians * Math.sin(t * Math.PI * 2 / SETTINGS.head_cycle_ms) + bias,
    hand: SETTINGS.hand_radians * (work ? 1 : SETTINGS.hand_idle_amplitude) * Math.sin(t * Math.PI * 2 / (work ? SETTINGS.work_hand_cycle_ms : SETTINGS.idle_hand_cycle_ms)),
    breath: 1 + SETTINGS.breath_scale * (0.5 + 0.5 * Math.sin(t * Math.PI * 2 / PIXEL_LAYOUT.life.breath_cycle_ms)),
  };
}

/** State transitions are eased; a paused or disconnected view keeps its last pose. */
export class StaffPoseTrack {
  constructor() { this.people = new Map(); }
  frame(id, motion) {
    const target = poseTarget(motion), at = motion.elapsed;
    let track = this.people.get(id);
    if (!track) {
      track = { mode: motion.mode, at, from: target, current: target, sampledAt: at };
      if (this.people.size >= 64) this.people.delete(this.people.keys().next().value);
      this.people.set(id, track);
    }
    if (!motion.animate) return track.current;
    if (track.mode !== motion.mode || at < track.sampledAt) {
      track.from = track.current; track.at = at; track.mode = motion.mode;
    }
    const progress = Math.max(0, Math.min(1, (at - track.at) / SETTINGS.blend_ms));
    const ease = progress * progress * (3 - 2 * progress);
    track.current = Object.fromEntries(Object.entries(target).map(([key, value]) => [key, track.from[key] + (value - track.from[key]) * ease]));
    track.sampledAt = at;
    return track.current;
  }
}
