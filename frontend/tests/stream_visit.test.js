// W18 «a stranger with the real stream»: what the adversary found with the Unreal video in the frame.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { INVITE_RELAYOUT_MS, invitePlacement } from '../src/replay_invite.js';

const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');

// 1920x1080, both drawers open: the room the camera leaves, the building at fit, the card's size
const room = { left: 360, top: 112, right: 1580, bottom: 1020 };
const card = { w: 656, h: 66 };

test('at fit the invitation stands under the building, on the street', () => {
  const spot = invitePlacement({ room, building: { x: 470, y: 150, w: 870, h: 720 }, card });
  assert.ok(spot);
  assert.ok(spot.y >= 150 + 720 * 0.78, 'below the floors of work');
});

test('zoomed in, the invitation moves with the building, and steps aside once no free room is left', () => {
  const fit = invitePlacement({ room, building: { x: 470, y: 150, w: 870, h: 720 }, card });
  // ×1.95 about the frame's centre: L1's floor comes down to y 935, the card goes under it
  const zoomed = { x: 470 - 440, y: 150 - 310, w: 870 * 1.95, h: 720 * 1.95 };
  const moved = invitePlacement({ room, building: zoomed, card });
  assert.ok(fit && moved);
  assert.ok(moved.y > fit.y, 'it follows the building down');
  assert.ok(moved.y >= zoomed.y + zoomed.h * 0.78, 'never over the floors of work');
  // ×3: the floors of work fill the room to its bottom
  const close = { x: 470 - 900, y: 150 - 700, w: 870 * 3, h: 720 * 3 };
  assert.equal(invitePlacement({ room, building: close, card }), null);
});

test('the camera moving asks the invitation to be placed again once it rests, not every frame', () => {
  assert.ok(INVITE_RELAYOUT_MS > 0 && INVITE_RELAYOUT_MS <= 400);
  const onView = MAIN.slice(MAIN.indexOf('onView: (view) => {'), MAIN.indexOf('onView: (view) => {') + 600);
  assert.match(onView, /replayInvite && replayInvite\.shown\) relayoutInviteSoon\(\)/);
  assert.doesNotMatch(onView, /liveStream/, 'the invitation follows the pixel camera directly');
  const soon = MAIN.slice(MAIN.indexOf('function relayoutInviteSoon()'), MAIN.indexOf('function relayoutInviteSoon()') + 400);
  assert.match(soon, /clearTimeout\(inviteRelayoutTimer\)/);
  assert.match(soon, /replayInvite\.relayout\(\)/);
  assert.match(soon, /INVITE_RELAYOUT_MS/);
});

test('the pixel scene uses its own motion control and preserves current-data guards', () => {
  const engine = MAIN.slice(MAIN.indexOf('function buildOfficeEngine()'), MAIN.indexOf('function stagedSceneBox()'));
  assert.match(engine, /reducedMotion: \(\) => !sceneMotion\.enabled\(\)/);
  assert.match(engine, /dataLive: \(\) => presentationLive\(liveSignals/);
  assert.match(engine, /presentationReadable:.*liveSignals.data==='fresh'/);
});


test('the building\'s focus ring stands above the stream, inside the room the drawers leave', () => {
  const css = fs.readFileSync(new URL('../src/office_scene.css', import.meta.url), 'utf8');
  const rule = css.match(/\.scene-viewport:has\(\.office-canvas:focus-visible\)::after \{[^}]*\}/);
  assert.ok(rule, 'a ring drawn by the viewport while the canvas has keyboard focus');
  assert.match(rule[0], /z-index: 3;/, 'over the stream layer (z-index 2)');
  assert.match(rule[0], /left: calc\(var\(--hud-l\)/);
  assert.match(rule[0], /right: calc\(var\(--hud-r\)/);
  assert.match(rule[0], /border: 2px solid var\(--teal\)/);
  assert.match(rule[0], /pointer-events: none/);
});

test('an employee reached by the keyboard under the stream gets the glass card, in the desk card\'s words', async () => {
  const { agentReadout, readoutSentence } = await import('../src/hq_readouts.js');
  const now = Date.parse('2026-09-24T19:30:00Z');
  const agent = { id: 'a1', display_name: 'Sarah (Director)', runtime_state: 'IDLE', lifecycle: 'ACTIVE' };
  const r = agentReadout(agent, { facts: { tasks: { tasks: {} } }, now });
  assert.ok(r);
  assert.equal(r.id, 'agent:a1');
  assert.equal(r.eyebrow, 'ANGAJAT');
  assert.equal(r.value, 'Sarah (Director)');
  assert.equal(r.action, 'Enter: deschide fișa angajatului.');
  assert.equal(r.tone, 'quiet');
  assert.equal(r.poster, false);
  assert.equal(agentReadout({ ...agent, runtime_state: 'WORKING' }, { now }).tone, 'ok');
  assert.equal(agentReadout({ ...agent, runtime_state: 'ERROR' }, { now }).tone, 'alert');
  assert.equal(agentReadout({ ...agent, lifecycle: 'PAUSED', runtime_state: 'WORKING' }, { now }).tone, 'quiet');
  assert.equal(agentReadout(null), null);
  assert.ok(readoutSentence(r).startsWith('angajat. Sarah (Director).'));
  // wired: only while the stream covers the renderer and the world is live (in the replay the ring is seen)
  const engine = fs.readFileSync(new URL('../src/office_engine.js', import.meta.url), 'utf8');
  assert.match(engine, /if \(hit && this\.hitsOnly && !this\.replay\) \{/);
  assert.match(MAIN, /faceReadout\.show\(target, target\.covered \? agentReadout\(agent, \{ facts, now \}\) : null, \{ speech \}\)/);
  const card = fs.readFileSync(new URL('../src/scene_readout.js', import.meta.url), 'utf8');
  assert.match(card, /if \(target\.kind === 'agent' && !readout\) \{/);
  assert.match(card, /this\.speak\(extra\.speech \|\| readoutSentence\(readout\)/, 'the words said stay the ones said before');
});
