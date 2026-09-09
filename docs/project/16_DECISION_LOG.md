# Architectural / Product Decision Log v5

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
