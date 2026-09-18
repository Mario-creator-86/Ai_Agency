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

## 2026-09-17 — A transient fault is not a P0, and the clock gets a second chance

The playbook always distinguished retryable from non-retryable (`../architecture/18_AUTOMATION_ORCHESTRATION.md`: network timeout, 429, transient 5xx on one side; invalid credential, policy violation, invalid configuration on the other; `../architecture/21_FAILURE_RECOVERY_PLAYBOOK.md`: a P2 is retried, a P0 stops autonomy), and the runbook had collapsed both into one FAILED that opened safe mode. Measured on a copy of the live database, that is what had stopped the studio for days: one "database is locked" at the wrong second, treated as a P0. **Decision: a stage's fault has a class, read from the exception's shape and its chain, never from a stage's optimism, and the default for anything unrecognised is HARD** — retrying an unknown fault is how a studio spends a night repeating a bug — with `TransientStageError` as the one door a runner may open when only it can tell. A TRANSIENT fault is retried in place (`stage_retry_attempts` counts retries after the first failure, four tries by default, because that is what the name says) and, still failing, fails the run and does not open safe mode: nothing about the studio is wrong. **What still opens SAFE_MODE is a HARD fault** — a run that ends FAILED with `fault_class` HARD enters safe mode and sets the autonomy stop exactly as before, and the Owner clears it with a note; a `MediaProviderNotConfigured` is HARD on purpose, because no key is a configuration fact and waiting will not produce one. Rejected: retrying every exception a bounded number of times, which would have spent generation credits on a bug three times before stopping. **Same-day re-attempts count runs, not intent**: a clock-fired run is refused only by a date that did work or by `daily_max_attempts` spent; a manual run counts toward the attempts, and a manual run that fails transiently is also re-attempted, because the Owner pressed the button to have a day, not to have one try. A waiting retry does not refuse the Owner's button — when its time comes it finds the day done and skips itself — and a retry left over from another day skips itself too. **The letter waits for the last attempt**, so a provider down at five does not write to the Owner three times before it is up at six. **The fixed local hour stores its timezone on the row.** The entry of 2026-09-11 rejected a fixed hour for the daily job only because it needed a column and said so; this is that column, and it turned out to be two, because the activation route calls `set_job_active(engine, job_id, active, command_id)` with no settings in hand, the tick has none either, and `../architecture/18_AUTOMATION_ORCHESTRATION.md` says a stored schedule stores its timezone. The hour is the one thing an existing seeded job follows from configuration on start-up — following the hour is not starting the clock, so `is_active` is never touched and the job stays dormant until the Owner's `workflow.job_activated`. Rejected: plumbing `settings.timezone` through `worker_pass` and the router, which would have left the row unable to explain its own next slot. **The Owner's stop between stages is neither failure nor refusal**: PARTIAL if the studio did some of the day, BLOCKED if none, the log closed only when work was done, and no letter — the Owner knows, he did it.

## 2026-09-17 — A retry is a question the studio may ask twice, not a purchase it may make twice

The architecture's retry table classifies by what the vendor answered; the adapters needed a second axis, because the same silence means two different things. A read timeout on `GET /v1/tasks/{id}` is a poll that can be repeated for free; the same timeout on `POST /v1/text-to-speech` is a narration the vendor may already have synthesised and billed, and the "one 503 per scene" problem must not be fixed by paying for two scenes. **Decision: every call declares whether it is `repeatable`.** A refusal (429, 5xx) and a request that never left this machine are always retried; a request that left and got no answer is retried only when repeatable. Reads and Google's resumable chunks (Content-Range keeps one copy) are repeatable; TTS, image generation, Runway task submission and LLM generations are not, and their silence is raised at once. To make this honest the HTTPS boundary had to say which phase failed, so `MediaProviderError` gained `unsent`, `unanswered` and `retry_after`, and `ConfiguredLLM` raises `ProviderHTTPError(ValueError)` and `ProviderUnreachable(OSError)` — subclasses of what callers already catch. Also decided: a Retry-After beyond `provider_retry_max_seconds` is a refusal for now and is raised immediately rather than slept through (the worker's lease is an hour; a ten-minute wait inside one scene would spend it), and it is honoured as given up to the cap, not clamped, because being refused after waiting less than asked is the same as not honouring it; the final error keeps its own class with the attempt count appended, because a wrapper exception would hide which vendor answered what from `explain_key_error` and the Owner; and Runway's estimated credits are recorded once, from the answer that succeeded, so a retried call is never billed twice locally. Rejected: retrying health checks less than real calls (a transient blip flipping a VERIFIED provider to FAILED is exactly what retries are for), and a retry loop in the runbook instead of the adapters (the runbook cannot know which request left the machine). Not attempted: reconciling a POST the vendor answered 5xx after doing the work — there is no task id to reconcile with, and the policy assumes, with `../architecture/18_AUTOMATION_ORCHESTRATION.md`, that a 5xx answer means the request was not served.

## 2026-09-17 — Repair is bounded, and a row nobody can answer for is the Owner's

The watchdog reuses the two reconciliation functions the publishing module already had rather than asking the platform its own way, and that choice fixed what it may do. **Attempts are bounded by the record, not a column.** A platform that cannot be reached is asked `reconcile_max_attempts` times, counted from the watchdog's own `publishing.watchdog_reconcile` events per publication; after that the row is moved to NEEDS_RECONCILIATION — the status the model already declared for the manual repair queue — with the count in the Owner's note, and is not asked again. A retry loop with no bound is how a studio spends its quota asking a dead endpoint the same question every ten minutes. Rejected: a schema change for a counter, because the events are already the audit of each attempt. **An unknown publication with no remote id is handed over at once.** YouTube's UNKNOWN result carries no video id (the stream was interrupted before the platform named it), and `reconcile_publication` can only ask about an id, so such a row would stay REMOTE_UNKNOWN for as long as the studio ran; naming it as a person's to look at is the honest state, and the watchdog does not write a second reconcile-by-key path to avoid it. Left for the publishing module: `execute_publication` could admit REMOTE_UNKNOWN-without-id to its existing reconcile-by-idempotency-key branch, which would let the watchdog resolve these rows itself. **Lapsed leases are reported, never reclaimed.** `claim_task` already re-claims an expired lease; a second mechanism doing the same would be two owners of one row. **A stuck render is failed the way the assembler fails one**, with the reason on the row and the same event, so the ledger does not learn a second vocabulary for the same fact. **The service is a Scheduled Task, not a Windows service.** A task runs under the Owner's own account with the user profile loaded, which the DPAPI-wrapped credential key requires, and needs no service wrapper or password stored; `-RunWhenLoggedOff` uses an S4U logon for the same reason, and whether that logon can open the key on this machine is the one thing the Owner must confirm once. The task starts the studio, not the day: the daily job stays dormant until the Owner's `workflow.job_activated`.

## 2026-09-12 — The Director approves the scripts she passes (recorded 2026-09-18)

Recorded late: commit `c8fb3f6` of 2026-09-12 moved script approval from the Owner's inbox to the Director without an entry here, and the module docstring of `backend/app/runbook/stages.py` and `_script_and_storyboard`'s still said the Owner approves until 2026-09-18. One watched cycle had made a new film and then stopped, because the approval sat in an inbox nobody was going to read that day. **Decision: a script the Director has read and passed is approved in the same breath (`_director_approves`), recorded with who decided and on what reading, and the factual gate is re-checked inside `approve_script_draft`, so her approval cannot carry a claim that stopped being supported while the script was written; a PASS the gate refuses is logged and the script is left, and the day goes on.** The Owner said so, and the Owner can still refuse what she allowed. The writer and the Director work the story for up to `MAX_SCRIPT_EXCHANGES` exchanges in the same run, because text is the cheapest thing the studio produces and the render is where the money is. Rejected: keeping VERIFIED_PASS as a waiting state for the Owner's button, which left a day's production one click behind the Owner's attention.

## 2026-09-17 — The close of the day is a stage, and a slot is an instant

From Phase A's adversarial verification (the whole suite run twice, 863 passed, 0 failed, 1 skipped), two defects with a red-then-green test each. **Closing the daily log goes through the same fault classification and retry as a stage, because a locked database at the close lost a whole day's log** — the day's work was done and its record was the one write not retried. **The next local occurrence of an hour is compared in UTC instants, because comparing aware datetimes across a DST change put a slot twice or never**: two aware datetimes sharing one tzinfo compare as wall-clock time, and on the day the clocks go back the wall clock reads the same hour twice, so a slot inside the repeated hour read as still ahead and fired on every tick.

## 2026-09-17 — A channel's visibility is the Owner's versioned command, not a column a form fills

`upload_privacy_default` already existed on the channel and could be set through `configure_channel` with a plain field; nothing read it, and had something read it, an unversioned field with no ledger event would have let a film go public on a write nobody could later attribute. **Decision: the publish policy is a second set of fields (`autonomous_privacy`, `public_publish_enabled`, `publish_delay_minutes`, `policy_version`, `policy_changed_event_id`, migration 0037) changed only by an Owner command shaped like the environment command** — write lock, `CommandRecord` idempotency, `expected_version`, NO_CHANGE without a trace, a `publishing.channel_policy_changed` event with old and new values and the environment the decision was taken in. Two refusals live in the command rather than the resolver: "public" needs `public_publish_enabled=true` in the same command, so a page cannot flip one switch and forget the other, and "public" is never set while the studio is in TEST, because the environment says what a film may cost and a public release is the one cost that cannot be refunded. The old field is left as it is and still unread rather than repurposed, because a field with two histories is worse than a dead one. Rejected: recording the policy change in agent memory as `change_environment` does, because the runbook hands visibility to the Publisher explicitly and a memory would be a second, unversioned copy of the decision. Refined 2026-09-18: the TEST refusal is judged on the state the command would leave, not on the field it names — see "The command is judged on the state it leaves, not the field it names".

## 2026-09-17 — A scheduled release is a private upload with a date, and the resolver says so

YouTube has no "public in forty-five minutes"; it has a private upload carrying `status.publishAt`, which the platform makes public at that time, and it refuses a publishAt on anything not private. **Decision: `resolve_publish_visibility` returns the pair the platform understands — `privacy_status="private"`, `publish_at`, `release_privacy="public"` — and every reader downstream (the gate, the adapter, the event payload) treats the pair as the public release it is.** The delay applies to public releases only: an unlisted film has no premiere to wait for. The adapter checks the timestamp's form and refuses a publishAt on a non-private upload before any request leaves, because a 400 from Google is a wrong request, not a wrong moment, and the retry policy would otherwise have nothing to classify. The publication keeps status PUBLISHED after a scheduled upload rather than the model's declared SCHEDULED, because the video exists on the channel from that moment and the watchdog, reconciliation and analytics all key on PUBLISHED; the schedule is on the row and in the event. Left for a later part: reading `publishAt` back at reconciliation to mark the moment it went public. Reversed in part 2026-09-18: the unlisted/TEST row of the resolver's truth table — an unlisted policy resolving unlisted while the studio is in TEST — is reversed by the entry "An unlisted release exists only in PRODUCTION"; unlisted now needs PRODUCTION like public.

## 2026-09-17 — The sixth gate asks two things: which policy, and whether it allowed this

A visible publication must carry the policy version that authorised it, so an audit can say which policy published what. A stamp alone would let a request name a policy that never allowed it: an unlisted intent on a channel whose policy says private, stamped with that policy's current version, would read as authorised by it. **Decision: `POLICY_AUTHORISATION_GATE` passes only when the stamp is the channel's current `policy_version` and the requested visibility (a scheduled release counted as public) is no more open than what `resolve_publish_visibility` yields for the studio's environment.** The five checks before it are untouched and a private upload still gets exactly five. The Owner's own intent endpoint stamps the policy in force and is held to the same rule, so visibility is decided in one place for hand-made and autonomous publications alike; the one-click `publish-asset` route stays private and needs no stamp. Rejected: a gate that checks the stamp only, and a gate that runs for private uploads — a private upload authorises nothing and would only make the five-check tests lie.

## 2026-09-17 — A film is routed by its storyboard, and an unbound slot is a refusal

`ready[0]` was the first bound slot whatever film it held. `Storyboard.channel_id` existed since 0021 and nothing in production set it; `series_key` was the only signal the serial pipeline could plausibly carry. **Decision: `select_channel_for` reads the storyboard — `channel_id` when set, else series key `office_serial` → OFFICE_SERIAL, else MAIN_FACTUAL — and returns SELECTED with the bound connection or SKIPPED with a Romanian reason; a binding whose connection is no longer CONNECTED is not a binding; there is no fallback to another slot, because the wrong channel is the one mistake no later check can undo.** A film with no storyboard behind it is SKIPPED with `channel_id=None` rather than sent to the main channel by default, for the same reason the factual gate refuses an unresolvable provenance chain: an unanswered question is not an answer. Rejected: routing by the film's script topic or by the connection's title, both guesses about an intent the storyboard states directly. Superseded in part 2026-09-18: the reading "`channel_id` when set, else series key" is replaced by the entry "A storyboard's pin must agree with its key" — a pinned `channel_id` whose channel type contradicts the series key is SKIPPED, not followed.

## 2026-09-17 — Analytics for a channel come from that channel's account, never from the environment

`YouTubeAnalyticsProvider.from_verified_settings` falls through to environment credentials when the bound connection is not exactly one CONNECTED row. On the Owner's machine those may name an account that is not this channel's, and the intake would attribute the serial's retention to the main channel with a straight face. **Decision: `analytics_provider_for_channel` builds the adapter from the slot's bound connection row and the vault only, refusing with the reason an unbound slot, a missing row and a revoked grant, and never calling the fallback; `measure_channel_publications` filters publications by `channel_id`, status PUBLISHED and a remote id.** Rejected at the time: editing the adapter's constructor from the publishing part, which another part owned; the closure of 2026-09-18 gave the adapter its `channel_id` parameter and the whole-or-nothing reading of explicit credentials (below).

## 2026-09-17 — Two heads on 0035: chained after the serial's migration rather than merged

While the publishing part was being written the serial part added `0036_serial_continuity.py` on the same parent. Two heads make `migrate()` fail for everyone with "Multiple head revisions", so leaving them for a merge revision would have blocked every test in the tree until the integrator acted. **Decision: the publishing migration is `0037_publish_policy` with `down_revision = "0036_serial_continuity"`, `main.py` pins 0037, and the serial's migration, written first, stays where it is; one linear chain, no merge revision.** The chain was verified in an isolated copy of the tree while the serial's migration still raised `ValueError: Constraint must have a name` (unnamed foreign keys inside `batch_alter_table` on `story_episode`), which its author fixed before the phase closed; the audio part verified against a scratch copy carrying names for those two constraints only, never by editing a sibling's file.

## 2026-09-17 — Loudness is normalised twice-measured, once applied

The joined narration is measured with `loudnorm` first and the encode applies one linear gain from that measurement (`linear=true`), falling back to the single-pass dynamic mode only when the measurement is unusable (a silent track reads −inf). **Reason: the one-pass filter normalises with a three-second window and audibly breathes on speech; a linear gain leaves the narrator's dynamics as recorded.** `LOUDNESS_RANGE_LU` is 11 rather than loudnorm's default 7 because the filter abandons linear mode whenever the input's range exceeds the target and narration measures 5–9 LU. The target stays −14 LUFS / −1 dBTP as specified; QC's band is −16..−12 LUFS because the film is measured after the AAC encode, which moves the reading a little. The output reading in the manifest is the encode's own loudnorm report, free from the same pass, with a second measurement of the finished film only when the log lost the report.

## 2026-09-17 — Captions are timed from the recorded narration, and never invented

`caption_cues` reads `audio_seconds`, written per scene by the assembler after synthesis, and clamps it to the scene's duration so words never spill into the next scene; a scene without words has no cue, which removes the old behaviour of captioning a visual prompt in brackets. Sentences split on terminal punctuation followed by a space so decimals and initials stay whole; a sentence too long for two lines becomes consecutive cues; lines are re-wrapped at the width that shares a sentence evenly across the lines it needs, so a two-line cue reads as two lines rather than a line and a crumb. **The SRT is written after the voice pass, not before it as it was.** The captions rule numbers (42 characters, 2 lines) are declared in `qc.py` again rather than imported from the assembler, so that reading a film never imports the machinery that makes one; the two test files hold both copies to the same values through the same cues. `format_srt_timestamp` rounds once to whole milliseconds, because the old fraction-then-round could carry 999.6 ms to a printed 1000.

## 2026-09-17 — The burnt caption sits above the bottom fifth

The task's phrasing put the safe area at the bottom 20 % of the frame; the platforms' own controls and auto-caption occupy that band. **Decision: the text's baseline is placed at the top of it (MarginV=58 in libass's 288-unit script resolution, measured at 387 px on a rendered 1920-high frame).** FontSize 7.5 (50 px) was chosen after a frame at bold 11 wrapped a 42-character line into two; at 7.5 regular a 31-character line takes about 680 px, so 42 fit inside the 1024 px between the side margins. The SRT is referenced by a name relative to the encode's working directory because the subtitles filter's option parser reads a colon as a separator and an absolute Windows path would need escaping twice.

## 2026-09-17 — Fallback is counted as asked-and-not-delivered, and a check that cannot be made fails

`fallback_scenes` counts scenes a model was asked for that produced no clip (refused, failed, or quoted past a ceiling); scenes no model was asked for — a test's scene limit, a spent budget, no model — are `skipped_scenes`, because those are policy, not a model refusing. **QC reads the environment through `studio_environment(engine)` before its own transaction opens — the studio's state, never a parameter — and fails only a PRODUCTION film; in TEST the same count is recorded as `motion_qc.warning`, because two motion scenes are policy there.** The default ceiling is half the scenes and `settings.max_fallback_scenes` overrides it. The audio and caption checks fail rather than pass when they cannot be made, matching the existing rule that a missing ffprobe fails technical QC: no encoder with loudnorm, no audio stream, an unmeasurable film, or a missing or unparsable SRT each add a failure reason; a film already missing or undecodable skips the measurement with an error field and no second reason, since technical QC has already named the cause.

## 2026-09-17 — The privacy check and the truth check are one check

The spec asks for a `NarrativeProjection` and for grounding, and they were built as one mechanism rather than two. **`write_episode` grounds beats against `narrative_projection_json` alone: an event that is in the day's operational record but not in its PUBLIC_SAFE projection is, to the showrunner, an event that did not happen, and citing it fails the whole episode the way an invented id does.** Rejected: a second pass that strips private citations from a stored episode — the prose around a private citation was written from private material. The projection is stored on the closed log at close time, derived from the same committed events, so the public face of a day is frozen with the day; a log closed before the column existed is filled once, from those same events, recorded as backfill of a derived column, not a change to the record (counts, roster and notable events never move). Classification is a table in code, private by default: an event type nobody classified cannot leak by being new. Redaction is regex and over-redacts on purpose (a year in a title, a four-digit count), because a lost word in a title is cheaper than a key on a channel.

## 2026-09-17 — The Owner's words are a fact, not content

**A letter to or from the Owner (`for_owner`, `owner_attention`, or "Owner" as a party) is projected as "X wrote to the Owner" and nothing else.** The subject and excerpt of any other letter pass through redaction like every description. An agent's own report (`agent.message_sent`) is projected as the task it reported on, never its text, because that text is the model's working output and quotes whatever it was given. `agent.model_assigned` and everything under `provider.`, `settings.`, `youtube.`, `economy.` and `research.` stay OWNER_PRIVATE by omission from the table.

## 2026-09-17 — Canon moves only on approval, and once per episode

**`continuity_state` is one versioned row and advances in `advance_continuity` only from an APPROVED episode — the Owner's `decide_episode` or the Director's PASS under policy — and is idempotent by episode id, so the two paths cannot count one episode twice.** A rejected draft and a draft awaiting the Owner leave no trace in canon; the next draft is still "episode n+1" until one is approved. Rejected: deriving the episode number from the count of episode rows, which would number rejected drafts. Threads are ids the showrunner is handed and must answer for (`threads_continued`, `threads_closed`), and the episode's own declaration is what advances them; nothing infers a thread's fate from prose.

## 2026-09-17 — The Director's approval of an episode is a channel policy, default off

**A Director PASS approves an episode only under `director_may_approve_episodes` on the OFFICE_SERIAL channel, read by `app.story.review.director_may_approve_episodes` and never written by the story module; default off keeps today's behaviour — the Owner decides — with the review already on the episode.** (Where the flag lives changed on 2026-09-18: a column of the publish policy, below.) The checks that need no model decide first and the Director is not asked about an episode they refuse; when they pass, her verdict is the verdict, as in `editorial_review`. One rewrite with her notes, then REJECTED: the second FAIL is the review working, and a third draft on the same day would be the same day told a third time. A log whose drafts were all rejected is finished with for the stage's purposes.

## 2026-09-17 — The factual claim gate does not apply to a dramatisation

An episode makes no claims about the world: it dramatises committed events of a closed log, and its truth is the grounding check. **So the `ScriptDraft` behind a serial storyboard has no claims (`claim_ids_json=[]`, `story_json.kind="office_serial_episode"`, `factual_gate: not applicable`), which the five-point publishing gate already reads as "the script references no factual claims; none to verify".** The `StoryReview` the media stage's `story_gate` requires is written PASS from the Director's episode review rather than from the factual story checks, because asking a comedy about its hook and its attributed claim is asking the wrong questions; the reading that actually happened is the one recorded. The storyboard is built in exactly `generate_storyboard_from_script`'s shape (tested field for field) so render, narration review, QC and publish run unchanged; the rows that shape forces — a `TopicIdea` of status SERIAL, which the factual selection never picks and never counts as in production — say what they are. Rejected: making `storyboard.script_draft_id` nullable, which would have broken `film_identity` and the publishing gate's provenance walk.

## 2026-09-17 — Voices come from the bibles, through the scene's character ids

**Each serial scene lists the bible ids of the characters in its beat, in the beat's order, and the existing production policy binds the first locked character's voice where a bible has a `voice_binding_json`; otherwise the narrator speaks.** No new voice plumbing: the assembler synthesises one voiceover per scene, so one voice per scene is the granularity available, and a beat with two speakers is voiced by the first. Multi-voice inside one scene is left open. The visual prompt quotes `face_hair_desc`, `outfit_desc` and `props_desc` verbatim, as the prompt agent does, so the look is the bible's.

## 2026-09-17 — Yesterday is closed on the preflight line, retried like a stage, and never ends the day

`close_previous_day` closes the previous business date with every event of that date; it runs after a non-blocked preflight and before any stage, with `_run_with_retries`; a fault after the retries is logged and recorded on the preflight stage as `previous_day_log.error` with its fault class, and the day goes on. **Reason: yesterday's record is not today's work — a run that stopped over a bookkeeping write about a finished day would cost a day's production for nothing, and the serial stage, finding no closed log, reports a quiet day rather than lying.** A date already closed is returned as it is: a closed log never changes. Known consequence, recorded as open: today's close at the end of the run is kept as instructed, so a date whose run completes is frozen at the run's hour and tomorrow's `close_previous_day` returns it as it is; a full-day log for every date needs that end-of-run close moved, which is the runbook's decision. A blocked preflight closes nothing, for the same reason it was never a day.

## 2026-09-17 — The serial queue runs before the media stage, and the day's log stays last

`STAGES` had `serial_queue` after `daily_log`, matching the runbook's §12 numbering, and the stage wrote text nobody filmed; the media stage of the next run would have picked the storyboard up a day later, and only if nothing factual was ahead of it. **Decision: `serial_queue` moves between `script_and_storyboard` and `media`, so the same run writes, films, measures and routes the episode.** This does not change what the stage does — it still prepares Channel B's production from the *previous* day's safe narrative events, whose log is closed at the start of the run — only when in the day it runs; `daily_log` remains the last stage, and `STAGES[:6]` is unchanged. Rejected: rendering the serial from inside the serial stage by calling `_media` a second time, which would have left quality control and publication a day behind and put two camera calls in one run under two different budget readings.

## 2026-09-17 — The budget is asked per film, and a refusal after the first film names the film

`_media` asked `may_spend` once for the day and rendered one storyboard. With two films in a run the second check would have been the first's stale reading: what the factual film spent is in the books by the time the serial is asked about. **Decision: `may_spend(engine, 0)` before each film; a refusal before anything was made keeps the old SKIPPED with the budget's reason, a refusal afterwards records the film in `skipped_for_budget` and the reason says "serialul" or "filmul factual".** Order factual first, serial second, because the factual channel is the studio's product and the serial is its diary. The serial is recognised by its storyboard's series key through the same mapping the publish routing uses, so the film the media stage calls the serial's is the film the publish stage sends to Channel B.

## 2026-09-17 — The render reads the Owner's switch between scenes, whoever asked for the render

**`stop_requested` is polled inside `assemble_video_job` itself — before every scene after the first, and before every motion shot — rather than through a callback the stage passes in.** Reason: the stop outranks everything, and `generate_storyboard_from_script` already refuses under it, so a manual render from the media route stopping between scenes with the same Romanian reason is the studio's existing stance, not a new one. The first scene is not preceded by a poll because the stage read the switch a moment before. The stop is a failed job with `STOP_REASON` in its log and a `media.render_failed` event, and `RenderStopped` is distinct from `RenderEngineUnavailable` so the stage can report it BLOCKED (the Owner's decision) instead of SKIPPED. Note 2026-09-18: with two films per stage the stage's read "a moment before" was true for the first film only; `_media` now reads the switch before each film — see "The media stage reads the stop before each film".

## 2026-09-17 — A publish stage with no bound slot is still SKIPPED before it looks for films

The per-film routing made the up-front binding check look redundant, and removing it turned "no slot bound, no film waiting" into COMPLETED "nothing waiting" — which `tests/test_pipeline_coverage.py` rightly refused: a stage that cannot publish anything has not completed. **Decision: the old refusal ("Niciun slot de canal nu este legat…") stays, before the queue is read; which slot a particular film needs is then decided per film, and a connected account no slot names is never guessed to be a channel's.** Aggregation rule when nothing went out: a content outcome (the Director's refusal, a HOLD, the gate's reasons) makes the stage COMPLETED with that outcome's artefacts, as before; only a stage that could not work at all (unbound slot, no model, no account) is SKIPPED. Also from the integration, mechanical: the fake `evaluate_media_qc` in `tests/test_cycle_fixes.py` gained `**kwargs` because the stage now passes `settings=`, and the loudness report's `output` in `assembler.py` is used only when it is a dict, else the film is measured.

## 2026-09-18 — The Director's brief has two readings, chosen by the film's own marks

`gather_facts` refused every serial film for having no claims and the one brief told the Director that a film about the studio is REJECTED. **Decision: the film's kind is read from the marks the serial storyboard already carries — `Storyboard.series_key == "office_serial"` (the same mapping the publish routing and the media stage use through `channel_type_for_storyboard`) or `ScriptDraft.story_json["kind"] == "office_serial_episode"` (what `storyboard_from_episode` writes); either is enough, so a storyboard that lost one mark is still judged as what it is.** The brief is one template with the judgement, the nature sentence and the story question swapped by kind (`instructions_for`), so the frames rule, the language rule and the JSON shape cannot drift apart between the two readings. Rejected: importing `is_serial_storyboard` from `app.runbook.stages` (stages imports editorial; a cycle), and a per-channel lookup of the storyboard's `channel_id` (a serial storyboard built before the channel was seeded has none). Consequence recorded: a serial script that somehow carries claims is not asked about their sources either — its truth is the grounding check of the episode review, not a source.

## 2026-09-18 — A factual film without claims stays rejected in the same words

The exception for the serial could have been written as "a script with no claims is a dramatisation". **It was not: a factual script that rests on nothing is the film the Owner asked about on 2026-09-16, and it is still refused before any model with "scenariul nu se sprijină pe nicio afirmație".** A test holds both the words and the fact that the factual brief still says a film about the studio itself is REJECTED, so the exception cannot widen by accident.

## 2026-09-18 — The Director's leave to approve episodes is a column of the publish policy, not a key in the series rules

`director_may_approve_episodes` was read from `series_rules_json`, whose validator (`_check_selection_shape`) allows only `{series_key: {purpose: selection}}`; the two commands that touch that JSON would have refused or silently dropped a boolean there. **Decision: a real column (migration 0038, default false), part of `policy_snapshot`, set only by `change_publish_policy` under the rules the other policy fields already obey — stale `expected_version` refused, idempotent by command id, NO_CHANGE without an event when nothing changes, a change bumping `policy_version` and recorded with old and new in `publishing.channel_policy_changed`.** Reason: whether the studio films an episode on its own is the Owner's decision of the same weight as whether a film can be seen, so it lives in the same versioned, recorded command and not in a production-technology setting. Rejected: exempting the key inside the production-policy validator (two commands writing one JSON with two shapes), and a studio-wide flag on `OwnerPolicy` (the serial is one channel's product; the flag is read on the OFFICE_SERIAL row only, and a grant on the factual channel changes nothing, tested). A grant on a channel bumps that channel's `policy_version`, so a publication stamped with the previous version is refused by the sixth gate until re-resolved — the same consequence any policy change has, kept on purpose. The pipeline tests set the column directly as a fixture, because they test the stage and the review, not the command; the command's versioning, idempotency, NO_CHANGE, revocation and per-channel reading have their own test in `tests/test_publish_policy.py`.

## 2026-09-18 — Explicit analytics credentials are one account's, whole or not at all

`YouTubeAnalyticsProvider.__init__` completed each None argument from `STUDIO_YOUTUBE_*`, which meant an adapter built from a channel's bound connection (client id, client secret, refresh token) still inherited `STUDIO_YOUTUBE_ACCESS_TOKEN` from the Owner's machine, and `_refresh_access_token` uses a present access token before it refreshes: the serial channel's retention would have been asked of whatever account that token named. **Decision: the constructor reads the environment only when no credential at all was given, and an explicit set is taken as it is, gaps included, so a connection missing its secret is honestly `is_configured() == False` rather than silently completed from another account.** The environment path is kept for a bare constructor because `from_verified_settings` still falls back to it, and that fallback is that method's decision, not the constructor's. `channel_id` became a constructor parameter so the per-channel builder no longer sets an attribute the class did not declare. Rejected: an `allow_environment` flag, because the presence of any explicit credential already says which path the caller is on.

## 2026-09-18 — The studio view sums the channels' switches rather than lying or disappearing

`PolicyView.public_publish_enabled: Literal[False]` was true when no route could publish publicly; after the Owner's per-channel publish policy it was a constant contradicting a channel's own view. **Decision, the smallest honest change: the field is a `bool` computed as "any channel row has `public_publish_enabled`" inside `policy_view(policy, session)`, with the session every caller already holds (`change_environment`, `change_stop`, `snapshot`), and a bare `policy_view(policy)` answers False, the safe reading.** The per-channel truth stays on `ChannelView`; the studio view only says whether a page should expect public releases anywhere. Rejected: dropping the field, which every consumer of the snapshot would have had to be checked for; and computing it in the router, which would have left the `PolicyResult` a command returns saying False after the very command that enabled it.

## 2026-09-18 — The Owner's render button hands the camera the same settings as the day

The daily run passed `settings=` to `assemble_video_job` and `evaluate_media_qc` (captions burn-in, the fallback ceiling) and the media route did not, so the same storyboard produced two different films depending on who pressed render, and the Owner's `max_fallback_scenes` was read by nobody on the manual path. **Decision: all three call sites pass `request.app.state.settings`, and the test asserts identity with the settings object the app was built from, faking the assembler and quality control at `app.media.router`'s import boundary so no encoder runs.** `continuity_state` goes into `HISTORY_TABLES` beside `story_episode`: its only foreign key is to `domain_event`, whose rows are deleted after the history tables, so its position among them is free, and the reset test now seeds a canon row and asserts it is counted and gone.

## 2026-09-18 — The runbook document states the execution order, and its hash is re-indexed

`../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` numbered the serial queue §12 after the daily log §11 while `STAGES` had run it before the media stage since 2026-09-17. **Decision, a deliberate specification change: the document is renumbered to the order the code runs — §7 the next-day serial queue, §8 media, §9 edit/QC, §10 publish, §11 post-run, §12 the daily studio log — with one sentence saying why the serial runs before media and that it still prepares Channel B from the previous day's closed log, its sections' content otherwise unchanged, and its `sha256` in `DOCUMENTATION_INDEX.json` updated explicitly (`cbad740d…` → `70dc698c…`).** `PIPELINE_COVERAGE.md`'s stage table follows the same numbering. Rejected: leaving the document at the old order with a footnote, which would have had the specification and the code disagree on the one thing the runbook exists to state.

## 2026-09-18 — An unlisted release exists only in PRODUCTION

`resolve_publish_visibility` honoured "unlisted" in TEST, and the publishing part's truth table (`tests/test_publish_policy.py`) said so. **Decision: unlisted is held to the environment like public — an unlisted film is a release anyone with the link can watch, and TEST means nothing leaves the studio visibly; the policy may still be set to unlisted in TEST and takes effect when the Owner moves the studio to PRODUCTION.** This reverses one row of the 2026-09-17 truth table, deliberately. Rejected: refusing the command itself in TEST, which would make the policy and the environment two switches for one thing.

## 2026-09-18 — The command is judged on the state it leaves, not the field it names

The 2026-09-17 rule read only `autonomous_privacy == "public"`, so with the privacy already public from a PRODUCTION day the flag alone re-armed a public policy in TEST — `public_publish_enabled=true` was COMMITTED. **Decision: `change_publish_policy` refuses any command whose resulting policy is public+enabled outside PRODUCTION when the previous one was not, in the same words as the refusal of the word "public"; a policy already public is left as it is, and its other fields remain settable.**

## 2026-09-18 — A storyboard's pin must agree with its key

The media stage and `is_serial_storyboard` know a film by its series key; the 2026-09-17 decision let the id win, so the same film could be filmed as the serial and sent to Channel A. **Decision: `select_channel_for` refuses a `channel_id` whose channel type differs from `channel_type_for_storyboard(board)`, with no fallback; a pin that agrees routes as before.** Supersedes the "`channel_id` when set, else series key" sentence of the 2026-09-17 entry "A film is routed by its storyboard, and an unbound slot is a refusal". Rejected: letting the key win silently (a pin nobody meant is still a contradiction worth a refusal).

## 2026-09-18 — Canon is checked for leaks like the beats

The Director's privacy check read the title, the scenes and the dialogue only, while `_previously` hands the episode's summary, opened threads and recurring elements to every later showrunner prompt; a key in the summary would have entered canon. **Decision: the Director's privacy check reads the episode's summary, opened threads and recurring elements with the same `leaks()` as the dialogue; a leak fails the episode before any model.** Over-redaction (a year in a summary) is the accepted cost the beats already pay.

## 2026-09-18 — The media stage reads the stop before each film

The assembler skips the poll before a film's first scene because "the stage just asked", which stopped being true when the stage started filming two: a stop set during the factual film started the serial's render. **Decision: `_media` polls `stop_requested` at the top of its film loop and reports BLOCKED with the Owner's reason and the film it did not start.** Consequence: a direct call of `_media` on a bootstrapped (stopped) studio is BLOCKED; three tests that did so now switch autonomy on first, as the runbook would have.

## 2026-09-18 — Three redaction shapes added, chosen by measurement

A currency-first price ("USD 12.50"), a scheme-less link ("studio.example.com/invoices") and an uppercase opaque key ("AKIAIOSFODNN7EXAMPLE") planted in a *safe* title reached the projection and the showrunner prompt: prices were matched amount-first, links by scheme, keys by prefix. **Decision: `_MONEY_FIRST`, `_DOMAIN` and `_OPAQUE_UPPER` join `_PATTERNS`; a phone-number pattern was rejected (not named by the rule; dates and counts would pay for it).** Probed unchanged: "Apa de pe GJ 486 b", "Ep. 3", "1080x1920", "AMN-AI HQ", "COVID19".

## 2026-09-18 — The suite proves the Owner's rule instead of promising it

A grep of the tests for provider hosts found them only inside fake transports and error strings, which says nothing about a fake wired one call short. **Decision: an autouse fixture in `tests/conftest.py` refuses non-loopback sockets for every test** — `socket.connect` and `connect_ex` to anything but 127.*, localhost, ::1 or a Unix-socket path are refused with a message naming the address and the rule; every adapter goes through urllib or http.client, which the guard covers. Rejected: a grep-only check (it found nothing, but a fake wired one call short is exactly what a grep cannot see). Known edges, recorded: an async client on Windows' proactor loop would connect through ConnectEx and bypass the guard, so one introduced later needs a second hook; `tests/test_ollama_adapter.py::test_real_ollama_health_and_generate` (opt-in via `STUDIO_OLLAMA_URL`) now passes only for a loopback Ollama, which is the rule and not a bug.


## 2026-09-18 — Repair shared garment material usage without rebuilding HQ

The runtime reported SkeletalMesh material fallback for four HQ garments. Repair
the shared parent's skeletal usage, retaining colours and geometry. Verify copied
assets in a separate UE project and independent reload before replacing only the
five affected packages with backup. Keep the existing procedural/GLB scene pipeline.
Use a native still for artistic diagnosis, but do not treat editor colour metrics
as game/player performance or as a percentage of reference fidelity. L2 is the
next bounded art pass; backend room identities remain authoritative.


## 2026-09-18 — A budget period begins when the studio's day begins, and the zone is the studio's own row

The DAILY window opened at UTC midnight while the studio's day is Europe/Bucharest, so a cost at 22:30 UTC on the 17th was counted against the 17th's budget while the daily log had already closed the 17th. **Decision: `studio_timezone(session)` reads `Studio.timezone` — which bootstrap writes from `STUDIO_TIMEZONE` — and `_period_start` opens the day and the month on that calendar, so the period the books count is the same business date `story.services.business_date` closes.** UTC is used only for a database with no studio row, which is not a studio. Rejected: threading `settings` through `may_spend` and `budget_status`, which would have changed the signature of every caller — the router, the stages and four test files — for a value the database already holds.

## 2026-09-18 — A reservation is a ledger row decided behind the write lock, and `may_spend` stays a reading

The race is read-then-decide: two films asked in the same second were both told the last ten dollars were free, because nothing between the reading and the spending said the money was promised. **Decision: `reserve_spend` takes `lock_for_write` before it reads the period and writes a RESERVED `spend_reservation` row that every budget counts as `reserved_usd_micros` until `settle_reservation` or `release_reservation`; `may_spend` keeps its old contract as a reading and is unchanged for its other callers.** A reservation of zero — an unpriced plan — is checked and holds nothing, because there is nothing to hold and an exceeded budget still refuses it. The Romanian refusal names what is held rather than pretending it was spent, and `spend_since` reports held and spent apart. Stale holds are released, never settled, by `release_stale_reservations`: a process that died under a hold made no film.

## 2026-09-18 — The day's remaining budget is read before the film's own hold, and other films' holds still count

`_budget_left_usd` feeds the per-film motion ceiling and now subtracts reservations. Measured after the hold, a PRODUCTION film that had just reserved its 12 USD would have been handed the ceiling of what was left after its own 12 were set aside — nothing — and would have rendered stills for a day with money in it. **Decision: the ceiling is read one line before `reserve_spend`, so a film never counts its own hold against itself while every other film's hold still counts against it.** This is the single place where a reservation changes what a render is allowed to buy, and the order is load-bearing.

## 2026-09-18 — Settle only after the cost rows are in; release on every other path out of a render

A settlement is a statement that the books now carry the truth. **Decision: `settle_reservation` follows `record_render_costs` and names the job (`render:{job_id}`); every other exit — the Owner's stop read between two scenes, an encoder that will not run, a vendor's refusal — releases the hold at once rather than leaving the day's money pledged until the watchdog's six hours are up.** Between the render and the settlement the film is counted twice rather than not at all, which is the error a budget may make. `_release` swallows its own failure and logs it: the watchdog is the backstop, and a second fault must not take the stage down on top of the first.

## 2026-09-18 — A price is a callable inside an adapter, not an engine

An adapter that costs its own call needs a price, and a price lives in the database. **Decision: `PriceLookup = Callable[[str, str], int | None]`, so `providers/elevenlabs.py`, `providers/ollama.py` and `integrations/llm.py` stay free of the database and a test can hand an adapter a dict; `price_lookup(engine, provider_kind)` does one short read per call, so a price the Owner types this afternoon costs this evening's runs without a restart.** Resource `"*"` prices every model of a kind that has no row of its own, and a model's own row outranks it.

## 2026-09-18 — Half a price is no price, and a cost row is never a float

**Decision: `llm_cost_vr` returns None unless both per-million prices exist and both token counts were reported, and `tts_cost_vr` prices the characters actually sent, rounding half up on the last micro.** A run priced on one side would be read by the budget as cheaper than it was, and a gap the Accountant reports as `unpriced_agent_runs` is honest where a half-cost is not. Zero tokens on one side is a zero, not an unknown. Money is integer micros end to end, because a cost row is money.

## 2026-09-18 — The only seeded price is ElevenLabs' public one, and it says it is not the Owner's plan

All nine live ElevenLabs models carried `pricing {}`, so narration was read as free, and the Owner's plan is not in the code. **Decision: `DOCUMENTED_PRICES` carries exactly one row — elevenlabs, `*`, per 1 000 characters, 0.22 USD (Creator plan, 22 USD for 100 000 credits, one credit a character; Flash and Turbo bill half, so the figure is the dearer one) — seeded by `seed_documented_prices` with provenance DOCUMENTED and a note saying it is the public list and not his invoice; it never overrides a row of any provenance and adds nothing on a second run, and the Owner's own price outranks it the moment he types it.** Rejected: seeding Ollama Cloud, whose price is the plan he bought — a guess in the books is worse than a gap the Accountant reports.

## 2026-09-18 — A failed render's cost is a row with a different reference, not a different table

The vendor charges for the shot it generated whether or not the film was finished, and a `MediaProviderError` recorded nothing. **Decision: `record_failed_render_cost` reuses `_priced_scene_costs` with the reference tag `failed:scene`, so a finished and a failed reading of the same job can never charge the same scene twice, a re-run charges nothing (the unique `(provider, external_reference)` refuses it), and the rows are ESTIMATED with `failed=True`, counted by the budgets like any estimate and labelled "ESTIMAT (randare eșuată)" in the books.** `failed=True` is refused for a BILLED row: a bill is what the vendor charged. Rejected: reconstructing the attempt from the plan inside the media stage — that would charge for shots the vendor may never have generated, and an invented entry is worse than the honest zero the stage records until `assembler._fail_job` writes the scenes it had already built.

## 2026-09-18 — One letter a day, decided behind the write lock

A budget refusal was a SKIPPED stage in a report nobody reads, and a stage refused twice in a minute would have written the Owner two letters. **Decision: `_letter_once_a_day` keys idempotency on the letter's `kind` and the business `date`, scanning that day's Owner-addressed messages, and takes the write lock, so `budget_refusal_letter` and `may_run_agent` each write to the Owner once a day whatever refused; the Accountant signs, the Director signs when the studio has no Accountant, and with neither the function reports `written=False` rather than inventing an author.**

## 2026-09-18 — The token ceiling is the Policy Kernel's first gate, and a refusal is a row, not an exception

391 agent runs went through the Director's loop and the mail rounds under no ceiling at all. **Decision: `may_run_agent` is asked before `run_agent_task` opens its write transaction — the Accountant's letter writes in a transaction of its own, and two writers on one SQLite connection are a lock, not a policy — and the verdict is raised inside the kernel's own `try` as `PolicyKernelError(..., "BLOCKED_BUDGET")`, so the existing handler writes the `AgentRun` exactly as it does for BLOCKED_POLICY and BLOCKED_PROVIDER.** Twenty call sites keep reading a status and none of them learns a new exception. It is the first of the six checks because it is the only one that costs money to learn the hard way. The ceiling counts every token of every run since local midnight whatever its outcome — an empty answer was billed like a good one — and `STUDIO_AGENT_DAILY_TOKEN_BUDGET` 0 means no ceiling, as the studio has run until now.

## 2026-09-18 — `run_agent_task` reads the settings the way the vendors' retry policy does

None of its twenty callers carries a settings object, and threading one through all of them to read a single integer would have been a larger change than the feature. **Decision: `_studio_settings()` is an `lru_cache`d `Settings()` that answers None when there is no usable `.env` — the shortcut `app.providers.retry` and `app.integrations.autoconfig` already take — and every ceiling is read through `getattr` with the code's own default, which for the token budget is 0.** A test overrides the function, not the environment.

## 2026-09-18 — The film's estimate is conservative on purpose

**Decision: `estimate_film_cost_micros` takes the motion at the ceiling that render will be given (`motion_budget_usd` in PRODUCTION, `test_max_cost_per_generation_usd` × `test_motion_scenes` in TEST) and the narration at the dearest active per-thousand price over the storyboard's own voiceover, and reports `narration_priced=False` when no voice price exists.** A film that costs less settles for less; a film let through on a hopeful estimate spends the week.

## 2026-09-18 — A discovered search address is a finding, the Owner's is a decision, and a finding never overrides a decision

Page discovery ran only through the OpenSearch address the Owner had typed per host, and only the two Wikipedias carried one. **Decision: every PASSED host test reads the front page through the same DNS-pinned retriever and looks for the site's own search address (`<link rel="search" type="application/opensearchdescription+xml">`, then `/opensearch.xml`), stores it in `discovered_search_template` (migration 0040) and never touches it from `set_search_template`; `effective_search_template` returns the Owner's address first and the discovered one only in its absence.** Discovery re-runs on every PASSED test and replaces what was stored, including with nothing: an address that vanished from the front page is not kept on faith, because a stale address that 404s is the failure this work removes. A retriever stand-in with no `describe_search` cannot look and says so (`discovery_ran=False`), so the caller keeps what it had rather than clearing it.

## 2026-09-18 — The OpenSearch description is read with the HTML parser, and a template that still needs a parameter is refused

The description is XML from a host the studio does not control. **Decision: `_OpenSearchUrls` extends the standard HTML parser — it takes the XML tags and unescapes attributes and has no entity expansion for a hostile document to exploit — and only the `application/x-suggestions+json` template is taken: `{searchTerms}` becomes `{query}`, optional parameters are dropped with their names, and a template that still needs a parameter the studio cannot fill, exceeds 500 characters, or is not HTTPS on the very host being tested is rejected.** The description's own address is validated under a one-host policy before it is fetched, so a front page naming another host's search cannot make the studio read that host.

## 2026-09-18 — A search engine may name addresses and nothing else, and the allowlist is applied by the studio, not by the engine

The Owner authorises hosts; an engine answers with whatever it indexes, and its answer carries cached copies, snippets and "answers" of its own. **Decision: `providers/search.py` returns addresses and titles only and knows nothing about the allowlist, and `find_pages` validates every result under the studio's own `RetrievalPolicy`, keeps the ones on authorised hosts, counts the rest as dropped (once per address, however many queries repeat it) and logs the count without the addresses; every kept page is then fetched by the studio's own DNS-pinned retriever.** Both halves are the decision. Reading an engine's copy, snippet or answer would be fetching through a third party exactly what the studio would not fetch itself, which is how an allowlist is widened without anyone deciding to widen it; and an adapter that knew the allowlist would be a second place where the list lives, which is a second place for it to be wrong. No agent, no request and no result can add a host: the list is the Owner's rows, and a name the engine returns is either already on it or dropped and counted. One documented HTTPS JSON contract (endpoint, key header, results path, field names) was chosen over a per-vendor adapter, so any engine that answers a GET with a key in a header and a list of `{url, title}` can be connected without new code; a bearer token is composed only for the `Authorization` header. `MAX_RESULTS` 50 and `MAX_URL_CHARS` 1000 bound what a hostile answer can make the caller iterate. Rejected: asking the engine first and the sites afterwards (a Wikipedia day would pay the vendor for nothing), and trusting the engine's own "site:" filter, which is the vendor's promise and not the studio's rule.

## 2026-09-18 — A search connection counts only when it is verified, and a verification does not look like a research query

**Decision: the catalog declares kind `search` with runtime `search` and group `social` — the bucket for accounts that are not language or media models, shared with e-mail — so the integrations check route sends it to `probe()`; the probe sends one neutral word (`PROBE_QUERY` "encyclopedia"), checks the shape of the answer and stores nothing, and `verified_search_provider` uses a connection only when its status is VERIFIED or ACCESS_VERIFIED, decrypting the key from the vault there and nowhere else.** SAVED is not enough, the same rule the media providers follow. The neutral word is deliberate: a verification should not appear in the vendor's logs as the studio's research.

## 2026-09-18 — When the studio found pages, a guessed address is set aside rather than fetched

Measured on the clean studio's first days: every address the Researcher guessed returned 404 and every page a site's own search returned existed, so a guess next to a real page is a page not read. **Decision: when discovery or the engine found pages, the Researcher's plan is a choice among them — a guessed address is not fetched, and its being set aside is recorded in the run's failed list as GUESS_SET_ASIDE in Romanian for the Director to read, not raised as an escalation; when nothing was found, his addresses are tried exactly as before and the escalation letter now also says that the site searches and the engine found nothing.** The pages found are read up to the day's limit whether or not the Researcher chose them.

## 2026-09-18 — The day's reading is four candidates of four pages, and the ceiling is the code's

Two topics of three pages left the studio with 0 pages on a day when both guessed plans failed. **Decision: `DEFAULT_CANDIDATES_PER_DAY` and `DEFAULT_PAGES_PER_TOPIC` are 4 and 4; `research_budget(settings)` reads `research_candidates_per_day` and `research_pages_per_topic` when the settings object carries them and clamps both to 1..12, and `MAX_URLS` in the Researcher's plan rises from 4 to 8 and becomes the ceiling under the Owner's setting rather than the setting itself.** A typo in the environment cannot turn a research pass into a crawl.

## 2026-09-18 — A script-only shell is a host failure with a name, and the heuristic is measured on fixtures

14 of the 36 authorised hosts failed retrieval, and the reason was a sentence nobody could act on. **Decision: `last_test_reason` is a closed vocabulary — HTTP_403, HTTP_ERROR, RATE_LIMITED, SCRIPT_ONLY, NETWORK, OTHER — and the retriever keeps `<noscript>` text apart from the page text and marks `scripts_required` when the visible text is under 500 characters and mentions JavaScript; a shell with under 10 characters of text raises a `RetrievalError` naming JavaScript, and a shell with a little text is PASSED by the retriever and FAILED by the host test on the flag.** The 500-character threshold was measured on the shells of the hosts that failed — a title, an empty root element and a one-line notice, never a paragraph — and is proven on fixture HTML modelled on them, not on live pages, because no test may open a socket. Recorded as such: the first weekly retest on the live database is the measurement.

## 2026-09-18 — The health report is computed from the record and probes nothing

A preflight that asked whether a row existed passed on 36 authorised hosts of which 14 were unreadable and none had a search address, and the day then fetched nothing. **Decision: `research_health(engine, settings)` answers "can the studio find pages" from the record alone — hosts authorised, tested, with a search address, failing and why, whether an engine is VERIFIED, how many SUPPORTED claims are in hand — and is DEGRADED with named Romanian reasons when no host passed, when there is no way to find pages at all, or when fewer than `MIN_CLAIMS_AVAILABLE` (10) verified claims remain; it opens no connection, so the preflight may call it on every run.** Ten is a day's margin: a thirty-second short spends three to five claims and a day's verification lands a handful. A DEGRADED report stops nothing by itself — a day that finds nothing completes honestly with nothing — and the counts are in the check's `detail` as well as its message, because the run the Owner needs them for is the one where the check failed.

## 2026-09-18 — The weekly host retest lives inside the research stage, not in a scheduled job of its own

A site readable a week ago may have grown a bot wall since, and one that failed may have dropped it. **Decision: `retest_stale_hosts` touches only hosts whose last test is missing or older than `RETEST_AFTER_DAYS` (7) and runs inside the research stage, wrapped in a broad `except` and logged — on the other six days it fetches nothing and costs the sites nothing.** Rejected: a scheduled job of its own, which would have added a row to the scheduler, a handler to the worker and a second thing behind the autonomy stop to reason about, for a pass that already decides for itself when to do nothing. A site that cannot be reached is a fact about the site: under Phase A's rule such a failure costs the stage, never the studio — here, not even the stage. A host authorised by the `.env` file has no row of its own, so its result and discovered address are stored on a row marked `added_by="env"`, which never re-authorises the host once the file drops it.

## 2026-09-18 — The end-to-end test fakes the vendors and nothing else

The project had every stage tested and no test of a day. **Decision: `tests/test_autonomous_day_end_to_end.py` fires the scheduled job, lets the worker execute the real runbook with the real stage runners against a temporary database, and asserts the whole day — twelve stages under a `scheduled:` idempotency key, a claim extracted and verified by a second employee, a script the Director passed, two films encoded by FFmpeg and measured by quality control, both published private through the five gates to their own channels, the serial episode grounded in yesterday's events — then a second tick that starts nothing; only the vendors are faked, and the docstring says so.** The picture is a small PNG of noise rather than a flat card, because quality control refuses a still that survives being flattened along either axis, and a fixture that could only pass by disabling that check would prove the wrong thing. The film is asserted PUBLISHED_SIMULATED and not PUBLISHED: a studio that wrote "published" for a film no platform received would be lying in its own books. The model stand-in fills each schema from what the prompt itself carries — the claim ids the writer was given, the day's event ids, the cast read from the cast section alone — so the studio's own checks are what make its answers usable, exactly as with a real model. The test skips where FFmpeg is absent, by the convention `tests/test_phase5_media.py` already uses.

## 2026-09-18 — Migration numbering: economy 0039, research 0040

Two implementers needed a schema change in the same tree. **Decision: `0039_pricing_truth_and_reservations` (economy) first, `0040_research_sources` (research) chained after it with `down_revision = "0039_pricing_truth_and_reservations"`, and `main.py` pins `0040_research_sources` as the head.** Both are additive — two tables and a column for the economy, three nullable columns for research, plain `ADD COLUMN` as 0030 did — and every existing row keeps its meaning. `scripts/bootstrap.py` must run against the live database before the server starts on this version, and no test touches it.

## 2026-09-18 — A price table is passed at construction, never fetched at the call site

The three adapters already took `price_lookup: PriceLookup | None = None` and no construction site
passed one, so every `agent_run.cost_vr` was NULL and every narration unpriced whatever the Owner
had typed. **Decision: the four places that build an adapter hand it `price_lookup(engine, kind)`
— the seeded Ollama endpoint (`main.register_seeded_ollama`), the language connections loaded at
start-up (`integrations.services.load_registry`), the one re-registered when the Owner saves a
connection while the studio runs (`integrations/router.py`), and both doors into a voice
(`media.factory.tts_provider` and `tts_provider_for`) — rather than handing each adapter an
`Engine` and letting it read the table itself.** The alternative would have put the database inside
`elevenlabs.py`, `ollama.py` and `integrations/llm.py`, which is exactly what the callable was
designed to avoid. The consequence is that the engine must be in hand where the adapter is built,
and it is at all four: two take one as a parameter, the settings router reads
`request.app.state.engine`, and both voice doors already take `engine` as their first argument. No
signature changed. One short read per call, so a price typed this afternoon costs this evening's
runs without a restart; a model with no row still reports None, never zero.

## 2026-09-18 — The connection re-registered by the router carries the same table as the one start-up registered

`PUT /settings/integrations/{id}` replaces the adapter in the live registry for any connection
whose runtime is `llm`. **Decision: wire the router's re-registration as well as `load_registry`,
and prove each by its own test.** Wiring only start-up would have meant that a connection the Owner
edited at noon ran the rest of the day reporting `cost_vr` NULL while an untouched one was priced —
the kind of asymmetry that is discovered months later in the books rather than in a test.

## 2026-09-18 — `credits.py` and `discovery.py` build an ElevenLabs adapter and are deliberately left unpriced

Those two construct one to read the subscription balance and to list the models and voices a
connection offers. **Decision: neither is given a price table, because neither call generates
audio, so neither has characters to price and `tts_cost_vr` would answer None for them anyway; and
rather than leave that as a silent omission, the list of priced construction sites is written down
in `tests/test_pricing_truth.py::PRICED_CONSTRUCTION_SITES` with the reason beside it.** The scan
that walks the list fails on a fifth site added later without a table, and also fails if a listed
module stops building an adapter at all, so it can never pass by finding nothing to look at.

## 2026-09-18 — The documented seed goes in bootstrap alone, because there are no start-up seeds

The economy implementer offered `scripts/bootstrap.py` "or the start-up seeds in `main.py`".
**Decision: `seed_documented_prices(engine)` is called from bootstrap, beside
`seed_chart_of_accounts`, and from nowhere else.** `main.py` has no seeds — its lifespan migrates
nothing and seeds nothing, it loads the registry and registers the seeded endpoint — and a seed
that wrote a price row on every server start would be a write the Owner did not ask for at a moment
he is not watching. The test therefore *reads* `scripts/bootstrap.py` rather than running it:
bootstrap writes `.env` and migrates the database named in it, which is the Owner's own, and no
test may open that.

## 2026-09-18 — The failed-render test plans three scenes and stops at the third, so the plan and the attempt cannot be confused

The existing adversary test refuses the second of two, which a job writing the *plan* minus its last
scene would also pass. **Decision: the new test plans three scenes and has the vendor refuse the
third, and asserts the exact scene list `[1, 2]` and exactly two ESTIMATED cost rows named by their
references, rather than a count a third row would still satisfy.** With three planned and two made,
a `production_json` carrying the plan would charge the day for a shot the vendor was never asked
for — the opposite error to the one this work fixed, and just as wrong in the books. The fix itself
was already in the committed tree (the assembler wraps its scene loop and `_fail_job` writes the
production it had built); what was missing was the proof that it writes the attempt and not the
plan, and a second reading charges nothing.

## 2026-09-18 — The research health report and the forced retest are the Owner's, on the factual router

The research half computed a health report and a forced retest that nothing called. **Decision:
both get a route on the factual router — `GET /api/v1/factual/research/health` and
`POST /api/v1/factual/research/allowed-hosts/retest` — rather than a research router of their own,
because that is where `/sources/allowed-hosts` already lives and the router's
`dependencies=[Depends(require_owner)]` is what makes them his.** The retest fetches front pages
and the report names every failing site and every site the studio can read, which is a map of the
studio's reach that an unauthenticated caller has no business reading. A test pins the 401 on both,
from the other side of the door. The health route probes nothing, so the screen may ask for it on
every refresh.

## 2026-09-18 — The retest route takes no body and forces the pass with `max_age_days=0`

**Decision: the route accepts no parameters; `max_age_days=0` is hard-coded, which is what makes it
"now", and the retriever is taken from `app.state.source_retriever` the way the existing per-host
test route takes it.** A parameter would have been a way for a caller to widen what the button
does, and the weekly age is the runbook's decision, not the interface's: the route is the Owner's
"now" after he has fixed something, and nothing else. The retriever hand-off is what lets a test
drive it with a stub — `tests/conftest.py` refuses every non-loopback socket, so without it the
route could not be tested at all without spending someone's bandwidth.

## 2026-09-18 — The discovered search address is shown even where the Owner has typed his own

**Decision: *Cercetare → Surse* prints, for every authorised site, whose address is in force
(marking the discovered one «not used, yours wins» where the Owner typed his), the address the
studio found on the site itself and when it found it, and «Try it» resolves whichever address is in
force, because `search_pages` resolves it the same way.** Hiding the discovered address where the
Owner has his own would have been tidier and wrong: his address is a decision and the discovered one
a finding, and he can only judge whether his decision is still the better one if he can see what the
site now offers. For the same reason the badge names whose address is in force rather than merely
saying «search», and «Try it» is offered wherever any address exists, including on a site that came
from `.env` and has no row of his to edit.

## 2026-09-18 — A failure reason is printed as a label from a closed list, with the site's own words after it

**Decision: the screen prints `last_test_reason` through a fixed label map and the site's own detail
after it, and an unknown code falls through to itself rather than to a friendly guess.** The code is
the same word on every host and can be compared down a column; the detail is what actually came back
and cannot be. A bot wall and a script-only shell are two different jobs for the Owner rather than
one paragraph of Romanian. A reason the backend adds later shows as the backend's own word instead
of silently reading as something else.

## 2026-09-18 — The budget card prints what is held apart from what was spent, and names the unpriced runs

**Decision: a budget card prints the held sum only when there is one, as «held for films in
production» rather than folded into what was spent; and the day prints what is held, what was paid
for renders that failed midway, and how many runs have no recorded price, named.** The percentage on
that card is already of spent plus held — that is how the backend computes it — so a card printing
only what was paid would leave the Owner reading a ratio he could not reconstruct and believing the
day has room it does not have. The unpriced-run line says in words that the total is lower than the
real spend, because a zero that means "not known" is the one number this studio must never present
as a fact. A run blocked by the day's token ceiling reads as a sentence instead of the raw word
BLOCKED_BUDGET.

## 2026-09-18 — The two changed screens are pinned at the API that feeds them, not by a DOM harness invented for them

`frontend/package.json` runs `node --test` over `frontend/tests`, and `main.js` touches the document
at import, so it cannot be imported there. **Decision: no DOM harness was invented for one screen;
what the screens render is pinned instead at the API — a Python test asserts that a failing host
comes back with `last_test_reason` SCRIPT_ONLY and a Romanian detail, and that the Owner's address
wins `search_template_origin` — and the file itself is kept honest by `tsc`, which type-checks
`src/*.js` with `checkJs`.** The honest next step, if the screens themselves are to be tested, is to
lift `renderAllowedHosts`, `budgetCard` and the run-status map into a module that takes data and
returns HTML; that is a refactor of `main.js` and not a test, and it was not this part's work.

## 2026-09-18 — The daily runbook is edited and its index hash re-recorded

The runbook still described the budget check, the research stage and the preflight as they were
before Phases E and F, and an architecture document that contradicts the code is worse than one that
is silent. **Decision: this is a deliberate specification change under ADR-FOUNDATION-003 — §1 now
states that the research check answers whether the studio can find pages at all; §4 states the order
in which pages are found (the Owner's search address, then the one the studio discovered on the
site, then a verified search engine filtered to the allowlist, every page read by the studio's own
DNS-pinned retriever and never the engine's copy) and that the weekly retest of authorised hosts
lives inside the research stage rather than in a scheduled job; §8 states the money path (the film
priced and the sum held before a frame is made, settled after the real cost rows are written,
released on every path where the film was not made, and a hold left by a dead process released by
the watchdog after six hours) — and the document's `sha256` in `DOCUMENTATION_INDEX.json` is updated
in the same change (`70dc698c…` → `1de4ef7a…`), with this entry as the recorded
reason.** Nothing was removed: every line the runbook already carried is still there, and each addition is dated in place so a reader can see what
the stage was before. No other architecture document was touched, and the check was not bypassed.

## 2026-09-18 — PIPELINE_COVERAGE's research and media rows follow the code, and its analytics line is corrected in place

**Decision: the stage table's rows 4 and 8 now say what those stages do and refuse today — the
retest and the three-tier page search, every engine result dropped and counted before anything
downstream sees it; the plan estimated and reserved behind the write lock before a frame is made —
and the stale limitation "Analytics measures through the first bound slot; per-channel measurement
needs one call per binding" is struck through with a dated correction rather than deleted.**
`measure_channel_publications` has measured per channel since Phase B/C, so the line was untrue; the
document already corrects in place with a dated marker, and striking it through keeps what the
document once claimed visible beside what is true now, which is the property that makes a coverage
audit readable a year later. What survives the correction is narrower and stated: a channel whose
slot is unbound is still not measured at all.

## 2026-09-18 — The economy's own documents name `provider_price`, `spend_reservation` and the hold inside `spend_since`

`PHASE11_ECONOMY.md` and `ACCOUNTING_AND_HISTORY.md` described a ledger that recorded what a vendor
had charged and a budget measured only from what was already recorded; neither mentioned the two
tables migration 0039 added. **Decision: both gain a dated section in their own voice — what a
RESERVED row is, that it is settled only when the real cost rows replace it and released on every
path where the film was not made or by the watchdog after six hours, that `spend_since` reports the
held sum apart from the spent one and every budget counts spent plus held, and that a price is the
Owner's with its provenance recorded (OWNER, DOCUMENTED, QUOTED, BILLED) and never a figure the
studio discovered for itself.** Both are project documents and neither is hashed, so no index entry
changed. The two documents' stale limitations are corrected in place, dated, rather than deleted: a
run and a narration are priced now, image and video generation still are not, and a model the Owner
has not priced is still reported as unpriced usage instead of as free.

## 2026-09-18 — The shots bought before the Owner pressed STOP are charged to the day

The verification of the Phase E/F closure left one open question from the previous pass: the media
stage's `except RenderStopped` branch released the film's hold and recorded no cost, although the
assembler now writes `production_json` for the Owner's stop exactly as for a vendor's refusal. A
test written against that branch found a stopped film whose FAILED job carried scene 1, whose hold
was RELEASED, and whose day was charged nothing. **Decision: the stop branch calls
`_record_failed_attempt` before `_release`, in the order the refusal branch already uses — the
estimate stops counting exactly when the real cost of the attempt starts.** The Owner's switch is a
decision about whether the studio keeps working; it is not a decision about whether a vendor has
already been paid. A shot generated in the minute before STOP was bought exactly as one the vendor
then refused, and a film the Owner stopped after one scene read in the books as a film that cost
nothing. Nothing is reconstructed from the plan: the attempt is read from the job's own record, so a
render that stopped before it made anything still charges nothing, and `record_failed_render_cost`
remains idempotent per job and scene, so a re-read charges nothing twice. `_record_failed_attempt`'s
docstring, which still said the assembler kept `production_json` for a finished render only, was
corrected to what the code does.

## 2026-09-18 — Every construction of a priced adapter is scanned, not four named files

The closure proved its price wiring with a scan of the four files it had changed. **Decision: the
verification replaces that list with a walk of all 183 application modules
(`tests/test_phase_ef_closure_adversary.py`), matching attribute calls as well as bare names, and
requires every site it finds to be either a priced one or a documented exception.** A whitelist
passes for whatever is on it, and the invariant is about the studio and not about four modules: a
fifth construction site would most likely arrive in a module nobody thought to list. The two
exceptions are named with their reason — `economy/credits.py` reads a subscription balance and
`integrations/discovery.py` lists models and voices, and neither generates anything to price. The
scan was run against a deliberately incomplete list first and named `economy/credits.py`, which is
how it is known to bite.

## 2026-09-18 — The roadmap and PROJECT_STATE are ticked against the closure

`13_ROADMAP_TODO.md` still carried open boxes for the price lookups, the documented seed's caller,
the failed-render record and the routes and screens, and `PROJECT_STATE.json` carried the matching
`known_blockers` and a `next_task` describing work already done. **Decision: the five closed boxes
are ticked with the date and the evidence, and the blockers are replaced by what is actually open —
the Owner's own prices, a bundle that is not rebuilt, and the reconciliation of ESTIMATED rows
against a vendor's invoice, which still has a vocabulary and no function.** A tracking document that
keeps listing closed work teaches the next reader to stop reading it, and the cost of leaving it is
that the work is done twice.

## 2026-09-18 — A picture the model refuses fails the film in both environments

The picture gate was asked to follow the fallback-scene gate, which is conditional on PRODUCTION.
**Decision: it follows `content_integrity_qc` and `content_source_qc` instead, and fails
unconditionally.** The existing gates do not all work one way, and the difference has a reason:
`motion_qc` is conditional because in TEST two motion scenes are the studio's own policy and the
rest push by design, so the count it measures is expected there. Nothing in TEST policy
deliberately produces a blank scene or a stranger in a character's clothes. The degenerate-still
check already fails unconditionally for exactly this defect measured on the still instead of on the
film, and the placeholder-footage check blocks unconditionally; the picture check belongs beside
those two.

## 2026-09-18 — One vision call for the whole film, carrying both questions

The pictures and the characters could have been two calls with two schemas, which would keep a
NOT_APPLICABLE character check from sharing a run with a measured picture check. **Decision: one
call — a `scenes` array and a `characters` array in one object, the scene frames followed by at most
four reference portraits, the prompt saying which are which and in what order — because the frames
are the expensive part of the payload and sending them twice doubles the image tokens for an answer
about the same images.** The record still separates the two verdicts: `picture_qc` and
`character_drift_qc` carry their own status, their own `passed` and their own run id, so a character
check that could not run never drags the picture check down with it. A film costs one call, two when
the model must be asked again with its own thinking on, and none when the check stands down.

## 2026-09-18 — Nothing in the vision answer has a default that reads as a pass

**Decision: `is_a_picture`, `shows_the_scene` and `matches` are required fields of the parsed
object, so a model that omits them fails validation and the whole check stands down rather than
passing a scene by silence.** A scene the model simply leaves out of its array is recorded
NOT_APPLICABLE with `no verdict was returned for this scene` and does not count towards the pass.
The same rule covers the frame cap: the Director's `frames_for` cuts at most eight frames, so a
ninth scene is recorded `no frame was cut for this scene`, never as looked at and approved. A gate
that certifies what it did not measure is worse than no gate, because the report then carries the
studio's signature on it.

## 2026-09-18 — The looking happens before quality control opens its write transaction

**Decision: `evaluate_pictures` is called next to where `studio_environment` is already read, before
the report's transaction, and it reads the storyboard out into plain values and closes its own
session before the call.** A vision call is an agent run; `run_agent_task` reads the day's token
ceiling outside a transaction by design and writes its own rows, so doing it inside the report's
transaction would put two writers on one SQLite connection. For the same reason no detached ORM row
and no held connection survives into the wait.

## 2026-09-18 — The employee who looks is found by department, and only the primary model counts

**Decision: `app.agents.vision.vision_agent` asks in the order Video Editor, Director, Quality
Assurance, and reads only the primary model slot.** The department that made the pictures answers
for them, and the Director's own model (glm-5.3) declares completion, thinking and tools and no
vision at all — a gate that asked her first would never run. A second or third model slot is the
Owner's configuration for other work and a run here would not use it, so counting it would let the
gate claim a capability the run cannot reach. `model_can_see` and `frames_for` were not moved: they
are the Director's, and `vision.py` imports them so callers have one door.

## 2026-09-18 — A Character Bible slot holds a stored asset id or nothing

**Decision: the slots are read exactly as the model documents them — a value that is not a string is
ignored, a portrait whose row or file is missing is simply not attached, and a description is never
accepted as standing in for an image.** A character with a description is compared against the
description; one with a portrait and no description against the portrait; one with neither is
recorded NOT_APPLICABLE for that scene with the reason and is never sent to the model, because there
is nothing to compare the frame with. The writing half follows the same rule:
`generate_character_reference_set` writes a `MediaAsset` per produced slot — bytes on disk, size and
dimensions measured from what the adapter returned, SHA-256 provenance, `license_status =
ORIGINAL_AI_GENERATED`, `provider_name` from the adapter — and only then writes that asset id into
`reference_assets_json`. A slot whose generation failed keeps its previous value and appears in
`failed` with the reason.

## 2026-09-18 — Producing a reference set is an Owner command, not a stage of the day

**Decision: it lives behind `POST /media/characters/{id}/reference-set` on the Owner-only media
router, reads STOP AUTONOMY before the first request (`AUTONOMY_STOPPED`, HTTP 409), and
`tests/test_character_references.py::test_the_days_run_never_produces_a_reference_set` asserts that
`runbook/stages.py`, `runbook/services.py` and `workflows/services.py` do not name the function.** It
costs one image credit per slot, and a studio that regenerated references on its own would spend a
budget on pictures nobody asked for. The route also refuses when no verified image provider is
selected, rather than drawing five placeholder cards and calling them references.

## 2026-09-18 — The money for a reference set is asked for once, before the first slot

**Decision: `reserve_spend` holds the estimate for the whole set behind the studio's write lock,
exactly as the media stage holds a film's cost; the hold is settled when at least one picture was
produced and released when none was.** The estimate is `estimate_cost_usd(..., images=1)` times the
number of slots; a model with no recorded price estimates to None, the hold is of nothing, and the
answer reports `cost.usd = None` and `priced = False`. An exceeded budget still refuses a request it
cannot value — that is the existing `reserve_spend` behaviour, and the reason the refusal is asked
for rather than computed at the route.

## 2026-09-18 — A locked look with no readable reference is a refusal, not a warning

**Decision: `image_reference_for_scene` returns None for a character with no lock and no reference —
the scene is drawn from its prompt as it always was — but raises `ReferenceRequired` when a character
whose `identity_locks_json['visual']` is set has no reference asset, or one whose file cannot be
read.** Drawing that scene anyway would invent a face for a character whose face is fixed, which is
the thing the lock exists to prevent. The first character the writer named decides the reference, so
a still is never drawn from two faces at once.

## 2026-09-18 — The studio asks an adapter whether it can take a reference

**Decision: `factory.accepts_reference_image` reads a class attribute and treats silence as no;
`still_from_chain` drops `extra['reference_image']` for an adapter that cannot take it and records
`reference_image: False` on that attempt.** A render must never report a continuity it did not have.
The OpenAI adapter implements the documented multipart `/v1/images/edits` path and sets
`ACCEPTS_REFERENCE_IMAGE = True`, which is a statement about the code; `REFERENCE_IMAGE_VERIFIED =
False` is the statement about the account and stays False until an Owner-approved run has actually
drawn a scene that way, because no test may buy one. A reference given as a path, an id or a
description is refused before the vendor is called rather than posted as a form field.

## 2026-09-18 — A second vendor is the Owner's, never the studio's

**Decision: `approved_alternatives` reads the `approved_fallbacks` list a level of the hierarchy
holds for a purpose — a new `SELECTION_KEYS` entry validated as a list of `{integration_id,
model_id}` objects, and also a `TECHNOLOGY_KEYS` entry so a consistency-locked channel does not let
an episode swap it in — and where a scene has a visually locked character the chain is narrowed to
entries in that character's `approved_fallbacks_json`, the list an APPROVED `CharacterIdentityChange`
writes.** Approval is the evidence that the technology keeps the character recognisable, and the
studio cannot produce that evidence about itself. Every alternative goes through the same `_validate`
as the first vendor, so an approval naming an unverified connection is dropped with a note rather
than tried.

## 2026-09-18 — The fallback chain is one alternative long

**Decision: `MAX_FALLBACKS_PER_PURPOSE = 1`, and when every approved vendor refuses,
`still_from_chain` re-raises the last `MediaProviderError` with the attempts attached as
`exc.attempts`.** A render that kept trying vendors would spend a film's budget on one shot, and the
second refusal is usually the same refusal — a prompt both vendors decline, not an account that is
down. Re-raising means the caller does exactly what it did before a chain existed, and a failed
render can still be priced for what was tried.

## 2026-09-18 — In TEST the chain is ordered cheapest-first; in PRODUCTION the Owner's order stands

**Decision: in TEST the alternatives are ordered by the price the studio has recorded, cheapest
first, with unpriced models keeping their place behind the priced ones; in PRODUCTION the resolved
vendor comes first and the alternative after.** The Owner's rule is that a test takes the cheapest
model that can do the job, and an approved alternative does not create an exception to it. A model
nobody priced can never be proven cheapest, so it is never promoted ahead of one that can.

## 2026-09-18 — The autonomy mode is recorded as AUTONOMOUS_CEO, because that is what the code does

**Decision: migration `0043_autonomy_mode` writes AUTONOMOUS_CEO on existing and new rows, and says
in its docstring that it records the mode rather than granting it.** The code is unambiguous:
`runbook/services.py` walks twelve stages in one call with no Owner approval between them,
`stages.py::_director_approves` approves a script in the same breath the Director reads it, the media
stage reserves budget and pays a vendor, `_publish_one` writes to YouTube — and nothing in the tree
executes a T4 action autonomously. That is 51's sentence for Autonomous CEO word for word. Choosing
MANUAL would have been the more cautious-looking answer and the false one: it would have described a
studio that does not exist and refused every stage of the run the Owner has been watching work. 51's
own example seals it — AUTONOMOUS CEO with `public_publish_enabled=false` is a studio that can create
final content automatically but not publish publicly, which is exactly this studio, TEST by default
with no channel set public. `change_autonomy_mode` remains the only thing that can promote.

## 2026-09-18 — A promotion is refused on what the database can read; the rest is said, not simulated

51 requires four things before a higher mode: acceptance criteria, a burn-in, no unresolved P0, and
the Owner's action. **Decision: the two that are readable here are enforced — an open
`safe_mode_record` is an unresolved P0 and `autonomy_stopped` is the Owner saying the studio should
not act, and a promotion is refused on either, in Romanian, with no event written and the version
untouched — and the two that are not are named in the refusal instead of being approximated.**
Acceptance criteria and burn-in are judgements about evidence outside the database; nothing here
measures them, so the refusal names them to the Owner and the docstring says plainly that the command
does not verify them. This is the rule the quality gates follow: a check that could not run says so
and never reports a pass. Lowering the mode is allowed unconditionally — 51 calls it immediate and
safe, and a safety state that blocked the safer choice would be the wrong shape of safety.

## 2026-09-18 — The risk-tier table is transcribed from 31 and 32, and it fails closed

**Decision: every entry in `ACTION_RISK_TIERS` is one of 31's own examples, named as the code names
the operation, with 32's tool risk classes deciding where the boundary between T2 and T3 falls; an
action the table does not know and the caller does not classify is refused `BLOCKED_UNCLASSIFIED`,
and a caller's own tier is only ever taken upward.** T0 is read-only, T1 reversible internal, T2
material internal plus EXTERNAL_READ and the paid generation that stays inside the Owner's budget
(31 reserves T3 for "paid generation beyond threshold"), T3 external, financial and public, T4 the
Owner's alone. The order inside `may_act` is 31's authority hierarchy read top down — stop, then T4,
then safe mode, then the mode — so no mode can ever be the thing that lets a lower layer past a
higher one, and an agent cannot downgrade the risk of its own action.

## 2026-09-18 — SUPERVISED writes an Approval rather than refusing, so the row had to exist

There was no Approval object anywhere in the tree, although 31 specifies its fields. **Decision:
`owner_approval_request` carries them (action, requester, risk tier, evidence, proposed diff, cost,
reversibility, expiry, approver, result); `cost_usd` is nullable on purpose, because a cost the
studio cannot compute is None and never zero; a request is reused while it stands rather than
duplicated; and an expired request is marked EXPIRED and a new one raised, because 31 says an expired
approval cannot be reused and saying so in the row is part of the record.** Answering a request is
deliberately not implemented in this phase: a half-built approval route that nothing calls would be
worse than an honest gap, and the gap is named in CURRENT_STATUS.

## 2026-09-18 — The Policy Kernel asks the mode gate for the run itself, at T1, and calls it `agent.run`

**Decision: `_assert_policy_allows_run` asks `may_act(session, "agent.run", "T1")`, immediately after
the stop check and before the lifecycle check.** An LLM call is a reversible internal write — 31's
"create draft" — which every mode allows, so the question changes no behaviour today; it is added
anyway, because a mode that nothing consults is a label, and this is what will refuse a run if the
Owner ever takes the studio below MANUAL's floor or if safe mode opens under a run in flight. It is
`agent.run` and not `script.draft`, which was the first wiring: from a prompt the kernel cannot tell
what the answer will be used for, and calling every run a script draft would have described the
Accountant's letter and an analytics read as drafting. The tier of what an agent then *does* with the
answer — a page fetched, a shot bought, a film uploaded — is asked by the stage that does it.

## 2026-09-18 — A mode refusal is SKIPPED, not BLOCKED

The runbook's vocabulary is exact: COMPLETED means the stage ran to its end, SKIPPED means it could
not run, and BLOCKED is what the Owner's STOP does — `execute_daily_run` stops the day at the first
BLOCKED stage and marks the rest blocked behind it. **Decision: the mode gate returns SKIPPED with
the Owner's Romanian reason, and the tier, the mode and the approval id in the artefacts.** A MANUAL
studio is not a stopped studio: it may not buy a shot or upload a film, but it may still draft,
storyboard, write the serial's episode and measure what it already has. Recording the refusal as
BLOCKED would have ended the day at the research stage and thrown away the internal work the mode
explicitly permits. The day then comes out PARTIAL, which is what it was.

## 2026-09-18 — The upload is T3 at every visibility, and the tier is not read off the channel policy

The tempting version tiers the publish stage by what the film will be: private upload T2, public T3.
**Decision: the tier is fixed at T3 and the channel policy decides afterwards who may see what was
uploaded.** It is wrong twice otherwise. A private upload is still a write to the platform under the
studio's account, which is 32's EXTERNAL_WRITE, and the visibility is a setting the same day's policy
command could change — so the day's riskiest act would have had its risk decided by the thing most
likely to move. It also breaks the mode's shape: SUPERVISED is 51's "configurable T2/T3 actions
create Approval; publishing usually requires approval initially", and a T2 private upload would
publish without ever asking.

## 2026-09-18 — The stop is deliberately not re-read in the mode gate

`may_act` answers BLOCKED_STOP first, and `mode_refusal` treats that answer as "not my refusal" and
returns None. **Decision: the stop stays where it already is — read by the runbook before every
stage, by the media stage before every film, by the render between scenes, by the publishing gate's
five points and by the Policy Kernel — and the wrapper does not become a sixth reader.** A sixth
would add nothing except a new single place where somebody could later think the stop lives, and it
would have changed what a dozen existing tests measure about *other* refusals: a stage called
directly with the stop on would have reported the stop instead of the missing model it was written to
expose. What this gate asks is the question none of the five ask — whether the mode the Owner set
lets the studio attempt the thing at all. The reason is written in the code beside the return.

## 2026-09-18 — Two layers, on purpose: the stage and the act

**Decision: `STAGE_ACTIONS` maps each stage to one action and one tier, tested against
`ACTION_RISK_TIERS` so the two tables cannot drift, and the stages that spend or publish ask again
per film.** The table is what makes "the day's stages mapped to tiers" readable — one line per
stage. The act-level calls are where the answer is specific: `_media` asks again per film with that
film's estimate as the cost on the Owner's question, and with `media.paid_generation_over_threshold`
when the estimate passes his line, so the approval he reads names a figure; `_publish_one` asks again
per film after the Director has approved it and the five-point gate has passed it, so he is asked
about a film that is otherwise ready to go rather than about a hypothetical. `request_approval`
reuses a standing request for the same action, so the two layers cannot bury him under duplicates —
the SUPERVISED end-to-end day writes exactly one row.

## 2026-09-18 — The paid-generation threshold is a setting, because a tier boundary with no number cannot be moved

31 says "paid generation beyond threshold" and names no figure. **Decision: the figure is the
Owner's — `paid_generation_approval_threshold_usd`, default five dollars — read by
`runbook/stages.py::_media` against the film's own `estimate_film_cost_micros`.** Five, because a
six-second shot on `seedance2_5` costs about 2.60 USD on his account and two shots is where one
film's spend stops looking like routine. It changes nothing in AUTONOMOUS_CEO, where both tiers are
allowed: it is the line that decides which question SUPERVISED asks, not a second budget. The
per-film ceiling he already has (`motion_budget_usd`) stays what it is — what a film may spend, not
who decides that it may.

## 2026-09-18 — The preflight's third severity is structural, not polite

**Decision: `INFORMATIONAL` exists as a severity and the preflight's verdict is computed over the
other two only, so an informational line cannot reach `blocking_failures` or `degrading_failures`
even if it reported `ok=False`.** The mode had to appear where the Owner reads the studio before a
run, and it must never fail one: MANUAL is his answer, and a preflight that called it DEGRADED would
be asking him to repair his own decision. A check that is simply always `ok=True` would hold only as
long as nobody edited it. One existing assertion (`test_every_check_says_what_it_found`, which
enumerated the two severities) was widened by one word; nothing else in the tree reads severity.

## 2026-09-18 — `ReferenceRequired` is caught beside the vendor's refusal and settled in the same order

It is a `ValueError`, not a `MediaProviderError`, so the assembler's existing handler would have let
it escape with the job left RENDERING — a render nobody could price afterwards. **Decision: it fails
the job like any unfinished render, which is what lets `record_failed_render_cost` read what was
already bought, and is re-raised as itself; the media stage costs the attempt first and releases the
hold second, the same order and for the same reason as a vendor's refusal.** The estimate stops
counting exactly when the real cost of the attempt starts. It is not a fault and opens no safe mode:
tomorrow's run tries the film again, and producing the character's reference set is the Owner's act.

## 2026-09-18 — The assembler and the Accountant were edited by the integrator, and are named here

`backend/app/media/assembler.py` and `backend/app/economy/accountant.py` were outside the file list
of the implementer who built the chain, and nothing works without them: passing `image_chain` into an
assembler that does not accept it is a keyword error, and recording per-attempt costs that
`_priced_scene_costs` never reads leaves a scene the alternative drew charged to the first vendor's
model. **Decision: the integrator made exactly the two changes the report specified — the two new
keyword parameters and the per-scene attempt records in the assembler, and `scene["image"]` before
the film-level `production["image"]` in the Accountant — and they are called out in the change list
rather than folded in silently.** Both files were untouched in the working tree, so no other
session's work was overwritten.

## 2026-09-18 — Migration numbering: 0041 and 0042 were reserved and not used; 0043 is the head

Three implementers were given 0041, 0042 and 0043 in order. **Decision: the first two took no
migration and said so — the picture and character verdicts live in the existing
`quality_control_report.checks_json`, and the reference set and the approved-fallback lists live in
columns and JSON that already existed — so `0043_autonomy_mode` chains onto `0040_research_sources`,
its docstring records that 0041 and 0042 are free, and `backend/app/main.py` pins 0043 as the head.**
A migration written only to hold a number would be a schema change nobody needed, and a gap in the
numbering that the head pin and the docstring both explain costs a reader one sentence.

## 2026-09-18 — `50_CONTENT_GATE_MATRIX` names the two gates that now exist, and its hash is re-indexed

The matrix listed "Visual factual QC" and a continuity row as gates of the pipeline, and the code had
neither: `character_drift_qc` reported NOT_IMPLEMENTED on every film ever made and nothing anywhere
looked at a frame. **Decision: this is a deliberate specification change under ADR-FOUNDATION-003 —
the gate table gains the two rows the code now runs (`picture_qc` and `character_drift_qc`, at
render and before publish), the gate-behavior section states what each status certifies and that
NOT_APPLICABLE and NOT_IMPLEMENTED carry a reason and a `passed` of None, and a new section states
what the picture gate measures and the four ways it stands down — and the document's `sha256` in
`DOCUMENTATION_INDEX.json` is updated in the same change (`f7da10d8…` → `a436dab0…`), with this
entry as the recorded reason.**
Nothing was removed: every row and rule the matrix carried is still there, and each addition is dated
in place so a reader can see what the matrix claimed before.

## 2026-09-18 — `51_AUTONOMY_MODE_SEMANTICS` says which of its sentences are code and which are not

51 described three modes, a transition rule and a department scoping, and the studio had a constant.
**Decision: this is a deliberate specification change under ADR-FOUNDATION-003 — each mode section
gains a dated line naming the column, the command and the tier the code actually allows; the
transition section states that two of its four requirements are enforced and two are named in the
refusal because nothing in this database can measure them; the department section is marked as not
implemented rather than left reading as current behaviour; and the STOP and SAFE_MODE sections name
where they are enforced — and the document's `sha256` in `DOCUMENTATION_INDEX.json` is updated
(`17cb4169…` → `33f42c6c…`) with this entry as the reason.** A specification that is silent about which of its sentences are built is
the way a reader comes to trust none of them.

## 2026-09-18 — `24_VISUAL_CONTINUITY_ASSET_SYSTEM` says who produces a reference set and what it costs

24 listed portrait, full-body and front/side/back references as properties of a Character Bible and
said nothing about where they come from, while every slot was null in every studio that ever ran.
**Decision: this is a deliberate specification change under ADR-FOUNDATION-003 — the Character Bible
section states that a slot holds a stored asset id or nothing and never a description standing in for
an image; a new dated section states that reference sets are produced by an Owner-triggered route
that spends image credits, refuses under STOP AUTONOMY, holds the money for the whole set before the
first slot, and is named by no stage of the day; the provider-capability and degraded-mode sections
name the reference-image capability the code queries and the one approved alternative per purpose;
and the QC-checks section points at the gate that now measures face, hair, outfit and wrong-employee
drift and at what it cannot see — and the document's `sha256` in `DOCUMENTATION_INDEX.json` is
updated (`8a5d4396…` → `73d5c9cd…`) with this entry as the reason.**

## 2026-09-18 — `08_VIDEO_PIPELINE` was examined and deliberately left unchanged

The second vendor was the one change of this phase that could have made the video pipeline document
untrue. **Decision: it does not, and 08 is not edited.** 08 already says that autonomy must not
depend on one generative video vendor, that IMAGE_PROVIDER has a "reference/edit if supported"
method, that a provider that cannot preserve a character means "change provider" or fail continuity
QC, and that repeated generation failure should simplify, switch provider, fall back or block —
which is the chain the code now implements, bounded at one alternative and ending on the placeholder
still QC blocks. Editing a document to restate what it already says would spend an index hash on
nothing and teach the next reader that the hashes move for cosmetic reasons.

## 2026-09-18 — The roadmap, the changelog and PROJECT_STATE are ticked against this phase

`13_ROADMAP_TODO.md` carried `character drift QC` as flatly unimplemented and
`Manual/Supervised/Autonomous` as "STOP flag plus a dormant-by-default schedule", and
`PROJECT_STATE.json` carried `autonomy_mode: "MANUAL"`, migration 0040 and 1067 tests. **Decision:
the closed boxes are ticked with the date and the evidence, the two that are only half closed are
marked `[~]` with what is missing named in the same line — a picture gate that stands down in the
live studio because no employee's model declares vision, an approval that is written and cannot be
answered — and `PROJECT_STATE.json` moves to `0043_autonomy_mode`, 42 migrations, AUTONOMOUS_CEO and
1148/1.** A tracking document that keeps listing closed work teaches the next reader to stop reading
it; one that ticks a box the studio cannot actually exercise teaches him worse.

## 2026-09-18 — A request is keyed by the action and the subject, and the subject is an identifier the studio already has

The adversarial pass left one defect standing because nothing could yet exploit it: `request_approval`
deduped a standing request by its `action` alone, so under SUPERVISED the second, dearer film of a day
reused the first film's row, carrying the first film's evidence and the first film's price. An
answering route on top of that would have let a yes to a four-dollar film authorise a forty-dollar one.
The candidates for a key were the evidence string, the channel and the film. **Decision: the key is the
action plus `subject`, a new column on `owner_approval_request` (migration `0044_approval_answered`)
holding the identifier of the thing the question is about — the media asset for an upload, the
storyboard for a paid render.** The evidence is prose for the Owner to read; it changes when the
Publisher rewrites the title and is truncated to fit, and a key that moves when the wording moves is
not a key. The channel is too coarse in the other direction: two films reach one channel across two
days and one answer would cover both. The film is what he is actually being asked about and what the
act itself writes, and the channel derives from it, so keying by the film keys by the channel for free.
A re-render produces a new asset id and therefore a new question, which is the conservative reading and
the right one: he approved the film he was shown. An action with no subject keeps the old behaviour
under an empty string, because an action about the studio itself has one answer by nature.

## 2026-09-18 — The daily run's stage wrapper asks the mode and does not ask the Owner

The same defect existed one level above `request_approval`, where nothing had looked.
`build_stage_runners` asked `may_act` for the publish stage before the stage ran, with no film on the
request: under SUPERVISED that answer skipped the stage outright, so `_publish_one`'s own per-film gate
was unreachable code, one answer would have authorised every film of the day, and a studio with nothing
in the publish queue still put a question in the Owner's inbox. **Decision: `may_act` and `mode_refusal`
gain `ask_owner=False`, and the wrapper uses it — the mode is asked without anything being written and
without any answer of his being spent, and the caller that can name the film does the asking.** A mode
that refuses outright — MANUAL on a T3, safe mode, T4 — still refuses at the wrapper, so nothing above
the mode moved. The proof changed with the fix: the end-to-end SUPERVISED day used to record one
request for the whole day and now records two, one for the factual short and one for the serial's
episode, each with its own subject.

## 2026-09-18 — The Owner's answer is spent inside `may_act`, not beside it

The publish stage could have looked for an APPROVED row itself and then skipped the gate. **Decision:
the answer is read in exactly one place, the SUPERVISED T3 branch of `may_act`, after the unclassified
refusal, the stop, T4 and safe mode have each had their say.** Reading it beside the gate would have
put his yes *above* the authority hierarchy of 31 instead of inside it, and the first thing anyone
would then have had to re-derive is what a stop means for a film that was already approved. Inside, the
whole of 31's order comes for nothing: an approval can only ever convert the one verdict it is about —
"he would have to be asked" becomes "allowed, once" — it can never reach a refusal above it, and every
one of those refusals leaves the yes unspent, which is the behaviour a stop should have. It pauses the
studio; it does not retract what he decided.

## 2026-09-18 — A column is the lock, the ledger is the record, and the yes is spent before the act

**Decision: `consumed_at` on the row is what the gate reads, `governance.approval_consumed` is written
beside it, and the spending happens before the act it authorises rather than after.** A gate that had to
walk the event history for every film would make the day's riskiest decision depend on a scan, and the
index (`action`, `subject`, `result`) is exactly the query the publish stage makes once per film; the
event is written anyway, because the column alone would leave "the film went out on the Owner's yes" as
a nullable timestamp nobody reads. Spending it first is the conservative direction: an upload that then
fails costs him one more question tomorrow, where the alternative costs him an upload he only agreed to
once.

## 2026-09-18 — What a stop, an incident, a lowered mode and a moved policy version each do to an answer he has already given

**Decision, written into the code and now into 31: a STOP AUTONOMY and a SAFE_MODE refuse before his
answer is looked for at all, so the yes is still there, unspent, when he lifts the stop or the incident
closes — neither of them is him changing his mind. A channel policy version that moved after he
answered does retract it, because he said yes to this film going out at that visibility under that
version: the proposed diff he was shown is compared at the moment of spending, the stale yes is left on
the record unspent, and a fresh request naming the new policy is raised. Lowering the mode to MANUAL
refuses too, and never looks for the answer: MANUAL is him asking to be asked about everything, and an
answer given under a more permissive mode must not be the way past the mode he chose to replace it.**
This is 31's "gate immutability" read for approvals — an approval applies to an exact version, never to
an idea — and it is now specified there rather than living only in the order of four branches.

## 2026-09-18 — A refusal is COMPLETED, an unanswered question is SKIPPED

The publish stage's vocabulary was already exact: SKIPPED means the studio could not do the work,
COMPLETED means the work was done and the answer was no, which is how the Director's refusal and the
Publisher's HOLD are already recorded. **Decision: the Owner's refusal is an answer, so the stage
reports COMPLETED with `refused_by_owner` and the approval id, and the status is deliberately spelled
`REFUSED_BY_OWNER` and not `BLOCKED_OWNER_REFUSED` — the studio was permitted to ask and got an answer,
which is not a block.** A question still standing stays SKIPPED with `awaiting_owner` and the approval
id, as it was. The film keeps the verdict quality control gave it, because he said no to sending it out
and not that anything is wrong with the film, and nothing asks again until his decision expires — the
same 24-hour clock that decides how long an unanswered request stands.

## 2026-09-18 — The decision command carries no `expected_version`

The Owner's other commands guard `owner_policy.version`, because that row is edited by several commands
and a page can read it minutes before it writes. **Decision: `ApprovalDecisionCommand` carries a command
id and no expected version, because the row it answers has no version to be stale about.** An approval
request's whole life is one transition, PENDING to answered, made by one command; the only thing that
can go wrong is answering twice, and that is refused directly with 409 and the result the row already
carries. A version column would have been a guard against a race that does not exist, and a schema
change to express it. An expired request is refused the same way and is deliberately left PENDING on the
way out — it is filtered out of everything that reads it by its own expiry, and a command that fails
must not be the thing that changes state. A request the studio never made is 404, because that is what
it is: a stale page, not a governance conflict.

## 2026-09-18 — Nothing is written into the agents' memory when the Owner answers

The mode, the environment and the stop each write an `OWNER_POLICY` memory every agent reads, because
each is a standing rule about how the studio works. **Decision: an approval writes none, and
`decide_approval`'s comment says why the pattern is broken here on purpose.** An approval is about one
film. A letter to every agent for every upload would be the noise that makes the standing rules
unreadable, so the answer lives in the row, in the ledger and in the stage's own report.

## 2026-09-18 — The Owner's two buttons are measured by the day's rules, not by their own

A film read twice — once by the stage and once by the Owner — disagreed about which gates had run at
all: the stage handed quality control the registry and the encoder, the route handed neither, and
`picture_qc` and `character_drift_qc` came back NOT_APPLICABLE with a reason that was true of the caller
and not of the film. **Decision: both `evaluate_media_qc` call sites in `backend/app/media/router.py`
pass `registry` and `ffmpeg_path`, read from where the app already holds them, so the Owner's reading of
a film is the reading the day would have given it.** This does mean his Quality Control button may now
make one vision call and cut frames with FFmpeg inside the request, where before it only probed the
container — it is his act, on his provider, and it is the same single call per film the stage makes.
With no vision-capable model, no registry or no encoder it is still NOT_APPLICABLE with the reason and
the verdict is exactly what the other gates left it: nothing there passes by absence.

## 2026-09-18 — An injected adapter stays the only vendor; the character's reference travels regardless

`app.state.image_adapter` is how a test says "this vendor draws this film". **Decision: `start_render`
passes the plan's `image_chain` only when nothing was injected, and passes `reference_for_scene`
unconditionally.** Handing the assembler the studio's resolved vendors in front of an injected adapter
would break what injection means, and the route already applied that rule to the injected voice. The
reference is not a statement about a vendor: it resolves which character's stored sheet a scene must be
drawn from and refuses a film whose locked character has none. Suppressing it for an injected adapter
would let exactly the render that is easiest to run invent a face the Owner locked.

## 2026-09-18 — A missing reference is a refusal with its own answer, not a lost storyboard

`app.media.services.ReferenceRequired` subclasses `ValueError`, and `start_render` answered every
`ValueError` with 404 and the exception's text, so the studio declining to invent a locked character's
look was reported to the Owner as "storyboard not found" about a storyboard sitting in front of him.
**Decision: it is caught before the `MediaProviderError` handler and answered 422 with
`error: ReferenceRequired`, a Romanian message telling him to produce the character's reference set
first, and the refusal's own text naming the character.** It is deliberately not a 502: the vendor did
nothing wrong.

## 2026-09-18 — Runway is given the picture in the field its own contract publishes

`RunwayImageAdapter` could not be handed a reference at all, so `accepts_reference_image` read False for
it, the chain dropped the sheet, and a Runway-drawn still of a locked character was honestly recorded as
drawn from the words. **Decision: the adapter sends `referenceImages` on the documented `text_to_image`
task as an array of one object whose single required member is a `uri`, built as an inline data URI by
the same helper that has always validated an image-to-video first frame — so a reference given as a
path, an id, or bytes that are not a PNG, JPEG or WebP is refused before the task is submitted — and the
result's raw response counts `reference_images` 0 or 1.** The studio holds the bytes of the sheet it
produced and not an address anybody else can fetch, which is why it is the inline form. No `tag` is sent
with the reference: a tag means something to Runway only when the prompt names it as `@tag`, and
inventing one would change the words the Director approved. The per-attempt count is what makes a
render's record able to say whether a character's face came from their sheet or from the words.

## 2026-09-18 — The contract refusal for a model that requires references was about the missing picture all along

The adapter refused any model whose published contract lists `referenceImages` as required —
gen4_image_turbo, which answered HTTP 400 to every scene of a day drawn from words alone. **Decision:
that refusal now fires only when no reference was given**, because with a character's sheet in hand the
stated reason, that the model cannot generate a still from a prompt alone, is no longer true. The
catalog still keeps such a model out of the `image` purpose, so nothing in the studio chooses one for a
storyboard whose scenes may have nobody in them; the path exists for a model the Owner names by hand and
it has never been run.

## 2026-09-18 — What the code builds and what the account has answered are two statements, and both are recorded

**Decision: `ACCEPTS_REFERENCE_IMAGE` is True on the Runway image adapter because the code builds the
documented field, `REFERENCE_IMAGE_VERIFIED` stays False as it does on the OpenAI adapter until an
Owner-approved live run has actually drawn a scene this way, and a test asserts the second flag is
False so nobody can flip it on mock evidence.** No test may spend a credit to find out. Neither
adapter's reference path has ever been accepted by a vendor, and an HTTP 400 on the first real render is
the thing to watch: that is how the last unread contract detail announced itself.

## 2026-09-18 — The autonomy mode is shown where the studio's state is shown, and the page refuses only what it can see

The autonomy switch, the environment banner and the module list are the three things that say what the
studio is; the mode is the fourth. **Decision: the governance panel lives in the ledger column under
`modules-panel`, inside `#workspace` so it is invisible until the Owner has a key, and it refuses a
promotion it can already see is impossible while never refusing one it cannot see.**
`promotionBlockedReason` reads only the stop, which is in the snapshot, and says so in his language
before spending a request; SAFE_MODE is not in the snapshot, so the page does not infer it, does not
grey the button out on a guess, and prints the server's own 409 sentence when it arrives. A blocked
mode button therefore stays pressable, because pressing it answers *why* and a disabled button cannot.
An unconfirmed mode command is resent only when its `autonomy_mode` is the one now being asked for and
replaced otherwise, because with three modes a slow network is one decision and a change of mind is a
different one — the two-state switches of the stop and the environment could keep a single pending
command and this cannot.

## 2026-09-18 — The approvals list is read on a slower clock, a missing route is said once, and every card repeats what an approval is not

An approval stands for a day. **Decision: the panel reads `GET /api/v1/owner/approvals` at most every
thirty seconds, immediately after any decision and whenever the Owner presses refresh; a backend that
answers 404 is recorded as not having the route and stops being asked, with one sentence saying the
requests exist in the database while the route that shows them does not.** Fetching a list nobody
answered sixty times an hour, or repeating a 404 every five seconds, teaches its Owner to ignore the
panel. **And every request card carries, in Romanian, the sentence that an approval lets a permitted
action happen and never turns a hard gate's refusal into a pass** — 31 says a hard gate's result cannot
be overridden, and the most likely misreading of a green «Aprobă» button is that it makes something
pass.

## 2026-09-18 — A cost nothing could compute stays «necunoscut» on the page, and a reference set takes two presses

**Decision: `approvalCostText` returns «necunoscut» for anything that is not a finite number and
`0.00 USD` only for an actual zero, the panel prefers the server's own `cost_label` when the row carries
one, and the same function labels the reference set's price.** A page that formatted `cost_usd` itself
would show "0 USD" for a question nobody can price, which is the one number the books are written never
to invent. **And the reference-set button states its cost on the first press and generates nothing until
the second**: the slots are drawn as chips rather than summed into a ratio, because "3/5" does not tell
him which slot is missing — and a missing reference is exactly the reason a locked character's scene is
refused.

## 2026-09-18 — The panel's judgements were put in a module so that they could be tested

`main.js` touches the document at import, so `node --test` cannot load it. **Decision: rather than
invent a DOM harness, the decisions that matter — what a mode means, whether a promotion is possible,
how a request's cost and expiry read, which slots a character has, what shape each command takes — moved
to `frontend/src/governance.js` and are tested there (14 tests, 102 in the frontend suite, `tsc`
clean).** What remains untested is the wiring: which element the text lands in, and that a click reaches
the right function. That is recorded as untested rather than covered by a harness that would have proved
something else.

## 2026-09-18 — `31_GOVERNANCE_APPROVAL_POLICY` is edited and re-hashed; 51 is corrected; 50 is left alone

31 specified the Approval object and stopped there: it said an expired approval cannot be reused and
said nothing about how one is answered, how it is consumed, that one approval authorises exactly one
action, or what a STOP, a SAFE_MODE or a policy-version change does to one already given. The code now
answers all four. **Decision: 31 gains one dated section, *Answering an approval, and spending it*, as a
deliberate specification change under ADR-FOUNDATION-003, with its `sha256` re-recorded in
`DOCUMENTATION_INDEX.json` (`c788e9bc…` → `b4aedc31…`) and this entry as the reason.**
`51_AUTONOMY_MODE_SEMANTICS` carried two sentences this closure makes untrue — a **Not built:**
paragraph saying nothing answers a request, and "writes exactly one request" for a whole SUPERVISED day
— so its Supervised section is corrected in place, dated, with its `sha256` re-recorded as well
(`33f42c6c…` → `f5f96f18…`). **`50_CONTENT_GATE_MATRIX` was read and deliberately left unedited, its
hash unchanged:** the picture and character gates it describes are unchanged by this closure, and the
Owner's route now running them is a fact about a caller, not about a gate. Editing a document to restate
what it already says spends an index hash on nothing.

## 2026-09-18 — The closure's recorded figures are attributed rather than invented

No whole-suite run has been made since the three closure parts landed, and the brief for this part
forbids running one. **Decision: the last whole-tree figure (1152 passed, 1 skipped) is left standing in
CURRENT_STATUS and PROJECT_STATE as what it is — the adversarial verifier's measurement, now older than
the tree — and every figure this closure adds is written with the part that measured it beside it:** 231
Python tests across the files the governance part owns and their neighbours, 186 across the media part's
four files and its regression set, 102 frontend tests with 14 new, and `check_docs.py` plus
`tests/test_documentation.py` for this part. `javascript_passed` moves 87 → 102 because that figure *is*
a whole-suite measurement of its suite; `python_passed` does not move, because inventing a number for a
run nobody made is the one thing these documents exist to prevent.

## ADR-PREFLIGHT-003 — The preflight reports what only the Owner can supply
**Status:** Implemented, 2026-09-18

Problem: the preflight answered "can the day start" and nothing answered "is the day worth having".
Five things decide whether the first real day produces a quality film, every one of them was measured
as absent on the live copy, and the Owner had no single place that told him: no active budget, no
price for the models the employees run on, no employee whose model declares vision, five reference
slots null in every studio that has ever run, and a serial channel with no leave for the Director.
Choice: five more checks in `app.runbook.preflight`, each reading the database only —
`app.economy.budget.budget_status`, `app.economy.prices.price_for` on both token units,
`app.agents.vision.vision_agent`, `CharacterBible.reference_assets_json` against `MediaAsset`, and the
OFFICE_SERIAL `ChannelRecord` with `channel_bindings`. Rejected: probing a vendor to confirm a price
or a model's vision (a preflight that made outbound calls would be slow, would fail for reasons
unrelated to the studio, and under the Owner's rule of 2026-09-17 would cost money to answer a
question the record already answers), and reading a vendor's published price to fill a gap in the
price table (a guessed price in the books is worse than the gap the Accountant reports). No schema
change: every fact these checks need is already a column.

## ADR-PREFLIGHT-004 — A check never blocks the day for something the Owner chose
**Status:** Implemented, 2026-09-18

Problem: a budget the Owner has not set while the studio is in TEST, and a serial channel he has not
created, are answers of his, not capabilities the studio is missing. A preflight that refused the day
over either would be asking him to repair his own decision, which is the same mistake `autonomy_mode`
avoided by being INFORMATIONAL. Choice: none of the five is BLOCKING; `serial_channel` is
INFORMATIONAL always, and `character_references` is DEGRADING only where a character whose look is
*locked* has no readable reference — that case really does refuse a film
(`image_reference_for_scene` raises rather than invent a face), so it is a blocked day the Owner can
prevent in advance; an unlocked character with no picture is a line he reads. The verdict is computed
over BLOCKING and DEGRADING only, so this holds structurally rather than by the checks happening to
pass, and a test asserts that a studio with nothing configured still reports exactly `stop_autonomy`
and `llm_provider` as blocking.

## ADR-GOVERNANCE-006 — How long an approval stands is the Owner's setting
**Status:** Implemented, 2026-09-18

Problem: `APPROVAL_EXPIRES_AFTER_HOURS = 24` was a module constant in `backend/app/services.py`. One
number decides three things — how long an unanswered question stands, how long a refusal keeps the
studio from asking again, and how long a yes can be spent — and the Owner could not reach any of them
without a source edit. Choice: `approval_expires_after_hours` on `Settings` (default 24, `ge=1`,
`le=168`, `STUDIO_APPROVAL_EXPIRES_AFTER_HOURS`), with the bounds stated as what they protect: below
an hour a question could expire before he reads it, above a week a yes could be spent long after the
film it was asked about. `services.py` reads it through `approval_expires_after_hours()`, a local
import of `Settings` with `getattr` and a documented fallback of 24 — the shortcut `providers.retry`
and `integrations.autoconfig` already take, because this module is called from inside a session and
has no handle on the application, and a studio whose settings cannot be built must still be able to
ask the Owner a question rather than raise while asking it. Behaviour unchanged;
`tests/test_approvals.py` (18) and `tests/test_autonomy_modes.py` pass untouched.

## 2026-09-18 — PREFERRED was honoured nowhere, so it was implemented in the hiring path and not by making it REQUIRED

`RoleCapability.requirement_level` accepted any string, but the only readings in the whole codebase
were `== "REQUIRED"` in `_check_required_capabilities` (`backend/app/agents/services.py`) and,
indirectly, in `assign_agent`. The "PREFERRED" in `backend/app/integrations/lifecycle.py` is the last
step of a model's life (DISCOVERED → … → PREFERRED), not a requirement level, so there was no
precedent for a preference in assignment at all. **Decision: implement it where the role is owned —
`seed_role_preferences` writes the PREFERRED row on the Video Editor's role, idempotently at every
start-up so that it also reaches a studio whose roles were created earlier, and
`prefer_capable_models` acts on it.** Making the capability REQUIRED was rejected: it would have
blocked the role in a studio with no seeing model, which is exactly what the brief forbids. The move
writes `agent.model_preferred`, never `agent.model_assigned`: the second event is the proof of the
Owner's choice and `apply_llm_allocation` reads it as "already configured", so writing it here would
make the next start-up read the studio's own move as his and stop applying his allocation file. A
candidate must be available and declare everything the role *requires*, not only what it prefers,
otherwise the move would trade a working employee for one the Policy Kernel blocks. `list_roles`
still returns REQUIRED capabilities only — the field is called `required_capabilities`, and listing a
preference there would tell the Owner the Video Editor needs a seeing model to work at all, which is
false.

## 2026-09-18 — `vision` is a row in the table, not a claim about any model

The seed now creates `Capability(name="vision")`, because a role can only prefer a capability the
studio has by name. **Decision: attach it to no proposed model.** `SEEDED_MODEL_CAPABILITIES` names
the four text capabilities explicitly, replacing the loop that wrote "every capability" onto every
proposed model. Nothing in the seed contacts a provider, so a seeded guess that a model can see would
make the picture gate certify a look nobody took; `sync_provider_models` attaches `vision` where the
vendor itself declares it, which is the only evidence that exists.

## 2026-09-18 — A factual scene's cast is read from the scene itself, in two readings, in the order of the evidence

**Decision: the scriptwriter's `characters` list first (the shape the serial's script already uses),
then the names in the requested picture (`visual_prompt`/`visual_description`, read through one
`_scene_visual` so the cast and the scene cannot disagree about what the picture says). The narration
is not read at all:** in a factual film it is the narrator's voice, and a name spoken over a
photograph of a mirror does not put that person in frame. Matching is on the full canonical name or
the first name — the rule `app.story.services.bibles_for_roster` already uses to match a cast member,
without the title that rule keeps by mistake ("Aris", not "Dr.") — capitalised as in the bible, and
never on a first name followed by another capitalised word, so that the observer "Vera Rubin" stays a
telescope. The cost of that last rule is a Title Case scene whose character is missed; the cost of
dropping it would have been an invented cast, and a gate comparing a film against a cast nobody put
in it certifies nothing.

## 2026-09-18 — "No cast, by design" is written in the storyboard's creation event, not in a new column

The ledger is where the studio already keeps facts of this kind (`agent.model_assigned` is exactly
such a fact), and what is needed here is a record, not a lock. **Decision: `media.storyboard_created`
carries `scenes_with_cast` and `cast_note`, read back by
`app.media.services.storyboard_cast_note(session, storyboard_id)` and returned by `get_storyboard` as
`cast_note`.** So migration 0046 was not taken and the revision chain keeps one head, the one the
economy moved with 0045. A storyboard written before this revision, or one whose scenes do list
characters, answers None: "nobody said" and "somebody is in it" are both not this.

## 2026-09-18 — The letter about what is waiting is one a day, not one a question, and does not exist when nothing waits

The pattern followed is `_letter_once_a_day` exactly: idempotent on the studio's business date,
decided behind the write lock, so two stages of the same day cannot write two letters. **Decision:
one letter per day naming every standing question, and nothing at all when nothing is standing.** A
letter per approval request would have buried the single decision he has to make under duplicates —
the mistake `request_approval` already avoids by keeping one request per (action, subject). The
silence is meaningful: a day with no letter means nothing is being asked of him. The questions are
ordered as the day raised them (by `created_at`), so the first line is the oldest and the deadline in
the last line is its deadline. The cost of a question is read from the request itself
(`approval_view.cost_label`, «necunoscut» where `cost_usd` is None) and never recomputed, so the
governance page and the mailbox cannot say two different things about the same question; the
model-written evidence enters the text cut at 120 characters, because it is what the panel shows
beside the same question and a long title may not become the whole letter. `reconcile_day` calls it
as its first act rather than its last: a close that fails because a model never produced the report
must not swallow the only letter saying he has decisions standing.

## 2026-09-18 — Reconciliation marks the estimate, it does not subtract it

The obvious variant — subtracting the estimated sum from the period — would have required
`spend_since` to know about invoices and would have left the books with a figure that can no longer
be reconstructed from the rows. **Decision: the estimate is kept whole, because it is the document of
what the studio believed a film would cost, and is stamped `reconciled_at`; `spend_since` skips it.**
The BILLED row the invoice writes carries the hour of the last spend it pays for, so it falls in the
same period as the estimates it replaced. The exact consequence: after a reconciliation a period
counts the billed sum once, plus any row in the period the invoice did not cover, and
`treasury_snapshot.unbilled_provider_costs` falls the same way, because an estimate that has been
paid is no longer an obligation coming. **An invoice over an already reconciled period is refused
without `expected_version`, unlike a price:** `set_price` accepts a command with no version and
replaces what stands, which here would let an inattentive command reverse a ledger posting. The
correction, when it comes with the right version, posts the mirror of the previous transaction
(`reverses_transaction_id`, as `reverse_transaction` does), stamps `reconciled_at` on the invoice it
replaces so it stops being counted, and re-adopts the estimates the first one covered. The ledger
stays append-only and the balance stays closed.

## 2026-09-18 — What could not be matched is reported, never dropped and never kept quiet

`unmatched_json` sits on the reconciliation row and not only in the HTTP answer, because a spend the
invoice does not explain is the finding, not a detail of one request. Three kinds: a row already
reconciled by another invoice (it cannot be paid twice), a row already billed directly (it is not an
estimate to replace), and the case where the invoice covers no estimate in the books at all — the sum
is still recorded, with the reason, because the vendor billed whether or not the studio can explain
it. The difference between what the vendor billed and what the studio estimated is reported as a
figure (`difference_vr`) rather than melted into the total: that distance is the price of an
assumption.

## 2026-09-18 — The migration head moved to 0045 in `main.py`, and 0046 stayed free

`backend/app/main.py` is not the economy's file, but every test that starts the application fails at
start-up if the database revision is not the pinned one, so one line and the comment that says why
were changed there. The brief reserved 0045 for the economy and 0046 for the media part; the media
part needed no column and took neither. **Decision recorded here so the next phase does not have to
rediscover it: the chain is 0039 → 0040 → 0043 → 0044 → 0045, `main.py` pins `0045_reconciliation`,
and 0046 is free.** If a future part needs a cast column on `storyboard`, that is the number to take.

## 2026-09-18 — `39_DAILY_AUTONOMOUS_RUNBOOK` is edited and re-hashed

The runbook's preflight section listed the checks the day makes, and five were added on 2026-09-18
that it did not name — including two that report a state no severity in the document had, because
they never fail the day. Its post-run section said "reconcile cost" and nothing about the letter the
day now sends the Owner before it closes. **Decision: 39 gains two dated paragraphs — the five new
checks with their severities and the rule that none of them blocks, and the waiting-approvals letter
as the first act of the close — as a deliberate specification change under ADR-FOUNDATION-003, with
its `sha256` re-recorded in `DOCUMENTATION_INDEX.json` (`1de4ef7a…` → `226397b6…`) and this entry
as the reason.**

## 2026-09-18 — `15_SECURITY_COSTS_OBSERVABILITY` was read against the new books and deliberately left unedited

The question asked was whether that document still describes the books truthfully now that a
reconciliation exists. It does: its *Cost controls* section already requires recording "estimate
before action; reserved amount; actual/reconciled amount", and its financial metrics already list
"reconciliation backlog" — sentences that were aspirational when written and are now met by
`reserve_spend`, `record_render_costs` and `provider_reconciliation`. Nothing in it is false, and its
hard boundary (no ordinary agent's tool may hold outbound payment authority) is untouched by a route
that is Owner-only through `require_owner`. **Decision: report it as incomplete rather than edit it,
and spend no index hash.** What it does not say, and what a later editor of that document should add
if it is opened for another reason: that reconciliation is the Owner's act alone because only he sees
the invoice; that the estimate is kept and marked rather than replaced, so a period counts the
estimate until the invoice arrives and the invoice afterwards, never both; and that an employee's
token cost is computed in `agent_run` and never passes through `provider_cost_record`, so it is the
one spend no invoice can yet reconcile. Editing a document to restate what it already says spends an
index hash on nothing.

## 2026-09-18 — «Ce are Owner-ul de făcut» becomes an ordered checklist, and keeps every line it had

The section had grown by accretion: eleven bullets in the order the phases that needed them landed,
inside the Money-and-sources section, which is not the order a person does them in on the morning of
the first real day. **Decision: rewrite it as a numbered checklist — migrate, build, read the
preflight, budgets, prices, token ceiling, sites and search engine, channels and their policy, a
model that can see, the character reference sets, the fallback vendors, the autonomy mode, and only
then the clock — move it under the readiness section, and leave a dated pointer where it stood.**
Every existing bullet's content is kept and each line now carries three things: what to do, with what
command or screen, and what happens if he skips it. Activating the daily job and installing the
scheduled task are last on purpose: the Owner's rule of 2026-09-17 is that video generation costs
money and happens only after everything is proven, and steps 1 to 12 are what "everything" means.
Reconciling a vendor's invoice is step 14 because it cannot be done before there is a real spend to
reconcile.

## 2026-09-18 — The readiness phase's figures are attributed, and the suite figure is left for the verifier

No whole-suite run was made by any of the four parts of this phase, and the brief for the documents
forbids running one. **Decision: every figure recorded for this phase is written with the part that
measured it beside it — 11 + 46 and its neighbours for the preflight part, 359 across five owned and
nineteen neighbouring files for the workforce and storyboard part, 11 + 17 + 34 + 18 and its
neighbours for the economy part, `check_docs.py` and `tests/test_documentation.py` for this one — and
`PROJECT_STATE.json` keeps 1194 passed / 1 skipped as what it is: the Phase D/G closure's adversarial
verifier's measurement of 2026-09-18, now older than the tree.** The whole-suite figure for this
phase lands when the verifier takes it, after these documents. Inventing a number for a run nobody
made is the one thing these documents exist to prevent.
