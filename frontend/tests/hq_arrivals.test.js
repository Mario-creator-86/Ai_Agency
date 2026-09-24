// The live arrival seen from across the room (W12): what a live event brings up, for how long,
// and what it never does (a replay, old news, an unknown employee).
import test from 'node:test';
import assert from 'node:assert/strict';
import { ARRIVAL_FRESH_MS, ARRIVAL_TAG_MS, Arrivals, ROOM_FLARE_MS, STAGE_ROOMS, arrivalAccent, arrivalWords, envelope } from '../src/hq_arrivals.js';
import { scenePalette } from '../src/hq_palette.js';
import { RUN_STAGE_WORD } from '../src/hud_charts.js';
import fs from 'node:fs';

const WALL = Date.parse('2026-09-24T09:00:00Z');
const AGENTS = [
  { id: 'aris', display_name: 'Dr. Aris (Researcher)', desk_id: 'desk_research_1' },
  { id: 'elena', display_name: 'Elena (Fact Checker)', desk_id: 'desk_research_2' },
];
const at = (ms = 0) => new Date(WALL + ms).toISOString();
const working = (id, task = 'propose_topics', state = 'WORKING', ms = 0) => ({ event_type: 'agent.state_changed', aggregate_id: id, timestamp: at(ms), payload: { runtime_state: state, task_type: task } });
const stage = (name, ms = 0) => ({ event_type: 'runbook.stage_started', aggregate_id: 'run', timestamp: at(ms), payload: { stage: name, index: 3, total: 13 } });
const ctx = (now, extra = {}) => ({ live: true, now, wallNow: WALL, agents: AGENTS, ...extra });

test('a live start of work shows the employee\'s tag in the event\'s own words, for about four seconds', () => {
  const a = new Arrivals();
  assert.equal(a.offer(working('aris'), ctx(1000)), 'tag');
  const [tag] = a.tags(1000 + 1000);
  assert.equal(tag.id, 'aris');
  assert.equal(tag.words, 'Dr. Aris (Researcher) · lucrează · idei de subiect');
  assert.equal(tag.strength, 1);
  assert.ok(a.tags(1000 + 100)[0].strength < 1, 'it rises');
  assert.ok(a.tags(1000 + ARRIVAL_TAG_MS - 100)[0].strength < 1, 'it falls');
  assert.deepEqual(a.tags(1000 + ARRIVAL_TAG_MS), [], 'and is gone');
  assert.ok(ARRIVAL_TAG_MS >= 3500 && ARRIVAL_TAG_MS <= 4500);
});

test('a replay, old news, an unknown employee or a state that is not work starts nothing', () => {
  const a = new Arrivals();
  assert.equal(a.offer(working('aris'), ctx(0, { live: false })), null, 'a replayed event');
  assert.equal(a.offer(working('aris', 'x', 'WORKING', -ARRIVAL_FRESH_MS - 1000), ctx(0)), null, 'an outbox flushing old news');
  assert.equal(a.offer(working('nobody'), ctx(0)), null);
  assert.equal(a.offer(working('aris', 'x', 'IDLE'), ctx(0)), null);
  assert.equal(a.offer({ event_type: 'agent.state_changed', aggregate_id: 'aris', payload: { runtime_state: 'WORKING' } }, ctx(0)), null, 'no time, no arrival');
  assert.equal(a.offer(stage('media'), ctx(0, { live: false })), null);
  assert.deepEqual(a.tags(10), []);
  assert.deepEqual(a.rooms(10), []);
  assert.equal(a.signBeat, 0);
});

test('work that ends changes the words at once; the same work again keeps the tag, not a new arrival', () => {
  const a = new Arrivals();
  a.offer(working('elena', 'verify_claim', 'THINKING'), ctx(0));
  a.offer(working('elena', 'verify_claim', 'IDLE', 1000), ctx(1000));
  const [ended] = a.tags(1100);
  assert.equal(ended.words, 'Elena (Fact Checker) · a terminat · verificarea faptelor');
  assert.equal(a.offer(working('elena', 'verify_claim', 'THINKING', 1500), ctx(1500)), null, 'the next claim is not a new arrival');
  assert.equal(a.tags(1600)[0].words, 'Elena (Fact Checker) · lucrează · verificarea faptelor');
  assert.ok(a.tags(1500 + ARRIVAL_TAG_MS - 200).length, 'held while the work goes on');
  a.offer(working('elena', 'verify_claim', 'ERROR', 2000), ctx(2000));
  assert.equal(a.tags(2100)[0].words, 'Elena (Fact Checker) · stare: eroare · verificarea faptelor');
  a.offer(working('elena', 'verify_claim', 'PAUSED', 2500), ctx(2500));
  assert.deepEqual(a.tags(2500 + 500), [], 'a pause takes the tag away');
  assert.equal(a.count.tags, 1);
  assert.equal(a.offer(working('elena', 'write_script', 'WORKING', 9000), ctx(9000)), 'tag', 'other work is a new arrival');
});

test('a live stage start lights the rooms that do its work, and beats the sign once', () => {
  const a = new Arrivals();
  assert.equal(a.offer(stage('research_and_verification'), ctx(0)), 'room');
  assert.deepEqual(a.rooms(1000).map((r) => r.zone).sort(), ['factcheck_room', 'research_lab']);
  assert.equal(a.rooms(1000)[0].strength, 1);
  assert.equal(a.rooms(1000)[0].stage, 'research_and_verification');
  assert.deepEqual(a.rooms(ROOM_FLARE_MS), []);
  assert.equal(a.signBeat, 1);
  assert.equal(a.offer(stage('preflight'), ctx(0)), 'room');
  assert.deepEqual(a.rooms(10), [], 'the preflight has no room; the sign alone says it');
  assert.equal(a.signBeat, 2);
  a.clear();
  assert.equal(a.active(0), false);
});

test('every stage of the run has a room entry, and every room is one the headquarters draws', () => {
  const manifest = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/manifest.json', import.meta.url), 'utf8'));
  assert.deepEqual(Object.keys(STAGE_ROOMS).sort(), Object.keys(RUN_STAGE_WORD).sort());
  for (const zones of Object.values(STAGE_ROOMS)) for (const zone of zones) assert.ok(manifest.rooms[zone], zone);
});

test('the envelope rises, holds and falls, and is 0 outside its life', () => {
  assert.equal(envelope(-1, 1000), 0);
  assert.equal(envelope(1000, 1000), 0);
  assert.equal(envelope(500, 1000, 100, 100), 1);
  assert.ok(envelope(50, 1000, 100, 100) > 0 && envelope(50, 1000, 100, 100) < 1);
  assert.equal(arrivalWords({ display_name: 'Vera (Publisher)' }, null), 'Vera (Publisher) · lucrează · —');
});

test('«Reluarea zilei» (W13): a replayed event from the record says itself, however old; a socket replay still does not', () => {
  const a = new Arrivals();
  const old = working('aris', 'gather_sources', 'THINKING', -12 * 24 * 3600 * 1000);
  assert.equal(a.offer(old, ctx(0, { live: false })), null, 'the socket\'s replay_event: history, not an arrival');
  assert.equal(a.offer(old, ctx(0, { live: false, replay: true })), 'tag', 'the day replayed, played forward');
  assert.equal(a.tags(100)[0].words, 'Dr. Aris (Researcher) · lucrează · căutarea surselor');
  assert.equal(a.offer(stage('media', -12 * 24 * 3600 * 1000), ctx(0, { live: false, replay: true })), 'room');
  assert.equal(a.offer({ event_type: 'agent.state_changed', aggregate_id: 'aris', payload: { runtime_state: 'WORKING' } }, ctx(0, { replay: true })), null, 'no time, nothing');
});

test("a replayed arrival is drawn in the replay's violet, a live one in the register's green (W14)", () => {
  // a stranger read the replay's tags as live: the green bar and «lucrează» were the live ones
  assert.equal(arrivalAccent(true), 'replayInk');
  assert.equal(arrivalAccent(false), 'okInk');
  const c = scenePalette();
  assert.ok(c[arrivalAccent(true)] && c[arrivalAccent(false)], 'both inks are in the scene palette');
  assert.notEqual(c[arrivalAccent(true)], c[arrivalAccent(false)]);
  // the world draws its tags and room chips through the accent, never the live green directly
  const world = fs.readFileSync(new URL('../src/hq_world.js', import.meta.url), 'utf8');
  const tags = world.slice(world.indexOf('  drawArrivals(ctx, state) {'), world.indexOf('  drawFacade(ctx, scale) {'));
  const rims = world.slice(world.indexOf("  drawRoomRims(ctx, state, part = 'all') {"), world.indexOf('  drawArrivals(ctx, state) {'));
  for (const body of [tags, rims]) {
    assert.match(body, /arrivalAccent\(Boolean\(state\.replay\)\)/);
    assert.doesNotMatch(body, /c\.okInk/);
  }
});
