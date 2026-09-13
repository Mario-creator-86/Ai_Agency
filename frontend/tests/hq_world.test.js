import test from 'node:test';
import assert from 'node:assert/strict';
import { solarElevation, timeOfDay, skyStops } from '../src/hq_time.js';
import { normalizeWeather, weatherEffects, WeatherManager } from '../src/hq_weather.js';
import { RandomEventManager, validateEvent, RARITY_RATE } from '../src/hq_events.js';
import { TrafficManager } from '../src/hq_traffic.js';
import { PedestrianManager } from '../src/hq_pedestrians.js';
import { animationFor, spriteFor, screenModeFor, AgentVisualStateManager } from '../src/hq_agents.js';
import { mulberry32, streetLight } from '../src/hq_world.js';
import fs from 'node:fs';

const EVENTS = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/world_events.json', import.meta.url), 'utf8'));
const MANIFEST = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/manifest.json', import.meta.url), 'utf8'));
const VEHICLES = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/vehicles/vehicles.json', import.meta.url), 'utf8'));
const CHARACTERS = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/characters/characters.json', import.meta.url), 'utf8'));

/* ------------------------------------------------------------------ time of day */

test('the sun over Bucharest: high at a June noon, far below the horizon at a December midnight', () => {
  assert.ok(solarElevation(new Date('2026-06-21T10:00:00Z')) > 60);
  assert.ok(solarElevation(new Date('2026-12-21T22:00:00Z')) < -50);
  const september = solarElevation(new Date('2026-09-13T16:00:00Z'));
  assert.ok(september > -3 && september < 12, `mid-September 19:00 local is near sunset (${september})`);
});

test('phases follow the sun, not a fixed hour table', () => {
  assert.equal(timeOfDay(new Date('2026-06-21T10:00:00Z')).phase, 'day');
  assert.equal(timeOfDay(new Date('2026-06-21T23:00:00Z')).phase, 'night');
  // 17:30 local in December is already dark; in June it is broad daylight
  assert.equal(timeOfDay(new Date('2026-12-15T15:30:00Z')).phase, 'night');
  assert.equal(timeOfDay(new Date('2026-06-15T14:30:00Z')).phase, 'day');
});

test('the sky darkens under cloud and warms at dusk', () => {
  const clearDay = skyStops({ daylight: 1, dusk: 0 }, { cloudiness: 0, fog: 0 });
  const cloudyDay = skyStops({ daylight: 1, dusk: 0 }, { cloudiness: 1, fog: 0 });
  assert.notEqual(clearDay[0][1], cloudyDay[0][1]);
  assert.equal(clearDay.length, 4);
});

/* ------------------------------------------------------------------ weather */

test('unknown weather draws nothing: no rain, no fog, no clouds invented', () => {
  const state = normalizeWeather({ available: false, reason: 'not_configured' });
  assert.equal(state.available, false);
  assert.deepEqual(weatherEffects(state), { cloudiness: 0, rain: 0, snow: 0, fog: 0, storm: false, wet: 0, wind: 0 });
  assert.equal(normalizeWeather({ available: true, condition: 'volcanic_ash' }).available, false);
});

test('real rain wets the street and brings umbrellas', () => {
  const fx = weatherEffects(normalizeWeather({ available: true, condition: 'rain', intensity: 1, temperature_c: 12 }));
  assert.ok(fx.rain > 0.9 && fx.wet === 1);
});

test('a weather service that fails leaves the scene without weather, labelled as unavailable', async () => {
  const manager = new WeatherManager(async () => {
    throw new Error('down');
  });
  await manager.refresh();
  assert.equal(manager.state.available, false);
  assert.equal(manager.label(), 'Weather unavailable');
});

/* ------------------------------------------------------------------ random events */

test('every configured event is valid and the UFO is the rarest thing in the sky', () => {
  for (const raw of EVENTS.events) assert.ok(validateEvent(raw), raw.eventId);
  const ufo = EVENTS.events.find((e) => e.eventId === 'ufo_flyover');
  assert.equal(ufo.rarity, 'very_rare');
  assert.ok(RARITY_RATE.very_rare < RARITY_RATE.rare / 10);
});

test('the UFO never appears by day, in rain, or twice within its cooldown', () => {
  const manager = new RandomEventManager(EVENTS, mulberry32(1));
  const ufo = manager.definitions.find((d) => d.eventId === 'ufo_flyover');
  assert.equal(manager.eligible(ufo, { weather: 'clear', phase: 'day' }), false);
  assert.equal(manager.eligible(ufo, { weather: 'rain', phase: 'night' }), false);
  assert.equal(manager.eligible(ufo, { weather: 'clear', phase: 'night' }), true);
  manager.start(ufo);
  manager.update(ufo.duration[1] + 1, { weather: 'clear', phase: 'night' });
  assert.equal(manager.eligible(ufo, { weather: 'clear', phase: 'night' }), false, 'still cooling down');
});

test('the same seed replays the same day of events', () => {
  const run = () => {
    const manager = new RandomEventManager(EVENTS, mulberry32(42));
    const started = [];
    manager.on((kind, ev) => kind === 'start' && started.push(ev.def.eventId));
    for (let i = 0; i < 3600; i += 1) manager.update(1, { weather: 'clear', phase: i < 1800 ? 'day' : 'night' });
    return started;
  };
  const a = run();
  assert.deepEqual(a, run());
  assert.ok(a.length > 10, 'an hour of city has things happening');
});

test('common events are common and very rare events are very rare over a simulated day', () => {
  const manager = new RandomEventManager(EVENTS, mulberry32(7));
  const counts = {};
  manager.on((kind, ev) => {
    if (kind === 'start') counts[ev.def.eventId] = (counts[ev.def.eventId] || 0) + 1;
  });
  for (let i = 0; i < 86400; i += 1) manager.update(1, { weather: 'clear', phase: i % 86400 < 50000 ? 'day' : 'night' });
  assert.ok((counts.pedestrians_cross || 0) > 50);
  assert.ok((counts.ufo_flyover || 0) <= 2);
});

/* ------------------------------------------------------------------ traffic */

const dense = { hour: 17.5, day: 3, effects: { rain: 0, snow: 0, wet: 0, fog: 0 } };

function lanesGaps(traffic) {
  const gaps = [];
  for (const lane of traffic.lanes) {
    const list = traffic.vehicles.filter((v) => v.lane === lane.id).sort((a, b) => a.x - b.x);
    for (let i = 1; i < list.length; i += 1) gaps.push(list[i].x - list[i - 1].x - (list[i].length + list[i - 1].length) / 2);
  }
  return gaps;
}

test('street sprites take the light of the hour: untouched by day, dim and cool at night', () => {
  assert.deepEqual(streetLight({ daylight: 1 }, { cloudiness: 0 }), [1, 1, 1]);
  const night = streetLight({ daylight: 0 }, { cloudiness: 0 });
  assert.ok(night[2] > night[0] && night.every((c) => c < 0.7), `night light ${night}`);
  const overcast = streetLight({ daylight: 1 }, { cloudiness: 1 });
  assert.ok(overcast.every((c) => c < 1), `overcast light ${overcast}`);
});

test('each vehicle frame knows where its visible lamps are, inside the frame', () => {
  for (const [kind, entry] of Object.entries(VEHICLES.vehicles)) {
    for (const [dir, d] of Object.entries(entry.directions)) {
      assert.ok(d.lamps && Array.isArray(d.lamps.head) && Array.isArray(d.lamps.tail), `${kind} ${dir} has no lamp anchors`);
      for (const [x, y] of [...d.lamps.head, ...d.lamps.tail]) {
        assert.ok(x >= 0 && x <= d.w && y >= 0 && y <= d.h, `${kind} ${dir} lamp at ${x},${y} is outside ${d.w}x${d.h}`);
      }
      if (kind !== 'bicycle') assert.ok(d.lamps.head.length > 0, `${kind} ${dir} shows no headlight`);
    }
  }
});

test('in rush hour no vehicle ever drives through another', () => {
  const traffic = new TrafficManager({ lanes: MANIFEST.street.lanes, catalogue: VEHICLES, worldWidth: 1600, rng: mulberry32(3), crosswalk: MANIFEST.street.crosswalk, shelterX: 1462 });
  for (let i = 0; i < 20 * 60 * 20; i += 1) {
    traffic.crosswalkBusy = i % 1200 < 200;
    traffic.update(1 / 20, dense);
    if (i % 10 === 0) for (const gap of lanesGaps(traffic)) assert.ok(gap > -0.5, `overlap ${gap} at step ${i}`);
  }
  assert.ok(traffic.serial > 40, 'rush hour brings plenty of traffic');
});

test('vehicles wait before the zebra while people are on it', () => {
  const lane = MANIFEST.street.lanes.find((l) => l.direction > 0);
  const traffic = new TrafficManager({ lanes: [lane], catalogue: VEHICLES, worldWidth: 1600, rng: mulberry32(5), crosswalk: MANIFEST.street.crosswalk });
  traffic.timers.set(lane.id, 1e9);
  const car = traffic.spawn('sedan', lane);
  car.x = MANIFEST.street.crosswalk.x - 320;
  traffic.crosswalkBusy = true;
  for (let i = 0; i < 400; i += 1) traffic.update(1 / 20, dense);
  const nose = car.x + car.length / 2;
  assert.ok(nose <= MANIFEST.street.crosswalk.x, `the car stopped short of the zebra (nose ${nose})`);
  traffic.crosswalkBusy = false;
  for (let i = 0; i < 400; i += 1) traffic.update(1 / 20, dense);
  assert.ok(car.x > MANIFEST.street.crosswalk.x + MANIFEST.street.crosswalk.w || !traffic.vehicles.includes(car), 'and drove on once it was clear');
});

test('a bus serving the shelter stops there, then leaves', () => {
  const lane = MANIFEST.street.lanes.find((l) => l.direction < 0);
  const traffic = new TrafficManager({ lanes: [lane], catalogue: VEHICLES, worldWidth: 1600, rng: mulberry32(9), shelterX: 1462 });
  traffic.timers.set(lane.id, 1e9);
  const bus = traffic.spawn('bus_amn', lane, { stopAtShelter: true });
  let stoppedNear = false;
  for (let i = 0; i < 20 * 40; i += 1) {
    traffic.update(1 / 20, dense);
    if (bus.speed < 1 && Math.abs(bus.x - 1462) < 12) stoppedNear = true;
  }
  assert.ok(stoppedNear, 'the bus stood at the shelter');
  assert.ok(bus.served);
  assert.ok(bus.x < 1300 || !traffic.vehicles.includes(bus), 'and drove away afterwards');
});

/* ------------------------------------------------------------------ pedestrians */

test('people walk on the pavement and block the road only while crossing', () => {
  const people = new PedestrianManager({ rows: MANIFEST.street.walk, crosswalk: MANIFEST.street.crosswalk, road: MANIFEST.street.road, nearWalkRow: MANIFEST.street.near_walk_row, shelterX: 1462, worldWidth: 1600, sheets: ['ped00', 'ped01'], rng: mulberry32(11) });
  for (let i = 0; i < 600; i += 1) people.update(0.1, dense);
  for (const p of people.people) {
    assert.ok(p.row >= MANIFEST.street.walk.far - 4 && p.row <= MANIFEST.street.walk.near + 4, `on the pavement (${p.row})`);
  }
  people.startCrossing();
  let busy = false;
  for (let i = 0; i < 400; i += 1) {
    people.update(0.1, dense);
    busy = busy || people.crosswalkBusy;
  }
  assert.ok(busy, 'crossing people occupy the zebra');
  assert.equal(people.crosswalkBusy, false, 'and free it once across');
});

/* ------------------------------------------------------------------ agents */

test('what an employee does on screen is the backend state, and only that', () => {
  assert.equal(animationFor({ runtime_state: 'WORKING' }, false), 'sit_type');
  assert.equal(animationFor({ runtime_state: 'THINKING' }, false), 'sit_think');
  assert.equal(animationFor({ runtime_state: 'IDLE' }, false), 'sit_idle');
  assert.equal(animationFor({ runtime_state: 'IDLE' }, true), 'sit_talk');
  assert.equal(animationFor({ runtime_state: 'WORKING', lifecycle: 'PAUSED' }, true), 'sit_sleep');
  assert.equal(animationFor({ runtime_state: 'ERROR' }, true), 'sit_error');
  assert.equal(screenModeFor({ runtime_state: 'WORKING', lifecycle: 'PAUSED' }), 'off');
});

test('each employee is drawn from their Character Bible sprite', () => {
  assert.equal(spriteFor({ display_name: 'Sarah (Director)', role_name: 'Director' }, CHARACTERS), 'sarah');
  assert.equal(spriteFor({ display_name: 'Dr. Aris (Researcher)', role_name: 'Researcher', desk_id: 'desk_research_1' }, CHARACTERS), 'aris');
  assert.equal(spriteFor({ display_name: 'Nadia (Accountant)', role_name: 'Accountant' }, CHARACTERS), 'nadia');
  for (const key of ['sarah', 'aris', 'elena', 'marcus', 'lyra', 'kael', 'vera', 'nadia']) {
    const entry = CHARACTERS.characters[key];
    assert.ok(entry, key);
    for (const anim of ['sit_type_front', 'sit_type_back', 'sit_sleep_front', 'walk_right']) assert.ok(entry.animations[anim]?.length, `${key} ${anim}`);
  }
});

test('an idle employee looks up at a big event; one at work keeps working', () => {
  const manager = new AgentVisualStateManager(mulberry32(2));
  const idle = { id: 'a', runtime_state: 'IDLE' };
  const busy = { id: 'b', runtime_state: 'WORKING' };
  manager.react([idle, busy], 5);
  const entry = CHARACTERS.characters.sarah;
  assert.equal(manager.frame(idle, entry, 'front', false).anim, 'sit_talk');
  assert.equal(manager.frame(busy, entry, 'front', false).anim, 'sit_type');
});
