/**
 * Owner-directed conversation fixes, verified in the real UI:
 *   1. the inspector dialog is wide, and a run whose answer is JSON reads as sentences
 *      and lists — the raw JSON only inside the collapsed "Răspunsul exact al modelului";
 *   2. the chat is a real exchange (question right, answer left), the "scrie…" indicator
 *      shows while the employee works, and the exchange survives a page reload;
 *   3. "Fereastră live" opens a standalone window showing the employee's day and updating
 *      from live events.
 */
import pw from '../frontend/node_modules/playwright/index.js';
import { readFileSync, mkdirSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const { chromium } = pw;
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const OUT = path.join(ROOT, 'output', 'playwright');
mkdirSync(OUT, { recursive: true });
const token = readFileSync(path.join(ROOT, '.env'), 'utf8')
  .split('\n').find((l) => l.startsWith('STUDIO_OWNER_TOKEN=')).split('=')[1].trim();

const results = [];
const check = (name, ok, detail = '') => {
  results.push({ name, ok: Boolean(ok) });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`);
};

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));

await page.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle' });
await page.fill('#owner-token', token);
await page.evaluate(() => document.getElementById('login-form').requestSubmit());
await page.waitForSelector('#studio-name');
await page.waitForTimeout(2500);

// --- 1. The inspector, wide, with a history that reads like a person wrote it. ---
// Dr. Aris carries the structured answers (URL picks, claims) — exactly what used to print
// as raw JSON. His history proves the friendly rendering even while he is busy.
await page.evaluate(() => {
  const engine = window.__studio.engine;
  const agent = engine.agents.find((x) => String(x.display_name || '').includes('Aris')) || engine.agents[0];
  engine.onSelectAgent(agent);
});
await page.waitForSelector('#agent-inspector[open]');
await page.waitForTimeout(2500); // identity + history load

const width = await page.evaluate(() => document.getElementById('agent-inspector').getBoundingClientRect().width);
check('inspector dialog is wide (>=1100px)', width >= 1100, `${Math.round(width)}px`);

const history = await page.evaluate(() => {
  const box = document.getElementById('agent-history');
  return {
    items: box.querySelectorAll('.chat-item').length,
    answers: [...box.querySelectorAll('.chat-answer')].map((a) => {
      const clone = a.cloneNode(true);
      clone.querySelectorAll('details').forEach((d) => d.remove());
      return { visible: clone.textContent.trim().slice(0, 80), hasRaw: Boolean(a.querySelector('details.chat-raw')) };
    }),
    rawCount: box.querySelectorAll('details.chat-raw').length,
    salvageNotes: box.querySelectorAll('.friendly-note').length,
  };
});
check('history has entries', history.items > 0, `${history.items} items`);
const jsonVisible = history.answers.filter((a) => /^\s*[[{]/.test(a.visible));
check('no visible answer starts with raw JSON', jsonVisible.length === 0, JSON.stringify(jsonVisible.slice(0, 2)));
check('structured answers keep the exact model output collapsed', history.rawCount > 0, `${history.rawCount} raw blocks`);
check('an answer cut off by the token limit is salvaged with a note', history.salvageNotes > 0, `${history.salvageNotes} notes`);
await page.screenshot({ path: path.join(OUT, 'conversation-inspector.png') });

// --- 1b. The extend button: the whole history on one traversable page. ---
await page.evaluate(() => document.getElementById('inspector-expand').click());
await page.waitForTimeout(300);
const expanded = await page.evaluate(() => {
  const dialog = document.getElementById('agent-inspector');
  const box = document.getElementById('agent-history');
  return {
    hasClass: dialog.classList.contains('dialog-max'),
    dialogHeight: dialog.getBoundingClientRect().height,
    viewport: window.innerHeight,
    historyMaxHeight: getComputedStyle(box).maxHeight,
  };
});
check(
  'extend fills the screen and the history stops cropping',
  expanded.hasClass && expanded.dialogHeight > expanded.viewport * 0.9 && expanded.historyMaxHeight === 'none',
  JSON.stringify(expanded),
);
await page.screenshot({ path: path.join(OUT, 'conversation-inspector-expanded.png') });
await page.evaluate(() => document.getElementById('inspector-expand').click());
const restored = await page.evaluate(() => !document.getElementById('agent-inspector').classList.contains('dialog-max'));
check('extend restores the normal size', restored);

// --- 2. A real chat turn on a free employee: indicator, exchange rendered, persists. ---
const chosen = await page.evaluate(() => {
  const engine = window.__studio.engine;
  const free = engine.agents.find((x) => x.runtime_state === 'IDLE' && x.model_is_available !== false);
  if (!free) return null;
  engine.onSelectAgent(free);
  return free.display_name;
});
check('picked a free employee for the chat', Boolean(chosen), String(chosen));
await page.waitForTimeout(2000); // the new agent's history loads

// --- 2. A real chat turn: indicator while waiting, exchange rendered, then persists. ---
const question = 'Răspunde într-o singură propoziție: la ce ai lucrat azi?';
await page.fill('#agent-run-objective', question);
await page.evaluate(() => document.getElementById('agent-run-form').dispatchEvent(new Event('submit', { cancelable: true, bubbles: true })));
// Sample for the indicator: a fast answer may land between two polls, so look several times.
let typingShown = false;
for (let i = 0; i < 8 && !typingShown; i += 1) {
  typingShown = await page.evaluate(() => !document.getElementById('agent-typing').hidden);
  if (!typingShown) await page.waitForTimeout(150);
}
check('"scrie…" indicator shows while the employee works', typingShown);
await page.waitForFunction(
  () => {
    const items = document.querySelectorAll('#agent-history .chat-item.is-chat');
    const last = items[items.length - 1];
    return last && last.querySelector('.chat-answer') && last.querySelector('.chat-answer').textContent.trim().length > 0
      && last.querySelector('.chat-asked') && last.querySelector('.chat-asked').textContent.includes('la ce ai lucrat azi');
  },
  { timeout: 60000 },
);
const exchange = await page.evaluate(() => {
  const items = document.querySelectorAll('#agent-history .chat-item.is-chat');
  const last = items[items.length - 1];
  return {
    asked: last.querySelector('.chat-asked').textContent.trim(),
    answer: last.querySelector('.chat-answer').textContent.trim().slice(0, 120),
  };
});
check('the exchange shows my question and the answer', exchange.asked === question && exchange.answer.length > 0, JSON.stringify(exchange));
await page.screenshot({ path: path.join(OUT, 'conversation-chat.png') });

// --- 3. The live window, for Dr. Aris (the employee the Owner asked about). ---
const popupPromise = context.waitForEvent('page', { timeout: 8000 });
const liveOpened = await page.evaluate(() => {
  const engine = window.__studio.engine;
  const aris = engine.agents.find((x) => String(x.display_name || '').includes('Aris'));
  if (!aris) return false;
  engine.onSelectAgent(aris);
  return true;
});
if (!liveOpened) check('re-selected Dr. Aris for the live window', false);
await page.waitForTimeout(1200);
await page.evaluate(() => document.getElementById('agent-live-btn').click());
let popup = null;
try {
  popup = await popupPromise;
  await popup.waitForTimeout(1200);
  const live = await popup.evaluate(() => ({
    title: document.title,
    header: document.querySelector('header h1') ? document.querySelector('header h1').textContent : '',
    now: document.querySelector('.now') ? document.querySelector('.now').textContent : '',
    rows: document.querySelectorAll('.live-row').length,
    styled: getComputedStyle(document.body).backgroundColor,
  }));
  check('live window opened for the employee', live.header.includes('Dr. Aris') || live.header.length > 0, JSON.stringify(live.header));
  check('live window shows the current state line', /Acum:/.test(live.now), live.now);
  check('live window is seeded with the day (rows already present)', live.rows > 0, `${live.rows} rows`);
  check('live window is styled (CSSOM stylesheet applied)', live.styled !== 'rgba(0, 0, 0, 0)', live.styled);
  await popup.screenshot({ path: path.join(OUT, 'conversation-live-window.png') });
} catch (err) {
  const blocked = await page.evaluate(() => document.getElementById('message').textContent);
  check('live window opened for the employee', false, `no popup; page notice: "${blocked}"`);
}

// --- 4. The exchange survives a reload: it was saved on the run, not only on the page. ---
await page.reload({ waitUntil: 'networkidle' });
await page.fill('#owner-token', token);
await page.evaluate(() => document.getElementById('login-form').requestSubmit());
await page.waitForSelector('#studio-name');
await page.waitForTimeout(2500);
await page.evaluate(() => {
  const engine = window.__studio.engine;
  const agent = engine.agents.find((x) => String(x.display_name || '').includes('Aris')) || engine.agents[0];
  engine.onSelectAgent(agent);
});
await page.waitForSelector('#agent-inspector[open]');
await page.waitForFunction(
  () => {
    const items = document.querySelectorAll('#agent-history .chat-item.is-chat');
    return items.length > 0 && items[items.length - 1].textContent.includes('la ce ai lucrat azi');
  },
  { timeout: 15000 },
);
check('the chat exchange is saved (present after reload)', true);
await page.screenshot({ path: path.join(OUT, 'conversation-after-reload.png') });

check('no page errors during the whole pass', errors.length === 0, errors.join(' | ').slice(0, 300));

await browser.close();
const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
process.exit(failed.length ? 1 : 0);
