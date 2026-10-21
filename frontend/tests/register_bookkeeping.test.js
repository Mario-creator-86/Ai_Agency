// THE STUDIO'S OWN BOOKKEEPING STAYS OFF THE REGISTER (2026-10-17).
//
// The Owner's register at 00:50:56 (Bucharest) showed two rows for one act: «Studioul a închis
// fără răspuns o cerere — Blocaje foaie: Storyboard: The Zero Script Club» and, right above it,
// «Angajați: ask expired.», the raw event name. The sweep of stale asks (backend
// agents/inbox.py expire_stale_asks) writes `agent.message_answered` (expired) and
// `agent.ask_expired` for every ask it closes, always together: 120 pairs on the live record
// since the restart. His rules: the register speaks in sentences, never code, and the studio's
// own bookkeeping stays recorded but does not crowd his register (2026-10-16, the YouTube
// checks: «Vreau să rămână verificarea dar să nu apară aici»).
//
// The events below are the live record's own (sequence, ids, payloads), read 2026-10-17.
import test from 'node:test';
import assert from 'node:assert/strict';
import { Ledger, describeEvent, isBookkeeping } from '../src/ledger.js';
import { interruptsReplay } from '../src/day_replay.js';
import { escapeHtml } from '../src/html.js';

/** The pair at 00:50:56: the answer event the sweep writes, then its closing. */
const ANSWERED = {
  sequence: 34263,
  event_id: '9fc70007-a72c-422e-98ee-c404cea60834',
  event_type: 'agent.message_answered',
  timestamp: '2026-10-16T21:50:56.589486+00:00',
  aggregate_type: 'agent_message',
  aggregate_id: '8a027350-055b-4901-8c56-1976de291781',
  aggregate_version: 2,
  correlation_id: 'b11384b7-e41e-431d-9927-9ff6645fc378',
  payload: { intent: 'REQUEST_REVIEW', subject: 'Blocaje foaie: Storyboard: The Zero Script Club', resolved_by: 'Studioul (cereri expirate)', expired: true },
};
const CLOSED = {
  sequence: 34264,
  event_id: '0fdec58f-74bf-409b-a46e-d9c2ecb29a63',
  event_type: 'agent.ask_expired',
  timestamp: '2026-10-16T21:50:56.590539+00:00',
  aggregate_type: 'agent_message',
  aggregate_id: '8a027350-055b-4901-8c56-1976de291781',
  aggregate_version: 2,
  correlation_id: 'b11384b7-e41e-431d-9927-9ff6645fc378',
  payload: {
    reason: 'DUPLICATE',
    resolution: 'Închisă de studio: aceeași cerere a venit din nou la 2026-10-16 21:23 (UTC); rămâne deschisă numai cea mai nouă.',
    kept_message_id: 'b5c90e85-db94-4106-941f-1a89ae51ebab',
  },
};
/** The same pair as the page reads it after the restart: with the backend's words (events_feed). */
const ANSWERED_SAID = {
  ...ANSWERED,
  words_ro: 'Studioul a închis o copie veche a cererii «Blocaje foaie: The Zero Script Club» către Sarah (Director); cea mai nouă rămâne deschisă.',
};
const CLOSED_SAID = {
  ...CLOSED,
  words_ro: 'Cererea «Blocaje foaie: The Zero Script Club» către Sarah (Director) a venit din nou; studioul a închis copia veche, rămâne deschisă cea mai nouă.',
};
/** An answer recorded before the event carried `expired` (it says so only by its closer). */
const ANSWERED_OLD = { ...ANSWERED, event_id: 'old-answer', payload: { intent: 'REQUEST_REVIEW', subject: 'Blocaje foaie: Storyboard: The Zero Script Club', resolved_by: 'Studioul (cereri expirate)' } };
/** A real answer from the live record (sequence 33594): an employee's act. */
const REAL_ANSWER = {
  sequence: 33594,
  event_id: 'f01fed8d-8ea6-4d50-981c-8d2a81651f71',
  event_type: 'agent.message_answered',
  timestamp: '2026-10-16T14:02:58.035203+00:00',
  aggregate_type: 'agent_message',
  aggregate_id: 'ffbd83b2-5137-4296-9476-2138aee84953',
  aggregate_version: 2,
  correlation_id: '99ef5f60-7b3b-4755-a216-c78a3f3b3931',
  payload: { intent: 'REQUEST_INFO', subject: 'De investigat: Preluarea performanței: încheiată — 7 publicări măsurate pe 2 canale.', resolved_by: 'Dr. Aris (Researcher)' },
};
/** The other closings' payloads as the live record has them, one per reason seen there. */
const CLOSINGS = [
  { reason: 'FILM_CLOSED', resolution: "Închisă de studio: filmul «Storyboard: The Universe's Missing Pieces: Why the LHC Upgrade Matters» este încheiat (publicat sau închis); cererea nu mai are obiect.", storyboard_id: 'dbb3fd3a-ff26-41c0-9a46-251b146dd1af' },
  { reason: 'EPISODE_CLOSED', resolution: 'Închisă de studio: episodul «The Week of Two Videos» a fost înlocuit de o rescriere; cererea nu mai are obiect.', episode_id: '307d29db-ed3e-4456-92f3-8b6f0d2593de' },
  { reason: 'EXPIRED', resolution: 'Închisă de studio: cererea a stat deschisă mai mult de 3 zile fără să țină de un film în lucru; dacă mai contează, se trimite din nou.', days: 3 },
  CLOSED.payload,
];

/** The smallest document Ledger.render() uses (as ledger_fold.test.js). */
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

function ledgerOn(parts, timezone = 'UTC') {
  const ledger = new Ledger({ ...parts, escape: escapeHtml });
  ledger.timezone = timezone;
  return ledger;
}

// the day's heading and the empty filter's line are not rows
const rowsOf = (html) => html.split('<li ').slice(1).filter((row) => !row.startsWith('class="ledger-day"') && !row.startsWith('class="ledger-empty"'));
const daysOf = (html) => [...html.matchAll(/<li class="ledger-day">([^<]*)<\/li>/g)].map((m) => m[1]);
const countsIn = (html) => [...html.matchAll(/×(\d+)<\/span>/g)].map((m) => Number(m[1]));

const watchdog = (sequence, iso) => ({
  event_id: `w-${sequence}`,
  sequence,
  timestamp: iso,
  event_type: 'workflow.created',
  aggregate_id: `run-${sequence}`,
  payload: { workflow_type: 'WATCHDOG' },
});
const at = (event, sequence, iso) => ({ ...event, event_id: `${event.event_id}-${sequence}`, sequence, timestamp: iso });

test('the sweep\'s two events are bookkeeping; a real answer is an act', () => {
  for (const event of [ANSWERED, CLOSED, ANSWERED_SAID, CLOSED_SAID, ANSWERED_OLD]) {
    assert.equal(isBookkeeping(event), true, event.event_type);
    assert.equal(describeEvent(event, {}).bookkeeping, true, event.event_type);
  }
  for (const payload of CLOSINGS) assert.equal(describeEvent({ ...CLOSED, payload }, {}).bookkeeping, true, payload.reason);
  assert.equal(isBookkeeping(REAL_ANSWER), false);
  assert.equal(isBookkeeping({ ...REAL_ANSWER, payload: { ...REAL_ANSWER.payload, expired: false } }), false);
  assert.equal(isBookkeeping({ event_type: 'agent.message_posted', payload: { expired: true } }), false);
  assert.equal(isBookkeeping(null), false);
  const real = describeEvent(REAL_ANSWER, {});
  assert.equal(real.bookkeeping, undefined, 'an act carries no flag');
  assert.equal(real.label, 'a răspuns la un mesaj');
  assert.equal(real.text, REAL_ANSWER.payload.subject);
});

test('a closing is never said by its event name, with or without the backend\'s words', () => {
  for (const payload of CLOSINGS) {
    const bare = describeEvent({ ...CLOSED, payload }, {});
    const said = `${bare.who} ${bare.label} ${bare.text}`;
    assert.doesNotMatch(said, /ask expired|ask_expired|reason:|resolution:|kept_message_id|storyboard_id/, said);
    assert.equal(bare.who, 'Studioul');
    assert.equal(bare.label, 'a închis o cerere');
  }
  const said = describeEvent(CLOSED_SAID, {});
  assert.equal(`${said.who} ${said.text}`, `Studioul ${CLOSED_SAID.words_ro}`);
  assert.doesNotMatch(said.text, /ask expired/);
});

test('the 00:50:56 pair draws no row, and the real answer beside it keeps its own', () => {
  for (const pair of [[ANSWERED, CLOSED], [ANSWERED_SAID, CLOSED_SAID]]) {
    const parts = stubDocument();
    const ledger = ledgerOn(parts, 'Europe/Bucharest');
    ledger.add([REAL_ANSWER, ...pair]);
    const html = parts.list.innerHTML;
    const rows = rowsOf(html);
    assert.equal(rows.length, 1, html);
    assert.match(rows[0], /a răspuns la un mesaj/);
    assert.match(rows[0], /<time>17:02:58<\/time>/, 'the newest row is the newest act, not the bookkeeping');
    assert.doesNotMatch(html, /ask expired|fără răspuns|copie veche|Zero Script Club/, html);
    assert.equal(ledger.events.size, 3, 'the record keeps all three events');
  }
});

test('no filter shows the bookkeeping: «Discuții» still holds only the real answer', () => {
  const parts = stubDocument();
  const ledger = ledgerOn(parts);
  ledger.add([REAL_ANSWER, ANSWERED, CLOSED]);
  for (const kind of ['speech', 'work', 'all']) {
    ledger.kind = kind;
    ledger.render();
    const rows = rowsOf(parts.list.innerHTML);
    assert.equal(rows.length, kind === 'work' ? 0 : 1, `${kind}: ${parts.list.innerHTML}`);
    assert.doesNotMatch(parts.list.innerHTML, /ask expired|fără răspuns/);
  }
});

test('a skipped pair is not an act: the routine on either side stays one row (W34)', () => {
  const parts = stubDocument();
  const ledger = ledgerOn(parts);
  // 09:50 and 10:10, two hours of the clock, with only the sweep between them: one stretch
  ledger.add([
    watchdog(1, '2026-10-16T09:50:00.000+00:00'),
    at(ANSWERED, 2, '2026-10-16T10:05:00.000+00:00'),
    at(CLOSED, 3, '2026-10-16T10:05:00.001+00:00'),
    watchdog(4, '2026-10-16T10:10:00.000+00:00'),
  ]);
  let html = parts.list.innerHTML;
  assert.equal(rowsOf(html).length, 1, html);
  assert.deepEqual(countsIn(html), [2]);
  assert.match(html, /09:50:00 – 10:10:00/);

  // the same stretch with a real answer between: an act, so each hour keeps its routine row
  const acted = stubDocument();
  const other = ledgerOn(acted);
  other.add([
    watchdog(1, '2026-10-16T09:50:00.000+00:00'),
    at(REAL_ANSWER, 2, '2026-10-16T10:05:00.000+00:00'),
    watchdog(4, '2026-10-16T10:10:00.000+00:00'),
  ]);
  html = acted.list.innerHTML;
  assert.equal(rowsOf(html).length, 3, html);
});

test('a skipped pair never breaks a fold: the same words on either side are one row', () => {
  const parts = stubDocument();
  const ledger = ledgerOn(parts);
  const quiet = (sequence, iso) => ({ event_id: `t-${sequence}`, sequence, timestamp: iso, event_type: 'trends.unavailable', payload: { reason: 'Google Trends nu răspunde.' } });
  ledger.add([
    quiet(1, '2026-10-16T10:00:00.000+00:00'),
    at(ANSWERED, 2, '2026-10-16T10:01:00.000+00:00'),
    at(CLOSED, 3, '2026-10-16T10:01:00.001+00:00'),
    quiet(4, '2026-10-16T10:02:00.000+00:00'),
  ]);
  const html = parts.list.innerHTML;
  assert.equal(rowsOf(html).length, 1, html);
  assert.deepEqual(countsIn(html), [2]);
  assert.match(html, /10:00:00 – 10:02:00/);
});

test('a pair alone on a day opens no heading for that day', () => {
  const parts = stubDocument();
  const ledger = ledgerOn(parts, 'Europe/Bucharest');
  // the pair falls on the 17th in Bucharest (00:50:56); the real answer on the 16th
  ledger.add([REAL_ANSWER, ANSWERED, CLOSED]);
  assert.equal(daysOf(parts.list.innerHTML).length, 1, parts.list.innerHTML);
});

test('a bookkeeping arrival is not news: the register stands still and lights nothing', () => {
  const parts = stubDocument();
  const ledger = ledgerOn(parts);
  ledger.openedAt = Date.now() - 10_000;
  ledger.add([REAL_ANSWER]);
  assert.match(parts.list.innerHTML, /is-new/, 'a real arrival is lit');
  ledger.render();
  // what is on screen now; a redraw would write the list again
  parts.list.innerHTML = 'UNCHANGED';
  assert.equal(ledger.add([ANSWERED_SAID, CLOSED_SAID]), true, 'the events are taken into the record');
  assert.equal(parts.list.innerHTML, 'UNCHANGED', 'nothing is drawn again for the bookkeeping');
  assert.equal(ledger.arrived.size, 0);
  // and the next real arrival is drawn and lit as before
  const later = { ...REAL_ANSWER, event_id: 'later', sequence: 34270, timestamp: '2026-10-16T22:02:44.000+00:00' };
  ledger.add([{ ...later, payload: { ...later.payload, subject: 'Ce cârlig merge' } }]);
  assert.match(parts.list.innerHTML, /is-new/);
  assert.equal(rowsOf(parts.list.innerHTML).length, 2);
});

test('the sweep neither interrupts the replay nor speaks in its live prompt', async () => {
  for (const event of [ANSWERED, CLOSED, ANSWERED_SAID, CLOSED_SAID, ANSWERED_OLD]) {
    assert.equal(interruptsReplay(event), false, event.event_type);
  }
  assert.equal(interruptsReplay(REAL_ANSWER), true, 'a real answer is still live news');

  const { DayReplayPlayer } = await import('../src/replay_player.js');
  globalThis.window = { setInterval: () => 1, setTimeout: () => 2, clearInterval() {}, clearTimeout() {} };
  const player = Object.create(DayReplayPlayer.prototype);
  player.active = true;
  player.liveEvents = [];
  player.deps = { names: () => ({}) };
  player.el = { live: { hidden: true }, liveWhat: { textContent: '' }, liveCount: { textContent: '' } };
  player.liveArrived(ANSWERED_SAID);
  player.liveArrived(CLOSED_SAID);
  assert.equal(player.el.live.hidden, true, 'no prompt for the bookkeeping');
  assert.equal(player.el.liveWhat.textContent, '');
  assert.equal(player.liveEvents.length, 0);
  player.liveArrived(REAL_ANSWER);
  assert.equal(player.el.live.hidden, false, 'a real answer still prompts');
  assert.match(player.el.liveWhat.textContent, /a răspuns la un mesaj/);
  assert.equal(player.liveEvents.length, 1);
});
