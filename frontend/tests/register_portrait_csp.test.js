// The register's portraits must be URLs the page's CSP lets an <img> load (2026-10-12, the Owner:
// «Pozele nu se văd la agent sub oră»). 3d49e9a handed them out as blob: URLs while the backend's
// CSP allows `img-src 'self' data:` only, so every portrait was blocked; the verification page had
// no CSP and the test fixture used a data: URL, so nothing caught it. This pins both sides.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const main = readFileSync(new URL('../src/main.js', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
const backend = readFileSync(new URL('../../backend/app/main.py', import.meta.url), 'utf8');

/** The body of `function registerPortrait`, up to the next top-level function. */
function portraitBody() {
  const start = main.indexOf('function registerPortrait(');
  assert.ok(start >= 0, 'registerPortrait exists');
  const end = main.indexOf('\n}\n', start);
  return main.slice(start, end);
}

test('the register portrait is a data: URL, never a blob: one', () => {
  const body = portraitBody();
  assert.match(body, /toDataURL\('image\/jpeg'/);
  assert.doesNotMatch(body, /createObjectURL|new Blob\(/);
});

test("the backend's CSP lets an <img> load a data: URL", () => {
  const imgSrc = backend.match(/img-src ([^;]*);/);
  assert.ok(imgSrc, 'the CSP names img-src');
  assert.match(imgSrc[1], /(^|\s)data:(\s|$)/);
});
