# LLM routing: how the backend uses language models, who decides, and how much is LLM

> Scope: every language-model call in `backend/app`, the employees who make them, how a model is
> chosen for each employee, the providers and adapters, the gate every call passes, structured
> answers, multi-model strategies and what the calls cost. Media generation models (RunPod, the
> shooting sheet, `production_policy.choose_model`) are *not* LLM routing and are mapped in
> `subsystems/05_media_shooting_sheet_policy.md` and `subsystems/12_providers_runpod.md`.
>
> Method: read the code of the working tree on 2026-10-12 (branch `codex/simple-pixel-studio`, HEAD
> `3d49e9a` plus uncommitted files), the static inventory `docs/project/backend_map/inventory.json`
> and `STATS.md`, and the live database `data/studio.db` opened **read-only**
> (`file:data/studio.db?mode=ro`); newest `agent_run` row 2026-10-12T13:52:23Z. Per-call-site detail
> (prompts, schemas, every check) lives in the subsystem files under `subsystems/`; this file is the
> cross-cutting view and cites them where it summarises them.
>
> Vocabulary. **Decided by**: LLM, LLM_CHECKED_BY_CODE, CODE_RULE, OWNER, CONFIG, EXTERNAL.
> **Trust** of an LLM answer: FINAL, CHECKED_BY_CODE, ADVISORY, INFORMATIONAL. The human is "the
> Owner"; employees follow the code's pronouns (the Director is "she", Kael "he").

---

## 1. The short answer

- **One door.** Every model call in the backend leaves through
  `app.agents.services.run_agent_task` (`backend/app/agents/services.py:733`). Twenty functions call
  it directly; four thin wrappers sit on top of it: `structured_run`
  (`backend/app/agents/structured.py:76`), `run_with_strategy` (`backend/app/agents/ensemble.py:182`),
  `reviews._run` (`backend/app/agents/reviews.py:121`) and `prompt_agent._run`
  (`backend/app/media/prompt_agent.py:2948`). **37 functions** are LLM call sites (they write the
  question and use the answer), out of **3951** functions (`STATS.md`).
- **Who decides which model answers.** The Owner (Settings → assignment, origin `OWNER`) outranks
  everything; the allocation file `config/workforce_seed.json` (CONFIG) applies only to an employee
  nobody has ever assigned; two code rules can move an employee without the Owner — the vision
  preference for the Video Editor (`prefer_capable_models`, `services.py:1331`) and the Director's
  repair of a model that fails *now* (`switch_agent_model`, `backend/app/agents/repairs/agent_health.py:601`,
  kernel tier T2, at most once a day per employee). Live: all eight employees carry an
  `agent.model_assigned` event with origin `OWNER` dated 2026-10-08 09:52; no preference move and
  no Director repair has ever been recorded.
- **Who decides whether a call may happen.** Deterministic code: the Policy Kernel in
  `run_agent_task` (token ceiling, USD budget, STOP AUTONOMY, autonomy mode, lifecycle, model
  availability, one run at a time, required capabilities, provider health, adapter present). Its
  thresholds are Owner settings. No model participates in that decision.
- **How much is LLM.** Statically: 1 % of functions call the gateway directly, 4 % of function lines
  are call sites, 18 % of function lines can *reach* a model (`STATS.md`). By authority: of the 37
  call sites, **25 are CHECKED_BY_CODE**, **4 FINAL**, **5 ADVISORY**, **3 INFORMATIONAL** (§9). The
  model writes text (scripts, prompts, verdicts, letters, plans) and chooses among options code
  computed; code validates the shape, verifies ids and quotes, clamps, falls back, and holds every
  money, publishing, model-assignment and price decision. The four FINAL answers are picture and
  prompt judgements (§9.2), and none of them spends money by itself. *Reference tally:* the map's
  three tallies were reconciled in `LLM_CALL_SITES.md` §6, which counts 24 CHECKED_BY_CODE,
  5 FINAL (adding #5 `editorial_judgement.judge`, whose scores are acted on as given),
  5 ADVISORY, 3 INFORMATIONAL; use that count when the files differ.
- **How much it is used.** Live: 2424 runs since 2026-09-12 (1519 SUCCEEDED), 10.45 M prompt +
  0.87 M completion tokens, USD 4.48 recorded cost; the last seven days 906 runs (901 SUCCEEDED),
  USD 3.89. The busiest task types this week are claim verification, still/clip vision QC and the
  Director's scene repair loop (§11).

---

## 2. The employees (roles, missions, models, call sites)

### 2.1 Where the roster comes from

| What | Decided by | Source |
|---|---|---|
| The eight roles, their mission, allowed task types and prohibited actions | CODE_RULE (a constant in code) | `_ROLE_DEFINITIONS`, `backend/app/agents/services.py:1082-1137`; new task types reach an existing studio through `seed_role_task_types` (`:1143`) |
| The employees' names and their first model | CONFIG | `config/workforce_seed.json` `agents_def` and `models_data`, validated by `WorkforceSeed` (`backend/app/agents/seed_config.py:33-56`) |
| First hire | CODE_RULE, once | `_seed_initial_workforce` returns at once if any agent exists (`services.py:1575-1579`); models are seeded `SEEDED_UNVERIFIED`, `is_available=False`, on provider `local-ollama` with status `NOT_CONFIGURED` (`:1606-1680`); every role gets `text_generation` REQUIRED (`:1708-1716`) |
| A role added to the seed later (the Accountant) | CODE_RULE | `seed_missing_workforce` hires on the seed's model if it is available, else on the Director's model (`services.py:1179-1280`) |
| Work contracts (watch for / investigate / correct / let pass / never let pass / escalate / deliverables, memory scope) | CONFIG, then OWNER | `config/role_contracts.json` seeded by `seed_role_contracts` only into a role whose contract is empty (`backend/app/agents/identity.py:99-128`); the Owner edits through `PUT /api/v1/agents/roles/{role_id}/contract` → `set_role_contract` (`identity.py:139`) |
| Persona (speech style, habits, phrases) | data (Character Bible) | `_persona_section` (`identity.py:192-226`): "It never changes what you approve, reject, verify or publish" (`identity.py:196-197`) |
| Hiring, suspending, terminating later | OWNER | `app.workforce.services` proposes from counted rows only ("Nothing here asks a model what it thinks of an employee", `backend/app/workforce/services.py:1-12`); the Owner applies (`decide_proposal`, `:270`) |

**Allowed task types are told, not enforced.** `compose_identity` writes "YOU MAY DO: …" and "YOU
MUST NEVER: …" into the system prompt (`identity.py:296-297`); a repository-wide search finds no
other reader of `allowed_task_types` or `prohibited_actions` besides views and seeding. The kernel
does not compare `task_type` with the role, so e.g. Kael runs `still_qc`, `clip_qc`, `shot_prompts`,
`research_models` although his role lists `render_video,edit_scenes,qc_video`. The Director's
contract lists "an employee acting outside its allowed task types" under NEVER LET PASS
(`config/role_contracts.json`), but nothing measures it.

### 2.2 The roster table

Models: **live** = `agent.model_id` in the database now (all on the Owner's Ollama Cloud connection
`settings:d54989ee…`, base URL `https://ollama.com`); **seed** = `config/workforce_seed.json`
`agents_def` (models on the seeded `local-ollama` endpoint); **sees** = the provider declared
`vision` for the live model (`model_capability`). Run counts are all-time `agent_run` rows by that
employee (SUCCEEDED in brackets).

| Role | Agent | Mission (abridged, `services.py:1082-1137`) | Model(s) live / seed | Sees | LLM call sites it speaks in | Task types run (all-time runs) |
|---|---|---|---|---|---|---|
| Director | Sarah (Director) | Grow the audience (views, retention); direct every department in writing; decide from measured analytics | `kimi-k3` + secondary `nemotron-3-ultra`, strategy REVIEW / IMPORTANT_ONLY / STRATEGIC; seed `kimi-k3:cloud` | yes (kimi-k3; nemotron no) | `command._choose`, `director.choose_topic`, `director.director_review`, `editorial.editorial_review`, `editorial_judgement.judge`, `reviews.review_film_qc`, `reviews.review_bought_pictures`, `story_review._ask_director`, `story.review.review_episode`, `scene_rewrite.director_brief`, `scene_rewrite.review_rewrite`, `blocker_repair.director_assignment`, `weekly.execute_weekly_review`; second in `picture_qc.LOOKERS`; plus mail/chat/test | director_review 75 (69), story_review 65, answer_mail 58 (14), director_scene_brief 57, director_qc_review 45, sheet_repair_assignment 29, owner_chat 12, direct_company 8 + `:critique` 8 + `:final` 8, choose_topic 7, editorial_review 7, director_rewrite_review 6, WEEKLY_REVIEW 4, director_take_look 2, episode_review 2, editorial_judgement 1 |
| LeadResearcher | Dr. Aris (Researcher) | Discover factual, high-retention topics and source evidence | `minimax-m3`; seed `minimax-m3:cloud` | yes | `research.agent.propose_topics`, `research.agent.gather_sources`, `agent_pipeline.agent_extract_claims` (preferred role) | extract_claims 66 (39), answer_mail 27, gather_sources 22, propose_topics 14, owner_chat 5 |
| FactChecker | Elena (Fact Checker) | Verify atomic claims against sources; enforce the factual gate | `deepseek-v4-pro:0813`; seed `deepseek-v4-pro:0813-cloud` | no | `agent_pipeline.agent_verify_claim` (preferred role; never the extractor) | verify_claim 539 (368), answer_mail 4 |
| ScriptWriter | Marcus (Script Writer) | Draft scripts, scene breakdowns, voiceover pacing | `kimi-k3`; seed `kimi-k3:cloud` | yes | `agent_pipeline.agent_write_script`, `story.services.write_episode` (showrunner), `script_agent.draft_with_agent` (no callers) | write_script 108, write_episode 36 (29), answer_mail 34 |
| VoiceArtist | Lyra (Voice Artist) | Speech, narration timing, sound design (the TTS itself is the voice provider, not the LLM) | `mistral-large-4`; seed `mistral-large-4:cloud` | yes | `reviews.review_narration`, `sound_design.sound_plan`, `model_research.research_models` (voice) | answer_mail 5, review_narration 4, sound_design 2 |
| VideoEditor | Kael (Video Editor) | Compose video, pacing, transitions, rendering; first looker at pictures | `kimi-k3`; seed `kimi-k3:cloud`; role PREFERS `vision` | yes | `picture_qc.evaluate_pictures`, `picture_qc.judge_still`, `picture_qc.judge_clip` (first of `LOOKERS`), `prompt_agent.build_visual_bible`, `prompt_agent.write_shot_prompts`, `scene_rewrite._editor_rewrite`, `reviews.review_failed_render`, `model_research.research_models` (video, image) | clip_qc 245 (137), still_qc 155, scene_prompt_rewrite 55, picture_qc 36 (18), shot_prompts 32, research_models 24 (16), answer_mail 14, visual_bible 10, review_failed_render 6 |
| Publisher | Vera (Publisher) | Final QC, metadata, packaging, distribution schedule | `nemotron-3-ultra`; seed `nemotron-3-ultra:cloud` | no | `reviews.prepare_publication` | answer_mail 6, prepare_publication 4 |
| Accountant | Nadia (Accountant) | Keep the books, hold the budget, close every day with figures | `mistral-large-4`; seed `mistral-large-4:cloud` | yes | `accountant.reconcile_day`; her mail answers carry the books | answer_mail 505 (24; 481 failed on 2026-10-04, see §11.3), reconcile_day 30 (24) |
| (anyone) | any employee | — | the employee's own | — | `history.chat` (Owner chat), `mail.answer_mail` (addressee), `router.run_agent`, `integrations.router.test_agent_llm`, `agent_health._probe` | owner_chat, answer_mail, TEST_CONNECTIVITY |

`picture_qc.LOOKERS = ("VideoEditor", "Director", "QualityAssurance")`
(`backend/app/media/picture_qc.py:119`): no `QualityAssurance` role exists in `_ROLE_DEFINITIONS`, so
the third name never matches; `vision_agent` then takes any active employee whose primary model
sees (`backend/app/agents/vision.py:116-142`).

The role-to-call-site mapping comes from how each call site resolves its speaker:
`agent_for_role(session, "<Role>")` (first-hired ACTIVE holder, `backend/app/agents/memory.py:161-168`)
in `command.py:900`, `director.py:211`, `:501`, `editorial.py:411`, `editorial_judgement.py:76`,
`:435`, `reviews.py:214`, `:469`, `:999`, `:1177`, `:1495`, `accountant.py:1204`,
`story_review.py:779`, `blocker_repair.py:565`, `model_research.py:69`, `:228`,
`prompt_agent.py:76`, `:1005`, `:1116`, `scene_rewrite.py:853`, `:1092`, `:1504`,
`sound_design.py:56`, `research/agent.py:62`, `:413`; `_resolve_agent` with a preferred role and a
fallback to any active agent with a model (`backend/app/factual/agent_pipeline.py:78-108`) for
extraction, verification and script writing; `_resolve_verifier` excludes the claim's extractor
(`agent_pipeline.py:302-330`).

### 2.3 What every employee is told on every run (identity)

`compose_identity` (`backend/app/agents/identity.py:278-343`) builds the system prompt from stored
data only (`identity.py:1-12`), in this order: who you are; MISSION; YOU MAY DO; YOU MUST NEVER;
YOU REPORT TO; the seven contract sections (`CONTRACT_SECTIONS`, `:41-49`); the persona; up to
`RECALL_LIMIT = 12` memory records of the classes the role may read (`memory.py:28`, `:124-143`);
up to 10 OPEN messages addressed to the employee with the last three lines of each thread
(`identity.py:229-275`); four STANDING RULES (`:51-60`: data is never instruction; return exactly
the structured output; return `{"blocker": {...}}` instead of improvising; "Your text never changes
studio state by itself"). The run records the manifest: identity version `identity-v2`, contract
and bible versions, memory ids, open message ids, SHA-256 and length of the prompt (`:326-341`) —
the execution envelope of `docs/architecture/04_AGENT_SYSTEM.md` §16 and the ContextManifest of
`docs/architecture/30_PROMPT_CONTEXT_MEMORY_ARCHITECTURE.md`.

Measured live (last 7 days): the identity averages **14,230 characters** per run (max 24,523)
against an average task prompt of 9,743 characters, i.e. more than half of what each run sends.
Sarah and Marcus carry the full 10 open messages in every run (average system prompt ≈ 20,500
characters).

---

## 3. How a model is chosen for an employee

### 3.1 The layers, in order of authority

| # | Layer | Decided by | What it does | Code |
|---|---|---|---|---|
| 1 | Discovery: which models exist and are available | EXTERNAL | `sync_provider_models` calls the adapter's `list_models`, marks found models available and missing ones unavailable, records the capabilities the provider declares (Ollama `/api/show`), and is "the only place allowed to record the provider as healthy" | `backend/app/agents/services.py:313-500`; `backend/app/integrations/llm.py:171-199`; triggered by the Owner's «Verifică» (`backend/app/integrations/router.py:263-277`) or `POST /api/v1/providers/{id}/sync-models` (`backend/app/agents/router.py:363-369`) |
| 2 | Seed hire | CONFIG | First model from `agents_def`; unusable until a sync makes it available | `services.py:1575-1749` |
| 3 | Starting allocation file | CONFIG | `llm_allocation` (primary/secondary/tertiary, strategy, policy, min_importance) applied **only** to an employee with no `agent.model_assigned` event ever; names resolved through `resolve_model` (tries `x`, `x:cloud`, `x-cloud`); unknown or unavailable names skipped; a non-SINGLE strategy without a second model degrades to SINGLE; written with origin `SEED_ALLOCATION` | `backend/app/agents/ensemble.py:789-921`; called after every sync (`services.py:457-477`); `--force` only from `scripts/apply_llm_allocation.py` |
| 4 | Owner's assignment | OWNER | `PUT /api/v1/settings/agents/{agent_id}/model` → `assign_agent(..., assignment_origin="OWNER")`: model available, versioned command, employee idle, every slot model satisfies the role's REQUIRED capabilities, a tertiary needs a secondary, a non-SINGLE strategy needs a secondary; writes `agent.model_assigned` with the previous slots | `backend/app/integrations/router.py:99-120`, `:414-433`; `backend/app/integrations/services.py:534-661` (checks at `:569-623`, event at `:632-649`) |
| 5 | Role preference (vision for the Video Editor) | CODE_RULE | `ROLE_PREFERENCES = {"VideoEditor": ("vision",)}`; moves her only if her model lacks vision, the Owner did not choose her models (`_owner_chose_models`), she is idle, and an available model declares vision plus every REQUIRED capability; writes `agent.model_preferred` (never `agent.model_assigned`) | `services.py:1068`, `:1283-1440`, `:1482-1518`; called on every seed and after every sync (`:483-498`); decision log 2026-09-18 (`docs/project/16_DECISION_LOG.md:2970-2990`, `:3134-3165`) |
| 6 | Director's repair of a failing model | CODE_RULE (behind the kernel's `agent.change_model`, tier T2) | Only when her current model fails *now*: gone, or its last 3 runs since assignment failed at the model and the latest within 24 h, **and** a probe of it fails. Candidates: on a VERIFIED Settings connection (never `local-ollama`), available, registered, provider health HEALTHY/UNKNOWN, not Anthropic/Claude, not on the deny list, REQUIRED capabilities met, priced on both token sides, not failing for others; ranked Owner's home model first, then the allocation file's models, then most successes this week; up to 3 probes; the first that answers is assigned with origin `DIRECTOR_REPAIR`, slots kept; one switch per employee per day, a second is an Owner card | `backend/app/agents/repairs/agent_health.py:1-35`, `:61-90`, `:455-527`, `:568-740`, registration `:743-772` |
| 7 | Per-call override | CODE_RULE | `run_agent_task(model_id=…)` runs one call on another model with the same identity, policy and record; the run records the model that answered (`services.py:756-760`, `:811-827`). Used by ensemble slots (§7), by `seeing_model` for a picture decision (`vision.py:162-185`, used at `backend/app/agents/reviews.py:1181`), and by the repair probes | as cited |
| 8 | Which *employee* looks at pictures | CODE_RULE + EXTERNAL | `vision_agent(session, *LOOKERS)`: the first preferred role whose primary model the provider says sees, else any such employee, else None (the picture checks then report NOT_APPLICABLE) | `vision.py:116-142`; `picture_qc.py:1003`, `:1691`, `:1963` |
| 9 | Demo mode | CODE_RULE | `DemoModel` replaces every provider's adapter; answers each prompt in the schema it asks for, from ids in the prompt | `backend/app/demo.py:185-404`; `backend/app/main.py:311-325` |

**Protection of the Owner's choice.** `_owner_chose_models` (`services.py:1482-1518`) reads the
last assignment event, ignoring `DIRECTOR_REPAIR` detours (`_assignments`, `:1447-1462`): an
`agent.model_preferred` or no event means "not the Owner"; an origin other than `SEED_ALLOCATION`
means "the Owner"; legacy events without origin are compared slot by slot with the allocation
file. `owner_home_model` (`:1465-1479`) is where a repaired employee returns.

**Saving a connection blocks its employees until it is verified again.** `integrations.services.save`
marks every model of an LLM connection unavailable on save (`backend/app/integrations/services.py:166-180`);
the kernel then refuses the employees on it with BLOCKED_PROVIDER «Assigned model is unavailable or
not verified» (`services.py:641-648`) until the Owner presses «Verifică» (sync). Live: 32 runs were
refused this way (26 `verify_claim`, 6 `answer_mail`).

### 3.2 Live state of the assignments

From `domain_event` (read-only): the last assignment of every employee is an `agent.model_assigned`
with `assignment_origin = "OWNER"` at 2026-10-08 09:52 (the re-allocation described in
`docs/project/OLLAMA_ROLE_ALLOCATION.md`). Earlier history includes Elena on `qwen3.5:397b`
(2026-09-09), Sarah on `glm-5.3` (2026-09-11) then `kimi-k3` (2026-09-12), Nadia on
`glm-5.3-flash:cloud` (2026-10-03) then `kimi-k3` (2026-10-04 07:52) and `mistral-large-4`
(2026-10-08). No `agent.model_preferred` and no `DIRECTOR_REPAIR` event exist.

Model registry: three provider rows — `local-ollama` (`http://127.0.0.1:11434`, seeded, HEALTHY
2026-09-12), the Owner's Ollama Cloud connection `settings:d54989ee…` (`https://ollama.com`, HEALTHY
2026-10-08, integration VERIFIED) and an orphan `settings:9298e62d…` (`https://ollama.com/api`,
UNKNOWN, no integration row). Models declaring `vision` on the cloud connection: `kimi-k3`,
`minimax-m3`, `mistral-large-4`, `mistral-large-3:675b`, `gemma4:31b`, `glm-5.3-flash`,
`deepseek-v4.1-flash`, `kimi-k2.6`, `kimi-k2.7-code` (and `qwen3.5:397b`, now unavailable).

Live role capabilities: every role except the Accountant has `text_generation` REQUIRED; the Video
Editor also has `vision` PREFERRED. The Accountant role was created by `seed_missing_workforce`,
which writes no `RoleCapability` row (`services.py:1219-1246`), so her runs pass the capability gate
with no requirement at all (`_check_required_capabilities` returns early, `services.py:533-545`).

---

## 4. Providers and adapters

| Adapter | Serves | Kinds / endpoints | Thinking, JSON, images | Retries and timeouts | Cost | Code |
|---|---|---|---|---|---|---|
| `ConfiguredLLM` | every connection the Owner saves in Settings (the live studio runs only on this) | `ollama` (`/api/generate`, `/api/tags`, `/api/show`, `/api/me` to prove a cloud key), `openai` (`https://api.openai.com/v1` `/chat/completions`, `max_completion_tokens`), `compatible` (base URL from config, `/chat/completions`, `max_tokens`), `anthropic` (`https://api.anthropic.com/v1/messages`, `x-api-key`, `anthropic-version: 2023-06-01`, default `max_tokens` 1024) | Ollama: `think: false` always, then `extra` merged over the body (so `structured_run`'s `{"format": "json"}` / `{"think": true}` and `{"images": [...]}` reach the model). OpenAI/compatible/Anthropic: **`extra` is ignored**, so JSON mode, native thinking and attached images are Ollama-only | `call_with_retries` on 429/502/503/504 and unsent connections; a generation POST that left is never re-sent; 600 s socket timeout (20 s for `/api/me`); 4 MB response cap | `llm_cost_vr(price_lookup, model, prompt_tokens, completion_tokens)` | `backend/app/integrations/llm.py:24-272` (body `:211-223`, other kinds `:238-272`, retries `:90-102`, cloud key proof `:160-169`, capabilities `:181-199`) |
| `OllamaProvider` | only the seeded `local-ollama` endpoint (`provider_type == "OLLAMA"`) | `/api/generate`, `/api/tags`, `/api/show` | `think: false`, `extra` merged | generation not repeatable; refusals raised as `ProviderHTTPError` with status, vendor word and `keyless` | same | `backend/app/providers/ollama.py:77-233`; registered by `register_seeded_ollama` (`backend/app/main.py:222-245`) |
| `DemoModel` | every provider in demo mode | in-process | answers in the requested schema | none | `None` | `backend/app/demo.py:185-404` |

Registration: at start-up `load_registry` registers a `ConfiguredLLM` for every LLM connection whose
keys decrypt (`backend/app/integrations/services.py:186-221`; `main.py:301`), then the seeded Ollama
endpoint (`main.py:302`); re-saving a connection re-registers its adapter with the price table
(`backend/app/integrations/router.py:243-257`). The registry is an in-process map
(`backend/app/providers/registry.py:8-55`).

Model capabilities are the provider's word: `record_declared` stores what `/api/show` lists,
creating unknown capability names rather than dropping them (`services.py:348-391`); seeded models
never get `vision` (`SEEDED_MODEL_CAPABILITIES`, `services.py:1074-1079`).

Errors the Owner must fix become cards: a FAILED run with HTTP 401/402/403 on a Settings connection
proposes the reconnect card, and the next SUCCEEDED run withdraws it
(`backend/app/decisions/sources.py:64`, `:799-845`, called at `services.py:1022-1027`). The run's
`error_detail` holds the class, HTTP status, vendor word and a Romanian meaning, never the vendor's
message (`_failure_detail`, `services.py:697-730`).

The Owner rule "no Anthropic model works in the product" is enforced only when the Director picks a
repair candidate (`agent_health.py:434-437`, `:498`). The catalogue still offers an `anthropic`
connection kind (`backend/app/integrations/catalog.py`), `assign_agent` does not refuse one, and the
preflight counts `openai`/`anthropic` as paid kinds (`backend/app/runbook/preflight.py:460`).

---

## 5. What `run_agent_task` does, step by step

`run_agent_task(engine, registry, agent_id, task_type, objective, prompt_template_version,
correlation_id, max_tokens=None, temperature=None, emit_message=True, summary=None, extra=None,
model_id=None)` — `backend/app/agents/services.py:733-1047`.

| Step | What happens | Decided by | Lines |
|---|---|---|---|
| 1 | Daily token ceiling and USD budget: `may_run_agent(engine, settings, correlation_id, task_type)` before any write transaction (the Accountant's letter writes in its own). Ceiling `agent_daily_token_budget` (0 = none) counts every token since local midnight whatever the outcome; an active DAILY/MONTHLY budget already EXCEEDED refuses too, except `reconcile_day` (`BUDGET_EXEMPT_TASKS`); one Owner letter per kind per day | OWNER (settings, budgets) + CODE_RULE | `services.py:770-781`; `backend/app/economy/accountant.py:1024-1158` |
| 2 | Write lock; load the agent; compose the identity (§2.3) | CODE_RULE | `services.py:783-791` |
| 3 | Director token multiplier: if the role is `Director`, `max_tokens × director_token_multiplier` (default 2, bounds 1..4); requested/effective limits recorded in the context | CONFIG (`STUDIO_DIRECTOR_TOKEN_MULTIPLIER`) | `services.py:792-807`; `backend/app/config.py:11`, `:425`; ADR-DIRECTOR-TOKEN-BUDGET-X2 (`docs/project/16_DECISION_LOG.md:90-112`) |
| 4 | Resolve the answering model (own or `model_id`); a slot model must be available and meet REQUIRED capabilities — this check **raises** (no run row) rather than recording a blocked run | CODE_RULE | `services.py:811-827` |
| 5 | Policy Kernel, inside one `try`: budget verdict → `autonomy_stopped` → `may_act(session, "agent.run", "T1")` (autonomy mode, safe mode) → lifecycle ACTIVE → model exists, available, and (for the own model) on the agent's provider → no live run of this agent (a RUNNING row younger than 45 min; older ones closed ABANDONED; a stale THINKING flag cleared) → REQUIRED capabilities (`BLOCKED_CAPABILITY`, `04_AGENT_SYSTEM.md` §15) → provider health from the in-process cache (HEALTHY or UNKNOWN passes) | CODE_RULE + OWNER (stop, mode) | `services.py:828-857`, `_assert_policy_allows_run` `:608-679`, `_has_live_run` `:563-584`, `_check_required_capabilities` `:520-560` |
| 6 | Refusal: an `AgentRun` row with status `BLOCKED_BUDGET`/`BLOCKED_POLICY`/`BLOCKED_PROVIDER`/`BLOCKED_CAPABILITY` and the reason, returned like any run | CODE_RULE | `services.py:832-857` |
| 7 | Adapter present, else a `BLOCKED_PROVIDER` row | CODE_RULE | `services.py:859-882` |
| 8 | `runtime_state = THINKING`, event `agent.state_changed`; a RUNNING `AgentRun` row written before the call | CODE_RULE | `services.py:884-923` |
| 9 | The call, outside the transaction: `adapter.generate(model, objective, system=identity, max_tokens=effective, temperature, extra)` | EXTERNAL | `services.py:926-937` |
| 10 | Outcome: text → `SUCCEEDED`; no text → `EMPTY_OUTPUT` (explained when `done_reason == "length"`); exception → `FAILED` with `_failure_detail` | CODE_RULE | `services.py:938-975` |
| 11 | Record: `runtime_state = IDLE`, `agent.run_completed`, the run's status, text, tokens, `cost_vr`; reconnect card proposed/withdrawn; if `emit_message` and SUCCEEDED, `agent.message_sent` with ≤1200 characters (the live speech bubble; `docs/architecture/06_BACKEND_EVENT_MODEL.md` §7) | CODE_RULE | `services.py:977-1047` |

Notes on the kernel:

- The module docstring lists six gates (`services.py:1-15`); the code has more (autonomy mode,
  model availability, live run) and runs the adapter check last.
- **The provider-health gate is inert at runtime.** `registry.cached_status` returns UNKNOWN until
  `check_health` fills the cache (`registry.py:28-39`); the only caller of `check_health` is
  `refresh_all` (`registry.py:41-45`), and nothing in `backend/app` or `scripts/` calls
  `refresh_all`. So the gate always sees UNKNOWN, which passes (`services.py:674-679`). Provider
  outages surface as FAILED runs, not BLOCKED_PROVIDER.
- `Agent.cost_limit_per_task` and `max_concurrent_tasks` (`backend/app/agents/models.py:139-140`)
  are stored and shown, never read by a gate; concurrency is the live-run check above.
- Only three call paths let the answer become a speech bubble (default `emit_message=True`):
  `history.chat`, `router.run_agent`, `test_agent_llm`; every other direct call passes
  `emit_message=False`, and the ensemble's own call (`ensemble.py:222`) inherits the caller's
  `False` from `command._choose` (AST scan of the 23 direct calls).

Live settings: `STUDIO_AGENT_DAILY_TOKEN_BUDGET` is not set in `.env`, so the ceiling is 0 (none);
`STUDIO_DIRECTOR_TOKEN_MULTIPLIER` is not set, so 2. The active USD budget is DAILY 500 USD (warn
at 80 %); a 15 USD daily budget was replaced on 2026-10-05. `owner_policy`: not stopped,
`PRODUCTION`, `AUTONOMOUS_CEO`, paid media approval `OVER_USD` 5.0. The preflight line
`agent_token_ceiling` is DEGRADING while paid models run without a ceiling
(`backend/app/runbook/preflight.py:463-511`).

Statuses recorded live: SUCCEEDED 1519, FAILED 866, BLOCKED_PROVIDER 32, EMPTY_OUTPUT 5,
BLOCKED_POLICY 2 (both «Agent already has an active task»), BLOCKED_BUDGET 0.

---

## 6. Structured answers and retries

| Piece | What it does | Code |
|---|---|---|
| `structured_run` | Two attempts at most. First: the prompt, `extra={"format": "json"}`, thinking off. If the run failed or returned no text: stop (no retry). If no JSON object at all came back: second attempt with `{"think": true}` (template `+think`). If an object came back but the schema refused it even after fitting: second attempt in JSON mode with the refusal quoted (`REFUSED_NOTE`, template `+again`). Returns `(parsed, first, second)`; a refused run carries `refusal` and an `error_detail` saying why | `backend/app/agents/structured.py:76-166` (attempt logic `:109-160`) |
| `read_structured` | Accepts fenced, bare or embedded JSON; tries every `{` (≤400) as the start of an object; the first that validates wins; otherwise the refusal of the candidate closest to the schema | `backend/app/agents/identity.py:603-639` |
| `fit_to_schema` | Before validation: strings over `max_length` cut at a word boundary, lists truncated, nested models fitted, Literal/Enum/`^(A|B)$` code words matched case- and spacing-insensitively; nothing added or retyped (introduced after the cyclotron QC decision of 2026-10-11 was refused five times for a 773-character reason) | `identity.py:406-583` |
| `clipped`, `joined` | Field validators that clip text or join a list of lines instead of refusing | `identity.py:377-403` |
| `blocker_of` | The STANDING RULE's `{"blocker": {"reason", "needs"}}` parsed as a structured refusal; several call sites turn it into an ESCALATE letter | `identity.py:648-662` |
| `parse_structured` | Fit-then-validate without a retry; used by the call sites that call `run_agent_task` directly (e.g. `command._choose`, `story.review.review_episode`) | `identity.py:642-645` |

Call sites that bypass `structured_run` parse the text themselves; the factual pipeline does its
own retry (`write_script` templates `v1`, `v1+retry`, `v1+cards`,
`backend/app/factual/agent_pipeline.py:724`, `:758`, `:804`), and `write_shot_prompts` re-asks once
for missing shots (`backend/app/media/prompt_agent.py:1191`). Live: 10 runs used `+think`, none
used `+again` yet.

---

## 7. Multi-model strategies (ensembles)

Principles (module docstring, `backend/app/agents/ensemble.py:1-27`): no model is named in logic;
extra models cost money so routine work does not get them; "The advisers advise; the agent
decides" — in REVIEW, DEBATE and PARALLEL the answer returned is always a run on the employee's own
primary model with the others' words in its prompt; a review that could not happen is recorded
`REVIEW_INCOMPLETE`, never invented.

| Element | Values / rule | Code |
|---|---|---|
| Strategies | `SINGLE`, `FALLBACK`, `REVIEW`, `DEBATE`, `PARALLEL` | `ensemble.py:46` |
| Policies | `IMPORTANT_ONLY` (caller's importance ≥ `min_importance`), `LOW_CONFIDENCE` (reported confidence < `min_confidence`, default 0.6), `ALWAYS`, `MANUAL` (only when the caller requests review) | `ensemble.py:49`, `should_collaborate` `:131-166` |
| Importance | `ROUTINE` < `NOTABLE` < `STRATEGIC`, stated by the caller | `ensemble.py:53-54` |
| FALLBACK | primary; if unusable, secondary then tertiary (task type `…:fallback`); the last real failure is returned if none answers | `ensemble.py:311-356` |
| REVIEW | primary; secondary critiques (`…:critique`, inert-boundary prompt, "You are not the decision-maker"); primary writes the final (`…:final`); overlap < 0.34 flagged as disagreement | `ensemble.py:359-456`, `_critique_prompt` `:612-627`, `_CRITIC_INSTRUCTIONS` `:68-79` |
| DEBATE | primary and secondary answer independently; tertiary judges only on material disagreement (`agreement` < `AGREEMENT_FLOOR = 0.34`, shared content words); primary synthesises | `ensemble.py:459-544`, `:62`, `:169-179` |
| PARALLEL | two or three models answer; primary synthesises | `ensemble.py:547-609` |
| Record | every participating call is an ordinary `AgentRun`; `LlmCollaboration` joins them (strategy, reason, roles, disagreement, final model, latency, summed tokens); `GET /api/v1/agents/{id}/collaborations` | `_finish` `ensemble.py:643-740`; `backend/app/agents/models.py:182` |

Who decides: the strategy, policy and slots are OWNER (or CONFIG through the allocation file); the
importance is CODE_RULE at the call site; whether a second model runs is CODE_RULE
(`should_collaborate`); the final answer is the primary model's (LLM) and then whatever the call
site checks.

Reality: **only one call site uses `run_with_strategy`**: `command._choose`
(`backend/app/agents/command.py:1156-1177`, `importance="STRATEGIC"`, a critic `review_objective`
about sample size, noise and causation). Every other Director task runs on her primary model alone.
Live: 8 `LlmCollaboration` rows, all REVIEW / COMPLETE, final model `kimi-k3`, critic
`nemotron-3-ultra` (`direct_company:critique` 8 runs). A `REVIEW_INCOMPLETE` lowers the Director's
choices to LOW confidence (`command.py:1202-1207`).

---

## 8. What LLM calls cost

| Element | Rule | Decided by | Code |
|---|---|---|---|
| Price per token | `ProviderPrice` rows typed by the Owner (`PUT /economy/prices`); "no agent, no search result and no vendor page can write one"; per model, family `prefix*`, or `*` for the kind; OWNER outranks DOCUMENTED | OWNER | `backend/app/economy/prices.py:1-25`, `price_lookup` `:242-252` |
| Cost of a run | `llm_cost_vr`: both input and output prices and both token counts known, else `None` (never zero); integer micros | CODE_RULE | `prices.py:261-278`; called in `llm.py:229-231`, `:263`, `:271`, `ollama.py:228` |
| Live price | `ollama` / `*` / 0.50 USD per 1M input and per 1M output tokens, OWNER, set 2026-10-05. Because it is `*` for the kind `ollama`, it also prices models served by the local endpoint (the seeded `local-ollama` adapter is built with `price_lookup(engine, "ollama")`, `main.py:241-245`); a truly local model would need its own `0` row to cost nothing | OWNER | `provider_price` table |
| Coverage | 1519 SUCCEEDED runs: 1068 with a cost, 451 without; every uncosted one is older than 2026-10-03 06:15Z, the first costed run (the active price rows are stamped 2026-10-05 13:46Z) | — | live |
| Token ceiling / USD budget | §5 step 1 | OWNER + CODE_RULE | `accountant.py:1098-1158` |
| Director allowance | ×2 on every Director run with an explicit limit, including the critic call made in her name | CONFIG | `services.py:792-798` |
| Preflight | `model_prices` DEGRADING when an employee's model has no token price; `agent_token_ceiling` DEGRADING when paid models run without a ceiling | CODE_RULE | `backend/app/runbook/preflight.py:382-511` |
| Collaboration cost | each run of a strategy carries its own `cost_vr`; the `LlmCollaboration` row sums tokens only | CODE_RULE | `ensemble.py:674-675` |

`price_table_for` (`backend/app/media/shooting_sheet.py:319-327`) is the **media** price table (RunPod
estimates, MEASURED Runway prices, and `local_media.local_prices` which prices verified ComfyUI
resources at 0 credits, `backend/app/media/local_media.py:66-96`). It is not used for LLM tokens:
"local models cost 0" holds for local image/video generation, not for language models, whose cost
comes only from `ProviderPrice` through `llm_cost_vr`.

`STUDIO_EDITORIAL_ROUNDS` (default 10) multiplies the Director's judgement and the writer's rewrites;
its comment says "a round is model calls, never credits, so no money gate reads it"
(`backend/app/config.py:427-434`). Since the Owner's token price exists, those calls do carry a USD
`cost_vr` and count against the USD budget through `may_run_agent`.

---

## 9. The 37 LLM call sites

### 9.1 The table

Gateway line = the line of the gateway call inside the function (AST scan). `max_tokens` before the
Director's ×2. Trust per the vocabulary; the detailed justification is in the subsystem file named
in the last column.

| # | Call site (definition) | Gateway (call line) | Speaker | task_type | max_tokens / temp | Trust | If the model fails | Detail |
|---|---|---|---|---|---|---|---|---|
| 1 | `agents.command._choose` `command.py:1083` | `run_with_strategy` `:1156` | Director (+ critic) | `direct_company` | 3000 / 0.2 | CHECKED_BY_CODE | the computed findings in their own order | `subsystems/10_agents_core.md` |
| 2 | `agents.director.choose_topic` `director.py:195` | `run_agent_task` `:217` | Director | `choose_topic` | 2400 / 0.1 | CHECKED_BY_CODE (id must be a candidate) | deterministic candidate order | 10 |
| 3 | `agents.director.director_review` `director.py:492` | `structured_run` `:534` | Director | `director_review` | 24000 / 0.1 | CHECKED_BY_CODE (unknown ids dropped, escalations downgraded unless the Owner's matter) | `DirectorError`, Owner letter | 10 |
| 4 | `agents.editorial.editorial_review` `editorial.py:400` | `structured_run` `:456` | Director (frames cut and attached only if her own model sees, `editorial.py:431-438`; no borrowed model) | `editorial_review` | 6000 / 0.1 | FINAL for REJECT (closes the storyboard); APPROVE still passes the publishing gates | SKIPPED for the day | `subsystems/11_agents_reviews_repairs.md` |
| 5 | `agents.editorial_judgement.judge` `editorial_judgement.py:410` | `structured_run` `:442` | Director | `editorial_judgement` | 2000 / 0.2 | CHECKED_BY_CODE (code computes the bar and ranking; a version always ships) | None, best version so far | 11 |
| 6 | `agents.history.chat` `history.py:111` | `run_agent_task` `:123` | employee the Owner opened | `owner_chat` | 3600 / 0.4 | INFORMATIONAL | run status shown | 10 |
| 7 | `agents.mail.answer_mail` `mail.py:443` | `structured_run` `:491` | addressee | `answer_mail` | 3600 / 0.3 | CHECKED_BY_CODE (repeat requests held, unproven media claims labelled; the `done` flag closes HANDOFFs as given) | back-off 300 s doubling to 6 h | 10 |
| 8 | `agents.repairs.agent_health._probe` `agent_health.py:568` | `run_agent_task` `:575` | the probed employee, pinned model | `TEST_CONNECTIVITY` (template `director-probe-v1`) | 64 / 0.0 | CHECKED_BY_CODE (only status and non-empty text count) | model treated as down | 11 |
| 9 | `agents.reviews.review_narration` `reviews.py:203` | `reviews._run` `:221` | VoiceArtist | `review_narration` | 4500 / 0.1 | ADVISORY | `ReviewError` | 11 |
| 10 | `agents.reviews.review_failed_render` `reviews.py:455` | `reviews._run` `:490` | VideoEditor | `review_failed_render` | 3600 / 0.1 | ADVISORY (redo list and prices do not depend on it) | `ReviewError` | 11 |
| 11 | `agents.reviews.review_film_qc` `reviews.py:981` | `structured_run` `:1028` | Director | `director_qc_review` | 6000 / 0.1 | CHECKED_BY_CODE (REPAIR must be doable; paid steps behind `may_act`) | waits, asked again | 11 |
| 12 | `agents.reviews.review_bought_pictures` `reviews.py:1148` | `structured_run` `:1201` | Director on a seeing model (`seeing_model`) | `director_take_look` | 4000 / 0.1 | FINAL (her CHOOSE overrides the gate's refusal) | waits | 11 |
| 13 | `agents.reviews.prepare_publication` `reviews.py:1485` | `reviews._run` `:1546` | Publisher | `prepare_publication` | 4500 / 0.1 | CHECKED_BY_CODE (language hold, title/tag sanitising, cross-channel copy guard, HOLD on refusal) | SKIPPED for the day | 11 |
| 14 | `agents.router.create_agents_router.run_agent` `router.py:297` (`POST /api/v1/agents/{agent_id}/run`) | `run_agent_task` `:303` | any (Owner) | from the request | from the request | INFORMATIONAL | run returned | 10 |
| 15 | `economy.accountant.reconcile_day` `accountant.py:1188` | `structured_run` `:1214` | Accountant | `reconcile_day` | 6000 / 0.1 | ADVISORY (escalation decided by the books; the model can only add one) | `AccountantError`, books filed SKIPPED | `subsystems/14_decisions_economy.md` |
| 16 | `factual.agent_pipeline.agent_extract_claims` `agent_pipeline.py:208` | `run_agent_task` `:229` | LeadResearcher (fallback any) | `extract_claims` | 7200 / 0.2 | ADVISORY (stored UNVERIFIED) | nothing stored | `subsystems/15_factual_research.md` |
| 17 | `factual.agent_pipeline.agent_verify_claim` `agent_pipeline.py:357` | `run_agent_task` `:389` | FactChecker, never the extractor | `verify_claim` | 2100 / 0.0 | CHECKED_BY_CODE (a SUPPORTED/REFUTED quote must occur in the source text, `agent_pipeline.py:411-417`) | claim stays unverified | 15 |
| 18 | `factual.agent_pipeline.agent_write_script` `agent_pipeline.py:642` | `run_agent_task` `:724`, `:758`, `:804` | ScriptWriter (fallback any) | `write_script` | 7200 / 0.4, 0.3, 0.2 | CHECKED_BY_CODE (cited claims must be SUPPORTED) | refused draft | 15 |
| 19 | `factual.script_agent.draft_with_agent` `script_agent.py:28` | `run_agent_task` `:73` | ScriptWriter | `write_script` | 9000 / — | CHECKED_BY_CODE — **no callers** | — | 15 |
| 20 | `factual.story_review._ask_director` `story_review.py:544` | `run_agent_task` `:618` | Director | `story_review` | 3000 / 0.2 | CHECKED_BY_CODE (stricter only) | computed verdict stands | 15 |
| 21 | `integrations.router.create_settings_router.test_agent_llm` `integrations/router.py:436` (`POST /api/v1/settings/agents/{agent_id}/test`) | `run_agent_task` `:444` | any (Owner) | `TEST_CONNECTIVITY` | 2400 / 0.2 | INFORMATIONAL | run returned | `subsystems/13_providers_integrations.md` |
| 22 | `media.blocker_repair.director_assignment` `blocker_repair.py:557` | `structured_run` `:579` | Director | `sheet_repair_assignment` | 1400 / 0.1 | CHECKED_BY_CODE (role pinned by code; effect re-linted) | — | `subsystems/07_media_repair_cards_sound.md` |
| 23 | `media.model_research.research_models` `model_research.py:205` | `run_agent_task` `:297`, `:337` | VideoEditor (video, image), VoiceArtist (voice) | `research_models` | 1500 and 6000 / 0.1 | CHECKED_BY_CODE (vendor hosts only, scores clamped, unknown ids ignored, billed prices protected) | purpose SKIPPED | 07, 13 |
| 24 | `media.picture_qc.evaluate_pictures` `picture_qc.py:904` | `structured_run` `:1162` | first seeing `LOOKERS` | `picture_qc` | 4000 / 0.1 | FINAL for the QC record (a false flag fails the film; a later Director decision may overrule) | checks NOT_APPLICABLE | `subsystems/03_media_quality_control.md` |
| 25 | `media.picture_qc.judge_still` `picture_qc.py:1668` | `structured_run` `:1737` | first seeing `LOOKERS` | `still_qc` | 800 + 150 per must-fix / 0.1 | CHECKED_BY_CODE (local checks first; best PASSED by score) | candidate not judged | 03 |
| 26 | `media.picture_qc.judge_clip` `picture_qc.py:1929` | `structured_run` `:1997` | first seeing `LOOKERS` | `clip_qc` | 800 / 0.1 | CHECKED_BY_CODE (any negative flag fails; missing verdict NOT_RUN) | NOT_RUN | 03 |
| 27 | `media.prompt_agent.build_visual_bible` `prompt_agent.py:987` | `prompt_agent._run` `:1017` | VideoEditor | `visual_bible` | 2200 / 0.3 | CHECKED_BY_CODE | degrade, no bible | `subsystems/04_media_prompts_rewrite.md` |
| 28 | `media.prompt_agent.write_shot_prompts` `prompt_agent.py:1081` | `prompt_agent._run` `:1169`, `:1191` | VideoEditor | `shot_prompts` | 7000 / 0.3 | CHECKED_BY_CODE (compiled, linted) | one re-ask; serial composes from the fixed look | 04 |
| 29 | `media.scene_rewrite.director_brief` `scene_rewrite.py:837` | `structured_run` `:872` | Director | `director_scene_brief` | 2500 / 0.1 | CHECKED_BY_CODE | no brief | 04 |
| 30 | `media.scene_rewrite.review_rewrite` `scene_rewrite.py:1067` | `structured_run` `:1130` | Director | `director_rewrite_review` | 1600 / 0.1 | FINAL for store-or-not (internal consistency checked) | fail closed, nothing stored | 04 |
| 31 | `media.scene_rewrite._editor_rewrite` `scene_rewrite.py:1279` | `structured_run` `:1308` | VideoEditor | `scene_prompt_rewrite` | 3000 / 0.3 | CHECKED_BY_CODE (then reviewed by #30) | nothing stored | 04 |
| 32 | `media.sound_design.sound_plan` `sound_design.py:379` | `structured_run` `:439` | VoiceArtist | `sound_design` | 3000 / 0.1 | CHECKED_BY_CODE (vetted tracks, bounded levels, loudness measured) | computed plan | 07 |
| 33 | `research.agent.propose_topics` `research/agent.py:398` | `run_agent_task` `:450` | LeadResearcher | `propose_topics` | 7500 / 0.4 | CHECKED_BY_CODE (validation; no second film on a made subject, `_too_similar` `research/agent.py:121`, `:506`) | nothing stored | 15 |
| 34 | `research.agent.gather_sources` `research/agent.py:707` | `run_agent_task` `:767` | LeadResearcher | `gather_sources` | 3600 / 0.2 | CHECKED_BY_CODE (stored text is what the studio downloaded from allowed hosts) | nothing stored | 15 |
| 35 | `runbook.weekly.execute_weekly_review` `weekly.py:271` | `run_agent_task` `:322` | Director | `WEEKLY_REVIEW` | 4800 / 0.3 | ADVISORY (indications are letters to other employees) | review skipped | `subsystems/09_runbook_services_workflows.md` |
| 36 | `story.review.review_episode` `story/review.py:946` | `run_agent_task` `:1001` | Director | `episode_review` | 3000 / 0.1 | CHECKED_BY_CODE (rubric floor; PASS without scores refused) | DRAFT stays unreviewed | `subsystems/16_story_publishing.md` |
| 37 | `story.services.write_episode` `story/services.py:1520` | `run_agent_task` `:1637` | ScriptWriter as showrunner (fallback any) | `write_episode` | 7200 / 0.7 | CHECKED_BY_CODE (every event id, speaker and thread must exist) | `StoryError` / `DraftRefused` | 16 |

### 9.2 Trust tally and what "FINAL" means here

| Trust | Count | Call sites |
|---|---:|---|
| CHECKED_BY_CODE | 25 | 1, 2, 3, 5, 7, 8, 11, 13, 17, 18, 19, 20, 22, 23, 25, 26, 27, 28, 29, 31, 32, 33, 34, 36, 37 |
| FINAL | 4 | 4 (REJECT), 12, 24, 30 |
| ADVISORY | 5 | 9, 10, 15, 16, 35 |
| INFORMATIONAL | 3 | 6, 14, 21 |

> Reconciled count (reference for the whole map): `LLM_CALL_SITES.md` §6 moves #5 `judge` to
> FINAL (24 / 5 / 5 / 3) and keeps the other labels above; it also corrects the "scores clamped"
> reading of #23 `research_models` (an out-of-range score refuses the whole object).

The four FINAL answers are judgements about pictures or prompts where the model's verdict is the
measurement: the Director's REJECT of a finished film (#4), her choice among candidates the gate
refused (#12), the vision employee's picture/character flags (#24) and the Director's
store-or-not verdict on a rewrite (#30). None spends money by itself; #12 and #30 let a later paid
step proceed under its own money gates (`may_act` paid-media rule, budgets).

### 9.3 Functions that only reach a model through others

The inventory counts 151 functions with a static path to the gateway (`STATS.md`). Typical chains:
the daily runbook stages (`app.runbook.stages`, 34 functions reach a model) call the call sites
above; `mail.correspondence_round` → `answer_mail`; `command.direct_company` → `_choose`;
`POST /api/v1/agents/director/review` → `director_review`; `POST /api/v1/settings/model-research`
and the weekly job `model_research_weekly` → `research_models`
(`backend/app/integrations/router.py:393`, `backend/app/workflows/worker.py:91`).

---

## 10. How much of the system is LLM, and how much is strict rules

### 10.1 Static measure (`STATS.md`, generated by `scripts/backend_map.py`)

| Measure | Value |
|---|---|
| Functions | 3951 in 245 files, 156,526 lines |
| Call `run_agent_task` directly | 20 functions (1 %), 2353 lines (2 %) |
| LLM call sites | 37 functions, 5012 lines (4 % of function lines) |
| Can reach a model (any static path) | 151 functions (4 %), 21,571 lines (18 %) |
| Packages with no static path to a model | `providers`, `decisions`, `publishing`, `office`, `analytics`, `services`, `events_feed`, `youtube`, `workforce`, `backup`, `wording`, `config`, `goal`, `operations`, … (`STATS.md` rows with 0) |
| Highest LLM share by lines | `app.runbook` 47 % reachable, `app.factual` and `app.story` 30 %, `app.research` 26 %, `app.media` 22 % |

### 10.2 What the models never decide (strict rules and the Owner)

| Decision | Decided by | Where |
|---|---|---|
| Whether any model may run now | CODE_RULE + OWNER settings | §5 (`services.py:608-679`, `accountant.py:1098-1158`) |
| Which model an employee uses | OWNER, CONFIG, two CODE_RULEs | §3 |
| Which models exist and can see | EXTERNAL | `services.py:313-455` |
| Token prices and budgets | OWNER | `prices.py:1-25`; `spending_budget` |
| Paid media steps (stills, motion, redo) | OWNER rule `paid_media_approval` + mode + budgets via `may_act` | `backend/app/services.py:1410-1458` |
| Publishing gates (file present, QC passed, factual provenance, no duplicate, privacy) | CODE_RULE | `subsystems/16_story_publishing.md`, `subsystems/08_runbook_stages.md` |
| Measured QC (resolution, duration, loudness, placeholder frames) | CODE_RULE | `subsystems/03_media_quality_control.md` |
| Hiring, suspension, termination | OWNER (proposals computed from counted rows) | `backend/app/workforce/services.py:1-12`, `:129`, `:270` |
| Accounting totals | CODE_RULE ("the sums are computed, not for you to recompute") | `accountant.py:1176-1185` |
| Which employee looks at a picture | CODE_RULE + EXTERNAL | `vision.py:116-142` |
| Whether a second model is consulted | CODE_RULE on OWNER configuration | `ensemble.py:131-166` |

### 10.3 Where the model's answer carries weight

The model writes all creative and evaluative text: topics, claims, verdicts on claims, scripts,
serial episodes, visual bibles, shot prompts and rewrites, sound plans, publication metadata,
picture/clip verdicts, film verdicts, QC repair decisions, inbox decisions, company direction,
letters and chat. In 25 of 37 call sites code verifies that content against stored facts (ids,
quotes, rosters, schemas, rubrics, lint) or bounds it (stricter-only, clamps, fallbacks); in 9 the
answer is advice or human-readable text; in 4 it is the judgement itself.

---

## 11. Live usage (read-only snapshot, newest run 2026-10-12T13:52:23Z)

### 11.1 Runs by task type and model, last seven days (from 2026-10-05)

| task_type | model | runs | SUCCEEDED |
|---|---|---:|---:|
| verify_claim | deepseek-v4-pro:0813 | 171 | 170 |
| clip_qc | kimi-k3 | 137 | 137 |
| still_qc | kimi-k3 | 131 | 131 |
| director_scene_brief | kimi-k3 | 57 | 56 |
| scene_prompt_rewrite | kimi-k3 | 55 | 55 |
| director_qc_review | kimi-k3 | 45 | 42 |
| director_review | kimi-k3 | 32 | 32 |
| answer_mail | kimi-k3 | 29 | 29 |
| write_script | kimi-k3 | 26 | 26 |
| shot_prompts | kimi-k3 | 25 | 24 |
| story_review | kimi-k3 | 25 | 25 |
| sheet_repair_assignment | kimi-k3 | 21 | 21 |
| answer_mail | mistral-large-4 | 17 | 17 |
| extract_claims | minimax-m3 | 16 | 16 |
| write_episode | kimi-k3 | 16 | 16 |
| picture_qc | kimi-k3 | 15 | 15 |
| owner_chat | kimi-k3 | 10 | 10 |
| reconcile_day | mistral-large-4 | 7 | 7 |
| direct_company / `:critique` / `:final` | kimi-k3 / nemotron-3-ultra / kimi-k3 | 5 / 5 / 5 | 5 / 5 / 5 |
| other (visual_bible, research_models, review_failed_render, choose_topic, prepare_publication, sound_design, episode_review, editorial_review, …) | mostly kimi-k3 | ≤ 9 each | — |

Seven-day totals: 906 runs, 901 SUCCEEDED, 7.39 M prompt + 0.39 M completion tokens, USD 3.89.
Per day: 10-08 57 runs, 10-09 110, 10-10 96, 10-11 285, 10-12 340 (USD 1.66 so far). No runs on
10-06 and 10-07.

### 11.2 All-time by model

| model (provider) | runs | SUCCEEDED | FAILED | USD |
|---|---:|---:|---:|---:|
| kimi-k3 (cloud connection) | 947 | 884 | 52 | 3.64 |
| glm-5.3-flash:cloud (local-ollama) | 492 | 0 | 492 | 0 |
| qwen3.5:397b (cloud) | 371 | 201 | 144 | 0 |
| mistral-large-3:675b (cloud) | 209 | 74 | 135 | 0.09 |
| deepseek-v4-pro:0813 (cloud) | 174 | 173 | 0 | 0.50 |
| minimax-m3 (cloud) | 118 | 81 | 37 | 0.12 |
| mistral-large-4 (cloud) | 31 | 31 | 0 | 0.07 |
| glm-5.3-flash (cloud) | 27 | 22 | 5 | 0.01 |
| nemotron-3-ultra (cloud) | 22 | 22 | 0 | 0.04 |
| nemotron-3-super, glm-5.3, gpt-oss:120b (cloud) | 19 / 11 / 3 | 19 / 9 / 3 | 0 / 1 / 0 | 0 |

### 11.3 The 2026-10-04 retry storm

492 runs on `glm-5.3-flash:cloud @ local-ollama` failed between 05:23 and 07:51, 481 of them Nadia's
`answer_mail` («HTTPError» with no status). This is the incident that led to `ProviderHTTPError`
carrying status and vendor word on the local adapter (`backend/app/providers/ollama.py:12-16`) and
to the Director's health desk (`backend/app/agents/repairs/agent_health.py:3-8`). It still dominates
the all-time failure counts (Nadia: 551 runs, 54 SUCCEEDED) although she has not failed on her
current model.

---

## 12. Comparison with the existing routing documents

| Document | What it covers | Still right | Stale or off-topic |
|---|---|---|---|
| `docs/project/MODEL_ROUTING.md` (2026-09-12) | **Media** model routing (test vs production environment, Runway video models, price provenance, model lifecycle) | the functions it names still exist (`production_policy.rank_candidates` `backend/app/media/production_policy.py:320`, `choose_model` `:908`, `resolve_purpose` `:1184`, `factory.motion_for_scene` `backend/app/media/factory.py:543`) | It says nothing about LLM routing despite its title. Its vendor examples (Runway `seedance2*`, `docs.dev.runwayml.com` prices) predate the move of media to RunPod Serverless; its test figures (625 tests) are historical |
| `docs/project/MULTI_LLM.md` (2026-09-12) | slots, strategies, policies, allocation, traceability | the strategy semantics, policies, 0.34 floor, `REVIEW_INCOMPLETE`, "the advisers advise" rule all match `ensemble.py` | Allocation table: FactChecker `qwen3.5:397b` (now unavailable; live `deepseek-v4-pro:0813`), VoiceArtist `mistral-large-3:675b` (live `mistral-large-4`), VideoEditor `glm-5.3-flash:cloud` (live `kimi-k3`), Accountant `glm-5.3-flash:cloud` (live `mistral-large-4`). Limit 2 ("collaboration cost not in the books… Ollama Cloud is not priced") is outdated: every run now carries `cost_vr` from the Owner's 0.50 USD/1M price. It does not mention the `DIRECTOR_REPAIR` origin, `owner_home_model`, the Director token multiplier, the token ceiling or the USD-budget refusal. The migration head it cites (0038) is now `0057_runpod_copy_pod` |
| `docs/project/OLLAMA_ROLE_ALLOCATION.md` (2026-10-08) | the current allocation and why | matches the live database exactly (8 assignments, origin OWNER, Sarah REVIEW with `nemotron-3-ultra`) | Does not say that the REVIEW strategy affects only `direct_company` (§7), nor that the Accountant's role has no REQUIRED capability, nor that JSON mode and images work only on Ollama-kind connections |
| `config/workforce_seed.json` | first hire and starting allocation | `llm_allocation` equals the live assignment | `agents_def` names `:cloud` models on `local-ollama`, while the live studio runs on the direct cloud connection; the file only affects a new studio or an employee never assigned |
| `config/role_contracts.json` (version 6) | the contracts in every identity | — | The live roles hold contract version 3 (seeded by migration `backend/migrations/versions/0026_director_mandate.py`). `seed_role_contracts` never overwrites an existing contract (`identity.py:115-116`) and no migration carries versions 4-6, so the live prompts lack e.g. the Director's `editorial_judgement` and `episode_review` watch items, the ScriptWriter's serial-episode rules ("a speaker's name, a colon or a stage direction inside a serial line's text"), the Video Editor's serial-shot item and the Accountant's daily-USD item (compared field by field, read-only) |

---

## 13. Oddities and risks found while mapping

1. **Provider-health gate never fires** (§5): `ProviderRegistry.check_health` has no runtime caller;
   `cached_status` is always UNKNOWN (`backend/app/providers/registry.py:28-45`,
   `backend/app/agents/services.py:674-679`).
2. **Role task types are not enforced** (§2.1): `identity.py:296-297` is the only use.
3. **The Accountant role has no REQUIRED capability** (`services.py:1219-1246`; live `role_capability`).
4. **`QualityAssurance` in `LOOKERS`** names a role that is never seeded (`picture_qc.py:119`).
5. **`extra` is dropped for OpenAI, compatible and Anthropic connections** (`llm.py:238-272`):
   attached images, `format: json` and `think` are not sent; a picture check moved to such a
   connection would judge without the pictures. `model_can_see` and `seeing_model` read only the
   declared capability, which those kinds never declare (`_declared_capabilities` returns `{}` for
   non-Ollama kinds, `llm.py:188-189`), so in practice no seeing model is found there.
6. **A slot model that became unavailable raises** `PolicyKernelError` before the kernel's `try`
   (`services.py:819-827`), so no `AgentRun` row records it; callers catch it
   (`agent_health.py:589-590`, `reviews.py:1219-1222`), and ensembles pre-check availability
   (`ensemble.py:334`, `:383`, `:481`, `:566`).
7. **Verifier independence is per agent, not per model** (`agent_pipeline.py:302-330`): the claim's
   extractor is excluded, but nothing prevents the verifier from running on the same model. Live
   they differ (`minimax-m3` vs `deepseek-v4-pro:0813`).
8. **The `*` Ollama price also prices the local endpoint** (`main.py:241-245`): a model actually
   running on the Owner's machine would be booked at 0.50 USD/1M tokens unless the Owner types a
   model-specific `0`.
9. **Open messages enter the system prompt** (`identity.py:314-324`): text written by other
   employees' models (and the Owner) sits in the privileged section that
   `docs/architecture/30_PROMPT_CONTEXT_MEMORY_ARCHITECTURE.md` "Prompt injection boundary" reserves
   for trusted text; task payloads, by contrast, are wrapped in `<untrusted_source_evidence>`
   (`backend/app/factual/sanitizer.py:104-112`).
10. **Identity size**: ≈14 k characters per run on average (§2.3), the largest single share of the
    tokens the studio pays for.
11. **Dead call site**: `factual.script_agent.draft_with_agent` has no callers (static search).
12. **`Agent.cost_limit_per_task` / `max_concurrent_tasks`** are never enforced (`models.py:139-140`).
13. **Anthropic exclusion is partial** (§4): only the repair candidate filter applies it.
14. **`docs/architecture/33_MODEL_EVALUATION_DRIFT.md` "Role suitability"** (APPROVED,
    APPROVED_DEGRADED, TESTING, UNSUITABLE, UNKNOWN, STALE) has no implementation for language
    models in `backend/app`; suitability today is the Owner's assignment plus the REQUIRED
    capability check.

---

## 14. Index of the code read for this file

| File | Lines | Role in LLM routing |
|---|---:|---|
| `backend/app/agents/services.py` | 1749 | the gateway, the kernel, seeding, preferences, assignment provenance |
| `backend/app/agents/identity.py` | 662 | system prompt, contracts, structured parsing and fitting |
| `backend/app/agents/structured.py` | 166 | two-attempt structured answers |
| `backend/app/agents/ensemble.py` | 921 | strategies, allocation file, model-name resolution |
| `backend/app/agents/vision.py` | 185 | who can look at a picture |
| `backend/app/agents/seed_config.py` | 62 | allocation file schema |
| `backend/app/agents/memory.py` | 184 | recall into the identity |
| `backend/app/agents/models.py` | 317 | `Agent`, `AgentRun`, `LlmCollaboration` |
| `backend/app/agents/repairs/agent_health.py` | 778 | diagnosis and the Director's model switch |
| `backend/app/integrations/llm.py` | 272 | `ConfiguredLLM` |
| `backend/app/integrations/services.py` | — | `load_registry`, `save`, `assign_agent` |
| `backend/app/integrations/router.py` | — | assignment, verification, test routes |
| `backend/app/providers/ollama.py` | 233 | seeded local adapter |
| `backend/app/providers/registry.py` | 55 | adapter map and health cache |
| `backend/app/economy/prices.py` | — | token prices and `llm_cost_vr` |
| `backend/app/economy/accountant.py` | — | `may_run_agent`, `reconcile_day` |
| `backend/app/decisions/sources.py` | — | reconnect card after a refused run |
| `backend/app/demo.py` | 576 | the demo model |
| `backend/app/main.py` | 1000 | adapter registration at start-up |
| `config/workforce_seed.json`, `config/role_contracts.json` | 153, 432 | roster, allocation, contracts |
