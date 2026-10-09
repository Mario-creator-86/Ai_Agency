// «Închide filmul» on the shooting sheet (2026-10-09).
//
// Three old films each waited for his look at one scene, and the day chose no new topic while any
// of them stood. The sheet now carries a button «Închide filmul»: the first press only shows
// «Confirmă închiderea filmului» with what closing does (nothing more is bought for it, what was
// bought stays in the books, its topic no longer holds the studio); the second press posts
// POST /media/storyboards/{id}/close once, with a command id, and the drawer shows the closed film
// or the backend's 409 in its own words. Written before the code.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  BUSY_SEE_BAR,
  CLOSE_FILM,
  CLOSE_FILM_EFFECTS,
  assembleButton,
  closeFilm,
  closeFilmCommand,
  closeFilmHtml,
  closeFilmEffects,
  closeFilmPath,
  redoConfirmHtml,
  redoKey,
  sheetHtml,
  stepButtons,
} from '../src/shooting_sheet.js';
import { escapeHtml } from '../src/html.js';

const SHEET = JSON.parse(fs.readFileSync(new URL('./fixtures/shooting_sheet.json', import.meta.url), 'utf8'));
const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
const ID = SHEET.storyboard_id;
const e = escapeHtml;

const OPEN = { closed: false, closable: true, reason_ro: null, busy: false, closed_by: null, closed_at: null, bought_takes: {}, spent_usd_micros: 0, words_ro: null };
const CLOSED_WORDS = 'Filmul «Nepal» este închis: nimic nu se mai cumpără pentru el; ce s-a cumpărat pentru el (4 imagini; 0,72 USD în registre) rămâne în registre; subiectul lui nu mai ține studioul pe loc, iar rularea următoare alege alt subiect.';
const CLOSED = { closed: true, closable: false, reason_ro: null, closed_by: 'Owner', closed_at: '2026-10-09T10:00:00+00:00', bought_takes: { still: 4 }, spent_usd_micros: 720000, words_ro: CLOSED_WORDS };

/** The fixture with the closure the backend sends. @param {any} closure */
function sheetWith(closure) {
  const s = structuredClone(SHEET);
  s.closure = closure;
  return s;
}

/** The buttons in an HTML string, as {action, text, disabled}. @param {string} html */
function buttonsIn(html) {
  return [...html.matchAll(/<button([^>]*)>([^<]*)<\/button>/g)].map(([, attrs, text]) => ({
    action: (/data-sheet-action="([^"]*)"/.exec(attrs) || [])[1] || '',
    text,
    disabled: /\sdisabled\b/.test(attrs),
  }));
}

test('the first press only arms: the sheet shows «Închide filmul» and nothing else happens', () => {
  const html = closeFilmHtml(sheetWith(OPEN), { escape: e, confirm: null });
  const pressable = buttonsIn(html);
  assert.deepEqual(pressable.map((b) => [b.action, b.text, b.disabled]), [['close-film', 'Închide filmul', false]]);
  assert.ok(!html.includes('Confirmă închiderea filmului'));
});

test('armed, it asks «Confirmă închiderea filmului» and says what closing does', () => {
  const html = closeFilmHtml(sheetWith(OPEN), { escape: e, confirm: CLOSE_FILM });
  const pressable = buttonsIn(html);
  assert.deepEqual(pressable.map((b) => [b.action, b.text]), [
    ['confirm-close-film', 'Confirmă închiderea filmului'],
    ['cancel-step', 'Nu acum'],
  ]);
  assert.equal(CLOSE_FILM_EFFECTS.length, 3);
  assert.match(CLOSE_FILM_EFFECTS[0], /nimic nu se mai cumpără pentru el/i);
  assert.match(CLOSE_FILM_EFFECTS[1], /ce s-a cumpărat rămâne în registre/i);
  assert.match(CLOSE_FILM_EFFECTS[2], /subiectul nu mai ține studioul pe loc/i);
  for (const effect of CLOSE_FILM_EFFECTS) assert.ok(html.includes(e(effect)), effect);
  // another question open on the sheet (a step's) does not arm it
  assert.ok(!closeFilmHtml(sheetWith(OPEN), { escape: e, confirm: 'stills' }).includes('Confirmă închiderea'));
});

test('a film that cannot be closed, or is being bought, says why and cannot be pressed', () => {
  const serial = { ...OPEN, closable: false, reason_ro: '«Ziua 12» este un episod al serialului: un episod nu se închide de aici.' };
  for (const confirm of [null, CLOSE_FILM]) {
    const html = closeFilmHtml(sheetWith(serial), { escape: e, confirm });
    assert.deepEqual(buttonsIn(html).map((b) => [b.action, b.disabled]), [['close-film', true]]);
    assert.ok(html.includes(e(serial.reason_ro)));
  }
  const busy = sheetWith(OPEN);
  busy.in_progress = { holder: 'h', step: 'stills', reason_ro: 'Filmul este deja în lucru: pasul «imaginile» a început acum 3 minute.' };
  const html = closeFilmHtml(busy, { escape: e, confirm: CLOSE_FILM });
  assert.deepEqual(buttonsIn(html).map((b) => [b.action, b.disabled]), [['close-film', true]]);
  assert.ok(html.includes(e(BUSY_SEE_BAR)));
});

test('a closed film shows that it is closed, and no step of it can be pressed', () => {
  const s = sheetWith(CLOSED);
  const html = closeFilmHtml(s, { escape: e, confirm: CLOSE_FILM });
  assert.deepEqual(buttonsIn(html), [], 'nothing to press on a closed film');
  assert.ok(html.includes('Filmul este închis'));
  assert.ok(html.includes(e(CLOSED_WORDS)));
  for (const b of stepButtons(s)) {
    assert.equal(b.disabled, true, b.step);
    assert.match(b.reason_ro, /închis/);
  }
  assert.equal(assembleButton(s).disabled, true);
  // the whole sheet carries it, and an older studio (no closure) shows no button at all
  assert.ok(sheetHtml(s, { escape: e }).includes('Filmul este închis'));
  assert.ok(sheetHtml(sheetWith(OPEN), { escape: e }).includes('data-sheet-action="close-film"'));
  assert.equal(closeFilmHtml(structuredClone(SHEET), { escape: e, confirm: CLOSE_FILM }), '');
});

test('the second press posts the close once, and the drawer says the backend\'s words', async () => {
  assert.equal(closeFilmPath(ID), `/media/storyboards/${ID}/close`);
  assert.deepEqual(closeFilmCommand('c-1'), { schema_version: 1, command_id: 'c-1' });
  const calls = [];
  const api = async (path, options = {}) => {
    calls.push([path, options.method, JSON.parse(options.body)]);
    return { status: 'CLOSED', already_closed: false, words_ro: CLOSED_WORDS };
  };
  const done = await closeFilm(api, { storyboardId: ID, commandId: 'c-1' });
  assert.deepEqual(calls, [[`/media/storyboards/${ID}/close`, 'POST', { schema_version: 1, command_id: 'c-1' }]]);
  assert.equal(done.status, 'CLOSED');
  assert.equal(done.message, CLOSED_WORDS);

  const busy = 'Filmul este deja în lucru: pasul «imaginile» a început acum 3 minute. Filmul nu se închide în timpul unei cumpărări: nimic nu s-a schimbat.';
  const refusing = async () => { throw Object.assign(new Error('409'), { status: 409, detail: { status: 'FILM_BUSY', message: busy } }); };
  const refused = await closeFilm(refusing, { storyboardId: ID, commandId: 'c-2' });
  assert.equal(refused.status, 'REFUSED');
  assert.equal(refused.code, 'FILM_BUSY');
  assert.equal(refused.message, busy);
});

test('main.js arms on the first press and closes only on the confirmation', () => {
  assert.ok(MAIN.includes("action === 'close-film'"), 'the first press');
  const arm = MAIN.slice(MAIN.indexOf("action === 'close-film'"));
  assert.ok(arm.slice(0, 300).includes('CLOSE_FILM'), 'it only arms the confirmation');
  assert.ok(!arm.slice(0, 300).includes('closeFilm('), 'the first press posts nothing');
  assert.ok(MAIN.includes("action === 'confirm-close-film'"), 'the second press');
  const confirm = MAIN.slice(MAIN.indexOf("action === 'confirm-close-film'"));
  assert.ok(confirm.slice(0, 600).includes('closeFilm(api'), 'the confirmation posts the close');
  assert.ok(confirm.slice(0, 600).includes('crypto.randomUUID()'), 'with a command id of its own');
});

test('the close is styled from the page\'s tokens, with no colour literal', () => {
  const block = STYLE.slice(STYLE.indexOf('/* «Închide filmul»'));
  assert.ok(block.length > 0 && STYLE.includes('/* «Închide filmul»'));
  const rules = block.slice(0, block.indexOf('\n\n') > 0 ? block.indexOf('\n\n') : undefined);
  for (const selector of ['.sheet-close', '.sheet-close-closed', '.sheet-close-effects']) assert.ok(rules.includes(selector), selector);
  assert.ok(!/#[0-9a-f]{3,8}\b|rgba?\(/i.test(rules.replace(/\/\*[\s\S]*?\*\//g, '')), 'no colour literal');
});

test('a closed film offers no take to choose and no «Refă» to press', () => {
  const open = sheetHtml(sheetWith(OPEN), { escape: e });
  // the fixture's scene 3 has a paid candidate, and every scene its redo plans
  assert.ok(buttonsIn(open).some((b) => b.action === 'take'), 'an open film offers its takes');
  assert.ok(buttonsIn(open).some((b) => b.action === 'redo' && !b.disabled), 'an open film offers its redos');

  const s = sheetWith(CLOSED);
  const html = sheetHtml(s, { escape: e });
  const buttons = buttonsIn(html);
  assert.deepEqual(buttons.filter((b) => b.action === 'take'), [], 'no «Alege imaginea aceasta» on a closed film');
  const redos = buttons.filter((b) => b.action === 'redo');
  assert.ok(redos.length > 0);
  for (const b of redos) assert.equal(b.disabled, true, b.text);
  assert.ok(html.includes(e('Filmul este închis: pentru el nu se mai cumpără nimic.')));
  // a redo armed before the sheet was read again asks nothing of a closed film
  const armed = redoKey('still', 3);
  assert.notEqual(redoConfirmHtml(sheetWith(OPEN), armed, { escape: e, confirm: armed }), '');
  assert.equal(redoConfirmHtml(s, armed, { escape: e, confirm: armed }), '');
  assert.ok(!sheetHtml(s, { escape: e, confirm: armed }).includes('data-sheet-action="confirm-redo"'));
});

test('the confirmation says what the backend read about the topic', () => {
  const held = { ...OPEN, topic_ro: 'Subiectul lui rămâne în lucru prin filmul mai nou «Nepal, refăcut», deci rularea următoare nu alege alt subiect cât timp acela stă deschis.' };
  assert.deepEqual(closeFilmEffects(held), [CLOSE_FILM_EFFECTS[0], CLOSE_FILM_EFFECTS[1], held.topic_ro]);
  const html = closeFilmHtml(sheetWith(held), { escape: e, confirm: CLOSE_FILM });
  assert.ok(html.includes(e(held.topic_ro)));
  assert.ok(!html.includes(e(CLOSE_FILM_EFFECTS[2])), 'the topic is not said to be freed');
  // an older studio that does not say it keeps the default words
  assert.deepEqual(closeFilmEffects(OPEN), [...CLOSE_FILM_EFFECTS]);
});
