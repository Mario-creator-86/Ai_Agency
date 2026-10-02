// PAGE_SETTINGS_ERRORS (PAGE-12): the task queue, its retry and a workflow's cancel existed in the
// API and nowhere on the page, and a run «ÎN CURS» stayed so forever. «Coada de lucru» reads the
// queue in his words; a pending run past its retries with no live lease asks whether it is stuck.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  EMPTY_QUEUE,
  QUEUE_PATH,
  ageWords,
  queueHtml,
  retryQuestion,
  stuckThresholdMs,
  stuckWords,
  taskStatusWord,
} from '../src/work_queue.js';

const NOW = Date.parse('2026-10-02T12:00:00Z');
const ago = (ms) => new Date(NOW - ms).toISOString();
const MIN = 60_000;
const HOUR = 60 * MIN;

test('an age is said in Romanian with its plurals', () => {
  assert.equal(ageWords(ago(10_000), NOW), 'chiar acum');
  assert.equal(ageWords(ago(1 * MIN), NOW), 'acum 1 minut');
  assert.equal(ageWords(ago(19 * MIN), NOW), 'acum 19 minute');
  assert.equal(ageWords(ago(45 * MIN), NOW), 'acum 45 de minute');
  assert.equal(ageWords(ago(1 * HOUR), NOW), 'acum 1 oră');
  assert.equal(ageWords(ago(5 * HOUR), NOW), 'acum 5 ore');
  assert.equal(ageWords(ago(23 * HOUR), NOW), 'acum 23 de ore');
  assert.equal(ageWords(ago(26 * HOUR), NOW), 'acum 1 zi');
  assert.equal(ageWords(ago(21 * 24 * HOUR), NOW), 'acum 21 de zile');
  assert.equal(ageWords('not a date', NOW), '—');
});

test('the stuck threshold is the day\'s retries times its attempts, and a live lease is never stuck', () => {
  assert.equal(stuckThresholdMs(), 1800 * 3 * 1000);
  assert.equal(stuckThresholdMs({ daily_retry_seconds: 600, daily_max_attempts: 2 }), 1_200_000);
  const old = { created_at: ago(5 * HOUR), status: 'QUEUED', lease_expires_at: null };
  assert.equal(stuckWords(old, NOW), 'blocată de 5 ore?');
  assert.equal(stuckWords({ ...old, created_at: ago(30 * MIN) }, NOW), '');
  // a day that runs long under a heartbeat is working, not stuck
  assert.equal(stuckWords({ ...old, status: 'RUNNING', lease_expires_at: new Date(NOW + 10 * MIN).toISOString() }, NOW), '');
  assert.equal(stuckWords({ ...old, status: 'RUNNING', lease_expires_at: ago(MIN) }, NOW), 'blocată de 5 ore?');
  assert.equal(stuckWords({ ...old, created_at: ago(26 * HOUR) }, NOW), 'blocată de 1 zi?');
  assert.equal(stuckWords(null, NOW), '');
});

test('an empty queue says so', () => {
  assert.equal(EMPTY_QUEUE, 'Coada este goală.');
  assert.match(queueHtml([], NOW), /Coada este goală\./);
  assert.match(QUEUE_PATH, /^\/tasks\/queue\?limit=\d+$/);
});

test('each task shows its kind, status, age, attempts and last error; only a dead one offers a retry', () => {
  const html = queueHtml([
    { id: 't-1', task_type: 'DAILY_RUN', status: 'DEAD_LETTER', attempts: 1, max_attempts: 1, created_at: ago(3 * HOUR), error_detail: 'INTERRUPTED: studioul s-a oprit <brusc>', workflow_id: null },
    { id: 't-2', task_type: 'WATCHDOG', status: 'QUEUED', attempts: 0, max_attempts: 3, created_at: ago(2 * MIN), error_detail: null, workflow_id: 'wf-1' },
  ], NOW);
  assert.match(html, /rularea zilei/);
  assert.match(html, /oprită definitiv/);
  assert.match(html, /acum 3 ore/);
  assert.match(html, /încercări: 1 din 1/);
  assert.match(html, /studioul s-a oprit &lt;brusc&gt;/);
  assert.match(html, /data-queue-retry="t-1"/);
  assert.doesNotMatch(html, /data-queue-retry="t-2"/);
  assert.match(html, /data-workflow-cancel="wf-1"/);
  assert.match(html, /supraveghetorul/);
  assert.equal(taskStatusWord('QUEUED'), 'în coadă');
  assert.equal(taskStatusWord('RUNNING'), 'rulează');
  assert.equal(taskStatusWord('SOMETHING'), 'SOMETHING');
});

test('a retry that can spend asks with its consequence named', () => {
  assert.match(retryQuestion({ task_type: 'DAILY_RUN' }), /pași plătiți/);
  assert.match(retryQuestion({ task_type: 'FILM_CONTINUE' }), /pași plătiți/);
  assert.match(retryQuestion({ task_type: 'WATCHDOG' }), /^Pui din nou în coadă «supraveghetorul»\?$/);
});

test('a scheduled fire (workflow.job_fired) reads as the routine row, not the English fallback', async () => {
  const { describeEvent } = await import('../src/ledger.js');
  const fired = describeEvent({ event_type: 'workflow.job_fired', payload: { workflow_type: 'WATCHDOG', job_name: 'watchdog' }, created_at: '2026-10-02T10:00:00Z' });
  assert.equal(fired.label, 'sarcină de rutină pornită');
  assert.equal(fired.routine, 'WATCHDOG');
  const other = describeEvent({ event_type: 'workflow.job_fired', payload: { workflow_type: 'DAILY_RUN', job_name: 'daily_main' }, created_at: '2026-10-02T05:00:00Z' });
  assert.equal(other.label, 'sarcină programată pornită');
});
