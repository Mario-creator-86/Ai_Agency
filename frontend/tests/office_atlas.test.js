import test from 'node:test';
import assert from 'node:assert/strict';
import { decodeKey, colorForCode, decodeImageData, CODE, loadAtlas, atlas } from '../src/office_atlas.js';
import { AMBIENT, SKIN, HAIR, CLOTH } from '../src/office_palette.js';

test('key colours decode to (material, tone) codes and nothing else does', () => {
  assert.equal(decodeKey(255, 0, 0), CODE.SKIN);
  assert.equal(decodeKey(255, 128, 128), CODE.SKIN + 4);
  assert.equal(decodeKey(64, 255, 64), CODE.HAIR + 2);
  assert.equal(decodeKey(96, 96, 255), CODE.GARMENT + 3);
  assert.equal(decodeKey(255, 255, 32), CODE.SECOND + 1);
  assert.equal(decodeKey(255, 0, 255), CODE.TRIM);
  assert.equal(decodeKey(255, 255, 255), CODE.EYE_WHITE);
  assert.equal(decodeKey(0, 0, 0), CODE.EYE_DARK);
  assert.equal(decodeKey(0xdf, 0xe6, 0xf0), null, 'glasses frames are fixed colours');
  assert.equal(decodeKey(255, 10, 10), null, 'off-step tones are not keys');
});

test('codes resolve to the look ramps; fixed colours pass through', () => {
  const look = { skin: SKIN[2], hair: HAIR[3], garment: CLOTH.navy, second: CLOTH.white, trim: CLOTH.teal };
  assert.equal(colorForCode(CODE.SKIN + 2, look, []), SKIN[2][2]);
  assert.equal(colorForCode(CODE.HAIR + 4, look, []), HAIR[3][4]);
  assert.equal(colorForCode(CODE.GARMENT, look, []), CLOTH.navy[0]);
  assert.equal(colorForCode(CODE.SECOND + 3, look, []), CLOTH.white[3]);
  assert.equal(colorForCode(CODE.EYE_DARK, look, []), AMBIENT.shadow);
  assert.equal(colorForCode(CODE.FIXED + 1, look, ['#111111', '#222222']), '#222222');
  assert.equal(colorForCode(CODE.CLEAR, look, []), null);
});

test('image data decodes pixel by pixel, collecting fixed colours once', () => {
  const data = new Uint8ClampedArray([
    255, 0, 0, 255,       // skin tone 0
    0, 0, 0, 10,          // transparent
    0x3a, 0x3a, 0x52, 255, // fixed
    0x3a, 0x3a, 0x52, 255, // same fixed colour again
  ]);
  const d = decodeImageData(data, 2, 2);
  assert.deepEqual(Array.from(d.codes), [CODE.SKIN, CODE.CLEAR, CODE.FIXED, CODE.FIXED]);
  assert.deepEqual(d.fixed, ['#3a3a52']);
});

test('without a DOM the atlas stays unavailable and callers fall back', async () => {
  assert.equal(await loadAtlas(), false);
  assert.equal(atlas.ready, false);
});
