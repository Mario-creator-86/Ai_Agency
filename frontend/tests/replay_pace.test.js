// W24 «the last rough edges»: the replay's pace keys say what the line beside them says, against
// the same base (the run); the bar never says «11:38 din 11:39» with «rularea s-a încheiat»; the
// OFFICE SERIAL plaque stands only over an episode with a number; two replayed captions spoken in
// the same second by neighbours never lie over each other.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { REPLAY_SPEEDS, ReplayClock, barTick, buildTimeline, paceKeys, quietSpan, rateWords, replayWords } from '../src/day_replay.js';
import { plaqueWords } from '../src/stream_plaques.js';
import { captionPlace } from '../src/hq_world.js';

const FIX = JSON.parse(fs.readFileSync(new URL('./fixtures/replay_runs_2026-09-12.json', import.meta.url), 'utf8'));
const TZ = 'Europe/Bucharest';
const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const PLAYER = fs.readFileSync(new URL('../src/replay_player.js', import.meta.url), 'utf8');

/* ------------------------------------------------------------------------------ the pace -- */

test('each key says the replay\'s pace against the run, the number the line then says', () => {
  const keys = paceKeys(4.37);
  assert.deepEqual(keys.map((k) => k.speed), [...REPLAY_SPEEDS]);
  assert.deepEqual(keys.map((k) => k.label), ['4×', '17×', '70×']);
  assert.deepEqual(keys.map((k) => k.name), ['de 4 ori mai repede decât rularea', 'de 17 ori mai repede decât rularea', 'de 70 de ori mai repede decât rularea']);
  // a run that fits the minute at its own pace
  assert.deepEqual(paceKeys(1).map((k) => k.label), ['1×', '4×', '16×']);
  assert.equal(paceKeys(1)[0].name, 'în timp real');
  // the pressed key and the line agree in the busy record at every key
  const tl = buildTimeline(FIX.complete.run, FIX.complete.events);
  const clock = new ReplayClock(tl);
  const labels = paceKeys(clock.factor);
  for (const [i, speed] of REPLAY_SPEEDS.entries()) {
    clock.setSpeed(speed);
    clock.seek(tl.stages[1].at + 1000);
    assert.equal(clock.segment.quiet, false);
    const line = replayWords(tl, clock.t, { timeZone: TZ, rate: clock.rate, speed }).rate;
    assert.equal(line, labels[i].name, `${speed}: «${labels[i].label}» beside «${line}»`);
    assert.equal(line, rateWords(Number(labels[i].label.replace('×', ''))));
  }
});

test('a quiet stretch says how long it is on the page at this key, not another rate', () => {
  const q = { t0: Date.parse('2026-09-12T20:51:30Z'), t1: Date.parse('2026-09-12T20:58:24Z'), p0: 1000, p1: 3000, quiet: true };
  assert.equal(quietSpan(q, 1), 'trece în 2 s');
  assert.equal(quietSpan(q, 4), 'trece în 0,5 s');
  assert.equal(quietSpan(q, 16), 'trece în 0,1 s');
  assert.equal(quietSpan({ ...q, p1: 1600 }, 1), 'trece în 0,6 s');
  const tl = buildTimeline(FIX.complete.run, FIX.complete.events);
  assert.equal(replayWords(tl, q.t0 + 60000, { timeZone: TZ, rate: 200, quiet: q, speed: 4 }).rate, 'nicio schimbare în registru 23:51:30–23:58:24 · trece în 0,5 s');
});

test('the keys are named for the pace, and the group for what the pace is against', () => {
  assert.match(HTML, /class="replay-speeds" role="group" aria-label="Ritmul reluării, față de rulare"/);
  assert.match(PLAYER, /paceKeys\(/);
});

/* ----------------------------------------------------------------------- the end's words -- */

test('the bar is rewritten whenever its words change, not only when the clock\'s second does', () => {
  // a run that starts at .9 s and lasts 11:39.05: its last moments share the end's clock second
  const start = Date.parse('2026-09-12T20:48:06.900Z');
  const end = start + 699050;
  const tl = { ...buildTimeline(FIX.complete.run, FIX.complete.events), start, end, duration: end - start };
  const before = replayWords(tl, end - 500, { timeZone: TZ });
  const after = replayWords(tl, end, { timeZone: TZ });
  assert.equal(Math.floor((end - 500) / 1000), Math.floor(end / 1000), 'the same second of the clock');
  assert.equal(before.progress, '11:38 din 11:39');
  assert.equal(after.progress, '11:39 din 11:39');
  assert.equal(after.stage, 'rularea s-a încheiat');
  assert.notEqual(barTick(before), barTick(after), 'the stale «11:38 din 11:39» at the end');
  assert.doesNotMatch(PLAYER, /second !== this\.lastSecond/);
});

/* -------------------------------------------------------------------------- the serial plaque -- */

test('OFFICE SERIAL stands only over an episode with a number', () => {
  const episodes = (status, n) => ({ episodes: [{ created_at: '2026-09-12T00:00:00Z', status, title: 'v2', continuity: n === null ? {} : { episode_number: n } }] });
  assert.equal(plaqueWords('writers_screen', { episodes: episodes('DRAFT', null) }), null, 'never «EP — · Ciornă» over the video');
  assert.equal(plaqueWords('writers_screen', { episodes: { episodes: [] } }), null);
  assert.equal(plaqueWords('writers_screen', {}), null, 'not read: nothing to stand for');
  const w = plaqueWords('writers_screen', { episodes: episodes('DRAFT', 3) });
  assert.equal(w.eyebrow, 'OFFICE SERIAL');
  assert.equal(w.value, 'EP 3 · Ciornă');
});

/* ------------------------------------------------------------------------ the captions -- */

test('a caption spoken beside another in the same second stands clear of it, its tail still on the speaker', () => {
  const first = { x: 400, y: 200, w: 180, h: 58 };
  // the neighbour's seat is 90 px along: centred it would lie over the first
  const want = { x: 490 - 90, y: 200, w: 180, h: 58 };
  const placed = captionPlace(want, 490, [first], 2, 1600, 6);
  const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  assert.equal(overlap(placed, first), false);
  assert.ok(placed.tail >= placed.x && placed.tail <= placed.x + placed.w, 'the tail leaves from the box');
  // no neighbour: exactly where it wanted to be
  assert.deepEqual(captionPlace(want, 490, [], 2, 1600, 6), { ...want, tail: 490 });
  // hemmed in along its row: it rises above the other
  const wall = [{ x: 0, y: 200, w: 1600, h: 58 }];
  const up = captionPlace(want, 490, wall, 2, 1600, 6);
  assert.ok(up.y + up.h <= 200 - 6 + 0.001, `${up.y}`);
  assert.equal(overlap(up, wall[0]), false);
  // three in one second along a row: none over another
  const laid = [];
  for (const seat of [400, 470, 540]) {
    const box = captionPlace({ x: seat - 90, y: 200, w: 180, h: 58 }, seat, laid, 2, 1600, 6);
    for (const other of laid) assert.equal(overlap(box, other), false);
    laid.push(box);
  }
});

test('two captions of one second, drawn by the renderer: each label and line in its own type, no box over another', async () => {
  const { HQRenderer } = await import('../src/hq_world.js');
  const MANIFEST = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/manifest.json', import.meta.url), 'utf8'));
  const r = Object.create(HQRenderer.prototype);
  Object.assign(r, { world: { worldW: 1600, worldH: 840 }, m: { seats: MANIFEST.seats }, captionBoxes: [], drawnCaptions: [] });
  const drawn = [];
  const target = { font: '900 40px x' };
  const stack = [];
  const ctx = new Proxy(target, {
    get(t, key) {
      if (key in t) return t[key];
      if (key === 'measureText') return (s) => ({ width: String(s).length * 5 });
      if (key === 'fillText') return (s) => drawn.push({ s: String(s), font: t.font });
      // a canvas's save and restore keep the font, as the real one does
      if (key === 'save') return () => stack.push(t.font);
      if (key === 'restore') return () => { t.font = stack.pop(); };
      return () => {};
    },
    set(t, key, value) { t[key] = value; return true; },
  });
  // Sarah and Aris, neighbours in L4, in the same replayed second
  const seats = Object.entries(MANIFEST.seats).slice(0, 2);
  const agents = seats.map(([desk], i) => ({ id: `a${i}`, desk_id: desk }));
  const bubbles = agents.map((a, i) => ({ agentId: a.id, label: `RELUARE · 23:49:0${i}`, lines: [`Sarcină reușită: pasul ${i} din rularea zilei ✓`] }));
  r.drawBubbles(ctx, { agents, bubbles, scale: 1 });
  for (const b of bubbles) {
    const label = drawn.find((d) => d.s === b.label);
    const line = drawn.find((d) => d.s === b.lines[0]);
    assert.match(label.font, /^700 9\.5px /, `the label «${b.label}» in its own small type`);
    assert.match(line.font, /^600 12px /);
  }
  const caps = r.captionBoxes.filter((b) => b.kind === 'caption');
  assert.equal(caps.length, 2);
  const [a, b] = caps;
  assert.ok(!(a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h), JSON.stringify(caps));
});
