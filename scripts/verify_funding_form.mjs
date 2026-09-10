/**
 * Drive the Owner funding form in a real browser against an isolated studio.
 *
 * The form is the only place an Owner puts money into the company, so what matters is not that
 * it submits but that it refuses correctly: an ambiguous amount, a loan without a maturity, a
 * foreign currency without a rate anyone can point at. Each of those is exercised here, and the
 * resulting treasury figures are read back from the page rather than assumed.
 *
 * Usage: node scripts/verify_funding_form.mjs <port> <owner-token>
 */

import { chromium } from '../frontend/node_modules/playwright/index.mjs';

const [port, token] = process.argv.slice(2);
if (!port || !token) throw new Error('Usage: verify_funding_form.mjs <port> <token>');

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1200, height: 1300 } });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => {
  if (m.type() === 'error') errors.push(m.text());
});

const status = () => page.locator('#funding-status').textContent();
const spendable = () => page.locator('.treasury-tile-primary .wf-stat-value').textContent();

await page.goto(`http://127.0.0.1:${port}`);
await page.locator('#owner-token').fill(token);
await page.locator('#login-form button').click();
await page.locator('#office-canvas').waitFor();
await page.waitForTimeout(1500);
await page.locator('#open-treasury-btn').click();
await page.waitForTimeout(900);

const results = {};
results.startsEmpty = (await spendable()).trim();
results.loanFieldsHiddenForContribution = await page.locator('#funding-loan-fields').isHidden();

// A comma is ambiguous in money and must be refused, not guessed at.
await page.locator('#funding-amount').fill('1,000');
await page.locator('#funding-form button[type=submit]').click();
await page.waitForTimeout(300);
results.refusesComma = await status();

// A loan needs its terms; the form must not let one through without them.
await page.locator('#funding-amount').fill('2000');
await page.selectOption('#funding-type', 'OWNER_LOAN');
await page.waitForTimeout(200);
results.loanFieldsShown = await page.locator('#funding-loan-fields').isVisible();
await page.locator('#funding-rate').fill('7.25');
await page.locator('#funding-form button[type=submit]').click();
await page.waitForTimeout(300);
results.refusesLoanWithoutMaturity = await status();

// The real thing: a loan at 7.25% maturing in 2027.
await page.locator('#funding-maturity').fill('2027-09-30');
await page.locator('#funding-note').fill('Imprumut Owner de test');
await page.locator('#funding-form button[type=submit]').click();
await page.waitForTimeout(1200);
results.loanRecorded = await status();
results.afterLoan = (await spendable()).trim();

// A contribution in euros: the form must demand a rate and a source before it converts anything.
await page.selectOption('#funding-type', 'CAPITAL_CONTRIBUTION');
await page.locator('#funding-amount').fill('500');
await page.locator('#funding-currency').fill('EUR');
await page.waitForTimeout(200);
results.fxFieldsShownForEur = await page.locator('#funding-fx-fields').isVisible();
await page.locator('#funding-form button[type=submit]').click();
await page.waitForTimeout(300);
results.refusesEurWithoutRate = await status();

await page.locator('#funding-fx-rate').fill('1.08');
await page.locator('#funding-form button[type=submit]').click();
await page.waitForTimeout(300);
results.refusesRateWithoutSource = await status();

await page.locator('#funding-fx-source').fill('BNR 10.09.2026');
await page.locator('#funding-form button[type=submit]').click();
await page.waitForTimeout(1500);
results.contributionRecorded = await status();
results.afterContribution = (await spendable()).trim();

results.positions = await page.evaluate(() =>
  [...document.querySelectorAll('#treasury-summary .treasury-tile')].map((tile) => ({
    label: tile.querySelector('.wf-stat-label')?.textContent,
    amount: tile.querySelector('.wf-stat-value')?.textContent,
  })),
);
results.verdict = await page
  .locator('#treasury-summary .runbook-verdict strong')
  .textContent();
results.history = await page.evaluate(() =>
  [...document.querySelectorAll('#funding-history .topic-card')].map((card) => ({
    kind: card.querySelector('.topic-card-title')?.textContent,
    vr: card.querySelector('.topic-card-novelty')?.textContent,
    meta: card.querySelector('.topic-card-meta')?.textContent,
  })),
);

await page.locator('#treasury-modal').screenshot({ path: 'output/playwright/funding-form.png' });
console.log(JSON.stringify({ results, errors }, null, 1));
await browser.close();
