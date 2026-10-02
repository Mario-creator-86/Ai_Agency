// W27, the release judge: the Distribution door listed the five gates a publication must pass,
// each with a green ✓ written into the page. Nothing had been checked: the list said which gates
// the studio enforces, not a result, and a stranger reads a green tick as «passed». The Owner's
// first rule: a mark that looks like a state must come from a real state.
//
// PAGE_SETTINGS_ERRORS (PAGE-10, 2026-10-02): the static list (and its «PARȚIAL» note, which had
// gone stale) is gone. The card now shows the backend's own evaluation of the film the quick
// publish would send (GET /publishing/gate/evaluate/{asset}/{channel}), so every «Trecut» or
// «Oprit» beside a gate is a state the studio measured.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { gateChecksHtml } from '../src/owner_controls.js';

const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');

test('the page writes no gate result of its own', () => {
  assert.ok(!/<ul class="pub-gate-list">/.test(HTML), 'no static list of gates in the page');
  assert.ok(/id="pub-gate-checks"/.test(HTML), 'the card is filled from the backend');
  assert.ok(!/✓|✔|gate-icon/.test(HTML.match(/id="pub-gate-checks"[\s\S]*?<\/div>/)[0]));
});

test('each mark is the backend\'s passed flag, in words, never a tick', () => {
  const html = gateChecksHtml({ eligible: false, checks: [{ check_name: 'a', passed: true, detail: 'x' }, { check_name: 'b', passed: false, detail: 'y' }] });
  assert.equal((html.match(/<li /g) || []).length, 2);
  assert.match(html, /Trecut:/);
  assert.match(html, /Oprit:/);
  assert.ok(!/✓|✔/.test(html));
});
