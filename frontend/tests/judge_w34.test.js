// W34, THE OWNER'S OWN DECISIONS ON THE PAGE, AND THE LAST NO ON THE MAIN SCREEN. The release judge
// (W33) found three of the Owner's decisions with no control on the page (the preflight said «doar
// prin API-ul studioului»), «Starea modulelor» at full weight on the main screen, a seam above the
// kept Unreal frame on the returning title, the register crowded by the watchdog's routine, raw
// YouTube and voice ids printed, and long scene prompts printed whole. Written before the code.
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { checklistHtml, fixPlaceOf, preflightChecklist } from '../src/readiness.js';
import {
  DIRECTOR_RIGHT_LABEL, directorRightAnswer, directorRightCommand, directorRightQuestion,
  priceAnswer, priceCommands, priceInput, serialChannel, tokenPriceRows, unpricedModels, channelFacts,
  modulesSummary,
} from '../src/owner_controls.js';
import { Ledger, describeEvent } from '../src/ledger.js';
import { keptEdges, titleFrame } from '../src/title_frame.js';
import { promptFirstSentence, voiceWords } from '../src/dialog_words.js';
import { escapeHtml } from '../src/html.js';

const HTML = fs.readFileSync(new URL('../index.html', import.meta.url), 'utf8');
const MAIN = fs.readFileSync(new URL('../src/main.js', import.meta.url), 'utf8');
const SETTINGS = fs.readFileSync(new URL('../src/settings.js', import.meta.url), 'utf8');

// the two lines as the W33 backend writes them (ui/w33/fixtures33/runbook_preflight.json)
const PRICES_NOT_ON_PAGE = {
  name: 'model_prices', ok: false, severity: 'DEGRADING', code: 'model_prices.unpriced', impact: 'degrades',
  message: 'Modele fără preț pe tokenuri la: ollama. … Prețul se pune deocamdată doar prin API-ul studioului: pagina nu are încă un loc pentru el.',
  detail: 'ollama:glm-5.3-flash, ollama:kimi-k3, ollama:mistral-large-3:675b',
  value: null, place: 'not_on_page', place_label: 'API-ul studioului', place_section: null,
  technical: { routes: ['PUT /economy/prices'], settings: [], scopes: [], fields: [], answers: [], paths: [] },
};
const DIRECTOR_NOT_ON_PAGE = {
  name: 'serial_channel', ok: false, severity: 'INFORMATIONAL', code: 'serial_channel.director_may_not_approve', impact: 'informs',
  message: 'Canalul serialului este legat, dar Directoarea nu are dreptul să aprobe episoade: …',
  detail: 'Channel B - Office Serial: legat, Directoarea nu poate aproba episoade',
  value: { channel_type: 'OFFICE_SERIAL', exists: true, bound: true, director_may_approve_episodes: false },
  place: 'not_on_page', place_label: 'API-ul studioului', place_section: null,
};

test('the two places that were «only through the API» now open the page\'s own controls', () => {
  assert.deepEqual(fixPlaceOf(PRICES_NOT_ON_PAGE), { label: 'Trezorerie · Prețurile modelelor', door: 'treasury-modal', section: 'tr-prices' });
  assert.deepEqual(fixPlaceOf(DIRECTOR_NOT_ON_PAGE), { label: 'Setări · Canale', door: 'settings', tab: 'channels' });
  // the Owner's running studio (no place, no code): read by the check's name and its value
  const { place, place_label, place_section, code, ...old } = DIRECTOR_NOT_ON_PAGE;
  assert.equal(fixPlaceOf(old)?.tab, 'channels');
  assert.equal(fixPlaceOf({ ...old, value: { ...old.value, bound: false } })?.door, 'publishing-modal', 'an unbound serial is fixed in its slot');
  assert.equal(fixPlaceOf({ ...old, value: { exists: false } }), null, 'no serial slot: nothing on the page creates one');
  const { place: p2, place_label: l2, place_section: s2, code: c2, ...oldPrices } = PRICES_NOT_ON_PAGE;
  assert.equal(fixPlaceOf(oldPrices)?.section, 'tr-prices');
  // a backend that moved them (the other half of this wave): its label wins, the page's own section
  // stands in for a section the page does not have
  assert.deepEqual(fixPlaceOf({ ...PRICES_NOT_ON_PAGE, place: 'treasury', place_label: 'Trezorerie → Prețurile modelelor', place_section: 'tr-token-prices' }),
    { label: 'Trezorerie → Prețurile modelelor', door: 'treasury-modal', section: 'tr-prices' });
  assert.deepEqual(fixPlaceOf({ ...DIRECTOR_NOT_ON_PAGE, place: 'settings:channels', place_label: 'Setări → Canale' }),
    { label: 'Setări → Canale', door: 'settings', tab: 'channels' });
  // FFmpeg stays on the machine: no key
  assert.equal(fixPlaceOf({ name: 'ffmpeg', ok: false, code: 'ffmpeg.missing', place: 'machine', place_label: 'calculatorul studioului' }), null);
  const html = checklistHtml(preflightChecklist({ checks: [PRICES_NOT_ON_PAGE, DIRECTOR_NOT_ON_PAGE] }), escapeHtml);
  assert.match(html, /data-door="treasury-modal" data-section="tr-prices">Deschide Trezorerie · Prețurile modelelor</);
  assert.match(html, /data-door="settings" data-tab="channels">Deschide Setări · Canale</);
  assert.ok(html.includes(PRICES_NOT_ON_PAGE.message), 'the backend\'s sentence is printed as it came');
});

const CHANNELS = [
  { id: '23d3ba8b-5f3c-4a99-9ab8-4993fe108f1a', channel_name: 'Main Channel A - Factual Shorts', channel_type: 'MAIN_FACTUAL', remote_channel_id: 'UCb6g_x2qeRFyGJkgIbkmKZA', youtube_channel_title: 'NEXUS CURIOSITY', publisher_ready: true, director_may_approve_episodes: false, policy_version: 1 },
  { id: '34acf9d6-d5e2-4891-a494-7dafc27a4438', channel_name: 'Channel B - Office Serial', channel_type: 'OFFICE_SERIAL', remote_channel_id: 'UCsJC65Up_k9TtKHA1eaEK3Q', youtube_channel_title: 'INSIDE THE NEXUS', publisher_ready: true, director_may_approve_episodes: false, policy_version: 3 },
];

test('the Director\'s right is the serial channel\'s versioned command, never set without its question', () => {
  assert.equal(serialChannel(CHANNELS)?.id, CHANNELS[1].id);
  assert.equal(serialChannel([CHANNELS[0]]), null);
  assert.equal(DIRECTOR_RIGHT_LABEL, 'Directoarea poate aproba episoadele serialului');
  const id = '0f7c7a36-2f3c-4b47-9d7c-1a2b3c4d5e6f';
  assert.deepEqual(directorRightCommand(CHANNELS[1], true, id), { command_id: id, expected_version: 3, director_may_approve_episodes: true });
  assert.deepEqual(directorRightCommand({ ...CHANNELS[1], policy_version: undefined }, false, id).expected_version, 1, 'a row before the policy existed is version 1');
  assert.equal(directorRightQuestion(true), 'Îi dai Directoarei dreptul să aprobe episoadele serialului?');
  assert.equal(directorRightQuestion(false), 'Îi iei Directoarei dreptul să aprobe episoadele serialului?');
  assert.equal(directorRightAnswer({ status: 'COMMITTED', channel: { director_may_approve_episodes: true, policy_version: 4 } }),
    'Salvat: Directoarea poate aproba episoadele serialului. Politica canalului este acum la versiunea 4.');
  assert.equal(directorRightAnswer({ status: 'COMMITTED', channel: { director_may_approve_episodes: false, policy_version: 5 } }),
    'Salvat: Directoarea nu mai poate aproba episoadele serialului. Politica canalului este acum la versiunea 5.');
  assert.equal(directorRightAnswer({ status: 'NO_CHANGE', channel: { director_may_approve_episodes: false, policy_version: 3 } }),
    'Nimic de schimbat: politica era deja așa (versiunea 3).');
  // an answer the page cannot read is not dressed as a success
  assert.equal(directorRightAnswer({ ok: true }), '');
  const facts = channelFacts(CHANNELS[1]);
  assert.equal(facts.type, 'Office Serial');
  assert.equal(facts.account, 'INSIDE THE NEXUS');
  assert.equal(facts.accountTitle, 'ID extern: UCsJC65Up_k9TtKHA1eaEK3Q');
  assert.equal(channelFacts({ ...CHANNELS[1], youtube_channel_title: null, publisher_ready: false }).account, 'nelegat');
});

test('a token price is read as the Owner writes it and refused when it is not a price', () => {
  assert.deepEqual(priceInput('0,50'), { ok: true, usd: '0.50' });
  assert.deepEqual(priceInput(' 2 '), { ok: true, usd: '2' });
  assert.deepEqual(priceInput('0.000125'), { ok: true, usd: '0.000125' });
  assert.deepEqual(priceInput('0'), { ok: true, usd: '0' }, 'a free local model is a fact, unlike a missing row');
  for (const bad of ['', '-1', '1,2,3', 'abc', '0.1234567', '1e3', '12345678901']) {
    assert.equal(priceInput(bad).ok, false, bad);
  }
  assert.equal(priceInput('abc').error, 'Scrie prețul ca număr, de exemplu 0,50 (cel mult 6 zecimale).');
});

test('the unpriced models come from the preflight line; the priced ones from the books', () => {
  assert.deepEqual(unpricedModels(PRICES_NOT_ON_PAGE), [
    { kind: 'ollama', model: 'glm-5.3-flash' }, { kind: 'ollama', model: 'kimi-k3' }, { kind: 'ollama', model: 'mistral-large-3:675b' },
  ]);
  // a backend that sends them as data is read as data
  assert.deepEqual(unpricedModels({ ...PRICES_NOT_ON_PAGE, value: { unpriced: [{ provider_kind: 'ollama', model: 'qwen3.5:397b' }] } }), [{ kind: 'ollama', model: 'qwen3.5:397b' }]);
  // the shape the W34 backend sends (preflight._price_check value.unpriced)
  assert.deepEqual(unpricedModels({ ...PRICES_NOT_ON_PAGE, value: { models: 6, unpriced: [{ provider_kind: 'ollama', resource: 'kimi-k3', missing_units: ['per_1m_output_tokens'] }] } }), [{ kind: 'ollama', model: 'kimi-k3' }]);
  assert.deepEqual(unpricedModels({ ...PRICES_NOT_ON_PAGE, ok: true }), []);
  assert.deepEqual(unpricedModels({ ...PRICES_NOT_ON_PAGE, detail: '6 modele, toate prețuite' }), [], 'a sentence is never read as models');
  const prices = [
    { provider_kind: 'elevenlabs', resource: '*', unit: 'per_1k_characters', usd: '0.22', usd_micros: 220000, version: 1, active: true },
    { provider_kind: 'ollama', resource: 'kimi-k3', unit: 'per_1m_input_tokens', usd: '0.6', usd_micros: 600000, version: 2, active: true },
  ];
  const rows = tokenPriceRows({ checks: [PRICES_NOT_ON_PAGE] }, prices);
  assert.deepEqual(rows.map((r) => `${r.kind}:${r.model}`), ['ollama:glm-5.3-flash', 'ollama:kimi-k3', 'ollama:mistral-large-3:675b']);
  const kimi = rows[1];
  assert.equal(kimi.input?.version, 2);
  assert.equal(kimi.output, null);
  assert.equal(kimi.priced, false, 'half a price is no price');
  const [cin, cout] = priceCommands(kimi, '0.6', '2.40', ['a0000000-0000-4000-8000-000000000001', 'a0000000-0000-4000-8000-000000000002']);
  assert.deepEqual(cin, { command_id: 'a0000000-0000-4000-8000-000000000001', provider_kind: 'ollama', resource: 'kimi-k3', unit: 'per_1m_input_tokens', usd: '0.6', provenance: 'OWNER', expected_version: 2 });
  assert.deepEqual(cout, { command_id: 'a0000000-0000-4000-8000-000000000002', provider_kind: 'ollama', resource: 'kimi-k3', unit: 'per_1m_output_tokens', usd: '2.40', provenance: 'OWNER' });
  assert.equal(priceAnswer(kimi, { usd_micros: 600000, version: 3 }, { usd_micros: 2400000, version: 1 }),
    'Salvat: ollama · kimi-k3 — intrare 0,60 USD, ieșire 2,40 USD pe milion de tokenuri (versiunea 3).');
});

const at = (hhmmss) => `2026-09-25T${hhmmss}.000+00:00`;
const routine = (n, hhmmss, type = 'WATCHDOG') => ({ event_id: `r-${n}`, sequence: n, timestamp: at(hhmmss), event_type: 'workflow.created', aggregate_id: `w-${n}`, payload: { workflow_type: type } });
const ownerAct = (n, hhmmss) => ({ event_id: `o-${n}`, sequence: n, timestamp: at(hhmmss), event_type: 'owner.autonomy_mode_changed', aggregate_id: 'policy', payload: { previous_autonomy_mode: 'SUPERVISED', autonomy_mode: 'AUTONOMOUS_CEO' } });

function ledgerStub() {
  const make = () => ({ className: '', textContent: '', type: '', innerHTML: '', children: [], addEventListener() {}, append(...k) { this.children.push(...k); }, replaceChildren(...k) { this.children = [...k]; } });
  globalThis.document = /** @type {any} */ ({ createElement: () => make() });
  const parts = { list: make(), now: make(), filters: make() };
  const ledger = new Ledger({ ...parts, escape: escapeHtml });
  ledger.timezone = 'UTC';
  return { ledger, parts };
}

test('the routine is one quiet row per stretch (and per hour across an act), in the studio\'s words, and never hides an Owner\'s act', () => {
  assert.equal(describeEvent(routine(1, '10:00:00')).text, 'supraveghetorul');
  const { ledger, parts } = ledgerStub();
  const events = [
    routine(1, '09:05:00'), routine(2, '09:15:00'),
    routine(3, '10:02:11'), routine(4, '10:12:00'), ownerAct(5, '10:20:00'), routine(6, '10:22:00', 'DIRECTOR_LOOP'),
    routine(7, '10:32:00'), routine(8, '10:42:00', 'TRENDS_REFRESH'), routine(9, '10:52:00', 'TRENDS_REFRESH'), routine(10, '10:58:31'),
  ];
  ledger.add(events);
  const html = parts.list.innerHTML;
  const rows = html.split('<li ').slice(1).filter((r) => !r.startsWith('class="ledger-day"'));
  assert.equal(rows.length, 3, 'two hours of routine and the Owner\'s act');
  const routineRows = rows.filter((r) => r.includes('ledger-routine'));
  assert.equal(routineRows.length, 2);
  assert.match(routineRows[0], /Rutina studioului/);
  assert.match(routineRows[0], /×7/);
  assert.match(routineRows[0], /supraveghetorul ×4 · tendințe ×2 · bucla Directoarei/);
  assert.match(routineRows[0], /10:02:11 – 10:58:31/);
  assert.match(routineRows[0], /<time>10:58:31<\/time>/);
  assert.match(routineRows[1], /×2/);
  assert.ok(rows.some((r) => r.includes('Proprietarul a schimbat modul de autonomie') && !r.includes('ledger-routine')), 'the Owner\'s act keeps its own row');
  // the order is the record's: the hour's summary stands where its newest routine entry is
  assert.ok(html.indexOf('×7') < html.indexOf('Proprietarul a schimbat') && html.indexOf('Proprietarul a schimbat') < html.indexOf('×2</span>'));
  const counted = [...html.matchAll(/×(\d+)<\/span>/g)].reduce((a, m) => a + Number(m[1]), 0);
  assert.equal(counted + 1, events.length, 'every event is its own row or inside a count');
  assert.match(html, /title="Sarcini pe care ceasul studioului le pornește singur; nu fac filme\."/);
});

test('the returning title\'s sky continues the frame\'s own edges: every strip the frame leaves is known', () => {
  const frame = titleFrame(1920, 1080);
  const edges = keptEdges(frame, 1920, 1080);
  const top = frame.y;
  if (top > 0) assert.deepEqual(edges.top, { x: frame.x, y: 0, w: 1600 * frame.scale, h: top });
  else assert.equal(edges.top, null);
  // a frame that covers the screen leaves nothing
  const all = keptEdges({ x: -10, y: -10, scale: 2 }, 1920, 1080);
  assert.deepEqual(all, { top: null, bottom: null, left: null, right: null });
  const small = keptEdges({ x: 100, y: 50, scale: 0.5 }, 1280, 800);
  assert.deepEqual(small.top, { x: 100, y: 0, w: 800, h: 50 });
  assert.deepEqual(small.bottom, { x: 100, y: 470, w: 800, h: 330 });
  assert.deepEqual(small.left, { x: 0, y: 0, w: 100, h: 800 });
  assert.deepEqual(small.right, { x: 900, y: 0, w: 380, h: 800 });
});

test('a long scene prompt shows its first sentence; the rest is one disclosure away, word for word', () => {
  const p = 'A yellowed 1964 theory page dissolving into a glowing field filling a dark universe. A yellowed 1964 theory page dissolving into a glowing field filling a dark universe. Environment: A yellowed page.. Camera: medium shot, locked camera.';
  const { first, rest } = promptFirstSentence(p);
  assert.equal(first, 'A yellowed 1964 theory page dissolving into a glowing field filling a dark universe.');
  assert.equal(`${first} ${rest}`, p);
  assert.deepEqual(promptFirstSentence('Galaxy spinning, then a ghostly overlay; pie chart updates to show 27% labeled \'Dark Matter\'.'), { first: 'Galaxy spinning, then a ghostly overlay; pie chart updates to show 27% labeled \'Dark Matter\'.', rest: '' });
  assert.deepEqual(promptFirstSentence('Scene 3'), { first: 'Scene 3', rest: '' });
  // a short prompt of two sentences is not folded
  assert.equal(promptFirstSentence('Wide shot. Then a pie chart.').rest, '');
});

test('a voice is its style and pace; its id is the tooltip', () => {
  assert.deepEqual(voiceWords({ voice_id: 'dr_aris_narrator', style: 'Scientific/Inquisitive', speed: 0.98 }),
    { text: 'Scientific/Inquisitive · ×0,98', title: 'Identificatorul vocii: dr_aris_narrator' });
  assert.deepEqual(voiceWords({ voice_id: 'lyra_studio', style: 'Warm', speed: 1 }), { text: 'Warm · ×1', title: 'Identificatorul vocii: lyra_studio' });
  assert.deepEqual(voiceWords({}), { text: '', title: '' });
  assert.deepEqual(voiceWords({ voice_id: 'x_only' }), { text: '—', title: 'Identificatorul vocii: x_only' });
});

test('the page wires them: Setări → Canale and Despre studio, Trezorerie → Prețurile modelelor, no module list on the main screen', () => {
  assert.match(SETTINGS, /\['channels', 'Canale'\]/);
  assert.match(SETTINGS, /\['about', 'Despre studio'\]/);
  assert.ok(!HTML.includes('id="modules-panel"'), 'the module list left the drawer');
  assert.ok(!/<h2>Starea modulelor<\/h2>/.test(HTML));
  assert.match(HTML, /<a href="#tr-prices">Prețurile modelelor<\/a>/);
  assert.match(HTML, /id="tr-prices"/);
  assert.match(HTML, /id="studio-about-btn"/);
  assert.equal(modulesSummary({ agents: 'IMPLEMENTED', research: 'PARTIAL', vendorshop: 'NOT_IMPLEMENTED', settings: 'IMPLEMENTED' }), '2 implementate · 1 parțial · 1 neimplementat');
  // Research's heavy parts come in one step per frame, as Media's do
  for (const id of ['rs-topics', 'rs-sources', 'rs-scripts']) assert.match(HTML, new RegExp(`id="${id}"[^>]*data-door-steps`), id);
  assert.match(MAIN, /distribution-account" title="\$\{escapeHtml\(/);
  assert.ok(!MAIN.includes('ID extern: <code>'), 'the raw id is no longer printed');
});

test('the returning title\'s sky row: the building that touches the frame\'s top is not drawn on into the sky', async () => {
  const { skyRow } = await import('../src/title_frame.js');
  const px = (/** @type {number[][]} */ cols) => new Uint8ClampedArray(cols.flatMap(([r, g, b]) => [r, g, b, 255]));
  // a bright day sky with the dark lift tower in the middle
  const day = px([[90, 150, 220], [92, 152, 222], [5, 8, 12], [4, 6, 10], [98, 158, 228], [100, 160, 230]]);
  const out = skyRow(day, 6);
  assert.deepEqual(Array.from(out.slice(8, 12)), [94, 154, 224, 255], 'the tower\'s first column is the sky between');
  assert.deepEqual(Array.from(out.slice(12, 16)), [96, 156, 226, 255]);
  assert.deepEqual(Array.from(out.slice(0, 8)), Array.from(day.slice(0, 8)), 'the sky itself is untouched');
  // the night: no bright sky, nothing is taken for the building
  const night = px([[2, 7, 19], [1, 2, 6], [3, 9, 29], [1, 3, 4]]);
  assert.deepEqual(Array.from(skyRow(night, 4)), Array.from(night));
  // a dark run at the edge takes the nearest sky
  const edge = skyRow(px([[3, 3, 3], [120, 170, 230], [118, 168, 228], [121, 171, 231]]), 4);
  assert.deepEqual(Array.from(edge.slice(0, 4)), [120, 170, 230, 255]);
});
