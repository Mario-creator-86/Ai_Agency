/**
 * The fold, under oath.
 *
 * The ledger collapses consecutive entries that say exactly the same thing into one row
 * carrying ×N and the span the run covers. It is the one place where the interface changes
 * WHAT is on screen rather than how it looks, and the specification's own risk list asks for
 * a test that it is lossless and that correspondence never folds. Until now the fold had
 * none, because it lives inside Ledger.render(), which needs a document.
 *
 * So this test gives it the smallest document that will do: createElement, append,
 * replaceChildren, addEventListener and innerHTML — nothing else is touched by the ledger.
 * Then it reads the HTML the real render() writes.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { Ledger } from '../src/ledger.js';
import { escapeHtml } from '../src/html.js';

/** The smallest document Ledger.render() and Ledger.renderFilters() actually use. */
function stubDocument() {
  const make = () => ({
    className: '',
    textContent: '',
    type: '',
    innerHTML: '',
    children: [],
    addEventListener() {},
    append(...kids) { this.children.push(...kids); },
    replaceChildren(...kids) { this.children = [...kids]; },
  });
  globalThis.document = { createElement: () => make() };
  return { list: make(), now: make(), filters: make() };
}

/** A ledger that reads its clock in one place, so a time in a test is the time on screen. */
function ledgerOn(parts) {
  const ledger = new Ledger({ ...parts, escape: escapeHtml });
  ledger.timezone = 'UTC';
  return ledger;
}

const watchdog = (sequence, hhmmss) => ({
  event_id: `w-${sequence}`,
  sequence,
  timestamp: `2026-09-12T${hhmmss}.000+00:00`,
  event_type: 'workflow.created',
  aggregate_id: `run-${sequence}`,
  payload: { workflow_type: 'WATCHDOG' },
});

const letter = (sequence, hhmmss, threadId) => ({
  event_id: `m-${sequence}`,
  sequence,
  timestamp: `2026-09-12T${hhmmss}.000+00:00`,
  event_type: 'agent.message_posted',
  aggregate_id: threadId,
  payload: { intent: 'REPORT', subject: 'Raport zilnic', from_name: 'Vera (Publisher)', to_name: 'Director' },
});

const rowsOf = (html) => html.split('<li ').slice(1);
const countsIn = (html) => [...html.matchAll(/×(\d+)/g)].map((m) => Number(m[1]));

test('seventeen identical runs fold into one row that carries the true count and the true span', () => {
  const parts = stubDocument();
  const ledger = ledgerOn(parts);
  // Recorded 13:54:10 first, 16:34:15 last — the exact run the specification cites.
  const times = ['13:54:10', '14:04:15', '14:14:15', '14:24:15', '14:34:15', '14:44:15', '14:54:15',
    '15:04:15', '15:14:15', '15:24:15', '15:34:15', '15:44:15', '15:54:15', '16:04:15', '16:14:15',
    '16:24:15', '16:34:15'];
  ledger.add(times.map((t, i) => watchdog(i + 1, t)));

  const html = parts.list.innerHTML;
  assert.equal(rowsOf(html).length, 1, 'seventeen identical runs draw one row');
  assert.deepEqual(countsIn(html), [17], 'the pill says exactly how many were folded');
  assert.match(html, /<time>16:34:15<\/time>/, 'the row keeps the newest time');
  assert.match(html, /13:54:10 – 16:34:15/, 'the span runs from the oldest to the newest');
  assert.match(html, /routine job started/);
  assert.match(html, /watchdog/);
});

test('nothing is dropped: every event is either its own row or inside a count', () => {
  const parts = stubDocument();
  const ledger = ledgerOn(parts);
  const events = [
    watchdog(1, '10:00:00'), watchdog(2, '10:10:00'), watchdog(3, '10:20:00'),
    letter(4, '10:30:00', 'thread-a'),
    watchdog(5, '10:40:00'), watchdog(6, '10:50:00'),
    letter(7, '11:00:00', 'thread-b'),
  ];
  ledger.add(events);

  const html = parts.list.innerHTML;
  const rows = rowsOf(html);
  const folded = countsIn(html).reduce((a, b) => a + b, 0);
  const single = rows.length - countsIn(html).length;
  assert.equal(single + folded, events.length, 'the rows and the counts account for every event');
  // And the run that is interrupted by a letter is not welded across it.
  assert.deepEqual(countsIn(html).sort(), [2, 3], 'a run stops at the row that interrupts it');
});

test('correspondence never folds: two identical letters stay two letters', () => {
  const parts = stubDocument();
  const ledger = ledgerOn(parts);
  ledger.add([
    letter(1, '09:00:00', 'thread-a'),
    letter(2, '09:00:01', 'thread-a'),
    letter(3, '09:00:02', 'thread-a'),
  ]);

  const html = parts.list.innerHTML;
  assert.equal(rowsOf(html).length, 3, 'every letter keeps its own row');
  assert.equal(countsIn(html).length, 0, 'no letter is ever carried by a count');
  assert.equal([...html.matchAll(/Open the thread/g)].length, 3, 'every letter keeps its way into the thread');
});

test('a fold is a fold of the same words, never of two different ones', () => {
  const parts = stubDocument();
  const ledger = ledgerOn(parts);
  ledger.add([
    watchdog(1, '08:00:00'),
    { ...watchdog(2, '08:10:00'), payload: { workflow_type: 'MAINTENANCE' } },
    watchdog(3, '08:20:00'),
  ]);

  const html = parts.list.innerHTML;
  assert.equal(rowsOf(html).length, 3, 'three different sentences are three rows');
  assert.equal(countsIn(html).length, 0, 'nothing is folded that does not say the same thing');
});

/* The same stub closes a hole the finishing pass left open: arrivingIds() was proved pure,
   but the line in render() that turns a marked id into `is-new` on the right row was not,
   and neither was the clear that keeps the highlight from playing twice. */

test('a row recorded while he watches is the row that is lit, and it is lit once', () => {
  const parts = stubDocument();
  const ledger = ledgerOn(parts);
  // The column has been open long enough that what arrives now is news, not history.
  ledger.openedAt = Date.now() - 10_000;
  ledger.add([watchdog(1, '12:00:00')]);
  assert.match(parts.list.innerHTML, /ledger-item[^"]*is-new/, 'the new row is marked');

  // A later render — a filter change, the office layout arriving with its names — must not
  // replay the mark on a row that has already settled.
  ledger.render();
  assert.doesNotMatch(parts.list.innerHTML, /is-new/, 'the highlight plays once and only once');
});

test('the history that fills the column when the page opens is not lit', () => {
  const parts = stubDocument();
  const ledger = ledgerOn(parts);
  ledger.add([watchdog(1, '12:00:00'), letter(2, '12:01:00', 'thread-a')]);
  assert.doesNotMatch(parts.list.innerHTML, /is-new/, 'seventy rows of history are not news');
});

test('a filter hides rows, it does not fold them into somebody else\'s count', () => {
  const parts = stubDocument();
  const ledger = ledgerOn(parts);
  ledger.add([
    watchdog(1, '07:00:00'), watchdog(2, '07:10:00'),
    letter(3, '07:20:00', 'thread-a'),
    watchdog(4, '07:30:00'), watchdog(5, '07:40:00'),
  ]);
  // Talk: only the correspondence is shown.
  ledger.kind = 'speech';
  ledger.render();
  let html = parts.list.innerHTML;
  assert.equal(rowsOf(html).length, 1, 'only the letter is shown');
  assert.equal(countsIn(html).length, 0, 'and it carries no count');

  // Back to everything: the two runs are still two runs of two, not one of four.
  ledger.kind = 'all';
  ledger.render();
  html = parts.list.innerHTML;
  assert.deepEqual(countsIn(html), [2, 2], 'the filter left the fold exactly as it found it');
  assert.equal(rowsOf(html).length, 3, 'two folded runs and the letter between them');
});
