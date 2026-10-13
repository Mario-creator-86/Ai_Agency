# 10 — Agent core: the LLM gateway, identity, ensembles, mail and the Director

Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).

> Files (line counts from `wc -l`):
> `backend/app/agents/services.py` (1749), `backend/app/agents/structured.py` (166),
> `backend/app/agents/identity.py` (662), `backend/app/agents/ensemble.py` (921),
> `backend/app/agents/models.py` (317), `backend/app/agents/router.py` (387),
> `backend/app/agents/vision.py` (185), `backend/app/agents/memory.py` (184),
> `backend/app/agents/messages.py` (284), `backend/app/agents/history.py` (140),
> `backend/app/agents/language.py` (70), `backend/app/agents/schemas.py` (108),
> `backend/app/agents/seed_config.py` (62), `backend/app/agents/mail.py` (932),
> `backend/app/agents/command.py` (1404), `backend/app/agents/director.py` (641),
> `backend/app/agents/__init__.py` (0). 8212 lines in all; 183 functions.
>
> Mapped 2026-10-12 from commit b00083c plus the working tree. These 17 files are identical at
> the later HEAD f4e2bfd and had no uncommitted changes when read. Verified again (adversarial
> review, same day): `git diff b00083c HEAD` is empty for all 17 files at HEAD 3d49e9a, and
> `git status` shows no uncommitted change in `backend/app/agents/`. `git diff b00083c 20abffd`
> is empty for all 17 files as well (the only agents file those commits touch is
> `agents/editorial.py`, mapped in group 11).

Conventions used below. "Decided by" uses the shared vocabulary: **LLM**, **LLM_CHECKED_BY_CODE**,
**CODE_RULE**, **OWNER**, **CONFIG**, **EXTERNAL**. "Trust" of an LLM answer uses **FINAL**,
**CHECKED_BY_CODE**, **ADVISORY**, **INFORMATIONAL**. Every model call costs tokens, which the
run records (`AgentRun.cost_vr`, `prompt_tokens`, `completion_tokens`); "can lead to spend" below
means money *beyond* the call's own tokens (GPU, media, purchases). Employee names come from
`config/workforce_seed.json` (Sarah = Director, Dr. Aris = LeadResearcher, Elena = FactChecker,
Marcus = ScriptWriter, Lyra = VoiceArtist, Kael = VideoEditor, Vera = Publisher, Nadia =
Accountant); pronouns for the Director follow the code ("she").

---

## In one paragraph

This group is the studio's thinking machinery and its management desk. `run_agent_task`
(`backend/app/agents/services.py:733`) is the single function through which every language-model
call in the backend leaves: it composes the employee's identity as the system prompt
(`identity.compose_identity`, `backend/app/agents/identity.py:278`), applies the Owner Policy
Kernel (daily token ceiling, exceeded USD budget, STOP AUTONOMY, autonomy mode, lifecycle, model
availability, one-run-at-a-time, required capabilities, provider health), calls the provider
adapter outside any database transaction, and records the run, its context manifest and a live
speech-bubble event. Around it sit thin wrappers: `structured_run` (schema-validated answer, at
most two attempts, `backend/app/agents/structured.py:76`) and `run_with_strategy` (optional
second/third model as critic, peer, judge or fallback, `backend/app/agents/ensemble.py:182`).
On top of the gateway the group runs three management loops: employees answer their typed
letters (`mail.correspondence_round`, `backend/app/agents/mail.py:866`), the Director reviews
her inbox and picks the day's topic (`director.director_review`, `director.choose_topic`,
`backend/app/agents/director.py:492`, `:195`), and the Director's command loop turns computed
findings into assignments, repairs or escalations (`command.direct_company`,
`backend/app/agents/command.py:866`). The group also owns the workforce registry (roles,
capabilities, providers, models, agents, seeding and model allocation), employee memory, typed
messages, the Owner's chat with an employee, the "who can see a picture" lookup, and the
publishing-language guard. Almost everything the models answer here is either text for a human
(chat, letters) or a choice among options that deterministic code computed, validated and can
override; no answer in this group buys anything by itself. Three model outputs are acted on
with only schema validation: the `done` flag of a mail reply closes the sender's HANDOFFs
(`mail.py:309-313`), any closing decision of the Director's review on a Publisher HOLD releases
the held metadata to the publish stage (`director.py:451-464`; see Oddities 1), and the
free-text `action` of a command-loop choice becomes the department's instruction (only the role
is checked, `command.py:1030-1034`).

## Why it exists

- **One choke point for every model call.** The module docstring lists the kernel's gates in
  order and explains why the token ceiling is first: it is the only one that "costs money to
  learn the hard way" (`backend/app/agents/services.py:1-15`). The ceiling was added after 391
  runs on Ollama Cloud, "the Director's loop and the mail rounds among them, ran under no ceiling
  at all" (`services.py:770-778`; decision log `docs/project/16_DECISION_LOG.md:2048-2050`). A
  refusal is a recorded `AgentRun` row, not an exception the "twenty callers would each have to
  learn" (`services.py:775-776`).
- **Employees must know who they are.** "Until now `run_agent_task` sent the model the task text
  and nothing else ... Sarah did not know she was Sarah" (`identity.py:3-5`). The identity is
  composed from stored data only, and the run records a context manifest
  (`docs/architecture/04_AGENT_SYSTEM.md` §16 "Agent execution envelope", §9 "Memory", §19 persona
  "never changes what you approve"; cited at `identity.py:6-9`, `models.py:177-179`).
- **Structured answers kept failing for shape, not content.** `glm-5.3` narrated twelve thousand
  tokens before reaching JSON (`structured.py:5-9`); on 2026-10-11 the Director's QC decision for
  the cyclotron film was refused five times because a repair reason exceeded 400 characters
  (`structured.py:15-23`, `identity.py:408-418`). Hence the two-attempt ladder and
  `fit_to_schema`, which cuts over-long fields at a word boundary before validation.
- **A second opinion without a second employee.** `ensemble.py:3-6`: the Director "commits to [a
  strategic decision] alone"; a researcher whose model is down "has no answer at all". The design
  rules are stated at `ensemble.py:10-26`: no model is named in code, extra models cost money so
  routine work does not get them, "the advisers advise; the agent decides", and an incomplete
  review is recorded as `REVIEW_INCOMPLETE`, never passed off as a challenged decision.
- **Letters instead of an evening-only inbox, but bounded.** `mail.py:3-33` records the Owner's
  wish for an office where employees answer each other, and the 2026-10-11 incident: three
  handoffs to the Accountant answered three times each in two minutes, a colleague's letter never
  answered, about 160 attempts per letter on a failing model (2026-10-04). Every bound in
  `mail.py:73-131` comes from one of those incidents (e.g. `REVIEWS_PER_HOUR`: "One night she
  reviewed nine times in twenty-four minutes ... at twenty thousand tokens a time",
  `mail.py:85-89`). The spec behind it is `docs/architecture/04_AGENT_SYSTEM.md` §18
  "Communication controls" and `docs/architecture/20_EMPLOYEE_AGENT_SPEC.md` "Communication".
- **Letters to the Owner only for what is the Owner's.** The Owner's rule of 2026-10-12, «Ar
  trebui să nu ajungă la mine, este la Director!», is encoded as `OWNER_MATTER_KINDS` /
  `OWNER_MATTER_WORDS` and the override in `_apply_decisions` (`director.py:84-111`, `:370-378`;
  decision log `16_DECISION_LOG.md:51-53`; changelog `docs/project/CHANGELOG.md:77`).
- **An executive, not a reporter.** `command.py:1-33`: "Every part was measured and no part was
  managed." The rules are: numbers say what is wrong and the Director decides; an action or
  nothing; no busywork; and (Owner, 2026-10-11, «vreau ca directoarea să poată repara asta»)
  what she can repair from the studio's own data she repairs, through the Policy Kernel.
- **Vision must be declared, not guessed.** Measured 2026-09-18: no employee in a seeded studio
  could see, so picture and character checks reported NOT_APPLICABLE "for ever"
  (`vision.py:16-22`, `services.py:1061-1068`; decision log `16_DECISION_LOG.md:2975-2984`,
  `:3134`).
- **Busy states must be true.** Lyra's voice was recorded for five minutes while the office
  showed her IDLE (`services.py:60-66`); a stale THINKING flag blocked Dr. Aris for a whole day
  (`services.py:654-657`).

## Who decides here

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| Whether a model call may run under the day's token ceiling | CONFIG (`Settings.agent_daily_token_budget`, env `STUDIO_AGENT_DAILY_TOKEN_BUDGET`) + CODE_RULE | `services.py:779-781`, `:829-830`; `backend/app/economy/accountant.py:1119-1158` | tokens used since the studio-day start ≥ ceiling → run recorded `BLOCKED_BUDGET`; ceiling 0 = none; the Accountant writes the Owner once a day |
| Whether a call runs while a USD budget is exceeded | CODE_RULE over budgets the OWNER set | `accountant.py:1124-1127`, `:1037` | an active DAILY/MONTHLY budget already EXCEEDED → `BLOCKED_BUDGET`, except task `reconcile_day` (`BUDGET_EXEMPT_TASKS`; matched on the `task_type` string alone, Oddities 45); the token ceiling is checked first and has no exemption |
| STOP AUTONOMY stops every model run, the Owner's own chat included | OWNER (`OwnerPolicy.autonomy_stopped`) | `services.py:619-621` | stopped → `BLOCKED_POLICY` with `AUTONOMY_STOPPED` text |
| Autonomy mode admits a run | CODE_RULE (`may_act("agent.run", "T1")`) over the OWNER's mode | `services.py:623-632`; `backend/app/services.py:532` | a run is T1; T1 passes in every mode and in safe mode (`SAFE_MODE_ALLOWS = "T1"`) |
| Only ACTIVE employees think | CODE_RULE | `services.py:634-639` | lifecycle ≠ ACTIVE → `BLOCKED_POLICY` |
| The answering model must exist and be available | CODE_RULE over EXTERNAL availability (set by provider sync) | `services.py:641-648`, `:813-825` | missing/unavailable model, or own model on another provider → `BLOCKED_PROVIDER`; a slot model that is unavailable raises `PolicyKernelError` |
| One live run per employee | CODE_RULE | `services.py:562-586`, `:649-668` | a RUNNING row younger than 45 min blocks ("already has an active task"); older RUNNING rows become ABANDONED; THINKING with no live run is reset to IDLE |
| The model has the role's REQUIRED capabilities | CODE_RULE over EXTERNAL declarations | `services.py:520-559`, `:671`, `:824` | missing REQUIRED capability → `BLOCKED_CAPABILITY`; PREFERRED is never a gate (`services.py:529-531`) |
| Provider health admits the run | EXTERNAL (registry's cached status) | `services.py:673-679` | only `HEALTHY` or `UNKNOWN` pass |
| The Director's token allowance | CONFIG (`Settings.director_token_multiplier`, default 2, bounds 1..4) | `services.py:793-806`; `backend/app/config.py:11`, `:425` | Director's `max_tokens` × multiplier; recorded in `context_json.generation_limits` (ADR-DIRECTOR-TOKEN-BUDGET-X2, `16_DECISION_LOG.md:91-106`) |
| A run's outcome status | EXTERNAL (provider answer) + CODE_RULE | `services.py:938-975` | non-empty text → SUCCEEDED; empty → EMPTY_OUTPUT (with `done_reason == "length"` wording); exception → FAILED with `_failure_detail` |
| A reconnect card for a refused connection | CODE_RULE, card answered by OWNER | `services.py:1022-1027`; `backend/app/decisions/sources.py:64`, `:799-838` | FAILED with HTTP 401/402/403 → card; next SUCCEEDED on that provider withdraws it |
| Whether the answer becomes a live speech bubble | CODE_RULE | `services.py:1029-1046` | `emit_message` and SUCCEEDED and non-empty → `agent.message_sent` (text capped at 1200 chars) |
| How a structured answer is retried | CODE_RULE | `structured.py:109-163` | first: JSON mode, thinking off; object refused by schema → second with the refusal quoted; no object at all → second with native thinking; a failed/empty first run is not retried |
| Over-long fields are cut rather than refused | CODE_RULE | `identity.py:568-583`, `:440-452` | strings cut at a word boundary to `max_length`, lists truncated, code words matched case/spacing-insensitively |
| Whether extra models are consulted | CONFIG (agent slots, `multi_llm_strategy`, `additional_llm_policy`, `min_importance`, `min_confidence`; set by the OWNER in Settings or by the seed allocation) + caller's stated importance | `ensemble.py:131-166` | SINGLE or no secondary → no; MANUAL → only when the caller requests; ALWAYS → yes; LOW_CONFIDENCE → confidence < floor (default 0.6); IMPORTANT_ONLY → importance ≥ `min_importance` (default STRATEGIC) |
| The answer a caller receives under REVIEW/DEBATE/PARALLEL | LLM (the primary model's own final run) | `ensemble.py:431-456`, `:528-544`, `:588-606` | advisers' words are inserted into the primary's prompt as advice; the final run is the primary's |
| Calling a third model in DEBATE | CODE_RULE | `ensemble.py:62`, `:515-527` | only when word overlap < 0.34 and a tertiary model is configured and available |
| Starting allocation of models to roles | CONFIG (`config/workforce_seed.json` `llm_allocation`) | `ensemble.py:814-921` | applied only to an ACTIVE employee with no `agent.model_assigned` event ever; unknown/unavailable names skipped; a non-SINGLE strategy without a secondary becomes SINGLE |
| Moving the Video Editor to a model that sees | CODE_RULE over EXTERNAL `vision` declarations | `services.py:1331-1439`, `:1068` | only if the role PREFERS it, the employee's model lacks it, the OWNER did not choose her models, she is idle, and an available model declares all REQUIRED + PREFERRED capabilities (first by name) |
| Who looks at a picture | EXTERNAL (provider-declared `vision`) + CODE_RULE (preferred roles first) | `vision.py:116-142`, `:162-185` | own model, then own 2nd/3rd slot (each must declare `vision` and be available), then the model of the employee `vision_agent` names (preferred roles first, else the first-hired ACTIVE employee with a seeing primary; `vision_agent` does not check availability, so `seeing_model` returns None if that one model is unavailable, Oddities 47) |
| What memory an employee is told | CONFIG (role contract `memory_scope.read`, editable by the OWNER) + CODE_RULE | `memory.py:111-143` | 12 newest live records (not invalidated, not expired) of readable classes, studio-wide or own |
| A duplicate memory record is not written | CODE_RULE | `memory.py:67-79` | same agent, class and clipped content, still live → returns None |
| A role's work contract | OWNER (PUT with optimistic version) | `identity.py:139-158`; `router.py:90-99` | `expected_version` must equal stored `contract_version` |
| The seed never overwrites an edited contract | CODE_RULE | `identity.py:110-114` | skip a role that has both a contract and a version |
| One open letter to the Owner per subject | CODE_RULE | `messages.py:55-74` | an OPEN Owner-addressed letter with the same subject is returned instead of a new one |
| Which letters are answered this round | CODE_RULE | `mail.py:739-800`, `:697-736` | newest open asking letter per (thread, addressee, sender); max 6; thread < 8 letters; 15 min since the addressee last wrote (Owner's letters exempt); not blocked; no back-off running; failing model gets one letter after its wait |
| The text of an employee's reply and whether the matter is done | LLM (`MailReply`) | `mail.py:491-535` | schema: reply 1..4000 chars with ≥3 letters, `done`, `needs` ≤600 |
| A repeated request is held, not sent | CODE_RULE | `mail.py:254-273`, `:537-548` | same need (equal or `agreement` ≥ 0.6) and same words (≥ 0.6), neither done, both needs name something (not in `NOTHING_NEEDED`), sender not the Owner |
| Unproven media-work claims are labelled | CODE_RULE | `mail.py:563-566`; `backend/app/agents/reviews.py:1389-1419` | claimed media work with no `media.*` event since the thread began → `NEEFĂCUT` label (the letter is still sent) |
| Back-off after a failed answer | CODE_RULE | `mail.py:803-845`, `:638-666` | 300 s doubled per failure on the same model, max 6 h; ≥3 failed attempts on a model → the employee waits as a person |
| Whether the Director reviews after a mail round | CODE_RULE | `mail.py:911-931` | a reply landed in a thread she did not decide within 1 h, or an unread reply is ≥1 h old; deferred when ≥3 `director_review` runs started in the last hour (`reviews_this_hour` counts runs, so a review that needed its second structured attempt counts twice, `mail.py:588-597`) |
| The day's production topic | LLM_CHECKED_BY_CODE | `director.py:195-254`; caller `backend/app/runbook/stages.py:808-818` | `topic_id` must be one of the shortlist ids, else `DirectorError` and the runbook keeps the deterministic order |
| What happens to each inbox letter | LLM_CHECKED_BY_CODE | `director.py:345-466` | message must be open in the inbox; action one of 5; ESCALATE_TO_OWNER overridden unless the Owner's matter; an investigation's answer is not re-investigated; an investigation target must be an active role or the sender |
| Escalation to the Owner from the review | LLM_CHECKED_BY_CODE (the model proposes ESCALATE_TO_OWNER; code downgrades it) | `director.py:114-122`, `:370-378` | kept only for body `kind` in OWNER_MATTER_KINDS, a letter with no sending employee (`from_agent_id is None`: the Owner's own letter; the code comment calls it "a thread the Owner opened" but only the letter's own sender is read), or OWNER_MATTER_WORDS in the letter's subject, its text **or the model's own note**; otherwise ACKNOWLEDGE with `HERS_NOTE` (+ `developer_defect` note when DEFECT_WORDS match). The model can satisfy the word test with its own note (Oddities 43) |
| A Publisher HOLD is lifted | LLM (any closing decision) | `director.py:409-464`; `reviews.py:1717-1748`; `stages.py:5773-5795` | ACKNOWLEDGE, APPROVE and REJECT all resolve with status RESOLVED, and `approved_metadata` returns a RESOLVED HOLD's title/description/tags as approved metadata (the title refusal check at `stages.py:5784-5795` still applies). REQUEST_INVESTIGATION and ESCALATE_TO_OWNER leave the HOLD ANSWERED: `publication_hold` reads only OPEN letters, so it no longer blocks either, and the Publisher is asked again (`stages.py:5796-5810`) |
| Stage reports filed to the inbox | CODE_RULE | `director.py:257-311` | one STATUS per stage outcome, from the outcome's own `agent_id` if given, else the ACTIVE employee whose contract lists the stage, else the Director |
| A letter to the Owner when the day stops | CODE_RULE (caller decides) | `director.py:469-489` | deterministic text from the caller; no model |
| Which matters the studio raises | CODE_RULE | `command.py:536-774` | blockers, bottleneck, channel growth constraints, anomalies, idle roles (only with nothing in flight), due reviews, repair detectors |
| Backlog order | CODE_RULE | `command.py:473-530` | editorial composite + min(0.2, 0.05 × verified claims) + 0.15 if SELECTED − 0.2 if category among last 5 produced − 0.1 if feasibility < 0.4 |
| The production bottleneck | CODE_RULE | `command.py:340-355` | first stage with ≥3 waiting and 0 passed on; else the busiest stage if ≥5 and > 3× passed on |
| Which matters the Director acts on now | LLM_CHECKED_BY_CODE | `command.py:1083-1208` | only matter keys in the fresh list, one choice per key; any failure → the measurements' own order |
| Repairs she did not choose still run | CODE_RULE | `command.py:945-956`, `:170` | every fresh matter offering a repair of tier T0-T2 is appended with its suggested decision |
| Whether a repair may run | CODE_RULE (`may_act` with the repair's tier) over the OWNER's mode | `backend/app/agents/repairs/desk.py:316-332` | refused → one Owner card per cause (`command.py:1006-1021`) |
| A repair is held | LLM (her decision in `WAIT_DECISIONS`, acted on as given); for a repair appended unchosen, the matter's own suggested decision (CODE_RULE) | `command.py:982-986`, `:189` | HOLD, COOLDOWN, REDUCE, STOP, or NEEDS_MORE_DATA where the measurements suggested otherwise → `hold_repair` records a closed DirectorDecision (which counts toward the 24 h and all-time counts) |
| A repair that keeps coming back goes to the Owner | CODE_RULE | `command.py:987-1004` | ≥3 DirectorDecision rows for the matter in 24 h → Owner card (cause REPEATED) |
| A matter goes to the Owner instead of a department | CODE_RULE over the model's `decision` and `owner_role` | `command.py:1030-1037` | decision STOP or SCALE, or ≥3 DirectorDecision rows ever for the key, or role (the choice's, else the matter's) not in `ASSIGNABLE` (outside it: "Director", any misspelt role, and the role-less APPROVAL bottleneck) |
| The work a department is handed | LLM (free text, schema ≤1200 chars) | `command.py:1031`, `:1277` | the choice's `action` (else the matter's) is written as «DE FĂCUT» in the HANDOFF; code checks only that the role is in `ASSIGNABLE`, never that the action is one of that role's listed works (`ASSIGNABLE[role]`), unless it begins with an `ACTION_REPAIRS` phrase, which turns it into a repair (`command.py:1211-1233`) |
| How many assignments a loop makes | CODE_RULE | `command.py:156`, `:1026` | first 3 non-repair picks (escalations and picks with no action count against the 3) |
| When an assignment is reviewed | LLM (schema bound 1..100) + CODE_RULE default | `command.py:214`, `:1255-1257` | Director's `review_after_videos` (an out-of-range value fails the whole `Direction` schema → fallback) or the matter's; default 3 unless NEEDS_MORE_DATA |
| A decision nobody could challenge | CODE_RULE | `command.py:1202-1207`; `ensemble.py:383-399`, `:413-429` | `REVIEW_INCOMPLETE` → every kept choice set to LOW confidence and the note says so. Only a critic that ran and gave nothing usable yields REVIEW_INCOMPLETE here: `_choose` does not pass `require_review`, so a critic model that is unavailable yields PARTIAL, which lowers nothing (Oddities 42) |
| Which task types an employee may run | CODE_RULE of each caller (it names the task type); the role's list is CONFIG text the model reads, never a gate | `identity.py:296-297`; `services.py:608-679`, `:733-883` | `Role.allowed_task_types` and `prohibited_actions` are written into the system prompt; no code compares a run's `task_type` with them (Oddities 39) |
| Pause / resume an employee | OWNER | `services.py:237-284`; `router.py:319-341` | only ACTIVE/HIRED can pause, only PAUSED/SUSPENDED can resume, else HTTP 409 |
| Which models exist and are available | EXTERNAL (provider's model list) on an OWNER-triggered sync | `services.py:313-503`; `router.py:363-385`; `backend/app/integrations/router.py:277` (verifying an LLM connection) | listed → available, DECLARED_BY_PROVIDER; not listed → unavailable; provider marked HEALTHY |
| A publication held for language | CODE_RULE | `language.py:61-70` | for `en`: any Romanian diacritic, or ≥2 common Romanian words, → hold reason |

## LLM involvement

### The gateways defined in this group

**`run_agent_task`** (`services.py:733-1047`). Inputs: agent, `task_type`, `objective` (the user
prompt), `prompt_template_version`, `correlation_id`, optional `max_tokens`, `temperature`,
`emit_message`, `summary` (one Owner-readable sentence, stored as `context_json.task_summary`,
300 chars), `extra` (provider options such as `{"format": "json"}` or `{"think": True}`), and
`model_id` (answer on a slot model instead of the agent's own). Sequence:

1. Budget verdict (`may_run_agent`) before any write transaction (`services.py:779-781`).
2. Transaction 1 under `lock_for_write`: load agent, `compose_identity` (system prompt + manifest),
   Director multiplier, model/provider records; a slot model must be available and satisfy the
   role's REQUIRED capabilities (`services.py:819-825`, raised outside the kernel's `try`); kernel
   (`services.py:828-856`) — a block writes a BLOCKED_* row and returns it; no adapter →
   `BLOCKED_PROVIDER` row (`services.py:858-883`); else agent → THINKING, event
   `agent.state_changed`, a RUNNING `AgentRun` row (`services.py:885-924`).
3. The provider call `adapter.generate(model, objective, system=..., max_tokens=..., temperature=...,
   extra=...)` via `asyncio.run`, outside the transaction (`services.py:926-976`).
4. Transaction 2: agent → IDLE, `agent.run_completed` event, run row completed, provider card
   hook `model_run_finished`, optional `agent.message_sent` bubble (`services.py:979-1047`).

It never interprets the answer; it returns `AgentRunView` (`schemas.py:91-108`). Callers decide.

**`structured_run`** (`structured.py:76-166`). Calls `run_agent_task` with `emit_message=False`
at most twice and parses with `identity.read_structured`. Returns `(parsed or None, first run,
second run or None)`. Template version suffixes record the attempt kind: `+again` (refusal
quoted, JSON mode) and `+think` (native thinking). `schema_hint` and `format_tokens` are accepted
and discarded (`structured.py:105`).

**`run_with_strategy`** (`ensemble.py:182-304`). Decides by `should_collaborate` whether the
agent's configured strategy applies; SINGLE is one `run_agent_task` call. FALLBACK tries
secondary then tertiary only if the primary's run is unusable; REVIEW asks the secondary to
critique, then the primary writes the final answer with the critique appended as advice; DEBATE
asks a peer, calls the tertiary as judge only on disagreement, then the primary reconciles;
PARALLEL asks all available slots, then the primary synthesises. For every strategy but SINGLE,
`_finish` writes one `LlmCollaboration` row and returns the final run plus a `collaboration`
dict (`ensemble.py:643-740`); SINGLE writes no collaboration row and returns the run with a
`collaboration` dict that has no `id` (`ensemble.py:234-242`). Runs per question: SINGLE 1,
FALLBACK 1-3, REVIEW 1-3, DEBATE 1-4, PARALLEL 1-4 (the extra runs carry suffixed task types
such as `direct_company:critique`, `:final`, `:peer`, `:judge`, `:fallback`). Inside this group
only `command._choose` calls it (`command.py:1156`); a repository-wide search finds no other
caller.

### Call site 1 — `create_agents_router.run_agent` (`router.py:296-317`), `POST /api/v1/agents/{agent_id}/run`

| Aspect | Fact |
|---|---|
| Speaker | Any employee the Owner names by id |
| Task type / template | From the request: `RunAgentCommand.task_type` (1..100 chars, any string — not checked against the role's allowed task types; `reconcile_day` would also skip the exceeded-USD-budget check, Oddities 45), `prompt_template_version` (default `"v1"`), `max_tokens` ≤8192 (×2 for the Director) (`schemas.py:80-88`) |
| Asks | The Owner's `objective` verbatim (1..2000 chars), with the employee's identity as system prompt |
| Answer shape | Free text; the route returns `AgentRunView` |
| Use of answer | Returned to the caller; emitted as `agent.message_sent` (default `emit_message=True`) |
| Trust | INFORMATIONAL |
| If the model fails | The run row's status (FAILED, EMPTY_OUTPUT, BLOCKED_*) is returned with HTTP 200; unknown agent → 404; database fault → 500 with `DATABASE_FAULT` (`router.py:314-317`) |
| Can lead to spend | No (tokens only; under the same kernel and budget gates) |

### Call site 2 — `history.chat` (`history.py:111-140`), reached by `POST /api/v1/agents/{agent_id}/chat`

| Aspect | Fact |
|---|---|
| Speaker | The employee the Owner opened |
| Task type / template | `owner_chat` / `chat-v1` (`history.py:26-27`) |
| Asks | `_CHAT_INSTRUCTIONS` (answer in your own voice and the Owner's language, cite recorded reasons, say when you do not know; `history.py:29-34`) + the Owner's question wrapped in `<untrusted_source_evidence hash="owner-question">` |
| Parameters | `max_tokens=3600` (×2 for the Director), `temperature=0.4`, `summary` = the question |
| Answer shape | Free text |
| Use of answer | Returned as a timeline item (`_run_item`) with `asked` = the Owner's words; bubble event emitted |
| Trust | INFORMATIONAL |
| If the model fails | The item carries the run's status and `error`; empty question → `ValueError("Scrie o întrebare")` → HTTP 404 (`router.py:250-251`) |
| Can lead to spend | No |

### Call site 3 — `mail.answer_mail` (`mail.py:443-585`), reached by `correspondence_round`

| Aspect | Fact |
|---|---|
| Speaker | The addressee of a letter (any ACTIVE employee; `mail.py:457-463`) |
| Task type / template | `answer_mail` / `mail-v1` (`mail.py:70-71`), through `structured_run` (`+again`/`+think` on a second attempt) |
| Asks | `_INSTRUCTIONS` (`mail.py:133-142`): answer as yourself, be concrete, never claim undone work as done, return `{"reply", "done", "needs"}`; then the whole thread (`_thread_text`) in an inert boundary `mail-thread`; for the Accountant also her books (`accountant.daily_figures`, JSON ≤12000 chars) with `_BOOKS_INSTRUCTIONS` (`mail.py:144-149`, `:211-227`, `:482-488`) |
| Parameters | `max_tokens=3600` (×2 if the addressee is the Director), `temperature=0.3`, summary «Răspund la «subject» de la sender.» |
| Answer shape | `MailReply` (`mail.py:152-164`): `reply` 1..4000 chars, ≥3 alphabetic characters; `done: bool = False`; `needs` ≤600 |
| Use of answer | A STATUS letter in the thread (to the Owner if the Owner wrote, to the Director's inbox if the Director wrote, else to the colleague; `mail.py:474-481`, `:549-562`); `done` decides whether the sender's open HANDOFFs close (`_close_earlier`, `mail.py:284-323`); questions of that sender before it are marked ANSWERED |
| Code checks | A structured blocker (`{"blocker": ...}`) becomes an ESCALATE letter in words (`mail.py:515-527`); prose instead of JSON is still sent as a letter, `done=False` (`mail.py:529-535`); a repeated request is held (`mail.py:537-548`); unproven media claims are labelled `NEEFĂCUT` (`mail.py:563-566`) |
| Trust | CHECKED_BY_CODE (the code can hold a reply and labels unproven claims; the `done` flag itself is acted on as given and closes the sender's HANDOFFs — also the Director's command-loop assignments — even when the same reply's media claim was labelled `NEEFĂCUT`, `mail.py:563-578`) |
| If the model fails | `MailError` with the last run's status/id (`mail.py:505-513`); a prose answer with fewer than 3 letters fails `MailReply` (pydantic `ValidationError`, a `ValueError`) and is handled the same way; the round records `answer_attempts` and backs off 300 s doubling to 6 h (`mail.py:803-845`, `:888-909`); after 3 failed attempts on a model the employee waits as a person (`mail.py:638-666`) |
| Can lead to spend | No |

### Call site 4 — `command._choose` (`command.py:1083-1208`), reached by `direct_company`

| Aspect | Fact |
|---|---|
| Speaker | The Director (`agent_for_role(session, "Director")`, `command.py:900`) |
| Task type / template | `direct_company` / `direction-v1` (`command.py:81`), through `run_with_strategy` with `importance="STRATEGIC"` (so a REVIEW strategy with a secondary model is used when configured; the seed allocation gives the Director REVIEW with a second model, `config/workforce_seed.json`) |
| Asks | `_INSTRUCTIONS` (`command.py:225-246`): choose at most 3 matters that most limit growth (+ up to 6 repairs), do not invent matters, NEEDS_MORE_DATA where evidence is one film or fewer than three samples, prefer finishing work in flight; payload `company-state` (maturity, channels, pipeline, idle count, backlog top 5, open decisions, matters with evidence and suggestions, departments' assignable work, the repair desk), JSON truncated to 14000 chars; critic's `review_objective` asks about sample size, noise, causation, cheaper experiments (`command.py:1165-1171`) |
| Parameters | `max_tokens=3000` (×2 for the Director), `temperature=0.2`, `emit_message=False` |
| Answer shape | `Direction` (`command.py:219-222`): `choices` ≤6 of `Choice` (`command.py:202-216`: `matter_key`, `decision` ∈ SCALE/CONTINUE/ITERATE/EXPERIMENT/HOLD/COOLDOWN/REDUCE/STOP/NEEDS_MORE_DATA, `interpretation` ≤1200, `confidence` LOW/MEDIUM/HIGH, `action` ≤1200, `owner_role` ≤50, `review_after_videos` 1..100, `repair_action` ≤60), `note` ≤800 |
| Code checks | Only keys in the fresh list; first choice per key (`command.py:1187-1194`); one parse, no second attempt (`parse_structured`, not `structured_run`); more than 6 choices are cut to 6 by `fit_to_schema`; empty or invalid → fallback order; `REVIEW_INCOMPLETE` → LOW confidence (`command.py:1202-1207`; an unavailable critic gives PARTIAL and lowers nothing); then in `direct_company`: repairs through `submit_repair` (kernel with the repair's tier), WAIT decisions hold a repair, repeated repairs and kernel refusals become Owner cards, STOP/SCALE or ≥3 decisions or unassignable role → Owner letter, ≤3 assignments; repairs of tier ≤T2 she left out run anyway (`command.py:945-1051`) |
| Not checked | The `action` text (≤1200 chars) is sent to the department as written; it is not compared with `ASSIGNABLE[role]` (`command.py:1031`, `:1277`); it also becomes studio-wide STRATEGY memory (`command.py:1327-1337`) |
| Trust | CHECKED_BY_CODE (which matter, which repair and who may receive it are checked; the instruction text and the decision code are acted on as given) |
| If the model fails | Exception (ValueError/RuntimeError, incl. `EnsembleError`), FAILED/empty run, invalid schema or no valid choice → the computed suggestions in their own order (`_suggested`, only matters with both an action and a role), with a note (`command.py:1097-1099`, `:1178-1186`, `:1208`). A `PolicyKernelError` from a slot model is not caught and ends the loop (Oddities 9) |
| Can lead to spend | No GPU/media money: repairs are T0-T2 (`agent.change_model` T2, `economy.apply_active_price` T1, reports, closing threads/decisions; `backend/app/agents/repairs/*.py`); assignments are HANDOFF letters that later cost mail tokens. Token spend beyond this call: the T2 `switch_agent_model` repair, offered by the `agents_failing` detector and appended unasked when she leaves it out, probes candidate models with `run_agent_task` (`repairs/agent_health.py:568`, `:634`, `:668`) and moves the employee to another (differently priced) model, gated by `may_act("agent.change_model", "T2")` under the Owner's mode |

### Call site 5 — `director.choose_topic` (`director.py:195-254`), reached by the runbook's selection stage

| Aspect | Fact |
|---|---|
| Speaker | The Director |
| Task type / template | `choose_topic` / `director-review-v1` (the review's constant is reused, `director.py:56`, `:223`) |
| Asks | `_CHOOSE_INSTRUCTIONS` (`director.py:186-192`): choose today's topic from candidates that each have ≥1 verified claim, on scores, verified-claim count and strategy; payload `production-candidates` (id, title, angle ≤300, scores, supported_claims; built at `stages.py:794-805`), JSON ≤12000 chars |
| Parameters | `max_tokens=2400` (×2), `temperature=0.1`, `emit_message=False`, plain `run_agent_task` (no retry) |
| Answer shape | `TopicChoice` (`director.py:180-183`): `topic_id` 1..36, `reason` ≤1000 |
| Code checks | `topic_id` must be one of the candidates' ids, else `DirectorError` — "refused rather than corrected" (`director.py:203-205`, `:233-236`) |
| Use of answer | The chosen id is moved to the front of the candidate order; `select_topic` then tries them in order, skipping unproducible ones (`stages.py:808-822`); the reason is stored as AGENT_OPINION memory (`director.py:237-245`) |
| Trust | CHECKED_BY_CODE |
| If the model fails | `DirectorError`; the runbook logs `director_choice_refused` and uses the deterministic order (`stages.py:814-818`); the call is skipped when there is ≤1 candidate or no language model |
| Can lead to spend | Indirectly: the chosen topic is the film the day's paid production is made of; each paid step is gated elsewhere (`may_act` paid-media rule, budgets) |

### Call site 6 — `director.director_review` (`director.py:492-641`)

| Aspect | Fact |
|---|---|
| Speaker | The Director |
| Task type / template | `director_review` / `director-review-v1`, through `structured_run` |
| Asks | `_INSTRUCTIONS` (`director.py:160-177`): answer every message by id with one action; ESCALATE_TO_OWNER only for accounts/sign-ins, what only the Owner authorises, security or legal standing; money is never hers to escalate; a failing tool is noted for the developer; never fewer than three samples; JSON only. Payload `director-inbox` (≤12 newest open inbox messages, workforce measurement, stage outcomes), JSON ≤16000 chars. Each inbox message is given as `id`, `intent`, `from_name`, `subject`, `body_json`, `created_at` only (`director.py:515-522`): the letter's written text (`body_text`) — an employee's whole reply, the Owner's words — is **not** in the payload, while `owners_matter` does read it (Oddities 40) |
| Parameters | `max_tokens=24000` (×2 = 48000 by default), `temperature=0.1` |
| Answer shape | `DirectorReview` (`director.py:76-81`): `summary` 1..2000 (clipped), `decisions` ≤60 of `Decision` (`director.py:67-73`: `message_id`, `action` pattern of the 5 ACTIONS, `note` ≤1000 clipped, `assign_to_role`), `priorities` ≤3 |
| Use of answer | `_apply_decisions` (`director.py:345-466`): REQUEST_INVESTIGATION → a REQUEST_INFO letter titled `De investigat: …` to the named role's employee (or the sender), original ANSWERED; ESCALATE_TO_OWNER → letter to the Owner `Am nevoie de decizia ta: …`, original ANSWERED; ACKNOWLEDGE/APPROVE/REJECT → original RESOLVED with `Luat la cunoștință`/`Aprobat`/`Respins`. The summary and priorities become AGENT_OPINION and TEMP_CONTEXT memory; event `director.review_completed` |
| Code checks | Unknown or closed message ids dropped and counted (any of the 200 newest open inbox letters may be decided, not only the 12 shown, `director.py:352`); ESCALATE_TO_OWNER downgraded to ACKNOWLEDGE unless `owners_matter` (whose word test also reads the model's own note), plus a `developer_defect` note when DEFECT_WORDS match; REQUEST_INVESTIGATION on an investigation's answer downgraded to ACKNOWLEDGE; investigation target = the ACTIVE employee of `assign_to_role`, else the letter's sender (no ACTIVE check), else dropped. ACKNOWLEDGE/APPROVE/REJECT are acted on as given |
| Trust | CHECKED_BY_CODE |
| If the model fails | First run not SUCCEEDED or empty final text → `DirectorError`; no object → `DirectorError` naming the model and pointing the Owner to Settings → Agenți (`director.py:558-575`); a `blocker` → an ESCALATE letter in the Director's inbox with `owner_attention: True` and `reviewed: 0` (`director.py:576-593`). The evening caller writes the Owner a letter when the review raises (`stages.py:6284-6292`) |
| Can lead to spend | No money; a RESOLVED Publisher HOLD lets the next publish stage use the held metadata, and any decision on a HOLD takes it off the publish path (Oddities 1) |

### Functions here that reach the LLM indirectly

| Function | Reaches the model through | Hops |
|---|---|---|
| `create_agents_router.post_director_review` (`router.py:195-201`), `POST /api/v1/agents/director/review` | `director_review` → `structured_run` → `run_agent_task` | 3 |
| `create_agents_router.post_agent_chat` (`router.py:239-253`) | `history.chat` → `run_agent_task` | 2 |
| `mail.correspondence_round` (`mail.py:866-932`) | `answer_mail` → `structured_run` → `run_agent_task`; and `director_review` | 3 |
| `command.direct_company` (`command.py:866-1066`) | `_choose` → `run_with_strategy` → `run_agent_task` | 3 |

Gateways themselves: `run_agent_task` (distance 0), `structured_run` and `run_with_strategy`
(distance 1). The ensemble's private strategy functions (`_fallback`, `_review`, `_debate`,
`_parallel`) call the model through the `call` closure (`ensemble.py:220-232`), which the static
analysis does not resolve.

### How much of this group is LLM

- 183 functions, 6341 function lines (the router factories' 303 lines also contain their nested
  handlers, which are counted again on their own). 13 functions (7 %) have a static path to the model,
  holding 1347 lines (21 %); the 6 call sites hold 530 lines (8 %). Computed from
  `docs/project/backend_map/inventory.json`.
- What the models decide here: the words of chat answers and letters; whether a letter's matter
  is done; which of the code's computed matters the Director takes up, with what decision and
  what instruction text for the department; which shortlisted topic is filmed; how each inbox
  letter is closed (and with it whether a Publisher HOLD's metadata is released); whether a
  repair she chose waits. What code decides: whether
  any model may be called at all (budget, stop, mode, lifecycle, availability, capabilities,
  health), which model answers, who answers which letter and when, which matters exist, the
  backlog order, the bottleneck, every cap and back-off, whether a repair may run, whether a
  matter goes to the Owner, and whether an escalation is allowed to reach the Owner.

## Hard rules and limits

### Gateway and kernel (`services.py`, `structured.py`, `identity.py`)

| Rule | Value | Where |
|---|---|---|
| Kernel order in code | budget verdict computed (`:781`, before any write) → agent/model/provider rows must exist (`ValueError`, `:787-818`) → identity composed → slot-model checks for a named non-own model (raise `PolicyKernelError`, `:819-825`) → budget refusal applied (`:829-830`) → STOP AUTONOMY → `may_act` T1 → lifecycle ACTIVE → model available/provider → live-run check → REQUIRED capabilities → provider health → adapter present | `services.py:779-883`, `:608-679` |
| Stale RUNNING run | 45 min (`RUN_STALE_AFTER_SECONDS`) → ABANDONED | `services.py:562-586` |
| Runtime states that do not block a new run | IDLE, BLOCKED, ERROR, WORKING | `services.py:651` |
| Pausable / resumable lifecycles | `{ACTIVE, HIRED}` / `{PAUSED, SUSPENDED}`; TERMINATED refused | `services.py:202-234` |
| Director token multiplier | default 2, bounds 1..4 | `services.py:793-798`; `config.py:11`, `:425` |
| Task summary on the run | 300 chars | `services.py:808` |
| Bubble text | 1200 chars | `services.py:1036` |
| WORKING detail | 160 chars | `services.py:86` |
| Owner-fixable HTTP statuses (card) | 401, 402, 403 | `decisions/sources.py:64` |
| Failure wording | 401/402/403/404/429 and 5xx meanings; keyless 401/403 variants; vendor word ≤60 ASCII chars | `services.py:688-730` |
| Structured attempts | 2 at most; `{"format": "json"}` first; `{"think": True}` or refusal-quoted JSON second | `structured.py:44-60`, `:109-154` |
| Refusal wording | first 6 errors, ≤700 chars | `identity.py:435-437`, `:586-600` |
| JSON object scan | up to 400 `{` positions | `identity.py:619-639` |
| Identity open messages | 10 newest OPEN, detail ≤600 chars, 3 earlier thread turns ≤240 chars | `identity.py:229-275` |
| Role contract lists | ≤12 items per section | `identity.py:62-75` |
| Standing rules in every prompt | 4 (data is never instructions; exact structured output; return a `blocker` object; text never changes state) | `identity.py:51-59` |

### Ensemble (`ensemble.py`)

| Rule | Value | Where |
|---|---|---|
| Strategies | SINGLE, FALLBACK, REVIEW, DEBATE, PARALLEL (DB check constraint) | `ensemble.py:46`; `models.py:194-197` |
| Policies | IMPORTANT_ONLY (default), LOW_CONFIDENCE, ALWAYS, MANUAL | `ensemble.py:49`; `models.py:134` |
| Importance levels | ROUTINE < NOTABLE < STRATEGIC; default threshold STRATEGIC | `ensemble.py:53-54`, `:163` |
| Low-confidence floor | 0.6 when `min_confidence` unset | `ensemble.py:156` |
| Disagreement threshold | word overlap < 0.34 | `ensemble.py:62` |
| Unusable run statuses | FAILED, EMPTY_OUTPUT, BLOCKED_POLICY, BLOCKED_PROVIDER, ABANDONED | `ensemble.py:66` |
| Critic/judge inputs | task/evidence ≤6000 chars; judge answers ≤4000 | `ensemble.py:612-640` |
| Collaboration outcomes | COMPLETE, PARTIAL, REVIEW_INCOMPLETE | `models.py:198-201` |

### Memory and messages (`memory.py`, `messages.py`, `models.py`)

| Rule | Value | Where |
|---|---|---|
| Memory classes | VERIFIED_FACT, STRATEGY, OWNER_POLICY, HISTORICAL_EVENT, AGENT_OPINION, TEMP_CONTEXT | `models.py:247-254` |
| Records per run | 12 (`RECALL_LIMIT`) | `memory.py:28` |
| TEMP_CONTEXT lifetime | 3 days | `memory.py:30`, `:80-82` |
| Record content | 600 chars, whitespace collapsed | `memory.py:31`, `:38-39` |
| Default readable classes without a contract | OWNER_POLICY, HISTORICAL_EVENT, TEMP_CONTEXT | `memory.py:120-121` |
| Memory source types | event, run, owner, system | `memory.py:61-62` |
| Message intents | REQUEST_INFO, REQUEST_REVIEW, CHALLENGE, HANDOFF, STATUS, ESCALATE | `models.py:255` |
| Message statuses | OPEN → ANSWERED → RESOLVED; a RESOLVED letter cannot be resolved again | `models.py:256`; `messages.py:175-205` |
| Subject / letter / resolution / excerpt | 200 / 8000 / 2000 / 300 chars | `messages.py:52`, `:79`, `:192`, `:119` |

### Mail (`mail.py`)

| Rule | Value | Where |
|---|---|---|
| Letters answered per round | 6 | `mail.py:75` |
| Letters that wait for an answer | REQUEST_INFO, REQUEST_REVIEW, CHALLENGE, HANDOFF (not STATUS/ESCALATE) | `mail.py:79` |
| Thread length that stops automatic answers | 8 letters | `mail.py:83` |
| Director reviews per hour | 3 `director_review` runs (not reviews: a two-attempt review counts 2); rations only the mail-triggered review — the evening passes and the Owner's button are counted but not refused | `mail.py:89`, `:588-597`, `:921-923` |
| Decided-thread window | 1 h | `mail.py:92` |
| One employee's letters in one thread | ≥15 min apart (Owner's letters answered at once) | `mail.py:97`, `:732-736` |
| Back-off after a failed answer | 300 s × 2^(n-1), max 6 h | `mail.py:102-103`, `:832` |
| Failing model | 3 consecutive failed attempts; runs read: 24 | `mail.py:108`, `:113`, `:638-666` |
| Provider failures / model faults | FAILED, BLOCKED_PROVIDER / + EMPTY_OUTPUT | `mail.py:117`, `:121` |
| Same-request similarity | 0.6 | `mail.py:125` |
| Needs that name nothing | "", "-", n/a, none, nothing, nu, nimic, … | `mail.py:129-131` |

### Director (`director.py`)

| Rule | Value | Where |
|---|---|---|
| Inbox letters per review | 12 | `director.py:59` |
| Review actions | ACKNOWLEDGE, REQUEST_INVESTIGATION, APPROVE, REJECT, ESCALATE_TO_OWNER | `director.py:60` |
| Owner matter kinds | security, credentials, legal, licence, license, account, owner_question | `director.py:91-93` |
| Owner matter words | regex: authorise a site/host/domain/model, password, token, credential, API key, login, OAuth, account names (YouTube, Google, RunPod, ElevenLabs), security, legal, licence, copyright | `director.py:94-100` |
| Defect words | tool, defect, bug, identical prompt, unpriced, schema, crash, traceback, exception (RO/EN) | `director.py:102-106` |
| Review payload / topic payload | 16000 / 12000 chars | `director.py:530`, `:215` |
| Evening review passes | up to 3 per evening while letters remain (caller) | `stages.py:6264-6283` |

### Command loop (`command.py`)

| Rule | Value | Where |
|---|---|---|
| Data maturity | 0 measured films = COLD_START, <10 = EARLY_DATA, else MATURE | `command.py:86-87`, `:252-258` |
| Assignments per loop | 3 | `command.py:156` |
| Decisions per matter before the Owner | 3 (all time, all DirectorDecision rows for the key) | `command.py:160`, `:908-915`, `:1033` |
| Repairs per loop | 6 (a 7th or later repair pick is neither repaired nor assigned this loop) | `command.py:166`, `:971`, `:1024-1025` |
| Repair repetition window | 24 h, ≥3 → Owner card | `command.py:167`, `:916-926`, `:987-988` |
| Repairs that run unasked when left out | T0, T1, T2 | `command.py:170`, `:949-956` |
| Owner-only decisions | STOP, SCALE | `command.py:152` |
| Decisions that hold a repair | HOLD, COOLDOWN, REDUCE, STOP (+ NEEDS_MORE_DATA where not suggested) | `command.py:189`, `:982-984` |
| Default review | 3 published films unless NEEDS_MORE_DATA | `command.py:1255-1257` |
| Payload / evidence | 14000 / 8000 chars | `command.py:1147`, `:1172` |
| Loop schedule | every 21600 s (4 per day), first run 30 min after start, missed runs skipped | `backend/app/main.py:550-560` |

### Vision and language

| Rule | Value | Where |
|---|---|---|
| Frame width for QC | 1080 px (`SPAN_FRAME_WIDTH`) | `vision.py:48-52` |
| ffmpeg cut | 2 threads, 300 s timeout; nothing returned if any frame is missing | `vision.py:80-113` |
| Publishing language guard | only for `en`; diacritics ăâîșț or ≥2 listed Romanian words → hold | `language.py:27-32`, `:49-70` |

### State machines

- `Agent.lifecycle`: ACTIVE ⇄ PAUSED/SUSPENDED (pause from ACTIVE/HIRED, resume from
  PAUSED/SUSPENDED), TERMINATED final (`services.py:202-284`).
- `Agent.runtime_state`: IDLE → THINKING (model call) → IDLE; IDLE → WORKING (paid work without a
  model, `mark_working`) → IDLE; a THINKING with no live run is reset to IDLE by the next run
  (`services.py:57-133`, `:649-668`, `:888`, `:983`). A run is allowed beside WORKING
  (`:651`) and sets THINKING then IDLE unconditionally, so a model call made during paid work
  ends the WORKING state early (Oddities 46).
- `AgentRun.status`: RUNNING → SUCCEEDED / EMPTY_OUTPUT / FAILED; RUNNING older than 45 min →
  ABANDONED; blocked runs are written directly as BLOCKED_POLICY / BLOCKED_PROVIDER /
  BLOCKED_CAPABILITY / BLOCKED_BUDGET or a `may_act` status (`services.py:829-883`, `:946-975`).
- `AgentMessage.status`: OPEN → ANSWERED (a reply, an investigation requested, an escalation) →
  RESOLVED (a decision, the Owner's resolve) (`messages.py:175-205`; `director.py:409-464`).
  Only RESOLVED is final: `resolve_message` refuses a RESOLVED row but lets an ANSWERED row be
  answered again or resolved (`messages.py:189-190`).
- Letter `body_json` flags used as state: `answer_attempts` (back-off), `blocked` (repeated
  request), `executed_by_worker` (a durable task owns it), `owner_attention`, `to: "Owner"`
  (`mail.py:187-195`, `:350-379`, `:843`; `messages.py:49-51`).

## Modules

### `app.agents.services` — `backend/app/agents/services.py` (1749 lines)

The gateway, the Policy Kernel's agent gate, the workforce registry (roles, capabilities,
providers, models, agents) and its seeding, and the "working without a model" status. Module
docstring `services.py:1-15`.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `mark_working` | 57 | Sets the role's ACTIVE employee to WORKING, emits `agent.state_changed` (outbox); returns her id; swallows every error | Paid renders ran in an employee's name while the office showed IDLE (`:60-66`); "a paid render must never die because a status line failed" (`:67-68`) | CODE_RULE |
| `mark_idle` | 98 | Back to IDLE only if still WORKING | Do not overwrite a state something else took (`:106-107`) | CODE_RULE |
| `at_work` | 127 | Context manager around `mark_working`/`mark_idle`; used by `app.media.assembler` | IDLE again even if the work fails | CODE_RULE |
| `list_roles` | 141 | Roles with REQUIRED and PREFERRED capabilities in separate fields | A preference shown as a requirement would mislead the Owner (`:146-149`) | — |
| `list_agents`, `get_agent` | 174, 180 | Read projections (`AgentView`) | API | — |
| `_refuse_lifecycle` | 207 | Raises `AgentLifecycleRefused` (code + Romanian sentence) for a no-op pause/resume or a TERMINATED employee | Until 2026-09-25 a resume of a working employee wrote a false «a reluat lucrul» (`:191-194`) | CODE_RULE |
| `pause_agent` | 237 | ACTIVE/HIRED → PAUSED, event `agent.paused` | Owner pause | OWNER |
| `resume_agent` | 262 | PAUSED/SUSPENDED → ACTIVE, event `agent.resumed` | Owner resume | OWNER |
| `list_providers`, `list_provider_models` | 287, 293 | Providers; a provider's models with capability names | API | — |
| `sync_provider_models` | 313 | Calls `adapter.list_models()`; upserts models as DECLARED_BY_PROVIDER with availability and notes; records declared capabilities, creating unknown capability names (`record_declared`, `:348-391`); new models get `text_generation` and a `provider.model_discovered` event; models no longer listed become unavailable; provider → HEALTHY ("the only place allowed", `:450-453`); then `apply_llm_allocation` and `prefer_capable_models`, each failure only logged | Discovery is the only source of truth about models; the preference had reached nobody admitted after the first start (2026-09-18, `:478-487`) | EXTERNAL (+ CONFIG allocation) |
| `_check_required_capabilities` | 520 | Raises `BLOCKED_CAPABILITY` if the answering model lacks a REQUIRED capability | Spec: fallback must preserve the role contract (`20_EMPLOYEE_AGENT_SPEC.md` "Fallback behavior") | CODE_RULE |
| `_has_live_run` | 566 | True for a RUNNING run younger than 45 min; closes older ones as ABANDONED | A dead process leaves a RUNNING row, not an unexplained flag | CODE_RULE |
| `_studio_settings` | 590 | `lru_cache`d `Settings()` or None | 20 callers carry no settings (decision log `16_DECISION_LOG.md:2052-2054`) | CONFIG |
| `_assert_policy_allows_run` | 608 | STOP, `may_act`, lifecycle, model, live run (and stale-THINKING reset), capabilities, provider health | The kernel gate (ADR-016 "Owner Policy Kernel", `16_DECISION_LOG.md`) | CODE_RULE / OWNER / EXTERNAL |
| `_failure_detail` | 697 | Error class + HTTP status + vendor word + Romanian meaning, never the message | A vendor's text can carry a URL with a key (`:701-702`) | CODE_RULE |
| `run_agent_task` | 733 | The gateway (see LLM involvement) | Every model call is identity-composed, gated and recorded | CODE_RULE around EXTERNAL |
| `seed_role_task_types` | 1143 | Appends seed task types a role lacks, event `role.task_types_extended` | `sound_design` (2026-10-11) never reached existing studios (`:1146-1150`) | CONFIG |
| `seed_missing_workforce` | 1179 | Hires seed employees whose role nobody holds; creates the role from `_ROLE_DEFINITIONS`; uses the seed model if available, else the Director's model | The Accountant role was added after studios existed (`:1182-1187`) | CONFIG |
| `seed_role_preferences` | 1283 | Writes PREFERRED `vision` for VideoEditor (`ROLE_PREFERENCES`, `:1068`) | A preference belongs to the role, never a gate (`:1286-1290`) | CONFIG |
| `prefer_capable_models` | 1331 | Moves an employee to an available model with REQUIRED+PREFERRED capabilities; event `agent.model_preferred` (deliberately not `agent.model_assigned`, `:1416-1418`) | PREFERRED was read by no code (2026-09-18, `:1334-1336`) | CODE_RULE over EXTERNAL |
| `owner_home_model` | 1465 | The model the Owner last assigned (origin None or OWNER), skipping Director repairs | Where `repairs.agent_health` returns an employee once her model works | OWNER (read) |
| `_owner_chose_models` | 1482 | Whether the employee's latest `agent.model_assigned` (Director repairs skipped) is the Owner's: a newer `agent.model_preferred` → no; an `assignment_origin` → yes unless SEED_ALLOCATION; a legacy event without the ensemble fields → yes; an ensemble event → yes unless every slot equals the seed allocation (resolved with `resolve_model`); unreadable seed → yes | "Protect explicit assignments even when they match the current seed configuration" (`:1483-1490`); read by `prefer_capable_models` | CODE_RULE over OWNER history |
| `seed_initial_workforce` | 1553 | Runs `_seed_initial_workforce` then the five idempotent seeds above | Called by `scripts/bootstrap.py`, which `scripts/start.py:602` runs at every start (also `app/demo.py`, `scripts/e2e_server.py`); so every start refreshes contracts, task types and preferences | CONFIG |
| `_seed_initial_workforce` | 1575 | Only when no agent exists: capabilities (incl. `vision` as a row), provider `local-ollama` at `http://127.0.0.1:11434` NOT_CONFIGURED, seed models SEEDED_UNVERIFIED and unavailable with the four text capabilities, roles with REQUIRED `text_generation`, the seed agents ACTIVE/IDLE | "Seeding writes intent, never observation" (`:1562-1565`) | CONFIG |

Helpers: `_assignments` (1447) — `agent.model_assigned`/`agent.model_preferred` events newest
first without `DIRECTOR_REPAIR` origin; `_owner_chose_models` (1482, in the table above);
`_allocation_entry` (1521) — the role's entry in the seed file; `_model_capabilities` (1540) —
capability names of a model; `AgentLifecycleRefused.__init__` (197) and
`PolicyKernelError.__init__` (514) — exception constructors carrying `code` / `block_reason` +
`status`.

Data read/written: `agent`, `agent_run`, `role`, `capability`, `role_capability`,
`model_record`, `model_capability`, `provider_record`, `owner_policy` (read), `domain_event`
and outbox. Events: `agent.state_changed`, `agent.run_completed`, `agent.message_sent`,
`agent.paused`, `agent.resumed`, `provider.model_discovered`, `provider.registered`,
`role.created`, `role.task_types_extended`, `agent.hired`, `agent.model_preferred`. Files:
`config/workforce_seed.json` (via `seed_config`). External calls: the provider adapter's
`generate` and `list_models` (network; token cost recorded as `cost_vr`).

### `app.agents.structured` — `backend/app/agents/structured.py` (166 lines)

The two-attempt structured-answer ladder (module docstring `:1-23`). `NATIVE_THINKING_MODELS`
(`:42`) is an in-process record of models that answered only with thinking on; nothing reads it
for decisions.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `structured_run` | 76 | Up to two `run_agent_task` calls; parses with `read_structured`; attaches `refusal` and an `error_detail` note to the returned run dicts | Narrating models (glm-5.3) and length-refused objects (kimi-k3, 2026-10-11) | CODE_RULE |
| `_carry_refusal` | 63 | A second attempt without an object keeps the first attempt's refusal on its note | Review of 2026-10-11 (`:64-66`) | CODE_RULE |

Data: only through `run_agent_task`. The `refusal` is set on the returned dict, not on the stored
run row.

### `app.agents.identity` — `backend/app/agents/identity.py` (662 lines)

Who an employee is (system prompt + manifest), role contracts, and the shared structured-answer
parser/fitter used across the backend. `IDENTITY_VERSION = "identity-v2"` (`:38`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `RoleContract.scope` | 77 | Validates memory scope classes | Unknown classes refused | CODE_RULE |
| `load_role_contracts` | 94 | Reads `config/role_contracts.json` (version 6 at mapping time) | Contracts are data | CONFIG |
| `seed_role_contracts` | 99 | Fills empty contracts; never overwrites one with a version; event `role.contract_seeded` | The Owner's edits stand (`:102-104`) | CONFIG |
| `set_role_contract` | 139 | Owner edit with version check; event `role.contract_set` | Optimistic concurrency | OWNER |
| `contract_view` | 161 | Read projection | API | — |
| `_persona_section` | 192 | The Character Bible's speech style, habits, traits, values and typical phrases as prompt lines, opened by "It never changes what you approve, reject, verify or publish" | Persona is style, never authority (`04_AGENT_SYSTEM.md` §19 "Personality / Persona layer") | CONFIG (Character Bible data) |
| `compose_identity` | 278 | System prompt: name/role/studio, MISSION, YOU MAY DO, YOU MUST NEVER, REPORTS TO, contract sections, persona (style only), WHAT YOU REMEMBER (recall), WHAT IS ASKED OF YOU RIGHT NOW (≤10 open letters addressed to this employee's id + thread turns; the Director's NULL-addressed inbox is not included), STANDING RULES; manifest with ids, versions and SHA-256. YOU MAY DO / YOU MUST NEVER are text only: nothing enforces them | Spec §16 envelope, §19 persona; "Sarah did not know she was Sarah" | CODE_RULE over CONFIG/OWNER data |
| `identity_view` | 346 | What the Owner sees in the inspector: prompt, parts, character, contract, memory | Transparency | — |
| `clipped`, `joined` | 377, 392 | Before-validators: cut a string; join a list of lines then cut | One long field lost a whole episode (`:380-383`, `:395-397`) | CODE_RULE |
| `cut_at_word` | 440 | Cut at a word boundary | Keep the opening, drop the tail | CODE_RULE |
| `_fit_value` | 524 | Fits one value to its annotation: picks a union member by shape, matches Literal/Enum/choice-pattern code words, truncates lists to `max_length` and fits their items, recurses into nested models, cuts strings at a word boundary; numbers are never clamped | The per-field worker of `fit_to_schema` | CODE_RULE |
| `fit_to_schema` | 568 | Recursively fits a decoded dict to a pydantic model (strings, lists, nested models, Literal, Enum, code-word patterns); nothing added or retyped | Cyclotron film, 2026-10-11 (`:408-418`) | CODE_RULE |
| `refusal_words` | 586 | Pydantic errors in plain words | Quoted back to the model and the Owner | CODE_RULE |
| `read_structured` | 603 | Tries every `{` (≤400) as a JSON object, fits and validates; returns the object, or the closest refusal, or (None, None) when no object | Distinguishes "ask again corrected" from "ask again with thinking" | CODE_RULE |
| `parse_structured` | 642 | `read_structured(...)[0]` | Used by many modules | CODE_RULE |
| `blocker_of` | 659 | Parses `{"blocker": {"reason", "needs"}}` | Spec: an employee lacking capability/evidence/budget/authority returns a structured blocker (`20_EMPLOYEE_AGENT_SPEC.md` "Escalation") | CODE_RULE |

Helpers: `_lines` (184), `_persona_section` (192, in the table), `_open_messages` (229),
`_message_line` (252), `_thread_lines` (263), `_limit_of` (455), `_pattern_of` (464), `_unwrap`
(475), `_code_word` (484), `_fits` (502), `_fit_value` (524, in the table).

Data read: `role`, `character_bible`, `memory_record`, `agent_message`, `agent`. Written:
`role.work_contract_json`, `memory_scope_json`, `contract_version`; events
`role.contract_seeded`, `role.contract_set`. File: `config/role_contracts.json`.

### `app.agents.ensemble` — `backend/app/agents/ensemble.py` (921 lines)

Multi-model strategies and the starting model allocation (module docstring `:1-27`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `slots` | 102 | The agent's primary/secondary/tertiary models with availability; a missing model reported unusable | "never replaced by a guess" (`:105-106`) | CONFIG |
| `should_collaborate` | 131 | Whether extra models are earned, with a recorded reason | Extra models cost money (`:15-18`) | CONFIG + CODE_RULE |
| `agreement` | 169 | Jaccard overlap of content words (`app.factual.editorial.content_words`) | Crude, cheap, cannot be inflated by writing more (`:59-61`) | CODE_RULE |
| `run_with_strategy` | 182 | Dispatches to the configured strategy or a single call | See gateways | CONFIG |
| `_fallback` | 311 | Primary, then available secondary/tertiary until a usable answer; both fallback attempts are stored under the one key `FALLBACK`, so when both run the record keeps only the tertiary's run id (`:333-338`, `:700-702`) | A failed researcher has no answer otherwise | CODE_RULE |
| `_review` | 359 | Primary → critic (`:critique`) → primary final (`:final`) with `_SYNTHESIS` + critique. Outcome REVIEW_INCOMPLETE when the critic ran and gave nothing usable, or when the critic is unavailable and the caller passed `require_review`; an unavailable critic without `require_review` is PARTIAL (`:383-399`, `:413-429`) | Keeps the employee the author (`:377-379`) | LLM (final) |
| `_debate` | 459 | Primary + peer; judge only on disagreement; primary reconciles | "an arbiter for a disagreement that does not exist is money for nothing" (`:476-477`) | LLM (final) / CODE_RULE (judge trigger) |
| `_parallel` | 547 | Primary + all available slots; primary synthesises. The tertiary's run is recorded in the `JUDGE` part although it was asked as a peer (task suffix `:peer`, `:565-568`) | — | LLM (final) |
| `_critique_prompt` | 612 | Critic instructions + task/evidence/answer in inert boundaries | "Not the whole company" (`:615-616`) | CODE_RULE |
| `_finish` | 643 | Writes `LlmCollaboration` + event `agent.llm_collaboration_recorded`; returns the final run with `collaboration` | "the studio decided" vs "here is what was considered" (`models.py:185-190`) | CODE_RULE |
| `collaborations` | 743 | Lists collaboration rows with primary status | API | — |
| `resolve_model` | 789 | Finds a model by name, trying `:cloud`/`-cloud` spellings; never creates one | Vendor spelling drifts (`:792-796`) | CODE_RULE |
| `apply_llm_allocation` | 814 | Applies `llm_allocation` through `integrations.services.assign_agent` with `assignment_origin="SEED_ALLOCATION"`; `force` exists for an explicit Owner hand-over | Starting allocation without overwriting the Owner (`:819-827`) | CONFIG |

Helpers: `_usable` (307), `_judge_prompt` (630). Data: `agent`, `agent_run`, `model_record`,
`llm_collaboration`, `domain_event`. Event: `agent.llm_collaboration_recorded`.

### `app.agents.models` — `backend/app/agents/models.py` (317 lines)

ORM only (no functions). Tables: `role` (incl. `work_contract_json`, `memory_scope_json`,
`contract_version`), `capability`, `role_capability` (`requirement_level` REQUIRED/PREFERRED),
`provider_record`, `model_record`, `model_capability` (`confidence`), `agent` (slots, strategy,
policy, thresholds, lifecycle, runtime state, `cost_limit_per_task`, `max_concurrent_tasks`,
version), `agent_run` (indexes `ix_agent_run_agent_started`, `ix_agent_run_started`;
`context_json` manifest), `llm_collaboration` (check constraints on strategy/outcome),
`tool_receipt` (immutable by DB trigger, migration 0002), `memory_record`, `agent_message`
(thread fields from migration 0027). Constants `MEMORY_CLASSES`, `MESSAGE_INTENTS`,
`MESSAGE_STATUSES` (`:247-256`).

### `app.agents.router` — `backend/app/agents/router.py` (387 lines)

FastAPI routes mounted at `/api/v1` (`backend/app/main.py:962-963`); every route requires the
Owner token (`Depends(require_owner)`, `router.py:84`, `:347`; `backend/app/security.py:60`).

| Route handler | Line | Method and path | What it does | Decided by |
|---|---|---|---|---|
| `get_roles` | 87 | GET `/agents/roles` | `list_roles` | — |
| `put_role_contract` | 91 | PUT `/agents/roles/{role_id}/contract` | `set_role_contract`; 422 on conflict | OWNER |
| `get_messages` | 102 | GET `/agents/messages` | filter by status/agent | — |
| `get_owner_letters` | 110 | GET `/agents/messages/owner` | `letters_for_owner` | — |
| `get_thread` | 115 | GET `/agents/messages/threads/{thread_id}` | `thread_view` | — |
| `post_reply` | 122 | POST `/agents/messages/{message_id}/reply` | Owner letter (REQUEST_INFO, `from_agent_id=None`) to the sender or a named agent; an OPEN letter to the Owner becomes ANSWERED | OWNER |
| `post_forward` | 160 | POST `/agents/messages/{message_id}/forward` | HANDOFF in the thread to a named agent | OWNER |
| `post_resolve_message` | 180 | POST `/agents/messages/{message_id}/resolve` | RESOLVED by "Owner" | OWNER |
| `post_director_review` | 196 | POST `/agents/director/review` | Runs `director_review` now (LLM, 3 hops); `DirectorError` → 422 | OWNER triggers, LLM decides |
| `get_agents` | 204 | GET `/agents/` | list | — |
| `get_agent_detail` | 208 | GET `/agents/{agent_id}` | detail or 404 | — |
| `get_agent_identity` | 218 | GET `/agents/{agent_id}/identity` | `identity_view` + 20 messages | — |
| `get_agent_history` | 230 | GET `/agents/{agent_id}/history` | `agent_timeline` | — |
| `post_agent_chat` | 240 | POST `/agents/{agent_id}/chat` | `history.chat` (LLM, 2 hops) | OWNER asks, LLM answers |
| `get_collaborations` | 256 | GET `/agents/{agent_id}/collaborations` | `ensemble.collaborations` | — |
| `get_agent_memory` | 273 | GET `/agents/{agent_id}/memory` | `list_memory` | — |
| `post_invalidate_memory` | 282 | POST `/agents/{agent_id}/memory/{record_id}/invalidate` | `memory.invalidate` with reason | OWNER |
| `run_agent` | 297 | POST `/agents/{agent_id}/run` | `run_agent_task` with the Owner's objective (call site 1) | OWNER asks, LLM answers |
| `post_pause_agent` | 320 | POST `/agents/{agent_id}/pause` | 409 on a no-op | OWNER |
| `post_resume_agent` | 332 | POST `/agents/{agent_id}/resume` | 409 on a no-op | OWNER |
| `get_providers` | 350 | GET `/providers/` | with `runtime_status` from the registry cache | — |
| `get_provider_models` | 357 | GET `/providers/{provider_id}/models` | models with capabilities | — |
| `sync_models` | 364 | POST `/providers/{provider_id}/sync-models` | `sync_provider_models`; unreachable provider → 503 "nothing was recorded" | OWNER triggers, EXTERNAL answers |
| `create_agents_router` | 83 | — (factory, prefix `/agents`) | Builds the 20 `/agents` handlers above behind `Depends(require_owner)`; its `registry` parameter is unused (handlers read `request.app.state.registry`) | — |
| `create_providers_router` | 346 | — (factory, prefix `/providers`) | Builds the 3 `/providers` handlers above behind `Depends(require_owner)`; uses its `registry` parameter | — |

`create_agents_router` (83) and `create_providers_router` (346) are the factories. Request
schemas: `ResolveMessageCommand`, `ReplyCommand`, `ForwardCommand`, `ChatCommand`,
`InvalidateMemoryCommand` (`:46-72`); `DATABASE_FAULT` Romanian 500 text (`:77-80`, "PAGE-11").

### `app.agents.vision` — `backend/app/agents/vision.py` (185 lines)

Who can look at a picture and how frames reach them (module docstring `:1-23`). Re-exports
`VISION`, `frames_for`, `model_can_see` from `app.agents.editorial`.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `frames_at` | 55 | One ffmpeg pass selecting exact frame numbers, scaled to 1080 px PNGs; `{}` on any failure or count mismatch | QC must see the frame the viewer sees, at delivered size (`:48-51`, `:63-70`) | CODE_RULE |
| `vision_agent` | 116 | First-hired ACTIVE employee whose primary model declares `vision`, preferred roles first (the last-hired holder when a role has several); the model's availability is not checked | QC asks the Video Editor first; the Director's model declared no vision (`:9-14`) | EXTERNAL + CODE_RULE |
| `seeing_model` | 162 | The model id an employee looks with: own, own slots, then the seeing employee's | 2026-10-10: the Director had to judge stills on a writing model (`:169-171`) | EXTERNAL + CODE_RULE |

Helper: `_sees` (145). External: the ffmpeg binary (`app.media.toolchain.find_ffmpeg`); files
written under the caller's `work_dir` (old `span_frame_*.png` deleted first).

### `app.agents.memory` — `backend/app/agents/memory.py` (184 lines)

Memory records per `04_AGENT_SYSTEM.md` §9 and role scope per `20_EMPLOYEE_AGENT_SPEC.md`
"Memory scope" (module docstring `:1-12`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `remember` | 42 | Validates class and source type, clips, dedupes live identical records, sets TEMP_CONTEXT expiry | Memory is written by services from outcomes, with provenance | CODE_RULE |
| `invalidate` | 101 | Marks a record invalid with a reason (never deletes) | What an agent was told can be re-read | OWNER (route) / CODE_RULE |
| `readable_classes` | 111 | The role's read scope, or a default | Role-scoped reading | CONFIG |
| `recall` | 124 | 12 newest live readable records, studio-wide or own | "a briefing, not an archive" (`:26-27`) | CODE_RULE |
| `memory_view` | 146 | Projection | API | — |
| `agent_for_role` | 161 | First-hired ACTIVE employee of a role | Used across the backend to find "the Director", "the Accountant" | CODE_RULE |
| `list_memory` | 171 | Up to 200 records, own and studio-wide | API | — |

Helper: `_clip` (38). Data: `memory_record`.

### `app.agents.messages` — `backend/app/agents/messages.py` (284 lines)

Typed letters in threads (`20_EMPLOYEE_AGENT_SPEC.md` "Communication"; migration 0027).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `post_message` | 30 | Validates intent and subject; `to_owner` addresses the Owner (body `to: "Owner"`, `owner_attention`); dedupes an OPEN Owner letter with the same subject; threads replies; event `agent.message_posted` (outbox) | "one evening she was asked the same question nine times" (`:56-58`) | CODE_RULE |
| `forward_message` | 127 | HANDOFF `Fwd:` in the same thread | The receiver reads the exchange | CODE_RULE |
| `thread_messages` | 153 | A thread oldest first (pre-0027 rows are their own thread) | Context for replies | — |
| `thread_view` | 164 | Projection | API | — |
| `resolve_message` | 175 | ANSWERED or RESOLVED with resolution and resolver; refuses a RESOLVED one; event `agent.message_resolved`/`agent.message_answered` | Closing letters is the only state change | CODE_RULE |
| `is_for_owner` | 208 | `body_json.to == "Owner"` | Owner letters share the inbox's NULL addressee | CODE_RULE |
| `open_messages` | 214 | OPEN letters to an agent, or the Director's inbox without Owner letters; for the inbox it reads the `2 × limit` newest NULL-addressed OPEN rows and then drops the Owner's, so open Owner letters can push inbox letters out (Oddities 41) | The Director must not read letters addressed to the Owner | CODE_RULE |
| `letters_for_owner` | 232 | Owner letters, newest first | The Owner's mail window | — |
| `message_view`, `list_messages` | 243, 271 | Projections | API | — |

Data: `agent_message`, `agent` (names). Events through the outbox (reach the live office).

### `app.agents.history` — `backend/app/agents/history.py` (140 lines)

One timeline of an employee's runs, letters and memory, and the Owner's chat (module docstring
`:1-9`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_run_item` | 37 | A run as a line: `asked` = the run's summary or objective, `prompt` = the full objective | Nine hundred words of instructions per entry hid the difference between runs (`:40-43`) | — |
| `agent_timeline` | 66 | Merges runs, messages and memory (memory copies of listed messages dropped from the view) | "the studio saying everything twice" (`:94-100`) | — |
| `chat` | 111 | Call site 2 | The Owner talks to an employee without inventing a task type | LLM (INFORMATIONAL) |

### `app.agents.language` — `backend/app/agents/language.py` (70 lines)

The publishing-language rule (Owner: everything posted is in English; module docstring `:1-11`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `language_name` | 35 | Code → English name | Prompt wording | — |
| `audience_language_line` | 39 | One prompt sentence fixing the audience language | Used by editorial, reviews, factual pipeline, story | CONFIG (`content_language`) |
| `looks_like_english` | 49 | False on Romanian diacritics or ≥2 listed Romanian words | Catches an employee answering in the office's language | CODE_RULE |
| `publication_language_hold` | 61 | A hold reason for `en` titles/descriptions that are not English; used by `reviews.prepare_publication` | Hold rather than ship | CODE_RULE |

### `app.agents.schemas` — `backend/app/agents/schemas.py` (108 lines)

Pydantic views: `CapabilityView`, `RoleView` (with `required_capabilities` and
`preferred_capabilities`), `ProviderView`, `ModelView`, `AgentView` (slots and policy fields),
`RunAgentCommand` (`command_id` UUID, `task_type` ≤100, `objective` ≤2000, `max_tokens` ≤8192,
`temperature` 0..2), `AgentRunView`. No functions.

### `app.agents.seed_config` — `backend/app/agents/seed_config.py` (62 lines)

Editable initial workforce (`config/workforce_seed.json`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `WorkforceSeed.consistent` | 40 | No duplicate model or agent names; every agent's model is proposed; labels non-empty ≤200 | A bad seed fails loudly | CODE_RULE |
| `load_seed_config` | 60 | Validates and returns the seed (models, agents, `llm_allocation` of `LlmAllocation` rows) | Allocation is configuration, not architecture (`:14-18`) | CONFIG |

### `app.agents.mail` — `backend/app/agents/mail.py` (932 lines)

Employees answer their letters; the Director reads what came back (module docstring `:1-33`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `answer_mail` | 443 | Call site 3 | One run reads the thread and writes a reply in the employee's voice | LLM_CHECKED_BY_CODE |
| `_close_earlier` | 284 | Closes the sender's earlier open asks to this employee in the thread; a HANDOFF closes only when `done`; a non-done reply lifts an earlier `blocked` mark | A reply to the Owner had closed the Director's question (`:296-300`) | LLM (`done`) + CODE_RULE |
| `_hold_repeated_request` | 326 | Does not send a repeat; answers the sender's questions with "same answer as the letter of …", marks the sender's HANDOFFs `blocked`, posts one STATUS to the Director's inbox, event `agent.mail_repeated` | Repeated asks went round in circles (2026-10-11) | CODE_RULE |
| `reviews_this_hour` | 588 | Count of `director_review` runs started in the last hour | `REVIEWS_PER_HOUR` | CODE_RULE |
| `_latest_attempts` | 607 | The employee's latest attempts on one model (24 newest runs, grouped by correlation: a first try plus its second try is one attempt), each with the status of its last run | A narrated first try followed by a refused second one is one failed attempt, not a success and a failure (`:610-612`) | CODE_RULE |
| `_model_resumes_at` | 638 | When a failing model may be tried again (≥3 failed attempts, 300 s × 2^(n-3), ≤6 h) | 30 letters each on its own clock asked a refusing model on 135 of 148 passes (`:644-647`) | CODE_RULE |
| `_backing_off` | 669 | Whether a failed letter still waits; ends on a model change, or when a newer attempt on the model succeeded after a provider failure | A narrated first try voided the wait at once (`:681-684`) | CODE_RULE |
| `_addressees_turn` | 697 | Whether the newest letter of a sender is the addressee's turn now | See rules | CODE_RULE |
| `letters_awaiting_answer` | 739 | Up to 6 letter ids, longest waiting first, one per (thread, addressee) per round, one try per failing employee | The 2026-10-11 double answers | CODE_RULE |
| `note_failed_answer` | 803 | Writes `answer_attempts` on the letter (count per model, total, retry_after, error, run status/id) | The wait outlives the pass and the process | CODE_RULE |
| `correspondence_round` | 866 | Skips when autonomy is stopped; answers waiting letters; decides whether to run (or defer) a Director review | Called by the worker after every pass (`backend/app/workflows/worker.py:757-760`) | CODE_RULE (+LLM inside) |

Helpers: `MailReply._words_not_placeholder` (160), `MailError.__init__` (171), `_when` (179),
`_owed` (187), `_thread_text` (198), `_books_for` (211), `_answered_letter` (230), `_last_reply`
(236), `_real_need` (254), `_repeats` (260), `_studio_clock` (276), `_model_of` (600),
`_latest_attempts` (607, in the table), `_unread_replies` (848).

Data: `agent_message` (letters, `answer_attempts`, `blocked`), `agent_run` (attempt history,
review count), `agent`, `model_record`, `provider_record`, `owner_policy`. Events:
`agent.message_posted`, `agent.message_answered`, `agent.mail_repeated`, `agent.claim_unproven`
(via `reviews.mark_unproven_claims`). Reads the Accountant's books (`economy.accountant.daily_figures`).

### `app.agents.command` — `backend/app/agents/command.py` (1404 lines)

The Director's management loop (module docstring `:1-33`). Departments and their assignable work
(`ASSIGNABLE`, `:92-123`), improvement work when nothing is in flight (`IMPROVEMENT_WORK`,
`:127-148`), work computed by repairs (`ACTION_REPAIRS`, `MATTER_REPAIRS`, `:178-182`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `repair_desk` | 192 | Registered repairs and their summaries | Shown to the Director as `director_repairs` | CODE_RULE |
| `data_maturity` | 252 | COLD_START / EARLY_DATA / MATURE from measured films | "Not a preference — a fact" | CODE_RULE |
| `pipeline` | 261 | Counts per stage, in-flight work, bottleneck, finished ratio | "The bottleneck is not the stage with the most work" (`:264-266`) | CODE_RULE |
| `company_state` | 364 | Read-only snapshot: environment, stop flag, maturity, channels, pipeline, backlog, agents, open decisions, anomalies, growth diagnoses, target video length | One readable shape for the Director and the Owner (`backend/app/runbook/router.py:150-154`) | CODE_RULE |
| `backlog` | 449 | PROPOSED/SELECTED topics by priority with reason | The candidate queue | CODE_RULE |
| `prioritise_backlog` | 473 | Recomputes `TopicIdea.priority` and `priority_reason` (weights in the rules table) | "Not first-in-first-out" (`:476-479`) | CODE_RULE |
| `findings` | 536 | Builds the matters (blockers, bottleneck, growth, anomalies, idle work, due reviews with a `film_cost_report` repair), filters decided repair cases (`repairs.desk.undecided`), appends repair detectors (`repairs.desk.repair_matters`) | "computed, not judged" (`:539-541`) | CODE_RULE |
| `matter_words` | 793 | Matter key → Romanian words for the page | Owner-readable | — |
| `due_reviews` | 824 | OPEN decisions (not repairs) whose `review_after_videos` (or date) has come | Decisions are reviewed against results | CODE_RULE |
| `direct_company` | 866 | One loop: state → stop check → backlog → findings → drop matters with an OPEN decision → `_choose` → repairs (hold / Owner card / submit) → assignments or escalations | "Its output is action" | CODE_RULE + LLM choice |
| `_suggested` | 1069 | A matter's own suggestion as a `Choice` | Fallback and unasked repairs | CODE_RULE |
| `_choose` | 1083 | Call site 4 | The Director's judgement among computed matters | LLM_CHECKED_BY_CODE |
| `_repair_spec` | 1218 | The repair that carries out a matter (offered, by matter key, by action prefix, or by `repair_action` naming a computed repair) | Nadia was sent work the studio computes itself three times (`:172-177`) | CODE_RULE |
| `_assign` | 1243 | HANDOFF letter (OBSERVAȚIE / INTERPRETARE / ÎNCREDERE / DECIZIE / DE FĂCUT / REVIZUIRE) to the role's employee (to the Director's inbox when nobody holds the role), `DirectorDecision` row OPEN, event `director.decision_recorded`, studio-wide STRATEGY memory quoting the action | A decision with a review condition, not a report | CODE_RULE (content from LLM) |
| `_escalate` | 1352 | An ESCALATE letter to the Owner (`kind: direction_escalation`) stating the case | High-impact or thrice-failed matters are the Owner's | CODE_RULE |
| `review_decision` | 1395 | Closes a decision as REVIEWED with its outcome | Called only by the Owner's route POST `/decisions/{decision_id}/review` (`backend/app/runbook/router.py:207-215`); repairs close their decisions with `repairs.desk.close_decision` and only mention this function in comments | OWNER |

Helpers: `_autonomy_stopped` (439, True when no policy row), `_roles_of` (817), `_computed_by`
(1211).

Data read: `topic_idea`, `script_draft`, `storyboard`, `video_render_job`, `media_asset`,
`quality_control_report`, `publication_record`, `channel_record`, `task_queue_item`,
`director_decision`, `owner_policy`, analytics (`channel_health`, `anomalies`,
`growth_diagnosis`), workforce measurement. Written: `topic_idea.priority`/`priority_reason`,
`agent_message`, `director_decision`, `memory_record`, and through `repairs.desk` a
`task_queue_item` of type DIRECTOR_REPAIR and Owner cards. Events: `director.decision_recorded`,
`agent.message_posted`.

### `app.agents.director` — `backend/app/agents/director.py` (641 lines)

The Director's evening review, topic choice, stage reports and letters to the Owner (module
docstring `:1-12`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `owners_matter` | 114 | Whether a letter is the Owner's to answer: body `kind` in OWNER_MATTER_KINDS, or the letter has no sending employee, or OWNER_MATTER_WORDS match its subject + text + the model's decision note | Owner rule 2026-10-12 | CODE_RULE (over text that includes the model's note) |
| `_developer_defect` | 125 | A STATUS to her own desk (`kind: developer_defect`), resolved at once | A failing tool is the developer's, not the Owner's | CODE_RULE |
| `choose_topic` | 195 | Call site 5 | Runbook §5 selection by the Director | LLM_CHECKED_BY_CODE |
| `file_stage_reports` | 257 | One STATUS per stage outcome, reported by the outcome's own `agent_id` if it names one (the Accountant's close), else the ACTIVE employee whose contract lists the stage, else the Director; TEMP_CONTEXT memory for the reporter | "Deterministic: the report is the stage's own outcome" (`:262-263`) | CODE_RULE |
| `answers_an_investigation` | 314 | A letter titled as an investigation or replying to one | "Investigate: Re: Investigate: …" loops (2026-10-11) | CODE_RULE |
| `threads_decided_since` | 325 | Threads where the Director resolved a letter since a moment | A reply there waits for her next review | CODE_RULE |
| `_apply_decisions` | 345 | Applies the review's decisions with the checks in call site 6 | Decisions are letters and memory, never gate changes (`:6-9`) | LLM_CHECKED_BY_CODE |
| `letter_to_owner` | 469 | ESCALATE letter to the Owner (`kind: owner_letter`) | Written "even when no model answers" (`:474-475`) | CODE_RULE |
| `director_review` | 492 | Call site 6 | Reports in, decisions out | LLM_CHECKED_BY_CODE |

Helper: `_model_status` (50). Data: `agent_message`, `agent`, `role`, `memory_record`,
`domain_event` (`director.review_completed`); reads `measure_workforce`.

### `app.agents.__init__` — `backend/app/agents/__init__.py` (0 lines)

Empty package marker.

## Connections

**Who calls in.**

- Every LLM call in the backend reaches `run_agent_task`; 20 functions call it directly and 38
  call sites use one of the gateways (`docs/project/backend_map/STATS.md`, regenerated at 20abffd;
  37 at b00083c, the 38th being `app.media.second_look._look`). Outside this group:
  `app.agents.reviews`, `app.agents.editorial`, `app.agents.editorial_judgement`,
  `app.agents.repairs.agent_health._probe`, `app.economy.accountant.reconcile_day`,
  `app.factual.*`, `app.media.*` (incl. `prompt_agent`, `model_research`), `app.story.*`,
  `app.research`, `app.runbook.weekly.execute_weekly_review`, `app.integrations.router`.
- The worker: `director_loop` task → `direct_company` (`backend/app/workflows/worker.py:385-398`),
  scheduled every 6 h (`backend/app/main.py:550-560`); after every worker pass →
  `correspondence_round` (`worker.py:757-760`).
- The runbook: selection stage → `choose_topic` (`backend/app/runbook/stages.py:808-818`); the
  evening `post_run` stage → `file_stage_reports`, up to three `director_review` passes, and
  `letter_to_owner` when the review cannot run (`stages.py:6255-6292`); `runbook/router.py`
  exposes `company_state`, `direct_company` (POST `/direct`), decisions and `review_decision`.
- `app.media.assembler` wraps paid work in `at_work`/`mark_working`; `app.media.picture_qc`,
  `app.media.qc` and `app.runbook.preflight` use `vision_agent`/`frames_at`; `app.agents.reviews`
  uses `seeing_model`, `publication_language_hold`. Since 20abffd `app.media.second_look._look`
  (the Director's second look at a still or clip QC refused, before a re-roll or retry is bought)
  finds her with `agent_for_role(session, "Director")`, picks her eyes with
  `seeing_model(session, director_id, *LOOKERS)` and asks through `structured_run` with the
  pictures in `extra` (`backend/app/media/second_look.py:682`, `:686`, `:720-734`).
- `sync_provider_models` is also called by `app.integrations.router` (verifying an LLM
  connection, `backend/app/integrations/router.py:277`); `repairs.agent_health` only names it
  in a comment (`agent_health.py:215`). `owner_home_model` is called by `repairs.agent_health`
  (`agent_health.py:473`, `:622`).
- `identity.parse_structured`, `clipped`, `blocker_of`, `memory.remember`,
  `memory.agent_for_role`, `messages.post_message`/`resolve_message` are used across
  `app.media`, `app.economy`, `app.factual`, `app.story`, `app.analytics`.

**What it calls out to.**

- `app.providers.registry.ProviderRegistry` adapters (`generate`, `list_models`, `cached_status`).
- `app.economy.accountant.may_run_agent` (budget gate) and `daily_figures` (the Accountant's
  books in her mail).
- `app.services.may_act` (autonomy mode), `append_event`, `utc_now`;
  `app.workflows.services.append_event_with_outbox`; `app.db.lock_for_write`.
- `app.decisions.sources.model_run_finished` (reconnect cards).
- `app.agents.reviews.mark_unproven_claims`; `app.agents.repairs` and `repairs.desk`
  (`submit_repair`, `hold_repair`, `ask_owner_about_repair`, `undecided`, `repair_matters`,
  `fingerprint`); `app.integrations.services.assign_agent`.
- `app.analytics.performance` (`channel_health`, `anomalies`, `growth_diagnosis`),
  `app.workforce.services.measure_workforce`, `app.factual.editorial` (`composite`,
  `content_words`), `app.factual.sanitizer.wrap_in_inert_boundary`, `app.media.toolchain.find_ffmpeg`,
  `app.wording`.

**Events emitted.** `agent.state_changed`, `agent.run_completed`, `agent.message_sent`,
`agent.message_posted`, `agent.message_answered`, `agent.message_resolved`, `agent.mail_repeated`,
`agent.llm_collaboration_recorded`, `agent.paused`, `agent.resumed`, `agent.hired`,
`agent.model_preferred`, `role.created`, `role.task_types_extended`, `role.contract_seeded`,
`role.contract_set`, `provider.registered`, `provider.model_discovered`,
`director.review_completed`, `director.decision_recorded`; via helpers `agent.claim_unproven` and
`agent.model_assigned`. Those written with the outbox (`append_event_with_outbox`) reach the live
office: the state changes, bubbles, letters, pause/resume. Events consumed: none directly; the
group reads `domain_event` rows for assignment history (`services.py:1447-1462`,
`ensemble.py:851-858`).

## Owner touchpoints

- **Settings (CONFIG the Owner owns):** daily token ceiling `STUDIO_AGENT_DAILY_TOKEN_BUDGET`
  (`accountant.py:1119`); DAILY/MONTHLY USD budgets (`accountant.py:1124-1127`); Director token
  multiplier `STUDIO_DIRECTOR_TOKEN_MULTIPLIER` (`config.py:425`); autonomy mode and STOP
  AUTONOMY (`OwnerPolicy`, read at `services.py:619-632`, `mail.py:881-883`,
  `command.py:439-443`); each employee's models, strategy and policy (Settings → Agenți, through
  `integrations.services.assign_agent`, read by `ensemble.slots`/`should_collaborate`).
- **Buttons and routes:** pause/resume an employee; edit a role contract; reply to, forward or
  resolve a letter; run the Director's review now; chat with an employee; run an arbitrary agent
  task; invalidate a memory record; sync a provider's models (`router.py`, table above).
- **Cards:** reconnect a provider connection after HTTP 401/402/403
  (`services.py:1025-1027`); a repair the kernel refused or that keeps coming back
  (`command.py:987-1021` → `repairs.desk.ask_owner_about_repair`).
- **Letters to the Owner:** the Accountant's once-a-day letters when the token ceiling is
  reached or a USD budget is exceeded (`may_run_agent` → `_letter_once_a_day`, a `to_owner`
  letter, not a card; `accountant.py:1070`, `:1139`, `:702`); the review's ESCALATE_TO_OWNER when
  `owners_matter` holds (`director.py:420-450`); `command._escalate` for STOP/SCALE,
  thrice-decided matters and unassignable roles (`command.py:1033-1037`, `:1352-1392`);
  `letter_to_owner` from the runbook (`director.py:469-489`); an employee's reply to a letter the
  Owner wrote (`mail.py:476-481`).
- **What the Owner decides here:** whether any agent may think today (stop, mode, budgets,
  ceiling); which model each employee uses and whether a second model is consulted; role
  contracts and memory scope; whether an employee works at all; the answers to escalated
  letters; high-impact company decisions (STOP/SCALE) the Director only proposes.

## Oddities and gaps

1. **A REJECT of a Publisher HOLD releases the held metadata.** `_apply_decisions` resolves
   ACKNOWLEDGE, APPROVE and REJECT identically with status RESOLVED (`director.py:451-464`);
   `reviews.publication_hold` only looks for OPEN letters and `reviews.approved_metadata`
   returns a HOLD's title/description/tags when `message.status == "RESOLVED"`
   (`reviews.py:1715-1748`); the publish stage then uses that metadata, after its own refusal
   check (`stages.py:5773-5795`). The same follows when an ESCALATE_TO_OWNER on a non-Owner matter
   is converted to ACKNOWLEDGE (`director.py:370-378`). A HOLD the review leaves ANSWERED
   (REQUEST_INVESTIGATION, or an escalation the Owner rule keeps) stops blocking as well,
   because `publication_hold` reads only OPEN letters; the publish stage then asks the Publisher
   again (`stages.py:5796-5810`) while the Owner or the investigator has not yet answered.
2. **The module docstring of `director.py` says APPROVE lifts a HOLD** (`director.py:8-9`); the
   code makes no distinction between APPROVE and the other closing actions (item 1).
3. **Unreachable wording in `director_review`.** When the second attempt is EMPTY_OUTPUT, `text`
   (taken from that attempt, `director.py:553`) is empty and the function already raised at
   `director.py:554-557`, so the EMPTY_OUTPUT sentence at `director.py:564-567` cannot be reached.
4. **The status check in `director_review` reads only the first run** (`director.py:554`) while
   the text comes from the second (`:553`).
5. **A failed or empty first structured attempt is never retried.** `structured_run` breaks on a
   non-SUCCEEDED or empty first run (`structured.py:138-140`); the second attempt only follows a
   SUCCEEDED run that had text but no valid object. The module docstring's "if no object at all
   comes back" (`structured.py:11-12`) refers to narration, not to EMPTY_OUTPUT.
6. **`schema_hint` and `format_tokens` are accepted and discarded** (`structured.py:105`); the
   callers in this group still pass a hint (`mail.py:500`, `director.py:543-545`).
7. **A schema refusal is not stored on the run row.** `structured_run` writes `refusal` and the
   refusal note into the returned dict only (`structured.py:147-150`); the persisted `AgentRun`
   of a refused answer stays SUCCEEDED with `error_detail` None. Spec
   `20_EMPLOYEE_AGENT_SPEC.md` "Output validation" says "Malformed output is a failed attempt";
   `04_AGENT_SYSTEM.md` §16 lists "schema validation result" in the run envelope.
8. **Prose is sent as a letter.** `answer_mail` sends a reply that failed the schema as written,
   `done=False` (`mail.py:529-535`), which departs from the same "Output validation" rule.
9. **`PolicyKernelError` is not a `ValueError`.** It subclasses `Exception` (`services.py:511`).
   `run_agent_task` raises it outside the kernel's `try` for an unavailable or under-capable slot
   model (`services.py:819-825`); `command._choose` catches only `ValueError`/`RuntimeError`
   (`command.py:1178`). The ensemble checks `available` before calling a slot
   (`ensemble.py:334`, `:383`, `:481`, `:518`, `:566`) but not REQUIRED capabilities.
10. **Missing-policy handling differs.** `command._autonomy_stopped` treats a missing
    `OwnerPolicy` row as stopped (`command.py:443`); `_assert_policy_allows_run`
    (`services.py:620`) and `correspondence_round` (`mail.py:882`) treat it as not stopped.
11. **The Owner cannot chat while STOP AUTONOMY is on.** `owner_chat` and `POST /agents/{id}/run`
    go through the same kernel, which refuses every run when autonomy is stopped
    (`services.py:619-621`).
12. **`MAX_ATTEMPTS_PER_MATTER` counts all history.** `attempts` counts every `DirectorDecision`
    row ever written for a matter key (`command.py:908-915`), so a recurring key such as
    `publications_failed` is escalated to the Owner on every later occurrence once it has three
    decisions (`command.py:1033-1037`).
13. **Escalations consume assignment slots and leave no decision row.** `others[:MAX_ASSIGNMENTS]`
    is sliced before escalation (`command.py:1026`); `_escalate` writes no `DirectorDecision`
    (`command.py:1352-1392`), so the matter stays "fresh" and is escalated again each loop; only
    `post_message`'s same-subject dedupe of OPEN Owner letters (`messages.py:55-74`) prevents a
    duplicate letter.
14. **`command._escalate` is not filtered by the 2026-10-12 Owner rule.** The review's
    escalations pass `owners_matter` (`director.py:370`); the command loop's escalations for
    STOP/SCALE, repeated matters and unassignable roles (including the APPROVAL bottleneck, whose
    role is `None`, `command.py:644-650`) write to the Owner directly (`command.py:1034-1036`).
15. **The fallback path skips role-less matters.** `_choose`'s fallback keeps only matters with an
    action and an owner role (`command.py:1097`), so the APPROVAL bottleneck is escalated when the
    model names it but ignored when no model answers.
16. **`due_reviews` has a date branch nothing feeds.** `_assign` always writes
    `review_after_at=None` (`command.py:1316`); only `review_after_videos` triggers a review
    (`command.py:844-848`).
17. **Unchosen repairs run anyway.** Every fresh matter offering a T0-T2 repair is appended to the
    Director's choices (`command.py:949-956`); all registered repairs are T0-T2
    (`backend/app/agents/repairs/*.py`, e.g. `agent_health.py:767` T2, `reprice.py:521` T1), so
    her choice can hold a repair (WAIT decisions) but leaving it out does not stop it.
18. **The blocked-review escalation goes to her own inbox.** `director_review` posts an ESCALATE
    with `owner_attention: True` but without `to_owner` (`director.py:578-587`), so
    `is_for_owner` is False and it is not among the Owner's letters (`messages.py:208-211`,
    `:232-240`).
19. **`choose_topic` records the review's template version** (`director.py:223` uses
    `REVIEW_TEMPLATE_VERSION = "director-review-v1"`).
20. **Prompt templates are code constants.** Template ids (`chat-v1`, `mail-v1`,
    `direction-v1`, `director-review-v1`, `identity-v2`) are strings in code; the
    `PromptTemplate` entity of `docs/architecture/30_PROMPT_CONTEXT_MEMORY_ARCHITECTURE.md`
    (status, evaluation baseline, created_by) does not exist in this group.
21. **Silent payload truncation.** Inputs are JSON strings cut by length without a marker:
    `director.py:215` (12000), `director.py:530` (16000), `command.py:1147` (14000),
    `mail.py:227` (12000); spec 30 "Context budget": "Never truncate hard policy/evidence
    constraints silently".
22. **Letters enter the system prompt without an inert boundary.** `compose_identity` places open
    letters (≤600 chars) and three thread turns in the system prompt as plain text
    (`identity.py:314-324`), while task payloads are wrapped in `<untrusted_source_evidence>`
    (spec 30 "Prompt injection boundary").
23. **The Owner's chat question is wrapped as untrusted source evidence**
    (`history.py:122`, tag `owner-question`).
24. **Memory write scope is not enforced.** Role contracts store `memory_scope.write`
    (`identity.py:115-116`, `config/role_contracts.json`), but `memory.remember` checks no role
    (`memory.py:42-98`); only the read scope is used (`memory.py:111-121`).
25. **Model-written text does become memory.** `director_review` stores the review's `summary`
    and `priorities` (`director.py:600-618`), `choose_topic` the choice's `reason`
    (`director.py:238-245`), and `command._assign` the Director's free-text `action` as a
    studio-wide STRATEGY record (`agent_id=None`, `command.py:1327-1337`) that every role whose
    scope reads STRATEGY is then told; `models.py:263-265` says records are "never from a
    model's free text" (the text is schema-validated, not checked for content).
26. **PROCEDURAL memory class is in the spec, not the code.**
    `30_PROMPT_CONTEXT_MEMORY_ARCHITECTURE.md` lists `PROCEDURAL`; `MEMORY_CLASSES`
    (`models.py:247-254`) does not.
27. **Recall is not task-aware.** `compose_identity` receives `task_type` but only records it in
    the manifest (`identity.py:278`, `:340`); `recall` filters by class, owner, expiry and
    recency only (`memory.py:124-143`). Spec 30 "Retrieval" asks for role-, task-, visibility-
    and freshness-aware retrieval.
28. **`ToolReceipt` is never written.** The table is defined (`models.py:228-244`) and no code in
    `backend/app` instantiates it (only `models.py` and `app/maintenance.py` mention it).
29. **`AgentRun.output` (JSON) is never set by the gateway** (always None, `services.py:842`,
    `:870`, `:912`).
30. **`cost_limit_per_task` and `max_concurrent_tasks` are written, never enforced.** Seeded as
    None/1 (`services.py:1270-1271`, `:1742-1743`); concurrency is enforced by `_has_live_run`
    regardless (one live run).
31. **Roles created by `seed_missing_workforce` get no REQUIRED capability**
    (`services.py:1219-1244`), unlike `_seed_initial_workforce`, which adds REQUIRED
    `text_generation` to each new role (`services.py:1709-1716`).
32. **`apply_llm_allocation` treats any `agent.model_assigned` as "configured"**, including events
    of origin SEED_ALLOCATION or DIRECTOR_REPAIR (`ensemble.py:851-861`), whereas
    `_owner_chose_models` distinguishes origins (`services.py:1497-1499`).
33. **The adapter-missing run row has no context manifest** (`services.py:861-880` omits
    `context_json`, unlike the kernel-block row at `:852`).
34. **`create_agents_router(registry)` ignores its argument**; its handlers read
    `request.app.state.registry` (`router.py:199`, `:248`, `:305`), while
    `create_providers_router` uses its parameter (`router.py:353`, `:369`).
35. **An empty chat question becomes HTTP 404.** `ChatCommand` allows whitespace-only text
    (`router.py:65-67`); `chat` raises `ValueError` (`history.py:120-121`), which the route maps
    to 404 (`router.py:250-251`).
36. **A second reply to the Owner can be folded into the first.** `answer_mail` posts the reply
    to the Owner with subject `Re: <subject>` and `to_owner=True` (`mail.py:549-562`); while an
    earlier Owner letter with that subject is OPEN, `post_message` returns it instead of writing
    a new one (`messages.py:55-74`).
37. **Recipient allowlists are not implemented.** Spec `04_AGENT_SYSTEM.md` §18 lists "recipient
    allowlist by role"; any active role may be the target of a Director investigation
    (`director.py:387-389`) and the Owner may forward to any agent id (`router.py:159-177`). Max
    hops/messages are implemented as thread length 8, the 15-minute interval and 3 reviews per
    hour (`mail.py:83-97`).
38. **The review reads the 12 newest open inbox letters** (`messages.py:225`, ordering
    `created_at desc`; `director.py:509-511`); older letters wait until newer ones are decided
    (the evening stage runs up to three passes, `stages.py:6264-6283`).
39. **A role's allowed task types and prohibitions are prompt text only.** `compose_identity`
    writes `Role.allowed_task_types` and `prohibited_actions` into the system prompt as «YOU MAY
    DO» / «YOU MUST NEVER» (`identity.py:296-297`); no code compares a run's `task_type` with
    them (the kernel, `services.py:608-679`, and `run_agent_task`, `:733-883`, never read them).
    The Director's own runs (`direct_company`, `choose_topic`, `director_review`) and every
    employee's `answer_mail` are outside their roles' lists, and `POST /agents/{id}/run` accepts
    any `task_type` (`schemas.py:84`). Spec `04_AGENT_SYSTEM.md` §2 "Role Contract" describes
    allowed task types as part of the contract.
40. **The Director's review never sees the letters' words.** The payload keeps only `id`,
    `intent`, `from_name`, `subject`, `body_json`, `created_at` of each inbox letter
    (`director.py:515-522`); `body_text` — an employee's whole reply (`mail.py:555`), the Owner's
    own words (`router.py:141`), a stage report's reason (`director.py:296`) — is left out, and the
    NULL-addressed inbox is not in her identity's open letters either (`identity.py:237-242`).
    She decides on subjects, `done`/`needs` flags and the `claim_check` label; `owners_matter`
    reads the text she was not shown (`director.py:121`).
41. **Open Owner letters can hide the Director's inbox.** Owner letters share the NULL addressee;
    `open_messages(inbox=True, limit=n)` reads the `2n` newest NULL-addressed OPEN rows and only
    then drops the Owner's (`messages.py:223-226`). With 24 or more open Owner letters newer than
    an inbox letter, the review (n = 12) does not see it; if all 24 newest are Owner letters the
    review returns "Inbox empty." (`director.py:509-513`) while letters wait.
42. **An unavailable critic leaves the Director's decision at full confidence.** `_review` gives
    REVIEW_INCOMPLETE for an unavailable secondary only when `require_review` is set
    (`ensemble.py:383-384`); `_choose` does not set it (`command.py:1156-1177`), so the outcome is
    PARTIAL, `review_incomplete` is False and the LOW-confidence rule (`command.py:1202-1207`)
    does not fire, contrary to the module rule "a decision nobody managed to challenge is not
    passed off as a challenged one" (`ensemble.py:24-26`). Only the note carries
    `[REVIEW: …; PARTIAL]`.
43. **The Owner-matter word test reads the model's own note, and `\btoken` matches «tokeni».**
    `owners_matter` searches `subject + body_text + decision.note` (`director.py:121-122`), so the
    escalation the model proposes is kept when its own note uses one of the words; the pattern's
    `\btoken` (`director.py:97`) also matches Romanian «tokeni» (token budgets), a money matter
    the rule says is never the Director's to escalate (`director.py:88-90`).
44. **`reviews_this_hour` counts runs, not reviews.** It counts `AgentRun` rows with
    `task_type == "director_review"` (`mail.py:588-597`); `structured_run` writes a second run
    with the same task type whenever the first answer had no valid object
    (`structured.py:121-135`), so the "3 reviews per hour" ration can stop after 2 reviews.
45. **The exceeded-budget exemption is a task-type string.** `may_run_agent` skips the USD check
    when `task_type in BUDGET_EXEMPT_TASKS` (`accountant.py:1037`, `:1125`); the Owner's
    `POST /agents/{id}/run` passes any `task_type` through (`router.py:307`), so a run named
    `reconcile_day` runs past an exceeded budget (the token ceiling still applies). Owner-only
    route; no automatic caller does this.
46. **A model call ends a WORKING state early.** `_assert_policy_allows_run` lets a run start
    beside WORKING (`services.py:651`); `run_agent_task` then writes THINKING and, after the call,
    IDLE (`services.py:888`, `:983`), and `mark_idle` later finds no WORKING to clear
    (`services.py:106-107`). An employee who thinks during a paid render shows IDLE for the rest
    of it — the situation `mark_working` was written to prevent (`services.py:60-66`).
47. **`vision_agent` ignores availability.** It joins on the declared `vision` capability only
    (`vision.py:125-132`); `seeing_model` then requires the borrowed model to be available
    (`vision.py:183-184`) and returns None when the one employee `vision_agent` named has an
    unavailable seeing model, even if another ACTIVE employee's seeing model is available.
    `picture_qc` and `preflight` use `vision_agent` directly (`picture_qc.py:1003`,
    `preflight.py:528`) and may name an employee whose seeing model cannot be called.
    Since 20abffd the Director's second look at a refused still or clip borrows through this
    lookup when her own model and slots do not see (`seeing_model(session, director_id, *LOOKERS)`,
    `backend/app/media/second_look.py:686`): a None there makes the look UNAVAILABLE
    (`:687-692`), so the QC refusal stands and the re-roll or retry is bought as before.
48. **Collaboration records can lose a run.** `_fallback` stores the secondary and the tertiary
    attempt under the same key `FALLBACK` (`ensemble.py:333-338`), so `roles_json` and
    `secondary_run_id` keep only the last; `_parallel` records the tertiary as `JUDGE` although it
    was asked as a peer (`ensemble.py:565-568`); `_judge_prompt` is always given an empty critique
    (`ensemble.py:522`).
49. **An investigation can go to an inactive employee or to the Director herself.** When
    `assign_to_role` names no ACTIVE holder, the target is the letter's sender with no lifecycle
    check (`director.py:387-389`); `answer_mail` then refuses a non-ACTIVE addressee
    (`mail.py:462-463`) and the letter backs off for ever; a sender who is the Director (her
    stage reports, her blocked-review ESCALATE) gets a letter to herself, which
    `_addressees_turn` never answers (`mail.py:707-710`).
