import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  PANES, EXTRA_SCREENS, WALL, NOTES, DESK_MONITOR, deskPane, FaceCache,
  paneMode, roomOccupancy, roomShade, screenLight, latestFilm, renderBayFace, treasuryFace,
  wholeOrCents, runSignFace, factCheckFace, boardTopics, writersFace, publishFace, tokensFace,
  drawPane, paintTreasury, paintRunSign, paintFactCheck, paintNote, paintWriters, paintPublish, paintInfra, paintRenderBay,
} from '../src/hq_screens.js';
import { dayTrack, dayTrackFromRun } from '../src/hud_charts.js';

/**
 * W7: the building's screens show the studio's truth. Every binding is value -> face, and a value
 * the page does not hold is «—» or dark, never invented.
 */

const MANIFEST = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/manifest.json', import.meta.url), 'utf8'));
const RUN = JSON.parse(fs.readFileSync(new URL('./fixtures/runbook_run.json', import.meta.url), 'utf8'));

/* -------------------------------------------------------------- monitors and rooms -- */

test('a desk monitor is dark with nobody at the desk or a paused employee, lit only as the backend says', () => {
  assert.equal(paneMode(null), 'dark');
  assert.equal(paneMode({ runtime_state: 'WORKING', lifecycle: 'PAUSED' }), 'dark');
  assert.equal(paneMode({ runtime_state: 'IDLE' }), 'idle');
  assert.equal(paneMode({}), 'idle', 'an employee with no state reported sits idle, not at work');
  assert.equal(paneMode({ runtime_state: 'WORKING' }), 'work');
  assert.equal(paneMode({ runtime_state: 'executing' }), 'work');
  assert.equal(paneMode({ runtime_state: 'THINKING' }), 'think');
  assert.equal(paneMode({ runtime_state: 'BLOCKED' }), 'error');
});

test('a room is lit by whether anyone there works', () => {
  assert.equal(roomOccupancy([]), 'empty');
  assert.equal(roomOccupancy([null]), 'empty');
  assert.equal(roomOccupancy([{ runtime_state: 'IDLE', lifecycle: 'PAUSED' }]), 'empty', 'a paused employee is not at work');
  assert.equal(roomOccupancy([{ runtime_state: 'IDLE' }]), 'present');
  assert.equal(roomOccupancy([{ runtime_state: 'IDLE' }, { runtime_state: 'THINKING' }]), 'working');
  // at night the difference is strong, by day it is the daylight that lights the room
  assert.equal(roomShade('working', 0), 0);
  assert.equal(roomShade('working', 1), 0);
  assert.ok(roomShade('empty', 0) > roomShade('present', 0));
  assert.ok(roomShade('present', 0) > roomShade('present', 1));
  assert.ok(roomShade('empty', 1) < 0.2, 'by day an empty room is only a little darker');
  assert.equal(roomShade('empty', 0.5), (0.5 + 0.14) / 2);
});

test('a screen is washed by the sun and glows only when the sun is gone', () => {
  assert.deepEqual(screenLight(0), { washout: 0, bloom: 1 });
  assert.equal(screenLight(1).bloom, 0);
  assert.ok(screenLight(1).washout > 0);
  assert.ok(screenLight(0.5).bloom > 0 && screenLight(0.5).bloom < 1);
});

test('every screen the manifest lists is bound, and every pane lies inside its screen', () => {
  for (const [name, screen] of Object.entries(MANIFEST.screens)) {
    const bound = screen.kind === 'render_status' || DESK_MONITOR.test(name) || name in PANES || screen.zone;
    assert.ok(bound, `${name} is bound`);
    for (const [x, y, w, h] of PANES[name] || []) {
      const [sx, sy, sw, sh] = screen.rect;
      // 3 px of slack: the manifest's rectangles were drawn around the screens by hand, and the
      // panes were measured off the plates (the fact-check room's right monitor ends at 948).
      assert.ok(x >= sx - 3 && y >= sy - 3 && x + w <= sx + sw + 3 && y + h <= sy + sh + 3, `${name}: a pane stays inside the screen`);
    }
  }
  for (const [name, extra] of Object.entries(EXTRA_SCREENS)) {
    assert.ok(MANIFEST.seats[extra.desk], `${name} follows a desk that exists`);
    assert.ok(MANIFEST.rooms[extra.zone], `${name} stands in a room that exists`);
  }
  const quad = deskPane([1002.4, 462.9, 11.2, 10.2]);
  assert.equal(quad.length, 4);
  for (const [px, py] of quad) assert.ok(px > 1002.4 && px < 1013.6 && py > 462.9 && py < 473.1, 'a desk monitor is painted inside its frame');
  assert.ok(quad[0][1] > quad[1][1], 'turned towards its employee: the left edge stands lower');
});

test('the walls bound to values stand inside the building, each inside its own room', () => {
  const inside = (r, room) => r[0] >= room.x && r[1] >= room.y && r[0] + r[2] <= room.x + room.w && r[1] + r[3] <= room.y + room.h;
  assert.ok(inside(WALL.treasury_board, MANIFEST.rooms.accounting_office));
  assert.ok(inside(WALL.factcheck_board, MANIFEST.rooms.factcheck_room));
  assert.ok(inside(WALL.writers_screen, MANIFEST.rooms.script_room));
  for (const note of NOTES) assert.ok(inside(note, MANIFEST.rooms.research_lab));
  const sign = MANIFEST.labels.sign;
  const r = WALL.run_sign;
  assert.ok(r[0] >= sign.x && r[1] >= sign.y && r[0] + r[2] <= sign.x + sign.w && r[1] + r[3] <= sign.y + sign.h, 'the run track stays on the façade sign');
});

/* -------------------------------------------------------------------- the render bay -- */

test('the newest film is the newest run that rendered one, its last asset', () => {
  assert.equal(latestFilm(null), null);
  assert.equal(latestFilm([{ stages: [{ stage: 'media', artefacts: { assets: [] } }] }]), null);
  const runs = [
    { business_date: '2026-09-13', stages: [{ stage: 'media', artefacts: { assets: [] } }] },
    { business_date: '2026-09-12', stages: [{ stage: 'media', artefacts: { assets: ['a', 'b'] } }] },
  ];
  assert.deepEqual(latestFilm(runs), { assetId: 'b', date: '2026-09-12' });
});

test('the render bay shows the render at work, else the newest film, else the state; never a number', () => {
  const working = renderBayFace({ agent: { runtime_state: 'WORKING', task_type: 'review_failed_render' }, film: { canvas: {}, assetId: 'x', date: '2026-09-12' } });
  assert.equal(working.kind, 'rendering');
  assert.equal(working.word, 'ÎN LUCRU');
  assert.equal(working.detail, 'diagnoza randării');
  const poster = renderBayFace({ agent: { runtime_state: 'IDLE' }, film: { canvas: {}, assetId: 'x', date: '2026-09-12' } });
  assert.equal(poster.kind, 'poster');
  assert.equal(poster.caption, 'ultimul film · 12.09');
  const noFrame = renderBayFace({ agent: { runtime_state: 'IDLE' }, film: { canvas: null, assetId: 'x' } });
  assert.equal(noFrame.kind, 'state');
  assert.equal(noFrame.word, 'ÎN AȘTEPTARE');
  assert.equal(renderBayFace({ agent: null }).word, '—', 'no editor at the desk: nothing is claimed');
  assert.equal(renderBayFace({ agent: { runtime_state: 'ERROR' } }).fault, true);
  assert.notEqual(poster.key, noFrame.key);
});

/* --------------------------------------------------------------------- the treasury -- */

test('the Treasury ticker shows the spendable balance and today against the daily budget, in Romanian figures', () => {
  const treasury = { spendable: { amount: '50000' }, in_deficit: false };
  const budget = { budgets: [{ period: 'DAILY', active: true, limit_usd: '15', spent_usd: '1.250000', ratio: 0.0833, state: 'OK' }], today: { spent_usd: '1.25' } };
  const face = treasuryFace(treasury, budget);
  assert.equal(face.balance, '50.000');
  assert.equal(face.line, 'azi 1,25 / 15 USD');
  assert.equal(face.ratio, 0.0833);
  assert.equal(face.state, 'OK');
  const none = treasuryFace(null, null);
  assert.equal(none.balance, '—');
  assert.equal(none.line, 'azi —');
  assert.equal(none.ratio, null);
  const unbudgeted = treasuryFace(treasury, { budgets: [], today: { spent_usd: '0.316' } });
  assert.equal(unbudgeted.line, 'azi 0,31 USD · fără buget');
  assert.equal(treasuryFace({ spendable: { amount: '-120.5' }, in_deficit: true }, null).balance, '−120,5');
  assert.equal(treasuryFace({ spendable: { amount: 'n/a' } }, null).balance, '—');
});

test('money is cut to cents, never rounded up', () => {
  assert.equal(wholeOrCents('50000'), '50000');
  assert.equal(wholeOrCents('0.316000'), '0.31');
  assert.equal(wholeOrCents('12.500'), '12.5');
  assert.equal(wholeOrCents('7.000'), '7');
  assert.equal(wholeOrCents('50000.009'), '50000', 'cut to cents first: no «,00» left over');
});

/* -------------------------------------------------------------------- the run track -- */

test('the façade sign says what the slate says about the day', () => {
  const recorded = dayTrackFromRun(RUN);
  const face = runSignFace(recorded, { today: '2026-09-24' });
  assert.equal(face.segments.length, recorded.segments.length);
  assert.equal(face.title, `RULAREA DIN ${RUN.business_date.slice(8, 10)}.${RUN.business_date.slice(5, 7)}`);
  assert.match(face.tally, /^\d+\/\d+$/);
  assert.equal(face.running, -1);
  const empty = runSignFace(null);
  assert.equal(empty.tally, '—');
  assert.deepEqual(empty.segments, []);
  const live = dayTrack([
    { event_type: 'runbook.stage_started', payload: { stage: 'media', index: 7, total: 12 }, timestamp: '2026-09-24T09:10:00Z' },
    { event_type: 'runbook.daily_run_started', aggregate_id: 'r', payload: { date: '2026-09-24', preflight: 'READY', stages: 12 }, timestamp: '2026-09-24T09:00:00Z' },
  ]);
  const running = runSignFace(live, { today: '2026-09-24', live: true });
  assert.equal(running.title, 'RULAREA DE AZI');
  assert.equal(running.running, 6);
  assert.equal(running.state, 'acum: producție media');
  assert.notEqual(running.key, face.key);
});

/* -------------------------------------------------------------- the boards and walls -- */

test('the fact-check board writes the newest run\'s own counts, and a dash without them', () => {
  const run = { business_date: '2026-09-12', stages: [{ stage: 'research_and_verification', artefacts: { claims_verified: 3, verdicts_refused: 11 } }] };
  assert.deepEqual({ ...factCheckFace(run), key: undefined }, { verified: '3', refused: '11', date: '12.09', key: undefined });
  const none = factCheckFace(null);
  assert.equal(none.verified, '—');
  assert.equal(none.refused, '—');
  assert.equal(none.date, '');
  assert.equal(factCheckFace({ stages: [{ stage: 'research_and_verification', artefacts: {} }] }).verified, '—');
  assert.equal(factCheckFace({ business_date: '2026-09-12', stages: [{ stage: 'research_and_verification', artefacts: { claims_verified: 1200 } }] }).verified, '1.200');
});

test('the research board pins the newest topics the Researcher proposed, at most six', () => {
  const events = [
    { event_type: 'factual.topic_proposed', payload: { title: 'Newest' } },
    { event_type: 'agent.message_posted', payload: { title: 'not a topic' } },
    ...Array.from({ length: 8 }, (_, i) => ({ event_type: 'factual.topic_proposed', payload: { title: `T${i}` } })),
    { event_type: 'factual.topic_proposed', payload: {} },
  ];
  const board = boardTopics(events);
  assert.deepEqual(board.titles, ['Newest', 'T0', 'T1', 'T2', 'T3', 'T4']);
  assert.deepEqual(boardTopics([]).titles, []);
});

test('the writers\' screen shows the newest episode, its number only when the backend gave one', () => {
  assert.equal(writersFace(null).number, '—');
  assert.equal(writersFace({ episodes: [] }).state, 'niciun episod');
  const face = writersFace({ episodes: [
    { created_at: '2026-09-22T20:00:00Z', status: 'APPROVED', title: 'Old', continuity: { episode_number: 2 } },
    { created_at: '2026-09-23T21:00:00Z', status: 'DRAFT', title: 'The Render That Wouldn\'t Wait', continuity: { episode_number: 3 } },
  ] });
  assert.equal(face.number, 'EP 3');
  assert.equal(face.state, 'Ciornă');
  assert.equal(face.title, 'The Render That Wouldn\'t Wait');
  assert.equal(writersFace({ episodes: [{ created_at: '2026-09-12T00:00:00Z', status: 'DRAFT', title: 'v2', continuity: {} }] }).number, 'EP —');
});

test('the radar says what the newest run published', () => {
  assert.equal(publishFace(null).word, '—');
  assert.equal(publishFace({ business_date: '2026-09-12', stages: [{ stage: 'publish', artefacts: { publication_status: 'PUBLISHED' } }] }).word, 'PUBLICAT');
  assert.equal(publishFace({ business_date: '2026-09-12', stages: [{ stage: 'publish', artefacts: {} }] }).word, 'NIMIC PUBLICAT');
  // W9: a simulated upload is no video on the channel, and no backend code is shown in English
  const face = (status) => publishFace({ business_date: '2026-09-12', stages: [{ stage: 'publish', artefacts: { publication_status: status } }] }).word;
  assert.equal(face('PUBLISHED_SIMULATED'), 'SIMULAT');
  assert.equal(face('REMOTE_CONFIRMED'), 'PUBLICAT');
  assert.equal(face('SCHEDULED'), 'PROGRAMAT');
  assert.equal(face('REMOTE_UNKNOWN'), 'NECONFIRMAT');
  assert.equal(face('FAILED'), 'EȘUAT');
});

test('tokens used today are counted as a Romanian speaker counts them', () => {
  assert.equal(tokensFace(null).text, 'tokenuri azi —');
  assert.equal(tokensFace({ today: { prompt_tokens: 0, completion_tokens: 0 } }).text, '0 tokenuri azi');
  assert.equal(tokensFace({ today: { prompt_tokens: 1, completion_tokens: 0 } }).text, '1 token azi');
  assert.equal(tokensFace({ today: { prompt_tokens: 12, completion_tokens: 7 } }).text, '19 tokenuri azi');
  assert.equal(tokensFace({ today: { prompt_tokens: 1782381, completion_tokens: 301637 } }).text, '2.084.018 tokenuri azi');
  assert.equal(tokensFace({ today: { prompt_tokens: 1782383, completion_tokens: 301637 } }).text, '2.084.020 de tokenuri azi');
});

/* ---------------------------------------------------------------- drawing and cache -- */

/** A 2D context that records calls, enough for the painters. */
function recorder() {
  const calls = [];
  const ctx = new Proxy({ calls }, {
    get(target, prop) {
      if (prop in target) return target[prop];
      if (prop === 'measureText') return (t) => ({ width: String(t).length * 2 });
      if (prop === 'createLinearGradient' || prop === 'createRadialGradient') return () => ({ addColorStop() {} });
      return (...args) => { calls.push([prop, ...args]); };
    },
    set(target, prop, value) { calls.push([`=${String(prop)}`, value]); return true; },
  });
  return ctx;
}

test('every painter draws its face without a document, and no painter invents a figure', () => {
  const palette = { okInk: '#0f0', warnInk: '#ff0', alertInk: '#f00', chromeMuted: '#888', gold: '#fc0', segPending: '#333', segUnrun: '#111' };
  const texts = (ctx) => ctx.calls.filter((c) => c[0] === 'fillText').map((c) => c[1]);
  let c = recorder();
  paintTreasury(c, 23.5, 22.8, treasuryFace(null, null));
  assert.ok(texts(c).includes('—'));
  c = recorder();
  paintFactCheck(c, 28.5, 39.5, factCheckFace(null));
  assert.equal(texts(c).filter((t) => t === '—').length, 2);
  c = recorder();
  paintRunSign(c, 132, 30, runSignFace(null), palette);
  assert.ok(texts(c).includes('—'));
  c = recorder();
  paintWriters(c, 57.5, 26.5, writersFace(null));
  assert.ok(texts(c).includes('—'));
  c = recorder();
  paintNote(c, 22, 12, '');
  assert.equal(texts(c).length, 0, 'a note with no topic is blank paper');
  c = recorder();
  paintPublish(c, 36, 28, publishFace(null));
  paintInfra(c, 84, 13, tokensFace(null));
  paintRenderBay(c, 61, 60, renderBayFace({ agent: null }), null);
  assert.ok(texts(c).includes('RANDARE'));
});

test('a monitor moves only with the clock: the same clock draws the same frame', () => {
  const frame = (clock) => {
    const c = recorder();
    drawPane(c, [0, 0, 20, 12], 'work', '120,170,255', clock, 3);
    return JSON.stringify(c.calls);
  };
  assert.equal(frame(2), frame(2), 'a held clock (reduced motion) holds the picture');
  assert.notEqual(frame(2), frame(2.5), 'work moves while the clock runs');
  const idle = (clock) => { const c = recorder(); drawPane(c, [0, 0, 20, 12], 'idle', '1,2,3', clock, 3); return JSON.stringify(c.calls); };
  assert.equal(idle(1), idle(9), 'an idle screen does not flicker');
  const dark = (clock) => { const c = recorder(); drawPane(c, [0, 0, 20, 12], 'dark', '1,2,3', clock, 3); return JSON.stringify(c.calls); };
  assert.equal(dark(1), dark(9));
});

test('a face is drawn once per value and scale', () => {
  const saved = globalThis.document;
  let made = 0;
  globalThis.document = { createElement: () => { made += 1; return { width: 0, height: 0, getContext: () => recorder() }; } };
  try {
    const cache = new FaceCache();
    let painted = 0;
    const paint = () => { painted += 1; };
    cache.get('t', 'a', 20, 10, 1.2, paint);
    cache.get('t', 'a', 20, 10, 1.2, paint);
    cache.get('t', 'a', 20, 10, 1.4, paint);
    assert.equal(painted, 1, 'the same value at a nearby scale is not redrawn');
    cache.get('t', 'b', 20, 10, 1.4, paint);
    assert.equal(painted, 2, 'a new value is');
    cache.get('t', 'b', 20, 10, 3, paint);
    assert.equal(painted, 3, 'and so is a new scale bucket');
    assert.equal(made, 1, 'one canvas per surface, reused');
  } finally {
    if (saved === undefined) delete globalThis.document;
    else globalThis.document = saved;
  }
});
