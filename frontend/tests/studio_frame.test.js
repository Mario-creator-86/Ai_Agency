// W24 «the cold first visit in the same building»: the studio keeps the newest real frame of the
// Unreal building, sent rarely by the Owner's signed-in page, and a stranger's title stands on it
// when its light is the light outside now.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  STUDIO_FRAME_URL, STUDIO_SEND_EVERY_MS, TITLE_FRAME_MAX_AGE_MS, chooseTitleFrame, lightMatches, readStudioFrame,
  sendStudioFrame, solarState, studioSendDue,
} from '../src/studio_frame.js';

const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
const TITLE = fs.readFileSync(new URL('../src/title_screen.js', import.meta.url), 'utf8');
const Z = (iso) => Date.parse(iso);

/* ------------------------------------------------------------------------- the sun's states -- */

test('a moment over Bucharest is day, golden hour, twilight or night, and which half of the day', () => {
  // 25.09.2026: sunrise about 07:07, sunset about 19:07 in Bucharest (04:07Z, 16:07Z)
  assert.equal(solarState(Z('2026-09-25T02:00:00Z')), 'night');
  assert.equal(solarState(Z('2026-09-25T03:40:00Z')), 'twilight-morning');
  assert.equal(solarState(Z('2026-09-25T04:30:00Z')), 'golden-morning');
  assert.equal(solarState(Z('2026-09-25T10:00:00Z')), 'day');
  assert.equal(solarState(Z('2026-09-25T15:45:00Z')), 'golden-evening');
  assert.equal(solarState(Z('2026-09-25T16:40:00Z')), 'twilight-evening');
  assert.equal(solarState(Z('2026-09-25T17:30:00Z')), 'night');
});

test('a kept frame stands on the title only in the light it was taken in, and not a day on', () => {
  const now = Z('2026-09-25T21:00:00Z'); // 00:00 in Bucharest, night
  assert.equal(lightMatches(Z('2026-09-25T20:10:00Z'), now), true, 'night, taken 50 min ago');
  assert.equal(lightMatches(Z('2026-09-24T22:00:00Z'), now), true, 'last night, 23 h ago');
  assert.equal(lightMatches(now - TITLE_FRAME_MAX_AGE_MS - 1, now), false, 'older than a day');
  assert.equal(lightMatches(Z('2026-09-25T10:00:00Z'), now), false, 'a noon frame at midnight');
  assert.equal(lightMatches(Z('2026-09-25T16:40:00Z'), now), false, 'an evening twilight at night');
  assert.equal(lightMatches(now + 5 * 60000, now), false, 'a frame from the future is a wrong clock');
  assert.equal(lightMatches(NaN, now), false);
  // the golden hour of the morning is not the evening's: the sun is on the other side
  assert.equal(lightMatches(Z('2026-09-25T04:30:00Z'), Z('2026-09-25T15:45:00Z')), false);
  assert.equal(lightMatches(Z('2026-09-24T15:55:00Z'), Z('2026-09-25T15:45:00Z')), true, 'yesterday\'s evening gold');
});

test('the title takes the newest kept frame whose light matches, the browser\'s or the studio\'s', () => {
  const now = Z('2026-09-25T21:00:00Z');
  const browser = { at: Z('2026-09-25T20:00:00Z'), from: 'browser' };
  const studio = { at: Z('2026-09-25T20:50:00Z'), from: 'studio' };
  const noon = { at: Z('2026-09-25T10:00:00Z'), from: 'browser' };
  assert.equal(chooseTitleFrame([browser, studio], now), studio);
  assert.equal(chooseTitleFrame([studio, browser], now), studio);
  assert.equal(chooseTitleFrame([null, studio], now), studio, 'a cold first visit: the studio\'s frame');
  assert.equal(chooseTitleFrame([noon, studio], now), studio, 'the browser\'s noon frame is not tonight');
  assert.equal(chooseTitleFrame([noon, null], now), null, 'no frame in tonight\'s light: the plates');
  assert.equal(chooseTitleFrame([], now), null);
});

/* ---------------------------------------------------------------------------- the reading -- */

/** @param {number} status @param {Record<string, string>} headers @param {Blob|null} [blob] */
const answer = (status, headers, blob = new Blob([new Uint8Array([1, 2, 3])], { type: 'image/webp' })) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: new Headers(headers),
  blob: async () => blob,
});

test('the title reads the studio\'s frame from its own origin, with no key and nothing in the URL', async () => {
  const seen = [];
  const at = Z('2026-09-25T20:50:00Z');
  const frame = await readStudioFrame(async (url, init) => { seen.push({ url, init }); return answer(200, { 'content-type': 'image/webp', 'x-captured-at': String(at) }); });
  assert.equal(frame.at, at);
  assert.equal(frame.blob.size, 3);
  assert.equal(seen.length, 1);
  assert.equal(seen[0].url, STUDIO_FRAME_URL);
  assert.equal(seen[0].init.headers, undefined, 'no key: the title stands before the sign-in');
});

test('nothing kept, a studio without the route, or anything that is not a timed WebP: the plates', async () => {
  const at = String(Z('2026-09-25T20:50:00Z'));
  assert.equal(await readStudioFrame(async () => answer(204, {}, null)), null, 'nothing kept: an empty answer');
  assert.equal(await readStudioFrame(async () => answer(404, { 'content-type': 'application/json' })), null, 'an older studio without the route');
  assert.equal(await readStudioFrame(async () => answer(405, {})), null);
  // an older studio's page files answer a path they do not have with the page itself
  assert.equal(await readStudioFrame(async () => answer(200, { 'content-type': 'text/html', 'x-captured-at': at })), null);
  assert.equal(await readStudioFrame(async () => answer(200, { 'content-type': 'image/webp' })), null, 'no capture time');
  assert.equal(await readStudioFrame(async () => answer(200, { 'content-type': 'image/webp', 'x-captured-at': 'soon' })), null);
  assert.equal(await readStudioFrame(async () => answer(200, { 'content-type': 'image/webp', 'x-captured-at': at }, new Blob([]))), null);
  assert.equal(await readStudioFrame(async () => { throw new Error('offline'); }), null);
});

/* ---------------------------------------------------------------------------- the sending -- */

test('the Owner\'s page sends a kept frame at most every five minutes, and not to a studio without the route', () => {
  assert.equal(STUDIO_SEND_EVERY_MS, 300000);
  assert.equal(studioSendDue({ supported: true, lastSent: 0 }, 1000), true, 'the first kept frame of a visit');
  assert.equal(studioSendDue({ supported: true, lastSent: 1000 }, 1000 + 60000), false, 'the next kept frame, a minute on');
  assert.equal(studioSendDue({ supported: true, lastSent: 1000 }, 1000 + STUDIO_SEND_EVERY_MS), true);
  assert.equal(studioSendDue({ supported: false, lastSent: 0 }, 1000), false);
});

test('the key goes in a header, the capture time with it, never in the URL', async () => {
  const seen = [];
  const blob = new Blob([new Uint8Array([9, 9])], { type: 'image/webp' });
  const out = await sendStudioFrame(async (url, init) => { seen.push({ url, init }); return { ok: true, status: 201 }; }, 'the-owners-key', { blob, at: 1790000000123.4 });
  assert.equal(out, 'stored');
  assert.equal(seen[0].url, STUDIO_FRAME_URL);
  assert.ok(!seen[0].url.includes('the-owners-key'));
  assert.equal(seen[0].init.method, 'POST');
  assert.equal(seen[0].init.body, blob);
  assert.equal(seen[0].init.headers.Authorization, 'Bearer the-owners-key');
  assert.equal(seen[0].init.headers['Content-Type'], 'image/webp');
  assert.equal(seen[0].init.headers['X-Captured-At'], '1790000000123');
  assert.equal(await sendStudioFrame(async () => ({ ok: false, status: 404 }), 'k', { blob, at: 1 }), 'unsupported');
  assert.equal(await sendStudioFrame(async () => ({ ok: false, status: 405 }), 'k', { blob, at: 1 }), 'unsupported');
  assert.equal(await sendStudioFrame(async () => ({ ok: false, status: 413 }), 'k', { blob, at: 1 }), 'failed');
  assert.equal(await sendStudioFrame(async () => { throw new Error('x'); }, 'k', { blob, at: 1 }), 'failed');
  assert.equal(await sendStudioFrame(async () => ({ ok: true, status: 201 }), '', { blob, at: 1 }), 'failed', 'no key, no send');
});

/* ------------------------------------------------------------------------------ the wiring -- */

test('the page offers the title both kept frames and sends only from the live stream\'s kept frames', () => {
  assert.match(MAIN, /chooseTitleFrame\(\[/);
  assert.match(MAIN, /readStudioFrame\(/);
  // the send rides on the stream's own rare keep (onKeep), never on a frame loop
  const keep = MAIN.slice(MAIN.indexOf('onKeep: (record) =>'), MAIN.indexOf('onKeep: (record) =>') + 900);
  assert.match(keep, /sendStudioFrame\(/);
  assert.match(keep, /studioSendDue\(/);
  // the title gives up a kept frame whose light no longer matches the hour
  assert.match(TITLE, /dropKept\(\)/);
  assert.match(TITLE, /keptStillTrue/);
});
