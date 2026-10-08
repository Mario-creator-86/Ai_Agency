// W23: a stranger's FIRST visit stopped for about one second (909-983 ms, one frame) 130 ms after
// the key, in the middle of the entry. Profiled: the Pixel Streaming library's Config asks
// RTCRtpReceiver.getCapabilities('video'), and the browser's first answer in a fresh process
// enumerates its codecs synchronously (977 ms self time in getSupportedVideoCodecs). Later answers
// are immediate. The page now asks once itself while the title stands idle, when the stream is
// configured, so the entry does not pay it.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { warmVideoCodecs } from '../src/hq_stream_config.js';

const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');

test('warmVideoCodecs asks the browser for its video codecs once, and never throws', () => {
  const asked = [];
  assert.equal(warmVideoCodecs({ RTCRtpReceiver: { getCapabilities: (kind) => { asked.push(kind); return { codecs: [] }; } } }), true);
  assert.deepEqual(asked, ['video']);
  assert.equal(warmVideoCodecs({}), false, 'no WebRTC: nothing to warm');
  assert.equal(warmVideoCodecs(null), false);
  assert.equal(warmVideoCodecs({ RTCRtpReceiver: {} }), false);
  assert.equal(warmVideoCodecs({ RTCRtpReceiver: { getCapabilities: () => { throw new Error('x'); } } }), false);
});

test('the pixel page requires no video codec warmup', () => { assert.doesNotMatch(MAIN, /warmVideoCodecs\(|warmStreamCodecs\(/); });
