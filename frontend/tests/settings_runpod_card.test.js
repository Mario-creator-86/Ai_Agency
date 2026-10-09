// The RunPod connection's card carries the «RunPod pornit» switch and «Pașii configurării»
// (his card, 2026-10-09); no other connection's card does.
import test from 'node:test';
import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import { findAll, installDom, settle } from './fake_dom.js';

registerHooks({ load(url, context, next) {
  return url.endsWith('.css') ? { format: 'module', source: '', shortCircuit: true } : next(url, context);
} });
const { initSettings } = await import('../src/settings.js');

function matches(node, selector) {
  return selector.startsWith('.') ? node.className.split(/\s+/).includes(selector.slice(1)) : node.tagName === selector.toUpperCase();
}

function harness() {
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
  const calls = [];
  const api = async (path) => {
    calls.push(path);
    if (path.startsWith('/runpod/')) {
      return { integration_id: 'rp', checked_at: null,
        switch: { on: false, can_turn_on: true, words_ro: 'RunPod oprit.' },
        rows: [{ key: 'api_key', title_ro: 'Cheia API RunPod', status: 'green', words_ro: 'Cheia API RunPod este salvată.', link: null }] };
    }
    return {
      catalog: {
        runpod: { group: 'media', runtime: 'media', label: 'RunPod GPU Cloud', fields: [], purposes: ['image', 'video'] },
        runway: { group: 'media', runtime: 'media', label: 'Runway', fields: [], purposes: ['video'] },
      },
      integrations: [
        { id: 'rp', name: 'RunPod', kind: 'runpod', status: 'VERIFIED', config: {}, secret_fields: [], version: 3 },
        { id: 'rw', name: 'Runway', kind: 'runway', status: 'VERIFIED', config: {}, secret_fields: [], version: 1 },
      ],
      legacy_providers: [], agents: [], models: [], roles: [], selections: {},
    };
  };
  const settings = initSettings(api);
  const dialog = findAll(host, n => n.tagName === 'DIALOG')[0];
  return { settings, dialog, calls };
}

test('the RunPod card shows the switch and the steps; the Runway card does not', async () => {
  const h = harness();
  await h.settings.open('media');
  await settle();
  const cards = findAll(h.dialog, n => n.tagName === 'ARTICLE');
  const runpod = cards.find(c => c.textContent.includes('RunPod GPU Cloud'));
  const runway = cards.find(c => c.textContent.includes('Runway ·'));
  assert.ok(runpod && runway);
  assert.match(runpod.textContent, /RunPod pornit/);
  assert.match(runpod.textContent, /Pașii configurării/);
  assert.match(runpod.textContent, /Cheia API RunPod este salvată/);
  assert.doesNotMatch(runway.textContent, /Pașii configurării/);
  assert.ok(h.calls.includes('/runpod/integrations/rp/setup'));
  assert.ok(!h.calls.some(path => path.endsWith('/setup/check')));
});
