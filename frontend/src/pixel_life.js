import { PIXEL_LAYOUT } from './pixel_desks.js';
import { weatherEffects } from './hq_weather.js';
import { drawPedestrian, drawBicycle, drawCat, drawDog } from './pixel_town_people.js';
import { pixelPen } from './pixel_art.js';
import { drawCar } from './pixel_vehicle.js';
const LIFE = PIXEL_LAYOUT.life;
const W = PIXEL_LAYOUT.world.width;

export function ambientMoves({ live, reduced, replay, parked, hidden }) {
  return Boolean(live && !reduced && !replay && !parked && !hidden);
}

/** Decorative townspeople are separate from the real workforce and never emit work events. */
export function streetFrame(elapsed, weather, night) {
  const t = Number.isFinite(elapsed) ? Math.max(0, elapsed) : 0;
  const effects = weatherEffects(weather);
  const wet = effects.rain > 0;
  const progress = (period, offset) => ((t / period + offset) % 1) * (W + 2 * LIFE.street_margin) - LIFE.street_margin;
  const people = Array.from({ length: LIFE.pedestrian_count }, (_, i) => ({
    kind: 'pedestrian', id: i, x: i % 2 ? W - progress(LIFE.pedestrian_cycle_ms, LIFE.pedestrian_offsets[i % LIFE.pedestrian_offsets.length]) : progress(LIFE.pedestrian_cycle_ms, LIFE.pedestrian_offsets[i % LIFE.pedestrian_offsets.length]),
    y: LIFE.sidewalk_y + (i % 2 ? 3 : -2), direction: i % 2 ? -1 : 1, step: Math.floor(t / LIFE.pedestrian_step_ms + i * 2) % 8, blink: (t + i * 997) % 5700 < 160, umbrella: wet,
  }));
  return { people,
    bicycle: { x: progress(LIFE.cycle_cycle_ms, 0.63), y: LIFE.sidewalk_y + 7, direction: 1, step: Math.floor(t / LIFE.pedal_step_ms) % 8 },
    car: { x: W - progress(LIFE.car_cycle_ms, 0), y: LIFE.road_y, direction: -1, variant: Math.floor(t / LIFE.car_cycle_ms) % 4, elapsed: t, lights: night },
    cat: catFrame(t, LIFE.cat, 0),
    cats: [LIFE.cat, ...LIFE.extra_cats].map((cat, id) => catFrame(t, cat, id)),
    dog: people[2] ? { x: people[2].x + 29 * people[2].direction, y: people[2].y + 2, direction: people[2].direction, step: Math.floor(t / LIFE.dog_step_ms) % 8 } : null,
    bird: { x: Math.round(progress(LIFE.bird_cycle_ms, 0.3)), y: LIFE.bird_y + Math.round(Math.sin(t / 3000) * 3), step: Math.floor(t / 180) % 2 },
    moths: Boolean(night && weather?.available && !effects.rain && !effects.snow && !effects.fog), t };
}

function catFrame(t, position, id) {
  const leg = LIFE.cat_walk_ms + LIFE.cat_sit_ms + LIFE.cat_groom_ms + LIFE.cat_stretch_ms;
  const phase = (t + id * LIFE.cat_phase_offset_ms) % (2 * leg), part = phase % leg;
  const direction = phase < leg ? 1 : -1;
  const u = Math.min(1, part / LIFE.cat_walk_ms);
  const start = direction === 1 ? position.min_x : position.max_x;
  const end = direction === 1 ? position.max_x : position.min_x;
  return { id, x: start + (end-start)*u, y: position.y, direction,
    pose: part < LIFE.cat_walk_ms ? 'walk' : part < LIFE.cat_walk_ms + LIFE.cat_sit_ms ? 'sit'
      : part < LIFE.cat_walk_ms + LIFE.cat_sit_ms + LIFE.cat_groom_ms ? 'groom' : 'stretch',
    step: Math.floor(t / LIFE.cat_step_ms + id) % 8, blink: (t + id * 1900) % 4900 < 160 };
}

/** Original detailed pixel sprites, clipped to their own street/sky layers. */
export function drawOutdoorLife(ctx, weather, elapsed, moment) {
  const night = moment.daylight < 0.4;
  const frame = streetFrame(elapsed, weather, night);
  ctx.save(); ctx.beginPath(); ctx.rect(0, 0, W, PIXEL_LAYOUT.world.height); ctx.clip();
  const sidewalk = LIFE.sidewalk_clip, road = LIFE.road_clip;
  ctx.save(); ctx.beginPath(); ctx.rect(sidewalk.x, sidewalk.y, sidewalk.width, sidewalk.height); ctx.clip();
  if (frame.dog) {
    const owner = frame.people[2], d = frame.dog;
    pixelPen(ctx).line(owner.x + 4 * owner.direction, owner.y - 17, d.x - 5 * d.direction, d.y - 8, '#b39e88');
    drawDog(ctx, d);
  }
  const walkers = frame.people.map(p => ({ y: p.y, draw: () => drawPedestrian(ctx, p) }));
  walkers.push({ y: frame.bicycle.y, draw: () => drawBicycle(ctx, frame.bicycle) });
  for (const cat of frame.cats) walkers.push({ y: cat.y, draw: () => drawCat(ctx, cat) });
  for (const actor of walkers.sort((a,b) => a.y - b.y)) actor.draw();
  ctx.restore();
  ctx.save(); ctx.beginPath(); ctx.rect(road.x, road.y, road.width, road.height); ctx.clip();
  drawCar(ctx, frame.car, weatherEffects(weather).rain > 0); ctx.restore();
  if (!night) {
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, W, 48); ctx.clip(); ctx.fillStyle = '#3a405d';
    for (let i = 0; i < 3; i++) {
      const x = frame.bird.x + i * 11, y = frame.bird.y + i * 3, wing = frame.bird.step ? -2 : 1;
      ctx.fillRect(x, y, 2, 1); ctx.fillRect(x - 3, y + wing, 3, 1); ctx.fillRect(x + 2, y + wing, 3, 1);
    }
    ctx.restore();
  }
  if (night) {
    for (let i = 0; i < LIFE.windows.length; i++) {
      const w = LIFE.windows[i]; ctx.globalAlpha = 0.35 + 0.2 * Math.sin(elapsed / 4300 + i);
      ctx.fillStyle = LIFE.palette.light; ctx.fillRect(w.x, w.y, 2, 4);
    }
    ctx.globalAlpha = 1;
  }
  if (frame.moths) {
    ctx.fillStyle = '#f8dd9b';
    for (const lamp of PIXEL_LAYOUT.outdoors.lamps) for (let i = 0; i < 2; i++) {
      const phase = elapsed / 1400 + i * 2.6;
      ctx.fillRect(lamp.x + Math.round(Math.sin(phase) * 8), lamp.y - 12 + Math.round(Math.cos(phase * 1.3) * 5), 1, 1);
    }
  }
  ctx.restore(); return frame;
}
