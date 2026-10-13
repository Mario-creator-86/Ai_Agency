import test from 'node:test';
import assert from 'node:assert/strict';
import { buttons, findAll, installDom, settle } from './fake_dom.js';

const { STATUS_LABEL, renderRunPodSetup, rowView, safeLink, switchCommand } = await import('../src/runpod_setup.js');

const setup = (on = false, canTurnOn = true) => ({
  integration_id: 'rp',
  checked_at: null,
  switch: { on, source: on ? 'switch' : 'environment', can_turn_on: canTurnOn,
    why_not_ro: canTurnOn ? null : 'Conexiunea RunPod nu este verificată.',
    words_ro: on ? 'RunPod pornit: pașii plătiți aprobați pot porni GPU-ul.' : 'RunPod oprit.' },
  rows: [
    { key: 'api_key', title_ro: 'Cheia API RunPod', status: 'green', words_ro: 'Cheia API RunPod este salvată.',
      link: 'https://console.runpod.io/user/settings', link_ro: 'Consola RunPod → API Keys' },
    { key: 'cached_model', title_ro: 'Modelul din cache', status: 'grey',
      words_ro: 'Nu se poate citi prin API: se verifică la primul rezultat (weights_revision).',
      link: 'https://console.runpod.io/serverless', link_ro: 'Consola' },
    { key: 'bucket', title_ro: 'Bucketul', status: 'red', words_ro: 'Bucketul refuză cheile (HTTP 403).',
      link: 'javascript:alert(1)', link_ro: 'rău' },
  ],
});

test('the words of a row and its status', () => {
  assert.equal(STATUS_LABEL.green, 'verde');
  assert.equal(STATUS_LABEL.red, 'roșu');
  assert.equal(STATUS_LABEL.grey, 'nu se poate verifica încă');
  const view = rowView(setup().rows[1]);
  assert.equal(view.tone, 'grey');
  assert.match(view.words, /weights_revision/);
  assert.equal(rowView({ status: 'odd', words_ro: 'x' }).tone, 'grey');
});

test('only the console pages are links', () => {
  assert.equal(safeLink('https://console.runpod.io/serverless'), 'https://console.runpod.io/serverless');
  assert.equal(safeLink('https://huggingface.co/settings/tokens'), 'https://huggingface.co/settings/tokens');
  assert.equal(safeLink('https://dash.cloudflare.com/?to=/:account/r2/overview'), 'https://dash.cloudflare.com/?to=/:account/r2/overview');
  assert.equal(safeLink('https://github.com/new'), 'https://github.com/new');
  assert.equal(safeLink('javascript:alert(1)'), null);
  assert.equal(safeLink('https://evil.example/'), null);
  assert.equal(safeLink(null), null);
});

test('the switch command', () => {
  assert.deepEqual(switchCommand(true), { schema_version: 1, on: true });
  assert.deepEqual(switchCommand(false), { schema_version: 1, on: false });
});

function harness(answers) {
  const { host } = installDom();
  const calls = [];
  const api = async (path, options = {}) => {
    calls.push({ path, method: options.method || 'GET', body: options.body ? JSON.parse(options.body) : null });
    const answer = answers(path, options);
    if (answer instanceof Error) throw answer;
    return answer;
  };
  const card = document.createElement('article');
  host.append(card);
  return { card, calls, api };
}

test('on page open the cached checklist is shown without a check', async () => {
  const h = harness(() => setup());
  await renderRunPodSetup(h.card, { id: 'rp' }, { api: h.api });
  await settle();
  assert.deepEqual(h.calls.map(c => `${c.method} ${c.path}`), ['GET /runpod/integrations/rp/setup']);
  const text = h.card.textContent;
  assert.match(text, /Pașii configurării/);
  assert.match(text, /RunPod oprit/);
  assert.match(text, /nu se poate verifica încă/);
  assert.match(text, /weights_revision/);
  const links = findAll(h.card, n => n.tagName === 'A');
  assert.deepEqual(links.map(a => a.href), ['https://console.runpod.io/user/settings', 'https://console.runpod.io/serverless']);
  for (const link of links) assert.equal(link.rel, 'noopener noreferrer');
});

test('«Verifică pașii» asks for a fresh check', async () => {
  const h = harness(() => setup());
  await renderRunPodSetup(h.card, { id: 'rp' }, { api: h.api });
  await settle();
  const [check] = buttons(h.card, 'Verifică pașii');
  await check.click();
  await settle();
  assert.deepEqual(h.calls.at(-1), { path: '/runpod/integrations/rp/setup/check', method: 'POST', body: null });
});

test('turning on asks a second press, then sends his command; the refusal is shown', async () => {
  let refuse = true;
  const h = harness((path, options) => {
    if (options.method === 'PUT') return refuse ? new Error('Conexiunea RunPod nu este verificată.') : { ...setup(true).switch, readings: [] };
    return setup(false);
  });
  await renderRunPodSetup(h.card, { id: 'rp' }, { api: h.api });
  await settle();
  const [turnOn] = buttons(h.card, 'Pornește RunPod');
  await turnOn.click();
  await settle();
  assert.equal(h.calls.filter(c => c.method === 'PUT').length, 0);
  const [confirm] = buttons(h.card, 'Confirmă pornirea RunPod');
  await confirm.click();
  await settle();
  const sent = h.calls.filter(c => c.method === 'PUT');
  assert.deepEqual(sent, [{ path: '/runpod/integrations/rp/switch', method: 'PUT', body: { schema_version: 1, on: true } }]);
  assert.match(h.card.textContent, /nu este verificată/);
  refuse = false;
});

test('turning off is one press and immediate', async () => {
  const h = harness((path, options) => options.method === 'PUT'
    ? { ...setup(false).switch, readings: [{ off: true }], words_ro: 'RunPod oprit. GPU-ul este oprit și verificat.' }
    : setup(true));
  await renderRunPodSetup(h.card, { id: 'rp' }, { api: h.api });
  await settle();
  const [turnOff] = buttons(h.card, 'Oprește RunPod');
  await turnOff.click();
  await settle();
  const sent = h.calls.filter(c => c.method === 'PUT');
  assert.deepEqual(sent.map(c => c.body), [{ schema_version: 1, on: false }]);
  assert.match(h.card.textContent, /oprit și verificat/);
});

test('without a verified connection the switch says why and cannot turn on', async () => {
  const h = harness(() => setup(false, false));
  await renderRunPodSetup(h.card, { id: 'rp' }, { api: h.api });
  await settle();
  const [turnOn] = buttons(h.card, 'Pornește RunPod');
  assert.equal(turnOn.disabled, true);
  assert.match(h.card.textContent, /nu este verificată/);
});

// Verified as the Owner (2026-10-09): after a press the checklist's own «Comutatorul» row must
// say what the switch box says, and the outcome sentence is written once, not twice.
const withSwitchRow = (on) => {
  const answer = setup(on);
  answer.rows.push({ key: 'switch', title_ro: 'Comutatorul «RunPod pornit»', status: on ? 'green' : 'red',
    words_ro: answer.switch.words_ro, link: null, link_ro: null });
  return answer;
};

test('after turning on, the switch row of the checklist follows the switch', async () => {
  const h = harness((path, options) => options.method === 'PUT'
    ? { ...withSwitchRow(true).switch, readings: [] }
    : withSwitchRow(false));
  await renderRunPodSetup(h.card, { id: 'rp' }, { api: h.api });
  await settle();
  await buttons(h.card, 'Pornește RunPod')[0].click();
  await settle();
  await buttons(h.card, 'Confirmă pornirea RunPod')[0].click();
  await settle();
  const [row] = findAll(h.card, n => n.tagName === 'LI' && n.textContent.includes('Comutatorul'));
  assert.equal(row.dataset.status, 'green');
  assert.match(row.textContent, /RunPod pornit/);
  assert.doesNotMatch(row.textContent, /RunPod oprit/);
});

test('after turning off, the outcome is said once and the switch row is red', async () => {
  const h = harness((path, options) => options.method === 'PUT'
    ? { ...withSwitchRow(false).switch, readings: [{ off: true }], words_ro: 'RunPod oprit. GPU-ul este oprit și verificat.' }
    : withSwitchRow(true));
  await renderRunPodSetup(h.card, { id: 'rp' }, { api: h.api });
  await settle();
  await buttons(h.card, 'Oprește RunPod')[0].click();
  await settle();
  const box = findAll(h.card, n => n.className === 'runpod-switch')[0];
  assert.equal(box.textContent.split('oprit și verificat').length - 1, 1);
  const [row] = findAll(h.card, n => n.tagName === 'LI' && n.textContent.includes('Comutatorul'));
  assert.equal(row.dataset.status, 'red');
});

test('a step row wraps a long repo name or endpoint id on a phone', async () => {
  const fs = await import('node:fs');
  const css = fs.readFileSync(new URL('../src/settings.css', import.meta.url), 'utf8');
  const rule = css.match(/\.runpod-step \{([^}]*)\}/);
  assert.ok(rule, 'the step rule exists');
  assert.match(rule[1], /overflow-wrap:\s*anywhere/);
  assert.match(rule[1], /min-width:\s*0/);
});
