// PAGE_SETTINGS_ERRORS (TS-12): youtube_connections.js (connect, verify, disconnect, delete and
// edit a YouTube connection) had no test. These run it on a fake DOM with a fake api(): opening
// the section only reads; every change waits for his press (deletion for a second one); the
// bodies are the backend's commands; the words are Romanian; no secret is ever drawn.
import test from 'node:test';
import assert from 'node:assert/strict';
import { buttons, findAll, installDom, settle } from './fake_dom.js';

const { host, opened } = installDom();
const { renderYouTubeConnections } = await import('../src/youtube_connections.js');

const CONNECTED = {
  id: 'yt-1',
  name: 'Canalul A',
  status: 'CONNECTED',
  connected: true,
  client_id: 'abc.apps.googleusercontent.com',
  redirect_uri: 'http://127.0.0.1:8000/auth/youtube/callback',
  has_client_secret: true,
  has_refresh_token: true,
  channel: { id: 'UC123', title: 'Știință pe scurt', subscriber_count: 1200, video_count: 30, view_count: 45000 },
};

async function harness(connections = [CONNECTED], answers = {}) {
  host.replaceChildren();
  const calls = [];
  const notes = [];
  const api = async (path, options = {}) => {
    calls.push({ path, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null });
    if (path === '/youtube/connections' && !options.method) return { connections };
    const answer = answers[`${options.method || 'GET'} ${path}`];
    if (answer instanceof Error) throw answer;
    return answer || {};
  };
  renderYouTubeConnections(host, { api, notify: (text, error) => notes.push({ text, error: Boolean(error) }) });
  await settle();
  return { calls, notes };
}

test('opening the section only reads the connections; nothing is changed without his press', async () => {
  const { calls } = await harness();
  assert.deepEqual(calls.map((c) => `${c.method} ${c.path}`), ['GET /youtube/connections']);
  // the channel is shown back as evidence, with Romanian numbers
  assert.ok(findAll(host, (n) => n._text === 'Știință pe scurt').length === 1);
  assert.ok(findAll(host, (n) => /1\.200 abonați · 30 videoclipuri/.test(n._text)).length === 1);
});

test('no secret is ever drawn: only whether one is saved', async () => {
  await harness();
  const text = host.textContent;
  assert.match(text, /salvat, criptat/);
  assert.doesNotMatch(text, /refresh_token|client_secret"/);
});

test('deleting needs a second press, and only then sends DELETE', async () => {
  const { calls, notes } = await harness();
  const [remove] = buttons(host, 'Șterge');
  await remove.click();
  assert.equal(calls.length, 1, 'the first press only arms the key');
  assert.equal(remove.textContent, 'Confirmă ștergerea');
  await remove.click();
  await settle();
  assert.deepEqual(calls.slice(1, 2).map((c) => `${c.method} ${c.path}`), ['DELETE /youtube/connections/yt-1']);
  assert.deepEqual(notes[0], { text: 'Canalul A a fost șters.', error: false });
});

test('verify and disconnect are POSTs of their own, answered in Romanian', async () => {
  const { calls, notes } = await harness([CONNECTED], { 'POST /youtube/connections/yt-1/verify': { channel: { title: 'Știință pe scurt' } } });
  await buttons(host, 'Verifică')[0].click();
  await settle();
  assert.ok(calls.some((c) => c.method === 'POST' && c.path === '/youtube/connections/yt-1/verify'));
  assert.deepEqual(notes.at(-1), { text: 'Canal confirmat: Știință pe scurt.', error: false });
  await buttons(host, 'Deconectează')[0].click();
  await settle();
  assert.ok(calls.some((c) => c.method === 'POST' && c.path === '/youtube/connections/yt-1/disconnect'));
  assert.match(notes.at(-1).text, /tokenul a fost șters și revocat la Google/);
});

test('a refusal is shown in the backend\'s own words, as an error', async () => {
  const { notes } = await harness([CONNECTED], { 'POST /youtube/connections/yt-1/verify': new Error('Google a refuzat: reconectează contul.') });
  await buttons(host, 'Verifică')[0].click();
  await settle();
  assert.deepEqual(notes.at(-1), { text: 'Google a refuzat: reconectează contul.', error: true });
});

test('connecting opens the consent tab on the press and asks the backend for the address', async () => {
  const { calls } = await harness([{ ...CONNECTED, connected: false, status: 'AUTH_REQUIRED', channel: null }], {
    'POST /youtube/connections/yt-1/authorize': { authorization_url: 'https://accounts.google.com/o/oauth2/auth?x=1' },
  });
  await buttons(host, 'Conectează YouTube')[0].click();
  await settle();
  assert.ok(calls.some((c) => c.method === 'POST' && c.path === '/youtube/connections/yt-1/authorize'));
  assert.equal(opened.at(-1).opener, null, 'the opener link is cut');
  assert.equal(opened.at(-1).location, 'https://accounts.google.com/o/oauth2/auth?x=1');
});

test('a new connection without a client secret is refused before anything is sent', async () => {
  const { calls, notes } = await harness([]);
  await buttons(host, 'Adaugă un canal')[0].click();
  await settle();
  const form = findAll(host, (n) => n.tagName === 'FORM')[0];
  const inputs = findAll(form, (n) => n.tagName === 'INPUT');
  inputs[0].value = 'Canalul B';
  inputs[1].value = 'id.apps.googleusercontent.com';
  await form.dispatch('submit');
  await settle();
  assert.equal(calls.filter((c) => c.method !== 'GET').length, 0);
  assert.deepEqual(notes.at(-1), { text: 'Client Secret este obligatoriu la prima salvare.', error: true });
  // with the secret, one POST with his command id and the four fields
  inputs[2].value = 'secret-value'; // pragma: allowlist secret
  await form.dispatch('submit');
  await settle();
  const posted = calls.find((c) => c.method === 'POST' && c.path === '/youtube/connections');
  assert.ok(posted);
  assert.deepEqual(Object.keys(posted.body).sort(), ['client_id', 'client_secret', 'command_id', 'name', 'redirect_uri']);
  assert.equal(posted.body.redirect_uri, 'http://127.0.0.1:8000/auth/youtube/callback');
});
