// «Reluarea zilei» (W13): the newest real working day played back from its record. The fixture
// holds two real runs of 12.09, unedited (tests/fixtures/replay_runs_2026-09-12.json).
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  LIVE_WINS_MS, QUIET_MS, QUIET_PAGE_MS, REPLAY_SPEEDS, REPLAY_TARGET_MS, ReplayClock, agentsAt, buildSchedule, buildTimeline, crossed, frameAt,
  indexAt, initialStates, interruptsReplay, locateStart, nextStageTime, pageAt, prevStageTime, quietSpans, rateWords, readRecord, recordAt,
  captionLines, replayBubble, replayWords, replayableRun, runAt, searchBounds, spanText, stageTicks,
} from '../src/day_replay.js';

const FIX = JSON.parse(fs.readFileSync(new URL('./fixtures/replay_runs_2026-09-12.json', import.meta.url), 'utf8'));
const RUN = FIX.complete.run;
const EVENTS = FIX.complete.events;
const TZ = 'Europe/Bucharest';
const ARIS = '4df0b539-49dc-41aa-b68f-748c67d87532';

/** A fake /events over a list, as the backend answers it (after, limit, has_more, next_cursor). */
function ledgerApi(rows, calls = []) {
  return async (after, limit) => {
    calls.push([after, limit]);
    const page = rows.filter((e) => e.sequence > after).slice(0, limit + 1);
    const events = page.slice(0, limit);
    return { events, next_cursor: events.length ? events.at(-1).sequence : after, has_more: page.length > limit };
  };
}

test('the run replayed is the newest the runbook recorded as finished; a run under way is not a replay', () => {
  const older = { id: 'a', started_at: '2026-09-12T07:36:33Z', finished_at: '2026-09-12T07:44:36Z' };
  const newer = { id: 'b', started_at: '2026-09-12T20:48:06Z', finished_at: '2026-09-12T20:59:45Z' };
  const running = { id: 'c', started_at: '2026-09-13T05:00:00Z', finished_at: null };
  assert.equal(replayableRun([older, newer]).id, 'b');
  assert.equal(replayableRun([running, older, newer]).id, 'b');
  assert.equal(replayableRun([running]), null, 'nothing recorded as finished: no button');
  assert.equal(replayableRun([]), null);
  assert.equal(replayableRun(null), null);
  assert.equal(replayableRun([FIX.captured.run, RUN]).id, RUN.id);
});

test('the start of the run is found in the record by bisection, narrowed by what the page holds', async () => {
  const start = Date.parse(RUN.started_at);
  const calls = [];
  const get = ledgerApi(EVENTS, calls);
  const probe = async (after) => (await get(after, 1)).events[0] || null;
  const cursor = EVENTS.at(-1).sequence;
  const found = await locateStart(probe, start, searchBounds([], start, cursor));
  const first = EVENTS.find((e) => e.sequence > found.after);
  assert.equal(first.event_type, 'runbook.daily_run_started');
  assert.equal(first.aggregate_id, RUN.id);
  assert.ok(found.requests <= Math.ceil(Math.log2(cursor)) + 1, `${found.requests} probes`);
  // an event the page holds from before the start, and one from after, leave almost nothing to search
  const before = EVENTS[1];
  const after = EVENTS.at(-2);
  const bounds = searchBounds([after, before], start, cursor);
  assert.equal(bounds.lo, before.sequence);
  assert.equal(bounds.hi, after.sequence - 1);
  const narrowed = await locateStart(probe, start, bounds);
  assert.equal(narrowed.after, found.after);
  assert.ok(narrowed.requests <= found.requests);
});

test('the run is read once, in pages, from its own start to its own finish event', async () => {
  const calls = [];
  const record = await readRecord(ledgerApi(EVENTS, calls), RUN, { cursor: EVENTS.at(-1).sequence });
  assert.equal(record.complete, true);
  assert.equal(record.events[0].event_type, 'runbook.daily_run_started');
  assert.equal(record.events.at(-1).event_type, 'runbook.daily_run_finished');
  assert.equal(record.events.at(-1).aggregate_id, RUN.id);
  assert.equal(record.requests, calls.length);
  assert.ok(calls.every(([, limit]) => limit === 1 || limit === 300));
  // nothing added or reordered: the events are the record's, in its order
  const ids = record.events.map((e) => e.event_id);
  const expected = EVENTS.filter((e) => e.sequence >= record.events[0].sequence && e.sequence <= record.events.at(-1).sequence).map((e) => e.event_id);
  assert.deepEqual(ids, expected);
  assert.equal(ids.length, 214);
});

test('the timeline is cut by the run\'s own start and finish events, and keeps the record\'s times', () => {
  const tl = buildTimeline(RUN, EVENTS);
  assert.equal(tl.events[0].event_type, 'runbook.daily_run_started');
  assert.equal(tl.events.at(-1).event_type, 'runbook.daily_run_finished');
  assert.ok(tl.events.every((e) => !String(e.event_id).startsWith('w')), 'no invented rows');
  assert.equal(tl.start, Date.parse(RUN.started_at));
  assert.ok(tl.end >= Date.parse(RUN.finished_at));
  assert.ok(Math.abs(tl.duration - 699013) < 50, `${tl.duration} ms: the run of 20:48:06-20:59:45`);
  for (let i = 1; i < tl.times.length; i += 1) assert.ok(tl.times[i] >= tl.times[i - 1]);
  assert.deepEqual(tl.stages.map((s) => s.stage), ['preflight', 'performance_intake', 'idea_generation', 'research_and_verification', 'selection', 'script_and_storyboard', 'media', 'edit_and_qc', 'publish', 'post_run', 'daily_log', 'serial_queue']);
  assert.equal(tl.stages[3].word, 'documentare și verificare');
  const schedule = buildSchedule(tl);
  const ticks = stageTicks(tl, schedule);
  assert.equal(ticks[0].p, 0);
  assert.ok(ticks.every((t, i) => i === 0 || t.p >= ticks[i - 1].p));
  assert.ok(ticks.at(-1).p <= 1);
  const media = ticks.find((t) => t.stage === 'media');
  const qc = ticks.find((t) => t.stage === 'edit_and_qc');
  assert.ok(qc.p - media.p < 0.06, "the render's seven quiet minutes are short on the scrubber");
  const spans = quietSpans(schedule);
  assert.equal(spans.length, 2);
  assert.ok(spans.every((q) => q.to > q.from));
});

test('the reducer: the world at a moment is the events up to it, by the live page\'s own rules', () => {
  const tl = buildTimeline(RUN, EVENTS);
  const atStart = frameAt(tl, tl.start);
  assert.equal(atStart.index, 1, 'only the run\'s start has happened');
  assert.equal(atStart.track.segments[0].stage, 'preflight');
  assert.ok(Object.values(atStart.agents).every((a) => a.runtime_state === 'IDLE'), 'nobody was at work as it began');
  // the first work of the night: someone THINKING at 20:48:07 verifying claims
  const firstWork = tl.events.find((e) => e.event_type === 'agent.state_changed' && e.payload.runtime_state === 'THINKING');
  const t1 = Date.parse(firstWork.timestamp);
  const during = frameAt(tl, t1);
  assert.equal(during.agents[firstWork.aggregate_id].runtime_state, 'THINKING');
  assert.equal(during.agents[firstWork.aggregate_id].task_type, firstWork.payload.task_type);
  assert.equal(during.stage, 'research_and_verification');
  assert.equal(frameAt(tl, t1 - 1).agents[firstWork.aggregate_id].runtime_state, 'IDLE', 'a millisecond before, not yet');
  // the run as the runbook's record stood then: the stages finished by then, no summary yet
  assert.ok(during.run.stages.every((s) => Date.parse(s.at) <= t1));
  assert.equal(during.run.status, 'RUNNING');
  assert.equal(during.run.summary, null);
  const end = frameAt(tl, tl.end);
  assert.equal(end.index, tl.events.length);
  assert.equal(end.track.finished, true);
  assert.equal(end.run.status, 'COMPLETED');
  assert.equal(end.run.summary, RUN.summary);
  assert.equal(end.stage, null);
  // every employee's last task is one the record gave them
  for (const task of Object.values(end.tasks.tasks)) assert.ok(task.at >= tl.start && task.at <= tl.end);
});

test('someone whose first change in the run ends work was at work as it began; nothing else is assumed', () => {
  const t = (s) => `2026-09-12T20:00:0${s}Z`;
  const states = initialStates([
    { event_type: 'agent.state_changed', aggregate_id: 'a', timestamp: t(1), payload: { runtime_state: 'IDLE', task_type: 'render' } },
    { event_type: 'agent.state_changed', aggregate_id: 'b', timestamp: t(2), payload: { runtime_state: 'WORKING', task_type: 'x' } },
    { event_type: 'agent.run_completed', aggregate_id: 'r', timestamp: t(3), payload: { agent_id: 'c', status: 'SUCCEEDED', task_type: 'y' } },
    { event_type: 'agent.state_changed', aggregate_id: 'a', timestamp: t(4), payload: { runtime_state: 'WORKING', task_type: 'z' } },
  ]);
  assert.deepEqual(states.a, { runtime_state: 'WORKING', task_type: 'render', detail: '', lifecycle: 'ACTIVE' });
  assert.equal(states.b.runtime_state, 'IDLE');
  assert.equal(states.c.runtime_state, 'WORKING');
  assert.equal(states.c.task_type, 'y');
  assert.equal(states.d, undefined);
});

test('the run as the record stood: stages recorded by then, and its end only once it ended', () => {
  const t = Date.parse(RUN.stages[4].at);
  const r = runAt(RUN, t);
  assert.equal(r.stages.length, 5);
  assert.equal(r.finished_at, null);
  assert.equal(r.summary, null);
  const done = runAt(RUN, Date.parse(RUN.finished_at));
  assert.equal(done.stages.length, RUN.stages.length);
  assert.equal(done.status, RUN.status);
  assert.equal(done.finished_at, RUN.finished_at);
});

test('the page\'s people keep their desks and take the record\'s states', () => {
  const tl = buildTimeline(RUN, EVENTS);
  const people = [{ id: ARIS, display_name: 'Dr. Aris (Researcher)', desk_id: 'desk_research_1', runtime_state: 'IDLE', lifecycle: 'PAUSED' }, { agent_id: 'nobody', desk_id: 'd2', runtime_state: 'ERROR' }];
  const firstAris = tl.events.find((e) => e.event_type === 'agent.state_changed' && e.aggregate_id === ARIS && e.payload.runtime_state !== 'IDLE');
  if (!firstAris) return;
  const out = agentsAt(people, frameAt(tl, Date.parse(firstAris.timestamp)));
  assert.equal(out[0].desk_id, 'desk_research_1');
  assert.equal(out[0].runtime_state, firstAris.payload.runtime_state);
  assert.equal(out[0].lifecycle, 'ACTIVE', 'the live pause is not the night\'s');
  assert.equal(out[1].runtime_state, 'IDLE', 'no record of them in the run: not at work');
  assert.equal(people[0].runtime_state, 'IDLE', 'the live agents are not touched');
});

test('time compression: the busy record at one rate, about a minute at 1×; a quiet stretch passes in 2 s and says so', () => {
  assert.deepEqual([...REPLAY_SPEEDS], [1, 4, 16]);
  const tl = buildTimeline(RUN, EVENTS);
  const schedule = buildSchedule(tl);
  // 20:51:30-20:58:24 nothing was recorded while the film rendered, 20:50:43-20:51:24 one long task
  const quiet = schedule.segments.filter((s) => s.quiet);
  assert.equal(quiet.length, 2);
  assert.ok(quiet.every((s) => s.t1 - s.t0 >= QUIET_MS && s.p1 - s.p0 === QUIET_PAGE_MS));
  assert.ok(Math.abs(schedule.pageDuration - REPLAY_TARGET_MS) < 1, `${schedule.pageDuration} ms at 1×`);
  // every moment of the record maps to one page moment and back, in order
  let lastP = -1;
  for (const t of tl.times) {
    const p = pageAt(schedule, t);
    assert.ok(p >= lastP);
    lastP = p;
    assert.ok(Math.abs(recordAt(schedule, p) - t) < 1);
  }
  assert.equal(recordAt(schedule, 0), tl.start);
  assert.equal(recordAt(schedule, schedule.pageDuration), tl.end);
  // a run shorter than a minute, with no quiet stretch, plays in real time
  const short = buildSchedule({ start: 0, end: 20000, times: [0, 5000, 10000, 15000, 20000] });
  assert.equal(short.factor, 1);
  assert.equal(short.pageDuration, 20000);
  const clock = new ReplayClock(tl);
  clock.play();
  clock.advance(1000);
  assert.ok(Math.abs(clock.t - tl.start - clock.factor * 1000) < 0.01);
  assert.ok(Math.abs(clock.rate - clock.factor) < 1e-6);
  clock.setSpeed(16);
  clock.setSpeed(3);
  assert.equal(clock.speed, 16, 'only the offered speeds');
  clock.advance(REPLAY_TARGET_MS);
  assert.equal(clock.t, tl.end);
  assert.equal(clock.playing, false, 'it stops at the end');
  clock.play();
  assert.equal(clock.t, tl.start, 'play at the end starts again');
  clock.pause();
  assert.equal(clock.advance(5000), tl.start, 'paused, nothing moves');
  assert.equal(clock.seek(tl.end + 99999), tl.end);
  assert.equal(clock.seek(0), tl.start);
  // in the render's quiet stretch the clock runs faster, and the words say why, with the real times
  clock.setSpeed(1);
  clock.seek(Date.parse('2026-09-12T20:55:00Z'));
  assert.equal(clock.segment.quiet, true);
  assert.ok(clock.rate > 100, `${clock.rate}`);
  const w = replayWords(tl, clock.t, { timeZone: TZ, stage: 'media', rate: clock.rate, quiet: clock.segment, speed: 1 });
  // W24: a quiet stretch says how long it is on the page, not a rate other than the pressed key's
  assert.equal(w.rate, 'nicio schimbare în registru 23:51:30–23:58:24 · trece în 2 s');
  clock.seekFraction(0.5);
  assert.ok(Math.abs(clock.fraction - 0.5) < 1e-9);
});

test('stepping through the stages, and the events crossed while playing forward', () => {
  const tl = buildTimeline(RUN, EVENTS);
  const research = tl.stages.find((s) => s.stage === 'research_and_verification').at;
  assert.equal(nextStageTime(tl, tl.start), tl.stages.find((s) => s.at > tl.start + 1).at);
  assert.equal(nextStageTime(tl, tl.end), tl.end);
  assert.equal(prevStageTime(tl, research + 10000), research);
  assert.ok(prevStageTime(tl, research + 100) < research, 'pressed again at a stage\'s start, the one before');
  assert.equal(prevStageTime(tl, tl.start), tl.start);
  const all = crossed(tl, tl.start - 1, tl.end);
  assert.equal(all.length, tl.events.length);
  assert.deepEqual(crossed(tl, tl.end, tl.start), [], 'a seek backwards announces nothing');
  assert.equal(indexAt(tl, tl.start - 1), 0);
});

test('the words: the chip, the clock of the moment in the studio\'s zone, the stage, the rate', () => {
  const tl = buildTimeline(RUN, EVENTS);
  const research = tl.stages.find((s) => s.stage === 'research_and_verification').at;
  const w = replayWords(tl, research, { timeZone: TZ, stage: 'research_and_verification', rate: 11.6, staff: 8 });
  // 20:48 UTC is 23:48 in Bucharest (summer time)
  assert.equal(w.chip, 'RELUARE · 12.09 · 23:48');
  assert.equal(w.clock, '23:48:07');
  assert.equal(w.clockLabel, 'ATUNCI');
  assert.equal(w.stage, 'acum: documentare și verificare');
  assert.equal(w.progress, '0:01 din 11:39');
  assert.equal(w.rate, 'de 12 ori mai repede decât rularea');
  assert.equal(rateWords(20.2), 'de 20 de ori mai repede decât rularea');
  assert.equal(rateWords(104), 'de 104 ori mai repede decât rularea');
  assert.equal(w.caption, '8 angajați · reluarea rulării din 12.09, 23:48');
  assert.match(w.title, /Nu este live\.$/);
  assert.equal(replayWords(tl, tl.end, { timeZone: TZ }).stage, 'rularea s-a încheiat');
  assert.equal(replayWords(tl, tl.start + 1, { timeZone: TZ, stage: null }).stage, 'între două etape');
  assert.equal(spanText(699013), '11:39');
  assert.equal(spanText(3 * 3600000 + 5000), '3:00:05');
  assert.equal(rateWords(1), 'în timp real');
});

test('a replayed caption says what the record says, labelled as the replay\'s, with its moment', () => {
  const done = EVENTS.find((e) => e.event_type === 'agent.run_completed' && e.payload.status === 'SUCCEEDED');
  const b = replayBubble(done, { timeZone: TZ });
  assert.equal(b.agentId, done.payload.agent_id);
  assert.match(b.text, /^Sarcină reușită: .+ ✓$/);
  assert.match(b.label, /^RELUARE · \d{2}:\d{2}:\d{2}$/);
  assert.deepEqual(replayBubble({ event_type: 'agent.message_sent', aggregate_id: 'a', timestamp: '2026-09-12T20:50:00Z', payload: { text: 'Gata.' } }, { timeZone: TZ }), { agentId: 'a', text: 'Gata.', label: 'RELUARE · 23:50:00' });
  assert.equal(replayBubble({ event_type: 'agent.message_sent', aggregate_id: 'a', timestamp: '2026-09-12T20:50:00Z', payload: {} }), null, 'nothing said, no caption');
  assert.equal(replayBubble({ event_type: 'agent.run_completed', timestamp: '2026-09-12T20:50:00Z', payload: { agent_id: 'a', status: 'FAILED' } }), null);
});

test('a replayed caption keeps the words as written: two lines at most, then «…» at a word\'s end', () => {
  assert.deepEqual(captionLines('Gata.'), ['Gata.']);
  const said = 'Am scris «How ATLAS Caught the Higgs Boson in Real Time» — 5 afirmații, toate cu sursă, și l-am trimis Directorului.';
  const lines = captionLines(said, 56, 2);
  assert.equal(lines.length, 2);
  assert.ok(lines.every((l) => l.length <= 56), lines.join('|'));
  assert.ok(lines[1].endsWith('…'));
  assert.ok(said.startsWith(lines.join(' ').replace(/…$/, '')), 'nothing reworded, only cut');
  assert.deepEqual(captionLines('x'.repeat(70), 56, 2), [`${'x'.repeat(55)}…`]);
  assert.deepEqual(captionLines(''), []);
});

test('live wins: what changes the world ends a replay; the watchdog\'s routine does not', () => {
  assert.equal(interruptsReplay({ event_type: 'agent.state_changed', payload: { runtime_state: 'WORKING' } }), true);
  assert.equal(interruptsReplay({ event_type: 'runbook.stage_started', payload: { stage: 'media' } }), true);
  assert.equal(interruptsReplay({ event_type: 'media.video_rendered', payload: {} }), true);
  assert.equal(interruptsReplay({ event_type: 'workflow.created', payload: { job_name: 'watchdog', workflow_type: 'WATCHDOG' } }), false);
  assert.equal(interruptsReplay({ event_type: 'workflow.stage_changed', payload: { current_stage: 'RESEARCH' } }), true);
  assert.equal(interruptsReplay({ event_type: 'provider.catalog_refreshed', payload: {} }), false);
  assert.equal(interruptsReplay(null), false);
  assert.ok(LIVE_WINS_MS >= 3000 && LIVE_WINS_MS <= 10000, 'a few seconds');
});

test('the captured fixture\'s run (07:36) plays what was captured, and says it was cut', async () => {
  const run = FIX.captured.run;
  const rows = FIX.captured.events;
  const record = await readRecord(ledgerApi(rows), run, { cursor: rows.at(-1).sequence, known: rows });
  assert.equal(record.events[0].event_type, 'runbook.daily_run_started');
  const tl = buildTimeline(run, record.events, { complete: record.complete });
  // the capture ends before the run's finish event: the window falls back to the recorded times
  assert.ok(tl.events.length > 10);
  assert.equal(tl.end, Date.parse(run.finished_at));
  const f = frameAt(tl, Date.parse('2026-09-12T07:36:40Z'));
  assert.equal(f.stage, 'idea_generation');
  assert.equal(f.agents['4df0b539-49dc-41aa-b68f-748c67d87532'].runtime_state, 'THINKING', 'Dr. Aris proposing topics, 07:36:34-07:36:59');
  assert.equal(f.agents['4df0b539-49dc-41aa-b68f-748c67d87532'].task_type, 'propose_topics');
  assert.equal(f.topics.titles.length, 0, 'no topic proposed yet at 07:36:40');
  assert.equal(frameAt(tl, Date.parse('2026-09-12T07:37:00Z')).topics.titles.length, 6);
});

test('W14 adversary: every replayed state traces to a recorded event (an independent fold, at every event)', () => {
  for (const key of ['captured', 'complete']) {
    const { run, events } = FIX[key];
    const tl = buildTimeline(run, events);
    const ids = new Set(events.map((e) => e.event_id));
    assert.ok(tl.events.every((e) => ids.has(e.event_id)), `${key}: no event the record does not hold`);
    const ts = (/** @type {any} */ e) => Date.parse(e.timestamp);
    for (const e of tl.events) {
      for (const t of [ts(e) - 1, ts(e)]) {
        const frame = frameAt(tl, t);
        /** @type {Record<string, string>} */
        const fold = Object.fromEntries(Object.entries(tl.initial).map(([id, s]) => [id, s.runtime_state]));
        let started = null;
        const open = new Set();
        for (const x of tl.events) {
          if (ts(x) > t) break;
          if (x.event_type === 'agent.state_changed') fold[x.aggregate_id] = x.payload.runtime_state;
          if (x.event_type === 'agent.run_completed' && x.payload.agent_id in fold) fold[x.payload.agent_id] = 'IDLE';
          if (x.event_type === 'runbook.stage_started') { started = x.payload.stage; open.add(x.payload.stage); }
          if (x.event_type === 'runbook.stage_finished') open.delete(x.payload.stage);
        }
        for (const id of new Set([...Object.keys(fold), ...Object.keys(frame.agents)])) {
          assert.equal((frame.agents[id] || { runtime_state: 'IDLE' }).runtime_state, fold[id] || 'IDLE', `${key} ${id} at ${new Date(t).toISOString()}`);
        }
        assert.equal(frame.stage || null, started && open.has(started) ? started : null, `${key} stage at ${new Date(t).toISOString()}`);
        assert.ok(frame.run.stages.every((/** @type {any} */ s) => Date.parse(s.at) <= t), 'no stage from the future');
        if (t < Date.parse(run.finished_at)) assert.equal(frame.run.finished_at, null, 'no finish before it happened');
      }
    }
  }
});

test('W14: inside the letterbox the slate shows the replayed run, and the scrubber\'s run to play reads at 3:1', () => {
  const main = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
  const body = main.slice(main.indexOf('function renderDayTrack() {'), main.indexOf('const moments = new Moments('));
  assert.match(body, /replaying\(\) && replay \? replay\.frame : null/);
  assert.match(body, /dayTrackWords\(shown,/);
  // the live facts are still the live track: the replay never writes them
  assert.match(body, /worldFacts\.track = track;/);
  const scene = fs.readFileSync(new URL('../src/office_scene.css', import.meta.url), 'utf8');
  assert.equal((scene.match(/var\(--replay-fill\) var\(--replay-p\), var\(--replay-rest\) var\(--replay-p\)/g) || []).length, 2);
  const style = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  const hex = (/** @type {string} */ name) => (style.match(new RegExp(`${name}:[ ]*(#[0-9a-f]{6})`, 'i')) || [])[1];
  const lum = (/** @type {string} */ h) => {
    const c = [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  };
  const rest = hex('--replay-rest');
  assert.ok(rest, '--replay-rest is a token in :root');
  // the plate's ground as measured from the pixels at 1280, 1920 and 2560, day and night: #0a0e1a
  assert.ok((lum(rest) + 0.05) / (lum('#0a0e1a') + 0.05) >= 3);
});
