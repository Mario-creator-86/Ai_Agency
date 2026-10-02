// PAGE_SETTINGS_ERRORS (PAGE-12): «Coada de lucru». The studio's task queue (GET /tasks/queue),
// its retry of a dead task (POST /tasks/{id}/retry) and a workflow's cancel
// (POST /workflows/{id}/cancel) existed in the API and nowhere on the page, and a pending run
// read «ÎN CURS» forever. Pure: the words and the markup; main.js fetches and wires the keys.
import { escapeHtml } from './html.js';
import { taskLabel } from './ledger.js';
import { countWords } from './plurals.js';

export const QUEUE_PATH = '/tasks/queue?limit=30';
export const EMPTY_QUEUE = 'Coada este goală.';

/** The backend's defaults for a day's retries (config.py daily_retry_seconds, daily_max_attempts). */
const DEFAULT_RETRY_SECONDS = 1800;
const DEFAULT_ATTEMPTS = 3;

const STATUS_WORD = /** @type {Record<string, string>} */ ({
  QUEUED: 'în coadă',
  CLAIMED: 'preluată',
  RUNNING: 'rulează',
  COMPLETED: 'terminată',
  FAILED: 'eșuată',
  DEAD_LETTER: 'oprită definitiv',
  CANCELLED: 'anulată',
});

/** @param {unknown} status */
export function taskStatusWord(status) {
  return STATUS_WORD[String(status)] || String(status || '—');
}

/**
 * How long ago, in his words: «chiar acum», «acum 1 minut», «acum 45 de minute», «acum 5 ore».
 * @param {unknown} iso @param {number} now
 */
export function ageWords(iso, now) {
  const span = spanWords(iso, now);
  return span === null ? '—' : span ? `acum ${span}` : 'chiar acum';
}

/** «1 minut», «5 ore», «1 zi»; '' under a minute; null when the date cannot be read. */
function spanWords(/** @type {unknown} */ iso, /** @type {number} */ now) {
  const at = Date.parse(String(iso || ''));
  if (!Number.isFinite(at)) return null;
  const minutes = Math.floor(Math.max(0, now - at) / 60_000);
  if (minutes < 1) return '';
  if (minutes < 60) return countWords(minutes, 'minut', 'minute');
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return countWords(hours, 'oră', 'ore');
  return countWords(Math.floor(hours / 24), 'zi', 'zile');
}

/**
 * How long a pending day may wait before the page asks whether it is stuck: the day's retry
 * interval times its attempts (the backend's own window for a day to finish trying).
 * @param {{daily_retry_seconds?: number, daily_max_attempts?: number}} [settings]
 */
export function stuckThresholdMs(settings = {}) {
  const retry = Number(settings.daily_retry_seconds) > 0 ? Number(settings.daily_retry_seconds) : DEFAULT_RETRY_SECONDS;
  const attempts = Number(settings.daily_max_attempts) > 0 ? Number(settings.daily_max_attempts) : DEFAULT_ATTEMPTS;
  return retry * attempts * 1000;
}

/**
 * «blocată de 5 ore?» for a pending day older than the threshold and holding no live lease (a day
 * that runs long keeps its lease by heartbeat and is not stuck); '' otherwise.
 * @param {any} task the pending task (TaskQueueItemView) @param {number} now
 * @param {{daily_retry_seconds?: number, daily_max_attempts?: number}} [settings]
 */
export function stuckWords(task, now, settings) {
  if (!task) return '';
  const created = Date.parse(String(task.created_at || ''));
  if (!Number.isFinite(created) || now - created <= stuckThresholdMs(settings)) return '';
  const lease = Date.parse(String(task.lease_expires_at || ''));
  if (Number.isFinite(lease) && lease > now) return '';
  return `blocată de ${spanWords(task.created_at, now)}?`;
}

/** The tasks whose retry may start paid steps under his rule. */
const SPENDING_TASKS = new Set(['DAILY_RUN', 'FILM_CONTINUE']);

/** The confirmation before a retry. @param {any} task */
export function retryQuestion(task) {
  const name = taskLabel(String(task && task.task_type));
  return SPENDING_TASKS.has(String(task && task.task_type))
    ? `Pui din nou în coadă «${name}»? Poate porni pași plătiți, după regula ta pentru pașii plătiți și bugetul zilei.`
    : `Pui din nou în coadă «${name}»?`;
}

/** The confirmation before a workflow is cancelled. */
export const CANCEL_QUESTION = 'Anulezi fluxul acestei sarcini? Un flux anulat nu mai poate fi reluat.';

/**
 * The queue as cards: kind, status, age, attempts and last error, with «Reîncearcă» on a dead task
 * and «Anulează» on a task that belongs to a workflow.
 * @param {any[]} tasks @param {number} now
 */
export function queueHtml(tasks, now) {
  const rows = Array.isArray(tasks) ? tasks : [];
  if (!rows.length) return `<div class="topics-loading">${EMPTY_QUEUE}</div>`;
  return rows
    .map((task) => {
      const error = String(task.error_detail || '').trim();
      const keys = [
        task.status === 'DEAD_LETTER'
          ? `<button type="button" class="secondary" data-queue-retry="${escapeHtml(task.id)}">Reîncearcă</button>`
          : '',
        task.workflow_id && !['COMPLETED', 'CANCELLED'].includes(task.status)
          ? `<button type="button" class="quiet" data-workflow-cancel="${escapeHtml(task.workflow_id)}">Anulează fluxul</button>`
          : '',
      ].join('');
      return `<div class="topic-card queue-task" data-status="${escapeHtml(task.status)}">
        <div class="topic-card-header">
          <strong class="topic-card-title" title="${escapeHtml(task.task_type)}">${escapeHtml(taskLabel(String(task.task_type)))}</strong>
          <span class="topic-card-novelty">${escapeHtml(taskStatusWord(task.status))}</span>
        </div>
        <div class="topic-card-meta">${escapeHtml(ageWords(task.created_at, now))} · încercări: ${escapeHtml(String(task.attempts ?? 0))} din ${escapeHtml(String(task.max_attempts ?? '—'))}</div>
        ${error ? `<div class="claim-notes">${escapeHtml(error.slice(0, 400))}</div>` : ''}
        ${keys ? `<div class="source-actions">${keys}</div>` : ''}
      </div>`;
    })
    .join('');
}
