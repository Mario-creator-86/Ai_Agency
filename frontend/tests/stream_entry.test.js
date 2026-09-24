// W19 «one continuous, truthful visit with the real stream»: the kept last live frame at the entry,
// the studio's numbers over the video, the replay's door, and «live» only while it is.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { KEEP_EVERY_MS, KEEP_FIRST_MS, KEEP_MAX_AGE_MS, keptCaption, keptSize, keptUsable, readKept, writeKept } from '../src/stream_keep.js';
import { streamLayers } from '../src/hq_stream_config.js';
import { LiveStream, DOOR_MS, HANDOFF_MS } from '../src/hq_stream.js';
import { PLAQUES, PLAQUE_GAP, placePlaque, plaqueLevel, plaqueShownAt, plaqueWords, streamOffset } from '../src/stream_plaques.js';
import { SURFACES, surfaceReadout } from '../src/hq_readouts.js';
import { liveScope, roomCaption, roomCaptionShort } from '../src/live_claims.js';
import { dayTrackFromRun } from '../src/hud_charts.js';

const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
const SCENE_CSS = fs.readFileSync(new URL('../src/office_scene.css', import.meta.url), 'utf8');
const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const MANIFEST = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/manifest.json', import.meta.url), 'utf8'));
const RUN = JSON.parse(fs.readFileSync(new URL('./fixtures/runbook_run.json', import.meta.url), 'utf8'));

/* ------------------------------------------------------------------ the kept frame -- */

test('the kept frame is small, in the stream\'s own aspect, and never enlarged', () => {
  // W22: at the stream's own width, since the title stands on it as key art; never enlarged
  assert.deepEqual(keptSize(1920, 1008), { w: 1920, h: 1008 });
  assert.deepEqual(keptSize(3840, 2016), { w: 1920, h: 1008 });
  assert.deepEqual(keptSize(640, 360), { w: 640, h: 360 });
  assert.equal(keptSize(0, 1008), null);
  assert.ok(KEEP_FIRST_MS >= 2000 && KEEP_EVERY_MS >= 30000, 'taken rarely, never per frame');
});

test('the kept frame is named for what it is, with its day and hour in the studio\'s zone', () => {
  const now = Date.parse('2026-09-24T20:48:00Z'); // 23:48 in Bucharest, Thursday
  assert.equal(keptCaption(Date.parse('2026-09-24T19:15:00Z'), now, 'Europe/Bucharest'), 'ultimul cadru live · azi 22:15');
  assert.equal(keptCaption(Date.parse('2026-09-23T18:05:00Z'), now, 'Europe/Bucharest'), 'ultimul cadru live · ieri 21:05');
  assert.equal(keptCaption(Date.parse('2026-09-20T09:30:00Z'), now, 'Europe/Bucharest'), 'ultimul cadru live · duminică 12:30');
  assert.equal(keptCaption(Date.parse('2026-09-12T20:59:00Z'), now, 'Europe/Bucharest'), 'ultimul cadru live · 12.09 23:59');
  // just after midnight in Bucharest is already the next day, whatever UTC says
  assert.equal(keptCaption(Date.parse('2026-09-23T21:30:00Z'), Date.parse('2026-09-24T06:00:00Z'), 'Europe/Bucharest'), 'ultimul cadru live · azi 00:30');
  assert.equal(keptCaption(NaN, now), '');
});

test('only a real, recent picture is laid on the plate', () => {
  const now = Date.parse('2026-09-24T20:48:00Z');
  const good = { blob: {}, at: now - 3600e3, w: 960, h: 504 };
  assert.ok(keptUsable(good, now));
  assert.ok(!keptUsable(null, now));
  assert.ok(!keptUsable({ ...good, blob: null }, now));
  assert.ok(!keptUsable({ ...good, w: 0 }, now));
  assert.ok(!keptUsable({ ...good, at: now + 3600e3 }, now), 'a frame from the future is not one');
  assert.ok(!keptUsable({ ...good, at: now - KEEP_MAX_AGE_MS - 1 }, now), 'the building may have been rebuilt since');
});

/** A small in-memory indexedDB: open, upgrade, one store, get and put. */
function fakeIDB() {
  const stores = new Map();
  const later = (fn) => setTimeout(fn, 0);
  const db = {
    objectStoreNames: { contains: (n) => stores.has(n) },
    createObjectStore: (n) => { stores.set(n, new Map()); },
    close() {},
    transaction(name) {
      const map = stores.get(name);
      const tx = { oncomplete: null, onerror: null, onabort: null };
      tx.objectStore = () => ({
        get(key) { const r = { result: undefined, onsuccess: null }; later(() => { r.result = map.get(key); r.onsuccess && r.onsuccess(); }); return r; },
        put(value, key) { later(() => { map.set(key, value); tx.oncomplete && tx.oncomplete(); }); },
      });
      return tx;
    },
  };
  return {
    open() {
      const r = { result: db, onupgradeneeded: null, onsuccess: null, onerror: null, onblocked: null };
      later(() => { if (!stores.size) r.onupgradeneeded && r.onupgradeneeded(); r.onsuccess && r.onsuccess(); });
      return r;
    },
  };
}

test('a frame kept by one visit is read by the next', async () => {
  const idb = fakeIDB();
  assert.equal(await readKept(idb), null, 'a first visit has none');
  assert.equal(await writeKept(idb, { blob: { size: 50000 }, at: 1758744000000, w: 960, h: 504 }), true);
  assert.deepEqual(await readKept(idb), { blob: { size: 50000 }, at: 1758744000000, w: 960, h: 504 });
});

test('a browser that refuses storage simply has no kept frame', async () => {
  const throws = { open() { throw new Error('SecurityError'); } };
  assert.equal(await readKept(throws), null);
  assert.equal(await writeKept(throws, { blob: {}, at: 1, w: 1, h: 1 }), false);
  assert.equal(await readKept(null), null);
  const refuses = { open() { const r = { onerror: null }; setTimeout(() => r.onerror && r.onerror(), 0); return r; } };
  assert.equal(await readKept(refuses), null);
});

test('with a kept frame the starting plate is that frame, never the dark and never the old renderer', () => {
  assert.deepEqual(streamLayers('connecting', false, false, true), { still: true, waiting: false, note: 'kept', held: false, kept: true });
  assert.deepEqual(streamLayers('offline', false, false, true), { still: true, waiting: false, note: 'kept', held: false, kept: true });
  // this visit's own frozen frame outranks an earlier visit's
  assert.equal(streamLayers('offline', true, false, true).note, 'reconnecting');
  // live: the video, whatever was kept
  assert.equal(streamLayers('live', false, false, true).still, false);
  // none kept: the dark plate says the live headquarters is starting (the Owner's rule, 2026-09-15)
  assert.equal(streamLayers('connecting', false, false, false).note, 'starting');
});

/** A LiveStream without the library: the parts the page's own logic touches. */
function player(t, { reduced = false } = {}) {
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const previous = globalThis.window;
  globalThis.window = { setTimeout: (...a) => setTimeout(...a), clearTimeout: (id) => clearTimeout(id) };
  t.after(() => { globalThis.window = previous; });
  const classes = new Set();
  const drawn = [];
  const p = Object.create(LiveStream.prototype);
  Object.assign(p, {
    status: 'offline', settings: { retryMs: 15000 }, retryTimer: 0, stillTimer: 0, keepTimer: 0, handoffTimer: 0, doorTimer: 0,
    hasStill: false, held: false, keptShown: false, keptCaption: '', firstFrame: false, door: '',
    still: { hidden: true, width: 0, height: 0, getContext: () => ({ drawImage: (img) => drawn.push(img) }) },
    badge: { hidden: true, textContent: '' },
    layer: { hidden: true, classList: { toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)), add: (...c) => c.forEach((x) => classes.add(x)), remove: (...c) => c.forEach((x) => classes.delete(x)) }, querySelector: () => null },
    stream: { reconnect() {} },
    onStatus() {}, onFrameRate() {}, onKeep: null,
    reduced: () => reduced,
    _copyFrame() { this.hasStill = true; return true; },
  });
  return { p, classes, drawn };
}

test('the kept frame is shown dimmed and named, and gives way when the live video presents its first frame', (t) => {
  const { p, classes, drawn } = player(t);
  p._setStatus('connecting');
  assert.ok(classes.has('waiting'));
  assert.equal(p.showKept({ width: 960, height: 504 }, 'ultimul cadru live · azi 22:48'), true);
  assert.equal(drawn.length, 1);
  assert.ok(classes.has('kept') && !classes.has('waiting'));
  assert.equal(p.still.hidden, false);
  assert.equal(p.badge.textContent, 'ultimul cadru live · azi 22:48 · pornește sediul live…');
  // live, but no frame presented yet: the kept frame stays; nothing says live over it
  p.status = 'live';
  p._applyLayers();
  assert.equal(p.still.hidden, false);
  assert.ok(classes.has('kept'));
  // the first frame: the kept one fades off, then is gone
  p._firstFrame();
  assert.ok(classes.has('handoff'));
  assert.equal(p.badge.hidden, true);
  t.mock.timers.tick(HANDOFF_MS + 50);
  assert.ok(!classes.has('handoff') && !classes.has('kept'));
  assert.equal(p.still.hidden, true);
  assert.equal(p.keptShown, false);
  // once this visit has its own frame, an earlier one is refused
  assert.equal(p.showKept({ width: 960, height: 504 }, 'x'), false);
});

test('W20: going live with the video already holding a frame keeps the kept frame for its fade, and does not paint over it', (t) => {
  // Seen on the real stream (W20): the library's playStream came with the video's first frame
  // already decoded, and the frozen-frame copy made on going live dropped the kept frame at once: a
  // cut, never the fade, and the kept canvas repainted with this visit's frame under the old name.
  const { p, classes, drawn } = player(t);
  p._setStatus('connecting');
  p.showKept({ width: 960, height: 504 }, 'ultimul cadru live · azi 22:48');
  assert.equal(drawn.length, 1);
  let copies = 0;
  p._copyFrame = function () { copies += 1; this.hasStill = true; return true; };
  p._setStatus('live');
  assert.equal(copies, 0, 'nothing is copied over the kept frame before it has given way');
  assert.ok(classes.has('kept'));
  assert.equal(p.keptShown, true);
  p._firstFrame();
  assert.ok(classes.has('handoff'), 'the kept frame fades off the live video');
  // its name goes with it: the corner already says «Live» over the live video fading in
  p._applyLayers();
  assert.equal(p.badge.hidden, true, 'no «ultimul cadru live … pornește sediul live…» during the fade');
  t.mock.timers.tick(HANDOFF_MS + 50);
  assert.ok(!classes.has('kept') && !classes.has('handoff'));
  assert.equal(copies, 1, 'once it has given way, this visit keeps its own frame at once');
  assert.equal(p.hasStill, true);
});

test('W20: should the first-frame callback never come, a video that has presented frames still hands the kept frame off', (t) => {
  const { p, classes } = player(t);
  let presented = 0;
  const video = { readyState: 4, videoWidth: 1920, videoHeight: 1008, getVideoPlaybackQuality: () => ({ totalVideoFrames: presented }) };
  p.layer.querySelector = () => video;
  p._setStatus('connecting');
  p.showKept({ width: 960, height: 504 }, 'ultimul cadru live · azi 22:48');
  p._setStatus('live');
  assert.ok(classes.has('kept') && !classes.has('handoff'), 'no frame presented: the kept frame stays');
  presented = 3;
  t.mock.timers.tick(2000);
  assert.ok(classes.has('handoff'));
  t.mock.timers.tick(HANDOFF_MS + 50);
  assert.ok(!classes.has('kept'));
  assert.equal(p.hasStill, true);
});

test('W20: held (reduced motion), going live replaces the kept frame with this visit\'s first held frame', (t) => {
  const { p, classes } = player(t, { reduced: true });
  p.held = true;
  p._setStatus('connecting');
  p.showKept({ width: 960, height: 504 }, 'ultimul cadru live · azi 22:48');
  p._setStatus('live');
  assert.equal(p.keptShown, false);
  assert.ok(!classes.has('kept'));
  assert.ok(classes.has('held'));
});

test('under reduced motion the kept frame is cut to the live video, not faded', (t) => {
  const { p, classes } = player(t, { reduced: true });
  p._setStatus('connecting');
  p.showKept({ width: 960, height: 504 }, 'ultimul cadru live · azi 22:48');
  p.status = 'live';
  p._firstFrame();
  assert.ok(!classes.has('handoff'));
  assert.equal(p.still.hidden, true);
});

test('the replay\'s door: the live picture fades out into the graded building and back in; a cut under reduced motion', (t) => {
  const { p, classes } = player(t);
  p.status = 'live';
  p._applyLayers();
  p.doorway('out');
  assert.ok(classes.has('door-out'));
  assert.equal(p.still.hidden, false, 'a real frame of the live video, held while it fades');
  assert.equal(p.hasStill, true);
  t.mock.timers.tick(DOOR_MS + 50);
  assert.ok(!classes.has('door-out'));
  assert.equal(p.still.hidden, true);
  p.doorway('in');
  assert.ok(classes.has('door-in'));
  t.mock.timers.tick(DOOR_MS + 50);
  assert.ok(!classes.has('door-in'));
});

test('under reduced motion the replay door is a clean cut', (t) => {
  const r = player(t, { reduced: true });
  r.p.status = 'live';
  r.p.doorway('out');
  assert.ok(!r.classes.has('door-out'));
  r.p.doorway('in');
  assert.ok(!r.classes.has('door-in'));
});

test('a frame is kept rarely while the stream plays, and only then', (t) => {
  const { p } = player(t);
  const kept = [];
  const previous = globalThis.document;
  globalThis.document = { visibilityState: 'visible', createElement: () => ({ width: 0, height: 0, getContext: () => ({ drawImage() {} }), toBlob: (cb) => cb({ size: 1 }) }) };
  t.after(() => { globalThis.document = previous; });
  p.onKeep = (record) => kept.push(record);
  const video = { readyState: 4, videoWidth: 1920, videoHeight: 1008 };
  p.layer.querySelector = () => video;
  p.status = 'live';
  p._firstFrame();
  t.mock.timers.tick(KEEP_FIRST_MS - 1);
  assert.equal(kept.length, 0);
  t.mock.timers.tick(1);
  assert.equal(kept.length, 1);
  assert.deepEqual([kept[0].w, kept[0].h], [1920, 1008], 'W22: at the stream width');
  t.mock.timers.tick(KEEP_EVERY_MS);
  assert.equal(kept.length, 2);
  p._setStatus('offline');
  t.mock.timers.tick(KEEP_EVERY_MS * 3);
  assert.equal(kept.length, 2, 'nothing is kept while the stream is not live');
});

test('the page reads the kept frame while the title is up, keeps new ones, and opens the door both ways', () => {
  // W22: read by one function, again after a sign-out, and first by the title
  assert.match(MAIN, /let keptFrame = readKeptFrame\(\);/);
  assert.match(MAIN, /readKept\(browserStore\(\)\)/);
  assert.match(MAIN, /writeKept\(browserStore\(\), record\)/);
  assert.match(MAIN, /liveStream\.showKept\(kept\.image, keptCaption\(/);
  assert.match(MAIN, /liveStream\.doorway\('out'\)/);
  assert.match(MAIN, /liveStream\.doorway\('in'\)/);
  assert.match(SCENE_CSS, /\.live-stream-layer\.kept \.live-stream-still \{ filter: var\(--kept-dim\); \}/);
  assert.match(SCENE_CSS, /\[data-replay\] \.live-stream-layer\.door-out \{ visibility: visible;/);
  assert.match(SCENE_CSS, /@media \(prefers-reduced-motion: reduce\) \{\r?\n  \.scene-viewport \.stream-plaque,[\s\S]*?door-in \{ animation: none; \}/);
  assert.match(STYLE, /--dur-door:\s+620ms;/);
});

/* ------------------------------------------------------------------ the plaques -- */

const factsRun = {
  business_date: '2026-09-12',
  stages: [
    { stage: 'research_and_verification', artefacts: { claims_verified: 0, verdicts_refused: 11 } },
    { stage: 'publish', artefacts: { publication_status: 'PUBLISHED' } },
  ],
};
const facts = {
  run: factsRun,
  track: dayTrackFromRun(RUN),
  today: '2026-09-24',
  live: true,
  treasury: { spendable: { amount: '50000.00' }, in_deficit: false },
  budget: null,
  reads: { runs: 'ok', figures: 'ok' },
};

test('the plaques say the faces\' own figures, from the same facts, shortened', () => {
  const run = plaqueWords('run_sign', facts);
  assert.equal(run.eyebrow, 'RULAREA DIN 12.09');
  assert.equal(run.value, '12/12 · încheiată');
  assert.deepEqual([plaqueWords('factcheck_board', facts).eyebrow, plaqueWords('factcheck_board', facts).value], ['VERIFICARE · 12.09', '0 verificate · 11 respinse']);
  const one = plaqueWords('factcheck_board', { run: { ...factsRun, stages: [{ stage: 'research_and_verification', artefacts: { claims_verified: 1, verdicts_refused: 1 } }] } });
  assert.equal(one.value, '1 verificată · 1 respins');
  assert.equal(plaqueWords('publish_radar', facts).value, 'PUBLICAT · 12.09');
  assert.equal(plaqueWords('publish_radar', facts, [{ desk_id: 'desk_publish', runtime_state: 'WORKING' }]).value, 'ÎN LUCRU');
  // W21: the same record holds a VR_DEBT of 50.000; the bare number misled, the face card's phrase does not
  assert.equal(plaqueWords('treasury_board', facts).value, '50.000 VR$ cheltuibili');
  assert.equal(plaqueWords('treasury_board', facts).value, surfaceReadout('treasury_board', { facts }).value);
  assert.equal(plaqueWords('treasury_board', { ...facts, treasury: { spendable: { amount: '-3' }, in_deficit: true } }).tone, 'alert');
});

test('a plaque the page holds no value for says «—», never an invented figure', () => {
  for (const def of PLAQUES) assert.equal(plaqueWords(def.id, {}).value, '—', def.id);
  assert.equal(plaqueWords('run_sign', {}).eyebrow, 'RULAREA ZILEI');
});

test("W21: the serial's board, the render screen and the servers carry their faces' own words", () => {
  const more = {
    ...facts,
    episodes: { episodes: [{ created_at: '2026-09-20T10:00:00Z', status: 'DRAFT', title: 'Primul pas', continuity: { episode_number: 3 } }] },
    budget: { today: { prompt_tokens: 1000, completion_tokens: 234 } },
  };
  const card = (id) => surfaceReadout(id, { facts: more, agents: [] }).value;
  const w = plaqueWords('writers_screen', more);
  assert.equal(w.eyebrow, 'OFFICE SERIAL');
  assert.equal(w.value, card('writers_screen'));
  assert.match(w.value, /^EP 3 · /);
  const r = plaqueWords('render_bay', more);
  assert.equal(r.eyebrow, 'RANDARE');
  assert.equal(r.value, card('render_bay'));
  const editor = [{ desk_id: 'desk_video', runtime_state: 'WORKING', display_name: 'Leo (Editor)' }];
  assert.equal(plaqueWords('render_bay', more, editor).value, surfaceReadout('render_bay', { facts: more, agents: editor }).value);
  assert.equal(plaqueWords('render_bay', more, editor).tone, 'ok');
  const i = plaqueWords('infra_plate', more);
  assert.equal(i.eyebrow, 'SERVERE');
  assert.equal(i.value, '1.234 de tokenuri azi');
  assert.equal(i.value, card('infra_plate'));
  // nothing read: «—», not the face's «tokenuri azi —»
  assert.equal(plaqueWords('infra_plate', { ...facts, budget: null }).value, '—');
});

test('W21: the three newer plaques need their eyebrow to be read, so the small building (1280 at fit) shows only the four', () => {
  const small = PLAQUES.filter((def) => plaqueShownAt(def, 'compact')).map((def) => def.id);
  assert.deepEqual(small, ['run_sign', 'factcheck_board', 'publish_radar', 'treasury_board']);
  for (const level of ['full', 'large']) assert.equal(PLAQUES.filter((def) => plaqueShownAt(def, level)).length, 7, level);
  for (const def of PLAQUES) assert.equal(plaqueShownAt(def, 'none'), false, def.id);
});

test('each plaque is anchored to a real object of the streamed building, measured on the stream', () => {
  assert.equal(PLAQUES.length, 7);
  const offsets = Object.fromEntries(PLAQUES.map((def) => {
    const face = SURFACES.find((s) => s.id === def.id);
    const rect = face.rect || MANIFEST.screens[face.screen].rect;
    return [def.id, streamOffset(def, rect)];
  }));
  // the Unreal building was built from the same manifest: three objects stand on the plates' faces,
  // the Treasury's lockers 79 px left of the plate's ticker (the ticker's wall is a bookcase in Unreal)
  assert.deepEqual(offsets, {
    run_sign: { dx: -5, dy: -2 }, factcheck_board: { dx: 0, dy: -1 }, publish_radar: { dx: 0, dy: 0 }, treasury_board: { dx: -79, dy: -7 },
    // W21: the serial's empty wall screen and the servers' dark band stand on the plates' faces; the
    // render plaque stands on the screen's light bar, 13 px below the screen's centre
    writers_screen: { dx: 0, dy: 0 }, render_bay: { dx: 1, dy: 13 }, infra_plate: { dx: 0, dy: 0 },
  });
  for (const def of PLAQUES) {
    const [x, y, w, h] = def.anchor;
    assert.ok(x >= 0 && y >= 0 && x + w <= 1600 && y + h <= 840 && w > 0 && h > 0, def.id);
  }
});

test('the plaques fade below the zoom where they would clutter, and say less where the building is small', () => {
  assert.equal(plaqueLevel(0.4), 'none');
  assert.equal(plaqueLevel(0.78), 'compact'); // 1280 at fit
  assert.equal(plaqueLevel(1.15), 'full'); // 1920 at fit
  assert.equal(plaqueLevel(1.55), 'large'); // 2560 at fit
  assert.equal(plaqueLevel(NaN), 'none');
});

test('a plaque never covers an employee, stays in the room, and gives up rather than cover one', () => {
  const room = { left: 0, top: 0, right: 1000, bottom: 800 };
  const anchor = { x: 400, y: 300, w: 40, h: 30 };
  const size = { w: 100, h: 30 };
  assert.deepEqual(placePlaque(anchor, size, ['on'], room, []), { x: 370, y: 300, side: 'on' });
  const desk = { x: 380, y: 298, w: 60, h: 60 };
  const at = placePlaque(anchor, size, ['on', 'above', 'right'], room, [desk]);
  assert.equal(at.side, 'above');
  assert.equal(at.y, 300 - PLAQUE_GAP - 30);
  assert.equal(placePlaque(anchor, size, ['on'], room, [desk]), null);
  // off the room's edge (under a drawer): not shown there
  assert.equal(placePlaque({ x: 960, y: 10, w: 30, h: 20 }, size, ['on', 'right'], room, []), null);
});

test('the plaques are shown only while the live stream is what is seen, and step aside for their face\'s readout', () => {
  assert.match(MAIN, /viewport\.dataset\.stream === 'live' && !replaying\(\)/);
  assert.match(MAIN, /streamPlaques\.suppress\(target && target\.kind !== 'agent'/);
  // W22: hidden over the page's own replay; over the replay in the Unreal building they stay
  assert.match(SCENE_CSS, /\.scene-viewport\[data-replay\]:not\(\[data-replay-look="unreal"\]\) \.stream-plaques \{ visibility: hidden; \}/);
  assert.match(SCENE_CSS, /\.stream-plaques \{ position: absolute; inset: 0; z-index: 3; pointer-events: none;/);
});

/* ------------------------------------------------------------------ what is live -- */

test('«live» on the slate only while the picture and the data both are; otherwise which one is', () => {
  const s = (stream, socket, data = 'fresh') => liveScope({ stream, socket, data, hasStill: false, streamFps: null, pageFps: null });
  assert.equal(s('live', 'open'), 'all');
  assert.equal(s('live', 'reconnecting'), 'stream', 'W18: the socket dropped while Unreal kept playing');
  assert.equal(s('live', 'open', 'stale'), 'stream');
  assert.equal(s('connecting', 'open'), 'data');
  assert.equal(s('offline', 'open'), 'data');
  assert.equal(s('offline', 'closed'), 'none');
  // without a stream the page's drawing is the data
  assert.equal(s('off', 'open'), 'all');
  assert.equal(s('off', 'reconnecting'), 'none');
  assert.equal(roomCaption(8, 'stream'), '8 angajați la birourile lor · sediul AMN-AI · doar imaginea e live');
  assert.equal(roomCaption(8, 'data'), '8 angajați la birourile lor · sediul AMN-AI · doar datele sunt live');
  assert.equal(roomCaption(8, 'all'), roomCaption(8, true));
  assert.equal(roomCaption(8, 'none'), roomCaption(8, false));
  assert.equal(roomCaptionShort(8, 'stream'), '8 angajați · imagine live');
  assert.equal(roomCaptionShort(8, 'data'), '8 angajați · date live');
  assert.match(MAIN, /const scope = liveScope\(liveSignals\);/);
  assert.match(MAIN, /canvasLabel\(scope === 'all'\)/);
});
