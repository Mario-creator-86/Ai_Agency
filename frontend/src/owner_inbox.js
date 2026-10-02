import { when } from './mail_thread.js';
import { sheetKeyFor } from './sheet_key.js';

/**
 * «SCRISORI PENTRU TINE» (PAGE_OWNER_DAY: PAGE-07).
 *
 * The studio writes to the Owner (sheet letters, QC letters, failures, interrupted days), and
 * GET /agents/messages/owner, /resolve and /forward had no caller on the page: on 2026-10-01
 * thirteen escalations stood OPEN and he could only find them by scrolling the ledger. This
 * module lists the open ones under the approvals: the subject, who wrote and when, a key to the
 * thread (mail_thread.js), a key to the film's sheet when the letter names one (never its API
 * path), and «Marchează rezolvat» through the existing route.
 *
 * Pure: main.js fetches and paints.
 */

/** Where the letters are read; only the open ones are asked for. */
export const OWNER_LETTERS_PATH = '/agents/messages/owner?open_only=true';

/** @param {string} id */
export function resolvePath(id) {
  return `/agents/messages/${encodeURIComponent(id)}/resolve`;
}

/**
 * The route's body when he marks a letter resolved (agents/router.py ResolveMessageCommand).
 * @param {string} [text] his own words, when he wrote any
 */
export function resolveCommand(text) {
  const said = String(text || '').trim().slice(0, 2000);
  return { resolution: said || 'Rezolvat de Proprietar din pagină.' };
}

/**
 * A count of letters in Romanian: «1 scrisoare», «13 scrisori», «20 de scrisori».
 * @param {number} n
 */
export function lettersWord(n) {
  if (!n) return 'nicio scrisoare';
  if (n === 1) return '1 scrisoare';
  const rest = n % 100;
  return `${n} ${n >= 20 && (rest === 0 || rest >= 20) ? 'de scrisori' : 'scrisori'}`;
}

/** @param {number} n */
function requestsWord(n) {
  if (n === 1) return '1 cerere';
  const rest = n % 100;
  return `${n} ${n >= 20 && (rest === 0 || rest >= 20) ? 'de cereri' : 'cereri'}`;
}

/**
 * The Owner mark at the top of the page, counting what waits for him: the requests and the
 * open letters together. '' when nothing does.
 * @param {number} requests pending approvals
 * @param {number} letters open letters to him
 */
export function ownerMarkWords(requests, letters) {
  if (requests > 0 && letters > 0) return `${requestsWord(requests)} și ${lettersWord(letters)} te așteaptă`;
  // «așteaptă» is the same for one and for many in Romanian
  if (requests > 0) return `${requestsWord(requests)} așteaptă decizia ta`;
  if (letters > 0) return `${lettersWord(letters)} te așteaptă`;
  return '';
}

/**
 * @typedef {{id: string, thread_id: string, subject: string, from_name: string, created_at: string|null,
 *   intent: string, sheet: string|null}} OwnerLetter
 */

/**
 * The open letters to him, from whichever container the route answers with.
 * @param {unknown} payload GET /agents/messages/owner
 * @returns {OwnerLetter[]}
 */
export function readLetters(payload) {
  const rows = Array.isArray(payload)
    ? payload
    : payload && typeof payload === 'object' && Array.isArray(/** @type {any} */ (payload).letters)
      ? /** @type {any} */ (payload).letters
      : [];
  return rows
    .filter((/** @type {any} */ row) => row && typeof row === 'object' && (row.status || 'OPEN') === 'OPEN')
    .map((/** @type {any} */ row) => ({
      id: String(row.id || ''),
      thread_id: String(row.thread_id || row.id || ''),
      subject: String(row.subject || ''),
      from_name: String(row.from_name || 'Studioul'),
      created_at: row.created_at || null,
      intent: String(row.intent || ''),
      sheet: sheetKeyFor(row),
    }));
}

/**
 * The list under «Scrisori pentru tine».
 * @param {OwnerLetter[]} letters
 * @param {{escape: (value: unknown) => string, read: 'pending'|'ok'|'failed', timezone?: string}} o
 */
export function inboxHtml(letters, o) {
  const e = o.escape;
  if (o.read === 'failed') return '<div class="topics-loading">Scrisorile pentru tine nu au putut fi citite.</div>';
  if (!letters.length) {
    return o.read === 'ok'
      ? '<div class="topics-loading">Nicio scrisoare nu te așteaptă.</div>'
      : '<div class="topics-loading">Se citesc scrisorile…</div>';
  }
  return letters
    .map((letter) => `<article class="inbox-letter" data-letter="${e(letter.id)}">`
      + `<p class="inbox-subject">${e(letter.subject || '(fără subiect)')}</p>`
      + `<p class="inbox-meta"><strong>${e(letter.from_name)}</strong>${letter.created_at ? ` · <time>${e(when(letter.created_at, o.timezone))}</time>` : ''}</p>`
      + '<div class="source-actions">'
      + (letter.sheet ? `<button type="button" class="secondary" data-sheet-open="${e(letter.sheet)}">Deschide foaia de filmare</button>` : '')
      + `<button type="button" class="quiet" data-inbox-thread="${e(letter.thread_id)}">Deschide</button>`
      + `<button type="button" class="quiet" data-inbox-resolve="${e(letter.id)}">Marchează rezolvat</button>`
      + '</div></article>')
    .join('');
}
