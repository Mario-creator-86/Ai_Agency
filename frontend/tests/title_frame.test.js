// THE FIRST TEN SECONDS: the title screen's composition, its light and its entry.
//
// The title is the studio's own world behind the sign-in (title_screen.js). What can break it
// without anyone noticing lives in title_frame.js and is held here: a frame that shows the edge
// of the world or cuts the roof, a light that is not the real sun, an entry that plays for a key
// that was not accepted or for a visitor who asked for less motion, and a stylesheet whose entry
// timings drift from the ones the script waits for.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  BUILDING,
  ENTRY,
  KERB_FOOT,
  OVERSCAN,
  PARALLAX_MAX,
  TITLE_LAYERS,
  WORLD,
  entryOrigin,
  entryPlays,
  followPointer,
  parallaxOffset,
  titleCaption,
  titleFrame,
  titleLight,
} from '../src/title_frame.js';

const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const PLATES = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/plates/plates.json', import.meta.url), 'utf8'));

const SCREENS = [
  [1920, 1080],
  [1440, 900],
  [1280, 800],
  [2560, 1440],
  [1366, 768],
  [3440, 1440],
];

test('the frame never shows the edge of the world, whatever the screen', () => {
  for (const [vw, vh] of [...SCREENS, [390, 844], [768, 1024]]) {
    const f = titleFrame(vw, vh);
    assert.ok(f.x <= -OVERSCAN + 1e-6, `${vw}x${vh}: the city runs off the left edge (${f.x})`);
    assert.ok(f.x + WORLD.width * f.scale >= vw + OVERSCAN - 1e-6, `${vw}x${vh}: and off the right edge`);
    assert.ok(f.y + WORLD.height * f.scale >= vh + OVERSCAN - 1e-6, `${vw}x${vh}: the street reaches the bottom`);
  }
});

test('on a wide screen the headquarters stands in the right of the frame, roof and kerb in view', () => {
  for (const [vw, vh] of SCREENS) {
    const f = titleFrame(vw, vh);
    assert.equal(f.layout, 'side');
    const middle = f.building.x + f.building.w / 2;
    assert.ok(middle > vw * 0.55, `${vw}x${vh}: the building's middle (${middle.toFixed(0)}) is right of centre`);
    assert.ok(f.building.x + f.building.w <= vw + 1, `${vw}x${vh}: its right wall is on screen`);
    assert.ok(f.building.y >= vh * 0.08 - 1e-6, `${vw}x${vh}: its roof keeps a band of sky`);
    if (vw / vh < 2) assert.ok(f.y + KERB_FOOT * f.scale <= vh + 1e-6, `${vw}x${vh}: the kerb is on screen`);
  }
});

test('on a narrow, tall screen the building is centred under the words', () => {
  const f = titleFrame(390, 844);
  assert.equal(f.layout, 'stacked');
  const middle = f.building.x + f.building.w / 2;
  assert.ok(Math.abs(middle - 195) < 2, `centred (${middle})`);
  assert.ok(f.building.y > 844 * 0.4, 'standing in the lower part of the screen');
});

test('the layers are the plates the office renderer composites, far to near', () => {
  const names = TITLE_LAYERS.flatMap((l) => l.layers).sort();
  assert.deepEqual(names, Object.keys(PLATES.variants.night).sort(), 'every plate, once');
  assert.deepEqual(names, Object.keys(PLATES.variants.day).sort());
  const depths = TITLE_LAYERS.map((l) => l.depth);
  assert.deepEqual([...depths].sort((a, b) => a - b), depths, 'depth grows toward the viewer');
  assert.equal(WORLD.width, PLATES.world.width);
  assert.equal(WORLD.height, PLATES.world.height);
  const shell = PLATES.variants.night.building_shell;
  assert.deepEqual([BUILDING.x, BUILDING.y, BUILDING.w, BUILDING.h], [shell.x, shell.y, shell.w, shell.h]);
  assert.equal(TITLE_LAYERS.find((l) => l.name === 'building').grade, false, 'the night grade spares the lit building, as the renderer does');
});

test('parallax answers the pointer, within its bound, and is still when the pointer is centred', () => {
  const centre = parallaxOffset({ x: 960, y: 540 }, 1, 1920, 1080);
  assert.ok(Math.abs(centre.x) < 1e-9 && Math.abs(centre.y) < 1e-9, 'no offset at rest');
  const right = parallaxOffset({ x: 1920, y: 540 }, 1, 1920, 1080);
  assert.equal(right.x, -PARALLAX_MAX);
  const far = parallaxOffset({ x: 1920, y: 540 }, 0.1, 1920, 1080);
  assert.ok(Math.abs(far.x) < Math.abs(right.x), 'the far city moves less than the kerb');
  const outside = parallaxOffset({ x: 99999, y: -99999 }, 1, 1920, 1080);
  assert.ok(Math.abs(outside.x) <= PARALLAX_MAX && Math.abs(outside.y) <= PARALLAX_MAX, 'never beyond the bound');
  assert.ok(PARALLAX_MAX < OVERSCAN, 'the overscan covers the full travel');
});

test('the lag arrives and then stops asking for frames', () => {
  let current = { x: 0, y: 0 };
  const target = { x: -14, y: 7 };
  let frames = 0;
  while (current && frames < 1000) {
    const next = followPointer(current, target, 16.7);
    frames += 1;
    if (!next) break;
    current = next;
  }
  assert.ok(frames < 120, `settles within two seconds of frames (${frames})`);
  assert.equal(followPointer(target, target, 16.7), null, 'nothing to do at rest');
});

test('the light is the real Bucharest sun: noon is day, after sunset is dusk, midnight is night', () => {
  const noon = titleLight(new Date('2026-09-24T10:00:00Z')); // 13:00 in Bucharest
  assert.equal(noon.time.phase, 'day');
  assert.ok(noon.dayMix > 0.999, 'full day plates');
  assert.equal(noon.needsNight, false, 'the night plates are not even downloaded');
  assert.equal(noon.grade, 0);
  const dusk = titleLight(new Date('2026-09-24T16:15:00Z')); // 19:15, just after sunset
  assert.equal(dusk.time.phase, 'dusk');
  assert.ok(dusk.dayMix < 0.5, 'dusk is closer to night on the plates, as in the renderer');
  const night = titleLight(new Date('2026-09-24T20:30:00Z')); // 23:30
  assert.equal(night.time.phase, 'night');
  assert.equal(night.dayMix, 0);
  assert.equal(night.needsDay, false, 'a night visit does not download the day plates');
  assert.equal(night.grade, 1, 'the deep-night grade at full strength');
  assert.deepEqual(night.multiply, [0.674, 0.698, 0.779], 'the renderer\'s own multiply, rgba(70,84,130,.45)');
});

test('the entry plays only for an accepted key, on the title, without reduced motion', () => {
  assert.equal(entryPlays({ accepted: true, reducedMotion: false, titleShown: true }), true);
  assert.equal(entryPlays({ accepted: false, reducedMotion: false, titleShown: true }), false, 'a refused key moves nothing');
  assert.equal(entryPlays({ accepted: true, reducedMotion: true, titleShown: true }), false, 'reduced motion: the workspace at once');
  assert.equal(entryPlays({ accepted: true, reducedMotion: false, titleShown: false }), false);
});

test('the camera aims at the middle of the floors, inside the building', () => {
  const f = titleFrame(1920, 1080);
  const o = entryOrigin(f);
  assert.ok(o.x > f.building.x && o.x < f.building.x + f.building.w);
  assert.ok(o.y > f.building.y + f.building.h * 0.3 && o.y < f.building.y + f.building.h * 0.8);
});

/** @param {string} name */
function token(name) {
  const m = new RegExp(`--${name}:\\s*([^;]+);`).exec(STYLE);
  assert.ok(m, `--${name} is declared`);
  return m[1].trim();
}
const ms = (/** @type {string} */ v) => Number(v.replace('ms', ''));

test('the stylesheet plays the entry with the numbers the script waits for, 600-900ms in all', () => {
  assert.equal(ms(token('dur-push')), ENTRY.pushMs);
  assert.equal(ms(token('arrive-first')), ENTRY.firstPanelMs);
  assert.equal(ms(token('arrive-step')), ENTRY.stepMs);
  assert.equal(ms(token('dur-arrive')), ENTRY.panelMs);
  assert.equal(Number(token('push-scale')), ENTRY.pushScale);
  // the last panel is the fifth: masthead, register, render, modules, governance
  assert.equal(ENTRY.totalMs, ENTRY.firstPanelMs + 4 * ENTRY.stepMs + ENTRY.panelMs);
  assert.ok(ENTRY.totalMs >= 600 && ENTRY.totalMs <= 900, `the whole entry is ${ENTRY.totalMs}ms`);
  assert.ok(ENTRY.pushMs <= ENTRY.totalMs);
  for (const name of ['dur-push', 'dur-leave', 'dur-arrive']) {
    const v = ms(token(name));
    assert.ok(v >= 120 && v <= 700, `--${name} ${v}ms is a motion, not a wait`);
  }
});

test('under reduced motion the entry does not play and the layers are not promoted', () => {
  const block = STYLE.slice(STYLE.lastIndexOf('@media (prefers-reduced-motion: reduce)'));
  assert.ok(/body\.is-entering \.title-stage[^{]*\{\s*animation:\s*none/s.test(block), 'no push under the preference');
  assert.ok(block.includes('.title-layer { will-change: auto; }'));
});

test('the title\'s only controls are the key and its button; the stage is decoration', () => {
  const login = HTML.slice(HTML.indexOf('<section id="login"'), HTML.indexOf('</section>', HTML.indexOf('<section id="login"')));
  assert.equal((login.match(/<input\b/g) || []).length, 1, 'one field');
  assert.equal((login.match(/<button\b/g) || []).length, 1, 'one button');
  assert.equal((login.match(/<a\b/g) || []).length, 0, 'no link');
  assert.ok(/<div id="title-stage" class="title-stage" aria-hidden="true">/.test(HTML));
  assert.ok(/<body class="is-title">/.test(HTML), 'the first paint is the title, with no masthead');
});

test('the caption states the one thing the picture claims: the real hour', () => {
  assert.equal(
    titleCaption({ text: '19:15', phase: 'dusk' }),
    'Sediul AMN-AI, București · 19:15 · amurg, în lumina reală a orei',
  );
});
