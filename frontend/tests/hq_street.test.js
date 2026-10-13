import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { RandomEventManager, REMOVED_EVENTS, EMERGENCY_EVENTS, eventAllowed, streetMoves, streetRule } from '../src/hq_events.js';
import { TrafficManager, trafficDensity, vehicleMix } from '../src/hq_traffic.js';
import { pedestrianTarget, umbrellaShare, weatherActivities } from '../src/hq_pedestrians.js';
import { dailyRhythm, isPublicHoliday, orthodoxEaster } from '../src/street_schedule.js';
import { normalizeWeather, weatherEffects } from '../src/hq_weather.js';
import { timeOfDay } from '../src/hq_time.js';
import { mulberry32, WorldSimulationManager } from '../src/hq_world.js';

/*
 * The street outside the headquarters is not simulated: how full it is and what may happen on
 * it follows the real hour and day in Bucharest, the real weather the backend reads, and
 * whether the page still has the studio's data (the Owner's rule, 2026-09-24).
 */

const EVENTS = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/world_events.json', import.meta.url), 'utf8'));
const MANIFEST = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/manifest.json', import.meta.url), 'utf8'));
const VEHICLES = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/vehicles/vehicles.json', import.meta.url), 'utf8'));

const DRY = weatherEffects(normalizeWeather({ available: true, condition: 'clear', intensity: 0.5 }));
const RAIN = weatherEffects(normalizeWeather({ available: true, condition: 'rain', intensity: 0.5 }));
const SNOW = weatherEffects(normalizeWeather({ available: true, condition: 'snow', intensity: 0.8 }));
const UNKNOWN = weatherEffects(normalizeWeather(null));

/** A moment in Bucharest, as the scene reads it. @param {string} iso */
const at = (iso) => {
  const t = timeOfDay(new Date(iso));
  return { hour: t.hour, day: t.day, ymd: t.ymd };
};

test('the working day has its rush hours, and the small hours are nearly empty', () => {
  const rush = streetRule({ ...at('2026-09-23T05:30:00Z'), effects: DRY }); // Wed 08:30
  const evening = streetRule({ ...at('2026-09-23T15:00:00Z'), effects: DRY }); // Wed 18:00
  const midday = streetRule({ ...at('2026-09-23T11:30:00Z'), effects: DRY }); // Wed 14:30
  const small = streetRule({ ...at('2026-09-23T00:00:00Z'), effects: DRY }); // Wed 03:00
  assert.equal(rush.day, 3);
  assert.ok(rush.traffic >= 0.9, `08:30 is a rush hour (${rush.traffic})`);
  assert.ok(evening.traffic >= 0.9, `18:00 is a rush hour (${evening.traffic})`);
  assert.ok(midday.traffic < rush.traffic - 0.2, 'midday is calmer than the rush');
  assert.ok(small.traffic <= 0.15 && small.people <= 3, 'at three in the morning the street is nearly empty');
  assert.equal(small.buses, false, 'and no day bus runs');
  assert.equal(rush.buses, true);
});

test('Sunday night is quieter than a Saturday night, and a weekend morning than a weekday one', () => {
  const sunday = streetRule({ ...at('2026-09-27T20:30:00Z'), effects: DRY }); // Sun 23:30
  const saturday = streetRule({ ...at('2026-09-26T20:30:00Z'), effects: DRY }); // Sat 23:30
  assert.equal(sunday.day, 0);
  assert.ok(sunday.traffic <= 0.15 && sunday.people <= 3, `Sunday 23:30 is nearly empty (${sunday.traffic}, ${sunday.people})`);
  assert.ok(saturday.traffic > sunday.traffic && saturday.people > sunday.people, 'Saturday night is out');
  const weekendMorning = streetRule({ ...at('2026-09-26T05:30:00Z'), effects: DRY }); // Sat 08:30
  const weekdayMorning = streetRule({ ...at('2026-09-25T05:30:00Z'), effects: DRY }); // Fri 08:30
  assert.ok(weekendMorning.traffic < weekdayMorning.traffic / 2);
});

test('a Romanian public holiday keeps Sunday on the street', () => {
  assert.deepEqual(orthodoxEaster(2026), [4, 12]);
  assert.deepEqual(orthodoxEaster(2025), [4, 20]);
  assert.deepEqual(orthodoxEaster(2027), [5, 2]);
  assert.ok(isPublicHoliday(2026, 4, 10), 'Good Friday');
  assert.ok(isPublicHoliday(2026, 4, 13), 'Easter Monday');
  assert.ok(isPublicHoliday(2026, 6, 1), 'Rusalii (Easter + 50) and Children\'s Day');
  assert.ok(isPublicHoliday(2026, 12, 1), 'the National Day');
  assert.ok(!isPublicHoliday(2026, 9, 24));
  const holiday = streetRule({ ...at('2026-12-01T06:00:00Z'), effects: DRY }); // Tue 08:00, 1 December
  assert.equal(holiday.holiday, true);
  assert.equal(holiday.day, 0);
  assert.ok(holiday.traffic < 0.4, `no rush hour on the National Day (${holiday.traffic})`);
});

test('rain thins the pavement and opens umbrellas; the road keeps its cars, fewer two-wheelers', () => {
  const dry = streetRule({ ...at('2026-09-23T11:30:00Z'), effects: DRY });
  const wet = streetRule({ ...at('2026-09-23T11:30:00Z'), effects: RAIN });
  assert.ok(wet.people < dry.people * 0.7, `fewer people in the rain (${wet.people} of ${dry.people})`);
  assert.equal(dry.umbrellas, 0, 'no umbrella when it is dry');
  assert.ok(wet.umbrellas > 0.8, 'most walkers under one in the rain');
  assert.ok(wet.traffic >= dry.traffic, 'rain does not empty a Bucharest road');
  const mixDry = vehicleMix(dailyRhythm(14.5, 3).vehicles, DRY);
  const mixWet = vehicleMix(dailyRhythm(14.5, 3).vehicles, RAIN);
  assert.equal(mixWet.bicycle, 0, 'no bicycles in real rain');
  assert.ok(mixDry.bicycle > 0 && mixWet.sedan === mixDry.sedan);
  const acts = weatherActivities({ walk: 10, run: 10, skate: 5, dog: 5 }, RAIN);
  assert.equal(acts.run, 0);
  assert.equal(acts.skate, 0);
  assert.equal(acts.walk, 10);
  const snowy = streetRule({ ...at('2026-09-23T11:30:00Z'), effects: SNOW });
  assert.ok(snowy.traffic < dry.traffic && snowy.people < dry.people, 'snow keeps people and drivers home');
});

test('when the weather is unavailable the street follows the hour alone, and draws no rain', () => {
  const r = streetRule({ ...at('2026-09-23T11:30:00Z'), effects: UNKNOWN });
  assert.equal(r.umbrellas, 0);
  assert.equal(r.traffic, trafficDensity(dailyRhythm(14.5, 3), UNKNOWN));
  assert.equal(r.people, pedestrianTarget(dailyRhythm(14.5, 3), UNKNOWN));
  assert.equal(umbrellaShare(UNKNOWN), 0);
});

test('the street stops when the page has lost its data, and under reduced motion', () => {
  assert.equal(streetMoves({ data: 'fresh', socket: 'open' }), true);
  for (const socket of ['connecting', 'reconnecting', 'refused', 'closed']) assert.equal(streetMoves({ data: 'fresh', socket }), false, socket);
  assert.equal(streetMoves({ data: 'stale', socket: 'open' }), false, 'a failed read of the studio');
  const base = { ...at('2026-09-23T05:30:00Z'), effects: DRY };
  assert.equal(streetRule({ ...base, live: true }).moving, true);
  assert.equal(streetRule({ ...base, live: false }).moving, false);
  assert.equal(streetRule({ ...base, live: true, still: true }).moving, false);
});

test('no UFO, no fireworks, no balloon: the fantastical is gone, even from the console', () => {
  for (const id of ['ufo_flyover', 'fireworks', 'hot_air_balloon']) assert.ok(REMOVED_EVENTS.has(id), id);
  const manager = new RandomEventManager(EVENTS, mulberry32(3));
  for (const id of REMOVED_EVENTS) {
    assert.equal(eventAllowed(id, { emergency: true }), false, id);
    assert.equal(manager.definitions.some((d) => d.eventId === id), false, `${id} is not rolled`);
    assert.equal(manager.trigger(id), null, `${id} cannot be started by hand`);
  }
  // The ordinary street stays.
  for (const id of ['airplane_cross', 'bird_flock', 'bus_arrives', 'pedestrians_cross', 'jogger_group']) {
    assert.ok(manager.definitions.some((d) => d.eventId === id), id);
  }
});

test('an emergency vehicle drives only when the backend says an emergency exists', () => {
  const manager = new RandomEventManager(EVENTS, mulberry32(4));
  for (const id of EMERGENCY_EVENTS) {
    const def = manager.definitions.find((d) => d.eventId === id);
    assert.ok(def, id);
    assert.equal(manager.eligible(def, { weather: 'clear', phase: 'day' }), false, `${id} with no emergency`);
    assert.equal(manager.trigger(id, { weather: 'clear', phase: 'day' }), null);
    assert.equal(manager.eligible(def, { weather: 'clear', phase: 'day', emergency: true }), true, `${id} when one is declared`);
  }
  assert.equal(streetRule({ ...at('2026-09-23T05:30:00Z'), effects: DRY }).sirens, false, 'no backend state declares one today');
  let sirens = 0;
  manager.on((kind, ev) => { if (kind === 'start' && EMERGENCY_EVENTS.has(ev.def.eventId)) sirens += 1; });
  for (let i = 0; i < 86400; i += 1) manager.update(1, { weather: 'clear', phase: 'day' });
  assert.equal(sirens, 0);
});

test('buses stop at the shelter only in the hours they run', () => {
  const manager = new RandomEventManager(EVENTS, mulberry32(5));
  const bus = manager.definitions.find((d) => d.eventId === 'bus_arrives');
  assert.equal(manager.eligible(bus, { weather: 'clear', phase: 'night', buses: false }), false);
  assert.equal(manager.eligible(bus, { weather: 'clear', phase: 'day', buses: true }), true);
});

test('rush hour brings several times the cars of a Sunday night, from the same seed', () => {
  const count = (/** @type {{hour:number, day:number}} */ when) => {
    const traffic = new TrafficManager({ lanes: MANIFEST.street.lanes, catalogue: VEHICLES, worldWidth: 1600, rng: mulberry32(21), crosswalk: MANIFEST.street.crosswalk, shelterX: 1462 });
    for (let i = 0; i < 20 * 60 * 10; i += 1) traffic.update(1 / 20, { ...when, effects: DRY });
    return traffic.serial;
  };
  const rush = count({ hour: 8.5, day: 3 });
  const sundayNight = count({ hour: 23.5, day: 0 });
  assert.ok(rush >= sundayNight * 3, `ten minutes: ${rush} cars at 08:30 on a Wednesday, ${sundayNight} at 23:30 on a Sunday`);
});

/** The world with its real art data and a weather the test answers when it chooses. */
function world(now, fetchWeather) {
  const read = (/** @type {string} */ p) => JSON.parse(fs.readFileSync(new URL(`../public/assets/hq/${p}`, import.meta.url), 'utf8'));
  const assets = { manifest: MANIFEST, events: EVENTS, vehicles: VEHICLES, pedestrians: read('characters/pedestrians.json'), loadVariant() {} };
  return new WorldSimulationManager({ assets, seed: 5, now: () => new Date(now), fetchWeather });
}

test('the street is dressed for the first weather reading before anyone sees it', async () => {
  /** @type {(v: any) => void} */
  let answer = () => {};
  const w = world('2026-09-23T11:30:00Z', () => new Promise((r) => { answer = r; }));
  assert.equal(w.warm, false, 'no street before the weather is known');
  answer({ available: true, condition: 'rain', intensity: 0.6 });
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(w.warm, true);
  const people = w.pedestrians.people;
  assert.ok(people.length > 0);
  assert.ok(people.filter((p) => p.umbrella).length >= people.length * 0.6, 'the walkers arrive under umbrellas');
  assert.ok(people.every((p) => p.activity !== 'run'), 'nobody jogs in the rain');
});

test('a world whose page has lost its data holds its street where it is', async () => {
  const w = world('2026-09-23T05:30:00Z', async () => ({ available: true, condition: 'clear', intensity: 0.2 }));
  await new Promise((r) => setTimeout(r, 0));
  const where = () => JSON.stringify([w.traffic.vehicles.map((v) => [v.id, v.x]), w.pedestrians.people.map((p) => [p.id, p.x, p.row])]);
  const before = where();
  for (let i = 0; i < 60; i += 1) w.step(1 / 20, 0, false, false);
  assert.equal(where(), before, 'nothing moved while the data was lost');
  assert.equal(w.rule.moving, false);
  for (let i = 0; i < 60; i += 1) w.step(1 / 20, 0, false, true);
  assert.notEqual(where(), before, 'and it moves again once the data is back');
});
