// SHEET_DRAWER — «Foaia de filmare» on the Owner's page (2026-10-01).
//
// The Nepal film was bought twice from a button that showed no price, no prompt and no model, and
// asked nothing. In PRODUCTION that button now answers 409 «Folosește foaia de filmare»; the page
// opens the sheet in its place. The drawer shows every scene (its frame, model, resolution, billed
// seconds and credits, badges, lint, the stills chosen and refused with their reasons, both prompts),
// the footer the backend priced, and one «Aprobă …» button per paid step with its price and cap,
// disabled with a Romanian reason while it cannot buy. A press only opens the question; his «Da» with
// his note decides the approval bound to THIS sheet's hash, and only then is the step bought.
//
// The fixture is the backend's own GET /media/storyboards/{id}/shooting-sheet (build_sheet, every
// provider faked), shaped as the Nepal film: four filmed scenes, the 100/83 chart and the black end.
// Written before the code.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  SHEET_TITLE,
  STEP_TIMEOUT_MS,
  approveStep,
  creditWords,
  footerRows,
  frameWord,
  heroState,
  lintLine,
  renderAnswer,
  requestRender,
  sceneLine,
  sheetHtml,
  sheetPath,
  stepButtons,
  stepConfirmHtml,
  stepPath,
  stillRedoLabel,
  usdText,
} from '../src/shooting_sheet.js';
import { paidMediaRuleWords } from '../src/owner_controls.js';
import { escapeHtml } from '../src/html.js';

const SHEET = JSON.parse(fs.readFileSync(new URL('./fixtures/shooting_sheet.json', import.meta.url), 'utf8'));
// a Windows checkout writes CRLF; the handler is read line by line
const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const ID = SHEET.storyboard_id;

/** A fresh copy the test may change. @returns {any} */
const sheet = () => structuredClone(SHEET);
/** @param {any} s @param {string} step */
const button = (s, step) => /** @type {any} */ (stepButtons(s).find((b) => b.step === step));
/** The sheet with the hero test shot bought, in the status given. @param {string} status */
function withHero(status, balance = 5000) {
  const s = sheet();
  const hero = s.scenes[0];
  hero.motion.status = 'BOUGHT';
  hero.motion.step_status = 'BOUGHT';
  hero.motion.take_id = 'hero-take';
  hero.motion.take_kind = 'test_shot';
  hero.motion.take_status = status;
  hero.shots = [{ take_id: 'hero-take', kind: 'test_shot', status, model_id: 'seedance2_5', resolution: '1080p', seconds: 5, seed: s.seed, sha256: 'ab'.repeat(32), credits_quoted: 340, credits_measured: 340, failure_code: null, reason_ro: null, approved_by: status === 'APPROVED' ? 'owner' : null, for_current_prompt: true, file_url: '/api/v1/media/takes/hero-take/file' }];
  s.footer.balance = { credits: balance, read: true, problem: null };
  return s;
}

// ------------------------------------------------------------------ 1. the drawer reads the sheet

test('every scene reads as one line: frame, model, resolution, billed seconds and credits', () => {
  assert.equal(SHEET_TITLE, 'Foaia de filmare');
  assert.equal(sceneLine(SHEET.scenes[2]), 'Cadrul 3 · Peisaj · seedance2_5 · 1080p · 5 s · 340 de credite');
  assert.equal(sceneLine(SHEET.scenes[0]), 'Cadrul 1 · Peisaj · seedance2_5 · 1080p · 5 s · 340 de credite');
  assert.equal(sceneLine(SHEET.scenes[1]), 'Cadrul 2 · Plan mediu · veo3.1_fast · 1080p · 6 s · 60 de credite');
  assert.equal(sceneLine(SHEET.scenes[3]), 'Cadrul 4 · Detaliu · veo3.1_fast · 1080p · 6 s · 60 de credite');
  // the cards say what the backend priced them as: composed here, 0 credits
  assert.equal(sceneLine(SHEET.scenes[4]), 'Cadrul 5 · Grafic compus local · 0 credite');
  assert.equal(sceneLine(SHEET.scenes[5]), 'Cadrul 6 · Ecran negru compus local · 0 credite');
  assert.equal(frameWord(SHEET.scenes[4]), 'Grafic');
  // a scene with no model says so, and never prints a price it does not have
  const open = sheet().scenes[1];
  open.motion = { ...open.motion, model_id: null, status: 'NEEDS_OWNER', credits: 0, reason_ro: 'Niciun model nu acoperă scena.' };
  assert.equal(sceneLine(open), 'Cadrul 2 · Plan mediu · fără model ales: Niciun model nu acoperă scena.');
  const local = sheet().scenes[1];
  local.motion = { ...local.motion, model_id: null, status: 'LOCAL', credits: 0 };
  assert.equal(sceneLine(local), 'Cadrul 2 · Plan mediu · imagine fixă animată local · 0 credite');
});

test('Romanian counts: «18 credite», «340 de credite», «1.284 de credite»; USD with a comma', () => {
  assert.equal(creditWords(0), '0 credite');
  assert.equal(creditWords(1), '1 credit');
  assert.equal(creditWords(18), '18 credite');
  assert.equal(creditWords(20), '20 de credite');
  assert.equal(creditWords(340), '340 de credite');
  assert.equal(creditWords(1284), '1.284 de credite');
  assert.equal(creditWords(101), '101 credite');
  assert.equal(creditWords(null), 'necunoscut');
  assert.equal(usdText(3400000), '3,40 USD');
  assert.equal(usdText(12840000), '12,84 USD');
  assert.equal(usdText(null), 'necunoscut');
});

test('the drawer shows the badges, «curat» lint, the card rows and the Owner\'s rule', () => {
  assert.equal(lintLine(SHEET.scenes[0]), 'curat');
  assert.equal(lintLine(SHEET.scenes[2]), '1 avertisment');
  const blocked = sheet().scenes[0];
  blocked.lint = [
    { code: 'ENUM_CODE', severity: 'BLOCK', scene: 1, evidence: 'NEPAL_CLIMATE_CRISIS', message_ro: 'Promptul imaginii conține un cod: „NEPAL_CLIMATE_CRISIS”.' },
    { code: 'HEX_CODE', severity: 'BLOCK', scene: 1, evidence: '#2E4A66', message_ro: 'Promptul imaginii conține o culoare hex: „#2E4A66”.' },
    { code: 'MOTION_LENGTH', severity: 'WARN', scene: 1, evidence: 'x', message_ro: 'Scurt.' },
  ];
  assert.equal(lintLine(blocked), '2 blocaje, 1 avertisment');

  const html = sheetHtml(SHEET, { escape: escapeHtml });
  assert.ok(html.includes('Foaia de filmare'));
  assert.ok(html.includes('Why Nepal Is Being Handed a Climate Bill It Cannot Pay'));
  assert.ok(html.includes('Cadrul 3 · Peisaj · seedance2_5 · 1080p · 5 s · 340 de credite'));
  assert.ok(html.includes('fără fețe: da'), 'the measured face badge');
  assert.ok(html.includes('lumină: înnorat'));
  assert.match(html, /Verificarea prompturilor: <strong[^>]*>curat<\/strong>/);
  assert.ok(html.includes('Grafic compus local · 0 credite'));
  assert.ok(html.includes('Ecran negru compus local · 0 credite'));
  // a card shows its verified numbers and its local preview, never a paid prompt
  assert.ok(html.includes('Promis: 100 mld. USD') && html.includes('Livrat: 83 mld. USD'));
  assert.ok(html.includes(`data-sheet-src="${SHEET.scenes[4].card.preview_url}"`));
  // the Owner's choice of a scene's model is named as his
  assert.ok(html.includes('alegerea ta'), 'scene 3 runs on the model the Owner chose');
  // the seed, the sheet's hash and the Owner's rule
  assert.ok(html.includes(String(SHEET.seed)));
  assert.ok(html.includes(SHEET.sheet_hash.slice(0, 12)));
  assert.equal(paidMediaRuleWords(SHEET.owner_rule), 'Regula ta: fiecare pas plătit al unui film îți cere aprobarea, în orice mod al studioului.');
  assert.equal(paidMediaRuleWords({ paid_media_approval: 'OVER_USD', over_usd: 5 }), 'Regula ta: un pas plătit de peste 5,00 USD îți cere aprobarea; unul mai mic urmează modul studioului.');
  assert.equal(paidMediaRuleWords({ paid_media_approval: 'MODE', over_usd: null }), 'Regula ta: pașii plătiți urmează modul studioului.');
  assert.equal(paidMediaRuleWords(null), paidMediaRuleWords({ paid_media_approval: 'EVERY_PAID_STEP' }), 'an unread rule reads as the strictest');
  assert.ok(html.includes(paidMediaRuleWords(SHEET.owner_rule)));
  // the first real referenceImages use is flagged
  assert.ok(html.includes('nevalidat'), 'reference images not yet verified on this account');
  // backend text is escaped
  const hostile = sheet();
  hostile.scenes[0].still_prompt = '<img src=x onerror=alert(1)>';
  assert.ok(!sheetHtml(hostile, { escape: escapeHtml }).includes('<img src=x'));
});

// --------------------------------------------------------------------- 2. the steps and their guards

test('every step button carries its price and its cap', () => {
  const buttons = stepButtons(withHero('APPROVED'));
  assert.deepEqual(buttons.map((b) => b.label), ['Aprobă imaginile', 'Aprobă cadrul de probă', 'Aprobă mișcarea']);
  const motion = button(withHero('APPROVED'), 'motion');
  assert.equal(motion.price_ro, '460 de credite (4,60 USD)');
  assert.equal(motion.cap_ro, 'plafon 800 de credite (8,00 USD)');
  assert.equal(motion.disabled, false);
  assert.deepEqual(motion.reasons, []);
  const hero = button(sheet(), 'test_shot');
  assert.equal(hero.price_ro, '340 de credite (3,40 USD)');
  assert.equal(hero.cap_ro, 'plafon 680 de credite (6,80 USD)');
  // the stills are all approved: nothing to buy, said in the backend's own words
  const stills = button(sheet(), 'stills');
  assert.equal(stills.disabled, true);
  assert.deepEqual(stills.reasons, [SHEET.steps.stills.waiting_ro]);
  const html = sheetHtml(withHero('APPROVED'), { escape: escapeHtml });
  assert.ok(html.includes('Aprobă mișcarea') && html.includes('460 de credite (4,60 USD)') && html.includes('plafon 800 de credite'));
  assert.match(html, /data-sheet-action="step" data-step="motion"(?![^>]*disabled)/);
});

test('«Aprobă mișcarea» waits for the hero, an open BLOCK and the balance, and says why in Romanian', () => {
  // the fixture: the hero test shot is not bought, and 900 credits are under the motion cap × 1.15
  const first = button(sheet(), 'motion');
  assert.equal(first.disabled, true);
  assert.ok(first.reasons.some((r) => r.startsWith('Întâi cadrul de probă (scena 1)')), first.reason_ro);
  assert.ok(first.reasons.includes('Sold Runway insuficient: 900 de credite; pasul cere plafonul de 800 de credite plus marja de 15% (920 de credite).'));

  // bought but not yet looked at
  const waiting = button(withHero('PAID'), 'motion');
  assert.equal(waiting.disabled, true);
  assert.deepEqual(waiting.reasons, ['Cadrul de probă (scena 1) așteaptă privirea ta: aprobă-l pe foaie înainte de restul mișcării.']);
  assert.equal(heroState(withHero('PAID')).bought, true);
  assert.equal(heroState(withHero('PAID')).approved, false);
  assert.equal(heroState(withHero('APPROVED')).approved, true);

  // a BLOCK open anywhere in the film
  const blocked = withHero('APPROVED');
  blocked.lint_blocked = true;
  blocked.lint_summary_ro = 'Prompturile au 1 blocaje și 0 avertismente. Primul blocaj (scena 2): …';
  const b = button(blocked, 'motion');
  assert.equal(b.disabled, true);
  assert.deepEqual(b.reasons, [`Blocaj deschis: ${blocked.lint_summary_ro}`]);
  assert.equal(button(blocked, 'test_shot').disabled, true, 'a BLOCK holds every paid step');

  // the balance under the cap, and a balance nobody could read
  const poor = withHero('APPROVED', 900);
  assert.equal(button(poor, 'motion').disabled, true);
  const unread = withHero('APPROVED');
  unread.footer.balance = { credits: null, read: false, problem: 'niciun cont Runway conectat' };
  assert.deepEqual(button(unread, 'motion').reasons, ['Soldul Runway nu a putut fi citit (niciun cont Runway conectat); nimic nu se cumpără pe un sold necunoscut.']);

  // the reason is printed under the disabled button
  const html = sheetHtml(sheet(), { escape: escapeHtml });
  assert.match(html, /data-sheet-action="step" data-step="motion"[^>]*disabled/);
  assert.ok(html.includes('Sold Runway insuficient: 900 de credite'));
  assert.ok(html.includes('Întâi cadrul de probă (scena 1)'));
});

test('a step over the day\'s budget is not hidden: the question asks for his explicit consent', () => {
  const s = withHero('APPROVED');
  s.footer.daily_budget.remaining_usd = 2.0;
  const motion = button(s, 'motion');
  assert.equal(motion.disabled, false, 'his consent is asked, the press is not refused');
  assert.equal(motion.over_budget, true);
  const ask = stepConfirmHtml(s, 'motion', { escape: escapeHtml });
  assert.ok(ask.includes('Bugetul zilei'), ask);
  assert.ok(ask.includes('data-sheet-over-budget'));
  assert.ok(ask.includes('Scenele 2, 3, 4'));
  assert.ok(ask.includes(s.sheet_hash.slice(0, 12)));
  assert.ok(ask.includes('data-sheet-note'), 'his note goes with his yes');
  assert.ok(ask.includes('Da, aprob și cumpăr'));
  assert.ok(!stepConfirmHtml(withHero('APPROVED'), 'motion', { escape: escapeHtml }).includes('data-sheet-over-budget'));
});

// ---------------------------------------------- 3. the footer, the contact sheet and the redo buttons

test('the footer total is the sheet\'s total, and its rows are the backend\'s figures', () => {
  const rows = footerRows(SHEET);
  const by = Object.fromEntries(rows.map((r) => [r.key, r.value]));
  assert.equal(by.total, '872 de credite (8,72 USD)');
  // the sheet's total is what its scenes cost: the stills plus every scene's motion
  const scenes = SHEET.scenes.reduce((sum, s) => sum + s.still_credits + s.motion.credits, 0);
  assert.equal(scenes, SHEET.footer.total_credits);
  assert.equal(by.cap, '1.284 de credite (12,84 USD)');
  assert.equal(by.hero, 'scena 1 · 340 de credite (3,40 USD) · rămâne în film');
  assert.equal(by.rest, '460 de credite (4,60 USD)');
  assert.equal(by.stills_spent, '72 de credite (măsurat)');
  assert.equal(by.balance, '900 de credite');
  assert.equal(by.daily, '14,26 USD rămași din 15,00 USD');
  assert.equal(by.saved, '696 de credite (6,96 USD) față de seedance2_5 peste tot');
  assert.equal(by.source, 'tarif publicat 27.09');
  assert.ok(String(by.alternatives).includes('veo3.1_fast 1080p: 312 credite (3,12 USD)'));
  assert.ok(String(by.alternatives).includes('același film la 720p: 552 de credite (5,52 USD)'));
  const unmeasured = sheet();
  unmeasured.footer.stills_spent_credits = { quoted_credits: 18, measured_credits: null };
  assert.equal(Object.fromEntries(footerRows(unmeasured).map((r) => [r.key, r.value])).stills_spent, '18 credite (estimat, nemăsurat)');
  const html = sheetHtml(SHEET, { escape: escapeHtml });
  assert.ok(html.includes('872 de credite (8,72 USD)'));
});

test('a rejected candidate shows its reason; «Refă imaginea (18 credite)» and «Vezi promptul de mișcare» exist', () => {
  const html = sheetHtml(SHEET, { escape: escapeHtml });
  assert.ok(html.includes('YuNet a găsit 2 fețe; biblia vizuală nu permite fețe.'));
  assert.ok(html.includes('Respinsă'));
  assert.equal(stillRedoLabel(SHEET.scenes[0]), 'Refă imaginea (18 credite)');
  assert.equal(stillRedoLabel(SHEET.scenes[4]), '', 'a card has no picture to buy again');
  assert.ok(html.includes('Refă imaginea (18 credite)'));
  assert.match(html, /data-sheet-action="redo-still" data-take="a1f0c2d0-0001-4c11-9a00-000000000101"/);
  assert.ok(html.includes('Vezi promptul de mișcare'));
  assert.ok(html.includes('Vezi promptul imaginii'));
  // the prompts as they will be sent, in English, whole
  assert.ok(html.includes(escapeHtml(SHEET.scenes[1].motion_prompt)));
  assert.ok(html.includes(escapeHtml(SHEET.scenes[1].negative_prompt)));
  // the runner-up the gate passed can be chosen or refused on the contact sheet
  assert.match(html, /data-sheet-action="take" data-take="b7e1c2d0-0003-4c11-9a00-000000000302" data-decision="APPROVED"/);
  assert.match(html, /data-sheet-action="take" data-take="b7e1c2d0-0003-4c11-9a00-000000000302" data-decision="REJECTED"/);
  // a refused candidate cannot be chosen
  assert.doesNotMatch(html, /data-take="c9d0e1f2-0004-4c11-9a00-000000000401" data-decision="APPROVED"/);
  // the bought hero test shot is looked at, then approved or refused, here
  const hero = sheetHtml(withHero('PAID'), { escape: escapeHtml });
  assert.match(hero, /data-sheet-action="take" data-take="hero-take" data-decision="APPROVED"/);
  assert.ok(hero.includes('Aprobă cadrul de probă după ce l-ai văzut'));
  // the scene's model can be changed on the sheet: the cheaper one, the better one, or a local move
  assert.match(html, /data-sheet-action="model" data-scene="3" data-model="veo3.1_fast"/);
  assert.match(html, /data-sheet-action="model" data-scene="2" data-model="seedance2_5"/);
  assert.match(html, /data-sheet-action="model" data-scene="2" data-model="LOCAL_MOVE"/);
  assert.match(html, /data-sheet-action="model" data-scene="3" data-model=""/, 'the Owner can go back to the studio\'s choice');
});

// ---------------------------------------------------- 4. the render button and the approval press

/** A fake of main.js's api(): answers in order, records every call. */
function fakeApi(/** @type {any[]} */ answers) {
  /** @type {{path: string, options: any}[]} */
  const calls = [];
  const api = async (/** @type {string} */ path, /** @type {any} */ options = {}) => {
    calls.push({ path, options });
    const next = answers.shift();
    if (next instanceof Error) throw next;
    return next;
  };
  return { api, calls };
}
/** An error as main.js's api() throws it. @param {number} status @param {any} detail */
function apiError(status, detail) {
  const error = new Error(typeof detail === 'object' && detail ? detail.message || detail.error : String(detail));
  return Object.assign(error, { status, detail });
}

test('the render button opens the sheet when the API answers 409, and goes straight to it after', async () => {
  const use = apiError(409, { error: 'UseShootingSheet', message: 'Folosește foaia de filmare: în PRODUCȚIE nimic nu se mai cumpără de la butonul vechi de randare.', sheet_url: sheetPath(ID), shot_plan_gaps: [] });
  assert.deepEqual(renderAnswer(use), { sheet: true, message: use.detail.message });
  assert.deepEqual(renderAnswer(apiError(409, 'Starea s-a schimbat.')), { sheet: false, message: 'Starea s-a schimbat.' });

  const { api, calls } = fakeApi([use]);
  /** @type {string[]} */
  const opened = [];
  const state = { sheetFirst: false };
  const first = await requestRender(api, ID, state, (/** @type {string} */ id) => { opened.push(id); });
  assert.deepEqual(calls.map((c) => c.path), [`/media/render/${ID}`]);
  assert.deepEqual(opened, [ID]);
  assert.equal(first.opened, true);
  assert.equal(state.sheetFirst, true);
  // the next press does not POST /media/render at all
  const again = await requestRender(api, ID, state, (/** @type {string} */ id) => { opened.push(id); });
  assert.equal(calls.length, 1, 'no second POST /media/render');
  assert.equal(again.opened, true);
  assert.deepEqual(opened, [ID, ID]);

  // TEST keeps the old button: a 200 renders, another error is the caller's
  const ok = fakeApi([{ job_id: 'j' }]);
  assert.deepEqual(await requestRender(ok.api, ID, { sheetFirst: false }, () => assert.fail('no sheet')), { rendered: true, opened: false });
  const broken = fakeApi([apiError(503, { error: 'RenderEngineUnavailable', message: 'FFmpeg lipsește.' })]);
  await assert.rejects(requestRender(broken.api, ID, { sheetFirst: false }, () => assert.fail('no sheet')), /FFmpeg lipsește/);
});

test('main.js wires the render button through the sheet, never straight to POST /media/render', () => {
  const handler = MAIN.slice(MAIN.indexOf("querySelectorAll('.btn-render-video')"));
  const body = handler.slice(0, handler.indexOf('});\n    });') + 1);
  assert.ok(body.includes('requestRender('), 'the button goes through requestRender');
  assert.ok(body.includes('openShootingSheet'), 'a 409 opens the drawer');
  assert.ok(!/api\(`\/media\/render\//.test(MAIN), 'no bare POST /media/render left in main.js');
  assert.ok(MAIN.includes("from './shooting_sheet.js'"));
  assert.ok(MAIN.includes('btn-shooting-sheet'), 'every storyboard can open its sheet directly (0 credits)');
  assert.ok(STYLE.includes('.sheet-drawer'), 'the drawer is styled');
  assert.ok(STYLE.includes('.sheet-step[disabled]') || STYLE.includes('.sheet-step:disabled'));
});

test('a press asks; his «Da» decides the approval bound to this sheet, and only then the step buys', async () => {
  const asked = { status: 'NEEDS_APPROVAL', message: 'Aprobarea Proprietarului este necesară.', approval_id: 'appr-1', cost_usd: 4.6, cap_credits: 800 };
  const bought = { status: 'FINISHED', scenes: [{ scene_index: 2, status: 'PAID' }] };
  const { api, calls } = fakeApi([asked, { status: 'COMMITTED' }, bought]);
  const result = await approveStep(api, { storyboardId: ID, step: 'motion', planHash: SHEET.sheet_hash, note: 'Da, restul mișcării.', commandId: 'cmd-1' });
  assert.equal(result.status, 'BOUGHT');
  assert.deepEqual(calls.map((c) => c.path), [stepPath(ID, 'motion'), '/owner/approvals/decision', stepPath(ID, 'motion')]);
  assert.deepEqual(JSON.parse(calls[0].options.body), { plan_hash: SHEET.sheet_hash, allow_over_budget: false });
  assert.deepEqual(JSON.parse(calls[1].options.body), { schema_version: 1, command_id: 'cmd-1', approval_id: 'appr-1', decision: 'APPROVED', note: 'Da, restul mișcării.' });
  assert.deepEqual(JSON.parse(calls[2].options.body), JSON.parse(calls[0].options.body), 'the same sheet, by hash');
  // a purchase runs on the server until every clip is in: the page waits for it, not 10 s
  assert.equal(calls[0].options.timeoutMs, STEP_TIMEOUT_MS);
  assert.ok(STEP_TIMEOUT_MS >= 30 * 60 * 1000);

  // a stale sheet or an open BLOCK: 409, his yes is never written, nothing is bought
  const stale = fakeApi([apiError(409, { status: 'STALE_PLAN', message: 'Foaia s-a schimbat de când ai văzut-o.' })]);
  const refused = await approveStep(stale.api, { storyboardId: ID, step: 'motion', planHash: SHEET.sheet_hash, note: '', commandId: 'cmd-2' });
  assert.deepEqual(refused, { status: 'REFUSED', code: 'STALE_PLAN', message: 'Foaia s-a schimbat de când ai văzut-o.' });
  assert.equal(stale.calls.length, 1);

  // a yes already spent, or a step that asks again: it stops, it never loops
  const twice = fakeApi([asked, { status: 'COMMITTED' }, { ...asked, approval_id: 'appr-2' }]);
  const waiting = await approveStep(twice.api, { storyboardId: ID, step: 'stills', planHash: SHEET.sheet_hash, note: '', commandId: 'cmd-3' });
  assert.equal(waiting.status, 'WAITING');
  assert.equal(twice.calls.length, 3);

  // the explicit consent over the daily budget travels with the press
  const over = fakeApi([bought]);
  await approveStep(over.api, { storyboardId: ID, step: 'motion', planHash: SHEET.sheet_hash, note: '', commandId: 'c', allowOverBudget: true });
  assert.equal(JSON.parse(over.calls[0].options.body).allow_over_budget, true);
  // a hash that is not a sheet's is never sent
  await assert.rejects(approveStep(over.api, { storyboardId: ID, step: 'motion', planHash: 'nope', note: '', commandId: 'c' }), /foaia/i);
  await assert.rejects(approveStep(over.api, { storyboardId: ID, step: 'render', planHash: SHEET.sheet_hash, note: '', commandId: 'c' }), /pas/i);
});
