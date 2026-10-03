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
// DRAWER_COMPLETE (2026-10-01): each scene's «Refă» (imaginea / mișcarea / cardul) and the film's
// «Refă sunetul» with the redo plan's price, bought through the same approval flow under the plan's
// own hash; «Asamblează filmul» after the motion, with its price line (0 Runway credits, the
// narration's cents) and the QC verdict and reasons when it comes back; his paid-media rule as a real
// control; the SAFETY suggestion, the shot size, the premium reference, the allowed set and the
// narration line.
//
// The fixture is the backend's own GET /media/storyboards/{id}/shooting-sheet, written by a pytest
// run with every provider faked (build_sheet through the route: a fake Runway account reading 900
// credits, fake image and video adapters, a priced ElevenLabs line, a 15 USD daily budget), shaped as
// the Nepal film: four filmed scenes, the 100/83 chart and the black end. Written before the code.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  SHEET_TITLE,
  STEP_TIMEOUT_MS,
  approveAssemble,
  approveRedo,
  approveStep,
  assembleButton,
  assembleResultHtml,
  audioRedoButton,
  clipQcWords,
  creditWords,
  footerRows,
  frameWord,
  heroState,
  lintLine,
  redoButtons,
  redoConfirmHtml,
  redoKey,
  redoPath,
  renderAnswer,
  requestRender,
  sceneLine,
  sheetHtml,
  sheetPath,
  shotSizeWord,
  stepButtons,
  stepConfirmHtml,
  stepPath,
  usdText,
  withdrawnWords,
} from '../src/shooting_sheet.js';
import {
  PAID_MEDIA_CHOICES,
  PAID_MEDIA_PATH,
  paidMediaAnswer,
  paidMediaCommand,
  paidMediaFormHtml,
  paidMediaRefusal,
  paidMediaRuleWords,
  savePaidMediaRule,
} from '../src/owner_controls.js';
import { escapeHtml } from '../src/html.js';

const SHEET = JSON.parse(fs.readFileSync(new URL('./fixtures/shooting_sheet.json', import.meta.url), 'utf8'));
// a Windows checkout writes CRLF; the handler is read line by line
const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8').replace(/\r\n/g, '\n');
const ID = SHEET.storyboard_id;
const e = escapeHtml;

/** A fresh copy the test may change. @returns {any} */
const sheet = () => structuredClone(SHEET);
/** @param {any} s @param {string} step */
const button = (s, step) => /** @type {any} */ (stepButtons(s).find((b) => b.step === step));
/** @param {any} s @param {number} n */
const scene = (s, n) => s.scenes.find((/** @type {any} */ x) => x.scene_index === n);
/** The sheet with the hero test shot bought, in the status given. @param {string} status */
function withHero(status, balance = 5000) {
  const s = sheet();
  const hero = s.scenes[0];
  hero.motion.status = 'BOUGHT';
  hero.motion.step_status = 'BOUGHT';
  hero.motion.take_id = 'hero-take';
  hero.motion.take_kind = 'test_shot';
  hero.motion.take_status = status;
  hero.shots = [{ take_id: 'hero-take', kind: 'test_shot', status, model_id: 'seedance2_5', resolution: '1080p', seconds: 5, seed: s.seed, sha256: 'ab'.repeat(32), credits_quoted: 340, credits_measured: 340, failure_code: null, reason_ro: null, approved_by: status === 'APPROVED' ? 'owner' : null, for_current_prompt: true, file_url: '/api/v1/media/takes/hero-take/file', clip_qc: null }];
  s.footer.balance = { credits: balance, read: true, problem: null };
  return s;
}
/** The sheet once every paid step is bought: only the assembly is left. */
function afterMotion() {
  const s = withHero('APPROVED');
  for (const name of ['stills', 'test_shot', 'motion']) s.steps[name].to_buy = [];
  s.steps.assemble.paid_steps_left = [];
  return s;
}

// ------------------------------------------------------------------ 1. the drawer reads the sheet

test('the fixture is the backend\'s own answer: every field the drawer reads is there', () => {
  assert.match(SHEET.sheet_hash, /^[0-9a-f]{64}$/);
  for (const key of ['scenes', 'steps', 'footer', 'owner_rule', 'lint_summary_ro']) assert.ok(key in SHEET, key);
  for (const key of ['narration', 'audio_redo', 'premium_model_id', 'premium_resolution', 'allowed_models', 'hero_threshold', 'catalogue_problem_ro']) assert.ok(key in SHEET.footer, key);
  for (const key of ['ready', 'blocked', 'scenes', 'paid_steps_left', 'narration', 'cost_usd', 'environment']) assert.ok(key in SHEET.steps.assemble, key);
  for (const s of SHEET.scenes) {
    assert.ok('shot_size' in s && 'redo' in s && 'safety_suggested' in s.motion, `scene ${s.scene_index}`);
    for (const plan of Object.values(s.redo)) assert.match(/** @type {any} */ (plan).plan_hash, /^[0-9a-f]{64}$/);
  }
});

test('every scene reads as one line: frame, model, resolution, billed seconds and credits', () => {
  assert.equal(SHEET_TITLE, 'Foaia de filmare');
  assert.equal(sceneLine(scene(SHEET, 1)), 'Cadrul 1 · Plan aerian · seedance2_5 · 1080p · 5 s · 340 de credite');
  assert.equal(sceneLine(scene(SHEET, 2)), 'Cadrul 2 · Plan mediu · veo3.1_fast · 1080p · 6 s · 60 de credite');
  assert.equal(sceneLine(scene(SHEET, 3)), 'Cadrul 3 · Detaliu · seedance2_5 · 1080p · 5 s · 340 de credite');
  assert.equal(sceneLine(scene(SHEET, 4)), 'Cadrul 4 · Plan larg · veo3.1_fast · 1080p · 6 s · 60 de credite');
  // the cards say what the backend priced them as: composed here, 0 credits
  assert.equal(sceneLine(scene(SHEET, 5)), 'Cadrul 5 · Grafic compus local · 0 credite');
  assert.equal(sceneLine(scene(SHEET, 6)), 'Cadrul 6 · Ecran negru compus local · 0 credite');
  assert.equal(frameWord(scene(SHEET, 5)), 'Grafic');
  // a scene with no model says so, and never prints a price it does not have
  const open = scene(sheet(), 2);
  open.motion = { ...open.motion, model_id: null, status: 'NEEDS_OWNER', credits: 0, reason_ro: 'Niciun model nu acoperă scena.' };
  assert.equal(sceneLine(open), 'Cadrul 2 · Plan mediu · fără model ales: Niciun model nu acoperă scena.');
  const local = scene(sheet(), 2);
  local.motion = { ...local.motion, model_id: null, status: 'LOCAL', credits: 0 };
  assert.equal(sceneLine(local), 'Cadrul 2 · Plan mediu · imagine fixă animată local · 0 credite');
});

test('the shot size is the word of prompt_json.shot_size; an older scene falls back to its prompt', () => {
  const words = { aerial: 'Plan aerian', wide: 'Plan larg', medium: 'Plan mediu', close: 'Prim-plan', detail: 'Detaliu', establishing: 'Plan de ansamblu', two_shot: 'Plan mediu în doi', single: 'Plan apropiat' };
  for (const [size, word] of Object.entries(words)) assert.equal(shotSizeWord(size), word, size);
  assert.equal(shotSizeWord(''), '');
  assert.equal(shotSizeWord('sideways'), '');
  // a storyboard written before the compiler named its sizes: the still prompt still says it
  const older = scene(sheet(), 1);
  older.shot_size = null;
  assert.equal(frameWord(older), 'Plan larg', 'a «wide establishing view» in the prompt');
  older.still_prompt = 'A quiet frame.';
  assert.equal(frameWord(older), 'Cadru filmat');
});

test('Romanian counts: «18 credite», «340 de credite», «1.284 de credite»; USD with a comma', () => {
  assert.equal(creditWords(0), '0 credite');
  assert.equal(creditWords(1), '1 credit');
  assert.equal(creditWords(18), '18 credite');
  assert.equal(creditWords(20), '20 de credite');
  assert.equal(creditWords(312), '312 credite');
  assert.equal(creditWords(340), '340 de credite');
  assert.equal(creditWords(1284), '1.284 de credite');
  assert.equal(creditWords(101), '101 credite');
  assert.equal(creditWords(null), 'necunoscut');
  assert.equal(usdText(3400000), '3,40 USD');
  assert.equal(usdText(12840000), '12,84 USD');
  assert.equal(usdText(null), 'necunoscut');
  assert.equal(withdrawnWords(1), '1 întrebare veche retrasă');
  assert.equal(withdrawnWords(2), '2 întrebări vechi retrase');
  assert.equal(withdrawnWords(20), '20 de întrebări vechi retrase');
});

test('the drawer shows the badges, the lint, the card rows and the Owner\'s rule', () => {
  assert.equal(lintLine(scene(SHEET, 1)), 'curat');
  assert.equal(lintLine(scene(SHEET, 4)), '1 avertisment');
  const blocked = scene(sheet(), 1);
  blocked.lint = [
    { code: 'ENUM_CODE', severity: 'BLOCK', scene: 1, evidence: 'NEPAL_CLIMATE_CRISIS', message_ro: 'Promptul imaginii conține un cod: „NEPAL_CLIMATE_CRISIS”.' },
    { code: 'HEX_CODE', severity: 'BLOCK', scene: 1, evidence: '#2E4A66', message_ro: 'Promptul imaginii conține o culoare hex: „#2E4A66”.' },
    { code: 'MOTION_LENGTH', severity: 'WARN', scene: 1, evidence: 'x', message_ro: 'Scurt.' },
  ];
  assert.equal(lintLine(blocked), '2 blocaje, 1 avertisment');

  const html = sheetHtml(SHEET, { escape: e });
  assert.ok(html.includes('Foaia de filmare'));
  assert.ok(html.includes('Why Nepal Is Being Handed a Climate Bill It Cannot Pay'));
  assert.ok(html.includes('Cadrul 3 · Detaliu · seedance2_5 · 1080p · 5 s · 340 de credite'));
  assert.ok(html.includes('fără fețe: da'), 'the measured face badge');
  assert.ok(html.includes('lumină: înnorat'));
  assert.match(html, /Verificarea prompturilor: <strong[^>]*>curat<\/strong>/);
  assert.ok(html.includes(e(SHEET.lint_summary_ro)));
  assert.ok(html.includes('Grafic compus local · 0 credite'));
  assert.ok(html.includes('Ecran negru compus local · 0 credite'));
  // a card shows its verified numbers and its local preview, never a paid prompt
  assert.ok(html.includes('Promis: 100 mld. USD') && html.includes('Livrat: 83 mld. USD'));
  assert.ok(html.includes(`data-sheet-src="${scene(SHEET, 5).card.preview_url}"`));
  // the Owner's choice of a scene's model is named as his
  assert.ok(html.includes('alegerea ta'), 'scene 3 runs on the model the Owner chose');
  // the seed, the sheet's hash and the Owner's rule
  assert.ok(html.includes(String(SHEET.seed)));
  assert.ok(html.includes(SHEET.sheet_hash.slice(0, 12)));
  assert.equal(paidMediaRuleWords(SHEET.owner_rule), 'Regula ta: fiecare pas plătit al unui film îți cere aprobarea, în orice mod al studioului; narațiunea urmează deocamdată modul studioului.');
  assert.equal(paidMediaRuleWords({ paid_media_approval: 'OVER_USD', over_usd: 5 }), 'Regula ta: un pas plătit cu plafonul de peste 5,00 USD îți cere aprobarea; unul cu plafonul mai mic urmează modul studioului.');
  assert.equal(paidMediaRuleWords({ paid_media_approval: 'MODE', over_usd: null }), 'Regula ta: pașii plătiți urmează modul studioului.');
  assert.equal(paidMediaRuleWords(null), paidMediaRuleWords({ paid_media_approval: 'EVERY_PAID_STEP' }), 'an unread rule reads as the strictest');
  assert.ok(html.includes(paidMediaRuleWords(SHEET.owner_rule)));
  // the page's fresher policy wins over the sheet's copy of the rule
  const fresher = sheetHtml(SHEET, { escape: e, policy: { version: 9, paid_media_approval: 'MODE', paid_media_approval_over_usd: null } });
  assert.ok(fresher.includes('Regula ta: pașii plătiți urmează modul studioului.'));
  // the first real referenceImages use is flagged
  assert.ok(html.includes('nevalidat'), 'reference images not yet verified on this account');
  // backend text is escaped
  const hostile = sheet();
  hostile.scenes[0].still_prompt = '<img src=x onerror=alert(1)>';
  hostile.scenes[0].redo.still.reason_ro = '<script>x</script>';
  hostile.footer.narration.line_ro = '<b>x</b>';
  const out = sheetHtml(hostile, { escape: e, confirm: redoKey('still', 1) });
  assert.ok(!out.includes('<img src=x') && !out.includes('<script>') && !out.includes('<b>x</b>'));
});

// ------------------------------------------- 2. (d) the SAFETY move, the catalogue, the narration

test('a SAFETY suggestion is shown on its scene and can be chosen there, for the price it names', () => {
  const four = scene(SHEET, 4);
  assert.equal(four.motion.safety_suggested.model_id, 'veo3.1_fast');
  const html = sheetHtml(SHEET, { escape: e });
  assert.ok(html.includes('Refuz de siguranță'), html.slice(0, 200));
  assert.ok(html.includes(e(four.motion.safety_suggested.refused)));
  assert.ok(html.includes('Modelul sugerat: veo3.1_fast · 120 de credite'));
  assert.ok(html.includes(e(four.motion.safety_suggested.reason_ro)));
  assert.match(html, /data-sheet-action="model" data-scene="4" data-model="veo3.1_fast"[^>]*>Alege veo3\.1_fast/);
  // scenes with no suggestion say nothing about safety
  const quiet = sheet();
  scene(quiet, 4).motion.safety_suggested = null;
  assert.ok(!sheetHtml(quiet, { escape: e }).includes('Refuz de siguranță'));
});

test('the footer total is the sheet\'s total, with the premium reference, the allowed set and the narration', () => {
  const rows = footerRows(SHEET);
  const by = Object.fromEntries(rows.map((r) => [r.key, r.value]));
  assert.equal(by.total, '872 de credite (8,72 USD)');
  // the sheet's total is what its scenes cost: the stills plus every scene's motion
  const scenes = SHEET.scenes.reduce((/** @type {number} */ sum, /** @type {any} */ s) => sum + s.still_credits + s.motion.credits, 0);
  assert.equal(scenes, SHEET.footer.total_credits);
  assert.equal(by.cap, '1.284 de credite (12,84 USD)');
  assert.equal(by.hero, 'scena 1 · 340 de credite (3,40 USD) · rămâne în film');
  assert.equal(by.rest, '460 de credite (4,60 USD)');
  assert.equal(by.stills_spent, '9 credite (estimat, nemăsurat)');
  assert.equal(by.balance, '900 de credite');
  assert.equal(by.daily, '15,00 USD rămași din 15,00 USD');
  assert.equal(by.saved, '560 de credite (5,60 USD) față de seedance2_5 la 1080p peste tot');
  assert.equal(by.source, 'tarif publicat 27.09');
  assert.ok(String(by.alternatives).includes('veo3.1_fast 1080p: 312 credite (3,12 USD)'));
  assert.ok(String(by.alternatives).includes('același film la 720p: 492 de credite (4,92 USD)'));
  assert.equal(by.premium, 'seedance2_5 · 1080p · pragul cadrului de probă 0,93');
  assert.equal(by.allowed, `16 modele: ${SHEET.footer.allowed_models.join(', ')}`);
  assert.equal(by.narration, SHEET.footer.narration.line_ro);
  const measured = sheet();
  measured.footer.stills_spent_credits = { quoted_credits: 18, measured_credits: 72 };
  assert.equal(Object.fromEntries(footerRows(measured).map((r) => [r.key, r.value])).stills_spent, '72 de credite (măsurat)');
  // no allowed list in the file: every model of the connection may be planned
  const open = sheet();
  open.footer.allowed_models = null;
  assert.equal(Object.fromEntries(footerRows(open).map((r) => [r.key, r.value])).allowed, 'toate modelele conexiunii Runway');
  const html = sheetHtml(SHEET, { escape: e });
  assert.ok(html.includes('872 de credite (8,72 USD)'));
  assert.ok(html.includes('Referința premium') && html.includes('Modele permise') && html.includes('Narațiune: 256 de caractere'));
  // a malformed catalogue is said, never hidden
  const broken = sheet();
  broken.footer.catalogue_problem_ro = 'config/film_models.json: câmpul allowed nu este o listă.';
  assert.ok(sheetHtml(broken, { escape: e }).includes('câmpul allowed nu este o listă'));
});

// --------------------------------------------------------------------- 3. the steps and their guards

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
  assert.equal(hero.disabled, false, '900 credits hold the hero cap and its 15% (782)');
  // the stills are all approved: nothing to buy, said in the backend's own words
  const stills = button(sheet(), 'stills');
  assert.equal(stills.disabled, true);
  assert.deepEqual(stills.reasons, [SHEET.steps.stills.waiting_ro]);
  const html = sheetHtml(withHero('APPROVED'), { escape: e });
  assert.ok(html.includes('Aprobă mișcarea') && html.includes('460 de credite (4,60 USD)') && html.includes('plafon 800 de credite'));
  assert.match(html, /data-sheet-action="step" data-step="motion"(?![^>]*disabled)/);
});

test('«Aprobă mișcarea» waits for the hero, an open BLOCK and the balance, and says why in Romanian', () => {
  // the fixture: the hero test shot is not bought, and 900 credits are under the motion cap × 1.15
  const first = button(sheet(), 'motion');
  assert.equal(first.disabled, true);
  assert.ok(first.reasons.some((/** @type {string} */ r) => r.startsWith('Întâi cadrul de probă (scena 1)')), first.reason_ro);
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
  blocked.lint_summary_ro = 'Prompturile au 1 blocaj și 0 avertismente. Primul blocaj (scena 2): …';
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
  const html = sheetHtml(sheet(), { escape: e });
  assert.match(html, /data-sheet-action="step" data-step="motion"[^>]*disabled/);
  assert.ok(html.includes('Sold Runway insuficient: 900 de credite'));
  assert.ok(html.includes('Întâi cadrul de probă (scena 1)'));
});

test('a step over the day\'s budget is not hidden: the question asks for his explicit consent', () => {
  const s = withHero('APPROVED');
  s.footer.daily_budget.remaining_usd = '2';
  const motion = button(s, 'motion');
  assert.equal(motion.disabled, false, 'his consent is asked, the press is not refused');
  assert.equal(motion.over_budget, true);
  const ask = stepConfirmHtml(s, 'motion', { escape: e });
  assert.ok(ask.includes('Bugetul zilei'), ask);
  assert.ok(ask.includes('data-sheet-over-budget'));
  assert.ok(ask.includes('Scenele 2, 3, 4'));
  assert.ok(ask.includes(s.sheet_hash.slice(0, 12)));
  assert.ok(ask.includes('data-sheet-note'), 'his note goes with his yes');
  assert.ok(ask.includes('Da, aprob și cumpăr'));
  assert.ok(!stepConfirmHtml(withHero('APPROVED'), 'motion', { escape: e }).includes('data-sheet-over-budget'));
});

// --------------------------------------------------------- 4. the contact sheet and the shots' QC

test('a rejected candidate shows its reason; the runner-up can be chosen; the prompts are whole', () => {
  const html = sheetHtml(SHEET, { escape: e });
  assert.ok(html.includes('YuNet a găsit 2 fețe; biblia vizuală nu permite fețe.'));
  assert.ok(html.includes('Respinsă'));
  assert.ok(html.includes('Vezi promptul de mișcare'));
  assert.ok(html.includes('Vezi promptul imaginii'));
  // the prompts as they will be sent, in English, whole
  assert.ok(html.includes(e(scene(SHEET, 2).motion_prompt)));
  // the runner-up the gate passed can be chosen or refused on the contact sheet
  const runner = scene(SHEET, 3).candidates[0].take_id;
  const refused = scene(SHEET, 2).candidates[0].take_id;
  assert.match(html, new RegExp(`data-sheet-action="take" data-take="${runner}" data-decision="APPROVED"`));
  assert.match(html, new RegExp(`data-sheet-action="take" data-take="${runner}" data-decision="REJECTED"`));
  // a refused candidate cannot be chosen
  assert.doesNotMatch(html, new RegExp(`data-take="${refused}" data-decision="APPROVED"`));
  // the bought hero test shot is looked at, then approved or refused, here
  const hero = sheetHtml(withHero('PAID'), { escape: e });
  assert.match(hero, /data-sheet-action="take" data-take="hero-take" data-decision="APPROVED"/);
  assert.ok(hero.includes('Aprobă cadrul de probă după ce l-ai văzut'));
  // the scene's model can be changed on the sheet: the cheaper one, the better one, or a local move
  assert.match(html, /data-sheet-action="model" data-scene="1" data-model="veo3.1_fast"/);
  assert.match(html, /data-sheet-action="model" data-scene="2" data-model="seedance2_5"/);
  assert.match(html, /data-sheet-action="model" data-scene="2" data-model="LOCAL_MOVE"/);
  assert.match(html, /data-sheet-action="model" data-scene="3" data-model=""/, 'the Owner can go back to the studio\'s choice');
  // the old «reject the still» shortcut is gone: a redo is a priced plan now
  assert.ok(!html.includes('data-sheet-action="redo-still"'));
});

test('a bought shot shows its clip QC: passed, failed with the reasons, or waiting for his look', () => {
  const report = (/** @type {string} */ verdict, /** @type {string[]} */ blocks = []) => ({ storyboard_id: ID, scene_number: 1, take_id: 'hero-take', seed: SHEET.seed, attempt: 1, scene: 1, passed: verdict === 'PASSED', verdict, checks: [], blocks_ro: blocks, warnings_ro: [], unmeasured: [], measured: {} });
  assert.equal(clipQcWords(null), 'Controlul clipului: nerulat încă.');
  assert.equal(clipQcWords(report('PASSED')), 'Controlul clipului: trecut.');
  assert.equal(clipQcWords(report('FAILED', ['clipul stă pe loc', 'o tăietură la 2,1 s'])), 'Controlul clipului: picat — clipul stă pe loc; o tăietură la 2,1 s.');
  assert.equal(clipQcWords(report('UNCHECKED', ['nicio vedere disponibilă'])), 'Controlul clipului: neverificat (nicio vedere disponibilă) — așteaptă privirea ta.');
  const s = withHero('PAID');
  s.scenes[0].shots[0].clip_qc = report('FAILED', ['o față spre cameră']);
  const html = sheetHtml(s, { escape: e });
  assert.match(html, /class="sheet-clip-qc" data-verdict="FAILED"/);
  assert.ok(html.includes('Controlul clipului: picat — o față spre cameră.'));
  // the take's own reason repeats the report: it is said once
  s.scenes[0].shots[0].status = 'REJECTED';
  s.scenes[0].shots[0].reason_ro = 'Controlul clipului: o față spre cameră';
  const once = sheetHtml(s, { escape: e });
  assert.equal(once.split('o față spre cameră').length - 1, 1);
});

// ----------------------------------------------------------------- 5. (a) the «Refă» buttons

test('each scene\'s «Refă» buttons carry the redo plan\'s price and cap in credits and USD', () => {
  const one = redoButtons(scene(SHEET, 1));
  assert.deepEqual(one.map((b) => b.label), ['Refă imaginea', 'Refă mișcarea']);
  const [still, motion] = one;
  assert.equal(still.kind, 'still');
  assert.equal(still.price_ro, '18 credite (0,18 USD)');
  assert.equal(still.cap_ro, 'plafon 54 de credite (0,54 USD)');
  assert.equal(still.plan_hash, scene(SHEET, 1).redo.still.plan_hash);
  assert.equal(still.disabled, false);
  assert.equal(still.free, false);
  assert.equal(motion.price_ro, '340 de credite (3,40 USD)');
  assert.equal(motion.cap_ro, 'plafon 680 de credite (6,80 USD)');
  const card = redoButtons(scene(SHEET, 5));
  assert.deepEqual(card.map((b) => [b.kind, b.label, b.price_ro, b.free]), [['card', 'Refă cardul', '0 credite', true]]);
  const sound = audioRedoButton(SHEET);
  assert.equal(sound.label, 'Refă sunetul');
  assert.equal(sound.price_ro, '0 credite');
  assert.equal(sound.scene, null);
  // a plan the backend could not make is disabled with its reason
  const s = sheet();
  scene(s, 2).redo.motion = { available: false, plan_hash: null, reason_ro: 'Scena 2 nu are o imagine aprobată.' };
  const off = redoButtons(scene(s, 2)).find((b) => b.kind === 'motion');
  assert.equal(off?.disabled, true);
  assert.equal(off?.reason_ro, 'Scena 2 nu are o imagine aprobată.');
  // a paid plan the account cannot buy now
  scene(s, 2).redo.still = { ...scene(s, 2).redo.still, buyable: false, reason_ro: 'Sold Runway insuficient.' };
  assert.equal(redoButtons(scene(s, 2)).find((b) => b.kind === 'still')?.disabled, true);

  const html = sheetHtml(SHEET, { escape: e });
  assert.match(html, /data-sheet-action="redo" data-kind="still" data-scene="1"[^>]*>Refă imaginea/);
  assert.match(html, /data-sheet-action="redo" data-kind="motion" data-scene="4"/);
  assert.match(html, /data-sheet-action="redo" data-kind="card" data-scene="5"/);
  assert.match(html, /data-sheet-action="redo" data-kind="audio" data-scene=""[^>]*>Refă sunetul/);
  assert.ok(html.includes(e(SHEET.footer.audio_redo.reason_ro)), 'the sound says what it would remaster, or that there is no film yet');
  assert.ok(html.includes('18 credite (0,18 USD) · plafon 54 de credite (0,54 USD)'));
  assert.match(sheetHtml(s, { escape: e }), /data-sheet-action="redo" data-kind="motion" data-scene="2"[^>]*disabled/);
});

test('a «Refă» press opens its question: what it replaces, its price and cap, the plan it is bound to', () => {
  const ask = redoConfirmHtml(SHEET, redoKey('still', 1), { escape: e });
  assert.ok(ask.includes('Refaci imaginea scenei 1?'), ask);
  assert.ok(ask.includes(e(scene(SHEET, 1).redo.still.reason_ro)));
  assert.ok(ask.includes('18 credite (0,18 USD) · plafon 54 de credite (0,54 USD)'));
  assert.ok(ask.includes(scene(SHEET, 1).redo.still.plan_hash.slice(0, 12)));
  assert.ok(ask.includes('Înlocuiește 1 imagine'));
  assert.ok(ask.includes('data-sheet-note'));
  assert.match(ask, /data-sheet-action="confirm-redo" data-kind="still" data-scene="1"[^>]*>Da, aprob și refac/);
  // a free redo still asks, but there is nothing to approve
  const card = redoConfirmHtml(SHEET, redoKey('card', 5), { escape: e });
  assert.ok(card.includes('Refaci cardul scenei 5?'));
  assert.match(card, />Da, refă \(0 credite\)/);
  const sound = redoConfirmHtml(SHEET, redoKey('audio', null), { escape: e });
  assert.ok(sound.includes('Refaci sunetul filmului?'));
  // over the day's budget: his explicit consent, as for a step
  const s = sheet();
  s.footer.daily_budget.remaining_usd = '0.10';
  assert.ok(redoConfirmHtml(s, redoKey('motion', 1), { escape: e }).includes('data-sheet-over-budget'));
  // a disabled plan opens no question
  scene(s, 2).redo.motion = { available: false, plan_hash: null, reason_ro: 'Nu.' };
  assert.equal(redoConfirmHtml(s, redoKey('motion', 2), { escape: e }), '');
  // the question is shown inside its scene, where the button was pressed
  const html = sheetHtml(SHEET, { escape: e, confirm: redoKey('still', 1) });
  const one = html.slice(html.indexOf('Cadrul 1 ·'), html.indexOf('Cadrul 2 ·'));
  assert.ok(one.includes('Refaci imaginea scenei 1?'));
});

// ------------------------------------------------------- 6. talking to the studio: the approval flow

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
  const again = await requestRender(api, ID, state, (/** @type {string} */ id) => { opened.push(id); });
  assert.equal(calls.length, 1, 'no second POST /media/render');
  assert.equal(again.opened, true);
  assert.deepEqual(opened, [ID, ID]);

  const ok = fakeApi([{ job_id: 'j' }]);
  assert.deepEqual(await requestRender(ok.api, ID, { sheetFirst: false }, () => assert.fail('no sheet')), { rendered: true, opened: false });
  const broken = fakeApi([apiError(503, { error: 'RenderEngineUnavailable', message: 'FFmpeg lipsește.' })]);
  await assert.rejects(requestRender(broken.api, ID, { sheetFirst: false }, () => assert.fail('no sheet')), /FFmpeg lipsește/);
});

test('a press asks; his «Da» decides the approval bound to this sheet, and only then the step buys', async () => {
  const asked = { status: 'NEEDS_APPROVAL', message: 'Aprobarea Proprietarului este necesară.', approval_id: 'appr-1', cost_usd: 4.6, cap_credits: 800, withdrawn: ['old-1'] };
  const bought = { status: 'FINISHED', scenes: [{ scene_index: 2, status: 'PAID' }] };
  const { api, calls } = fakeApi([asked, { status: 'COMMITTED' }, bought]);
  const result = await approveStep(api, { storyboardId: ID, step: 'motion', planHash: SHEET.sheet_hash, note: 'Da, restul mișcării.', commandId: 'cmd-1' });
  assert.equal(result.status, 'BOUGHT');
  assert.deepEqual(result.withdrawn, ['old-1'], 'the older question it withdrew is said');
  assert.deepEqual(calls.map((c) => c.path), [stepPath(ID, 'motion'), '/owner/approvals/decision', stepPath(ID, 'motion')]);
  assert.deepEqual(JSON.parse(calls[0].options.body), { plan_hash: SHEET.sheet_hash, allow_over_budget: false });
  assert.deepEqual(JSON.parse(calls[1].options.body), { schema_version: 1, command_id: 'cmd-1', approval_id: 'appr-1', decision: 'APPROVED', note: 'Da, restul mișcării.' });
  assert.deepEqual(JSON.parse(calls[2].options.body), JSON.parse(calls[0].options.body), 'the same sheet, by hash');
  assert.equal(calls[0].options.timeoutMs, STEP_TIMEOUT_MS);
  assert.ok(STEP_TIMEOUT_MS >= 30 * 60 * 1000);

  const stale = fakeApi([apiError(409, { status: 'STALE_PLAN', message: 'Foaia s-a schimbat de când ai văzut-o.' })]);
  const refused = await approveStep(stale.api, { storyboardId: ID, step: 'motion', planHash: SHEET.sheet_hash, note: '', commandId: 'cmd-2' });
  assert.deepEqual(refused, { status: 'REFUSED', code: 'STALE_PLAN', message: 'Foaia s-a schimbat de când ai văzut-o.', scenes: [] });
  assert.equal(stale.calls.length, 1);

  const twice = fakeApi([asked, { status: 'COMMITTED' }, { ...asked, approval_id: 'appr-2' }]);
  const waiting = await approveStep(twice.api, { storyboardId: ID, step: 'stills', planHash: SHEET.sheet_hash, note: '', commandId: 'cmd-3' });
  assert.equal(waiting.status, 'WAITING');
  assert.equal(twice.calls.length, 3);

  const over = fakeApi([bought]);
  await approveStep(over.api, { storyboardId: ID, step: 'motion', planHash: SHEET.sheet_hash, note: '', commandId: 'c', allowOverBudget: true });
  assert.equal(JSON.parse(over.calls[0].options.body).allow_over_budget, true);
  await assert.rejects(approveStep(over.api, { storyboardId: ID, step: 'motion', planHash: 'nope', note: '', commandId: 'c' }), /foaia/i);
  await assert.rejects(approveStep(over.api, { storyboardId: ID, step: 'render', planHash: SHEET.sheet_hash, note: '', commandId: 'c' }), /pas/i);
});

test('a paid redo goes the same way, under the redo plan\'s own hash; a free one is one POST', async () => {
  const plan = scene(SHEET, 2).redo.still;
  const asked = { error: 'SceneRedoRefused', status: 'NEEDS_APPROVAL', message: 'Aprobarea ta este necesară.', approval_id: 'appr-r', plan_hash: plan.plan_hash, cost_usd: 0.18, cap_credits: 54, findings: [] };
  const done = { kind: 'still', scene_index: 2, status: 'PAID' };
  const { api, calls } = fakeApi([asked, { status: 'COMMITTED' }, done]);
  const result = await approveRedo(api, { storyboardId: ID, kind: 'still', sceneIndex: 2, planHash: plan.plan_hash, note: 'Fețe.', commandId: 'cmd-r' });
  assert.equal(result.status, 'DONE');
  assert.deepEqual(result.result, done);
  assert.deepEqual(calls.map((c) => c.path), [redoPath(ID), '/owner/approvals/decision', redoPath(ID)]);
  assert.equal(redoPath(ID), `/media/storyboards/${ID}/redo`);
  assert.deepEqual(JSON.parse(calls[0].options.body), { kind: 'still', scene_index: 2, plan_hash: plan.plan_hash, note: 'Fețe.', allow_over_budget: false });
  assert.deepEqual(JSON.parse(calls[2].options.body), JSON.parse(calls[0].options.body));
  assert.equal(JSON.parse(calls[1].options.body).approval_id, 'appr-r');
  assert.equal(calls[0].options.timeoutMs, STEP_TIMEOUT_MS);

  // the sound and a card cost nothing: one POST, no question
  const free = fakeApi([{ output_asset_id: 'a2', job_id: 'j2' }]);
  const sound = await approveRedo(free.api, { storyboardId: ID, kind: 'audio', sceneIndex: null, planHash: SHEET.footer.audio_redo.plan_hash, note: '', commandId: 'c' });
  assert.equal(sound.status, 'DONE');
  assert.deepEqual(JSON.parse(free.calls[0].options.body), { kind: 'audio', scene_index: null, plan_hash: SHEET.footer.audio_redo.plan_hash, note: null, allow_over_budget: false });
  // a refusal is the backend's own sentence; nothing is decided
  const none = fakeApi([apiError(409, { error: 'SceneRedoRefused', status: 'NO_FILM', message: 'Nu există încă un film randat.' })]);
  assert.deepEqual(await approveRedo(none.api, { storyboardId: ID, kind: 'card', sceneIndex: 5, planHash: null, note: '', commandId: 'c' }), { status: 'REFUSED', code: 'NO_FILM', message: 'Nu există încă un film randat.', scenes: [] });
  // a paid redo without its plan's hash is never sent
  await assert.rejects(approveRedo(none.api, { storyboardId: ID, kind: 'motion', sceneIndex: 2, planHash: null, note: '', commandId: 'c' }), /plan/i);
  await assert.rejects(approveRedo(none.api, { storyboardId: ID, kind: 'film', sceneIndex: 2, planHash: plan.plan_hash, note: '', commandId: 'c' }), /refacere/i);
});

// ----------------------------------------------------------------- 7. (b) «Asamblează filmul»

test('«Asamblează filmul» comes after the motion, priced: 0 Runway credits and the narration\'s cents', () => {
  const first = assembleButton(SHEET);
  assert.equal(first.label, 'Asamblează filmul');
  assert.equal(first.price_ro, '0 credite Runway · narațiunea 0,08 USD');
  assert.equal(first.line_ro, SHEET.footer.narration.line_ro);
  assert.equal(first.disabled, true);
  assert.deepEqual(first.reasons, ['Întâi pașii plătiți rămași: cadrul de probă, mișcarea. Filmul se asamblează după ultimul.']);
  const ready = assembleButton(afterMotion());
  assert.equal(ready.disabled, false);
  assert.deepEqual(ready.reasons, []);
  // a filmed scene without an accepted take holds it, scene by scene, in the backend's words
  const held = afterMotion();
  held.steps.assemble.ready = false;
  held.steps.assemble.blocked = [{ scene_index: 2, reason_ro: 'Scena 2: cadrul plătit nu a trecut controlul clipului (clipul stă pe loc).' }];
  assert.deepEqual(assembleButton(held).reasons, ['Scena 2: cadrul plătit nu a trecut controlul clipului (clipul stă pe loc).']);
  // a narration with no price is never 0: he is asked before it is voiced
  const unpriced = afterMotion();
  unpriced.steps.assemble.narration = { ...unpriced.steps.assemble.narration, priced: false, usd_micros: 0, usd: 0 };
  assert.equal(assembleButton(unpriced).price_ro, '0 credite Runway · narațiunea: preț necunoscut, te întreabă înainte');
  // a film with no words costs nothing at all
  const silent = afterMotion();
  silent.steps.assemble.narration = { characters: 0, per_1k_usd_micros: null, usd_micros: 0, usd: 0, priced: true, line_ro: 'Narațiune: niciun cuvânt de citit · 0 USD' };
  assert.equal(assembleButton(silent).price_ro, '0 credite Runway · fără narațiune');

  const html = sheetHtml(SHEET, { escape: e });
  const steps = html.slice(html.indexOf('class="sheet-steps"'));
  assert.ok(steps.indexOf('Aprobă mișcarea') < steps.indexOf('Asamblează filmul'), 'after the motion step');
  assert.match(html, /data-sheet-action="step" data-step="assemble"[^>]*disabled/);
  assert.ok(html.includes('0 credite Runway · narațiunea 0,08 USD'));
  assert.match(sheetHtml(afterMotion(), { escape: e }), /data-sheet-action="step" data-step="assemble"(?![^>]*disabled)/);
  const ask = stepConfirmHtml(afterMotion(), 'assemble', { escape: e });
  assert.ok(ask.includes('Asamblezi filmul din cadrele acceptate?'), ask);
  assert.ok(ask.includes(e(SHEET.footer.narration.line_ro)));
  assert.match(ask, /data-sheet-action="confirm-step" data-step="assemble"[^>]*>Da, asamblează/);
});

test('the assembly is asked and voiced under this sheet\'s hash, and 409 names each scene', async () => {
  const asked = { status: 'NEEDS_APPROVAL', message: 'Narațiunea costă 0,08 USD.', approval_id: 'appr-a', cost_usd: 0.0768, cap_credits: 0, withdrawn: [] };
  const film = { status: 'ASSEMBLED', storyboard_id: ID, plan_hash: SHEET.sheet_hash, job_id: 'job-1', asset_id: 'asset-1', file_path: 'x', narration: { usd_micros: 76800, asked: true }, credits_measured: null, fallback_gate: null, costs: {}, qc: { status: 'PASSED', score: 1, failure_reasons_json: [] }, qc_letter_ro: 'Controlul calității: trecut.' };
  const { api, calls } = fakeApi([asked, { status: 'COMMITTED' }, film]);
  const result = await approveAssemble(api, { storyboardId: ID, planHash: SHEET.sheet_hash, note: '', commandId: 'cmd-a' });
  assert.equal(result.status, 'ASSEMBLED');
  assert.equal(result.result.asset_id, 'asset-1');
  assert.deepEqual(calls.map((c) => c.path), [stepPath(ID, 'assemble'), '/owner/approvals/decision', stepPath(ID, 'assemble')]);
  assert.deepEqual(JSON.parse(calls[0].options.body), { plan_hash: SHEET.sheet_hash, allow_over_budget: false });
  assert.equal(calls[0].options.timeoutMs, STEP_TIMEOUT_MS);
  // nothing to ask (no price, or the mode lets it): one POST
  const direct = fakeApi([film]);
  assert.equal((await approveAssemble(direct.api, { storyboardId: ID, planHash: SHEET.sheet_hash, note: '', commandId: 'c' })).status, 'ASSEMBLED');
  assert.equal(direct.calls.length, 1);
  // scenes with no accepted take: the backend's reason per scene, before any job exists
  const held = fakeApi([apiError(409, { status: 'TAKES_NOT_ACCEPTED', message: 'Filmul nu se asamblează.', scenes: [{ scene_index: 2, reason_ro: 'Scena 2: clipul așteaptă privirea ta.' }, { scene_index: 4, reason_ro: 'Scena 4: nicio imagine aprobată.' }] })]);
  const refused = await approveAssemble(held.api, { storyboardId: ID, planHash: SHEET.sheet_hash, note: '', commandId: 'c' });
  assert.equal(refused.status, 'REFUSED');
  assert.equal(refused.code, 'TAKES_NOT_ACCEPTED');
  assert.deepEqual(refused.scenes, ['Scena 2: clipul așteaptă privirea ta.', 'Scena 4: nicio imagine aprobată.']);
  assert.equal(held.calls.length, 1);
});

test('the QC verdict and its reasons are shown when the film comes back', () => {
  const failed = { status: 'ASSEMBLED', job_id: 'job-1', asset_id: 'asset-1', narration: { usd_micros: 76800, asked: true }, qc: { status: 'FAILED', score: 0.5, failure_reasons_json: ['Scena 7 (ecran negru) tace 3,4 s, peste maximul de 2,0 s.', 'Filmul durează mai mult decât narațiunea.'] }, qc_letter_ro: 'Controlul calității a picat.\n- Scena 7: ecran negru prea lung.\nRefacerea cardului: 0 credite.' };
  const html = assembleResultHtml(failed, { escape: e });
  assert.match(html, /class="sheet-qc" data-verdict="FAILED"/);
  assert.ok(html.includes('Controlul calității: picat'));
  assert.ok(html.includes('Scena 7 (ecran negru) tace 3,4 s, peste maximul de 2,0 s.'));
  assert.ok(html.includes('Filmul durează mai mult decât narațiunea.'));
  assert.ok(html.includes('Refacerea cardului: 0 credite.'), 'the Owner\'s QC letter, whole');
  assert.ok(html.includes('Narațiunea: 0,08 USD'));
  const passed = assembleResultHtml({ ...failed, qc: { status: 'PASSED', score: 1, failure_reasons_json: [] }, qc_letter_ro: 'Totul a trecut.' }, { escape: e });
  assert.match(passed, /data-verdict="PASSED"/);
  assert.ok(passed.includes('Controlul calității: trecut'));
  assert.equal(assembleResultHtml(null, { escape: e }), '');
  // the drawer shows it in the assembly's box
  const sheetWith = sheetHtml(afterMotion(), { escape: e, assembled: failed });
  assert.ok(sheetWith.includes('Controlul calității: picat'));
  const hostile = assembleResultHtml({ ...failed, qc_letter_ro: '<img src=x>' }, { escape: e });
  assert.ok(!hostile.includes('<img src=x>'));
});

// ------------------------------------------------------------ 8. (c) his paid-media rule, a control

test('his paid-media rule has three choices, each explained in one Romanian line', () => {
  assert.deepEqual(PAID_MEDIA_CHOICES.map((c) => c.value), ['EVERY_PAID_STEP', 'OVER_USD', 'MODE']);
  for (const c of PAID_MEDIA_CHOICES) {
    assert.ok(c.label && c.meaning, c.value);
    assert.ok(!c.meaning.includes('\n'), 'one line');
  }
  const every = PAID_MEDIA_CHOICES[0];
  assert.equal(every.label, 'La fiecare pas plătit');
  assert.match(every.meaning, /imaginile, cadrul de probă, mișcarea, o refacere/);
  assert.match(PAID_MEDIA_CHOICES[1].meaning, /plafonul unui pas depășește suma/);
  assert.match(PAID_MEDIA_CHOICES[0].meaning, /Narațiunea .* urmează modul studioului/);
  assert.match(PAID_MEDIA_CHOICES[2].meaning, /modul studioului/);
  const policy = { version: 7, paid_media_approval: 'OVER_USD', paid_media_approval_over_usd: 2.5 };
  const html = paidMediaFormHtml(policy, { escape: e });
  for (const c of PAID_MEDIA_CHOICES) assert.match(html, new RegExp(`type="radio" name="paid-media" value="${c.value}"`));
  assert.match(html, /value="OVER_USD" checked/);
  assert.match(html, /data-paid-media-amount[^>]*value="2,50"/);
  assert.ok(html.includes('versiunea 7'));
  assert.match(html, /data-sheet-action="paid-media-save"/);
  // an unread policy: nothing can be sent without its version
  const unread = paidMediaFormHtml(null, { escape: e });
  assert.match(unread, /data-sheet-action="paid-media-save"[^>]*disabled/);
  assert.match(unread, /value="EVERY_PAID_STEP" checked/, 'an unread rule reads as the strictest');
  // the drawer carries the control
  assert.ok(sheetHtml(SHEET, { escape: e, policy }).includes('data-sheet-action="paid-media-save"'));
});

test('the rule is sent with its policy version; 409 reloads and says so, 403 shows the refusal', async () => {
  assert.equal(PAID_MEDIA_PATH, '/owner/paid-media-approval');
  assert.deepEqual(paidMediaCommand('OVER_USD', '2,50', 7, 'cmd-p'), { ok: true, command: { schema_version: 1, command_id: 'cmd-p', expected_version: 7, paid_media_approval: 'OVER_USD', over_usd: 2.5 } });
  assert.deepEqual(paidMediaCommand('EVERY_PAID_STEP', '9', 7, 'c'), { ok: true, command: { schema_version: 1, command_id: 'c', expected_version: 7, paid_media_approval: 'EVERY_PAID_STEP', over_usd: null } });
  assert.equal(paidMediaCommand('MODE', '', 7, 'c').ok, true);
  assert.deepEqual(paidMediaCommand('OVER_USD', '', 7, 'c'), { ok: false, error: 'Scrie suma în USD, de exemplu 2,50.' });
  assert.deepEqual(paidMediaCommand('OVER_USD', '-1', 7, 'c'), { ok: false, error: 'Scrie suma în USD, de exemplu 2,50.' });
  assert.equal(paidMediaCommand('ALWAYS', '', 7, 'c').ok, false);
  assert.deepEqual(paidMediaCommand('MODE', '', null, 'c'), { ok: false, error: 'Versiunea regulii nu a fost citită; reîncarcă pagina.' });

  assert.equal(paidMediaAnswer({ command_id: 'c', status: 'COMMITTED', paid_media_approval: 'OVER_USD', over_usd: 2.5, version: 8, event_id: 'e' }), 'Salvat. Regula ta: un pas plătit cu plafonul de peste 2,50 USD îți cere aprobarea; unul cu plafonul mai mic urmează modul studioului. (versiunea 8)');
  assert.equal(paidMediaAnswer({ command_id: 'c', status: 'NO_CHANGE', paid_media_approval: 'MODE', over_usd: null, version: 8, event_id: null }), 'Nimic de schimbat: regula era deja aceasta (versiunea 8).');

  const saved = fakeApi([{ command_id: 'c', status: 'COMMITTED', paid_media_approval: 'MODE', over_usd: null, version: 8, event_id: 'e' }]);
  const ok = await savePaidMediaRule(saved.api, { choice: 'MODE', amount: '', version: 7, commandId: 'c' });
  assert.equal(ok.status, 'SAVED');
  assert.match(ok.message, /^Salvat\./);
  assert.deepEqual(saved.calls.map((c) => [c.path, c.options.method]), [[PAID_MEDIA_PATH, 'POST']]);
  assert.deepEqual(JSON.parse(saved.calls[0].options.body), { schema_version: 1, command_id: 'c', expected_version: 7, paid_media_approval: 'MODE', over_usd: null });

  const stale = fakeApi([apiError(409, 'Policy changed; refresh the snapshot and retry')]);
  const again = await savePaidMediaRule(stale.api, { choice: 'MODE', amount: '', version: 6, commandId: 'c' });
  assert.equal(again.status, 'STALE');
  assert.equal(again.reload, true);
  assert.equal(again.message, 'Regula ta s-a schimbat între timp, din altă parte. Am reîncărcat-o: privește-o și alege din nou.');
  assert.deepEqual(paidMediaRefusal(apiError(409, 'x')), { status: 'STALE', reload: true, message: again.message });

  const forbidden = fakeApi([apiError(403, 'Doar Proprietarul poate schimba când îl întreabă un pas plătit al unui film.')]);
  const no = await savePaidMediaRule(forbidden.api, { choice: 'MODE', amount: '', version: 7, commandId: 'c' });
  assert.deepEqual(no, { status: 'REFUSED', reload: false, message: 'Doar Proprietarul poate schimba când îl întreabă un pas plătit al unui film.' });

  // nothing is sent when the amount is not one
  const quiet = fakeApi([]);
  const bad = await savePaidMediaRule(quiet.api, { choice: 'OVER_USD', amount: 'cinci', version: 7, commandId: 'c' });
  assert.deepEqual(bad, { status: 'INVALID', reload: false, message: 'Scrie suma în USD, de exemplu 2,50.' });
  assert.equal(quiet.calls.length, 0);
});

// --------------------------------------------------------------------- 9. main.js and the style

test('main.js wires the render button through the sheet, never straight to POST /media/render', () => {
  // PAGE-17: the media list's keys are one delegated listener; the render key's branch is read
  const handler = MAIN.slice(MAIN.indexOf("closest('.btn-render-video')"));
  const body = handler.slice(0, handler.indexOf("closest('.btn-qc-video')"));
  assert.ok(body.includes('requestRender('), 'the button goes through requestRender');
  assert.ok(body.includes('openShootingSheet'), 'a 409 opens the drawer');
  assert.ok(!/api\(`\/media\/render\//.test(MAIN), 'no bare POST /media/render left in main.js');
  assert.ok(MAIN.includes("from './shooting_sheet.js'"));
  assert.ok(MAIN.includes('btn-shooting-sheet'), 'every storyboard can open its sheet directly (0 credits)');
  assert.ok(STYLE.includes('.sheet-drawer'), 'the drawer is styled');
  assert.ok(STYLE.includes('.sheet-step[disabled]') || STYLE.includes('.sheet-step:disabled'));
});

test('main.js presses every new control through the pure flows, and the old shortcut is gone', () => {
  for (const call of ['approveRedo(', 'approveAssemble(', 'savePaidMediaRule(', 'assembled: sheetDrawer.assembled', 'withdrawnWords(']) assert.ok(MAIN.includes(call), call);
  for (const action of ["'redo'", "'confirm-redo'", "'paid-media-save'"]) assert.ok(MAIN.includes(`action === ${action}`), action);
  assert.ok(!MAIN.includes("action === 'redo-still'"), 'a redo is a priced plan, not a rejected still');
  assert.ok(!/window\.confirm\(`Respingi imaginea/.test(MAIN));
  // a stale rule reloads the page's policy before he chooses again
  const save = MAIN.slice(MAIN.indexOf("action === 'paid-media-save'"));
  assert.ok(save.slice(0, 1500).includes('refresh()'), 'a 409 reloads the policy');
});

test('the new parts of the drawer are styled from the page\'s tokens, with no colour literal', () => {
  const block = STYLE.slice(STYLE.indexOf('/* ------------------------------------------------- Foaia de filmare'));
  for (const selector of ['.sheet-redos', '.sheet-redo-btn', '.sheet-safety', '.sheet-assemble', '.sheet-qc', '.sheet-letter', '.sheet-rule-box', '.paid-media-option', '.sheet-clip-qc']) {
    assert.ok(block.includes(selector), selector);
  }
  assert.ok(!/#[0-9a-f]{3,8}\b|rgba?\(/i.test(block.replace(/\/\*[\s\S]*?\*\//g, '')), 'no colour literal');
  assert.match(block, /\.sheet-qc\[data-verdict="FAILED"\][^{]*\{[^}]*var\(--alert/);
  assert.match(block, /\.sheet-qc\[data-verdict="PASSED"\][^{]*\{[^}]*var\(--ok/);
});

// -------------------------------------------- 10. PAGE_OWNER_DAY: the sheet reached from everywhere

test('sheetKeyFor finds the film in a sheet letter, a media.* question and a run waiting for him', async () => {
  const { sheetKeyFor } = await import('../src/shooting_sheet.js');
  const letter = { id: 'm-1', body_json: { kind: 'owner_shooting_sheet', storyboard_id: ID, sheet_url: `/api/v1/media/storyboards/${ID}/shooting-sheet`, approval_id: 'a-1' } };
  assert.equal(sheetKeyFor(letter), ID);
  // a letter of another kind that still names the film's sheet (the TEST letter) opens it too
  assert.equal(sheetKeyFor({ body_json: { kind: 'owner_test_environment', storyboard_id: ID, sheet_url: sheetPath(ID) } }), ID);
  assert.equal(sheetKeyFor({ body_json: { kind: 'qc', reason: 'x' } }), null);
  // a paid question: the action is media.*, its subject the film
  assert.equal(sheetKeyFor({ action: 'media.motion_purchase', subject: ID }), ID);
  assert.equal(sheetKeyFor({ action: 'media.stills_purchase', subject: 'board-1', context: { storyboard_id: ID } }), ID);
  assert.equal(sheetKeyFor({ action: 'publishing.public_publish', subject: ID }), null, 'not a film question');
  // a run's media stage waiting for him
  const run = { stages: [{ stage: 'selection', artefacts: {} }, { stage: 'media', artefacts: { awaiting_owner: [{ storyboard_id: ID, step: 'stills', approval_id: 'a-2' }] } }] };
  assert.equal(sheetKeyFor(run), ID);
  assert.equal(sheetKeyFor(run.stages[1]), ID);
  assert.equal(sheetKeyFor({ awaiting_owner: [{ storyboard_id: ID }] }), ID);
  // nothing that is not a film's id
  assert.equal(sheetKeyFor({ body_json: { kind: 'owner_shooting_sheet', storyboard_id: '../../etc' } }), null);
  assert.equal(sheetKeyFor(null), null);
  assert.equal(sheetKeyFor({ stages: [{ stage: 'media', artefacts: { awaiting_owner: [] } }] }), null);
});

test('while a step is being bought elsewhere, every paid button says so and none can be pressed', () => {
  const s = withHero('APPROVED');
  s.in_progress = { holder: 'day-1', step: 'stills', reason_ro: 'Filmul este deja în lucru: imaginile au început acum 3 minute.' };
  s.steps.stills.in_progress = true;
  for (const b of stepButtons(s)) {
    assert.equal(b.disabled, true, b.step);
    assert.match(b.reason_ro, /deja în lucru/);
  }
  assert.equal(assembleButton(s).disabled, true);
  assert.match(assembleButton(s).reason_ro, /deja în lucru/);
  // a step marked in progress with no film-wide lease still says it is being bought
  const t = sheet();
  t.steps.stills.in_progress = true;
  assert.match(button(t, 'stills').reason_ro, /în curs/);
});

test('the hero gate the backend sends decides whether the motion waits for his look', () => {
  const accepted = withHero('PAID');
  accepted.steps.motion.hero = { status: 'ACCEPTS', reason_ro: 'Cadrul de probă a trecut controlul clipului.', rule_accepts: true };
  assert.ok(!button(accepted, 'motion').reasons.some((/** @type {string} */ r) => /cadrul de probă/i.test(r)), 'clip QC accepts it under his rule');
  const waiting = withHero('PAID');
  waiting.steps.motion.hero = { status: 'WAITING', reason_ro: 'Cadrul de probă (scena 1) a trecut controlul clipului și așteaptă privirea Proprietarului.' };
  assert.ok(button(waiting, 'motion').reasons.includes(waiting.steps.motion.hero.reason_ro));
});

test('a press shows what is being bought, and a lost answer says the purchase may still be running', async () => {
  const { NETWORK_STEP_WORDS, buyingNotice } = await import('../src/shooting_sheet.js');
  assert.equal(buyingNotice('stills'), 'Se cumpără imaginile: poate dura până la 45 de minute. Nu cumpăra din nou; foaia se reîncarcă singură.');
  assert.match(buyingNotice('motion'), /^Se cumpără mișcarea: poate dura până la 45 de minute/);
  assert.match(buyingNotice('test_shot'), /^Se cumpără cadrul de probă:/);
  assert.match(buyingNotice('assemble'), /^Se asamblează filmul:/);
  assert.match(buyingNotice('redo:motion:3'), /^Se reface mișcarea scenei 3:/);
  assert.equal(NETWORK_STEP_WORDS, 'Răspunsul nu a ajuns; cumpărarea poate continua pe server. Reîncarcă foaia peste câteva minute înainte de orice altă apăsare.');
  const lost = Object.assign(new Error('Conexiunea nu este disponibilă. Ce se vede nu mai este la zi.'), { network: true });
  const { api } = fakeApi([lost]);
  const result = await approveStep(api, { storyboardId: ID, step: 'stills', planHash: SHEET.sheet_hash, note: '', commandId: 'c-1' });
  assert.deepEqual(result, { status: 'REFUSED', code: 'NETWORK', message: NETWORK_STEP_WORDS, scenes: [] });
  // the second post, after his yes, lost the same way
  const asked = { status: 'NEEDS_APPROVAL', approval_id: 'a-1' };
  const later = fakeApi([asked, { status: 'COMMITTED' }, lost]);
  assert.equal((await approveStep(later.api, { storyboardId: ID, step: 'stills', planHash: SHEET.sheet_hash, note: '', commandId: 'c-2' })).code, 'NETWORK');
});

test('a press carries its own purchase id, never the id of his yes', async () => {
  const asked = { status: 'NEEDS_APPROVAL', approval_id: 'a-1' };
  const { api, calls } = fakeApi([asked, { status: 'COMMITTED' }, { status: 'FINISHED' }]);
  await approveStep(api, { storyboardId: ID, step: 'stills', planHash: SHEET.sheet_hash, note: '', commandId: 'yes-1', purchaseId: 'buy-1' });
  assert.equal(JSON.parse(calls[0].options.body).command_id, 'buy-1');
  assert.equal(JSON.parse(calls[1].options.body).command_id, 'yes-1');
  assert.equal(JSON.parse(calls[2].options.body).command_id, 'buy-1', 'the same press, the same purchase');
  const redo = fakeApi([{ status: 'DONE' }]);
  await approveRedo(redo.api, { storyboardId: ID, kind: 'card', sceneIndex: 5, planHash: null, note: '', commandId: 'y', purchaseId: 'buy-2' });
  assert.equal(JSON.parse(redo.calls[0].options.body).command_id, 'buy-2');
});

test('the sheet opens on a summary bar: his rule, the next step with its price and cap, a key to the steps', async () => {
  const { sheetSummary } = await import('../src/shooting_sheet.js');
  const s = sheet();
  const summary = sheetSummary(s, { paid_media_approval: 'MODE', paid_media_approval_over_usd: null });
  assert.equal(summary.rule_ro, 'Regula ta: pașii plătiți urmează modul studioului.');
  const first = stepButtons(s).find((b) => b.to_buy.length > 0);
  assert.ok(first, 'the fixture still has a paid step to buy');
  assert.equal(summary.next?.step, first?.step, 'the first paid step with something to buy');
  assert.equal(summary.next?.label, first?.label);
  assert.match(String(summary.next?.price_ro), /credite/);
  assert.match(String(summary.next?.cap_ro), /^plafon /);
  const html = sheetHtml(s, { escape: e });
  assert.ok(html.indexOf('sheet-summary-bar') >= 0 && html.indexOf('sheet-summary-bar') < html.indexOf('sheet-head'), 'the bar is the first thing');
  assert.ok(html.includes('data-sheet-action="to-steps"'));
  assert.ok(html.includes('Mergi la pași'));
  // with every paid step bought, the next step is the assembly
  assert.equal(sheetSummary(afterMotion(), null).next?.step, 'assemble');
  assert.match(STYLE, /\.sheet-summary-bar\s*\{[^}]*position:\s*sticky/);
});

test('the film\'s own ceiling is a footer row', () => {
  const s = sheet();
  s.footer.film_budget = { limit_usd_micros: 15240000, spent_usd_micros: 740000, remaining_usd_micros: 14500000, limit_ro: '15,24 USD', spent_ro: '0,74 USD', source: 'default' };
  const row = footerRows(s).find((r) => r.key === 'film_budget');
  assert.equal(row?.label, 'Plafonul filmului');
  assert.equal(row?.value, '0,74 USD cheltuiți din 15,24 USD; rămân 14,50 USD');
  assert.equal(footerRows(sheet()).find((r) => r.key === 'film_budget'), undefined, 'an older studio sends none');
});

test('main.js keeps a purchase busy per film, keeps the drawer open while it buys, and opens the sheet from every key', () => {
  assert.ok(MAIN.includes('buyingNotice('), 'the notice of what is being bought');
  assert.ok(MAIN.includes("addEventListener('cancel'"), 'Esc does not hide a purchase');
  assert.ok(MAIN.includes('sheetBusy'), 'busy is kept per storyboard');
  assert.ok(!/Object\.assign\(sheetDrawer, \{[^}]*busy: false/.test(MAIN), 'reopening never clears a purchase in flight');
  assert.ok(MAIN.includes('purchaseId: crypto.randomUUID()'));
  for (const where of ['data-sheet-open', 'sheetKeyFor(']) assert.ok(MAIN.includes(where), where);
});

test('the sheet shows the backend repair state and never calls a queued repair solved', () => {
  for (const [status, words] of [['QUEUED', 'Trimis Directorului'], ['RUNNING', 'în lucru'], ['RESOLVED', 'rezolvate'], ['UNRESOLVED', 'deschise'], ['WAITING_OWNER', 'decizia ta']]) {
    const html = sheetHtml({ remediation: { status, reason: 'Raport <verificat>' } }, { escape: escapeHtml });
    assert.ok(html.includes(words), status);
    assert.ok(html.includes('Raport &lt;verificat&gt;'));
  }
});
