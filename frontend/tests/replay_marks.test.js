// W23: over the replay in the Unreal building, the plaques step aside for every mark the replay
// draws, not only its captions. The adversary found a plaque (SERVERE) lying over Lyra's replayed tag
// and DISTRIBUȚIE over its room's «acum: …» chip: the renderer handed the plaques its captions only.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
const MANIFEST = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/manifest.json', import.meta.url), 'utf8'));

function recordingCtx() {
  const gradient = { addColorStop() {} };
  return new Proxy({}, {
    get(target, key) {
      if (key in target) return target[key];
      if (key === 'measureText') return () => ({ width: 40 });
      if (key === 'createLinearGradient' || key === 'createRadialGradient') return () => gradient;
      return () => {};
    },
    set(target, key, value) { target[key] = value; return true; },
  });
}

async function stillRenderer({ tags = [], rooms = [] } = {}) {
  const { HQRenderer } = await import('../src/hq_world.js');
  const r = Object.create(HQRenderer.prototype);
  const seat = MANIFEST.seats.desk_script;
  Object.assign(r, {
    world: { time: { state: { text: '23:51' } }, worldW: 1600, worldH: 840 },
    assets: { characters: null, layer: () => null },
    arrivals: { rooms: () => rooms, tags: () => tags },
    m: { seats: MANIFEST.seats, rooms: MANIFEST.rooms, street: MANIFEST.street },
    hits: [],
    facts: {},
  });
  // the photograph has the figures; their hit boxes are what the tag hangs from
  r.drawAgents = function drawAgents() { this.hits = [{ agent: { id: 'w' }, x0: seat.x - 16, y0: seat.y - 60, x1: seat.x + 16, y1: seat.y + 2 }]; };
  return { r, seat };
}

const STILL = { image: { width: 1920, height: 1008 }, daylight: 0 };
const AGENTS = [{ id: 'w', desk_id: 'desk_script', runtime_state: 'WORKING' }];

test('a replayed tag over the still is handed to the plaques, at the place it rests (not where it fades in)', async () => {
  const tag = (strength) => ({ id: 'w', words: 'Marcus (Script Writer) · a terminat · scenariu', strength, age: 1500 });
  const { r, seat } = await stillRenderer({ tags: [tag(1)] });
  r.drawOverStill(recordingCtx(), { agents: AGENTS, bubbles: [], reduced: false, scale: 1, replay: true, still: STILL });
  const tags = r.captionBoxes.filter((b) => b.kind === 'tag');
  assert.equal(tags.length, 1);
  assert.ok(tags[0].y >= seat.y + 2 && tags[0].x < seat.x && tags[0].x + tags[0].w > seat.x, 'under the desk of the employee it names');
  const rest = { ...tags[0] };
  const key = r.captionKey;
  // fading in, it slides; the box the plaques avoid does not, so they are laid once, not every frame
  const fading = await stillRenderer({ tags: [tag(0.4)] });
  fading.r.drawOverStill(recordingCtx(), { agents: AGENTS, bubbles: [], reduced: false, scale: 1, replay: true, still: STILL });
  assert.deepEqual(fading.r.captionBoxes.find((b) => b.kind === 'tag'), rest);
  assert.equal(fading.r.captionKey, key);
});

test('a room\'s «acum: …» chip over the still is handed to the plaques as well', async () => {
  const { r } = await stillRenderer({ rooms: [{ zone: 'script_room', stage: 'script_and_storyboard', strength: 1 }] });
  r.drawOverStill(recordingCtx(), { agents: AGENTS, bubbles: [], reduced: false, scale: 1, replay: true, still: STILL });
  const chips = r.captionBoxes.filter((b) => b.kind === 'chip');
  assert.equal(chips.length, 1);
  assert.ok(chips[0].w > 0 && chips[0].h > 0);
  assert.ok(r.captionKey.length > 0);
});

test('a replayed caption keeps its kind, and under reduced motion (no tags, no chips) only captions are handed on', async () => {
  const { r } = await stillRenderer({ tags: [{ id: 'w', words: 'Marcus · lucrează', strength: 1, age: 0 }], rooms: [{ zone: 'script_room', stage: 'selection', strength: 1 }] });
  const bubbles = [{ agentId: 'w', label: 'RELUARE · 23:50:05', lines: ['Am scris un scenariu'], text: 'x' }];
  r.drawOverStill(recordingCtx(), { agents: AGENTS, bubbles, reduced: true, scale: 1, replay: true, still: STILL });
  assert.deepEqual(r.captionBoxes.map((b) => b.kind), ['caption']);
});

test('the page lays the plaques off every mark the renderer hands it over the replay', () => {
  assert.match(MAIN, /for \(const c of officeEngine\.renderer\.captionBoxes \|\| \[\]\)/);
  assert.doesNotMatch(MAIN, /captionBoxes \|\| \[\]\)\.filter\(/, 'no kind is left out');
});

test('a tag never lies over a replayed caption: it steps sideways, so «RELUARE · hh:mm:ss» stays legible', async () => {
  const inter = (a, b) => Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
  const bubbles = [{ agentId: 'w', label: 'RELUARE · 23:48:32', lines: ['Sarcină reușită: verificarea faptelor ✓'], text: 'x' }];
  const first = await stillRenderer();
  first.r.drawOverStill(recordingCtx(), { agents: AGENTS, bubbles, reduced: false, scale: 1, replay: true, still: STILL });
  const cap = first.r.captionBoxes.find((b) => b.kind === 'caption');
  // an employee on the floor above: the bottom of their desk is where the caption's label is
  const { r } = await stillRenderer({ tags: [{ id: 'u', words: 'Sarah (Director) · lucrează · alegerea subiectului', strength: 1, age: 2000 }] });
  const mid = cap.x + cap.w / 2 - 30;
  const drawAgents = r.drawAgents;
  r.drawAgents = function withAbove(ctx, state) { drawAgents.call(this, ctx, state); this.hits.push({ agent: { id: 'u' }, x0: mid - 16, y0: cap.y - 60, x1: mid + 16, y1: cap.y }); };
  r.drawOverStill(recordingCtx(), { agents: AGENTS, bubbles, reduced: false, scale: 1, replay: true, still: STILL });
  const tag = r.captionBoxes.find((b) => b.kind === 'tag');
  const caption = r.captionBoxes.find((b) => b.kind === 'caption');
  assert.ok(tag && caption);
  assert.equal(inter(tag, caption), 0, 'no overlap');
  assert.equal(tag.y, cap.y + 6, 'still under the desk it names');
  assert.ok(tag.x >= 2 && tag.x + tag.w <= 1600 - 2, 'inside the world');
});

test('tagClear: the nearest free place along the row, inside the world; where there is none, the place asked', async () => {
  const { tagClear } = await import('../src/hq_world.js');
  const cap = { x: 100, y: 0, w: 100, h: 40 };
  assert.equal(tagClear(300, 10, 50, 20, [cap], 0, 1000, 6), 300, 'already clear');
  assert.equal(tagClear(120, 10, 50, 20, [cap], 0, 1000, 6), 44, 'left of it is nearer');
  assert.equal(tagClear(170, 10, 50, 20, [cap], 0, 1000, 6), 206, 'right of it is nearer');
  assert.equal(tagClear(120, 60, 50, 20, [cap], 0, 1000, 6), 120, 'another row: not in the way');
  assert.equal(tagClear(20, 10, 90, 20, [cap], 0, 1000, 6), 4, 'left of it, the nearer side');
  assert.equal(tagClear(20, 10, 95, 20, [cap], 10, 1000, 6), 206, 'no room on the left inside the world: right');
  assert.equal(tagClear(20, 10, 90, 20, [{ x: 0, y: 0, w: 1000, h: 40 }], 0, 1000, 6), 20, 'no free place: as asked');
});

test('two tags on one row do not lie over each other', async () => {
  const inter = (a, b) => Math.max(0, Math.min(a.x + a.w, b.x + b.w) - Math.max(a.x, b.x)) * Math.max(0, Math.min(a.y + a.h, b.y + b.h) - Math.max(a.y, b.y));
  const { r, seat } = await stillRenderer({ tags: [
    { id: 'w', words: 'Marcus (Script Writer) · a terminat · scenariu', strength: 1, age: 2000 },
    { id: 'v', words: 'Vera (Publisher) · a terminat · pregătirea publicării', strength: 1, age: 2000 },
  ] });
  const drawAgents = r.drawAgents;
  r.drawAgents = function withNeighbour(ctx, state) { drawAgents.call(this, ctx, state); this.hits.push({ agent: { id: 'v' }, x0: seat.x + 40, y0: seat.y - 60, x1: seat.x + 72, y1: seat.y + 2 }); };
  r.drawOverStill(recordingCtx(), { agents: AGENTS, bubbles: [], reduced: false, scale: 1, replay: true, still: STILL });
  const [a, b] = r.captionBoxes.filter((x) => x.kind === 'tag');
  assert.ok(a && b);
  assert.equal(inter(a, b), 0);
});
