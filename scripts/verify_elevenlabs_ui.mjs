/** Browser acceptance check; demo_elevenlabs.py supplies an isolated studio and stubbed vendor. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from '../frontend/node_modules/playwright/index.mjs';

const base = process.argv[2];
const token = process.env.STUDIO_OWNER_TOKEN;
const key = process.env.ELEVENLABS_TEST_API_KEY;
assert(base && token && key, 'Run through scripts/demo_elevenlabs.py');
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 1100 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(base);
  await page.locator('#owner-token').fill(token);
  await page.locator('#login-form button').click();
  await page.locator('#open-settings').click();
  await page.getByRole('button', { name: 'Video și sunet', exact: true }).click();
  await page.getByRole('combobox', { name: 'Serviciu de adăugat' }).selectOption('elevenlabs');
  await page.getByRole('button', { name: 'Adaugă conexiune', exact: true }).click();
  const form = page.locator('.settings-editor');
  assert.deepEqual(await form.locator('input').evaluateAll((fields) => fields.map((f) => ({
    name: f.name, required: f.required, type: f.type,
  }))), [
    { name: 'name', required: true, type: 'text' },
    { name: 'api_key', required: true, type: 'password' },
  ]);
  await form.getByLabel('Numele conexiunii').fill('ElevenLabs UI acceptance · MOCK');
  await form.getByLabel('Cheie API').fill(key);
  const savedResponse = page.waitForResponse((r) => r.url().includes('/settings/integrations/') && r.request().method() === 'PUT');
  await form.getByRole('button', { name: 'Salvează conexiunea', exact: true }).click();
  const saved = await savedResponse;
  assert.equal(saved.status(), 200);
  const result = await saved.json();
  assert.equal(result.status, 'VERIFIED');
  assert.deepEqual(result.config, {});
  await page.locator('.elevenlabs-production').waitFor();
  const model = page.getByRole('combobox', { name: 'Model de producție', exact: true });
  const voice = page.getByRole('combobox', { name: 'Voce de producție', exact: true });
  assert.equal(await model.inputValue(), '');
  assert.equal(await voice.inputValue(), '');
  const values = (locator) => locator.locator('option').evaluateAll((options) => options.map((o) => o.value).filter(Boolean).sort());
  assert.deepEqual(await values(model), result.catalog.models.map((r) => r.remote_id).sort());
  assert.deepEqual(await values(voice), result.catalog.voices.map((r) => r.remote_id).sort());
  await model.selectOption(result.catalog.models[0].remote_id);
  await voice.selectOption(result.catalog.voices[0].remote_id);
  const configuredResponse = page.waitForResponse((r) => r.url().endsWith('/production'));
  await page.getByRole('button', { name: 'Salvează configurația de producție', exact: true }).click();
  assert.equal((await configuredResponse).status(), 200);
  await page.getByText('Configurație de producție salvată.', { exact: true }).waitFor();
  const refreshedResponse = page.waitForResponse((r) => r.url().endsWith('/refresh-resources'));
  await page.getByRole('button', { name: 'Actualizează modelele și vocile', exact: true }).click();
  assert.equal((await refreshedResponse).status(), 200);
  await page.getByText(/Conexiune verificată\. \d+ modele și \d+ voci încărcate\./).waitFor();
  assert.equal(await model.inputValue(), result.catalog.models[0].remote_id);
  assert.equal(await voice.inputValue(), result.catalog.voices[0].remote_id);
  assert(!(await page.locator('#settings-dialog').innerText()).includes(key));
  assert.deepEqual(errors, []);
  await mkdir('output/playwright', { recursive: true });
  await page.locator('.settings-content').screenshot({ path: 'output/playwright/elevenlabs-mock-acceptance.png' });
  const report = { evidence: 'LOCAL INTEGRATION / MOCK VENDOR', requiredFields: ['name', 'api_key'],
    connectionStatus: result.status, models: result.catalog.models.length, voices: result.catalog.voices.length,
    productionSelection: 'persisted', manualRefresh: 'passed', browserErrors: errors };
  await writeFile('output/playwright/elevenlabs-mock-acceptance.json', JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} catch (error) {
  console.error(String(error).replaceAll(token, '[REDACTED]').replaceAll(key, '[REDACTED]'));
  process.exitCode = 1;
} finally {
  await browser.close();
}
