# Decision authority: who decides what, and where it is enforced

Scope: `backend/app` as found in the working tree on 2026-10-12 (branch `codex/simple-pixel-studio`,
HEAD `3d49e9a`, uncommitted `scripts/backend_map.py` and `docs/project/backend_map/`). Other
sessions may be editing code; line numbers are those of the tree as read. Read-only analysis: no
test, model, provider or network was called.

Companion files: `STATS.md` (counts), `inventory.json` (every function), `subsystems/*.md` (one
file per subsystem). This file is cross-cutting: it follows authority, not modules.

## 0. How to read this file

**DECIDED-BY** (used exactly):

| value | meaning |
|---|---|
| `LLM` | the model answer is acted on with only shape/schema validation |
| `LLM_CHECKED_BY_CODE` | the model proposes; code verifies content, clamps it, or can refuse it (the check is named) |
| `CODE_RULE` | deterministic rule, threshold, cap or state machine |
| `OWNER` | the human, through a decision card, a button (an Owner route) or a setting written by an Owner command |
| `CONFIG` | a static config file or `Settings` value (`.env`, `config/*.json`) |
| `EXTERNAL` | a provider or vendor result (RunPod status, YouTube API, a vendor balance, a fetched page) |

**TRUST** of an LLM answer: `FINAL` (acted on as is after schema validation), `CHECKED_BY_CODE`
(code verifies content and can refuse/clamp/override), `ADVISORY` (recorded or weighed; code or the
Owner has the final say), `INFORMATIONAL` (text with no control effect).

**Who "the Owner" is, in code.** Every router is mounted behind `require_owner`
(`backend/app/security.py:60`), which compares a bearer token with `Settings.owner_token`
(`backend/app/config.py:50`). The code cannot tell the human from any process holding that token;
on the Owner's own machine the page receives the token without a sign-in form
(`backend/app/local_session.py:1-21`, `STUDIO_LOCAL_AUTO_LOGIN`). Owner-only services add a
second, explicit check on an `issued_by` argument that only the Owner routes pass as `"owner"`:
`change_paid_media_approval` (`backend/app/services.py:1816-1835`) and `decide_owner_decision`
(`backend/app/decisions/services.py:1174-1192`).

**Agents hold no tools.** No provider adapter offers tool or function calling; a language model
only returns text (`backend/app/providers/base.py:58`, `generate`). Every side effect in the
studio is a code path that reads a model's structured answer, validates it, and then acts (or not).
Every model call goes through `app.agents.services.run_agent_task`
(`backend/app/agents/services.py:733`).

## 1. The short answer

1. **The Owner sets the boundaries and holds the money.** STOP AUTONOMY, the autonomy mode, TEST vs
   PRODUCTION, the paid-media rule, the USD budgets, the channel publish policies, accounts and
   credentials, card answers and approval answers are all Owner commands reachable only from Owner
   routes (section 3). T4 actions exist in the risk table only to be refused
   (`backend/app/services.py:518-525`, `1497-1503`); no agent code path asks for one (grep: no caller
   outside `app.services`).
2. **One deterministic Policy Kernel decides whether the studio may attempt an act.**
   `may_act` (`backend/app/services.py:1410-1633`) reads, in order: GPU-off always allowed, the
   unclassified check, STOP, T4, SAFE_MODE, GPU-on special case, the Owner's paid-media rule, the
   fail-closed budget rule, the mode ceiling, SUPERVISED approvals. It has no static path to a model
   (`inventory.json`: `llm_distance` null).
3. **Hard gates run after the kernel and decide on their own**: the publishing gate's seven checks
   (`backend/app/publishing/services.py:984-1400`), the factual gate (`backend/app/factual/services.py:470`),
   the money gates before every purchase (`backend/app/media/shooting_sheet.py:1876-1879`), the
   Owner-approved-take protection (`backend/app/media/assembler.py:16014`).
4. **The Director (an LLM persona, "she" in the code) decides production and quality alone**: the
   day's topic, script approval, the editorial verdict, every failed quality-control report, which
   defects are minor, her look at refused pictures, rewrite reviews, inbox and company decisions,
   self-repairs. In almost every case code bounds her answer (schemas bound to the report,
   allow-lists, "stricter but never looser" merges) and money still passes the kernel after her
   (section 7).
5. **How much is LLM.** 37 of 3951 functions (1%) are LLM call sites, holding 4% of function lines;
   151 functions (4%) and 18% of function lines have any static path to a model
   (`docs/project/backend_map/STATS.md`). The kernel (`app.services`), the decisions package, the
   publishing package and the budget module have none (`STATS.md` rows `app.services`,
   `app.decisions`, `app.publishing`: 0 functions reach a model). Of the 37 call sites, 22 are
   `CHECKED_BY_CODE`, 5 `FINAL`, 4 `ADVISORY`, 5 `INFORMATIONAL` and 1 reads only the run's
   status (section 12). In the authority matrix (section 11) no money, mode, stop, publication
   or account decision is taken by a model alone. (The map's reference tally, reconciled in
   `LLM_CALL_SITES.md` §6, is 24 `CHECKED_BY_CODE`, 5 `FINAL`, 5 `ADVISORY`, 3 `INFORMATIONAL`:
   `answer_mail` and `_probe` count as `CHECKED_BY_CODE`, `reconcile_day` as `ADVISORY`.)

## 2. The authority hierarchy as implemented

`docs/architecture/31_GOVERNANCE_APPROVAL_POLICY.md` ("Authority hierarchy"): Owner, Owner Policy
Kernel, hard gates, Director/CEO, delegated managers, employee agents.

| layer | what implements it | enforcement point |
|---|---|---|
| Owner | Owner commands behind `require_owner` (section 3) | `backend/app/security.py:60`; `issued_by` checks `backend/app/services.py:1832-1836`, `backend/app/decisions/services.py:1188-1192` |
| Policy Kernel | `may_act` (attempt permission), `_assert_policy_allows_run` + `may_run_agent` (model runs) | `backend/app/services.py:1410`; `backend/app/agents/services.py:608-680`, `781-831`; `backend/app/economy/accountant.py:1098` |
| Hard gates | publishing gate (7 checks), factual gate, rights gate, money gates, protected takes, prompt lint, stills gate / clip QC | `backend/app/publishing/services.py:984`; `backend/app/factual/services.py:470`; `backend/app/media/shooting_sheet.py:1876`; `backend/app/media/assembler.py:16014` |
| Director | LLM call sites with role "Director" (topic, reviews, QC decisions, looks, briefs, loop, repairs) | sections 7 and 12 |
| Managers | not implemented as a separate layer; the Director assigns work to roles (`ASSIGNABLE`) | `backend/app/agents/command.py:94-134` |
| Employees | LLM call sites of other roles (Lead Researcher, Fact Checker, Script Writer, Video Editor, Voice Artist, Publisher, Accountant) | section 12 |

"No lower layer can grant itself authority above a higher one": a caller's tier is raised to the
table's tier when the action is known (`backend/app/services.py:1459-1463`); an approval only turns
"would be asked" into "allowed once" and is read after STOP, T4 and SAFE_MODE
(`backend/app/services.py:1491-1510`, `1284-1323`). See section 13 for the cases the table does not
know.

## 3. The Owner's commands

| decision | command (service) | route | idempotent / versioned / ledger |
|---|---|---|---|
| STOP AUTONOMY on/off | `change_stop` `backend/app/services.py:382` | `POST /api/v1/owner/autonomy-stop` `backend/app/main.py:952` | yes / `expected_version` / `autonomy.stopped`, `autonomy.stop_cleared` |
| autonomy mode | `change_autonomy_mode` `backend/app/services.py:1636` | `POST /api/v1/owner/autonomy-mode` `backend/app/main.py:888` | yes / yes / `owner.autonomy_mode_changed` |
| TEST / PRODUCTION | `change_environment` `backend/app/services.py:244` | `POST /api/v1/owner/environment` `backend/app/main.py:876` | yes / yes / `owner.environment_changed` |
| paid-media rule | `change_paid_media_approval` `backend/app/services.py:1816` | `POST /api/v1/owner/paid-media-approval` `backend/app/main.py:903` | yes / yes / `owner.paid_media_approval_changed`; refuses any `issued_by` other than `"owner"` |
| answer an approval | `decide_approval` `backend/app/services.py:937` | `POST /api/v1/owner/approvals/decision` `backend/app/main.py:933` | yes / one answer per request / `governance.approval_decided` |
| answer a decision card | `decide_owner_decision` `backend/app/decisions/services.py:1174` | `POST /api/v1/owner/decisions/{id}/decide` `backend/app/decisions/router.py:39` | yes / card `version` / `owner.decision_decided` |
| USD budget (DAILY / MONTHLY) | `set_budget` `backend/app/economy/budget.py:150` | `PUT /api/v1/economy/budget` `backend/app/economy/router.py:70` | yes / per-period version / `economy.budget_*` |
| start the daily clock | `set_job_active` `backend/app/workflows/services.py:748` | `POST /api/v1/scheduler/jobs/{id}/active` `backend/app/workflows/router.py:147` | event `workflow.job_activated` |
| run today now ("GO", «Pornește rularea de azi») | `start_daily_run` `backend/app/runbook/services.py:1291` | `POST /api/v1/runbook/runs` `backend/app/runbook/router.py:80` | idempotency key `manual-run-{command_id}` |
| leave safe mode | `clear_safe_mode` `backend/app/runbook/services.py:708` | `POST /api/v1/runbook/safe-mode/clear` `backend/app/runbook/router.py:223` | note required; the stop stays on |
| «Oprește GPU acum» | `set_owner_hold` + `force_off` | `POST /api/v1/runpod/gpu/off` `backend/app/providers/runpod/router.py:66-118` | idempotent by `command_id` |
| channel publish policy (visibility, `public_publish_enabled`, `director_may_approve_episodes`) | `change_publish_policy` `backend/app/publishing/services.py:352` | `POST /api/v1/publishing/channels/{id}/publish-policy` `backend/app/publishing/router.py:204` | versioned |
| workforce suspend / terminate | `decide_proposal` `backend/app/workforce/services.py:270` | `POST /api/v1/workforce/proposals/{id}/decide` `backend/app/workforce/router.py:79` | event `workforce.change_*` |
| an agent's model | `assign_agent` | `PUT /api/v1/settings/agents/{id}/model` `backend/app/integrations/router.py:413` | event |
| a film: paid step press, scene model, redo, take look, close | sheet and take routes | `backend/app/media/router.py:883` (steps), `946` (scene model), `1010` (redo), `1067` (take decision), `860` (close) | each with its own gates |
| research hosts | allow-list rows | `PUT /api/v1/factual/sources/allowed-hosts/{host}` `backend/app/factual/router.py:160` | merged with `STUDIO_RESEARCH_ALLOWED_HOSTS` (`backend/app/research/service.py:130-138`) |

Two Owner acts are not routes: the restore guard, run by the Owner's restore script, sets STOP,
TEST and turns `daily_main` off (`backend/app/services.py:321-379`); and `.env` settings (CONFIG),
read at process start.

Callers of the policy commands, by grep: only the routes above and the card appliers in
`backend/app/decisions/services.py:318, 353, 382, 392`, which run only inside
`decide_owner_decision` with `issued_by="owner"`.

## 4. Autonomy modes, STOP, SAFE_MODE, environment

### 4.1 The state

`owner_policy` (`backend/app/models.py:35-68`): `autonomy_stopped`, `environment` (TEST/PRODUCTION),
`autonomy_mode` (MANUAL / SUPERVISED / AUTONOMOUS_CEO, `backend/app/schemas.py:10,13`),
`paid_media_approval` (EVERY_PAID_STEP / OVER_USD / MODE, `backend/app/models.py:31`) and its
threshold. A fresh install starts MANUAL and stopped (`NEW_STUDIO_AUTONOMY_MODE`,
`backend/app/services.py:94`; `autonomy_stopped=True` at `118`); the column's server default is
still AUTONOMOUS_CEO (`backend/app/models.py:55-57`) and so is the view default
(`backend/app/schemas.py:62`). No other mode exists; a per-department mode is not implemented
(`docs/architecture/51_AUTONOMY_MODE_SEMANTICS.md`, "V4 department autonomy").

### 4.2 The risk tiers and the ceiling per mode

`ACTION_RISK_TIERS` (`backend/app/services.py:467-526`), `MODE_ALLOWS = {"MANUAL": "T1",
"SUPERVISED": "T2", "AUTONOMOUS_CEO": "T3"}` (`:528`), `SAFE_MODE_ALLOWS = "T1"` (`:532`).

| tier | actions in the table | asked by a caller? |
|---|---|---|
| T0 | `analytics.read`, `provider.health_read`, `research.search_public`, `memory.read`, `infra.gpu_off` | `analytics.read` (stage, `backend/app/runbook/stages.py:257`; repair `diagnose_agent`) |
| T1 | `idea.create`, `script.draft`, `storyboard.draft`, `task.reprioritise`, `benchmark.run` | the day's stages (`backend/app/runbook/stages.py:256-268`); `agent.run` (not in the table, caller tier T1, `backend/app/agents/services.py:630`) |
| T2 | `agent.change_model`, `agent.change_prompt`, `agent.hire`, `agent.suspend`, `office.room_draft`, `research.fetch_page`, `media.paid_generation`, `media.stills_purchase`, `media.character_reference_set`, `infra.gpu_on` | `research.fetch_page` (`stages.py:259,559`), `media.paid_generation` (`stages.py:263,2643,3329`), `media.stills_purchase` (`backend/app/media/stills_stage.py:1744`), `agent.change_model` (repair), `infra.gpu_on` (`backend/app/providers/runpod/gpu_session.py:829-842`) |
| T3 | `publishing.public_publish`, `media.paid_generation_over_threshold`, `agent.fire`, `provider.activate`, `story.public_world_change`, `media.test_shot`, `media.motion_purchase`, `media.scene_redo` | publish (`stages.py:5845-5856`, `backend/app/publishing/licence_release.py:298`), paid steps (`backend/app/media/assembler.py:9970`, `11605`, `15987`), narration over threshold (`backend/app/media/shooting_sheet.py:198`); `agent.fire`, `provider.activate`, `story.public_world_change`: no caller found |
| T4 | `budget.change_hard_limit`, `policy.change_kernel`, `credential.reveal`, `credential.rotate`, `legal.accept_terms`, `audit.disable` | none; refused `BLOCKED_OWNER_ONLY` in every mode (`services.py:1497-1503`) |

### 4.3 What each mode lets agents do alone

| | MANUAL (T1) | SUPERVISED (T2) | AUTONOMOUS_CEO (T3) |
|---|---|---|---|
| model runs (`agent.run`, T1) | yes | yes | yes |
| ideas, selection, scripts, storyboards, QC measurement, Director's QC decision, post-run review | yes | yes | yes |
| fetch research pages (`research_and_verification` stage, T2) | stage SKIPPED (`stages.py:6360-6372`) | yes | yes |
| the day's `media` stage (T2) | SKIPPED | runs; each paid step then meets the paid-media rule | runs; idem |
| stills (T2) under rule MODE | `BLOCKED_MODE` | allowed (PRODUCTION needs a DAILY budget) | allowed (idem) |
| test shot / motion / redo (T3) under rule MODE | `BLOCKED_MODE` | approval request | allowed (idem) |
| any paid step under EVERY_PAID_STEP (default) | approval request (rule read before the mode, `services.py:1520-1577`) | approval request | approval request, except a step whose cap is exactly 0 |
| narration (`media.paid_generation`, T2; over `paid_generation_approval_threshold_usd` T3) | refused | T2 unasked, T3 asked | unasked |
| publish (T3) | SKIPPED | stage runs; one approval per film (`stages.py:5845-5876`) | unasked, within the channel policy and the gates |
| Director repairs T0/T1 | yes | yes | yes |
| Director repair `switch_agent_model` (T2) | refused, one Owner card | yes | yes |
| GPU on | only inside a step the kernel already lets run, or the Owner's own press (`services.py:1352-1407`) | idem | idem |
| T4 | never | never | never |

The stage wrapper asks the mode with `ask_owner=False` and records a refused stage SKIPPED, not
BLOCKED (`backend/app/runbook/stages.py:6347-6372`, `mode_refusal` at `271-316`); a SUPERVISED T3
answers "would be asked", which the wrapper treats as no refusal so that the stage that knows the
film asks per film (`stages.py:313-316`).

### 4.4 Promotion, lowering, STOP and SAFE_MODE

- **Promotion** is refused while STOP is on or safe mode is open (`backend/app/services.py:1670-1688`);
  acceptance criteria and burn-in are not checked and the refusal says so (`:1643-1651`).
  **Lowering** is always allowed (`:1670`). A paid step in flight re-reads the kernel before each
  vendor request (`PurchaseGuard`, `backend/app/media/mode_guard.py:155-230`; incident of 2026-10-04,
  `mode_guard.py:3-9`).
- **STOP** is read by: `may_act` (`services.py:1491`), the run gate (`backend/app/agents/services.py:618-621`),
  `scheduler_tick` (`backend/app/workflows/services.py:814`), `claim_task` (`:366`, `:376`), the
  publishing gate 1 (`backend/app/publishing/services.py:1022-1026`), `start_daily_run`
  (`backend/app/runbook/services.py:1313-1319`), the runbook between stages (`runbook/services.py:1490`,
  `1547`), the Director's loop (`backend/app/agents/command.py:881-886`), the watchdog
  (`backend/app/workflows/watchdog.py:822`, and before each pass `:643-648`, unreadable = pressed).
  Only `infra.gpu_off` passes it (`services.py:1479-1482`).
- **SAFE_MODE** is opened by code only, for a HARD fault in `media`, `publish` or `daily_log`, or a
  database integrity doubt (`SAFE_MODE_STAGES`, `backend/app/runbook/services.py:150-159`;
  `1749-1757`, `1868-1881`). Opening it also sets STOP (`:684-688`). Leaving it is the Owner's,
  with a note, and STOP stays on (`:708-745`). Under safe mode the kernel allows T0-T1 only
  (`services.py:1505-1510`).

### 4.5 Environment

PRODUCTION is the only environment that buys from real vendors on the unasked path:
`continue_film` skips in TEST (`backend/app/runbook/stages.py:5486-5492`), `queue_film_continue`
queues nothing in TEST (`backend/app/services.py:657-659`), the film ceiling applies in PRODUCTION
only (`backend/app/media/shooting_sheet.py:2693-2694`), the render button refuses in PRODUCTION
(`backend/app/media/router.py:546-553`). TEST caps per generation and per second are CONFIG
(`backend/app/config.py:335-336`). The environment is read only from the policy row, never from a
request (`backend/app/services.py:232-241`).

## 5. The Policy Kernel

### 5.1 `may_act` (attempt permission)

`backend/app/services.py:1410-1633`. Verdict shape: action, tier, mode, allowed, status, reason,
approval_id (`:1465-1473`). Order:

1. Tier resolution: table tier, raised by the caller's when both exist; otherwise whichever exists
   (`:1459-1463`).
2. `infra.gpu_off` → ALLOWED before anything (`:1479-1482`).
3. No tier → `BLOCKED_UNCLASSIFIED` (`:1484-1489`).
4. STOP (or no policy row) → `BLOCKED_STOP` (`:1491-1495`).
5. T4 → `BLOCKED_OWNER_ONLY` (`:1497-1503`).
6. Safe mode and tier above T1 → `BLOCKED_SAFE_MODE` (`:1505-1510`).
7. `infra.gpu_on` → `_gpu_on_verdict` (`:1512-1518`, `1352-1407`): only with `step_action` one of
   the four paid steps, the Owner's RunPod card accepted (`allow_infra_actions`,
   `_runpod_infra_allowed` `:1339-1349`), and that step itself allowed, or answered yes for the same
   plan, or the Owner's own press.
8. Paid steps (`PAID_MEDIA_STEPS`: stills, test shot, motion, scene redo, `:606-611`):
   no `plan_hash` → `BLOCKED_NO_PLAN` (`:1520-1532`); then the Owner's rule
   (`paid_media_policy`, unreadable = strictest, `:1212-1231`):
   - cap exactly 0 under AUTONOMOUS_CEO → the rule is skipped (`:1535-1545`; the Owner's
     2026-10-05 rule, «pe CEO autonom îmi cere acordul doar dacă generează cu bani»);
   - EVERY_PAID_STEP → ask; OVER_USD → ask above the threshold or when the cost is unknown
     (`:1545-1560`); `cost_usd` is the step's cap, not its estimate (`:1555-1557`);
   - when the rule asks: `_ask_or_spend` (`:1284-1323`): a standing refusal refuses, a standing yes
     is spent now (before the act), otherwise one approval request is written (`:1561-1577`);
   - when the rule would let it through: in PRODUCTION with no active DAILY budget →
     `BLOCKED_NO_BUDGET` (`:1583-1595`, fail closed; free steps exempt).
9. Mode ceiling → ALLOWED (`:1597-1598`).
10. SUPERVISED and T3 → approval (ask or spend) (`:1600-1626`).
11. Otherwise `BLOCKED_MODE` (`:1628-1633`).

### 5.2 The model-run gate in `run_agent_task`

`backend/app/agents/services.py:733-1000`.

| check | decides | where |
|---|---|---|
| daily token ceiling (`agent_daily_token_budget`, default 0 = none) | CONFIG + CODE_RULE | `backend/app/economy/accountant.py:1098-1160`; `backend/app/config.py:419` |
| an active USD budget already exceeded refuses every run except the Accountant's close | OWNER (budget) + CODE_RULE | `accountant.py:1037` (`BUDGET_EXEMPT_TASKS`), `1123-1125`, `1040-1095` |
| STOP | OWNER | `agents/services.py:618-621` |
| `may_act("agent.run", "T1")` (mode, safe mode) | CODE_RULE | `:623-632` |
| agent lifecycle ACTIVE | OWNER (pause / workforce) | `:634-639` |
| model available and verified (slot model checked too) | CODE_RULE + OWNER (model choice) | `:641-648`, `817-825` |
| one live run per agent; stale THINKING cleared | CODE_RULE | `:649-668`, `566-590` |
| role's REQUIRED capabilities | CODE_RULE | `:670-671`, `520-560` |
| provider health | EXTERNAL | `:673-679` |
| Director's output allowance x `director_token_multiplier` (default 2) | CONFIG | `:793-797`; `backend/app/config.py:425` |

A blocked run is recorded as an `AgentRun` with the `BLOCKED_*` status, not raised
(`agents/services.py:832-855`). A provider 401/402/403 proposes a reconnect card
(`:1025-1027`, `backend/app/decisions/sources.py:799`).

### 5.3 Approvals: ask, answer, spend

- Request: one per action and subject, reused while its `proposed_diff` is unchanged; a moved
  context closes the old one (`backend/app/services.py:731-761`, `1031-1100`).
- Expiry: 48 h for a film's paid step and the sheet's narration, 24 h otherwise (CONFIG,
  `backend/app/services.py:555-583`; `backend/app/config.py:401,408`).
- Answer: only PENDING and unexpired, once (`backend/app/services.py:937-1028`). A yes on a paid
  step queues `FILM_CONTINUE` in the same transaction (PRODUCTION only, `:985-1001`, `645-689`).
- Spend: in `_ask_or_spend` only, before the act (`:1306-1310`, `811-835`); bound to the context
  (`_context_matches`, `:715-728`: the sheet's `plan_hash` for paid steps, the channel and policy
  version for uploads).

### 5.4 Other permission checks outside `may_act`

| check | decides | where |
|---|---|---|
| purchase lease: one buyer per film | CODE_RULE | `backend/app/media/shooting_sheet.py:2048` |
| vendor balance must hold the next round x margin (1.15) | EXTERNAL + CONFIG | `backend/app/media/balance_rule.py:39,52`; `backend/app/media/stills_stage.py:1729-1741`; `backend/app/config.py:286` |
| film ceiling (`film_budget_usd`, default motion budget + stills cap) | CONFIG + CODE_RULE; Owner consent may exceed | `shooting_sheet.py:2632-2724` |
| hold the step's cap against the budgets | OWNER (budget) + CODE_RULE | `shooting_sheet.py:2726-2781`; `backend/app/economy/budget.py:473-533` |
| PurchaseGuard before each vendor request | CODE_RULE | `backend/app/media/mode_guard.py:80-95`, `155-230` |
| hero gate: clip QC may accept the hero only when the motion step would be allowed unasked | CODE_RULE (+ LLM vision via clip QC) | `backend/app/media/assembler.py:9917-9990` |
| GPU precheck and open: Owner hold, configuration, bucket, RunPod card, weights, kernel, one-GPU rule, RunPod switch | OWNER + CODE_RULE + EXTERNAL | `backend/app/providers/runpod/gpu_session.py:701-743`, `890-1000` |
| paid attempts per scene since the Owner last decided (3) | CONFIG | `backend/app/config.py:294`; `stills_stage.py:62-66` |
| Owner-approved takes are never retired by an unasked redo | CODE_RULE | `backend/app/media/assembler.py:16014`, `12973` |
| publishing gate (7 checks) | CODE_RULE | `backend/app/publishing/services.py:984-1400` |

## 6. Money

### 6.1 The order of gates before a film's purchase

`backend/app/media/shooting_sheet.py:1876-1879`: purchase lease, vendor balance, film ceiling
(PRODUCTION), a reservation of the step's cap against every active budget, then `may_act` (the
Owner's rule, the mode, `BLOCKED_NO_BUDGET`). Each gate only adds refusals.

### 6.2 Budgets and reservations

- `SpendingBudget`, one active per period (DAILY, MONTHLY), set only by `set_budget`
  (`backend/app/economy/budget.py:150-198`), from the Owner route or the `budget` card applier
  (`backend/app/decisions/services.py:298-326`).
- `reserve_spend` decides behind the write lock; with no budget it refuses nothing; `force` is the
  Owner's sheet consent (`allow_over_budget`) and is recorded (`budget.py:473-533`;
  `shooting_sheet.py:2758-2781`; route field `backend/app/media/router.py:207`).
- Holds older than `reservation_ttl_seconds` (6 h) are released by the watchdog
  (`budget.py:597-632`; `backend/app/config.py:380`).
- No budget means "no limit" for `reserve_spend`; that is why the kernel refuses unasked buying in
  PRODUCTION without a DAILY budget (`backend/app/services.py:1583-1595`) and why the paid-step
  rule defaults to EVERY_PAID_STEP (`backend/app/models.py:31`, `services.py:614`).

### 6.3 Model spending

The token ceiling and the exceeded-USD refusal (section 5.2) are the only limits on LLM spend; the
USD figure counts `agent_run.cost_vr` (`backend/app/economy/budget.py:276-291`); a run with no
stored price is reported as unpriced, not as zero (`budget.py:1-11`). Model runs never pass
`may_act` beyond the T1 `agent.run` check.

### 6.4 The paid-redo cap and its card

- Limits: `film_max_paid_redos_per_scene` 5 and `film_max_paid_redos` 20 (CONFIG, bounded at
  those values, `backend/app/config.py:314-315`), plus the Owner's allowances
  (`redo_allowance`, `backend/app/decisions/producers/redo_cap.py:64-79`).
- Applied in `_apply_repairs` (`backend/app/runbook/stages.py:4966-4968`); a round counts only when
  it produced a picture inside its own window (ADR-REDO-ROUNDS-BY-PICTURES,
  `docs/project/16_DECISION_LOG.md:3-9`).
- When the cap alone stopped the Director's REPAIR and nothing else could be done, one card per
  film: `redo_cap_reached` (`stages.py:5174-5185`; `redo_cap.py:104-228`). Options: allow 5 more
  (`EXTRA_REDOS`, `:50`; applier `:241`), publish as it is (writes the PASSED report with
  `decided_by` owner, `:288`), close the film (`:340`), wait. The card closes itself when the count
  read again is below the cap (`:379-455`).
- Free fixes (card, audio, encode) have no count of their own: once per failed film
  (`backend/app/agents/reviews.py:737-741`).

### 6.5 "Free local steps never ask"

A paid step whose cap is exactly 0 (the local ComfyUI selection) skips the Owner's rule and the
no-budget refusal under AUTONOMOUS_CEO only; under MANUAL and SUPERVISED it is asked like any paid
step (`backend/app/services.py:1535-1545`, `1583-1586`).

### 6.6 The GPU

- Off: always allowed, under STOP too (`services.py:1479-1482`; route
  `backend/app/providers/runpod/router.py:66`; the guard `backend/app/main.py:430-470`).
- On: only inside a paid step the kernel already lets run, after the Owner accepted the
  `runpod_infra_actions` card (`services.py:1339-1407`; applier
  `backend/app/decisions/sources.py:1180-1233`).
- **The Owner's hold** (2026-10-12): «Oprește GPU acum» records `runpod.owner_hold {on: true}`
  before switching off (`backend/app/providers/runpod/router.py:87-99`). `precheck` and
  `open_session` refuse `OWNER_HOLD` while it stands (`gpu_session.py:723`, `926`); an unreadable
  hold reads as held (`:775-792`). Only the Owner's answer «Permite din nou» on the
  `gpu_owner_hold` card lifts it (`backend/app/decisions/producers/gpu_hold.py:85-92`); the card
  has no other option and closes itself when the newest record says off (`:95-108`).
- The Owner's per-connection switch «RunPod pornit» is read again under the endpoint lock before
  switching on (`gpu_session.py:972-986`).

### 6.7 Spend authorised by a card alone

The `runpod_mirror_copy` card's accept starts a temporary RunPod pod
(`backend/app/decisions/sources.py:1236-1260`), bounded by the card's own `max_usd` and minutes
(`backend/app/providers/runpod/pods.py:496-500`); it passes neither `may_act` nor `reserve_spend`
(grep: no call in `pods.py`).

## 7. The Director's authority

### 7.1 What she decides alone

| decision | DECIDED-BY | what code still does | where |
|---|---|---|---|
| the day's topic | LLM_CHECKED_BY_CODE | shortlist = topics with at least one SUPPORTED claim, computed by code; an id outside it is refused; one candidate or no model = deterministic order; `select_topic` still refuses a non-producible topic | `backend/app/agents/director.py:195-254`; `backend/app/runbook/stages.py:756-830`; `backend/app/factual/services.py:113` |
| script approval (her story-review PASS is the approval) | LLM_CHECKED_BY_CODE | computed story checks decide alone; her opinion can only make a verdict stricter, once per story; grounding and the factual gate re-checked at approval | `backend/app/factual/story_review.py:400-470`; `stages.py:929-975`; `factual/services.py:470` |
| editorial judgement: rewrite or ship | LLM scores + CODE_RULE bar (35/50, no criterion below 5); up to `editorial_rounds` (10) versions; the best-scored version ships regardless | `backend/app/agents/editorial_judgement.py:88-89`, `278-281`, `640`; `backend/app/config.py:434` |
| viewing verdict before publication | LLM (FINAL), after code hard rejects (no source, wrong language, under 40 words) | REJECT closes the storyboard; APPROVE only lets the film reach the publishing gate | `backend/app/agents/editorial.py:420-426`, `518-521`; `stages.py:5729-5737` |
| serial episode approval | LLM_CHECKED_BY_CODE + OWNER grant | the computed episode checks first; a PASS with any of her six scores below 3 is a FAIL; approval only if the OFFICE_SERIAL channel's `director_may_approve_episodes` is set by the Owner | `backend/app/story/review.py:30-40`, `221-233`, `946` |
| a failed QC report: ACCEPT or REPAIR | LLM_CHECKED_BY_CODE | schema bound to the report (every finding judged, none invented, scenes exist); REAL forbids ACCEPT; minor must be ACCEPTED; cause and lesson required; CLOSE refused ("never closed for quality"); a REPAIR must list a redo that can be carried out (paid redos left, not an Owner-final take, not motion against LOCAL_MOVE, free fix once); scenes `passed_before_unchanged` are never REAL nor redone | `backend/app/agents/reviews.py:605-709`, `711-778`, `781-845`, `848-905`; `backend/app/runbook/stages.py:4041-4120`, `4442-4520` |
| accepting minor defects | LLM within schema rules | the ACCEPT writes a PASSED report at the publishing minimum score | `reviews.py:689-705`; `backend/app/media/director_qc.py:1678-1735` |
| her look at candidates a gate refused | LLM (FINAL) | index bound to what was shown; approved as `director`, never as the Owner; the Owner's later look replaces hers | `reviews.py:1091-1127`, `1148`; `director_qc.py:137`, `2069-2090` |
| rewrite brief and review before a paid redo | LLM_CHECKED_BY_CODE; her MISSES is a veto | the rewrite is linted; MISSES stores and buys nothing; a paid redo is bought only on a corrected prompt | `backend/app/media/scene_rewrite.py:227-252`, `837`, `1067`, `1279`; `stages.py:4734` |
| her inbox (acknowledge, investigate, approve, reject, escalate) | LLM_CHECKED_BY_CODE | unknown ids dropped; ESCALATE_TO_OWNER downgraded to ACKNOWLEDGE unless the matter is an account, credential, security, legal, licence or a thread the Owner opened; investigating an investigation becomes ACKNOWLEDGE | `backend/app/agents/director.py:91-122`, `345-470` |
| a Publisher HOLD | LLM via her inbox | any resolution of the HOLD letter other than an investigation or an escalation (APPROVE, REJECT, ACKNOWLEDGE all write RESOLVED) lifts it; the title is re-checked | `director.py:451-465`; `reviews.py:1717-1750` (`:1744`); `stages.py:5772-5791` |
| the company loop: assignments, escalations, repairs | LLM_CHECKED_BY_CODE | choices limited to computed matters; at most 3 assignments and 6 repairs; STOP/SCALE and a matter assigned 3 times go to the Owner; with no model the measured order is followed | `backend/app/agents/command.py:152-170`, `866-1066`, `1083-1170` |
| self-repairs | LLM choice, kernel decides | section 9 | `backend/app/agents/repairs/desk.py:284-575` |
| retire a film that stood still `film_wait_days` (3) | CODE_RULE, in her name | never a film with a pending Owner question | `stages.py:2204-2240`; `backend/app/config.py:303` |

### 7.2 What code still gates after her

- **Not hers to accept away**: `rights_qc`, `factual_qc`, `content_source_qc`,
  `production_path_qc`, file/provenance faults, music-licence findings
  (`backend/app/media/director_qc.py:147-205`); an ACCEPT that meets any such finding is recorded
  `ACCEPT_REFUSED` (`backend/app/runbook/stages.py:4466-4475`). `not_yours` comes from the report,
  not from her answer (`director_qc.py:1003-1030`).
- **Publishing gate** after her APPROVE: STOP, file on disk and digest, QC PASSED with score at
  least 0.90, factual claims SUPPORTED, no duplicate, policy authorisation for anything visible,
  rights for anything visible (`backend/app/publishing/services.py:166`, `1022-1400`). A film
  whose licence is not proven goes up private (`stages.py:5745-5755`).
- **The mode** after the gate: `publishing.public_publish` (T3) is asked per film
  (`stages.py:5845-5876`).
- **Money**: every paid redo she lists is bought only through `redo_scene`, inside which the
  gates of section 6.1 and `may_act("media.scene_redo")` apply (`stages.py:4957-4968`;
  `backend/app/media/assembler.py:15955-16020`).
- **The Owner's takes**: a take the Owner approved as final is never redone; one approved without
  "final" is replaced only by her confirmed repair and the Owner is told (`stages.py:4912-4914`;
  `reviews.py:757-759`).
- **The stills gate and clip QC** judge what her repair bought (`backend/app/media/stills_stage.py:1-80`);
  only her own look can overrule them for candidates bought for her repair (7.1).

### 7.3 What she cannot do

Write a budget, a price, the paid-media rule, the mode, the environment or the stop; answer a card
or an approval; change a channel's publish policy; suspend or terminate an employee; reveal or
rotate a credential; accept terms; start a day (section 8). Enforcement: these are reachable only
through the Owner routes of section 3; the repair and watchdog-pass registries are scanned by tests
for Owner and money calls (`backend/app/agents/repairs/__init__.py:40-47`;
`backend/app/workflows/passes/__init__.py:25-36`; `backend/app/decisions/producers/__init__.py:34-56`).
Her letters to the Owner are limited to accounts, authorisations, security and legal matters
(`backend/app/agents/director.py:84-122`).

## 8. Starting, stopping, restarting

### 8.1 Who may start work

Every creator of a `DAILY_RUN` task (grep `DAILY_RUN_TASK`):

| creator | decided by | where |
|---|---|---|
| the scheduler fires `daily_main` at `daily_run_hour_local` (05:00, studio time zone) | OWNER activates the job (seeded dormant); CONFIG the hour | seed `backend/app/main.py:475-487`; activation `backend/app/workflows/services.py:748-788`; tick `:791-830`; `backend/app/config.py:464` |
| «Pornește rularea de azi» (GO) | OWNER | `backend/app/runbook/router.py:80-93`; `backend/app/runbook/services.py:1291-1342` (refuses under safe mode, STOP, worker off, a pending run) |
| retry of a day that could not run (up to `daily_max_attempts`, after `daily_retry_seconds`) | CODE_RULE | `backend/app/workflows/worker.py:291-321` |
| resume of a day cut off by a restart | CODE_RULE | `backend/app/workflows/passes/resume_interrupted_day.py:40-80` (not under STOP or safe mode, not when a day task is pending) |

The clock does one successful day per business date; a manual run repeats a day by design
(`backend/app/workflows/worker.py:174-177`; module docstring `:1-19`). No Director code path
enqueues a `DAILY_RUN` (the creators above are the only ones).

Continuations of films already started (not new days): `FILM_CONTINUE` after the Owner's yes or
take approval (`backend/app/services.py:645-689`), the Director QC review pass, the ladder retry,
the owner-choice continuation, the serial filming pass (`backend/app/workflows/passes/*.py`).

Always-on scheduled jobs (seeded active, all behind STOP through `scheduler_tick`): watchdog,
weekly review, trends, model research (not in demo), model review, the Director's loop every 6 h,
backup (`backend/app/main.py:491-575`). The Owner can also run the Director's loop now
(`POST /api/v1/runbook/direct`, `backend/app/runbook/router.py:156-174`), which still returns
SKIPPED under STOP (`backend/app/agents/command.py:881-886`).

### 8.2 Stopping

STOP (section 4.4), safe mode (4.4), lowering the mode (PurchaseGuard), the GPU off and the Owner's
hold (6.6), the RunPod switch, `«Închide filmul»` for one film (`backend/app/media/router.py:860`;
`backend/app/media/film_close.py:526`), and pausing an agent (`backend/app/agents/router.py:319`).

### 8.3 Restarting

No function in `backend/app` restarts the process. A shutdown request ends the day at its stage
boundary as INTERRUPTED (`backend/app/runbook/services.py:364-380`); the resume pass continues it
after the next start (8.1). The restart itself is the developer's script `scripts/restart.py`
(outside the backend; `scripts/restart.py:1-25`). The Director cannot restart the studio, and no
code-modification capability exists in `backend/app` (grep: no `subprocess` use in `app.agents`
except ffmpeg frame extraction in `editorial.py` and `vision.py`).

## 9. The self-repair desk

`backend/app/agents/repairs/__init__.py:1-60` (rules), `desk.py:1-25` (flow).

| repair | tier | kernel action | effect | module |
|---|---|---|---|---|
| `diagnose_agent` | T0 | `analytics.read` | diagnosis only, a STATUS letter | `backend/app/agents/repairs/agent_health.py:750` |
| `switch_agent_model` | T2 | `agent.change_model` | moves an employee whose current model fails now (probe first) to a verified, priced, role-capable, non-denied, non-Anthropic model; one switch per employee per day, then an Owner card | `agent_health.py:83`, `601-700`, `764` |
| `reprice_unpriced_runs` | T1 | `economy.apply_active_price` | applies the price already active to runs stored without cost; a budget it would exceed becomes an Owner card | `backend/app/agents/repairs/reprice.py:478-516`, `518` |
| `film_cost_report` | T1 | `director.close_review` | per-film cost from the books | `backend/app/agents/repairs/film_cost.py:312` |
| `close_stale_decisions` | T1 | `director.close_decisions` | closes decisions whose work is over | `backend/app/agents/repairs/stale_decisions.py:202` |
| `close_thread` | T1 | `director.close_thread` | closes a looping thread | `backend/app/agents/repairs/threads.py:361` |
| `unbilled_estimates` | T1 | `director.ask_for_invoices` | an invoice card for the Owner | `backend/app/agents/repairs/unbilled.py:354` |

Boundaries in code:

- The kernel is asked twice, with the repair's own action and tier: when she chooses
  (`desk.py:316-332`, nothing written if refused) and when the worker applies
  (`desk.py:555-571`). T4 cannot be declared (`REPAIR_TIERS`, `__init__.py:68`).
- A refused repair becomes one card `director_repair_blocked`, quiet 7 days after an answer
  (`desk.py:443-511`, `80`). A matter repaired 3 times in 24 h goes to the Owner
  (`command.py:986-1002`).
- Repairs up to T2 that her choice left out are queued anyway in the measurements' order
  (`UNASKED_TIERS`, `command.py:170`, `945-956`).
- Rules (not code-enforced at run time, enforced by test scans): never buys, approves or moves
  money; never writes a price, budget, ledger, credential or the Owner's policy; never decides a
  card (`__init__.py:40-47`).
- Statically, `execute_repair` has no path to a model (`inventory.json`, `llm_distance` null):
  the repair functions are called through the registry object. `switch_agent_model`'s probe is an
  LLM call site (`agent_health.py:568`).
- Level 2 (code repairs) is not implemented: a tool defect she names is filed as a
  `developer_defect` note to herself, resolved at once (`backend/app/agents/director.py:107`,
  `125-157`).

Watchdog passes follow the same rules (`backend/app/workflows/passes/__init__.py:25-44`) and stop
when STOP is pressed (`backend/app/workflows/watchdog.py:643-670`).

## 10. Owner decision cards

### 10.1 Model and lifecycle

`OwnerDecision` (`backend/app/decisions/models.py:23-85`): PENDING, ACCEPTED, REFUSED,
WAITING_FOR_OWNER_ACTION, WITHDRAWN, EXPIRED; one open card per `dedupe_key`
(`:40-45`). Anyone proposes (`propose_owner_decision`, `backend/app/decisions/services.py:826`;
a proposal writes no ledger event and grants nothing); only the Owner decides
(`:1174-1192`, route `backend/app/decisions/router.py:39-61`). ACCEPT runs the option's applier
(`APPLIERS`, `:438-453`, plus registered producers) under an inner command id derived from card,
version and option; a failed apply leaves the card PENDING with the reason. A guided option waits
for the Owner's own act; «Am făcut-o» closes it only when its condition reads true. Conditions
(`CONDITIONS`, `:604-627`) are read by `refresh_owner_decisions` (`:961`) on start
(`backend/app/main.py:307-308`) and whenever the window is read (`:1577`). A producer's refused
card is not re-proposed for 7 days (`backend/app/decisions/sources.py:60`, `149-180`). The window
also shows pending paid-step approvals and letters that ask something
(`owner_decision_cards`, `:1560`; `_approval_card` `:1403`; `_letter_card` `:1478`).

### 10.2 Every card kind

| kind | proposed by (file:line) | trigger | options and what each does | closes when |
|---|---|---|---|---|
| `daily_budget` (audit) | `backend/app/decisions/seed.py:185-258` | no adequate DAILY budget at start | set the computed budget (`budget` applier) / keep | daily budget at least the figure |
| `daily_budget` (film) | `backend/app/decisions/sources.py:579-674`, from `backend/app/runbook/stages.py:2399-2430` | a paid step refused `OVER_DAILY_BUDGET` or `BLOCKED_NO_BUDGET` | raise to the figure the film needs (`budget`) / keep | `daily_budget_at_least` |
| `low_balance` | `sources.py:676-756`, from `backend/app/media/shooting_sheet.py:3593` | vendor balance below next round x margin | top up (guided) / wait | `balance_covers` (books reading) |
| `reconnect_connection` | `sources.py:216-246`; `sources.py:799-845` (from `run_agent_task`); `seed.py:260-300` | a model provider answered 401/402/403 | reconnect (guided, Settings) | `integration_verified`; withdrawn by the next successful run |
| `reconnect_youtube` | `sources.py:248-276`, `846-878`; `seed.py:302-372` | Google refused the grant | reconnect (guided) | `youtube_channel_connected` |
| `google_oauth_production` | `seed.py:331-370` | audit | move the app to production and request the audit (guided) | per its condition |
| `commercial_use` | `sources.py:282-313`, `880-919` (licence ledger NEEDS_REVIEW) | a vendor connection does not state commercial use | state it (guided) | `commercial_use` |
| `music_library` | `sources.py:529-566`, `921-938` (from `backend/app/media/assembler.py:5865`) | film assembled with an empty library | add music (guided) / without | `music_library_has_music` |
| `sheet_repair_paused` | `sources.py:971-1066`, from `backend/app/media/blocker_repair.py:270-274` | automatic sheet repair paused (model down, daily limit) | reconnect (guided) / retry now (`sheet_repair_retry`) / local move for blocked scenes (`sheet_local_move`) / wait | `sheet_repair_resumed` |
| `runpod_infra_actions` | `sources.py:315-352`; `seed.py:374-395` | a RunPod connection without the permission | yes: agents may switch the GPU on inside approved steps (`runpod_infra`, `sources.py:1180`) / not yet | `runpod_infra_enabled` |
| `runpod_ltx_licence` | `sources.py:354-397`; `seed.py:394` | LTX model licence | accept (guided) / without | never (Owner's DONE) |
| `runpod_weights` | `sources.py:399-456`, from `backend/app/providers/runpod/weights.py:237-243` | endpoint results prove other weights | fix in the console (guided) / keep off | never |
| `runpod_mirror_copy` | `sources.py:458-527`; `seed.py:392`; `backend/app/providers/runpod/pods.py:1042-1090` | model mirrors missing | yes: start the copy pod under the card's cap (`runpod_mirror_copy`, spends) / not yet | `runpod_mirrors_ready` |
| `runpod_unsent_release` | `backend/app/media/runpod_unsent.py:672-736`, `886-905` | a scene held by a /run with no job id and a clean record | release the scene (`runpod_unsent_release`, buys nothing) / keep | `runpod_unsent_hold_cleared` |
| `narration_paid_step` | `seed.py:454-493` | rule is EVERY_PAID_STEP | record "ask for narration too" (spec change needed) / none | rule no longer EVERY_PAID_STEP |
| `paid_media_rule` | `seed.py:494-528` | rule is EVERY_PAID_STEP | keep / switch to MODE (`paid_media_approval` applier) | idem |
| `editorial_qc` | `seed.py:531-570` | `STUDIO_EDITORIAL_QC_BLOCKING` unset | stay advisory / blocking (guided: `.env`) | setting is set |
| `old_test_films` | `seed.py:588-627` | 100 or more media folders | archive or delete (guided) / keep | folders below 100 |
| `sale_terms` | `seed.py:629-660` | no LICENSE/EULA file | write terms (guided) | a licence file exists |
| `gpu_owner_hold` | `backend/app/decisions/producers/gpu_hold.py:46-83`, from `backend/app/providers/runpod/router.py:94-99` | the Owner pressed «Oprește GPU acum» | allow again (lifts the hold) — no other option | hold record says off |
| `redo_cap_reached` | `backend/app/decisions/producers/redo_cap.py:104-228`, from `stages.py:5174-5185` | the cap alone stopped the Director's REPAIR | +5 redos and continue / publish as is (PASSED report in the Owner's name) / close the film / wait | film closed, published, passed, given an allowance, or the cap re-count below limit |
| `director_repair_blocked` | `backend/app/agents/repairs/desk.py:443-511` | the kernel refused her repair, or it repeated 3 times | do it in Settings (guided) / leave it (quiet 7 days) | Owner's answer |
| `agent_model_failing` | `backend/app/agents/repairs/agent_health.py:530-560` | no working replacement, or second switch in a day | choose the model (guided) | Owner's answer |
| `agent_model_price` | `backend/app/agents/repairs/reprice.py:442-476` | runs whose provider has no active price | set the price (guided) | Owner's answer |
| `agent_runs_over_budget` | `reprice.py:478-516` | pricing the runs would exceed a budget | look at the budget (guided) / leave runs unpriced | Owner's answer |
| `provider_invoice_missing` | `backend/app/agents/repairs/unbilled.py:210-240` | estimates without an invoice | enter the invoice (guided) | Owner's answer |

Approval requests are a second kind of question (section 5.3), shown in the same window and
answered through `POST /api/v1/owner/approvals/decision`. Their actions and labels:
`APPROVAL_ACTION_LABELS` (`backend/app/services.py:586-601`).

## 11. Authority matrix

"LLM alone?" = can a model's answer, by itself, produce the effect. "No" means code or the Owner
holds the decision even when a model proposes.

| decision class | who decides | LLM alone? | enforcement point | Owner override |
|---|---|---|---|---|
| stop all autonomous work | OWNER; CODE_RULE on P0 (safe mode sets STOP) | No | `backend/app/services.py:382`, `1491`; `backend/app/runbook/services.py:684-688` | clear the stop, `backend/app/main.py:952` |
| autonomy mode | OWNER; CODE_RULE refuses promotion under STOP or safe mode | No | `backend/app/services.py:1636-1700` | `backend/app/main.py:888`; card applier `backend/app/decisions/services.py:365` |
| TEST / PRODUCTION | OWNER | No | `backend/app/services.py:244` | `backend/app/main.py:876` |
| paid-media rule | OWNER only (`issued_by`) | No | `backend/app/services.py:1816-1836` | `backend/app/main.py:903`; card `paid_media_rule` |
| T4 actions (hard budget, kernel, credentials, legal, audit) | OWNER only | No | `backend/app/services.py:518-525`, `1497-1503`; no agent caller | the Owner acts outside the agents |
| USD budgets | OWNER | No | `backend/app/economy/budget.py:150`, `473` | `backend/app/economy/router.py:70`; `daily_budget` cards |
| daily token ceiling for agents | CONFIG (`STUDIO_AGENT_DAILY_TOKEN_BUDGET`) | No | `backend/app/economy/accountant.py:1098-1160` | `.env` |
| whether a model run may start | CODE_RULE (kernel) + OWNER (stop, budget, model, lifecycle) + EXTERNAL (provider health) | No | `backend/app/agents/services.py:608-680`, `781-831` | stop, budgets, model choice, pause |
| buy a paid step of a film | OWNER (yes on the sheet) or CODE_RULE (rule + mode + budget) | No | `backend/app/services.py:1520-1595`; `backend/app/media/shooting_sheet.py:1876-1879` | press, answer, `allow_over_budget` |
| buy a zero-cap step under AUTONOMOUS_CEO | CODE_RULE | No | `backend/app/services.py:1535-1545` | lower the mode |
| narration purchase | CODE_RULE (mode, threshold `paid_generation_approval_threshold_usd`) | No | `backend/app/runbook/stages.py:2643`, `3329`; `backend/app/config.py:392` | mode, threshold |
| film ceiling | CONFIG (`STUDIO_FILM_BUDGET_USD`) + CODE_RULE | No | `backend/app/media/shooting_sheet.py:2673-2724` | consent per step |
| vendor balance enough | EXTERNAL + CONFIG margin | No | `backend/app/media/stills_stage.py:1729-1741`; `backend/app/media/balance_rule.py:52` | `low_balance` card |
| GPU on | CODE_RULE + OWNER (RunPod card, switch, hold) | No | `backend/app/services.py:1352-1407`; `backend/app/providers/runpod/gpu_session.py:701-743`, `890-986` | hold, switch, card |
| GPU off | anyone, always | n/a | `backend/app/services.py:1479-1482` | — |
| lift the Owner's GPU hold | OWNER only | No | `backend/app/decisions/producers/gpu_hold.py:85-92` | the card |
| paid-redo count | CONFIG + OWNER allowance | No | `backend/app/runbook/stages.py:4966-4968`; `backend/app/decisions/producers/redo_cap.py:64-79` | `redo_cap_reached` card |
| retire an Owner-approved take | CODE_RULE: never unasked | No | `backend/app/media/assembler.py:16014`, `12973`; `backend/app/agents/reviews.py:757-759` | the Owner's own press or yes |
| topic proposals | LLM_CHECKED_BY_CODE (Lead Researcher; validation, duplicate-subject check) | No | `backend/app/research/agent.py:121-175`, `398` | add topics `backend/app/factual/router.py:111`; host list |
| which pages are read | CONFIG + OWNER (allowed hosts); LLM names pages, studio fetches | No | `backend/app/research/service.py:130-138`; `backend/app/research/agent.py:707` | host routes `backend/app/factual/router.py:160` |
| a claim is SUPPORTED | LLM_CHECKED_BY_CODE (independent verifier, verbatim quote) | No | `backend/app/factual/agent_pipeline.py:357-460` | manual verify `backend/app/factual/router.py:320` |
| the day's topic | LLM_CHECKED_BY_CODE (Director, shortlist) | Yes, within the shortlist | `backend/app/agents/director.py:195-254`; `backend/app/runbook/stages.py:756-830` | no Owner route that picks the day's topic was found |
| script approval | LLM_CHECKED_BY_CODE (Director PASS + computed checks + factual gate) | No | `backend/app/runbook/stages.py:929-975`; `backend/app/factual/story_review.py:400-470` | `backend/app/factual/router.py:406` |
| which script version ships | LLM scores + CODE_RULE bar and round cap | Yes, among versions that passed the checks | `backend/app/agents/editorial_judgement.py:278-281`, `640` | `editorial_rounds` (CONFIG) |
| serial episode approval | LLM_CHECKED_BY_CODE + OWNER grant | No (needs `director_may_approve_episodes`) | `backend/app/story/review.py:221-233` | `backend/app/story/router.py:174`; publish policy |
| shot prompts | LLM_CHECKED_BY_CODE (lint BLOCK, NEEDS_SHOT_PLAN) | No | `backend/app/media/prompt_agent.py:1081` | `backend/app/media/router.py:1146` |
| a still passes the stills gate | LLM vision after code local checks | Yes, after local checks | `backend/app/media/picture_qc.py:1668`; `backend/app/media/stills_stage.py:1-80` | the Owner's take decision `backend/app/media/assembler.py:9698` |
| clip QC accepts the hero | CODE_RULE (rule and mode) + LLM vision | No | `backend/app/media/assembler.py:9917-9990` | the Owner's look |
| film QC verdict | CODE_RULE checks + LLM vision findings | No (a FAIL goes to the Director) | `backend/app/media/picture_qc.py:904` | — |
| failed-QC disposition (ACCEPT / REPAIR) | LLM_CHECKED_BY_CODE (Director) | Yes for ACCEPT within schema; REPAIR spending still gated | `backend/app/agents/reviews.py:657-905`; `backend/app/runbook/stages.py:4442-4520` | close film `backend/app/media/router.py:860`; `redo_cap_reached` |
| minor defect accepted | LLM (Director) under schema rules | Yes | `backend/app/agents/reviews.py:689-705` | — |
| rights, factual, placeholder, production-path, file findings | CODE_RULE | No | `backend/app/media/director_qc.py:147-205`; `backend/app/runbook/stages.py:4466-4475` | the Owner or the sources |
| choose among refused candidates bought for her repair | LLM (Director, FINAL) | Yes | `backend/app/agents/reviews.py:1148`; `backend/app/media/director_qc.py:2069-2090` | the Owner's later look replaces hers |
| a rewrite may be bought on | LLM veto (MISSES) + CODE_RULE (lint, `PROMPT_NOT_CORRECTED`) | No (a TREATS still meets every gate) | `backend/app/media/scene_rewrite.py:1067`; `backend/app/runbook/stages.py:4734` | — |
| viewing verdict before publication | CODE hard rejects, then LLM (Director) | Yes for REJECT (closes the storyboard); No for publication | `backend/app/agents/editorial.py:420-426`, `518-521` | Owner publish route `backend/app/publishing/router.py:380` (not traced further here) |
| publication metadata | LLM_CHECKED_BY_CODE (Publisher; metadata refusals, language) | No | `backend/app/agents/reviews.py:1485`; `backend/app/runbook/stages.py:5772-5800` | — |
| lift a Publisher HOLD | LLM (Director inbox resolution) | Yes (the gate still runs) | `backend/app/agents/director.py:451-465`; `backend/app/agents/reviews.py:1744` | — |
| publish a film | CODE_RULE (7 gates) + mode (T3) + OWNER (channel policy; SUPERVISED approval) | No | `backend/app/publishing/services.py:984-1400`; `backend/app/runbook/stages.py:5845-5876` | approval; publish policy |
| visibility of an upload | OWNER (channel policy) + CODE_RULE (rights) + EXTERNAL (vendor plan licence) | No | `backend/app/publishing/services.py:352`, `480`, `1363-1400`; `backend/app/runbook/stages.py:5745-5755` | publish policy |
| what reaches the Owner by letter | LLM_CHECKED_BY_CODE (`owners_matter`) | No | `backend/app/agents/director.py:91-122`, `370-377` | — |
| company assignments | LLM_CHECKED_BY_CODE (computed matters, caps, HIGH_IMPACT escalation) | Yes for assignments within caps | `backend/app/agents/command.py:1034`, `1083-1170` | STOP; matters escalated |
| self-repairs | LLM choice or CODE_RULE (UNASKED_TIERS) + kernel | No | `backend/app/agents/repairs/desk.py:316-332`, `555-571` | stop, mode, `director_repair_blocked` |
| an employee's model | OWNER; Director repair once a day when the model fails now | No (probe and kernel decide) | `backend/app/agents/repairs/agent_health.py:601-700` | `backend/app/integrations/router.py:413` |
| suspend / terminate an employee | CODE_RULE proposes from measurements; OWNER decides | No | `backend/app/workforce/services.py:129`, `270-337` | the decision route |
| start a day | OWNER (schedule activation, GO); CONFIG hour | No | `backend/app/workflows/services.py:748-830`; `backend/app/runbook/services.py:1291` | — |
| retry / resume a started day | CODE_RULE | No | `backend/app/workflows/worker.py:291-321`; `backend/app/workflows/passes/resume_interrupted_day.py:40-80` | STOP |
| enter safe mode / leave it | CODE_RULE / OWNER | No | `backend/app/runbook/services.py:1749-1757`, `708` | clear with a note |
| retire a film that stood still | CODE_RULE (`film_wait_days`) | No | `backend/app/runbook/stages.py:2204` | CONFIG |
| answer a card / an approval | OWNER only | No | `backend/app/decisions/services.py:1188`; `backend/app/services.py:937` | — |

Tally of the 49 rows. In 9 a model's answer can produce the effect by itself: the day's topic
(within a code-computed shortlist), the script version that ships (among versions that passed the
checks), a still passing the stills gate (after the local checks), a failed-QC ACCEPT (within its
bound schema), a minor defect accepted, the Director's choice among refused candidates, a viewing
REJECT, the lift of a Publisher HOLD, and company assignments (within caps). None of the nine spends
money, changes a policy or setting, or publishes: each is followed by the money gates (section 6.1)
or by the publishing gate and the mode (section 7.2). 39 rows are decided by the Owner, by
configuration, by code, or by a model whose answer code can refuse; 1 row (GPU off) is open to
anyone.

## 12. The 37 LLM call sites: who answers and how far the answer is trusted

| call site | role | DECIDED-BY | TRUST | the check |
|---|---|---|---|---|
| `backend/app/agents/command.py:1083` `_choose` | Director | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | matter keys from code; caps; escalation |
| `backend/app/agents/director.py:195` `choose_topic` | Director | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | id must be in the shortlist |
| `backend/app/agents/director.py:492` `director_review` | Director | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | unknown ids dropped; `owners_matter` |
| `backend/app/agents/editorial.py:400` `editorial_review` | Director | LLM | FINAL | code hard rejects before; gates after |
| `backend/app/agents/editorial_judgement.py:410` `judge` | Director | LLM | FINAL (scores) | bar and round cap in code |
| `backend/app/agents/history.py:111` `chat` | any | LLM | INFORMATIONAL | Owner chat |
| `backend/app/agents/mail.py:443` `answer_mail` | addressee | LLM | INFORMATIONAL | rate and repeat limits on letters |
| `backend/app/agents/repairs/agent_health.py:568` `_probe` | the employee | CODE_RULE on run status | — | text ignored |
| `backend/app/agents/reviews.py:203` `review_narration` | Voice Artist | LLM | ADVISORY | never holds the render (`backend/app/runbook/stages.py:3069-3072`) |
| `backend/app/agents/reviews.py:455` `review_failed_render` | Video Editor | LLM | ADVISORY | diagnosis passed to the Director |
| `backend/app/agents/reviews.py:981` `review_film_qc` | Director | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | bound schema, `not_yours`, repair refusals |
| `backend/app/agents/reviews.py:1148` `review_bought_pictures` | Director | LLM | FINAL | index bound to shown candidates |
| `backend/app/agents/reviews.py:1485` `prepare_publication` | Publisher | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | metadata refusals, language |
| `backend/app/agents/router.py:297` `run_agent` | any | LLM | INFORMATIONAL | Owner-initiated |
| `backend/app/economy/accountant.py:1188` `reconcile_day` | Accountant | LLM | INFORMATIONAL | figures from the books; `continue_spending` and `holds` (`:1164-1173`) have no consumer (grep) |
| `backend/app/factual/agent_pipeline.py:208` `agent_extract_claims` | Lead Researcher | LLM | ADVISORY | stored UNVERIFIED |
| `backend/app/factual/agent_pipeline.py:357` `agent_verify_claim` | Fact Checker | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | verbatim quote; verifier is not the extractor |
| `backend/app/factual/agent_pipeline.py:642` `agent_write_script` | Script Writer | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | cited ids, grounding, story checks |
| `backend/app/factual/script_agent.py:28` `draft_with_agent` | Script Writer | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | evidence ids (no callers, per `subsystems/15_factual_research.md`) |
| `backend/app/factual/story_review.py:544` `_ask_director` | Director | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | stricter only, once |
| `backend/app/integrations/router.py:436` `test_agent_llm` | any | LLM | INFORMATIONAL | connectivity test |
| `backend/app/media/blocker_repair.py:557` `director_assignment` | Director | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | money and config escalated by code |
| `backend/app/media/model_research.py:205` `research_models` | stewards | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | vendor hosts only; locked defaults untouched |
| `backend/app/media/picture_qc.py:904` `evaluate_pictures` | lookers | LLM | FINAL (as a QC finding) | the Director judges every finding after |
| `backend/app/media/picture_qc.py:1668` `judge_still` | lookers | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | local checks first; `decide` |
| `backend/app/media/picture_qc.py:1929` `judge_clip` | lookers | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | measured clip checks |
| `backend/app/media/prompt_agent.py:987` `build_visual_bible` | Video Editor | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | schema and lint |
| `backend/app/media/prompt_agent.py:1081` `write_shot_prompts` | Video Editor | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | lint BLOCK |
| `backend/app/media/scene_rewrite.py:837` `director_brief` | Director | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | schema; feeds the rewrite only |
| `backend/app/media/scene_rewrite.py:1067` `review_rewrite` | Director | LLM | FINAL (veto only) | a TREATS still meets every gate |
| `backend/app/media/scene_rewrite.py:1279` `_editor_rewrite` | Video Editor | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | compile, lint, her review |
| `backend/app/media/sound_design.py:379` `sound_plan` | Voice Artist | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | deterministic fallback; mix measured |
| `backend/app/research/agent.py:398` `propose_topics` | Lead Researcher | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | validation; duplicate subjects |
| `backend/app/research/agent.py:707` `gather_sources` | Lead Researcher | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | authorised hosts; studio fetches |
| `backend/app/runbook/weekly.py:271` `execute_weekly_review` | Director | LLM | ADVISORY | indications filed as letters |
| `backend/app/story/review.py:946` `review_episode` | Director | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | computed checks; scores; Owner grant |
| `backend/app/story/services.py:1520` `write_episode` | showrunner | LLM_CHECKED_BY_CODE | CHECKED_BY_CODE | checked against the day |

Count: CHECKED_BY_CODE 22, FINAL 5, ADVISORY 4, INFORMATIONAL 5, status-only 1.

Reference count for the whole map: `LLM_CALL_SITES.md` §6 reconciles this table with
`LLM_ROUTING.md` §9.2 against the code and arrives at CHECKED_BY_CODE 24, FINAL 5, ADVISORY 5,
INFORMATIONAL 3 (`answer_mail` CHECKED_BY_CODE because its `done` flag closes HANDOFFs;
`_probe` CHECKED_BY_CODE on run status; `reconcile_day` ADVISORY because `continue_spending=false`
escalates, `backend/app/economy/accountant.py:1263-1264`).

## 13. Where the implementation differs from the specifications

Specs: `docs/architecture/31_GOVERNANCE_APPROVAL_POLICY.md`, `32_AGENT_TOOL_PERMISSION_MATRIX.md`,
`51_AUTONOMY_MODE_SEMANTICS.md`, `19_DIRECTOR_CEO_SPEC.md`. Facts only; whether each is a defect
or an undocumented decision is for the Owner and the decision log.

1. **The Director can overrule the QC gate.** 31 ("Conflict resolution: gate wins") — her ACCEPT
   writes a new PASSED report at the publishing minimum score (`backend/app/media/director_qc.py:1678-1735`,
   score at `:1714`), which satisfies publishing gate 3 (`backend/app/publishing/services.py:1087-1129`).
   QC is not in 31's hard-gate list; rights, factual, placeholder and production-path findings
   stay outside her reach (`director_qc.py:151`). Recorded as ADR-2026-10-10
   (`docs/project/16_DECISION_LOG.md:129-152`); no file under `docs/architecture/` mentions
   `director_qc` (grep).
2. **Her look overrules the stills gate and clip QC** for candidates bought for her repair
   (`backend/app/media/director_qc.py:2069-2090`). Not in the architecture package (grep).
3. **The redo-cap card's "publish as is" writes a PASSED report in the Owner's name**
   (`backend/app/decisions/producers/redo_cap.py:288-338`, calling `accept_film` with
   `decided_by` owner, `director_qc.py:1678-1684`). 31 says a card "converts no gate's refusal"
   (31, "Owner decision cards").
4. **A yes can be spent under a lowered mode.** 31 ("Lowering the autonomy mode refuses without
   looking for an answer"). For the four paid steps the Owner's rule is read before the mode
   (`backend/app/services.py:1520-1577` before `1597`): under MANUAL with EVERY_PAID_STEP (or
   OVER_USD above the threshold) a standing yes for the same plan is spent and the step is ALLOWED;
   without one the answer is NEEDS_APPROVAL, not BLOCKED_MODE.
5. **A MANUAL day may raise a paid-redo question** (inferred from code, not run). 51 says a whole
   MANUAL day "raises no approval request". The `edit_and_qc` stage is T1 (`backend/app/runbook/stages.py:264`)
   and reaches `redo_scene(..., unasked=True)` through the Director's REPAIR
   (`stages.py:5036-5058`) with no stage-level mode check on that path (`stages.py:3700-5430`, grep);
   `redo_scene`'s `may_act` (`backend/app/media/assembler.py:15987-15995`) then writes a request
   under MANUAL with the default rule (point 4). The day's `media` stage and `continue_film` are
   refused under MANUAL (`stages.py:6360-6372`, `5493-5496`).
6. **Unknown actions keep the caller's tier.** 51: "a caller's own tier is only ever taken upward".
   That holds for actions in `ACTION_RISK_TIERS`; an action absent from it is classified by the
   caller as is (`backend/app/services.py:1459-1463`): `agent.run` (`backend/app/agents/services.py:630`),
   `media.quality_control`, `runbook.day_report` (`stages.py:264`, `266`), and the repair actions
   (`economy.apply_active_price`, `director.close_review`, `director.close_decisions`,
   `director.close_thread`, `director.ask_for_invoices`; section 9), all T1. These are code
   declarations, not agent answers.
7. **SUPERVISED is not configurable.** 51: "configurable T2/T3 actions create Approval". Code: T2 is
   allowed outright and only T3 asks (`backend/app/services.py:528`, `1597-1626`).
8. **New-studio default.** 51 says existing and new rows were written AUTONOMOUS_CEO. A bootstrap
   now writes MANUAL and stopped (`backend/app/services.py:94`, `118-128`); the column and view
   defaults still say AUTONOMOUS_CEO (`backend/app/models.py:55-57`, `backend/app/schemas.py:62`).
9. **Zero-cap steps skip the paid-media rule under AUTONOMOUS_CEO** (`backend/app/services.py:1535-1545`).
   51's "Paid media steps" section has no such exception (grep for the 2026-10-05 rule in 51 and 31:
   none; no entry in `16_DECISION_LOG.md` dated 2026-10-05 either).
10. **The Owner's GPU hold** (2026-10-12) is not in 51's STOP/GPU amendment: a hold that only the
    card lifts and that reads as held when unreadable (`backend/app/providers/runpod/gpu_session.py:767-808`;
    `backend/app/decisions/producers/gpu_hold.py`). Changelog entry only
    (`docs/project/CHANGELOG.md:3`).
11. **Policy version is not recorded by the kernel.** 31: "Every material autonomous action should
    record which PolicyVersion authorized it"; 32 audit wants the policy version per privileged call.
    The verdict carries action, tier, mode, status, reason, approval id, not `owner_policy.version`
    (`backend/app/services.py:1465-1473`). Uploads carry the channel's policy version in their
    approval context (`backend/app/runbook/stages.py:5851-5854`).
12. **No tool grants or capability tokens.** 32 specifies per-role tool grants, short-lived scoped
    tokens and revocation. Models receive no tools (`backend/app/providers/base.py:58`); the only
    per-role check is REQUIRED model capabilities (`backend/app/agents/services.py:520-560`) and
    lifecycle ACTIVE (`:634-639`). Side effects are code paths, so the matrix's intent is met by
    construction rather than by grants.
13. **The Director can change her own model.** 19: changing the Director's own model "should require
    Owner approval by default". The `switch_agent_model` detector iterates every ACTIVE agent with no
    role exclusion (`backend/app/agents/repairs/agent_health.py:344`), the action is T2
    (`backend/app/services.py:476`), allowed unasked under SUPERVISED and AUTONOMOUS_CEO, once a day
    per employee (`agent_health.py:83`).
14. **Hiring and firing are the Owner's, not the Director's.** 19 lists hiring/firing in her
    workforce domain (governed). Code: proposals are computed from measurements and applied only on
    the Owner's decision; autonomous firing is behind a flag that is off
    (`backend/app/workforce/services.py:1-12`, `270-337`). `agent.fire`, `agent.hire`,
    `agent.suspend` have tiers but no caller of `may_act` (`backend/app/services.py:477-481`; grep).
15. **Decision object is partial.** 19 asks for options considered, expected benefit, risk and
    required approval. `DirectorDecision` holds observation, evidence, interpretation, confidence,
    decision, action, owner role, review condition, outcome (`backend/app/analytics/models.py:195-223`).
16. **P0 does not suspend a provider or channel.** 31 ("Emergency control"): a P0 may suspend the
    affected provider/channel. `_open_safe_mode` records the incident and sets STOP only
    (`backend/app/runbook/services.py:657-688`).
17. **A card's accept can spend outside the budgets.** 31 says an accept runs the Owner's own
    command "behind the same gate". The `runpod_mirror_copy` applier starts a paid pod bounded by
    the card's cap, without `may_act` or `reserve_spend` (`backend/app/decisions/sources.py:1236-1260`;
    `backend/app/providers/runpod/pods.py:496-500`).
18. **31's list of card appliers is out of date.** 31 names the budget, paid-media rule,
    environment, mode, `set_scene_model` and `allow_repair_retry`. Code also registers
    `runpod_infra`, `runpod_mirror_copy`, `runpod_unsent_release`
    (`backend/app/decisions/services.py:438-453`), `gpu_hold_lift`
    (`backend/app/decisions/producers/gpu_hold.py:110`), `redo_allowance`, `film_publish_as_is`,
    `film_close_capped` (`backend/app/decisions/producers/redo_cap.py:456-458`).
19. **Promotion checks are partial, as 51 itself states**: acceptance criteria and burn-in are not
    measured (`backend/app/services.py:1643-1651`).

Where the code matches the specs (selected): STOP outranks every mode and only GPU-off passes it
(51; `services.py:1479-1495`); T4 refused in every mode (31; `:1497-1503`); approvals keyed by
action and subject, spent once, before the act, bound to their context (31; `:731-835`,
`1284-1323`); paid steps asked under EVERY_PAID_STEP in every mode with `BLOCKED_NO_PLAN` and
`BLOCKED_NO_BUDGET` (51; `:1520-1595`); the Director cannot override the rights or factual gates
(19 "Independent vetoes"; `director_qc.py:151`, publishing gates 4 and 7); narration stays outside
the four paid steps pending the Owner (51; `backend/app/decisions/seed.py:454-493`).

## 14. Limits of this map

- `llm_distance` and the call-site list are static and name-based; calls through objects or
  registries are not resolved (for example the repair registry, section 9). The trust labels were
  read from the code at the lines cited.
- Section 13 point 5 is an inference from reading the call path; no test was run.
- Behaviour that depends on runtime state (which settings are in `.env`, which cards are open,
  whether `daily_main` is active) is described as code, not as the live studio's state.
