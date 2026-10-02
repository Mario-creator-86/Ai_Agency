// PAGE_SETTINGS_ERRORS (TS-12): provider_production.js (the production model and voice of a
// paid connection, and the catalog refresh) had no test at all. These run it on a fake DOM with a
// fake api(): nothing is sent until he presses a key, and the bodies are the backend's commands.
import test from 'node:test';
import assert from 'node:assert/strict';
import { buttons, findAll, installDom, settle } from './fake_dom.js';

const { host } = installDom();
const { renderProviderProduction } = await import('../src/provider_production.js');

const CATALOG = {
  kind_info: { title: 'Producție ElevenLabs', has_voices: true, model_label: 'Model', voice_label: 'Voce' },
  discovery: { status: 'READY', last_success_at: '2026-10-01T10:00:00Z' },
  production: { model_id: 'eleven_multilingual_v2', voice_id: 'v-1', image_model_id: null, allow_production_override: true, version: 7 },
  models: [
    { name: 'Multilingual v2', remote_id: 'eleven_multilingual_v2', usable_purposes: ['voice'], production_usable: true },
    { name: 'Old', remote_id: 'old', usable_purposes: [], production_usable: false },
  ],
  voices: [{ name: 'Roger', remote_id: 'v-1', production_usable: true }],
};

function harness(connection, catalog = CATALOG) {
  host.replaceChildren();
  const calls = [];
  const said = [];
  const api = async (path, options = {}) => { calls.push({ path, options }); return {}; };
  const run = async (op, success) => { await op(); said.push(success); };
  renderProviderProduction(host, connection, catalog, { api, run });
  return { calls, said };
}

test('drawing the section sends nothing', () => {
  const { calls } = harness({ id: 'int-1', status: 'VERIFIED' });
  assert.equal(calls.length, 0);
  assert.ok(findAll(host, (n) => n.textContent === 'Producție ElevenLabs').length > 0);
});

test('«Salvează valorile implicite» sends the versioned production command with what is selected', async () => {
  const { calls, said } = harness({ id: 'int-1', status: 'VERIFIED' });
  const [save] = buttons(host, 'Salvează valorile implicite');
  await save.click();
  await settle();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].path, '/settings/integrations/int-1/production');
  assert.equal(calls[0].options.method, 'PUT');
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    model_id: 'eleven_multilingual_v2', voice_id: 'v-1', image_model_id: null, allow_production_override: true, expected_version: 7,
  });
  assert.deepEqual(said, ['Valori implicite salvate.']);
});

test('a model the vendor marks unusable cannot be chosen', () => {
  harness({ id: 'int-1', status: 'VERIFIED' });
  const selects = findAll(host, (n) => n.tagName === 'SELECT');
  const old = selects[0].options.find((o) => o.value === 'old');
  assert.equal(old.disabled, true);
  assert.match(old.text, /indisponibil/);
});

test('the catalog refresh is its own press, a POST, in Romanian', async () => {
  const { calls, said } = harness({ id: 'int-2', status: 'SAVED' });
  const [refresh] = buttons(host, 'Actualizează catalogul');
  await refresh.click();
  await settle();
  assert.deepEqual(calls.map((c) => [c.path, c.options.method]), [['/settings/integrations/int-2/refresh-resources', 'POST']]);
  assert.deepEqual(said, ['Catalog actualizat.']);
});

test('an unverified key offers no defaults to save, and says why', () => {
  harness({ id: 'int-3', status: 'SAVED' });
  assert.equal(buttons(host, 'Salvează valorile implicite').length, 0);
  assert.ok(findAll(host, (n) => /Verifică cheia/.test(n._text)).length > 0);
});

test('an empty catalog says so in Romanian', () => {
  harness({ id: 'int-1', status: 'VERIFIED' }, { ...CATALOG, models: [], voices: [] });
  assert.ok(findAll(host, (n) => /API-ul nu a returnat nicio opțiune/.test(n._text)).length >= 2);
});
