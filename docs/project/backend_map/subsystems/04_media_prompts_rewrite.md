# 04 — Prompt writing, prompt lint and compilation, scene rewrites, series look and serial storyboards

> Files:
> - `backend/app/media/prompt_agent.py` (3695 lines)
> - `backend/app/media/prompt_lint.py` (1272 lines)
> - `backend/app/media/scene_rewrite.py` (3147 lines)
> - `backend/app/media/sheet_words.py` (512 lines)
> - `backend/app/media/sheet_story_repair.py` (277 lines)
> - `backend/app/media/series_look.py` (597 lines)
> - `backend/app/media/serial_storyboard.py` (410 lines)
>
> 9910 lines, 259 functions in scope.
> Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).

## In one paragraph

This group turns an approved story into the exact words a paid picture model and a paid video
model receive, checks those words before anything is priced, and rewrites them when quality
control refuses what was bought. The Video Editor's model (role `VideoEditor`, the persona the code
calls Kael) writes a visual bible and a shot plan for each film (`prompt_agent.build_visual_bible`,
`prompt_agent.write_shot_prompts`). Deterministic code then validates every shot, removes invented
numbers and requests for on-screen text, and compiles two prompts per filmed scene (a still prompt
and a motion prompt) with a fixed look block, fixed camera-move sentences and per-vendor dialects
(`prompt_agent.compile_prompts`, `series_look.look_block`). A pure-text linter
(`prompt_lint`) produces BLOCK and WARN findings; a BLOCK stops pricing and purchase elsewhere. When
quality control refuses a scene, the Director's model writes a brief, the Video Editor's model
rewrites that one scene, the code compiles and lints it, and the Director's model reviews the
rewrite before anything is stored (`scene_rewrite`). Her review answers each of quality control's
findings by an id the code gives it, with a severity: only a serious finding left untreated, or a
broken studio lesson, refuses the rewrite, and when every finding that refuses a motion rewrite is
in words the motion layer keeps (locked), the scene turns to the picture. A rewrite she passes records her lesson for the
film's kind (serial or factual) as unverified, and the stills gate or clip QC later confirms or
withdraws it. The office serial takes a separate path: an approved episode becomes a storyboard
(`serial_storyboard`), its look is a fixed config file (`series_look`), and its prompts are composed
by code from the beat (`compose_serial_prompt`, `compose_serial_motion`). `sheet_words` writes the
Owner-facing Romanian sentences of the shooting sheet, and `sheet_story_repair` rewrites the story
itself when a sheet blocker can only be fixed by a new script. Nothing in these seven files calls a
media vendor or spends media money directly; they decide the words that are bought and they open or
close the gates the purchase code reads.

## Why it exists

- **Prompts that said nothing.** The module docstring of `prompt_agent` records that the studio
  used to send a video model the writer's one line ("a spinning galaxy"), about 2.60 USD a shot, and
  the Owner's verdict «sunt doar niste imagini lipite» (`backend/app/media/prompt_agent.py:1-26`).
  The bible and the per-shot package exist so a shot has a camera, a light, a continuity rule and a
  story purpose.
- **The Nepal film (storyboard 1d530880, 2026-09-26).** Enum codes ("NEPAL_CLIMATE_CRISIS"), a hex
  palette, "Camera: medium shot, locked camera" on every scene, an 8-item "Avoid:" list, a bar chart
  and a black screen asked of a photo model, and no face rule. It cost more than 1,000 Runway credits
  and failed QC. Each of those is a lint finding (`backend/app/media/prompt_lint.py:1-13`), the bible
  scrubs codes and hex (`prompt_agent.py:239-254`, `688-744`), and the compiler was introduced
  (`prompt_agent.py:2153-2169`). The shot plan was lost to one unescaped quote, which led to
  `repair_json` (`prompt_agent.py:781-826`) and the NEEDS_SHOT_PLAN hold
  (`prompt_agent.py:182-184`, `1422-1466`; `docs/project/16_DECISION_LOG.md:4064-4068`;
  `docs/architecture/08_VIDEO_PIPELINE.md:214-231`).
- **The ATLAS plan (2026-09).** 14,036 characters of shot plan were discarded because two
  `audio_intent` lines ran past 200 characters; `_coerce` now fits answers instead of refusing them
  (`prompt_agent.py:688-703`).
- **Film babcf272 (2026-10-09).** A still prompt listed three moments and pointed at "scene 1"; the
  image model drew three stacked panels. This produced the still-is-one-moment reading
  (`_clauses_of`, `prompt_agent.py:2430-2520`), `without_scene_reference` (`prompt_agent.py:2398-2421`)
  and the STILL_SEQUENCE, STILL_PANELS and SCENE_REFERENCE checks (`prompt_lint.py:192-284`).
- **«Mișcare v2» (Owner, 2026-10-11).** «Pe video pare doar un zoom, și mișcări mici.» The motion
  sentences now carry a path and a tempo, there are 18 camera-move families, the motion word band is
  25-95, and stillness words are flagged (`prompt_agent.py:2177-2263`; `prompt_lint.py:39-46`,
  `50-99`, `154-172`; `docs/project/16_DECISION_LOG.md:59-61`).
- **«Redo until QC passes» (Owner, 2026-10-11).** «Nu trebuie să respingă un film, trebuie să îl
  refacă până trece QC», «Nu reface pur și simplu imaginea, trebuie verificat promptul și corectat!»:
  the Director's brief and the Video Editor's rewrite (`scene_rewrite.py:1-27`;
  ADR-DIRECTOR-PROMPT-LADDER, `docs/project/16_DECISION_LOG.md:123-127`).
- **Review before purchase (Owner, 2026-10-12, 15:05).** «Nu ai cum să faci de 5 ori aceeași
  greșeală!» after scene 5 of film 1c038a99 was redone five times. Her review of each rewrite against
  the findings, failing closed (`scene_rewrite.py:28-37`; ADR-REWRITE-REVIEWED-BEFORE-PURCHASE,
  `docs/project/16_DECISION_LOG.md:11-17`).
- **Lessons (Owner, 2026-10-12, 16:50).** «DIRECTOAREA ACCEPTĂ DEFECTELE MICI! DAR TREBUIE SĂ
  ÎNȚELEAGĂ DE CE APAR DEFECTELE ȘI LA VIITOARELE PROMPTURI SĂ SE ASIGURE CĂ NU MAI SUNT!» A lesson is
  stored and given as a rule to every prompt writer of its kind of film (`prompt_agent.py:120-173`,
  `3319-3351`; `scene_rewrite.py:38-50`, `1791-1820`). The first half of the sentence is the
  severity rule: a minor finding left untreated no longer refuses a rewrite
  (`scene_rewrite.py:126-128`, `374-381`).
- **Her review answered findings quality control never gave (2026-10-12, 16:46-16:48, f06808c9
  scenes 3, 4, 7; runs e31aa5e7, 8035e541).** Her review listed two diagnoses of her own as findings
  and refused a rewrite that treated quality control's one finding; what she called untreated were
  the camera move's fixed sentence and the beat's action, words the motion layer keeps, so the
  second rewrite could not treat them and nothing turned to the picture. Findings now carry quality
  control's ids, her own notes are advisory observations, an untreated finding names a field or is
  locked with a quote, and a locked motion rewrite turns to the still (`scene_rewrite.py:51-68`,
  `246-253`, `1167-1174`, `2923-2941`).
- **Lessons per kind of film, unverified until a picture proves them (review of a9f84ea,
  2026-10-12).** A factual film's «show people only from behind» would have reached the serial's
  beat writer, whose rule is «in frame, facing the viewer»; the older lesson used to win, so «Keep
  the camera static.» kept out the lesson that corrected it; and a lesson was never verified or
  retired (`prompt_agent.py:141-157`, `3437-3456`, `3521-3522`).
- **The office serial (S8, 2026-09-24; look v2 2026-10-11).** The serial's style was the label
  "CHARACTER_ANIMATION", which no prompt carried; the look is now a config proposal that opens every
  serial prompt (`series_look.py:1-16`; `serial_storyboard.py:35-43`;
  `docs/project/16_DECISION_LOG.md:3970`, `80-85`).
- **Serial stills drawn as stacked panels (f06808c9, 2026-10-11/12).** One moment per person in the
  still, the chain kept for the clip (`prompt_agent.py:1709-1807`, `1822-1894`); a content refusal of
  a serial scene goes to a brief, a technical one re-rolls the same words (`scene_rewrite.py:70-79`,
  `2568-2602`).
- **A serial clip lost its ending (f06808c9 scene 3, 2026-10-12).** The rewrite's ending and a
  45-word action did not fit 95 words together; the composer dropped the ending, two rewrites
  composed to the same prompt, and her review found «finalul cerut … a fost șters». The action's
  later moments now give way before the ending (`_action_for_ending`, `prompt_agent.py:1977-2000`).
- **A second board for the same film (Owner, 2026-10-11).** «De ce există 2 Storyboard? Trebuie
  doar 1!» → `sheet_story_repair.retire_replaced` (`sheet_story_repair.py:45-60`).
- **The Owner's look at a take said nothing true (Nepal sheet 81438d13, 2026-10-04).**
  `sheet_words.decision_outcome` describes what the choice set going (`sheet_words.py:1-19`).

## Who decides here

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| The film's look (style, world, palette, light, continuity rules, avoid) | LLM_CHECKED_BY_CODE | `prompt_agent.py:1018-1097` | Video Editor model proposes; `_coerce` cuts fields to their caps, drops clauses with ENUM_CODE or hex, moves hex to `card_palette` (`688-744`); `_avoid_list` puts `DEFAULT_NEGATIVES` first, cap 16 (`1100-1107`); aspect ratio and quality target forced (`1068-1070`); defaults on failure (`1066-1081`) |
| Which look words actually reach a still prompt | CODE_RULE + CONFIG | `series_look.py:473-597` | `look_block`: rendering from `config/factual_look.json`; bible values only as whole clauses that pass `look_phrase` filters and slot word caps (`357-439`); 40-60 words |
| Whether a film may be described at all | CODE_RULE (OWNER for closure) | `prompt_agent.py:1135-1143` | `film_is_closed` (the Owner's «Închide filmul» or a Director retirement) → PromptError; `story_gate` not passed → PromptError |
| The shot plan per scene (subject, action, camera, motion, ...) | LLM_CHECKED_BY_CODE | `prompt_agent.py:1178-1243`, `1469-1553` | Model proposes; `_validated_package`: purpose in `SCENE_PURPOSES` else DEVELOPMENT, on-screen-text clauses removed from subject/action/environment/background/composition/ending_frame (`1530-1536`), missing required fields filled from the writer's line or the bible (`1538-1541`), 2-4 digit numbers not in the title, narration, claims or story strings removed from subject/action/environment/background only (`1542-1552`), `camera_move` only if in the enum |
| Re-ask a shot plan with missing scenes | CODE_RULE | `prompt_agent.py:1221-1243` | Exactly one re-ask, factual films only, with the decoder's error and the missing scene numbers |
| Hold a film NEEDS_SHOT_PLAN | CODE_RULE | `prompt_agent.py:1266`, `1325-1345`; `1422-1466` | A model answered and scenes are still missing after the re-ask (factual), or in PRODUCTION a scene's package source is not in the allowed sources. The media stage calls `hold_for_shot_plan` for factual films only (`runbook/stages.py:3191-3193`); the legacy render's 409 calls it too (`media/router.py:166-167`) |
| Keep an earlier model-written package over a template | CODE_RULE | `prompt_agent.py:1271-1277` | When this answer was lost or no model answered, a package with `source == "model"` is never overwritten |
| Package provenance (`model` / `template` / `series_look`) | CODE_RULE | `prompt_agent.py:1283`, `1523` | Set from whether a model shot existed for the scene; PRODUCTION buys only allowed sources (`assembler.py:9832-9835`) |
| Which camera move a clip makes | CODE_RULE (LLM proposal honoured) | `prompt_agent.py:2656-2682` | Plan's `camera_move` if in `lint.CAMERA_MOVES`; else the one move its camera text names; else first of `SIZE_MOVES[size]` not equal to the previous scene's move. The compiler passes `avoid=("slow orbit",)` for faceless people (`2976-2978`), but no `SIZE_MOVES` list contains an orbit, so that argument never changes the result: the compiler never picks an orbit, and a plan that names one keeps it |
| Serial camera move | CODE_RULE | `prompt_agent.py:1906-1914` | Plan's move unless equal to the previous scene's, then chosen by shot size |
| Serial shot size | CODE_RULE | `series_look.py:64-78` | Index 1 → establishing; part `turn` → single; `button` → close; else two-shot if ≥2 speakers |
| Who is in a serial frame and the room | CODE_RULE | `prompt_agent.py:1626-1706` | Room from the beat, never the model; speakers from bibles; establishing = all, two-shot = 2 speakers, single/close = 1 |
| Model text that restyles the serial look | CODE_RULE | `prompt_agent.py:637-666`, `1682` | `strip_style_overrides` removes medium/style/frame clauses while the look is in use |
| A serial clip's action beside its ending | CODE_RULE | `prompt_agent.py:1977-2000`, `2048-2052` | When the whole action and the ending sentence do not fit 95 words and 1000 UTF-16 units together with the move sentence and the closing, the action's later moments are taken off one at a time (from the person with the most left, the later person on a tie), down to each person's first moment (`_shorter_actions`, `1956-1974`); if not even that fits, the action stays whole and `_fit_sentences` leaves the ending out |
| Faces hidden in a factual still | CODE_RULE (from bible words) | `prompt_agent.py:2917`, `2935`, `2964`; `prompt_lint.py:617-637` | `bible_face_rule` reads the bible; `hide_faces` adds "seen from behind"; PEOPLE_SENTENCE or NO_PEOPLE_SENTENCE |
| Look slots left to the scene (place, light) | CODE_RULE | `prompt_agent.py:2925-2930` | Scene names its environment → `PLACE_SLOTS` omitted; names its lighting → `LIGHT_SLOTS` omitted |
| Motion prompt dialect per vendor | CODE_RULE + CONFIG | `prompt_agent.py:2808-2860`; `prompt_lint.py:548-580` | Family from model id prefix (veo/seedance/wan/gen4/seedream); veo and gen4 get the closing without its «No ...» sentence (`VEO_MOTION_CLOSING`, `2823-2824`); veo only: fixed nouns plus the plan's `avoid` in `negativePrompt` (`2828-2831`) and no `FACES_CONSTRAINT` sentence (`2826`); negations are already dropped clause by clause for every family (`_clauses_of`, `2462`); cap from the contract, default 1000 UTF-16 |
| Motion amplitude (AMPLE / MEASURED) | CODE_RULE (fixed AMPLE in practice) | `prompt_agent.py:2287-2297`, `2785`, `2793`, `2846`, `2853` | `motion_amplitude` from the package if valid, else AMPLE. No code in `backend/app` writes `motion_amplitude`, and neither `ShotPrompt` nor the rewrite's `shot_schema` has the field (`extra="ignore"` drops it), so neither a model nor the Director can set MEASURED today; the comment's «the Director's rewrite may set it» (`2289`) is the roadmap's "Next" item (`docs/project/13_ROADMAP_TODO.md:1898-1899`). Only a package edited by hand (or a test) gets MEASURED |
| A prompt BLOCKs pricing and purchase | CODE_RULE | `prompt_lint.py:689-1242`; enforced at `stills_stage.py:1949`, `assembler.py:15985`, `shooting_sheet.py:1759` | Severity table below (ENUM_CODE, HEX_CODE, Camera:/Motion: labels, Avoid list, quotes, over cap, faces, kind mismatch, camera count, same camera every scene, ...) |
| Which scenes go to the Director's ladder | CODE_RULE | `scene_rewrite.py:762-775`, `3139-3147` | Newest failing take's code in `QUALITY_CODES` (`QC.CLIP`, `LOCAL.STILL_GATE`), and no newer take PAID/APPROVED/SUBMITTED |
| Which layers a scene may be rewritten on | CODE_RULE (OWNER for approved stills) | `scene_rewrite.py:933-954` | Owner-approved still → motion only (none after a still-gate refusal); still-gate refusal → still only; ≥1 motion attempt since the last still rewrite (rewritten, same words, or `layer_exhausted`), counted from `media.director_scene_brief` events → still only; else both |
| Skip a scene the Owner chose to animate locally | OWNER | `scene_rewrite.py:743-748`, `2916-2918` | `owner_scene_choices == LOCAL_MOVE` and the refusal is not the still gate's |
| The brief: diagnosis, layer, avoid, keep, change | LLM_CHECKED_BY_CODE | `scene_rewrite.py:1335-1412` | Schema `SceneBrief` (caps), layer bound to the code's open layers (`brief_schema`, `229-239`); two attempts (`structured_run`) |
| The findings a rewrite must treat | CODE_RULE | `scene_rewrite.py:1592-1647` | Quality control's own words, each with an id: the finished film's findings (from `rewrite_for_redo`, with the cause her film QC gave) and, when the scene's newest failure is a quality code, the newest refusal split at «; » outside «…» quotes (`_pieces`, `1561-1576`); the gate's verdict line and `fix_check.PROCESS_NOTES` are dropped (`_is_finding`, `1579-1589`); at most 8 (`MAX_QC_FINDINGS`, `194`); if none remain, her brief's diagnosis stands in (`findings_to_treat`) |
| What a layer may change and the words it keeps | CODE_RULE | `scene_rewrite.py:1156-1266` | `layer_terms`: editable fields (factual motion: motion, camera_move, ending_frame; factual still: every shot field but avoid; serial motion: camera_move, ending_frame, emotion; serial still: action, emotion, background, continuity, ending_frame, camera_move), fields kept word for word, and the composer's fixed sentences found in the prompts (the whole still on a motion rewrite) |
| The rewritten shot | LLM_CHECKED_BY_CODE | `scene_rewrite.py:1847-1922`, `1418-1535` | Fields required per layer (`shot_schema`); only the layer's fields merged; validated, compiled; new lint BLOCKs → one retry with the lint's words, then refused |
| A rewrite with the same words | CODE_RULE | `scene_rewrite.py:2209-2230` | Round 1: still and motion identity unchanged → `same_prompt`, nothing stored; round 2: the stored words or the refused round's words → refused, and `layer_exhausted` on the motion layer |
| Store a rewrite (and so unlock a re-purchase) | LLM (her per-finding answers; the code derives the verdict) | `scene_rewrite.py:333-381`, `402-449`, `2268-2306` | Her review must answer every quality-control id once and no other (`review_schema`); verdict computed by code: MISSES while a `serious` finding is untreated or a studio lesson is broken, else TREATS (a `minor` untreated finding is accepted); whether a finding is treated, and how serious, is her word; no verdict → nothing stored (fail closed) |
| A locked finding turns the scene to the picture | LLM_CHECKED_BY_CODE | `scene_rewrite.py:430-436`, `1759-1763`, `2097-2113`, `2923-2941` | A locked untreated finding must quote words found in the layer's kept texts (`words_kept`, `390-399`), else the answer is refused; when every blocking finding is locked and no lesson is broken, no second rewrite: on the motion layer `layer_exhausted`, and `rewrite_failed_scene` runs a still rung in the same call when the still is open |
| Second rewrite in the rung | CODE_RULE | `scene_rewrite.py:125`, `2192-2273` | `REWRITES_PER_RUNG = 2`; round 2 receives her untreated findings with why_not and field (locked ones marked), broken lessons, cause, treated findings, `layer_terms` and the refused prompts (`_second_rewrite_note`, `2029-2067`) |
| Concurrent change protection | CODE_RULE | `scene_rewrite.py:2287-2303` | Write lock; film closed → nothing; stored package changed since read → nothing |
| Record a lesson | LLM_CHECKED_BY_CODE | `scene_rewrite.py:1791-1820`; `prompt_agent.py:3415-3492` | Stored for the film's kind, unverified (`[serial][?]` / `[factual][?]`); refused when empty, over 400 characters, naming a scene/shot/beat by number, a record's UUID, a storyboard id head, or three consecutive words of any storyboard title; compared with the newest 40 live lessons of its scope and "all": overlap <0.6 → stored; ≥0.9 → the closest is refreshed (its own words when they are longer or reach more films); else the new one supersedes the closest (retired when of the same scope) |
| Confirm or withdraw a lesson | CODE_RULE (on the stills gate's and clip QC's results) | `prompt_agent.py:3516-3564`; `fix_check.py:536-571` | A take approved with every review finding gone → the review's unverified lessons stored again as confirmed; a take refused with a finding persisting → withdrawn, and a lesson one of them had replaced is stored again. Called from the still gate (`stills_stage.py:1105`, `1157`) and clip QC (`fix_check.py:787-793`, `assembler.py:10391`) |
| Lessons given to every writer | CODE_RULE | `prompt_agent.py:3319-3351`, `983-1000` | Of the newest 200 live lessons, those of the film's kind and "all"; near-duplicates (overlap ≥0.6 either way) dropped, the newer kept; confirmed first, then unverified ones marked " (unverified)", 12 in all; kept whole at the head of the payload |
| Serial refusal kind (content vs technical) | CODE_RULE | `scene_rewrite.py:2579-2602` | `QC.CLIP` → content; gate text containing a content phrase → content; empty → content; else technical |
| Serial scene: recompose / re-roll / brief | CODE_RULE | `scene_rewrite.py:2745-2857` | Words differ from today's composer → say again (0 credits); technical refusal → re-roll same words (decision recorded as the Director's); content refusal → `needs_brief` |
| Redo after a failed film QC is corrected first | CODE_RULE (Director's film-QC decision upstream) | `scene_rewrite.py:2991-3042`; `runbook/stages.py:4791-4863` | Layer forced to the one her film QC decided; the reasons are read with their causes (`film_failure`, `2948-2988`); on the still layer an Owner-approved still is not rewritable. A scene that is not rewritable (card, closed film, no plan, Owner-approved still) keeps its paid redo unchanged; a rewritable scene that was not rewritten makes the caller refuse the redo (`PROMPT_NOT_CORRECTED`, nothing bought, `stages.py:4854-4863`); a motion rewrite that came back with the same words is escalated to a still rewrite by the caller (`stages.py:4820-4847`); `layer_exhausted` is not read there (oddity 27) |
| A serial episode becomes a storyboard | OWNER / LLM upstream, CODE_RULE here | `serial_storyboard.py:156-170` | Only `StoryEpisode.status == "APPROVED"`; once per episode (existing non-REJECTED storyboard returned) |
| Story gate record for a serial episode | CODE_RULE | `serial_storyboard.py:103-153` | Director's review PASS → her checks and run; otherwise PASS recorded as the Owner's approval with no reviewer |
| Serial durations | CODE_RULE | `serial_storyboard.py:196`, `334` | 2.5 words/second; episode 30-75 s; scene 3.0-9.0 s |
| Re-describe serial shots | CODE_RULE + CONFIG | `serial_storyboard.py:375-410` | Skip when every package has the current look version and (all from a model or no model registered) |
| The serial look in use | CONFIG (OWNER edits) | `series_look.py:89-152` | `use_until_the_owner_changes_it` and a non-empty block; cap clamped 300-2000 |
| The factual look in use | CONFIG (OWNER edits) | `series_look.py:271-313`, `492-494` | `use_until_the_owner_changes_it` (default True); off → empty block |
| Story repair: rewrite the script | CODE_RULE trigger, LLM writer | `sheet_story_repair.py:174-239` | Story gate failed, or blockers SCENE_TOO_LONG / KIND_MISMATCH / CARD_INVALID |
| Story repair: approve the revised script | LLM (review) + CODE_RULE | `sheet_story_repair.py:240-249`; `runbook/stages.py:929-972` | Director review verdict PASS and grounding check passed |
| Retire the replaced board | CODE_RULE | `sheet_story_repair.py:45-90` | Not while a purchase lease is held, a purchase is in flight, it has a finished render, it is a serial episode, or the replacement is REJECTED |
| What the Owner is told a take decision set going | CODE_RULE (describes OWNER policy) | `sheet_words.py:337-512` | Mirrors `may_act`'s order: stop, safe mode, mode tier, T4, the Owner's paid-media rule and standing answer, daily budget |
| What a refused take cost, as shown | CODE_RULE / EXTERNAL | `sheet_words.py:154-183` | Measured credits if known; HTTP 4xx at submit → 0; else the quoted credits, marked unmeasured |

## LLM involvement

Five functions in this group write a question to a model and use its answer. All five reach
`run_agent_task` (`backend/app/agents/services.py:733`), which applies the policy kernel, the daily
token ceiling and the USD budget, and doubles explicit token limits for the Director role
(`services.py:793-798`; ADR-DIRECTOR-TOKEN-BUDGET-X2). A run the kernel refuses comes back as a
`BLOCKED_*` row, not an exception (`services.py:827-855`). Every payload is wrapped by
`wrap_in_inert_boundary` (data, not instructions). Every writer of picture words, and since
`a50407e` her rewrite review too, is given the studio's lessons for the film's kind whole, ahead of
the fitted data, with `LESSONS_RULE` (`prompt_agent.py:164-173`): lessons are rules, an
"(unverified)" one is followed unless a confirmed one says otherwise, and none overrides the brief's
fixed rules.

### 1. `build_visual_bible` — `prompt_agent.py:1018`

| Item | Value |
|---|---|
| Speaker | `PROMPT_ROLE = "VideoEditor"` (`prompt_agent.py:76`) |
| Gateway | `prompt_agent._run` → `run_agent_task` (`3054-3088`), temperature 0.3, `max_tokens` 2200, `emit_message=False` |
| Task / template | `visual_bible` / `visual-bible-v1` (`77`, `1053-1057`) |
| Asks | Decide one look for the whole film: style, realism, period, world, season, palette, lighting, camera language, weather, continuity rules, what must never appear; plain English words, no capital codes, no hex except in `card_palette` (`_BIBLE_INSTRUCTIONS`, `325-348`), plus `LESSONS_RULE` when lessons exist (`164-173`) |
| Data | `_film_facts` (title, aspect ratio, story, scenes with narration, writer's visual line, claims, characters) with the lessons of the film's kind first (`prompt_lessons(scope=…)`, `1042`), fitted to 12,000 characters by dropping whole claims then scenes (`983-995`, `941-980`) |
| Answer shape | `VisualBible` (`219-236`): `style`≤300, `realism`≤200, `period`≤200, `world`≤400, `palette`≤300, `lighting`≤400, `camera_language`≤400, `weather`≤200, `continuity_rules`≤10, `avoid`≤12, `season`≤100, `card_palette`≤16 hex |
| Parsing | `_first_object` (first JSON object holding any bible field, at most 400 tries, `747-763`), `_coerce` (flatten objects to sentences, cut at a whole word, scrub codes and hex from prompt-bound fields, collect hex into `card_palette`, `688-744`), `model_validate` (`1003-1012`) |
| What code does with it | Stores on `Storyboard.visual_bible_json` with `avoid` = `DEFAULT_NEGATIVES` + the model's (≤16, each ≤120 chars), `aspect_ratio` forced to the board's, `quality_target` fixed, default `style` and `continuity_rules` when empty, `source = "director"` or `"studio defaults"` (`1066-1081`); emits `media.visual_bible_written` (`1088-1096`). Downstream the bible's words reach a still prompt through `look_block` (whole clauses that pass `look_phrase` filters, slot word caps) and as `_validated_package`'s fallbacks for a shot's empty environment (`world`), lighting (`lighting`) or any empty required field (`style`) (`1495`, `1498`, `1540`), which then pass `_clauses_of`'s filters; the whole bible is also data for the shot writer (`1190`). A face rule the model writes into `continuity_rules` or `avoid` is read by `bible_face_rule` (`prompt_lint.py:617-637`): the compiler then hides faces (`2917`, `2935`, `2964`) and the lint BLOCKs (FORBIDDEN_FACES, BIBLE_RULE_MISSING) any still prompt that does not keep it |
| Trust | CHECKED_BY_CODE |
| If the model fails | `_run` returns None on `ValueError`/`RuntimeError`, a non-SUCCEEDED status (including policy BLOCKED) or empty text (`3082-3087`); unparseable JSON → `None`. The film gets the studio-default bible (`source "studio defaults"`), and the next `write_shot_prompts` with a registry asks again (`1144-1146`) |
| Can lead to spend | No purchase is triggered by it (a default bible exists); its words appear inside every bought still prompt, and its face rule can BLOCK a purchase through the lint. LLM tokens/USD are spent under `run_agent_task`'s budgets |

### 2. `write_shot_prompts` — `prompt_agent.py:1113`

| Item | Value |
|---|---|
| Speaker | `VideoEditor` |
| Gateway | `_run` → `run_agent_task`, temperature 0.3, `max_tokens` 7000 (`1204-1214`, `1226-1236`) |
| Task / template | `shot_prompts` / `shot-prompts-v1` (factual) or `serial-shot-prompts-v1` (serial) (`78-79`, `1188-1191`) |
| Asks (factual) | For every scene: subject, action as movement, environment, camera (size, lens, one `camera_move` from 16 listed moves, path and speed), lighting, composition, motion as verbs, emotion, background, continuity, ending frame, audio intent, transition, avoid, optional `second_framing`; never writing in the picture, never new facts or numbers, never more spectacular than the story (`_SHOTS_INSTRUCTIONS`, `350-402`) |
| Asks (serial) | For every beat: who is in frame facing the viewer, action as movement, expression, camera varied across the episode, background life, continuity; do not describe style/light/palette, never writing (`_SERIAL_SHOTS_INSTRUCTIONS`, `410-429`) |
| Data | Factual: `{"visual_bible", "film"}`; serial: `{"series_look": {style_block, version, continuity_rules}, "episode"}`; plus `repair_context` when the sheet repair calls (the Director's note from `blocker_repair`, the issues, the exchange number; `1192-1193`; `blocker_repair.py:882-891`); the lessons of the film's kind first (`1153`); 16,000 characters (`180`, `1198`) |
| Answer shape | `{"shots": [ShotPrompt]}` (`292-322`): `scene_index` 1-60, `story_purpose`≤20, `subject`≤400, `action`≤500, `environment`≤500, `camera`≤300, `lighting`≤300, `composition`≤300, `motion`≤400, `emotion`≤200, `background`≤300, `continuity`≤400, `ending_frame`≤300, `audio_intent`≤200, `transition`≤200, `avoid`≤10, `camera_move`≤40, `second_framing` any |
| Parsing | `parse_shot_plan` (`881-912`): strict JSON (or the first object holding `shots`), then `repair_json` (escape an inner quote, drop a trailing comma; `781-826`), then shot-by-shot salvage (`853-878`), else none with the decoder's error. Each shot is fitted with `_coerce`; a shot that still fails validation costs only itself (`837-850`) |
| Re-ask | One re-ask for a factual film with missing scenes, carrying the decoder's message and the missing numbers (`1221-1243`, `1393-1400`). The serial is never re-asked: its missing shots are composed from the look |
| What code does with it | Per scene, under the write lock and after re-checking `film_is_closed` (`1251-1257`): `_validated_package` (`1469-1553`); factual: `compile_prompts` (`2885-2991`) writes still prompt, motion prompt, negative prompt, look block, camera move, shot size, motion intent; serial: `_serial_package` + `compose_serial_prompt` + `_serial_camera_move` + `compose_serial_motion` (`1280-1294`). Stores `StoryboardScene.prompt_json`, `visual_prompt`, `story_purpose` (serial also `shot_type`). Sets the board `NEEDS_SHOT_PLAN` (with `media.shot_prompts_incomplete`, severity WARNING) or back to `APPROVED` (with `media.shot_prompts_written`) (`1319-1363`) |
| Trust | CHECKED_BY_CODE |
| If the model fails | No model reachable, kernel BLOCKED, or empty answer: template packages (`source "template"`; serial `source "series_look"`) and the run goes on; earlier model packages are kept (`1271-1277`). A model answered but scenes are still missing after the re-ask (factual): `NEEDS_SHOT_PLAN`, WARNING event, `ShotPlanUnusable` raised (`1364-1375`). The runbook re-asks such films at most once a day on `SHOT_PLAN_REASK_DAYS = 2` days (`runbook/stages.py:1946`, `1192-1262`): factual NEEDS_SHOT_PLAN boards, or APPROVED ones whose last recorded day was LINT_BLOCKED, never a rendered film, a serial or a film holding a bought take (`1231-1241`) |
| Can lead to spend | Yes. In PRODUCTION a factual scene is bought only from a `source == "model"` package and a serial scene from `model` or `series_look` (`assembler.py:9832-9835`; `hold_for_shot_plan`; stills refusal of template prompts at `stills_stage.py:1928-1941`). The prompts written here are the words the stills and motion purchases send |

### 3. `director_brief` — `scene_rewrite.py:1335`

| Item | Value |
|---|---|
| Speaker | `Director` (`agent_for_role(session, "Director")`, `1353`) |
| Gateway | `structured_run` (`backend/app/agents/structured.py:76-166`): two attempts at most; the second quotes the schema refusal or asks with native thinking; a failed or BLOCKED first run gets no second attempt (`structured.py:138-140`); exceptions are not caught there; default temperature 0.1; `max_tokens` 2500 (`1394`; ×2 for the Director role in `run_agent_task`) |
| Task / template | `director_scene_brief` / `director-scene-brief-v1` (`114-115`) |
| Asks | Read the prompt the vendor got and QC's reasons, find what in the prompt invited the failure, choose the layer (motion keeps the picture; still redraws it) among the open ones, list avoid / keep / change; remove causes instead of forbidding results (models ignore negations); diagnose only what the refusal names; do not repeat a brief or a change that was refused or failed, and remove exactly what a review's why_not or cause names; the diagnosis answers `quality_control_findings` (each with its id; the refusals are their history); read `layers_he_may_change` and `camera_move_sentences`, and choose still when the defect is in words the motion layer keeps (`_BRIEF_INSTRUCTIONS`, `495-546`); serial note on who stands where (`550-557`); the open-layer sentence (`_LAYERS_OPEN`, `647-654`, or the caller's `layers_note`) |
| Data | `_data` (`1269-1298`): film title and story, scene facts, `shot_as_stored`, `prompts_sent`, bible subset, refusals (≤6), earlier briefs (≤4 whole, then up to 12 older in short) with their reviews' verdict, cause, why_not (or, when the rung ended TREATS, its refused rounds) and lesson, and for the serial `serial_shot`; plus `open_layers`, `layers_he_may_change` (`layer_terms` per open layer), `camera_move_sentences` and `quality_control_findings` (`1361-1368`). Fitted by `_fitted` (`1305-1329`): the oldest refusals beyond the newest two go, then the oldest whole briefs move to short form, then the oldest short ones go; the lessons of the film's kind are put whole in front (`fit_with_lessons`); a payload still over 14,000 characters is sent as it is (oddity 21) |
| Answer shape | `SceneBrief` (`205-226`): `diagnosis` 1-800, `layer` motion/still, `avoid` 1-8 (each ≤240), `keep` ≤8, `change` 1-8, `summary_ro` 1-500; `brief_schema(layers)` refuses a layer not open (`229-239`) |
| What code does with it | Passes it to the Video Editor's rewrite (`director_brief` in the data, `2176`) and to her own review (layer, diagnosis, avoid, change; `1694-1696`); for a factual scene merges its `avoid` into the package's `avoid` (`rewritten_package`, `1441-1450`; that list reaches no positive prompt, only veo's `negativePrompt` through `_scene_constraints`, `prompt_agent.py:2828-2831`, `2863-2882`), while a serial rewrite drops it (`serial_rewritten_package`, `1505`); its `layer` (bounded by code) selects which fields the rewrite may replace; records it in `media.director_scene_brief` and the Director's `AGENT_OPINION` memory (`2485-2559`); writes it as a HANDOFF letter (`2379-2482`); returns `summary_ro` to the walk (`3089`) |
| Trust | CHECKED_BY_CODE (the layer is bounded by code; the content is instructions to another model, whose output is compiled, linted and reviewed) |
| If the model fails | No Director or no registry → reason «Niciun Director activ.» (`1355-1356`); invalid twice → `brief None` with the refusal reason (`1397-1406`); an exception is caught by `_rung` (`3053-3062`). The failed attempt is still recorded (`_record_brief` with `rewritten False`, `3063-3072`) so `earlier_briefs` and the `ladder_retry` watchdog pass see it; the scene waits |
| Can lead to spend | Indirectly: its layer choice decides whether a new still and a new clip, or only a clip, is bought after a stored rewrite |

### 4. `review_rewrite` — `scene_rewrite.py:1650`

| Item | Value |
|---|---|
| Speaker | `Director` (`1680`) |
| Gateway | `structured_run`, default temperature 0.1, `max_tokens` 2400 (`1728-1743`) |
| Task / template | `director_rewrite_review` / `director-rewrite-review-v1` (`119-120`) |
| Asks | Answer every finding of quality control by its id and only those; anything else goes to `observations`, which decide nothing. A finding is treated only if the new prompt changes the words that invited it or names in their place what the scene asks for; a finding about subject, composition, who is in frame or location is answered in the still prompt, one about movement or the clip's ending in the motion prompt. For each: treated, the new sentence that treats it (`by`), its layer, its severity (serious: QC would refuse again or it breaks the bible; minor: a small defect the studio accepts); for an untreated one, `why_not` and either the `field` he must change or `locked` with the kept words quoted (`locked_words`); a camera move's words are fixed but `camera_move` is his to change. Then the `cause` and a positive general `lesson` of at most 240 characters with no film title, scene number, id or person's name (unless about the serial's recurring characters), empty when there is none (`_REVIEW_INSTRUCTIONS`, `559-615`). With lessons: list the lessons his words break (`_REVIEW_LESSONS_NOTE`, `618-623`); on round 2 check first what the earlier review left untreated (`625-630`) |
| Data | `quality_control_findings` (`findings_to_treat`, computed once per rung, `2160`), the brief's layer/diagnosis/avoid/change, `this_layer` (`layer_terms` with the rewritten package), `camera_move_sentences`, prompts before and after, a sentence-level diff of still and motion (`sentence_diff`, `1549-1558`), `serial_shot`, `your_earlier_review` with its findings and broken lessons (`1692-1714`); the lessons of the film's kind whole in front (`1684-1685`, `1725`). Nothing in this payload can be dropped by `_fitted`, so it is never shortened |
| Answer shape | `RewriteReview` (`333-381`): `findings` 1-8 of `FindingReview` {`id`, `finding`≤400, `treated`, `severity` minor/serious, `layer` still/motion or empty, `by`≤500, `why_not`≤400, `field`≤40, `locked`, `locked_words`≤300} (`246-311`), `observations` ≤6 (each cut to 300), `broken_lessons` ≤6 {`lesson`, `why_not`, `field`} (`314-330`), `reason_ro` 1-500, `cause` 1-400, `lesson` ≤2000. `FindingReview._explained` (`298-311`): treated needs `by`, untreated needs `why_not`, locked needs `locked_words`. `review_schema` (`402-449`): every QC id answered once and no other; an untreated, unlocked finding names a field he may change on this layer; a locked one quotes words found in the layer's kept texts (`words_kept`, `390-399`; `kept_texts`, `1251-1259`); a broken lesson names a field he may change. The verdict is not hers to state: `RewriteReview.verdict` (`379-381`) is MISSES while a serious finding is untreated (`blocking`, `374-377`) or a lesson is broken, else TREATS |
| What code does with it | TREATS: the rewrite is stored (`2287-2306`), its lesson goes through `learn_from_review` (`2307`), and `SCENE_PROMPTS_REWRITTEN_EVENT` (`media.prompts_rewritten`) is written with `decided_by "director"` and the review's findings in quality control's words (`_kept_findings`, `1959-1991`), which `fix_check` later checks the bought picture against (`2308-2362`). MISSES with every blocking finding locked: no second rewrite; on the motion layer `layer_exhausted` (`2270-2273`, `2097-2113`). MISSES: one more rewrite with her words (`2192-2269`); a second MISSES stores nothing (`2274-2279`). No verdict: nothing stored, `review_unavailable` (`2280-2286`); an unreadable second review keeps the first refusal (`2249-2257`) |
| Trust | FINAL for whether each finding is treated and how serious (code checks the ids, the fields and the locked quotes, not that the quoted `by` sentence is in the new prompt, oddity 6), and so for the store-or-not verdict the code derives from them; the lesson is CHECKED_BY_CODE |
| If the model fails | `_no_review` (`1771-1785`), also on any exception (`_reviewed`, `1925-1956`): fail closed, nothing is stored and nothing is bought on the words |
| Can lead to spend | Yes: TREATS stores the rewrite, and `assembler.scene_memory` reads a `director` rewrite as a decision that lifts the scene's hold and restarts its attempt count (`assembler.py:8785-8796`); the next walk buys under the staircase's own gates. A locked motion finding sends `rewrite_failed_scene` to a still rung, whose stored rewrite leads to a still purchase |

### 5. `_editor_rewrite` — `scene_rewrite.py:1847`

| Item | Value |
|---|---|
| Speaker | `VideoEditor` (`rewrite_scene` resolves `PROMPT_ROLE`, `2153`) |
| Gateway | `structured_run`, temperature 0.3, `max_tokens` 3000 (`1876-1891`); up to two lint rounds (`1868`), each with up to two schema attempts |
| Task / template | `scene_prompt_rewrite` / `scene-prompt-rewrite-v1` (`116-117`) |
| Asks | Rewrite this one shot following her brief (nothing under avoid in any field, keep stays, change is written differently), the layer rule (`_LAYER_RULE` / `_SERIAL_LAYER_RULE`, `678-713`), positive words only, faces per bible, no writing, no new facts, one ample camera move from all 18 `CAMERA_MOVES`, read `this_layer` and `camera_move_sentences` (`_REWRITE_INSTRUCTIONS`, `656-677`), plus `LESSONS_RULE` (`2171`). Round 2 adds her review inside its own boundary: untreated findings in quality control's words with why_not, severity and field or the lock, broken lessons, treated findings, cause, `this_layer`, refused prompts (`_second_rewrite_note`, `2029-2067`; `_SECOND_REWRITE_NOTE`, `635-646`); a lint retry adds the linter's Romanian messages (`1870-1875`) |
| Data | `_data` plus `director_brief`, `quality_control_findings`, `this_layer` and `camera_move_sentences` (`2172-2184`), fitted by `_fitted` with the lessons in front |
| Answer shape | `shot_schema(index, layer, serial)` (`452-492`): a `ShotPrompt` (unwrapped from `shot`/`shots` if nested, fitted by `_coerce`, `scene_index` forced); required: factual motion → `motion`; factual still → `subject`, `action`, `motion`; serial still → `action`; serial motion → one of `camera_move`, `ending_frame`, `emotion` |
| What code does with it | Factual `rewritten_package` (`1418-1478`): only the layer's fields replace the stored ones (motion layer: `motion`, `camera_move`, `ending_frame`; still layer: every shot field but `avoid`, including `story_purpose`, `audio_intent`, `transition`, `second_framing`), `avoid` = brief + new + stored (≤10), `_validated_package`, `compile_prompts` with the factual look and without a contract (default model dialect); a motion rewrite restores the stored still words, `still_prompt`, `look_block` and `shot_size`. The stored layer is the one actually changed (`layer_done = STILL if still_changed else MOTION`, `2231`), not the brief's. Serial `serial_rewritten_package` (`1481-1535`): only `SERIAL_STILL_FIELDS` / `SERIAL_MOTION_FIELDS`, cleaned of on-screen text and style overrides, `camera_move` only if in the enum, the motion layer's feeling to `motion_emotion`, recomposed. Then `_lint_blocks` (`1823-1844`): BLOCK messages the new prompts add over the old → retry once quoting them, then refused |
| Trust | CHECKED_BY_CODE (and then reviewed by the Director's model before storing) |
| If the model fails | `package None` with the reason (invalid twice, or lint blocked twice) (`1894-1903`, `1917-1922`); `rewrite_scene` returns without storing; round 2 failing keeps her refusal of round 1 (`_second_rewrite_failed`, `2077-2094`) |
| Can lead to spend | Yes, only through a TREATS review (see 4) |

### Functions that reach a model indirectly

| Function | Line | Reaches the model through |
|---|---|---|
| `scene_rewrite._reviewed` | `scene_rewrite.py:1925` | `review_rewrite` |
| `scene_rewrite.rewrite_scene` | `scene_rewrite.py:2116` | `_editor_rewrite`, `_reviewed` → `review_rewrite` |
| `scene_rewrite._rung` | `scene_rewrite.py:3045` | `director_brief`, `rewrite_scene` |
| `scene_rewrite.rewrite_failed_scene` | `scene_rewrite.py:2885` | `_rung` (serial scenes only when `recompose_serial_scene` says `needs_brief`); a second `_rung` on the still when the first ended `layer_exhausted` (`2923-2941`) |
| `scene_rewrite.rewrite_for_redo` | `scene_rewrite.py:2991` | `_rung` |
| `scene_rewrite.director_ladder` | `scene_rewrite.py:3111` | `rewrite_failed_scene` per scene |
| `sheet_story_repair.repair_story` | `sheet_story_repair.py:147` | `app.factual.agent_pipeline.agent_write_script` (a call site, `factual/agent_pipeline.py:642`) and `app.factual.story_review.review_story` → `_ask_director` (`factual/story_review.py:312`, `544`) |
| `serial_storyboard.storyboard_from_episode` | `serial_storyboard.py:156` | Statically `write_shot_prompts`, but it passes `registry=None` (`serial_storyboard.py:362`), so `_run` is never called (`prompt_agent.py:1178`): no model call at runtime |
| `serial_storyboard.describe_serial_shots` | `serial_storyboard.py:375` | `write_shot_prompts` with the registry when one is registered (`404-406`) |
| `prompt_agent._run` | `prompt_agent.py:3054` | Gateway itself: `run_agent_task` |

### How much is model and how much is rule, in this group

- 5 of 259 functions are call sites; `_run` is the gateway they use in `prompt_agent`; 9 more
  reach a model statically (one of them, `storyboard_from_episode`, never at runtime). The other
  244 functions are deterministic text processing, gates, state changes, lesson bookkeeping and
  Owner-facing wording.
- The models write words: a bible, a shot plan, a brief, a rewritten shot, a review of each
  finding with a cause and a lesson. Code decides what is stored, which layers are open, which
  findings must be answered, what a layer may change, which camera move is used, which look words
  are said, what the linter blocks, when to fall back to a template, when to hold a film, whether a
  serial refusal is content or technical, which lessons are kept, given, confirmed or withdrawn.
- The model answers acted on after validation that cannot check their truth are the review's
  per-finding `treated` flags and severities (`review_rewrite`): the code computes the verdict from
  them. That verdict can only permit storing a rewrite that already passed the code's validation,
  compilation and lint; it can always refuse; and a locked finding (its quote checked against the
  kept words) can move a motion rewrite to the picture.
- No model answer here buys anything. Purchases are made by the shooting-sheet staircase, under the
  Policy Kernel, the Owner's paid-media rule, the budgets, the film ceiling and the paid-redo cap.

## Hard rules and limits

### Prompt writing and compilation (`prompt_agent.py`)

| Constant / rule | Value | Where |
|---|---|---|
| `PROMPT_ROLE` | `"VideoEditor"` | `76` |
| Templates | `visual-bible-v1`, `shot-prompts-v1`, `serial-shot-prompts-v1` | `77-79` |
| `DEFAULT_NEGATIVES` | 8 exclusions (on-screen text, warped hands, waxy skin, cartoon look, unmotivated camera, clothing/weather changes, morphing, watermarks) | `88-97` |
| `MAX_PROMPT_CHARS` | 1400 (used only by `compose_prompt`) | `101`, `2120` |
| `MAX_BIBLE_CHARS` | 2400 (unused) | `102` |
| `REQUIRED_SHOT_FIELDS` | subject, action, environment, camera, lighting, composition, motion | `106-114` |
| `LESSONS_GIVEN` / `LESSONS_COMPARED` / `LESSONS_SCANNED` | 12 given / 40 compared with a new one / 200 newest live lessons read | `126-130` |
| `LESSON_MAX_CHARS` / `LESSON_OVERLAP` / `LESSON_CONTAINED` | 400 / 0.6 (share of the new lesson's words) / 0.9 (refresh instead of supersede) | `133-140` |
| Lesson scopes | `serial`, `factual`, `all` (rows written before scopes read as `all`, confirmed) | `146-149`, `3132-3135` |
| Lesson markers | stored as `prompt lesson: [scope][?] text`; given with `" (unverified)"` while `[?]`; retire reasons `SUPERSEDED_RO`, `CONFIRMED_RO`, `WITHDRAWN_RO` | `151-157`, `3232-3233` |
| Lesson comparison words | letters and digits, accents off, plurals folded, length >2, filler words and the scaffold every picture lesson shares (camera, prompt, still, clip, scene, shot, frame, ...) left out | `3094-3114`, `3138-3163` |
| Not a rule | empty, >400 characters, a UUID, a storyboard id head (8+ hex), a scene/shot/beat (English or Romanian) by number but not a length («a shot 5 seconds long»), three consecutive words of any storyboard title with two of meaning | `3115-3131`, `3361-3427` |
| `MAX_BIBLE_PAYLOAD_CHARS` / `MAX_SHOTS_PAYLOAD_CHARS` | 12,000 / 16,000 characters of JSON (lessons ride on top) | `179-180` |
| `NEEDS_SHOT_PLAN` | board status for a lost plan | `184` |
| Sources | `model`, `template`, `series_look` | `194-196` |
| Shot plan size | `scene_index` 1-60, at most 60 shots | `296`, `322` |
| `_first_object` tries | 400 | `753` |
| Model calls | temperature 0.3; bible 2200 tokens; shots 7000 tokens | `1060`, `1213`, `1235`, `3079` |
| Re-ask | one, factual only | `1224` |
| `_avoid_list` | ≤16 items, each ≤120 characters, defaults first | `1100-1107` |
| `second_framing` | centre clamped to 0..1 (3 decimals), subject ≤200 characters | `1556-1568` |
| Serial identity budget per person | 220 (1 person) / 130 (2) / 90 (3+), lowered in steps of 10 while above 45 (so down to 40) to fit the cap | `1870-1874` |
| Serial cap fallback | 900 characters when the look has no `max_prompt_chars` | `1837` |
| Serial clip: action beside ending | action and ending must fit `MOTION_MAX_WORDS` (95) and 1000 UTF-16 units with the move sentence and the closing; later moments go first | `1977-2000` |
| `DEFAULT_STILL_MODEL` / `DEFAULT_MOTION_MODEL` | `seedream5_pro` / `seedance2_5` | `2172-2173` |
| `STILL_MAX_WORDS` | 120 (`lint.STILL_WORDS[1]`) | `2174` |
| `MOTION_MIN_WORDS`, `MOTION_MAX_WORDS` | 25, 95 (`lint.MOTION_WORDS`) | `2175` |
| `MOVE_SENTENCES` | one sentence per camera move, 18 keys, each with tempo and path | `2192-2263` |
| `DEFAULT_MOVE` | `dolly in` | `2265` |
| `SIZE_MOVES` | aerial / wide / medium / close / detail move preferences; never static, orbit or rack focus by default | `2272-2278` |
| `TWO_BEAT_SECONDS` | 7.0 s (a second beat of camera, `END_BEAT`) | `2280-2286` |
| Amplitudes | `ample` (default, and in practice always), `measured` (read from `motion_amplitude`, which no production code writes) | `2291-2297`, `2785` |
| Fixed sentences | `COMPOSITION_SENTENCE`, `STILL_EXCLUSIONS` ("No text, no logo."), `PEOPLE_SENTENCE`, `NO_PEOPLE_SENTENCE`, `FACES_CONSTRAINT`, `MOTION_PAD`, `DEFAULT_WORLD_MOTION` | `2299-2322` |
| Veo negatives | `text, subtitles, logo, watermark` (+ `human faces` when banned, + the plan's own `avoid` nouns from `_scene_constraints`) | `2332-2333`, `2828-2831`, `2863-2882` |
| `hide_faces` loop | at most 32 insertions | `2573` |
| Serial sentences | `SERIAL_FRAME_SENTENCE`, `SERIAL_BLANK_SENTENCE` (only when a writing surface is named), `SERIAL_FACES_SENTENCE`, `SERIAL_LIFE_SENTENCE`, `SERIAL_ENDING_SENTENCE` | `1714-1721`, `1918-1933` |

### Lint (`prompt_lint.py`)

| Constant | Value | Where |
|---|---|---|
| `DEFAULT_PROMPT_MAX_UTF16` | 1000 (Runway's promptText limit) | `37` |
| `STILL_WORDS` | 60-120 | `39` |
| `MOTION_WORDS` | 25-95 (20-70 before 2026-10-11) | `46` |
| `MAX_INLINE_EXCLUSIONS` | 2 | `47` |
| `EVIDENCE_CHARS` | 120 | `48` |
| `CAMERA_MOVES` | 18 families with disjoint regexes | `58-99` |
| `MOTION_CLOSING` / `VEO_MOTION_CLOSING` | "Continuous, seamless shot. No subtitles, no on-screen text." / "Continuous, seamless shot." | `33-34` |
| `MOTION_REDESCRIBES` | WARN when >60% of the motion prompt's content words are in the still prompt | `963` |
| Camera language | a run of 3 equal moves or sizes → WARN; all ≥3 LIVE scenes equal → BLOCK | `1196-1242` |

Finding codes and severities:

| Code | Severity | Prompt | Where |
|---|---|---|---|
| `ENUM_CODE` | BLOCK | both | `693-704` |
| `HEX_CODE` | BLOCK | both | `706-717` |
| `TEMPLATE_LABEL` | BLOCK for `Camera:` / `Motion:`, else WARN | both | `719-731` |
| `AVOID_LIST` | BLOCK | both | `733-745` |
| `QUOTED_TEXT` | BLOCK | both | `747-758` |
| `OVER_CAP` | BLOCK | both | `760-774` |
| `TOO_MANY_EXCLUSIONS` | WARN | still | `792-805` |
| `KIND_MISMATCH` | BLOCK (chart, black screen or title in a LIVE scene) | still | `807-820` |
| `STILL_SEQUENCE` | WARN | still | `825-838` |
| `STILL_PANELS` | WARN | still | `839-852` |
| `SCENE_REFERENCE` | WARN | still | `853-865` |
| `FORBIDDEN_FACES` | BLOCK (bible forbids faces; a face asked or a person not hidden) | still | `867-894` |
| `BIBLE_RULE_MISSING` | BLOCK | still | `895-909` |
| `STILL_LENGTH` | WARN | still | `911-924` |
| `MOTION_EQUALS_STILL` | BLOCK | motion | `944-958` |
| `MOTION_REDESCRIBES` | WARN | motion | `959-974` |
| `CAMERA_COUNT` | BLOCK (not exactly one move) | motion | `976-992` |
| `THEN_CHAIN` | BLOCK on seedance, WARN elsewhere, not checked on veo | motion | `994-1007` |
| `NEGATION_IN_PROMPT` | BLOCK on veo | motion | `1009-1021` |
| `MOTION_CLOSING`, `MOTION_SPEED`, `MOTION_ENVIRONMENT`, `MOTION_STILLNESS`, `MOTION_LENGTH` | WARN | motion | `1023-1086` |
| `KIND_UNKNOWN` | BLOCK | scene | `1121-1131` |
| `CARD_HAS_PROMPT` | BLOCK (a card scene would reach a paid model) | scene | `1132-1146` |
| `PROMPT_MISSING` | BLOCK | scene | `1148-1157` |
| `SAME_CAMERA_EVERY_SCENE` | BLOCK | film | `1199-1215` |
| `SAME_CAMERA_RUN` | WARN | film | `1216-1242` |

### Scene rewrites (`scene_rewrite.py`)

| Constant / rule | Value | Where |
|---|---|---|
| `QUALITY_CODES` | `QC.CLIP`, `LOCAL.STILL_GATE` | `138-139` |
| `REWRITES_PER_RUNG` | 2 | `125` |
| `MINOR` / `SERIOUS` | only a serious finding left untreated refuses a rewrite | `128`, `374-381` |
| `MOTION_REWRITES_BEFORE_STILL` | 1 | `141` |
| `LESSON_CHARS_ASKED` | 240, asked of her review only (the schema takes 2000, the store keeps up to 400) | `131`, `354`, `602` |
| Lesson scopes | `serial` / `factual` by the film's kind | `134`, `1079-1082` |
| `MAX_FAILURES_SHOWN` / `MAX_BRIEFS_SHOWN` / `MAX_OLDER_BRIEFS` / `OLDER_DIAGNOSIS_CHARS` | 6 / 4 / 12 / 200 | `186-192` |
| `MAX_QC_FINDINGS` | 8 findings per rewrite (also the cap on her review's findings) | `194`, `346` |
| `MAX_PAYLOAD_CHARS` | 14,000 (lessons ride on top) | `195` |
| Not a finding | the gate's «verdictul modelului de vedere» line, `fix_check.PROCESS_NOTES` | `197`, `1579-1589` |
| `MOTION_FIELDS` | motion, camera_move, ending_frame | `143` |
| `SERIAL_STILL_FIELDS` / `SERIAL_MOTION_FIELDS` | action, emotion, background, continuity, ending_frame, camera_move / camera_move, ending_frame (the motion layer's feeling goes to `motion_emotion`) | `176-184`, `1526-1527` |
| Review answer caps | observations ≤6 (each ≤300), broken lessons ≤6, locked quote ≤300 | `278`, `348-349`, `369` |
| `MAX_FILM_FINDINGS` | 6 film findings per redo brief, each ≤400 characters, with causes ≤400 | `2945`, `2977-2987` |
| `CONTENT_REFUSAL_PHRASES` | «nu arată ce cere scena», «nu arată ce cere planul», «text lizibil», «interzice fețele», «încalcă biblia», «aspectul filmului» | `2579-2586` |
| Token limits | brief 2500, review 2400, rewrite 3000 (Director ×2 in `run_agent_task`) | `1394`, `1742`, `1889` |
| Lint rounds per rewrite | 2 | `1868` |
| Reasons kept per refusal | ≤4 reasons, each ≤400 characters | `799` |

The rung as a state machine (one scene, one call of `_rung`):

```
director_brief ── none ──► record attempt (rewritten False) ──► scene waits
      │ brief
      ▼
round 1: _editor_rewrite ── no package ──► reason ──► letters + record
      │ package
      ├── same words as stored ──► same_prompt True (caller may turn to the still) ──► record
      ▼
_reviewed ── TREATS ──► store (lock, not closed, package unchanged) + unverified lesson + prompts_rewritten event
      │      None ──► review_unavailable, nothing stored
      │      MISSES, every serious untreated finding locked, no lesson broken ──► not_treating
      │                (motion layer: layer_exhausted; rewrite_failed_scene runs a still rung)
      │ MISSES
      ▼
round 2: _editor_rewrite with her why_not ── no package ──► not_treating
      │                                    ── stored or refused words ──► not_treating (+ layer_exhausted on motion)
      ▼
_reviewed ── TREATS ──► store ; MISSES ──► not_treating (locked: as above) ; None ──► not_treating (round 1's refusal stands)
```

### Looks (`series_look.py`) and serial storyboards (`serial_storyboard.py`)

| Constant / rule | Value | Where |
|---|---|---|
| `SERIES_LOOK_FILE` | `config/serial_series_look.json` (v2, 2026-10-11, in use, `max_prompt_chars` 980) | `series_look.py:30` |
| `DEFAULT_MAX_PROMPT_CHARS` | 980; any value clamped to 300-2000 | `series_look.py:34`, `150` |
| `DEFAULT_SHOT_SIZES` / `SHOT_TYPES` / `PART_PURPOSES` | four sizes; hook→HOOK, situation→SETUP, turn→REVEAL, payoff→PAYOFF, button→ENDING | `series_look.py:38-61` |
| `FACTUAL_LOOK_FILE` | `config/factual_look.json` | `series_look.py:191` |
| `LOOK_MIN_WORDS` / `LOOK_MAX_WORDS` | 40 / 60 | `series_look.py:209-210` |
| `DEFAULT_SLOT_WORDS` | place 8, season 4, weather 6, light 8, palette 8 | `series_look.py:204` |
| `OVERCAST_LIGHT` | said when a bible rule asks for overcast/diffuse light | `series_look.py:213-214`, `534-535` |
| `WORDS_PER_SECOND` | 2.5 | `serial_storyboard.py:81` |
| Episode length | 30-75 s | `serial_storyboard.py:196` |
| Scene length | 3.0-9.0 s | `serial_storyboard.py:334` |
| Transitions | FADE for scene 1, CUT after | `serial_storyboard.py:349` |
| `TOPIC_STATUS` | `SERIAL` (keeps the factual selection off it) | `serial_storyboard.py:82`, `207` |

### Related limits outside this group

| Constant | Value | Where |
|---|---|---|
| `SHOT_PLAN_REASK_DAYS` | 2 | `backend/app/runbook/stages.py:1946` |
| `DIRECTOR_LADDER_ROUNDS` | 3 rounds of rewrites per walk | `backend/app/runbook/stages.py:1609` |
| `SHOT_PLAN_SOURCES` / `SERIAL_SHOT_PLAN_SOURCES` | `("model",)` / `("model", "series_look")` | `backend/app/media/assembler.py:9832-9835` |

## Modules

### `app.media.prompt_agent` — `backend/app/media/prompt_agent.py` (3695 lines)

Purpose: the step between the approved script and the generator. It asks the Video Editor's model
for a bible and a shot plan, validates them, and compiles the words each paid model receives. It
also keeps the studio's prompt lessons (scoped by kind of film, unverified until a picture proves
them, superseded by corrections) and assembles the audit package. Why: the prompts that said
nothing, the Nepal codes, the lost plan, the stacked panels, «Mișcare v2» and the lessons review of
a9f84ea (see "Why it exists").

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `ShotPlanUnusable.__init__` | 210 | Exception carrying the board id and missing scenes | A film whose plan could not be read after the re-ask is held, not rendered from templates | CODE_RULE |
| `_scrub_codes` | 268 | Removes clauses holding ENUM codes or hex colours from a bible value; keeps words around a hex | Nepal bible pasted "NEPAL_CLIMATE_CRISIS" and "#2E4A66" into every prompt | CODE_RULE |
| `_is_serial` | 435 | Serial by `series_key == office_serial` or `story_json.kind` | Chooses the serial brief and composer | CODE_RULE |
| `_serial_scene_facts` | 443 | Adds the beat's part, room, lines, speaker bible ids, background people | The serial brief needs who speaks and where | CODE_RULE |
| `_film_facts` | 479 | Builds the facts dict: title, story, scenes (narration, writer's line from the script, claims, characters) | Reads the writer's own line from the script first, then the stored `writer_visual`, and `visual_prompt` only as a last fallback, so reruns do not drift (`528-536`) | CODE_RULE |
| `new_numbers` | 574 | Numbers of 2-4 digits in a text that the narration/claims never state (lenses, ratios, fps excluded) | "A prompt is not a place to write history" | CODE_RULE |
| `strip_on_screen_text` | 598 | Removes sentences/`;` clauses that ask for writing (overlay, caption, title card, "reads: '…'") | Models draw letters as gibberish (ATLAS "Theam Thory") | CODE_RULE |
| `strip_style_overrides` | 651 | Removes clauses that restyle (photoreal, anime, film stock, 16:9, engine names) | 2026-09-24 adversary pass: a model's "shot on 35mm film" pulled serial stills off the look | CODE_RULE |
| `_coerce` | 688 | Fits any answer to a schema: flatten, cut at word, scrub bible codes/hex, collect `card_palette` | ATLAS plan discarded for two long fields | CODE_RULE |
| `repair_json` | 781 | Narrow repair: escape an inner quote, drop a trailing comma | Nepal plan lost to one unescaped quote | CODE_RULE |
| `_salvage_shots` | 853 | Decodes each shot on its own from its `"scene_index"` brace | One unreadable shot no longer loses the others | CODE_RULE |
| `parse_shot_plan` | 881 | Strict → repaired → salvaged → none, keeping the decoder's error | Read as much of a plan as possible; the error feeds the re-ask | CODE_RULE |
| `trim_payload` | 941 | Drops whole longest claims, then lessons, then scenes from the end until the JSON fits | The payload used to be sliced mid-string | CODE_RULE |
| `fit_with_lessons` | 983 | Fits the data without lessons, then puts the lessons first | Serial payload at 14-15k of 16k would have lost every lesson first; also used by the rewrite payloads (`scene_rewrite._fitted`) and the serial episode writer (`story/services.py:1530-1556`) | CODE_RULE |
| `lessons_rule` | 998 | `LESSONS_RULE` when lessons exist: lessons are rules, an unverified one yields to a confirmed one, none overrides the brief's fixed rules (`164-173`) | Lessons inside the inert boundary must be named as rules; a lesson of one kind of film can contradict the other's look | CODE_RULE |
| `build_visual_bible` | 1018 | LLM call site 1 (above); lessons of the film's kind (`1042`) | One look per film | LLM_CHECKED_BY_CODE |
| `_avoid_list` | 1100 | Defaults first, then the film's exclusions, ≤16 | The studio always refuses the "raw AI" failures | CODE_RULE |
| `write_shot_prompts` | 1113 | LLM call site 2 (above), with gates, re-ask, validation, compile/compose, status and events; lessons of the film's kind (`1153`) | The last step before money | LLM_CHECKED_BY_CODE |
| `_reask_note` | 1393 | The re-ask's addition: decoder error, missing scenes, quoting rule | One re-ask carrying the decoder's words | CODE_RULE |
| `shot_plan_gaps` | 1403 | Scenes whose package `source` is not in the allowed sources | f06808c9: serial look-composed scenes were read as gaps | CODE_RULE |
| `hold_for_shot_plan` | 1422 | Under the write lock: closed film → []; gaps → board NEEDS_SHOT_PLAN + WARNING event (`held_by: media_stage`) | PRODUCTION buys only model-written plans; the media stage asks it for factual films only (`runbook/stages.py:3191-3193`) | CODE_RULE |
| `_validated_package` | 1469 | Builds one shot's package: purpose, fields with fallbacks, `camera_move` enum, `second_framing`, `source`; strips text requests and invented numbers | Gaps filled from the film's own facts; invented facts cut | CODE_RULE |
| `_second_framing` | 1556 | Accepts `{subject, centre_x, centre_y}` with numeric centres clamped to 0..1 | A free closer framing for the edit; a rough answer never costs the shot | CODE_RULE |
| `_identity` | 1595 | A character in ≤limit characters, whole clauses only, hair then garment | f06808c9 stills said «Tousled wavy dark hair, wearing;» | CODE_RULE |
| `_serial_package` | 1626 | Serial package: size by part, people in frame, room from the beat, model fields restyled-out, look's avoid, `series_look_version`, `from_model`, purpose by part | The room is the beat's, never the model's | CODE_RULE |
| `_still_moment` | 1741 | First moment of each person's clause (cut at later-moment words and at a comma that starts a new moment) | Chains of moments drawn as stacked panels (f06808c9) | CODE_RULE |
| `compose_serial_prompt` | 1822 | Look block word for word, room, fixed framing, frame sentence, blank-pages sentence, people, first moment; shrinks people then action to the cap; adds emotion/background/continuity while room | Serial stills in one look, no `Camera:`/`Action:` rubrics (TEMPLATE_LABEL refusals) | CODE_RULE + CONFIG |
| `_serial_camera_move` | 1906 | Plan's move unless it repeats the previous scene's | SAME_CAMERA_EVERY_SCENE on f06808c9 | CODE_RULE |
| `_action_for_ending` | 1977 | The action as it may be said beside the ending and the move: whole when they fit 95 words and 1000 UTF-16 units with the closing, else with later moments left out (`_shorter_actions`), down to each person's first moment; else whole, and the ending is left out | f06808c9 scene 3: the ending was dropped, two rewrites composed to the same prompt | CODE_RULE |
| `compose_serial_motion` | 2003 | Move sentence, action (fitted beside the ending, `2048-2052`), ending sentence, faces, life, feeling (`motion_emotion` first), second beat, closing | Until 2026-10-11 serial clips had no motion prompt of their own | CODE_RULE |
| `compose_prompt` | 2071 | Legacy labelled prompt ("Camera: … Avoid: …"), cut at 1400 | Pre-compiler composition; no production caller | CODE_RULE |
| `cut_at_sentence` | 2123 | Cuts within a UTF-16 limit after the last whole sentence or word | A sliced prompt is read as an instruction | CODE_RULE |
| `without_scene_reference` | 2398 | Removes "scene 1", "the previous scene" pointers; drops a clause left broken | babcf272 "the identical tunnel from scene 1" | CODE_RULE |
| `_clauses_of` | 2430 | Clauses of a plan field that may enter a prompt; still: first moment only, first picture of a layout; motion: no camera words, colours or then-chains | One filter for every field the compiler reads | CODE_RULE |
| `hide_faces` | 2569 | Adds "seen from behind" after a person mention not already hidden | Bible face rule | CODE_RULE |
| `shot_frame` | 2617 | (size, sentence) from the camera text or shot type: size, lens mm, angle | The still says the frame, never the camera's path | CODE_RULE |
| `choose_camera_move` | 2656 | The clip's one move (see "Who decides") | One move per clip, varied across the film | CODE_RULE |
| `_fit_sentences` | 2685 | Chooses ranked sentences under a word budget, then removes whole sentences to the UTF-16 cap | Caps are met by leaving sentences out, never slicing | CODE_RULE |
| `_motion_intent` | 2744 | Model-neutral intent: move, world motion (≥3 words, no people), subject clauses, action verbs, seconds, amplitude, constraints, faces | One intent, re-rendered per vendor at purchase | CODE_RULE |
| `render_motion` | 2808 | (promptText, negativePrompt) for a family; replaces legacy stillness; adds END_BEAT, MEASURED_SENTENCE (never reached today, see "Who decides"), face constraint (not on veo), closing (veo and gen4 without «No ...»); pads under 25 words | «Mișcare v2»; vendor dialects | CODE_RULE |
| `_scene_constraints` | 2863 | Plan's `avoid` as nouns for a negative channel (no camera words, codes or hex) | ADR-POSITIVE-PROMPTS-ONLY | CODE_RULE |
| `compile_prompts` | 2885 | Still prompt (look block, frame, subject, cast, action, environment, people sentence, composition, light, exclusions), camera move, motion intent and motion prompt; cards get no prompt | Two prompts per filmed scene, each in its model's words | CODE_RULE |
| `_cast_sentence` | 2994 | Characters by look, never by name; faceless → "a figure seen from behind wearing …" | A name can be drawn as writing | CODE_RULE |
| `compile_film_prompts` | 3014 | `compile_prompts` across a film with per-scene contracts | Model chosen per scene by cost (Owner, 2026-09-27); no production caller | CODE_RULE |
| `motion_prompt_for` | 3037 | Re-renders a stored motion intent for the model actually bought; legacy packages use the stored text | The scene's model is decided at purchase | CODE_RULE |
| `_run` | 3054 | `run_agent_task` wrapper returning None on failure | A failed call is a degradation | CODE_RULE (gateway) |
| `lesson_words` | 3152 | Normalised content words: accents off, plurals folded, filler and picture-lesson scaffold words out, length >2 | Lesson comparison; the shared scaffold let «Keep the camera static.» pass for its correction (review of a9f84ea) | CODE_RULE |
| `lesson_overlap` | 3166 | Share of the NEW lesson's content words found in the other (a lesson with no content words matches only the same text) | Measured from the shorter lesson, a short older rule blocked the longer correction | CODE_RULE |
| `lesson_scope` | 3192 | "serial" or "factual" for a storyboard, "all" when it is not found | Scope of a lesson learned on a film; no caller in `backend/app` (oddity 29) | CODE_RULE |
| `_lesson_stamp` | 3261 | A timestamp with microseconds later than every lesson row's own | Lessons are ordered by it, and `withdraw_prompt_lessons` finds the lesson a withdrawn one replaced by it | CODE_RULE |
| `prompt_lessons` | 3319 | Of the newest 200 live lessons, those of `scope` and "all" (every scope when None); near-duplicates either way dropped, the newer kept; confirmed first, then unverified with " (unverified)"; 12 in all | Every writer reads the studio's lessons of its kind of film | CODE_RULE |
| `lesson_is_general` | 3376 | Why a text is not a rule (empty, >400 chars, a UUID, a scene/shot/beat by number, three consecutive words of a given title), or None | Review of a9f84ea: one film's «scene 4» note became a rule for every film; also used by the editorial review (`agents/editorial.py:403-417`) | CODE_RULE |
| `_names_an_id` | 3400 | A whole UUID, or a hex head that starts a storyboard id | A rule for every film cannot name one film | CODE_RULE |
| `lesson_refusal` | 3415 | `lesson_is_general` against every storyboard title, then `_names_an_id` | One refusal check for every lesson writer | CODE_RULE |
| `record_prompt_lesson` | 3429 | Refuses what `lesson_refusal` refuses; compares with the newest 40 live lessons of its scope and "all": stores a new one, refreshes the closest when ≥0.9 inside it (its words when longer or broader; proven if either was), else supersedes the closest (retired when of the same scope); stores `STRATEGY` memory `prompt lesson: [scope][?] …` | Owner, 2026-10-12, «la viitoarele prompturi să se asigure că nu mai sunt»; review of a9f84ea: the older lesson used to win | CODE_RULE |
| `confirm_prompt_lessons` | 3516 | The live unverified lessons of the given source runs stored again without `[?]` (`CONFIRMED_RO` on the old row) | A picture made from the rewrite passed with every finding gone | CODE_RULE |
| `withdraw_prompt_lessons` | 3532 | The live unverified lessons of the given source runs retired; a lesson one of them superseded (same stamp, `SUPERSEDED_RO`) is stored again unless it is the same lesson (≥0.9) | A lesson that did not correct the mistake must not teach it | CODE_RULE |
| `production_package` | 3567 | Read-only audit bundle: idea, thesis, sources, fact check, story, timeline, CTA, bible, shot list with prompts, audio intent, continuity, exclusions, duration, approval (including who let the story through) | The Owner's list of what a person needs to audit a film | CODE_RULE |

Helpers: `_hex6` (normalise hex to `#RRGGBB`), `_allowed_text` (title, narration, claims, story strings),
`_flatten` (structured value as one line), `_max_length` (field cap from pydantic metadata),
`_first_object` (first JSON object with a wanted key), `_decoder_error` (decoder message with
offset/line/column), `_shots_from` (validate each shot, first per index wins), `_parse_shot_pack`
(no caller), `_scene_lists`, `_dumps`, `_parse_bible`, `_listed`, `_short_name` ("Dr. Aris"),
`_fit` (cut at a word), `_clauses`, `_clean_cut` (drop a dangling function word), `_next_moment`,
`_first_moment`, `_serial_framing` (the look's fixed framing for the size), `_action_moments` (a
beat's action as each person's moments), `_shorter_actions` (the action with one later moment fewer
at a time, then the first moments alone), `_then_head`, `_phrase` (whole clauses within a word
budget), `_sentence`, `_person_window`, `_shows_people`, `_motion_family`, `_contract_model`,
`_continuous` (chain words removed, chain kept), `_seconds_of`, `_intent_clauses`, `_plain` (accents
off, lower case), `_fold` (plural to singular), `_scope_of`, `_checked_scope` (refuses an unknown
scope), `_read_lesson` (scope and `[?]` read from a row's head), `_lesson_content`, `_lesson_rows`,
`_live_lessons` (the newest 200 live lessons of some scopes), `_retire` (`app.agents.memory.invalidate`
with the stamp), `_store_lesson`, `_title_words`, `_title_named`, `_provisional_from` (live
unverified lessons of some source runs, oldest first). The dataclass `_StoredLesson` holds one row.

Data read: `Storyboard` (including every title, for `lesson_refusal`), `StoryboardScene`,
`ScriptDraft`, `FactualClaim`, `CharacterBible`, `MemoryRecord`, `TopicIdea`, `SourceSnapshot`,
`StoryReview` (via `latest_review`), the headquarters locations (`app.story.locations`). Data
written: `Storyboard.visual_bible_json`, `Storyboard.status` (`NEEDS_SHOT_PLAN` / `APPROVED`),
`StoryboardScene.prompt_json`, `visual_prompt`, `story_purpose`, `shot_type` (serial), `MemoryRecord`
(`STRATEGY`, "prompt lesson: [scope][?] …", with `created_at` from `_lesson_stamp`; retired rows get
`invalidated_at` and a reason). Events: `media.visual_bible_written`, `media.shot_prompts_written`,
`media.shot_prompts_incomplete`. External calls: model runs only, through `run_agent_task`. Config
read: `config/serial_series_look.json`, `config/factual_look.json` (through `series_look`).

### `app.media.prompt_lint` — `backend/app/media/prompt_lint.py` (1272 lines)

Purpose: read every prompt before a credit is priced or spent. Pure text: no database, provider or
network (`1-13`). Each finding has a code, severity, scene, verbatim evidence and a Romanian message
for the Owner. It also exports the shared vocabularies the compiler uses (camera moves, speed words,
later-moment openers, person words, face patterns, kind phrases).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `dangling` | 309 | Clause ends in a function word, unless it is a particle after a verb of motion ("fog rolling in") | babcf272 "two interconnected spaces: the" | CODE_RULE |
| `without_asides` | 329 | Opens, removes or keeps parenthetical asides so clauses stay whole | babcf272 "lined with (blue-painted) magnets" lost its tunnel | CODE_RULE |
| `Finding.as_dict` | 455 | Serialises a finding | Sheet and 409 bodies | CODE_RULE |
| `PromptLintBlocked.__init__` | 480 | Exception holding BLOCK findings | Intended for `require_no_block` | CODE_RULE |
| `utf16_units` | 488 | Length as JavaScript counts it | Vendor caps are in UTF-16 units | CODE_RULE |
| `model_family` | 548 | veo / seedance / wan / gen4 / seedream by id prefix | Dialect rules per family | CODE_RULE |
| `prompt_cap` | 558 | Cap from the contract (`prompt_max_utf16` or `prompt_max`, per task), else 1000 | Vendors state their own limits | CONFIG / CODE_RULE |
| `classify_kind_phrase` | 605 | Earliest chart / black screen / title phrase | Nepal chart and black screen became women | CODE_RULE |
| `bible_face_rule` | 617 | The bible's own words when it forbids faces | Nepal never carried "No human faces" | CODE_RULE |
| `camera_moves` | 640 | Distinct moves named in a text, in order | One move per clip | CODE_RULE |
| `shot_size` | 651 | First shot size a still names | Camera language across the film | CODE_RULE |
| `_hygiene` | 689 | Shared checks: ENUM_CODE, HEX_CODE, TEMPLATE_LABEL, AVOID_LIST, QUOTED_TEXT, OVER_CAP | The Nepal defects | CODE_RULE |
| `lint_still_prompt` | 781 | Still checks (exclusions, kind, sequence, panels, scene reference, faces, bible rule, length) | Image model failures seen live | CODE_RULE |
| `lint_motion_prompt` | 931 | Motion checks (equals/redescribes still, camera count, then-chain, veo negation, closing, speed, environment, stillness, length) | Video model failures seen live | CODE_RULE |
| `lint_scene` | 1112 | Kind check; cards must have no prompt; LIVE needs a still prompt; runs still and motion checks | A card never reaches a paid model | CODE_RULE |
| `lint_film` | 1173 | Every scene, then camera language across LIVE scenes | "The film looks like one picture" | CODE_RULE |
| `_camera_language` | 1196 | SAME_CAMERA_EVERY_SCENE (BLOCK) or SAME_CAMERA_RUN (WARN) | Nepal "Camera: medium shot, locked camera" on every scene | CODE_RULE |
| `has_block` | 1248 | Any BLOCK | The gate used by stills, redo and the sheet | CODE_RULE |
| `summary_ro` | 1252 | One Romanian line: counts and the first BLOCK | Sheet and 409 text | CODE_RULE |
| `require_no_block` | 1269 | Raises `PromptLintBlocked` on a BLOCK | Gate helper; no production caller | CODE_RULE |

Helpers: `_index_at_units`, `_words`, `_excerpt` (verbatim first sentence, cut at a word),
`_last_sentence`, `_norm`, `_distinct`, `_others` (Romanian «și încă: …» tail), `_sequence_in`,
`_panels_in`, `_person_mentions` (person words with a 3-before/6-after window), `_finding`,
`_content_words`, `_strip_closing`.

Data read/written: none. Events: none. External calls: none. Note on severity choice: STILL_SEQUENCE
is a WARN on purpose, because a BLOCK on a stored prompt makes the sheet LINT_BLOCKED and the sheet
repair would rewrite every scene, orphaning takes already bought (`822-824`).

### `app.media.scene_rewrite` — `backend/app/media/scene_rewrite.py` (3147 lines)

Purpose: the Director's ladder for a scene quality control refused: her brief, the Video Editor's
rewrite of that scene only, the code's compile and lint, her review against quality control's
findings by id and severity, the turn to the picture when the motion layer cannot treat them, their
letters, the record, and the lesson the review draws (`1-80`). Also the serial rung (recompose,
re-roll or brief). Why: the Owner's rules of 2026-10-11 and 2026-10-12 quoted above, and the
incidents on aa170155, 1c038a99 and f06808c9.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `SceneBrief._lower`, `_items` | 218, 223 | Lower-case the layer; normalise list items (≤8, each ≤240) | Tolerate the model's shape | CODE_RULE |
| `brief_schema` | 229 | Subclass refusing a layer not open | The layer the code allows is the only one she may pick | CODE_RULE |
| `FindingReview._number`, `_word`, `_text` | 282, 290, 295 | Digits of a string id as an int; lower-case severity/layer/field; normalise whitespace | Tolerate the model's shape | CODE_RULE |
| `FindingReview._explained` | 299 | Treated needs `by`; untreated needs `why_not`; locked needs `locked_words` | A verdict must be explained finding by finding | CODE_RULE |
| `BrokenLesson._text`, `_word` | 324, 329 | Normalise the lesson, why_not and field | Schema hygiene | CODE_RULE |
| `RewriteReview._said`, `_observed` | 358, 363 | Normalise cause, lesson, reason; observations from strings or dicts, ≤6, each ≤300 | Schema hygiene | CODE_RULE |
| `RewriteReview.blocking`, `verdict` | 375, 380 | The serious untreated findings; MISSES when any, or a broken lesson, else TREATS | Owner, 2026-10-12: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!» | CODE_RULE (on her answers) |
| `words_kept` | 390 | Whether a quote (parts around an ellipsis, case and spacing aside) is in one of the kept texts | A lock no quote supports would turn the scene to the picture, and buy one, on her word alone | CODE_RULE |
| `review_schema` | 402 | Her review bound to this rewrite: each QC id once, no other; untreated → editable field or a supported lock; broken lesson → editable field | f06808c9 scene 7: her own diagnoses read as findings | CODE_RULE |
| `shot_schema` | 452 | Per-layer required fields on a `ShotPrompt` for one scene | A rewrite must change what the layer rewrites | CODE_RULE |
| `_owner_still` | 723 | Whether an APPROVED still of the scene is one the Owner approved | A still the Owner approved is never rewritten | OWNER |
| `_local_move` | 743 | Whether the Owner chose `LOCAL_MOVE` for the scene | No paid motion for that scene | OWNER |
| `scene_takes` | 751 | The scene's takes, newest first | Shared reader | CODE_RULE |
| `last_failure_code` | 762 | Code of the newest failing take, unless a newer take is PAID/APPROVED/SUBMITTED | Only a current refusal counts | CODE_RULE |
| `scene_failures` | 778 | QC refusals (REJECTED with a quality code), each with up to 4 reasons (clip-QC `blocks_ro` or the gate's detail) | What the brief reads | CODE_RULE |
| `earlier_briefs` | 807 | Her briefs for the scene from `media.director_scene_brief`, with rewritten/same_prompt/layer_exhausted flags, reasons, review cause, why_not (or the refused rounds when the rung passed) and lesson | The same diagnosis is not written again | CODE_RULE |
| `untreated_findings` | 879 | Untreated findings with why (and the lock), each once, oldest round first, ≤6 | Feeds the next brief | CODE_RULE |
| `refused_rounds` | 896 | The refused rounds of a rung that ended TREATS, each with what it left untreated and its cause | Round 1's why_not read as if the scene still carried it | CODE_RULE |
| `open_layers` | 933 | The Owner's ladder (see "Who decides"); counts `layer_exhausted` as a motion attempt | Motion first, then the picture | CODE_RULE / OWNER |
| `scene_context` | 961 | Everything a rewrite reads, or None (no board, closed film, not LIVE, no plan); briefs beyond the newest 4 in short (≤12) | One context for brief, rewrite and review | CODE_RULE |
| `_serial_shot` | 1045 | Serial shot's size, fixed framing, people in frame, room, how still and clip are composed | Stored fields alone do not say who stands where | CODE_RULE |
| `lesson_scope` | 1079 | "serial" or "factual" from the context | The lessons a scene reads and writes are its kind of film's | CODE_RULE |
| `_fixed_still_sentences` | 1123 | The composer's sentences a still carries that no field writes (serial: look, room, framing, frame and blank sentences, the people sentence; factual: look block, people rule, composition, exclusions) | Words the still layer cannot change | CODE_RULE |
| `layer_terms` | 1156 | Per layer: the fields he may change (with what each becomes), the fields kept word for word, the fixed sentences of the still and the motion, the camera move | f06808c9 scenes 3, 4, 7: her review named words the motion layer keeps | CODE_RULE |
| `kept_texts` | 1251 | Every text a layer keeps, for a lock's quote | Feeds `words_kept` | CODE_RULE |
| `camera_move_sentences` | 1262 | `prompt_agent.MOVE_SENTENCES` as data | A move's words change only by choosing another move | CODE_RULE |
| `_data` | 1269 | Context as agent data (film, scene, stored shot, prompts sent, bible subset, refusals, briefs, older briefs in short, serial shot) | Inside the inert boundary | CODE_RULE |
| `_fitted` | 1305 | Fits the data to 14,000 by whole items (old refusals, then briefs to short form, then short ones), lessons whole in front | `trim_payload` dropped every lesson first (2026-10-12 review) | CODE_RULE |
| `director_brief` | 1335 | LLM call site 3 | Her brief | LLM_CHECKED_BY_CODE |
| `rewritten_package` | 1418 | Factual merge by layer, validate, compile; motion keeps the still's words | Only one layer changes | CODE_RULE |
| `serial_rewritten_package` | 1481 | Serial merge of composer fields, clean, compose | Serial words stay the composer's | CODE_RULE |
| `sentence_diff` | 1549 | Sentences removed and added | 1c038a99: three paid rewrites with empty or beside-the-point diffs | CODE_RULE |
| `review_findings` | 1592 | Film findings (with causes) plus the newest QC refusal split into its pieces, each with an id and QC's words, process notes dropped, ≤8 | A weeks-old panels refusal would make every later rewrite MISS; her own diagnoses read as findings | CODE_RULE |
| `findings_to_treat` | 1633 | `review_findings`, or her brief's diagnosis as finding 1 when none remain | Something must be answered | CODE_RULE |
| `review_rewrite` | 1650 | LLM call site 4 | Her review before purchase | LLM (per-finding answers; verdict derived by code) |
| `learn_from_review` | 1791 | Records a passing review's lesson for the film's kind, unverified, and reports the store's answer | Owner, 2026-10-12 | LLM_CHECKED_BY_CODE |
| `_lint_blocks` | 1823 | New BLOCK messages the rewrite adds | The rewrite may not add a blocker | CODE_RULE |
| `_editor_rewrite` | 1847 | LLM call site 5 | The Video Editor's rewrite | LLM_CHECKED_BY_CODE |
| `_reviewed` | 1925 | `review_rewrite` with any exception turned into no review | Fail closed | CODE_RULE |
| `_kept_findings` | 1959 | Her findings as the record keeps them: id, QC's words, her words, treated, by, why_not, severity (serious when unsaid), layer (the rewrite's when unsaid), field, locked, source | The contract `fix_check` checks the bought picture against | CODE_RULE |
| `_same_words` | 2018 | Round 2 equals round 1, word for word | Refused words cannot treat what they did not | CODE_RULE |
| `_second_rewrite_note` | 2029 | Her refusal (untreated with why and field or lock, broken lessons, treated with by, cause, `layer_terms`, refused prompts) in its own boundary | f06808c9: refusals never reached the Video Editor | CODE_RULE |
| `_second_rewrite_failed` | 2077 | Round 2 came to nothing: her first refusal stands; `layer_exhausted` when the motion layer gave its stored or refused words again | The motion layer has nothing else to say | CODE_RULE |
| `_locked_on_layer` | 2097 | Every reason she refused for is locked: no second rewrite; motion → `layer_exhausted`, still → the scene waits | Another rewrite on the layer cannot treat words it keeps | CODE_RULE |
| `rewrite_scene` | 2116 | The rung's rewrite and review loop and the store (see state machine) | Store only reviewed words | LLM (verdict) + CODE_RULE |
| `_letters` | 2379 | HANDOFF letter Director → Video Editor and STATUS answer (including the picture's turn), both resolved at once | The agents talk about the work; nobody is asked to answer | CODE_RULE (text INFORMATIONAL) |
| `_record_brief` | 2485 | `media.director_scene_brief` event with brief, outcome, findings, observations, broken lessons, locks, review rounds; Director's `AGENT_OPINION` memory | The next brief, `fix_check` and the watchdog read it | CODE_RULE |
| `refusal_kind` | 2589 | CONTENT or TECHNICAL from code and detail phrases | f06808c9 scene 4: a named defect was re-rolled on the same words | CODE_RULE |
| `serial_refusal` | 2605 | (code, kind, detail) of the scene's newest refusal | Serial rung input | CODE_RULE |
| `_serial_scene` | 2624 | Whether the film is a serial episode (`is_serial_film`) | Chooses the serial rung | CODE_RULE |
| `serial_recomposition` | 2638 | Today's composer output for a stored serial plan, when it differs; reads only, 0 credits | f06808c9 stills bought on words from before the composer's fix | CODE_RULE |
| `_say_serial_words_again` | 2707 | Stores the recomposed words; `media.prompts_rewritten` with reason `serial_recompose`, layer still | The hold lifts and the stills step buys again | CODE_RULE |
| `recompose_serial_scene` | 2745 | Serial rung: recompose; else re-roll on a technical refusal (`serial_reroll` event); else `needs_brief` on a content refusal | Owner rule: redo until QC passes | CODE_RULE |
| `_serial_words_said_again` | 2860 | Recompose before her brief on a serial redo | Her brief reads today's words | CODE_RULE |
| `rewrite_failed_scene` | 2885 | One rung for a scene the ladder answers, with the guards (serial, context, QC code, local move, Owner still); after a `layer_exhausted` motion rung, a still rung in the same call when the still is open | Entry point of the ladder per scene; f06808c9 scenes 3, 4, 7: nothing turned to the picture | CODE_RULE |
| `film_failure` | 2948 | The finished film's refusal as a brief reads it: findings (≤6, each ≤400) with each one's cause, read from dicts or after a «cauza:» / «cause:» label, and a scene-wide cause | Her film-QC verdict's cause starts the brief instead of a new diagnosis | CODE_RULE |
| `rewrite_for_redo` | 2991 | Brief + rewrite + review before a paid redo her film QC decided; film findings first (`film_failure`); layer forced; a serial scene's stale words are recomposed first. Returns `rewritable` False (the caller's redo then goes on unchanged) for a card, a closed film, a package with no plan or, on the still layer, an Owner-approved still; a rewritable scene not rewritten makes the caller buy nothing (`runbook/stages.py:4854-4863`) | «Nu reface pur și simplu imaginea, trebuie verificat promptul și corectat!» | CODE_RULE |
| `_rung` | 3045 | Brief → rewrite → letters → record; outcome flags (`same_prompt`, `not_treating`, `review_unavailable`, `layer_exhausted`, rounds, lesson) | One rung | CODE_RULE |
| `director_ladder` | 3111 | `rewrite_failed_scene` for each scene, split into rewritten / not rewritten | The walk's call | CODE_RULE |
| `quality_refused` | 3139 | Scenes whose newest failure is a quality code | Other failures (vendor, account) wait as before | CODE_RULE |

Helpers: `_said_text`, `_quoted` (a quote as compared), `_payload` (event payload as dict),
`_finding_words`, `_untreated`, `_cut` (cut at a word with an ellipsis), `_brief_in_short` (older
brief summary), `_shot_of` (shot fields of a package), `_norm`, `_present` (sentences a prompt says,
in its order), `_fixed_motion_sentences` (the move sentence, second beat, measured sentence, faces,
world motion, pad and closing a motion carries; serial faces and life), `_dumps`, `_motion_changed`
(any of `MOTION_IDENTITY` differs), `_sentences`, `_pieces` (a refusal split at «; » outside «…»),
`_is_finding` (not the gate's verdict line, not a `fix_check.PROCESS_NOTES` note), `_no_review`,
`_round_record`.

Data read: `Storyboard`, `StoryboardScene`, `ScriptDraft`, `SceneTake`, `DomainEvent`
(`media.director_scene_brief`), clip-QC reports (`assembler.clip_qc_of`), the Owner's approvals and
scene choices (`director_qc.owner_approved_take_ids`, `owner_scene_choices`), `MemoryRecord` lessons
of the film's kind (`prompt_agent.prompt_lessons`), the serial look (`series_look.load_series_look`,
`series_bible`), the factual look (`load_factual_look`), `fix_check.PROCESS_NOTES`. Data written:
`StoryboardScene.prompt_json`, `visual_prompt`, `story_purpose`; `MemoryRecord` (`STRATEGY` lesson,
scoped and unverified, through `record_prompt_lesson`; `AGENT_OPINION` brief); `AgentMessage`
(letters). Events: `media.prompts_rewritten` (reasons `director_brief`, `serial_recompose`,
`serial_reroll`; the brief's review carries findings with ids, observations, `lesson_scope`,
`lesson_provisional`, refused rounds), `media.director_scene_brief` (now also `asked_layer`,
`layer_exhausted`, `locked_findings`, `qc_findings`, `observations`, `broken_lessons`,
`lesson_recorded`, `lesson_skipped`). External calls: model runs only.

### `app.media.sheet_words` — `backend/app/media/sheet_words.py` (512 lines)

Purpose: the shooting sheet's Owner-facing Romanian sentences that span rows: what the Owner's look at
a take set going, the assembly's wait said once, a vendor's refusal in the Owner's words (`1-19`). Why:
on the Nepal sheet (81438d13, 2026-10-04) the notice said «Nimic nu s-a cumpărat» while the Owner's
choice had queued FILM_CONTINUE, the assemble card repeated a sentence five times, and the vendor's
English appeared twice. It never calls `may_act` (that could spend a yes the Owner already gave); it
reads the same policy.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `scene_list` | 46 | «1, 2, 3 și 6» | Romanian scene lists | CODE_RULE |
| `blocked_words` | 69 | One sentence per reason (NO_STILL, NO_SHOT, own reasons) | The assemble card repeated one sentence per scene | CODE_RULE |
| `dedupe_clauses` | 139 | Vendor text with each `;` clause once | Vendor English shown twice | CODE_RULE |
| `refusal_view` | 154 | Kind, explanation, vendor text once, credits and whether measured; HTTP 4xx at submit → 0 credits; an accepted but unmeasured request keeps its quoted credits | 2026-10-04 adversary review: a possibly-charged refusal was shown as 0 credits | CODE_RULE / EXTERNAL |
| `_refusal_kind` | 186 | PICTURE_TOO_LARGE, RATIO_NOT_AUTO, else `production_policy.classify_failure` kind with a Romanian sentence | Known Runway refusals named | CODE_RULE |
| `_next_step` | 250 | First sheet step with something to buy | Name what comes next | CODE_RULE |
| `_continuation_live` | 274 | The queued FILM_CONTINUE (or any live one for the film) is QUEUED/RETRYING/CLAIMED/RUNNING | A re-chosen picture returned a task that ran hours before (deaa682c) | CODE_RULE |
| `_standing_answer` | 302 | The Owner's APPROVED/REFUSED answer for this step and plan hash, read without spending | The sentence must say whether the Owner's yes will be spent | OWNER (read) |
| `_continuation_words` | 337 | (buys unasked, sentence) in `may_act`'s order: stop, safe mode, media-stage tier vs mode, assembly/narration, T4, the Owner's paid-media rule (EVERY_PAID_STEP / OVER_USD), standing answer, daily budget, mode | Tell the truth about what the continuation will do | CODE_RULE (describes OWNER policy) |
| `decision_outcome` | 454 | `message_ro`, `continues`, `buys_unasked`, `next_step` for the Owner's take decision | The page must say what the Owner's press did | CODE_RULE |

Helpers: `_scenes`, `_mb`, `_safe_mode_open`, `_media_stage_tier` (`runbook.stages.STAGE_ACTIONS`),
`_rule_words` (`runbook.stages.paid_rule_words`).

Data read: `OwnerPolicy` (environment, autonomy stop, mode, paid-media rule), `SafeModeRecord`,
`TaskQueueItem`, approvals (`services._answered_approval`), daily budgets. Data written: none.
Events: none. External calls: none. Trust: INFORMATIONAL output.

### `app.media.sheet_story_repair` — `backend/app/media/sheet_story_repair.py` (277 lines)

Purpose: repair a blocked film's prerequisites before the editor is asked to describe it again: a
new script (and so a new storyboard) when the story gate fails or a blocker can only be fixed in the
story (a scene too long for any clip, a chart or card scene described wrongly). Revisions are new rows;
bought media and narration keep their provenance (`1-5`). Called by `blocker_repair`
(`backend/app/media/blocker_repair.py:799`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `progress` | 28 | Newest `media.sheet_story_repair_progress` payload for the board | The cursor survives retries | CODE_RULE |
| `save_progress` | 39 | Appends a progress event under the write lock | Durable checkpoint | CODE_RULE |
| `retire_replaced` | 45 | Closes the replaced board through `close_film_books` (`retired_by "Director"`, spent recorded) unless leased, in flight, rendered, serial, already closed, or the replacement is REJECTED | Owner, 2026-10-11: «De ce există 2 Storyboard? Trebuie doar 1!» | CODE_RULE |
| `retire_replaced_boards` | 93 | Closes every replaced board still open (watchdog pass `replaced_boards`) | Boards replaced before 2026-10-11 | CODE_RULE |
| `_handoff` | 120 | HANDOFF letter from the Director to the responsible role with the reason | Who does the repair is visible | CODE_RULE |
| `repair_story` | 147 | See below | One durable revision per task | CODE_RULE + LLM (writer, reviewer) |

`repair_story` in order: a replacement already recorded → retire the old board, `REVISED`
(`157-159`); read the gate and latest review (`171-173`); collect SCENE_TOO_LONG and KIND_MISMATCH /
CARD_INVALID issues (`176-177`); nothing to do → None (`178-179`); no review yet → ask the Director's
story review (`180-187`); story not passed or a visual rewrite needed → notes (repair rules, split
instruction, review notes ≤5, issue details ≤2), handoff to the ScriptWriter, `agent_write_script`
(`ScriptRejected` → `UNRESOLVED` ScriptWriter, `NoVerifiedClaims` → `UNRESOLVED` FactChecker),
checkpoint, story review, gate (`189-237`); a reused candidate that passed gets a synthesized
`{"verdict": "PASS"}` (`238-239`); `_director_approves` (review PASS and grounding) or `UNRESOLVED`
Director (`240-249`); reuse a board already made for the script or `generate_storyboard_from_script`,
copying channel, series key and overrides (`251-267`); checkpoint and retire (`268-277`).

Data read: `Storyboard`, `ScriptDraft`, `StoryReview`, `DomainEvent`. Data written: new
`ScriptDraft`/`Storyboard` (through the factual and media services), board channel/series/overrides,
progress events, letters; old board REJECTED with `runbook.film_retired` (through
`close_film_books`). External calls: model runs through the factual pipeline. No media purchase.

### `app.media.series_look` — `backend/app/media/series_look.py` (597 lines)

Purpose: the two looks as the prompts read them. The serial look is a proposal file the Owner edits
(`config/serial_series_look.json`), versioned, never written by a model (`1-16`). The factual look
(`config/factual_look.json`) opens every factual still prompt with one block of 40-60 words; the
bible supplies place, season, weather, light and palette only in whole clauses that a model would
read correctly (`181-188`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `serial_shot_size` | 64 | Size by beat index, part and speaker count | The camera varies across an episode | CODE_RULE |
| `load_series_look` | 89 | Reads the file; block only when `use_until_the_owner_changes_it` and non-empty; strips writing requests; shot sizes merged; cap clamped 300-2000; missing file → no look | The Owner switches the look by editing a file | CONFIG |
| `series_bible` | 155 | The look in the factual bible's shape, `source "series look"` / `"no series look"` | Package and viewing read it unchanged | CONFIG |
| `load_factual_look` | 271 | Reads the factual look with built-in defaults | The studio still films one look when the file is missing | CONFIG |
| `_names_several_places` | 339 | A world of more than one place (labels or "two … spaces") | babcf272 tunnel and void | CODE_RULE |
| `look_phrase` | 357 | Whole readable clauses of a bible value, within a word budget; drops codes, hex, negations, people, writing, style overrides, shot sizes, charts, then-chains, later moments, panels, quotes, place-scoped pieces for whole-film slots | babcf272 "The setting is entirely" fragments | CODE_RULE |
| `look_block` | 473 | Rendering, where (place/season/weather), light (overcast rule, place-by-place → none), palette, fills, lens and grain; slots omitted when the scene names its own; fitted to 40-60 words by dropping season, weather, then sentences | aa170155 daylight over a lamp-lit night desk | CODE_RULE + CONFIG |

Helpers: `_clean`, `_strings`, `_said`, `_scoped_to_a_place`, `_place_by_place`, `_bible_rules`,
`_sentence`.

Data read: the two config files. Data written: none. Events: none. External calls: none.

### `app.media.serial_storyboard` — `backend/app/media/serial_storyboard.py` (410 lines)

Purpose: turn one APPROVED serial episode into the same rows `generate_storyboard_from_script`
produces, so the render, narration review, QC, the Director's viewing and the publishing gate run
unchanged; rows the serial does not naturally have are written honestly (`1-43`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_character_line` | 89 | A bible's look as one line | First-draft visual line | CODE_RULE |
| `_story_gate_record` | 103 | StoryReview row: PASS with her checks and run when her review passed; otherwise PASS recorded as the Owner's approval, no reviewer, no checks, `source "owner_approval"` and a note | S10: an Owner-only approval read as if she had passed it | CODE_RULE |
| `storyboard_from_episode` | 156 | Once per APPROVED episode: TopicIdea (SERIAL), ScriptDraft (dialogue as voiceover, per-scene lines and `speaker_bibles`, `story_json.kind office_serial_episode`, no claims), StoryReview, `media.storyboard_created` event, Storyboard (APPROVED, 9:16, series key, series bible), one scene per beat (size by part, duration by words, cast bibles); then `write_shot_prompts` with no model | Nothing consumed an approved episode before | CODE_RULE (the Owner's or the Director's approval upstream) |
| `_registered` | 368 | Registry has registered ids | Whether a model can be asked | CODE_RULE |
| `describe_serial_shots` | 375 | Re-describes shots through `write_shot_prompts` unless every package carries the current look version and (all from a model or no model registered) | Once per look version | CODE_RULE + CONFIG |

Data read: `StoryEpisode`, `DailyStudioLog`, character bibles for the roster, studio locations,
`ChannelRecord` (OFFICE_SERIAL), `AgentRun`. Data written: `TopicIdea`, `ScriptDraft`,
`StoryReview`, `Storyboard`, `StoryboardScene`, `StoryEpisode.storyboard_id`. Events:
`media.storyboard_created` (plus the prompt agent's events). External calls: a model run only
through `describe_serial_shots`.

## Connections

Calls into this group:

| Caller | Calls | Where |
|---|---|---|
| Daily runbook, story stage | `write_shot_prompts` for new boards, re-ask of NEEDS_SHOT_PLAN boards | `backend/app/runbook/stages.py:1130`, `1258` |
| Daily runbook, media stage | `hold_for_shot_plan` (PRODUCTION), `describe_serial_shots` | `backend/app/runbook/stages.py:3194`, `3225` |
| Film staircase walk | `quality_refused`, `director_ladder` (≤ `DIRECTOR_LADDER_ROUNDS` = 3 per walk) | `backend/app/runbook/stages.py:1625-1628`, `1676-1679` |
| Director's film-QC repair | `rewrite_for_redo` (with a still escalation when the motion words came back the same; `layer_exhausted` is not read) | `backend/app/runbook/stages.py:4791-4863` |
| Watchdog `ladder_retry` | `quality_refused` (re-queues a FILM_CONTINUE, at most `MAX_PER_DAY = 6` a day) | `backend/app/workflows/passes/ladder_retry.py:40`, `74`, `183`, `200` |
| Watchdog `replaced_boards` | `retire_replaced_boards` | `backend/app/workflows/passes/replaced_boards.py:21-23` |
| Sheet blocker repair | `repair_story`; `write_shot_prompts(repair_context=…)` | `backend/app/media/blocker_repair.py:799`, `882` |
| Shooting sheet | `lint_film`, `has_block`, `summary_ro`, `decision_outcome`, `refusal_view`, `blocked_words`, `shot_plan_gaps`, `motion_prompt_for` | `backend/app/media/shooting_sheet.py:140-144`, `519`, `771`, `1061`, `1425`, `1759` |
| Stills stage | `lint_film`, `has_block` before buying stills; lessons settled through `fix_check.settle_lessons` after a round | `backend/app/media/stills_stage.py:1942-1956`, `1105`, `1157` |
| Fix check | `confirm_prompt_lessons`, `withdraw_prompt_lessons` (`settle_lessons`, for the review runs its items came from); reads the rewrite review's findings from `media.prompts_rewritten` and `media.director_scene_brief`; its `PROCESS_NOTES` are read by `_is_finding` | `backend/app/media/fix_check.py:536-571`, `525-534`, `313-392`, `82-86` |
| Assembler | `motion_prompt_for` (`1264-1271`, `9200-9303`); `lint_film` for the hero/sheet view (`9349`); `strip_on_screen_text` for a degenerate-still retry (`2862-2867`, `3519-3539`); `_scene_prompt_rewrite` recompiles a factual scene for a paid redo with `compile_prompts` and a serial one with `serial_recomposition` (`13920-13975`); the scene-redo lint gate `lint_film` + `has_block` on the still prompt (`15982-15989`); clip QC settles a motion rewrite's lessons through `fix_check.clip_settled` (`10391`). `compose_serial_prompt` is named only in a comment there (`13904`) | `backend/app/media/assembler.py` |
| Director QC | `prompt_lessons` (no scope), `record_prompt_lesson` (default scope "all", not provisional; lessons from her film-QC verdicts) | `backend/app/media/director_qc.py:1611-1649` |
| Editorial review / reviews | `lesson_is_general` (`picture_lesson`), `record_prompt_lesson` (scope by film kind, provisional) | `backend/app/agents/editorial.py:58-64`, `403-417`, `579-590`; `backend/app/agents/reviews.py:618` (schema comment) |
| Serial episode writer | `prompt_lessons(scope=SCOPE_SERIAL)`, `lessons_rule`, `fit_with_lessons` | `backend/app/story/services.py:1530-1556` |
| Serial stage and story router | `storyboard_from_episode`, `describe_serial_shots` | `backend/app/story/serial_stage.py:285-295`; `backend/app/story/router.py:167`, `199` |
| Still gate | its `persists_reason` writes `refusal_kind`'s content phrase «nu arată ce cere scena» | `backend/app/media/still_gate.py:900-917`, `999-1001` |
| HTTP | `POST /storyboards/{id}/prompts` → `write_shot_prompts`; `GET /storyboards/{id}/production-package` → `production_package`; legacy render 409 → `hold_for_shot_plan` | `backend/app/media/router.py:1146-1175`, `143-178` |

Calls out of this group: `app.agents.services.run_agent_task`, `app.agents.structured.structured_run`,
`app.agents.memory` (`agent_for_role`, `remember`, `invalidate`), `app.agents.messages`
(`post_message`, `resolve_message`), `app.agents.editorial.is_serial_film`, `app.factual.story_review`
(`story_gate`, `latest_review`, `review_story`), `app.factual.agent_pipeline.agent_write_script`,
`app.factual.sanitizer.wrap_in_inert_boundary`, `app.media.shooting_sheet` (`film_is_closed`,
`current_lease`, `SHEET_STEPS`), `app.media.assembler` (`take_failure`, `clip_qc_of`,
`shot_plan_sources`, `SCENE_PROMPTS_REWRITTEN_EVENT`, `DIRECTOR_REWRITE`), `app.media.director_qc`
(Owner approvals and scene choices), `app.media.fix_check.PROCESS_NOTES`, `app.media.film_close`,
`app.media.services` (`generate_storyboard_from_script`),
`app.media.production_policy.classify_failure`, `app.runbook.stages` (`close_film_books`,
`film_spent_micros`, `_director_approves`, `STAGE_ACTIONS`, `paid_rule_words`), `app.services`
(`append_event`, policy readers), `app.story.*` (lines, locations, bibles).

Events emitted: `media.visual_bible_written`, `media.shot_prompts_written`,
`media.shot_prompts_incomplete`, `media.prompts_rewritten`, `media.director_scene_brief`,
`media.sheet_story_repair_progress`, `media.storyboard_created`, and (through `close_film_books`)
`runbook.film_retired`.

Events consumed: `media.director_scene_brief` (`earlier_briefs`, `open_layers`),
`media.sheet_story_repair_progress` (`progress`, `retire_replaced_boards`). `media.prompts_rewritten`
with `decided_by "director"` is consumed by `assembler.scene_memory` (`assembler.py:8785-8796`); the
rewrite review's findings in both events are read by `fix_check._rewrite_items`
(`fix_check.py:313-392`), and both events become the register's sentences
(`events_feed._brief_words`, `_rewrite_words`, `backend/app/events_feed.py:567-588`, `623-648`).

## Owner touchpoints

- **Series look file.** `config/serial_series_look.json`: the Owner changes the serial style block,
  palette, rules, shot sizes and cap by editing it, or switches it off with
  `use_until_the_owner_changes_it` (`series_look.py:89-152`). Version 2 is from the Owner's office
  picture, 2026-10-11 (`docs/project/16_DECISION_LOG.md:83`).
- **Factual look file.** `config/factual_look.json`, same switch (`series_look.py:271-313`, `492-494`).
- **«Închide filmul».** A closed film is not described again, not held and not rewritten
  (`prompt_agent.py:1135-1137`, `1255-1257`, `1440-1441`; `scene_rewrite.py:975`, `2292-2294`,
  `2778-2780`).
- **A still the Owner approved.** Never rewritten; only its motion may be (`scene_rewrite.py:723-740`,
  `939-940`, `2919-2921`, `3032-3035`).
- **The Owner's LOCAL_MOVE choice.** The ladder leaves that scene's motion alone
  (`scene_rewrite.py:743-748`, `2916-2918`); `rewrite_for_redo` does not check it.
- **«Directoarea acceptă defectele mici».** The Owner's sentence of 2026-10-12 is coded as the
  review's severity: a minor finding left untreated does not refuse a rewrite
  (`scene_rewrite.py:126-128`, `374-381`, `584-596`).
- **Approving a serial episode.** Makes `storyboard_from_episode` possible; an approval without the
  Director's reading is recorded as the Owner's (`serial_storyboard.py:103-153`, `163-166`).
- **The Owner's take decisions on the sheet.** `decision_outcome` tells the Owner, in Romanian,
  whether a continuation was queued and whether it will buy without asking, by reading the
  autonomy stop, safe mode, mode, paid-media rule (EVERY_PAID_STEP / OVER_USD), standing answers and
  the daily budget (`sheet_words.py:337-512`).
- **Refused takes and the assembly's wait.** `refusal_view` and `blocked_words` are the sheet's text
  for the Owner (`sheet_words.py:69-183`).
- **Environment.** Template prompts are a TEST convenience; in PRODUCTION a factual film without a
  model plan is held (`prompt_agent.py:1422-1431`; `runbook/stages.py:3182-3212`; serial films are
  not passed to the hold, `3191-3193`).
- **HTTP routes.** `POST /storyboards/{id}/prompts` (starts the model calls) and
  `GET /storyboards/{id}/production-package` (the audit bundle the Owner asked for)
  (`media/router.py:1146-1175`).
- **No cards or letters to the Owner originate here.** The letters in `scene_rewrite._letters` and
  `sheet_story_repair._handoff` are between agents. Money questions are asked by the staircase. The
  lessons, their scopes and their confirmation are kept without any Owner step.

## Oddities and gaps

1. `compose_prompt` (`prompt_agent.py:2071`) has no caller in `backend/app` (only tests). It writes
   `Camera:`, `Motion:` labels and an `Avoid:` list, which `prompt_lint` BLOCKs (TEMPLATE_LABEL,
   AVOID_LIST; `prompt_lint.py:176-184`, `719-745`). `MAX_PROMPT_CHARS` (`101`) is used only by it.
2. `MAX_BIBLE_CHARS = 2400` (`prompt_agent.py:102`) is not used anywhere.
3. `require_no_block` and `PromptLintBlocked` (`prompt_lint.py:1269-1272`, `477-482`) have no caller in
   `backend/app`. The docstring says it is "Called before any pricing or purchase"; the gates
   actually use `has_block` (`stills_stage.py:1949`, `assembler.py:15985`, `shooting_sheet.py:1759`).
4. `compile_film_prompts` (`prompt_agent.py:3014`) has no caller in `backend/app` (tests only);
   `_parse_shot_pack` (`prompt_agent.py:915`) has no caller at all.
5. Two lesson-overlap measures remain (the third, `scene_rewrite`'s own, was removed):
   `prompt_agent.lesson_overlap` divides by the new lesson's words, folds plurals, strips accents
   and leaves out filler and picture-lesson scaffold words (`prompt_agent.py:3103-3114`,
   `3152-3178`); `director_qc` has its own `_lesson_words` (`director_qc.py:1599-1606`, ratio at
   `1638`), with no plural folding, accents kept and no scaffold list, and it compares against
   `prompt_lessons(session, limit=…)` with no scope (`director_qc.py:1628`), whose unverified items
   end in " (unverified)" (`prompt_agent.py:3351`). Lesson length: her review is asked for 240
   characters (`scene_rewrite.py:131`, `602`), the schema takes 2000 (`354`), the store keeps up to
   400 (`prompt_agent.py:133`).
6. The review's `by` quote is required to be non-empty for a treated finding
   (`scene_rewrite.py:300-303`) but the code does not check that it appears in the rewritten
   prompts; only a locked finding's quote is checked against the kept words (`430-436`). Whether a
   finding is treated, and whether it is serious, decide the store and rest on the model's answer.
7. `write_shot_prompts` sets a NEEDS_SHOT_PLAN board back to APPROVED when no model answered at all
   (registry absent, run blocked, empty answer), because `lost` requires `answered`
   (`prompt_agent.py:1266`, `1346-1348`); the missing scenes get template packages. Purchase is still
   blocked in PRODUCTION by `hold_for_shot_plan` (`runbook/stages.py:3194`) and the stills step's
   refusal of template prompts (`stills_stage.py:1928-1941`).
8. The bible's provenance label is `"director"` (`prompt_agent.py:1080`) although the bible is
   written by the `VideoEditor` role (`prompt_agent.py:76`, `1036`).
9. `_is_serial` (`prompt_agent.py:435-440`) duplicates `agents.editorial.is_serial_film`
   (`agents/editorial.py:159-170`), with duplicated constants (`prompt_agent.py:81-84`); the comment
   says the duplication is to avoid an import cycle.
10. `scene_rewrite.DECIDED_BY = "director"` (`scene_rewrite.py:113`) duplicates
    `assembler.DIRECTOR_REWRITE = "director"` (`assembler.py:8472`); `_say_serial_words_again`
    (`2737`) and `recompose_serial_scene` (`2827`) use the assembler constant, `rewrite_scene` the
    local one (`2318`). The values agree today.
11. Serial cap: `compose_serial_prompt` falls back to 900 characters (`prompt_agent.py:1837`), the
    module default is 980 (`series_look.py:34`), the decision log for S8 says 900
    (`docs/project/16_DECISION_LOG.md:3970`), and the config (v2) says 980. `load_series_look` always
    sets `max_prompt_chars`, so the 900 fallback only applies to a look dict built elsewhere.
12. `_STYLE_OVERRIDE` removes clauses containing "hand-drawn", "2D" or "cartoon"
    (`prompt_agent.py:637-648`) from the model's serial fields, while the serial look in use (v2) is
    "Warm hand-drawn 2D animation" (`config/serial_series_look.json`). Model words that agree with the
    look are removed with the ones that contradict it; the look block itself passes only
    `strip_on_screen_text`, never `strip_style_overrides` (`series_look.py:124`).
13. The architecture spec says "strict parse, one repair, one re-ask"
    (`docs/architecture/08_VIDEO_PIPELINE.md:225-227`). The code adds a shot-by-shot salvage step
    (`prompt_agent.py:853-878`, `909-911`), and the serial path is never re-asked
    (`prompt_agent.py:1222-1224`).
14. `storyboard_from_episode` reaches `write_shot_prompts` statically, but passes `registry=None`
    (`serial_storyboard.py:362`), so it never calls a model; the static LLM distance (3) is not a
    runtime path. The model description comes from `describe_serial_shots`.
15. `repair_story` synthesizes `reading = {"verdict": "PASS"}` for a reused candidate whose story gate
    passed (`sheet_story_repair.py:238-239`) before `_director_approves`; its docstring states there
    is no attempt ceiling ("later scans continue without an attempt ceiling", `155`).
16. `_lint_blocks` compares BLOCK findings by their Romanian message (`scene_rewrite.py:1836`), not by
    code, and lints without a model id or contract (`1827-1835`), so model-specific motion rules
    (THEN_CHAIN as BLOCK on seedance, NEGATION_IN_PROMPT on veo) are not applied at rewrite time; the
    sheet lint applies them later. It also lints one scene (`lint.lint_scene`), not the film, so a
    film-level SAME_CAMERA_EVERY_SCENE BLOCK that a rewrite's camera move creates is not seen
    before the rewrite is stored.
17. The stills purchase and the scene-redo gate lint only the still prompt
    (`stills_stage.py:1942-1948`, `assembler.py:15982-15984`); motion prompts are linted, with the
    scene's model id, on the sheet (`shooting_sheet.py:1273-1281`, `1425`).
18. Factual prompts are compiled without a contract in `write_shot_prompts` (`prompt_agent.py:1300`),
    so the stored motion prompt is in the default model's dialect (`seedance2_5`, 1000 UTF-16);
    `motion_prompt_for` re-renders it for the model actually bought (`prompt_agent.py:3037-3051`;
    `assembler.py:1264`, `9200`).
19. A `StoryReview` with verdict PASS may mean the Owner approved a serial episode without the
    Director's reading (`serial_storyboard.py:138-153`); the truth is in `notes_json.source` and the
    empty reviewer. This is documented as intentional (S10) because PASS is the only verdict the gate
    and the table constraint accept.
20. All model behaviour in this group is proven on fakes in tests; the decision log notes the
    rewrite ladder was "Tested on fakes only" when introduced
    (`docs/project/16_DECISION_LOG.md:126-127`). The finding ids, severities, locks, scoped lessons
    and their confirmation were added in `68fa0b4`, `a50407e` and `5fc7468` with test changes only
    (`tests/test_rewrite_learns.py`, `tests/test_lessons_reach_prompts.py`,
    `tests/test_serial_ladder.py`, `tests/test_fix_is_verified.py`) and no new decision-log entry.
21. `scene_rewrite._fitted` (`1305-1329`) now keeps the lessons whole in front of every payload, but
    when the brief's or the rewrite's data is still over 14,000 characters after the old refusals
    and briefs are gone, the loop stops (`1328`) and the payload is sent over budget; the review's
    payload holds nothing `_fitted` may drop, so it is never shortened.
22. `motion_amplitude` / MEASURED (`prompt_agent.py:2287-2297`, `2785`, `2846`, `2853`) is read but
    never written by any code in `backend/app`; `ShotPrompt` and the rewrite schema have no such
    field (extra keys are ignored). The comment that «the Director's rewrite may set
    motion_amplitude» (`2289`) describes a roadmap item still marked "Next"
    (`docs/project/13_ROADMAP_TODO.md:1898-1899`). Only tests (`tests/test_motion_v2.py:358`) set it.
23. `render_motion` gives gen4 the veo closing without «No subtitles, no on-screen text.»
    (`prompt_agent.py:2823-2824`), while `lint_motion_prompt` expects that closing from every
    family but veo (`prompt_lint.py:1024`), so every compiled gen4 motion prompt carries a
    MOTION_CLOSING WARN.
24. `compile_prompts` passes `avoid=("slow orbit",)` to `choose_camera_move` for faceless people
    (`prompt_agent.py:2976-2978`), but no `SIZE_MOVES` list contains an orbit (`2272-2278`) and a
    plan's own move wins before `avoid` is read (`2671-2678`): the argument has no effect.
25. `compose_serial_prompt` opens the room with a «Location: …» label (`prompt_agent.py:1851`), a
    rubric of the kind the module avoids elsewhere; `TEMPLATE_LABEL` does not list «Location»
    (`prompt_lint.py:176-179`), so the lint does not see it. The rewrite counts it among the
    composer's fixed still sentences (`scene_rewrite.py:1134`).
26. `describe_serial_shots` (`serial_storyboard.py:375-410`) asks the model again on every media
    stage pass while, with a model registered, any package of the episode is not model-written or
    is from an older look version (`397-402`; the media stage calls it for the day's serial film,
    `runbook/stages.py:3224-3225`). Unlike the factual re-ask (`runbook/stages.py:1231-1251`: at
    most once a day on two days, never for a film holding a bought take), this group's code has no
    day count and no bought-take guard, and `write_shot_prompts` recomposes every scene's package
    from the new answer (a beat the model omits is recomposed from the look, even over an earlier
    model package: `lost` is never true for the serial, `prompt_agent.py:1266`, `1271`).
27. `rewrite_for_redo` returns `layer_exhausted` (through `_rung`, `scene_rewrite.py:3100`) and its
    docstring says the caller then turns to the picture (`3004-3006`), but its only caller,
    `runbook.stages._correct_before_redo`, escalates to a still rewrite only on `same_prompt`
    (`runbook/stages.py:4820`); a motion redo whose rewrite ended `layer_exhausted` is refused
    `PROMPT_NOT_CORRECTED` (`stages.py:4856-4865`). `rewrite_for_redo` forces the caller's layer
    (`3037`) and does not escalate itself, unlike `rewrite_failed_scene` (`2923-2941`).
28. With an Owner-approved still, `open_layers` returns motion only (`scene_rewrite.py:939-940`), so
    a motion rewrite that ends `layer_exhausted` is not escalated (`2930-2931`) and every later rung
    asks a new motion brief, rewrite and review (model tokens, no media), up to
    `DIRECTOR_LADDER_ROUNDS` per walk (`runbook/stages.py:1609`).
29. `prompt_agent.lesson_scope(session, storyboard_id)` (`prompt_agent.py:3192-3198`) has no caller
    in `backend/app`; `scene_rewrite` has its own `lesson_scope(context)` (`scene_rewrite.py:1079-1082`)
    and scope constants (`134`) duplicating `prompt_agent.SCOPE_SERIAL` / `SCOPE_FACTUAL`
    (`prompt_agent.py:146-147`). `_lesson_rows`' `live=False` branch (`3236-3249`) has no caller.
30. Lessons are verified for one writer only. The rewrite review's lessons are stored per kind of
    film and unverified with the review's run id (`scene_rewrite.py:1808-1814`), which `fix_check`
    collects from the review's findings to confirm or withdraw them (`fix_check.py:525-571`). The
    editorial review's picture lessons are stored unverified with the editorial run's id
    (`agents/editorial.py:584-590`), which no review finding carries, so nothing confirms or withdraws
    them; they stay unverified, given after every confirmed lesson, until a newer lesson
    supersedes them.
    `director_qc.learn_from_decision` stores with the default scope "all" and not provisional
    (`director_qc.py:1640`; `prompt_agent.py:3434-3435`), so a film-QC lesson reaches both kinds of
    film as a confirmed rule with no picture proving it.
31. `lesson_refusal` reads every storyboard title for each lesson (`prompt_agent.py:3420`), and
    `_title_named` refuses a lesson only for three consecutive title words with two of meaning
    (`3361-3373`): a one- or two-word title (its docstring names «Higgs») is never caught, where the
    review's removed check refused the film's whole title of four or more characters. A person's
    name is not checked by code; her instructions ask for none outside the serial's recurring
    characters (`scene_rewrite.py:602-604`).
32. `review_findings` keeps at most 8 findings (`MAX_QC_FINDINGS`, `scene_rewrite.py:194`, `1630`),
    so a refusal with more pieces has the rest neither reviewed nor checked on the bought picture.
    When none remain (only process notes), her review judges her own brief's diagnosis as finding 1
    (`findings_to_treat`, `1633-1647`).
