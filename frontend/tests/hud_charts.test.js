import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { productionStatus } from '../src/ledger.js';
import {
  PIPELINE_TRACK,
  RING,
  budgetRing,
  budgetRingSvg,
  channelFilms,
  channelFilmsHtml,
  dayTrack,
  dayTrackFromRun,
  dayTrackGeometry,
  dayTrackWords,
  pipelineGeometry,
  pipelineSentence,
  newerTrack,
  pipelineSvg,
  runStageWord,
} from '../src/hud_charts.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));

// The runbook's events as the backend writes them (backend/app/runbook/services.py), newest
// first, the way the register holds them. The copy of the studio's database has this run.
const at = (s) => `2026-09-12T07:${s}+00:00`;
const run = [
  { event_type: 'runbook.daily_run_started', aggregate_id: 'run-1', timestamp: at('36:33'), payload: { date: '2026-09-12', preflight: 'READY', stages: 12 } },
  { event_type: 'runbook.stage_started', timestamp: at('36:33'), payload: { stage: 'performance_intake', index: 2, total: 12 } },
  { event_type: 'runbook.stage_finished', timestamp: at('36:33'), payload: { stage: 'performance_intake', status: 'COMPLETED' } },
  { event_type: 'runbook.stage_started', timestamp: at('36:34'), payload: { stage: 'idea_generation', index: 3, total: 12 } },
  { event_type: 'agent.message_posted', timestamp: at('36:40'), payload: {} },
  { event_type: 'runbook.stage_finished', timestamp: at('36:59'), payload: { stage: 'idea_generation', status: 'PARTIAL' } },
  { event_type: 'runbook.stage_started', timestamp: at('36:59'), payload: { stage: 'research_and_verification', index: 4, total: 12 } },
  { event_type: 'runbook.stage_finished', timestamp: at('37:08'), payload: { stage: 'research_and_verification', status: 'FAILED' } },
  { event_type: 'runbook.stage_started', timestamp: at('37:08'), payload: { stage: 'selection', index: 5, total: 12 } },
].reverse();

test('the day tracker lights one segment per stage, placed by the index the backend gave it', () => {
  const track = dayTrack(run);
  assert.equal(track.empty, false);
  assert.equal(track.total, 12);
  assert.equal(track.date, '2026-09-12');
  assert.deepEqual(track.segments.map((s) => s.state), [
    'done', 'done', 'partial', 'failed', 'running', 'pending', 'pending', 'pending', 'pending', 'pending', 'pending', 'pending',
  ]);
  assert.equal(track.segments[0].stage, 'preflight');
  assert.equal(track.segments[4].stage, 'selection');
  assert.equal(track.running, 'selection');
  assert.equal(track.closed, 4);
  // a stage that has not started is an unnamed slot, not a guess at the order
  assert.equal(track.segments[6].stage, null);
});

test('the geometry is one rectangle per segment, evenly spaced, the running one in its place', () => {
  const g = dayTrackGeometry(dayTrack(run));
  assert.equal(g.rects.length, 12);
  assert.equal(g.width, 12 * 14 + 11 * 3);
  assert.deepEqual(g.rects.slice(0, 3).map((r) => r.x), [0, 17, 34]);
  assert.equal(g.rects[4].state, 'running');
  assert.equal(g.rects[4].x, 4 * 17);
});

test('the end of the day closes the run: an unfinished stage did not finish, an unstarted one did not run', () => {
  const ended = [
    { event_type: 'runbook.daily_run_finished', timestamp: at('40:00'), payload: { status: 'PARTIAL', stages_productive: 3 } },
    ...run,
  ];
  const track = dayTrack(ended);
  assert.equal(track.finished, true);
  assert.equal(track.segments[4].state, 'failed');
  assert.equal(track.segments[4].word, 'neterminată');
  assert.equal(track.segments[11].state, 'unrun');
  assert.equal(track.running, null);
  const words = dayTrackWords(track, { today: '2026-09-24' });
  assert.equal(words.label, 'Rularea din 12.09 · 5/12 · parțială');
  assert.equal(words.short, '12.09 · 5/12');
  assert.equal(dayTrackWords(track, { today: '2026-09-12' }).short, 'Azi · 5/12');
});

test('the words say which day, how far, and «acum» only while the register is live', () => {
  const track = dayTrack(run);
  assert.equal(dayTrackWords(track, { today: '2026-09-12', live: true }).label, 'Rularea de azi · 4/12 · acum: alegerea subiectului');
  assert.equal(
    dayTrackWords(track, { today: '2026-09-24', live: false }).label,
    'Rularea din 12.09 · 4/12 · ultima etapă începută: alegerea subiectului',
  );
  assert.match(dayTrackWords(track, {}).sentence, /1\. verificarea preliminară: trecută; 2\. preluarea performanței: încheiată/);
});

test('a newer day replaces the older one, and a register without a run says so in words', () => {
  const next = [
    { event_type: 'runbook.stage_started', timestamp: '2026-09-13T07:00:01+00:00', payload: { stage: 'performance_intake', index: 2, total: 12 } },
    { event_type: 'runbook.daily_run_started', aggregate_id: 'run-2', timestamp: '2026-09-13T07:00:00+00:00', payload: { date: '2026-09-13', preflight: 'DEGRADED', stages: 12 } },
    ...run,
  ];
  const track = dayTrack(next);
  assert.equal(track.date, '2026-09-13');
  assert.deepEqual(track.segments.slice(0, 3).map((s) => s.state), ['partial', 'running', 'pending']);
  const none = dayTrack([{ event_type: 'agent.message_posted', payload: {} }]);
  assert.equal(none.empty, true);
  assert.equal(dayTrackWords(none).label, 'Nicio rulare a zilei în registru');
  assert.equal(runStageWord('serial_queue'), 'episodul din serial');
});

// /runbook/company-state from the copy of the studio's database.
const companyState = JSON.parse(
  fs.readFileSync(path.join(HERE, 'fixtures', 'company_state.json'), 'utf8'),
);

test('the pipeline bars are the company state\'s own counts, on one scale', () => {
  const stages = companyState.pipeline.stages;
  const g = pipelineGeometry(stages, 200);
  assert.deepEqual(g.rows.map((r) => r.value), [5, 5, 2, 0, 5, 2]);
  // the longest row sets the scale: 2 approved + 29 waiting, and nothing is drawn past the track
  assert.equal(g.max, 31);
  const scripts = g.rows[2];
  assert.equal(scripts.waiting, 29);
  assert.equal(Math.round((scripts.w + scripts.waitW) * 100) / 100, 200);
  assert.equal(Math.round(g.rows[0].w * 1000) / 1000, Math.round((5 / 31) * 200 * 1000) / 1000);
  // losses sit beside the bar they came out of
  assert.equal(g.rows[3].lost, 1);
  assert.equal(g.rows[4].lost, 2);
  assert.equal(g.rows[3].w, 0);
  assert.equal(pipelineSentence(stages), '5 teme propuse · 5 selectate · 2 scenarii aprobate · 0 storyboard-uri · 5 randate · 2 publicate');
});

test('the pipeline rows draw the bars at the computed widths and says the numbers to a screen reader', () => {
  const svg = pipelineSvg(companyState.pipeline.stages, { bottleneck: companyState.pipeline.bottleneck });
  const track = PIPELINE_TRACK;
  const bars = [...svg.matchAll(/class="chart-bar" x="[\d.]+" y="[\d.]+" width="([\d.]+)"/g)].map((m) => Number(m[1]));
  // five non-zero rows (storyboards has none)
  assert.equal(bars.length, 5);
  assert.equal(bars[0], Math.round((5 / 31) * track * 100) / 100);
  assert.match(svg, /aria-label="5 teme propuse · 5 selectate · 2 scenarii aprobate · 0 storyboard-uri · 5 randate · 2 publicate\. Blocaj la APPROVAL: 29 în așteptare\."/);
  assert.match(svg, /29 scenarii aprobate în așteptare/);
  assert.doesNotMatch(svg, /style=/);
  assert.equal(pipelineSvg(null), '<p class="chart-empty">Fluxul nu a fost citit.</p>');
  assert.equal(pipelineSvg({ topics_proposed: 0 }), '<p class="chart-empty">Nimic în flux încă.</p>');
});

// /economy/budget → budgets[0] from the copy of the studio's database, then two spends.
const budget = { period: 'DAILY', limit_usd_micros: 15000000, spent_usd_micros: 0, reserved_usd_micros: 0, warn_ratio: 0.8, state: 'OK' };

test('the budget ring is spent then held against the limit, with the warning line where it is', () => {
  const empty = budgetRing(budget);
  assert.equal(empty.spentFrac, 0);
  assert.equal(empty.percent, 0);
  assert.equal(empty.warnFrac, 0.8);
  // 80% round a clock from twelve is at about ten to ten: left of centre and above it
  assert.ok(empty.tick.x1 < RING.size / 2 && empty.tick.y1 < RING.size / 2);
  const g = budgetRing({ ...budget, spent_usd_micros: 6000000, reserved_usd_micros: 3000000, state: 'OK' });
  const c = 2 * Math.PI * RING.r;
  assert.equal(g.spentFrac, 0.4);
  assert.equal(g.reservedFrac, 0.2);
  assert.equal(g.spentDash, `${Math.round(0.4 * c * 100) / 100} ${Math.round(c * 100) / 100}`);
  assert.equal(g.reservedOffset, Math.round(-0.4 * c * 100) / 100);
  assert.equal(g.percent, 60);
  const over = budgetRing({ ...budget, spent_usd_micros: 18000000, state: 'EXCEEDED' });
  assert.equal(over.spentFrac, 1);
  assert.equal(over.reservedFrac, 0);
  assert.equal(over.over, true);
  assert.equal(over.percent, 120);
});

test('the ring\'s SVG carries those arcs, and no limit is said in words, not drawn', () => {
  const svg = budgetRingSvg({ ...budget, spent_usd_micros: 6000000, reserved_usd_micros: 3000000 }, 'Zilnic: 6 din 15 USD');
  assert.match(svg, /class="ring-spent"[^>]*stroke-dasharray="72\.88 182\.21"/);
  assert.match(svg, /class="ring-reserved"[^>]*stroke-dashoffset="-72\.88"/);
  assert.match(svg, />60%</);
  assert.match(svg, /aria-label="Zilnic: 6 din 15 USD"/);
  // nothing spent, nothing held: the track and the warning line only
  const zero = budgetRingSvg(budget, 'Zilnic');
  assert.doesNotMatch(zero, /ring-spent|ring-reserved/);
  assert.match(zero, /ring-warn/);
  assert.equal(budgetRingSvg({ ...budget, limit_usd_micros: 0 }, 'x'), '<p class="chart-empty">Fără buget: nicio limită pusă.</p>');
  assert.equal(budgetRingSvg(null, 'x'), '<p class="chart-empty">Fără buget: nicio limită pusă.</p>');
});

// /analytics/performance from the copy of the studio's database: channel A has two films, one
// measured at zero views and one YouTube has not measured.
const performance = JSON.parse(fs.readFileSync(path.join(HERE, 'fixtures', 'analytics_performance.json'), 'utf8'));
const CHANNEL_A = '23d3ba8b-5f3c-4a99-9ab8-4993fe108f1a';
const CHANNEL_B = '34acf9d6-d5e2-4891-a494-7dafc27a4438';

test('a channel\'s bars are its films, oldest first: a measured zero is a tick, an unmeasured film has no height', () => {
  const g = channelFilms(performance.videos, CHANNEL_A);
  assert.equal(g.bars.length, 2);
  // 18:01 (measured, 0 views) was published before 20:58 (not measured)
  assert.deepEqual(g.bars.map((b) => b.measured), [true, false]);
  assert.equal(g.bars[0].h, 2);
  assert.equal(g.bars[0].y, 38);
  assert.equal(g.bars[0].dot, null);
  assert.equal(g.bars[1].h, 0);
  assert.deepEqual(g.bars[1].dot, { cx: 18 + 6, cy: 36, r: 3 });
  assert.equal(g.measured, 1);
  assert.equal(g.views, 0);
  const html = channelFilmsHtml(performance.videos, CHANNEL_A);
  assert.match(html, /2 filme · 1 măsurat · 0 vizualizări/);
  assert.match(html, /The Universe's Missing Pieces: Why the LHC Upgrade Matters: 0 vizualizări|The Universe&#39;s Missing Pieces: Why the LHC Upgrade Matters: 0 vizualizări/);
  assert.match(html, /nemăsurat încă/);
  assert.equal(channelFilmsHtml(performance.videos, CHANNEL_B), '<p class="chart-empty">Niciun film publicat pe acest canal.</p>');
});

test('views set the height against the channel\'s best film', () => {
  const videos = [
    { channel_id: 'c', published_at: '1', measured: true, views: 50, title: 'a' },
    { channel_id: 'c', published_at: '2', measured: true, views: 200, title: 'b' },
    { channel_id: 'c', published_at: '3', measured: true, views: 0, title: 'c' },
    { channel_id: 'x', published_at: '4', measured: true, views: 999, title: 'other channel' },
  ];
  const g = channelFilms(videos, 'c');
  assert.deepEqual(g.bars.map((b) => b.h), [2 + 38 * 0.25, 40, 2]);
  assert.equal(g.views, 250);
  assert.match(channelFilmsHtml(videos, 'c'), /3 filme · 3 măsurate · 250 de vizualizări/);
});

// /runbook/runs -> runs[0] from the copy of the studio's database: the evening run of 12.09,
// twelve stages, all COMPLETED.
const runRecord = JSON.parse(fs.readFileSync(path.join(HERE, 'fixtures', 'runbook_run.json'), 'utf8'));

test('a finished day reads from the runbook record when the register lost its start', () => {
  const record = dayTrackFromRun(runRecord);
  assert.equal(record.total, 12);
  assert.equal(record.closed, 12);
  assert.equal(record.finished, true);
  assert.deepEqual([...new Set(record.segments.map((s) => s.state))], ['done']);
  assert.equal(record.segments[6].stage, runRecord.stages[6].stage);
  assert.equal(dayTrackWords(record, { today: '2026-09-24' }).label, 'Rularea din 12.09 · 12/12 · încheiată');
  // the morning's events (07:36) are older than the recorded evening run (20:48): the record wins
  assert.equal(newerTrack(dayTrack(run), record), record);
  // a day starting after the record is shown from its events
  const later = [{ event_type: 'runbook.daily_run_started', timestamp: '2026-09-13T07:00:00+00:00', payload: { date: '2026-09-13', preflight: 'READY', stages: 12 } }];
  assert.equal(newerTrack(dayTrack(later), record).date, '2026-09-13');
  assert.equal(newerTrack(dayTrack([]), record), record);
  assert.equal(newerTrack(dayTrack([]), null).empty, true);
  assert.equal(dayTrackFromRun(null), null);
  assert.equal(dayTrackFromRun({ stages: [] }), null);
});

test('the register and the slate agree: a stage started before the recorded finish is not running', () => {
  const closedAt = Date.parse(runRecord.finished_at);
  const now = Date.parse('2026-09-12T21:10:00+00:00');
  // the morning's selection started at 07:37 and the register lost its finish
  const fresh = run.map((e) => ({ ...e, timestamp: e.timestamp }));
  const noon = [{ event_type: 'agent.message_posted', timestamp: '2026-09-12T21:05:00+00:00', payload: {} }, ...fresh];
  assert.equal(productionStatus(noon, now).running, 'selection', 'without the record the register would say «Acum»');
  const status = productionStatus(noon, now, closedAt);
  assert.equal(status.running, null);
  assert.equal(status.live, false);
  assert.doesNotMatch(status.text, /Acum/);
  // a stage that starts after the recorded finish is running again
  const later = [{ event_type: 'runbook.stage_started', timestamp: '2026-09-12T21:06:00+00:00', payload: { stage: 'publish' } }, ...noon];
  assert.equal(productionStatus(later, now, closedAt).live, true);
});
