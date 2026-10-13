# 15 — Factual films: research agent and retrieval, claims, grounding, script writing, story review

Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).

> Files (6 880 lines in all):
> `backend/app/factual/__init__.py` (1), `backend/app/factual/agent_pipeline.py` (1025),
> `backend/app/factual/editorial.py` (541), `backend/app/factual/grounding.py` (514),
> `backend/app/factual/models.py` (201), `backend/app/factual/router.py` (538),
> `backend/app/factual/sanitizer.py` (112), `backend/app/factual/schemas.py` (203),
> `backend/app/factual/script_agent.py` (111), `backend/app/factual/services.py` (609),
> `backend/app/factual/story_review.py` (859), `backend/app/research/__init__.py` (1),
> `backend/app/research/agent.py` (870), `backend/app/research/models.py` (40),
> `backend/app/research/retrieval.py` (357), `backend/app/research/service.py` (898).
>
> Mapped 2026-10-12 from commit b00083c plus the working tree, and verified against HEAD 3d49e9a
> (`git diff b00083c 3d49e9a` touches none of these 16 files and `git status` shows none of them
> modified). 160 functions in scope (inventory); 7 call the LLM gateway directly, 6 more reach it
> through another function. Everything else is deterministic code. No commit from b00083c to
> 20abffd touches these 16 files; citations into `media/prompt_agent.py` and `agents/editorial.py`,
> which those commits changed, give their 20abffd lines.

---

## In one paragraph

This group is the front half of a factual short: it decides **what the studio will say and whether
it is allowed to say it**, before any shot is bought. The Lead Researcher (an LLM employee) proposes
candidate topics with self-scored editorial dimensions and a "thesis"; deterministic code throws out
duplicates of subjects the studio already made, hosts the Owner never authorised, and ideas that fail
written editorial floors. For the topics that survive, the studio first asks the authorised sites' own
search addresses and an Owner-verified web search API for real pages, the Researcher chooses among them
(or guesses addresses when nothing was found), and a DNS-pinned, size-bounded HTTPS retriever downloads
every page itself, only from the Owner's allowlist. A research agent extracts atomic claims from each
stored page (always stored UNVERIFIED); a **different** agent verifies each claim, and a SUPPORTED or
REFUTED verdict is only recorded when its evidence quote is found verbatim in the stored source. The
Script Writer drafts a short only from SUPPORTED claims; code rejects fabricated citations, cuts or
refuses uncited scenes, checks every number on a data card against its claim, and re-runs the factual
gate. The story review then runs 16 computed checks plus a lexical grounding measure (does the narration
say what its cited claims and topic say) and a clip-length check; the Director's LLM reading may only
make that verdict stricter. A PASS goes through the Director's editorial judgement loop (up to
`Settings.editorial_rounds` versions, default 10 = the passed draft plus at most 9 rewrites; the
best-scored version whose story review passed ships, and the judge can never stop a film) and,
finally, `story_gate` stands in front of every step that spends media money.

## Why it exists

- **Nothing verified was ever produced without a human.** Runbook §3 (idea generation) and the retrieval
  half of §4 (research) "had no agent behind them": topics were typed by the Owner and sources pasted by
  hand, so a studio left alone produced nothing (`backend/app/research/agent.py:1-19`;
  `docs/architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` §3-§5).
- **Independent verification is a spec requirement.** FR-038 ("Fact-check path should be independent of
  initial research path where practical", `docs/architecture/02_SRS.md:128-129`). D-P4-002 (2026-09-10) added
  `extracted_by_agent_id`/`verified_by_agent_id`, the 409 when no independent agent exists, and the
  verbatim-quote rule: "A verdict whose quote is not in the source is rejected whole and the claim stays
  UNVERIFIED" (`docs/project/16_DECISION_LOG.md:1402-1448`; code `backend/app/factual/agent_pipeline.py:278-295`,
  `:411-418`).
- **The allowlist is the Owner's, never a request's or an agent's.** D-P4-002 point 1 and the later entry
  moving hosts into an Owner-only table with a real front-page test
  (`docs/project/16_DECISION_LOG.md:1418-1424`, `:1834-1836`; `backend/app/research/service.py:1-19`). A search
  engine "may name addresses and nothing else" (`docs/project/16_DECISION_LOG.md:2068-2070`).
- **"Why should this video exist?"** — the Owner's verdicts on the first real film ("sunt doar niste
  imagini lipite", "filmul nu se incadreaza deloc") led to the editorial module: weighted idea scores,
  floors, a thesis per idea, a story shape per script, and narration measured at the studio's own speaking
  rate (`backend/app/factual/editorial.py:1-24`; CHANGELOG "The idea has to argue for itself — 2026-09-12",
  `docs/project/CHANGELOG.md:3074`).
- **The review before money.** "Every gate the studio had ran after the money was spent" — QC measured a
  rendered file, the Director watched a film generated "at two dollars sixty a shot"
  (`backend/app/factual/story_review.py:1-21`; `backend/app/factual/models.py:165-174`).
- **The Nepal/telescope rehearsal (2026-09-18).** A script about the James Webb telescope cited a SUPPORTED
  Nepal climate-finance claim and passed the factual gate, the story review and the Director. The lexical
  grounding check was built so "she is never the one thing standing between a Nepal topic and a telescope
  film" (`backend/app/factual/grounding.py:1-56`; `docs/project/16_DECISION_LOG.md:3695-3745`;
  `docs/architecture/50_CONTENT_GATE_MATRIX.md` "Narration grounding (built 2026-09-19)").
- **The writers' room.** The Owner: "we have plenty of tokens ... We can have ten or twenty exchanges until
  we have a film. The day closes when the short is published" → `MAX_REVISIONS` 19 / `MAX_EXCHANGES` 20
  (`backend/app/factual/story_review.py:97-111`; `docs/project/CHANGELOG.md:2816-2836`). A reviewer who
  could not see the conversation said REVISE nine times → exchange number and earlier notes in her prompt
  (`docs/project/CHANGELOG.md:2783-2800`; `backend/app/factual/story_review.py:559-567`).
- **Taste loops (2026-10-10, «How NASA Keeps a Space Telescope Alive With Frozen Fuel»).** A second
  taste-only REVISE on a draft that passes every check is a loop; the studio goes on
  (`backend/app/factual/story_review.py:121-139`).
- **Editorial judgement (Owner card 2026-10-11 23:30).** ATLAS/Higgs short passed every structural check
  yet was "jargon for experts" → five-criterion score, up to ten rewrites, best ships
  (`backend/app/factual/story_review.py:23-33`; `docs/project/16_DECISION_LOG.md:71-73`).
- **No duplicate subjects (2026-10-12).** «The Particle That Shouldn't Exist (And Briefly Didn't)» was made
  two days after «... (But Does)»; the subject check now compares against ideas, scripts, storyboards and
  publications (`backend/app/research/agent.py:121-168`; `docs/project/16_DECISION_LOG.md:19-21`).
- **Incidents encoded in parsers.** A model's `"confidence": 0.95.0` "stopped a whole day" → per-object
  salvage (`backend/app/factual/agent_pipeline.py:148-158`); an LHC-upgrade ending told from the writer's
  own knowledge → uncited-scene retry (`:746-787`); a guessed address returned 404 every time → found pages
  first (`backend/app/research/agent.py:692-704`).

---

## Who decides here

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| Whether topic proposal or source gathering can run at all | CODE_RULE | `backend/app/research/agent.py:407-411`, `:725-729` | At least one host that is authorised **and** (from `.env` or last test PASSED) (`_tested_hosts`, `:171-181`); else `NoAuthorisedHosts` |
| Which candidate topics exist | LLM_CHECKED_BY_CODE | `backend/app/research/agent.py:450-497` | Lead Researcher proposes; per-candidate schema (`TopicCandidate`), max `MAX_CANDIDATES`=8 |
| A candidate duplicates an existing subject | CODE_RULE | `backend/app/research/agent.py:121-148`, `:504-509` | Title word-set Jaccard ≥ 0.6, or ≥2 shared 5+-letter title keys, or ≥3 shared keys across title+topic, against ideas, scripts, storyboards, publications (`existing_subjects`, `:155-168`) |
| A candidate names a host the studio may not read | CODE_RULE | `backend/app/research/agent.py:510-515` | `expected_hosts` must be in the tested-host list |
| A candidate is editorially refused (stored REJECTED with reasons) | CODE_RULE (on LLM self-scores) | `backend/app/factual/editorial.py:328-375`; `backend/app/research/agent.py:522-558` | Thesis fields ≥12 chars (cta ≥6); floors hook 0.45, payoff 0.45, story 0.40, fact_confidence 0.55; weighted composite ≥ 0.50; expected_seconds 12..90; hook shares a content word with payoff/ending; CTA not generic. `decided_by="editorial rules"` |
| Researcher declares himself blocked | LLM | `backend/app/research/agent.py:469-486` | `blocker_of(text)` → ESCALATE letter, nothing stored |
| Which topic goes into production | LLM_CHECKED_BY_CODE (Director, outside this group) then CODE_RULE | `backend/app/runbook/stages.py:778-822`; `backend/app/agents/director.py:233-236`; `backend/app/factual/services.py:113-165` | The Director's `choose_topic` runs only when >1 shortlisted topic has a SUPPORTED claim; her pick must be one of the shortlisted ids or it is discarded; otherwise (or on failure) the order is `novelty_score` desc. `select_topic` refuses unless status PROPOSED/RESEARCHED and ≥1 SUPPORTED claim |
| Novelty score of an Owner-typed topic | CODE_RULE | `backend/app/factual/services.py:45-67` | 1 − max Jaccard against last 20 topics, floor 0.1 |
| Which hosts may ever be fetched | OWNER + CONFIG | `backend/app/research/service.py:130-138`, `:187-231`; `backend/app/config.py:92` | `.env` `STUDIO_RESEARCH_ALLOWED_HOSTS` plus Owner rows in `research_allowed_host`; no agent tool reaches the endpoints (`backend/app/factual/router.py:161-163`) |
| Whether an authorised host is usable | EXTERNAL | `backend/app/research/service.py:279-376` | Real front-page fetch; PASSED / FAILED with reason code HTTP_403, HTTP_ERROR, RATE_LIMITED, SCRIPT_ONLY, NETWORK, OTHER |
| Which search address a host uses | OWNER over EXTERNAL | `backend/app/research/service.py:141-147`, `:507-534` | Owner's `search_template` wins; else `discovered_search_template` from the host's own OpenSearch description |
| Which pages exist for a topic | EXTERNAL filtered by CODE_RULE | `backend/app/research/service.py:629-731` | Owner templates → discovered templates → verified web search API (only if limit unfilled); every engine result validated against the allowlist, others dropped and counted |
| Which pages the studio reads for a topic | LLM_CHECKED_BY_CODE | `backend/app/research/agent.py:790-828` | Researcher's plan; when real pages were found, a URL not among them is set aside unread (`GUESS_SET_ASIDE`); found pages are read up to the limit whatever the plan said |
| How many pages per topic | CONFIG | `backend/app/research/agent.py:724`; `backend/app/research/service.py:734-746`; `backend/app/config.py:442` | `research_pages_per_topic` (default 4, clamp 1..12), capped at `MAX_URLS`=8 |
| Whether a fetched page is stored | EXTERNAL + CODE_RULE | `backend/app/research/retrieval.py:166-357`; `backend/app/research/service.py:827-866` | HTTPS:443 only, allowlisted host (all authorised hosts, tested or not), DNS resolves only to global IPs, ≤3 redirects re-validated, 15 s deadline, ≤2 MB body, text 10..100 000 chars, HTML/plain only, no compression; 429 → no retry. A script-only shell is refused only when its text is under 10 chars (`retrieval.py:327-331`); a shell with 10..499 chars is returned flagged `scripts_required`, which only the host test reads (`service.py:310`) — `retrieve_and_ingest` stores it |
| Prompt-injection handling of stored text | CODE_RULE | `backend/app/factual/sanitizer.py:62-101`; `backend/app/factual/services.py:193-210` | Delimiter tokens stripped, 5 regex families redacted to `[FILTERED_ADVERSARIAL_INSTRUCTION]`; `has_injection` only recorded in the event, never blocks |
| Which claims a source yields | LLM | `backend/app/factual/agent_pipeline.py:229-252` | Schema `ExtractClaimItem`, first 12 kept; always stored `UNVERIFIED` (`backend/app/factual/services.py:272`). The model's own `importance` is acted on unchecked: it orders the runbook's daily verification queue (CRITICAL first, 24 a day, `backend/app/runbook/stages.py:608-617`) |
| Who may verify a claim | CODE_RULE | `backend/app/factual/agent_pipeline.py:302-331` | Never the agent that extracted it; FactChecker role preferred; none available → `NoIndependentVerifier` (HTTP 409) |
| A claim's verdict (agent path) | LLM_CHECKED_BY_CODE | `backend/app/factual/agent_pipeline.py:408-431` | SUPPORTED/REFUTED need a non-empty `evidence_quote` whose whitespace/case-normalised text is a substring of the stored source; else nothing recorded. Code proves the quote exists, not that it supports or contradicts the claim. UNCERTAIN is recorded with no check at all (the quote is discarded, `:419-420`) and takes the claim out of the runbook's UNVERIFIED queue for good |
| A claim's verdict (Owner path) | OWNER | `backend/app/factual/router.py:320-337`; `backend/app/factual/services.py:285-332` | Any of SUPPORTED/REFUTED/UNCERTAIN/UNVERIFIED with notes; no quote check |
| Whether a script may be written for a topic | CODE_RULE | `backend/app/factual/agent_pipeline.py:666-678` | At least one SUPPORTED claim on the topic, else `NoVerifiedClaims` |
| The writer's length brief | CODE_RULE | `backend/app/factual/editorial.py:169-212`; `backend/app/factual/agent_pipeline.py:622-639` | 2.6 words/s, 0.35 s per scene change, scenes = round(target×2.6/15) clamped 3..12; tolerance ±50 %, max 60 s |
| A draft with a fabricated citation | CODE_RULE | `backend/app/factual/agent_pipeline.py:906-913` | Any `claim_id` not in the topic's SUPPORTED set rejects the whole draft (no retry) |
| A draft with scenes citing nothing | CODE_RULE | `backend/app/factual/agent_pipeline.py:743-787` | One rewrite with the scenes named; then refused if uncited > 1/3 of scenes, otherwise those scenes are cut |
| Numbers on a data card | CODE_RULE | `backend/app/factual/agent_pipeline.py:791-831`, `:916-957` | `media.services.card_problems` against the scene's SUPPORTED claims; one rewrite, then refused |
| Scene kind (LIVE / DATA_CARD / TITLE_CARD / BLACK) | LLM_CHECKED_BY_CODE | `backend/app/factual/agent_pipeline.py:936`; `backend/app/media/services.py:1051-1076` | A declared DATA_CARD/TITLE_CARD/BLACK is kept as is; only a LIVE, missing or unknown kind is re-read by `media.services.classify_scene_kind` from the visual phrase, then from two comparable numbers its claims carry (recorded as `kind_forced_by`). Code never turns a card back into a paid LIVE shot |
| Draft passes the factual gate | CODE_RULE | `backend/app/factual/services.py:353-467` | Every cited claim exists and is SUPPORTED → `VERIFIED_PASS`; else stored `BLOCKED_UNVERIFIED_CLAIMS` and `FactualGateError` |
| Story review computed verdict | CODE_RULE | `backend/app/factual/editorial.py:385-531`; `backend/app/factual/story_review.py:334-411` | 16 checks + `narration_is_grounded` + `every_scene_fits_one_clip`; any non-advisory failure → REVISE |
| Story refused outright | CODE_RULE | `backend/app/factual/story_review.py:408-415` | `every_scene_is_attributed` fails → REJECT; or broken at the wall (19 stalled rounds or exchange ≥ 20) → REJECT |
| Story review final verdict | LLM_CHECKED_BY_CODE | `backend/app/factual/story_review.py:424-473` | Director may turn a computed PASS into REVISE/REJECT, never the reverse; a second taste-only REVISE in the story's history is overridden to PASS; REVISE at the wall becomes REJECT |
| Narration grounded in its claims/topic | CODE_RULE | `backend/app/factual/grounding.py:346-468` | Each cited claim: ≥2 of its terms in the narration; ≥2 topic terms; foreign numbers/names not > 50 % (with ≥2 of them) |
| Every filmed scene fits one motion clip | CODE_RULE + CONFIG | `backend/app/factual/story_review.py:263-309` | Scene clip seconds ≤ selected motion model's max × 1.25 (`SLOWDOWN_ALLOWANCE`) |
| Which draft ships after editorial judgement | LLM_CHECKED_BY_CODE | `backend/app/factual/story_review.py:745-859`; `backend/app/agents/editorial_judgement.py:640-729` | Director scores 5 criteria (pass = total ≥35/50, none <5); code ships the best-scored version whose story review PASSED (`:717-718`). The judge can choose among versions but never stop a film: below the bar the best eligible version still ships, and if she cannot answer the first (passed) draft ships unjudged |
| Number of editorial versions | CONFIG | `backend/app/config.py:15`, `:434`; `backend/app/runbook/stages.py:1048` | `Settings.editorial_rounds`, default 10, 1..20 — versions read, the passed draft included, so at most `editorial_rounds − 1` rewrites |
| Script approval | CODE_RULE (runbook, in the Director's name) or OWNER (route), then CODE_RULE gate | `backend/app/runbook/stages.py:929-972`; `backend/app/factual/router.py:406-431`; `backend/app/factual/services.py:470-546` | The runbook's `_director_approves` makes no model call: it approves automatically when the (final) review verdict is PASS and grounding re-measures as passed, recording `approved_by` = the Director agent. The factual gate is re-run at approval; refuted claim since → `BLOCKED_UNVERIFIED_CLAIMS`. Approval does not itself check a story review (the Owner route can approve an unreviewed script; `story_gate` still guards media) |
| Whether a script may reach paid media steps | CODE_RULE | `backend/app/factual/story_review.py:649-679` | Latest review exists and is PASS, and grounding (re-measured) passed or is not applicable |
| Weekly host retest | CODE_RULE / OWNER | `backend/app/research/service.py:379-400`; `backend/app/factual/router.py:222-236` | Hosts untested for `RETEST_AFTER_DAYS`=7; Owner button uses `max_age_days=0` |
| Research health DEGRADED | CODE_RULE | `backend/app/research/service.py:749-817` | No host / none PASSED; no search address and no verified engine; fewer than 10 SUPPORTED claims. Reports only, stops nothing |

---

## LLM involvement

All seven direct call sites call `app.agents.services.run_agent_task`
(`backend/app/agents/services.py:733`), which composes the agent identity as system prompt, applies the
policy kernel, the daily token ceiling and the USD budget, calls the provider and records the run. A
policy or budget refusal comes back as a run with a `BLOCKED_*` status, not an exception
(`backend/app/agents/services.py:827-856`), so every call site's "status ≠ SUCCEEDED" branch is also
its budget-refusal branch. Every call here passes `emit_message=False`; the three in
`agent_pipeline.py` then write their own speech-bubble event (`_announce`,
`backend/app/factual/agent_pipeline.py:193-205`), the research agent and the story review write letters
(or nothing, e.g. on a PASS). None of them uses `structured_run` or `run_with_strategy`; each parses the
raw text itself (`parse_structured` is a parser, not a second model call).

| # | Call site | Speaker | Task / template | Trust |
|---|---|---|---|---|
| 1 | `agent_extract_claims` `backend/app/factual/agent_pipeline.py:208` | LeadResearcher (fallback: any active agent with a model) | `extract_claims` / `v1` | ADVISORY (stored only as UNVERIFIED) |
| 2 | `agent_verify_claim` `:357` | FactChecker (fallback: any other ACTIVE agent with a model), never the extractor | `verify_claim` / `v1` | CHECKED_BY_CODE (UNCERTAIN unchecked) |
| 3 | `agent_write_script` `:642` | ScriptWriter (fallback: any active agent with a model) | `write_script` / `v1`, `v1+retry`, `v1+cards` | CHECKED_BY_CODE |
| 4 | `draft_with_agent` `backend/app/factual/script_agent.py:28` | ScriptWriter | `write_script` / `v1` | CHECKED_BY_CODE (dead code, no callers) |
| 5 | `_ask_director` `backend/app/factual/story_review.py:544` | Director | `story_review` / `story-review-v1` | CHECKED_BY_CODE (stricter-only) |
| 6 | `propose_topics` `backend/app/research/agent.py:398` | LeadResearcher | `propose_topics` / `research-agent-v1` | CHECKED_BY_CODE |
| 7 | `gather_sources` `backend/app/research/agent.py:707` | LeadResearcher | `gather_sources` / `research-agent-v1` | CHECKED_BY_CODE |

### 1. `agent_extract_claims` — the research agent reads one source

- **Prompt** (`backend/app/factual/agent_pipeline.py:58-75`, Romanian): extract up to 10 atomic,
  verifiable claims; each a JSON object with `claim_text`, `claim_type`
  (STATISTIC/HISTORICAL_EVENT/SCIENTIFIC_FACT/QUOTE/GENERAL), `importance` (CRITICAL/SUPPORTING/FLAVOR),
  `confidence` 0..1; answer only a JSON list. The source is the first 12 000 characters of
  `sanitized_content`, wrapped in `<untrusted_source_evidence hash=...>` (`:227`).
- **Run parameters**: `max_tokens=7200`, `temperature=0.2` (`:229-241`).
- **Answer shape**: `list[ExtractClaimItem]` (`backend/app/factual/schemas.py:89-95`: `claim_text`
  5..2000 chars, Literal type (default GENERAL) and importance (default SUPPORTING), `confidence` 0..1
  (default 0.7); extra keys ignored).
- **Parsing** (`_parse_claims`, `:165-190`): strips a markdown fence; tries the whole text, then the
  outermost `[...]`, then `_salvage_complete_objects` (`:118-162`), which keeps every complete top-level
  object of a truncated list, repairs a doubled decimal (`0.95.0` → `0.95`) and skips an object that still
  fails to decode. The salvage repairs JSON syntax only: the whole list is then validated at once
  (`:189`), so one schema-invalid item (an unknown `claim_type`, a 4-character claim) rejects the whole
  answer. Empty or non-list → `ValueError`. Kept: first `MAX_CLAIMS`=12.
- **What code does with it**: `extract_claims` stores every item as `UNVERIFIED` with
  `extracted_by_agent_id` (`backend/app/factual/services.py:231-282`). The model's `confidence` is stored
  but nothing in this group reads it for a decision; its `importance` is used unchecked by the runbook to
  order the daily verification queue (`backend/app/runbook/stages.py:608-617`). Trust: **ADVISORY** —
  the content is recorded as is, but it cannot reach a script until a different agent verifies it with
  a verbatim quote (the claim wording that a script later cites is still the extractor's).
- **If the model fails**: status ≠ SUCCEEDED or empty text → `ValueError` (`:242-244`); unparseable →
  `ValueError` or pydantic `ValidationError` (a `ValueError` subclass). Nothing is stored. The runbook
  counts it as an unreadable source and moves on (`backend/app/runbook/stages.py:590-599`).
- **Money**: one LLM run (tokens under the gateway's USD budget). No media spend.

### 2. `agent_verify_claim` — an independent agent checks one claim against its source

- **Verifier choice** (`_resolve_verifier`, `:302-331`): an explicit `agent_id` equal to the extractor
  raises `NoIndependentVerifier`; otherwise any ACTIVE agent with provider and model that is not the
  extractor, FactChecker role first.
- **Prompt** (`:257-275`): the task is "does the source below support it", not "is it true in the world";
  answer only `{"status","confidence","evidence_quote","notes"}`; the quote must be copied word for word,
  10-400 chars, empty for UNCERTAIN, "verified automatically against the source". Source: first 12 000
  chars, inert boundary (`:386-388`). `max_tokens=2100`, `temperature=0.0`.
- **Answer shape**: `_Verdict` (`:45-56`): `status` Literal SUPPORTED/REFUTED/UNCERTAIN, `confidence`
  0..1, `evidence_quote` ≤4000, `notes` ≤4000. Parsed by `_parse_verdict` (`:334-354`): fence, whole text,
  outermost `{...}`; anything else → `VerificationRejected`.
- **Checks** (`:409-420`): for SUPPORTED/REFUTED, the quote must be non-empty and
  `" ".join(quote.split()).casefold()` must be a substring of the same normalisation of the **full**
  stored `sanitized_content`; otherwise `VerificationRejected` and the claim stays UNVERIFIED. For
  UNCERTAIN the quote is discarded and nothing is checked: the model's UNCERTAIN is recorded as is, and
  since the runbook only verifies UNVERIFIED claims, it is never retried automatically. The quote's
  existence is checked; whether it actually supports (or contradicts) the claim is the model's judgement.
- **Effects**: `verify_claim` writes status, confidence, notes (clipped to 2000, default text if empty),
  evidence, `verified_by_agent_id` (`:422-431`). SUPPORTED → memory `VERIFIED_FACT` (code comment "Web text
  enters VERIFIED_FACT only after this validation", `:441-442`, implementing "Web text never enters
  VERIFIED_FACT without evidence validation", `docs/architecture/04_AGENT_SYSTEM.md:158`); REFUTED → memory
  `HISTORICAL_EVENT` (`:439-458`).
- **Trust**: **CHECKED_BY_CODE**.
- **If the model fails**: `VerificationRejected` (422 via the route) — the runbook catches every exception
  per claim and counts it as refused (`backend/app/runbook/stages.py:620-628`).
- **Money**: one LLM run. A SUPPORTED verdict is what later makes a topic selectable
  (`backend/app/factual/services.py:140-148`) and a script writable — an indirect path to media spend,
  behind the story review, approval and the media budgets.

### 3. `agent_write_script` — the Script Writer drafts the short

- **Inputs** (`:662-723`): only the topic's SUPPORTED claims, as `- <id>: "<text>"`; the audience
  language line (`app.agents.language.audience_language_line`, default `"en"`); the brief
  `_WRITE_INSTRUCTIONS` (`:465-540`) filled from `narration_budget` and `beat_table`; the topic title; on a
  revision, the previous draft (`previous_draft`, `:591-619`) inside an inert boundary plus up to 8 notes
  and "revise, keep what works" (`:691-720`); then `media.local_media.writer_constraints` (the selected
  local video model's shot limit, `backend/app/media/local_media.py:28`).
- **Brief content (rules the model is told)**: one idea, hook in 3 s, causal progression, payoff, ending +
  CTA in a spoken LIVE last scene that loops back to the opening; only listed claims; every scene has
  `claim_ids` copied from the list, a `purpose`, a `kind`; no text in images; people only far or from
  behind; DATA_CARD bars copy value and unit exactly from a claim and name its `claim_id`; BLACK ≤1 s and
  never last; target word count and hard ceiling stated.
- **Run parameters**: first call `v1`, `max_tokens=7200`, `temperature=0.4` (`:724-738`).
- **Answer shape**: `_Script` (`:573-588`): `title` 3..200, `scenes` 1..`MAX_STORY_SCENES`(12) of
  `_Scene` (`:557-570`: `narration` 10..800, `visual` ≤500, `claim_ids` 1..20, `purpose` ≤20, `kind` ≤20,
  `card` any), plus `core_message` ≤240, `takeaway` ≤400, `hook` ≤400, `ending` ≤400, `cta` ≤300,
  `cta_kind` ≤20. Parsed by `_script_object` (`:977-992`) and `_parse_script` (`:1010-1025`).
- **Checks and retries, in order**:
  1. **Uncited scenes** (`:743-787`): if any scene has empty `claim_ids`, a second run (`v1+retry`,
     `temperature=0.3`) with those narrations named. If the second answer still has uncited scenes and they
     are more than one third of all scenes → `ScriptRejected`; otherwise the uncited scenes are dropped
     (`drop_uncited`) and listed in `cut_scenes`.
  2. **Citations** (`_check_citations`, `:906-913`): any id not in the SUPPORTED set → `ScriptRejected`
     (no retry).
  3. **Scene kinds and cards** (`_scene_kinds`, `:916-957`): `classify_scene_kind` decides the kind (it
     keeps a declared DATA_CARD/TITLE_CARD/BLACK and may only turn a LIVE/missing/unknown declaration into
     a card or BLACK); `card_problems` checks each card's bars and numbers against the scene's own and its
     bars' SUPPORTED claims (a bar naming an unsupplied claim is a fault). Faults → one third run
     (`v1+cards`, `temperature=0.2`, `:796-816`), re-checked; faults again → `ScriptRejected`. The third
     answer is parsed with the same `drop_uncited` flag as the second (see oddity 25).
  4. **Purpose fallback** (`_implied_purpose`, `:960-974`): first scene HOOK, last ENDING, second-to-last
     PAYOFF when ≥4 scenes, else SETUP/DEVELOPMENT.
  5. **Story metadata** computed by code: `estimated_seconds` (`expected_seconds`), `structure` (`:864-874`).
  6. **Factual gate** in `generate_script_draft` (`backend/app/factual/services.py:404-438`).
- **Trust**: **CHECKED_BY_CODE**. What is spoken is exactly the scene narrations joined (`:876`).
- **If the model fails**: any non-SUCCEEDED or empty run → `ScriptRejected` (`:739-741`, `:771-776`,
  `:817-822`); nothing stored. The runbook closes the room for that topic on `ScriptRejected`/
  `NoVerifiedClaims` (`backend/app/runbook/stages.py:1061-1071`).
- **Calls per invocation**: 1 to 3 LLM runs.
- **Money**: tokens; the draft's scene list (count and LIVE vs card kinds) is what the media stage later
  prices and buys, behind the story review, approval, `story_gate` and the Owner/budget gates elsewhere.

### 4. `draft_with_agent` — an older writer path (no callers)

- `backend/app/factual/script_agent.py:28-111`. Picks an ACTIVE `ScriptWriter` (does not check that a
  model is assigned, `:52-59`), asks in English for JSON with `title`, `voiceover_full_text`, `scenes`,
  `referenced_claim_ids` (`:64-72`), `max_tokens=9000`. Answer schema `ScriptOutput` (`:20-25`,
  `extra="forbid"`, ids as UUID). Code checks `referenced_claim_ids ⊆` supplied SUPPORTED ids (`:95-100`)
  and the factual gate. Trust CHECKED_BY_CODE. A grep of `backend/` and `tests/` finds no caller of
  `draft_with_agent` or of the module.

### 5. `_ask_director` — the Director reads the story before production

- **Prompt** (`backend/app/factual/story_review.py:173-192`, `:568-617`): read the script "as a viewer on a
  phone"; answer the hook, one-idea, progression, payoff, ending, CTA, picture-feasibility and stranger
  questions; give retention at 0/3/5/10/15/20/25 s and end; PASS / REVISE / REJECT. Appended: the exchange
  number ("of at most 20", or "no attempt limit" when `continuous`), her earlier notes with "a note already
  acted on is settled", at the wall "Answer PASS or REJECT, not REVISE", the computed failures with "do not
  return PASS", the advisory flags with "the flag is not a verdict", the local model's shot limits, and the
  script facts JSON (`_script_facts`, `:224-260`, cut to 14 000 chars) inside an inert boundary.
- **Run parameters**: `max_tokens=3000`, `temperature=0.2` (`:618-630`); the gateway multiplies a
  Director's `max_tokens` by `Settings.director_token_multiplier` (default 2, so 6000 effective;
  `backend/app/agents/services.py:792-798`, `backend/app/config.py:11`, `:425`).
- **Answer shape**: `StoryVerdict` (`:162-170`): `verdict` pattern `^(PASS|REVISE|REJECT)$`,
  `hook_strength`/`clarity`/`payoff`/`cta_fit` 0..100, `retention` (`Retention`, `:146-159`), `notes` ≤10.
  Parsed with `app.agents.identity.parse_structured` (fits over-long strings/lists, case-insensitive
  literals, then validates; `backend/app/agents/identity.py:568-645`).
- **What code does with it** (`:443-473`):
  - Her scores and retention are recorded; up to 6 of her notes are appended after the computed checks'
    reasons. The review stores ≤12 notes and the writer's prompt takes ≤8 (`agent_pipeline.py:711`), so
    computed reasons come first and her later notes can be cut.
  - If the computed verdict is PASS and she says REVISE while an earlier reading of this story was already
    taste-only → verdict stays **PASS**, note `TASTE_SETTLED_RO`, `taste_settled=True`.
  - Else if the computed verdict is PASS and she says REVISE or REJECT → her verdict applies
    (`taste_only=True` for REVISE); REVISE at the wall becomes **REJECT**.
  - If the computed verdict is REVISE or REJECT, her verdict is ignored for the verdict (her PASS cannot
    wave a failure through).
- **Trust**: **CHECKED_BY_CODE** — code bounds her authority to "stricter only" and overrides a repeated
  taste REVISE.
- **If the model fails**: `StoryReviewError` (non-SUCCEEDED/BLOCKED run, empty text, or no object
  matching `StoryVerdict`) is caught in `review_story` (`:440-442`); the computed verdict stands alone and
  `model_used` is false. Not caught: a `ValueError` raised by the gateway itself, e.g. "Agent model
  record missing" when the active Director has no model assigned (`agent_for_role` does not check;
  `backend/app/agents/services.py:813-815`) — it propagates out of `review_story`.
- **Money**: her PASS (with the computed checks) is what lets the runbook approve and storyboard
  (`backend/app/runbook/stages.py:929-972`), and `story_gate` then permits the paid media steps; her REVISE
  causes another writer run.

### 6. `propose_topics` — the Lead Researcher proposes ideas

- **Inputs** (`backend/app/research/agent.py:412-449`): tested hosts, the 40 newest idea titles, up to 60
  "made subjects" (every idea, script, storyboard and publication title from `existing_subjects` that is
  not among those 40, sorted alphabetically and cut at 60, `:426-429`), the active
  `ContentStrategy.topic_weights_json`, and `_signals` (`:347-395`: `trending_now` when
  `settings.trends_enabled` — stored `TrendSnapshot` rows of the last 48 h, fetched earlier by the
  runbook's `refresh_trends`, `backend/app/runbook/stages.py:358-359`; and best/worst topic cohorts of ≥3
  videos from the studio's analytics).
- **Prompt** (`_IDEA_INSTRUCTIONS`, `:294-344`): an idea answers why the video should exist; name only
  listed hosts; never repeat recent topics or made subjects; do not propose because something trends; score
  13 dimensions 0..1 honestly; fill the thesis; JSON only. `wanted` = `min(wanted, 8)`; the runbook asks
  for `IDEA_POOL_TARGET (6) − pool` (`backend/app/runbook/stages.py:332`, `:361-363`).
- **Run parameters**: `max_tokens=7500`, `temperature=0.4` (`:450-462`).
- **Answer shape**: `LooseProposal` (≤40 raw dicts, `:281-286`) then per item `TopicCandidate` (`:265-278`:
  `title` 5..200, `topic` 2..600, `angle` 5..2000, `target_audience`, `expected_hosts` ≤6, `scores`
  `TopicScores` (`:187-228`, 12 editorial dimensions + `source_availability`, legacy names mapped),
  `thesis` `TopicThesis` (`:231-262`, text fields clipped)).
- **Checks** (`:493-597`): schema per candidate (a bad one is listed as rejected, not fatal); duplicate
  subject (`_too_similar`); unknown host; `idea_rejections`. A refused idea is still stored, status
  REJECTED, with `rejection_reasons_json` and `decided_by="editorial rules"`; survivors stored PROPOSED with
  `scores_json` incl. weighted `composite`, `thesis_json`, `source_plan_json`. Survivors are remembered
  (`AGENT_OPINION`) and announced in a HANDOFF letter to the Director's inbox (`to_agent_id=None`, not
  `to_owner`, `:608-617`).
- **What code cannot check**: the scores are the model's opinion of its own ideas; code only thresholds them
  (`backend/app/research/agent.py:190-193`: "A score is an opinion about a candidate and never evidence").
- **Trust**: **CHECKED_BY_CODE**.
- **If the model fails**: non-SUCCEEDED/empty → `ResearchAgentError`; unparseable → `ResearchAgentError`;
  structured blocker → ESCALATE letter, empty proposal. The runbook records the stage COMPLETED with zero
  proposals (`backend/app/runbook/stages.py:366-377`).
- **Money**: tokens only. The idea's `novelty_score` is set to the model's `originality` (`:540`, `:575`),
  and the runbook's selection fallback orders by `novelty_score` (`backend/app/runbook/stages.py:782`).

### 7. `gather_sources` — the Lead Researcher picks pages

- **Before the model** (`backend/app/research/agent.py:747-757`): `find_pages` with
  `search_queries(title, topic)` (proper-name runs, ≤6 queries, `:635-670`) — sites' own searches first,
  then the verified web search API; already-stored URLs excluded.
- **Prompt** (`:684-699`, `:758-766`): name up to `limit` pages on the listed hosts (the topic's planned
  hosts, else all tested hosts, first 12); when pages were found, "prefer them ... an address that is not in
  this list is a guess and is not fetched today". Topic title and angle in an inert boundary.
  `max_tokens=3600`, `temperature=0.2`.
- **Answer shape**: `SourcePlan` (`:679-681`): `urls` ≤8 of `SourceCandidate` (`url` 10..1000, `why` ≤500).
- **What code does** (`:790-828`): for each planned URL up to `limit`: skip duplicates (trailing slash
  ignored); if pages were found and this URL is not one of them → recorded as set aside, not fetched;
  otherwise `retrieve_and_ingest` (allowlist + retriever). Then every found page not yet read is fetched
  until `limit` pages are stored. Failures are recorded per URL. Nothing fetched and something failed →
  ESCALATE letter to the Director's inbox, signed "Dr. Aris", with each URL and reason (`:841-861`).
  With found pages, the plan only decides which of them are read first; without found pages the
  Researcher's guessed URLs are what is fetched (allowlist still enforced by code).
- **Trust**: **CHECKED_BY_CODE** — the text stored is what the studio downloaded, never what the model
  expected (`:14-18`).
- **If the model fails**: `ResearchAgentError`; the runbook logs and continues
  (`backend/app/runbook/stages.py:525-532`).
- **Money**: tokens. Page fetches cost nothing in this code. The web search API inside `find_pages` runs
  before the model is asked, not because of its answer.

### Functions here that reach the LLM indirectly

| Function | Line | Reaches the LLM through |
|---|---|---|
| `create_factual_router.post_extract_with_agent` (`POST /api/v1/factual/sources/{source_id}/extract-with-agent`) | `backend/app/factual/router.py:299` | `agent_extract_claims` |
| `create_factual_router.post_verify_with_agent` (`POST .../claims/{claim_id}/verify-with-agent`) | `backend/app/factual/router.py:340` | `agent_verify_claim` |
| `create_factual_router.post_write_with_agent` (`POST .../scripts/write-with-agent`) | `backend/app/factual/router.py:434` | `agent_write_script` (always language `"en"`) |
| `create_factual_router.run_story_review` (`POST .../scripts/{script_id}/story-review`) | `backend/app/factual/router.py:477` | `review_story` → `_ask_director` |
| `review_story` | `backend/app/factual/story_review.py:312` | `_ask_director` |
| `judged_story` | `backend/app/factual/story_review.py:745` | `app.agents.editorial_judgement.editorial_loop` → `judge` (`structured_run`, task `editorial_judgement`, `editorial-judgement-v1`, `max_tokens=2000`, temperature 0.2, at most 2 runs per version; `backend/app/agents/editorial_judgement.py:410-466`), plus, through the `rewrite` callback the static analysis cannot follow, `agent_write_script` and `review_story` → `_ask_director` for each rewrite |

### How much is LLM and how much is rule

- **Of 160 functions in scope, 7 call the gateway; 6 reach it indirectly; 147 are deterministic.** Two
  modules (`editorial.py`, `grounding.py`) exist specifically to answer, without a model, questions a model
  used to answer alone.
- **The LLM generates content**: topic ideas and their self-scores, page choices, claims, verdicts with
  quotes, scripts, story opinions, editorial scores.
- **Code decides admission**: every LLM product here passes at least one content check that can refuse it
  (duplicate/host/editorial rules for ideas; allowlist and real download for pages; verbatim quote for
  verdicts; citation, uncited-scene, card-number, factual-gate, story-check and grounding rules for
  scripts). The places where an LLM answer is acted on with no content check are: the Director's
  REJECT/REVISE on a script that passes every computed check (even there a second taste-only REVISE is
  overridden, `backend/app/factual/story_review.py:456-458`); a verifier's UNCERTAIN (no quote needed,
  `backend/app/factual/agent_pipeline.py:419-420`); the extractor's `importance`, which orders the daily
  verification queue; the Researcher's structured blocker (ESCALATE, nothing stored); the editorial
  judge's scores, which pick which PASS-reviewed version ships (but can never stop one); and the
  self-scores of an idea, which code only thresholds (a model that scores its own idea above the floors
  passes them).
- **Semantic truth remains an LLM judgement in two places**: whether a verbatim quote actually supports a
  claim (`agent_verify_claim`), and whether a narration that repeats two of a claim's words means what the
  claim means (`backend/app/factual/grounding.py:42-45`).

---

## Hard rules and limits

| Name | Value | Where | Meaning |
|---|---|---|---|
| `MAX_CLAIMS` | 12 | `backend/app/factual/agent_pipeline.py:39` | Claims kept per extraction (prompt asks for ≤10) |
| Source text shown to extractor/verifier | 12 000 chars | `backend/app/factual/agent_pipeline.py:227`, `:386` | Truncation of `sanitized_content` |
| Extract / verify / write `max_tokens` | 7200 / 2100 / 7200 | `:238`, `:398`, `:736` | Per run |
| Temperatures | 0.2 / 0.0 / 0.4 → 0.3 → 0.2 | `:239`, `:399`, `:737`, `:769`, `:814` | Extract / verify / write, retry, cards |
| Uncited-scene tolerance after retry | ≤ 1/3 of scenes cut, more → refused | `backend/app/factual/agent_pipeline.py:779` | `len(still) * 3 > total` refuses |
| Revision notes passed to the writer | ≤ 8 | `:711` | |
| `IDEA_WEIGHTS` | hook 0.14, payoff 0.14, story 0.13, fact 0.13, curiosity 0.10, retention 0.09, channel 0.07, visual 0.06, originality 0.05, share 0.04, cta 0.03, feasibility 0.02 | `backend/app/factual/editorial.py:36-49` | Weighted composite (sum 1.00) |
| `IDEA_FLOORS` | hook 0.45, payoff 0.45, story 0.40, fact_confidence 0.55 | `:54-59` | Below → refused |
| `IDEA_MINIMUM_COMPOSITE` | 0.50 | `:62` | |
| Idea length | 12..90 s | `:359-361` | `expected_seconds` outside → refused |
| `WORDS_PER_SECOND` | 2.6 | `:128` | Speaking rate (also read by `media.local_media`) |
| `SCENE_BEAT_SECONDS` | 0.35 | `:129` | Breath per scene change |
| `DURATION_TOLERANCE` | 0.5 | `:140` | Was 0.3; Owner: "fine if it goes over by a few words" |
| `MAX_SHORT_SECONDS` | 60.0 | `:144` | Outer wall |
| `WORDS_PER_SCENE` | 15 | `:150` | Scene count = round(target × 2.6 / 15), clamp 3..12 |
| `MAX_STORY_SCENES` | 12 | `:154` | Writer schema max |
| `STORY_BEATS` | 0-10 % hook, 10-27 % setup, 27-60 % development, 60-87 % payoff, 87-100 % ending | `:160-166` | At 30 s: 0-3/3-8/8-18/18-26/26-30 |
| Budget examples | 20 s → 3 scenes, 49 words (max 75); 30 s → 5 scenes, 73 words (max 112, min 35), 11-18 per scene; 50 s → 9 scenes, 122 words (max 147) | computed by `narration_budget`, `:169-212` | |
| `BLACK_BEAT_SECONDS` | 1.0 | `:278` | A spoken BLACK scene longer than this fails |
| Grounding `MIN_WORD` / `SHARED_PREFIX` / `SUFFIX_SLACK` | 4 / 5 / 2 | `backend/app/factual/grounding.py:70-76` | Stem equality |
| `CLAIM_TERMS_NEEDED` / `TOPIC_TERMS_NEEDED` | 2 / 2 | `:78-80` | Or all terms when fewer |
| `FOREIGN_SHARE_LIMIT` / `FOREIGN_ANCHORS_NEEDED` | 0.5 / 2 | `:86-87` | Numbers+names from nowhere |
| `FATAL_CHECKS` | `every_scene_is_attributed` | `backend/app/factual/story_review.py:78` | → REJECT |
| `ADVISORY_CHECKS` | `ending_answers_the_hook`, `ending_loops_to_hook` | `:95` | Never refuse |
| `MAX_REVISIONS` | 19 stalled rounds | `:107` | Was 2, then 15 |
| `MAX_EXCHANGES` | 20 readings per story (topic) | `:111` | Runbook `MAX_SCRIPT_EXCHANGES` = this (`backend/app/runbook/stages.py:211`) |
| Director review `max_tokens` / payload | 3000 (×`director_token_multiplier`, default 2 → 6000 effective) / 14 000 chars | `:627`, `:568`; `backend/app/agents/services.py:792-798` | |
| Clip slowdown allowance | 25 % | `backend/app/media/cost_plan.py:74`, used at `story_review.py:280` | |
| Editorial bar | total ≥ 35 of 50, each ≥ 5 | `backend/app/agents/editorial_judgement.py:86-89`, `:278-282` | Read by `judged_story` |
| `Settings.editorial_rounds` | default 10, 1..20 | `backend/app/config.py:15`, `:434` | Versions per editorial loop (the passed draft is version 1, so ≤9 rewrites by default) |
| `DUPLICATE_RATIO` | 0.6 | `backend/app/research/agent.py:80` | Title Jaccard |
| `SHARED_TITLE_KEYS` / `SHARED_KEYS` | 2 / 3 | `:111-112` | Subject words ≥5 letters |
| `MAX_CANDIDATES` | 8 | `:81` | Ideas per proposal |
| `MAX_URLS` | 8 | `:84` | Pages per topic ceiling |
| Recent titles / made subjects in prompt | 40 / 60 | `:420`, `:429` | |
| `DEFAULT_CANDIDATES_PER_DAY` / `DEFAULT_PAGES_PER_TOPIC` / `MAX_BUDGET` | 4 / 4 / 12 | `backend/app/research/service.py:82-84` | Settings `research_candidates_per_day`, `research_pages_per_topic` (`backend/app/config.py:441-442`) |
| `RETEST_AFTER_DAYS` | 7 | `backend/app/research/service.py:87` | |
| `MIN_CLAIMS_AVAILABLE` | 10 | `:90` | Health DEGRADED below |
| `find_pages` default limit | 6 | `:633` | Per-host share `max(1, limit // hosts)` |
| `search_pages` default limit | 5 | `:558` | |
| `RetrievalPolicy` defaults | timeout 15 s, 2 000 000 bytes, 100 000 text chars, 3 redirects, cache 300 s × 32 entries | `backend/app/research/retrieval.py:31-65` | Validated ranges: timeout (0,120], bytes 10..10 M, text 10..100 000, redirects 0..5, cache 0..3600 s, 1..128 entries |
| `_SHELL_TEXT_CHARS` | 500 | `:116` | Script-only shell detection |
| URL rules | https, port 443, no userinfo, no backslash, ≤1000 chars, no control chars, host in allowlist | `:166-186` | |
| DNS rule | every resolved IP `is_global` | `:189-194` | Connect to pinned IP, TLS SNI = host (`:197-210`) |
| Search template | contains `{query}`, https, same host, ≤500 chars | `backend/app/research/service.py:421-457`, `:477-504` | |

**State machines**

- `TopicIdea.status` (`backend/app/factual/models.py:30`): `PROPOSED` (Owner route or Researcher) |
  `REJECTED` (editorial rules) → `SELECTED` (`select_topic`, requires ≥1 SUPPORTED claim). `RESEARCHED` is
  accepted as a source state (`backend/app/factual/services.py:136`) but no code writes it. Outside this
  group `SERIAL` (`backend/app/media/serial_storyboard.py:207`) and `DEMO`
  (`backend/app/media/router.py:420`) are written at creation; `PRODUCED` is only read
  (`backend/app/agents/command.py:493`) and, like `RESEARCHED`, written nowhere in `backend/app`.
- `FactualClaim.status`: `UNVERIFIED` (on extraction) → `SUPPORTED` | `REFUTED` (agent with a verbatim
  quote, or Owner) | `UNCERTAIN` (agent with no quote, or Owner) — the Owner may also set it back to
  `UNVERIFIED`
  (`backend/app/factual/services.py:301-302`).
- `ScriptDraft.status`: `VERIFIED_PASS` | `BLOCKED_UNVERIFIED_CLAIMS` (at creation) → `APPROVED` (approval,
  gate re-run) or back to `BLOCKED_UNVERIFIED_CLAIMS` (gate failed at approval). Approval accepts
  `DRAFT`, `VERIFIED_PASS`, `APPROVED`, `BLOCKED_UNVERIFIED_CLAIMS` (`backend/app/factual/services.py:503`).
- `StoryReview.verdict` ∈ `PASS`/`REVISE`/`REJECT` (DB check constraint, `backend/app/factual/models.py:178`).
- `ResearchAllowedHost.last_test_status` ∈ `PASSED`/`FAILED` with `last_test_reason`
  (`backend/app/research/models.py:25-39`).

---

## Modules

### `app.factual` — backend/app/factual/__init__.py (1 line)

Package docstring only: "Phase 4 Factual Intelligence & Verification Engine package." No functions.

### `app.factual.agent_pipeline` — backend/app/factual/agent_pipeline.py (1025 lines)

The LLM-driven steps of the factual pipeline: extraction, independent verification and script writing.
The module docstring states the contract: raw text is advisory until it parses against the exact schema;
claims are stored UNVERIFIED; the extractor never verifies (`:1-7`, FR-038).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_resolve_agent` | 78 | Given `agent_id`: must exist, be ACTIVE, have provider+model. Else the first ACTIVE agent with a model whose role is the preferred role, else any such agent (ordered by role name descending) | One resolver for "who runs this task"; Romanian errors name the settings page | CODE_RULE |
| `_salvage_complete_objects` | 118 | Brace-depth scan outside strings; keeps complete objects, repairs `0.95.0`, skips broken ones | A token cap mid-list, and a doubled decimal that "stopped a whole day" | CODE_RULE |
| `_parse_claims` | 165 | Fence → whole JSON → `[...]` → salvage; validate `list[ExtractClaimItem]`; keep 12 | Nothing unvalidated is stored | CODE_RULE |
| `_announce` | 193 | Writes `agent.message_sent` with the text (≤200 chars) via the outbox | The agent's speech bubble in the office view | CODE_RULE |
| `agent_extract_claims` | 208 | LLM call site 1 (above); stores claims UNVERIFIED; announces | Research agent reads a source | LLM (stored as UNVERIFIED) |
| `_normalise` | 297 | Collapse whitespace, casefold | Quote matched on words, not formatting | CODE_RULE |
| `_resolve_verifier` | 302 | Picks a verifier that is not the extractor; FactChecker preferred | FR-038 independence | CODE_RULE |
| `_parse_verdict` | 334 | Fence → JSON → `{...}`; validate `_Verdict`; else `VerificationRejected` | Shape before content | CODE_RULE |
| `agent_verify_claim` | 357 | LLM call site 2; verbatim-quote check; `verify_claim`; memory | Independent fact check | LLM_CHECKED_BY_CODE |
| `previous_draft` | 591 | Newest draft of the topic as title/hook/core/ending/cta/scenes | "A revision is a revision": the writer must see what he revises (`:692-698`) | CODE_RULE |
| `_write_instructions` | 622 | Fills `_WRITE_INSTRUCTIONS` from `narration_budget` and `beat_table` | Brief and check read the same numbers | CODE_RULE |
| `agent_write_script` | 642 | LLM call site 3 (1-3 runs), checks, stores via `generate_script_draft` | Script from verified claims only | LLM_CHECKED_BY_CODE |
| `_check_citations` | 906 | Any unknown claim id → `ScriptRejected` | A fabricated citation discredits the whole draft | CODE_RULE |
| `_scene_kinds` | 916 | Kind per scene via `classify_scene_kind`; card checked by `card_problems` against SUPPORTED claims | Cards are drawn for free from these numbers; a wrong one is never stored | CODE_RULE |
| `_implied_purpose` | 960 | Positional fallback purpose | A guess, marked as fallback; the review still checks payoff | CODE_RULE |
| `_script_object` | 977 | JSON object from the answer, fences/prose tolerated | | CODE_RULE |
| Helpers: `_role_ids` (111, role ids by name), `_scene_dicts` (995, scenes list from raw answer), `_uncited_scenes` (1001, narrations of scenes with no `claim_ids`), `_parse_script` (1010, optional drop of uncited scenes, validate `_Script`) | | | | CODE_RULE |

Exceptions: `VerificationRejected` (`:278`), `NoIndependentVerifier` (`:288`), `ScriptRejected` (`:543`),
`NoVerifiedClaims` (`:553`) — all `ValueError` subclasses.

Data read/written: reads `SourceSnapshot`, `FactualClaim`, `TopicIdea`, `ScriptDraft`, `Agent`, `Role`;
writes claims and drafts through `app.factual.services`; events `agent.message_sent` (outbox) plus those of
the services; memory `VERIFIED_FACT` / `HISTORICAL_EVENT`. External calls: LLM via `run_agent_task` only.

### `app.factual.editorial` — backend/app/factual/editorial.py (541 lines)

The studio's editorial judgement "that can be stated as a rule": deterministic and cheap, run "before an
agent is asked anything and before a single shot is bought" (`:1-24`). Also the shared home of
`WORDS_PER_SECOND` and `FUNCTION_WORDS` used by media (`backend/app/media/local_media.py:49`,
`backend/app/media/assembler.py:39`, `backend/app/media/qc.py:48`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `narration_budget` | 169 | Target, max seconds (×1.5, ≤60), scene count, total/max/min words, per-scene range, beats in seconds | The brief once gave words but not scenes; 78 words over 7 scenes was unwritable (`:172-177`); beats priced in (`:181-186`) | CODE_RULE |
| `beat_table` | 215 | The beats as text lines for the brief | Stays true at any length | CODE_RULE |
| `dangles` | 266 | A word is a function word without closing punctuation | One list for caption cutter and QC, so they cannot drift (`:234-239`) | CODE_RULE |
| `content_words` | 285 | Lowercased words >2 letters minus stopwords, then `rstrip("'s")` — which strips every trailing `'` and `s` character, not only a possessive ("class" → "cla", "process" → "proce") | Crude, checkable word overlap | CODE_RULE |
| `composite` | 291 | Weighted mean over dimensions present | Weighted, not averaged; partial answers scored on what they said | CODE_RULE |
| `expected_seconds` | 307 | Words / 2.6 + 0.35 per scene change | The number the review compares with the target | CODE_RULE |
| `idea_rejections` | 328 | The editorial rules a candidate fails (see table above) | "Every rule here is one the Owner stated" (`:331-333`) | CODE_RULE |
| `story_checks` | 385 | 16 named checks with Romanian reasons: `has_hook`, `hook_is_not_generic`, `every_scene_has_a_purpose`, `every_scene_is_attributed`, `has_payoff` (REVEAL/PAYOFF in the second half), `has_ending` (label or the declared ending's words in the last scene), `ending_answers_the_hook`, `ending_is_not_black`, `black_is_a_beat`, `ending_loops_to_hook`, `has_one_message` (12..240 chars), `has_progression` (causal connective present, no "and then"), `cta_belongs_to_the_story`, `cta_kind_is_stated`, `title_keeps_its_promise`, `duration_is_realistic` | "Everything about a script that can be checked without asking a model" | CODE_RULE |
| `failed` | 534 | Names of failed checks | | CODE_RULE |
| `revision_notes` | 539 | Reasons of failed checks | Notes name what is wrong instead of "try harder" | CODE_RULE |
| Helpers: `_scene_kind` (281), `_check` (381) | | | | CODE_RULE |

Data: none (pure functions). External calls: none.

### `app.factual.grounding` — backend/app/factual/grounding.py (514 lines)

The computed half of "does the narration say what its claims say": lexical, deterministic, explained.
Calibrated on 31 drafts of 2026-09-12 and the Nepal rehearsal (`:46-51`). Implements
`docs/architecture/50_CONTENT_GATE_MATRIX.md` "Narration grounding (built 2026-09-19)".

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_spell_numbers` | 208 | Rewrites spelled-out numbers (EN/RO) as digits in place | "six hundred million" was a 6 and a 100; the faithful Nepal film was refused at 0.75 foreign share (`:151-154`) | CODE_RULE |
| `_read_run` | 179 | Value(s) of a run of number words; two 10-99 groups = a spoken year | "twenty eighteen" is 2018 | CODE_RULE |
| `_numbers` | 255 | Canonical numbers ("7,000" = "7.000" = 7000) | | CODE_RULE |
| `_same_number` | 268 | Equal, or a decimal and its rounded whole | "about 83 billion" says 83.3 | CODE_RULE |
| `_terms` | 279 | Content words, numbers, names (capitalised not at sentence start, or ≥2 capitals) | Numbers and names survive translation | CODE_RULE |
| `_same` | 313 | Stem equality: 5-letter shared prefix, or prefix with ≤2 letters slack; numbers via `_same_number` | Paraphrase and EN/RO cognates; slack 3 matched "bill"/"billion" | CODE_RULE |
| `is_serial_script` | 332 | `story.kind == "office_serial_episode"` | Serial makes no world claims | CODE_RULE |
| `measure_grounding` | 346 | NOT_MEASURED (no claims, a missing claim, no narration) / PASSED / REFUSED with reasons and all counts | The rehearsal's telescope film | CODE_RULE |
| `script_grounding` | 471 | Loads topic + cited claims of a stored script; None for serial (kind or topic status SERIAL) | Used by the review, `story_gate`, `_director_approves`, `app.agents.editorial` | CODE_RULE |
| `grounding_check` | 497 | Measurement as a story-review check | | CODE_RULE |
| Helpers: `_fold` (145, diacritics off, lowercase), `_found` (328), `_quote` (341) | | | | CODE_RULE |

Data: reads `TopicIdea`, `FactualClaim` (in `script_grounding`). Writes nothing.

### `app.factual.models` — backend/app/factual/models.py (201 lines)

SQLAlchemy tables, no functions:

| Table | Line | Key columns | Notes |
|---|---|---|---|
| `topic_idea` (`TopicIdea`) | 21 | `title`, `topic`, `angle`, `status`, `novelty_score`, `scores_json`, `source_plan_json`, `thesis_json` (0032), `rejection_reasons_json`, `priority`/`priority_reason` (0033), `proposed_by_agent_id`, `decided_by`, `decision_notes`, `selected_at` | "A score is an opinion about a candidate, never evidence about the world" (`:31-32`) |
| `source_snapshot` (`SourceSnapshot`) | 63 | `url`, `title`, `publisher`, `content_hash` (SHA-256 of raw), `raw_content`, `sanitized_content`, `credibility_score`, `fetched_at` | |
| `factual_claim` (`FactualClaim`) | 87 | `claim_text`, `claim_type`, `importance`, `status`, `confidence`, `evidence_text`, `verifier_notes`, `extracted_by_agent_id`, `verified_by_agent_id` | NULL agent = older claim or the Owner (`:105-107`) |
| `script_draft` (`ScriptDraft`) | 123 | `version`, `title`, `target_duration_seconds` (default 50), `voiceover_full_text`, `scenes_json`, `status`, `claim_ids_json`, `unverified_claim_ids_json`, `story_json` | |
| `hook_option` (`HookOption`) | 149 | `hook_text`, `hook_technique`, `retention_score_estimate`, `is_selected` | |
| `story_review` (`StoryReview`) | 165 | `verdict` (check constraint), `checks_json`, `retention_json`, `scores_json`, `notes_json`, `estimated_seconds`, `reviewer_agent_id`, `run_id` | Index on (`script_id`, `created_at`) |

### `app.factual.router` — backend/app/factual/router.py (538 lines)

All routes mounted at `/api/v1/factual` (`backend/app/main.py:976`) behind `require_owner`
(`router.py:109`): every endpoint here is an Owner action with the Owner token. Command bodies are
`extra="forbid"`.

| Function | Line | Route | What it does | Decided by |
|---|---|---|---|---|
| `create_factual_router` | 108 | — | Builds the router (431 lines of nested handlers) | — |
| `post_topic` | 112 | `POST /topics` | `propose_topic_idea` | OWNER |
| `get_topics` | 123 | `GET /topics` | List, optional status filter | — |
| `post_source` | 130 | `POST /sources/ingest` | Owner pastes a source (text, URL string, credibility default 0.8); sanitised and stored; not fetched, URL not checked against the allowlist | OWNER |
| `get_sources` | 144 | `GET /sources` | Sources with claim counts, allowed hosts and host rows | — |
| `get_allowed_hosts` | 157 | `GET /sources/allowed-hosts` | Host rows | — |
| `put_allowed_host` | 161 | `PUT /sources/allowed-hosts/{host}` | Authorise a host; "Agents have no tool that reaches this endpoint" | OWNER |
| `delete_allowed_host` | 169 | `DELETE /sources/allowed-hosts/{host}` | Revoke an Owner host (`.env` hosts refused) | OWNER |
| `post_test_allowed_host` | 177 | `POST /sources/allowed-hosts/{host}/test` | Real front-page fetch, recorded | OWNER triggers, EXTERNAL result |
| `put_search_template` | 190 | `PUT /sources/allowed-hosts/{host}/search` | Record or clear the host's search address | OWNER |
| `post_search_test` | 198 | `POST /sources/allowed-hosts/{host}/search/test` | Runs `search_pages`, stores nothing | EXTERNAL |
| `get_research_health` | 213 | `GET /research/health` | `research_health` (no probing) | CODE_RULE |
| `post_retest_allowed_hosts` | 223 | `POST /research/allowed-hosts/retest` | `retest_stale_hosts(max_age_days=0)` | OWNER |
| `post_retrieve_source` | 239 | `POST /sources/retrieve` | `retrieve_and_ingest`; 503 no allowlist, 422 host not allowed, 429 rate limited (no retry), 502 other | OWNER + EXTERNAL |
| `post_extract_claims` | 285 | `POST /claims/extract` | Owner-supplied claims stored UNVERIFIED | OWNER |
| `post_extract_with_agent` | 299 | `POST /sources/{source_id}/extract-with-agent` | `agent_extract_claims`; 422 on `ValueError` | LLM |
| `post_verify_claim` | 321 | `POST /claims/{claim_id}/verify` | Owner records a verdict (any status) | OWNER |
| `post_verify_with_agent` | 340 | `POST /claims/{claim_id}/verify-with-agent` | `agent_verify_claim`; 409 no independent verifier, 422 rejected verdict | LLM_CHECKED_BY_CODE |
| `get_claims` | 366 | `GET /claims` | Filter by topic/source/status | — |
| `post_generate_script` | 382 | `POST /scripts/generate` | Owner-written draft through the factual gate (422 with unverified ids) | OWNER + CODE_RULE |
| `post_approve_script` | 407 | `POST /scripts/{script_id}/approve` | `approve_script_draft` (gate re-run; 422 lists claims no longer supported); `approved_by` not set | OWNER + CODE_RULE |
| `post_write_with_agent` | 434 | `POST /scripts/write-with-agent` | `agent_write_script` with `revision_notes` (≤8, each ≤2000) and duration 15..180; 409/422 mappings | LLM_CHECKED_BY_CODE |
| `get_scripts` | 470 | `GET /scripts` | List | — |
| `run_story_review` | 477 | `POST /scripts/{script_id}/story-review` | `review_story` for a script written or approved by hand | LLM_CHECKED_BY_CODE |
| `read_story_review` | 497 | `GET /scripts/{script_id}/story-review` | Latest review or `verdict: NONE` | — |
| `post_generate_hooks` | 519 | `POST /hooks/generate` | Store Owner-supplied hook options | OWNER |
| `get_hooks` | 532 | `GET /scripts/{script_id}/hooks` | List by `retention_score_estimate` desc | — |

Command models: `AgentExtractCommand` (`:73`), `WriteScriptCommand` (`:80`), `RetrieveSourceCommand`
(`:94`, deliberately no host/policy/timeout field).

### `app.factual.sanitizer` — backend/app/factual/sanitizer.py (112 lines)

Zone D (untrusted web data) isolation per `docs/architecture/40_THREAT_MODEL_SECURITY_BOUNDARIES.md` and
`30_PROMPT_CONTEXT_MEMORY_ARCHITECTURE.md` (`:1-5`). `wrap_in_inert_boundary` is also imported by 17 modules outside this group (agents, economy, media, story).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `strip_llm_delimiters` | 62 | Replaces 10 chat-template tokens (`<|im_start|>`, `[INST]`, `### System:` ...) with a space; counts them | Control tokens must not leak from web text | CODE_RULE |
| `detect_prompt_injections` | 74 | Names matched pattern families: INSTRUCTION_OVERRIDE, SYSTEM_PROMPT_PROBE, PERSONA_HIJACK, HTML_SCRIPT_TAG, CODE_EXEC_PROBE | Flag for the ingest event | CODE_RULE |
| `sanitize_untrusted_text` | 83 | Strip, detect, redact matches to `[FILTERED_ADVERSARIAL_INSTRUCTION]`, normalise newlines | Stored `sanitized_content` | CODE_RULE |
| `wrap_in_inert_boundary` | 104 | `<untrusted_source_evidence hash="...">text</untrusted_source_evidence>` | Prompt templates mark data as data | CODE_RULE |

### `app.factual.schemas` — backend/app/factual/schemas.py (203 lines)

Pydantic commands and views, no functions. Notable limits: `IngestSourceCommand.raw_content` 10..100 000
(`:47`), `credibility_score` default 0.8 (`:48`); `ExtractClaimItem` (`:89-95`, also the LLM answer
schema); `ExtractClaimsCommand.claims` 1..50; `VerifyClaimCommand.status` includes `UNVERIFIED`
(`:109`), `verifier_notes` ≥3 chars; `GenerateScriptCommand.target_duration_seconds` 15..180,
`referenced_claim_ids` 1..50 (`:141-149`); `CreateHookOptionItem.hook_technique` Literal of 5
(`:168-173`); `SearchTemplateCommand` (`:194`), `SearchQueryCommand` 2..200 (`:201`).

### `app.factual.script_agent` — backend/app/factual/script_agent.py (111 lines)

An earlier writer path, superseded by `agent_write_script`; no callers in `backend/` or `tests/`.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `draft_with_agent` | 28 | LLM call site 4 (above): SUPPORTED claims (optionally a chosen subset, all on this topic) → ScriptWriter → `ScriptOutput` → id subset check → `generate_script_draft` | "Generate a draft using the assigned writer, then validate all cited evidence IDs" (`:1`) | LLM_CHECKED_BY_CODE |

### `app.factual.services` — backend/app/factual/services.py (609 lines)

The record-keeping core: topics, sources, claims, the factual gate, drafts, approval, hooks. No LLM.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `FactualGateError.__init__` | 35 | Carries `unverified_claim_ids` | The route tells the Owner which claims | — |
| `compute_content_hash` | 40 | SHA-256 of stripped text | Source identity | CODE_RULE |
| `compute_novelty_score` | 45 | 1 − max Jaccard (word sets) vs 20 newest topics, floor 0.1 | `docs/architecture/44_CONTENT_DEDUPLICATION_NOVELTY.md` | CODE_RULE |
| `propose_topic_idea` | 70 | Stores an Owner topic, status PROPOSED, event `factual.topic_proposed` | Owner route | OWNER |
| `select_topic` | 113 | PROPOSED/RESEARCHED + ≥1 SUPPORTED claim → SELECTED, event `factual.topic_selected`, `decided_by`/notes; idempotent | "only if there is something true to say about it" (`:120-125`) | CODE_RULE (choice made by caller) |
| `list_topic_ideas` | 168 | List | | — |
| `ingest_source_snapshot` | 177 | Hash raw, sanitise, store, event `factual.source_ingested` with `has_injection`, `flagged_reasons` | One ingestion path for Owner paste and retrieval | CODE_RULE |
| `extract_claims` | 231 | Stores claims UNVERIFIED with extractor id; event per claim `factual.claim_extracted` | Independence needs attribution | CODE_RULE |
| `verify_claim` | 285 | Writes verdict, evidence, notes, verifier; event `factual.claim_verified` | UNCERTAIN is a real outcome (`:297-299`) | caller (OWNER or LLM_CHECKED_BY_CODE) |
| `list_claims` | 335 | Filtered list | | — |
| `evaluate_factual_gate` | 353 | Passed iff every id exists and is SUPPORTED; empty list fails | "Strict Content Gate" (`docs/architecture/50_CONTENT_GATE_MATRIX.md`) | CODE_RULE |
| `generate_script_draft` | 372 | Version = count+1; gate fail → store `BLOCKED_UNVERIFIED_CLAIMS` + event `factual.script_blocked_by_gate` + raise; pass → `VERIFIED_PASS` + `factual.script_verified_pass` | Every draft path ends here | CODE_RULE |
| `approve_script_draft` | 470 | Re-runs the gate; fail → BLOCKED + event + raise; pass → APPROVED + `factual.script_approved` (approved_by, reason) | "a claim may have been refuted since" (`:494-496`); approval is the Director's, the Owner can still use the route (`:480-485`) | CODE_RULE + caller |
| `generate_hook_options` | 549 | Stores supplied hooks, `is_selected=False`, event `factual.hooks_generated` | Hook options for a script | OWNER |
| `list_scripts` | 592 | List | | — |
| `list_hooks` | 601 | List | | — |

Events emitted: `factual.topic_proposed`, `factual.topic_selected`, `factual.source_ingested`,
`factual.claim_extracted`, `factual.claim_verified`, `factual.script_blocked_by_gate`,
`factual.script_verified_pass`, `factual.script_approved`, `factual.hooks_generated`.

### `app.factual.story_review` — backend/app/factual/story_review.py (859 lines)

The review before anything is bought, in two parts that "stay separate on purpose": computed checks, and
the Director's opinion "recorded as one" (`:8-21`); then the editorial judgement (`:23-33`) and the
`story_gate` the media stage asks.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_taste_only` | 121 | A past REVISE whose failures were all non-refusing (or marked `taste_only`) | NASA frozen-fuel film, five rounds on taste (`:125-133`) | CODE_RULE |
| `blocking_count` | 195 | Count of failed, non-advisory, non-flagged checks of a past review | Progress measured without asking anyone | CODE_RULE |
| `stalled_rounds` | 203 | REVISE rounds since the best (lowest) blocking count | "The budget is for going nowhere" (`:353-360`) | CODE_RULE |
| `_script_facts` | 224 | Title, topic, thesis, story, target, estimate, scenes with their claims' texts, grounding | What the Director reads | CODE_RULE |
| `scene_clip_check` | 263 | Each filmed scene's clip seconds ≤ motion model max × 1.25; None without a selected model | 2026-10-10: 11.1 s and 12.5 s scenes under a 10 s model (`:267-271`) | CODE_RULE + CONFIG |
| `review_story` | 312 | Computes checks, history, exchange, wall; asks the Director; settles the verdict; stores `StoryReview` + event `factual.story_reviewed`; non-PASS → letter (CHALLENGE for REJECT, REQUEST_REVIEW for REVISE) from the Director into the studio inbox (`to_agent_id=None`, not `to_owner`), only when a Director exists | "The computed checks decide on their own" (`:323-326`) | LLM_CHECKED_BY_CODE |
| `_ask_director` | 544 | LLM call site 5 (above) | A reviewer who cannot see the conversation cannot finish it | LLM |
| `latest_review` | 640 | Newest review of a script | | — |
| `story_gate` | 649 | (False, why) unless latest review is PASS and grounding passes or is N/A | "a script does not reach the prompt agent — the step that spends money — until the story has been reviewed and passed" (`:652-655`) | CODE_RULE |
| `script_as_text` | 690 | Title + `[n. PURPOSE, KIND] narration (seen: visual)` lines + small context | The editorial judge reads it "as the viewer meets it"; claims omitted on purpose (`:694`) | CODE_RULE |
| `_version_of_script` | 728 | A draft as an editorial `Version`, eligible iff its review is PASS | Only reviewed drafts may ship | CODE_RULE |
| `judged_story` | 745 | Runs `editorial_loop` with a `rewrite` that calls `agent_write_script(notes=[brief])` then `review_story`; records rounds (`editorial.judged`), writes `story_json["editorial"]` per draft, `letter_to_owner` when shipped below the bar; returns the shipped id and its review | Owner card 2026-10-11 | LLM_CHECKED_BY_CODE |

`review_story` verdict algorithm (`:398-473`), exactly:
1. `broken` = failed checks minus `ADVISORY_CHECKS`; `verdict = "PASS" if not broken else "REVISE"`.
2. Any broken check in `FATAL_CHECKS` → REJECT. Else broken and `at_the_wall` → REJECT + note.
   `at_the_wall = not continuous and (stalled ≥ 19 or exchange ≥ 20)`; `exchange = number of StoryReview rows
   of the topic + 1`.
3. With a Director and a registry: her verdict may only tighten a PASS (see call site 5).
4. Store; message on non-PASS.

`continuous=True` (used by `backend/app/media/sheet_story_repair.py:182`, `:227`) disables the wall and
tells her "there is no attempt limit".

### `app.research` — backend/app/research/__init__.py (1 line)

Docstring: "Owner-directed public source retrieval; fetching is not factual verification."

### `app.research.agent` — backend/app/research/agent.py (870 lines)

Runbook §3 (ideas) and the retrieval half of §4 (sources) as an agent, under two rules: "A proposal is not
a fact" and "Every URL is actually fetched" (`:1-19`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_keys` | 115 | Words ≥5 letters minus subject-less long words | Subject keys for duplicates | CODE_RULE |
| `_too_similar` | 121 | Existing title this idea duplicates (Jaccard ≥0.6, ≥2 title keys, ≥3 keys) | 2026-10-12 second Higgs film (`:126-129`) | CODE_RULE |
| `existing_subjects` | 155 | (title, topic) of ideas, scripts, storyboards, publications ("Storyboard:" prefix removed) | Compare against what was made, under any title | CODE_RULE |
| `_tested_hosts` | 171 | Authorised hosts from `.env`, or Owner hosts last tested PASSED | Only readable hosts are offered | CODE_RULE |
| `TopicScores._read_legacy_names` | 214 | Maps `interest`/`credibility`/`novelty`/`cost` to new dimensions | An old-shape answer is scored, not thrown away | CODE_RULE |
| `TopicScores.composite` | 227 | `editorial.composite` | | CODE_RULE |
| `_signals` | 347 | Trends (if enabled; stored `TrendSnapshot` rows of the last 48 h read by `trending_now`, no network here — the runbook's `refresh_trends` fetched them) and best/worst measured topic cohorts (≥3 videos) | "prefer the kinds of topic that measured well" | CODE_RULE (over EXTERNAL data stored earlier) |
| `propose_topics` | 398 | LLM call site 6 (above) | Ideas without the Owner | LLM_CHECKED_BY_CODE |
| `search_queries` | 635 | ≤6 proper-name queries from title and topic, longest first | A suggestion search matches the start of a page title | CODE_RULE |
| `gather_sources` | 707 | LLM call site 7 (above) | Pages without the Owner pasting links | LLM_CHECKED_BY_CODE |
| Helpers: `_words` (99), `_made_title` (151) | | | | CODE_RULE |

Data: reads `TopicIdea`, `ScriptDraft`, `Storyboard`, `PublicationRecord`, `ContentStrategy`,
`ChannelRecord`, `SourceSnapshot`; writes `TopicIdea` rows (PROPOSED/REJECTED), events
`factual.topic_proposed`, `factual.topic_refused`; memory `AGENT_OPINION`, `HISTORICAL_EVENT`; letters
(HANDOFF, ESCALATE — both to the Director's inbox). External: LLM, site searches, web search API, page
fetches (trends are read from the database, not fetched here).

### `app.research.models` — backend/app/research/models.py (40 lines)

`ResearchAllowedHost` (`:11`): `host` PK, `added_by` (`owner`|`env`), test columns, `search_template`
(Owner, migration 0030), `discovered_search_template`/`discovered_at` (migration 0040), `last_test_reason`.
"Only the Owner writes here ... no agent has a tool that reaches it" (`:14-16`); "a finding never overrides
a decision" (`:33-34`). True of authorisation only: the runbook's weekly `retest_stale_hosts` (code, no
Owner) writes the test columns and the discovered template, and creates `added_by="env"` rows for `.env`
hosts (`backend/app/research/service.py:337-352`).

### `app.research.retrieval` — backend/app/research/retrieval.py (357 lines)

Bounded HTTPS retrieval with exact-host policy and DNS-pinned TLS. Also used by
`backend/app/analytics/trends.py:30` and `backend/app/media/model_research.py:61`.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `RateLimited.__init__` | 26 | Keeps `Retry-After`; message says no retry | 429 is respected, not worked around | CODE_RULE |
| `RetrievalPolicy.__post_init__` | 41 | Lowercase DNS names only; not localhost; not a non-global IP literal; bounded limits | A hostile config fails at build time | CODE_RULE |
| `RetrievedSource.ingest_command` | 87 | `IngestSourceCommand` with `credibility_score=0` | "Retrieval does not establish publisher identity, credibility or claim correctness" (`:88`) | CODE_RULE |
| `RetrievedSource.receipt` | 100 | Digests, URLs, time, type (no text) | Trace what is on screen to the download | CODE_RULE |
| `_PageText.*` | 120-163 | HTML → text; excludes script/style/noscript/template; collects title, OpenSearch `<link>`s, noscript text | Text extraction and shell evidence | CODE_RULE |
| `validate_url` | 166 | URL rules (table above) → normalised URL, host | One validator for every fetch | CODE_RULE |
| `resolve_public` | 189 | All resolved IPs global, pick one | No internal reads (SSRF) | CODE_RULE |
| `_PinnedHTTPS.__init__` / `connect` | 198 / 203 | Socket to the pinned IP, TLS for the hostname | DNS rebinding cannot redirect | CODE_RULE |
| `SourceRetriever.__init__` | 214 | Policy + LRU cache | | — |
| `SourceRetriever.describe_search` | 218 | `fetch(..., accept_xml=True)` | Discovery skips retrievers without it | CODE_RULE |
| `SourceRetriever.fetch` | 227 | Cache (300 s); per hop re-validate + resolve + deadline; 429 → `RateLimited`; redirects ≤3; non-200 → error; MIME check; no compression; size cap; decode; extract; shell detection (raises only when the text is under 10 chars, otherwise returns `scripts_required=True`, `:322-331`); text length check; digests; network/TLS/decoding errors become `RetrievalError` (`:355-356`) | The only way the studio reads the web here | EXTERNAL + CODE_RULE |

Helpers: the `_PageText` parser's methods, summarised in the `_PageText.*` row above:
`__init__` (120), `handle_starttag` (129), `handle_endtag` (145, pops an excluded tag when it
closes, ends the title, breaks a line after a block element) and `handle_data` (153, keeps text
inside script/style/noscript/template out of the page text, setting `<noscript>` text apart as
shell evidence, and sends the rest to the title or the text).

### `app.research.service` — backend/app/research/service.py (898 lines)

Owner allowlist, host tests, search-address discovery, page finding, health, and fetch-and-ingest
(`:1-19`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_rows` | 116 | Table rows that count: Owner rows, and `env` test rows only while `.env` still names the host | A test row must not re-authorise a host dropped from `.env` | CODE_RULE |
| `allowed_hosts` | 130 | `.env` hosts then Owner hosts | The allowlist | OWNER + CONFIG |
| `effective_search_template` | 141 | Owner's template, else discovered; with origin | "a finding never overrides a decision" | OWNER over EXTERNAL |
| `allowed_host_rows` | 162 | Allowlist as shown in the interface (origin, test, templates) | Research door and preflight | — |
| `add_allowed_host` | 187 | `validate_public_host`; create row or adopt an `env` row as Owner's; event `research.host_authorised` | Owner authorises in the interface (`docs/project/16_DECISION_LOG.md:1834-1836`) | OWNER |
| `remove_allowed_host` | 217 | Delete an Owner row; `env` rows refused; event `research.host_revoked` | | OWNER |
| `_failure_reason` | 234 | Closed reason code from retriever text (also for pre-0040 rows) | Preflight shows a code, not prose | CODE_RULE |
| `_test_words` | 262 | Reason code and Romanian detail for a FAILED row | Same words at the Research door and preflight | CODE_RULE |
| `test_allowed_host` | 279 | Fetch `https://host/`; PASSED (+ discovery) or FAILED with reason; row created for `env` hosts; event `research.host_tested` | An authorised site the studio cannot read is not a source | EXTERNAL |
| `retest_stale_hosts` | 379 | Tests hosts not tested within `max_age_days` | Weekly pass inside the research stage (runbook §4) | CODE_RULE |
| `set_search_template` | 426 | Validate `{query}`, https, same host; store; event `research.search_configured` | Owner records a site's search | OWNER |
| `parse_opensearch_description` | 477 | Suggestions JSON template from a description; `{searchTerms}`→`{query}`; optional params dropped; refused if another param, >500 chars, or not same-host https | `docs/project/16_DECISION_LOG.md:2064-2066` | CODE_RULE |
| `discover_search_template` | 507 | Page `<link rel="search">` addresses (same host only), then `/opensearch.xml` | Only two Wikipedias had a template (`:13-18`) | EXTERNAL + CODE_RULE |
| `search_pages` | 553 | One host's search answer; results validated against the allowlist; failure → empty | Find real pages | EXTERNAL + CODE_RULE |
| `verified_search_provider` | 608 | The Owner's `search` integration in a VERIFIED status, key from the vault | "SAVED is not enough" (`:613-614`) | OWNER |
| `find_pages` | 629 | Owner templates → discovered → web search API (only if not full); allowlist filter; dedupe; `report` counts | Runbook §4 order | EXTERNAL + CODE_RULE |
| `research_budget` | 734 | (candidates/day, pages/topic) from settings, clamp 1..12 | | CONFIG |
| `research_health` | 749 | Counts, failing hosts, search provider status, SUPPORTED claims, DEGRADED reasons | Preflight (`backend/app/runbook/preflight.py:1527`) | CODE_RULE |
| `retrieve_and_ingest` | 827 | Allowlist check against every authorised host, tested or not (→ `HostNotAllowed` before any network), fetch, ingest with `credibility_score=0`; returns snapshot + receipt. Does not read `scripts_required`, so a short script-only shell is stored | One fetch-and-store path for the Owner and the Researcher | CODE_RULE + EXTERNAL |
| `list_sources` | 869 | Sources with claim counts per status | | — |
| Helpers: `_host_view` (403), `_same_host_https` (421), `_OpenSearchUrls.__init__`/`handle_starttag` (465/469, XML read with the HTML parser — no entity expansion), `_parse_opensearch` (537, `[q,[titles],[descs],[urls]]`), `_vault_for` (593), `_verified_search_row` (598), `_policy` (820, raises `RetrievalNotConfigured` with no hosts) | | | | CODE_RULE |

Events: `research.host_authorised`, `research.host_revoked`, `research.host_tested`,
`research.search_configured`. External: front-page fetches, OpenSearch reads, site searches, web search
API (vendor), page fetches.

---

## Connections

**Who calls in**

- Daily runbook (`backend/app/runbook/stages.py`):
  - idea stage → `propose_topics` (`:361`) when fewer than `IDEA_POOL_TARGET`=6 PROPOSED/RESEARCHED ideas;
  - research stage → `retest_stale_hosts` (`:564`), `gather_sources` for up to `research_candidates_per_day`
    topics without sources (`:525-532`), `agent_extract_claims` for up to `BATCH`=5 unread sources
    (`:590-599`), `agent_verify_claim` for up to `VERIFY_BATCH`=24 UNVERIFIED claims, CRITICAL first, newest
    first (`:604-628`). Page fetching is gated first by `mode_refusal(engine, "research.fetch_page")`
    (`:559`); MANUAL mode still extracts and verifies but fetches nothing;
  - selection → Director `choose_topic` then `select_topic` (`:804-822`);
  - script stage → `agent_write_script` → `review_story` → `judged_story` → `_director_approves` (grounding
    re-measured, then `approve_script_draft`) for up to `MAX_SCRIPT_EXCHANGES`=20 exchanges
    (`:1014-1071`); unreviewed approved scripts get a backlog `review_story` (`:1089-1103`);
  - `story_gate` at `:3159` and `:5515`.
- Preflight → `research_health` (`backend/app/runbook/preflight.py:1527`).
- Media: `story_gate` in `prompt_agent` (`backend/app/media/prompt_agent.py:1141`, "the last step before
  money"), shooting sheet (`backend/app/media/shooting_sheet.py:1081`), render route
  (`backend/app/media/router.py:554`); `sheet_story_repair` uses `review_story(continuous=True)`,
  `agent_write_script` and `story_gate` (`backend/app/media/sheet_story_repair.py:171-229`).
- Director's last look: `script_grounding` (`backend/app/agents/editorial.py:246`).
- Owner HTTP routes (`backend/app/factual/router.py`).
- Many modules import `wrap_in_inert_boundary`; media imports `dangles`, `SCENE_PURPOSES`,
  `WORDS_PER_SECOND`; `app.story.services` imports `_resolve_agent` (`backend/app/story/services.py:1125`).

**What it calls out to**

- `app.agents.services.run_agent_task` (all LLM), `app.agents.identity` (`parse_structured`,
  `blocker_of`, `clipped`), `app.agents.memory` (`remember`, `agent_for_role`), `app.agents.messages`
  (`post_message`), `app.agents.language`, `app.agents.editorial_judgement` (`editorial_loop`,
  `record_rounds`, `letter_to_owner`).
- `app.media.services` (`classify_scene_kind`, `card_problems`, `card_claim_ids`), `app.media.local_media`
  (`writer_constraints`), `app.media.assembler` (`script_clip_seconds`, `spoken_words`),
  `app.media.cost_plan` (`SLOWDOWN_ALLOWANCE`), `app.media.shooting_sheet` (`motion_clip_limit`).
- `app.analytics.trends.trending_now`, `app.analytics.services.compute_cohort_metrics`.
- `app.providers.search.SearchProvider`, `app.integrations.vault.CredentialVault`.
- `app.services.append_event`, `app.workflows.services.append_event_with_outbox`.

**Events emitted**: the `factual.*` and `research.*` events listed per module, `agent.message_sent`,
`factual.story_reviewed`, `factual.topic_refused`, and (through `record_rounds`) `editorial.judged`. No
event is consumed by this group.

---

## Owner touchpoints

- **Every `/api/v1/factual/*` route is Owner-only** (`require_owner`, `backend/app/factual/router.py:109`).
- **Allowlist**: `.env` `STUDIO_RESEARCH_ALLOWED_HOSTS` (`backend/app/config.py:92`) and the
  authorise/revoke/test/search-address/retest buttons (`backend/app/factual/router.py:156-236`). The Owner's
  search address always beats a discovered one (`backend/app/research/service.py:141-147`).
- **Web search API**: only a `search` integration the Owner connected and verified is used
  (`backend/app/research/service.py:608-626`).
- **Settings**: `research_candidates_per_day`, `research_pages_per_topic` (`backend/app/config.py:441-442`),
  `editorial_rounds` (`:434`), `trends_enabled`/`trends_geo` (`:136-137`).
- **Manual research path**: propose a topic, paste a source, add claims, record a verdict (any status,
  no quote required), write a script through the gate, approve a script (gate re-run; the Owner "can still
  refuse what she allowed", `backend/app/factual/services.py:484-485`), run a story review, add hook
  options.
- **Letters**: the Researcher's ESCALATE when blocked (`backend/app/research/agent.py:471-480`) or when no
  page could be read (`:844-861`), the Researcher's HANDOFF of new ideas (`:608-617`) and the Director's
  REQUEST_REVIEW/CHALLENGE on a non-PASS story (`backend/app/factual/story_review.py:512-525`) all go to
  the **Director's inbox** (`to_agent_id=None` without `to_owner`; `backend/app/agents/messages.py:45-46`,
  `:208-224`), not to the Owner. The only letter to the Owner from this group is the STATUS letter
  `letter_to_owner` (`to_owner=True`), written only when the editorial loop ships a judged version below
  the bar (`backend/app/factual/story_review.py:838-844`;
  `backend/app/agents/editorial_judgement.py:773-822`). It asks nothing.
- **Studio mode**: the page-fetch permission (`research.fetch_page`) is asked in the runbook
  (`backend/app/runbook/stages.py:559`), not inside this group.
- No decision card is raised by code in this group.

---

## Oddities and gaps

1. **Dead code**: `draft_with_agent` (`backend/app/factual/script_agent.py:28`) has no caller in `backend/`
   or `tests/`. Its writer query does not require a provider/model (`:52-59`), unlike `_resolve_agent`.
2. **`RESEARCHED` is never written.** It is accepted in `select_topic`
   (`backend/app/factual/services.py:136`) and read by three runbook queries (`backend/app/runbook/stages.py:346`,
   `:511`, `:781`), but no code assigns it.
3. **Two meanings of `novelty_score`.** Owner topics get a Jaccard novelty
   (`backend/app/factual/services.py:83`); Researcher topics get the model's own `originality` score
   (`backend/app/research/agent.py:540`, `:575`). The runbook orders the selection fallback by
   `novelty_score` (`backend/app/runbook/stages.py:782`).
4. **Stale comments/docstrings**: `TopicIdea.scores_json` says "six criteria ... plus their mean"
   (`backend/app/factual/models.py:31-32`) — the code stores 13 dimensions and a weighted composite
   (`backend/app/research/agent.py:545`). `research_budget` says the two settings are "the integrator's to
   add to `config.py`" (`backend/app/research/service.py:737-739`) — they exist
   (`backend/app/config.py:441-442`). `MAX_REVISIONS`'s CHANGELOG history (2 → 15) differs from the current
   19 (`backend/app/factual/story_review.py:107`); the code comment explains 19.
5. **Prompt vs cap**: the extraction prompt asks for "până la 10" claims (`agent_pipeline.py:62`), the code
   keeps up to 12 (`:39`, `:190`).
6. **`_announce` always tags `task_type: "extract_claims"`** (`backend/app/factual/agent_pipeline.py:203`),
   including for verification (`:432-438`) and script-writing (`:889-896`) announcements.
7. **The Director's REJECT is dropped when the checks already failed.** The comment says "Her REJECT stays
   hers" (`backend/app/factual/story_review.py:455`), but her verdict is applied only when the computed
   verdict is PASS (`:459`); on a REVISE from the checks the stored verdict stays REVISE whatever she said.
8. **Exchange budget is shared with the editorial loop and the backlog.** `exchange` counts every
   `StoryReview` of the topic (`backend/app/factual/story_review.py:361-379`), and each editorial rewrite
   calls `review_story` (`:805-807`), so editorial rounds consume the same 20-exchange budget the runbook
   loop uses.
9. **Event aggregate versions are literals or derived from counters**: `factual.story_reviewed` uses
   `(revisions + 1) if earlier else 1` (`backend/app/factual/story_review.py:482`) — `revisions` is the
   stalled-round count and can go down; `factual.claim_verified` is always 1 (`backend/app/factual/services.py:322`);
   `research.host_tested` always 3 (`backend/app/research/service.py:358`).
10. **Inert boundary is not escaped.** `wrap_in_inert_boundary` (`backend/app/factual/sanitizer.py:104-112`)
    does not neutralise a literal `</untrusted_source_evidence>` inside the text, and
    `DISALLOWED_DELIMITERS` (`:13-24`) does not list it.
11. **Injection detection never blocks.** `has_injection` is only written to the ingest event
    (`backend/app/factual/services.py:207-208`); the redacted text is stored and later shown to agents.
12. **Owner-pasted sources bypass the allowlist and the retriever** (`POST /sources/ingest`,
    `backend/app/factual/router.py:129-141`): the URL is a free string and `credibility_score` defaults to
    0.8, while fetched sources get 0 (`backend/app/research/retrieval.py:97`). Nothing in this group reads
    `credibility_score` for a decision.
13. **Researcher guesses may hit untested hosts.** `propose_topics` limits `expected_hosts` to tested hosts
    (`backend/app/research/agent.py:510`), but `gather_sources` fetches the plan's URLs through
    `retrieve_and_ingest`, whose policy is every authorised host whatever its last test
    (`backend/app/research/service.py:820-824`, `:845-851`), when no pages were found.
14. **Web search API spend is not accounted here.** `find_pages` may query the vendor once per search query
    (`backend/app/research/service.py:694-700`); `backend/app/providers/search.py` records no price or cost
    (grep for cost/price/budget finds nothing).
15. **Hooks are never selected.** `generate_hook_options` stores every hook with `is_selected=False`
    (`backend/app/factual/services.py:572`); no backend code sets it True, while analytics reads selected
    hooks (`backend/app/analytics/services.py:490-492`).
16. **Owner approval through the route records no approver.** `post_approve_script` calls
    `approve_script_draft` without `approved_by` (`backend/app/factual/router.py:413`), so the
    `factual.script_approved` event carries `approved_by: null` for the Owner's own approvals.
17. **`FactualGateError` is not a `ValueError`.** `agent_write_script` can raise it from
    `generate_script_draft` (`backend/app/factual/services.py:435-438`) — in practice only if a cited claim
    stops being SUPPORTED between the writer's read (`agent_pipeline.py:666-673`) and the store, since every
    cited id was read as SUPPORTED; the runbook script loop catches only
    `ScriptRejected` and `NoVerifiedClaims` (`backend/app/runbook/stages.py:1061`). `judged_story`'s rewrite
    and the HTTP route do catch it (`backend/app/factual/story_review.py:795`,
    `backend/app/factual/router.py:454`).
18. **Fallback speakers.** With no LeadResearcher or ScriptWriter, `_resolve_agent` lets any ACTIVE agent
    with a model extract claims or write the script (`backend/app/factual/agent_pipeline.py:100-108`);
    `agent_for_role` (used by `propose_topics`, `gather_sources`, the story review) returns the oldest-hired
    ACTIVE holder of the role without checking it has a model (`backend/app/agents/memory.py:161-168`).
19. **Hard-coded persona signature** "— Dr. Aris" in the no-sources letter
    (`backend/app/research/agent.py:855`).
20. **Verbatim check proves presence, not support.** A quote that exists in the source but does not support
    the claim is accepted (`backend/app/factual/agent_pipeline.py:411-418`); the module and decision log
    state this limit only for grounding (`backend/app/factual/grounding.py:42-45`).
21. **A short script-only shell is stored as a source.** The retriever raises only when a JavaScript shell
    has under 10 characters of text; with 10..499 characters it returns the page flagged
    `scripts_required` (`backend/app/research/retrieval.py:322-331`). Only `test_allowed_host` reads the
    flag (`backend/app/research/service.py:310`); `retrieve_and_ingest` (`:845-866`) stores the shell's
    text as a source the extractor will then read.
22. **An UNCERTAIN verdict is final and unchecked.** The verifier's UNCERTAIN needs no quote
    (`backend/app/factual/agent_pipeline.py:419-420`), and the runbook only re-verifies `UNVERIFIED`
    claims (`backend/app/runbook/stages.py:609-613`), so a model's UNCERTAIN removes a claim from
    automatic verification for good; only the Owner's verify route can reopen it.
23. **A Director without a model makes the story review raise.** `agent_for_role` does not check a model
    is assigned; `run_agent_task` then raises `ValueError("Agent model record missing")`
    (`backend/app/agents/services.py:813-815`), which `review_story` does not catch (it catches
    `StoryReviewError`, `backend/app/factual/story_review.py:440`), nor does the runbook script loop
    (`backend/app/runbook/stages.py:1061`). Plausible from the code, not observed.
24. **The made-subjects list in the idea prompt is an alphabetical slice.** All idea, script, storyboard
    and publication titles not among the 40 newest ideas are sorted alphabetically and cut at 60
    (`backend/app/research/agent.py:426-429`), so on a large record the model sees titles A..something,
    not the most recent ones. The code's own duplicate check (`_too_similar`) still compares against all.
25. **The card rewrite drops uncited scenes without the one-third rule.** When the uncited-scene retry
    already cut scenes, the third (`v1+cards`) answer is parsed with `drop_uncited=True`
    (`backend/app/factual/agent_pipeline.py:823`): any uncited scene in it is dropped silently, however
    many, and `cut_scenes` still lists the second answer's narrations (`:787`). When nothing was cut, an
    uncited scene in the third answer fails the schema and the draft is refused.
26. **Column lengths narrower than the agent schema.** `TopicIdea.topic` is `String(200)` and
    `target_audience` `String(100)` (`backend/app/factual/models.py:26`, `:28`), while `TopicCandidate`
    allows 600 and 300 characters (`backend/app/research/agent.py:268`, `:270`); SQLite does not enforce
    `VARCHAR` length, so it works today and would truncate or fail on a stricter database.
27. **The host model's docstring overstates who writes.** "Only the Owner writes here"
    (`backend/app/research/models.py:14-16`) holds for authorisation, but the runbook's weekly retest
    writes test results and discovered templates and creates `env` rows
    (`backend/app/research/service.py:337-352`).
