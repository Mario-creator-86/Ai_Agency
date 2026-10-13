import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  MOMENT_FRESH_MS,
  MOMENT_QUEUE,
  MOMENT_TIMING,
  MomentQueue,
  chapterWords,
  filmSeconds,
  momentFor,
} from '../src/moments.js';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const now = Date.parse('2026-09-24T10:00:00+00:00');
const fresh = new Date(now - 5000).toISOString();

// The payloads exactly as the backend appends them (story/services.py, story/review.py,
// media/assembler.py, publishing/services.py, services.py).
const drafted = { event_id: 'e1', event_type: 'story.episode_drafted', aggregate_id: 'ep-1', timestamp: fresh, payload: { log_id: 'l', grounded_events: 12, episode_number: 3, rewrite_of: null } };
const approved = { event_id: 'e2', event_type: 'story.episode_approved', aggregate_id: 'ep-1', timestamp: fresh, payload: { log_id: 'l', reviewed_by: 'owner' } };
const rendered = { event_id: 'e3', event_type: 'media.video_rendered', aggregate_id: 'asset-1', timestamp: fresh, payload: { storyboard_id: 'sb-1', render_engine: 'FFMPEG', duration_seconds: 45.28 } };
const published = { event_id: 'e4', event_type: 'publishing.video_published', aggregate_id: 'pub-1', timestamp: fresh, payload: { title: 'How ATLAS Caught the Higgs Boson', privacy_status: 'private', simulated: false } };
const asked = { event_id: 'e5', event_type: 'governance.approval_requested', aggregate_id: 'req-1', timestamp: fresh, payload: { action: 'x' } };

test('only an event the socket delivered as it happened makes a moment', () => {
  for (const event of [drafted, approved, rendered, published, asked]) {
    assert.equal(momentFor(event, { live: false, now }), null, `${event.event_type} on replay`);
    assert.notEqual(momentFor(event, { live: true, now }), null, `${event.event_type} live`);
  }
});

test('the replay that fills the page when it opens plays nothing', () => {
  // The day the shooter replays (a copy of the Owner's events) contains no milestone; the
  // real risk is a replay of one, so every event of that file is offered as a replay and as
  // stale-but-live, and neither plays.
  const events = JSON.parse(fs.readFileSync(path.join(HERE, 'fixtures', 'milestone_events.json'), 'utf8'));
  for (const event of events) {
    assert.equal(momentFor(event, { live: false, now: Date.parse(event.timestamp) }), null);
    assert.equal(momentFor(event, { live: true, now: Date.parse(event.timestamp) + MOMENT_FRESH_MS + 1 }), null);
  }
});

test('old news delivered live (an outbox flushing a backlog) is not a moment, and nothing plays twice', () => {
  const old = { ...rendered, event_id: 'old', timestamp: new Date(now - MOMENT_FRESH_MS - 1000).toISOString() };
  assert.equal(momentFor(old, { live: true, now }), null);
  const seen = new Set(['e3']);
  assert.equal(momentFor(rendered, { live: true, now, seen }), null);
  assert.equal(momentFor({ ...rendered, event_id: '' }, { live: true, now }), null);
  assert.equal(momentFor({ ...rendered, event_type: 'publishing.video_published_simulated' }, { live: true, now }), null);
  assert.equal(momentFor({ ...rendered, event_type: 'agent.message_posted' }, { live: true, now }), null);
});

test('each milestone makes its own kind, with the fields its event carries', () => {
  assert.deepEqual(momentFor(drafted, { live: true, now }), {
    kind: 'chapter', id: 'e1', episodeId: 'ep-1', episodeNumber: 3, approved: false, line: 'Episod scris · așteaptă decizia',
  });
  assert.equal(momentFor(approved, { live: true, now }).line, 'Episod aprobat de Proprietar');
  assert.equal(momentFor({ ...approved, payload: { reviewed_by: 'director' } }, { live: true, now }).line, 'Episod aprobat de Directoare');
  assert.deepEqual(momentFor(rendered, { live: true, now }), {
    kind: 'film', id: 'e3', assetId: 'asset-1', storyboardId: 'sb-1', seconds: 45.28, eyebrow: 'FILM RANDAT',
  });
  const pub = momentFor(published, { live: true, now });
  assert.equal(pub.kind, 'published');
  assert.equal(pub.title, 'How ATLAS Caught the Higgs Boson');
  assert.equal(pub.line, 'pe YouTube · privat');
  assert.equal(momentFor(asked, { live: true, now }).kind, 'approval');
});

test('the chapter card says the series, the number and the title it was given, and guesses none', () => {
  const moment = momentFor(drafted, { live: true, now });
  const words = chapterWords(moment, { series: 'Inside The Nexus', episode: { title: 'Day Three - The Queue' } });
  assert.equal(words.eyebrow, 'Inside The Nexus · Ep 3');
  assert.equal(words.title, 'Day Three - The Queue');
  assert.equal(words.label, 'Inside The Nexus · episodul 3 · Day Three - The Queue · Episod scris · așteaptă decizia');
  // approved: the number comes from the draft's event when the page still holds it, else none
  const approval = momentFor(approved, { live: true, now });
  assert.equal(chapterWords(approval, { series: 'Inside The Nexus', episode: null }).eyebrow, 'Inside The Nexus');
  assert.equal(chapterWords(approval, { series: 'Inside The Nexus', number: 3, episode: { title: 'T' } }).eyebrow, 'Inside The Nexus · Ep 3');
  assert.equal(chapterWords(approval, {}).eyebrow, 'Office Serial');
  assert.equal(filmSeconds(45.28), '45 s');
  assert.equal(filmSeconds(NaN), '');
});

test('one moment at a time, the oldest waiting dropped, each id accepted once', () => {
  const q = new MomentQueue();
  const m = (id) => ({ kind: 'film', id });
  assert.equal(q.push(m('a')), true);
  assert.equal(q.push(m('a')), false);
  assert.equal(q.next().id, 'a');
  assert.equal(q.next(), null, 'nothing else while one is up');
  for (const id of ['b', 'c', 'd', 'e']) q.push(m(id));
  assert.equal(q.waiting.length, MOMENT_QUEUE);
  q.done();
  assert.equal(q.next().id, 'c', 'b was dropped, the oldest waiting');
  q.clear();
  assert.equal(q.next(), null);
});

test('every moment lasts one to three seconds, and its motion stays inside the page\'s 120-400ms', () => {
  for (const kind of ['chapter', 'toast', 'mark']) {
    assert.ok(MOMENT_TIMING[kind] >= 1000 && MOMENT_TIMING[kind] <= 3000, kind);
  }
  for (const part of ['in', 'out']) {
    assert.ok(MOMENT_TIMING[part] >= 120 && MOMENT_TIMING[part] <= 400, part);
  }
  // the stylesheet states the same numbers as tokens
  const css = fs.readFileSync(path.join(HERE, '..', 'src', 'style.css'), 'utf8');
  const token = (name) => Number((css.match(new RegExp(`--${name}:\\s*(\\d+)ms`)) || [])[1]);
  assert.equal(token('moment-in'), MOMENT_TIMING.in);
  assert.equal(token('moment-out'), MOMENT_TIMING.out);
  assert.equal(token('moment-mark'), MOMENT_TIMING.mark);
  // and under reduced motion no moment travels or glows
  const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'));
  assert.match(reduced, /\.moment-chapter[^{]*\{[^}]*transform: none/);
  assert.match(reduced, /\.owner-mark\.is-arriving[^{]*\{[^}]*animation: none/);
});
