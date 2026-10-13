// PAGE_OWNER_DAY (PAGE-01, REL-07): the page says when it is older than the studio, and when
// something that keeps the studio running is wrong. The words are the snapshot's; the module only
// decides which banners stand.
import test from 'node:test';
import assert from 'node:assert/strict';
import { PAGE_STALE_WORDS, bannersKey, pageBanners } from '../src/build_banner.js';

test('a page built from older sources says so, in his words', () => {
  assert.equal(PAGE_STALE_WORDS, 'Pagina e mai veche decât studioul: repornește studioul.');
  const banners = pageBanners({ page_build: { built: 'a'.repeat(64), source: 'b'.repeat(64), stale: true } });
  assert.deepEqual(banners.map((b) => [b.kind, b.text]), [['page', PAGE_STALE_WORDS]]);
  assert.equal(banners[0].tone, 'warn');
});

test('a current page, or a studio that cannot tell, shows no page banner', () => {
  assert.deepEqual(pageBanners({ page_build: { built: 'a', source: 'a', stale: false } }), []);
  assert.deepEqual(pageBanners({ page_build: null }), []);
  assert.deepEqual(pageBanners({}), []);
  assert.deepEqual(pageBanners(null), []);
});

test('the operations reading is shown in its own words while anything is wrong', () => {
  const operations = {
    status: 'DEGRADED',
    banner_ro: 'Lucrătorul nu a mai lucrat de 14 minute: ultima trecere a fost la 10:02.',
    problems: [{ code: 'WORKER_STALE', reason_ro: 'Lucrătorul nu a mai lucrat de 14 minute: ultima trecere a fost la 10:02.' }],
  };
  const banners = pageBanners({ operations });
  assert.deepEqual(banners.map((b) => [b.kind, b.text, b.tone]), [['operations', operations.banner_ro, 'alert']]);
  // more than one problem: the first in words, the rest counted with the right plural
  const two = pageBanners({ operations: { ...operations, problems: [...operations.problems, { code: 'DISK_LOW', reason_ro: 'Discul are 3 GB liberi.' }] } });
  assert.equal(two[0].text, `${operations.banner_ro} (încă o problemă)`);
  const three = pageBanners({ operations: { ...operations, problems: [...operations.problems, { code: 'a' }, { code: 'b' }] } });
  assert.match(three[0].text, /\(încă 2 probleme\)$/);
  assert.deepEqual(pageBanners({ operations: { status: 'HEALTHY', banner_ro: '', problems: [] } }), []);
  // both at once: the studio's problem first, the page after
  const both = pageBanners({ operations, page_build: { stale: true } });
  assert.deepEqual(both.map((b) => b.kind), ['operations', 'page']);
});

test('the key changes only when a banner does', () => {
  const a = bannersKey(pageBanners({ page_build: { stale: true } }));
  assert.equal(a, bannersKey(pageBanners({ page_build: { stale: true, built: 'x' } })));
  assert.notEqual(a, bannersKey([]));
});
