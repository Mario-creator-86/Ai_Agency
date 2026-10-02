import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { STREAM_NO_SAFE_AUTH, eventsUrl, liveStreamSettings, relayUrl, streamLayers } from '../src/hq_stream_config.js';

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
  assert.equal(relayUrl({ protocol: 'http:', host: '127.0.0.1:8000' }, path), 'ws://127.0.0.1:8000/api/v1/office/stream/signalling');
  assert.equal(relayUrl({ protocol: 'https:', host: 'hq.example' }, 'api/x'), 'wss://hq.example/api/x');
});

// SEC-02 (2026-10-01): uvicorn logs a socket's path with its query and the service kept that log
// on disk, so the backend refuses a key in a socket's URL outright. No URL the page builds carries
// one, whatever it is handed, and the stream never falls back to one.
test('no socket URL the page builds ever carries the key', () => {
  const home = { protocol: 'http:', host: '127.0.0.1:8000' };
  const urls = [
    relayUrl(home, '/api/v1/office/stream/signalling'),
    // a caller from before still passing the key and the old mode gets no key in the URL
    /** @type {any} */ (relayUrl)(home, '/api/v1/office/stream/signalling', 'k3y', 'query'),
    eventsUrl(home),
    /** @type {any} */ (eventsUrl)(home, 'k3y', 'query'),
  ];
  for (const url of urls) {
    assert.doesNotMatch(url, /token=/i, url);
    assert.doesNotMatch(url, /k3y/, url);
  }
});

test('the stream has no URL with the key to fall back to, and says so when it cannot use the first message', () => {
  const stream = fs.readFileSync(new URL('../src/hq_stream.js', import.meta.url), 'utf8');
  const main = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
  for (const src of [stream, main]) {
    assert.doesNotMatch(src, /legacyUrl/);
    assert.doesNotMatch(src, /'query'\)/);
  }
  assert.match(main, /STREAM_NO_SAFE_AUTH/);
  assert.match(stream, /firstMessageAuth/);
  assert.equal(typeof STREAM_NO_SAFE_AUTH, 'string');
  assert.match(STREAM_NO_SAFE_AUTH, /cheia/);
});

test('W17: the streamed video never takes the pointer from the page\'s hit boxes (the library writes pointer-events: all on it)', () => {
  const css = fs.readFileSync(new URL('../src/office_scene.css', import.meta.url), 'utf8');
  const lib = fs.readFileSync(new URL('../node_modules/@epicgames-ps/lib-pixelstreamingfrontend-ue5.8/dist/esm/VideoPlayer/VideoPlayer.js', import.meta.url), 'utf8');
  assert.match(lib, /pointerEvents\s*=\s*'all'/, 'the library still sets it inline (else this rule can go)');
  const rule = css.match(/\.live-stream-layer video \{[^}]*\}/);
  assert.ok(rule);
  assert.match(rule[0], /pointer-events:\s*none\s*!important/, 'an inline style is only beaten by !important');
});

// PAGE-20: the Pixel Streaming client is downloaded only by a studio whose stream is switched on.
test('the stream client is never a static import: it is loaded by import() when the stream starts', () => {
  const stream = fs.readFileSync(new URL('../src/hq_stream.js', import.meta.url), 'utf8');
  const main = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
  const statics = (src) => src.split('\n').filter((line) => /^\s*import\s[^(]/.test(line));
  for (const [name, src] of [['hq_stream.js', stream], ['main.js', main]]) {
    assert.ok(!statics(src).some((line) => line.includes('@epicgames-ps/lib-pixelstreamingfrontend-ue5.8')), name);
  }
  assert.ok(!statics(main).some((line) => line.includes("'./hq_stream.js'")), 'main.js imports the stream module only when it starts it');
  assert.match(stream, /import\('@epicgames-ps\/lib-pixelstreamingfrontend-ue5\.8'\)/);
  assert.match(main, /await import\('\.\/hq_stream\.js'\)/);
  // the redacting logger is still installed with the library, before the first connect
  assert.match(stream, /overrideLogger\(redactingLogger\(Logger\)\);/);
});

test('a LiveStream made before the client is loaded says so instead of failing inside the library', async () => {
  const { LiveStream, streamClientLoaded } = await import('../src/hq_stream.js');
  assert.equal(streamClientLoaded(), false);
  assert.throws(() => new LiveStream(/** @type {any} */ ({ appendChild() {} }), { signallingUrl: '', streamerId: '', retryMs: 15000 }), /loadStreamClient/);
});
