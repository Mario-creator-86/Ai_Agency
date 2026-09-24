import test from 'node:test';
import assert from 'node:assert/strict';
import { amount } from '../src/numbers.js';

test('money reads the Romanian way, with every digit the ledger holds', () => {
  const grouped = new Intl.NumberFormat('ro-RO').format(50000);
  assert.equal(amount('50000'), grouped);
  assert.equal(amount('1234567.5'), `${new Intl.NumberFormat('ro-RO').format(1234567)},5`);
  assert.equal(amount('0.316'), '0,316');
  assert.equal(amount('0.316000'), '0,316000', 'no digit is dropped or rounded');
  assert.equal(amount(15), '15');
  assert.equal(amount('-0.5'), '−0,5', 'a negative sum keeps its sign, even under one');
  assert.equal(amount('12345678901234567890.01'), `${new Intl.NumberFormat('ro-RO').format(12345678901234567890n)},01`, 'no float in the way');
  assert.equal(amount('n/a'), 'n/a', 'anything that is not a plain number is left as written');
  assert.equal(amount(null), '');
});
