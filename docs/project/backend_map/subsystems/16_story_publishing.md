# 16 — The Office Serial story engine and publishing

> Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).
>
> Files (16, 9,782 lines, 258 functions in scope):
> `backend/app/story/__init__.py` (5), `backend/app/story/lines.py` (199), `backend/app/story/locations.py` (81),
> `backend/app/story/models.py` (133), `backend/app/story/projection.py` (604), `backend/app/story/review.py` (1387),
> `backend/app/story/router.py` (206), `backend/app/story/serial_stage.py` (892), `backend/app/story/services.py` (1882),
> `backend/app/publishing/__init__.py` (1), `backend/app/publishing/licence_release.py` (521), `backend/app/publishing/models.py` (155),
> `backend/app/publishing/router.py` (472), `backend/app/publishing/schemas.py` (178), `backend/app/publishing/serial_identity.py` (203),
> `backend/app/publishing/services.py` (2863).

## In one paragraph

The story half turns the studio's own operating day into a daily episode of the Office Serial "Inside The Nexus". A
day is first **closed**: every domain event of the business date is counted into a frozen `DailyStudioLog`, and a
**PUBLIC_SAFE narrative projection** of it (a fixed table of event types, regex redaction, a deterministic story
selection) is stored beside it. A language model in the **showrunner** seat (the ScriptWriter) then writes an episode
from that projection (the only record of the day it sees); code refuses any answer that cites an event not in the
projection, casts a person not on the day's roster, leaves the format's placeholders in, or names a thread that is not
open, and measures the draft with the same checks the review will use, asking once more if it fails. Beside the day's
events, every ask also carries the studio's **picture lessons** for the serial (rules about how its picture models
misread words, written from the Director's model readings of finished films and of pictures quality control flagged
or refused), because each beat's "scene" line is what
every picture of the episode is made from. The **Director** (a second model call) reviews a draft only after a battery
of computed checks passes; her PASS must carry all six rubric scores (else no verdict is stored) and a score below 3
makes code turn it into a FAIL, while her own FAIL rejects the draft as given. A PASS then goes through her
**editorial judgement** loop (up to `Settings.editorial_rounds` versions; her five 0–10 scores are held by code to a
35/50 bar and rank the versions), and the best eligible version is **approved only if the Owner's channel policy
`director_may_approve_episodes` allows it** — otherwise it waits for the Owner's `decide_episode`. An approved episode
advances canon (`ContinuityState`), becomes a storyboard (rows, no vendor), and in the evening stage its GPU filming
is queued (PRODUCTION only, behind the Owner's money rules elsewhere). The publishing half is almost entirely
deterministic: it routes a finished film to the channel its storyboard names, resolves the visibility the Owner's
versioned **publish policy** allows, runs a 7-check **publishing gate** (autonomy stop, file hash, QC, claims,
duplicates, policy authorisation, rights) plus a computed **episode-metadata check**, uploads through the YouTube
adapter with a STARTED→outcome state machine that never re-uploads without asking the platform first, reconciles
uncertain uploads, hands unresolvable ones to the Owner, and later makes public the uploads that were held private
only for an unconfirmed licence. Only **2 of 258 functions** are LLM call sites; 10 more reach a model indirectly; 246
have no static path to a model.

## Why it exists

**Story engine.**

- The architecture asks for two separated truth layers — Operational Truth and the Narrative Layer — and forbids the
  narrative from overwriting or inventing operational facts (`docs/architecture/07_STORY_ENGINE.md` "Two separate truth
  layers", "Forbidden fabrication"). That is implemented structurally: the log is counted and never narrated
  (`backend/app/story/services.py:6-9`, `backend/app/story/models.py:1-14`), and every beat must cite events of the
  day (decision D-P9-001, `docs/project/16_DECISION_LOG.md:1682`).
- The spec also asks for a `NarrativeProjection` before the showrunner sees anything (07_STORY_ENGINE "Narrative
  safety / sanitization"). Measured before `projection.py` existed: every `domain_event` carried visibility OWNER and
  notable events were raw `key=value` payloads with a model id, an agent's full message and a dollar figure
  (`backend/app/story/projection.py:3-9`). Decision "The privacy check and the truth check are one check"
  (`16_DECISION_LOG.md:1900`) made grounding run against the projection alone, and "The Owner's words are a fact, not
  content" (`16_DECISION_LOG.md:1904`) made Owner letters project as the fact of the letter only
  (`projection.py:342-348`).
- Story selection (`select_story`, 2026-09-24): the log used to keep the last 40 public events, so a long day handed the
  writer "a stage of the day ended" and lost the morning's choices; a 2026-09-12 day had 993 events, 900 of them
  routine (`projection.py:27-32`, `projection.py:535-536`).
- Brief v3–v7 history is in the constants' comments: lines `{speaker, text, direction?}` because one voice read names
  and stage directions aloud (`backend/app/story/lines.py:3-7`); the cast rule of 2–4 speakers (the Owner's rule
  2026-09-24, `services.py:96-98`); `OFFERED_SPEAKERS = 3` because the cast check refused 14 of 16 drafts on a copy of
  the Owner's database (`services.py:99-103`); measuring the draft before storing it because 16 of 16 drafts were
  rejected by the computed checks after the writer had finished (`services.py:1580-1586`).
- Picture lessons in the showrunner's brief (`_picture_lessons`, 2026-10-12, review of a9f84ea): the studio's prompt
  lessons reached the shot writer, the visual bible and every rewrite, but never the showrunner's «scene» line, from
  which every shot of an episode is written as the scriptwriter's own (`backend/app/story/services.py:1530-1537`).
  Lessons are kept per kind of film because a factual film's «show people only from behind» would otherwise reach the
  serial, whose fixed rule is «in frame, facing the viewer» (`backend/app/media/prompt_agent.py:141-149`).
- `MAX_DRAFTS_PER_DAY = 3` and `day_to_retell`: every day from 2026-09-19 to 2026-10-10 ended with two refused drafts and
  the serial made nothing (`backend/app/story/serial_stage.py:54-59`, `serial_stage.py:134-137`).
- The editorial judgement (`judged_review`, the Owner's card of 2026-10-11 23:30): «The Zero Script Club» passed every
  structural check and the Director's reading and was "a status meeting with no stake and no punchline"
  (`backend/app/story/review.py:43-53`; decision `16_DECISION_LOG.md:71`).
- `_queue_filming` (2026-10-11): episode 043317d3 was approved at 12:46 UTC by the evening stage and had no storyboard
  until the next morning at the earliest; the serial had never made a public episode (`serial_stage.py:313-322`,
  `serial_stage.py:724-737`).
- The Director's approval is a channel policy, default off (decisions `16_DECISION_LOG.md:1912` and `:1952`): whether
  the studio films an episode on its own is the Owner's decision of the same weight as visibility.

**Publishing.**

- ADR-PHASE6-001 (`16_DECISION_LOG.md:983`): publish without human intervention while guaranteeing that nothing
  unverified, un-QC'd or policy-stopped reaches a platform, private by default, no duplicate uploads, no live
  credentials in CI.
- "A channel's visibility is the Owner's versioned command, not a column a form fills"
  (`16_DECISION_LOG.md:1860`): `autonomous_privacy`, `public_publish_enabled`, `publish_delay_minutes`,
  `policy_version` are changed only by `change_publish_policy`; "public" is never set in TEST because "a public
  release is the one cost that cannot be refunded" (`backend/app/publishing/services.py:352-363`).
- "A film is routed by its storyboard, and an unbound slot is a refusal" (`16_DECISION_LOG.md:1872`): the daily run
  used to publish to `ready[0]`, the first bound slot (`services.py:574-583`).
- The episode-metadata check: in the 2026-09-18 rehearsal the factual film and the serial episode both went up as
  'Infrared light and what it shows' (`services.py:1497-1501`).
- The audit items PUB-01 (never leave a row STARTED), PUB-04 (gate again at execution), PUB-05 (YouTube keeps an
  unaudited project's uploads private), PUB-06 (YouTube limits), PUB-08 (rejected/failed/deleted is not a
  publication), PUB-09 (per-channel upload settings), PUB-10 (sources under a factual film), PUB-12 (letters and the
  Owner's manual resolution), PUB-14 (file hash equals what QC passed) are named in the docstrings of the functions
  that implement them (e.g. `services.py:994-1006`, `services.py:2045-2050`, `services.py:2738-2752`).
- `licence_release.py` (2026-10-10): film babcf272 passed QC and was uploaded private although the channel's policy was
  public, because its ElevenLabs narration had no commercial-use evidence; when the Owner upgraded the plan, nothing
  made the film public afterwards (`backend/app/publishing/licence_release.py:3-9`). The missing-scope letter comes
  from 2026-10-11, when YouTube answered 403 insufficientPermissions (`licence_release.py:457-462`).
- `serial_identity.py`: in the 2026-09-18 rehearsal an episode reached the Publisher as "Storyboard: <title>" with no
  series, number or link (`backend/app/publishing/serial_identity.py:3-7`; spec 07_STORY_ENGINE "New viewer
  accessibility": "episode metadata linking prior related episode").

## Who decides here

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| Which events a day "holds" | CODE_RULE | `story/services.py:394-471` | `close_daily_log` counts every event in the business date's UTC window; a closed date is returned unchanged forever (`:408-412`) |
| Which days get closed | CODE_RULE | `story/services.py:474-513` | Yesterday at run start; every missing date of the last `CLOSE_WINDOW_DAYS = 7`, never before the first recorded event |
| What the showrunner may see of a day | CODE_RULE | `story/projection.py:61-105`, `:213-224`, `:562-597` | Event type must be in `PUBLIC_SAFE_EVENTS` (private by default); every value redacted by 13 regexes + model names on record; story selection by `STORY_WEIGHTS`: at most 15 story lines, topped up with routine lines to 8 when the day has them |
| Whether a day is "quiet" (no episode) | CODE_RULE | `story/projection.py:590-592`, `story/services.py:1594-1598` | No projected line above routine weight 1 → `NothingHappened`, no model call |
| Which day the serial tells | CODE_RULE | `story/serial_stage.py:95-128`, `:131-202` | Newest closed day before today, after the newest told day, within 7 days, with something public; else a refused day with draft budget left, in a fixed priority order |
| Who is offered lines (SPEAKERS) | CODE_RULE | `story/services.py:771-796` | Top `OFFERED_SPEAKERS = 3` by summed story weight of events they act in; filled from ACTIVE roster when fewer than 2 act |
| Which agent writes the episode | CODE_RULE | `story/services.py:1124-1127`, `factual/agent_pipeline.py:78-108` | Given agent (must be ACTIVE with a model, else `ValueError`, `:94`, `:96`), else an ACTIVE ScriptWriter with a model, else any ACTIVE agent with a model (agents ordered by role name descending, `:100-102`); none → `ValueError` (`:104`) |
| Which picture lessons the showrunner is told to follow | CODE_RULE (selection; the lesson text is the Director's model answer, recorded by other modules) | `story/services.py:1530-1555`, `:1650`, `:1672`, `media/prompt_agent.py:3319-3351` | Of the newest 200 live lesson rows of any scope (`memory_record`, STRATEGY, "prompt lesson:", `media/prompt_agent.py:3236-3258`), those of scope "serial" or "all" (a row with no scope tag reads as "all", `:3213-3219`); of two that overlap ≥ 0.6 either way only the newer; confirmed first, then "(unverified)"; 12 in all. Given with `LESSONS_RULE` and as data in an inert boundary ahead of any rewrite section on every ask; none → nothing added |
| What the picture lessons tell the showrunner to do | LLM_CHECKED_BY_CODE (the Director's model text, checked by other modules when it was stored) | `media/prompt_agent.py:3376-3426`, `:3429-3492`, `:164-173` | The lesson words are given to the writer as rules ("follow every one"). Code checked them only when they were recorded: refused if empty, over 400 characters, or naming a film title, a scene or shot number or a record id; nothing checks what they ask for. `LESSONS_RULE` tells the writer a lesson never overrides the brief's fixed rules. The writer's answer is then checked like any other (call site 1) |
| The episode's words, beats, citations, plan | LLM_CHECKED_BY_CODE | `story/services.py:1675-1737`, `:1366-1482` | Schema (`_Episode`); every `event_ids` in the projection; every speaker/background on the roster (`NameBook`); no foreign "Name:" label in a line; no placeholders; thread ids open; `next_episode` complete — any failure is `DraftRefused`, nothing stored |
| Ask the writer a second time inside one write | CODE_RULE | `story/services.py:1738-1761` | If `draft_checks` fail (except `offered_speakers`): one more ask with reasons; keep the answer with fewer failed checks (second on a tie) |
| Draft refused at write → retry | CODE_RULE | `story/serial_stage.py:400-413` | A `DraftRefused` spends one draft; retry with the reason and the refused answer while `drafts < MAX_DRAFTS = 2` |
| Computed review verdict | CODE_RULE | `story/review.py:522-694`, `:978-987` | grounding, privacy, length (45–70 s at 2.5 w/s, ≤ 8 beats), words per beat (8–22), concentration (≤ half the beats per event), cast (2–4 who act), structure (5 parts in order, studio rooms), accessibility, language (English), filmable (each beat fits one motion clip ×1.25); any failure = FAIL without asking a model |
| The Director's PASS on content | LLM_CHECKED_BY_CODE | `story/review.py:988-1024`, `:893-925` | PASS must carry all six rubric scores 1–5 (else `ReviewError`, no verdict); any score < `RUBRIC_FLOOR = 3` turns PASS into FAIL |
| A Director FAIL rejects the draft | LLM | `story/review.py:903-906`, `:1065-1091`, `story/serial_stage.py:443-457` | A model FAIL is acted on as given (schema only; its scores are merely filtered to 1–5): the draft is REJECTED at once, her `notes`/`reasons` become the HANDOFF letter and the next rewrite's brief. No code check can overturn a FAIL |
| Episode approved without the Owner | OWNER (policy) | `story/review.py:221-233`, `:1031-1033`, `:1171-1201` | Only when `ChannelRecord.director_may_approve_episodes` is True on the OFFICE_SERIAL row; set only by the Owner's publish-policy command (`publishing/services.py:399-400`) |
| Episode approved / rejected by hand | OWNER | `story/services.py:1813-1852`, `story/router.py:174-204` | `decide_episode` on any DRAFT; a rejection must carry notes (`router.py:180-183`) |
| Editorial bar ("would a stranger watch it") | LLM_CHECKED_BY_CODE | `agents/editorial_judgement.py:278-282` via `story/review.py:1343-1351` | Director scores 5 criteria 0–10; code passes at total ≥ 35 and every criterion ≥ 5 |
| How many editorial versions | CONFIG | `config.py:15`, `config.py:434`, `story/serial_stage.py:557` | `Settings.editorial_rounds`, default 10, 1–20 |
| Which version ships | LLM_CHECKED_BY_CODE | `agents/editorial_judgement.py:538-544`, `:715-716`, `story/review.py:1352-1380` | The Director's own editorial scores (schema 0–10 only, `agents/editorial_judgement.py:167-187`) rank the versions; code restricts the choice to versions that passed every computed check and her reading (`eligible`) and ranks by its fixed key (total, then lowest criterion, then the earlier version). No judged version → the first, reviewed draft ships unjudged; the others are retired REJECTED |
| A rewrite after a Director FAIL | CODE_RULE | `story/serial_stage.py:443-457` | One rewrite per run (`MAX_DRAFTS = 2`), at most `MAX_DRAFTS_PER_DAY = 3` stored drafts per day across runs |
| Canon moves | CODE_RULE | `story/services.py:614-671` | Only on APPROVED, idempotent by episode id; number +1; threads closed/opened per the episode's own declaration; caps 12 threads, 12 recurring, 3 summaries |
| What canon records (threads closed and opened, recurring items, summary) | LLM_CHECKED_BY_CODE | `story/services.py:1450-1466`, `:628-649`, `story/review.py:570-581` | The writer's declarations become canon as written once the episode is approved; code checks only that closed/continued ids are open threads, that no item is a format placeholder, and (review privacy check) that none of them would be redacted |
| What became of last episode's plan | LLM (recorded as given) | `story/services.py:1347-1363`, `:326` | Writer's `plan_kept` true/false/other → KEPT/DROPPED/UNSAID, written on the earlier episode at approval |
| No new episode while one waits | CODE_RULE | `story/serial_stage.py:603-631`, `:842-853` | A DRAFT waiting for the Owner or for a reading blocks new writing (canon number fixed on approval) |
| Storyboard built for an approved episode | CODE_RULE | `story/serial_stage.py:276-297` | `storyboard_from_episode` (rows, no vendor), then `describe_serial_shots` (video editor's model, once per look version) |
| GPU filming queued tonight | CODE_RULE + OWNER (environment) | `story/serial_stage.py:310-338`, `services.py:645-660` (app) | Only from the evening stage (`media_stage_follows=False`), only in PRODUCTION, once per storyboard key; what it buys is decided later by the Owner's money rules (`runbook.stages.continue_film`) |
| Stage fault retried or fatal | CODE_RULE | `story/serial_stage.py:89-92`, `:706-711` | `runbook.services.classify_fault` == TRANSIENT → `TransientStageError` (retried in place); anything else re-raised. A provider fault inside a model call never gets here: `run_agent_task` returns it as a FAILED run, which ends the attempt COMPLETED (Oddity 20) |
| Channel a film goes to | CODE_RULE | `publishing/services.py:569-651` | Storyboard `channel_id`, else series key (`office_serial` → OFFICE_SERIAL), else MAIN_FACTUAL; contradiction or unbound/unCONNECTED slot = SKIPPED, never another channel |
| Visibility of an autonomous upload | OWNER (publish policy and the environment, both Owner commands: `change_publish_policy`, `app/services.py:244` `change_environment`), applied by CODE_RULE | `publishing/services.py:480-560` | private unless policy says otherwise; unlisted only in PRODUCTION; public only with `public_publish_enabled` and PRODUCTION; delay → private + `publishAt` |
| Publish policy change accepted | OWNER, checked by CODE_RULE | `publishing/services.py:352-470` | Idempotent by command id; stale `expected_version` refused; "public" requires PRODUCTION and the flag in the same command; NO_CHANGE leaves no event |
| Gate 1 — autonomy stop | OWNER (stop) via CODE_RULE | `publishing/services.py:1022-1033` | `OwnerPolicy.autonomy_stopped` refuses |
| Gate 2 — the file | CODE_RULE | `publishing/services.py:1035-1085` | File exists, non-empty, SHA-256 equals `MediaAsset.provenance_hash` |
| Gate 3 — quality control | CODE_RULE (on a QC report made elsewhere) | `publishing/services.py:1087-1129` | Latest report status PASSED and score ≥ `QC_MINIMUM_SCORE = 0.90` |
| Gate 4 — factual integrity | CODE_RULE | `publishing/services.py:1131-1223` | Provenance walkable; every cited claim exists and is SUPPORTED; no claims = pass "nothing to verify" |
| Gate 5 — duplicates | CODE_RULE | `publishing/services.py:1225-1287` | Same asset or same film (script/storyboard) live on this channel refuses; cross-posting to another channel allowed |
| Gate 6 — policy authorisation | CODE_RULE on OWNER policy | `publishing/services.py:1289-1361` | Only for unlisted/public/scheduled: must carry the channel's current `policy_version` and ask no more than the policy resolves to |
| Gate 7 — rights | CODE_RULE | `publishing/services.py:1363-1399` | Only for a visible publication: licence status not in `PRIVATE_ONLY_LICENCE_STATUSES` |
| Episode title/tags allowed | CODE_RULE (checks the Publisher's LLM answer) | `publishing/services.py:1488-1586`, `:1666-1679` | Not the same title (or title+tags) as another film for a different channel in 24 h, counting both publication rows and the Publisher's READY letters (`:1534-1552`); at least one meaning-bearing word (or 5-letter stem) of the hook shared with the episode; an episode with no readable words is refused |
| Upload outcome | EXTERNAL | `publishing/services.py:2277-2374` | YouTube adapter status CONFIRMED / UNKNOWN / RETRYABLE / other → PUBLISHED / REMOTE_UNKNOWN / FAILED_RETRYABLE / FAILED_FINAL |
| Retry after a fault | CODE_RULE | `publishing/services.py:2045-2075` | `providers.retry.is_transient` → FAILED_RETRYABLE, else FAILED_FINAL + letter |
| Re-upload on retry | EXTERNAL then CODE_RULE | `publishing/services.py:2190-2266` | Ask the platform (`ask_reconcile`) first; found → PUBLISHED without uploading; no answer (any exception) → back to FAILED_RETRYABLE, nothing uploaded; the platform answering "not there" (None) → the upload proceeds (`:2268-2286`) |
| Uncertain publication settled | EXTERNAL / OWNER | `publishing/services.py:2418-2619`, `:2738-2808` | `reconcile_*` read YouTube; when the watchdog's bound is spent, `hand_to_owner` → NEEDS_RECONCILIATION; the Owner answers «Există» (with id) / «Nu există» |
| What YouTube says the video is | EXTERNAL | `publishing/services.py:1894-1916` | `remote_privacy_status`/`remote_upload_status` stored; YouTube keeping private a film asked visible → event + Owner letter |
| Held-private upload made public | CODE_RULE + OWNER (mode, policy) + EXTERNAL | `publishing/licence_release.py:281-404` | `may_act(publishing.public_publish, T3, ask_owner=False)` allows (AUTONOMOUS_CEO, `app/services.py:528`; under SUPERVISED only an Owner approval already on record, `:1600-1625`; never under a stop or safe mode); policy resolves public; licence now LICENSED; gate passes except file checks; YouTube `update_visibility`; back-off 15 min doubling to 24 h |
| Licence confirmed | CODE_RULE on recorded evidence (OWNER or EXTERNAL) | `publishing/licence_release.py:201-273`, `media/factory.py:418-440`, `integrations/plan_licence.py:1-13` | Every ledger component without evidence re-read: its take's `commercial_use`, or the commercial-use answer recorded on the connection (`vendor_licence`: the Owner's typed yes, or a paid plan the studio read from the vendor's own API); all commercial-use → LICENSED + event. Written even if the release later stops at the gate or at YouTube |
| Disclosure / footer text | CONFIG | `publishing/services.py:700-791` | `Settings.ai_disclosure_texts`, `studio_display_name`, `content_language`, `ai_disclosure_url`, `creator_channel_title`; built-in en/ro sentences otherwise |
| Default channel slots | CODE_RULE / CONFIG | `publishing/services.py:133-156`, `:244-297` | Two slots seeded with no remote identity (`NOT_CONFIGURED`); production policy seeded once, never overwritten |

## LLM involvement

Every model call in this group leaves through `app.agents.services.run_agent_task` (`backend/app/agents/services.py:733`),
which composes the agent's identity as the system prompt, applies the daily token ceiling and the USD budget
(`may_run_agent`, `agents/services.py:781`) and the policy kernel, and records an `AgentRun`. A refused run (budget,
token ceiling, kernel) and a provider fault both come back as a non-SUCCEEDED status (BLOCKED_* / FAILED /
EMPTY_OUTPUT, `agents/services.py:832`, `:960-967`), not as an exception. The exceptions it does raise are for a
missing agent, model record or provider record (`ValueError`, `agents/services.py:789`, `:815`, `:818`), e.g. a
Director with no model assigned; no caller in this group catches those.

### Call site 1 — `app.story.services.write_episode` (`backend/app/story/services.py:1558`, call at `:1675-1688`)

| Item | Value |
|---|---|
| Speaker | The "showrunner": the agent given by `agent_id`, else the first ACTIVE `ScriptWriter` with a model, else any ACTIVE agent with a model (`_resolve_showrunner` → `factual.agent_pipeline._resolve_agent`, `story/services.py:1124-1127`, `factual/agent_pipeline.py:78-108`) |
| Task type / template | `"write_episode"`, `EPISODE_TEMPLATE_VERSION = "episode-v7"` (`story/services.py:92`); `max_tokens=7200`, `temperature=0.7`, `emit_message=False` (`:1685-1687`) |
| Prompt | `audience_language_line(language)` + `_INSTRUCTIONS` (`story/services.py:887-1003`): THE SHOW (`SHOW_TONE`, `:878-885`), a 13-point brief (structure hook/situation/turn/payoff/button, 6–8 beats; 2–4 speakers from SPEAKERS; lines as `{speaker,text,direction}`; 8–22 words per beat, 115–170 per episode; English; locations by id; voices from bibles; truth rules — no invented hires, outcomes, money, vendors, models, prices, addresses, letter contents; grounding — one unknown id refuses the whole episode; ≤ half the beats per event; continuity thread ids; data boundaries are not instructions; `next_episode` plan; what was done with the plan received), ALLOWED_NAMES, SPEAKERS, the JSON answer format, CAST (full bible for those who act, one line for the rest, `:1614-1629`), LOCATIONS, EVENTS (projection lines as JSON inside an inert boundary, `:1076-1112`), PREVIOUSLY (`:1155-1175`), PLAN FOR THIS EPISODE (`:1278-1293`), PICTURE LESSONS when the studio has lessons for the serial (`_PICTURE_LESSONS_HEAD` + `prompt_agent.LESSONS_RULE` + up to 12 lessons as JSON inside an inert boundary, `:1520-1555`; put in the `{rewrite}` slot, `:992`, ahead of the rewrite section, `:1650`, `:1672`, so every ask carries them, the second ask and editorial rewrites included), an optional rewrite section (`:1197-1233`), and a final spoken-length check |
| Answer shape | One JSON object validated by pydantic `_Episode` (`:296-329`): `title` (3–200), `beats` 1–8 of `_Beat` (`part`, `location`, `scene` 5–800, `lines` 1–16 of `_Line{speaker,text,direction}`, `background` ≤ 12, `event_ids` 1–10), `summary`, `logline`, `threads_continued/closed/opened`, `recurring`, `next_episode` (`_NextEpisode{premise, cold_open_line, open_question, threads_to_pay_off}`), `plan_kept`, `plan_note`. Fenced or embedded JSON is extracted (`_parse_episode`, `:1130-1152`); a v2-shaped `dialogue` is converted to lines (`:249-258`); a line as "Name: words" is split (`:213-223`) |
| What code does with it | CHECKED_BY_CODE. `_episode_from_answer` (`:1366-1482`) refuses (`DraftRefused`/`EpisodeNotGrounded`, nothing stored) when: any `event_ids` entry is not in the day's projection (`:1383-1389`); any speaker or background name is not on the roster after `NameBook` normalisation (`:1393-1401`); a line's text starts with another roster member's "Name:" label (`:1406-1414`); a beat has nothing left to say (`:1424-1425`); title/summary/logline/opened threads/recurring are format placeholders (`:1450-1462`); a thread id is not open (`:1236-1252`); `next_episode` is missing, incomplete, copied, or names a thread that will not stay open (`:1296-1344`). Then `_measured_refusals` (`:1485-1517`) runs the review's own `draft_checks` on the unsaved episode; any failure (except the brief's `offered_speakers` steering) asks once more with the reasons and the first answer as data (`:1741-1757`); the version with fewer failed checks is kept (`:1758-1761`) and stored as a DRAFT with `continuity_json.write_checks` (`:1767-1771`). Locations are normalised to room ids (`:1437`); lines are cleaned of labels and stage directions (`lines.clean_line`). The stored DRAFT then goes through the full review below |
| If the model fails | Non-SUCCEEDED run (provider fault, budget or token-ceiling refusal) or empty text → `StoryError` (`:1689-1691`): the stage ends the day's attempt as COMPLETED with the reason, no retry and no `TransientStageError` (`serial_stage.py:414-418`). Unparseable/invalid first answer → `DraftRefused`: the stage retries with the reason and the answer while a draft is left (`serial_stage.py:400-413`). A failure of the second ask inside `write_episode` keeps the first answer (`:1751-1757`). In an editorial rewrite (`judged_review`'s closure) either error returns None and the loop ships the best version so far (`review.py:1309-1316`). The HTTP route answers 409 (quiet day) or 422 (`router.py:122-128`). No eligible agent → `ValueError` from `_resolve_agent`, which nobody in scope catches (see Oddities) |
| Can it lead to money | Yes. The call itself spends model tokens (budget-gated in `run_agent_task`). A stored draft that passes review and is approved becomes a storyboard and, in the evening stage in PRODUCTION, a queued GPU filming task (`serial_stage.py:481-486`) |

### Call site 2 — `app.story.review.review_episode` (`backend/app/story/review.py:946`, call at `:1001-1013`)

| Item | Value |
|---|---|
| Speaker | The Director: the first-hired ACTIVE agent of role `"Director"` (`REVIEWER_ROLE`, `review.py:113`; `agents/memory.py:161-168`) |
| Task type / template | `REVIEW_TASK = "episode_review"`, `TEMPLATE_VERSION = "episode-review-v3"` (`review.py:107-112`); `max_tokens=3000` (multiplied for the Director by `director_token_multiplier` inside `run_agent_task`), `temperature=0.1`, `emit_message=False` |
| When it is asked | Only when the episode is a DRAFT, has no review yet, a Director exists, every computed check passed, and a registry with at least one model exists (`review.py:963-972`, `:980-988`). A computed failure is the verdict without any model call (`:980-987`) |
| Prompt | `audience_language_line` + `_INSTRUCTIONS` (`review.py:188-218`: truth — FAIL any beat whose outcome is not in the cited event or that quotes a letter known only by its subject; the viewer — 3-second hook, situation/turn/payoff, button; voices against the bibles; continuity; score hook, situation, turn, payoff, voices, button 1–5) + the facts from `review_facts` (`:727-814`: each beat with its lines and the cited events' public words and actors, the speakers' bible voice fields, the serial's memory, the measured checks) fitted to `FACTS_BUDGET = 14000` characters by `fit_to_budget` (`:870-890`, sheds `_TRIMS` in order, never the beats), inside an inert boundary |
| Answer shape | `EpisodeVerdict` (`review.py:152-185`): `verdict` "PASS"/"FAIL", `reasons` ≤ 8, `notes` ≤ 1200, `story` ≤ 400, `scores` (only rubric keys, numeric). Parsed with `parse_structured` (fit-then-validate) |
| What code does with it | CHECKED_BY_CODE for a PASS; a FAIL is acted on as given (FINAL in that direction). `_held_to_her_rubric` (`:893-925`): a PASS missing any of the six scores or with a score outside 1–5 raises `ReviewError` (no verdict stored; the draft is read again on a later run); a PASS with any score < `RUBRIC_FLOOR = 3` becomes FAIL with the low parts as reasons. A FAIL (hers, or a PASS turned FAIL) is stored REJECTED with her notes and a HANDOFF letter to the ScriptWriter (`:1065-1091`); nothing in code can overturn it. A PASS approves only when `approve=True` and the Owner's policy flag allows it (`:1031-1033`, `_approve` `:928-943` advances canon); with `approve=False` (the stage's path) it is held for the editorial judgement (`:1049`). The review, checks, scores and run id are stored on `review_json` (`:1035-1050`) and an AGENT_OPINION memory is written (`:1094-1104`) |
| If the model fails | Non-SUCCEEDED run (provider fault, budget refusal) or no parsable object → `ReviewError` (`:1020-1023`); no registry/model → `ReviewError` (`:1025-1026`). The stage records "could not be read" and the DRAFT stays unreviewed for the next run (`serial_stage.py:432-435`). Inside the editorial loop a rewrite she cannot read is retired REJECTED and scored only for the record (`review.py:1323-1336`). The HTTP route answers 409 (`router.py:156-157`). A Director with no model assigned makes `run_agent_task` raise `ValueError` (`agents/services.py:815`), which neither the stage nor the route catches |
| Can it lead to money | Yes. Model tokens for the call; a PASS that is approved under policy leads to a storyboard and a queued GPU filming task. A FAIL's HANDOFF letter is an asking intent (`agents/mail.py:79`) that a later mail round answers with a ScriptWriter model call (`agents/mail.py:489-491`), outside this group |

### Functions that reach a model indirectly

| Function | Path to the model | Notes |
|---|---|---|
| `app.story.review.judged_review` (`review.py:1257`) | `review_episode` (call site 2); `write_episode` (call site 1) for each rewrite; and `app.agents.editorial_judgement.editorial_loop` → `judge` → `structured_run` (`agents/editorial_judgement.py:442-456`, task `editorial_judgement`, template `editorial-judgement-v1`, max_tokens 2000, temperature 0.2) | Static analysis counted 2 hops via the two in-scope sites; the editorial judge is a third model path. Up to `rounds` judge readings (each ≤ 2 attempts in `structured_run`) and `rounds − 1` rewrites (each ≤ 2 writer asks + 1 Director reading) per PASS |
| `app.story.router.create_story_router.post_write` (`router.py:112`) | `write_episode` | Owner HTTP route |
| `app.story.router.create_story_router.post_review` (`router.py:142`) | `review_episode` with the default `approve=True` | Owner HTTP route; skips the editorial judgement (see Oddities) |
| `app.story.router.create_story_router.post_storyboard` (`router.py:160`) | `media.serial_storyboard.storyboard_from_episode` → `media.prompt_agent.write_shot_prompts` | Static path only: `storyboard_from_episode` passes `registry=None` (`media/serial_storyboard.py:362`), so no model is called on this route |
| `app.story.router.create_story_router.post_decide` (`router.py:175`) | same as `post_storyboard` | Same: no model is actually called |
| `app.story.serial_stage._ready_for_filming` (`serial_stage.py:276`) / `ready_for_filming` (`:300`) | `media.serial_storyboard.describe_serial_shots` → `write_shot_prompts(registry)` → `media.prompt_agent._run` (the `VideoEditor`'s model, `media/prompt_agent.py:76`) | Once per series-look version; skipped when no model is registered (`media/serial_storyboard.py:375-410`). Every caller in `serial_stage` passes the registry; the only other caller, the watchdog pass `serial_unfilmed`, calls `ready_for_filming` without one (`workflows/passes/serial_unfilmed.py:127-129`), so that path never reaches a model |
| `app.story.serial_stage._tell_the_day` (`serial_stage.py:345`) | `write_episode`, `judged_review`, `_ready_for_filming` | The day's writer/review/judgement/storyboard sequence |
| `app.story.serial_stage.run_serial_stage` (`serial_stage.py:542`) / `run_serial_next_stage` (`:714`) | `_tell_the_day`, `_ready_for_filming` | Runbook stages `serial_queue` and `serial_next` (`runbook/stages.py:6188`, `:6197`) |

### Model influence the static analysis cannot see

| Path | What happens | Where |
|---|---|---|
| The editorial judge | `judged_review` → `editorial_loop` → `judge` → `structured_run`: a third model call (the Director, task `editorial_judgement`) reached through another module; listed in the table above | `story/review.py:1343-1351`, `agents/editorial_judgement.py:410-463` |
| A rewrite callback | `editorial_loop` calls back into `judged_review`'s nested `rewrite`, which runs `write_episode` and `review_episode` again (call sites 1 and 2) | `story/review.py:1296-1341`, `agents/editorial_judgement.py:709` |
| The HANDOFF letter after a FAIL | `review_episode` posts a HANDOFF to the ScriptWriter; HANDOFF is an asking intent, so a later mail round makes the ScriptWriter answer it through `structured_run` (a model call, tokens under the same gates). The stage's own rewrite already carries the same notes | `story/review.py:1078-1091`, `agents/mail.py:79`, `:489-491` |
| Memory writes | `review_episode` writes an AGENT_OPINION memory for the Director and `decide_episode` an OWNER_POLICY memory for the ScriptWriter; memories are composed into those agents' later system prompts (`compose_identity` inside `run_agent_task`) | `story/review.py:1094-1104`, `story/services.py:1838-1850`, `agents/services.py:790` |
| The Director's brief to the writer | The editorial judge's `brief` (keep/change/avoid, ≤ 600 chars) is passed as `notes` into the next `write_episode` prompt: one model's text steering another's | `agents/editorial_judgement.py:469-507`, `story/services.py:1214-1223` |
| Picture lessons | The lessons the showrunner is told to follow as rules are text from the Director's model answers, stored as `memory_record` rows by other modules: the first sentence of her editorial review's note to the VideoEditor, recorded whatever her verdict on the film (scoped to the film's kind, unverified, `agents/editorial.py:403-417`, `:575-590`), the lessons of the REAL or ACCEPTED verdicts of her QC decisions (`media/director_qc.py:1609-1643`, stored with the defaults: scope "all", not unverified), and the rewrite review's lesson (`media/scene_rewrite.py:1791-1820`, scoped to the film's kind, unverified). Code checks a lesson only when it is recorded (not empty, ≤ 400 characters, no film title, scene number or record id, `media/prompt_agent.py:3376-3426`) and then chooses which to give by scope, recency and overlap. Whether an unverified lesson is promoted to confirmed (and so given first) or withdrawn follows quality control's later reading of the picture made from the rewrite: every finding reported gone on an approved take confirms it, a finding that persists withdraws it (`media/fix_check.py:536-571`, called from `media/stills_stage.py:1104-1107`, `:1154-1159` and `fix_check.py:786-793`) | `story/services.py:1530-1555`, `media/prompt_agent.py:3319-3351`, `:3429-3492` |

No vision, ensemble or `run_with_strategy` call exists in this group.

### Code in this group that checks other modules' model answers

The Publisher's metadata for a film is a model answer written in `app.agents.reviews.prepare_publication`
(`backend/app/agents/reviews.py:1485`, call through `reviews._run`). This group supplies the deterministic parts around
it: `episode_identity` (series facts from the episode row), `series_title` (forces `<hook> | Inside The Nexus Ep. N`),
`fallback_metadata` (the studio's own deterministic title/description/tags used when the Publisher's answer is
refused), and `publication_metadata_refusals` (the computed copy/relevance check). `publication_metadata_refusals` is
run again inside `create_publication_intent` (`publishing/services.py:1666-1679`), "the one road every upload takes",
so a lifted HOLD cannot push a refused title through.

### How much is model, how much is rule

- Story: the model writes the episode text and the Director gives a content verdict and an editorial score. Everything
  that decides *whether* anything happens — which day, which events are visible, who may speak, whether an answer is
  stored, whether it is filmable, length, structure, privacy, grounding, the rubric floor, the editorial bar, the
  draft budgets, when canon moves, approval permission, filming — is code or the Owner. Three model answers are acted
  on without a content check: a Director FAIL (rejects the draft and briefs the rewrite), the Director's editorial
  scores (they rank the eligible versions and so choose which one ships), and the writer's thread/recurring/summary
  declarations, which become canon on approval after only id, placeholder and privacy checks. The writer's
  `plan_kept` is recorded as given. The Director's picture lessons (her model text, recorded by other modules)
  reach the writer's brief as rules: code refused some when they were stored (length, a film, scene or id named) and
  chooses which to give, but never checks what they ask for. None of these can make an episode
  public or spend GPU money by itself: approval still needs the Owner's flag or click, and filming the Owner's
  environment and money rules.
- Publishing: no model call at all in `app.publishing.*`. Channel routing, visibility, the 7-check gate, the metadata
  check, the upload state machine, reconciliation, licence release and every letter are code, Owner policy or the
  external platform's answer.
- Counts (inventory): 2 call sites, 10 indirect, 246 of 258 functions with no static path to a model; the
  publishing package (106 functions) has none.

## Hard rules and limits

### Story — writing (`backend/app/story/services.py`)

| Constant / rule | Value | Where |
|---|---|---|
| `MAX_BEATS` | 8 | `:83` |
| `MIN_BEATS` | 6 = max(5 parts, ceil(115/22)) | `:113` |
| `EPISODE_PARTS` | hook, situation, turn, payoff, button | `:95` |
| `SPEAKING_CAST` | 2–4 speakers | `:98` |
| `OFFERED_SPEAKERS` | 3 | `:103` |
| `WORDS_PER_BEAT` | 8–22 spoken words | `:106` |
| `EPISODE_WORDS` | 115–170 spoken words | `:109` |
| `MAX_NOTABLE_EVENTS` | 40 (operational record) | `:115` |
| `CLOSE_WINDOW_DAYS` | 7 | `:120` |
| `CONTINUITY_SUMMARIES` | 3 | `:123` |
| `EPISODE_TEMPLATE_VERSION` | "episode-v7" | `:92` |
| `_REJECTED_CHARS` | 8000 characters of a refused draft shown to the rewrite | `:1007` |
| Writer call | max_tokens 7200, temperature 0.7 | `:1685-1686` |
| Asks per `write_episode` | 1, plus 1 if the review's checks fail | `:1735-1761` |
| Picture lessons in the brief | up to `LESSONS_GIVEN = 12`, of scope "serial" or "all", confirmed first; read once per `write_episode` | `:1545`, `:1650`, `media/prompt_agent.py:126`, `:3338`, `:3348-3351` |
| `_PICTURE_LESSONS_CHARS` | 6000 characters of JSON, passed to `fit_with_lessons`, which does not apply it to the lessons (Oddity 29) | `:1527`, `:1549` |
| Canon caps | 12 open threads (the first 12 kept, so a newly opened 13th is dropped), 12 recurring (newest kept), thread text 300, recurring item 120, summary 600 | `:630-666` |
| Schema caps | line text 600, direction 200, scene 5–800, lines 1–16, event_ids 1–10, background 12, title 3–200, summary 600, logline 300, premise 400 | `:205-325` |

### Story — projection (`backend/app/story/projection.py`)

| Constant / rule | Value | Where |
|---|---|---|
| `PUBLIC_SAFE_EVENTS` | 39 event types, each with its safe payload keys; anything else OWNER_PRIVATE | `:61-105`, `:257-259` |
| `MAX_STORY_EVENTS` / `MIN_STORY_EVENTS` | 15 / 8 | `:492-493` |
| `_VALUE_CHARS` | 160 per quoted value | `:128` |
| Redaction | `_SECRET`, `_URL`, `_EMAIL`, `_DOMAIN`, `_MONEY`, `_MONEY_FIRST`, `_PROVIDER`, `_MODEL_FAMILY`, `_MODEL_SHAPE`, `_OPAQUE`, `_OPAQUE_UPPER`, `_HEX`, `_CARD` + model names from `model_record`/`model_outcome` (≥ 3 chars) | `:136-201`, `:232-251` |
| Weights | `STORY_WEIGHTS` 2–10; a trouble verdict (FAIL, REJECTED, REFUTED, …) weighs ≥ 9; routine = 1 | `:498-559` |

### Story — review (`backend/app/story/review.py`)

| Constant / rule | Value | Where |
|---|---|---|
| `RUBRIC` / `RUBRIC_FLOOR` | hook, situation, turn, payoff, voices, button / 3 | `:115-118` |
| `FACTS_BUDGET` | 14000 characters | `:123` |
| Spoken length | 45–70 s at 2.5 words/s, ≤ 8 beats | `:125-127`, `:655-669` |
| Accessibility | first beat names someone, scene ≥ 3 words, opening not a continuation marker | `:130-145`, `:674-683` |
| Concentration | no event cited in more than half the beats unless the projection has exactly one event | `:445-482` |
| Filmable | each beat's clip estimate ≤ model's longest clip × (1 + `SLOWDOWN_ALLOWANCE`) | `:342-442` |
| Director call | max_tokens 3000, temperature 0.1 | `:1010-1011` |
| Editorial bar (other module) | total ≥ 35/50, every criterion ≥ 5; text budget 12000; brief ≤ 600 chars | `agents/editorial_judgement.py:86-94` |
| Editorial rounds | `Settings.editorial_rounds` default 10, 1–20 | `config.py:15`, `config.py:434` |

### Story — the stage (`backend/app/story/serial_stage.py`)

| Constant / rule | Value | Where |
|---|---|---|
| `MAX_DRAFTS` | 2 per run (a draft and one rewrite; a refused answer counts) | `:53` |
| `MAX_DRAFTS_PER_DAY` | 3 stored drafts per day across runs | `:59` |
| `RESUME_WINDOW_DAYS` | 7 | `:62` |
| Continuation key | `film-continue-{storyboard_id}-serial_approved` | `:75-82` |
| FILM_CONTINUE task | priority 4, `max_attempts=1`, PRODUCTION only | `app/services.py:659-677` |
| One action per run | resume one unfinished item, else tell one day | `:563-705` |

### Publishing (`backend/app/publishing/*.py`)

| Constant / rule | Value | Where |
|---|---|---|
| `QC_MINIMUM_SCORE` | 0.90 | `services.py:166` |
| `PRIVACY_LEVELS` | private < unlisted < public | `services.py:113-114` |
| `DEFAULT_SHORTS_MAX_SECONDS` / limit | 60 / 180; seeded 60 (Channel A), 70 (Channel B) | `services.py:123-124`, `:143`, `:154` |
| `MAX_SOURCES` | 5 source addresses under a factual film | `services.py:675` |
| `METADATA_COPY_WINDOW` | 24 hours | `services.py:1417` |
| Meaningful-word test | words ≥ 3 letters minus fillers; shared 5-letter stem counts | `services.py:1422-1447` |
| `LIVE_PUBLICATION_STATES` | PUBLISHED, PUBLISHED_SIMULATED, REMOTE_CONFIRMED, REMOTE_UNKNOWN, STARTED, SCHEDULED | `services.py:170-177` |
| `RUNNABLE_STATES` | VALIDATED, FAILED_RETRYABLE | `services.py:1747` |
| `REMOTE_REJECTED_STATES` | rejected, failed, deleted | `services.py:1752` |
| `RESOLVABLE_STATES` | NEEDS_RECONCILIATION, REMOTE_UNKNOWN | `services.py:2734` |
| Video id shape | `^[A-Za-z0-9_-]{6,20}$` | `services.py:2735`, `router.py:73-75` |
| Publish policy command | delay 0–43200 min; category 1–3 digits; language BCP-47-ish ≤ 20; shorts 15–180 s | `schemas.py:84-105` |
| Scheduled release | must be `privacy_status="private"` | `schemas.py:128-137` |
| Licence release | `PER_PASS = 20`; back-off 15 min × 2^(n−1) capped at 1440 min; only uploads created on/after `HELD_SINCE = "2026-10-10"` unless marked | `licence_release.py:84-90` |
| Series title | `<hook> \| Inside The Nexus Ep. N`, ≤ 100 chars, hook cut at a word | `serial_identity.py:36-80` |
| Series tags | series name first, ≤ 15, unique | `serial_identity.py:110-116` |

### State machines

**StoryEpisode** (`story/models.py:82`): `DRAFT` → `APPROVED` (Owner `decide_episode` `services.py:1824`; Director
under policy `review.py:931`) | `REJECTED` (Owner; Director FAIL `review.py:1066`; retired by the editorial loop
`review.py:1137`). A DRAFT carries `review_json.held_for_judgement` while a PASS waits for the judgement
(`review.py:1049`). Nothing returns an APPROVED or REJECTED episode to DRAFT.

**Plan for the next episode** (`continuity_json.next_episode.status`): `PLANNED` (`services.py:1713`) → `KEPT` /
`DROPPED` / `UNSAID` when the next episode is approved (`services.py:1360-1362`).

**ContinuityState** (`story/models.py:107`): one row, `version` and `canon_episode_number` +1 per approved episode
(`services.py:663-667`).

**PublicationRecord** (`publishing/models.py:125-127`):

| From | To | Where |
|---|---|---|
| (new) | VALIDATED / BLOCKED_GATE | `services.py:1687` |
| VALIDATED, FAILED_RETRYABLE | BLOCKED_GATE (gate again at execution) | `services.py:2127-2128`, `:2012-2042` |
| VALIDATED, FAILED_RETRYABLE | STARTED | `services.py:2160` |
| STARTED (retry) | PUBLISHED / PUBLISHED_SIMULATED (found by reconcile) or FAILED_RETRYABLE (no answer) | `services.py:2190-2266` |
| STARTED | PUBLISHED / PUBLISHED_SIMULATED / REMOTE_UNKNOWN / FAILED_RETRYABLE / FAILED_FINAL | `services.py:2294-2374` |
| STARTED (exception) | FAILED_RETRYABLE / FAILED_FINAL | `services.py:2045-2075` |
| STARTED (stale) | REMOTE_UNKNOWN | `services.py:2640-2670` |
| any row with a video id (the watchdog sends REMOTE_UNKNOWN with an id here, REMOTE_UNKNOWN without one to `reconcile_by_title`, and FAILED_RETRYABLE to `execute_publication`'s retry, `workflows/watchdog.py:388-394`; `reconcile_publication` itself does not check the status) | PUBLISHED / PUBLISHED_SIMULATED (exists), FAILED_FINAL (rejected/failed/deleted), FAILED_RETRYABLE (not found), REMOTE_UNKNOWN (no answer) | `services.py:2418-2512` |
| (no video id) | PUBLISHED / FAILED_RETRYABLE / unchanged | `services.py:2515-2619` |
| PUBLISHED | FAILED_FINAL (rejected/failed/deleted) | `services.py:2673-2707` |
| any | NEEDS_RECONCILIATION | `services.py:2710-2730` |
| NEEDS_RECONCILIATION / REMOTE_UNKNOWN | PUBLISHED / FAILED_RETRYABLE (Owner) | `services.py:2738-2808` |
| PUBLISHED private (held for licence) | privacy_status public (status stays PUBLISHED, whatever YouTube says) | `licence_release.py:427-428` |
| PUBLISHED private (held for licence), YouTube answers "not there" | FAILED_FINAL (deleted) + letter | `licence_release.py:421-425` |

## Modules

### `app.story` — `backend/app/story/__init__.py` (5 lines)

Package docstring only. It re-exports nothing so that `app/models.py` can import `app.story.models` to register tables
without pulling in the service layer and closing an import cycle (`__init__.py:3-4`).

### `app.story.models` — `backend/app/story/models.py` (133 lines)

The three tables of Phase 9, separating the two truth layers (`models.py:1-14`). No functions.

| Class | Line | What it is | Why |
|---|---|---|---|
| `DailyStudioLog` | 24 | One business date: `event_counts_json`, `total_events`, `roster_json` (who was employed), `notable_events_json` (operational record, raw), `narrative_projection_json` (PUBLIC_SAFE, nullable, migration 0036), `status`, `closed_at`; unique per `business_date` | The record an episode is checked against; "No model writes any part of this" (`:27-28`) |
| `StoryEpisode` | 60 | `title`, `beats_json`, `grounded_event_ids_json`, `continuity_json`, `status` DRAFT/APPROVED/REJECTED, `written_by_agent_id`, `notes`, `reviewed_by` ("director"/"owner"), `review_json`, `storyboard_id`, `rewrite_of_id` | A dramatisation that references events rather than modifying them |
| `ContinuityState` | 107 | Single row: `canon_episode_number`, `threads_json`, `recurring_json`, `summaries_json` (last 3), `version` | The serial's memory, advanced only on approval; never inferred from the newest row, which may be a rejected draft (`:110-114`) |

### `app.story.locations` — `backend/app/story/locations.py` (81 lines)

Where a scene may happen: the studio's own rooms. Measured 2026-09-24: beats were set in rooms that do not exist and
every still drew a different office (`locations.py:3-8`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `studio_locations` | 31 | Rooms from `office.services.DEFAULT_OFFICE_LAYOUT` zones (with the roster members whose desk role matches) plus every `Room` row, as `{id, name, where, who}` | So the brief and the review share one list of real rooms | CODE_RULE / CONFIG (layout constant) |
| `location_id` | 64 | Map a model's written location (id, name or slug) to a room id; None when no room | Structure check and storage normalisation | CODE_RULE |
| `location_name` | 75 | The room's name and floor for the storyboard | Storyboard text | CODE_RULE |

Helpers: `_slug`, `_floor` — slug and floor wording. Reads `room` table; writes nothing.

### `app.story.lines` — `backend/app/story/lines.py` (199 lines)

Who says what: normalises names written by a model to the roster's display names and separates spoken words from stage
directions, because a voice reads every character of `text` (`lines.py:3-18`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `NameBook` (class) / `__init__` / `canonical` | 49 / 58 / 92 | Every unambiguous way to write a roster member (display name, base name, words ≥ 3 letters not titles, bracketed role, role name, bible canonical name and first word) → display name; a key two members share maps to nobody; display names always win | A short name ("Sarah") refused whole days; guessing between two Annas would misplace a person | CODE_RULE |
| `split_direction` | 100 | Take `(sighs)`, `[quietly]`, `*laughs*` out of spoken text | So directions are not voiced or captioned | CODE_RULE |
| `split_label` | 111 | Take a leading "Name:" off; with a `NameBook`, only a known name | Labels were read aloud | CODE_RULE |
| `clean_line` | 130 | One stored line `{speaker, text, direction?}`; None when nothing is left to say | Storage form | CODE_RULE |
| `beat_lines` | 149 | Lines of a v3 beat, or a v2 beat's `dialogue` parsed into lines (unknown labels → narrator) | Old episodes still filmable | CODE_RULE |
| `spoken_text` | 169 | Joined spoken words only | Word counts, storyboard narration | CODE_RULE |
| `speakers_of` | 174 | Speakers in first-speaking order | Cast check | CODE_RULE |
| `participants` | 184 | Roster names acting in one projected event (actor + names in the public line) | Who "acts" in an event for the cast rule | CODE_RULE |

Helpers: `_key` (case/space folding), `_base` (strip bracketed role). No I/O.

### `app.story.projection` — `backend/app/story/projection.py` (604 lines)

The PUBLIC_SAFE narrative projection (07_STORY_ENGINE "Narrative safety / sanitization"). Two "deliberately dumb"
mechanisms: a table of event types (private by default) and a redaction pass (`projection.py:10-21`), plus a computed
story selection — "no model decides what the day was about" (`:27-32`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `redact` | 213 | Replace secrets, URLs, emails, domains, prices, provider/model names and shapes, opaque tokens, hex, card-like numbers, and the studio's own model names with `[redacted]` | "Over-redaction is the accepted cost" (`:216-217`) | CODE_RULE |
| `leaks` | 227 | Whether `redact` would change a text | The review's privacy check | CODE_RULE |
| `private_model_names` | 232 | Every model name in `model_record` and `model_outcome` (and the stem before ":") | A new model under a plain word has no recognisable shape | CODE_RULE |
| `classify_event_type` | 257 | PUBLIC_SAFE if in the table, else OWNER_PRIVATE | Private by default | CODE_RULE |
| `is_stage_report` | 269 | An end-of-run stage report letter to the Director's desk | They weighed 8 and crowded out the day's story (2026-09-24) | CODE_RULE |
| `describe_public` | 326 | One English sentence for a public event; Owner letters reduced to "X wrote to the Owner"; refuted claims quoted | The only text the showrunner reads | CODE_RULE |
| `project_events` | 390 | The projection of a list of events with actor names (never ids), story keys, routine flag | Projection | CODE_RULE |
| `refuted_claims` | 441 | claim id → text for REFUTED verifications | A refuted claim is the one claim text a public line may carry | CODE_RULE |
| `project_day` | 460 | `project_events` with DB-only inputs | Close-time projection | CODE_RULE |
| `project_log_for_story` | 469 | Re-read a closed log's events and project them | Backfill of logs closed before 0036 | CODE_RULE |
| `story_weight` | 553 | Weight of one event (trouble ≥ 9, routine 1) | Story selection | CODE_RULE |
| `select_story` | 562 | Collapse repeats, rank by weight, keep ≤ 15, fill to 8 with routine, return in time order; nothing when no story line | The day's story, not its tail | CODE_RULE |
| `left_out` | 600 | Public events not shown | Told to the writer ("do not invent what they were") | CODE_RULE |

Helpers: `_names_pattern` (cached regex of model names), `_is_owner_letter`, `_value` (first list item, 160 chars),
`_story_keys` (title/reason/verdict/claim, redacted), `_actor`. Reads `domain_event`, `factual_claim`,
`model_record`, `model_outcome`; writes nothing.

### `app.story.services` — `backend/app/story/services.py` (1882 lines)

Closing the day, continuity, the cast from the bibles, and writing the episode (`services.py:1-30`). Contains call site
1.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `StoryError` / `DraftRefused` / `EpisodeNotGrounded` / `NothingHappened` | 154 / 158 / 172 / 180 | Exceptions: no episode; answer refused before storage (carries the answer); citation outside the day; quiet day | A refusal is a content result, not a fault (`:159-165`); "Manufacturing a story from an empty log would be exactly the fabrication the spec forbids" (`:183-185`) | — |
| `_Line`, `_Beat`, `_NextEpisode`, `_Episode` (pydantic) | 200, 226, 274, 296 | The writer's answer schema with clipping validators and v2→v3 conversion | Schema validation of the model answer | CODE_RULE |
| `business_date` | 335 | Today in the studio's timezone | Day boundaries are the studio's | CONFIG (`Settings.timezone`) |
| `close_daily_log` | 394 | Count a date's events, build roster (non-TERMINATED agents), `_notable` record, projection (`select_story(project_day)`), emit `story.daily_log_closed`, store CLOSED; return existing unchanged | "letting it drift after the fact would let an episode become grounded retroactively" (`:399-401`) | CODE_RULE |
| `close_previous_day` | 474 | Close yesterday | Measured: the log was frozen in the morning of its own date and covered 92 events (`:477-482`) | CODE_RULE |
| `close_missing_days` | 487 | Close every missing date of the last 7 days, never before the first event | Days between runs were never closed (`:116-119`) | CODE_RULE |
| `list_daily_logs` / `get_daily_log` | 531 / 541 | Read logs | API | — |
| `ensure_projection` | 547 | Fill a NULL projection once from the same events | "the one write a closed log ever receives" (`:551-552`) | CODE_RULE |
| `get_continuity` | 593 | The canon row (number 0 when none) | API | — |
| `advance_continuity` | 614 | On approval: judge the plan handed to this episode, number +1, close/open threads, add recurring, keep last 3 summaries, emit `story.continuity_advanced`; idempotent by episode id | "an Owner's approval and a Director's cannot both count the same episode" (`:617-618`) | CODE_RULE |
| `bibles_for_roster` | 677 | Display name → `CharacterBible` by employee id, else first-word match | "A member with no bible has no line … never invents a look" (`:681-682`) | CODE_RULE |
| `acting_cast` | 760 | Roster members acting in the projection | Full bibles only for them (brief v4) | CODE_RULE |
| `speakers_to_offer` | 771 | Top 3 by story weight; fill from ACTIVE roster when < 2 | Brief v7 steering | CODE_RULE |
| `voice_of` | 799 | A bible's voice fields as data | The Director judges voices against what the writer was told | CODE_RULE |
| `list_episodes` / `get_episode` | 848 / 856 | Read episodes | API | — |
| `write_episode` | 1558 | **LLM call site 1** (see above): brief (with the serial's picture lessons), ask, read, measure, ask once more, store DRAFT with `story.episode_drafted` | The serial's writing step | LLM_CHECKED_BY_CODE |
| `decide_episode` | 1813 | Owner approves/rejects a DRAFT: status, notes, `reviewed_by="owner"`, event, canon on approval, OWNER_POLICY memory for the ScriptWriter | "The Owner accepts or rejects a dramatisation of their own studio" (`:1816`) | OWNER |
| `grounding_report` | 1855 | Re-check a stored episode's citations against the projection (or the notable events of a pre-projection log) | "so the claim can be audited, not trusted" (`:1856`) | CODE_RULE |

Private functions of 25+ lines or that decide something:

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `_notable` | 367 | Operational record: narratable types, heaviest 40 when more | CODE_RULE |
| `_who_they_are` | 702 | Full bible text (looks, speech, habits, traits, humour, conflict style, phrases) for the brief | CODE_RULE |
| `_events_block` | 1076 | Events as JSON lines in an inert boundary, with "N more not listed" and "recorded until HH:MM" notes | CODE_RULE |
| `_parse_episode` | 1130 | JSON extraction and schema validation; `DraftRefused` on failure | CODE_RULE |
| `_previously` | 1155 | Canon as data (summaries, open threads, recurring) | CODE_RULE |
| `_rewrite_section` | 1197 | Rewrite instructions: refused-answer, judged (editorial brief: keep what it keeps), Director-refused, or notes only | CODE_RULE |
| `_plan_for` / `_plan_block` | 1255 / 1278 | The newest canon episode's PLANNED plan, as data | CODE_RULE |
| `_next_episode_plan` | 1296 | Validate the new plan (required, complete, not copied, threads stay open) | CODE_RULE |
| `_judge_the_plan` | 1347 | Mark the earlier plan KEPT/DROPPED/UNSAID | LLM (writer's word recorded) |
| `_episode_from_answer` | 1366 | All write-time refusals (see call site 1) | CODE_RULE |
| `_measured_refusals` | 1485 | Run `review.draft_checks` on the unsaved draft; ignore `offered_speakers` | CODE_RULE |
| `_picture_lessons` | 1530 | The serial's picture lessons (`prompt_agent.prompt_lessons(scope="serial")`, which adds the "all" ones) under a PICTURE LESSONS heading, with `lessons_rule` and the lessons as JSON in an inert boundary (`_inert`); "" when there are none | CODE_RULE (selection; lesson text written by the Director's model elsewhere) |

Helpers: `_names`, `_text_or_empty`, `_kept_or_unsaid`, `_day_bounds`, `_describe`, `_public_log`, `_continuity_row`,
`_public_continuity`, `_next_thread_id`, `_texts`, `_in_one_line`, `_public_episode`, `_given`, `_placeholder`,
`_inert`, `_local_moment`, `_local_time`, `_locations_block`, `_resolve_showrunner`, `_rejected_draft`,
`_open_thread_ids` — formatting, parsing and small validations; the schema validators `_Line._as_written` (a line
written as "Name: words" split into speaker and text) and `_Beat._dialogue_as_lines` (a v2 `dialogue` turned into
lines); `DraftRefused.__init__` (keeps the refused answer).

Data: reads `domain_event`, `agent`, `role`, `character_bible`, `room`, `daily_studio_log`, `story_episode`,
`continuity_state`, `memory_record` (picture lessons, via `prompt_agent.prompt_lessons`); writes `daily_studio_log`,
`story_episode`, `continuity_state`, `memory_record` (via `remember`).
Events: `story.daily_log_closed`, `story.episode_drafted`, `story.episode_approved`, `story.episode_rejected`,
`story.continuity_advanced`. External calls: model provider through `run_agent_task` only.

### `app.story.review` — `backend/app/story/review.py` (1387 lines)

The gate between the showrunner and the camera: computed checks, the Director's verdict, then the editorial judgement
(`review.py:1-54`). Contains call site 2.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `ReviewError` / `EpisodeVerdict` | 148 / 152 | No verdict; the Director's answer schema (rubric-only scores) | — | — |
| `director_may_approve_episodes` | 221 | Read the OFFICE_SERIAL channel's flag | The Owner's grant; "Nothing here writes it" (`:228-229`) | OWNER |
| `motion_clip_limit` | 342 | The serial's motion model (production policy for `office_serial`) and its longest clip (contract, price table or `max_seconds`) × (1 + `SLOWDOWN_ALLOWANCE`); None when unknown | A beat longer than a clip was refused at assembly after stills, clip and voice were bought (2026-10-10, `:417-419`) | CODE_RULE / CONFIG (production policy, provider metadata) |
| `beat_clip_seconds` | 389 | Seconds one beat's lines need, sized as the motion plan sizes an estimated narration | Filmable check | CODE_RULE |
| `episode_checks` | 522 | The ten computed checks (grounding, privacy incl. canon text, length, words per beat, concentration, cast, structure, accessibility, language when "en", filmable when a limit exists); v2 episodes judged by the old rules | "they are not matters of taste" (`:8`); "A check certifies only what it measured" (`:26-27`) | CODE_RULE |
| `draft_checks` | 697 | `episode_checks` + `offered_speakers` | The writer's measure and the Director's can never disagree | CODE_RULE |
| `review_facts` | 727 | The Director's facts: beats with cited events' public words and actors, voices, canon, measured checks | v1 judged "is this grounded" without the events (`:732-734`) | CODE_RULE |
| `fit_to_budget` | 870 | JSON within 14000 chars, shedding `_TRIMS` in order; never cuts beats; marks `trimmed`/`over_budget` | v1 cut JSON mid-way and dropped last beats (`:119-122`) | CODE_RULE |
| `review_episode` | 946 | **LLM call site 2** (see above) | The Director's reading | LLM_CHECKED_BY_CODE |
| `retire_episode` | 1151 | Retire a DRAFT as REJECTED with a note | Otherwise a second episode for one day would claim the canon number (`:1159-1163`) | CODE_RULE |
| `approve_reviewed_episode` | 1171 | Approve a held PASS under the policy; else leave it DRAFT for the Owner | The approval step after the judgement | OWNER (policy) via CODE_RULE |
| `episode_as_text` | 1204 | The episode as a viewer meets it (title, beats, «Name: words») + small context | The judgement reads "for the stranger" without ids or checks | CODE_RULE |
| `judged_review` | 1257 | `review_episode(approve=False)` → if PASS, `editorial_loop` with a rewrite closure (`write_episode(judged=True)` + `review_episode`); record rounds; retire non-shipped DRAFTs; letter to the Owner when shipped below the bar; `approve_reviewed_episode` on the shipped one | The Owner's card of 2026-10-11 23:30 | LLM_CHECKED_BY_CODE + OWNER (policy) |

Private functions that decide something:

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `_speaking_cast` | 240 | The Owner's cast rule (2026-09-24): 2–4 speakers, all acting in the cited events; when the cited events name fewer than two, those named must speak and the rest may be anyone on the roster | CODE_RULE |
| `_structure` | 275 | Every part known, all five present, in order, one hook first and one button last; every beat's location a studio room | CODE_RULE |
| `_words_per_beat` | 306 | 8–22 spoken words per beat for v3; a v2 episode is measured but not held; no beat fails | CODE_RULE |
| `_filmable` | 411 | Each beat's `beat_clip_seconds` ≤ the motion model's longest clip × 1.25 (`SLOWDOWN_ALLOWANCE = 0.25`, `media/cost_plan.py:74`) | CODE_RULE / CONFIG (model metadata) |
| `_concentration` | 445 | No event cited in more than half the beats unless the day has one event; every beat cites something | CODE_RULE |
| `_language` | 485 | Title and every line pass the Publisher's `looks_like_english` guard, line by line and over the whole | CODE_RULE |
| `_held_to_her_rubric` | 893 | The rubric check on the Director's PASS (see call site 2) | CODE_RULE on the LLM answer |
| `_approve` | 928 | APPROVED as the Director's, her `story` as the note, `story.episode_approved`, canon advanced | CODE_RULE (called only under the Owner's flag) |
| `_retire` | 1128 | A DRAFT retired as the Director's REJECTED with a note and `superseded_by` | CODE_RULE |
| `_version_of` | 1242 | A stored episode as an editorial `Version`, eligible only when her reading passed | CODE_RULE |

Helpers: `_words`, `_beat_numbers`, `_dumps`, `EpisodeVerdict._rubric_only` (keeps only rubric keys with numeric
scores; a non-number is left out, which a PASS then answers for as a missing score, `review.py:170-185`), and the
`_TRIMS` steps `_measured_verdicts_only`,
`_newest_summary_only`, `_voices_without_phrases`, `_short_scenes`, `_short_event_texts`, `_no_summaries`,
`_no_voices`.

Data: reads `story_episode`, `daily_studio_log`, `continuity_state`, `character_bible`, `channel_record`,
`provider_resource`, production policy; writes `story_episode.status/notes/reviewed_by/review_json`,
`continuity_state` (via `advance_continuity`), `memory_record`, `agent_message` (HANDOFF to the ScriptWriter; the
editorial STATUS letter to the Owner via `letter_to_owner`). Events: `story.episode_reviewed`,
`story.episode_approved`, `story.episode_rejected`, `story.continuity_advanced` (via `advance_continuity`),
`editorial.judged` (via `record_rounds`).

### `app.story.router` — `backend/app/story/router.py` (206 lines)

Owner-only HTTP routes under `/story` (`Depends(require_owner)`, `router.py:61`). Commands carry a `command_id`
(`:30-57`).

| Route | Function | Line | What it does | Decided by |
|---|---|---|---|---|
| `GET /story/logs` | `get_logs` | 64 | List logs | — |
| `POST /story/logs/close` | `post_close` | 68 | `close_daily_log` for a date (default today) | OWNER (trigger) / CODE_RULE |
| `POST /story/logs/close-previous` | `post_close_previous` | 83 | `close_previous_day` | OWNER (trigger) |
| `GET /story/continuity` | `get_continuity_state` | 90 | Canon | — |
| `GET /story/logs/{log_id}` | `get_log` | 95 | One log | — |
| `GET /story/episodes` | `get_episodes` | 105 | Episodes (optionally of one log) | — |
| `POST /story/episodes/write` | `post_write` | 112 | `write_episode`; 409 quiet day, 422 refused | OWNER (trigger), LLM |
| `GET /story/episodes/{id}/grounding` | `get_grounding` | 131 | `grounding_report` | CODE_RULE |
| `POST /story/episodes/{id}/review` | `post_review` | 142 | `review_episode` (approve=True) | OWNER (trigger), LLM_CHECKED_BY_CODE |
| `POST /story/episodes/{id}/storyboard` | `post_storyboard` | 160 | `storyboard_from_episode` (rows, no model) | OWNER (trigger) |
| `POST /story/episodes/{id}/decide` | `post_decide` | 175 | `decide_episode`; rejection needs notes; approval builds the storyboard at once (an error is returned, the approval stands) | OWNER |

`create_story_router` (`:60`) builds the router. External calls: none directly.

### `app.story.serial_stage` — `backend/app/story/serial_stage.py` (892 lines)

The serial's day as runbook stages: resume, project, write, review, judge, approve, storyboard, queue filming
(`serial_stage.py:1-16`). Content refusals are recorded in the outcome and never raised; only provider/network faults
are raised as `TransientStageError`.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `serial_continuation_key` | 75 | Idempotency key for the one FILM_CONTINUE per storyboard | The stage and the `serial_unfilmed` pass never queue twice | CODE_RULE |
| `day_to_tell` | 95 | Newest closed day before today, after the newest told day, within 7 days, with a non-empty projection; plus the quiet days passed | Yesterday was often empty while a real day sat unused (2026-09-24) | CODE_RULE |
| `day_to_retell` | 131 | A refused day with budget left (< 3 drafts, all REJECTED, after the newest APPROVED day), priority: newest told day, oldest untold, other refused newest-first; returns the last draft and notes | 16 drafts of 8 days, none approved (2026-10-10) | CODE_RULE |
| `pending_log` | 216 | `day_to_tell(...)[0]` | Kept from an earlier design (no caller in backend code) | CODE_RULE |
| `unfinished_episodes` | 235 | What earlier runs left: APPROVED without storyboard; DRAFT unread; DRAFT PASS waiting for the Owner — within 7 days | Approved episodes were never filmed; unreadable answers lost the day (2026-09-24) | CODE_RULE |
| `ready_for_filming` | 300 | `_ready_for_filming` for callers without a run card; its registry defaults to None | Used by the `serial_unfilmed` watchdog pass, which passes no registry, so shots keep the studio's composition there | CODE_RULE |
| `run_serial_stage` | 542 | Morning stage `serial_queue`: resume one unfinished item (ready storyboard / read the unread draft / approve a held PASS under policy / report waiting for the Owner), else tell a new day, else retell a refused day; SKIPPED without a model | One episode a day, filmed by the same run's media stage | CODE_RULE (+ LLM via `_tell_the_day`) |
| `run_serial_next_stage` | 714 | Evening stage `serial_next`: tell TODAY from its closed log; nothing when the log is not closed, today already told (unless all refused with budget left), or an earlier episode waits; readies and queues filming of an approved episode | The Owner's one click films an episode and writes the next (2026-09-24); queue filming the same evening (2026-10-11) | CODE_RULE (+ LLM) |

Private functions that decide something:

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `_transient` | 89 | `classify_fault(exc) == TRANSIENT` | CODE_RULE |
| `_ready_for_filming` | 276 | Build/get the storyboard; `describe_serial_shots` with the registry; False with the refusal | CODE_RULE (+ LLM in media) |
| `_queue_filming` | 310 | Under the write lock, `queue_film_continue` with the serial key and cause; queue fault logged, `None` | CODE_RULE / OWNER (environment) |
| `_tell_the_day` | 345 | The write → judged review → rewrite-on-FAIL loop with `MAX_DRAFTS` and `MAX_DRAFTS_PER_DAY`; approval check; storyboard; filming queue when no media stage follows | CODE_RULE (+ LLM) |
| `_left_by_earlier_runs` | 489 | `unfinished_episodes` read into plain dicts with draft counts and `held` | CODE_RULE |
| `_new_counts` | 515 | The run card's counters (projected, written, refused, reviewed, rewritten, approved, storyboard, shots described, FILM_CONTINUE task, resumed kind, told date, editorial record) | CODE_RULE (record only) |

Helpers: `_outcome`, `_last_told`, `_naming_the_day`, `_filming_words` — outcome/reason formatting
(Romanian card text). Data: reads `daily_studio_log`, `story_episode`; writes through the services above and
`task_queue_item` (`queue_film_continue`). Money: the FILM_CONTINUE task (GPU later).

### `app.publishing` — `backend/app/publishing/__init__.py` (1 line)

Docstring only.

### `app.publishing.models` — `backend/app/publishing/models.py` (155 lines)

| Class | Line | What it is | Why |
|---|---|---|---|
| `ChannelRecord` | 11 | A channel slot: identity (`remote_channel_id`, `credentials_ref` = `youtube_connection:<id>`), `status`, the versioned publish policy (`autonomous_privacy`, `public_publish_enabled`, `publish_delay_minutes`, `director_may_approve_episodes`, `youtube_category_id`, `made_for_kids`, `default_language`, `shorts_max_seconds`, `policy_version`, `policy_changed_event_id`), production policy (`production_policy`, `production_defaults_json`, `series_rules_json`, `allow_production_override`) | Visibility and the Director's episode approval are the Owner's versioned decisions (`:25-44`) |
| `ChannelBrandAsset` | 93 | Tagline/avatar/banner per channel | Brand assets |
| `PublicationRecord` | 109 | One upload attempt: metadata, `privacy_status`, `status`, `idempotency_key` (unique per channel), `remote_video_id/url`, `scheduled_publish_time`, `policy_version` (which policy authorised visibility), `remote_privacy_status/upload_status/checked_at` (what YouTube says, migration 0052), `error_detail` | Lifecycle record; "never what was asked for" for the remote fields (`:138-141`) |

### `app.publishing.schemas` — `backend/app/publishing/schemas.py` (178 lines)

Pydantic views and commands. `PublishPolicyCommand` (`:71`) is the Owner's versioned command ("never a setting a page
can flip or an agent can assume", `:75-78`), `extra="forbid"`, `expected_version` required. `CreatePublicationIntentCommand`
(`:115`) refuses a scheduled release that is not private (`_a_scheduled_release_is_a_private_upload`, `:128-137`,
CODE_RULE). `GateCheckItem` / `PublishingGateEvaluationView` (`:162`, `:171`) carry Romanian detail plus machine data and
reason codes. `ChannelView` (`:13`), `ConfigureChannelCommand` (`:61`), `PublishPolicyResult` (`:108`),
`PublicationView` (`:140`).

### `app.publishing.serial_identity` — `backend/app/publishing/serial_identity.py` (203 lines)

The serial's identity at publish: series, episode number, title, logline, previous episode (`serial_identity.py:1-21`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `series_suffix` | 55 | " \| Inside The Nexus Ep. N" | One series format | CODE_RULE |
| `hook_of` | 62 | A title without "Storyboard:" and the series marker at either end | The metadata guard judges the Publisher's own words | CODE_RULE |
| `series_title` | 71 | `<hook> \| Inside The Nexus Ep. N` within 100 chars, hook cut at a word | Forced title format around the Publisher's hook | CODE_RULE |
| `series_description` | 87 | Prepend the logline, append "Previously on … Ep. N" with a public link when one exists; ≤ 5000 | "episode metadata linking prior related episode" (07_STORY_ENGINE) | CODE_RULE |
| `series_tags` | 110 | Series name first, ≤ 15 unique | Identity | CODE_RULE |
| `logline_of` | 119 | Writer's logline, else first sentence of the summary, else the title | Description opening | CODE_RULE |
| `episode_identity` | 152 | For a script with `story_json.kind == "office_serial_episode"`: number, hook title, logline, previous APPROVED episode (number − 1) and its public URL | Facts the Publisher is given | CODE_RULE |
| `fallback_metadata` | 194 | Deterministic title/description/tags for an episode | Used when the Publisher's answer is refused by the guard | CODE_RULE |

Helpers: `_one_line`, `_folded`, `_public_url` (only a public/unlisted publication's URL). Reads `script_draft`,
`story_episode`, `video_render_job`, `publication_record`.

### `app.publishing.services` — `backend/app/publishing/services.py` (2863 lines)

Channels, the publish policy, routing, the description footer, the publishing gate, the episode-metadata check, the
upload state machine, reconciliation and the Owner's letters. No model calls.

**Channels and policy**

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `film_identity` | 180 | Asset → (script id, storyboard id) via its render job | "A file is not a film" (`:183`) | CODE_RULE |
| `published_films` | 201 | Live publications on a channel keyed by script and storyboard | Duplicate-film check | CODE_RULE |
| `file_sha256` | 226 | Block-wise SHA-256 | Gate 2 | CODE_RULE |
| `derive_channel_status` | 235 | NOT_CONFIGURED / AUTH_REQUIRED / CONFIGURED from present fields | "Never assume configuration" | CODE_RULE |
| `seed_default_channels` | 244 | Create the two slots with no remote identity; fill a NULL production policy once | "Inventing a remote_channel_id … would fabricate external state" (`:131-132`) | CODE_RULE / CONFIG (`DEFAULT_CHANNELS`) |
| `bound_connection_id` / `channel_bindings` | 304 / 312 | Which YouTube connection a slot is bound to; ready only when CONNECTED | A revoked grant is not a binding | CODE_RULE / EXTERNAL (connection status) |
| `policy_snapshot` | 337 | The policy fields as recorded | Ledger old/new | CODE_RULE |
| `change_publish_policy` | 352 | The Owner's publish-policy command (idempotent, versioned, refusals, NO_CHANGE, `publishing.channel_policy_changed`) | Decision `16_DECISION_LOG.md:1860` | OWNER (checked by CODE_RULE) |
| `resolve_publish_visibility` | 480 | Pure: what an autonomous upload may be, and why | Replaced a hardcoded "private" | CODE_RULE on OWNER policy + environment |
| `channel_type_for_storyboard` | 563 | Series key → slot type | Routing | CODE_RULE |
| `select_channel_for` | 569 | Route a film to its slot and bound account, or SKIPPED with the reason | Decision `16_DECISION_LOG.md:1872` | CODE_RULE |
| `list_channels` / `get_channel` / `configure_channel` | 794 / 804 / 812 | Read; configure name/identity/credentials ref/privacy default, status re-derived, `channel.configured` | API | OWNER |

**Description assembly**

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `studio_settings` | 688 | Cached `Settings()` for callers handed none | CONFIG |
| `disclosure_sentence` | 700 | The AI-disclosure line in the content language (Owner's sentence wins) | CONFIG |
| `channel_link` | 721 | A connected channel's public address (handle or id) | EXTERNAL (connection snapshot) |
| `publication_footer` | 738 | Disclosure + site + "Created by <channel>" with a link from a real connection | CONFIG |
| `with_footer` | 776 | Footer once at the end, replacing a known one, within 5000 bytes; text above is cut first | CODE_RULE |
| `film_attributions` / `with_attributions` | 849 / 861 | Music/ambience licence credits above the footer | CODE_RULE |
| `film_sources` / `sources_heading` / `with_sources` | 893 / 941 / 946 | Up to 5 source URLs of SUPPORTED claims for a MAIN_FACTUAL film (PUB-10) | CODE_RULE |
| `upload_language` / `upload_settings` | 956 / 963 | Category, made-for-kids, language from the channel policy (migration 0053) | OWNER (policy) / CONFIG |
| `film_title` | 973 | Fallback title from the script or storyboard (hook only) | CODE_RULE |

**Gate, metadata, intent**

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `evaluate_publishing_gate` | 984 | The 7 checks with Romanian detail, data and reason codes; `eligible` only when no reason | ADR-PHASE6-001; spec `50_CONTENT_GATE_MATRIX.md` "Before publish" | CODE_RULE |
| `publication_metadata_refusals` | 1488 | For an episode: no copy of another channel's film's title (or title+tags) in 24 h; title shares a meaningful word with the episode; unreadable episode refused | The 2026-09-18 rehearsal (`:1497-1501`) | CODE_RULE |
| `create_publication_intent` | 1589 | Add sources, attributions, disclosure; fit to YouTube limits; idempotency by (channel, key); asset/channel must exist; gate + metadata; commit VALIDATED or BLOCKED_GATE with its event, then raise on BLOCKED | "a gate refusal is an auditable governance decision" (`:1683-1685`) | CODE_RULE |
| `publish_media_asset` | 2811 | Footer, refuse without a provider (no simulator fallback), intent, execute | The daily run's one call | CODE_RULE |

Helpers: `_terms`, `_shares_a_term`, `_same_metadata_key`, `_episode_words`, `_configured_settings`, `_language`,
`_above_footer`, `_http_address`, `_rfc3339`.

**Upload, outcome, reconciliation, letters**

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `execute_publication` | 2092 | Gate again (PUB-04); under the write lock move VALIDATED/FAILED_RETRYABLE → STARTED with `publishing.started`; upload; any exception settled (PUB-01) | 47_STATE_MACHINE "Publication" | CODE_RULE |
| `tell_owner_about_publication` | 1852 | ESCALATE letter from the Publisher for FAILED_FINAL / REMOTE_UNKNOWN / NEEDS_RECONCILIATION, subject names film/channel/state | PUB-12 | CODE_RULE |
| `tell_owner_locked_private` | 1919 | Record + ESCALATE letter when YouTube kept private a film asked visible | PUB-05 (unaudited Google Cloud project) | EXTERNAL |
| `list_publications` / `get_publication` | 2401 / 2410 | Read | — | — |
| `reconcile_publication` | 2418 | Ask YouTube about a known video id: rejected/failed/deleted → FAILED_FINAL; exists → PUBLISHED; absent → FAILED_RETRYABLE; no answer → REMOTE_UNKNOWN | "Never re-upload from REMOTE_UNKNOWN without checking remote state" (`:2426-2427`) | EXTERNAL |
| `reconcile_by_title` | 2515 | Same with no video id, by exact title since creation on the bound channel | Uploads cut before YouTube named the video | EXTERNAL |
| `upload_started_at` | 2622 | Newest `publishing.started` time | Staleness | CODE_RULE |
| `mark_stale_started` | 2640 | STARTED older than the caller's threshold → REMOTE_UNKNOWN | A dead process left rows STARTED forever (PUB-01) | CODE_RULE |
| `check_processing` | 2673 | Read YouTube's processing once; rejected/failed/deleted → FAILED_FINAL; else record remote state | PUB-08 | EXTERNAL |
| `hand_to_owner` | 2710 | → NEEDS_RECONCILIATION + letter | The manual repair queue (PUB-12) | CODE_RULE → OWNER |
| `resolve_publication` | 2738 | The Owner's «Există» (id) → PUBLISHED / «Nu există» → FAILED_RETRYABLE; idempotent by command id | PUB-12 | OWNER |

Private functions that decide something:

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `_upload_and_record` | 2178 | 206 lines: on a retry, ask the platform first (found → PUBLISHED, no answer → FAILED_RETRYABLE, not found → upload); upload with `extra` = idempotency key, the channel's upload settings, `disclosed=True`, `publish_at`; map the adapter status CONFIRMED / UNKNOWN / RETRYABLE / other → PUBLISHED (or PUBLISHED_SIMULATED) / REMOTE_UNKNOWN + letter / FAILED_RETRYABLE / FAILED_FINAL + letter; `_mark_reconnect_needed` on `auth_refused` | EXTERNAL, mapped by CODE_RULE |
| `_blocked_at_execution` | 2012 | The gate refused at the last moment: BLOCKED_GATE with the reasons and `publishing.gate_failed_at_execution` | CODE_RULE |
| `_settle_failed_execution` | 2045 | An exception after STARTED: `is_transient` → FAILED_RETRYABLE, else FAILED_FINAL + letter; a row no longer STARTED is left as written (PUB-01) | CODE_RULE |
| `_record_remote_rejection` | 1982 | FAILED_FINAL with YouTube's reason in Romanian, the remote state, `publishing.remote_rejected` and an ESCALATE letter | EXTERNAL, recorded by CODE_RULE |
| `_note_remote_state` | 1894 | Store YouTube's privacy/upload status; the first time YouTube says private for a film asked public/unlisted (not scheduled), `tell_owner_locked_private` | EXTERNAL |
| `_mark_reconnect_needed` | 2078 | The bound connection → ERROR via `youtube.services.mark_reconnect_needed` | EXTERNAL (Google refused the account) |
| `_next_step` | 1824 | The letter's next-step sentence for FAILED_FINAL (auth refused / rejected / other), REMOTE_UNKNOWN and NEEDS_RECONCILIATION | CODE_RULE (wording) |

Helpers: `_requested_visibility`, `_bound_connection`, `_channel_name`, `_in_owner_words`,
`_remote_reason`, `_remote_state_unread`. Exceptions: `PublishingGateError` (`:63`; its `__init__`, `:66-69`, keeps the
message and the gate's reasons), `PublishingAssetNotFound` (`:72`),
`PublicationNotResolvable` (`:76`), `PublisherNotConfigured` (`:80`), `PublishPolicyError` (`:102`).

Data: reads/writes `channel_record`, `channel_brand_asset`, `publication_record`, `command_record`; reads
`owner_policy`, `media_asset`, `quality_control_report`, `video_render_job`, `storyboard`, `script_draft`,
`factual_claim`, `source_snapshot`, `youtube_connection`, `agent_message`, `story_episode`, `domain_event`. Events:
`channel.created`, `channel.configured`, `publishing.channel_policy_changed`, `publishing.intent_created`,
`publishing.gate_failed`, `publishing.gate_failed_at_execution`, `publishing.started`, `publishing.video_published`,
`publishing.video_published_simulated`, `publishing.remote_unknown`, `publishing.failed_retryable`,
`publishing.failed`, `publishing.reconcile_unavailable`, `publishing.retry_reconciled`,
`publishing.reconciled_published`, `publishing.reconciled_not_found`, `publishing.remote_rejected`,
`publishing.visibility_locked_private`, `publishing.started_stale`, `publishing.reconcile_exhausted`,
`publishing.resolved_by_owner`. External calls: the YouTube adapter (`upload_video`, `get_video_status`,
`ask_reconcile`), local file reads. No money.

### `app.publishing.licence_release` — `backend/app/publishing/licence_release.py` (521 lines)

Uploads held private only because the film's licence was unconfirmed, made public once it is (`licence_release.py:1-37`).
Driven by the watchdog pass `workflows/passes/licence_release.py`.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `mark_held_for_licence` | 111 | Write `publishing.held_private_for_licence` once on a publication | Called by `runbook.stages._publish_one` in the upload's transaction | CODE_RULE |
| `held_for_licence` | 136 | "marked" (event), "walk" (the film's `runbook.film_continued` reason contains the held words), "day" (the day's publish stage artefact `private_until_licensed`), or None | Uploads made before the marker existed | CODE_RULE |
| `licence_held_uploads` | 178 | PUBLISHED private, unscheduled, with a video id, held and not released; oldest first, ≤ 20 | One pass's work list | CODE_RULE |
| `confirm_licence` | 201 | Re-read each ledger component's commercial-use evidence; all present → asset LICENSED, ledger updated, `media.licence_confirmed` | QC froze NEEDS_REVIEW; Gate 7 would refuse forever | CODE_RULE on EXTERNAL evidence |
| `release_licence_held_uploads` | 281 | `may_act(publishing.public_publish, T3, ask_owner=False)` once; then `_release_one` each | "under SUPERVISED or MANUAL a film is made public by him, never by this pass" (`:296-297`) | OWNER (mode) + CODE_RULE |

Private functions that decide something:

| Function | Line | What it does | Decided by |
|---|---|---|---|
| `_release_one` | 319 | In order: the channel's policy must resolve to a public release (`resolve_publish_visibility(...)["release_privacy"] == "public"`); back-off after failures (15 min × 2^(n−1), ≤ 24 h); `confirm_licence` must allow public; the gate asked for public under the current policy version must pass except `MEDIA_FILE_MISSING`/`MEDIA_HASH_MISMATCH`; a publisher with `update_visibility`; the YouTube call. A call that raises → `publishing.privacy_release_failed` and, on `insufficientPermissions`, the reconnect letter | OWNER (policy, environment) + CODE_RULE + EXTERNAL |
| `_record_release` | 407 | YouTube says not there → deleted, FAILED_FINAL via `_record_remote_rejection`; else privacy_status "public", `policy_version`, remote state, `publishing.privacy_released` (written before YouTube's privacy answer is compared); YouTube still private → `tell_owner_locked_private`, else a STATUS note | EXTERNAL, recorded by CODE_RULE |
| `_tell_owner_reconnect` | 457 | One STATUS letter per channel asking the Owner to reconnect the YouTube account with the visibility scope; scans every `AgentMessage` for an earlier one | CODE_RULE |
| `_tell_owner_released` | 490 | STATUS letter: the film is public now, with the policy version and its address | CODE_RULE (INFORMATIONAL) |

Helpers: `_events`, `_moment`.

Data: reads `publication_record`, `domain_event`, `daily_run`, `media_asset`, `video_render_job`, `scene_take`,
`integration` (the Owner's licence answer, via `vendor_licence`), `channel_record`, `owner_policy`, `agent_message`;
writes `publication_record`, `media_asset.license_status`, `video_render_job.production_json`, `agent_message`,
`domain_event` (`publishing.held_private_for_licence`, `media.licence_confirmed`, `publishing.privacy_released`,
`publishing.privacy_release_failed`). External: YouTube `videos.update` (status part). No money.

### `app.publishing.router` — `backend/app/publishing/router.py` (472 lines)

Owner-only routes under `/publishing` (`router.py:140`).

| Route | Function | Line | What it does | Decided by |
|---|---|---|---|---|
| — | `get_active_publisher` | 87 | The YouTube provider for the request's channel (publication's channel, or MAIN_FACTUAL for `/publish-asset`); 409 when the selected account does not match the channel or the slot is not AUTHENTICATED; 503 when nothing is configured; no simulator fallback | CODE_RULE / EXTERNAL |
| `GET /publishing/channels` | `get_all_channels` | 143 | Channels with bindings, connected accounts, a binding hint | — |
| `POST /publishing/channels/seed` | `seed_channels_endpoint` | 185 | `seed_default_channels` | OWNER (trigger) |
| `PUT /publishing/channels/{id}/production-policy` | `set_production_policy` | 191 | `media.production_policy.set_channel_policy` | OWNER |
| `POST /publishing/channels/{id}/publish-policy` | `set_publish_policy` | 205 | `change_publish_policy`; 404/409/422 | OWNER |
| `GET /publishing/channels/{id}` | `get_single_channel` | 227 | One channel | — |
| `POST /publishing/channels/{id}/configure` | `configure_channel_endpoint` | 237 | `configure_channel` | OWNER |
| `GET /publishing/gate/evaluate/{asset}/{channel}` | `evaluate_gate` | 258 | Gate dry-run as a private upload, so the policy (6) and rights (7) checks never run here, nor the episode-metadata check | CODE_RULE |
| `GET /publishing/publications` | `get_all_publications` | 266 | List | — |
| `GET /publishing/publications/{id}` | `get_single_publication` | 270 | One | — |
| `POST /publishing/publications/intent` | `post_publication_intent` | 280 | The Owner's own intent with the footer; a visible request is stamped with the channel's current policy version | OWNER, CODE_RULE (gate) |
| `POST /publishing/publications/{id}/execute` | `execute_publication_endpoint` | 336 | `execute_publication` | OWNER (trigger), EXTERNAL |
| `POST /publishing/publications/{id}/resolve` | `resolve_publication_endpoint` | 357 | `resolve_publication` | OWNER |
| `POST /publishing/publish-asset/{asset_id}` | `quick_publish_asset` | 381 | Channel A, script title, empty tags, footer, private intent, execute | OWNER (trigger) |

`create_publishing_router` (`:139`). `ResolvePublicationCommand` (`:65`) requires a video id with «Există»
(`_found_names_the_video`, `:77-84`).

## Connections

**Who calls into this group**

| Caller | What it calls |
|---|---|
| `app.main` | `create_story_router`, `create_publishing_router` |
| `app.runbook.services` (`:43-45`, `:805`, `:830-847`, `:1672`) | `close_daily_log` (stage `daily_log`), `close_missing_days` + `close_previous_day` (at run start) |
| `app.runbook.stages` (`:177`, `:6182-6197`, `:6422-6425`) | `run_serial_stage` (stage `serial_queue`, before `media`), `run_serial_next_stage` (stage `serial_next`, after `daily_log`) |
| `app.runbook.stages._publish_one` (`:5670`) and `_publish` (`:5991`) | `select_channel_for`, `resolve_publish_visibility`, `evaluate_publishing_gate`, `publication_metadata_refusals`, `publish_media_asset`, `mark_held_for_licence`, `PublisherNotConfigured`, `PublishingGateError`; the module also imports `film_identity`, `published_films`, `channel_bindings`, `channel_type_for_storyboard`, `publication_footer`, `LIVE_PUBLICATION_STATES`, `REMOTE_REJECTED_STATES`, `ROUTE_SELECTED` and `story.services.business_date` (`runbook/stages.py:140-178`) |
| `app.agents.reviews.prepare_publication` (`:1485`) | `episode_identity`, `series_title`, `hook_of`, `fallback_metadata`, `publication_metadata_refusals` (around the Publisher's model answer) |
| `app.workflows.watchdog` (`:68-77`, `:301-395`, `:476`) | `mark_stale_started`, `check_processing`, `reconcile_publication` (REMOTE_UNKNOWN with an id), `reconcile_by_title` (REMOTE_UNKNOWN without one), `execute_publication` (FAILED_RETRYABLE retry), `hand_to_owner`, `upload_started_at`, `channel_bindings`, `REMOTE_SETTLED_STATES` |
| `app.workflows.passes.licence_release` | `licence_held_uploads`, `release_licence_held_uploads` |
| `app.workflows.passes.serial_unfilmed` | `ready_for_filming`, `serial_continuation_key` |
| `app.media.serial_storyboard` | `lines` (`NameBook`, `beat_lines`, `speakers_of`, `spoken_text`), `locations` (`location_name`, `studio_locations`), the story models, `SERIES_KEY`, `bibles_for_roster` |
| `app.media.prompt_agent` (`:451-453`) | `location_name`, `studio_locations` |
| `app.runbook.preflight` | the `ChannelRecord.director_may_approve_episodes` column (not the function, `runbook/preflight.py:641`), `bound_connection_id`, `channel_bindings` |
| `app.analytics.services`, `app.goal`, `app.media.qc`, `app.media.director_qc`, `app.demo` | `StoryEpisode`, `bound_connection_id`, `channel_type_for_storyboard`, `QC_MINIMUM_SCORE`, `seed_default_channels` |
| `app.workflows.worker`, `app.workflows.passes.resume_interrupted_day` | `story.services.business_date` |
| `app.providers.youtube` | names `resolve_publish_visibility` in a comment only (`providers/youtube.py:442`) |

Not a caller: `app.factual.story_review` and `app.media.shooting_sheet` use their own `motion_clip_limit`
(`media/shooting_sheet.py:4224`, signature `(engine)`), a different function from `app.story.review.motion_clip_limit`
(`(session)`), which is called only by `episode_checks` (`story/review.py:692`).

**What this group calls out to**

`app.agents.services.run_agent_task` (model calls); `app.agents.editorial_judgement` (`editorial_loop`,
`record_rounds`, `letter_to_owner`); `app.agents.memory` (`agent_for_role`, `remember`); `app.agents.messages.post_message`
(letters); `app.agents.language` (`audience_language_line`, `looks_like_english`); `app.agents.identity` (`clipped`,
`joined`, `parse_structured`); `app.factual.sanitizer.wrap_in_inert_boundary`; `app.factual.agent_pipeline._resolve_agent`;
`app.media.serial_storyboard` (`storyboard_from_episode`, `describe_serial_shots`); `app.media.prompt_agent`
(`prompt_lessons`, `lessons_rule`, `fit_with_lessons`, `SCOPE_SERIAL`: the showrunner's picture lessons,
`story/services.py:1538-1549`); `app.media.production_policy`,
`app.media.cost_plan`, `app.media.assembler`, `app.media.speaker_voices` (filmable check); `app.media.qc`
(`rights_verdict`), `app.media.factory.vendor_licence`, `app.media.assembler.film_licences` (licence);
`app.services` (`append_event`, `queue_film_continue`, `may_act`, `utc_now`); `app.runbook.services.classify_fault`;
`app.providers.youtube` / `publishing_base` (adapter, `ask_reconcile`, `fit_bytes`, `youtube_safe_metadata`);
`app.integrations.services.selected_youtube`; `app.youtube.services.mark_reconnect_needed`.

**Events emitted** — story: `story.daily_log_closed`, `story.episode_drafted`, `story.episode_reviewed`,
`story.episode_approved`, `story.episode_rejected`, `story.continuity_advanced`, `editorial.judged` (through
`record_rounds`). Publishing: listed under `app.publishing.services` above, plus `publishing.held_private_for_licence`,
`publishing.privacy_released`, `publishing.privacy_release_failed`, `media.licence_confirmed`.

**Events consumed** — the projection reads every committed `domain_event` of a day and keeps the 39 PUBLIC_SAFE types
(including `publishing.video_published`, `media.editorial_reviewed`, `factual.topic_selected`, …).
`held_for_licence` reads `publishing.held_private_for_licence`, `runbook.film_continued` and the publish stage's
artefacts in `DailyRun.stages_json`; `licence_held_uploads` reads `publishing.privacy_released`; `_release_one` reads
`publishing.privacy_release_failed` (back-off); `upload_started_at` reads `publishing.started`;
`publication_metadata_refusals` reads the Publisher's READY `AgentMessage` bodies of the last 24 h.

## Owner touchpoints

| Touchpoint | What the Owner decides | Where |
|---|---|---|
| Publish-policy command (`POST /publishing/channels/{id}/publish-policy`) | Channel visibility (private/unlisted/public), the public flag, release delay, **whether the Director may approve episodes**, YouTube category, made-for-kids, language, longest Short | `publishing/services.py:352-470`, `publishing/router.py:204-224` |
| Environment (TEST/PRODUCTION, the Owner's `change_environment` command, `app/services.py:244`) | Read here: nothing visible leaves in TEST; filming tasks are queued only in PRODUCTION | `publishing/services.py:387-389`, `:528-546`; `app/services.py:658-660` |
| Autonomy stop (set elsewhere) | Gate 1 refuses every publication | `publishing/services.py:1022-1026` |
| Mode (AUTONOMOUS_CEO / SUPERVISED / MANUAL, via `may_act`) | Whether held uploads are made public by the watchdog | `publishing/licence_release.py:297-304` |
| Commercial-use answer on a vendor connection (recorded elsewhere: the Owner's yes in Setări, or the paid plan `integrations.plan_licence` reads under his card of 2026-10-10) | Read by `confirm_licence` as licence evidence; anything but an explicit yes counts as none | `publishing/licence_release.py:240-241`, `media/factory.py:418-440` |
| Episode decision (`POST /story/episodes/{id}/decide`) | Approve or reject any DRAFT (rejection needs a reason); approval advances canon and builds the storyboard | `story/services.py:1813-1852`, `story/router.py:174-204` |
| Manual story actions | Close a day, write, review, storyboard an episode | `story/router.py:67-172` |
| Publication resolution (`POST /publishing/publications/{id}/resolve`) | «Există» with the video id / «Nu există» | `publishing/services.py:2738-2808` |
| Channel configuration, seeding, production policy, own intents, execute, one-click publish | Channel identity and binding; hand-made publications | `publishing/router.py:184-470` |
| Settings | `editorial_rounds`, `content_language`, `timezone`, `ai_disclosure_url`, `ai_disclosure_texts`, `studio_display_name`, `creator_channel_title` | `config.py:434`, `publishing/services.py:700-773` |
| Letters to the Owner | ESCALATE: publication FAILED_FINAL / REMOTE_UNKNOWN / NEEDS_RECONCILIATION (`publishing/services.py:1852-1891`), YouTube keeps films private (`:1919-1961`); STATUS: reconnect the channel's account for visibility changes (`licence_release.py:457-487`), a held film is now public (`:490-521`), an episode shipped below the editorial bar (`agents/editorial_judgement.py:773-823` via `review.py:1373-1379`) | as listed |
| Stage card text | "waits for your approval; the channel policy does not let the Director approve alone" (`serial_stage.py:459-469`, `:625-631`, `:842-853`) | as listed |

## Oddities and gaps

1. `pending_log` (`backend/app/story/serial_stage.py:216-218`) has no caller in backend code; it is referenced only in
   docstrings (`serial_stage.py:238`, `:249`), a test docstring (`tests/test_reattempt_buys_nothing_twice.py:7`) and a
   test comment (`tests/test_serial_pipeline.py:865`).
2. `execute_publish = execute_publication` (`backend/app/publishing/services.py:2863`) and `LETTER_STATUSES`
   (`services.py:1789`) have no reader anywhere in `backend/app`. `CHANNEL_AUTHENTICATED` (`services.py:161`) is defined
   but the AUTHENTICATED status is written only in `backend/app/integrations/router.py:479`.
3. `evaluate_publishing_gate`'s docstring says "the 5 mandatory publishing gates" (`services.py:994`), the body runs 7
   checks (policy authorisation `:1289`, rights `:1363`), and `create_publication_intent` appends an eighth reason
   family, `EPISODE_METADATA` (`:1666-1679`).
4. `REMOTE_CONFIRMED` and `SCHEDULED` are listed as live states (`services.py:170-177`), in the model comment
   (`publishing/models.py:125-126`) and in spec 47 "Publication" (`docs/architecture/47_STATE_MACHINE_SPECIFICATIONS.md:84-85`),
   but no code in scope assigns them: a scheduled release is stored as PUBLISHED with `scheduled_publish_time`, a
   deliberate choice recorded in `16_DECISION_LOG.md:1866` ("keeps status PUBLISHED … rather than the model's declared
   SCHEDULED"); REMOTE_CONFIRMED has no such record. `PUBLISHED_SIMULATED` is assigned
   (`services.py:2237`, `:2299`, `:2474`, `:2581`) but is in neither the model comment nor spec 47.
5. `configure_channel` always re-derives the status with `derive_channel_status` (`services.py:831`), which never
   returns AUTHENTICATED; reconfiguring an AUTHENTICATED channel therefore sets it to CONFIGURED, and both
   `get_active_publisher` (`router.py:130-135`) and `quick_publish_asset` (`router.py:395-405`) then refuse it.
6. `quick_publish_asset` always publishes to the first MAIN_FACTUAL channel (`router.py:103-111`, `:391-394`)
   whatever the film's storyboard says, unlike the daily run's `select_channel_for` (decision
   `16_DECISION_LOG.md:1872`).
7. `POST /story/episodes/{id}/review` calls `review_episode` with the default `approve=True` (`story/router.py:149-155`):
   a PASS there approves under the policy at once and skips the editorial judgement that the stages apply through
   `judged_review` (`serial_stage.py:429-431`). `POST /story/episodes/write` passes no `language`, so it writes with
   "en" (`router.py:115-121`), while the review route passes `settings.content_language`.
8. `_resolve_showrunner` falls back to any ACTIVE agent with a model when no ScriptWriter exists
   (`factual/agent_pipeline.py:101-102`), and raises `ValueError` (not `StoryError`) when none exists (`:104`) or when
   the route's `agent_id` names an agent that is not ACTIVE or has no model (`:94`, `:96`); `_tell_the_day`
   catches only `NothingHappened`, `DraftRefused`, `StoryError` (`serial_stage.py:398-418`) and `post_write` only those
   three (`router.py:122-128`), so this surfaces as a stage hard fault (`classify_fault` → HARD, re-raised at
   `serial_stage.py:706-711`) or an HTTP 500. `StoryError` subclasses `ValueError`, not the other way round.
9. Two episode numbers: `continuity_json.episode_number` is fixed at write time from the canon in force
   (`story/services.py:1602`, `:1702`) and is what `episode_identity` publishes (`serial_identity.py:167`), while canon
   assigns its own number at approval (`story/services.py:627`). They agree only because the stages never write beside
   a waiting episode (`serial_stage.py:625-631`, `:842-853`); `decide_episode` accepts any DRAFT
   (`story/services.py:1822`), including an older one.
10. `_record_release` sets `privacy_status = "public"` and writes `publishing.privacy_released` before comparing YouTube's
    privacy answer; when YouTube keeps the video private the row says public while `remote_privacy_status` says private, and
    the pass will not try again (`licence_release.py:426-452`, filter `:184-194`). `_public_url` trusts the stored
    `privacy_status` (`serial_identity.py:147`), so such an episode would be linked as "Previously on …" under the next
    episode although nobody can open it.
11. The brief asks for 115–170 spoken words (`story/services.py:109`); the review's length check accepts 45–70 s at
    2.5 words/s, i.e. about 113–175 words, with seconds rounded to 0.1 (`review.py:583-584`, `:656`). The length check
    does not enforce `MIN_BEATS = 6`; only the five-part structure check bounds the low end (`review.py:275-299`).
12. Letters vs. the Owner's 2026-10-12 rule: the decision log says a letter reaches the Owner only for accounts,
    sign-ins, authorisations and security, and a failing tool is a `developer_defect` note
    (`16_DECISION_LOG.md:51-53`). The code in scope still writes ESCALATE letters for REMOTE_UNKNOWN and other
    non-account publication states (`publishing/services.py:2346`, `:2372-2374`, `:2730`), a STATUS letter for every
    released film (`licence_release.py:453`), and the editorial letter when an episode ships below the bar
    (`review.py:1373-1379`).
13. Decision "A channel's visibility is the Owner's versioned command" says `upload_privacy_default` is "still unread"
    (`16_DECISION_LOG.md:1862`); it is now passed to the Publisher's prompt as `privacy_default`
    (`agents/reviews.py:1520`), though no publish path uses it for visibility.
14. `DailyStudioLog.status` documents an OPEN state (`story/models.py:52`), but `close_daily_log` writes only CLOSED
    (`story/services.py:465`) and nothing in scope writes OPEN.
15. `NARRATIVE_EVENT_TYPES` (`story/services.py:133-151`) includes `agent.model_assigned` and
    `settings.integration_checked`, which are deliberately not PUBLIC_SAFE (`projection.py:56-60`): they reach the raw
    operational record (`notable_events_json`) but not the showrunner. `grounding_report` falls back to
    `notable_events_json` for a log with no projection (`story/services.py:1867-1871`).
16. Static analysis lists `post_storyboard` and `post_decide` as reaching a model (4 hops), but
    `storyboard_from_episode` calls `write_shot_prompts(engine, None, …)` (`media/serial_storyboard.py:362`), so no model
    is called on those routes; the model description of serial shots happens only through `describe_serial_shots`.
17. Scans that grow with history: `held_for_licence` iterates every `DailyRun` since 2026-10-10 for each held
    publication (`licence_release.py:162-174`); `_tell_owner_reconnect` iterates every `AgentMessage`
    (`licence_release.py:467-470`); `episode_identity` iterates every APPROVED episode (`serial_identity.py:171-178`).
18. `review_episode` checks `registry.registered_ids()` before asking (`review.py:988`) but `judged_review`'s rewrite
    closure asserts `registry is not None` (`review.py:1297`) — safe only because a PASS requires a model reading.
19. The `review.py` module docstring says her notes go back "for the one rewrite the stage allows" (`review.py:35-36`);
    the stage allows one rewrite per run but up to `MAX_DRAFTS_PER_DAY = 3` stored drafts across runs
    (`serial_stage.py:53-59`), plus up to `editorial_rounds − 1` editorial rewrites outside that budget
    (`serial_stage.py:367-371`).
20. Provider faults during the two model calls never become `TransientStageError`, although the module docstring
    (`serial_stage.py:12-15`) and `_serial_queue`'s (`runbook/stages.py:6184-6186`) say a provider or network fault is
    raised for an in-place retry: `run_agent_task` records a provider exception as a FAILED run and returns
    (`agents/services.py:960-967`), so `write_episode` raises `StoryError` and `review_episode` `ReviewError`, and
    `_tell_the_day` ends the attempt COMPLETED (`serial_stage.py:414-418`, `:432-435`). Only exceptions from elsewhere
    (database, storyboard building, filming queue) reach `_transient`.
21. `classify_event_type` (`projection.py:257`) has no caller in `backend/app`; only `tests/test_serial_pipeline.py:50`,
    `:278-280`, `:1707` use it. The projection decides privacy with `PUBLIC_SAFE_EVENTS.get` inside `describe_public`.
22. `resolve_publication` writes `remote_url = https://youtube.com/shorts/<id>` from the Owner's id
    (`publishing/services.py:2778`), while `reconcile_publication` says "Keep whatever URL the provider actually returned;
    never synthesise one" (`:2476`). The id is checked only for shape (`:2735`, `:2774`), never against the channel.
23. `ChannelRecord.status` documents `UNCONFIGURED | CONFIGURED | AUTHENTICATED | ERROR | ACTIVE` with default
    "UNCONFIGURED" (`publishing/models.py:66-67`), but the services write NOT_CONFIGURED / AUTH_REQUIRED / CONFIGURED
    (`services.py:159-162`, `:235-241`) and only `integrations/router.py:479` writes AUTHENTICATED. Two readiness
    signals coexist: the daily run asks whether the bound `YouTubeConnection` is CONNECTED (`select_channel_for`,
    `services.py:633-642`), the manual routes whether the slot's own status is AUTHENTICATED (`router.py:130`, `:395`).
24. `runbook.stages._serial_next`'s docstring says the evening script is "never storyboarded" (`runbook/stages.py:6194-6196`);
    since 2026-10-11 `run_serial_next_stage` readies the approved episode and queues its filming
    (`serial_stage.py:724-737`, `:481-486`, `:817-830`).
25. The story routes take a `command_id` (`story/router.py:30-57`) but use it only as a correlation id: there is no
    `CommandRecord` idempotency, so re-sending `POST /story/episodes/write` with the same `command_id` writes, and pays
    for, a second draft. (`close_daily_log` is idempotent by date; review and decide refuse a second call by state.)
26. On a retold day, a refused answer (`DraftRefused`) replaces the Director's notes on the day's last refused draft with
    the refusal reason and drops `rewrite_of` (`serial_stage.py:412`), so the next attempt no longer sees her notes or
    that draft.
27. A Director FAIL posts a HANDOFF letter to the ScriptWriter (`review.py:1078-1091`). HANDOFF is an asking intent
    (`agents/mail.py:79`), so a later mail round spends a ScriptWriter model call answering it (`agents/mail.py:489-491`),
    while the rewrite itself is done by the stage with the same notes.
28. Canon keeps the first 12 open threads (`row.threads_json = threads[:12]`, `story/services.py:664`) after appending
    the new ones, so once 12 are open every thread an approved episode opens is silently dropped, while recurring items
    keep the newest 12 (`:665`). The writer is still told it may open threads (brief rule 10, `:939-943`).
29. `_PICTURE_LESSONS_CHARS = 6000` (`story/services.py:1527`) bounds nothing: `_picture_lessons` passes it to
    `fit_with_lessons` with an empty payload (`:1549`), and `fit_with_lessons` fits only the non-lesson data to the limit
    and puts every lesson in front whole (`media/prompt_agent.py:992-995`). The block is bounded by `LESSONS_GIVEN = 12`
    (`prompt_agent.py:126`) and by the 400-character refusal at record time (`LESSON_MAX_CHARS`, `:133`,
    `lesson_is_general` `:3388-3389`); `_read_lesson` does not check length when a lesson is read (`:3213-3229`).
30. The `LESSONS_RULE` text the showrunner now receives (`media/prompt_agent.py:164-173`) says a lesson never overrides
    "this brief's fixed rules (the look it gives, who faces the viewer and how, the visual bible, no writing in the
    picture)". The episode brief has only the last of these (rule 6, `story/services.py:922-925`); it gives no look, no
    facing rule and no visual bible. The same rule tells the writer that each lesson "was learned from a picture that
    failed quality control" (`prompt_agent.py:166-167`), but the editorial review records its picture note whatever her
    verdict on the film, an approved one included (`agents/editorial.py:575-590`). And the brief's rule 11 says EVENTS,
    PREVIOUSLY, the PLAN and any earlier draft are data inside boundaries and nothing inside them is an instruction
    (`story/services.py:944-945`); the lessons arrive inside the same `untrusted_source_evidence` boundary (`:1553`,
    `factual/sanitizer.py:104-112`) and `LESSONS_RULE` names them as rules to follow.
31. Lessons recorded by `director_qc.learn_from_decision` use `record_prompt_lesson`'s defaults, scope "all" and not
    unverified (`media/director_qc.py:1640`, `media/prompt_agent.py:3429-3436`), whatever kind of film the decision was
    about; they therefore reach the serial showrunner's brief as confirmed lessons, ahead of every unverified serial
    lesson (`prompt_agent.py:3348-3350`).
32. The picture lessons reach the showrunner's brief without `projection.redact` (`story/services.py:1545-1555`), and
    the lesson store refuses an empty or long lesson, a film title, a scene number or a record id, but not a vendor's or
    model's name (`media/prompt_agent.py:3376-3426`); the day's event lines, by contrast, are redacted
    (`projection.py:213-224`). The review's privacy check still runs on the scene, line, direction, title and canon text
    the writer returns (`story/review.py:544-581`). `MemoryRecord`'s docstring says its records are written "never from
    a model's free text" (`agents/models.py:263-265`); the lesson rows this brief now reads are the Director's model text.
