# 07 — Media blocker repair, Owner cards, film close, sound design, voices, music, model research, mode guard, media HTTP router

> Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).
>
> Files (10 files, 6770 lines, 178 functions):
> - `backend/app/media/blocker_repair.py` (1041 lines, 19 functions)
> - `backend/app/media/cards.py` (1302 lines, 39 functions)
> - `backend/app/media/film_close.py` (700 lines, 17 functions)
> - `backend/app/media/sound_design.py` (698 lines, 25 functions)
> - `backend/app/media/speaker_voices.py` (295 lines, 6 functions)
> - `backend/app/media/music_library.py` (318 lines, 11 functions)
> - `backend/app/media/model_research.py` (546 lines, 7 functions)
> - `backend/app/media/mode_guard.py` (266 lines, 9 functions)
> - `backend/app/media/answered_letters.py` (176 lines, 3 functions)
> - `backend/app/media/router.py` (1428 lines, 42 functions: 7 module-level incl. `create_media_router`, plus 35 nested route handlers)
>
> First mapped 2026-10-12 from commit b00083c plus the working tree. The ten files of this group
> are byte-identical at b00083c and 20abffd, so their line numbers hold; citations into files
> changed after b00083c (`assembler.py`, `stills_stage.py`, `qc.py`, `prompt_agent.py`) and into
> the new `second_look.py` give their lines at 20abffd.
> Verified adversarially on 2026-10-12 at HEAD 3d49e9a (still no change to these ten files since
> b00083c); the corrections are folded into the text below.
>
> Note on the name "cards": `app.media.cards` draws *picture cards* (bar charts, title cards,
> black screens, the cover) with ffmpeg. The Owner's *decision cards* are built in
> `app.decisions.sources`; this group only triggers them (see "Owner touchpoints").

## In one paragraph

This group is the media department's housekeeping and its HTTP door. `blocker_repair` is a
worker loop that scans shooting sheets every few minutes, turns each sheet's blockers into a
report to the Director, asks the Director (an LLM) to assign prompt fixes to the Video Editor,
runs the real repair tools (story repair, prompt rewrite), re-reads the sheet to verify, and
backs off / pauses with strict counters. `sound_design` asks the Voice Artist (an LLM) for a
music plan per film, validates it against the Owner's licensed library and falls back to a
deterministic plan; the mixer and QC enforce the loudness rules regardless of the plan.
`model_research` lets the stewards (Video Editor, Voice Artist) read vendor documentation and
score models; code filters the pages to the vendor's hosts, keeps only listed model ids, bounds
the scores to 0..1 (it does not judge them: the scores are written as given and drive
`rank_candidates`), protects billed prices and changes the default model only where the Owner
left it unlocked. Everything else is strict code:
`cards` composes 0-credit picture cards with pinned fonts; `music_library` vouches for each
licensed track by sha256; `speaker_voices` picks a voice per speaker by a fixed precedence;
`mode_guard` re-reads the Owner's policy before every vendor request of an unasked paid step;
`film_close` implements the Owner's «Închide filmul»; `answered_letters` closes stale letters;
and `router` exposes 35 Owner-only routes of `/media`, including the shooting sheet's paid
steps, redo, take decisions and the legacy render button (refused in PRODUCTION). Of 178
functions, 3 are LLM call sites (473 of 5141 function lines, about 9%; 8% if the 1037 lines of
nested route handlers are counted a second time inside `create_media_router`); 9 more reach the
LLM through other modules.

## Why it exists

| Module | Problem it solves | Incident / Owner rule (cited) |
|---|---|---|
| `blocker_repair` | A shooting sheet blocked by lint/shot-plan/story problems must be repaired by the studio, never turned into an Owner questionnaire, and never loop forever. | 2026-10-03 Owner: «pune și o siguranță să nu meargă la infinit» after the scan queued the same repair every five minutes for an hour with every model call failing (`blocker_repair.py:50-54`); 2026-10-10 NASA film: the daily-ceiling pause letter reached the Owner, who answered «studioul trebuie să rezolve singur, fără intervenții», so non-account pauses go to the Director (`blocker_repair.py:259-269`); 2026-10-11 serial board f06808c9: rewritten prompts changed the fingerprint so the ceiling never engaged; counting moved to `issue_key` (`blocker_repair.py:166-175`; `16_DECISION_LOG.md:82`); same board: a RESOLVED repair left the film idle until the next morning, so a FILM_CONTINUE is queued (`blocker_repair.py:613-624`). |
| `sound_design` | The bed used to be chosen by counting mood words and sat at one level under the whole film. | Owner 2026-10-11: music placed by the sound agent, well under the voice, quiet or loud where needed, never covering the voice (`sound_design.py:3-6`); decision log `16_DECISION_LOG.md:84` (commit 2e20ecf). |
| `model_research` | Employees should choose their technology by reading vendor pages, with prices, not guess. | Owner request that the video editor and voice artist choose models (`model_research.py:3-8`); the judge prompt cites the model recorded at 0.025 USD/s that cost 0.43 (`model_research.py:128-131`). |
| `mode_guard` | A paid step that asked the Policy Kernel once at its start kept buying after the Owner lowered the mode. | 2026-10-04 05:02-05:21 UTC, LHC film 4d0da5d9: scenes 4-9 submitted after the mode went to MANUAL at 05:08:27, 6 x 18 = 108 credits (`mode_guard.py:3-9`); spec `docs/architecture/51_AUTONOMY_MODE_SEMANTICS.md:185-189` «Lowering autonomy»; ADR-POLICY-READ-PER-REQUEST (`16_DECISION_LOG.md:4186`). |
| `film_close` | Nothing let the Owner close a film; three old factual films blocked topic selection for days. | 2026-10-09 (`film_close.py:1-6`). |
| `answered_letters` | Letters to the Owner kept asking after the question was answered or the film had moved on. | 2026-10-09 film babcf272: the Owner closed six stale sheet letters by hand; 2026-10-12: «scena 6 așteaptă decizia Proprietarului» stayed open after the walk moved on (`answered_letters.py:3-16`). |
| `cards` | Photographic models asked for a chart or a black screen return photographs anyway, and both were paid for and failed QC. | Nepal film, scenes 5 and 6 (`cards.py:3-8`); Nepal rehearsal 2026-10-01: captions over bar labels (`cards.py:52-55`) and a 4.3 s black ending (`cards.py:106-111`); LHC film 2026-10-03: highlight text refused every script rewrite (`cards.py:466-472`). |
| `music_library` | A film's music may come only from tracks the Owner has rights to. | Spec `docs/architecture/23_CONTENT_RIGHTS_PLATFORM_POLICY.md:18-26` («Do not use random copyrighted music automatically»); 2026-10-11 Owner library of 20 beds and 5 ambiences (`music_library.py:39-42`). |
| `speaker_voices` | Every serial line was read by the narrator, so two people talking sounded like one person reading. | Measured 2026-09-24 (`speaker_voices.py:3-9`); decision log 2026-09-24 S7 (`16_DECISION_LOG.md:3968`). |
| `router` | One HTTP surface for the media department, Owner key only. | The legacy render button bought a whole film without showing a price (second Nepal render, 2026-09-26) and is refused in PRODUCTION (`router.py:545-552`). |

## Who decides here

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| Whether the automatic sheet repair may run at all | CODE_RULE + OWNER (mode) | `blocker_repair.py:314-318` | OwnerPolicy not stopped, `autonomy_mode != "MANUAL"`, no shutdown requested, safe mode off. |
| How often sheets are scanned | CONFIG | `workflows/worker.py:461-474`; `config.py:56` | `sheet_blocker_scan_seconds` default 300 (30..86400); also requires a registry. |
| Which films are scanned | CODE_RULE | `blocker_repair.py:968-976` | Newest 30 storyboards with status APPROVED, NEEDS_SHOT_PLAN or RENDERED; skipped when a story repair already wrote a replacement. |
| What counts as a blocker and whose it is (PROMPT / STORY / OWNER) | CODE_RULE | `blocker_repair.py:321-434` | Sheet `blocks` and `shot_plan_gaps` → PROMPT; card `problem_ro`, failed story review → STORY; for each step still `to_buy`: balance unverified, balance < the footer's `balance_needed_credits` for the step (or `ceil(cost_credits × 1.15)` when the footer lacks it, `DEFAULT_MARGIN`, not the Owner's `paid_step_balance_margin`), step cap > day's remaining budget, step cap > film's remaining ceiling, blocked step; and a catalogue problem → OWNER. (PROMPT codes `SCENE_TOO_LONG` and `KIND_MISMATCH`, and STORY `CARD_INVALID`, send the story to a rewrite rather than to the prompt writer: `sheet_story_repair.py:174-179`.) |
| Whether a new repair attempt is queued, backed off or paused | CODE_RULE | `blocker_repair.py:194-251`, `461-479` | An open task (QUEUED/CLAIMED/RUNNING/RETRYING) or a same-fingerprint task already RESOLVED/WAITING_OWNER is reused (no new attempt). Otherwise counts UNRESOLVED attempts on the same `issue_key` since max(now−24 h, Owner retry, process start); with at least one: the 3 newest `AgentRun` rows of the whole studio all FAILED with `ProviderHTTPError` → PAUSED LANGUAGE_MODEL_DOWN; ≥5 → PAUSED DAILY_LIMIT; else wait 0 s for <2 attempts, then 300 s × 2^(n−2), capped at 6 h. |
| Whether a pause reaches the Owner | CODE_RULE | `blocker_repair.py:256`, `272-295` | Only LANGUAGE_MODEL_DOWN (the Owner's LLM account) → card (re-asked on every paused scan, deduplicated by `ask`) + ESCALATE letter to the Owner; DAILY_LIMIT → STATUS letter to the Director. At most one open pause letter per sheet, whatever its cause (`blocker_repair.py:276-279`). |
| Allow a paused repair to try again now | OWNER | `blocker_repair.py:119-163` | `issued_by == "owner"` else PermissionError; idempotent per correlation id; resets the attempt window. |
| Which agent repairs the prompts | CODE_RULE | `blocker_repair.py:554`, `597`, `845-860` | Always `PROMPT_ROLE` ("VideoEditor", `prompt_agent.py:76`), looked up by code; the Director's `assign_to_role` (default "VideoEditor") can only confirm it or make the attempt fail. Only PROMPT issues are handed over (`blocker_repair.py:819`). |
| What the repair instructions say | LLM_CHECKED_BY_CODE | `blocker_repair.py:557-599`, `848-892` | The Director's `note` (1..1200 chars, a longer one cut at a word boundary by `identity.fit_to_schema`) is passed as is as the HANDOFF letter and `repair_context["instructions"]` of the Video Editor's `write_shot_prompts`; code does not read the text. What code checks is the result: the sheet is rebuilt and re-linted (next row). |
| Whether the repair succeeded | CODE_RULE | `blocker_repair.py:893-923` | The sheet is rebuilt and re-linted: any PROMPT issue left → UNRESOLVED; only OWNER/STORY issues left → WAITING_OWNER; none → RESOLVED. |
| Whether a RESOLVED film is walked on (can lead to paid steps) | CODE_RULE | `blocker_repair.py:613-639`; `services.py:645-660` | Not closed, not RENDERED/REJECTED, PRODUCTION only, once per report id; the continuation's purchases are gated by `may_act`. |
| Stop a repair on a closed film | CODE_RULE | `blocker_repair.py:740-748`, `653-656`, `924-926` | `film_is_closed` → STALE; no repair tool runs (only the result, a STATUS letter and `media.sheet_repair_finished` are written by `_finish`). |
| The film's music plan (bed, level per scene, ambience, fades) | LLM_CHECKED_BY_CODE | `sound_design.py:379-499`, `171-228` | Voice Artist's JSON must name only library ids, every scene exactly once; fades clamped to 0.3..4.0 s; a re-plan must differ from the refused plan and add no lift. A `null` bed (no music under the narration) is accepted as is and recorded as her advisory (`assembler.py:5853-5860`). |
| Fallback music plan | CODE_RULE | `sound_design.py:324-369`; `music_library.py:290-318` | Bed by mood-word stems with a sha256(seed:id) tie-break; every scene "under"; ambience by tag prefix of `audio_intent`. |
| How loud the bed actually is under the voice | CODE_RULE | `toolchain.py:587-614`, `771-794` | Bed 20 LU under the voice; soft −6 dB; lift +8 dB only inside voice silences (≤ −35 dBFS for ≥ 0.8 s, 0.1 s guard). |
| Whether a mix passes | CODE_RULE (QC) | `toolchain.py:591`; `sound_design.py:656-670` | Band 18-22 LU under the voice; a refusal triggers a re-plan through the Director's free audio redo (assembler). |
| Which track files may be used at all | CONFIG (the Owner's library file) + CODE_RULE | `music_library.py:193-240` | Entry needs `commercial_ok: true`, a written licence, a file inside the library folder, and a matching 64-hex sha256. |
| Which library file is read | CONFIG | `music_library.py:45-60` | Env `STUDIO_MUSIC_LIBRARY`, else `config/music/music_library.json` if present at import, else `config/music_library.json`. |
| The voice of each speaker take | CODE_RULE over OWNER/CONFIG inputs | `speaker_voices.py:147-218` | Locked voice (a binding with a `voice_id` and an identity lock on `voice`, resolved by `resolve_purpose`) → Owner binding (if `_validate` passes) → `serial_voice_cast.json` proposal (if in use, the narrator has a connection, that connection's kind equals the file's `provider_kind` when the file names one, and `_validate` passes) → narrator. |
| One voice per scene instead of per speaker | CODE_RULE | `speaker_voices.py:258-262` | When the joined lines differ from the scene's narration, the scene is read whole by one voice. |
| Which pages a steward reads | LLM_CHECKED_BY_CODE | `model_research.py:294-323` | URLs must be `https://`, on the vendor's own hosts, de-duplicated, ≤5. |
| Model quality / reliability / speed scores (and so the order `rank_candidates` gives the account's models) | LLM | `model_research.py:375-403`; `production_policy.py:369-378` | Only shape checks: each score must be 0..1 (an out-of-range score refuses the whole object, it is not clamped) and only notes whose `remote_id` is a listed candidate are written. The values themselves are written as given and enter `rank_candidates`' weighted score directly. |
| Documented prices | LLM_CHECKED_BY_CODE | `model_research.py:379-415`; `integrations/lifecycle.py:132-187` | A documented price never overwrites a BILLED one, key by key (`stamp_price`). Not checked: the magnitude (`_price_key` names the key from words in the unit and never rescales, oddity 26), the evidence URL (any `https://` URL is stored as the source), and an unpriced note (`pricing={}` replaces every recorded price, billed included, oddity 10). Moves ≥ `price_change_alert_percent` (default 10%) → the Accountant's ESCALATE letter to the Owner. |
| Default production model for a purpose | LLM_CHECKED_BY_CODE + OWNER lock | `model_research.py:417-454` | Recommendation must be a listed candidate, else (also when there is none) the top of `rank_candidates` — itself ordered by the steward's just-written scores; it must pass `production_resource`, and is applied only if `allow_production_override` is true (or there is no config row) and it differs from the current default. |
| Whether model research runs | CONFIG + OWNER | `main.py:526-536`; `integrations/router.py:392-399` | Weekly job (first run +2 h) when not demo mode; Owner button POST `/settings/model-research`. |
| Whether the next vendor request of an unasked paid step may be sent | CODE_RULE (Policy Kernel) over OWNER policy | `mode_guard.py:208-250` | `may_act(ask_owner=False)` again: ALLOWED goes on; NEEDS_APPROVAL goes on only if the step spent the Owner's yes for this plan; the Owner's own press goes on for BLOCKED_MODE/NEEDS_APPROVAL; anything else stops it and records `media.paid_step_stopped_by_mode` once. |
| Refuse an unasked step before the balance is read | CODE_RULE | `mode_guard.py:80-98` | A verdict that is neither allowed nor NEEDS_APPROVAL. |
| Close a film | OWNER | `film_close.py:526-572`; `router.py:860-881` | POST `/media/storyboards/{id}/close`, Owner key; idempotent by `command_id`. |
| Refuse a close | CODE_RULE | `film_close.py:159-251`, `568-572` | Finished render → FILM_RENDERED; serial episode → SERIAL_EPISODE; status not DRAFT/APPROVED/NEEDS_SHOT_PLAN → NOT_CLOSABLE; GPU session OPENING/OPEN/CLOSING, render PENDING/RENDERING, FILM_CONTINUE CLAIMED/RUNNING with a live lease, or the purchase lease held → FILM_BUSY. |
| What a close withdraws | CODE_RULE | `film_close.py:295-359` | Policy-kernel approvals whose subject is the film; open decision cards with `subject_id` = film; open asking letters about this film alone. Money/books letters stay. |
| Close a stale letter to the Owner | CODE_RULE | `answered_letters.py:91-176` | Sheet letter whose approval no longer waits, or superseded by a newer sheet letter, or the film's newest `runbook.film_state` differs; a waiting-list letter whose questions all no longer wait. |
| Refuse a picture card | CODE_RULE | `cards.py:409-463`, `906-921`, `567-581`, `740-741` | Unknown kind, LIVE kind, >4 bars, mixed units, non-positive or non-finite value, missing label/unit/claim id, text that does not fit, bars with <200 px, BLACK >1.5 s in a short with no still. |
| Fonts used in cards and captions | CODE_RULE (SHA-256 pins are constants in code) | `cards.py:74-83`, `170-185` | Inter Bold/Regular only if the SHA-256 matches; never a system fallback. |
| The film's finish (caption colours, headline, grade, second framing, cover, editorial QC blocking) | CONFIG (`config/factual_look.json`, the Owner's look file) + CODE_RULE bounds | `cards.py:1201-1302`; `qc.py:4198-4204` | `config/factual_look.json` → `finish`; out-of-bound values fall back to defaults with a note; a LUT without a licence is dropped; `editorial_qc_blocking` default False, and `settings.editorial_qc_blocking`, when set, wins over the look file (`qc.py:4201-4204`). |
| Legacy render button | CODE_RULE | `router.py:539-589` | Closed film → 409; PRODUCTION → 409 «use the sheet» (and holds a film missing shot plans); failed story gate → 422; any real paid vendor in the plan → 409. |
| Buy one paid step of the sheet | OWNER | `router.py:883-944` | Owner key + the Owner's yes bound to `plan_hash` inside `run_sheet_step` (202 asks, 409 refuses, 200 bought); `allow_over_budget` is the Owner's explicit consent; same `command_id` replays without buying. |
| Disk floor before assembly | CONFIG | `router.py:284-286` | `disk_refusal(storage, settings)` → 409 LOW_DISK. |
| Redo one scene or the sound | OWNER | `router.py:1010-1065` | Still/motion redo needs the `plan_hash` of the shown redo plan; card/audio cost nothing. |
| A take's fate on the contact sheet | OWNER | `router.py:1067-1108` | APPROVED / REJECTED, `final` marks an approval no Director repair replaces. |
| A scene's motion model (or LOCAL_MOVE) | OWNER | `router.py:946-982` | Changes the sheet hash, so an older yes buys nothing. |

## LLM involvement

Summary for the group: **3 LLM call sites of 178 functions** (`director_assignment` 43 lines,
`sound_plan` 121 lines, `research_models` 309 lines: 473 of 5141 function lines, ~9%; the
inventory's 6178 counts the 1037 lines of the nested route handlers twice, once inside
`create_media_router`, which gives ~8%). Every one of them goes through
`app.agents.services.run_agent_task` (directly, or via `app.agents.structured.structured_run`),
so the employee's identity, the policy kernel, the daily token ceiling and the USD budget apply;
a refused run comes back as a run with a BLOCKED status, not an exception
(`agents/services.py:827-856`). Code bounds what each answer may touch: the Director's note is
free text whose effect is re-linted; the sound plan is confined to library ids and three
levels whose loudness the mixer bounds; but the steward's model scores are written as given
(0..1 is the only check) and order `rank_candidates`, which can pick the default model. None of
the three buys media itself.

Shared parsing behaviour (`agents/identity.py:568-639`): before validation, `fit_to_schema` cuts
strings longer than their `max_length` at a word boundary and truncates over-long lists (it does
not clamp numbers), and Literal values are matched whatever their case. `read_structured` tries
every `{` in the text as the start of an object and returns the first one that validates. A
schema whose fields all have defaults (`UrlPlan`, `ModelResearch`) therefore accepts any JSON
object, including a nested one, when the top-level answer is refused (oddity 24).

### 1. `app.media.blocker_repair.director_assignment` (L557)

| Item | Value |
|---|---|
| Speaker | The Director (`agent_for_role(session, "Director")`, `blocker_repair.py:565`); raises `ValueError("Niciun Director activ.")` when none. |
| Gateway | `structured_run` (`blocker_repair.py:579-595`): up to 2 runs; the second only when the first SUCCEEDED but gave no valid object, with the schema refusal quoted or with native thinking; a first run that failed or was blocked is not retried (`agents/structured.py:109-163`, `138-140`). |
| Task type / template | `sheet_repair_assignment` / `sheet-repair-v1`; `max_tokens=1400`; temperature 0.1 (default of `structured_run`). |
| What it asks | Assign the sheet's prompt and missing-shot-plan blockers to `VideoEditor` (owner of `write_shot_prompts`), with concrete natural-language, camera and continuity instructions for every scene; never ask for paid media, funding, credentials or policy changes; financial/config blockers are escalated by the backend (`blocker_repair.py:569-578`). Data: `{title, issues}` inside `wrap_in_inert_boundary(..., "sheet-issues")`. |
| Answer shape | `Assignment` (`blocker_repair.py:551-554`): `note: str` (1..1200; a longer note is cut at a word boundary by `fit_to_schema`, not refused), `repair_prompts: bool` (required), `assign_to_role: str = "VideoEditor"`. |
| What code does with it | Refuses unless `parsed` is not None, the final run's status is SUCCEEDED and `assign_to_role == PROMPT_ROLE` ("VideoEditor", `prompt_agent.py:76`) (`blocker_repair.py:596-598`). The `note` becomes the body of a HANDOFF letter Director → Video Editor (`blocker_repair.py:848-864`) and `repair_context["instructions"]` for `write_shot_prompts` (`blocker_repair.py:882-892`). `repair_prompts` is never read. The routing (who repairs, which issues) is fixed by code: the editor is `agent_for_role(PROMPT_ROLE)` and only PROMPT issues are handed over (`blocker_repair.py:819`, `845`). The Director is asked even when no PROMPT issue is left (oddity 2). |
| Trust | CHECKED_BY_CODE: role pinned by code; the note's text is passed unread to another LLM call (the Video Editor's), and only its effect is verified, by rebuilding and re-linting the sheet (`blocker_repair.py:893-923`). |
| If the model fails / refuses / returns junk | `ValueError` → caught by the generic handler → `_finish(..., "UNRESOLVED", ...)` with «Instrumentul de remediere a eșuat (ValueError)… Directorul păstrează sarcina și reia remedierea automat» (`blocker_repair.py:927-947`). The UNRESOLVED result feeds the back-off and the 5-a-day ceiling (`blocker_repair.py:194-251`); when the 3 newest model runs of the whole studio (any agent) all FAILED with `ProviderHTTPError`, the next scan pauses the repair as LANGUAGE_MODEL_DOWN with an Owner card. A run blocked by the budget or policy kernel is not a provider failure and counts only toward DAILY_LIMIT. |
| Can it lead to spending money | Indirectly. No media is bought here (`blocker_repair.py:1-4`), but a RESOLVED repair queues FILM_CONTINUE in PRODUCTION (`blocker_repair.py:719-720`), whose paid steps are gated by `may_act` and the Owner's rules. Text-model tokens are spent under the budget kernel. |

### 2. `app.media.sound_design.sound_plan` (L379)

| Item | Value |
|---|---|
| Speaker | The Voice Artist (`SOUND_ROLE = "VoiceArtist"`, `sound_design.py:56`), "the studio's sound department" (Lyra per `model_research.py:7`); the code refers to her as "she". |
| Gateway | `structured_run` (`sound_design.py:436-451`), imported lazily; up to 2 runs (the second only after a SUCCEEDED run whose answer did not validate; a failed or blocked first run is not retried, `agents/structured.py:138-140`). |
| Task type / template | `sound_design` / `sound-design-v1` (`sound_design.py:57-58`); `max_tokens=3000` (`sound_design.py:69`); payload trimmed to 14000 chars by `prompt_agent.trim_payload` (`sound_design.py:68`, `372-376`). |
| What it asks | Choose one bed from the Owner's library (or null), a level per scene (`under` default, `soft` where the words must stand alone, `lift` only where there is no narration or a long pause), an ambience only where a scene's audio intent calls for one, fades 0.3-4 s, and `why`/`summary_ro` in Romanian (`sound_design.py:273-298`). The prompt states the mixer's guarantees (20 LU under, lifts only in silences, QC refuses <18 LU). Data: film title/core message, `scene_brief` rows, `library_brief` (beds with moods/bpm/duration, ambiences with tags; no licences) inside `wrap_in_inert_boundary(..., "sound-design")`. Re-plan adds `_REPLAN_INSTRUCTIONS` and `refusal` = measured LU values, reasons, previous plan (`sound_design.py:299-306`, `423-425`). |
| Answer shape | `BoundPlan(SoundPlan)` from `plan_schema` (`sound_design.py:171-228`): `bed: str|None`, `why` ≤400, `scenes: list[ScenePlan]` ≤200 (`scene_index` 1..200, `level` Literal under/soft/lift, lowercased; `ambience: str|None`, "none/null/-/fără" → None; `why` ≤300), `fade_in_seconds`, `fade_out_seconds` (non-numbers/NaN → default; clamped to `BED_FADE_BOUNDS` 0.3..4.0), `summary_ro` ≤600. |
| Checks by code (schema validator) | Bed must be a `music` track id of the loaded library; every ambience an `ambience` track id; scenes named exactly once, none missing, none unknown (`sound_design.py:189-210`). With `previous` (re-plan): identical bed+levels+ambiences refused; any new `lift` refused (`sound_design.py:211-225`). |
| What code does with it | `plan_record` stores it in `production['audio']['plan']` with source/agent/run id (`sound_design.py:505-536`); assembler emits `media.sound_plan_written` (`assembler.py:5843-5852`); `_tracks_of_plan` re-resolves each id against the library at mix time (whose loader already re-hashed every file), dropping a missing track and, on a remix (`made_with`), one whose sha256 differs from the film's record (`assembler.py:5699-5739`); `toolchain.mix_bed` applies LEVEL_GAIN_DB (under 0, soft −6, lift +8 dB) with lifts only inside measured voice silences (`toolchain.py:604-614`, `771-794`). A successful plan is also remembered as an `AGENT_OPINION` memory of the Voice Artist (`sound_design.py:479-490`). |
| Trust | CHECKED_BY_CODE: the plan can only pick from vetted tracks and three levels whose loudness effect is bounded by the mixer and measured by QC (18-22 LU band, `toolchain.py:591`). Acted on as given within those bounds: which track, which scenes are soft or lifted, and whether the film has music at all (`bed: null`). |
| If the model fails / refuses / returns junk | Never raises (`sound_design.py:397-399`). No registry → deterministic plan, reason «niciun model nu a fost întrebat»; no active Voice Artist → «niciun VoiceArtist activ»; exception → «planul nu a putut fi cerut (…)»; no valid plan (two invalid answers, or a single failed/blocked run that `structured_run` does not retry) → «răspunsul nu a respectat forma cerută nici a doua oară» plus the run's error detail (`sound_design.py:410-478`; oddity 27). The deterministic plan (`sound_design.py:324-369`) keeps the previous bed on a re-plan (`sound_design.py:400-409`). The record says which plan was used (`source`: `voice_artist` / `deterministic`). |
| Can it lead to spending money | No media spend (local ffmpeg mix). Text-model tokens only, under the budget kernel. |

### 3. `app.media.model_research.research_models` (L205)

Two `run_agent_task` calls in one function (no `structured_run`, so no automatic retry); the
answers are parsed with `app.agents.identity.parse_structured` (= `read_structured`, which
fits the object first and tries every `{` in the text). Because every field of `UrlPlan` and
`ModelResearch` has a default and extras are ignored, any JSON object in the answer validates
(oddity 24).

| Item | Value |
|---|---|
| Speaker | The steward of the purpose (`STEWARDS`, `model_research.py:69`): `VideoEditor` (Kael) for `video` and `image`, `VoiceArtist` (Lyra) for `voice`. |
| Task type / template | `research_models` / `model-research-v1` (`model_research.py:66-67`); both runs `temperature=0.1`, `emit_message=False`. |
| Run 1 — which pages (L297) | Prompt `_PLAN_INSTRUCTIONS` (`model_research.py:109-117`, "up to 5 pages", while the module docstring says three, `model_research.py:9`) + the vendor docs index (≤20000 chars, `INDEX_CHARS`) inside an inert boundary; `max_tokens=1500`. Answer `UrlPlan{urls: list[str] ≤6}` (`model_research.py:80-82`; a longer list is truncated to 6 by `fit_to_schema`). |
| Code checks on run 1 | Each URL kept only if it starts with `https://` and its host is in `vendor_hosts(kind)` (the catalogue docs host and its parent domains, `model_research.py:172-182`), de-duplicated; at most `MAX_PAGES=5` fetched, the index URL itself skipped (`model_research.py:310-323`). Fetches go through `SourceRetriever(RetrievalPolicy(hosts, max_text_chars=40000))` (`model_research.py:280`); each page cut to 12000 chars. The run's status is not read: a failed run, an unparsable answer or an object without `urls` just leaves the index page as the only evidence. |
| Run 2 — the judgement (L337) | Prompt `_JUDGE_INSTRUCTIONS` with the studio's priority line (`STUDIO_PRODUCTION_PRIORITY`: premium / balanced / thrifty, `model_research.py:148-169`), the account's candidate list (≤12000 chars of JSON), and each fetched page in its own inert boundary; `max_tokens=6000`. The prompt asks, for every purpose including voice and image, for a recommendation "for the studio's short vertical videos" compared on "prices per second" (`model_research.py:132-135`). Answer `ModelResearch{models: list[ModelNote] ≤80, recommendation: {remote_id, reason ≤1500} | None}`; `ModelNote` = `remote_id`, `quality_score`/`reliability_score`/`latency_score` (0..1, default 0.5; out of range refuses the object, not clamped), `price_usd ≥0 | None`, `price_unit` ≤60, `notes` ≤600, `evidence_url` ≤1000 (`model_research.py:85-106`; over-long strings and lists are cut by `fit_to_schema`). |
| What code does with it | For each note whose id is a listed candidate: `update_resource_metadata` writes `capabilities = {quality_score, reliability_score, latency_score, notes, judged_by}` (replacing the whole dict, oddity 11) and `pricing = {<unit key>: price, "unit": ...}` when priced, `pricing = {}` when not (which wipes the recorded prices, oddity 10), with source = the note's `evidence_url` when it starts with `https://` (any host; not checked against the vendor's) or the docs URL (`model_research.py:375-413`). The unit key comes from words in `price_unit` and the number is never rescaled (`model_research.py:185-193`, oddity 26). `stamp_price` keeps a BILLED price over a documented one for keys both name (`integrations/lifecycle.py:152-177`). Price moves ≥ `price_change_alert_percent` → `economy.accountant.price_change_alert`, an ESCALATE letter to the Owner (`model_research.py:404-415`; `economy/accountant.py:657-700`). Recommendation used only if it is a listed candidate, else — also when there is none — `rank_candidates(...)[0]`, re-ranked after the new scores were written; must pass `production_resource`; written as the default (`save_production`, optimistic `expected_version`) only when `allow_production_override` is true (or no config row) and it differs from the current one (`model_research.py:417-454`). A STATUS letter from the steward (`to_agent_id=None`, not to the Owner) and `media.model_research_recorded` close the run (`model_research.py:456-502`). |
| Trust | CHECKED_BY_CODE overall: pages restricted to the vendor's hosts; unknown ids ignored; billed prices protected; the default changes only where the Owner left it unlocked and only to a usable listed model. Not checked by code: the score values (0..1 is the only check) and the price magnitudes, which `production_policy.rank_candidates` reads directly to order the models (`production_policy.py:357-378`) — and that order picks the default when the recommendation is missing or not a candidate, and drives `strategy: auto`. |
| If the model fails / refuses / returns junk | Docs index unreachable → letter «documentația … nu a putut fi citită» and `SKIPPED` (`model_research.py:281-291`). Run 2 with no JSON object at all (e.g. a failed run, empty text) → `ModelResearchError` (nothing recorded); `research_all` turns it into `SKIPPED` for that purpose (`model_research.py:353-359`, `540-546`). Run 2 whose top-level object the schema refuses (one score of 1.2, a note without `remote_id`) is not an error: `read_structured` moves on and the first nested object (a `ModelNote`) validates as an empty `ModelResearch`, so nothing is annotated and `rank_candidates()[0]` is reported as "recommended" and may be saved as the default (oddity 24). A `ValueError` from a metadata write (version moved) is logged and skipped per model (`model_research.py:412-413`); a refused default save is logged (`model_research.py:453-454`). |
| Can it lead to spending money | Indirectly: it changes the recorded prices, the capability scores and possibly the default model that later paid steps buy. The research itself spends text-model tokens (2 runs per purpose, up to 3 purposes a week) and free HTTPS GETs. |

### Functions in scope that reach the LLM indirectly

Paths from `docs/project/backend_map/callgraph.json` (static, name-based). "Runtime" notes what
the arguments actually allow.

| Function | Reaches the LLM through | Runtime note |
|---|---|---|
| `blocker_repair.process_sheet_repair` (L727) | `director_assignment` (Director); `prompt_agent.write_shot_prompts` → `build_visual_bible` (Video Editor); `sheet_story_repair.repair_story` → `factual.agent_pipeline.agent_write_script` (Script Writer) and `factual.story_review.review_story` → `_ask_director` | Runs from the worker task `FILM_SHEET_REPAIR` (`workflows/worker.py:445-457`). |
| `model_research.research_all` (L530) | `research_models` | Weekly job and the Owner's Settings button. |
| `router._assemble_step` (L266) | `shooting_sheet.run_assemble_step` → `qc.evaluate_media_qc` → `picture_qc.evaluate_pictures` / `judge_clip`; → `assembler.assemble_from_takes` → `assemble_video_job` → `film_mix` → `sound_plan`; redo ladder → `picture_qc.judge_still`, and since 20abffd `stills_stage._settle_pending` → `_director_looks` → `fix_check.director_second_look` → `second_look._look` (the Director's second look, `second_look.py:653`) | Registry passed from `app.state` (`router.py:300`). |
| `router.start_render` (L523) | `qc.evaluate_media_qc` → `picture_qc.evaluate_pictures`/`judge_clip`; `assemble_video_job` → `film_mix` → `sound_plan` | Refused in PRODUCTION before any of it (`router.py:549-552`); in TEST it passes the real `app.state.registry` to the mix and to QC (`router.py:598`, `702`), so the Voice Artist and the vision QC model are asked (text/vision tokens) even though media vendors are fakes. |
| `router.post_adopt_existing_files` (L763) | `rehearsal.rehearse` → `evaluate_media_qc`; → `assemble_from_takes` → `film_mix` → `sound_plan` | Static only: `rehearse` passes `registry=None` to QC (`rehearsal.py:1265`) and none to the assembly (`rehearsal.py:1238-1247`), so the sound plan is the deterministic one and QC has no vision model. |
| `router.post_sheet_step` (L884) | `_assemble_step` paths above; `run_sheet_step` → `stills_stage.run_stills_stage` → `picture_qc.judge_still`; `run_sheet_step` → `assembler.run_motion_step` → `_check_shot` → `judge_clip`; since 20abffd also the Director's second look before a still re-roll (`stills_stage._settle_round` → `_director_looks`, `stills_stage.py:1143-1149`) or a clip retry (`_check_shot` → `fix_check.shot_second_look`, `assembler.py:10334-10346`) → `second_look._look` | Owner press. Her look buys nothing; a still or clip she lets stand is kept and nothing more is bought for it. |
| `router.post_scene_redo` (L1011) | `assembler.redo_scene` → `settle_stills` → `judge_still`; `_paid_redo` → `run_motion_step` → `_check_shot` → `judge_clip`; `_free_redo` → `repair_audio` → `_replan_sound` → `sound_plan`; since 20abffd the Director's second look (`second_look._look`) through `settle_stills` → `_settle_pending` → `_director_looks`, through `_check_shot` → `fix_check.shot_second_look`, and in the paid still redo through `_redo_still` → `_StillRedoBuyer.run` → `stills_stage._settle_round` (`assembler.py:16571`; the call into `_StillRedoBuyer.run` is not on the static graph) | Owner press. Her look comes before any re-roll or retry inside the redo is bought. |
| `router.write_prompts` (L1147) | `prompt_agent.write_shot_prompts` → `build_visual_bible` | Owner press. |
| `router.evaluate_qc_for_storyboard` (L1386) | `qc.evaluate_media_qc` → `picture_qc.evaluate_pictures` / `judge_clip` | Owner press. |
| `blocker_repair._continue_repaired_film` (L613) | Not in the static graph: it queues a `FILM_CONTINUE` task (`services.queue_film_continue`), whose worker handler walks the film on (paid steps under `may_act`, picture QC, the Director's repair loop) | Runs only after a RESOLVED repair, in PRODUCTION (`services.py:658-660`). |

No other model call hides in this group: `cards`, `film_close`, `mode_guard`, `speaker_voices`,
`music_library` and `answered_letters` import no provider or agent gateway; the router's other
handlers pass no registry (`create_storyboard_from_script`, `post_take_decision`,
`post_character_reference_set` buys images from a media vendor, not from a language model).

## Hard rules and limits

### Sheet repair (`blocker_repair.py`)

| Constant / rule | Value | Where |
|---|---|---|
| `REPAIR_TASK` | `FILM_SHEET_REPAIR` | L44 |
| `MAX_SAME_ISSUES_PER_DAY` | 5 UNRESOLVED attempts per `issue_key` in the window | L62, L235 |
| `BACKOFF_BASE_SECONDS` | 300 s before the 2nd retry, doubling | L64, L247 |
| `BACKOFF_MAX_SECONDS` | 6 h (21600 s) | L66, L248 |
| Effective waits | n=1: 0 s; n=2: 300 s; n=3: 600 s; n=4: 1200 s; n=5: PAUSED | L247 (arithmetic) |
| `MODEL_RUNS_READ` | 3 latest `AgentRun` rows all FAILED with `ProviderHTTPError` → LANGUAGE_MODEL_DOWN | L68, L87-103 |
| Attempt window start | max(now − 24 h, Owner's latest retry event, `STUDIO_STARTED_AT`) | L206-211, L73 |
| `issue_key` | sha256 of the sorted set of (kind, code, scene_index) | L166-182 |
| Attempt fingerprint | sha256 of `[sheet_hash, issues]` | L445-447 |
| Task queueing | priority 6, `max_attempts=1`, idempotency key `sheet-repair-{id}-{fingerprint}-{date}-{attempt}` | L490, L533-547 |
| Lease for story and prompt repair | `film_purchase_lease(..., ttl_seconds=3600)` steps `story_repair` and `prompt_repair` | L787-789, L830-832 |
| Balance rule in blockers | needed = the footer's `balance_needed_credits[step]`, else `ceil(round(cost_credits × 1.15, 6))` (`DEFAULT_MARGIN`, not `margin_of(settings)`) | L367-372; `balance_rule.py:38`, `45-48`, `52-58` |
| Director answer | `note` 1..1200 chars; `max_tokens=1400` | L552, L594 |
| Scan scope | 30 newest storyboards in APPROVED / NEEDS_SHOT_PLAN / RENDERED | L968-976 |

Repair result state machine (written in `repair_result` on the report letter and in
`media.sheet_repair_finished`):

| Status | Set when | Where |
|---|---|---|
| `CLEAR` | the sheet has no issues (nothing queued) | L441-443 |
| `REVISED` | a story repair already wrote a replacement storyboard (at submit time, or returned by `repair_story` inside the task, which then submits the replacement's sheet) | L438-440, L802-817; L156-159, L277 of `sheet_story_repair.py` |
| `BACKING_OFF` / `PAUSED` | `_repair_guard` refuses a new attempt | L483-488 |
| `BLOCKED` | `allowed()` false | L736-737 |
| `STALE` | film closed; sheet hash changed before or during the repair | L742-748, L761-769, L790-798, L833-841 |
| `UNRESOLVED` | another lease holds the film; `repair_story` itself returned UNRESOLVED; a PROMPT issue remains; any exception | L778-786, L809-817 (`sheet_story_repair.py:219-244`), L821-829, L913-917, L927-947 |
| `WAITING_OWNER` | only OWNER/STORY issues remain (turned into STALE if the film closed meanwhile) | L913-917, L653-656 |
| `RESOLVED` | no issue remains; or a later scan finds the sheet clear | L913-917, L1008-1016 |

### Sound plan (`sound_design.py`, enforced with `toolchain.py`)

| Constant / rule | Value | Where |
|---|---|---|
| `SOUND_ROLE` / task / template | `VoiceArtist` / `sound_design` / `sound-design-v1` | `sound_design.py:56-58` |
| `MAX_PAYLOAD_CHARS` / `MAX_TOKENS` | 14000 / 3000 | `sound_design.py:68-69` |
| Levels | `under` 0 dB, `soft` −6 dB, `lift` +8 dB | `toolchain.py:604` |
| Bed under the voice | 20 LU; QC band 18-22 LU | `toolchain.py:590-591`; `sound_design.py:667` |
| Lift only in silences | ≤ −35 dBFS for ≥ 0.8 s, clear of words by 0.1 s, segment ≥ 0.3 s | `toolchain.py:610-612`, `786-792` |
| Fades | default in 0.3 s, out 0.8 s; plan clamped to 0.3..4.0 s | `toolchain.py:592-593`, `614`; `sound_design.py:97-107` |
| Scenes per plan | ≤200; `scene_index` 1..200; each exactly once | `sound_design.py:78`, `116`, `202-210` |
| Re-plan | must change; no new lift | `sound_design.py:211-225` |
| Attempts | up to 2 (`structured_run`; a failed or blocked first run is not retried) then deterministic | `agents/structured.py:109-154`, `138-140`; `sound_design.py:461-478` |

### Model research (`model_research.py`)

| Constant / rule | Value | Where |
|---|---|---|
| `PURPOSES` | voice, image, video (in that order) | L70 |
| `MAX_PAGES` / `PAGE_CHARS` / `INDEX_CHARS` | 5 / 12000 / 20000 | L71-73 |
| Retriever text cap | 40000 chars, vendor hosts only | L280 |
| Account listing in prompt | first 12000 chars of JSON | L333 |
| Runs | plan `max_tokens=1500`, judge `max_tokens=6000`, temperature 0.1 | L297-309, L337-352 |
| Schedule | every 7 days, first run 2 h after start, CATCH_UP, not in demo mode | `main.py:526-536` |
| Price alert threshold | `price_change_alert_percent` default 10.0 (0.1..1000) | `config.py:446`; L408-411 |
| Price keys | unit text with "char" → `per_1k_characters_usd`; "image" or purpose image → `per_image_usd`; "second"/"sec" or purpose video → `per_second_usd`; else `price_usd`; the number is stored unconverted | L185-193, L381-385 |

### Mode guard (`mode_guard.py`)

| Constant / rule | Value | Where |
|---|---|---|
| `MODE_STOP_EVENT` | `media.paid_step_stopped_by_mode` (recorded once per step) | L44, L219-250 |
| `MODE_CHANGED_EVENT` | `owner.autonomy_mode_changed` (read to word the stop) | L46, L120-134 |
| Owner press passes | `OWNER_PRESS_PASSES = {BLOCKED_MODE, NEEDS_APPROVAL}` | `media/services.py:1821`; L217 |
| `by_yes` | the starting verdict was allowed with an `approval_id` | L202 |
| Kernel read | `may_act(..., ask_owner=False)` then `session.rollback()` | L53-77 |
| Clock in the stop sentence | `Europe/Bucharest` default | L50, L101-117 |

### Film close (`film_close.py`)

| Constant / rule | Value | Where |
|---|---|---|
| `CLOSABLE_STATUSES` | DRAFT, APPROVED, NEEDS_SHOT_PLAN | L65 |
| `LIVE_TASK_STATUSES` | CLAIMED, RUNNING (QUEUED/RETRYING do not refuse) | L72 |
| `LIVE_GPU_STATUSES` | OPENING, OPEN, CLOSING | L74 |
| `LIVE_RENDER_STATUSES` | PENDING, RENDERING with no `finished_at` | L77, L220-228 |
| Close lease | step `close`, `ttl_seconds=600` | L559-560; `shooting_sheet.py:1907` |
| Command | `CloseFilmCommand{schema_version: 1, command_id: UUID, note ≤500}`, extra forbidden | L112-120 |
| Refusal codes | FILM_RENDERED, SERIAL_EPISODE, NOT_CLOSABLE, FILM_BUSY (and COMMAND_REUSED at the route) | L85-87, L159-251; `router.py:878-881` |

### Picture cards and finish (`cards.py`)

| Constant / rule | Value | Where |
|---|---|---|
| Frame | 1080 x 1920 at 24 fps | L44-45, L65 |
| `SAFE_RECT` | (90, 300, 990, 1540) | L50 |
| `CAPTION_BAND_TOP` | 1320 (content ends above the burnt captions) | L56 |
| `MAX_BARS` | 4 | L61 |
| Bar timing | start 0.3 s, stagger 0.6 s, grow 1.0 s, hold 0.3 s; min card 1.0 s | L87-95 |
| `MIN_TEXT_SIZE` | 36 px | L104 |
| `MAX_SHORT_BLACK_SECONDS` | 1.5 s; longer → closing card on the hook still, or refused | L111, L906-921 |
| Closing card | darken 0.5, blur 3, push 8% | L114-116 |
| Still background | darken 0.42, blur 30, luma cap 110 | L99-101 |
| Fonts | Inter Bold / Regular with pinned SHA-256 | L74-83 |
| Encode | x264 High, CRF 4, BT.709 limited range; ffmpeg timeout 600 s (card), 120 s (cover) | L993-1016, L1026, L1176 |
| Cover | hook 104→56 px, ≤4 lines, band alpha 0.45 | L1056-1060 |
| Finish bounds | shadow_opacity 0..1, shadow_px 0..4, headline 0.5..4 s, grade strength 0..1, grain 0..10, second framing 2..10 s and zoom 1.12..1.2 | L1229-1237 |
| `editorial_qc_blocking` default | False | L1225 |

### Music library, voices, letters, router

| Constant / rule | Value | Where |
|---|---|---|
| Track kinds | music, ambience | `music_library.py:126` |
| Track admission | `commercial_ok is True`, licence text, file inside library folder, 64-hex sha256 equal to the file's | `music_library.py:203-220` |
| Duplicate ids | later entries refused «id repetat» | `music_library.py:266-267` |
| `SPEAKER_GAP_SECONDS` | 0.3 s between speakers | `speaker_voices.py:52` |
| Voice cast file | `config/serial_voice_cast.json`, used only when `use_until_the_owner_binds` is true | `speaker_voices.py:48`, `94-101` |
| Letter resolution text | truncated to 600 chars | `answered_letters.py:154` |
| Router auth | every route `Depends(require_owner)` (bearer = `owner_token`) | `router.py:319`; `security.py:60-68` |
| Router parameters | storyboard/character ids 36 chars; `motion_scenes` 0..24; `model` ≤200; `step` ≤20; `scene_index` 1..200; redo `plan_hash` 64 hex; notes ≤500 | `router.py:330`, `526-527`, `887`, `950`, `204-206` |

## Modules

### `app.media.blocker_repair` — backend/app/media/blocker_repair.py (1041 lines)

Purpose: durable shooting-sheet repair: a worker scan discovers blocked sheets, a Director
assignment routes prompt work to the Video Editor, the real tools run, and the sheet is re-read
to verify. No media generation, funding, policy edit or publication happens here
(`blocker_repair.py:1-5`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_language_model_failing` | 87 | Returns the last error when the 3 newest `AgentRun` rows (any agent) all FAILED with `ProviderHTTPError`. | Tell a dead provider from one bad answer (2026-10-03). | CODE_RULE |
| `_latest_retry` | 106 | Timestamp of the newest `media.sheet_repair_retry_allowed` event for the sheet. | The Owner's retry resets the window. | CODE_RULE |
| `allow_repair_retry` | 119 | Owner-only; records `media.sheet_repair_retry_allowed` once per correlation id. | Owner's accept on the pause card (2026-10-03; ADR-APPLY-THROUGH-OWNER-COMMANDS `16_DECISION_LOG.md:4140`). | OWNER |
| `issue_key` | 166 | Hash of the set of (kind, code, scene). | "Same blockers" independent of wording (2026-10-11, f06808c9). | CODE_RULE |
| `_same_blockers` | 185 | Compares by `issue_key`, else by the pre-2026-10-11 fingerprint. | Backward compatibility of queued tasks. | CODE_RULE |
| `_repair_guard` | 194 | Returns PAUSED (LANGUAGE_MODEL_DOWN / DAILY_LIMIT) or BACKING_OFF, or None. | The "not to infinity" safety. | CODE_RULE |
| `_pause_letter` | 259 | Card (`sources.sheet_repair_paused`, asked on every paused scan) + ESCALATE letter to the Owner only for LANGUAGE_MODEL_DOWN, else STATUS to the Director; the letter is skipped when any open pause letter of the sheet exists, whatever its cause. | 2026-10-10: non-account pauses are the studio's business. | CODE_RULE |
| `_close_pause_letters` | 298 | Withdraws pause cards (`sources.sheet_repair_resumed`) and resolves open pause letters. | A resumed repair clears its own notes. | CODE_RULE |
| `allowed` | 314 | Policy/stop/shutdown/safe-mode gate. | Product agents never bypass the Owner's policy. | CODE_RULE + OWNER |
| `sheet_issues` | 321 | Converts a built sheet into PROMPT / STORY / OWNER issues (see table above). | One reading of "what blocks this film" for the repair and for cards (`decisions/sources.py:941-966`). | CODE_RULE |
| `submit_sheet_issues` | 437 | Returns REVISED/CLEAR, an existing open task (or a same-fingerprint task already RESOLVED/WAITING_OWNER), or the guard (writing the pause letter/card when PAUSED); else withdraws the sheet's pause cards and letters (`_close_pause_letters`), writes the «Blocaje foaie: …» REQUEST_REVIEW letter to the Director and enqueues `FILM_SHEET_REPAIR`. | Idempotent hand-off of a blocked sheet; a report survives a crash between commit and enqueue (L494). | CODE_RULE |
| `director_assignment` | 557 | **LLM call site** (Director); see "LLM involvement". | The Director assigns work; the backend escalates money/config. | LLM_CHECKED_BY_CODE |
| `_film_title` | 602 | The film's title (or short id) for Owner letters. | Owner knows films by title (2026-10-03). | CODE_RULE |
| `_continue_repaired_film` | 613 | Queues FILM_CONTINUE (cause `sheet_repaired`) in the repair's transaction. | 2026-10-11: a RESOLVED film otherwise waited for the next morning. | CODE_RULE |
| `_finish` | 642 | Writes `repair_result`, resolves letters on RESOLVED, posts STATUS (Video Editor → Director), ESCALATE «Foaia necesită intervenție: <title>» to the Owner on WAITING_OWNER, queues the continuation, emits `media.sheet_repair_finished`. | Single place where an attempt ends, in one transaction. | CODE_RULE |
| `process_sheet_repair` | 727 | The worker handler: gate → closed? → idempotent previous result → hash check → lease (`story_repair`) → `repair_story` (a failed story review, or the codes `SCENE_TOO_LONG` / `KIND_MISMATCH` / `CARD_INVALID`, rewrite the story through the Script Writer and the Director's review; its REVISED/UNRESOLVED ends the task) → `director_assignment` → if PROMPT issues: lease (`prompt_repair`) → HANDOFF letter + `media.sheet_repair_plan_saved` → `write_shot_prompts` → re-lint → `_finish`. 221 lines. | Verified outcome, never a conversational success (L928). | CODE_RULE orchestrating LLM steps |
| `scan_sheet_issues` | 950 | Resolves legacy `sheet_repair_limit` letters; scans 30 films; submits blocked sheets; with live reads, marks a previously unresolved repair RESOLVED when the sheet is now clear. | A worker scan, not an open page, discovers work (L4). | CODE_RULE |
| `repair_status` | 1022 | Latest repair task + result for the sheet page. | Shown as `sheet["remediation"]` (`router.py:851-853`). | CODE_RULE |

Helpers: `_when` (ISO → aware datetime).

Data read/written: `AgentMessage` (reports `shooting_sheet_blockers`, work `shooting_sheet_repair_work`, results `sheet_repair_result`, pause `sheet_repair_paused`, Owner escalation `sheet_repair_owner`), `TaskQueueItem` (`FILM_SHEET_REPAIR`, FILM_CONTINUE via `services.queue_film_continue`), `DomainEvent` (`media.sheet_repair_retry_allowed`, `media.sheet_repair_finished`, `media.sheet_repair_plan_saved`), `AgentRun` (read), `Storyboard`, `OwnerPolicy` (read). Owner decision cards via `app.decisions.sources`.

External calls: none to media vendors. The sheet build with `read_live=True` reads the vendor balance (free) inside `shooting_sheet.build_sheet`. Text-model calls via the repair tools.

### `app.media.sound_design` — backend/app/media/sound_design.py (698 lines)

Purpose: the sound department's plan for a film's music (bed, level per scene, ambience,
fades), asked of the Voice Artist and bounded by the library, the mixer and QC; the
deterministic plan when the model is absent or fails (`sound_design.py:1-26`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `ScenePlan._lower`, `_no_ambience` | 85, 90 | Normalise level case; "none"-like ambience → None. | Tolerate model wording. | CODE_RULE |
| `_fade` | 97 | Number → clamped to `BED_FADE_BOUNDS`; junk → default. | The plan may not ask impossible fades. | CODE_RULE |
| `SoundPlan` (+ `_no_bed`, `_fade_in`, `_fade_out`, `level_of`, `lifts`, `level_counts`) | 110 | The plan schema and readers. | Shape of the answer. | CODE_RULE |
| `_previous_shape` | 156 | Refused plan reduced to bed + {scene: (level, ambience)}. | Compare a re-plan with the refused one. | CODE_RULE |
| `plan_schema` | 171 | Builds `BoundPlan` bound to the library and the film's scenes (and the refused plan). | Refuse ids the library lacks, missing/duplicate scenes, unchanged re-plans, new lifts. | CODE_RULE |
| `scene_brief` | 234 | One scene for the brief: index, purpose, kind, narration, seconds, audio intent. | What the Voice Artist reads. | CODE_RULE |
| `library_brief` | 250 | Beds (moods, bpm, duration) and ambiences (tags); no licences. | Only usable tracks are offered. | CODE_RULE |
| `deterministic_plan` | 324 | `choose_bed` (or the kept bed), ambience by `choose_ambience`, every scene "under", default fades, Romanian summary. | A film is never without its mix. | CODE_RULE |
| `sound_plan` | 379 | **LLM call site** (Voice Artist); see above. | Owner 2026-10-11 music rule. | LLM_CHECKED_BY_CODE |
| `plan_record` | 505 | The record kept in `production['audio']['plan']`, with each scene's start/seconds. | Provenance: who planned, how, attempts, refusals. | CODE_RULE |
| `plan_from_record` | 539 | Reads a stored plan back (levels outside the three → "under"). | A remix keeps the plan the film was mixed with. | CODE_RULE |
| `levels_for_mix` | 566 | The level list `toolchain.mix_bed` takes. | Mixer input. | CODE_RULE |
| `changes_between` | 599 | Romanian list of what a re-plan changed. | The replan record shows whether a loop repeats. | CODE_RULE |
| `plan_event_payload` | 627 | Payload of `media.sound_plan_written`. | Event record. | CODE_RULE |
| `mix_refusal` | 656 | Measured LU values, QC reasons, band [18, 22], report id. | What a re-plan is told. | CODE_RULE |
| `replan_record` | 673 | One entry of `production['audio']['replans']`. | Visible loop history (`REPLAN_EVENT`). | CODE_RULE |

Helpers: `_ids` (track ids of a kind), `_payload` (trimmed JSON), `_plan_words` (plan as quoted
in a refusal).

Data read/written: no tables directly except the Voice Artist's memory (`remember`,
`AGENT_OPINION`, `sound_design.py:479-490`). Events `media.sound_plan_written` /
`media.sound_plan_replanned` are emitted by the assembler with payloads from here
(`assembler.py:5843-5852`, `7838-7846`). External calls: none (the mix is local ffmpeg).

### `app.media.music_library` — backend/app/media/music_library.py (318 lines)

Purpose: the Owner's licensed music library, the only source of beds and ambiences
(`music_library.py:1-23`; spec `23_CONTENT_RIGHTS_PLATFORM_POLICY.md:18-26`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `library_path` | 45 | Env `STUDIO_MUSIC_LIBRARY` → Owner library (git-ignored `config/music/`) if it exists → shipped empty library. | A buyer's music is their own choice; the Owner's files are never committed (2026-10-11). | CONFIG |
| `Track.record` | 151 | What a film records about a track (id, file name, sha256, licence, commercial_ok, redistributable, attribution). | Rights provenance on every film. | CODE_RULE |
| `_checked` | 193 | Admits or refuses one entry with a Romanian reason (a missing `kind` reads as "music"). | A track is never guessed at. | CODE_RULE over CONFIG data (the Owner's library file) |
| `load_library` | 243 | Loads and checks every entry; missing file → empty library; unreadable → empty with a refusal row. | Never stops a film. | CODE_RULE |
| `moods_of` | 274 | Counts words starting with each mood's stems (EN + RO). | Deterministic mood reading. | CODE_RULE |
| `choose_bed` | 290 | Music track maximising mood hits; ties by sha256(seed:id). | Successive films do not all carry the same track. | CODE_RULE |
| `choose_ambience` | 307 | Ambience whose tag prefixes a word of the scene's `audio_intent`; smallest id wins. | Deterministic ambience. | CODE_RULE |

Helpers: `Library.entry`, `_sha256` (1 MiB chunks), `_strings`, `_order`.

Data read: the library JSON and track files. Readers outside: `assembler.film_mix`,
`remix_film_sound`, `_replan_sound`, `qc.audio_mix_verdict`, `decisions.seed._music_cards`,
`decisions.services._music_library_has_music`, and `decisions.sources` (grep).

### `app.media.speaker_voices` — backend/app/media/speaker_voices.py (295 lines)

Purpose: split a scene's script lines into takes per speaker and resolve a voice per take
(`speaker_voices.py:1-30`). Nothing synthesises here; choosing a voice id is configuration.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `load_voice_cast` | 67 | Reads `config/serial_voice_cast.json`; `voices` empty unless `use_until_the_owner_binds` is true; `proposed` always kept for the page. | The Owner's default-voice proposal (2026-09-24 S7, `16_DECISION_LOG.md:3968`). | CONFIG |
| `speaker_segments` | 109 | Consecutive lines of one speaker joined into one take; narrator lines (no speaker) are their own takes. | One voice per speaker. | CODE_RULE |
| `speaker_voice` | 147 | Precedence: identity-locked voice (a bound `voice_id` plus a `voice` identity lock, resolved by `production_policy.resolve_purpose`, not re-validated) → Owner binding if `_validate` passes → cast proposal if the narrator has a connection whose kind matches the file's `provider_kind` (any kind when the file names none) and `_validate` passes → narrator; notes why each level was skipped. | Locks and the Owner's binding always win; proposals name the Owner's catalogue only. | CODE_RULE over OWNER/CONFIG |
| `plan_speakers` | 221 | Adds `speakers` (takes + voices) to each scene of a resolved plan; leaves a scene whole when lines and narration differ. | The guard against stale lines. | CODE_RULE |

Helpers: `_words` (whitespace normalise), `_recorded` (voice record with `speaker_source`).

Data read: `ScriptDraft.scenes_json` lines, `StoryboardScene`, `CharacterBible`
(`voice_binding_json`, `identity_locks_json`), `ChannelRecord`, `Integration`. Called by
`media.factory.render_plan`; `speaker_segments` also by `story.review.beat_clip_seconds`.

### `app.media.model_research` — backend/app/media/model_research.py (546 lines)

Purpose: the stewards read vendor documentation (fetched by the studio, restricted to the
vendor's own hosts), score the account's models and recommend one; the studio records the
scores and prices where the production hierarchy reads them and changes the default only where
the Owner allowed it (`model_research.py:1-22`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_priority_line` | 166 | Priority sentence for premium / balanced / thrifty (default premium). | The recommendation serves the studio's standing priority. | CONFIG |
| `vendor_hosts` | 172 | Docs host from `integrations.catalog.CATALOG[kind]["docs"]` plus its parent domains. | The only hosts any fetch may reach. | CODE_RULE |
| `_price_key` | 185 | Unit text/purpose → `per_1k_characters_usd` / `per_image_usd` / `per_second_usd` / `price_usd`; the key only, the number is not rescaled (oddity 26). | Store prices under the keys accounting reads. | CODE_RULE |
| `_fetch` | 196 | One retriever fetch, `None` on `RetrievalError`/`OSError`. | A dead page never aborts research. | CODE_RULE |
| `research_models` | 205 | **LLM call site** (steward; two runs); see above. 309 lines. | Choose models by evidence. | LLM_CHECKED_BY_CODE (pages, ids, billed prices, default lock); LLM for the score values |
| `_report` | 516 | STATUS letter from the steward to the Director's inbox (`to_agent_id=None`, not to the Owner). | Everything said in a letter. | CODE_RULE |
| `research_all` | 530 | Runs every purpose; `ModelResearchError` → `SKIPPED`. | Weekly job and the Owner's button. | CODE_RULE |

Data read/written: `ServiceSelection`, `Integration`, `ProviderResource` (capabilities,
pricing via `update_resource_metadata`), `MediaProductionConfig` (via `save_production`),
`AgentMessage`, `DomainEvent` (`media.model_research_recorded`;
`provider.resource_metadata_updated` from discovery). External calls: HTTPS GETs to the
vendor's documentation hosts (free).

### `app.media.mode_guard` — backend/app/media/mode_guard.py (266 lines)

Purpose: the Owner's policy re-read before every vendor request of a paid step bought unasked
(`mode_guard.py:1-30`; spec 51 «Lowering autonomy»).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_verdict` | 53 | `may_act(..., ask_owner=False)` in a session rolled back. | Read the kernel without writing a question or spending a yes. | CODE_RULE |
| `unasked_refusal` | 80 | The kernel's outright refusal, or None (NEEDS_APPROVAL is not a refusal). | No «top up the account» card for a step MANUAL would refuse anyway. | CODE_RULE |
| `_local_clock` | 101 | UTC stamp → "HH:MM" in the Owner's zone (unknown zone → "HH:MM UTC"). | The stop sentence names the time of the mode change. | CODE_RULE |
| `_mode_change_since` | 120 | Newest `owner.autonomy_mode_changed` since the step started. | Explain a stop by the Owner's own change. | CODE_RULE |
| `stop_words` | 137 | Romanian sentence: mode lowered at HH:MM, or the kernel's reason; ends with «ce s-a cumpărat până atunci rămâne; restul nu s-a cumpărat.» | The Owner reads why buying stopped. | CODE_RULE |
| `PurchaseGuard.after` | 179 | Builds the guard from the starting verdict (`by_yes`). | Remember whether the Owner's yes covers this plan. | CODE_RULE |
| `PurchaseGuard._goes_on` | 208 | ALLOWED; or `by_yes` and NEEDS_APPROVAL; or not unasked and status in `OWNER_PRESS_PASSES`. | Do not stop what `may_act` itself allows (ADR-POLICY-READ-PER-REQUEST). | CODE_RULE |
| `PurchaseGuard.stop_reason` | 219 | None while the next request may go; else records the stop once and keeps returning the same sentence. | 2026-10-04 LHC: 108 credits bought after MANUAL. | CODE_RULE (Policy Kernel) |
| `PurchaseGuard._record` | 252 | Appends `media.paid_step_stopped_by_mode`. | Audit. | CODE_RULE |

Users (callgraph + grep): `stills_stage.run_stills_stage` (L2002, L2050, L2159),
`assembler.run_motion_step` (L11621, L11723, L11871, L12012), `assembler._redo_still`
(L16011, L16106; and `_StillRedoBuyer.run`, L16385), `shooting_sheet._run_sheet_step` (L3352), `gpu_batch` (L354-367),
and `providers/runpod/gpu_session.py` (L77, L209, the guard passed into a GPU session).

### `app.media.film_close` — backend/app/media/film_close.py (700 lines)

Purpose: «Închide filmul», the Owner's command that ends one unfilmed film: REJECTED through
`runbook.stages.close_film_books`, every question about it withdrawn, nothing more bought
(`film_close.py:1-32`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_title` | 139 | Title without "Storyboard: ". | Owner-facing wording. | CODE_RULE |
| `_rendered` | 145 | Whether a COMPLETED render exists. | Rendered films end through QC/viewing/publication. | CODE_RULE |
| `_unclosable` | 159 | FILM_RENDERED / SERIAL_EPISODE / NOT_CLOSABLE refusals. | REJECTED would not stop a rendered film's publication; a serial day needs its episode. | CODE_RULE |
| `_in_flight` | 197 | FILM_BUSY when a GPU session, an unfinished render or a live FILM_CONTINUE exists for the film. | Never close in the middle of a purchase. | CODE_RULE |
| `_asking_letter_kinds` | 254 | Sheet letter, TEST-environment letter, `sheet_repair_owner`, film-retired letter. | Money/books letters stay. | CODE_RULE |
| `_asks_only_about` | 276 | An asking letter naming this film, or a waiting list whose every question is about it. | Never close a list that also asks about another film. | CODE_RULE |
| `_withdraw_questions` | 295 | `withdraw_subject_approvals`, `withdraw_owner_decision` for each open card of the film, `resolve_message` for asking letters. | Each through its own service. | CODE_RULE |
| `_topic_after_close` | 362 | Whether the topic is freed, held by a newer storyboard/script, and how many other topics are live (as `topics_in_production` reads it). | Say truthfully what the next daily run will do. | CODE_RULE |
| `topic_words` | 412 | Romanian clause for the topic outcome. | Confirmation text. | CODE_RULE |
| `_closing` | 437 | Reads the newest `runbook.film_retired` event (or the books for a film rejected another way). | Never say nothing was bought when the books hold spend. | CODE_RULE |
| `closed_words` | 474 | Romanian summary: nothing more bought, what stays in the books, topic outcome. | Confirmation text. | CODE_RULE |
| `_answer` | 490 | Response body (status CLOSED, withdrawn ids, topic, words). | Route answer. | CODE_RULE |
| `close_film` | 526 | Idempotent replay → 404 → refusals → takes the purchase lease (`close`, 600 s) → `_commit`; FilmBusy → 409 (CLOSING_NOW_RO if another close holds it). | The Owner's command. | OWNER |
| `_commit` | 575 | Under the write lock: re-check refusals, withdraw questions, `close_film_books(retired_by="Owner", details=…)`, remember the command. | One transaction. | CODE_RULE |
| `closure_view` | 649 | Read-only: closed (by whom, when, spend) or closable now (reason, busy lease), topic sentence. | The sheet's «Închide filmul» panel (`router.py:855`). | CODE_RULE |

Helpers: `FilmCloseRefused.__init__` / `.as_dict` (the 409's `{status, message}`, L127-136).

Data read/written: `Storyboard`, `VideoRenderJob`, `GpuSessionRow`, `TaskQueueItem`,
`OwnerDecision`, `AgentMessage`, policy-kernel approval rows (through
`services.withdraw_subject_approvals`), `ScriptDraft`, `DomainEvent` (`runbook.film_retired`
via `close_film_books`), command store (`recall_command` / `remember_command`). External calls:
none; the close blocks future purchases (`shooting_sheet.FilmClosed` at every lease).

### `app.media.answered_letters` — backend/app/media/answered_letters.py (176 lines)

Purpose: close the Owner's asking letters whose question no longer waits; local reads/writes,
nothing sent or bought (`answered_letters.py:1-25`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_film_moved_on` | 63 | Newest `runbook.film_state` after the letter: None if still WAITING with the same reason, else the new reason/status. | 2026-10-12 scene 6 letter stayed open. | CODE_RULE |
| `retire_answered_letters` | 91 | Under the write lock: reads pending approvals through `services.pending_approvals(engine)`; closes sheet letters (answered / superseded / moved on) and waiting lists with no pending question; returns ids by reason. | 2026-10-09 babcf272: six letters closed by hand. | CODE_RULE |

Helpers: `_state_words`. Called by `runbook.stages._sheet_letter` (`stages.py:2525-2532`) and
`workflows.watchdog.run_watchdog` (`watchdog.py:937-947`).

### `app.media.cards` — backend/app/media/cards.py (1302 lines)

Purpose: picture cards drawn locally with ffmpeg for 0 credits — DATA_CARD (animated bars from
spec values), TITLE_CARD, BLACK (with optional call to action), the cover — plus the font
metrics used by the burnt captions and the Owner's "finish" settings (`cards.py:1-23`,
`1194-1199`). No provider is imported.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `CardPalette.__post_init__` | 148 | Refuses any colour that is not `#RRGGBB`. | Hex colours drawn only here. | CODE_RULE |
| `font_path` / `_verified_font` | 165 / 170 | Path/bytes of a bundled font only when its SHA-256 matches the pin; else `FontMissingError`/`FontIntegrityError`. | Never a system fallback. | CODE_RULE (pins in code, L74-83) |
| `_parse_cmap` | 222 | Parses cmap formats 12 (3/10) and 4 (3/1). | Glyph coverage without a font library. | CODE_RULE |
| `_metrics_for` | 268 | Units/em, ascent, descent, cmap, advances (cached by digest). | Exact text measurement. | CODE_RULE |
| `line_height_px`, `text_width`, `em_for_cell`, `uncovered_characters`, `font_family` | 299-333 | Public measures used by the assembler's captions (`assembler._caption_px`, `ass_from_cues`, `_write_captions`, `install_caption_fonts`). | Captions measured with the font that draws them. | CODE_RULE |
| `card_spec_from_json` | 409 | Validates a scene's `card_json` into a `CardSpec` (see refusals): LIVE or unknown kind, no bars, >4 bars, mixed units, a non-number / non-finite / ≤0 value, a missing label/unit/claim id, an integer highlight out of range or a highlight of another type are refused; a text highlight that names no bar (or several) colours nothing. | Refuse anything that cannot be drawn truly. | CODE_RULE |
| `_highlighted_bar` | 466 | Exact label → case-folded label → the one label mentioned → None. | LHC 2026-10-03: highlight text refused every rewrite. | CODE_RULE |
| `format_value` | 486 | Romanian number format (1.000 / 83,5), up to six decimals. | Values written as a Romanian reader writes them. | CODE_RULE |
| `_fit` | 567 | Largest size (2 px steps) at which text wraps into `max_lines`; refuses missing glyphs or text that cannot fit. | No cut text, no other face. | CODE_RULE |
| `_lines` | 584 | Lays out lines as `TextItem`s. | Layout. | CODE_RULE |
| `layout_card` | 631 | Pure layout inside `SAFE_RECT`, above `CAPTION_BAND_TOP`; refuses < 1 s. | Safe-area guarantee. | CODE_RULE |
| `_layout_data` | 685 | Bar geometry proportional to values; refuses <200 px of bar height. | Bars at their true ratio. | CODE_RULE |
| `build_filtergraph` | 803 | ffmpeg graph: background (colour, blurred still, or closing push-in), eased bars, axis, fading text, BT.709 limited range. | One conversion, black at Y=16. | CODE_RULE |
| `black_refusal` | 906 | Refuses a BLACK card > 1.5 s in a short without a still. | Nepal rehearsal black ending. | CODE_RULE |
| `compose_card` | 924 | Verifies fonts, decides closing card, lays out, runs ffmpeg (600 s timeout), hashes the clip; provenance `composed`, 0 credits. | Cards never go to a paid model. | CODE_RULE |
| `layout_cover` / `compose_cover` | 1076 / 1103 | Hook text on the hero still as a PNG thumbnail candidate (120 s timeout). | 0-credit cover. | CODE_RULE |
| `_finish_value` | 1240 | Accepts a look-file value only of the default's kind and within bounds; notes the rejection. | A typo never draws captions in no colour. | CODE_RULE |
| `film_finish` | 1264 | Reads `config/factual_look.json` → `finish` merged with defaults; drops an unlicensed LUT. | The Owner's look file. | CONFIG + CODE_RULE |

Helpers: `_ff_color`, `_Metrics.covers/width/line_height`, `_tables`, `_metrics`, `_clean`,
`_bar`, `TextItem.x/box`, `_wrap`, `_time_scale`, `_alpha`, `_text_file`, `_seconds_ro`.

Callers: `assembler._compose_card_clip`, `assembler.film_cover`, `shooting_sheet._sheet` and
`card_preview_png`, `media.services.card_problems`, `qc.editorial_blocking` (callgraph); the
constants `CARD_KINDS` are also read by `factory` and `rehearsal`, and `CAPTION_BAND_TOP` /
`FRAME_HEIGHT` by `picture_qc` (grep).
External calls: local ffmpeg subprocess only.

### `app.media.router` — backend/app/media/router.py (1428 lines)

Purpose: the `/media` FastAPI router (mounted by `app.main.create_app`); every route requires
the Owner's bearer key (`router.py:319`). Route handlers are thin: they wire `app.state`
(engine, vault, registry, settings, test fakes) into the services and map exceptions to HTTP
codes. Paid work happens only in the sheet step, the redo and the reference-set routes.

Module-level functions:

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_use_the_sheet` | 143 | 409 body for the legacy render in PRODUCTION; also holds the film for its shot plan (`hold_for_shot_plan`) when non-serial scenes lack a model-written shot plan. | Second Nepal render 2026-09-26 bought everything with nothing shown. | CODE_RULE |
| `_paid_vendor_refusal` | 181 | 409 body naming the paid vendors the legacy render would reach. | Real paid media only through the sheet. | CODE_RULE |
| `SceneRedoCommand` | 193 | `kind` still/motion/card/audio, `scene_index`, `plan_hash`, `note`, `allow_over_budget`, `command_id`; extra forbidden. | Who asks is the route's, never the body's. | OWNER |
| `_spent_stage` | 212 | 409 SPENT_AND_STOPPED for a paid step that failed after paying. | Nothing retried after money was spent. | CODE_RULE |
| `_replayed` | 226 | Replays what a `command_id` already bought; 409 COMMAND_REUSED for another body. | MONEY-04 idempotent presses. | CODE_RULE |
| `_sheet_wiring` | 239 | Test fakes on `app.state`, else the Runway connection the Owner selected (capabilities, image adapter, account, video adapters, resolution). | Same wiring for every sheet route. | CONFIG |
| `_assemble_step` | 266 | Production plan voices, disk floor (409 LOW_DISK), `run_assemble_step` (202 question / 409 / 200 film). | The sheet's last step buys the narration. | OWNER (yes) + CODE_RULE |
| `create_media_router` | 318 | Builds the router (1111 lines including all handlers). | — | — |

Route handlers (all nested in `create_media_router`):

| Route | Handler | Line | What it does | Decided by |
|---|---|---|---|---|
| GET `/character-bible` | `get_character_bibles` | 322 | Seeds default bibles if the table is empty, then lists them. | CODE_RULE |
| GET `/character-bible/{id}` | `get_single_character` | 328 | One bible or 404. | — |
| GET `/storyboards` | `get_all_storyboards` | 340 | One page of summaries (PAGE-17), optional `qc_status` filter. | — |
| GET `/scripts/awaiting-storyboard` | `get_scripts_awaiting_storyboard` | 354 | Approved scripts production has not picked up. | — |
| GET `/storyboards/{id}` | `get_single_storyboard` | 359 | Detail or 404. | — |
| POST `/storyboards/from-script/{script_id}` | `create_storyboard_from_script` | 369 | `generate_storyboard_from_script`; FactualGateError → 422. | CODE_RULE (factual gate) |
| POST `/storyboards/demo-fixture` | `create_demo_fixture` | 394 | Seeds a DEMO topic, an UNVERIFIED claim and a DRAFT script; event `factual.demo_fixture_created`. Never marks a claim SUPPORTED. | CODE_RULE |
| POST `/render/{id}` | `start_render` | 523 | Legacy render: closed → 409; PRODUCTION → 409 «use the sheet»; story gate → 422; real paid vendors → 409; else (TEST, fakes) assemble, book costs, QC, `release_after_qc`. 238 lines. | CODE_RULE |
| POST `/storyboards/{id}/adopt-existing-files` | `post_adopt_existing_files` | 763 | 0-credit rehearsal: copies paid files into `rehearsals/`, adopts them as takes, optionally assembles and QCs with no adapter (`issued_by="owner"`). | OWNER |
| GET `/storyboards/{id}/shooting-sheet` | `get_shooting_sheet` | 828 | Builds the sheet (free balance read, local face count) plus `remediation` and `closure`. | — |
| POST `/storyboards/{id}/close` | `post_close_film` | 861 | `close_film`; 404 / 409 refusals / 409 COMMAND_REUSED. | OWNER |
| POST `/storyboards/{id}/steps/{step}` | `post_sheet_step` | 884 | One paid step (`SHEET_STEPS` or `assemble`): replay by `command_id`; `run_sheet_step` 202 asks / 409 / 200; `SpentStageError` → 409. | OWNER |
| PUT `/storyboards/{id}/shooting-sheet/scenes/{n}/model` | `put_scene_model` | 947 | The Owner's motion model or LOCAL_MOVE for one scene; returns old and new sheet hash. | OWNER |
| GET `/storyboards/{id}/redo-plan` | `get_redo_plan` | 985 | What a redo would do and cost, with its `plan_hash`; 0 credits. | CODE_RULE |
| POST `/storyboards/{id}/redo` | `post_scene_redo` | 1011 | `redo_scene`; paid kinds need the Owner's yes for this redo plan; replay by `command_id`. | OWNER |
| POST `/takes/{id}/decision` | `post_take_decision` | 1068 | APPROVED / REJECTED (+ `final`) via `decide_sheet_take`; FILM_CLOSED refused. | OWNER |
| GET `/takes/{id}/file` | `get_take_file` | 1111 | Serves a take file only inside the media roots (SEC-06). | CODE_RULE |
| GET `/storyboards/{id}/scenes/{n}/card-preview` | `get_card_preview` | 1127 | Last frame of a card composed locally (0 credits). | — |
| POST `/storyboards/{id}/prompts` | `write_prompts` | 1147 | `write_shot_prompts` (LLM, Video Editor); PromptError → 422. | OWNER triggers, LLM writes |
| GET `/storyboards/{id}/production-package` | `read_production_package` | 1167 | Everything the generator is given, for audit. | — |
| GET `/storyboards/{id}/production-plan` | `get_production_plan` | 1178 | `resolve_storyboard_plan` now. | CODE_RULE |
| PUT `/storyboards/{id}/production` | `put_storyboard_production` | 1190 | Channel/series/episode/scene overrides. | OWNER |
| PUT `/character-bible/{id}/voice-binding` | `put_voice_binding` | 1202 | Binds a voice to a character. | OWNER |
| PUT `/character-bible/{id}/identity-locks` | `put_identity_locks` | 1213 | Sets identity locks. | OWNER |
| POST `/character-bible/{id}/approved-models` | `post_approved_model` | 1224 | `approve_model_fallback` from an untyped body (`decided_by` default "Owner"). | OWNER |
| POST `/characters/{id}/reference-set` | `post_character_reference_set` | 1242 | Buys the character's reference pictures (image credits; budget asked before the first slot; STOP AUTONOMY refuses). | OWNER |
| POST `/character-bible/{id}/identity-changes` | `post_identity_change` | 1269 | Proposes an identity change. | OWNER |
| GET `/identity-changes` | `get_identity_changes` | 1280 | Lists proposed changes. | — |
| POST `/identity-changes/{id}/decision` | `post_identity_decision` | 1284 | Decides a proposed change. | OWNER |
| GET `/providers` | `get_media_providers` | 1295 | Which generators a render would use (no probe). | — |
| GET `/renders/{job_id}` | `get_render_status` | 1312 | Render job row. | — |
| GET `/assets/{id}` | `get_asset_info` | 1327 | Asset row. | — |
| GET `/assets/{id}/stream` | `stream_asset_file` | 1342 | Streams an asset file inside the media roots only. | CODE_RULE |
| GET `/qc/{id}` | `get_asset_qc_report` | 1363 | QC report by asset, or by the storyboard's newest completed render. | — |
| POST `/qc/{id}` | `evaluate_qc_for_storyboard` | 1386 | Runs `evaluate_media_qc` with the Owner's settings, registry (vision) and ffmpeg — the same gates as the day's QC. | CODE_RULE + LLM (vision QC elsewhere) |

Data written directly: `TopicIdea`, `FactualClaim`, `ScriptDraft` and an event (demo fixture,
`router.py:409-508`); everything else through services. External calls (through services):
paid stills/motion/narration (sheet step, redo), image credits (reference set), free vendor
balance reads, local ffmpeg.

## Connections

Who calls into this group (callgraph + grep):

| Caller | Calls | Where |
|---|---|---|
| `workflows.worker.build_task_handlers` | `scan_sheet_issues`, `allowed` (SCAN_FILM_SHEETS each worker pass, throttled), `process_sheet_repair` (FILM_SHEET_REPAIR), `research_all` (MODEL_RESEARCH) | `worker.py:412-417`, `445-475`, `497-504`, `742-746` |
| `app.main` | schedules `model_research_weekly`; mounts `create_media_router` | `main.py:526-536` |
| `runbook.stages._sheet_letter` | `submit_sheet_issues` for LINT_BLOCKED / NEEDS_SHOT_PLAN; `retire_answered_letters` after each sheet letter | `stages.py:2430-2435`, `2525-2532` |
| `workflows.watchdog.run_watchdog` | `retire_answered_letters` | `watchdog.py:937-947` |
| `decisions.sources` | `sheet_issues` (`_blocked_live_scenes`), `allow_repair_retry` (`apply_sheet_repair_retry`) | `sources.py:941-966`, `1086-1107` |
| `integrations.router.post_model_research` | `research_all` (Owner button) | `integrations/router.py:392-399` |
| `media.assembler` | `sound_plan`, `scene_brief`, `plan_record`, `plan_event_payload`, `levels_for_mix`, `mix_refusal`, `replan_record`; `load_library`; `compose_card`, `compose_cover`, `card_spec_from_json`, `film_finish`, font measures; `PurchaseGuard`, `unasked_refusal` | `assembler.py:5760-5911`, `7786-7855`, others per callgraph |
| `media.stills_stage`, `media.shooting_sheet`, `media.gpu_batch` | `PurchaseGuard`, `unasked_refusal`; `card_spec_from_json`, `compose_card` | see `mode_guard` section |
| `media.factory.render_plan` | `plan_speakers` | callgraph |
| `media.sheet_story_repair.retire_replaced` | `film_close._unclosable`, `film_close._in_flight` | callgraph |
| `media.qc` | `film_finish` (`editorial_blocking`), `load_library` (`audio_mix_verdict`) | `qc.py:4198-4204` |

What this group calls out to: `agents.structured.structured_run`, `agents.services.run_agent_task`,
`agents.messages` (post/resolve letters), `agents.memory` (`agent_for_role`, `remember`),
`media.shooting_sheet` (sheet build, leases, sheet steps, take decisions), `media.prompt_agent`,
`media.sheet_story_repair`, `media.assembler`, `media.qc`, `media.rehearsal`,
`media.production_policy`, `media.factory`, `integrations.discovery` / `lifecycle`,
`economy.accountant`, `research.retrieval`, `runbook.stages`, `decisions.sources` /
`decisions.services`, `services` (`may_act`, `queue_film_continue`, commands, approvals),
`toolchain` (ffmpeg).

Events emitted here: `media.sheet_repair_retry_allowed`, `media.sheet_repair_finished`,
`media.sheet_repair_plan_saved` (blocker_repair); `media.model_research_recorded`
(model_research); `media.paid_step_stopped_by_mode` (mode_guard); `factual.demo_fixture_created`
(router); `agent.message_posted` for every letter (through `post_message`). Payloads defined here
and emitted by the assembler: `media.sound_plan_written`, `media.sound_plan_replanned`. Through
services: `runbook.film_retired` (film close), `provider.resource_metadata_updated`.

Events consumed: `owner.autonomy_mode_changed` (mode_guard), `runbook.film_state`
(answered_letters), `runbook.film_retired` (film_close), `media.sheet_repair_retry_allowed`
(blocker_repair).

## Owner touchpoints

| Touchpoint | Kind | What the Owner decides | Where |
|---|---|---|---|
| «Închide filmul» | Button → POST `/media/storyboards/{id}/close` | Ends an unfilmed film; withdraws every question about it. | `film_close.py:526`; `router.py:860` |
| Sheet step press | Button → POST `/steps/{step}` with `plan_hash`, `allow_over_budget`, `command_id` | Buys stills / test shot / motion / assembly for the exact sheet shown; consent to exceed the daily/film budget. | `router.py:883-944` |
| Scene motion model | PUT `/shooting-sheet/scenes/{n}/model` | Model id or LOCAL_MOVE per filmed scene. | `router.py:946-982` |
| Redo | GET `/redo-plan` then POST `/redo` | Redo a still/motion (paid, bound to the redo plan's hash) or card/sound (free). | `router.py:984-1065` |
| Take decision | POST `/takes/{id}/decision` | APPROVED / REJECTED, `final`. | `router.py:1067-1108` |
| Character identity | PUT voice binding / identity locks, POST approved models, identity changes, reference set | Voices, locks, fallback models, reference pictures (image credits). | `router.py:1201-1292` |
| Production overrides | PUT `/storyboards/{id}/production` | Channel/series/episode/scene overrides. | `router.py:1189-1199` |
| Prompts, QC, rehearsal, legacy render | POST `/prompts`, `/qc/{id}`, `/adopt-existing-files`, `/render/{id}` (TEST only) | Trigger LLM prompt writing, QC, a 0-credit rehearsal. | `router.py:1146`, `1385`, `762`, `522` |
| Sheet repair paused (LANGUAGE_MODEL_DOWN) | Decision card + ESCALATE letter | Reconnect the language model, animate blocked LIVE scenes locally, or wait. | `blocker_repair.py:272-295`; `sources.py:971-1065` |
| Sheet repair retry | Card option → `allow_repair_retry` | Let a paused repair try again now. | `blocker_repair.py:119-163`; `sources.py:1086-1107` |
| Sheet needs intervention | ESCALATE letter «Foaia necesită intervenție: <title>» | Money/config blockers left after the repair (balance, budget, film ceiling, blocked step, catalogue). | `blocker_repair.py:688-700` |
| Model research now | Settings button → POST `/settings/model-research` | Run the stewards' research immediately. | `integrations/router.py:392-399` |
| Locked default model | `MediaProductionConfig.allow_production_override` | Whether research may change the default model. | `model_research.py:267-269`, `438` |
| Price alert | The Accountant's ESCALATE letter to the Owner | Informed when a documented price moves ≥ threshold. | `model_research.py:404-415`; `economy/accountant.py:657-700` |
| Autonomy mode / stop | Setting | MANUAL stops automatic sheet repair; a lowered mode stops an unasked paid step at its next vendor request. | `blocker_repair.py:314-318`; `mode_guard.py:208-250` |
| Music library | `config/music/music_library.json` (or `STUDIO_MUSIC_LIBRARY`) | Which licensed tracks exist (commercial_ok, licence, sha256). | `music_library.py:36-60`, `193-240` |
| Voice cast | `config/serial_voice_cast.json` (`use_until_the_owner_binds`) | Default voices per character until bound. | `speaker_voices.py:48`, `67-102` |
| Film finish | `config/factual_look.json` → `finish` | Caption colours, headline, grade, LUT (+licence), second framing, cover, editorial QC blocking. | `cards.py:1201-1302` |
| Settings | `.env` / settings | `sheet_blocker_scan_seconds`, `production_priority`, `price_change_alert_percent`, test cost ceilings, disk floor. | `config.py:56`, `251`, `446`; `router.py:284`, `640-672` |

## Oddities and gaps

1. `Assignment.repair_prompts` is required in the Director's answer but never read; the prompt hand-off depends only on whether PROMPT issues exist (`blocker_repair.py:553`, `819-907`).
2. `director_assignment` runs (a Director model call) even when the sheet has no PROMPT issue left after `repair_story` returns None (e.g. only OWNER blockers); its note is then unused (`blocker_repair.py:818-909`; `sheet_story_repair.py:178-179`).
3. An attempt that finds another lease on the film is recorded UNRESOLVED (`blocker_repair.py:778-786`, `821-829`) and counts toward the back-off and the five-a-day ceiling exactly like a failed repair (`blocker_repair.py:212-220`).
4. `BACKOFF_MAX_SECONDS` (6 h) is never reached: with `MAX_SAME_ISSUES_PER_DAY = 5` the longest wait is 1200 s at the 4th unresolved attempt; the 5th pauses (`blocker_repair.py:62-66`, `235-248`).
5. `STUDIO_STARTED_AT` is set at import, so every process restart resets the attempt window (by design, `blocker_repair.py:69-73`); the daily ceiling holds only within one process run.
6. `_language_model_failing` reads the 3 newest `AgentRun` rows of any agent, not the Director's or the repair's runs (`blocker_repair.py:91-103`).
7. The DAILY_LIMIT branch of `decisions.sources.sheet_repair_paused`, which offers the «retry» option that calls `allow_repair_retry`, is no longer reached: the card itself accepts both causes (`SHEET_REPAIR_CAUSES`, `sources.py:81`), but its only caller passes causes in `OWNER_PAUSE_CAUSES = {LANGUAGE_MODEL_DOWN}` (`blocker_repair.py:256`, `272-274`; `sources.py:1003-1016`). The LANGUAGE_MODEL_DOWN card offers reconnect / local move / wait, not retry; `allow_repair_retry` is reachable only from cards created before that change.
8. `scan_sheet_issues` resolves every open `sheet_repair_limit` letter on each scan, and `_finish` resolves them on RESOLVED, but nothing in `backend/app` writes that kind any more (`blocker_repair.py:710`, `953-967`; grep finds only these readers).
9. On WAITING_OWNER, `_finish` posts an ESCALATE letter to the Owner listing money/config blockers (LOW_BALANCE, OVER_DAILY_BUDGET, OVER_FILM_BUDGET, STEP_BLOCKED, …) (`blocker_repair.py:688-700`); the decision of 2026-10-12 (a) says money is asked by the studio's cards, never by a letter (`16_DECISION_LOG.md:53`).
10. `research_models` writes `pricing={}` for a model the steward did not price (`model_research.py:380-385`); `update_resource_metadata` passes it to `stamp_price`, which stores `row.pricing = wanted` = `{}`; the BILLED-protection loop only covers keys the new pricing names (`integrations/discovery.py:791-799`; `integrations/lifecycle.py:152-177`). A previously recorded price, billed or documented, is replaced by an empty pricing.
11. `research_models` replaces the whole `capabilities` dict with five keys (`model_research.py:393-399`; `discovery.py:781-789`), without `basis` or `sources`; `production_policy.model_research` classifies such a row as an unsourced estimate («estimat»), below `config/film_models.json` (`production_policy.py:3288-3321`), and any previous `basis`/`need_quality`/`camera_moves` keys on the row are dropped. The module docstring says scores go "with the source URL" (`model_research.py:17-19`); the URL is stored as the row's metadata source, not in `capabilities`.
12. In `research_models` the first run's status is not checked; a failed page-plan run silently reduces the evidence to the index page (`model_research.py:297-323`).
13. The research letter's "top three" prints only `per_1k_characters_usd` (`model_research.py:457-462`); `rank_candidates` fills that key with whatever price key is recorded first in the order per_1k_characters / per_second / per_image / price_usd (`production_policy.py:228-238`, `357`, `400`), so a video's per-second price is printed as "USD" with no unit.
14. `start_render` passes `video_adapter_for_scene=(None if … else None)`, always None (`router.py:620-622`).
15. `start_render` maps any remaining `ValueError` to 404 «not found» (`router.py:751-752`); the code already special-cases `ReferenceRequired` for this reason (`router.py:720-737`).
16. `post_approved_model` takes an untyped `dict` body and records `decided_by` from it (default "Owner") (`router.py:1224-1239`), unlike the other commands, which forbid extra fields and take who issued them from the route.
17. GET `/character-bible` writes (seeds default bibles when the table is empty) (`router.py:322-325`); `_use_the_sheet`, a 409 body builder, also writes (`hold_for_shot_plan`, `router.py:166-167`).
18. `post_adopt_existing_files` reaches the LLM only in the static call graph: `rehearse` passes no registry to the assembly and `registry=None` to QC, so the sound plan is deterministic and no vision model runs (`rehearsal.py:1196-1202`, `1238-1247`, `1265`).
19. `film_close._unclosable` and `_in_flight` are private but imported by `sheet_story_repair.retire_replaced` (callgraph).
20. `music_library.LIBRARY_PATH` is computed once at import (`music_library.py:60`): an Owner library file created after start-up is not read until a restart (the file's contents are re-read on every `load_library` call).
21. `moods_of` matches by prefix (`music_library.py:274-283`); short stems such as "who", "cine", "win", "lin", "pace", "risc" also match unrelated words ("cinema", "window", "line"), which can tilt `choose_bed`.
22. `CardBar.claim_id` is required but not checked against claims here (`cards.py:405`); the module relies on the story gate and `media.services.card_problems` for that (`cards.py:11-12`).
23. On a re-plan, the deterministic fallback keeps the bed of the plan QC refused (`sound_design.py:400-409`), changing only the levels to "under" and the summary. It is not checked against the refused plan: when the refused plan was itself the deterministic one, the fallback is the same plan again.
24. `UrlPlan` and `ModelResearch` give every field a default and ignore extra keys (`model_research.py:80-106`), so any JSON object validates against them. `read_structured` tries every `{` in the answer and returns the first object that validates (`agents/identity.py:603-639`): when the steward's top-level judgement is refused (one score above 1, a note without `remote_id`), the first nested `ModelNote` object validates as an empty `ModelResearch` (models `[]`, recommendation `None`). The run then annotates nothing, raises no `ModelResearchError`, and promotes `rank_candidates()[0]` (next item). `ModelResearchError` is raised only when the text holds no JSON object at all (`model_research.py:353-359`).
25. With no recommendation, or one that is not a listed candidate, the code still sets `recommended = rank_candidates(...)[0]` (`model_research.py:427-431`), may save it as the default (`model_research.py:438-452`), and the steward's letter says «Recomand <id>: » with an empty reason (`model_research.py:456-466`), as if the steward had chosen it.
26. `_price_key` chooses the pricing key from words in `price_unit` but never converts the number (`model_research.py:185-193`, `381-385`): a video price given "per minute" is stored as `per_second_usd`, a voice price "per 1M characters" as `per_1k_characters_usd`, unchanged; `rank_candidates` and the price alerts then compare those figures with real per-second / per-1k prices. The BILLED protection covers only `lifecycle.PRICE_KEYS`, which does not include the fallback key `price_usd` (`integrations/lifecycle.py:59`).
27. `structured_run` stops after a first run that is not SUCCEEDED (provider error, budget or policy block) without a second attempt (`agents/structured.py:138-140`), yet `sound_plan` records the fallback reason «răspunsul nu a respectat forma cerută nici a doua oară» for that case too (`sound_design.py:464-476`).
28. `_pause_letter` skips the letter when any OPEN `sheet_repair_paused` letter of the sheet exists, whatever its cause (`blocker_repair.py:276-279`): a LANGUAGE_MODEL_DOWN pause that follows a still-open DAILY_LIMIT STATUS letter to the Director gets its Owner card (called first, L272-274) but no ESCALATE letter to the Owner.
29. The model-research module docstring says the steward names "up to three pages" (`model_research.py:9`), while the prompt and the code allow five (`MAX_PAGES = 5`, `model_research.py:71`, `111`); the judge prompt asks every purpose, voice and image included, for a recommendation "for the studio's short vertical videos" compared on "prices per second" (`model_research.py:132-135`).
30. `sheet_issues` falls back to `DEFAULT_MARGIN` (1.15) when the footer lacks `balance_needed_credits`, not to the Owner's `paid_step_balance_margin` setting that `balance_rule.margin_of` reads (`blocker_repair.py:370-372`; `balance_rule.py:45-48`).
