// W30, THE EMPLOYEES AS PEOPLE. The employees' door is a roster: a card per employee with a
// portrait cut from the scene's own figure at the desk, the name and role as the data gives them,
// the place in the building, the state now, the last real task and the measured runs; «—» where
// the page holds nothing. A card opens the inspector from the desk.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {
  NO_DESK, applyMeters, buildingOrder, personName, portraitWindow, rosterCards, rosterHtml, rosterKey, stillFrame,
} from '../src/roster.js';
import { tasksFromRecord } from '../src/hq_readouts.js';

const MANIFEST = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/manifest.json', import.meta.url), 'utf8'));
const ATLAS = JSON.parse(fs.readFileSync(new URL('../public/assets/hq/characters/characters.json', import.meta.url), 'utf8'));
const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const escape = (/** @type {unknown} */ s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] || c);

const NOW = Date.parse('2026-09-25T06:00:00Z');
const measurements = {
  window_days: 30,
  agents: [
    { agent_id: 'nadia', display_name: 'Nadia (Accountant)', role_name: 'Accountant', lifecycle: 'ACTIVE', runs: 0, failure_rate: 0 },
    { agent_id: 'sarah', display_name: 'Sarah (Director)', role_name: 'Director', lifecycle: 'ACTIVE', runs: 78, failure_rate: 0.026 },
    { agent_id: 'aris', display_name: 'Dr. Aris (Researcher)', role_name: 'LeadResearcher', lifecycle: 'ACTIVE', runs: 40, failure_rate: 0 },
    { agent_id: 'ghost', display_name: 'Ion', role_name: 'Intern', lifecycle: 'PAUSED', runs: 1, failure_rate: 1 },
  ],
};
const office = [
  { id: 'sarah', agent_id: 'sarah', desk_id: 'desk_director', display_name: 'Sarah (Director)', role_name: 'Director', runtime_state: 'IDLE', lifecycle: 'ACTIVE' },
  { id: 'aris', agent_id: 'aris', desk_id: 'desk_research_1', display_name: 'Dr. Aris (Researcher)', role_name: 'LeadResearcher', runtime_state: 'WORKING', lifecycle: 'ACTIVE' },
  { id: 'nadia', agent_id: 'nadia', desk_id: 'desk_accounting', display_name: 'Nadia (Accountant)', role_name: 'Accountant', runtime_state: 'IDLE', lifecycle: 'ACTIVE' },
];
const tasks = tasksFromRecord({
  sarah: { task_type: 'director_review', status: 'SUCCEEDED', started_at: '2026-09-18T21:03:47Z', finished_at: '2026-09-18T21:03:55Z' },
  aris: { task_type: 'answer_mail', status: 'FAILED', started_at: '2026-09-25T05:10:00Z', finished_at: '2026-09-25T05:12:00Z' },
}).tasks;

test('a name and its role are the data\'s own halves; no parenthesis leaves the role unknown', () => {
  assert.deepEqual(personName('Sarah (Director)'), { name: 'Sarah', role: 'Director' });
  assert.deepEqual(personName('Dr. Aris (Researcher)'), { name: 'Dr. Aris', role: 'Researcher' });
  assert.deepEqual(personName('Ion'), { name: 'Ion', role: '—' });
  assert.deepEqual(personName(''), { name: '—', role: '—' });
});

test('the roster stands as the building: top floor first, left to right, no desk last', () => {
  const seats = { a: { level: 1, x: 900 }, b: { level: 4, x: 800 }, c: { level: 1, x: 600 } };
  const order = buildingOrder(['a', 'none', 'b', 'c'], (p) => /** @type {any} */ (seats)[p] || null);
  assert.deepEqual(order, ['b', 'c', 'a', 'none']);
});

test('each card is the record: place, state now, last task, runs and failure share, «—» where nothing is held', () => {
  const cards = rosterCards({ measurements, office, tasks, manifest: MANIFEST, now: NOW });
  assert.deepEqual(cards.map((c) => c.id), ['sarah', 'aris', 'nadia', 'ghost']);
  const [sarah, aris, nadia, ghost] = cards;
  assert.equal(sarah.name, 'Sarah');
  assert.equal(sarah.role, 'Director');
  assert.equal(sarah.place, 'DIRECȚIUNE · L4');
  assert.equal(sarah.state, 'în așteptare');
  assert.equal(sarah.standing, 'activ');
  assert.equal(sarah.task, 'revizuirea Directorului');
  assert.equal(sarah.taskWhen, 'acum 6 zile');
  assert.equal(sarah.runs, '78 de rulări');
  assert.equal(sarah.failures, '3% eșecuri');
  assert.equal(aris.place, 'CERCETARE · L3');
  assert.equal(aris.state, 'în lucru');
  assert.equal(aris.taskFailed, true);
  assert.equal(aris.taskWhen, 'acum 48 de minute');
  assert.equal(aris.failures, '0% eșecuri');
  // no runs in the window: the share is unknown, not zero, and no meter is drawn
  assert.equal(nadia.runs, 'nicio rulare');
  assert.equal(nadia.failures, '—');
  assert.equal(nadia.failureShare, null);
  assert.equal(nadia.task, '—');
  // measured but not seated: a person all the same, with no place, no state and no portrait
  assert.equal(ghost.place, NO_DESK);
  assert.equal(ghost.hasDesk, false);
  assert.equal(ghost.state, '—');
  assert.equal(ghost.standing, 'în pauză');
  assert.equal(ghost.role, '—');
  assert.equal(ghost.runs, '1 rulare');
  assert.equal(ghost.failures, '100% eșecuri');
  assert.match(ghost.label, /deschide fișa$/);
  assert.match(sarah.label, /^Sarah \(Director\) — deschide fișa, de la birou$/);
});

test('a card the office seats but the measurement does not list says «—» for its runs', () => {
  const cards = rosterCards({ measurements: { agents: [] }, office, tasks: {}, manifest: MANIFEST, now: NOW });
  assert.equal(cards.length, 3);
  assert.ok(cards.every((c) => c.runs === '—' && c.failures === '—' && c.task === '—'));
});

test('the markup: one button per person, the role code only in a title, no inline style (the policy refuses it)', () => {
  const cards = rosterCards({ measurements, office, tasks, manifest: MANIFEST, now: NOW });
  const html = rosterHtml(cards, escape);
  assert.equal((html.match(/<button type="button" class="person-card"/g) || []).length, 4);
  assert.ok(!/style="/.test(html));
  assert.ok(html.includes('title="LeadResearcher"'));
  assert.ok(!/>LeadResearcher</.test(html));
  assert.ok(html.includes('Rulări · 30 de zile'));
  assert.ok(html.includes('data-fail="2.6"'));
  assert.ok(html.includes('person-portrait is-empty'));
  assert.equal(rosterHtml([], escape), '<div class="topics-loading">Niciun angajat înregistrat.</div>');
  // the key changes when a state changes, not otherwise
  const again = rosterCards({ measurements, office, tasks, manifest: MANIFEST, now: NOW });
  assert.equal(rosterKey(again), rosterKey(cards));
  const moved = rosterCards({ measurements, office: office.map((a) => (a.id === 'sarah' ? { ...a, runtime_state: 'WORKING' } : a)), tasks, manifest: MANIFEST, now: NOW });
  assert.notEqual(rosterKey(moved), rosterKey(cards));
});

test('the meters are set through the CSSOM, clamped', () => {
  const set = /** @type {Record<string, string>} */ ({});
  const bar = { dataset: { fail: '130' }, style: { setProperty: (/** @type {string} */ k, /** @type {string} */ v) => { set[k] = v; } } };
  applyMeters(/** @type {any} */ ({ querySelectorAll: () => [bar] }));
  assert.equal(set['--fail'], '100%');
});

test('the portrait is the scene\'s own figure in the pose of the state now, at the desk', () => {
  const sarah = ATLAS.characters.sarah;
  assert.equal(stillFrame({ runtime_state: 'IDLE', lifecycle: 'ACTIVE' }, sarah, 'front'), sarah.animations.sit_idle_front[0]);
  assert.equal(stillFrame({ runtime_state: 'WORKING', lifecycle: 'ACTIVE' }, sarah, 'front'), sarah.animations.sit_type_front[0]);
  assert.equal(stillFrame({ runtime_state: 'IDLE', lifecycle: 'PAUSED' }, sarah, 'front'), sarah.animations.sit_sleep_front[0]);
  assert.equal(stillFrame({ runtime_state: 'ERROR', lifecycle: 'ACTIVE' }, sarah, 'front'), sarah.animations.sit_error_front[0]);
  assert.equal(stillFrame({}, { animations: {} }, 'front'), -1);
  const seat = MANIFEST.seats.desk_director;
  const w = portraitWindow(seat);
  assert.ok(w);
  // the head and the monitors: the window starts above the figure's frame and is 4:3
  assert.ok(w[1] < seat.y - 40 && w[1] + w[3] < seat.y - 8);
  assert.ok(Math.abs(w[2] / w[3] - 4 / 3) < 0.01);
  assert.equal(portraitWindow(null), null);
});

test('a card opens the inspector from the desk, through its door; the roster is drawn by the renderer', () => {
  assert.match(MAIN, /function openPerson\(/);
  assert.match(MAIN, /drawPortrait\(/);
  assert.match(STYLE, /\.person-card/);
});
