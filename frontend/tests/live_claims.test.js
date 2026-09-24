import test from 'node:test';
import assert from 'node:assert/strict';
import {
  EventsLink,
  REPLAY_PAGE,
  SOCKET_PING_MS,
  SOCKET_REFUSED,
  SOCKET_SILENT_MS,
  connectionLabel,
  roomCaption,
  roomCaptionShort,
  sceneReadout,
  socketRetryMs,
} from '../src/live_claims.js';
import { inboundFrameRate } from '../src/hq_stream.js';
import { productionStatus, quietFor, RUN_QUIET_MS } from '../src/ledger.js';

const base = { stream: 'off', hasStill: false, socket: 'open', data: 'fresh', streamFps: null, pageFps: null };
const words = (readout) => readout.parts.map(([, text]) => text).join('');

test('while the Unreal stream plays, the readout is live and its figure is Unreal\'s', () => {
  const r = sceneReadout({ ...base, stream: 'live', streamFps: 59.6, pageFps: 144 });
  assert.equal(r.live, true);
  assert.equal(r.state, 'live');
  assert.equal(words(r), 'Live · Unreal 60fps');
  assert.doesNotMatch(words(r), /144/);
  // no statistics yet: no number rather than someone else's
  assert.equal(words(sceneReadout({ ...base, stream: 'live', pageFps: 144 })), 'Live · Unreal');
});

test('over a frozen frame the readout says it is reconnecting, never live', () => {
  for (const stream of ['offline', 'connecting']) {
    const r = sceneReadout({ ...base, stream, hasStill: true, pageFps: 144 });
    assert.equal(r.live, false, stream);
    assert.equal(r.state, 'frozen');
    assert.equal(words(r), 'Se reconectează · cadru înghețat');
    assert.doesNotMatch(words(r), /Live|fps/);
  }
});

test('before any frame the viewport plate speaks and the corner is hidden', () => {
  const r = sceneReadout({ ...base, stream: 'connecting', hasStill: false, pageFps: 144 });
  assert.equal(r.hidden, true);
  assert.equal(r.live, false);
  assert.deepEqual(r.parts, []);
});

test("with no stream the page's renderer is named as what the figure measures", () => {
  for (const stream of ['off', 'pending']) {
    const r = sceneReadout({ ...base, stream, pageFps: 143.7 });
    assert.equal(r.live, true);
    assert.equal(words(r), 'Live · randarea paginii 144fps');
    assert.match(r.title, /nu de Unreal/);
  }
});

test('with no stream the page is live only while the events reach it', () => {
  assert.equal(words(sceneReadout({ ...base, socket: 'connecting', pageFps: 60 })), 'Se conectează');
  const again = sceneReadout({ ...base, socket: 'reconnecting', pageFps: 60 });
  assert.equal(again.live, false);
  assert.equal(again.state, 'reconnecting');
  assert.equal(words(again), 'Se reconectează');
  assert.equal(words(sceneReadout({ ...base, socket: 'refused' })), 'Deconectat');
  assert.equal(sceneReadout({ ...base, socket: 'refused' }).live, false);
});

test('a failed read of the studio outranks everything: the data is not current', () => {
  for (const stream of ['live', 'off', 'offline']) {
    const r = sceneReadout({ ...base, stream, data: 'stale', streamFps: 60, pageFps: 60 });
    assert.equal(r.live, false);
    assert.equal(words(r), 'Date neactualizate');
  }
});

test('the masthead chip follows the socket and the snapshot', () => {
  assert.equal(connectionLabel({ data: 'fresh', socket: 'open' }), 'Conectat · Proprietar');
  assert.equal(connectionLabel({ data: 'fresh', socket: 'connecting' }), 'Se conectează…');
  assert.equal(connectionLabel({ data: 'fresh', socket: 'reconnecting' }), 'Se reconectează…');
  assert.equal(connectionLabel({ data: 'fresh', socket: 'refused' }), 'Deconectat');
  assert.equal(connectionLabel({ data: 'stale', socket: 'open' }), 'Deconectat');
});

test('the slate says live only while it is, and keeps its Romanian counting', () => {
  assert.equal(roomCaption(8, true), '8 angajați la birourile lor · sediul AMN-AI, live');
  assert.equal(roomCaption(8, false), '8 angajați la birourile lor · sediul AMN-AI');
  assert.equal(roomCaption(1, true), '1 angajat la birourile lor · sediul AMN-AI, live');
  assert.equal(roomCaption(20, false), '20 de angajați la birourile lor · sediul AMN-AI');
  assert.equal(roomCaption(0, true), 'Sediul AMN-AI, live');
  assert.equal(roomCaption(0, false), 'Sediul AMN-AI');
});

test('the retry pause doubles from a second and stops at half a minute', () => {
  assert.deepEqual([0, 1, 2, 3, 4, 5, 6, 50].map(socketRetryMs), [1000, 2000, 4000, 8000, 16000, 30000, 30000, 30000]);
  assert.equal(socketRetryMs(-3), 1000);
});

test("Unreal's frame rate is read from Pixel Streaming's inbound video statistics", () => {
  assert.equal(inboundFrameRate({ inboundVideoStats: { framesPerSecond: 58 } }), 58);
  assert.equal(inboundFrameRate({ inboundVideoStats: {} }), null);
  assert.equal(inboundFrameRate(undefined), null);
  assert.equal(inboundFrameRate({ inboundVideoStats: { framesPerSecond: Number.NaN } }), null);
});

/* ------------------------------------------------------------ the link -- */

function harness(t, { cursor = 40 } = {}) {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval', 'Date'] });
  const sockets = [];
  const states = [];
  const events = [];
  let reconnected = 0;
  let seq = cursor;
  const link = new EventsLink({
    url: () => 'ws://studio/api/v1/ws?token=k',
    open: (url) => {
      const socket = {
        url,
        sent: [],
        closed: false,
        send(text) { this.sent.push(JSON.parse(text)); },
        close() { this.closed = true; },
      };
      sockets.push(socket);
      return socket;
    },
    afterSequence: () => seq,
    onEvent: (e) => { events.push(e); seq = Math.max(seq, e.sequence); },
    onState: (s) => states.push(s),
    onReconnected: () => { reconnected += 1; },
    timers: { setTimeout, clearTimeout, setInterval, clearInterval },
    now: () => Date.now(),
  });
  t.after(() => link.stop());
  return { link, sockets, states, events, reconnected: () => reconnected };
}

test('the link connects, asks for what it has not seen, and says it is open', (t) => {
  const h = harness(t);
  h.link.start();
  assert.deepEqual(h.states, ['connecting']);
  h.sockets[0].onopen();
  assert.deepEqual(h.states, ['connecting', 'open']);
  assert.deepEqual(h.sockets[0].sent, [{ type: 'replay', after_sequence: 40, limit: REPLAY_PAGE }]);
  h.sockets[0].onmessage({ data: JSON.stringify({ type: 'event', data: { sequence: 41 } }) });
  assert.deepEqual(h.events, [{ sequence: 41 }]);
  assert.equal(h.reconnected(), 0);
});

test('after a drop it says it is reconnecting, retries with a growing pause, and replays the gap', (t) => {
  const h = harness(t);
  h.link.start();
  h.sockets[0].onopen();
  h.sockets[0].onmessage({ data: JSON.stringify({ type: 'event', data: { sequence: 55 } }) });
  h.sockets[0].onclose({ code: 1006 });
  assert.equal(h.states.at(-1), 'reconnecting');
  t.mock.timers.tick(999);
  assert.equal(h.sockets.length, 1);
  t.mock.timers.tick(1);
  assert.equal(h.sockets.length, 2);
  // the backend is still down: the next pause is two seconds
  h.sockets[1].onclose({ code: 1006 });
  t.mock.timers.tick(1999);
  assert.equal(h.sockets.length, 2);
  t.mock.timers.tick(1);
  assert.equal(h.sockets.length, 3);
  h.sockets[2].onopen();
  assert.equal(h.states.at(-1), 'open');
  assert.deepEqual(h.sockets[2].sent[0], { type: 'replay', after_sequence: 55, limit: REPLAY_PAGE });
  assert.equal(h.reconnected(), 1);
  // and the pause starts from a second again after a success
  h.sockets[2].onclose({ code: 1006 });
  t.mock.timers.tick(1000);
  assert.equal(h.sockets.length, 4);
});

test('a full replay page is followed by the next one', (t) => {
  const h = harness(t);
  h.link.start();
  h.sockets[0].onopen();
  h.sockets[0].onmessage({ data: JSON.stringify({ type: 'replay_complete', count: REPLAY_PAGE, up_to_sequence: 540 }) });
  assert.deepEqual(h.sockets[0].sent.at(-1), { type: 'replay', after_sequence: 540, limit: REPLAY_PAGE });
  h.sockets[0].onmessage({ data: JSON.stringify({ type: 'replay_complete', count: 12, up_to_sequence: 552 }) });
  assert.equal(h.sockets[0].sent.length, 2);
});

test('a refused key is final: no retry, and the page says it is disconnected', (t) => {
  const h = harness(t);
  h.link.start();
  h.sockets[0].onclose({ code: SOCKET_REFUSED });
  assert.equal(h.states.at(-1), 'refused');
  t.mock.timers.tick(120000);
  assert.equal(h.sockets.length, 1);
});

test('signing out stops the link: a close after it asks nothing again', (t) => {
  const h = harness(t);
  h.link.start();
  h.sockets[0].onopen();
  const first = h.sockets[0];
  h.link.stop();
  assert.equal(first.closed, true);
  assert.equal(h.states.at(-1), 'closed');
  t.mock.timers.tick(120000);
  assert.equal(h.sockets.length, 1);
});

test('a socket that goes silent is taken for dead and reopened', (t) => {
  const h = harness(t);
  h.link.start();
  h.sockets[0].onopen();
  t.mock.timers.tick(SOCKET_PING_MS);
  assert.deepEqual(h.sockets[0].sent.at(-1), { type: 'ping' });
  h.sockets[0].onmessage({ data: JSON.stringify({ type: 'pong' }) });
  t.mock.timers.tick(SOCKET_SILENT_MS + SOCKET_PING_MS);
  assert.equal(h.sockets[0].closed, true);
  assert.equal(h.states.at(-1), 'reconnecting');
  t.mock.timers.tick(1000);
  assert.equal(h.sockets.length, 2);
});

/* ------------------------------------------------------- the «Acum» pulse -- */

const at = (iso) => Date.parse(iso);

test('«Acum» pulses while a stage runs and the register has spoken in the last hour', () => {
  const events = [
    { event_type: 'agent.run_started', timestamp: '2026-09-24T10:40:00Z', payload: {} },
    { event_type: 'runbook.stage_started', timestamp: '2026-09-24T10:30:00Z', payload: { stage: 'media' } },
  ];
  const status = productionStatus(events, at('2026-09-24T11:00:00Z'));
  assert.equal(status.live, true);
  assert.equal(status.text, 'Acum: producție media');
});

test('«Acum» goes quiet after an hour without a single event, and says for how long', () => {
  const events = [
    { event_type: 'runbook.stage_started', timestamp: '2026-09-19T13:43:00Z', payload: { stage: 'media' } },
  ];
  const justUnder = productionStatus(events, at('2026-09-19T13:43:00Z') + RUN_QUIET_MS);
  assert.equal(justUnder.live, true);
  const past = productionStatus(events, at('2026-09-19T13:43:00Z') + RUN_QUIET_MS + 1);
  assert.equal(past.live, false);
  assert.equal(past.running, 'media');
  assert.equal(past.text, 'Ultima etapă începută: producție media · nimic nou de o oră');
  const days = productionStatus(events, at('2026-09-24T09:00:00Z'));
  assert.equal(days.text, 'Ultima etapă începută: producție media · nimic nou de 4 zile');
});

test('the end of the day closes a stage that never said it finished', () => {
  const status = productionStatus(
    [
      { event_type: 'runbook.daily_run_finished', timestamp: '2026-09-24T10:00:00Z', payload: { status: 'FAILED' } },
      { event_type: 'runbook.stage_started', timestamp: '2026-09-24T09:59:00Z', payload: { stage: 'media' } },
    ],
    at('2026-09-24T10:01:00Z'),
  );
  assert.equal(status.running, null);
  assert.equal(status.live, false);
  assert.doesNotMatch(status.text, /Acum/);
});

test('nothing running is never live', () => {
  assert.equal(productionStatus([], Date.now()).live, false);
});

test('how long the register has been quiet, in Romanian', () => {
  assert.equal(quietFor(RUN_QUIET_MS), 'de o oră');
  assert.equal(quietFor(5 * 3600000), 'de 5 ore');
  assert.equal(quietFor(20 * 3600000), 'de 20 de ore');
  assert.equal(quietFor(47 * 3600000), 'de 47 de ore');
  assert.equal(quietFor(48 * 3600000), 'de 2 zile');
  assert.equal(quietFor(24 * 86400000), 'de 24 de zile');
  assert.equal(quietFor(101 * 86400000), 'de 101 zile');
});

test('the link tells an event that happened now from one the page asked to replay', (t) => {
  const flags = [];
  const sockets = [];
  const link = new EventsLink({
    url: () => 'ws://studio/api/v1/ws?token=k',
    open: () => { const s = { send() {}, close() {} }; sockets.push(s); return s; },
    afterSequence: () => 0,
    onEvent: (e, live) => flags.push([e.sequence, live]),
    onState: () => {},
    timers: { setTimeout, clearTimeout, setInterval, clearInterval },
  });
  t.after(() => link.stop());
  link.start();
  sockets[0].onopen();
  sockets[0].onmessage({ data: JSON.stringify({ type: 'replay_event', data: { sequence: 1 } }) });
  sockets[0].onmessage({ data: JSON.stringify({ type: 'event', data: { sequence: 2 } }) });
  assert.deepEqual(flags, [[1, false], [2, true]]);
});

test('a slate too narrow for the caption beside the day says only the count and whether it is live', () => {
  assert.equal(roomCaptionShort(8, true), '8 angajați · live');
  assert.equal(roomCaptionShort(8, false), '8 angajați');
  assert.equal(roomCaptionShort(1, true), '1 angajat · live');
  assert.equal(roomCaptionShort(20, false), '20 de angajați');
  assert.equal(roomCaptionShort(0, true), 'Sediul AMN-AI · live');
});
