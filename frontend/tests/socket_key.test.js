// THE KEY OUT OF THE URL (2026-09-25): the Owner's key travelled in both sockets' query strings
// (the stream's signalling and the events), printed by the browser when a socket failed and kept
// by proxy and server logs. A backend that says `auth: 'first_message'` now takes it as each
// socket's first message. SEC-02 (2026-10-01): no URL carries it any more, for any backend; a
// backend that does not say 'first_message' gets no live stream (hq_stream.test.js).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { createRequire } from 'node:module';
import {
  PLATE_NOTES,
  RELAY_READY,
  STREAM_SILENT_FAILURES,
  STREAM_SILENT_MS,
  authMessage,
  authenticateTransport,
  eventsUrl,
  isRelayReady,
  plateNote,
  relayUrl,
  socketAuth,
  streamSilent,
} from '../src/hq_stream_config.js';
import { EventsLink, REPLAY_PAGE } from '../src/live_claims.js';
import { LiveStream } from '../src/hq_stream.js';

const KEY = 'k3y-of-the-owner-0123456789-abcdefghijklmnopqrstuv';
const HOME = { protocol: 'http:', host: '127.0.0.1:8000' };
const RELAY = '/api/v1/office/stream/signalling';

test('the page takes first-message auth only when the backend says it can', () => {
  assert.equal(socketAuth({ available: true, relay: RELAY, auth: 'first_message' }), 'first_message');
  // a backend that does not say it: the page opens no stream (it never puts the key in a URL)
  assert.equal(socketAuth({ available: true, relay: RELAY }), 'query');
  for (const route of [null, undefined, 'first_message', {}, { auth: 'header' }, { auth: true }]) {
    assert.equal(socketAuth(route), 'query', JSON.stringify(route));
  }
});

test('with first-message auth neither socket carries the key in its URL', () => {
  const relay = relayUrl(HOME, RELAY, KEY, 'first_message');
  const events = eventsUrl(HOME, KEY, 'first_message');
  assert.equal(relay, 'ws://127.0.0.1:8000/api/v1/office/stream/signalling');
  assert.equal(events, 'ws://127.0.0.1:8000/api/v1/ws');
  assert.equal(eventsUrl({ protocol: 'https:', host: 'hq.example' }, KEY, 'first_message'), 'wss://hq.example/api/v1/ws');
  for (const url of [relay, events]) assert.doesNotMatch(url, /token|k3y/);
  // SEC-02: whatever a caller hands it, no URL carries the key
  assert.equal(relayUrl(HOME, RELAY, KEY), `ws://127.0.0.1:8000${RELAY}`);
  assert.equal(eventsUrl(HOME, 'a b'), 'ws://127.0.0.1:8000/api/v1/ws');
  assert.deepEqual(JSON.parse(authMessage(KEY)), { type: 'auth', token: KEY });
});

test('the page builds no socket URL with the key by hand any more', () => {
  const main = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
  assert.doesNotMatch(main, /\?token=/);
  assert.match(main, /firstMessage:/);
  assert.match(main, /authMessage: \(\) => authMessage\(ownerToken\)/);
});

test('only the relay\'s own word counts as ready', () => {
  assert.equal(isRelayReady(JSON.stringify({ type: RELAY_READY })), true);
  for (const data of ['{"type":"config"}', 'relay_ready', '{"type":"relay_ready"', null, 42, JSON.stringify({ type: 'relay_ready', pad: 'x'.repeat(80) })]) {
    assert.equal(isRelayReady(data), false, String(data));
  }
});

/** A browser WebSocket for the library's transport, driven by the test. */
function fakeSockets() {
  const made = [];
  class FakeWebSocket {
    static CLOSED = 3;
    constructor(url, protocols) {
      this.url = url;
      this.protocols = protocols;
      this.readyState = 0;
      this.sent = [];
      made.push(this);
    }
    send(data) { this.sent.push(data); }
    close() { this.readyState = 3; }
  }
  return { FakeWebSocket, made };
}

test("the real Pixel Streaming transport sends the key first and starts only on the relay's ready", (t) => {
  const require = createRequire(new URL('../package.json', import.meta.url));
  const { WebSocketTransport, Logger } = require('@epicgames-ps/lib-pixelstreamingcommon-ue5.8');
  const { FakeWebSocket, made } = fakeSockets();
  const previous = globalThis.WebSocket;
  globalThis.WebSocket = FakeWebSocket;
  const logged = [];
  const info = Logger.Info;
  Logger.Info = (...args) => { logged.push(args.join(' ')); };
  t.after(() => { globalThis.WebSocket = previous; Logger.Info = info; });

  const transport = new WebSocketTransport();
  const opened = [];
  const heard = [];
  const closed = [];
  transport.addListener('open', () => opened.push(true));
  transport.addListener('close', () => closed.push(true));
  transport.onMessage = (data) => heard.push(data);
  assert.equal(authenticateTransport(transport, () => authMessage(KEY)), true);

  transport.connect(relayUrl(HOME, RELAY, KEY, 'first_message'));
  const ws = made[0];
  assert.doesNotMatch(ws.url, /token|k3y/);
  assert.ok(logged.every((line) => !line.includes(KEY)), 'the URL the library prints carries no key');
  ws.readyState = 1;
  ws.onopen({});
  assert.deepEqual(ws.sent.map((m) => JSON.parse(m)), [{ type: 'auth', token: KEY }]);
  assert.equal(opened.length, 0, 'the library is not told the socket is open before the relay is ready');
  ws.onmessage({ data: '{"type":"config"}' });
  assert.deepEqual(heard, [], 'nothing before «relay_ready» reaches the library');
  ws.onmessage({ data: JSON.stringify({ type: RELAY_READY }) });
  assert.equal(opened.length, 1);
  assert.deepEqual(heard, [], '«relay_ready» itself is the page\'s, not the library\'s');
  ws.onmessage({ data: '{"type":"config"}' });
  assert.deepEqual(heard, ['{"type":"config"}']);

  // a reconnect sends the key again, and waits again
  transport.connect(relayUrl(HOME, RELAY, KEY, 'first_message'));
  const again = made[1];
  again.readyState = 1;
  again.onopen({});
  assert.deepEqual(again.sent.map((m) => JSON.parse(m).type), ['auth']);
  assert.equal(opened.length, 1);
  // the relay refuses (a wrong key, or no signalling): to the library, a socket that never opened
  again.onclose({ code: 1008, reason: '' });
  assert.equal(closed.length, 1);
  assert.equal(opened.length, 1);
});

test('the pinned library still opens its socket through the handlers first-message auth takes', () => {
  const src = fs.readFileSync(new URL('../node_modules/@epicgames-ps/lib-pixelstreamingcommon-ue5.8/dist/esm/Transport/WebSocketTransport.js', import.meta.url), 'utf8');
  assert.match(src, /onopen = \(_\) => this\.handleOnOpen\(\)/);
  assert.match(src, /onmessage = \(event\) => this\.handleOnMessage\(event\)/);
  const controller = fs.readFileSync(new URL('../node_modules/@epicgames-ps/lib-pixelstreamingfrontend-ue5.8/dist/esm/WebRtcPlayer/WebRtcPlayerController.js', import.meta.url), 'utf8');
  assert.match(controller, /this\.transport = new WebSocketTransport/);
});

test('a transport that is not the library\'s is left alone', () => {
  assert.equal(authenticateTransport(null, () => ''), false);
  const odd = { sendMessage() {} };
  assert.equal(authenticateTransport(odd, () => ''), false);
  assert.deepEqual(Object.keys(odd), ['sendMessage']);
});

function eventsHarness(t, firstMessage) {
  const sockets = [];
  const states = [];
  const events = [];
  const link = new EventsLink({
    url: () => eventsUrl(HOME, KEY, firstMessage ? 'first_message' : 'query'),
    firstMessage: () => (firstMessage ? authMessage(KEY) : null),
    open: (url) => {
      const socket = { url, sent: [], send(text) { this.sent.push(JSON.parse(text)); }, close() {} };
      sockets.push(socket);
      return socket;
    },
    afterSequence: () => 40,
    onEvent: (e) => events.push(e),
    onState: (s) => states.push(s),
    timers: { setTimeout, clearTimeout, setInterval, clearInterval },
    now: () => Date.now(),
  });
  t.after(() => link.stop());
  return { link, sockets, states, events };
}

test('the events socket sends the key first and is open only when the backend answers auth_ok', (t) => {
  const h = eventsHarness(t, true);
  h.link.start();
  const socket = h.sockets[0];
  assert.doesNotMatch(socket.url, /token|k3y/);
  socket.onopen();
  assert.deepEqual(socket.sent, [{ type: 'auth', token: KEY }]);
  assert.deepEqual(h.states, ['connecting'], 'not open, so nothing on the page says live');
  // nothing is taken from a socket not yet authenticated
  socket.onmessage({ data: JSON.stringify({ type: 'event', data: { sequence: 41 } }) });
  assert.deepEqual(h.events, []);
  socket.onmessage({ data: JSON.stringify({ type: 'auth_ok' }) });
  assert.deepEqual(h.states, ['connecting', 'open']);
  assert.deepEqual(socket.sent.slice(1), [{ type: 'replay', after_sequence: 40, limit: REPLAY_PAGE }]);
  socket.onmessage({ data: JSON.stringify({ type: 'event', data: { sequence: 42 } }) });
  assert.deepEqual(h.events, [{ sequence: 42 }]);
});

test('a refusal before auth_ok is final, as a refused key always was', (t) => {
  const h = eventsHarness(t, true);
  h.link.start();
  h.sockets[0].onopen();
  h.sockets[0].onclose({ code: 1008 });
  assert.equal(h.states.at(-1), 'refused');
});

test('a link given no first message: still no key in the URL, and the replay is the first message', (t) => {
  const h = eventsHarness(t, false);
  h.link.start();
  assert.doesNotMatch(h.sockets[0].url, /token|k3y/);
  h.sockets[0].onopen();
  assert.deepEqual(h.states, ['connecting', 'open']);
  assert.deepEqual(h.sockets[0].sent, [{ type: 'replay', after_sequence: 40, limit: REPLAY_PAGE }]);
});

/* ----------------------------------------------------------------------------------------------
 * A DEAD STREAM IS SAID
 * -------------------------------------------------------------------------------------------- */

test('after a few failed connects, or a set time, the plate says the headquarters does not answer', () => {
  assert.equal(streamSilent(0, false), false);
  assert.equal(streamSilent(STREAM_SILENT_FAILURES - 1, false), false);
  assert.equal(streamSilent(STREAM_SILENT_FAILURES, false), true);
  assert.equal(streamSilent(0, true), true);
  assert.ok(STREAM_SILENT_MS >= 10000 && STREAM_SILENT_MS <= 60000, 'longer than any start measured (3.4 s), short enough to be honest');
  assert.equal(plateNote('starting', false), 'Pornește sediul live…');
  assert.equal(plateNote('starting', true), 'Sediul live nu răspunde · se încearcă din nou…');
  assert.equal(plateNote('reconnecting', false), 'Se reconectează la sediul live…');
  assert.equal(plateNote('reconnecting', true), PLATE_NOTES.silent);
  assert.equal(plateNote('kept', false, 'ultimul cadru live · azi 22:48'), 'ultimul cadru live · azi 22:48 · pornește sediul live…');
  assert.equal(plateNote('kept', true, 'ultimul cadru live · azi 22:48'), 'ultimul cadru live · azi 22:48 · sediul live nu răspunde');
  assert.equal(plateNote('', true), '');
});

function player(t) {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  const previous = globalThis.window;
  globalThis.window = {
    setTimeout: (...args) => setTimeout(...args),
    clearTimeout: (id) => clearTimeout(id),
    setInterval: (...args) => setInterval(...args),
    clearInterval: (id) => clearInterval(id),
  };
  t.after(() => { globalThis.window = previous; });
  const p = Object.create(LiveStream.prototype);
  const classes = new Set();
  Object.assign(p, {
    status: 'offline', settings: { retryMs: 15000 }, retryTimer: 0, stillTimer: 0,
    hasStill: false, still: {}, badge: {}, onStatus() {}, onFrameRate() {},
    layer: { classList: { toggle(c, on) { if (on) classes.add(c); else classes.delete(c); } } },
    stream: { reconnect() {} },
    _copyFrame() { return false; },
  });
  return { p, classes };
}

test('three connects that end before a picture: the dark plate says the headquarters does not answer', (t) => {
  const { p, classes } = player(t);
  p._setStatus('connecting');
  assert.equal(p.badge.textContent, 'Pornește sediul live…');
  p._offline();
  p._offline();
  assert.equal(p.badge.textContent, 'Pornește sediul live…');
  p._offline();
  assert.equal(p.badge.textContent, 'Sediul live nu răspunde · se încearcă din nou…');
  assert.ok(classes.has('silent'));
  // it answers: the count starts again
  p._setStatus('live');
  assert.equal(p.failures, 0);
  assert.ok(!classes.has('silent'));
});

test('no picture for the set time: silent, even with no failed connect', (t) => {
  const { p } = player(t);
  p._setStatus('connecting');
  t.mock.timers.tick(STREAM_SILENT_MS - 1);
  assert.equal(p.badge.textContent, 'Pornește sediul live…');
  t.mock.timers.tick(1);
  assert.equal(p.badge.textContent, 'Sediul live nu răspunde · se încearcă din nou…');
});

test('a drop from live is not a failed connect, and the kept frame says the silence in its own line', (t) => {
  const { p } = player(t);
  p._setStatus('live');
  p._offline();
  assert.equal(p.failures, 0);
  p.keptShown = true;
  p.keptCaption = 'ultimul cadru live · ieri 23:07';
  p.hasStill = false;
  p._setStatus('connecting');
  p._offline(); p._offline(); p._offline();
  assert.equal(p.badge.textContent, 'ultimul cadru live · ieri 23:07 · sediul live nu răspunde');
});
