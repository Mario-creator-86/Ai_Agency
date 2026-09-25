// W30, DOORS AT 60 FPS. A door's parts are laid out only once its words begin to show, one step
// per frame, heavy parts in pieces; the mail and the inspector lay out their content once the
// pane has landed; the pane's warm edge is a gradient, not two blurred shadows; the mail's reply
// has no resize grip; the key light reads its pixels without the main thread waiting on the GPU.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { DOOR_REVEAL_SHARE, doorLanded, doorRevealAt, doorSteps, doorTiming } from '../src/dialog_doors.js';
import { KeyLight, readAsync } from '../src/key_light.js';

const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
const MAIL = fs.readFileSync(new URL('../src/mail_thread.js', import.meta.url), 'utf8');
const SERIAL = fs.readFileSync(new URL('../src/serial_room.js', import.meta.url), 'utf8');

const TOKENS = { '--dur-room-open': '340ms', '--dur-room-close': '300ms', '--dur-room-fade': '180ms', '--ease-push': 'ease', '--ease': 'ease' };
const token = (/** @type {string} */ n) => /** @type {Record<string,string>} */ (TOKENS)[n] || '';

test('the parts wait until the words begin to show; under reduced motion they come at once', () => {
  const moving = doorTiming(false, token);
  assert.equal(doorRevealAt(moving), Math.round(340 * DOOR_REVEAL_SHARE));
  // before the content's fade-in (it starts at half the opening, doorKeyframes)
  assert.ok(doorRevealAt(moving) < 340 * 0.5);
  assert.equal(doorRevealAt(doorTiming(true, token)), 0);
});

/** A tiny element: children, and whether it asks to be laid out in pieces. */
function el(name, steps, kids = []) {
  return { name, children: kids, hasAttribute: (/** @type {string} */ a) => a === 'data-door-steps' && steps };
}

test('a heavy part is laid out in its pieces, one per frame; a plain part is one step', () => {
  const room = el('room', false);
  const slate = el('slate', false);
  const episode = el('episode', true, [slate, room]);
  const episodes = el('episodes', true, [episode]);
  const cover = el('cover', false);
  const first = el('st-episodes', true, [cover, el('h3', false), episodes]);
  const days = el('st-days', false, [el('x', false)]);
  const steps = doorSteps(/** @type {any} */ ([first, days]));
  assert.deepEqual(steps.map((/** @type {any} */ s) => s.name), ['cover', 'h3', 'slate', 'room', 'st-days']);
  // an empty heavy part is itself a step
  assert.deepEqual(doorSteps(/** @type {any} */ ([el('empty', true)])).map((/** @type {any} */ s) => s.name), ['empty']);
});

test('the Journal says which of its parts are heavy: the episodes and the newest episode', () => {
  assert.match(HTML, /id="st-episodes" data-door-steps/);
  assert.match(HTML, /id="story-episodes"[^>]*data-door-steps/);
  assert.match(SERIAL, /' data-door-steps open'/);
});

test('a door not moving has landed at once', async () => {
  const t0 = Date.now();
  await doorLanded(/** @type {any} */ ({}));
  assert.ok(Date.now() - t0 < 50);
});

test('the mail and the inspector lay out their content once the pane has landed', () => {
  assert.match(MAIL, /if \(opening\) await this\.landed\(\);/);
  assert.match(MAIN, /landed: \(\) => doorLanded\(/);
  assert.match(MAIN, /await doorLanded\(inspector\);\s*\n\s*if\(request!==inspectorRequest/);
  assert.match(MAIN, /revealInSteps\(INSPECTOR_HEAVY/);
  // a fresh opening shows no one else's contract while it grows
  assert.match(MAIN, /if \(!inspector\.open\) clearInspectorBody\(\);/);
});

test('the pane\'s warm edge is a gradient, not two blurred shadows; the reply has no resize grip', () => {
  const edge = STYLE.slice(STYLE.indexOf('.studio-dialog.has-door::after {'));
  const rule = edge.slice(0, edge.indexOf('}'));
  assert.ok(!/box-shadow:[^;]*\d+px \d+px/.test(rule.replace('0 0 0 1px', '')), 'no blurred shadow on the edge');
  assert.match(rule, /linear-gradient/);
  assert.match(STYLE, /\.mail-reply textarea \{[^}]*resize: none/);
});

test('the key light copies its 64 bytes out through a VideoFrame when the browser has one', async () => {
  const g = /** @type {any} */ (globalThis);
  const saved = { VideoFrame: g.VideoFrame, createImageBitmap: g.createImageBitmap, window: g.window };
  let closed = 0;
  g.VideoFrame = class {
    allocationSize() { return 64; }
    async copyTo(/** @type {Uint8Array} */ buf) { for (let i = 0; i < 64; i += 4) buf.set([200, 120, 60, 255], i); }
    close() { closed++; }
  };
  try {
    const bytes = await readAsync(/** @type {any} */ ({}));
    assert.ok(bytes && bytes.length === 64 && bytes[0] === 200);
    assert.equal(closed, 1);
    // the sampler writes the light from those bytes, and never draws into a canvas
    g.createImageBitmap = async () => ({ close() {} });
    const set = /** @type {Record<string,string>} */ ({});
    const light = new KeyLight({ target: /** @type {any} */ ({ style: { setProperty: (/** @type {string} */ k, /** @type {string} */ v) => { set[k] = v; }, removeProperty() {} } }), source: () => /** @type {any} */ ({ width: 100, height: 50 }) });
    light.timer = 1;
    await light.sample();
    assert.match(set['--key-cool'] || '', /^rgba\(/);
    assert.equal(light.small, null, 'no canvas was made to read the pixels');
    // a browser that refuses the conversion: null, and the canvas path takes over
    g.VideoFrame = class { constructor() { throw new Error('no'); } };
    assert.equal(await readAsync(/** @type {any} */ ({})), null);
    delete g.VideoFrame;
    assert.equal(await readAsync(/** @type {any} */ ({})), null);
  } finally {
    g.VideoFrame = saved.VideoFrame;
    g.createImageBitmap = saved.createImageBitmap;
    if (saved.VideoFrame === undefined) delete g.VideoFrame;
    if (saved.createImageBitmap === undefined) delete g.createImageBitmap;
  }
});
