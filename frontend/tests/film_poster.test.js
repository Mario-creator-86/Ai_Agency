import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { POSTER_MIN_DETAIL, POSTER_SAMPLES, keyFrame, keyFramesAt, locateMoov, lumaStats, pickBrightest } from '../src/film_poster.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));

// A real H.264 file, made the way the studio's assembler makes its films (libx264, yuv420p,
// +faststart): `ffmpeg -f lavfi -i testsrc2=size=90x160:rate=10:duration=3 -c:v libx264 -g 10
// -pix_fmt yuv420p -profile:v high -movflags +faststart poster_tiny.mp4`. ffprobe reads its
// packets as: #1 key frame at byte 1226, 2948 bytes; #11 key frame at byte 10108, 2867 bytes;
// profile High (0x64), level 1.0 (0x0a).
const film = new Uint8Array(fs.readFileSync(path.join(HERE, 'fixtures', 'poster_tiny.mp4')));

test('the index is found at the front of a faststart film, and a short read says it is incomplete', () => {
  const whole = locateMoov(new DataView(film.buffer, film.byteOffset, film.byteLength));
  assert.equal(whole.found, true);
  assert.equal(whole.complete, true);
  assert.ok(whole.end < 1226, 'the index ends before the first frame');
  const cut = film.subarray(0, 600);
  const partial = locateMoov(new DataView(cut.buffer, cut.byteOffset, cut.byteLength));
  assert.equal(partial.found, true);
  assert.equal(partial.complete, false);
  assert.equal(keyFrame(cut), null);
});

test('the first key frame is where ffprobe says, with the decoder configuration the file carries', () => {
  const frame = keyFrame(film, 0);
  assert.ok(frame);
  assert.equal(frame.codec, 'avc1.64000a');
  assert.equal(frame.width, 90);
  assert.equal(frame.height, 160);
  assert.equal(frame.sample, 1);
  assert.equal(frame.samples, 30);
  assert.equal(frame.offset, 1226);
  assert.equal(frame.size, 2948);
  // the avcC record starts with configurationVersion 1 and the profile/level of the codec string
  assert.deepEqual([...frame.description.subarray(0, 4)], [1, 0x64, 0x00, 0x0a]);
});

test('a poster further in is the last key frame before that point, so it decodes on its own', () => {
  // 0.4 of 30 frames is frame 12; the key frames are 1, 11 and 21, so it is 11.
  const frame = keyFrame(film, 0.4);
  assert.equal(frame.sample, 11);
  assert.equal(frame.offset, 10108);
  assert.equal(frame.size, 2867);
  // the bytes there begin a key frame's NAL units: a 4-byte length, then a NAL header
  const nal = film[frame.offset + 4] & 0x1f;
  assert.ok([5, 6, 7, 8, 9].includes(nal), `first NAL type ${nal}`);
});

test('something that is not a film has no poster', () => {
  assert.equal(keyFrame(new Uint8Array([0, 0, 0, 8, 0x66, 0x72, 0x65, 0x65])), null);
  assert.equal(keyFrame(new Uint8Array(0)), null);
});

// W10: THE RENDER BAY IS BRIGHT. The frame at POSTER_AT on the Owner's newest film was two small
// lights on black (luma 42 of 255). Five key frames are sampled once per film and the brightest
// one that is a picture is kept; nothing is filtered.

test('the render bay samples distinct key frames across the film, in the order they come', () => {
  // key frames 1, 11, 21 of 30: 0.1 -> 1, 0.3 -> 1, 0.5 -> 11, 0.7 -> 21, 0.9 -> 21
  const frames = keyFramesAt(film, POSTER_SAMPLES);
  assert.deepEqual(frames.map((f) => f.sample), [1, 11, 21]);
  assert.ok(frames.every((f, i) => !i || f.offset > frames[i - 1].offset));
});

test('the frame kept is the brightest that is a picture, measured on the Owner\'s film', () => {
  // ffmpeg on backend/storage/media/63e3da7c-.../final_short_9_16.mp4, the six key frames: mean luma
  // and the spread between a 4x7 grid of block means. The two brightest are near-flat stripes.
  const film = [
    { mean: 67.8, detail: 44.2 }, // a page of notes on black
    { mean: 42.7, detail: 26.7 }, // two lights: the old poster
    { mean: 133.3, detail: 38.1 }, // a flare
    { mean: 61.9, detail: 21.3 }, // a spiral
    { mean: 162.8, detail: 4.5 }, // stripes
    { mean: 163.7, detail: 4.9 }, // stripes
  ];
  assert.equal(pickBrightest(film), 2);
  assert.ok(POSTER_MIN_DETAIL > 4.9 && POSTER_MIN_DETAIL < 21.3);
  // a film of flat fields only: the brightest of them, rather than nothing
  assert.equal(pickBrightest([{ mean: 10, detail: 1 }, { mean: 90, detail: 2 }]), 1);
  assert.equal(pickBrightest([null, { mean: 20, detail: 30 }]), 1);
  assert.equal(pickBrightest([]), -1);
});

test('detail is measured between blocks, so a fine texture does not count and a shape does', () => {
  const w = 40;
  const h = 70;
  const img = (fn) => {
    const a = new Uint8ClampedArray(w * h * 4);
    for (let y = 0; y < h; y += 1) for (let x = 0; x < w; x += 1) {
      const v = fn(x, y);
      a.set([v, v, v, 255], (y * w + x) * 4);
    }
    return a;
  };
  const stripes = lumaStats(img((x) => (x % 2 ? 200 : 120)), w, h);
  assert.ok(Math.abs(stripes.mean - 160) < 0.5);
  assert.ok(stripes.detail < 1, `stripes: ${stripes.detail}`);
  const shape = lumaStats(img((x, y) => (x > 10 && x < 30 && y > 20 && y < 50 ? 230 : 20)), w, h);
  assert.ok(shape.detail > POSTER_MIN_DETAIL, `a bright shape on black: ${shape.detail}`);
  assert.ok(Number.isNaN(lumaStats(new Uint8ClampedArray(0), 0, 0).mean));
});
