/**
 * Fullscreen round-trip and toolbar state.
 *
 * Regression guards:
 *  - the office canvas must return to its original size after leaving fullscreen;
 *  - a toolbar button is highlighted only while its own panel is open.
 */
import pw from '../frontend/node_modules/playwright/index.js';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const { chromium } = pw;
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const token = readFileSync(path.join(ROOT, '.env'), 'utf8')
  .split('\n').find((l) => l.startsWith('STUDIO_OWNER_TOKEN=')).split('=')[1].trim();

const results = [];
const check = (name, ok, detail = '') => {
  results.push({ name, ok: Boolean(ok) });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`);
};

const browser = await chromium.launch({
  executablePath: '/opt/pw-browsers/chromium',
  args: ['--auto-accept-this-tab-capture'],
});
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));

await page.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle' });
await page.fill('#owner-token', token);
await page.click('#login-form button[type="submit"]');
await page.waitForSelector('#studio-name');
await page.waitForTimeout(1200);

const measure = () => page.evaluate(() => {
  const c = document.querySelector('.office-canvas');
  const box = c.getBoundingClientRect();
  return {
    cssW: Math.round(box.width), cssH: Math.round(box.height),
    attrW: c.width, attrH: c.height,
    containerH: Math.round(document.querySelector('.office-scene-container').getBoundingClientRect().height),
  };
});

const before = await measure();
check('Canvas starts at a bounded height', before.cssH > 300 && before.cssH < 700, JSON.stringify(before));

// Enter fullscreen (the fallback class path is what runs when the API is unavailable headless).
await page.click('#fullscreen-btn');
await page.waitForTimeout(700);
const during = await measure();
check('Fullscreen enlarges the canvas', during.cssH > before.cssH, JSON.stringify(during));

await page.click('#exit-fullscreen-btn');
await page.waitForTimeout(900);
const after = await measure();
check(
  'Canvas returns to its original size after leaving fullscreen',
  Math.abs(after.cssH - before.cssH) <= 2 && Math.abs(after.cssW - before.cssW) <= 2,
  `before=${before.cssW}x${before.cssH} after=${after.cssW}x${after.cssH}`,
);
check(
  'Canvas backing store follows the element back down',
  Math.abs(after.attrH - before.attrH) <= 2,
  `before=${before.attrH} after=${after.attrH}`,
);

// Toolbar highlight
const activeOf = () => page.evaluate(() =>
  ['open-research-btn', 'open-media-btn', 'open-publishing-btn']
    .filter((id) => document.getElementById(id).classList.contains('cam-btn-active')));

check('No toolbar button is highlighted when every panel is closed', (await activeOf()).length === 0, JSON.stringify(await activeOf()));

await page.click('#open-research-btn');
await page.waitForSelector('#research-modal[open]');
await page.waitForTimeout(400);
check('Only the open panel is highlighted', JSON.stringify(await activeOf()) === JSON.stringify(['open-research-btn']), JSON.stringify(await activeOf()));

await page.click('#close-research-btn');
await page.waitForTimeout(400);
check('Highlight clears when the panel closes', (await activeOf()).length === 0, JSON.stringify(await activeOf()));

await page.click('#open-media-btn');
await page.waitForSelector('#media-modal[open]');
await page.waitForTimeout(400);
check('Highlight follows to another panel', JSON.stringify(await activeOf()) === JSON.stringify(['open-media-btn']), JSON.stringify(await activeOf()));
await page.keyboard.press('Escape');
await page.waitForTimeout(500);
check('Escape also clears the highlight', (await activeOf()).length === 0, JSON.stringify(await activeOf()));

check('No page errors', errors.length === 0, errors.join(' | '));

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) process.exit(1);
