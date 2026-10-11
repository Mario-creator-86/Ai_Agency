import test from 'node:test';
import assert from 'node:assert/strict';
import { privacyWord, publicationBadge } from '../src/dialog_words.js';

// 2026-10-11, the Owner, on a film uploaded the evening before and shown only as «randat ·
// QC: a trecut» in the media list: «Este publicat! Ar trebui să apară asta!».
test('a film uploaded says so on its card, with the visibility YouTube reports', () => {
  assert.equal(publicationBadge({ status: 'PUBLISHED', privacy: 'private' }), 'publicat · privat');
  assert.equal(publicationBadge({ status: 'REMOTE_CONFIRMED', privacy: 'public' }), 'publicat, confirmat de YouTube · public');
  assert.equal(publicationBadge({ status: 'SCHEDULED' }), 'programat');
  assert.equal(privacyWord('unlisted'), 'nelistat');
});

test('a film never uploaded shows no upload at all', () => {
  assert.equal(publicationBadge(null), '');
  assert.equal(publicationBadge(undefined), '');
  assert.equal(publicationBadge({ privacy: 'private' }), '');
});
