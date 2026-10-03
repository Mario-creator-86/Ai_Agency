import test from 'node:test';
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { buttons, findAll, installDom, settle } from './fake_dom.js';

registerHooks({ load(url, context, next) {
  return url.endsWith('.css') ? { format: 'module', source: '', shortCircuit: true } : next(url, context);
} });
const { initSettings } = await import('../src/settings.js');

function harness(check, savedResult = null) {
  const { host } = installDom();
  const create = document.createElement;
  document.createElement = tag => {
    const el = create(tag);
    el.querySelectorAll = selector => findAll(el, n => selector.split(',').some(s => matches(n, s.trim())));
    el.querySelector = selector => el.querySelectorAll(selector)[0] || null;
    el.classList = {
      add(...names) { el.className += ' ' + names.join(' '); },
      toggle(name, enabled) {
        const names = new Set(el.className.split(/\s+/).filter(Boolean));
        if (enabled) names.add(name); else names.delete(name);
        el.className = [...names].join(' ');
      },
    };
    el.showModal = () => { el.open = true; };
    el.close = () => { el.open = false; };
    return el;
  };
  const header = document.createElement('header');
  host.append(header);
  document.body = host;
  document.querySelector = selector => selector === '.topbar-right' ? header : null;
  window.setTimeout = setTimeout;
  let result = savedResult;
  const calls = [];
  const api = async (path, options) => {
    calls.push({ path, options });
    if (path.endsWith('/check')) { result = await check(); return result; }
    return { catalog: { ollama: { group: 'llm', runtime: 'llm', label: 'Ollama' } },
      integrations: [{ id: 'cloud', name: 'Ollama Cloud', kind: 'ollama', status: result?.status || 'VERIFIED',
        config: { base_url: 'https://ollama.com' }, checked_at: '2026-10-03T06:14:49Z', check_result: result }],
      legacy_providers: [], agents: [], models: [], roles: [], selections: {} };
  };
  const settings = initSettings(api);
  const dialog = findAll(host, n => n.tagName === 'DIALOG')[0];
  return { settings, dialog, calls };
}

function matches(node, selector) {
  return selector.startsWith('.') ? node.className.split(/\s+/).includes(selector.slice(1)) : node.tagName === selector.toUpperCase();
}
function card(dialog) { return findAll(dialog, n => n.tagName === 'ARTICLE')[0]; }

test('an old public-catalog check does not certify the Cloud key', async () => {
  const h = harness(async () => ({}));
  await h.settings.open();
  assert.match(card(h.dialog).textContent, /cheia netestată/);
  assert.doesNotMatch(card(h.dialog).textContent, /Conexiune verificată/);
});

test('the button shows pending and the specific successful result on its own card', async () => {
  let finish;
  const h = harness(() => new Promise(resolve => { finish = resolve; }));
  await h.settings.open();
  const [button] = buttons(h.dialog, 'Verifică și încarcă modelele');
  const clicking = button.click();
  await settle();
  assert.match(card(h.dialog).textContent, /Se verifică/);
  assert.ok(buttons(h.dialog, 'Verifică și încarcă modelele')[0].disabled);
  finish({ status: 'VERIFIED', models_loaded: 17, generation_tested: false,
    message: 'Cheia API Ollama Cloud este validă. 17 modele încărcate. Generarea nu a fost testată.' });
  await clicking;
  await settle();
  assert.match(card(h.dialog).textContent, /Cheia API Ollama Cloud este validă/);
  assert.match(card(h.dialog).textContent, /17 modele/);
  assert.match(card(h.dialog).textContent, /Generarea nu a fost testată/);
  assert.equal(h.calls.filter(c => c.path.endsWith('/check')).length, 1);
});

test('a rejected key stays visible on the card after returning to the tab', async () => {
  const h = harness(async () => ({ status: 'FAILED', error_code: 'AUTH_REQUIRED', message: 'Cheia API a fost respinsă (HTTP 401).' }));
  await h.settings.open();
  await buttons(h.dialog, 'Verifică și încarcă modelele')[0].click();
  await settle();
  await buttons(h.dialog, 'Angajați')[0].click();
  await buttons(h.dialog, 'Furnizori AI')[0].click();
  const result = findAll(card(h.dialog), n => n.className.includes('settings-check-result'))[0];
  assert.match(result.textContent, /Cheia API a fost respinsă/);
  assert.ok(result.className.includes('settings-error'));
  assert.equal(result.getAttribute('role'), 'status');
});

test('a browser/network failure is shown on the tested card and allows a retry', async () => {
  const h = harness(async () => { throw new Error('Serverul studioului nu răspunde.'); });
  await h.settings.open();
  await buttons(h.dialog, 'Verifică și încarcă modelele')[0].click();
  await settle();
  assert.match(card(h.dialog).textContent, /Serverul studioului nu răspunde/);
  assert.equal(buttons(h.dialog, 'Verifică și încarcă modelele')[0].disabled, false);
});
