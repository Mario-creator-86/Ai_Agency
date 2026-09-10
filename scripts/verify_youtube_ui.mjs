/**
 * Drive the YouTube connection panel in a real browser and record what it actually shows.
 *
 * Google is never contacted: every request to accounts.google.com is aborted at the network
 * layer, and the URL the consent tab tried to load is captured there instead of being guessed.
 * Everything the panel renders comes from the studio's own API, so the screenshot this writes is
 * the genuine rendering of rows the real service code produced.
 *
 *   node scripts/verify_youtube_ui.mjs <port> <owner-token>
 */
import { chromium } from '../frontend/node_modules/playwright/index.mjs';

const [port, token] = process.argv.slice(2);
if (!port || !token) throw new Error('usage: verify_youtube_ui.mjs <port> <owner-token>');

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1280, height: 1500 } });

/** Where the consent tab was sent. Captured, never followed. */
const consentAttempts = [];
await context.route('https://accounts.google.com/**', (route) => {
  consentAttempts.push(route.request().url());
  return route.abort();
});

const page = await context.newPage();
const problems = [];
page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));
page.on('console', (m) => {
  if (m.type() === 'error') problems.push(`console: ${m.text()}`);
});

await page.goto(`http://127.0.0.1:${port}`);
await page.locator('#owner-token').fill(token);
await page.locator('#login-form button').click();
await page.locator('#open-settings').click();
await page.getByRole('button', { name: 'Conturi și e-mail' }).click();
await page.locator('.yt-card').first().waitFor();

const cards = await page.evaluate(() =>
  [...document.querySelectorAll('.yt-card')].map((card) => ({
    name: card.querySelector('.yt-card-name')?.textContent,
    status: card.querySelector('.tag')?.textContent,
    channel: card.querySelector('.yt-channel strong')?.textContent ?? null,
    identity: card.querySelector('.yt-channel .helper')?.textContent ?? null,
    secrets: [...card.querySelectorAll('.yt-meta dd')].map((d) => d.textContent),
    actions: [...card.querySelectorAll('.settings-actions button')].map((b) => b.textContent),
  })),
);

// The catalog picker must no longer offer YouTube: a second form asking for a refresh token
// beside the OAuth flow would put back exactly what the flow removes.
const catalogOffers = await page.evaluate(() =>
  [...document.querySelectorAll('.settings-add select option')].map((o) => o.textContent),
);
if (catalogOffers.some((label) => /youtube/i.test(label))) {
  problems.push(`the catalog still offers YouTube: ${catalogOffers.join(', ')}`);
}
// No field anywhere in the section may ask for a refresh token or a channel id.
const forbiddenFields = await page.evaluate(() =>
  [...document.querySelectorAll('.settings-content label, .settings-content .yt-field-label')]
    .map((l) => l.textContent.trim())
    .filter((label) => /refresh token|id canal/i.test(label)),
);
if (forbiddenFields.length) problems.push(`hand-typed fields remain: ${forbiddenFields.join(', ')}`);

// Nothing resembling a stored secret may appear anywhere in the rendered page.
const leaks = await page.evaluate(() => {
  const text = document.body.innerText;
  return ['not-real', 'client-secret-', 'refresh-token-'].filter((probe) => text.includes(probe));
});

await page.locator('.settings-content').screenshot({ path: 'output/playwright/youtube-panel.png' });

// The whole point of the refactor: the form must ask for four things and nothing else.
await page.getByRole('button', { name: 'Adaugă un canal' }).click();
const form = page.locator('.yt-form');
await form.waitFor();
const fields = await page.evaluate(() =>
  [...document.querySelectorAll('.yt-form .yt-field')].map((f) => ({
    label: f.querySelector('.yt-field-label')?.textContent,
    type: f.querySelector('input')?.type,
    value: f.querySelector('input')?.value,
  })),
);
await form.screenshot({ path: 'output/playwright/youtube-form.png' });
const expectedFields = [
  'Nume conexiune',
  'Google OAuth Client ID',
  'Google OAuth Client Secret',
  'Redirect URI',
];
const labels = fields.map((f) => f.label);
if (labels.join('|') !== expectedFields.join('|')) {
  problems.push(`form fields are ${labels.join(', ')}`);
}
if (fields[2]?.type !== 'password') problems.push('the client secret field is not masked');
if (!fields[3]?.value.endsWith('/auth/youtube/callback')) {
  problems.push(`redirect URI was not prefilled: ${fields[3]?.value}`);
}
await page.getByRole('button', { name: 'Renunță' }).click();
await page.locator('.yt-card').first().waitFor();

// Press Connect on the connection that has no token yet and see where it sends the browser.
const popupPromise = page.waitForEvent('popup');
await page.getByRole('button', { name: 'Conectează YouTube' }).click();
const popup = await popupPromise;
await popup.waitForTimeout(1500);
const consentUrl = consentAttempts[0] ?? null;
const stayedPut = new URL(page.url()).port === port;
await popup.close().catch(() => {});

if (consentUrl) {
  const url = new URL(consentUrl);
  const query = url.searchParams;
  for (const [key, expected] of [
    ['access_type', 'offline'],
    ['response_type', 'code'],
    ['include_granted_scopes', 'true'],
  ]) {
    if (query.get(key) !== expected) problems.push(`${key} is ${query.get(key)}, expected ${expected}`);
  }
  if (!query.get('state') || query.get('state').length < 32) problems.push('state is too short');
  if (query.get('prompt') !== 'consent') problems.push('prompt=consent missing on a first authorisation');
  if (url.origin !== 'https://accounts.google.com') problems.push(`consent origin ${url.origin}`);
}

if (!stayedPut) problems.push('the application navigated its own tab away instead of opening one');
if (leaks.length) problems.push(`secret-shaped text on screen: ${leaks.join(', ')}`);
if (!consentUrl) problems.push('no consent URL was requested');

console.log(JSON.stringify({ cards, fields, consentUrl, stayedPut, problems }, null, 1));
await browser.close();
if (problems.length) process.exitCode = 1;
