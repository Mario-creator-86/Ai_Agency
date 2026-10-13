// LOCAL_AUTO_LOGIN (2026-10-08). The Owner: «Te rog sa elimini pagina de logare, nu trebuie
// momentan». On his own machine the page asks the studio for his key (GET
// /api/v1/owner/local-session, answered only to this machine) and enters as the form would; from
// anywhere else the route is a 404 and the form shows as before. The key lives only in the page's
// memory, never in storage or the URL. After a sign-out the form offers to enter again without the
// key; after a refused key the page tries once by itself, never in a loop.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { askLocalKey, LOCAL_SESSION_HEADER, LOCAL_SESSION_URL, LocalEntry } from '../src/local_entry.js';

const KEY = 'k'.repeat(48);
const SOURCE = fs.readFileSync(new URL('../src/local_entry.js', import.meta.url), 'utf8');
const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');

/** A fetch that answers as given and records how it was asked. */
function fakeFetch(answer, calls = []) {
  const fn = async (url, init) => {
    calls.push({ url, init });
    if (answer instanceof Error) throw answer;
    return answer;
  };
  return Object.assign(fn, { calls });
}

const ok = (body) => ({ ok: true, status: 200, json: async () => body });
const status = (code) => ({ ok: false, status: code, json: async () => ({ detail: 'Not Found' }) });

// ------------------------------------------------------------------------------ asking for it

test('the page asks its own studio, same origin, with nothing cached and no cookies sent', async () => {
  const calls = [];
  const key = await askLocalKey({ fetchImpl: fakeFetch(ok({ token: KEY }), calls) });
  assert.equal(key, KEY);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/v1/owner/local-session');
  assert.equal(LOCAL_SESSION_URL, '/api/v1/owner/local-session');
  assert.equal(calls[0].init.method, 'GET');
  assert.equal(calls[0].init.credentials, 'omit');
  assert.equal(calls[0].init.cache, 'no-store');
  assert.ok(calls[0].init.signal, 'a short timeout');
  assert.ok(!('Authorization' in (calls[0].init.headers || {})), 'no key is sent to ask for the key');
  // The studio answers only a request carrying the page's own header: an <img>, <script>, frame,
  // form or link of another site cannot add one (backend/app/local_session.py).
  assert.equal(calls[0].init.headers['X-Studio-Local-Session'], '1');
  assert.equal(LOCAL_SESSION_HEADER, 'X-Studio-Local-Session');
});

test('a 404, a network failure, a timeout or a strange answer is no key', async () => {
  assert.equal(await askLocalKey({ fetchImpl: fakeFetch(status(404)) }), null);
  assert.equal(await askLocalKey({ fetchImpl: fakeFetch(status(500)) }), null);
  assert.equal(await askLocalKey({ fetchImpl: fakeFetch(new TypeError('Failed to fetch')) }), null);
  const timeout = Object.assign(new Error('timed out'), { name: 'TimeoutError' });
  assert.equal(await askLocalKey({ fetchImpl: fakeFetch(timeout) }), null);
  assert.equal(await askLocalKey({ fetchImpl: fakeFetch(ok({})) }), null);
  assert.equal(await askLocalKey({ fetchImpl: fakeFetch(ok({ token: 42 })) }), null);
  assert.equal(await askLocalKey({ fetchImpl: fakeFetch(ok({ token: 'short' })) }), null);
  assert.equal(await askLocalKey({ fetchImpl: fakeFetch({ ok: true, status: 200, json: async () => { throw new SyntaxError('html'); } }) }), null);
});

test('a page with no fetch at all shows the form', async () => {
  assert.equal(await askLocalKey({ fetchImpl: undefined }), null);
});

test('the key is never written to storage or to the URL', () => {
  for (const forbidden of ['localStorage', 'sessionStorage', 'location', 'history.', 'document.cookie']) {
    assert.ok(!SOURCE.includes(forbidden), `local_entry.js must not touch ${forbidden}`);
  }
});

// ---------------------------------------------------------------------------- the entry itself

/** The page's side of the entry: what it was asked to show, and the keys it entered with. */
function page({ keys = [KEY], accepts = [true] } = {}) {
  const log = [];
  const entered = [];
  let asked = 0;
  const entry = new LocalEntry({
    ask: async () => { asked++; const key = keys.length ? keys.shift() : null; log.push(`ask:${key ? 'key' : 'none'}`); return key; },
    enter: async (key) => { entered.push(key); const yes = accepts.length ? accepts.shift() : false; log.push(`enter:${yes}`); return yes; },
    view: {
      waiting: () => log.push('waiting'),
      form: (offer) => log.push(`form:${offer ? 'offer' : 'plain'}`),
    },
  });
  return { entry, log, entered, asked: () => asked };
}

test('on this machine the page enters without ever showing the form', async () => {
  const p = page();
  assert.equal(await p.entry.start(), true);
  assert.deepEqual(p.log, ['waiting', 'ask:key', 'enter:true']);
  assert.deepEqual(p.entered, [KEY]);
});

test('from elsewhere the form shows as before, with no offer', async () => {
  const p = page({ keys: [] });
  assert.equal(await p.entry.start(), false);
  assert.deepEqual(p.log, ['waiting', 'ask:none', 'form:plain']);
  assert.deepEqual(p.entered, []);
});

test('a handed key the studio then refuses falls back to the form, once', async () => {
  const p = page({ accepts: [false] });
  assert.equal(await p.entry.start(), false);
  assert.deepEqual(p.log, ['waiting', 'ask:key', 'enter:false', 'form:offer']);
  assert.equal(p.asked(), 1, 'no second try on its own');
});

test('after a sign-out the form offers to enter again, and the press enters', async () => {
  const p = page({ keys: [KEY, KEY], accepts: [true, true] });
  await p.entry.start();
  p.entry.offer();
  assert.equal(p.log.at(-1), 'form:offer');
  assert.equal(p.asked(), 1, 'the sign-out itself does not enter again');
  assert.equal(await p.entry.again(), true);
  assert.deepEqual(p.entered, [KEY, KEY]);
});

test('no offer after a sign-out when the page never had a key from this machine', async () => {
  const p = page({ keys: [] });
  await p.entry.start();
  p.entry.offer();
  assert.equal(p.log.at(-1), 'form:plain');
});

test('a key refused later is retried once by itself, and then the form waits for him', async () => {
  const p = page({ keys: [KEY, KEY, KEY], accepts: [true, true, true] });
  await p.entry.start();
  assert.equal(await p.entry.afterRefusal(), true, 'the first refusal: one automatic entry');
  assert.equal(p.asked(), 2);
  assert.equal(await p.entry.afterRefusal(), false, 'the second: no loop');
  assert.equal(p.asked(), 2);
  assert.equal(p.log.at(-1), 'form:offer');
  // his own press is not an automatic attempt and still works
  assert.equal(await p.entry.again(), true);
  assert.equal(p.asked(), 3);
});

test('when the studio stops handing the key over, the offer disappears', async () => {
  const p = page({ keys: [KEY, null], accepts: [true] });
  await p.entry.start();
  assert.equal(await p.entry.again(), false);
  assert.equal(p.log.at(-1), 'form:plain');
});

test('two attempts never run at once', async () => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  let asked = 0;
  const entry = new LocalEntry({
    ask: async () => { asked++; await gate; return KEY; },
    enter: async () => true,
    view: { waiting: () => {}, form: () => {} },
  });
  const first = entry.start();
  assert.equal(await entry.again(), false);
  release();
  assert.equal(await first, true);
  assert.equal(asked, 1);
});

// --------------------------------------------------------------------------------- the page

test('the form starts hidden, under a waiting line, so a local entry never flashes it', () => {
  const login = HTML.slice(HTML.indexOf('<section id="login"'), HTML.indexOf('</section>', HTML.indexOf('<section id="login"')));
  assert.match(login, /<form id="login-form" class="title-form" hidden>/);
  assert.match(login, /<p id="login-wait"[^>]*role="status"[^>]*>Se deschide studioul…<\/p>/);
  assert.match(login, /<p id="login-local"[^>]*hidden>[^<]*fără cheie/);
});

test('the form and the local entry share one way in; sign-out and a refusal go through the entry', () => {
  assert.ok(MAIN.includes("from './local_entry.js'"));
  assert.match(MAIN, /async function enterStudio\(key\)/);
  const submit = MAIN.slice(MAIN.indexOf("element('login-form').addEventListener"), MAIN.indexOf("element('logout').addEventListener"));
  assert.match(submit, /enterStudio\(/);
  assert.match(submit, /localEntry\.again\(\)/, 'an empty field on this machine enters without the key');
  const logout = MAIN.slice(MAIN.indexOf("element('logout').addEventListener"), MAIN.indexOf('environmentButton.addEventListener'));
  assert.match(logout, /localEntry\.offer\(\)/);
  const refresh = MAIN.slice(MAIN.indexOf('async function refresh()'), MAIN.indexOf('async function enterStudio(key)'));
  assert.match(refresh, /status === 401/);
  assert.match(refresh, /localEntry\.afterRefusal\(\)/);
  assert.match(MAIN, /void localEntry\.start\(\);/);
  for (const forbidden of ['localStorage.setItem(\'owner', 'sessionStorage.setItem(\'owner']) {
    assert.ok(!MAIN.includes(forbidden));
  }
});
