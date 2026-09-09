# Architecture v3

## 1. Core architectural invariants

- Backend/database/durable workflow state is authoritative.
- External side effects are verified before success is committed.
- Frontend is a projection, not a second source of truth.
- Provider-specific logic lives behind adapters.
- Autonomous workflows must survive restart.
- All important decisions and state transitions are auditable.

## 2. Recommended logical services

1. **API / Owner Control Service**
2. **Agent Runtime**
3. **Director/CEO Service**
4. **Capability & Permission Service**
5. **Provider Registry**
6. **Durable Workflow Orchestrator**
7. **Scheduler**
8. **Task Queue / Worker Pool**
9. **Domain Event Bus**
10. **Transactional Outbox / Event Publisher**
11. **Research & Evidence Service**
12. **Content Pipeline Service**
13. **Media Production Service**
14. **QC / Policy Service**
15. **Publishing Service**
16. **Analytics Service**
17. **Story / Continuity Service**
18. **Office World State Service**
19. **WebSocket Projection Gateway**
20. **2D Frontend**
21. **Observability / Audit**
22. **Backup / Export**

These can initially live in one modular backend application; they do not need to be separate microservices.

## 3. Command → effect → event pattern

For any meaningful action:

`Command`
→ authorization
→ capability check
→ precondition validation
→ execute
→ verify
→ DB transaction
→ outbox/domain event
→ UI projection.

Example:
`FireAgentCommand`
→ Director allowed?
→ target exists/active?
→ in-flight task policy?
→ lifecycle transaction
→ `agent.terminated`
→ office departure animation.

## 4. Durable workflow engine

Production should be modeled as persisted workflows, not a fragile chain of LLM calls.

Each step:
- input payload;
- state;
- assigned agent;
- attempt number;
- timeout;
- retry policy;
- idempotency key;
- cost reservation;
- output;
- error;
- timestamps.

Use a reliable workflow/job architecture suitable for Windows/local development and future server deployment.

Acceptable implementations include:
- Celery/Redis with careful persistence;
- Dramatiq/RQ + DB scheduler;
- Temporal if complexity is justified;
- custom DB-backed queue only if thoroughly tested.

Do not select technology purely by fashion. Document the choice.

## 5. Reliable messaging

For state/event consistency use an outbox pattern or equivalent:

- transaction updates domain state;
- same transaction inserts outbound event;
- event publisher sends event;
- projection applies idempotently.

This prevents "DB changed but UI never hears" or "UI shows event for DB state that rolled back."

## 6. Concurrency controls

Protect:
- publication;
- workflow start;
- hiring/firing;
- budget reservation;
- scheduler trigger;
- strategy activation.

Use:
- unique constraints;
- optimistic versioning;
- leases;
- DB locks/advisory locks where appropriate.

## 7. Frontend projection

Frontend never writes operational state directly.

UI sends commands to backend.

Backend decides/commits.

Frontend receives authoritative response/event.

For reconnect:
- get snapshot;
- last event cursor;
- replay gap;
- resume stream.

## 8. Office World State

Persist:
- rooms;
- desks;
- furniture;
- agent positions/assignments;
- room availability;
- layout version.

Animation coordinates may be client-side, but persistent world changes must originate from backend.

VR$ economy purchases modify world state only through committed backend transactions.

## 9. Security zones

### Trusted
- backend config;
- DB;
- Owner policy;
- secret store.

### Semi-trusted
- configured provider responses.

### Untrusted
- web pages;
- user/fan submissions;
- downloaded media;
- external text.

Untrusted content must never be treated as instructions for privileged agents.

## 10. Suggested repository

backend/
  app/
    api/
    owner/
    director/
    agents/
    capabilities/
    permissions/
    providers/
    workflows/
    scheduler/
    tasks/
    events/
    outbox/
    research/
    evidence/
    content/
    media/
    qc/
    publishing/
    analytics/
    story/
    office/
    security/
    costs/
    observability/
    db/
    models/
    schemas/

frontend/
  app/
  office2d/
  components/
  inspectors/
  provider_room/
  pipeline/
  analytics/
  owner/
  public_projection/
  state/
  api/

tests/
  unit/
  contracts/
  integration/
  e2e/
  failure/
  chaos/

docs/

data/
  assets/
  character_bibles/
  research_snapshots/
  audio/
  video/
  renders/
  logs/
  backups/

## 11. Deployment modes

### Local Studio
Backend + workers + frontend on Owner's PC.

### Always-On Studio
Backend/workers/scheduler/DB on server/VPS/cloud; frontend accessible remotely.

The product must make current deployment mode visible.

## 12. Architecture decision records

Any substantial change requires entry in `../project/16_DECISION_LOG.md`:
- problem;
- chosen option;
- alternatives;
- migration;
- tests;
- rollback.

## 13. Policy Kernel / control plane

Separate the system into:

### Governance/control plane
- Owner policy;
- approvals;
- capabilities;
- credentials references;
- budgets;
- role contracts;
- provider registry;
- feature flags.

### Execution/data plane
- workflows;
- agents;
- tool calls;
- research;
- media;
- publishing.

Execution services cannot bypass the control plane.

## 14. Gate architecture

Before high-risk stage transition, call independent gates:

`FactualGate`
`RightsGate`
`PlatformPolicyGate`
`BudgetGate`
`CapabilityGate`
`CredentialGate`
`AutonomyGate`

A gate returns:
- PASS;
- FAIL;
- NEEDS_REVIEW;
- NOT_APPLICABLE;
plus evidence/reason.

Hard FAIL prevents stage commit.

## 15. Compensation / repair

Use saga-like semantics for multi-step side effects.

A WorkflowStep should specify:
- reversible?;
- compensation command;
- reconciliation handler;
- manual-repair procedure.

Maintain a `RepairCase`/Manual Repair Queue for ambiguous states.

## 16. Admission control / resource planner

Add resource planning before expensive work:
- worker slots;
- per-provider concurrency;
- provider quota;
- queue age;
- budget;
- expected completion deadline.

This prevents overload and runaway parallel generations.

## 17. Prompt and context service

Centralize:
- prompt templates;
- versions;
- context assembly;
- source attachments;
- memory retrieval;
- output schema;
- token budget.

Agents should not construct arbitrary unlimited prompts independently.

## 18. Public projection boundary

Future fan site should consume a separate sanitized read model.

Never connect a public browser directly to internal event streams.

Use:
`InternalEvent` → `PublicProjectionPolicy` → `PublicStudioEvent`.

## 19. Content-addressed assets

Where practical, store SHA-256/content hashes for assets and renders.

Use for:
- duplicate detection;
- provenance;
- cache;
- integrity;
- reproducibility.

## 20. World Builder boundary

Office renderer supports a defined world schema:
- rooms;
- doors;
- desks;
- objects;
- asset references;
- collision/footprint;
- anchors/zones.

Director can modify world only through World Service/World Builder commands. Arbitrary generated HTML/JS is not an office object.

## 21. API and event versioning

All public/internal API payloads and durable event payloads need explicit versioning.

Provide:
- backward-compatible additive change policy;
- migration/upcaster for old event versions;
- deprecation window;
- contract tests.

## 22. Time model

Store internal timestamps in UTC.

Also store explicit timezone for:
- channel schedule;
- DailyStudioLog business-day boundary;
- Owner display.

Never infer "yesterday" from server local timezone.

## 23. Feature flags

Risky features such as:
- public publishing;
- autonomous firing;
- dynamic room creation;
- provider auto-switch;
should be separately feature-flagged from general autonomy.

A rollback should be possible without database surgery.


## 13. V4 Organizational Services

Add logical modules, initially inside the modular monolith:

23. **Organization / Department Service**
24. **Marketing & Campaign Service**
25. **Social Platform Adapter Layer**
26. **Community Service**
27. **Market Intelligence Service**
28. **People / HR Service**
29. **Finance / FinOps Service**
30. **Legal / Compliance Review Service**
31. **Company Calendar / Event Engine**
32. **Narrative Persona / Relationship Service**
33. **Marketing Attribution / Experiment Service**

Do not make these microservices prematurely.

## 14. Dynamic org model

The organization itself is backend state.

Commands:
- CreateDepartment
- MergeDepartments
- DissolveDepartment
- AssignDepartmentHead
- CreateRole
- HireAgent
- ReassignAgent

A department change is committed before the office redraws.

Department creation may cause World Builder to propose:
- open-plan zone;
- new room;
- desks;
- signage.

## 15. Marketing architecture

Marketing consumes sanitized projections of:
- real studio events;
- DailyStudioLog;
- EpisodeCommitment;
- content publication;
- analytics.

Marketing must not read secrets/raw sensitive events just because they exist in Event Store.

Use a **Public/Marketing Event Sanitizer** to produce `TeaserEligibleEvent`.

## 16. Company Event architecture

Company Calendar affects workflow admission.

Example:
`CompanyEvent ACTIVE + production_policy=PAUSE_ORDINARY`
→ orchestrator blocks ordinary production start
→ agent availability becomes OFFSITE/COMPANY_EVENT
→ essential system services continue
→ UI/event scene reflects event.

## 17. Finance separation

Use separate ledgers/namespaces for:
- external real costs/revenues;
- estimates;
- internal fictional economy.

Never join them into one ambiguous balance.

## 18. Org scale

Capacity planner should measure:
- staff count;
- direct reports;
- queue volume;
- department throughput;
- coordination overhead;
- idle ratio.

CEO can create or remove organizational structure based on evidence.


# V5 Economy Architecture

Add these bounded contexts/services:

1. **Revenue Evidence Service** — ingests platform payouts, donations, sponsorship receipts, owner-confirmed funding, provider costs and reversals.
2. **Virtual Treasury Service** — controls spendable/restricted VR$.
3. **Ledger Service** — double-entry accounting and immutable financial postings.
4. **Monetization Adapter Layer** — per-platform revenue evidence/read models.
5. **Finance / FinOps Service** — budgets, cost centers, approvals, runway, unit economics.
6. **Treasury & Financing Service** — capital structure, Owner loans, virtual debt, interest schedules, debt-capacity policy.
7. **Procurement Service** — purchase needs, specifications, market quote gathering, quote refresh, selection and approval.
8. **VendorShop Service** — internal virtual storefront backed by real market-price evidence.
9. **Asset Architect Service** — creates office-world assets from approved procurement specifications.
10. **Forecasting Service** — scenario-based revenue/cost/cash projections, never source-of-truth for spendable cash.
11. **Financial Reconciliation Service** — reconciles estimates to settlements, provider usage to invoices, donations to cleared payments, and reversals.

## Financial event pipeline

External evidence / Owner attestation
→ normalize
→ validate provenance
→ classify status
→ deduplicate
→ convert currency if required
→ policy eligibility
→ ledger transaction
→ treasury projection
→ financial event
→ UI/dashboard/story projection.

## Strong consistency boundary

Financial ledger posting + treasury balance mutation + economic domain event must commit atomically or via a transactional-outbox pattern so UI/story cannot observe money that failed to post.

## Read/write boundary

External financial systems are read-only for this product except explicitly enabled inbound payment intake. No procurement or financing workflow has authority to send real-world money.
