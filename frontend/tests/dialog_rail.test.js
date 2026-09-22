import assert from 'node:assert/strict';
import test from 'node:test';

import { currentSectionId } from '../src/dialog_rail.js';

const SECTIONS = [
  { id: 'rb-company', top: 0 },
  { id: 'rb-preflight', top: 900 },
  { id: 'rb-schedule', top: 1600 },
  { id: 'rb-runs', top: 1750 },
];

test('with no sections the rail marks nothing', () => {
  assert.equal(currentSectionId([], 0, 600, 600), null);
});

test('at the top the first section is the one being read', () => {
  assert.equal(currentSectionId(SECTIONS, 0, 600, 3000), 'rb-company');
});

test('a section becomes current once its heading crosses the reading line', () => {
  // reading line = scrollTop + a quarter of the body: 760 + 150 = 910, past 900.
  assert.equal(currentSectionId(SECTIONS, 740, 600, 3000), 'rb-company');
  assert.equal(currentSectionId(SECTIONS, 760, 600, 3000), 'rb-preflight');
});

test('the last section is marked at the end however short it is', () => {
  // rb-runs starts 1750 into a 2400px body: it can never reach the reading line on its
  // own, because the body cannot scroll past 1800.
  assert.equal(currentSectionId(SECTIONS, 1800, 600, 2400), 'rb-runs');
});

test('one pixel short of the end the rule is still the reading line', () => {
  assert.equal(currentSectionId(SECTIONS, 1500, 600, 2400), 'rb-schedule');
});

test('a body that has not been shown yet marks the first section, not the last', () => {
  // A closed dialog measures zero in every direction; before this guard the "scrolled to
  // the end" rule fired on 0 >= -2 and the rail opened with its last link marked.
  assert.equal(currentSectionId(SECTIONS, 0, 0, 0), 'rb-company');
});

test('a report short enough to fit shows every section, so the first is current', () => {
  assert.equal(currentSectionId(SECTIONS, 0, 900, 900), 'rb-company');
});

test('the order of the list does not decide the answer', () => {
  const shuffled = [SECTIONS[2], SECTIONS[0], SECTIONS[3], SECTIONS[1]];
  assert.equal(currentSectionId(shuffled, 760, 600, 3000), 'rb-preflight');
});
