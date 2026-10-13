// PAGE_SETTINGS_ERRORS (PAGE-18): one place for a count said in Romanian. «1 scenă», «19 scene»,
// «20 de scene», «101 scene», «1.284 de credite»: from 20 up, a number whose last two digits are
// 00 or 20-99 takes «de». Dependency-free, so every module (ledger.js and hud_charts.js included,
// which dialog_words.js itself imports) can use it without an import cycle.

const NUMBER = new Intl.NumberFormat('ro-RO', { useGrouping: true, maximumFractionDigits: 2 });

/**
 * @param {unknown} value the count
 * @param {string} one the singular, «scenă»
 * @param {string} many the plural, «scene»
 */
export function countWords(value, one, many) {
  const n = Number(value);
  if (value === null || value === undefined || value === '' || !Number.isFinite(n)) return `— ${many}`;
  if (n === 1) return `1 ${one}`;
  if (!Number.isInteger(n)) return `${NUMBER.format(n)} ${many}`;
  const rest = Math.abs(n) % 100;
  const joiner = Math.abs(n) >= 20 && (rest === 0 || rest >= 20) ? ' de ' : ' ';
  return `${NUMBER.format(n)}${joiner}${many}`;
}
