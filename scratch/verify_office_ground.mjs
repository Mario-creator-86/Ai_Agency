/** Capture the office so the ground floor and the lift can be inspected as rendered. */
import pw from '../frontend/node_modules/playwright/index.js';
import { readFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';

const { chromium } = pw;
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const OUT = path.join(ROOT, 'output', 'playwright');
mkdirSync(OUT, { recursive: true });
const token = readFileSync(path.join(ROOT, '.env'), 'utf8')
  .split('\n').find((l) => l.startsWith('STUDIO_OWNER_TOKEN=')).split('=')[1].trim();

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
await page.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle' });
await page.fill('#owner-token', token);
await page.click('#login-form button[type="submit"]');
await page.waitForSelector('#studio-name');
await page.waitForTimeout(2500);

const canvas = await page.$('#office-canvas');
await canvas.screenshot({ path: path.join(OUT, 'office-full.png') });

// Zoom into the ground floor: the double-height volume is the bottom quarter of the world.
const box = await canvas.boundingBox();
await page.screenshot({
  path: path.join(OUT, 'office-ground-floor.png'),
  clip: { x: box.x, y: box.y + box.height * 0.55, width: box.width, height: box.height * 0.45 },
});

console.log(errors.length ? `PAGE ERRORS: ${errors.join(' | ')}` : 'no page errors');
await browser.close();
