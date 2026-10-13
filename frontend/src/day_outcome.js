/**
 * What the panel says a day did, and what the preflight says will stop the next one.
 *
 * Measured on the rehearsal's copy of the Owner's data: a day whose ideas were refused, whose
 * research verified nothing and whose Director decided nothing read "COMPLETED 12/12" on a
 * green card, because a run was shown by its status and a stage by whether it reached its end.
 * The backend now counts what each stage made (`produced_by`, `run_summary` in
 * `backend/app/runbook/services.py`) and names the first check that stops or empties the day
 * (`first_stop` in `backend/app/runbook/preflight.py`); this module decides how the page shows
 * them. It lives here rather than in `main.js` for the reason `readiness.js` gives: `main.js`
 * touches the document the moment it is imported and cannot be loaded by `node --test`.
 *
 * The run's sentence is the backend's Romanian, shown as it came. A count this page does not
 * have is never read as zero: a run or a stage stored before counts existed says so rather
 * than being called empty or idle.
 */

import { checkLabel } from './readiness.js';

/**
 * @typedef {{status?: string, stages_productive?: number | null, summary?: string | null}} RunRecord
 * @typedef {{stage?: string, status?: string, produced?: number | null}} StageRecord
 */

/** @param {unknown} value */
function isCount(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

/**
 * The day's headline and whether it made nothing at all.
 *
 * @param {RunRecord} run
 * @returns {{text: string, empty: boolean}}
 */
export function runHeadline(run) {
  return {
    text: typeof run.summary === 'string' ? run.summary : '',
    empty: isCount(run.stages_productive) && run.stages_productive === 0,
  };
}

/**
 * The run card's classes. A day that made nothing gets `rb-empty` over its status colour, so a
 * COMPLETED status cannot paint green a day that produced nothing.
 *
 * @param {RunRecord} run
 */
export function runClassName(run) {
  const status = String(run.status || '').toLowerCase();
  return `topic-card runbook-run rb-${status}${runHeadline(run).empty ? ' rb-empty' : ''}`;
}

/**
 * What a stage made, in words. `produced: null` is the backend saying the stage is not
 * counted (the preflight, the day's log): nothing is shown. A record without the field was
 * stored before counts existed, and is said to be uncounted rather than idle.
 *
 * @param {StageRecord} stage
 */
export function stageProducedWord(stage) {
  if (!('produced' in stage) || stage.produced === undefined) return 'nenumărat';
  if (stage.produced === null) return '';
  if (!isCount(stage.produced)) return 'nenumărat';
  return stage.produced > 0 ? `a produs ${stage.produced}` : 'nu a produs nimic';
}

/**
 * A stage row's classes: its status, and for a stage that ran to its end, whether it made
 * something. A skipped or failed stage keeps only its status — its reason already says why.
 *
 * @param {StageRecord} stage
 */
export function stageClassName(stage) {
  const status = String(stage.status || '').toLowerCase();
  const base = `runbook-stage rb-${status}`;
  if (status !== 'completed' || !isCount(stage.produced)) return base;
  return `${base} ${Number(stage.produced) > 0 ? 'rb-produced' : 'rb-idle'}`;
}

/**
 * The check the preflight says will stop or empty the day, with that check's own message.
 * A name the list does not carry is still named, by its code name: the page never drops the
 * line because it could not find what to say beside it.
 *
 * @param {{first_stop?: string | null, checks?: Array<{name: string, severity?: string, message?: string}>}} preflight
 * @returns {{name: string, label: string, message: string, blocking: boolean} | null}
 */
export function firstStop(preflight) {
  const name = preflight.first_stop;
  if (!name) return null;
  const check = (preflight.checks || []).find((c) => c.name === name);
  return {
    name,
    label: checkLabel(name),
    message: check?.message || '',
    blocking: String(check?.severity || '').toUpperCase() === 'BLOCKING',
  };
}
