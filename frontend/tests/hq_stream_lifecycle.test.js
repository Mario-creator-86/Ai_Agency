import test from 'node:test';
import assert from 'node:assert/strict';
import { LiveStream } from '../src/hq_stream.js';

function fixture(t) {
  t.mock.timers.enable({ apis: ['setTimeout', 'setInterval'] });
  const previous = globalThis.window;
  globalThis.window = {
    setTimeout: (...args) => setTimeout(...args),
    clearTimeout: (id) => clearTimeout(id),
    setInterval: (...args) => setInterval(...args),
    clearInterval: (id) => clearInterval(id),
  };
  t.after(() => { globalThis.window = previous; });
  const player = Object.create(LiveStream.prototype);
  let reconnects = 0;
  let snapshots = 0;
  Object.assign(player, {
    status: 'offline', settings: { retryMs: 15000 }, retryTimer: 0, stillTimer: 0,
    hasStill: false, still: {}, badge: {}, onStatus() {},
    layer: { classList: { toggle() {} } },
    stream: { reconnect() { reconnects++; } },
    _copyFrame() { snapshots++; this.hasStill = true; },
  });
  return { player, reconnects: () => reconnects, snapshots: () => snapshots };
}

test('a recovered live stream is not torn down by an old retry timer', (t) => {
  const f = fixture(t);
  f.player._offline();
  t.mock.timers.tick(3000); // the SDK reconnects before our fallback timer
  f.player._setStatus('connecting');
  f.player._setStatus('live');
  t.mock.timers.tick(30000);
  assert.equal(f.reconnects(), 0);
  assert.equal(f.player.status, 'live');
});

test('ongoing negotiation is not restarted by the previous offline deadline', (t) => {
  const f = fixture(t);
  f.player._offline();
  t.mock.timers.tick(3000);
  f.player._setStatus('connecting');
  t.mock.timers.tick(15000);
  assert.equal(f.reconnects(), 0);
});

test('a genuine repeated outage still has exactly one fallback retry', (t) => {
  const f = fixture(t);
  f.player._offline();
  f.player._offline();
  t.mock.timers.tick(15000);
  assert.equal(f.reconnects(), 1);
});

test('a short live interval keeps a frame instead of flashing the empty viewport', (t) => {
  const f = fixture(t);
  f.player._setStatus('live');
  assert.equal(f.snapshots(), 1);
  t.mock.timers.tick(1000);
  f.player._offline();
  assert.equal(f.player.still.hidden, false);
  assert.equal(f.player.badge.textContent, 'Reconnecting to the live headquarters…');
});
