// W10: THE FACES MADE LEGIBLE. Every bound face of the building is a place the pointer and the
// keyboard can stand on, and the glass readout beside it says the face's own words from the same
// facts, larger. Nothing here may invent a value, cover the face it describes, or leave the room.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  SURFACES, ROOM_WORD, GLINT_MS, GlintTracker, agoWords, canvasLabel, counted, hitAt, lastTaskLine, lastTasks, nextRunSign,
  placeReadout, readoutSentence, screenRect, surfaceReadout, surfaceRects, unionRect,
  deskRegion, pointerHit, tasksFromRecord, newerTasks, REPLAY_ACTION, replayOffered,
} from '../src/hq_readouts.js';
import { NOTES, WALL, runSignFace } from '../src/hq_screens.js';
import { dayTrack, dayTrackFromRun } from '../src/hud_charts.js';

const MANIFEST = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/manifest.json', import.meta.url), 'utf8'));
const RUN = JSON.parse(fs.readFileSync(new URL('./fixtures/runbook_run.json', import.meta.url), 'utf8'));
const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const AGENTS = [
  { id: 'sarah', display_name: 'Sarah (Director)', desk_id: 'desk_director', runtime_state: 'IDLE', lifecycle: 'ACTIVE' },
  { id: 'kael', display_name: 'Kael (Video Editor)', desk_id: 'desk_video', runtime_state: 'WORKING', task_type: 'render_video' },
  { id: 'vera', display_name: 'Vera (Publisher)', desk_id: 'desk_publish', runtime_state: 'IDLE' },
];

/* ------------------------------------------------------------------------ the surfaces -- */

test('every bound wall is a surface with its own face\'s rectangle, and opens a room the menu has', () => {
  const rects = surfaceRects(MANIFEST, AGENTS);
  const walls = rects.filter((r) => !r.desk);
  assert.deepEqual(walls.map((r) => r.id), SURFACES.map((s) => s.id));
  assert.deepEqual(walls.find((r) => r.id === 'treasury_board').rect, WALL.treasury_board);
  assert.deepEqual(walls.find((r) => r.id === 'research_board').rect, unionRect(NOTES));
  assert.deepEqual(walls.find((r) => r.id === 'render_bay').rect, MANIFEST.screens.render_display.rect);
  assert.deepEqual(walls.find((r) => r.id === 'publish_radar').rect, MANIFEST.screens.publish_radar.rect);
  for (const s of SURFACES.filter(s => s.room !== 'open-treasury-btn')) {
    assert.equal((HTML.match(new RegExp(`id="${s.room}"`, 'g')) || []).length, 1, `${s.id} opens ${s.room}`);
    assert.ok(ROOM_WORD[s.room], `${s.room} is named in the readout`);
  }
  for (const r of rects) {
    const [x, y, w, h] = r.rect;
    assert.ok(x >= 0 && y >= 0 && x + w <= MANIFEST.world.width && y + h <= MANIFEST.world.height, `${r.id} lies in the world`);
  }
});

test('only an occupied desk is a surface, and it names its employee', () => {
  const desks = surfaceRects(MANIFEST, AGENTS).filter((r) => r.desk);
  assert.deepEqual(desks.map((r) => r.id).sort(), ['desk:desk_director', 'desk:desk_publish', 'desk:desk_video']);
  assert.equal(desks.find((r) => r.id === 'desk:desk_director').agent.id, 'sarah');
  const seat = MANIFEST.seats.desk_director;
  assert.deepEqual(desks.find((r) => r.id === 'desk:desk_director').rect, deskRegion(seat, MANIFEST.screens.desk_director_monitor.rect));
});

test('a desk is the monitor, the chair and the figure at it, at least 32 px at fit zoom (W12)', () => {
  for (const [desk, seat] of Object.entries(MANIFEST.seats)) {
    const monitor = MANIFEST.screens[`${desk}_monitor`].rect;
    const [x, y, w, h] = deskRegion(seat, monitor);
    // the monitor inside
    assert.ok(x <= monitor[0] && y <= monitor[1] && x + w >= monitor[0] + monitor[2] && y + h >= monitor[1] + monitor[3], desk);
    // the figure's own box (hq_world.js drawAgents) inside
    assert.ok(x <= seat.x - 16 && x + w >= seat.x + 16 && y <= seat.y - 44 && y + h >= seat.y + 2, desk);
    // fit zoom at 1920 is about 0.78 screen px per world px (1280 is smaller still, and the
    // monitor there was 9 px): 48 x 54 world px is at least 37 x 42 screen px at 0.78
    assert.ok(w * 0.78 >= 32 && h * 0.78 >= 32, `${desk} ${w}x${h}`);
  }
});

test('the pointer on an employee stands on their desk; a figure without a desk is itself', () => {
  const seat = MANIFEST.seats.desk_director;
  const employee = { agent: AGENTS[0], x0: seat.x - 16, y0: seat.y - 44, x1: seat.x + 16, y1: seat.y + 2 };
  const [dx, dy, dw, dh] = deskRegion(seat, MANIFEST.screens.desk_director_monitor.rect);
  const desk = { agent: AGENTS[0], surface: 'desk:desk_director', desk: true, x0: dx, y0: dy, x1: dx + dw, y1: dy + dh };
  const wall = { agent: null, surface: 'run_sign', x0: 0, y0: 0, x1: 2000, y1: 2000 };
  assert.equal(pointerHit([employee, desk, wall], seat.x, seat.y - 20), desk, 'the figure is part of the desk');
  assert.equal(pointerHit([employee, desk, wall], dx + 1, dy + dh - 1), desk, 'the corner of the desk');
  assert.equal(pointerHit([employee, wall], seat.x, seat.y - 20), employee);
  assert.equal(pointerHit([employee, desk, wall], 1900, 1900), wall);
  assert.equal(pointerHit([], 1, 1), null);
});

test('the façade sign\'s card stands under it, off the AMN-AI lettering', () => {
  const sign = SURFACES.find((s) => s.id === 'run_sign');
  assert.equal(sign.prefer, 'below');
  const room = { left: 0, top: 0, right: 1200, bottom: 900 };
  const target = { x: 600, y: 60, w: 160, h: 30 };
  assert.equal(placeReadout(target, { w: 300, h: 120 }, room, 14).side, 'right', 'without a preference, right first');
  const at = placeReadout(target, { w: 300, h: 120 }, room, 14, 'below');
  assert.equal(at.side, 'below');
  assert.ok(at.y >= target.y + target.h, 'under the sign');
  // no room below: the other sides still hold it
  assert.equal(placeReadout({ x: 600, y: 820, w: 160, h: 30 }, { w: 300, h: 120 }, room, 14, 'below').side, 'right');
});

test('the pointer finds the smallest box under it: a desk\'s monitor in front of its employee', () => {
  const seat = MANIFEST.seats.desk_director;
  const employee = { agent: AGENTS[0], x0: seat.x - 16, y0: seat.y - 50, x1: seat.x + 16, y1: seat.y + 2 };
  const [mx, my, mw, mh] = MANIFEST.screens.desk_director_monitor.rect;
  const monitor = { agent: AGENTS[0], surface: 'desk:desk_director', desk: true, x0: mx, y0: my, x1: mx + mw, y1: my + mh };
  const hits = [employee, monitor];
  assert.equal(hitAt(hits, mx + mw / 2, my + mh / 2), monitor);
  assert.equal(hitAt(hits, seat.x - 12, seat.y - 5), employee);
  assert.equal(hitAt(hits, 0, 0), null);
});

test('a face on screen is its world rectangle through the camera, in CSS pixels', () => {
  const r = screenRect([100, 50, 20, 10], { zoom: 2.3, panX: -40, panY: 96 }, 2);
  assert.deepEqual(r, { x: (100 * 2.3 - 40) / 2, y: (50 * 2.3 + 96) / 2, w: 23, h: 11.5 });
});

/* --------------------------------------------------------------------------- the words -- */

test('figures agree with their nouns as a Romanian reader counts', () => {
  assert.equal(counted(1, 'verdict respins', 'verdicte respinse'), '1 verdict respins');
  assert.equal(counted(11, 'verdict respins', 'verdicte respinse'), '11 verdicte respinse');
  assert.equal(counted(20, 'verdict respins', 'verdicte respinse'), '20 de verdicte respinse');
  assert.equal(counted(101, 'x', 'afirmații'), '101 afirmații');
  assert.equal(counted(1200, 'x', 'afirmații'), '1.200 de afirmații');
  assert.equal(counted(0, 'subiect propus', 'subiecte propuse'), '0 subiecte propuse');
});

test('how long ago, in the register\'s own measures', () => {
  const m = 60000;
  assert.equal(agoWords(20 * 1000), 'chiar acum');
  assert.equal(agoWords(m), 'acum un minut');
  assert.equal(agoWords(5 * m), 'acum 5 minute');
  assert.equal(agoWords(60 * m), 'acum o oră');
  assert.equal(agoWords(20 * 60 * m), 'acum 20 de ore');
  assert.equal(agoWords(47 * 60 * m), 'acum 47 de ore');
  assert.equal(agoWords(3 * 24 * 60 * m), 'acum 3 zile');
  assert.equal(agoWords(12 * 24 * 60 * m), 'acum 12 zile');
  assert.equal(agoWords(NaN), '');
});

test('an employee\'s last task is the newest real one the register holds, and a dash without', () => {
  const events = [
    { event_type: 'agent.state_changed', aggregate_id: 'aris', timestamp: '2026-09-12T07:37:07Z', payload: { runtime_state: 'IDLE', task_type: 'gather_sources' } },
    { event_type: 'agent.run_completed', aggregate_id: 'run-2', timestamp: '2026-09-12T07:37:07Z', payload: { agent_id: 'aris', status: 'SUCCEEDED', task_type: 'gather_sources' } },
    { event_type: 'agent.state_changed', aggregate_id: 'nadia', timestamp: '2026-09-12T07:37:08Z', payload: { runtime_state: 'THINKING', task_type: 'reconcile_day' } },
    { event_type: 'agent.run_completed', aggregate_id: 'run-1', timestamp: '2026-09-12T07:36:59Z', payload: { agent_id: 'aris', status: 'SUCCEEDED', task_type: 'propose_topics' } },
    { event_type: 'agent.message_posted', aggregate_id: 'm', timestamp: '2026-09-12T07:38:00Z', payload: { from_agent_id: 'sarah' } },
  ];
  const { tasks, key } = lastTasks(events);
  assert.deepEqual(Object.keys(tasks).sort(), ['aris', 'nadia']);
  assert.equal(tasks.aris.task, 'căutarea surselor');
  assert.equal(tasks.aris.status, 'SUCCEEDED');
  assert.equal(tasks.nadia.task, 'închiderea zilei');
  assert.equal(tasks.sarah, undefined, 'a letter is not a task');
  assert.equal(lastTasks(events).key, key, 'the same register, the same key');
  const now = Date.parse('2026-09-24T09:00:00Z');
  assert.equal(lastTaskLine(tasks.aris, now), 'ultima sarcină: căutarea surselor · acum 12 zile');
  assert.equal(lastTaskLine(undefined, now), 'ultima sarcină: —');
});

test('the façade says the next run only as the scheduler set it, or that the schedule is stopped', () => {
  const daily = (over) => [{ workflow_type: 'WATCHDOG', is_active: true, next_run_at: '2026-09-24T10:00:00Z' }, { workflow_type: 'DAILY_RUN', is_active: true, next_run_at: '2026-09-25T02:00:00+00:00', ...over }];
  const ctx = { timeZone: 'Europe/Bucharest' };
  assert.equal(nextRunSign(daily({}), ctx), 'următoarea rulare vin. 25.09, 05:00');
  assert.equal(nextRunSign(daily({ is_active: false }), ctx), 'programarea zilnică este oprită');
  assert.equal(nextRunSign(daily({}), { ...ctx, stopped: true }), 'autonomia este oprită');
  assert.equal(nextRunSign(daily({ next_run_at: null }), ctx), '', 'no time from the scheduler, no time on the sign');
  assert.equal(nextRunSign([], ctx), 'nicio treabă zilnică programată');
  assert.equal(nextRunSign(null, ctx), '', 'a schedule the page has not read says nothing');
});

test('the sign adds the next run while no run is under way, and never while one is', () => {
  const next = 'programarea zilnică este oprită';
  const done = runSignFace(dayTrackFromRun(RUN), { today: '2026-09-24', next });
  assert.ok(done.state.endsWith(` · ${next}`), done.state);
  const empty = runSignFace(null, { next });
  assert.equal(empty.state, next);
  // not read is not empty (W12)
  assert.equal(runSignFace(null).state, '—');
  assert.equal(runSignFace(null, { read: 'pending' }).state, '—');
  assert.equal(runSignFace(null, { read: 'ok' }).state, 'nicio rulare în registru');
  assert.equal(runSignFace(null, { read: 'failed' }).state, 'registrul nu a putut fi citit');
  assert.notEqual(runSignFace(null, { read: 'ok' }).key, runSignFace(null, { read: 'failed' }).key);
  const live = dayTrack([
    { event_type: 'runbook.stage_started', payload: { stage: 'media', index: 7, total: 12 }, timestamp: '2026-09-24T09:10:00Z' },
    { event_type: 'runbook.daily_run_started', aggregate_id: 'r', payload: { date: '2026-09-24', preflight: 'READY', stages: 12 }, timestamp: '2026-09-24T09:00:00Z' },
  ]);
  assert.equal(runSignFace(live, { today: '2026-09-24', live: true, next }).state, 'acum: producție media');
  assert.notEqual(runSignFace(null, { next }).key, runSignFace(null).key);
});

test('W11: between two stages of today\'s run the run is still under way, so the sign says no next run', () => {
  const next = 'programarea zilnică este oprită';
  // stage 1 finished, stage 2 not started yet: no segment is running, the run is not finished
  const between = dayTrack([
    { event_type: 'runbook.stage_finished', payload: { stage: 'preflight', index: 1, total: 12, status: 'COMPLETED' }, timestamp: '2026-09-24T09:02:00Z' },
    { event_type: 'runbook.stage_started', payload: { stage: 'preflight', index: 1, total: 12 }, timestamp: '2026-09-24T09:01:00Z' },
    { event_type: 'runbook.daily_run_started', aggregate_id: 'r', payload: { date: '2026-09-24', preflight: 'READY', stages: 12 }, timestamp: '2026-09-24T09:00:00Z' },
  ]);
  assert.equal(between.finished, false);
  // the page's live rule: between stages no stage is live, so nothing is claimed as running now
  const face = runSignFace(between, { today: '2026-09-24', live: false, next });
  assert.equal(face.open, true);
  assert.equal(face.underWay, false);
  assert.ok(!face.state.includes(next), face.state);
  const r = surfaceReadout('run_sign', { facts: { track: between, today: '2026-09-24', live: false, jobs: [{ workflow_type: 'DAILY_RUN', is_active: false }] }, agents: [], now: Date.parse('2026-09-24T09:03:00Z') });
  assert.equal(r.context, 'Rularea de azi nu s-a încheiat încă.');
  assert.ok(!r.context.includes('acum'));
  // a stage running now is still said as happening now
  const running = runSignFace(dayTrack([{ event_type: 'runbook.stage_started', payload: { stage: 'media', index: 2, total: 12 }, timestamp: '2026-09-24T09:04:00Z' }]), { today: '2026-09-24', live: true, next });
  assert.equal(running.underWay, true);
  // the same unfinished run seen from a later day is not open: the schedule is said again
  const stale = runSignFace(between, { today: '2026-09-26', live: false, next });
  assert.equal(stale.open, false);
  assert.ok(stale.state.endsWith(next), stale.state);
});

/* ------------------------------------------------------------------------ the readouts -- */

const FACTS = {
  treasury: { spendable: { amount: '12450.009' }, in_deficit: false },
  budget: { budgets: [{ period: 'DAILY', active: true, spent_usd: '12.75', limit_usd: '15', ratio: 0.85, state: 'WARN' }], today: { prompt_tokens: 1200, completion_tokens: 34 } },
  run: RUN,
  track: dayTrackFromRun(RUN),
  today: '2026-09-24',
  topics: { titles: ['How CERN Measures the Higgs Boson', 'The Truth About AI Training Data'], key: 'x' },
  episodes: { episodes: [{ id: 'e', status: 'DRAFT', title: 'Inside The Nexus', created_at: '2026-09-20T10:00:00Z', continuity: { episode_number: 3 } }] },
  jobs: [{ workflow_type: 'DAILY_RUN', is_active: false, next_run_at: '2026-09-25T02:00:00Z' }],
  tasks: { tasks: { sarah: { task: 'revizuirea Directorului', at: Date.parse('2026-09-21T09:00:00Z'), status: 'SUCCEEDED' } }, key: 'k' },
};
const NOW = Date.parse('2026-09-24T09:00:00Z');
const read = (id, facts = FACTS, agents = AGENTS) => surfaceReadout(id, { facts, agents, now: NOW });

test('the Treasury readout says the ticker\'s own figures, larger', () => {
  const r = read('treasury_board');
  assert.equal(r.eyebrow, 'TREZORERIE · S2');
  assert.equal(r.value, '12.450 VR$ cheltuibili');
  assert.equal(r.line, 'azi 12,75 / 15 USD');
  assert.equal(r.tone, 'warn');
  assert.equal(r.action, 'Clic sau Enter: deschide Trezoreria.');
  const none = read('treasury_board', {});
  assert.equal(none.value, '—');
  assert.equal(none.line, '');
  const deficit = read('treasury_board', { treasury: { spendable: { amount: '-1234.56' }, in_deficit: true } });
  assert.equal(deficit.value, '−1.234,56 VR$ cheltuibili');
  assert.equal(deficit.tone, 'alert');
  assert.equal(deficit.context, 'Trezoreria este în deficit.');
});

test('the sign\'s readout says the day and, with no run under way, the scheduler\'s own words', () => {
  const r = read('run_sign', { ...FACTS, nextRun: 'x', stopped: false, timeZone: 'Europe/Bucharest' });
  assert.match(r.value, /^RULAREA DIN \d{2}\.\d{2} · \d+\/\d+$/);
  assert.equal(r.context, 'Programarea zilnică este oprită.');
  const active = read('run_sign', { ...FACTS, jobs: [{ workflow_type: 'DAILY_RUN', is_active: true, next_run_at: '2026-09-25T02:00:00Z' }], timeZone: 'Europe/Bucharest' });
  assert.equal(active.context, 'Următoarea rulare vin. 25.09, 05:00.');
  const empty = read('run_sign', { reads: { runs: 'ok' } });
  assert.equal(empty.value, 'nicio rulare în registru');
  assert.equal(empty.context, '');
  assert.equal(read('run_sign', {}).value, '—', 'a record not read yet');
  assert.equal(read('run_sign', { reads: { runs: 'failed' } }).value, 'registrul nu a putut fi citit');
});

test('the boards, the screens and the plate say their counts in words that agree', () => {
  const run = { business_date: '2026-09-12', stages: [{ stage: 'research_and_verification', artefacts: { claims_verified: 1, verdicts_refused: 11 } }] };
  assert.equal(read('factcheck_board', { run }).value, '1 afirmație verificată · 11 verdicte respinse');
  assert.equal(read('factcheck_board', { run }).line, 'rularea din 12.09');
  assert.equal(read('factcheck_board', { run: { ...run, stages: [{ stage: 'research_and_verification', artefacts: { claims_verified: 0, verdicts_refused: null } }] } }).value, '0 afirmații verificate · —');
  assert.equal(read('factcheck_board', {}).value, '—');
  assert.equal(read('factcheck_board', { reads: { runs: 'ok' } }).line, 'nicio rulare în registru');
  assert.equal(read('research_board').value, '2 subiecte propuse');
  assert.equal(read('research_board').line, 'cel mai nou: How CERN Measures the Higgs Boson');
  assert.equal(read('research_board', { reads: { ledger: 'ok' } }).value, 'niciun subiect propus în registru');
  assert.equal(read('writers_screen').value, 'EP 3 · Ciornă');
  assert.equal(read('writers_screen').line, 'Inside The Nexus');
  assert.equal(read('infra_plate').value, '1.234 de tokenuri azi');
  assert.equal(read('infra_plate', {}).value, 'tokenuri azi —');
});

test('the radar says what was published, or that the Publisher is at work now', () => {
  const run = { business_date: '2026-09-12', stages: [{ stage: 'publish', artefacts: { publication_status: 'PUBLISHED', title: 'How ATLAS Caught the Higgs Boson' } }] };
  const idle = read('publish_radar', { run });
  assert.equal(idle.value, 'PUBLICAT · 12.09');
  assert.equal(idle.line, 'How ATLAS Caught the Higgs Boson');
  const busy = read('publish_radar', { run }, [{ ...AGENTS[2], runtime_state: 'WORKING' }]);
  assert.equal(busy.value, 'ÎN LUCRU');
  assert.equal(busy.tone, 'ok');
  assert.equal(read('publish_radar', {}).value, '—');
});

test('the render bay\'s readout shows the render at work, the film\'s frame, or the state', () => {
  const working = read('render_bay');
  assert.equal(working.value, 'ÎN LUCRU');
  assert.equal(working.poster, false);
  assert.match(working.context, /Kael \(Video Editor\)/);
  const idle = [{ ...AGENTS[1], runtime_state: 'IDLE' }];
  const film = { assetId: 'a', date: '2026-09-12', canvas: { dataset: { sampled: '5' } } };
  const poster = read('render_bay', { film }, idle);
  assert.equal(poster.value, 'ultimul film · 12.09');
  assert.equal(poster.line, 'cel mai luminos dintre 5 cadre-cheie ale filmului');
  assert.equal(poster.poster, true);
  const bare = read('render_bay', { reads: { runs: 'ok', film: 'none' } }, idle);
  assert.equal(bare.value, 'ÎN AȘTEPTARE');
  assert.equal(bare.line, 'niciun film randat în registru');
});

test('a desk\'s readout is its employee, the monitor\'s real state and the last real task', () => {
  const r = read('desk:desk_director');
  assert.equal(r.value, 'Sarah (Director)');
  assert.equal(r.line, 'în așteptare · monitor aprins, fără lucru');
  assert.equal(r.context, 'ultima sarcină: revizuirea Directorului · acum 3 zile');
  assert.equal(read('desk:desk_video').line, 'în lucru · monitor lucrează');
  assert.equal(read('desk:desk_publish').context, 'ultima sarcină: —');
  const paused = read('desk:desk_director', FACTS, [{ ...AGENTS[0], lifecycle: 'PAUSED' }]);
  assert.equal(paused.line, 'în pauză · monitor stins');
  assert.equal(read('desk:desk_audio'), null, 'an empty desk has no readout');
  assert.equal(read('nothing'), null);
});

test('no readout invents a figure: with no facts every value is a dash or says there is none', () => {
  for (const s of SURFACES.filter(s => s.room !== 'open-treasury-btn')) {
    const r = surfaceReadout(s.id, { facts: {}, agents: [], now: NOW });
    assert.ok(r, s.id);
    assert.doesNotMatch(`${r.value} ${r.line}`, /\d/, `${s.id}: «${r.value}» «${r.line}»`);
  }
});

test('the spoken readout is one sentence, the floor codes left to the eye', () => {
  const r = read('treasury_board');
  assert.equal(readoutSentence(r), 'trezorerie. 12.450 VR$ cheltuibili. azi 12,75 / 15 USD. Soldul cheltuibil și cheltuiala de azi față de bugetul zilnic.');
  assert.ok(readoutSentence(read('run_sign')).startsWith('fațada · rularea zilei. '));
});

/* ------------------------------------------------------------------- where it stands -- */

const ROOM = { left: 360, top: 112, right: 1580, bottom: 1016 };
const SIZE = { w: 300, h: 150 };
const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const inside = (p, room) => p.x >= room.left && p.y >= room.top && p.x + SIZE.w <= room.right && p.y + SIZE.h <= room.bottom;

test('the readout stands right of its face, then left, above or below, inside the room', () => {
  const face = { x: 800, y: 500, w: 40, h: 30 };
  const right = placeReadout(face, SIZE, ROOM);
  assert.equal(right.side, 'right');
  assert.equal(right.x, 852);
  const nearRight = placeReadout({ x: 1400, y: 500, w: 40, h: 30 }, SIZE, ROOM);
  assert.equal(nearRight.side, 'left');
  assert.equal(nearRight.x + SIZE.w, 1388);
  const wide = placeReadout({ x: 380, y: 150, w: 1180, h: 30 }, SIZE, ROOM);
  assert.equal(wide.side, 'below');
  const low = placeReadout({ x: 380, y: 900, w: 1180, h: 30 }, SIZE, ROOM);
  assert.equal(low.side, 'above');
});

test('wherever a face stands in the room, its readout never covers it and never leaves the room', () => {
  let seed = 7;
  const rand = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let i = 0; i < 2000; i += 1) {
    const w = 8 + rand() * 90;
    const h = 8 + rand() * 70;
    const face = { x: ROOM.left + rand() * (ROOM.right - ROOM.left - w), y: ROOM.top + rand() * (ROOM.bottom - ROOM.top - h), w, h };
    const at = placeReadout(face, SIZE, ROOM);
    const card = { x: at.x, y: at.y, w: SIZE.w, h: SIZE.h };
    assert.ok(inside(card, ROOM), `in the room: ${JSON.stringify({ face, at })}`);
    assert.ok(!overlaps(card, face), `off the face: ${JSON.stringify({ face, at })}`);
  }
});

test('in the narrowest room the frame opens (1280, both drawers) the readout still fits beside every face', () => {
  const room = { left: 308, top: 56, right: 982, bottom: 670 };
  const fit = { zoom: 0.78, panX: 308 + (674 - 1600 * 0.78) / 2, panY: 48 };
  for (const s of surfaceRects(MANIFEST, AGENTS)) {
    const [x, y, w, h] = s.rect;
    const face = { x: x * fit.zoom + fit.panX, y: y * fit.zoom + fit.panY, w: w * fit.zoom, h: h * fit.zoom };
    if (face.x < room.left || face.x + face.w > room.right) continue; // under a drawer: not reachable there
    const at = placeReadout(face, SIZE, room);
    const card = { x: at.x, y: at.y, w: SIZE.w, h: SIZE.h };
    assert.ok(inside(card, room), s.id);
    assert.ok(!overlaps(card, face), s.id);
  }
});

/* -------------------------------------------------------------------------- the glint -- */

test('a face glints once when its value changes live, never for the first value or a reset', () => {
  const g = new GlintTracker(4000);
  assert.equal(g.note('treasury_board', 't|50.000|false', 0), false, 'the first value is the page arriving');
  assert.equal(g.note('treasury_board', 't|49.990|false', 1000), false, 'still arriving');
  assert.equal(g.note('treasury_board', 't|49.990|false', 6000), false, 'no change');
  assert.equal(g.note('treasury_board', 't|49.980|false', 7000), true, 'a live change');
  assert.equal(g.progress('treasury_board', 7000), 0);
  assert.ok(g.progress('treasury_board', 7000 + GLINT_MS / 2) > 0.4);
  assert.equal(g.progress('treasury_board', 7000 + GLINT_MS), null, 'once, and over');
  assert.equal(g.note('treasury_board', 't|—|false', 9000), false, 'a value lost is not news');
  assert.equal(g.note('treasury_board', 't|49.970|false', 9500), false, 'nor a value read again after it');
  assert.equal(g.note('writers_screen', 'w|none', 9000), false);
  assert.equal(g.note('writers_screen', 'w|EP 3|Ciornă|x', 9100), false, 'the serial read for the first time');
  assert.equal(g.note('research_board', 'nb|', 9000), false);
  assert.equal(g.note('research_board', 'nb|A topic', 9100), false, 'the first note pinned is the board being read');
  assert.equal(g.note('research_board', 'nb|B topic\u0001A topic', 9200), true, 'a topic proposed live');
  assert.equal(g.note('run_sign', 'a', 9000), false);
  assert.equal(g.note('run_sign', 'b', 9001), true);
  g.reset();
  assert.equal(g.note('run_sign', 'c', 10000), false);
});

/* --------------------------------------------------------------------------- the page -- */

test('W11: the canvas keeps naming the screens once the page is live (main.js rewrote it without them)', () => {
  assert.equal(canvasLabel(false), 'Sediul AMN-AI. Săgețile trec de la un angajat la altul, apoi prin ecranele clădirii; Enter deschide ce ai ales.');
  assert.equal(canvasLabel(true), 'Sediul AMN-AI, live. Săgețile trec de la un angajat la altul, apoi prin ecranele clădirii; Enter deschide ce ai ales.');
  assert.ok(HTML.includes('aria-label="Studioul AMN-AI. Săgețile selectează angajații, Enter deschide conversația."'), 'the active pixel page names its actual controls');
  const main = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
  assert.match(main, /officeCanvas\.setAttribute\('aria-label', 'Studioul AMN-AI\. Săgețile selectează angajații/);
  assert.doesNotMatch(main, /tastele-săgeți/, 'no second, older sentence');
});

test('the glass readout is in the render, hidden from assistive technology, and said in a polite live region', () => {
  assert.match(HTML, /<div id="face-card" class="face-card" aria-hidden="true" hidden>/);
  assert.match(HTML, /<p id="face-card-announce" class="moment-announce" role="status" aria-live="polite"><\/p>/);
  assert.match(HTML, /aria-label="Studioul AMN-AI\. Săgețile selectează angajații, Enter deschide conversația\."/);
  const scene = fs.readFileSync(new URL('../src/office_scene.css', import.meta.url), 'utf8');
  const block = scene.slice(scene.indexOf('THE FACES MADE LEGIBLE (W10)'));
  assert.doesNotMatch(block, /#[0-9a-f]{3,8}\b|rgba?\(/i, 'the card states no colour of its own');
  assert.match(block, /pointer-events: none/);
  assert.match(block, /@media \(prefers-reduced-motion: reduce\) \{\s*\.scene-viewport \.face-card \{ animation: none; \}/);
});


/* ------------------------------------------------------------------ W12: not read is not empty -- */

test('a list that could not be read is «—» or says so, never an empty record', () => {
  const failed = { reads: { runs: 'failed', ledger: 'failed', episodes: 'failed', figures: 'failed', film: 'none' } };
  const pending = { reads: { runs: 'pending', ledger: 'pending', episodes: 'pending', figures: 'pending', film: 'none' } };
  const idle = [{ ...AGENTS[1], runtime_state: 'IDLE' }];
  for (const facts of [failed, pending, {}]) {
    const words = ['run_sign', 'factcheck_board', 'research_board', 'writers_screen', 'publish_radar', 'infra_plate', 'treasury_board', 'render_bay']
      .map((id) => read(id, facts, idle))
      .map((r) => [r.value, r.line].join(' | '));
    for (const w of words) assert.doesNotMatch(w, /nicio rulare|niciun film|niciun subiect|niciun episod/, w);
  }
  assert.equal(read('factcheck_board', failed).line, 'registrul nu a putut fi citit');
  assert.equal(read('factcheck_board', pending).line, '');
  assert.equal(read('publish_radar', failed).line, 'registrul nu a putut fi citit');
  assert.equal(read('research_board', failed).value, '—');
  assert.equal(read('research_board', failed).line, 'registrul nu a putut fi citit');
  assert.equal(read('writers_screen', failed).line, 'serialul nu a putut fi citit');
  assert.equal(read('treasury_board', failed).line, 'trezoreria nu a putut fi citită');
  assert.equal(read('infra_plate', failed).line, 'bugetul nu a putut fi citit');
  assert.equal(read('render_bay', failed, idle).line, 'registrul nu a putut fi citit');
  // the record names a film whose frame could not be read: not «no film»
  assert.equal(read('render_bay', { reads: { runs: 'ok', film: 'failed' } }, idle).line, 'cadrul filmului nu a putut fi citit');
  assert.equal(read('render_bay', { reads: { runs: 'ok', film: 'pending' } }, idle).line, '');
  // a run was read, and it has no verification stage
  assert.equal(read('factcheck_board', { run: { business_date: '2026-09-12', stages: [] }, reads: { runs: 'ok' } }).line, 'cea mai nouă rulare nu are etapa de verificare');
});

test('the name tags read the studio\'s record of runs, and a live event newer than it wins', () => {
  const record = {
    sarah: { task_type: 'director_review', status: 'SUCCEEDED', started_at: '2026-09-18T21:03:47Z', finished_at: '2026-09-18T21:03:55Z' },
    kael: { task_type: 'research_models', status: 'RUNNING', started_at: '2026-09-19T00:10:01Z', finished_at: null },
    lyra: { task_type: 'direct_company:critique', status: 'SUCCEEDED', started_at: '2026-09-18T21:03:31Z', finished_at: '2026-09-18T21:03:35Z' },
    bad: { task_type: 'x', started_at: 'not a date' },
  };
  const fromRecord = tasksFromRecord(record);
  assert.deepEqual(Object.keys(fromRecord.tasks).sort(), ['kael', 'lyra', 'sarah']);
  assert.equal(fromRecord.tasks.sarah.task, 'revizuirea Directorului');
  assert.equal(fromRecord.tasks.sarah.at, Date.parse('2026-09-18T21:03:55Z'), 'a finished run is dated by its end');
  assert.equal(fromRecord.tasks.kael.at, Date.parse('2026-09-19T00:10:01Z'), 'a run under way by its start');
  assert.equal(fromRecord.tasks.kael.task, 'cercetarea modelelor');
  assert.equal(fromRecord.tasks.lyra.task, 'conducerea companiei', 'a step of a task is said as its task');
  assert.deepEqual(tasksFromRecord(null).tasks, {});
  const live = { tasks: { sarah: { task: 'idei de subiect', at: Date.parse('2026-09-24T09:00:00Z'), status: null } } };
  const merged = newerTasks(live, fromRecord);
  assert.equal(merged.tasks.sarah.task, 'idei de subiect', 'the live event is newer');
  assert.equal(merged.tasks.kael.task, 'cercetarea modelelor', 'the record fills what the register never replayed');
  assert.equal(newerTasks({ tasks: {} }, fromRecord).key, fromRecord.key);
  const older = { tasks: { sarah: { task: 'scenariu', at: Date.parse('2026-09-01T09:00:00Z'), status: null } } };
  assert.equal(newerTasks(older, fromRecord).tasks.sarah.task, 'revizuirea Directorului');
});

test('a live stage start glints the sign even when its words did not change', () => {
  const g = new GlintTracker(0);
  g.note('run_sign', 'a', 0);
  assert.equal(g.progress('run_sign', 10), null);
  g.force('run_sign', 100);
  assert.ok(g.progress('run_sign', 100 + GLINT_MS / 2) > 0.4);
  assert.equal(g.progress('run_sign', 100 + GLINT_MS + 1), null);
});

test("«Reluarea zilei» (W13): the idle façade's card offers the last working day; a run under way or open does not", () => {
  const idle = read('run_sign', { ...FACTS, replayOffer: true });
  assert.equal(idle.action, REPLAY_ACTION);
  assert.equal(REPLAY_ACTION, 'Clic sau Enter: Vezi ultima rulare încheiată.');
  assert.equal(read('run_sign', { ...FACTS, replayOffer: false }).action, 'Clic sau Enter: deschide Rularea zilei.', 'no finished day on record: the room, as before');
  const underWay = dayTrack([{ event_type: 'runbook.stage_started', payload: { stage: 'media', index: 7, total: 12 }, timestamp: '2026-09-24T09:04:00Z' }]);
  const busy = read('run_sign', { ...FACTS, track: underWay, live: true, replayOffer: true });
  assert.equal(busy.action, 'Clic sau Enter: deschide Rularea zilei.', 'live work is not replayed');
  assert.equal(replayOffered({ replayOffer: true }, { underWay: false, open: true }), false, "today's run still open");
  assert.equal(replayOffered({ replayOffer: true }, { underWay: false, open: false }), true);
  assert.equal(replayOffered(null, { underWay: false, open: false }), false);
});
