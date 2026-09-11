# Architectural / Product Decision Log v5

## ADR-YOUTUBE-AVATARS-001 — API thumbnail identity and narrow image CSP
**Status:** Implemented and live verified, 2026-09-11

The connection snapshot already stored a URL, but the browser's same-origin-only image policy
blocked it. Select `snippet.thumbnails.high.url`, then medium, then default, skipping missing or
empty URLs. Keep the URL unchanged in the existing per-connection JSON snapshot. Authorization
and Verify already commit fresh snapshots; completed Reconnect uses the authorization callback.
The existing channel request includes snippet/statistics plus id/contentDetails so the stored
uploads-playlist metadata continues to work.

Allow only `https://yt3.ggpht.com` and `https://yt3.googleusercontent.com` in addition to the existing
image sources. Reject a broad `https:`/wildcard policy and an unnecessary backend image proxy.
Use a neutral CSS silhouette only when there is no API thumbnail, not to mask a failed image load.
No schema migration or channel-specific logic is needed. Rollback is a source rebuild/server
restart; snapshots remain compatible. Regression tests cover quality fallback, per-connection
refresh and CSP; live Chromium loaded both existing channel images at 800×800 after Verify.

## ADR-FOUNDATION-001 — Local modular monolith
**Status:** Implemented, 2026-09-09

Problem: the repository contained specifications only. Build the documented Phase 0 before integrations.
Choice: Python/FastAPI, SQLAlchemy, explicit Alembic migrations and file-backed SQLite; HTML/Tailwind/JS
with Vite. SQLite gives a Windows-friendly no-service setup. PostgreSQL and durable worker technology
remain later decisions and must pass their own tests. Synchronous DB endpoints run in FastAPI's thread
pool; later network adapters can use async I/O. No worker or queue is falsely implied.

State updates and domain events commit together. The initial event store is read directly; a durable
outbox publisher/WebSocket layer remains Phase 2. Immutable DB triggers protect event/command history.
Tests: migrations/schema comparison, rollback-on-error, race/idempotency and restart.
Migration: new empty schema only. Rollback: stop application and restore a verified backup; destructive
schema downgrade is deliberately absent.

References checked: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/),
[SQLAlchemy SQLite transaction control](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html),
[Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html).

## ADR-FOUNDATION-002 — Early Owner control without premature autonomy
**Status:** Implemented, 2026-09-09

The Owner STOP flag is introduced early as a tested foundation primitive. A generated backend secret
authenticates Owner APIs; the browser keeps it only in memory. Clearing STOP does not promote autonomy:
mode remains Manual, advanced features remain unavailable. No provider, publish or payment route exists.
Phase 1 must reuse this policy boundary; Phase 2 must enforce it on admission and execution/cancellation.
Tests: unauthorized access, forbidden input, idempotency, stale versions, persistence and browser flow.

## ADR-FOUNDATION-003 — Authoritative documentation separated from source
**Status:** Implemented per Owner request, 2026-09-09

Move the 78 architecture/review Markdown files to `../architecture/`; keep the five original live
tracking files in this directory. Preserve source content, change only cross-folder document references,
and record original/current hashes in DOCUMENTATION_INDEX.json. Add root AGENTS/README entrypoints.
Local/CI checks reject missing documents and unreviewed architecture changes. Tracking files evolve
with implementation. No competing copies remain in the root. Any deliberate spec edit needs a logged
decision plus explicit hash update; automated checks never rewrite hashes.

## ADR-FOUNDATION-004 — Resolve inherited documentation identifiers
**Status:** Accepted, 2026-09-09

The inherited roadmap reuses phase 11–14 across v3/v4/v5; SRS also repeats FR numbers. Preserve original
normative text and use IMPLEMENTATION_PLAN.md's canonical phases 0–21. Reference repeated requirements
by document + section + title. This is naming/traceability repair, not a scope reduction.
V5's authorized provider-usage allowance does not grant outbound checkout/real-loan authority.

## ADR-FOUNDATION-005 — Lateral Cutaway Skyscraper Office & Procedural Animated Characters
**Status:** Implemented per Owner direction, 2026-09-09

Problem: The initial blueprint top-down circle avatar presentation did not provide depth, seniority hierarchy, or engaging character animation.
Choice: Switched 2D Office projection to a side-view cutaway multi-floor tower (cross-section architecture), inspired by simulation/pixel-art games (Space Haven, Anomaly President, Tiny Tower).
Hierarchical floors stacked from top to bottom by corporate seniority:
- Floor 4 (Penthouse / Executive Suite): Director / CEO (Sarah) with panoramic glass view, mahogany desk, and executive awards.
- Floor 3 (Research & Fact-Check Lab): Lead Researcher (Dr. Aris) and Fact Checker (Elena) with holographic network projection.
- Floor 2 (Creative Writing & Narrative Studio): Script Writer (Marcus) with cork storyboard and screenplay drafts.
- Floor 1 (Media Lab & Production Bay): Voice Artist (Lyra) in acoustic foam vocal booth & Video Editor (Kael) with triple monitors.
- Ground Floor / Level 0 (Infrastructure, Distribution & Lounge): Ollama & Cloud server racks with animated LEDs, Coffee lounge with rising steam, Release console (Vera), and working transparent elevator shaft with moving cabin.
Animated Characters (Personaje): Procedural sprite rendering with idle breathing, eye blinking, rapid typing when WORKING, glowing lightbulbs/sparks when THINKING, and responsive interactive click inspection.
Invariants: Visuals remain 100% data-driven projections of real SQLite state and live WebSocket domain events with zero simulated/fabricated state and strict CSP compliance.



## ADR-001 — Backend is the source of truth
**Status:** Accepted  
2D office is a projection of committed backend state/events.

## ADR-002 — Dynamic workforce
**Status:** Accepted  
Agents, roles, rooms and desks are data-driven.

## ADR-003 — Two-channel strategy
**Status:** Accepted  
Channel A = factual Shorts. Channel B = prior-day office serial.

## ADR-004 — Director as CEO
**Status:** Accepted  
Director manages operations within Owner-controlled guardrails.

## ADR-005 — Provider-agnostic integrations
**Status:** Accepted  
LLM/video/image/TTS/search/publishing are adapters.

## ADR-006 — Economy implementation is phased, architecture is core
**Status:** Superseded/Updated by V5  
The original economy placeholder has evolved into the core VR$ Treasury/Procurement architecture. Full implementation may follow the content MVP, but data contracts and hard money boundaries are first-class.

## ADR-007 — Multi-AI developer continuity
**Status:** Accepted  
Living documentation and explicit handoff are mandatory.

## ADR-008 — Intent/Capability/Outcome separation
**Status:** Accepted  
LLM statements never directly prove actions happened.

## ADR-009 — Durable workflow before full autonomy
**Status:** Accepted  
State, scheduler, retries and idempotency must be persistent.

## ADR-010 — Transactional event delivery
**Status:** Accepted  
Use outbox/equivalent to keep DB truth and UI events consistent.

## ADR-011 — Live dialogue vs serial dialogue separation
**Status:** Accepted  
Dramatized sitcom dialogue cannot enter operational logs.

## ADR-012 — Director cannot self-escalate
**Status:** Accepted  
Owner policy remains a higher immutable authority.

## ADR-013 — Local and always-on deployment modes
**Status:** Accepted  
Local PC is not assumed to run 24/7.

## ADR-014 — External web content is untrusted
**Status:** Accepted  
Prompt-injection/security boundary applies to research.

## ADR-015 — Media rights/provenance are first-class
**Status:** Accepted  
Assets need source/license/generation provenance.

## ADR-016 — Owner Policy Kernel
**Status:** Accepted  
Hard guardrails and approval rules are enforced outside Director prompts.

## ADR-017 — No hidden chain-of-thought dependency
**Status:** Accepted  
Store/display structured decision summaries, evidence and receipts, not private scratchpad reasoning.

## ADR-018 — Bounded multi-agent communication
**Status:** Accepted  
Agent message hops/rework loops have explicit limits and escalation.

## ADR-019 — Daily autonomous preflight
**Status:** Accepted  
Autonomous cycles check health, auth, quotas, budget, incidents and required providers before starting.

## ADR-020 — Admission control/backpressure
**Status:** Accepted  
Scheduler/orchestrator does not launch work beyond system/provider/budget capacity.

## ADR-021 — Public projection is separate
**Status:** Accepted  
Future fan UI consumes sanitized public projections, never raw internal event streams.

## ADR-022 — Technical identity separate from public character brand
**Status:** Accepted  
Provider/model names need not be public character names.

## ADR-023 — World Builder uses schema, not arbitrary UI code
**Status:** Accepted  
Director can evolve office only through supported backend world assets/layout operations.

## ADR-024 — Deterministic media fallback
**Status:** Accepted  
The studio must have a provider-independent fallback video format for resilient automation.

## ADR-025 — Multi-objective optimization
**Status:** Accepted  
Growth is optimized inside hard quality/rights/security/cost constraints.

## ADR-026 — CI/release pipeline outside content-agent autonomy
**Status:** Accepted  
Agents may optimize prompts/config but cannot autonomously deploy source-code changes.

## ADR-027 — Explicit privacy/data classification
**Status:** Accepted  
Internal/public/secret data boundaries are modeled and enforced.

## ADR-028 — Transfer-ready architecture
**Status:** Accepted  
Business assets/config should be exportable without personal credentials.


## ADR-V4-001 — Dynamic departments
**Status:** Accepted

The company may create/merge/dissolve departments through backend organization state; org chart is not hardcoded.

## ADR-V4-002 — Marketing becomes first-class future department
**Status:** Accepted

Marketing owns cross-platform communication and truthful teaser generation.

## ADR-V4-003 — Operational identity separate from narrative persona
**Status:** Accepted

Personality/birthday/relationships cannot modify permissions or factual standards.

## ADR-V4-004 — Company world events are separate truth category
**Status:** Accepted

Team building/birthdays can be committed in-universe events without being confused with physical operational facts.

## ADR-V4-005 — Organizational growth must resist bloat
**Status:** Accepted

CEO must justify new roles/departments using workload/value/cost evidence.


## ADR-V5-001 — VR$ is a one-to-one market-anchored virtual currency
**Status:** Accepted

Eligible verified USD inflows mint VR$ 1:1; actual USD operating costs and market-priced virtual purchases are represented 1:1. The studio does not autonomously spend real money.

## ADR-V5-002 — Three financial truth layers
**Status:** Accepted

External evidence, VR ledger, and forecasts are separate. Forecasts never directly become spendable cash.

## ADR-V5-003 — VendorShop uses market evidence but performs virtual purchases only
**Status:** Accepted

Procurement can research specific real products and prices, but checkout is never executed externally.

## ADR-V5-004 — Financing is virtual and reference-backed
**Status:** Accepted

CEO may use virtual financing with real-market reference terms, Finance/Legal/governance controls and real debt-service consequences inside the VR ledger.

## ADR-V5-005 — Asset Architect is downstream of purchase approval
**Status:** Accepted

A purchased product may become a persistent office-world asset only through an auditable specification and world-builder pipeline.

## ADR-PHASE1-001 — Ollama-first LLM adapter; stdlib HTTP; no async runtime
**Status:** Implemented, 2026-09-09

**Problem:** Phase 1 requires a real LLM connection. The project must not assume any particular provider.

**Choice:** Implemented Ollama as the first LLM adapter using Python stdlib `urllib.request` (synchronous HTTP). Async interface (`async def`) is used to satisfy the abstract contract, but the actual HTTP call is synchronous. `asyncio.run()` bridges the sync call from the synchronous service layer. This avoids introducing `httpx` or `aiohttp` as new dependencies before the durable worker layer (Phase 2) justifies them. The Ollama adapter returns `OFFLINE` (real status) if the process is not running — never a fabricated result.

**Alternatives rejected:**
- `httpx` async: adds dependency before Phase 2 worker needs it.
- `requests`: sync-only, no async interface.
- Mock-only path: violates "never mark as working based on mocks" rule.

**Migration:** When Phase 2 introduces an async worker, adapters can switch to async HTTP without interface changes (interface is already `async def`).

**Test impact:** `test_ollama_adapter.py` mocks `urlopen` for unit tests; real provider test is skip-marked until `STUDIO_OLLAMA_URL` is set.

**Rollback:** Remove `backend/app/providers/` and `backend/app/agents/` directories; revert migration to 0001_foundation.

## ADR-PHASE1-002 — Policy Kernel enforces all gates before every LLM run
**Status:** Implemented, 2026-09-09

**Choice:** A single `_assert_policy_allows_run()` function in `agents/services.py` enforces the complete gate sequence (autonomy_stop → lifecycle → capabilities → provider health) before any adapter call. Blocked runs are **persisted** in `agent_run` with a BLOCKED_* status — they are never silently dropped. This makes every policy decision auditable.

**Key invariant:** Director/Owner prompts cannot override the kernel; it runs in Python before the adapter is called.

**Test impact:** Tests directly verify each gate independently and verify the persisted blocked run record.

## ADR-PHASE2-001 — Durable Automation with Leases, Backoff, and Transactional Outbox
**Status:** Implemented, 2026-09-09

**Problem:** Unattended content production requires workflows and tasks that survive backend restarts, recover from crashed workers without duplicate side effects, route exhausted failures to a dead-letter queue, and stream events to clients reliably without ghost events on rollback.

**Choice:**
1. **Workflow State Machine:** Persisted in `workflow` & `workflow_step` tables tracking the 17 normative pipeline stages from `../architecture/47_STATE_MACHINE_SPECIFICATIONS.md`. Invalid transitions raise `InvalidStateTransitionError`.
2. **Task Queue with Time-Bounded Leases:** Workers acquire tasks atomically setting `lease_token` and `lease_expires_at`. Crashed workers' tasks are automatically reclaimed by other workers after lease expiry. Heartbeat extends active leases.
3. **Exponential Backoff & Dead-Letter Queue:** Retryable errors calculate exponential backoff (`backoff_seconds * 2^(attempts-1)`). Max attempts exhausted transition tasks to `DEAD_LETTER`. Operator intervention can revive them.
4. **Transactional Outbox:** Events are written with `append_event_with_outbox()` inside the active business transaction. Rollback discards both `domain_event` and `outbox_record`. Dispatcher pushes to WebSockets and marks `PUBLISHED`.
5. **WebSocket Gateway with Replay Protocol:** `/api/v1/ws` authenticates with Owner token, handles live push, and processes `replay` commands with `after_sequence` cursors so clients never lose state on reconnection.

**Test impact:** `tests/test_phase2_workflows.py` verifies all 10 automation capabilities.

## ADR-PHASE2-002 — Ollama Cloud Models & Dynamic Discovery
**Status:** Implemented, 2026-09-09

**Problem:** Ollama can run and proxy cloud-backed models (e.g. `glm-5.2:cloud`, `kimi-k2.6:cloud`, `qwen3-coder:480b-cloud`) in addition to local models. Newly available models must be continuously discoverable.

**Choice:**
1. `OllamaProvider` supports optional Bearer API key authentication and tags cloud models with `is_cloud=True`.
2. Added `sync_provider_models(engine, registry, provider_id)` service and `POST /api/v1/providers/{provider_id}/sync-models` endpoint.
3. Discovered models are recorded in `model_record`, automatically linked with `text_generation` capabilities, and emit `provider.model_discovered` domain events for auditability.
4. Models that are removed or unavailable are marked `is_available = False` rather than deleting historical records.

## ADR-PHASE3-001 — Lightweight 2D Canvas Office Rendering Engine
**Status:** Implemented, 2026-09-09

**Problem:** The Studio requires an interactive top-down 2D office visualization showing zones, desks, server racks with real-time blinking LEDs, agent avatars with state rings, and live speech bubbles, within strict resource limits (target <100MB RAM, 60fps, minimal bundle size). Heavy game frameworks would bloat the bundle size and introduce complex external dependencies.

**Choice:**
1. **Lightweight Canvas 2D Engine (`OfficeEngine`):** Pure HTML5 Canvas 2D implementation with custom `Viewport` supporting pan, smooth zoom (0.4x to 2.5x), DPI awareness (`devicePixelRatio`), and `fitToOffice()`. Total JS bundle remains tiny (~19 kB).
2. **Zero Simulated State:** Office state (`OfficeState`) strictly mirrors backend state retrieved from `GET /api/v1/office/layout` and updates via the live WebSocket `/api/v1/ws` event stream (`agent.state_changed`, `agent.paused`, `agent.resumed`, `agent.message_sent`, `workflow.*`).
3. **Data-Driven Zone & Desk Configuration:** Backend defines the 8 canonical production zones (`DIRECTOR`, `RESEARCH`, `SCRIPT`, `AUDIO`, `VIDEO`, `PUBLISH`, `SERVER`, `LOUNGE`) with fixed coordinate boundaries and desk positions.
4. **Direct Operator Controls:** Agent Inspector modal allows the Owner to inspect agent metrics, issue single tasks, and pause/resume agents via `POST /api/v1/agents/{id}/pause` and `POST /api/v1/agents/{id}/resume`.

**Test impact:** `tests/test_phase3_office.py` (backend layout, pause/resume) and `frontend/tests/office_engine.test.js` (viewport, office state) verify end-to-end functionality.

## ADR-PHASE4-001 — Factual Verification Matrix, Content Gate Hard-Stop, and Zone D Isolation
**Status:** Implemented, 2026-09-09

**Problem:** Content generated by autonomous AI agents easily suffers from hallucinated statistics, outdated facts, or prompt injection attacks embedded inside untrusted web sources. In addition, production channels must avoid spammy, repetitive content.

**Choice:**
1. **Zone D Sanitization & Inert Tag Boundary:** External web content is treated as untrusted (Zone D). Delimiters (`<|im_start|>`, `### System:`, etc.) are stripped, adversarial injection patterns (`ignore previous instructions`, `reveal system prompt`) are neutralized, and content is encapsulated within `<untrusted_source_evidence hash="...">` tags.
2. **Immutable Source Snapshots & SHA-256 Hashes:** Every ingested research document receives an immutable SHA-256 digest (`content_hash`) in `source_snapshot` to guarantee provenance and auditability.
3. **Atomic Claim Extraction & Verification Matrix:** Facts are extracted as individual `FactualClaim` records with explicit importance (`CRITICAL`, `SUPPORTING`, `FLAVOR`) and initial status `UNVERIFIED`. Fact Checkers independently verify each claim to `SUPPORTED` or `REFUTED`.
4. **Normative Content Gate:** In accordance with `../architecture/50_CONTENT_GATE_MATRIX.md`, the backend hard-blocks script generation (`FactualGateError`) whenever any referenced claim is `UNVERIFIED` or `REFUTED`. Blocked attempts are recorded as `BLOCKED_UNVERIFIED_CLAIMS` with domain event `factual.script_blocked_by_gate` for complete operator visibility.
5. **Deduplication Novelty Scoring:** Candidate topics are evaluated against recent historical topics (`../architecture/44_CONTENT_DEDUPLICATION_NOVELTY.md`) to compute a novelty score (0.1 to 1.0) and prevent repetitive content loops.
6. **Hook Optimization:** Formulates opening hook variations classified by proven psychological techniques (`CURIOSITY_GAP`, `CONTRARIAN`, `STATISTIC_SHOCK`, `STORY_IN_MEDIA_RES`) with estimated retention scores.

**Test impact:** `tests/test_phase4_factual.py` verifies all 8 factual intelligence invariants and endpoints.

## ADR-PHASE5-001 — Media Production Pipeline, Deterministic Synthesis, 9:16 Video Assembly, and 4-Tier QC Engine
**Status:** Implemented, 2026-09-09

**Problem:** The Studio must transform verified factual scripts into vertical 9:16 video shorts/reels (1080x1920) with synchronized speech, visual prompts, and subtitles, without depending on paid third-party media APIs during local testing, while strictly preventing visual factual errors and character drift.

**Choice:**
1. **Character Bible Foundation (`character_bible`):** Pre-seeded 7 core canonical studio employees (Sarah, Dr. Aris, Elena, Marcus, Lyra, Kael, Vera) with immutable visual descriptors, distinct hex color palettes, signature role symbols, and voice profiles.
2. **Deterministic Media Synthesis:** Developed `DeterministicVisualAdapter` (generating valid 1080x1920 SVG visual cards) and `DeterministicTTSAdapter` (synthesizing valid RIFF/WAVE audio bytes with exact duration and word alignment) to enable 100% reproducible, zero-paywall testing.
3. **Strict Content Gate Enforcement:** Storyboard generation strictly blocks unapproved scripts or scripts with unverified claims (`FactualGateError`), upholding normative truth invariants.
4. **Synchronized Subtitle Engine:** Formats scene cues and durations into standard SRT subtitle tracks for on-screen captioning.
5. **Video Assembly Engine & Cryptographic Provenance:** Assembles scene assets into vertical 9:16 MP4 containers via local FFmpeg (or standard ISO Base Media File container fallback) and computes an immutable SHA-256 digest (`provenance_hash`) recorded in `media_asset` and domain event `media.video_rendered`.
6. **Automated 4-Tier Quality Control (QC) Engine (`quality_control_report`):**
   - *Technical QC:* Verifies 1080x1920 resolution, 9:16 aspect ratio, non-zero duration, valid file size, and presence of SHA-256 provenance hash.
   - *Rights QC:* Verifies studio proprietary licensing and approved synthesis engines.
   - *Factual QC:* Verifies 100% of claims referenced across all scenes remain in `SUPPORTED` status.
   - *Character Drift QC:* Verifies characters adhere to Character Bible visual profiles without prohibited deviations.
7. **Frontend Media Production Modal (`#media-modal`):** Responsive dark-theme UI providing Storyboard pipeline inspection, interactive 9:16 video player preview, QC scorecard breakdown, and Character Bible viewer.

**Test impact:** `tests/test_phase5_media.py` (7 tests) and Playwright E2E verification test suite (`scratch/verify_phase5_e2e.mjs`) pass with 0 errors and 0 CSP violations.

## ADR-PHASE6-001 — Autonomous Publishing & Distribution, 5-Point Publishing Gate, Default Private Upload, and Idempotent Reconciliation
**Status:** Implemented, 2026-09-09

**Problem:** Autonomous AI Studio must publish finished 9:16 vertical video assets to official distribution channels (YouTube Shorts) without human intervention while strictly guaranteeing:
1. No unverified, un-QC'd, or policy-stopped content ever reaches public platforms.
2. Default upload privacy must remain `private` to avoid premature public exposure without human Owner policy clearance.
3. Zero duplicate uploads on network dropouts, retries, or server restarts.
4. No external paywalls or live credentials required for local CI test suites.

**Choice:**
1. **Channel Records & Brand Assets (`channel_record`, `channel_brand_asset`):** Pre-seeded Channel A (`MAIN_FACTUAL`) and Channel B (`OFFICE_SERIAL`) with canonical channel IDs and brand taglines, defaulting `upload_privacy_default="private"`.
2. **5-Point Publishing Gate Hard-Stop (`evaluate_publishing_gate`):**
   - *Autonomy Gate:* Blocks upload if Global Autonomy Stop is active (`OwnerPolicy.autonomy_stopped == True`).
   - *Disk Existence Gate:* Blocks upload if target file does not exist on disk or has 0 bytes.
   - *Quality Control Gate:* Blocks upload if `QualityControlReport` is missing or status is not `PASSED` (score < 0.90).
   - *Factual Integrity Gate:* Blocks upload if any factual claim associated with the video script is not in `SUPPORTED` status.
   - *Duplicate Protection Gate:* Blocks upload if media asset has already been published or is in-flight on the target channel.
3. **Official YouTube Data API v3 Adapter (`YouTubeProvider`):** Implements Google OAuth2 token refresh, resumable upload chunk protocol, synthetic media declaration flag, remote status polling, and title/idempotency key reconciliation before retry.
4. **Deterministic Publishing Adapter (`DeterministicPublishingAdapter`):** Provides zero-paywall simulated YouTube Shorts upload and status querying for reproducible local verification and CI.
5. **State Machine & Idempotency Guarantee (`publication_record`):**
   - Transition states: `DRAFT_INTENT` -> `VALIDATED` -> `STARTED` -> `REMOTE_CONFIRMED` -> `PUBLISHED` (with `REMOTE_UNKNOWN` and `FAILED_RETRYABLE`).
   - Hard DB Unique Constraint `uq_channel_idempotency` (`channel_id`, `idempotency_key`) prevents concurrent duplicate upload records.
   - Ambiguous timeouts (`REMOTE_UNKNOWN`) require reconciliation query against remote channel before any retry attempt is permitted.
6. **Frontend Distribution Hub Modal (`#publishing-modal`):** Responsive UI inside the 2D Office skyscraper providing channel inspection, 5-point gate status, 1-click private upload execution, and publication history with clickable YouTube Shorts links.

**Test impact:** `tests/test_phase6_publishing.py` (6 tests) and Playwright E2E UI verification suite (`scratch/verify_phase6_e2e.mjs`) pass with 100% success and 0 console errors.


---

## D-AUDIT-001 — Post-audit truthfulness remediation (2026-09-09)

**Problem:** An independent audit (`AUDIT_2026-09-09_EXTERNAL.md`) found that the system reported
external state it had invented. Specifically: channel slots were seeded with fabricated
`remote_channel_id` values and a hardcoded `CONFIGURED` status; a missing OAuth configuration fell
back silently to the simulator, which returned `https://youtube.com/shorts/yt_sim_…` and was stored
as `PUBLISHED`; the renderer wrote an `ftyp` header plus JSON to a `.mp4` file when FFmpeg was
absent; QC verified the resolution and duration that the renderer itself had written to the
database, so the fabricated file passed with score 1.0; the character-drift check returned a
hardcoded pass; and `POST /media/storyboards/sample` inserted a `SUPPORTED` factual claim with an
invented evidence URL. Together these satisfied the entire publishing gate with evidence the
application had authored for itself, violating `AGENTS.md` ("never mark a provider integration or
production feature working based on mocks") and `../architecture/26_MASTER_ACCEPTANCE_CRITERIA.md` §A, §E and §G.

**Choice — refuse rather than simulate.** Every layer now fails loudly instead of substituting a
plausible artefact:

1. **Channel identity is derived, never assumed.** Seeding creates *slots* with no remote ID, no
   credentials and status `NOT_CONFIGURED`. `derive_channel_status()` is the only writer of that
   field: `NOT_CONFIGURED` -> `AUTH_REQUIRED` (real remote ID present) -> `AUTHENTICATED`
   (credential reference present).
2. **No provider fallback at runtime.** `get_active_publisher()` returns the official adapter or
   raises 503 `PublisherNotConfigured` naming the three settings required. The simulator is
   reachable only through explicit injection (`app.state.publishing_provider`) in tests.
3. **Simulated results are structurally distinguishable.** `UploadResult.simulated`,
   `PublishingProvider.IS_SIMULATED`, `sim:` identifiers, empty platform URL, terminal state
   `PUBLISHED_SIMULATED`, event `publishing.video_published_simulated`. The UI links only genuine
   `youtube.com` URLs and labels a simulated run "SIMULAT (nepublicat)".
4. **A render either encodes or fails.** The placeholder-MP4 fallback is deleted. Scenes are
   rasterised to PPM frames and encoded by FFmpeg into a real H.264 1080x1920 file; without FFmpeg
   the job is recorded `FAILED` and `RenderEngineUnavailable` surfaces as 503. No `MediaAsset` is
   created for a failed render, so no gate can pass on a non-existent video.
5. **QC measures, it does not trust.** Technical QC reads the file with `ffprobe` (video stream,
   resolution, duration) and recomputes the SHA-256 provenance digest, and fails when declared and
   measured values disagree. A new content-source check fails assets built from placeholder
   visuals. Character drift reports `NOT_IMPLEMENTED` with `passed: null` rather than `true`.
6. **No self-authored evidence.** `POST /media/storyboards/sample` is replaced by
   `POST /media/storyboards/demo-fixture`, which creates the claim as `UNVERIFIED` and the script as
   `DRAFT`. A claim reaches `SUPPORTED` only through explicit verification.
7. **A refusal is an audit record.** `create_publication_intent` commits the `BLOCKED_GATE` row and
   its `publishing.gate_failed` event before raising, instead of raising inside the transaction and
   discarding both.

**Consequence, accepted deliberately:** with no image/TTS provider and no OAuth credentials, the
studio currently cannot publish anything. That is the true state of the system; the previous
behaviour concealed it behind a green demo.

**Test impact:** `tests/test_truthfulness_gates.py` (10 tests) locks each invariant above.
`test_phase5_media.py` skips render tests when FFmpeg is absent rather than certifying a fallback;
`test_phase6_publishing.py` asserts the 503 refusal and the simulated terminal state. Suite: 87
passed with FFmpeg, 85 passed / 3 skipped without it.

## D-AUDIT-002 — Corrections to the Phase 6 decision record (2026-09-09)

The Phase 6 entry above described behaviour the code did not have. For the record:

- "Pre-seeded … with canonical channel IDs" — those IDs (`UC_main_factual_studio_01`,
  `UC_office_serial_studio_02`) were invented and correspond to no YouTube channel. Superseded by
  D-AUDIT-001 §1.
- "score < 0.90" — the gate checked only `status == PASSED`; the score threshold was never
  evaluated. It is now enforced (`QC_MINIMUM_SCORE`).
- "resumable upload chunk protocol" — the adapter read the whole file into memory and issued a
  single `PUT` with no `Content-Range` and no 308 handling. Chunked resume is now implemented.
- "synthetic media declaration flag" — no such field was sent. `containsSyntheticMedia` plus a
  disclosure line in the description are now sent.
- "reconciliation … before any retry attempt is permitted" — `reconcile_upload()` was defined but
  never called from anywhere. It is now invoked before retrying a `FAILED_RETRYABLE` publication.
- "5-Point Publishing Gate" per `../architecture/50_CONTENT_GATE_MATRIX.md` — the matrix's publish column also
  requires rights on the final package, platform policy, novelty on final metadata, brand strategy,
  budget, and Channel B continuity and narrative privacy. Those remain unimplemented and the UI now
  says so.

## D-AUDIT-003 — Script approval as an explicit, re-checked step (2026-09-09)

**Problem:** `generate_script_draft()` writes `VERIFIED_PASS`; `generate_storyboard_from_script()`
accepts only `APPROVED`. No code path moved a draft between the two, so a script created through
the real API could never be storyboarded. The media pipeline was reachable only through the
fixture endpoint that wrote `APPROVED` directly alongside a self-authored `SUPPORTED` claim.

**Choice:** add `approve_script_draft()` and `POST /api/v1/factual/scripts/{id}/approve`. Approval
is an explicit Owner command, and it **re-evaluates the factual gate at approval time** rather than
trusting the verdict recorded when the draft was written — a claim may have been refuted since
(`../architecture/50_CONTENT_GATE_MATRIX.md`, gate immutability). A failed re-check moves the draft back to
`BLOCKED_UNVERIFIED_CLAIMS` and emits `factual.script_blocked_by_gate` with `at: "approval"`.

## D-AUDIT-004 — WebSocket dependency (2026-09-09)

**Problem:** the `/api/v1/ws` gateway was implemented and unit-tested, but the locked dependency set
contained no WebSocket library, so the running server answered every handshake with 404. The
feature was documented as working; in the browser it never once connected.

**Choice:** `websockets>=13,<16` is a first-class runtime dependency, not an optional extra. Adding
it to `pyproject.toml` and `uv.lock` makes the shipped configuration match the documented
behaviour. Verified in a real browser: the handshake succeeds and the console is clean.

## D-DESIGN-001 — One colour system for the whole interface (2026-09-09)

**Problem:** the application shipped two unrelated visual languages. The original template is a warm
editorial palette (paper `#f5f4ef`, forest `#172927`/`#254e43`, gold `#ddae6a`); every screen added
after Phase 3 — the agent inspector, research, media and publishing dialogs, the camera toolbar —
was written in a Tailwind slate/sky palette (`#0f172a`, `#1e293b`, `#38bdf8`, plus purple and
magenta accents). The stylesheet held 97 distinct colour literals with no tokens, so each new
feature invented its own.

**Choice:**

1. **Tokens are the only source of colour.** `:root` defines paper, ink, brand, semantic-state and
   scene tokens derived from the template. Component rules reference tokens; a new literal in a
   component is a defect, because that is exactly how the interface drifted apart.
2. **Dialogs use the page surface.** They are cards on the same paper as `.panel`, not a dark
   overlay theme. Verified in the browser: all three dialogs compute the same background colour as
   the panels behind them.
3. **Semantic colours carry meaning, not decoration.** Success / warning / alert / info exist as
   background+border+ink triples so that "published", "simulated", "blocked" and "validated" stay
   distinguishable at a glance — the honesty work of D-AUDIT-001 depends on that distinction being
   visible.
4. **The 2D office stays dark but joins the family.** It is a night-time interior, so it keeps its
   darkness; its structural literals were retinted from slate blue to the brand's deep greens and it
   is framed like the template's office scene. Per-department accents (research screens, storyboard
   cork, audio meter, distribution console) and character details were deliberately left alone:
   they encode which floor you are looking at.
5. **No pictographic icons.** The emoji added to buttons, headings and badges were removed; only the
   template's typographic glyphs remain, and they inherit token colours. Labels were rewritten in
   sentence case.
6. **Contrast is measured, not assumed.** `scratch/verify_design.mjs` reads computed styles from the
   running page and fails below WCAG AA (4.5:1). Three tokens were darkened when it caught them.

**Test impact:** `scratch/verify_design.mjs` — 14/14 checks pass, worst pairing 4.87:1.
`scratch/verify_post_audit_e2e.mjs` — 27/27 unchanged. TypeScript check, Vite build and the six
frontend tests pass.

## D-DESIGN-002 — Office renderer rebuilt (2026-09-09)

**Problem:** the 2D office was thin: flat rooms, a handful of props, characters with almost no
individuality, and a scene that stopped at the building's edge. It also carried 82 ad-hoc colour
literals from the pre-audit palette.

**Choice:** `frontend/src/office_engine.js` was rewritten around four ideas.

1. **The backend stays the truth.** The renderer draws the zones, desks and agents the API
   reports, and posture comes only from `runtime_state` and `lifecycle`: WORKING types, THINKING
   holds a thought, PAUSED sleeps, everything else idles. Idle characters breathe, blink, sip and
   stretch — cosmetic motion that deliberately never includes typing, so no viewer can read
   activity into an idle studio. Screens, VU meters and the ON AIR lamp light up only for zones
   that actually contain a working agent.
2. **Scenery is labelled scenery.** Sky, skyline, traffic, trees and pedestrians are generated
   from fixed seeds and are wired to nothing. A passing car reports no event. This is stated at
   the top of the file so the next contributor does not attach data to it.
3. **Deterministic variety.** Every face, outfit, lit window and leaning tree comes from a hash of
   a stable id, so the studio looks rich but identical on each reload, and `Math.random()` appears
   nowhere. Seven agents produce seven distinct people from the same code path.
4. **Crisp pixels and a predictable frame cost.** The world is drawn once at 1:1 into an offscreen
   buffer and blitted with image smoothing disabled, so zooming enlarges pixels instead of
   blurring them. Static art (sky, skyline, building shell, furniture) is rasterised once into
   cached layers; only moving things are redrawn. Clouds are composited between the sky layer and
   the building layer, which is what stops them drifting through the offices.

The building now stands on a street: the horizon is derived from the backend building box rather
than fixed, which is what previously drew the road through the ground floor.

**Test impact:** `scratch/verify_design.mjs` 14/14, `scratch/verify_fullscreen.mjs` 10/10,
`scratch/verify_post_audit_e2e.mjs` 27/27, frontend unit tests 6/6, no console errors.

## D-DESIGN-003 — Scene corrections: scale, street, lift and the shop unit (2026-09-09)

Four defects reported against the first renderer pass, and what each one required.

**1. Pedestrians walked through the ground floor.** The pavement was drawn at the horizon while
the building's base also sat there, so passers-by overlapped the studio. The street is now a
stack below the base course — plinth, pavement, kerb, carriageway, far pavement — and the
standing line is placed so the tallest pedestrian clears the building entirely. The rule is
enforced by `streetGeometry()`, which is exported and unit-tested rather than checked by eye.

**2. The lift moved with nobody in it.** The cab used to sweep the shaft on a sine wave, which
showed motion the backend had never reported. It is now parked with its doors shut and reads
IDLE. It travels only when a workflow token changes to a stage on a different floor — the
project physically moving between departments — then waits at the delivery floor and returns to
the ground floor. With no workflow running, the lift never moves.

**3. Vehicles were half-scale.** A person is 34px tall in this scene, so a car is about 90px long
and 30px tall, a van taller, a bus 168px. Wheels, glazing and lamps were resized with them, and
the carriageway was deepened to 118px to hold two lanes. Street lamps were also cut back to the
building's flanks: a column across the open cutaway hid the studio behind it.

**4. Names were unreadable.** Nameplates now draw the name at double scale on an opaque plate
with a drop shadow, with the backend state in small type beneath it.

**Ground floor.** Made double height (200px, backend layout) and re-divided to add `ad_shop`, a
street-facing unit for selling advertising space: glazed front, awning, rate boards, counter.
It has no desks, so the renderer places no character in it — the shop is not staffed until the
backend says it is. The building grew to 740px and the layout to 1000px tall; the office layout
test now also asserts that zones on a floor do not overlap and that every desk stands on its
own zone's slab.

## D-DOC-001 — Documentation identifiers made unique (2026-09-10)

**Problem:** two documentation defects blocked unambiguous references. (1) `16_DECISION_LOG.md`
carried a byte-identical duplicate of the whole ADR-001…ADR-V5-003 block (an edit accident), so
every early decision appeared twice. (2) In `../architecture/02_SRS.md` the "v3 Additional
Functional Requirements" block reused identifiers FR-037…FR-066 that already exist in the base
list, so a citation like "FR-037" was ambiguous (base "Untrusted web content" vs v3 "Policy
Kernel"). ADR-FOUNDATION-004 had recorded the collision and prescribed citing by document +
section + title; the Owner then directed the collision be removed outright.

**Choice:**

1. **Decision log deduplicated.** The second copy of ADR-001…ADR-V5-003 was deleted verbatim
   (verified byte-identical before removal); ADR-V5-004/005 and all later entries were single
   occurrences and are untouched.
2. **SRS v3 block namespaced, not renumbered.** The v3 additional FRs are now
   `FR-V3-037…FR-V3-066`, mirroring the established `FR-V4-…` and `FR-ECON-…` namespaces in the
   same file while preserving the numeric suffix, so the historical mapping stays readable.
   Base FR-001…068 are untouched and now unique. NFR-013…021 never collided and keep their
   numbers. The normative text of every requirement is unchanged.
3. **Cross-references updated.** `../architecture/V3_FILE_BY_FILE_REVIEW.md` notes the rename next to its
   historical "Added FR-037–060" record; `../project/IMPLEMENTATION_PLAN.md` marks the recorded
   conflict resolved.
4. **Indexed hashes updated explicitly** for the two deliberately edited architecture documents
   (`../architecture/02_SRS.md`, `../architecture/V3_FILE_BY_FILE_REVIEW.md`) in `../project/DOCUMENTATION_INDEX.json`, per
   AGENTS.md; `original_sha256` values are preserved.

**Alternatives rejected:** renumbering the v3 block sequentially from FR-069 (breaks the visible
correspondence with the v3 revision record and collides with nothing today but reads as new
requirements rather than renamed ones); renumbering the base list (every existing citation in
tracking documents would silently change meaning).

**Test impact:** `scripts/check_docs.py` and `tests/test_documentation.py` pass with the updated
index; no requirement text changed, so no product tests are affected.

## D-TRUTH-002 — The seed may write intent, never observation (2026-09-10)

**Problem:** an independent re-audit of the whole tree found the original falsehood pattern
still alive in one place the earlier audit had not reached. `seed_initial_workforce` wrote,
at bootstrap and without contacting anything:

- `provider_record`: `local-ollama` at `http://127.0.0.1:11434` with `status = 'HEALTHY'` and
  `last_health_check = <now>`;
- `model_record`: `glm-5.2:cloud`, `kimi-k2.6:cloud`, `qwen3-coder:480b-cloud` with
  `is_available = 1`, `last_verified = <now>` and `discovery_method = 'DECLARED_BY_PROVIDER'`.

Nothing in that function makes a network call, so on a machine where Ollama is not installed
the studio still displayed a healthy provider health-checked at a precise timestamp and three
models verified at a precise timestamp. This is the same defect the Owner originally reported
as "it says the YouTube channel is configured, but it is not", reproduced against a different
subsystem. It was verified by inspection of a freshly bootstrapped database on a host with no
Ollama: the rows above were present exactly as described.

Two consequences made it worse than a cosmetic lie. The seeded provider had no adapter
registered at startup — `load_registry` only registers Settings integrations — so both the
health check and the model sync failed with "no adapter registered", and the Owner had **no
way at all** to replace the seeded claim with a measured one. And any agent assigned to those
"available" models failed at run time with the same message, while the interface said the
model was ready.

**Choice:**

1. **The seed records intent only.** The provider is written `NOT_CONFIGURED` with
   `last_health_check = NULL`; the models are written `is_available = False`,
   `last_verified = NULL` and `discovery_method = 'SEEDED_UNVERIFIED'` — a new value that says
   what is true, namely that this list came from configuration and not from the provider.
2. **`sync_provider_models` is the only path to a positive claim.** It is the only code that
   calls the endpoint, so it is now the only code that may set `provider.status = 'HEALTHY'`,
   stamp `last_verified`, or promote a row to `DECLARED_BY_PROVIDER`. It raises on failure,
   so reaching those lines means the endpoint answered.
3. **The Owner gets a working control.** `register_seeded_ollama` registers a live adapter for
   every seeded OLLAMA provider at startup (registering an adapter asserts nothing about
   whether the service is running), `GET /settings` returns those providers as
   `legacy_providers`, and Settings renders a card for each with a "Verifică și încarcă
   modelele" button. Until it is pressed the card states plainly that the endpoint has never
   been contacted and its models cannot be assigned yet.
4. **A failure says what failed.** `POST /providers/{id}/sync-models` maps a connection error
   to HTTP 503 with "Furnizorul nu a răspuns, deci nu s-a înregistrat niciun model" instead of
   a generic 500, and the frontend now shows the server's own detail for `/providers` as it
   already did for `/settings`.
5. **Migration `0009_unverified_seeded_provider`** withdraws the claim from databases that
   already carry it, in the conservative direction: an owner whose Ollama really is running
   restores the true state with one click, whereas leaving the row alone would keep asserting
   something false on every machine where it is not. Rows the provider genuinely declared
   during a sync are left untouched.

**Alternatives rejected:** probing Ollama during bootstrap (bootstrap must not depend on the
network, and a slow or hanging endpoint would block first start); leaving the models available
and merely relabelling the provider (the availability flag is what the Settings dropdown reads,
so the lie would survive where it actually matters); deleting the seeded rows entirely (the
Owner would lose the record of which models the studio expects, and the agents' assignments
with it).

**Test impact:** six new governance tests in `tests/test_truthfulness_gates.py` — the seed
claims neither health nor availability; a model becomes available only after the provider names
it, and only that model; a failed sync upgrades nothing; the seeded provider is checkable; an
unreachable provider reports 503 with an actionable message. `scratch/verify_provider_honesty.mjs`
checks the same rules through the running interface (8/8).

## D-P7-001 — Phase 7 analytics wired, with the simulator removed (2026-09-10)

**Problem:** roughly 40 KB of analytics code sat on disk passing ruff, mypy and pytest while
never executing: `main.py` did not mount the router, the models were absent from
`Base.metadata`, and no migration created the tables. Wiring it as it stood would have been
worse than leaving it dead. `get_analytics_provider()` fell back to
`DeterministicAnalyticsAdapter`, which manufactures 1,500–65,000 views, 40–75% retention and
3.5–11% CTR by hashing a video id. `ingest_publication_metrics` then took
`pub.remote_video_id or pub.id`, so a publication that was never uploaded would have been
"measured" under its internal row id. The numbers would not merely have been displayed: the
learning loop reads them back, turns them into Director recommendations, and those change the
topic and hook weights the studio writes to. A fabricated view count would have steered real
editorial decisions.

**Choice:**

1. **The simulator is gone.** `backend/app/providers/deterministic_analytics.py` was deleted,
   and a test asserts the module cannot be imported. Analytics report what a platform
   measured; there is no local substitute for that, so there is no fallback to reach for.
2. **No provider means HTTP 503**, with the same shape as publishing: `get_analytics_provider`
   returns the YouTube Analytics adapter built from a **VERIFIED** YouTube connection (or the
   pre-Settings environment credentials) and otherwise refuses, saying in the response that the
   studio does not estimate or simulate audience figures. Tests inject their own adapter
   through `app.state.analytics_provider`; production has no such door.
3. **Nothing is measured that does not exist.** Ingestion refuses (409) unless the publication
   is `PUBLISHED` and carries a real `remote_video_id`; the internal-id fallback is removed.
   A provider failure is a 502 and stores nothing.
4. **The YouTube adapter stopped ignoring the window.** It used to send a fixed
   2024-01-01…2026-12-31 range for every query, so a report stored as "24h" or "7d" covered all
   time. Each window now maps to the date range actually requested. Impressions and CTR come
   from the `impressions` and `impressionClickThroughRate` metrics; when the account does not
   return them the adapter retries with the core metrics and reports zero with
   `raw["impressions_reported"] = false`, instead of back-computing impressions from views as
   before. `total_videos` is no longer guessed from the row count, and the channel report's
   subscriber figure is labelled in `raw` as the net change over the window, which is what it is.
5. **`seed_default_strategy` fixed and called.** It pointed at two hardcoded channel ids that
   no database ever had, so the strategy would have been orphaned; it now looks channels up by
   `channel_type`, and `scripts/bootstrap.py` runs it. Every seeded weight is 1.0: the baseline
   expresses no preference because nothing has been measured.
6. **Migration `0010_phase7_analytics`** creates the four tables with the invariants as database
   constraints, not only service checks: a snapshot cannot store a negative count or a retention
   outside 0–100, and a recommendation cannot exist with fewer than three observations or a
   weight change beyond ±0.20.

**Alternatives rejected:** keeping the deterministic adapter behind a flag (a flag that can be
turned on is a fabrication that will eventually be believed, and this data feeds a control
loop); leaving the module unwired (the Owner cannot see the analytics they were promised, and
dead code drifts); shipping a UI panel in the same change (there is nothing true to show until
a channel is connected).

**Test impact:** `tests/test_phase7_analytics.py`, 11 tests. Total 163 passed, 1 skipped.

## D-UI-004 — The lift carries a visible courier; the ground floor got its volume (2026-09-10)

**Problem:** three defects in the same part of the scene.

1. The cab moved between floors with nobody in it and its **doors parted while travelling** —
   backwards from how a lift behaves.
2. The **ground floor read as emptier than the floors above** despite holding four departments.
   It is 200px tall against 130px upstairs, but every fixture stopped at desk height, leaving
   the top two thirds of a double-height volume bare.
3. `STAGE_COORDINATES` in `office_state.js` was a table of **hardcoded pixel positions that no
   longer matched the building**. After the rebuild, `RESEARCH` at y=140 landed in the executive
   suite, everything from asset generation to QC landed in the script room, and
   `READY_TO_PUBLISH` at x=1010 sat outside the wall, in the lift shaft. This was not only
   cosmetic: the lift is dispatched by which zone a token lands in, so the wrong coordinates
   sent the cab to the wrong floor.

**Choice:**

1. **The token's journey is drawn as a journey.** A floor change now runs a four-stage
   delivery: `summon` (the cab comes to the floor the work is on while a runner walks to the
   doors), `board` (doors open, the runner steps into the shaft), `travel` (doors shut, the cab
   carries the runner, visible through the glass), `alight` (doors open, the runner walks the
   work to where the token now sits). Doors part only while the cab is standing at a floor.
   The runner is not an agent and carries no name — it holds the same crate the token is drawn
   as, and the token is not drawn twice. Every stage descends from the one backend fact that a
   token changed floor; with no workflow running the cab still stands still with its doors shut.
   A second floor change is not started until the current delivery finishes.
2. **The tall ground floor is built.** `drawTallVolume` adds what a double-height street-level
   volume actually has above head height: exposed ducting on hanger straps, a service mezzanine
   with a railing, and pendant lights on their drops. `drawTallVolumeSign` mounts one fixture
   per department above the rail — a rack status wall for infra, a clock and corkboard for the
   commons, a dispatch board for publishing, an empty hoarding reading "YOUR AD HERE" over the
   shopfront. All of it is architecture: no fixture displays a figure, because a board showing
   numbers here would assert something the backend has not said.
3. **Stage placement asks the layout.** `STAGE_ZONES` maps each stage to a department *by the
   zone id the backend serves*, and the position is computed from that zone's own desks. A
   token is not placed at all until a layout has arrived — a guessed position is worse than
   none.

**Test impact:** six new frontend tests (17 total) covering the still cab, the full delivery
cycle, doors shut in transit, one delivery at a time, every stage landing inside a real
department, and no placement before the layout. `scratch/verify_lift_courier.mjs` drives the
running page through a real delivery and reads the engine's own trip state back (9/9).

## D-P4-002 — The research loop is reachable, and verification is independent (2026-09-10)

**Problem:** the whole Phase 4 chain existed in the backend and could not be driven by the
Owner. Sources could only be fetched by a shell script (`scripts/research_source.py`); there
was no endpoint to retrieve one, no way to list stored sources, and the Research panel showed
topics only. Verification had no interface at all. The first product milestone — manual topic →
real research → verified claims → script — was therefore unreachable through the product.

A separate defect sat inside the same area. `VerifyClaimCommand` takes a verdict, so any
"verify" control has to supply one. The obvious design — a single button that marks a claim
checked — would be a verdict with nothing behind it, and FR-038 asks the fact-check path to be
independent of the research path. Nothing recorded who extracted a claim, so that independence
could be asserted in a docstring but never enforced or audited.

**Choice:**

1. **The allowlist is configuration, not application state.** `STUDIO_RESEARCH_ALLOWED_HOSTS`
   in `.env`, empty by default, which disables retrieval entirely rather than meaning
   "anywhere". No endpoint, form or agent can extend it, and the retrieve command deliberately
   carries no host field — a request-supplied allowlist is not an allowlist. Both the settings
   validator and `RetrievalPolicy` now also refuse an entry naming this machine or a private
   range, so a mistyped or hostile configuration fails at start-up instead of turning the
   research feature into a reader of internal services.
2. **`POST /factual/sources/retrieve` and `GET /factual/sources`.** Each failure is reported as
   itself: 503 with no allowlist, 422 for a host outside it, 429 for a rate limit that is
   respected rather than worked around, 502 when the source does not answer. In every one of
   them nothing is stored. A stored source carries `credibility_score = 0` and a receipt with
   the digests of the bytes received and the text extracted, so any figure on screen can be
   traced to what was actually downloaded.
3. **Claim attribution (migration `0011`).** `extracted_by_agent_id` and
   `verified_by_agent_id`, both nullable, because a claim the Owner judged has no agent behind
   it and a placeholder id would be a fabricated record.
4. **`POST /factual/claims/{id}/verify-with-agent`.** A second agent — never the one that
   extracted the claim — reads the stored source and returns a verdict. Two things make it a
   check rather than a formality: the studio refuses (409) when no independent agent exists,
   instead of letting an agent confirm its own reading; and a SUPPORTED or REFUTED verdict must
   quote the source verbatim, matched against the stored text on words rather than formatting.
   **A verdict whose quote is not in the source is rejected whole and the claim stays
   UNVERIFIED** — a fluent verdict resting on invented evidence is indistinguishable from an
   invention, so it is thrown away rather than stored with a caveat. UNCERTAIN was added as a
   real outcome so a checker that finds nothing can say so instead of guessing.
5. **The panel offers both honest routes** — the agent fact-check, and the Owner's own recorded
   verdict with notes and an optional quote — and no single "mark verified" control. Each claim
   shows its status, the evidence under it, and whether an agent or the Owner decided.

**Alternatives rejected:** letting the request name an allowed host (the allowlist would be
whatever the caller says); a one-click verify (a verdict with no reasoning, and the content gate
downstream would then be gating on nothing); accepting a paraphrased quote (paraphrase is where
an invention hides); storing a rejected verdict with a warning flag (a stored SUPPORTED is read
back by the gate, and a caveat in a neighbouring column does not travel with it).

**Test impact:** `tests/test_research_ingestion.py` (19) and `tests/test_claim_verification.py`
(15). Total 199 passed, 1 skipped. `scratch/verify_research_loop.mjs` drives the panel through
refusal, retrieval, extraction and verdict (18/18).

## D-UI-005 — The agent inspector showed a model nobody had assigned (2026-09-10)

**Problem:** reported by the Owner — choosing a model per agent in Settings changed nothing in
the agent's panel. Two independent causes.

1. `index.html` carried `<strong id="inspector-model">glm-5.2:cloud</strong>` and `showInspector`
   never touched that element. Every agent displayed the same hardcoded string forever,
   whatever was assigned. The office layout did not carry a model at all, so there was nothing
   truthful to display even if the field had been filled.
2. `loadOfficeLayout()` ran once, at login. Even a correct field would have shown the state from
   before the change until the page was reloaded.

**Choice:** each office assignment now carries `model_id`, `model_name`, `provider_name` and
`model_is_available`, and the inspector renders three distinct states — no model assigned, a
model assigned on a provider that has never answered ("· neverificat"), and a model the provider
confirmed. Only the last enables the run button, because only the last can actually run.
Settings calls back into the app after every successful change and on close, so the office
reloads.

A third defect surfaced while testing this: `api()` replaced the server's explanation with
"Conexiunea nu a putut fi verificată" for every path except `/settings` and `/providers`. Every
refusal this backend writes is a sentence meant for the Owner — which host is not authorised,
why a provider did not answer — so the server's own detail is now preferred wherever there is
one, with the generic wording as the fallback.

**Test impact:** two tests in `tests/test_phase3_office.py` asserting each assignment carries its
own model and that availability is reported as the provider left it;
`scratch/verify_agent_model.mjs` opens all seven agents in the running page and compares each
against the backend (9/9).

## D-P4-003 — Scripts are written from verified claims, and cite them scene by scene (2026-09-10)

**Problem:** the last link of the Phase 4 chain was unreachable. `POST /factual/scripts/generate`
requires the full voiceover text and a list of claim ids, so the only way to produce a script was
to write it by hand and pass the ids by `curl`. Nothing in the product drafted one, nothing
displayed one, and the approval endpoint — which re-runs the factual gate — had no control at
all. With phases 0–3 usable and verification now reachable, this was the single step still
standing between the Owner and the Master Prompt's first product milestone.

The interesting question was not how to call an LLM for the text. It was what stops the text from
containing facts the evidence does not carry. A model writing "Hubble, launched in 1990 at a cost
of 4.7 billion dollars" from a claim about the launch year produces one true clause and one
invented one, in the same sentence, and the factual gate downstream cannot see it: the gate
checks the claim ids a draft cites, not the prose.

**Choice:**

1. **Only SUPPORTED claims reach the writer.** `agent_write_script` selects the topic's claims
   with status SUPPORTED and refuses (409) when there are none — a topic whose claims are all
   unverified has nothing truthful to write from, and a draft written anyway would only be
   blocked later, after the Owner had read it.
2. **Every scene names the claims it rests on.** The agent returns scenes, each with its
   narration and a `claim_ids` list, and the schema refuses a scene with an empty one. A framing
   sentence attaches to the claim it frames; there is no "non-factual scene" escape hatch,
   because that is precisely where an unsourced assertion would live.
3. **A citation that was not supplied rejects the whole draft.** Not the offending scene — the
   whole draft. An identifier the writer did not receive means that scene's narration came from
   somewhere other than the evidence, and there is no way to tell how far that reaches into the
   sentences around it. Nothing is stored, and the message names the scene.
4. **The stored voiceover is assembled from the scene narrations**, so the text the studio will
   speak is exactly the text that carries an attribution. It is not a separate field the model
   could fill with something else.
5. **The draft cites only the claims it used**, not every claim it was given: citing the whole
   catalogue regardless of use would make the attribution decorative.
6. **The panel shows a script scene by scene** with its citation counts and status, and offers
   approval only on a draft that has passed the gate. Approval re-runs the gate, and its refusal
   now says how many claims stopped being supported instead of returning a raw exception string.

**Alternatives rejected:** dropping an unattributable scene and keeping the rest (the remaining
prose was written by the same pass, under the same misapprehension); letting the model return a
free-form voiceover and attributing it afterwards (attribution reconstructed after the fact is a
guess); allowing scenes with no claims for hooks and outros (the hook is the most-watched
sentence in a short, and the least supervised place to put an invention).

**Test impact:** `tests/test_script_writing.py`, 12 tests. Total 211 passed, 1 skipped.
`scratch/verify_script_loop.mjs` drives the chain in the running page: no supported claim → no
script, gate blocks a draft citing an unverified claim, a fully supported draft passes, and
approval fails once a cited claim is refuted (11/11).

## D-P5-002 — Media adapters built ahead of the credentials, with the placeholder label intact (2026-09-10)

**Context:** the Owner will supply media credentials themselves, later. The work that can be
done before then is the part that decides what happens once they arrive, and that is where the
truthfulness risk sits — not in the HTTP calls.

**Problem:** `assemble_video_job` constructed `DeterministicVisualAdapter` and
`DeterministicTTSAdapter` directly, so a render was always placeholder content no matter what the
Owner configured, and the media entries in the Settings catalogue said as much ("Generarea nu este
încă conectată"). Wiring providers in naively would have created two new ways to lie: an adapter
that returned a plausible substitute when a vendor failed, and a render that kept the
placeholder label after real frames were used, or lost it before they were.

**Choice:**

1. **Adapters return what arrived, or raise.** `ElevenLabsTTSAdapter` and `OpenAIImageAdapter`
   call documented endpoints over HTTPS with bounded response sizes. A failure raises; there is
   no fallback asset, because a substitute would enter the pipeline and be reasoned about by QC
   and the publishing gate as though a vendor had produced it.
2. **Every number is measured from the bytes.** An MP3's duration is counted by walking its
   frame headers (`mp3_duration_seconds`), a WAV's from its own header, and an image's size is
   read from the PNG header — not taken from what was requested. The assembler cuts video to
   those durations, so a length estimated from the word count would desynchronise picture and
   voice while looking like a measurement. Where a vendor genuinely offers nothing — ElevenLabs
   returns no word alignment on this endpoint, the Images API takes no seed — the adapter
   reports nothing rather than echoing the request back as if it had applied.
3. **A URL-only image response raises** instead of being followed: fetching it would be a second,
   unvalidated request to whatever host the response named.
4. **Only a verified *and* selected provider is used.** `app/media/factory.py` resolves the
   integration chosen for the "image" and "voice" purposes and uses it only at `VERIFIED` or
   `ACCESS_VERIFIED` — the same rule publishing and analytics follow. `SAVED` means the key was
   typed in, not that the vendor accepted it, and a render started on unaccepted credentials
   would fail mid-pipeline after the Owner had been told it was under way. A catalogued vendor
   with no adapter yet (Runway) resolves to no provider: that is "no generator", not a silent
   substitution.
5. **The recorded provider name is the generator that actually made the frames.** One value
   drives the asset's `provider_name`, the `media.video_rendered` event and the QC report. With
   no provider the render still happens — a video to look at — and is labelled placeholder, so
   `content_source_qc` blocks it from publication exactly as before.
6. **Provider narration is joined by ffmpeg, not by byte surgery.** The placeholder path can
   splice raw WAV bodies because it produced them; a vendor's audio is whatever it encoded, and
   concatenating that by hand would corrupt a differing format silently.
7. **`GET /media/providers`** reports which generators a render would use, and states plainly
   that renders are not publishable without a verified image provider. It probes nothing, so it
   never asserts reachability — only what the Owner selected and verified.

**Alternatives rejected:** falling back to a placeholder when a vendor call fails (the render
would appear to have succeeded and the label would be the only trace); reporting the requested
image size (a provider may return another, and the asset would carry a measurement nobody took);
estimating narration duration from the text (the figure feeds the cut).

**Test impact:** `tests/test_media_providers.py` (18) and `tests/test_media_selection.py` (12),
including a full render proving that the placeholder block lifts only when a real generator made
the frames, and that the asset names it. Total 241 passed, 1 skipped.

## D-P5-003 — Research hands work to production, and the render says what it will be (2026-09-10)

**Problem:** with Phase 4 usable end to end, the chain stopped at approval. An Owner who had just
approved a real script — sources fetched, claims verified by a second agent, citations checked —
opened Producție media and found no way to carry it forward. The only creation control there was
"Creează fixture demo", which builds test data with a deliberately unverified claim. The two
halves of the studio were joined by a fixture.

A second, quieter problem sat next to it. Renders are placeholder content until the Owner
configures a media provider, and QC blocks placeholder content from publication. That is correct,
but the Owner only discovered it *after* pressing Randare and reading a failed QC report.

**Choice:**

1. **`GET /media/scripts/awaiting-storyboard`** lists approved drafts no storyboard has been
   built from, and the Media panel shows them as the first thing in the pipeline, with the scene
   count and the number of verified claims each rests on. Only APPROVED drafts appear: approval
   is what passing the factual gate means, and offering a draft that had not passed would invite
   starting production on unverified claims. A script leaves the queue as soon as its storyboard
   exists, so nothing is produced twice by accident.
2. **The storyboard is built from the panel**, through the same endpoint and the same gate as
   before. A refusal is shown as it comes back — the gate runs again at this step, and a claim
   refuted since approval must stop production here too.
3. **The render says what it will be before it is asked for.** The panel reads
   `GET /media/providers` on open and states plainly, as a warning, that without a verified image
   provider the output is placeholder content that QC will block. Learning that from a failed QC
   report is a worse way to learn it, and the fact is knowable in advance.
4. Approving a script in Cercetare now refreshes the production queue, so the handover is visible
   without reloading.

**Alternatives rejected:** letting production pick up any script and relying on the gate to stop
it later (the Owner would have built a storyboard, waited for a render and read a QC failure to
learn something the studio knew at the start); hiding the demo fixture (it is genuinely useful
for exercising the factual gate, and it is labelled as a fixture).

**Test impact:** three tests in `tests/test_media_selection.py` — only approved scripts are
offered, a script in production leaves the queue, and the endpoint is reachable. Total 244
passed, 1 skipped. `scratch/verify_production_handover.mjs` drives approval → queue → storyboard
→ render in the running page and confirms the asset is labelled placeholder and blocked by QC
(11/11).

## D-P8-001 — The studio may recommend changes to its own staff, and nothing more (2026-09-10)

**Problem:** Phase 8 asks for evidence-driven workforce changes. This is the most consequential
thing the studio can recommend, and the two obvious ways to build it are both wrong. Asking a
model what it thinks of an employee produces a fluent judgement with nothing under it. Letting
the studio act on its own conclusion makes an unaudited recommendation into a decision.

**Choice:**

1. **Evidence is counted, never asked for.** `measure_workforce` reads rows the studio already
   has — agent runs and their outcomes over a 30-day window, task queue backlog, dead-lettered
   tasks. No model is consulted about a colleague. The same call at the same moment always
   yields the same numbers, so a proposal can be re-derived from them.
2. **An unmeasured agent is unmeasured, not perfect.** An agent with no runs has
   `failure_rate: None`, not `0.0`. Zero would read as a flawless record and could support a
   favourable judgement nobody earned; the panel says "nicio rulare în fereastră".
3. **A small sample never becomes a recommendation.** Fewer than five runs in the window
   produces nothing, at any failure rate — four failures out of four is a bad day. The service
   refuses to build such a proposal and a CHECK constraint refuses to store one, so the rule
   survives a future caller that forgets it.
4. **The proposal carries its own evidence.** `evidence_json` holds the counts, the window and
   the status breakdown as they were read, and the panel displays them rather than only the
   conclusion. "The studio recommended it" is not something anyone can audit six weeks later.
5. **Failure proposes suspension, not termination.** A run fails for reasons that are usually
   the model or the provider rather than the person doing the work, and suspension is
   reversible. Termination exists but is not something the measurements reach for.
6. **The Owner decides, and `decide_proposal` will not let a caller pass for the Owner by
   omission.** It takes an explicit `owner_decision` flag and raises `AutonomousChangeBlocked`
   when a non-Owner approves — raised, not quietly downgraded to a pending proposal, so a caller
   that expected the change cannot continue as though it happened. Rejection requires a written
   reason: an applied change leaves its own trail in the event log, a refusal leaves none.
7. **Employment is a record, not a column.** `employment_record` gives each period of work its
   own row. `../architecture/47_STATE_MACHINE_SPECIFICATIONS.md` forbids TERMINATED becoming ACTIVE by editing
   state; a rehire opens a new period and leaves the closed one closed, so a return is an event
   with a history and not a flipped field.
8. **A hire is approved but not carried out here.** Which role, on which model, is a decision
   the studio cannot make for the Owner, so approval is recorded and the Owner completes it in
   Settings. Guessing would put an agent on a model nobody chose.

**Alternatives rejected:** an LLM performance review (a judgement with no measurement under it,
about a colleague, that would then be cited as evidence); proposing termination on a high
failure rate (the evidence does not distinguish a bad agent from a broken provider); letting the
studio suspend an agent autonomously while the `autonomous_firing_enabled` flag is off (the flag
would be decorative).

**Test impact:** `tests/test_phase8_workforce.py`, 19 tests, most of them about what is *not*
proposed. Total 263 passed, 1 skipped. `scratch/verify_workforce.mjs` checks in the running page
that an unmeasured agent is shown as such, that nothing is proposed without evidence, and that
the server — not just the form — requires a reason for a rejection (9/9).

## D-P9-001 — The serial is grounded in the day it dramatises (2026-09-10)

**Problem:** Phase 9 asks the studio to turn its own operating day into an ongoing workplace
serial. `../architecture/07_STORY_ENGINE.md` separates Operational Truth from the Narrative
Layer, permits dramatisation — jokes, pauses, compressed dialogue, comic framing — and forbids a
specific list of fabrications: a hire or departure that did not happen, a success or failure that
did not happen, invented view counts, an invented provider outage, a decision attributed to the
wrong person, staff who were not there.

Read closely, those are one failure with several faces: a beat about something the event stream
never recorded. So the design question was not "how do we write an episode" but "what makes a
beat checkable".

**Choice:**

1. **The log is counted, never narrated.** `close_daily_log` reads the domain event stream for
   one business date in the studio's own timezone and records what is in it — counts per event
   type, the roster, and the events worth dramatising. No model writes any part of it. The log is
   what every episode is checked against, so a narrative inside it would make the check circular.
2. **A closed day does not change.** Re-closing returns the stored log untouched, and the date is
   unique in the schema. Letting a log drift would let an episode become grounded after the fact,
   and having two logs for one date would give an episode a choice of records to be grounded
   against — which is no grounding at all.
3. **Every beat cites its events, and a citation that is not in that day fails the whole
   episode.** Not the beat: the prose around an invented citation was written under the same
   misapprehension, and there is no way to tell how far it reaches. The forbidden-fabrication
   list is enforced by this one rule — an invented outage or a fake hire has no event to cite.
4. **The cast is the day's roster.** A character named in a beat must have been employed that
   day. Putting someone in a room the record says they were not in is the same failure as citing
   an event that did not happen.
5. **A quiet day produces no episode.** `NothingHappened` is raised and the panel marks the day
   rather than offering a button that would fail. Manufacturing a story from an empty log is
   exactly the fabrication the spec forbids, dressed as productivity.
6. **The claim can be re-checked later.** `GET /story/episodes/{id}/grounding` re-reads a stored
   episode against its log and names any citation that is not there, so grounding is audited
   rather than trusted — including if a row were ever written past the check.
7. **Only narratable event types are offered as material.** A heartbeat is not a story beat, and
   a shorter list of real material is better than a long one that invites padding. Everything
   still counts towards the day's totals.

**Alternatives rejected:** letting the showrunner write freely and checking afterwards
(attribution reconstructed after the fact is a guess); dropping an ungrounded beat and keeping
the episode; summarising the day with a model before handing it over (the summary would become
the thing the episode is checked against, and it would already contain interpretation).

**Test impact:** `tests/test_phase9_story.py`, 21 tests. Total 284 passed, 1 skipped.
`scratch/verify_story.mjs` drives the panel and confirms a quiet day is reported as a fact, a day
is closed once, and no episode is stored when the writing fails (11/11).

## D-P10-001 — A run reports what it did, not what it was for (2026-09-10)

**Problem:** Phase 10 asks for the daily autonomous runbook from
`../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md`: a preflight, twelve stages in order, and abort
behaviour when something fails. Every earlier phase guarded against inventing a fact about the
world. Nothing in a daily run does that — and that is what makes this phase easy to get wrong.
The falsehood available here is quieter: a run that *reports* more than it did. A stage that
never ran because a provider is missing, left out of the list, reads as a stage that succeeded.
A preflight that rounds a missing capability up to READY produces a failure that arrives hours
after the Owner stopped watching. Neither needs a single false sentence to mislead.

**Choice:**

1. **The preflight never rounds up, and it probes nothing.** Each check reports one capability as
   present or absent, with the severity that follows from it; the verdict is the worst of them.
   Missing media providers *degrade* — the studio can still work, the output is unpublishable —
   while a stopped autonomy gate, no verified model, or no FFmpeg *block*. The DEGRADED summary
   says in words that stages will be skipped and output will be unpublishable, because the word
   "DEGRADED" alone invites being read as "fine for now". Nothing is called over the network: a
   preflight that made outbound calls would be slow, would fail for unrelated reasons, and would
   still only describe the instant it ran.
2. **The run's status is derived from its stages, never asserted.** `_derive_status` computes
   FAILED > BLOCKED > PARTIAL > COMPLETED from what the stages actually recorded. A stage
   returning COMPLETED cannot make the day completed while another was skipped.
3. **Every stage appears in the record, including the ones that never ran.** A stage with no
   implementation connected is recorded SKIPPED with that reason; the stages after a stop are
   recorded BLOCKED naming where the run stopped. A page listing three stages when the runbook
   has twelve would mislead by the arrangement of the page alone.
4. **A blocked preflight closes nothing.** The daily log is closed on a partial day — a partial
   day is still a day — but not on a day the studio never started. Writing a log for a blocked
   preflight would put an entry in the record for work that did not happen, and tomorrow's
   episode is checked against that record.
5. **A failed stage enters safe mode and stops autonomy.** An unattended studio must not carry on
   into the next day with an unexamined fault behind it. A second failure does not open a second
   record, because that would obscure when the incident began.
6. **Leaving safe mode requires a note and does not restart autonomy.** The note is kept.
   Examining an incident and deciding the studio should act again are separate decisions, and
   folding them into one click would let the second happen by accident while making the first.

**Alternatives rejected:** probing providers during preflight (slow, flaky, and still only true
for an instant); omitting unimplemented stages from the run record (the honest-looking version of
the same lie); letting a caller pass the run's status; auto-clearing safe mode on the next
schedule; restarting autonomy when the incident is closed.

**A note on the test fixture.** A freshly bootstrapped studio ships with the STOP gate closed, so
its preflight is correctly BLOCKED and no run starts. The Phase 10 tests were written assuming
the opposite and failed for that reason; the fixture now opens the gate explicitly, because these
tests are about what happens *after* the Owner has made that decision. The product default was
not changed to make tests pass.

**Test impact:** `tests/test_phase10_runbook.py`, 20 tests. Total 304 passed, 1 skipped.
`scratch/verify_runbook.mjs` drives the panel: the preflight names every check it made and its
verdict in words, reading it starts nothing, the run button follows the verdict, and a recorded
run shows all twelve stages with the skipped ones and their reasons (16/16 including the run
branch, which needs a verified model and is covered against a throwaway database — the script's
header says how, and that flag never means a provider answered).

## 2026-09-10 — Bucharest as scene timezone

Owner requested an outdoor electronic clock showing Bucharest time in 24-hour format. Use Intl Europe/Bucharest (h23), not a fixed UTC offset. Align street day/hour with this clock to avoid contradictory rhythms when the device is elsewhere. HH:mm refreshes each minute, with DST handled by the runtime timezone database. No schema change. 35 frontend tests and browser checks passed.

## 2026-09-10 — External street clock and CSP-safe scene CSS

Owner references call for a freestanding street display rather than a facade plaque. Place it outside the building on the right, preserving HH:mm Europe/Bucharest. Force Vite to emit the dynamically attached scene stylesheet via ?no-inline: its previous data URL was blocked by style-src, making the live controls appear at the top. Preserve CSP and concurrent dashboard controls. No migration; browser verifies loaded same-origin stylesheet and bottom dock geometry.

## 2026-09-10 — Resolve inspector assignments independently of legacy scene projections

Observed live layout lacks model fields even though Settings and agent records contain real assignments. Read agent and provider model catalogs when opening the inspector; never infer no assignment from missing scene fields. Distinguish failures and guard response ordering. Avoid unnecessary backend restart while concurrent development is active. No migrations or credential changes. 38 frontend tests and all 7 live agent comparisons passed without writes/provider runs. See `INSPECTOR_MODEL_FIX.md`.

## 2026-09-10 — Pixel office v2: design in Figma, render procedurally, never trade truth for polish

Owner asked for a commercial-grade pixel-art rebuild of the 2D agency with Figma as the design tool. Decision: the design system (palette variables, department material stories, HUD components, character sheet) lives in Figma and is mirrored one-to-one in `frontend/src/office_palette.js`; the room art itself stays procedural in Canvas 2D because a floor is tens of thousands of pixels and the backend layout decides geometry at runtime. The quality bar is one finished floor (Research, level 3) rendered from the same code that ships, uploaded to Figma at 4x. Rules kept: no backend change, no hardcoded data, posture from backend state only (typing only on WORKING, sleep only on PAUSED), lift only on token trips, street purely decorative. Static art is baked into cached layers so the target stays 60 FPS (measured 60 FPS, ~6 ms/frame). Character sprites are compiled from letter rows with an automatic hue-shifted outline; the same agent id always yields the same look and the role decides the costume. See `PIXEL_OFFICE_V2.md`.

## 2026-09-10 — AMN-AI: the stored studio name is domain state, not configuration

The agency was named AMN-AI (Autonomous Machine Nexus — Artificial Intelligence) and the name and logo had to be introduced across the product. Configuration, packaging, markup and documentation were simply updated. The studio row was not: `bootstrap_studio` writes `STUDIO_NAME` only at creation and never again, because the studio's identity belongs to the immutable history rather than to an environment variable read at render time — an existing database therefore kept displaying the old name in the workspace H1. Rejected: making bootstrap reconcile the row with `STUDIO_NAME` on every start, which would let an env edit silently rewrite domain state and would contradict the invariant the foundation tests protect. Chosen: `scripts/rename_studio.py`, an explicit Owner act that updates the row and appends a `studio.renamed` event (aggregate `studio`, next version, carrying `previous_name`) in one transaction, idempotent and refusing empty or over-long names. Applied once locally. Logo assets are derived from one source: the cube mark at icon sizes because the wordmark is illegible below ~120px, the full lockup only on the sign-in screen, quantised from 1.16 MB to ~8 kB per page load; the previous brand's unreferenced `favicon.svg` was deleted so no old identity is served. Distribution names became `amn-ai` and `amn-ai-ui` with both lockfiles regenerated and dependency resolution proven unchanged. See `BRAND_AMN_AI.md`.

## 2026-09-10 — Phase 11: the ledger records evidence, and refuses everything else

The economy had to start somewhere, and the choice was between building the treasury dashboard people can see (Phase 12) or the books underneath it. Built the books, because a dashboard over an unsound ledger is a more convincing lie than no dashboard. Decisions taken at implementation time, which the architecture audit left open: money is integer micros rather than cents, since provider usage bills in fractions of a cent and cents would round it away; only SETTLED revenue mints and only a BILLED invoice posts, keeping the two sides symmetric and the ledger a record of what happened rather than of what is expected; estimates are reported beside the books rather than accrued, because accrual needs a true-up path that has no reader yet; a treasury deficit is reported rather than blocked, because nothing spends VR$ yet and a freeze would have nothing to stop — enforcement belongs with procurement in Phase 13; and no command-idempotency table was added, because the unique evidence and invoice references already make every money-creating operation idempotent, which is the property that matters. Rejected: letting an agent mint (the spec calls minting a controlled ledger event, so the routes are Owner-only and no agent-facing path exists), and converting a foreign amount at a fetched-but-unrecorded rate (a conversion must be able to cite the snapshot that produced it). The demo script uses a throwaway database on a port it binds first: recording invented payouts in the Owner's real books and reversing them afterwards would still leave fabricated history in an append-only audit trail. See `PHASE11_ECONOMY.md`.

## 2026-09-11 — A YouTube connection proves itself; it is not described

The Owner asked to stop typing a refresh token and a channel id. The deeper reason to agree: those two fields let a connection be described correctly and be wrong. A pasted token carries no proof that whoever pasted it controls the channel, and a typed channel id is an unverified claim about which account that token opens; the publishing pipeline could not tell the difference. Decision: four manual fields (name, client id, client secret, redirect URI) and one button, with the Authorization Code flow issuing the refresh token directly to the studio and `channels.list` reading the identity back, so a row cannot name an account its grant does not open. `prompt=consent` is sent only when no refresh token is stored or the Owner pressed Reconnect — always sending it re-prompts a working connection, never sending it means a re-authorisation returns no refresh token at all. Secrets are not columns: the client secret and refresh token live in one Fernet blob, with a `secret_fields` list so a view can report CONNECTED without decrypting anything and no view model has a branch that could leak one. The callback route is public because Google redirects a browser to it, and its whole defence is a 43-character single-use state that dies in ten minutes. Failure states are written in their own transaction, after a test caught the first version setting `status = ERROR` inside the transaction whose rollback then erased it. Disconnect forgets the token locally before revoking it at Google, because the local half is the half the studio controls. Editing the client id drops the stored token rather than keeping a connection that reports CONNECTED and cannot mint an access token. Nothing is special-cased per channel: AMN-AI's two channels are not named anywhere in the code, and a test greps for hardcoded channel ids, client ids, secrets, tokens and account names. Verified in a browser against a throwaway studio driven through the real service functions with only the transport to Google stubbed, which is also how two defects were found: `window.open(..., 'noopener')` returns null, so the consent tab silently became a navigation of the studio's own tab; and `.secondary`, the affirmative button class used in roughly fifteen places across the admin surface, had never been defined in any stylesheet. See `YOUTUBE_CONNECTIONS.md`.

## 2026-09-11 — One way to connect a channel, not two

The OAuth section shipped beside the settings catalog, which still carried a `youtube` entry asking for a refresh token and an ID canal YouTube. The Owner saw it in the browser within minutes. Adding a good path next to a bad one leaves the bad one reachable, and a credential form is not a matter of taste: whichever form is filled in decides what the publisher believes about who owns the channel. Decision: delete the catalog entry and repoint every consumer at the connection — publishing credentials, channel binding, the analytics provider, the runbook preflight, and the purpose selections. Channel binding now takes a `connection_id` and copies the remote channel id from the grant, so a channel record cannot claim an account its credentials do not open; the API contract changed name because `integration_id` pointing at a connection would be a lie in the schema. Where more than one channel is connected and nothing names which, `selected_youtube` raises rather than returning the first row: AMN-AI runs several channels and publishing to the wrong one is not a recoverable mistake. Rejected: keeping the catalog entry with the two offending fields removed, which would leave two ways to describe the same channel and no way to tell which the pipeline used. A pre-existing bug fell out of the same change — the verification route branched llm → stored → else, and the else built a YouTube provider, so verifying an ElevenLabs or OpenAI media key raised, was swallowed by a bare except and reported FAILED every time; media and stored now share the vendor probe that always covered both. Verified in a browser: the social catalog offers TikTok, Instagram, Facebook and e-mail, and no label anywhere in the section reads Refresh token or ID canal. See `YOUTUBE_CONNECTIONS.md`.

## 2026-09-11 — An unanswered question is not a negative answer

The audit's central finding is one shape repeated in four places, and it is worth stating as a rule rather than as four fixes. Code is written for the answer arriving; the branch that runs when the question fails inherits the optimistic reading of the branch beside it. `get_video_status` returned "the video does not exist" when YouTube could not be reached. `reconcile_upload` returned "no previous upload" for the same reason, and its caller's next act is to upload. The factual gate, unable to trace an asset back to a script, fell through to a check reading "Asset has verified factual provenance" and passed. The same gate loaded the claim rows that existed and compared only those, so a claim id with no row behind it simply vanished from the comparison. Decision: a failed question raises `RemoteStateUnavailable` rather than returning a value that reads as an answer; an unresolvable provenance chain fails the gate and names the missing link; a dangling reference fails and is named. `../architecture/50_CONTENT_GATE_MATRIX.md` already made this distinction — NOT_APPLICABLE records a reason, it does not pass — and the code had collapsed it. Rejected: keeping the permissive behaviour behind a configuration flag, which would leave the studio one setting away from publishing a duplicate. Also decided: money-creating commands honour their `command_id` through the existing CommandRecord table, because the Phase 11 claim that unique external references made every such operation idempotent was true of evidence and invoices and false of Owner funding, which carries no reference; and the FFmpeg toolchain gets exactly one resolver, because three of them disagreeing is how a studio comes to report that an encoder it is configured to use does not exist. See `AUDIT_2026-09-11_INTERNAL.md`.

## 2026-09-11 — The clock is the Owner's to start

A scheduler existed that could be ticked and a queue that could be claimed, and nothing in the process did either on its own; "autonomous" meant a button pressed daily. The background worker closes that gap, and three decisions shape it. **The daily job is seeded dormant.** The Owner's studio has its autonomy stop cleared, so a job seeded active would have begun a real day — agents on paid tokens, a render, a closed log — within thirty seconds of the first restart, on a decision nobody took. The schedule exists from the first start-up; starting its clock is a recorded Owner act, `workflow.job_activated`, of the same weight as clearing the stop. Waking a dormant job whose slot is in the past sets the clock from now rather than firing on the spot, for the same reason. **A missed slot fires once under either policy.** `../architecture/09_CHANNELS_AND_AUTOMATION.md` forbids a backlog explosion after an offline period; SKIP and CATCH_UP differ only in the cadence afterwards, one re-anchored to now and one kept on the original anchor. The field had been decorative. **The slot names the task.** A fired job enqueues a task keyed on the job id and the slot it was due for, so a restart that puts the slot back — or a second scheduler leader after a lapsed lease — finds the queued work rather than duplicating it; the tick had created a workflow row and enqueued nothing, so nothing could have run it. Also decided: the scheduled daily run happens at most once per business date, because a second run on the same day is the Owner continuing after an approval, not the clock; and a task with no handler is dead-lettered with that reason rather than retried into the ground. The worker is off under test, where a loop that starts the day on its own would make every other test's timing a coincidence; it has its own tests, driven by hand, and a demo that starts the real server process and waits for a run to appear without touching anything. Rejected: a fixed local hour for the daily job, which is the right shape and needs a column; the interval-based schedule with CATCH_UP holds the anchor until then.


The runbook walked twelve stages and asked `app.state.stage_runners` for the work of each; nothing in the application ever set that attribute, so every run in production recorded preflight and eleven SKIPPED. The framework was honest and idle. Decisions taken while connecting real work to it. **COMPLETED means the stage ran to its end; SKIPPED means it could not run.** A research stage that finds no sources has completed — it looked, and there was nothing; one with no language model configured has been skipped. Collapsing the two is how a runbook comes to imply work it never did, so every stage reports a count as well as a reason. **A refusal is not a failure.** A model that writes narration it cannot attribute to a verified claim has its draft rejected and nothing stored, which is the pipeline working; the first version let that raise, and because the runbook stops the day at the first FAILED stage, one unusable draft left the daily log unclosed and every later stage BLOCKED. Rejected scripts and rejected episodes are now counted and reported by a stage that completes. **Where a person decides, the studio stops.** Clearing the autonomy stop is what authorises a run at all, but it is not approval of a particular script: a draft is left at VERIFIED_PASS, storyboarding requires an APPROVED one, and publication still passes the five-point gate that re-checks the stop, the file, quality control, factual provenance and duplication. **Two stages stay unwired on purpose.** `idea_generation` has no implementation — topics are proposed by the Owner — and `post_run` has no defined work; naming them with an invented body would be worse than the runbook reporting that nothing is connected. Added `select_topic`, the missing verb: a topic enters production only if at least one claim about it is SUPPORTED, because selecting one whose claims are all unverified only moves the refusal a stage later while implying the day had work. Quality control selects files by mime type rather than by asset label, after the renderer's `RENDERED_VIDEO` went unmeasured by a stage looking for `VIDEO_COMPOSED` — an unmeasured file is exactly what the publishing gate exists to stop. Verified by `scripts/demo_daily_run.py`, which runs two days in a throwaway studio with an Owner approval between them and produces a real MP4 that quality control measures and fails for the right reasons.

## 2026-09-11 — The Owner authorises sites from the interface, and each one is tested

The allowlist for source retrieval lived in `.env` on the reasoning that an allowlist an agent could add to would not be an allowlist. That reasoning stands; the conclusion drawn from it — no endpoint, no form — did not. The Owner saw "Niciun site autorizat" in the preflight and could act on it only by editing a file and restarting the studio, and even then had no way to learn whether the studio could read the site at all: a bot wall or a script-only page is an authorised host that yields nothing, discovered one research stage later as a quiet empty result. Decision: hosts are added and removed through Owner-authenticated endpoints and stored in `research_allowed_host`, next to the `.env` list, under the same rule (bare lowercase public DNS name, never this machine or a private range); no agent has a tool that reaches these endpoints, which is what keeps the list the Owner's. Every host can be tested: the studio fetches its front page through the same DNS-pinned, size-bounded retriever it uses for real sources, stores nothing, and records PASSED or the exact reason it could not read the page. The preflight counts the tested ones, and the research modal shows origin and last test beside each host. Rejected: letting the retrieve request carry its host (still a request-controlled allowlist), and a test that only resolves DNS (it would pass for a site that then answers 403 to the studio's user agent).

Also decided today: a preflight that says "no verified provider" when the key is verified sends the Owner to the wrong place. `media_readiness()` distinguishes no selection, unverified, no default chosen, and no adapter, and the check reports which; the Owner's studio was in the third state for both voice and image. And a connection that makes two kinds of media keeps a default per kind (`image_model_id`), because Runway's account lists video and still models in one inventory and one default cannot name both.
