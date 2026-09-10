import test from 'node:test';
import assert from 'node:assert/strict';
import {
  Viewport,
  OfficeEngine,
  streetGeometry,
  PEDESTRIAN_HEIGHT,
  makeTraffic,
  updateTraffic,
} from '../src/office_engine.js';
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
  const dummyCanvas = { width: 1000, height: 600 };
  const vp = new Viewport(dummyCanvas);
  vp.panX = 150;
  vp.panY = 80;
  vp.zoom = 1.5;

  const worldX = 300;
  const worldY = 200;
  const screen = vp.worldToScreen(worldX, worldY);
  assert.equal(screen.x, 300 * 1.5 + 150);
  assert.equal(screen.y, 200 * 1.5 + 80);

  const backToWorld = vp.screenToWorld(screen.x, screen.y);
  assert.ok(Math.abs(backToWorld.x - worldX) < 1e-5);
  assert.ok(Math.abs(backToWorld.y - worldY) < 1e-5);
});

test('viewport zoom clamps between minZoom and maxZoom', () => {
  const dummyCanvas = { width: 800, height: 600 };
  const vp = new Viewport(dummyCanvas);

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
      {
        agent_id: 'agent_1',
        display_name: 'Sarah Director',
        role_name: 'Director',
        runtime_state: 'IDLE',
        lifecycle: 'ACTIVE',
        x: 130,
        y: 140,
      },
    ],
  });

  assert.equal(state.agents.length, 1);
  assert.equal(state.agents[0].runtime_state, 'IDLE');

  // Handle agent.state_changed
  state.handleDomainEvent({
    event_type: 'agent.state_changed',
    aggregate_id: 'agent_1',
    payload: { runtime_state: 'THINKING' },
  });
  assert.equal(state.agents[0].runtime_state, 'THINKING');

  // Handle agent.message_sent -> creates speech bubble
  state.handleDomainEvent({
    event_type: 'agent.message_sent',
    aggregate_id: 'agent_1',
    payload: { text: 'Reviewing pipeline performance.' },
  });
  assert.equal(state.speechBubbles.length, 1);
  assert.equal(state.speechBubbles[0].text, 'Reviewing pipeline performance.');
  assert.equal(state.speechBubbles[0].x, 130);

  // Handle agent.paused
  state.handleDomainEvent({
    event_type: 'agent.paused',
    aggregate_id: 'agent_1',
    payload: { lifecycle: 'PAUSED' },
  });
  assert.equal(state.agents[0].lifecycle, 'PAUSED');

  // Handle workflow stage advance -> moves project token
  state.handleDomainEvent({
    event_type: 'workflow.running',
    aggregate_id: 'wf_42',
    payload: { current_stage: 'SCRIPTING' },
  });
  assert.equal(state.projectTokens.length, 1);
  assert.equal(state.projectTokens[0].stage, 'SCRIPTING');
  // The token stands in the department the backend serves for that stage, not at a
  // coordinate baked into the frontend.
  assert.equal(state.projectTokens[0].x, 520, 'beside the script desk');
  assert.equal(state.projectTokens[0].y, 420, 'on the second floor');
});

test('every workflow stage lands inside a department the backend actually serves', () => {
  const state = new OfficeState();
  state.initFromLayout({ width: 1200, height: 1000, zones: LIFT_ZONES_WITH_DESKS });

  const stages = [
    'DISCOVERY', 'RESEARCH', 'FACT_CHECK', 'SCRIPTING', 'STORYBOARD',
    'VOICE_GENERATION', 'VIDEO_GENERATION', 'EDITING', 'QUALITY_CONTROL',
    'READY_TO_PUBLISH', 'PUBLISHING', 'PUBLISHED', 'ANALYTICS',
  ];
  for (const stage of stages) {
    state.updateProjectToken('wf_stage', stage);
    const token = state.projectTokens[0];
    // Two departments share floor 1, so the token must fall inside one zone's full box.
    const zone = LIFT_ZONES_WITH_DESKS.find(
      z =>
        token.y >= z.y &&
        token.y <= z.y + z.height &&
        token.x >= z.x &&
        token.x <= z.x + z.width,
    );
    assert.ok(
      zone,
      `${stage} placed the token at ${token.x},${token.y} — inside no department`,
    );
  }
});

test('no token is placed before the backend layout has arrived', () => {
  const state = new OfficeState();
  state.updateProjectToken('wf_early', 'SCRIPTING');
  assert.equal(state.projectTokens.length, 0, 'a guessed position is worse than none');
});

test('pedestrians stand entirely below the building base', () => {
  // Regression: the pavement used to overlap the ground floor, so passers-by appeared to
  // walk through the studio. A person on the pavement must clear the base course.
  for (const base of [600, 750, 800, 940]) {
    const g = streetGeometry(base);
    assert.ok(g.standLine > base, 'pavement must start below the building base');
    assert.ok(
      g.standLine - PEDESTRIAN_HEIGHT > base,
      `a pedestrian at base ${base} pokes into the ground floor (headroom ${g.headroom})`,
    );
    assert.ok(g.headroom > 0);
  }
});

test('street layers stack in the right order and fit the world', () => {
  const g = streetGeometry(800);
  assert.ok(g.plinthTop < g.pavementTop);
  assert.ok(g.pavementTop < g.standLine);
  assert.ok(g.standLine < g.roadTop);
  assert.ok(g.roadTop < g.roadBottom);
  assert.ok(g.roadBottom <= g.worldHeight, 'the carriageway must fit inside the world buffer');
});

const TRAFFIC_WORLD_W = 1200;
const TRAFFIC_LOOP = TRAFFIC_WORLD_W + 120 - -180;

/** Circular bumper gap to the car ahead in the same lane, mirroring updateTraffic. */
function trafficGaps(cars) {
  const gaps = [];
  for (const dir of [1, -1]) {
    const lane = cars.filter((c) => c.dir === dir).sort((a, b) => (b.x - a.x) * dir);
    if (lane.length < 2) continue;
    for (let i = 0; i < lane.length; i += 1) {
      const leader = i === 0 ? lane[lane.length - 1] : lane[i - 1];
      let ahead = (leader.x - lane[i].x) * dir;
      if (i === 0) ahead += TRAFFIC_LOOP;
      gaps.push(dir > 0 ? ahead - lane[i].style.w : ahead - leader.style.w);
    }
  }
  return gaps;
}

test('traffic spawns with every same-lane bumper gap positive', () => {
  const cars = makeTraffic(0x33aa);
  assert.equal(cars.length, 5);
  for (const gap of trafficGaps(cars)) assert.ok(gap > 0, `spawn gap ${gap}`);
});

test('a fast car never drives through a slower car in its lane', () => {
  // Sedan at 100 px/s closes on a bus at 52 px/s; without the platoon rule it would
  // pass through it in under five seconds.
  const cars = [
    { dir: 1, laneOffset: 0.78, x: 400, speed: 100, bobPhase: 0, style: { w: 90, h: 30 } },
    { dir: 1, laneOffset: 0.78, x: 700, speed: 52, bobPhase: 0, style: { w: 168, h: 50 } },
  ];
  for (let t = 0; t < 60; t += 1 / 30) {
    updateTraffic(cars, TRAFFIC_WORLD_W, 1 / 30);
    for (const gap of trafficGaps(cars)) {
      assert.ok(gap > 0, `bumper overlap at t=${t.toFixed(2)}s (gap ${gap})`);
    }
  }
});

test('traffic never overlaps across the wrap seam over a long run', () => {
  const cars = makeTraffic(0x33aa);
  // Mixed timesteps including the engine's 50 ms cap, over roughly twelve loop laps.
  const steps = [1 / 60, 1 / 30, 0.05, 1 / 60, 1 / 45];
  for (let i = 0; i < 9000; i += 1) {
    updateTraffic(cars, TRAFFIC_WORLD_W, steps[i % steps.length]);
    if (i % 7 === 0) {
      for (const gap of trafficGaps(cars)) {
        assert.ok(gap > 0, `seam overlap at step ${i} (gap ${gap})`);
      }
    }
  }
});

/* --------------------------------------------------------------------------
 * Lift choreography
 *
 * The cab exists to carry work between departments. Two rules matter and both are
 * about honesty rather than looks: it must stand still when the backend reports no
 * movement, and the courier riding it must correspond to a token that really changed
 * floor. The trip state machine is exercised directly, without a canvas.
 * ------------------------------------------------------------------------ */

/** A minimal engine stand-in carrying only the state _updateLift touches. */
function liftHarness() {
  const engine = Object.create(OfficeEngine.prototype);
  engine.layout = { zones: LIFT_ZONES_WITH_DESKS };
  engine.building = { x: 120, y: 60, width: 960, height: 740 };
  engine.shaft = { ex: 980, ew: 90 };
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
  const ground = LIFT_ZONES_WITH_DESKS[4];
  engine.projectTokens = [tokenAt(ground)];

  engine.step(20);

  assert.equal(engine.lift.moving, false, 'a cab with no job must not move');
  assert.equal(engine.lift.trip, null, 'no token moved, so nobody is riding');
  assert.equal(engine.lift.y, 734, 'the cab stays exactly where it was parked');
});

test('a token changing floor sends a courier through the cab and out again', () => {
  const engine = liftHarness();
  const ground = LIFT_ZONES_WITH_DESKS[4];
  const script = LIFT_ZONES_WITH_DESKS[2];

  // First sighting only records where the work is; it is not yet a movement.
  engine.projectTokens = [tokenAt(ground, 690)];
  engine.step(0.5);
  assert.equal(engine.lift.trip, null, 'seeing a token for the first time is not a trip');

  // The workflow advances to a stage two floors up.
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

  assert.deepEqual(
    [...seen].sort(),
    ['alight', 'board', 'summon', 'travel'],
    'the delivery must pass through every stage',
  );
  assert.equal(engine.lift.trip, null, 'and finish');
  assert.ok(
    Math.abs(engine.lift.y - (script.y + script.height - 66)) <= 1,
    'the cab ends at the destination floor',
  );
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
    if (trip && trip.phase === 'travel') {
      assert.ok(engine.lift.moving || Math.abs(engine.lift.y - trip.toY) <= 1);
    }
    if (trip && (trip.phase === 'board' || trip.phase === 'alight')) {
      assert.equal(engine.lift.moving, false, 'the cab must be stopped while someone steps through');
    }
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
