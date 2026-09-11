/** Live browser check. Verifies every connected channel; never starts Google consent.
 * STUDIO_OWNER_TOKEN must be provided through the environment, never a command argument.
 * node scripts/verify_youtube_avatars.mjs http://127.0.0.1:8000
 */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from '../frontend/node_modules/playwright/index.mjs';

const base = process.argv[2];
const token = process.env.STUDIO_OWNER_TOKEN;
assert(base && token, 'Provide the studio URL and STUDIO_OWNER_TOKEN environment variable');
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 1600 } });
  await page.addInitScript(() => {
    window.avatarPolicyViolations = [];
    document.addEventListener('securitypolicyviolation', (event) => {
      if (event.effectiveDirective === 'img-src') {
        window.avatarPolicyViolations.push(event.blockedURI);
      }
    });
  });
  const headers = { Authorization: `Bearer ${token}` };
  const list = async () => {
    const response = await page.request.get(`${base}/api/v1/youtube/connections`, { headers });
    assert.equal(response.status(), 200);
    return (await response.json()).connections;
  };
  const connections = (await list()).filter((row) => row.connected);
  assert(connections.length > 0, 'No live connected channels to verify');
  await page.goto(base);
  await page.locator('#owner-token').fill(token);
  await page.locator('#login-form button').click();
  await page.locator('#open-settings').click();
  await page.getByRole('button', { name: 'Conturi și e-mail' }).click();
  await page.locator('.yt-card').first().waitFor();
  const evidence = [];
  for (const connection of connections) {
    const card = page.locator('.yt-card').filter({
      has: page.getByRole('heading', { name: connection.name, exact: true }),
    });
    const verifiedResponse = page.waitForResponse((response) =>
      response.url().endsWith(`/youtube/connections/${connection.id}/verify`) &&
      response.request().method() === 'POST',
    );
    await card.getByRole('button', { name: 'Verifică', exact: true }).click();
    const verified = await verifiedResponse;
    assert.equal(verified.status(), 200, `Verify failed for ${connection.name}`);
    const fresh = await verified.json();
    const persisted = (await list()).find((row) => row.id === connection.id);
    assert.equal(persisted.channel.thumbnail_url, fresh.channel.thumbnail_url);
    const url = fresh.channel.thumbnail_url;
    await card.waitFor();
    if (url) {
      const avatar = card.locator('img.yt-avatar');
      await avatar.waitFor();
      await page.waitForFunction(({ name, url }) => {
        const row = [...document.querySelectorAll('.yt-card')].find((el) =>
          el.querySelector('.yt-card-name')?.textContent === name,
        );
        const img = row?.querySelector('img.yt-avatar');
        return img?.getAttribute('src') === url && img.complete && img.naturalWidth > 0;
      }, { name: connection.name, url });
      assert.equal(await card.locator('.yt-avatar-fallback').count(), 0);
      evidence.push({ connection: connection.name, channel: fresh.channel.title,
        persisted: true, ...await avatar.evaluate((img) => ({
          url: img.src, width: img.naturalWidth, height: img.naturalHeight,
        })) });
    } else {
      await card.locator('.yt-avatar-fallback').waitFor();
      assert.equal(await card.locator('img.yt-avatar').count(), 0);
      evidence.push({ connection: connection.name, persisted: true, thumbnail: null });
    }
  }
  const violations = await page.evaluate(() => window.avatarPolicyViolations);
  assert.deepEqual(violations, [], 'Image Content-Security-Policy violations');
  await mkdir('output/playwright', { recursive: true });
  await page.locator('.yt-section').screenshot({ path: 'output/playwright/youtube-avatars-live.png' });

  // Browser-only missing-thumbnail fixture. Does not change the real database or live evidence.
  const fixture = await list();
  for (const row of fixture) if (row.channel) row.channel.thumbnail_url = null;
  await page.route('**/api/v1/youtube/connections', (route) => route.fulfill({
    json: { connections: fixture },
  }));
  await page.getByRole('button', { name: 'Adaugă un canal', exact: true }).click();
  await page.locator('.yt-form').waitFor();
  assert.equal(await page.locator('.yt-avatar-fallback').count(),
    fixture.filter((row) => row.channel).length);
  assert.equal(await page.locator('img.yt-avatar').count(), 0);
  const report = { live: evidence, imagePolicyViolations: violations, missingThumbnailFixture: 'passed' };
  await writeFile('output/playwright/youtube-avatars-live.json', JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
} catch (error) {
  // Playwright includes request headers in transport errors. Never print the Owner credential.
  console.error(String(error).replaceAll(token, '[REDACTED]'));
  process.exitCode = 1;
} finally {
  await browser.close();
}
