import { PIXEL_LAYOUT } from './pixel_desks.js';
import { weatherEffects } from './hq_weather.js';
import { drawPedestrian, drawBicycle, drawCat, drawDog } from './pixel_town_people.js';
import { pixelPen } from './pixel_art.js';
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
  const progress = (period, offset) => ((t / period + offset) % 1) * (W + 100) - 50;
  const people = Array.from({ length: LIFE.pedestrian_count }, (_, i) => ({
    kind: 'pedestrian', id: i, x: Math.round(i % 2 ? W - progress(LIFE.pedestrian_cycle_ms, (i + 1) / (LIFE.pedestrian_count + 1)) : progress(LIFE.pedestrian_cycle_ms, (i + 1) / (LIFE.pedestrian_count + 1))),
    y: LIFE.sidewalk_y + (i % 2 ? 3 : -2), direction: i % 2 ? -1 : 1, step: Math.floor(t / 150 + i * 2) % 8, blink: (t + i * 997) % 5700 < 160, umbrella: wet,
  }));
  return { people,
    bicycle: { x: Math.round(progress(LIFE.cycle_cycle_ms, 0.63)), y: LIFE.sidewalk_y + 7, step: Math.floor(t / 140) % 8 },
    car: { x: Math.round(W - progress(LIFE.car_cycle_ms, 0.3)), y: LIFE.road_y, lights: night },
    cat: catFrame(t, LIFE.cat, 0),
    cats: [LIFE.cat, ...LIFE.extra_cats].map((cat, id) => catFrame(t, cat, id)),
    dog: people[2] ? { x: people[2].x + 29 * people[2].direction, y: people[2].y + 2, direction: people[2].direction, step: Math.floor(t / 140) % 8 } : null,
    bird: { x: Math.round(progress(LIFE.bird_cycle_ms, 0.3)), y: LIFE.bird_y + Math.round(Math.sin(t / 3000) * 3), step: Math.floor(t / 180) % 2 },
    moths: Boolean(night && weather?.available && !effects.rain && !effects.snow && !effects.fog), t };
}

function catFrame(t, position, id) {
  const phase = (t + id * 9200) % 56000, part = phase % 28000;
  const direction = phase < 28000 ? 1 : -1;
  const travel = part < 8000 ? -10 + part / 8000 * 20 : 10;
  return { id, x: position.x + Math.round(travel * direction), y: position.y, direction,
    pose: part < 8000 ? 'walk' : part < 16000 ? 'sit' : part < 23000 ? 'groom' : 'stretch',
    step: Math.floor(t / 140 + id) % 8, blink: (t + id * 1900) % 4900 < 160 };
}

function car(ctx, car, wet) {
  const x = car.x, y = car.y, p = LIFE.palette;
  const r = (dx, dy, w, h, colour) => { ctx.fillStyle = colour; ctx.fillRect(x + dx, y + dy, w, h); };
  if (car.lights) { r(-25, -2, 19, 2, '#ffe5ac38'); r(-34, 0, 31, 1, '#ffe5ac20'); }
  if (wet) r(-4, 5, 43, 1, '#b9af8640');
  r(-2, -1, 46, 4, '#222637a0'); r(0, -10, 40, 10, p.ink); r(3, -12, 33, 3, p.car);
  r(8, -19, 25, 8, p.ink); r(10, -18, 20, 7, p.car); r(9, -16, 11, 4, '#c8c5ac'); r(22, -16, 7, 4, '#8fa8b2');
  r(2, -9, 35, 7, p.car); r(5, -8, 26, 1, '#809e9e'); r(18, -5, 5, 1, '#b8b7a1');
  for (const wheel of [8, 32]) { r(wheel - 3, -3, 7, 6, p.ink); r(wheel - 1, -2, 3, 3, '#b1b5b3'); }
  r(0, -7, 3, 3, car.lights ? p.light : '#b8bcbc'); r(38, -6, 2, 3, '#be7770');
}

/** Original detailed pixel sprites, clipped to their own street/sky layers. */
export function drawOutdoorLife(ctx, weather, elapsed, moment) {
  const night = moment.daylight < 0.4;
  const frame = streetFrame(elapsed, weather, night);
  ctx.save(); ctx.beginPath(); ctx.rect(0, 0, W, PIXEL_LAYOUT.world.height); ctx.clip();
  ctx.save(); ctx.beginPath(); ctx.rect(147, LIFE.sidewalk_y - 68, W - 165, 78); ctx.clip();
  if (frame.dog) {
    const owner = frame.people[2], d = frame.dog;
    pixelPen(ctx).line(owner.x + 4 * owner.direction, owner.y - 17, d.x - 5 * d.direction, d.y - 8, '#b39e88');
    drawDog(ctx, d);
  }
  const walkers = frame.people.map(p => ({ y: p.y, draw: () => drawPedestrian(ctx, p) }));
  walkers.push({ y: frame.bicycle.y, draw: () => drawBicycle(ctx, frame.bicycle) });
  for (const actor of walkers.sort((a,b) => a.y - b.y)) actor.draw();
  ctx.restore();
  ctx.save(); ctx.beginPath(); ctx.rect(156, LIFE.road_y - 21, W - 156, 30); ctx.clip();
  car(ctx, frame.car, weatherEffects(weather).rain > 0); ctx.restore();
  for (const cat of frame.cats) drawCat(ctx, cat);
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
