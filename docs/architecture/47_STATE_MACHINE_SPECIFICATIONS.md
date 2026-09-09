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
