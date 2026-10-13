# 17 — Application core: the app factory, settings, database, the Policy Kernel and the Owner's commands, snapshot and register, operations, backup, demo, security, logging, wording

> Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).
>
> Files (19, 9 142 lines):
> `backend/app/__init__.py` (1), `backend/app/backup.py` (722), `backend/app/config.py` (570),
> `backend/app/db.py` (105), `backend/app/demo.py` (576), `backend/app/events_feed.py` (1 377),
> `backend/app/goal.py` (292), `backend/app/local_session.py` (137), `backend/app/logging.py` (272),
> `backend/app/main.py` (1 000), `backend/app/maintenance.py` (192), `backend/app/models.py` (186),
> `backend/app/operations.py` (285), `backend/app/page_build.py` (107),
> `backend/app/registry_loader.py` (216), `backend/app/schemas.py` (165),
> `backend/app/security.py` (196), `backend/app/services.py` (2 109), `backend/app/wording.py` (634).
> 277 functions in the static inventory; the closures nested inside `main.create_app` (the
> lifespan, the background loops, the middleware and the route handlers) are documented as well.
> Verified adversarially on 2026-10-12 (line numbers, thresholds, decided-by labels and money
> gates re-read in the code; corrections are in place below). Of these files only
> `events_feed.py` changed between the two commits (the register's reading of the Director's
> rewrite reviews, and a sentence for her second look at a refusal of quality control).

## In one paragraph

This group is the frame every other subsystem runs inside, and the place where the Owner's
authority is written into code. `app.main.create_app` builds the FastAPI process: it refuses to
start on a database at the wrong migration revision, loads the credential vault and the provider
registry, starts up to five background tasks (the outbox dispatcher every second; the provider
catalogue refresher when `provider_catalog_refresh_enabled`; the Unreal Remote Control bridge
when `office_unreal_remote_url` is set; and, only in the process that holds the worker lock, the
RunPod GPU guard and the one worker that runs scheduled jobs and queued tasks,
`backend/app/main.py:354-613`), seeds up to eight scheduled jobs in that same process (the daily
run dormant, the others active; trends only when enabled, model research not in the demo), serves
the Owner-only API and the built page, and on shutdown tells the running day to stop at its next
boundary and forces any GPU off. `app.services` holds the **Policy Kernel** (`may_act`), the
single function every agent action, every paid media step, every GPU switch-on and every model
run (through `app.agents.services`) must pass, plus the Owner's versioned commands (autonomy
stop, environment, autonomy mode, paid-media rule, approval answers) and the approval objects
those commands and the kernel read and spend. Around that sit the snapshot and the live
register (`services.snapshot`, `services.read_events`, `app.events_feed`, `app.goal`), which turn
the event ledger into Romanian sentences for the page (the Director's verdicts on rewrites and her
second look at a refusal of quality control included, read from the record, or from her stored
answer as her review's bare schema reads it while no event names the run); the operations reading behind
`/health/ready` (`app.operations`); backup, restore and its guard (`app.backup`); the history
reset (`app.maintenance`); the simulated-vendor demo (`app.demo`); Owner authentication for HTTP,
WebSockets and the loopback auto-login (`app.security`, `app.local_session`); safe JSON logging
(`app.logging`); settings (`app.config`); the SQLite engine and migrations (`app.db`); the core
tables (`app.models`) and command schemas (`app.schemas`); and the code-to-Romanian dictionary
(`app.wording`). **None of the 277 functions here asks a language model anything**: the group is
entirely deterministic code, configuration and the Owner's recorded commands. Two functions reach
the model only indirectly (`create_app` through the worker's handlers and the stage runners;
`run_demo_day` through the daily run), and the Policy Kernel here is the gate every model call in
the studio passes before it is sent (`backend/app/agents/services.py:630`), right after
`_assert_policy_allows_run` has itself refused any run while the Owner's stop is on
(`backend/app/agents/services.py:618-621`).

## Why it exists

- **The Owner's authority must live outside any prompt.** ADR-016 «Owner Policy Kernel» and
  ADR-PHASE1-002 «Policy Kernel enforces all gates before every LLM run»
  (`docs/project/16_DECISION_LOG.md:779`, `:901`): hard guardrails are Python, not Director
  instructions. `may_act` (`backend/app/services.py:1410`) implements the authority hierarchy of
  `docs/architecture/31_GOVERNANCE_APPROVAL_POLICY.md` («Authority hierarchy», «Action risk tiers»)
  and the modes of `docs/architecture/51_AUTONOMY_MODE_SEMANTICS.md`; the risk table cites both
  documents (`backend/app/services.py:454-466`).
- **The Nepal film (2026-09-26/27).** Under AUTONOMOUS_CEO the studio bought two whole films
  (over 1 000 Runway credits) unasked (`docs/architecture/51_AUTONOMY_MODE_SEMANTICS.md`
  «Paid media steps»; comment at `backend/app/services.py:496-506`). Consequence: four paid-step
  actions of their own, the Owner's `paid_media_approval` rule read before the mode, a yes bound
  to the shooting sheet's `plan_hash` and spent once (`backend/app/services.py:1520-1595`,
  `backend/app/models.py:58-67`).
- **A missing budget must stop spending, not remove the limit** (ADR-DAILY-BUDGET-REQUIRED,
  `docs/project/16_DECISION_LOG.md:4102`: «measured on fakes, a fresh install with no budget let a
  $10,000 hold through») → `BLOCKED_NO_BUDGET` (`backend/app/services.py:1583-1595`).
- **A per-second GPU bill must be stoppable under STOP AUTONOMY** (ADR-GPU-OFF-ALWAYS,
  `docs/project/16_DECISION_LOG.md:4200`, amends spec 51) → `infra.gpu_off` is the kernel's first
  check (`backend/app/services.py:1479-1482`); ADR-GPU-ON-IN-STEP-ONLY (`:4198`) →
  `_gpu_on_verdict` (`backend/app/services.py:1352`).
- **A yes given in the evening expired before the 05:00 run used it** (ADR-FILM-CONTINUE,
  `docs/project/16_DECISION_LOG.md:4110`) → paid-media questions stand 48 h and the Owner's yes
  queues `FILM_CONTINUE` at once (`backend/app/services.py:645-689`, `:987-1001`).
- **One approval, one act, one thing.** A SUPERVISED day reused the first film's approval row for
  the second, dearer film (`backend/app/models.py:80-85`; decision log 2026-09-18 «A request is
  keyed by the action and the subject», `docs/project/16_DECISION_LOG.md:2679`).
- **A buyer's first start must not be able to spend** (ADR-MANUAL-DEFAULT,
  `docs/project/16_DECISION_LOG.md:4114`) → a new studio is MANUAL, stopped, TEST, with the daily
  job dormant (`backend/app/services.py:89-128`, `backend/app/main.py:483-486`).
- **Operations were invisible** (audit REL-04/REL-07/AR-08/AR-18, 2026-10-01/02): no backup code
  existed, `/health/ready` answered HEALTHY with a dead worker, a full disk and no FFmpeg
  (`backend/app/backup.py:1-31`, `backend/app/operations.py:1-14`;
  `docs/architecture/25_DEPLOYMENT_BACKUP_OPERATIONS.md` «As built (amended 2026-10-02)»).
- **The register spoke in codes.** The Owner, 2026-10-11/12: «Trebuie să fie mai pentru oameni,
  mai puțin cod …» and «LA CE SCENĂ LUCREAZĂ?!» (`backend/app/events_feed.py:1-38`;
  `docs/project/CHANGELOG.md` entries «The live register's words travel with the snapshot and the
  socket» and «The register speaks for people», 2026-10-11/12).
- **The register announced a refusal the Director never made** (review of a9f84ea, 2026-10-12):
  a MISSES was read from an answer the validator had refused, and «se poate cumpăra» would have
  been said while the Owner's «Oprește GPU acum» held → the verdict is read only from an answer
  her review's schema accepts (the bare `RewriteReview`, not the bound schema the studio accepts
  it with; oddity 18) and that was not asked again, and never promises a purchase
  (`backend/app/events_feed.py:817-823`, `:838`, `:1011-1016`). The Owner's «trece imaginile picate de la
  QC pe la Directoare …» → a sentence for her second look (`:592-595`).
- **«Putem urmări goal-ul de generare câte 2 pe fiecare canal, totul autonom?»** (the Owner,
  2026-10-12 14:00) → `app.goal` (`backend/app/goal.py:1-12`; `docs/project/CHANGELOG.md` «The day's
  goal, counted from the record, travels with the snapshot»).
- **The sign-in form** (the Owner, 2026-10-08: «Te rog sa elimini pagina de logare») → the key is
  handed only to a loopback page (ADR-LOCAL-AUTO-LOGIN, `docs/project/16_DECISION_LOG.md:292-327`;
  `backend/app/local_session.py:1-26`).
- **A key in a socket URL reached the service log** (SEC-02, ADR-NO-SOCKET-TOKEN,
  `docs/project/16_DECISION_LOG.md:4120`) → `refuse_key_in_url` and first-message auth
  (`backend/app/security.py:91-196`).
- **The Owner reads Romanian** (standing rule 2026-09-23) → `app.wording`, «where a code becomes a
  word, once» (`backend/app/wording.py:1-17`).
- **A sellable demo that cannot buy or publish** (SELL-03) → `app.demo` (`backend/app/demo.py:1-16`).

## Who decides here

| decision | decided by | where | rule / check / threshold |
|---|---|---|---|
| Whether any agent action may be *attempted* (the Policy Kernel) | CODE_RULE | `backend/app/services.py:1410-1633` | Order: `infra.gpu_off` → unclassified → STOP → T4 → safe mode → `infra.gpu_on` → paid-media rule → mode ceiling → SUPERVISED T3 asks → `BLOCKED_MODE`. Spec 31 hierarchy, spec 51. |
| Whether a model run may start at all (this group's part of it) | CODE_RULE (Owner's stop as input) | `backend/app/agents/services.py:618-621`, then `:630` → `backend/app/services.py:1491` | The Owner's stop is read first by `_assert_policy_allows_run` itself and refuses the run `BLOCKED_POLICY` (`AUTONOMY_STOPPED`) before `may_act` is asked. Then `may_act("agent.run","T1")`: `agent.run` is not in the table, so the caller's T1 is used; every mode and safe mode allow T1, so here only a missing policy row refuses (`BLOCKED_STOP`). The run's other gates (lifecycle, token and USD ceilings, provider health) are the agents subsystem's. |
| A risk tier for an action | CODE_RULE | `backend/app/services.py:467-525`, `:1459-1463` | Table wins; a caller's tier is only taken upward (`max(known, tier)`); an unknown action with no caller tier → `BLOCKED_UNCLASSIFIED`. |
| The autonomy stop | OWNER | `backend/app/main.py:952-957` → `backend/app/services.py:382-447` | Versioned (`expected_version`), idempotent by command id; one `autonomy.stopped` / `autonomy.stop_cleared` event and an OWNER_POLICY memory for every agent. |
| The autonomy mode (MANUAL / SUPERVISED / AUTONOMOUS_CEO) | OWNER | `backend/app/main.py:888-901` → `backend/app/services.py:1636-1735` | Versioned; a promotion is refused (409) while the stop is on or a safe-mode record is open; lowering is always allowed. |
| What each mode lets through | CODE_RULE | `backend/app/services.py:528` | `MODE_ALLOWS`: MANUAL T1, SUPERVISED T2, AUTONOMOUS_CEO T3; T4 in no list. |
| Safe mode ceiling | CODE_RULE | `backend/app/services.py:532`, `:1505-1510` | Any open `SafeModeRecord` → only T0/T1 pass. |
| The environment TEST / PRODUCTION (what a generation may cost) | OWNER | `backend/app/main.py:876-886` → `backend/app/services.py:244-313` | Versioned, idempotent, one `owner.environment_changed` event + memory. No stop/safe-mode check on this command. |
| The paid-media rule (EVERY_PAID_STEP / OVER_USD / MODE) | OWNER | `backend/app/main.py:903-919` → `backend/app/services.py:1816-1897` | Only `issued_by == "owner"`; any other issuer → `PaidMediaApprovalRefused` (403), nothing written. Threshold exactly with OVER_USD, `>= 0`, finite (`:1780-1786`). |
| Reading of an incomplete or unknown paid-media rule | CODE_RULE | `backend/app/services.py:1212-1231` | Fail closed → EVERY_PAID_STEP. |
| Whether a paid step of a film asks the Owner | CODE_RULE over OWNER settings | `backend/app/services.py:1520-1577` | EVERY_PAID_STEP asks in every mode; OVER_USD asks when `cost_usd` (the step's cap) is above the threshold or unknown; MODE defers to the mode. A step with cap exactly 0 under AUTONOMOUS_CEO is decided by the mode alone (`:1541-1544`). No `plan_hash` → `BLOCKED_NO_PLAN`. |
| An unasked paid step in PRODUCTION without a daily budget | CODE_RULE | `backend/app/services.py:1583-1595`, `:1234-1243` | `BLOCKED_NO_BUDGET` unless an active DAILY `SpendingBudget` exists; free (cap 0) steps exempt. |
| A T3 action under SUPERVISED | OWNER (via approval) | `backend/app/services.py:1600-1627` | Becomes one `ApprovalRequest`; with `ask_owner=False` nothing is written. |
| Answering an approval (APPROVED / REFUSED + note) | OWNER | `backend/app/main.py:933-950` → `backend/app/services.py:937-1028` | 404 unknown id; 409 already answered or expired; idempotent by command id; one `governance.approval_decided` event. |
| Whether an answer applies to what is being done now | CODE_RULE | `backend/app/services.py:715-728`, `:764-790` | Same action + subject, unexpired, unspent, and every key of the current context equal to the stored `proposed_diff`; newest answer wins. |
| Spending a yes | CODE_RULE | `backend/app/services.py:811-835`, `:1309-1311` | `consumed_at` set **before** the act; `governance.approval_consumed` event. A failed act does not get a second try on the same yes. |
| Re-using vs re-asking a question | CODE_RULE | `backend/app/services.py:731-761`, `:1053-1055` | Same action + subject + identical `proposed_diff` and unexpired → reused; otherwise the old row is marked EXPIRED and a new one raised. |
| How long a question / refusal / yes stands | CONFIG | `backend/app/config.py:401`, `:408`; `backend/app/services.py:539-581`, `:1057-1061` | `approval_expires_after_hours` 24 (1..168); paid-media questions `paid_media_approval_expires_hours` 48 (1..168). |
| Continuing a film at once after the Owner's yes | CODE_RULE | `backend/app/services.py:987-1001`, `:645-689` | APPROVED + paid-media question + PRODUCTION → one `FILM_CONTINUE` task (priority 4, `max_attempts` 1), idempotent per approval. |
| Closing questions about a replaced plan or a closed film | CODE_RULE (caller decides *that*) | `backend/app/services.py:1106-1162`, `:1165-1209` | Unanswered rows → EXPIRED with the caller's reason and `governance.approval_withdrawn`; answered rows left as history. |
| GPU off | CODE_RULE | `backend/app/services.py:1479-1482` | Always ALLOWED, first check, under STOP too (ADR-GPU-OFF-ALWAYS). |
| GPU on | CODE_RULE + OWNER (card) | `backend/app/services.py:1352-1407`, `:1339-1349` | Only inside a paid step (`step_action` in `PAID_MEDIA_STEPS`), the RunPod connection's `allow_infra_actions` true (the Owner's card), and the step itself allowed now, or his APPROVED answer for that action/film/plan named by `approval_id`, or his own press with a status in `OWNER_PRESS_PASSES`. Never asks, writes or spends. |
| Startup refusal on a wrong or missing schema | CODE_RULE | `backend/app/main.py:272-296`, `:200-214` | Revision ≠ migration head, or `owner_policy` row count ≠ 1 → `RuntimeError` in Romanian naming `scripts/bootstrap.py`. |
| Which process runs the worker | CODE_RULE | `backend/app/main.py:397-413` | OS lock per database (AR-17); a second process serves the page only. |
| Whether the daily production day runs on its own | OWNER (activation) | `backend/app/main.py:475-487` | `daily_main` seeded `active=False`; hour from CONFIG `daily_run_hour_local` 05:00. |
| Which other scheduled jobs exist and are active | CODE_RULE + CONFIG | `backend/app/main.py:491-575` | watchdog, weekly review, trends (if `trends_enabled`), model research (not in demo), model review, director loop, backup — all active from birth, all behind STOP (enforced in the scheduler, `backend/app/workflows/services.py:366`, `:376`, `:814`, not here). Intervals are code constants except `watchdog_interval_seconds`; a job is created once and an existing row keeps its interval and its active flag, only its local hour follows the setting (`backend/app/workflows/services.py:693-719`). |
| Taking back film purchase leases left by dead processes | CODE_RULE | `backend/app/main.py:418-429` | Only in the worker's process, at start, leases older than this process's start. |
| GPU guard at boot / tick / shutdown | CONFIG + CODE_RULE (+ EXTERNAL readings) | `backend/app/main.py:434-471`, `:641-657` | `runpod_guard_enabled` (default true); boot pass bounded 60 s; shutdown `force_off` bounded 20 s. |
| Owner authentication on the Owner's `/api/v1` routes | CODE_RULE | `backend/app/main.py:836`, `backend/app/security.py:60-88` | Bearer key compared in constant time; wrong keys counted per client; >20 in 60 s → 429 with Retry-After; the right key always passes; a missing key is 401 and not counted. Public by design: `/health/*`, `GET /api/v1/owner/local-session` (its own checks), the kept frame's GET (`backend/app/office/kept_frame.py:227`) and the YouTube OAuth callback (single-use state, `backend/app/main.py:984-986`). |
| Handing the key to the loopback page | CONFIG + CODE_RULE | `backend/app/local_session.py:74-106` | `local_auto_login` on; bound to loopback; peer loopback; no proxy header; exact Host; Origin/Sec-Fetch-Site same-origin; header `X-Studio-Local-Session: 1`. Else 404. |
| Socket authentication | CODE_RULE | `backend/app/security.py:143-186` | Key as first message within 5 s; ≤16 pending sockets (1013 past it); any `token` query parameter → closed 1008 before accept. |
| Whether `/health/ready` answers 503 | CODE_RULE | `backend/app/main.py:783-826`, `backend/app/operations.py:231-285` | 503 when the database is unreadable or any operations problem exists (worker STALE, disk LOW, FFmpeg/FFprobe missing, backup STALE/MISSING, or `OPERATIONS_UNREADABLE` when the reading itself raises, `main.py:811-815`); credentials UNREADABLE (or UNKNOWN when the vault check raises) → DEGRADED but 200. |
| Worker STALE | CODE_RULE | `backend/app/operations.py:160-198` | No pass for 3 × `worker_interval_seconds` and no task with a live lease. |
| Telling the Owner the worker is failing | CODE_RULE | `backend/app/operations.py:81-128` | Exactly the 3rd consecutive failed pass → one event + one ESCALATE letter; later failures only counted. |
| Making the daily backup | CONFIG + CODE_RULE | `backend/app/main.py:566-575`, `backend/app/backup.py:540-612` | 03:30 local; online copy + `integrity_check`; prune rows only after a good copy; failure → event + one letter a day. |
| Which backups are kept | CONFIG + CODE_RULE | `backend/app/backup.py:366-406`; `:564-565` | Newest copy of each of the `backup_keep_daily` (14) most recent days that have one, newest per ISO week for the `backup_keep_weekly` (4) weeks before them, newest `KEEP_SPECIAL` = 5 of each special tag (constant); copies without a manifest never touched. A copy is judged only against the other copies, never the clock (`:376-378`). The pre-migration and pre-restore copies run this pass with the defaults 14/4, not the settings (`:420`, `:657`, `:217-218`). |
| Restoring a backup | OWNER (runs `scripts/restore.py`) + CODE_RULE | `backend/app/backup.py:627-690` | Refused while the studio answers on its port, or when sha256/integrity fail; current DB kept as `prerestaurare`. |
| Restore guard after a restore | CODE_RULE | `backend/app/services.py:321-379` | Stop on, environment TEST, `daily_main` inactive, one versioned write + `owner.restore_guard_applied`. The Owner re-enables from the page. |
| Deleting the studio's history | OWNER (runs `scripts/reset_history.py`) | `backend/app/maintenance.py:84-182` | `HISTORY_TABLES` deleted, ledger cut to cited events, immutability triggers dropped and recreated in the same transaction. |
| Demo: which writes are refused | CODE_RULE | `backend/app/demo.py:60-79`, `:504-510`; `backend/app/main.py:706-727` | Any method but GET/HEAD/OPTIONS to publishing, YouTube, economy, settings, providers, environment/paid-media rule, sheet steps/redo/adopt, reference sets, factual source retrieval and allowed hosts, research, analytics trends refresh and ingest → 403 (only when the Owner's key is presented; otherwise the route's own 401). |
| Demo: refusing the real database and the network | CODE_RULE | `backend/app/demo.py:104-112`, `:527-558` | `data/studio.db` or no file → `DemoRefused`; any non-loopback socket connect → `DemoNetworkRefused`. |
| Demo: which "LLM" answers | CODE_RULE (scripted stand-in) | `backend/app/demo.py:185-393`, `:396-404` | `DemoModel` registered for every provider; answers chosen by keywords in the prompt. |
| Page older than its sources | CODE_RULE | `backend/app/page_build.py:94-107` | SHA-256 of `frontend/index.html` + `frontend/src/**` vs `dist/build.json`; mtime fallback. |
| Where a film stands in the day's goal and whose wait it is | CODE_RULE | `backend/app/goal.py:155-181` | Open `OwnerDecision` card, or an `OWNER_DECIDES`/`NEEDS_REFERENCE` refusal → blocked, Owner; WAITING on a ladder refusal or a FAILED QC report → in work, Director; HELD → blocked, studio; PASSED/READY → in work, studio; else in work, Director when the reason names «Directoar», otherwise studio. Target 2 per channel (hard-coded). |
| Which employee an event is attributed to | CODE_RULE | `backend/app/events_feed.py:319-334`, `:74-107` | Payload `agent_id`/`from_agent_id`, then the aggregate (for `agent.*` events), then `decided_by`/`director_repair`, then the event-kind prefix table (`media.director_` → Director, which covers `media.director_second_look`). |
| Whether a Director's rewrite review verdict is shown in the register | LLM_CHECKED_BY_CODE (display only) | `backend/app/events_feed.py:726-766`, `:797-809`, `:817-863`, `:866-893`; `backend/app/media/scene_rewrite.py:374-381` | The record first: a verdict a brief names (`review_verdict`, each round of `review_attempts`) or a stored rewrite names (`review`, plus each review in `review.refused` said as MISSES) is shown as written; a review run an event names without a verdict is said without one. Only for a review run no event names yet: her `output_text` is parsed with `app.agents.identity.read_structured` against `scene_rewrite.RewriteReview`, the verdict being the schema's own property (MISSES while a serious finding is untreated or a lesson is broken), and the run is skipped when the next `director_rewrite_review` run of the same employee and correlation carries a `+again`/`+think` template suffix. No control effect. |
| How the register words the Director's second look at a refusal of quality control | CODE_RULE (wording of a verdict `second_look` recorded) | `backend/app/events_feed.py:589-620`, `:1180-1181` | `verdict` CONFIRMED/OVERTURNED × `redo` → four sentences with the scene and the film; any other verdict (UNAVAILABLE) → «… nu s-a putut uita …: refuzul controlului rămâne», no bubble. `severity` is not read. Display only. |
| What is never written to a log | CODE_RULE | `backend/app/logging.py:119-134`, `:153-166`, `:64-79` | Secret-named keys blanked; other text sanitised and cut at 2 000 chars; tracebacks as class + frames only; `token=` values blanked in uvicorn lines. |
| Settings validity | CODE_RULE (validators over CONFIG values) | `backend/app/config.py:18-42`, `:520-570` | Owner token ≥ 32 chars (hard-coded); research hosts bare lowercase public DNS names (no localhost, no non-global IP); IANA timezone; non-empty city; `media_root`/`backup_dir` relative paths resolved against the repo root; numeric bounds per `Field(ge, le)`. |
| Database engine | CODE_RULE | `backend/app/db.py:40-79` | SQLite file only (no in-memory, no PostgreSQL); WAL; FKs on; busy_timeout 30 s; deferred BEGIN. |
| Migrations | OWNER (runs `scripts/bootstrap.py`) + CODE_RULE | `backend/app/db.py:82-105`; `backend/app/backup.py:412-420` | FKs off for the migration connection, `foreign_key_check` after; a `premigrare` copy before migrating a non-head database. |

## LLM involvement

**No LLM call site in these 19 files.** Static analysis lists none, and reading the code confirms
it: no function here calls `run_agent_task`, `structured_run`, `run_with_strategy`,
`reviews._run` or `prompt_agent._run`, and no function here writes a prompt. Calls the static
graph could miss were checked by reading: the start-up's `seed_owner_decisions` /
`refresh_owner_decisions` (whose producers load through `PackageLoader`; no gateway name in
`backend/app/decisions/`), `refresh_due_catalogs` (vendor model lists, no generation),
`run_gpu_guard` / `force_off`, `run_unreal_bridge`, `reclaim_abandoned_leases`, and the letters
and memories written here (`post_message`, `remember`) reach no gateway; the worker's handlers
and the stage runners are callbacks the graph resolves through `create_app` (below). The register's
`_review_verdicts` calls `app.agents.identity.read_structured` (`backend/app/events_feed.py:834`,
`:856`), the parser `structured_run` itself uses (`backend/app/agents/structured.py:141`), on an
answer already stored; it sends nothing.

How this group is nevertheless central to the model's role:

| function | what it has to do with the LLM | path / call site reached |
|---|---|---|
| `app.services.may_act` (`backend/app/services.py:1410`) | The gate every model run passes: `run_agent_task` calls `_assert_policy_allows_run` (`backend/app/agents/services.py:831`), which first reads the Owner's stop itself and refuses `BLOCKED_POLICY` (`:618-621`), then asks `may_act(session, "agent.run", "T1", requester=agent.id)` before the provider adapter is called (`:630`). A refusal raises `PolicyKernelError` and the run is recorded BLOCKED. Effective refusal from `may_act` for `agent.run`: only a missing policy row (`BLOCKED_STOP`), because the stop was already caught and T1 passes every mode and safe mode. | Gateway itself: `app.agents.services.run_agent_task` (`backend/app/agents/services.py:733`). |
| `app.main.create_app` (`backend/app/main.py:249`, 3 hops) | Builds the worker handlers and stage runners and starts the worker loop that runs them. | e.g. `build_task_handlers` → `app.runbook.weekly.execute_weekly_review` → `run_agent_task`; `build_stage_runners` → `_selection` → `app.agents.director.choose_topic` → `run_agent_task`; `build_stage_runners` → `_post_run` → `app.agents.director.director_review` / `app.economy.accountant.reconcile_day` → `structured_run`; `build_task_handlers` → `app.agents.command.direct_company` → `_choose` → `run_with_strategy`; `worker_pass` → `app.agents.mail.correspondence_round` → `answer_mail` → `structured_run` (callgraph). |
| `app.demo.run_demo_day` (`backend/app/demo.py:491`, 4 hops) | Runs one whole daily run on the demo database. | `build_stage_runners` → every stage's call sites, e.g. `_research_and_verification` → `app.factual.agent_pipeline.agent_extract_claims` / `agent_verify_claim` → `run_agent_task`; `_script_and_storyboard` → `agent_write_script` → `run_agent_task` and `app.media.prompt_agent.write_shot_prompts` → `prompt_agent._run`; `_publish` → `_publish_one` → `app.agents.editorial.editorial_review` → `structured_run`. In the demo every one of them is answered by `DemoModel`, not a model. |
| `app.demo.DemoModel` (`backend/app/demo.py:185-393`) | A scripted stand-in registered as the adapter of every provider in the demo (`register_demo_models`, `:396`). It picks an answer by keywords in the prompt (`'"assign_to_role"' and '"decisions"'` → the Director's decision JSON; `'"shots": ['` or `ending_frame` → a shot plan; `evidence_quote` → SUPPORTED claim; `claim_type`; `core_message` → a fixed four-scene script whose every scene cites the first UUID (sorted) found anywhere in the prompt; `hook_strength`; `continuity_rules`; `pronunciation`; `hold_reasons`; `notes_for`; `assign_to_role` alone → the Director's decision again; else prose «DEMO: nimic de raportat.»). Reports 12 prompt / 48 completion tokens and `cost_vr` None (`:204-206`; `GenerateResult`, `backend/app/providers/base.py:28-33`). | Not an LLM; deterministic code. Its prose fallback is what a caller sees as an unparseable answer. |
| `app.main.register_seeded_ollama` (`backend/app/main.py:224-246`) | Gives each seeded Ollama provider that has no adapter a live `OllamaProvider` with `price_lookup(engine, "ollama")`, so a generation on a model the Owner's price table prices is costed from its tokens (the comment records 391 runs on the live copy with `cost_vr` NULL that the day's budget never saw); a model with no price still costs None, never zero (`:237-240`). | No model call; adapter registration. |
| `app.events_feed._review_verdicts` (`backend/app/events_feed.py:817-863`) with `_asked_again` (`:866-893`) | For a finished `director_rewrite_review` run that no brief, stored rewrite or second look names yet (`named` false, `:829`), parses her stored `output_text` with `read_structured` against `app.media.scene_rewrite.RewriteReview` (lazy imports, `:833-840`; on ImportError nothing is shown) and takes the schema's `verdict` property (computed by code from her per-finding `treated`/`severity` and `broken_lessons`, `backend/app/media/scene_rewrite.py:374-381`) and `reason_ro`, to say «Am refuzat rescrierea scenei 4: nu tratează constatarea» in the register before the brief event records it. A run is skipped when the next review run of the same employee and correlation carries `structured_run`'s retry suffix `+again`/`+think` (`_RETRY_SUFFIXES`, `:215`; `backend/app/agents/structured.py:56-57`). Decided-by LLM_CHECKED_BY_CODE, trust INFORMATIONAL: nothing reads it back for control. The bare schema is not the bound one the review is accepted with (oddity 18). | No model call; displays an answer the agents subsystem already received. |
| `app.events_feed._second_look_words` (`backend/app/events_feed.py:589-620`) | Words the Director's second look (`media.director_second_look`, written by `app.media.second_look._record`, `backend/app/media/second_look.py:515-569`): whether QC's refusal was right and whether the scene is redone. Trust INFORMATIONAL. | No model call; displays the verdict of call site `second_look._look` as recorded. |
| `app.config` (`backend/app/config.py:15`, `:419`, `:425`, `:434`) | Model-related settings: `agent_daily_token_budget` (0 = none), `director_token_multiplier` (2), `editorial_rounds` (10), `DEFAULT_EDITORIAL_ROUNDS`. | Read by the agents subsystem. |

Money: none of the functions above spends money by itself; the indirect paths through
`create_app` reach purchases only through `may_act` in the media modules (see the money paths in
the structured summary and «Hard rules and limits»).

## Hard rules and limits

### Policy Kernel and approvals (`backend/app/services.py`)

| rule | value | where |
|---|---|---|
| Risk tiers | T0: `analytics.read`, `provider.health_read`, `research.search_public`, `memory.read`, `infra.gpu_off`; T1: `idea.create`, `script.draft`, `storyboard.draft`, `task.reprioritise`, `benchmark.run`; T2: `agent.change_model`, `agent.change_prompt`, `agent.hire`, `agent.suspend`, `office.room_draft`, `research.fetch_page`, `media.paid_generation`, `media.stills_purchase`, `media.character_reference_set`, `infra.gpu_on`; T3: `publishing.public_publish`, `media.paid_generation_over_threshold`, `agent.fire`, `provider.activate`, `story.public_world_change`, `media.test_shot`, `media.motion_purchase`, `media.scene_redo`; T4: `budget.change_hard_limit`, `policy.change_kernel`, `credential.reveal`, `credential.rotate`, `legal.accept_terms`, `audit.disable` | `:467-525` |
| Mode ceilings | MANUAL T1, SUPERVISED T2, AUTONOMOUS_CEO T3 | `:528` |
| Safe-mode ceiling | T1 | `:532` |
| Tier comparison | string comparison (`"T0" < … < "T4"`), caller tier only raised | `:1459-1463`, `:1505`, `:1597` |
| Paid steps of a film | `media.stills_purchase` → `stills`, `media.test_shot` → `test_shot`, `media.motion_purchase` → `motion`, `media.scene_redo` → `scene_redo` | `:606-611` |
| Strictest paid-media rule | `EVERY_PAID_STEP` (first of `PAID_MEDIA_APPROVALS`) | `:614`, `backend/app/models.py:32` |
| Narration bound to the sheet | step `assemble` + `plan_hash` makes a `media.paid_generation*` question a paid-media one | `:624`, `:630-642` |
| Approval expiry | 24 h general, 48 h paid media; floor 1 h; fallbacks when settings cannot be built: 24 / 48 | `:536`, `:555`, `:539-581` |
| FILM_CONTINUE task | `task_type="FILM_CONTINUE"`, priority 4, `max_attempts` 1, backoff 60 s, idempotency key `film-continue-<subject>-<approval id>`, PRODUCTION only | `:627`, `:645-689`, `:991` |
| Approval result states | PENDING → APPROVED / REFUSED (Owner) or EXPIRED (studio); `consumed_at` set once | `backend/app/models.py:90-92`, `backend/app/services.py:811-835` |
| Unknown cost | `None`, shown «necunoscut», never 0; paid steps shown as «plafon N USD» | `:700`, `:884-889` |
| Statuses `may_act` returns | `ALLOWED`, `BLOCKED_UNCLASSIFIED`, `BLOCKED_STOP`, `BLOCKED_OWNER_ONLY`, `BLOCKED_SAFE_MODE`, `BLOCKED_NOT_IN_STEP`, `BLOCKED_INFRA_DISABLED`, `BLOCKED_NO_PLAN`, `NEEDS_APPROVAL`, `REFUSED_BY_OWNER`, `BLOCKED_NO_BUDGET`, `BLOCKED_MODE` | `:1465-1633` |
| New studio | `NEW_STUDIO_AUTONOMY_MODE = "MANUAL"`, `autonomy_stopped=True`, environment from DB default TEST | `:94`, `:118-128`, `backend/app/models.py:47` |
| Restore guard | stop on, TEST, jobs `("daily_main",)` inactive, event `owner.restore_guard_applied` | `:317-318`, `:321-379` |

### Process and schedule (`backend/app/main.py`)

| rule | value | where |
|---|---|---|
| Migration head | read from the Alembic chain once per process | `:177-192` |
| Outbox dispatch | every 1 s | `:337-354` |
| Vault health cache for the public probe | 30 s | `:129`, `:796-802` |
| GPU guard | boot pass timeout 60 s; loop interval from `guard_intervals`/`next_interval`, 60 s on error; shutdown `force_off` timeout 20 s | `:436-471`, `:641-657` |
| `daily_main` | 86 400 s, CATCH_UP, at `daily_run_hour_local` (05:00), **dormant** | `:475-487` |
| `watchdog` | `watchdog_interval_seconds` (600), SKIP, active | `:491-499` |
| `weekly_review` | 7 days, CATCH_UP, first after 1 h, active | `:504-512` |
| `trends_daily` | 86 400 s, CATCH_UP, first after 120 s, only if `trends_enabled` | `:516-525` |
| `model_research_weekly` | 7 days, CATCH_UP, first after 2 h, not in demo | `:527-536` |
| `model_review_daily` | 86 400 s, SKIP, first after 900 s | `:541-549` |
| `director_loop` | 21 600 s (four a day), SKIP, first after 1 800 s | `:553-561` |
| `backup_daily` | 86 400 s, CATCH_UP, at `backup_hour_local` (03:30) | `:566-575` |
| Job rows | created once, only in the worker's process; an existing row keeps its interval and active flag, only `run_at_local`/`timezone` follow the settings | `:413`, `backend/app/workflows/services.py:693-719` |
| Worker loop | one pass every `worker_interval_seconds` (30) | `:581-611` |
| `/events` | `after ≥ 0`, `limit` 1..300 (default 50), `since` ≤ 40 chars ISO | `:861-874` |
| Static cache | page files: hashed `assets/*-XXXXXXXX.(js|css|…)` → `public, max-age=31536000, immutable`, other page files `no-cache`; `/api/*` and any response without its own Cache-Control → `no-store` | `:136-147`, `:170-174`, `:746-747` |
| Response headers | `X-Correlation-ID`, `nosniff`, `Referrer-Policy: no-referrer`, CSP (self, YouTube thumbnails, `blob:` media, youtube-nocookie frames) | `:740-756` |
| Docs / OpenAPI | disabled | `:673-675` |
| Hosts | `TrustedHostMiddleware(allowed_hosts)` default `["localhost","127.0.0.1"]` | `:1000`, `backend/app/config.py:57` |

### Security (`backend/app/security.py`, `backend/app/local_session.py`)

| rule | value | where |
|---|---|---|
| Wrong-key throttle | 20 per 60 s per client address, 1 024 addresses remembered | `security.py:25-28`, `:44-57` |
| Socket auth | first message `{"type":"auth","token":…}` within 5 s, ≤ 4 096 chars, ≤ 16 pending (1013), else 1008 | `security.py:100-107`, `:143-170` |
| Key in socket URL | closed 1008 before accept | `security.py:173-186` |
| Local hand-over | loopback binds `127.0.0.1`/`localhost`/`::1`; peers `127.0.0.1`/`::1`/`::ffff:127.0.0.1`; 13 proxy headers refused; header `x-studio-local-session: 1`; refusal = 404 | `local_session.py:37-64`, `:74-106` |

### Operations, backup, logging

| rule | value | where |
|---|---|---|
| Worker STALE | 3 intervals without a pass and no live lease | `backend/app/operations.py:33`, `:160-198` |
| Worker failing letter | exactly at 3 consecutive failures | `backend/app/operations.py:35`, `:81-93` |
| Backup STALE / MISSING | `backup_max_age_hours` 36 | `backend/app/backup.py:426-476`, `backend/app/config.py:124` |
| Retention | 14 daily, 4 weekly, 5 per special tag (`premigrare`, `prerestaurare`) | `backend/app/backup.py:66-67`, `:366-406` |
| Backup name | `studio-YYYYMMDDTHHMMSSZ[-n][-tag].db` (UTC) | `backend/app/backup.py:62-64` |
| Online copy busy wait | sqlite3 `timeout=30` | `backend/app/backup.py:157` |
| Pruning | COMPLETED housekeeping tasks (`WATCHDOG`, `BACKUP`, `MODEL_REVIEW`, `TRENDS_REFRESH`) older than 30 days; PUBLISHED outbox rows older than 7 days; events never | `backend/app/backup.py:78`, `:479-513`, `backend/app/config.py:127-128` |
| SQLite | WAL, `foreign_keys=ON`, `busy_timeout=30000`, connect timeout 10 s, deferred `BEGIN` | `backend/app/db.py:51-77` |
| Logs | JSON lines; file `studio.log` rotated at 10 MiB × 10; text values ≤ 2 000 chars; ≤ 30 frames; `[ascuns]` for secrets | `backend/app/logging.py:36-46`, `backend/app/config.py:72-73` |
| Register sentence lengths | `WORDS_MAX` 220, `BUBBLE_MAX` 64; correlation look-back 12 h | `backend/app/events_feed.py:292-293`, `:226` |
| Register: a review answer asked again | a run followed (by `started_at`, then id) by a `director_rewrite_review` run of the same employee and correlation whose template ends `+again` or `+think` is not read | `backend/app/events_feed.py:215`, `:866-893` |
| Register: reasons quoted | second look 110 chars, refused rewrite 120 chars | `backend/app/events_feed.py:599`, `:1022` |
| Goal | 2 per channel; films of the last 7 days | `backend/app/goal.py:26-28` |

### Settings that bound money and retries (`backend/app/config.py`; read elsewhere)

| setting | default (bounds) | line |
|---|---|---|
| `motion_budget_usd` | 12.0 | `:258` |
| `film_budget_usd` | None → motion budget + six-scene stills cap (15.24 USD) | `:269` |
| `film_purchase_lease_seconds` | 10 800 (600..86 400) | `:275` |
| `paid_step_balance_margin` | 1.15 (1.0..3.0) | `:286` |
| `max_paid_attempts_per_scene` | 3 (1..20) | `:294` |
| `film_wait_days` | 3 (1..60) | `:303` |
| `film_max_paid_redos_per_scene` / `film_max_paid_redos` | 5 (0..5) / 20 (0..20) | `:314-315` |
| `test_motion_scenes` | 2 | `:330` |
| `test_max_cost_per_generation_usd` / `_per_second_usd` | 0.60 / 0.12 | `:335-336` |
| `auto_benchmark_new_models` / `max_benchmark_budget_usd` | False / 1.50 | `:360-363` |
| `reservation_ttl_seconds` | 21 600 | `:380` |
| `paid_generation_approval_threshold_usd` | 5.0 | `:392` |
| `agent_daily_token_budget` | 0 = no ceiling | `:419` |
| `director_token_multiplier` | 2 (1..4) | `:425` |
| `editorial_rounds` | 10 (1..20) | `:434` |
| `research_candidates_per_day` / `research_pages_per_topic` | 4 / 4 (1..12) | `:441-442` |
| `min_free_gb` | 20.0 | `:109` |
| `daily_max_attempts` / `daily_retry_seconds` | 3 / 1 800 | `:470-471` |
| `stage_retry_attempts` / `stage_retry_backoff_seconds` | 3 / 20 | `:477-478` |
| `provider_retry_attempts` / `provider_retry_max_seconds` | 3 / 30 | `:487-488` |
| `render_stuck_after_seconds` / `reconcile_max_attempts` | 10 800 / 3 | `:502-503` |
| `publish_stuck_after_seconds` | 3 600 | `:183` |
| `provider_catalog_refresh_seconds` / `_retry_seconds` / `_poll_seconds` | 21 600 / 900 / 60 | `:505-507` |
| `runpod_guard_enabled` | True | `:511` |
| `production_priority` | `premium` | `:251` |

## Modules

### `app` — backend/app/__init__.py (1 line)

Package docstring only: «AMN-AI (Autonomous Machine Nexus — Artificial Intelligence) application.»
No functions.

### `app.main` — backend/app/main.py (1 000 lines)

The FastAPI application factory. Everything that runs inside the studio process is wired here:
logging, the engine, the vault, the provider registry, the stage runners, the background loops,
the scheduled jobs, the middleware, the Owner's policy routes and every subsystem's router.

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `static_cache_control` | 145 | Cache header for a built page file: immutable for content-hashed assets, `no-cache` for the rest. | Until 2026-09-24 every response said `no-store` and every visit re-downloaded 8.7 MB of art (`:151-157`). | CODE_RULE |
| `PageFiles.__call__` | 159 | Closes WebSockets on unknown paths with 1008 instead of letting StaticFiles assert. | A stranger's socket knocking caused 500s and tracebacks (Owner's console, 2026-10-02, `:160-163`). | CODE_RULE |
| `PageFiles.get_response` | 170 | Sets the cache header on 200/304 page files. | Same as above. | CODE_RULE |
| `expected_revision` | 177 | Reads the Alembic chain's single head (cached). | It was a literal every migration had to remember to change (`:181-182`). | CODE_RULE |
| `database_revision` | 200 | `SELECT version_num FROM alembic_version`; a missing table → Romanian RuntimeError naming `scripts/bootstrap.py`. | A raw OperationalError said nothing to a buyer (`:203-205`). | CODE_RULE |
| `register_seeded_ollama` | 224 | Registers an `OllamaProvider` with `price_lookup(engine,"ollama")` for each seeded Ollama provider lacking an adapter. | Without it health checks failed «no adapter registered», and 391 runs carried no cost (`:225-240`). | CODE_RULE |
| `create_app` | 249 | Builds and returns the ASGI app (752 lines incl. closures below). Demo settings applied first; `TrustedHostMiddleware` wraps the result. | The single composition root. | CODE_RULE / CONFIG |
| ↳ `lifespan` | 267 | Startup: revision/policy checks, vault health, registry load, Ollama adapter, Owner-decision seed + refresh (failure logged, start continues), demo seams, `clear_shutdown`, the outbox dispatcher, the catalogue refresher (if enabled), the Unreal bridge (if configured); then, only in the process holding the worker lock: lease reclaim, GPU guard (boot pass + loop), the up-to-eight jobs, the worker. Shutdown: `request_shutdown`, await the tasks, `force_off` GPU (20 s), release worker lock, close demo, `clear_shutdown`, dispose engine. | REL-06 (page must come up even if the vault is unreadable, `:297-299`), REL-10 (the day ends INTERRUPTED instead of being killed mid-purchase, `:619-622`), AR-17, ADR-GPU-GUARD. | CODE_RULE |
| ↳ `dispatch_outbox` | 337 | Every second: `dispatch_pending_outbox` (DB part in a thread), errors logged. | REL-12: nobody hears of an event whose row did not commit (`:340-341`). | CODE_RULE |
| ↳ `refresh_provider_catalogs` | 358 | Only when `provider_catalog_refresh_enabled` (off in the demo): every `provider_catalog_poll_seconds` (60), `refresh_due_catalogs` in a thread (network to vendors; due per `provider_catalog_refresh_seconds` / `_retry_seconds`). | Model catalogues follow the vendors. | CONFIG |
| ↳ `guard_gpu` | 448 | Loop: compute next interval, wait, `run_gpu_guard(reason="TICK")`. | ADR-GPU-GUARD: a GPU on with no paid step open is switched off; runs under STOP (`:430-433`). | CODE_RULE + EXTERNAL |
| ↳ `run_worker` | 581 | Loop: `record_pass_start`, `worker_pass` in a thread, `record_pass_end`; on exception log and `record_pass_failure`. | The studio runs without the browser (`:389-392`); REL-07 counting. | CODE_RULE |
| ↳ `demo_refused` | 706 | In demo, returns the refusal for a write only when the request carries the Owner's key; otherwise the route answers 401 as usual. | SELL-03; the refusal is told only to the Owner (`:707-708`). | CODE_RULE |
| ↳ `request_context` (middleware) | 719 | Correlation id, demo refusal (403), exception → 500 with correlation id (class only logged), security headers, `no-store` on `/api/*`, CSP, one `request_complete` log line. | «Never log arbitrary request bodies, authorization headers, URLs or DB error strings» (`:729`). | CODE_RULE |
| ↳ `validation_error` | 768 | 422 with type/loc/msg only (no input echo). | Avoid echoing request input. | CODE_RULE |
| ↳ `live` — GET `/health/live` | 780 | Always `HEALTHY`. Public. | Liveness probe. | CODE_RULE |
| ↳ `ready` — GET `/health/ready` | 784 | DB check (503 DEGRADED if unreadable); vault health cached 30 s (UNREADABLE → DEGRADED, still 200); `public_health` of the operations reading; 503 when any problem. Public, codes only. | REL-06, REL-07, AR-18 (`:790-810`). | CODE_RULE |
| ↳ `operations_now` | 828 | `operations_reading` with the process's own worker record. | Shared by `/health/ready` and the snapshot. | CODE_RULE |
| ↳ `get_snapshot` — GET `/api/v1/snapshot` | 839 | `services.snapshot` + operations + location + demo flag + `page_build`. Owner key. | The page's first and periodic read. | CODE_RULE |
| ↳ `get_events` — GET `/api/v1/events` | 861 | Paged record from `after`, or from the first event at/after `since`. Owner key. | Replay of a day in one read (migration 0047). | CODE_RULE |
| ↳ `set_environment` — POST `/api/v1/owner/environment` | 877 | `change_environment`; 409 on conflict. | «never from a query parameter a page could set» (`:880-881`). | OWNER |
| ↳ `set_autonomy_mode` — POST `/api/v1/owner/autonomy-mode` | 889 | `change_autonomy_mode`; 409 on conflict or `AutonomyRefused`. | Spec 51. | OWNER |
| ↳ `set_paid_media_approval` — POST `/api/v1/owner/paid-media-approval` | 904 | `change_paid_media_approval(issued_by="owner")`; 403 refused issuer, 409 stale. | Issuer fixed by the authenticated route, never by the body (`:909-912`). | OWNER |
| ↳ `list_owner_approvals` — GET `/api/v1/owner/approvals` | 922 | `pending_approvals`: PENDING and unexpired, newest first. | Spec 31 «What waiting looks like». | CODE_RULE |
| ↳ `decide_owner_approval` — POST `/api/v1/owner/approvals/decision` | 934 | `decide_approval`; 404 missing, 409 closed/conflict. | Spec 31 «how it is answered». | OWNER |
| ↳ `set_autonomy_stop` — POST `/api/v1/owner/autonomy-stop` | 953 | `change_stop`; 409 on conflict. | The Owner's global stop. | OWNER |

Helpers: `_utc_now_plus` (`:217`, ISO timestamp N seconds ahead for `first_run_at`).

Routers mounted (`:959-996`): settings, agents, providers, workflows, tasks, scheduler (+ the
`/api/v1/ws` gateway and the office stream relay), office, kept frame, factual, media, publishing,
analytics, economy, YouTube (+ the public OAuth callback, protected by single-use state, `:984-986`),
workforce, story, runbook, decisions, RunPod, local session. The `/api/v1` router of this file
carries `Depends(require_owner)` (`:836`); `/health/*` and the local-session route are public.
The built page is mounted at `/` only when `frontend/dist` exists (`:998-999`).

Data read/written: `alembic_version`, `owner_policy` (startup checks), `provider_record`,
`scheduled_job` (via `ensure_scheduled_job`), `app.state.*` (settings, engine, operations,
page_root, media root, worker flag, vault, registry, connection manager, stage runners). Files:
`<database>.credentials.key` (vault), the worker lock beside the database, `frontend/dist`.
External calls started here: vendor catalogue refresh (network), RunPod GPU guard and shutdown
`force_off` (network, can only stop spending), Unreal Remote Control bridge when configured.

### `app.services` — backend/app/services.py (2 109 lines)

The studio's governance kernel and the Owner's command layer: the event appender, bootstrap,
command idempotency, the policy view, the five Owner commands, the restore guard, the risk table,
`may_act`, the approval object's whole life, the GPU switch rules, and the snapshot and paged
record the page reads.

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `utc_now` | 58 | ISO UTC timestamp. | One clock format for every row (189 callers). | CODE_RULE |
| `append_event` | 62 | Adds one `DomainEvent` (uuid, UTC stamp, visibility OWNER, schema 1, no causation) and flushes. | The ledger's single writer (213 callers). | CODE_RULE |
| `bootstrap_studio` | 97 | Creates studio row 1, policy row (version 1, stopped), mode (MANUAL by default) where the column exists, `studio.created` + `office.room_created` events and the first room 24×16; a second call does nothing. | ADR-MANUAL-DEFAULT; «A real empty initial world, not simulated staff» (`:149`). | CODE_RULE |
| `command_hash` | 164 | SHA-256 of a command payload. | Replay vs repeat detection (11 external callers). | CODE_RULE |
| `recall_command` | 169 | The stored answer of a command id; a different payload under the same id → `CommandConflict(COMMAND_REUSED)`. | Safe retries (`:172-175`). | CODE_RULE |
| `remember_command` | 184 | Writes the `CommandRecord` in the same transaction. | Idempotency. | CODE_RULE |
| `policy_view` | 199 | `PolicyView` from the policy row; `public_publish_enabled` = any channel public; None environment → TEST, None mode → MANUAL, paid rule via `paid_media_policy`. | «anything incomplete or unknown shows as the strictest» (`:226`). | CODE_RULE |
| `studio_environment` | 232 | TEST/PRODUCTION from the policy row; missing row → TEST. | «Every selection that spends money asks this, and nothing else may answer it» (`:235-237`; 24 callers). | OWNER (stored) |
| `change_environment` | 244 | The Owner's environment command (write lock, idempotency, version check, event, memory, command record). | The environment decides what a shot may cost (`:247-248`). | OWNER |
| `apply_restore_guard` | 321 | Stop on, TEST, `daily_main` inactive, version + 1, `owner.restore_guard_applied` with the previous state. | Spec 25 «Restore guard»: a restored past must not buy or publish (`:324-330`). | CODE_RULE |
| `change_stop` | 382 | The Owner's autonomy stop command (same shape). | Global stop. | OWNER |
| `_hours_setting` | 539 | Builds `Settings()` and reads an hour setting (≥ 1), falling back to a default. | ADR-GOVERNANCE-006 (`docs/project/16_DECISION_LOG.md:2955`). | CONFIG |
| `paid_media_approval_expires_hours` | 558 | 48 h default. | AR-05. | CONFIG |
| `approval_expires_after_hours` | 568 | 24 h default. | Spec 31 «Expiry». | CONFIG |
| `is_paid_media_question` | 630 | A `PAID_MEDIA_STEPS` action, or narration bound to a sheet (`step == "assemble"` + `plan_hash`). | Decides the 48 h expiry and the continuation. | CODE_RULE |
| `queue_film_continue` | 645 | Queues one `FILM_CONTINUE` task in the caller's transaction (PRODUCTION only; idempotent by key). | A6/AR-05: his yes continues the film the same day (`:651-653`; 11 external callers). | CODE_RULE |
| `action_words` | 692 | Romanian label of an action, else its code. | Owner-language sentences. | CODE_RULE |
| `_open_approval` | 731 | Live PENDING request for action + subject + identical diff; others marked EXPIRED. | The second film reused the first film's row (`:736-746`). | CODE_RULE |
| `_answered_approval` | 764 | The Owner's newest unexpired, unspent APPROVED/REFUSED answer whose diff matches the context. | Spec 31's three standing conditions (`:769-773`). | CODE_RULE |
| `approval_answers` | 793 | Read-only dict of the Owner's answers by id. | The Director reads what came of her questions without touching the row (`:795-797`). | CODE_RULE |
| `_spend_approval` | 811 | `consumed_at` now + `governance.approval_consumed`. | One approval authorises one act, spent before the act (`:812-819`). | CODE_RULE |
| `approval_context` | 848 | For a paid question: step, first 12 chars of `plan_hash`, storyboard. | PAGE-03: the page opens the sheet rather than approving in one click. | CODE_RULE |
| `film_titles` | 864 | Storyboard titles for paid questions. | Page display. | CODE_RULE |
| `approval_view` | 877 | `ApprovalView` with `cost_label` («necunoscut», «plafon N USD», «N USD»). | MONEY-08: a paid step is asked with its cap. | CODE_RULE |
| `pending_approvals` | 913 | PENDING + unexpired, newest first; writes nothing. | Spec 31; read by decisions, accountant, letters and stages too. | CODE_RULE |
| `decide_approval` | 937 | The Owner's answer: refuses missing (404), answered or expired (409); sets result, approver `owner`, note, `decided_at`; queues `FILM_CONTINUE` for an APPROVED paid-media question; event `governance.approval_decided`; command record. No agent memory written (`:946-948`). | Spec 31 «how it is answered»; ADR-FILM-CONTINUE. | OWNER |
| `request_approval` | 1031 | Reuses an open request or creates one (expiry 24/48 h) with `governance.approval_requested`. | «a queue of duplicates would bury the one decision» (`:1045-1046`). | CODE_RULE |
| `withdraw_superseded_approvals` | 1106 | Closes unanswered questions about an older `plan_hash` of the same action and subject (keeps `keep` and rows with a note). | A yes is spent only for the plan it names (`:1118-1119`). | CODE_RULE (caller decides the supersession) |
| `withdraw_subject_approvals` | 1165 | Closes every PENDING question about a closed film. | Nothing about a closed subject can be bought (`:1170-1171`). | CODE_RULE (caller decides the closure) |
| `paid_media_policy` | 1212 | (rule, threshold) with fail-closed reading. | «the one place a wrong reading would spend money» (`:1215-1218`). | CODE_RULE |
| `has_active_daily_budget` | 1234 | Any active DAILY `SpendingBudget`. | MONEY-06. | OWNER (budget) read by CODE_RULE |
| `buys_paid_media_unasked` | 1246 | Whether rule + mode let the cheapest paid step through unasked. | Shared with the preflight's budget line (`:1250`). | CODE_RULE |
| `_paid_media_context` | 1265 | The sheet context with `step` and `cap_credits`; None without a non-empty `plan_hash` or with another step. | «an answer bound to nothing would match every plan» (`:1268-1269`). | CODE_RULE |
| `_ask_or_spend` | 1284 | The one reader/spender of the Owner's answer: REFUSED → `REFUSED_BY_OWNER`; APPROVED → spend, ALLOWED; none → `request_approval`, NEEDS_APPROVAL. With `ask_owner=False` reads and writes nothing. | Spec 31 «It is spent once». | CODE_RULE |
| `_runpod_infra_allowed` | 1339 | The RunPod integration's `allow_infra_actions` is `true`/`1`/`yes`. | The Owner's card «Agenții pot porni singuri GPU-ul RunPod …». | OWNER (card) |
| `_gpu_on_verdict` | 1352 | See «Who decides»: step, card, inner `may_act(..., ask_owner=False)`, or a named APPROVED answer, or the Owner's press. | ADR-GPU-ON-IN-STEP-ONLY. | CODE_RULE |
| `may_act` | 1410 | The Policy Kernel (224 lines). Returns `{action, tier, mode, allowed, status, reason, approval_id}`. | ADR-016, spec 31, spec 51, the Nepal amendment, MONEY-06, ADR-GPU-*. | CODE_RULE |
| `change_autonomy_mode` | 1636 | The Owner's mode command; promotion refused under stop or open safe mode, naming the unverifiable acceptance criteria and burn-in (`:1673-1688`); event with direction; memory `MODE_MEMORY`. | Spec 51 «Transition to higher autonomy» / «Lowering autonomy». | OWNER |
| `PaidMediaApprovalCommand._threshold_only_with_over_usd` | 1783 | Validator: threshold iff OVER_USD. | Same shape the DB accepts (migration 0048). | CODE_RULE |
| `change_paid_media_approval` | 1816 | The Owner's paid-media command; non-owner issuer refused before any write. | «an agent cannot loosen the gate it is waiting at» (`:1824-1825`). | OWNER |
| `last_task_per_agent` | 1900 | Each employee's newest `AgentRun` (one grouped query over migration 0046's index). | Name tags in the HQ (W12); the snapshot is read every five seconds (`:1906-1907`). | CODE_RULE |
| `studio_location` | 1943 | Latitude, longitude, city, holiday country from settings. | SELL-08. | CONFIG |
| `snapshot` | 1959 | The page's state: cursor, operations, studio, demo banner, maturity, policy, rooms, last 20 events enriched, last tasks, goal. | The page's single read. | CODE_RULE |
| `read_instant` | 2057 | Parses an instant to UTC ISO (naive = UTC). | `/events?since=`. | CODE_RULE |
| `read_events` | 2069 | Page of events after `max(after, ledger_floor-1)`, optionally from the first stamp ≥ `since` (`sequence + 0` to use the timestamp index), enriched. | Replay; history before a reset is not read back (`:2082`). | CODE_RULE |

Helpers: `_safe_mode_is_open` (`:703`, open `SafeModeRecord` in the caller's transaction),
`_context_matches` (`:715`, every context key equals the stored diff; empty context matches),
`_owner_refusal_reason` (`:838`, «Proprietarul a refuzat «…».»), `_usd_words` (`:1259`, «12,24»),
`_goal_of` (`:2051`, lazy import of `goal_snapshot`).

Constants also defined here: `CommandConflict`, `AutonomyRefused`, `ApprovalClosed`,
`ApprovalMissing` (`:42-55`); `APPROVAL_ACTION_LABELS` (`:586-601`); `MODE_MEMORY` (`:1739-1753`)
and `PAID_MEDIA_MEMORY` (`:1799-1813`), the standing sentences written to every agent's memory
when the Owner moves the mode or the rule; `DEMO_BANNER_RO` (`:1956`); `PaidMediaApprovalResult`
(`:1789`).

Data read/written: `owner_policy` (every Owner command takes the write lock with a no-op UPDATE
first, e.g. `:255`, `:390`, `:957`, `:1658`, `:1841`), `command_record`, `domain_event`,
`owner_approval_request`, `room`, `studio`, `task_queue` (`FILM_CONTINUE`), `scheduled_job`
(restore guard), `safe_mode_record`, `spending_budget`, `integration` (RunPod card), `agent_run`,
`channel_record`, `storyboard`, `memory_record` (via `app.agents.memory.remember`). Events
emitted: `studio.created`, `office.room_created`, `owner.environment_changed`, `autonomy.stopped`,
`autonomy.stop_cleared`, `owner.autonomy_mode_changed`, `owner.paid_media_approval_changed`,
`owner.restore_guard_applied`, `governance.approval_requested`, `governance.approval_decided`,
`governance.approval_consumed`, `governance.approval_withdrawn`. No external calls.

### `app.config` — backend/app/config.py (570 lines)

`Settings` (pydantic-settings, prefix `STUDIO_`, `.env` at the repo root, extra keys ignored,
input hidden in errors). Every field carries a comment that dates the incident or Owner rule
behind its default (e.g. `motion_budget_usd` from «twenty-one dollars went out» `:253-258`;
`film_max_paid_redos*` from «a film is redone until QC passes and only money stops it»
`:305-315`; `editorial_rounds` from «vreau să încerce de 10 ori» `:427-434`; `trends_geo` moved to
the audience's countries on 2026-10-11 `:130-142`). The full numeric list is in «Hard rules and
limits».

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `validate_public_host` | 18 | Bare lowercase public DNS name; refuses scheme/port/path/wildcard, `localhost`, non-global IPs. | Half of the SSRF boundary; «an allowlist an agent could add to would not be an allowlist» (`:85-92`). Also used for hosts the Owner adds (`app.research.service`). | CODE_RULE |
| `Settings.trends_geos` | 145 | Upper-cased unique country codes. | Trends feed per audience country. | CONFIG |
| `Settings.youtube_credentials_present` | 514 | True only with the full OAuth triple. | «never simulate a publishing integration» (`:78-79`). | CONFIG |
| `Settings.strong_token` | 522 | Owner token ≥ 32 chars (threshold in code), else «Run scripts/bootstrap.py». | Owner key strength. | CODE_RULE (over CONFIG `STUDIO_OWNER_TOKEN`) |
| `Settings.plain_hostnames` | 529 | Validates `research_allowed_hosts` with `validate_public_host`. | SSRF boundary. | CODE_RULE (over CONFIG) |
| `Settings.studio_relative` | 542 | `media_root` and `backup_dir` only: empty → None; relative → under the repo root. | A relative folder is the studio's, not the process's cwd (`:543-544`). | CODE_RULE (over CONFIG) |
| `Settings.city_words` / `country_code` / `valid_timezone` | 552 / 560 / 565 | Non-empty city; upper-case country; IANA zone. | SELL-08. | CODE_RULE (over CONFIG) |

Constants: `ROOT` (repo root, `:10`), `DEFAULT_DIRECTOR_TOKEN_MULTIPLIER = 2` (`:11`),
`DEFAULT_EDITORIAL_ROUNDS = 10` (`:15`). No data access, no external calls.

### `app.db` — backend/app/db.py (105 lines)

The SQLite engine and migrations.

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `lock_for_write` | 15 | `UPDATE owner_policy SET version = version WHERE id = 1` as a transaction's first statement. | A deferred transaction that read then wrote failed instantly with «database is locked»; `BEGIN IMMEDIATE` deadlocked nested sessions for 32.8 s (`:16-35`). 150 callers. | CODE_RULE |
| `create_db_engine` | 40 | File-backed SQLite only; resolves relative paths under the repo root; WAL, FKs, busy_timeout 30 s, deferred `BEGIN`. | «Foundation supports SQLite» (`:43`); a four-minute stage died on a 10 s timeout (`:60-64`). | CODE_RULE |
| `migrate` | 82 | Alembic upgrade with FKs off on that connection, then `foreign_key_check`, FKs back on. | Batch migrations failed on studios with bound YouTube channels (`:86-91`). | CODE_RULE |

### `app.models` — backend/app/models.py (186 lines)

Core tables: `Studio` (id = 1), `OwnerPolicy` (id = 1; `version`, `autonomy_stopped`,
`environment` server default TEST, `autonomy_mode` server default AUTONOMOUS_CEO,
`paid_media_approval` server default EVERY_PAID_STEP, `paid_media_approval_over_usd`),
`ApprovalRequest` (`owner_approval_request`: action, subject, tier T0–T4, requester, evidence,
`proposed_diff`, nullable `cost_usd`, reversible, expiry, approver, result
PENDING/APPROVED/REFUSED/EXPIRED, note, `decided_at`, `consumed_at`; indexes `ix_approval_open`,
`ix_approval_subject`), `DomainEvent` (autoincrement `sequence`, unique `event_id`, index on
timestamp), `CommandRecord`, `Room`. `PAID_MEDIA_APPROVALS` (`:32`). It imports every other
package's models to register them on `Base.metadata` (`:172-186`). No functions.

### `app.schemas` — backend/app/schemas.py (165 lines)

Command and view schemas, all commands `extra="forbid"`, `schema_version: Literal[1]`, UUID
`command_id`: `PolicyCommand` (stop, `expected_version`, strict bool), `EnvironmentCommand`,
`AutonomyModeCommand`, `ApprovalDecisionCommand` (no `expected_version` by design: the closed
state guards the only failure, `:102-111`; note ≤ 500 chars). Views: `PolicyView` (with four
`Literal[False]` flags: `external_payments_enabled`, `autonomous_firing_enabled`,
`provider_auto_switch_enabled`, `world_generation_enabled`, `:73-76`), `EventView`,
`PolicyResult`, `ApprovalView`, `ApprovalDecisionResult`. `AutonomyMode` and `AUTONOMY_RANK`
(`:10-13`). No functions.

### `app.backup` — backend/app/backup.py (722 lines)

Backup, retention, the copy before a migration, the restore and its guard, operational pruning
(REL-04, AR-08, SELL-20, REL-15; spec 25).

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `database_file` | 106 | DB path from an engine/URL/path, relative → repo root. | Shared path rule. | CODE_RULE |
| `backup_folder` | 115 | `STUDIO_BACKUP_DIR`, else `backups` beside the DB. | Owner's choice of disk. | CONFIG |
| `key_file` | 124 | `<db>.credentials.key`. | The wrapped vault key. | CODE_RULE |
| `database_revision_of` | 145 | Read-only revision of a DB file. | Decides whether a pre-migration copy is needed. | CODE_RULE |
| `make_backup` | 210 | Online copy to `.partial`, `integrity_check == ok`, rename, manifest (sha256, bytes, revision, key copy with DPAPI note, optional media listing), then retention. Raises `BackupError` (Romanian) and leaves nothing half-made. | Spec 25 «Backup». | CODE_RULE |
| `verify_backup` | 299 | Manifest present and readable, sha256 matches, integrity ok. | A restore must not take a changed or broken copy. | CODE_RULE |
| `list_backups` | 342 | Copies matching `BACKUP_NAME`, newest first. | Retention, status, script. | CODE_RULE |
| `apply_retention` | 366 | Keep newest of 14 days, of 4 weeks before them, 5 per special tag; only copies with a manifest are counted or deleted. | The 2026-09-12 copy made by another script is never touched (`:374-375`). | CONFIG + CODE_RULE |
| `backup_before_migration` | 412 | `premigrare` copy when the DB exists and is not at the head. | REL-04: start migrated in place with no copy. | CODE_RULE |
| `backup_status` | 426 | OK / STALE (> `backup_max_age_hours`) / MISSING (none and the studio older than that) / NONE_YET. | `/health/ready` and the page banner. | CONFIG |
| `prune_operational_rows` | 479 | Deletes COMPLETED housekeeping tasks > 30 days and PUBLISHED outbox rows > 7 days; events never. | REL-15. | CONFIG |
| `run_backup_job` | 540 | The daily task: copy, prune after a good copy, `operations.backup_made`; on failure `operations.backup_failed` + `_tell_backup_failed`; returns COMPLETED/FAILED. | «Never a network call, never a cost» (`:548-549`). | CODE_RULE |
| `studio_answers` | 618 | TCP connect to the studio's address (1 s). | Restore refuses while the studio runs. | EXTERNAL (local socket) |
| `restore_backup` | 627 | Refuse if running or the copy fails verification; keep current DB as `prerestaurare`; online copy back; optional key restore; `apply_restore_guard`; list credentials to re-enter. | Spec 25 «Restore guard». | OWNER initiates; CODE_RULE |
| `credentials_to_reenter` | 693 | Connections whose keys the vault cannot read, plus every YouTube connection when the key itself is unusable, with the Settings tab. | A DPAPI key does not open on another account/machine (`:17-19`). | CODE_RULE |
| `BackupError.__init__` / `RestoreRefused.__init__` | 89 / 98 | Carry `reason_ro`. | Owner-language errors. | — |

Helpers: `_sha256` (`:129`), `_revision` (`:137`), `_online_copy` (`:154`, `sqlite3.backup` with
30 s timeout), `_integrity` (`:168`), `_media_listing` (`:174`, path/size/mtime of every media
file, never bytes), `_name` (`:199`), `_parsed` (`:334`), `_remove` (`:355`, the copy, its
manifest, media listing and key copy), `_tell_backup_failed` (`:516`, one ESCALATE letter to the
Owner from the Director's identity, subject per day so a still-open letter is that day's).

Data: reads the SQLite file directly (sqlite3), writes `data/backups` (or `STUDIO_BACKUP_DIR`),
`key/`, manifests; deletes rows in `task_queue` and `outbox_record`; events
`operations.backup_made`, `operations.backup_failed`; letter `backup_failed`. No network, no
money.

### `app.operations` — backend/app/operations.py (285 lines)

The process's own worker record and the reading behind `/health/ready` and the page banner
(REL-07, AR-18; spec 25 «Monitoring»).

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `new_operations` | 54 | The in-memory worker record on `app.state.operations`. | REL-07. | — |
| `record_pass_start` / `record_pass_end` | 67 / 72 | Mark a pass; a finished pass resets the failure streak. | Same. | CODE_RULE |
| `record_pass_failure` | 81 | Count a failure; at exactly 3 → `_tell_worker_failing`. | «Three failed passes in a row are one event and one letter» (`:13`). | CODE_RULE |
| `_tell_worker_failing` | 96 | Event `operations.worker_failing` + ESCALATE letter to the Owner. | While it fails no job starts (`:121-123`). | CODE_RULE |
| `worker_reading` | 160 | OFF / ELSEWHERE / STARTING / OK / BUSY / STALE (see «Hard rules»). | A long pass with a live lease is BUSY, not dead. | CODE_RULE |
| `toolchain_reading` | 201 | FFmpeg / FFprobe found or MISSING. | Films cannot be rendered or measured without them. | EXTERNAL (local binaries) |
| `operations_reading` | 231 | Worker + disk (`app.media.disk.disk_reading`) + toolchain + backup → problems with Romanian reasons, `banner_ro`. | The page's «Lucrătorul nu a mai lucrat de 14 minute». | CODE_RULE |
| `public_health` | 275 | Statuses and codes only for the public probe. | No paths or sentences to strangers. | CODE_RULE |

Helpers: `_now` (`:40`), `_parse` (`:44`), `_minutes` (`:134`, Romanian minute counts),
`_live_task` (`:141`, CLAIMED/RUNNING task with an unexpired lease), `_studio_created_at` (`:223`).

### `app.maintenance` — backend/app/maintenance.py (192 lines)

«Start over»: delete what the agents produced, keep what the Owner configured.

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `reset_history` | 84 | FKs off; drop the `*_no_delete` triggers; delete every `HISTORY_TABLES` table; delete events not cited by a configuration row's `event_id`; agents IDLE; scheduled jobs' last run and leader cleared; recreate the triggers; FK check; empty the media folder; one `studio.history_reset` event. | Owner's «start over» (`docs/project/CHANGELOG.md` «Starting over»). Run only by `scripts/reset_history.py:84`. | OWNER |
| `ledger_floor` | 185 | Sequence of the latest `studio.history_reset`. | `read_events` does not read before the reset (`backend/app/services.py:2083`). | CODE_RULE |

Helper: `_tables_with_event_id` (`:74`). `HISTORY_TABLES` (`:30-71`) includes
`owner_approval_request` and `command_record`: «a yes about a film that no longer exists is an
authority nothing should still be able to spend» (`:63-66`).

### `app.demo` — backend/app/demo.py (576 lines)

The demo (SELL-03): the real runbook, kernel, gates, renderer and QC on a separate database, with
every vendor seam replaced, a scripted model, a network belt and refused write routes.

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `guard_demo_database` | 104 | Refuse `data/studio.db` or no file. | Never touch the real studio. | CODE_RULE |
| `demo_vendor_fakes` | 134 | Replacement for each of the ten `DEMO_VENDOR_SEAMS` (images, voice, render plan, motion, YouTube, analytics, balances, search, sheet wiring, reference check); asserts the two lists agree. | Kept equal to the end-to-end test's fakes (`:39-40`). | CODE_RULE |
| `demo_vendors` | 168 | Context manager patching then restoring the seams. | Lifetime of the demo process. | CODE_RULE |
| `DemoModel` (`__init__`, `health_check`, `list_models`, `generate`) | 185-206 | Stand-in model; `generate` records the prompt and returns a scripted answer with 12/48 tokens and no cost. | «It is not intelligent and does not pretend to be» (`:191-192`). | CODE_RULE |
| `DemoModel._answer` | 208 | Keyword dispatch to a schema-shaped answer (Director decision schema first: ADR-DEMO-DIRECTOR-SCHEMA, `docs/project/16_DECISION_LOG.md:412`). | Callers validate the shape; identifiers come from the prompt. | CODE_RULE |
| `DemoModel._script` | 291 | Fixed four-scene script about `DEMO_FACT`; every scene cites `claim_ids[:1]`, the first of the sorted UUIDs found anywhere in the prompt (not necessarily a claim's). | The verifier refuses invented ids. | CODE_RULE |
| `DemoModel._shots` | 331 | One shot per `scene_index` in the prompt, four rotating framings. | The shot-plan lint refuses identical framing (`:333-334`). | CODE_RULE |
| `DemoModel._director` | 366 | ACKNOWLEDGE every inbox id found inside `<untrusted_source_evidence>` (≤ 20). | Director review schema. | CODE_RULE |
| `register_demo_models` / `demo_registry` | 396 / 407 | `DemoModel` for every provider id. | All employees answer from the stand-in. | CODE_RULE |
| `prepare_demo_studio` | 419 | Seeds workforce, bibles, channels; once: stop released, AUTONOMOUS_CEO, TEST, all `ModelRecord.is_available = True` with a DEMO note, one topic, one source snapshot, `demo.prepared`. Provider rows stay NOT_CONFIGURED. | «nothing here claims that a real model answered» (`:451-452`). | CODE_RULE |
| `run_demo_day` | 491 | `execute_daily_run` with fresh stage runners on the demo DB. | Demo day (`scripts/demo_daily_run.py:77`). | CODE_RULE (reaches LLM call sites, answered by `DemoModel`) |
| `demo_refusal` | 504 | Romanian refusal for a non-GET matching `DEMO_REFUSED_PATHS`. | Publishing, payment, connection and network routes answer 403. | CODE_RULE |
| `no_outbound_network` | 528 | Patches `socket.connect`/`connect_ex` to refuse non-loopback addresses. | A belt beside the seams (`:531-533`). | CODE_RULE |
| `demo_settings` | 561 | Copy of settings with trends, catalogue refresh, weather, stream, Unreal, research hosts and YouTube credentials off. | Every switch that would reach the network. | CODE_RULE |

Helpers: `_database_file` (`:94`), `_no_motion` (`:126`), `_no_analytics` (`:130`),
`_local_address` (`:517`); class `DemoVoice` (`:118`).

### `app.events_feed` — backend/app/events_feed.py (1 377 lines)

The live register in human sentences: `enrich` adds `words_ro`, `actor`, `film_title` and
`bubble_ro` to each event dict served by `services.read_events`, `services.snapshot` and the
outbox/socket (`app.workflows.publisher`). Read-only, Romanian, no simulation: «every sentence is
read from the event's payload and the rows it names» (`:17-18`). Since the evening of 2026-10-12
the Director's verdict on a rewrite is read from her answer only when her review's schema accepts
it (the bare `RewriteReview`, `:838`; oddity 18) and nothing asked her again, it never promises a
purchase, and her second look at a refusal of quality control has its sentence (`:35-38`). All of
this landed in commit `68fa0b4`, before `second_look.py` itself (`20abffd`).

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `enrich` | 1352 | Builds the actor table, storyboard titles, run places (failure logged, never fatal), then sets the four fields per event (sentences ≤ 220, bubbles ≤ 64). | The Owner's register rule 2026-10-11/12. | CODE_RULE |
| `_Actors.__init__` / `for_event` | 304 / 319 | Employees by id and first per role; attribution by payload, aggregate, `decided_by`, then `_ROLE_BY_PREFIX`. | «poate punem și imaginea celui care lucrează» (`:7`). | CODE_RULE |
| `_words` | 1040 | 310-line dispatch over 43 event kinds (takes, stills, motion, sheets, rewrites, Director QC decisions, the Director's second looks, editorial notes, clip QC, film QC, renders, paid redos, RunPod sessions, money reservations, vendor costs, runs, states, jobs, serial) to (sentence, bubble); unknown kinds via `_fallback` (never ids or hashes). | 2026-10-12: raw rows like «run paused — endpoint_id: …» (`:20-26`). | CODE_RULE |
| `_judged_words` | 491 | Editorial judgement note: score/50, weakest criteria, shipped/brief. | `editorial.judged` (2026-10-12). | CODE_RULE |
| `_take_words` | 525 | A take's QUOTED/SUBMITTED/PAID/APPROVED/REJECTED/REFUSED/LOST sentence. | `media.scene_take_recorded`. | CODE_RULE |
| `_brief_words` / `_rewrite_words` / `_repair_words` | 567 / 623 / 649 | The Director's scene brief, a prompt rewrite, a failed film's repair. | Director loop visibility. | CODE_RULE |
| `_second_look_words` | 589 | `media.director_second_look` (dispatched at `:1180-1181`): what she looked at (`_LOOK_KIND_RO`: still → «imaginea», shot → «clipul», film_scene → «cadrele»), the scene and the film, her reason cut at 110 chars; OVERTURNED without redo «refuzul controlului e greșit — se acceptă, nu se reface», CONFIRMED with redo «refuzul e corect — se reface», CONFIRMED without redo «… defectul e mic — se acceptă», OVERTURNED with redo «… dar scena tot se reface»; any other verdict (UNAVAILABLE) «nu s-a putut uita …: refuzul controlului rămâne» with no bubble. `severity` is not read. | The Owner, 2026-10-12: «trece imaginile picate de la QC pe la Directoare și să decidă dacă au picat corect sau nu și dacă trebuie refăcute» (`:592-595`). | CODE_RULE (wording of a recorded LLM verdict) |
| `_run_places` | 924 | For runs of one-scene/one-film tasks (`director_second_look` included through `_SCENE_TASK_RO`, `:201`, which `_run_id` filters on, `:698`): scene from the run summary, film from briefs/correlations/summary title; each place carries a `named` flag (`:961`). | «LA CE SCENĂ LUCREAZĂ?!» (`:28-33`). | CODE_RULE |
| `_runs_named` | 726 | The runs an event names: a `media.director_scene_brief` (brief and rewrite runs; each round of `review_attempts`, his rewrite and her review with its verdict; the final review with `review_verdict`), a `media.prompts_rewritten` (his run; each review in `review.refused` said as MISSES; her accepted review), a `media.director_second_look` (her run, no verdict). A review named without a verdict is said without one. | Which run worked on which scene, read from the record (`:216-221`); review of a9f84ea (`:727-730`). | CODE_RULE |
| `_from_correlations` | 769 | Events of each run's correlation within 12 h: storyboard, scene, review verdict; marks every run an event names `named` (`:801`). | One correlation can hold several scenes (`:773-775`). | CODE_RULE |
| `_review_verdicts` | 817 | Only for review runs with no verdict and not `named`: parses the stored answer with `read_structured` against `scene_rewrite.RewriteReview`, skipping runs `_asked_again` returns (see «LLM involvement»). | Show her verdict before the brief records it, never from an answer the validator refused (`:818-823`). | LLM_CHECKED_BY_CODE (display only) |
| `_asked_again` | 866 | Among the pending review runs: those whose next `director_rewrite_review` run of the same employee and correlation (ordered by `started_at`, id) has a template version ending in `+again` or `+think`. | `structured_run` writes its second attempt with those suffixes (`backend/app/agents/structured.py:56-57`, `:114`, `:117`). | CODE_RULE |
| `_place_titles` | 896 | Titles from storyboards, or a unique title completing the summary's cut one. | Summaries cut titles at 60 chars (`:900`). | CODE_RULE |
| `_placed_run_words` | 1003 | Finished scene/film run sentence; a review's MISSES said as «nu tratează constatarea» (reason ≤ 120 chars), a TREATS as «tratează constatarea.» — no longer followed by «se poate cumpăra» (`:1026-1031`). | What the office must hear before anything is bought, never that anything can be bought: that depends on money and the Owner's GPU hold (`:1011-1016`). | CODE_RULE |

Helpers (each under 20 lines): `_payload`, `_reference_parts` (parses `foaie:<film>:<step>:<plan>` and
`redo:<film>:<kind>:<scene>:…`), `_storyboard_of`, `_titles`, `_bare_title` (drops «Storyboard:»),
`_short`, `_end`, `_reason`, `_cause`, `_codes`, `_film`, `_feminine`, `_number`, `_seconds`,
`_purpose_ro`, `_vendor`, `_listed`, `_fallback`, `_task_of`, `_run_id`, `_hours_before`,
`_scene_number`, `_with_film`, `_placed_task`. Tables: `ROLE_WORDS_RO`,
`_ROLE_BY_PREFIX`, `_KIND_RO`, `_TASK_RO`, `_SCENE_TASK_RO`, `_FILM_TASK_RO`, `_GPU_OFF_RO`,
`_VENDOR_RO`, `_FAMILY_RO`, `_LOOK_KIND_RO`, `_RETRY_SUFFIXES`, the event names `_BRIEF_EVENT`,
`_REWRITTEN_EVENT`, `_SECOND_LOOK_EVENT` and others (`:59-293`).

Data read: `agent`, `role`, `storyboard`, `agent_run` (summary, task type, correlation,
`started_at`, `agent_id`, `prompt_template_version`, `output_text`), `domain_event`
(correlations). Writes nothing. Imports at read time `app.agents.identity.read_structured` and
`app.media.scene_rewrite` (`:833-837`).

### `app.goal` — backend/app/goal.py (292 lines)

The day's goal from the record: per channel, published today, in work (where and whose), blocked
(why and whose), the serial's next episode, one Romanian line. Read-only; any exception → `{}`
with a logged warning (`:206-212`).

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `goal_snapshot` | 206 | Public entry; never raises into the snapshot. | The Owner, 2026-10-12 14:00. | CODE_RULE |
| `_goal` | 215 | APPROVED/RENDERED storyboards of the last 7 days with no published asset, bucketed per channel type; published today per channel; totals line. | Same. | CODE_RULE |
| `_where` | 155 | (bucket, whose, words): open card → Owner; `OWNER_DECIDES`/`NEEDS_REFERENCE` refusal → Owner; WAITING on `LADDER_REFUSALS` → Director; HELD → studio; FAILED QC → Director; PASSED → studio; READY → studio. | «whose the wait is: the Owner's for money and his accounts, the Director's for quality» (`:9-10`). | CODE_RULE |
| `_next_episode` | 184 | Newest `StoryEpisode` without a storyboard and its state in words. | Serial channel. | CODE_RULE |

Helpers: `_day` (`:37`, newest `DailyRun.business_date`, else today's UTC date), `_since`,
`_title`, `_film_states` (latest `runbook.film_state` per storyboard), `_open_cards`
(`OwnerDecision` PENDING / WAITING_FOR_OWNER_ACTION about a storyboard), `_published`,
`_published_assets`, `_film_assets`, `_newest_report` (newest non-INVALIDATED QC report).
Constants: `TARGET_PER_CHANNEL = 2`, `LOOKBACK_DAYS = 7`, `CHANNEL_ORDER`.

### `app.security` — backend/app/security.py (196 lines)

Owner authentication for HTTP and WebSockets.

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `require_owner` | 60 | FastAPI dependency: Bearer key in constant time; a wrong key is logged (host, path) and counted; > 20/min → 429 `Retry-After`; else 401. Missing key not counted. | SEC-07: probing was invisible (`:17-23`). 20 routers depend on it. | CODE_RULE |
| `owner_key_matches` | 119 | Constant-time compare; empty never matches. | Demo refusal and sockets. | CODE_RULE |
| `socket_first_message_auth` | 143 | Waits ≤ 5 s for `{"type":"auth","token":…}`; 1008 on timeout/malformed/wrong, 1013 when 16 already wait. | A browser cannot set socket headers; URLs leak (`:91-98`). | CODE_RULE |
| `url_carries_key` / `refuse_key_in_url` | 173 / 178 | Any `token` query parameter → close 1008 before accept. | SEC-02, ADR-NO-SOCKET-TOKEN. | CODE_RULE |
| `pending_socket_auths` | 114 | Count of sockets waiting (W24). | Bound on open waits. | — |

Helpers: `_refusals` (`:34`), `_count_refusal` (`:44`), `_first_message_key` (`:126`), `_refuse`
(`:189`, logs only the reason).

### `app.local_session` — backend/app/local_session.py (137 lines)

LOCAL_AUTO_LOGIN: the Owner's page on his own machine receives the key without the sign-in form
(ADR-LOCAL-AUTO-LOGIN).

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `is_loopback_peer` | 69 | Exact match against `LOOPBACK_PEERS`. | uvicorn reports the socket address. | CODE_RULE |
| `local_handover_refusal` | 74 | Returns the first failing check: `disabled`, `bind`, `peer`, `proxy`, `host`, `origin`, `fetch_site`, `page`; None to hand over. | DNS rebinding, proxies, other origins, plain GETs (module doc `:7-21`). | CONFIG + CODE_RULE |
| `create_local_session_router` and its route ↳ `local_session` — GET `/api/v1/owner/local-session` | 109 / 114 | Refusal → 404 «Not Found» + DEBUG line; else `{"token": …}` with `no-store`, `Pragma: no-cache`, `Cross-Origin-Resource-Policy: same-origin` + INFO line without the key. Not in the API schema. | The Owner, 2026-10-08. | CODE_RULE |

### `app.logging` — backend/app/logging.py (272 lines)

JSON-line logging that keeps every extra but never a secret (REL-05, SEC-07, SEC-02).

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `redact_url_tokens` | 64 | Blanks every `token=` value. | uvicorn prints socket paths with queries (SEC-02). | CODE_RULE |
| `RedactUrlTokens.filter` | 72 | Applies it to uvicorn records. | Same. | CODE_RULE |
| `QuietStrangerSockets.__init__` / `filter` | 99 / 103 | Drops uvicorn's lines for refused sockets on paths the studio does not serve, and the rejection line within 2 s after. | Another program's page knocked on `/ws` every few seconds (Owner's console, 2026-10-02, `:92-97`). | CODE_RULE |
| `render_exception` | 153 | Class, `file:line:function` frames (≤ 30), cause class; never text or locals. | «an exception's text is where a vendor's echo of a key … turns up» (`:9-11`). | CODE_RULE |
| `JsonFormatter.format` | 170 | timestamp, level, logger, redacted message, every extra through `_safe_value`, rendered exception. | REL-05. | CODE_RULE |
| `log_directory` | 187 | `STUDIO_LOG_DIR`, else `logs` beside the SQLite file; None when file logging is off or the DB is not a file. | Log beside the data. | CONFIG |
| `configure_logging` | 213 | Console + rotating file handlers on `studio`, `amn`, `app`; replaces its own handlers on a second call; filters on uvicorn loggers. | One configuration per app instance. | CONFIG |

Helpers: `_safe_value` (`:119`, secret-named keys → `[ascuns]`; identifier/path keys kept with
control chars removed; other text through `app.providers.media_http.sanitise_vendor_text`),
`_where` (`:137`), `_exception_name` (`:147`), `_studio_handler` (`:208`).

### `app.page_build` — backend/app/page_build.py (107 lines)

Whether the served page was built from the sources on disk (PAGE-01; the 2026-10-01 bundle was
four days older than the shooting sheet). Standard library only, because `scripts/start.py`
imports it before the studio is installed (`:12-14`).

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `source_hash` | 53 | SHA-256 over `frontend/index.html` and `frontend/src/**` (relative path + LF-folded bytes), cached on (path, mtime, size). | Same hash on Windows and POSIX checkouts. | CODE_RULE |
| `write_build_record` | 74 | Writes `frontend/dist/build.json` (called by `scripts/start.py:125-129`). | Record what was built. | CODE_RULE |
| `page_build` | 94 | `{built, source, stale, basis}`: hash compare, else mtime compare, else `none`. | Banner «Pagina e mai veche decât studioul». | CODE_RULE |

Helpers: `_sources` (`:34`), `_fingerprint` (`:45`), `_recorded` (`:85`).

### `app.registry_loader` — backend/app/registry_loader.py (216 lines)

`PackageLoader`: imports every public module of a self-registering package once, on first read,
and keeps a failed module from leaving half its registrations live. Used by
`app.decisions.producers.PRODUCERS` (`backend/app/decisions/producers/__init__.py:60`),
`app.workflows.passes.PASSES` (`backend/app/workflows/passes/__init__.py:112`) and
`app.agents.repairs.REPAIRS` (`backend/app/agents/repairs/__init__.py:125`). Why: the Owner's
rule of 2026-10-09 (every correction must leave the studio able to repair itself) adds ~15
producer/pass modules; first-read import avoids an import circle (`:1-15`); two reviews of
2026-10-09 found half-registered broken producers whose applier could still run his accept
(`:21-34`).

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `PackageLoader.__init__` | 75 | State: lock, done/loading flags, errors, loaded, current import, added entries, owned entries. | — | — |
| `PackageLoader.done` | 93 | Property. | — | — |
| `PackageLoader.load` | 96 | Import all once (re-entrant safe); then `_drop_dead`. | First read imports the package. | CODE_RULE |
| `PackageLoader.added` | 114 | Called by a registry after a NEW entry: records it for undo when added during this loader's import on this thread; keeps it as owned by its function's module otherwise. | Undo of failed modules. | CODE_RULE |
| `PackageLoader._import_all` | 167 | Imports each non-underscore module sorted by name; a failure is undone, logged and named in `errors`. | «one broken module must not hide the rest» (`:180`). | CODE_RULE |
| `PackageLoader._drop_dead` | 141 | Removes owned entries whose module Python no longer has. | Failed imports elsewhere. | CODE_RULE |
| `PackageLoader._undo` | 195 | Removes the failed module's entries and forgets siblings it imported. | Same. | CODE_RULE |
| `PackageLoader.reset` | 207 | For tests: next read imports again. | Tests. | — |

Helpers: `_module_of` (`:50`), `_Owned.__init__` (`:63`), `PackageLoader._forget` (`:161`).

### `app.wording` — backend/app/wording.py (634 lines)

Pure code-to-Romanian dictionary («where a code becomes a word, once», `:7-8`); never changes a
code; an unknown code passes through lower-cased with spaces (`:12-15`). No imports from the
studio.

| function | line | what it does | why it exists | decided by |
|---|---|---|---|---|
| `count` | 28 | Romanian plural agreement («1 buget activ», «20 de bugete»). | Same rule as the page's `countLabel` (94 callers). | CODE_RULE |
| `decimal` | 40 | Comma decimals. | 25 callers. | CODE_RULE |
| `settings_place` | 69 | Settings tab in words; an unknown tab is a KeyError, never a guess. | W34 (`:56-59`). | CODE_RULE |
| `stage_name` / `stage_list` | 106 / 113 | Daily-run stage names. | Register words. | CODE_RULE |
| `host_test_detail` | 355 | Full Romanian sentence for a research host's failed reading test from its code and the retriever's English text (never printed). | W31. | CODE_RULE |
| `written_for_the_owner` | 545 | Diacritics or ≥ 2 common Romanian words. | Distinguish the studio's sentences from library text. | CODE_RULE |
| `error_words` | 564 | Exception → Romanian kind of fault (Owner-written text kept; DB busy; HTTP status class; timeout; unreachable; studio classes; shape error; else «o eroare neașteptată în codul studioului»). | «never a library's raw text» (`:568-570`). | CODE_RULE |
| `error_fields` | 632 | `{error_class, error_detail[:500]}` for diagnosis. | Keep the raw fault as data. | CODE_RULE |
| `sentence` / `clause` | 617 / 623 | Capitalise + full stop / lower-case for after a colon. | Sentence assembly. | CODE_RULE |

One-line code mappers. Each is `_words(TABLE, code)` (an unknown code → lower-cased with spaces,
an empty one → «—») or a plain table lookup over the dictionary defined just above it; none
decides anything, all are CODE_RULE.

| function | line | table it reads | used for |
|---|---|---|---|
| `stage_status` | 133 | `STAGE_STATUS` (`:119`) | a daily-run stage's status |
| `autonomy_mode` | 147 | `AUTONOMY_MODE` (`:140`) | the mode in a sentence (`services.mode_words`) |
| `environment` | 155 | `ENVIRONMENT` (`:152`) | TEST / PRODUCTION |
| `budget_period` / `budget_state` | 174 / 178 | `BUDGET_PERIOD` (`:162`) / `BUDGET_STATE` (`:165`) | a budget's period and state |
| `work_status` | 195 | `WORK_STATUS` (`:185`) | a script's or storyboard's own state (callers in `app.story`) |
| `review_verdict` / `viewing_verdict` | 210 / 218 | `REVIEW_VERDICT` (`:200`) / `VIEWING_VERDICT` (`:215`) | story and viewing review verdicts |
| `publication_verdict` / `publication_status` | 226 / 246 | `PUBLICATION_VERDICT` (`:223`) / `PUBLICATION_STATUS` (`:231`) | publication readiness and state |
| `privacy` | 254 | `PRIVACY` (`:251`) | YouTube privacy |
| `provider_name` | 268 | `PROVIDER_PRODUCT` (`:259`) | a vendor as the Owner knows it |
| `qc_status` | 285 | `QC_STATUS` (`:277`) | a quality-control result |
| `host_test_reason` | 317 | `HOST_TEST_REASON` (`:307`) | a research host test's code |
| `youtube_scope` | 408 | `YOUTUBE_SCOPE` (`:399`), plain `.get` | a YouTube OAuth scope (preflight) |
| `search_engine` | 422 | `SEARCH_ENGINE` (`:416`) | whether a web search engine is verified (preflight) |
| `decision` / `confidence` | 442 / 451 | `DECISION` (`:429`, own capitalising fallback) / `CONFIDENCE` (`:448`) | a Director's decision as an imperative and its confidence (`app.agents.command`) |
| `pipeline_stage` / `constraint` / `diagnosis` / `anomaly` | 465 / 480 / 494 / 506 | `PIPELINE_STAGE` (`:456`) / `CONSTRAINT` (`:470`) / `DIAGNOSIS` (`:485`) / `ANOMALY` (`:499`) | the bottleneck stage, what limits a channel, why a film underperformed, an anomaly (`app.agents.command`; `diagnosis` from `app.analytics.performance`; `constraint` has no caller in the static graph) |

Helpers: `_words` (`:45`), `_status_of` (`:536`), `_chain` (`:551`). Constants: `SETTINGS_TABS`
(`:60`), `COMMAND_REUSED` (`:78`), `STAGE_NAMES` (`:87`), `AUTONOMY_STOPPED` (`:291`),
`MEDIA_KEY_UNUSABLE` (`:297`).

## Connections

**Who calls into this group**

- `require_owner` guards the Owner's routers (18 modules, about 20 routers: agents and
  providers, analytics, decisions, economy, factual, integrations/settings, media, office, the
  kept frame's POST, RunPod router and setup steps, publishing, runbook, story, workflows/tasks/
  scheduler, workforce, YouTube, main). Not behind it by design: `/health/*`, the local-session
  hand-over, the kept frame's GET (`backend/app/office/kept_frame.py:227`) and the YouTube OAuth
  callback; the sockets authenticate with `socket_first_message_auth`.
- `may_act` is called by `app.agents.services` (every model run, `:630`), `app.agents.repairs.desk`
  (`:316`, `:555`), `app.media.assembler` (`:9970`, `:11664`, `:16045`), `app.media.mode_guard`
  (`:66`), `app.media.services` (`:1905`), `app.media.shooting_sheet` (`:3703`),
  `app.media.stills_stage` (`:2027`), `app.providers.runpod.gpu_session` (`:833`),
  `app.publishing.licence_release` (`:298`), `app.runbook.stages` (`:302`).
- The kernel's private helpers are also imported from outside: `_answered_approval` by
  `backend/app/media/assembler.py:13053-13059` and `backend/app/media/sheet_words.py:309-320`;
  `_ask_or_spend` and `_paid_media_context` by `backend/app/media/assembler.py:13087-13097`;
  `_runpod_infra_allowed` by `app.providers.runpod.gpu_session`.
- The Owner's commands are also run by `app.decisions.services` appliers when he accepts a card
  (`backend/app/decisions/services.py:353`, `:382`, `:392`), always issued as the Owner.
- `queue_film_continue` has eleven external callers in ten modules (the `redo_cap` decisions
  producer, assembler, blocker repair, shooting sheet, two in stages, serial stage, and four
  watchdog passes), besides `decide_approval` here.
- `append_event` (202 external callers), `utc_now` (170), `lock_for_write` (150), `count` (93),
  `studio_environment` (24), `error_words` (22), `paid_media_policy` (6 external).
- `pending_approvals`: decisions, accountant, answered letters, stages, main.
- `enrich`: `services.snapshot`, `services.read_events`, `app.workflows.publisher` (live socket).
- `run_backup_job`: `backend/app/workflows/worker.py:430-432` (task `BACKUP`).
- `PackageLoader`: decisions producers, workflow passes, agent repairs.
- Scripts: `scripts/bootstrap.py` (`backup_before_migration`, `migrate`, `bootstrap_studio`),
  `scripts/backup.py` (`list_backups`, `make_backup`), `scripts/restore.py` (`restore_backup`),
  `scripts/reset_history.py` (`reset_history`), `scripts/start.py` (`source_hash`,
  `write_build_record`, `prepare_demo_studio`), `scripts/demo_daily_run.py`
  (`prepare_demo_studio`, `run_demo_day`), `scripts/e2e_server.py` (`bootstrap_studio(...,
  autonomy_mode="AUTONOMOUS_CEO")`).

**What this group calls out to**

`app.workflows` (worker, services, publisher, router), `app.runbook` (stages, services, weekly,
models), `app.integrations` (vault, registry load, discovery, vault health),
`app.providers.runpod` (gpu_guard, gpu_session), `app.providers.ollama`,
`app.economy.prices` / `models`, `app.decisions` (seed, refresh, models),
`app.media` (shooting_sheet lease reclaim, disk, toolchain, models, services),
`app.agents.memory` (`remember`, `agent_for_role`), `app.agents.messages.post_message`,
`app.office.unreal`, `app.publishing.services` / `models`, `app.story.models`,
`app.youtube.models`, `app.providers.media_http.sanitise_vendor_text`,
`app.providers.deterministic_media` (demo); the register reads with
`app.agents.identity.read_structured` and `app.media.scene_rewrite.RewriteReview` (lazy imports,
`backend/app/events_feed.py:833-840`).

**Events emitted here**: `studio.created`, `office.room_created`, `owner.environment_changed`,
`autonomy.stopped`, `autonomy.stop_cleared`, `owner.autonomy_mode_changed`,
`owner.paid_media_approval_changed`, `owner.restore_guard_applied`,
`governance.approval_requested`, `governance.approval_decided`, `governance.approval_consumed`,
`governance.approval_withdrawn`, `operations.backup_made`, `operations.backup_failed`,
`operations.worker_failing`, `studio.history_reset`, `demo.prepared`.

**Events consumed here**: every event, for words (`app.events_feed`); `runbook.film_state` (goal);
`studio.history_reset` (ledger floor); `media.director_scene_brief`, `media.prompts_rewritten`,
`media.director_second_look` and correlations (run places); `media.director_second_look` also
for its own sentence (`backend/app/events_feed.py:1180-1181`).

**Letters to the Owner written here**: `backup_failed` (`backend/app/backup.py:516-537`),
`worker_failing` (`backend/app/operations.py:96-128`), both ESCALATE from the Director's identity.

## Owner touchpoints

| touchpoint | what the Owner decides | where |
|---|---|---|
| «STOP autonomie» | Every autonomous act stops (`may_act` → BLOCKED_STOP) and every model run is refused (BLOCKED_POLICY in `_assert_policy_allows_run`) until he clears it; scheduled jobs and queued tasks do not fire; the GPU may still be switched off. | `backend/app/main.py:952`, `backend/app/services.py:382`, `:1491`; `backend/app/agents/services.py:618-621`; `backend/app/workflows/services.py:366`, `:376`, `:814` |
| Environment TEST / PRODUCTION | What generations may cost; FILM_CONTINUE only in PRODUCTION. | `backend/app/main.py:876`, `backend/app/services.py:244`, `:659` |
| Autonomy mode | Which risk tiers run unasked; promotion refused under stop or safe mode. | `backend/app/main.py:888`, `backend/app/services.py:1636` |
| Paid-media rule (EVERY_PAID_STEP / OVER_USD + threshold / MODE) | When a film's stills, hero test shot, motion or scene redo asks him. | `backend/app/main.py:903`, `backend/app/services.py:1816` |
| Approval list and answers | APPROVED / REFUSED (+ note) per action and film; a yes on a paid step continues the film at once. | `backend/app/main.py:921`, `:933`; `backend/app/services.py:913`, `:937` |
| Decision cards that apply his commands | Accepting a card runs `change_paid_media_approval` / `change_environment` / `change_autonomy_mode` as him. | `backend/app/decisions/services.py:353`, `:382`, `:392` |
| RunPod card `allow_infra_actions` | Whether agents may switch the GPU on inside an approved step. | `backend/app/services.py:1339-1349` |
| Daily budget (economy) | Without an active DAILY budget nothing is bought unasked in PRODUCTION. | `backend/app/services.py:1234`, `:1583-1595` |
| Daily run activation | `daily_main` is created dormant; he starts the clock. | `backend/app/main.py:475-487` |
| `.env` settings | Every `Settings` field: Owner key, hosts, hours, money caps, retries, backup, logging, demo, office. | `backend/app/config.py:45-511` |
| Local auto-login | `STUDIO_LOCAL_AUTO_LOGIN=false` brings the sign-in form back. | `backend/app/config.py:64`, `backend/app/local_session.py:87-88` |
| Backup / restore / reset scripts | He runs `scripts/backup.py`, `scripts/restore.py` (then re-enables stop/environment/daily job and re-types unreadable keys), `scripts/reset_history.py`. | `backend/app/backup.py:627-722`, `backend/app/services.py:321-379`, `backend/app/maintenance.py:84` |
| Letters | Backup failed (once a day); worker failing (at 3 failed passes). | `backend/app/backup.py:516`, `backend/app/operations.py:96` |
| Page banners | Operations problems (`banner_ro`), stale page, demo banner, the goal line («… așteaptă decizia ta»). | `backend/app/operations.py:263-272`, `backend/app/page_build.py:94`, `backend/app/services.py:2001`, `backend/app/goal.py:278-283` |

## Oddities and gaps

1. **History reset can commit a half-deleted studio.** `HISTORY_TABLES`
   (`backend/app/maintenance.py:30-71`, file last changed in ca713bb, 2026-09-18) does not list
   `scene_take` (FK `storyboard.id` NOT NULL), `film_purchase_lease` (PK/FK `storyboard.id`),
   `story_review` (FK `script_draft.id`), `director_decision` and `llm_collaboration` (FKs to
   `agent_message` / `agent_run`), or `model_outcome` (FK `video_render_job.id`), while it deletes
   their parents. The `foreign_key_check` runs at `:149` after the `with connection.begin()` block
   (`:99-148`) has committed, so on a studio with such rows the reset raises «Reset left foreign
   key violations» with the deletes already committed — the opposite of the docstring's «a
   half-deleted studio is an error, never a state» (`:89-91`). `owner_decision`,
   `spend_reservation` and the RunPod session tables are also not reset.
2. **`db.migrate` checks foreign keys after the commit too** (`backend/app/db.py:97-103`).
3. **Spec 31 says an approval «is read in one place only: inside the authority gate»**
   (`docs/architecture/31_GOVERNANCE_APPROVAL_POLICY.md` «What an approval does»). The kernel's
   private helpers are also used outside `may_act`: `_ask_or_spend` spends a yes from
   `backend/app/media/assembler.py:13089` (after a kernel ALLOWED, per its docstring
   `:13080-13086`), `_answered_approval` is read from `backend/app/media/assembler.py:13059` and
   `backend/app/media/sheet_words.py:320`, and `_gpu_on_verdict` reads an `ApprovalRequest` row
   directly (`backend/app/services.py:1389-1401`).
4. **Under MANUAL, a paid step can still be bought with the Owner's yes**: when his rule asks
   (EVERY_PAID_STEP, or OVER_USD above the threshold or with an unknown cost) the paid-media
   branch reads and spends his answer and returns before the mode ceiling is consulted
   (`backend/app/services.py:1545-1577`); the «a yes is not a way past MANUAL» rule
   (`:1606-1609`) applies only to the SUPERVISED T3 branch. Consistent with spec 51's
   «EVERY_PAID_STEP … asks him in every mode», but spec 51 also says of this rule «a step the rule
   lets through still meets the mode, and a mode that refuses still refuses»
   (`docs/architecture/51_AUTONOMY_MODE_SEMANTICS.md` «Paid media steps», lines 88-90), while a
   MANUAL studio (ceiling T1) would otherwise refuse every paid step `BLOCKED_MODE`. The two
   readings coexist in one function.
5. **`agent.run` is not in `ACTION_RISK_TIERS`**; it passes only because the caller supplies T1
   (`backend/app/agents/services.py:630`). Since every mode and safe mode allow T1, the kernel's
   mode and safe-mode checks never refuse a model run. The stop is read twice: first by
   `_assert_policy_allows_run` itself (`backend/app/agents/services.py:618-621`, status
   `BLOCKED_POLICY`), then by `may_act`, whose `BLOCKED_STOP` can therefore only come from a
   missing policy row at this call site. The comment at `:623-629` says the call refuses the run
   «should safe mode open under a run in flight», but `SAFE_MODE_ALLOWS = "T1"` and the check is
   `tier > SAFE_MODE_ALLOWS` (`backend/app/services.py:532`, `:1505`), so an open safe-mode
   record never refuses a T1 run; and no mode is below MANUAL's T1 ceiling.
6. **Tier ordering is string comparison** (`backend/app/services.py:1461`, `:1505`, `:1597`,
   `:1255`); correct for `T0`..`T4` only.
7. **Duplicated idempotency code.** `change_environment` (`:250-260`), `change_stop`
   (`:383-395`) and `change_autonomy_mode` (`:1653-1663`) inline the hash/recall/record logic;
   `decide_approval` and `change_paid_media_approval` use `recall_command`/`remember_command`.
   `command_hash` (`:164`) hashes differently (`default=str`, no `mode="json"`).
8. **Duplicated migration-head reading**: `app.main.expected_revision` (`backend/app/main.py:177`)
   and `scripts/bootstrap.py:55-60`.
9. **Duplicated job-name literal**: `RESTORE_GUARD_JOBS = ("daily_main",)`
   (`backend/app/services.py:318`) repeats `DAILY_JOB_NAME` (`backend/app/workflows/worker.py:78`).
10. **Default mode disagrees across layers by design**: DB server default AUTONOMOUS_CEO
    (`backend/app/models.py:55-57`), `PolicyView` default AUTONOMOUS_CEO
    (`backend/app/schemas.py:62`), `policy_view` reads None as MANUAL
    (`backend/app/services.py:224`), new studios are written MANUAL (`:94`, `:123-128`). The
    comments explain each, but there are three answers to «unknown mode».
11. **`_hours_setting` constructs `Settings()` on every call** (`backend/app/services.py:544`),
    re-reading `.env` each time an approval is raised, and ignores the running app's own settings
    object (fallback 24/48 when construction fails).
12. **`change_environment` has no stop/safe-mode check**: PRODUCTION can be set while the stop is
    on or an incident is open (`backend/app/services.py:244-313`), unlike a mode promotion.
13. **Snapshot module maturity is hard-coded** (`backend/app/services.py:2002-2040`:
    `"maturity": "DEVELOPMENT"`, `"deployment_mode": "LOCAL_STUDIO"`, and a `modules` map «Read
    against the code on 2026-09-24»).
14. **Stale chronology comment**: the lifespan comment lists migrations up to 0049
    (`backend/app/main.py:274-285`); the chain is at 0057 (`backend/migrations/versions/`). The check
    itself reads the head and is not affected.
15. **Log directory for a relative SQLite URL is relative to the process's working directory**
    (`backend/app/logging.py:198-205`: `Path(database).parent / "logs"`), whereas the engine and
    backups resolve relative paths under the repo root (`backend/app/db.py:46-48`,
    `backend/app/backup.py:110-112`). The worker-failing letter names `data/logs/studio.log`
    literally (`backend/app/operations.py:123`) although `STUDIO_LOG_DIR` can move it.
16. **The demo guard checks one path only**: `guard_demo_database` refuses `ROOT/data/studio.db`
    (`backend/app/demo.py:107`); a real studio configured at another path is not recognised.
    `demo_settings` does not turn off `runpod_guard_enabled` (`backend/app/demo.py:561-576`), so
    the boot GPU guard runs in the demo under `no_outbound_network`.
17. **The goal's «today» is the newest DailyRun's business date** (`backend/app/goal.py:37-44`),
    and publications are matched by string prefix of `published_at`/`created_at` against it
    (`:102-104`) without time-zone conversion. `TARGET_PER_CHANNEL = 2` is a constant, not a
    setting (`:26`).
18. **The register reads a rewrite review with the bare schema, not the one the review is
    accepted with.** For a review run no event names yet, `_review_verdicts` validates the stored
    answer against `scene_rewrite.RewriteReview` (`backend/app/events_feed.py:838`, `:856`), while
    the review is asked and accepted against `review_schema(...)`'s `BoundReview`
    (`backend/app/media/scene_rewrite.py:402-447`, `:1736`), which also refuses unknown, missing or
    repeated finding ids, an untreated finding naming a field the editor may not change, a lock
    that quotes no words the layer keeps, and a broken lesson naming a field he may not change
    (`scene_rewrite.py:411-447`). A refused first attempt is skipped once its `+again` run
    exists (`backend/app/events_feed.py:866-893`; not in the moments before that run starts), but
    a second attempt the bound schema refused has no later run, so until an event names that run
    (`_runs_named`, `:726-766`) the register can still say a TREATS or MISSES from an answer the
    studio refused. The verdict itself is the schema's computed property, never the model's own
    word (`scene_rewrite.py:374-381`). Display only. (The earlier
    regex reading of the model's own `"verdict"` text was removed by commit `68fa0b4`.)
19. **`events_feed._VENDOR_RO` hard-codes three model ids to RunPod**
    (`backend/app/events_feed.py:155`); any other model's take is said with «furnizor» (`:448-450`).
20. **`/health/ready` status vs code**: unreadable credentials make `status` DEGRADED while the
    HTTP code stays 200 (`backend/app/main.py:816-826`); documented in spec 25 «As built».
21. **Restore guard vs spec 25**: the spec's guard lasts «until Owner confirms environment;
    credentials checked; reconciliation completed»; the code sets the stop, TEST and the daily job
    off and lists unreadable credentials (`backend/app/services.py:321-379`,
    `backend/app/backup.py:693-722`); nothing in code tracks «reconciliation completed» — the Owner
    lifts the guard by his own commands.
22. **SQL built by interpolation in the reset**: kept event ids are joined into a `NOT IN (...)`
    literal (`backend/app/maintenance.py:131-134`) and table names are formatted into SQL
    (`:80`, `:113-114`, `:125`); all values come from the database catalogue and constants, not
    from requests.
23. **`security._pending_socket_auths` is a module global without a lock**
    (`backend/app/security.py:111`, `:153-169`), relying on one event loop (stated at `:110`).
24. **The goal does not see a film waiting for the Owner's paid-media yes as his wait.**
    `_open_cards` reads only `OwnerDecision` rows (`backend/app/goal.py:78-90`), while a pending
    `ApprovalRequest` is shown in his window as a card built on the fly from `pending_approvals`
    and never stored as an `OwnerDecision` row (`backend/app/decisions/services.py:1403-1409`,
    `:1582`). `_where` has no branch for the film state `ASKED` the day records when a step waits
    for his yes (`backend/app/runbook/stages.py:2966-2978`), and `NEEDS_APPROVAL` is not in
    `OWNER_DECIDES` (`backend/app/runbook/stages.py:1441-1464`). Such a film falls through to
    «in work» (whose: studio, or Director when the reason names her, `goal.py:179-181`) and is not
    counted in «… așteaptă decizia ta» (`goal.py:275-283`).
25. **Retention after a special copy ignores the Owner's keep settings.** `backup_before_migration`
    and the restore's `prerestaurare` copy call `make_backup` without `keep_daily`/`keep_weekly`
    (`backend/app/backup.py:420`, `:657`), so the retention pass that follows uses the defaults 14/4
    (`:217-218`, `:290`) and can delete daily copies a larger `STUDIO_BACKUP_KEEP_DAILY` would keep;
    the daily job and `scripts/backup.py:78-84` pass the settings.
26. **Unused constant**: `ROWS_PRUNED_EVENT = "operations.rows_pruned"` (`backend/app/backup.py:75`)
    is never emitted; the pruned counts travel inside `operations.backup_made` (`:572-592`).
27. **Job settings apply only at creation.** `ensure_scheduled_job` leaves an existing job alone
    except its local hour (`backend/app/workflows/services.py:693-719`), so a later change of
    `STUDIO_WATCHDOG_INTERVAL_SECONDS` does not reach the job row created at an earlier start
    (`backend/app/main.py:491-499`), and turning `trends_enabled` off leaves `trends_daily` active
    (its fire is then neutralised by the refresh's own check, `backend/app/analytics/trends.py:144`).
28. **`wording.constraint` has no caller** in `backend/` (`backend/app/wording.py:480`; static
    graph and grep).
29. **Two of the register's four second-look sentences cannot be produced, and a minor defect is
    said as a wrong refusal.** `_second_look_words` has branches for CONFIRMED without redo («…
    defectul e mic — se acceptă, nu se reface») and OVERTURNED with redo («… dar scena tot se
    reface») (`backend/app/events_feed.py:610-614`), but `SecondLook._consistent` refuses both
    combinations (`backend/app/media/second_look.py:114-135`) and the event carries the validated
    answer's `verdict`/`redo` unchanged (`:753-760`, `:544-546`); UNAVAILABLE carries `redo` True
    but is said by the first branch (`events_feed.py:603-605`). An OVERTURNED that names a real but
    minor defect (`severity` «minor», allowed: `second_look.py:91-92`) is said «refuzul controlului
    e greșit» (`events_feed.py:606-607`): the register never reads `severity`.
30. **The register imports the media stage at read time.** `_review_verdicts` imports
    `app.media.scene_rewrite` («it imports the whole media stage») and
    `app.agents.identity.read_structured` inside the function (`backend/app/events_feed.py:833-837`),
    on the snapshot's and the socket's read path whenever a review run is pending; an ImportError
    shows no verdict, silently (`:836-837`), as does a missing `RewriteReview` (`:838-840`).
