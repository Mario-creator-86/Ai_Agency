/**
 * What the panel says about a check and about a figure.
 *
 * Measured on the page before these tests: a failing INFORMATIONAL check read as a red
 * "DEGRADES", the five checks that name what only the Owner can supply were shown by their
 * code names, and the approvals card printed a cost as though it were the whole film.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  RUNBOOK_CHECK_LABELS,
  UNPRICED_CAVEAT_PREFIX,
  approvalCaveat,
  checkClassName,
  checkLabel,
  checkVerdictWord,
} from '../src/readiness.js';

test('an informational failure reads as information, not as a degraded day', () => {
  const serial = { name: 'serial_channel', ok: false, severity: 'INFORMATIONAL' };
  assert.equal(checkVerdictWord(serial), 'INFORMATIV');
  assert.ok(!checkVerdictWord(serial).startsWith('DEGRAD'));
  // And it is not coloured as one: the degrading class is what paints the card amber.
  assert.equal(checkClassName(serial), 'runbook-check rb-fail rb-informational');
});

test('the two severities that do cost him the day still say so', () => {
  assert.equal(checkVerdictWord({ ok: false, severity: 'BLOCKING' }), 'BLOCHEAZĂ');
  assert.equal(checkClassName({ ok: false, severity: 'BLOCKING' }), 'runbook-check rb-fail rb-blocking');
  assert.equal(checkVerdictWord({ ok: false, severity: 'DEGRADING' }), 'DEGRADEAZĂ');
  assert.equal(
    checkClassName({ ok: false, severity: 'DEGRADING' }),
    'runbook-check rb-fail rb-degrading',
  );
});

test('a passing check is OK whatever severity it carries', () => {
  assert.equal(checkVerdictWord({ ok: true, severity: 'INFORMATIONAL' }), 'OK');
  assert.equal(checkClassName({ ok: true, severity: 'BLOCKING' }), 'runbook-check rb-ok');
});

test('a severity this page has never heard of is shown, not rounded into one of the three', () => {
  // The defect these tests are about was exactly this rounding, one severity earlier.
  assert.equal(checkVerdictWord({ ok: false, severity: 'FATAL' }), 'FATAL');
  assert.equal(checkClassName({ ok: false, severity: 'FATAL' }), 'runbook-check rb-fail');
});

test('every check the preflight can emit has a name the Owner would use', () => {
  // The five that name what only he can supply, and the one that reports the mode he chose.
  for (const name of [
    'spending_budget',
    'model_prices',
    'vision_capability',
    'character_references',
    'serial_channel',
    'autonomy_mode',
  ]) {
    assert.ok(RUNBOOK_CHECK_LABELS[name], `${name} has no label`);
    assert.notEqual(checkLabel(name), name);
  }
});

test('a check name nobody has labelled is shown as it came rather than hidden', () => {
  assert.equal(checkLabel('something_new'), 'something_new');
});

test('the caveat about an incomplete estimate is found beside the cost', () => {
  const evidence =
    'storyboard 7f3a, estimat 4.200000 USD (estimare incompletă: narația nu are preț ' +
    'stocat și este numărată ca zero)';
  const caveat = approvalCaveat(evidence);
  assert.ok(caveat.startsWith(UNPRICED_CAVEAT_PREFIX));
  assert.ok(caveat.includes('narația'));
  assert.ok(!caveat.endsWith(')'), 'the line’s bracket is punctuation, not part of the sentence');
});

test('a question whose figure was whole carries no caveat at all', () => {
  assert.equal(approvalCaveat('storyboard 7f3a, estimat 4.200000 USD'), '');
  assert.equal(approvalCaveat(''), '');
  assert.equal(approvalCaveat(null), '');
  assert.equal(approvalCaveat(undefined), '');
});
