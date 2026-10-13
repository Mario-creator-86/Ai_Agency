// Visual review of the live headquarters: logs into the running studio with the Owner token from
// .env and captures the office. Review artefact only; it changes nothing in the studio.
//
//   node scripts/shot_hq.mjs --out shot.png [--port 8000] [--panel] [--fullscreen] [--zoom 2 --focus 800,300]
//        [--time 2026-09-13T16:15:00Z] [--event ufo_flyover] [--weather rain] [--wait 3000] [--width 1640 --height 1100]
//
// --time freezes the scene clock (the reference picture is at dusk); --weather feeds the scene a
// weather condition for QA only, in this browser, never to the backend; --event starts a random event.
import { chromium } from '../frontend/node_modules/playwright/index.mjs';
import fs from 'node:fs';

const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, cur, i, all) => {
    if (cur.startsWith('--')) acc.push([cur.slice(2), all[i + 1] && !all[i + 1].startsWith('--') ? all[i + 1] : true]);
    return acc;
  }, []),
);
const out = args.out || 'output/playwright/hq.png';
const port = args.port || '8000';
const token = /STUDIO_OWNER_TOKEN=(\S+)/.exec(fs.readFileSync('.env', 'utf8'))[1];
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: Number(args.width || 1640), height: Number(args.height || 1100) }, deviceScaleFactor: 1 });
const errors = [];
page.on('pageerror', (e) => errors.push(e.message));
page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
await page.goto(`http://127.0.0.1:${port}`);
await page.locator('#owner-token').fill(token);
await page.locator('#login-form button').click();
await page.locator('#office-canvas').waitFor();
await page.waitForFunction(() => window.__studio && window.__studio.engine && window.__studio.engine.world, null, { timeout: 30000 });
if (args.fullscreen) {
  await page.locator('#fullscreen-btn').click();
  await page.waitForTimeout(800);
}
await page.evaluate(async ({ time, weather, event }) => {
  const e = window.__studio.engine;
  const w = e.world;
  if (time) {
    w.time.now = () => new Date(time);
    w.time._elapsed = 1;
    w.time.update(0);
  }
  if (weather) {
    // QA only, in this browser: a first real poll may still be in flight, so wait it out and
    // stop the manager from polling again before the override is applied.
    await new Promise((resolve) => setTimeout(resolve, 1500));
    w.weather._last = Date.now();
    w.weather.fetchWeather = async () => ({ available: true, condition: weather, intensity: 0.8, temperature_c: 14 });
    await w.weather.refresh();
  }
  if (event) w.events.trigger(event);
}, { time: args.time || null, weather: args.weather || null, event: args.event || null });
await page.waitForTimeout(Number(args.wait || 2500));
if (args.zoom) {
  const focus = String(args.focus || '').split(',').map(Number);
  await page.evaluate(({ z, focus }) => {
    const e = window.__studio.engine;
    e.viewport.setZoom(z);
    if (focus.length === 2 && !Number.isNaN(focus[0])) {
      e.viewport.panX = e.canvas.width / 2 - focus[0] * z;
      e.viewport.panY = e.canvas.height / 2 - focus[1] * z;
    }
  }, { z: Number(args.zoom), focus });
  await page.waitForTimeout(400);
}
const target = args.panel ? page.locator('.office-panel') : page.locator('#office-canvas');
await target.screenshot({ path: out });
const stats = await page.evaluate(() => {
  const { engine, state } = window.__studio;
  return {
    agents: state.agents.map((a) => `${a.display_name}:${a.runtime_state}/${a.lifecycle}:${a.desk_id}`),
    fps: engine.fps,
    zoom: engine.viewport.zoom,
    time: engine.world.time.state.text,
    phase: engine.world.time.state.phase,
    weather: engine.world.weather.state.condition,
    vehicles: engine.world.traffic.vehicles.length,
    people: engine.world.pedestrians.people.length,
    events: engine.world.events.active.map((ev) => ev.def.eventId),
    canvas: [engine.canvas.width, engine.canvas.height],
  };
});
console.log(JSON.stringify({ out, errors, ...stats }));
await browser.close();
