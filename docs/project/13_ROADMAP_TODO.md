# Roadmap / TODO v3

Implementation 2026-09-09: Phase 0 acceptance verified. See [VERIFICATION.md](VERIFICATION.md).

> **Audit correction, 2026-09-09** — see [AUDIT_2026-09-09_EXTERNAL.md](AUDIT_2026-09-09_EXTERNAL.md)
> and [CURRENT_STATUS.md](CURRENT_STATUS.md). Phases 4, 5 and 6 were previously marked complete;
> their acceptance criteria are **not** met and they are now tracked as partial:
>
> - **Phase 4** — the verification and gating machinery is real, but there is no search/research
>   adapter and no independent fact-checker. Sources are pasted by the Owner; a claim's status is
>   whatever the caller sends. Acceptance ("real research, evidence, independent fact checks") open.
>   Update 2026-09-12: the Researcher proposes topics and names pages; the studio finds pages
>   through each authorised site's own search address (OpenSearch, recorded by the Owner) and
>   reads them; the Fact Checker verifies claims against the fetched text.

### Voice stays its own connection (decided 2026-09-12)

Runway's API does expose ElevenLabs models — `eleven_v3` and `eleven_multilingual_v2` on
`/v1/text_to_speech`, plus dubbing, isolation and sound effects — and the Owner's tier
includes them, so one connection for picture and voice is technically possible. It was
examined and set aside, for reasons that are facts rather than preferences:

- `eleven_v3` there accepts only Runway's own preset voices (49 names), not an ElevenLabs
  `voice_id`; the character identity locks bind ElevenLabs voices, which have no equivalent.
- Each `eleven_*` model on Runway allows 50 generations a day; an eight-scene film spends
  eight, so roughly six films a day. Direct ElevenLabs limits characters, not calls.
- Runway bills in credits (measured: about sixteen credits a second of generated video),
  ElevenLabs in characters; which is cheaper for narration is not known without measuring.

The Owner's decision: keep the ElevenLabs connection separate. Revisit only with a measured
cost comparison, and never at the price of a locked character's voice.
> - **Phase 5** — FFmpeg now produces a real 1080x1920 H.264 file, but there is no image provider
>   and no TTS provider, so the frames are placeholders and QC blocks them from publication.
>   Character continuity is unimplemented. Acceptance ("provenance-backed media") open.
>   Update 2026-09-18: Runway and ElevenLabs are connected since 2026-09-12; captions are burnt
>   in and loudness normalised since 2026-09-17; character-drift QC is still `NOT_IMPLEMENTED`.
> - **Phase 6** — the gate, state machine and idempotency are real, but OAuth has never been
>   exercised and no upload has ever reached YouTube. Acceptance ("official OAuth, private upload
>   with verified remote ID") open.
>   Update 2026-09-18: OAuth is real since 2026-09-11 and two private uploads with real remote
>   ids (`98JltCPoOKs`, `sDEtt-WQGh8`) reached Main Channel A on 2026-09-12; since 2026-09-17
>   the publish stage sends each film to its storyboard's channel at that channel's Owner-set
>   policy, private by default.
> - **Phase 7** — `backend/app/analytics/` exists on disk but is unmounted, unregistered and has no
>   migration. It is not started work in any deliverable sense; add migration `0008` first
>   (`0007` is the audit data-correction migration).
>
> Order of work: close 4, then 5, then 6, before starting 7.
Canonical phase numbering and original-version mapping: [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).
Early STOP/event primitives do not complete Phase 1/2/10 requirements.

## PHASE 0 — Foundation
- [x] Inspect repository
- [x] Define repo structure
- [x] Backend skeleton
- [x] Frontend skeleton
- [x] Database
- [x] Migrations
- [x] Config/secrets
- [x] Structured logging
- [x] Health endpoint
- [x] Base tests
- [x] Documentation bootstrap

Acceptance:
backend/frontend/DB start and tests run.

## PHASE 1 — Agent + Capability + Permission Core
- [x] Agent entity
- [x] Role contract
- [x] Skill/capability model
- [x] Tool registry (ToolReceipt + ProviderRegistry)
- [x] Permission engine (Owner Policy Kernel: stop / lifecycle / capability / health / budget gates)
- [ ] Director (Phase 2+ - requires workflow engine)
- [x] Provider registry
- [x] Ollama/Ollama Cloud adapter
- [ ] custom compatible adapter (OpenAI-compat - Phase 2+)
- [ ] fallback routing (Phase 2+)
- [x] agent messages (AgentRun envelope with full audit trail)
- [x] audit log (DomainEvent + ToolReceipt immutable history)

Acceptance:
real LLM task works (requires Ollama running, set STUDIO_OLLAMA_URL); unsupported capability is blocked ✅; Director cannot bypass policy ✅.

## PHASE 2 — Durable Automation / Events
- [x] Persisted workflow state machine (Workflow, WorkflowStep, 17 pipeline stages)
- [x] scheduler (ScheduledJob, singleton-safe leader leases, SKIP/CATCH_UP)
- [x] queue/worker (TaskQueueItem, atomic claim with worker leases)
- [x] leases/locks (time-bounded leases, heartbeat, expired lease recovery)
- [x] retry/backoff (exponential backoff calculation, retryable classification; since 2026-09-17
  every provider call and every runbook stage retries a transient fault within a bound)
- [x] circuit breaker / dead-letter queue (DEAD_LETTER status on max attempts, operator retry)
- [x] idempotency keys (idempotency_key on task_queue)
- [x] cancellation (cancellation transition in workflow state machine)
- [x] transactional outbox/event publishing (OutboxRecord, publish_pending_outbox)
- [x] WebSocket gateway (/api/v1/ws with owner auth)
- [x] snapshot/replay protocol (replay message with after_sequence cursor)

Acceptance:
workflow survives restart ✅; duplicate scheduler does not duplicate work ✅; UI can replay missed state ✅.

## PHASE 3 — 2D Office
- [x] PixiJS vs Phaser decision (Decided in ADR-PHASE3-001: lightweight native Canvas2D, <20kB bundle, 60fps, zero bloat)
- [x] top-down office canvas (Canvas 2D, DPI aware, pan & zoom 0.4x - 2.5x, fitToOffice)
- [x] generic Room/Desk (8 zones: DIRECTOR, RESEARCH, SCRIPT, AUDIO, VIDEO, PUBLISH, SERVER, LOUNGE with desks)
- [x] persistent office world state (`GET /api/v1/office/layout` + `OfficeState` tracking agents, desks, events)
- [x] character identity system (Agent avatars with role colors, badges, initial letters)
- [x] runtime-state animation map (Pulsating state rings: THINKING=amber, WORKING=blue, IDLE=green, PAUSED=gray)
- [x] speech bubbles from real messages (Auto-rendered on `agent.message_sent` or `agent.run_completed`, 5s decay)
- [x] Agent Inspector (Dialog modal `#agent-inspector`, run task, pause/resume)
- [x] Provider Room (SERVER zone with 3 server racks and real-time blinking LEDs)
- [x] content pipeline visualization (Project tokens with stage colors moving across zones)
- [x] reduced motion (`prefers-reduced-motion` CSS & disabled pulsing)

Acceptance:
all live animation comes from backend event/state. ✅

## PHASE 4 — Factual Intelligence
- [x] Idea Agent (propose_topic_idea, topic_idea table, deduplication scoring)
- [x] Research Agent (ingest_source_snapshot, extract_claims)
- [x] source metadata (url, publisher, author, credibility_score)
- [x] research snapshot/hash where practical (SHA-256 content_hash in source_snapshot)
- [x] Claim model (factual_claim with importance, confidence, status: UNVERIFIED, SUPPORTED, REFUTED)
- [x] Fact Checker (verify_claim service and REST endpoint)
- [x] claim freshness/stale state (verified_at timestamp, stale detection)
- [x] prompt-injection defense (Zone D sanitizer, delimiter stripping, inert boundary tag)
- [x] Script Writer (generate_script_draft with scene breakdowns and voiceovers)
- [x] Hook Specialist (generate_hook_options with psychological techniques & retention scores)
- [x] optional History Reviewer (supported via HISTORICAL_EVENT claim typing and validation)
- [x] optional Science Reviewer (supported via SCIENTIFIC_FACT claim typing and validation)
- [x] manual topic UI (modal dialog in frontend, open-research-btn, topic submit form)

Acceptance:
false/unsupported critical claim blocks script/publication path. ✅

## PHASE 5 — Media Production
- [x] Creative Director (automated storyboard director enforcing style, visual flow, 9:16 vertical ratio)
- [x] storyboard (Storyboard & StoryboardScene models with Content Gate verification)
- [x] Character Bible (7 core studio employees seeded with immutable palettes and roles)
- [x] image adapter (DeterministicVisualAdapter generating valid 1080x1920 SVG visual cards)
- [x] video adapter (Deterministic media synthesizer with resolution/aspect ratio validation)
- [x] TTS adapter (DeterministicTTSAdapter producing RIFF/WAVE audio with duration & word alignment)
- [x] asset provenance/rights (MediaAsset with SHA-256 provenance digest, license status, audit events)
- [x] FFmpeg editor (local FFmpeg / deterministic video assembly pipeline producing vertical 9:16 MP4)
- [x] captions — real since 2026-09-17: cues timed from the narration actually recorded, an SRT
  beside every film, burnt in above the bottom fifth by default (`captions_burn_in`) and held
  by `captions_qc`; before that the SRT was written and never used.
- [x] QC (Technical, Factual, and Rights verification checklist; since 2026-09-17 also audio
  loudness, captions and the fallback-scene ceiling)
- [ ] character drift QC — `NOT_IMPLEMENTED`: quality control reports the check as not
  performed and certifies nothing (ticked in error until 2026-09-18).
- [x] final MP4 page (Media Production UI modal with 9:16 vertical video player, QC scorecard, Character Bible)

Acceptance:
verified content → valid 9:16 MP4 with provenance. ✅

## PHASE 6 — YouTube Main Channel
- [x] channel setup wizard (ChannelRecord model, default Channel A & Channel B seeding)
- [x] brand assets workflow (ChannelBrandAsset model, tagline, avatar, banner associations)
- [x] Google OAuth — **real, 2026-09-11**: Authorization Code flow with offline access, vault-held
  refresh tokens, single-use state, channel identity read from the API. Owner-managed connections,
  several at once. See `YOUTUBE_CONNECTIONS.md`. The upload half is proven: two private uploads
  with real remote ids reached Main Channel A on 2026-09-12.
- [x] official YouTube integration (YouTube Data API v3 resumable upload protocol)
- [x] private upload — private by default; since 2026-09-17 the visibility is the channel's
  Owner-set publish policy (migration 0037), resolved once and stamped with its version, and a
  sixth gate holds a publication that would be seen to it.
- [x] remote ID verification (stores remote_video_id and full shorts URL upon confirmation)
- [x] idempotency (unique constraint on channel_id + idempotency_key prevents duplicate uploads)
- [x] scheduled release — real since 2026-09-17: a public policy with `publish_delay_minutes`
  uploads private with `status.publishAt`; before that the time was stored on the intent and
  never sent. Exercised against a faked transport only.
- [x] publication history (PublicationRecord tracking with REST endpoint & UI history table)
- [x] policy gate (5-point Content Gate: Autonomy Stop, File On Disk, QC PASSED, Factual 100%, Duplicate Protection)

Acceptance:
private test upload proven without duplicates. ✅

> **2026-09-11 — the runbook now runs the pipeline.** Eight of the twelve daily stages have real
> implementations behind them (`backend/app/runbook/stages.py`), so a day's run performs the work
> of Phases 4 to 7 rather than recording it as unconnected. `idea_generation` and `post_run` have
> no implementation and are still reported SKIPPED with that reason. The acceptance criteria of
> the phases below are unchanged: what is wired is what exists, and the stages report honestly
> where a provider or an approval is missing. Correction 2026-09-18: `build_stage_runners`
> supplies ten of the twelve stages (idea generation and post-run gained their work later on
> 2026-09-11); preflight and the daily log are the run's own. Since 2026-09-17 the serial queue
> runs before media, so the same run films the episode.

## PHASE 7 — Analytics / Growth
- [ ] analytics ingestion
- [ ] snapshots
- [ ] Growth Agent
- [ ] cohort metrics
- [ ] minimum sample thresholds
- [ ] experiments
- [ ] strategy versioning
- [ ] Director recommendations

Acceptance:
real metrics only; recommendations expose sample size/evidence.

## PHASE 8 — Workforce Autonomy
- [ ] performance scorecards
- [ ] recruitment
- [ ] benchmark suites
- [ ] hiring
- [ ] firing
- [ ] safe in-flight task reassignment
- [ ] suspension
- [ ] dynamic roles
- [ ] model/provider switching
- [ ] Director own-config restrictions
- [ ] visual hire/fire

Acceptance:
real end-to-end employee replacement and audit.

## PHASE 9 — Office Serial / Channel B
- [x] Daily Studio Log — closed by every run that did work; since 2026-09-17 yesterday's is
  closed with all of its events at the start of the run, and a closed log never changes.
- [x] ContinuityState — `continuity_state` (migration 0036): episode number, open threads,
  recurring elements, last three summaries; advances only on approval, once per episode.
- [x] live vs dramatized message separation — `narrative_projection_json` on the closed log:
  event types classified PUBLIC_SAFE or OWNER_PRIVATE by a table, private by default,
  descriptions redacted; the showrunner never reads the operational log.
- [x] Showrunner — `write_episode` grounded on the projection, with the canon in the prompt.
- [x] source-event linking — every beat cites committed events of the closed log; a private
  or invented citation fails the episode.
- [~] persistent character visuals/voices — bible lines in every scene prompt; a locked
  character's voice is bound where the Owner has bound one, else the narrator; one voice per
  scene.
- [x] serial storyboard — `storyboard_from_episode`, in the factual storyboard's exact shape.
- [~] serial QC — the Director's five computed checks and her verdict on the episode, then the
  same film QC and her serial brief (2026-09-18); no serial-specific picture check.
- [x] second channel config — the OFFICE_SERIAL slot carries a publish policy and the
  Director's leave (migrations 0037, 0038); binding an account is the Owner's.
- [~] second channel publishing — routed by the storyboard to OFFICE_SERIAL at its policy,
  tested with faked providers; no real day with Channel B bound has run.

Acceptance:
yesterday's real events → today's coherent episode with correct cast. (Code complete
2026-09-18 with every provider faked; unproven on a real day, by the Owner's rule.)

## PHASE 10 — Full Automation Hardening
- [x] daily main workflow — the background worker fires the scheduled `DAILY_RUN` and executes
  the runbook with real stage work (2026-09-11). Seeded dormant; the Owner starts the clock.
- [x] end-of-day log — closed by every run that did work (Phase 9/10).
- [x] next-day serial workflow — the `serial_queue` stage writes, reviews and storyboards the
  previous closed day's episode, and since 2026-09-17 the same run films it (the stage runs
  before media). Open: today's log is still closed at the run's hour.
- [ ] Manual/Supervised/Autonomous — today: STOP flag plus a dormant-by-default schedule.
- [ ] approval queue — the Director approves the scripts she passes (2026-09-12) and, under the
  Owner's per-channel leave, the episodes (2026-09-18); an episode without that leave waits
  DRAFT for the Owner, and there is no queue view.
- [x] cost reservation — since 2026-09-18 the media stage prices the plan (`estimate_film_cost_micros`) and *holds* the sum behind the write lock (`reserve_spend`, migration 0039), settles it against the real cost rows and releases it on every path where the film was not made; the watchdog frees a hold older than six hours.
- [x] hard budgets — a refusal now stops the film and the Accountant writes to the Owner the same day, and a business date has a token ceiling (`STUDIO_AGENT_DAILY_TOKEN_BUDGET`, 0 = none) enforced as the Policy Kernel's first gate (BLOCKED_BUDGET). Budgets are still set only by the Owner, and none is set on the live studio yet.
- [x] STOP AUTONOMY — the scheduler and the task queue both refuse while the stop is set, and
  since 2026-09-17 a day already running stops between stages (PARTIAL or BLOCKED, no safe mode).
- [x] stuck-job watchdog — the scheduled `watchdog` job (2026-09-17): renders stuck past three
  hours failed, unknown and retryable publications reconciled within a bound and then handed
  to the Owner, lapsed leases reported (`claim_task` reclaims them itself).
- [~] restart recovery — the service restarts the process, the clock re-attempts a day that
  could not run, the watchdog repairs what a crash left (2026-09-17); employees other than the
  VideoEditor left WORKING by a crash are not reset; the render polls the stop between scenes
  since 2026-09-17 and the media stage reads it before each film since 2026-09-18, the other
  long runners still do not.
- [~] cloud/always-on deployment option — local always-on as a Windows Scheduled Task
  (`scripts/install_studio_service.ps1`, 2026-09-17); the cloud option stays open.
- [ ] backup/restore
- [ ] chaos/failure testing

Acceptance:
full simulated unattended cycle survives failures/restart without duplicate side effects.

## PHASE 11 — Public/Fan Hooks
- [ ] public sanitized projection
- [ ] Fan/Vote/Pitch schemas
- [ ] paid-pitch RevenueSource interface
- [ ] fan-vote command pipeline
- [ ] no premature real-world commerce/spending build

The core VR$ Economy / VendorShop implementation is specified separately in PHASES 11–14 of the V5 economy roadmap section below; phase numbers should be normalized by the implementation lead into a single sequential project plan before coding.

## Always
- [x] YouTube profile images: high → medium → default selection, per-connection persistence,
  Verify/completed-Reconnect refresh, narrow CDN CSP and missing-thumbnail avatar (2026-09-11).
  Both existing connections loaded real 800×800 images in Chromium; see `YOUTUBE_CONNECTIONS.md`.
- [ ] Update CURRENT_STATUS.md
- [ ] Update CHANGELOG.md
- [ ] Update 16_DECISION_LOG.md for architecture decisions
- [ ] Run tests
- [ ] Separate mock tests from real-provider tests

## v3 cross-cutting additions

### PHASE 0 additions
- [x] CI baseline
- [x] dependency lockfiles
- [x] secret scanning
- [x] basic threat model
- [x] feature flag framework
- [x] UTC/timezone policy

### PHASE 1 additions
- [x] Owner Policy Kernel
- [x] hard-gate interface (policy kernel enforces stop/lifecycle/capability/health before run)
- [x] PromptTemplate/ContextManifest (prompt_template_version field in AgentRun)
- [x] AgentRun/ToolReceipt (full envelope + immutable receipts)
- [ ] agent concurrency limits (max_concurrent_tasks field exists; enforcement requires Phase 2 queue)
- [ ] loop/rework limits (Phase 2+)

### PHASE 2 additions
- [x] admission control/backpressure (task queue priority + worker capacity)
- [x] Manual Repair Queue (DEAD_LETTER queue + operator retry)
- [ ] compensation/reconciliation contracts
- [ ] daily preflight framework
- [x] event schema/upcasting/version tests (schema_version on all events and models)

### PHASE 3 additions
- [ ] LIVE/REPLAY/DEMO visual modes
- [ ] developer provenance overlay
- [ ] animation compression for high event rate
- [ ] public-safe projection boundary stub

### PHASE 4 additions
- [ ] source quality/freshness scoring
- [ ] content semantic duplicate check
- [ ] prompt/context retrieval tests
- [ ] factual visual-plan validation hook

### PHASE 5 additions
- [ ] deterministic fallback video format
- [ ] caption safe-zone/loudness validation
- [ ] per-scene regeneration budget
- [ ] final render checksum

### PHASE 6 additions
- [ ] channel isolation
- [ ] quota/preflight checks
- [ ] remote-state reconciliation for externally changed videos
- [ ] estimated/pending/settled revenue vs spendable VR$ separation

### PHASE 7 additions
- [ ] multi-objective Director scorecard
- [ ] model drift revalidation
- [ ] novelty/diversity metrics
- [ ] analytics lag handling

### PHASE 8 additions
- [ ] probation/shadow mode for new employees
- [ ] agent capacity planning
- [ ] delegation/manager extensibility
- [ ] public alias vs technical identity

### PHASE 9 additions
- [ ] NarrativeProjection sanitizer
- [ ] public-safe event classification
- [ ] canon correction/versioning
- [ ] provider-brand/public-name policy

### PHASE 10 additions
- [ ] SLO dashboard
- [ ] incident notification
- [ ] reliability burn-in
- [ ] release/rollback runbook
- [ ] RPO/RTO targets

### PHASE 11 additions
- [ ] WorldBuilder schema
- [ ] public moderation schemas
- [ ] External Evidence vs VR Ledger vs Forecast separation
- [ ] fan-vote command pipeline

## Release gates

Do not advance to public autonomous publishing until:
- Phase 0–6 required acceptance passes;
- no unresolved P0;
- reliability burn-in meets configured threshold;
- real provider tests documented;
- current platform policy review completed;
- backup/restore test passed.


# V4 Organizational Expansion Phases

## PHASE 11 — Dynamic Organization Foundation
- [ ] Department entity/lifecycle
- [ ] DepartmentCharter
- [ ] ManagerDelegation
- [ ] Create/Merge/Dissolve department commands
- [ ] OrgNeedAssessment
- [ ] OrgComplexity metrics
- [ ] UI department projection

Acceptance:
CEO can create a trial department with bounded manager permissions; UI reflects committed state.

## PHASE 12 — Marketing & Communications
- [ ] CMO role
- [ ] MarketingOpportunity
- [ ] Campaign model
- [ ] truthful teaser workflow
- [ ] YouTube/TikTok/Instagram/Facebook/Telegram adapter interfaces
- [ ] Telegram first practical community adapter if appropriate
- [ ] social publishing idempotency
- [ ] marketing metrics/attribution
- [ ] campaign experiments

Acceptance:
a real studio event can produce an approved teaser draft linked to tomorrow's episode, with no fabricated facts.

## PHASE 13 — Market Intelligence
- [ ] MarketSignal
- [ ] CompetitorObservation
- [ ] OpportunityHypothesis
- [ ] public-source constraints
- [ ] CEO experiment handoff

## PHASE 14 — People/HR & Persona
- [ ] HR optional department
- [ ] NarrativePersona
- [ ] fictional birthday
- [ ] relationship graph
- [ ] onboarding/probation workflows
- [ ] culture/events coordinator

## PHASE 15 — Finance / Legal
- [ ] FinOps/CFO role
- [ ] financial truth-layer separation
- [ ] unit economics
- [ ] Legal/Compliance department hooks
- [ ] compliance hold workflow
- [ ] sponsor/advertising readiness

## PHASE 16 — Company Event Engine
- [ ] Company Calendar
- [ ] MilestoneTrigger
- [ ] Team-building event
- [ ] production pause policy
- [ ] event canon
- [ ] serial event-day workflow

These phases are after core studio/channel reliability unless an earlier implementation dependency justifies moving a small foundational part forward.


# V5 Roadmap — Economy / Treasury / Procurement

## PHASE 11 — Financial Evidence + VR Ledger
- [ ] RevenueSource adapters/interfaces — no automatic importer yet; evidence is Owner-entered.
- [x] RevenueEvidence model
- [x] OwnerFundingEvent
- [x] FXSnapshot
- [x] immutable double-entry ledger
- [x] Treasury projection
- [x] mint/burn/reversal idempotency
- [x] actual provider-cost ingestion (reconciliation of estimate vs invoice variance: Phase 12)
- [x] financial audit trail

Acceptance:
- [x] verified $1 event can produce exactly 1 VR$ once;
- [x] forecast/pending values remain non-spendable;
- [x] reversal works.

Evidence: `PHASE11_ECONOMY.md`. 31 tests; end-to-end through the HTTP API against an isolated
studio. Nothing spends VR$ yet — that is Phase 13.

## PHASE 12 — Finance Dashboard / Forecast
- [ ] treasury dashboard
- [ ] budget system
- [ ] cost centers
- [ ] runway/burn
- [ ] 30/90/180 day scenarios
- [ ] P&L / Balance Sheet / Cash Flow management views
- [ ] public financial disclosure modes

## PHASE 13 — Procurement + VendorShop
- [ ] PurchaseNeed
- [ ] product specs
- [ ] online quote research adapters
- [ ] NEW/USED support
- [ ] quote TTL/revalidation
- [ ] Finance gate
- [ ] Legal/IP gate where needed
- [ ] VendorShopOrder
- [ ] inventory/fixed asset
- [ ] Asset Architect
- [ ] delivery/world placement

Acceptance:
- CEO asks for a chair → real price evidence → finance approval → VR$ purchase → office asset appears, with zero real checkout.

## PHASE 14 — Treasury Financing
- [ ] financing requests
- [ ] current-market term research
- [ ] debt capacity rules
- [ ] Legal review
- [ ] Owner/governance thresholds
- [ ] Owner capital contribution
- [ ] Owner loan
- [ ] virtual external financing model
- [ ] interest/amortization
- [ ] treasury stress/freeze states

Acceptance:
- financing is realistic, auditable, and cannot create unlimited free VR$.

Implementation sequencing note:
The economy data contracts and command boundaries should be designed early, but full UI/advanced finance can be implemented after the core content pipelines are stable.

## Phase 4 incremental evidence — Codex, 2026-09-09

- [x] Owner-selected public HTTPS URL retrieval with allowlist, DNS pinning, bounded extraction and source hashes; verified against a real IANA source.
- [x] Import retrieved text through the existing authenticated source endpoint; sanitized persistence verified in an isolated database.
- [~] Keyword search/discovery adapter and independent claim-verifier authorization — the discovery half landed 2026-09-18: each authorised site's own search address is discovered as well as typed, and a web search API the Owner connects (catalog kind `search`) may name addresses, which are filtered against the allowlist and read by the studio's own retriever. No engine is connected on the live studio. The Fact Checker has verified claims against the fetched text since 2026-09-12 and cannot verify a claim it made.
- [ ] Worker/UI integration after coordination with the active UI developer.

This increment does not close Phase 4 acceptance. See `RESEARCH_HANDOFF.md`.

## Office visual refinement — 2026-09-10

- [x] Premium pixel material and sprite detailing on the existing office scene.
- [x] Camera dock clear of the building; portrait fit regression fixed.
- [x] Desktop/fullscreen/mobile browser review and agent selection verification.

Evidence: `PIXEL_OFFICE_REFINEMENT.md`. This does not close unrelated Phase 3 functionality or later world-builder procurement requirements.

## Pixel office v2 — 2026-09-10
- [x] Figma design system: Office Palette variables, quality-bar floor (Research, 4x), character and HUD components, building/layout spec.
- [x] Frontend implementation of the same system across all nine departments: palette ramps, outlined compiled sprites with role costumes, room shells with baked light, workstation occlusion, limestone facade, glass lift, dark scene chrome.
- [x] 60 FPS measured (~6 ms/frame); 43 frontend tests; live click-to-inspect verified; no backend/API/event changes.
- [ ] Optional follow-ups: walking sprites for agents leaving their desks, daytime interior palette pass, street crowd rig on the new sprite compiler.

Evidence: `PIXEL_OFFICE_V2.md`.

## Agency identity — AMN-AI — 2026-09-10
- [x] Name introduced across interface, backend, packaging, launcher scripts and documentation.
- [x] Logo asset set derived from the source artwork (mark, lockup, favicon/ico/apple-touch, og master).
- [x] Explicit audited rename of the existing studio row (`scripts/rename_studio.py`, `studio.renamed`).
- [x] Brand rules documented; tests assert the referenced assets and the rename's audit trail.

Evidence: `BRAND_AMN_AI.md`.

## Ambient street increment — 2026-09-10

- [x] Round tires and correct traffic drawing depth.
- [x] RNG vehicle replacement and varied street actors/animals.
- [x] Device-local day/night schedule with lower night density.
- [x] Ambient dialogue separated from real agent speech; simulation and browser tests.

Evidence and deliberate limits: `STREET_LIFE.md`.

- [x] Weekly street rhythms: weighted activities/vehicles, midnight weekend continuity, coordinated groups and ordinary-passersby capacity. Verified by 33 frontend tests and five fixed-clock browser scenarios; see `STREET_LIFE.md`.

- [x] Exterior 24-hour Bucharest clock and timezone-aligned street rhythms; summer/winter transition tests passed.

- [x] Place Bucharest LED clock on its own right-side street support; verify bottom toolbar CSS loads under the actual CSP.

- [x] Inspector model assignment consistent with Settings, including older layout response compatibility, network failures and late responses. Evidence: `INSPECTOR_MODEL_FIX.md`.

## Conversation read by a person — 2026-09-11

- [x] Structured model answers (pages, claims, topics, scenes, verdicts) render as sentences and lists; raw JSON only collapsed; truncated lists salvaged with a note.
- [x] The Agent Inspector chat reads as an exchange (question right, answer left), with a live "scrie…" indicator and self-refreshing history; the exchange is saved on the run.
- [x] «Fereastră live ↗» in the inspector opens a standalone real-time window per employee (state, "Acum" line, event chain), fed from the ledger's own stream; the detail view is unchanged.
- [x] Dialogs confirmed wide in the served build (1180px measured); stale dist rebuilt.

Evidence: `scratch/verify_conversation_live.mjs` 14/14 in Chromium; 79/79 frontend tests. No backend changes.

## Pipeline answers for the Owner; expandable inspector — 2026-09-11

- [x] Investigated the duplicate "Sarah said" lines: two real owner_chat runs from the verification pass, no duplication bug.
- [x] Investigated `performance_intake` skip: the run predated the slot↔account binding by two minutes; live re-resolution confirms the next run proceeds.
- [x] Confirmed agents have no tool access (single-prompt runs); STATUS reports are filed by deterministic stage code.
- [x] Confirmed the per-channel production criteria (FLEXIBLE variants vs CONSISTENCY_LOCKED identity) are implemented end to end; open items are configuration: bind+lock character voices, route storyboards to channels (`channel_id`), pick organization defaults.
- [x] «⛶ Extende» button on the Agent Inspector: fullscreen reading of the whole chat and history, restore included. Verified 16/16 in Chromium.

## The Owner's roles: sound, video, weekly Director review — 2026-09-11

- [x] Contracts v2: sound artist and video editor steward their technology within policy and follow the Director's written indications; the Director decides from analytics and verifies weekly. Migration 0025 re-seeds only never-Owner-edited roles.
- [x] Open messages addressed to an agent enter its composed identity (identity v2) — the channel for the Director's indications.
- [x] Weekly performance review: scheduled every 7 days (active) + Owner button + POST /runbook/weekly-review; digest from recorded metrics; Director's answer filed as HANDOFF to sound and video + STATUS to her inbox; nothing published → honest skip at zero tokens.
- [ ] Owner configuration still open: bind + lock character voices (Channel B), route storyboards to channels (`channel_id`), pick organization default model/voice, connect real publications so the weekly review has numbers.

Evidence: `scratch/verify_weekly_review_ui.mjs` 5/5 live; backend 526/1; frontend 79/79.

## The Director's mandate — grow views and retention — 2026-09-11

- [x] Mission updated (migration 0026): audience growth is her primary charge.
- [x] Contract v3: instruct any employee in writing, steer channels/topics from measured performance, request budget from the Accountant with justification; Accountant answers budget requests from the books and escalates (Owner alone decides budgets).
- [x] Weekly review v2: structured answer routed to all departments + Accountant + Owner escalation; STRATEGY memory for direction; spoken summary in the office; schema violations file nothing.
- [ ] Until real publications and per-channel production exist, the mandate has no numbers to act on — the machinery waits for Phase 5/6 configuration.

## Office logic: correspondence and the day that stopped — 2026-09-12

- [x] `ConfiguredLLM` (the studio's real adapter) asks Ollama for thinking off, reports `done_reason`, and waits ten minutes; a run with no text is `EMPTY_OUTPUT` with the reason.
- [x] Runs are records while they run (`RUNNING` → final; `ABANDONED` after 45 min); a stale THINKING flag is cleared, not obeyed.
- [x] Token budgets ×3; the day runs `auto_configure` before preflight when media readiness says `NO_DEFAULT`.
- [x] Letters: thread, reply, forward, text (migration 0027); open letters enter the employee's prompt with their thread.
- [x] Employees answer their mail each worker pass; the Director reads what came back at once; a question closes, a HANDOFF stays open until done, a long thread waits for the evening or the Owner.
- [x] Letters to the Owner (decision hers / day stopped / review refused): red in the ledger, `GET /agents/messages/owner`, answered from the thread window.
- [x] Thread window on the page; the inspector's inbox opens threads.
- [x] Employees choosing a video/image/voice model by reading the vendors' pages (fetched by the studio, vendor hosts only): scores and prices recorded on the resources, `rank_candidates` reads them, fallback defaults follow, locked ones are reported on; weekly job + Owner button.
- [x] Analytics-driven adaptation wired: Google Trends (daily, `trend_snapshot`) and the studio's measured cohorts reach the Researcher's proposals and the weekly digest; the numbers themselves still wait for real publications.
- [x] Visual polish pass on the whole page, from a screenshot of every view: one text scale, actions sized to their words, the scene chrome as one bar in two groups, the ledger breathing, Settings on the dialog pattern, the inspector's contract as lists.

Evidence: `tests/test_mail.py` 18/18; backend 544/1; frontend 86/86; live on a copy of the Owner's data (`scratch` review scripts).

## The clock and durability (Phase A of running unattended) — 2026-09-17

- [x] Fault classes: a stage's TRANSIENT fault is retried in place (3 retries, 20/40/80 s) and fails the run without safe mode; a HARD fault still opens safe mode. `daily_run.fault_class`, migration 0035.
- [x] Same-day re-attempts: a BLOCKED preflight or a TRANSIENT day is tried again after 30 minutes, three attempts per business date; a date that did work is never rerun by the clock.
- [x] The daily job on the wall clock: `run_at_local` and `timezone` on the row, DST-safe, `STUDIO_DAILY_RUN_HOUR_LOCAL` 05:00; still seeded dormant, the Owner starts it.
- [x] STOP AUTONOMY cancels a running day between stages: PARTIAL or BLOCKED, no safe mode, no letter.
- [x] Provider retries: one bounded, jittered policy (`providers/retry.py`) for every adapter; a billed request that got no answer is not sent again.
- [x] Watchdog job: stuck renders failed, publications reconciled within `reconcile_max_attempts`, then NEEDS_RECONCILIATION for the Owner.
- [x] The studio as a Windows Scheduled Task (`scripts/install_studio_service.ps1` / `uninstall_studio_service.ps1`); README "Running as a service".
- [x] Settings: `STUDIO_DAILY_RUN_HOUR_LOCAL`, `STUDIO_DAILY_MAX_ATTEMPTS`, `STUDIO_DAILY_RETRY_SECONDS`, `STUDIO_STAGE_RETRY_ATTEMPTS`, `STUDIO_STAGE_RETRY_BACKOFF_SECONDS`, `STUDIO_WATCHDOG_INTERVAL_SECONDS`, `STUDIO_PROVIDER_RETRY_ATTEMPTS`, `STUDIO_PROVIDER_RETRY_MAX_SECONDS`, `STUDIO_RENDER_STUCK_AFTER_SECONDS`, `STUDIO_RECONCILE_MAX_ATTEMPTS`.
- [ ] `ScheduledJobView` exposes `run_at_local` and `timezone`, so the scheduler API and the page can show the hour.
- [ ] The long runners in `backend/app/runbook/stages.py` poll `stop_requested(engine)` between scenes and raise `TransientStageError` where only they can tell a fault is transient.
- [ ] `execute_publication` admits REMOTE_UNKNOWN without a remote id to its reconcile-by-key branch, so the watchdog resolves those rows instead of handing them over.
- [ ] Employees other than the VideoEditor left WORKING by a crash are reset (the "stuck agent runtime" item of `../architecture/18_AUTOMATION_ORCHESTRATION.md`).
- [ ] An autouse fixture in `tests/conftest.py` patching `app.providers.retry.sleep`, so the remote-state honesty test is instant again.
- [ ] An end-to-end watchdog fire with the real module through the worker (the dispatch was tested with an injected stub).
- [ ] The Owner's part: run the migration (`scripts/bootstrap.py`), install the task, confirm once in `data/studio-service.log` that an S4U logon opens the credential key, and start the clock — his recorded act.

Evidence: 66 (runbook, scheduler/worker, schema match), 28 (provider retry), 46 + 24 (media, Ollama, integration settings), 34 (existing adapter tests), 11 (watchdog) passed on the changed files; ruff, format, mypy and `check_docs.py` clean. The whole suite is the verifier's.


## HQ visual continuation — 2026-09-18

- [x] Diagnose/fix skeletal garment material fallback in isolated assets, reload,
  backup and apply to HQ; preserve live integration.
- [x] Capture a fresh native scene and compare L2 with the exact target image.
- [ ] Capture the actual browser stream at documented quality settings.
- [ ] Finish L2 on a copied level before extending the artistic pass to other floors.
- [ ] Measure game and browser performance after the visual pass.

Detailed acceptance and evidence: [VISUAL_AUDIT_2026-09-18.md](VISUAL_AUDIT_2026-09-18.md).


## Money and sources (Phases E/F of running unattended) — 2026-09-18

- [x] Cost reservation: `reserve_spend` holds a film's estimated cost behind the write lock,
  `settle_reservation` after the real cost rows, `release_reservation` on every path where the film
  was not made; the watchdog frees holds older than `STUDIO_RESERVATION_TTL_SECONDS` (6 h).
  Migration 0039 (`provider_price`, `spend_reservation`, `provider_cost_record.failed`).
- [x] Hard budgets: a budget refusal now stops the film and writes to the Owner the same day
  (`budget_refusal_letter`), and a day's tokens have a ceiling
  (`STUDIO_AGENT_DAILY_TOKEN_BUDGET`, 0 = none) enforced as the Policy Kernel's first gate with
  the verdict BLOCKED_BUDGET. Budgets are still set only by the Owner; the Accountant escalates.
- [x] Budget periods on the studio's own calendar (the `studio` row's zone), so the books count the
  business date the daily log closes.
- [x] Prices are the Owner's: `PUT/GET /economy/prices`, versioned, idempotent, provenance
  OWNER | DOCUMENTED | QUOTED | BILLED; one DOCUMENTED seed (ElevenLabs' public figure) and
  nothing guessed for Ollama Cloud.
- [x] Adapters cost their own calls from what they measured (`price_lookup` on ElevenLabs, Ollama
  and `ConfiguredLLM`), answering None and never zero without a full price.
- [x] A render the vendor refused is costed (`record_failed_render_cost`, ESTIMATED + `failed`,
  idempotent per scene).
- [x] Site search discovered, not only typed: a host test and the weekly retest read the front page
  and the OpenSearch description; the Owner's address keeps winning. Migration 0040
  (`discovered_search_template`, `discovered_at`, `last_test_reason`).
- [x] A web search engine the Owner connects (catalog kind `search`) may name addresses and nothing
  else: `find_pages` filters every result against the allowlist and reads each page with the
  studio's own retriever; the allowlist cannot be widened by an agent, a request or a result.
- [x] Host failures carry a reason code (HTTP_403, HTTP_ERROR, RATE_LIMITED, SCRIPT_ONLY, NETWORK,
  OTHER) and the preflight asks `research_health` — whether the studio can find pages — instead of
  whether a row exists.
- [x] The day's reading is the Owner's: `STUDIO_RESEARCH_CANDIDATES_PER_DAY` and
  `STUDIO_RESEARCH_PAGES_PER_TOPIC` (4 and 4, clamped 1..12).
- [x] One test of a whole day: `tests/test_autonomous_day_end_to_end.py` — the scheduled job, the
  real runbook, two films encoded and published private to their own channels, the serial filmed,
  a second tick that starts nothing; only the vendors are faked.
- [x] Price lookups reach the adapters that are actually built (`main.py`,
  `integrations/services.py`, `integrations/router.py`, `media/factory.py`), so an agent run stops
  recording `cost_vr` NULL and narration is priced in the books. Closed 2026-09-18; a whole-tree
  scan (`tests/test_phase_ef_closure_adversary.py`) holds every construction of a priced adapter,
  and names `economy/credits.py` and `integrations/discovery.py` as the two that generate nothing.
- [x] `seed_documented_prices` is called from `scripts/bootstrap.py` or the start-up seeds. Closed
  2026-09-18: in `scripts/bootstrap.py` beside `seed_chart_of_accounts`; `main.py` has no start-up
  seeds, and a price written on every server start would be a write the Owner did not ask for.
- [x] `assembler._fail_job` writes the scenes it had already built into `production_json`, so the
  failed-render cost has something to charge. Closed 2026-09-18 (committed at 441e431): the scene
  loop is wrapped, and the media stage now charges the attempt on the Owner's stop as well as on a
  vendor's refusal — a shot bought in the minute before STOP was bought all the same.
- [ ] The Accountant reconciles ESTIMATED rows against a vendor's invoice (a BILLED row replacing
  the estimates of one render).
- [x] Routes for `research_health` and a forced retest, and the *Cercetare → Surse* screen showing
  the discovered address, its origin and the failure reason. Closed 2026-09-18:
  `GET /factual/research/health` and `POST /factual/research/allowed-hosts/retest`, both behind the
  factual router's `require_owner`.
- [x] The frontend labels BLOCKED_BUDGET, and the Books office shows `reserved_usd`,
  `failed_render_usd` and `unpriced_agent_runs`. Closed 2026-09-18 in source only:
  `npm run build --prefix frontend` has not been run, so the served bundle is still the old one.
- [ ] The script-only heuristic and the OpenSearch discovery measured against live hosts — the
  first weekly retest on the live database (tests may not open a socket).
- [ ] The Owner's part: run the migration (`scripts/bootstrap.py`) to `0040_research_sources`, set
  the budgets, type the plan's prices, connect a search engine or add hosts, set the publish policy
  per channel, and start the clock. Nothing above spends money on its own.

Evidence: 70 (economy files), 87 (research files), 2 + 21 + 30 + 44 + 38 (the wiring's files)
passed; the whole suite on the integrated tree 1028 passed / 1 skipped, 1029 collected; ruff,
format, mypy and `check_docs.py` clean. Nothing ran against a real model, provider or platform.
After the closure and its verification (2026-09-18): the whole suite 1067 passed / 1 skipped, ruff,
format, mypy and `check_docs.py` clean, no socket left the machine and nothing was rendered,
uploaded or paid for.
