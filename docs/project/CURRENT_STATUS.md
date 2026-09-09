# CURRENT STATUS — Phases 0-2 complete; Phases 4-6 partially implemented

Last verified: 2026-09-09 by an independent audit (`AUDIT_2026-09-09_EXTERNAL.md`) and the
remediation that followed it. Active edit claim: none.

> **Correction notice (2026-09-09).** An earlier revision of this document declared Phases 4, 5
> and 6 "complete — verified". That was not supported by the code. The audit found fabricated
> channel configuration, simulated uploads recorded as real YouTube publications, a
> non-playable file written with an `.mp4` name, a QC gate that verified its own metadata
> instead of the file, and a demo endpoint that inserted a self-authored "SUPPORTED" claim.
> Those defects are fixed; the phases they belonged to are now marked partial, because the
> providers their acceptance criteria require still do not exist. Sections below state what is
> actually true.

## Baseline and document authority

Started from 83 Markdown documents with no application code, tests, dependencies or Git history.
All original documents were read. The Master Prompt remains authoritative under Owner instructions.
There was no pre-existing test suite to run.

Per Owner request, 78 specifications/review documents live in ../architecture/; five original
tracking documents live here. The document index records original and post-move hashes. Only path
references were changed inside the architecture package. CI/local checks protect the indexed files.

## Working and verified locally

**Phase 0 (complete):**
- FastAPI application at http://127.0.0.1:8000, with private Owner Bearer authentication.
- HTML/Tailwind/JavaScript UI built with Vite; desktop and 390px mobile layouts inspected.
- SQLite database and Alembic revisions 0001_foundation, 0002_phase1_agents, 0003_phase2_automation, 0004_phase4_factual; explicit bootstrap.
- Persisted studio, empty initial room, Owner STOP flag, immutable command/event history.
- Atomic policy/event transactions, optimistic version checks and command idempotency.
- Duplicate/concurrent commands tested; failed event insertion rolls back policy changes.
- STOP state survives application restart; clearing it keeps MANUAL mode.
- Owner-only consistent snapshots/event pagination; disconnects label stale UI.
- No credentials in frontend builds, API projections or request logs.
- Structured request logs, request correlation, health endpoints, CSP/Host checks.
- Locked Python/Node dependencies, lint/types/build/test baseline and GitHub Actions.
- Documentation inventory/hash checks with integrity tests.

**Phase 1 (complete — verified 2026-09-09):**
- Abstract LLMProvider interface (base.py): health_check, list_models, generate, is_cloud model metadata.
- Ollama HTTP adapter (ollama.py v1.0.0): real /api/tags discovery + /api/generate; returns OFFLINE if not running; supports cloud models (glm-5.2:cloud, kimi-k2.6:cloud, qwen3-coder:480b-cloud), api_key bearer auth, and /api/show model inspection.
- ProviderRegistry (registry.py): maps provider IDs to adapter instances; in-process health cache.
- Dynamic model discovery (sync_provider_models): automatically discovers both local and cloud models from provider endpoint, updates model_record, links text_generation capabilities, and emits provider.model_discovered events.
- Role entity with mission, allowed_task_types, prohibited_actions; RoleCapability requirement levels (REQUIRED/PREFERRED).
- Capability entity (text_generation, tool_calling, etc.); ModelCapability mapping with confidence.
- ProviderRecord, ModelRecord: registered providers and models with discovery_method tracking.
- Agent entity: lifecycle (PROPOSED/CANDIDATE/HIRED/ACTIVE/PAUSED/SUSPENDED/TERMINATING/TERMINATED/ARCHIVED) and runtime_state (IDLE/THINKING/WORKING/...).
- AgentRun envelope: full audit record of every LLM invocation with status, tokens, cost_vr, event_id.
- ToolReceipt: immutable append-only receipts (DB trigger, no UPDATE/DELETE) for all tool calls.
- Owner Policy Kernel: enforces autonomy_stop check, lifecycle check, capability match, provider health before any LLM run.
- FastAPI routes: GET/POST /api/v1/agents/, GET/POST /api/v1/providers/, /sync-models, /run.

**Phase 2 (complete — verified 2026-09-09):**
- Persisted workflow state machine (Workflow, WorkflowStep): tracks 17 pipeline stages (DISCOVERY -> ... -> PUBLISHED -> ANALYTICS -> LEARNING) according to 47_STATE_MACHINE_SPECIFICATIONS.md; rejects illegal state transitions.
- Task queue with leases and backoff (TaskQueueItem): atomic task claims with time-bounded worker leases, automatic expired-lease reclamation when workers fail, heartbeat renewal, and task completion.
- Error classification and dead-letter queue: retryable failures trigger exponential backoff with computed next_attempt_at; max attempts exhausted routes tasks to DEAD_LETTER; operator recovery endpoint allows manual retry.
- Singleton-safe scheduler (ScheduledJob): recurring jobs with leader leases to prevent duplicate work across scheduler instances, with support for SKIP and CATCH_UP missed-run policies.
- Transactional outbox (OutboxRecord): atomic commit guarantees that business events and outbox records commit together; outbox dispatcher broadcasts to WebSocket clients and marks status PUBLISHED.
- WebSocket gateway (/api/v1/ws): authenticated real-time event streaming with replay protocol supporting after_sequence cursor to replay missed events after reconnection.
- Autonomy stop hard-gate: task worker and scheduler refuse to claim or run tasks when autonomy_stopped is active.
- Alembic migration 0003_phase2_automation: 5 new tables (workflow, workflow_step, task_queue, scheduled_job, outbox_record) with zero schema drift.

**Phase 3 (complete — upgraded to Lateral Cutaway Skyscraper 2026-09-09):**
- Lateral cutaway multi-floor skyscraper canvas rendered at 60fps with zero simulated state, inspired by Space Haven, Anomaly President, and retro pixel-art simulation games.
- Seniority-based corporate hierarchy from top to bottom:
  * Floor 4 (Penthouse / Executive Suite): Director / CEO (Sarah) with panoramic city view, executive mahogany desk, gold trendlines, and award trophies.
  * Floor 3 (Research & Fact-Check Lab): Lead Researcher (Dr. Aris) & Fact Checker (Elena) with glowing holographic network graph whiteboard.
  * Floor 2 (Creative Writing & Narrative Studio): Script Writer (Marcus) with cork storyboard pinned with colored cards and red string.
  * Floor 1 (Media Lab & Production Bay): Voice Artist (Lyra) in acoustic foam vocal booth with boom mic & active LED EQ meter; Video Editor (Kael) with triple editing monitors.
  * Ground Floor / Level 0 (Infrastructure, Distribution & Lounge): Ollama Local Cluster & Cloud AI Gateway racks with blinking LED matrices and cooling fans; Coffee lounge with espresso machine emitting steam, water cooler, couch, and wall clock; Distribution hub with Vera at release console with radar map.
- Functional Glass Elevator Shaft on building exterior with moving elevator cabin traveling between floors.
- Procedural Animated Characters (Personaje):
  * Idle breathing bounce and periodic eye blinking.
  * Rapid typing hands on keyboard with dynamic monitor light reflections when WORKING.
  * Chin scratching gesture with floating glowing idea lightbulb and sparks when THINKING.
  * Resting / Zzz animation when PAUSED.
- Smooth camera controls: mouse pan, pinch/wheel zoom (0.4x to 2.5x), `fitToOffice()`, 1:1 reset, and dedicated Fullscreen (`#fullscreen-btn`) & Exit Fullscreen (`#exit-fullscreen-btn`) buttons with automatic canvas resize and Escape key support.
- Interactive Agent Inspector drawer modal (`#agent-inspector`) opened by clicking any character workstation, supporting live agent state inspection, direct task execution, and pause/resume actions (`POST /api/v1/agents/{id}/pause`, `POST /api/v1/agents/{id}/resume`).
- Real-time WebSocket connection to `/api/v1/ws` syncing backend events directly into `OfficeState`.
- Zero CSP violations (`style-src 'self'`). Frontend bundle remains compact.

**Phase 4 (PARTIAL — verification machinery works, real research does not exist):**
- Alembic migration `0004_phase4_factual`: 5 new tables (`topic_idea`, `source_snapshot`, `factual_claim`, `script_draft`, `hook_option`).
- Zone D Prompt Injection Defense (`sanitizer.py`): token stripping, instruction override filtering, and inert `<untrusted_source_evidence>` XML boundary tagging.
- Immutable source snapshots with SHA-256 digests (`content_hash`) and metadata (url, publisher, author, credibility_score). **Source text is supplied to the API by the Owner; nothing is retrieved from the web — there is no search or research adapter.**
- Atomic claim model (`factual_claim`) with status (`UNVERIFIED`, `SUPPORTED`, `REFUTED`), importance (`CRITICAL`, `SUPPORTING`, `FLAVOR`), and confidence.
- Strict Content Gate: attempts to generate or approve scripts with unverified or refuted claims raise `FactualGateError` and record an immutable `BLOCKED_UNVERIFIED_CLAIMS` draft for auditability (`factual.script_blocked_by_gate`).
- Script generation with 100% `SUPPORTED` claims compiles scene cues, voiceovers, and claim references. **A claim becomes SUPPORTED only through `POST /factual/claims/{id}/verify`, whose status is decided by the caller; there is no independent fact-checking agent.**
- Hook Specialist: opening hook variations with psychological techniques (`CURIOSITY_GAP`, `CONTRARIAN`, `STATISTIC_SHOCK`, `STORY_IN_MEDIA_RES`) and retention scores.
- Deduplication novelty calculation preventing repetitive content drift.
- Ollama Cloud model integration (`glm-5.2:cloud`, `kimi-k2.6:cloud`, `qwen3-coder:480b-cloud`).
- Frontend Topic Submission & Verification Modal (`#research-modal`) in 2D Office.
- **Not met for Phase 4 acceptance** (`IMPLEMENTATION_PLAN.md`: "real research, evidence, independent fact checks"): research and independent verification are manual.

**Phase 5 (PARTIAL — real encoding works, real visuals/voice do not exist):**
- Character Bible (`character_bible`): Pre-seeded with 7 canonical studio employees (Sarah, Dr. Aris, Elena, Marcus, Lyra, Kael, Vera) with immutable visual descriptions, hex palettes, role symbols, and voice profiles.
- Storyboard generator (`storyboard`, `storyboard_scene`): Transforms approved scripts into multi-scene visual shot lists enforcing aspect ratio 9:16 (1080x1920); strictly blocks unapproved scripts or scripts with unverified claims via `FactualGateError`.
- Placeholder media adapters (`DeterministicVisualAdapter`, `DeterministicTTSAdapter`): produce SVG layout cards and RIFF/WAVE tones locally. These are placeholders, not generated content: no image model and no voice model is connected. Assets built from them are recorded with provider `PLACEHOLDER_DETERMINISTIC_VISUALS` and are **blocked by QC from publication**.
- Subtitle generator: Compiles synchronized SRT subtitle tracks matching scene voiceover segments and durations.
- Video Assembly Engine (`VideoRenderJob`, `MediaAsset`): encodes a real H.264 1080x1920 MP4 with FFmpeg from raster placeholder frames plus the narration track, and records a SHA-256 digest of the encoded bytes (`media.video_rendered`). **Without FFmpeg the render fails** (`RenderEngineUnavailable`, HTTP 503) and no MediaAsset is recorded; the studio no longer writes a stand-in file with an `.mp4` name.
- Quality Control Engine (`quality_control_report`): Technical QC now **measures the file with ffprobe** (video stream present, measured resolution, measured duration) and **recomputes** the SHA-256 provenance digest, instead of trusting the metadata the renderer wrote. Rights QC checks the license field. Content-source QC fails any asset built from placeholder visuals. Factual QC re-checks every referenced claim. Character-drift QC is reported as `NOT_IMPLEMENTED` — it performs no comparison and certifies nothing.
- Alembic migration `0005_phase5_media`: 6 new tables (`character_bible`, `storyboard`, `storyboard_scene`, `media_asset`, `video_render_job`, `quality_control_report`).
- Media API routes (`/api/v1/media`): Character Bible endpoints, Storyboards, `POST /storyboards/demo-fixture` (creates a topic/script with an **UNVERIFIED** claim; it never marks anything SUPPORTED), video rendering, streaming, and QC gate verification.
- Frontend Media Production Modal (`#media-modal`): Storyboard pipeline viewer, 9:16 preview, QC scorecard, provenance hash badge, Character Bible inspector.
- **Not met for Phase 5 acceptance** (`../architecture/26_MASTER_ACCEPTANCE_CRITERIA.md` §F): there is no image or TTS provider, so no real footage or narration exists; character continuity is unimplemented.

**Phase 6 (PARTIAL — pipeline and gates work, no real upload has ever happened):**
- Channel slots (`channel_record`, `channel_brand_asset`): two slots (`MAIN_FACTUAL`, `OFFICE_SERIAL`) are seeded with **no remote channel ID, no credentials and status `NOT_CONFIGURED`**. Status is derived from what is actually present (`NOT_CONFIGURED` -> `AUTH_REQUIRED` -> `AUTHENTICATED`); nothing is ever reported as configured on the strength of a seed.
- Five-check publishing gate (`evaluate_publishing_gate`). This is a **subset** of the publish column of `../architecture/50_CONTENT_GATE_MATRIX.md`, not an implementation of it — rights on the final package, platform policy, novelty on final metadata, brand strategy, budget, and Channel B continuity/narrative privacy are not implemented:
  1. Global Autonomy Stop check (fails if `autonomy_stopped` is active).
  2. Media file on disk existence check (fails if file missing or 0 bytes).
  3. Quality Control check (fails if QC status is not `PASSED` or score < 0.90).
  4. Factual claim integrity check (fails if any claim referenced in the script is not `SUPPORTED`).
  5. Idempotency & duplicate protection check (fails if asset was already published on that channel).
- YouTube Data API v3 Adapter (`YouTubeProvider`): OAuth2 refresh-token exchange, chunked resumable upload with `Content-Range` and 308 resume, synthetic-content disclosure (`containsSyntheticMedia` plus a disclosure line in the description), remote status polling, and reconciliation that is actually invoked before any retry. **This adapter has never run against Google**: no credentials have been configured, so the whole path is untested against the real API.
- Simulated Publishing Adapter (`DeterministicPublishingAdapter`): **tests and CI only**. It is never selected at runtime; without real credentials the API returns 503 `PublisherNotConfigured`. Its results carry `simulated=True`, a `sim:` identifier and no platform URL, and are stored as `PUBLISHED_SIMULATED` with event `publishing.video_published_simulated`.
- Publication State Machine & Tracking (`publication_record`): Enforces `DRAFT_INTENT` -> `VALIDATED` -> `STARTED` -> `REMOTE_CONFIRMED` -> `PUBLISHED` transitions with recovery from `REMOTE_UNKNOWN` and `FAILED_RETRYABLE`.
- Unique constraint `uq_channel_idempotency`: Prevents duplicate uploads of the same intent.
- Alembic migration `0006_phase6_publishing`: 3 new tables (`channel_record`, `channel_brand_asset`, `publication_record`).
- Publishing API routes (`/api/v1/publishing`): Channel management, gate evaluation, intent creation, publication execution, quick-publish, and publication history retrieval.
- Frontend Distribution Hub Modal (`#publishing-modal`): shows real channel status with plain-language hints, a banner when no credentials are configured, the gate breakdown including what is not implemented, and publication history where a simulated run is labelled "SIMULAT (nepublicat)" and gets no link. Only a genuine `youtube.com` URL becomes a clickable link.
- **Not met for Phase 6 acceptance** (`../architecture/26_MASTER_ACCEPTANCE_CRITERIA.md` §G): OAuth has never been exercised, no private upload has been verified, and no real remote ID has ever been persisted.

## Partial / exact limits

- The application runs end to end locally: foundation, automation, 2D office, factual gating,
  media assembly and the publishing state machine are all exercisable.
- **Nothing has ever been published.** Without `STUDIO_YOUTUBE_*` credentials the publishing API
  returns 503 and refuses; the simulator is reachable only by injecting a provider in tests.
- **No asset currently passes QC for publication.** Renders use placeholder visuals, which
  content-source QC fails by design until an image/TTS provider is connected.
- Rendering requires FFmpeg on the host. Without it, `POST /media/render/{id}` returns 503.
- Local single-owner SQLite deployment only. PostgreSQL and multi-user auth remain pending.
- Real Ollama end-to-end test is skip-marked; it runs when `STUDIO_OLLAMA_URL` is set.

## Not implemented

- Search/research adapter (Phase 4 acceptance) and independent fact-checking agent.
- Image and TTS providers (Phase 5 acceptance); character-continuity drift detection.
- The remaining publish-time gates of `../architecture/50_CONTENT_GATE_MATRIX.md` (rights on final package,
  platform policy, novelty on final metadata, brand, budget, Channel B continuity/privacy).
- Phase 7 analytics: `backend/app/analytics/` and `providers/youtube_analytics.py` exist on
  disk from an unfinished work session, but they are **not mounted in `main.py`, not
  registered in `Base.metadata`, and have no Alembic migration**. They are inert; do not
  treat them as delivered, and add migration `0008` before wiring them.
- Office Serial autonomous scriptwriter, dynamic departments, VR economy ledger, VendorShop,
  financing.

## Test evidence

Independent audit environment (Linux, Python 3.13, SQLAlchemy 2.0), 2026-09-09, after remediation:

- `pytest` **with FFmpeg available**: 87 passed, 1 skipped (real Ollama), 0 failed.
- `pytest` **without FFmpeg**: 85 passed, 3 skipped (Ollama + two render tests that are skipped
  rather than silently exercising a fake path), 0 failed.
- `tests/test_truthfulness_gates.py` (new, 10 tests) locks the governance invariants: channel
  slots are never reported as configured, publishing refuses without credentials, a simulated
  upload is never stored as a real publication, a gate refusal is persisted with its event,
  QC rejects a non-video file named `.mp4`, QC rejects a tampered provenance digest, and the
  character-drift check never claims to pass.
- `ffprobe` on a produced render: 1080x1920, h264, duration equal to the storyboard timeline.
- `npm test --prefix frontend`: 6 passed. `npm run check`: 0 errors. `npm run build`: succeeded
  (51.33 kB JS, 24.44 kB CSS).
- **Live application verification** (`scratch/verify_post_audit_e2e.mjs`, real Chromium against a
  running server): **27/27 checks passed**, 0 console errors, 0 CSP violations. It exercises the
  full chain — login, clearing the Owner STOP, channel status, the credential banner, the 1-click
  publish refusal, the demo fixture, the factual gate blocking an unverified script, claim
  verification, approval, storyboarding, rendering, QC, and the publishing gate refusal — and
  confirms with `ffprobe` that the produced file is a real 1080x1920 H.264 video of 18.00s.
  Screenshots: `output/playwright/post-audit-publishing-hub.png`, `post-audit-history.png`,
  `post-audit-media-modal.png`, `post-audit-mobile.png`.
- **Cold-start verification**: from a clean checkout with no `.venv`, no `node_modules`, no `.env`
  and no database, `uv run python scripts/start.py` brought the studio up unattended (uv venv +
  `uv sync --locked` + `npm ci` + Vite build + bootstrap + server), `/health/live` answered 200,
  and the 27-check Playwright suite passed against that fresh instance.

Note on the previous revision of this section: the "80 passed" figure it reported was
reproducible, but the suite passed **because** FFmpeg was absent on the development machine —
the real encoder path raised `DetachedInstanceError` and had never been executed. The suite now
fails loudly in that situation instead of certifying the fallback.

## Files changed / architecture impact

Post-audit remediation (2026-09-09):
- `backend/app/config.py`: `STUDIO_YOUTUBE_*` and `STUDIO_FFMPEG_PATH` settings; credentials no
  longer read ad hoc via `os.getenv`.
- `backend/app/publishing/services.py`: honest channel seeding and `derive_channel_status`;
  gate refusals persisted before raising; `PUBLISHED_SIMULATED` state; QC score minimum
  enforced; reconciliation before any retry; no provider fallback.
- `backend/app/publishing/router.py`: 503 `PublisherNotConfigured`; `POST /channels/seed`
  replaces seeding inside a GET; 404 instead of 500 for a missing asset; quick-publish requires
  an AUTHENTICATED channel.
- `backend/app/providers/publishing_base.py`, `deterministic_pub.py`: `simulated` flag,
  `sim:` identifiers, no fabricated platform URL.
- `backend/app/providers/youtube.py`: chunked resumable upload, synthetic-content disclosure,
  `youtube_provider_from_settings`.
- `backend/app/media/assembler.py`: placeholder raster frames + real FFmpeg encode or
  `RenderEngineUnavailable`; no stand-in `.mp4`; storage root no longer a hardcoded Windows
  path; detached-ORM bug fixed.
- `backend/app/media/qc.py`: ffprobe measurement, provenance re-verification, content-source
  check, character drift reported as `NOT_IMPLEMENTED`.
- `backend/app/media/router.py`: `POST /storyboards/demo-fixture` creates UNVERIFIED claims
  only; render surfaces 503 when no encoder exists.
- `scripts/bootstrap.py`: fixed a `TypeError` that broke first-time `.env` creation.
- `frontend/index.html`, `src/main.js`, `src/style.css`: truthful channel and publication
  status vocabulary, credential banner, no links to non-existent videos.
- `tests/test_truthfulness_gates.py` (new); `tests/test_phase5_media.py` and
  `tests/test_phase6_publishing.py` updated to assert the honest behaviour.
- `pyproject.toml` / `uv.lock`: added `websockets` — without it uvicorn answered the
  `/api/v1/ws` handshake with 404 and the office never received live events. Run `uv sync`.
- `backend/app/factual/services.py`, `router.py`, `schemas.py`: new
  `POST /api/v1/factual/scripts/{id}/approve`, which re-runs the factual gate at approval time.
  Without it, scripts created through the real API (`VERIFIED_PASS`) could never reach the
  `APPROVED` status storyboarding requires — only the removed fixture endpoint could.
- `start.cmd` and `scripts/start.py` (new): single-command launcher with a preflight report that
  states which integrations are configured; `scripts/bootstrap.py` and `../../README.md` point at it.
- `scratch/verify_post_audit_e2e.mjs` (new): the Playwright verification described below.
- `docs/project/AUDIT_2026-09-09_EXTERNAL.md` (new): the audit these changes answer.

- `backend/migrations/versions/0007_correct_fabricated_records.py` (new, data-only): corrects
  rows already written by the pre-audit code — invented channel IDs are cleared and the channels
  set to `NOT_CONFIGURED`, `yt_sim_*` publications become `PUBLISHED_SIMULATED` with their dead
  YouTube URLs removed, and every earlier `PASSED` QC report is marked `INVALIDATED` because the
  gate that granted it measured nothing. Nothing is deleted; history stays auditable.
- `backend/app/main.py`: startup revision check moved to `0007_correct_fabricated_records`.

Modular monolith; no table was added or altered (migration 0007 is data-only). Phase 7 analytics
must therefore start at `0008`.

## Blockers and risks

- **Publishing is blocked by design** until `STUDIO_YOUTUBE_CLIENT_ID`,
  `STUDIO_YOUTUBE_CLIENT_SECRET` and `STUDIO_YOUTUBE_REFRESH_TOKEN` are configured and a
  channel is moved to `AUTHENTICATED`. The whole YouTube path is still unexercised against
  Google.
- **Publishable content is blocked** until a real image/TTS provider replaces the placeholder
  adapters; content-source QC fails placeholder visuals on purpose.
- Rendering requires FFmpeg on the host.
- Phase 7 analytics code on disk is inert and unmigrated; wiring it as-is would cause schema
  drift and refuse startup.

## Exact next task

Close the acceptance gaps before advancing to Phase 7, in this order:

1. **Phase 4 acceptance** — a real search/research adapter (`../architecture/22_PROVIDER_INTEGRATION_CONTRACTS.md`
   search adapter contract) feeding `ingest_source_snapshot`, plus an independent fact-checking
   role that cannot verify its own claims.
2. **Phase 5 acceptance** — a real image provider and a real TTS provider, so renders stop being
   placeholder frames and content-source QC can pass; then character-continuity drift detection.
3. **Phase 6 acceptance** — configure Google OAuth, verify one private upload end to end against
   the real API, and record the real remote ID.
4. Only then Phase 7 (analytics), starting by adding migration `0008` for the analytics tables
   and wiring the router and `Base.metadata`.


## Codex research scope claim — 2026-09-09T23:19

Active: isolated public HTTPS source retrieval in new backend/app/research files, a local Owner CLI and dedicated tests. UI, media, app wiring, dependencies and migrations remain outside this claim while Claude works there. Baseline: 88 passed, 3 skipped; one documentation test fails on nine stale relative references.

## Codex research increment — completed, scope released

- Implemented Owner-directed known-URL HTTPS retrieval in new `backend/app/research/` files and `scripts/research_source.py`; existing UI/media/application code remains outside this change.
- The CLI can feed the existing authenticated source-ingestion API. No claim is automatically verified; no search provider or worker is activated. Phase 4 remains partial.
- Corrected nine stale architecture/root-document references in project tracking. Original architecture hashes are unchanged.
- Windows validation: 121 passed, 3 skipped (real Ollama unavailable; two FFmpeg checks unavailable). New-module Ruff and mypy pass; document inventory/hash verification passes.
- Real IANA HTTPS retrieval and authenticated ingestion into an isolated temporary database succeeded with matching hashes. Live studio state was not changed.
- Usage, limitations, touched paths and exact remaining research work: `RESEARCH_HANDOFF.md`.
- Next: keyword-search provider integration and independently authorized fact checking; coordinate separately before modifying shared factual routes. Claude retains UI/media scope.

Verification follow-up: the secret scanner flagged a pre-existing hardcoded provenance fixture in `tests/test_phase6_publishing.py`. Replaced only that fixture value with the actual SHA-256 of its test video bytes; no scanner suppression or publishing implementation change.

Final follow-up checks: all six publishing tests pass after the fixture correction; secret scan and documentation inventory/hash checks pass. No frontend or pre-existing backend source file was modified.

## Codex Settings scope — 2026-09-09T23:38

Owner explicitly requested Settings UI: LLM providers, agent assignments, video/audio tools, YouTube/TikTok/Instagram/Facebook and optional email credentials. Scope: new integrations backend + migration 0008, separate settings UI module/styles and minimal app wiring. No office animation edits. Credentials encrypted; saved configuration must never imply verified connectivity or publishing capability.

## Owner-directed renderer fixes — 2026-09-10, ZCode

Owner-reported visual defects only, scope `frontend/src/office_engine.js` scenery/nameplates + one new frontend unit test: remove the invented bus route number "12", stop same-lane vehicles passing through each other (lane spacing at spawn + car-following), and shrink the agent nameplates onto a light "paper" plate for readability. No backend, settings, integrations or office-state changes.

Completed and released the same day. Details:

- `drawCar`: the hard-coded bus route label "12" is gone; the destination blind stays blank.
- `makeTraffic`/`updateTraffic` (new, exported): vehicles now spawn spread across each lane's loop stretch and move as a platoon — a follower near its leader adopts the leader's speed and a hard clamp holds a 24 px bumper gap, including across the road's wrap seam, so same-lane vehicles can no longer drive through each other.
- `drawNamePlate`: the name renders at single scale (was double) on a light paper card with dark ink and a muted state line — half the height, far less floor area, readable over the night interiors; the selected variant keeps the gold border.
- Follow-up (Owner direction, same day): the runtime state moved out of the floor card
  entirely. The card at the character's feet now carries the name only; a new
  `drawStateTag` floats the state (IDLE, WORKING…) above the head as a dark chip with
  department-accent text, and the thinking bulb / sleeping Z marks were raised above it
  so the three never overlap.
- Verification: `npm test` 11/11 (3 new traffic invariant tests: spawn spacing, fast-car-catches-slow-bus, 15-minute mixed-timestep seam run), `npm run check` clean, `npm run build` OK (86 kB). Live browser check on the running local studio confirmed the bus has no number, traffic flows with no overlap across frames, and the nameplates render as small light cards.

## Documentation identifiers, initial Git commit — 2026-09-10, ZCode (second session)

Owner-directed documentation and repository repairs; recorded as D-DOC-001 in the decision log:

- `16_DECISION_LOG.md`: removed the byte-identical duplicate of the ADR-001…ADR-V5-003 block
  (verified identical before deletion; 706 → 551 lines, every ADR now single).
- `../architecture/02_SRS.md`: the v3 additional FRs are renamed `FR-V3-037…FR-V3-066`
  (same numeric suffix, consistent with the existing `FR-V4-`/`FR-ECON-` namespaces), clearing the
  collision with base FR-037…066. NFR-013…021 never collided and are unchanged. Requirement text
  unchanged. `../architecture/V3_FILE_BY_FILE_REVIEW.md` notes the rename; `IMPLEMENTATION_PLAN.md`
  marks the
  recorded conflict resolved. Indexed `sha256` values for both architecture documents updated
  explicitly (original hashes preserved).
- `tests/test_integration_settings.py` (two fixture values only, inside the active Codex Settings
  claim — flagged here so that agent is aware): `"do-not-echo"` → `"abc"` and
  un URL de test cu utilizator și parolă în el → unul doar cu nume de utilizator, so `scripts/check_secrets.py`
  passes without suppression. Both payloads still assert the same 422 refusals; all 15 settings
  tests pass.
- Initial Git commit created at the Owner's request (`ae4dee3`, branch `codex/foundation`, with a
  `main` branch pointer at the same commit): 212 files — source, tests, docs, scratch verification
  scripts. `.gitignore` extended with `backend/storage/` and `Claude outputs/` (generated media and
  screenshots); `.env`, `data/`, `output/`, `dist/`, `node_modules` were already excluded and are
  confirmed absent from the commit.

Verification at commit time: `pytest` 136 passed / 3 skipped; frontend `npm test` 11/11, `tsc`
clean, build OK; `scripts/check_docs.py` and `scripts/check_secrets.py` pass.

## Owner-directed LLM connectivity test — 2026-09-10, ZCode (third session)

Verified the Ollama Cloud integration end to end and added the missing Settings test affordance:

- Live state checked first: the "Ollama Cloud" integration (`https://ollama.com`) is saved and
  VERIFIED, 22 models discovered, all 7 agents carry an assigned model on that provider,
  autonomy stop inactive.
- Real runs through the policy kernel succeeded against the live provider: Sarah/glm-5.3-flash
  (reasoning output; token counts recorded) and Lyra/gpt-oss:120b answered
  "Da, sunt funcțional și gata să te ajut." in ~1s. Runs, tokens and events are in the audit trail.
- New: `POST /api/v1/settings/agents/{id}/test` runs one real connectivity task through the
  agent's assigned model (fixed short objective, max 800 tokens) and returns the same AgentRun
  envelope plus duration; 404 for unknown agents, policy blocks recorded as BLOCKED_* statuses.
- New: each agent card in Settings → Agenți has a "Testează răspunsul" button that surfaces the
  model's answer (or the block reason). Verified live in the browser: the button returned
  "glm-5.3-flash a răspuns: «Da, sunt complet funcțional…»".
- Test: `test_agent_llm_test_endpoint_runs_assigned_model` (provider monkeypatched; no network in
  tests). Settings suite 16/16.

## Whole-tree lint and type cleanup — 2026-09-10, ZCode

With the parallel agents' sessions finished, the committed baseline still failed the README's own
`ruff check .`, `ruff format --check .` and `mypy` (177 ruff findings, 9 mypy errors, inherited
from pre-audit and remediation code). Cleaned without behaviour change:

- `ruff format` across the tree (23 files) plus manual wrapping of the remaining 65 long lines
  (string literals split with identical content; the deterministic SVG template's XML attributes
  re-wrapped — rendering unchanged, hashes are computed at runtime).
- Auto-fixes: 22 unused imports, 11 unsorted import blocks, small UP modernisations.
- Manual: SQLAlchemy `== True` filters → `.is_(True)` (analytics), an unused local dropped
  (publishing), explicit `strict=False` on an intentionally asymmetric `zip` (office layout test),
  `requires_ffmpeg` moved below the imports it uses (E402).
- mypy: explicit `dict[str, Any]` annotations for the ffprobe result and the storyboard scene
  payloads (media/qc.py, media/assembler.py).

Verification after cleanup: `ruff check .` clean, `ruff format --check .` clean (185 files),
`mypy` clean (68 files), `pytest` 137 passed / 3 skipped, frontend `npm test` 11/11, `tsc` clean,
build OK, `check_docs.py` and `check_secrets.py` pass.

## Live speech bubbles wired end to end — 2026-09-10, ZCode (fourth session)

The speech-bubble projection existed in the frontend (handler, expiry, paper bubble renderer)
but nothing ever fed it: the backend never emitted `agent.message_sent`, and the transactional
outbox had no dispatcher, so no event was broadcast live after the initial replay. Three fixes:

1. **Producer** — `run_agent_task` now emits `agent.message_sent` (through
   `append_event_with_outbox`) in the same transaction that records the successful run, with the
   model's real output text (whitespace-normalised, capped at 200 chars) plus `run_id` and
   `task_type`. Per `../architecture/06_BACKEND_EVENT_MODEL.md` §7 only real messages may become
   live bubbles: failed runs and successful runs with no visible text (reasoning models with a
   small budget) emit nothing.
2. **Dispatcher** — the app lifespan now runs the outbox dispatcher every second
   (`publish_pending_outbox`), broadcasting committed outbox events to WebSocket clients. It runs
   on the server's own event loop on purpose: the broadcast tasks and the sockets belong to that
   loop. This also un-silences the workflow events that were already written to the outbox.
3. **UI label** — `agent.message_sent` shows as "Agentul a răspuns" in the activity log.

Verification: three new phase-1 tests (successful run emits the event with the real text and a
PENDING outbox record; failed run emits nothing; empty visible output emits nothing). Live E2E
against Ollama Cloud with the office open: an API-triggered run for Lyra/gpt-oss:120b produced
the speech bubble above her head reading "SUNT GATA SĂ LUCREZ ÎN CABINA VOCALĂ." — the run was
fired from outside the page, so the bubble proves the live event chain, not page-local state.
Full suite: ruff/format/mypy clean, pytest 140 passed / 3 skipped, frontend 11/11, docs and
secret checks pass.

Known related gap (not addressed here): agent runtime-state changes (THINKING/IDLE) are column
updates without events, so the state tag above the head updates on layout refresh rather than
instantly.
