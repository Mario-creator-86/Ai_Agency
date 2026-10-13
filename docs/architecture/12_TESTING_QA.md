# Testing and QA v3

## Test philosophy

A feature is not complete because code compiles or UI looks correct.

Critical flows require:
- unit tests;
- integration tests;
- provider contract tests;
- E2E tests;
- failure tests;
- restart/recovery tests;
- race/idempotency tests.

## Unit tests

- agent lifecycle;
- role permissions;
- Director authority modes;
- Director self-permission restrictions;
- model capability matching;
- provider routing;
- fallback;
- budget reservation;
- task transitions;
- claim status/freshness;
- memory classification;
- idempotency;
- continuity rules;
- Showrunner grounding;
- office state transitions.

## Provider contract tests

For every configured provider adapter:
- health check behavior;
- auth failure;
- timeout;
- malformed response;
- rate limit;
- unavailable model;
- capability discovery;
- cost estimate behavior;
- retry classification.

Do not treat mock contract tests as proof a real external API is connected.

## Integration tests

- Director → command → permission engine;
- agent → provider;
- research → source;
- source → claim;
- fact checker → claim state;
- script → storyboard;
- media generation → asset store;
- TTS → editor;
- editor → QC;
- publication intent → YouTube;
- backend DB transaction → outbox → WebSocket;
- WebSocket → 2D projection;
- YouTube → analytics;
- DailyStudioLog → Showrunner.

## E2E

### E2E-01
Manual topic → verified script.

### E2E-02
Manual topic → final MP4.

### E2E-03
Final MP4 → private YouTube upload with confirmed remote ID.

### E2E-04
Uploaded video → analytics snapshot.

### E2E-05
Poor employee → benchmark → replacement.

### E2E-06
Backend task state → identical office state.

### E2E-07
Previous-day studio log → office episode.

### E2E-08
Terminated employee excluded from present-day cast.

### E2E-09
Provider failure → fallback or clean block.

### E2E-10
STOP AUTONOMY → no new external autonomous side effects.

## Realism tests

### Intent ≠ success
Have Director request a provider action without credentials.
Expected:
- action blocked;
- UI shows blocked/configuration required;
- no success event.

### Missing capability
Assign video task to text-only model.
Expected:
- task does not execute;
- BLOCKED_CAPABILITY.

### Hire unavailable model
Director tries to hire agent using unavailable model.
Expected:
- rejected or approval/configuration request;
- no employee appears in office.

## UI synchronization tests

### Wrong-task invariant
Backend: Agent A works Task X.
Frontend may not show Task Y.

### Event loss
Disconnect WebSocket, generate events, reconnect.
Expected:
snapshot/replay restores correct state.

### Duplicate event
Send same event twice.
Expected:
single visual/state application.

### Out-of-order event
Send older state after newer state.
Expected:
newer state preserved.

## Automation/recovery tests

- process crash mid-workflow;
- worker crash;
- scheduler restart;
- duplicate scheduler instance;
- DB temporarily unavailable;
- network outage;
- provider 429;
- provider 5xx;
- OAuth expiration;
- upload timeout after remote side effect;
- stuck task lease expiration;
- retry budget exceeded.

## Publishing idempotency test

Simulate YouTube responding slowly after receiving upload.

Client retries.

Expected:
system must determine whether remote upload already occurred before creating a second upload.

## Security tests

- malicious webpage prompt injection;
- SSRF URL;
- path traversal;
- command injection attempt in filename;
- secret in log;
- malicious fan prompt future;
- unsafe downloaded file metadata.

## Content tests

- false science claim;
- conflicting sources;
- stale time-sensitive claim;
- citation mismatch;
- script contains claim absent from Claim table;
- synthetic visual incorrectly labeled as real footage;
- unlicensed asset metadata missing.

## Character/serial tests

- same employee maintains canonical identity references;
- provider without reference-image capability yields warning/degraded mode;
- character drift can fail QC;
- fictional serial dialogue does not appear in live Agent Room;
- prior-day episode references valid source events.

## Cost tests

- per-task cap;
- per-day cap;
- retry cost cap;
- budget reservation concurrency.

## Restore test

Create backup.
Destroy test DB/assets.
Restore.
Expected:
- employment history;
- continuity;
- project state;
- content provenance;
remain usable.

## Acceptance report

Every milestone must produce:
- test commands;
- pass/fail counts;
- skipped tests;
- real-provider tests separately identified from mock tests;
- known limitations.

## v3 additional test classes

### Property/invariant tests
Assert invariants across many generated state sequences:
- terminated agent receives no new task;
- blocked hard gate cannot transition to publish;
- budget never becomes negative through concurrent reservations;
- one idempotency key produces at most one confirmed external side effect.

### Golden event-replay tests
Given a recorded backend snapshot + event sequence:
- reconstruct identical office state;
- reconstruct identical employment roster;
- reconstruct story continuity state.

### Migration tests
Upgrade representative old database/event fixtures through current migrations.

Verify:
- history preserved;
- event schemas upcast;
- no accidental publication triggered.

### Load/backpressure tests
Simulate:
- large idea queues;
- slow provider;
- many WebSocket viewers;
- multiple media jobs.

Expected:
- bounded queues;
- admission control;
- stable memory/CPU;
- no duplicate work.

### Agent-loop tests
Force:
- Research and Fact Checker repeated disagreement;
- Script ↔ QC rework loop.

Expected:
- configured iteration limit;
- escalation;
- no infinite token/cost loop.

### Context/prompt tests
- oversized history;
- malicious memory;
- irrelevant memory;
- schema-breaking model response;
- prompt-version rollback.

### Privacy/public projection tests
Assert public event stream cannot contain:
- secrets;
- private Owner commands;
- raw stack traces;
- confidential provider fields.

### World-builder tests
- room overlap;
- invalid asset;
- unsupported item type;
- inaccessible desk;
- failed asset generation.

No committed world change unless validation passes.

### Release tests
- feature flag off prevents risky path;
- rollback restores previous deploy;
- destructive migration requires backup/approval.

## Test evidence classification

Every test report must distinguish:
- MOCK;
- LOCAL INTEGRATION;
- REAL PROVIDER;
- STAGING;
- PRODUCTION OBSERVATION.

Do not use a mock pass to claim external production readiness.

## Reliability burn-in

Before enabling autonomous public publishing, run repeated supervised/dry-run cycles over a configured observation period.

Measure:
- failure rate;
- retry rate;
- manual interventions;
- duplicate side effects;
- provider degradation;
- cost variance;
- factual/QC rejection.


## V4 Organization / Marketing Tests

### Dynamic org
- CEO creates specialist role.
- CEO creates department when permitted.
- Department head cannot exceed delegated permissions.
- Dissolved department cannot receive new tasks.
- Org change updates UI only after backend commit.

### Marketing truth
Given real event "Director criticized Security Agent":
- truthful teaser allowed;
- teaser saying "Security was fired" rejected if no termination exists.

### Social adapter
- unsupported publish capability returns NOT_SUPPORTED.
- ambiguous post result enters reconciliation.
- duplicate post blocked by idempotency.

### Market Intelligence
- competitor observation stores source.
- copied script/content test triggers similarity/rights warning.
- recommendation remains recommendation until CEO decision.

### Persona
- birthday/personality persists across serial episodes.
- persona cannot grant tool permission.
- personality change is versioned.

### Company Event
- team-building event pauses ordinary production.
- essential system/watchdog remains active.
- UI shows OFFSITE/event state.
- serial can use committed event outcome.

### Finance
- real cost, estimated revenue and fictional economy remain separate.

### Legal
- hard compliance hold blocks public campaign/publish.

### Marketing learning
- cross-platform attribution with low confidence is not labeled exact causal conversion.


# V5 Economy Tests

## Money invariants

1. Same settled payout ingested twice → only one VR$ mint.
2. Forecast revenue → zero spendable VR$.
3. Pending payout → zero spendable VR$ unless explicit policy/financing mechanism says otherwise.
4. Settled $100 payout → exactly +100 VR$ before reserves/other ledger entries.
5. $20 refund/chargeback → exactly -20 VR$ reversing effect.
6. Non-USD settlement → original currency retained, sourced FX snapshot retained, deterministic VR$ conversion.
7. Ledger debits equal credits for every posted transaction.
8. UI treasury balance equals backend ledger projection.

## Procurement

- generic chair request obtains multiple quotes or explicitly documents single-source reason;
- stale quote blocks purchase until refresh;
- missing price blocks purchase;
- used/new condition remains correct through purchase and asset creation;
- VendorShop purchase never calls external checkout;
- insufficient VR$ blocks discretionary purchase;
- Finance rejection prevents ledger/world mutation;
- Asset Architect cannot create item before committed purchase unless marked PREVIEW;
- purchased asset visual identity matches selected specification within defined tolerance.

## Financing

- CEO cannot create financing without policy route;
- debt capacity limit blocks excessive loan;
- Owner loan and capital contribution produce different ledger/equity/liability effects;
- interest accrual is deterministic across restart;
- repayment reduces principal/interest correctly;
- market reference expiry causes re-pricing before new financing;
- virtual financing cannot invoke real loan application/checkout.

## Reconciliation

- estimate → settlement variance is recorded;
- provider usage estimate → invoice reconciliation is recorded;
- duplicate provider cost evidence does not double-charge VR$;
- reversal after VR$ already spent triggers deficit/stress logic rather than silently ignoring it.

## Story/privacy

- public episode cannot disclose exact PRIVATE_EXACT financial values;
- story cannot describe forecast as settled revenue;
- story cannot say a physical real-world chair was bought.
