# Software Requirements Specification v3

## Functional Requirements

### Ownership / governance

**FR-001 — Owner authority**  
The system must have a human Owner role above all AI agents.

**FR-002 — Autonomy modes**  
Support Manual, Supervised/Managed and Autonomous CEO modes.

**FR-003 — Stop autonomy**  
A persisted backend kill switch must block new autonomous side effects and request cancellation of active cancellable workflows.

### Director / workforce

**FR-004 — Director/CEO**  
Director manages strategy, staffing, routing, providers, budgets, experiments and production within explicit policy.

**FR-005 — Director capability-bound actions**  
Director may only execute actions through explicit tools/capabilities/permissions.

**FR-006 — Director self-governance restriction**  
Director may not remove Owner controls or silently escalate its own permissions.

**FR-007 — Dynamic agents**  
Agents, roles, skills, rooms and desks must be data-driven.

**FR-008 — Hiring**  
Director may propose/execute hiring according to authority mode.

**FR-009 — Firing**  
Director may terminate an employee without deleting history; active tasks must be safely resolved.

**FR-010 — New roles**  
Director may propose or create new roles with an explicit justification.

**FR-011 — Recruitment benchmark**  
Candidate agents must be comparable using identical benchmark sets.

**FR-012 — Per-agent config**  
Each agent supports provider/model/fallback/tools/permissions/budget/prompt/memory policy.

**FR-013 — Capability matrix**  
Each model/provider configuration must expose known/unknown capabilities used for assignment eligibility.

### Providers

**FR-014 — Provider registry**  
Register LLM, image, video, TTS, research/search, browser and publishing providers.

**FR-015 — Honest provider state**  
Unknown capability or health must remain unknown; never infer online/compatible without evidence.

**FR-016 — Connection test**  
Providers must support a real test path where possible.

**FR-017 — Credential boundary**  
Credentials remain backend-only and are never generated/fabricated by agents.

### Automation

**FR-018 — Durable workflow**  
Production workflows must persist across process restarts.

**FR-019 — Persisted scheduler**  
Schedules must persist and be timezone-aware.

**FR-020 — Idempotency**  
External writes, especially publishing, must have idempotency protection.

**FR-021 — Retry/backoff**  
Transient failures use bounded retry/backoff rules.

**FR-022 — Circuit breakers**  
Repeated provider failures must stop wasteful retry loops.

**FR-023 — Stuck-job detection**  
Watchdog must identify abandoned/overdue work.

**FR-024 — Cancellation**  
Workflows/tasks must support safe cancellation where technically possible.

**FR-025 — Duplicate-scheduler protection**  
Multiple scheduler/worker processes must not duplicate the same production run.

### UI / event truth

**FR-026 — 2D office**  
Home interface is top-down interactive office.

**FR-027 — Backend-driven visuals**  
Every live operational animation must be caused by committed backend state/event.

**FR-028 — UI success verification**  
UI may not show success until backend verifies effect.

**FR-029 — Reconnect/replay**  
Frontend must rebuild state from snapshot + missed events after disconnect.

**FR-030 — Out-of-order safety**  
Frontend must tolerate duplicate/out-of-order events without corrupting displayed state.

**FR-031 — Agent Inspector**  
Clicking employee displays real state/config/history/performance.

**FR-032 — Provider Room**  
Provider status must reflect backend health/capability state.

### Research / facts

**FR-033 — Source storage**  
Research must store source metadata and provenance.

**FR-034 — Claim model**  
Important factual claims map to evidence.

**FR-035 — Claim status**  
Support SUPPORTED, UNCERTAIN, CONTRADICTED, STALE and UNVERIFIED.

**FR-036 — Critical claim gate**  
Critical non-supported claim blocks publishing.

**FR-037 — Untrusted web content**  
External web data must not be allowed to override system instructions or exfiltrate secrets.

**FR-038 — Independent verification**  
Fact-check path should be independent of initial research path where practical.

### Main content production

**FR-039 — Main pipeline**  
Idea → research → verification → script → hook → storyboard → media → voice → edit → QC → publish → analytics.

**FR-040 — Video adapter**  
Video generation is provider-agnostic.

**FR-041 — Image adapter**  
Image generation is provider-agnostic.

**FR-042 — TTS adapter**  
Voice generation is provider-agnostic.

**FR-043 — Deterministic edit**  
Final editing supports FFmpeg/equivalent.

**FR-044 — Media provenance**  
Generated/downloaded media stores provider/source/rights metadata.

**FR-045 — Character consistency QC**  
Office serial visuals must be checked for identity drift.

### YouTube / analytics

**FR-046 — Official YouTube integration**  
Use official OAuth/API where available.

**FR-047 — Upload verification**  
Publication success requires confirmed remote video ID.

**FR-048 — Separate channels**  
Channel A and Channel B have independent configuration/history.

**FR-049 — Real analytics only**  
Unavailable metrics display NOT AVAILABLE.

**FR-050 — Policy gate**  
Before public autonomous publishing, confirm current platform/policy requirements.

### Story / office serial

**FR-051 — Daily Studio Log**  
Persist immutable daily operational summary.

**FR-052 — Showrunner**  
Generate serial episode from prior-day real events.

**FR-053 — Continuity state**  
Track current roster, character identities, office state and story continuity.

**FR-054 — Dynamic cast**  
Terminated staff cannot appear as current staff.

**FR-055 — Live vs dramatized dialogue separation**  
Operational messages and fictionalized serial dialogue must be stored separately.

**FR-056 — Scene grounding**  
Meaningful serial scenes should reference source backend events.

### Costs / learning

**FR-057 — Cost records**  
Track cost per task/agent/provider/content item where possible.

**FR-058 — Budget reservation**  
Expensive operations should reserve budget before execution.

**FR-059 — Hard caps**  
Support per-task, agent, provider, daily and monthly limits.

**FR-060 — Experiment system**  
Growth changes must be measurable/versioned.

**FR-061 — Statistical caution**  
Director should not make large strategy changes from insufficient samples.

### Future-ready modules

**FR-062 — Public projection boundary**  
Architecture must support a sanitized fan-facing view.

**FR-063 — Future voting/pitches**  
Schema/extensions must not block future votes and paid pitches.

**FR-064 — VR$ economy extensibility**  
Schema/extensions must support the core VR$ treasury, VendorShop, inventory, market-priced office purchases and later fan-funded/economy extensions.

**FR-065 — Office world persistence**  
Room/furniture/layout changes must be backend state, not frontend-only decoration.

### Backup / operations

**FR-066 — Backup**  
Support database and critical asset backup.

**FR-067 — Restore test**  
Document and test restore procedure.

**FR-068 — Export**  
Support safe project/configuration export excluding secrets.

---

## Non-Functional Requirements

**NFR-001 — Windows-friendly local development**  
Must work reliably on Windows in local development mode.

**NFR-002 — Always-on deployment path**  
Architecture must permit a cloud/VPS/server deployment for true unattended operation.

**NFR-003 — Typed contracts**  
Use typed schemas for agents, tasks, events and provider adapters.

**NFR-004 — Transactional consistency**  
Important state transitions and external side effects must be transactionally guarded.

**NFR-005 — Observability**  
Structured logs, health, metrics and audit trail.

**NFR-006 — Security**  
Least privilege, secret isolation, input/URL validation, prompt-injection defense.

**NFR-007 — Maintainability**  
No giant monolithic files; clear module boundaries.

**NFR-008 — Multi-AI handoff**  
Documentation/current state sufficient for another coding AI to continue.

**NFR-009 — Visual performance**  
2D UI should remain responsive and offer reduced motion.

**NFR-010 — Causal traceability**  
Every live operational UI event references backend event/state.

**NFR-011 — Deterministic replay**  
Given a known event stream, office projection should reconstruct the same operational state.

**NFR-012 — Recoverability**  
Restart must not silently lose work or duplicate external writes.

## v3 Additional Functional Requirements

**FR-V3-037 — Policy Kernel**  
Hard Owner policy must be enforced outside Director prompts and cannot be bypassed by agents.

**FR-V3-038 — Independent hard gates**  
Factual, rights, policy, budget, credential and STOP AUTONOMY gates must fail independently of Director preference.

**FR-V3-039 — Decision summaries, not hidden reasoning**  
The system may store structured rationales but must not require raw chain-of-thought.

**FR-V3-040 — Agent capacity**  
Each agent/role must have configurable concurrency and workload limits.

**FR-V3-041 — Loop prevention**  
Workflows must have maximum agent-message hops, rework iterations and recursion limits.

**FR-V3-042 — Deadlock detection**  
The orchestrator must detect cyclic waits/repeated mutual rejection and escalate.

**FR-V3-043 — Daily preflight**  
Autonomous production must run preflight health, budget, auth, capability and incident checks.

**FR-V3-044 — Admission control**  
Scheduler must avoid starting work that exceeds worker/provider/budget capacity.

**FR-V3-045 — Manual Repair Queue**  
Unrecoverable or ambiguous external-side-effect states must be surfaced for explicit repair.

**FR-V3-046 — Prompt artifacts**  
Prompts/context policies must be versioned, testable and rollback-capable.

**FR-V3-047 — Memory lifecycle**  
Agent memory must support type, provenance, retention/TTL and deletion/invalidating rules.

**FR-V3-048 — Model drift detection**  
Provider/model suitability must be re-evaluated when behavior/version/capabilities materially change.

**FR-V3-049 — Fallback quality policy**  
A fallback can only be used if it satisfies role capability and minimum quality policy.

**FR-V3-050 — Multi-objective optimization**  
Director must optimize growth subject to accuracy, rights, reliability, brand, cost and Owner constraints.

**FR-V3-051 — Story sanitization**  
Public serial content may use only narrative-safe projections of operational events.

**FR-V3-052 — Public/internal identity separation**  
Agent technical provider identity and public character/display identity must be separable.

**FR-V3-053 — World Builder contract**  
Office expansion may only use supported room/item/asset schemas and committed backend world transactions.

**FR-V3-054 — Content novelty gate**  
System must detect excessive semantic/topic/script repetition before production/publishing.

**FR-V3-055 — Asset/content hash**  
Critical media/output assets should have checksums/content identifiers for provenance and duplicate detection.

**FR-V3-056 — API/schema versioning**  
Internal and external contracts must be versioned with compatibility policy.

**FR-V3-057 — Release safety**  
Production code changes must pass configured CI/test/release controls and may not be autonomously deployed by content agents.

**FR-V3-058 — Privacy classification**  
Stored/public-projected data must have explicit visibility/sensitivity classification.

**FR-V3-059 — Notification/escalation**  
P0/P1 incidents and Owner-required actions must have a persistent notification/escalation mechanism.

**FR-V3-060 — Sale/export readiness**  
System must support business configuration/data export without exposing or bundling secrets.

## v3 Additional Non-Functional Requirements

**NFR-013 — Backpressure**  
System remains stable when queues/providers are slower than incoming work.

**NFR-014 — Schema evolution**  
Stored events/APIs remain interpretable through version migrations or compatibility adapters.

**NFR-015 — Supply-chain security**  
Dependencies are pinned/reviewed and deployment artifacts are reproducible enough for rollback.

**NFR-016 — Time correctness**  
Persist UTC timestamps plus explicit business/channel timezone where scheduling semantics require it.

**NFR-017 — Idempotent projections**  
UI/read-model consumers must tolerate duplicate delivery.

**NFR-018 — Public privacy boundary**  
Future public mode must not share private/internal data by default.

**NFR-019 — Operational SLOs**  
Autonomous production readiness must be based on measured reliability targets.

**NFR-020 — Transferability**  
No required production logic may depend on one developer machine's personal path/account configuration.

**FR-V3-061 — Requirements traceability**  
Critical requirements must map to implementation, tests, roadmap and acceptance evidence.

**FR-V3-062 — Explicit state machines**  
Agent/content/workflow/publication/provider/gate states and allowed transitions must be explicit and testable.

**FR-V3-063 — Typed command catalog**  
Privileged state changes must occur through versioned typed backend commands.

**FR-V3-064 — UI/backend mapping contract**  
Operational UI states must have a documented mapping to backend states.

**FR-V3-065 — Gate invalidation**  
Material content/asset/version changes must invalidate affected prior gate approvals.

**FR-V3-066 — Autonomy semantics**  
Autonomy level and risky feature flags must be independent controls.

**NFR-021 — Capacity planning**  
System must expose and enforce resource/concurrency limits for expensive subsystems.


# V4 Additional Functional Requirements

### FR-V4-001 — Dynamic departments
System shall support create/merge/dissolve departments as data-driven backend entities.

### FR-V4-002 — Department charter
Every active department shall have a charter, manager, budget envelope, permissions and measurable purpose.

### FR-V4-003 — Delegated management
CEO may delegate bounded authority to department heads; delegated managers cannot exceed CEO/Policy limits.

### FR-V4-004 — Marketing department
Architecture shall support Marketing & Communications as a first-class department.

### FR-V4-005 — Multi-platform social
System shall support adapter-based YouTube, TikTok, Instagram, Facebook and Telegram account integration.

### FR-V4-006 — Teaser grounding
Marketing teasers based on studio events must link to committed backend/world events and pass public-safety/truth gates.

### FR-V4-007 — Marketing experiments
Marketing variants and results shall be stored and analyzed with attribution confidence.

### FR-V4-008 — Competitive intelligence
System shall support public market/competitor observations and opportunity hypotheses without copying protected content.

### FR-V4-009 — HR/People Ops
System shall support optional HR functions when workforce complexity justifies them.

### FR-V4-010 — Operational/narrative identity separation
Agent technical identity shall be distinct from public/narrative persona.

### FR-V4-011 — Persona
Narrative persona may include fictional birthday, traits, preferences, quirks and relationships.

### FR-V4-012 — Financial truth separation
External money evidence, estimates/forecasts, spendable VR$ and virtual debt/procurement shall remain distinct truth categories.

### FR-V4-013 — Legal review
System shall support rights/compliance review of content and marketing with configurable hard blocks.

### FR-V4-014 — Company events
System shall support scheduled company/world events with participant availability and production impact.

### FR-V4-015 — Milestone triggers
Channel/business milestones may propose configurable company events.

### FR-V4-016 — No-production event day
A CompanyEvent may pause ordinary production while essential reliability/security services remain operational.

### FR-V4-017 — Story truth categories
Story system shall distinguish operational events, committed fictional world events and story embellishment.

### FR-V4-018 — Org growth controls
CEO must consider cost/coordination overhead before creating new roles or departments.

### FR-V4-019 — Department visualization
Committed department changes shall be reflected in 2D office organization through backend events.

### FR-V4-020 — Public disclosure
Public-facing experience shall make clear that employee personas are AI/fictitious characters where appropriate.


# V5 Financial Economy Requirements

**FR-ECON-001 — VR$ peg**  
The in-world economy shall use `VR$`, pegged one-to-one to USD for eligible verified money events and market-priced virtual purchases.

**FR-ECON-002 — No autonomous real-money spending**  
The system shall not initiate bank transfers, card purchases, real loans, or external product checkout purchases.

**FR-ECON-003 — Financial truth separation**  
The system shall separate settled real-world evidence, pending receivables, estimates/forecasts, spendable VR$, restricted reserves, virtual procurement, and virtual debt.

**FR-ECON-004 — Revenue mint idempotency**  
Each external settlement/funding event shall map to at most one VR$ mint event.

**FR-ECON-005 — Reversals**  
Refunds/chargebacks/reversed payouts shall post reversing entries and may create a treasury deficit if prior VR$ was already spent.

**FR-ECON-006 — Multi-source monetization**  
RevenueSource architecture shall support platform income, donations, paid pitches, sponsorships, memberships, affiliate income, Owner capital and other future monetization sources.

**FR-ECON-007 — Settlement eligibility**  
Estimated or forecast income shall not become spendable VR$ automatically. Eligibility shall require settlement or explicit Owner-confirmed funding evidence.

**FR-ECON-008 — Multi-currency provenance**  
Non-USD amounts shall preserve original amount/currency and use a timestamped, sourced FX conversion for VR$ valuation.

**FR-ECON-009 — Double-entry VR ledger**  
The virtual economy shall use auditable double-entry accounting records.

**FR-ECON-010 — Treasury dashboard**  
Owner/CEO/Finance views shall expose cash, restricted cash, receivables, payouts, revenue, spend, debt, interest, burn, runway, budget and forecasts.

**FR-ECON-011 — Finance gate**  
Discretionary purchases shall require Finance affordability/budget validation according to policy.

**FR-ECON-012 — Procurement**  
Product requests shall use a typed Procurement workflow with real-world price evidence and quote expiry.

**FR-ECON-013 — New vs used**  
Procurement shall support NEW and USED condition requests with explicit condition metadata.

**FR-ECON-014 — No fake market price**  
A market price shall never be invented; unavailable/stale evidence shall block or require re-quotation.

**FR-ECON-015 — VendorShop**  
VendorShop shall execute only virtual purchases, not external checkout.

**FR-ECON-016 — Asset Architect**  
Approved virtual purchases may create a persistent office-world asset through a controlled asset-generation workflow.

**FR-ECON-017 — Financing proposal**  
CEO may propose virtual debt subject to Finance capacity analysis, current market reference terms, Legal review and governance.

**FR-ECON-018 — Financing no-cheat rule**  
Virtual borrowing shall be constrained by configured debt-capacity/risk rules and shall not be an unlimited source of VR$.

**FR-ECON-019 — Owner funding**  
Owner may record capital contributions or Owner loans. The system shall not independently transfer the underlying real funds.

**FR-ECON-020 — Interest accrual**  
Virtual loans shall accrue and schedule interest/principal deterministically.

**FR-ECON-021 — Financial stress modes**  
Treasury thresholds may trigger spending/hiring freezes and restructuring proposals.

**FR-ECON-022 — Financial story provenance**  
Serial/marketing references to economic events shall link to committed ledger/world events and may not fabricate amounts or approvals.

**FR-ECON-023 — Public financial privacy**  
Owner shall control whether exact VR$ values are public, rounded, indexed, or hidden.

**FR-ECON-024 — Actual provider costs**  
Where connected provider usage incurs real billable costs, those costs shall be imported/estimated with provenance and reconciled to actual invoices when available.

**FR-ECON-025 — Virtual financial statements**  
The system shall produce management-oriented VR$ P&L, Balance Sheet and Cash Flow views clearly labeled as non-statutory simulation/management records.
