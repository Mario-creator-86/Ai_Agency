// THE KEY LIGHT IS THE PICTURE'S, AND IT NEVER COSTS A WORD ITS CONTRAST.
//
// key_light.js takes the sky colour of the frame the visitor is looking at and writes it as the
// page's key light. Two things are held here: the light follows the frame (a dusk sky gives a
// warm light, a noon sky a blue one), and whatever the frame, the faintest text on the page
// ground still reads at 4.5:1 over the ground the light makes at its brightest.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  FAINT_INK,
  GROUND,
  KEY_ALPHA,
  KEY_DEFAULT,
  KEY_MIN_RATIO,
  contrastRatio,
  keyLight,
  keyLightCss,
  meanColour,
} from '../src/key_light.js';

const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');

/** @param {{r:number,g:number,b:number,a:number}} light */
const lit = (light) => GROUND.map((c, i) => c + ([light.r, light.g, light.b][i] - c) * light.a);

test('the constants are the page\'s own tokens', () => {
  const hex = (/** @type {string} */ name) => {
    const m = new RegExp(`--${name}:\\s*#([0-9a-f]{6})`).exec(STYLE);
    assert.ok(m, name);
    return [0, 2, 4].map((i) => parseInt(m[1].slice(i, i + 2), 16));
  };
  assert.deepEqual(GROUND, hex('bg'));
  assert.deepEqual(FAINT_INK, hex('ink-3'));
  const m = /--key-cool:\s*rgba\((\d+), (\d+), (\d+), ([.\d]+)\)/.exec(STYLE);
  assert.ok(m);
  assert.deepEqual([KEY_DEFAULT.r, KEY_DEFAULT.g, KEY_DEFAULT.b, KEY_DEFAULT.a], m.slice(1).map(Number), 'no frame: the light the page always had');
});

test('no frame, no guess: the stylesheet\'s light', () => {
  assert.deepEqual(keyLight(null), KEY_DEFAULT);
});

test('the light takes the frame\'s hue: warm at dusk, blue at noon', () => {
  const dusk = keyLight([208, 128, 108]);
  assert.ok(dusk.r > dusk.b, 'a dusk sky gives a warm light');
  const noon = keyLight([121, 169, 224]);
  assert.ok(noon.b > noon.r, 'a noon sky gives a blue light');
  const night = keyLight([15, 22, 48]);
  assert.ok(night.b > night.r && night.a >= KEY_ALPHA.min, 'a night sky still lights the page a little');
});

test('whatever the frame, the faintest text on the ground keeps 4.5:1', () => {
  let worst = Infinity;
  for (let r = 0; r <= 255; r += 51) {
    for (let g = 0; g <= 255; g += 51) {
      for (let b = 0; b <= 255; b += 51) {
        const light = keyLight([r, g, b]);
        assert.ok(light.a <= KEY_ALPHA.max + 1e-9);
        worst = Math.min(worst, contrastRatio(FAINT_INK, lit(light)));
      }
    }
  }
  assert.ok(worst >= KEY_MIN_RATIO, `worst ${worst.toFixed(2)}:1`);
});

test('a white sky cannot wash the page out', () => {
  const white = keyLight([255, 255, 255]);
  const [, , l] = [white.r, white.g, white.b].map((v) => v / 255);
  assert.ok(Math.max(white.r, white.g, white.b) < 200, `lightness held (${white.r},${white.g},${white.b}) ${l}`);
});

test('the frame is averaged over its visible pixels only', () => {
  assert.equal(meanColour([0, 0, 0, 0, 0, 0, 0, 0]), null, 'nothing drawn: no colour');
  assert.deepEqual(meanColour([10, 20, 30, 255, 30, 40, 50, 255, 255, 255, 255, 0]), [20, 30, 40]);
});

test('the value is quantised, so a frame that barely changed does not repaint the page', () => {
  assert.equal(keyLightCss({ r: 101, g: 102, b: 103, a: 0.1234 }), keyLightCss({ r: 100, g: 103, b: 104, a: 0.12 }));
  assert.equal(keyLightCss({ r: 66, g: 104, b: 168, a: 0.16 }), 'rgba(68, 104, 168, 0.16)');
});
