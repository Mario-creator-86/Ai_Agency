/**
 * Design verification: colour consistency, contrast and the absence of stray icons.
 *
 * It reads computed styles from the running page rather than the stylesheet source, so it
 * checks what a viewer actually sees.
 */
import pw from '../frontend/node_modules/playwright/index.js';
import { readFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';

const { chromium } = pw;
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..');
const BASE = 'http://127.0.0.1:8000';
const OUT = path.join(ROOT, 'output', 'playwright');
mkdirSync(OUT, { recursive: true });

const token = readFileSync(path.join(ROOT, '.env'), 'utf8')
  .split('\n')
  .find((l) => l.startsWith('STUDIO_OWNER_TOKEN='))
  .split('=')[1]
  .trim();

const results = [];
function check(name, ok, detail = '') {
  results.push({ name, ok: Boolean(ok) });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`);
}

// --- WCAG relative luminance / contrast -------------------------------------------------
function srgbToLinear(c) {
  const v = c / 255;
  return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
}
function luminance([r, g, b]) {
  return 0.2126 * srgbToLinear(r) + 0.7152 * srgbToLinear(g) + 0.0722 * srgbToLinear(b);
}
function parseRGB(s) {
  const m = s.match(/rgba?\(([^)]+)\)/);
  if (!m) return null;
  const parts = m[1].split(/[,\s/]+/).filter(Boolean).map(Number);
  return parts.slice(0, 3);
}
function contrast(fg, bg) {
  const l1 = luminance(fg);
  const l2 = luminance(bg);
  const [hi, lo] = l1 > l2 ? [l1, l2] : [l2, l1];
  return (hi + 0.05) / (lo + 0.05);
}

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
const page = await browser.newPage({ viewport: { width: 1440, height: 940 } });
const consoleErrors = [];
page.on('console', (m) => m.type() === 'error' && consoleErrors.push(m.text()));
page.on('pageerror', (e) => consoleErrors.push(String(e)));

await page.goto(BASE, { waitUntil: 'networkidle' });
await page.fill('#owner-token', token);
await page.click('#login-form button[type="submit"]');
await page.waitForSelector('#studio-name');
await page.waitForTimeout(1200);

// --- 1. No stray pictographic icons anywhere in the rendered UI -------------------------
const pictographs = await page.evaluate(() => {
  const re = /[\u{1F000}-\u{1FAFF}\u{2B00}-\u{2BFF}\u{1F300}-\u{1F5FF}]/gu;
  const found = new Set();
  const walk = (node) => {
    if (node.nodeType === 3) (node.textContent.match(re) || []).forEach((c) => found.add(c));
    else node.childNodes.forEach(walk);
  };
  walk(document.body);
  return [...found];
});
check('No pictographic emoji in the rendered interface', pictographs.length === 0, pictographs.join(' '));

// --- 2. Every dialog uses the paper surface, not a foreign dark theme -------------------
const dialogIds = ['research-modal', 'media-modal', 'publishing-modal'];
const openers = {
  'research-modal': '#open-research-btn',
  'media-modal': '#open-media-btn',
  'publishing-modal': '#open-publishing-btn',
};

const surfaces = [];
for (const id of dialogIds) {
  await page.click(openers[id]);
  await page.waitForSelector(`#${id}[open]`);
  await page.waitForTimeout(900);
  const info = await page.evaluate((sel) => {
    const el = document.getElementById(sel);
    const cs = getComputedStyle(el);
    return { bg: cs.backgroundColor, fg: cs.color, border: cs.borderTopColor };
  }, id);
  surfaces.push({ id, ...info });
  await page.screenshot({ path: path.join(OUT, `design-${id}.png`) });
  await page.keyboard.press('Escape');
  await page.waitForTimeout(400);
}

const panelBg = await page.evaluate(() => getComputedStyle(document.querySelector('.panel')).backgroundColor);
check(
  'All dialogs share the page surface colour',
  surfaces.every((s) => s.bg === panelBg),
  surfaces.map((s) => `${s.id}=${s.bg}`).join(' '),
);

// --- 3. Contrast of the main text pairings ---------------------------------------------
await page.click('#open-publishing-btn');
await page.waitForSelector('#publishing-modal[open]');
await page.waitForFunction(() => !document.querySelector('#channels-list')?.textContent.includes('Se încarcă'));
await page.waitForTimeout(600);

const samples = await page.evaluate(() => {
  const pick = (sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    let node = el;
    let bg = cs.backgroundColor;
    while (node && (bg === 'rgba(0, 0, 0, 0)' || bg === 'transparent')) {
      node = node.parentElement;
      if (!node) break;
      bg = getComputedStyle(node).backgroundColor;
    }
    return { sel, fg: cs.color, bg, size: parseFloat(cs.fontSize) };
  };
  return [
    '.dialog-title',
    '.dialog-desc',
    '.pub-gate-list',
    '.channel-meta',
    '.channel-status-warn',
    '.pub-quick-info',
    '.pub-gate-note',
    '.btn-pub-action',
  ].map(pick).filter(Boolean);
});

let worst = { ratio: 99, sel: '' };
for (const s of samples) {
  const fg = parseRGB(s.fg);
  const bg = parseRGB(s.bg);
  if (!fg || !bg) continue;
  const ratio = contrast(fg, bg);
  const large = s.size >= 18.66;
  const min = large ? 3 : 4.5;
  if (ratio < worst.ratio) worst = { ratio, sel: s.sel };
  check(`Contrast ${s.sel} ≥ ${min}:1`, ratio >= min, `${ratio.toFixed(2)}:1 at ${s.size}px`);
}

await page.screenshot({ path: path.join(OUT, 'design-publishing-hub.png') });

// --- 4. Status colours remain semantically distinct -------------------------------------
const statusColors = await page.evaluate(() => {
  const probe = (cls) => {
    const el = document.createElement('span');
    el.className = cls;
    document.body.appendChild(el);
    const cs = getComputedStyle(el);
    const out = { bg: cs.backgroundColor, fg: cs.color };
    el.remove();
    return out;
  };
  return {
    ok: probe('pub-status-badge pub-status-published'),
    warn: probe('pub-status-badge pub-status-simulated'),
    bad: probe('pub-status-badge pub-status-blocked'),
  };
});
const distinct = new Set(Object.values(statusColors).map((c) => c.fg)).size === 3;
check('Published / simulated / blocked stay visually distinct', distinct, JSON.stringify(statusColors));

// --- 5. Office frame ties into the palette ---------------------------------------------
const frame = await page.evaluate(() => {
  const el = document.querySelector('.office-scene-container');
  const cs = getComputedStyle(el);
  return { border: cs.borderTopColor, side: cs.borderLeftColor };
});
check('2D office is framed in the studio palette', frame.border !== 'rgba(0, 0, 0, 0)', JSON.stringify(frame));

// --- 6. Mobile ---------------------------------------------------------------------------
await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(600);
const overflow = await page.evaluate(
  () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
);
check('No horizontal overflow at 390px', !overflow);
await page.screenshot({ path: path.join(OUT, 'design-mobile.png'), fullPage: false });

check('No console errors', consoleErrors.length === 0, consoleErrors.join(' | ').slice(0, 200));

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed (worst contrast ${worst.ratio.toFixed(2)}:1 on ${worst.sel})`);
if (failed.length) process.exit(1);
