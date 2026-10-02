# State Machine Specifications

## Agent lifecycle

PROPOSED
→ CANDIDATE
→ HIRED
→ ACTIVE
↔ PAUSED
↔ SUSPENDED
→ TERMINATING
→ TERMINATED
→ ARCHIVED

Rules:
- TERMINATED cannot become ACTIVE by editing state; create explicit rehire/employment event.
- SUSPENDED loses privileged execution until resumed.
- CANDIDATE cannot receive production-critical external-write work.

## Agent runtime

IDLE
→ THINKING / WORKING
→ WAITING_TOOL / WAITING_EXTERNAL / COMMUNICATING / REVIEWING
→ RETRYING
→ IDLE

Error branches:
BLOCKED
ERROR

Runtime state never changes lifecycle automatically.

## Content pipeline

DISCOVERY
→ IDEA_SELECTION
→ RESEARCH
→ FACT_CHECK
→ SCRIPTING
→ HOOK_OPTIMIZATION
→ STORYBOARD
→ ASSET_GENERATION
→ VIDEO_GENERATION
→ VOICE_GENERATION
→ EDITING
→ QUALITY_CONTROL
→ READY_TO_PUBLISH
→ PUBLISHING
→ PUBLISHED
→ ANALYTICS
→ LEARNING

Exceptional:
- NEEDS_REWORK returns only to declared upstream stage.
- FAILED is terminal for that workflow attempt, not necessarily ContentItem.
- BLOCKED waits for configuration/Owner/policy.
- PAUSED preserves resumable state.

### The content pipeline as built (amended 2026-10-02)

Amended deliberately on 2026-10-02 after the production-readiness audit (finding AR-14). The
content pipeline above is implemented as the stages of a `daily_run`, not as a `workflow` row per
item: preflight, performance intake, idea generation, research and verification, selection,
script and storyboard, serial queue, media, edit and QC, publish, post-run, daily log and
tomorrow's serial script. The run's own states:

RUNNING (written right after the preflight)
→ COMPLETED / PARTIAL / BLOCKED / FAILED

Exceptional:
- RUNNING → INTERRUPTED, at most once, when the studio stops between stages (the stage in flight
  ends after its current scene) or when the run's queue task lost its lease (the worker's sweep or
  the watchdog finds it). An INTERRUPTED day is never re-run by the clock; the Owner starts a new
  run. One letter tells him where it stopped.
- A paid step bought for a film is a `scene_take` (QUOTED → SUBMITTED → PAID → APPROVED /
  REJECTED; REFUSED; SUBMITTED → LOST after 24 h uncollected). APPROVED is the Owner's act only.

## Publication

DRAFT_INTENT
→ VALIDATED
→ STARTED
→ REMOTE_UNKNOWN or REMOTE_CONFIRMED
→ SCHEDULED / PUBLISHED

Failure:
FAILED_RETRYABLE
FAILED_FINAL
NEEDS_RECONCILIATION

Never retry from REMOTE_UNKNOWN without reconciliation.

## Provider

NOT_CONFIGURED
→ AUTH_REQUIRED / UNKNOWN
→ HEALTHY
↔ DEGRADED
↔ RATE_LIMITED
→ OFFLINE

Role suitability is separate:
UNKNOWN / TESTING / APPROVED / APPROVED_DEGRADED / UNSUITABLE / STALE.

## Workflow

CREATED
→ PREFLIGHT
→ ADMITTED
→ RUNNING
↔ PAUSED
→ COMPLETED

Exceptional:
BLOCKED
CANCEL_REQUESTED
CANCELLED
FAILED
NEEDS_REPAIR

### Workflow rows as built (amended 2026-10-02)

Amended deliberately on 2026-10-02 (finding AR-14). Scheduled jobs no longer create `workflow`
rows: a scheduled fire writes the event `workflow.job_fired` and a `task_queue` item with no
workflow. The machine above remains for workflows created by hand, and its pause, resume and
cancel routes act only on those rows; they never controlled the daily run, which the Owner stops
with STOP. The 665 rows already in the Owner's database stay as they are (CREATED, DISCOVERY);
removing or relabelling them is a later maintenance step. A queue task's lease is one token per
claim, renewed by a heartbeat; a task whose lease lapsed with no attempts left becomes
DEAD_LETTER with an `INTERRUPTED:` reason and is not run again.

## Gate

NOT_EVALUATED
→ PASS / FAIL / NEEDS_REVIEW / NOT_APPLICABLE

Gate history is immutable per policy/content version. Re-review creates a new GateEvaluation.

## Office world change

PROPOSED
→ VALIDATING
→ PREVIEW_READY
→ APPROVED
→ COMMITTED
→ RENDERED

Exceptional:
REJECTED
FAILED_ASSET
FAILED_PLACEMENT

UI must never show permanent new object before COMMITTED.


## V4 Department state machine

PROPOSED → TRIAL → ACTIVE → UNDER_REVIEW → MERGING/DISSOLVING → DISSOLVED → ARCHIVED

## Campaign

DRAFT → REVIEW → APPROVED → SCHEDULED → PUBLISHING → ACTIVE → COMPLETED
Failure:
BLOCKED / FAILED / CANCELLED

## CompanyEvent

PROPOSED → APPROVED → SCHEDULED → ACTIVE → COMPLETED → ARCHIVED
or CANCELLED

## ComplianceReview

REQUESTED → REVIEWING → PASS / NEEDS_REWORK / HOLD / ESCALATED


# V5 Financial State Machines

## RevenueEvidence
DISCOVERED → NORMALIZED → VERIFIED → {ESTIMATED | PENDING | SETTLED | REVERSED | REJECTED}

Only SETTLED/eligible Owner-confirmed funding can transition into MINT_ELIGIBLE.

## Procurement
REQUESTED → SPECIFIED → SOURCING → QUOTED → FINANCE_REVIEW → LEGAL_REVIEW_IF_NEEDED → APPROVED → VIRTUAL_PURCHASED → ASSET_BUILDING → DELIVERED → PLACED

Alternative states:
REJECTED, QUOTE_EXPIRED, CANCELLED, FULFILLMENT_FAILED.

## Financing
REQUESTED → CAPACITY_REVIEW → MARKET_TERMS → LEGAL_REVIEW → APPROVAL → ACTIVE → REPAID
Alternative: REJECTED, CANCELLED, AT_RISK, DEFAULTED_VIRTUAL, RESTRUCTURED.

## LedgerTransaction
DRAFT → VALIDATED → POSTED
Corrections use a new REVERSING transaction; posted entries are not mutated.
