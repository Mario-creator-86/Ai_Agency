// PAGE_OWNER_DAY (PAGE-07): the letters the studio wrote to the Owner, in one list he can see. Each
// letter opens its thread; a sheet letter opens the film's sheet; each can be marked resolved.
import test from 'node:test';
import assert from 'node:assert/strict';
import { escapeHtml } from '../src/html.js';
import { inboxHtml, lettersWord, ownerMarkWords, readLetters, resolveCommand } from '../src/owner_inbox.js';

const ID = '3ec1740c-0000-4000-8000-000000000001';
const SHEET_LETTER = {
  id: 'm-1',
  thread_id: 't-1',
  intent: 'ESCALATE',
  from_name: 'Sarah (Director)',
  subject: 'Filmul «Nepal» așteaptă răspunsul tău la pasul imaginilor',
  body_json: { kind: 'owner_shooting_sheet', storyboard_id: ID, sheet_url: `/api/v1/media/storyboards/${ID}/shooting-sheet` },
  body_text: `Foaia de filmare: /api/v1/media/storyboards/${ID}/shooting-sheet`,
  status: 'OPEN',
  created_at: '2026-10-02T05:03:00+00:00',
};

test('the count says letters with the right Romanian plural', () => {
  assert.equal(lettersWord(1), '1 scrisoare');
  assert.equal(lettersWord(2), '2 scrisori');
  assert.equal(lettersWord(13), '13 scrisori');
  assert.equal(lettersWord(20), '20 de scrisori');
  assert.equal(lettersWord(101), '101 scrisori');
  assert.equal(lettersWord(120), '120 de scrisori');
  assert.equal(lettersWord(0), 'nicio scrisoare');
});

test('an empty inbox says so; an unread one says it was not read', () => {
  assert.match(inboxHtml([], { escape: escapeHtml, read: 'ok' }), /Nicio scrisoare nu te așteaptă/);
  assert.match(inboxHtml([], { escape: escapeHtml, read: 'failed' }), /nu au putut fi citite/);
});

test('a letter shows its subject, who wrote, a key to its thread and one to mark it resolved', () => {
  const html = inboxHtml(readLetters({ letters: [SHEET_LETTER] }), { escape: escapeHtml, read: 'ok', timezone: 'UTC' });
  assert.ok(html.includes('Filmul «Nepal» așteaptă'));
  assert.ok(html.includes('Sarah (Director)'));
  assert.ok(html.includes('data-inbox-thread="t-1"'));
  assert.ok(html.includes('data-inbox-resolve="m-1"'));
  assert.ok(html.includes('Marchează rezolvat'));
  // a sheet letter opens the film's sheet, and never prints the API path
  assert.ok(html.includes(`data-sheet-open="${ID}"`));
  assert.ok(html.includes('Deschide foaia de filmare'));
  assert.ok(!html.includes('/api/v1'));
});

test('only open letters are listed, and text written by a model is escaped', () => {
  const letters = readLetters({ letters: [SHEET_LETTER, { ...SHEET_LETTER, id: 'm-2', status: 'RESOLVED' }, { id: 'm-3', subject: '<img src=x>', status: 'OPEN' }] });
  assert.deepEqual(letters.map((l) => l.id), ['m-1', 'm-3']);
  const html = inboxHtml(letters, { escape: escapeHtml, read: 'ok' });
  assert.ok(!html.includes('<img'));
  assert.deepEqual(readLetters(null), []);
});

test('the Owner mark counts requests and letters together', () => {
  assert.equal(ownerMarkWords(0, 0), '');
  assert.equal(ownerMarkWords(1, 0), '1 cerere așteaptă decizia ta');
  assert.equal(ownerMarkWords(0, 13), '13 scrisori te așteaptă');
  assert.equal(ownerMarkWords(1, 1), '1 cerere și 1 scrisoare te așteaptă');
  assert.equal(ownerMarkWords(3, 20), '3 cereri și 20 de scrisori te așteaptă');
});

test('resolving a letter sends his resolution in the route\'s own shape', () => {
  assert.deepEqual(resolveCommand(), { resolution: 'Rezolvat de Proprietar din pagină.' });
  assert.deepEqual(resolveCommand('  Am văzut foaia. '), { resolution: 'Am văzut foaia.' });
});
