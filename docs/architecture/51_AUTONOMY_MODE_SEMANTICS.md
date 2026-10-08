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
a cost the studio cannot compute is None and never zero. A standing request for the same action *and
the same subject* is reused rather than duplicated, and an expired one is marked EXPIRED and a new one
raised, because 31 says an expired approval cannot be reused.

Corrected 2026-09-18, at the close of the phase: this section said **Not built:** nothing answers a
request — no route to approve or refuse, nothing consuming an APPROVED row, no stage re-attempting
after one appears — and it said a whole SUPERVISED day writes *exactly one* request for
`publishing.public_publish`. All four are now built and the count was a defect, not a design: a
request keyed by its action alone let the day's second film reuse the first film's row. Migration
`0044_approval_answered` adds the subject the question is about, `GET /api/v1/owner/approvals` lists
what waits, `POST /api/v1/owner/approvals/decision` answers it once, and the answer is spent inside
`may_act` in this very branch — after the stop, T4 and safe mode, so it converts "he must be asked"
into "allowed, once" and never a refusal into a pass. 31's new section *Answering an approval, and
spending it* specifies the whole of it, including what a STOP, a SAFE_MODE, a lowered mode and a moved
policy version each do to an answer he has already given. The stage wrapper asks the mode with
`ask_owner=False` so that nothing is written before the studio knows which film it is asking about,
and the whole-day test now measures **one request per film** — two on that day, the factual short and
the serial's episode — each with its own subject, and reads back the one the publish stage recorded.

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

## Paid media steps: the Owner's own rule, read before the mode

Amended deliberately on 2026-09-27, after the Nepal film. Under AUTONOMOUS_CEO the studio bought
two whole films (over 1,000 Runway credits) with no question asked, because a paid render sat
inside the mode's T3 ceiling. The paid steps of a film are therefore four actions of their own:
`media.stills_purchase` (T2), `media.test_shot` (T3), `media.motion_purchase` (T3) and
`media.scene_redo` (T3). None of them is T4, because T4 would make a film impossible to buy. For
these four, `may_act` reads one more thing, the Owner policy's `paid_media_approval`, after the
unclassified check, STOP, T4 and SAFE_MODE and before the mode's "within the ceiling → allowed"
return. `EVERY_PAID_STEP` is the default, and a missing, unknown or incomplete value is read as
it; it asks him in every mode, AUTONOMOUS_CEO included. `OVER_USD` asks above his threshold and
whenever the cost is unknown. `MODE` hands the step back to the modes above, unchanged. This is
stricter than the modes by the Owner's own policy, which 31's hierarchy already ranks above the
Director, and it loosens nothing: a step the rule lets through still meets the mode, and a mode
that refuses still refuses. The question and the answer are bound to the shooting sheet's
`plan_hash`, its step and its credit cap through the proposed diff, so a yes is spent once, before
the purchase, and only on the plan he saw; a request that names no plan is refused
`BLOCKED_NO_PLAN` and asks nothing. 31's "read in one place only" still holds: the same gate, the
same spending, after the same refusals, with one widening — "he would have to be asked" can now
come from his paid-media rule as well as from SUPERVISED. Only his versioned command
`SetPaidMediaApproval` (`change_paid_media_approval`, issued by the Owner and nobody else) moves
the rule; no agent, AUTORUN, mode change or request parameter does. The cost of the rule is stated
here on purpose: while it stays `EVERY_PAID_STEP`, every film waits for him at the stills, the hero
test shot and the motion, which conflicts openly with "autonomous from day two", and only he can
resolve that, by loosening it. Not built at this writing: the gate is code and tested, but nothing
calls these four actions yet. The shooting sheet's step routes, the stills and motion stages and
the daily run's staircase are specified and pending; until they land, the daily run's media stage
is still asked as `media.paid_generation` under the mode alone, and the page's render button does
not consult `may_act`. The MANUAL whole-day statement above is unaffected, because the daily run's
media stage is skipped under MANUAL before any paid step is proposed.

### The staircase as built (amended 2026-10-02)

Built since 2026-10-01; amended deliberately on 2026-10-02 after the production-readiness audit
(finding A17). The paragraph above that says "Not built at this writing" is history and is kept
as such. The four actions are called: `stills_stage.run_stills_stage` asks
`media.stills_purchase`, `assembler.run_motion_step` asks `media.test_shot` and
`media.motion_purchase` (through `shooting_sheet.run_sheet_step` for the Owner's press and for
the day), and `assembler.redo_scene` asks `media.scene_redo`. In PRODUCTION the daily run's media
stage climbs the same shooting sheet (`runbook.stages._film_staircase`), one stair per call, each
bound to its own `plan_hash`; in TEST the day buys nothing from the real vendors and writes the
Owner one letter that says what PRODUCTION would do under his rule. The rules as built:

- **OVER_USD reads the cap** (ADR-OVER-USD-CAP). The `cost_usd` a paid step hands to `may_act` is
  the step's credit cap in USD, not its estimate, because the cap is what the step may spend; the
  question reads «plafon X USD».
- **No daily budget, no unasked purchase** (ADR-DAILY-BUDGET-REQUIRED). In PRODUCTION, when MODE,
  or OVER_USD under his amount, would let a paid step through without asking and the mode allows
  its tier, `may_act` answers `BLOCKED_NO_BUDGET` unless an active DAILY `SpendingBudget` exists;
  a monthly budget alone is not enough. Under `EVERY_PAID_STEP` nothing changes, because he is
  asked anyway. The preflight line `spending_budget` is BLOCKING in exactly that case.
- **The hero rule** (ADR-HERO-CLIP-QC). The rest of the motion follows the hero test shot only
  when `assembler.hero_gate` allows it: the hero take is PAID, its latest clip-QC report PASSED,
  and a dry `may_act("media.motion_purchase", cost_usd=<the motion cap>, ask_owner=False)` answers
  ALLOWED. Under MODE, or OVER_USD with the motion cap under his amount, clip QC therefore accepts
  the hero, recorded once per take as the event `media.hero_accepted_by_clip_qc` with the clip-QC
  report's id; the take stays PAID, and APPROVED stays his alone. Under `EVERY_PAID_STEP`,
  SUPERVISED or MANUAL the hero waits for his look as before. An unchecked or failed hero always
  waits; STOP, SAFE_MODE and `BLOCKED_NO_BUDGET` refuse with their own status. No new action or
  tier was added: the gate is the kernel's existing answer for the motion.
- **His yes continues the film the same day** (ADR-FILM-CONTINUE). In PRODUCTION an APPROVED
  paid-media question, or an APPROVED take, queues one `FILM_CONTINUE` task that walks only that
  film through the same staircase, every purchase again behind `may_act`, its `plan_hash`, the
  lease and the budgets. Paid-media questions expire after `paid_media_approval_expires_hours`
  (48 h); every other question keeps 24 h.
- **Budgets before buying.** One buyer per film (`film_purchase_lease`), the step's cap reserved
  (`reserve_spend`, purpose `sheet:<step>`), and the film's own ceiling (`film_budget_usd`,
  `OVER_FILM_BUDGET`) are checked before the kernel is asked; they add refusals and loosen nothing.
- **The narration is not one of the four actions.** It is asked as `media.paid_generation`
  (T2, or `media.paid_generation_over_threshold`, T3, above `paid_generation_approval_threshold_usd`),
  bound to the sheet's `plan_hash` at step `assemble`, and the studio's mode decides whether it is
  asked, whatever the paid-media rule says. Whether the narration becomes a fifth paid step
  (`narration_purchase`) is the Owner's decision and is pending; this document does not decide it.
- **Only the Owner moves the rule.** The page shows what the next run will buy under his rule and
  mode (Guvernanță → «Mod de autonomie», and the sheet's own control) and asks a confirmation
  before a looser choice; nothing in the studio writes `paid_media_approval` or the environment.

Proven on fakes only: every vendor, the stills judge and clip QC were faked in the tests that
show this; no real paid film has yet climbed the staircase under MODE.

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

Amended 2026-10-08 (ADR-GPU-OFF-ALWAYS, 16_DECISION_LOG): «Oprirea GPU-ului nu este o acțiune
autonomă: nu cheltuie, doar oprește cheltuiala». `infra.gpu_off` (T0) — purging a RunPod queue,
cancelling its jobs, setting `workers.max` to 0 and verifying it is off — is answered ALLOWED by
`may_act` as its first check, before the stop, T4 and SAFE_MODE. The Owner's «Oprește GPU acum», the
GPU guard (at start, every minute while a GPU session is open, at shutdown) and the launcher's off
therefore work under STOP AUTONOMY; the guard is neither the watchdog nor a scheduled job, both of
which stay behind the stop. Switching the GPU ON (`infra.gpu_on`, T2) stays behind the stop, T4 and
SAFE_MODE, and is allowed only inside a paid media step the kernel already lets run.

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
