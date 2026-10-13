// W32, THE RELEASE JUDGE'S LIST. The preflight (Rularea zilei → Verificare preliminară) was the one
// surface judged NO: nineteen cards of the backend's paragraphs, passing and failing alike, with API
// routes and scope lists printed at the same weight as the one line that costs the day. It is now a
// game's checklist: the lines that fail first, each one row with its state in words, colour and
// shape and a key to the place in the page that fixes it; the passing lines one quiet row each; every
// detail behind a disclosure. The order, the state and the place are read from the check's code,
// `ok` and `severity`; the backend's sentences are printed as they came.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  BACKEND_DOORS, CHECK_FIX, FIX_PLACES, checkDetailAdds, checklistHtml, fixPlaceOf, preflightChecklist, technicalNote,
} from '../src/readiness.js';
import { streamPortraitSource, portraitWindow } from '../src/roster.js';

const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const SETTINGS = fs.readFileSync(new URL('../src/settings.js', import.meta.url), 'utf8');
const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const escape = (/** @type {unknown} */ s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] || c);

/** The shape of /runbook/preflight on the fresh copy of 25.09 (sentences shortened). */
const PREFLIGHT = {
  status: 'DEGRADED',
  first_stop: null,
  checks: [
    { name: 'stop_autonomy', ok: true, severity: 'BLOCKING', message: 'Autonomia este pornită.', detail: '' },
    { name: 'autonomy_mode', ok: true, severity: 'INFORMATIONAL', message: 'Modul de autonomie este CEO autonom.', detail: '', value: 'AUTONOMOUS_CEO' },
    { name: 'render_engine', ok: true, severity: 'BLOCKING', message: 'FFmpeg disponibil.', detail: 'C:\\ffmpeg.EXE' },
    { name: 'research_sources', ok: true, severity: 'DEGRADING', message: '36 de site-uri autorizate.', detail: '36 de site-uri autorizate. Nu pot fi citite: www.loc.gov' },
    { name: 'image_provider', ok: false, severity: 'DEGRADING', message: 'AMN-AI este ales și verificat pentru Imagini, dar cheia lui lipsește.', detail: '', value: 'READY' },
    { name: 'daily_budget_films', ok: false, severity: 'INFORMATIONAL', message: 'Acum ești în mediul de test.', detail: 'mediul de test: 1.2 USD pe film' },
    { name: 'youtube_upload_access', ok: true, severity: 'BLOCKING', message: '2 sloturi legate.', detail: '' },
    { name: 'model_prices', ok: false, severity: 'DEGRADING', message: 'Modele fără preț pe jetoane la: ollama.', detail: 'ollama:kimi-k3' },
    { name: 'llm_provider', ok: false, severity: 'BLOCKING', message: 'Niciun model disponibil.', detail: '' },
    { name: 'serial_channel', ok: false, severity: 'INFORMATIONAL', message: 'Canalul serialului este legat.', detail: '' },
    { name: 'future_check', ok: false, severity: 'SOMETHING_NEW', message: 'O verificare nouă.', detail: '' },
  ],
};

test('the lines that fail come first: blocking, then degrading, then a severity the page has never heard of', () => {
  const list = preflightChecklist(PREFLIGHT);
  assert.deepEqual(list.attention.map((r) => r.name), ['llm_provider', 'image_provider', 'model_prices', 'future_check']);
  assert.deepEqual(list.notes.map((r) => r.name), ['daily_budget_films', 'serial_channel']);
  assert.deepEqual(list.ok.map((r) => r.name), ['stop_autonomy', 'autonomy_mode', 'render_engine', 'research_sources', 'youtube_upload_access']);
  // the state in words, from the column's own words, and the tone that colours it
  assert.deepEqual(list.attention.map((r) => [r.word, r.tone]), [['BLOCHEAZĂ', 'blocking'], ['DEGRADEAZĂ', 'degrading'], ['DEGRADEAZĂ', 'degrading'], ['SOMETHING_NEW', 'unknown']]);
  assert.equal(list.notes[0].word, 'INFORMATIV');
  assert.equal(list.ok[0].word, 'OK');
});

test('the backend\'s first stop stands first, with its own words as the row\'s eyebrow', () => {
  const list = preflightChecklist({ ...PREFLIGHT, first_stop: 'model_prices' });
  assert.equal(list.attention[0].name, 'model_prices');
  assert.equal(list.attention[0].first, 'Ziua nu ajunge întreagă');
  const blocked = preflightChecklist({ ...PREFLIGHT, first_stop: 'llm_provider' });
  assert.equal(blocked.attention[0].first, 'Primul punct blocant');
  assert.equal(blocked.attention.filter((r) => r.first).length, 1);
});

test('the place that fixes a line is read from its code, and only a failing line carries a key', () => {
  // an older backend (no `place` field) is read by the check's code
  assert.equal(fixPlaceOf({ name: 'image_provider', ok: false }), FIX_PLACES['settings:media']);
  assert.equal(fixPlaceOf({ name: 'llm_provider', ok: false }).label, 'Setări · Furnizori AI');
  assert.equal(fixPlaceOf({ name: 'spending_budget', ok: false }).door, 'autonomy-modal');
  assert.equal(fixPlaceOf({ name: 'image_provider', ok: true }), null);
  // nothing in the page fixes FFmpeg or FFprobe, nor a serial line whose condition is unknown
  for (const name of ['render_engine', 'media_inspection', 'serial_channel']) {
    assert.equal(fixPlaceOf({ name, ok: false }), null, name);
  }
  // W34 (updated on purpose): the model prices have their place in the Treasury now
  assert.equal(fixPlaceOf({ name: 'model_prices', ok: false })?.section, 'autonomy-prices');
  // every place named is one the page has
  for (const key of Object.values(CHECK_FIX)) assert.ok(FIX_PLACES[key], key);
  for (const place of Object.values(FIX_PLACES)) {
    if (place.door.endsWith('-modal')) assert.ok(HTML.includes(`id="${place.door}"`), place.door);
    if (place.section) assert.ok(HTML.includes(`id="${place.section}"`), place.section);
  }
  for (const door of Object.values(BACKEND_DOORS)) if (door.endsWith('-modal')) assert.ok(HTML.includes(`id="${door}"`), door);
});

test("the backend's own place is read first; the computer and the API alone are no place in the page", () => {
  // backend/app/runbook/preflight.py (W32): place, place_label, place_section beside each line
  const budget = { name: 'daily_budget_films', ok: false, place: 'autonomy', place_label: 'Autonomie → Buget și cheltuieli', place_section: 'autonomy-budget' };
  assert.deepEqual(fixPlaceOf(budget), { label: 'Autonomie → Buget și cheltuieli', door: 'autonomy-modal', section: 'autonomy-budget' });
  assert.deepEqual(fixPlaceOf({ name: 'image_provider', ok: false, place: 'settings:media', place_label: 'Setări → Video și sunet', place_section: null }), { label: 'Setări → Video și sunet', door: 'settings', tab: 'media' });
  assert.deepEqual(fixPlaceOf({ name: 'character_references', ok: false, place: 'media', place_label: 'Producție media → Character Bible', place_section: 'media-characters-section' }), { label: 'Producție media → Character Bible', door: 'media-modal', tab: 'characters', section: 'media-characters-section' });
  assert.equal(fixPlaceOf({ name: 'render_engine', ok: false, place: 'machine', place_label: 'calculatorul studioului' }), null);
  // W34 (updated on purpose): a line the W32 backend still calls `not_on_page` opens the page's new control
  assert.equal(fixPlaceOf({ name: 'model_prices', ok: false, place: 'not_on_page', place_label: 'API-ul studioului' })?.door, 'autonomy-modal');
  assert.equal(fixPlaceOf({ name: 'serial_channel', ok: false, code: 'serial_channel.missing', place: 'not_on_page', place_label: 'API-ul studioului' }), null);
  // a line the backend gives no place, even one the page would have guessed a place for
  assert.equal(fixPlaceOf({ name: 'image_provider', ok: false, place: null }), null);
  const html = checklistHtml(preflightChecklist({ checks: [
    { ...budget, severity: 'INFORMATIONAL', message: 'x', technical: { routes: ['PUT /economy/budget'], settings: ['STUDIO_MOTION_BUDGET_USD'], scopes: [], fields: [], answers: [], paths: [] } },
    { name: 'stop_autonomy', ok: false, severity: 'BLOCKING', message: 'y', place: 'autonomy_switch', place_label: 'comutatorul AUTONOMIE' },
  ] }), escape);
  assert.match(html, /data-door="autonomy-modal" data-section="autonomy-budget">Deschide Autonomie → Buget și cheltuieli</);
  assert.match(html, /data-door="autonomy_switch">Arată comutatorul AUTONOMIE</);
  // what the sentence no longer says is the line's tooltip, never printed
  assert.match(html, /title="PUT \/economy\/budget · STUDIO_MOTION_BUDGET_USD"/);
  assert.equal(technicalNote({}), '');
});

test('a detail loses only what repeats the message; the sentences stay as the backend wrote them', () => {
  assert.equal(checkDetailAdds(PREFLIGHT.checks[3]), 'Nu pot fi citite: www.loc.gov');
  assert.equal(checkDetailAdds(PREFLIGHT.checks[0]), '');
  const row = preflightChecklist(PREFLIGHT).attention[1];
  assert.equal(row.message, PREFLIGHT.checks[4].message);
});

test('the checklist\'s markup: groups with counts, a key per fixable failing line, every detail behind «Detalii»', () => {
  const html = checklistHtml(preflightChecklist(PREFLIGHT), escape);
  assert.match(html, /De rezolvat<\/span>\s*<span class="pf-count">4</);
  assert.match(html, /De știut<\/span>\s*<span class="pf-count">2</);
  assert.match(html, /În regulă<\/span>\s*<span class="pf-count">5</);
  // W34 (updated on purpose): model_prices has a key now
  assert.equal((html.match(/class="secondary pf-fix"/g) || []).length, 4); // llm_provider, image_provider, model_prices, daily_budget_films
  assert.match(html, /data-door="settings" data-tab="media">Deschide Setări · Video și sunet</);
  // a passing line is one quiet row; with a detail, a disclosure of its own; a failing line's detail
  // is behind «Detalii»
  assert.equal((html.match(/class="pf-row pf-ok"/g) || []).length, 5);
  assert.equal((html.match(/<details class="pf-row pf-ok"/g) || []).length, 2); // render_engine, research_sources
  assert.match(html, /<summary class="pf-more-key">Detalii<\/summary>\s*<p class="pf-detail">ollama:kimi-k3<\/p>/);
  // the code is data, never a word on the row
  assert.ok(!/>\s*image_provider\s*</.test(html));
  assert.match(html, /data-check="image_provider"/);
  // an empty group is not shown
  const clean = checklistHtml(preflightChecklist({ checks: PREFLIGHT.checks.filter((c) => c.ok) }), escape);
  assert.ok(!clean.includes('De rezolvat'));
  assert.ok(!clean.includes('De știut'));
});

test('the preflight panel prints the checklist and no longer a card per check', () => {
  assert.match(MAIN, /checklistHtml\(preflightChecklist\(data\)/);
  assert.ok(!/runbook-first-stop/.test(MAIN.slice(MAIN.indexOf('async function loadPreflight'), MAIN.indexOf('async function loadSafeMode'))));
  assert.match(MAIN, /function openFixPlace/);
});

test('a portrait over the stream is cut from the real frame at the same world window', () => {
  // the stream's frame is laid exactly over the world (1920x1008 over 1600x840, replay_still.js)
  const win = portraitWindow({ x: 811, y: 171.2 });
  const src = streamPortraitSource(win, { width: 1920, height: 1008 }, { w: 1600, h: 840 });
  assert.deepEqual(src, { sx: 946.8, sy: 148.8, sw: 52.8, sh: 39.6 });
  // a window partly outside the frame is clamped; one wholly outside gives nothing
  assert.deepEqual(streamPortraitSource([-10, -10, 44, 33], { width: 1600, height: 840 }, { w: 1600, h: 840 }), { sx: 0, sy: 0, sw: 34, sh: 23 });
  assert.equal(streamPortraitSource([2000, 10, 44, 33], { width: 1920, height: 1008 }, { w: 1600, h: 840 }), null);
  assert.equal(streamPortraitSource(win, { width: 0, height: 0 }, { w: 1600, h: 840 }), null);
  assert.equal(streamPortraitSource(null, { width: 1920, height: 1008 }, { w: 1600, h: 840 }), null);
});

test('the inspector\'s header wears the portrait; the raw id is a copy key, not a headline fact', () => {
  assert.ok(!/<span class="stat-label">Identificator<\/span>/.test(HTML));
  assert.match(HTML, /id="inspector-portrait"/);
  assert.match(HTML, /id="inspector-copy-id"[^>]*>Copiază identificatorul</);
  assert.match(MAIN, /paintPortrait\(element\('inspector-portrait'\)/);
});

test('Setări keeps a connection\'s stored name in a tooltip, not as a printed line', () => {
  assert.ok(!/settings-card-id/.test(SETTINGS));
  assert.match(SETTINGS, /heading\.title = item\.name|title\.title = item\.name|h3\.title = /);
});

test('the Treasury\'s vendor tile sets the vendor\'s name in its own case', () => {
  assert.match(MAIN, /<span class="stat-label budget-vendor">\$\{escapeHtml\(providerName\(p\.provider\)\)\}/);
  assert.match(STYLE, /\.budget-vendor\s*\{[^}]*text-transform:\s*none/);
});
