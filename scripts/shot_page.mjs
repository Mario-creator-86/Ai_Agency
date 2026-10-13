// Screenshots the whole workspace page (admin panels + embedded scene) at desktop and mobile widths.
import { chromium } from '../frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
const token = /STUDIO_OWNER_TOKEN=(\S+)/.exec(fs.readFileSync('.env', 'utf8'))[1];
const browser = await chromium.launch({ headless: true });
for (const [name, vw, vh] of [['desktop', 1600, 1100], ['mobile', 390, 844]]) {
  const page = await browser.newPage({ viewport: { width: vw, height: vh } });
  const errors = []; page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('http://127.0.0.1:8000');
  await page.locator('#owner-token').fill(token);
  await page.locator('#login-form button').click();
  await page.locator('#office-canvas').waitFor();
  await page.waitForTimeout(2200);
  await page.screenshot({ path: `output/playwright/page-${name}.png`, fullPage: name === 'mobile' });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
  console.log(JSON.stringify({ name, errors, overflow }));
  await page.close();
}
await browser.close();
