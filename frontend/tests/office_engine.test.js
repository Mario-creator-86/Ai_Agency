import test from 'node:test';
import assert from 'node:assert/strict';
import {
  Viewport,
  streetGeometry,
  PEDESTRIAN_HEIGHT,
  makeTraffic,
  updateTraffic,
} from '../src/office_engine.js';
import { OfficeState } from '../src/office_state.js';

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
    height: 800,
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
  assert.equal(state.projectTokens[0].x, 130);
  assert.equal(state.projectTokens[0].y, 390);
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
