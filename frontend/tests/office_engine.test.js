import test from 'node:test';
import assert from 'node:assert/strict';
import { Viewport, OfficeEngine } from '../src/office_engine.js';
import { OfficeState } from '../src/office_state.js';

/** The floors the backend serves, trimmed to what the state and lift logic read. */
const LIFT_ZONES_WITH_DESKS = [
  { id: 'director_suite', floor: 4, x: 130, y: 60, width: 840, height: 130, desks: [{ x: 520 }] },
  {
    id: 'research_lab', floor: 3, x: 130, y: 195, width: 840, height: 130,
    desks: [{ x: 350 }, { x: 680 }],
  },
  { id: 'script_room', floor: 2, x: 130, y: 330, width: 840, height: 130, desks: [{ x: 520 }] },
  { id: 'audio_booth', floor: 1, x: 130, y: 465, width: 415, height: 130, desks: [{ x: 330 }] },
  { id: 'video_studio', floor: 1, x: 555, y: 465, width: 415, height: 130, desks: [{ x: 750 }] },
  { id: 'publish_desk', floor: 0, x: 590, y: 600, width: 200, height: 200, desks: [{ x: 690 }] },
];

test('viewport screenToWorld and worldToScreen invert correctly', () => {
  const vp = new Viewport({ width: 1000, height: 600 });
  vp.panX = 150;
  vp.panY = 80;
  vp.zoom = 1.5;
  const screen = vp.worldToScreen(300, 200);
  assert.equal(screen.x, 300 * 1.5 + 150);
  assert.equal(screen.y, 200 * 1.5 + 80);
  const back = vp.screenToWorld(screen.x, screen.y);
  assert.ok(Math.abs(back.x - 300) < 1e-5);
  assert.ok(Math.abs(back.y - 200) < 1e-5);
});

test('viewport zoom clamps between minZoom and maxZoom', () => {
  const vp = new Viewport({ width: 800, height: 600 });
  vp.setZoom(10.0);
  assert.equal(vp.zoom, vp.maxZoom);
  vp.setZoom(0.01);
  assert.equal(vp.zoom, vp.minZoom);
});

test('office state initializes agents and handles state change event', () => {
  const state = new OfficeState();
  state.initFromLayout({
    width: 1200,
    height: 1000,
    zones: LIFT_ZONES_WITH_DESKS,
    assignments: [
      { agent_id: 'agent_1', display_name: 'Sarah Director', role_name: 'Director', runtime_state: 'IDLE', lifecycle: 'ACTIVE', x: 130, y: 140 },
    ],
  });
  assert.equal(state.agents.length, 1);
  assert.equal(state.agents[0].runtime_state, 'IDLE');

  state.handleDomainEvent({ event_type: 'agent.state_changed', aggregate_id: 'agent_1', payload: { runtime_state: 'WORKING', task_type: 'research', detail: 'Reading the source' } });
  assert.equal(state.agents[0].runtime_state, 'WORKING');
  assert.equal(state.agents[0].detail, 'Reading the source', 'what the agent does travels to the scene');
  state.handleDomainEvent({ event_type: 'agent.state_changed', aggregate_id: 'agent_1', payload: { runtime_state: 'IDLE' } });
  assert.equal(state.agents[0].detail, '', 'and is cleared when the work ends');

  state.handleDomainEvent({ event_type: 'agent.message_sent', aggregate_id: 'agent_1', payload: { text: 'Reviewing pipeline performance.' } });
  assert.equal(state.speechBubbles.length, 1);
  assert.equal(state.speechBubbles[0].text, 'Reviewing pipeline performance.');

  state.handleDomainEvent({ event_type: 'agent.paused', aggregate_id: 'agent_1', payload: { lifecycle: 'PAUSED' } });
  assert.equal(state.agents[0].lifecycle, 'PAUSED');

  state.handleDomainEvent({ event_type: 'workflow.running', aggregate_id: 'wf_42', payload: { current_stage: 'SCRIPTING' } });
  assert.equal(state.projectTokens.length, 1);
  assert.equal(state.projectTokens[0].stage, 'SCRIPTING');
  assert.equal(state.projectTokens[0].x, 520, 'beside the script desk');
  assert.equal(state.projectTokens[0].y, 420, 'on the second floor');
});

test('every workflow stage lands inside a department the backend actually serves', () => {
  const state = new OfficeState();
  state.initFromLayout({ width: 1200, height: 1000, zones: LIFT_ZONES_WITH_DESKS });
  const stages = ['DISCOVERY', 'RESEARCH', 'FACT_CHECK', 'SCRIPTING', 'STORYBOARD', 'VOICE_GENERATION', 'VIDEO_GENERATION', 'EDITING', 'QUALITY_CONTROL', 'READY_TO_PUBLISH', 'PUBLISHING', 'PUBLISHED', 'ANALYTICS'];
  for (const stage of stages) {
    state.updateProjectToken('wf_stage', stage);
    const token = state.projectTokens[0];
    const zone = LIFT_ZONES_WITH_DESKS.find((z) => token.y >= z.y && token.y <= z.y + z.height && token.x >= z.x && token.x <= z.x + z.width);
    assert.ok(zone, `${stage} placed the token at ${token.x},${token.y} — inside no department`);
  }
});

test('no token is placed before the backend layout has arrived', () => {
  const state = new OfficeState();
  state.updateProjectToken('wf_early', 'SCRIPTING');
  assert.equal(state.projectTokens.length, 0, 'a guessed position is worse than none');
});

/* --------------------------------------------------------------------------
 * Lift choreography
 *
 * The cab exists to carry work between departments. It must stand still when the backend
 * reports no movement, and the courier riding it must correspond to a token that really changed
 * floor. The trip state machine is exercised directly, without a canvas.
 * ------------------------------------------------------------------------ */

function liftHarness() {
  const engine = Object.create(OfficeEngine.prototype);
  engine.layout = { zones: LIFT_ZONES_WITH_DESKS };
  engine.building = { x: 120, y: 60, width: 960, height: 740 };
  engine.shaft = { ex: 980, ew: 90 };
  engine.liftStops = null;
  engine.animTime = 0;
  engine.projectTokens = [];
  engine.tokenPlaces = new Map();
  engine.lift = { y: 734, target: 734, moving: false, restUntil: 0, homeY: 734, trip: null };
  engine.step = (seconds, frame = 1 / 60) => {
    for (let t = 0; t < seconds; t += frame) {
      engine.animTime += frame;
      engine._updateLift(frame);
    }
  };
  return engine;
}

function tokenAt(zone, x = 400) {
  return { id: 'wf_1', stage: 'SCRIPTING', x, y: zone.y + zone.height - 40 };
}

test('the lift stands still while no token changes floor', () => {
  const engine = liftHarness();
  engine.projectTokens = [tokenAt(LIFT_ZONES_WITH_DESKS[4])];
  engine.step(20);
  assert.equal(engine.lift.moving, false, 'a cab with no job must not move');
  assert.equal(engine.lift.trip, null, 'no token moved, so nobody is riding');
  assert.equal(engine.lift.y, 734, 'the cab stays exactly where it was parked');
});

test('a token changing floor sends a courier through the cab and out again', () => {
  const engine = liftHarness();
  const ground = LIFT_ZONES_WITH_DESKS[4];
  const script = LIFT_ZONES_WITH_DESKS[2];
  engine.projectTokens = [tokenAt(ground, 690)];
  engine.step(0.5);
  assert.equal(engine.lift.trip, null, 'seeing a token for the first time is not a trip');

  engine.projectTokens = [tokenAt(script, 520)];
  engine._updateLift(1 / 60);
  const trip = engine.lift.trip;
  assert.ok(trip, 'a floor change must dispatch the lift');
  assert.equal(trip.tokenId, 'wf_1');
  assert.equal(trip.phase, 'summon');
  assert.equal(trip.startX, 690, 'the courier starts where the work was');
  assert.equal(trip.exitX, 520, 'and ends where the work now is');

  const seen = new Set([trip.phase]);
  for (let i = 0; i < 60 * 40 && engine.lift.trip; i += 1) {
    engine.animTime += 1 / 60;
    engine._updateLift(1 / 60);
    if (engine.lift.trip) seen.add(engine.lift.trip.phase);
  }
  assert.deepEqual([...seen].sort(), ['alight', 'board', 'summon', 'travel'], 'the delivery must pass through every stage');
  assert.equal(engine.lift.trip, null, 'and finish');
  assert.ok(Math.abs(engine.lift.y - (script.y + script.height - 66)) <= 1, 'the cab ends at the destination floor');
});

test('with the rendered building the cab stops at the manifest floor rows', () => {
  const engine = liftHarness();
  engine.liftStops = { 0: 650, 1: 495, 2: 387, 3: 277, 4: 172 };
  engine.lift = { y: 650, target: 650, moving: false, restUntil: 0, homeY: 650, trip: null };
  engine.projectTokens = [tokenAt(LIFT_ZONES_WITH_DESKS[4], 690)];
  engine.step(0.5);
  engine.projectTokens = [tokenAt(LIFT_ZONES_WITH_DESKS[0], 520)];
  for (let i = 0; i < 60 * 60 && (engine.lift.trip || i === 0); i += 1) {
    engine.animTime += 1 / 60;
    engine._updateLift(1 / 60);
  }
  assert.ok(Math.abs(engine.lift.y - 172) <= 1, `the cab reached the fourth floor row (${engine.lift.y})`);
});

test('the cab keeps its doors shut while it is travelling', () => {
  const engine = liftHarness();
  engine.projectTokens = [tokenAt(LIFT_ZONES_WITH_DESKS[4], 690)];
  engine.step(0.5);
  engine.projectTokens = [tokenAt(LIFT_ZONES_WITH_DESKS[2], 520)];
  for (let i = 0; i < 60 * 40 && engine.lift.trip; i += 1) {
    engine.animTime += 1 / 60;
    engine._updateLift(1 / 60);
    const trip = engine.lift.trip;
    if (trip && trip.phase === 'travel') assert.ok(engine.lift.moving || Math.abs(engine.lift.y - trip.toY) <= 1);
    if (trip && (trip.phase === 'board' || trip.phase === 'alight')) assert.equal(engine.lift.moving, false, 'the cab must be stopped while someone steps through');
  }
});

test('a second floor change is not started while a delivery is in progress', () => {
  const engine = liftHarness();
  engine.projectTokens = [tokenAt(LIFT_ZONES_WITH_DESKS[4], 690)];
  engine.step(0.5);
  engine.projectTokens = [tokenAt(LIFT_ZONES_WITH_DESKS[2], 520)];
  engine._updateLift(1 / 60);
  const first = engine.lift.trip;
  engine.projectTokens = [tokenAt(LIFT_ZONES_WITH_DESKS[0], 300)];
  engine._updateLift(1 / 60);
  assert.equal(engine.lift.trip, first, 'the cab finishes one delivery before taking another');
});

test('portrait fit keeps the entire world above the camera controls', () => {
  const vp = new Viewport({ width: 318, height: 468 });
  vp.bottomInset = 132;
  vp.fitToOffice(1600, 840);
  const top = vp.worldToScreen(0, 0);
  const bottom = vp.worldToScreen(1600, 840);
  assert.ok(top.x >= 0 && top.y >= 0);
  assert.ok(bottom.x <= 318 && bottom.y <= 468 - 132);
});
