import { dayTrackWords } from './hud_charts.js';
import { listWords } from './hq_screens.js';
import { sheetKeyFor } from './sheet_key.js';

/**
 * THE STUDIO AT A GLANCE, at the foot of the side drawer on a tall screen (W8).
 *
 * At 2560x1440 the governance drawer ended its module list with about 350px of bare glass under
 * it. It now closes on three lines the page already holds, word for word from their sources:
 * - the day's run, in the slate's own words (hud_charts.js dayTrackWords);
 * - the actual daily USD budget, remaining amount and spend from the budget projection;
 * - the next scheduled daily run, from /scheduler/jobs, said the way the daily-run dialog says it:
 *   a time only while the job is active and autonomy is on, because a time beside a stopped
 *   studio would promise a run that cannot happen.
 * A value the page does not hold is «—». Nothing here is computed beyond what its source says.
 *
 * PAGE_OWNER_DAY (PAGE-14): a fourth line, «Filmul zilei», from the newest run's own stages: where
 * the day's film stands (waiting for him at a step, in production, assembled with its QC,
 * published and how) and, when it has a sheet, the key to it.
 */

/**
 * @typedef {{label: string, value: string, note?: string, tone?: 'ok'|'warn'|'alert'|'quiet', sheet?: string|null}} ReadoutRow
 */

/** A paid step, as the line says where the film waits. */
const STEP_PLACE = { stills: 'imagini', test_shot: 'cadrul de probă', motion: 'mișcare', assemble: 'narațiune', scene_redo: 'o refacere' };

/** How a film was published, in words. */
const PRIVACY_WORDS = { private: 'privat', unlisted: 'nelistat', public: 'public' };

/**
 * «18 credite», «358 de credite».
 * @param {number} n
 */
function creditsWords(n) {
  if (n === 1) return '1 credit';
  const rest = Math.abs(n) % 100;
  return `${n.toLocaleString('ro-RO')}${Math.abs(n) >= 20 && (rest === 0 || rest >= 20) ? ' de' : ''} credite`;
}

/**
 * The film of the day, from the newest run (GET /runbook/runs, its stages' artefacts).
 * @param {any} run
 * @returns {ReadoutRow}
 */
export function filmOfTheDay(run) {
  const label = 'Filmul zilei';
  if (!run || !Array.isArray(run.stages)) return { label, value: '—', tone: 'quiet' };
  /** @param {string} name */
  const stage = (name) => {
    const found = run.stages.find((/** @type {any} */ s) => s && s.stage === name);
    return found && found.artefacts && typeof found.artefacts === 'object' ? found.artefacts : null;
  };
  const media = stage('media');
  const qc = stage('edit_and_qc');
  const publish = stage('publish');
  const published = publish && Array.isArray(publish.published) ? publish.published[0] : null;
  if (published) {
    const privacy = PRIVACY_WORDS[/** @type {keyof typeof PRIVACY_WORDS} */ (published.release_privacy)] || String(published.release_privacy || '');
    return { label, value: `publicat ${privacy}`.trim(), note: published.channel_name ? String(published.channel_name) : undefined, tone: 'ok' };
  }
  if (!media) return { label, value: 'niciun film azi', tone: 'quiet' };
  const films = Array.isArray(media.films) ? media.films : [];
  const sheet = sheetKeyFor(media) || (films[0] && sheetKeyFor({ awaiting_owner: [films[0]] })) || null;
  const bought = (Array.isArray(media.bought_steps) ? media.bought_steps : []).reduce((sum, /** @type {any} */ b) => sum + (Number(b && b.credits) || 0), 0);
  const note = bought > 0 ? `cumpărat până acum: ${creditsWords(bought)}` : undefined;
  const assembled = (Array.isArray(media.assets) && media.assets.length > 0) || films.some((/** @type {any} */ f) => f && f.status === 'ASSEMBLED');
  if (assembled && qc && Number(qc.failed) > 0 && !Number(qc.passed)) return { label, value: 'QC picat', note, tone: 'alert', sheet };
  if (assembled && qc && Number(qc.passed) > 0) return { label, value: 'asamblat, QC trecut', note, tone: 'ok', sheet };
  if (assembled) return { label, value: 'asamblat', note, tone: 'ok', sheet };
  const waiting = Array.isArray(media.awaiting_owner) ? media.awaiting_owner[0] : null;
  if (waiting) {
    const place = STEP_PLACE[/** @type {keyof typeof STEP_PLACE} */ (waiting.step)] || 'un pas plătit';
    return { label, value: `te așteaptă la ${place}`, note, tone: 'warn', sheet };
  }
  const first = films[0];
  if (first && first.status === 'WAITING') return { label, value: 'așteaptă decizia ta pe foaia de filmare', note, tone: 'warn', sheet };
  if (first && first.status === 'HELD') return { label, value: 'oprit înainte de un pas plătit', note, tone: 'warn', sheet };
  if (first && first.status === 'REFUSED') return { label, value: 'asamblarea a fost refuzată', note, tone: 'alert', sheet };
  if (bought > 0 || first) return { label, value: 'în producție', note, tone: 'ok', sheet };
  return { label, value: 'niciun film azi', tone: 'quiet' };
}

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
 * @param {{track?: any, today?: string|null, live?: boolean, treasury?: any, budget?: any, jobs?: any[]|null, stopped?: boolean|null, timeZone?: string, reads?: Record<string, string>, run?: any}} facts
 *   `reads`: how each list was read ('pending', 'ok', 'failed'); a list not read is never «nicio …» (W12)
 * @returns {{rows: ReadoutRow[], key: string}}
 */
export function studioReadout(facts) {
  /** @type {ReadoutRow[]} */
  const rows = [];
  const track = facts.track;
  if (track && !track.empty) {
    const words = dayTrackWords(track, { today: facts.today ?? null, live: facts.live });
    const [title, ...rest] = words.label.split(' · ');
    // W35: under «Studioul azi», a run of another day is the last run, not the day's (the judge
    // read «RULAREA ZILEI 12/12 · încheiată» on 25.09 for the run of 12.09)
    const todays = Boolean(track.date && facts.today && track.date === facts.today);
    rows.push({ label: todays ? 'Rularea zilei' : 'Ultima rulare', value: rest.join(' · ') || '—', note: title, tone: track.running && facts.live !== false ? 'ok' : 'quiet' });
  } else {
    rows.push({ label: 'Rularea zilei', value: listWords(facts.reads && facts.reads.runs, 'nicio rulare în registru'), tone: 'quiet' });
  }
  const daily = facts.budget?.budgets?.find(b => b.period === 'DAILY');
  rows.push({ label: 'Buget zilnic', value: daily ? `${daily.remaining_usd} USD disponibili` : '—', note: daily ? `${daily.spent_usd} / ${daily.limit_usd} USD cheltuiți` : 'bugetul nu este disponibil', tone: daily?.state === 'EXCEEDED' ? 'alert' : 'quiet' });
  const next = nextRunWords(facts.jobs, { stopped: facts.stopped, timeZone: facts.timeZone });
  rows.push({ label: 'Următoarea rulare', value: next.value, tone: next.tone });
  rows.push(filmOfTheDay(facts.run));
  return { rows, key: rows.map((r) => `${r.label}|${r.value}|${r.note || ''}|${r.tone || ''}|${r.sheet || ''}`).join('#') };
}
