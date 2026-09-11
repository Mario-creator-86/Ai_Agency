# Changelog

## The stewards read the vendors' pages; the studio reads what people search for — 2026-09-12

The Owner asked how employees could choose a video model by researching online, and that
the analytics machinery exist before the numbers do.

- **Model research** (`backend/app/media/model_research.py`): the steward of a purpose
  (Kael for video and image, Lyra for voice) names up to three pages worth reading on the
  vendor's own site, the studio fetches them over the source retriever restricted to the
  vendor's hosts (`vendor_hosts` from the catalogue's documentation URL — no employee has
  a tool that reaches anywhere else), and the steward scores every model the account
  exposes (quality, reliability, speed, price with its unit, a note, the page as evidence).
  Scores and prices go into `provider_resource.capabilities/pricing` with the source, where
  `rank_candidates` and `strategy: auto` already read them (`per_second_usd` and
  `per_image_usd` now count as prices too). The recommended model becomes the default only
  where the Owner left it as a fallback (`allow_production_override`); a locked default is
  reported on. Every run ends in a letter to the Director. Weekly job
  `model_research_weekly`, Owner button in Settings → Video și sunet, `POST
  /settings/model-research`.
- **Trends** (`backend/app/analytics/trends.py`, migration 0028 `trend_snapshot`): Google's
  public "trending now" feed for the studio's country (`STUDIO_TRENDS_GEO`, default RO), read
  once a day over pinned HTTPS, kept as rows; a feed that does not answer is recorded as
  `trends.unavailable`. The Researcher's proposals get `trending_now` and
  `measured_performance` (the studio's own cohorts of three or more videos, best and worst);
  the weekly digest lists the week's trends; a trend is a hook, never a source. Daily job
  `trends_daily`, the idea stage refreshes when stale, `GET/POST /analytics/trends`, and a
  «Ce caută lumea acum» block in the research dialog.
- Tests: `tests/test_signals.py` (10), `tests/test_scheduler_worker.py`; live: the RO feed
  read once (10 trends, with traffic and news).

## The office writes letters, and the Director writes to the Owner — 2026-09-12

What stopped the day of 2026-09-11 (12/12 stages "completed", nothing produced), and the
correspondence the Owner asked for.

- **The real adapter.** The studio's connections run through `ConfiguredLLM`
  (`backend/app/integrations/llm.py`), not `app.providers.ollama`; the thinking-off fix of
  2026-09-11 had gone into the wrong class, so every run on the Owner's Ollama Cloud still
  spent its whole token budget on reasoning and returned nothing. `think: false` is now sent
  by the adapter the studio uses, `done_reason` travels back, and the socket timeout is ten
  minutes instead of thirty seconds ("time-out" was the browser and the socket, not the model).
- **A stuck employee.** Dr. Aris sat in THINKING all day — a flag left by a run the process
  never came back to — and every stage that needed him was refused "already has an active
  task". A run is now a record from the moment the model is called (`RUNNING`, closed as
  `ABANDONED` after 45 minutes); a THINKING flag with no run behind it is cleared, not obeyed.
- **Token budgets ×3** on every task (fact-check 2 100, Director review 7 500, scripts 9 000…).
- **Media setup finishes itself.** A verified image or voice connection with no default model
  or voice reported `NO_DEFAULT` until the Owner found a form; the day now runs the existing
  `auto_configure` before its preflight when readiness says something is empty.
- **Letters** (migration 0027): a message has a thread, a reply, and the letter itself
  (`thread_id`, `in_reply_to`, `body_text`). Forwarding keeps the thread, so everyone on it
  reads the same exchange. The Director's decisions are letters in the thread they answer;
  stage reports carry their reason as text. An employee's open letters enter its prompt with
  the last three turns of their thread.
- **Employees answer their mail** (`backend/app/agents/mail.py`): the worker answers, each
  pass, the letters that ask for something — in the employee's voice, in the thread — and
  the Director reads what came back at once. A question closes with its answer; a HANDOFF
  stays open until the employee says the work is done; a report waits for nobody; a thread
  past eight letters is left to the evening review or the Owner.
- **Letters to the Owner.** When a decision is the Owner's, or the day stopped, or the
  evening review could not run, the Director writes to the Owner: what stopped, where, what
  she needs. Such letters are out of her own inbox, in red in the ledger under the Owner
  chip, and wait for the Owner's reply, which closes them and reaches her; her answer to the
  Owner is again addressed to the Owner. `GET /agents/messages/owner`.
- **The page**: a letter in the ledger names both ends and opens its thread
  (`frontend/src/mail_thread.js`): who wrote to whom, when, about what, the text, how it
  ended; the Owner writes back from the bottom. The inspector's inbox opens threads too.
- API: `GET /agents/messages/threads/{id}`, `POST /agents/messages/{id}/reply`,
  `POST /agents/messages/{id}/forward`, `GET /agents/messages/owner`.
- Tests: `tests/test_mail.py` (18), `tests/test_audit_regressions.py`,
  `frontend/tests/mail_thread.test.js`, `frontend/tests/ledger.test.js`.

## The Director's mandate: grow views and retention — 2026-09-11, ZCode

The Owner's decree, made mechanical:

- **Sarah's mission** (role row + migration 0026): growing views and retention is her
  primary charge; she directs every department in writing, steers channels and topics from
  measured analytics, documents every decision.
- **Contract v3**: she may instruct any employee, change channel direction and topics on
  the measured evidence, and request a larger budget from the Accountant with the numbers
  and the reason written down. The Accountant must answer every budget request from the
  books and escalate it — only the Owner can raise a budget, and nothing in this change
  gives an agent that power.
- **The weekly review became the mandate's instrument.** Her answer is structured JSON,
  validated before anything is stored: verdict; sound indications → Lyra; video indications
  → Kael; channel direction and topic changes → LeadResearcher and ScriptWriter (and
  remembered as STRATEGY); budget request → the Accountant; escalation → the Owner. Every
  piece lands as a message that enters that employee's runs, the office hears her spoken
  summary, and her inbox keeps the full review. An answer that breaks the schema files
  nothing and says so.
- **The Accountant answers at the daily close**: every open budget request is answered with
  the day's computed figures, resolved as transmitted, and the close escalates to the Owner.

Backend 528 passed / 1 skipped; ruff, format, mypy clean; frontend 79/79. Live: server on
0026, mission and contracts confirmed, weekly review re-run honestly skipped at zero tokens.

## Sound, video and a Director who checks weekly — the roles the Owner ordered — 2026-09-11, ZCode

- **The contracts say who does what now.** Seed v2 (migration 0025, data-only; a role the
  Owner edited keeps the Owner's text): the sound artist chooses the voice and TTS model
  where the policy allows and follows the Director's written indications; the video editor
  picks film models by quality, recorded cost and what kept viewers watching; the Director
  decides from measured performance, instructs the two departments in writing, and never
  skips the weekly review while anything published exists.
- **Indications travel.** Open messages addressed to an employee enter that employee's every
  run ("WHAT IS ASKED OF YOU RIGHT NOW", identity v2, capped at ten, recorded on the run).
  The Director files a HANDOFF to the sound or video department; from the next run onward
  the employee works under it until it is resolved.
- **The weekly review exists.** Every seven days (standing policy, autonomy stop still
  gates) or on the Owner's new button in the runbook panel, the studio compiles the week's
  measured picture — views, retention, click-through per published video, per-channel
  totals, open strategy recommendations — and puts it in front of the Director through her
  identity and memory. Her answer becomes HANDOFF indications to Lyra and Kael plus a STATUS
  report in her inbox. A week with nothing published reports exactly that and spends no
  tokens; the clock reviews a week once. Live-verified: the first run answered "Revizia
  săptămânală 2026-S37: nimic publicat, nimic de măsurat".
- Failed agent runs log the exception with its traceback.
- Backend 526 passed / 1 skipped; ruff, format, mypy clean; frontend 79/79; UI checks 5/5
  in Chromium. Limits, honestly: with no publications and no bound voices/models, the review
  and the locks have nothing to chew on until the Owner configures them — the machinery
  waits ready.

## What the Owner asked about the pipeline, and an expandable inspector — 2026-09-11, ZCode

Investigation turn; one small frontend addition.

- **Sarah did not write twice by accident.** The two 21:58/21:59 ledger lines are two real
  `owner_chat` runs — the first verification pass sent the same question twice; each run has
  its own row and its own freshly generated answer. No duplication bug.
- **"Niciun cont YouTube verificat" was true when written, and no longer is.** The daily run
  started 20:17:03; the channel slots were bound to their accounts at 20:18:54 and 20:19:02
  (`channel.credentials_bound`). Re-ran the stage's own resolution against the live
  database: both bindings `publisher_ready`, the analytics adapter builds. The next run
  reports "Nicio publicare reală de măsurat" instead of the skip.
- **Agents see only what their prompt carries.** No tool-calling exists anywhere in
  `run_agent_task`: a run is one prompt to one model. Every STATUS/ESCALATE an employee
  "says" is written by deterministic pipeline code in its name — Sarah never read the
  YouTube state herself; the stage told the studio (and her report) what it found.
- **Per-channel production criteria are implemented; the data is not dressed yet.** The full
  hierarchy (organization → channel → series → episode → scene → character lock) is live in
  `media/production_policy.py`, `render_plan` resolves it per scene into real ElevenLabs
  TTS / Runway video adapters and records the plan on the render job. Channel A is FLEXIBLE
  (episode/scene may swap voices and film models, `strategy: auto` ranks candidates by
  stored quality/cost/speed/language), Channel B is CONSISTENCY_LOCKED (technology changes
  at episode/scene are ignored with a note; a locked character keeps its bound voice;
  visual locks refuse unapproved video models; changes go through the identity-change
  approval workflow). What is missing is configuration, not code: no character has a bound
  or locked voice, no storyboard names its channel, and no organization default model/voice
  is chosen — until those are set, the locks have nothing to hold.
- **«⛶ Extinde» on the Agent Inspector.** The dialog fills the screen and the entire
  history — every run, message, memory, every question and answer — becomes one
  traversable page instead of a box with its own scrollbar; the button restores the normal
  size. Verified in Chromium (expand, restore, 16/16 checks).

## The conversation reads like one: answers in words, a chat, and a window into the work — 2026-09-11, ZCode

Owner-reported: a structured answer printed as raw JSON, cramped cards, no way to watch an
employee at work. All three fixed in the frontend, against the already-recorded data.

- **An answer is written for a person.** A run whose output is JSON — chosen pages, extracted
  claims, proposed topics, scenes, a verdict — renders as sentences and lists with links;
  the model's exact output stays one click away under «Răspunsul exact al modelului». An
  answer cut off mid-list by the token limit now has its complete items salvaged and shown
  with a note, instead of printing the broken JSON (the backend already kept those items;
  the display finally agrees). Old runs whose only line was the engineered prompt no longer
  print 240 characters of instructions as the headline — the chip says what the job was and
  the full prompt stays under «Cererea completă». Nothing stopped being saved: everything
  lives on the run, as before.
- **The conversation is a conversation.** Owner questions render right in the studio green,
  employee answers left on paper. While the employee works the panel says "scrie…", driven
  by the real THINKING/IDLE events, and the history refreshes itself when the answer, a
  report or a completed run lands — including runs fired from outside the page. Verified
  with a real chat turn to Sarah (glm-5.3-flash), and again after a reload: the exchange
  was on the run all along.
- **A window into the work.** The inspector's new «Fereastră live ↗» opens a standalone
  window for one employee: the current state as a pill ("THINKING"), a head line ("Acum:
  lucrează la sarcina propose topics"), and the employee's own event chain — starting work,
  what it says, what it finishes — seeded with the day and updated from every new event,
  from the socket or the events endpoint alike. The inspector keeps every detail of each
  action; the window is the live view. The popup is styled through CSSOM because the page
  CSP (rightly) forbids inline styles in it.
- New modules `friendly_text.js` and `live_window.js`, both pure-tested (14 new frontend
  tests; 79 total). `Ledger` gained an `onEvents` callback so the live windows see exactly
  the stream the ledger renders. Verified in Chromium against the running studio:
  14/14 checks (`scratch/verify_conversation_live.mjs`), screenshots under
  `output/playwright/conversation-*.png`.

## Three things the Owner reported: a silent start, a prompt for a task, twin entries — 2026-09-11

- **Starting the day answers at once.** `POST /runbook/runs` executed the whole run inside the
  request — twelve stages, minutes of work — while the page gave up after ten seconds and said
  "Conexiune indisponibilă", though the studio kept working. The button now queues the day
  (the same `DAILY_RUN` task the schedule uses, `manual: true` so it may repeat a day the
  clock would not) and answers "Rularea de azi a fost pornită". A second press, a stopped
  autonomy, safe mode and a disabled worker each refuse with their own sentence.
  `GET /runbook/runs` also returns `pending`, and the panel shows the day on its way.
- **Where production is, while it is there.** `runbook.daily_run_started`,
  `runbook.stage_started` and `runbook.stage_finished` go through the outbox, so the ledger
  reads "etapă pornită · producția media (7/12)" as it happens and its head line says
  "Acum: producția media".
- **A task reads as a sentence.** Runs recorded the engineered prompt as what was asked, so
  five fact-checks in a row opened with the same nine hundred words and looked like one entry
  repeated — the claim was buried in the middle. `run_agent_task(..., summary=...)` carries
  the employee's own sentence ("Verific afirmația: «…»", "Închid ziua: 0 USD azi…"); the
  history shows it, with the full prompt under «Cererea completă». Older runs keep their
  prompt, trimmed to a readable line.
- **An answer nobody can read is not an answer.** Ollama counts a thinking model's private
  reasoning against `num_predict`: `qwen3.5:397b` asked for 700 tokens spent all 700 thinking
  and returned an empty response with `done_reason: length` — recorded as SUCCEEDED with
  nothing under it (17 of 18 fact-checks, both Director reviews, the Accountant's close).
  Generation now asks for thinking off, and a run with no text is recorded `EMPTY_OUTPUT`
  with the reason instead of a green line.
- **Nothing is said twice.** A report an employee files is both a message and a memory in the
  same words; the timeline now shows the message and drops the copy — the memory itself is
  untouched, so the next run still has it.
- Tests: `tests/test_phase10_runbook.py` (queued start, refusals, stage events),
  `tests/test_books_and_history.py`, `tests/test_ollama_adapter.py`,
  `tests/test_phase1_agents.py`, `frontend/tests/ledger.test.js`.

## The Owner watches the pipeline live from a ledger beside the office — 2026-09-11

- **Live ledger** (`frontend/src/ledger.js`, pure and tested): the left column of the
  workspace lists what is happening now and what happened today — every message an employee
  sends or files (by name, with its intent and subject), every task started or finished,
  every workflow stage, provider cost, budget event and Owner action — in words, newest
  first, with filters (Vorbe / Producție / Personal / Bani / Owner). The head line says where
  production stands (current stage, last daily run). Events arrive over the WebSocket as
  before; on load the ledger backfills up to 600 events through `GET /events` (limit now up
  to 300 per page).
- **Layout**: the office is first and wide (`380px | rest`, height up to 76 vh); Owner Control
  and Workforce panels, the page heading and the FOUNDATION notice are gone. Connection
  status, Settings and logout live in the top bar.
- **Autonomy switch**: one ON/OFF toggle in the office toolbar, styled as game chrome,
  replaces the STOP AUTONOMY button; it still posts `POST /owner/autonomy-stop`.
- **The books report carries the Accountant's name.** `post_run` turned Nadia's close into a
  stage report with no status and filed it as the Director's. The report now carries her
  intent, headline and holds, and is filed by her (`config/role_contracts.json`,
  `backend/app/runbook/stages.py`, `backend/app/agents/director.py`).
- Tests: `frontend/tests/ledger.test.js`, `tests/test_books_and_history.py`.

## The Accountant keeps the books; every employee has a history and a chat — 2026-09-11

Write-up: `ACCOUNTING_AND_HISTORY.md`.

- **Speech bubbles read the whole answer.** Same box, three lines; the text pages through
  at reading speed with a page counter, and the bubble stays up as long as reading takes.
  `frontend/src/speech_bubble.js` (pure, tested); the event carries 1 200 characters.
- **History and chat per employee.** `GET /agents/{id}/history` merges runs, typed messages
  and memory into one timeline (what was asked, answered, decided and why);
  `POST /agents/{id}/chat` puts the Owner's question through the employee's identity and
  policy kernel. The Agent Inspector shows the timeline above a chat input.
- **Nadia (Accountant)**: role, work contract, Character Bible, memory scope, a desk in the
  new Accounting & Treasury office (the Coffee Lounge / Commons is gone). A studio staffed
  before the role existed hires her through `seed_missing_workforce()`.
- **Budget** (migration 0024, `spending_budget`): daily and monthly limits set by the Owner
  in Trezorerie; spend measured from the books (estimates and bills), unpriced usage reported
  as such. The media stage refuses a render an exceeded budget cannot afford; every render's
  narration is costed per scene at the stored price; the Accountant closes the day in
  `post_run` before the Director's review and escalates a warning or an exceeded budget.
- API: `GET/PUT /economy/budget`, `GET /economy/books/daily`, `POST /economy/books/close`.
- Tests: `tests/test_books_and_history.py`, `frontend/tests/speech_bubble.test.js`.

## The pipeline has no empty stages left, and a channel knows its account — 2026-09-11

Everything was connected and nothing worked: the publishing screen answered "Internal error",
images and voice were reported missing, analytics found no account, and idea generation was
skipped. Audit and fixes: `PIPELINE_COVERAGE.md`.

- **The 500 is gone.** `GET /publishing/channels` asked `selected_youtube()` for the studio's
  one publisher; with two accounts connected and no channel naming either, that refusal became
  a 500, and the screen printed it into both panels. Publishing is per slot, so the endpoint
  answers per slot: the account each channel is bound to, and the accounts available to bind.
- **Channel ↔ account binding is visible and one click** in Publicare → Sloturi de canale. The
  publish stage uploads through the bound account instead of "the first channel row", the
  analytics stage measures through it, and the preflight names an unbound slot as the missing
  step.
- **`POST /settings/auto-configure`** (a button in Settings → Video și sunet) selects a service
  for a purpose where exactly one verified connection can serve it and fills only empty
  defaults, preferring a model the pipeline can call from a prompt. It reports every choice
  with its reason, refuses to resolve an ambiguous purpose, and never replaces the Owner's own.
- **Idea generation exists** (runbook §3): the Lead Researcher proposes candidates scored on
  the six criteria, deduplicated by title similarity, limited to hosts the Owner authorised;
  duplicates and unauthorised sites are dropped with the reason.
- **Research fetches its own pages** (§4): the Researcher names URLs on authorised hosts and
  the studio downloads each one itself, so an invented URL simply fails and a real one is
  stored with the text that came back.
- **The Director selects the day's topic** (§5) among candidates that have a verified claim,
  and the decision is recorded on the topic (`decided_by`, `decision_notes`); a choice that
  names nothing on the shortlist falls back to the deterministic order.
- **Every dialog is one width** (1180px, 94vw) instead of 520–950px: reports, contracts,
  source lists and production plans were being read through a narrow strip.
- Migration 0023 (`topic_idea`: scores, source plan, proposer, decision);
  `tests/test_pipeline_coverage.py`.

## The preflight names the missing step; Runway makes stills; sites are added and tested — 2026-09-11

The Owner had a verified ElevenLabs key selected for voice and a verified Runway key, and the
preflight still said "no verified image/voice provider". The connections were fine; no default
model and voice had been chosen, and nothing said so.

- `media.factory.media_readiness()`: per purpose, READY / NO_SELECTION / NOT_VERIFIED /
  NO_DEFAULT / NO_ADAPTER with the next action in the Owner's words; the preflight's image and
  voice checks use it ("X este verificat și ales pentru Voce / TTS, dar nu are un model și o
  voce implicită…").
- Runway serves images too: `RunwayImageAdapter` (text_to_image task, polled, measured from
  the bytes), a per-purpose usability from the discovered contract (`usable_purposes`), an
  image default on the connection (`MediaProductionConfig.image_model_id`, "Model imagine
  implicit" in Settings) and purpose-aware validation in the hierarchy. `CATALOG["runway"]`
  now lists `video` and `image`.
- Authorised source sites are an Owner action in the interface, not only a line in `.env`:
  `research_allowed_host` (migration 0022), `PUT/DELETE /factual/sources/allowed-hosts/{host}`
  with the same public-hostname rules as the configuration file, and
  `POST …/{host}/test`, which fetches the site's front page through the real retriever and
  records PASSED or the exact reason it cannot be read. The research modal lists hosts with
  their origin and last test; the preflight counts the tested ones. No agent has a tool that
  reaches these endpoints. Tests: `tests/test_sources_and_readiness.py`.
- `migrate()` runs table rebuilds with foreign keys suspended (the live studio's 0021 failed
  on referenced rows); regression test in `tests/test_foundation.py`.

## Every employee has an identity, a memory and a report to file — 2026-09-11

The model was never told who it was: `run_agent_task` sent the task text alone. Now every run
carries a system prompt composed from stored data (name, role, mission, allowed and prohibited
tasks, work contract, character voice, memory the role may read, standing rules) and records
the manifest of it on the run. Write-up: `AGENT_IDENTITY_MEMORY.md`.

- `config/role_contracts.json` → `role.work_contract_json` / `memory_scope_json` (what each
  role watches, investigates, corrects, lets pass, never lets pass, escalates; who it reports
  to; which stages it owns). Seeded, Owner-editable, never overwritten by a reseed.
- Character Bible entries are linked to the employees holding their roles.
- `memory_record` (04_AGENT_SYSTEM §9 classes) written by services on real outcomes with
  provenance, expiry and invalidation; read by role scope; ids recorded per run.
- `agent_message` with the spec's intents; the Director's inbox; events through the outbox.
- Lyra reviews narration, Kael diagnoses failed renders, Vera prepares publication metadata
  and may HOLD a candidate; the runbook publishes with her metadata or not at all.
- `post_run` is the Director's desk: stage reports filed by their owners, then Sarah's review
  (ACKNOWLEDGE / REQUEST_INVESTIGATION / APPROVE / REJECT / ESCALATE_TO_OWNER) as messages and
  memory, never as a change to a gate.
- API and Agent Inspector expose identity, contract, memory, messages and the prompt itself.
- Migration 0022; `tests/test_agent_identity.py`.

## Runway: name and key only, models read from the account — 2026-09-11

The Runway connection form asked for a "Model ID" and stored it as a preference; nothing
verified the key or read the account. Now it is the same flow ElevenLabs has, through the same
code: save name + key → key verified → models discovered → optional default → production.

- `DISCOVERED_KINDS` (`integrations/discovery.py`) replaces the `kind == "elevenlabs"`
  branches in save/verify/refresh/catalog/default/validation; ElevenLabs and Runway share one
  discovery, one `ProviderResource` inventory and one `MediaProductionConfig` default.
- `providers/runway.py`: a `VideoProvider`. Models come from `GET /v1/organization`
  (`tier.models`, limits, usage); tasks, ratios and durations per model from Runway's
  published OpenAPI contract for the same API version. No model id, ratio or duration in code.
  `create_generation` / `get_generation_status` implement the task + poll flow;
  `factory.video_provider_for()` and `render_plan()["video_for_scene"]` expose it.
- `CATALOG["runway"]`: `[KEY]`, runtime `media`. The Settings card shows "Model video
  implicit" with the override switch; only discovered models that make video are selectable.
  The "Verify" button is no longer hidden for Runway. `elevenlabs_settings.js` became the
  generic `provider_production.js`, driven by the catalog's `kind_info`.
- Per-scene plans resolve `video` with the scene's cast: a character with a locked `visual`
  identity accepts only video models in its approved list, on any channel. The flexible /
  locked channel rules for video models were already in place and are now tested with a real
  video catalogue (`tests/test_production_policy.py`), plus `tests/test_runway_connection.py`.

## Two channels, two production policies — 2026-09-11

Technology (providers, models, voices) is replaceable; a recurring character is a persistent
creative asset. Nexus Curiosity (MAIN_FACTUAL) may pick its technology per video; Inside The
Nexus (OFFICE_SERIAL) keeps its characters' identities whatever the technology underneath.
Audit first, reuse second, extend third: no new agents, registry, discovery or production path.

- The connection's model/voice (`MediaProductionConfig`) is now the Organization default with
  `allow_production_override`; the Settings card calls them "Model implicit" / "Voce implicită".
- A configuration hierarchy in `backend/app/media/production_policy.py`: Organization → Channel
  (`production_policy`, `production_defaults_json`, `series_rules_json`) → Series → Episode
  (`Storyboard.channel_id`, `series_key`, overrides) → Scene → Character. Later levels win,
  except a locked character field, which wins over everything. A selection is valid only if
  it names a verified connection and discovered, available resources.
- FLEXIBLE channels may ask for `strategy: auto`, ranked from stored research annotations
  (quality, reliability, latency, price, language) — never from a preference in code.
  CONSISTENCY_LOCKED channels keep technology decisions at channel/series level and refuse
  automatic voice choice.
- Character identity locks: `voice_binding_json`, `identity_locks_json` (voice, visual,
  personality, speech style), `approved_fallbacks_json`, `consistency_status`. A newer model
  reaches a locked voice only through an approved fallback. Identity changes go through
  `CharacterIdentityChange`: PROPOSED → TESTING → APPROVED | REJECTED; only APPROVED rewrites
  the bible. Rebinding a locked voice directly returns 409.
- Renders (API and daily runbook) resolve a plan per storyboard and per scene, so a scene that
  casts a locked character is voiced by that character's voice; `VideoRenderJob.production_json`
  records provider, model, voice, characters, audio seconds, synthesis time and attempts.
- Migration 0021 adds the columns and the workflow table with neutral defaults; the channel
  seed fills only a NULL policy from `DEFAULT_CHANNELS`. Rehearsed on a copy of the live
  database: connections, secrets, discovered resources, defaults, both YouTube channels and
  all characters unchanged.
- UI: channel cards show the policy (FLEXIBILĂ / CONSISTENȚĂ BLOCATĂ), the ElevenLabs card shows
  defaults with an override switch, character cards show the bound voice, locks and status.
- Tests: `tests/test_production_policy.py` covers the seven acceptance scenarios from the brief
  plus the identity workflow. 467 backend tests, 53 frontend tests, lint, types, format,
  documentation integrity and the secret scan pass. Write-up: `PRODUCTION_POLICY.md`.

## The Character Bible says who each employee is, not only how they look — 2026-09-11

The bible stored appearance and a voice profile. Everything the Owner listed as needed next —
personality, speaking style, expressions, behaviour, reference assets — had nowhere to live, so
a story engine asked to write for Elena had no stored answer for how Elena talks and would have
invented one per episode, which `../architecture/64_NARRATIVE_PERSONA_RELATIONSHIP_ENGINE.md` forbids.

- `character_bible` gains five columns (migration 0020): `personality_json` (traits, values,
  humor, social energy, conflict style, strengths and weaknesses), `speech_style_json`
  (register, cadence, sentence length, vocabulary, habits, language), `expressions_json`
  (greeting, agreement, disagreement, under pressure, sign-off, recurring joke),
  `behavior_json` (work rituals, gestures, desk habits, likes, dislikes) and
  `reference_assets_json`.
- The canonical seven are authored in full, consistent with the voice style and role each
  already had. Narrative only: none of it may change what an agent may do or whether a gate
  passes, which is the persona spec's core rule.
- Reference assets are declared slots — portrait, full body, front, side, back, as
  `../architecture/24_VISUAL_CONTINUITY_ASSET_SYSTEM.md` asks — and every one is null, because none have been
  produced. A description standing in for a missing image would let continuity QC believe a
  reference exists.
- Rows seeded before these fields are completed once on the next read; a field an Owner has
  edited is never overwritten. Rehearsed on a copy of the live database: revision 0019 → 0020,
  seven rows kept, thirty-five fields completed, second run writes nothing.
- The Character Bible panel showed `visual_profile_json.archetype`, `appearance_notes` and
  `voice.pace`, none of which the record has, so every card read "Specialist / Design canonic
  studio / default (normal)". It now shows the stored values and omits a line the bible does
  not carry.

Verified: 458 backend tests (3 new), 53 frontend tests, lint, types, format, documentation
integrity and the secret scan pass.

## ElevenLabs verification says what the key lacks — 2026-09-11

- Diagnosis of the Owner's "Cheia nu a putut fi verificată" after the dynamic-catalogue rework:
  the flow was correct; ElevenLabs answered HTTP 401 `missing_permissions` on `/v1/user`,
  `/v1/models` and `/v2/voices` because the key was created with restricted scopes. The
  message hid that behind a generic sentence.
- `MediaProviderError` now carries the vendor's short error identifier (`code`, e.g.
  `missing_permissions`, `invalid_api_key`) and the HTTP status; `media_http.error_code()`
  reads only closed-vocabulary slugs from error bodies, never free text, so no vendor message
  or key fragment can reach the UI or the log.
- Discovery maps the identifier to an Owner-facing instruction: restricted key → grant User
  (Read), Models (Read), Voices (Read) and Text to Speech in ElevenLabs → Developers → API
  Keys; invalid/revoked key → generate a new one; quota/concurrency → wait or check the plan.
  A key that reads the account but not the catalogue gets its own message.
- Tests: restricted key, catalogue-only restriction and invalid key are each explained
  (`test_integration_settings.py`); error-identifier parsing rejects free text
  (`test_media_providers.py`).

## Detail pass on the hand-drawn office — 2026-09-11

Owner direction after the Blender comparison: keep the hand-drawn art and raise it with
details, shadows and subtle animation, on every floor. Frontend only.

- Windows are now holes onto the scene's own backdrop: each one shows exactly what stands
  behind the building at its world coordinates, so the penthouse looks out on sky and tower
  tops while lower floors see the roofs and lit windows across the street, and the view
  follows the Bucharest clock (day/night). Six distant high-rises were added to the far
  skyline so upper floors are not looking at empty sky. The standalone room preview keeps a
  floor-aware fallback view.
- Window light spills down the wall and pools on the floor (warm by day, cool blue at night).
- Chairs are high-backed with a headrest and show around the seated figure; desks stand on the
  floor plane with feet, a pedestal to the floor, a bevelled lip, a mousepad and a cable.
- Characters: lit forehead, shadow under the chin and along the jaw, shaded right side of the
  torso, a second hair highlight; an idle glance every few seconds; the monitor's light
  catches the near cheek and shoulder while WORKING (state-driven, never decorative).
- Skirting boards on plaster, panelled and brick walls; the research lab's flasks bubble
  in their own colours.
- By day the ceiling fixtures dim to fill light and desk/floor lamps fade, so the windows
  carry the room; at night the fixtures and lamps carry it. Steam curls off the mug during the
  idle sip. Plants are pointed blades on stems, back blades in shade, front blades lit with a
  pale vein, instead of stacked blocks.
- The sun follows the real Bucharest clock across the sky (east at sunrise, high at noon,
  west at dusk). A desk's screen animates only while the agent seated at that desk is
  WORKING; screens without a desk (shopfront, dispatch) still follow their zone.
- Verified: 53 frontend tests, tsc/build clean, 61 FPS at fit and 2.2x (median draw 7.7 ms).

## YouTube channel avatars — 2026-09-11

- Select the API-provided thumbnail URL in high, medium, default order and persist it in each
  connection's existing JSON snapshot on authorization, completed reconnect and Verify.
- Fix the actual browser failure: `img-src` now permits the two YouTube avatar CDN origins.
  Keep all other CSP directives unchanged. No image URL or channel identity is hardcoded.
- Render a neutral CSS avatar only for a missing thumbnail; real images retain their API URL
  and send no referrer. The full frontend build and 52 frontend tests pass.
- Live Chromium verification clicked Verify for Nexus Curiosity and Inside The Nexus: both
  URLs persisted, both images decoded at 800×800, and no image CSP violations occurred.
  `scripts/verify_youtube_avatars.mjs` records live evidence separately from its missing-image fixture.
  Reconnect callback refresh and connection isolation are covered by stubbed Google regression tests.

## Pixel-art pipeline: the Research floor rendered from Blender — 2026-09-11

- The 2D office's art can now come from Blender renders instead of hand-placed rectangles.
  `art-source/blender/` builds every prop, wall/floor tile and character part in 3D from the
  palette exported out of `office_palette.js`, renders it at 1 world px = 1 sprite px with toon
  ramps (no anti-aliasing), snaps every pixel to the palette and adds the renderer's 1 px
  outline. Output lands in `frontend/public/assets/{pixel/office,environment,sprites/characters}`
  with `atlas.json` / `parts.json` manifests (anchors, screen rectangles, lamp points).
- `frontend/src/office_atlas.js` loads the manifests and recolours the key-coloured character
  parts per agent look, so identity, costume-per-role and posture-from-backend-state rules are
  unchanged. `office_rooms.js` draws a zone from the atlas only if it is in `ATLAS_ZONES`
  (RESEARCH, the quality bar) **and** the atlas has loaded; every other case is the procedural
  art, so nothing ever renders as a hole.
- The premium floor shows a 10 px 3/4 floor plane, wainscot with dado, skirting and picture
  rail, volumetric desks and chairs, a lab bench, shelves, evidence board and fillers, all under
  one key light. Desk plane, seat and hit-test geometry are the same numbers as before.
- Unreal Engine 5.8 is used as a reference tool only: `export_floor_scene.py` composes the floor
  as glTF and `art-source/unreal/build_reference_scene.py` builds a lit, ortho-camera level in
  the `AMNReference` project for lighting/composition checks. Nothing from it ships.
- Outcome: after the live comparison the Owner judged both the rendered characters and the
  rendered rooms/furniture below the hand-drawn art, so `ATLAS_ZONES` and
  `ATLAS_CHARACTER_ZONES` are empty and every floor draws the procedural art. The pipeline and
  its assets stay in the repository, switched off.
- The Character Bible (`/media/character-bible`) is now authoritative for how the office draws
  each employee: hair colour and style, glasses, headset and outfit colours come from the
  bible entry matched by employee link or first name; the per-agent hash only fills what the
  bible leaves open. Applies to every floor, procedural or atlas.
- Verified: 53 frontend tests (5 new), tsc/build clean, ruff/mypy/docs/secrets clean, live
  studio with seven agents at 61 FPS (fit and 2.2×). Write-up and honest before/after in
  `PIXEL_ART_PIPELINE.md`.

## The studio runs without the browser — 2026-09-11

- Added the background worker (`backend/app/workflows/worker.py`), the part of the studio that
  was missing for it to be autonomous at all. The scheduler could be ticked and the queue could
  be claimed, and nothing did either on its own: a daily job would sit with `next_run_at` in the
  past forever, and "autonomous" meant the Owner pressing a button every day.
- One pass, every `worker_interval_seconds` (default 30): fire the due jobs, then run the queued
  tasks through a dispatch table. `DAILY_RUN` executes the runbook. Nothing fires while the
  autonomy stop is set. The scheduled daily run happens at most once per business date; a second
  run on the same day stays the Owner's decision from the panel.
- `scheduler_tick` now enqueues a task for each fired job, keyed on the job and the slot it was
  due for, so a restart that puts the slot back finds the queued work instead of adding to it.
  `missed_policy` is honoured: a missed slot fires once under either policy — three days offline
  is one run, never three — and CATCH_UP keeps the original anchor while SKIP re-anchors to now.
- The daily job is seeded at start-up **dormant**. A schedule that fired within thirty seconds of
  the first start-up would begin a real day — agents, tokens, renders — on a decision nobody
  took. Starting it is an Owner action from the panel, recorded as `workflow.job_activated`.
- The daily-run panel shows the schedule: next and last run, the cadence, the missed-run policy,
  a plain note when autonomy is stopped, and the toggle.
- `scripts/demo_worker.py` starts the real server process with the worker on, activates the
  schedule through the API, makes the slot due, and waits without touching anything. A daily run
  appeared on its own in an isolated studio. `scripts/verify_runbook_ui.mjs` drives the panel.

## The daily run does the day's work — 2026-09-11

- Connected real work to the runbook. `execute_daily_run` walked twelve stages and nothing in the
  application ever supplied the work for any of them, so every run recorded preflight and then
  eleven SKIPPED: truthful, and idle. Eight stages now have implementations behind them.
- Performance intake measures the videos the platform is actually serving. Research reads the
  ingested sources and has a second agent check every claim against the source it came from.
  Selection takes a topic that has something verified to say. The script writer drafts from the
  supported claims, storyboards what the Owner has approved, renders it, and quality control
  measures the file. Publishing goes through the same five-point gate as a manual publication.
  The serial writes the episode for the day the studio has just closed.
- Two outcomes, kept apart: COMPLETED means the stage ran to its end, SKIPPED means it could not
  run. "We looked and there was nothing" and "we could not look" now read differently in a run.
- Where a person decides, the studio stops. A draft is left at VERIFIED_PASS for the Owner, and
  storyboarding waits for that approval. `idea_generation` and `post_run` stay unwired, because
  neither has an implementation and inventing one would be worse than the runbook saying so.
- A refusal is not a failure. A rejected script or a rejected episode is the pipeline working;
  letting it raise would have stopped the day at that stage and left the log unclosed.
- Added `select_topic`, the verb that was missing: a topic goes into production only if at least
  one claim about it is SUPPORTED. Idempotent, and it records the decision.
- `scripts/demo_daily_run.py` runs two full days in a throwaway studio, with an Owner approval
  between them. The second day renders a real 51 kB MP4 through FFmpeg and quality control
  measures it with ffprobe and fails it — placeholder visuals, duration outside Shorts limits.
  Every refusal in the run is specific and correct.

## Internal audit — 2026-09-11

- Audited the whole studio at the Owner's request. Nine defects found and fixed, each with a test
  that fails without the fix; five areas checked, found sound, and given tests so the finding
  repeats on every run. Full account: `AUDIT_2026-09-11_INTERNAL.md`.
- The serious ones: a failed question to YouTube was recorded as the answer "no", which could
  produce a duplicate upload of a video already live; the factual gate passed assets whose
  provenance it never established while claiming it had; a claim referenced but absent counted as
  supported; and Owner funding was not idempotent, so a retried request doubled the money.
- The quiet one: the studio could not find its own encoder. Three parts of the code resolved
  FFmpeg three different ways, so media inspection reported unavailable with ffprobe sitting
  beside the configured ffmpeg. One resolver now, and five media tests that had been skipping
  themselves run against the real encoder: 402 passed, 1 skipped, from 391 passed, 6 skipped.
- CI had been failing two of its eleven checks since Phase 11. Both green.
- Migration `0018_audit_gaps` links an exchange rate and a scheduled job to the event that
  created them.

## The YouTube form no longer empties itself — 2026-09-11

- Fixed the connection form losing everything typed into it whenever the window lost focus.
  Filling it means copying a client id and a secret out of the Google console one at a time, and
  the refresh-on-focus listener rebuilt the whole section on every return, so the Owner could
  never reach the end of the form.
- The refresh now runs only after an authorisation has actually been started, and never while a
  form is open. Independently, what is typed is mirrored into a draft held outside the DOM and
  restored on any redraw, dropped on cancel and after a successful save.
- Saving now closes the form before the request, so a success shows the cards instead of leaving
  the filled form on screen; a failure leaves the form and its contents untouched.

## The YouTube catalog form is gone — 2026-09-11

- Deleted the `youtube` entry from the settings catalog. It still asked for a refresh token and an
  ID canal YouTube beside the new OAuth section, which is exactly what the OAuth flow exists to
  remove. Connecting a channel through Google is now the only way to give the studio YouTube
  credentials.
- Repointed every consumer at the connection: publishing credentials, channel binding (now
  `connection_id`, with the remote channel id copied from the grant rather than from a typed
  field), the analytics provider, the runbook preflight check, and the purpose selections.
- With several channels connected and no binding, the studio refuses to choose one rather than
  taking the first row. Publishing to the wrong channel is not recoverable.
- Fixed a bug this uncovered: media providers (ElevenLabs, OpenAI media) were verified by a branch
  that built a YouTube provider, so every check raised and reported FAILED. They now use the vendor
  probe that already covered them.

## YouTube connections by OAuth, not by typing — 2026-09-11

- Replaced the hand-typed refresh token and channel id with the Authorization Code flow. The Owner
  now enters four things — connection name, Google OAuth client id, client secret, redirect URI —
  and presses **Conectează YouTube**. The studio requests `access_type=offline`, asks for consent
  only when it has no refresh token or the Owner pressed Reconnect, stores the token in the Fernet
  vault, reads the channel with `channels.list`, and shows which account was authorised.
- Added `backend/app/youtube/` and migration `0017_youtube_connections`: two tables, eight
  Owner-only routes, and one public callback protected by a single-use, ten-minute random state.
  Neither the client secret nor the refresh token is a column, and no view model has a branch that
  could return one.
- Several channels are supported and none is special: no channel id, client id, token or account
  name appears anywhere in the code, and a test greps for all five shapes.
- Reconnect, Verify, Disconnect and Delete are Owner actions. Disconnect forgets the token locally
  before revoking it at Google, so an unreachable Google still leaves the studio clean. Editing the
  client id drops the stored refresh token, because a token issued to one OAuth client cannot be
  used by another.
- Fixed two defects the browser pass found: `window.open(..., 'noopener')` returns `null`, so the
  consent tab fell through to a fallback that navigated the studio's own tab to Google; and the CSS
  class `.secondary`, used by roughly fifteen affirmative buttons across the admin surface, had
  never been defined in any stylesheet. Evidence: `YOUTUBE_CONNECTIONS.md`.

## Phase 11 — Financial evidence and the VR$ ledger — 2026-09-10

- Added `backend/app/economy/`: immutable double-entry books in VR$, posted only from real
  external evidence. Seven tables (`0016_phase11_economy`), eleven Owner-only routes, and a
  **Trezorerie** panel in the office.
- The four invariants the economy exists for are enforced by schema and service, not convention:
  one verified dollar mints exactly one VR$ once; forecasts and pending payouts can never be
  spent; a reversal posts a mirror and never deletes; the books always balance. Money is integer
  micros, and a non-USD amount without a recorded FX snapshot is refused rather than converted at
  an invented rate.
- Provider costs are mirrored too, so the treasury shows what running the studio costs and can
  report a deficit honestly. Estimates are shown but never posted.
- No route in the entire API pays, buys, transfers or checks out; a test asserts it over the
  whole OpenAPI surface.
- Owner funding has a form in the Trezorerie panel: contribution or loan, the rate entered as a
  percentage and stored as basis points, loan terms required and contribution terms refused, an
  ambiguous comma refused rather than guessed, and a non-USD amount recording its exchange rate
  and source before it is converted.
- `treasury` moves from NOT_IMPLEMENTED to PARTIAL in the snapshot module map; `procurement` and
  `financing` stay NOT_IMPLEMENTED. Evidence: `PHASE11_ECONOMY.md`.

## Agency identity: AMN-AI — 2026-09-10

- Named the agency **AMN-AI (Autonomous Machine Nexus — Artificial Intelligence)** everywhere it is
  stated: browser tab, share metadata, top bar, sign-in screen, footer, the 2D building's neon sign,
  FastAPI title, `STUDIO_NAME` default, simulated channel title and Channel B tagline, README,
  AGENTS, launcher scripts, and the distribution names (`amn-ai`, `amn-ai-ui`) with both lockfiles
  regenerated — dependency resolution unchanged (44 packages identical, `uv sync --locked` and
  `npm ci` clean).
- Added the logo as a proper asset set derived from the source artwork: top-bar mark, sign-in
  lockup with a transparent ground, `favicon.ico`, `favicon-32.png`, `apple-touch-icon.png` and a
  512 px master used as `og:image`. Quantised from a single 1.16 MB PNG to ~8 kB per page load.
  Removed the previous brand's unreferenced `favicon.svg`.
- Added `scripts/rename_studio.py`: bootstrap deliberately never rewrites an existing studio name,
  so renaming is an explicit Owner act that appends a `studio.renamed` event beside the row update.
  Applied it to the local studio; the workspace H1 now reads AMN-AI because the database says so.
- Documented the whole identity in `BRAND_AMN_AI.md`. Tests now assert the brand assets the page
  actually references and cover the rename's audit trail, idempotence and refusals.

## Pixel office v2 — 2026-09-10

- Rebuilt the 2D office's visual layer to a modern pixel-art standard, frontend only: new
  `office_palette.js` (hue-shifted five-tone ramps, one material story per department),
  `pixel_sprites.js` (outlined compiled sprites, glow cache), `office_characters.js` (26×34
  seated sprites, role costumes, deterministic looks, honest state poses), `office_rooms.js`
  (room shells, baked light, nine department interiors, workstation occlusion layers),
  `pixel_font.js`; `office_engine.js` rewritten around three cached layers with the same exports.
- Designed the system in Figma before implementing (palette variables, quality-bar floor at 4x,
  character and HUD components, building/layout spec).
- Scene chrome: slim dark bezel and high-contrast dark controls; admin panels unchanged.
- Removed the superseded `office_art.js`. Added 5 frontend tests (43 total), a standalone room
  preview harness and screenshot/FPS review scripts. Backend, API, events and data untouched.

## Foundation 0.1 — 2026-09-09

- Read the full original 83-document specification package; established its implementation baseline.
- Separated architecture (78 documents) and live project tracking (5 original documents) at Owner request.
- Added indexed document hashes, link/inventory validation and failure tests for accidental spec edits.
- Added FastAPI/SQLAlchemy/Alembic backend, configured local credentials, persisted initial world and
  Owner policy, immutable events, idempotent/versioned STOP command and private snapshot/event routes.
- Added responsive HTML/Tailwind/JS foundation shell, truthful unavailable modules and stale-state UI.
- Added locked dependencies, structured logs, security headers, CI baseline and secret scan.
- Verified 26 Python tests, 3 JS tests, lint/types/build, schema upgrade, concurrency, restart and browser.
- Preserved all unimplemented core/V4/V5 requirements; no LLM/media/publishing integration claimed.

## v2 — 2026-09-09

### Strengthened realism
- Added strict Intent → Policy → Capability → Execution → Verification → Commit model.
- Added tool/action receipts.
- Added UNKNOWN provider/capability states.
- Added realistic local-PC vs always-on deployment constraints.

### Strengthened Director
- Defined broad CEO responsibilities.
- Added self-permission/self-guardrail restrictions.
- Added strategy-change and workforce-evaluation safeguards.
- Added provider discovery vs actual onboarding distinction.

### Strengthened employees
- Added Role Contracts.
- Added capability requirements and least privilege.
- Added safe firing with in-flight task handling.
- Added explicit model-upgrade vs employee-replacement semantics.

### Strengthened automation
- Added durable workflow requirements.
- Added scheduler safety.
- Added leases/locks, idempotency, outbox, retry/backoff, circuit breakers and watchdogs.
- Added external side-effect reconciliation.

### Strengthened UI truthfulness
- UI success only after backend verification.
- Added snapshot/replay, duplicate/out-of-order event handling.
- Added persistent office world state.

### Strengthened research/security
- Added prompt-injection defense.
- Added memory provenance and poisoning controls.
- Added source freshness/staleness.

### Strengthened media/serial
- Added Character Bible and provider-capability constraints.
- Added live operational vs dramatized serial dialogue separation.
- Added media rights/provenance requirements.

### Strengthened operations
- Added provider contract testing.
- Added failure/recovery playbook.
- Added backup/restore, disk retention and deployment guidance.
- Added master acceptance checklist and risk register.

## v3 — 2026-09-09

### Deep file-by-file hardening
- Re-reviewed every v2 document.
- Added Policy Kernel and independent hard gates.
- Added bounded agent communication, deadlock and rework limits.
- Added daily preflight and admission control.
- Added compensation/manual repair model.
- Added prompt/context/memory lifecycle architecture.
- Added model drift and role-suitability revalidation.
- Added multi-objective Director scorecard.
- Added public character alias / provider-brand separation.
- Added WorldBuilder contract for dynamic office growth.
- Added narrative privacy/sanitization.
- Added anti-repetition/novelty gates.
- Added deterministic media fallback.
- Added CI/CD, feature flags and rollback requirements.
- Added reliability SLOs and burn-in.
- Added data privacy classification.
- Added transfer/sale-readiness requirements.
- Added dedicated v3 specifications for governance, prompts/memory, tool permissions, evaluation, reliability, security, public community, IP, daily runbook, world evolution, schema versioning and launch readiness.


## 2026-09-09 — V4 Organizational Expansion
- Added dynamic Department Factory and manager delegation.
- Added Marketing & Communications architecture for YouTube, TikTok, Instagram, Facebook and Telegram.
- Added same-day truthful teaser → next-day Office Serial loop.
- Added marketing attribution and experiments.
- Added Market/Competitive Intelligence.
- Added HR/People Ops, persistent fictional personas, birthdays and relationship graph.
- Added Finance/Accounting/FinOps separation.
- Added Legal/Rights/Compliance department.
- Added future Advertising/Paid Media/Sponsorship architecture.
- Added Company Calendar, milestone triggers and team-building/no-production event mode.
- Added organizational-bloat controls and capacity planning.
- Extended data model, events, commands, tests, UI mappings, governance and acceptance criteria.


## 2026-09-09 — V5 Economy Expansion
- Added 1:1 USD ↔ VR$ market-anchored virtual economy.
- Added financial truth layers and double-entry ledger requirements.
- Added revenue settlement/reversal/idempotency rules.
- Added Owner capital contribution and Owner loan models.
- Added market-referenced virtual financing with debt-capacity gates.
- Added Procurement + VendorShop + NEW/USED current market quote sourcing.
- Added Asset Architect and market-priced office asset lifecycle.
- Added treasury dashboard, runway, burn, forecasts and virtual financial statements.
- Added strict no-real-money-spend boundary.
- Added financial events to UI, Story Engine and marketing provenance.

## Post-audit remediation — 2026-09-09

Answers `docs/project/AUDIT_2026-09-09_EXTERNAL.md`. Decisions recorded as D-AUDIT-001/002.

### Truthfulness (breaking behaviour changes)
- Channel slots seed as `NOT_CONFIGURED` with no remote ID; status is derived from real
  configuration only. Previously seeded as `CONFIGURED` with invented channel IDs.
- Publishing without `STUDIO_YOUTUBE_*` credentials now returns 503 `PublisherNotConfigured`.
  The silent fallback to the simulated adapter is removed.
- Simulated uploads are recorded as `PUBLISHED_SIMULATED` with `sim:` identifiers and no platform
  URL, and are labelled as such in the UI.
- The renderer no longer writes a placeholder file named `.mp4`. It encodes a real H.264
  1080x1920 video with FFmpeg or fails with `RenderEngineUnavailable` (HTTP 503).
- QC measures the file with `ffprobe` and recomputes the provenance digest instead of trusting the
  renderer's own metadata; placeholder visuals are blocked from publication; the character-drift
  check reports `NOT_IMPLEMENTED` instead of passing.
- `POST /media/storyboards/sample` replaced by `POST /media/storyboards/demo-fixture`, which
  creates `UNVERIFIED` claims only.

### Correctness
- Fixed `DetachedInstanceError` in the FFmpeg render path (ORM objects used after session close);
  that path had never executed successfully.
- Gate refusals now persist the `BLOCKED_GATE` record and `publishing.gate_failed` event.
- Missing media asset or channel returns 404 instead of a 500 database integrity error.
- `GET /publishing/channels` no longer writes; seeding moved to `POST /publishing/channels/seed`.
- YouTube upload is chunked and resumable (`Content-Range`, 308 handling); synthetic-content
  disclosure is sent; `reconcile_upload` is invoked before any retry.
- QC minimum score (0.90) is actually enforced by the publishing gate.
- Removed a hardcoded Windows storage path from `assembler.py`.
- Fixed a `TypeError` in `scripts/bootstrap.py` that broke first-time `.env` creation.

### Found and fixed while running the application under Playwright
- **WebSocket gateway repaired.** `websockets` was missing from the dependencies, so uvicorn
  answered the `/api/v1/ws` handshake with 404 and the 2D office never received live events.
  Added `websockets>=13,<16` to `pyproject.toml` and regenerated `uv.lock`. Run `uv sync`.
- **Script approval path added.** `generate_script_draft` produced `VERIFIED_PASS` scripts while
  storyboarding required `APPROVED`, and no approval endpoint existed — the real pipeline could
  not reach the media stage at all; only the fabricated `sample` endpoint could.
  New `POST /api/v1/factual/scripts/{id}/approve` re-runs the factual gate at approval time.

### Data correction
- Migration `0007_correct_fabricated_records` (data-only) repairs existing databases: fabricated
  channel identities cleared, simulated publications relabelled `PUBLISHED_SIMULATED` with their
  dead YouTube URLs removed, and all prior `PASSED` QC reports invalidated so they are re-run by
  the measuring gate. Startup now expects revision `0007`; Phase 7 analytics starts at `0008`.

### Developer experience
- `start.cmd` / `scripts/start.py`: one idempotent command that syncs dependencies, prepares the
  database, builds the frontend and starts the server, then prints a preflight report naming the
  integrations that are actually configured. It stops on a failed step instead of starting a
  half-built studio. README updated accordingly.

### Configuration
- `STUDIO_YOUTUBE_CLIENT_ID`, `STUDIO_YOUTUBE_CLIENT_SECRET`, `STUDIO_YOUTUBE_REFRESH_TOKEN`,
  `STUDIO_YOUTUBE_CHANNEL_ID` and `STUDIO_FFMPEG_PATH` added to `Settings` and `.env.example`.

### Tests
- New `tests/test_truthfulness_gates.py` (10 tests) locking the governance invariants.
- Render tests skip when FFmpeg is absent instead of exercising a fake path.
- 87 passed with FFmpeg; 85 passed / 3 skipped without it.

### Documentation
- `CURRENT_STATUS.md` corrected: Phases 4, 5 and 6 are marked PARTIAL with their exact unmet
  acceptance criteria. `PROJECT_STATE.json` brought up to date (was five phases stale).

## Interface consistency pass — 2026-09-09

Decision D-DESIGN-001.

- **Single colour system.** `frontend/src/style.css` rebuilt around `:root` design tokens derived
  from the original template. The 97 ad-hoc colour literals are gone; components reference tokens.
- **Dialogs re-skinned** from the Tailwind dark theme to the studio's paper surface, with tokenised
  borders, inputs, buttons, tabs, cards and badges.
- **Semantic state colours** unified: published / validated / simulated / blocked and channel
  statuses now use consistent background-border-ink triples and stay mutually distinguishable.
- **2D office** framed like the template's office scene; structural scene colours retinted from
  slate blue to the brand greens. Department accents and character art left untouched.
- **Icons removed.** All pictographic emoji dropped from buttons, headings and badges; labels
  rewritten in sentence case.
- **Media panel corrected**: it showed the storyboard UUID under the label "Provenance SHA-256" and
  scored the unimplemented continuity check as 0%. It now shows the measured resolution, duration
  and codec, the real verified digest, and an em dash for the check that does not exist.
- **Accessibility**: `scratch/verify_design.mjs` measures computed contrast in the running page;
  three tokens were darkened to clear WCAG AA. 14/14 design checks and 27/27 functional checks pass.
- **Toolbar highlight fixed.** `cam-btn-active` was hard-coded on the "Cercetare" button, so it
  looked permanently selected. The highlight is now bound to whether that panel is actually open.
- **Leaving fullscreen restores the office.** `.office-scene-container` had no height of its own,
  so it was sized by the canvas while the canvas was sized by it; on exit nothing shrank the canvas
  back and the scene stayed at fullscreen dimensions. The container now has a definite responsive
  height and the engine resizes across two animation frames.
- `scratch/verify_fullscreen.mjs` (new, 10 checks) measures the canvas before, during and after a
  fullscreen round trip and asserts the toolbar highlight follows the open panel.

## Office renderer rebuild — 2026-09-09

Decision D-DESIGN-002. `frontend/src/office_engine.js` rewritten (~2,200 lines).

- **Scene**: dusk sky with stars, moon and drifting clouds; two parallax skylines with lit
  windows; a street at the foot of the building with traffic, pedestrians, swaying trees, lamp
  light pools, a bus stop and planters. All of it seeded scenery, connected to no data.
- **Building**: cutaway shell with structural columns, parapet, roof plant, extractor fans,
  antenna beacon, satellite dish, neon sign, and a glass elevator whose cab travels the shaft.
- **Interiors**: every department has its own furniture — executive bookshelf and awards, research
  evidence board with pinned cards and string, storyboard wall, vocal booth with foam, boom mic,
  mixing desk and VU meters, edit bay with a scrubbing timeline, server racks with per-unit LEDs
  and fans, lounge with espresso steam and a water cooler, distribution console with a radar
  sweep. Empty wall runs are filled with cabinets, posters, whiteboards, coat racks and plants.
- **Characters**: appearance derived from the agent id (skin, hair style and colour, outfit,
  glasses, headset, build), so no two look alike; blinking, breathing, sipping and stretching on
  per-character phases; typing, thinking and sleeping driven strictly by backend state.
- **Rendering**: 1:1 offscreen world buffer blitted without smoothing for crisp pixel art; cached
  static layers; ceiling light cones, screen spill and lamp pools composited additively.
- Nameplates moved onto the floor slab with the state inline, so they no longer collide with the
  floor header below them.

## Office scene corrections — 2026-09-09

Decision D-DESIGN-003.

- **Backend layout**: ground floor doubled in height (200px) and re-divided; new `SHOP` zone
  `ad_shop` for street-level advertising sales, with no desks assigned. Building height 690 -> 740,
  layout height 800 -> 1000. `tests/test_phase3_office.py` extended: floor zones must not overlap
  and every desk must stand inside its own zone.
- **Street rebuilt below the building**: plinth, pavement, kerb, two-lane carriageway with a
  pedestrian crossing, far pavement with drains and planters. Pedestrians can no longer overlap
  the ground floor; `streetGeometry()` is exported and covered by two new frontend tests.
- **Human scale**: pedestrians drawn at the same size as the staff inside; cars ~90px, vans and a
  168px bus, with wheels and glazing to match. Street lamps moved to the building's flanks.
- **Lift**: parked and dark by default, labelled IDLE. It moves only when a workflow token changes
  floor, waits at the delivery floor, then returns to the ground floor.
- **Readability**: nameplates use double-scale type on an opaque plate; wall sconces added to
  tall floors; `M` and `W` glyphs redrawn.

## 2026-09-10 — Street and nameplate corrections (Owner feedback)

- **Bus**: removed the invented route number "12"; the destination blind stays blank.
- **Traffic**: vehicles spawn spread across their lane and follow their lane leader (speed matching
  plus a hard 24 px bumper clamp, seam-aware), so same-lane vehicles no longer pass through each
  other. `makeTraffic`/`updateTraffic` are exported and covered by three new frontend tests
  (spawn spacing, catch-up scenario, 15-minute mixed-timestep seam run).
- **Nameplates**: name type reduced from double to single scale on a light paper card with dark ink
  and a muted state line — smaller plates that stay readable over the dark floors.

## 2026-09-10 — State tag above the character (Owner feedback)

- The floor nameplate now carries the agent name only. The runtime state (IDLE, WORKING, …)
  floats above the character's head on a dark chip in the department accent, and the thinking
  bulb and sleeping Z marks were raised so none of the three overlap.

## 2026-09-10 — Settings agent LLM test + verified Ollama Cloud connectivity

- New `POST /api/v1/settings/agents/{id}/test`: one real run through the assigned model via the
  policy kernel; the Settings → Agenți cards gained a "Testează răspunsul" button that shows the
  model's answer or the block reason. Verified live against Ollama Cloud (glm-5.3-flash,
  gpt-oss:120b). New settings test; suite 16/16.

## 2026-09-10 — Whole-tree lint and type cleanup

- `ruff format` across the tree, 65 long lines wrapped (string content preserved), unused/unsorted
  imports removed, SQLAlchemy `== True` → `.is_(True)`, `zip(..., strict=False)`, import order fix.
- mypy: typed the ffprobe result and storyboard scene payloads (`dict[str, Any]`).
- Baseline now passes every README check: ruff, ruff format, mypy, pytest 137, frontend 11,
  docs integrity, secret scan.

## 2026-09-10 — Live speech bubbles with the agent's real answer

- `run_agent_task` emits `agent.message_sent` (transactional outbox) carrying the model's real
  output when a run succeeds with visible text; failed and text-less runs stay silent.
- The app lifespan now dispatches the outbox every second, so committed events are broadcast to
  WebSocket clients live (previously the dispatcher was never invoked and the office only saw
  the one-shot replay at connect).
- Activity log labels the event "Agentul a răspuns". Verified live: an API-triggered run made
  the answering bubble appear above the agent in the 2D office.

## 2026-09-10 — Research agent extracts claims from real sources; office fully live

- `agent.state_changed` (THINKING/IDLE) now flows through the outbox during runs, and
  pause/resume events were moved onto the outbox — state tags and pause animations in the
  2D office follow backend events live.
- New `POST /factual/sources/{id}/extract-with-agent`: the research agent reads the sanitized
  source (inert boundary, prompt-injection safe) and extracts schema-validated atomic claims
  via its assigned model. Claims stay UNVERIFIED; unparseable output is rejected; truncated
  JSON keeps only complete objects. The agent announces "Am extras N afirmatii..." as its
  speech bubble instead of raw JSON.
- Verified live end to end: real IANA page fetched via the retrieval adapter -> Dr. Aris
  (nemotron-3-super) -> 9 accurate UNVERIFIED claims -> bubble in the office.

## 2026-09-10 — Re-audit of third-party work; the seed stops claiming a healthy provider

- **Independent verification of the newest external work.** Re-ran the full battery against a
  clean checkout rather than trusting the tracking documents: pytest, ruff, ruff format, mypy,
  `tsc`, the frontend unit tests, the Vite build, the documentation hash integrity check and
  the three Playwright suites. Everything passed and nothing regressed. Read the new
  security-sensitive modules line by line — the credential vault, the Settings save/check path,
  the SSRF-hardened retrieval adapter and the research agent pipeline — and confirmed each of
  their stated properties holds in the code: a saved connection is `SAVED` and never verified,
  only a real probe writes `VERIFIED`, retrieval refuses anything but an allow-listed public
  HTTPS host on a DNS-pinned connection, and every extracted claim is stored `UNVERIFIED`.
  Confirmed the two edited architecture documents match their indexed hashes and that the
  decision log records the edit, as the process requires.
- **Fixed: the workforce seed asserted a health check that never happened.** A freshly
  bootstrapped studio recorded the local Ollama endpoint as `HEALTHY` with a health-check
  timestamp and three models as available and verified, on a machine with no Ollama installed —
  the same falsehood the Owner first reported about the YouTube channel. The seed now records
  the provider `NOT_CONFIGURED` and its models `SEEDED_UNVERIFIED` with no timestamps; only a
  real model sync may record health, availability or a verification time. See D-TRUTH-002.
- **Fixed: the seeded provider could not be verified at all.** It had no adapter registered, so
  every check failed with "no adapter registered" and the unverified state was permanent. The
  adapter is now registered at startup, Settings lists the endpoint with a working
  "Verifică și încarcă modelele" button, and an unreachable endpoint answers 503 with what went
  wrong instead of a generic internal error.
- Migration `0009_unverified_seeded_provider` withdraws the claim from existing databases.
- Baseline: ruff, ruff format, mypy, pytest 152 passed / 1 skipped, frontend 11, `tsc`, build,
  docs integrity; Playwright 27/27 + 14/14 + 10/10 + 8/8 (new provider-honesty suite).

## 2026-09-10 — Phase 7 analytics live; lift courier; the ground floor built out

- **Analytics wired, simulator deleted.** The Phase 7 module now runs: router mounted, models in
  `Base.metadata`, migration `0010_phase7_analytics`. Before wiring it, the deterministic
  analytics adapter — which invented view counts, retention and CTR from a hash — was removed
  outright, and the fallback that would have measured a never-uploaded publication under its
  internal row id with it. With no verified YouTube connection, ingestion answers HTTP 503 and
  says plainly that the studio does not estimate or simulate audience figures. This mattered
  more than a display bug: the learning loop reads these numbers back and turns them into the
  Director's recommendations, which change the topic and hook weights the studio writes to.
- **The YouTube Analytics adapter stopped ignoring the reporting window.** Every query used to
  send the same fixed date range, so an all-time report could be stored labelled "24h".
  Impressions and CTR are now read from YouTube's own metrics or reported as zero — never
  back-computed from views.
- **The lift carries someone.** A workflow token changing floor now runs a full delivery: the
  cab comes to the floor, doors open, a runner boards with the work, doors shut for the ride,
  and the runner walks the token to its new department. Doors part only at a floor, as a real
  lift's do. With no workflow running the cab still stands still.
- **The double-height ground floor was built out** — ducting, a service mezzanine with railing,
  pendant lights, and one wall fixture per department (rack status wall, canteen board, dispatch
  board, and an empty "YOUR AD HERE" hoarding over the shopfront).
- **Fixed: workflow tokens were drawn in the wrong departments.** The stage-to-position table
  was hardcoded pixels that predated the taller building — research appeared in the executive
  suite and publishing floated outside the wall — and because the lift is dispatched by the
  zone a token lands in, it also sent the cab to the wrong floor. Stages now name a department
  and the position comes from the layout the backend serves.
- Baseline: ruff, ruff format, mypy, pytest 163 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 27/27 + 14/14 + 10/10 + 8/8 + 9/9.

## 2026-09-10 — The research loop is usable; verification is independent; inspector fixed

- **Fixed (reported by the Owner): the agent panel showed a model nobody had assigned.** The
  "model" field was a fixed string in the HTML — every agent read `glm-5.2:cloud` whatever was
  chosen in Settings — and the office layout carried no model at all. Assignments now carry the
  agent's real model, its provider, and whether that provider has confirmed it; the panel
  distinguishes "not assigned", "assigned · unverified" and confirmed, and only a confirmed
  model enables a run. Settings now refreshes the office after every change, so a reassignment
  lands without reloading the page. See D-UI-005.
- **The Phase 4 research loop can be driven from the interface.** Fetch a source from a site you
  authorised, have the research agent read it, then verify each claim — all of it previously
  existed only behind `curl` and a shell script.
- **Independent fact-checking.** A second agent, never the one that extracted the claim, checks
  it against the stored source; the studio refuses when no independent agent exists rather than
  letting an agent confirm its own reading. A SUPPORTED or REFUTED verdict must quote the source
  verbatim, and **a verdict whose quote is not in the source is rejected whole — the claim stays
  UNVERIFIED**. UNCERTAIN was added so a checker that finds nothing can say so instead of
  guessing. Migration `0011` records who extracted and who verified each claim.
- **The retrieval allowlist is configuration, not application state.**
  `STUDIO_RESEARCH_ALLOWED_HOSTS` in `.env`, empty by default (retrieval off). The request
  carries no host field, and an entry naming this machine or a private range is refused at
  start-up.
- **Fixed: refusals were replaced by a generic message.** The interface now shows the server's
  own explanation — which host is not authorised, why a provider did not answer — instead of
  "try again", which was hiding the part that says what to do.
- Baseline: ruff, ruff format, mypy, pytest 199 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 27+14+10+8+9+9+18 = 95 checks.

## 2026-09-10 — Scripts written from verified claims, cited scene by scene

- **The script writer drafts only from SUPPORTED claims**, and every scene names the claims it
  rests on. A scene citing an identifier that was never supplied rejects the whole draft, not
  just that scene: the narration around an invented citation came from somewhere other than the
  evidence, and there is no way to tell how far that reaches. A topic with no verified claim
  produces no script at all rather than one that would be blocked later.
- **The spoken text is the attributed text.** The stored voiceover is assembled from the scene
  narrations, so there is no separate field a model could fill with something the citations do
  not cover.
- **The Research panel now shows scripts** scene by scene with their citation counts, and offers
  approval only on a draft that passed the factual gate. Approval re-runs that gate — a claim
  refuted since the draft was written blocks it — and the refusal now says how many claims
  stopped being supported instead of showing a raw exception.
- Baseline: ruff, ruff format, mypy, pytest 211 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 106 checks across 8 suites.

## 2026-09-10 — Media adapters, ready for the credentials the Owner will add

- **Real TTS and image adapters** (ElevenLabs, OpenAI Images) that call documented endpoints and
  return what came back. A vendor failure raises; there is no fallback asset, because a
  substitute would flow into QC and the publishing gate as though a provider had made it.
- **Every figure is measured from the bytes received** — narration duration counted from the MP3
  frames, image size read from the PNG header — never taken from the request. Where a vendor
  offers nothing (no word alignment, no seed), the adapter reports nothing instead of echoing the
  request back as if it had applied.
- **A render uses a provider only when it is both verified and selected** for that purpose. With
  none, the render still happens and is labelled placeholder content, which QC keeps out of
  publication — unchanged. The recorded provider name is always the generator that actually made
  the frames, and it drives the asset, the event and the QC report from one value.
- `GET /media/providers` says which generators a render would use and whether its output could be
  published. Settings stops telling you these vendors are unconnected once an adapter exists.
- Baseline: ruff, ruff format, mypy, pytest 241 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 106 checks across 8 suites.

## 2026-09-10 — Research hands work to production

- **An approved script now reaches production.** The Media panel opens with the approved scripts
  no storyboard has been built from yet — with their scene count and how many verified claims
  each rests on — and builds the storyboard from there. Previously the only creation control was
  the demo fixture, so the two halves of the studio were joined by test data.
- Only APPROVED drafts are offered: approval is what passing the factual gate means. A script
  leaves the queue the moment its storyboard exists, so nothing is produced twice by accident.
- **The panel says what a render will be before you ask for one** — without a verified image
  provider the output is placeholder content that QC blocks from publication. That was knowable
  in advance; reading it in a failed QC report afterwards was the wrong way to find out.
- Baseline: ruff, ruff format, mypy, pytest 244 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 117 checks across 9 suites.

## 2026-09-10 — Phase 8: the studio can recommend staffing changes, and only recommend them

- **Evidence is counted from the studio's own record** — agent runs and their outcomes over a
  30-day window, queue backlog, dead-lettered tasks. No model is asked what it thinks of a
  colleague; a fluent judgement with nothing under it is exactly what this must not produce.
- **An agent with no runs is shown as unmeasured, not as flawless.** Its failure rate is unknown,
  not zero.
- **Fewer than five runs never becomes a recommendation**, at any failure rate. The service
  refuses to build such a proposal and the database refuses to store one.
- Each proposal carries the numbers it was built from, and the panel shows them — a staffing
  decision has to be checkable months later.
- **A high failure rate proposes suspension, not termination**: the cause is usually the model or
  the provider, and suspension is reversible.
- **Approving is the Owner's act.** An autonomous approval is refused outright rather than
  quietly turned into a pending proposal, and a rejection requires a written reason.
- Employment is now a record with its own history, so a rehire opens a new period instead of
  reviving a closed one — TERMINATED cannot become ACTIVE by editing state, as the spec requires.
- New "Personal" panel; migration `0012_workforce`.
- Baseline: ruff, ruff format, mypy, pytest 263 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 126 checks across 10 suites.

## 2026-09-10 — Phase 9: the daily log, and a serial that cannot invent the day

- **The day is counted from the event stream**, in the studio's own timezone — counts per event
  type, the roster, and the events worth dramatising. No model writes any part of the log,
  because the log is what every episode is checked against.
- **A closed day does not change**, and a date can only be closed once. Otherwise an episode
  could become grounded after the fact.
- **Every beat cites the real events it dramatises**, and a citation that is not in that day's
  log fails the whole episode — not just the beat. The spec's forbidden-fabrication list (a fake
  hire, an invented outage, a decision attributed to the wrong person) is all enforced by this
  one rule: those things have no event to cite.
- **The cast is the day's roster.** The serial cannot put someone in a room the record says they
  were not in.
- **A quiet day produces no episode** and the panel says so, instead of offering a button that
  would fail. A quiet day is a fact about the studio.
- `GET /story/episodes/{id}/grounding` re-checks a stored episode against its log, so the
  grounding claim is audited rather than trusted.
- New "Jurnal" panel; migration `0013_story`.
- Baseline: ruff, ruff format, mypy, pytest 284 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 137 checks across 11 suites.

## 2026-09-10 — Phase 10: the daily runbook, and a run that reports only what it did

- **A preflight that never rounds up.** Every capability is checked and listed with what it
  found — the passing ones too, so the Owner can see what was looked at. A missing media provider
  degrades the day; a stopped autonomy gate, no verified model or no FFmpeg blocks it. The
  DEGRADED summary says in words that stages will be skipped and the output will be
  unpublishable, because "DEGRADED" on its own invites being read as "fine for now".
- **The preflight probes nothing over the network** and changes nothing: reading it twice cannot
  start a run.
- **The run's status is derived from its stages**, never asserted by a caller or a stage. A stage
  reporting COMPLETED does not make the day completed while another was skipped.
- **All twelve stages appear in every run record**, including the ones with no implementation
  connected (SKIPPED, with the reason) and the ones after a stop (BLOCKED, naming where it
  stopped). A record listing only the stages that ran would mislead by its shape alone.
- **A blocked preflight closes no daily log.** A partial day is still a day; a day the studio
  never started is not, and writing a log for it would put work that did not happen into the
  record tomorrow's episode is checked against.
- **A failed stage enters safe mode and stops autonomy**, so an unattended studio does not carry
  on into the next day with an unexamined fault behind it. A second failure does not open a
  second record and obscure when the incident began.
- **Leaving safe mode requires a written note and does not restart autonomy** — examining an
  incident and deciding the studio should act again are separate decisions.
- New "Rulare zilnică" panel; migration `0014_runbook`.
- Baseline: ruff, ruff format, mypy, pytest 304 passed / 1 skipped, frontend 17, `tsc`, build,
  docs integrity, secret scan; Playwright 149 checks across 12 suites.

## 2026-09-10 — Outdoor electronic clock

Added a pixel seven-segment clock marked BUCURESTI, 24-hour HH:mm, using Europe/Bucharest including DST. Street schedules now use the same timezone. 35 frontend tests and browser checks passed.

## 2026-09-10 — Street clock placement and consistent controls

Clock is now freestanding on the right side of the street. Bottom control dock CSS is emitted as a same-origin file, fixing CSP-blocked inline styling. Browser placement checks pass in desktop/fullscreen/mobile.

## 2026-09-10 — Correct agent inspector model assignment

Fixed false “Niciun model alocat” when an older office projection omits model metadata. Inspector now loads persisted agent/model details, handles errors explicitly and discards late responses. All 7 live agents matched Settings in read-only browser QA; 38 frontend tests passed. See `INSPECTOR_MODEL_FIX.md`.
