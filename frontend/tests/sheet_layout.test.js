import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { sceneMediaState, sheetProgress, testShotRecovery, sheetHtml } from '../src/shooting_sheet.js';
import { escapeHtml } from '../src/html.js';

const fixture = JSON.parse(fs.readFileSync(new URL('./fixtures/shooting_sheet.json', import.meta.url), 'utf8'));
const sheet = () => structuredClone(fixture);

function refusedHero() {
  const s = sheet();
  s.steps.test_shot.to_buy = [];
  s.steps.test_shot.held = [1];
  s.steps.test_shot.cost_credits = 0;
  s.steps.test_shot.cap_credits = 0;
  s.scenes[0].motion.step_status = 'NEEDS_OWNER';
  s.scenes[0].shots = [{ take_id: 'refusal', kind: 'test_shot', status: 'REFUSED', file_url: null, for_current_prompt: true,
    reason_ro: 'Keyframe image-to-video requests must use auto_1080p',
    refusal: { kind: 'RATIO_NOT_AUTO', explain_ro: 'Raportul clipului a fost refuzat.', vendor_text: 'Keyframe image-to-video requests must use auto_1080p', credits: 0 } }];
  return s;
}

test('a refused request with no file is never presented or counted as a generated clip', () => {
  const s = refusedHero();
  assert.equal(sceneMediaState(s.scenes[0]).label, 'Refuzat, fără clip');
  assert.equal(sceneMediaState(s.scenes[0]).generated, false);
  assert.equal(sheetProgress(s).clips, 0);
  assert.equal(sheetProgress(s).images, 4);
  assert.equal(sheetProgress(s).filmed, 4);
});

test('current usable files count once per scene; old prompts and rejected clips do not count', () => {
  const s = sheet();
  s.scenes[0].shots = [
    { take_id: 'old', status: 'APPROVED', file_url: '/old.mp4', for_current_prompt: false },
    { take_id: 'bad', status: 'REJECTED', file_url: '/bad.mp4', for_current_prompt: true },
  ];
  assert.equal(sheetProgress(s).clips, 0);
  s.scenes[0].shots.push({ take_id: 'one', status: 'PAID', file_url: '/one.mp4', for_current_prompt: true });
  s.scenes[0].shots.push({ take_id: 'two', status: 'APPROVED', file_url: '/two.mp4', for_current_prompt: true });
  assert.equal(sheetProgress(s).clips, 1);
  assert.equal(sceneMediaState(s.scenes[0]).label, 'Clip aprobat');
});

test('local motion and composed cards are labelled without claiming a generated vendor clip', () => {
  const s = sheet();
  s.scenes[0].motion.status = 'LOCAL';
  assert.equal(sceneMediaState(s.scenes[0]).label, 'Animație locală aleasă');
  assert.equal(sceneMediaState(s.scenes[4]).label, 'Grafic local');
  assert.equal(sheetProgress(s).clips, 0);
  assert.equal(sheetProgress(s).local, 1);
  assert.equal(sceneMediaState({}).label, 'Clip negenerat');
});

test('the held test shot points to the existing redo plan, with its real cost rather than zero', () => {
  const s = refusedHero();
  const recovery = testShotRecovery(s);
  assert.equal(recovery?.scene, 1);
  assert.equal(recovery?.kind, 'motion');
  assert.equal(recovery?.price_ro, `${s.scenes[0].redo.motion.credits} de credite (${s.scenes[0].redo.motion.cost_usd.toFixed(2).replace('.', ',')} USD)`);
  const html = sheetHtml(s, { escape: escapeHtml });
  assert.match(html, /Reia clipul de probă/);
  assert.match(html, /data-sheet-action="to-scene" data-scene="1"/);
  assert.doesNotMatch(html, /Clipuri cumpărate/);
  assert.ok(html.indexOf('id="sheet-steps"') < html.indexOf('<ol class="sheet-scenes"'), 'production steps precede scene details');
});

test('recovery is absent after a current clip is available or when the backend offers no redo', () => {
  const s = refusedHero();
  s.scenes[0].shots.push({ status: 'PAID', file_url: '/new.mp4', for_current_prompt: true });
  assert.equal(testShotRecovery(s), null);
  s.scenes[0].shots = [];
  delete s.scenes[0].redo.motion;
  assert.equal(testShotRecovery(s), null);
});

test('raw vendor text remains escaped and folded away; the balance and batch scope remain visible', () => {
  const s = refusedHero();
  s.scenes[0].shots[0].refusal.vendor_text = 'Keyframe <script>bad</script>';
  const html = sheetHtml(s, { escape: escapeHtml });
  assert.ok(html.includes('Keyframe &lt;script&gt;bad&lt;/script&gt;'));
  assert.doesNotMatch(html, /<script>bad/);
  assert.match(html, /<details class="sheet-shot-history">/);
  assert.match(html, /Sold Runway/);
  assert.match(html, /O singură aprobare/);
});

test('a generated test shot asks for review instead of offering another purchase', () => {
  const s = refusedHero();
  s.scenes[0].shots.push({ take_id: 'new', kind: 'test_shot', status: 'PAID', file_url: '/new.mp4', for_current_prompt: true });
  const html = sheetHtml(s, { escape: escapeHtml });
  assert.match(html, /Vezi și aprobă clipul de probă/);
  assert.match(html, /Clipul există\. Redă-l și aprobă-l/);
  assert.doesNotMatch(html, /Reia clipul de probă/);
});

test('redo is disabled when the known balance cannot cover its real next round and margin', () => {
  const s = refusedHero();
  s.footer.balance.credits = 100;
  const html = sheetHtml(s, { escape: escapeHtml });
  assert.match(html, /data-sheet-action="redo"[^>]*data-kind="motion"[^>]*disabled/);
  assert.match(html, /Pentru pornire:/);
  assert.match(html, /Lipsesc/);
  s.footer.balance.credits = null;
  assert.match(sheetHtml(s, { escape: escapeHtml }), /Soldul Runway este necunoscut/);
});

test('completed motion is shown as ready for review or done instead of waiting to buy zero credits', () => {
  const s = sheet();
  s.steps.motion.to_buy = [];
  for (const scene of s.scenes.slice(1, 4)) scene.shots = [{ status: 'PAID', file_url: `/clip-${scene.scene_index}.mp4`, for_current_prompt: true }];
  let html = sheetHtml(s, { escape: escapeHtml });
  assert.match(html, /Clipurile există\. Verifică rezultatele/);
  assert.match(html, /data-sheet-action="to-scene" data-scene="2"/);
  for (const scene of s.scenes.slice(1, 4)) scene.shots[0].status = 'APPROVED';
  html = sheetHtml(s, { escape: escapeHtml });
  assert.match(html, /Toate scenele rămase au clip sau animație locală/);
});

test('a composed-only film does not claim that an unneeded test shot was accepted', () => {
  const s = sheet();
  s.scenes = [s.scenes[4]];
  s.footer.hero_scene = null;
  s.steps.motion.hero = { status: 'NO_HERO' };
  for (const key of ['stills', 'test_shot', 'motion']) s.steps[key].to_buy = [];
  const html = sheetHtml(s, { escape: escapeHtml });
  assert.match(html, /Nu este necesar/);
  assert.doesNotMatch(html, /Clipul de probă este acceptat/);
});
