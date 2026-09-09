# Master Acceptance Criteria

## A. Reality / UI

- [ ] Backend is authoritative.
- [ ] Every live operational animation has event/state provenance.
- [ ] UI distinguishes pending from verified success.
- [ ] WebSocket reconnect restores correct state.
- [ ] Duplicate/out-of-order events do not corrupt UI.

## B. Director

- [ ] Director can assign/prioritize.
- [ ] Director can benchmark.
- [ ] Director can hire/fire within mode.
- [ ] Director cannot self-escalate.
- [ ] Director cannot hire unavailable/unconfigured capability as if successful.
- [ ] Director decisions are auditable.

## C. Employees

- [ ] Every role has contract.
- [ ] Least privilege enforced.
- [ ] Required capability checked.
- [ ] Tool receipts separate reality from model narrative.
- [ ] Termination preserves history.

## D. Automation

- [ ] Durable state machine.
- [ ] Persisted scheduler.
- [ ] Worker leases.
- [ ] Retry/backoff.
- [ ] Circuit breakers.
- [ ] Stuck-job watchdog.
- [ ] Idempotent publishing.
- [ ] Restart recovery.
- [ ] STOP AUTONOMY.

## E. Factual pipeline

- [ ] Sources stored.
- [ ] Claims map to evidence.
- [ ] Critical unsupported claims block.
- [ ] Prompt injection tested.
- [ ] Stale/conflicting claims handled.

## F. Video

- [ ] Provider adapters honest.
- [ ] Media provenance.
- [ ] Character continuity system.
- [ ] FFmpeg final render.
- [ ] Technical QC.
- [ ] Rights/policy QC.

## G. YouTube

- [ ] OAuth works.
- [ ] Private upload verified.
- [ ] Remote ID persisted.
- [ ] Duplicate protection.
- [ ] Real analytics only.
- [ ] Current policy gate before autonomous public mode.

## H. Office serial

- [ ] Daily Studio Log.
- [ ] Showrunner.
- [ ] Dynamic roster continuity.
- [ ] Operational vs dramatized messages separated.
- [ ] Scene-to-event provenance.
- [ ] Correct office historical layout.

## I. Operations

- [ ] Local background service works without open UI.
- [ ] Always-on deployment path documented.
- [ ] Backup succeeds.
- [ ] Restore tested.
- [ ] Disk/asset retention configured.
- [ ] Health/observability dashboard.

## J. Multi-AI development

- [ ] CURRENT_STATUS current.
- [ ] TODO current.
- [ ] Decision log current.
- [ ] Tests reproducible.
- [ ] Next AI can continue without re-architecture.

## K. Governance / policy
- [ ] Owner Policy Kernel enforced server-side.
- [ ] Hard gates cannot be overridden by Director prose.
- [ ] Approval tiers work.
- [ ] Public publishing is feature-flagged separately.

## L. Agent runtime
- [ ] AgentRun stores prompt/context/provider metadata.
- [ ] Schema validation rejects malformed outputs.
- [ ] Message/rework loop limits work.
- [ ] Agent concurrency limits work.
- [ ] Probation/shadow mode available for new critical employees.

## M. Prompt/memory
- [ ] Prompt versions rollback.
- [ ] Context budgets enforced.
- [ ] Memory provenance/TTL/invalidation works.
- [ ] Untrusted memory cannot silently become verified fact.

## N. Reliability
- [ ] Daily preflight blocks unsafe run.
- [ ] Backpressure prevents queue/resource overload.
- [ ] Manual Repair Queue exists.
- [ ] Safe mode blocks external writes on P0.
- [ ] SLO/reliability burn-in measured before autonomous public launch.

## O. Public/story safety
- [ ] Narrative projection sanitizes internal events.
- [ ] Private Owner/security data cannot reach public serial.
- [ ] Technical provider identity can be hidden behind public alias.

## P. World evolution
- [ ] Director cannot create unsupported arbitrary UI code.
- [ ] Room/object changes validate asset/placement.
- [ ] World change commits before UI rendering.

## Q. Release/security
- [ ] CI/type/lint/test pipeline.
- [ ] dependency lockfile.
- [ ] secret scanning.
- [ ] feature flags.
- [ ] rollback procedure.
- [ ] high-risk tools constrained by permission/egress policy.

## R. Business transfer
- [ ] assets and licenses inventoried.
- [ ] provider/channel account inventory.
- [ ] config/data export excluding secrets.
- [ ] no required personal filesystem paths.

## S. Contracts / state
- [ ] critical FRs trace to tests/phases;
- [ ] state transitions tested;
- [ ] typed commands used for privileged effects;
- [ ] gate approvals tied to exact versions;
- [ ] autonomy mode and feature flags behave independently.

## T. Capacity
- [ ] provider concurrency limits;
- [ ] render worker limits;
- [ ] queue backpressure;
- [ ] storage runway/alerts;
- [ ] public-view load plan before fan launch.


# V4 Acceptance Additions

## Dynamic organization
PASS only if:
- CEO can create a department via command/policy path;
- department persists;
- manager permission is bounded;
- office updates from event;
- rollback/dissolution history remains.

## Marketing teaser
PASS only if:
- teaser is linked to committed event;
- false escalation is rejected;
- sanitizer prevents sensitive data leak;
- campaign stores variants/results.

## Cross-platform
PASS only if:
- unsupported platform capability is reported honestly;
- posting has idempotency/reconciliation;
- account auth state is real.

## Persona
PASS only if:
- birthday/traits persist;
- fired character continuity remains correct;
- persona cannot change permissions.

## Event day
PASS only if:
- scheduled team building can pause ordinary production;
- essential system services remain safe;
- UI shows event status;
- Story Engine can produce an event-day episode from committed event canon.


# V5 Economy Acceptance Criteria

Economy is not complete until:
- [ ] $1 eligible settled evidence produces exactly 1 VR$ once.
- [ ] forecasts/pending payouts cannot be spent.
- [ ] reversals/chargebacks post correctly.
- [ ] ledger always balances.
- [ ] treasury UI equals backend ledger projection.
- [ ] no external checkout/payment command exists in autonomous procurement path.
- [ ] CEO chair request can source current new/used quotes with provenance.
- [ ] stale quote blocks or refreshes before purchase.
- [ ] Finance can approve/reject based on runway/budget.
- [ ] virtual purchase deducts exact approved VR$ amount.
- [ ] Asset Architect generates the selected item representation and world state updates only after purchase commit.
- [ ] Owner contribution and Owner loan behave differently in ledger.
- [ ] virtual financing uses market reference evidence and debt-capacity gates.
- [ ] interest survives restart and accrues deterministically.
- [ ] exact financial values obey public privacy/disclosure mode.
