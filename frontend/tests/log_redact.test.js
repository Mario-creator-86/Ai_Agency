// W23: the Pixel Streaming library prints the signalling URL on every connect (WebSocketTransport:
// Logger.Info(connectionURL)). Against the Owner's running backend, which still takes the key in
// the URL until he restarts it, that line carried his key into the console: once per connect, and
// twelve times in 26 s while the signalling was down. The page now gives the library a logger that
// blanks any `token=` value before a line reaches the console.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import { redactKey, redactingLogger, relayUrl } from '../src/hq_stream_config.js';

const KEY = 'k3y-'.padEnd(48, 'q');
const HOME = { protocol: 'http:', host: '127.0.0.1:8000' };
const RELAY = '/api/v1/office/stream/signalling';

test('redactKey blanks the value of every token= in a line, and only that', () => {
  assert.equal(redactKey(`ws://h/api/v1/ws?token=${KEY}`), 'ws://h/api/v1/ws?token=…');
  assert.equal(redactKey(`ws://h/x?a=1&token=${encodeURIComponent('a b&c')}&b=2`), 'ws://h/x?a=1&token=…&b=2');
  assert.equal(redactKey(`WebSocket connection to 'ws://h/s?TOKEN=${KEY}' failed`), "WebSocket connection to 'ws://h/s?TOKEN=…' failed");
  assert.equal(redactKey('Connected to the signalling server via WebSocket'), 'Connected to the signalling server via WebSocket');
  assert.equal(redactKey('ws://h/api/v1/office/stream/signalling'), 'ws://h/api/v1/office/stream/signalling');
  assert.equal(redactKey(undefined), 'undefined');
});

test('the library, given the page\'s logger, never prints the key of a URL (the old backend\'s path)', (t) => {
  const require = createRequire(new URL('../package.json', import.meta.url));
  const lib = require('@epicgames-ps/lib-pixelstreamingcommon-ue5.8');
  const original = lib.Logger;
  const lines = [];
  const saved = { log: console.log, warn: console.warn, error: console.error };
  for (const k of Object.keys(saved)) console[k] = (...a) => lines.push(a.join(' '));
  class FakeWebSocket { static CLOSED = 3; constructor(url) { this.url = url; this.readyState = 0; } send() {} close() {} }
  const previous = globalThis.WebSocket;
  globalThis.WebSocket = FakeWebSocket;
  t.after(() => { Object.assign(console, saved); globalThis.WebSocket = previous; lib.overrideLogger(original); });

  lib.overrideLogger(redactingLogger(lib.Logger));
  assert.equal(redactingLogger(lib.Logger), lib.Logger, 'wrapping twice is wrapping once');
  const transport = new lib.WebSocketTransport();
  transport.connect(relayUrl(HOME, RELAY, KEY, 'query'));
  lib.Logger.Error(`Failed to construct 'WebSocket': The URL '${relayUrl(HOME, RELAY, KEY, 'query')}' is invalid.`);
  assert.ok(lines.some((l) => l.includes('/api/v1/office/stream/signalling?token=…')), 'the URL is still said, without its key');
  assert.ok(lines.every((l) => !l.includes(KEY)), 'no line carries the key');
});

test('the page installs the redacting logger with the library it streams through', () => {
  const src = fs.readFileSync(new URL('../src/hq_stream.js', import.meta.url), 'utf8');
  assert.match(src, /overrideLogger\(redactingLogger\(Logger\)\);/);
});
