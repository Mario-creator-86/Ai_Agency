// THE GAME FRAME IN THE STYLESHEET. The frame is decided in three places that must agree: the
// stylesheet's frame block, the scene's frame block, and drawers.js, which decides where the menu
// stands and which drawers are open. A frame block written for another width would leave the
// drawers opening over a stacked page, or a stacked page with its menu lifted away.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { FRAME_QUERY } from '../src/drawers.js';

const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const SCENE = fs.readFileSync(new URL('../src/office_scene.css', import.meta.url), 'utf8');
const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('the stylesheet, the scene and the drawers share one frame query', () => {
  assert.ok(STYLE.includes(`@media ${FRAME_QUERY} {`), 'style.css has the frame block');
  assert.ok(SCENE.includes(`@media ${FRAME_QUERY} {`), 'office_scene.css has the frame block');
});

test('the frame\'s measures are tokens, declared once in the token block', () => {
  for (const name of ['footer-h', 'frame-h', 'drawer-register', 'drawer-side', 'drawer-rail', 'drawer-glass', 'dur-drawer']) {
    const found = [...STYLE.matchAll(new RegExp(`--${name}:`, 'g'))].length;
    assert.equal(found, 1, `--${name} is declared exactly once`);
  }
  assert.ok(/--frame-h:\s*calc\(100vh - var\(--topbar-h\) - var\(--footer-h\)\)/.test(STYLE), 'the frame is the screen less the masthead and the footer strip');
});

test('a drawer opens and closes by transform only, and under reduced motion at once', () => {
  assert.ok(/:root\[data-register="closed"\] \.ledger-panel \{[^}]*transform: translateX\(-100%\)/s.test(STYLE));
  assert.ok(/:root\[data-side="closed"\] \.governance-panel,\s*:root\[data-side="closed"\] \.modules-panel \{[^}]*transform: translateX\(100%\)/s.test(STYLE));
  const reduced = STYLE.slice(STYLE.lastIndexOf('@media (prefers-reduced-motion: reduce)'));
  assert.ok(reduced.includes('body.is-entering .drawer-rail'), 'no rail arrives under the preference');
});

test('every instrument on the glass stands inside the room the drawers leave', () => {
  for (const rule of [/\.scene-readout-info \{[^}]*left: var\(--hud-l\)/s, /\.scene-readout-live \{[^}]*right: var\(--hud-r\)/s, /\.scene-slate \{[^}]*left: var\(--hud-l\);\s*right: var\(--hud-r\)/s]) {
    assert.ok(rule.test(SCENE), String(rule));
  }
});

test('the rooms, the drawers and their rails keep one id each', () => {
  const ids = ['open-research-btn', 'open-media-btn', 'open-publishing-btn', 'open-workforce-btn', 'open-story-btn', 'open-runbook-btn', 'open-treasury-btn',
    'register-panel', 'governance-panel', 'modules-panel', 'register-rail', 'side-rail', 'register-close', 'side-close', 'topbar-rooms',
    'ledger-count', 'approvals-count', 'modules', 'office-canvas', 'scene-viewport'];
  for (const id of ids) assert.equal((HTML.match(new RegExp(`id="${id}"`, 'g')) || []).length, 1, id);
  // the rails and the close keys say what they control and whether it is open
  for (const id of ['register-rail', 'side-rail', 'register-close', 'side-close']) {
    assert.ok(new RegExp(`id="${id}"[^>]*aria-controls="[^"]+"[^>]*aria-expanded="(true|false)"`).test(HTML), `${id} names what it controls`);
  }
});

test('the slate stays one line in the rooms the frame opens: a short caption below 880px of room', () => {
  const narrow = SCENE.slice(SCENE.indexOf('@container slate (max-width: 879.98px)'));
  const rule = narrow.slice(0, narrow.indexOf('\n}') + 2);
  assert.match(rule, /\.room-caption-long \{ display: none; \}/);
  assert.match(rule, /\.room-caption-short \{ display: inline; \}/);
  assert.doesNotMatch(rule, /flex: 1 0 100%/, 'the caption no longer takes a line of its own there');
  // only a room narrower than any the frame opens (1280 with both drawers: 690px) still folds
  const fold = SCENE.slice(SCENE.indexOf('@container slate (max-width: 619.98px)'));
  assert.match(fold.slice(0, 200), /#room-caption \{ flex: 1 0 100%/);
  assert.ok(1280 - 300 - 290 > 620, 'the narrowest frame room is wider than the fold');
});
