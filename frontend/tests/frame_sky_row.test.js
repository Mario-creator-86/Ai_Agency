// W8: THE FRAME'S ROW OF SKY, THE DOCK IN IT, AND THE ORDER THE KEYBOARD WALKS.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { SkyRenderer } from '../src/hq_sky.js';
import { timeOfDay } from '../src/hq_time.js';
import { weatherEffects, normalizeWeather } from '../src/hq_weather.js';
import { mulberry32 } from '../src/hq_world.js';
import { skyTopOf } from '../src/office_engine.js';

const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const SCENE = fs.readFileSync(new URL('../src/office_scene.css', import.meta.url), 'utf8');
const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');

/** A context that records what is filled where. */
function recorder() {
  const calls = [];
  const noop = () => {};
  return {
    calls,
    ctx: new Proxy({ fillRect: (x, y, w, h) => calls.push(['fillRect', x, y, w, h]), createLinearGradient: () => ({ addColorStop: noop }), createRadialGradient: () => ({ addColorStop: noop }) }, {
      get: (target, key) => (key in target ? target[key] : noop),
      set: (target, key, value) => { target[key] = value; return true; },
    }),
  };
}

test('the canvas top lies above the world only when the camera shows sky there', () => {
  assert.equal(skyTopOf({ zoom: 1.15, panY: 48 * 1.0 }), -48 / 1.15);
  assert.equal(skyTopOf({ zoom: 1.2, panY: -30 }), 0, 'a world cut at the top has no sky row');
  assert.equal(skyTopOf({ zoom: 2, panY: 0 }), 0);
});

test('the sky is painted from the canvas top, in one gradient, so the row is the same sky', () => {
  const sky = new SkyRenderer({ worldWidth: 1600, worldHeight: 840, horizonRow: 350, rng: mulberry32(1) });
  const time = timeOfDay(new Date('2026-09-24T09:00:00Z'));
  const fx = weatherEffects(normalizeWeather({ available: false }));
  const { ctx, calls } = recorder();
  sky.drawSky(ctx, time, fx, -42);
  assert.deepEqual(calls[0], ['fillRect', 0, -42, 1600, 882]);
  assert.equal(sky.top, -42, 'rain and snow start from the new top');
  const flat = recorder();
  sky.drawSky(flat.ctx, time, fx);
  assert.deepEqual(flat.calls[0], ['fillRect', 0, 0, 1600, 840], 'without a row, the world rect as before');
});

test('the dock hangs in the sky row, spans the free room as a container, and keeps every key', () => {
  assert.ok(/#office-scene-container \.camera-toolbar \{[^}]*top: 0;[^}]*left: var\(--hud-l\);\s*right: var\(--hud-r\);[^}]*container: dock \/ inline-size;/s.test(SCENE), 'the dock stands at the top of the room');
  assert.ok(!/camera-toolbar \{[^}]*bottom: calc\(var\(--scene-readout\)/s.test(SCENE.slice(SCENE.indexOf('9 THE RENDER AS THE FRAME'))), 'no longer over the street');
  assert.ok(/--hud-top:\s*48px;/.test(STYLE), 'the sky row is a token');
  for (const id of ['stop-toggle', 'environment-toggle', 'zoom-in', 'zoom-out', 'zoom-fit', 'zoom-reset', 'fullscreen-btn', 'exit-fullscreen-btn', 'switch-state', 'environment-state']) {
    assert.equal((HTML.match(new RegExp(`id="${id}"`, 'g')) || []).length, 1, id);
  }
  // a key reduced to its icon still carries its word, for the label and for a screen reader
  assert.ok(/id="zoom-fit"[^>]*>.*<span class="dock-label">Încadrează<\/span>/.test(HTML));
  assert.ok(/id="fullscreen-btn"[^>]*>.*<span class="dock-label">Ecran complet<\/span>/.test(HTML));
});

test('the keyboard walks the frame as the eye reads it: register, render and dock, side drawer', () => {
  const order = ['id="register-panel"', 'id="office-canvas"', 'id="stop-toggle"', 'id="fullscreen-btn"', 'id="side-rail"', 'id="governance-panel"', 'id="studio-readout"', 'id="studio-about-btn"'];
  const at = order.map((needle) => HTML.indexOf(needle));
  assert.ok(at.every((i) => i > 0), 'every landmark is on the page');
  assert.deepEqual([...at].sort((a, b) => a - b), at, 'in that order in the document');
});

test('the Journal opens on the writers room, the closed days after it', () => {
  const dialog = HTML.slice(HTML.indexOf('<dialog id="story-modal"'), HTML.indexOf('</dialog>', HTML.indexOf('<dialog id="story-modal"')));
  assert.ok(dialog.indexOf('id="story-episodes"') < dialog.indexOf('id="story-logs"'));
});
