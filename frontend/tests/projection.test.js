import test from 'node:test';
import assert from 'node:assert/strict';
import { acceptSnapshot } from '../src/projection.js';

test('late response cannot rewind the displayed policy', () => {
  const current = { schema_version: 1, cursor: 20, policy: { autonomy_stopped: true } };
  const stale = { schema_version: 1, cursor: 19, policy: { autonomy_stopped: false } };
  assert.equal(acceptSnapshot(current, stale), current);
});
test('initial, repeated and newer snapshots remain authoritative', () => {
  const first = { schema_version: 1, cursor: 2 };
  assert.equal(acceptSnapshot(null, first), first);
  assert.deepEqual(acceptSnapshot(first, { ...first }), first);
  const next = { schema_version: 1, cursor: 3 };
  assert.equal(acceptSnapshot(first, next), next);
});
test('unknown schema and malformed cursor fail rather than imply live state', () => {
  assert.throws(() => acceptSnapshot(null, { schema_version: 2, cursor: 1 }));
  assert.throws(() => acceptSnapshot(null, { schema_version: 1, cursor: '1' }));
});

