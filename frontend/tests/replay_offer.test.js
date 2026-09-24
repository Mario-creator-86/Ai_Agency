// W15 «the replay offered, and made whole»: the invitation's words and rules, the replay's reads
// by time (/events?since=) and of the books at past moments (/economy/as-of), the walls' words.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { acceptFigures, buildTimeline, figureMoments, figuresAt, figuresQuery, readRecord, REPLAY_TAIL_MS } from '../src/day_replay.js';
import { GROUND_FLOOR, INVITE_KEY, inviteMemory, invitePlacement, inviteWords, publishedCount, restingNow } from '../src/replay_invite.js';
import { tokensFace, treasuryFace } from '../src/hq_screens.js';

const FIX = JSON.parse(fs.readFileSync(new URL('./fixtures/replay_runs_2026-09-12.json', import.meta.url), 'utf8'));
const RUN = FIX.complete.run;
const EVENTS = FIX.complete.events;
const TZ = 'Europe/Bucharest';

/** /events as a studio answers it; `withSince` false is a studio that ignores `since`. */
function studio(rows, { withSince }, calls) {
  const page = (after, limit) => {
    const got = rows.filter((e) => e.sequence > after).slice(0, limit + 1);
    const events = got.slice(0, limit);
    return { events, next_cursor: events.length ? events.at(-1).sequence : after, has_more: got.length > limit };
  };
  return {
    get: async (after, limit) => { calls.push(['after', after, limit]); return page(after, limit); },
    since: async (iso, limit) => {
      calls.push(['since', iso, limit]);
      if (!withSince) return page(0, limit); // an older studio: the parameter is ignored
      const t = Date.parse(iso);
      const first = rows.find((e) => Date.parse(e.timestamp) >= t);
      const answer = page(first ? first.sequence - 1 : Infinity, limit);
      return { ...answer, since: new Date(t).toISOString() };
    },
  };
}

test('a studio that reads its log by time gives the run in one request, the same events as bisection', async () => {
  const calls = [];
  const s = studio(EVENTS, { withSince: true }, calls);
  const fast = await readRecord(s.get, RUN, { since: s.since, cursor: EVENTS.at(-1).sequence });
  assert.equal(fast.method, 'since');
  assert.equal(fast.requests, 1);
  assert.equal(calls.length, 1);
  assert.equal(Date.parse(calls[0][1]), Date.parse(RUN.started_at) - REPLAY_TAIL_MS);
  const slowCalls = [];
  const old = studio(EVENTS, { withSince: false }, slowCalls);
  const slow = await readRecord(old.get, RUN, { since: old.since, cursor: EVENTS.at(-1).sequence });
  assert.equal(slow.method, 'bisect', 'a page that does not name its instant is not believed');
  assert.ok(slow.requests > 3);
  const ids = (r) => buildTimeline(RUN, r.events).events.map((e) => e.event_id);
  assert.deepEqual(ids(fast), ids(slow));
  assert.equal(buildTimeline(RUN, fast.events).events.length, 214);
});

test('the books are asked at the run start, its end and after every event that can move a figure', () => {
  const timeline = buildTimeline(RUN, EVENTS);
  const moments = figureMoments(timeline);
  const expected = new Set([timeline.start, timeline.end + 1]);
  for (const e of timeline.events) if (e.event_type === 'agent.run_completed' || e.event_type.startsWith('economy.')) expected.add(Date.parse(e.timestamp) + 1);
  assert.deepEqual(moments.map((m) => Date.parse(m)), [...expected].sort((a, b) => a - b));
});

test('a wall shows the reading that held at the moment, «—» before the first', () => {
  const readings = [{ at: '2026-09-12T20:48:06Z', v: 1 }, { at: '2026-09-12T20:50:00Z', v: 2 }, { at: '2026-09-12T20:59:45Z', v: 3 }];
  assert.equal(figuresAt(readings, Date.parse('2026-09-12T20:48:00Z')), null);
  // a reading taken a millisecond after its event is the wall's from the event on
  assert.equal(figuresAt([{ at: '2026-09-12T20:48:06.001Z', v: 1 }], Date.parse('2026-09-12T20:48:06Z')).v, 1);
  assert.equal(figuresAt(readings, Date.parse('2026-09-12T20:48:06Z')).v, 1);
  assert.equal(figuresAt(readings, Date.parse('2026-09-12T20:55:00Z')).v, 2);
  assert.equal(figuresAt(readings, Date.parse('2026-09-13T00:00:00Z')).v, 3);
  assert.equal(figuresAt(null, 0), null);
});

test("the books' answer is believed only when it answers the moments asked", () => {
  const asked = ['2026-09-12T20:48:06.030Z', '2026-09-12T20:50:00.000Z'];
  const reading = (at) => ({ at, treasury: { spendable: { amount: '50' } }, budget: { today: {} } });
  assert.equal(acceptFigures({ readings: [reading('2026-09-12T20:48:06.030000+00:00'), reading('2026-09-12T20:50:00+00:00')] }, asked).length, 2);
  assert.equal(acceptFigures({ readings: [reading('2026-09-12T20:48:06.030000+00:00')] }, asked), null);
  assert.equal(acceptFigures({ spendable: {} }, asked), null, 'the live treasury is not a reading');
  assert.equal(acceptFigures(null, asked), null);
});

test('in the replay the walls say «atunci», never «azi»', () => {
  const budget = { budgets: [{ period: 'DAILY', limit_usd: '15', spent_usd: '0.124', ratio: 0.01, state: 'OK' }], today: { prompt_tokens: 1400, completion_tokens: 100 } };
  assert.equal(treasuryFace({ spendable: { amount: '50' } }, budget, 'atunci').line, 'atunci 0,12 / 15 USD');
  assert.equal(tokensFace(budget, 'atunci').text, '1.500 de tokenuri atunci');
  assert.equal(tokensFace(null, 'atunci').text, 'tokenuri atunci —');
  assert.equal(treasuryFace(null, null, 'atunci').line, 'atunci —');
  assert.equal(treasuryFace(null, null).line, 'azi —');
});

test("the invitation says the last working day from the run's record only", () => {
  const words = inviteWords(RUN, { timeZone: TZ });
  assert.equal(words.lead, 'Studioul se odihnește acum.');
  assert.equal(words.line, 'Ultima rulare încheiată: sâmbătă 12.09, 23:48–23:59 · 12 etape · 1 film publicat.');
  assert.match(words.sentence, /Vezi reluarea/);
  const partial = { ...RUN, stages_completed: 7, stages: RUN.stages.filter((s) => s.stage !== 'publish') };
  assert.equal(inviteWords(partial, { timeZone: TZ }).line, 'Ultima rulare încheiată: sâmbătă 12.09, 23:48–23:59 · 7 din 12 etape · niciun film publicat.');
  assert.equal(inviteWords({ ...RUN, finished_at: null }), null);
});

test("films published: the backend's count, its list, or a legacy run's publication", () => {
  const run = (publish) => ({ stages: publish ? [{ stage: 'publish', ...publish }] : [] });
  assert.equal(publishedCount(null), null);
  assert.equal(publishedCount(run(null)), 0);
  assert.equal(publishedCount(run({ produced: 2, artefacts: {} })), 2);
  assert.equal(publishedCount(run({ artefacts: { published: [{}, {}, {}] } })), 3);
  assert.equal(publishedCount(run({ artefacts: { publication_id: 'p', publication_status: 'PUBLISHED' } })), 1);
  assert.equal(publishedCount(run({ artefacts: { publication_id: 'p', publication_status: 'PUBLISHED_SIMULATED' } })), 0);
  assert.equal(publishedCount(RUN), 1);
});

test('the studio rests only with a finished run, no run under way and nobody at work', () => {
  const idle = [{ runtime_state: 'IDLE' }, { runtime_state: 'PAUSED' }];
  assert.equal(restingNow({ run: RUN, live: false, agents: idle }), true);
  assert.equal(restingNow({ run: RUN, live: true, agents: idle }), false);
  assert.equal(restingNow({ run: null, live: false, agents: idle }), false);
  for (const state of ['WORKING', 'THINKING', 'working']) assert.equal(restingNow({ run: RUN, live: false, agents: [...idle, { runtime_state: state }] }), false, state);
});

test('the invitation stands under the building, never over its floors of work', () => {
  const building = { x: 440, y: 112, w: 1070, h: 765 };
  const room = { left: 360, top: 48, right: 1580, bottom: 1000 };
  const spot = invitePlacement({ room, building, card: { w: 700, h: 60 }, gap: 12 });
  assert.equal(spot.x, Math.round(360 + (1580 - 360) / 2 - 350));
  assert.equal(spot.y, 112 + 765 + 12, 'on the street');
  // a short street: as low as the room allows, over the ground floor at most
  const low = invitePlacement({ room: { ...room, bottom: 900 }, building, card: { w: 700, h: 60 }, gap: 12 });
  assert.equal(low.y, 900 - 12 - 60);
  assert.ok(low.y >= building.y + building.h * GROUND_FLOOR);
  assert.equal(invitePlacement({ room: { ...room, bottom: 700 }, building, card: { w: 700, h: 60 } }), null, 'never over the floors of work');
  assert.equal(invitePlacement({ room: { ...room, right: 900 }, building, card: { w: 700, h: 60 } }), null, 'not squeezed');
});

test('the session remembers the invitation; a storage that throws forgets it and breaks nothing', () => {
  const store = new Map();
  const ok = inviteMemory(() => ({ getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) }));
  assert.equal(ok.seen(), false);
  ok.remember();
  assert.equal(store.get(INVITE_KEY), '1');
  assert.equal(ok.seen(), true);
  const broken = inviteMemory(() => { throw new Error('SecurityError'); });
  assert.equal(broken.seen(), false);
  assert.doesNotThrow(() => broken.remember());
  assert.equal(inviteMemory(() => null).seen(), false);
});

test('the replayed world is lit by its own moment over Bucharest and draws no weather', async () => {
  const { WorldSimulationManager } = await import('../src/hq_world.js');
  const { BUCHAREST } = await import('../src/hq_time.js');
  const { NO_WEATHER } = await import('../src/hq_weather.js');
  const noon = new Date('2026-09-24T09:00:00Z');
  const seen = {};
  const rec = (name) => ({ update: (dt) => { seen[name] = dt; return { phase: 'day', hour: 12, day: 3, daylight: 1 }; } });
  const world = {
    replayAt: null,
    time: { now: () => noon, location: BUCHAREST, state: null, update: () => { seen.liveClock = true; return world.time.state; } },
    weather: { update() {}, effects: { cloudiness: 0.9, rain: 0.8, snow: 0, fog: 0, wet: 1, wind: 0.3 }, state: { condition: 'rain' } },
    events: { update: (dt, ctx) => { seen.eventsWeather = ctx.weather; } },
    traffic: rec('traffic'),
    pedestrians: { ...rec('pedestrians'), crosswalkBusy: false, waitingAtShelter: 0 },
    agents: rec('agents'),
    ambient: rec('ambient'),
    sky: { update: (dt, time, fx) => { seen.skyFx = fx; seen.skyTime = time; } },
    assets: { loadVariant() {} },
  };
  const set = (ms) => WorldSimulationManager.prototype.setReplayMoment.call(world, ms);
  set(Date.parse('2026-09-12T20:49:35Z'));
  assert.equal(world.time.state.text, '23:49', 'the replayed moment in Bucharest');
  assert.equal(world.time.state.night, true, 'its own sun: night at 23:49 in September');
  WorldSimulationManager.prototype.step.call(world, 0.016, Date.now(), false);
  assert.equal(seen.liveClock, undefined, "today's clock does not relight the replayed world");
  assert.deepEqual(seen.skyFx, NO_WEATHER, 'no weather is drawn: that night\'s is not known');
  assert.equal(seen.eventsWeather, 'unknown');
  // a moment less than a second on is not re-read
  const state = world.time.state;
  set(Date.parse('2026-09-12T20:49:35.500Z'));
  assert.equal(world.time.state, state);
  set(null);
  assert.equal(world.replayAt, null);
  assert.equal(world.time.state.text, '12:00', 'back to the real hour at once');
  assert.equal(world.time.state.night, false);
});

test('a step of the sun is composed a group a frame and taken whole; a jump at once; a light prepared ahead is taken at once', async () => {
  const { HQRenderer } = await import('../src/hq_world.js');
  const made = [];
  const ctx = () => ({ setTransform() {}, clearRect() {}, drawImage() {}, fillText() {}, set font(v) {}, set textAlign(v) {}, set fillStyle(v) {}, set globalAlpha(v) {}, imageSmoothingEnabled: true, imageSmoothingQuality: 'low', measureText: () => ({ width: 1 }) });
  const hadDocument = 'document' in globalThis;
  globalThis.document = { createElement: () => { const c = { width: 0, height: 0, getContext: ctx }; made.push(c); return c; } };
  try {
    const layer = { img: {}, x: 0, y: 0, w: 100, h: 50 };
    const r = Object.create(HQRenderer.prototype);
    Object.assign(r, {
      assets: { layers: { night: { a: 1 }, day: { a: 1 } }, layer: () => layer },
      caches: new Map(), cacheKey: '', _cacheLight: -1, _staging: null, _spare: null, _prepared: null, _wantedScale: 0, _scaleSince: 0,
    });
    const noon = { daylight: 1 };
    const night = { daylight: 0.97 }; // one step of the sun: 40 -> 39
    assert.equal(r.ensureCaches(1, noon), true);
    const groups = r.caches.size;
    assert.equal(groups, 7, 'the first light is composed at once');
    const first = r.caches;
    r._scaleSince = -Infinity; // the scale has settled (220 ms on)
    const calls = [];
    const compose = r.composeGroup.bind(r);
    r.composeGroup = (...a) => { calls.push(a[1]); return compose(...a); };
    for (let i = 0; i < groups - 1; i++) {
      r.ensureCaches(1, night);
      assert.equal(r.caches, first, 'the frames between keep the previous light whole');
    }
    assert.equal(calls.length, groups - 1, 'one group per frame');
    r.ensureCaches(1, night);
    assert.notEqual(r.caches, first, 'taken whole once every group is done');
    assert.equal(r.caches.size, 7);
    // a jump (back to live from a replayed night) is composed at once: no night plates under a noon sky
    calls.length = 0;
    const stepped = r.caches;
    r.ensureCaches(1, { daylight: 0 });
    assert.equal(calls.length, 7);
    assert.equal(r.caches, stepped, 'composed in place, at once');
    // prepared ahead of its first frame: taken at once, no composition in that frame
    calls.length = 0;
    globalThis.requestAnimationFrame = (f) => setTimeout(f, 0);
    await r.prepareLight(1, noon, 0);
    const composedAhead = calls.length;
    const before = r.caches;
    r.ensureCaches(1, noon);
    assert.equal(calls.length, composedAhead, 'nothing composed in the frame of the switch');
    assert.notEqual(r.caches, before);
    assert.equal(r._prepared, null);
  } finally {
    if (!hadDocument) delete globalThis.document;
  }
});

test('W16: the books are asked only of a studio that read its log by time (no 404 from an older one)', () => {
  const timeline = buildTimeline(RUN, EVENTS);
  assert.equal(figuresQuery(timeline, 'bisect'), null, 'a studio without `since` predates /economy/as-of');
  assert.equal(figuresQuery(timeline, ''), null);
  assert.equal(figuresQuery(null, 'since'), null);
  const query = figuresQuery(timeline, 'since');
  assert.ok(query);
  assert.deepEqual(query.moments, figureMoments(timeline));
  assert.equal(query.reads.length, 1, 'a run of 12.09 is one read');
  assert.equal(query.until, null);
  assert.ok(query.reads[0].path.startsWith('/economy/as-of?at='));
  const asked = new URLSearchParams(query.reads[0].path.split('?')[1]).getAll('at');
  assert.deepEqual(asked, query.moments, 'every moment asked, in order, encoded');
});
