// DECISIONS_WINDOW (2026-10-03): the Owner's own window of decisions. His words: «Dacă sunt
// decizii pe care eu ca owner trebuie să le iau, trebuie să îmi apară un card. Trebuie să am
// propria mea fereastră unde pot să accept sau refuz ce îmi este recomandat sau trimis.»
//
// A «Decizii» key in the top bar with the count of what waits for him opens his window: two tabs
// («Te așteaptă», «Istoric»), one card per question (a paid step, an agent's or the audit's
// recommendation, a letter that asks him something). Each card says what, why, the recommended
// option, each option's effect or cost, who asked and when; «Accept» and «Refuz» with an optional
// note; anything that spends money or changes his policy asks once more before it is sent. The
// fixture is the feed app.decisions produced on a scratch database (fixtures/owner_decision_cards.json).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { escapeHtml } from '../src/html.js';
import {
  DECISION_CARDS_PATH,
  answerCard,
  appliedWords,
  cardHtml,
  confirmWords,
  decideCommand,
  decisionsBadge,
  decisionsButtonLabel,
  needsConfirm,
  placeTab,
  readDecisionFeed,
  refreshesOn,
  sourceWords,
  studioPath,
  windowHtml,
} from '../src/owner_decisions.js';

const FIXTURE = JSON.parse(fs.readFileSync(new URL('./fixtures/owner_decision_cards.json', import.meta.url), 'utf8'));
const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
const WINDOW = fs.readFileSync(new URL('../src/decisions_window.js', import.meta.url), 'utf8');
const STYLE = fs.readFileSync(new URL('../src/owner_decisions.css', import.meta.url), 'utf8');

const feed = () => readDecisionFeed(structuredClone(FIXTURE.feed));
const card = (/** @type {(c: any) => boolean} */ pick) => {
  const found = feed().cards.find(pick) || feed().history.find(pick);
  assert.ok(found, 'the fixture has this card');
  return found;
};
const BUDGET = () => card((c) => c.kind === 'daily_budget');
const RECONNECT = () => card((c) => c.kind === 'reconnect_connection');
const SALE = () => card((c) => c.kind === 'sale_terms');
const STILLS = () => card((c) => c.kind === 'media.stills_purchase' && c.waiting);
const PUBLISH = () => card((c) => c.kind === 'publishing.public_publish');
const LETTER = () => card((c) => c.source_type === 'letter');
const BOARD = '3ec1740c-0000-4000-8000-000000000001';
const o = (/** @type {any} */ extra = {}) => ({ escape: escapeHtml, timezone: 'UTC', ...extra });

/** A fake api: answers in order, records each call; an Error-like answer is thrown. */
function fakeApi(/** @type {any[]} */ answers) {
  const calls = /** @type {{path: string, options: any}[]} */ ([]);
  const api = async (/** @type {string} */ path, /** @type {any} */ options = {}) => {
    calls.push({ path, options: { ...options, body: options.body ? JSON.parse(options.body) : undefined } });
    const next = answers.shift();
    if (next instanceof Error) throw next;
    return next;
  };
  return { api, calls };
}
const apiError = (/** @type {number} */ status, /** @type {string} */ detail) => Object.assign(new Error(detail), { status, detail });

// ------------------------------------------------------------------------------- 1. the feed

test('the feed is read from the route DECISIONS_CORE serves, newest first, with its count', () => {
  assert.equal(DECISION_CARDS_PATH, '/owner/decision-cards');
  const read = feed();
  assert.equal(read.count, 6);
  assert.deepEqual(read.counts, { approvals: 2, decisions: 2, waiting_action: 1, letters: 1 });
  assert.equal(read.cards.length, 6);
  assert.equal(read.history.length, 6);
  const stamps = read.cards.map((c) => c.created_at);
  assert.deepEqual(stamps, [...stamps].sort().reverse());
  assert.ok(read.cards.every((c) => c.waiting));
  assert.ok(read.history.every((c) => !c.waiting));
});

test('a broken or empty answer is an empty window, and a card of an unknown kind is left out', () => {
  assert.deepEqual(readDecisionFeed(null), { cards: [], history: [], count: 0, counts: { approvals: 0, decisions: 0, waiting_action: 0, letters: 0 }, measuredAt: null });
  const odd = readDecisionFeed({ cards: [{ card_id: 'x:1', source_type: 'rumour', title_ro: 'x' }, { title_ro: 'no id' }, ...FIXTURE.feed.cards.slice(0, 1)], count: 1 });
  assert.equal(odd.cards.length, 1);
  // the count is the feed's, never fewer than the cards he can see
  assert.equal(readDecisionFeed({ cards: FIXTURE.feed.cards }).count, 6);
});

// ----------------------------------------------------------------------- 2. the top-bar key

test('the key says how many decisions wait, with the Romanian plural', () => {
  assert.equal(decisionsButtonLabel(0), 'Decizii — nimic nu te așteaptă');
  assert.equal(decisionsButtonLabel(1), 'Decizii — 1 decizie te așteaptă');
  assert.equal(decisionsButtonLabel(3), 'Decizii — 3 decizii te așteaptă');
  assert.equal(decisionsButtonLabel(20), 'Decizii — 20 de decizii te așteaptă');
  assert.equal(decisionsButtonLabel(101), 'Decizii — 101 decizii te așteaptă');
  assert.equal(decisionsBadge(0), '');
  assert.equal(decisionsBadge(3), '3');
  assert.equal(decisionsBadge(120), '99+');
});

test('the key sits in the top bar, opens a dialog, and the page wires the window', () => {
  const right = HTML.slice(HTML.indexOf('class="topbar-right"'), HTML.indexOf('</header>'));
  assert.match(right, /<button id="decisions-button"[^>]*aria-haspopup="dialog"/);
  assert.match(right, /id="decisions-badge"/);
  assert.match(right, />Decizii</);
  assert.ok(MAIN.includes("from './decisions_window.js'"));
  assert.ok(MAIN.includes("import './owner_decisions.css'"));
  // after the key is accepted the key shows; signing out hides it and forgets the window
  const login = MAIN.slice(MAIN.indexOf("element('login-form').addEventListener"), MAIN.indexOf("element('logout').addEventListener"));
  assert.match(login, /decisions\.signedIn\(\)/);
  const logout = MAIN.slice(MAIN.indexOf("element('logout').addEventListener"), MAIN.indexOf('environmentButton.addEventListener'));
  assert.match(logout, /decisions\.reset\(\)/);
  // the events socket refreshes it, and so does the page's own poll
  const socket = MAIN.slice(MAIN.indexOf('const eventsLink = new EventsLink'), MAIN.indexOf('// 2D Office Engine'));
  assert.match(socket, /decisions\.onEvent\(/);
  const refresh = MAIN.slice(MAIN.indexOf('async function refresh()'), MAIN.indexOf("element('login-form').addEventListener"));
  assert.match(refresh, /decisions\.refreshCount\(/);
  // the gold mark in the register opens his window too
  const mark = MAIN.slice(MAIN.indexOf("ownerMark.addEventListener('click'"));
  assert.match(mark.slice(0, 600), /decisions\.open\(/);
});

// ------------------------------------------------------------------------------- 3. a card

test('a recommendation says what, why, who asked and when, with the recommended option first and lit', () => {
  const html = cardHtml(BUDGET(), o());
  assert.ok(html.includes('Studioul nu are un buget zilnic pentru filme'));
  assert.ok(html.includes('Cel mai ieftin film capabil'), 'the why');
  assert.ok(html.includes('Auditul studioului'), 'the source in his words');
  assert.match(html, /<time[^>]*>03\.10\.2026/);
  // each option with its effect, the recommended one marked and chosen by default
  assert.ok(html.includes('Ridic bugetul zilnic la 15 USD'));
  assert.ok(html.includes('Un film întreg, cu plafonul lui, încape într-o zi.'));
  assert.ok(html.includes('Aleg un model mai ieftin sau 720p'));
  assert.match(html, /data-recommended="true"[\s\S]*Recomandat/);
  assert.match(html, /<input type="radio"[^>]*value="raise"[^>]*checked/);
  assert.doesNotMatch(html, /value="cheaper"[^>]*checked/);
  assert.ok(html.indexOf('value="raise"') < html.indexOf('value="cheaper"'), 'recommended first');
  // Accept, Refuz and his optional note, named for a screen reader
  assert.match(html, /data-decision-action="accept"[^>]*>Accept</);
  assert.match(html, /data-decision-action="refuse"[^>]*>Refuz</);
  assert.match(html, /<label[^>]*>[^<]*Nota ta \(opțional\)<textarea[^>]*data-decision-note/);
  assert.ok(!html.includes('/api/v1'), 'never a route on the card');
});

test('the source is said in his words: the audit, an agent, a stage, the requester, the letter writer', () => {
  assert.equal(sourceWords(BUDGET()), 'Auditul studioului');
  assert.equal(sourceWords({ source_type: 'decision', source: 'agent:director' }), 'Directoarea (propunere)');
  assert.equal(sourceWords({ source_type: 'decision', source: 'agent:researcher' }), 'Cercetătorul (propunere)');
  assert.equal(sourceWords({ source_type: 'decision', source: 'stage:media' }), 'Etapa «media» a zilei');
  assert.equal(sourceWords(STILLS()), 'Cerută de Director');
  assert.equal(sourceWords(LETTER()), 'Scrisoare de la Directoarea');
});

test('a model or a source cannot write markup into his window', () => {
  const bad = { ...BUDGET(), title_ro: '<img src=x onerror=alert(1)>', why_ro: '<script>x</script>' };
  bad.options = bad.options.map((/** @type {any} */ opt) => ({ ...opt, label_ro: '<b>x</b>' }));
  const html = cardHtml(bad, o());
  assert.ok(!html.includes('<img'));
  assert.ok(!html.includes('<script'));
  assert.ok(!html.includes('<b>x'));
});

test('an answer in flight disables the card\'s keys', () => {
  const html = cardHtml(BUDGET(), o({ busy: true }));
  assert.ok(!/<button(?![^>]*disabled)[^>]*data-decision-action/.test(html), 'every key disabled');
});

// ----------------------------------------------------------- 4. money and policy ask first

test('an option that spends money or changes his policy asks once more; the rest do not', () => {
  const budget = BUDGET();
  const raise = budget.options.find((/** @type {any} */ x) => x.key === 'raise');
  const cheaper = budget.options.find((/** @type {any} */ x) => x.key === 'cheaper');
  assert.equal(needsConfirm(budget, raise), true, 'a budget');
  assert.equal(needsConfirm(budget, cheaper), false, 'a guided option changes nothing here');
  const mode = { ...budget, options: [{ key: 'mode', label_ro: 'Trec la MODE', effect_ro: 'Pașii plătiți urmează modul.', recommended: true, apply_type: 'paid_media_approval' }] };
  assert.equal(needsConfirm(mode, mode.options[0]), true, 'his paid-media rule');
  for (const type of ['environment', 'autonomy_mode']) assert.equal(needsConfirm(mode, { ...mode.options[0], apply_type: type }), true, type);
  assert.equal(needsConfirm(mode, { ...mode.options[0], apply_type: 'none' }), false);
  assert.equal(needsConfirm(mode, { ...mode.options[0], apply_type: 'record' }), false);
  assert.equal(needsConfirm(PUBLISH(), PUBLISH().options[0]), true, 'an approval lets the studio act');
  assert.equal(needsConfirm(LETTER(), LETTER().options[0]), false);
});

test('the confirmation line names the change and its cost before «Da, aplică»', () => {
  const budget = BUDGET();
  const words = confirmWords(budget, budget.options[0]);
  assert.match(words, /«Ridic bugetul zilnic la 15 USD»/);
  assert.match(words, /comanda ta/);
  const html = cardHtml(budget, o({ confirming: true }));
  assert.match(html, /role="group"[^>]*aria-label="Confirmă decizia"/);
  assert.ok(html.includes(escapeHtml(words)));
  assert.match(html, /data-decision-action="confirm"[^>]*>Da, aplică</);
  assert.match(html, /data-decision-action="cancel"[^>]*>Nu acum</);
  // an approval's line says its cost
  assert.match(confirmWords(PUBLISH(), PUBLISH().options[0]), /Cost: 0\.0 USD/);
});

// -------------------------------------------------------------- 5. paid steps and letters

test('a paid step shows its film\'s sheet: Accept opens the sheet, Refuz goes through the approval route', () => {
  const html = cardHtml(STILLS(), o());
  assert.ok(html.includes('Pas plătit'));
  assert.ok(html.includes('plafon 0.72 USD'), 'the cost');
  assert.ok(html.includes(`data-sheet-open="${BOARD}"`));
  assert.match(html, /pe foaia de filmare, unde sunt scenele, modelele și plafonul/);
  assert.match(html, /foaia aaaaaaaaaaaa/, 'the sheet key he approves');
  // the yes is given on the sheet, where the scenes and the cap are (PAGE-03), never a bare click
  assert.doesNotMatch(html, /data-decision-action="accept"/);
  assert.match(html, /<button[^>]*data-sheet-open="[^"]+"[^>]*>Accept pe foaia de filmare</);
  assert.match(html, /data-decision-action="refuse"[^>]*>Refuz</);
});

test('any other approval is answered in the window, after the confirmation line', () => {
  const html = cardHtml(PUBLISH(), o());
  assert.ok(html.includes('Cerere de aprobare'));
  assert.match(html, /data-decision-action="accept"[^>]*>Accept</);
  assert.doesNotMatch(html, /data-sheet-open/);
});

test('a letter that asks him something offers its own reply and close', () => {
  const html = cardHtml(LETTER(), o());
  assert.ok(html.includes('Scrisoare'));
  assert.ok(html.includes('Reparația foii s-a oprit'));
  assert.ok(html.includes('Am nevoie de tine.'));
  assert.match(html, /<label[^>]*>[^<]*Răspunsul tău<textarea[^>]*data-decision-note/);
  assert.match(html, /data-decision-action="reply"[^>]*>Trimite răspunsul</);
  assert.match(html, /data-decision-action="resolve"[^>]*>Închid scrisoarea</);
  assert.doesNotMatch(html, /data-decision-action="accept"/);
});

// ------------------------------------------------------------------------ 6. guided cards

test('a guided card names its place; a Settings place opens from the card', () => {
  assert.equal(placeTab(RECONNECT().options[0]), 'llm');
  assert.equal(placeTab({ place_ro: 'Setări → Video și sunet' }), 'media');
  assert.equal(placeTab({ place: 'social' }), 'social');
  assert.equal(placeTab({ place_ro: 'fișierul .env al studioului' }), null);
  const pending = cardHtml(RECONNECT(), o());
  assert.ok(pending.includes('Setări → Furnizori AI'));
  assert.match(pending, /Accept deschide locul/);
  // once he accepted, it waits for him: «Deschide locul» and «Am făcut-o»
  const waiting = { ...RECONNECT(), status: 'WAITING_FOR_OWNER_ACTION', status_ro: 'în așteptarea acțiunii tale', version: 2, chosen_option: 'reconnect', applied: { type: 'guided', place: 'llm', place_ro: 'Setări → Furnizori AI', steps_ro: 'Pune cheia nouă.' }, answer: { ...RECONNECT().answer, done: 'DONE' } };
  const html = cardHtml(waiting, o());
  assert.ok(html.includes('în așteptarea acțiunii tale'));
  assert.ok(html.includes('Pune cheia nouă.'));
  assert.match(html, /data-decision-action="place"[^>]*data-decision-place="llm"[^>]*>Deschide locul</);
  assert.match(html, /data-decision-action="done"[^>]*>Am făcut-o</);
  assert.match(html, /data-decision-action="refuse"/);
  assert.doesNotMatch(html, /data-decision-action="accept"/);
});

test('a waiting card whose place is not in Settings says where, without a dead key', () => {
  const html = cardHtml(SALE(), o());
  assert.ok(html.includes('rădăcina proiectului: LICENSE și EULA.md'));
  assert.ok(html.includes('Alege licența'));
  assert.doesNotMatch(html, /data-decision-action="place"/);
  assert.match(html, /data-decision-action="done"[^>]*>Am făcut-o</);
});

// ------------------------------------------------------------------------- 7. his answers

test('his accept goes to the card\'s own route, with its version and only the fields it takes', async () => {
  const budget = BUDGET();
  assert.deepEqual(decideCommand({ decision: 'ACCEPT', version: 1, commandId: 'c-1', optionKey: 'raise' }), { command_id: 'c-1', expected_version: 1, decision: 'ACCEPT', option_key: 'raise' });
  assert.deepEqual(decideCommand({ decision: 'REFUSE', version: 3, commandId: 'c-2', note: '  Mai târziu. ' }), { command_id: 'c-2', expected_version: 3, decision: 'REFUSE', note: 'Mai târziu.' });
  const answer = structuredClone(FIXTURE.accept_answer);
  const { api, calls } = fakeApi([answer]);
  const result = await answerCard(api, budget, { decision: 'ACCEPT', optionKey: 'raise', commandId: 'c-3' });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, `/owner/decisions/${budget.id}/decide`);
  assert.equal(calls[0].options.method, 'POST');
  assert.deepEqual(calls[0].options.body, { command_id: 'c-3', expected_version: 1, decision: 'ACCEPT', option_key: 'raise' });
  assert.equal(result.status, 'DONE');
  assert.match(result.message, /Aplicat prin comanda ta/);
  assert.equal(result.reload, true);
});

test('a guided accept says it waits for him and names the place to open', async () => {
  const reconnect = RECONNECT();
  const answer = { command_id: 'c', status: 'COMMITTED', decision: { ...reconnect, status: 'WAITING_FOR_OWNER_ACTION', applied: { type: 'guided', place: 'llm', place_ro: 'Setări → Furnizori AI', steps_ro: 'Pune cheia nouă.' } } };
  const { api } = fakeApi([answer]);
  const result = await answerCard(api, reconnect, { decision: 'ACCEPT', commandId: 'c' });
  assert.equal(result.status, 'WAITING');
  assert.equal(result.place, 'llm');
  assert.match(result.message, /Setări → Furnizori AI/);
});

test('a stale card reloads, a failed apply says his reason, and nothing else is guessed', async () => {
  const budget = BUDGET();
  const stale = await answerCard(fakeApi([apiError(409, 'Cardul s-a schimbat.')]).api, budget, { decision: 'ACCEPT', commandId: 'c' });
  assert.deepEqual(stale, { status: 'STALE', reload: true, message: 'Cardul s-a schimbat.', place: null });
  const failed = await answerCard(fakeApi([apiError(422, 'Politica studioului s-a schimbat chiar acum; nu s-a aplicat nimic.')]).api, budget, { decision: 'ACCEPT', commandId: 'c' });
  assert.equal(failed.status, 'FAILED');
  assert.equal(failed.reload, true);
  assert.match(failed.message, /nu s-a aplicat nimic/);
  const gone = await answerCard(fakeApi([apiError(404, 'Cardul nu există.')]).api, budget, { decision: 'REFUSE', commandId: 'c' });
  assert.equal(gone.status, 'GONE');
  const network = await answerCard(fakeApi([Object.assign(new Error('Conexiunea nu este disponibilă.'), { network: true })]).api, budget, { decision: 'REFUSE', commandId: 'c' });
  assert.equal(network.status, 'FAILED');
  assert.equal(network.reload, true);
});

test('an approval is answered through the existing approval route; a paid step\'s yes is never sent from here', async () => {
  const publish = PUBLISH();
  const { api, calls } = fakeApi([{ status: 'COMMITTED' }, { status: 'COMMITTED' }]);
  const yes = await answerCard(api, publish, { decision: 'ACCEPT', commandId: 'c-1', note: 'Da.' });
  assert.equal(calls[0].path, '/owner/approvals/decision');
  assert.deepEqual(calls[0].options.body, { schema_version: 1, command_id: 'c-1', approval_id: publish.id, decision: 'APPROVED', note: 'Da.' });
  assert.equal(yes.status, 'DONE');
  await answerCard(api, STILLS(), { decision: 'REFUSE', commandId: 'c-2' });
  assert.deepEqual(calls[1].options.body, { schema_version: 1, command_id: 'c-2', approval_id: STILLS().id, decision: 'REFUSED' });
  const quiet = fakeApi([]);
  const sheet = await answerCard(quiet.api, STILLS(), { decision: 'ACCEPT', commandId: 'c-3' });
  assert.equal(sheet.status, 'SHEET');
  assert.equal(sheet.sheet, BOARD);
  assert.equal(quiet.calls.length, 0);
});

test('a letter is answered through its own reply and resolve routes', async () => {
  const letter = LETTER();
  const empty = fakeApi([]);
  const nothing = await answerCard(empty.api, letter, { decision: 'REPLY', commandId: 'c', note: '   ' });
  assert.equal(nothing.status, 'INVALID');
  assert.equal(empty.calls.length, 0);
  const { api, calls } = fakeApi([{ id: 'r' }, { id: 'r' }]);
  const replied = await answerCard(api, letter, { decision: 'REPLY', commandId: 'c', note: 'Repar-o mâine.' });
  assert.equal(calls[0].path, `/agents/messages/${letter.id}/reply`);
  assert.deepEqual(calls[0].options.body, { text: 'Repar-o mâine.' });
  assert.equal(replied.status, 'DONE');
  await answerCard(api, letter, { decision: 'RESOLVE', commandId: 'c' });
  assert.equal(calls[1].path, `/agents/messages/${letter.id}/resolve`);
  assert.deepEqual(calls[1].options.body, { resolution: 'Rezolvat de Proprietar din pagină.' });
});

test('only the studio\'s own routes are called from a card', async () => {
  assert.equal(studioPath('/api/v1/owner/decisions/x/decide'), '/owner/decisions/x/decide');
  assert.equal(studioPath('https://elsewhere.example/api/v1/x'), null);
  assert.equal(studioPath('/api/v2/x'), null);
  assert.equal(studioPath('/api/v1/../../x'), null);
  const forged = { ...BUDGET(), answer: { ...BUDGET().answer, path: 'https://elsewhere.example/steal' } };
  const { api, calls } = fakeApi([]);
  const result = await answerCard(api, forged, { decision: 'ACCEPT', commandId: 'c' });
  assert.equal(result.status, 'INVALID');
  assert.equal(calls.length, 0);
});

// --------------------------------------------------------------------------- 8. the history

test('the history says what each answer applied', () => {
  const history = feed().history;
  const words = (/** @type {(c: any) => boolean} */ pick) => appliedWords(/** @type {any} */ (history.find(pick)));
  assert.match(words((c) => c.source === 'agent:director'), /^Aplicat prin comanda ta \(regula pașilor plătiți\): «Trec la MODE»\./);
  assert.match(words((c) => c.kind === 'music_library'), /^Ai refuzat\. Nimic nu s-a schimbat\. Nota ta: «Mai târziu\.»/);
  assert.match(words((c) => c.kind === 'editorial_qc'), /^Ai ales «Rămâne consultativ până la primul film real»: Nimic de schimbat/);
  assert.match(words((c) => c.kind === 'narration_paid_step'), /^Retras: Situația s-a rezolvat/);
  assert.match(words((c) => c.source_type === 'approval'), /^Ai refuzat cererea; refuzul rămâne în registru\. Nota ta: «Nu acum\.»/);
  assert.equal(appliedWords({ source_type: 'decision', status: 'ACCEPTED', chosen_option: 'x', options: [], applied: { type: 'guided', completed_by: 'owner' } }), 'Ai marcat-o făcută.');
  assert.equal(appliedWords({ source_type: 'decision', status: 'ACCEPTED', chosen_option: 'x', options: [], applied: { type: 'guided', completed_by: 'condition' } }), 'S-a rezolvat: studioul a văzut că nu mai trebuie nimic.');
  assert.equal(appliedWords({ source_type: 'decision', status: 'EXPIRED', options: [] }), 'A expirat fără răspunsul tău.');
});

test('the window has two tabs, each with its count, and an empty or unread state of its own', () => {
  const read = feed();
  const waiting = windowHtml(read, o({ tab: 'waiting', read: 'ok' }));
  assert.match(waiting, /role="tablist"/);
  assert.match(waiting, /role="tab"[^>]*aria-selected="true"[^>]*data-decisions-tab="waiting"[^>]*>Te așteaptă <span[^>]*>6</);
  assert.match(waiting, /role="tab"[^>]*aria-selected="false"[^>]*data-decisions-tab="history"[^>]*>Istoric <span[^>]*>6</);
  assert.match(waiting, /role="tabpanel"/);
  assert.equal((waiting.match(/<article /g) || []).length, 6);
  const history = windowHtml(read, o({ tab: 'history', read: 'ok' }));
  assert.equal((history.match(/<article /g) || []).length, 6);
  assert.ok(history.includes('Aplicat prin comanda ta'));
  assert.doesNotMatch(history, /data-decision-action="(accept|refuse)"/, 'a closed card is not answered again');
  const empty = readDecisionFeed({ cards: [], history: [], count: 0 });
  assert.match(windowHtml(empty, o({ tab: 'waiting', read: 'ok' })), /Nimic nu așteaptă decizia ta/);
  assert.match(windowHtml(empty, o({ tab: 'history', read: 'ok' })), /Nu ai răspuns încă la niciun card/);
  assert.match(windowHtml(empty, o({ tab: 'waiting', read: 'pending' })), /Se citesc deciziile/);
  assert.match(windowHtml(empty, o({ tab: 'waiting', read: 'failed', error: 'Conexiunea nu este disponibilă.' })), /nu au putut fi citite[\s\S]*Conexiunea nu este disponibilă/);
  assert.match(windowHtml(empty, o({ tab: 'waiting', read: 'missing' })), /repornești studioul/);
});

// ------------------------------------------------------------------------ 9. the socket

test('the window reads again when a decision, an approval, a letter or his policy moves', () => {
  for (const type of ['owner.decision_decided', 'owner.decision_withdrawn', 'governance.approval_requested', 'governance.approval_decided',
    'agent.message_posted', 'agent.message_resolved', 'economy.budget_set', 'owner.paid_media_approval_changed', 'owner.environment_changed']) {
    assert.equal(refreshesOn({ event_type: type }), true, type);
  }
  for (const type of ['agent.run_completed', 'economy.spend_reserved', 'media.video_rendered']) assert.equal(refreshesOn({ event_type: type }), false, type);
  assert.equal(refreshesOn(null), false);
});

// ---------------------------------------------------------------- 10. the window's behaviour

test('the window is a modal dialog: Esc closes it, focus returns to the key that opened it', () => {
  assert.match(WINDOW, /showModal\(\)/, 'a modal dialog keeps the keyboard inside it');
  assert.match(WINDOW, /addEventListener\('close'/);
  assert.match(WINDOW, /opener[\s\S]{0,200}\.focus\(/, 'focus goes back to the opener');
  assert.match(WINDOW, /role="status"[^>]*data-decisions-status|data-decisions-status[^>]*role="status"/, 'one persistent status line');
  assert.match(WINDOW, /'aria-labelledby', 'decisions-title'/);
  assert.match(WINDOW, /id="decisions-title"/);
  // a repaint keeps the key that had focus, and does not throw away what he is typing
  assert.match(WINDOW, /restoreFocus\(/);
  assert.match(WINDOW, /TEXTAREA/);
  // arrow keys walk the tabs (WAI-ARIA tabs)
  assert.match(WINDOW, /ArrowRight/);
  assert.match(WINDOW, /ArrowLeft/);
});

test('the window is styled from the page\'s tokens, with no colour literal', () => {
  for (const selector of ['.decisions-window', '.decisions-button', '.decisions-badge', '.decision-card', '.decision-option', '.decision-ask', '.decisions-tab']) {
    assert.ok(STYLE.includes(selector), selector);
  }
  assert.ok(!/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i.test(STYLE.replace(/\/\*[\s\S]*?\*\//g, '')), 'no colour literal');
  assert.match(STYLE, /\.decision-option\[data-recommended="true"\][^{]*\{[^}]*var\(--/);
  assert.match(STYLE, /prefers-reduced-motion/);
});
