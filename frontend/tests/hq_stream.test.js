import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { liveStreamSettings, relayUrl, streamLayers } from '../src/hq_stream_config.js';

const SCENE = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/scene.json', import.meta.url), 'utf8'));

test('the shipped scene shows the Unreal headquarters whenever the backend has a stream configured', () => {
  const s = liveStreamSettings(SCENE);
  assert.equal(s.enabled, true);
  assert.ok(s.retryMs >= 1000);
});

test('no scene, no block or not switched on: the page keeps its own renderer', () => {
  for (const scene of [null, {}, { live_stream: null }, { live_stream: { enabled: false } }, { live_stream: { enabled: 'yes' } }]) {
    assert.equal(liveStreamSettings(scene).enabled, false, JSON.stringify(scene));
  }
});

test('a retry faster than a second falls back to the default pause', () => {
  const s = liveStreamSettings({ live_stream: { enabled: true, retry_ms: 10 } });
  assert.equal(s.retryMs, 15000);
  assert.equal(s.streamerId, '');
});

test('with a stream configured the old renderer is never shown: live video, a frozen frame or a note', () => {
  const live = { still: false, waiting: false, note: '', held: false, kept: false };
  assert.deepEqual(streamLayers('live', false), live);
  assert.deepEqual(streamLayers('live', true), live);
  for (const status of ['offline', 'connecting']) {
    assert.deepEqual(streamLayers(status, true), { still: true, waiting: false, note: 'reconnecting', held: false, kept: false }, status);
    // before any frame (Unreal starting or being rebuilt) a dark viewport says so
    assert.deepEqual(streamLayers(status, false), { still: false, waiting: true, note: 'starting', held: false, kept: false }, status);
  }
});

test("the relay is on the page's own origin, secure when the page is", () => {
  const path = '/api/v1/office/stream/signalling';
  assert.equal(relayUrl({ protocol: 'http:', host: '127.0.0.1:8000' }, path, 'a b'), 'ws://127.0.0.1:8000/api/v1/office/stream/signalling?token=a%20b');
  assert.equal(relayUrl({ protocol: 'https:', host: 'hq.example' }, 'api/x', 't'), 'wss://hq.example/api/x?token=t');
});

test('W17: the streamed video never takes the pointer from the page\'s hit boxes (the library writes pointer-events: all on it)', () => {
  const css = fs.readFileSync(new URL('../src/office_scene.css', import.meta.url), 'utf8');
  const lib = fs.readFileSync(new URL('../node_modules/@epicgames-ps/lib-pixelstreamingfrontend-ue5.8/dist/esm/VideoPlayer/VideoPlayer.js', import.meta.url), 'utf8');
  assert.match(lib, /pointerEvents\s*=\s*'all'/, 'the library still sets it inline (else this rule can go)');
  const rule = css.match(/\.live-stream-layer video \{[^}]*\}/);
  assert.ok(rule);
  assert.match(rule[0], /pointer-events:\s*none\s*!important/, 'an inline style is only beaten by !important');
});
