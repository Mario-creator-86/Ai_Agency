# 05 — The shooting sheet, production policy, cost plan and balance rule

> Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).
>
> Files: `backend/app/media/shooting_sheet.py` (4368 lines, 97 functions), `backend/app/media/production_policy.py` (3445 lines, 78 functions), `backend/app/media/cost_plan.py` (608 lines, 22 functions), `backend/app/media/balance_rule.py` (158 lines, 10 functions). 8579 lines, 207 functions.
> The four files of this group are byte-identical at `b00083c` and `20abffd`, so their line numbers hold. Citations into files changed after `b00083c` (`assembler.py`, `stills_stage.py`, `still_gate.py`, `qc.py`, `picture_qc.py`, `fix_check.py`, `prompt_agent.py`) and into the new `second_look.py` give their lines at `20abffd`.

## In one paragraph

This group is the money gate in front of every paid media purchase of a film. `cost_plan` is a pure price calculator over `config/runway_prices.json` (whole billed seconds, credits, USD micros, price provenance). `production_policy` answers "which technology makes this": the Organization → channel → series → episode → scene → character configuration hierarchy with identity locks, and the per-scene motion-model planner (`plan_scene_models`) that picks, for every filmed scene, the cheapest model in the Owner's allowed set whose documented or measured capability covers the scene's need (unless the Owner's per-scene choice, a model kept from an approved sheet, or the connection's selected RunPod/ComfyUI default names one first, `backend/app/media/production_policy.py:2811-2882`), and that classifies vendor failures. `balance_rule` is the Owner's 2026-10-03 rule that a paid step starts when the vendor balance holds its next round times a margin. `shooting_sheet` assembles all of it into the "foaia de filmare": a 0-credit page per film (prompts, models, seconds, credits, USD, caps, lint, balance, budgets) whose canonical-JSON SHA-256 (`sheet_hash`) every paid step must name; it then runs the paid steps (stills, hero test shot, motion, assemble/narration) behind a strict, ordered chain of deterministic gates (one buyer per film, stale-hash, shot-plan, lint, Owner mode, balance, film ceiling, budget reservation) before handing over to the stages that ask the Owner and buy, and it books what was bought. No function in this group calls a language model; every decision here is deterministic code, configuration, an external reading, or the Owner, although some of the data and configuration it reads were written by models elsewhere (prompts, steward quality scores, possibly the RunPod default model; see "LLM involvement").

## Why it exists

| Incident or rule | What it caused here | Source |
|---|---|---|
| Nepal film, 2026-09-26: over 1,000 Runway credits spent while the books said 0.74 USD; the vendor's price was never read and nothing priced a film before buying it | `cost_plan` prices a whole film at 0 credits from the vendor's own table; no guessed prices (`UnpricedError`) | `backend/app/media/cost_plan.py:1-23` |
| Second Nepal render (2026-09-26 18:16) started from a button that showed no price, prompt or model and bought every still and clip again | The shooting sheet: the page shown before any credit; every paid step bound to its `sheet_hash` | `backend/app/media/shooting_sheet.py:1-25` |
| Owner, 2026-09-27: «Nu trebuie un singur model pe tot filmul! Trebuie sa optimizam costurile!» | No model lock: per-scene cheapest capable model; premium only where the scene needs it; the Owner's per-scene override wins | `backend/app/media/production_policy.py:2043-2055`, `docs/project/16_DECISION_LOG.md:4048-4058` |
| 2026-10-01 MODEL_CATALOG: a steward's unsourced quality guesses were plainly wrong | Research counts only when measured or sourced; `config/film_models.json` outranks an unsourced annotation; the Owner owns `allowed`, `hero_threshold`, `premium_reference` | `backend/app/media/production_policy.py:3290-3322`, `docs/project/16_DECISION_LOG.md:4074` |
| 2026-10-01: real paid media only through the sheet's steps | The sheet's steps are the only purchase path for real paid adapters | `docs/project/16_DECISION_LOG.md:4080`, `docs/architecture/08_VIDEO_PIPELINE.md:214-238` |
| 2026-10-02 GATES_BEFORE_BUYING (MONEY-04 one buyer per film, MONEY-06 no unasked buying without a daily budget, MONEY-07 film ceiling, AR-03 reservation behind the write lock) | `film_purchase_lease`, `check_film_ceiling`, `hold_step_budget`, the gate order | `backend/app/media/shooting_sheet.py:1874-1880`, `docs/project/16_DECISION_LOG.md:4100-4104` |
| 2026-10-02 booking duplicates: 2,040 credits spent, 680 booked (reference was the sheet alone) | One booking reference per purchase (`foaie:{film}:{step}:{hash16}:{correlation}`) | `backend/app/media/shooting_sheet.py:2988-2999` |
| REL-01: four purchases on one "database is locked", none booked | A stage that raised after paying is booked from the measured balance drop and raised as a HARD `SpentStageError`, never retried | `backend/app/media/shooting_sheet.py:3514-3556` |
| MONEY-12: the sheet's assemble step booked nothing it had voiced when the assembly failed | `_book_failed_assembly` | `backend/app/media/shooting_sheet.py:4146-4178` |
| Owner, 2026-10-03: «De ce avem nevoie de așa de multe credite…» (LHC film waited with 316 credits while the start check asked 497) | `balance_rule`: start on next round × margin; re-read before every further purchase; cap stays the ceiling | `backend/app/media/balance_rule.py:1-25`, `docs/project/16_DECISION_LOG.md:4155-4157` |
| 2026-10-03 REDO_HANG: a three-hour lease outlived its dead process and refused every press «acum 144 de minute» | Renewed leases (60 s, never more than 300 s ahead), reclaim of abandoned leases with a letter | `backend/app/media/shooting_sheet.py:1914-1923`, `docs/project/16_DECISION_LOG.md:4169` |
| 2026-10-04 STUDIO_DEFECT: a 400 naming our own request's parameter held a scene for the Owner | `STUDIO_DEFECT_PATTERNS`, `classify_failure` STUDIO_DEFECT stops the step without blaming the model | `backend/app/media/production_policy.py:2097-2113`, `docs/project/16_DECISION_LOG.md:4188` |
| Owner, 2026-10-08: «Totul pe RunPod oricum» | The selected RunPod model is taken unasked by quality (`selected_default` branch) | `backend/app/media/production_policy.py:2839-2861`, `docs/project/16_DECISION_LOG.md:4204` |
| Owner's «Încetinește local», 2026-10-09/10 (NASA film: 11.1 s and 12.5 s scenes on a 10 s model) | `SLOWDOWN_ALLOWANCE` 25 %: a longer scene is billed at the model's longest clip | `backend/app/media/cost_plan.py:69-74`, `backend/app/media/cost_plan.py:236-255` |
| Film 6fe6a577, 2026-10-10: a scene no clip could carry held only itself while the rest was bought | `SCENE_TOO_LONG` is a lint BLOCK on the whole sheet; the Director's story repair splits the scene | `backend/app/media/shooting_sheet.py:1426-1442`, `backend/app/media/production_policy.py:2450-2453` |
| babcf272, 2026-10-09: the sheet said «Pregătit» four times while the render refused a 5.0 s clip for 6.06 s of words | The assemble step reads the render's own `assembly_readiness` | `backend/app/media/shooting_sheet.py:1124-1145` |
| 2026-10-10: the Owner chose LOCAL_MOVE at 08:46 UTC and nothing moved | `set_scene_model` queues a FILM_CONTINUE | `backend/app/media/shooting_sheet.py:480-492` |
| 2026-10-09 ADR-OWNER-CLOSE-FILM | `FilmClosed`, `film_is_closed`; every lease except `close` refuses a closed film | `backend/app/media/shooting_sheet.py:1902-1971`, `docs/project/16_DECISION_LOG.md:4245` |
| Production-policy rule: providers/models/voices are replaceable technology, a recurring character is a persistent creative asset | The configuration hierarchy and identity locks | `backend/app/media/production_policy.py:1-25` |

## Who decides here

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| A paid sheet step may run at all only for the sheet the Owner (or the walk) saw | CODE_RULE | `backend/app/media/shooting_sheet.py:3316-3322` | `plan_hash` must equal the freshly computed `sheet_hash`, else `STALE_PLAN` (409), nothing bought |
| Only one buyer per film at a time | CODE_RULE | `backend/app/media/shooting_sheet.py:2077-2086` | `FilmPurchaseLease` row taken behind `lock_for_write`; another live holder → `FILM_BUSY` |
| A closed film buys nothing | CODE_RULE (closure itself is OWNER or Director retirement) | `backend/app/media/shooting_sheet.py:1954-1971`, `backend/app/media/shooting_sheet.py:2091-2094` | Storyboard `REJECTED` with no `COMPLETED` render job → `FilmClosed` for every lease step except `close` |
| A PRODUCTION film is not bought from template prompts | CODE_RULE | `backend/app/media/shooting_sheet.py:3324-3331` | `shot_plan_gaps` non-empty → `NEEDS_SHOT_PLAN` |
| A prompt defect or an over-long scene blocks every purchase | CODE_RULE | `backend/app/media/shooting_sheet.py:3332-3338`, `backend/app/media/shooting_sheet.py:1432-1442` | any lint finding of severity BLOCK, including `SCENE_TOO_LONG` → `LINT_BLOCKED` |
| Nothing to buy for this step | CODE_RULE | `backend/app/media/shooting_sheet.py:3339-3341` | step's `to_buy` empty → `NOTHING_TO_BUY` with the step's waiting reason |
| An unasked step (the day's walk) is refused by the Owner's mode before any balance read | OWNER (policy via the Policy Kernel) | `backend/app/media/shooting_sheet.py:3345-3360` | `mode_guard.unasked_refusal`: kernel refusal other than NEEDS_APPROVAL stops the step |
| A step does not start on an unreadable balance | CODE_RULE on EXTERNAL | `backend/app/media/shooting_sheet.py:3371-3380` | `_read_balance` credits `None` (not local/GPU) → `LOW_BALANCE` (fail closed) |
| A step starts only if the balance holds its next round × margin | CODE_RULE + CONFIG + EXTERNAL | `backend/app/media/shooting_sheet.py:3384-3413`, `backend/app/media/balance_rule.py:52-58` | `ceil(round(cost × margin, 6))`; margin `paid_step_balance_margin` default 1.15; short → `LOW_BALANCE` + Owner card |
| RunPod (GPU-billed) and 0-cap local steps skip the vendor-balance rule | CODE_RULE | `backend/app/media/shooting_sheet.py:3372-3374`, `backend/app/media/shooting_sheet.py:614-630` | `applicable is False` and (`cap == 0` or `billing_mode == "gpu"`) |
| A PRODUCTION step may not take the film past its ceiling | CODE_RULE + CONFIG; OWNER may consent | `backend/app/media/shooting_sheet.py:2673-2723` | books for the film + step cap > `film_budget_usd` (default 15.24 USD) → `OVER_FILM_BUDGET`; `allow_over_budget` records `media.film_budget_excess_approved` |
| The step's cap is reserved against every active budget | CODE_RULE; OWNER may consent | `backend/app/media/shooting_sheet.py:2726-2778` | `economy.budget.reserve_spend` refuses → `OVER_DAILY_BUDGET`/`OVER_BUDGET`; `allow_over_budget` forces the hold and records `media.budget_excess_approved` |
| Whether the Owner is asked or the step buys | OWNER (via `may_act` inside the stage, out of scope) | `backend/app/media/shooting_sheet.py:27-40` (docstring), stages called at `backend/app/media/shooting_sheet.py:3455`, `:3479` | Stage answers NEEDS_APPROVAL (202) or spends the yes bound to `plan_hash` |
| Older unanswered questions about the same step are withdrawn when a newer sheet asks | CODE_RULE | `backend/app/media/shooting_sheet.py:3092-3127`, `backend/app/media/shooting_sheet.py:3624-3633` | kernel `withdraw_superseded_approvals` keeps only the new approval |
| A stage that raised after paying is booked and never retried | CODE_RULE + EXTERNAL | `backend/app/media/shooting_sheet.py:3514-3556`, `backend/app/media/shooting_sheet.py:3018-3024` | `meter.attempts > 0` and spend > 0 → book (balance drop if readable, else `meter.committed`), letter, `SpentStageError` (HARD) |
| What a bought step is booked at | CODE_RULE + EXTERNAL | `backend/app/media/shooting_sheet.py:2979-3015` | measured balance drop (`spent_credits_measured`) over quoted credits; ESTIMATED provider cost |
| A booking the books refuse is never silent | CODE_RULE | `backend/app/media/shooting_sheet.py:2945-2975` | `EconomyError`/`ValueError` → WARNING event `media.step_cost_not_booked` + Accountant letter |
| Reservation after the step: settled or released | CODE_RULE | `backend/app/media/shooting_sheet.py:2814-2829` | spent ≤ 0 → release; booked → settle; spent but not booked → hold kept until watchdog TTL |
| The assemble step refuses a film whose filmed scenes lack an accepted take | CODE_RULE | `backend/app/media/shooting_sheet.py:3866-3894` | `assembly_readiness` not ok → `TAKES_NOT_ACCEPTED`, recorded via `record_assembly_refused` |
| Whether the narration is asked about | CODE_RULE | `backend/app/media/shooting_sheet.py:3926-3928` | characters > 0 and (micros > 0 or (a paid voice and unpriced)) |
| Narration under the period budget | CODE_RULE; OWNER may consent | `backend/app/media/shooting_sheet.py:3931-3937`, `backend/app/media/shooting_sheet.py:1849-1871` | read-only `may_spend`; refused unless `allow_over_budget` |
| Narration risk tier (T2 vs T3) | CODE_RULE + CONFIG | `backend/app/media/shooting_sheet.py:3671-3676` | unpriced or no threshold → `media.paid_generation_over_threshold`; USD > `paid_generation_approval_threshold_usd` (default 5.0) → over; else `media.paid_generation` |
| Narration approval | OWNER (Policy Kernel `may_act`) | `backend/app/media/shooting_sheet.py:3679-3715`, `backend/app/media/shooting_sheet.py:3948-3967` | verdict not allowed → refusal (202 with question if NEEDS_APPROVAL) |
| A per-scene motion model or LOCAL_MOVE | OWNER | `backend/app/media/shooting_sheet.py:413-497` | `issued_by` must be `owner`; LIVE scenes only; a model must have a video price row at the resolution, else 422 |
| A take is approved or rejected | OWNER | `backend/app/media/shooting_sheet.py:500-605` | `decide_take(decided_by="owner")`; approving a still demotes other APPROVED stills of the same scene and prompt to PAID |
| Which model films each scene (planner) | CODE_RULE over CONFIG and data | `backend/app/media/production_policy.py:2587-2966` | cheapest capable model (credits, then quality, then id; slowed clips last) |
| The Owner's per-scene choice beats the planner, even outside the allowed set | OWNER | `backend/app/media/production_policy.py:2811-2838` | override taken if priced and in the catalogue; shortfalls shown as warnings only |
| The selected RunPod model is taken unasked by quality | CONFIG (the connection's `MediaProductionConfig.model_id`; usually the Owner's Settings choice, but see below) | `backend/app/media/production_policy.py:2839-2861`, `backend/app/media/production_policy.py:3413-3417`, `:3440` | `selected_default and not local_generation`; held only if unpriced or blocked by something other than quality. The stored default is written by the Owner (`PUT /settings/integrations/{id}/production` → `integrations.discovery.save_production`, `backend/app/integrations/router.py:361-366`) and also, when the connection's `allow_production_override` is on, by `integrations.autoconfig.auto_configure` (first ranked model, `backend/app/integrations/autoconfig.py:209-240`) and by the weekly model steward's LLM recommendation (`media.model_research.research_models`, `backend/app/media/model_research.py:417-455`, job `backend/app/main.py:527-536`); for a RunPod/ComfyUI connection that save also promotes the model to CANDIDATE, an admitted station (`backend/app/integrations/discovery.py:727-739`, `backend/app/integrations/lifecycle.py:55`) |
| Which models are excluded for a scene | CODE_RULE + CONFIG | `backend/app/media/production_policy.py:2497-2555` | outside `allowed`; not admitted; refused here; no `image_to_video`; frame not delivered; camera move not followed; ≥50 % failures over ≥2 judged on that kind of scene |
| No model reaches the tier: escalate, never downgrade silently | CODE_RULE → OWNER | `backend/app/media/production_policy.py:2894-2917` | `NEEDS_OWNER` with `best_available` (the best model lacking only quality) |
| Required quality per tier | CONFIG | `backend/app/media/production_policy.py:651-655`, `backend/app/media/production_policy.py:683-691` | STANDARD 0.80, PREMIUM 0.88, HERO 0.93 (`config/film_models.json` `hero_threshold` 0.93 overrides HERO) |
| Scene tier | CODE_RULE | `backend/app/media/production_policy.py:2414-2420` | stated `tier`/`quality_tier` if valid, else scene 1 = HERO, others STANDARD |
| Scene needs people/water/fast motion | CODE_RULE on LLM-written prompt text | `backend/app/media/production_policy.py:2421-2444` | regex over still/motion prompts, motion intent, visual prompt/description after stripping "Avoid:"/"no …" clauses |
| A scene with two SAFETY refusals | CODE_RULE | `backend/app/media/production_policy.py:2792-2798` | `len(safety) > MAX_SAFETY_MOVES (1)` → `NEEDS_STILL` (picture back to the stills gate) |
| Retry ladder per scene | CODE_RULE | `backend/app/media/production_policy.py:2947-2965` | one TRANSIENT/BAD_OUTPUT/QUALITY failure → retry once; two → `NEEDS_OWNER`; any UNKNOWN → `NEEDS_OWNER` |
| Vendor failure kind and action | CODE_RULE on EXTERNAL | `backend/app/media/production_policy.py:2257-2369` | ACCOUNT stop; SAFETY move; BAD_OUTPUT retry; TRANSIENT retry; QUALITY retry; STUDIO_DEFECT stop; CONTRACT move (second in a row stop); else UNKNOWN to the Owner |
| After a failure only that scene changes; a move over the cap goes to the Owner | CODE_RULE | `backend/app/media/production_policy.py:3182-3269` | others kept/overridden; `OVER_CAP` → hold for the failed scene; `stop_step` → `STOPPED` |
| A plan buys nothing when over budget or cap | CODE_RULE | `backend/app/media/production_policy.py:3087-3098` | `OVER_BUDGET` (total > budget) or `OVER_CAP` (spent + remaining > cap) → `to_buy = []` |
| A step's hard cap | CODE_RULE | `backend/app/media/production_policy.py:3058`, `backend/app/media/cost_plan.py:468` | total + dearest single shot + one more round of stills (unless an approved cap is given) |
| A scene longer than any clip even slowed | CODE_RULE → Director's repair | `backend/app/media/production_policy.py:2753-2774` | > longest × 1.25 → `too_long`, a sheet BLOCK |
| A longer scene billed at the model's longest clip | CODE_RULE | `backend/app/media/cost_plan.py:236-255` | scene ≤ longest × (1 + 0.25) |
| Billed seconds | CODE_RULE + EXTERNAL (vendor contract) | `backend/app/media/cost_plan.py:185-215` | ceil to whole seconds, then the smallest legal length (`values`) or clamp to `min`, refuse above `max` |
| A price the table does not list | CODE_RULE | `backend/app/media/cost_plan.py:123-129` | `UnpricedError`, never a guess |
| Price label shown to the Owner | CODE_RULE | `backend/app/media/cost_plan.py:304-319` | older than 30 days → `nevalidat`; MEASURED → `măsurat`; ESTIMATED → GPU estimate; else `tarif publicat dd.mm` |
| A model's quality figure | CODE_RULE over CONFIG, LLM-written research and the studio's own results | `backend/app/media/production_policy.py:3290-3322`, `backend/app/media/production_policy.py:856-868` | layers: unsourced row < `film_models.json` < measured/sourced row, field by field (a field the file leaves null keeps the unsourced row's value); own acceptance blended once ≥3 judged, weight `min(1, judged/10)` (it replaces research fully only at 10 judged); unknown → 0.5, or for a RunPod model the pinned `api_metadata.quality_score` when research has none (`:3399-3404`) |
| Organization → channel → series → episode → scene resolution | CONFIG / OWNER | `backend/app/media/production_policy.py:1184-1253` | later levels override; `allow_production_override=False` stops the merge; CONSISTENCY_LOCKED ignores episode/scene technology keys |
| A locked character's voice and approved models | OWNER | `backend/app/media/production_policy.py:1257-1300`, `backend/app/media/production_policy.py:1303-1364` | binding wins; another model only from `approved_fallbacks_json`; a visual lock invalidates an unapproved video model |
| Second vendor per purpose | OWNER (approved list) + CODE_RULE | `backend/app/media/production_policy.py:1415-1485` | at most `MAX_FALLBACKS_PER_PURPOSE` (1), validated, approved for every locked character |
| `auto` strategy model/voice | CODE_RULE over stored annotations | `backend/app/media/production_policy.py:320-442`, `backend/app/media/production_policy.py:1320-1339` | weighted score; premium: frame first, within 0.1 of best quality, then cheapest |
| Legacy per-scene model choice (`choose_model`) | CODE_RULE | `backend/app/media/production_policy.py:908-1116` | TEST: cheapest compatible within test ceilings; PRODUCTION: admitted, frame, budget, least expensive meeting tier |
| Identity change state | OWNER | `backend/app/media/production_policy.py:1976-2032` | PROPOSED → TESTING/APPROVED/REJECTED; TESTING → APPROVED/REJECTED; APPROVED applies the change |
| An abandoned lease is taken back | CODE_RULE | `backend/app/media/shooting_sheet.py:2204-2262` | lapsed, or (at process start) acquired before start and standing further than now + 360 s; holds released, event, letter |
| Measured and quoted prices overwrite stored ones | EXTERNAL + CODE_RULE | `backend/app/media/production_policy.py:445-538` | measured: any change, `BILLED`; quoted: past `tolerance_percent`, `ESTIMATED` |

## LLM involvement

**No LLM call site exists in these four files.** No function here calls `run_agent_task`, `structured_run`, `run_with_strategy`, `reviews._run` or `prompt_agent._run`. All 207 functions are deterministic code. Five functions (2.4 % of the group, 808 of 8579 lines) reach the LLM indirectly through other modules; none of them uses a model answer itself — the answers are consumed inside the stages and QC modules they call.

Callbacks checked by hand (the static graph does not resolve them): `face_counter` is `app.media.faces.count_faces`, a local OpenCV count (`backend/app/media/router.py:837-849`); `image_adapter`, `adapter_for_model`, `account` and the TTS adapters are media vendors (RunPod, Runway, ComfyUI, ElevenLabs), not language models; `registry` is only passed through to `stills_stage`, `assembler`, `qc` and `sound_design`, where the LOOKERS' vision calls, the Director's second look at a refused still or clip (`second_look._look`, `backend/app/media/second_look.py:653`, reached through `fix_check.director_second_look`, `backend/app/media/fix_check.py:642`) and the Voice Artist's sound plan below use it (`backend/app/media/shooting_sheet.py:3160`, `:3183`, `:3461`, `:3500`, `:3985`, `:4046`, `:4118`). No ensemble or review gateway is reached from here.

### Functions that reach the LLM indirectly

Paths are from the static call graph (`docs/project/backend_map/callgraph.json`), shortest first.

| Function here | Path to the call site | Call site and speaker | What the model does there | Can it lead to spending? |
|---|---|---|---|---|
| `recover_paid_takes` (`backend/app/media/shooting_sheet.py:3130`) | → `stills_stage.settle_stills` → `picture_qc.judge_still` | `backend/app/media/picture_qc.py:1765`, the LOOKERS (`VideoEditor`, `Director`, `QualityAssurance`, `backend/app/media/picture_qc.py:119`) | Vision judgement of already-paid candidate stills | No media purchase ("nothing is bought and no yes is asked", `backend/app/media/shooting_sheet.py:3147-3149`); LLM tokens only |
| `recover_paid_takes` | → `stills_stage.settle_stills` → `_settle_pending` → `_director_looks` → `fix_check.director_second_look` → `second_look.second_look` → `second_look._look` | `backend/app/media/second_look.py:653`, the Director on her seeing model (`structured_run`, task `director_second_look`, `:720`) | When the gate refused every collected candidate of a scene, she looks at the ones `still_gate.may_be_overturned` allows (`backend/app/media/still_gate.py:1118-1130`); a candidate her look lets stand (`fix_check.look_accepts`, `backend/app/media/fix_check.py:693-703`) is set APPROVED with `approved_by = "director_look"` (`backend/app/media/stills_stage.py:1250-1268`, `:1017-1035`) | No: a look buys nothing; it can only spare the scene's next purchase |
| `recover_paid_takes` | → `assembler.check_unchecked_shots` → `assembler._check_shot` → `picture_qc.judge_clip`, and → `fix_check.shot_second_look` → … → `second_look._look` | `backend/app/media/picture_qc.py:2074`, the LOOKERS; `second_look._look`, the Director | Clip QC of paid shots nobody checked; a refusal `qc.look_may_overturn` allows (`backend/app/media/qc.py:2588-2606`) is shown to the Director, and a clip her look keeps is recorded PASSED with `accepted_by: director_look` and its take stays PAID (ACCEPTED_BY_LOOK, `backend/app/media/qc.py:2670-2683`, `backend/app/media/assembler.py:10361-10373`) | No ("vision tokens only, no retry bought", `backend/app/media/shooting_sheet.py:3147`) |
| `run_sheet_step` / `_run_sheet_step` (`backend/app/media/shooting_sheet.py:3193`, `:3272`) | → `stills_stage.run_stills_stage` → `picture_qc.judge_still`; → `stills_stage._settle_round` → `_director_looks` → … → `second_look._look` | `judge_still`, the LOOKERS; `second_look._look`, the Director | Stills gate: which candidate is kept, which scene is re-rolled. Since `20abffd`, a round the gate refused whole goes to the Director's second look before a re-roll is bought, and before the scene goes to the Owner or to her ladder (`backend/app/media/stills_stage.py:1110-1184`, look at `:1143-1149`): a candidate she lets stand is APPROVED by her and nothing more is bought; her confirmation travels with the re-roll as `director_confirmed`. A still that shows its plan and repeats a mistake its corrected words were meant to fix is not re-rolled at all (`still_gate.next_step` action `rewrite`, `backend/app/media/still_gate.py:1160-1183`; `round_step`, `:1198-1213`): the scene ends NEEDS_OWNER with `rewrite: True` for the Director's ladder (`backend/app/media/stills_stage.py:1173-1183`); one that also missed its plan gets at most one re-roll on those words (`PERSISTS_REROLLS`, `backend/app/media/still_gate.py:199`) | Yes, inside the stage: a re-roll round is bought under the approved cap and per-purchase balance re-read, only after her look did not let a candidate stand |
| same | → `assembler.run_motion_step` → `assembler._check_shot` → `picture_qc.judge_clip`, and → `fix_check.shot_second_look` → … → `second_look._look` | `judge_clip`, the LOOKERS; `second_look._look`, the Director | Clip QC of each bought shot; a failed clip may buy one retry inside the cap. Since `20abffd` the Director looks first at a refusal `qc.look_may_overturn` allows, before the retry and again before an escalation after a failed retry (`qc.qc_clip_with_retry`, `backend/app/media/qc.py:2626-2763`, looks at `:2670`, `:2737`); a clip she keeps is ACCEPTED_BY_LOOK and nothing more is bought. A clip that shows its plan and repeats a mistake its rewritten movement was meant to fix escalates without a retry (`clip_retry_decision`, `backend/app/media/qc.py:2515-2529`) | Yes, one clip-QC retry within the approved cap, only when her look did not keep the clip |
| same | → `run_motion_step` → `redo_scene` → `_free_redo` → `repair_audio` → `_replan_sound` → `sound_design.sound_plan` | `backend/app/media/sound_design.py:379`, the Voice Artist | Sound plan of a free audio repair | No (free redo path) |
| `run_assemble_step` (`backend/app/media/shooting_sheet.py:3786`) | → `assembler.assemble_from_takes` → `assemble_video_job` → `film_mix` → `sound_design.sound_plan` | `sound_plan`, the Voice Artist | The film's music/ambience plan for the mix | No media purchase (music from the Owner's library) |
| `run_assemble_step` | → `qc.evaluate_media_qc` → `picture_qc.evaluate_pictures` (and `span_picture_qc` → `judge_clip`) | `backend/app/media/picture_qc.py:904` | Picture QC of the finished film; result goes into the QC letter | Not here; the QC verdict feeds the Director's repair loop elsewhere |
| `_with_redos` (`backend/app/media/shooting_sheet.py:4087`) | → `assembler.propose_clip_redos` → `redo_scene` → (`_judge_paid_stills_first` → `settle_stills` → `judge_still`, and `_settle_pending` → `_director_looks` → … → `second_look._look`) or (`_paid_redo` → `run_motion_step` → `judge_clip`, and `_check_shot` → `fix_check.shot_second_look` → … → `second_look._look`) or (`_free_redo` → … → `sound_plan`) | `judge_still`, `judge_clip`, `second_look._look` (the Director), `sound_plan` | Raising a paid motion redo for a CLIP_SHORT scene | Would ask the Owner under the paid-media rule; **unreachable at runtime**: no caller passes `redo_wiring` (see Oddities) |

### LLM-written data that deterministic code here consumes

These are not call sites, but model output that reaches decisions in this group:

| Data | Written by (LLM) | Used here | How code limits it |
|---|---|---|---|
| Still/motion prompts, motion intent (`StoryboardScene.prompt_json`) | shot-plan model (`media.prompt_agent.write_shot_prompts`) | `need_from_scene` regexes decide people/water/fast-motion needs (`backend/app/media/production_policy.py:2421-2444`), which choose per-need quality and so the model and price; the exact prompt text is hashed into `sheet_hash` (`backend/app/media/shooting_sheet.py:1401-1423`) and linted (`backend/app/media/shooting_sheet.py:1425`) | "Avoid:"/"no …" clauses stripped (`backend/app/media/production_policy.py:2130-2136`); lint BLOCK stops every purchase (`backend/app/media/shooting_sheet.py:3332`); template prompts refused in PRODUCTION (`backend/app/media/shooting_sheet.py:3324`) |
| `camera_move` | shot-plan model, clamped to `lint.CAMERA_MOVES` (`backend/app/media/prompt_agent.py:1516-1518`) | excludes models whose `camera_moves` do not include it (`backend/app/media/production_policy.py:2526-2529`) | clamp to the known list upstream |
| `ProviderResource.capabilities.quality_score`, `reliability_score`, `latency_score`; `pricing` | the model steward (`media.model_research.research_models`, an LLM call site; written without a `basis` or `sources` key, `backend/app/media/model_research.py:386-399`) | `rank_candidates` scores and `choose_model` quality and price use them directly (`backend/app/media/production_policy.py:368-378`, `:961-964`); `model_research` treats them as the lowest layer «estimat» (`backend/app/media/production_policy.py:3297-3308`) | in the sheet planner `config/film_models.json` outranks them only field by field, where the file states a value (`backend/app/media/production_policy.py:3309-3321`). The file leaves `quality_score` null for four allowed models (`seedance2_fast`, `seedance2_mini`, `wan3_prime`, `h3_max`) and lists no RunPod or ComfyUI model, so for those an unsourced steward score is the planner's quality (labelled «estimat») and decides whether the model reaches the tier; for a RunPod model it also outranks the pinned `config/runpod_models.json` score (`:3399-3404`). Only range validation applies (0..1, `_score`). The studio's own judged results are blended in from 3 judgements, weight `min(1, judged/10)`, and replace them fully at 10 (`:856-868`); prices in the sheet come from `config/runway_prices.json` plus measured, local and RunPod-estimated overlays (`price_table_for`), not from these rows |
| The connection's default model `MediaProductionConfig.model_id` (on a RunPod or ComfyUI connection: `ModelCapability.selected_default`) | the Owner in Settings; or, when `allow_production_override` is on, the weekly model steward's recommendation (`media.model_research.research_models`, an LLM call site, `backend/app/media/model_research.py:417-455`) or `integrations.autoconfig` (first of `rank_candidates`, `backend/app/integrations/autoconfig.py:209-240`) | `_choose_scene` takes the selected RunPod default for every scene unasked by quality (`backend/app/media/production_policy.py:2839-2861`); `motion_clip_limit` measures scene lengths against it (`backend/app/media/shooting_sheet.py:4224-4246`) | the recommendation must be a ranked candidate and `production_resource`-usable (`backend/app/media/model_research.py:427-438`); in the planner it still needs a price row and must not be blocked by a non-quality shortfall (allowed set, admission, frame, camera move, failure history); every clip is still clip-QC'd and every purchase still passes `may_act` |
| Clip-QC and stills-gate verdicts (vision), and the Director's second look at a refused still or clip | the LOOKERS; the Director (`second_look._look`, `backend/app/media/second_look.py:653`) | take statuses, `hero_acceptances`, `assembly_readiness` shown on the sheet and gating the motion and assemble steps (`backend/app/media/shooting_sheet.py:1129-1160`, `:1246-1249`). A hero test shot whose clip-QC report passed may be accepted under the Owner's paid-media rule (`hero_gate` status ACCEPTS/ACCEPTED, `backend/app/media/assembler.py:9917-9940`), which lets the motion step buy the rest of the film; that acceptance is hashed into the sheet (`accepted_by`, `backend/app/media/shooting_sheet.py:1421`). Since `20abffd` a clip that clip QC refused and her look kept is recorded with verdict PASSED and `accepted_by: director_look` (`backend/app/media/assembler.py:10365-10373`); `hero_gate` reads only the newest clip-QC record's verdict (`backend/app/media/assembler.py:10006-10010`), so a hero clip she kept counts as passed. A still her look let stand is APPROVED with `approved_by = "director_look"` (`backend/app/media/stills_stage.py:1017-1035`) and is the scene's approved still on the sheet | rules in `assembler`/`picture_qc`/`qc`/`fix_check` (out of scope); she is asked only about refusals code lets her overturn: the bible's hard limits (faces where forbidden, writing, panels, a degenerate picture, `backend/app/media/fix_check.py:130`), unmeasured checks and a still's fault on a clip stay the code's (`backend/app/media/still_gate.py:1118-1130`, `backend/app/media/qc.py:2588-2606`); hero acceptance only when the Owner's rule and mode allow it (`rule_accepts`, `backend/app/media/shooting_sheet.py:1529`); the hero take's APPROVED stays the Owner's (a clip she keeps stays PAID) |

**How much is LLM here:** 0 of 207 functions call a model; no decision in this group acts on a model answer it asked for. Model output enters only as stored data that code reads with fixed rules (regex over prompts, the camera-move clamp, hashes, the research layering), or through verdicts produced in other modules. Since `20abffd` one of those verdicts is the Director's second look at a refused still or clip, asked inside the stills stage and clip QC before a re-roll or retry is bought: within the refusals code lets her see, her verdict is final; it buys nothing itself and can spare the re-roll or retry, but a still or hero clip she keeps then lets the film go on to its next paid stair under the unchanged money gates (`backend/app/media/stills_stage.py:1143-1149`, `backend/app/media/qc.py:2670-2683`, `:2737-2751`). Two of the stored-data paths carry real weight and are easy to miss: an unsourced steward quality score is the planner's quality wherever `config/film_models.json` is silent (always for RunPod/ComfyUI models), and the connection default that the planner takes unasked by quality on RunPod can have been written by the steward's weekly recommendation (see the table above and Oddities 21-22). In both cases code still checks price, admission, frame, camera move and failure history, and the Owner's mode and `may_act` still gate the purchase.

## Hard rules and limits

| Rule | Value | Where |
|---|---|---|
| Balance margin default | 1.15 (`DEFAULT_MARGIN`); setting `paid_step_balance_margin` 1.0–3.0 | `backend/app/media/balance_rule.py:39`, `backend/app/config.py:286` |
| Need rounding | `ceil(round(price × margin, 6))` (20 × 1.15 = 23, 144 × 1.15 = 166) | `backend/app/media/balance_rule.py:52-58` |
| Price table | `config/runway_prices.json`, `credit_usd` 0.01, rows dated 2026-09-27, all DOCUMENTED | `backend/app/media/cost_plan.py:39` |
| Price staleness | 30 days → «nevalidat» | `backend/app/media/cost_plan.py:42`, `:304-308` |
| Stills purchase | `seedream5_pro` at 2K, 2 candidates per scene (9 credits each in the table) | `backend/app/media/cost_plan.py:51-53` |
| Premium reference | `seedance2_5` at 1080p (also `premium_reference` in `config/film_models.json`) | `backend/app/media/cost_plan.py:56` |
| Whole-film alternatives priced on the sheet | each scene's own model at 720p; `seedance2` 1080p; `veo3.1_fast` 1080p | `backend/app/media/cost_plan.py:60-64` |
| Local slow-down allowance | 0.25 (a 10 s clip fills 12.5 s) | `backend/app/media/cost_plan.py:74` |
| Credits are whole, rounded up | `ceil(amount − 1e-9)`; shot price never below `minimum_credits` | `backend/app/media/cost_plan.py:258-260`, `:282` |
| Credits → USD micros | Decimal, half up | `backend/app/media/cost_plan.py:295-298` |
| Step cap formula | total + dearest shot + one more round of stills | `backend/app/media/cost_plan.py:468`, `backend/app/media/production_policy.py:3058` |
| Quality tiers | STANDARD 0.80, PREMIUM 0.88, HERO 0.93 (`hero_threshold` 0.93 in `config/film_models.json`) | `backend/app/media/production_policy.py:651-655` |
| Scene roles | HOOK→HERO, ENDING/KEY→PREMIUM, NORMAL/TRANSITION/BACKGROUND→STANDARD; scene 1 = HOOK, last = ENDING. The sheet planner's `need_from_scene` uses only HOOK→HERO: with no stated tier the last scene is STANDARD there, not PREMIUM (`:2417-2420`) | `backend/app/media/production_policy.py:660-680` |
| Unknown quality | 0.5 (below every tier) | `backend/app/media/production_policy.py:3399-3400`, `:370` |
| Own results outweigh research | from 3 judged generations; weight `min(1, judged/10)` | `backend/app/media/production_policy.py:865-868` |
| Failure-history exclusion | ≥2 judged and ≥50 % failed on that kind of scene (SAFETY refusals not counted) | `backend/app/media/production_policy.py:2075-2076`, `:3362-3363` |
| Moving vs retry failures | move: SAFETY, CONTRACT; retry once: TRANSIENT, BAD_OUTPUT, QUALITY | `backend/app/media/production_policy.py:2079-2081` |
| Safety moves per scene | 1 (the second sends the picture back to the stills gate) | `backend/app/media/production_policy.py:2083` |
| Account-failure detection | HTTP 401/402/403, code `ACCOUNT*`, or text "insufficient / not enough credits / out of credits / credit balance / fonduri insuficiente" | `backend/app/media/production_policy.py:2091-2094`, `:2276-2287` |
| Transient detection | `THIRD_PARTY.UNAVAILABLE*`, `INTERNAL`, `INTERNAL.*` (after `INTERNAL.BAD_OUTPUT*`, which is BAD_OUTPUT), HTTP 408/429/500/502/503/504 | `backend/app/media/production_policy.py:2299-2319` |
| Other failure codes (checked in this order after ACCOUNT) | SAFETY: code starts `SAFETY` or contains `.SAFETY`; QUALITY: `QC.*` or `CLIP_QC`; STUDIO_DEFECT: HTTP 400/422 whose text matches a pattern; CONTRACT: HTTP 400/422 or code starting `INPUT_PREPROCESSING`, `ASSET`, `INVALID` (a second in a row stops the step); anything else UNKNOWN | `backend/app/media/production_policy.py:2288-2369` |
| Studio-defect patterns | `must use auto_<n>p`, `Data URI is too large` (on 400/422) | `backend/app/media/production_policy.py:2102-2105` |
| Vendor error text kept | 500 characters, control characters stripped | `backend/app/media/production_policy.py:2089`, `:2250-2254` |
| Studio frame | 1080:1920; 720p → 720:1280 | `backend/app/media/production_policy.py:260`, `:2086` |
| `auto` ranking weights | premium 0.6/0.25/0.1/0.05 (quality/reliability/speed/cost); balanced 0.25 each; thrifty 0.2/0.2/0.1/0.5; quality band 0.1 | `backend/app/media/production_policy.py:245-255` |
| Fallback vendors per purpose | 1 | `backend/app/media/production_policy.py:112` |
| Identity-change transitions | PROPOSED→{TESTING, APPROVED, REJECTED}; TESTING→{APPROVED, REJECTED}; one open change per field | `backend/app/media/production_policy.py:88-93`, `:1858-1866` |
| Lease ceiling | `film_purchase_lease_seconds` default 10,800 s (600–86,400) | `backend/app/media/shooting_sheet.py:1916`, `backend/app/config.py:275` |
| Lease renewal | every 60 s, never more than 300 s ahead; keeper join timeout 30 s | `backend/app/media/shooting_sheet.py:1918`, `:1923`, `:2166` |
| Abandoned-lease window at process start | expires beyond now + 360 s and acquired before the start | `backend/app/media/shooting_sheet.py:2227-2241` |
| Film ceiling default | `motion_budget_usd` 12.0 + 18 credits × (1 + `MAX_REROLLS` 2) × 6 scenes × 0.01 = 15.24 USD; `film_budget_usd` overrides | `backend/app/media/shooting_sheet.py:2632-2654`, `backend/app/media/still_gate.py:196`, `backend/app/config.py:258-269` |
| Film ceiling scope | PRODUCTION only | `backend/app/media/shooting_sheet.py:2693-2694` |
| Booking reference | ≤120 characters, `prefix:correlation` | `backend/app/media/shooting_sheet.py:2887`, `:2894-2897` |
| Default film resolution | 1080p (setting `motion_resolution` 1080p or 720p) | `backend/app/media/shooting_sheet.py:218`, `backend/app/config.py:279` |
| Step tiers | stills `media.stills_purchase` T2; test shot `media.test_shot` T3; motion `media.motion_purchase` T3; narration `media.paid_generation` T2 / `media.paid_generation_over_threshold` T3 | `backend/app/media/shooting_sheet.py:27-33` (docstring), enforced by `ACTION_RISK_TIERS` at `backend/app/services.py:488`, `:492`, `:503-505` |
| Narration threshold | `paid_generation_approval_threshold_usd` default 5.0 USD | `backend/app/config.py:392`, `backend/app/media/shooting_sheet.py:3938` |
| Card preview | span ≥ 2.5 s; ffmpeg timeout 60 s | `backend/app/media/shooting_sheet.py:4323`, `:4366` |

**State machines in this group**

- Sheet step refusals (`SheetStepRefused.status`): `UNKNOWN_STEP`, `FILM_BUSY`, `FILM_CLOSED`, `STALE_PLAN`, `NEEDS_SHOT_PLAN`, `LINT_BLOCKED`, `NOTHING_TO_BUY`, kernel statuses for unasked steps, `LOW_BALANCE`, `OVER_FILM_BUDGET`, `OVER_DAILY_BUDGET`, `OVER_BUDGET`, `NO_ADAPTER`, the stages' own statuses (`NEEDS_APPROVAL` is 202, all others 409), and for assembly `TAKES_NOT_ACCEPTED`, `TAKES_MISSING`, `STOPPED`, `NO_ENGINE`, `REFUSED` (`backend/app/media/shooting_sheet.py:248-299`). A stage failure after payment is `SpentStageError` (route answers 409 `SPENT_AND_STOPPED`, `backend/app/media/router.py:212-222`).
- Per-scene plan status: `COMPOSED`, `LOCAL`, `PLANNED`, `BOUGHT`, `NEEDS_OWNER`, `NEEDS_STILL` (`backend/app/media/production_policy.py:2633-2966`). Plan status: `READY`, `NEEDS_OWNER`, `OVER_CAP`, `OVER_BUDGET`, and `STOPPED` after a stopping failure (`backend/app/media/production_policy.py:3087-3098`, `:3266-3268`).
- Failure verdict actions: `move_scene`, `retry_same`, `stop_step`, `needs_owner` (`backend/app/media/production_policy.py:2224-2247`).
- Lease: none → held (expires ≤ min(start + ttl, now + 300 s)) → renewed every 60 s → given back, or lapsed → reclaimed with a letter (`backend/app/media/shooting_sheet.py:2047-2262`).
- Character consistency: UNVERIFIED → CONSISTENT (first voice binding) → CHANGE_PENDING (proposal) → CONSISTENT/UNVERIFIED after the decision (`backend/app/media/production_policy.py:1778-1779`, `:1879`, `:2000-2005`).

**The gate order of a sheet step** (`run_sheet_step` → `_run_sheet_step`): unknown step → lease (FILM_BUSY/FILM_CLOSED) → recompute sheet → STALE_PLAN → NEEDS_SHOT_PLAN (PRODUCTION) → LINT_BLOCKED → NOTHING_TO_BUY → (unasked only) mode → balance readable → balance ≥ next round × margin (reading recorded) → film ceiling (PRODUCTION) → budget reservation → adapter present → stage (`may_act` per purchase, per-purchase balance, cap; since `20abffd` the Director's second look before a still re-roll or a clip retry is bought) → booking → reservation settled/released → low-balance card if the stage stopped a scene on the balance (`backend/app/media/shooting_sheet.py:3234-3585`).

## Modules

### `app.media.balance_rule` — backend/app/media/balance_rule.py (158 lines)

The Owner's rule of 2026-10-03 («Doar pentru runda următoare»): to start a paid media step the vendor balance must hold the cost of its next round × margin; before each further purchase the balance is re-read and must hold that purchase × margin; the approved cap stays the step's absolute ceiling; an unreadable balance stops the step (`backend/app/media/balance_rule.py:1-25`, `docs/project/16_DECISION_LOG.md:4157`). This module holds the arithmetic and the Romanian sentences; the stills stage, the motion step, the redo and the sheet all import it.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `margin_of` | 46 | Settings' `paid_step_balance_margin`, else 1.15 | One source for the margin | CONFIG |
| `needed_credits` | 52 | `max(0, ceil(round(price × margin, 6)))` | Floating-point safe need (23, not 24, for 20 × 1.15) | CODE_RULE |
| `missing_credits` | 61 | Credits the account lacks (0 when covered) | Card and letter figure for a top-up | CODE_RULE |
| `start_refusal_ro` | 74 | Romanian refusal: balance, next round, margin, need, cap, top-up | The Owner's words when a step does not start | CODE_RULE (text) |
| `round_line_ro` | 91 | Sheet line under a step: starts on X credits, round cost, cap | Shows the rule before a press | CODE_RULE (text) |
| `purchase_stop_ro` | 102 | Romanian reason a scene stops before its next purchase | Per-purchase stop wording | CODE_RULE (text) |
| `low_balance_record` | 115 | The step summary's `low_balance` dict | Fed to the Owner's low-balance card | CODE_RULE |
| `record_balance_reading` | 130 | Appends `media.paid_step_balance_read` behind the write lock | The card clears on the books, never on a vendor call from the feed | CODE_RULE |

Helpers: `_credits` (floored count with Romanian plural), `_percent` (margin as whole percent).

Data: writes `DomainEvent` `media.paid_step_balance_read` (`backend/app/media/balance_rule.py:43`). No external calls, no money.

### `app.media.cost_plan` — backend/app/media/cost_plan.py (608 lines)

What a film costs before a credit is spent: the published table and pure arithmetic, no database and no network (`backend/app/media/cost_plan.py:1-23`). Three rules: billed seconds rounded UP to a length the model accepts; the model chosen per scene; an unlisted model or resolution is unpriced, never guessed. MEASURED rows from the account outrank the page through `apply_measured`; `app.economy.credits` writes them back.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `PriceRow.as_dict` | 98 | Row as dict | Serialisation | — |
| `PriceTable.round_overhead` | 117 | Whole credits one paid round adds for a round-priced model (RunPod cold start + idle), else 0 | RunPod Serverless bills per batch round (`docs/project/16_DECISION_LOG.md:4212`) | CODE_RULE |
| `PriceTable.row` | 123 | Row for model at resolution, else its `*` row, else `UnpricedError` | Never a guessed price | CODE_RULE |
| `_row_from_json` | 132 | Parses one JSON row; kind inferred from per-image price; keeps documented rates | Table loading | CODE_RULE |
| `load_price_table` | 173 | Cached published table (`_load`, `lru_cache` by path) | Immutable base table | CONFIG |
| `billable_seconds` | 185 | Ceil to whole seconds, then the smallest legal `values` length or `min`..`max`; above max → `UnpricedError` | Rounding down froze frames under the Nepal dissolves | CODE_RULE + EXTERNAL contract |
| `longest_seconds` | 218 | Longest single clip from contract or table | Slow-down and too-long checks | CODE_RULE |
| `slowed_clip_seconds` | 236 | The longest clip when slowing ≤25 % fills the scene, else None | NASA film 2026-10-10 could never be assembled | CODE_RULE |
| `price_shot` | 263 | Credits for one shot (audio rate when asked; minimum credits) | Per-shot price | CODE_RULE |
| `price_still` | 285 | Credits for N images | Stills price | CODE_RULE |
| `credits_to_micros` | 295 | Credits × credit_usd × 1e6, Decimal half-up | Exact books amounts | CODE_RULE |
| `row_status` | 304 | `validat` within 30 days, else `nevalidat` | Stale prices are flagged to the Owner | CODE_RULE |
| `source_label` | 311 | «tarif publicat dd.mm», «măsurat», GPU estimate, or «nevalidat» | The Owner reads where each price comes from | CODE_RULE |
| `_price_scenes` | 363 | Prices every LIVE scene (shot + 2 stills), 0 for others; optional whole-film override | Core of `plan_film` | CODE_RULE |
| `plan_film` | 415 | The money staircase: stills, hero, rest, total, cap (total + dearest + stills), premium saving, priced alternatives | Price a film at 0 credits; used for the sheet's whole-film alternatives | CODE_RULE |
| `attribute_measured_credits` | 530 | Shares a measured balance drop across what was bought (exact for one group, proportional otherwise) and builds MEASURED rows | What the account was charged outranks the page | CODE_RULE + EXTERNAL |
| `apply_measured` | 602 | New table with MEASURED rows laid over documented ones | Overlay without mutating the base | CODE_RULE |

Helpers: `_load` (JSON → `PriceTable`), `_table` (default table), `_credits` (ceil), `_film_source` (one label for several rows), `_scenes` (normalise spans or mappings into scene dicts).

Data: reads `config/runway_prices.json` (`backend/app/media/cost_plan.py:39`). No database, no events, no network, no money. Note that `_load` does not fill `overhead_credits_per_round` or `round_models`; RunPod overlays add them (`backend/app/providers/runpod/pricing.py:31-35`).

### `app.media.production_policy` — backend/app/media/production_policy.py (3445 lines)

Two jobs. (1) **Which technology a video is made with and what may never change**: the configuration hierarchy (Organization default from `ServiceSelection` + `MediaProductionConfig`; channel `production_defaults_json`; series `series_rules_json`; episode `Storyboard.production_overrides_json`; scene `StoryboardScene.production_overrides_json`; character voice binding under `identity_locks_json`), with identity locks and Owner-approved fallbacks; "nothing in this module names a channel, a model, a voice or a price: every value comes from a row" (`backend/app/media/production_policy.py:1-25`). (2) **The per-scene motion-model planner** that prices a film on the cheapest capable model per scene and classifies vendor failures (`backend/app/media/production_policy.py:2043-2055`). Everything in part 2 is pure except `scene_model_capabilities`.

#### Hierarchy, views and the Owner's commands

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `channel_policy_view` | 122 | Channel policy fields as dict | API view | — |
| `character_identity_view` | 131 | Voice binding, locks, approved fallbacks, consistency status | API view | — |
| `identity_change_view` | 140 | Identity change row as dict | API view | — |
| `organization_default` | 161 | Org-level selection for a purpose: integration, model (image default for `image`), voice, and whether overrides are allowed | Base of the hierarchy | CONFIG (Owner settings rows) |
| `_apply` | 200 | Copies the keys a level sets onto the merge | Hierarchy merge | CODE_RULE |
| `resolve_purpose` | 1184 | Walks the hierarchy for one purpose; applies `allow_production_override`, CONSISTENCY_LOCKED (episode/scene technology keys ignored), voice lock (binding wins; model only from approved fallbacks), visual lock (video model must be approved, else `valid=False`), `auto` ranking, validation, approved fallbacks; returns the deciding level and notes | Auditable "what production must use" | CONFIG + OWNER + CODE_RULE |
| `_fallback_entries` | 1390 | Approved-fallback list as `{integration_id, model_id[, voice_id]}`, deduplicated | A free-text name would resolve to nothing | CODE_RULE |
| `approved_alternatives` | 1415 | The Owner's approved second vendors for a purpose, narrowed by every locked character's approval, validated, at most 1 | Never invent an alternative: it is a purchase from another account | OWNER + CODE_RULE |
| `_validate` | 1488 | A selection must name an existing, VERIFIED/ACCESS_VERIFIED connection and discovered, available model (and voice for voice purposes) | No production on undiscovered resources | CODE_RULE |
| `named_model` | 1524 | The video model a deliberate level (channel, series, episode, scene, character) named for a scene | A person's choice is honoured over the ranking | CODE_RULE |
| `resolve_storyboard_plan` | 1543 | Resolves every purpose for a storyboard and voice+video per scene with its characters in the scene's order | Render plan and `GET …/production-plan` | CODE_RULE |
| `_check_selection_shape` | 1618 | Validates purposes, keys, `strategy` in {fixed, auto}, `approved_fallbacks` as objects with `integration_id` | Refuse malformed policy writes | CODE_RULE |
| `set_channel_policy` | 1644 | Writes channel policy/defaults/series rules/override flag; event `channel.production_policy_set` | Owner's command (`PUT /channels/{channel_id}/production-policy`) | OWNER |
| `set_storyboard_production` | 1687 | Writes a storyboard's channel, series, overrides and scene overrides; event `media.storyboard_production_set`; returns the resolved plan | Owner's command (`PUT /storyboards/{id}/production`) | OWNER |
| `set_voice_binding` | 1756 | Binds a character to a discovered voice; refused when the voice is locked and differs; first binding marks CONSISTENT; event `character.voice_bound` | Identity protection | OWNER + CODE_RULE |
| `set_identity_locks` | 1805 | Sets voice/visual/personality/speech_style locks; a voice lock needs a binding; event `character.identity_locks_set` | Identity protection | OWNER |
| `propose_identity_change` | 1847 | Opens a PROPOSED change (one open per field), keeps the previous identity, marks CHANGE_PENDING; event | The only way to change a locked identity | OWNER (route is Owner-only) |
| `_apply_identity_change` | 1901 | Applies an approved change; for voice keeps the previous model as an approved fallback | Previous technology stays usable for the identity | CODE_RULE |
| `approve_model_fallback` | 1931 | Adds a model to a character's approved list (idempotent); event `character.model_fallback_approved` | How a newer model reaches a locked voice or look | OWNER (`POST /character-bible/{id}/approved-models`) |
| `decide_identity_change` | 1976 | Moves a change along `CHANGE_TRANSITIONS`; APPROVED applies it; writes an `OWNER_POLICY` memory | Audited identity decisions | OWNER |
| `list_identity_changes` | 2035 | Lists changes, newest first | `GET /identity-changes` | — |

Helpers: `_level_value` (a level's dict for a purpose), `_binding_resources_exist` (voice/model discovered), `_current_identity` (columns of a lockable field).

#### Ranking, prices and the legacy choice

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `same_ratio` | 272 | Whether two ratios reduce to the same shape | Frame checks | CODE_RULE |
| `reaches_frame` | 278 | Frame delivered: listed, or listed as its reduced ratio with declared output ≥ frame | RunPod lists "9:16" and outputs 1080×1920 | CODE_RULE |
| `delivers_studio_frame` | 294 | Whether the contract lets a model fill 1080:1920 for its purpose's tasks (unknown counts as able) | `seedance2_fast` stops at 720×1280 | CODE_RULE |
| `rank_candidates` | 320 | Scores available resources from stored annotations (quality, reliability, latency, price) with priority weights; language mismatch halves; premium order: frame first, within 0.1 of best quality, then cheapest | `auto` strategy and the steward's default; "equal footage at a third of the price wins" | CODE_RULE over LLM/steward-written data |
| `record_measured_price` | 445 | Writes the billed per-unit USD price over the stored one (`BILLED`, provenance kept) | The studio learns prices by using models | EXTERNAL + CODE_RULE |
| `record_quoted_price` | 491 | Replaces a stored price when a vendor quote drifts past tolerance (`ESTIMATED`) | Vendor dry run speaks about today's price | EXTERNAL + CODE_RULE |
| `credit_usd` | 541 | USD per vendor credit from the connection's config (the Owner's purchase) | Credits → money conversion | OWNER (connection config) |
| `cheapest_prompt_to_video` | 562 | Cheapest priced available `text_to_video` model needing no references | Test renders (no caller in `backend/app`, see Oddities) | CODE_RULE |
| `estimate_cost_usd` | 597 | Vendor-named credits × credit price, else per-1k-chars/per-image/per-second recorded prices, else None | Unpriced is reported, never counted as free | CODE_RULE |
| `scene_role` | 670 | Scene 1 = HOOK, last = ENDING, else NORMAL | Hook and ending carry the most weight | CODE_RULE |
| `required_quality` | 683 | Tier → quality; HERO from `hero_threshold` when set | Tier is a property of the scene, not of a model | CONFIG |
| `FilmModelCatalogue.allows` | 721 | Model in the Owner's allowed set (None: no restriction) | Planner never buys outside it | CONFIG |
| `_check_model` | 729 | Validates one catalogue entry (scores in 0..1, need names, camera moves list) | A malformed file is refused, never read as empty (Nepal shot plan lost to a silent discard) | CODE_RULE |
| `_read_film_models` | 751 | Parses `config/film_models.json`, cached by path+mtime+size | The Owner's edit applies without restart | CONFIG |
| `load_film_models` | 788 | Catalogue or an unrestricted empty one when the file is missing; raises `ValueError` on a bad file | Owner's three choices: allowed, hero threshold, premium reference | CONFIG |
| `model_record` | 817 | Generations, judged, acceptance, first-pass, cost per accepted second, technical failures from `ModelOutcome` | Only benchmarks and production teach quality | CODE_RULE |
| `_observed_quality` | 856 | Blends own acceptance with research after ≥3 judged | One lucky shot is not evidence | CODE_RULE |
| `choose_model` | 908 | Legacy per-scene choice: filters by availability, DEPRECATED (unless forced), purpose, tasks, references; TEST = cheapest within test ceilings; PRODUCTION = admitted, frame, budget, least expensive meeting tier, else best available (`met=False`); `forced` honoured | Used by `factory.motion_for_scene` (`backend/app/media/factory.py:606-613`); that legacy render path refuses real paid adapters since 2026-10-01 (`docs/project/16_DECISION_LOG.md:4080`) | CODE_RULE |
| `_within_test_ceilings` | 1123 | Refuses a TEST model whose known price exceeds the per-generation or per-second ceiling | "an unpriced test is how twenty-one dollars left the account" | CODE_RULE + CONFIG |
| `_decision` | 1144 | Decision dict with up to 4 alternatives | What the page shows and the job records | — |

Helpers: `_number` (0..1 or default), `_recorded_price` (first price key), `_ratio`, `_unit_price`, `_money`, `_score`.

#### The per-scene planner and failure classification

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `names_our_request` | 2110 | Whether a refusal text matches `STUDIO_DEFECT_PATTERNS` | Our own malformed request is the studio's defect | CODE_RULE |
| `SceneNeed.needs` / `.categories` | 2163 / 2166 | Need flags present; failure-history categories (`general` when none) | Need model | CODE_RULE |
| `ModelCapability.as_dict` / `.quality_for` | 2203 / 2206 | Dict view; per-need quality or overall | Capability model | — |
| `FailureRecord.as_dict` | 2220 | Dict view | — | — |
| `FailureVerdict.move_scene` / `.retry_same` / `.stop_step` | 2238 / 2242 / 2246 | Action predicates | — | — |
| `classify_failure` | 2257 | Sorts a vendor failure into ACCOUNT, SAFETY, BAD_OUTPUT, TRANSIENT, QUALITY, STUDIO_DEFECT, CONTRACT (second in a row stops), UNKNOWN, each with action, Romanian reason and whether the model is blamed | A refused input is never sent to the same model again; account problems stop; unknowns go to the Owner | CODE_RULE on EXTERNAL |
| `need_from_scene` | 2403 | Scene dict → `SceneNeed` (kind, tier, seconds, camera move, people/water/fast-motion from prompt words) | "Read from the words the models will receive, never guessed from the narration" | CODE_RULE on LLM-written text |
| `_price` | 2456 | Credits and billed seconds for a model on a scene, the slowed-clip fallback, or why it cannot be bought (and its longest clip) | Unpriced and too-long reasons | CODE_RULE |
| `_shortfalls` | 2497 | Blocking reasons (allowed set, admitted, refused here, i2v, frame, camera move, failure history) and quality-only reasons; effective quality | Explains every exclusion to the Owner | CODE_RULE + CONFIG |
| `_choose_scene` | 2587 | The per-scene decision ladder (see below) | The 2026-09-27 per-scene rule | CODE_RULE / OWNER / CONFIG |
| `plan_scene_models` | 2984 | Runs `_choose_scene` for every scene; totals, hero, cap, premium saving, committed spend, status, `to_buy`, Romanian summary, `plan_film_scenes` | The film costs the sum of its scenes; over cap or budget buys nothing | CODE_RULE |
| `replan_after_failure` | 3182 | Re-plans after one scene failed: others kept/overridden, bought frozen, approved cap binds; a move over the cap waits for the Owner; stopping failures set STOPPED | Only THAT scene may change | CODE_RULE |
| `model_research` | 3290 | Layers research: unsourced row («estimat») < documented file < measured/sourced row | MODEL_CATALOG rule | CODE_RULE |
| `scene_model_capabilities` | 3325 | Builds `ModelCapability` for every available, non-DEPRECATED model of a connection: contract (tasks, i2v ratios, durations, output), research layers, own judged outcomes and failure counts per category (SAFETY excluded), admitted flag, `owner_allowed` (ComfyUI, RunPod routes, or catalogue `allowed`), `selected_default` (ComfyUI/RunPod config) | The only DB-reading part of the planner | CODE_RULE + CONFIG |

Helpers: `_clean_detail`, `_ro_int`, `_ro_decimal`, `_ro_credits`, `_ro_usd`, `_ro_seconds` (Romanian figures), `_history` (normalises failure records per scene), `_option` (cheaper/better option view), `_premium_credits` (premium-everywhere motion price), `_needs_of` (valid need scores).

**`_choose_scene` ladder** (`backend/app/media/production_policy.py:2587-2966`), first match wins:

1. Composed kinds (DATA_CARD, TITLE_CARD, BLACK) → `COMPOSED`, 0 credits (`:2633-2639`).
2. Unknown kind → `NEEDS_OWNER` (`:2640-2646`).
3. Price every capability; capable = no shortfall; sorted by (slowed clip, credits, −quality, id) (`:2660-2700`).
4. More than one SAFETY refusal and not bought → `NEEDS_STILL` (`:2792-2798`).
5. Owner's LOCAL_MOVE and not bought → `LOCAL`, motion 0 credits, decided by owner (`:2800-2809`).
6. A named model (kept from an approved sheet / bought, or the Owner's override): not in the catalogue or unpriced → `NEEDS_OWNER`; else taken, shortfalls become warnings (`:2811-2838`).
7. Selected cloud (RunPod) default → taken if priced and lacking only quality, else `NEEDS_OWNER` (+ too-long check) (`:2839-2861`).
8. Selected local (ComfyUI) default → same, quality `None`, API cost zero (`:2862-2882`).
9. Cheapest capable model → `PLANNED`, decided by policy (`:2883-2893`).
10. Nothing capable: best quality-only candidate → `NEEDS_OWNER` with `best_available`; empty catalogue → `NEEDS_OWNER` "catalogul … este gol"; else `NEEDS_OWNER` listing every exclusion, plus `too_long` (`:2894-2943`).
11. Not bought: any UNKNOWN failure → `NEEDS_OWNER`; two retry-class failures on this model → `NEEDS_OWNER`; one → `retry=True`; a `hold_ro` → `NEEDS_OWNER` (`:2945-2966`).

Data: reads `Integration`, `ServiceSelection`, `MediaProductionConfig`, `ProviderResource`, `ModelOutcome`, `ChannelRecord`, `Storyboard`, `StoryboardScene`, `CharacterBible`, `CharacterIdentityChange`, `config/film_models.json`; writes `ChannelRecord`, `Storyboard`/`StoryboardScene` overrides, `CharacterBible`, `CharacterIdentityChange`, `ProviderResource.pricing` (via `lifecycle.stamp_price`), agent memory `OWNER_POLICY`; events `channel.production_policy_set`, `media.storyboard_production_set`, `character.voice_bound`, `character.identity_locks_set`, `character.identity_change_proposed`, `character.identity_change_{testing,approved,rejected}`, `character.model_fallback_approved`. No network, no purchase.

### `app.media.shooting_sheet` — backend/app/media/shooting_sheet.py (4368 lines)

The page in front of every purchase and the steps it gates (`backend/app/media/shooting_sheet.py:1-41`). It builds the sheet at 0 credits (the only live call is the free vendor balance read), hashes what will be bought into `sheet_hash`, and runs the paid steps `stills`, `test_shot`, `motion` and `assemble` behind the gate chain; it also owns the film purchase lease, the film ceiling, the budget hold, the bookings, the abandoned-purchase letters, and the studio's default wiring (connection, capabilities, account, adapters).

#### The Owner's choices on the sheet

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `sheet_url` | 315 | `/api/v1/media/storyboards/{id}/shooting-sheet` | Links in letters and cards | — |
| `price_table_for` | 319 | Published table + connection's MEASURED rows + ComfyUI local rows + RunPod ESTIMATED rows | One table for sheet and steps | CONFIG + EXTERNAL measurements |
| `sheet_overrides` | 386 | The Owner's per-scene choices from `media.sheet_scene_model_set` events, last per scene wins, `None` dropped | Choices are events, so they change the hash | OWNER |
| `set_scene_model` | 413 | Owner-only per-scene model or LOCAL_MOVE; LIVE scenes only; model must have a video price at the resolution; event; queues FILM_CONTINUE | Choosing a model is the Owner's; nothing bought on a guessed price; 2026-10-10 continuation fix | OWNER + CODE_RULE |
| `decide_sheet_take` | 500 | The Owner's APPROVED/REJECTED (optionally final) via `assembler.decide_take`; approving a still demotes other APPROVED stills of the same scene/prompt to PAID; returns `outcome` wording | One scene never has two starting pictures; FILM_CLOSED refused | OWNER |

#### Building the sheet

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_read_balance` | 611 | GPU billing → not applicable; local → not applicable; else `credit_balance()` via `asyncio.run`; never raises; failure named, never 0 | Fail-closed balance | EXTERNAL |
| `_daily_budget` | 648 | DAILY budget status from `economy.budget.budget_status` | Footer line | CONFIG |
| `_badges` | 672 | Faces (measured locally when a counter and still exist, else from prompt/lint), "no text" asked, light word from the look block | What the sheet can say about a picture and how it knows | CODE_RULE |
| `_take_view` | 736 | Take dict with clip QC, hero acceptance by clip QC, refusal view, final flag | Contact sheet | — |
| `_stills_spent` | 783 | Quoted and measured credits of bought stills | Footer | — |
| `_alternatives` | 801 | Whole-film alternatives via `cost_plan.plan_film` with their price sources | Owner sees 720p / seedance2 / veo3.1_fast totals | CODE_RULE |
| `_price_line` | 839 | One price line per scene | Owner wording | — |
| `_narration` | 858 | Narration characters (scenes already voiced cost 0) × dearest active ElevenLabs per-1k price; unpriced when words and no price | Narration is a hashed paid line of the plan | CODE_RULE |
| `_safety_moves` | 927 | Latest SAFETY suggestion per scene from `media.motion_needs_owner` | Shown for the Owner to choose; nothing bought on a suggestion | CODE_RULE |
| `_redo_plans` | 986 | Each scene's still/motion/card redo plan and the audio redo, each with its own `plan_hash`, computed exactly like the redo routes | The «Refă» buttons are bound to the hash `redo_scene` checks | CODE_RULE |
| `_catalogue_view` | 1027 | The Owner's three catalogue choices, or the catalogue problem | Footer | CONFIG |
| `_sheet` | 1049 | Builds the whole sheet: story review, shot-plan gaps, takes, approved stills, readiness, clip plan, refusals, clip QC, hero acceptances, narration, stills plan, motion plan, per-scene policy (`plan_scene_models`), hero gate, prompts per model, lint + SCENE_TOO_LONG blocks, badges, step views, assemble step, the hashed dict and its SHA-256, prices used, footer (balance, need per step, budgets, film ceiling, alternatives), redo plans | The single page before every purchase | CODE_RULE |
| `_runpod_metrics` | 1768 | RunPod generation metrics for the film | Footer | EXTERNAL |
| `_reference_verified` | 1782 | `RunwayImageAdapter.REFERENCE_IMAGE_VERIFIED` | Says referenceImages is unverified until proven | — |
| `build_sheet` | 1790 | Public entry: context + `_sheet` | `GET …/shooting-sheet`, the day's walk, sheet repair | CODE_RULE |
| `sheet_hash` | 1837 | The hash only (no balance read, no face count) | Hash before/after the Owner's model choice | CODE_RULE |

Helpers: `_context`, `_canonical` (sorted compact JSON), `_ro_usd`, `_ro_credits`, `_source_of`, `_light_badge`, `_file_url`, `_scene_takes`, `_redo_view`.

**What the hash covers** (`backend/app/media/shooting_sheet.py:1608-1636`): storyboard id, resolution, seed, stills model/resolution/candidates, per scene (kind, card JSON, still prompt, motion prompt, negative prompt, approved still SHA-256, model, status, decided_by, override, billed seconds, credits, still credits, take id, take status, hero acceptance), per paid step (`to_buy`, cost, cap), hero scene, narration (characters, USD micros, priced). Not hashed: balance, budgets, lease, lint text, badges, redo plans.

#### The gates before every purchase

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `may_spend_step` | 1849 | Read-only `economy.budget.may_spend` for a cap; Romanian refusal | Used by the narration check (`:3932`) | CODE_RULE + CONFIG |
| `film_is_closed` | 1954 | REJECTED with no finished render | ADR-OWNER-CLOSE-FILM | CODE_RULE |
| `current_lease` | 2027 | Live lease or None (expired counts only when alive in this process) | Page disables buy buttons | CODE_RULE |
| `held_films` | 2039 | Films with a live lease | Watchdog leaves their paid tasks to the buyer | CODE_RULE |
| `film_purchase_lease` | 2048 | Context manager: take/renest the lease behind the write lock, refuse FILM_BUSY/FILM_CLOSED, reclaim an expired row (settle + letter), start the keeper, give back on exit | MONEY-04, REDO_HANG | CODE_RULE |
| `_LeaseKeeper` (`__init__` 2146, `start` 2157, `stop` 2162, `_forget` 2168, `_run` 2172, `_renew` 2188) | 2139 | Background renewal every 60 s up to min(ceiling, now + 300 s); stops when no longer the holder | A gone process renews nothing | CODE_RULE |
| `reclaim_abandoned_leases` | 2204 | Takes back lapsed leases, or (at start) pre-start long leases; settles each | Startup (`app.main.create_app`) and watchdog | CODE_RULE |
| `_balance_around` | 2274 | Last balance reading before and first after a moment, from events (never the vendor) | Letter figures | CODE_RULE |
| `_settle_abandoned` | 2310 | Releases `sheet:*` holds of the window, finds consumed approvals and takes, computes the unexplained balance drop, writes `media.film_purchase_lease_reclaimed` and the Accountant's `film_purchase_abandoned` letter | The spent yes and any charge are told, nothing re-bought | CODE_RULE (letter is INFORMATIONAL) |
| `_abandoned_text` | 2465 | Romanian letter body | Owner wording | — |
| `_give_back_lease` | 2545 | Delete or restore nested step; never raises | Lease release | CODE_RULE |
| `lease_seconds` | 2569 | Setting or 10,800 s | — | CONFIG |
| `film_spend_micros` | 2577 | Cost rows attributed to the film + narration of its render jobs + its RESERVED holds | Estimates count: a ceiling waiting for invoices says "fine" late | CODE_RULE |
| `film_ceiling_micros` | 2632 | `film_budget_usd` («setare») or motion budget + six-scene stills cap («implicit») | MONEY-07 | CONFIG |
| `film_budget_view` | 2657 | Limit, spent, remaining | Footer | — |
| `check_film_ceiling` | 2673 | PRODUCTION only: refuse `OVER_FILM_BUDGET`, or record the Owner's consent | One stuck film is not bought day after day | CODE_RULE + OWNER |
| `hold_step_budget` | 2726 | `reserve_spend` of the cap (`sheet:<step>`, correlation = film); refuse or force with the Owner's consent | AR-03: two films were both told the last ten dollars were free | CODE_RULE + OWNER |
| `settle_step_hold` / `release_step_hold` / `close_step_hold` | 2781 / 2800 / 2814 | Settle after booking, release when nothing bought; never raise | Holds do not double-count | CODE_RULE |
| `recall_purchase` / `remember_purchase` | 2836 / 2848 | Idempotent replay of a press by `command_id` (`SheetPurchase`); reused id with another body → conflict | The same press buys once | CODE_RULE |
| `purchase_reference` | 2894 | `prefix:correlation`, ≤120 chars | One reference per purchase | CODE_RULE |
| `book_purchase` | 2900 | ESTIMATED provider cost with attribution; refusal → WARNING event + Accountant letter | Next budget check sees the spend | CODE_RULE |
| `book_step_cost` | 2979 | Measured drop or quoted credits under `foaie:{film}:{step}:{hash16}:{correlation}` | 2,040 spent vs 680 booked | CODE_RULE + EXTERNAL |
| `interrupted_spend` | 3018 | Balance drop if readable again, else the meter's committed credits | Booking a crashed step | EXTERNAL |
| `book_interrupted_step` | 3027 | Books it, WARNING `media.paid_step_interrupted`, Accountant letter | REL-01 | CODE_RULE |
| `withdraw_stale_questions` | 3092 | Kernel withdraws older unanswered questions for the step; returns ids | The Owner's inbox holds only questions that can still buy | CODE_RULE |

Helpers: `_now`, `_lease_view`, `_busy_reason` (Romanian «Filmul este deja în lucru…»), `_alive_here`, `_clock` (Owner's time zone), `_settings_of`, `_budget_words`.

#### The paid steps

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `recover_paid_takes` | 3130 | Collects late deliveries by task id, judges unjudged still candidates, clip-checks unchecked paid shots; buys nothing | A film whose only open scene was such a take waited for ever (2026-10-02, A7) | CODE_RULE (judging in other modules) |
| `run_sheet_step` | 3193 | Unknown step check; runs `_run_sheet_step` under the film lease; FilmBusy/FilmClosed → `SheetStepRefused` | One paid step under the Owner's yes for THIS sheet | CODE_RULE |
| `_run_sheet_step` | 3272 | The gate chain (see "gate order"), then `run_stills_stage` or `run_motion_step`, booking, hold close, low-balance card; crash handling | GATES_BEFORE_BUYING, NEXT_ROUND_BALANCE, REL-01 | CODE_RULE + OWNER + CONFIG + EXTERNAL |
| `_low_balance_card` | 3588 | `decisions.sources.film_low_balance` card | ADR-LOW-BALANCE-CARD | CODE_RULE → OWNER |
| `_balance_covered` | 3604 | Withdraws the card when a step starts on a covering balance | Card clears on the books | CODE_RULE |
| `_step_refused` | 3612 | Stage refusal in sheet words; withdraws stale questions on NEEDS_APPROVAL | — | CODE_RULE |
| `_step_bought` | 3645 | Books the step once, whoever pressed it | Next step's budget check reads it | CODE_RULE |
| `narration_action` | 3671 | T3 action when unpriced, no threshold, or above threshold; else T2 | Narration tier | CODE_RULE + CONFIG |
| `narration_gate` | 3679 | `may_act` for the narration bound to `plan_hash` and step `assemble` (requester `video_editor`) | The Owner's yes is spent only for the plan shown | OWNER (kernel) |
| `_letter_sheet` / `_qc_letter` | 3718 / 3738 | QC letter via `qc_report.qc_summary_ro`, with a fallback listing up to 8 reasons | The Owner's QC letter | CODE_RULE (INFORMATIONAL text) |
| `_leased` | 3760 | Decorator: run a step under the film lease | `run_assemble_step` | CODE_RULE |
| `run_assemble_step` | 3786 | STALE_PLAN; blocked scenes → `TAKES_NOT_ACCEPTED` (recorded, CLIP_SHORT redos when wired); narration: exact characters from the voices, budget check, `narration_gate`; `assemble_from_takes`; booking of failed assemblies; render costs; media QC (`qc.evaluate_media_qc`, vision inside); `release_after_qc` frees the film's intermediate shot files; QC letter text returned as `qc_letter_ro`; `media.sheet_assembled` | The sheet's last step | CODE_RULE + OWNER |
| `_with_redos` | 4087 | For CLIP_SHORT scenes, `propose_clip_redos` when `redo_wiring` is given, attaching each outcome | 2026-10-09 babcf272: refusals ended as letters and nothing moved the film | CODE_RULE (unreachable at runtime) |
| `_book_failed_assembly` | 4146 | Books the narration a FAILED render job of this attempt voiced | MONEY-12 | CODE_RULE |

#### The studio's own wiring

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `runway_connection_id` | 4191 | Owner-selected video (else image) connection of kind runway/comfyui/runpod if verified; else the single verified Runway connection | Default wiring | CONFIG (Owner selection) |
| `connection_capabilities` | 4214 | `scene_model_capabilities` for the connection | Planner input | CODE_RULE |
| `motion_clip_limit` | 4224 | Longest clip of the selected cloud default, else local default, else allowed+admitted models | Story review checks scene lengths before filming (`factual.story_review.scene_clip_check`) | CODE_RULE |
| `connection_account` | 4249 | Balance reader: RunPod connection, ComfyUI connection, or Runway adapter with the decrypted key | Balance reads | CONFIG |
| `connection_video_adapters` | 4279 | `adapter_for_model` via `factory.video_provider_for` | Adapters carry their contract | CONFIG |
| `card_preview_png` | 4300 | Composes a card scene locally (background: first filmed scene's approved still) and extracts its last frame with ffmpeg | 0-credit preview | CODE_RULE |

#### Exception classes

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `SheetNotFound` (class) | 240 | Storyboard, scene or take missing; routes answer 404 | — | — |
| `SheetChoiceRefused` (class) | 244 | The Owner's sheet choice cannot be taken (unpriced model, card scene); routes answer 422 | Nothing chosen on a guessed price | — |
| `SheetStepRefused.__init__` | 255 | Carries `status`, `reason_ro`, `approval_id`, `cost_usd`, `cap_credits`, lint `findings`, blocking `scenes`, `withdrawn` question ids | One refusal shape for every gate and stage | — |
| `SheetStepRefused.http_status` | 280 | 202 for `NEEDS_APPROVAL`, 409 for everything else | The Owner's question waits; every other refusal bought nothing | CODE_RULE |
| `SheetStepRefused.as_dict` | 283 | Response body; question fields only for `NEEDS_APPROVAL` | — | — |
| `FilmBusy.__init__` | 1935 | `FILM_BUSY` with the holder's lease view | MONEY-04 one buyer per film | — |
| `FilmClosed.__init__` | 1949 | A `FilmBusy` with status `FILM_CLOSED`, so every buyer that stops on a busy film stops on a closed one | ADR-OWNER-CLOSE-FILM | — |
| `PurchaseGateRefused.__init__` | 1978 | `status` + `reason_ro` of a refused gate (film ceiling, budget); each caller rewraps it | Shared by the sheet and `assembler.redo_scene` | — |

**Data read/written**: reads `Storyboard`, `StoryboardScene`, `SceneTake`, `VideoRenderJob`, `ProviderPrice` (ElevenLabs per-1k), `OwnerPolicy`, `ApprovalRequest`, `SpendReservation`, `ProviderCostRecord`, `Integration`, `ServiceSelection`, `DomainEvent`; writes `SceneTake` (supersede), `FilmPurchaseLease`, `CommandRecord` (via `remember_command`), cost records (via `economy.services.record_provider_cost`), reservations (via `economy.budget`), Owner letters (via `economy.accountant`), decision cards (via `decisions.sources`). Events emitted: `media.sheet_scene_model_set`, `media.scene_take_superseded`, `media.paid_step_balance_read`, `media.film_budget_excess_approved`, `media.budget_excess_approved`, `media.film_purchase_lease_reclaimed`, `media.step_cost_not_booked`, `media.paid_step_interrupted`, `media.sheet_assembled`, plus `governance.approval_withdrawn` through the kernel. Events consumed: `media.sheet_scene_model_set`, `media.motion_needs_owner`, `media.paid_step_balance_read`, `media.stills_step_finished`, `media.motion_step_finished`, `media.scene_redone` (`backend/app/media/shooting_sheet.py:2266-2271`).

**External calls**: vendor balance GET (`credit_balance()`, `backend/app/media/shooting_sheet.py:632-645`); all purchases happen inside `stills_stage.run_stills_stage` (Runway/RunPod/ComfyUI images), `assembler.run_motion_step` (video), `assembler.assemble_from_takes` (TTS narration); task collection GETs in `recover_paid_takes`; local ffmpeg (`backend/app/media/shooting_sheet.py:4349-4366`).

## Connections

**Who calls in** (static call graph):

- HTTP (all under the Owner-only media router, `backend/app/media/router.py:319`): `GET /storyboards/{id}/shooting-sheet` → `build_sheet`; `POST /storyboards/{id}/steps/{step}` → `run_sheet_step` or (step `assemble`) `run_assemble_step` via `router._assemble_step`, with `recall_purchase`/`remember_purchase`; `PUT /storyboards/{id}/shooting-sheet/scenes/{n}/model` → `sheet_hash` + `set_scene_model`; `POST /takes/{id}/decision` → `decide_sheet_take` (+ `build_sheet` as reader); `GET …/scenes/{n}/card-preview` → `card_preview_png`; `GET …/redo-plan` and `POST …/redo` → `sheet_overrides`; `GET …/production-plan` → `resolve_storyboard_plan`; `PUT /storyboards/{id}/production` → `set_storyboard_production`; character routes → `set_voice_binding`, `set_identity_locks`, `propose_identity_change`, `decide_identity_change`, `list_identity_changes`, `approve_model_fallback`; publishing router `PUT /channels/{id}/production-policy` → `set_channel_policy`.
- The daily runbook: `runbook.stages._walk_staircase` → `recover_paid_takes`, `build_sheet`, `run_sheet_step(unasked=True)` (`backend/app/runbook/stages.py:1749-1863`); `_film_staircase`/`_media_staircase` → `film_purchase_lease`, `lease_seconds`; `_apply_repairs` → `sheet_overrides`; `film_spent_micros` → `film_spend_micros`; preflight → `film_ceiling_micros`.
- The assembler (redo and motion machinery): `redo_scene` → `check_film_ceiling`, `hold_step_budget`, `film_purchase_lease`, `lease_seconds`, `release_step_hold`; `_paid_redo` → `close_step_hold`; `_book_redo` → `book_purchase`; `_redo_interrupted` → `book_interrupted_step`; `_motion_state` → `need_from_scene`, `plan_scene_models`, `price_table_for`; `_capabilities` → `scene_model_capabilities`; `_suggest_move` → `replan_after_failure`; `take_failure`/`classify_vendor_failure` → `classify_failure`; `scene_tier` → `scene_role`/`SCENE_ROLE_TIERS`; `assemble_video_job` → `record_quoted_price`; `run_motion_step`/`run_stills_stage`/`_StillRedoBuyer.run` → `balance_rule`.
- Others: `media.factory` (`choose_model`, `estimate_cost_usd`, `render_plan` → `resolve_storyboard_plan`); `media.blocker_repair` (`build_sheet`, `current_lease`, `film_purchase_lease`, `needed_credits`); `media.film_close` and many writers → `film_is_closed`; `workflows.watchdog` → `reclaim_abandoned_leases`, `held_films`, `connection_account`; `app.main.create_app` → `reclaim_abandoned_leases`; `economy.credits` → `apply_measured`, `attribute_measured_credits`, `credit_usd`, `record_measured_price`; `economy.accountant` → `record_measured_price`, `credit_usd`, `estimate_cost_usd`, `film_spend_micros`; `economy.budget.estimate_film_cost_micros` → `cost_plan`; `decisions.sources.apply_sheet_local_move` → `set_scene_model`; `decisions.seed.cheapest_capable_film` → `plan_scene_models`, `scene_model_capabilities`; `integrations.autoconfig` and `media.model_research` → `rank_candidates`; `integrations.lifecycle.review_models` → `model_record`; `factual.story_review.scene_clip_check` → `motion_clip_limit`; `story.review.motion_clip_limit` → `resolve_purpose`, `longest_seconds`.

**What it calls out to**: `app.media.stills_stage` (stills plan, stage, settle), `app.media.assembler` (motion plan/step, hero gate, readiness, takes, clip QC, assembly, redos), `app.media.prompt_lint`, `app.media.prompt_agent` (`motion_prompt_for`, `shot_plan_gaps`), `app.media.sheet_words`, `app.media.cards`, `app.media.qc`/`qc_report`, `app.media.mode_guard`, `app.factual.story_review` (`story_gate`), `app.economy.budget`/`services`/`accountant`/`credits`, `app.decisions.sources`, `app.services` (`append_event`, `may_act`, `queue_film_continue`, `withdraw_superseded_approvals`, `recall_command`/`remember_command`, `studio_environment`, `paid_media_policy`), `app.providers.runpod.*`, `app.providers.runway`, `app.media.factory`, `app.integrations.discovery`/`lifecycle`.

**Downstream LLM loop fed by this module's output**: a sheet BLOCK such as `SCENE_TOO_LONG` is picked up by `blocker_repair.scan_sheet_issues`, which hands it to the Director's repair (`media.blocker_repair.director_assignment` is an LLM call site) and the story repair (`backend/app/media/shooting_sheet.py:1426-1431`, `backend/app/media/production_policy.py:2450-2453`).

**Gates that live outside this module** but belong to the same staircase: the free-disk floor (`backend/app/media/stills_stage.py:1981`, `backend/app/media/assembler.py:11576`, `backend/app/media/router.py:284`), `may_act` with the `plan_hash` inside the stages, the hero gate (`backend/app/media/assembler.py:9917`), per-purchase balance re-reads and the step cap inside the stages, the Director's second look before a still re-roll or a clip retry is bought (since `20abffd`: `stills_stage._settle_round`, `backend/app/media/stills_stage.py:1143-1149`; `qc.qc_clip_with_retry`, `backend/app/media/qc.py:2670`, `:2737`; it can only spare that purchase), and the story gate before shot prompts are written (`backend/app/media/prompt_agent.py:1141`).

## Owner touchpoints

| Touchpoint | What the Owner decides | Where |
|---|---|---|
| Press of a paid step on the sheet (`POST …/steps/{step}`) | Starts a step for the plan shown (`plan_hash`); the stage then asks or spends the yes | `backend/app/media/shooting_sheet.py:3193`, `backend/app/media/router.py:883-944` |
| `allow_over_budget` on that press | Explicit consent to exceed the film ceiling and a period budget for one step (events record it) | `backend/app/media/shooting_sheet.py:2704-2723`, `:2754-2778`, `:3931` |
| Approval question for the step / the narration | Yes or no, bound to `plan_hash`, spent once; older questions withdrawn | `backend/app/media/shooting_sheet.py:3612-3642`, `:3679-3715`, `:3948-3967` |
| Per-scene model or LOCAL_MOVE (`PUT …/model`, or a decision card's accept) | The motion model of one scene, overriding the planner | `backend/app/media/shooting_sheet.py:413-497`, `backend/app/decisions/sources.py:1113-1160` |
| Take decision (`POST /takes/{id}/decision`) | APPROVED / REJECTED, optionally final | `backend/app/media/shooting_sheet.py:500-605` |
| Low-balance card | Top up the vendor account by at least N credits, or wait | `backend/app/media/shooting_sheet.py:3399-3413`, `:3572-3584`, `backend/app/decisions/sources.py:676` |
| Letters (INFORMATIONAL) | Abandoned purchase, booking refused, paid step interrupted (Accountant letters); the QC letter is text returned in the assemble step's answer (`qc_letter_ro`), not posted to the inbox here | `backend/app/media/shooting_sheet.py:2436-2444`, `:2968-2974`, `:3079-3088`, `:4051`, `:4083` |
| Settings | `paid_step_balance_margin`, `film_budget_usd`, `motion_budget_usd`, `film_purchase_lease_seconds`, `motion_resolution`, `paid_generation_approval_threshold_usd`, `timezone` | `backend/app/config.py:52`, `:258-286`, `:392` |
| `config/film_models.json` | `allowed` models, `hero_threshold`, `premium_reference` | `backend/app/media/production_policy.py:696-804` |
| `config/runway_prices.json` | Published prices and `credit_usd` | `backend/app/media/cost_plan.py:39` |
| Connection `credit_usd` | What one vendor credit costs | `backend/app/media/production_policy.py:541-555` |
| Video/image selection and connection defaults (incl. RunPod model) | Which connection and default model; the RunPod default is taken unasked by quality. The default can also be rewritten without the Owner by autoconfig or the weekly model steward when the connection allows production override (Oddity 22) | `backend/app/media/shooting_sheet.py:4191-4211`, `backend/app/media/production_policy.py:2839-2861`, `backend/app/integrations/router.py:361-366` |
| Channel policy, storyboard production, voice bindings, identity locks, identity changes, approved models | Technology per level; character identity | `backend/app/media/production_policy.py:1644-2040` |
| Closing a film («Închide filmul») | After closure nothing more is bought for the film | `backend/app/media/shooting_sheet.py:1902-1971` |

## Oddities and gaps

1. **Stale module docstring.** The sheet's docstring says a step is refused on "a Runway balance below the step's cap x 1.15" (`backend/app/media/shooting_sheet.py:37-38`); the code checks the next round × margin (`backend/app/media/shooting_sheet.py:3384-3395`), per ADR-NEXT-ROUND-BALANCE (`docs/project/16_DECISION_LOG.md:4157`).
2. **`_read_balance` docstring misplaced.** The string «The live Runway balance: one free GET…» sits after two early returns (`backend/app/media/shooting_sheet.py:631`) and is a no-op expression, not the function's docstring.
3. **`CLIP_SHORT` redos are never raised from an assembly refusal.** `run_assemble_step` only calls `_with_redos` → `propose_clip_redos` when `redo_wiring` is passed (`backend/app/media/shooting_sheet.py:4109`); its only caller, `router._assemble_step`, does not pass it (`backend/app/media/router.py:288-309`), the runbook does not call `run_assemble_step` (it runs its own assembly under the lease, `backend/app/runbook/stages.py:2873-2885`), and `propose_clip_redos` (`backend/app/media/assembler.py:4947`) has no other caller. The docstring promise (`backend/app/media/shooting_sheet.py:3824-3828`) is unreachable at runtime.
4. **The Owner's per-scene model check uses the published table only.** `set_scene_model` falls back to `load_price_table()` (`backend/app/media/shooting_sheet.py:440`) and the route passes no table (`backend/app/media/router.py:964-972`); RunPod and ComfyUI models are priced only through the overlays in `price_table_for` (`backend/app/media/shooting_sheet.py:319-328`), so choosing one of them per scene is refused 422 «nu are preț publicat», although the sheet itself prices them. LOCAL_MOVE is unaffected.
5. **Narration gate differs from the other steps.** The narration is checked by a read-only `may_spend` (`backend/app/media/shooting_sheet.py:3931-3937`) with no reservation (AR-03 holds are used for the other steps, `:3430`) and no `check_film_ceiling`. `may_spend_step`'s docstring says it is "the check of every paid step … the sheet's steps, the assemble step's narration and a one-scene redo" (`backend/app/media/shooting_sheet.py:1850-1852`); its only caller is the narration (`:3932`).
6. **Narration priced at ElevenLabs regardless of the voice used.** `_narration` takes the dearest active ElevenLabs per-1k price (`backend/app/media/shooting_sheet.py:881-888`), and `run_assemble_step` asks whenever that price yields micros > 0 (`backend/app/media/shooting_sheet.py:3928`), including when the voices are not paid vendors.
7. **Stale `book_step_cost` docstring.** It says "nothing is reserved ahead of it, because that check would count the hold and the cap twice" (`backend/app/media/shooting_sheet.py:2996-2998`); `_run_sheet_step` reserves the cap through `hold_step_budget` before the stage (`backend/app/media/shooting_sheet.py:3430-3439`).
8. **Consent events written before anything is bought.** With `allow_over_budget`, `check_film_ceiling` and `hold_step_budget` append `approved_by: owner` excess events (`backend/app/media/shooting_sheet.py:2706-2723`, `:2761-2777`) before the stage asks or buys; the event stands even when the stage then answers NEEDS_APPROVAL or refuses.
9. **Abandoned-lease letter may compare the wrong readings.** `_balance_around` returns the first balance reading after the lease's acquisition (`backend/app/media/shooting_sheet.py:2297-2306`); `_run_sheet_step` records a reading at its own start check right after taking the lease (`backend/app/media/shooting_sheet.py:3386-3394`), so for an abandoned sheet step the "after" figure can be that step's pre-purchase reading. `record_balance_reading` is called only from this module (`:3387`, `:3576`). The readings are also not filtered by film (the `DomainEvent` queries have no aggregate filter, `:2286-2307`), and the booked credits subtracted from the drop are only `ProviderCostRecord.provider == "runway"` rows (`:2373-2383`), so another film's purchase in the same window can show up as this film's "unexplained" credits.
10. **An unreadable balance raises no card.** `LOW_BALANCE` on a balance that could not be read (`backend/app/media/shooting_sheet.py:3375-3380`) gets no `_low_balance_card`; only a short balance does (`:3395-3413`).
11. **The allowed list is bypassed for local and RunPod models.** `owner_allowed` is true for any ComfyUI model and any RunPod-routed model regardless of `config/film_models.json` `allowed` (`backend/app/media/production_policy.py:3436-3438`); the 2026-10-01 decision says "the planner never buys outside 'allowed'" (`docs/project/16_DECISION_LOG.md:4074`). The later RunPod decision (`docs/project/16_DECISION_LOG.md:4204`) is consistent with the code.
12. **Owner override and kept models skip every shortfall.** A named model (Owner override, or a model kept from an approved sheet) is taken if catalogued and priced; its shortfalls (allowed set, admission, failure history, frame) become warnings only (`backend/app/media/production_policy.py:2811-2838`). Stated as intended for the Owner's choice (`backend/app/media/production_policy.py:2194-2196`); for a `kept` model it applies too.
13. **Price-table cache.** `cost_plan._load` is cached by path only (`backend/app/media/cost_plan.py:163-170`): an edit to `config/runway_prices.json` is read only after a restart, while `config/film_models.json` is re-read on a change of mtime or size (`backend/app/media/production_policy.py:750-804`).
14. **Dead or unused code.** `cheapest_prompt_to_video` (`backend/app/media/production_policy.py:562`) has no caller in `backend/app`; constants `CONSISTENCY_STATUSES` (`:87`), `NOT_FOR_PRODUCTION` (`:814`), `shooting_sheet.WITHDRAWN_EVENT` (`backend/app/media/shooting_sheet.py:200`) and `shooting_sheet.BALANCE_MARGIN` (`:214`) are never read in `backend/app` (`WITHDRAWN_EVENT` is read only by `tests/test_shooting_sheet.py:722-724`).
15. **Duplicated logic.** Price-source labelling exists three times (`backend/app/media/cost_plan.py:322-333`, `backend/app/media/shooting_sheet.py:368-380`, `backend/app/media/production_policy.py:3072-3082`); the cap formula twice (`backend/app/media/cost_plan.py:468`, `backend/app/media/production_policy.py:3058`); `_ro_credits` twice (`backend/app/media/production_policy.py:2383`, `backend/app/media/shooting_sheet.py:361`); the 1.15 margin is also hard-coded as `REFERENCE_BALANCE_MARGIN` (`backend/app/media/services.py:1826`, kept on purpose per `docs/project/16_DECISION_LOG.md:4157`) and re-exported as `PAID_STEP_BALANCE_MARGIN` (`backend/app/media/assembler.py:8083`) and `stills_stage.BALANCE_MARGIN` (`backend/app/media/stills_stage.py:277`); "longest clip" is computed by two functions with different model selection: `shooting_sheet.motion_clip_limit` (selected connection, `backend/app/media/shooting_sheet.py:4224`) and `story.review.motion_clip_limit` (serial channel via `resolve_purpose`, `backend/app/story/review.py:342`).
16. **Film-ceiling default ignores the stills model actually used.** `film_ceiling_micros` prices the six-scene stills allowance with the constant `STILLS_MODEL` (`seedream5_pro`) (`backend/app/media/shooting_sheet.py:2647-2652`), not the connection's stills model.
17. **Misleading key name.** `rank_candidates` stores whatever unit's price it found (per second, per image, per 1k characters) under `per_1k_characters_usd` (`backend/app/media/production_policy.py:373`, `:400`), and the premium ordering sorts by it (`:432-436`).
18. **Scene index parsed from human text.** `_settle_abandoned` finds the scene of a consumed approval by the regex «scenei (\d+)» over its evidence text (`backend/app/media/shooting_sheet.py:2390-2392`).
19. **Story review shown but not enforced here.** The sheet reports `story_review` (`backend/app/media/shooting_sheet.py:1081`, `:1754`), but `_run_sheet_step` does not refuse on it; enforcement is upstream, before shot prompts are written (`backend/app/media/prompt_agent.py:1141`).
20. **LLM-steward scores reach two different choosers differently.** `choose_model` and `rank_candidates` read `capabilities.quality_score` directly (`backend/app/media/production_policy.py:370`, `:963`), while the sheet planner demotes the same unsourced score below `config/film_models.json` (`backend/app/media/production_policy.py:3297-3308`); the steward writes no `basis`/`sources` key (`backend/app/media/model_research.py:392-398`; `update_resource_metadata` replaces the whole `capabilities` dict, `backend/app/integrations/discovery.py:782-789`), so its scores are always «estimat» for the planner.
21. **The documented file does not cover every model the planner ranks.** The demotion in 20 works only field by field: `config/film_models.json` has `quality_score: null` for four models in its own `allowed` list (`seedance2_fast`, `seedance2_mini`, `wan3_prime`, `h3_max`) and no entry at all for the RunPod models (`LTX-2.5`, `Wan-2.2-LightX2V` in `config/runpod_models.json`), so for them the unsourced steward score, when present, is the planner's quality and decides whether they reach a tier (`backend/app/media/production_policy.py:3309-3321`, `:3399-3404`). For a RunPod model it even outranks the pinned `quality_score` of `config/runpod_models.json`, which is read only when research has none. At the default 1080p, `seedance2_fast`/`seedance2_mini` have no price row and `wan3_prime`/`h3_max` none at all in `config/runway_prices.json`, so today they are unpriced there unless an overlay prices them.
22. **The "Owner-selected" RunPod default can be chosen by the steward.** `_choose_scene` takes the connection's `selected_default` for every scene unasked by quality (ADR-RUNPOD-ANYWAY, `backend/app/media/production_policy.py:2839-2861`). That default is `MediaProductionConfig.model_id` (`:3413-3417`), which the weekly `model_research_weekly` job (`backend/app/main.py:527-536`) overwrites with the VideoEditor steward's LLM recommendation whenever the connection's `allow_production_override` is on and the model is usable (`backend/app/media/model_research.py:417-455`); `integrations.autoconfig.auto_configure` can also set it to the first-ranked model (`backend/app/integrations/autoconfig.py:209-240`). For RunPod/ComfyUI connections that save also promotes the model to CANDIDATE, an admitted station (`backend/app/integrations/discovery.py:727-739`). The code still requires a price row and no non-quality shortfall, and every purchase still passes the Owner's mode and `may_act`.
23. **Stale `rank_candidates` docstring.** It says the weights default "to an even split" (`backend/app/media/production_policy.py:333-334`); the code defaults to the `premium` weights 0.6/0.25/0.1/0.05 (`:339-348`), as its own comment says.
