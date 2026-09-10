// Renders one department at N x scale with the new room modules, without the backend.
import { chromium } from '../frontend/node_modules/playwright/index.mjs';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
const [,, out = 'output/playwright/room.png', query = 'zone=RESEARCH&scale=4'] = process.argv;
const root = path.resolve('frontend');
const types = { '.html': 'text/html', '.js': 'text/javascript', '.mjs': 'text/javascript', '.css': 'text/css', '.png': 'image/png' };
const server = http.createServer((req, res) => {
  const file = path.join(root, decodeURIComponent(req.url.split('?')[0]));
  if (!file.startsWith(root) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { 'content-type': types[path.extname(file)] || 'application/octet-stream' });
  fs.createReadStream(file).pipe(res);
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const port = server.address().port;
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1800, height: 1000 }, deviceScaleFactor: 1 });
const errors = []; page.on('pageerror', (e) => errors.push(e.message)); page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
await page.goto(`http://127.0.0.1:${port}/dev/room_preview.html?${query}`);
await page.waitForFunction(() => window.__ready === true, null, { timeout: 15000 }).catch(() => {});
await page.locator('#c').screenshot({ path: out });
console.log(JSON.stringify({ out, errors }));
await browser.close(); server.close();
