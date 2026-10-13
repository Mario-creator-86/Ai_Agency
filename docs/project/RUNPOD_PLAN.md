# RunPod integration implementation plan — 2026-10-07

Goal: add an optional RunPod provider to the existing Agency, with no real GPU activity until
Owner supplies credentials, endpoint details and paid-test approval.

Architecture: keep ImageProvider/VideoProvider and the SQLAlchemy workflow worker. Put transport,
request models, durable submission identity, polling, safe downloads and telemetry behind
app.providers.runpod. Keep SceneTake and MediaAsset as production asset and QA records.
Tech stack: existing Python/SQLAlchemy/Pydantic, media_http transport and Alembic.

- [x] Audit existing provider selection, purchases, QA, storage and restart recovery; run baseline.
- [x] Write failing contract tests for configuration, requests, both transports, idempotency,
  ambiguous submissions, downloads, mock jobs, retries, QA feedback and cost aggregation.
- [x] Implement focused modules: config.py, models.py, client.py, jobs.py, provider.py, mock.py,
  adapters.py. Add durable telemetry via one additive migration; no second worker or queue.
- [x] Extend existing media factory, integration catalog/discovery, prices and watchdog collector;
  preserve verified selection, paid staircase, budget and no unapproved fallback invariants.
- [x] Test complete mock scene lifecycle, local persistence, rejection/new attempt and restart.
- [x] Document custom cloud contract including backend idempotency handshake; supply read-only
  connection check. Record missing credentials/endpoints and real tests as unverified.
- [x] Run relevant backend regressions, formatting, lint, types, docs and secret checks.
- [x] Record changed files, actual commands/results and next steps in tracking and handoff.

Result: 394 scoped backend tests and 799 frontend tests passed. Lint/format/types/docs/secrets
passed; offline image/video QA/restart exercise passed. Migration 0055 applied with backup,
all 77 old tables unchanged. Official plugin installed; paid cloud access remains disabled.
See RUNPOD_HANDOFF.md for evidence and the remaining credential/endpoint-dependent live checks.

- [ ] Authenticate the real account/endpoint and verify its health/model catalogue.
- [ ] Run one real image and one five-second I2V after the Owner's separate paid-test approval.

ComfyUI cleanup is separately authorized. Inventory only owned E:/Studio runtime/model/cache
paths and matching launch shortcuts/processes. Verify absolute targets before deletion, do
not traverse links into other projects, and retain output/film/benchmark artifacts.
