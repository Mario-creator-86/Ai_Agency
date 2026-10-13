/**
 * Figures as a Romanian reader writes them: «50.000», «0,316».
 *
 * The backend sends money as exact decimal strings («50000», «0.316000»). They are regrouped
 * here as text, never passed through a float, so no digit the ledger holds is rounded away or
 * invented: the grouping comes from Intl.NumberFormat('ro-RO') on the whole part, and the
 * fraction keeps exactly the digits it had.
 */

const GROUPS = new Intl.NumberFormat('ro-RO', { useGrouping: true, maximumFractionDigits: 0 });

/**
 * @param {string|number|null|undefined} value
 * @returns {string} the figure in Romanian form, or the value unchanged when it is not a plain number
 */
export function amount(value) {
  if (value === null || value === undefined) return '';
  const text = String(value).trim();
  const match = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(text);
  if (!match) return text;
  const [, sign, whole, fraction] = match;
  const grouped = GROUPS.format(BigInt(whole));
  return `${sign === '-' ? '−' : ''}${grouped}${fraction ? `,${fraction}` : ''}`;
}
