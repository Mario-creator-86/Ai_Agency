// W25 «a tag inside the frame»: at the replay's end at 1920 the tag «Marcus (Script Writer) · a
// terminat · scenariul» read «…cus (Script Writer)»: it was kept inside the world, and the world runs
// on under the register's drawer. Tags and replayed captions now stay inside the part of the world
// the frame shows, between the drawers.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { visibleSpan } from '../src/hq_world.js';

const WORLD = fs.readFileSync(new URL('../src/hq_world.js', import.meta.url), 'utf8');
const ENGINE = fs.readFileSync(new URL('../src/office_engine.js', import.meta.url), 'utf8');

test('the span is the part of the world between the drawers, less a margin', () => {
  assert.deepEqual(visibleSpan([120, 1500], 1600, 2), [122, 1498]);
});

test('the world edges still hold where the frame shows past them', () => {
  assert.deepEqual(visibleSpan([-50, 1800], 1600, 2), [2, 1598]);
});

test('no span said, or one too narrow to be real: the world, as before', () => {
  assert.deepEqual(visibleSpan(null, 1600, 2), [2, 1598]);
  assert.deepEqual(visibleSpan([800, 810], 1600, 2), [2, 1598]);
  assert.deepEqual(visibleSpan([Number.NaN, 900], 1600, 2), [2, 1598]);
});

test('the engine tells the renderer the span it shows, live and over the replay', () => {
  assert.equal((ENGINE.match(/^\s+span,\r?$/gm) || []).length, 2);
  assert.match(ENGINE, /const span = \[\(ins\.left - panX\) \/ zoom, \(w - ins\.right - panX\) \/ zoom\];/);
});

test('the arrival tags, the replayed captions and the name tag keep inside it', () => {
  assert.match(WORLD, /const \[lo, hi\] = visibleSpan\(state\.span, this\.world\.worldW, px\(2\)\);\r?\n(?:\s*\/\/.*\r?\n)*\s+const x = tagClear\(mid - tw \/ 2, hit\.y1 \+ px\(6\), tw, th, taken, lo, hi, px\(6\), tw\);/);
  assert.match(WORLD, /captionPlace\(want, item\.x, laid, lo, hi, px\(6\), px\(12\)\)/);
  assert.match(WORLD, /const x = Math\.min\(hiTag - tw, Math\.max\(loTag, seat\.x - tw \/ 2\)\);/);
});

test('a tag never leaves its speaker for a free place across the room', async () => {
  // W25, seen at 1920: kept inside the frame, «Marcus (Script Writer) · …» found its row taken by a
  // replayed caption and the nearest free place was past Vera's tag, 900 px from Marcus: it read as
  // hers. A free place farther than the tag's own width is not taken; the tag stands where it wants
  const { tagClear } = await import('../src/hq_world.js');
  const cap = { x: 250, y: 20, w: 220, h: 40 };
  const vera = { x: 480, y: 10, w: 300, h: 28 };
  // free only past Vera: too far for a 290-wide tag that wants 30
  assert.equal(tagClear(30, 10, 290, 28, [cap, vera], 12, 1600, 6, 290), 30);
  // the W23 behaviour is kept when no limit is said
  assert.equal(tagClear(30, 10, 290, 28, [cap, vera], 12, 1600, 6), 786);
  // a near free place is still taken
  assert.equal(tagClear(120, 10, 50, 20, [{ x: 150, y: 0, w: 50, h: 40 }], 0, 1000, 6, 50), 94);
});

test('the arrival tags use the limit', () => {
  assert.match(WORLD, /tagClear\(mid - tw \/ 2, hit\.y1 \+ px\(6\), tw, th, taken, lo, hi, px\(6\), tw\)/);
});
