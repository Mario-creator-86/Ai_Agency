import test from 'node:test';
import assert from 'node:assert/strict';
import { ambientMoves, streetFrame } from '../src/pixel_life.js';
import { characterMotion, characterProfile, drawDeskGesture } from '../src/pixel_people.js';
import { normalizeWeather } from '../src/hq_weather.js';

const clear = normalizeWeather({ available: true, condition: 'clear' });
const live = { live: true, reduced: false, replay: false, parked: false, hidden: false };

test('city motion respects visibility, sign-out, replay and reduced-motion guards', () => {
  assert.equal(ambientMoves(live), true);
  for (const key of ['reduced', 'replay', 'parked', 'hidden']) assert.equal(ambientMoves({ ...live, [key]: true }), false);
  assert.equal(ambientMoves({ ...live, live: false }), false);
});

test('original street sprites move within bounded cycles without making staff/work events', () => {
  const first = streetFrame(0, clear, true), next = streetFrame(5000, clear, true);
  assert.equal(first.people.length, 4);
  assert.notEqual(first.people[0].x, next.people[0].x);
  assert.notEqual(first.bicycle.x, next.bicycle.x); assert.notEqual(first.car.x, next.car.x);
  assert.ok(first.people.every(p => p.kind === 'pedestrian' && !('agent_id' in p)));
  for (let t = 0; t < 300000; t += 5000) {
    const scene = streetFrame(t, clear, true);
    assert.ok(scene.people.every(p => p.x >= -50 && p.x <= 1010));
    assert.ok(scene.car.x >= -50 && scene.car.x <= 1010);
  }
  assert.deepEqual(streetFrame(NaN, clear, true), first);
});

test('umbrella, headlights and moths use actual weather/daylight without inventing rain', () => {
  const rainy = streetFrame(2000, normalizeWeather({ available: true, condition: 'rain' }), true);
  assert.ok(rainy.people.every(p => p.umbrella)); assert.equal(rainy.moths, false);
  assert.equal(streetFrame(2000, clear, true).moths, true);
  assert.equal(streetFrame(2000, clear, false).car.lights, false);
  const unknown = streetFrame(2000, normalizeWeather(null), true);
  assert.ok(unknown.people.every(p => !p.umbrella)); assert.equal(unknown.moths, false);
});

test('idle employees have visible breathing, glances, cup and stretch without fake work', () => {
  const agent = { id: 'idle-fixture', role_name: 'FactChecker', lifecycle: 'ACTIVE', runtime_state: 'IDLE' };
  const before = structuredClone(agent), gestures = new Set(), breaths = new Set();
  for (let t = 0; t <= 42000; t += 180) {
    const motion = characterMotion(agent, t, true); gestures.add(motion.gesture); breaths.add(motion.breath);
    assert.equal(motion.mode, 'IDLE');
  }
  assert.deepEqual([...gestures].sort(), ['look', 'rest', 'sip', 'stretch']);
  assert.equal(breaths.size, 3); assert.deepEqual(agent, before);
  assert.notDeepEqual(characterMotion(agent, 1000, true), characterMotion({ ...agent, id: 'another' }, 1000, true));
});

test('work gestures vary by real role and reviewing/thinking remain distinct', () => {
  const agent = { id: 'work-fixture', lifecycle: 'ACTIVE', runtime_state: 'WORKING' };
  const actions = role_name => new Set(Array.from({ length: 64 }, (_, i) => characterMotion({ ...agent, role_name }, i * 250, true).gesture));
  assert.ok(actions('Writer').has('type')); assert.ok(actions('Accountant').has('write'));
  assert.ok(actions('LeadResearcher').has('read')); assert.ok(actions('VoiceArtist').has('headset'));
  const thought = characterMotion({ ...agent, runtime_state: 'THINKING' }, 0, true);
  assert.ok(['chin', 'look'].includes(thought.gesture));
  for (const runtime_state of ['IDLE', 'WORKING', 'THINKING', 'REVIEWING']) {
    const a = { ...agent, runtime_state };
    assert.deepEqual(characterMotion(a, 0, false), characterMotion(a, 50000, false));
    assert.deepEqual(characterMotion(a, 0, true, true), characterMotion(a, 50000, true, true));
  }
});

test('visible foreground gestures use different actual tools without covering paused staff', () => {
  const profile = characterProfile({ id: 'hands' });
  const paint = gesture => {
    const rows = [];
    const ctx = { save() {}, restore() {}, translate() {}, scale() {}, fillRect(...args) { rows.push([...args, this.fillStyle]); } };
    drawDeskGesture(ctx, profile, { gesture, animate: true, gestureFrame: 1, breath: 1 }, 0, 0);
    return rows;
  };
  assert.notDeepEqual(paint('type'), paint('read')); assert.notDeepEqual(paint('mouse'), paint('write'));
  assert.deepEqual(paint('rest'), []);
});
