// Local visual review helper: logs into the running studio with the Owner token from .env
// and screenshots the 2D office. Review artifact only; no backend or provider calls.
import { chromium } from '../frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
const out = process.argv[2] || 'output/playwright/office-now.png';
const port = process.argv[3] || '8000';
const zoom = parseFloat(process.argv[4] || '0'); // 0 = fit
const env = fs.readFileSync('.env', 'utf8');
const token = /STUDIO_OWNER_TOKEN=(\S+)/.exec(env)[1];
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 }, deviceScaleFactor: 1 });
const errors = []; page.on('pageerror', e => errors.push(e.message));
await page.goto(`http://127.0.0.1:${port}`);
await page.locator('#owner-token').fill(token);
await page.locator('#login-form button').click();
await page.locator('#office-canvas').waitFor();
await page.waitForTimeout(2500);
await page.locator('#fullscreen-btn').click();
await page.waitForTimeout(800);
if (zoom > 0) {
  const focus = (process.argv[5] || '').split(',').map(Number);
  await page.evaluate(({ z, focus }) => {
    const e = window.__studio.engine; e.viewport.setZoom(z);
    if (focus.length === 2 && !Number.isNaN(focus[0])) {
      e.viewport.panX = e.canvas.width / 2 - focus[0] * z; e.viewport.panY = e.canvas.height / 2 - focus[1] * z;
    }
  }, { z: zoom, focus });
  await page.waitForTimeout(300);
}
await page.locator('#office-canvas').screenshot({ path: out });
const stats = await page.evaluate(() => {
  const { engine, state } = window.__studio;
  return { agents: state.agents.length, world: [engine.worldW, engine.worldH], zoom: engine.viewport.zoom };
});
console.log(JSON.stringify({ out, errors, ...stats }));
await browser.close();
