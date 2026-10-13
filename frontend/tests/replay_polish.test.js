// W17 «the last polish»: every moment of the books asked (in reads of 240, all at the start), «—»
// after the last moment asked, and focus moved by the page only for a keyboard visitor.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { FIGURES_MAX, FIGURES_READS_MAX, figureMoments, figuresAt, figuresQuery } from '../src/day_replay.js';
import { fromKeyboard, replayFocus } from '../src/replay_invite.js';

/** A run whose books moved `n` times, one economy event a second. */
function busyRun(n) {
  const start = Date.parse('2026-09-12T20:48:00Z');
  const events = Array.from({ length: n }, (_, i) => ({ event_type: 'economy.cost_recorded', timestamp: new Date(start + 1000 * (i + 1)).toISOString() }));
  return { start, end: start + 1000 * (n + 2), events };
}

test('every moment the books can have moved is asked, not only the first 240', () => {
  const timeline = busyRun(600);
  const moments = figureMoments(timeline);
  assert.equal(moments.length, 602, 'start, 600 changes, end');
  const query = figuresQuery(timeline, 'since');
  assert.ok(query);
  assert.equal(query.reads.length, 3);
  for (const read of query.reads) {
    assert.ok(read.moments.length <= FIGURES_MAX);
    assert.deepEqual(new URLSearchParams(read.path.split('?')[1]).getAll('at'), read.moments);
  }
  assert.deepEqual(query.reads.flatMap((r) => r.moments), moments, 'the reads together ask every moment, in order');
  assert.equal(query.until, null);
});

test('past the reads a replay makes, the walls say «—» from the first moment not asked, never a stale figure', () => {
  const cap = FIGURES_MAX * FIGURES_READS_MAX;
  const timeline = busyRun(cap + 50);
  const query = figuresQuery(timeline, 'since');
  assert.ok(query);
  assert.equal(query.reads.length, FIGURES_READS_MAX);
  assert.equal(query.moments.length, cap);
  const all = figureMoments(timeline);
  assert.equal(query.until, Date.parse(all[cap]));
  const readings = query.moments.map((at, i) => ({ at, v: i }));
  const lastAsked = Date.parse(query.moments.at(-1));
  assert.equal(figuresAt(readings, lastAsked, query.until).v, cap - 1, 'the last moment asked still holds');
  // the event that moves the next figure is stamped a millisecond before the moment asked after it
  assert.equal(figuresAt(readings, query.until - 1, query.until), null, 'from that event on: not known');
  assert.equal(figuresAt(readings, timeline.end, query.until), null);
  assert.equal(figuresAt(readings, lastAsked, null).v, cap - 1, 'without a limit nothing changes');
});

test('the run of 12.09 is still asked in one read', () => {
  const FIX = JSON.parse(fs.readFileSync(new URL('./fixtures/replay_runs_2026-09-12.json', import.meta.url), 'utf8'));
  const start = Date.parse(FIX.complete.run.started_at);
  const end = Date.parse(FIX.complete.run.finished_at);
  const query = figuresQuery({ start, end, events: FIX.complete.events }, 'since');
  assert.ok(query);
  assert.equal(query.reads.length, 1);
});

test('a click from Enter or Space (no pointer press) is the keyboard; a pointer click is not', () => {
  assert.equal(fromKeyboard({ detail: 0 }), true);
  assert.equal(fromKeyboard({ detail: 1 }), false);
  assert.equal(fromKeyboard({ detail: 2 }), false);
  assert.equal(fromKeyboard(null), false);
  assert.equal(fromKeyboard(undefined), false);
});

test('the page moves focus only for a keyboard visitor, or when the controls holding it go', () => {
  assert.deepEqual(replayFocus({ keyboard: true, inControls: false }), { onStart: true, onExit: true });
  assert.deepEqual(replayFocus({ keyboard: false, inControls: false }), { onStart: false, onExit: false }, 'a mouse visitor keeps their focus: no «RELUARE» label left over the live building');
  assert.deepEqual(replayFocus({ keyboard: false, inControls: true }), { onStart: false, onExit: true }, 'a focus on the replay\'s own keys is not lost with them');
});

test('in a narrow frame the live hour beside ATUNCI says it is now; the end offers the way back to live', () => {
  const css = fs.readFileSync(new URL('../src/office_scene.css', import.meta.url), 'utf8');
  const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  assert.match(html, /<span class="scene-label replay-now-label">ACUM<\/span><span id="scene-info">/);
  assert.match(css, /max-width: 1599\.98px\) \{\s+\.scene-viewport\[data-replay\] #scene-info > :nth-child\(n\+2\) \{ display: none; \}\s+\/\*[^*]*\*\/\s+\.scene-viewport\[data-replay\] \.replay-now-label \{ display: inline; \}/);
  assert.match(css, /\.scene-viewport \.replay-now-label \{ display: none;/);
  assert.match(html, /<button id="replay-back" class="replay-back" type="button" title="Înapoi la live \(Esc\)" hidden>Înapoi la live<\/button>/);
  assert.match(css, /\.scene-viewport \.replay-back \{[^}]*min-height: var\(--hit\)/);
});

test("the Owner's own switches read in the register's words, never as raw keys", async () => {
  const { describeEvent } = await import('../src/ledger.js');
  const mode = describeEvent({ event_type: 'owner.autonomy_mode_changed', payload: { autonomy_mode: 'AUTONOMOUS_CEO', previous_autonomy_mode: 'SUPERVISED', direction: 'PROMOTION' } });
  assert.equal(mode.label, 'Proprietarul a schimbat modul de autonomie');
  assert.equal(mode.text, 'Supravegheat → CEO autonom');
  assert.equal(mode.kind, 'owner');
  const env = describeEvent({ event_type: 'owner.environment_changed', payload: { environment: 'TEST' } });
  assert.equal(env.label, 'Proprietarul a schimbat mediul');
  assert.equal(env.text, 'MEDIU TEST');
  assert.equal(env.kind, 'owner');
});
