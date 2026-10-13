// W29: THE REGISTER'S FILTER CHIPS ARE 26 PX TO THE EYE AND 34 PX TO THE HAND. Their hit area is an
// ::after reaching 4 px above and below. Where the six chips wrap into two rows (the phone, and a
// register drawer under 340 px), the rows must stand at least those two outsets apart, or the first
// row's lower edge is the second row's hit area (measured at 1920: «Toate» had 30 px of its own).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');

const px = (token) => {
  const m = STYLE.match(new RegExp(`--${token}:\\s*(\\d+(?:\\.\\d+)?)px`));
  assert.ok(m, `--${token} is declared in px`);
  return Number(m[1]);
};

test('the chip hit area reaches 4 px above and below', () => {
  const m = STYLE.match(/\.ledger-chip::after \{[^}]*inset:\s*-(\d+)px 0/);
  assert.ok(m, 'the chip has an ::after hit area');
  assert.equal(Number(m[1]), 4);
});

test('wrapped chip rows stand at least the two outsets apart', () => {
  const outset = Number(STYLE.match(/\.ledger-chip::after \{[^}]*inset:\s*-(\d+)px 0/)[1]);
  const rules = [...STYLE.matchAll(/\.ledger-panel \.ledger-filters \{[^}]*flex-wrap: wrap;[^}]*row-gap:\s*var\(--(s\d)\)/g)];
  assert.ok(rules.length >= 2, 'the phone and the narrow register both wrap the chips');
  for (const [, token] of rules) {
    assert.ok(px(token) >= 2 * outset, `row-gap var(--${token}) = ${px(token)} px keeps each row's hit area its own`);
  }
});
