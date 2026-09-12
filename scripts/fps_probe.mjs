// Measures the office renderer's frame rate in the running studio (fullscreen, fit zoom).
import { chromium } from '../frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';
const token = /STUDIO_OWNER_TOKEN=(\S+)/.exec(fs.readFileSync('.env', 'utf8'))[1];
// The GPU flags make headless Chromium draw with the graphics card, as the Owner's browser does;
// without them it falls back to software rendering and measures the CPU instead.
const browser = await chromium.launch({ headless: true, args: ['--enable-gpu', '--ignore-gpu-blocklist', '--use-angle=d3d11', '--enable-gpu-rasterization'] });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
await page.goto('http://127.0.0.1:8000');
await page.locator('#owner-token').fill(token);
await page.locator('#login-form button').click();
await page.locator('#office-canvas').waitFor();
await page.waitForTimeout(2000);
await page.locator('#fullscreen-btn').click();
await page.waitForTimeout(500);
const result = await page.evaluate(async () => {
  const e = window.__studio.engine;
  const samples = [];
  for (const zoom of [e.viewport.zoom, 2.2]) {
    e.viewport.setZoom(zoom);
    let frames = 0; const t0 = performance.now();
    const drawTimes = [];
    const origDraw = e._draw.bind(e);
    e._draw = () => { const s = performance.now(); origDraw(); drawTimes.push(performance.now() - s); };
    await new Promise((r) => { const tick = () => { frames += 1; if (performance.now() - t0 < 2000) requestAnimationFrame(tick); else r(); }; requestAnimationFrame(tick); });
    e._draw = origDraw;
    drawTimes.sort((a, b) => a - b);
    samples.push({ zoom, fps: Math.round(frames / 2), drawMedianMs: drawTimes[Math.floor(drawTimes.length / 2)].toFixed(2), drawP95Ms: drawTimes[Math.floor(drawTimes.length * 0.95)].toFixed(2) });
  }
  return samples;
});
const renderer = await page.evaluate(() => {
  const gl = document.createElement('canvas').getContext('webgl');
  const info = gl && gl.getExtension('WEBGL_debug_renderer_info');
  return info ? gl.getParameter(info.UNMASKED_RENDERER_WEBGL) : 'no webgl';
});
console.log(JSON.stringify({ renderer, samples: result }));
await browser.close();
