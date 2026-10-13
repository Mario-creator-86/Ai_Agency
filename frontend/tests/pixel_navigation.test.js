import test from 'node:test';
import assert from 'node:assert/strict';
import { sceneFrame } from '../src/pixel_navigation.js';

const frame = { width: 1200, height: 600, worldWidth: 960, worldHeight: 640, zoom: 1 };

test('fit shows the entire scene and needs no captured scroll', () => {
  const view = sceneFrame({ ...frame, panX: 300, panY: -200 });
  assert.equal(view.scale, 600 / 640); assert.equal(view.panX, 0); assert.equal(view.panY, 0); assert.equal(view.movable, false);
});

test('zoomed scene can reach every edge without moving off the artwork', () => {
  const view = sceneFrame({ ...frame, zoom: 2, panX: 10000, panY: -10000 });
  assert.equal(view.panX, 300); assert.equal(view.panY, -300); assert.equal(view.movable, true);
  const reverse = sceneFrame({ ...frame, zoom: 2, panX: -10000, panY: 10000 });
  assert.equal(reverse.panX, -300); assert.equal(reverse.panY, 300);
});

test('wide viewport keeps horizontal centering while allowing vertical navigation', () => {
  const view = sceneFrame({ ...frame, width: 1900, zoom: 1.5, panX: 50, panY: -50 });
  assert.equal(view.panX, 0); assert.equal(view.panY, -50); assert.equal(view.movable, true);
});

test('resize clamps previous offsets to the new frame', () => {
  const view = sceneFrame({ ...frame, width: 400, height: 900, zoom: 1.5, panX: 90, panY: 90 });
  assert.equal(view.panX, 90); assert.equal(view.panY, 0);
});
