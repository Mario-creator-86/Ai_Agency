// HERO_AUTO_ACCEPT (2026-10-02) — the hero test shot follows the Owner's paid-media rule.
//
// Under his MODE rule the page promised that paid steps «urmează modul studioului», but the hero
// test shot still waited for his look every day. The backend now accepts a hero whose clip QC
// passed when his rule lets the motion through unasked (MODE, or OVER_USD with the motion's cap
// within his amount); under EVERY_PAID_STEP he still looks at it. Each choice says so.

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { PAID_MEDIA_CHOICES } from '../src/owner_controls.js';

const meaning = (/** @type {string} */ value) => PAID_MEDIA_CHOICES.find((c) => c.value === value)?.meaning ?? '';

test('under MODE the meaning says a hero that passes clip QC is accepted without him', () => {
  assert.match(meaning('MODE'), /cadrul de probă inclus/);
  assert.match(meaning('MODE'), /trece controlul clipului, e acceptat fără să te aștepte/);
  assert.match(meaning('MODE'), /dacă nu trece, îl privești tu/);
});

test('under OVER_USD the hero is accepted only when the motion cap is within his amount', () => {
  assert.match(meaning('OVER_USD'), /plafonul restului mișcării e sub sumă/);
  assert.match(meaning('OVER_USD'), /altfel îl privești tu/);
});

test('under EVERY_PAID_STEP he still looks at the hero himself, whatever clip QC said', () => {
  assert.match(meaning('EVERY_PAID_STEP'), /cadrul de probă îl privești tu, chiar dacă a trecut controlul clipului/);
  assert.match(meaning('EVERY_PAID_STEP'), /Narațiunea .* urmează modul studioului/);
});
