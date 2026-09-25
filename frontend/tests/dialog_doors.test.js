// W28, THE DOORS FROM THEIR ROOMS. Each dialog grows out of its room on the building and goes back
// into it; its content is read ahead on the menu's hover or focus; its words are a step up the
// scale from 1900 px; the scenes' shared directions are said once; the inspector names a place,
// not a role code; the mail keeps the page's date style.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  DOOR_MIN_SCALE, DOOR_ROOMS, doorKeyframes, doorMove, doorNeedsRead, doorTiming, doorWorldRect, roomOnScreen,
} from '../src/dialog_doors.js';
import { deskPlace, sharedTail, ZONE_PLACE } from '../src/dialog_words.js';
import { when } from '../src/mail_thread.js';
import { STREAM_ROOMS } from '../src/replay_still.js';
import { WALL } from '../src/hq_screens.js';

const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
const MANIFEST = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/manifest.json', import.meta.url), 'utf8'));

test('the move lays the pane exactly over the room, about the pane\'s centre', () => {
  const pane = { x: 240, y: 54, w: 1440, h: 970 };
  const room = { x: 549, y: 336, w: 396, h: 100 };
  const m = doorMove(pane, room);
  assert.ok(m);
  // the pane's centre goes to the room's centre, and its size becomes the room's
  assert.equal(pane.x + pane.w / 2 + m.tx, room.x + room.w / 2);
  assert.equal(pane.y + pane.h / 2 + m.ty, room.y + room.h / 2);
  assert.ok(Math.abs(pane.w * m.sx - room.w) < 1);
  assert.ok(Math.abs(pane.h * m.sy - room.h) < 1);
});

test('a sliver of a room never squeezes the pane to a line, and a room larger than the pane never grows it', () => {
  const m = doorMove({ x: 0, y: 0, w: 1000, h: 1000 }, { x: 10, y: 10, w: 2, h: 5000 });
  assert.equal(m.sx, DOOR_MIN_SCALE);
  assert.equal(m.sy, 1);
  assert.equal(doorMove({ x: 0, y: 0, w: 0, h: 10 }, { x: 0, y: 0, w: 10, h: 10 }), null);
  assert.equal(doorMove({ x: 0, y: 0, w: 10, h: 10 }, null), null);
});

test('a room is put on the page through the camera, and cut to what the visitor sees', () => {
  const view = { zoom: 2, panX: -100, panY: 20 };
  // dpr 2: world 100 → canvas 100 → css 50, offset by the canvas box
  const r = roomOnScreen([100, 50, 200, 40], view, 2, { left: 360, top: 64 }, { left: 0, top: 0, right: 1920, bottom: 1080 });
  assert.deepEqual(r, { x: 410, y: 124, w: 200, h: 40 });
  // under a drawer: only the part between the drawers is the door
  const cut = roomOnScreen([100, 50, 200, 40], view, 2, { left: 360, top: 64 }, { left: 500, top: 0, right: 1920, bottom: 1080 });
  assert.deepEqual(cut, { x: 500, y: 124, w: 110, h: 40 });
  // wholly out of sight: no door from it
  assert.equal(roomOnScreen([100, 50, 200, 40], view, 2, { left: 360, top: 64 }, { left: 700, top: 0, right: 1920, bottom: 1080 }), null);
});

test('every door belongs to a room the building has, and the stream\'s measured rooms stand in while it plays', () => {
  for (const [id, place] of Object.entries(DOOR_ROOMS)) {
    const own = doorWorldRect(id, { rooms: MANIFEST.rooms, streamRooms: STREAM_ROOMS, faces: WALL, stream: false });
    assert.ok(own && own.length === 4 && own[2] > 0 && own[3] > 0, `${id} has a room`);
    const live = doorWorldRect(id, { rooms: MANIFEST.rooms, streamRooms: STREAM_ROOMS, faces: WALL, stream: true });
    if (place.zone) assert.deepEqual(live, STREAM_ROOMS[place.zone], `${id} uses the stream's room`);
  }
  assert.deepEqual(doorWorldRect('research-modal', { rooms: MANIFEST.rooms, stream: false }), [517, 195, 345, 87]);
  assert.equal(doorWorldRect('nowhere', { rooms: MANIFEST.rooms }), null);
  // every door in the page is one of them, and the eyebrows name the same places
  for (const id of ['research-modal', 'media-modal', 'publishing-modal', 'story-modal', 'runbook-modal', 'treasury-modal', 'workforce-modal']) {
    assert.ok(HTML.includes(`<dialog id="${id}"`), id);
  }
  assert.match(HTML, /id="research-modal"[\s\S]{0,300}CERCETARE · L3/);
  assert.match(HTML, /id="treasury-modal"[\s\S]{0,300}TREZORERIE · S2/);
  assert.match(HTML, /id="media-modal"[\s\S]{0,300}RANDARE · L1/);
});

test('the door\'s times are the page\'s tokens; under reduced motion it only fades', () => {
  const tokens = { '--dur-room-open': '340ms', '--dur-room-close': '0.3s', '--dur-room-fade': '180ms', '--ease': 'cubic-bezier(.22, .7, .3, 1)', '--ease-push': 'cubic-bezier(.55, .06, .3, 1)' };
  const t = doorTiming(false, (n) => tokens[n] || '');
  assert.deepEqual(t, { open: 340, close: 300, ease: 'cubic-bezier(.55, .06, .3, 1)', move: true });
  const r = doorTiming(true, (n) => tokens[n] || '');
  assert.equal(r.move, false);
  assert.equal(r.open, 180);
  // the numbers the stylesheet declares are the ones read
  assert.match(STYLE, /--dur-room-open:\s*340ms/);
  assert.match(STYLE, /--dur-room-close:\s*300ms/);
  assert.match(STYLE, /--dur-room-fade:\s*180ms/);
  // a missing token falls back, it never becomes NaN
  assert.equal(doorTiming(false, () => '').open, 340);
});

test('the opening moves only what the compositor moves: nothing is painted again while the door moves', () => {
  const k = doorKeyframes({ tx: -200, ty: -150, sx: 0.27, sy: 0.1 }, false);
  const allowed = new Set(['translate', 'scale', 'opacity', 'offset']);
  for (const frame of [...k.pane, ...k.content, ...k.edge]) {
    for (const key of Object.keys(frame)) assert.ok(allowed.has(key), `only compositor properties: ${key}`);
  }
  assert.equal(k.pane[0].translate, '-200px -150px');
  assert.equal(k.pane[0].scale, '0.27 0.1');
  assert.equal(k.pane.at(-1).scale, '1 1');
  // the words come up only once the pane is half-way (nothing is read squeezed)
  assert.equal(k.content[1].opacity, 0);
  assert.ok(k.content[1].offset >= 0.4);
  const still = doorKeyframes({ tx: 1, ty: 1, sx: 0.5, sy: 0.5 }, true);
  assert.equal(still.edge, null);
  assert.ok(still.pane.every((f) => !('translate' in f) && !('scale' in f)));
});

test('a door read on the hover a moment ago opens on it; an old or unread one reads after it lands', () => {
  assert.equal(doorNeedsRead(undefined, 1000, 10000), true);
  assert.equal(doorNeedsRead(0, 5000, 10000), false);
  assert.equal(doorNeedsRead(0, 10001, 10000), true);
  assert.equal(doorNeedsRead(9000, 5000, 10000), true, 'a clock that went back is not fresh');
  // the seven rooms of the menu read through the doors, not on their own click
  for (const id of ['research-modal', 'media-modal', 'publishing-modal', 'workforce-modal', 'story-modal', 'runbook-modal', 'treasury-modal']) {
    assert.ok(MAIN.includes(`doorReads.set('${id}'`), `${id} has a reader`);
  }
  assert.equal((MAIN.match(/openDoor\(\w+Modal\)/g) || []).length, 7);
  assert.ok(!/researchModal\.showModal\(\);\s*loadTopics/.test(MAIN), 'no read laid out under the moving pane');
});

test('the stylesheet: the exit goes back to the room, reduced motion fades, the lit room and the first frame', () => {
  assert.match(STYLE, /\.studio-dialog\.has-door \{[^}]*translate: var\(--door-tx, 0px\) var\(--door-ty, 8px\);[^}]*scale: var\(--door-sx, \.96\) var\(--door-sy, \.96\)/s);
  assert.match(STYLE, /@starting-style \{ \.studio-dialog\.has-door\[open\] \{ opacity: 1; translate: 0 0; scale: 1 1; \} \}/);
  const reduced = STYLE.slice(STYLE.lastIndexOf('@media (prefers-reduced-motion: reduce)'));
  assert.match(reduced, /:root \.studio-dialog\.has-door,\s*:root \.studio-dialog\.has-door\[open\] \{\s*translate: none;\s*scale: none;/);
  assert.match(STYLE, /\.scene-viewport \.door-light \{[^}]*pointer-events: none;/s);
  assert.ok(HTML.includes('<div id="door-light" class="door-light" aria-hidden="true" hidden></div>'));
  assert.match(STYLE, /\.studio-dialog \.dialog-pane > \*,[^{]*\{\s*content-visibility: auto;/);
});

test('from 1900 px the doors take their own step of the type scale, as tokens', () => {
  const block = STYLE.slice(STYLE.indexOf('W28 — THE DOORS\' TYPE AND READING'));
  assert.match(block, /@media \(min-width: 1900px\) \{\s*\.studio-dialog \{\s*--fs-micro: var\(--dialog-fs-micro\);/);
  const px = (name) => Number((STYLE.match(new RegExp(`--dialog-${name}:\\s*([\\d.]+)px`)) || [])[1]);
  const base = (name) => Number((STYLE.match(new RegExp(`--${name}:\\s*([\\d.]+)px`)) || [])[1]);
  for (const name of ['fs-micro', 'fs-meta', 'fs-body', 'fs-lead', 'fs-h3', 'fs-h2']) assert.ok(px(name) > base(name), `${name} steps up`);
  // one scroll: the lists no longer scroll inside the door
  assert.match(block, /\.studio-dialog \.topics-container \{\s*max-height: none;\s*overflow: visible;/);
});

test('the scenes\' shared directions are said once, word for word; each scene keeps its own words', () => {
  const tail = 'Composition: subject centred in a vertical frame, readable on a phone. Motion: slow, natural movement.';
  const a = `A yellowed page. Camera: medium shot. Lighting: A yellowed page.. ${tail}`;
  const b = `A particle collision. Camera: medium shot. Lighting: A particle collision.. ${tail}`;
  const out = sharedTail([a, b]);
  assert.equal(out.tail, tail);
  assert.deepEqual(out.heads, ['A yellowed page. Camera: medium shot. Lighting: A yellowed page..', 'A particle collision. Camera: medium shot. Lighting: A particle collision..']);
  // nothing is lost: each head and the tail make the prompt again
  assert.equal(`${out.heads[0]} ${out.tail}`, a);
  // one scene, a short common end, or an end that starts mid-sentence: nothing is taken out
  assert.equal(sharedTail([a]).tail, '');
  assert.equal(sharedTail(['one ends the same way.', 'two ends the same way.']).tail, '');
  assert.equal(sharedTail(['alpha and the rest of a long shared ending here', 'beta and the rest of a long shared ending here']).tail, '');
  // two identical prompts: the scene's own words are never emptied
  assert.equal(sharedTail([tail, tail]).tail, '');
});

test('the inspector names the employee\'s place, not a role code; an unseated desk is the headquarters', () => {
  assert.equal(deskPlace(MANIFEST, 'desk_director'), 'DIRECȚIUNE · L4');
  assert.equal(deskPlace(MANIFEST, 'desk_research_1'), 'CERCETARE · L3');
  assert.equal(deskPlace(MANIFEST, 'desk_research_2'), 'VERIFICAREA FAPTELOR · L3');
  assert.equal(deskPlace(MANIFEST, 'nowhere'), 'SEDIUL · ANGAJAȚI');
  assert.equal(deskPlace(null, 'desk_director'), 'SEDIUL · ANGAJAȚI');
  for (const zone of Object.keys(MANIFEST.rooms)) assert.ok(ZONE_PLACE[zone], `${zone} has a place word`);
  assert.ok(!MAIN.includes("(agent.role_name || 'Agent').toUpperCase()"), 'no role code as the eyebrow');
  assert.ok(!/<span>\$\{escapeHtml\(agent\.role_name\)\}<\/span> ·/.test(MAIN), 'no role code under the name');
  const LIVE = fs.readFileSync(new URL('../src/live_window.js', import.meta.url), 'utf8');
  assert.ok(!LIVE.includes('` — ${agent.role_name}`'), 'the live window title is the name alone');
});

test('the mail says its time in the page\'s date style', () => {
  assert.equal(when('2026-09-12T07:37:21Z', 'Europe/Bucharest'), '12.09.2026, 10:37');
  assert.equal(when('', 'Europe/Bucharest'), '');
});
