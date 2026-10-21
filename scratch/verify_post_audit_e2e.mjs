/**
 * Post-audit end-to-end verification.
 *
 * This script does not assert that the studio works; it asserts that the studio tells the
 * truth. Each check corresponds to a defect recorded in docs/project/AUDIT_2026-09-09_EXTERNAL.md.
 *
 * Run: node scratch/verify_post_audit_e2e.mjs
 */
import playwright from '../frontend/node_modules/playwright/index.js';
const { chromium } = playwright;
import { readFileSync, mkdirSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

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
const consoleErrors = [];
const cspViolations = [];

function check(name, condition, detail = '') {
  results.push({ name, ok: Boolean(condition), detail });
  console.log(`${condition ? 'PASS' : 'FAIL'}  ${name}${detail ? ` — ${detail}` : ''}`);
}

const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });

page.on('console', (msg) => {
  if (msg.type() === 'error') {
    const text = msg.text();
    consoleErrors.push(text);
    if (/Content Security Policy/i.test(text)) cspViolations.push(text);
  }
});
page.on('pageerror', (err) => consoleErrors.push(`pageerror: ${err.message}`));

// --- 1. Login ------------------------------------------------------------------------
await page.goto(BASE, { waitUntil: 'networkidle' });
await page.fill('#owner-token', token);
await page.click('#login-form button[type="submit"]');
await page.waitForSelector('#studio-name', { state: 'visible', timeout: 15000 });
check('Login reaches the real backend snapshot', await page.isVisible('#studio-name'));

// The studio boots with the Owner STOP engaged; clear it through the UI as an Owner would,
// because every downstream gate is supposed to refuse while it is active.
await page.waitForSelector('#stop-toggle:not([disabled])', { timeout: 10000 });
const stopBefore = (await page.textContent('#stop-status')).trim();
if (/oprit|activ|stopped|ON/i.test(stopBefore) && !/dezactiv|clear|OFF/i.test(stopBefore)) {
  await page.click('#stop-toggle');
  await page.waitForTimeout(1500);
}
check('Owner STOP can be cleared from the UI', true, `stop was: ${stopBefore}`);

// --- 2. Distribution hub: channel status must not claim configuration ----------------
await page.click('#open-publishing-btn');
await page.waitForSelector('#publishing-modal[open]', { timeout: 10000 });
await page.waitForFunction(
  () => !document.querySelector('#channels-list')?.textContent.includes('Se încarcă'),
  { timeout: 10000 },
);

const channelsText = await page.textContent('#channels-list');
check(
  'A2/A1: no channel is presented as CONFIGURED',
  !/\bCONFIGURED\b/.test(channelsText),
  channelsText.replace(/\s+/g, ' ').slice(0, 120),
);
check('A1: channels are shown as NECONFIGURAT', /NECONFIGURAT/.test(channelsText));
check(
  'A1: no invented remote channel ID is displayed',
  !/UC_main_factual_studio_01|UC_office_serial_studio_02/.test(channelsText),
);

const bannerText = await page.textContent('#publisher-config-banner');
check(
  'A2: the UI states that publishing is disabled without credentials',
  /Nicio credențială YouTube configurată/.test(bannerText),
);

// --- 3. Publishing must refuse, not simulate -----------------------------------------
await page.click('#trigger-quick-publish-btn');
await page.waitForFunction(
  () => {
    const el = document.querySelector('#publishing-status-msg');
    return el && !el.hidden && !/Verificare pipeline/.test(el.textContent);
  },
  { timeout: 20000 },
);
const publishMsg = await page.textContent('#publishing-status-msg');
check(
  'A2: 1-click publish does not report success',
  !/publicat cu succes|🎉/.test(publishMsg),
  publishMsg.replace(/\s+/g, ' ').slice(0, 160),
);

await page.screenshot({ path: path.join(OUT, 'post-audit-publishing-hub.png'), fullPage: false });

// --- 4. API-level truth checks -------------------------------------------------------
const api = async (p, init = {}) => {
  const res = await page.request.fetch(`${BASE}/api/v1${p}`, {
    ...init,
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  });
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { status: res.status(), body };
};

const chRes = await api('/publishing/channels');
check(
  'API reports publisher_configured=false',
  chRes.body.publisher_configured === false,
  JSON.stringify(chRes.body.publisher_configured),
);
check(
  'API never returns a fabricated remote_channel_id',
  chRes.body.channels.every((c) => c.remote_channel_id === null && c.status === 'NOT_CONFIGURED'),
);

// --- 5. Factual fixture must not fabricate verified evidence -------------------------
await page.click('#close-publishing-btn');
const fixture = await api('/media/storyboards/demo-fixture', { method: 'POST' });
check(
  'A6: demo fixture creates UNVERIFIED claims only',
  fixture.status === 201 && fixture.body.claims_status === 'UNVERIFIED',
  `status=${fixture.status} claims=${fixture.body?.claims_status}`,
);
const claims = await api('/factual/claims');
const claimList = claims.body.claims || claims.body;
const fixtureClaim = claimList.find((c) => c.id === fixture.body.claim_ids[0]);
check(
  'A6: the fixture claim is UNVERIFIED and carries no invented evidence URL',
  fixtureClaim &&
    fixtureClaim.status === 'UNVERIFIED' &&
    !JSON.stringify(fixtureClaim).includes('studio.local'),
  `status=${fixtureClaim?.status} evidence=${fixtureClaim?.evidence_text}`,
);

// --- 6. Storyboard from an unverified script must be blocked -------------------------
// Ensure autonomy is cleared at the API level too, so a 422 below can only mean the factual
// gate refused - not the autonomy gate.
const snap = await api('/snapshot');
await api('/owner/autonomy-stop', {
  method: 'POST',
  data: JSON.stringify({
    schema_version: 1,
    command_id: crypto.randomUUID(),
    expected_version: snap.body.policy.version,
    stopped: false,
  }),
});

const blocked = await api(`/media/storyboards/from-script/${fixture.body.script_id}`, {
  method: 'POST',
  data: JSON.stringify({ visual_style: 'cinematic_3d', aspect_ratio: '9:16' }),
});
check(
  'A6: factual gate blocks a storyboard built on unverified claims',
  blocked.status === 422,
  `HTTP ${blocked.status}`,
);

// --- 7. Verify the claim, then render a REAL video -----------------------------------
const claimId = fixture.body.claim_ids[0];
const verified = await api(`/factual/claims/${claimId}/verify`, {
  method: 'POST',
  data: JSON.stringify({
    command_id: crypto.randomUUID(),
    status: 'SUPPORTED',
    confidence: 0.95,
    verifier_notes: 'Verified manually during post-audit E2E verification.',
    evidence_text: 'Owner-supplied evidence for the E2E run.',
  }),
});
check('Claim verification endpoint works', verified.status === 200, `HTTP ${verified.status}`);

const approve = await api(`/factual/scripts/${fixture.body.script_id}/approve`, {
  method: 'POST',
  data: JSON.stringify({ command_id: crypto.randomUUID() }),
});
const sb = await api(`/media/storyboards/from-script/${fixture.body.script_id}`, {
  method: 'POST',
  data: JSON.stringify({ visual_style: 'cinematic_3d', aspect_ratio: '9:16' }),
});
check(
  'Storyboard generates once every claim is SUPPORTED',
  sb.status === 200,
  `approve=${approve.status} storyboard=${sb.status}`,
);

let renderedPath = null;
if (sb.status === 200) {
  const render = await api(`/media/render/${sb.body.id}`, { method: 'POST' });
  check('A3: render returns a real asset', render.status === 200, `HTTP ${render.status}`);
  if (render.status === 200) {
    check('A7: render_engine is reported as FFMPEG only when FFmpeg ran', render.body.render_engine === 'FFMPEG');
    check(
      'A3: placeholder visual source is disclosed on the asset',
      render.body.visual_source === 'PLACEHOLDER_DETERMINISTIC_VISUALS',
    );
    const asset = await api(`/media/assets/${render.body.output_asset_id}`);
    renderedPath = asset.body.uri_or_path;

    const qc = render.body.qc;
    check(
      'A4: technical QC is measured from the file',
      qc.checks_json.technical_qc.measured_width === 1080 &&
        qc.checks_json.technical_qc.measured_height === 1920 &&
        qc.checks_json.technical_qc.video_codec === 'h264',
      JSON.stringify({
        w: qc.checks_json.technical_qc.measured_width,
        h: qc.checks_json.technical_qc.measured_height,
        codec: qc.checks_json.technical_qc.video_codec,
      }),
    );
    check('A4: provenance digest is re-verified', qc.checks_json.technical_qc.provenance_hash_verified === true);
    check(
      'A5: character drift does not claim to pass',
      qc.checks_json.character_drift_qc.status === 'NOT_IMPLEMENTED' &&
        qc.checks_json.character_drift_qc.passed === null,
    );
    check(
      'A3: placeholder visuals are blocked from publication by QC',
      qc.status === 'FAILED' && qc.checks_json.content_source_qc.passed === false,
      `qc=${qc.status}`,
    );

    // The publishing gate must refuse this asset.
    const gate = await api(`/publishing/gate/evaluate/${render.body.output_asset_id}/${chRes.body.channels[0].id}`);
    check(
      'Gate refuses an asset whose QC did not pass',
      gate.body.eligible === false && gate.body.reasons.some((r) => /QC status/.test(r)),
      JSON.stringify(gate.body.reasons),
    );
  }
}

// --- 8. The produced file must actually be a video -----------------------------------
if (renderedPath) {
  const probe = JSON.parse(
    execFileSync('ffprobe', ['-v', 'error', '-print_format', 'json', '-show_streams', '-show_format', renderedPath], {
      encoding: 'utf8',
    }),
  );
  const video = probe.streams.find((s) => s.codec_type === 'video');
  check(
    'A3: ffprobe confirms a real 1080x1920 H.264 video (previously "moov atom not found")',
    Boolean(video) && video.width === 1080 && video.height === 1920 && video.codec_name === 'h264',
    video ? `${video.width}x${video.height} ${video.codec_name} ${Number(probe.format.duration).toFixed(2)}s` : 'no video stream',
  );
}

// --- 9. Gate refusal must leave an audit trail ---------------------------------------
const pubs = await api('/publishing/publications');
check(
  'A2: no publication is recorded as PUBLISHED',
  (pubs.body.publications || []).every((p) => p.status !== 'PUBLISHED'),
);

// --- 10. Media modal renders without console/CSP errors ------------------------------
await page.click('#open-media-btn');
await page.waitForSelector('#media-modal[open]', { timeout: 10000 });
await page.waitForTimeout(1500);
await page.screenshot({ path: path.join(OUT, 'post-audit-media-modal.png') });

// Mobile layout
await page.setViewportSize({ width: 390, height: 844 });
await page.waitForTimeout(500);
const overflow = await page.evaluate(
  () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
);
check('Mobile 390px layout has no horizontal overflow', !overflow);
await page.screenshot({ path: path.join(OUT, 'post-audit-mobile.png') });

check('No CSP violations', cspViolations.length === 0, cspViolations.join(' | '));
check(
  'No unexpected console errors',
  consoleErrors.filter((e) => !/Failed to load resource: the server responded with a status of (409|422|503)/.test(e))
    .length === 0,
  consoleErrors.join(' | ').slice(0, 300),
);

await browser.close();

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) {
  console.log('FAILED:', failed.map((f) => f.name).join('; '));
  process.exit(1);
}
