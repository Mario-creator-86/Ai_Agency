import test from 'node:test';
import assert from 'node:assert/strict';
import { SheetReader } from '../src/sheet_reader.js';

test('repeated presses share a read and retain real snapshots for immediate reopening', async () => {
  let finish;
  let calls = 0;
  const reader = new SheetReader(() => { calls++; return new Promise(resolve => { finish = resolve; }); }, 2);
  const one = reader.load('a');
  const two = reader.load('a');
  assert.equal(calls, 1);
  const sheet = { storyboard_id: 'a', sheet_hash: 'old' };
  finish(sheet);
  assert.deepEqual(await one, sheet);
  assert.deepEqual(await two, sheet);
  assert.equal(reader.peek('a'), sheet);
  const fresh = reader.load('a');
  assert.equal(calls, 2);
  finish({ storyboard_id: 'a', sheet_hash: 'new' });
  await fresh;
  assert.equal(reader.peek('a').sheet_hash, 'new');
});

test('failed reads retry and logout discards even results still in flight', async () => {
  let resolve;
  const reader = new SheetReader(() => new Promise(done => { resolve = done; }));
  const read = reader.load('a');
  reader.clear();
  resolve({ sheet_hash: 'private' });
  await read;
  assert.equal(reader.peek('a'), null);
  let calls = 0;
  const failing = new SheetReader(async () => { calls++; throw Error('offline'); });
  await assert.rejects(failing.load('a'));
  await assert.rejects(failing.load('a'));
  assert.equal(calls, 2);
});

test('snapshots have bounded memory', async () => {
  const reader = new SheetReader(async id => ({ id }), 2);
  for (const id of ['a', 'b', 'c']) await reader.load(id);
  assert.equal(reader.peek('a'), null);
  assert.equal(reader.peek('c').id, 'c');
});
