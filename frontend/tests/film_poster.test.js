import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { keyFrame, locateMoov } from '../src/film_poster.js';

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
