// W22 «one building from the title to the replay»: with the stream configured, the title stands on
// this browser's kept real frame of the Unreal building and lands it where the stream will play,
// and the replay plays over a still of the real building instead of the page's own renderer.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { keptCaption, keptDay } from '../src/stream_keep.js';
import {
  ROOM_EASE_MS, STREAM_MONITORS, STREAM_ROOMS, STREAM_SEATED, STREAM_SHELTER_CLOCK, easeToward, glowBloom, monitorGlow, monitorGlows,
  replayInUnreal, roomLevels, roomLight, stillLine, stillSentence,
} from '../src/replay_still.js';
import { KEPT_DEPTH, WORLD, keptPlacement, landingPlacement, placementTransform, titleFrame, titleKeptCaption } from '../src/title_frame.js';
import { plaqueWords } from '../src/stream_plaques.js';
import { LiveStream } from '../src/hq_stream.js';

const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
const TITLE = fs.readFileSync(new URL('../src/title_screen.js', import.meta.url), 'utf8');
const WORLD_JS = fs.readFileSync(new URL('../src/hq_world.js', import.meta.url), 'utf8');
const ENGINE = fs.readFileSync(new URL('../src/office_engine.js', import.meta.url), 'utf8');
const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const SCENE_CSS = fs.readFileSync(new URL('../src/office_scene.css', import.meta.url), 'utf8');
const MANIFEST = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/manifest.json', import.meta.url), 'utf8'));

const NOW = Date.parse('2026-09-24T21:52:00Z'); // 00:52 in Bucharest, Friday 25.09

/* ----------------------------------------------------------------------------- the words -- */

test('a real frame is named by its day and hour in the studio\'s zone, the same way everywhere', () => {
  assert.deepEqual(keptDay(Date.parse('2026-09-24T21:47:00Z'), NOW, 'Europe/Bucharest'), { day: 'azi', hm: '00:47', dated: false });
  assert.deepEqual(keptDay(Date.parse('2026-09-24T18:05:00Z'), NOW, 'Europe/Bucharest'), { day: 'ieri', hm: '21:05', dated: false });
  assert.deepEqual(keptDay(Date.parse('2026-09-12T20:59:00Z'), NOW, 'Europe/Bucharest'), { day: '12.09', hm: '23:59', dated: true });
  assert.equal(keptDay(NaN, NOW), null);
  // the plate's badge is unchanged by the refactor
  assert.equal(keptCaption(Date.parse('2026-09-24T21:47:00Z'), NOW, 'Europe/Bucharest'), 'ultimul cadru live · azi 00:47');
});

test('the replay over the photograph says what the picture is, and that its light and weather are not those of then', () => {
  const at = Date.parse('2026-09-24T21:47:00Z');
  assert.equal(stillLine(at, NOW, 'Europe/Bucharest'), 'cadru live de azi, 00:47 · lumina și vremea nu sunt cele de atunci');
  assert.equal(stillLine(Date.parse('2026-09-20T09:30:00Z'), NOW, 'Europe/Bucharest'), 'cadru live de duminică, 12:30 · lumina și vremea nu sunt cele de atunci');
  assert.equal(stillLine(Date.parse('2026-09-12T20:59:00Z'), NOW, 'Europe/Bucharest'), 'cadru live din 12.09, 23:59 · lumina și vremea nu sunt cele de atunci');
  assert.equal(stillSentence(at, NOW, 'Europe/Bucharest'), 'Clădirea este cadrul live de azi, 00:47; lumina și vremea lui nu sunt cele de atunci.');
  assert.equal(stillLine(NaN, NOW), '', 'a picture with no moment says nothing rather than a false one');
});

test('the title over the kept frame names the real hour and the frame, and never claims the light is the hour\'s', () => {
  const caption = titleKeptCaption({ text: '00:52' }, 'ultimul cadru live · azi 00:47');
  assert.equal(caption, 'Sediul AMN-AI, București · acum 00:52 · ultimul cadru live · azi 00:47');
  assert.doesNotMatch(caption, /lumina reală/);
  assert.doesNotMatch(caption, /\blive ·? ?acum\b/i, 'the frame is never called live now');
});

test('the plaques over the replay carry the books as they stood, marked «atunci»', () => {
  const facts = { treasury: { spendable: { amount: '50000' } }, budget: { today: { prompt_tokens: 1000, completion_tokens: 234 } }, replay: true };
  const treasury = plaqueWords('treasury_board', facts);
  assert.equal(treasury.eyebrow, 'TREZORERIE · ATUNCI');
  assert.equal(treasury.value, '50.000 VR$ cheltuibili');
  assert.equal(plaqueWords('infra_plate', facts).value, '1.234 de tokenuri atunci');
  const live = plaqueWords('treasury_board', { ...facts, replay: false });
  assert.equal(live.eyebrow, 'TREZORERIE');
  assert.equal(plaqueWords('infra_plate', { ...facts, replay: false }).value, '1.234 de tokenuri azi');
  assert.notEqual(treasury.key, live.key, 'the plaque is rewritten when the replay starts');
});

/* --------------------------------------------------------------------------- the anchors -- */

test('every overlay is anchored where the photograph shows its object, near the manifest the building was built to', () => {
  for (const [zone, [x, y, w, h]] of Object.entries(STREAM_ROOMS)) {
    const m = MANIFEST.rooms[zone];
    assert.ok(m, zone);
    for (const [a, b] of [[x, m.x], [y, m.y], [x + w, m.x + m.w], [y + h, m.y + m.h]]) assert.ok(Math.abs(a - b) <= 13, `${zone}: ${a} vs ${b}`);
  }
  for (const [desk, zone] of Object.entries(STREAM_SEATED)) {
    assert.equal(MANIFEST.seats[desk].zone, zone, desk);
    const monitor = MANIFEST.screens[`${desk}_monitor`].rect;
    const [mx, my] = STREAM_MONITORS[desk];
    assert.ok(Math.hypot(mx - (monitor[0] + monitor[2] / 2), my - (monitor[1] + monitor[3] / 2)) < 11, desk);
    const [rx, ry, rw, rh] = STREAM_ROOMS[zone];
    assert.ok(mx > rx && mx < rx + rw && my > ry && my < ry + rh, `${desk}'s monitor is in its room`);
  }
  assert.equal(Object.keys(STREAM_MONITORS).length, Object.keys(MANIFEST.seats).length, 'a glow for every desk');
  // the photograph's shelter clock shows the live hour: the ATUNCI face covers all of the manifest's
  const [cx, cy, cw, ch] = STREAM_SHELTER_CLOCK;
  const [mx, my, mw, mh] = MANIFEST.street.shelter_clock.rect;
  assert.ok(cx <= mx && cy <= my && cx + cw >= mx + mw && cy + ch >= my + mh);
});

/* ------------------------------------------------------------------------- the light -- */

test('a room\'s light over the photograph follows its replayed occupancy, softer by day', () => {
  assert.deepEqual(roomLight('working', 0), { shade: 0, lift: 0.26 });
  assert.deepEqual(roomLight('working', 1), { shade: 0, lift: 0.12 });
  assert.deepEqual(roomLight('empty', 0), { shade: 0.5, lift: 0 });
  assert.ok(roomLight('present', 0).shade < roomLight('empty', 0).shade);
});

test('the light rises and falls over ROOM_EASE_MS, and jumps under reduced motion (the same frames, no animation)', () => {
  assert.equal(easeToward(0, 1, 16, true), 1);
  assert.equal(easeToward(0.3, 0.3, 16, false), 0.3);
  assert.equal(easeToward(0, 1, 0, false), 0, 'no time, no step');
  const one = easeToward(0, 1, 16, false);
  assert.ok(one > 0 && one < 0.2, `one frame is a small step (${one})`);
  let v = 0;
  for (let t = 0; t < ROOM_EASE_MS; t += 16) v = easeToward(v, 1, 16, false);
  assert.ok(v > 0.9, `most of the way in ROOM_EASE_MS (${v})`);
  for (let t = 0; t < ROOM_EASE_MS * 3; t += 16) v = easeToward(v, 1, 16, false);
  assert.equal(v, 1, 'and it arrives');
});

test('the rooms\' levels are the replayed employees\', eased from the frame before', () => {
  const zoneOf = (a) => STREAM_SEATED[a.desk_id] || null;
  const working = [{ desk_id: 'desk_script', runtime_state: 'WORKING' }, { desk_id: 'desk_audio', runtime_state: 'IDLE' }];
  const first = roomLevels({}, working, zoneOf, 0, 0, false);
  assert.equal(first.script_room.occupancy, 'working');
  assert.equal(first.script_room.lift, 0.26, 'the first frame starts at the target');
  assert.equal(first.director_suite.occupancy, 'empty');
  assert.equal(first.lobby, undefined, 'a room without a desk takes no light');
  const idle = [{ desk_id: 'desk_script', runtime_state: 'IDLE' }];
  const next = roomLevels(first, idle, zoneOf, 0, 16, false);
  assert.ok(next.script_room.lift < 0.26 && next.script_room.lift > 0.12, 'it falls, not cuts');
  assert.equal(roomLevels(first, idle, zoneOf, 0, 16, true).script_room.lift, 0, 'reduced motion: at once');
});

test('a monitor glows for its employee\'s state then, where the photograph\'s monitor is', () => {
  assert.equal(monitorGlow('dark'), null);
  assert.equal(monitorGlow('error').rgb, '239,68,68');
  assert.ok(monitorGlow('work').strength > monitorGlow('think').strength);
  assert.ok(monitorGlow('think').strength > monitorGlow('idle').strength);
  const glows = monitorGlows([{ desk_id: 'desk_video', runtime_state: 'WORKING' }, { desk_id: 'nowhere', runtime_state: 'WORKING' }]);
  assert.equal(glows.length, 1);
  assert.deepEqual([glows[0].x, glows[0].y], STREAM_MONITORS.desk_video);
  assert.ok(glowBloom(0) > glowBloom(1), 'by day the sun washes a screen');
});

test('the replay plays in the Unreal building only with a stream configured and a real picture in hand', () => {
  assert.ok(replayInUnreal({ configured: true, picture: { width: 1920, height: 1008 } }));
  assert.ok(!replayInUnreal({ configured: false, picture: { width: 1920, height: 1008 } }));
  assert.ok(!replayInUnreal({ configured: true, picture: null }));
  assert.ok(!replayInUnreal({ configured: true, picture: { width: 0, height: 0 } }));
});

/* ------------------------------------------------------------------ the stream's picture -- */

test('the stream hands the replay the picture it holds, with the moment it was taken', () => {
  const s = Object.create(LiveStream.prototype);
  s.still = { width: 1920, height: 1008 };
  s.hasStill = false;
  s.keptShown = false;
  s.stillAt = NaN;
  assert.equal(s.replayPicture(), null, 'no picture, no still');
  s.hasStill = true;
  s.stillAt = 1234;
  assert.deepEqual(s.replayPicture(), { image: s.still, at: 1234 });
  s.hasStill = false;
  s.keptShown = true;
  s.stillAt = 99;
  assert.equal(s.replayPicture().at, 99, 'the kept frame keeps its own moment');
  s.still = { width: 0, height: 0 };
  assert.equal(s.replayPicture(), null);
});

/* ------------------------------------------------------------------------ the renderer -- */

test('over the photograph the renderer draws the still, the light, the ATUNCI clock, the grade, then the words — and no plate', async () => {
  const { HQRenderer } = await import('../src/hq_world.js');
  const calls = [];
  const gradient = { addColorStop() {} };
  const ctx = new Proxy({}, {
    get(target, key) {
      if (key in target) return target[key];
      if (key === 'measureText') return () => ({ width: 10 });
      if (key === 'createLinearGradient') return () => gradient;
      return (...args) => calls.push([key, ...args]);
    },
    set(target, key, value) {
      if (key === 'globalCompositeOperation') calls.push(['composite', value]);
      target[key] = value;
      return true;
    },
  });
  const r = Object.create(HQRenderer.prototype);
  let plates = 0;
  Object.assign(r, {
    world: { time: { state: { text: '23:51' } }, worldW: 1600, worldH: 840 },
    assets: { characters: null, layer: () => { plates += 1; return null; } },
    arrivals: { rooms: () => [], tags: () => [] },
    m: { seats: MANIFEST.seats, rooms: MANIFEST.rooms, street: MANIFEST.street },
    hits: [],
    facts: {},
  });
  const still = { image: { width: 1920, height: 1008 }, daylight: 0 };
  r.drawOverStill(ctx, { agents: [{ desk_id: 'desk_script', runtime_state: 'WORKING', id: 'a' }], bubbles: [], reduced: false, scale: 1, replay: true, still });
  assert.equal(plates, 0, 'no plate is drawn');
  const first = calls.find((c) => c[0] === 'drawImage');
  assert.deepEqual(first, ['drawImage', still.image, 0, 0, 1600, 840], 'the photograph first, over the world\'s rectangle');
  const clock = calls.findIndex((c) => c[0] === 'fillText' && c[1] === 'ATUNCI');
  const hour = calls.findIndex((c) => c[0] === 'fillText' && c[1] === '23:51');
  const grade = calls.findIndex((c) => c[0] === 'composite' && c[1] === 'saturation');
  assert.ok(clock > 0 && hour > clock, 'the photograph\'s live clock is covered by the replayed hour under ATUNCI');
  assert.ok(grade > hour, 'and graded with it');
  const lift = calls.findIndex((c) => c[0] === 'composite' && c[1] === 'lighter');
  assert.ok(lift > 0 && lift < grade, 'the working room\'s light is under the grade');
});

test('the engine plays over its own copy of the still, only in a replay, and composes no plates for it', () => {
  assert.match(ENGINE, /if \(this\.replay && this\.replayStill\) \{[\s\S]*?this\.renderer\.drawOverStill\(ctx,/);
  assert.match(ENGINE, /if \(!this\.replay\) this\.replayStill = null;/);
  assert.match(ENGINE, /if \(this\.stillAhead && this\.stillAhead\(\)\) return true;/);
  assert.match(ENGINE, /setReplayStill\(image, at = Date\.now\(\)\) \{\s+if \(!this\.replay \|\|/);
});

/* --------------------------------------------------------------------------- the page -- */

test('the page plays the replay over the door\'s own frame, and gives the plaques the replayed moment', () => {
  assert.match(MAIN, /liveStream\.doorway\('out'\);[\s\S]{0,300}enterReplayLook\(\);/);
  assert.match(MAIN, /const picture = liveStream \? liveStream\.replayPicture\(\) : null;/);
  assert.match(MAIN, /officeEngine\.setReplayStill\(picture\.image, picture\.at\)/);
  assert.match(MAIN, /viewport\.dataset\.replayLook = over \? 'unreal' : 'page';/);
  assert.match(MAIN, /const overStill = replaying\(\) && Boolean\(officeEngine && officeEngine\.replayStill\);/);
  assert.match(MAIN, /facts: world \? world\.facts : worldFacts/);
  assert.match(SCENE_CSS, /\.stream-plaques\[data-replay\] \.stream-plaque-eyebrow \{ color: var\(--replay-ink\); \}/);
});

test('the title stands on the kept frame only with the stream configured, waits for it briefly, and loads no plates then', () => {
  // W24: this browser's frame or the studio's, by the hour's light (studio_frame.test.js)
  assert.match(MAIN, /if \(!liveStreamSettings\(scene\)\.enabled\) return null;\r?\n  return chooseTitleFrame\(\[browser, studio\], Date\.now\(\)\);/);
  assert.match(MAIN, /kept: titleChoice,/);
  assert.match(TITLE, /export const KEPT_WAIT_MS = (\d+);/);
  assert.ok(Number(TITLE.match(/export const KEPT_WAIT_MS = (\d+);/)[1]) <= 800, 'the title never waits long for it');
  const relight = TITLE.slice(TITLE.indexOf('  relight() {'), TITLE.indexOf('  /** @param {HTMLElement} film */'));
  assert.ok(relight.indexOf('if (this.kept) {') > 0 && relight.indexOf('if (this.kept) {') < relight.indexOf('this.load('), 'the plates are not downloaded under a kept frame');
  assert.match(STYLE, /\.title-kept \{ position: absolute; left: 0; top: 0; display: block; width: 1600px; height: 840px; transform-origin: 0 0;/);
  assert.match(STYLE, /\.title-stage\[data-kept='true'\] \.title-world \{ display: none; \}/);
});

/* ------------------------------------------------------------------------- the landing -- */

test('the kept frame stands on the title as the plates\' world does, moved by its share of the pointer', () => {
  const frame = titleFrame(1920, 1080);
  assert.deepEqual(keptPlacement(frame, { x: 0, y: 0 }), { x: frame.x, y: frame.y, scale: frame.scale });
  const moved = keptPlacement(frame, { x: 10, y: -4 });
  assert.equal(moved.x, frame.x + 10 * KEPT_DEPTH);
  assert.equal(moved.y, frame.y - 4 * KEPT_DEPTH);
});

test('the entry lands the frame exactly where the workspace lays the stream\'s video (the engine\'s world rectangle)', () => {
  const box = { left: 0, top: 64, width: 1920, height: 1016 };
  const view = { zoom: 2.3, panX: 310, panY: 120, dpr: 2, worldW: WORLD.width };
  const land = landingPlacement(box, view);
  // world (0, 0) is at the canvas's (panX, panY) device px; one world px is zoom device px
  assert.deepEqual(land, { x: 155, y: 124, scale: 1.15 });
  assert.equal(placementTransform(land), 'translate3d(155.00px, 124.00px, 0) scale(1.15000)');
  assert.equal(landingPlacement(null, view), null);
  assert.equal(landingPlacement(box, null), null);
  assert.equal(landingPlacement({ ...box, width: 0 }, view), null, 'a workspace not laid out yet: the old push');
  assert.match(MAIN, /titleScreen\.enter\(titleLanding\)/);
  // read after the title is put away and the render's panel is told not to rise (it missed by the masthead's 64 px)
  assert.match(TITLE, /document\.body\.classList\.remove\('is-title'\);[\s\S]{0,400}document\.body\.classList\.add\('is-landing'\);\s+document\.body\.classList\.add\('is-entering'\);\s+this\.land\(lands && landing \? landing\(\) : null\);/);
  assert.match(STYLE, /body\.is-entering \.title-stage\.lands \{ animation: none; \}/);
  assert.match(TITLE, /\{ duration: ENTRY\.pushMs, easing: ease, fill: 'forwards' \}/);
  assert.match(TITLE, /getPropertyValue\('--kept-dim'\)/, 'dimmed on the way as the plate dims the kept frame');
});

test('a replayed caption over the still is not covered by a plaque: its box is handed to the plaques\' placement', async () => {
  const { HQRenderer } = await import('../src/hq_world.js');
  const gradient = { addColorStop() {} };
  const ctx = new Proxy({}, {
    get(target, key) {
      if (key in target) return target[key];
      if (key === 'measureText') return () => ({ width: 40 });
      if (key === 'createLinearGradient') return () => gradient;
      return () => {};
    },
    set(target, key, value) { target[key] = value; return true; },
  });
  const r = Object.create(HQRenderer.prototype);
  Object.assign(r, {
    world: { time: { state: { text: '23:51' } }, worldW: 1600, worldH: 840 },
    assets: { characters: null, layer: () => null },
    arrivals: { rooms: () => [], tags: () => [] },
    m: { seats: MANIFEST.seats, rooms: MANIFEST.rooms, street: MANIFEST.street },
    hits: [],
    facts: {},
  });
  const agents = [{ id: 'w', desk_id: 'desk_script', runtime_state: 'WORKING' }];
  const bubbles = [{ agentId: 'w', label: 'RELUARE · 23:50:05', lines: ['Am scris un scenariu'], text: 'x' }];
  r.drawOverStill(ctx, { agents, bubbles, reduced: false, scale: 1, replay: true, still: { image: { width: 1920, height: 1008 }, daylight: 0 } });
  assert.equal(r.captionBoxes.length, 1);
  const box = r.captionBoxes[0];
  const seat = MANIFEST.seats.desk_script;
  assert.ok(box.x < seat.x && box.x + box.w > seat.x && box.y + box.h <= seat.y - 42 + 1, 'above the employee it quotes');
  assert.ok(r.captionKey.length > 0);
  // the plates' own replay keeps no boxes (nothing grows there)
  assert.match(WORLD_JS, /draw\(ctx, state\) \{\s+const w = this\.world;\s+\/\/[^\n]*\n\s+this\.captionBoxes = null;/);
  assert.match(MAIN, /for \(const c of officeEngine\.renderer\.captionBoxes \|\| \[\]\)/);
  assert.match(MAIN, /onCaptions: \(\) => layoutPlaques\(\),/);
});

test('under the landing frame the render\'s panel does not rise: it appears where the frame lands', () => {
  assert.match(STYLE, /body\.is-entering\.is-landing \.office-panel \{ animation: panel-appear var\(--dur-fast\) var\(--ease\) both; animation-delay: var\(--dur-push\); \}/);
  assert.match(TITLE, /document\.body\.classList\.add\('is-landing'\);/);
  assert.match(TITLE, /hide\(\) \{\s+this\.stage\.classList\.remove\('lands'\);\s+document\.body\.classList\.remove\('is-landing'\);/);
});
