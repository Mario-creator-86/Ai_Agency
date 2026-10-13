import SETTINGS from '../../config/pixel_presentation.json' with { type: 'json' };
export { SETTINGS as PRESENTATION };

/** A recent authenticated HTTP policy can bridge event-stream reconnection, never stale data. */
export function presentationLive(signals,received,now=Date.now()){
  return signals.data==='fresh' && (signals.socket==='open' || (received>0 && now>=received && now-received<SETTINGS.valid_ms));
}

/** A visual action is authorized by a fresh, matching server snapshot, never random UI state. */
export function presentationAction(plan, agent, elapsed, received, now = Date.now()) {
  if (!plan || now - received > SETTINGS.valid_ms || now < received
      || plan.lifecycle !== agent.lifecycle || plan.runtime_state !== agent.runtime_state
      || Number(plan.version) !== Number(agent.version || 0)) return null;
  const cycle = plan.cycle;
  if (!Array.isArray(cycle) || !cycle.length) return { action: 'rest', progress: 0, monitor: 'off', authorized: true };
  const duration = cycle.reduce((n, item) => n + item[1], 0);
  if (!Number.isFinite(duration) || duration <= 0) return null;
  let phase = ((plan.phase_ms + Math.max(0, elapsed)) % duration + duration) % duration;
  for (const [action, ms] of cycle) {
    if (phase < ms) return { action, progress: phase / ms, monitor: action === 'screen_off' ? 'off' : 'on', authorized: true };
    phase -= ms;
  }
  return null;
}

export const poseColumn = action => ['think', 'frustrated'].includes(action) ? 1 : action === 'coffee' ? 2 : action === 'hair' ? 3 : 0;

/** Stable spring integration; fixed feet/chair contacts, bounded upper-body reach. */
export class SeatedPhysics {
  constructor() { this.people = new Map(); }
  frame(id, motion, seating) {
    let p = this.people.get(id);
    const action = motion.action || 'look', column = poseColumn(action);
    if (!p) {
      if (this.people.size >= 64) this.people.delete(this.people.keys().next().value);
      p = { at: motion.elapsed, action, weights: [0,0,0,0], velocity: [0,0,0,0], lean: 0, leanVelocity: 0, head: 0 };
      p.weights[column] = 1; this.people.set(id,p);
    }
    if (motion.animate) {
      let remaining = Math.min(SETTINGS.max_catchup_ms, Math.max(0, motion.elapsed - p.at));
      const omega = SETTINGS.spring_hz * Math.PI * 2;
      const target = ['type','mouse','read','write'].includes(action) ? -0.9 : action === 'frustrated' ? 0.5 : action === 'relax' ? 0.85 : 0;
      while (remaining > 0.001) {
        const dt = Math.min(SETTINGS.fixed_step_ms,remaining)/1000; remaining -= dt*1000;
        for (let i=0;i<4;i++) {
          p.velocity[i] += (omega*omega*((i===column?1:0)-p.weights[i])-2*SETTINGS.damping*omega*p.velocity[i])*dt;
          p.weights[i] = Math.max(0,Math.min(1,p.weights[i]+p.velocity[i]*dt));
        }
        p.leanVelocity += (omega*omega*(target-p.lean)-2*SETTINGS.damping*omega*p.leanVelocity)*dt;
        p.lean = Math.max(-1,Math.min(1,p.lean+p.leanVelocity*dt));
      }
      p.action=action; p.at=motion.elapsed;
      const gaze = Math.atan2((seating?.monitor?.[0] ?? seating?.ensemble_x ?? 0)-(seating?.ensemble_x ?? 0), 120);
      const wind = motion.wind || 0;
      const reaction=action==='frustrated'?Math.sin((motion.progress||0)*Math.PI*6)*Math.sin((motion.progress||0)*Math.PI)*.055:0;
      p.head = Math.max(-SETTINGS.physics.head_limit_radians,Math.min(SETTINGS.physics.head_limit_radians,
        gaze*0.18 + Math.sin(motion.elapsed/2200)*0.013 + Math.sin(motion.elapsed/390)*Math.min(1,wind/30)*0.015 + reaction));
    }
    const sum=p.weights.reduce((a,b)=>a+b,0)||1;
    const feet=seating?.contacts?.feet||[],plane=seating?.floor_plane;
    const grounded=Boolean(plane && feet.length===2 && feet.every(([x,y])=>x>=plane.min_x&&x<=plane.max_x&&y>=plane.far_y&&y<=plane.near_y
      && (seating.solids||[]).every(s=>x<s.x||x>s.x+s.w||y<s.y||y>s.y+s.h)));
    return { action:p.action, weights:p.weights.map(w=>w/sum), lean:p.lean, head:p.head,
      feet, chair: seating?.contacts?.chair || [],
      grounded, floor:seating?.floor_y,
      reach: Math.min(SETTINGS.physics.reach_limit, Math.abs(p.lean)*7) };
  }
}
