# CURRENT STATUS — Phases 0-2 complete; Phases 4-6 partially implemented

Last verified: 2026-09-09 by an independent audit (`AUDIT_2026-09-09_EXTERNAL.md`) and the
remediation that followed it. Active edit claim: Codex, 2026-09-11 — ElevenLabs authentication,
database resource discovery/refresh, separate production choices, UI and regression tests.

> **Correction notice (2026-09-09).** An earlier revision of this document declared Phases 4, 5 An earlier revision of this document declared Phases 4, 5
> and 6 "complete — verified". That was not supported by the code. The audit found fabricated
> channel configuration, simulated uploads recorded as real YouTube publications, a
> non-playable file written with an `.mp4` name, a QC gate that verified its own metadata
> instead of the file, and a demo endpoint that inserted a self-authored "SUPPORTED" claim.
> Those defects are fixed; the phases they belonged to are now marked partial, because the
> providers their acceptance criteria require still do not exist. Sections below state what is
> actually true.

## An employee may think with more than one model (2026-09-12)

Every agent now has an optional second and third model beside its primary, from the same
registry, with a strategy that says what to do with them: single, fallback, review, debate or
parallel (migration 0034). No model is named in the studio's logic — a test scans the backend
and fails if one is — so any slot can be replaced from Settings without a code change. Extra
models are spent only where the agent's own policy says the task earns them, and the reason is
recorded. In review, debate and parallel the answer acted on is always a run on the employee's
own model: a critic advises and cannot publish, command or decide. A review that could not be
done is recorded as incomplete rather than filled in, and the Director's decision then carries
low confidence. The Owner's current allocation lives in `config/workforce_seed.json`: the
Director with a strategic critic, everyone else single. The report is `MULTI_LLM.md`.

## The company is managed, not only measured (2026-09-12)

The Director now answers where the company stands, what is preventing growth and who acts next
(migration 0033). Performance is normalised per film — views per hour, subscriber conversion,
cost and production time on the same row — and judged against the channel's own rolling median,
never an absolute number: a verdict needs three measured films, a day of age and a rate, or the
answer is INSUFFICIENT_DATA. A diagnosis separates reach from retention from conversion and
names the department that can fix it. Her pass runs every six hours on the existing scheduler,
assigns at most three things through the existing mailbox with a review condition on each,
never raises a matter already in hand, and sends STOP and SCALE to the Owner. Each decision is
a row the database refuses to accept without a review condition, and it comes back when the
films it was waiting for have been published. Verified on a copy of the live database: it found
the real bottleneck, six films through quality control and none published. The report is
`DIRECTOR_COMMAND.md`.

## The content decides, before the generation (2026-09-12)

A film now has to be worth making before it can be made. A topic carries an argument — the
fact, why it matters, the payoff, the hook, the ending, a call to action — scored on twelve
weighted editorial dimensions, and an idea that fails the rules is kept with its reasons. A
script carries its story and declares the part every scene plays. Before anything is
generated, the story is reviewed: computed checks for hook, progression, payoff, ending, CTA
and pacing, plus the Director's estimate of where a viewer would stop watching; a script that
is sent back is rewritten once. The render and the prompt agent both refuse a film whose story
has not passed. Then one master visual bible and a full prompt package per shot replace the
single line that used to be sent to a model at 2.60 USD a shot — the same package in both
environments, because TEST saves money on the model, not on the thinking. The report is
`EDITORIAL_PIPELINE.md`.

## Two environments, decided by the studio (2026-09-12)

The studio knows whether it is testing or publishing (`owner_policy.environment`, migration
0031), and that decides which policy chooses each scene's model: in TEST the cheapest
compatible model under a cost ceiling per generation and per second, in PRODUCTION the least
expensive model that reaches the quality the scene's part in the film requires. The
environment is server-side state changed only by the Owner's versioned command; the page
displays it and asks for a change. A model now carries a standing it has to earn
(DISCOVERED → … → PREFERRED) and cannot film anything that will be published until its own
recorded results admit it. Prices carry their provenance — documented, quoted, billed — with
what they were before, and a change past the Owner's threshold reaches him as a letter.

## The clean studio's first film, approved and unpublished (2026-09-12)

From an empty history: six topics proposed in English on authorised sites, pages found
through Wikipedia's and CERN's own addresses, 23 claims verified, a script whose every scene
cites a claim, a storyboard that speaks the writer's words, a 45.6-second 9:16 render with
Runway stills (`seedream5_lite`, after the studio dropped an editing-only model) and an
ElevenLabs voice, quality control passed on every check, and an APPROVE from the Director —
on `kimi-k3`, the first model she has had that can see, citing what the frames show. The
film is not published: that decision is the Owner's.

## Pages are found, not guessed (2026-09-12)

An authorised site can carry its own search address (OpenSearch JSON, `{query}` inside);
the studio asks it before the Researcher plans and reads the pages found when his guesses
fail. On the clean studio's first day every guessed address returned 404; with Wikipedia's
search address recorded, the day is expected to read real pages. Sites that serve articles
only to browsers (UNESCO) stay unreadable under the studio's honest identity.

## Starting over, and a Director who decides once (2026-09-12)

`scripts/reset_history.py` deletes the agents' history and the live ledger and keeps the
configuration (a backup is taken first; the studio must be stopped). The ledger begins at
the reset line. The Director's escalations now close the escalated message, one open letter
per matter reaches the Owner, an investigation's answer is not investigated again, and the
correspondence round runs at most three reviews an hour — the evening of 2026-09-11 ran
nine in twenty-four minutes.

## The Director watches before publishing (2026-09-12)

Nothing reaches a channel without the Director's editorial verdict (migration 0029): she
reads the film as data and frames from the file, decides APPROVE or REJECT with reasons,
and writes to the departments that must change something. The one video that went out —
demo script, sourceless claim, Romanian narration, twenty words — would be rejected on
three counts before any model is asked.

## English on the way out (2026-09-12)

`STUDIO_CONTENT_LANGUAGE` (default `en`) is told to every employee whose words reach the
audience, and a publication whose title or description is not in that language holds. The
Owner's first real upload (private, Main Channel A, title in Romanian) is the case that
motivated it. Structured tasks ask the provider for JSON on the first attempt and think
natively on the second; the Director on `glm-5.3` needs the second, at ~11 minutes and ~46k
tokens per twelve messages.

## The cycle, watched (2026-09-12)

A real day run on a copy of the Owner's data: trends read, five topics proposed, claims
verified, a stalled storyboard re-rendered with real visuals, the Accountant's close parsed,
letters filed. Still short of a published video because the Researcher's guessed URLs 404
(no search step; see the changelog) and the Director's long analysis needed the new
formatting pass. The publish stage was disabled in the copy on purpose.

## Polish pass (2026-09-12)

Every view read from a screenshot and set on one text scale, one radius and shadow, actions
sized to their words, the scene chrome as one bar in two groups, the ledger breathing, and
Settings on the same dialog pattern as the rest. Details in `CHANGELOG.md`.

## Signals: vendor pages and search trends (2026-09-12)

Kael and Lyra choose their models by reading the vendors' own pages (fetched by the studio,
restricted to the vendor's hosts) and scoring the account's models where the production
hierarchy reads scores; a fallback default follows the recommendation, a locked one is
reported on. Google Trends for the studio's country is read daily (migration 0028) and, with
the studio's own measured cohorts, reaches the Researcher's proposals and the Director's
weekly review — so the adaptation loop runs the day real numbers appear. `STUDIO_TRENDS_GEO`.

## Correspondence, and the day that stopped (2026-09-12)

Messages are letters in threads (migration 0027): the ledger names both ends and opens the
thread; the Owner reads the exchange and writes back. Employees answer the letters that ask
for something at each worker pass, and the Director reads the answers at once; a letter to
the Owner (a decision that is hers, a day that stopped, a review that could not run) is red,
under the Owner chip, and waits for the Owner's reply. The empty answers of 2026-09-11 came
from the adapter the studio actually uses (`ConfiguredLLM`, thinking now off, ten-minute
timeout), a stale THINKING flag (runs are records while they run), and media defaults never
chosen (the day finishes its own setup). Token budgets are three times larger.

Still open from the Owner's office-logic request: employees choosing a video model by
researching online (cost, capability, examples), analytics-driven adaptation from Google
Trends and channel numbers, and the visual polish pass — tracked in `13_ROADMAP_TODO.md`.

## The Director's mandate: grow views and retention — 2026-09-11, ZCode (verified, scope released)

Owner's second decree of the day, implemented and live-verified:

- **Sarah's mission is now the growth of the audience** — raising views and retention is her
  primary charge (`_ROLE_DEFINITIONS` + migration `0026_director_mandate`, which also offers
  contract seed v3 to roles never Owner-edited).
- **Contract v3 powers**: she directs ANY employee in writing (every instruction, choice and
  request documented as a message), steers each channel's direction and changes or
  deprioritises topics when the measured performance says so, and requests a larger budget
  from the Accountant with the numbers and the reason written down — the Owner alone
  decides budgets, so a justified request also reaches the Owner. The Accountant's matching
  duty: answer every budget request from the books, in writing.
- **The weekly review routes the mandate.** Its answer is now structured
  (`weekly-review-v2`): verdict, sound indications (→ Lyra), video indications (→ Kael),
  channel direction and topic changes (→ LeadResearcher and ScriptWriter, and remembered as
  STRATEGY memory), a budget request (→ the Accountant, amount + justification) and an
  Owner escalation — all filed as messages that enter each employee's runs, plus her spoken
  summary in the office and the full review in her inbox. A schema-breaking answer files
  nothing and says so; a week with nothing published still reports that at zero tokens.
- **The Accountant answers budget requests at the daily close**: each open request is
  answered with the books' figures, resolved as "transmitted to the Owner", and the close
  escalates — documentation without ever granting a budget (Owner-only, unchanged).

Live verification: server restarted on `0026_director_mandate` (mission + contracts at v3
confirmed in the database), weekly review triggered and completed with the honest
"nimic publicat, nimic de măsurat" STATUS. Tests: backend 528 passed / 1 skipped (new:
schema-break files nothing; the Accountant's budget-request close); ruff, format, mypy
clean; frontend 79/79; docs integrity passes. The pre-existing secret-scan false positive
(`discovery.py:80`) stands, untouched, in Codex's file.

## The roles the Owner ordered: sound, video, and a Director who checks weekly — 2026-09-11, ZCode (verified, scope released)

Owner directive implemented end to end, live-verified against the running studio:

- **Contracts v2** (`config/role_contracts.json`, migration `0025_role_contracts_v2` data-only):
  the sound artist stewards the audio — chooses voice and TTS model where the channel's
  policy allows, weighs naturalness, recorded cost and measured retention, follows the
  Director's written indications, escalates when an indication would break a lock; the video
  editor the same for film models (quality/cost/what kept viewers watching); the Director
  decides from measured performance, sends production indications as messages to the two
  departments, and never skips the weekly review while anything published exists. A role the
  Owner has edited keeps the Owner's text (the migration only offers the newer seed).
- **The Director's indications now reach the employees.** Open messages addressed to an
  agent enter that agent's composed identity ("WHAT IS ASKED OF YOU RIGHT NOW", capped at
  ten, recorded in the context manifest) — identity v2. Resolved messages stop following
  the employee.
- **The weekly performance review** (`backend/app/runbook/weekly.py`): a scheduled job every
  seven days (active standing policy, first fire an hour after birth) plus an Owner button
  in the runbook panel and `POST /runbook/weekly-review`. It reads only what is recorded
  (publications with measured views/retention/CTR, per-channel totals, open strategy
  recommendations), puts the digest in front of the Director through her identity, and files
  her answer as HANDOFF indications to the sound and video departments and a STATUS report
  in her inbox. A week with nothing published reports exactly that and costs no tokens —
  verified live: task `COMPLETED`, "Revizia săptămânală 2026-S37: nimic publicat, nimic de
  măsurat". The autonomy stop gates both the schedule and the button; a week is reviewed at
  most once by the clock.
- Failed agent runs now log the exception with its traceback (`exc_info`), for diagnosis.

Tests: backend 526 passed / 1 skipped (new: open-messages identity test, three weekly-review
tests, scheduler asserts the two standing jobs); ruff, format, mypy clean; frontend 79/79,
tsc clean, build OK; docs integrity passes. Live: server restarted on 0025, contracts at v2,
both jobs registered (daily dormant, weekly active), UI checks 5/5
(`scratch/verify_weekly_review_ui.mjs`). The pre-existing secret-scan flag
(`discovery.py:80`, keyword false positive in Codex's file) stands, untouched.

Honest limits: the review reads the numbers `performance_intake` has collected — with no
publications yet there is nothing to judge, and the departments have no bound voices/models
to be bound by indications until those are configured (the Owner's next configuration step,
not code).

## ZCode investigation + inspector extend — 2026-09-11 (verified, scope released)

Owner questions answered by investigation (no behaviour change): the double "Sarah said"
line is two real `owner_chat` runs sent by the first verification pass, not duplication —
each has its own run row and its own freshly generated answer (today's re-verification
added a third turn). The `performance_intake` SKIPPED message was written at 20:17, before
the channel slots were bound (20:18–20:19, events `channel.credentials_bound`); verified
live against the current database that both bindings are `publisher_ready` and the
analytics provider resolves — the next daily run will not repeat that skip (it will report
"Nicio publicare reală de măsurat", which is the honest state while nothing is published).
Per-channel production criteria are implemented end to end (`media/production_policy.py`
hierarchy and locks, `media/factory.py render_plan` building real ElevenLabs/Runway
adapters per scene, the plan recorded on the render job); the gaps are data, not code:
no character has a bound/locked voice yet and no storyboard carries a `channel_id`, so on
Channel B the "fixed voice" has nothing defined to enforce and nothing routes production
to a channel. Agents have no tool-calling: a run is one prompt; the STATUS lines an
employee "says" are written by deterministic stage code in its name.

Code change: an «⛶ Extinde» button on the Agent Inspector header — the dialog fills the
screen and the whole history reads as one traversable page (no inner scroll box); the
choice persists while reopening the inspector during the session. Frontend only
(`index.html`, `main.js`, `style.css`). Verified: frontend 79/79, tsc clean, build OK,
browser checks 16/16 (`scratch/verify_conversation_live.mjs`, including expand/restore),
zero page errors; screenshot `output/playwright/conversation-inspector-expanded.png`.

## The conversation reads like one — 2026-09-11, ZCode (verified, scope released)

Owner-reported defects, fixed frontend-only against the data already recorded:

- **Raw JSON is no longer shown to the Owner.** A run whose output is JSON (URL picks,
  claims, topics, scenes, verdicts) renders as sentences and lists
  (`frontend/src/friendly_text.js`); the exact model output stays collapsed under
  «Răspunsul exact al modelului», and everything remains saved on the run. A truncated
  answer (token limit mid-list) has its complete items salvaged and shown with a note —
  the Owner-visible case came from Dr. Aris's stored runs and is unit-tested. Old runs
  whose only line was the engineered prompt no longer print instructions as the headline;
  the prompt stays under «Cererea completă».
- **The inspector chat is a live, saved exchange.** Owner question right, employee answer
  left; a "scrie…" indicator driven by the real THINKING/IDLE events; the history refreshes
  itself on message/run events for the open employee, including runs fired from outside
  the page. Proven with a real chat turn (Sarah/glm-5.3-flash) that survived a reload.
- **A live window into an employee's work.** The inspector's «Fereastră live ↗» opens a
  standalone popup (`frontend/src/live_window.js`): state pill, "Acum: …" line, and the
  employee's own event chain, seeded with the day from the ledger and updated from every
  newly recorded event via `Ledger`'s new `onEvents` callback (one funnel for socket,
  snapshot and events endpoint). The inspector detail view is unchanged.
- **The wide dialogs actually reach the page** — they were already styled at
  `min(1180px, 94vw)`; the served build was stale. Rebuilt; measured 1180px in Chromium.

Tests at release: frontend `npm test` 79/79 (14 new for the two modules), `tsc` clean,
build OK; backend `pytest` 522 passed / 1 skipped (unchanged code); ruff, ruff format,
mypy, documentation integrity pass. Browser verification: 14/14 checks in
`scratch/verify_conversation_live.mjs` against the running studio on port 8000, zero page
errors; screenshots `output/playwright/conversation-*.png`. One live chat turn was sent to
an existing configured provider as part of verification.

**Pre-existing baseline failure discovered, not mine and left for its owner:** since the
ElevenLabs work landed (`backend/app/integrations/discovery.py:80`, commit 1c8de87/096dd26),
`scripts/check_secrets.py` flags the dictionary key `"invalid_api_key"` — a keyword-detector
false positive on a key *name*, not a credential. Confirmed present on a clean tree
(stash/pop). `discovery.py` is inside Codex's active claim, so I did not touch it.

## The day starts without blocking the page (2026-09-11)

The Owner's "Pornește rularea de azi" queues the day on the background worker and says so;
the run panel shows the day on its way, and the ledger names each stage as it starts and
ends. Agent runs carry a one-sentence summary of their task, so a history reads as work done
rather than as the prompt behind it, and a run that returned no visible text is recorded
EMPTY_OUTPUT with its reason — thinking models were spending the whole token budget on
reasoning, which is now switched off for Ollama generation.

## Live ledger and the office first (2026-09-11)

The workspace opens on the office, wide, with a live ledger in the left column: every message
an employee sends or files, every task, stage, cost and Owner action, in words and by name,
newest first, filtered by kind, with the production stage and the last daily run in the
head line. The ledger streams over the WebSocket and backfills the day from `GET /events`.
Owner Control and Workforce panels are gone; autonomy is one ON/OFF switch in the office
toolbar. The evening books report is filed by the Accountant, with her headline and holds.

## Books, budget, history (2026-09-11)

Eight employees: Nadia (Accountant) joined, with contract, Bible and a desk in the Accounting
& Treasury office that replaced the Commons. The Owner sets a daily or monthly budget in
Trezorerie; spend is measured from the books, the media stage refuses what an exceeded
budget cannot afford, every render's narration is costed per scene at the stored price, and
the Accountant closes each day before the Director's review. Every employee has a history
(runs, messages, decisions with reasons) and a chat in the Agent Inspector; speech bubbles
page through the whole answer at reading speed. Details and limits:
`ACCOUNTING_AND_HISTORY.md`. Migration 0024.

## The pipeline has no empty stages left (2026-09-11)

Every stage of `../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` now has work behind it. New:
§3 idea generation (the Lead Researcher proposes candidates scored on the runbook's six
criteria, deduplicated, limited to authorised hosts), the retrieval half of §4 (the studio
fetches its own pages and keeps only what actually came back) and §5 selection (the Director
chooses among topics that have a verified claim, and the decision is recorded on the topic).
A channel slot now names the YouTube account it publishes through; publishing and analytics
use that binding instead of "the first row", and `GET /publishing/channels` no longer answers
500 when several accounts are connected. `POST /settings/auto-configure` finishes what a
verified connection leaves unfinished, only where the choice is forced. Details and limits:
`PIPELINE_COVERAGE.md`. Migration 0023.

## Employees: identity, memory, reports (2026-09-11)

Every agent run now carries the employee's identity as the system prompt, composed from stored
data (role mission, allowed/prohibited tasks, the role's work contract from
`config/role_contracts.json`, the character's speech style and phrases, the memory its role may
read, standing rules) and records the context manifest on the run. Character Bible entries are
linked to the employees holding their roles. Memory (`memory_record`, classes per
`../architecture/04_AGENT_SYSTEM.md` §9) is written by services on real outcomes with
provenance and read by role scope. Typed messages (`agent_message`) carry STATUS reports and
escalations to the Director; the runbook's `post_run` stage files the day's reports and runs
Sarah's review. Lyra reviews narration, Kael diagnoses failed renders, Vera prepares
publication metadata and may hold a candidate. Details and limits: `AGENT_IDENTITY_MEMORY.md`.
Migration 0022. No new agents were added: hiring stays evidence-driven through workforce
proposals.

## Identity

The agency is **AMN-AI — Autonomous Machine Nexus — Artificial Intelligence**. The name and logo
assets, and the rule that the stored studio name is domain state rather than configuration, are
documented in `BRAND_AMN_AI.md`. Renaming an existing studio is done with
`scripts/rename_studio.py`, which appends a `studio.renamed` event; bootstrap never rewrites it.

## Audit history

- **2026-09-09**, external: found fabricated channel configuration, simulated uploads recorded as
  real publications, a non-playable file named `.mp4`, a self-certifying QC gate. Remediated; see
  `AUDIT_2026-09-09_EXTERNAL.md`.
- **2026-09-10**, third party: `AUDIT_2026-09-10_THIRD_PARTY.md`.
- **2026-09-11**, internal, at the Owner's request: nine defects found and fixed, five areas
  verified and put under test. The most serious were an unanswered question to YouTube recorded as
  a "no" (risking a duplicate upload), a factual gate passing assets it had never traced while
  claiming verification, and Owner funding that a retried request could double. See
  `AUDIT_2026-09-11_INTERNAL.md`.

## Running on its own

Since 2026-09-11 the application process carries a background worker that fires due scheduled
jobs and executes the tasks they enqueue. The daily job (`daily_main`, `DAILY_RUN`, every 24
hours, CATCH_UP on missed slots) is created at start-up but dormant; the Owner starts it from the
daily-run panel, and that decision is an event. Nothing fires while the autonomy stop is set, and
the scheduled run happens at most once per business date. Eight of the twelve runbook stages
have real work behind them; `idea_generation` and `post_run` report SKIPPED with that reason.

## Connected accounts

Avatar repair verified 2026-09-11: the CSP now permits YouTube's two avatar origins and the
snapshot selects high → medium → default. Both existing connections (Nexus Curiosity and Inside
The Nexus) were refreshed through the real Verify buttons and displayed their own 800×800 API
images in Chromium, with persisted URLs and zero image-policy violations. Missing-thumbnail
fallback passed a separate browser fixture; completed-Reconnect refresh passed stubbed API tests.
Changed: YouTube snapshot selection, HTTP image CSP, connection-card avatar/CSS, regression tests
and `scripts/verify_youtube_avatars.mjs`. No migration. The local server was rebuilt/restarted.
Validation: 435 backend tests passed, 1 skipped (unconfigured real Ollama); 52 frontend tests
passed; Python/JS type checks, lint, frontend build, documentation integrity and secret scan passed.
Evidence and scope limits are in `YOUTUBE_CONNECTIONS.md`. No remaining avatar blocker.

YouTube channels are connected by OAuth, not by pasting credentials. Settings → *Conturi și
e-mail* takes a connection name, a Google OAuth client id and secret, and a redirect URI; the
Authorization Code flow with `access_type=offline` does the rest, and the channel identity is read
back from `channels.list` rather than typed. Refresh tokens and client secrets live in the Fernet
vault and are never returned by any route. Multiple independent channels are supported, and no
channel is named in the code. Connecting a channel is not the same as publishing to one — see the
Phase 6 correction below. Evidence: `YOUTUBE_CONNECTIONS.md`.

## Baseline and document authority

Started from 83 Markdown documents with no application code, tests, dependencies or Git history.
All original documents were read. The Master Prompt remains authoritative under Owner instructions.
There was no pre-existing test suite to run.

Per Owner request, 78 specifications/review documents live in ../architecture/; five original
tracking documents live here. The document index records original and post-move hashes. Only path
references were changed inside the architecture package. CI/local checks protect the indexed files.

## Working and verified locally

**Phase 0 (complete):**
- FastAPI application at http://127.0.0.1:8000, with private Owner Bearer authentication.
- HTML/Tailwind/JavaScript UI built with Vite; desktop and 390px mobile layouts inspected.
- SQLite database and Alembic revisions 0001_foundation, 0002_phase1_agents, 0003_phase2_automation, 0004_phase4_factual; explicit bootstrap.
- Persisted studio, empty initial room, Owner STOP flag, immutable command/event history.
- Atomic policy/event transactions, optimistic version checks and command idempotency.
- Duplicate/concurrent commands tested; failed event insertion rolls back policy changes.
- STOP state survives application restart; clearing it keeps MANUAL mode.
- Owner-only consistent snapshots/event pagination; disconnects label stale UI.
- No credentials in frontend builds, API projections or request logs.
- Structured request logs, request correlation, health endpoints, CSP/Host checks.
- Locked Python/Node dependencies, lint/types/build/test baseline and GitHub Actions.
- Documentation inventory/hash checks with integrity tests.

**Phase 1 (complete — verified 2026-09-09):**
- Abstract LLMProvider interface (base.py): health_check, list_models, generate, is_cloud model metadata.
- Ollama HTTP adapter (ollama.py v1.0.0): real /api/tags discovery + /api/generate; returns OFFLINE if not running; supports cloud models (glm-5.2:cloud, kimi-k2.6:cloud, qwen3-coder:480b-cloud), api_key bearer auth, and /api/show model inspection.
- ProviderRegistry (registry.py): maps provider IDs to adapter instances; in-process health cache.
- Dynamic model discovery (sync_provider_models): automatically discovers both local and cloud models from provider endpoint, updates model_record, links text_generation capabilities, and emits provider.model_discovered events.
- Role entity with mission, allowed_task_types, prohibited_actions; RoleCapability requirement levels (REQUIRED/PREFERRED).
- Capability entity (text_generation, tool_calling, etc.); ModelCapability mapping with confidence.
- ProviderRecord, ModelRecord: registered providers and models with discovery_method tracking.
- Agent entity: lifecycle (PROPOSED/CANDIDATE/HIRED/ACTIVE/PAUSED/SUSPENDED/TERMINATING/TERMINATED/ARCHIVED) and runtime_state (IDLE/THINKING/WORKING/...).
- AgentRun envelope: full audit record of every LLM invocation with status, tokens, cost_vr, event_id.
- ToolReceipt: immutable append-only receipts (DB trigger, no UPDATE/DELETE) for all tool calls.
- Owner Policy Kernel: enforces autonomy_stop check, lifecycle check, capability match, provider health before any LLM run.
- FastAPI routes: GET/POST /api/v1/agents/, GET/POST /api/v1/providers/, /sync-models, /run.

**Phase 2 (complete — verified 2026-09-09):**
- Persisted workflow state machine (Workflow, WorkflowStep): tracks 17 pipeline stages (DISCOVERY -> ... -> PUBLISHED -> ANALYTICS -> LEARNING) according to 47_STATE_MACHINE_SPECIFICATIONS.md; rejects illegal state transitions.
- Task queue with leases and backoff (TaskQueueItem): atomic task claims with time-bounded worker leases, automatic expired-lease reclamation when workers fail, heartbeat renewal, and task completion.
- Error classification and dead-letter queue: retryable failures trigger exponential backoff with computed next_attempt_at; max attempts exhausted routes tasks to DEAD_LETTER; operator recovery endpoint allows manual retry.
- Singleton-safe scheduler (ScheduledJob): recurring jobs with leader leases to prevent duplicate work across scheduler instances, with support for SKIP and CATCH_UP missed-run policies.
- Transactional outbox (OutboxRecord): atomic commit guarantees that business events and outbox records commit together; outbox dispatcher broadcasts to WebSocket clients and marks status PUBLISHED.
- WebSocket gateway (/api/v1/ws): authenticated real-time event streaming with replay protocol supporting after_sequence cursor to replay missed events after reconnection.
- Autonomy stop hard-gate: task worker and scheduler refuse to claim or run tasks when autonomy_stopped is active.
- Alembic migration 0003_phase2_automation: 5 new tables (workflow, workflow_step, task_queue, scheduled_job, outbox_record) with zero schema drift.

**Phase 3 (complete — visual system v2 2026-09-10, see `PIXEL_OFFICE_V2.md`; Blender sprite pipeline tried on the RESEARCH floor 2026-09-11 and switched off after the Owner's comparison; Character Bible now drives character looks, see `PIXEL_ART_PIPELINE.md`; per-channel production policies with locked character identities 2026-09-11, see `PRODUCTION_POLICY.md`):**
- Premium pixel-art rebuild of the cutaway (palette module with hue-shifted ramps, compiled outlined character sprites with role costumes, per-department room shells and interiors, baked lighting, limestone facade, glass lift). Designed first in Figma (`AMN-AI Office · Pixel Art Design System`, file `bqTc0PoCbjL5dH5xw0FRDI`), then implemented frontend-only; backend, API and events untouched. Measured 60 FPS at ~6 ms/frame; 43 frontend tests pass.
- Lateral cutaway multi-floor skyscraper canvas rendered at 60fps with zero simulated state, inspired by Space Haven, Anomaly President, and retro pixel-art simulation games.
- Seniority-based corporate hierarchy from top to bottom:
  * Floor 4 (Penthouse / Executive Suite): Director / CEO (Sarah) with panoramic city view, executive mahogany desk, gold trendlines, and award trophies.
  * Floor 3 (Research & Fact-Check Lab): Lead Researcher (Dr. Aris) & Fact Checker (Elena) with glowing holographic network graph whiteboard.
  * Floor 2 (Creative Writing & Narrative Studio): Script Writer (Marcus) with cork storyboard pinned with colored cards and red string.
  * Floor 1 (Media Lab & Production Bay): Voice Artist (Lyra) in acoustic foam vocal booth with boom mic & active LED EQ meter; Video Editor (Kael) with triple editing monitors.
  * Ground Floor / Level 0 (Infrastructure, Distribution & Lounge): Ollama Local Cluster & Cloud AI Gateway racks with blinking LED matrices and cooling fans; Coffee lounge with espresso machine emitting steam, water cooler, couch, and wall clock; Distribution hub with Vera at release console with radar map.
- Functional Glass Elevator Shaft on building exterior with moving elevator cabin traveling between floors.
- Procedural Animated Characters (Personaje):
  * Idle breathing bounce and periodic eye blinking.
  * Rapid typing hands on keyboard with dynamic monitor light reflections when WORKING.
  * Chin scratching gesture with floating glowing idea lightbulb and sparks when THINKING.
  * Resting / Zzz animation when PAUSED.
- Smooth camera controls: mouse pan, pinch/wheel zoom (0.4x to 2.5x), `fitToOffice()`, 1:1 reset, and dedicated Fullscreen (`#fullscreen-btn`) & Exit Fullscreen (`#exit-fullscreen-btn`) buttons with automatic canvas resize and Escape key support.
- Interactive Agent Inspector drawer modal (`#agent-inspector`) opened by clicking any character workstation, supporting live agent state inspection, direct task execution, and pause/resume actions (`POST /api/v1/agents/{id}/pause`, `POST /api/v1/agents/{id}/resume`).
- Real-time WebSocket connection to `/api/v1/ws` syncing backend events directly into `OfficeState`.
- Zero CSP violations (`style-src 'self'`). Frontend bundle remains compact.

**Phase 4 (PARTIAL — verification machinery works, real research does not exist):**
- Alembic migration `0004_phase4_factual`: 5 new tables (`topic_idea`, `source_snapshot`, `factual_claim`, `script_draft`, `hook_option`).
- Zone D Prompt Injection Defense (`sanitizer.py`): token stripping, instruction override filtering, and inert `<untrusted_source_evidence>` XML boundary tagging.
- Immutable source snapshots with SHA-256 digests (`content_hash`) and metadata (url, publisher, author, credibility_score). **Source text is supplied to the API by the Owner; nothing is retrieved from the web — there is no search or research adapter.**
- Atomic claim model (`factual_claim`) with status (`UNVERIFIED`, `SUPPORTED`, `REFUTED`), importance (`CRITICAL`, `SUPPORTING`, `FLAVOR`), and confidence.
- Strict Content Gate: attempts to generate or approve scripts with unverified or refuted claims raise `FactualGateError` and record an immutable `BLOCKED_UNVERIFIED_CLAIMS` draft for auditability (`factual.script_blocked_by_gate`).
- Script generation with 100% `SUPPORTED` claims compiles scene cues, voiceovers, and claim references. **A claim becomes SUPPORTED only through `POST /factual/claims/{id}/verify`, whose status is decided by the caller; there is no independent fact-checking agent.**
- Hook Specialist: opening hook variations with psychological techniques (`CURIOSITY_GAP`, `CONTRARIAN`, `STATISTIC_SHOCK`, `STORY_IN_MEDIA_RES`) and retention scores.
- Deduplication novelty calculation preventing repetitive content drift.
- Ollama Cloud model integration (`glm-5.2:cloud`, `kimi-k2.6:cloud`, `qwen3-coder:480b-cloud`).
- Frontend Topic Submission & Verification Modal (`#research-modal`) in 2D Office.
- **Not met for Phase 4 acceptance** (`IMPLEMENTATION_PLAN.md`: "real research, evidence, independent fact checks"): research and independent verification are manual.

**Phase 5 (PARTIAL — real encoding works, real visuals/voice do not exist):**
- Character Bible (`character_bible`): Pre-seeded with 7 canonical studio employees (Sarah, Dr. Aris, Elena, Marcus, Lyra, Kael, Vera) with immutable visual descriptions, hex palettes, role symbols, and voice profiles.
- Storyboard generator (`storyboard`, `storyboard_scene`): Transforms approved scripts into multi-scene visual shot lists enforcing aspect ratio 9:16 (1080x1920); strictly blocks unapproved scripts or scripts with unverified claims via `FactualGateError`.
- Placeholder media adapters (`DeterministicVisualAdapter`, `DeterministicTTSAdapter`): produce SVG layout cards and RIFF/WAVE tones locally. These are placeholders, not generated content: no image model and no voice model is connected. Assets built from them are recorded with provider `PLACEHOLDER_DETERMINISTIC_VISUALS` and are **blocked by QC from publication**.
- Subtitle generator: Compiles synchronized SRT subtitle tracks matching scene voiceover segments and durations.
- Video Assembly Engine (`VideoRenderJob`, `MediaAsset`): encodes a real H.264 1080x1920 MP4 with FFmpeg from raster placeholder frames plus the narration track, and records a SHA-256 digest of the encoded bytes (`media.video_rendered`). **Without FFmpeg the render fails** (`RenderEngineUnavailable`, HTTP 503) and no MediaAsset is recorded; the studio no longer writes a stand-in file with an `.mp4` name.
- Quality Control Engine (`quality_control_report`): Technical QC now **measures the file with ffprobe** (video stream present, measured resolution, measured duration) and **recomputes** the SHA-256 provenance digest, instead of trusting the metadata the renderer wrote. Rights QC checks the license field. Content-source QC fails any asset built from placeholder visuals. Factual QC re-checks every referenced claim. Character-drift QC is reported as `NOT_IMPLEMENTED` — it performs no comparison and certifies nothing.
- Alembic migration `0005_phase5_media`: 6 new tables (`character_bible`, `storyboard`, `storyboard_scene`, `media_asset`, `video_render_job`, `quality_control_report`).
- Media API routes (`/api/v1/media`): Character Bible endpoints, Storyboards, `POST /storyboards/demo-fixture` (creates a topic/script with an **UNVERIFIED** claim; it never marks anything SUPPORTED), video rendering, streaming, and QC gate verification.
- Frontend Media Production Modal (`#media-modal`): Storyboard pipeline viewer, 9:16 preview, QC scorecard, provenance hash badge, Character Bible inspector.
- **Not met for Phase 5 acceptance** (`../architecture/26_MASTER_ACCEPTANCE_CRITERIA.md` §F): there is no image or TTS provider, so no real footage or narration exists; character continuity is unimplemented.

**Phase 6 (PARTIAL — pipeline and gates work, no real upload has ever happened):**
- Channel slots (`channel_record`, `channel_brand_asset`): two slots (`MAIN_FACTUAL`, `OFFICE_SERIAL`) are seeded with **no remote channel ID, no credentials and status `NOT_CONFIGURED`**. Status is derived from what is actually present (`NOT_CONFIGURED` -> `AUTH_REQUIRED` -> `AUTHENTICATED`); nothing is ever reported as configured on the strength of a seed.
- Five-check publishing gate (`evaluate_publishing_gate`). This is a **subset** of the publish column of `../architecture/50_CONTENT_GATE_MATRIX.md`, not an implementation of it — rights on the final package, platform policy, novelty on final metadata, brand strategy, budget, and Channel B continuity/narrative privacy are not implemented:
  1. Global Autonomy Stop check (fails if `autonomy_stopped` is active).
  2. Media file on disk existence check (fails if file missing or 0 bytes).
  3. Quality Control check (fails if QC status is not `PASSED` or score < 0.90).
  4. Factual claim integrity check (fails if any claim referenced in the script is not `SUPPORTED`).
  5. Idempotency & duplicate protection check (fails if asset was already published on that channel).
- YouTube Data API v3 Adapter (`YouTubeProvider`): OAuth2 refresh-token exchange, chunked resumable upload with `Content-Range` and 308 resume, synthetic-content disclosure (`containsSyntheticMedia` plus a disclosure line in the description), remote status polling, and reconciliation that is actually invoked before any retry. **This adapter has never run against Google**: no credentials have been configured, so the whole path is untested against the real API.
- Simulated Publishing Adapter (`DeterministicPublishingAdapter`): **tests and CI only**. It is never selected at runtime; without real credentials the API returns 503 `PublisherNotConfigured`. Its results carry `simulated=True`, a `sim:` identifier and no platform URL, and are stored as `PUBLISHED_SIMULATED` with event `publishing.video_published_simulated`.
- Publication State Machine & Tracking (`publication_record`): Enforces `DRAFT_INTENT` -> `VALIDATED` -> `STARTED` -> `REMOTE_CONFIRMED` -> `PUBLISHED` transitions with recovery from `REMOTE_UNKNOWN` and `FAILED_RETRYABLE`.
- Unique constraint `uq_channel_idempotency`: Prevents duplicate uploads of the same intent.
- Alembic migration `0006_phase6_publishing`: 3 new tables (`channel_record`, `channel_brand_asset`, `publication_record`).
- Publishing API routes (`/api/v1/publishing`): Channel management, gate evaluation, intent creation, publication execution, quick-publish, and publication history retrieval.
- Frontend Distribution Hub Modal (`#publishing-modal`): shows real channel status with plain-language hints, a banner when no credentials are configured, the gate breakdown including what is not implemented, and publication history where a simulated run is labelled "SIMULAT (nepublicat)" and gets no link. Only a genuine `youtube.com` URL becomes a clickable link.
- **Not met for Phase 6 acceptance** (`../architecture/26_MASTER_ACCEPTANCE_CRITERIA.md` §G): OAuth has never been exercised, no private upload has been verified, and no real remote ID has ever been persisted.

**Phase 11 (complete for the ledger — verified 2026-09-10, see `PHASE11_ECONOMY.md`):**
- Immutable double-entry VR$ books: `ledger_account`, `ledger_transaction`, `ledger_entry`, with
  a seeded chart of accounts covering cash, restricted cash, receivables, fixed assets,
  depreciation, debt, equity, revenue by source and expense lines.
- External evidence layer: `revenue_evidence` (YouTube, donations, sponsorship, other),
  `provider_cost_record`, `owner_funding_event` and `fx_snapshot`. Recording evidence mints
  nothing; only SETTLED revenue mints, and only a BILLED invoice posts a cost.
- The 1:1 rule holds under retry and re-import: `(source, external_reference)` is unique and a
  minted row is stamped with its transaction, so one verified dollar becomes one VR$ exactly once.
- Forecast and pending payouts are reported beside the treasury, labelled, and can never be
  minted or spent. FX is never invented: a non-USD amount without a recorded rate is refused.
- Reversals post a mirrored transaction and never delete; a transaction is reversible at most
  once. A chargeback after real spending shows a deficit rather than hiding it.
- Money is integer micros throughout, so the books cannot drift; `trial_balance` re-adds every
  stored line and is surfaced in the UI.
- Owner-only routes under `/api/v1/economy`; **no route anywhere in the API pays, buys, transfers
  or checks out**, and a test asserts that across the whole OpenAPI surface.
- Frontend **Trezorerie** panel renders the backend's own labels (VR VIRTUAL / PENDING / FORECAST
  / ESTIMAT), the trial-balance verdict and the "not filed accounts" disclaimer.
- Alembic migration `0016_phase11_economy`: 7 new tables. 31 new tests.
- **Not met yet**: nothing spends VR$, no interest accrues, no budgets/runway/P&L, no depreciation,
  and no automatic revenue import — those are Phases 12–14.

## Partial / exact limits

- The application runs end to end locally: foundation, automation, 2D office, factual gating,
  media assembly and the publishing state machine are all exercisable.
- **Nothing has ever been published.** Without `STUDIO_YOUTUBE_*` credentials the publishing API
  returns 503 and refuses; the simulator is reachable only by injecting a provider in tests.
- **No asset currently passes QC for publication.** Renders use placeholder visuals, which
  content-source QC fails by design until an image/TTS provider is connected.
- Rendering requires FFmpeg on the host. Without it, `POST /media/render/{id}` returns 503.
- Local single-owner SQLite deployment only. PostgreSQL and multi-user auth remain pending.
- Real Ollama end-to-end test is skip-marked; it runs when `STUDIO_OLLAMA_URL` is set.

## Not implemented

- Search/research adapter (Phase 4 acceptance) and independent fact-checking agent.
- Image and TTS providers (Phase 5 acceptance); character-continuity drift detection.
- The remaining publish-time gates of `../architecture/50_CONTENT_GATE_MATRIX.md` (rights on final package,
  platform policy, novelty on final metadata, brand, budget, Channel B continuity/privacy).
- Office Serial autonomous scriptwriter and dynamic departments.
- Spending VR$: procurement/VendorShop (Phase 13) and treasury financing with interest accrual
  (Phase 14). The ledger they will post to exists; nothing spends from it yet.
- Finance dashboard: budgets, cost centres, runway/burn, P&L, balance sheet, cash flow and
  30/90/180-day scenarios (Phase 12).

## Test evidence

Independent audit environment (Linux, Python 3.13, SQLAlchemy 2.0), 2026-09-09, after remediation:

- `pytest` **with FFmpeg available**: 87 passed, 1 skipped (real Ollama), 0 failed.
- `pytest` **without FFmpeg**: 85 passed, 3 skipped (Ollama + two render tests that are skipped
  rather than silently exercising a fake path), 0 failed.
- `tests/test_truthfulness_gates.py` (new, 10 tests) locks the governance invariants: channel
  slots are never reported as configured, publishing refuses without credentials, a simulated
  upload is never stored as a real publication, a gate refusal is persisted with its event,
  QC rejects a non-video file named `.mp4`, QC rejects a tampered provenance digest, and the
  character-drift check never claims to pass.
- `ffprobe` on a produced render: 1080x1920, h264, duration equal to the storyboard timeline.
- `npm test --prefix frontend`: 6 passed. `npm run check`: 0 errors. `npm run build`: succeeded
  (51.33 kB JS, 24.44 kB CSS).
- **Live application verification** (`scratch/verify_post_audit_e2e.mjs`, real Chromium against a
  running server): **27/27 checks passed**, 0 console errors, 0 CSP violations. It exercises the
  full chain — login, clearing the Owner STOP, channel status, the credential banner, the 1-click
  publish refusal, the demo fixture, the factual gate blocking an unverified script, claim
  verification, approval, storyboarding, rendering, QC, and the publishing gate refusal — and
  confirms with `ffprobe` that the produced file is a real 1080x1920 H.264 video of 18.00s.
  Screenshots: `output/playwright/post-audit-publishing-hub.png`, `post-audit-history.png`,
  `post-audit-media-modal.png`, `post-audit-mobile.png`.
- **Cold-start verification**: from a clean checkout with no `.venv`, no `node_modules`, no `.env`
  and no database, `uv run python scripts/start.py` brought the studio up unattended (uv venv +
  `uv sync --locked` + `npm ci` + Vite build + bootstrap + server), `/health/live` answered 200,
  and the 27-check Playwright suite passed against that fresh instance.

Note on the previous revision of this section: the "80 passed" figure it reported was
reproducible, but the suite passed **because** FFmpeg was absent on the development machine —
the real encoder path raised `DetachedInstanceError` and had never been executed. The suite now
fails loudly in that situation instead of certifying the fallback.

## Files changed / architecture impact

Post-audit remediation (2026-09-09):
- `backend/app/config.py`: `STUDIO_YOUTUBE_*` and `STUDIO_FFMPEG_PATH` settings; credentials no
  longer read ad hoc via `os.getenv`.
- `backend/app/publishing/services.py`: honest channel seeding and `derive_channel_status`;
  gate refusals persisted before raising; `PUBLISHED_SIMULATED` state; QC score minimum
  enforced; reconciliation before any retry; no provider fallback.
- `backend/app/publishing/router.py`: 503 `PublisherNotConfigured`; `POST /channels/seed`
  replaces seeding inside a GET; 404 instead of 500 for a missing asset; quick-publish requires
  an AUTHENTICATED channel.
- `backend/app/providers/publishing_base.py`, `deterministic_pub.py`: `simulated` flag,
  `sim:` identifiers, no fabricated platform URL.
- `backend/app/providers/youtube.py`: chunked resumable upload, synthetic-content disclosure,
  `youtube_provider_from_settings`.
- `backend/app/media/assembler.py`: placeholder raster frames + real FFmpeg encode or
  `RenderEngineUnavailable`; no stand-in `.mp4`; storage root no longer a hardcoded Windows
  path; detached-ORM bug fixed.
- `backend/app/media/qc.py`: ffprobe measurement, provenance re-verification, content-source
  check, character drift reported as `NOT_IMPLEMENTED`.
- `backend/app/media/router.py`: `POST /storyboards/demo-fixture` creates UNVERIFIED claims
  only; render surfaces 503 when no encoder exists.
- `scripts/bootstrap.py`: fixed a `TypeError` that broke first-time `.env` creation.
- `frontend/index.html`, `src/main.js`, `src/style.css`: truthful channel and publication
  status vocabulary, credential banner, no links to non-existent videos.
- `tests/test_truthfulness_gates.py` (new); `tests/test_phase5_media.py` and
  `tests/test_phase6_publishing.py` updated to assert the honest behaviour.
- `pyproject.toml` / `uv.lock`: added `websockets` — without it uvicorn answered the
  `/api/v1/ws` handshake with 404 and the office never received live events. Run `uv sync`.
- `backend/app/factual/services.py`, `router.py`, `schemas.py`: new
  `POST /api/v1/factual/scripts/{id}/approve`, which re-runs the factual gate at approval time.
  Without it, scripts created through the real API (`VERIFIED_PASS`) could never reach the
  `APPROVED` status storyboarding requires — only the removed fixture endpoint could.
- `start.cmd` and `scripts/start.py` (new): single-command launcher with a preflight report that
  states which integrations are configured; `scripts/bootstrap.py` and `../../README.md` point at it.
- `scratch/verify_post_audit_e2e.mjs` (new): the Playwright verification described below.
- `docs/project/AUDIT_2026-09-09_EXTERNAL.md` (new): the audit these changes answer.

- `backend/migrations/versions/0007_correct_fabricated_records.py` (new, data-only): corrects
  rows already written by the pre-audit code — invented channel IDs are cleared and the channels
  set to `NOT_CONFIGURED`, `yt_sim_*` publications become `PUBLISHED_SIMULATED` with their dead
  YouTube URLs removed, and every earlier `PASSED` QC report is marked `INVALIDATED` because the
  gate that granted it measured nothing. Nothing is deleted; history stays auditable.
- `backend/app/main.py`: startup revision check moved to `0007_correct_fabricated_records`.

Modular monolith; no table was added or altered (migration 0007 is data-only). Phase 7 analytics
must therefore start at `0008`.

## Blockers and risks

- **Publishing is blocked by design** until `STUDIO_YOUTUBE_CLIENT_ID`,
  `STUDIO_YOUTUBE_CLIENT_SECRET` and `STUDIO_YOUTUBE_REFRESH_TOKEN` are configured and a
  channel is moved to `AUTHENTICATED`. The whole YouTube path is still unexercised against
  Google.
- **Publishable content is blocked** until a real image/TTS provider replaces the placeholder
  adapters; content-source QC fails placeholder visuals on purpose.
- Rendering requires FFmpeg on the host.
- Phase 7 analytics code on disk is inert and unmigrated; wiring it as-is would cause schema
  drift and refuse startup.

## Exact next task

Close the acceptance gaps before advancing to Phase 7, in this order:

1. **Phase 4 acceptance** — a real search/research adapter (`../architecture/22_PROVIDER_INTEGRATION_CONTRACTS.md`
   search adapter contract) feeding `ingest_source_snapshot`, plus an independent fact-checking
   role that cannot verify its own claims.
2. **Phase 5 acceptance** — a real image provider and a real TTS provider, so renders stop being
   placeholder frames and content-source QC can pass; then character-continuity drift detection.
3. **Phase 6 acceptance** — configure Google OAuth, verify one private upload end to end against
   the real API, and record the real remote ID.
4. Only then Phase 7 (analytics), starting by adding migration `0008` for the analytics tables
   and wiring the router and `Base.metadata`.


## Codex research scope claim — 2026-09-09T23:19

Active: isolated public HTTPS source retrieval in new backend/app/research files, a local Owner CLI and dedicated tests. UI, media, app wiring, dependencies and migrations remain outside this claim while Claude works there. Baseline: 88 passed, 3 skipped; one documentation test fails on nine stale relative references.

## Codex research increment — completed, scope released

- Implemented Owner-directed known-URL HTTPS retrieval in new `backend/app/research/` files and `scripts/research_source.py`; existing UI/media/application code remains outside this change.
- The CLI can feed the existing authenticated source-ingestion API. No claim is automatically verified; no search provider or worker is activated. Phase 4 remains partial.
- Corrected nine stale architecture/root-document references in project tracking. Original architecture hashes are unchanged.
- Windows validation: 121 passed, 3 skipped (real Ollama unavailable; two FFmpeg checks unavailable). New-module Ruff and mypy pass; document inventory/hash verification passes.
- Real IANA HTTPS retrieval and authenticated ingestion into an isolated temporary database succeeded with matching hashes. Live studio state was not changed.
- Usage, limitations, touched paths and exact remaining research work: `RESEARCH_HANDOFF.md`.
- Next: keyword-search provider integration and independently authorized fact checking; coordinate separately before modifying shared factual routes. Claude retains UI/media scope.

Verification follow-up: the secret scanner flagged a pre-existing hardcoded provenance fixture in `tests/test_phase6_publishing.py`. Replaced only that fixture value with the actual SHA-256 of its test video bytes; no scanner suppression or publishing implementation change.

Final follow-up checks: all six publishing tests pass after the fixture correction; secret scan and documentation inventory/hash checks pass. No frontend or pre-existing backend source file was modified.

## Codex Settings scope — 2026-09-09T23:38

Owner explicitly requested Settings UI: LLM providers, agent assignments, video/audio tools, YouTube/TikTok/Instagram/Facebook and optional email credentials. Scope: new integrations backend + migration 0008, separate settings UI module/styles and minimal app wiring. No office animation edits. Credentials encrypted; saved configuration must never imply verified connectivity or publishing capability.

## Owner-directed renderer fixes — 2026-09-10, ZCode

Owner-reported visual defects only, scope `frontend/src/office_engine.js` scenery/nameplates + one new frontend unit test: remove the invented bus route number "12", stop same-lane vehicles passing through each other (lane spacing at spawn + car-following), and shrink the agent nameplates onto a light "paper" plate for readability. No backend, settings, integrations or office-state changes.

Completed and released the same day. Details:

- `drawCar`: the hard-coded bus route label "12" is gone; the destination blind stays blank.
- `makeTraffic`/`updateTraffic` (new, exported): vehicles now spawn spread across each lane's loop stretch and move as a platoon — a follower near its leader adopts the leader's speed and a hard clamp holds a 24 px bumper gap, including across the road's wrap seam, so same-lane vehicles can no longer drive through each other.
- `drawNamePlate`: the name renders at single scale (was double) on a light paper card with dark ink and a muted state line — half the height, far less floor area, readable over the night interiors; the selected variant keeps the gold border.
- Follow-up (Owner direction, same day): the runtime state moved out of the floor card
  entirely. The card at the character's feet now carries the name only; a new
  `drawStateTag` floats the state (IDLE, WORKING…) above the head as a dark chip with
  department-accent text, and the thinking bulb / sleeping Z marks were raised above it
  so the three never overlap.
- Verification: `npm test` 11/11 (3 new traffic invariant tests: spawn spacing, fast-car-catches-slow-bus, 15-minute mixed-timestep seam run), `npm run check` clean, `npm run build` OK (86 kB). Live browser check on the running local studio confirmed the bus has no number, traffic flows with no overlap across frames, and the nameplates render as small light cards.

## Documentation identifiers, initial Git commit — 2026-09-10, ZCode (second session)

Owner-directed documentation and repository repairs; recorded as D-DOC-001 in the decision log:

- `16_DECISION_LOG.md`: removed the byte-identical duplicate of the ADR-001…ADR-V5-003 block
  (verified identical before deletion; 706 → 551 lines, every ADR now single).
- `../architecture/02_SRS.md`: the v3 additional FRs are renamed `FR-V3-037…FR-V3-066`
  (same numeric suffix, consistent with the existing `FR-V4-`/`FR-ECON-` namespaces), clearing the
  collision with base FR-037…066. NFR-013…021 never collided and are unchanged. Requirement text
  unchanged. `../architecture/V3_FILE_BY_FILE_REVIEW.md` notes the rename; `IMPLEMENTATION_PLAN.md`
  marks the
  recorded conflict resolved. Indexed `sha256` values for both architecture documents updated
  explicitly (original hashes preserved).
- `tests/test_integration_settings.py` (two fixture values only, inside the active Codex Settings
  claim — flagged here so that agent is aware): `"do-not-echo"` → `"abc"` and
  un URL de test cu utilizator și parolă în el → unul doar cu nume de utilizator, so `scripts/check_secrets.py`
  passes without suppression. Both payloads still assert the same 422 refusals; all 15 settings
  tests pass.
- Initial Git commit created at the Owner's request (`ae4dee3`, branch `codex/foundation`, with a
  `main` branch pointer at the same commit): 212 files — source, tests, docs, scratch verification
  scripts. `.gitignore` extended with `backend/storage/` and `Claude outputs/` (generated media and
  screenshots); `.env`, `data/`, `output/`, `dist/`, `node_modules` were already excluded and are
  confirmed absent from the commit.

Verification at commit time: `pytest` 136 passed / 3 skipped; frontend `npm test` 11/11, `tsc`
clean, build OK; `scripts/check_docs.py` and `scripts/check_secrets.py` pass.

## Owner-directed LLM connectivity test — 2026-09-10, ZCode (third session)

Verified the Ollama Cloud integration end to end and added the missing Settings test affordance:

- Live state checked first: the "Ollama Cloud" integration (`https://ollama.com`) is saved and
  VERIFIED, 22 models discovered, all 7 agents carry an assigned model on that provider,
  autonomy stop inactive.
- Real runs through the policy kernel succeeded against the live provider: Sarah/glm-5.3-flash
  (reasoning output; token counts recorded) and Lyra/gpt-oss:120b answered
  "Da, sunt funcțional și gata să te ajut." in ~1s. Runs, tokens and events are in the audit trail.
- New: `POST /api/v1/settings/agents/{id}/test` runs one real connectivity task through the
  agent's assigned model (fixed short objective, max 800 tokens) and returns the same AgentRun
  envelope plus duration; 404 for unknown agents, policy blocks recorded as BLOCKED_* statuses.
- New: each agent card in Settings → Agenți has a "Testează răspunsul" button that surfaces the
  model's answer (or the block reason). Verified live in the browser: the button returned
  "glm-5.3-flash a răspuns: «Da, sunt complet funcțional…»".
- Test: `test_agent_llm_test_endpoint_runs_assigned_model` (provider monkeypatched; no network in
  tests). Settings suite 16/16.

## Whole-tree lint and type cleanup — 2026-09-10, ZCode

With the parallel agents' sessions finished, the committed baseline still failed the README's own
`ruff check .`, `ruff format --check .` and `mypy` (177 ruff findings, 9 mypy errors, inherited
from pre-audit and remediation code). Cleaned without behaviour change:

- `ruff format` across the tree (23 files) plus manual wrapping of the remaining 65 long lines
  (string literals split with identical content; the deterministic SVG template's XML attributes
  re-wrapped — rendering unchanged, hashes are computed at runtime).
- Auto-fixes: 22 unused imports, 11 unsorted import blocks, small UP modernisations.
- Manual: SQLAlchemy `== True` filters → `.is_(True)` (analytics), an unused local dropped
  (publishing), explicit `strict=False` on an intentionally asymmetric `zip` (office layout test),
  `requires_ffmpeg` moved below the imports it uses (E402).
- mypy: explicit `dict[str, Any]` annotations for the ffprobe result and the storyboard scene
  payloads (media/qc.py, media/assembler.py).

Verification after cleanup: `ruff check .` clean, `ruff format --check .` clean (185 files),
`mypy` clean (68 files), `pytest` 137 passed / 3 skipped, frontend `npm test` 11/11, `tsc` clean,
build OK, `check_docs.py` and `check_secrets.py` pass.

## Live speech bubbles wired end to end — 2026-09-10, ZCode (fourth session)

The speech-bubble projection existed in the frontend (handler, expiry, paper bubble renderer)
but nothing ever fed it: the backend never emitted `agent.message_sent`, and the transactional
outbox had no dispatcher, so no event was broadcast live after the initial replay. Three fixes:

1. **Producer** — `run_agent_task` now emits `agent.message_sent` (through
   `append_event_with_outbox`) in the same transaction that records the successful run, with the
   model's real output text (whitespace-normalised, capped at 200 chars) plus `run_id` and
   `task_type`. Per `../architecture/06_BACKEND_EVENT_MODEL.md` §7 only real messages may become
   live bubbles: failed runs and successful runs with no visible text (reasoning models with a
   small budget) emit nothing.
2. **Dispatcher** — the app lifespan now runs the outbox dispatcher every second
   (`publish_pending_outbox`), broadcasting committed outbox events to WebSocket clients. It runs
   on the server's own event loop on purpose: the broadcast tasks and the sockets belong to that
   loop. This also un-silences the workflow events that were already written to the outbox.
3. **UI label** — `agent.message_sent` shows as "Agentul a răspuns" in the activity log.

Verification: three new phase-1 tests (successful run emits the event with the real text and a
PENDING outbox record; failed run emits nothing; empty visible output emits nothing). Live E2E
against Ollama Cloud with the office open: an API-triggered run for Lyra/gpt-oss:120b produced
the speech bubble above her head reading "SUNT GATA SĂ LUCREZ ÎN CABINA VOCALĂ." — the run was
fired from outside the page, so the bubble proves the live event chain, not page-local state.
Full suite: ruff/format/mypy clean, pytest 140 passed / 3 skipped, frontend 11/11, docs and
secret checks pass.

Known related gap (not addressed here): agent runtime-state changes (THINKING/IDLE) are column
updates without events, so the state tag above the head updates on layout refresh rather than
instantly.

## Research agent works the pipeline; office fully live — 2026-09-10, ZCode (fifth session)

Two increments, both verified against the configured Ollama Cloud provider:

**1. The office is fully live.** `run_agent_task` now emits `agent.state_changed`
(THINKING at start, IDLE at completion) through the outbox, and `agent.paused`/`agent.resumed`
were moved onto the outbox too — the state tag above each character's head and the pause
animation now follow backend events in real time instead of waiting for a layout refresh.

**2. The research agent actually reads sources.** New
`POST /api/v1/factual/sources/{id}/extract-with-agent` (`backend/app/factual/agent_pipeline.py`):
the LeadResearcher agent (or any given ACTIVE agent with a model) receives the source's
sanitized text inside the inert `<untrusted_source_evidence>` boundary, extracts up to 12
atomic claims through its real LLM, and the JSON is strictly schema-validated before anything
is stored. Every claim lands **UNVERIFIED** regardless of the model's confidence — the model
that read the source is never the one that verifies it. Unparseable output raises (422) and
stores nothing. A truncated JSON list (token cap hit mid-item) keeps only the complete
objects — the dangling partial claim is dropped, never guessed. The agent announces a human
summary ("Am extras N afirmații...") as its speech bubble instead of raw JSON
(`run_agent_task` gained an `emit_message` flag for structured pipelines).

Live evidence: the IANA Example Domains page was fetched with the research retrieval adapter
(real SHA-256 provenance) and ingested; Dr. Aris (nemotron-3-super) returned 9 accurate claims
(RFC 2606/6761 reservations, registration restrictions, subdomain guidance) recorded UNVERIFIED,
and his speech bubble appeared in the 2D office. Phase 4 remains partial: keyword
search/discovery and an independently authorized fact-checker are still open.

Tests: 4 pipeline tests (stubbed adapter: valid JSON with fences; unparseable output rejected
with nothing stored; policy STOP blocks before any claim; truncated list keeps only complete
claims), phase-1 run tests extended to assert THINKING/IDLE state events. Suite: 144 passed /
3 skipped; ruff, ruff format, mypy, docs and secret checks pass.

## Codex Settings completion and bug audit — 2026-09-10T09:23

Scope resumed on current tree after ZCode additions: finish Settings channel binding UI, reproduce five factual-pipeline test failures, fix confirmed hardcoded operational claims and model availability guards. Preserve concurrent office/research additions. Baseline: 199 passed, 5 failed, 3 skipped; Ruff passed. No production credentials or messages will be generated during tests.

## Codex premium pixel office — 2026-09-10T14:55

Active claim: frontend/src/office_engine.js and a dedicated visual-art module; visual verification artifacts and tracking docs. Owner requested richer pixel characters, architecture, furniture, street people, dogs and cars. Preserve backend projections and concurrent Settings/research changes. Earlier audit verification/handoff remains to finish after this visual increment.

## Codex pixel office — verified, scope released

Visual increment completed; see `PIXEL_OFFICE_REFINEMENT.md`. Added material library, refined building/furniture/characters/dogs/cars/foliage, moved camera controls below the scene and fixed portrait framing. Frontend typecheck/build passed, 18 tests passed; Playwright desktop/fullscreen/mobile and real agent selection passed with zero page errors. Port 8000 serves the rebuilt assets. No backend or provider execution was part of this increment. Concurrent media changes preserved; earlier audit scope remains separately tracked.

## Codex street simulation — active claim

Owner requested round wheels/correct vehicle depth, randomized vehicle/pedestrian activities, animals and a local-clock day/night cycle. Scope: office_engine.js, new street simulation module, frontend tests and tracking docs. Decorative street events remain separate from operational agent events.

## Codex ambient street — complete, scope released

Round pixel wheels and far-to-near vehicle rendering fixed. Added session RNG, ten vehicle models, randomized pedestrian/animal activities, 48 shuffled decorative phrases and local-clock day/night density/lighting. 25 frontend tests, typecheck/build and browser 12:00/03:00 checks passed. Existing agent selection/mobile browser QA passed. See `STREET_LIFE.md` for limits, time semantics and screenshots. No operational backend changes.

## Codex weekly street rhythm — active claim

Refine ambient-life probabilities by local hour and weekday, including weekend nightlife crossing midnight, ordinary passersby throughout the day, coordinated groups and commute props. Scope limited to street simulation, renderer activity props, tests and docs.

## Codex weekly street rhythm — verified, scope released

Replaced exclusive time bins with blended weekday/hour activity and vehicle probabilities. Added morning runners, visible commuters/shoppers, coordinated social groups, weekend nightlife continuing after midnight and quieter Sunday evenings. Ordinary passersby remain possible throughout; groups cannot monopolize the scene. 33 frontend tests pass, typecheck/build pass, five fixed-clock weekly browser scenarios and desktop/mobile/agent selection pass. See `STREET_LIFE.md`. No backend/provider work in this scope.

## Codex outdoor Bucharest clock — active claim

Add a pixel electronic exterior clock, 24-hour HH:mm, Europe/Bucharest with DST. Align decorative street schedule with the same timezone. Scope: clock module, renderer, street time conversion and tests.

## Codex Bucharest clock — verified

Exterior seven-segment HH:mm display added at the building base. Intl Europe/Bucharest supplies DST-aware time and weekday independently of device timezone; street rhythms share this time basis. Typecheck/build, 35 frontend tests (including both DST transitions) and browser canvas/mobile/selection checks passed. Owner has asked about bar placement; clarification pending before changing its location.

## Codex street clock placement / toolbar consistency — active

Owner clarified: controls must match the bottom dock preview; electronic clock should be a freestanding street object to one side. Fix stylesheet packaging under existing CSP and place a sculptural pixel clock to the right. Preserve concurrent dashboard additions.

## Codex clock placement / toolbar — verified, scope released

Moved HH:mm Bucharest clock off the building base onto a sculptural freestanding support at the right pavement edge, based on Owner reference images. Fixed actual toolbar inconsistency: Vite inlined the small dynamic stylesheet as a data URL, blocked by the app CSP; ?no-inline now emits a same-origin CSS asset. No CSP relaxation. Browser asserts stylesheet loaded and dock bottom placement in normal/fullscreen, mobile overflow and real agent selection; zero page errors. Main port 8000 serves the new CSS with HTTP 200. Typecheck/build passed.

## Codex inspector model mismatch — active claim

Read-only live reproduction: /office/layout omits all model fields while /settings reports Sarah has a persisted model_id. Running server exposes an older layout shape. Fix inspector to resolve authoritative agent/provider model records on open, distinguish loading/error from no assignment, and discard stale responses. No model/provider execution or reassignment.

## Codex inspector model mismatch — verified, scope released

Resolved assigned models directly from persisted agent/provider catalogs when opening the inspector; old /office/layout omissions no longer imply no assignment. Loading/error/unverified states are distinct. Added stale-request guards including queued close events. 38 frontend tests and typecheck/build pass. Read-only browser verification on actual port 8000 matched all 7 agents to Settings, including Sarah/glm-5.3-flash; no LLM calls or writes. See `INSPECTOR_MODEL_FIX.md`.

## Codex articulated street actors — active claim

Owner rejects translated walking sprites and disconnected props. Replace ambient human rendering with contact-driven articulated poses for walk/run/cycle/skate/phone/briefcase; add varied appearances and fix clock occlusion. Research: BioMotionLab and Blender IK documentation. Scope street_actor module, ambient update/renderer, tests and visual QA; operational employees/backend preserved.

## Migration-branch unification and full-tree verification — 2026-09-10, ZCode (sixth session)

The parallel sessions had advanced the project massively but left the tree unable to run:
two concurrent revisions after `0011_claim_attribution` (`0012_channel_verification` and
`0012_workforce -> 0013_story -> 0014_runbook`) gave Alembic two heads, so every
`upgrade head` — every test fixture and every bootstrap — failed with 243 errors, and
`main.py` pinned yet another revision. Verified where each session had got to, then:

- `0015_merge_heads` merges both branches into a single head (no schema of its own);
  `main.py` now pins `0015_merge_heads`. Live database bootstrapped through it.
- The 13 Phase-10 runbook failures were environmental, not logical: FFmpeg is a BLOCKING
  preflight check and this machine (like CI) has no FFmpeg. The `studio` fixture now names
  a stub path when no real encoder exists — the stage state machine stays observable
  everywhere; the real encoder path remains covered by the Phase-5 skips.
- ZCode's earlier writer tests were superseded by the parallel session's stronger
  `script_agent.py` implementation (scene-level claim citations) and its
  `test_script_writing.py` suite; the superseded tests were removed. The extraction
  pipeline tests (7) remain.

Combined tree verification: pytest **306 passed / 6 skipped**, ruff + ruff format clean,
mypy clean (89 files), frontend `tsc` clean, **38/38 frontend tests**, Vite build OK
(142.8 kB), docs integrity and secret scan pass. Live studio restarted on `0015_merge_heads`.

## FFmpeg installed on the dev machine — 2026-09-10, ZCode

Owner-approved system change: FFmpeg 9.0.1 (full build, via winget/Gyan) is installed and on
the user PATH; `.env` pins `STUDIO_FFMPEG_PATH` to the absolute executable. The studio's
live preflight moved from BLOCKED to **DEGRADED** — render_engine and media_inspection are
now OK; the remaining degradations are exactly the unlinked credentials (image provider,
voice provider, YouTube) and the empty research allowlist. Full suite with the real encoder
on PATH: **311 passed / 1 skipped** (the render tests no longer skip and pass on the real
FFmpeg path). Future `start.cmd` launches pick FFmpeg up from the registry PATH.
