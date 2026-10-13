// W21: after a window resize the stream's video took its new box in the frame the layout changed,
// but the camera laid on it (and the plaques over it) followed a frame or two later, up to 363 px
// off. The engine now says, in that same frame, the camera its deferred resize will set.
import test from 'node:test';
import assert from 'node:assert/strict';
import { OfficeEngine, Viewport, BUILDING } from '../src/office_engine.js';
import { streamTransform } from '../src/game_frame.js';

function engineAt(cssW, cssH, dpr = 1) {
  const previous = globalThis.window;
  globalThis.window = { devicePixelRatio: dpr };
  const parent = { clientWidth: cssW, clientHeight: cssH, querySelector: () => null };
  const canvas = { width: cssW * dpr, height: cssH * dpr, parentElement: parent };
  const e = Object.create(OfficeEngine.prototype);
  Object.assign(e, {
    canvas, worldW: 1600, worldH: 840, dpr, glide: null, _resizeQueued: false, _viewKey: '',
    viewport: new Viewport(canvas),
  });
  e.viewport.focus = { x: BUILDING.x, y: BUILDING.y, width: BUILDING.width, height: BUILDING.height };
  e._cssInsets = { left: 360, right: 340, top: 60, bottom: 0 };
  e._cssFloor = { left: 44, right: 44, top: 60, bottom: 0 };
  e._restateInsets();
  e.viewport.fitFrame(e.worldW, e.worldH);
  return { e, parent, restore: () => { globalThis.window = previous; } };
}

for (const [from, to, dpr] of [[[1920, 1008], [1536, 856], 1], [[1280, 728], [1920, 1008], 1], [[2560, 1368], [1280, 728], 1], [[1920, 1008], [1440, 800], 2]]) {
  test(`the camera said at once for ${from.join('x')} → ${to.join('x')} (dpr ${dpr}) is the one resize() then sets`, () => {
    const { e, parent, restore } = engineAt(from[0], from[1], dpr);
    try {
      parent.clientWidth = to[0];
      parent.clientHeight = to[1];
      const planned = e.plannedView(to[0], to[1]);
      e.resize();
      const actual = e.view();
      for (const k of ['cw', 'ch', 'dpr', 'zoom', 'panX', 'panY']) assert.ok(Math.abs(planned[k] - actual[k]) < 1e-6, `${k}: ${planned[k]} vs ${actual[k]}`);
      const box = e.frameBox();
      for (const k of ['left', 'top', 'right', 'bottom']) assert.ok(Math.abs(planned.room[k] - box.room[k]) < 1e-6, k);
      // the stream's transform from either is the same to the hundredth of a pixel
      const a = streamTransform(planned);
      const b = streamTransform(actual);
      assert.ok(Math.abs(a.k - b.k) < 1e-9 && Math.abs(a.tx - b.tx) < 0.01 && Math.abs(a.ty - b.ty) < 0.01);
    } finally {
      restore();
    }
  });
}

test('the box changes: the camera is said in that frame, and the frame before the resize says nothing stale', () => {
  const { e, parent, restore } = engineAt(1920, 1008);
  try {
    const said = [];
    e.onView = (v) => said.push(v);
    parent.clientWidth = 1536;
    parent.clientHeight = 856;
    e._emitPlannedView();
    assert.equal(said.length, 1);
    assert.equal(said[0].cw, 1536);
    assert.ok(said[0].room, 'with the room the plaques are laid in');
    // the loop's frame before the queued resize: the old canvas is not said over the planned camera
    e._resizeQueued = true;
    e._emitView();
    assert.equal(said.length, 1);
    // the resize's own frame: the same camera, not said twice
    e._resizeQueued = false;
    e.resize();
    e._emitView();
    assert.equal(said.length, 1);
  } finally {
    restore();
  }
});

test('the drawers of the new size are laid out before the camera is planned (the resize event can come a frame late)', () => {
  const { e, parent, restore } = engineAt(1946, 1116);
  try {
    const said = [];
    e.onView = (v) => said.push(v);
    // the box is already 2560 wide; the window's resize event has not come yet
    parent.clientWidth = 2560;
    parent.clientHeight = 1346;
    const stale = e.plannedView(2560, 1346);
    e.beforePlan = () => e.setInsets({ left: 44, right: 44, top: 48, bottom: 0 }, { glide: false, floor: { left: 44, right: 44, top: 48, bottom: 0 } });
    e._emitPlannedView();
    assert.equal(said.length, 1);
    e.resize();
    const actual = e.view();
    assert.ok(Math.abs(said[0].panX - actual.panX) < 1e-6 && Math.abs(said[0].zoom - actual.zoom) < 1e-6, 'planned with the new drawers');
    assert.ok(Math.abs(stale.panX - actual.panX) > 1, 'without them it would have been off');
  } finally {
    restore();
  }
});

// W26: the adversary's probe, which reads the page inside requestAnimationFrame, still saw the façade
// plaque 252-363 px off its sign for one frame after a window resize: the ResizeObserver that said the
// planned camera runs after the frame's rAF callbacks. The engine now reads its box first in its own
// frame and says the planned camera there; the observer then says the same camera again, unchanged.
test('the engine reads its box first in its frame and says the planned camera when it changed', () => {
  const { e, parent, restore } = engineAt(1920, 1008);
  try {
    const said = [];
    e.onView = (v) => said.push(v);
    e.parked = false;
    const queued = [];
    const previousRaf = globalThis.requestAnimationFrame;
    globalThis.requestAnimationFrame = (fn) => { queued.push(fn); return queued.length; };
    e._watchBox();
    assert.equal(said.length, 0, 'the first reading only learns the box');
    e._watchBox();
    assert.equal(said.length, 0, 'an unchanged box says nothing');
    parent.clientWidth = 1536;
    parent.clientHeight = 856;
    e._watchBox();
    assert.equal(said.length, 1);
    assert.equal(said[0].cw, 1536);
    assert.equal(e._resizeQueued, true, 'the resize waits for its own frame');
    e._emitView();
    assert.equal(said.length, 1, 'the loop does not say the old canvas over the planned camera');
    e._watchBox();
    assert.equal(said.length, 1, 'once per change');
    globalThis.requestAnimationFrame = previousRaf;
    e.parked = true;
    parent.clientWidth = 1280;
    e._watchBox();
    assert.equal(said.length, 1, 'a parked engine (the title) says nothing');
  } finally {
    restore();
  }
});

test('the loop reads the box before it draws', () => {
  const src = OfficeEngine.prototype._loop.toString();
  assert.ok(src.indexOf('this._watchBox()') > -1 && src.indexOf('this._watchBox()') < src.indexOf('this._draw()'));
});
