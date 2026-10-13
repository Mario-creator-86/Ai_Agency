// PAGE_SETTINGS_ERRORS (PAGE-17): every still the shooting sheet showed was kept for the whole
// session, and every clip and film played left its object URL behind. The pictures now live in an
// LRU of 60; what leaves it, and every clip a repaint or a close removes, is revoked.
import test from 'node:test';
import assert from 'node:assert/strict';
import { MediaCache, ObjectUrls, PICTURE_CAPACITY } from '../src/media_cache.js';

test('the picture cache holds 60 and revokes what it evicts, oldest first', () => {
  const revoked = [];
  const cache = new MediaCache(PICTURE_CAPACITY, (url) => revoked.push(url));
  assert.equal(PICTURE_CAPACITY, 60);
  for (let i = 0; i < 60; i += 1) cache.set(`/p/${i}`, `blob:${i}`);
  assert.equal(cache.size, 60);
  assert.deepEqual(revoked, []);
  cache.set('/p/60', 'blob:60');
  assert.equal(cache.size, 60);
  assert.deepEqual(revoked, ['blob:0']);
  assert.equal(cache.get('/p/0'), undefined);
});

test('a picture read again is kept as the newest', () => {
  const revoked = [];
  const cache = new MediaCache(3, (url) => revoked.push(url));
  cache.set('a', 'blob:a');
  cache.set('b', 'blob:b');
  cache.set('c', 'blob:c');
  assert.equal(cache.get('a'), 'blob:a');
  cache.set('d', 'blob:d');
  assert.deepEqual(revoked, ['blob:b']);
  assert.equal(cache.get('a'), 'blob:a');
});

test('replacing an entry revokes the old URL; clearing revokes all', () => {
  const revoked = [];
  const cache = new MediaCache(5, (url) => revoked.push(url));
  cache.set('a', 'blob:1');
  cache.set('a', 'blob:2');
  assert.deepEqual(revoked, ['blob:1']);
  cache.set('b', 'blob:3');
  cache.clear();
  assert.deepEqual(revoked.sort(), ['blob:1', 'blob:2', 'blob:3']);
  assert.equal(cache.size, 0);
});

test('the default revoke frees only object URLs, never a data: URL', () => {
  const freed = [];
  const original = URL.revokeObjectURL;
  URL.revokeObjectURL = (url) => { freed.push(url); };
  try {
    const cache = new MediaCache(1);
    cache.set('a', 'data:image/png;base64,AAAA');
    cache.set('b', 'blob:http://127.0.0.1/x');
    cache.set('c', 'blob:http://127.0.0.1/y');
    assert.deepEqual(freed, ['blob:http://127.0.0.1/x']);
  } finally {
    URL.revokeObjectURL = original;
  }
});

test('clips and films played are revoked together when their view goes', () => {
  const revoked = [];
  const urls = new ObjectUrls((url) => revoked.push(url));
  urls.add('blob:clip-1');
  urls.add('blob:clip-2');
  assert.equal(urls.size, 2);
  urls.revokeAll();
  assert.deepEqual(revoked, ['blob:clip-1', 'blob:clip-2']);
  assert.equal(urls.size, 0);
  urls.revokeAll();
  assert.equal(revoked.length, 2);
});

test('main.js keeps its pictures in the bounded cache and revokes what it plays', async () => {
  const { readFileSync } = await import('node:fs');
  const main = readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
  assert.match(main, /new MediaCache\(PICTURE_CAPACITY/);
  assert.doesNotMatch(main, /const sheetPictures = new Map\(\)/);
  assert.match(main, /sheetClips\.revokeAll\(\)/);
  assert.match(main, /filmUrls\.revokeAll\(\)/);
  // the media room reads one page of summary rows, never every storyboard's detail at once
  assert.match(main, /\/media\/storyboards\?limit=/);
  assert.doesNotMatch(main, /storyboards\.map\(async/);
});
