// PAGE_OWNER_DAY (PAGE-05): an empty «Limită» once retired the daily budget with one Enter, and
// with no daily budget nothing in the budget stops a film of the day. The limit is now a positive
// sum or nothing is sent; retiring is its own key, asked first, and every command carries its id
// and the version the page read.
import test from 'node:test';
import assert from 'node:assert/strict';
import { LIMIT_PATTERN, RETIRE_QUESTION, budgetCommand, budgetVersion, retireCommand } from '../src/budget_form.js';

const STATUS = { versions: { DAILY: 3, MONTHLY: 0 }, budgets: [] };

test('an empty, zero or unreadable limit is refused before anything is sent', () => {
  for (const limit of ['', '   ', '0', '0,00', '0.0', '-5', 'cinci', '1e3']) {
    const built = budgetCommand({ period: 'DAILY', limit, status: STATUS, commandId: 'c' });
    assert.ok('error' in built, limit);
    assert.match(String(/** @type {any} */ (built).error), /retrage|sumă/i, limit);
  }
});

test('a limit is sent as a decimal with its period, id and the version the page read', () => {
  assert.deepEqual(budgetCommand({ period: 'DAILY', limit: '15', status: STATUS, commandId: 'c-1' }), {
    command: { period: 'DAILY', limit_usd: '15', command_id: 'c-1', expected_version: 3 },
  });
  assert.equal(/** @type {any} */ (budgetCommand({ period: 'DAILY', limit: '12,50', status: STATUS, commandId: 'c' })).command.limit_usd, '12.50');
  assert.equal(/** @type {any} */ (budgetCommand({ period: 'MONTHLY', limit: '300', status: STATUS, commandId: 'c' })).command.expected_version, 0);
  // a budget the page has not read is not changed blindly
  assert.ok('error' in budgetCommand({ period: 'DAILY', limit: '15', status: null, commandId: 'c' }));
  assert.ok('error' in budgetCommand({ period: 'WEEKLY', limit: '15', status: STATUS, commandId: 'c' }));
});

test('retiring is its own command, asked first in his words', () => {
  assert.equal(RETIRE_QUESTION, 'Fără buget zilnic, nimic din buget nu oprește un film al zilei. Retragi?');
  assert.deepEqual(retireCommand({ period: 'DAILY', status: STATUS, commandId: 'r-1' }), {
    command: { period: 'DAILY', retire: true, command_id: 'r-1', expected_version: 3 },
  });
  assert.ok('error' in retireCommand({ period: 'DAILY', status: null, commandId: 'r' }));
});

test('the version is read per period, 0 for one never set', () => {
  assert.equal(budgetVersion(STATUS, 'DAILY'), 3);
  assert.equal(budgetVersion({ versions: {} }, 'MONTHLY'), 0);
  assert.equal(budgetVersion(null, 'DAILY'), null);
  assert.equal(budgetVersion({ budgets: [] }, 'DAILY'), null, 'an older studio sends no versions');
});

test('the field itself refuses an empty or zero sum', async () => {
  const fs = await import('node:fs');
  const html = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
  const field = html.slice(html.indexOf('id="budget-limit"') - 10, html.indexOf('id="budget-limit"') + 400);
  assert.match(field, /\brequired\b/);
  assert.ok(field.includes(`pattern="${LIMIT_PATTERN}"`), 'the same pattern as the module');
  assert.ok(!html.includes('0 = fără buget'), 'zero is no longer the way to retire');
  assert.ok(html.includes('id="budget-retire"'), 'a separate key retires the daily budget');
  const re = new RegExp(`^(?:${LIMIT_PATTERN})$`);
  for (const ok of ['15', '12,50', '0.5', '1000']) assert.ok(re.test(ok), ok);
  for (const no of ['', '0', '00', '0,00', '-1', 'abc']) assert.ok(!re.test(no), no);
});
