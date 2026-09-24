/**
 * What the panel says about a day that ran, and about a day that is about to.
 *
 * Measured on the rehearsal's copy of the Owner's data before these tests: a day whose ideas
 * were refused, whose research verified nothing and whose Director decided nothing read
 * "COMPLETED 12/12" on a green card, and «Studioul poate rula» stood above a check that
 * foresaw the day losing its film. The backend now says both; these tests hold the page to
 * showing them.
 */

import test from 'node:test';
import assert from 'node:assert/strict';
import {
  firstStop,
  runHeadline,
  runClassName,
  stageClassName,
  stageProducedWord,
} from '../src/day_outcome.js';
import { describeEvent, productionStatus } from '../src/ledger.js';

const EMPTY_DAY_SUMMARY =
  '10 din 10 etape au rulat până la capăt; 0 au produs ceva. Ziua nu a produs nimic. ' +
  'Niciun film publicat azi.';

test("the run's headline is the backend's sentence, word for word", () => {
  const run = { status: 'COMPLETED', stages_productive: 0, summary: EMPTY_DAY_SUMMARY };
  assert.equal(runHeadline(run).text, EMPTY_DAY_SUMMARY);
  assert.equal(runHeadline(run).empty, true);
  const busy = { status: 'COMPLETED', stages_productive: 7, summary: '10 din 10 etape…' };
  assert.equal(runHeadline(busy).empty, false);
});

test('a run recorded without a summary says nothing rather than inventing one', () => {
  assert.deepEqual(runHeadline({ status: 'COMPLETED' }), { text: '', empty: false });
});

test('a completed day that made nothing does not wear the green of a completed one', () => {
  const empty = { status: 'COMPLETED', stages_productive: 0, summary: EMPTY_DAY_SUMMARY };
  assert.equal(runClassName(empty), 'topic-card runbook-run rb-completed rb-empty');
  assert.equal(
    runClassName({ status: 'COMPLETED', stages_productive: 3 }),
    'topic-card runbook-run rb-completed',
  );
  // An old run with no count is not called empty: the count is absent, not zero.
  assert.equal(runClassName({ status: 'COMPLETED' }), 'topic-card runbook-run rb-completed');
});

test('each stage says whether it produced something, from its own count', () => {
  assert.equal(stageProducedWord({ stage: 'idea_generation', status: 'COMPLETED', produced: 4 }), 'a produs 4');
  assert.equal(
    stageProducedWord({ stage: 'selection', status: 'COMPLETED', produced: 0 }),
    'nu a produs nimic',
  );
  // The preflight and the day's log are not counted: the backend says null, the page says nothing.
  assert.equal(stageProducedWord({ stage: 'preflight', status: 'COMPLETED', produced: null }), '');
  // A stage record without the field was stored before counts existed: it is not called idle.
  assert.equal(stageProducedWord({ stage: 'media', status: 'COMPLETED' }), 'nenumărat');
});

test('a stage that finished and made nothing is marked apart from one that made something', () => {
  assert.equal(
    stageClassName({ status: 'COMPLETED', produced: 0 }),
    'runbook-stage rb-completed rb-idle',
  );
  assert.equal(
    stageClassName({ status: 'COMPLETED', produced: 2 }),
    'runbook-stage rb-completed rb-produced',
  );
  assert.equal(stageClassName({ status: 'SKIPPED', produced: 0 }), 'runbook-stage rb-skipped');
  assert.equal(stageClassName({ status: 'COMPLETED', produced: null }), 'runbook-stage rb-completed');
  assert.equal(stageClassName({ status: 'COMPLETED' }), 'runbook-stage rb-completed');
});

test("the preflight's first stop is the check it names, with that check's own message", () => {
  const preflight = {
    status: 'DEGRADED',
    first_stop: 'daily_budget_films',
    checks: [
      { name: 'llm_provider', ok: true, severity: 'BLOCKING', message: 'Model prezent.' },
      {
        name: 'daily_budget_films',
        ok: false,
        severity: 'DEGRADING',
        message: 'Al doilea film al zilei depășește bugetul zilnic.',
      },
    ],
  };
  assert.deepEqual(firstStop(preflight), {
    name: 'daily_budget_films',
    label: 'Filmele zilei în bugetul zilnic',
    message: 'Al doilea film al zilei depășește bugetul zilnic.',
    blocking: false,
  });
  preflight.checks[1].severity = 'BLOCKING';
  assert.equal(firstStop(preflight)?.blocking, true);
});

test('no first stop, no line; a first stop missing from the list is still named', () => {
  assert.equal(firstStop({ status: 'READY', first_stop: null, checks: [] }), null);
  assert.equal(firstStop({ status: 'READY', checks: [] }), null);
  assert.deepEqual(firstStop({ first_stop: 'something_new', checks: [] }), {
    name: 'something_new',
    label: 'something_new',
    message: '',
    blocking: false,
  });
});

test('the ledger line of a finished day carries its summary', () => {
  const item = describeEvent({
    event_type: 'runbook.daily_run_finished',
    payload: { status: 'COMPLETED', preflight: 'DEGRADED', summary: EMPTY_DAY_SUMMARY, stages_productive: 0 },
  });
  assert.ok(item.text.startsWith('10 din 10 etape au rulat'), item.text);
  // An event written before summaries existed keeps what it said.
  const old = describeEvent({
    event_type: 'runbook.daily_run_finished',
    payload: { status: 'COMPLETED', preflight: 'READY' },
  });
  assert.equal(old.text, 'verificare preliminară READY');
});

test('the head line does not call a day that produced nothing simply completed', () => {
  const status = productionStatus([
    { event_type: 'runbook.daily_run_finished', payload: { status: 'COMPLETED', stages_productive: 0 } },
  ]);
  assert.equal(status.text, 'Ultima rulare a zilei încheiată · 0 etape au produs ceva');
  const busy = productionStatus([
    { event_type: 'runbook.daily_run_finished', payload: { status: 'COMPLETED', stages_productive: 6 } },
  ]);
  assert.equal(busy.text, 'Ultima rulare a zilei încheiată · 6 etape au produs ceva');
  const old = productionStatus([
    { event_type: 'runbook.daily_run_finished', payload: { status: 'COMPLETED' } },
  ]);
  assert.equal(old.text, 'Ultima rulare a zilei încheiată');
});
