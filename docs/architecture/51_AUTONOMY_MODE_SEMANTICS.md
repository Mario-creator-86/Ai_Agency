# Autonomy Mode Semantics

Built 2026-09-18, and the dated paragraphs below say which sentence of this document is code and
which is not. Until then the mode was `Literal["MANUAL"] = "MANUAL"` on `PolicyView` — a constant no
command could move — while the daily run walked twelve stages with no Owner approval between them.
The mode is now a column (`owner_policy.autonomy_mode`, migration `0043_autonomy_mode`), one command
(`change_autonomy_mode`, `POST /api/v1/owner/autonomy-mode`) and one gate
(`app.services.may_act(session, action, tier)`), asked over a risk-tier table
(`ACTION_RISK_TIERS`) transcribed from `31_GOVERNANCE_APPROVAL_POLICY`'s action risk tiers and
`32_AGENT_TOOL_PERMISSION_MATRIX`'s tool risk classes. Existing and new rows were written
AUTONOMOUS_CEO because that is the reading of the code that is true, not as a promotion: the
migration records what the studio has been doing, and the command is the only thing that raises the
mode.

`may_act` reads 31's authority hierarchy top down — STOP AUTONOMY, then T4, then SAFE_MODE, then the
mode — so no mode can be the thing that lets a lower layer past a higher one. An action the table
does not know and the caller does not classify is refused `BLOCKED_UNCLASSIFIED`, and a caller's own
tier is only ever taken upward, so an agent cannot downgrade the risk of its own act.

## Manual

- agents may draft/analyze;
- Owner approves defined stage transitions;
- no autonomous public external write unless explicitly requested.

In code since 2026-09-18: `MODE_ALLOWS["MANUAL"] = "T1"`. The day still runs, and the stages above
T1 are recorded SKIPPED with the Owner's reason rather than BLOCKED — a MANUAL studio is not a
stopped studio, and it may still draft, storyboard, write the serial's episode and measure what it
already has. A whole scheduled day under MANUAL is tested: it fetches no page, buys no shot, uploads
nothing and raises no approval request, because MANUAL is already the Owner's answer.

## Supervised / Managed

- routine internal stages automatic;
- configurable T2/T3 actions create Approval;
- publishing usually requires approval initially.

In code since 2026-09-18: `MODE_ALLOWS["SUPERVISED"] = "T2"`, and a T3 action writes the Approval of
31 — `owner_approval_request` (action, requester, risk tier, evidence, proposed diff, nullable cost,
reversibility, expiry, approver, result) — instead of being performed. The cost is nullable because
a cost the studio cannot compute is None and never zero. A standing request for the same action is
reused rather than duplicated, and an expired one is marked EXPIRED and a new one raised, because 31
says an expired approval cannot be reused. **Not built:** nothing answers a request. There is no
route to approve or refuse, nothing consumes an APPROVED row and no stage re-attempts after one
appears, so a SUPERVISED studio records its question honestly and stops there. A whole scheduled day
under SUPERVISED is tested: it films the day and writes exactly one request, for
`publishing.public_publish`, instead of uploading.

## Autonomous CEO

- Director can execute allowed T0–T3 actions within policy;
- T4 remains Owner-only;
- hard gates remain non-bypassable;
- P0 can enter SAFE_MODE automatically.

In code since 2026-09-18: `MODE_ALLOWS["AUTONOMOUS_CEO"] = "T3"`, and T4 is in no mode's list at
all. This is the mode the migration recorded, because it is what the code does: the runbook walks
twelve stages in one call with no Owner approval between them, the Director approves in the same
breath she reads, the media stage reserves budget and pays a vendor, the publish stage writes to the
platform — and nothing in the tree executes a T4 action autonomously. The hard gates are unchanged
and a test proves the mode cannot move one: the five-point publishing gate is asked for a public
film in each of the three modes and refuses in all three. A mode decides what the studio may
*attempt*; it never decides what a gate *concludes*.

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

In code since 2026-09-18, and honestly partial. Two of the four are readable in this database and
are enforced: an open `safe_mode_record` is an unresolved P0, and `autonomy_stopped` is the Owner
saying the studio should not act, and a *promotion* is refused on either — in Romanian, with no
ledger event written and the policy version untouched. The Owner's action is the command itself,
which is versioned by `expected_version` and idempotent by `command_id`, so a promotion is his
recorded act and a replay is not a second one. **Acceptance criteria and burn-in are not checked and
cannot be from this database**: they are judgements about evidence outside it. The refusal names
them to the Owner instead of approximating them, and the command's docstring says plainly that it
does not verify them. A numeric burn-in would need a definition of what counts as a clean run and
over how many days, which is the Owner's to give.

## Lowering autonomy

Immediate and safe:
- future work uses lower mode;
- active workflow external writes respect current policy at execution time.

In code since 2026-09-18: lowering is allowed unconditionally — under STOP, in safe mode, at any
time — because a safety state that blocked the safer choice would be the wrong shape of safety. A
day already in flight reads the mode again before each stage and again per film before it spends or
uploads, so the lower mode takes effect at the next act rather than at the next run.

## STOP AUTONOMY

Overrides all modes until explicitly cleared.

In code since long before the modes existed, and unchanged by them: `may_act` answers
`BLOCKED_STOP` before it looks at the tier or the mode, and the stop is read independently by the
runbook before every stage, by the media stage before every film, by the render between scenes, by
the five-point publishing gate and by the Policy Kernel. The mode gate in the daily run deliberately
does not re-read it — five readers are enough, and a sixth would create a place where somebody could
later think the stop lives.

## SAFE_MODE

Stricter incident state:
- no risky external writes;
- repair/reconciliation priority;
- monitoring available.

In code since 2026-09-18: `SAFE_MODE_ALLOWS = "T1"`, asked after the T4 refusal and before the
mode's own ceiling, so monitoring (T0) and reversible internal repair (T1) continue while money and
anything leaving the studio do not. An incident therefore lowers the studio below any mode without
changing the mode the Owner set, and clearing the incident restores his mode rather than a
remembered one.


## V4 department autonomy

**Not implemented (stated 2026-09-18).** `owner_policy.autonomy_mode` is one global mode and
`may_act` consults only it. A per-department override is additive on this shape — a second table
keyed by department, consulted before the global mode — but it needs a department on each action
first, and inventing the department list without the Owner would be guesswork. Everything below
therefore describes an intention, not behaviour.

Autonomy can be scoped per department.

Example:
- Production = AUTONOMOUS
- Marketing = SUPERVISED
- Paid Media = MANUAL
- Legal = autonomous review but human escalation
- HR = MANAGED

Global STOP AUTONOMY overrides all autonomous departmental actions.

CompanyEvent with production pause changes workflow admission, not global security monitoring.
