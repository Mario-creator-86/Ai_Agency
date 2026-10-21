import test from 'node:test';
import assert from 'node:assert/strict';
import {
  topicStatus, storyboardStatus, storyboardTone, shotWords, qcWord, consistencyWord, channelTypeWord,
  publicationStatus, lifecycleWord, runStatusWord, preflightWord, decisionWord, decisionStateWord,
  matterWords, pipelineStageWord, confidenceWord, constraintWord, budgetStateWord, moneyTagWord,
  accountTypeWord, letterStateWord, policyWord, ownerName, seconds, frameSize, isoDay, codeWords,
} from '../src/dialog_words.js';
import { amount } from '../src/numbers.js';

test('a code the page does not know passes through lower-cased, never guessed', () => {
  assert.equal(codeWords('SOME_NEW_STATE'), 'some new state');
  assert.equal(topicStatus('ARCHIVED_LATER'), 'archived later');
  assert.equal(codeWords(''), '—');
  assert.equal(codeWords(null), '—');
});

test('each state agrees with the noun it is said of (glossary W26)', () => {
  assert.equal(topicStatus('SELECTED'), 'ales');
  assert.equal(topicStatus('PROPOSED'), 'propus');
  assert.equal(storyboardStatus('RENDERED'), 'randat');
  assert.equal(storyboardStatus('REJECTED'), 'respins');
  assert.equal(consistencyWord('UNVERIFIED'), 'neverificată');
  assert.equal(publicationStatus('PUBLISHED'), 'publicat');
  assert.equal(lifecycleWord('ACTIVE'), 'activ');
  assert.equal(lifecycleWord('TERMINATED'), 'concediat');
  assert.equal(runStatusWord('COMPLETED'), 'încheiată');
  assert.equal(runStatusWord('FAILED'), 'eșuată');
  assert.equal(preflightWord('READY'), 'gata');
  assert.equal(preflightWord('DEGRADED'), 'cu limitări');
  assert.equal(preflightWord('BLOCKED'), 'blocantă');
  assert.equal(decisionStateWord('OPEN'), 'deschisă');
  assert.equal(letterStateWord('ANSWERED'), 'răspuns');
  assert.equal(confidenceWord('MEDIUM'), 'medie');
  assert.equal(budgetStateWord('OK'), 'în limită');
  assert.equal(budgetStateWord('WARNING'), 'peste avertizare');
  assert.equal(budgetStateWord('EXCEEDED'), 'peste limită');
});

test('a rejected or failed storyboard is not drawn in the accent green', () => {
  assert.equal(storyboardTone('RENDERED'), 'text-accent');
  assert.equal(storyboardTone('REJECTED'), 'text-error');
  assert.equal(storyboardTone('FAILED'), 'text-error');
  assert.equal(storyboardTone('DRAFT'), '');
});

test('a shot says its size and its picture in film words', () => {
  assert.equal(shotWords('MEDIUM', 'MOTION_GRAPHIC'), 'plan mediu · grafică animată');
  assert.equal(shotWords('CLOSEUP', 'GENERATED_IMAGE'), 'prim-plan · imagine generată');
  assert.equal(shotWords('', 'MOTION_GRAPHIC'), 'grafică animată');
});

test('quality control, channels, decisions and money in words', () => {
  assert.equal(qcWord('PASSED'), 'a trecut');
  assert.equal(qcWord('FAILED'), 'nu a trecut');
  assert.equal(channelTypeWord('MAIN_FACTUAL'), 'Shorts factuale');
  assert.equal(channelTypeWord('OFFICE_SERIAL'), 'Office Serial');
  assert.equal(decisionWord('ITERATE'), 'Corectează');
  assert.equal(decisionWord('NEEDS_MORE_DATA'), 'Mai multe date');
  assert.equal(pipelineStageWord('APPROVAL'), 'aprobare');
  assert.equal(constraintWord('NO_DATA'), 'fără date');
  assert.equal(moneyTagWord('PENDING'), 'NEDECONTAT');
  assert.equal(moneyTagWord('FORECAST'), 'PROGNOZĂ');
  assert.equal(moneyTagWord('VR VIRTUAL'), 'VR VIRTUAL', 'the backend’s own label stays');
  assert.equal(moneyTagWord('ESTIMAT'), 'ESTIMAT');
  assert.equal(accountTypeWord('ASSET'), 'activ');
  assert.equal(accountTypeWord('LIABILITY'), 'datorie');
  assert.equal(policyWord('IMPORTANT_ONLY'), 'numai pentru sarcini importante');
});

test('what a decision is about, from the backend’s own matter keys', () => {
  assert.equal(matterWords('renders_failed'), 'randări eșuate');
  assert.equal(matterWords('bottleneck_approval'), 'gâtuire la aprobare');
  assert.equal(matterWords('bottleneck_research'), 'gâtuire la cercetare');
  const names = new Map([['23d3ba8b', 'Main Channel A - Factual Shorts']]);
  assert.equal(matterWords('cold_start_23d3ba8b', names), 'pornire la rece · Main Channel A - Factual Shorts');
  assert.equal(matterWords('cold_start_ffffffff'), 'pornire la rece');
  assert.equal(matterWords('something_else'), 'something else');
});

test('the Owner named in the data is the Proprietar on the page; nobody else is renamed', () => {
  assert.equal(ownerName('Owner'), 'Proprietar');
  assert.equal(ownerName('owner'), 'Proprietar');
  assert.equal(ownerName('Sarah (Director)'), 'Sarah (Director)');
  assert.equal(ownerName(''), '');
});

test('figures in Romanian form: a decimal comma and a space before the second', () => {
  assert.equal(seconds(4.8), '4,8 s');
  assert.equal(seconds('30.2'), '30,2 s');
  assert.equal(seconds(9), '9 s');
  assert.equal(seconds(null), '—');
  assert.equal(seconds('n/a'), '—');
  assert.equal(frameSize(1080, 1920), '1080×1920');
  assert.equal(frameSize(null, 1920), '—');
  assert.equal(isoDay('2026-09-12'), '12.09.2026');
  assert.equal(isoDay('2026-10-10T00:00:00Z'), '10.10.2026');
  assert.equal(isoDay(''), '—');
  assert.equal(seconds(1234.5), `${amount('1234')},5 s`);
});

test('an account line says a thing once, and a provider keeps its product name', async () => {
  const { accountLine, providerName } = await import('../src/dialog_words.js');
  assert.equal(accountLine('LIABILITY', 'Datorie'), 'Datorie');
  assert.equal(accountLine('ASSET', 'Numerar VR$ (cheltuibil)'), 'activ · Numerar VR$ (cheltuibil)');
  assert.equal(providerName('runway'), 'Runway');
  assert.equal(providerName('elevenlabs'), 'ElevenLabs');
  assert.equal(providerName('some-new'), 'some-new');
  assert.equal(providerName('OLLAMA'), 'Ollama', 'the upper-case type the seed wrote is the same product');
});

test('a letter’s kind is the mail window’s tag word, capitalised', async () => {
  const { mailIntentLabel } = await import('../src/ledger.js');
  assert.equal(mailIntentLabel('STATUS'), 'Raport');
  assert.equal(mailIntentLabel('REQUEST_INFO'), 'Întrebare');
  assert.equal(mailIntentLabel('NEW_KIND'), 'New kind');
});

// W27, the release judge: «Pune în pauză» and «Reia lucrul» stood lit side by side for an active
// employee, and «Reia lucrul» on an active one writes an «agent.resumed» event into the register
// for a resume that never happened. Each control is offered only when its act is a real change.
test('the inspector offers only the lifecycle act that changes something', async () => {
  const { lifecycleActs } = await import('../src/dialog_words.js');
  assert.deepEqual(lifecycleActs('ACTIVE'), { pause: true, resume: false });
  assert.deepEqual(lifecycleActs('PAUSED'), { pause: false, resume: true });
  assert.deepEqual(lifecycleActs('SUSPENDED'), { pause: false, resume: true });
  assert.deepEqual(lifecycleActs('TERMINATED'), { pause: false, resume: false });
  assert.deepEqual(lifecycleActs('paused'), { pause: false, resume: true }, 'case as the data gives it');
  assert.deepEqual(lifecycleActs(undefined), { pause: true, resume: false }, 'an agent without a lifecycle is active');
});
