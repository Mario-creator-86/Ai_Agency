# 08 — The daily runbook stages (the day's production run, film continuation)

> Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).
>
> Files: `backend/app/runbook/stages.py` (6426 lines, 93 top-level functions),
> `backend/app/runbook/models.py` (74 lines, 2 tables, 0 functions),
> `backend/app/runbook/__init__.py` (5 lines, docstring only).
> First mapped 2026-10-12 at HEAD 3d49e9a plus the working tree (`stages.py` last changed in b00083c;
> no uncommitted change to these three files at mapping or verification time). The three files are
> byte-identical at b00083c and 20abffd, so their line numbers (`stages.py:N`, shorthand `:N`)
> hold; citations into files changed after b00083c (`prompt_agent.py`, `scene_rewrite.py`,
> `picture_qc.py`, `agents/editorial.py`, `story/services.py`, `assembler.py`) give their lines
> at 20abffd.

## In one paragraph

`app.runbook.stages` is the work behind the daily run that
`app.runbook.services.execute_daily_run` walks (`STAGES`, 13 entries from `preflight` to
`serial_next`, backend/app/runbook/services.py:76-90; 11 of them have a runner here).
`build_stage_runners` (backend/app/runbook/stages.py:6330) hands the run one closure per stage:
performance intake, idea generation, research and verification, topic selection, script and
storyboard, the Office Serial queue, media (the paid "staircase" in PRODUCTION, a whole-film
render in TEST), edit and QC (including the Director's decision on a film that failed QC and the
repairs she orders), publish, post-run (the Accountant's close and the Director's inbox review)
and the next serial script. Every closure first asks the Owner's autonomy mode, through the
Policy Kernel, whether the stage may be attempted at all (`mode_refusal`, :271). The same module
also holds `continue_film` (:5430), which the worker runs when the Owner answers a paid question
or approves a take (`FILM_CONTINUE`), walking one film through the same staircase, QC, repair and
publication outside the daily run. The module calls no language model itself: every model call
is made in another module (research, factual, agents, media, story, economy), and this module
decides by deterministic code what to ask, in what order, how often, what to buy, when to stop,
and what to tell the Owner. `models.py` defines the run's own record (`DailyRun`) and the safe
mode record (`SafeModeRecord`); neither is read or written by `stages.py`.

## Why it exists

- **Turn the runbook into real work.** Before this module a run "recorded preflight and then
  eleven stages as SKIPPED — honest, and idle" (backend/app/runbook/stages.py:3-5). The runner
  contract is `{"status", "reason", "artefacts"}`; COMPLETED means the stage ran to its end,
  SKIPPED that it could not run, and only a genuine fault may raise (:7-15). Spec:
  `docs/architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` §1-§12; `build_stage_runners` names §3,
  §4, §5 and §10 (:6335-6339).
- **Risk tiers per stage, the Owner's mode respected without ending the day.** Each stage is
  one action and one tier of `31_GOVERNANCE_APPROVAL_POLICY` (`STAGE_ACTIONS`, :223-268); a
  stage the mode refuses is SKIPPED, not BLOCKED, "a mode is his decision, not an incident"
  (:26-34). The stop is deliberately not re-read in `mode_refusal` (decision log 2026-09-18,
  docs/project/16_DECISION_LOG.md:2538-2549); the two layers (stage and act) are deliberate
  (16_DECISION_LOG.md:2552-2563).
- **The Nepal film (2026-09-26).** A film was bought twice, whole, from a path that "showed no
  price, no prompt and no model and asked nothing" (:1416-1425); its shot plan was lost to one
  unescaped quote and template prompts were bought in its place (:1109-1110, :3184-3188). Result:
  in PRODUCTION the day climbs each film's shooting sheet one answered stair at a time
  (`_media_staircase`, :2738), holds a film without a model-written plan (`hold_for_shot_plan`,
  :3189-3218), re-asks lost plans (`_reask_shot_plans`, :1192), and the TEST whole-film path
  refuses any real paid vendor (:3380-3395). Decision log "The film staircase" sections
  (16_DECISION_LOG.md:4022-4070).
- **The day never stalls (2026-10-02, AR-02, REL-11, A3, A4, A15).** The media stage used to take
  the oldest approved film alone, so one stuck film stopped every later film and its topic
  blocked selection (:1922-1934). Now films are walked oldest first and passed over when stuck,
  each film's day is recorded (`FILM_STATE_EVENT`), a stale film is retired by the Director after
  `film_wait_days` (`retire_stale_films`, :2204), and the Owner is told once per film in TEST why
  nothing is bought (`_test_environment_letter`, :2079). ADR-FILM-RETIREMENT
  (16_DECISION_LOG.md:4108, "The production-readiness audit").
- **The Owner's yes continues the film the same day (A6, ADR-FILM-CONTINUE).** Under
  EVERY_PAID_STEP a film climbed one stair a day and answers expired unused (:5416-5425).
- **A failed film is decided by the Director, not repaired mechanically (2026-10-10, film
  babcf272).** The mechanical repair redid the Owner's approved scenes 1 and 2, reading burned-in
  subtitles as "text or a logo", while the one real flaw waited (:3826-3835). The Owner: "the
  agents check one another and the Director decides alone" (:3831-3832); only an exceeded budget
  reaches the Owner (ADR-2026-10-10, 16_DECISION_LOG.md:129-150).
- **Redo until QC passes, on corrected prompts (2026-10-11, ADR-DIRECTOR-PROMPT-LADDER).** A scene
  QC refused is the Director's to rewrite, three rounds per walk then a continuation
  (`DIRECTOR_LADDER_ROUNDS`, :1605-1609); a paid redo is bought only on a corrected prompt
  (`PROMPT_NOT_CORRECTED`, :4733-4734); paid-redo limits default 5 per scene and 20 per film
  (16_DECISION_LOG.md:123-127).
- **Rounds counted by pictures, not events (2026-10-12, film 1c038a99).** Five "rounds" of which
  three made nothing exhausted a cap; the Owner: «5 refaceri? Pentru o poză în mișcare?»
  (`_round_windows`, :3912-3926).
- **Scripts approved by the Director (2026-09-12).** A script she passed is approved in the same
  breath, the factual gate re-checked (:17-20, :929-935; 16_DECISION_LOG.md:1854).
- **Many smaller incidents are named in comments**: seven topics stuck SELECTED for days
  (:673-678); 28 drafts that made every day say "a script awaits your approval" (:907-912); 61
  refused claims re-read daily while new ones never reached the Fact Checker (:602-607); a
  telescope film approved on the Nepal topic (:941-945); the serial's retention asked of the main
  channel's account (:398-403); the first bound slot used for every film (:6011-6016); one film
  rendered four times would publish four times (:6065-6071); two lost shots cost six dollars
  with nothing in the books (:3559-3563); a day at 14.99 of 15 USD started a full film
  (:3290-3293); a question raised at 05:30 reached the Owner only at the run's end (:3610-3618).

## Who decides here

Vocabulary: LLM, LLM_CHECKED_BY_CODE, CODE_RULE, OWNER, CONFIG, EXTERNAL. "OWNER via CODE_RULE"
means the Owner set the policy and the code applies it mechanically.

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| A stage may run at all under the autonomy mode | OWNER (mode) via CODE_RULE | stages.py:6345-6377, :271-317 | `may_act(action, tier, ask_owner=False)` for `STAGE_ACTIONS[name]`; refused → SKIPPED with reason, never BLOCKED; `BLOCKED_STOP` returns None (stop read elsewhere, :313-314) |
| An agent stage is skipped for want of a model | CODE_RULE | :320-326 | `registry.registered_ids()` non-empty |
| New topics are proposed only when the pool is thin | CODE_RULE | :341-356 | PROPOSED+RESEARCHED count < `IDEA_POOL_TARGET` = 6 (:332) |
| Which topics are proposed | LLM_CHECKED_BY_CODE | :361-385 → research/agent.py:398 | the Lead Researcher proposes; the callee stores only what survives validation (duplicate or unauthorised site rejected, :383) |
| Trends refreshed before ideas | CONFIG | :358-359 | `settings.trends_enabled` and not `is_fresh` |
| Which channel's numbers are measured, through which account | CODE_RULE + EXTERNAL | :405-437 | per slot its own binding (`analytics_provider_for_channel`); a slot without one is named, never measured through another account; `limit=BATCH` (5) |
| Pages may be fetched today | OWNER (mode) via CODE_RULE | :559, :562, :570-572 | `mode_refusal("research.fetch_page")` (T2, EXTERNAL_READ); refused → only extraction/verification of what is held |
| Which candidate topics get pages | CODE_RULE + CONFIG | :490-522 | `research_budget` (4 candidates, 4 pages; clamped 1..12, research/service.py:734-746, config.py:441-442); pages per topic further capped at `MAX_URLS` = 8 inside `gather_sources` (research/agent.py:84, :725); newest 30 by created/novelty; skip topics with sources, topics that failed today (ESCALATE with `failed`, UTC date), duplicate titles |
| Which pages to read for a topic | LLM_CHECKED_BY_CODE | :527-529 → research/agent.py:707 | the Researcher names pages; the studio fetches them itself from authorised hosts |
| Which sources are extracted today | CODE_RULE | :579-587 | newest 5 (`BATCH`) sources with no claim |
| Which claims are verified first | CODE_RULE | :608-617 | UNVERIFIED with a source; importance CRITICAL < SUPPORTING < FLAVOR, then newest; at most `VERIFY_BATCH` = 24 |
| A claim becomes SUPPORTED | LLM_CHECKED_BY_CODE | :620-628 → factual/agent_pipeline.py:357 | the Fact Checker's verdict; the callee refuses a SUPPORTED/REFUTED verdict whose verbatim `evidence_quote` is not found in the stored source text (factual/agent_pipeline.py:409-418; comment here :625-626); whether the quote really supports the claim stays the model's judgement |
| A new topic may be selected | CODE_RULE | :765-777, `topics_in_production` :670-753 | no SELECTED topic with work still owed (script, storyboard, render, QC verdict, publication) |
| Which topic is produced | LLM_CHECKED_BY_CODE | :807-834 | only when the shortlist (topics with ≥1 SUPPORTED claim) has >1 entry; the Director's `topic_id` must be on the list (agents/director.py:236-238); `select_topic` re-checks producibility (`TopicNotProducible`); any failure → novelty order, `decided_by` None |
| Which topic owes a script, with which notes | CODE_RULE | :861-904, :1003 | newest draft; owed when no draft, no review, or REVISE (notes carried); one topic per run (`[:1]`) |
| Script text | LLM_CHECKED_BY_CODE | :1016-1025 → factual/agent_pipeline.py:642 | ScriptWriter drafts; `ScriptRejected`/`NoVerifiedClaims` (unattributable narration) close the room for the topic (:1061-1069) |
| Story verdict PASS / REVISE / REJECT | LLM_CHECKED_BY_CODE | :1029 → factual/story_review.py:312, :400-470 | computed checks decide; the Director may be stricter, never looser (her REVISE or REJECT on a draft that passed every check is acted on, but a second taste-only REVISE is overridden by code, `taste_settled`, story_review.py:456-458); a REVISE at the wall becomes REJECT |
| Which version of the script ships | LLM_CHECKED_BY_CODE | :1037-1053 → factual/story_review.py:745 | the Director's editorial judgement, up to `editorial_rounds` (10, config.py:15, :434); only versions whose story review passed |
| Script approval | CODE_RULE (after an LLM PASS) | :929-971, :1054-1057 | `review["verdict"] == "PASS"`, `script_grounding` passes, `approve_script_draft` factual gate does not raise |
| How long the writer's room stays open | CONFIG (code constant) | :211, :1014 | `MAX_SCRIPT_EXCHANGES` = `MAX_EXCHANGES` = 20 (factual/story_review.py:111) |
| A storyboard is built from an approved script | CODE_RULE | :1078-1084, :1115-1123 | APPROVED, not storyboarded, at most 5; `FactualGateError` (content gate) holds it |
| Shot prompts for the film | LLM_CHECKED_BY_CODE | :1129-1136 → media/prompt_agent.py:1113 (first `build_visual_bible`, :1018) | Video Editor writes the film's look and the shots; `ShotPlanUnusable` → film waits NEEDS_SHOT_PLAN |
| A lost shot plan is asked again | CODE_RULE | :1192-1276 | NEEDS_SHOT_PLAN, or APPROVED whose last state was LINT_BLOCKED; once a business day, at most `SHOT_PLAN_REASK_DAYS` = 2 days; never a rendered, serial, just-written, or bought-take film |
| Which films the media stage takes | CODE_RULE | :3099-3121 | APPROVED with no COMPLETED render; factual oldest first; one serial episode whose told day is before today (`serial_films_due`, :1341-1363); else one stalled placeholder film when an image provider is READY (:1282-1317) |
| Nothing is bought before the story passed | CODE_RULE | :3150-3179 | `story_gate` (latest review PASS and grounding) |
| PRODUCTION: nothing bought without a model-written plan | CODE_RULE | :3189-3218 | `hold_for_shot_plan` gaps → HELD NEEDS_SHOT_PLAN |
| Staircase (PRODUCTION) or whole-film (TEST) path | OWNER (environment) via CODE_RULE | :3183, :3231-3243 | `studio_environment(engine)` |
| Each paid stair (stills, hero test shot, motion) is bought | OWNER via CODE_RULE | :1846-1881 → media/shooting_sheet.py:3193 | `run_sheet_step(..., unasked=True)`: `may_act` with the Owner's `paid_media_approval` (EVERY_PAID_STEP default), mode, daily budget, film ceiling, balance margin, disk, purchase lease |
| The walk's verdict: ASKED / WAITING / HELD / READY | CODE_RULE | :1866-1881, :1441-1464 | `NEEDS_APPROVAL` → ASKED; `OWNER_DECIDES` → WAITING; anything else → HELD (the Owner's `OWNER_HOLD` included, see Oddities) |
| One factual film a day; a stuck film is passed over | CODE_RULE | :2800-2830, :1992-2006 | `factual_done` set by the first film moved (bought, asked, ready, assembled) or account-wide refusal (`ACCOUNT_WIDE`) |
| A stair is not bought twice in one walk | CODE_RULE | :1826-1845 | the next step is not after the last bought → WAITING NEEDS_OWNER |
| Scenes QC refused are rewritten by the Director, how many times | CODE_RULE (+ LLM rewrites) | :1558-1588 | `DIRECTOR_LADDER_ROUNDS` = 3 per walk, then `queue_film_continue` (:1689-1704); a rung that rewrote nothing ends the walk |
| The narration is voiced at assembly | OWNER (mode) via CODE_RULE + CODE_RULE (budget) | :2637-2669 | `media.paid_generation_over_threshold` if narration > `paid_generation_approval_threshold_usd` (5.0, config.py:392) else `media.paid_generation`; `reserve_spend` must allow |
| A stale factual film is retired | CODE_RULE (recorded as the Director's; threshold CONFIG) | :2204-2247, :2323-2391 | stood still ≥ `film_wait_days` (3, config.py:303) days, counted as the calendar difference of two local business dates (:2237); only APPROVED/NEEDS_SHOT_PLAN, never a rendered, serial, or film with a PENDING approval; a day recorded `moved` (bought, asked, ready, assembled, ACCOUNT_WIDE wait, TEST "use the sheet") or any take change resets the count (:2173-2201) |
| A letter to the Owner about a stopped film | CODE_RULE | :2399-2533 | once per (film, sheet_hash, step, status); none for a closed film, `OWNER_HOLD`, a NEEDS_OWNER/TAKES_NOT_ACCEPTED stop with any QC-refused scene (:2440-2445), or LINT/NEEDS_SHOT_PLAN (sent to the studio's repair, :2430-2435) |
| TEST: a film is attempted under the mode | OWNER (mode) via CODE_RULE | :3310-3347 | per film, `ask_owner=True`; estimate > 5 USD → T3 question; SUPERVISED writes the Approval |
| TEST: the budget holds the film's estimate | CODE_RULE | :3348-3361 | `reserve_spend`; refused before any film → stage SKIPPED; after → film named |
| TEST: a real paid vendor is never handed to the render | CODE_RULE | :3385-3395, :3470-3498 | `legacy_render_vendors` → `PaidVendorRefused`; the film waits for its sheet |
| TEST: motion ceiling | CONFIG | :3452-3465 | the film's motion budget is `test_max_cost_per_generation_usd` 0.60, `test_max_cost_per_second_usd` 0.12, `test_motion_scenes` 2 (config.py:330-336); the non-TEST arms of these expressions are unreachable (see Oddities) |
| Which files QC measures | CODE_RULE | :3706-3735 | `video/*` assets with no non-INVALIDATED report and not a repair intermediate, newest first, at most `BATCH` = 5; a continuation measures only its own `asset_ids` |
| QC pass / fail of a rendered file | CODE_RULE + LLM vision (in media.qc) | :3755-3762 | `evaluate_media_qc` (out of scope, group media) |
| A failed film: ACCEPT / REPAIR (CLOSE refused) | LLM_CHECKED_BY_CODE | :4316-4367, :4442-4591 | the Director's `review_film_qc`; schema-bound to the report (agents/reviews.py:848-890: every finding judged, scenes real, CLOSE refused, `passed_scene_refusal` :781 — a scene that passed unchanged is never REAL and never redone, a still/motion redo only for a scene a REAL finding names — and `repair_refusal` :711 — at least one redo carriable now); ACCEPT refused when a verdict is `not_yours` (:4467-4476; flag computed by code from the report, `director_qc.is_not_yours` media/director_qc.py:196: rights/factual/content-source/production-path checks, file faults, music-licence findings); REPAIR filtered by `director_qc.repair_list` |
| Which of her repairs can be carried out | CODE_RULE | :4636-4660 | film assembled from takes (`SCENE_TAKES`); `protected_redos`, `owner_scene_choices`, scene kinds, free fix used, `already` bought |
| Paid redo limits per scene / per film | CONFIG (+ OWNER card) | :4960-4999 | `film_max_paid_redos_per_scene` 5, `film_max_paid_redos` 20 (config.py:314-315) + `redo_allowance` from the Owner's redo-cap card; only rounds that delivered count (:3951-3974) |
| A paid redo is bought only on a corrected prompt | LLM_CHECKED_BY_CODE | :5000-5008, :4791-4865 | `rewrite_for_redo` must report `rewritten` (or not rewritable); else `PROMPT_NOT_CORRECTED`, nothing bought |
| A take the Owner marked final is never retired | OWNER (mark) via CODE_RULE | :5027-5034 | `retiring & his_final` → `SceneRedoRefused(OWNER_APPROVED)` before pricing |
| Each paid redo purchase | OWNER via CODE_RULE | :5036-5061 → media/assembler.py `redo_scene` | `unasked=True`: `may_act("media.scene_redo")` T3 under the paid-media rule, budgets, ceiling, lease; `director_repair=True` may replace a non-final approval |
| Free fixes once per failed film | CODE_RULE | :4947-4955, :5244-5245, :3864-3872 | encode, card, audio; not when the film's line already had a repair (`_repaired_assets`) |
| The repaired film is measured again, once | CODE_RULE | :5265-5280 | `evaluate_media_qc` on `new_asset` |
| How many Director rounds per failed film in one walk | CODE_RULE | :4028-4032, :4080-4151 | `DIRECTOR_QC_ROUNDS` = 4; one re-read after NOTHING_DONE; a FAILED repaired film yields to other queued films (:4155-4190) |
| A candidate a gate refused becomes her approved take | LLM | :4370-4439 → agents/reviews.py:1148 | the Director picks one candidate index (schema `look_schema(n)`) or rejects all; recorded by `director_qc.record_look` |
| Redo cap reached → the Owner's card | CODE_RULE → OWNER | :5171-5186 | limited and nothing bought, asked or applied → `propose_redo_cap_card` |
| A continuation may walk the film | CODE_RULE | :5476-5525 | stop off, safe mode off, PRODUCTION, mode allows `media.paid_generation` T2, board APPROVED, story gate passed (or a render exists) |
| A film may go to its channel: the Director's viewing | LLM (refusal) / LLM_CHECKED_BY_CODE (approval) | :5702-5736 → agents/editorial.py:428 | a stored verdict (`latest_editorial`) is reused, not asked again (:5702-5704, :5726-5728); code's `hard_rejects` refuse before the model (agents/editorial.py:448-454); not APPROVE → not published, and excluded from the queue (:6060-6064); APPROVE → the publishing gate still decides |
| Visibility of the upload | OWNER (channel policy) + CODE_RULE (rights) | :5741-5755 | `resolve_publish_visibility(channel, environment)`; licence not confirmed → private, no schedule (`_private_until_licensed`, :5972) |
| Publishing gate | CODE_RULE | :5756-5771 | `evaluate_publishing_gate` (out of scope, group publishing) |
| Title, description, tags | LLM_CHECKED_BY_CODE | :5773-5827 → agents/reviews.py:1485 | Publisher READY/HOLD; `publication_metadata_refusals` computed in the callee and again for a lifted HOLD (:5791-5796) |
| The upload itself | OWNER (mode) via CODE_RULE | :5845-5875 | `may_act("publishing.public_publish")` T3; MANUAL refuses, SUPERVISED asks for this asset under this policy version, AUTONOMOUS_CEO proceeds |
| Whether the upload went out | EXTERNAL | :5877-5938 | `publish_media_asset` status in `OUT_ON_THE_CHANNEL` (:5663) |
| Which film to which channel | CODE_RULE | :6072-6117 | the storyboard's route (`select_channel_for`); one film per channel per run; newest render per film; never a film the channel carries |
| Old STATUS reports archived | CODE_RULE | :6203-6227 | older than `REPORT_SHELF_DAYS` = 3 |
| The evening review comes round again | CODE_RULE (+ LLM) | :6264-6283 | up to 3 passes while `left_open` and something was reviewed |

## LLM involvement

**No LLM call site is in these files.** Verified by reading and by search: `stages.py` never calls
`run_agent_task`, `structured_run`, `run_with_strategy`, `reviews._run` or `prompt_agent._run`;
`models.py` and `__init__.py` contain no functions. Static analysis agrees (0 call sites,
inventory.json).

**But this module is the main caller of models in the backend.** 32 of its 93 functions (holding
4181 of its 5709 function lines) have a static path to a model, and they reach 28 of the
backend's 38 LLM call sites at 20abffd (transitive closure over docs/project/backend_map/callgraph.json,
regenerated at 20abffd; the 38th site, `media.second_look._look`, added after b00083c, is reached
from `_walk_staircase` (through `recover_paid_takes` and `run_sheet_step`) and from `_apply_repairs`
(through `redo_scene`), see `_walk_staircase` below; the ten not reached are `agents.history.chat`,
`agents.mail.answer_mail`,
`agents.command._choose`, `agents.repairs.agent_health._probe`, the agents router's
`run_agent`, the settings router's `test_agent_llm`, `media.model_research.research_models`,
`runbook.weekly.execute_weekly_review`, `factual.script_agent.draft_with_agent` and
`media.blocker_repair.director_assignment` — the last one is reached asynchronously through the
task queue, see `_sheet_letter` below). What this module does is decide, by code, when each of those models
is asked, how often, and what is done with the answer. Each indirect path below names the call
here, the call site it reaches, and how this module treats the answer (trust vocabulary applied
to what *this* code does with it).

### The research and selection stages

| Function here (call line) | Reaches call site | Speaker | What this code does with the answer | Trust here | If the model fails | Money |
|---|---|---|---|---|---|---|
| `_idea_generation` (:361) | `app.research.agent.propose_topics` (research/agent.py:398) | Lead Researcher | counts `proposed`/`rejected`; a `blocked` answer becomes the stage reason (:374-377) | CHECKED_BY_CODE (the callee stores only what survives validation) | `ResearchAgentError`/`NoResearcher`/`ValueError` → COMPLETED "proposals refused", 0 proposed (:366-373); `NoAuthorisedHosts` → SKIPPED (:364-365) | tokens only |
| `_gather_for_candidates` (:527) | `app.research.agent.gather_sources` (research/agent.py:707) | Lead Researcher | counts `fetched` pages | CHECKED_BY_CODE (the studio fetches from authorised hosts itself) | logged and skipped per topic (:531-532) | tokens; external reads |
| `_research_and_verification` (:592) | `app.factual.agent_pipeline.agent_extract_claims` (:208) | Lead Researcher | extraction counted; claims stay UNVERIFIED until verified | ADVISORY (candidates for verification) | `ValueError` → that source counted unreadable, the next is read (:594-599) | tokens |
| `_research_and_verification` (:622) | `app.factual.agent_pipeline.agent_verify_claim` (:357) | Fact Checker | counted verified | CHECKED_BY_CODE (a SUPPORTED/REFUTED verdict's verbatim quote must be found in the stored source, factual/agent_pipeline.py:411-418; comment here :625-626) | any `Exception` counted as "verdict refused" (:624-628) | tokens |
| `_selection` (:810) | `app.agents.director.choose_topic` (agents/director.py:195) | Director (task `choose_topic`, `REVIEW_TEMPLATE_VERSION`, temperature 0.1, 2400 tokens) | `TopicChoice {topic_id, reason}` moves the chosen topic to the front of the candidate list; `select_topic` records it with `decided_by="Director"` and her notes | CHECKED_BY_CODE (id must be on the shortlist; `select_topic` re-checks producibility) | `DirectorError`/`ValueError` → deterministic novelty order, logged `director_choice_refused` (:815-818) | tokens |

### The script and storyboard stage

| Function here (call line) | Reaches call site | Speaker | What this code does with the answer | Trust here | If the model fails | Money |
|---|---|---|---|---|---|---|
| `_script_and_storyboard` (:1016) | `agent_write_script` (factual/agent_pipeline.py:642) | ScriptWriter | new draft id goes to the story review | CHECKED_BY_CODE (callee refuses narration not attributable to SUPPORTED claims) | `ScriptRejected`/`NoVerifiedClaims` → topic's room closes for today, the day goes on (:1061-1069) | tokens |
| `_script_and_storyboard` (:1029, :1096) | `review_story` → `_ask_director` (factual/story_review.py:544, template `story-review-v1`) | Director | `verdict` drives the loop: PASS → editorial judgement + approval; REJECT → stop; REVISE → `notes` brief the next draft (:1037-1060) | CHECKED_BY_CODE for a PASS (computed checks set the ceiling; story_review.py:400-411); her REVISE/REJECT of a draft the checks passed is acted on as given, except a second taste-only REVISE, which code overrides (story_review.py:456-475) | the computed checks decide alone (story_review.py:16-18); `StoryReviewError` on the backlog review is logged (:1102-1103) | tokens |
| `_script_and_storyboard` (:1042) | `judged_story` → `app.agents.editorial_judgement.judge` (:410) and `agent_write_script` rewrites | Director (judge), ScriptWriter (rewrites) | replaces `script_id` and `review` with the best-scored shipped version (:1051-1053) | CHECKED_BY_CODE (each version must pass the story review; approval then re-checks grounding and the factual gate) | out of scope (factual group) | tokens; up to `editorial_rounds` = 10 versions |
| `_script_and_storyboard` (:1130), `_reask_shot_plans` (:1258) | `app.media.prompt_agent.write_shot_prompts` (:1113), which first calls `build_visual_bible` (:1018, task `visual_bible`; called at prompt_agent.py:1164) | Video Editor (`PROMPT_ROLE` = "VideoEditor", prompt_agent.py:76) | counts shots; the look and the prompts stored are what the staircase later buys from | CHECKED_BY_CODE (`ShotPlanUnusable` → NEEDS_SHOT_PLAN; lint in prompt_agent; `hold_for_shot_plan` in PRODUCTION :3189-3218; the bible's aspect ratio and quality target are overwritten by code and it falls back to a composed bible without a model, prompt_agent.py:1067-1072) | `ShotPlanUnusable` → film waits for a plan (:1132-1134); `PromptError` logged (:1135-1136); re-ask outcome event UNUSABLE/REFUSED (:1260-1275) | tokens now; leads to paid stills/motion later, under the Owner's rule |

### The media stage and the Director's ladder

| Function here (call line) | Reaches call site | Speaker | What this code does with the answer | Trust here | If the model fails | Money |
|---|---|---|---|---|---|---|
| `_director_rung` (:1679) | `scene_rewrite.director_ladder` → `director_brief` (:1335), `_editor_rewrite` (:1847), `review_rewrite` (:1650) | Director (brief, review), Video Editor (rewrite) | `rewritten` non-empty → the film is walked again (so the rewritten scenes can be bought); empty → walk ends with "the studio retries the rewrite by itself" (:1571-1588) | CHECKED_BY_CODE (rewrite compiled and linted in scene_rewrite; since a50407e her review must answer every one of QC's findings by id, once, and an untreated finding must name a field the Video Editor may change on that layer or quote words the layer keeps, `review_schema`, scene_rewrite.py:402-440; a motion rewrite whose findings are locked in the motion layer turns to the still in the same rung, `rewrite_failed_scene`, scene_rewrite.py:2923-2935; buying still goes through `run_sheet_step`'s gates) | any exception → `not_rewritten` with the error words; the walk's stop stands (stages.py:1680-1686) | tokens; then paid stills/motion via the walk |
| `_walk_staircase` (:1749, :1847) | `recover_paid_takes`/`run_sheet_step` → `picture_qc.judge_still` (:1765), `judge_clip` (:2074), `sound_design.sound_plan` (:379); since 20abffd also `second_look._look` (media/second_look.py:653) through `stills_stage._director_looks` (media/stills_stage.py:1038) and `fix_check.shot_second_look` (media/fix_check.py:713) | vision `LOOKERS` = VideoEditor, Director, QualityAssurance (media/picture_qc.py:119) for the stills gate and clip QC; the Director's second look at a refused still or clip before a re-roll or retry is bought (a still she lets stand is APPROVED by `director_look`, a clip she keeps is ACCEPTED_BY_LOOK, and nothing more is bought for it: media/stills_stage.py:1143-1149, media/qc.py:2670-2683); Voice Artist | only the step's result is read here (`needs_owner`, `needs_still`, `stopped`, `mode_stopped`, `hero_accepted`) | CHECKED_BY_CODE (inside media) | inside media | the stairs are the money (see Money paths) |
| `_assemble_from_takes` (:2673), `_media_films` (:3396), `_reencode_from_takes` (:5323) | `sound_design.sound_plan` via the assembler | Voice Artist | the mix plan | ADVISORY (falls back to the deterministic plan without a model, per :5297-5300) | deterministic sound plan | none for the plan |
| `_media_films` (:3225) | `describe_serial_shots` (media/serial_storyboard.py:375) → `write_shot_prompts`, `build_visual_bible` | Video Editor | serial shots described "once per look" before anything is bought | CHECKED_BY_CODE (as above) | never raises for a refusal; the studio's composed shots are kept (serial_storyboard.py:383-385) | tokens |
| `_sheet_letter` (:2434) | `media.blocker_repair.submit_sheet_issues` (:437) queues a `FILM_SHEET_REPAIR` task (:44); the worker later runs `process_sheet_repair` → `director_assignment` (media/blocker_repair.py:557, :818; workflows/worker.py:446). Not on the static call graph: asynchronous, through the task queue | Director | for a LINT_BLOCKED / NEEDS_SHOT_PLAN stop the studio's repair is queued instead of a letter to the Owner | out of scope (group media repair) | out of scope | tokens |
| `_media_films` (:3366) | `app.agents.reviews.review_narration` (:203) | Voice Artist | verdict recorded in `narration_reviews`; never holds the render (:3069-3072) | ADVISORY (a FLAG escalates to the Director inside the callee, per :3070) | error string recorded (:3370-3371) | tokens |

### Edit and QC: the Director decides a failed film

| Function here (call line) | Reaches call site | Speaker | What this code does with the answer | Trust here | If the model fails | Money |
|---|---|---|---|---|---|---|
| `_edit_and_qc` (:3755), `_apply_repairs` (:5270) | `media.qc.evaluate_media_qc` → `picture_qc.evaluate_pictures` (:904), `judge_clip` | vision "LOOKERS" | `report["status"]` PASSED/FAILED routes the film | CHECKED_BY_CODE (media QC combines measured gates and vision checks) | NOT_APPLICABLE checks per media group | none |
| `_edit_and_qc` (:3775) | `app.agents.reviews.review_failed_render` (:455) | Video Editor (Kael) | the diagnosis (`correction`) is passed to the Director as context for round 0 (:3789-3791) | ADVISORY | error recorded in `diagnoses` (:3779-3786); the Director still reads the report | tokens |
| `_director_reads` (:4326) | `app.agents.reviews.review_film_qc` (:981; `structured_run`, schema `decision_schema`) | Director | `decision` (ACCEPT / REPAIR; CLOSE fails validation), `verdicts` per finding, `repairs` [{scene_index, redo, reason}], `summary` become the decision record; lessons recorded (:4345); carried out by `_carry_out` | CHECKED_BY_CODE: schema forces every finding judged, scenes real, CLOSE refused, no redo of a scene that passed unchanged and no still/motion redo without a REAL finding on that scene (`passed_scene_refusal`, agents/reviews.py:781, :881), a REPAIR that can be carried out (`repair_refusal`, :711, :885) (agents/reviews.py:848-890); here ACCEPT is refused when any verdict is `not_yours` (a flag code computes from the report, `director_qc.is_not_yours`, media/director_qc.py:196: rights, factual, content source, production path checks, `NOT_YOURS_CHECKS` :151, plus file-fault and music-licence findings) (:4467-4476); REPAIR is filtered by `repair_list` and every purchase passes limits, `PROMPT_NOT_CORRECTED`, `redo_plan` buyable, the Owner's final approvals and `may_act` (:4868-5281) | no model, `NoReviewer`, `ReviewError` (two invalid answers) or `ValueError` → `wait_for_director`: nothing redone, the watchdog asks again (:4321-4328) | yes: REPAIR buys paid still/motion redos |
| `_director_looks` (:4428) | `app.agents.reviews.review_bought_pictures` (:1148) | Director (vision) | her choice of one candidate (or rejection of all) is recorded by `director_qc.record_look`; a choice makes the decision ready to carry on in the same round, a rejection lapses it (:4242-4244) | FINAL (schema-validated index only, `look_schema`, agents/reviews.py:1113; it can override a stills-gate or clip-QC refusal; `record_look` does not apply a choice when the take changed since she was shown it, media/director_qc.py:2086-2087; the Owner's own look still wins per media/director_qc.py:1834) | no model or invalid twice → `wait` (watchdog back-off), nothing chosen (:4425-4432) | none here; an approved take lets the motion or rejoin proceed |
| `_correct_before_redo` (:4819, :4834) | `scene_rewrite.rewrite_for_redo` (:2991) | Director (brief), Video Editor (rewrite) | `rewritten` → the redo may be priced; `same_prompt` on a motion → escalates to the still layer (:4820-4847); the callee's `layer_exhausted` (since a50407e) is not read here (Oddity 26) | CHECKED_BY_CODE (no rewrite → `PROMPT_NOT_CORRECTED`, nothing bought) | exception → treated as not rewritten → refusal recorded (:4848-4853) | gates a paid redo |

### Publish, the serial, post-run

| Function here (call line) | Reaches call site | Speaker | What this code does with the answer | Trust here | If the model fails | Money |
|---|---|---|---|---|---|---|
| `_publish_one` (:5711) | `app.agents.editorial.editorial_review` (:428) | Director (watches the film) | verdict APPROVE or REJECT (agents/editorial.py:92); not APPROVE → not published, reasons returned; later runs skip the asset (:6060-6064); the callee also sets a REJECTed film's storyboard REJECTED (agents/editorial.py:546-549) and rejects by code first when `hard_rejects` exist (agents/editorial.py:448-454) | FINAL for a refusal; CHECKED_BY_CODE for an approval (gate, Publisher, mode follow) | no model → SKIPPED (:5705-5709); `EditorialError`/`ValueError` → SKIPPED (:5719-5724) | none |
| `_publish_one` (:5806) | `app.agents.reviews.prepare_publication` (:1485) | Publisher | `READY` → title (cut to 100 chars), description, tags used for the upload; HOLD → not published | CHECKED_BY_CODE (`publication_metadata_refusals` in the callee, agents/reviews.py:1592, and again on the upload path, `publish_media_asset` → `create_publication_intent`, publishing/services.py:1589, :1667); a HOLD is acted on as given | no model → SKIPPED (:5798-5804); `ReviewError`/`NoReviewer`/`ValueError` → SKIPPED (:5809-5814) | none |
| `_serial_queue` (:6188), `_serial_next` (:6197) | `run_serial_stage`/`run_serial_next_stage` → `story.services.write_episode` (:1558), `story.review.review_episode` (:946), `editorial_judgement.judge`, `write_shot_prompts` | ScriptWriter (showrunner), Director | the callee's outcome is returned unchanged | out of scope (group story) | callee reports SKIPPED/COMPLETED | tokens |
| `_post_run` (:6241) | `app.economy.accountant.reconcile_day` (:1188; `structured_run`, schema `AccountantReport`) | Accountant | `intent`, `headline`, `holds` become the `books` outcome filed with the day's reports; the headline and the figures are computed by code, the model adds summary, recommendations and `holds`, and its `continue_spending: false` turns the close into an ESCALATE (economy/accountant.py:1249-1264) | INFORMATIONAL here (no control effect in this module) | error words in `books` (:6242-6244) | none (figures come from the books) |
| `_post_run` (:6267, :6275) | `app.agents.director.director_review` (:492) | Director | counts `reviewed`, `applied`, `left_open`, `priorities` | out of scope; actions on her inbox are checked in agents/director.py (e.g. :370) | first pass fails → letter to the Owner "Nu am putut revizui ziua" signed «— Sarah» (:6284-6300); a later pass failing keeps the first (:6274-6278) | tokens |

### How much is model and how much is rule, in this group

- Models write and judge: topics, page choices, claims, verdicts on claims, the day's topic
  choice, scripts, story opinions, editorial scores, the film's look (visual bible) and shot
  prompts, prompt rewrites, the sheet-repair assignment (asynchronous), pictures'
  and clips' acceptance (vision), the failed-film decision, picture picks, the viewing before
  publish, publication metadata, the Accountant's and Director's evening text.
- Code decides everything that moves money or leaves the studio: whether a stage runs (mode),
  how many items per day (`BATCH` 5, `VERIFY_BATCH` 24, 1 topic, 1 factual film, 1 serial, 1 film
  per channel), when a model is asked again (20 exchanges, 2 re-ask days, 3 ladder rounds, 4 QC
  rounds), what is bought (every purchase goes through `may_act`, the Owner's paid-media rule,
  `reserve_spend`, the film ceiling and the lease, in another module), the limits on redos, the
  Owner's final approvals, retirement after `film_wait_days`, which channel a film goes to,
  the publishing gate and the visibility.
- Model answers acted on with no content check beyond shape/schema are of two kinds, and none
  of them buys anything by itself:
  - refusals that withhold: the Director's refusal at the viewing (`_publish_one`, :5729-5736;
    it also sets the storyboard REJECTED, agents/editorial.py:546-549), the Publisher's HOLD
    (:5815-5822), and the Director's REVISE/REJECT of a story the computed checks passed
    (factual/story_review.py:456-475; a second taste-only REVISE is overridden by code);
  - choices among options code already validated: the day's topic (must be on the shortlist,
    :810), the shipped script version (only versions whose story review passed, :1042), and her
    pick among candidates a gate refused (`_director_looks`, :4428), which can override a stills
    gate or clip-QC refusal and so lets the next paid stair proceed under every money gate.
    Since 20abffd there is one more of this kind, outside this module but on every stair it
    walks: the Director's second look at a still or clip QC refused, asked inside the stills stage and
    clip QC before a re-roll or retry is bought (`second_look._look`, media/second_look.py:653;
    media/stills_stage.py:1143-1149; media/qc.py:2670-2683, :2737-2751). Code limits it to
    refusals that are readings (the bible's hard limits and unmeasured checks stay the code's,
    media/fix_check.py:130); a still she lets stand is APPROVED by `director_look`, a clip she
    keeps is ACCEPTED_BY_LOOK, nothing more is bought for it, and the walk goes on to the next
    stair under the same money gates. Her film-QC REPAIR redo bought by `_apply_repairs`
    (stages.py:5036-5061) is not preceded by such a look (Oddity 27).
- Her ACCEPT of a failed film is the one model answer that turns a QC failure into a
  publishable film; code refuses it for `not_yours` findings and the publishing gate's rights and
  factual checks still run, but for every finding that is hers the judgement is the model's.

## Hard rules and limits

| Name | Value | Where | What it limits |
|---|---|---|---|
| `COMPLETED`, `SKIPPED` | strings | stages.py:203-204 | runner outcome vocabulary; `BLOCKED` comes from runbook/services.py:182 |
| `MAX_SCRIPT_EXCHANGES` | `MAX_EXCHANGES` = 20 | :211; factual/story_review.py:111 | drafts of one story in one run |
| `BATCH` | 5 | :213 | sources extracted, measurements, approved scripts storyboarded, QC files measured per run |
| `VERIFY_BATCH` | 24 | :216 | claims verified per day |
| `STAGE_ACTIONS` | 11 entries | :256-268 | action and tier per stage: performance_intake T0, idea_generation T1, research T2, selection T1, script T1, serial_queue T1, media T2, edit_and_qc T1, publish T3, post_run T1, serial_next T1 |
| `IDEA_POOL_TARGET` | 6 | :332 | topic pool size above which nothing is proposed |
| `STEP_WORDS` | stills / test_shot / motion | :1428-1432 | the paid stairs in the Owner's words |
| `OWNER_DECIDES` | 11 refusals | :1441-1464 | refusals that make a film WAITING (HERO_NOT_APPROVED, HERO_FIRST, LOW_BALANCE, OVER_DAILY_BUDGET, OVER_BUDGET, NEEDS_REFERENCE, OVER_FILM_BUDGET, BLOCKED_NO_BUDGET, FILM_BUSY, LOW_DISK, BLOCKED_MODE) |
| `DIRECTOR_LADDER_ROUNDS` | 3 | :1609 | Director rewrite rounds per walk; then a continuation |
| `LADDER_REFUSALS` | NEEDS_OWNER, TAKES_NOT_ACCEPTED | :1611 | stops whose scenes may be QC's to answer |
| `SHOT_PLAN_REASK_DAYS` | 2 | :1946 | business days a lost shot plan is asked again |
| `ACCOUNT_WIDE` | 6 refusals | :1949-1959 | refusals that end the walk and never retire a film |
| `BOUGHT_TAKE_STATUSES` | SUBMITTED, PAID, APPROVED, REJECTED, LOST | :1961 | takes that cost or may have cost credits |
| `_BUDGET_WAITS` | 4 refusals | :2537-2558 | letter headlines for budget waits |
| `DIRECTOR_QC_ROUNDS` | 4 | :4032 | Director rounds per failed film in one walk |
| `OWNER_APPROVED_REDO` | "OWNER_APPROVED" | :4038 | refusal code for a redo that would retire a final approval |
| `PROMPT_NOT_CORRECTED` | string | :4734 | refusal code for a paid redo whose prompt was not rewritten |
| `OUT_ON_THE_CHANNEL` | PUBLISHED, PUBLISHED_SIMULATED, SCHEDULED, REMOTE_CONFIRMED | :5663 | what counts as published |
| `SETTLING_ELSEWHERE_STATES` | FAILED_RETRYABLE, NEEDS_RECONCILIATION | :5667 | publications the day does not offer again |
| `REPORT_SHELF_DAYS` | 3 | :6205 | STATUS reports archived after |
| Evening review passes | ≤ 3 | :6268 | `director_review` re-runs while messages are left |
| Topic rows read | 30 (gather), 20 (selection) | :513, :783 | candidate windows |
| Settings read | `film_wait_days` 3 (config.py:303); `film_max_paid_redos_per_scene` 5, `film_max_paid_redos` 20 (config.py:314-315; code fallbacks 1 and 2 at :4213-4214, :4967-4968); `paid_generation_approval_threshold_usd` 5.0 (config.py:392); `motion_budget_usd` 12.0 (config.py:258); `test_max_cost_per_generation_usd` 0.60, `test_max_cost_per_second_usd` 0.12, `test_motion_scenes` 2 (config.py:330-336); `research_candidates_per_day` 4, `research_pages_per_topic` 4 (config.py:441-442); `editorial_rounds` 10 (config.py:15, :434); `film_purchase_lease_seconds` 10800 (config.py:275); `timezone` Europe/Bucharest (config.py:52) | | |
| External limits relied on | `director_qc.BOUGHT_WAIT_DAYS` 3 (media/director_qc.py:126); `NOT_YOURS_CHECKS` (:151); `FINAL_OUTCOMES`, `PENDING_OUTCOMES` (:121, :145); worker `FILM_CONTINUE_DEFERRALS` 3, `FILM_CONTINUE_DEFER_SECONDS` 600 (workflows/worker.py:133-134); `approval_expires_after_hours` 24, `paid_media_approval_expires_hours` 48 (config.py:401, :408) | | |

**State machines visible here.**

- Film walk status (`_walk_staircase` → `_film_staircase`): `READY` (nothing left to buy) |
  `ASKED` (an Approval stands) | `WAITING` (only the Owner, the account or QC's ladder can move it)
  | `HELD` (the film's own fault) | `CLOSED` (Owner or Director closed it) → after assembly
  `ASSEMBLED` | `REFUSED` | `STOPPED` | `NO_ENGINE`, or ASKED/HELD from the narration's mode or
  budget refusal and WAITING `FILM_BUSY` from the assembly lease (:2653-2669, :2873-2942).
- Recorded film day (`FILM_STATE_EVENT` payload): business_date, status, refusal, step, reason,
  moved (:2143-2150); deduplicated on everything but the reason (:2163-2165).
- Director QC outcomes (`director_decides_failed_film`): ACCEPTED, ACCEPT_REFUSED, REPAIRED,
  ASKED, BOUGHT_WAITING, CLOSED, NOTHING_DONE, WAITING (:4064-4065, :4536-4543).
- Topic: SELECTED live vs stalled (`topics_in_production`, :714-752). Storyboard statuses read:
  APPROVED, NEEDS_SHOT_PLAN, REJECTED (set by `close_film_books`, :2299).

## Modules

### `app.runbook` — backend/app/runbook/__init__.py (5 lines)

Docstring only: "Phase 10 — the daily autonomous runbook: preflight, staged run, and safe mode."
It re-exports nothing because `app/models.py` imports `app.runbook.models` to register the tables
and pulling the router in "would close an import cycle through the service layer" (:3-4).

### `app.runbook.models` — backend/app/runbook/models.py (74 lines)

Two SQLAlchemy tables; no functions.

| Table | Line | Columns of note | Why |
|---|---|---|---|
| `DailyRun` (`daily_run`) | 11 | `business_date`, `preflight_status` READY/DEGRADED/BLOCKED, `preflight_json`, `status` RUNNING/COMPLETED/PARTIAL/BLOCKED/FAILED (derived, never written directly by a caller), `stages_json`, `stages_total` (CHECK `stages_total >= 0`, :22; `stages_completed` has no check), `stages_completed`, `stopped_at_stage`, `stop_reason`, `fault_class` TRANSIENT/HARD, `started_at` (indexed, :23), `finished_at`, `event_id` → `domain_event` | "a run cannot report success while carrying a stage that never ran" (:14-17); a transient fault did not open safe mode and may be retried, a hard one waits for a person (:40-42) |
| `SafeModeRecord` (`safe_mode_record`) | 51 | `reason`, `trigger` PREFLIGHT/STAGE_FAILURE/OWNER, `run_id` → `daily_run`, `entered_at`, `cleared_at` (indexed, :60), `cleared_notes`, `event_id` → `domain_event` | "entering safe mode is easy and leaving it is not": a P0 is cleared by a person with a note (:52-56) |

Data: written by `app.runbook.services` (DailyRun at runbook/services.py:953 and :1855,
SafeModeRecord at :674); `stages.py` only mentions `DailyRun` in a comment (:5425:
`continue_film` "writes no DailyRun"). Read elsewhere: `DailyRun` by goal.py:42,
publishing/licence_release.py:162, workflows/passes/serial_unfilmed.py:145 and
workflows/worker.py:190; an open `SafeModeRecord` by app/services.py:709 (the Policy Kernel) and
media/sheet_words.py:245.

### `app.runbook.stages` — backend/app/runbook/stages.py (6426 lines)

Purpose: the work behind each daily stage, the PRODUCTION staircase walk, the Director's QC
decision loop and its repairs, publication, the evening close, and the per-film continuation.
Module docstring: :1-38.

#### Stage gating and shared helpers

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `mode_refusal` | 271 | Asks `may_act` in its own transaction; returns None when allowed, when the answer is `BLOCKED_STOP`, or when it is `NEEDS_APPROVAL` with `ask_owner=False`; otherwise the verdict (reason, mode, tier, status, approval_id) | One door for the Owner's mode; under SUPERVISED a T3 writes or spends the Approval for this exact `subject`; the stop is read elsewhere on purpose (:285-299) | OWNER (mode) via CODE_RULE |
| `_has_language_model` | 320 | True when any provider is registered | "no model configured" reported as a skip with a reason (:321-325) | CODE_RULE |
| `build_stage_runners` | 6330 | Returns the 11 runner closures; each `keep()` wrapper asks the mode with `ask_owner=False`, stores the outcome in `outcomes` for `post_run` | Stages with real work; asking left to the stage that knows the film (:6352-6359) | CODE_RULE |

Helpers: `_outcome` (:219) builds the runner dict; `_credits_words` (:1492), `_usd_words`
(:1499), `_scenes_ro` (:1637), `_no_stop` (:1978), `_skip` (:1983) format Romanian words.

#### Performance intake, ideas, research

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_performance_intake` | 391 | For every YouTube slot, builds an analytics adapter from that slot's own binding and measures up to 5 publications; vault errors and unbound slots are named, not measured | Retention was once asked of the wrong channel's account (:398-403) | CODE_RULE + EXTERNAL |
| `_idea_generation` | 335 | Skips without a model; does nothing when ≥6 PROPOSED/RESEARCHED topics exist; refreshes trends if enabled and stale; asks the Lead Researcher for `6 − pool` topics | runbook §3; a refused proposal is "the validation working" (:367) | CODE_RULE + LLM_CHECKED_BY_CODE |
| `_gather_for_candidates` | 479 | Picks up to `research_candidates_per_day` topics without sources (not failed today, unique titles) and gathers `research_pages_per_topic` pages each | "two candidates of three pages... left the studio with nothing" (:486-488) | CODE_RULE + LLM_CHECKED_BY_CODE |
| `_research_and_verification` | 536 | Asks the mode for `research.fetch_page`; if allowed, retests stale hosts and gathers pages; extracts up to 5 newest unread sources; verifies up to 24 claims, most important then newest | A claim nobody checked is not research (:541-543); backlog fixes of 2026-10-02 (:576-578, :602-607) | CODE_RULE + LLM_CHECKED_BY_CODE |

#### Selection and scripts

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `topics_in_production` | 670 | Splits SELECTED topics into live (work owed) and stalled (REJECTED storyboard, refused story, editorial REJECT, failed/invalidated QC); a published film's topic is neither | Seven topics stuck SELECTED for days; REJECT stories and published films blocking selection (2026-09-12) (:673-686) | CODE_RULE |
| `_selection` | 756 | Returns the live topic if any; else shortlists topics with SUPPORTED claims; asks the Director when >1; `select_topic` in order; reports orphan SUPPORTED claims | runbook §5; "the Director decides, under policy" (:757-762) | LLM_CHECKED_BY_CODE / CODE_RULE |
| `script_work` | 861 | Topics owing a script and the notes of their last reading (no draft, unread draft, REVISE); skips storyboarded, superseded, PASS and REJECT drafts | A story sent back twice used to sit forever (:864-872); a crashed run's unread draft (:893-897) | CODE_RULE |
| `_script_awaiting_owner` | 907 | The newest VERIFIED_PASS, unstoryboarded, story-PASS draft (one the Director should have approved but did not) | 28 drafts made every day claim a script awaited the Owner (2026-10-02) (:910-912) | CODE_RULE |
| `_director_approves` | 929 | On PASS: re-measures `script_grounding`; calls `approve_script_draft` with the Director as approver | Approval is hers (Owner, 2026-09-12); a telescope film on the Nepal topic was approved when grounding was not asked (:941-945) | CODE_RULE |
| `_script_and_storyboard` | 974 | One topic: write → story review → (PASS) editorial judgement → approve, up to 20 exchanges; reviews unreviewed approved scripts; builds up to 5 storyboards with their shot prompts; re-asks lost shot plans; reports a script awaiting the Owner | Text is cheap, renders cost money: the conversation happens in full the same day (:1008-1012) | LLM_CHECKED_BY_CODE |
| `_reask_shot_plans` | 1192 | Asks `write_shot_prompts` again for NEEDS_SHOT_PLAN or lint-blocked APPROVED factual films, once a day, ≤2 days, never with bought takes; records `runbook.shot_plan_reasked` | Only the POST /prompts route re-asked; a plan the model lost stayed lost (A4) (:1203-1206) | CODE_RULE |

#### Media: selection of films, TEST whole-film path

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `stalled_storyboards` | 1282 | Rendered storyboards whose QC failed for placeholders (or was invalidated), one per title, only when an image provider is READY | Re-render once real images exist, never the same placeholder film twice (:1283-1285) | CODE_RULE |
| `_budget_left_usd` | 1320 | min(`motion_budget_usd`, every active budget's remaining) | Meant as the per-film motion ceiling of the whole-film path outside TEST (:3301-3306, :3452-3456); since that path only runs in TEST, its value is computed but never used (see Oddities) | CODE_RULE |
| `is_serial_storyboard` | 1332 | `channel_type_for_storyboard(board) == "OFFICE_SERIAL"` | Same mapping as publish routing (:1335-1337) | CODE_RULE |
| `serial_films_due` | 1341 | Serial storyboards whose episode's day is before today | The Owner's approve button builds a storyboard at once; an episode of today must not be filmed before its day ends (:1344-1349) | CODE_RULE |
| `_release` | 1366 | Releases a reservation; errors logged | A film not made has no cost rows; the watchdog sweeps leftovers (:1367-1372) | CODE_RULE |
| `_record_failed_attempt` | 1382 | Books the cost of what a failed render bought (`record_failed_render_cost`) from the newest FAILED job's `production_json` | The vendor charges for shots of an unfinished film (:1385-1392) | CODE_RULE |
| `_media` | 3041 | `_media_films`, then (unless BLOCKED) `retire_stale_films`, adding the retired titles to the reason | A stuck film must not hold its topic forever (A4) | CODE_RULE |
| `_media_films` | 3064 | Chooses the films; records NEEDS_SHOT_PLAN days; applies the story gate; in PRODUCTION holds films without a model plan; in both environments has the serial episode's shots described (:3223-3225); in PRODUCTION then hands off to `_media_staircase`; in TEST runs the whole-film path: per film the stop, the mode (T2/T3 by estimate), `reserve_spend`, Voice Artist review, refusal of any real paid vendor, `assemble_video_job` with TEST cost caps, cost booking and settlement; writes the waiting-approvals letter once | runbook §8; the gate before the money (:3150-3151); questions reach the Owner the same morning (:3610-3618) | CODE_RULE (+ OWNER mode) |

#### Media: the PRODUCTION staircase

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `sheet_wiring` | 1467 | The selected Runway connection id, its capabilities, image adapter, account, per-model video adapters, resolution, media root | One wiring for sheets and steps; opens no connection | CONFIG + CODE_RULE |
| `_film_staircase` | 1504 | Under the film's purchase lease: walks the film; while the stop is off and QC refused scenes, runs up to 3 Director rewrite rounds and walks again, then queues a continuation; a busy lease → WAITING, a closed film → HELD | MONEY-04 (no double buying); the Owner's rule "redone until QC passes" (:1534-1538) | CODE_RULE |
| `_ladder_scenes` | 1615 | Scenes of a WAITING NEEDS_OWNER/TAKES_NOT_ACCEPTED walk whose newest take QC refused | QC's refusal is the Director's, not the Owner's | CODE_RULE |
| `_quality_scenes` | 1623 | `scene_rewrite.quality_refused`, [] on any error | as above | CODE_RULE |
| `_held_words` | 1646 | Splits held scenes into QC-refused (the Director's rewrite) and others (the Owner's decision) | 2026-10-12: a QC-refused scene was announced as waiting for the Owner (:1649-1650) | CODE_RULE |
| `_director_rung` | 1668 | One `director_ladder` round; any fault becomes `not_rewritten` | The ladder must never break the walk | CODE_RULE (+ LLM inside) |
| `_ladder_continues` | 1689 | Queues `FILM_CONTINUE` (cause `director_ladder`) under the write lock | Past 3 rounds the film is walked on later, never left idle (:1605-1608) | CODE_RULE |
| `_walk_staircase` | 1707 | Recovers paid-but-unsettled takes (0 credits); then up to 4 times: builds the sheet, stops on missing reference pictures, on scenes held for the Owner, on blocked assembly (TAKES_NOT_ACCEPTED), returns READY when nothing is left; refuses to buy the same stair twice; runs `run_sheet_step(unasked=True)` and classifies its refusal | The Nepal rule: one answered stair at a time (:1414-1425); spec 51 (:1861-1863) | OWNER via CODE_RULE |
| `_held_stair` | 1902 | The stair that holds scenes for the Owner (the test shot also guards motion) | The motion starts only after the hero (:1907-1909) | CODE_RULE |
| `_film_moved` / `_passed_over` | 1992 / 2003 | Whether the day moved the film (bought, asked, ready, assembled, or an account-wide wait) / a film stopped for its own reason | Only one factual film a day, but a stuck film never blocks the next | CODE_RULE |
| `_assemble_from_takes` | 2602 | Asks the mode about the narration (T3 above 5 USD) with the sheet's plan_hash and the `assemble` step, holds the narration estimate, assembles from takes, books costs, settles or releases | Only the narration is paid at assembly; one yes per plan (:2615-2621) | OWNER (mode) via CODE_RULE |
| `_media_staircase` | 2738 | Walks pending films; one factual film a day; passes over stuck ones; lists bought stairs (incl. hero accepted by clip QC); prices the film from its sheet; assembles READY films under the lease; records each factual film's day; collects questions, waits and holds; writes a sheet letter per film and the waiting-approvals letter once; COMPLETED only if something was assembled or bought | AR-02, REL-11: never one film standing in front of the others (:2754-2760) | CODE_RULE |

#### The day never stalls: film state, retirement, letters

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `paid_rule_words` | 2009 | The Owner's paid-media rule in Romanian (OVER_USD, MODE, EVERY_PAID_STEP) | Same words as the page (`paidMediaRuleWords`) | CODE_RULE |
| `_owner_rule` | 2021 | Reads (environment, mode, rule, threshold) from `OwnerPolicy` 1; defaults TEST and MANUAL | Read, never changed (:2022) | OWNER (settings) |
| `_rule_line` | 2033 | The line every staircase letter carries | A15: every letter says the rule, the environment and where they change | CODE_RULE |
| `_production_day_words` | 2042 | What the day would do in PRODUCTION under the rule and mode | For the TEST letter (A3) | CODE_RULE |
| `_test_environment_letter` | 2079 | Once per film: an ESCALATE letter to the Owner saying TEST refused the paid vendors and what PRODUCTION would do; changes nothing | A3 (:2082-2084) | CODE_RULE |
| `_note_film_state` | 2130 | Appends `runbook.film_state` unless identical to the last one; failure logged | The record retirement reads (:1936-1937) | CODE_RULE |
| `_stood_since` | 2173 | First business date the film stood still since it last moved or a take changed | Anything that happens to the film restarts the count | CODE_RULE |
| `retire_stale_films` | 2204 | Retires unrendered factual films standing ≥ `film_wait_days`, unless an Approval about them is PENDING | A4: a stuck film must free its topic (:2207-2214) | CODE_RULE |
| `film_spent_micros` | 2250 | `film_spend_micros`, 0 on error | The figure a closed film's event and letter carry | CODE_RULE |
| `bought_takes_of` | 2261 | Count of takes by kind in `BOUGHT_TAKE_STATUSES` | What a closed film's letter lists | CODE_RULE |
| `close_film_books` | 2278 | In the caller's transaction: sets the storyboard REJECTED and appends `runbook.film_retired` with the bought takes, spend and `retired_by` | Shared by the Director's retirement, the Owner's «Închide filmul» (media/film_close.py:587), `director_qc.close_film` (:1765) and `sheet_story_repair` (:63) | CODE_RULE |
| `_retire_film` | 2323 | Re-checks status, closes the books with `retired_by="Director"`, posts the "Film retras" ESCALATE letter | The Director's retirement with a letter (A4) | CODE_RULE |
| `_sheet_letter` | 2399 | The Owner's deterministic letter about one stopped film: headline by refusal, the rule line, the step's price and cap, the film's estimate and cap, the Runway balance, each scene's price line, the sheet URL; a budget card when the film cannot fit a day's budget; deduplicated; older letters retired | "Deterministic: the sheet's own facts, never a model's account of them" (:2410-2411) | CODE_RULE |
| `_letter_headline` | 2561 | Headline and follow-up sentence per status/refusal | A15: a question is a question, a hero is a look, a balance a top-up (:2454-2455) | CODE_RULE |

Helpers: `_owner_letter_exists` (:2071) scans the Owner's letters for a kind and key;
`_film_figures` (:2394) shapes the sheet's money for `estimate_film_cost_micros`.

#### Edit and QC, the Director's decision, repairs

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_edit_and_qc` | 3689 | Measures up to 5 unmeasured video files (or only `asset_ids`), skipping a repair's intermediate films; after each measurement deletes the film's intermediate shot files on disk (`release_after_qc`, :3765; media/assembler.py:12711); for a failure asks Kael's diagnosis, then `director_decides_failed_film`; collects passed assets (including ones she accepted or repaired) | "Quality control is measured, never opined" (:3699); nothing redone before she reads (:3703-3704) | CODE_RULE (+ LLM via callees) |
| `_round_windows` | 3912 | Per scene, paid redo rounds sorted by start, each with the next round's start | 1c038a99: empty rounds counted as delivered (:3920-3926) | CODE_RULE |
| `_round_delivered` | 3890 | Whether a still or shot of the scene came (or may come) within the window | Count rounds by pictures made | CODE_RULE |
| `_paid_redo_rounds` | 3951 | Rounds per scene that delivered something; a motion continuing its still is the same round | babcf272: empty rounds spent the film's redos (:3958-3961) | CODE_RULE |
| `_open_still_rounds` | 3977 | Per scene, the round whose new still was bought and whose motion may still follow | So a later-approved still can still be animated | CODE_RULE |
| `director_decides_failed_film` | 4041 | Up to 4 rounds: `_director_round`; a fault → `wait_for_director`; ACCEPTED → passed asset; REPAIRED and requalified PASSED → passed; FAILED → yield to queued films or read the new report; NOTHING_DONE → read once more | 2026-10-10 babcf272: the Director decides, never a mechanical repair (:4053-4062) | LLM_CHECKED_BY_CODE |
| `_yield_next_round` | 4155 | If another film's FILM_CONTINUE is queued, queues this film's next round as a continuation keyed like the watchdog's pass | 2026-10-12: rounds held the worker an hour while the serial waited (:4133-4134) | CODE_RULE |
| `_redo_allowance` | 4201 | {per_scene, per_film, spent, open_motion} and whether the free fix was used | What she is told before deciding | CONFIG + CODE_RULE |
| `_director_round` | 4221 | Reads `decision_state`; if a REPAIR waits on her look at refused candidates, `_director_looks` first, then `_director_reads` | A decided report is not read again (:4233-4241) | CODE_RULE |
| `_director_reads` | 4272 | A final decision stands, or a pending one whose wait ended is carried on (`resumed`); otherwise builds `film_qc_context` with limits and asks `review_film_qc`; records lessons; marks takes already bought for her listed scenes | Her decision, nothing re-bought (:4347-4350) | LLM_CHECKED_BY_CODE |
| `_director_looks` | 4370 | Shows her each scene's refused candidates (frames in a temp dir), records her pick or rejection and a STATUS letter to the Owner | The Owner, 2026-10-10: «El ar trebui să hotărască dacă poza este bună sau nu» (:4379-4380) | LLM |
| `_carry_out` | 4442 | ACCEPT (refused when a verdict is not hers), CLOSE (branch unreachable, see Oddities), or REPAIR via `_director_repairs`; outcome REPAIRED/ASKED/BOUGHT_WAITING/NOTHING_DONE; records the decision; letter and inbox settled for final outcomes, else she waits | 2026-10-10 review: a bought still was recorded "nothing could be done" (:4454-4457) | CODE_RULE (executes an LLM decision) |
| `_director_repairs` | 4594 | Only for a film assembled from takes: filters her list (`repair_list`), applies it (`_apply_repairs`), records `runbook.qc_repair` when something was applied, bought or made | Only what she listed; never a take the Owner approved (:4605-4611) | CODE_RULE |
| `_still_newer_than_film` | 4743 | Whether the scene's approved still is newer than the clip in the failed film (by time) | 2026-10-12: 269 credits re-bought for two scenes; a "new" still that was already in the film (:4747-4758) | CODE_RULE |
| `_correct_before_redo` | 4791 | Has the scene's prompt rewritten before its paid redo; an unchanged motion escalates to the still (unless a newer still exists); returns a PROMPT_NOT_CORRECTED refusal when nothing was rewritten | «Nu reface pur și simplu imaginea, trebuie verificat promptul și corectat!» (scene_rewrite.py:3004) | LLM_CHECKED_BY_CODE |
| `_apply_repairs` | 4868 | Free fixes once (encode, card; audio last); paid redos per scene within limits (+ the Owner's card allowance), after a corrected prompt, priced with the Owner's sheet overrides, refused if they retire a final approval, bought by `redo_scene(unasked=True, director_repair=True)`; records `runbook.qc_paid_redo`; raises the redo-cap card; rejoins the film from approved takes; lists what waits; re-measures the new film once | babcf272 and the cyclotron incidents (:4885-4890, :5084-5087) | CODE_RULE |
| `_reencode_from_takes` | 5283 | Builds the sheet, prices, and `_assemble_from_takes` (narration reused) as a free fix or a rejoin | Free repair at 0 image/shot credits | CODE_RULE |
| `_repair_lines` | 5351 | The repair in the Owner's words, line by line | Her letter lists what was done and why not | CODE_RULE |
| `_decisions_words` | 4704 | One sentence tallying her outcomes | Stage reason | CODE_RULE |

Helpers: `_repair_intermediates` (:3850) and `_repaired_assets` (:3864) read `runbook.qc_repair`;
`_round_began` (:3875); `_repair_summary` (:4023); `_decision_summary` (:4700); `_film_of`
(:4193) finds a file's storyboard.

#### Film continuation (FILM_CONTINUE)

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `continue_film` | 5430 | Stop, safe mode, PRODUCTION, the mode (media T2, `ask_owner=False`); a rendered film → `_continue_rendered`; else APPROVED + story gate → `_media_staircase([film])` → QC → publish; every outcome recorded as `runbook.film_continued` | ADR-FILM-CONTINUE: the Owner's yes continues the film the same day (:5416-5425) | CODE_RULE |
| `_continue_rendered` | 5571 | Measure if unmeasured; failed → the Director decides; passed → publish | A report never decided is read now (babcf272's d4ea68d2) (:5605-5606) | CODE_RULE |
| `_publish_passed` | 5629 | Mode check for publish (T3, `ask_owner=False`), then `_publish(only_assets=passed)` | A continuation publishes its own film and no other | CODE_RULE |

#### Publish

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_publish` | 5991 | Needs a slot and a bound account; offers QC-PASSED files not live/settling/rejected, newest render per film; routes each film to its storyboard's channel; one film per channel per run; skips films the channel already carries; reports | PUB-02; routing by storyboard not by first slot (:6011-6017) | CODE_RULE |
| `_publish_one` | 5670 | Account → the Director's viewing → visibility (private if the licence is unproven) → publishing gate → Publisher's HOLD/metadata (computed refusals) → the mode → upload → licence hold mark → Publisher memory | Six questions, each in its own place; the mode last so the Owner is asked about a ready film (:5829-5835) | CODE_RULE + LLM + OWNER + EXTERNAL |
| `_film_rights` | 5958 | `rights_verdict` from the asset's licence status and the render manifest | Same reading as the gate's rights check | CODE_RULE |
| `_private_until_licensed` | 5972 | Forces private, no schedule, with the reason | 2026-10-10 review: refused every run, never uploaded (:5750-5754) | CODE_RULE |

#### Serial and post-run

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_serial_queue` | 6176 | `run_serial_stage` | The serial ended as text before (:6181-6184) | CODE_RULE here; the decisions are delegated to `app.story.serial_stage` (group story) |
| `_serial_next` | 6191 | `run_serial_next_stage` | Tomorrow's script, never storyboarded | CODE_RULE here; delegated to `app.story.serial_stage` (group story) |
| `archive_stale_reports` | 6208 | Resolves Director-inbox STATUS messages older than 3 days | Seventy-five old reports buried letters needing an answer (:6203-6204) | CODE_RULE |
| `_post_run` | 6230 | Accountant's close (if a model) → file every stage's report → no model: SKIPPED → archive → `director_review` up to 3 passes; failure → letter to the Owner | runbook §10/§11 (:6235-6236) | CODE_RULE (+ LLM) |

**Data read/written by `stages.py`.**

- Reads: `TopicIdea`, `SourceSnapshot`, `FactualClaim`, `ScriptDraft`, `Storyboard`,
  `VideoRenderJob`, `QualityControlReport`, `MediaAsset`, `EditorialReview`, `PublicationRecord`,
  `ChannelRecord`, `StoryEpisode`, `DailyStudioLog`, `SceneTake`, `AgentMessage`, `DomainEvent`,
  `TaskQueueItem`, `OwnerPolicy`.
- Writes directly: `Storyboard.status = "REJECTED"` (:2299); STATUS messages in the Director's
  inbox resolved by `archive_stale_reports` (:6219); a publication marked held for its licence
  (`mark_held_for_licence`, :5902); `DomainEvent` rows
  `runbook.film_state` (:2166), `runbook.film_retired` (:2300), `runbook.shot_plan_reasked`
  (:1267), `runbook.qc_repair` (:4686), `runbook.qc_paid_redo` (:5152), `runbook.film_continued`
  (:5459); `AgentMessage` letters to the Owner (`owner_test_environment` :2108,
  `owner_film_retired` :2372, `owner_shooting_sheet` :2514); `TaskQueueItem` FILM_CONTINUE via
  `queue_film_continue` (:1696, :4182); Publisher memory (:5907). Everything else is written by
  the called services (reservations, cost rows, approvals, reviews, takes, publications).
- Files: a temporary directory for her look's frames (:4414); media files through the
  assembler (out of scope).

**External calls (through other modules).** YouTube analytics (:420-429) and upload (:5878);
page fetches from authorised sites (:527, :564); the trends feed (`refresh_trends`, :359); Runway/RunPod paid
stills, test shots, motion and redos (:1847, :5036); TTS narration (:2673, :3396); vendor credit
balances (:3374, :3585); language models (see LLM involvement).

## Connections

**Who calls into this part.**

- `app.main` builds the runners at startup (backend/app/main.py:63, :700); `app.demo` too
  (demo.py:498) and patches `selected_youtube`, `analytics_provider_for_channel`, `sheet_wiring`
  for the demo (demo.py:46-50, :147-151).
- `app.runbook.services.execute_daily_run` calls the runners in `STAGES` order
  (runbook/services.py:76-90).
- `app.workflows.worker` runs `continue_film` for FILM_CONTINUE tasks, re-queuing FILM_BUSY up to
  3 times every 600 s (workflows/worker.py:326-364) and uses `sheet_wiring` (:485).
- `app.media.film_close` uses `close_film_books`, `bought_takes_of`, `film_spent_micros`,
  `topics_in_production`, `is_serial_storyboard`, `TAKE_WORDS`, `_usd_words` and the letter kinds
  (media/film_close.py:172-654); `app.media.director_qc.close_film` uses `close_film_books`,
  `film_spent_micros` (media/director_qc.py:1765); `app.media.sheet_story_repair` uses
  `close_film_books`, `film_spent_micros`, `_director_approves` (:63, :240).
- `app.decisions.producers.redo_cap` uses `_paid_redo_rounds` (:391); `app.media.sheet_words`
  uses `STAGE_ACTIONS`, `paid_rule_words` (:326, :332); `app.goal` uses `LADDER_REFUSALS`,
  `OWNER_DECIDES` (goal.py:159); watchdog passes `ladder_retry`, `owner_choice_continuation`,
  `serial_unfilmed` use `LADDER_REFUSALS`/`OWNER_DECIDES`; `workflows.passes.director_qc_review`
  is the watchdog counterpart of `director_decides_failed_film`.

**What it calls out to.** `app.services` (`may_act`, `pending_approvals`,
`queue_film_continue`, `studio_environment`, `append_event`), `app.runbook.services` (stop, safe
mode, `BLOCKED`), `app.economy` (budget holds, cost booking, the Accountant's letters and close),
`app.research`, `app.factual`, `app.agents` (director, reviews, editorial, memory, messages),
`app.media` (shooting sheet, assembler, factory, prompt agent, QC, director_qc, scene_rewrite,
answered_letters, blocker_repair), `app.decisions` (film budget card, redo-cap card),
`app.publishing`, `app.integrations`, `app.analytics`, `app.story`, `app.wording`.

**Events emitted.** `runbook.film_state`, `runbook.film_retired`, `runbook.shot_plan_reasked`,
`runbook.qc_repair`, `runbook.qc_paid_redo`, `runbook.film_continued` (constants :1938-1942,
:3838-3840, :5427). **Consumed.** `runbook.film_state` (`_stood_since`, `_reask_shot_plans`;
also read by goal.py:33, media/answered_letters.py:56); `runbook.shot_plan_reasked`;
`runbook.qc_repair` (`_repair_intermediates`, `_repaired_assets`); `runbook.qc_paid_redo`
(`_round_windows`, `_open_still_rounds`); `runbook.film_continued` is read by
publishing/licence_release.py:82 and workflows/passes/serial_unfilmed.py:52.

## Owner touchpoints

- **Autonomy mode** gates every stage (:6360-6372) and, per film, the TEST render (:3327-3347),
  the narration (:2641-2652), the upload (:5845-5875), page fetching (:559), the continuation
  (:5493-5496) and a continuation's publication (`_publish_passed`, :5640-5643). Under SUPERVISED the per-film calls write an Approval the Owner answers (subject =
  storyboard or asset).
- **Paid-media rule** (`paid_media_approval`: EVERY_PAID_STEP, OVER_USD x, MODE) is applied inside
  `run_sheet_step` and `redo_scene` for every stair and redo (:1863, :5057); quoted in every
  staircase letter (:2033-2039).
- **Environment** (TEST/PRODUCTION) picks the path (:3189, :3231) and blocks continuations outside
  PRODUCTION (:5485-5492); the TEST letter says where to change it (:1971-1974, :2079).
- **Stop switch**: read before each film (:2805, :3274), after a walk (:2871), inside the ladder
  loop (:1564) and at the start of a continuation (:5476); **safe mode** is read here only at the
  start of a continuation (:5478-5484) — the daily run's own stop and safe-mode handling live in
  `app.runbook.services`.
- **Letters to the Owner**: ESCALATE letters written here — the shooting-sheet letter (:2399),
  the TEST-environment letter (:2079), the film-retired letter (:2323); written through other
  modules — the waiting-approvals letter (:2996, :3620), the budget-refusal letter (:2668,
  :3356), the Director's QC decision letter and look letter, both STATUS letters, never a
  question (:4576, :4435; media/director_qc.py:49), and «Nu am putut revizui ziua» (:6285).
- **Decision cards**: the film budget card (`decisions.sources.film_budget`, :2427, withdrawn on
  assembly :2922); the redo-cap card «mai cumpăr, public așa cum e, sau închid» (:5177, :5379-5382).
- **Answers that continue a film**: an APPROVED paid step or take queues FILM_CONTINUE
  (`continue_film`, :5430).
- **The Owner's marks honoured**: an approval marked final is never retired by a repair
  (:5027-5034); a non-final approval may be replaced and the Owner is told (:5116-5133,
  :5384-5393); a scene's LOCAL_MOVE and model choice on the sheet are honoured (:4984, :4651).
- **«Închide filmul»** (FILM_CLOSED) ends letters and buying for that film (:2417-2421,
  :2811-2817; the purchase lease refuses a closed film, :1592-1602, :2899-2904). **«Oprește GPU
  acum»** (OWNER_HOLD) is a studio-wide GPU hold enforced by the GPU session's precheck
  (providers/runpod/gpu_session.py:767-808); here it only suppresses the per-film letter
  (:2436-2439), and the walk treats the film as HELD (see Oddities).
- **Settings the Owner may change**: `film_wait_days`, `film_max_paid_redos(_per_scene)`,
  `paid_generation_approval_threshold_usd`, `motion_budget_usd`, `film_budget_usd`,
  `editorial_rounds`, `research_candidates_per_day`, `research_pages_per_topic`, daily budgets,
  channel visibility policy.
- **A script approved by hand** in the interface is reviewed by the story review before
  storyboarding (:1085-1104); a script only the Owner can move is announced (:1174-1175).

## Oddities and gaps

1. **CLOSE is unreachable from the Director's QC decision.** `decision_schema` refuses CLOSE for
   every answer (backend/app/agents/reviews.py:865-871, the Owner's rule of 2026-10-11), yet
   `_carry_out` keeps a CLOSE branch (stages.py:4480-4482), and the docstrings of `_edit_and_qc`
   (:3702-3703) and `director_decides_failed_film` (:4060-4061, :4064-4065) still describe CLOSE
   as one of her decisions. A resumed decision cannot be CLOSE either: only ASKED/BOUGHT_WAITING
   are pending (media/director_qc.py:121).
2. **Dead constants.** `QC_LETTER_KIND` (:3843) and `FREE_FIX_ORDER` (:3846) are referenced
   nowhere in the backend. `FREE_FIX_ORDER`'s comment says "the sound last" but the tuple has no
   `audio`; the real order is in `_apply_repairs` (encode :4949, card :4953, audio :5244).
3. **Redo limit fallbacks disagree with the settings.** `getattr(settings,
   "film_max_paid_redos_per_scene", 1)` and `getattr(settings, "film_max_paid_redos", 2)`
   (:4213-4214, :4967-4968) versus defaults 5 and 20 (config.py:314-315). The fallbacks apply only
   when `settings` is None (`_redo_allowance` accepts None). `_paid_redo_rounds`' docstring still
   speaks of "the film's two paid redos" (:3960-3961), the 2026-10-02 default
   (ADR-AUTOMATIC-REDOS, 16_DECISION_LOG.md:4112) superseded on 2026-10-11
   (16_DECISION_LOG.md:126).
4. **Misplaced comment.** The `BATCH` comment ("How many items one stage will process in a single
   run", :206-208) sits above `MAX_SCRIPT_EXCHANGES` (:209-211), and `BATCH` (:213) follows
   without it.
5. **Every verification fault counts as a refused verdict.** `_research_and_verification` catches
   `Exception` around `agent_verify_claim` (:624) and reports it as «verdict respins»; a provider
   outage reads like a content refusal in the stage reason.
6. **"Model available" means "any provider registered".** `_has_language_model` (:326) does not
   check that the specific agent has a working model; the callers rely on exceptions for that.
7. **Gate numbering is inconsistent.** The module docstring speaks of a "five-point gate … plus a
   sixth" (:22-24), `_publish`'s docstring of "the five gates" (:6007-6008), and `_publish_one`'s
   comment of the rights check as "Gate 7" (:5752).
8. **Hard-coded Director name.** The post-run failure letter is signed «— Sarah» (:6290), while
   other letters take the Director from `agent_for_role`.
9. **A day that only asked the Owner is SKIPPED.** `_media_staircase` returns COMPLETED only when
   something was assembled or a stair bought (:3022); a day that raised questions or found films
   waiting reports SKIPPED with the reason.
10. **TEST path: the narration review comes after the money is held.** `review_narration` runs
    after `reserve_spend` (:3348 then :3364-3371) and never blocks the render (by design,
    :3069-3072).
11. **Wasted query.** `_edit_and_qc` builds the BATCH-limited `pending` list (:3720-3728) and
    discards it whenever `asset_ids` is given (:3729-3735).
12. **Forward references.** `_reask_shot_plans` (:1192) uses `BOUGHT_TAKE_STATUSES`,
    `SHOT_PLAN_REASKED_EVENT` and `SHOT_PLAN_REASK_DAYS`, defined ~750 lines later (:1942-1961);
    it works because they are read at call time.
13. **Name shadowing.** `_selection`'s dict comprehension uses `count` as the loop variable
    (:787-788), shadowing the imported `app.wording.count` inside the comprehension only.
14. **The narration is outside the Owner's EVERY_PAID_STEP rule.** `_assemble_from_takes` asks
    `media.paid_generation[_over_threshold]` (:2641-2652), not a paid-media step; under
    AUTONOMOUS_CEO a narration is voiced unasked. Recorded as a known gap awaiting the Owner's
    decision (16_DECISION_LOG.md:4082, 2026-10-01 "the assemble step's narration is gated through
    may_act"). The mode question here uses the default `ask_owner=True`, so under SUPERVISED it
    writes the Approval and the film returns ASKED (:2653-2658).
15. **One topic's script per run.** `script_work(...)[:1]` (:1003): a second SELECTED topic owing
    a script waits for the next run.
16. **Linear scans of the Owner's inbox.** `_owner_letter_exists` (:2071-2076) and `_sheet_letter`
    (:2505-2512) iterate every message addressed to the Owner in Python to deduplicate.
17. **Silent fallbacks in the ladder.** `_quality_scenes` returns [] on any error (:1627-1634);
    then `_sheet_letter`'s rule that QC-refused scenes are the Director's (:2440-2445) does not
    apply and an Owner letter is written for them.
18. **Caller list mutated.** `_media_staircase` appends to the `held` list it is given (:2991),
    which belongs to `_media_films` (:3152).
19. **`models.py` is not used by `stages.py`.** Both tables are written only by
    `app.runbook.services` (:674, :953, :1855).
20. **"Twelve stages" is stale.** The module docstring (stages.py:3) and main.py:698 say the run
    walks twelve stages; `STAGES` has thirteen (runbook/services.py:76-90, `serial_next` last),
    eleven of which have a runner here (`preflight` and `daily_log` have none, :254-255).
21. **The decision-log entries behind this module's money paths record tests on fakes only**
    (16_DECISION_LOG.md:127 "Tested on fakes only … Not yet proven on a real vendor" for the
    Director's prompt ladder; 16_DECISION_LOG.md:4096 "None of them was tested against a real paid
    vendor" for the production-readiness audit's decisions, retirement and continuation included).
22. **The whole-film path's non-TEST arms are unreachable.** The environment is `TEST` or
    `PRODUCTION` only (`EnvironmentCommand.environment: Literal["TEST", "PRODUCTION"]`,
    backend/app/schemas.py:36), and PRODUCTION returns to the staircase at :3231, so in
    `_media_films` `min(settings.motion_budget_usd, left_usd)`, `settings.motion_scenes_max`, the
    `None` per-second cap and `motion_from_prompt=False` (:3439-3465) never apply, and `left_usd`
    (`_budget_left_usd`, :3306) is computed with a long comment about it (:3301-3305) but never used.
23. **The Owner's GPU hold is not an Owner wait for the walk.** `OWNER_HOLD` is in neither
    `OWNER_DECIDES` (:1441-1464) nor `ACCOUNT_WIDE` (:1949-1959). A stair refused OWNER_HOLD is
    HELD (:1866-1872), the film is passed over (`_passed_over`, :2003-2006) and the next film meets
    the same studio-wide hold; each day is recorded as not moved (:2955-2964), so a GPU hold
    standing for `film_wait_days` can let `retire_stale_films` retire those factual films unless an
    Approval about them is PENDING (:2219, :2231). `retire_stale_films`' docstring promises that a
    film waiting on the Owner's money or budget is never retired (:2212-2213); the GPU hold is not
    covered. (The status reaches this module — the motion step's GPU precheck raises it,
    media/assembler.py:11409-11423 — and `_sheet_letter` names it at :2436.)
24. **A mixed stop sends no letter at all.** `_sheet_letter` returns None as soon as any of the
    held scenes is QC-refused (:2440-2445), although `_held_words` says the other scenes "wait for
    the Owner's decision on the sheet" (:1651-1657); those scenes reach the Owner only through the
    film's reason in the stage line.
25. **"Failed today" is a UTC date.** `_gather_for_candidates` compares ESCALATE letters with
    `utc_now()[:10]` (:497-502), while the rest of the day uses the local business date
    (`business_date(settings.timezone)`, e.g. :2215, :3132): between midnight Bucharest and
    midnight UTC a topic that failed "yesterday" is still skipped.
26. **`layer_exhausted` is not read before a paid redo.** Since a50407e `scene_rewrite.rewrite_for_redo`
    can return `layer_exhausted` (her review found the findings in words the motion layer keeps, or
    the Video Editor's second rewrite gave the stored or refused words again; media/scene_rewrite.py:2077-2113)
    without `same_prompt`, and its docstrings say the caller, `runbook.stages`, then turns to the
    still as on `same_prompt` (media/scene_rewrite.py:3004-3006, :2131-2134). `_correct_before_redo`
    escalates to the still only on `same_prompt` (stages.py:4820), so a motion redo whose rewrite comes back
    `layer_exhausted` ends as PROMPT_NOT_CORRECTED and nothing is bought (stages.py:4854-4865); the turn to
    the still happens only on the ladder's own path (`rewrite_failed_scene`,
    media/scene_rewrite.py:2923-2935).
27. **Her film-QC repair is bought without a second look.** `second_look`'s docstring names "her
    own film repair" among the purchases her look precedes (media/second_look.py:13-16), and the
    kind `film_scene` exists for it (media/second_look.py:71), but no backend caller uses that kind:
    the only callers are `stills_stage._director_looks` (still) and `fix_check.shot_second_look`
    (shot) (media/fix_check.py:642-754). The paid redo `_apply_repairs` buys for her REPAIR
    (stages.py:5036-5061) is therefore not looked at again; only a still re-roll or clip retry inside that
    redo is.
