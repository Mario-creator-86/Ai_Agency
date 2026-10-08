// W36, THE LAST PLAIN SURFACES, GAME-GRADE. The release judge (W35) found Setări → Canale and
// Autonomie → Prețurile modelelor clean but plain (the OFF switch read as an alarm), a cold entry
// that showed the plates and the live stream at once for ~300 ms, Distribuție's first open under
// reduced motion laid out in one frame, a price form that could not add a model the preflight did
// not name nor price a whole provider, and the page's own labels for the two new places in «·»
// where the backend writes «→». Written before the code.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { fixPlaceOf } from '../src/readiness.js';
import {
  ANY_MODEL, DIRECTOR_RIGHT_MEANING, checkNewModel, directorRightLines, knownModels, priceAnswer, priceCommands,
  providerMark, providerWideRows, tokenPriceRows,
} from '../src/owner_controls.js';

const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const STYLE = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
const TITLE = fs.readFileSync(new URL('../src/title_screen.js', import.meta.url), 'utf8');
const SETTINGS = fs.readFileSync(new URL('../src/settings.js', import.meta.url), 'utf8');
const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');

test('the page\'s own names for the two new places are the backend\'s, with its arrow', () => {
  const old = (name, value) => ({ name, ok: false, severity: 'INFORMATIONAL', message: '…', detail: '', value, place: 'not_on_page', place_label: 'API-ul studioului' });
  assert.equal(fixPlaceOf({ ...old('model_prices', null), code: 'model_prices.unpriced' })?.label, 'Autonomie → Prețurile modelelor');
  assert.equal(fixPlaceOf({ ...old('serial_channel', { exists: true, bound: true }), code: 'serial_channel.director_may_not_approve' })?.label, 'Setări → Canale');
});

test('the switch\'s sentence is set as its two states, word for word, the current one marked', () => {
  const lines = directorRightLines(false);
  assert.equal(lines.length, 2);
  assert.deepEqual(lines.map((l) => l.state), ['on', 'off']);
  assert.ok(lines[0].text.startsWith('Pornit: '));
  assert.ok(lines[1].text.startsWith('Oprit: '));
  assert.equal(`${lines[0].text} ${lines[1].text}`, DIRECTOR_RIGHT_MEANING, 'nothing reworded, nothing lost');
  assert.deepEqual(lines.map((l) => l.now), [false, true]);
  assert.deepEqual(directorRightLines(true).map((l) => l.now), [true, false]);
});

test('a provider\'s mark is drawn from its name, one tone per name, no logo', () => {
  const o = providerMark('ollama');
  assert.equal(o.letter, 'O');
  assert.equal(o.name, 'Ollama');
  assert.ok(['info', 'forest', 'teal'].includes(o.tone));
  assert.deepEqual(providerMark('OLLAMA'), o, 'the kind\'s case does not change its mark');
  assert.equal(providerMark('my-llm').letter, 'M');
  assert.equal(providerMark('my-llm').name, 'my-llm');
  assert.equal(providerMark('').letter, '—');
});

const SETTINGS_READ = {
  integrations: [{ id: 'i-cloud', kind: 'ollama', name: 'Ollama Cloud' }, { id: 'i-voice', kind: 'elevenlabs', name: 'AMN-AI' }],
  legacy_providers: [{ id: 'p-local', provider_type: 'OLLAMA', name: 'local-ollama' }],
  models: [
    { id: 'm1', provider_id: 'i-cloud', model_name: 'kimi-k3', is_available: true },
    { id: 'm2', provider_id: 'p-local', model_name: 'glm-5.2:cloud', is_available: true },
    { id: 'm3', provider_id: 'i-cloud', model_name: 'kimi-k3', is_available: true },
    { id: 'm4', provider_id: 'unknown', model_name: 'orphan', is_available: true },
    { id: 'm5', provider_id: 'i-cloud', model_name: 'qwen3.5:397b', is_available: false },
  ],
};

test('the models the studio knows are its own, by the kind the price table is keyed by', () => {
  const known = knownModels(SETTINGS_READ);
  assert.deepEqual(known.map((k) => `${k.kind}:${k.model}`), ['ollama:glm-5.2:cloud', 'ollama:kimi-k3', 'ollama:qwen3.5:397b'], 'unique, lower-case kind, a model with no provider is left out');
  assert.deepEqual(knownModels(null), []);
});

test('a model is added to the list only when the studio knows it, and nothing is sent', () => {
  const known = knownModels(SETTINGS_READ);
  const rows = [{ kind: 'ollama', model: 'kimi-k3', input: null, output: null, priced: false }];
  assert.deepEqual(checkNewModel('ollama', 'glm-5.2:cloud', known, rows), { ok: true, row: { kind: 'ollama', model: 'glm-5.2:cloud' } });
  assert.deepEqual(checkNewModel('ollama', '  glm-5.2:cloud ', known, rows), { ok: true, row: { kind: 'ollama', model: 'glm-5.2:cloud' } }, 'trimmed');
  assert.equal(checkNewModel('ollama', '', known, rows).ok, false);
  assert.equal(checkNewModel('ollama', '', known, rows).error, 'Scrie numele modelului, așa cum îl știe studioul.');
  assert.equal(checkNewModel('ollama', 'gpt-9', known, rows).error, 'Studioul nu cunoaște modelul „gpt-9” la Ollama. Alege unul din lista lui.');
  assert.equal(checkNewModel('ollama', 'kimi-k3', known, rows).error, 'Modelul este deja în listă.');
  assert.equal(checkNewModel('ollama', '*', known, rows).error, 'Pentru toate modelele unui furnizor folosește rândul „Toate modelele Ollama”.');
  assert.equal(checkNewModel('elevenlabs', 'kimi-k3', known, rows).ok, false, 'a model is known at its own provider only');
});

const side = (resource, unit, usd, version = 1) => ({ provider_kind: 'ollama', resource, unit, usd, usd_micros: Math.round(Number(usd) * 1e6), version, active: true });

test('a whole provider has its own price: the backend\'s «*», apart from the model rows', () => {
  const prices = [side('*', 'per_1m_input_tokens', '0.4', 2), side('*', 'per_1m_output_tokens', '1.6'), side('kimi-k3', 'per_1m_input_tokens', '0.6')];
  const rows = tokenPriceRows({ checks: [] }, prices, [{ kind: 'ollama', model: 'glm-5.2:cloud' }]);
  assert.deepEqual(rows.map((r) => `${r.kind}:${r.model}`), ['ollama:glm-5.2:cloud', 'ollama:kimi-k3'], 'an added model is a row; «*» is not a model row');
  const wide = providerWideRows(prices, ['ollama', 'anthropic']);
  assert.deepEqual(wide.map((r) => `${r.kind}:${r.model}`), ['anthropic:*', 'ollama:*']);
  assert.equal(wide[1].model, ANY_MODEL);
  assert.equal(wide[1].priced, true);
  assert.equal(wide[1].input?.version, 2);
  assert.equal(wide[0].priced, false);
  const [cin, cout] = priceCommands(wide[1], '0.45', '1.8', ['a0000000-0000-4000-8000-000000000003', 'a0000000-0000-4000-8000-000000000004']);
  assert.equal(cin.resource, '*');
  assert.equal(cin.expected_version, 2);
  assert.equal(cout.resource, '*');
  assert.equal(priceAnswer(wide[1], { usd_micros: 450000, version: 3 }, { usd_micros: 1800000, version: 2 }),
    'Salvat: ollama · toate modelele — intrare 0,45 USD, ieșire 1,80 USD pe milion de tokenuri (versiunea 3).');
});

test('a cold entry holds the stream\'s picture until the push has landed, as the returning entry does', () => {
  assert.match(TITLE, /is-pushing/, 'the title marks the push of a cold entry');
  assert.match(TITLE, /if \(!lands\) \{\s*document\.body\.classList\.add\('is-pushing'/, 'only when no kept frame is carried');
  // W37: until the plates are all but gone (ENTRY.streamMs), not the push's end: judge_w37.test.js
  assert.match(TITLE, /setTimeout\([^\n]*classList\.remove\('is-pushing'\)[^\n]*ENTRY\.streamMs\)/, 'until the plates have all but gone');
  assert.match(STYLE, /body\.is-pushing[^{]*\.live-stream-layer[^{]*video[^{]*\{[^}]*opacity:\s*0/s);
  assert.match(STYLE, /body\.is-pushing[^{]*\.live-stream-still[^{]*\{[^}]*opacity:\s*0/s);
});

test('Distribuție\'s channel cards and publications are laid out one step per frame', () => {
  for (const id of ['channels-list', 'publications-list']) assert.match(HTML, new RegExp(`id="${id}"[^>]*data-door-steps`), id);
  assert.match(HTML, /class="pub-overview-grid" data-door-steps/);
  assert.match(HTML, /class="pub-card pub-channels-card" data-door-steps/);
});

test('the switch is a plate: calm when OFF, lit in the accent when ON, never an alarm', () => {
  const block = STYLE.slice(STYLE.indexOf('/* W36 — THE LAST PLAIN SURFACES'));
  assert.ok(block.length > 100, 'the W36 section exists');
  assert.ok(!/#[0-9a-f]{3,8}\b|rgba?\(/i.test(block.replace(/\/\*[\s\S]*?\*\//g, '')), 'no colour literal below :root');
  const state = /\.decision-state\s*\{([^}]*)\}/.exec(block);
  assert.ok(state && !/alert/.test(state[1]), 'the OFF word is not the alarm colour');
  assert.match(block, /\.decision-plate\.is-on[^{]*\{[^}]*var\(--teal\)/s, 'ON is lit in the page\'s accent');
  assert.match(SETTINGS, /role', 'switch'/);
  assert.match(SETTINGS, /director-right-switch/);
  assert.match(MAIN, /Adaugă în listă/);
});
