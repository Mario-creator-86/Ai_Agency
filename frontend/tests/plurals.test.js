// PAGE_SETTINGS_ERRORS (PAGE-18): «1 afirmații verificate», «30 zile», «1 modele disponibile»: raw
// `${n} <plural>` at a dozen call sites. Every count of these words now goes through a helper that
// knows Romanian: the singular for 1, «de» from 20 on (except 101-119, 201-219, …).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { countWords } from '../src/plurals.js';

test('1, 19, 20 and 101 are each said right', () => {
  assert.equal(countWords(1, 'scenă', 'scene'), '1 scenă');
  assert.equal(countWords(19, 'scenă', 'scene'), '19 scene');
  assert.equal(countWords(20, 'scenă', 'scene'), '20 de scene');
  assert.equal(countWords(101, 'scenă', 'scene'), '101 scene');
  assert.equal(countWords(120, 'zi', 'zile'), '120 de zile');
  assert.equal(countWords(0, 'film', 'filme'), '0 filme');
  assert.equal(countWords(1284, 'credit', 'credite'), '1.284 de credite');
  assert.equal(countWords(2.5, 'oră', 'ore'), '2,5 ore');
  assert.equal(countWords(undefined, 'model', 'modele'), '— modele');
});

const FILES = ['main.js', 'settings.js', 'ledger.js', 'hud_charts.js'];
// a template field followed directly by one of the plural nouns the finding named
const RAW = /\$\{[^}]+\}\s+(scene|modele|zile|filme|afirmații|etape)\b/g;
// `${a}/${b} etape` reads «3/20 etape» and hides the count from the helper the same way
const SLASHED = /\$\{[^}]+\}\/\$\{[^}]+\}\s+(scene|modele|zile|filme|afirmații|etape)\b/g;

test('no raw count of these words is left in the page\'s modules', () => {
  const found = [];
  for (const file of FILES) {
    const text = fs.readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8');
    text.split('\n').forEach((line, index) => {
      for (const pattern of [RAW, SLASHED]) {
        pattern.lastIndex = 0;
        if (pattern.test(line)) found.push(`${file}:${index + 1}: ${line.trim().slice(0, 120)}`);
      }
    });
  }
  assert.deepEqual(found, []);
});
