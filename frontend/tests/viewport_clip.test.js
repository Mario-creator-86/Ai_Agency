// W27, seen by the release judge on the real stream: the Pixel Streaming library places its <video>
// 48 px down the frame and 28 px past its foot, so the frame's box held 28 px more than it shows.
// With `overflow: hidden` that box is still a scroll container: anything that brings a child into
// view (a focus, find-in-page, an automation's hover) scrolled the whole building 28 px up, hid the
// glass readouts under the masthead and left a dark band under the street for the rest of the
// visit. `overflow: clip` shows the same picture and cannot be scrolled by anything.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const SCENE = fs.readFileSync(new URL('../src/office_scene.css', import.meta.url), 'utf8');

test('the game frame clips what lies past its edge and can never be scrolled', () => {
  const rule = SCENE.match(/#office-scene-container \.scene-viewport \{([^}]*)\}/s);
  assert.ok(rule, 'the viewport rule exists');
  const decls = rule[1];
  assert.ok(/overflow:\s*hidden;[\s\S]*overflow:\s*clip;/.test(decls), 'clip after the hidden fallback');
});

test('the plaques\' layer clips too, so no plaque can move the frame', () => {
  assert.ok(/\.scene-viewport \.stream-plaques \{[^}]*overflow: clip;/s.test(SCENE));
});
