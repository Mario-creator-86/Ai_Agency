/**
 * Drive the daily-run panel in a real browser against an isolated studio.
 *
 * What is asserted comes from what the page renders, not from the API: the schedule block names
 * the daily job, says whether it is active, and the toggle flips it through the same route the
 * Owner would use. The run the worker fired on its own must be listed.
 *
 *   node scripts/verify_runbook_ui.mjs <port> <owner-token>
 */
import { chromium } from '../frontend/node_modules/playwright/index.mjs';

const [port, token] = process.argv.slice(2);
if (!port || !token) throw new Error('usage: verify_runbook_ui.mjs <port> <owner-token>');

const browser = await chromium.launch({ headless: true });
const page = await (await browser.newContext({ viewport: { width: 1200, height: 1100 } })).newPage();
const problems = [];
page.on('pageerror', (error) => problems.push(`pageerror: ${error.message}`));

await page.goto(`http://127.0.0.1:${port}`);
await page.locator('#owner-token').fill(token);
await page.locator('#login-form button').click();
await page.locator('#open-runbook-btn').click();
await page.locator('#toggle-daily-job-btn').waitFor();

const before = await page.evaluate(() => ({
  schedule: document.querySelector('#runbook-schedule')?.innerText ?? '',
  button: document.querySelector('#toggle-daily-job-btn')?.textContent ?? '',
  runs: document.querySelectorAll('.runbook-run').length,
}));
if (!before.schedule.includes('daily_main')) problems.push('the schedule block does not name the daily job');
if (before.runs < 1) problems.push('the run the worker fired is not listed');
await page.locator('#runbook-modal').screenshot({ path: 'output/playwright/runbook-schedule.png' });

// The job was activated by the demo; stopping it from the panel must flip the label and stick.
await page.locator('#toggle-daily-job-btn').click();
await page.waitForFunction(
  () => document.querySelector('#toggle-daily-job-btn')?.textContent?.includes('Pornește'),
  null,
  { timeout: 10000 },
);
const after = await page.evaluate(() => ({
  schedule: document.querySelector('#runbook-schedule')?.innerText ?? '',
  button: document.querySelector('#toggle-daily-job-btn')?.textContent ?? '',
}));
if (!after.schedule.includes('Programarea este oprită')) {
  problems.push('after stopping, the panel does not say the schedule is stopped');
}
await page.locator('#runbook-schedule').screenshot({ path: 'output/playwright/runbook-schedule-stopped.png' });

console.log(JSON.stringify({ before, after, problems }, null, 1));
await browser.close();
if (problems.length) process.exitCode = 1;
