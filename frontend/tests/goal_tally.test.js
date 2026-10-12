/**
 * THE DAY'S GOAL (goal_tally.js, 2026-10-12): the register's head shows the snapshot's `goal` as
 * the record counts it, per channel, in the backend's words; an unreadable goal draws nothing.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { goalTallyHtml, renderGoalTally } from '../src/goal_tally.js';
import { escapeHtml } from '../src/html.js';

/** The snapshot's goal as backend/app/goal.py writes it. */
const GOAL = {
  day: '2026-10-12',
  target_per_channel: 2,
  words_ro: 'Azi (2026-10-12): shorturi 1/2, episoade 0/2 publicate; 2 în lucru; 1 așteaptă decizia ta.',
  channels: [
    {
      channel_type: 'MAIN_FACTUAL',
      channel_id: 'ch-1',
      channel_name: 'AMN Facts',
      target: 2,
      published: [{ title: 'Why the Moon Rings', at: '2026-10-12T08:12:00+00:00', url: 'https://youtube.com/shorts/abc' }],
      in_work: [{ storyboard_id: 'b-1', title: 'The Zero Script Club', whose: 'director', words_ro: 'controlul calității a picat; Directoarea decide', since: '2026-10-11T09:12' }],
      blocked: [{ storyboard_id: 'b-2', title: 'Salt & <Static>', whose: 'owner', words_ro: 'cardul tău: Refacerea plătită a scenei 5 a atins plafonul', since: '2026-10-10T17:40' }],
    },
    {
      channel_type: 'OFFICE_SERIAL',
      channel_id: 'ch-2',
      channel_name: null,
      target: 2,
      published: [],
      in_work: [{ storyboard_id: 'b-3', title: 'Episodul 2: Cafeaua', whose: 'studio', words_ro: 'gata de asamblare', since: '2026-10-12T05:01' }],
      blocked: [],
      next_episode: { title: 'Episodul 3: Tăcerea', status: 'APPROVED', words_ro: 'aprobat, se pregătește de filmare' },
    },
  ],
};

test('the day line and each channel: the count, the published titles, the work and its owner, the wait and whose it is', () => {
  const html = goalTallyHtml(GOAL, escapeHtml);
  assert.ok(html.includes('<p class="goal-line">Azi (2026-10-12): shorturi 1/2, episoade 0/2 publicate; 2 în lucru; 1 așteaptă decizia ta.</p>'));
  // the channel by its own name, with its count
  assert.ok(html.includes('<span class="goal-channel-name">AMN Facts</span><span class="goal-count">publicate 1/2</span>'));
  assert.ok(html.includes('«Why the Moon Rings»'));
  assert.ok(html.includes('href="https://youtube.com/shorts/abc" target="_blank" rel="noopener"'));
  // the work: the film, where it stands in the record's words, whose it is
  assert.ok(html.includes('<span class="goal-group-label">în lucru</span>'));
  assert.ok(html.includes('«The Zero Script Club»</span> <span class="goal-words">controlul calității a picat; Directoarea decide</span> <span class="goal-tag is-director">Directoarea</span>'));
  assert.ok(html.includes('title="din 2026-10-11 09:12"'));
  // the wait: his decision, in the warm tag
  assert.ok(html.includes('<span class="goal-group-label">blocat</span>'));
  assert.ok(html.includes('<span class="goal-tag is-owner">decizia ta</span>'));
  // the serial: no name in the record, so its type's word; the studio's work; the next episode
  assert.ok(html.includes('<span class="goal-channel-name">Serialul biroului</span><span class="goal-count">publicate 0/2</span>'));
  assert.ok(html.includes('<span class="goal-tag is-studio">studioul</span>'));
  assert.ok(html.includes('<span class="goal-group-label">episodul următor</span> <span class="goal-title">«Episodul 3: Tăcerea»</span> <span class="goal-words">aprobat, se pregătește de filmare</span>'));
  // everything from the record is escaped
  assert.ok(html.includes('«Salt &amp; &lt;Static&gt;»'));
  assert.ok(!html.includes('<Static>'));
});

test('a channel at its target is marked done; an empty channel says so; an address that is not a web link is not linked', () => {
  const goal = {
    ...GOAL,
    channels: [
      { channel_type: 'MAIN_FACTUAL', channel_name: 'AMN Facts', target: 2, published: [{ title: 'A', url: 'javascript:alert(1)' }, { title: 'B', url: null }], in_work: [], blocked: [] },
      { channel_type: 'OFFICE_SERIAL', channel_name: 'Serial', target: 2, published: [], in_work: [], blocked: [], next_episode: null },
    ],
  };
  const html = goalTallyHtml(goal, escapeHtml);
  assert.ok(html.includes('<span class="goal-count is-done">publicate 2/2</span>'));
  assert.ok(!html.includes('javascript:'));
  assert.ok(!html.includes('<a '));
  assert.ok(html.includes('<p class="goal-empty">Nimic publicat azi, nimic în lucru.</p>'));
});

test('an unreadable or missing goal draws nothing and hides the block; the same goal is not redrawn', () => {
  assert.equal(goalTallyHtml({}, escapeHtml), '');
  assert.equal(goalTallyHtml(null, escapeHtml), '');
  assert.equal(goalTallyHtml(undefined, escapeHtml), '');
  assert.equal(goalTallyHtml({ channels: [] }, escapeHtml), '');
  const host = { hidden: true, innerHTML: '', writes: 0 };
  Object.defineProperty(host, 'innerHTML', { set(value) { this.html = value; this.writes += 1; }, get() { return this.html; } });
  renderGoalTally(host, GOAL, escapeHtml);
  assert.equal(host.hidden, false);
  assert.equal(host.writes, 1);
  renderGoalTally(host, JSON.parse(JSON.stringify(GOAL)), escapeHtml);
  assert.equal(host.writes, 1, 'the same goal again is not written again');
  renderGoalTally(host, {}, escapeHtml);
  assert.equal(host.hidden, true);
  assert.equal(host.html, '');
});
