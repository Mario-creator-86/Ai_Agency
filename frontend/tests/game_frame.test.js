// THE GAME FRAME: the render is the first viewport, and two glass drawers lie over its edges.
// These are the promises the frame makes, checked without a page: the building is never covered
// by a drawer the page opened on its own, bare ground past the world's edge appears only under a
// drawer, and the streamed picture moves exactly as the page's hit boxes do.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  NO_INSETS,
  between,
  drawerDefaults,
  drawerInsets,
  easeOut,
  frameFit,
  frameFloor,
  railCount,
  resolveDrawers,
  streamTransform,
} from '../src/game_frame.js';

const WORLD = { worldW: 1600, worldH: 840 };
/** The building in the manifest's world (office_engine.js). */
const BUILDING = { x: 415, y: 10, width: 937, height: 665 };
const close = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;

/** Where a world point lands on screen for a camera. */
const at = (fit, x, y) => ({ x: x * fit.zoom + fit.panX, y: y * fit.zoom + fit.panY });

test('with no drawer the world covers the viewport and nothing past its edge is seen', () => {
  for (const [cw, ch] of [[1920, 988], [2560, 1348], [1280, 708], [1440, 808], [1600, 840]]) {
    const fit = frameFit({ cw, ch, ...WORLD, focus: BUILDING });
    const tl = at(fit, 0, 0);
    const br = at(fit, 1600, 840);
    assert.ok(tl.x <= 1e-6 && tl.y <= 1e-6, `${cw}x${ch}: the world's top-left is off screen`);
    assert.ok(br.x >= cw - 1e-6 && br.y >= ch - 1e-6, `${cw}x${ch}: the world's bottom-right is off screen`);
  }
});

test('a box of the world\'s own shape is filled exactly, as the old contain fit did', () => {
  const fit = frameFit({ cw: 1600, ch: 840, ...WORLD, focus: BUILDING });
  assert.ok(close(fit.zoom, 1) && close(fit.panX, 0) && close(fit.panY, 0));
});

test('with both drawers open at 1920 the building sits whole in the room between them', () => {
  const insets = { left: 360, right: 340, top: 0, bottom: 0 };
  const fit = frameFit({ cw: 1920, ch: 988, ...WORLD, focus: BUILDING, insets });
  const left = at(fit, BUILDING.x, 0).x;
  const right = at(fit, BUILDING.x + BUILDING.width, 0).x;
  assert.ok(left >= 360, `the building starts right of the register (${left})`);
  assert.ok(right <= 1920 - 340, `and ends left of the approvals (${right})`);
  // centred in the free room
  assert.ok(close(left - 360, 1920 - 340 - right, 1e-6));
});

test('bare ground past the world\'s edge appears only under a drawer', () => {
  const insets = { left: 360, right: 340, top: 0, bottom: 0 };
  const fit = frameFit({ cw: 1920, ch: 988, ...WORLD, focus: BUILDING, insets });
  const worldLeft = at(fit, 0, 0).x;
  const worldRight = at(fit, 1600, 0).x;
  assert.ok(worldLeft <= insets.left, 'any bare strip on the left is under the register');
  assert.ok(worldRight >= 1920 - insets.right, 'any bare strip on the right is under the approvals');
  // and with the drawers closed to their rails, the camera goes back to covering the viewport
  const rails = frameFit({ cw: 1920, ch: 988, ...WORLD, focus: BUILDING, insets: { left: 40, right: 40, top: 0, bottom: 0 } });
  assert.ok(at(rails, 0, 0).x <= 40 && at(rails, 1600, 0).x >= 1880);
});

test('a tall narrow box keeps the building whole rather than covering the box', () => {
  const fit = frameFit({ cw: 318, ch: 468, ...WORLD, focus: BUILDING });
  const left = at(fit, BUILDING.x, BUILDING.y);
  const right = at(fit, BUILDING.x + BUILDING.width, BUILDING.y + BUILDING.height);
  assert.ok(left.x >= -1e-6 && right.x <= 318 + 1e-6, 'the building is seen from side to side');
  assert.ok(left.y >= -1e-6 && right.y <= 468 + 1e-6);
});

test('the page opens a drawer only when the building still fits beside it', () => {
  const widths = (cw) => ({ registerW: Math.min(400, Math.max(300, cw * 0.1875)), sideW: Math.min(380, Math.max(290, cw * 0.177)), railW: 40 });
  const frames = { 1920: 988, 2560: 1348, 1440: 808, 1280: 708 };
  const got = Object.fromEntries(Object.entries(frames).map(([cw, ch]) => [cw, drawerDefaults({ cw: Number(cw), ch, ...WORLD, focus: BUILDING, ...widths(Number(cw)) })]));
  assert.deepEqual(got[1920], { register: true, side: true });
  assert.deepEqual(got[2560], { register: true, side: true });
  assert.deepEqual(got[1440], { register: true, side: false });
  assert.deepEqual(got[1280], { register: true, side: false });
  // and whatever it opens, the building then fits in the room left
  for (const [cw, ch] of Object.entries(frames)) {
    const open = got[cw];
    const insets = drawerInsets(open, widths(Number(cw)));
    const fit = frameFit({ cw: Number(cw), ch, ...WORLD, focus: BUILDING, insets });
    assert.ok(at(fit, BUILDING.x, 0).x >= insets.left - 1e-6, `${cw}: the building clears the left drawer`);
    assert.ok(at(fit, BUILDING.x + BUILDING.width, 0).x <= Number(cw) - insets.right + 1e-6, `${cw}: and the right one`);
  }
});

test('a screen too small for any drawer opens none', () => {
  const open = drawerDefaults({ cw: 1060, ch: 900, ...WORLD, focus: BUILDING, registerW: 300, sideW: 290, railW: 40 });
  assert.deepEqual(open, { register: false, side: false });
});

test('the drawers take their own width when open and their rail when closed', () => {
  const w = { registerW: 360, sideW: 340, railW: 40 };
  assert.deepEqual(drawerInsets({ register: true, side: false }, w), { left: 360, right: 40, top: 0, bottom: 0 });
  assert.deepEqual(drawerInsets({ register: false, side: true }, w), { left: 40, right: 340, top: 0, bottom: 0 });
  assert.deepEqual(NO_INSETS, { left: 0, right: 0, top: 0, bottom: 0 });
});

test('the streamed picture lands where the page\'s camera puts the world', () => {
  // A 1920x988 box, a stream laid in it whole like object-fit: contain, and the camera zoomed and
  // dragged: every world point the video shows must fall where the hit boxes say it is.
  const cw = 1920;
  const ch = 988;
  const native = Math.min(cw / 1600, ch / 840);
  const nx = (cw - 1600 * native) / 2;
  const ny = (ch - 840 * native) / 2;
  for (const view of [
    { zoom: native, panX: nx, panY: ny },
    { zoom: 2.1, panX: -640, panY: -300 },
    { zoom: 1.2, panX: -90, panY: 0 },
  ]) {
    const t = streamTransform({ cw, ch, ...WORLD, ...view });
    for (const [x, y] of [[0, 0], [883.5, 342.5], [1600, 840], [415, 675]]) {
      const inVideo = { x: x * native + nx, y: y * native + ny };
      const shown = { x: inVideo.x * t.k + t.tx, y: inVideo.y * t.k + t.ty };
      const hit = { x: x * view.zoom + view.panX, y: y * view.zoom + view.panY };
      assert.ok(close(shown.x, hit.x, 1e-6) && close(shown.y, hit.y, 1e-6), `(${x}, ${y}) at zoom ${view.zoom}`);
    }
  }
  // at the stream's own framing the transform is the identity
  const still = streamTransform({ cw, ch, ...WORLD, zoom: native, panX: nx, panY: ny });
  assert.ok(close(still.k, 1) && close(still.tx, 0) && close(still.ty, 0));
});

test('a glide runs from one stand to the other and stops there', () => {
  const a = { zoom: 1, panX: 0, panY: 0 };
  const b = { zoom: 2, panX: -100, panY: 50 };
  assert.deepEqual(between(a, b, 0), a);
  assert.deepEqual(between(a, b, 1), b);
  assert.deepEqual(between(a, b, 7), b);
  assert.equal(between(a, b, 0.5).zoom, 1.5);
  assert.equal(easeOut(0), 0);
  assert.equal(easeOut(1), 1);
  assert.ok(easeOut(0.5) > 0.5, 'it decelerates');
});

test('a drawer the visitor opened or closed stays that way; the others follow the screen', () => {
  const fits = { register: true, side: false };
  assert.deepEqual(resolveDrawers(null, fits), fits);
  assert.deepEqual(resolveDrawers({}, fits), fits);
  assert.deepEqual(resolveDrawers({ side: true }, fits), { register: true, side: true });
  assert.deepEqual(resolveDrawers({ register: false }, fits), { register: false, side: false });
  assert.deepEqual(resolveDrawers({ register: 'yes', side: 1 }, fits), fits, 'only a real choice counts');
});

test('a closed drawer\'s rail repeats the panel\'s own count and nothing else', () => {
  assert.equal(railCount('70 de intrări'), '70 de intrări');
  assert.equal(railCount('—'), '');
  assert.equal(railCount(null), '');
  assert.equal(railCount(' NICIUNA '), 'NICIUNA');
});

// W8: THE ROOF UNDER OPEN SKY. The frame keeps a row of sky over the roof for the instruments
// (--hud-top) and its rails at the sides; the zoom is chosen against that floor.
const HUD = 48;
const FRAMES = { 1280: 706, 1440: 806, 1920: 986, 2560: 1346 };
const railsOf = () => frameFloor({ railW: 40, hudTop: HUD });

test('the world top edge stands at the sky row, so the roof is never under an instrument', () => {
  for (const [cw, ch] of Object.entries(FRAMES)) {
    for (const insets of [{ left: 40, right: 40, top: HUD, bottom: 0 }, { left: 360, right: 340, top: HUD, bottom: 0 }]) {
      const fit = frameFit({ cw: Number(cw), ch, ...WORLD, focus: BUILDING, insets, floor: railsOf() });
      assert.ok(close(at(fit, 0, 0).y, HUD, 1e-6), `${cw}: the world starts at the sky row (${at(fit, 0, 0).y})`);
      assert.ok(at(fit, 0, 840).y >= ch - 1e-6, `${cw}: and reaches the frame's bottom`);
      assert.ok(at(fit, 0, 0).x <= insets.left + 1e-6 && at(fit, 1600, 0).x >= Number(cw) - insets.right - 1e-6, `${cw}: nothing bare beside it but under glass`);
    }
  }
});

test('the near lane stays above the slate at every frame', () => {
  const SLATE = 28;
  for (const [cw, ch] of Object.entries(FRAMES)) {
    const fit = frameFit({ cw: Number(cw), ch, ...WORLD, focus: BUILDING, insets: { left: 40, right: 40, top: HUD, bottom: 0 }, floor: railsOf() });
    assert.ok(at(fit, 0, 790).y <= ch - SLATE + 1e-6, `${cw}: the road's near kerb at ${at(fit, 0, 790).y.toFixed(1)} is above the slate at ${ch - SLATE}`);
  }
});

test('opening a drawer moves the camera and never resizes the house', () => {
  const floor = railsOf();
  const closed = frameFit({ cw: 1920, ch: 986, ...WORLD, focus: BUILDING, insets: { left: 40, right: 40, top: HUD, bottom: 0 }, floor });
  const open = frameFit({ cw: 1920, ch: 986, ...WORLD, focus: BUILDING, insets: { left: 360, right: 340, top: HUD, bottom: 0 }, floor });
  assert.equal(closed.zoom, open.zoom);
  assert.deepEqual(frameFloor({ railW: 40, hudTop: HUD }), { left: 40, right: 40, top: HUD, bottom: 0 });
  assert.deepEqual(frameFloor(), NO_INSETS);
  assert.deepEqual(drawerInsets({ register: true, side: false }, { registerW: 360, sideW: 340, railW: 40, hudTop: HUD }), { left: 360, right: 40, top: HUD, bottom: 0 });
});

test('with the sky row the page still opens only the drawers the building fits beside', () => {
  const widths = (cw) => ({ registerW: Math.min(400, Math.max(300, cw * 0.1875)), sideW: Math.min(380, Math.max(290, cw * 0.177)), railW: 40, hudTop: HUD });
  const got = Object.fromEntries(Object.entries(FRAMES).map(([cw, ch]) => [cw, drawerDefaults({ cw: Number(cw), ch, ...WORLD, focus: BUILDING, ...widths(Number(cw)) })]));
  assert.deepEqual(got, { 1280: { register: true, side: false }, 1440: { register: true, side: false }, 1920: { register: true, side: true }, 2560: { register: true, side: true } });
});

// W10: THE SLATE OFF THE KERB. With both drawers open at 1280 and 1440 the slate's room is 690px
// and 850px, and its caption used to take a line of its own: a 56px slate covered the near kerb
// by 12-18px. The slate is now one line (office_scene.css, the short caption), and the kerb clears
// a one-line slate at every frame with both drawers open as well as closed.
test('with both drawers open the near kerb stays above a one-line slate at 1280 and 1440', () => {
  const SLATE = 28;
  const widths = (cw) => ({ left: Math.min(400, Math.max(300, cw * 0.1875)), right: Math.min(380, Math.max(290, cw * 0.177)) });
  for (const [cw, ch] of Object.entries(FRAMES)) {
    const { left, right } = widths(Number(cw));
    const fit = frameFit({ cw: Number(cw), ch, ...WORLD, focus: BUILDING, insets: { left, right, top: HUD, bottom: 0 }, floor: railsOf() });
    const kerb = at(fit, 0, 790).y;
    assert.ok(kerb <= ch - SLATE + 1e-6, `${cw}: the kerb at ${kerb.toFixed(1)} is above the one-line slate at ${ch - SLATE}`);
    if (Number(cw) <= 1440) assert.ok(kerb > ch - 2 * SLATE, `${cw}: a two-line slate (${ch - 2 * SLATE}) would cover it (${kerb.toFixed(1)})`);
  }
});
