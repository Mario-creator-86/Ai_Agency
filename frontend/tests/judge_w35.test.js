// W35, THE RELEASE JUDGE AGAIN. What the judge found when the page's new controls were driven
// against the real W34 backend on a fresh studio (scratchpad ui/w35/prove35.mjs). Written before
// the code.
import test from 'node:test';
import assert from 'node:assert/strict';
import { tokenPriceRows } from '../src/owner_controls.js';

const line = (models) => ({
  name: 'model_prices', ok: models.length === 0, code: 'model_prices.unpriced', place: 'treasury', place_section: 'tr-prices',
  value: { models: 3, unpriced: models.map((m) => ({ provider_kind: 'ollama', resource: m, missing_units: ['per_1m_input_tokens', 'per_1m_output_tokens'] })) },
});
const priced = (model, version = 1) => ['per_1m_input_tokens', 'per_1m_output_tokens'].map((unit) => ({
  provider_kind: 'ollama', resource: model, unit, usd: '0.5', usd_micros: 500000, version, active: true,
}));

test('a row the Owner has just priced stays where it was: the list does not reorder under his hand', () => {
  const before = tokenPriceRows({ checks: [line(['glm-5.2:cloud', 'kimi-k2.6:cloud', 'qwen3-coder:480b-cloud'])] }, []);
  // the backend recomputes the preflight after the first save: glm leaves the unpriced list and
  // comes back from the books
  const after = tokenPriceRows({ checks: [line(['kimi-k2.6:cloud', 'qwen3-coder:480b-cloud'])] }, priced('glm-5.2:cloud'));
  assert.deepEqual(before.map((r) => r.model), ['glm-5.2:cloud', 'kimi-k2.6:cloud', 'qwen3-coder:480b-cloud']);
  assert.deepEqual(after.map((r) => r.model), before.map((r) => r.model), 'the second row is still kimi, not qwen');
  assert.deepEqual(after.map((r) => r.priced), [true, false, false]);
});

test('the order is by provider, then model, whatever order the two sources arrive in', () => {
  const rows = tokenPriceRows(
    { checks: [line(['zeta', 'alpha'])] },
    [...priced('mid'), { provider_kind: 'anthropic', resource: 'claude-x', unit: 'per_1m_input_tokens', usd: '3', usd_micros: 3000000, version: 1, active: true }],
  );
  assert.deepEqual(rows.map((r) => `${r.kind}:${r.model}`), ['anthropic:claude-x', 'ollama:alpha', 'ollama:mid', 'ollama:zeta']);
});

test('«Studioul azi» does not call a run from another day «Rularea zilei»', async () => {
  const { studioReadout } = await import('../src/side_readout.js');
  const old = { empty: false, date: '2026-09-12', closed: 12, total: 12, finished: true, status: 'COMPLETED', running: null, segments: [] };
  const row = studioReadout({ track: old, today: '2026-09-25' }).rows[0];
  assert.equal(row.label, 'Ultima rulare', 'the run of 12.09 is the last run, not the day\'s');
  assert.equal(row.note, 'Rularea din 12.09');
  assert.equal(studioReadout({ track: { ...old, date: '2026-09-25' }, today: '2026-09-25' }).rows[0].label, 'Rularea zilei');
  // with no business date known, the page cannot say it is today's
  assert.equal(studioReadout({ track: old }).rows[0].label, 'Ultima rulare');
  // nothing read: the line keeps its name
  assert.equal(studioReadout({}).rows[0].label, 'Rularea zilei');
});

test('the side drawer\'s lower half arrives with the drawer, not before it', async () => {
  const fs = await import('node:fs');
  const css = fs.readFileSync(new URL('../src/style.css', import.meta.url), 'utf8');
  // the judge's frame at 400 ms: «Studioul azi» stood opaque while the rest of the frame was still
  // arriving, because it replaced .modules-panel, which the arrival named, and was never named itself
  assert.match(css, /body\.is-entering \.governance-panel,\s*body\.is-entering \.studio-readout,\s*body\.is-entering \.site-footer \{\s*animation: panel-arrive/);
  assert.match(css, /body\.is-entering \.studio-readout\s*\{ animation-delay: calc\(var\(--arrive-first\) \+ var\(--arrive-step\) \* 4\); \}/);
  // the arrival is declared before the reduced-motion list, so the list wins under the preference
  const arrive = css.search(/body\.is-entering \.studio-readout,\s*body\.is-entering \.site-footer \{/);
  const still = css.search(/body\.is-entering \.studio-readout,\s*body\.is-entering \.drawer-rail,/);
  assert.ok(arrive > 0 && arrive < still, 'arrival before the reduced-motion list');
  assert.match(css, /:root\[data-side="closed"\] body\.is-entering \.studio-readout \{ animation: none; \}/);
  const reduced = css.match(/body\.is-entering \.governance-panel,\s*body\.is-entering \.studio-readout,\s*body\.is-entering \.drawer-rail,\s*body\.is-entering \.site-footer \{ animation: none; \}/);
  assert.ok(reduced, 'under reduced motion it does not travel either');
});
