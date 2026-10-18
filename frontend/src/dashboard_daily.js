export const DASHBOARD_TIME_ZONE = 'Europe/Bucharest';
const dayFormatter = new Intl.DateTimeFormat('en-CA', { timeZone: DASHBOARD_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit' });
/** @param {number} now */
export function dashboardDay(now) {
  const parts = dayFormatter.formatToParts(now);
  return ['year', 'month', 'day'].map(type => parts.find(part => part.type === type)?.value).join('-');
}
/** Civil-day boundaries, rather than 24-hour arithmetic, include both DST transitions. @param {number} now */
export function dayWindow(now = Date.now()) {
  const day = dashboardDay(now);
  const boundary = (/** @type {number} */ low, /** @type {number} */ high, /** @type {(day:string)=>boolean} */ before) => {
    while (high - low > 1) {
      const middle = Math.floor((low + high) / 2);
      if (before(dashboardDay(middle))) low = middle; else high = middle;
    }
    return high;
  };
  const start = boundary(now - 36 * 3600_000, now, value => value < day);
  const next = boundary(now, now + 36 * 3600_000, value => value <= day);
  return { day, since: new Date(start).toISOString(), start, next };
}
const ACTIVE = new Set(['DRAFT', 'APPROVED', 'IN_PRODUCTION', 'RENDERING', 'RENDERED', 'COMPLETED']);
const RELEASED = new Set(['PUBLISHED', 'REMOTE_CONFIRMED', 'SCHEDULED']);
/** @param {any[]|null} projects */
export const activeProjects = projects => (projects || []).filter(row => ACTIVE.has(row.status) && !RELEASED.has(row.publication?.status));

/** @param {unknown} value @returns {bigint|null} */
function micros(value) {
  const text = String(value ?? '').trim();
  if (!/^\d+(?:\.\d{1,6})?$/.test(text)) return null;
  const [whole, fraction = ''] = text.split('.');
  return BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, '0'));
}
/** @param {bigint|null} value */
function usd(value) {
  if (value === null) return '—';
  const cents = (value + 5_000n) / 10_000n;
  return `${(cents / 100n).toLocaleString('ro-RO')},${String(cents % 100n).padStart(2, '0')}`;
}
/** The economy endpoint already reconciles invoices and estimates. Never sum its subtotals again. @param {any} budget */
export function dailyBudget(budget) {
  if (!budget) return { value: '—', note: 'Bugetul se citește…', percent: null, title: 'Date indisponibile' };
  const daily = budget.budgets?.find((/** @type {any} */ row) => row.period === 'DAILY');
  const spent = micros(daily?.spent_usd ?? budget.today?.spent_usd);
  const limit = micros(daily?.limit_usd);
  const held = micros(daily?.reserved_usd ?? budget.today?.reserved_usd) ?? 0n;
  const remaining = micros(daily?.remaining_usd) ?? (limit !== null && spent !== null ? (limit > spent + held ? limit - spent - held : 0n) : null);
  return {
    value: `${usd(spent)} / ${usd(limit)} USD`,
    note: limit === null ? 'Limită zilnică nesetată' : spent === null ? 'Cheltuielile nu sunt disponibile' : `${usd(remaining)} USD disponibili${spent > limit ? ' · limită depășită' : ''}`,
    percent: limit !== null && limit > 0n && spent !== null ? Math.min(100, Number(spent * 10_000n / limit) / 100) : null,
    title: `Cheltuieli din registrul furnizorilor, fără dublarea facturilor și estimărilor. ${usd(held)} USD rezervați separat; disponibilul ține cont de rezervări. Costurile LLM pe abonament nu se adaugă.`,
  };
}
/** The completion event is emitted with the terminal run, never the task's start. @param {any} event @param {ReturnType<typeof dayWindow>} window */
export function completionRecord(event, window) {
  if (event?.event_type !== 'agent.run_completed' || event.payload?.status !== 'SUCCEEDED' || !event.aggregate_id) return null;
  const completed = Date.parse(event.payload.finished_at || event.timestamp);
  if (!Number.isFinite(completed) || completed < window.start || completed >= window.next) return null;
  return { id: String(event.aggregate_id), status: 'COMPLETED', completed_at: event.payload.finished_at || event.timestamp };
}
