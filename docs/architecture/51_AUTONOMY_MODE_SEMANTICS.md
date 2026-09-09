# Autonomy Mode Semantics

## Manual

- agents may draft/analyze;
- Owner approves defined stage transitions;
- no autonomous public external write unless explicitly requested.

## Supervised / Managed

- routine internal stages automatic;
- configurable T2/T3 actions create Approval;
- publishing usually requires approval initially.

## Autonomous CEO

- Director can execute allowed T0–T3 actions within policy;
- T4 remains Owner-only;
- hard gates remain non-bypassable;
- P0 can enter SAFE_MODE automatically.

## Feature flags are separate

Autonomy mode alone does not imply every feature is enabled.

Example:
AUTONOMOUS CEO + `public_publish_enabled=false`
means studio can create final content automatically but not publish publicly.

## Transition to higher autonomy

Require:
- acceptance criteria;
- burn-in;
- no unresolved P0;
- Owner action.

Do not automatically promote autonomy mode because tests passed.

## Lowering autonomy

Immediate and safe:
- future work uses lower mode;
- active workflow external writes respect current policy at execution time.

## STOP AUTONOMY

Overrides all modes until explicitly cleared.

## SAFE_MODE

Stricter incident state:
- no risky external writes;
- repair/reconciliation priority;
- monitoring available.


## V4 department autonomy

Autonomy can be scoped per department.

Example:
- Production = AUTONOMOUS
- Marketing = SUPERVISED
- Paid Media = MANUAL
- Legal = autonomous review but human escalation
- HR = MANAGED

Global STOP AUTONOMY overrides all autonomous departmental actions.

CompanyEvent with production pause changes workflow admission, not global security monitoring.
