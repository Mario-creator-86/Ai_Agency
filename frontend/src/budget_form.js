/**
 * THE BUDGET FORM (PAGE_OWNER_DAY: PAGE-05).
 *
 * Trezorerie → Buget și cheltuieli once sent `limit_usd: ''` on Enter; the backend read it as 0
 * and retired the daily budget, and with no daily budget nothing in the budget stops a film of
 * the day. A limit is now a positive sum or nothing is sent; retiring is its own key, asked
 * first («Retrage bugetul zilnic»). Every command carries its id (a slow network is one
 * change, not two) and the version of the period the page read (`/economy/budget` `versions`),
 * so a limit set against a budget that moved meanwhile is refused by the server.
 *
 * Pure: main.js reads the form and sends what this module builds.
 */

/** The field's pattern (index.html #budget-limit): a positive sum, «15», «12,50», «0.5». */
export const LIMIT_PATTERN = '(?!0*(?:[.,]0*)?$)\\d{1,9}(?:[.,]\\d{1,2})?';

/** The question «Retrage bugetul zilnic» asks before anything is sent. */
export const RETIRE_QUESTION = 'Fără buget zilnic, nimic din buget nu oprește un film al zilei. Retragi?';

const LIMIT_REQUIRED = 'Scrie limita ca o sumă pozitivă în USD, de exemplu 15 sau 12,50. Un buget nu se retrage cu 0: folosește «Retrage bugetul zilnic».';
const NOT_READ = 'Bugetul nu a fost citit încă; reîncarcă Trezoreria înainte să-l schimbi.';
const PERIODS = ['DAILY', 'MONTHLY'];

/**
 * The period's version as the page read it; null when the studio sent none (not read, or an
 * older studio), 0 for a period never set.
 * @param {any} status GET /economy/budget
 * @param {string} period
 * @returns {number|null}
 */
export function budgetVersion(status, period) {
  const versions = status && typeof status === 'object' ? status.versions : null;
  if (!versions || typeof versions !== 'object') return null;
  const value = Number(versions[period] ?? 0);
  return Number.isInteger(value) && value >= 0 ? value : null;
}

/**
 * The limit as the decimal the backend reads, or null when it is not a positive sum.
 * @param {unknown} text
 */
function positiveDecimal(text) {
  const value = String(text ?? '').trim();
  if (!new RegExp(`^(?:${LIMIT_PATTERN})$`).test(value)) return null;
  const decimal = value.replace(',', '.');
  return Number(decimal) > 0 ? decimal : null;
}

/**
 * «Salvează bugetul»: the command, or the Romanian reason nothing is sent.
 * @param {{period: string, limit: unknown, status: any, commandId: string}} o
 * @returns {{command: {period: string, limit_usd: string, command_id: string, expected_version: number}} | {error: string}}
 */
export function budgetCommand(o) {
  if (!PERIODS.includes(o.period)) return { error: `Perioadă necunoscută: ${o.period}.` };
  const limit = positiveDecimal(o.limit);
  if (limit === null) return { error: LIMIT_REQUIRED };
  const version = budgetVersion(o.status, o.period);
  if (version === null) return { error: NOT_READ };
  return { command: { period: o.period, limit_usd: limit, command_id: o.commandId, expected_version: version } };
}

/**
 * «Retrage bugetul zilnic», after his «Da»: the command, or why nothing is sent.
 * @param {{period: string, status: any, commandId: string}} o
 * @returns {{command: {period: string, retire: true, command_id: string, expected_version: number}} | {error: string}}
 */
export function retireCommand(o) {
  if (!PERIODS.includes(o.period)) return { error: `Perioadă necunoscută: ${o.period}.` };
  const version = budgetVersion(o.status, o.period);
  if (version === null) return { error: NOT_READ };
  return { command: { period: o.period, retire: true, command_id: o.commandId, expected_version: version } };
}
