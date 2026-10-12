import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  FRESH_BACKOFF_MAX_MS, FRESH_EVERY_MS, STALE_READING_MS, focusCandidates, gpuLive, gpuWords, mountGpuSwitch, offAnswer,
  heldOnly, offCommand, offReadWords, offStateOf, placeInDialog, stopClock, stoppedLabel, workerWords,
} from '../src/gpu_switch.js';

const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
const CSS = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');

/** The page's moment in these tests: a live session's reading is judged by its age against it. */
const NOW = Date.now();
/** @param {number} ms */
const iso = (ms) => new Date(ms).toISOString();

const off = {
  configured: true, mock: false, rate_usd_per_hour: '4.00',
  endpoints: [{ purpose: 'image', endpoint_id: 'ep-s', state: 'OFF', workers_max: 0, running: 0, in_progress: 0, in_queue: 0, read_at: iso(NOW - 1000) }],
  sessions: [], last_off: { at: '2026-10-08T20:00:00+00:00', reason: 'STEP_DONE', verified: true },
  words_ro: 'GPU oprit.',
};
/** A session as the backend lists it: its endpoint and when it opened (before the reading). */
const stillsSession = [{ id: 's', purpose: 'image', step: 'stills', storyboard_id: 'f', endpoint_id: 'ep-s', opened_at: iso(NOW - 60000) }];
/** The evening of `off`'s stop, read on UTC: the receipt's clock does not depend on the machine's zone. */
const evening = { now: Date.parse('2026-10-08T21:00:00Z'), timeZone: 'UTC' };
/** @param {Record<string, unknown>} endpoint @param {any[]} [sessions] */
const liveWith = (endpoint, sessions = stillsSession) => ({
  ...off, endpoints: [{ ...off.endpoints[0], state: 'ON', workers_max: 1, ...endpoint }], sessions,
});

test('the switch says off, a worker that bills, a permitted GPU that does not, or unread', () => {
  assert.equal(gpuWords(off, evening).label, 'GPU oprit la 20:00:00 (verificat)');
  assert.equal(gpuWords(off, evening).tone, 'off');
  assert.match(gpuWords(off).detail, /4\.00 USD\/oră/);
  const working = liveWith({ running: 1, in_progress: 1 });
  assert.equal(gpuWords(working).label, 'GPU pornit, worker activ · pas: stills');
  assert.equal(gpuWords(working).tone, 'on');
  // 2026-10-08: «GPU pornit» while no worker ran; RunPod's own counts say it does not bill
  const permitted = liveWith({ running: 0, in_progress: 0, in_queue: 0 });
  assert.equal(gpuWords(permitted).label, 'GPU permis, 0 workeri — nu se plătește · pas: stills');
  assert.equal(gpuWords(permitted).tone, 'armed');
  // a paused endpoint during an open session: no worker allowed, none running
  const paused = { ...off, sessions: [{ ...stillsSession[0], purpose: 'video', step: 'motion' }] };
  assert.equal(gpuWords(paused).label, 'GPU oprit, 0 workeri — nu se plătește · pas: motion');
  // a reading that is missing is «necitită», never a guess
  const unread = liveWith({ state: 'UNKNOWN', workers_max: null, running: null, in_progress: null });
  assert.equal(gpuWords(unread).label, 'GPU: stare necitită · pas: stills');
  assert.equal(gpuWords(unread).tone, 'unknown');
  const unknown = { ...off, endpoints: [{ ...off.endpoints[0], state: 'UNKNOWN', running: null }] };
  assert.equal(gpuWords(unknown).label, 'GPU: stare necitită');
  assert.equal(gpuWords(unknown).tone, 'unknown');
  assert.equal(gpuWords(null).tone, 'unknown');
  // on without any paid step open: still live, still its stop
  assert.equal(gpuWords(liveWith({ running: 2 }, [])).label, 'GPU pornit, 2 workeri activi · pas: niciunul');
});

test('the switch names the film, the scene and the take, and his stop that holds', () => {
  // 2026-10-12, the Owner over «GPU pornit, worker activ · pas: scene_redo»: «Ce lucrează?
  // Pentru ce film, ce cadru?» — the backend's words for the session replace the step's code.
  const redo = [{ ...stillsSession[0], purpose: 'video', step: 'scene_redo',
    words_ro: "«The Particle That Shouldn't Exist»: refacerea — clipul scenei 5" }];
  const working = liveWith({ running: 1, in_progress: 1 }, redo);
  assert.equal(gpuWords(working).label,
    "GPU pornit, worker activ · «The Particle That Shouldn't Exist»: refacerea — clipul scenei 5");
  // His «Oprește GPU acum» holds: the switch says so until he allows the GPU again.
  const held = { ...off, owner_hold: true };
  assert.equal(gpuWords(held).label, 'GPU oprit de tine');
  assert.equal(gpuWords(held).tone, 'off');
});

test('his hold: a separate key allows the GPU again, on his confirmation; the stop key never changes', async () => {
  // 2026-10-12, the Owner: «GPU-ul RunPod este oprit, de unde îl pornesc??? Ar trebui să o pot
  // face din același loc din care îl opresc!» — from the same bar, never from the same click.
  const sinceLongAgo = new Date(evening.now - 60_000).toISOString();
  const held = { ...off, owner_hold: true, owner_hold_since: sinceLongAgo, allow_after_stop_seconds: 20 };
  assert.equal(heldOnly(held), true);
  assert.equal(heldOnly(off), false);
  const live = { ...held, endpoints: [{ ...off.endpoints[0], state: 'ON', workers_max: 1, running: 1 }],
    sessions: [{ id: 's', purpose: 'image', step: 'motion' }] };
  assert.equal(heldOnly(live), false, 'a live round is stopped first, never allowed past');
  assert.equal(heldOnly({ ...held, mock: true }), false);

  const calls = [];
  let status = held;
  const api = async (/** @type {string} */ path, /** @type {any} */ options = {}) => {
    calls.push([path, options.method || 'GET', options.body ? JSON.parse(options.body) : null]);
    if (path.startsWith('/runpod/gpu/allow')) {
      status = off;
      return { command_id: 'a-1', hold: false, words_ro: 'Ai permis din nou GPU-ul.' };
    }
    return status;
  };
  const said = [];
  let answer = false;
  const asked = [];
  const { bar } = fakeWorld();
  const control = mountGpuSwitch(bar, {
    api, notify: (m) => said.push(m), intervalMs: 0, uuid: () => 'a-1', dialogs: false, now: () => evening.now, timeZone: 'UTC',
    confirm: (m) => { asked.push(m); return answer; },
  });
  await control.refresh();
  const [allowKey, label, button] = bar.children;
  assert.equal(label.textContent, 'GPU oprit de tine');
  assert.equal(button.textContent, 'Oprește GPU acum', 'the stop key never changes its words');
  assert.equal(button.disabled, true, 'nothing to stop while held');
  assert.equal(allowKey.hidden, false);
  assert.equal(allowKey.textContent, 'Permite GPU din nou…');
  assert.equal(allowKey.disabled, false);
  assert.ok(allowKey.className.split(' ').includes('gpu-switch-allow'));
  assert.ok(!button.className.split(' ').includes('cam-worded'), 'the key never folds to an icon');
  // he says no: nothing is sent
  await allowKey.listeners.click();
  assert.equal(asked.length, 1);
  assert.equal(calls.filter((c) => c[0] === '/runpod/gpu/allow').length, 0);
  // he confirms: one POST
  answer = true;
  await allowKey.listeners.click();
  const allows = calls.filter((c) => c[0] === '/runpod/gpu/allow');
  assert.equal(allows.length, 1);
  assert.deepEqual(allows[0][2], { schema_version: 1, command_id: 'a-1' });
  assert.equal(calls.filter((c) => c[0] === '/runpod/gpu/off').length, 0);
  assert.deepEqual(said, ['Ai permis din nou GPU-ul.']);
  assert.equal(allowKey.hidden, true);
  assert.equal(button.textContent, 'Oprește GPU acum');
  // the long reading is said whole on hover, where the toolbar ends it in «…»
  assert.ok(label.title.startsWith(label.textContent));
  control.stop();
});

test('a second press right after the stop never lifts the hold (19:48 UTC, 2026-10-12)', async () => {
  // His stop, then a second press on the same spot 7 s later lifted the hold and the refused clip
  // was bought again: the stop key keeps its words, the allow key waits 20 s and asks first.
  let clock = evening.now;
  const calls = [];
  let status = { ...off, endpoints: [{ ...off.endpoints[0], state: 'ON', workers_max: 1, running: 1 }],
    sessions: [{ id: 's', purpose: 'video', step: 'scene_redo' }] };
  const api = async (/** @type {string} */ path, /** @type {any} */ options = {}) => {
    calls.push([path, options.method || 'GET']);
    if (path.startsWith('/runpod/gpu/off')) {
      status = { ...off, owner_hold: true, owner_hold_since: new Date(clock).toISOString(), allow_after_stop_seconds: 20 };
      return { command_id: 'x', verified: true, readings: [], words_ro: 'GPU-ul RunPod este oprit și verificat.' };
    }
    if (path.startsWith('/runpod/gpu/allow')) return { hold: false };
    return status;
  };
  const { bar } = fakeWorld();
  const control = mountGpuSwitch(bar, {
    api, notify: () => {}, intervalMs: 0, uuid: () => 'u-1', dialogs: false, now: () => clock, timeZone: 'UTC',
    confirm: () => true,
  });
  await control.refresh();
  const [allowKey, , button] = bar.children;
  assert.equal(allowKey.hidden, true, 'nothing to allow while a round is live');
  await button.listeners.click();
  assert.equal(button.textContent, 'Oprește GPU acum');
  assert.equal(button.disabled, true);
  // 7 s later: the allow key is there, counting down, and a press sends nothing
  clock += 7000;
  await control.refresh();
  assert.equal(allowKey.hidden, false);
  assert.equal(allowKey.disabled, true);
  assert.equal(allowKey.textContent, 'Permite GPU din nou (13 s)');
  await allowKey.listeners.click();
  // the stop key under his cursor is disabled (the browser sends it no click) and still says stop
  assert.equal(button.disabled, true);
  assert.equal(button.textContent, 'Oprește GPU acum');
  assert.equal(calls.filter((c) => c[0] === '/runpod/gpu/allow').length, 0, 'the stop was undone');
  // after the wait, it can be pressed (and still asks)
  clock += 14000;
  await control.refresh();
  assert.equal(allowKey.disabled, false);
  assert.equal(allowKey.textContent, 'Permite GPU din nou…');
  control.stop();
});

test('the workers are read from RunPod counts: running or a job in progress bills', () => {
  assert.deepEqual(workerWords([{ purpose: 'image', endpoint_id: 'a', state: 'ON', workers_max: 1, running: 0, in_progress: 1 }]),
    { words: 'GPU pornit, worker activ', tone: 'on', active: 1 });
  // one endpoint unread, another known to bill: the bill wins
  assert.equal(workerWords([
    { purpose: 'image', endpoint_id: 'a', state: 'UNKNOWN', running: null },
    { purpose: 'video', endpoint_id: 'b', state: 'ON', workers_max: 1, running: 1 },
  ]).tone, 'on');
  assert.equal(workerWords([]).words, 'GPU oprit, 0 workeri — nu se plătește');
});

// QUEUE (review 2026-10-09): «nu se plătește» was said with a job in the queue, while RunPod
// starts a worker for it and bills from that start; the studio's own OFF needs inQueue == 0.
test('a job in the queue of a permitted GPU is never called unbilled', () => {
  const queued = liveWith({ running: 0, in_progress: 0, in_queue: 1 });
  assert.equal(gpuWords(queued).label, 'GPU permis, o lucrare la coadă — poate porni un worker plătit · pas: stills');
  assert.equal(gpuWords(queued).tone, 'on');
  assert.doesNotMatch(gpuWords(queued).label, /nu se plătește/);
  assert.equal(workerWords([{ purpose: 'image', endpoint_id: 'a', state: 'ON', workers_max: 1, running: 0, in_progress: 0, in_queue: 3 }]).words,
    'GPU permis, 3 lucrări la coadă — poate porni un worker plătit');
  // a queue never read cannot prove that nothing bills
  const unreadQueue = liveWith({ running: 0, in_progress: 0, in_queue: null });
  assert.equal(gpuWords(unreadQueue).label, 'GPU: stare necitită · pas: stills');
  // a paused endpoint (max 0) starts no worker for its queue: nothing bills
  assert.equal(workerWords([{ purpose: 'image', endpoint_id: 'a', state: 'ON', workers_max: 0, running: 0, in_progress: 0, in_queue: 2 }]).words,
    'GPU oprit, 0 workeri — nu se plătește');
  // a worker RunPod is starting bills from its start (when the backend reads `initializing`)
  assert.deepEqual(workerWords([{ purpose: 'image', endpoint_id: 'a', state: 'ON', workers_max: 1, running: 0, in_progress: 0, in_queue: 1, initializing: 1 }]),
    { words: 'GPU pornit, worker activ', tone: 'on', active: 1 });
});

test('a stop that was never read says «necitită», not «neverificată»', () => {
  assert.equal(offReadWords(true), 'verificată');
  assert.equal(offReadWords(false), 'neverificată');
  assert.equal(offReadWords(null), 'necitită');
  assert.equal(offReadWords(undefined), 'necitită');
  // the backend's reading of the stop wins: the guard's later OFF read is a confirmation
  assert.equal(offReadWords(false, 'CONFIRMED'), 'confirmată de paznic');
  assert.equal(offReadWords(null, 'VERIFIED'), 'verificată');
  assert.equal(offReadWords(true, 'UNREAD'), 'necitită');
  const owner = { ...off, last_off: { at: '2026-10-08T20:00:00+00:00', reason: 'OWNER_OFF', verified: null } };
  assert.match(gpuWords(owner).detail, /Ultima oprire de tine: necitită\./);
  assert.doesNotMatch(gpuWords(owner).detail, /neverificată/);
  const failed = { ...off, last_off: { ...owner.last_off, verified: false } };
  assert.match(gpuWords(failed).detail, /Ultima oprire de tine: neverificată\./);
});

// EVERY STOP LEAVES A RECEIPT (WP4, row 5): the stop's time and how it was read were only in a
// hover title, and «neverificată» stayed after the guard's later OFF read proved the stop.
test('the stopped switch says when the last stop was and how it was read, on its face', () => {
  const at = '2026-10-08T20:00:00+00:00';
  /** @param {Record<string, unknown>} last */
  const stopped = (last) => ({ ...off, last_off: { at, reason: 'STEP_DONE', verified: null, ...last } });
  // the backend's own reading of the stop wins over `verified`
  const confirmed = stopped({
    verified: false, off_state: 'CONFIRMED', off_confirmed_at: '2026-10-08T20:01:05+00:00', confirmed_by: 'guard',
    words_ro: 'Oprirea GPU-ului trimisă la 23:00:00 la sfârșitul pasului; paznicul a confirmat că e oprit la 23:01:05 — pas: stills; timp de GPU facturat estimat ~340 s.',
  });
  // dated by the guard's reading, the first moment anyone saw it off, not by the close that
  // could not read it (the guard may have found it on and switched it off itself)
  assert.equal(gpuWords(confirmed, evening).label, 'GPU oprit (confirmat de paznic la 20:01:05)');
  assert.equal(gpuWords(confirmed, evening).tone, 'off');
  // a confirmation without its moment: the close's time, said as confirmed
  assert.equal(gpuWords(stopped({ off_state: 'CONFIRMED', verified: false }), evening).label,
    'GPU oprit la 20:00:00 (confirmat de paznic)');
  // the receipt itself, with the billed seconds, is the detail, never a guess of ours
  assert.match(gpuWords(confirmed, evening).detail, /Ultima oprire: Oprirea GPU-ului trimisă la 23:00:00 .*~340 s\./);
  assert.doesNotMatch(gpuWords(confirmed, evening).detail, /neverificat/);
  assert.equal(gpuWords(stopped({ off_state: 'UNREAD' }), evening).label, 'GPU oprit la 20:00:00 (necitit)');
  assert.equal(gpuWords(stopped({ off_state: 'UNVERIFIED', verified: false }), evening).label, 'GPU oprit la 20:00:00 (neverificat)');
  assert.equal(gpuWords(stopped({ off_state: 'VERIFIED', verified: true }), evening).label, 'GPU oprit la 20:00:00 (verificat)');
  // an older backend, without `off_state`: read from `verified`; a null one is «necitit»
  assert.equal(gpuWords(stopped({ verified: true }), evening).label, 'GPU oprit la 20:00:00 (verificat)');
  assert.equal(gpuWords(stopped({ verified: false }), evening).label, 'GPU oprit la 20:00:00 (neverificat)');
  assert.equal(gpuWords(stopped({}), evening).label, 'GPU oprit la 20:00:00 (necitit)');
  // a state this page does not know falls back to `verified`, never to «verificat»
  assert.equal(offStateOf({ off_state: 'SHARED', verified: null }), 'UNREAD');
  assert.equal(offStateOf({ off_state: 'confirmed', verified: false }), 'CONFIRMED');
  // the detail without the backend's words: who stopped it and how the stop was read
  assert.match(gpuWords(stopped({ reason: 'OWNER_OFF', off_state: 'CONFIRMED', verified: false }), evening).detail,
    /Ultima oprire de tine: confirmată de paznic\./);
  // yesterday's stop carries its day; a moment that cannot be read says no time at all
  assert.equal(gpuWords(off, { now: Date.parse('2026-10-09T08:00:00Z'), timeZone: 'UTC' }).label, 'GPU oprit la 08.10 20:00:00 (verificat)');
  assert.equal(gpuWords(stopped({ at: 'ieri' }), evening).label, 'GPU oprit');
  assert.equal(gpuWords({ ...off, last_off: null }, evening).label, 'GPU oprit');
  assert.equal(stoppedLabel(null, evening), 'GPU oprit');
});

test('the receipt is read on his clock', () => {
  // Bucharest is UTC+3 in October (until the last Sunday): 20:00 UTC is 23:00 on his PC
  assert.equal(stopClock('2026-10-08T20:00:00+00:00', { now: Date.parse('2026-10-08T20:30:00Z'), timeZone: 'Europe/Bucharest' }), '23:00:00');
  // past his midnight it is yesterday's stop, though UTC has the same day
  assert.equal(stopClock('2026-10-08T20:00:00+00:00', { now: Date.parse('2026-10-08T21:30:00Z'), timeZone: 'Europe/Bucharest' }), '08.10 23:00:00');
  // the backend's microseconds read as well
  assert.equal(stopClock('2026-10-08T20:00:07.123456+00:00', evening), '20:00:07');
  assert.equal(stopClock(null, evening), '');
  assert.equal(stopClock('', evening), '');
  // a zone this browser does not know falls back to its own clock rather than to nothing
  assert.match(stopClock('2026-10-08T20:00:00+00:00', { now: evening.now, timeZone: 'Nicăieri/Niciunde' }), /^(\d\d\.\d\d )?\d\d:\d\d:00$/);
});

test('a job RunPod has not started yet says the unbilled model wait', () => {
  const words = 'aștept descărcarea modelului (neplătită)';
  const waiting = { ...liveWith({ running: 0, model_wait_ro: words }), model_wait_ro: words };
  assert.equal(gpuWords(waiting).label, `GPU: ${words} · pas: stills`);
  assert.equal(gpuWords(waiting).tone, 'armed');
  assert.equal(gpuWords({ ...waiting, model_wait_ro: null }).label, 'GPU permis, 0 workeri — nu se plătește · pas: stills');
  // the job waits in the queue while the model downloads: still the unbilled wait
  const queuedWait = { ...waiting, endpoints: [{ ...waiting.endpoints[0], in_queue: 1 }] };
  assert.equal(gpuWords(queuedWait).label, `GPU: ${words} · pas: stills`);
  assert.equal(gpuWords(queuedWait).tone, 'armed');
  // a worker that already bills is said, whatever the wait says
  assert.equal(gpuWords({ ...waiting, endpoints: [{ ...waiting.endpoints[0], running: 1 }] }).tone, 'on');
});

test('live means a session or an endpoint that can bill; a simulation never is', () => {
  assert.equal(gpuLive(off), false);
  assert.equal(gpuLive(liveWith({ running: 0 })), true);
  assert.equal(gpuLive(liveWith({ running: 0 }, [])), true);
  assert.equal(gpuLive({ ...off, sessions: stillsSession }), true);
  assert.equal(gpuLive({ ...liveWith({ running: 1 }), mock: true }), false);
  assert.equal(gpuLive({ ...liveWith({ running: 1 }), configured: false }), false);
  assert.equal(gpuLive(null), false);
});

test('the off command and its answer', () => {
  assert.deepEqual(offCommand('c-1'), { schema_version: 1, command_id: 'c-1' });
  assert.equal(offAnswer({ verified: true, words_ro: 'GPU-ul RunPod este oprit și verificat.' }),
    'GPU-ul RunPod este oprit și verificat.');
  assert.match(offAnswer({ verified: false, readings: [{}] }), /nu a confirmat/);
});

/**
 * A few DOM pieces, enough for the switch and the dialogs it finds: elements with classes,
 * attributes, a parent, listeners and focus; a document whose dialogs open as showModal() does
 * (the focus to the first control); a MutationObserver that reports, a microtask later, the
 * `open` changes and the child changes under what it observes, as the browser's does.
 */
class El {
  /** @param {string} tag @param {any} doc */
  constructor(tag, doc) {
    this.tagName = tag.toUpperCase();
    this.ownerDocument = doc;
    /** @type {El[]} */
    this.children = [];
    /** @type {El|null} */
    this.parentNode = null;
    /** @type {Record<string, string>} */
    this.attrs = {};
    /** @type {Record<string, string>} */
    this.dataset = {};
    /** @type {Record<string, Function>} */
    this.listeners = {};
    this.hidden = false;
    this.disabled = false;
    this.text = '';
    this.title = '';
    this.type = '';
    this.className = '';
    this.modal = true;
  }

  // a text write replaces the node's text child: a child change, as in the browser
  get textContent() { return this.text; }
  set textContent(value) { this.text = String(value); this.ownerDocument.mutated?.(this); }

  get classList() {
    return { contains: (/** @type {string} */ name) => this.className.split(/\s+/).includes(name) };
  }

  /** focusable as the browser's focusing steps see it: an enabled control, nothing hidden above */
  get focusable() {
    if (this.tagName !== 'BUTTON' || this.disabled || !this.isConnected) return false;
    for (let n = /** @type {El|null} */ (this); n; n = n.parentNode) if (n.hidden) return false;
    return true;
  }

  focus() { if (this.focusable) this.ownerDocument.activeElement = this; }

  blur() { if (this.ownerDocument.activeElement === this) this.ownerDocument.activeElement = this.ownerDocument.body; }

  get isConnected() {
    /** @type {El|null} */
    let node = this;
    while (node && node !== this.ownerDocument.body) node = node.parentNode;
    return Boolean(node);
  }

  /** @param {El} node */
  adopt(node) {
    if (node.parentNode) node.parentNode.children = node.parentNode.children.filter((c) => c !== node);
    node.parentNode = this;
    return node;
  }

  /** @param {...El} nodes */
  append(...nodes) { for (const n of nodes) this.children.push(this.adopt(n)); this.ownerDocument.mutated?.(this); }

  /** @param {...El} nodes */
  prepend(...nodes) { this.children.unshift(...nodes.map((n) => this.adopt(n))); this.ownerDocument.mutated?.(this); }

  /** @param {El} node @param {El} before */
  insertBefore(node, before) {
    this.adopt(node);
    this.children.splice(this.children.indexOf(before), 0, node);
    this.ownerDocument.mutated?.(this);
  }

  /** @param {...El} nodes */
  replaceChildren(...nodes) {
    for (const c of this.children) c.parentNode = null;
    this.children = [];
    this.append(...nodes);
  }

  /** @param {string} name @param {string} value */
  setAttribute(name, value) { this.attrs[name] = String(value); }
  /** @param {string} name */
  hasAttribute(name) { return name in this.attrs; }
  /** @param {string} name */
  removeAttribute(name) { delete this.attrs[name]; }
  /** @param {string} type @param {Function} fn */
  addEventListener(type, fn) { this.listeners[type] = fn; }

  /** @param {El} node */
  contains(node) {
    for (let n = /** @type {El|null} */ (node); n; n = n.parentNode) if (n === this) return true;
    return false;
  }

  /** @param {string} selector */
  matches(selector) {
    if (selector === ':modal') return this.modal && this.hasAttribute('open');
    return false;
  }

  /** every node under this one, itself included @returns {El[]} */
  all() { return [this, ...this.children.flatMap((c) => c.all())]; }

  /** @param {string} name */
  find(name) { return this.all().filter((n) => n.classList.contains(name)); }
}

function fakeWorld() {
  /** @type {any} */
  const doc = { createElement: (/** @type {string} */ tag) => new El(tag, doc) };
  doc.body = new El('body', doc);
  doc.activeElement = doc.body;
  doc.querySelectorAll = (/** @type {string} */ selector) => {
    assert.equal(selector, 'dialog[open]');
    return doc.body.all().filter((/** @type {El} */ n) => n.tagName === 'DIALOG' && n.hasAttribute('open'));
  };
  /** @type {any[]} */
  const observers = [];
  class Observer {
    /** @param {Function} callback */
    constructor(callback) {
      this.callback = callback;
      this.options = null;
      /** @type {[El, any][]} */
      this.targets = [];
      /** @type {any[]} */
      this.queue = [];
      this.calls = 0;
      observers.push(this);
    }
    /** @param {any} target @param {any} options */
    observe(target, options) { if (!this.options) this.options = options; this.targets.push([target, options]); }
    disconnect() { this.targets = []; this.queue = []; }
    takeRecords() { const records = this.queue; this.queue = []; return records; }
    /** @param {any} record @param {'attributes'|'childList'} kind */
    offer(record, kind) {
      const hit = this.targets.some(([t, o]) => o[kind] && (t === record.target || (o.subtree && t.contains(record.target))));
      if (!hit) return;
      if (!this.queue.length) {
        queueMicrotask(() => {
          const records = this.takeRecords();
          if (records.length) { this.calls += 1; this.callback(records); }
        });
      }
      this.queue.push(record);
    }
  }
  doc.mutated = (/** @type {El} */ target) => {
    for (const o of observers) o.offer({ type: 'childList', target }, 'childList');
  };
  const bar = new El('div', doc);
  bar.hidden = true;
  doc.body.append(bar);
  /**
   * A dialog as the page builds it: a header with its words and its close key; the inspector's
   * keys (`actions`) hold an expand key before the close key.
   * @param {string} id
   */
  const dialog = (id, { actions = false } = {}) => {
    const box = new El('dialog', doc);
    box.attrs.id = id;
    box.className = 'studio-dialog';
    const header = new El('div', doc);
    header.className = 'dialog-header';
    const words = new El('div', doc);
    const close = new El('button', doc);
    close.className = 'dialog-close';
    if (actions) {
      const keys = new El('div', doc);
      keys.className = 'dialog-header-actions';
      const expand = new El('button', doc);
      expand.className = 'inspector-expand';
      keys.append(expand, close);
      header.append(words, keys);
    } else {
      header.append(words, close);
    }
    const body = new El('div', doc);
    body.className = 'dialog-body';
    box.append(header, body);
    doc.body.append(box);
    return box;
  };
  /**
   * showModal (or show, when not modal): the focusing steps give the focus to the first
   * [autofocus] control, else the first focusable one in tree order; the observers hear of it a
   * microtask later.
   * @param {El} box
   */
  const open = (box, modal = true) => {
    box.modal = modal;
    box.setAttribute('open', '');
    if (modal) {
      const all = box.all().filter((n) => n !== box && n.focusable);
      const first = all.find((n) => n.hasAttribute('autofocus')) || all[0];
      if (first) first.focus();
    }
    for (const o of observers) o.offer({ type: 'attributes', attributeName: 'open', target: box }, 'attributes');
  };
  /** @param {El} box */
  const close = (box) => {
    box.removeAttribute('open');
    if (box.contains(doc.activeElement)) doc.activeElement = doc.body;
    for (const o of observers) o.offer({ type: 'attributes', attributeName: 'open', target: box }, 'attributes');
  };
  return { doc, bar, dialog, open, close, observers, Observer };
}

const settle = async () => { for (let i = 0; i < 6; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); };

/** The page's API on fakes: the status the test sets; the off held until the test releases it. */
function fakeApi(initial) {
  const state = { status: initial, /** @type {any[]} */ calls: [], /** @type {Function|null} */ release: null };
  /** @param {string} path @param {any} [options] */
  const api = async (path, options = {}) => {
    state.calls.push([path, options.method || 'GET', options.body ? JSON.parse(options.body) : null]);
    if (path.startsWith('/runpod/gpu/off')) {
      await new Promise((resolve) => { state.release = resolve; });
      state.status = off;
      return { command_id: 'x', verified: true, readings: [], words_ro: 'GPU-ul RunPod este oprit și verificat.' };
    }
    return state.status;
  };
  return { api, state };
}

test('hidden without RunPod; the button switches off once however often it is pressed', async () => {
  const { api, state } = fakeApi({ ...off, configured: false });
  const said = [];
  const { bar } = fakeWorld();
  const control = mountGpuSwitch(bar, {
    api, notify: (m) => said.push(m), intervalMs: 0, uuid: () => 'u-1', dialogs: false, now: () => evening.now, timeZone: 'UTC',
  });
  await control.refresh();
  assert.equal(bar.hidden, true);
  state.status = { ...off, endpoints: [{ ...off.endpoints[0], state: 'ON', workers_max: 1, running: 1 }],
    sessions: [{ id: 's', purpose: 'image', step: 'motion' }] };
  await control.refresh();
  assert.equal(bar.hidden, false);
  const [, label, button] = bar.children;
  assert.equal(label.textContent, 'GPU pornit, worker activ · pas: motion');
  assert.equal(button.textContent, 'Oprește GPU acum');
  assert.equal(button.disabled, false);
  const first = button.listeners.click();
  const second = button.listeners.click();
  assert.equal(button.disabled, true);
  await settle();
  state.release?.();
  await first; await second;
  const offs = state.calls.filter((c) => c[0] === '/runpod/gpu/off');
  assert.equal(offs.length, 1);
  assert.deepEqual(offs[0][2], { schema_version: 1, command_id: 'u-1' });
  assert.deepEqual(said, ['GPU-ul RunPod este oprit și verificat.']);
  assert.equal(label.textContent, 'GPU oprit la 20:00:00 (verificat)');
  assert.equal(button.disabled, false);
  control.stop();
});

test('while a session is live the reading asks RunPod fresh, at most every 10 s', async () => {
  let clock = 1_000_000;
  const { api, state } = fakeApi(off);
  const { bar } = fakeWorld();
  const control = mountGpuSwitch(bar, { api, notify: () => {}, intervalMs: 0, now: () => clock, dialogs: false });
  await control.refresh();
  await control.refresh();
  // off: the guard's last reading is enough
  assert.deepEqual(state.calls.map((c) => c[0]), ['/runpod/gpu', '/runpod/gpu']);
  state.status = liveWith({ running: 1 });
  await control.refresh(); // learns it is live
  await control.refresh(); // live: fresh
  clock += FRESH_EVERY_MS - 1;
  await control.refresh(); // too soon for another fresh one
  clock += 1;
  await control.refresh();
  assert.deepEqual(state.calls.slice(2).map((c) => c[0]),
    ['/runpod/gpu', '/runpod/gpu?fresh=1', '/runpod/gpu', '/runpod/gpu?fresh=1']);
  control.stop();
});

// FRESH (review 2026-10-09): the backend has no de-duplication of live reads, and a fresh read
// the page abandons (its 10 s timeout) keeps a pool thread on RunPod for up to minutes; asking
// fresh again every 10 s stacked them in front of his own off POST.
test('after a failed fresh reading the next fresh one waits twice as long each time', async () => {
  let clock = 1_000_000;
  /** @type {string[]} */
  const calls = [];
  let failFresh = 2;
  const api = async (/** @type {string} */ path) => {
    calls.push(path);
    if (path.includes('fresh=1') && failFresh > 0) { failFresh -= 1; throw new Error('timeout'); }
    return liveWith({ running: 1 });
  };
  const { bar } = fakeWorld();
  const control = mountGpuSwitch(bar, { api, notify: () => {}, intervalMs: 0, now: () => clock, dialogs: false });
  await control.refresh(); // learns it is live
  await control.refresh(); // fresh: fails (the page gave up on it)
  assert.equal(bar.children[1].textContent, 'GPU: stare necitită');
  clock += FRESH_EVERY_MS;
  await control.refresh(); // 10 s later: the guard's reading, not another live one
  assert.equal(bar.children[1].textContent, 'GPU pornit, worker activ · pas: stills');
  clock += FRESH_EVERY_MS;
  await control.refresh(); // 20 s after the failure: fresh again, fails again
  clock += 3 * FRESH_EVERY_MS;
  await control.refresh(); // 30 s after the second failure: still waiting (40 s)
  clock += FRESH_EVERY_MS;
  await control.refresh(); // 40 s: fresh, succeeds
  clock += FRESH_EVERY_MS;
  await control.refresh(); // a success: back to every 10 s
  assert.deepEqual(calls, [
    '/runpod/gpu', '/runpod/gpu?fresh=1', '/runpod/gpu', '/runpod/gpu?fresh=1', '/runpod/gpu',
    '/runpod/gpu?fresh=1', '/runpod/gpu?fresh=1',
  ]);
  control.stop();
});

test('the fresh back-off is capped at five minutes', async () => {
  let clock = 1_000_000;
  /** @type {string[]} */
  const calls = [];
  const api = async (/** @type {string} */ path) => {
    calls.push(path);
    if (path.includes('fresh=1')) throw new Error('timeout');
    return liveWith({ running: 1 });
  };
  const { bar } = fakeWorld();
  const control = mountGpuSwitch(bar, { api, notify: () => {}, intervalMs: 0, now: () => clock, dialogs: false });
  await control.refresh();
  for (let i = 0; i < 12; i += 1) {
    calls.length = 0;
    clock += FRESH_BACKOFF_MAX_MS;
    await control.refresh();
    assert.deepEqual(calls, ['/runpod/gpu?fresh=1'], `try ${i}: never more than five minutes apart`);
  }
  control.stop();
});

test('with a session open the sheet and «Decizii» carry the stop; two places send one POST', async () => {
  const world = fakeWorld();
  const { api, state } = fakeApi(off);
  const said = [];
  const control = mountGpuSwitch(world.bar, {
    api, notify: (m) => said.push(m), intervalMs: 0, uuid: () => 'u-shared',
    document: world.doc, MutationObserver: world.Observer,
  });
  // the watcher looks only at the `open` attribute of the page's dialogs
  assert.deepEqual(world.observers[0].options, { subtree: true, attributes: true, attributeFilter: ['open'] });
  await control.refresh();
  // the sheet, built by main.js; the GPU is off: its stop exists, hidden
  const sheet = world.dialog('shooting-sheet-drawer');
  world.open(sheet);
  await settle();
  const [sheetStop] = sheet.find('gpu-switch-dialog');
  assert.ok(sheetStop, 'the sheet carries a stop');
  assert.equal(sheetStop.hidden, true, 'hidden while nothing can bill');
  // it sits in the header, just before the close key
  const header = sheet.children[0];
  assert.deepEqual(header.children.map((c) => c.className), ['', 'gpu-switch gpu-switch-dialog', 'dialog-close']);
  // a session opens (his paid step): the sheet's stop shows
  state.status = liveWith({ running: 1 });
  await control.refresh();
  assert.equal(sheetStop.hidden, false);
  const [sheetButton] = sheet.find('gpu-switch-off');
  assert.equal(sheetButton.textContent, 'Oprește GPU acum');
  assert.equal(sheetStop.find('gpu-switch-state')[0].textContent, 'GPU pornit, worker activ · pas: stills');
  // «Decizii», a modal too, gets its own as it opens
  const decisions = world.dialog('decisions-window');
  world.open(decisions);
  await settle();
  const [decisionsStop] = decisions.find('gpu-switch-dialog');
  assert.equal(decisionsStop.hidden, false);
  // he presses in the sheet and in the toolbar at once: one POST, one command id
  const barButton = world.bar.find('gpu-switch-off')[0];
  const fromSheet = sheetButton.listeners.click();
  const fromBar = barButton.listeners.click();
  const fromDecisions = decisionsStop.find('gpu-switch-off')[0].listeners.click();
  assert.equal(fromSheet, fromBar);
  assert.equal(fromSheet, fromDecisions);
  assert.equal(control.commandId(), 'u-shared');
  for (const b of [sheetButton, barButton]) assert.equal(b.disabled, true);
  await settle();
  state.release?.();
  await fromSheet;
  const offs = state.calls.filter((c) => c[0] === '/runpod/gpu/off');
  assert.equal(offs.length, 1);
  assert.deepEqual(offs[0][2], { schema_version: 1, command_id: 'u-shared' });
  // the toolbar's line is behind the modal: the sheet's stop says the answer itself
  assert.deepEqual(said, ['GPU-ul RunPod este oprit și verificat.']);
  const line = sheetStop.find('gpu-switch-said')[0];
  assert.equal(line.textContent, 'GPU-ul RunPod este oprit și verificat.');
  assert.equal(line.hidden, false);
  assert.equal(line.attrs.role, 'status');
  assert.equal(sheetStop.hidden, false, 'his answer stays in front of him though the GPU is off now');
  assert.equal(control.commandId(), '');
  control.stop();
});

// STALE ANSWER (2026-10-10, seen in a real Chromium): his answer stays a minute in the dialogs'
// stops, and a paid round opened in that minute read «GPU-ul RunPod este oprit și verificat.»
// under «GPU permis … pas: motion».
test('his answer goes when a GPU round he did not stop opens; it stays on his own unconfirmed stop', async () => {
  let clock = 1_000_000;
  const world = fakeWorld();
  const { api, state } = fakeApi(liveWith({ running: 1 }));
  const control = mountGpuSwitch(world.bar, {
    api, notify: () => {}, intervalMs: 0, now: () => clock, document: world.doc, MutationObserver: world.Observer,
  });
  await control.refresh();
  const sheet = world.dialog('shooting-sheet-drawer');
  world.open(sheet);
  await settle();
  const pressed = control.press();
  await settle();
  state.release?.();
  await pressed;
  const line = sheet.find('gpu-switch-said')[0];
  assert.equal(line.textContent, 'GPU-ul RunPod este oprit și verificat.');
  // the session he stopped is still listed (its close not written yet): his answer stays
  state.status = liveWith({ running: 0, in_progress: 0, in_queue: 0 });
  clock += 1000;
  await control.refresh();
  assert.equal(line.hidden, false);
  assert.equal(line.textContent, 'GPU-ul RunPod este oprit și verificat.');
  // 20 s later the studio opens the next paid round: the answer is about another GPU round now
  state.status = liveWith({ running: 0, in_progress: 0, in_queue: 0 }, [{ id: 's-next', purpose: 'video', step: 'motion' }]);
  clock += 20000;
  await control.refresh();
  assert.equal(line.hidden, true);
  assert.equal(line.textContent, '');
  assert.equal(sheet.find('gpu-switch-state')[0].textContent, 'GPU permis, 0 workeri — nu se plătește · pas: motion');
  assert.equal(sheet.find('gpu-switch-dialog')[0].hidden, false, 'the stop stays: the new round can bill');
  control.stop();
});

// FOCUS (review 2026-10-09): the stop stayed in a closed dialog's header, and while the GPU was
// live it was the reopened dialog's first control: showModal() focused it, and one Enter or Space
// after reopening the sheet or the inspector switched the GPU off in the middle of his paid round.
test('a dialog reopened while the GPU is live never opens with the focus on the stop', async () => {
  const world = fakeWorld();
  const { api, state } = fakeApi(liveWith({ running: 1 }));
  const control = mountGpuSwitch(world.bar, {
    api, notify: () => {}, intervalMs: 0, document: world.doc, MutationObserver: world.Observer,
  });
  await control.refresh();
  const sheet = world.dialog('shooting-sheet-drawer');
  const closeKey = sheet.find('dialog-close')[0];
  world.open(sheet);
  await settle();
  const [stop] = sheet.find('gpu-switch-dialog');
  assert.equal(stop.hidden, false);
  assert.equal(world.doc.activeElement, closeKey);
  world.close(sheet);
  await settle();
  // reopened: the browser focuses the stop (its first control); the switch gives the focus back
  world.open(sheet);
  assert.equal(world.doc.activeElement.className, 'gpu-switch-off', 'the browser picked the stop');
  await settle();
  assert.equal(world.doc.activeElement, closeKey, 'the focus is where the sheet alone would put it');
  // the inspector: its first key without the stop is its expand key
  const inspector = world.dialog('agent-inspector', { actions: true });
  world.open(inspector);
  await settle();
  world.close(inspector);
  await settle();
  world.open(inspector);
  await settle();
  assert.equal(world.doc.activeElement.className, 'inspector-expand');
  // an opener that moves the focus itself (Decizii, to its tab) keeps it there
  const decisions = world.dialog('decisions-window');
  const tab = new El('button', world.doc);
  tab.className = 'decisions-tab';
  decisions.children[1].append(tab);
  world.open(decisions);
  await settle();
  world.close(decisions);
  await settle();
  world.open(decisions);
  tab.focus();
  await settle();
  assert.equal(world.doc.activeElement, tab);
  // no Enter reached the stop: nothing was switched off
  assert.equal(state.calls.filter((c) => c[0] === '/runpod/gpu/off').length, 0);
  control.stop();
});

test('the focus candidates leave out the stop and hidden parts, [autofocus] first', () => {
  const world = fakeWorld();
  const box = world.dialog('d');
  const stop = new El('div', world.doc);
  const stopKey = new El('button', world.doc);
  stop.append(stopKey);
  placeInDialog(box, stop);
  const hiddenPart = new El('div', world.doc);
  hiddenPart.hidden = true;
  hiddenPart.append(new El('button', world.doc));
  const field = new El('input', world.doc);
  field.setAttribute('autofocus', '');
  box.children[1].append(hiddenPart, field);
  const found = focusCandidates(box, stop);
  assert.equal(found[0], field);
  assert.equal(found[1], box.find('dialog-close')[0]);
  assert.equal(found.includes(stopKey), false);
  assert.equal(found.length, 2);
});

test('a dialog opened twice keeps one stop; a rebuilt header gets it back; a non-modal one has none', async () => {
  const world = fakeWorld();
  const { api, state } = fakeApi(liveWith({ running: 1 }));
  const control = mountGpuSwitch(world.bar, {
    api, notify: () => {}, intervalMs: 0, document: world.doc, MutationObserver: world.Observer,
  });
  await control.refresh();
  const sheet = world.dialog('shooting-sheet-drawer');
  world.open(sheet);
  world.close(sheet);
  world.open(sheet);
  await settle();
  assert.equal(sheet.find('gpu-switch-dialog').length, 1);
  // Settings rebuilds its whole dialog on each render (REBUILT, review 2026-10-09): the stop is
  // back in the same microtask, not at the next poll; no reading is needed for it
  const settings = world.dialog('settings-dialog');
  world.open(settings);
  await settle();
  const before = settings.find('gpu-switch-dialog');
  assert.equal(before.length, 1);
  const reads = state.calls.length;
  for (let render = 0; render < 3; render += 1) {
    const header = new El('div', world.doc);
    header.className = 'dialog-header';
    const closeKey = new El('button', world.doc);
    closeKey.className = 'dialog-close';
    header.append(new El('div', world.doc), closeKey);
    settings.replaceChildren(header);
    assert.equal(settings.find('gpu-switch-dialog').length, 0);
    await settle();
    const back = settings.find('gpu-switch-dialog');
    assert.equal(back.length, 1, `render ${render}: the stop is back without a reading`);
    assert.equal(back[0], before[0], 'the same stop, his answer line with it');
    assert.equal(back[0].hidden, false);
    assert.equal(back[0].parentNode, header, 'in the rebuilt header');
  }
  assert.equal(state.calls.length, reads, 'no reading was asked for it');
  // its own words do not wake the watcher in a loop
  const inside = world.observers[1];
  const calls = inside.calls;
  await control.refresh();
  await settle();
  assert.ok(inside.calls - calls <= 2, `the watcher settled (${inside.calls - calls} wake-ups)`);
  // a closed dialog's contents are not watched any more
  world.close(settings);
  await settle();
  assert.equal(inside.targets.some(([/** @type {any} */ t]) => t === settings), false);
  // a dialog shown without showModal leaves the toolbar reachable
  const loose = world.dialog('loose');
  world.open(loose, false);
  await settle();
  assert.equal(loose.find('gpu-switch-dialog').length, 0);
  control.stop();
});

test('a reading that fails while the GPU is live keeps the stop, saying «necitită»', async () => {
  const world = fakeWorld();
  let fail = false;
  const api = async () => { if (fail) throw new Error('rețea'); return liveWith({ running: 1 }); };
  const control = mountGpuSwitch(world.bar, {
    api, notify: () => {}, intervalMs: 0, document: world.doc, MutationObserver: world.Observer,
  });
  const sheet = world.dialog('shooting-sheet-drawer');
  world.open(sheet);
  await settle();
  fail = true;
  await control.refresh();
  const [stop] = sheet.find('gpu-switch-dialog');
  assert.equal(stop.hidden, false);
  assert.equal(stop.find('gpu-switch-state')[0].textContent, 'GPU: stare necitită');
  assert.equal(stop.dataset.tone, 'unknown');
  control.stop();
});

test('a simulated RunPod shows no stop in the dialogs', async () => {
  const world = fakeWorld();
  const { api } = fakeApi({ ...liveWith({ running: 1 }), mock: true });
  const control = mountGpuSwitch(world.bar, {
    api, notify: () => {}, intervalMs: 0, document: world.doc, MutationObserver: world.Observer,
  });
  const sheet = world.dialog('shooting-sheet-drawer');
  world.open(sheet);
  await settle();
  assert.equal(sheet.find('gpu-switch-dialog')[0].hidden, true);
  assert.equal(world.bar.hidden, false);
  control.stop();
});

test('the stop goes among the inspector header keys, or first in a dialog without a header', () => {
  const world = fakeWorld();
  const inspector = world.dialog('agent-inspector', { actions: true });
  const node = new El('div', world.doc);
  placeInDialog(inspector, node);
  const actions = inspector.find('dialog-header-actions')[0];
  assert.equal(actions.children[0], node);
  const question = new El('dialog', world.doc);
  question.append(new El('div', world.doc));
  const other = new El('div', world.doc);
  placeInDialog(question, other);
  assert.equal(question.children[0], other);
});

test('the page mounts the switch with its dialog watcher on (GPU_STOP_REACHABLE)', () => {
  assert.match(MAIN, /mountGpuSwitch\(element\('gpu-switch'\), \{ api, notify \}\)/);
  assert.doesNotMatch(MAIN, /dialogs:\s*false/);
});
