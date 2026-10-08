import test from 'node:test';
import assert from 'node:assert/strict';
import { staffPositions, acting, identitySeed, WORLD_W, WORLD_H } from '../src/pixel_office.js';
import { autonomyOverview } from '../src/autonomy_overview.js';
import { escapeHtml } from '../src/html.js';
import { characterProfile, characterMotion, drawSeatedPerson } from '../src/pixel_people.js';
import { OfficeState } from '../src/office_state.js';
import { PIXEL_LAYOUT } from '../src/pixel_desks.js';

const staff = Array.from({ length: 30 }, (_, i) => ({ id: `agent-${String(i).padStart(2, '0')}`, lifecycle: 'ACTIVE', runtime_state: 'IDLE' }));

test('eight reserved employees sit at the illustrated furniture across three floors, leaving the lounge open', () => {
  assert.equal(PIXEL_LAYOUT.floor_count, 3);
  assert.equal(PIXEL_LAYOUT.scene_mode, 'illustrated_furniture');
  assert.equal(new Set(PIXEL_LAYOUT.stations.map(s => s.row)).size, 3);
  const positions = staffPositions(staff.slice(0, 8).map((agent, pixel_slot) => ({ ...agent, pixel_slot })));
  assert.ok(positions.every(p => p.orientation === 'back' && p.foreground.length > 0));
  assert.deepEqual(positions.map(p => p.slot), [0, 1, 2, 3, 4, 5, 6, 7]);
  assert.equal(positions.filter(p => p.row === 2 && p.x > 600).length, 0, 'the furnished lounge remains unobstructed');
});

test('rear seated characters retain the Bible palette and distinguish work from thinking', () => {
  const agent = { id: 'lyra', lifecycle: 'ACTIVE' };
  const profile = characterProfile(agent, { face_hair_desc: 'Sleek hair with pink streak', props_desc: 'Headphones', palette_json: { hair: '#0f172a', sweater: '#ec4899', headphones: '#f43f5e' } });
  const paint = runtime_state => {
    const rectangles = [];
    const ctx = { save() {}, restore() {}, translate() {}, scale() {}, fillRect(...args) { rectangles.push([...args, this.fillStyle]); } };
    drawSeatedPerson(ctx, profile, characterMotion({ ...agent, runtime_state }), 0, 0, 1.5, false, 'back');
    return rectangles;
  };
  assert.notDeepEqual(paint('WORKING'), paint('THINKING'));
  for (const color of ['#0f172a', '#ec4899', '#f43f5e']) assert.ok(paint('IDLE').some(r => r.at(-1) === color));
});

test('every actual employee has a distinct place inside the studio, including a large workforce', () => {
  const positions = staffPositions(staff);
  assert.equal(positions.length, staff.length);
  assert.equal(new Set(positions.map(p => `${p.page}:${p.x}:${p.y}`)).size, staff.length);
  assert.equal(new Set(positions.map(p => p.deskId)).size, staff.length);
  assert.ok(positions.every(p => positions.filter(q => q.page === p.page).length <= 8));
  assert.ok(positions.every(p => p.x > 140 && p.x < WORLD_W - 140 && p.y > 0 && p.y < WORLD_H));
  assert.deepEqual(staffPositions([]), []);
});

test('reserved backend seats survive row order, hiring, pausing and a departing colleague', () => {
  const agents = staff.map((a, pixel_slot) => ({ ...a, pixel_slot, pixel_desk_id: `desk-${a.id}` }));
  const seat = p => [p.id, p.deskId, p.slot, p.page, p.x, p.y];
  const expected = new Map(staffPositions(agents).map(p => [p.id, seat(p)]));
  const changed = [{ ...agents[0], lifecycle: 'PAUSED', runtime_state: 'THINKING' }, ...agents.slice(2).reverse(), { id: 'new-hire', pixel_slot: 30 }];
  for (const p of staffPositions(changed).filter(p => p.id !== 'new-hire')) assert.deepEqual(seat(p), expected.get(p.id));
});

test('real backend events change the seated pose without changing personal ownership', () => {
  const state = new OfficeState();
  state.initFromLayout({ assignments: [{ agent_id: 'aris', pixel_slot: 0, lifecycle: 'ACTIVE', runtime_state: 'IDLE' }] });
  const before = staffPositions(state.agents)[0];
  for (const runtime_state of ['WORKING', 'THINKING', 'REVIEWING', 'BLOCKED', 'ERROR', 'IDLE']) {
    state.handleDomainEvent({ event_type: 'agent.state_changed', aggregate_id: 'aris', payload: { runtime_state } });
    assert.equal(characterMotion(state.agents[0], 1500, true).mode, runtime_state);
    const after = staffPositions(state.agents)[0];
    assert.deepEqual([after.deskId, after.slot, after.x, after.y], [before.deskId, before.slot, before.x, before.y]);
  }
  state.handleDomainEvent({ event_type: 'agent.paused', aggregate_id: 'aris' });
  assert.equal(characterMotion(state.agents[0], 1500, true).mode, 'PAUSED');
  state.handleDomainEvent({ event_type: 'agent.resumed', aggregate_id: 'aris' });
  assert.equal(characterMotion(state.agents[0], 1500, true).mode, 'IDLE');
});

test('living gestures are cosmetic, state-specific and stop for stale data, replay or reduced motion', () => {
  for (const runtime_state of ['IDLE', 'WORKING', 'THINKING', 'REVIEWING']) {
    const agent = { id: 'aris', lifecycle: 'ACTIVE', runtime_state };
    const before = structuredClone(agent);
    assert.equal(characterMotion(agent, 1000, true).animate, true);
    for (const [live, reduced, replay] of [[false, false, false], [true, true, false], [true, false, true]]) {
      const first = characterMotion(agent, 1000, live, reduced, replay);
      assert.equal(first.animate, false);
      assert.deepEqual(first, characterMotion(agent, 7000, live, reduced, replay));
    }
    assert.deepEqual(agent, before);
  }
  for (const runtime_state of ['BLOCKED', 'ERROR', 'UNKNOWN']) assert.equal(characterMotion({ lifecycle: 'ACTIVE', runtime_state }, 1000, true).animate, false);
  for (const lifecycle of ['PAUSED', 'SUSPENDED', 'HIRED', 'OFFBOARDED']) assert.equal(characterMotion({ lifecycle, runtime_state: 'WORKING' }, 1000, true).animate, false);
  assert.equal(characterMotion({}).mode, 'UNKNOWN');
});

test('seated working, thinking and paused characters have different visible arm poses', () => {
  const agent = { id: 'aris', lifecycle: 'ACTIVE' };
  const profile = characterProfile(agent);
  const paint = runtime_state => {
    const rectangles = [];
    const ctx = { save() {}, restore() {}, translate() {}, scale() {}, fillRect(...args) { rectangles.push([...args, this.fillStyle]); } };
    drawSeatedPerson(ctx, profile, characterMotion({ ...agent, runtime_state, lifecycle: runtime_state === 'PAUSED' ? 'PAUSED' : 'ACTIVE' }), 0, 0);
    return rectangles;
  };
  assert.notDeepEqual(paint('WORKING'), paint('THINKING'));
  assert.notDeepEqual(paint('WORKING'), paint('PAUSED'));
});

test('slow reads and replayed old events cannot rewind a newer backend agent state', () => {
  const state = new OfficeState();
  const assignment = { agent_id: 'aris', pixel_slot: 0, version: 1, lifecycle: 'ACTIVE', runtime_state: 'IDLE' };
  state.initFromLayout({ assignments: [assignment] });
  state.handleDomainEvent({ event_type: 'agent.state_changed', aggregate_id: 'aris', aggregate_version: 3, payload: { runtime_state: 'THINKING' } });
  state.initFromLayout({ assignments: [{ ...assignment, version: 2, runtime_state: 'WORKING' }] });
  state.handleDomainEvent({ event_type: 'agent.state_changed', aggregate_id: 'aris', aggregate_version: 2, payload: { runtime_state: 'WORKING' } }, false);
  state.setAgents([{ id: 'aris', version: 2, runtime_state: 'IDLE' }]);
  state.handleDomainEvent({ event_type: 'agent.run_completed', payload: { agent_id: 'aris', status: 'SUCCEEDED' } }, false);
  assert.equal(state.agents[0].runtime_state, 'THINKING');
  assert.equal(state.agents[0].version, 3);
  state.initFromLayout({ assignments: [{ ...assignment, version: 4, runtime_state: 'BLOCKED' }] });
  assert.equal(state.agents[0].runtime_state, 'BLOCKED');
  state.initFromLayout({ assignments: [{ agent_id: 'missing-state' }] });
  assert.equal(state.agents[0].runtime_state, 'UNKNOWN');
  assert.equal(state.agents[0].lifecycle, 'UNKNOWN');
});

test('Character Bible details retain identity across state changes and reject invalid palette values', () => {
  const agent = { id: 'aris', role_name: 'LeadResearcher', runtime_state: 'IDLE' };
  const bible = { palette_json: { coat: '#f8fafc', hair: '#334155', glasses: '#e2e8f0' }, face_hair_desc: 'Silver temples, circular glasses', props_desc: 'Notebook' };
  const profile = characterProfile(agent, bible);
  assert.equal(profile.coat, '#f8fafc'); assert.equal(profile.glasses, true); assert.equal(profile.silver, true);
  assert.deepEqual(characterProfile({ ...agent, runtime_state: 'THINKING' }, bible), profile);
  assert.match(characterProfile(agent, { palette_json: { coat: 'url(evil)' } }).coat, /^#[0-9a-f]{6}$/i);
  const accountant = characterProfile({ id: 'nadia', role_name: 'Accountant' }, { face_hair_desc: 'Low bun and glasses', props_desc: 'Ledger', palette_json: { vest: '#b45309' } });
  assert.equal(accountant.ledger, true); assert.equal(accountant.hairStyle, 'bun');
});

test('backend row order cannot change appearance or placement', () => {
  assert.deepEqual(staffPositions([...staff].reverse()), staffPositions(staff));
  assert.equal(identitySeed('same-agent'), identitySeed('same-agent'));
  assert.notEqual(identitySeed('same-agent'), identitySeed('another-agent'));
});

test('work animation requires real work, active lifecycle, live data and motion permission', () => {
  const agent = { lifecycle: 'ACTIVE', runtime_state: 'WORKING' };
  assert.equal(acting(agent, true, false), true);
  assert.equal(acting(agent, false, false), false);
  assert.equal(acting(agent, true, true), false);
  for (const lifecycle of ['PAUSED', 'OFFBOARDED']) assert.equal(acting({ ...agent, lifecycle }, true, false), false);
  for (const runtime_state of ['IDLE', 'BLOCKED', 'ERROR']) assert.equal(acting({ ...agent, runtime_state }, true, false), false);
});

test('autonomy overview does not infer a mode, environment or schedule from missing data', () => {
  const html = autonomyOverview(null, null, escapeHtml);
  assert.match(html, /Necunoscut/);
  assert.doesNotMatch(html, /CEO autonom|Producție|Permis în limitele setate/);
});

test('autonomy overview reports the current policy and escapes external values', () => {
  const html = autonomyOverview({ policy: { autonomy_mode: 'AUTONOMOUS_CEO', environment: 'TEST', autonomy_stopped: true }, studio: { timezone: '<img src=x>' } }, [], escapeHtml);
  assert.match(html, /CEO autonom/);
  assert.match(html, />Test</);
  assert.match(html, />Oprit</);
  assert.ok(!html.includes('<img'));
  assert.ok(html.includes('&lt;img'));
});
