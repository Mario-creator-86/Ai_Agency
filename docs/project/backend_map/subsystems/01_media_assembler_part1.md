# 01 — The film assembler, part 1 (`app.media.assembler`, lines 1-8300)

> Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).
>
> Files: `backend/app/media/assembler.py` (16716 lines; this document covers only the
> functions and classes defined in lines 1-8300, 200 functions; lines 8301-16716 are mapped
> by another group). Lines 1-8300 are byte-identical at `b00083c` and `20abffd`; the four
> later commits changed only part 2 (`_clip_plan`, `_check_shot`, `_redo_still`,
> `_StillRedoBuyer`) and the modules this part reads verdicts from.
>
> Line numbers are `backend/app/media/assembler.py:<line>` unless another path is given.
> "LLM" in this document means a call that leaves through
> `app.agents.services.run_agent_task` (backend/app/agents/services.py:733).

## In one paragraph

This part of the assembler turns a storyboard into a finished 1080x1920 vertical film with
FFmpeg, and holds the bookkeeping that lets the studio never pay twice for the same picture,
shot or narration. It reads the storyboard's scenes (`scene_view`, :3351), uses or buys one
still per filmed (LIVE) scene (`_still_for_scene`, :2839), composes chart, title and black
scenes locally (`_compose_cards`, :3785), voices the narration scene by scene with the
vendor's silence trimmed (`_trimmed_take`, :648) and keeps each paid narration as a reusable
take (`keep_narration`, :3177), measures the timeline from the words (`scene_spans`, :1748),
buys or reuses a motion clip per scene (`assemble_video_job` motion pass, :6830-7141), slows a
slightly short clip locally or refuses it (`_clip_slowdowns`, :3844), mixes a music bed under
the voice from the Owner's licensed library following a sound plan the Voice Artist writes
(`film_mix`, :5788), masters the sound, burns word-timed captions (`_write_captions`, :3993),
grades every shot toward the first filmed shot (`film_grade`, :2221), cuts long scenes to a
second framing (`plan_second_framings`, :2337), encodes the film (`_dissolve_command`, :1938),
composes a cover (`film_cover`, :2432), judges the licence of every component
(`film_licence_ledger`, :6236) and records the asset. It also holds the shared "readiness"
reading that the shooting sheet, the pre-check and the render all use to decide whether a
scene's clip may enter the film (`clip_readiness`, :4646; `assembly_readiness`, :4739), the
studio's own proposal of a paid motion redo for a clip too short for its words
(`propose_clip_redos`, :4947), the eligibility of the Owner's «Aleg totuși acest clip» choice
(`clip_choice`, :5335), a 0-credit sound repair (`repair_audio`, :7851), and the constants and
exception types of the motion staircase (:8049-8315). Almost all of it is deterministic code.
No function here calls a model itself. The model reaches these lines in three ways. First,
through the sound plan (`film_mix`, `_replan_sound`). Second, through the paid motion redo
that `propose_clip_redos` raises in part 2 (`redo_scene`, :14994), whose clip QC asks the
vision judge and, on a refusal she may overturn, the Director's second look (see "LLM
involvement"). Third, through verdicts that models wrote earlier and that this code reads as
take statuses or events:
- a take's `APPROVED` status, written by the Owner, the Director's look
  (backend/app/media/director_qc.py:2145), the stills gate's vision-judged choice
  (backend/app/media/stills_stage.py:961-962) or, since `20abffd` (wired in `5fc7468`), the
  Director's second look at a still the gate refused (`approved_by` `director_look`,
  backend/app/media/stills_stage.py:1017-1035);
- clip QC's verdict, where the vision judge's "no" alone makes a paid clip REJECTED, unless
  the Director's second look keeps the refused clip: part 2's `_check_shot` then stores the
  report with verdict PASSED (`accepted_by` `director_look`, assembler.py:10361-10373).

`clip_accepted` (:5211, :5215) and `usable_take(statuses=("APPROVED",))` (:3542, :2879) do not
check who approved a take or who wrote a PASSED verdict.

## Why it exists

- The module states its own contract: a deterministic assembler following
  `docs/architecture/08_VIDEO_PIPELINE.md`, safe argument-list subprocesses, SHA-256 provenance
  (:1-8). Spec 08 §"Paid staircase" item 10 (Assemble), 11 (QC and repair) and 12 (Cover)
  (docs/architecture/08_VIDEO_PIPELINE.md:266-281) describe what this code builds.
- **Never pay twice.** The Nepal film's second render "bought all six stills and every clip a
  second time, with the same prompts" (:2484-2488); every paid picture is now a `SceneTake`
  keyed by a prompt hash and reused (`usable_take`, :2659; `record_take`, :2716). The Nepal
  film (2026-09-26) also "bought every clip twice, on five models, with no price shown"
  (:8051-8053), the reason for the motion staircase constants at :8049-8118.
- **Narration bought once** (A9 / MONEY-12, 2026-10-02): an assembly that failed after its
  narration and was retried paid ElevenLabs twice (:2998-3005).
- **Clip as long as its words** (film babcf272, 2026-10-09): clips bought at the planned length
  were shorter than the measured narration; the assembly was refused four times while the sheet
  said «Pregătit» (:4171-4193). The Owner's answer «Încetinește local» (slow a clip locally
  within 25%, never freeze a frame) is :1791-1803 and :3844-3917.
- **«Aleg totuși acest clip»** (Owner, 2026-10-10): a clip rejected by clip QC could not be
  chosen again; now one eligibility rule serves the sheet's button and `decide_take`
  (:5252-5269).
- **Audit 2026-10-02 items**: Q3 stitching of neighbouring words (:3030-3032), Q4 trimming the
  vendor's silence (:168-172, :648-660), Q5 closing card instead of a long black (:3753-3756),
  Q6 second framings (:2303-2308), Q7 caption cards and size (:344-348, :361-364), Q8 grading
  toward the hero (:2033-2040), Q14 the cover (:7568-7569); AR-15 the licence ledger
  (:6010-6016, docs/project/16_DECISION_LOG.md:4118).
- **Timeline at 24 fps, hard cuts** (2026-10-01, TIMELINE_24_CAPTIONS, the code's own label at
  :1700): the vendor's native 24 fps, hard cuts unless the script asks for a dissolve, every
  length on whole frames (:1699-1703). The decision log records the 24 fps timeline under
  2026-09-27 (e) (16_DECISION_LOG.md:4060-4062); the label TIMELINE_24_CAPTIONS appears only in
  the code.
- **Disk** (2026-10-01, DISK_AND_BREATHS): lossless intermediates were ~1.1 GB per film; CRF 4
  intermediates are half that (:1629-1651; 16_DECISION_LOG.md:4084).
- **Honest failure**: "a render either produces a real encoded video or it fails" (:184-189);
  the first dissolve render wrote six seconds of picture under forty-six seconds of audio and
  reported success, so each shot's frames and the final picture length are measured
  (:1847-1850, :7439-7450, :7556-7566).
- **Sound under the voice** (Owner, 2026-10-11): «mare grijă totuși să nu acopere vocea»; the
  Voice Artist plans the bed per film (backend/app/media/sound_design.py:3-25;
  16_DECISION_LOG.md:84).
- **Real paid media only through the shooting sheet** (2026-10-01): the legacy whole-film path
  that calls `assemble_video_job` refuses any real paid vendor adapter
  (16_DECISION_LOG.md:4080; backend/app/media/factory.py:120-175). The assemble step's
  narration is gated through `may_act` with the sheet's plan hash (16_DECISION_LOG.md:4082).

## Who decides here

| decision | decided by | where | rule / check / threshold |
|---|---|---|---|
| Whether a whole-film render may hand a real paid vendor to `assemble_video_job` | CODE_RULE (caller) | backend/app/media/router.py:577-588; backend/app/runbook/stages.py:3385-3395; backend/app/media/factory.py:160-175 | `legacy_render_vendors` / `guard_motion_chooser` raise `PaidVendorRefused` before any job exists or before the motion adapter is used |
| Whether the render records paid takes | CODE_RULE | :6430-6435 | `record_takes = image_adapter is not None and not takes_only`; takes-only renders buy nothing |
| Use an existing still instead of buying | CODE_RULE | :2871-2892, :2659-2713 | same prompt hash (words + reference sha256 + model), file on disk with matching sha256, status APPROVED (preferred) or PAID |
| Takes-only render with no APPROVED still | CODE_RULE over an `APPROVED` status that the Owner, the stills gate (LLM_CHECKED_BY_CODE), the Director's look (LLM_CHECKED_BY_CODE) or the Director's second look (LLM, on refusals code lets her see) wrote | :2893-2898, :3542-3572 | raises `TakesMissing` before a render job exists; nothing bought. `usable_take(statuses=("APPROVED",))` does not read `approved_by`. A still is APPROVED by the Owner's look, by the stills gate's choice (`approved_by` `still_gate`, backend/app/media/stills_stage.py:961-962; the vision judge `picture_qc.judge_still` plus `still_gate.decide`), by the Director's look on a refused candidate (`approved_by` `director`, backend/app/media/director_qc.py:2145), or by the Director's second look on candidates the gate refused whole, before a re-roll, a rewrite or the Owner's question (`stills_stage._settle_round`, stills_stage.py:1110-1184, look at :1143-1148) or after collected candidates were refused (`_settle_pending`, stills_stage.py:1254-1260); `_director_looks` (:1038-1077) then `_approve_by_look` (:1017-1035) write `approved_by` `director_look`. She sees only candidates `still_gate.may_be_overturned` allows (backend/app/media/still_gate.py:1118-1130: measured whole, not left to the local compositor, never a hard limit: faces where forbidden, writing, panels, a blank field), and code turns her answer into an approval only through `fix_check.look_accepts` (backend/app/media/fix_check.py:693-703), in practice an OVERTURNED with severity none or minor |
| Re-buy a still that is stripes/blank | CODE_RULE | :2967-2990 | `qc.still_is_degenerate` (deterministic ffmpeg measure, backend/app/media/qc.py:310-317) → take REJECTED `LOCAL.DEGENERATE_STILL`, one paid retry with on-screen text stripped and `DEGENERATE_RETRY_SUFFIX` |
| Stop the stills step after a vendor refusal | CODE_RULE over EXTERNAL code | :3453-3466 | `production_policy.classify_failure` verdict `stop_step` (backend/app/media/production_policy.py:2257-2340): an ACCOUNT failure (401/402/403, insufficient credits), a malformed studio request (400/422 naming the studio's own parameter, STUDIO_DEFECT), or a second CONTRACT refusal in a row |
| Stop rendering / buying between scenes | OWNER | :3425-3429, :6509-6521, :6960 | `runbook.services.stop_requested` (AUTONOMIE OPRITĂ or shutdown) read before each scene and before each shot |
| Which voice speaks a scene / whether the film is "placeholder" voiced | CODE_RULE | :6443-6458 | a scene voice from `tts_adapter_for_scene` else `tts_adapter`; if any scene lacks a real voice the whole film is labelled `PLACEHOLDER_DETERMINISTIC_VOICE` (QC blocks publication) |
| Whether a narration is paid or reused | CODE_RULE | :6610-6658, :3129-3174, :3014-3027 | `narration_key` (words, voice settings, adapter, neighbours' words for a stitching voice) matches a PAID/APPROVED narration take with file + sidecar intact → reused at 0 cost |
| Whether the narration may be bought at all | OWNER / CODE_RULE (caller) | backend/app/runbook/stages.py:2636-2667; backend/app/media/shooting_sheet.py:3895-3935 | `mode_refusal` on `media.paid_generation` (T2) or `..._over_threshold` (T3), `reserve_spend`, the sheet's `plan_hash`; `narration_to_buy` (:3300) supplies the exact character count |
| Trim the vendor's silence | CODE_RULE + EXTERNAL timing | :648-761 | silence under -45 dB for 50 ms (toolchain `speech_edges`), keep `EDGE_KEEP_SECONDS` 0.03 s, never cut a word the vendor timed (:709-711) |
| Scene length on the timeline | CODE_RULE | :1748-1781, :6803-6824 | `min(plan, words + 0.12 s)` rounded up to a frame, never shorter than the words; silent cards capped by `qc.MAX_SILENT_CARD_SECONDS` (BLACK 2.0, TITLE_CARD 2.5, DATA_CARD 4.0) |
| Cut or dissolve between scenes | CODE_RULE over storyboard data | :1713-1735 | dissolve (8 frames) only when `transition_in` is one of `DISSOLVE_WORDS`; a recorded `dissolve_seconds` is kept for older films |
| Scene quality tier | CODE_RULE | :1511-1530 | A stated `quality_tier` wins, then a stated `scene_role`. Neither is ever set: the only caller (:6860) passes `scene_view` dicts (:3351-3377), which carry neither key. So in practice the tier comes from `story_purpose`: HOOK→HERO, REVEAL/PAYOFF→KEY→PREMIUM, ENDING→PREMIUM, any other stated purpose→NORMAL→STANDARD. With no purpose, it comes from position (`production_policy.scene_role`: first HOOK, last ENDING); `SCENE_ROLE_TIERS` (backend/app/media/production_policy.py:660-667) |
| Reuse an already paid shot | CODE_RULE | :6884-6920, :4085-4139 | motion identity (package + still sha256 + from_prompt), at least `min_clip_seconds(span)` long as measured; the Owner's newest APPROVED choice wins (:4118-4121). Outside `takes_only` the reused shot is not passed through `clip_accepted`: a PAID clip whose clip QC is UNCHECKED is cut in (:6892-6920) |
| Which motion model films a scene | CODE_RULE (caller-supplied) | :6976-6989 | `motion_chooser(scene, tier, seconds, remaining_usd, ())` (runbook/stages.py:3427, `motion_for_scene`); none → scene stays a still |
| Skip a shot for the render's motion budget | CODE_RULE + CONFIG | :6966-6975 | after the first shot, skip when `remaining_usd < average shot USD` |
| Refuse a shot on the vendor's quote | CODE_RULE over an EXTERNAL quote | :7001-7061 | dry-run quote (only if the adapter offers `estimate_generation`, :1394-1396) above `motion_budget_usd`, above `motion_max_usd_per_second`, or above the remaining budget → not bought; the ceilings are the caller's arguments and are applied only when `_credit_price` found a price (:7015) |
| Correct a stored price that drifted | EXTERNAL | :7018-7035 | `production_policy.record_quoted_price(..., tolerance_percent=price_tolerance_percent)` (default 5.0, :6275) |
| Test-limit on motion | CONFIG (caller) | :6961-6965 | `motion_scene_limit`: only the first N LIVE scenes get motion |
| A motion task that failed or did not arrive | EXTERNAL + CODE_RULE | :1344-1375, :7101-7141 | vendor FAILED → `MotionTaskFailed` with its code; poll errors retried twice; deadline 600 s (or adapter's `timeout_seconds`); credits stated by the vendor are recorded `paid_but_lost` and the take PAID, else REFUSED |
| Slow a short clip or refuse it | CODE_RULE (Owner rule 2026-10-09) | :3844-3917, :4588-4603 | measured clip covers the span (to half a frame) → cut; short by ≤ `SLOWDOWN_ALLOWANCE` 0.25 → slowed with `minterpolate` (fallback `framerate`), 0 USD, an Owner warning; shorter → clip dropped, `CLIP_SHORT` |
| A LIVE scene shown as a still in PRODUCTION | OWNER | :3613-3637, :7197-7234; backend/app/media/qc.py:2802-2917 | allowed only for scenes the Owner set to LOCAL_MOVE on the sheet; else `ClipsNotAccepted`, job FAILED, `media.assembly_refused` recorded; in TEST it only warns |
| Whether a clip is "accepted" | OWNER, or LLM_CHECKED_BY_CODE (the Director's look, or clip QC whose verdict includes the vision judge), or LLM (the Director's second look, on refusals code lets her see) | :5204-5225 | Any `APPROVED` status → yes, whoever wrote it: the Owner (`decide_take`, `approved_by` owner, :9779), or the Director's look turning a REJECTED clip APPROVED (backend/app/media/director_qc.py:2145). Only `clip_choice`-eligible clips are offered to her (director_qc.py:2000-2004), and at write time code checks only that the take is still REJECTED, unseen by the Owner, the film open and the file unchanged (director_qc.py:2048-2066). `approved_by` is not read. The latest clip-QC verdict PASSED → yes (assembler.py:5215-5216). PASSED is written either by clip QC itself (vision judge "keep" and every measured check passed) or by part 2's `_check_shot` for a clip clip QC refused and the Director's second look kept (`qc.ACCEPTED_BY_LOOK`; record `verdict` PASSED, `passed` False, QC's `blocks_ro` kept, `accepted_by` `director_look`, assembler.py:10361-10373; backend/app/media/qc.py:2670-2683, :2737-2751). Her look is asked only where `qc.look_may_overturn` allows: a blocking FAILED, nothing unmeasured, not the still's fault, no `faces` or `panels` block, no readable text, one picture, no face the judge saw where faces are checked (qc.py:2588-2606). It is asked on the first refused clip before the one retry is bought (or before the scene is escalated when no retry is bought: the cap, or a corrected mistake seen again, qc.py:2515-2529, :2546-2552), and again on the retry when that fails too (`_looked`, qc.py:2616-2623; :2670-2683, :2734-2751). Code keeps the clip only on an answer `fix_check.look_accepts` takes (fix_check.py:693-703; in practice OVERTURNED with severity none or minor, since `SecondLook` makes CONFIRMED always redo, second_look.py:114-135). A motion-floor or cut failure can be kept. `accepted_by` is not read. UNCHECKED → yes only outside PRODUCTION; FAILED → no |
| Whether a scene's shot may be cut in (sheet, pre-check, render share it) | CODE_RULE over `clip_accepted` | :4646-4736, :4739-4842 | accepted + long enough for `span` (or `least_span` → "at_risk"); `NO_STILL`, `NO_SHOT`, `CLIP_SHORT` otherwise; LOCAL_MOVE or TEST make it ready as a still |
| Clip length to buy for a scene | CODE_RULE | :4469-4523 | max(planned + 0.4 s, narration + 0.12 s breath + dissolve + margin [10% if estimated, 2 frames if measured], refused-render floor + 2 frames), on whole frames |
| Narration length used for planning | CODE_RULE | :4337-4430 | rendered (trimmed by the newest render, same takes) > measured (kept takes, every part) > estimated (0.40 s per spoken word, least 0.75x) |
| Raise a paid motion redo for a too-short clip | CODE_RULE (proposal); purchase by the Policy Kernel under the Owner's mode and paid-media rule (OWNER setting, or the Owner's yes) | :4947-5093 | Covers scenes of the newest refusal coded `CLIP_SHORT`, skipped if a long-enough clip was bought since. Bought only through `redo_scene(unasked=True, proposal=True)`. `may_act` on `media.scene_redo` bound to `plan_hash` and the cap, the budgets, the film ceiling and the lease decide. Where the Owner's mode and rule allow an unasked buy, the redo is bought without a question. `proposal` forces the Owner's question only when the scene holds a shot the Owner approved (`owner_approved_among`, then `_proposal_asks_him`, :11676-11699, :13068) |
| A clip measured wrong by clip QC | LLM_CHECKED_BY_CODE for an accept; the vision judge's "no" alone is acted on for a reject; the Director's second look (LLM) can turn the reject into PASSED before it is stored | :5111-5143, :5146-5190 | verdict PASSED / FAILED (any blocking FAILED) / UNCHECKED; FAILED on a PAID take → REJECTED `QC.CLIP`. A blocking FAILED comes from a measured check (motion floor, cut, YuNet faces, flat-band panels; `qc.check_clip`, qc.py:2198) or from the vision judge `picture_qc.judge_clip`. `qc._picture_check` (backend/app/media/qc.py:2009-2075) reads the judge's yes/no answers strictly, so any "no" or a non-"keep" fails the clip, with no code re-check of that "no"; since `5fc7468` a motion-layer finding the judge says persists also fails it, and an unanswered one leaves the picture check NOT_RUN (qc.py:2031-2045). Before the report reaches `_keep_clip_report`, part 2's `_check_shot` lets the Director's second look keep a clip `qc.look_may_overturn` allows (qc.py:2588-2606); her keep is stored as PASSED, so the take stays PAID and is never REJECTED here (assembler.py:10361-10386, :5161). Her CONFIRMED, or no answer (UNAVAILABLE: no registry, an error, an answer invalid twice; fix_check.py:659-690, second_look.py:743-752), leaves the refusal standing, so a judge-only "no" still REJECTS the take. The Owner's «Aleg totuși acest clip» or the Director's look can still choose a rejected clip |
| A vendor delivered a file the scene already holds | CODE_RULE | :2761-2770 | Only when `take_id` names a SUBMITTED purchase row, which only the staircase in part 2 passes: that row → REJECTED `VENDOR.DUPLICATE_FILE`, credits kept on the books. No caller in this part passes `take_id`, so a same-file purchase here updates the existing row of that file in place, status included (:2771-2772, :2807) |
| Whether the Owner may choose a given clip | CODE_RULE | :5335-5413 | shot kind, status PAID/APPROVED/REJECTED, file on disk with the bought sha256, identity matches the scene's current still and motion prompt; codes in `CLIP_CHOICE_OFFERS` (:5273-5286) |
| Which clip the Owner chose | OWNER | :5445-5478 | among APPROVED shot takes, the one whose newest Owner decision (`media.scene_take_decided`, `decided_by` owner, or no `decided_by` at all, :5431) is APPROVED, latest first, identity and file still matching |
| Whether an Owner approval is "final" | OWNER | :8118-8123 | note matches `\b(final[aăe]?|definitiv[aăe]?)\b` |
| Which music bed, levels and ambience | LLM_CHECKED_BY_CODE | :5831-5853, :5699-5757 | Voice Artist's `SoundPlan` validated against the library and scenes (backend/app/media/sound_design.py:171-228); re-verified here by track kind (`_tracks_of_plan`; the sha256 check applies only on a remix, where `made_with` is passed, :5933-5935, not in `film_mix`, :5853); levels bounded by the mixer; deterministic plan when no model or refused twice |
| Film with no music | OWNER (card) + CODE_RULE | :5855-5867 | advisory text; if the library has no music track, `decisions.sources.film_without_music` raises the music card |
| Mix failure | CODE_RULE | :5879-5885 | the film keeps the voice only, with an Owner warning |
| Mastering loudness | CODE_RULE | :7316-7332 | `toolchain.encode_master_audio`: -14 LUFS, -2.0 dBTP target, -1.0 dBTP ceiling, 48 kHz, one AAC encode |
| Captions burnt in or not | CONFIG / OWNER setting | :4013-4026, :7288 | `settings.captions_burn_in` (default True), Inter Bold sha256 intact, encoder has `subtitles`, there are cues |
| Caption cards | CODE_RULE | :485-568 | 2-5 words, two lines of ≤ 42 chars and ≤ 776.64 px, never end a card on a function word |
| Grade toward the hero | CONFIG + CODE_RULE | :2153-2291 | `finish.grade.match_to_hero`, strength 0.6; gain 0.8-1.25, saturation 0.75-1.25, chroma shift ±6 |
| Second framing (punch-in) | CONFIG + LLM_CHECKED_BY_CODE (centre) | :2318-2385 | enabled in the finish, words > 3.2 s, cut at a caption start ≥ 1.2 s from both ends; centre from `prompt_json.second_framing` (model-written) clamped to [0,1], else (0.5, 0.45) |
| Fail the render for a short shot / short picture | CODE_RULE | :7439-7450, :7556-7566 | shot frames < span frames → FAILED; picture + 1.0 s < film length → FAILED |
| Film licence status | CODE_RULE over OWNER statements | :6208-6233, :6055-6091 | LICENSED only when every component carries `commercial_use True` (the Owner's statement on the connection, stamped on the take); else NEEDS_REVIEW |
| Ask the Owner about commercial use | OWNER (card) | :6248-6253 | NEEDS_REVIEW → `decisions.sources.film_needs_review` (one card per vendor connection) |
| Book the film's measured step spend once | CODE_RULE over EXTERNAL balances | :3658-3740 | step events' `balance_before - balance_after > 0`; keys already in an `economy.credits_measured` event are not booked again |
| Record model outcomes as benchmark or functional test | CODE_RULE | :1413-1496 | a caller's `run_kind` wins; else PRODUCTION; else TEST_FUNCTIONAL if the model is ADMITTED (CANDIDATE/PRODUCTION/PREFERRED, backend/app/integrations/lifecycle.py:55) else TEST_BENCHMARK |
| Re-plan the sound in an audio repair | CODE_RULE trigger, LLM_CHECKED_BY_CODE plan | :7908-7921, :7786-7848 | only when the newest QC report's `audio_mix_qc.passed is False`; new plan must differ and add no lift |
| Accept an audio repair | CODE_RULE | :7940-7947 | video stream sha256 before and after the remux must be identical, else the repaired file is deleted |
| Paid step error is never retried | CODE_RULE | :8236-8247 | `SpentStageError.fault_class = "HARD"` |
| HTTP answer of a refused motion step | CODE_RULE | :8150-8152 | NEEDS_APPROVAL → 202, every other status → 409 |

## LLM involvement

**LLM call sites in these lines: none.** No function in lines 1-8300 calls
`run_agent_task`, `structured_run`, `run_with_strategy`, `reviews._run` or `prompt_agent._run`
itself (static AST analysis, docs/project/backend_map/inventory.json; confirmed by reading).

### Functions here that reach the LLM indirectly

| function | line | path to the model | what the model decides there |
|---|---:|---|---|
| `film_mix` | 5788 | `sound_design.sound_plan` (backend/app/media/sound_design.py:379) → `agents.structured.structured_run` → `run_agent_task` | the film's sound plan |
| `_replan_sound` | 7786 | same `sound_plan`, with `previous` and `refusal` | a changed plan after QC refused the mix |
| `repair_audio` | 7851 | `_replan_sound` (only when the newest QC report's audio mix check failed) | as above |
| `assemble_video_job` | 6257 | `film_mix` (:7304) | as `film_mix` |
| `assemble_from_takes` | 3489 | `assemble_video_job` (:3606) | as `film_mix` |
| `propose_clip_redos` | 4947 | `redo_scene` (:14994, outside this part) with `kind="motion"` → `_paid_redo` (:15249) → `run_motion_step` (:11426) → `_check_shot` (:10245) → `picture_qc.judge_clip` (backend/app/media/picture_qc.py:2074) → `structured_run`; and `_check_shot` → `qc.qc_clip_with_retry` (backend/app/media/qc.py:2626; `_looked`, qc.py:2616-2623) → its `look` closure (assembler.py:10334-10346) → `fix_check.shot_second_look` (backend/app/media/fix_check.py:713) → `fix_check.director_second_look` (fix_check.py:642) → `second_look.second_look` (backend/app/media/second_look.py:583) → `second_look._look` (second_look.py:653; `structured_run` at :720) | the vision judge inside clip QC of the redone clip; and, when clip QC refuses that clip on a refusal `qc.look_may_overturn` allows (backend/app/media/qc.py:2588-2606), the Director's second look decides whether the clip is kept as hers (nothing more bought) or the refusal stands, so the one retry is bought within the cap or the scene is escalated (qc.py:2670-2683); a failed retry is shown to her once more (qc.py:2734-2751). The static call graph also shows `picture_qc.judge_still` and `second_look._look` on the still branches: `_judge_paid_stills_first` → `stills_stage.settle_stills` (assembler.py:15123-15129) and `_paid_redo` → `_redo_still` (assembler.py:15348) → `_redo_still_rounds` / `_StillRedoBuyer.run` (`stills._settle_round`, assembler.py:16571), both taken only for `kind == "still"`; and `sound_plan` via the audio redo (`_free_redo`, assembler.py:15548-15587). None of these branches is taken for the `kind="motion"` this function passes |

### The sound plan, as `film_mix` and `_replan_sound` use it

- **Speaker:** the agent holding role `VoiceArtist` (`SOUND_ROLE`,
  backend/app/media/sound_design.py:56), found by `agent_for_role` (sound_design.py:413). The
  code calls her "the sound department" and uses "her" (:5857; sound_design.py:10).
- **Task type / template:** `sound_design` / `sound-design-v1` (sound_design.py:57-58); max 3000
  tokens, payload trimmed to 14000 characters (sound_design.py:68-69).
- **What it asks:** one bed from the Owner's music library, a level per scene (`under`, `soft`,
  `lift`), an ambience where a scene's audio intent calls for one, fades, and why in Romanian.
  The brief carries the film title and core message (`_core_message`, :5662), each scene's
  `scene_brief` and a library brief, wrapped in an inert boundary (sound_design.py:418-426).
  On a re-plan it also carries the measured refusal and the previous plan
  (sound_design.py:423-425; `mix_refusal`, sound_design.py:656).
- **Answer shape:** pydantic `SoundPlan` bound per film by `plan_schema` (`BoundPlan`): `bed`
  (a music track id of the library or null), `why` (≤ 400), `scenes: list[ScenePlan]`
  (`scene_index`, `level` ∈ under/soft/lift, `ambience` id or null, `why` ≤ 300),
  `fade_in_seconds` / `fade_out_seconds` clamped to `BED_FADE_BOUNDS` (0.3-4.0 s),
  `summary_ro` (sound_design.py:74-149, 171-228).
- **Checks by code (trust: CHECKED_BY_CODE):**
  1. The schema refuses a bed or ambience not in the library and any scene missing, unknown or
     repeated; on a re-plan it refuses the identical plan and any new `lift`
     (sound_design.py:186-226). `structured_run` asks once more with the reason.
  2. `_tracks_of_plan` (:5699-5757) re-reads every named track from the library at mix time.
     A bed that is not `kind == "music"` or an ambience that is not `kind == "ambience"` is
     dropped, never replaced; on a remix (`made_with`, :5933-5935), so is a track whose
     sha256 differs from the one the film was made with. Placements ≤ 0.2 s are skipped.
  3. The mixer bounds what a level can do (`toolchain.LEVEL_GAIN_DB` under 0 dB, soft -6 dB,
     lift +8 dB only inside the voice's silences; the bed sits 20 LU under the voice,
     backend/app/media/toolchain.py:590-604), and quality control later refuses a mix whose
     bed sits less than 18 LU under the words (sound_design.py:19-23).
- **If the model fails:** no registry, no active VoiceArtist, an exception, or a second
  invalid answer → the deterministic plan (`deterministic_plan`: today's bed by mood words,
  every scene "under"), with the reason recorded in `production['audio']['plan']`
  (sound_design.py:400-478). `film_mix` never fails because of it.
- **Informational output:** when the plan names no bed but the library has music, the plan's
  `why` becomes the film's advisory text (:5856-5860) — INFORMATIONAL.
- **Money:** the call spends LLM tokens under `run_agent_task`'s token ceiling and USD budget;
  it buys no media (library tracks are local files).

### LLM-written data this code consumes (not calls, but inputs written by models upstream)

| input | written by (upstream) | used here | how code bounds it |
|---|---|---|---|
| `visual_prompt` | storyboard / prompt compiler | sent to the image vendor (:2866, :2957) | stills gate and shooting-sheet lint upstream; here only `strip_on_screen_text` on the degenerate retry (:2867) |
| `prompt_json` motion package | prompt agent (`write_shot_prompts`, spec 08 item 1) | `motion_request` → `prompt_agent.motion_prompt_for` (:1264-1282); motion take identity (:2590-2611) | deterministic dialect rewrite; adapter fits length |
| `prompt_json.second_framing` centre | prompt agent | punch-in centre (:2318-2325) | clamped to [0,1] (:2377), crop kept inside the frame (:2328-2334) |
| `prompt_json.audio_intent`, `story_purpose`, `voiceover_segment` | script writer / storyboard | mood text (:5673-5685), tier (:1523-1530), narration and captions | code rules only |
| `transition_in` | storyboard | cut or dissolve (:1713-1735) | only five words select a dissolve, length fixed at 8 frames |
| `story_json.hook` | script writer | cover and optional headline (:2396-2413) | headline wrapped to 3 lines of 26 chars (:1070-1071); cover refused if the font cannot draw it (:2459-2463) |
| clip-QC verdict | `qc.check_clip` incl. `picture_qc.judge_clip` (outside this part); for a refused clip on the motion staircase, the Director's second look (`second_look._look`, via part 2's `_check_shot`) | `clip_accepted` (:5204-5225), `_keep_clip_report` (:5146) | The verdict mapping is code (:5128-5133). The vision judge's "no" alone makes it FAILED, and `_keep_clip_report` then REJECTS a PAID take (qc.py:2009-2075). A keep by the Director's second look is stored as verdict PASSED with `accepted_by` `director_look` (assembler.py:10361-10373); code bounds only which refusals she sees (qc.py:2588-2606) and the consistency of her answer (`SecondLook`, second_look.py:88-135). Any APPROVED status overrides a FAILED, the Owner's or the Director's |
| `SceneTake.status` APPROVED (stills and shots) | the Owner (`decide_take`, :9779); the Director's look (an LLM choice among offered candidates, backend/app/media/director_qc.py:2069-2150); the stills gate's choice (vision judge `picture_qc.judge_still` + `still_gate.decide`, backend/app/media/stills_stage.py:912-962); the Director's second look on a still the gate refused (stills only, backend/app/media/stills_stage.py:1017-1077); the rehearsal (backend/app/media/rehearsal.py:579, :1037) | `usable_take(statuses=("APPROVED",))` for takes-only stills (:2879, :3542) and the sheet's still sha (:5496-5503); `clip_accepted` (:5211); APPROVED-first ranking (:2690, :4138) | `approved_by` is never read in these lines. The Director's choice is limited to candidates `clip_choice` finds eligible, and at write time is checked only for staleness (director_qc.py:2000-2004, :2048-2066). The stills gate's choice runs its local checks first (stills_stage.py:934-941). Her second look sees only candidates `still_gate.may_be_overturned` allows (still_gate.py:1118-1130) |

### Model-made approvals the acceptance rules read

The code's own docstrings and comments often say "his APPROVED" (:3499, :5207, :6868). In the
code, the test is `SceneTake.status == "APPROVED"` (:5211; `usable_take` :2686), and four
writers outside this part set it:
- the Owner (`approved_by` owner);
- the Director's look (`approved_by` director). Her choice among refused candidates can turn
  a still the gate refused, or a clip that clip QC REJECTED, into APPROVED. Shots are offered
  to her only if `clip_choice` (:5335) finds them eligible (director_qc.py:2000-2004). At write
  time `_choice_refused` (director_qc.py:2048-2066) checks only staleness. `clip_accepted` then
  lets such a clip into a PRODUCTION film;
- the stills gate (`approved_by` still_gate, stills_stage.py:961-962), for stills;
- the Director's second look (`approved_by` director_look, stills_stage.py:1026-1027), for a
  still the gate refused, asked before a re-roll, a rewrite or the Owner's question in the
  stills step and in part 2's paid still redo (`stills_stage._settle_round`,
  stills_stage.py:1110-1184, look at :1143-1148), and on collected candidates the gate refused
  (`_settle_pending`, stills_stage.py:1254-1260). The failure code is cleared on the take
  (stills_stage.py:1028-1029).

For clips, her second look writes no APPROVED status. A clip it keeps stays PAID and its
clip-QC record says PASSED (`accepted_by` director_look, assembler.py:10361-10373), which
`clip_accepted` accepts like clip QC's own pass (assembler.py:5215-5216).

The constant comment "Who may approve or reject a take: the Owner, on the sheet. Nobody else."
(:8111-8112) describes `decide_take` and `owner_take_decisions` (which do filter on
`decided_by`). It does not describe the status these lines test. So "accepted",
"approved still" and "APPROVED first" in this part mean "approved by the Owner, the Director's
look, her second look or the stills gate", and "a passing report" means "passed by clip QC or
kept by her second look". Only `owner_clip_choice` (:5445) and `owner_take_decisions` (:5416)
are the Owner's alone.

**How much is LLM here:** of the 200 functions in lines 1-8300, none calls a model. 6 reach one
through other modules: the sound plan in `film_mix`, `_replan_sound`, `repair_audio`,
`assemble_video_job` and `assemble_from_takes`, plus clip QC's vision judge and the Director's
second look (`second_look._look`, the 38th call site) on `propose_clip_redos`'s redo path. The
static call graph from `propose_clip_redos` reaches four call sites: `sound_design.sound_plan`,
`picture_qc.judge_clip`, `picture_qc.judge_still` and `second_look._look`. Every purchase,
timing, encode and licence decision here is made by deterministic code, the Owner's recorded
choices, configuration or a vendor's answer. The acceptance decisions are the exception.
`clip_accepted`, the takes-only still lookup and `_keep_clip_report` act on verdicts that
models wrote upstream: the Director's look, her second look, the stills gate's vision judge and
clip QC's vision judge. Code checks those verdicts only for staleness and identity, or, for a
clip QC "keep", adds its own measured checks. A keep by her second look can stand against a
failed measured check (motion floor, cut); code only decides which refusals she may see
(qc.py:2588-2606; still_gate.py:1118-1130), checks her answer for consistency (`SecondLook`,
second_look.py:88-135) and reads it through `fix_check.look_accepts` (fix_check.py:693-703).
It never re-checks what she says she sees.

## Hard rules and limits

| name | value | where | meaning |
|---|---|---|---|
| `TRANSITION_SECONDS` | 0.4 s | :153 | headroom a shot is asked for beyond its scene; `motion_seconds` adds it (:8365-8371) |
| `TIMELINE_FPS` | 24 | :157 | the film's frame rate (vendor native) |
| `DISSOLVE_SECONDS` | 8/24 ≈ 0.333 s | :159 | a dissolve where the script asks |
| `DISSOLVE_WORDS` | DISSOLVE, CROSSFADE, CROSS_DISSOLVE, MIX, FADE | :162 | `transition_in` words that mean dissolve |
| `SPOKEN_TAIL_SECONDS` | 0.12 s | :172 | breath after each scene's words |
| `MOTION_DEADLINE_SECONDS` / `MOTION_POLL_SECONDS` | 600 s / 5 s | :175-176 | motion poll (adapter's `timeout_seconds` overrides, :1347) |
| poll download retries | 2 | :1356 | `attempts > 2` raises |
| `run_encoder` timeout | 600 s | :207 | FFmpeg killed → `RenderEngineUnavailable` |
| `CAPTION_LINE_CHARS` / `CAPTION_MAX_LINES` | 42 / 2 | :341-342 | SRT and QC caption rule |
| `CAPTION_MIN_WORDS` / `CAPTION_MAX_WORDS` | 2 / 5 | :347-348 | caption card size |
| `CAPTION_FONT_SIZE` / `CAPTION_OUTLINE` / `CAPTION_MIN_FONT_SIZE` | 74 / 3.5 px / 40 | :364-367 | ASS style; a card shrinks, never below 40 (:1076-1080) |
| `CAPTION_BOTTOM_Y` / `CAPTION_RIGHT_CLEAR` / `CAPTION_MARGIN_V` / `CAPTION_MARGIN_X` | 1500 / 120 / 432 / 132 | :370-376 | safe area |
| `CAPTION_LINE_PX` | (1080 − 264 − 7) × 0.96 = 776.64 px | :379 | widest caption line |
| `HEADLINE_MARGIN_V` / `HEADLINE_FONT_SIZE` | 420 / 84 | :968-969 | optional hook headline |
| `FIRST_FRAME_WIDTH` / `FIRST_FRAME_QUALITY` | 1080 / "2" | :1221-1222 | first frame re-encoded so Runway does not answer 413 |
| `INTERMEDIATE_VIDEO_ARGS` | x264 High, veryfast, CRF 4, yuv420p, BT.709 tv | :1639-1651 | shot intermediates |
| `final_video_args` | x264 High 4.2, slow, CRF 17, maxrate 14M, bufsize 28M, 2 B-frames, GOP fps/2, no scene-cut keyframes, +faststart | :1654-1689 | delivered film |
| `SLOWDOWN_ALLOWANCE` | 0.25 | backend/app/media/cost_plan.py:74 | a clip may be slowed by at most 25% |
| `SLOWDOWN_EXTRA_FRAMES` | 2 | :1807 | interpolation asked 2 frames past the span |
| `SLOWDOWN_FILTERS` | minterpolate, framerate | :1809 | best first; fallback to framerate when minterpolate crashes (:7413-7429) |
| `GRADE_GAIN_RANGE` / `GRADE_SATURATION_RANGE` / `GRADE_MAX_CHROMA_SHIFT` / `GRADE_DEFAULT_STRENGTH` | (0.8, 1.25) / (0.75, 1.25) / 6.0 / 0.6 | :2054-2057 | grade bounds |
| `_GRADE_NEGLIGIBLE` | gain 0.01, offset 0.5, saturation 0.01, shift 0.5 | :2059 | below this no grade |
| `measure_picture` | every 12th frame at 270 px, 300 s timeout | :2063-2093 | signalstats sample |
| `SECOND_FRAMING_MIN_PART` | 1.2 s | :2311 | each part of a split scene |
| `SECOND_FRAMING_CENTRE` | (0.5, 0.45) | :2313 | default punch-in centre |
| `REUSABLE_TAKE_STATUSES` | APPROVED, PAID | :2492 | takes that may be reused |
| `TAKE_DETAIL_MAX` | 500 chars | :2512 | vendor reason stored on a take |
| `SHOT_TAKE_KINDS` | test_shot, motion | :2514 | take kinds that are a scene's shot |
| `SPEND_STEP_EVENTS` | media.stills_step_finished, media.motion_step_finished, media.scene_redone | :3643-3647 | step events carrying balance before/after |
| `_CLIP_SECONDS_MAX` / `_FILE_SHA_MAX` | 4096 entries | :4144, :5306 | process-wide caches cleared when full |
| `SECONDS_PER_SPOKEN_WORD` | 0.40 s | :4200 | narration estimate (measured on babcf272) |
| `NARRATION_ESTIMATE_MARGIN` | 10% | :4204 | added to an estimated narration |
| `MEASURED_NARRATION_MARGIN_SECONDS` | 2/24 s | :4206 | added to a measured narration |
| `FASTEST_SPOKEN_SHARE` | 0.75 | :4214 | the shortest an estimate can turn out |
| `UNTIMED_TRIM_MAX_SECONDS` | 1.0 s | :4217 | most a render can trim from an untimed take |
| `_HALF_FRAME` | 0.5/24 s | :4242 | a clip this close to its span covers it |
| `MAX_SILENT_CARD_SECONDS` | BLACK 2.0, TITLE_CARD 2.5, DATA_CARD 4.0 | backend/app/media/qc.py:1597 | silent card ceilings used by `scene_spans` |
| `SPEAKER_GAP_SECONDS` | 0.3 s | backend/app/media/speaker_voices.py:52 | breath between two speakers |
| loudness | -14 LUFS, TP target -2.0 dBTP, ceiling -1.0 dBTP, 48 kHz | backend/app/media/toolchain.py:129-152 | master |
| `EDGE_KEEP_SECONDS` | 0.03 s | backend/app/media/toolchain.py:585 | silence kept at each edge of a take |
| bed fades | in 0.3 s, out 0.8 s; plan bounds 0.3-4.0 s | backend/app/media/toolchain.py:592-614 | default fades |
| `MOTION_STEP_ACTIONS` | test_shot → `media.test_shot`, motion → `media.motion_purchase` | :8074-8077 | Policy Kernel actions of the staircase |
| `PAID_STEP_BALANCE_MARGIN` | `DEFAULT_MARGIN` = 1.15 | :8083; backend/app/media/balance_rule.py:39 | account must hold 15% more than the next purchase |
| `MOTION_RETRY_KINDS` | TRANSIENT, BAD_OUTPUT, TECHNICAL | :8090 | failures retried once on the same model and seed |
| `MOTION_STEP_RESOLUTION` | 1080p | :8092 | default motion resolution |
| `SEED_RANGE` | 4 294 967 295 | :8094 | seed modulus |
| `TAKE_DECIDER` / `TAKE_DECISIONS` | "owner" / APPROVED, REJECTED | :8112-8113 | Only the Owner decides takes through `decide_take` and the `media.scene_take_decided` events. The APPROVED status is also written by the Director's look, her second look (stills) and the stills gate (see "Model-made approvals") |
| `UNANSWERED_FAILURE_CODE` | VENDOR.UNANSWERED | :8282 | a request that may have been billed, never resent automatically |
| `CANCELLED_FAILURE_CODE` / `NOT_QUEUED_FAILURE_CODE` | RUNPOD.CANCELLED / RUNPOD.NOT_QUEUED | :8296-8298 | refusals that cost nothing |
| `UNCOUNTED_DROP_TOLERANCE` | 0.5 credits | :8315 | rounding before a balance drop counts as unexplained |

**State machines touched here**

- `SceneTake.status` (written by `record_take`, :2716-2819, and `_keep_clip_report`, :5146):
  PAID (bought), REFUSED (vendor refused), REJECTED (degenerate still :2968, duplicate file
  :2765, clip QC FAILED :5162; a clip the Director's second look kept arrives as PASSED and
  stays PAID, :10361-10373), APPROVED (outside this part: the Owner's `decide_take` :9779,
  the Director's look backend/app/media/director_qc.py:2145, the stills gate
  backend/app/media/stills_stage.py:961, the Director's second look on a still
  backend/app/media/stills_stage.py:1026, the rehearsal backend/app/media/rehearsal.py:579).
  SUBMITTED and LOST are read here (:4912, :5365, :8161-8165) and written by the motion
  staircase outside this part.
- `VideoRenderJob.status`: RENDERING (:6400-6413) → FAILED (`_fail_job`, :6479-6507) or
  COMPLETED (:7624-7633); the audio repair writes a new COMPLETED job (:8022-8036).
- `Storyboard.status` → RENDERED on success (:7636-7638).

## Modules

### `app.media.assembler` — backend/app/media/assembler.py (16716 lines; part 1: lines 1-8300)

Purpose: deterministic FFmpeg assembly of a film and the take, readiness, spend and licence
bookkeeping around it (see "In one paragraph"). Why: see "Why it exists". The tables below are
grouped by topic, in file order.

#### A. Process plumbing and placeholders (:127-336)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `_at_work` | 127 | context manager marking an agent role WORKING (via `agents.services.at_work`), a no-op for placeholders | the office view shows who is working; no LLM call | — |
| `media_root` | 141 | the film folder: the Owner's `STUDIO_MEDIA_ROOT`, else `DEFAULT_STORAGE_ROOT` (`backend/storage/media`) | REL-08: every entry resolves the same root | CONFIG |
| `concat_line` | 192 | one FFmpeg concat-list line with single quotes escaped | SEC-09: a folder named O'Brien broke the list | — |
| `run_encoder` | 202 | runs FFmpeg in a fresh short temp folder, copying `carry` files there; timeout 600 s; launch failure or timeout → `RenderEngineUnavailable` (Romanian) | Windows refuses a cwd longer than MAX_PATH (WinError 267 measured 2026-10-01, :212-215) | CODE_RULE |
| `motion_stop_reason` | 284 | shutdown vs Owner-switch wording for the motion step | 2026-10-12 00:03: the serial's step blamed the Owner during a restart (:275-277) | CODE_RULE |
| `render_stop_reason` | 291 | same for a render | same | CODE_RULE |
| `resolve_ffmpeg_path` | 298 | delegates to `toolchain.find_ffmpeg` | renderer, QC and preflight used to disagree whether FFmpeg existed (:301-305) | CONFIG |
| `write_placeholder_frame_ppm` | 316 | writes a binary PPM gradient frame per scene | an honest placeholder frame QC blocks from publication | — |

Helpers: `_scene_palette` (:309) — gradient colours by scene index.
Classes: `RenderEngineUnavailable` (:184, no encoder or encode failed; routes answer 503),
`RenderStopped` (:255, the Owner's stop between scenes; reported BLOCKED, not FAILED).

#### B. Captions (:338-1123)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `format_srt_timestamp` | 390 | seconds → `HH:MM:SS,mmm`, rounded once | rounding the fraction alone printed 1000 ms | — |
| `caption_cards` | 485 | a passage's words as cards of 2-5 words; `_segmented_cards` first, greedy walk as fallback | audit Q7: "Nepal is paying for a" / "crisis it did not create." broke phrases (:490-494) | CODE_RULE |
| `_segmented_cards` | 535 | dynamic programming over cut points: cost 10 for ending on a function word, 1 for not ending on a sentence/clause mark, 0.2 per word away from 4 | a cut chosen whole (2026-10-02) | CODE_RULE |
| `words_from_alignment` | 571 | ElevenLabs character alignment → words with start/end | captions on the voice's own clock | — |
| `take_word_timing` | 612 | the take's word timing: vendor alignment first, else adapter `word_timings`; never estimated | same | CODE_RULE |
| `_trimmed_take` | 648 | decodes the take to 48 kHz/24-bit WAV, measures silent edges, cuts all but 0.03 s each side without cutting a timed word, shifts the timing; the vendor file is untouched; on failure returns the take as it came with the reason | audit Q4: 0.28-0.61 s of digital silence at every cut (:168-171) | CODE_RULE + EXTERNAL timing |
| `_aligned_starts` | 764 | word starts from the take timing when it matches the words, in order, inside the take | captions only use timing that is about these words | CODE_RULE |
| `caption_cues` | 782 | cues per scene from `audio_seconds` (≤ the planned span), per speaker take where a scene has `voice_segments`; no cue for a scene without words | captions never invented from a visual prompt (:790-791) | CODE_RULE |
| `_timed_cues` | 833 | cards timed by word starts (`alignment`) or shared by characters (`character_share`); per-word highlight times | word-by-word highlight (audit Q7) | CODE_RULE |
| `_cue` | 904 | one cue dict; attaches lit word times only when the lines carry exactly these words | a word cut across lines is not highlighted | CODE_RULE |
| `srt_from_cues` | 934 | cues → SubRip text | the platform's caption track and QC's reading | — |
| `generate_subtitles_srt` | 945 | `srt_from_cues(caption_cues(scenes))` | public helper; only tests call it (tests/test_phase5_media.py:689) | — |
| `ass_colour` | 972 | `#RRGGBB` + alpha → `&HAABBGGRR` | ASS colour format | — |
| `_highlighted` | 984 | ASS override tags lighting each word while spoken, numbers in the emphasis colour | audit Q7 | CONFIG (finish colours) |
| `ass_from_cues` | 1016 | the full ASS script: Inter Bold 74, outline, shadow, optional headline for `finish.headline.seconds`; per-card shrink to fit (≥ 40) | burnt captions inside the safe area | CONFIG + CODE_RULE |
| `install_caption_fonts` | 1089 | copies Inter Bold into `fonts/` after checking its pinned sha256; raises `FontIntegrityError` otherwise | nothing burnt with whatever face the system has | CODE_RULE |
| `ass_captions_filter` | 1109 | `subtitles=filename=captions.ass:fontsdir=fonts` (relative paths) | Windows absolute paths would need double escaping | — |
| `captions_filter` | 1119 | legacy SRT burn with `CAPTION_STYLE` | a one-scene redo of an older film keeps its captions (used at :14782) | — |

Helpers: `_wrap_words` (:401, greedy wrap, long words cut), `_caption_px` (:422, width from the
bundled font's metrics, estimate if missing), `_fits_line` (:436), `_card_lines` (:440, one or
two balanced lines or None), `_ends_with` (:456), `_release_dangling` (:460) and
`_mend_dangling` (:471) (move trailing function words to the next card), `_shift_times` (:636),
`_ass_time` (:950), `_ass_text` (:959, neutralises braces and backslashes), `_override_colour`
(:979).

#### C. Narration join, first frame, motion request, poll and quote (:1125-1411)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `_concatenate_audio` | 1140 | joins narration files with FFmpeg into a 48 kHz/24-bit WAV, padding each with `apad` where a pause is given; raises `RenderEngineUnavailable` on failure | vendor audio must be decoded, not byte-spliced; the one lossy encode is the master's | — |
| `_first_frame` | 1225 | re-encodes the still to 1080 px wide JPEG q2 | a 12 MB still became 17 MB base64 and Runway answered 413 (:1218-1220) | — |
| `motion_request` | 1252 | (prompt, extra) for the video model: compiled motion prompt in the model's dialect (`prompt_agent.motion_prompt_for`, deterministic), the picture's words first when filmed from words, negative prompt in `extra` | the model already sees the still; never the still's words again | CODE_RULE |
| `_generate_motion` | 1285 | submits the shot (`adapter.create_generation`, 9:16, optional seed, optional `prompt_text`), calls `on_submitted(task_id)` before polling, then `_await_motion`; any non-FAILED loss → `TaskStillOpen` (collected later, never re-bought) | from the submit on, the shot may be billed | EXTERNAL |
| `_await_motion` | 1344 | polls `get_generation_status` every 5 s until COMPLETED with bytes, vendor FAILED (`MotionTaskFailed` with code/detail) or deadline | the vendor's code decides move/retry/Owner downstream | EXTERNAL + CODE_RULE |
| `_quote_motion` | 1378 | asks `estimate_generation` (dry run) only of adapters that offer it, with the same body as the purchase; None on any error | "a price per second written down somewhere is a guess" (:1390-1391) | EXTERNAL |

Class: `MotionTaskFailed` (:1339, a `MediaProviderError` carrying the vendor's failure code).

#### D. Outcomes, tiers, prices, loudness records, measurement (:1413-1697)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `_record_outcomes` | 1413 | writes a `ModelOutcome` per generated shot (not reused): run kind, seconds, credits, USD, accepted = landed, failure kind; DB errors only logged and noted | "a model's worth is ... what it delivered, for what it cost" (:1424-1427); a cheap functional test must not teach the studio a model is poor | CODE_RULE |
| `scene_tier` | 1511 | the scene's quality tier (stated tier, stated role, purpose, position); the stated tier and role are never present in the render's `scene_view` dicts, its only caller (:6860) | the hook and the ending are asked for more | CODE_RULE |
| `_credit_price` | 1533 | the first USD-per-credit found on any `Integration` row (`config["credit_usd"]`, the Owner's statement, production_policy.py:541-555), in no particular order and not necessarily the motion adapter's own connection | quotes in credits → USD | OWNER (recorded price) |
| `_loudness_record` | 1567 | the manifest's mastering record (targets, filter, limiter, codec, readings, warning) | QC and the Owner read it | — |
| `final_video_args` | 1654 | the delivered film's x264 arguments | "what a phone screen needs"; the Nepal film had 2.6 Mbps (:1657-1659) | CODE_RULE |

Helpers: `_loudness_readings` (:1546, finite numbers or None), `_shot_frames` (:1592, ffprobe
frame count), `_video_stream_seconds` (:1600, frames/fps else duration), `_audio_output_args`
(:1692, copy the master or encode a chain).

#### E. Timeline, shots and the edit (:1699-2031)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `whole_frames` | 1706 | seconds on a frame boundary (nearest or up), ≥ 1 frame | shots end to end never drift from the voice | CODE_RULE |
| `is_dissolve` | 1713 | `transition_in` ∈ `DISSOLVE_WORDS` | hard cut is the default since 2026-10-01 | CODE_RULE |
| `scene_joins` | 1719 | join length per scene (0 = cut; first scene always 0; recorded `dissolve_seconds` kept) | older films rejoin as they were | CODE_RULE |
| `shot_spans` | 1738 | scene length + the next scene's dissolve overlap | each shot file length | CODE_RULE |
| `scene_spans` | 1748 | words + breath on whole frames, never cutting a word; silent cards capped; others keep the plan | QC's length budget counts the breaths (`qc.film_length_budget`) | CODE_RULE |
| `slowdown_filter` | 1812 | best available interpolation filter | minterpolate preferred, framerate in every build | CODE_RULE |
| `_shot_command` | 1827 | FFmpeg args for one scene: the clip scaled/cropped/dithered, optionally slowed and interpolated, trimmed to exact frames; or the still with a 10% zoompan push | a single graph over eight inputs hid its own failure (:1847-1850) | CODE_RULE |
| `_shot_source` | 1893 | what a shot was cut from (still/clip sha256, card, hold, slow, interpolation, dither, fps) | rebuild a released intermediate exactly | — |
| `_shot_record` | 1922 | one shot as the manifest keeps it | a one-scene redo rejoins the others | — |
| `_dissolve_command` | 1938 | the film's single edit: per-shot grade, second-framing split + crop, concat or xfade joins, LUT, grain, captions burn, BT.709 tagging, audio copy or encode, `-t` total | shot N starts where scene N's words start | CODE_RULE |

Helpers: `_dither_chain` (:1784, zscale error diffusion or plain format), `_slow_chain`
(:1817, setpts + minterpolate/framerate).

#### F. One look, second framings, hook, LUT, cover (:2033-2480)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `measure_picture` | 2062 | signalstats means (Y low/high/avg, U, V, saturation) of a picture or shot | the grade and QC need numbers | — |
| `_lab` | 2116 | a measurement's mean Y/U/V (BT.709 limited range) converted to linear RGB, CIE XYZ and L*a*b* (D65) | `delta_e` compares colours perceptually, not in YUV | — |
| `delta_e` | 2143 | Delta E 1976 between two measurements | the grade's before/after distance for QC | — |
| `grade_toward` | 2153 | a bounded `lutyuv` pulling a shot part-way to the hero; None when negligible | audit Q8: Nepal stills jumped between storm blue, orange mud and sunny sky (:2034-2040) | CODE_RULE + CONFIG (strength) |
| `film_grade` | 2221 | measures the hero (first filmed shot) and grades every other filmed shot; cards untouched; records Delta E before/after | one look, 0 credits | CONFIG (`finish.grade`) + CODE_RULE |
| `framing_crop` | 2328 | crop rectangle of a punch-in inside 1080x1920 | audit Q6 | CODE_RULE |
| `plan_second_framings` | 2337 | where each long LIVE scene cuts to a 1.15x punch-in (finish values) at the caption start nearest its middle | one picture per ~5 s scene was slow for a short (:2304-2308) | CONFIG + CODE_RULE; centre LLM_CHECKED_BY_CODE |
| `film_hook` | 2396 | `story_json['hook']` of the script, else the first sentence said | cover and headline text | LLM-written data, used as is |
| `film_cover` | 2432 | composes `cover.png` from the hero still and the hook (`cards.compose_cover`), 0 credits; reasons recorded when off, no still, no hook or font error | audit Q14 | CONFIG (`finish.cover.compose`) |

Helpers: `_clamp` (:2149), `_shot_grade` (:2294),
`_framing_centre` (:2318, model-given centre or default), `_install_lut` (:2416, copies a
`.cube` from `config/luts` beside the film, records its sha256, drops a missing one).

#### G. Take identity, failure records, take recording (:2483-2836)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `scene_kind_of` | 2546 | LIVE / DATA_CARD / TITLE_CARD / BLACK; unknown → LIVE | cards never reach a model | CODE_RULE |
| `is_composed` | 2552 | a card scene (0 credits) | the Nepal chart and black screen came back from a photo model "as women" (:6554-6556) | CODE_RULE |
| `take_hash` | 2565 | sha256 of canonical JSON of the fields + model id | one identity, never bought twice | CODE_RULE |
| `still_fields` | 2576 | still identity: normalised words, resolution, reference picture sha256 | a new reference is a new still | CODE_RULE |
| `motion_fields` | 2590 | shot identity: motion package keys (or visual prompt), first-frame sha256 unless from prompt, resolution; length excluded | a clip resized anew never orphans a bought take | CODE_RULE |
| `failure_code_of` | 2614 | vendor code or `HTTP_<status>` | failure memory | — |
| `failure_detail_of` | 2623 | sanitised vendor reason with refused fields, ≤ 500 chars | Runway's 400 names the field; dropped, the studio changed models instead of fixing the request (:2626-2627) | — |
| `classify_vendor_failure` | 2647 | `production_policy.classify_failure` over code, status, detail, previous kind | SAFETY / CONTRACT / TRANSIENT / ACCOUNT routing | CODE_RULE |
| `usable_take` | 2659 | the newest reusable take for a scene/kind matching one of the field options, file and sha256 intact, APPROVED first, optional model filter and minimum length | reuse instead of buying | CODE_RULE |
| `record_take` | 2716 | Writes or updates one take row (write lock first) and `media.scene_take_recorded`. With `take_id` (a SUBMITTED row, passed only by the part-2 staircase), a duplicate delivered file makes that purchase REJECTED `VENDOR.DUPLICATE_FILE`. Without `take_id`, as every call in this part makes it, a row with the same scene, kind, prompt hash and file sha256 is updated in place, status included | the row that says money went out must not be lost to a concurrent reader (:2741-2743) | CODE_RULE |

Helpers: `_file_sha256` (:2557), `_quoted_credits` (:2822, adapter's
`last_estimated_credits`), `_take_file` (:2830, copies a take into the render folder).
Classes: `TakesMissing` (:2517, a LIVE scene has no approved still; raised before a job
exists), `ClipsNotAccepted` (:2525, PRODUCTION would show a still the Owner did not choose;
carries `scenes`, `message_ro`, `details`).

#### H. Stills (:2839-2995, :3380-3486)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `_still_for_scene` | 2839 | One LIVE still: a usable take, or one bought through `factory.still_from_chain` (the resolved vendor plus at most one Owner-approved alternative). With `takes_only` it uses only an APPROVED take, from any approver, and buys nothing. It records REFUSED on vendor errors, checks degeneracy and buys one retry. It returns the still, the attempts and the take info | money: each still is a take; a scene of stripes "costs the film" (:2970-2971) | CODE_RULE (+ EXTERNAL vendor answer) |
| `buy_stills` | 3380 | the stills step loop: cards composed, Owner stop read per scene, `_still_for_scene` per LIVE scene, failure classification stops the step; returns counts | "the purchase itself"; whether it may be bought is the caller's `may_act` (:3399-3400) | CODE_RULE + OWNER (stop) |

Note: `buy_stills` has no caller in `backend/app`; only tests/test_scene_takes.py calls it
(see Oddities). Without `storage_root` it writes under `DEFAULT_STORAGE_ROOT` (:3408), not
`media_root(settings)` as REL-08 asks of every entry (:141-147). The day's stills purchase
lives in `app.media.stills_stage`, which imports `usable_take`, `record_take`,
`still_fields`, `take_hash` and the failure helpers from here.

#### I. Narration bought once (:2998-3377)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `bought_voice` | 3014 | whether a voice's narration is kept as a take: studio adapters only when `factory.is_paid_vendor_adapter`; outside adapters treated as bought | the local stand-in costs nothing to say again | CODE_RULE |
| `stitches` | 3030 | whether the voice class accepts neighbours' words (`ACCEPTS_STITCHING`) | audit Q3 | CODE_RULE |
| `narration_context` | 3035 | previous/next spoken text for every part in film order, skipping silent scenes | intonation runs on across a cut | CODE_RULE |
| `narration_fields` | 3066 | narration identity: words, provider, adapter class and version, voice id/settings, request settings, output format, integration, context | a new voice or setting is a new recording | CODE_RULE |
| `narration_key` | 3105 | `take_hash` of those fields (+ context for a stitching voice) | narration take id | CODE_RULE |
| `reused_narration` | 3129 | a kept narration take (status APPROVED/PAID) with file sha256 and JSON sidecar intact → `TTSResult` marked `reused_take`; buys nothing | MONEY-12 | CODE_RULE |
| `keep_narration` | 3177 | stores a just-bought narration (`narration/scene_NN_<key>.ext` + sidecar) and records a PAID take; never fails the render | the next attempt does not pay again | CODE_RULE |
| `voiced_scenes` | 3245 | scenes whose current words are fully voiced by one voice (sidecar text sha256 and parts), voice-blind | the sheet prices them at 0 | CODE_RULE |
| `narration_to_buy` | 3300 | characters a real voice would actually buy (parts without a reusable take); 0 for the placeholder; calls no voice | the sheet asks for what would really be bought (shooting_sheet.py:3911-3925) | CODE_RULE |
| `scene_view` | 3351 | one `StoryboardScene` row as the render's dict (kind, prompt package, purpose, card spec, words, transition, cast) | one reading of a scene everywhere | — |

Helpers: `_context_fields` (:3054), `_voice_key` (:3114), `_text_sha` (:3121), `_sidecar`
(:3125), `_scene_parts` (:3285, one part per speaker or the whole scene), `_storyboard_scenes`
(:3335, title + scenes, raises `ValueError` if missing).

#### J. Assembly from takes and spend booking (:3489-3740)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `assemble_from_takes` | 3489 | Pre-check: every LIVE scene needs an APPROVED still for its current identity (else `TakesMissing`). Then `assembly_readiness` per scene, with `local_moves=set()`, and the fallback gate (`_require_chosen_stills`, which reads LOCAL_MOVE) before anything is voiced; a refusal records `media.assembly_refused` stage "precheck". Then `assemble_video_job(takes_only=True)`, then `book_film_spend` | assemble without buying any picture; one readiness with the sheet (2026-10-09, babcf272) | CODE_RULE over APPROVED statuses (the Owner, the stills gate or the Director's look) + OWNER (LOCAL_MOVE) |
| `_require_chosen_stills` | 3613 | `qc.require_chosen_fallbacks` re-raised as `ClipsNotAccepted` with per-scene reasons | PRODUCTION shows a still only by the Owner's LOCAL_MOVE | OWNER |
| `film_step_spend` | 3658 | per paid step event (stills, motion, scene redo) the measured balance drop and its USD | the QC letter reads real credits | EXTERNAL (vendor balance) |
| `book_film_spend` | 3702 | books the not-yet-booked steps once through `economy.credits.record_credit_spend` and writes all of them on the render (`booked_now`) | a film assembled again from the same takes books nothing again | CODE_RULE |

Helper: `_credits` (:3652, numeric or None).

#### K. Cards, slow-downs, timeline record, captions file, motion attach (:3743-4083)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `_compose_card_clip` | 3743 | composes one card clip from its spec on the first real still (blurred) or its canvas; 0 credits | a BLACK scene longer than a beat becomes a closing card (audit Q5) | CODE_RULE |
| `_compose_cards` | 3785 | composes every card at its shot span; a spec that cannot be composed fails the job (`RenderEngineUnavailable`), never filmed instead | honest cards | CODE_RULE |
| `_clip_slowdowns` | 3844 | measures each clip; cut / slow (≤ 25%, factor = (frames needed + 2)/frames had) / drop as `CLIP_SHORT`; writes `slowed_scenes` and an Owner warning | the Owner's rule 2026-10-09: never a frozen frame | CODE_RULE |
| `_timeline_record` | 3930 | the manifest's timeline: per scene start/end, join, shot length, moving/composed, slow factor, kind, spoken seconds, second framing; shots on screen and average length | QC reads it (`qc.timeline_spans`) | — |
| `_write_captions` | 3993 | writes `captions.srt` and `captions.ass`, installs the font, decides burn-in, records style, timing source per scene and uncovered characters | the platform track + the burnt captions | CONFIG + CODE_RULE |

Helpers: `_motion_record` (:3832), `_refused_reading` (:3920, the refusal's reading for the
event), `_attach_motion` (:4075).

#### L. Shot reuse, clip length planning and readiness (:4085-4945)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `_usable_motion_take` | 4085 | `_shot_take` in its own session, detached | the hero test shot is kept in the film, never re-bought | CODE_RULE |
| `_shot_take` | 4104 | the Owner's newest clip choice if long enough (else nothing), else the usable motion/test-shot take ≥ `seconds` as measured, APPROVED first | the Owner's choice is never silently replaced (2026-10-10) | OWNER + CODE_RULE |
| `shot_clip_seconds` | 4147 | a shot's length as its file measures (cached by sha256), else billed seconds | the sheet read billed seconds while the render measured the file (2026-10-10, :4152-4154) | EXTERNAL (file) |
| `spoken_words` | 4247 | words a voice says, numbers counted as 1-3 words | narration estimate; also used by `story.review` and `factual.story_review` | CODE_RULE |
| `estimated_narration_seconds` | 4260 | words × 0.40 s | clip sizing before voicing | CODE_RULE |
| `_rendered_narration` | 4265 | per scene the trimmed `audio_seconds` and narration take ids of the newest of the last 5 renders that kept them | the best length source | — |
| `narration_readings` | 4337 | per scene `NarrationReading(seconds, source, least)`: rendered / measured (all parts, any voice per part) / estimated | dialogue scenes stayed ESTIMATED and redos were priced too short (2026-10-10, :4352-4355) | CODE_RULE |
| `scene_narration_lengths` | 4433 | (seconds, source) per scene | shared reader | — |
| `expected_shot_spans` | 4444 | the span the render will cut, from narration lengths | sheet = render | CODE_RULE |
| `clip_plan` | 4469 | per filmed scene the clip length to buy, with source; floor from a refused render's span | a redo bought on a shorter reading would be refused and paid again (:4479-4482) | CODE_RULE |
| `script_clip_seconds` | 4526 | the same estimate per script scene before a storyboard exists | the story review compares a scene with its model's longest clip (2026-10-10, film 6fe6a577) | CODE_RULE |
| `clip_seconds_by_scene` | 4577 | `clip_plan` lengths only | no caller at `20abffd` (Oddities) | — |
| `min_clip_seconds` | 4588 | span / 1.25 | the shortest clip that can be slowed into the span | CODE_RULE |
| `clip_stretch` | 4593 | span / clip, 1.0 when it covers (half a frame) or unknown | — | CODE_RULE |
| `clip_fits` | 4601 | stretch ≤ 1.25 | — | CODE_RULE |
| `clip_short_words` | 4610 | Romanian reason a clip cannot be slowed (percent over 25%) | the Owner's words on the sheet | — |
| `slowed_words` | 4624 | Romanian note of a local slow-down, 0 USD | Owner warning | — |
| `clip_risk_words` | 4632 | Romanian note that a clip may be too short for words not yet measured | "at_risk" readings | — |
| `clip_readiness` | 4646 | the one reading of whether a filmed scene's shot may be cut in: shot (≥ span/1.25), accepted (`clip_accepted`), shot / slowed / at_risk; NO_SHOT or CLIP_SHORT with reasons | the sheet said «Pregătit» while every render refused (babcf272) | CODE_RULE (+ any APPROVED status, the Owner's or the Director's, and the clip-QC verdict, clip QC's own or the PASSED written for the Director's second look, via `clip_accepted`) |
| `assembly_readiness` | 4739 | readiness for every LIVE scene with spans from `narration_readings`; NO_STILL when no approved still; LOCAL_MOVE or TEST make a scene ready as a still; Romanian `reason_ro` | what the sheet shows and the pre-check checks | CODE_RULE + OWNER |
| `record_assembly_refused` | 4845 | writes `media.assembly_refused` with each refused scene's code, seconds, take and `words_sha256` | the sheet, `propose_clip_redos` and `clip_plan` read it | CODE_RULE |
| `_longest_shot_since` | 4903 | the longest shot take (APPROVED/PAID/SUBMITTED) of a scene created after a time | do not redo a scene twice | CODE_RULE |
| `latest_assembly_refusal` | 4919 | the newest refusal event unless a COMPLETED render started after it | the sheet shows it until a film is assembled | CODE_RULE |
| `propose_clip_redos` | 4947 | For each CLIP_SHORT scene of the newest refusal without a long-enough clip bought since: `redo_plan(kind="motion")` priced with `shooting_sheet.price_table_for`, then `redo_scene(unasked=True, proposal=True)`. Records `media.clip_redo_proposed` per scene with status BOUGHT / NEEDS_APPROVAL / refusal / SPENT_STOPPED / UNPRICED | four refusals of scene 3 ended as letters and nothing moved the film (shooting_sheet.py:4103-4104) | CODE_RULE (proposal); Policy Kernel under the Owner's mode and rule (purchase). This may be BOUGHT without a question unless the scene holds a shot the Owner approved (:11676-11699). On the redone clip, clip QC (measured checks and the vision judge) and, on a refusal she may overturn, the Director's second look decide whether the clip is kept, retried once within the cap or escalated (assembler.py:10245-10460; qc.py:2626-2763) |

Helpers: `_timed_seconds` (:4320, a kept take's length by its own word timing, never shorter
than the render's trim), `_voiced_clip_seconds` (:4515), `_words_sha` (:4547), `_refused_spans`
(:4551, spans of the newest `render`-stage refusal while the words are unchanged),
`_percent_longer` (:4606).
Classes: `NarrationReading` (:4301), `_KeptTake` (:4312).

#### M. Clip QC on shot takes and the Owner's clip choice (:5096-5644)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `clip_report_record` | 5111 | a `qc.ClipReport` as a dict with verdict PASSED / FAILED / UNCHECKED | a clip nobody could check waits for the Owner (CLIP_QC_WIRING, 16_DECISION_LOG.md:4072) | CODE_RULE |
| `_keep_clip_report` | 5146 | stores the report as `media.clip_qc_checked`; FAILED on a PAID take → REJECTED `QC.CLIP`; syncs the verdict to the RunPod quality row | a clip measured wrong is never cut in | CODE_RULE over a verdict a vision model can decide alone (a judge's "no" is a blocking FAILED, qc.py:2030-2074); part 2's `_check_shot` hands it PASSED for a clip the Director's second look kept (assembler.py:10361-10386), so that take is not REJECTED |
| `clip_qc_of` | 5193 | the latest clip-QC report of a take | readers of the verdict; also `fix_check._passing_clip_after` (backend/app/media/fix_check.py:265-283) | — |
| `clip_accepted` | 5204 | (accepted, Owner-facing reason) for a usable shot take: any APPROVED status, a PASSED report, or (outside PRODUCTION) anything not FAILED | PRODUCTION only with an APPROVED status or a passing report | OWNER or LLM_CHECKED_BY_CODE (the Director's look writes APPROVED too, director_qc.py:2145; `approved_by` not read) or LLM (a PASSED written for her second look's keep, assembler.py:10361-10373; `accepted_by` not read) / CONFIG (environment) |
| `shot_identity_matches` | 5326 | whether a take was filmed for the scene as it is now (from this still, or from words) | the Owner's choice is about this scene | CODE_RULE |
| `clip_choice` | 5335 | eligibility of «Aleg totuși acest clip»: kind, status, vendor refusal, duplicate, file present and unchanged, scene and still exist, identity matches (STILL_CHANGED vs PROMPT_CHANGED) | one rule for the sheet's button and `decide_take` (2026-10-10) | CODE_RULE |
| `owner_take_decisions` | 5416 | the Owner's decisions per take from `media.scene_take_decided` (`decided_by` owner, or none recorded: :5431) | the sheet shows them; `owner_clip_choice` reads them | OWNER |
| `owner_clip_choice` | 5445 | the scene's clip by the Owner's newest APPROVED decision, identity and file intact | the Owner's choice wins over clip QC | OWNER |
| `scene_clip_context` | 5481 | (scene, approved still sha256, other still sha256s) for `clip_choice` | used by `director_qc` (backend/app/media/director_qc.py:1986) | — |
| `clip_fit` | 5518 | how one clip fills a span: shot / slowed / at_risk / too_short / unknown with Romanian words | written for the sheet's button; no caller at `20abffd` (Oddities) | CODE_RULE |
| `clip_rejection_words` | 5573 | why a clip was rejected (QC blocks, the Owner's newest rejection and note, other take reasons) | written for the sheet; no caller at `20abffd` (Oddities) | — |
| `_record_motion_take` | 5612 | `record_take` for one shot (kind motion, motion identity, quoted credits, file sha256) | every shot is a take | CODE_RULE |
| `ClipChoiceRefused.as_dict` | 5299 | the 409 body `{status: CLIP_NOT_CHOOSABLE, code, message}` | the sheet's button and `decide_take` answer with the same words | — |

Helpers: `_known_file_sha256` (:5309, sha256 cached by path/size/mtime), `_scene_clip_refusal`
(:5228, the scene's latest shot REJECTED with `QC.CLIP` and its report, the Owner-facing reason a
scene has no shot to cut in; used by `clip_readiness` :4735 and the takes-only motion pass :6925).
Class: `ClipChoiceRefused` (:5291, 409 with `CLIP_NOT_CHOOSABLE`; `__init__` :5294 keeps
`code` and `reason_ro`; `as_dict` :5299, row above).

#### N. The bed under the voice (:5647-6007)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `_core_message` | 5662 | `story_json.core_message` of the storyboard's script | the sound plan's brief | — |
| `_mood_text` | 5673 | title, core message, each scene's words, purpose and audio intent joined | the deterministic bed choice reads mood words | — |
| `_tracks_of_plan` | 5699 | the bed and placed ambiences a plan names, as the library vouches for them now (kind check always; sha256 check only against `made_with`, which `remix_film_sound` passes and `film_mix` does not), placements ≤ 0.2 s skipped, and how many were dropped | a plan never smuggles in a track the library does not license | CODE_RULE (checks an LLM plan) |
| `_mix_with_plan` | 5760 | `toolchain.mix_bed` with the plan's fades and per-scene levels (`sound_design.levels_for_mix`) | levels bounded by the mixer | CODE_RULE |
| `film_mix` | 5788 | asks `sound_design.sound_plan`, records it (`media.sound_plan_written`), mixes bed + ambience under the narration, records attributions; advisory/warnings; raises the music card when the library has no music | the Owner, 2026-10-11 (sound_design.py:3-6) | LLM_CHECKED_BY_CODE |
| `remix_film_sound` | 5912 | remixes the bed and ambience a film was made with (or a new plan) under a remade voice track; drops tracks no longer vouched for, never replaces them; recomputes attributions | audio repair at 0 credits | CODE_RULE |

Helpers: `_as_dict` (:5657), `_scene_spans` (:5688), `_drop_mix_stems` (:5900).

#### O. The licence ledger (:6010-6254)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `_take_component` | 6055 | a bought component's licence: evidence on its take (`commercial_use True`) else `factory.vendor_licence` of the model's connection (the Owner's statement) | AR-15 | OWNER (statement) |
| `licence_components` | 6094 | every component of a rendered film: per scene still (or card / placeholder), motion, narration per take and per extra voice connection; fonts (OFL present); bed and ambience tracks (`commercial_ok`) | the studio used to stamp PROPRIETARY_STUDIO on everything (:6014-6016) | CODE_RULE |
| `film_licences` | 6208 | LICENSED only when there are components and all have commercial-use evidence, else NEEDS_REVIEW with Romanian reasons | NEEDS_REVIEW publishes privately only (spec 08 item 11) | CODE_RULE |
| `film_licence_ledger` | 6236 | `film_licences(licence_components(...))`, never fails a film; NEEDS_REVIEW raises per-connection Owner cards (`film_needs_review`) | the Owner answers commercial use | CODE_RULE + OWNER |

Helpers: `_fonts_component` (:6040), `_studio_component` (:6045), `_stamp_licences` (:6190,
writes evidence on takes; a take without evidence is re-stamped each time so a later yes is
read).

#### P. `assemble_video_job` (:6257-7653, 1397 lines)

The end-to-end render. Called by the legacy render route (backend/app/media/router.py:591), the
day's TEST media stage (backend/app/runbook/stages.py:3396) and `assemble_from_takes` (:3606,
with `takes_only=True`). Step by step:

| step | lines | what happens | decided by |
|---|---|---|---|
| setup | 6356-6413 | `release_reviewed_intermediates` sweep (errors only logged); loads the storyboard and scenes; creates the `VideoRenderJob` RENDERING | — |
| sources | 6415-6458 | image chain (or the deterministic placeholder), `real_stills`, `record_takes`, `visual_source`; one voice per scene; any missing real voice → whole film placeholder-voiced | CODE_RULE |
| failure helper | 6479-6507 | `_fail_job` writes FAILED, the log, the command and the production built so far (so the accountant can price a lost render, `economy.accountant.record_failed_render_cost`), emits `media.render_failed` | CODE_RULE |
| stop | 6509-6521 | `_stop_if_asked` before every scene after the first and before every shot | OWNER |
| per scene: still | 6546-6596 | cards get no still (or a placeholder frame); LIVE scenes call `_still_for_scene` (`ReferenceRequired` propagates: a locked character's face is never invented) | CODE_RULE / OWNER (locked look) |
| per scene: narration | 6598-6666 | per part: reuse a narration take or synthesize (paid), keep it at once, trim its silence | CODE_RULE (purchase gated by the caller) |
| per scene: record | 6667-6779 | scene record (voice provider/model/voice id, connections, narration takes, characters, `characters_bought`, `audio_seconds`, image attempt, still take, trims, speaker segments); voice segment files and pads; caption timing | — |
| errors | 6781-6793 | `ReferenceRequired`, `MediaProviderError`, `TakesMissing` → `_fail_job` then re-raise | CODE_RULE |
| timeline | 6798-6828 | scene spans from the measured words; pads after each scene's last take; joins and shot spans | CODE_RULE |
| cards | 6833-6842 | `_compose_cards` at the shot spans | CODE_RULE |
| motion pass | 6843-7141 | Per LIVE scene: the takes-only readiness (`clip_readiness`, :6873-6891), or a reusable shot (`_usable_motion_take`, not checked by `clip_accepted`, :6892-6898). Otherwise, when not takes-only: stop check, scene limit, budget estimate, model choice, vendor quote and three ceilings, stale-price correction, `_generate_motion`, PAID take. Failures are classified and recorded (`paid_but_lost` keeps PAID) | CODE_RULE + EXTERNAL + CONFIG |
| outcomes | 7142-7149 | `_record_outcomes` | CODE_RULE |
| slow-downs | 7150-7155 | `_clip_slowdowns`, interpolation filter chosen | CODE_RULE |
| motion summary | 7156-7196 | clips, fallbacks, skipped, composed, reused, seconds, credits, USD, lost credits, budget, limits, environment, run kind, dissolves | — |
| fallback gate | 7197-7234 | PRODUCTION: a LIVE still without the Owner's LOCAL_MOVE → `ClipsNotAccepted`, job FAILED, `media.assembly_refused` stage "render" | OWNER |
| narration track | 7236-7253 | `_concatenate_audio` with pads (real voices) or the placeholder WAV bytes; `voice_track` record for repairs | — |
| encoder check | 7255-7264 | no FFmpeg → FAILED, `RenderEngineUnavailable` | CODE_RULE |
| editor busy | 7266-7268 | `mark_working(VideoEditor, assemble_video)` | — |
| captions | 7270-7291 | `film_finish()` (config/factual_look.json), `film_hook`, `_write_captions` | CONFIG |
| sound | 7293-7332 | `film_mix` (sound plan), `encode_master_audio`, stems dropped, loudness record, Owner warnings | LLM_CHECKED_BY_CODE + CODE_RULE |
| framings + timeline record | 7334-7355 | dither if `zscale`, `plan_second_framings`, `_timeline_record` | CONFIG + CODE_RULE |
| shots | 7356-7478 | per scene build the shot (clip, card or still push), retry with `framerate` when a slowed shot's `minterpolate` fails, refuse a shot short of its frames, record its source; `film_grade`, `_install_lut`, per-shot grade and framing | CODE_RULE |
| edit command | 7479-7529 | `_dissolve_command` (real stills) or a concat of placeholder frames | CODE_RULE |
| encode | 7530-7550 | `run_encoder` with the caption and LUT files carried; any failure → FAILED | CODE_RULE |
| measure | 7552-7566 | output loudness reading; picture length vs film length (> 1.0 s short → FAILED) | CODE_RULE |
| cover + licences | 7568-7577 | `film_cover`, `film_licence_ledger` | CONFIG / CODE_RULE / OWNER |
| record | 7579-7653 | sha256 of the file, `media.video_rendered` event, `MediaAsset` (licence status from the ledger), job COMPLETED with `production_json`, storyboard RENDERED | — |

#### Q. Audio repair (:7656-8046)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `video_stream_sha256` | 7667 | sha256 over the first video stream's packets (`-f streamhash`) | proves a remux kept the picture packet for packet | CODE_RULE |
| `_repair_voice_source` | 7703 | the voice to remix from: kept WAV, else rejoined takes with their pads, else a legacy AAC track; else `AudioRepairError` | the order that loses least | CODE_RULE |
| `remux_with_audio` | 7729 | copies the picture and the new master into a new MP4 | no re-encode of the picture | — |
| `_refused_mix` | 7768 | the newest QC report's `audio_mix_qc` check when it failed | trigger for a re-plan | CODE_RULE |
| `_replan_sound` | 7786 | asks `sound_plan` again with the refusal and the previous plan; keeps the film's scene spans; records `media.sound_plan_replanned` | the Owner, 2026-10-11: what is wrong goes back to the agent (:7796-7798) | LLM_CHECKED_BY_CODE |
| `repair_audio` | 7851 | remakes a finished film's sound for 0 credits: voice source, optional re-plan, remix, master, remux, picture-identity check, licences re-read, new asset + new COMPLETED job + `media.audio_repaired` | free repair before any paid redo (ADR-AUTOMATIC-REDOS, 16_DECISION_LOG.md:4112); called by `_free_redo` (:15579) | CODE_RULE (+ LLM_CHECKED_BY_CODE plan) |

Class: `AudioRepairError` (:7659, Romanian message).

#### R. Motion staircase constants and exceptions (:8049-8300)

| function | line | what it does | why it exists | decided by |
|---|---:|---|---|---|
| `final_approval_words` | 8121 | whether the Owner's note marks an approval final («finală», «definitiv») | only a final approval stands against the Director's confirmed repair (2026-10-11, :8114-8117) | OWNER |
| `MotionStepRefused.__init__` / `MotionStepRefused.http_status` | 8134 / 8151 | the motion step bought nothing: status, Romanian reason, approval id, plan, findings; 202 for NEEDS_APPROVAL else 409 | route answers | CODE_RULE |
| `_shots_made` | 8168 | count of shot takes per scene that became a clip (PAID/APPROVED/REJECTED/LOST) | seed of the next round | CODE_RULE |
| `_scene_seed` | 8188 | film seed + 2 × clips made, mod `SEED_RANGE` | the same words on the same seed made the same failing clip (2026-10-12, :8192-8195) | CODE_RULE |
| `_shot_take_ids` | 8199 | every shot take id per scene | concurrency check input | — |
| `_bought_elsewhere` | 8218 | whether another buyer bought/submitted this scene's identity since a snapshot | one buyer per shot | CODE_RULE |
| `SpentStageError.__init__` | 8249 | a paid step failed after sending a possibly charged request; `fault_class = "HARD"` | "a database is locked after a purchase was TRANSIENT and the stage ran four times, four purchases, none of them booked" (:8241-8244) | CODE_RULE |

Helper: `_usd_ro` (:8155, «6,80 USD»). Dataclass `SpendMeter` (:8266, `committed`,
`attempts`; no methods). The functions that use the constants at :8280-8315 (`possibly_charged`
and later) are in part 2.

### Data read and written (this part)

- **Tables read:** `Storyboard`, `StoryboardScene`, `SceneTake`, `VideoRenderJob`,
  `MediaAsset`, `QualityControlReport` (:7771-7783), `DomainEvent`, `ScriptDraft`
  (:2402-2407, :5666-5670), `ProviderResource` (:1434-1439), `Integration` (via
  `production_policy.credit_usd`, :1538-1542).
- **Tables written:** `SceneTake` (:2745-2818, :5158-5167, :6194-6202), `VideoRenderJob`
  (:6400-6413, :6484-6497, :3734-3739, :7624-7633, :8022-8036), `MediaAsset` (:7606-7622,
  :8003-8020), `Storyboard.status` (:7636-7638), `ModelOutcome` (:1490-1493), agent memory via
  `sound_design.sound_plan` (outside).
- **Events emitted:** `media.scene_take_recorded` (:2776), `media.assembly_refused` (:4886),
  `media.clip_redo_proposed` (:5084), `media.clip_qc_checked` (:5177), `media.render_failed`
  (:6499), `media.video_rendered` (:7590), `media.audio_repaired` (:7988),
  `media.sound_plan_written` (:5844-5850), `media.sound_plan_replanned` (:7839-7845),
  `economy.credits_measured` (through `record_credit_spend`, :3726).
- **Events read:** `media.stills_step_finished`, `media.motion_step_finished`,
  `media.scene_redone` (:3643-3647), `economy.credits_measured` (:3718-3723),
  `media.clip_qc_checked` (:5195-5201), `media.scene_take_decided` (:5425-5429),
  `media.assembly_refused` (:4922-4930).
- **Files (in `media_root/<storyboard_id>/`):** `scene_NN.<png|jpeg|webp|svg>`,
  `frame_NN.ppm`, `voice_NN[_PP].<fmt>`, `narration/scene_NN_<key16>.<fmt>` + `.json`
  sidecar, `master_audio.wav`, `voice_segments.txt`, `mixed_audio.wav` (deleted after the
  master), `master_audio_final.m4a`, `captions.srt`, `captions.ass`, `fonts/`,
  `card_NN.mp4`, `motion_NN.mp4`, `shot_NN.mp4`, `grade.cube`, `cover.png`, `inputs.txt`,
  `final_short_9_16.mp4`; repair: `voice_rejoined_*.wav`, `master_audio_repair_<stamp>.m4a`,
  `<stem>_audio_<stamp>.mp4`. Config read: `config/factual_look.json` (finish, through
  `cards.film_finish`), `config/luts/*.cube`, the music library (`music_library.load_library`).

### External calls (money, GPU, publishing)

- Image vendor: `factory.still_from_chain` (:2900-2904) — paid per still (money).
- Voice vendor: `take_voice.synthesize` (:6633-6637) — paid per character (money).
- Video vendor: `adapter.create_generation` (:1318-1326), `get_generation_status` (:1351),
  `estimate_generation` dry run (:1399-1407) — paid per shot (money). `propose_clip_redos`
  also buys a motion redo through part 2 (`redo_scene`, :5032-5062 → :14994), under `may_act`.
- Language model: through `sound_design.sound_plan` (tokens) in the render and the audio
  repair; through `propose_clip_redos` → `redo_scene` (part 2), clip QC's vision judge and the
  Director's second look on the redone clip (tokens; the look buys nothing,
  backend/app/media/second_look.py:583-650).
- FFmpeg/ffprobe subprocesses everywhere (local, 0 credits).
- No publishing call in this part.

## Connections

- **Callers into this part:**
  - `app.media.router` — legacy render route → `assemble_video_job` (router.py:591), after
    refusing real paid vendors (router.py:577-588).
  - `app.runbook.stages` — TEST media stage → `assemble_video_job` (stages.py:3396);
    `_assemble_from_takes` → `assemble_from_takes` (stages.py:2673) after `mode_refusal` and
    `reserve_spend` for the narration (stages.py:2639-2667).
  - `app.media.shooting_sheet` — `assembly_readiness`, `clip_plan`, `latest_assembly_refusal`,
    `voiced_scenes`, `owner_take_decisions` (sheet build, shooting_sheet.py:1099-1161);
    `record_assembly_refused`, `narration_to_buy`, `assemble_from_takes` (assemble step,
    shooting_sheet.py:3869-3971); `propose_clip_redos` (shooting_sheet.py:4112).
  - `app.media.shooting_sheet` also imports `usable_take`, `clip_qc_of`, `scene_view`,
    `scene_kind_of`, `ClipsNotAccepted`, `TakesMissing`, `RenderStopped`,
    `RenderEngineUnavailable`, `SpentStageError`, `SpendMeter` and the motion-step constants.
  - `app.media.stills_stage` — `usable_take`, `record_take`, `still_fields`, `take_hash`,
    `classify_vendor_failure`, `failure_code_of`, `failure_detail_of`, `SpendMeter`,
    `UNANSWERED_*`, `NOT_QUEUED_DETAIL`, `DEFAULT_STORAGE_ROOT`.
  - `app.media.rehearsal` — `assemble_from_takes` (rehearsal.py:1239) and timeline helpers
    (`scene_spans`, `shot_spans`, `scene_joins`, `whole_frames`, `motion_fields`, `scene_view`).
  - `app.media.director_qc` — `clip_choice`, `scene_clip_context`, take constants.
  - `app.media.runpod_unsent` (`SHOT_TAKE_KINDS`, `UNANSWERED_FAILURE_CODE`),
    `app.media.local_media` (`TRANSITION_SECONDS`), `app.providers.runpod.adapters` and
    `app.providers.runpod.provider` (`DEFAULT_STORAGE_ROOT`).
  - `app.media.scene_rewrite` — `clip_qc_of`.
  - `app.media.fix_check` — `SHOT_TAKE_KINDS`, `clip_qc_of` (fix_check.py:267, in
    `_passing_clip_after`, fix_check.py:265-283: a motion-layer finding counts as closed once a
    later shot is APPROVED or its clip-QC verdict is PASSED).
  - `app.story.review`, `app.factual.story_review` — `spoken_words`, `script_clip_seconds`,
    narration constants.
  - `app.publishing.licence_release` — `film_licences`, `LICENSED`.
  - `app.agents.repairs.unbilled` — `film_step_spend`.
  - `app.decisions.sources` — `scene_kind_of`.
  - `app.workflows.passes.training_set` — `still_fields`, `take_hash`.
  - In-file (part 2): `_free_redo` → `repair_audio` (:15579); `_rebuild_film` →
    `captions_filter` (:14782); `run_motion_step` and the redo machinery use
    `motion_stop_reason`, `_generate_motion`, `record_take`, `_keep_clip_report`,
    `clip_report_record`, `owner_clip_choice` (:9145), `film_licence_ledger` (:14927);
    `_check_shot` uses `motion_request`, `clip_report_record` and `_keep_clip_report`
    (:10295, :10364, :10376).
- **Calls out to:** `app.media.toolchain` (FFmpeg resolution, loudness, mixing, speech edges),
  `app.media.cards` (cards, cover, finish, fonts), `app.media.qc` (probes, degenerate still,
  fallback gate, silent-card ceilings), `app.media.factory` (still chain, paid-vendor test,
  licences), `app.media.production_policy` (failure classification, quoted prices, credit
  price, tiers), `app.media.sound_design` (sound plan), `app.media.music_library`,
  `app.media.prompt_agent` (deterministic `motion_prompt_for`, `strip_on_screen_text`),
  `app.media.shooting_sheet` (`price_table_for`, `_clock`), `app.economy.credits`
  (`record_credit_spend`), `app.decisions.sources` (`film_without_music`,
  `film_needs_review`), `app.runbook.services` (`stop_requested`, `shutdown_requested`),
  `app.agents.services` (`at_work`, `mark_working`, `mark_idle`),
  `app.providers.runpod.wiring` (`sync_take_quality`), `app.integrations` (outcomes, prices).

## Owner touchpoints

- **The stop switch (AUTONOMIE OPRITĂ):** read before every scene and every shot
  (:3425-3429, :6509-6521, :6960); the render fails with `STOP_REASON` and nothing is
  recorded as a film.
- **Approving stills on the shooting sheet:** a takes-only film needs an APPROVED still per
  LIVE scene (:2893-2898, :3542-3572). The Owner is one of four writers of that status; the
  stills gate's choice, the Director's look and the Director's second look also make a still
  APPROVED (see "Model-made approvals").
- **LOCAL_MOVE per scene:** the only way a PRODUCTION LIVE scene may be a still
  (:3613-3637, :4817-4822, :7197-7234; qc.py:2802-2833).
- **Approving / rejecting clips and «Aleg totuși acest clip»:** an APPROVED status accepts a
  clip whatever clip QC said (:5211-5212). That status may be the Owner's or the Director's
  look (director_qc.py:2145). A clip the Director's second look kept after clip QC refused it
  is accepted too, without any APPROVED status, through its PASSED record (assembler.py:5215-5216,
  :10361-10373); `_check_shot` returns such a clip PAID with no Owner reason (:10446-10460).
  The Owner's newest APPROVED
  decision is the scene's clip (:4118-4121, :5445-5478); eligibility and the
  disabled/no-button reasons (:5273-5413).
- **The paid motion redo question:** `propose_clip_redos` raises the redo through
  `redo_scene(proposal=True)`. The Owner is asked only when the Owner's paid-media rule and
  mode ask, or when the scene holds a shot the Owner approved; otherwise the Policy Kernel may
  let it buy unasked (:4962-4970, :11676-11699).
- **Narration purchase:** asked by the caller under `media.paid_generation[_over_threshold]`
  bound to the sheet's plan hash (runbook/stages.py:2639-2654); this part supplies the exact
  character count (`narration_to_buy`, :3300).
- **Cards raised:** music library without music (`film_without_music`, :5863-5867);
  commercial use per vendor connection when the film is NEEDS_REVIEW (`film_needs_review`,
  :6248-6253).
- **Warnings on the film (`production['owner_warnings']`):** local slow-downs (:3916),
  loudness fallback (:7329-7330), mix failure (:7331-7332), tracks dropped in a repair
  (:5993-5997).
- **Settings and statements read:** `captions_burn_in` (:7288), the look file
  `config/factual_look.json` (captions colours, headline, grade, LUT, second framing, cover;
  :7277), `STUDIO_MEDIA_ROOT` (:141), the credit price recorded on a connection (:1533-1543),
  the commercial-use answer on each connection (:6079-6082), a locked character look
  (`ReferenceRequired`, :6781-6787), a final approval note (:8118-8123).

## Oddities and gaps

1. **Stop wording on shutdown.** `_stop_if_asked` (:6519-6521) and `buy_stills` (:3425-3426)
   always write `STOP_REASON` ("AUTONOMIE OPRITĂ a fost setată de Owner"), although
   `stop_requested` is also True during a shutdown; `render_stop_reason` (:291) exists for
   exactly this and is used in part 2 (:16309, :16382). The comment at :275-277 records the
   2026-10-12 00:03 incident of the same kind for the motion step.
2. **Stale docstring.** `assemble_video_job` says "either way the shots dissolve into one
   another instead of cutting" (:6319-6322); since 2026-10-01 films cut and dissolve only
   where `transition_in` asks (:150-152, :1719-1735). The module docstring promises "SRT/VTT
   subtitles" (:4); only `captions.srt` and `captions.ass` are written (:4009-4014).
3. **No caller at `20abffd`:** `clip_fit` (:5518), `clip_rejection_words` (:5573) and
   `clip_seconds_by_scene` (:4577) are not called from `backend/app` or `tests/`.
   `buy_stills` (:3380) and `generate_subtitles_srt` (:945) are called only from tests
   (tests/test_scene_takes.py:264, tests/test_phase5_media.py:689).
   `SECOND_FRAMING_MIN_SPOKEN` (:2310) and `SECOND_FRAMING_ZOOM` (:2312) are not read by code
   (the finish file supplies both, backend/app/media/cards.py:1223); `SECOND_FRAMING_ZOOM` is
   asserted in tests/test_grade.py:178.
4. **Unused parameter.** `_first_frame(ffmpeg_exe, still, seconds)` never uses `seconds`
   (:1225-1249).
5. **Duplicated rules.** The "one part per speaker, else the whole scene" rule is in
   `_scene_parts` (:3285-3297) and again inline in `assemble_video_job` (:6535-6541). The still
   identity pair (words + degenerate-retry words) is built in `_still_for_scene`
   (:2866-2869) and again in `assemble_from_takes` (:3537-3541).
6. **Spend booking labels.** `film_step_spend` and `book_film_spend` label every step
   `"kind": "runway"` (:3687, :3729) and pass `"<event_type>:<event_id>"` keys to
   `economy.credits.record_credit_spend`, which treats its keys as integration ids
   (`credit_usd(session, integration_id)`, backend/app/economy/credits.py:130-132) and words
   each line as "Runway ... credite" (credits.py:136).
7. **Budget checks need a credit price.** Inside `assemble_video_job` the per-shot quote
   ceilings and the remaining-budget arithmetic run only when `_credit_price` found a price
   (`if quoted is not None and credit_price`, :7015; :7081-7082; the "likely" estimate is 0.0
   without a price, :6969). The per-shot check compares one shot's quote with
   `motion_budget_usd` (:7036-7040), which the docstring calls the render's whole motion
   budget (:6314-6316).
8. **Legacy motion path writes no SUBMITTED take.** `assemble_video_job` calls
   `_generate_motion` without `on_submitted` (:7069-7075) and `_record_motion_take` without
   `remote_task_id` (:5612-5644), unlike the staircase (spec 08 item 7,
   docs/architecture/08_VIDEO_PIPELINE.md:249-257). A `TaskStillOpen` with no
   `last_estimated_credits` is recorded REFUSED (:7122-7136). This path refuses real paid
   video adapters through `guard_motion_chooser` (factory.py:160-175).
9. **Placeholder stills drawn and not used.** With no image adapter, `_still_for_scene` still
   draws a still through `still_from_chain`, with `DeterministicVisualAdapter` or with
   `image_chain` when a chain is passed without an adapter (:6422-6424, :6575-6589). The
   render then uses a PPM placeholder frame instead (:6590-6596).
10. **Refusal stages.** The `ASSEMBLY_REFUSED_EVENT` comment names stages "precheck" and
    "render" (:4232-4235); the shooting sheet also records stage "sheet"
    (backend/app/media/shooting_sheet.py:3869-3879). `_refused_spans` reads only "render"
    (:4557).
11. **Size.** `assemble_video_job` is one function of 1397 lines (:6257-7653) covering voicing,
    motion purchase, mixing, mastering, shot building, grading, encoding, licences and the
    database writes; its failure closure `_fail_job` reads `editor_id` and `command_args`
    assigned later (:6473-6478).
12. **Process-wide caches.** `_CLIP_SECONDS` (:4143) and `_FILE_SHA` (:5305) are module-level
    dicts, cleared wholesale at 4096 entries; `_CLIP_SECONDS` keys by sha256 only.
13. **Spec vs code on intermediates.** The 2026-09-27 decision names lossless `-qp 0`
    intermediates (16_DECISION_LOG.md:4060-4062); the code uses CRF 4 (:1639-1651), as the
    later DISK_AND_BREATHS decision records (16_DECISION_LOG.md:4084).
14. **Narration purchase is not a paid-media step.** The decision log records that the
    narration follows the studio's mode (`media.paid_generation`, T2/T3), not the Owner's
    EVERY_PAID_STEP rule, pending an Owner decision (16_DECISION_LOG.md:4082, :4130); in this
    part the purchase at :6633 has no gate of its own beyond reuse and the stop switch.
15. **"APPROVED" is not only the Owner's.** The constant comment says only the Owner may
    approve or reject a take, "Nobody else" (:8111-8112). Docstrings and comments here also
    say "his APPROVED" (:3499, :5207, :6868-6869). Yet the status these lines test is also
    written by the Director's look (`approved_by` director,
    backend/app/media/director_qc.py:2145, on a take clip QC or the gate had REJECTED), by
    the stills gate (`approved_by` still_gate, backend/app/media/stills_stage.py:961-962) and,
    since `20abffd` (wired in `5fc7468`), by the Director's second look on a still the gate
    refused (`approved_by` director_look, stills_stage.py:1026-1027).
    `clip_accepted` (assembler.py:5211) and `usable_take(statuses=("APPROVED",))` (:2879,
    :3542, :5502) never read `approved_by`. Part 2's `owner_approved_among` (:13012) and `_owner_stands_by`
    do read it (:13009).
16. **Stated tier never reaches `scene_tier`.** Its first two branches (`quality_tier`,
    `scene_role`, :1520-1528) are never fed. The only caller (:6860) passes `scene_view` dicts
    (:3351-3377), which carry neither key, though the docstring promises that a tier "from the
    channel, the episode or the Owner" is kept (:1515-1516).
17. **Credit price from any connection.** `_credit_price` (:1533-1543) returns the first
    `Integration` row with a `credit_usd`, in unspecified order, not the motion adapter's own
    connection. The quote ceilings and the budget arithmetic of the legacy motion pass use that
    price (:6845, :7015-7016).
18. **Legacy reuse skips acceptance.** Outside `takes_only`, a reused shot
    (`_usable_motion_take`, :6892-6898) is not passed through `clip_accepted`. A PAID clip
    whose clip QC is UNCHECKED, or never ran, is cut into a PRODUCTION film by this path. The
    fallback gate counts it as moving (qc.py:2778-2779). In practice the legacy path runs only
    with stand-in vendors (router.py:577-588).
19. **`record_take` without `take_id` overwrites by file.** Every call in this part omits
    `take_id`. A purchase whose file sha256 equals an existing row's, for the same scene, kind
    and prompt hash, updates that row's status, credits and path in place (:2771-2772,
    :2802-2815). That happens when the row was not reusable, for example its file moved or its
    narration sidecar was lost. A byte-identical new purchase then moves an APPROVED row to PAID
    or REJECTED. The duplicate-file branch (:2761-2770) applies only with `take_id`.
20. **`buy_stills` storage root.** Without `storage_root` it writes under `DEFAULT_STORAGE_ROOT`
    (:3408), not `media_root(settings)` (REL-08, :141-147), unlike `assemble_video_job`
    (:6370-6371).
21. **A PASSED clip-QC record need not be clip QC's pass.** For a clip clip QC refused and the
    Director's second look kept, part 2's `_check_shot` stores the record with `verdict`
    PASSED while `passed` stays False and QC's `blocks_ro` stay on it, adding `accepted_by`
    director_look and `director_look` (:10361-10373). `clip_accepted` (:5215-5216) and
    `fix_check._passing_clip_after` (backend/app/media/fix_check.py:279-281) read only
    `verdict`. The comments of this part still say a shot enters a PRODUCTION film only with
    "his APPROVED or a passing report" (assembler.py:5101-5103, :5207-5209).
    `_keep_clip_report` then syncs the take's quality row as accepted with QC's refusal words
    as the reason (assembler.py:5168-5174). Her keep can stand against a failed measured check
    (motion floor, cut): `qc.look_may_overturn` excludes only unmeasured checks, the still's
    fault, a failed `faces` or `panels` check, readable text, a picture that is not one
    picture and a face the judge saw where faces are checked (qc.py:2588-2606).
