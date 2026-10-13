# Backend map of AMN-AI: entry point

This folder maps the backend (`backend/app`, Python, FastAPI, SQLAlchemy on SQLite): every
function, what it does, why it exists, **who decides** each thing (a language model, fixed code,
the Owner, a config file, an outside provider) and how much of the studio is LLM against strict
rules. Every claim in the map carries `file:line`. Line numbers are those of commit `b00083c`
(section 8 explains the four commits made after the map). The map is documentation, not
specification: the normative architecture stays in `docs/architecture/` (start with
`docs/architecture/README.md` and `docs/architecture/00_MASTER_PROMPT.md`).

Vocabulary used across the map:

- **Decided by**: `LLM` (the model's answer is acted on with only shape/schema validation),
  `LLM_CHECKED_BY_CODE` (the model proposes; code verifies, clamps or can refuse it),
  `CODE_RULE` (deterministic rule, threshold, cap or state machine), `OWNER` (the human, through
  a decision card, a button or a setting), `CONFIG` (a config file or `Settings` value),
  `EXTERNAL` (a provider's or vendor's answer).
- **Trust** of a model's answer: `FINAL` (acted on as is after schema validation),
  `CHECKED_BY_CODE` (code verifies content and can refuse, clamp or override), `ADVISORY`
  (recorded or weighed; code or the Owner has the last word), `INFORMATIONAL` (human-readable
  text with no control effect).

---

## 1. Pe scurt (pentru Proprietar)

- **Cine pune regulile.** Proprietarul: modul de autonomie, TEST sau PRODUCȚIE, STOP, regula
  plăților, bugetele, prețurile, conturile. Codul le aplică la fiecare pas; agenții lucrează înăuntru.
- **O singură ușă.** Orice întrebare către un model trece prin aceeași funcție, care verifică întâi
  STOP, modul, plafonul de tokeni și bugetul. Cu STOP apăsat, niciun agent nu mai lucrează.
- **Cât e model.** Din 3.951 de funcții, doar 37 întreabă un model (4% din cod); 82% din cod nu
  atinge niciodată un model. Din 915 decizii importante: 64% reguli fixe, 14% ale Proprietarului,
  7% setări, 5% furnizori, 11% cu model (4% luate de la model fără verificarea conținutului).
- **Ce face modelul.** Scrie (subiecte, scenarii, episoade, descrieri de imagini, titluri, scrisori),
  judecă imagini, clipuri, filme și povești, alege între variante pregătite de cod.
- **Ce nu face.** Nu cumpără nimic singur; nu atinge banii, GPU-ul, programul zilei sau încărcarea pe
  YouTube. Orice cumpărare trece prin permisiunea Proprietarului, buget, plafonul filmului și sold.
- **Unde contează modelul: calitatea.** Directoarea (Sarah) acceptă sau repară un film căzut la
  control (cel mult 5 refaceri pe scenă, 20 pe film), poate aproba o imagine refuzată și poate respinge
  un film. În 5 locuri răspunsul modelului e final. Un „nu" al lui poate porni o recumpărare, dar numai
  în limitele de bani.
- **Ce nu poate Directoarea.** Nu pornește ziua, nu repornește programul, nu schimbă modul, STOP,
  bugetele sau regula plăților, nu acceptă un film cu probleme de drepturi, de fapte sau de licență.
- **Două excepții.** Cercetarea de modele poate schimba modelul implicit de imagine, video sau voce,
  doar unde Proprietarul a lăsat pornită această permisiune. Biroul de reparații poate muta un angajat
  pe alt model când modelul lui nu mai răspunde (cel mult o dată pe zi).
- **Unde decide Proprietarul.** Setări, cele 26 de tipuri de carduri, aprobările de plată, „Pornește
  rularea de azi", „Oprește GPU acum", „Închide filmul", aprobările marcate „final".
- **Data hărții.** Codul din 12 octombrie 2026 (`b00083c`). După aceea a apărut al 38-lea loc cu
  model: Directoarea se mai uită o dată la o imagine refuzată înainte să se cumpere alta (secțiunea 8).

## 2. In short (for other AIs)

- **One door.** Every language-model call leaves through `app.agents.services.run_agent_task`
  (`backend/app/agents/services.py:733`). Before the provider is called it applies the daily token
  ceiling and the USD budget (`may_run_agent`, `backend/app/economy/accountant.py:1098`), then STOP
  AUTONOMY (`backend/app/agents/services.py:618-621`), `may_act('agent.run', 'T1')` (`:630`),
  lifecycle, model availability, one live run, required capabilities and provider health
  (`:608-679`). Four thin gateways sit on top: `structured_run` (`backend/app/agents/structured.py:76`),
  `run_with_strategy` (`backend/app/agents/ensemble.py:182`), `reviews._run`
  (`backend/app/agents/reviews.py:121`), `prompt_agent._run` (`backend/app/media/prompt_agent.py:2948`).
  No adapter offers tool calling (`backend/app/providers/base.py:58`): a model only returns text, and
  every side effect is a code path that validates that text first.
- **Static share** (`STATS.md`): 37 of 3,951 functions are LLM call sites (0.9 %), holding 5,012 of
  120,671 function lines (4.2 %). 151 functions (17.9 % of function lines) have any static path to
  a model; 82 % of function lines cannot reach one. The Policy Kernel (`app.services`), the
  decision cards, publishing, RunPod and the office have none.
- **Decision census** (`LLM_VS_RULES.md` §3, 915 decisions from the 18 verified subsystem maps):
  CODE_RULE 63.9 %, OWNER 13.9 %, CONFIG 6.6 %, EXTERNAL 4.9 %, LLM_CHECKED_BY_CODE 6.8 %, LLM 3.9 %.
  A model is involved in 10.7 %; OWNER + CODE_RULE is 77.8 %.
- **Trust of the 37 call sites** (reference tally, `LLM_CALL_SITES.md` §1 and §6): CHECKED_BY_CODE 24,
  FINAL 5 (`review_rewrite`, `evaluate_pictures`, `review_bought_pictures`, `editorial_judgement.judge`,
  `editorial_review`), ADVISORY 5, INFORMATIONAL 3. `LLM_ROUTING.md` §9.2, `DECISION_AUTHORITY.md` §12
  and `RUNTIME_FLOW.md` §9 carry earlier tallies; each now points to the reference.
- **Money.** No model answer buys anything by itself. Every paid media step (stills, the hero test
  shot, motion, a one-scene redo; `PAID_MEDIA_STEPS`, `backend/app/services.py:606`) passes `may_act`
  (`backend/app/services.py:1410`) with the Owner's paid-media rule and a yes bound to the plan hash,
  the film's purchase lease, the vendor balance × margin, the film ceiling and a budget reservation
  (`backend/app/media/shooting_sheet.py:3193`, `:2048`, `:2632`, `:2726`;
  `backend/app/economy/budget.py:473`). 6 call sites can trigger or reopen such a purchase inside those
  gates; 15 shape what later steps buy; 16 cost tokens only (`LLM_CALL_SITES.md` §1).
- **Where the model has the last word: quality and content.** The Director's ACCEPT of a film that
  failed QC writes a PASSED report and can pass any measured failure that is not on the not-hers list
  (`NOT_YOURS_CHECKS`, `backend/app/media/director_qc.py:151`; refusal at
  `backend/app/runbook/stages.py:4466-4477`; report at `director_qc.py:1678-1735`). Her look can
  approve a candidate a code gate refused (`director_qc.py:2069-2161`). Her editorial REJECT closes a
  finished film (`backend/app/agents/editorial.py:518-521`). A vision "no" decides re-rolls (≤ 2,
  `backend/app/media/still_gate.py:185`), a clip retry (≤ 1, `backend/app/media/qc.py:2396`) and
  redos (≤ 5 per scene, ≤ 20 per film, `backend/app/config.py:314-315`), all inside the money gates.
  `LLM_VS_RULES.md` §6.4 lists every place where "the model proposes, the code governs" breaks.
- **The Owner.** The Owner is whoever holds the bearer token (`require_owner`,
  `backend/app/security.py:60`). Owner commands set STOP, TEST/PRODUCTION, the autonomy mode and the
  paid-media rule (`backend/app/models.py:35-68`; `backend/app/services.py:244`, `:382`, `:1636`,
  `:1816`), budgets, prices, connections and publish policies, and answer approvals and the 26 kinds
  of decision card (`DECISION_AUTHORITY.md` §3, §10). The daily clock is seeded dormant and only the
  Owner starts it (`backend/app/main.py:475-487`); no agent creates a day or restarts the process,
  and no model answer changes the mode, STOP, a budget or the paid-media rule
  (`DECISION_AUTHORITY.md` §8, §11). Two settings can change without an Owner press: the default
  media model, through model research where the Owner left `allow_production_override` on
  (`backend/app/media/model_research.py:417-455`), and an employee's model, through the repair
  desk's repair `switch_agent_model` when that model fails now (T2, once per employee per day,
  `switch_model`, `backend/app/agents/repairs/agent_health.py:601`).
- **Snapshot.** Mapped from commit `b00083c`. Four later commits add a 38th call site,
  `app.media.second_look._look`: the Director's second look at a refused still or clip before a
  re-roll or retry is bought (section 8).

## 3. Reading order for an AI new to the codebase

1. `AGENTS.md`, then `docs/architecture/README.md` and `docs/architecture/00_MASTER_PROMPT.md`: the
   normative rules this code implements. `docs/project/CURRENT_STATUS.md` and
   `docs/project/16_DECISION_LOG.md` give the dated reasons ("why") the code's docstrings refer to.
2. This file: section 2 (the shape), section 6 (the studio's words), section 8 (what changed after
   the map was made).
3. `LLM_VS_RULES.md` §1 and §6: how involved the model is, and where code governs and where it does
   not.
4. `RUNTIME_FLOW.md` §1-§4 (process, engine, daily skeleton), then §5 (the factual short) and §6
   (the Office Serial): what runs when, who acts at each step, where money is spent.
5. `DECISION_AUTHORITY.md` §1-§8: the Owner's commands, the Policy Kernel, money, the Director's
   authority and its limits.
6. `LLM_CALL_SITES.md` §1 and §7 (index), then the phase you need: every question put to a model.
7. `LLM_ROUTING.md` §2-§8: the eight employees, how each one's model is chosen, the gateway step
   by step, costs.
8. The subsystem files, in this order: 17 (app core, Policy Kernel) → 10 (agent core) → 09 (engine,
   runbook services) → 08 (daily stages) → 15 (research, facts, scripts) → 04 (prompts, rewrites) →
   05 (shooting sheet, money gates) → 06 (stills stage, GPU rounds) → 01 and 02 (assembler) → 03
   (quality control) → 07 (repair, cards, sound, router) → 11 (reviews, editorial, repair desk) → 16
   (serial, publishing) → 14 (decision cards, economy) → 12 (RunPod) → 13 (other providers,
   integrations) → 18 (office, analytics, YouTube, workforce).
   Every subsystem file has the same sections: *In one paragraph*, *Why it exists*, *Who decides
   here*, *LLM involvement*, *Hard rules and limits*, *Modules* (a table row per public function and
   per function of 25+ lines), *Connections*, *Owner touchpoints*, *Oddities and gaps* (09 adds *Money
   paths*). Read the first four and the last two; use *Modules* as reference.
9. For one function: find it in `inventory.json` (line, size, `llm_distance`, route), its callees in
   `callgraph.json`, then the code as mapped with `git show b00083c:<path>`.

## 4. Index of the map files

| File | What it holds |
|---|---|
| `README.md` | This entry point: summaries, reading order, index, package table, glossary, regeneration, snapshot delta, completeness check, metadata |
| `STATS.md` | Generated. Per-package counts (files, lines, functions, routes, call sites, LLM reach, prompt text) and the table of the 37 call sites |
| `inventory.json` | Generated. Every module (path, lines, docstring) and function (`name`, `line`, `lines`, `doc`, `route`, `async`, `long_text_chars`, `llm_distance`, `llm_callees`, `llm_call_site`, `llm_gateway`) |
| `callgraph.json` | Generated. Resolved internal call edges, caller → callees (2,377 callers, 7,233 edges) |
| `LLM_VS_RULES.md` | How involved the model is: static numbers and their limits, the 915-decision census per subsystem, trust census, per package, where the shape holds and breaks, the 13 riskiest LLM-dependent points |
| `LLM_CALL_SITES.md` | The 37 call sites by pipeline phase: speaker, question, answer schema, trust, what code does, failure handling, spend; paths the static graph misses; reconciliation of the tallies |
| `LLM_ROUTING.md` | The employees and their models, the nine layers that choose a model, providers and adapters, `run_agent_task` step by step, structured retries, ensembles, LLM cost, a read-only live usage snapshot, the older routing documents compared |
| `DECISION_AUTHORITY.md` | Who decides what and where it is enforced: Owner commands, modes, STOP, safe mode, environment, `may_act`, approvals, money and GPU gates, the Director's authority, start/stop/restart, the repair desk, the 26 card kinds, a 49-row authority matrix, spec divergences |
| `RUNTIME_FLOW.md` | Process start, stop and restart; the durable engine, watchdog and outbox; the daily-run skeleton; the factual short (F1-F70) and the Office Serial (E1-E13) step by step with Mermaid charts; work outside the daily run; invariants |
| `subsystems/01_media_assembler_part1.md` | `app.media.assembler` lines 1-8300: FFmpeg assembly, captions, narration takes, timeline, clip readiness, the bed under the voice, the licence ledger, `assemble_video_job`, audio repair |
| `subsystems/02_media_assembler_part2.md` | `app.media.assembler` lines 8300-16671: the motion staircase and hero gate, scene memory and holds, vendor task collection, RunPod shot rounds, intermediates, the one-scene redo |
| `subsystems/03_media_quality_control.md` | Stills gate, clip QC, finished-film QC, picture verdicts (three call sites), the Director's QC desk, the Owner's QC report, faces |
| `subsystems/04_media_prompts_rewrite.md` | Visual bible and shot prompts (call sites), prompt compiler and lint, the scene-rewrite ladder (brief, rewrite, review), series look, serial storyboards, sheet words |
| `subsystems/05_media_shooting_sheet_policy.md` | The 0-credit shooting sheet and its gate chain before every purchase, production policy and the per-scene model planner, cost plan, balance rule |
| `subsystems/06_media_execution.md` | Stills stage, GPU batch rounds, unsent RunPod work, media services and factory, audio toolchain, rehearsal, disk and storage, media tables |
| `subsystems/07_media_repair_cards_sound.md` | Sheet blocker repair, picture cards, film close, sound plan, music library, speaker voices, model research, mode guard, the media HTTP router |
| `subsystems/08_runbook_stages.md` | The daily run's stage runners: research to publish, the production staircase walk, the Director's ladder, failed-film decisions, film continuation |
| `subsystems/09_runbook_services_workflows.md` | `execute_daily_run`, preflight, weekly review, safe mode; the durable task queue, scheduler, worker, watchdog and its passes, outbox |
| `subsystems/10_agents_core.md` | `run_agent_task`, structured answers, identity, ensembles, model routing, vision, memory, letters and mail, the Director's inbox review and company loop |
| `subsystems/11_agents_reviews_repairs.md` | Role reviews (narration, failed render, failed QC, refused pictures, publication), editorial review and judgement loop, the self-repair desk |
| `subsystems/12_providers_runpod.md` | RunPod Serverless: GPU sessions and guard, batches, endpoints, weights, copy pod, pricing, the Owner's GPU page and hold |
| `subsystems/13_providers_integrations.md` | All other provider adapters (Ollama, Runway, OpenAI images, ComfyUI, ElevenLabs, YouTube, analytics, search), retry policy, the Settings connections, vault, discovery, model lifecycle |
| `subsystems/14_decisions_economy.md` | Owner decision cards and their appliers, budgets and reservations, prices, credits, the Accountant, provider costs, the retired VR$ ledger |
| `subsystems/15_factual_research.md` | Topic ideas, sources and retrieval, claim extraction and verification, grounding, script writing, story review |
| `subsystems/16_story_publishing.md` | The Office Serial engine (day log, public projection, episodes, review, canon, serial stage) and publishing (gate, uploads, licence release, serial identity) |
| `subsystems/17_app_core.md` | App factory and lifespan, settings, database, the Policy Kernel and Owner commands, approvals, snapshot and register, goal, operations, backup, demo, security, logging, wording |
| `subsystems/18_office_analytics_youtube_workforce.md` | The office view (world, sky, Unreal bridge, stream), analytics and performance, YouTube connections, workforce proposals |

## 5. Which subsystem file covers which backend package

Every one of the 245 files of the snapshot is owned by exactly one subsystem file (the assembler is
split between 01 and 02). "Sites" are LLM call sites; "model share" is the share of that group's
census decisions that involve a model (`LLM_VS_RULES.md` §3.2).

| Backend package / files | Files | Lines | Functions | Sites | Model share | Subsystem file |
|---|---:|---:|---:|---:|---:|---|
| `app.media.assembler`, lines 1-8300 | 1 | 16,671 (whole file) | 200 | 0 | 7.4 % | `01_media_assembler_part1.md` |
| `app.media.assembler`, lines 8300-16671 | (same) | | 138 | 0 | 13.2 % | `02_media_assembler_part2.md` |
| `app.media`: `qc`, `picture_qc`, `still_gate`, `director_qc`, `qc_report`, `fix_check`, `faces` | 7 | 10,719 | 249 | 3 | 27.5 % | `03_media_quality_control.md` |
| `app.media`: `prompt_agent`, `prompt_lint`, `scene_rewrite`, `sheet_words`, `sheet_story_repair`, `series_look`, `serial_storyboard` | 7 | 8,680 | 212 | 5 | 17.5 % | `04_media_prompts_rewrite.md` |
| `app.media`: `shooting_sheet`, `production_policy`, `cost_plan`, `balance_rule` | 4 | 8,579 | 207 | 0 | 1.7 % | `05_media_shooting_sheet_policy.md` |
| `app.media`: `stills_stage`, `gpu_batch`, `runpod_unsent`, `services`, `factory`, `toolchain`, `rehearsal`, `local_media`, `disk`, `storage`, `models`, `schemas`, `__init__` | 13 | 10,302 | 235 | 0 | 4.8 % | `06_media_execution.md` |
| `app.media`: `blocker_repair`, `sound_design`, `music_library`, `speaker_voices`, `model_research`, `mode_guard`, `film_close`, `answered_letters`, `cards`, `router` | 10 | 6,770 | 178 | 3 | 11.5 % | `07_media_repair_cards_sound.md` |
| `app.runbook`: `stages`, `models`, `__init__` | 3 | 6,505 | 93 | 0 | 19.6 % | `08_runbook_stages.md` |
| `app.runbook`: `services`, `preflight`, `weekly`, `router`; all of `app.workflows` (incl. `passes/*`) | 24 | 9,738 | 217 | 1 | 3.8 % | `09_runbook_services_workflows.md` |
| `app.agents`: `services`, `structured`, `identity`, `ensemble`, `vision`, `memory`, `messages`, `mail`, `director`, `command`, `history`, `language`, `models`, `router`, `schemas`, `seed_config`, `__init__` | 17 | 8,212 | 183 | 6 | 19.0 % | `10_agents_core.md` |
| `app.agents`: `reviews`, `editorial`, `editorial_judgement`, `repairs/*` | 11 | 6,806 | 178 | 8 | 28.9 % | `11_agents_reviews_repairs.md` |
| `app.providers.runpod` | 22 | 9,788 | 361 | 0 | 0 % | `12_providers_runpod.md` |
| `app.providers` (all but `runpod`), `app.integrations` | 32 | 9,759 | 293 | 1 | 2.1 % | `13_providers_integrations.md` |
| `app.decisions` (incl. `producers/*`), `app.economy` | 18 | 9,929 | 261 | 1 | 2.0 % | `14_decisions_economy.md` |
| `app.factual`, `app.research` | 16 | 6,880 | 160 | 7 | 23.1 % | `15_factual_research.md` |
| `app.story`, `app.publishing` | 16 | 9,743 | 257 | 2 | 12.8 % | `16_story_publishing.md` |
| Top-level `app` modules: `__init__`, `main`, `config`, `db`, `models`, `schemas`, `services`, `events_feed`, `goal`, `operations`, `backup`, `maintenance`, `demo`, `security`, `local_session`, `logging`, `page_build`, `registry_loader`, `wording` | 19 | 9,032 | 275 | 0 | 1.9 % | `17_app_core.md` |
| `app.office`, `app.analytics`, `app.youtube`, `app.workforce` | 25 | 8,413 | 254 | 0 | 0 % | `18_office_analytics_youtube_workforce.md` |
| **Total (snapshot `b00083c`)** | **245** | **156,526** | **3,951** | **37** | **10.7 %** | |
| Added after the snapshot: `app.media.second_look` | 1 | 763 | 16 (not in the committed inventory) | 1 | — | section 8 of this file |

## 6. Glossary of the studio's words

Lines are those of `b00083c`. Several words have two meanings in the code; both are given.

**People and authority**

| Term | Meaning in the code | Defined in |
|---|---|---|
| Owner | The human; in code, whoever presents the Owner bearer token. Owner-only services also check `issued_by == "owner"`. The policy row holds STOP, environment, mode and paid-media rule | `backend/app/security.py:60`; `backend/app/models.py:35`; `backend/app/services.py:1832-1836` |
| Director | The employee with role `Director` (persona Sarah, "she"): an LLM that chooses topics, reviews stories and films, decides failed QC, writes briefs, runs the company loop and the repair desk | `backend/app/agents/services.py:1082` (`_ROLE_DEFINITIONS`); `backend/app/agents/director.py:1`; `backend/app/agents/command.py:866` |
| employee, role, agent | An `Agent` row with a `Role` (contract, missions, required capabilities) and an assigned model; eight are seeded | `backend/app/agents/models.py:23`, `:111`; `config/workforce_seed.json`; `config/role_contracts.json` |
| LOOKERS | The roles whose seeing model judges pictures, in order: VideoEditor, Director, QualityAssurance (never seeded) | `backend/app/media/picture_qc.py:119` |
| identity | The system prompt composed for every run: who the employee is, the role contract, open letters, recalled memory | `backend/app/agents/identity.py:278` |
| run | One model call, recorded as an `AgentRun` (status, tokens, cost) | `backend/app/agents/models.py:147`; `backend/app/agents/services.py:733` |
| structured answer | A run whose JSON must validate against a schema; at most two attempts | `backend/app/agents/structured.py:76` |
| strategy, ensemble | Multi-model runs (REVIEW with a critic, fallback, parallel) for one employee; recorded as `LlmCollaboration` | `backend/app/agents/ensemble.py:182`; `backend/app/agents/models.py:182` |
| letter, intent | An `AgentMessage` between employees or to the Owner, with an intent: REQUEST_INFO, REQUEST_REVIEW, CHALLENGE, HANDOFF, STATUS, ESCALATE | `backend/app/agents/models.py:286`, `:255`; `backend/app/agents/messages.py:30` |
| memory, lesson | A `MemoryRecord` recalled into later prompts (STRATEGY, AGENT_OPINION...). A lesson is a picture-writing rule learned from a refused film and given to every prompt writer | `backend/app/agents/models.py:259`; `backend/app/agents/memory.py:42`, `:124`; `backend/app/media/prompt_agent.py:3050`, `:3088` |
| matter, company loop | A measured problem the Director's loop may assign, repair or escalate | `backend/app/agents/command.py:364`, `:866` |
| repair desk | The Director's registered self-repairs (seven, tiers T0-T2), each asked of the kernel before queueing and before applying | `backend/app/agents/repairs/desk.py:514` |
| card (decision card) | An `OwnerDecision`: a question only the Owner answers (ACCEPT / REFUSE / DONE); an accept runs an Owner command through an applier. 26 kinds | `backend/app/decisions/models.py:25`; `backend/app/decisions/services.py:438`, `:826`, `:1174` |
| approval | An `ApprovalRequest` for one action on one subject (often a plan hash): asked, answered once, spent once | `backend/app/models.py:71`; `backend/app/services.py:1031`, `:1284` |
| Policy Kernel, `may_act` | The deterministic function that says whether the studio may attempt an act: STOP, risk tier, safe mode, paid-media rule, budget, mode | `backend/app/services.py:1410` |
| risk tier T0-T4 | The class of an action; each mode allows up to a tier (MANUAL T1, SUPERVISED T2, AUTONOMOUS_CEO T3); T4 is always refused | `backend/app/services.py:467`, `:528` |
| STOP (AUTONOMIE OPRITĂ) | The Owner's global stop: every autonomous act and every model run is refused; switching the GPU off stays allowed | `backend/app/models.py:41`; `backend/app/services.py:382` |
| autonomy mode | MANUAL, SUPERVISED or AUTONOMOUS_CEO | `backend/app/models.py:55-57`; `backend/app/services.py:1636` |
| environment | TEST or PRODUCTION; PRODUCTION allows real vendors and the shooting-sheet path | `backend/app/models.py:47`; `backend/app/services.py:244` |
| paid-media rule | When a paid media step asks the Owner: EVERY_PAID_STEP, OVER_USD (with a threshold) or MODE | `backend/app/models.py:65-68`; `backend/app/services.py:606`, `:1816` |
| safe mode | Opened by code on a hard fault in media, publish or daily log, or on a database integrity doubt; sets STOP; only the Owner clears it, with a note | `backend/app/runbook/models.py:51`; `backend/app/runbook/services.py:657`, `:708` |
| command, `command_id` | A versioned, idempotent Owner command, remembered so a repeat returns the first answer | `backend/app/models.py:148` |
| event | A `DomainEvent` in the append-only record | `backend/app/models.py:126` |
| Director decision | A `DirectorDecision` row recording what her loop decided on a matter | `backend/app/analytics/models.py:164` |

**Money**

| Term | Meaning in the code | Defined in |
|---|---|---|
| micros | Every amount is an integer of millionths (1 USD = 1,000,000) | `backend/app/economy/models.py:43` |
| VR, VR$ | "Virtual Real" dollars of the Phase 11 ledger, anchored 1:1 to verified USD; the ledger is retired as a product, but `cost_vr` columns and `llm_cost_vr` still carry run costs | `backend/app/economy/models.py:1-17`, `:42`; `backend/app/economy/prices.py:261` |
| credits | A vendor's unit (Runway: about 100 per USD on the Owner's account); priced from `config/runway_prices.json`, converted to micros, measured from balance drops | `backend/app/media/cost_plan.py:295`; `backend/app/economy/credits.py:114` |
| price (`ProviderPrice`) | A price the Owner typed (or a documented seed); the only source of LLM token costs | `backend/app/economy/models.py:371`; `backend/app/economy/prices.py:1-25` |
| budget | An Owner `SpendingBudget` (DAILY, MONTHLY) in USD; an exceeded budget stops model runs and purchases | `backend/app/economy/models.py:327`; `backend/app/economy/budget.py:150`, `:457` |
| reservation (budget hold) | A `SpendReservation` taken behind the write lock before a step buys, released or booked after | `backend/app/economy/models.py:417`; `backend/app/economy/budget.py:473`; `backend/app/media/shooting_sheet.py:2726` |
| film ceiling | The most one film may cost before the Owner consents to more | `backend/app/media/shooting_sheet.py:2632` |
| balance margin | A step starts only when the vendor balance holds its next round × 1.15 | `backend/app/media/balance_rule.py:39`; `backend/app/config.py:286` |
| plan hash | The SHA-256 of a step's exact plan (prompts, models, cost, cap); an Owner yes is bound to it and spent once | `backend/app/media/stills_stage.py:564`; `backend/app/media/assembler.py:9463`, `:13716`; `backend/app/media/shooting_sheet.py:1837` |
| lease (film purchase lease) | One buyer per film at a time: a renewable `FilmPurchaseLease` | `backend/app/media/models.py:254`; `backend/app/media/shooting_sheet.py:2048` |
| lease (task lease) | A worker's claim on a queued task (`lease_token`, `lease_expires_at`) | `backend/app/workflows/models.py:56`; `backend/app/workflows/services.py:333` |

**Films and media**

| Term | Meaning in the code | Defined in |
|---|---|---|
| storyboard, scene | A film (`Storyboard`) and its numbered scenes; a scene kind is LIVE, DATA_CARD, TITLE_CARD or BLACK (only LIVE reaches an image or video model) | `backend/app/media/models.py:91`, `:132`, `:23` |
| card (picture card) | A DATA_CARD or TITLE_CARD scene the studio draws itself for 0 credits (chart, title, black) | `backend/app/media/cards.py:1`, `:924` |
| visual bible | The film's one look in plain words (style, palette, light, face rule), written by the Video Editor's model and stored on the storyboard | `backend/app/media/models.py:118`; `backend/app/media/prompt_agent.py:987` |
| shot plan, shot package | The per-scene prompt package (subject, action, camera move, ending frame) the Video Editor's model writes; the compiler turns it into vendor prompts, the lint checks them | `backend/app/media/prompt_agent.py:1081`, `:2779`; `backend/app/media/prompt_lint.py:1112`, `:1248` |
| shooting sheet | The 0-credit plan of a film's paid steps (stills, test shot, motion) with prices and its own `sheet_hash`; each step runs behind a fixed gate chain | `backend/app/media/shooting_sheet.py:192`, `:1790`, `:1837`, `:3193` |
| take | One bought (or quoted) result for a scene: a `SceneTake` of kind still, motion, test_shot or narration, with status QUOTED, SUBMITTED, PAID, APPROVED, REJECTED, REFUSED or LOST | `backend/app/media/models.py:174`, `:28-37` |
| still | A generated image for a LIVE scene; the first paid stair | `backend/app/media/stills_stage.py:186` |
| motion, clip | A video bought from a still (a take of kind motion); "clip" is the bought file | `backend/app/media/assembler.py:8072`, `:11367` |
| test shot, hero | The film's first motion purchase; the rest of the motion opens only after it is accepted (hero gate) | `backend/app/media/assembler.py:8071`, `:9917` |
| staircase, stair | The ordered paid steps of one film (stills → hero test shot → motion → assembly), walked one answered stair at a time | `backend/app/runbook/stages.py:1504`, `:1707`, `:2738` |
| SUBMITTED, LOST | A vendor task accepted but not yet collected (never bought again, only collected); LOST if never collected in time | `backend/app/media/models.py:24-29`; `backend/app/media/assembler.py:10615` |
| hold, NEEDS_OWNER, STUDIO_DEFECT | A scene the studio will not buy again until a decision (the Owner's, or the Director's rewrite) releases it; STUDIO_DEFECT is a hold caused by the studio's own malformed request | `backend/app/media/assembler.py:8715`, `:8480`, `:8886` |
| LOCAL_MOVE | The Owner's per-scene choice to animate a still locally instead of buying motion | `backend/app/media/production_policy.py:2058` |
| redo | Buying one scene again (still, motion or both) under its own plan hash and the kernel's `media.scene_redo` | `backend/app/media/assembler.py:14935`, `:13716` |
| re-roll | A new still candidate after the stills gate refused one (at most 2) | `backend/app/media/still_gate.py:185`, `:1035` |
| retry (clip) | One more purchase of a refused clip on the same model, seed + 1 (at most 1, inside the cap) | `backend/app/media/qc.py:2396`, `:2477` |
| round | One batch of purchases inside one RunPod GPU session | `backend/app/media/gpu_batch.py:278`; `backend/app/media/stills_stage.py:1119`; `backend/app/media/assembler.py:10937` |
| rung, ladder | The Director's rewrite ladder for a QC-refused scene: brief → the Video Editor's rewrite → her review; up to 3 rungs per walk | `backend/app/runbook/stages.py:1609`, `:1668`; `backend/app/media/scene_rewrite.py:2264` |
| brief | The Director's diagnosis of a refused scene and the layer (still or motion) to change | `backend/app/media/scene_rewrite.py:171`, `:837` |
| rewrite review | Her TREATS or MISSES verdict on the rewritten prompts, per QC finding | `backend/app/media/scene_rewrite.py:227`, `:1067` |
| narration take, sound plan | The voiced narration bought once and kept as a take; the Voice Artist's plan for the music bed under the voice | `backend/app/media/models.py:28`; `backend/app/media/sound_design.py:379` |
| intermediates | Working files of a film, deleted once its QC report exists | `backend/app/media/assembler.py:12484` |
| licence ledger | The per-component record of the terms each part was bought under; a film is LICENSED only when every part carries a commercial-use yes | `backend/app/media/assembler.py:6208` |
| close a film | The Owner's «Închide filmul»: nothing more is bought or rewritten for it | `backend/app/media/film_close.py:526`; `backend/app/media/shooting_sheet.py:1954` |

**Quality**

| Term | Meaning in the code | Defined in |
|---|---|---|
| gate | A check that decides on its own. Main ones: the stills gate, the hero gate, the factual gate, the story gate, the publishing gate (7 checks) | `backend/app/media/still_gate.py:849`; `backend/app/media/assembler.py:9917`; `backend/app/factual/services.py:353`; `backend/app/factual/story_review.py:649`; `backend/app/publishing/services.py:984` |
| QC, QC report | Measured and vision checks of a still, a clip or a finished film; the film's result is a `QualityControlReport` | `backend/app/media/qc.py:924`, `:2134`; `backend/app/media/models.py:341` |
| ACCEPT, REPAIR | The Director's decision on a film that failed QC; not-hers findings cannot be accepted | `backend/app/runbook/stages.py:4041`; `backend/app/agents/reviews.py:981`; `backend/app/media/director_qc.py:151` |
| final (approval) | An Owner approval marked final; no repair retires it | `backend/app/media/assembler.py:9698` |
| editorial review, editorial judgement | The Director's last look before publishing (APPROVE/REJECT); and her 0-10 scores on five criteria that pick the version that ships (bar 35/50) | `backend/app/agents/editorial.py:400`; `backend/app/agents/editorial_judgement.py:278`, `:410`, `:640` |
| PASS (verdict) | A story-review or episode-review verdict; not the same as a watchdog or worker "pass" (Machinery) | `backend/app/factual/story_review.py:312`; `backend/app/story/review.py:946` |

**Facts, story and publishing**

| Term | Meaning in the code | Defined in |
|---|---|---|
| topic idea | A candidate subject with self-scores, proposed by the Lead Researcher's model and filtered by code | `backend/app/factual/models.py:21` |
| source, claim | A fetched page (`SourceSnapshot`) and an atomic claim from it (`FactualClaim`), UNVERIFIED until another agent quotes the source verbatim | `backend/app/factual/models.py:63`, `:87` |
| script, story review | A `ScriptDraft` written only from SUPPORTED claims, and its computed plus Director review | `backend/app/factual/models.py:123`, `:165` |
| Office Serial, serial | The second channel's daily animated episode about the studio's own day | `backend/app/story/serial_stage.py:542`; `backend/app/goal.py:30` |
| day log, projection | The frozen `DailyStudioLog` of a business day, and its redacted PUBLIC_SAFE projection the writer may use | `backend/app/story/models.py:24`; `backend/app/story/projection.py:460` |
| episode | A `StoryEpisode` drafted, reviewed and approved (by the Director only if the Owner's channel policy allows it) | `backend/app/story/models.py:60`; `backend/app/story/services.py:1520`, `:1774` |
| canon | The serial's memory (`ContinuityState`), advanced only on approval | `backend/app/story/models.py:107` |
| channel, publish policy | A `ChannelRecord` (MAIN_FACTUAL or OFFICE_SERIAL) and the Owner's versioned visibility policy | `backend/app/publishing/models.py:11`; `backend/app/publishing/services.py:352` |
| Publisher HOLD | The Publisher's refusal of its own metadata, sent as a letter; publication waits while that letter is open, and any resolution of it lifts the hold (`DECISION_AUTHORITY.md` §7) | `backend/app/agents/reviews.py:1485` |
| licence release | An upload held private only for its licence, made public once the licence is confirmed | `backend/app/publishing/licence_release.py:111`, `:201` |

**Machinery and GPU**

| Term | Meaning in the code | Defined in |
|---|---|---|
| daily run, stage | A `DailyRun` walking 13 stages in order, each gated by the mode | `backend/app/runbook/models.py:11`; `backend/app/runbook/services.py:76`, `:1359`; `backend/app/runbook/stages.py:256` |
| FILM_CONTINUE | A queued task that walks one film on right after the Owner's yes | `backend/app/workflows/worker.py:129`; `backend/app/runbook/stages.py:5430` |
| task queue, worker | Durable SQLite tasks claimed under a lease by one worker per database (OS file lock) | `backend/app/workflows/models.py:56`; `backend/app/workflows/services.py:277`, `:333`; `backend/app/workflows/worker.py:815` |
| pass (worker pass) | One loop of the worker every 30 s: sweep, sheet scan, scheduler tick, up to 3 tasks, a mail round | `backend/app/workflows/worker.py:721` |
| pass (watchdog pass) | A self-registering repair run by the 10-minute watchdog after its built-in parts | `backend/app/workflows/passes/__init__.py:115`, `:139`; `backend/app/workflows/watchdog.py:803` |
| outbox | `OutboxRecord` rows committed with their events and broadcast to the page's socket afterwards | `backend/app/workflows/models.py:114` |
| register | The live record as sentences for the Owner (who did what, on which film) | `backend/app/events_feed.py:1` |
| goal | The day's tally per channel: published, in work, blocked and whose | `backend/app/goal.py:1` |
| GPU session | One open RunPod Serverless session for one paid step: precheck, open (workers.max=1), close (verified off) | `backend/app/providers/runpod/gpu_session.py:237`, `:701`, `:890`, `:1274` |
| GPU hold | The Owner's «Oprește GPU acum»: recorded before the forced off, lifted only by the card | `backend/app/providers/runpod/gpu_session.py:795`; `backend/app/providers/runpod/router.py:87-99` |
| endpoint | A RunPod Serverless endpoint read and switched through the REST API | `backend/app/providers/runpod/endpoint.py:1` |
| weights card, copy pod | The card raised when an endpoint's worker reports other model weights; the temporary pod that copies models to the Owner's Hugging Face account | `backend/app/decisions/sources.py:399`; `backend/app/providers/runpod/weights.py:232`; `backend/app/providers/runpod/pods.py:654` |
| unsent | A RunPod `/run` that may not have reached the queue; released by proof or by the Owner's card | `backend/app/media/runpod_unsent.py:886`; `backend/app/media/assembler.py:8974` |
| steward, model research | The Video Editor or Voice Artist reading vendor pages to score models and recommend a default | `backend/app/media/model_research.py:205` |

## 7. Regenerating the generated files, and the limits of the analysis

```
uv run python scripts/backend_map.py
```

writes `inventory.json`, `callgraph.json` and `STATS.md` in this folder
(`scripts/backend_map.py:1-24`, output at `:267-293`). Never edit those three by hand. The other
files are written by people and agents and must be updated by hand when the code changes. Running
the script on today's tree changes the numbers (section 8), so the narrative files would then need
re-checking.

How the script works and what it cannot see:

1. **What counts as a function.** Module-level functions, methods of top-level classes, and nested
   functions decorated as HTTP routes (`@x.get("...")` etc.) are entries (`scripts/backend_map.py:90-122`).
   Other nested functions (closures, lifespan loops, inner helpers, methods of nested classes) are
   not separate entries; their code and calls belong to the enclosing function. Group 18 found 17
   such nested functions in its scope, and group 17 maps the closures of `main.create_app` by hand.
2. **Lines.** A function's `lines` run from its `def` to its last line, docstring included. A nested
   route handler's lines are counted in its factory too, so the total of function lines (120,671)
   counts those twice.
3. **Call resolution is by name**: imports, `self.`/`cls.` methods, top-level classes and dotted
   module paths (`:151-187`). Any reference to a known function in load context is an edge, so a
   function passed as a value (a callback, `partial(...)`) counts. Calls through objects whose type is
   not visible (a provider instance, a registry, a dict of handlers, the task queue, `getattr`) are
   **not** resolved.
4. **`llm_distance`** is a breadth-first distance on the reversed graph from `run_agent_task`
   (`:231-243`). It over-counts (a whole function counts if one branch reaches a model, for example
   `app.main.create_app`) and under-counts (dynamic dispatch). `LLM_CALL_SITES.md` §5 lists the
   paths found by hand, such as the worker's `DIRECTOR_REPAIR` handler reaching the model probe, the
   GPU round's `on_outcome` callback reaching the vision judges, and the editorial-loop rewrite
   callbacks. Some static paths are not taken at runtime (for example `rehearse` passes no
   registry, `storyboard_from_episode` passes `registry=None`).
5. **`llm_call_site`** means "calls one of the five gateway functions itself"
   (`LLM_GATEWAY`, `:37-46`). If a gateway is renamed the script stops instead of silently reporting
   no LLM (`:197-199`). A call site's lines include all the code that checks the answer.
6. **"Prompt/message text"** counts string constants of 160+ characters inside functions,
   docstrings included, and misses module-level prompt templates (`:206-219`; `LLM_VS_RULES.md` §2).
7. **The census and trust labels are human judgement**, made by eighteen verifying groups and
   reconciled in `LLM_CALL_SITES.md` §6 and `LLM_VS_RULES.md` §3.3; they are not generated.
8. **Live state is not code.** `LLM_ROUTING.md` §3.2 and §11 read the live database read-only on
   2026-10-12 (newest run 13:52 UTC). Settings, open cards and model assignments change; re-read
   them before relying on them.

## 8. Snapshot, and what changed after it

The map was generated at 18:00 on 2026-10-12 (`STATS.md`, `inventory.json`) from the backend of
commit `b00083c`; it was verified against HEAD `3d49e9a`, whose backend is identical. Four commits
were made afterwards (all committed at 18:59 the same day). They touch eleven mapped files and add
one file:

| Commit | Subject (abridged) | Backend files (lines at `b00083c` → now) | Map files whose line numbers moved |
|---|---|---|---|
| `68fa0b4` | A correcting lesson replaces the one it corrects; each kind of film keeps its own lessons; an unproven lesson says so | `media/prompt_agent.py` 3249 → 3695; `agents/editorial.py` 594 → 629; `story/services.py` 1843 → 1882; `events_feed.py` 1267 → 1377 | 04, 11, 16, 17 |
| `a50407e` | The rewrite review answers QC's findings by id, knows which words each layer keeps, turns to the still when the motion layer is exhausted | `media/scene_rewrite.py` 2363 → 3147 | 04 |
| `5fc7468` | Each finding is checked on its layer in QC's own words; a small trace is accepted; the Director looks before any re-roll or retry is bought | `media/fix_check.py` 181 → 793; `media/qc.py` 3996 → 4204; `media/picture_qc.py` 2048 → 2221; `media/still_gate.py` 1067 → 1213; `media/stills_stage.py` 2269 → 2544; `media/assembler.py` 16671 → 16716 | 01, 02, 03, 06 |
| `20abffd` | The Director looks again at a picture QC refused before a redo is bought | new `media/second_look.py` (763) | none (new file) |

Each affected subsystem file now carries an "After the snapshot" note under its header. Run on the
tree as it is now (`20abffd`), the generator gives 246 files, 160,162 lines, 4,078 functions,
**38** call sites holding 5,183 lines, 20 functions that call `run_agent_task` directly, and
162 functions (22,406 lines, 18 %) with a static path to a model. These figures come from running
`scripts/backend_map.py` with its output sent to a scratch folder; the committed generated files
were not rewritten. Call sites whose definition line moved: `editorial_review` 400 → 428,
`judge_still` 1668 → 1765, `judge_clip` 1929 → 2074, `build_visual_bible` 987 → 1018,
`write_shot_prompts` 1081 → 1113, `director_brief` 837 → 1335, `review_rewrite` 1067 → 1650,
`_editor_rewrite` 1279 → 1847, `write_episode` 1520 → 1558.

**The 38th call site: `app.media.second_look._look`** (lines below are those of `20abffd`).

- *Why it exists.* On 2026-10-12, 19.50 USD went to RunPod in one day, 11.05 USD of it on redos,
  and every refusal behind them bought the next still or clip without anyone checking that the
  refusal was right. The Owner asked that QC's refused pictures go through the Director first,
  because a look costs nothing and a redo costs credits (`backend/app/media/second_look.py:1-33`).
- *What it does.* `second_look` (`:583`) shows the Director the refused picture (one still, or the
  first, middle and last frames of a clip) with QC's own words, the scene's intent, the bible's rules
  and her earlier looks at the scene. She is asked on her seeing model (`agent_for_role`, `:682`;
  `seeing_model`, `:686`) through `structured_run` (`:720`, task `director_second_look`, 2000
  tokens). Her answer `SecondLook` (`:88-135`) is validated for consistency only: OVERTURNED is never
  serious and never redoes; CONFIRMED always redoes and names a defect. No seeing model, no registry,
  two invalid answers or any error give UNAVAILABLE, and the refusal stands. Every look writes a
  `media.director_second_look` event and an AGENT_OPINION memory (`_record`, `:515-569`). It buys nothing.
- *Who calls it.* `fix_check.director_second_look` (`backend/app/media/fix_check.py:642`) and
  `shot_second_look` (`:713`). For stills: `stills_stage._director_looks`
  (`backend/app/media/stills_stage.py:1038`), before a paid re-roll, on candidates
  `still_gate.may_be_overturned` allows (`backend/app/media/still_gate.py:1118`). For clips:
  `assembler._check_shot` (`backend/app/media/assembler.py:10245`, look at `:10336`) through
  `qc.qc_clip_with_retry`, on refusals `qc.look_may_overturn` allows (`backend/app/media/qc.py:2588`).
  The kind `film_scene` is used only by the offline audit `scripts/qc_audit.py`, not by the backend.
- *Who decides.* Code decides which refusals she may see. Faces where the bible forbids them,
  writing, panels and degenerate pictures (`HARD_LIMITS`, `backend/app/media/fix_check.py:130`),
  unmeasured checks and `compose_locally` stay the code's. Within that set her verdict is
  **LLM / FINAL**. When `fix_check.look_accepts` (`:693`) holds, the still is set APPROVED with
  `approved_by = "director_look"` (`backend/app/media/stills_stage.py:1017-1035`), or the clip is kept
  as ACCEPTED_BY_LOOK (`backend/app/media/qc.py:2671-2684`), and nothing more is bought for it. A
  CONFIRMED verdict lets the purchase go on under the unchanged money gates, with her reason recorded.
  Her answer can only withhold spending; it never adds a purchase. This adds one more place where a
  model's judgement overrides a QC refusal (compare `LLM_VS_RULES.md` §6.4 point 2), and one more
  writer of APPROVED besides the Owner (compare the oddities of `subsystems/01_media_assembler_part1.md`).

The other changes (layer-scoped findings in `fix_check`, the rewrite review's finding ids and
severities, scoped and superseding lessons, the register's new sentences) refine behaviour already
mapped in subsystems 03, 04, 06 and 17; their line numbers there are those of `b00083c`.

## 9. Completeness check (run 2026-10-12 against `b00083c` and HEAD `20abffd`)

What was checked, and the result:

1. **Subsystem files exist and are substantial.** All 18 exist, 500-1,071 lines (81-109 KB) each,
   with the same section structure (section 3, item 8).
2. **Every backend file is mapped.** All 245 files of the snapshot appear in a subsystem file, each
   under exactly one owner (the assembler split between 01 and 02); package `__init__` files are named
   in their package's file. The post-snapshot `second_look.py` is mapped only in section 8 here.
3. **Every function is named.** 3,938 of 3,951 inventory functions are named in the file that owns
   their module, and all 1,348 functions of 25 or more lines are. The 13 not named are helpers of
   2-16 lines: `repairs.desk._now`, `qc.FallbackNotChosen.__init__`,
   `unreal._without_rehearsal.__getattr__`, `world._julian_century`, `world._zone`,
   `retrieval._PageText.handle_endtag` and `.handle_data`, `story.review.EpisodeVerdict._rubric_only`,
   `story.services._Line._as_written`, `_Beat._dialogue_as_lines`, and the three
   `workflows.router` pause/resume/cancel handlers, which `09_runbook_services_workflows.md` documents
   by route path.
4. **Every call site is catalogued.** All 37 functions with `llm_call_site` true appear, at their
   definition line, in `LLM_CALL_SITES.md`, `LLM_ROUTING.md` §9 and `DECISION_AUTHORITY.md` §12, and in
   the subsystem file that owns their module. Per group: 03 has 3, 04 5, 07 3, 09 1, 10 6, 11 8, 13 1,
   14 1, 15 7, 16 2, the rest 0; total 37.
5. **Numbers match.** The figures in `LLM_VS_RULES.md` §1, §2 and §5, the summaries above, and the
   global figures in `LLM_ROUTING.md`, `DECISION_AUTHORITY.md` and `RUNTIME_FLOW.md` were recomputed
   from `inventory.json`: 3,951 functions, 120,671 function lines, 37 sites / 5,012 lines, 20 direct
   / 2,353 lines, 60 within two hops, 151 reaching / 21,571 lines, and the per-package lines and
   percentages. They match `STATS.md`. Module headers' line counts in the subsystem files match the
   inventory.
6. **Citations resolve.** The map contains no Markdown links. Every path it names exists: 34
   `docs/` files, 241 `backend/app/` files, 53 `scripts/`, `tests/`, `config/` and `frontend/` files.
   5,865 `file:line` citations (in the map files other than this README) to uniquely identifiable
   backend files were checked against the file's length at `b00083c`; one was out of range and is
   fixed. Section 8 of this README cites lines of `20abffd` on purpose.

Issues fixed by this check: the out-of-range citation in `LLM_ROUTING.md` §3.1
(`integrations/services.py:534-662` → `:534-661`); a wrong cross-reference in
`subsystems/02_media_assembler_part2.md` (part 1 is `01_media_assembler_part1.md`); reference-tally
notes in `LLM_ROUTING.md` §1 and §9.2, `DECISION_AUTHORITY.md` §1 and §12 and `RUNTIME_FLOW.md` §9,
which carried trust tallies that disagree with the reconciled one; "After the snapshot" notes in
subsystems 01, 02, 03, 04 (whose "every line number below holds" was no longer true), 06, 11, 16
and 17; snapshot notes in `LLM_CALL_SITES.md` §1 and `LLM_VS_RULES.md` §9; this README.

Issues that remain:

- The generated files describe `b00083c`, not the current tree; `second_look.py` and the 38th call
  site are described only here, and the call-site counts elsewhere stay at 37.
- Line numbers in eleven backend files moved after the snapshot (section 8); citations into them are
  correct only for `b00083c`.
- `RUNTIME_FLOW.md` §10 counts schema-only steps with its own labels (F8, F20), not with the
  reconciled ones.
- The census is a judgement over the decisions the groups chose; a few decisions are counted in two
  groups and labels drift at the Owner/code border (`LLM_VS_RULES.md` §3.3).
- The cross-cutting files were written from the verified groups and re-checked in the code where
  disputed; unlike the 18 subsystem files, they had no separate adversarial verification pass.

## 10. Map metadata

Mapped 2026-10-12 from commit `b00083c` plus working tree (branch `codex/simple-pixel-studio`;
generated files at 18:00; verified against HEAD `3d49e9a`, whose backend is identical; this README
and its completeness check written against HEAD `20abffd`, section 8). Verification verdicts per
group (adversarial check against the code; corrections folded in): 01 FIXED (18 corrections),
02 FIXED (20), 03 FIXED (22), 04 FIXED (24), 05 FIXED (18), 06 FIXED (21), 07 FIXED (22),
08 FIXED (21), 09 FIXED (18), 10 FIXED (24), 11 FIXED (23), 12 FIXED (18), 13 FIXED (16),
14 FIXED (25), 15 FIXED (18), 16 FIXED (23), 17 FIXED (19), 18 FIXED (20): 18 of 18 groups FIXED,
370 corrections in all. Cross-cutting files (`LLM_ROUTING.md`, `DECISION_AUTHORITY.md`,
`RUNTIME_FLOW.md`, `LLM_CALL_SITES.md`, `LLM_VS_RULES.md`) were synthesised from the verified groups;
trust labels are reconciled in `LLM_CALL_SITES.md` §6. Nothing was run against the studio, a model,
a provider or the network; the live database was read, read-only, for `LLM_ROUTING.md` §3.2 and §11.
