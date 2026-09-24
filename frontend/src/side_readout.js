import { dayTrackWords } from './hud_charts.js';
import { treasuryFace } from './hq_screens.js';

/**
 * THE STUDIO AT A GLANCE, at the foot of the side drawer on a tall screen (W8).
 *
 * At 2560x1440 the governance drawer ended its module list with about 350px of bare glass under
 * it. It now closes on three lines the page already holds, word for word from their sources:
 * - the day's run, in the slate's own words (hud_charts.js dayTrackWords);
 * - the treasury: the spendable VR$ balance and today's spend against the daily budget, as the
 *   Treasury's wall screen in the building says them (hq_screens.js treasuryFace);
 * - the next scheduled daily run, from /scheduler/jobs, said the way the daily-run dialog says it:
 *   a time only while the job is active and autonomy is on, because a time beside a stopped
 *   studio would promise a run that cannot happen.
 * A value the page does not hold is «—». Nothing here is computed beyond what its source says.
 */

/**
 * @typedef {{label: string, value: string, note?: string, tone?: 'ok'|'warn'|'alert'|'quiet'}} ReadoutRow
 */

/**
 * The next daily run, in words.
 * @param {any[]|null|undefined} jobs /scheduler/jobs
 * @param {{stopped?: boolean|null, timeZone?: string}} [context]
 * @returns {{value: string, tone: 'ok'|'warn'|'quiet'}}
 */
export function nextRunWords(jobs, context = {}) {
  if (!Array.isArray(jobs)) return { value: '—', tone: 'quiet' };
  const daily = jobs.find((job) => job && job.workflow_type === 'DAILY_RUN');
  if (!daily) return { value: 'nicio treabă zilnică programată', tone: 'quiet' };
  if (!daily.is_active) return { value: 'programarea zilnică este oprită', tone: 'warn' };
  if (context.stopped) return { value: 'autonomia este oprită', tone: 'warn' };
  const at = Date.parse(String(daily.next_run_at || ''));
  if (!Number.isFinite(at)) return { value: '—', tone: 'quiet' };
  let text;
  try {
    text = new Date(at).toLocaleString('ro-RO', { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', timeZone: context.timeZone });
  } catch {
    text = new Date(at).toLocaleString('ro-RO');
  }
  return { value: text, tone: 'ok' };
}

/**
 * The three lines.
 * @param {{track?: any, today?: string|null, live?: boolean, treasury?: any, budget?: any, jobs?: any[]|null, stopped?: boolean|null, timeZone?: string}} facts
 * @returns {{rows: ReadoutRow[], key: string}}
 */
export function studioReadout(facts) {
  /** @type {ReadoutRow[]} */
  const rows = [];
  const track = facts.track;
  if (track && !track.empty) {
    const words = dayTrackWords(track, { today: facts.today ?? null, live: facts.live });
    const [title, ...rest] = words.label.split(' · ');
    rows.push({ label: 'Rularea zilei', value: rest.join(' · ') || '—', note: title, tone: track.running && facts.live !== false ? 'ok' : 'quiet' });
  } else {
    rows.push({ label: 'Rularea zilei', value: track ? 'nicio rulare în registru' : '—', tone: 'quiet' });
  }
  if (facts.treasury || facts.budget) {
    const face = treasuryFace(facts.treasury, facts.budget);
    rows.push({
      label: 'Trezorerie',
      value: face.balance === '—' ? '—' : `${face.balance} VR$ cheltuibili`,
      note: face.line,
      tone: face.deficit ? 'alert' : face.state && face.state !== 'OK' ? 'warn' : 'quiet',
    });
  } else {
    rows.push({ label: 'Trezorerie', value: '—', tone: 'quiet' });
  }
  const next = nextRunWords(facts.jobs, { stopped: facts.stopped, timeZone: facts.timeZone });
  rows.push({ label: 'Următoarea rulare', value: next.value, tone: next.tone });
  return { rows, key: rows.map((r) => `${r.label}|${r.value}|${r.note || ''}|${r.tone || ''}`).join('#') };
}
