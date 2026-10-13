# 09 — Runbook services, preflight, weekly review, and the durable workflow engine

Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).

> Files (24, 9 738 lines):
> `backend/app/runbook/services.py` (2015), `backend/app/runbook/preflight.py` (1718),
> `backend/app/runbook/weekly.py` (479), `backend/app/runbook/router.py` (231),
> `backend/app/workflows/__init__.py` (0), `backend/app/workflows/models.py` (128),
> `backend/app/workflows/schemas.py` (111), `backend/app/workflows/services.py` (920),
> `backend/app/workflows/worker.py` (835), `backend/app/workflows/watchdog.py` (1007),
> `backend/app/workflows/publisher.py` (180), `backend/app/workflows/router.py` (259),
> `backend/app/workflows/passes/__init__.py` (186), `passes/character_references.py` (361),
> `passes/director_qc_review.py` (180), `passes/ladder_retry.py` (212),
> `passes/licence_release.py` (37), `passes/owner_choice_continuation.py` (183),
> `passes/replaced_boards.py` (23), `passes/restore_retired_takes.py` (118),
> `passes/resume_interrupted_day.py` (93), `passes/serial_unfilmed.py` (228),
> `passes/training_set.py` (209), `passes/vendor_plan_licence.py` (25).
> Mapped 2026-10-12 at HEAD 3d49e9a (no commit from b00083c to 20abffd touches these files, and the
> working tree was clean for them) (217 functions in the static inventory; nested handler
> closures of `build_task_handlers` and `execute_daily_run` are documented as well although
> the inventory does not list them). Verified against the code on 2026-10-12 by a second pass;
> corrections are folded in.

## In one paragraph

This group is the studio's engine room. `app.workflows` is a durable, SQLite-backed task
queue with leases, a wall-clock/interval scheduler, a single background worker that every 30 s
sweeps dead tasks, fires due jobs and runs up to three queued tasks through a fixed dispatch
table, a watchdog that every 10 min repairs what dead processes, vendors and the studio's own
bugs left behind (plus eleven self-registering "passes"), and a transactional outbox that
pushes every committed domain event to the Owner's page over an authenticated WebSocket.
`app.runbook` is the daily production day: a read-only preflight that answers READY /
DEGRADED / BLOCKED in Romanian with the place on the page where each fix lives, and
`execute_daily_run`, which walks the 13 stages of `39_DAILY_AUTONOMOUS_RUNBOOK.md`, records
each stage's real outcome, retries transient faults in place, blocks only the stages that
depend on a failure, opens safe mode only for a P0, writes deterministic letters from the
Director to the Owner, and resumes a day cut off by a restart without buying anything twice.
`app.runbook.weekly` is the one place in this group that asks a language model a question
directly: the Director's weekly performance review. Almost everything else here is
deterministic code: of 217 functions, one is an LLM call site; the LLM-heavy work (stage
runners, film continuations, the Director's loop, mail rounds) is reached only through the
dispatch table and runs in other modules.

## Why it exists

- **The studio had no engine.** "Until now the studio had a scheduler that could be ticked
  and a task queue that could be claimed, and nothing that did either on its own"
  (`backend/app/workflows/worker.py:3-5`; decision "The clock is the Owner's to start",
  `docs/project/16_DECISION_LOG.md:1827`). The worker closes that gap; the daily job is seeded
  dormant so a first start-up never begins a paid day on a decision nobody took
  (`backend/app/main.py:483-486`).
- **A run must not report more than it did.** "The risk is a run that *reports* more than it
  did" (`backend/app/runbook/services.py:6-14`; D-P10-001 at
  `docs/project/16_DECISION_LOG.md:1731`). Hence SKIPPED stages, status derived from stages
  (`services.py:773`), per-stage `produced` counts (`services.py:500`) and a headline that
  says "Ziua nu a produs nimic" when nothing was made (`services.py:517-560`).
- **An optimistic preflight is worse than none** (`backend/app/runbook/preflight.py:3-12`):
  every check reads the database only and never probes the network.
- **One "database is locked" stopped the studio for days.** Transient vs HARD fault classes,
  in-place retries and same-day re-attempts (`services.py:185-191`, `services.py:299-326`;
  decision "A transient fault is not a P0" at `16_DECISION_LOG.md:1840-1842`).
- **Safe mode was opened by any hard fault** (one expired read-only token would have halted
  the studio); since 2026-09-18 only a P0 (`SAFE_MODE_STAGES`, `services.py:150-160`;
  `16_DECISION_LOG.md:3404-3417`; spec `39_DAILY_AUTONOMOUS_RUNBOOK.md` "Abort behavior").
- **One failure lost the whole day** (a refused statistics token at performance intake left
  nothing filmed, rehearsal 2026-09-18) → the dependency table `STAGE_PREREQUISITES`
  (`services.py:96-135`).
- **A crash re-ran a whole day with its purchases** (REL-03, 2026-10-02): the day row is
  written RUNNING at the start (`services.py:931-969`), a lapsed lease with no attempts left
  is dead-lettered, not re-claimed (`backend/app/workflows/services.py:333-349`, `399-457`).
- **Restarts became routine** (the Owner, 2026-10-12 07:40: «să dai singur restart la proiect,
  nu mă aștepta pe mine!») → an INTERRUPTED day is resumed by the watchdog with completed
  stages replayed from the record (`passes/resume_interrupted_day.py:1-16`,
  `services.py:1079-1109`; `16_DECISION_LOG.md:55-57`).
- **Dead processes leave rows behind**: renders RENDERING since 2026-09-12, uploads in
  REMOTE_UNKNOWN, budget holds never released, vendor tasks never collected, days left RUNNING
  (`backend/app/workflows/watchdog.py:1-48`).
- **Films stood waiting with nothing left to ask the Owner** (babcf272, cyclotron 00000160,
  NASA 6fe6a577, serial 043317d3) → registered passes that re-queue the film's continuation
  (the passes' module docstrings, 2026-10-09..11). The Owner's rules quoted there: «studioul
  trebuie să rezolve singur, fără intervenții», «Nu trebuie să respingă un film, trebuie să îl
  refacă până trece QC», «Agenția trebuie să fie autonomă».
- **The Owner's standing order for a weekly review** of measured performance with written
  indications to the sound and video departments (`backend/app/runbook/weekly.py:1-21`).
- **Live register**: events used to reach the page only after a run ended; the outbox makes
  them live and commits before broadcasting (REL-12, `backend/app/workflows/publisher.py:63-75`).

## Who decides here

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| A manual day may be queued | OWNER (button «Pornește rularea de azi») then CODE_RULE | `runbook/services.py:1291-1342`, route `runbook/router.py:80-93` | refused (409) in safe mode, with `worker_enabled` false (CONFIG), with autonomy stopped, or when a DAILY_RUN is QUEUED/RETRYING/CLAIMED/RUNNING that is not a waiting retry; queued priority 10, `max_attempts=1`, key `manual-run-{command_id}` |
| The daily clock starts at all | OWNER | `workflows/services.py:748-788`, route `workflows/router.py:147-155` | `daily_main` is seeded `active=False` (`main.py:475-487`); activation is the event `workflow.job_activated`; waking never fires a past slot on the spot |
| The hour the day fires | CONFIG | `main.py:475-487`, `workflows/services.py:653-678` | `daily_run_hour_local` default 05:00 in `timezone`; DST-safe next occurrence |
| Anything scheduled fires | CODE_RULE gated by OWNER stop | `workflows/services.py:791-920` | no fire while `OwnerPolicy.autonomy_stopped`; one task per slot (key `scheduled:{job}:{due_at}`), `max_attempts=1`; missed slots fire once (`next_run_after`, `services.py:629-650`) |
| Any queued task is claimed | CODE_RULE gated by OWNER stop | `workflows/services.py:333-391` | nothing claimed while stopped or shutting down (`worker.py:620`); a lapsed lease is re-claimed only with attempts left |
| A clock-fired day runs or is skipped | CODE_RULE | `worker.py:171-268` | skip when the retry was for another date, when today has an INTERRUPTED/RUNNING run, a COMPLETED/PARTIAL run, or `attempt > daily_max_attempts` (3); a `manual` payload bypasses these |
| Preflight verdict | CODE_RULE | `preflight.py:1679-1681` | BLOCKED if any BLOCKING line failed; DEGRADED if any DEGRADING line failed; INFORMATIONAL lines never count |
| Preflight blocks the day for money | CODE_RULE on OWNER settings | `preflight.py:320-363` | BLOCKING `spending_budget.none_unasked` when environment PRODUCTION and the paid rule buys unasked (`buys_paid_media_unasked`) and no active DAILY budget (MONEY-06) |
| Preflight blocks for an upload token | EXTERNAL (Google's recorded answers) | `preflight.py:918-960` | BLOCKING when the upload scope is not granted or a token refusal stands unanswered by a later reconnect/verification |
| Preflight blocks for disk / vault / FFmpeg / model / stop | CODE_RULE + CONFIG | `preflight.py:1238-1320`, `1369-1471` | `disk_space` LOW vs the Owner's minimum (MIN_FREE_SETTING); `credential_vault` unreadable for a used connection; no FFmpeg; no available model; `autonomy_stopped` |
| Empty media defaults are filled before judging | CODE_RULE (over the recorded vendor catalogue) | `runbook/services.py:1345-1356`, called at `1405`; `integrations/autoconfig.py:131-240` | only when some media purpose is not READY: `auto_configure` selects a service only where exactly one verified connection can serve the purpose (several = left to the Owner), fills empty default model/voice by `rank_candidates` over stored `ProviderResource` rows, and also replaces a stored default the recorded catalogue says can no longer serve the purpose; local reads/writes, no network; any exception ignored |
| A stage runs, is SKIPPED or BLOCKED | CODE_RULE | `runbook/services.py:1467-1523` | order: shutdown → Owner stop → `STAGE_PREREQUISITES` (blocked only when every prerequisite failed/was blocked) → no runner = SKIPPED |
| A failed stage is retried in place | CODE_RULE + CONFIG | `runbook/services.py:586-635` | only TRANSIENT (`classify_fault`), `stage_retry_attempts`=3 retries, backoff 20·2^n s (20, 40, 80), stop read before each retry |
| A fault is TRANSIENT or HARD | CODE_RULE | `runbook/services.py:259-326` | TRANSIENT: `TransientStageError`, SQLAlchemy/sqlite `OperationalError`, `RemoteStateUnavailable`, HTTP 408/425/429/500/502/503/504, timeouts and network errors; HARD: everything else, any link with `fault_class == HARD` (e.g. a paid step that already paid), `MediaProviderNotConfigured` |
| The Owner's stop ends the day | OWNER | `runbook/services.py:1490-1496`, `1547-1565`, `1635-1640` | read before every stage and after a failure; remaining stages BLOCKED "Oprit de AUTONOMIE OPRITĂ.", status PARTIAL/BLOCKED, no safe mode, no letter |
| A shutdown ends the day INTERRUPTED | CODE_RULE (process signal) | `runbook/services.py:1472-1485`, `1529-1546`, `1601-1618` | `request_shutdown` (lifespan exit, `main.py:622`) → current stage INTERRUPTED, rest BLOCKED, log not closed |
| The run's status | CODE_RULE | `runbook/services.py:773-781`, `1728-1741` | FAILED > BLOCKED > PARTIAL (any SKIPPED) > COMPLETED; FAILED/BLOCKED becomes PARTIAL when no production stage was lost and `daily_log` did not break |
| The day is re-attempted the same day | CODE_RULE + CONFIG | `runbook/services.py:404-424`, `worker.py:290-323` | BLOCKED preflight, or FAILED + TRANSIENT + a production stage lost; not after a stop; new task after `daily_retry_seconds` (1800 s), priority 5, key `daily-retry-{date}-{n}`, up to `daily_max_attempts` (3) |
| Safe mode opens (sets the autonomy stop) | CODE_RULE | `runbook/services.py:1749-1758`, `1875-1881`, `657-689` | a HARD fault in `media`, `publish` or `daily_log`, or a non-Operational `DatabaseError`/`IntegrityError` in any stage; not when the Owner stopped or on shutdown |
| Safe mode is cleared | OWNER | `runbook/services.py:708-742`, route `runbook/router.py:223-229` | a written note is required; autonomy is NOT restarted |
| The Director's letter about a stopped day | CODE_RULE (deterministic text) | `runbook/services.py:1767-1810` | only after the day's last attempt, not after an Owner stop; two wordings (production lost vs not) |
| A RUNNING day nobody runs is closed | CODE_RULE | `runbook/services.py:1239-1278`, called by `watchdog.py:621-629` | its task's lease lapsed / task no longer leased, or (no task) no activity for longer than `TASK_LEASE_SECONDS` (3600 s) → INTERRUPTED + one letter |
| An interrupted day is resumed | CODE_RULE | `passes/resume_interrupted_day.py:29-93`, `worker.py:212-239`, `runbook/services.py:1079-1109` | today's newest run INTERRUPTED with nothing after; not while stopped, in safe mode, or a DAILY_RUN pending; completed stages replayed from the record, the rest run; within `daily_max_attempts` |
| A dead task is dead-lettered (not re-run) | CODE_RULE | `workflows/services.py:399-457`, `worker.py:669-688` | lapsed lease with `attempts >= max_attempts` → DEAD_LETTER "INTERRUPTED: …", letter for DAILY_RUN and FILM_CONTINUE |
| A failed task is retried by the queue | CODE_RULE | `workflows/services.py:502-531`, `worker.py:646-660` | `NonRetryable` → DEAD_LETTER; other exceptions → RETRYING with `backoff_seconds·2^(attempts-1)` while attempts remain |
| A dead-letter task is put back | OWNER | `workflows/services.py:534-553`, route `workflows/router.py:123-131` | attempts reset to 0 |
| A film continuation waits for another buyer | CODE_RULE | `worker.py:342-363` | refusal FILM_BUSY → re-queued after 600 s, at most 3 deferrals, not after a stop |
| Weekly review is skipped | CODE_RULE | `weekly.py:281-301` | nothing PUBLISHED with a remote id → STATUS note, no tokens; a SUCCEEDED/EMPTY_OUTPUT `WEEKLY_REVIEW` run since Monday 00:00 UTC → skipped |
| Weekly review content (verdict, department indications, topics) and which departments get instructions | LLM (schema-only validation) | `weekly.py:322-383`, `384-445` | schema `WeeklyReviewAnswer` (`parse_structured` with `fit_to_schema`, which cuts over-long strings instead of refusing them); a structured blocker is filed instead; schema failure → nothing distributed. No code checks the content: every non-blank `sound`/`video`/`topics` becomes a HANDOFF as written and `topics` becomes STRATEGY memory |
| A budget increase | LLM proposes (amount + justification), OWNER decides | `weekly.py:376-380`, `404-422`; consumer `economy/accountant.py:1281-1306`, `1337-1342` | a REQUEST_INFO to the Accountant (only when amount > 0 and a justification are both given and an Accountant exists). The Accountant's daily close lists it in an ESCALATE flagged `owner_attention`, posted with `to_agent_id=None` and **without** `to_owner` — so it lands in the Director's inbox, not among `letters_for_owner` (`agents/messages.py:208-211`, `232-240`) — and marks the request RESOLVED «transmisă Proprietarului». It becomes a letter to the Owner only if the Director's inbox review (LLM) chooses ESCALATE_TO_OWNER and the code check `owners_matter` agrees (`agents/director.py:114-122`, `370`, `420-430`), or the Owner reads the inbox. No budget is changed by code |
| The watchdog acts at all | OWNER stop | `watchdog.py:822-838`, `643-649`, `721` | autonomy stopped (or no policy row, or unreadable stop) → nothing changes; re-read before every registered pass |
| A render is declared stuck | CODE_RULE + CONFIG | `watchdog.py:161-216` | RENDERING with no `finished_at` older than `render_stuck_after_seconds` (10 800 s) → FAILED + `media.render_failed` |
| An uncertain publication is reconciled / handed over | CODE_RULE + EXTERNAL | `watchdog.py:301-436` | STARTED older than `publish_stuck_after_seconds` (3600 s) → REMOTE_UNKNOWN; by-title lookup only after 15 min; after `reconcile_max_attempts` (3) attempts since the Owner's last resolution → handed to the Owner |
| A FAILED_RETRYABLE publication is uploaded again | CODE_RULE + EXTERNAL | `watchdog.py:391-394`; gate in `publishing/services.py:2092-2128` | `execute_publication` re-runs the publishing gate (stop, QC, policy version, file) and asks the platform by idempotency key first |
| A published video is FAILED_FINAL | EXTERNAL | `watchdog.py:439-490` | YouTube processing status rejected/failed/deleted within 6 h of publishing, ≤20 per pass |
| Budget holds are released | CODE_RULE + CONFIG | `watchdog.py:864-875` | `release_stale_reservations` with `reservation_ttl_seconds` (21 600 s) |
| A paid vendor task becomes PAID / REFUSED / LOST | EXTERNAL | `watchdog.py:568-596` | asked by task id (GET, buys nothing), films whose purchase lease is held are excluded |
| Failed-render intermediates are deleted | CONFIG (Owner setting) | `watchdog.py:602-615` | only when `sweep_failed_intermediates` is true (default false), older than `failed_intermediates_days` (7) |
| A failed film is put before the Director again | CODE_RULE | `passes/director_qc_review.py:75-180` | PRODUCTION only; newest QC report FAILED within 7 days, no final decision, no open redo-cap card; retry 60 min, doubling for walks that never reached her up to 1440 min; ≤24 rounds |
| A film stopped on the Director's ladder is walked again | CODE_RULE | `passes/ladder_retry.py:67-212` | PRODUCTION only; newest walk WAITING with NEEDS_OWNER/TAKES_NOT_ACCEPTED, QC-refused scenes, last brief attempt not rewritten and older than 20 min, ≤6 per film per UTC day |
| A film the studio left standing is walked once after a start | CODE_RULE (and OWNER's earlier scene-model choice) | `passes/owner_choice_continuation.py:57-183` | missed Owner scene-model choice; render failed before the start; WAITING/HELD for a non-Owner cause |
| An approved serial episode gets a storyboard and a walk | CODE_RULE | `passes/serial_unfilmed.py:65-228` | APPROVED episode with no storyboard for > 15 min; APPROVED serial storyboard with no render and no walk since the start |
| A character portrait fills an empty bible slot | CONFIG (verified file + SHA-256) | `passes/character_references.py:171-361` | slot `portrait` empty, character not visually locked by the Owner, file hash equals `config/character_references.json` |
| A licence-held private upload becomes public | EXTERNAL + CODE_RULE | `passes/licence_release.py:19-37` | the vendor plan licence recorded (`vendor_plan_licence`, order 120) then `release_licence_held_uploads` under the channel policy |
| The LoRA training milestone is announced | CODE_RULE | `passes/training_set.py:174-208` | ≥100 approved serial clips in the manifest → one event + one STATUS letter; the training itself is the Owner's card |
| Only one worker per database | CODE_RULE | `worker.py:767-835`, `main.py:397-413` | OS byte lock on the database path with its suffix replaced by `.lock` (`data/studio.lock` for `data/studio.db`, `worker.py:828-835`); a second process serves the page and runs no worker; no lock (and no exclusion) for an in-memory or server database |
| A socket hears events | CONFIG (`owner_token`) | `workflows/router.py:165-234` | first message must carry the Owner token within `SOCKET_AUTH_TIMEOUT_S` (5 s); key in URL refused |
| A Director decision is closed with its outcome | OWNER | `runbook/router.py:207-217` | «The Owner's word is final here» |

## LLM involvement

### Direct call site: `app.runbook.weekly.execute_weekly_review` (`backend/app/runbook/weekly.py:271-464`)

| Aspect | Fact |
|---|---|
| Speaker | the agent holding role `Director` (`_agent_for_role`, `weekly.py:248-254`; lifecycle ACTIVE, HIRED or CANDIDATE; first row found, no ORDER BY); pronouns in code: she/her |
| Gateway | `app.agents.services.run_agent_task` directly (`weekly.py:322-334`): identity as system prompt, policy kernel, daily token ceiling and USD budget (`agents/services.py:768-781`) |
| Task type / template | `WEEKLY_REVIEW` (`weekly.py:42`), prompt template version `weekly-review-v2` (`weekly.py:245`), `max_tokens=4800` (multiplied for the Director by `director_token_multiplier`, default 2 → 9600, `config.py:11`, `config.py:425`, `agents/services.py:789-795`), `temperature=0.3`, `emit_message=False`, on the Director's own assigned model (no `model_id` slot passed) |
| What it asks | `_REVIEW_INSTRUCTIONS` (`weekly.py:219-243`): judge views and retention from measured numbers only, return ONLY a JSON object in Romanian, leave a section empty rather than invent work, say when data is too thin (fewer than three videos of a kind). The data is `_digest_as_text(weekly_digest(...))` (`weekly.py:82-196`): latest 50 PUBLISHED publications with their latest analytics snapshot, per-channel totals, up to 10 PROPOSED `DirectorRecommendation`s, the editorial-accuracy comparison (`story_performance`) and, when `trends_enabled`, search trends for `trends_geo` |
| Answer shape | pydantic `WeeklyReviewAnswer` (`weekly.py:199-216`, `extra="ignore"`): `verdict` (1-4000 chars, required), `sound`, `video`, `topics` (≤2000 each), `budget_request_amount_usd` (float > 0 or null), `budget_request_justification` (≤2000), `escalate_to_owner` (≤2000). Alternatively a structured blocker `{"blocker": {"reason", "needs"}}` (`agents/identity.py:648-662`) |
| What code does with it | (1) blocker → filed as the STATUS report's reason, nothing routed (`weekly.py:355-359`). (2) Valid answer → HANDOFF messages from the Director: `sound` to VoiceArtist, `video` to VideoEditor, `topics` to LeadResearcher **and** ScriptWriter (`weekly.py:370-375`, `387-402`), each only when the department exists and the text is non-blank; these messages enter each employee's runs until resolved (module docstring `weekly.py:12-16`). (3) Budget request → REQUEST_INFO to the Accountant only when both amount and justification are present (`weekly.py:376-380`, `404-422`). (4) A STATUS report with the whole review to the Director's inbox (`weekly.py:426-434`). (5) `topics` stored as the Director's `STRATEGY` memory, first 400 chars (`weekly.py:437-445`), which `compose_identity` puts into her later system prompts (her role's memory scope reads STRATEGY, `config/role_contracts.json`; `agents/memory.py:111-121`, `agents/identity.py:305-311`). (6) A speech-bubble event `agent.message_sent` (`weekly.py:446-456`, `467-479`) |
| Trust | ADVISORY. Note the distinction: the *routing* is acted on as is after schema validation (the decision label is LLM, not LLM_CHECKED_BY_CODE): which departments receive instructions, their wording and the STRATEGY memory are exactly what the model wrote. But no code acts on that content; it is input that other LLM employees weigh in their own runs, and the Owner keeps every budget. The budget request is ADVISORY — it goes to the Accountant, whose daily close carries it into the **Director's inbox** as an ESCALATE flagged `owner_attention` (not addressed `to_owner`, `economy/accountant.py:1281-1306`); only the Owner sets budgets. `escalate_to_owner` is only kept inside the STATUS body (`weekly.py:425`); no code routes it to the Owner separately. The STATUS report (Director's inbox, `to_agent_id=None`, not `to_owner`) is INFORMATIONAL |
| Checks | only schema validation (`parse_structured` → `read_structured` with `fit_to_schema` truncation, `agents/identity.py:568-645`; a blocker is tried first, `blocker_of`, `agents/identity.py:648-662`); `budget_request_amount_usd` must be > 0; no content verification of the numbers the review cites |
| If the model fails | run status ≠ SUCCEEDED or empty text → returns that status and reason, nothing filed (`weekly.py:335-344`); invalid JSON/schema → `status: FAILED`, "nimic nu a fost distribuit" (`weekly.py:361-368`). The worker records the handler's dict as a COMPLETED task (no exception). A run with status SUCCEEDED or EMPTY_OUTPUT still counts as this week's review (`weekly.py:257-268`), so a schema failure (or an EMPTY_OUTPUT run) is not retried until next week (see Oddities). No Director → `WeeklyReviewError` → `NonRetryable` → DEAD_LETTER (`weekly.py:305-306`, `worker.py:376-377`); an exception raised out of `run_agent_task` (agent or model row missing, `agents/services.py:787-818`) → `fail_task` with `max_attempts=1` → DEAD_LETTER (`worker.py:653-660`, `workflows/services.py:523-528`) |
| Can it lead to spending? | Tokens only (paid models are priced by the economy; gated by `may_run_agent`). It cannot buy media and cannot change a budget: a budget request goes to the Accountant and from the Accountant's close into the Director's inbox; it reaches the Owner as a letter only through the Director's ESCALATE_TO_OWNER (see the decision table and Oddity 24). Indirectly its HANDOFFs and STRATEGY memory steer later LLM work (research, scripts, video and voice choices) that may lead to purchases under the Owner's paid-step rule |
| Triggers | the `weekly_review` scheduled job (7 days, active from birth, first fire 1 h after first start-up, `main.py:504-512`) and `POST /runbook/weekly-review` (`runbook/router.py:95-145`), both through the `WEEKLY_REVIEW` worker handler (`worker.py:366-378`); refused when `registry` is None (`NonRetryable`) |

### Functions here that reach the LLM only through other modules

| Function | Path to the model | What runs | Notes |
|---|---|---|---|
| `create_runbook_router.post_direct` (`runbook/router.py:156-175`) | `app.agents.command.direct_company` → `_choose` → `app.agents.ensemble.run_with_strategy` → `run_agent_task` | the Director's management pass (DIRECTOR_LOOP) | runs synchronously inside the HTTP request; `direct_company` returns SKIPPED when autonomy is stopped (`agents/command.py:881`) |
| `worker_pass` (`workflows/worker.py:721-761`) | `app.agents.mail.correspondence_round` → `app.agents.director.director_review` → `app.agents.structured.structured_run` → `run_agent_task` (and `answer_mail` per letter) | the mail round: employees answer letters within the pass | only with a registry and not during shutdown; `correspondence_round` refuses when stopped (`agents/mail.py:882-883`) |
| `build_task_handlers.director_repair` (`workflows/worker.py:400-405`) | **missed by static analysis**: `app.agents.repairs.desk.execute_repair` calls the registered repair through `repair.function(context, params)` (`agents/repairs/desk.py:570-581`); the repair `switch_model` runs `_probe`, a `run_agent_task` call (task `TEST_CONNECTIVITY`, `max_tokens=64`, on a named model slot) whose `answered` (SUCCEEDED and non-blank) code then uses to pick the model (`agents/repairs/agent_health.py:568-597`, `601-668`) | the Director's chosen repair, applied under the Policy Kernel (asked again at run time) | the inventory reports `execute_repair` with `llm_distance` None |
| `build_task_handlers` (`workflows/worker.py:162-510`) | `weekly_review` → `execute_weekly_review` (call site above); `director_loop` → `direct_company`; `film_continue` → `app.runbook.stages.continue_film` (static distance 4); `model_research` → `app.media.model_research.research_all` (distance 2); `sheet_repair` → `app.media.blocker_repair.process_sheet_repair` (distance 3); `daily_run` → `execute_daily_run` → the stage runners of `app.runbook.stages.build_stage_runners` (passed as callables, so static analysis finds no path; at runtime they run research, writing, Director review, shot prompts, QC and, since 20abffd, the Director's second look at a still or clip QC refused, asked before a re-roll or retry is bought: `app.media.second_look._look`, the 38th call site, through `fix_check.director_second_look`, `backend/app/media/fix_check.py:642`) | every LLM-heavy job of the studio | the dispatch table is the only door from the scheduler/queue to those agents |
| `finish_approved_episodes` (`passes/serial_unfilmed.py:65-228`) | static: `ready_for_filming` → `describe_serial_shots` → `write_shot_prompts` → `prompt_agent._run` → `run_agent_task` (6 hops) | **not taken at runtime**: the pass calls `ready_for_filming(engine, episode_id, correlation)` without a registry (`serial_unfilmed.py:127-129`), and `describe_serial_shots`/`write_shot_prompts` skip the model when the registry is None (`media/serial_storyboard.py:368-372`, `media/prompt_agent.py:1178`) | the FILM_CONTINUE it queues does reach models later, in the worker |

### Deterministic writing that looks like an agent's

These produce letters "from the Director" with no model involved (INFORMATIONAL, written even
when no model answers): `tell_day_interrupted` (`runbook/services.py:1007-1054`),
`letter_to_owner` used for a stopped day (`runbook/services.py:1767-1810`,
`agents/director.py:469-489`), `_tell_continue_interrupted` (`worker.py:691-718`), the
training-set milestone letter (`passes/training_set.py:191-208`), the weekly "nothing
published" STATUS note (`weekly.py:281-294`).

### How much of this group is LLM

One LLM call site out of 217 functions. The preflight, the day's state machine, fault
classification, retries, safe mode, the queue, scheduler, leases, watchdog repairs, the
eleven passes, the outbox and the routers are all CODE_RULE / CONFIG / OWNER / EXTERNAL.
What the model decides in this group is advisory text (the weekly review): its routing is
acted on with schema validation only (label LLM), but what it routes is instructions and a
memory for other LLM employees, never a code path, a purchase or a budget. This group
nonetheless *dispatches* nearly all LLM work in the studio, through the worker's handlers,
including one path static analysis misses (DIRECTOR_REPAIR's registered repairs, above).

## Hard rules and limits

| Constant / setting | Value | Where | Meaning |
|---|---|---|---|
| `STAGES` | 13 stages, preflight … daily_log, serial_next | `runbook/services.py:76-90` | the day's order (spec `39_DAILY_AUTONOMOUS_RUNBOOK.md` §1-§12) |
| `STAGE_PREREQUISITES` | selection←research; script←selection; media←script **or** serial_queue; edit_and_qc←media; publish←edit_and_qc; serial_next←daily_log; others none | `runbook/services.py:122-135` | failure travels only along these edges |
| `PRODUCTION_STAGES` | selection, script_and_storyboard, serial_queue, media, edit_and_qc, publish | `runbook/services.py:141-148` | a loss here makes the day re-attemptable (if transient) |
| `SAFE_MODE_STAGES` | media, publish, daily_log | `runbook/services.py:160` | HARD fault here = P0 |
| `PRODUCED_FROM` | artefact keys per stage | `runbook/services.py:166-178` | what counts as "produced" |
| `_TRANSIENT_HTTP` | 408, 425, 429, 500, 502, 503, 504 | `runbook/services.py:227` | transient HTTP statuses |
| `stage_retry_attempts` / `stage_retry_backoff_seconds` | 3 / 20 s (20, 40, 80) | `config.py:477-478` | in-place stage retries |
| `daily_max_attempts` / `daily_retry_seconds` | 3 / 1800 s | `config.py:470-471` | same-day re-attempts |
| `DAY_DONE_STATES` | COMPLETED, PARTIAL | `worker.py:137` | a day that "ran" for the clock |
| `PENDING_STATES` | QUEUED, RETRYING, CLAIMED, RUNNING | `runbook/services.py:66` | "a run is on its way" |
| `LEGACY_PUBLISHED_STATES` / `NESTED_PUBLISHED_STATES` | PUBLISHED, REMOTE_CONFIRMED, SCHEDULED (+ PUBLISHED_SIMULATED) | `runbook/services.py:463-469` | what counts as a film published |
| Preflight severities | BLOCKING, DEGRADING, INFORMATIONAL | `preflight.py:73-80` | INFORMATIONAL never changes the verdict |
| `EMPTIES_THE_DAY` | `daily_budget_films` | `preflight.py:721` | named first in the summary |
| `TESTING_REFRESH_TOKEN_DAYS` | 7 | `preflight.py:698` | Google Testing-mode token life caveat |
| `AUTH_REFUSAL_STATUSES` / `_ERRORS` | 400, 401, 403 / invalid_grant, invalid_client, unauthorized_client, access_denied, insufficient_scope | `preflight.py:703-712` | a refusal vs not reached |
| `REFRESH_FAILURES_READ` | 500 events | `preflight.py:716` | read cap |
| `PAID_LLM_KINDS` | openai, anthropic | `preflight.py:460` | billed per token whatever is recorded |
| `agents` check | ≥ 2 runnable agents | `preflight.py:1432-1446` | claim extraction and verification by different employees |
| `TASK_LEASE_SECONDS` | 3600 s, renewed every 1800 s by `LeaseKeeper` | `worker.py:144`, `worker.py:535` | a running handler's lease |
| `TASKS_PER_PASS` | 3 | `worker.py:153` | tasks per worker pass |
| `worker_interval_seconds` | 30 s | `config.py:457` | worker loop period (`main.py:607-608`) |
| `FILM_CONTINUE_DEFER_SECONDS` / `FILM_CONTINUE_DEFERRALS` | 600 s / 3 | `worker.py:133-134` | FILM_BUSY deferrals |
| Queue priorities | manual day 10, resume 8, manual weekly 8, sheet repair 6, day retry 5, FILM_CONTINUE 4 (and its FILM_BUSY deferrals), scheduled 0 | `runbook/services.py:1330`, `passes/resume_interrupted_day.py:74`, `runbook/router.py:133`, `media/blocker_repair.py:544`, `worker.py:313`, `services.py:673` (app.services), `worker.py:356`, `workflows/services.py:874` | claim order (priority desc, then `next_attempt_at`) |
| `claim_task` default lease | 30 s | `workflows/services.py:336` | overridden to 3600 s by `work_once` |
| `fail_task` backoff | `backoff_seconds · 2^(attempts-1)` | `workflows/services.py:525` | queue-level retry |
| Scheduler leader lease | 15 s | `workflows/services.py:794` | (released inside the same transaction; see Oddities) |
| `CreateScheduledJobCommand.interval_seconds` | 5 s … 30 days | `workflows/schemas.py:79` | API-created jobs |
| `VALID_WORKFLOW_TRANSITIONS` | 11-state machine | `workflows/services.py:55-67` | Workflow rows (inert) |
| Watchdog interval | 600 s | `config.py:493`, `main.py:491-499` | job `watchdog`, SKIP policy |
| `render_stuck_after_seconds` | 10 800 s | `config.py:502`, `watchdog.py:93` | stuck render |
| `reconcile_max_attempts` | 3 | `config.py:503`, `watchdog.py:97` | publication reconcile bound |
| `publish_stuck_after_seconds` | 3600 s | `config.py:183`, `watchdog.py:114` | STARTED upload → REMOTE_UNKNOWN |
| `PUBLICATIONS_PER_PASS` | 20 | `watchdog.py:101` | reconcile batch |
| `RECONCILE_BY_TITLE_AFTER_SECONDS` | 900 s | `watchdog.py:119` | wait before title lookup |
| `PROCESSING_WINDOW_SECONDS` / `PROCESSING_PER_PASS` | 6 h / 20 | `watchdog.py:123-124` | YouTube processing follow-up |
| `reservation_ttl_seconds` | 21 600 s | `config.py:380`, `economy/budget.py:54` | stale budget holds |
| `sweep_failed_intermediates` / `failed_intermediates_days` | false / 7 | `config.py:113-114` | intermediate deletion |
| `sheet_blocker_scan_seconds` | 300 s | `config.py:56`, `worker.py:461-475` | sheet scan throttle |
| Pass orders | resume_interrupted_day 20, vendor_plan_licence 120, licence_release 130, character_references 140, restore_retired_takes 140, replaced_boards 145, owner_choice_continuation 150, ladder_retry 155, director_qc_review 160, serial_unfilmed 160, training_set 170 | the decorators in `passes/*.py` | run order (then by name) |
| director_qc_review | RETRY 60 min, MAX_WAIT 1440 min, LOOKBACK 7 d, MAX_TRIES 24 | `passes/director_qc_review.py:42-49` | |
| ladder_retry | RETRY 20 min, MAX_PER_DAY 6, LOOKBACK 7 d | `passes/ladder_retry.py:38-42` | |
| owner_choice_continuation / serial_unfilmed | LOOKBACK 7 d; serial GRACE 15 min | `owner_choice_continuation.py:41`, `serial_unfilmed.py:48-50` | |
| training_set | MILESTONE_CLIPS 100 | `passes/training_set.py:32` | |
| `REPLAY_LIMIT_MAX` | 500 events | `workflows/router.py:238` | WebSocket replay cap |
| Outbox claim batch | 100 rows per second | `publisher.py:63`, `main.py:337-352` | |
| Weekly | `max_tokens` 4800, `temperature` 0.3, 7-day job | `weekly.py:330-331`, `main.py:504-512` | |

**State machines.** DailyRun: RUNNING → COMPLETED | PARTIAL | BLOCKED | FAILED | INTERRUPTED
(`runbook/services.py:196-207`, `1728-1741`; spec `47_STATE_MACHINE_SPECIFICATIONS.md`, hash
note at `16_DECISION_LOG.md:4127`). Stage: COMPLETED | SKIPPED | BLOCKED | FAILED |
INTERRUPTED (+ RUNNING marker while in progress, `services.py:919-928`). TaskQueueItem:
QUEUED → CLAIMED → COMPLETED | RETRYING → … | DEAD_LETTER (`workflows/services.py`). Workflow:
`VALID_WORKFLOW_TRANSITIONS` (`workflows/services.py:55-67`). Outbox: PENDING → PUBLISHED.

## Modules

### `app.runbook.services` — `backend/app/runbook/services.py` (2015 lines)

Runs the day and records the truth about it; owns safe mode, the shutdown signal, the
interrupted-day machinery and the run history. Implements `39_DAILY_AUTONOMOUS_RUNBOOK.md`
(stages, dependency table, abort behaviour) and the P0 rule of `21_FAILURE_RECOVERY_PLAYBOOK`
/ `36_RELIABILITY_SLO_RUNBOOK`.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `classify_fault` | 299 | walks the exception chain (cause, then context) and returns TRANSIENT at the first transient link, HARD at a link whose class declares `fault_class = HARD`, else HARD | a retried unknown fault "is how a studio spends a night repeating a bug"; a paid step that failed after paying must not be retried (`SpentStageError`) | CODE_RULE |
| `_is_transient` | 259 | the transient shapes (see table above); `MediaProviderNotConfigured` is not transient | waiting will not produce a missing key | CODE_RULE |
| `_declares_hard`, `_http_status` | 291, 249 | read `fault_class` from the class; HTTP status from attributes or "HTTP nnn" in the text | helpers of the classifier | CODE_RULE |
| `request_shutdown` | 342 | adds the engine (or all studios) to the shutdown set and sets the wake event | REL-10: a stopped process ends the day at a boundary instead of mid-purchase | CODE_RULE |
| `clear_shutdown` | 352 | clears one or all shutdown requests | a studio restarted in-process must not be born stopped (`main.py:329`, `666`) | CODE_RULE |
| `shutdown_requested` | 364 | is this studio (or the whole process) shutting down | read by the worker, stages, passes | CODE_RULE |
| `stop_requested` | 377 | shutdown requested **or** `OwnerPolicy.autonomy_stopped` | polled between units of work by every long loop (media, render, publish) | OWNER / CODE_RULE |
| `stop_reason_words` | 396 | the shutdown sentence if shutting down, else the Owner-stop sentence | 2026-10-12 00:03: a restart was misnamed «Oprit de AUTONOMIE OPRITĂ» | CODE_RULE |
| `retryable_outcome` | 404 | True for BLOCKED+BLOCKED-preflight, or FAILED+TRANSIENT+production lost | a re-attempt reruns the whole day and could buy a second film to recover a report | CODE_RULE |
| `_doubts_the_record` | 427 | any non-Operational `DatabaseError` in the chain | `21`'s "corrupted audit state" P0 | CODE_RULE |
| `produced_by` | 500 | counts a stage's artefacts by `PRODUCED_FROM`; publish counts films in published states; legacy flat publication read by its keys | "COMPLETED 12/12" headed a day that made nothing | CODE_RULE |
| `run_summary` | 517 | the Romanian headline: stages run to their end, how many produced, idle/interrupted/failed/blocked lists, films published | same | CODE_RULE |
| `_blocked_by` | 563 | reason a stage cannot run when every prerequisite is lost, naming root causes | dependency table | CODE_RULE |
| `_run_with_retries` | 586 | run a stage; on TRANSIENT, wait `backoff·2^n` and retry up to `stage_retry_attempts`; announces `runbook.stage_retrying`; stops retrying on a stop | the ledger shows "waiting", not "hanging" | CODE_RULE + CONFIG |
| `_announce`, `_finished` | 638, 882 | write `runbook.*` events with outbox (live on the page) | a run used to be silent until it was over | CODE_RULE |
| `_open_safe_mode` | 657 | one open `SafeModeRecord`, event `runbook.safe_mode_entered`, sets `autonomy_stopped` and bumps the policy version | P0 response | CODE_RULE |
| `safe_mode_state` | 692 | the open safe-mode record, if any | read by start, the day, passes, route | — |
| `clear_safe_mode` | 708 | requires a note, closes the record, event `runbook.safe_mode_cleared`; does not restart autonomy | "a P0 is cleared by a person who looked at it"; leaving safe mode and restarting autonomy are two decisions | OWNER |
| `_stage` | 745 | one stage record (status, Romanian reason, artefacts, fault class, attempts, error class/detail) | the Owner reads words, never library text | — |
| `_derive_status` | 773 | FAILED > BLOCKED > PARTIAL > COMPLETED | "what its stages add up to, not what the caller hoped for" | CODE_RULE |
| `_close_the_day` | 784 | closes today's log (`close_daily_log`) as a retried stage and replaces the `daily_log` record | a failed close used to carry no class, invisible to safe mode and the clock | CODE_RULE |
| `_close_previous_day` | 830 | closes missing past days (a week back) and yesterday in full, retried; recorded on the preflight line, never ends the day | 2026-09-13..22 were never closed; the serial reads yesterday's log (`16_DECISION_LOG.md:1924`) | CODE_RULE |
| `pending_daily_run` | 894 | the DAILY_RUN task still on its way (ignores a claim whose lease lapsed with no attempts left) | a dead claim must not refuse the Owner's start | CODE_RULE |
| `_running_marker`, `_begin_run`, `_progress` | 919, 931, 972 | write the DailyRun row RUNNING at the start (with `runbook.daily_run_started`, correlation = task id) and keep its stages current (best effort) | REL-03 2026-10-02: a crash left no trace and the clock reran the day | CODE_RULE |
| `tell_day_interrupted` | 1007 | ESCALATE letter from the Director to the Owner about an interrupted day (`kind` `day_interrupted`); says the day resumes by itself | deterministic so it arrives when no model answers | CODE_RULE |
| `resumable_run` | 1064 | today's newest run if it is INTERRUPTED | what a start resumes | CODE_RULE |
| `resume_runners` | 1079 | replaces the runner of every stage the interrupted run COMPLETED with a replay of its record (status, reason + note, artefacts); preflight never replayed | "a film is never bought or a subject chosen twice" | CODE_RULE |
| `interrupt_run` | 1112 | RUNNING → INTERRUPTED at the stage it was in, missing stages BLOCKED, event `runbook.daily_run_interrupted`, letter; no-op if not RUNNING | the one move out of RUNNING writes the letter once | CODE_RULE |
| `run_of_task` | 1185 | the run whose start event's correlation is the task id | link queue ↔ day | — |
| `interrupt_task_day` | 1198 | for a dead DAILY_RUN task: interrupt its run, or write the letter for a day that never began | called by `announce_interrupted` | CODE_RULE |
| `interrupt_stale_runs` | 1239 | closes every RUNNING day whose task no longer holds a live lease (or, without a task, idle > lease) | the watchdog's sixth job | CODE_RULE |
| `_last_activity` | 1225 | newest of start/stage timestamps | idle measure | — |
| `_is_waiting_retry` | 1281 | QUEUED with `retry_of` | a waiting retry must not refuse the Owner's button | CODE_RULE |
| `start_daily_run` | 1291 | gate and queue a manual day (see decision table) | the run takes minutes; a request that ran it timed out in the browser | OWNER + CODE_RULE |
| `finish_media_setup` | 1345 | when a media purpose is not READY, `auto_configure` (selects the one verified connection for a purpose, fills empty defaults and replaces a stored default the recorded catalogue no longer supports; local rows only, `integrations/autoconfig.py:131-240`); errors swallowed | an unfinished form must not DEGRADE the day | CODE_RULE (over the recorded catalogue) |
| `execute_daily_run` | 1359 | the day (547 lines): safe-mode refusal; media setup; preflight; RUNNING row; yesterday's close; stages up to `daily_log` via `run_stage`; today's close unless the preflight was BLOCKED, the day was interrupted, or the Owner stopped it before any stage completed (`services.py:1684-1697`); `serial_next`; counts and headline; production-loss roots; status; re-attempt flag; P0; letters; final event `runbook.daily_run_finished` (+ `runbook.daily_run_interrupted` on shutdown); row rewritten; safe mode opened for a P0 | spec 39; every rule above | CODE_RULE |
| ↳ `run_stage` (nested) | 1467 | one stage: shutdown → stop → prerequisites → runner with retries → outcome handling (runner may return its own BLOCKED/FAILED with `fault_class`) | | CODE_RULE |
| ↳ `breaks` (nested) | 1443 | records a stage that broke by itself (root of its own loss) | | — |
| `stored_summary`, `_before_counts_summary` | 1946, 1914 | headline of a stored run: recount if every stage has `produced`, else an explicit "before counting" headline with `stages_productive` None | 18 runs of 12.09 stored no counts (measured 2026-09-25) | CODE_RULE |
| `list_runs` | 1970 | finished runs (not RUNNING), newest first, with headline and `films_now` (the films' current state) | a film finished after its run is said so (NASA 2026-10-11) | — |

Helpers: `_studio_key` (shutdown set key), `_interruptible_wait` (backoff that a shutdown
cuts short), `_count`, `_films_published`, `_legacy_publications` (counting helpers),
`_interruption_words` (letter wording).

Data: reads/writes `daily_run`, `safe_mode_record`, `owner_policy` (stop flag), `task_queue`
(read), `domain_event`/`outbox_record`; posts `agent_message` rows (letters). Events:
`runbook.daily_run_started`, `runbook.stage_started`, `runbook.stage_retrying`,
`runbook.stage_finished`, `runbook.daily_run_finished`, `runbook.daily_run_interrupted`,
`runbook.safe_mode_entered`, `runbook.safe_mode_cleared`; constant
`runbook.daily_run_resume_queued` (written by the resume pass). External calls: none
directly; money and publishing happen inside the stage runners passed in
(`app.runbook.stages`), and `auto_configure` reads the provider's catalogue.

### `app.runbook.preflight` — `backend/app/runbook/preflight.py` (1718 lines)

What the studio can do right now, without changing or calling anything. Each line is
`_check(...)`: Romanian `message`/`detail`, stable `code` (`<name>.<condition>`), `impact`,
`place`/`place_label`/`place_section` (where on the page the Owner fixes it, W31/W34
2026-09-25), and `technical` (routes, settings, scopes, fields, answers, paths) for a tooltip.
Spec: `39_DAILY_AUTONOMOUS_RUNBOOK.md` §1; decisions ADR-019 (`16_DECISION_LOG.md:791`),
ADR-PREFLIGHT-003 (`:2922`), "third severity is structural" (`:2574`), "summary names the
first line" (`:3619`).

The lines, in order (`run_preflight`, `preflight.py:1356-1718`):

| # | Check (`name`) | Severity | Fails when | Line |
|---|---|---|---|---|
| 1 | `stop_autonomy` | BLOCKING | `autonomy_stopped` | 1369-1382 |
| 2 | `credential_vault` | BLOCKING if `vault_health` says blocking, else DEGRADING | a used connection's keys unreadable / key file broken | 1238-1278 |
| 3 | `autonomy_mode` | INFORMATIONAL | never (says what MANUAL / SUPERVISED / AUTONOMOUS_CEO mean, `MODE_MEANS` 84-100) | 1390-1403 |
| 4 | `paid_media_rule` | INFORMATIONAL | never (`paid_rule_means`, PAGE-04) | 1323-1353 |
| 5 | `llm_provider` | BLOCKING | no `ModelRecord.is_available` | 1406-1421 |
| 6 | `agents` | DEGRADING | fewer than 2 ACTIVE agents with provider and model | 1423-1446 |
| 7 | `render_engine` | BLOCKING | no FFmpeg (`ffmpeg_path` or PATH) | 1457-1471 |
| 8 | `media_inspection` | DEGRADING | no FFprobe | 1472-1487 |
| 9 | `disk_space` | BLOCKING (DEGRADING when unreadable) | free space LOW vs the configured minimum | 1281-1320 |
| 10 | `youtube_channel_binding` | DEGRADING | no slot bound to a CONNECTED account | 1490-1520 |
| 11 | `research_sources` | DEGRADING | `research_health` not OK (no hosts, none passed, no way to find pages, fewer than `MIN_CLAIMS_AVAILABLE` claims) | 1522-1579 |
| 12 | `image_provider` | DEGRADING | no image adapter (`describe_media`) | 1600-1613 |
| 13 | `voice_provider` | DEGRADING | no voice adapter | 1614-1626 |
| 14 | `publishing` | DEGRADING | no CONNECTED YouTube and no server credentials | 1628-1658 |
| 15 | `spending_budget` | BLOCKING (PRODUCTION + unasked rule + no DAILY budget) else DEGRADING | no active budget | 320-379 |
| 16 | `daily_budget_films` | DEGRADING; INFORMATIONAL when only PRODUCTION would refuse while in TEST | the DAILY budget cannot hold the day's films (1, or 2 with an OFFICE_SERIAL channel) at the per-film ceiling | 1083-1235 |
| 17 | `youtube_upload_access` | BLOCKING | upload scope not granted or a standing token refusal | 918-960 |
| 18 | `youtube_statistics_access` | DEGRADING | statistics scope missing or a standing token/report refusal | 1011-1054 |
| 19 | `youtube_visibility` | DEGRADING | the newest upload that asked to be seen came back private (unaudited API project, PUB-05) | 963-1008 |
| 20 | `model_prices` | DEGRADING | an active agent's model lacks a price on either token unit | 382-456 |
| 21 | `agent_token_ceiling` | DEGRADING | paid model in use and `agent_daily_token_budget` = 0 | 463-517 |
| 22 | `vision_capability` | DEGRADING | no active agent whose model can see (`vision_agent`) | 520-541 |
| 23 | `character_references` | DEGRADING if a visually locked character has no readable reference, else INFORMATIONAL | missing readable reference (asset row and file on disk) | 570-612 |
| 24 | `serial_channel` | INFORMATIONAL | no OFFICE_SERIAL slot, slot unbound, or Director lacks leave to approve episodes | 615-682 |

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `run_preflight` | 1356 | builds the 24 lines, verdict, `first_stop` (first BLOCKING line, else the first failed `EMPTIES_THE_DAY` line), summary | "not optimistic" | CODE_RULE |
| `paid_rule_means` | 111 | what the next run buys unasked: nothing when stopped, in TEST, MANUAL, or with no daily budget; asks at stills under EVERY_PAID_STEP/SUPERVISED; OVER_USD cap; otherwise buys up to the sheet cap and budget | PAGE-04: «ziua merge singură» was read as «the studio buys alone» | CODE_RULE on OWNER settings |
| `_budget_check` | 320 | see line 15 | MONEY-06 / AR-07 fail-closed (2026-10-02) | CODE_RULE |
| `_price_check` | 382 | unpriced (kind, model) pairs and their missing units; never invents a price | 391 `agent_run` rows had NULL cost | CODE_RULE |
| `_token_ceiling_check` | 463 | paid kinds = openai/anthropic or priced; fails with ceiling 0 | MONEY-10 | CODE_RULE |
| `_vision_check` | 520 | names who can see | without vision a blank film passes every automatic check | CODE_RULE |
| `_readable_reference` / `_character_reference_check` | 544 / 570 | a slot is filled only by an existing asset row with the file on disk | `image_reference_for_scene` refuses a locked character's film | CODE_RULE |
| `_serial_channel_check` | 615 | slot exists / bound / `director_may_approve_episodes` | both halves are the Owner's | CODE_RULE |
| `_youtube_slots` | 761 | per CONNECTED bound slot: scopes, grant age, standing token refusal, report refusal, network silence (a refusal counts only until a later reconnect/verification) | 2026-09-18 rehearsal: green lines from the stored status alone | EXTERNAL (recorded Google answers) |
| `_youtube_upload_check` / `_youtube_statistics_check` / `_youtube_visibility_check` | 918 / 1011 / 963 | see lines 17-19 | a film nobody can upload is money spent on nothing | EXTERNAL + CODE_RULE |
| `_grant_age_caveat` | 882 | age of each grant and the 7-day Testing-mode caveat | the studio cannot see the OAuth app's status | — |
| `_daily_budget_films_check` | 1083 | PRODUCTION per-film figure = `film_ceiling_micros`; TEST = `estimate_film_cost_micros` motion hold; also reports the PRODUCTION answer while in TEST | 2026-10-02 MONEY-07: the line showed 12 USD while a six-shot sheet could cap at 26 USD | CODE_RULE + CONFIG |
| `_vault_check` | 1238 | `vault_health` | REL-06, SELL-12 | CODE_RULE |
| `_disk_check` | 1281 | `disk_reading` vs minimum | REL-08: a film writes ~1.1 GB | CODE_RULE + CONFIG |
| `_paid_rule_check` | 1323 | INFORMATIONAL line from `paid_rule_means` | PAGE-04 | — |
| `_check` | 265 | builds one line; asserts the place id exists | W31 | — |
| `_motion_knob`, `_budget_films_technical` | 1057, 1078 | names the settings holding the per-film ceiling (STUDIO_FILM_BUDGET_USD etc.) | | — |

Nested helpers in `run_preflight`/`_daily_budget_films_check`/`_youtube_slots`: `_media_missing`,
`_media_code`, `hold`, `refused`, `refusal`, `standing`. Other helpers: `_usd_cents`, `_usd`,
`_technical`, `_moment`, `_http_status`, `_auth_refused`, `_answer`, `_answers`,
`_scopes_said`, `_slot_detail` (formatting and parsing).

Data read: `owner_policy`, `agent`, `model_record`, `provider_record`, price table,
`spending_budget`, `character_bible`, `media_asset` (+ one `stat` per reference file),
`channel_record`, `publication_record`, `youtube_connection`, `domain_event` (token/report
refusals), integrations/vault health, research health, disk. Writes nothing. No network.

### `app.runbook.weekly` — `backend/app/runbook/weekly.py` (479 lines)

The Director's weekly performance review (see LLM section).

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `weekly_digest` | 82 | latest 50 PUBLISHED publications with a remote id + latest analytics snapshot each, per-channel totals, ≤10 PROPOSED recommendations, `story_performance`, optional trends | "reads only what is recorded"; numbers come from the daily `performance_intake` | CODE_RULE |
| `_digest_as_text` | 162 | the digest as Romanian sentences (≤15 videos listed) | "a prompt reads text, not JSON trees" | — |
| `execute_weekly_review` | 271 | skip checks, the Director's run, routing of the answer (LLM section) | the Owner's standing order | skips: CODE_RULE; content and routing: LLM (schema-only validation), trust ADVISORY |
| `_already_reviewed_this_week` | 257 | a SUCCEEDED/EMPTY_OUTPUT `WEEKLY_REVIEW` run since Monday 00:00 (UTC of `utc_now`) | one review per week | CODE_RULE |
| `_announce` | 467 | `agent.message_sent` speech bubble | the office shows what she did | — |

Helpers: `_iso_week_label` ("2026-S41"), `_week_start`, `_latest_metrics`, `_agent_for_role`.
Data: reads `publication_record`, `analytics_snapshot`, `channel_record`,
`director_recommendation`, `agent_run`; writes `agent_message` (HANDOFF, REQUEST_INFO,
STATUS), `agent_memory` (STRATEGY), events. External: trends via `app.analytics.trends`
(reads stored trends; `refresh_trends` is a separate job).

### `app.runbook.router` — `backend/app/runbook/router.py` (231 lines)

`/api/v1/runbook/*`, every route behind `require_owner`.

| Route / function | Line | What it does | Decided by |
|---|---|---|---|
| `GET /preflight` → `get_preflight` | 63 | `run_preflight` with the app's vault | — |
| `GET /runs` → `get_runs` | 72 | `list_runs` + `pending_daily_run` | — |
| `POST /runs` → `post_run` | 80 | `start_daily_run`; `SafeModeActive`/`RunbookError` → 409 | OWNER |
| `POST /weekly-review` → `post_weekly_review` | 95 | 409 when the worker is disabled, autonomy stopped, or a WEEKLY_REVIEW task pending; queues priority 8, `max_attempts=1`, key `weekly-review-{command_id}` | OWNER |
| `GET /company-state` → `get_company_state` | 147 | `app.agents.command.company_state` (read only) | — |
| `POST /direct` → `post_direct` | 156 | runs `direct_company` now, in the request (LLM, indirect) | OWNER triggers; LLM inside |
| `GET /decisions` → `get_decisions` | 177 | last 40 `DirectorDecision` rows + `due_reviews` | — |
| `POST /decisions/{id}/review` → `post_review_decision` | 207 | `review_decision` with the outcome text (3-4000 chars); 404 on `CommandError` | OWNER (final) |
| `GET /safe-mode` → `get_safe_mode` | 219 | `safe_mode_state` | — |
| `POST /safe-mode/clear` → `post_clear_safe_mode` | 223 | `clear_safe_mode` with notes (3-2000 chars) | OWNER |
| `create_runbook_router` | 60 | builds the router (172 lines: the ten handlers above as closures, prefix `/runbook`, `Depends(require_owner)`); mounted at `/api/v1` (`main.py:989`) | — |

Note on `POST /weekly-review`: unlike `start_daily_run`, it has no safe-mode check, and its
"already pending" test counts a CLAIMED/RUNNING task whose lease lapsed with no attempts left
(`runbook/router.py:116-123`), which `pending_daily_run` deliberately ignores for the day.

Request models:
`RunCommand`, `ReviewDecisionCommand`, `ClearSafeModeCommand` (`extra="forbid"`).

### `app.workflows.models` — `backend/app/workflows/models.py` (128 lines)

ORM tables: `workflow` (`Workflow`, 11 statuses), `workflow_step` (`WorkflowStep`),
`task_queue` (`TaskQueueItem`: type, payload, priority, status, attempts/max_attempts,
backoff, `next_attempt_at`, lease token/expiry, unique `idempotency_key`, error),
`scheduled_job` (`ScheduledJob`: unique name, type, interval, active, last/next run, missed
policy SKIP/CATCH_UP, `run_at_local` + `timezone`, leader token, event id), `outbox_record`
(`OutboxRecord`: autoincrement sequence, event id, destination, PENDING/PUBLISHED/FAILED,
payload). No functions.

### `app.workflows.schemas` — `backend/app/workflows/schemas.py` (111 lines)

Pydantic commands and views: `CreateWorkflowCommand`, `WorkflowStepView`, `WorkflowView`,
`WorkflowDetailView`, `TaskQueueItemView`, `CreateScheduledJobCommand` (interval 5 s - 30 d,
missed policy literal), `SetJobActiveCommand`, `ScheduledJobView` (with `run_at_local`,
`timezone`), `ReplayRequest` (unused by the socket, which parses with `replay_window`). No
functions.

### `app.workflows.services` — `backend/app/workflows/services.py` (920 lines)

The durable queue, leases, scheduler and the transactional-outbox helper. The queue and
scheduler writers take `lock_for_write` first (`enqueue_task`, `claim_task`,
`sweep_interrupted_tasks`, `heartbeat_task`, `complete_task`, `fail_task`,
`retry_dead_letter_task`, `ensure_scheduled_job`, `set_job_active`, `scheduler_tick`; several
dated incidents of «database is locked»: `services.py:297-300`, `706-709`, `757-759`,
`808-811`). Three writers do **not**: `create_workflow` (`:160`), `transition_workflow`
(`:222`) and `create_scheduled_job` (`:589`, which `ensure_scheduled_job` calls outside its own
lock at `:720`); `append_event_with_outbox` writes in the caller's session. Spec:
`18_AUTOMATION_ORCHESTRATION.md` (timezone, DST), `09_CHANNELS_AND_AUTOMATION.md` ("never
create a backlog explosion").

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `append_event_with_outbox` | 102 | appends a `DomainEvent` and an `OutboxRecord` (WEBSOCKET) in the caller's session | events reach the page only if their transaction commits | — |
| `create_workflow` | 152 | creates a Workflow (CREATED, stage DISCOVERY) and its first step | Phase 2 API; nothing executes it (Oddities) | — |
| `transition_workflow` | 212 | enforces `VALID_WORKFLOW_TRANSITIONS`, event `workflow.<status>` | | CODE_RULE |
| `list_workflows`, `get_workflow_detail` | 251, 257 | reads | | — |
| `enqueue_task` | 277 | idempotent insert under the write lock; `not_before` delays the first claim | 2026-10-09 16:47: a FILM_CONTINUE deferral died on «database is locked» between the key lookup and the insert | CODE_RULE |
| `claim_task` | 333 | refuses while stopped; claims the highest-priority eligible task (QUEUED/RETRYING due, or lapsed lease with attempts left), new lease token, attempts+1 | REL-03 (a day re-run after a crash), AR-17 (distinct tokens per claim) | CODE_RULE / OWNER stop |
| `new_lease_token` | 394 | `<worker_id[:27]>:<uuid hex>` | AR-17 | — |
| `sweep_interrupted_tasks` | 399 | lapsed lease + no attempts left → DEAD_LETTER "INTERRUPTED: …", event `workflow.task_interrupted`; not behind the stop | a dead task must not be re-run (its purchases) and a stale CLAIMED day must not refuse the Owner's start | CODE_RULE |
| `heartbeat_task` | 464 | extends the lease while still held | used by `LeaseKeeper` | CODE_RULE |
| `complete_task` / `fail_task` | 483 / 502 | finish under the lease token or raise `LeaseLost`; `fail_task` → RETRYING with exponential backoff or DEAD_LETTER | the outcome is never written over a new holder's | CODE_RULE |
| `retry_dead_letter_task` | 534 | DEAD_LETTER → QUEUED, attempts 0 | operator intervention | OWNER |
| `list_queue_tasks` | 556 | newest first, optional status filter | | — |
| `create_scheduled_job` | 574 | creates an active job, next run = now + interval, event `workflow.job_scheduled` | a schedule is an autonomy decision and is recorded | OWNER (API) / CODE_RULE (seeding) |
| `list_scheduled_jobs` | 623 | read | | — |
| `next_run_after` | 629 | SKIP: now + interval; CATCH_UP: first slot after now on the original anchor; the missed slot fires once either way | no backlog explosion | CODE_RULE |
| `next_local_occurrence` | 653 | next instant the local clock reads HH:MM, compared as instants | DST: 05:00 stays 05:00; a slot in the repeated hour fires once | CODE_RULE |
| `ensure_scheduled_job` | 681 | create-if-missing (idempotent by name); an existing job follows a changed hour/timezone but never its active flag | start-up seeding | CONFIG |
| `set_job_active` | 748 | activate/deactivate with event `workflow.job_activated`/`_deactivated`; waking sets the next slot from now (never fires on the spot) | 2026-10-09: a commit race refused a «stop» with a 500 and left the daily job active | OWNER |
| `scheduler_tick` | 791 | under the write lock: refuse when stopped; for each active due job queue one task (key `scheduled:{job}:{due_at}`, `max_attempts=1`, priority 0), event `workflow.job_fired`, move `next_run_at` | AR-14: no Workflow row per fire (665 inert rows in the live copy) | CODE_RULE |

Helpers: `_held`. Exceptions: `InvalidStateTransitionError`, `LeaseLost` (a ValueError).
Events: `workflow.created`, `workflow.<status>`, `workflow.task_interrupted`,
`workflow.job_scheduled`, `workflow.job_activated`, `workflow.job_deactivated`,
`workflow.job_fired`; `workflow.task_lease_lost` is written by the worker.

### `app.workflows.worker` — `backend/app/workflows/worker.py` (835 lines)

The background worker: one loop in the server process (`main.py:581-613`), one per database.

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `build_task_handlers` | 162 | the dispatch table (12 task types, below) | the only door from the queue to the studio's work | CODE_RULE |
| `LeaseKeeper` (`__init__` 523, `_run` 541, `__enter__` 559, `__exit__` 563) | 513 | renews the lease every half lease in a daemon thread; marks `lost` and stops when no longer held | A16/AR-17: `heartbeat_task` had no caller, a long day was handed to the next claimer | CODE_RULE |
| `_lease_lost` | 573 | event `workflow.task_lease_lost`, result LEASE_LOST | loud, recorded | — |
| `work_once` | 604 | no claim during shutdown; claim with 3600 s lease; unknown type → DEAD_LETTER; run the handler under `LeaseKeeper`; `NonRetryable` → DEAD_LETTER; other exception → `fail_task(retryable=True)`; success → COMPLETED | | CODE_RULE |
| `announce_interrupted` | 669 | for swept tasks: DAILY_RUN → `interrupt_task_day`; FILM_CONTINUE → letter | each told once | CODE_RULE |
| `_tell_continue_interrupted` | 691 | ESCALATE letter: the continuation is not restarted by itself; the next daily run resumes the film; the Owner's approval stands until it expires | | CODE_RULE |
| `worker_pass` | 721 | (shutdown → nothing) sweep + announce; run `SCAN_FILM_SHEETS` directly; `scheduler_tick`; up to `TASKS_PER_PASS` (3) `work_once`; then the mail round when a registry exists | | CODE_RULE |
| `WorkerLock` (`__init__` 775, `release` 779) | 767 | holds an OS lock on the lock file beside the database (`worker_lock_path`) | AR-17: two workers on one database | CODE_RULE |
| `_lock` / `_unlock` | 792 / 804 | `msvcrt.locking` on Windows, `fcntl.flock` elsewhere, non-blocking | | — |
| `acquire_worker_lock` | 815 | the lock or None | | CODE_RULE |
| `worker_lock_path` | 828 | the SQLite file's path with its suffix replaced by `.lock` (`Path(database).with_suffix(".lock")`: `data/studio.db` → `data/studio.lock`); None in memory or on a server | | — |

The dispatch table (`worker.py:497-510`), nested in `build_task_handlers`:

| Task type | Handler (line) | What it runs | Gate / rule in the handler | LLM? |
|---|---|---|---|---|
| `DAILY_RUN` | `daily_run` (171) | `execute_daily_run` with `app.state.stage_runners` (or `resume_runners` for `resume_of`) | stale retry/resume date → SKIPPED; non-manual: skip a cut/done day or attempts spent; manual bypasses; `SafeModeActive` → `NonRetryable`; queues the same-day re-attempt | yes, through the stage runners |
| `FILM_CONTINUE` | `film_continue` (326) | `app.runbook.stages.continue_film` | no `storyboard_id` → NonRetryable; FILM_BUSY → deferral ×3 | yes (Director review, prompt writing; paid steps under the Owner's rule) |
| `WEEKLY_REVIEW` | `weekly_review` (366) | `execute_weekly_review` | registry required; `WeeklyReviewError` → NonRetryable | yes (call site) |
| `TRENDS_REFRESH` | `trends_refresh` (380) | `app.analytics.trends.refresh_trends` | — | no static path (EXTERNAL fetch) |
| `MODEL_RESEARCH` | `model_research` (412) | `app.media.model_research.research_all` | registry required | yes (static distance 2) |
| `MODEL_REVIEW` | `model_review` (407) | `app.integrations.lifecycle.review_models(full=False)` | — | no ("generates nothing", `worker.py:93-96`) |
| `DIRECTOR_LOOP` | `director_loop` (385) | `app.agents.command.direct_company` (returns a trimmed summary) | — | yes |
| `DIRECTOR_REPAIR` | `director_repair` (400) | `app.agents.repairs.desk.execute_repair` | the kernel is asked again when it runs (`worker.py:106-108`) | no static path, but **yes at runtime**: a registered repair is called through a table (`agents/repairs/desk.py:570-581`), and `switch_model` probes models with `run_agent_task` (`agents/repairs/agent_health.py:568-597`) |
| `WATCHDOG` | `watchdog` (419) | `app.workflows.watchdog.run_watchdog` | ImportError → NonRetryable | no |
| `BACKUP` | `backup` (429) | `app.backup.run_backup_job` | not COMPLETED → NonRetryable (its own letter is written there) | no |
| `FILM_SHEET_REPAIR` | `sheet_repair` (445) | `app.media.blocker_repair.process_sheet_repair` with `repair_wiring()` | registry required | yes (static distance 3) |
| `SCAN_FILM_SHEETS` | `scan_sheets` (461) | `scan_sheet_issues(read_live=True)`: reads every sheet; a sheet with blockers gets a report to the Director and a queued `FILM_SHEET_REPAIR` task (`submit_sheet_issues`, priority 6, `max_attempts=1`, `media/blocker_repair.py:437-548`); a sheet now clean closes its pending repair RESOLVED | throttled to `sheet_blocker_scan_seconds`; needs a registry and `blocker_repair.allowed` (not stopped, mode not MANUAL, no shutdown, no safe mode, `media/blocker_repair.py:314-318`) | no (it queues the FILM_SHEET_REPAIR that does) |

Nested helpers: `_environment` (policy environment), `repair_wiring` (sheet wiring from
`app.runbook.stages.sheet_wiring`). Constants name the seeded jobs: `DAILY_JOB_NAME`
`daily_main`, `TRENDS_JOB_NAME`, `MODEL_RESEARCH_JOB_NAME`, `MODEL_REVIEW_JOB_NAME`,
`DIRECTOR_LOOP_JOB_NAME`, `WATCHDOG_JOB_NAME`, `BACKUP_JOB_NAME` (`worker.py:72-122`).

Seeded schedule (CONFIG, `backend/app/main.py:475-575`, only in the process that holds the
worker lock):

| Job | Type | Cadence | Active at birth | First run |
|---|---|---|---|---|
| `daily_main` | DAILY_RUN | 05:00 local (`daily_run_hour_local`), CATCH_UP | **no** (the Owner starts it) | next 05:00 |
| `watchdog` | WATCHDOG | 600 s, SKIP | yes | +600 s |
| `weekly_review` | WEEKLY_REVIEW | 7 d, CATCH_UP | yes | +1 h |
| `trends_daily` | TRENDS_REFRESH | 1 d, CATCH_UP | yes (when `trends_enabled`) | +120 s |
| `model_research_weekly` | MODEL_RESEARCH | 7 d, CATCH_UP | yes (not in demo) | +2 h |
| `model_review_daily` | MODEL_REVIEW | 1 d, SKIP | yes | +15 min |
| `director_loop` | DIRECTOR_LOOP | 6 h, SKIP | yes | +30 min |
| `backup_daily` (`app/backup.py:70`) | BACKUP | 03:30 local (`backup_hour_local`, `config.py:123`), CATCH_UP | yes | next 03:30 |

`first_run_at` and `active` apply only when a job is created: for a job that already exists,
`ensure_scheduled_job` changes nothing but a changed wall-clock hour or timezone
(`workflows/services.py:710-719`), so after a restart each job fires when its persisted
`next_run_at` comes due (at the first worker pass if it is already past).

### `app.workflows.watchdog` — `backend/app/workflows/watchdog.py` (1007 lines)

One pass every 10 minutes; nothing while the Owner's stop is set ("a stopped studio is a
studio in which nothing moves, including repair", `watchdog.py:42-44`). The GPU guard is
deliberately not here (ADR-GPU-OFF-ALWAYS, `16_DECISION_LOG.md:4200`).

`run_watchdog` (`watchdog.py:803-1007`) order:

1. stop check → SKIPPED (`822-838`);
2. built-in parts **without** their own try (an exception ends the pass after running the
   registered passes, `852-878`): `_fail_stuck_renders`, `_reconcile_publications`,
   `_follow_processing` (has its own try), `_lapsed_leases`, `release_stale_reservations`;
3. each in its own try: `reclaim_abandoned_leases` (film purchase leases, `882-890`),
   `_collect_paid_tasks` (`893-902`), `_interrupted_days` (`905-909`),
   `release_studio_defect_holds` (`915-921`), `propose_release_cards` (RunPod unsent holds,
   `927-934`), `retire_answered_letters` (`940-952`), `_sweep_failed_intermediates`
   (`955-959`);
4. `_run_registered_passes` (`962`).

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `run_watchdog` | 803 | the pass above; logs `watchdog_pass` | | CODE_RULE |
| `_autonomy_stopped` | 135 | stop flag; a missing policy row reads as stopped | | OWNER |
| `_fail_stuck_renders` | 161 | RENDERING older than threshold → FAILED, log appended, `media.render_failed` (`watchdog: True`), VideoEditor set IDLE if WORKING | two renders RENDERING since 2026-09-12 | CODE_RULE + CONFIG |
| `_default_publisher_for` | 222 | channel → the bound YouTube provider from the vault; raises `NoPublisher` when unbound/disconnected | | CONFIG + EXTERNAL |
| `_attempts_so_far` | 251 | counts `publishing.watchdog_reconcile` events since the Owner's last `publishing.resolved_by_owner` | "the record is the counter"; an answered row must not return to the Owner at once | CODE_RULE |
| `_record_attempt`, `_hand_to_owner` | 280, 295 | event per attempt; `hand_to_owner` (manual repair queue + one letter) | | CODE_RULE |
| `_reconcile_publications` | 301 | `mark_stale_started`; up to 20 REMOTE_UNKNOWN/FAILED_RETRYABLE rows: wait (by-title rows < 15 min), hand over after max attempts, else `reconcile_by_title` / `reconcile_publication` / `execute_publication`; counts outcomes | PUB-01/PUB-08; decision "Repair is bounded" (`16_DECISION_LOG.md:1848`) | CODE_RULE + EXTERNAL |
| `_follow_processing` | 439 | `check_processing` (videos.list, 1 quota unit) for PUBLISHED videos of the last 6 h not settled | PUB-08: a rejected upload must not stay PUBLISHED | EXTERNAL |
| `_lapsed_leases` | 496 | reports expired leases only (the queue and the sweep own them) | "two owners of one row" avoided | — |
| `_default_collector_for` | 515 | adapter for a SUBMITTED take: the RunPod integration of its `GenerationJob` (VERIFIED/ACCESS_VERIFIED) or the Runway connection | | CONFIG |
| `_collect_paid_tasks` | 568 | `assembler.collect_submitted_takes`, excluding films whose purchase lease is held | a task the vendor accepted (and may have billed) that nobody collected | EXTERNAL |
| `_sweep_failed_intermediates` | 602 | deletes failed renders' shot/card clips when the Owner turned it on | REL-08 disk | CONFIG |
| `_interrupted_days` | 621 | `interrupt_stale_runs(lease_seconds=3600)` | REL-03 | CODE_RULE |
| `_stop_pressed` | 643 | the stop, re-read; unreadable = pressed | "a stop nobody can read is not a go" | OWNER |
| `_report_load_errors` | 652 | one `studio.registry_module_failed` event per failing pass/producer module per boot (not while stopped) | a pass or card producer that does not import must be said | CODE_RULE |
| `_run_registered_passes` | 698 | each pass in its own try, stop re-read before each, non-dict answer = failure, `{**on_error, error: True}`; also loads `app.decisions.producers` to report import errors | 2026-10-09 review | CODE_RULE |
| `_passes_after_a_failed_part` | 770 | runs the registered passes when a built-in part raised, then re-raises the original | money repairs must not be skipped by an unrelated lock | CODE_RULE |

Helpers: `_elapsed_text`, `_parse`. Exception: `NoPublisher`. Events written here:
`media.render_failed`, `publishing.watchdog_reconcile`, `studio.registry_module_failed`
(others by the called modules). External calls: YouTube reads (reconcile, title lookup,
processing) and **uploads** for FAILED_RETRYABLE rows; vendor task GETs (RunPod/Runway);
nothing is bought.

### `app.workflows.passes` — `backend/app/workflows/passes/__init__.py` (186 lines)

The registry of watchdog passes (2026-10-09, P0 self-repair plan). Rules a pass keeps
(`passes/__init__.py:26-45`): repair for free or propose a card, never buy/approve/move money,
never answer in the Owner's name (no `decide_owner_decision`, no appliers, no
`issued_by=OWNER`), idempotent, import defines only, top-level function or lambda (the money
and Owner scans in `tests/test_watchdog_passes.py` read only those), small JSON result whose
name is not a built-in key.

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `register_pass` | 115 | validates name (`^[a-z][a-z0-9_]{0,59}$`, not a built-in key), integer order, no different function under the same name; registers and tells `PackageLoader` to drop it if its module fails to import | CODE_RULE |
| `watchdog_pass` | 139 | decorator form | — |
| `_same` | 151 | the same function re-registered (module imported twice) | — |
| `registered_passes` | 164 | loads the package once, sorted by (order, name) | — |
| `unregister_pass` | 171 | test helper | — |

Types: `WatchdogContext(engine, settings, correlation_id)`, `WatchdogPass(name, order,
function, on_error)`, `BUILT_IN_RESULT_KEYS`, `PASSES = PackageLoader(__name__)`.

The eleven registered passes at a glance (run order = `order`, then name; each is detailed in
its own section below). None takes a registry, so none can run a model itself; a FILM_CONTINUE
it queues runs models later, in the worker.

| Pass (function) | File:line | Order | What it does | Writes / spends | Decided by |
|---|---|---|---|---|---|
| `resume_interrupted_day` (`resume_interrupted_days`) | `passes/resume_interrupted_day.py:30` | 20 | queues a DAILY_RUN `resume_of` today's INTERRUPTED run | queue row + event; the resumed day buys under the Owner's rule | CODE_RULE |
| `vendor_plan_licence` (`read_vendor_plans`) | `passes/vendor_plan_licence.py:18` | 120 | reads the ElevenLabs plan and records the licence | GET only | EXTERNAL under an OWNER card |
| `licence_release` (`make_licensed_uploads_public`) | `passes/licence_release.py:24` | 130 | makes licence-held private uploads public | YouTube privacy change | EXTERNAL + CODE_RULE |
| `character_references` (`register_character_portraits`) | `passes/character_references.py:172` | 140 | fills empty, unlocked `portrait` slots from verified Owner-supplied PNGs | file copy, MediaAsset, event, bible slot | CONFIG |
| `restore_retired_takes` (`give_back_what_redos_left`) | `passes/restore_retired_takes.py:45` | 140 | gives back takes a redo retired and delivered nothing for | take statuses, scene words, events | CODE_RULE |
| `replaced_boards` (`close_replaced_boards`) | `passes/replaced_boards.py:20` | 145 | closes storyboards a story repair replaced | storyboard REJECTED | CODE_RULE |
| `owner_choice_continuation` (`queue_missed_continuations`) | `passes/owner_choice_continuation.py:58` | 150 | walks once a film left standing (missed Owner choice, render failed before start, studio-side WAITING/HELD) | FILM_CONTINUE (PRODUCTION) | CODE_RULE |
| `ladder_retry` (`queue_ladder_retries`) | `passes/ladder_retry.py:67` | 155 | re-walks a film stopped on the Director's ladder | FILM_CONTINUE (PRODUCTION) | CODE_RULE |
| `director_qc_review` (`queue_director_reviews`) | `passes/director_qc_review.py:75` | 160 | puts a QC-failed film before the Director again | FILM_CONTINUE (PRODUCTION) | CODE_RULE |
| `serial_unfilmed` (`finish_approved_episodes`) | `passes/serial_unfilmed.py:65` | 160 | builds a missing serial storyboard and walks standing serial boards | storyboard (any environment) + FILM_CONTINUE (PRODUCTION) | CODE_RULE |
| `training_set` (`collect_training_samples`) | `passes/training_set.py:69` | 170 | appends approved takes to the LoRA manifest; milestone letter at 100 serial clips | manifest file, events, one letter | CODE_RULE |

### `app.workflows.passes.resume_interrupted_day` — `passes/resume_interrupted_day.py` (93 lines, order 20)

`resume_interrupted_days` (line 30): today's `resumable_run`; held while `stop_requested`,
safe mode, or a DAILY_RUN pending; else `enqueue_task(DAILY_RUN, {resume_of, date, cause:
"resume_after_start", stage}, priority=8, max_attempts=1, key "daily-resume-{run}")` and
event `runbook.daily_run_resume_queued`. Why: the Owner's 2026-10-12 07:40 restart rule.
Decided by: CODE_RULE. Money: the resumed day runs the stages not completed, including media
(purchases under the Owner's rule in `app.runbook.stages`).

### `app.workflows.passes.vendor_plan_licence` — `passes/vendor_plan_licence.py` (25 lines, order 120)

`read_vendor_plans` (line 18): `app.integrations.plan_licence.record_plan_licences` with the
vault at `<db>.credentials.key`. Reads the Owner's ElevenLabs plan (a GET that buys nothing)
at most hourly for a connection without the licence; allowed by the Owner's card «Da,
citește singur». Decided by: EXTERNAL (vendor plan) under an OWNER card.

### `app.workflows.passes.licence_release` — `passes/licence_release.py` (37 lines, order 130)

`make_licensed_uploads_public` (line 24): when `licence_held_uploads` exist,
`release_licence_held_uploads` with the default publisher. Film babcf272 went up private for
want of a confirmed narration licence (2026-10-10); this makes it public once the licence is
recorded, "under the channel's policy as it is then, the Owner's stop, safe mode and mode read
first" (module docstring). Decided by: EXTERNAL licence + CODE_RULE channel policy.
External: YouTube privacy change (publishing).

### `app.workflows.passes.character_references` — `passes/character_references.py` (361 lines, order 140)

Registers the Owner-supplied character sheets as each bible's `portrait` reference for free
(the Owner 2026-10-11: «Cauta pozele caracterelor/agentilor…»).

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `register_character_portraits` | 172 | reads `config/character_references.json`; for each named bible whose portrait slot is empty (an asset id with a live row), not visually locked, file present, SHA-256 equal to the config's, a real PNG, and not registered before (event mark), copies it to `<media_root>/references/<id>/portrait.png`, writes a `MediaAsset` (`provider_name` OWNER_SUPPLIED) and event `media.character_reference_registered`, fills the slot; re-checks filled/locked under the write lock | CONFIG (verified file) + OWNER lock respected |
| `png_dimensions` | 73 | width/height from the IHDR header, None if not PNG | — |
| `_entries` | 87 | parses the config; incomplete entries are problems, never a crash | — |
| `_slot_filled` | 131 | slot filled only if the asset row exists («Start over» deletes assets, keeps bibles) | CODE_RULE |
| `_locked` | 147 | `identity_locks_json.visual` | OWNER |
| `_store` | 154 | writes the file unless identical bytes exist; a different file keeps its name and the new one gets a hash suffix | — |

Helper: `_problem`. Review 2026-10-11 rules: a locked character is left to the Owner (the
first version lifted the Owner's block within ten minutes of a restart); a dangling slot is
empty; problem details in Romanian.

### `app.workflows.passes.restore_retired_takes` — `passes/restore_retired_takes.py` (118 lines, order 140)

`give_back_what_redos_left` (line 45): for each redo (one correlation id per scene) whose
`media.scene_take_retired` events of the last 7 days were not yet given back, skipping films
with a live `FilmPurchaseLease` or closed films, calls `assembler.give_back_retired_takes`
(restores only when nothing was delivered for the scene since, never a take the Owner turned
down, and puts the scene's words back). Why: film babcf272 — a QC redo retired the Owner's
approved takes and delivered nothing. Decided by: CODE_RULE. Writes take statuses, scene
prompts and their events; buys nothing.

### `app.workflows.passes.replaced_boards` — `passes/replaced_boards.py` (23 lines, order 145)

`close_replaced_boards` (line 20): `app.media.sheet_story_repair.retire_replaced_boards` —
storyboards a story repair replaced become REJECTED by the Director, takes and files kept.
Why: the Owner 2026-10-11 «De ce există 2 Storyboard? Trebuie doar 1!». Decided by:
CODE_RULE.

### `app.workflows.passes.owner_choice_continuation` — `passes/owner_choice_continuation.py` (183 lines, order 150)

`queue_missed_continuations` (line 58) queues one FILM_CONTINUE (via `queue_film_continue`,
PRODUCTION only) for three kinds of standing film in the last 7 days:

1. the newest scene-model choice with `decided_by == "owner"` (`SCENE_MODEL_EVENT`) whose
   continuation key `film-continue-{film}-scene-model-{event}` was never queued and with no
   walk after it (cause `scene_model:{scene}:{model}:missed`);
2. a film whose newest `media.render_failed` predates this process's `STARTED_AT`, with no
   completed render since and no walk since the start (cause `render_failed_before_start`);
3. a film whose newest `runbook.film_state` before the start is WAITING/HELD for a refusal
   that is neither in `OWNER_DECIDES` (`runbook/stages.py:1441`) nor STORY_GATE, storyboard
   APPROVED and not closed (cause `unfinished_before_start:{refusal}`).

Why: babcf272 (a choice that never walked its film; an encoder crash) and NASA 6fe6a577
(«Studioul ar trebui să realizeze că sunt lucruri neterminate…»). Decided by: CODE_RULE
(case 1 carries out an OWNER choice already made).

### `app.workflows.passes.ladder_retry` — `passes/ladder_retry.py` (212 lines, order 155)

`queue_ladder_retries` (line 67): PRODUCTION only; nothing while any `BRIEF_TASK` agent run
is RUNNING; for films whose newest walk stopped WAITING on `LADDER_REFUSALS`
(NEEDS_OWNER, TAKES_NOT_ACCEPTED, `runbook/stages.py:1611`), storyboard APPROVED and not
closed, with QC-refused scenes (`quality_refused`), whose newest brief attempt (BRIEF_EVENT,
or before 2026-10-11 the brief run under one of the film's continuations) did not rewrite and
is older than 20 min, with no walk in those 20 min and fewer than 6 retries today → queue
FILM_CONTINUE (cause `director_ladder_retry`, key `film-continue-{film}-ladder-retry-{day}-{n}`).
Helpers `_when`, `_retry_prefix`; nested `walked_since`, `newest_attempt`. Why: cyclotron
00000160 (brief refused by its schema twice, film left WAITING NEEDS_OWNER). Decided by:
CODE_RULE; the brief itself is the Director's (LLM) inside the continuation.

### `app.workflows.passes.director_qc_review` — `passes/director_qc_review.py` (180 lines, order 160)

`queue_director_reviews` (line 75): PRODUCTION only; for each film's newest COMPLETED render,
skipping films with a pending FILM_CONTINUE, REJECTED storyboards and films whose redo-cap
card (`decisions.producers.redo_cap`) waits for the Owner (`_his_card_open`, line 56): the
newest non-INVALIDATED QC report FAILED within 7 days with no final decision of the Director
(`media.director_qc.decision_state`; a pending REPAIR whose bought take is `ready` or awaits
her `look` counts as undecided), fewer than 24 rounds that reached her, and the back-off since
her last ask/walk elapsed (60 min doubling for walks that never reached her, cap 1440) →
queue FILM_CONTINUE (cause `director_qc:{report}`, key per report and walk count). Why: film
babcf272 (2026-10-10) — a mechanical redo retired approved takes; nothing is redone before
the Director reads a failed report. Decided by: CODE_RULE (queueing); the repair decision is
the Director's in the walk. Separate from this pass, which acts only on a film's FAILED QC
report: since 20abffd, each time a paid still re-roll (the still rounds of her repair included)
or a paid clip retry would be bought for one refused picture, the Director first gets a free
second look at that picture, and a refusal she overturns buys nothing
(`backend/app/media/stills_stage.py:1143-1149`, `backend/app/media/qc.py:2670-2683`; README §8).
Only refusals code lets her overturn are shown to her: faces the bible forbids, writing, panels
and degenerate pictures stay the code's (`HARD_LIMITS`, `backend/app/media/fix_check.py:130`).

### `app.workflows.passes.serial_unfilmed` — `passes/serial_unfilmed.py` (228 lines, order 160)

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `finish_approved_episodes` | 65 | (a) APPROVED `StoryEpisode` with no storyboard, created within 7 days and approved (newest `story.episode_approved`, else its creation) > 15 min ago → `ready_for_filming` (no registry → no model; it builds the storyboard in **any** environment, TEST included, `passes/serial_unfilmed.py:126-134`) and queue its continuation under the stage's own key `serial_continuation_key` (PRODUCTION only, via `queue_film_continue`); (b) APPROVED serial storyboards (series key) with no completed render, not continued since the start, not taken by the day's run of this process (`serial_films_due` rule), and whose last walk is older than the start and not stopped on `OWNER_DECIDES` → queue a walk (key `after_start_key`) | CODE_RULE |
| `after_start_key` | 59 | `film-continue-{storyboard}-serial-after-start-{started}` | — |

Why: episode 043317d3 «The Zero Script Club», APPROVED 2026-10-11 12:46 with no storyboard;
the serial had never made a public episode (the Owner: «Agenția trebuie să fie autonomă»).
Writes storyboards (through `app.story.serial_stage`) and queue rows.

### `app.workflows.passes.training_set` — `passes/training_set.py` (209 lines, order 170)

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `collect_training_samples` | 69 | appends every APPROVED still/test_shot/motion take whose file exists and is not yet in `<media_root>/training/manifest.jsonl` (film, scene, path, hash, scene prompt, whether the still was bought on exactly those words, camera move, seconds, resolution, model, look version, approver); event `training.samples_added`; at ≥100 approved serial clips, once, `training.milestone_reached` and a STATUS letter to the Owner that the LoRA training is the Owner's card | CODE_RULE |
| `manifest_path` | 39 | `media_root/training/manifest.jsonl` | — |
| `read_manifest` | 45 | JSON lines, bad lines skipped | — |
| `_prompt_of` | 63 | still or motion prompt from the scene package | — |

Why: the Owner 2026-10-11 «Strângem setul de date de acum, antrenăm după ~100 de clipuri».
Nothing is trained or bought here. Since 20abffd "APPROVED" also covers a still the stills gate
refused and the Director's second look let stand (`approved_by = "director_look"`,
`backend/app/media/stills_stage.py:1017-1035`, `backend/app/media/fix_check.py:126`); the pass
does not filter on the approver, it copies `approved_by` into the manifest
(`passes/training_set.py:89`, `:140`). A clip her look keeps stays PAID, not APPROVED (its report
is written PASSED and the take's status is left as it is, `backend/app/media/assembler.py:10361-10373`,
`:5161-5174`), so it enters the manifest only once it is approved later.

### `app.workflows.publisher` — `backend/app/workflows/publisher.py` (180 lines)

| Function | Line | What it does | Why | Decided by |
|---|---|---|---|---|
| `ConnectionManager` (`__init__` 26, `connect` 29, `add` 33, `disconnect` 38, `active_count` 43, `broadcast` 46) | 23 | the set of authenticated sockets; `broadcast` sends JSON to all and drops failed ones | | — |
| `claim_pending_outbox` | 63 | plain read first; then under the write lock mark ≤100 oldest PENDING rows PUBLISHED and commit; only then enrich with register words and return messages | REL-12 2026-10-02: broadcasting before the commit re-sent events on a failed commit | CODE_RULE |
| `_with_words` | 104 | `events_feed.enrich`; failure keeps the events | 2026-10-12: the page kept the first, wordless copy of an event | — |
| `_broadcast_all` | 119 | broadcasts each message, one failure does not lose the rest | | — |
| `dispatch_pending_outbox` | 127 | claim in a thread, broadcast on the server loop (every 1 s, `main.py:337-354`) | a write lock elsewhere must not stall requests | — |
| `publish_pending_outbox` | 141 | same for callers without a loop (scripts, tests) | | — |
| `replay_events` | 164 | events after a sequence (limit), with words | reconnect catch-up | — |

### `app.workflows.router` — `backend/app/workflows/router.py` (259 lines)

All REST routes behind `require_owner`; the socket authenticates by first message.

| Route / function | Line | What it does | Decided by |
|---|---|---|---|
| `POST /workflows/` → `post_workflow` | 55 | `create_workflow` | OWNER |
| `GET /workflows/` → `get_workflows` | 59 | list | — |
| `GET /workflows/{id}` → `get_workflow` | 63 | detail or 404 | — |
| `POST /workflows/{id}/pause` / `resume` / `cancel` | 73 / 85 / 97 | `transition_workflow` → PAUSED / RUNNING / CANCELLED; 409 illegal, 404 missing | OWNER (no runtime effect) |
| `GET /tasks/queue` → `get_queue` | 115 | queue list (limit 1-100, status filter) | — |
| `POST /tasks/{id}/retry` → `retry_task` | 123 | `retry_dead_letter_task`; 400 on error | OWNER |
| `GET /scheduler/jobs` → `get_jobs` | 139 | list jobs | — |
| `POST /scheduler/jobs` → `post_job` | 143 | `create_scheduled_job` (active immediately) | OWNER |
| `POST /scheduler/jobs/{id}/active` → `post_job_active` | 147 | `set_job_active` | OWNER |
| `POST /scheduler/tick` → `post_tick` | 157 | `scheduler_tick` now | OWNER |
| `WEBSOCKET /api/v1/ws` → `websocket_endpoint` | 178 | refuse a key in the URL; accept; first message auth within 5 s; `auth_ok`; join broadcast; handles `ping` and `replay` (`replay_window`); always leaves the broadcast on exit (SEC-10) | CONFIG (owner token) |
| `replay_window` | 241 | validates whole numbers, `after_sequence ≥ 0`, `limit ≥ 1`, caps at 500 | CODE_RULE |
| `create_workflows_router`, `create_tasks_router`, `create_scheduler_router`, `register_websocket_gateway` | 52, 112, 136, 165 | builders | — |

Helpers: the nested handlers of the pause / resume / cancel routes above,
`create_workflows_router.pause_workflow` (74), `.resume_workflow` (86) and `.cancel_workflow` (98)
(the table gives their decorator lines 73 / 85 / 97).

### `app.workflows` package init — `backend/app/workflows/__init__.py` (0 lines)

Empty.

## Connections

**Called by (into this group).**
- `backend/app/main.py`: lifespan clears/requests shutdown (`329`, `622`, `666`), runs the
  outbox dispatcher (`337-354`), takes the worker lock (`397-413`), seeds the scheduled jobs
  (`475-575`), builds the handlers with `app.state.stage_runners` and the registry (`576-578`),
  runs `worker_pass` every `worker_interval_seconds` in a thread (`581-613`), includes the
  routers (`965-968`, `989`).
- `app.runbook.stages` (another group) supplies the stage runners and `continue_film`; it
  calls `stop_requested`, `stop_reason_words`, `TransientStageError` and the outbox helper.
- Many modules call `append_event_with_outbox`, `enqueue_task`, `stop_requested`,
  `shutdown_requested`, `safe_mode_state`; `app.services.queue_film_continue` writes
  `TaskQueueItem` rows directly (`backend/app/services.py:645-689`);
  `app.media.blocker_repair.allowed` reads `shutdown_requested` and `safe_mode_state`.

**Calls out to.**
- Runbook: `app.story.services` (business date, log closes), `app.wording` (Romanian
  wording), `app.agents.messages.post_message`, `app.agents.memory`, `app.agents.director.
  letter_to_owner`, `app.media.services.films_now`, `app.integrations.autoconfig`,
  `app.media.factory`.
- Preflight: `app.economy.budget`, `app.economy.prices`, `app.integrations.services.
  vault_health`, `app.media.disk`, `app.media.factory`, `app.media.toolchain`,
  `app.media.shooting_sheet.film_ceiling_micros`, `app.publishing.services`,
  `app.research.service.research_health`, `app.youtube.services`, `app.agents.vision`,
  `app.services` (paid media policy, environment).
- Weekly: `app.agents.services.run_agent_task`, `app.agents.identity`, `app.analytics.*`.
- Worker handlers: `app.runbook.stages`, `app.agents.command`, `app.agents.repairs.desk`,
  `app.agents.mail`, `app.analytics.trends`, `app.media.model_research`,
  `app.integrations.lifecycle`, `app.media.blocker_repair`, `app.backup`.
- Watchdog and passes: `app.publishing.services`, `app.publishing.licence_release`,
  `app.economy.budget.release_stale_reservations`, `app.media.shooting_sheet`
  (`reclaim_abandoned_leases`, `held_films`, `film_is_closed`), `app.media.assembler`
  (`collect_submitted_takes`, `release_studio_defect_holds`, `sweep_failed_intermediates`,
  `give_back_retired_takes`), `app.media.runpod_unsent`, `app.media.answered_letters`,
  `app.media.sheet_story_repair`, `app.media.director_qc`, `app.media.scene_rewrite`,
  `app.story.serial_stage`, `app.integrations.plan_licence`, `app.decisions.producers`,
  `app.events_feed`.

**Events emitted** (here): `runbook.daily_run_started`, `runbook.stage_started`,
`runbook.stage_retrying`, `runbook.stage_finished`, `runbook.daily_run_finished`,
`runbook.daily_run_interrupted`, `runbook.daily_run_resume_queued`,
`runbook.safe_mode_entered`, `runbook.safe_mode_cleared`, `agent.message_sent`,
`workflow.created`, `workflow.<status>`, `workflow.task_interrupted`,
`workflow.task_lease_lost`, `workflow.job_scheduled`, `workflow.job_activated`,
`workflow.job_deactivated`, `workflow.job_fired`, `media.render_failed`,
`publishing.watchdog_reconcile`, `studio.registry_module_failed`,
`media.character_reference_registered`, `training.samples_added`,
`training.milestone_reached`.

**Events consumed** (read to decide): `runbook.daily_run_started` (run ↔ task),
`youtube.token_refresh_failed` / analytics refusals (preflight), `publishing.resolved_by_owner`,
`publishing.watchdog_reconcile`, `publishing.retry_reconciled` (watchdog), `runbook.film_state`,
`runbook.film_continued`, `media.render_failed`, the scene-model event, BRIEF_EVENT,
`media.scene_take_retired` / `media.scene_take_restored`, `story.episode_approved`,
`media.character_reference_registered`, `training.milestone_reached` (passes).

## Money paths

Nothing in this group buys media itself; every purchase happens in modules it dispatches
(`app.runbook.stages`, `app.media.*`) under the Owner's paid-step rule. What this group
decides is *whether that work starts*:

| Path | Gates in this group | Where |
|---|---|---|
| DAILY_RUN → `execute_daily_run` → stage runners (media buys stills, test shot, motion) | autonomy stop at claim and before every stage; safe-mode refusal; BLOCKED preflight (stop, unreadable vault, no model, no FFmpeg, low disk, refused upload token, no DAILY budget when buying unasked in PRODUCTION); dependency table; a HARD fault after paying is never retried | `runbook/services.py:1393-1398`, `313-317`, `1467-1523`; `worker.py:171-323` |
| Same-day re-attempt of the whole day (fresh runners: a new subject and film are possible) | only BLOCKED preflight, or FAILED + TRANSIENT + a production stage lost; after `daily_retry_seconds`, up to `daily_max_attempts`, not after a stop | `runbook/services.py:404-424`; `worker.py:290-317` |
| Resume of an interrupted day | completed stages replayed (no second purchase), the rest — media included — run for real; gated by stop, safe mode, no pending DAILY_RUN, `daily_max_attempts` | `passes/resume_interrupted_day.py:30-93`; `worker.py:212-239`; `runbook/services.py:1079-1109` |
| FILM_CONTINUE → `app.runbook.stages.continue_film` | queued by four passes (PRODUCTION only, `services.py:658-660`) and by FILM_BUSY deferrals (≤3, 600 s apart, not after a stop) | `worker.py:326-364`; passes `director_qc_review`, `ladder_retry`, `owner_choice_continuation`, `serial_unfilmed` |
| LLM tokens (priced models cost money) | weekly review, DIRECTOR_LOOP (and `POST /runbook/direct`), the mail round of every worker pass, MODEL_RESEARCH, FILM_SHEET_REPAIR (queued by the sheet scan), DIRECTOR_REPAIR probes; each run gated in `run_agent_task` by `may_run_agent` (daily token ceiling, exceeded USD budget) | `weekly.py:322`; `worker.py:385-417`, `445-457`, `757-760`; `agents/services.py:768-781` |
| DIRECTOR_REPAIR → `execute_repair` | the Policy Kernel is asked again when it runs | `worker.py:106-108`, `400-405`; `agents/repairs/desk.py:555-581` |
| Money released or collected, never spent | stale budget holds (`release_stale_reservations`, TTL 21 600 s), abandoned film purchase leases, studio-defect holds, RunPod unsent holds; SUBMITTED vendor tasks collected by GET only | `watchdog.py:869-875`, `882-934`, `568-596` |
| Uploads (not money, but irreversible) | the watchdog re-uploads FAILED_RETRYABLE rows through `execute_publication` (gate re-run, platform asked first); `licence_release` makes held uploads public | `watchdog.py:391-394`; `passes/licence_release.py:24-37` |
| Owner-triggered re-spend | `POST /tasks/{id}/retry` (a dead-lettered DAILY_RUN or FILM_CONTINUE), `POST /scheduler/jobs` (an active job of any type), `POST /scheduler/tick` (fire due jobs now), `POST /runbook/runs` | `workflows/router.py:123-160`; `runbook/router.py:80-93` |
| Budget increase asked by the weekly review | advisory; no code changes a budget | `weekly.py:404-422` |

## Owner touchpoints

| Touchpoint | Kind | Where | What the Owner decides |
|---|---|---|---|
| AUTONOMIE switch (`autonomy_stopped`) | setting / button | read at `runbook/services.py:377-393`, `workflows/services.py:365-377`, `813-815`, `watchdog.py:135-139`, `643-649` | stops the scheduler, claims, the watchdog, the passes and a running day at its next boundary |
| «Pornește rularea de azi» | button → `POST /runbook/runs` | `runbook/router.py:80-93` | a manual day (bypasses the clock's one-day rule) |
| Starting/stopping the daily clock | button → `POST /scheduler/jobs/{id}/active` | `workflows/services.py:748-788` | whether the studio begins a day on its own at 05:00 |
| Create a job / fire due jobs now | API → `POST /scheduler/jobs`, `POST /scheduler/tick` | `workflows/router.py:143-160` | |
| Retry a dead-letter task | API → `POST /tasks/{id}/retry` | `workflows/services.py:534-553` | re-run a task the studio refused to re-run (e.g. an INTERRUPTED day); a re-queued *scheduled* DAILY_RUN still meets the clock's one-day rule in the handler (`worker.py:240-268`: skipped while today has an INTERRUPTED/RUNNING or COMPLETED/PARTIAL run), a re-queued manual one does not |
| Weekly review now | button → `POST /runbook/weekly-review` | `runbook/router.py:95-145` | |
| Director pass now | button → `POST /runbook/direct` | `runbook/router.py:156-175` | |
| Close a Director decision with its outcome | form → `POST /runbook/decisions/{id}/review` | `runbook/router.py:207-217` | final word on what happened |
| Clear safe mode (with a note) | form → `POST /runbook/safe-mode/clear` | `runbook/services.py:708-742` | that the P0 was examined; autonomy stays off |
| Preflight lines | page checklist | `preflight.py:207-238` (places) | daily budget, model prices, token ceiling, vision model, character references (paid «Produ setul de referință»), channel binding, YouTube reconnect, Director's leave to approve episodes, disk, FFmpeg |
| Letters (ESCALATE) | inbox | `runbook/services.py:1007-1054`, `1767-1810`; `worker.py:691-718`; `watchdog.py:295-298` (publication handed over); letters written by `reclaim_abandoned_leases`, `collect_submitted_takes` (LOST) | day interrupted; day stopped at a stage; continuation interrupted; a publication to check by hand; a reclaimed film lease; lost vendor tasks |
| Cards | Decisions window | `propose_release_cards` (`watchdog.py:927-934`; it releases a hold by itself when a later round with the same keys proved nothing was queued, and proposes the card otherwise); the redo-cap card respected by `passes/director_qc_review.py:56-71`, `118-121` | release a RunPod-unsent hold; more paid redos / publish as is / close / wait |
| Budget request from the weekly review | Accountant's close (ESCALATE flagged `owner_attention`, but in the Director's inbox, not a `to_owner` letter) | `weekly.py:404-422`, `economy/accountant.py:1281-1306`, `1337-1342`; reaches the Owner's letters only through the Director's ESCALATE_TO_OWNER (`agents/director.py:420-430`) | whether to raise the budget |
| Training milestone | STATUS letter | `passes/training_set.py:191-208` | whether to pay for the LoRA training (a later card) |
| Character visual lock | bible setting | `passes/character_references.py:147-151` | locked characters get no free portrait |
| `sweep_failed_intermediates`, `daily_run_hour_local`, `worker_enabled`, thresholds | configuration | `config.py` lines above | |

## Oddities and gaps

1. **Workflow rows are inert.** Nothing outside `app.workflows.services`/`router` reads or
   moves `Workflow`/`WorkflowStep` (grep of `backend/app`); `POST /workflows/{id}/pause|resume|
   cancel` (`workflows/router.py:73-107`) changes a status that controls nothing;
   `PIPELINE_STAGES` (`workflows/services.py:35-53`) and the `NEEDS_REPAIR` state
   (`services.py:66`) have no producer. AR-14 removed the scheduler's Workflow rows
   (`services.py:88-91`, `858-863`) but kept the API.
2. **Two TaskQueueItem statuses are never written**: RUNNING and FAILED (`models.py:67`);
   `claim_task` writes CLAIMED, `fail_task` writes RETRYING or DEAD_LETTER
   (`workflows/services.py:385`, `523-528`). RUNNING is still listed in `LEASED_STATES` and
   `PENDING_STATES`.
3. **The scheduler's leader lease is set and cleared inside one transaction**
   (`workflows/services.py:820-917`): after commit `leader_token` is always None, so the
   "leader leasing" never excludes another scheduler; exclusion actually comes from
   `lock_for_write` and the per-slot idempotency key.
4. **Weekly review: a schema failure consumes the week.** `_already_reviewed_this_week` counts
   any SUCCEEDED/EMPTY_OUTPUT `WEEKLY_REVIEW` run (`weekly.py:257-268`), and a run whose JSON
   failed the schema is SUCCEEDED (`weekly.py:335`, `361-368`), so neither the clock nor the
   Owner's button gets a second review that week.
5. **Weekly digest is not a week.** `WINDOW_DAYS = 7` and `WEEKLY_SECONDS` are defined and
   unused (`weekly.py:44-45`); the digest takes the latest 50 published videos of all time
   (`weekly.py:91-99`) under a week label.
6. **`escalate_to_owner` is not routed.** The field exists in the schema and the prompt
   (`weekly.py:215-216`, `239-240`) but is only stored inside the Director's STATUS body
   (`weekly.py:424-425`); no code sends it to the Owner.
7. **"Nothing published" note repeats.** The STATUS note for an empty week is posted before
   the already-reviewed check (`weekly.py:281-301`), on every fire or press.
8. **Weekly speaker lookup is looser than elsewhere**: `_agent_for_role` accepts HIRED and
   CANDIDATE lifecycles (`weekly.py:252`) while the preflight counts only ACTIVE agents
   (`preflight.py:1423-1431`); the query has `.limit(1)` and no ORDER BY (`weekly.py:249-254`),
   so with two Director rows (e.g. an ACTIVE one and a CANDIDATE) which one speaks is not
   defined by the code. The same lookup picks the departments' recipients.
9. **Preflight comment and spec contradict the code on BLOCKING.** The comment says none of
   "the five checks below" is BLOCKING (`preflight.py:308-314`) and spec §1 says "None of the
   five is BLOCKING" (`docs/architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` §1), but
   `spending_budget` is BLOCKING in PRODUCTION when the paid rule buys unasked and no DAILY
   budget is active (`preflight.py:345-363`, MONEY-06/AR-07 2026-10-02). There are now six
   such functions (budget, price, token ceiling, vision, references, serial channel), and
   the spec's list does not include `agent_token_ceiling`, `credential_vault`, `disk_space`,
   `paid_media_rule` or `youtube_visibility` (only `disk_space` appears, in
   `docs/architecture/25_DEPLOYMENT_BACKUP_OPERATIONS.md:179`).
10. **A transient failure in `serial_queue` re-runs the whole day.** `serial_queue` is a
    PRODUCTION stage (`runbook/services.py:141-148`), so a TRANSIENT FAILED serial stage marks
    `production_lost` even when the factual short went through, and the worker queues a full
    `execute_daily_run` re-attempt with fresh runners (no replay) (`services.py:1713-1748`,
    `worker.py:290-317`). Whether the stages then refuse a second subject/film is decided in
    `app.runbook.stages`, outside this group.
11. **`interrupt_run` ignores its `cause` for the wording**: the stage reason and the run's
    `stop_reason` are always `CRASH_REASON` (`runbook/services.py:1132`, `1165`); its callers
    only pass INTERRUPTED_BY_CRASH today (`1206`, `1273-1275`).
12. **Hard-coded persona name** in deterministic letters: "— Sarah" (`runbook/services.py:1798`,
    `1808`), while the sender is looked up by role.
13. **`post_direct` runs agents inside the HTTP request** (`runbook/router.py:156-175`),
    unlike the day and the weekly review, which are queued so the browser does not time out
    (`runbook/services.py:1296-1300`); it has no `worker_enabled` check (the stop is checked
    inside `direct_company`).
14. **API jobs skip the dormant rule.** `POST /scheduler/jobs` creates an active job of any
    type with intervals down to 5 s (`workflows/services.py:595`, `schemas.py:79`), e.g. a
    DAILY_RUN job, while the seeded `daily_main` is dormant by decision. Owner-only.
15. **Vault opened by path convention in three places** (`watchdog.py:230`, `555`, `561`;
    `passes/vendor_plan_licence.py:24`) rather than `app.state.credential_vault`; comment
    says it is "the same file `create_app` opens".
16. **"After the start" means after the pass module was imported**: `STARTED_AT` is set at
    import (`passes/owner_choice_continuation.py:54`, `passes/serial_unfilmed.py:56`), i.e. at
    the first watchdog run that reaches the registered passes (`registered_passes` →
    `PASSES.load`, `passes/__init__.py:164-168`; not imported elsewhere). On a fresh database
    that is ~600 s after start-up (`first_run_at`, `main.py:497`); on an existing one the
    `watchdog` job keeps its persisted `next_run_at` (`ensure_scheduled_job` ignores
    `first_run_at` for an existing job, `workflows/services.py:710-719`), so the first fire is
    anywhere from the first worker pass to 600 s later — and later still if the studio is
    stopped (a stopped watchdog returns before loading the passes). Events between process
    start and that import count as "before the start".
17. **Static LLM path not taken**: `finish_approved_episodes` reaches `run_agent_task` in the
    call graph (6 hops) but passes no registry, so no model runs there
    (`passes/serial_unfilmed.py:127-129`).
18. **`execute_daily_run` hides its LLM work from static analysis**: stage runners are
    callables in a dict (`runbook/services.py:1364`, `1510`), so the inventory reports
    `llm_distance` None for the function that drives the day's agents.
19. **`ReplayRequest` schema is unused**: the socket validates with `replay_window`
    (`workflows/router.py:205-213`, `241-259`), not `schemas.py:108-111`.
20. **Duplicate query** in the preflight: `youtube_connected` and `connected_accounts` run the
    same CONNECTED query twice (`preflight.py:1448-1455`).
21. **`SCAN_FILM_SHEETS` is a dispatch-table entry nothing enqueues**: `worker_pass` calls it
    directly every pass (`worker.py:742-746`); no code enqueues the task type (grep).
22. **Decision log vs code on unknown publications**: "An unknown publication with no remote
    id is handed over at once" (entry `16_DECISION_LOG.md:1848`, sentence on line 1850,
    2026-09-17) is superseded in code
    by the title lookup after 15 min (`watchdog.py:351-358`, `387-388`, PUB-01/PUB-08
    2026-10-02).
23. **The watchdog can upload.** For FAILED_RETRYABLE publications it calls
    `execute_publication` (`watchdog.py:391-394`); the publishing gate is re-run there
    (`publishing/services.py:2099-2128`), but the pass is a publish action taken without a
    new Owner press.
24. **The weekly budget request does not reach the Owner's letters by code.** The Director's
    REQUEST_INFO goes to the Accountant (`weekly.py:404-422`); the Accountant's daily close
    (`reconcile_day`) lists it in an ESCALATE flagged `owner_attention` but posts it with
    `to_agent_id=None` and without `to_owner=True` (`economy/accountant.py:1286-1306`), unlike
    the Accountant's other letters (`:694`, `:740`, `:801`), so it is a Director-inbox item that
    `letters_for_owner` does not list (`agents/messages.py:208-211`, `232-240`); the request is
    nevertheless marked RESOLVED «transmisă Proprietarului» (`economy/accountant.py:1337-1342`).
    It becomes an Owner letter only if the Director's inbox review chooses ESCALATE_TO_OWNER
    and `owners_matter` agrees (`agents/director.py:114-122`, `370`, `420-430`).
25. **Not every event here is live.** `runbook.daily_run_finished`, `runbook.safe_mode_entered`
    / `_cleared`, `workflow.job_scheduled` / `_activated` / `_deactivated`,
    `runbook.daily_run_resume_queued`, the watchdog's `media.render_failed` and
    `publishing.watchdog_reconcile` are written with `app.services.append_event`, which writes
    no outbox row (`runbook/services.py:664`, `727`, `1814`; `workflows/services.py:605`, `777`;
    `passes/resume_interrupted_day.py:79`; `watchdog.py:187`, `284`), so they are not pushed
    live over the socket (the page sees them when it reads the event log or replays), while
    the stage events and `runbook.daily_run_interrupted` go through the outbox
    (`runbook/services.py:651-654`, `1145`, `1835`).
26. **`serial_unfilmed` writes in TEST too.** The PRODUCTION-only rule of the passes lives in
    `queue_film_continue`; `ready_for_filming` (a storyboard built from the episode's rows) runs
    before it in any environment (`passes/serial_unfilmed.py:126-134`).
27. **"Every writer takes the write lock" is not true of the whole module.** `create_workflow`,
    `transition_workflow` and `create_scheduled_job` write without `lock_for_write`
    (`workflows/services.py:160`, `222`, `589`), the pattern the module's own comments blame
    for several «database is locked» incidents (`:297-300`, `706-709`, `757-759`, `808-811`).
