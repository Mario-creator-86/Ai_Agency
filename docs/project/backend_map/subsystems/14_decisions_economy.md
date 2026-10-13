# 14 — Owner decision cards and the economy (budget, credits, prices, Accountant, ledger)

Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).

> Files (9,929 lines in all):
> `backend/app/decisions/__init__.py` (1), `backend/app/decisions/models.py` (85),
> `backend/app/decisions/producers/__init__.py` (62), `backend/app/decisions/producers/gpu_hold.py` (117),
> `backend/app/decisions/producers/redo_cap.py` (475), `backend/app/decisions/router.py` (64),
> `backend/app/decisions/seed.py` (701), `backend/app/decisions/services.py` (1659),
> `backend/app/decisions/sources.py` (1376), `backend/app/economy/__init__.py` (6),
> `backend/app/economy/accountant.py` (1359), `backend/app/economy/as_of.py` (313),
> `backend/app/economy/budget.py` (768), `backend/app/economy/credits.py` (306),
> `backend/app/economy/models.py` (512), `backend/app/economy/prices.py` (364),
> `backend/app/economy/router.py` (167), `backend/app/economy/services.py` (1594).
>
> Mapped 2026-10-12 from commit b00083c plus the working tree. HEAD moved to 3d49e9a while this
> was read and verified; `git diff b00083c HEAD` and `git status` show no change to any file of
> this group. 261 functions in scope (inventory; 97 of 25+ lines, 13 route handlers), 1 LLM call
> site, 1 function that reaches the LLM indirectly. Verified adversarially against the code on
> 2026-10-12 (second pass): corrections are folded into the text below. No commit from b00083c
> to 20abffd touches a file of this group; the `media/assembler.py` lines cited below hold at 20abffd.

## In one paragraph

This group is where the studio meets the Owner's authority and the Owner's money. The **decision
cards** (`app.decisions`) are one table of questions only the Owner answers: anyone in the studio
(an agent, a stage, the start-up audit) may *propose* a card, deduplicated by a key; only the Owner,
through one route behind the Owner key, *decides* it; the accepted option runs one of the Owner's own
existing commands (budget, paid-media rule, environment, autonomy mode, a sheet command, a RunPod
switch, a redo allowance) under a deterministic inner command id, or records a guided step he must
do himself, and the card closes by itself when a code-readable condition says the question went
away. The **economy** (`app.economy`) is integer-micro book-keeping: USD spending budgets per day
and month with reservations taken behind the write lock, a `provider_price` table that only the
Owner types (or a documented seed), cost rows for every render (priced first from the vendor's
named credits and the model catalogue's `provider_resource.pricing`, the Owner's table only as a
fallback), invoices the Owner reconciles, a token ceiling and an "exceeded budget" stop in front
of every language-model run, a set of deterministic letters to the Owner, and a retired
double-entry VR$ ledger kept for history. Exactly one function asks a model anything: the
Accountant's daily close (`reconcile_day`), whose answer is advisory; every figure, threshold
and refusal in this group is computed by code, and the close's escalation is decided by the
books (the model can only add an escalation, never remove one).

## Why it exists

- **Cards.** The Owner, 2026-10-03: «Dacă sunt decizii pe care eu ca owner trebuie să le iau,
  trebuie să îmi apară un card…» (`backend/app/decisions/services.py:3-5`). His questions were
  scattered over approvals, letters, Settings and audit prose (docs/project/16_DECISION_LOG.md:4136,
  ADR-OWNER-DECISION-CARDS). The normative text is docs/architecture/31_GOVERNANCE_APPROVAL_POLICY.md:156
  («Owner decision cards (amended 2026-10-03)»: anyone proposes, only the Owner decides, his accept
  runs his own command, a card is never an approval and never reaches past a hard gate).
  Related ADRs: ADR-ONLY-OWNER-DECIDES (16_DECISION_LOG.md:4138), ADR-GUIDED-DECISIONS (:4142),
  ADR-DECISION-SOURCES (:4144), ADR-DECISIONS-WINDOW (:4146), ADR-DONE-READS-CONDITION (:4184; on
  2026-10-03 his «Am făcut-o» closed three cards with nothing done, `services.py:1034-1037`).
- **Producer registry (2026-10-09, P0).** The self-repair plan adds about fifteen cards; each now
  registers its applier and condition from its own module instead of editing the core's tables
  (`backend/app/decisions/producers/__init__.py:1-58`, `backend/app/registry_loader.py:1-35`).
- **GPU hold card (2026-10-12).** At 16:52:08 the Owner pressed «Oprește GPU acum»; 25 s later the
  Director's repair walk opened a new GPU session and bought the same clip again. The press is now a
  hold, and this card is the only way back (`backend/app/decisions/producers/gpu_hold.py:1-15`,
  docs/project/CHANGELOG.md:3-5).
- **Redo-cap card (2026-10-12).** Film 1c038a99: the Director decided REPAIR three times in eleven
  seconds and each repair was stopped by the Owner's paid-redo cap; the film would have looped in
  her inbox. The cap is money, money is his, so it becomes his card
  (`backend/app/decisions/producers/redo_cap.py:1-23`; 16_DECISION_LOG.md:35-37). The same day the
  card was found raised on a miscount ("5 of 5" was really 2), hence `cap_still_reached`
  (`redo_cap.py:387-390`; 16_DECISION_LOG.md:7-9).
- **Budgets.** Nothing said what the Owner allows; the period opened at UTC midnight while the
  studio's day is Europe/Bucharest; `may_spend(engine, 0)` from a snapshot let two films share the
  last ten dollars, hence reservations behind the write lock (`backend/app/economy/budget.py:1-21`;
  16_DECISION_LOG.md:2018-2022). PAGE-05: an empty field once retired the daily budget with one
  Enter (`budget.py:71-77`).
- **Prices.** On a copy of the live DB (2026-09-18): 391 agent runs with `cost_vr` NULL, nine
  ElevenLabs models with `pricing {}` (`backend/app/economy/prices.py:3-25`; 16_DECISION_LOG.md:2034,
  :2038). A price is the Owner's fact, never an agent's or a vendor page's.
- **The Accountant.** "The books were kept but nobody read them" (`backend/app/economy/accountant.py:1-36`):
  figures computed, judgement asked of a model, escalation decided by the books. The token ceiling
  (391 runs under no ceiling, 16_DECISION_LOG.md:2048-2050) and MONEY-10 (an exceeded USD budget
  stopped no run, `accountant.py:1113-1117`). 2026-10-11: shown only counts, the Accountant asked the
  Director three times for a rate card the Owner had typed and for film costs in her own books
  (`accountant.py:96-98`, `:148-152`, `:244-246`).
- **Cost rows.** Two lost shots cost six dollars on 2026-09-16 and the books said nothing
  (`accountant.py:620-622`); the 2026-09-18 rehearsal wrote 1.44 USD for shots never bought
  (`accountant.py:402-405`); 2026-10-02 a refused booking was a log line while 2,040 credits showed
  as 680 (`accountant.py:817-818`); 2026-10-09 14:17 UTC a booking failed with «database is locked»
  after 2,100 s of GPU (`backend/app/economy/services.py:739-746`).
- **Reconciliation.** 4.20 estimated + 4.55 billed for one render charged a period 8.75
  (`backend/app/economy/models.py:259-264`, `services.py:1249-1251`; 16_DECISION_LOG.md:3041-3063).
- **Credits.** The ATLAS film was booked at 0.316 USD from catalogue prices; the Nepal film's first
  render moved the Runway balance by 966 credits while the books said 0.74 USD
  (`backend/app/economy/credits.py:1-13`, `:162-168`).
- **Ledger.** Phase 11 (spec docs/architecture/66_VIRTUAL_REAL_ECONOMY_ENGINE.md,
  58_FINANCE_ACCOUNTING_FINOPS.md): one verified dollar = one VR$, once (`services.py:1-25`;
  16_DECISION_LOG.md:1813, :1825). Retired as a product on 2026-10-08 by ADR-SIMPLE-PIXEL-STUDIO
  («Retire public Treasury, funding, minting, FX, virtual-ledger…; keep actual USD budgets/prices/
  provider costs», 16_DECISION_LOG.md:531-553; spec 66 §«Current Owner scope», 66_VIRTUAL_REAL_ECONOMY_ENGINE.md:3-19;
  `backend/app/economy/router.py:1-4`).

## Who decides here

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| Who may answer a card | CODE_RULE (+ OWNER key) | `decisions/services.py:1188-1192`, `decisions/router.py:24` | `issued_by` must be `"owner"`; route behind `require_owner`; `DecideCommand` forbids extra fields so no body can name an issuer (`services.py:147-158`). Anything else: `DecisionRefused` (403). |
| Whether an answer is still valid | CODE_RULE | `services.py:1112-1134` | `ALLOWED_FROM`: ACCEPT only from PENDING; REFUSE from PENDING or WAITING_FOR_OWNER_ACTION; DONE only from WAITING. `expected_version` must equal the card's `version`, else 409. Idempotent by `command_id` (`_recall`, `services.py:1098-1102`). |
| Which option an ACCEPT applies when none is named | CODE_RULE | `services.py:1137-1150` | The recommended option; else the only option; else `DecisionInvalid` (422). |
| Applying an accepted option | OWNER (through his own command) | `services.py:1221-1228`, `APPLIERS` at `:438-453` | Runs the registered applier under `uuid5(card, version, option)` (`:1105-1109`) so a retried answer never applies twice; a refusal (`DecisionApplyFailed`) leaves the card PENDING with the Romanian reason (`:1153-1171`). |
| Refuse an apply because the state moved since the card was written | CODE_RULE | `services.py:288-295` | Option `apply.expect` must equal the current policy value (paid-media rule, environment, autonomy mode). Budget cards carry `expected_version` checked by `set_budget` (`economy/budget.py:186-193`). |
| Accept of an option type nobody registers any more | CODE_RULE | `services.py:1210-1220` | Refused, card stays PENDING (`UNKNOWN_APPLY_RO`, `:118-121`). |
| Whether a guided card closes on his «Am făcut-o» (DONE) | CODE_RULE over DB / EXTERNAL state | `services.py:1242-1260`, `condition_reading` `:637-652` | Closes only when `clears_when` reads MET or the card is ONLY_OWNER (`never` / no condition); UNMET or UNREADABLE keeps it waiting with `still_missing_ro`. |
| Card withdrawn / completed by itself | CODE_RULE | `refresh_owner_decisions` `services.py:961-991`; `_close_by_condition` `:910-929` | Condition reads MET: PENDING → WITHDRAWN, WAITING → ACCEPTED (completed by condition). Runs at boot and on every read of the cards feed (`:1575-1579`). |
| Card expiry | CODE_RULE | `services.py:972-973` | PENDING with `expires_at <= now` → EXPIRED. No proposer in the backend passes `expires_at` (see Oddities). |
| One open card per question | CODE_RULE + DB | `decisions/models.py:46-51`, `services.py:853-884` | Partial unique index on `dedupe_key` where status is open; a racing insert falls back to the standing card. |
| Do not re-ask a refused question | CODE_RULE | `decisions/sources.py:149-179` | A REFUSED card, or an ACCEPT of an option whose apply type is `none`, keeps the key quiet for `REFUSAL_QUIET_DAYS` = 7 (`sources.py:60`). |
| The audit seed never re-seeds a key | CODE_RULE | `decisions/seed.py:662-668`, `:696-698` | A key that ever had a card (any state) is skipped. |
| Re-open a guided card an unverified DONE closed | CODE_RULE | `services.py:1031-1087` | ACCEPTED guided card completed by owner without `done_reading` and never re-opened, whose condition is not MET/ONLY_OWNER; not if an open or newer card has the key. |
| Film budget card (daily run) | CODE_RULE | `sources.py:579-670` | Only for refusals OVER_DAILY_BUDGET / BLOCKED_NO_BUDGET; only when the step cap can never fit (no active daily limit, or limit < step cap); recommended limit = ceil(max(step cap, film's `estimate_film_cost_micros` sum) / 5) × 5 USD (`:611-613`). A refusal that is not a budget one withdraws the film's card (`:594-601`); a budget refusal whose step fits a day proposes nothing and leaves any standing card to its condition `daily_budget_at_least` (`:608-610`, `:666`). |
| Audit budget card | CODE_RULE + CONFIG | `seed.py:185-257`, `cheapest_capable_film` `:108-179` | Reference film 4 scenes × 10 s, people, scene 1 HERO, planned by `plan_scene_models` on the Runway connection's capabilities or `config/film_models.json`, priced from the published table; cap = stills + motion + dearest shot + one more round of stills (`:164`). Card only when no daily limit or limit < cap. |
| Reconnect card for a model connection | EXTERNAL | `sources.py:799-840` | A run FAILED with HTTP 401/402/403 (`OWNER_FIXES_HTTP`, `:64`); a SUCCEEDED run withdraws it. 404/429/5xx give no card. |
| Seeded reconnect card (Ollama) | CODE_RULE over EXTERNAL results | `seed.py:260-299` | Integration FAILED, or provider AUTH_REQUIRED/OFFLINE, or the last ≥3 of up to 5 runs all FAILED (`:279-284`). |
| Commercial-use card | CONFIG | `seed.py:359-371`, `sources.py:880-915` | `media.factory.vendor_licence(...)["commercial_use"] is not True` on a Runway/ElevenLabs connection, or a licence-ledger component without it. |
| Low-balance card and its need | EXTERNAL | `sources.py:676-754`, `balance_covers` `:1353-1376` | From the balance rule's `needed_credits` / `missing_credits`; a PENDING card with another need is replaced; a WAITING one keeps its words and gets the new need. Cleared by the newest recorded balance reading (after the card) ≥ need. |
| Sheet-repair pause card options | CODE_RULE | `sources.py:971-1065` | Cause LANGUAGE_MODEL_DOWN → «reconnect» (guided); DAILY_LIMIT → «retry» (applier); «local_move» only for blocked LIVE scenes (`_blocked_live_scenes`, `:941-964`); «wait» always. |
| RunPod infra card at boot | CONFIG | `seed.py:374-395` | Real (non-mock) RunPod connection whose config `allow_infra_actions` is not `"true"`. LTX licence card once when any real RunPod connection exists. |
| Mirror-copy card at boot | CONFIG | `seed.py:428-443` | `model_source == "cache"` and a configured endpoint lacks its mirror revision. |
| Start the paid mirror-copy pod | OWNER (his accept is the press) | `sources.py:1236-1260`, card `:458-526` | `pods.start_copy` under the card's cap (`mirror_copy_max_usd` default 5.00 USD, `mirror_copy_max_minutes` 240, providers/runpod/config.py:200-201); a missing token/repo/bucket refuses (`CopyRefused` → card stays PENDING). |
| Let agents switch the RunPod GPU on in approved steps | OWNER | `sources.py:1180-1230` | Sets connection config `allow_infra_actions="true"`, version bump, event `runpod.infra_actions_enabled`; idempotent by inner id. Buys nothing itself. |
| GPU hold raised / lifted | OWNER | providers/runpod/router.py:89-97 (raise), `gpu_hold.py:85-92` (lift) | His «Oprește GPU acum» records the hold and proposes the card; only his «Permite din nou» lifts it (`set_owner_hold(..., False)`). Card closes when the newest hold event says off (`:95-107`). |
| Redo-cap card raised | CODE_RULE | runbook/stages.py:5174-5185 (caller), `redo_cap.py:104-216` | Repair result `limited` and nothing bought, asked or applied; one card per film (`redo-cap:{storyboard}`). |
| How far the paid-redo cap reaches | CONFIG + OWNER | `redo_cap.py:64-79`, `:379-402`; runbook/stages.py:4966-4968 | `film_max_paid_redos_per_scene` (default 5) and `film_max_paid_redos` (default 20) (config.py:314-315) plus the sum of `media.redo_allowance_granted` `extra` for the film. |
| Size of one allowance | CODE_RULE (constant) | `redo_cap.py:50` | `EXTRA_REDOS = 5`, added to both the per-scene and the per-film limit. |
| Redo-cap card moot | CODE_RULE | `redo_cap.py:405-453` | Board missing/REJECTED; an allowance since the card; cap no longer reached when counted again; a PASSED QC report since the card; or a publication of any of the film's assets. Without settings the cap is taken as reached (card stays). |
| Publish a capped film as it is | OWNER | `redo_cap.py:288-337` | `director_qc.accept_film(..., decided_by="owner")`, then `queue_film_continue`. |
| Close a capped film | OWNER, refused by CODE_RULE | `redo_cap.py:340-373` | `director_qc.close_film`; a purchase in flight (`FilmBusy`) refuses the apply. |
| Daily / monthly spending limit | OWNER | economy/router.py:71-76 → `budget.py:150-197`; or a budget card | Limit must be a positive USD sum; retiring is a separate `retire: true` (`budget.py:91-103`); optional `command_id` and `expected_version`. |
| Budget state | CODE_RULE | `budget.py:385-417` | committed = spent + reserved; EXCEEDED if committed > limit; WARNING if committed / limit ≥ `warn_ratio` (default 0.8, `budget.py:84`); else OK. |
| Hold money for a film or refuse | CODE_RULE (OWNER may force) | `budget.py:473-533` | Behind `lock_for_write`: refused if committed + sum > limit of any active budget; `force=True` is the Owner's per-purchase `allow_over_budget` consent (no refusal, still held). A zero sum holds nothing but an exceeded budget still refuses it. |
| Release stale holds | CONFIG | `budget.py:597-626`, workflows/watchdog.py:869-874 | Older than `reservation_ttl_seconds` (default 21,600 s, config.py:380; `DEFAULT_RESERVATION_TTL_SECONDS`, `budget.py:54`). Released, never settled. |
| A film's expected cost (the sum reserved) | CODE_RULE + CONFIG | `budget.py:657-768` | Sheet: narration + max(cap, stills + motion). No sheet: LIVE scenes' stills at the published rate (`cost_plan.load_price_table()`, `:734-739`) + `motion_budget_usd` (12.0, config.py:258) in any environment other than TEST, or `test_max_cost_per_generation_usd` (0.60, config.py:335) × `test_motion_scenes` (2, config.py:330) in TEST (`:740-745`); narration at the dearest active ElevenLabs per-1k price (`:710-717`), marked unpriced when none. |
| May a language-model run start | CONFIG + CODE_RULE | `accountant.py:1098-1158`, called at agents/services.py:781 | Tokens of every run (any outcome) since local midnight ≥ `agent_daily_token_budget` (0 = no ceiling, config.py:419) → BLOCKED_BUDGET (CONFIG, `:1124`, `:1135-1158`); else any active USD budget EXCEEDED → BLOCKED_BUDGET (CODE_RULE over the Owner's limit, `:1125-1127`), except task `reconcile_day` (`BUDGET_EXEMPT_TASKS`, `:1037`), which is exempt from the USD check only. |
| Daily close: escalate or report | CODE_RULE (LLM may only add) | `accountant.py:1257-1297` | ESCALATE if any budget EXCEEDED or WARNING or an open Director budget request (the books), or if the model answered with a structured blocker or `continue_spending: false` (the model can only add); `owner_attention` when exceeded or budget requests (`:1265-1266`, `:1296`). |
| Director's budget requests | CODE_RULE | `accountant.py:1272-1297`, `:1337-1343` | OPEN REQUEST_INFO letters to the Accountant with `budget_request` are attached to the close and RESOLVED as "passed to the Owner; only the Owner sets the budget". |
| Which `provider_price` row prices a call (LLM tokens, TTS characters, the Owner fallback for scene costs) | OWNER over CONFIG | `prices.py:211-234`, `price_lookup` `:242-250` | Active rows only; any OWNER (non-DOCUMENTED) row beats any DOCUMENTED row; then exact id > longest family `prefix*` > `*`. |
| Price rows themselves | OWNER (PUT) / CONFIG (seed) | `prices.py:90-181`, `:298-364` | Only `PUT /economy/prices` or `seed_documented_prices` from `integrations.catalog.DOCUMENTED_PRICES` (three ElevenLabs rows per 1k characters: `*` 0.22 USD, `eleven_flash_*` 0.11 USD, `eleven_turbo_*` 0.11 USD, catalog.py:311-342); seed never overrides any existing row or the Owner's `*` (`prices.py:311-330`). The PUT body may itself name a provenance (OWNER default, DOCUMENTED, QUOTED, BILLED; `prices.py:65`). |
| An LLM run's cost | CODE_RULE | `prices.py:261-278` | Both per-million prices and both token counts known, else None (unpriced, never zero). |
| Measured price of a model | EXTERNAL | `credits.py:176-246`; `accountant.py:559-576` | A Runway balance drop over one step attributed to its takes; a render's `estimated_credits` × the connection's `credit_usd`. Written as `source: measured` on `provider_resource.pricing`. |
| Price-move letter | CONFIG | `accountant.py:567-576`, `:657-696` | Move ≥ `price_change_alert_percent` (default 10.0 %, config.py:446), applied by the callers (`record_render_costs` only when they pass `alert_percent`; media/model_research.py:404-415). On the model-research path the "new" price is the steward model's reading of a vendor page (LLM, media/model_research.py:337-355, :379-384). |
| Whether a scene's shot is charged | CODE_RULE | `accountant.py:395-407` | Only when it came home (`bytes`) or was generated and lost (`paid_but_lost`). |
| Price of a scene purchase | CODE_RULE (over EXTERNAL / catalogue / OWNER prices) | `accountant.py:495-517`; media/production_policy.py:597-642 | Order: credits the vendor named × the connection's `credit_usd`; else the catalogue's `provider_resource.pricing` (`estimate_cost_usd`); else the Owner's `provider_price` table (`_owner_price_usd`); else counted as unpriced. The catalogue row is written by measured renders (`record_measured_price`) and also by the model-research steward from a vendor page (LLM; integrations/discovery.py:771-801 via media/model_research.py:379-401), so the Owner's typed price ranks *below* it here. |
| One cost per (provider, reference) | CODE_RULE + DB | `services.py:747-758`, `models.py:224` | Duplicate refused (`EconomyError`); `_record_priced` treats that as "already booked" (`accountant.py:604-606`). |
| A cost touches the ledger | CODE_RULE | `services.py:776-784` | Only BILLED posts (debit 5000, credit 1000); ESTIMATED never does. |
| An invoice replaces estimates | OWNER + CODE_RULE | `services.py:1235-1574` | Owner-only command; PERIOD (half-open window) or CORRELATION (default key `render_job_id`, `:1155`); a correction requires the current `expected_version` and reverses the previous bill's posting; rows already reconciled or billed are kept as `unmatched` with the reason. |
| Mint VR$ / record Owner funding / FX | CODE_RULE (retired as product) | `services.py:312-693` | Only SETTLED evidence mints, once; a non-USD amount needs a recorded FX snapshot; a loan needs rate and maturity. No route calls these (see Oddities). |
| Letters to the Owner once a day | CODE_RULE | `accountant.py:702-743` | Keyed on `kind` + business date in the studio time zone, behind the write lock. |
| Old test films card | CODE_RULE | `seed.py:585-626` | ≥ `OLD_FILMS_THRESHOLD` = 100 folders in the media root (`seed.py:68`). |
| Editorial QC card | CONFIG | `seed.py:529-565` | While `editorial_qc_blocking` is unset (config.py:186). |
| Paid-rule cards | CODE_RULE (reads the Owner's policy row) | `seed.py:454-526` | Seeded only while `owner_policy.paid_media_approval == EVERY_PAID_STEP` (`:458`); the answer is the Owner's (narration: `record`/`none`; MODE: `none`/applier `paid_media_approval` with `expect`). |

## LLM involvement

### Call site: `app.economy.accountant.reconcile_day` (`backend/app/economy/accountant.py:1188`)

| Item | Value |
|---|---|
| Speaker | The active employee holding the role «Accountant» (`agent_for_role`, `accountant.py:1204`; the earliest-hired ACTIVE agent of the role, app/agents/memory.py:161-168), with her composed identity as system prompt (agents/services.py:790-791). No Accountant → `NoAccountant` (`accountant.py:1205-1206`). The code's comments call her "she" and resolve requests as «Nadia (Accountant)» (`:1339`). |
| Gateway | `app.agents.structured.structured_run` (`accountant.py:1214-1232`) → `run_agent_task` (which first applies `may_run_agent`, agents/services.py:781). |
| Task type / template | `task_type="reconcile_day"`, `TEMPLATE_VERSION = "accountant-v1"` (`:77`); a second attempt is `accountant-v1+think` (no object at all: native thinking on) or `accountant-v1+again` (an object the schema refused: the refusal quoted, JSON mode again) (agents/structured.py:56-57, :109-120, :133). `max_tokens=6000`, `temperature=0.1`; the first and the `+again` attempts ask the provider for JSON (`structured.py:48`, `:133`). |
| What it asks | `_INSTRUCTIONS` (`:1176-1185`): end of day; today's and the month's spend per provider, active budgets with state, unpriced usage are data "computed, not for you to recompute"; say what stands out, what to hold, what the Director should know; return only JSON. The data is `daily_figures` (`:91-125`) serialised to JSON, cut at 12,000 characters (a raw slice, which can end mid-object: see Oddities) and wrapped in `wrap_in_inert_boundary(..., "books")` (`:1209-1211`; app/factual/sanitizer.py:104-112). |
| Answer shape | `AccountantReport` (`:1164-1173`, `extra="ignore"`): `summary` str 1..2000 (clipped, not refused, by `clipped(2000)`), `recommendations` list[str] ≤ 8, `holds` list[str] ≤ 8, `continue_spending` bool (default True). Longer lists and strings are cut before validation by `fit_to_schema` (agents/identity.py:568-584, called from `read_structured`, :603-640), so only a missing/empty `summary` or a wrong type is refused. A structured blocker `{"blocker": {reason, needs}}` (`blocker_of`, agents/identity.py:648-662) outranks the report. |
| What code does with it | **ADVISORY.** Stored in the close message body (`:1261-1262`) and the Accountant's memory (`AGENT_OPINION`, `:1316-1324`). The escalation is decided by the books (`:1256-1257`, `:1286-1297`: exceeded or warning budgets, open Director budget requests); the model can only *add* an escalation, by answering with a structured blocker (`:1257`) or with `continue_spending: false` (`:1263-1264`), never remove one. `holds` are not enforced anywhere: the daily run copies them into the books report (runbook/stages.py:6246-6251) and `file_stage_reports` files it. The message goes to the Director's inbox (`post_message` without `to_owner`, `:1298-1307`). |
| Checks | Schema validation (after `fit_to_schema`); one re-ask by `structured_run` (two attempts at most, agents/structured.py:94-96, :109, :153-154), and only when the first run SUCCEEDED with text that held no valid object: a failed or empty first run is not retried (`structured.py:138-140`). No content check of the summary, recommendations or holds. |
| If the model fails / refuses / returns junk | First run not SUCCEEDED (including a run the gate refused: BLOCKED_BUDGET by the token ceiling, or any other policy refusal) or empty text → `AccountantError` (`:1233-1238`); unparseable after the second attempt and no blocker → `AccountantError("…nu respectă schema; cifrele rămân valabile")` (`:1244-1245`). The router answers 422 (economy/router.py:103-106; `NoAccountant` is an `AccountantError`, `:84`); the daily run logs `daily_close_refused` and files the books as SKIPPED (runbook/stages.py:6239-6253), and does not ask for the close at all when the registry has no language model (`_has_language_model`, stages.py:6239; books SKIPPED «fără model»). The waiting-approvals letter is written *before* the model is asked (`:1196-1199`), so it survives a failed close. A blocker answer is posted as an ESCALATE close with `blocker` and `needs` (`:1259-1260`). |
| Can it lead to spending money? | No. The answer changes only the message intent and stored text. The run itself costs tokens (priced through `cost_vr`); it is exempt from the exceeded-USD-budget refusal (`BUDGET_EXEMPT_TASKS`, `:1035-1037`) but **not** from the token ceiling (`:1124-1158`). |

### Functions that reach the LLM indirectly

| Function | Path to the model |
|---|---|
| `create_economy_router.post_close_day` (`economy/router.py:101`, `POST /api/v1/economy/books/close`) | → `reconcile_day` → `structured_run` → `run_agent_task` (3 hops). The Owner asks for the close outside the daily run. |

Outside this group, the daily run's `_post_run` (runbook/stages.py:6230-6243) is the other caller of `reconcile_day`.

### The LLM gate and the LLM's outcome, both in this group (not call sites)

- `may_run_agent` (`accountant.py:1098`) is called by `run_agent_task` before every model run
  (agents/services.py:771-781). It is the token ceiling and the MONEY-10 stop; its refusal is recorded
  as a BLOCKED_BUDGET run (16_DECISION_LOG.md:2048-2050).
- `decisions.sources.model_run_finished` (`sources.py:799-840`) is called after every run's record is
  written (agents/services.py:1022-1027): an HTTP 401/402/403 from the provider proposes a reconnect
  card; a success withdraws it. Decided by EXTERNAL (the provider's status).

### LLM-written text that enters this group as data (no control effect)

- The Director's QC decision summary is quoted in the redo-cap card's `why_ro`, clipped to 600
  characters (`redo_cap.py:90-101`, `:145-146`). INFORMATIONAL.
- An approval's `evidence` line («the one part of a question written by a model», `accountant.py:980-982`)
  is quoted in the waiting-approvals letter, clipped to 120 characters. INFORMATIONAL.
- The Director's weekly `budget_request` justification is attached to the close, clipped to 500
  characters (`accountant.py:1287-1295`). INFORMATIONAL; the budget is only the Owner's.
- Letters to the Owner (many written by agents) are shown as cards (`services.py:1478-1533`). INFORMATIONAL.
- `price_change_alert` (`accountant.py:657-696`) is also called by the model-research steward
  (media/model_research.py:404-415) with price moves whose "now" figure is the steward model's
  reading of a vendor page (`note.price_usd`, media/model_research.py:379-384). The letter is
  INFORMATIONAL; the same LLM-read figure is written into the model catalogue's
  `provider_resource.pricing` (integrations/discovery.py:771-801), which `_priced_scene_costs`
  uses to price render cost rows before the Owner's `provider_price` table
  (`accountant.py:499-514`). That is an LLM-originated number reaching the books
  (ESTIMATED rows, budgets) through a call site outside this group.
- The Accountant's own close summary is stored as an `AGENT_OPINION` memory (`accountant.py:1316-1324`)
  and so returns in her composed identity on later runs; context only.

### How much of this group is LLM

1 call site among 261 functions (0.4 %), plus 1 route that reaches it. The call site's answer is
advisory and cannot spend. Every refusal, threshold, card, budget state and letter in this group
is deterministic code, a configuration value, an external reading, or the Owner's own act. The
one place a model's number can reach these books is indirect: a render's cost row is priced from
the model catalogue, which the model-research steward (an LLM call site in another group) may
have written from a vendor page; the Owner's `provider_price` rows are only the fallback there
(see «Price of a scene purchase» above).

## Hard rules and limits

| Constant / rule | Value | Where |
|---|---|---|
| Card states | PENDING, ACCEPTED, REFUSED, WAITING_FOR_OWNER_ACTION, WITHDRAWN, EXPIRED; open = PENDING, WAITING | `decisions/models.py:13-23`, DB check `:40-44` |
| One open card per `dedupe_key` | partial unique index | `decisions/models.py:46-51` |
| `dedupe_key` length | 1..200 | `services.py:848-849` |
| Option key / label / effect | `^[A-Za-z0-9_.\-]{1,60}$`; 1..200; ≤ 2000 | `services.py:161-169` |
| Recommended options per card | ≤ 1, sorted first; keys unique; ≥ 1 option | `services.py:783-815` |
| Guided option | must name `place` (a `SETTINGS_TABS` key) or `place_ro` | `services.py:797-806` |
| `DecideCommand` | `schema_version` 1, `command_id` UUID, `expected_version` ≥ 1, decision ACCEPT/REFUSE/DONE, `option_key` ≤ 60, `note` ≤ 500, extra fields forbidden | `services.py:147-158` |
| Answer transitions | ACCEPT←PENDING; REFUSE←PENDING/WAITING; DONE←WAITING | `services.py:1112-1116` |
| Inner command id | `uuid5(NAMESPACE_URL, "amn-ai:owner-decision:{id}:v{version}:{option}")` | `services.py:1105-1109` |
| Condition readings | MET / UNMET / UNREADABLE (fail closed) / ONLY_OWNER | `services.py:630-652` |
| Registered names | `^[a-z][a-z0-9_]{0,59}$`; a second owner of a name is refused | `services.py:221`, `:240-261` |
| Plain option types | `none`, `record`, `guided` | `services.py:95-99` |
| Refusal quiet period | 7 days | `sources.py:60` |
| HTTP statuses that make a reconnect card | 401, 402, 403 | `sources.py:64` |
| Budget card step | whole 5 USD, rounded up | `sources.py:76`, `seed.py:65` |
| Budget refusals that make a film card | OVER_DAILY_BUDGET, BLOCKED_NO_BUDGET | `sources.py:78` |
| Sheet-repair pause causes | LANGUAGE_MODEL_DOWN, DAILY_LIMIT | `sources.py:81` |
| Audit reference film | 4 scenes × 10.0 s, people, scene 1 HERO | `seed.py:62-63`, `:138-146` |
| Old test films threshold / scan limit | 100 folders / 200,000 files | `seed.py:68`, `:70` |
| Licence files looked for | LICENSE, LICENSE.md, LICENSE.txt, EULA.md, EULA.txt | `seed.py:73` |
| Paid-redo allowance per accept | 5 (per scene and per film) | `redo_cap.py:50` |
| Paid-redo caps | 5 per scene, 20 per film (Settings, bounded at 5 and 20); fallback in code 1 and 2 | config.py:314-315; `redo_cap.py:397-398` |
| History shown in the window | 50 | `services.py:1565` |
| Asking letter intents shown as cards | REQUEST_INFO, REQUEST_REVIEW, CHALLENGE, ESCALATE | `services.py:1475` |
| Budget periods | DAILY, MONTHLY; one active row each (kept by code: `_apply_budget` deactivates the previous row, `budget.py:233-239`; the table has only a non-unique index) | `budget.py:49`, `models.py:327-353` |
| Budget limit | > 0 micros (DB check); `warn_ratio` 0.1..1.0, default 0.8 | `models.py:338`, `budget.py:84` |
| Period start | local midnight (or local 1st) in the studio time zone, as UTC | `budget.py:120-132` |
| Reservation TTL | 6 h (`DEFAULT_RESERVATION_TTL_SECONDS`), settable 60..86,400 s | `budget.py:54`, config.py:380 |
| Reservation states | RESERVED → SETTLED or RELEASED; `usd_micros > 0` | `models.py:428-431` |
| Money unit | integer micros, 1 USD = 1 VR$ = 1,000,000 | `models.py:43`; `to_micros` rounds half away from zero (`services.py:144-163`) |
| Price units | per_1k_characters, per_1m_input_tokens, per_1m_output_tokens, per_second, per_generation | `models.py:358-364` |
| Price provenances | OWNER, DOCUMENTED, QUOTED, BILLED | `models.py:368` |
| Price amount | `^\d{1,9}(\.\d{1,6})?$`; 0 allowed (a free unit is a fact) | `prices.py:62-64` |
| Agent token ceiling | `agent_daily_token_budget`, default 0 = none | config.py:419 |
| Exempt from the exceeded-USD refusal | task `reconcile_day` | `accountant.py:1037` |
| Price-change alert | ≥ 10.0 % by default | config.py:446 |
| Published films in the figures | 8 | `accountant.py:224` |
| Figures in the close prompt | ≤ 12,000 characters | `accountant.py:1210` |
| Close answer | summary ≤ 2000, ≤ 8 recommendations, ≤ 8 holds (over-long values are cut, not refused: `clipped`, `fit_to_schema`) | `accountant.py:1164-1173`; agents/identity.py:377-390, :568-584 |
| Documented price seed | ElevenLabs per 1k characters: `*` 0.22, `eleven_flash_*` 0.11, `eleven_turbo_*` 0.11 USD | integrations/catalog.py:311-342 |
| Cost statuses | ESTIMATED (never posted), BILLED (posted); `amount_micros > 0`; unique (provider, reference) | `models.py:222-228` |
| Reconciliation scopes | PERIOD (half-open), CORRELATION (default key `render_job_id`) | `services.py:1150-1155` |
| Replay moments | ≤ 240 per call | `as_of.py:50` |
| Mirror-copy cap | 5.00 USD, 240 min (defaults) | providers/runpod/config.py:200-201 |

**State machine of a decision card** (`services.py:1174-1325`, `:891-991`, `:1031-1087`):

```
PENDING --ACCEPT(applier ok | none | record)--> ACCEPTED
PENDING --ACCEPT(guided, condition unmet)-----> WAITING_FOR_OWNER_ACTION
PENDING --ACCEPT(guided, condition MET)-------> ACCEPTED (completed_by condition)
PENDING --ACCEPT(applier refuses)-------------> PENDING (+ apply_error_ro, owner.decision_apply_failed)
PENDING --REFUSE------------------------------> REFUSED
PENDING --condition MET (refresh / withdraw)--> WITHDRAWN
PENDING --expires_at passed-------------------> EXPIRED
WAITING --DONE (MET or ONLY_OWNER)------------> ACCEPTED (done_reading)
WAITING --DONE (UNMET / UNREADABLE)-----------> WAITING (+ still_missing_ro)
WAITING --condition MET (refresh / withdraw)--> ACCEPTED (completed_by condition)
WAITING --REFUSE------------------------------> REFUSED
ACCEPTED (guided, unverified pre-2026-10-04 DONE) --seed--> WAITING (once, owner.decision_reopened)
```

## Modules

### `app.decisions` — backend/app/decisions/__init__.py (1 line)

Package docstring only: «The Owner's decisions window: cards he accepts or refuses (2026-10-03).» No functions.

### `app.decisions.models` — backend/app/decisions/models.py (85 lines)

The `owner_decision` table (migration 0054). `OwnerDecision` (`:25-85`): `kind`, `subject_type`/`subject_id`,
`title_ro`, `why_ro`, `effect_ro`, `options` (JSON list, recommended first), `clears_when` (JSON or
None), `source` («audit», «agent:<id>», «stage:<name>»), `dedupe_key`, `status`, `chosen_option`,
`note`, `decided_by`, `decided_at`, `applied` (JSON: what the answer did), `apply_error_ro`,
`expires_at`, `version`, `created_at`, `updated_at`, `event_id`. Constants `DECISION_STATUSES` (`:13`),
`OPEN_STATUSES` (`:22`). No functions.

### `app.decisions.producers` — backend/app/decisions/producers/__init__.py (62 lines)

`PRODUCERS = PackageLoader(__name__)` (`:60`): the first read of `APPLIERS`, `CONDITIONS` or
`MISSING_RO` imports every module of this package (app/registry_loader.py). The docstring
(`:1-53`) is the rule book for a producer module: importing only registers; an applier runs one of
the Owner's own commands under the inner id and raises `DecisionApplyFailed` when it refuses; it
"never buys, approves or moves money by itself"; a condition only reads; a name is registered once;
a module whose import fails leaves nothing registered; it never answers in the Owner's name
(`:48-52`; enforced by the Owner boundary scan, tests/test_watchdog_passes.py:685-703). No functions.

### `app.decisions.producers.gpu_hold` — backend/app/decisions/producers/gpu_hold.py (117 lines)

The card that follows the Owner's «Oprește GPU acum» (2026-10-12). Kind `gpu_owner_hold`, key
`gpu-owner-hold`, source `runpod` (`:36-38`). One option «Permite din nou pașii plătiți», not
recommended, no «keep» option: while unanswered the hold stands (`:11-14`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `propose_gpu_hold_card` | 46 | Proposes the card in its own transaction (`clears_when` `gpu_hold_lifted` since now); returns the card id or None; never raises into the button. | The hold needs a way back that only the Owner presses. | OWNER (his button, providers/runpod/router.py:89-97) |
| `apply_gpu_hold_lift` | 85 | His accept: `gpu_session.set_owner_hold(engine, False, by="owner", command_id=inner)`. | Lifts the hold on the record; paid steps may switch the GPU on again under his rule, budgets and the film ceiling. | OWNER |
| `gpu_hold_lifted` | 95 | Condition: the newest `OWNER_HOLD_EVENT` payload says `on` false. | Closes the card if the hold was lifted another way. | CODE_RULE |

Registers applier `gpu_hold_lift` and condition `gpu_hold_lifted` (`:110-115`). Reads `domain_event`; writes the card; the lift writes the hold event (in providers.runpod.gpu_session). No money moves here.

### `app.decisions.producers.redo_cap` — backend/app/decisions/producers/redo_cap.py (475 lines)

The Owner's card when the Director's paid repair of a film is stopped by his paid-redo cap
(2026-10-12). Kind `redo_cap_reached`, source `director_qc`, key `redo-cap:{storyboard_id}`.
Options: **allow** (recommended; +5 redos per scene and per film), **publish** (as it is), **close**,
**wait** (`:147-197`). Nothing here buys (`:21-22`). Since 20abffd, when every candidate of a still
round is refused (the rounds of her paid scene redo included: `assembler._redo_still_rounds` →
`stills_stage._StillRounds` → `_settle_round`) or a bought clip is refused, the Director gets a
free second look before a re-roll or retry is bought, and a refusal she overturns buys nothing
more (`backend/app/media/stills_stage.py:1143-1149`, `backend/app/media/qc.py:2670-2683`; the
bible's hard limits stay the code's, `backend/app/media/fix_check.py:130`); the cap, its count and
this card are unchanged.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `dedupe_key` | 60 | `redo-cap:{storyboard_id}`. | One card per film. | CODE_RULE |
| `redo_allowance` | 64 | Sums `extra` of every `media.redo_allowance_granted` event of the film (negatives and junk ignored). | The cap in runbook/stages.py:4966-4968 and `cap_still_reached` add it to the Owner's settings. | OWNER (his past accepts) |
| `propose_redo_cap_card` | 104 | Builds the card from the limited scenes, per-scene/per-film caps, rounds spent, the film title and the Director's QC summary; own transaction; returns card id or None (logged, never raises). No scenes → None. | Turns a cap-stopped repair into one question for the Owner instead of an hourly loop. | CODE_RULE (when), OWNER (answer) |
| `apply_redo_allowance` | 241 | Behind `lock_for_write`: writes `media.redo_allowance_granted` (`extra`, `granted_by: owner`, `correlation_id = inner`) unless one with that inner id exists; queues `queue_film_continue` with key `film-continue-{sb}-redo-cap-{inner}`. | His «allow»: moves his cap for this film only; the purchase stays behind may_act, budgets and the film ceiling. | OWNER |
| `apply_film_publish_as_is` | 288 | Reads the QC report (missing → refuse), calls `director_qc.accept_film(..., decided_by="owner")` with an Owner summary, queues the film's continuation. | His «publish as it is»: his ACCEPT carried out as the Director's would be. | OWNER |
| `apply_film_close_capped` | 340 | `director_qc.close_film` with a CLOSE decision by the Owner; `FilmBusy` → `DecisionApplyFailed`. (The module docstring, `:17`, still names `media.film_close.close_film`.) | His «close»: a rendered film retires through the Director's path (his own CloseFilm refuses rendered films, `:343-345`). | OWNER; CODE_RULE refusal |
| `cap_still_reached` | 379 | Counts paid rounds again (`runbook.stages._paid_redo_rounds`) against settings + allowance; per film ≥ limit, or a named scene ≥ per-scene limit; no settings → True. | 2026-10-12: a card raised on a miscount is moot, not his to answer (`:387-390`). | CODE_RULE + CONFIG |
| `redo_cap_cleared` | 405 | Condition: board gone/REJECTED; allowance since the card; cap not reached; a PASSED report since the card on any of the film's render assets; or a publication of one. | Closes the card when the question went away. | CODE_RULE |

Helpers: `_title_of` (`:82`, board title ≤ 120 chars), `_director_summary` (`:90`, newest `director_qc.DECISION_EVENT` summary ≤ 600 chars — LLM-written text), `_continuation` (`:230`, `queue_film_continue`).
Registers appliers `redo_allowance`, `film_publish_as_is`, `film_close_capped` and condition `redo_cap_cleared` (`:456-466`).
Data: reads `storyboard`, `quality_control_report`, `video_render_job`, `publication_record`, `domain_event`; writes `media.redo_allowance_granted` events and FILM_CONTINUE tasks. Spending: none directly; an allowance re-enables paid redos.

### `app.decisions.router` — backend/app/decisions/router.py (64 lines)

Prefix `/owner`, every route behind `require_owner`; mounted under `/api/v1` (app/main.py:991).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `create_decisions_router` | 24 | Builds the router. | — | — |
| `get_decision_cards` — `GET /api/v1/owner/decision-cards` | 28 | `owner_decision_cards(engine, settings, include_history=history)`. Note: refreshes (writes) closed cards first. | The «Decizii (N)» window's feed. | — |
| `post_decide` — `POST /api/v1/owner/decisions/{decision_id}/decide` | 38 | `decide_owner_decision(..., issued_by=OWNER)`; 404 missing, 409 conflict, 403 refused, 422 apply failed / invalid. | The only way a card is decided. | OWNER |

### `app.decisions.services` — backend/app/decisions/services.py (1659 lines)

The decisions core: three verbs (propose, withdraw, decide), the registries of appliers and
conditions, the condition reader, the window's feed. Atomicity note (`:30-35`): the apply and the
card's transition are two commits; the inner command id makes a retry safe.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_ProducerRegistry.*` (`__getitem__`, `__contains__`, `get`, `__iter__`, `__len__`, `keys`, `values`, `items`) | 181-217 | A dict whose every read first calls `PRODUCERS.load()`. | Producer modules register on first read without import cycles. | — |
| `_same_function` | 224 | Same object, or same module + qualname (not `<locals>`). | A module imported twice is not a second owner of a name. | CODE_RULE |
| `_register` | 240 | Validates the name, refuses a name owned by another function, records the entry with `PRODUCERS.added`. | Two producers answering one option type would make the accept run whichever loaded last. | CODE_RULE |
| `_recorded` | 272 | The stored response of a command id. | Idempotent appliers. | — |
| `_policy` | 279 | Reads `owner_policy` row 1, or refuses. | Appliers need the policy version. | — |
| `_expect` | 288 | Refuses if `spec.expect` ≠ current value. | His yes was about the state on the card. | CODE_RULE |
| `_apply_budget` | 298 | Builds a `BudgetCommand` (inner id as command id, card's `expected_version`) and calls `set_budget(..., set_by="owner")`. | Budget cards apply through his budget command. | OWNER |
| `_apply_paid_media` | 329 | Checks `expect`, calls `change_paid_media_approval(..., issued_by=OWNER)` with the policy version; conflicts → refusal. | The «treci la MODE» option. | OWNER |
| `_apply_policy` | 365 | Factory: `change_environment` or `change_autonomy_mode` with `expect` and version. | Environment and autonomy-mode options. | OWNER |
| `_from_sources` | 417 | Lazily resolves an applier defined in `decisions.sources`. | Avoids an import cycle. | — |
| `register_applier` | 456 | Adds an option type (not none/record/guided). | Producer modules' entry point. | — |
| `_integration_verified` | 471 | Condition: connection gone, or VERIFIED/ACCESS_VERIFIED and checked after the card, or its newest run SUCCEEDED after the card. | Reconnect cards close on proof. | EXTERNAL |
| `_youtube_connected`, `_commercial_use`, `_music_library_has_music`, `_daily_budget_at_least`, `_paid_media_approval_is_not`, `_setting_is_set`, `_media_folders_below`, `_file_exists`, `_never` | 500-585 | The core's conditions: all YouTube connections CONNECTED; `vendor_licence(...).commercial_use is True` (or connection gone); a music track in the library; active DAILY limit ≥ `usd_micros`; policy ≠ value; a settings attribute not None (no settings → False); media folders < count; any named file exists at ROOT; always False. | What the studio reads to know a question went away. | CODE_RULE / CONFIG |
| `media_folder_count` | 559 | Counts directories under the media root (read only; 0 on OSError). | The old-test-films card. | — |
| `_condition_from_sources` | 588 | Lazily resolves a condition defined in `decisions.sources`. | Import cycle. | — |
| `condition_reading` | 637 | Reads `clears_when`: ONLY_OWNER, UNREADABLE (unknown type or exception, logged), MET, UNMET. | Fail closed: a card never vanishes on an error. | CODE_RULE |
| `condition_cleared` | 655 | `condition_reading == "MET"`. | — | CODE_RULE |
| Missing-words helpers `_missing_commercial_use`, `_missing_file`, `_missing_budget`, `_missing_words` | 676-701 | The Romanian "still missing" sentence per condition. | His DONE never gets a bare «not yet». | — |
| `register_condition` | 749 | Adds a condition with its required missing words. | Producer entry point. | — |
| `still_missing_ro` | 764 | None when MET/ONLY_OWNER; the UNREADABLE sentence; or the lead + the condition's words. | — | CODE_RULE |
| `_checked_options` | 783 | Validates options (pydantic), known apply types, guided place, unique keys, ≤ 1 recommended; recommended first. | A malformed card is refused at proposal time. | CODE_RULE |
| `_open_card` | 818 | The open card of a key. | Dedupe. | — |
| `propose_owner_decision` | 826 | Validates, returns the standing open card of the key unchanged, else inserts a PENDING card in a savepoint (IntegrityError → the racing card). Writes no ledger event. | "Proposing decides nothing" (`:843`); open to agents, stages and the audit. | CODE_RULE |
| `_transition` | 891 | Status + version + event + `event_id`. | Every closing transition is in the event log. | — |
| `_close_by_condition` | 910 | WAITING → ACCEPTED (completed by condition) or PENDING → WITHDRAWN, with reason. | — | CODE_RULE |
| `withdraw_owner_decision` | 932 | Closes an open card by key or id in the caller's transaction. | "Withdrawing a question is not deciding it" (`:941`). | CODE_RULE (caller's observation) |
| `refresh_owner_decisions` | 961 | Reads open cards; expires aged PENDING ones; closes those whose condition is MET; writes only if something moved and only if the version did not move meanwhile. | Cards close themselves when the situation clears. | CODE_RULE |
| `_closed_by_unconfirmed_done`, `_asked_again` | 1001, 1016 | Identify a pre-2026-10-04 DONE without `done_reading`; a newer card with the same key. | Re-open only what was wrongly closed, never over a newer answer. | CODE_RULE |
| `reopen_unconfirmed_done` | 1031 | Re-opens such cards once to WAITING with what is still missing (`owner.decision_reopened`, by «seed»). | 2026-10-03: three cards closed by DONE with nothing done. | CODE_RULE |
| `_lock` | 1093 | `UPDATE owner_policy SET id=1` — the Owner commands' serialisation point. | One answer at a time. | — |
| `_recall` | 1098 | `recall_command`; reuse with another body → `DecisionConflict`. | Idempotence. | CODE_RULE |
| `_inner_command_id` | 1105 | Deterministic uuid5 of card, version, option. | No double apply on retry. | CODE_RULE |
| `_check_answerable` | 1119 | Exists, status allowed, version matches. | — | CODE_RULE |
| `_chosen_option` | 1137 | Option by key, or the recommended / sole option. | — | CODE_RULE |
| `_record_apply_error` | 1153 | Stores `apply_error_ro` and an `owner.decision_apply_failed` event on a still-PENDING card. | His failed accept is visible with its reason. | — |
| `decide_owner_decision` | 1174 | (1) owner only; (2) tx 1: lock, recall, check, choose option; (3) refuse unknown applier types; (4) run the applier outside the transaction; (5) tx 2: lock, recall, re-check, compute status (REFUSE / DONE with condition / applier / guided / record / none), store chosen option, note, `decided_by="owner"`, `applied`, emit `owner.decision_decided` (names the applied command and its event), remember the command. | The only way a card is decided; the Owner's commands run with their own validation, version and event. | OWNER |
| `decision_view` | 1331 | The card as the window reads it (options without internals beyond type/place/steps). | — | — |
| `_decision_card` | 1380 | Card shape + answer path `/api/v1/owner/decisions/{id}/decide`. | One card shape for three sources. | — |
| `_approval_card` | 1403 | A paid-step approval as a card; answered through `POST /api/v1/owner/approvals/decision` (no logic repeated). | The window shows paid steps beside cards. | — |
| `_letter_card` | 1478 | An asking letter as a card (reply / resolve through the letters' routes). | Questions in letters reach the same window. | — |
| `_covered_by_card`, `_answered_approvals` | 1536, 1543 | A letter whose (kind, storyboard) an open card already asks; the last answered approvals for history. | One question, one place. | — |
| `owner_decision_cards` | 1560 | Refresh (errors logged), then: PENDING approvals + open cards + open asking letters not covered by a card, newest first; `count` = approvals + PENDING cards + WAITING cards + letters; history of closed cards and answered approvals (≤ 50). | The «Decizii (N)» button and window. | — |

Data: reads/writes `owner_decision`; writes `domain_event` (`owner.decision_decided`, `_apply_failed`, `_withdrawn`, `_completed`, `_expired`, `_reopened`) and `command_record`; reads `approval_request`, `agent_message`, `owner_policy`, `integration`, `agent_run`, `provider_record`, `youtube_connection`, `spending_budget`, the media root and project-root files. External calls: none here; appliers may (RunPod pod start, see `sources`).

### `app.decisions.sources` — backend/app/decisions/sources.py (1376 lines)

The studio's own places that meet an Owner-only question: shared dedupe keys, card builders (also
used by the seed), producers called from the run, the agents, YouTube, the licence ledger, the
assembler and the sheet repair, plus the appliers and conditions they need. Rules (`:27-33`): only
propose; one open card per condition; withdraw when it clears; a refusal stays quiet 7 days; a
producer never breaks the caller (savepoint or own transaction).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| Key builders `reconnect_key`, `youtube_key`, `commercial_use_key`, `film_budget_key`, `sheet_repair_key`, `low_balance_key`, `runpod_infra_key`, `runpod_mirror_copy_key` | 92-135 | `reconnect:{id}`, `reconnect_youtube:{id}`, `commercial_use:{id}`, `daily_budget:film:{sb}`, `sheet_repair_paused:{sb}:{cause}`, `low_balance:film:{sb}`, `runpod_infra_actions:{id}`, `runpod_mirror_copy:{id}`; also `MUSIC_KEY`, `RUNPOD_LTX_KEY`. | One key per question, shared with the seed. | CODE_RULE |
| `_when` | 141 | ISO → aware datetime or None. | — | — |
| `_refused_lately` | 149 | Newest card of the key REFUSED, or ACCEPTED by the owner with apply type `none`, within 7 days. | His no stands; a failing connection does not re-ask hourly. | CODE_RULE |
| `ask` | 173 | `propose_owner_decision` unless refused lately. | The producers' door. | CODE_RULE |
| `_safely`, `_own_transaction` | 182, 193 | Savepoint in the caller's tx (failure logged, swallowed); or an own tx behind `lock_for_write`. | A card is never worth the work that found it (`:188`). | — |
| `_usd` | 206 | Micros as «15», «7,40». | — | — |
| `reconnect_card` | 216 | Guided card, place `llm`, steps differ for HTTP 402; clears on `integration_verified`. | Model connection refused. | — |
| `youtube_card` | 248 | Guided card, place `social`; clears on `youtube_channel_connected`. | Google refused a channel. | — |
| `vendor_label` | 278 | «Runway («name»)». | Two connections may share a name. | — |
| `commercial_use_card` | 282 | Guided card, place `media`; clears on `commercial_use`. | Films stay NEEDS_REVIEW/private without his statement. | — |
| `runpod_infra_card` | 315 | Options «yes» (applier `runpod_infra`, recommended) / «not_yet»; clears on `runpod_infra_enabled`. | 2026-10-08: no paid step may switch the GPU on without his consent (≤ 1 GPU, 4 USD/h, off right after). | — |
| `runpod_ltx_licence_card` | 354 | Guided Hugging Face licence step / «without»; `clears_when: never`. | Only his HF account can accept the gated LTX-2.5 licence. | — |
| `runpod_weights_card` | 399 | Guided console step / «keep_off»; `never` with the expected revision. Used by providers/runpod/weights.py:240-245. | An endpoint proved other weights than his mirror (2026-10-09). | — |
| `runpod_mirror_copy_card` | 458 | Options «yes» (applier `runpod_mirror_copy` with images, `max_usd`, `max_minutes` from `RunPodConfig`) / «not_yet»; clears on `runpod_mirrors_ready`. The effect text warns the HF token is visible in the pod's env. | The one-time copy of weights into his private mirrors; "his accept IS the press" (`:459-460`). | — |
| `music_card` | 529 | Guided `config/music_library.json` / «without»; clears on `music_library_has_music`. | Empty library. | — |
| `_active_daily_limit` | 568 | Active DAILY limit micros or None. | — | — |
| `film_budget` | 579 | Withdraws the film's budget card unless the refusal is a budget one; else, when the step cap can never fit a day, asks «raise to N USD» (applier `budget`, with the period's `budget_version`) or «keep»; clears on `daily_budget_at_least` step cap. Called from runbook/stages.py:2427, :2922. | A film waiting on the daily budget is his decision only when no day can ever fit it (`:587-590`). | CODE_RULE |
| `film_low_balance` | 676 | Card «top up Runway with at least N credits» (guided) / «wait»; replaces a PENDING card whose need changed; updates a WAITING card's need. Called from media/shooting_sheet.py:3593. | The Owner's balance rule of 2026-10-03. | EXTERNAL |
| `_open_low_balance_card`, `_card_need` | 757, 766 | Open card of the film; `clears_when.credits`. | — | — |
| `film_balance_covered` | 772 | Withdraws the card when a step started on a balance ≥ the card's need. | — | EXTERNAL |
| `_without_class` | 794 | Strips "ProviderHTTPError: ". | — | — |
| `model_run_finished` | 799 | After each run: SUCCEEDED withdraws the connection's reconnect card; FAILED with 401/402/403 asks it. Called from agents/services.py:1025. | Only the Owner fixes keys and plans. | EXTERNAL |
| `youtube_refused`, `youtube_reconnected` | 846, 863 | Ask / withdraw the channel's reconnect card (callers: youtube/services.py:535, :572, :646, :719; analytics/services.py:341). | — | EXTERNAL |
| `film_needs_review` | 880 | One commercial-use card per connection whose component lacks `commercial_use`; returns ids. Called from media/assembler.py:6251. | Licence ledger NEEDS_REVIEW. | CONFIG |
| `music_library_empty`, `film_without_music` | 921, 934 | The music card when a film was mixed with no music (media/assembler.py:5865). | — | CONFIG |
| `_blocked_live_scenes`, `_scene_words` | 941, 967 | LIVE scenes named by the sheet's blockers; «scena 3» / «scenele 2, 4». | Only a filmed scene can take the local move. | CODE_RULE |
| `sheet_repair_paused` | 971 | Card per (sheet, cause) with reconnect/retry, optional local move, wait; clears on `sheet_repair_resumed`. Called from media/blocker_repair.py:274. | The automatic sheet repair paused (LLM down or daily limit). | CODE_RULE |
| `sheet_repair_resumed` | 1068 | Withdraws both causes' cards (media/blocker_repair.py:301). | — | CODE_RULE |
| `apply_sheet_repair_retry` | 1086 | `blocker_repair.allow_repair_retry(..., issued_by=OWNER, fingerprint=...)`. | His «try again now» (LLM work only, nothing bought). | OWNER |
| `apply_sheet_local_move` | 1110 | Verifies every named scene is still LIVE, then `set_scene_model(..., LOCAL_MOVE, issued_by=OWNER)` for those not already local. | His «animate locally» (0 credits for motion). | OWNER; CODE_RULE refusal |
| `apply_runpod_infra` | 1180 | Behind the write lock, idempotent by inner id: `allow_infra_actions="true"`, version bump, `runpod.infra_actions_enabled`, remembered command. | His yes to the RunPod card. | OWNER |
| `apply_runpod_mirror_copy` | 1236 | Opens the credential vault and calls `providers.runpod.pods.start_copy(...)` with the card's cap; `CopyRefused` → refusal. | Starts a paid temporary pod (money). | OWNER |
| `apply_runpod_unsent_release` | 1263 | `media.runpod_unsent.apply_release`. | Release a scene held by a /run with no job id (buys and sends nothing). | OWNER |
| `runpod_unsent_hold_cleared` | 1274 | `media.runpod_unsent.hold_cleared(hold_event_id)`. | — | CODE_RULE |
| `runpod_mirrors_ready` | 1286 | Connection gone, not reading the cache, or every configured endpoint knows its mirror revision. | — | CONFIG |
| `runpod_infra_enabled` | 1308 | Connection gone or `allow_infra_actions == "true"`. | — | CONFIG |
| `youtube_channel_connected` | 1321 | CONNECTED and connected/checked after the card. | A statistics refusal leaves it CONNECTED; only a new Google answer clears it. | EXTERNAL |
| `sheet_repair_resumed_condition` | 1338 | No OPEN pause letter of the sheet. | — | CODE_RULE |
| `balance_covers` | 1353 | Newest `BALANCE_READ_EVENT` after the card has `credits ≥` the card's need (read from the books, never the vendor). | — | EXTERNAL (recorded) |

Data: writes `owner_decision` (through the core), integration config (`apply_runpod_infra`), events.
External: `apply_runpod_mirror_copy` starts a RunPod pod (paid, capped).

### `app.decisions.seed` — backend/app/decisions/seed.py (701 lines)

The production audit of 2026-10-02 (ac07033) left Owner-only questions; `seed_owner_decisions` puts
each in his window once, only when the studio's state says it still stands (`:1-23`). Called at
start-up (app/main.py:303-310) and after a successful Settings save of an integration
(app/integrations/router.py:130-134).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_usd` | 76 | Micros as «15», «27,92». | — | — |
| `_documented_capabilities` | 82 | `ModelCapability` list from `config/film_models.json` (quality default 0.5, `owner_allowed` from the catalogue). | A studio whose Runway connection lists no models. | CONFIG |
| `cheapest_capable_film` | 108 | Plans the reference film on the Runway capabilities (or the catalogue) and `cost_plan.load_price_table()`; returns models, credits, expected cost, cap; None when unpriceable (never a guess). | The budget card's figure is computed, never a constant. | CODE_RULE + CONFIG |
| `_budget_cards` | 185 | Daily-budget card when no limit or limit < the film's cap; options «raise» (applier `budget`) / «cheaper» (guided). Seeded only if the key `audit:daily_budget` never existed. | — | CODE_RULE |
| `_llm_cards` | 260 | Reconnect card per failing Ollama connection. | — | CODE_RULE over EXTERNAL |
| `_youtube_cards` | 302 | Reconnect card per non-CONNECTED channel; plus `google_oauth_production` (guided, `never`). | Testing consent screen expires in 7 days; private uploads without the API audit. | CODE_RULE |
| `_commercial_cards` | 359 | Commercial-use card per Runway/ElevenLabs connection without it. | — | CONFIG |
| `_runpod_cards` | 374 | Infra card, mirror-copy card per real RunPod connection; LTX licence card once. | — | CONFIG |
| `_runpod_unsent_cards` | 398 | `media.runpod_unsent.release_cards`; failure logged. | — | CODE_RULE |
| `_settle_runpod_unsent` | 411 | Before the cards: `settle_proven_holds` releases holds a later round's proof covered (local writes). | — | CODE_RULE |
| `_needs_mirror_copy` | 428 | `model_source == "cache"` and an endpoint lacks its revision. | — | CONFIG |
| `_music_cards` | 446 | Music card when the library has no music. | — | CONFIG |
| `_paid_rule_cards` | 454 | While EVERY_PAID_STEP: «narration as an asked paid step» (record / none) and «when to move to MODE» (keep recommended / applier `paid_media_approval` to MODE with `expect`). | Narration (~0.10 USD per film) is bought unasked; spec 51 change needed. | OWNER policy |
| `_editorial_cards` | 529 | Editorial QC advisory (recommended, none) or blocking (guided `.env`). | — | CONFIG |
| `_folder_size_gb` | 568 | Size of the media root, at most 200,000 files. | — | — |
| `_old_film_cards` | 585 | Old test films card at ≥ 100 folders (archive guided / keep). | The studio never moves or deletes them itself. | CODE_RULE |
| `_sale_terms_cards` | 629 | LICENSE/EULA card when none exists at ROOT. | Sale terms are his, ideally with a lawyer. | CODE_RULE |
| `_ever_seen` | 662 | Any card of the key, in any state. | "Once is literal". | CODE_RULE |
| `seed_owner_decisions` | 671 | Re-open unconfirmed DONEs, settle proven RunPod holds, gather proposals, propose those never seen. | — | CODE_RULE |

External calls: none (reads DB, config files, the media folder). Money: none.

### `app.economy` — backend/app/economy/__init__.py (6 lines)

Docstring only; deliberately re-exports nothing. No functions.

### `app.economy.accountant` — backend/app/economy/accountant.py (1359 lines)

The Accountant's desk: figures computed from the books, cost rows for renders, the deterministic
letters to the Owner, the per-run token/budget gate, and the daily close (the group's only LLM
call site).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `daily_figures` | 91 | `budget_status` + today's and the month's spend with unpriced usage per model + budgets + the last 8 published films' costs + the "agent cost not attributed" note. Also served by `GET /economy/books/daily` and fed to the Accountant's mail answers (agents/mail.py:210-227). | Everything she reads before saying a word. | CODE_RULE |
| `_with_unpriced` | 128 | Adds unpriced tokens and `unpriced_by_model` to a period's spend. | Kept out of `spend_since`, the money gate every run passes (`:129-132`). | — |
| `unpriced_by_model` | 144 | SUCCEEDED runs without cost since a moment, grouped by provider and model, with whether an active price now covers them and their value at it. Read only. | 2026-10-11: 167 unpriced runs before the Owner's Ollama price. | CODE_RULE |
| `published_film_costs` | 233 | For each published film: `film_spend_micros` split into ESTIMATED, RECONCILED, BILLED, held; rejected sibling boards of the topic; latest views. | 2026-10-11: the Accountant wrote cost "cannot be attributed" while 4.58 USD stood in the books. | CODE_RULE |
| `_rejected_attempts` | 306 | Boards of the same topic, REJECTED, between the previous non-rejected board and this one. | Attempts paid for this film. | CODE_RULE |
| `_film_booked_micros` | 334 | Cost rows per status for the board or its renders (narration rows without a board); reconciled rows as RECONCILED. | — | CODE_RULE |
| `_owner_price_usd` | 377 | The Owner's price row × quantity for voice/image/motion when the catalogue has none. | Live ElevenLabs models carry no catalogue price. | OWNER (price) |
| `motion_was_bought` | 395 | `bytes` or `paid_but_lost`. | A refused shot cost nothing. | CODE_RULE |
| `_priced_scene_costs` | 410 | Per scene: voice (characters bought this render), still (scene's own vendor), motion (only if bought; credits, else seconds). Price order (`:495-517`, production_policy.estimate_cost_usd): vendor-named credits × `credit_usd`; else the catalogue's `provider_resource.pricing` (written by measured renders and by the model-research steward, an LLM); else the Owner's `provider_price` row (`_owner_price_usd`); else counted unpriced. Also collects measured (USD, seconds) per motion model. | Shared by finished and failed renders so a scene is charged once. | CODE_RULE |
| `record_render_costs` | 537 | Prices a render; writes measured per-second prices (`record_measured_price`) and alerts above `alert_percent`; books ESTIMATED rows `render:{job}:scene:{n}:{unit}`. Callers: runbook/stages.py:2714, :3594; media/shooting_sheet.py:4033; media/router.py:682. | One price per what was bought; re-runs never charge twice. | CODE_RULE + EXTERNAL |
| `_record_priced` | 587 | `record_provider_cost(..., status="ESTIMATED")` per row; a duplicate is skipped. | — | CODE_RULE |
| `record_failed_render_cost` | 610 | Same pricing for a render a `MediaProviderError` interrupted; rows `failed=True`, reference `render:{job}:failed:scene:{n}:{unit}`. Callers: runbook/stages.py:1407; media/shooting_sheet.py:4174. | Vendors charge for what they generated. | CODE_RULE |
| `price_change_alert` | 657 | ESCALATE letter to the Owner from the Accountant listing price moves (none without an Accountant). Callers: `record_render_costs`, media/model_research.py:415 (there the new price is the steward model's reading of a vendor page). | Vendors change prices silently. | CONFIG (threshold applied by callers) |
| `_letter_once_a_day` | 702 | Behind the write lock: if a letter of this kind and business date exists, return it; else post an ESCALATE letter to the Owner from the Accountant (or the Director; none → not written). | One letter per kind per day. | CODE_RULE |
| `budget_refusal_letter` | 746 | Once a day: the day's film was refused by the budget, with figures; "only the Owner can raise the limit". Callers: runbook/stages.py:2668, :3356. | A refused day was silent. | CODE_RULE |
| `_letter_each_time` | 779 | A letter to the Owner every call (author Accountant, else Director, else no author: the studio itself, `:792`, `:799`); but `post_message` returns an open Owner letter with the same subject instead of writing a new one (see Oddities). | Each one is about money that went out. | — |
| `booking_refused_letter` | 807 | A purchase the books refused to record (media/shooting_sheet.py:2968). | 2026-10-02: 2,040 credits showed as 680. | — |
| `paid_step_interrupted_letter` | 835 | A paid step failed after paying: what it spent, whether booked, nothing re-bought (media/shooting_sheet.py:3079). | — | — |
| `purchase_abandoned_letter` | 869 | A purchase whose process died under it, worded by the sheet (media/shooting_sheet.py:2436). | — | — |
| `_local_moment`, `_cost_caveat` | 892, 907 | Local clock text; the unpriced caveat read back from an approval's evidence by its prefix. | The letter must not invent a deadline or a doubt. | — |
| `waiting_approvals_letter` | 927 | Once a day when approvals are PENDING: each question's label, evidence (≤ 120 chars, caveat removed), cost with caveat, expiry; the oldest expiry. Callers: `reconcile_day`; runbook/stages.py:2789, :2996, :3279, :3620. | SUPERVISED questions expired unseen after 24 h. | CODE_RULE |
| `agent_tokens_since` | 1024 | Prompt + completion tokens of every run (any outcome) since a moment. | Empty answers were billed too. | — |
| `_exceeded_budget` | 1040 | First active budget in state EXCEEDED. | — | CODE_RULE |
| `_usd_budget_refusal` | 1048 | BLOCKED_BUDGET verdict + once-a-day letter «Bugetul este depășit: angajații nu mai rulează». | MONEY-10. | CODE_RULE |
| `may_run_agent` | 1098 | Token ceiling, then exceeded USD budget (unless exempt task) → verdict; letter once a day. | The money gate before every model run. | CONFIG + CODE_RULE |
| `reconcile_day` | 1188 | See «LLM involvement». | The daily close. | LLM (advisory) + CODE_RULE |
| `format_usd` | 1358 | `format_micros`. No caller anywhere (backend, scripts, tests). | — | — |

Classes: `AccountantError` (`:80`), `NoAccountant` (`:84`), `AccountantReport` (`:1164`).
Data: reads `provider_cost_record`, `agent_run`, `provider_record`, `publication_record`,
`video_render_job`, `storyboard`, `script_draft`, `analytics_snapshot`, `approval_request`,
`agent_message`, `integration`, `provider_price`; writes `provider_cost_record`, `agent_message`,
memory records, `provider_resource.pricing` (through `record_measured_price`), events. External: the
model (close only). Money: none spent; costs booked.

### `app.economy.as_of` — backend/app/economy/as_of.py (313 lines)

The books at past moments (VR_CASH balance, the budgets active then, the period's and day's spend
and tokens) for the headquarters replay, in a fixed number of queries.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `economy_as_of` | 79 | For ≤ 240 instants: ledger balance by money class; costs recorded in the period and not yet replaced; prices of runs finished by then and known by then (`priced_after.at`); holds held then; budgets active then with state. | The replay's walls showed «—» (`:3-9`). | CODE_RULE |
| Helpers `_moment`, `_within`, `_still` | 60-77 | Stamp parsing and interval tests. | — | — |

No route serves it in the working tree (see Oddities). Read only.

### `app.economy.budget` — backend/app/economy/budget.py (768 lines)

The Owner's USD allowance per period, the period's spend, reservations, and the film cost estimate.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `BudgetCommand._a_limit_or_a_retirement` | 92 | A limit must be a positive sum; retiring takes no limit. | PAGE-05: an empty field retired the budget. | CODE_RULE |
| `_micros_or_none` | 106 | Parse or None. | — | — |
| `studio_timezone` | 113 | The studio row's time zone (UTC only without a studio row). | — | CONFIG |
| `_period_start` | 120 | Local midnight / 1st of month as a UTC ISO instant. | 2026-09-18: UTC midnight misfiled Bucharest's first two hours. | CODE_RULE |
| `_budget_view` | 135 | Row → dict. | — | — |
| `set_budget` | 150 | Behind the lock when versioned: recall command, check `expected_version`, apply, remember. Route `PUT /economy/budget`; also `_apply_budget` of the decisions core. | The Owner sets or retires a period's limit. | OWNER |
| `budget_version` | 207 | Rows of the period + retirement events. | Version the page sends back. | — |
| `_apply_budget` | 225 | Deactivates the active row; retirement event, or a new row + `economy.budget_set`. | Previous limits are kept. | — |
| `_agent_spend_micros` | 276 | Sum of `agent_run.cost_vr` since a moment (malformed strings skipped). | — | — |
| `reserved_since` | 294 | Sum of RESERVED holds made since a moment. | — | — |
| `spend_since` | 306 | Cost rows (ESTIMATED + BILLED, reconciled ones skipped) by provider, failed-render share, agent runs/tokens, unpriced runs, priced agent cost, holds. | The money gate's reading. | CODE_RULE |
| `_period_status` | 385 | Each active budget against its period: committed, ratio, OK/WARNING/EXCEEDED. | Session-based so a reservation is decided in its own transaction. | CODE_RULE |
| `budget_status` | 420 | Periods, versions, today, month, time zone. Route `GET /economy/budget`. | — | — |
| `_refusal` | 440 | Romanian refusal naming spent, held and asked. | — | — |
| `may_spend` | 457 | Reading: refuses if any committed + sum > limit. Caller: media/shooting_sheet.py:1856. | Kept as a reading; spenders reserve. | CODE_RULE |
| `reserve_spend` | 473 | Check and hold in one locked transaction; `force` skips the check. Callers: runbook/stages.py:2659, :3348; media/services.py:1958; media/shooting_sheet.py:2749, :2758 (force). | Two films cannot share the last ten dollars. | CODE_RULE / OWNER (force) |
| `_close_reservation` | 536 | RESERVED → RELEASED/SETTLED with reference and event; a closed hold is not changed. | — | — |
| `release_reservation` | 570 | The film was not made. | — | — |
| `settle_reservation` | 581 | Real cost rows booked; hold stops counting. | — | — |
| `release_stale_reservations` | 597 | Releases holds older than the TTL (watchdog). | A dead process must not pledge the day. | CONFIG |
| `unpriced_caveat` | 638 | «estimare incompletă: narația nu are preț stocat…» or "". | The same words wherever an incomplete figure is shown. | — |
| `estimate_film_cost_micros` | 657 | Film cost before it is made (see table above); returns `unpriced`, `caveat`, `complete`. Callers: runbook/stages.py:2861, :3307, :5316; runbook/preflight.py:1124. | Conservative reservation. | CODE_RULE + CONFIG |

Data: `spending_budget`, `spend_reservation`, `provider_cost_record`, `agent_run`, `provider_price`,
`storyboard_scene`, `studio`, events `economy.budget_set`, `economy.budget_retired`,
`economy.spend_reserved`, `economy.spend_reservation_closed`. No external calls.

### `app.economy.credits` — backend/app/economy/credits.py (306 lines)

Vendor balances before/after a render and prices measured from them.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `credit_balances` | 30 | For VERIFIED Runway/ElevenLabs connections with a readable key: Runway `organization().creditBalance`, ElevenLabs `subscription().character_count`; never raises. Callers: runbook/stages.py, app/demo.py. | "Before" had never been written down. | EXTERNAL (free reads) |
| `credit_spend` | 85 | Difference per vendor in its own unit. | — | CODE_RULE |
| `record_credit_spend` | 114 | Writes the difference (and USD at `credit_usd` for Runway) on the render's `production_json.credits_measured` and `economy.credits_measured`. Callers: media/assembler.py, runbook/stages.py. | Verify cost from credits (the Owner's instruction). | EXTERNAL |
| `record_measured_prices` | 176 | Attributes one step's Runway drop to its takes (`cost_plan.attribute_measured_credits`) and writes MEASURED per-second/per-image prices; one `economy.prices_measured` event; no drop → nothing. Callers: media/assembler.py, media/stills_stage.py. | A measured drop is the dearest evidence of a price. | EXTERNAL |
| `measured_price_table` | 249 | The published table with the connection's measured rows laid over it (credits at the Owner's rate). Caller: media/shooting_sheet.py:321. | Next sheet prices with what was paid. | EXTERNAL + CONFIG |

External: Runway and ElevenLabs account reads (free). Writes `provider_resource.pricing`, events.

### `app.economy.models` — backend/app/economy/models.py (512 lines)

Tables, no functions: `LedgerAccount` (`:46`, seeded chart), `FXSnapshot` (`:77`), `RevenueEvidence`
(`:111`, unique (source, reference)), `OwnerFundingEvent` (`:164`, a loan needs terms by DB check),
`ProviderCostRecord` (`:210`, unique (provider, reference), `failed`, `reconciled_at`,
`reconciled_by_id`), `LedgerTransaction` (`:272`, a transaction reversed at most once),
`LedgerEntry` (`:303`, exactly one side non-zero by DB check), `SpendingBudget` (`:327`),
`ProviderPrice` (`:371`, versioned, `usd_micros >= 0`), `SpendReservation` (`:417`),
`ProviderReconciliation` (`:450`). Constants `MICROS` (`:43`), `PRICE_UNITS` (`:358`),
`PRICE_PROVENANCES` (`:368`).

### `app.economy.prices` — backend/app/economy/prices.py (364 lines)

Prices the Owner supplies and the arithmetic of a call's cost.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_view` | 72 | Row → dict. | — | — |
| `set_price` | 90 | Behind the lock: idempotent by command id; optional `expected_version`; deactivates the active row, writes version + 1 and `economy.price_set`. Route `PUT /economy/prices`. | "The one way a price enters the books: the Owner's hand" (router.py:90-91). | OWNER |
| `list_prices` | 184 | Active (or all) prices. Route `GET /economy/prices`. | — | — |
| `_specificity` | 201 | Exact id > family prefix length; None if not covering. | — | CODE_RULE |
| `price_row` | 211 | Owner's rows before DOCUMENTED, then most specific. | A documented family row must not overrule his `*`. | CODE_RULE |
| `price_for` | 237 | Micros of `price_row` or None. | — | — |
| `price_lookup` | 242 | A per-kind callable for adapters, one short read per call. Callers: integrations/llm.py, providers/ollama.py, providers/elevenlabs.py, media/factory.py, runbook/preflight.py, main.py and others. | A price typed today costs tonight's runs without restart. | — |
| `_cost` | 256 | Micros → `cost_vr` string. | — | — |
| `llm_cost_vr` | 261 | (prompt × input + completion × output) / 1e6, half up; None unless both prices and both counts. | Half a price would understate a run. | CODE_RULE |
| `tts_cost_vr` | 281 | characters × per-1k / 1000, half up; None without a price. | — | CODE_RULE |
| `usd_from_micros` | 291 | Micros → float. No caller found. | — | — |
| `seed_documented_prices` | 298 | Seeds `DOCUMENTED_PRICES` as DOCUMENTED where nothing exists and the Owner has no `*` for the unit. Caller: scripts/bootstrap.py:88 (integrations/catalog.py:302 only names it in a comment). | Narration never read as free. | CONFIG |

### `app.economy.router` — backend/app/economy/router.py (167 lines)

Prefix `/economy`, every route behind `require_owner`, mounted under `/api/v1` (app/main.py:982).
`_guard` (nested, `:55`) maps `CommandConflict` and `EconomyError` to 409.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `create_economy_router` | 52 | Builds the router. "Virtual finance routes are retired" (`:3`). | — | — |
| `get_budget` — `GET /api/v1/economy/budget` | 66 | `budget_status`. | — | — |
| `put_budget` — `PUT /api/v1/economy/budget` | 71 | `set_budget`; `EconomyError` → 422. | — | OWNER |
| `get_prices` — `GET /api/v1/economy/prices` | 79 | `list_prices`. | — | — |
| `put_price` — `PUT /api/v1/economy/prices` | 87 | `set_price`. | — | OWNER |
| `get_daily_figures` — `GET /api/v1/economy/books/daily` | 96 | `daily_figures`. | — | — |
| `post_close_day` — `POST /api/v1/economy/books/close` | 101 | `reconcile_day`; `AccountantError` → 422. **Reaches the LLM.** | The Owner asks for the close now. | OWNER (asks), LLM (advisory) |
| `get_provider_costs` — `GET /api/v1/economy/provider-costs` | 109 | `list_provider_costs` (≤ 200). | — | — |
| `post_provider_cost` — `POST /api/v1/economy/provider-costs` | 117 | `record_provider_cost` (BILLED posts to VR Cash); `command_id` used as correlation id. | Record a real bill. | OWNER |
| `post_bill_cost` — `POST /api/v1/economy/provider-costs/{cost_id}/bill` | 134 | `bill_provider_cost`. | Confirm an estimate became an invoice. | OWNER |
| `get_reconciliations` — `GET /api/v1/economy/reconciliations` | 143 | `list_reconciliations`. | — | — |
| `put_reconciliation` — `PUT /api/v1/economy/reconciliations` | 156 | `reconcile_provider_invoice`. | "The only way a bill replaces an estimate: the Owner's hand" (`:159-160`). | OWNER |

`ProviderCostCommand` (`:36-49`): `command_id`, provider, reference, ESTIMATED/BILLED, amount string, currency, `fx_snapshot_id`, attribution.

### `app.economy.services` — backend/app/economy/services.py (1594 lines)

Phase 11 books: money helpers, the chart of accounts, balanced postings, evidence and minting
(retired as a product), Owner funding, provider costs, projections, and the invoice reconciliation.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `to_micros` | 144 | Decimal string → micros, half away from zero; refuses non-decimals. | Money never passes through a float. | CODE_RULE |
| `format_micros` | 166 | Micros → plain decimal. | — | — |
| `_convert_to_usd` | 173 | USD as is; other currencies only with a matching recorded FX snapshot. | "The studio does not invent rates" (spec 66 §Multi-currency). | CODE_RULE |
| `seed_chart_of_accounts` | 208 | Adds missing accounts of `CHART_OF_ACCOUNTS` (`:62-123`). Caller: scripts/bootstrap.py. | — | CONFIG |
| `post_transaction` | 234 | Refuses unbalanced, empty, two-sided, negative lines or unknown accounts before writing; writes transaction, entries, `economy.transaction_posted`. | The books always balance. | CODE_RULE |
| `record_fx_snapshot` | 312 | Stores a positive rate with source and event. | — | — |
| `record_revenue_evidence` | 362 | Records evidence (no minting); duplicate (source, reference) refused. | — | CODE_RULE |
| `settle_evidence` | 448 | Marks evidence SETTLED (REVERSED refused). | — | — |
| `mint_from_evidence` | 480 | SETTLED and not yet minted → MINT (debit 1000, credit revenue). | One verified dollar = one VR$, once. | CODE_RULE |
| `reverse_transaction` | 531 | Mirror posting once; marks minted evidence REVERSED; VR Cash may go negative. | Nothing is deleted. | CODE_RULE |
| `record_owner_funding` | 590 | Capital (credit 3000) or loan (credit 2000, needs rate and maturity); idempotent by `command_id`. | — | CODE_RULE |
| `record_provider_cost` | 699 | Behind the lock first: duplicate refused; ESTIMATED tracked; BILLED posts (debit 5000, credit 1000); `failed` only for estimates. | The only way VR Cash falls; 2026-10-09 lock incident. | CODE_RULE |
| `bill_provider_cost` | 805 | An unposted cost → BILLED and posted once. | — | OWNER (route) |
| `list_provider_costs` | 839 | Newest first, optional status. | — | — |
| `_account_balances` | 854 | Signed balances in each account's normal direction. | — | — |
| `trial_balance` | 874 | Total debits vs credits. Only caller: `treasury_snapshot` (`:979`), itself uncalled. (scripts/demo_treasury.py:249-254 reads `trial_balance` from the retired `GET /economy/treasury` route, not this function.) | — | — |
| `treasury_snapshot` | 889 | Money classes, pending/forecast evidence, unbilled (unreconciled) estimates, accounts, deficit flag, trial balance, disclaimer. No caller in backend/app. | Labels travel with numbers (spec 66 §Public representation). | — |
| `list_evidence`, `list_transactions`, `list_accounts`, `list_owner_funding` | 988-1051 | Listings. No caller in backend/app. | — | — |
| Views `_evidence_view`, `_cost_view`, `_funding_view`, `_fx_view`, `_unmatched_view`, `_reconciliation_view` | 1057-1232 | Row → dict with labels («ESTIMAT (înlocuit de factura furnizorului)», …). | — | — |
| `reconcile_provider_invoice` | 1235 | Owner's invoice: validates scope; recall; duplicate reference refused; previous active version must match `expected_version` (a missing version is refused when one stands); matches ESTIMATED rows of the provider in the window/correlation (re-adopts the previous version's), keeps others as `unmatched` with reasons; writes the BILLED row stamped at the last matched spend, posts it, reverses the previous bill's posting, stamps `reconciled_at` on matched rows and the superseded bill, writes the reconciliation and `economy.reconciliation_recorded`. | Stop counting an estimate and its bill together. | OWNER + CODE_RULE |
| `list_reconciliations` | 1577 | Newest first with the bill's `counted_at`. | — | — |

Data: all ledger tables, `provider_cost_record`, `provider_reconciliation`, `command_record`, events.
External: none (the module moves no real money, `services.py:19-24`).

## Connections

**Into this group**

- `run_agent_task` → `may_run_agent` before every model run (agents/services.py:771-781) and
  `sources.model_run_finished` after it (agents/services.py:1022-1027).
- The daily run (runbook/stages.py): `reserve_spend` / `settle_reservation` / `release_reservation`
  (:1377, :2659, :2724, :3348, :3603), `estimate_film_cost_micros` (:2861, :3307, :5316),
  `record_render_costs` / `record_failed_render_cost` (:1407, :2714, :3594), `budget_refusal_letter`
  (:2668, :3356), `waiting_approvals_letter` (:2789, :2996, :3279, :3620), `sources.film_budget`
  (:2427, :2922), `redo_allowance` and `propose_redo_cap_card` (:4961-4968, :5174-5185),
  `reconcile_day` in `_post_run` (:6241).
- Media: shooting sheet (`may_spend` :1856; `reserve_spend` :2749, :2758; letters :2436, :2968, :3079;
  `record_render_costs` :4033; `record_failed_render_cost` :4174; low-balance card :3593, :3607;
  `measured_price_table` via `price_table_for` :319-328); assembler (`film_without_music` :5865,
  `film_needs_review` :6251, `record_credit_spend`, `record_measured_prices`); stills stage;
  media/services.py:1958; media/router.py:682; media/model_research.py:415 (`price_change_alert`);
  media/blocker_repair.py:274, :301; media/film_close.py:307-327 and agents/repairs/desk.py:707-760
  (propose / withdraw cards); media/runpod_unsent.py:890-902 (propose).
- Providers: providers/runpod/router.py:89-97 (GPU hold raised, card proposed); providers/runpod/weights.py:240-245 and
  pods.py:463-466, :1045-1093 (card builders, keys, `ask`).
- YouTube and analytics: `youtube_refused` / `youtube_reconnected` (youtube/services.py:535, :572,
  :646, :719; analytics/services.py:341).
- Start-up: `seed_owner_decisions` + `refresh_owner_decisions` (app/main.py:303-310); Settings save
  (integrations/router.py:130-134). Watchdog: `release_stale_reservations` (workflows/watchdog.py:869).
- Mail: `daily_figures` for the Accountant's letters (agents/mail.py:210-227).
- Adapters: `price_lookup`, `llm_cost_vr`, `tts_cost_vr` (integrations/llm.py, providers/ollama.py,
  providers/elevenlabs.py, agents/repairs/reprice.py, runbook/preflight.py).

**Out of this group**

- Owner commands: `app.services.change_paid_media_approval`, `change_environment`,
  `change_autonomy_mode`; `media.shooting_sheet.set_scene_model`; `media.blocker_repair.allow_repair_retry`;
  `media.director_qc.accept_film` / `close_film`; `app.services.queue_film_continue`;
  `providers.runpod.gpu_session.set_owner_hold`; `providers.runpod.pods.start_copy`;
  `media.runpod_unsent.apply_release`.
- Planning and prices: `media.production_policy` (`plan_scene_models`, `estimate_cost_usd`,
  `credit_usd`, `record_measured_price`), `media.cost_plan`, `integrations.catalog.DOCUMENTED_PRICES`.
- Messages and memory: `agents.messages.post_message`, `letters_for_owner`; `agents.memory`.
- The model: `agents.structured.structured_run` (close only).
- Vendors: Runway and ElevenLabs account reads (`credit_balances`).

**Events emitted**: `owner.decision_decided`, `owner.decision_apply_failed`, `owner.decision_withdrawn`,
`owner.decision_completed`, `owner.decision_expired`, `owner.decision_reopened`,
`runpod.infra_actions_enabled`, `media.redo_allowance_granted`, `economy.budget_set`,
`economy.budget_retired`, `economy.spend_reserved`, `economy.spend_reservation_closed`,
`economy.price_set`, `economy.provider_cost_recorded`, `economy.provider_cost_billed`,
`economy.reconciliation_recorded`, `economy.transaction_posted`, `economy.credits_measured`,
`economy.prices_measured`, `economy.fx_snapshot_recorded`, `economy.evidence_recorded`,
`economy.evidence_settled`, `economy.vr_minted`, `economy.evidence_reversed`,
`economy.owner_funding_recorded`, `agent.message_posted` (through `post_message`).

**Events consumed**: `runpod.owner_hold` (`OWNER_HOLD_EVENT`), `media.redo_allowance_granted`,
the Director's QC decision event, `media.balance_rule.BALANCE_READ_EVENT`, `economy.budget_retired`,
the shooting sheet's `SCENE_MODEL_EVENT`.

## Owner touchpoints

- **The «Decizii (N)» window**: `GET /api/v1/owner/decision-cards` (decisions/router.py:28) and
  `POST /api/v1/owner/decisions/{id}/decide` with ACCEPT (option; default the recommended one, else the
  only one, services.py:1137-1146), REFUSE, or DONE («Am făcut-o»), each with an optional note (services.py:147-158). Paid-step
  approvals appear there but are answered through `POST /api/v1/owner/approvals/decision`
  (services.py:1462-1468); asking letters through `/api/v1/agents/messages/{id}/reply|resolve`
  (services.py:1526-1530).
- **Cards in this group and what his answer does**:
  daily budget (raise through `set_budget` / keep; audit variant: raise / cheaper models, guided);
  reconnect a model connection (guided «Furnizori AI»); reconnect a YouTube channel (guided);
  Google OAuth production + YouTube API audit (guided, only his DONE closes it); commercial use per
  vendor connection (guided); music library (guided / without); RunPod infra actions (yes → agents
  may switch the GPU on in approved steps / not yet); LTX-2.5 licence (guided / without); RunPod
  endpoint weights (guided console step / keep off); mirror copy (yes → a paid temporary pod starts,
  capped / not yet); unsent RunPod release (release a held scene); narration as an asked paid step
  (record / none); move from EVERY_PAID_STEP to MODE (keep / apply); editorial QC advisory or
  blocking (none / guided `.env`); old test films (guided / keep); sale terms (guided); low Runway
  balance (top up, guided / wait); sheet repair paused (reconnect / retry now / local move / wait);
  GPU hold (allow again); redo cap reached (allow 5 more / publish as is / close / wait).
- **Buttons outside the window**: «Oprește GPU acum» raises the hold and the card
  (providers/runpod/router.py:89-97).
- **Economy routes (Owner key)**: set or retire the DAILY/MONTHLY budget; set a price; read the
  day's figures; ask for the Accountant's close now; record a provider bill; mark an estimate
  billed; reconcile a vendor invoice (economy/router.py:65-165).
- **Settings he owns that act here**: `STUDIO_AGENT_DAILY_TOKEN_BUDGET` (config.py:419),
  `STUDIO_PRICE_CHANGE_ALERT_PERCENT` (config.py:446), `reservation_ttl_seconds` (config.py:380),
  `film_max_paid_redos_per_scene` / `film_max_paid_redos` (config.py:314-315), `motion_budget_usd`
  (config.py:258), `editorial_qc_blocking` (config.py:186), `approval_expires_after_hours`
  (config.py:401; the waiting letter quotes each request's resulting `expires_at`), the Runway
  connection's `credit_usd`, the RunPod
  connection's `mirror_copy_max_usd` / `mirror_copy_max_minutes`.
- **Letters he receives from this group**: budget refusal (once a day), token ceiling reached (once
  a day), budget exceeded – agents stopped (once a day), questions waiting (once a day), booking
  refused, paid step interrupted after paying, purchase abandoned, price changed (from measured
  renders, or from the model-research steward's reading of a vendor page).

## Oddities and gaps

1. **`economy_as_of` has no route.** CHANGELOG.md:839 and CURRENT_STATUS.md:2491, :2501 document
   `GET /api/v1/economy/as-of`; `economy/router.py` has no such route and the only importers are
   tests (tests/test_replay_reads.py:26, tests/test_director_repairs_review.py:28). The frontend
   still asks for it (frontend/src/day_replay.js:256), so the replay's figures read a 404. The
   route was apparently removed with the Treasury retirement (router.py:3), leaving `as_of.py`
   (313 lines) without a production caller.
2. **Retired ledger code without callers.** `record_revenue_evidence`, `settle_evidence`,
   `mint_from_evidence`, `reverse_transaction`, `record_owner_funding`, `record_fx_snapshot`,
   `treasury_snapshot`, `list_evidence`, `list_transactions`, `list_accounts`, `list_owner_funding`
   (`economy/services.py:312-1051`) have no caller in backend/app (grep); only tests.
   `seed_chart_of_accounts` is called by scripts/bootstrap.py:82; `trial_balance` only by the
   uncalled `treasury_snapshot` (`services.py:979`). scripts/demo_treasury.py drives the retired
   HTTP routes (`/economy/evidence`, `/economy/fx`, `/economy/owner-funding`, `/economy/treasury`,
   scripts/demo_treasury.py:129-249) that `economy/router.py` no longer serves, so it cannot run
   against the current backend. `prices.usd_from_micros` (`:291`) and `accountant.format_usd`
   (`:1358`) have no caller anywhere. Consistent with ADR-SIMPLE-PIXEL-STUDIO
   (16_DECISION_LOG.md:542), which keeps historical data.
3. **`bill_provider_cost` does not check `reconciled_at`** (`services.py:805-836`): an ESTIMATED row
   that an invoice already replaced (`reconcile_provider_invoice` stamps it, `:1512-1514`, and posts
   the invoice) can still be billed through `POST /provider-costs/{id}/bill`, which posts a second
   PROVIDER_COST transaction to VR Cash. `spend_since` would skip the row (reconciled), so budgets are
   not affected; the ledger is.
4. **`POST /economy/provider-costs` is not idempotent by `command_id`**: the id is used only as the
   correlation id (`router.py:129`); a retry is refused as a duplicate reference (409,
   `services.py:754-758`), unlike prices and reconciliations, which return the first answer.
5. **The daily close is not addressed to the Owner.** `reconcile_day` posts without `to_owner`
   (`accountant.py:1298-1307`), so the message lands in the Director's inbox (agents/messages.py:208-211,
   :217-221); `owner_attention: True` in its body is not what `is_for_owner` reads. The daily run
   intends this (the close is in the inbox when the Director reviews it, and «a budget exceeded reaches the
   Owner the same evening» through her, runbook/stages.py:6233-6236),
   but the resolution it writes on the Director's budget requests says «transmisă Proprietarului»
   (`:1340-1343`), and nothing in this group forwards the close to the Owner.
6. **"Every time" letters can be folded.** `_letter_each_time` says none may be folded into another
   (`accountant.py:788-790`), but `post_message(to_owner=True)` returns the open letter with the same
   subject (agents/messages.py:55-74). `booking_refused_letter`'s subject is constant (`:823`), so a
   second refused booking while the first letter is open writes nothing new; the same holds for
   `price_change_alert` (`:685`).
7. **Once-a-day letters across days.** `_letter_once_a_day` looks for today's letter by kind and date
   (`accountant.py:721-728`); if a letter with the same (constant) subject from an earlier day is
   still OPEN, `post_message` returns that old letter, the function reports `written: True` with its
   id, and no letter dated today is ever created.
8. **The token ceiling stops the daily close.** `BUDGET_EXEMPT_TASKS` only skips the exceeded-USD
   check (`accountant.py:1124-1127`, as the docstring `:1113-1117` says); the token-ceiling branch
   (`:1135-1158`) refuses `reconcile_day` like any run. The reason given for the exemption (`:1035-1036`:
   refusing the close "would silence the one escalation") applies equally to the ceiling, but is not
   applied there: on a day past the ceiling the Owner gets the ceiling letter and no close.
9. **Hard-coded persona.** Budget requests are resolved by «Nadia (Accountant)» (`accountant.py:1339`)
   whatever the active Accountant's name is.
10. **`price_change_alert` has no fallback author**: with no Accountant it returns silently
    (`accountant.py:679-681`), while the other letters fall back to the Director (`:729`, `:792`).
11. **The Accountant's `holds` are never enforced**; they are stored in the close and in the books
    report (runbook/stages.py:6250). `continue_spending: false` only turns the message into an
    ESCALATE (`accountant.py:1263-1264`).
12. **Close message `run_id`** is the first attempt's run even when the second attempt produced the
    report (`accountant.py:1305`, `:1313`, `:1347`; agents/structured.py:164-166 returns the first run
    as `result`).
13. **Raw price table in two estimators.** `seed.cheapest_capable_film` (`seed.py:137`) and
    `budget.estimate_film_cost_micros` (`budget.py:723`, `:734`) call `cost_plan.load_price_table()`
    directly, not `media.shooting_sheet.price_table_for` (shooting_sheet.py:319-328), which lays the
    connection's measured prices, local-model prices and RunPod estimated prices over the published
    table.
14. **Redo-cap arithmetic duplicated with different fallbacks.** `redo_cap.cap_still_reached`
    (`redo_cap.py:397-398`) and runbook/stages.py:4967-4968 both compute `settings + allowance`, with
    `getattr` fallbacks 1 and 2 while the Settings defaults are 5 and 20 (config.py:314-315). The
    module docstring (`redo_cap.py:6-7`) names the settings; the fallback applies only when the
    settings object lacks the attribute. A third copy, `runbook.stages._redo_allowance`
    (stages.py:4201-4219, same 1/2 fallbacks at :4213-4214), builds the limits the Director's QC
    review is shown (stages.py:4317-4320) from the settings alone, without the Owner's
    `media.redo_allowance_granted` allowance, so after his «allow» her prompt can still read the
    old cap while `_apply_repairs` (stages.py:4966-4968) uses the raised one.
15. **`expires_at` is never set.** `propose_owner_decision` accepts it (`services.py:839`, `:870`) and
    `refresh_owner_decisions` expires on it (`:972`), but no proposer in the backend passes it (grep
    of the producers, seed, runpod, repairs and media callers), so EXPIRED is unreachable today.
16. **Conditions are read only when someone reads.** `refresh_owner_decisions` runs at start-up
    (app/main.py:307-308) and on each `GET /owner/decision-cards` (`services.py:1575-1579`); between
    those, only producers that explicitly withdraw close cards. A GET therefore writes.
17. **Apply outside the lock.** `decide_owner_decision` takes `_lock` in transaction 1, runs the
    applier with no lock held, and re-locks in transaction 2 (`services.py:1196-1230`). Two answers
    with different `command_id`s naming different options of the same version can both run their
    appliers; only one card transition commits (the other raises `DecisionConflict`). The module
    docstring accepts two commits for retries of the same answer (`:30-35`).
18. **Spec 31 lists fewer appliers than exist.** 31_GOVERNANCE_APPROVAL_POLICY.md:158 names
    `set_budget`, `change_paid_media_approval`, `change_environment`, `change_autonomy_mode`,
    `set_scene_model`, `allow_repair_retry`; the code adds `runpod_infra`, `runpod_mirror_copy`
    (starts a paid pod), `runpod_unsent_release`, `gpu_hold_lift`, `redo_allowance`,
    `film_publish_as_is`, `film_close_capped` (`services.py:438-451`, producers).
19. **An ACCEPT without an option spends on the mirror-copy card.** `_chosen_option` applies the
    recommended option when none is named (`services.py:1141-1146`); on the mirror-copy card that is
    «yes», which starts the paid pod (`sources.py:504-516`, `:1236-1260`). The window's second
    confirmation («Da, aplică» / «Nu acum») covers only the apply types `budget`,
    `paid_media_approval`, `environment`, `autonomy_mode` (frontend/src/owner_decisions.js:30,
    :251-255; ADR-DECISIONS-WINDOW, 16_DECISION_LOG.md:4146), so the paid `runpod_mirror_copy`
    pod, `runpod_infra` and `redo_allowance` (which re-enables paid redos) apply on one press,
    although the ADR's own rule is "an option that spends money … asks once more".
20. **Seed docstring vs behaviour.** `seed.py:21-22` says the seed is read-only outside the card
    table, but `_settle_runpod_unsent` releases RunPod holds at boot (`seed.py:411-425`, "local
    writes only").
21. **Duplicated helpers.** `_usd` (seed.py:76, sources.py:206), `BUDGET_STEP_USD` (seed.py:65,
    sources.py:76), and the "active DAILY limit" query (seed.py:192-196, sources.py:568-576,
    services.py:529-539).
22. **Agent cost is not attributed to films**, said explicitly in the figures (`AGENT_COST_PER_FILM_RO`,
    `accountant.py:227-230`): a film's cost excludes the employees' model runs.
23. **Render costs rank the catalogue above the Owner's price.** prices.py:8-9 says a
    `ProviderPrice` is "typed by the Owner … and nowhere else: no agent, no search result and no
    vendor page can write one", which holds for that table; but `_priced_scene_costs` prices a
    scene from the model catalogue (`provider_resource.pricing`) first and reads the Owner's table
    only when the catalogue has no price (`accountant.py:499-514`). The catalogue is written by
    measured renders and by the model-research steward from a vendor page through
    `update_resource_metadata` (media/model_research.py:379-401; integrations/discovery.py:771-801),
    so a model-read price can set an ESTIMATED cost row and hence the period's budget state.
24. **The close's figures are cut mid-JSON.** `reconcile_day` sends
    `json.dumps(figures)[:12000]` (`accountant.py:1209-1211`): a raw character slice of a JSON
    document. On a day with many unpriced models or films the tail (`films.published`, then
    `measured_at`, `:120-124`) is lost and the object is left unclosed; the instructions still call
    it "the data".
25. **Redo-cap docstring names the wrong close.** `redo_cap.py:17` says «close» is
    `media.film_close.close_film`; the applier calls `media.director_qc.close_film`
    (`redo_cap.py:346`, `:370`), as its own docstring (`:343-345`) explains.
26. **`_record_priced` swallows every `EconomyError`** (`accountant.py:604-606`), not only the
    duplicate reference it is meant for; a cost row refused for another economy reason
    (for example an unconvertible currency in `_convert_to_usd`) is skipped with no letter, unlike
    the sheet's own booking path that writes `booking_refused_letter` (media/shooting_sheet.py:2968).
    With the USD rows it builds today the other refusals are not reachable, so this is latent.
