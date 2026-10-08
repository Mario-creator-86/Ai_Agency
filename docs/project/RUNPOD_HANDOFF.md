# RunPod preparation and local ComfyUI uninstall — 2026-10-07

## Scope and actual state

Branch: `feat/runpod-cloud-generation`. The checkout was already dirty; its previous work is
preserved. Nothing was committed, pushed, deployed or published. No GPU was provisioned,
started or charged. No large local model was installed.

The additional RunPod provider is implemented and verified offline. This is **not evidence of
a working authenticated cloud integration**: the Owner has not supplied RunPod credentials or
a generation endpoint. The latest instruction explicitly defers those and authorizes completing
all local preparation. Only real connection details and their subsequent verification remain.

The existing Agency remains responsible for routing, queues, workers, SceneTake/MediaAsset,
QA, VideoEditor, assembly, Owner permissions, budgets and accounting. RunPod-specific transport
and compute operations are inside app.providers.runpod. No second queue or QA agent was built.

Read [the integration guide](../RUNPOD_INTEGRATION.md) for the cloud contract and activation.

## Implemented behavior

- Optional typed configuration, disabled by default; empty .env.example placeholders.
- Pod custom API and official async Serverless transports; bounded HTTP/poll/download timeouts.
- Durable intent before submit; project/scene/attempt/operation/candidate/destination identity.
  Restart recovers the saved remote ID. Partial/ambiguous POSTs are never blindly bought again.
- Explicit reconciliation requires backend proof of the saved idempotency key. GETs and proven
  unsent requests use bounded infrastructure retry; QA rejection creates a new creative attempt.
- Typed image/video/finalize requests, 9:16 defaults, configurable logical Qwen/LTX/Wan/AUTO routes,
  inline approved source images and retained corrective feedback/history.
- Validated output download, public-address pinned transport, atomic local persistence/checksum,
  existing asset and watchdog recovery; the originating connection is retained for collection.
- Existing QA/Owner verdicts update provider telemetry. Rejected attempts remain in costs.
- Existing sheet budget disclosure adds GPU cost, accepted scene/finished Short cost, minutes,
  regenerations and model acceptance. Missing execution data stays unknown; all money is estimated.
- Actual provider purchases/redos are labeled RunPod rather than Runway, without inventing an
  account credit balance or marking a forecast as a paid invoice. Owner caps/approvals remain.
- Optional existing-Pod REST v2 read/start/stop hooks, all mutations disabled by default.
  Shutdown refuses pending/uncertain generation. No idle timer or provisioning was installed.
- Offline mock emits CPU-generated PNG and MP4, explicitly labeled synthetic; mocks cannot be
  selected through the production factory in the PRODUCTION environment.
- Public health alone cannot claim authentication; custom health requires authenticated=true.

## Files added or changed by this work

New provider package `backend/app/providers/runpod/`:
`__init__.py`, `config.py`, `models.py`, `errors.py`, `client.py`, `jobs.py`, `provider.py`,
`adapters.py`, `mock.py`, `compute.py`, `pricing.py`, `telemetry.py`, `wiring.py`.

New schema and operator check:
`backend/migrations/versions/0055_cloud_generation_jobs.py`, `scripts/check_runpod.py`.

Shared integration points (some also contain preserved earlier local-media changes):
`backend/app/integrations/catalog.py`, `discovery.py`, `services.py`;
`backend/app/media/factory.py`, `production_policy.py`, `stills_stage.py`, `assembler.py`,
`shooting_sheet.py`; `backend/app/workflows/watchdog.py`;
`backend/app/providers/media_http.py`; `frontend/src/shooting_sheet.js`; `.env.example`.

Verification:
`tests/test_runpod_generation.py`, `tests/test_runpod_pipeline.py`,
`frontend/tests/runpod_sheet.test.js`; `tests/test_no_paid_path_escapes.py` now distinguishes
plain isinstance/issubclass type references from adapter construction and explicitly keeps
RunPod transport/provider classes paid. Only the pure configuration module is classified free.
The secret baseline records four existing workflow SHA-256 checksums; synthetic credentials
in new adversarial tests have explicit inline pragmas. Actual credentials are never baselined.
Mechanical formatting: one import group in test_local_media_routing and two existing prompt
agent formatting lines; no functional change to those areas.

Documentation: `docs/RUNPOD_INTEGRATION.md`, `docs/project/RUNPOD_PLAN.md`, this handoff,
CURRENT_STATUS, roadmap, decision log and changelog. Normative architecture files are unchanged.

## Verification evidence

Final scoped backend regression: **394 passed in 234.23 seconds**, covering RunPod, existing
media providers/selection/retry/discovery, local-provider compatibility, stills/takes/watchdog,
shooting sheet, redos/interrupted purchases, budgets, lowered mode, paid-path guards and secrets.
This includes 59 RunPod contracts/pipeline tests. UI: **799 passed**, zero skipped/failed.
Ruff lint and formatting passed (604 files); mypy passed (197 source files); documentation
inventory/architecture hashes and secret checks passed. TypeScript and Vite build passed;
Vite retains the existing large-chunk advisory. git diff --check passed.

Commands: `uv run --locked pytest` with the 19 scoped modules above; `ruff check .`,
`ruff format --check .`, `mypy`, `python scripts/check_docs.py` through the locked environment;
`npm test`, `npm run check`, `npm run build` in frontend. The secrets module checks the current
entire shipping tree against the reviewed baseline, not only new RunPod files. Logs are under
`data/runpod-verification/`; `backend-tests.log` and `frontend-tests.log` retain final counts.
Earlier synthetic-credential scan findings were corrected with explicit test-value pragmas;
no real credential was added to the baseline. The final 394-test run passed without failures.
This is scoped regression verification, not a claim that every unrelated repository test ran.

Default read-only connection check returned configured=false, enabled=false, authenticated=false,
no available models and no external request. Authenticated endpoint behavior remains unverified.

The offline CLI exercise passed: image rejection → corrected image acceptance → five-second
video → adapter reconstruction/recovery → local assets and telemetry. Its synthetic acceptance
is an exercise of bookkeeping; it is not a measured Qwen/LTX creative-quality score.

Report: `data/runpod-mock-check/b7f22dc7-ef0b-44de-9472-33cbf2003f5d/report.json`.
Generated image and video are 72×128 (9:16); video is decodable H.264, 24 fps, 5 seconds.
Journal: 3 jobs, 1 regeneration, 1 accepted scene, 0 GPU seconds and USD 0 in MOCK.

Live migration: 0054 → 0055 applied to `data/studio.db`; all 77 pre-existing tables had identical
row counts and content hashes, no foreign-key violations, 0 cloud jobs. SQLite backup:
`data/runpod-verification/before-runpod-0055-fc3d083b-a721-4214-b11f-5d6747d01d4f.db`.
Verification report: `data/runpod-verification/live-migration-report.json`.
The separate backup before removing the obsolete Comfy connection is `data/before-comfy-uninstall.db`.

The Agency was already stopped during local verification. It was not restarted, and no existing
queued production work or paid voice generation was triggered. Normal next startup uses the
new schema/provider code; RunPod stays disabled until explicitly configured.

## Official tooling and remaining external work

Official plugin 1.5.0 installed from RunPod's runpod-plugins-official marketplace. Bundled MCP
uses https://mcp.getrunpod.io/. This session did not authenticate it; reload tooling when ready.
No duplicate MCP entry or API secret was added to Codex configuration.

Owner needs to supply:

1. RunPod API key via ignored environment or Agency credential vault.
2. Pod custom generation base URL, or Serverless endpoint ID plus the read-only backend URL
   for authenticated health/model inventory. The cloud server must implement the documented
   idempotency, payload, status, source-image, output and model/pricing contracts.
3. Enable RunPod, verify health/models and select the desired image/video connection/models
   through existing Settings. Optional infra control additionally needs a real existing Pod ID;
   it is not required for ordinary generation.

After authenticated health/models verification, follow the user's explicit paid-test gate:
`PREIA TU ACUM - READY FOR PAID GPU TEST`, with one image and then one five-second I2V test,
real backend time/cost estimates and Owner approval. Those live tests remain **unperformed**.
Do not infer real GPU performance, loaded models, prices or availability from mocks.

## ComfyUI uninstall

The Owner separately authorized finding and removing local ComfyUI and its models/traces.
Removed the owned E:/Studio application, all 50 inventoried weight/model files (~163.75 GB),
environment, Python runtime, custom nodes, caches, workflows/configuration, tools/tests,
desktop launcher, API client, process-state log and obsolete software backups. C:/AI/Workflows
copies were removed. No matching running Comfy process or application profile remained.

The primary inventory contained **172,694,650,674 bytes (~172.7 GB decimal /160.8 GiB)** removed;
this is inventoried file size, not a before/after free-disk-space measurement.
Films, Outputs, Benchmarks, API-Test generated outputs and historical written reports remain.
Nepal film SHA-256 unchanged:
`bc2046a56f887406a8c5f46a9ce787deea3dc2c9fd95b8629a88320bfece38f5`.

Removed the one obsolete Agency ComfyUI connection and detached its image/video selections
using the existing domain service/event transaction; voice selection stayed identical.
No replacement paid provider was selected. Agency adapter/tests/workflow **source code** remains
for compatibility with the instruction to preserve existing providers; it is not an installed
Comfy application or local model weights. Ollama/Unreal/Blender and other projects were untouched.

Evidence in the auxiliary workspace:
`C:/Users/mario/OneDrive/Documente/ChatGPT/AI Acency/output/comfy-cleanup-inventory.json`,
`comfy-cleanup-result.json`, `comfy-cleanup-residuals.json`, `comfy-cleanup-verification.json`.
The broad E: name scan encountered permission-denied unrelated Today_Market artifact directories;
the report preserves these limits. It does not claim an exhaustive forensic scan of every E: file.
E:/Studio/docs/HANDOFF.md and the auxiliary docs/HANDOFF.md now supersede old install/server claims.
