/**
 * THE INSTRUMENTS THAT DRAW NUMBERS (W6).
 *
 * Every mark on these charts is one field the backend already returns, and nothing else:
 *
 *  - the DAY TRACKER in the bezel reads the runbook's own events (`runbook.daily_run_started`,
 *    `runbook.stage_started` with its index and total, `runbook.stage_finished` with its status,
 *    `runbook.daily_run_finished`) and lights one segment per stage of the newest day;
 *  - the PIPELINE in the daily-run dialog is `/runbook/company-state` → `pipeline.stages`;
 *  - the BUDGET RING in the treasury is one row of `/economy/budget` → `budgets[]`;
 *  - the CHANNEL BARS are `/analytics/performance` → `videos[]`, one bar per film of a channel.
 *
 * No chart is drawn for a figure the backend did not give: a missing series returns `empty` with
 * the words that say so, and the caller prints those words instead of a chart. The geometry is
 * computed here, pure, so a node test can put a fixture in and read the marks out; the markup
 * builders only turn that geometry into SVG attributes (never a `style` attribute: the page's
 * Content-Security-Policy forbids inline style) and classes the stylesheet colours with tokens.
 */

import { escapeHtml } from './html.js';

/* ------------------------------------------------------------------------------------------
 * THE DAY TRACKER
 * ---------------------------------------------------------------------------------------- */

/** The stages as the Owner reads them; an unknown name is shown as it came. */
export const RUN_STAGE_WORD = {
  preflight: 'verificarea preliminară',
  performance_intake: 'preluarea performanței',
  idea_generation: 'generarea de idei',
  research_and_verification: 'documentare și verificare',
  selection: 'alegerea subiectului',
  script_and_storyboard: 'scenariu și storyboard',
  serial_queue: 'episodul din serial',
  media: 'producție media',
  edit_and_qc: 'montaj și controlul calității',
  publish: 'publicare',
  post_run: 'raportare și închiderea zilei',
  daily_log: 'jurnalul zilei',
  serial_next: 'scenariul de mâine',
};

/** @param {string|null|undefined} stage */
export function runStageWord(stage) {
  return RUN_STAGE_WORD[/** @type {keyof typeof RUN_STAGE_WORD} */ (String(stage))] || String(stage || '').replace(/_/g, ' ');
}

/** A finished stage's status → the segment's class and its word (after «etapă», feminine). */
const SEGMENT_STATUS = {
  COMPLETED: ['done', 'încheiată'],
  SUCCEEDED: ['done', 'încheiată'],
  PARTIAL: ['partial', 'parțială'],
  FAILED: ['failed', 'eșuată'],
  BLOCKED: ['failed', 'blocată'],
  SKIPPED: ['skipped', 'sărită'],
};

/** The preflight's verdict (daily_run_started.payload.preflight) → the first segment. */
const PREFLIGHT_STATUS = {
  READY: ['done', 'trecută'],
  DEGRADED: ['partial', 'cu limitări'],
  BLOCKED: ['failed', 'blocantă'],
};

/**
 * @typedef {{index: number, stage: string|null, state: string, word: string}} TrackSegment
 * @typedef {{
 *   empty: boolean, text: string,
 *   date: string|null, total: number, segments: TrackSegment[],
 *   finished: boolean, status: string|null, running: string|null, closed: number,
 *   startedAt?: number|null, source?: string,
 * }} DayTrack
 */

/**
 * The newest daily run, read from the events the page holds (newest first, as the register
 * sorts them). Segments are placed by the index the backend put on each `stage_started`, so the
 * page never assumes an order the runbook may change; a stage that has not started yet is an
 * unnamed, unlit slot.
 *
 * @param {Array<{event_type?: string, payload?: any, timestamp?: string, aggregate_id?: string}>} events newest first
 * @returns {DayTrack}
 */
export function dayTrack(events) {
  const list = Array.isArray(events) ? events : [];
  // The newest run: the first start or stage event met from the top decides which run it is.
  let runId = null;
  let startIndex = -1;
  for (let i = 0; i < list.length; i += 1) {
    const type = String(list[i]?.event_type || '');
    if (type === 'runbook.daily_run_started') {
      startIndex = i;
      runId = list[i].aggregate_id || null;
      break;
    }
  }
  // Everything newer than that start belongs to it (a run's events are contiguous in time: the
  // runbook runs one day at a time). Without a start in the register, the newest stage events
  // still describe the day that is on screen, from their own index and total.
  const scope = startIndex >= 0 ? list.slice(0, startIndex + 1) : list;
  const started = startIndex >= 0 ? list[startIndex] : null;
  const payload = (started && started.payload) || {};
  let total = Number(payload.stages) || 0;
  /** @type {Map<number, TrackSegment>} */
  const byIndex = new Map();
  /** @type {Map<string, number>} */
  const indexOf = new Map();
  /** @type {Map<string, string>} */
  const finishedStatus = new Map();
  let finished = null;
  let sawStage = false;
  // Oldest first, so a stage's finish lands after its start.
  for (let i = scope.length - 1; i >= 0; i -= 1) {
    const event = scope[i];
    const type = String(event?.event_type || '');
    const p = (event && event.payload) || {};
    if (type === 'runbook.stage_started' && p.stage) {
      sawStage = true;
      const index = Number(p.index);
      if (Number.isFinite(index) && index >= 1) {
        indexOf.set(String(p.stage), index);
        total = Math.max(total, Number(p.total) || 0, index);
      }
    } else if (type === 'runbook.stage_finished' && p.stage) {
      sawStage = true;
      finishedStatus.set(String(p.stage), String(p.status || ''));
    } else if (type === 'runbook.daily_run_finished') {
      finished = p;
    }
  }
  if (!started && !sawStage) {
    return {
      empty: true,
      text: 'Nicio rulare a zilei în registru',
      date: null, total: 0, segments: [], finished: false, status: null, running: null, closed: 0,
    };
  }
  // The preflight is the first stage and has no start event of its own: its verdict rides on
  // the day's start.
  if (started) {
    const verdict = PREFLIGHT_STATUS[/** @type {keyof typeof PREFLIGHT_STATUS} */ (String(payload.preflight))];
    byIndex.set(1, {
      index: 1,
      stage: 'preflight',
      state: verdict ? verdict[0] : 'done',
      word: verdict ? verdict[1] : String(payload.preflight || '').toLowerCase(),
    });
    total = Math.max(total, 1);
  }
  let running = null;
  for (const [stage, index] of indexOf) {
    const status = finishedStatus.get(stage);
    const mapped = status ? SEGMENT_STATUS[/** @type {keyof typeof SEGMENT_STATUS} */ (status)] : null;
    if (status) {
      byIndex.set(index, { index, stage, state: mapped ? mapped[0] : 'done', word: mapped ? mapped[1] : status.toLowerCase() });
    } else if (finished) {
      // The day ended without this stage finishing: it did not run to its end.
      byIndex.set(index, { index, stage, state: 'failed', word: 'neterminată' });
    } else {
      byIndex.set(index, { index, stage, state: 'running', word: 'în lucru' });
      running = stage;
    }
  }
  /** @type {TrackSegment[]} */
  const segments = [];
  for (let index = 1; index <= total; index += 1) {
    segments.push(
      byIndex.get(index) || {
        index,
        stage: null,
        state: finished ? 'unrun' : 'pending',
        word: finished ? 'nerulată' : 'încă nu a început',
      },
    );
  }
  const closed = segments.filter((s) => s.state !== 'pending' && s.state !== 'running' && s.state !== 'unrun').length;
  const date = typeof payload.date === 'string' ? payload.date : null;
  const first = started || scope[scope.length - 1];
  const startedAt = first ? Date.parse(String(first.timestamp || '')) : NaN;
  return {
    empty: false,
    text: '',
    date,
    total,
    segments,
    finished: Boolean(finished),
    status: finished ? String(finished.status || '') || null : null,
    running,
    closed,
    startedAt: Number.isFinite(startedAt) ? startedAt : null,
    source: 'events',
  };
}

/**
 * The same tracker from the runbook's own record of a finished day (`/runbook/runs` -> `runs[0]`):
 * the register holds at most its newest 400 events, and a day's stage events can have scrolled
 * out of it behind the watchdog's rows while the record still says how the day went.
 *
 * @param {{business_date?: string, status?: string, started_at?: string, stages_total?: number,
 *          stages?: Array<{stage?: string, status?: string}>}|null|undefined} run
 * @returns {DayTrack|null}
 */
export function dayTrackFromRun(run) {
  if (!run || !Array.isArray(run.stages) || !run.stages.length) return null;
  const total = Math.max(Number(run.stages_total) || 0, run.stages.length);
  /** @type {TrackSegment[]} */
  const segments = [];
  for (let index = 1; index <= total; index += 1) {
    const stage = run.stages[index - 1];
    if (!stage) {
      segments.push({ index, stage: null, state: 'unrun', word: 'nerulată' });
      continue;
    }
    const mapped = SEGMENT_STATUS[/** @type {keyof typeof SEGMENT_STATUS} */ (String(stage.status))];
    segments.push({
      index,
      stage: stage.stage ? String(stage.stage) : null,
      state: mapped ? mapped[0] : 'done',
      word: mapped ? mapped[1] : String(stage.status || '').toLowerCase(),
    });
  }
  const startedAt = Date.parse(String(run.started_at || ''));
  return {
    empty: false,
    text: '',
    date: typeof run.business_date === 'string' ? run.business_date : null,
    total,
    segments,
    finished: true,
    status: run.status ? String(run.status) : null,
    running: null,
    closed: segments.filter((s) => s.state !== 'unrun').length,
    startedAt: Number.isFinite(startedAt) ? startedAt : null,
    source: 'record',
  };
}

/**
 * Which day the slate shows: the newer of what the register's events describe and what the
 * runbook recorded. A day under way exists only in the events; a finished day is in both, and
 * the record is complete where the register may have lost the start of it.
 *
 * @param {DayTrack} fromEvents
 * @param {DayTrack|null} fromRecord
 * @returns {DayTrack}
 */
export function newerTrack(fromEvents, fromRecord) {
  if (!fromRecord) return fromEvents;
  if (fromEvents.empty) return fromRecord;
  const a = fromEvents.startedAt ?? -Infinity;
  const b = fromRecord.startedAt ?? -Infinity;
  return a > b ? fromEvents : fromRecord;
}

/** A business date '2026-09-12' as the slate prints it: '12.09'. */
export function shortDate(iso) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ''));
  return match ? `${match[3]}.${match[2]}` : '';
}

/** One segment's size on the bezel, in SVG user units (1 unit = 1 CSS px at scale 1). */
export const TRACK_SEGMENT = { w: 14, h: 6, gap: 3 };

/**
 * The tracker's geometry: one rectangle per segment, left to right in the backend's order.
 * @param {DayTrack} track
 */
export function dayTrackGeometry(track, seg = TRACK_SEGMENT) {
  const n = track.segments.length;
  const width = n ? n * seg.w + (n - 1) * seg.gap : 0;
  return {
    width,
    height: seg.h,
    rects: track.segments.map((s, i) => ({ x: i * (seg.w + seg.gap), y: 0, w: seg.w, h: seg.h, state: s.state, index: s.index, stage: s.stage })),
  };
}

/**
 * The words that go with the tracker: a short label on the bezel and the full sentence for the
 * tooltip and the screen reader. `today` is the studio's own business date, so a run from
 * another day says which day it was.
 *
 * @param {DayTrack} track
 * @param {{today?: string|null, live?: boolean}} [context]
 */
export function dayTrackWords(track, context = {}) {
  if (track.empty) return { label: track.text, short: 'Nicio rulare', sentence: `${track.text}.` };
  const when = track.date && context.today && track.date === context.today ? 'de azi' : track.date ? `din ${shortDate(track.date)}` : 'din registru';
  const tally = `${track.closed}/${track.total}`;
  let state;
  if (track.finished) {
    const status = SEGMENT_STATUS[/** @type {keyof typeof SEGMENT_STATUS} */ (String(track.status))];
    state = status ? status[1] : String(track.status || '').toLowerCase() || 'încheiată';
  } else if (track.running) {
    state = context.live === false ? `ultima etapă începută: ${runStageWord(track.running)}` : `acum: ${runStageWord(track.running)}`;
  } else {
    state = 'în lucru';
  }
  const label = `Rularea ${when} · ${tally} · ${state}`;
  const stages = track.segments
    .map((s) => `${s.index}. ${s.stage ? runStageWord(s.stage) : 'etapă'}: ${s.word}`)
    .join('; ');
  return {
    label,
    // For a slate too narrow for the sentence: the day and the tally, nothing that needs a verb.
    short: `${track.date && context.today && track.date === context.today ? 'Azi' : shortDate(track.date) || 'Rularea'} · ${tally}`,
    sentence: `Rularea zilei ${when}: ${track.closed} din ${track.total} etape închise, ${state}. ${stages}.`,
  };
}

/* ------------------------------------------------------------------------------------------
 * THE PIPELINE (daily-run dialog)
 * ---------------------------------------------------------------------------------------- */

/**
 * The six rows the dialog's «Flux» line always named, in its order, each with the loss the
 * backend counts beside it. `waiting` is work queued at that stage, not lost.
 */
export const PIPELINE_ROWS = [
  { key: 'topics_proposed', label: 'teme propuse' },
  { key: 'topics_selected', label: 'selectate' },
  { key: 'scripts_approved', label: 'scenarii aprobate', waiting: 'scripts_awaiting_review', lost: 'scripts_blocked', lostWord: 'blocate' },
  { key: 'storyboards_approved', label: 'storyboard-uri', lost: 'storyboards_rejected', lostWord: 'respinse' },
  { key: 'renders_completed', label: 'randate', lost: 'renders_failed', lostWord: 'eșuate' },
  { key: 'published', label: 'publicate', lost: 'publications_failed', lostWord: 'eșuate' },
];

/** @param {unknown} value */
function count(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
}

/**
 * Bars on one scale, the largest figure on the chart filling the track. The stages are not a
 * funnel in this studio's data (renders can outnumber approved storyboards, because a render
 * outlives the day its storyboard was approved), so every row is measured from the same
 * baseline rather than tapered: the picture must not claim a narrowing the numbers do not have.
 *
 * @param {Record<string, unknown>|null|undefined} stages `pipeline.stages`
 * @param {number} [track] the bar track's width in user units
 */
export function pipelineGeometry(stages, track = 100) {
  if (!stages || typeof stages !== 'object') {
    return { empty: true, text: 'Fluxul nu a fost citit.', rows: [], max: 0 };
  }
  const known = PIPELINE_ROWS.some((row) => row.key in stages);
  if (!known) return { empty: true, text: 'Fluxul nu a fost citit.', rows: [], max: 0 };
  const rows = PIPELINE_ROWS.map((row) => ({
    key: row.key,
    label: row.label,
    value: count(stages[row.key]),
    waiting: row.waiting ? count(stages[row.waiting]) : 0,
    lost: row.lost ? count(stages[row.lost]) : 0,
    lostWord: row.lostWord || '',
  }));
  const max = Math.max(0, ...rows.map((r) => r.value + r.waiting + r.lost));
  const scale = max ? track / max : 0;
  return {
    empty: false,
    text: max ? '' : 'Nimic în flux încă.',
    max,
    rows: rows.map((r) => ({
      ...r,
      w: r.value * scale,
      waitW: r.waiting * scale,
      lostW: r.lost * scale,
    })),
  };
}

/** The same numbers, as the sentence the dialog used to print (the chart's text alternative). */
export function pipelineSentence(stages) {
  const s = stages || {};
  return `${count(s.topics_proposed)} teme propuse · ${count(s.topics_selected)} selectate · ${count(s.scripts_approved)} scenarii aprobate · ${count(s.storyboards_approved)} storyboard-uri · ${count(s.renders_completed)} randate · ${count(s.published)} publicate`;
}

/** The bar track of one pipeline row, in user units (the SVG stretches it to the row's width). */
export const PIPELINE_TRACK = 100;

/**
 * The pipeline as rows of words and bars: the label and the figure are page text, set at the
 * page's own sizes, and each bar is an SVG stretched across the space between them, so the
 * chart reads the same in a 250px card and in a 400px one.
 *
 * @param {Record<string, unknown>|null|undefined} stages
 * @param {{bottleneck?: {stage?: string, waiting?: number}|null}} [extra]
 */
export function pipelineSvg(stages, extra = {}) {
  const track = PIPELINE_TRACK;
  const g = pipelineGeometry(stages, track);
  if (g.empty || !g.max) return `<p class="chart-empty">${escapeHtml(g.text)}</p>`;
  const h = 8;
  const rows = g.rows
    .map((r) => {
      const parts = [`<rect class="chart-track" x="0" y="0" width="${track}" height="${h}"></rect>`];
      if (r.w > 0) parts.push(`<rect class="chart-bar" x="0" y="0" width="${round(r.w)}" height="${h}"></rect>`);
      if (r.waitW > 0) parts.push(`<rect class="chart-bar-wait" x="${round(r.w)}" y="0" width="${round(r.waitW)}" height="${h}"></rect>`);
      if (r.lostW > 0) parts.push(`<rect class="chart-bar-lost" x="${round(r.w + r.waitW)}" y="0" width="${round(r.lostW)}" height="${h}"></rect>`);
      return `<div class="pipe-row" data-key="${escapeHtml(r.key)}"><span class="pipe-label">${escapeHtml(r.label)}</span><svg class="pipe-bar" viewBox="0 0 ${track} ${h}" preserveAspectRatio="none" aria-hidden="true" focusable="false">${parts.join('')}</svg><span class="pipe-value">${r.value}</span></div>`;
    })
    .join('');
  const notes = g.rows
    .filter((r) => r.waiting || r.lost)
    .map((r) => {
      const bits = [];
      if (r.waiting) bits.push(`<span class="chart-note is-wait">${r.waiting} ${escapeHtml(r.label)} în așteptare</span>`);
      if (r.lost) bits.push(`<span class="chart-note is-lost">${r.lost} ${escapeHtml(r.lostWord)} la ${escapeHtml(r.label)}</span>`);
      return bits.join('');
    })
    .join('');
  const bottleneck = extra.bottleneck && extra.bottleneck.stage ? ` Blocaj la ${extra.bottleneck.stage}: ${count(extra.bottleneck.waiting)} în așteptare.` : '';
  return `<div class="chart chart-pipeline" role="img" aria-label="${escapeHtml(pipelineSentence(stages) + '.' + bottleneck)}">${rows}</div>${notes ? `<div class="chart-notes" aria-hidden="true">${notes}</div>` : ''}`;
}

/* ------------------------------------------------------------------------------------------
 * THE BUDGET RING (treasury)
 * ---------------------------------------------------------------------------------------- */

/** The ring's size, in user units. */
export const RING = { size: 72, r: 29, stroke: 6 };

/**
 * One budget as a ring: spent, then held for films in production, against the limit, with the
 * warning line where the Accountant escalates (`warn_ratio`). Micro-dollars are integers, so the
 * fractions are exact; a spend past the limit fills the ring and says by how much.
 *
 * @param {{limit_usd_micros?: number, spent_usd_micros?: number, reserved_usd_micros?: number, warn_ratio?: number, state?: string}|null|undefined} budget
 */
export function budgetRing(budget, ring = RING) {
  const limit = Number(budget && budget.limit_usd_micros);
  if (!budget || !Number.isFinite(limit) || limit <= 0) {
    return { empty: true, text: 'Fără buget: nicio limită pusă.' };
  }
  const spent = Math.max(0, Number(budget.spent_usd_micros) || 0);
  const reserved = Math.max(0, Number(budget.reserved_usd_micros) || 0);
  const circumference = 2 * Math.PI * ring.r;
  const spentFrac = Math.min(1, spent / limit);
  const reservedFrac = Math.min(1 - spentFrac, reserved / limit);
  const warn = Number(budget.warn_ratio);
  const warnFrac = Number.isFinite(warn) && warn > 0 && warn < 1 ? warn : null;
  // The ring starts at twelve o'clock and runs clockwise.
  const angle = (/** @type {number} */ f) => -Math.PI / 2 + f * 2 * Math.PI;
  const c = ring.size / 2;
  const tick = warnFrac === null
    ? null
    : {
        x1: c + (ring.r - ring.stroke) * Math.cos(angle(warnFrac)),
        y1: c + (ring.r - ring.stroke) * Math.sin(angle(warnFrac)),
        x2: c + (ring.r + ring.stroke) * Math.cos(angle(warnFrac)),
        y2: c + (ring.r + ring.stroke) * Math.sin(angle(warnFrac)),
      };
  return {
    empty: false,
    text: '',
    circumference,
    spentFrac,
    reservedFrac,
    warnFrac,
    over: spent > limit,
    // stroke-dasharray / offset for each arc, the reserved arc starting where the spent one ends.
    spentDash: `${round(spentFrac * circumference)} ${round(circumference)}`,
    reservedDash: `${round(reservedFrac * circumference)} ${round(circumference)}`,
    reservedOffset: round(-spentFrac * circumference),
    tick,
    percent: Math.round(((spent + reserved) / limit) * 100),
    state: String(budget.state || ''),
  };
}

/**
 * @param {Parameters<typeof budgetRing>[0]} budget
 * @param {string} label what the ring measures, for the screen reader
 */
export function budgetRingSvg(budget, label, ring = RING) {
  const g = budgetRing(budget, ring);
  if (g.empty) return `<p class="chart-empty">${escapeHtml(g.text)}</p>`;
  const c = ring.size / 2;
  const rotate = `rotate(-90 ${c} ${c})`;
  const tick = g.tick
    ? `<line class="ring-warn" x1="${round(g.tick.x1)}" y1="${round(g.tick.y1)}" x2="${round(g.tick.x2)}" y2="${round(g.tick.y2)}"><title>Linia de avertizare: ${Math.round((g.warnFrac || 0) * 100)}%</title></line>`
    : '';
  return `<svg class="chart chart-ring ring-${escapeHtml(g.state.toLowerCase())}${g.over ? ' is-over' : ''}" viewBox="0 0 ${ring.size} ${ring.size}" width="${ring.size}" height="${ring.size}" role="img" aria-label="${escapeHtml(label)}">` +
    `<circle class="ring-track" cx="${c}" cy="${c}" r="${ring.r}" stroke-width="${ring.stroke}" fill="none"></circle>` +
    (g.reservedFrac > 0 ? `<circle class="ring-reserved" cx="${c}" cy="${c}" r="${ring.r}" stroke-width="${ring.stroke}" fill="none" stroke-dasharray="${g.reservedDash}" stroke-dashoffset="${g.reservedOffset}" transform="${rotate}"></circle>` : '') +
    (g.spentFrac > 0 ? `<circle class="ring-spent" cx="${c}" cy="${c}" r="${ring.r}" stroke-width="${ring.stroke}" fill="none" stroke-dasharray="${g.spentDash}" transform="${rotate}"></circle>` : '') +
    tick +
    `<text class="ring-figure" x="${c}" y="${c}" text-anchor="middle" dominant-baseline="central">${g.percent}%</text>` +
    `</svg>`;
}

/* ------------------------------------------------------------------------------------------
 * THE CHANNEL BARS (distribution dialog)
 * ---------------------------------------------------------------------------------------- */

/** Layout of one channel's bars, in user units. */
export const FILM_BARS = { height: 40, bar: 12, gap: 6, dot: 3 };

/**
 * One column per film the channel published, oldest to newest. A measured film stands as tall as
 * its views against the channel's best, a measured zero is a tick on the baseline (which is what
 * zero looks like), and a film YouTube has not measured yet has no height at all: it is a hollow
 * dot on the baseline of its column, because no number is known for it.
 *
 * @param {Array<{channel_id?: string, published_at?: string, measured?: boolean, views?: number|null, title?: string}>|null|undefined} videos
 * @param {string} channelId
 */
export function channelFilms(videos, channelId, layout = FILM_BARS) {
  const films = (Array.isArray(videos) ? videos : [])
    .filter((v) => v && v.channel_id === channelId)
    .sort((a, b) => String(a.published_at || '').localeCompare(String(b.published_at || '')));
  if (!films.length) return { empty: true, text: 'Niciun film publicat pe acest canal.', bars: [], measured: 0, views: 0 };
  const measured = films.filter((f) => f.measured && typeof f.views === 'number');
  const max = Math.max(0, ...measured.map((f) => /** @type {number} */ (f.views)));
  const floor = 2; // the height a measured zero is drawn at: a tick on the baseline
  const bars = films.map((f, i) => {
    const isMeasured = Boolean(f.measured) && typeof f.views === 'number';
    const views = isMeasured ? /** @type {number} */ (f.views) : null;
    const h = isMeasured ? (max ? floor + ((layout.height - floor) * /** @type {number} */ (views)) / max : floor) : 0;
    const x = i * (layout.bar + layout.gap);
    return {
      x,
      y: layout.height - h,
      w: layout.bar,
      h,
      measured: isMeasured,
      views,
      title: String(f.title || ''),
      dot: isMeasured ? null : { cx: x + layout.bar / 2, cy: layout.height - layout.dot - 1, r: layout.dot },
    };
  });
  const views = measured.reduce((sum, f) => sum + /** @type {number} */ (f.views), 0);
  return {
    empty: false,
    text: '',
    bars,
    measured: measured.length,
    unmeasured: films.length - measured.length,
    views,
    width: films.length * layout.bar + (films.length - 1) * layout.gap,
  };
}

/** «1 film», «2 filme», «20 de filme». */
export function filmsWord(n) {
  if (n === 1) return '1 film';
  const rest = n % 100;
  return `${n} ${n >= 20 && (rest === 0 || rest >= 20) ? 'de filme' : 'filme'}`;
}

/** «1 vizualizare», «0 vizualizări», «25 de vizualizări». */
export function viewsWord(n) {
  if (n === 1) return '1 vizualizare';
  const rest = n % 100;
  return `${n} ${n >= 20 && (rest === 0 || rest >= 20) ? 'de vizualizări' : 'vizualizări'}`;
}

/**
 * @param {Parameters<typeof channelFilms>[0]} videos
 * @param {string} channelId
 */
export function channelFilmsHtml(videos, channelId, layout = FILM_BARS) {
  const g = channelFilms(videos, channelId, layout);
  if (g.empty) return `<p class="chart-empty">${escapeHtml(g.text)}</p>`;
  const summary = `${filmsWord(g.bars.length)} · ${g.measured} ${g.measured === 1 ? 'măsurat' : 'măsurate'}${g.measured ? ` · ${viewsWord(g.views)}` : ''}`;
  const bars = g.bars
    .map((b) => {
      const title = `<title>${escapeHtml(b.title)}: ${b.measured ? viewsWord(/** @type {number} */ (b.views)) : 'nemăsurat încă'}</title>`;
      const slot = `<rect class="chart-track" x="${b.x}" y="0" width="${b.w}" height="${layout.height}" rx="1.5"></rect>`;
      const mark = b.dot
        ? `<circle class="film-unmeasured" cx="${b.dot.cx}" cy="${b.dot.cy}" r="${b.dot.r}"></circle>`
        : `<rect class="film-bar" x="${b.x}" y="${round(b.y)}" width="${b.w}" height="${round(b.h)}" rx="1.5"></rect>`;
      return `<g class="film">${title}${slot}${mark}</g>`;
    })
    .join('');
  return `<div class="channel-films"><svg class="chart chart-films" viewBox="0 0 ${g.width} ${layout.height}" width="${g.width}" height="${layout.height}" role="img" aria-label="${escapeHtml(summary)}"><line class="film-base" x1="0" y1="${layout.height - 0.5}" x2="${g.width}" y2="${layout.height - 0.5}"></line>${bars}</svg><span class="channel-films-words">${escapeHtml(summary)}</span></div>`;
}

/** Two decimals are finer than any screen pixel these charts are drawn at. */
function round(n) {
  return Math.round(n * 100) / 100;
}
