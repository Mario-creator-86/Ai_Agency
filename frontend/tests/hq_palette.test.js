import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { scenePalette, resetScenePalette, withAlpha } from '../src/hq_palette.js';

/**
 * hq_palette.js arrived with the scene's chrome and had no test. Two things in it can break
 * silently: the written-out copy of the page's tokens, which only the tests can see drift
 * (the running page reads the live values, so a drift is invisible in a browser), and
 * withAlpha, which is the only way the canvas gets a translucent token colour.
 */

const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');

/** The value a custom property is first given in style.css, which is the token block. */
function declaredToken(name) {
  const match = new RegExp(`--${name}:\\s*([^;]+);`).exec(STYLE);
  assert.ok(match, `style.css declares --${name}`);
  return match[1].trim();
}

test('the written-out copy of the tokens still says what style.css says', () => {
  // The file itself states the rule: "if a token named here is edited in style.css it must
  // be edited here too". This is that rule, enforced. Without a document scenePalette()
  // returns exactly the copy, so reading it here reads the copy.
  resetScenePalette();
  const palette = scenePalette();
  const pairs = [
    ['teal', 'teal'],
    ['ink', 'ink'],
    ['ink3', 'ink-3'],
    ['bg', 'bg'],
    ['scene', 'scene'],
    ['sceneDeep', 'scene-deep'],
    ['sceneFrame', 'scene-frame'],
    ['chromeInk', 'scene-chrome-ink'],
    ['chromeMuted', 'scene-chrome-muted'],
    ['chromeEdge', 'scene-chrome-edge'],
    ['surfaceSunk', 'surface-sunk'],
    ['lineStrong', 'line-strong'],
    ['alertInk', 'alert-ink'],
    ['okInk', 'ok-ink'],
    ['warnInk', 'warn-ink'],
    ['gold', 'gold'],
    ['segPending', 'seg-pending'],
    ['segUnrun', 'seg-unrun'],
    ['replayInk', 'replay-ink'],
    ['replayGrade', 'replay-grade'],
    ['replayTone', 'replay-tone'],
  ];
  for (const [key, token] of pairs) {
    assert.equal(
      palette[key],
      declaredToken(token),
      `hq_palette's ${key} and style.css's --${token} have drifted apart`,
    );
  }
  assert.equal(Object.keys(palette).length, pairs.length, 'every name in the palette is checked');
});

test('without a document the palette answers from the copy, and forgetting it is safe', () => {
  resetScenePalette();
  const first = scenePalette();
  const second = scenePalette();
  assert.deepEqual(first, second);
  resetScenePalette();
  assert.deepEqual(scenePalette(), first);
});

test('withAlpha understands the two forms a token can take, and leaves anything else alone', () => {
  assert.equal(withAlpha('#4fd6b4', 0.65), 'rgba(79,214,180,0.65)');
  assert.equal(withAlpha('#FFF', 1), 'rgba(255,255,255,1)');
  assert.equal(withAlpha(' #05080e ', 0.5), 'rgba(5,8,14,0.5)');
  assert.equal(withAlpha('rgb(12, 20, 33)', 0.4), 'rgba(12,20,33,0.4)');
  assert.equal(withAlpha('rgba(12, 20, 33, 0.9)', 0.4), 'rgba(12,20,33,0.4)');
  // A token that becomes something canvas cannot take apart is handed back untouched, so the
  // fill still paints rather than throwing.
  assert.equal(withAlpha('linear-gradient(red, blue)', 0.5), 'linear-gradient(red, blue)');
  assert.equal(withAlpha('rebeccapurple', 0.5), 'rebeccapurple');
});
