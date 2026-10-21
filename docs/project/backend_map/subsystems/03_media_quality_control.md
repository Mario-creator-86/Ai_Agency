# 03 — Quality control and judging of stills, clips and finished films

Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).

> Files:
> - `backend/app/media/qc.py` — 4204 lines (98 functions)
> - `backend/app/media/director_qc.py` — 2609 lines (63 functions)
> - `backend/app/media/picture_qc.py` — 2221 lines (44 functions)
> - `backend/app/media/still_gate.py` — 1213 lines (31 functions)
> - `backend/app/media/qc_report.py` — 640 lines (23 functions)
> - `backend/app/media/fix_check.py` — 793 lines (36 functions)
> - `backend/app/media/faces.py` — 178 lines (6 functions)
>
> 11 858 lines, 301 functions (counts from `../inventory.json`). Paths below are relative to the
> repository root; every `file:line` points into the code of commit `20abffd`
> (`git show 20abffd:<path>`). The first map was verified adversarially against the code; the
> refresh re-read every changed function. The Director's second look at a refused picture
> (`backend/app/media/second_look.py`, the 38th LLM call site) is mapped in
> `03b_media_second_look.md`; how this group hands refusals to it is described below
> ("The Director's second look: hand-off to 03b").

## In one paragraph

This group is the studio's set of eyes and rulers. It judges every picture at three moments:
**before motion is bought** (the stills gate: `still_gate.local_checks` measures structure,
panels, sharpness, motion blur, palette and faces at 0 credits, then
`picture_qc.judge_still` asks one vision model a fixed checklist, and `still_gate.decide`
folds both into PASSED/BLOCKED); **before a bought clip is cut into the film** (clip QC:
`qc.check_clip` measures motion against a locally calibrated floor, hard cuts, YuNet faces and
flat bands, and `picture_qc.judge_clip` looks at three frames; `qc.qc_clip_with_retry` buys at
most one retry inside the approved cap); and **on the finished film** (`qc.evaluate_media_qc`:
technical, rights, audio, audio mix, captions, editorial, motion/fallback, production path,
factual claims, content integrity, plus two vision looks — `picture_qc.evaluate_pictures`, one
frame per scene in one call, and `qc.span_picture_qc`, three frames per filmed scene, one call
each). The verdict is written as a `QualityControlReport` and the event `media.qc_evaluated`.
`qc_report` turns a report into the Owner's Romanian summary and per-scene, priced redo
proposals (never the whole film). When a film fails, `director_qc` is the Director's desk:
it numbers the findings, marks which are not hers to overrule, builds the context her LLM
reads, and then **carries out her decision under code rules** (`repair_list` filters her redos
against the Owner's final approvals and sheet choices; `accept_film` writes a PASSED report;
`close_film` retires the film; `record_look` approves a refused candidate she chose;
`learn_from_decision` stores her lessons for future prompts). `fix_check` names, per scene and
per layer (still or motion), what the scene's rewritten words were meant to fix, in quality
control's own words, so the next still and the next clip are each checked for exactly that
(each item answered gone, minor or persists: only persists refuses, a minor trace is a warning
on the take); it also settles the rewrite's provisional lessons from what the look saw, and
wraps the Director's second look (mapped in `03b_media_second_look.md`) that is asked before a
still re-roll or a clip retry is bought. `faces` is the deterministic YuNet face counter.
Almost all verdicts here are measured by code (ffmpeg, YuNet, thresholds); the vision model is
asked only the content questions a measurement cannot answer, through three call sites. The
vision model's "no" is acted on as given (it blocks, fails or routes); its "yes" never passes a
still or a clip on its own. Four places let another model, the Director's, override code: her
second look can keep a refused still and a refused clip before anything more is bought for them
(two places; `still_gate.may_be_overturned` and `qc.look_may_overturn` decide which refusals she
may see), her repair look can approve a candidate refused earlier (`record_look`), and her
ACCEPT can pass every measured failure except the "not hers" ones (`accept_film`). Her CLOSE is
refused by her own answer schema since 2026-10-11, so `close_film` runs only on the Owner's
«Închide filmul» card.

## Why it exists

The code's own docstrings name the incidents that built each part:

| When | Incident or Owner rule | What it produced | Source |
|---|---|---|---|
| 2026-09-26 | The Nepal film paid for twelve clips before anyone looked at a picture: three stills showed faces the bible forbade, one was a woman where a bar chart was asked, one a landscape where a black screen was asked; >1000 credits, QC failed | The stills gate (local checks + vision before motion), YuNet, the Owner's measured-spend report with per-scene redos (never the whole film) | `backend/app/media/still_gate.py:1-8`, `backend/app/media/faces.py:1-7`, `backend/app/media/qc_report.py:1-19` |
| 2026-09-26 | Second Nepal render bought whole on the legacy path from template prompts, sat unverified in the queue | `production_path_verdict` (STAIRCASE_CUTOVER) | `backend/app/media/qc.py:619-632`, `backend/app/media/qc.py:829-845` |
| September | "How ATLAS Caught the Higgs Boson" payoff was 11 s of beige stripes scored 1.0 by QC and approved | `still_is_degenerate` (SSIM after collapsing an axis, 0.94) | `backend/app/media/qc.py:301-307` |
| 2026-09-18 | No gate looked at a frame; `character_drift_qc` was NOT_IMPLEMENTED on every film | `picture_qc.evaluate_pictures` and the rule "a gate certifies only what it measured" | `backend/app/media/picture_qc.py:1-46`, `docs/architecture/50_CONTENT_GATE_MATRIX.md:42-80` |
| 2026-10-01 | CLIP_QC_WIRING, QC_SPANS: clip QC before assembly, film length = narration + breaths + silent cards + 1 s, the span look | `check_clip`, `qc_clip_with_retry`, `film_length_budget`, `span_picture_qc` | `docs/project/16_DECISION_LOG.md:4072`, `docs/project/16_DECISION_LOG.md:4078` |
| 2026-10-02 | Audit Q10: the zero-credit Nepal rehearsal had dead air, a 4.3 s black ending, cuts every 4.65 s, broken captions, and would have passed | `editorial_problems` (advisory unless the Owner makes it blocking) | `backend/app/media/qc.py:3799-3806` |
| 2026-10-02/03 | `edit_and_qc` failed "database is locked" four times | Measuring under a read session, verdict in a short write transaction | `backend/app/media/qc.py:977-981` |
| 2026-10-09 | Scene 5 of «The Particle That Shouldn't Exist (But Does)» came out as three stacked panels and passed every check | `flat_band` (panels), the `one_picture` question in all three looks, `back_to_still` in clip QC | `backend/app/media/qc.py:362-386`, `backend/app/media/still_gate.py:12-68`, `backend/app/media/picture_qc.py:1426-1428` |
| 2026-10-09 | First live RunPod round: the global sharpness floor rejected five good stills (sharp subject, soft background) | Tile-based `measure_focus` (floor 30, fine-detail ≤ 48 %) | `backend/app/media/still_gate.py:69-101`, `docs/project/16_DECISION_LOG.md:4251` |
| 2026-10-10 | Night-sky stills read as a pasted band and re-rolled (each paid) | `SOFT_EDGE_STEP` / soft-edged band waiver | `backend/app/media/qc.py:372-386`, `backend/app/media/qc.py:407-422` |
| 2026-10-10 | Film babcf272: the film-level look read the studio's own burnt-in subtitles as «text or a logo» in every scene; the mechanical repair retired takes the Owner approved | Clean shots / caption-row cutting / `StudioText` notes; the Director decides failed films (`director_qc`); nobody retires the Owner's approved takes | `backend/app/media/picture_qc.py:203-231`, `backend/app/media/director_qc.py:1-15` |
| 2026-10-10 20:06 | The Owner: the Director should decide whether a refused picture is good | `look_entries`, `record_look`, `look_letter` | `backend/app/media/director_qc.py:1828-1834` |
| 2026-10-11 | Owner's card: only takes he marked **final** are untouchable; «Mișcare v2»: ample motion, deformation takes one step back | `owner_approved_take_ids(final_only=)`, `calmer_motion_prompt` | `backend/app/media/director_qc.py:518-526`, `backend/app/media/qc.py:2444-2451` |
| 2026-10-12 | aa170155: scene 1 passed three film QCs with the same takes, failed the fourth; the Director's REPAIR bought a new still and clip. Owner: «Nu putem permite loopuri pe bani și picarea QC dacă deja a fost aprobată» | "Approved stays approved": `earlier_passes`, CARRIED_FORWARD | `backend/app/media/picture_qc.py:679-696` |
| 2026-10-12 | Five paid rounds of one scene: each still matched its prompt, none showed the scene | The `shows_scene` question in the stills gate | `backend/app/media/picture_qc.py:1429-1432`, `docs/project/16_DECISION_LOG.md:25` |
| 2026-10-12 16:50 | Owner: «să se asigure că ce a fost greșit este acum corectat» (f06808c9 scene 4) | `fix_check.open_findings`, `must_fix` items, violation `finding_persists` | `backend/app/media/fix_check.py:1-38`, `backend/app/media/still_gate.py:114-124` |
| 2026-10-12 | 19.50 USD of RunPod in a day, 11.05 on redos; Owner: «DIRECTOAREA ACCEPTĂ DEFECTELE MICI! … să se asigure că nu mai sunt» | Severity/cause/lesson on REAL/ACCEPTED verdicts, `learn_from_decision` | `backend/app/media/director_qc.py:54-61`, `backend/app/media/director_qc.py:1609-1620` |
| 2026-10-12, late evening | The review of 9ac0195: a still with Sarah's shoulder at the frame's edge, exactly as the correction asked, could be refused for «two women» (fixed true/false «even in part»); a finding treated in the motion's words was put to the still, which cannot show a movement, and never checked on the clip; a still repeating the mistake while showing its corrected words could be re-rolled twice more on the same words (up to four paid stills of one mistake) | Each `must_fix` item answered gone / minor / persists (`FixAnswer`), the correction's words as guidance; items split by layer (still → stills gate, motion → clip QC, unknown → both) in quality control's own words (`qc_text`); a persisting mistake on a picture that shows its plan ends in a rewrite of the words, not a re-roll (`next_step` action `rewrite`, clip `ESCALATE`); `settle_lessons` confirms or withdraws the rewrite's provisional lessons | `backend/app/media/still_gate.py:125-131`, `backend/app/media/picture_qc.py:1454-1467`, `backend/app/media/picture_qc.py:1898-1904`, `backend/app/media/fix_check.py:16-38`, `backend/app/media/fix_check.py:536-549` |
| 2026-10-12 | Owner: «trece imaginile picate de la QC pe la Directoare și să decidă dacă au picat corect sau nu și dacă trebuie refăcute»; «LLM-ul este pe abonament! NU COSTĂ BANI SĂ TRECEM PE LA EI! GENERAREA DE IMAGINI ȘI MIȘCĂRI COSTĂ!»; hard-coded rules stay only for the bible's hard limits | The Director's second look before a still re-roll or a clip retry is bought (`fix_check.director_second_look`, mapped in 03b); `still_gate.may_be_overturned`, `qc.look_may_overturn`, `fix_check.HARD_LIMITS`; ACCEPTED_BY_LOOK | `backend/app/media/fix_check.py:40-43`, `backend/app/media/fix_check.py:127-130`, `backend/app/media/still_gate.py:145-149`, `backend/app/media/qc.py:2646-2652` |

Specifications implemented: `docs/architecture/08_VIDEO_PIPELINE.md` §"Paid staircase" items 4-6
and 11 (stills gate, clip QC, QC and repair; `docs/architecture/08_VIDEO_PIPELINE.md:239-280`),
§"QC categories" (`docs/architecture/08_VIDEO_PIPELINE.md:98-118`), and
`docs/architecture/50_CONTENT_GATE_MATRIX.md` (gate statuses, "a gate certifies only what it
measured", picture and character gates; `docs/architecture/50_CONTENT_GATE_MATRIX.md:30-80`).

## Who decides here

Vocabulary: LLM, LLM_CHECKED_BY_CODE, CODE_RULE, OWNER, CONFIG, EXTERNAL (see the group
brief). "Model" means the vision employee chosen by `vision_agent` (Video Editor first).
"Environment" is the studio's TEST/PRODUCTION state, read by `services.studio_environment`
from the Owner's policy row (`OwnerPolicy.environment`, `backend/app/services.py:232-241`),
which only the Owner's command changes (`services.change_environment`,
`backend/app/services.py:244`, through `backend/app/main.py:884` or a decision card,
`backend/app/decisions/services.py:372-382`): rows that depend on it are labelled OWNER
(environment), not CONFIG.

### Stills gate (before motion is bought)

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| Still is "not a picture" (stripes, bands, blank field) | CODE_RULE | `backend/app/media/qc.py:310-359`, `backend/app/media/still_gate.py:648-663` | SSIM of the still vs itself collapsed to one row / one column ≥ 0.94 |
| Still is panels / has a pasted band | CODE_RULE | `backend/app/media/qc.py:549-616`, `backend/app/media/still_gate.py:664-700` | Flat full-width run ≥ 15 % of height at 270×480 (row std < 4, range < 24), unless glued to one edge with edge step < 3 and ≤ 50 % of height |
| Still is blurred / an upscale | CODE_RULE | `backend/app/media/still_gate.py:701-742` | Trimmed Laplacian median of the sharpest 1/10 tiles < 30, or fine detail kept after halve-and-restore > 48 % |
| Baked motion blur | CODE_RULE | `backend/app/media/still_gate.py:743-767` | Gradient anisotropy ≥ 2.5: FAILED on a static move, WARNING otherwise |
| Palette drift | CODE_RULE (warning only) | `backend/app/media/still_gate.py:768-792` | Mean CIELAB ΔE to named look colours > 30 → WARNING, never blocks |
| Faces where the bible forbids them | CODE_RULE + LLM (either blocks) | `backend/app/media/still_gate.py:603-626`, `backend/app/media/still_gate.py:1007-1013` | YuNet count > 0 (score ≥ 0.6) **or** model `faces_visible` true |
| A check that could not run | CODE_RULE + OWNER (environment) | `backend/app/media/still_gate.py:592-600`, `backend/app/media/still_gate.py:956-963` | NOT_RUN blocks in PRODUCTION, warns in TEST; required set = degenerate, panels, sharpness, motion_blur (+ faces when forbidden); a YuNet NOT_RUN on a bible that allows faces never blocks (`backend/app/media/still_gate.py:613-614`) |
| Nobody looked (vision unavailable / unusable) | CODE_RULE | `backend/app/media/still_gate.py:965-984` | Blocks in every environment ("nu a fost privită"). In production the model is not even asked when a local check already blocks (`backend/app/media/stills_stage.py:931-940`). For a still with `must_fix` items a second reason is added in the gate's content phrase («… se socotește că nu arată ce cere scena după rescriere»), with no violation code |
| Content answers backed by a measurement (faces, one picture, technical) | LLM_CHECKED_BY_CODE | `backend/app/media/still_gate.py:1007-1024`, `backend/app/media/still_gate.py:1038-1040` | The model's "no" blocks as given; its "yes" is not enough, because YuNet (faces), the flat band and SSIM (panels, stripes) and the sharpness/blur readings run independently and each can block |
| Content answers no code checks (readable text, matches plan, shows scene, look, bible) | LLM | `backend/app/media/still_gate.py:1014-1043` | A single false answer or a named bible violation blocks; a true answer is taken as given (only its shape is validated: `StrictBool`, required fields). A `buy_motion` summary cannot pass a still whose own answers contradict it (a consistency rule, not a content check) |
| The rewrite's mistake is still visible | LLM | `backend/app/media/still_gate.py:989-1006`, `backend/app/media/still_gate.py:855-898`, `backend/app/media/picture_qc.py:1454-1501`, `backend/app/media/picture_qc.py:1586-1602` | Every `must_fix` item must be answered gone, minor or persists (the schema refuses omissions and a minor/persists answer without `seen`; a legacy `fixed` true/false reads as gone/persists). Two answers for one item read as the worse. persists → violation `finding_persists` (blocks, `persists_reason`); minor → a warning only (`minor_warning`), kept on the report's `minor`; gone is taken as given. An unanswered item (possible only for a verdict built in code) adds "vision" to `unmeasured` |
| A persisting mistake: re-roll or rewrite | CODE_RULE (on the model's persists and matches_plan answers) | `backend/app/media/still_gate.py:1160-1183`, `backend/app/media/still_gate.py:342-344` | `finding_persists` and (the model said `matches_plan` true, or `rerolls_done` ≥ `PERSISTS_REROLLS` = 1) → action `rewrite`: nothing more is bought on these words, the scene ends as a content refusal for the Director's ladder (the stills step returns NEEDS_OWNER with `rewrite` true, `backend/app/media/stills_stage.py:1173-1181`). A persisting mistake on a still that also missed its plan gets at most one re-roll |
| Which refused candidate decides a round | CODE_RULE | `backend/app/media/still_gate.py:1198-1213` | The first that repeats a mistake while matching its plan, else the first with a violation code, else the first; `next_step` of it |
| The model's own verdict (buy_motion / regenerate_still / compose_locally) | LLM | `backend/app/media/still_gate.py:1044-1045` | Any verdict other than buy_motion blocks the still by itself, even with every answer positive; it adds no violation code |
| Outcome buy_motion / regenerate_still / compose_locally | CODE_RULE (compose_locally: LLM) | `backend/app/media/still_gate.py:1047-1053` | Not blocked → buy_motion; blocked and model said compose_locally → compose_locally (whatever else blocked it); else regenerate_still |
| Which passing candidate is kept | CODE_RULE | `backend/app/media/still_gate.py:828-840`, `backend/app/media/still_gate.py:1109-1115` | Fewest minor traces first (the model's minor answers), then score 0.5·sharpness term (log scale, 0 at the floor, 1 at 100× it) + 0.3·(1 − min(ΔE/60, 1)) palette (0.15 unmeasured) + 0.2·model `look_ok`; tie → sha256 |
| Re-roll (a new paid still) or stop | CODE_RULE | `backend/app/media/still_gate.py:1139-1195` | Re-roll only when the report carries a violation code and is not a `rewrite` (above), at most `MAX_REROLLS` = 2; no violation code (only "could not measure", or only the model's non-buy_motion verdict) → needs_owner, never re-rolled. Before a re-roll, a rewrite or a needs_owner is acted on, the stills step asks the Director's second look (next rows) |
| Which refused stills the Director may look at again | CODE_RULE | `backend/app/media/still_gate.py:1118-1130`, `backend/app/media/fix_check.py:127-130` | BLOCKED, at least one violation code, nothing unmeasured, no violation in `HARD_LIMITS` (faces, readable_text, panels, degenerate), outcome not compose_locally. Offered fewest violations first, one look per candidate, the first she lets stand wins (`backend/app/media/stills_stage.py:1038-1077`, called at `backend/app/media/stills_stage.py:1143-1149`) |
| Her second look keeps a refused still | LLM (her verdict, call site in 03b) executed by CODE_RULE | `backend/app/media/fix_check.py:693-703`, `backend/app/media/stills_stage.py:1017-1035` | `look_accepts`: OVERTURNED with severity none or minor, or CONFIRMED with severity minor and `redo` false → the candidate is set APPROVED, `approved_by` `director_look`, its failure cleared; no re-roll is bought. A CONFIRMED look lets the step go on, her reason added to the outcome. UNAVAILABLE leaves the refusal as it was |
| Words of the re-roll | CODE_RULE | `backend/app/media/still_gate.py:249-263`, `backend/app/media/still_gate.py:1133-1136` | Fixed positive phrases per violation code (`POSITIVE_WORDS`); the `scene` code (shows_scene false) has no phrase, so it adds no words |
| Which findings a still or a clip must be checked against | CODE_RULE (over texts written by LLMs elsewhere) | `backend/app/media/fix_check.py:313-497` | Per layer: her review's findings on the newest rewrite by her brief (the newest that changed the picture for the still layer, the newest of any layer for the motion layer), in quality control's `qc_text`, each on its own `layer` (older records: where its treating sentence stands, else both); the newest Director QC decision's REAL verdicts on the scene; the brief's film reasons only for a rewrite whose review kept no findings, only sentences that say what was seen (`observed`). An item is closed on the still layer by an APPROVED still created after it, on the motion layer by a clip after it that he approved or that clip QC passed; duplicates (≥ 0.6 word overlap) kept once; ranked review → Director QC → film, own-layer first; ≤ 4 items, ≤ 300 chars |
| The rewrite's provisional lessons confirmed or withdrawn | CODE_RULE (on the model's fix answers) | `backend/app/media/fix_check.py:536-571` | Approved take with every item gone → `prompt_agent.confirm_prompt_lessons`; refused because an item persists (still: the round ends in anything but a re-roll, `backend/app/media/stills_stage.py:1150-1159`; clip: not kept, `backend/app/media/fix_check.py:786-793`) → `withdraw_prompt_lessons` |

### Clip QC (before assembly)

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| Clip moves enough | CODE_RULE | `backend/app/media/qc.py:1816-1882` | Mean **and** median YDIF at 540 px ≥ ½ of a local fixture (3 % push-in or 5 % pan over 5 s built from the clip's own first frame); static and rack focus have no floor |
| Camera move has a floor at all | CODE_RULE | `backend/app/media/qc.py:1519-1538`, `backend/app/media/qc.py:1796-1804` | `MOVE_FIXTURE`; an unrecognised or ambiguous move → NOT_RUN, which blocks in PRODUCTION and is downgraded to a WARNING in TEST by `check_clip` (`backend/app/media/qc.py:2309-2314`) |
| Hard cut inside the clip | CODE_RULE | `backend/app/media/qc.py:1885-1894` | Frame YDIF > max(12, 8 × clip median) |
| Faces in first/middle/last frame | CODE_RULE | `backend/app/media/qc.py:2078-2117` | YuNet > 0 when the bible forbids faces |
| Panels in a frame | CODE_RULE | `backend/app/media/qc.py:2120-2177` | Flat band ≥ 15 % beside ≥ 10 % picture rows (`splits_the_picture`) |
| Content judgement (three frames) | LLM_CHECKED_BY_CODE (faces, one picture, technical: YuNet, flat band, motion floor and cut spikes also run) / LLM (text, plan, look, same shot, bible, verdict: no code check) | `backend/app/media/qc.py:2009-2075` | Any false flag, named bible violation or non-`keep` verdict fails, as given; a `keep` contradicted by its own answers fails. `faces_visible` counts only when the bible forbids faces |
| The movement's rewritten mistake is still visible | LLM | `backend/app/media/assembler.py:10288-10294`, `backend/app/media/qc.py:2281-2286`, `backend/app/media/qc.py:2031-2045`, `backend/app/media/qc.py:2303-2308` | Only a bought clip whose scene has motion-layer items (`fix_check.open_findings(layer="motion")`) is asked them. persists fails the picture check, its words first among the reasons; minor is a warning on the clip; gone is taken as given; an unanswered item makes the picture check NOT_RUN (blocks everywhere). The answers are kept on `ClipReport.fixes` and `measured["picture"]["fixes"]` |
| Unmeasured local check | CODE_RULE + OWNER (environment) | `backend/app/media/qc.py:2309-2316` | NOT_RUN of motion, cuts, faces or panels → WARNING in TEST, blocking in PRODUCTION; the vision check's NOT_RUN blocks everywhere. A clip whose only blocks are unmeasured is kept PAID as UNCHECKED by the caller and waits for the Owner's look (`backend/app/media/assembler.py:5111-5133`, `backend/app/media/assembler.py:10447-10454`) |
| Fault is in the still (no new seed) | CODE_RULE + LLM (either suffices) | `backend/app/media/qc.py:2180-2195`, `backend/app/media/qc.py:2327-2332` | The first frame split by a flat band (code), or, taken as given, the model's `one_picture` false or `back_to_still` verdict. When a motion-layer item persists, the model's `back_to_still` verdict is not read: only the flat band or `one_picture` false send the clip back to its still (the fault is the movement's words). The caller then refuses the still and the scene needs a new paid still (`backend/app/media/assembler.py:10427-10439`) |
| A persisting mistake on a clip that shows its plan | CODE_RULE (on the model's persists and matches_plan answers) | `backend/app/media/qc.py:2515-2529`, `backend/app/media/qc.py:1968-1978` | ESCALATE with no retry («Directoarea rescrie mișcarea»): a seed + 1 on the same words would buy the same mistake |
| Retry with seed + 1 (paid) | CODE_RULE | `backend/app/media/qc.py:2485-2564` | Not passed, not back_to_still, not a persisting mistake on a clip that shows its plan, retries < 1, not "all blocks unmeasured", committed + price ≤ approved cap, and her second look did not keep the clip (below). A vision NOT_RUN beside a measured local failure still buys the retry |
| Which refused clips the Director may look at again | CODE_RULE | `backend/app/media/qc.py:2588-2606`, `backend/app/media/qc.py:2616-2623` | Not passed, nothing unmeasured, not back_to_still, at least one FAILED blocking check, no FAILED `faces` or `panels` check, the model did not see writing or more than one picture, and no model-seen face where faces are forbidden. So a measured motion-floor failure, a hard cut, a deformation, a plan/look/same-shot refusal, a named bible violation and a persisting mistake can be looked at again. She is asked before the retry or escalation (`backend/app/media/qc.py:2670`) and, after a failed retry, on the clip bought last (`backend/app/media/qc.py:2734-2752`) |
| Her second look keeps a refused clip | LLM (her verdict, call site in 03b) executed by CODE_RULE | `backend/app/media/qc.py:2671-2683`, `backend/app/media/qc.py:2738-2751`, `backend/app/media/assembler.py:10361-10373` | `fix_check.look_accepts` → `ACCEPTED_BY_LOOK`: the clip is kept, nothing more is bought; the assembler records it PASSED with `accepted_by` `director_look` and her look beside clip QC's blocks. A CONFIRMED look adds her reason to the retry's or the escalation's reason (`_her_words`, `backend/app/media/qc.py:2609-2613`) |
| Retry prompt firmer vs calmer | LLM_CHECKED_BY_CODE (the model's flags, overridden by a measured motion-floor failure) | `backend/app/media/qc.py:2361-2379`, `backend/app/media/qc.py:2468-2475` | Calmer when the motion check did not FAIL and (YuNet face, or model `faces_visible` true even where faces are allowed, or `technical_ok` / `same_shot` / `look_ok` false); else firmer |
| Still shown as a still in a PRODUCTION film | OWNER | `backend/app/media/qc.py:2802-2833`, `backend/app/media/qc.py:2869-2882` | Allowed only for scenes the Owner set to LOCAL_MOVE on the sheet |
| Assembly stops before a PRODUCTION film with unchosen stills | CODE_RULE + OWNER | `backend/app/media/qc.py:2895-2917` | Raises `FallbackNotChosen` |

### Finished-film QC (`evaluate_media_qc`)

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| File valid, 9:16, Shorts length, provenance, declared = measured | CODE_RULE (+ CONFIG/OWNER for max length) | `backend/app/media/qc.py:987-1053` | ffprobe; aspect within 0.01 of 9/16; 10 s ≤ duration ≤ channel max + 1 s; sha256 equals `provenance_hash` |
| Channel's maximum Short length | OWNER (setting) / CONFIG | `backend/app/media/qc.py:899-921` | `ChannelRecord.shorts_max_seconds`, else 60 s factual / 70 s serial, clamped 10-180 |
| Delivery format | CODE_RULE | `backend/app/media/qc.py:2923-2975` | 1080×1920, H.264 High, yuv420p, tv range, bt709 tags, fps = timeline fps; fails in every environment |
| Delivery floors (bitrate, length, duplicates) | CODE_RULE + OWNER (environment) | `backend/app/media/qc.py:2977-3014` | < 6 Mbps or unmeasured bitrate fails (< 8 only warns, in both environments); length > narration + breaths + silent cards + 1 s, or narration length not recorded; a silent card over its maximum; duplicates ≥ 2 %; these fail in PRODUCTION, warn in TEST |
| Licence status allows upload / public | CODE_RULE on recorded evidence | `backend/app/media/qc.py:708-739` | Known status passes; only LICENSED/PUBLIC_DOMAIN/legacy stamps may be public; NEEDS_REVIEW private only |
| Music/ambience licensed and bed level | CODE_RULE + OWNER (his library) | `backend/app/media/qc.py:746-826`, `backend/app/media/music_library.py:36-58` | Every track is an entry of the library the studio reads (`STUDIO_MUSIC_LIBRARY`, else the Owner's git-ignored `config/music/music_library.json`, else the shipped empty `config/music_library.json`) with the same sha256; bed 18-22 LU under the voice (± 0.5), read in speech when measured there, else over the film; an unmeasured bed level fails |
| Loudness | CODE_RULE | `backend/app/media/qc.py:1185-1231` | Integrated −15..−13 LUFS, true peak ≤ −1 dBTP, measured on the delivered file; no loudnorm filter or no audio stream fails |
| Captions | CODE_RULE | `backend/app/media/qc.py:1233-1289` | SRT parses; ≤ 2 lines × 42 chars; no overlap; ends ≤ 0.5 s after the film; `difflib` ratio of the narration's and the captions' word sequences ≥ 0.95 |
| Editorial problems refuse the film | OWNER (setting, via decision card) / CONFIG | `backend/app/media/qc.py:4198-4204`, `backend/app/media/qc.py:4182-4187`, `backend/app/decisions/seed.py:528-565` | `settings.editorial_qc_blocking` (`STUDIO_EDITORIAL_QC_BLOCKING`, which the Owner's «Controlul editorial» card tells him to set), else `config/factual_look.json` `finish.editorial_qc_blocking` (false): advisory, `passed` True with status ADVISORY |
| Stills in a PRODUCTION film | OWNER | `backend/app/media/qc.py:2836-2892` | No LIVE scene without motion unless his LOCAL_MOVE; in TEST the ceiling (setting, else half) only warns |
| Template prompts / legacy whole-film purchase | CODE_RULE | `backend/app/media/qc.py:829-885` | Renders started ≥ 2026-09-26: PRODUCTION LIVE scenes need a model-written shot plan source; no paid vendor bought inside the render |
| Factual claims | CODE_RULE on data | `backend/app/media/qc.py:1342-1371` | Every referenced claim row exists and is SUPPORTED |
| Placeholder visuals | CODE_RULE | `backend/app/media/qc.py:1075-1092` | `provider_name` starting with PLACEHOLDER fails |
| Picture/one-picture/shows-the-scene per scene (one frame) | LLM | `backend/app/media/picture_qc.py:1202-1246` | A MEASURED false answer fails the film in every environment. The check passes when at least one scene was answered and none failed: scenes the model left out, or past the 8-frame cap, are NOT_APPLICABLE and do not stop the pass (`backend/app/media/picture_qc.py:1206-1219`, `backend/app/media/picture_qc.py:1247-1265`) |
| Character matches the bible | LLM (stated cast only) | `backend/app/media/picture_qc.py:1280-1371` | A stated character with `matches` false fails; guessed names are OBSERVED, never counted; a pair with no answer is NOT_APPLICABLE |
| Scene look on three frames per filmed scene | LLM_CHECKED_BY_CODE | `backend/app/media/qc.py:3669-3733` | A model refusal fails the scene as given; YuNet face and flat band fail it on their own; faces NOT_RUN fails in PRODUCTION. A scene passes only when the look, the flat band and (where faces are forbidden) YuNet all passed; the check passes only when every filmed scene passed (`backend/app/media/qc.py:3737-3741`) |
| A scene passed earlier with the same takes is not judged again | CODE_RULE (Owner rule 2026-10-12) | `backend/app/media/picture_qc.py:784-843`, `backend/app/media/picture_qc.py:994-997`, `backend/app/media/qc.py:3499`, `backend/app/media/qc.py:3596-3606` | Same storyboard, same (still take, clip take), newest earlier report whose check passed the scene |
| A look that could not run | CODE_RULE (spec 50) | `backend/app/media/qc.py:1416-1421` | `passed` None adds no failure: the verdict is what the other gates left |
| Overall PASSED/FAILED and score | CODE_RULE | `backend/app/media/qc.py:1405-1424` | AND of all gates; score 1.0 if passed else 1 − 0.25 × failures (floor 0) |

### The Director's desk (`director_qc`) — executing her LLM decision

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| Which findings are not hers to overrule | CODE_RULE | `backend/app/media/director_qc.py:147-205`, `backend/app/media/director_qc.py:377-423` | rights_qc, factual_qc, content_source_qc, production_path_qc; file faults; music-licence lines |
| ACCEPT refused when a not-hers finding exists | CODE_RULE (in the caller) | `backend/app/runbook/stages.py:4467-4477` (uses the `not_yours` flags built here and joined by `annotate_verdicts`) | ACCEPT_REFUSED. Her schema makes her judge every finding (`backend/app/agents/reviews.py:872-876`), so any not-hers finding refuses her ACCEPT |
| Her ACCEPT becomes a PASSED report | LLM_CHECKED_BY_CODE | `backend/app/media/director_qc.py:1678-1735` | Schema refuses ACCEPT with a REAL finding (`backend/app/agents/reviews.py:676-678`); a REAL picture finding, or a paid redo, on a scene that passed before with the same takes is refused too (`passed_scene_refusal`, `backend/app/agents/reviews.py:781-847`, applied at `backend/app/agents/reviews.py:880-883`), which steers such findings to FALSE or ACCEPTED; the caller refuses not-hers findings. Every other measured failure (delivery format, loudness, captions, bed level, motion/fallback, picture and character looks, editorial) can be accepted away by her verdicts. Score = max(0.90, 0.90, measured), capped at 1.0 |
| A film is CLOSEd after a failed QC | OWNER | `backend/app/media/director_qc.py:1738-1825`, `backend/app/decisions/producers/redo_cap.py:340-372` | Her answer schema refuses CLOSE («a film is not closed for its quality», `backend/app/agents/reviews.py:865-871`, the Owner's rule of 2026-10-11), so `close_film` is reached only by the Owner's «Închide filmul» card on the paid-redo cap. It runs under the film's purchase lease (600 s); a purchase in flight refuses (`FilmBusy`); paid approvals are withdrawn. The stages branch for her CLOSE (`backend/app/runbook/stages.py:4480-4482`) remains but cannot be reached by a validated answer |
| Which of her redos are carried out | LLM_CHECKED_BY_CODE + OWNER | `backend/app/media/director_qc.py:1427-1596` | Skips OWNER_APPROVED (his final takes), OWNER_CHOICE (motion on LOCAL_MOVE), FREE_FIX_USED, NOT_A_CARD, UNKNOWN, STILL_SKIPPED; a still/motion redo of a card scene becomes its card; still → motion follows (or REJOIN for LOCAL_MOVE); already-bought pairs never rebought. Her schema has already refused a REPAIR none of whose redos can run now (`backend/app/agents/reviews.py:711-772`, `backend/app/agents/reviews.py:884-888`) |
| Takes the Owner approved as final | OWNER | `backend/app/media/director_qc.py:518-559`, `backend/app/media/director_qc.py:577-619` | His newest `media.scene_take_decided` with `final` true; a REJECTED look removes it |
| State of a pending REPAIR (final/pending/ready/look/lapsed) | CODE_RULE + OWNER (answers) | `backend/app/media/director_qc.py:1234-1410` | ASKED: no question ids → ready; his approval APPROVED-unconsumed → ready; PENDING unexpired → waiting; else lapsed. BOUGHT_WAITING: approved new take → ready (a REJOIN entry only within 3 days); SUBMITTED/PAID candidate → waiting; refused candidate on disk, unseen by her, not looked at by him and < 3 days → look; else lapsed (look outranks waiting) |
| Which refused candidates she is shown | CODE_RULE | `backend/app/media/director_qc.py:1910-2045` | ≤ 6 newest; file sha256 still the bought one; not degenerate; shot eligible by `clip_choice`; not looked at by the Owner |
| Her chosen candidate is approved | LLM_CHECKED_BY_CODE | `backend/app/media/director_qc.py:2069-2161` | Candidate number in range (schema `look_schema`, and again `backend/app/media/director_qc.py:2096-2100`); `_choice_refused`: Owner has not looked, still REJECTED, film not closed, sha256 unchanged; `approved_by` "director". Her choice overrides the code gate's own refusal (flat band, sharpness, motion blur, YuNet faces, motion floor): only a degenerate picture and an ineligible shot are kept from her |
| Her lesson becomes a prompt rule | LLM | `backend/app/media/director_qc.py:1609-1643` | Only her fresh decision (`decided_by` Director, not `resumed`) teaches; a lesson is skipped when ≥ 60 % of its words are in one of the newest 40 lessons. Otherwise the model's text is stored as written, as a rule for the prompt writers |
| She could not decide | CODE_RULE | `backend/app/media/director_qc.py:2188-2254` | WAITING_EVENT, one open inbox note per report; nothing redone |

### Reporting (`qc_report`)

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| What counts as spent | CODE_RULE | `backend/app/media/qc_report.py:153-180` | Only balance before/after deltas that agree with `spent`; unmeasured reads "necunoscut", never 0 |
| What redo each failed scene gets | CODE_RULE | `backend/app/media/qc_report.py:515-563` | Card kind → free card; picture failure → still + motion; motion-only → motion; audio/encode free; never the whole film |
| Scene kind when unrecorded | CODE_RULE | `backend/app/media/qc_report.py:55-69`, `backend/app/media/qc_report.py:208-232` | Sheet kind, else recorded kind, else regex on the evidence |

## LLM involvement

All three call sites in this group call `app.agents.structured.structured_run`
(`backend/app/agents/structured.py:76-166`), which calls `run_agent_task` up to **twice**. The
second attempt happens only when the first run SUCCEEDED with text that did not validate: with
native thinking when no object could be read, or with the schema's refusal quoted when an
object was refused (`backend/app/agents/structured.py:109-164`). A run that failed or was
refused (budget, token ceiling, provider error) or returned empty text is not retried
(`backend/app/agents/structured.py:138-140`). Each run goes through the policy kernel, the
daily token ceiling and the USD budget inside `run_agent_task`. The speaker is chosen by
`app.agents.vision.vision_agent(session, *LOOKERS)` (`backend/app/agents/vision.py:116-142`):
among ACTIVE employees whose primary model declares the VISION capability (ordered by hire
date), the first of the roles `VideoEditor`, `Director`, `QualityAssurance`
(`backend/app/media/picture_qc.py:116-119`) that has one (within a role the latest hired,
because the role map keeps the last row, `backend/app/agents/vision.py:136`), else the
earliest-hired seeing employee (`backend/app/agents/vision.py:141`). The run uses that
employee's own model. Every prompt wraps the data in `wrap_in_inert_boundary` (untrusted text
marked as data).

### Call site 1 — `app.media.picture_qc.evaluate_pictures` (`backend/app/media/picture_qc.py:904`)

- **Speaker**: the vision employee (Video Editor first). Task type `picture_qc`
  (`backend/app/media/picture_qc.py:110`), template `picture-qc-v4`
  (`backend/app/media/picture_qc.py:114`), `max_tokens` 4000, temperature 0.1
  (`backend/app/media/picture_qc.py:1162-1178`).
- **When**: on every finished-film QC (`evaluate_media_qc`, `backend/app/media/qc.py:962`),
  before the report's write transaction. Skipped entirely when every scene is carried forward
  from an earlier passing report with the same takes (`backend/app/media/picture_qc.py:994-997`).
- **What it asks** (`_INSTRUCTIONS`, `backend/app/media/picture_qc.py:159-185`): for one middle
  frame per scene (≤ 8 frames, 480 px; `FRAME_WIDTH`/`MAX_FRAMES` in
  `backend/app/agents/editorial.py:78-79`) — is it a picture at all, is it ONE picture, does it
  show what the scene asked for (its submitted still/motion prompts, ending frame, narration).
  For each scene-and-character pair: does the person match the Character Bible's canonical
  description (and stored portrait, up to 4 references of ≤ 4 MB, only for characters the
  film states; `backend/app/media/picture_qc.py:1030-1038`). It is told where the frames were
  cut from (shot vs film) and that the subtitles are the studio's (`studio_text_note`,
  `backend/app/media/picture_qc.py:308-323`). The data JSON is cut at 14 000 characters
  (`backend/app/media/picture_qc.py:1158`).
- **Answer shape**: `PictureReport` (`backend/app/media/picture_qc.py:153-156`):
  `scenes[]: ScenePictureVerdict{scene:int, is_a_picture:bool, one_picture:bool,
  shows_the_scene:bool, reason≤300}` (≤ 16) and `characters[]: CharacterVerdict{scene,
  character, matches:bool, reason}` (≤ 48). Every boolean is required (no default reads as a
  pass).
- **Use of the answer — trust: FINAL** (for the QC record; a later Director decision may
  overrule it). The code does not verify the content; it maps answers to failures:
  `is_a_picture` false → "not a picture"; else `one_picture` false → "not one picture"; else
  `shows_the_scene` false → "not what the scene asked for" (`backend/app/media/picture_qc.py:1231-1246`).
  A stated character with `matches` false fails the film
  (`backend/app/media/picture_qc.py:1318-1333`); a **guessed** name (spelled in prose, not
  cast) is recorded OBSERVED and never counted (`backend/app/media/picture_qc.py:1300-1317`).
  Scenes the model leaves out are NOT_APPLICABLE; scenes past the frame cap are "no frame was
  cut". The check's `passed` is True as soon as one scene was answered and none failed, so a
  partial answer passes it (`backend/app/media/picture_qc.py:1264-1265`); duplicate entries for
  one scene are not refused, the last one wins (`backend/app/media/picture_qc.py:1204`). The
  failures fail the film in every environment
  (`backend/app/media/qc.py:1379-1381`, `backend/app/media/qc.py:1419-1420`).
- **If the model fails/refuses/returns junk**: `parsed is None` (including a run refused under
  the token ceiling or budget, which is not retried) or no scenes → both checks
  NOT_APPLICABLE with `passed` None and the reason; no failure is added, so the film's verdict
  is what the other gates left it (`backend/app/media/picture_qc.py:1181-1200`). The same when
  no registry, no seeing employee, or no frame could be cut (`backend/app/media/picture_qc.py:998-1008`, `backend/app/media/picture_qc.py:1075-1079`).
- **Can lead to spending money**: yes, indirectly. A FAILED report goes to the Director
  (`app.runbook.stages.director_decides_failed_film`), whose REPAIR buys paid still/motion
  redos; `qc_report.redo_proposals` reads a failed scene as "picture to redo" (still + motion).
  The call itself spends LLM tokens under `run_agent_task`'s budget.

### Call site 2 — `app.media.picture_qc.judge_still` (`backend/app/media/picture_qc.py:1765`)

- **Speaker**: the vision employee. Task type `still_qc` (`backend/app/media/picture_qc.py:1400`),
  template `still-qc-v3`, or `still-qc-v3-fixes2` when the plan carries `must_fix` items
  (`backend/app/media/picture_qc.py:1407-1414`); `max_tokens` 800 + 150 per item,
  temperature 0.1 (`backend/app/media/picture_qc.py:1829-1851`).
- **When**: for every candidate still the stills step bought, after the local checks — in
  production through `stills_stage._judge_candidate`, which skips the call when a local check
  already blocks (`backend/app/media/stills_stage.py:912-941`); the assembler's paid still redo
  uses the same `_judge_candidate` (`backend/app/media/assembler.py:16546-16557`); in
  `still_gate.check_still` the call is unconditional (`backend/app/media/still_gate.py:1102`).
- **What it asks** (`_STILL_INSTRUCTIONS`, `backend/app/media/picture_qc.py:1644-1679`): one
  still at 1080 px, judged as ONE moment (the first frame of the shot): `faces_visible`,
  `readable_text`, `one_picture`, `matches_plan`, `shows_scene` (the scriptwriter's line and
  the narration, not the compiled prompt), `look_ok`, `technical_ok`, `bible_violations`, and a
  `verdict` among buy_motion / regenerate_still / compose_locally. With `must_fix` items of the
  still layer (`fix_check.open_findings`, shown as `finding`, `expected` and `cause` by
  `fix_items`, `backend/app/media/picture_qc.py:1605-1620`), `_FIXES_NOTE` asks per item one
  status — gone, minor (a small trace a viewer would hardly notice) or persists — tells the
  model that `expected` is guidance (a picture showing what it describes has the mistake gone)
  and that an item about the movement, the ending or the cut is gone on a still because the clip
  is checked for it (`backend/app/media/picture_qc.py:1681-1706`). Data JSON cut at 8000
  characters, `must_fix` placed before the rules so it survives the cut
  (`backend/app/media/picture_qc.py:1809-1824`).
- **Answer shape**: `StillJudgeReport{stills: [StillVerdict]}` (≤ 4), built by
  `still_report_schema(asked)` (`backend/app/media/picture_qc.py:1586-1602`); a report object
  without its `stills` list is refused (`_report_named`, `backend/app/media/picture_qc.py:1444-1451`,
  `backend/app/media/picture_qc.py:1567-1570`). `StillVerdict`
  (`backend/app/media/picture_qc.py:1508-1539`): `scene: StrictInt`, `faces_visible`,
  `readable_text`, `matches_plan`, `look_ok`, `technical_ok`, `one_picture`, `shows_scene`:
  `StrictBool` (the last two required of a model by `_every_entry_answers`,
  `backend/app/media/picture_qc.py:1435-1441`), `bible_violations` (1-300), `verdict:
  Literal[...]`, `reason` (1-300), `fixes: [FixAnswer{item:StrictInt≥1, finding, status:
  gone|minor|persists, seen}]` (`backend/app/media/picture_qc.py:1454-1501`; `seen` required
  unless gone; a legacy `fixed` bool reads as gone/persists; `StillFix` is kept as an alias,
  `backend/app/media/picture_qc.py:1505`). When items were asked, every item number must be
  answered or the report is refused and asked again (`_every_fix_answered`,
  `backend/app/media/picture_qc.py:1542-1556`).
- **Use of the answer — trust: CHECKED_BY_CODE**. `judge_still` keeps only an answer with
  exactly one entry for the plan's scene (`backend/app/media/picture_qc.py:1861-1870`) and
  replaces each fix's `finding` with the studio's own words (`_studio_words`,
  `backend/app/media/picture_qc.py:1622-1629`, `backend/app/media/picture_qc.py:1872-1874`).
  `still_gate.decide` then reads every answer strictly: any negative answer, a named bible
  violation, a non-buy_motion verdict, or any item that persists blocks the still; a minor item
  is only a warning; a `buy_motion` summary whose answers contradict it does not pass
  (`backend/app/media/still_gate.py:985-1045`). The local checks run independently and can
  refuse a still the model passed. The model's yes can therefore only pass a still that every
  local check also passed; but its yes on readable text, plan, scene, look, bible and its gone
  or minor on each `must_fix` item is not verified by any code, and its no is acted on as given
  (a block, and for a violation code a paid re-roll). Routes that follow the model's answers
  unchecked: its `compose_locally` verdict alone blocks the still and routes it to the
  COMPOSE_LOCALLY hold (`backend/app/media/still_gate.py:1044-1051`); its `regenerate_still`
  verdict with every answer positive blocks it with no violation code, so `next_step` answers
  needs_owner, not a re-roll (`backend/app/media/still_gate.py:1152-1159`); its persists together
  with its `matches_plan` true (or a second persisting round) ends the scene's words in a
  rewrite with no re-roll (`backend/app/media/still_gate.py:1160-1183`); its minor answers rank
  the passing candidates (`backend/app/media/still_gate.py:1109-1115`). A refusal that is not a
  hard limit may then be looked at again by the Director before anything is bought (see "The
  Director's second look: hand-off to 03b").
- **If the model fails**: NOT_RUN «nu a fost privită» (`backend/app/media/picture_qc.py:1854-1870`)
  → `decide` adds "vision" to `unmeasured` and blocks in every environment
  (`backend/app/media/still_gate.py:965-984`); with no measured violation `next_step` returns
  needs_owner (no re-roll: "another still would be judged by the same missing eye",
  `backend/app/media/still_gate.py:1152-1159`), and the Director's second look is not offered
  (something is unmeasured, `backend/app/media/still_gate.py:1127`). When a local check measured a
  violation, the re-roll is still bought (`backend/app/media/still_gate.py:1184-1189`).
- **Can lead to spending money**: yes. PASSED → the motion purchase (`media.motion_purchase`,
  up to 68 credits/s per the docstring, `backend/app/media/still_gate.py:6-7`); BLOCKED with
  measured violations → a paid re-roll, up to `MAX_REROLLS` = 2
  (`backend/app/media/still_gate.py:1184-1189`), unless the Director's second look keeps a
  candidate; a persisting mistake on a still that shows its plan stops the purchases on those
  words.

### Call site 3 — `app.media.picture_qc.judge_clip` (`backend/app/media/picture_qc.py:2074`)

- **Speaker**: the vision employee. Task type `clip_qc` (`backend/app/media/picture_qc.py:1892`),
  template `clip-qc-v4` (`backend/app/media/picture_qc.py:1897`), or `clip-qc-v4-fixes` when a
  bought clip's plan carries motion-layer `must_fix` items
  (`backend/app/media/picture_qc.py:1898-1904`); `max_tokens` 800 + 150 per item, temperature 0.1
  (`backend/app/media/picture_qc.py:2158-2187`).
- **When**: (a) for every bought clip before assembly — the `judge` callback bound in
  `assembler` (`backend/app/media/assembler.py:10296-10307`) and called by `qc.check_clip`
  (`backend/app/media/qc.py:2280`); the plan carries the scene's motion-layer items
  (`backend/app/media/assembler.py:10288-10294`); (b) for every filmed, non-carried scene of a
  finished film in `qc.span_picture_qc` (`backend/app/media/qc.py:3506-3520`,
  `backend/app/media/qc.py:3674-3684`), one call per scene, with a `StudioText` describing the
  frame source; a film scene is never asked `must_fix` items
  (`backend/app/media/picture_qc.py:2141`).
- **What it asks** (`_CLIP_INSTRUCTIONS`, `backend/app/media/picture_qc.py:1994-2025`): three
  frames (first, middle, last) at 1080 px plus, for FILM_CROPPED frames, the three strips below
  the caption rows: `faces_visible`, `readable_text`, `matches_plan`, `look_ok`,
  `technical_ok`, `same_shot`, `one_picture`, `bible_violations`, `verdict` among keep /
  regenerate_motion / back_to_still. Subtitle words over the scene travel inside the inert
  boundary (`backend/app/media/picture_qc.py:2135-2138`). With motion-layer items,
  `_CLIP_FIXES_NOTE` asks per item gone, minor or persists, and the scene's written picture and
  narration are added to the data (`backend/app/media/picture_qc.py:2034-2052`,
  `backend/app/media/picture_qc.py:2139-2154`); data JSON cut at 8000 characters
  (`backend/app/media/picture_qc.py:2153`).
- **Answer shape**: `ClipJudgeReport{clips: [ClipVerdict]}` (≤ 4;
  `backend/app/media/picture_qc.py:1911-1961`), all StrictBool / Literal, `one_picture`
  required of a model, a report object without `clips` refused (`_names_its_clips`,
  `backend/app/media/picture_qc.py:1945-1948`); `fixes: [FixAnswer]` read only when items were
  asked, and then every item must be answered (`clip_report_schema`,
  `backend/app/media/picture_qc.py:1964-1978`).
- **Use of the answer — trust: CHECKED_BY_CODE**. `qc._picture_check` fails the clip on any
  false flag, a forbidden face, a named bible violation, a non-keep verdict or a persisting
  item, and a keep contradicted by its own answers fails (`backend/app/media/qc.py:2009-2075`).
  Motion floor, cut spikes, YuNet faces and the flat band are measured independently and each
  can block (`backend/app/media/qc.py:2238-2334`). A refusal on text, plan, look, same shot, a
  named violation, a non-keep verdict or a persisting item is acted on as given; no code checks
  it. The model's answers additionally steer routes, unchecked: `one_picture` false or
  `back_to_still` → BACK_TO_STILL, no motion bought again on that still, and the scene needs a
  new paid still (`backend/app/media/qc.py:2180-2195`, `backend/app/media/qc.py:2499-2514`,
  `backend/app/media/assembler.py:10425-10439`), except that a persisting item makes the
  `back_to_still` verdict unread; a persisting item with `matches_plan` true escalates with no
  retry (`backend/app/media/qc.py:2515-2529`); its faces/technical/same_shot/look flags choose
  the calmer retry prompt unless the motion floor failed (`backend/app/media/qc.py:2361-2379`);
  its readable_text, one_picture and faces_visible flags decide whether the Director may look
  at the refusal again (`backend/app/media/qc.py:2599-2606`). In the span look the same
  reading fails a film scene (`backend/app/media/qc.py:3705-3721`).
- **If the model fails**: NOT_RUN «clipul nu a fost privit» (`backend/app/media/picture_qc.py:2190-2208`;
  also wrong frame count, strip count, no registry, no seeing employee, frames not
  preparable: `backend/app/media/picture_qc.py:2102-2123`). In clip QC this blocks in every
  environment. When every block is unmeasured the clip is escalated without a retry
  (`backend/app/media/qc.py:2537-2545`) and the caller keeps it PAID as UNCHECKED, waiting for
  the Owner's look on the sheet (`backend/app/media/assembler.py:5111-5133`,
  `backend/app/media/assembler.py:10447-10454`); when a local check also measured a failure,
  the one paid retry is still bought. In the span look the scene is NOT_RUN with `passed`
  None and adds no failure unless something else failed (`backend/app/media/qc.py:3722-3733`).
- **Can lead to spending money**: yes. A failed clip buys one retry (seed + 1) when the cap
  allows (`backend/app/media/qc.py:2546-2564`, `backend/app/media/qc.py:2696-2697`), unless the
  Director's second look keeps it or a persisting mistake on a clip that shows its plan sends
  the movement's words to her rewrite; a BACK_TO_STILL sends the scene back for a new paid
  still; a passed clip is assembled. A failed film scene leads to the Director's paid redos.

### Functions that reach the LLM indirectly

| Function | Through | Notes |
|---|---|---|
| `app.media.qc.evaluate_media_qc` (`backend/app/media/qc.py:924`) | `picture_qc.evaluate_pictures` (one call) and `qc.span_picture_qc` → `picture_qc.judge_clip` (one call per filmed scene not carried) | Both run before the write transaction (`backend/app/media/qc.py:956-975`). Up to 1 + N scene calls, each up to 2 attempts |
| `app.media.qc.span_picture_qc` (`backend/app/media/qc.py:3413`) | `picture_qc.judge_clip` | Default judge bound only when a registry is given (`backend/app/media/qc.py:3506-3520`) |
| `app.media.still_gate.check_still` (`backend/app/media/still_gate.py:1075`) | `picture_qc.judge_still` | Not used by production code (see Oddities) |
| `app.media.qc.check_clip` / `qc_clip_with_retry` | `judge` callback (normally `judge_clip`, bound in `backend/app/media/assembler.py:10296-10307`); `qc_clip_with_retry` also the `look` callback (normally `fix_check.shot_second_look`, bound in `backend/app/media/assembler.py:10334-10346`) | Invisible to static analysis (callbacks). Per bought clip: up to 2 judge calls and up to 2 second looks |
| `app.media.fix_check.director_second_look` (`backend/app/media/fix_check.py:642`) | `second_look.second_look` → `second_look._look` (the 38th call site, mapped in `03b_media_second_look.md`) | Inventory distance 4. Called by `stills_stage._director_looks` (`backend/app/media/stills_stage.py:1056-1066`) and by `shot_second_look` |
| `app.media.fix_check.shot_second_look` (`backend/app/media/fix_check.py:713`) | `director_second_look` (kind `shot`) | Inventory distance 5. Cuts the clip's three frames with `qc.clip_frames` into a temporary folder removed after the look |

### LLM decisions executed here but asked elsewhere

`director_qc` contains no model call; it builds the input for, and executes the output of, two
Director call sites in `backend/app/agents/reviews.py` (group documented elsewhere). `fix_check`
and `qc` execute the output of a third, her second look (`second_look._look`, mapped in
`03b_media_second_look.md`; last row):

| Asked in | Answer schema | Executed here by | Trust here |
|---|---|---|---|
| `reviews.review_film_qc` (`backend/app/agents/reviews.py:981`), input `director_qc.film_qc_context` | `DirectorQcDecision{verdicts[FindingVerdict{finding, verdict REAL/FALSE/OWNER_CHOICE/ACCEPTED, reason, severity, cause, lesson}], decision ACCEPT/REPAIR/CLOSE, repairs[DirectorRedo], summary}` (`backend/app/agents/reviews.py:605-708`), bound per report by `decision_schema` (`backend/app/agents/reviews.py:848-890`: every finding judged, CLOSE refused, passed scenes protected, a REPAIR must have a runnable redo) | `accept_film`, `repair_list`, `record_decision`, `learn_from_decision`, `annotate_verdicts`, `director_letter` (`close_film` only on the Owner's card) | CHECKED_BY_CODE (repairs filtered; ACCEPT refused on not-hers findings in the caller; CLOSE refused by the schema). Her FALSE/ACCEPTED verdicts on the other findings and her lessons are taken as given |
| `reviews.review_bought_pictures` (`backend/app/agents/reviews.py:1148`), input `director_qc.look_entries` | `DirectorLook{decision CHOOSE/REJECT, candidate, reason}` bound by `look_schema(count)` (`backend/app/agents/reviews.py:1091-1127`) | `record_look`, `look_letter` | CHECKED_BY_CODE (`_choice_refused`) |
| `second_look.second_look` (`backend/app/media/second_look.py:583`), through `fix_check.director_second_look`, input the refused picture and QC's reasons | `SecondLook` (verdict CONFIRMED/OVERTURNED, severity none/minor/serious, redo, reason; `backend/app/media/second_look.py:88-135`), normalised by `director_second_look` (unknown verdict → UNAVAILABLE, unknown severity → serious, `reason_ro` ≤ 500 chars; `backend/app/media/fix_check.py:681-690`) | `look_accepts` (`backend/app/media/fix_check.py:693-703`), `qc.qc_clip_with_retry` (ACCEPTED_BY_LOOK), `stills_stage._approve_by_look`, `record_take_note`, `look_record` | FINAL within the refusals code lets her see (`may_be_overturned`, `look_may_overturn`): a look that lets the take stand stops the purchase; it never adds one |

### The Director's second look: hand-off to 03b

The look itself — `backend/app/media/second_look.py`, its prompt, its answer schema, its event
`media.director_second_look` and her memory — is mapped in
`docs/project/backend_map/subsystems/03b_media_second_look.md`. This group decides which
refusals reach it, shows it the refusal in quality control's own words, and carries out the
answer. Nothing here buys anything for a look; a look can only stop a purchase.

| Step | Stills (stills gate) | Clips (clip QC) |
|---|---|---|
| When she is asked | After a round in which the gate passed no candidate and the next step (`still_gate.round_step`, `backend/app/media/still_gate.py:1198-1213`) is a re-roll, a rewrite or needs_owner (not compose_locally): `stills_stage._settle_round` → `_director_looks` (`backend/app/media/stills_stage.py:1143-1149`, `backend/app/media/stills_stage.py:1038-1077`); the same in the assembler's paid still redo (`backend/app/media/assembler.py:16571-16579`) | Inside `qc.qc_clip_with_retry`: after the first check when it neither passed nor went BACK_TO_STILL, before the retry or the escalation (`backend/app/media/qc.py:2670`); and after a failed retry, before the escalation, unless BACK_TO_STILL (`backend/app/media/qc.py:2734-2752`) |
| Which refusals (CODE_RULE) | `still_gate.may_be_overturned` (`backend/app/media/still_gate.py:1118-1130`): BLOCKED, a violation code, nothing unmeasured, no `fix_check.HARD_LIMITS` violation (faces, readable_text, panels, degenerate; `backend/app/media/fix_check.py:130`), not compose_locally. Offered fewest violations first, one look per candidate | `qc.look_may_overturn` (`backend/app/media/qc.py:2588-2606`): not passed, nothing unmeasured, not back_to_still, a FAILED blocking check, none of them `faces` or `panels`, the model saw no writing and not more than one picture, and no model-seen face where faces are forbidden |
| What is handed over | `fix_check.director_second_look(kind="still", images=[the still], refusal=report.reasons_ro, take_ids=[take])` (`backend/app/media/stills_stage.py:1056-1066`) | `fix_check.shot_second_look(clip=report.path, refusal=report.blocks_ro, take_ids=[the take checked last])`, bound as the `look` callback by `assembler._check_shot` (`backend/app/media/assembler.py:10334-10346`); it cuts the clip's first, middle and last frames with `qc.clip_frames` into a temporary folder and calls `director_second_look(kind="shot")` (`backend/app/media/fix_check.py:713-754`) |
| Her answer, normalised | `director_second_look` (`backend/app/media/fix_check.py:642-690`): always a dict `{verdict, severity, redo, reason_ro, run_id}`; no registry, no images, the module missing or any exception → UNAVAILABLE with `redo` true (the refusal stands) | same |
| When it stops the purchase | `fix_check.look_accepts` (`backend/app/media/fix_check.py:693-703`): OVERTURNED with severity none/minor, or CONFIRMED + minor + `redo` false. The candidate is set APPROVED, `approved_by` `director_look`, failure cleared, generation-job quality synced (`stills_stage._approve_by_look`, `backend/app/media/stills_stage.py:1017-1035`); no re-roll | same rule → `ACCEPTED_BY_LOOK` (`backend/app/media/qc.py:2671-2683`, `backend/app/media/qc.py:2738-2751`): the clip is kept, the assembler records it PASSED with `accepted_by` `director_look` (`backend/app/media/assembler.py:10361-10373`); no retry |
| What is written | `fix_check.record_take_note` (`media.take_quality_note`: her look and the minor traces; `backend/app/media/fix_check.py:574-615`), via `stills_stage._after_approval` (`backend/app/media/stills_stage.py:1080-1107`), which also confirms the rewrite's lessons when every item was gone | `fix_check.clip_settled` (`backend/app/media/fix_check.py:757-793`, called at `backend/app/media/assembler.py:10389-10401`): the take note, and the lessons confirmed or withdrawn |
| A confirmation | Her reasons go into the round's outcome («Directoarea a privit și confirmă refuzul», `backend/app/media/stills_stage.py:1160-1183`); the re-roll, rewrite or needs_owner goes on | Her reason is appended to the retry's or the escalation's reason (`_her_words`, `backend/app/media/qc.py:2609-2613`); the retry is bought as before |

The finished film is not handed to her second look here: `evaluate_media_qc` and
`span_picture_qc` never call it, and the `film_scene` kind of `second_look` is used only by the
offline audit `scripts/qc_audit.py` (03b). A failed film still goes to her QC decision
(`director_qc`, above).

### How much is LLM and how much is rule

- 3 of 301 functions (1.0 %) are LLM call sites; they hold 752 of the group's 11 858 lines
  (`evaluate_pictures` 486, `judge_still` 118, `judge_clip` 148). 5 more functions have a
  static path to a model (`evaluate_media_qc`, `span_picture_qc` and `check_still` within 3
  hops; `fix_check.director_second_look` at 4 and `fix_check.shot_second_look` at 5, both to
  the second look of 03b), and `check_clip` / `qc_clip_with_retry` reach one through callbacks.
- The model answers only content questions no measurement can: does the picture show the
  scene, is it one photograph (backed by the flat band), is there a face (backed by YuNet), is
  there writing, does it keep the look, is the person the bible's character, is the mistake of
  a rewrite gone, minor or there again. Every structure, sharpness, motion, cut, loudness,
  caption, format, licence, length, money and retry-count decision is deterministic code with
  fixed, measured thresholds; five routes follow the vision model's own answers without a
  check: BACK_TO_STILL (its `one_picture` false or `back_to_still`), COMPOSE_LOCALLY (its
  `compose_locally`), the calmer or firmer wording of the one clip retry (its flags), the
  rewrite instead of a re-roll or retry (its persists with its `matches_plan` true), and which
  refusals the Director may look at again (its readable_text, one_picture and face answers).
- Asymmetry: before money is spent the model's silence blocks (stills, clips); on the
  finished film the model's silence certifies nothing and changes nothing (spec 50). A
  model's "no" fails a still, a clip or a film as given, and can lead to spending (a re-roll, a
  new still after BACK_TO_STILL, the Director's repairs); its "yes" never passes anything alone in
  the stills gate or clip QC. On the finished film the one-frame look's "yes" on some scenes
  passes `picture_qc` even when it left other scenes unanswered.
- After a film fails, the Director's LLM decides ACCEPT / REPAIR and per-finding verdicts (CLOSE
  is refused by her schema), and the code here decides what of it may be carried out. Two of her
  answers override deterministic code: her ACCEPT can pass every measured failure except the
  not-hers ones (rights, claims, placeholder, production path, four file faults, music-licence
  lines), and her look can approve a candidate the stills gate or clip QC refused on a
  measurement (flat band, sharpness, motion blur, YuNet faces, motion floor), except a degenerate
  picture or an ineligible shot.
- Before money is spent again, her second look (03b) can keep a still the stills gate refused on
  the model's readings (plan, scene, look, technique, a named bible violation, a persisting
  mistake) and a clip clip QC refused on a reading or a measurement (motion floor, hard cut),
  but never a face where faces are forbidden, writing or panels (nor, for a still, a blank
  picture), and never a refusal with anything unmeasured. Her verdict can only stop a purchase.

## Hard rules and limits

### Picture structure (shared by still, clip and film)

| Constant | Value | Where | Meaning |
|---|---|---|---|
| `DEGENERATE_SSIM` | 0.94 | `backend/app/media/qc.py:307` | SSIM after collapsing an axis at/above which a still is stripes/bands/blank |
| `PANEL_READ_SIZE` | 270×480 | `backend/app/media/qc.py:389` | Grey, area-scaled read size for the flat band |
| `FLAT_ROW_STD` / `FLAT_ROW_RANGE` | 4.0 / 24 | `backend/app/media/qc.py:392-393` | A row is flat |
| `PANEL_BAND_SHARE` | 0.15 | `backend/app/media/qc.py:395` | Band share that splits the picture |
| `FRAME_PICTURE_FLOOR` | 0.10 | `backend/app/media/qc.py:406` | Clip/film frames: minimum non-flat share for a band to count (captions/fades waiver); not applied to stills |
| `SOFT_EDGE_ROWS` / `SOFT_EDGE_STEP` | 4 / 3.0 | `backend/app/media/qc.py:411`, `backend/app/media/qc.py:418` | Soft-edged sky/background test |
| `SOFT_BAND_MAX_SHARE` | 0.5 | `backend/app/media/qc.py:422` | Widest band a soft edge excuses |

### Stills gate

| Constant | Value | Where |
|---|---|---|
| `MEASURE_WIDTH` | 1080 | `backend/app/media/still_gate.py:171` |
| `SHARPNESS_FLOOR` | 30 (trimmed Laplacian variance, median of sharpest 1/10 of 8×14 tiles) | `backend/app/media/still_gate.py:174-182` |
| `TRIM_SHARE` | 0.05 | `backend/app/media/still_gate.py:182` |
| `FINE_DETAIL_KEPT_MAX` | 0.48 | `backend/app/media/still_gate.py:186` |
| `SHARPNESS_SCORE_SPAN` | 100 (log scale) | `backend/app/media/still_gate.py:189` |
| `MOTION_BLUR_ANISOTROPY` | 2.5 | `backend/app/media/still_gate.py:192` |
| `PALETTE_WARN_DELTA_E` | 30.0 (warning only) | `backend/app/media/still_gate.py:194` |
| `MAX_REROLLS` | 2 paid re-rolls, then needs_owner | `backend/app/media/still_gate.py:196` |
| `PERSISTS_REROLLS` | 1: a still repeating a corrected mistake while missing its plan is re-rolled at most once; one that shows its plan never is (action `rewrite`) | `backend/app/media/still_gate.py:197-199`, `backend/app/media/still_gate.py:1160-1162` |
| `STATIC_MOVES` | static, locked, locked camera, locked-off | `backend/app/media/still_gate.py:204` |
| Required checks | degenerate, panels, sharpness, motion_blur (+ faces if forbidden) | `backend/app/media/still_gate.py:803-805` |
| Score weights | 0.5 sharpness, 0.3 palette (0.15 unmeasured), 0.2 look_ok; ranked after the count of minor traces | `backend/app/media/still_gate.py:828-840`, `backend/app/media/still_gate.py:1115` |
| `_STATUS_RANK` | gone 0 < minor 1 < persists 2 (two answers for one item read as the worse) | `backend/app/media/still_gate.py:851-852` |
| `STILL_WIDTH` / `MAX_STILL_BYTES` | 1080 px / 40 MB | `backend/app/media/picture_qc.py:1420-1422` |
| `STILL_FIX_TEMPLATE_VERSION` / `FixStatus` | `still-qc-v3-fixes2` / gone, minor, persists | `backend/app/media/picture_qc.py:1414`, `backend/app/media/picture_qc.py:1418` |
| `MAX_FIXES` (schema) / `fix_check.MAX_ITEMS` | 8 / 4 items, 300 chars each | `backend/app/media/picture_qc.py:1416`, `backend/app/media/fix_check.py:61-62` |

### Fix check and the Director's second look (`fix_check`)

| Constant | Value | Where |
|---|---|---|
| `MAX_ITEMS` / `MAX_CHARS` | 4 items per picture or clip, 300 characters each | `backend/app/media/fix_check.py:61-62` |
| Layers | `still`, `motion`, `both` (`PICTURE_LAYER` = still, kept for old callers) | `backend/app/media/fix_check.py:65-69` |
| `FIX_STATUSES` | gone, minor, persists | `backend/app/media/fix_check.py:72-73` |
| Source order | review → director_qc → film | `backend/app/media/fix_check.py:75`, `backend/app/media/fix_check.py:438` |
| `DUPLICATE_OVERLAP` | 0.6 share of content words (words of ≥ 3 letters outside `_FILLER`) | `backend/app/media/fix_check.py:78`, `backend/app/media/fix_check.py:102-110` |
| `PROCESS_NOTES` | three studio notes dropped as findings | `backend/app/media/fix_check.py:82-86` |
| `PROPOSAL_SENTENCE` | a film reason's sentence naming a purchase, a redo, a rewrite, credits, a prompt or a new/approved still is dropped | `backend/app/media/fix_check.py:93-99` |
| `_MOTION_WORDS` | words that rank an item last on the still layer (and first on the motion layer) | `backend/app/media/fix_check.py:114-118` |
| Treating sentence found in a prompt | word for word, at least 4 words | `backend/app/media/fix_check.py:219-226` |
| `DIRECTOR_QC_EVENT` | `media.director_qc_decision` (read for her REAL verdicts) | `backend/app/media/fix_check.py:120` |
| `TAKE_NOTE_EVENT` | `media.take_quality_note` | `backend/app/media/fix_check.py:124` |
| `DIRECTOR_LOOK_APPROVER` | `director_look` | `backend/app/media/fix_check.py:126` |
| `HARD_LIMITS` | faces, readable_text, panels, degenerate: never offered to her second look | `backend/app/media/fix_check.py:127-130` |
| Her verdicts / severities | CONFIRMED, OVERTURNED, UNAVAILABLE / none, minor, serious (anything else → serious); `reason_ro` ≤ 500 chars | `backend/app/media/fix_check.py:132`, `backend/app/media/fix_check.py:684-689` |
| A look that lets a take stand | OVERTURNED + none/minor, or CONFIRMED + minor + `redo` false | `backend/app/media/fix_check.py:693-703` |

### Faces (YuNet)

| Constant | Value | Where |
|---|---|---|
| Model | `backend/app/media/models/yunet_2023mar.onnx`, sha256 `8f2383e4…52fa4` pinned | `backend/app/media/faces.py:37-38` |
| `SCORE_THRESHOLD` | 0.6 (YuNet demo uses 0.9; tuned toward false alarms) | `backend/app/media/faces.py:47` |
| `NMS_THRESHOLD` / `TOP_K` | 0.3 / 5000 | `backend/app/media/faces.py:48-49` |
| `MAX_DETECT_WIDTH` | 1080 | `backend/app/media/faces.py:54` |

### Clip QC

| Constant | Value | Where |
|---|---|---|
| `CLIP_METRIC_WIDTH` | 540 px | `backend/app/media/qc.py:1503` |
| Fixtures | 5 s; push-in 3 %; pan 5 % of width | `backend/app/media/qc.py:1505-1507` |
| `FLOOR_SHARE` | 0.5 of the fixture's mean YDIF (mean and median must both reach it) | `backend/app/media/qc.py:1509`, `backend/app/media/qc.py:1863` |
| `MOVE_FIXTURE` | 18 moves → push_in / pan / none (static, rack focus) | `backend/app/media/qc.py:1519-1538` |
| `CUT_SPIKE_RATIO` / `CUT_SPIKE_MIN_YDIF` | 8× median / 12 | `backend/app/media/qc.py:1543-1544` |
| `MAX_CLIP_RETRIES` | 1 (seed + 1, same model, inside the cap) | `backend/app/media/qc.py:1546` |
| `CLIP_FRAMES` | 3 (first, middle, last) at 1080 px | `backend/app/media/picture_qc.py:1906` |
| `CLIP_FIX_TEMPLATE_VERSION` | `clip-qc-v4-fixes` (a bought clip with motion-layer items); `max_tokens` 800 + 150 per item | `backend/app/media/picture_qc.py:1904`, `backend/app/media/picture_qc.py:2184` |
| `ACCEPTED_BY_LOOK` | outcome status of a refused clip her second look kept | `backend/app/media/qc.py:2585` |

### Finished film

| Constant | Value | Where |
|---|---|---|
| `SHORTS_MIN_SECONDS` / slack / limit | 10 s / +1 s / 180 s | `backend/app/media/qc.py:889-894` |
| `SHORTS_MAX_BY_CHANNEL_TYPE` | MAIN_FACTUAL 60 s, OFFICE_SERIAL 70 s | `backend/app/media/qc.py:896` |
| Delivery spec | 1080×1920, H.264 High, yuv420p, tv, bt709 | `backend/app/media/qc.py:1561-1565` |
| `DEFAULT_TIMELINE_FPS` | 30 | `backend/app/media/qc.py:1568` |
| Bitrate | < 6 Mbps fails in PRODUCTION (warns in TEST); < 8 Mbps warns | `backend/app/media/qc.py:1571-1572` |
| Length allowance | narration + breaths (recorded, else 0.35 s/speaking scene) + silent cards + 1.0 s | `backend/app/media/qc.py:1575-1584`, `backend/app/media/qc.py:3194-3264` |
| `MAX_SILENT_CARD_SECONDS` | BLACK 2.0, TITLE_CARD 2.5, DATA_CARD 4.0 s | `backend/app/media/qc.py:1597` |
| Duplicates | < 0.05 YDIF (film) / < 0.03 (shots) is a repeat; ≥ 2 % fails; 0.5 s span edges ignored | `backend/app/media/qc.py:1550-1558`, `backend/app/media/qc.py:1600-1602` |
| Loudness | −14 ± 1 LUFS; true peak ≤ −1.0 dBTP | `backend/app/media/qc.py:1604`, `backend/app/media/toolchain.py:129`, `backend/app/media/toolchain.py:145` |
| Bed under voice | 18-22 LU (± 0.5) | `backend/app/media/toolchain.py:591`, `backend/app/media/qc.py:788-797` |
| Captions | 2 lines × 42 chars; coverage ≥ 0.95 | `backend/app/media/qc.py:92-98` |
| `STAIRCASE_CUTOVER` | 2026-09-26T00:00:00+00:00 | `backend/app/media/qc.py:630` |
| Licence statuses | public: LICENSED, PUBLIC_DOMAIN (+ legacy stamps); private-only: NEEDS_REVIEW | `backend/app/media/qc.py:703-705` |
| Editorial limits | narration silence 0.25 s at −45 dB; black/frozen end ≤ 1.5 s in last 3 s; avg shot ≤ 3.5 s; opening motion ≥ 0.1 YDIF in 0.5 s; grade ΔE ≤ 25 | `backend/app/media/qc.py:3809-3828` |
| Film looks | one frame/scene at 480 px, ≤ 8 scenes; three frames/scene at 1080 px | `backend/app/agents/editorial.py:78-79`, `backend/app/agents/vision.py:52` |
| Caption rows cut out | ASS 1320-1520, legacy 1380-1560 (of 1920) | `backend/app/media/picture_qc.py:424-425` |
| Reference portraits | ≤ 4 per call, ≤ 4 MB each | `backend/app/media/picture_qc.py:123-127` |
| Score | 1.0 if PASSED else max(0, 1 − 0.25 × failures) | `backend/app/media/qc.py:1424` |
| Publish threshold | PASSED and score ≥ 0.90 | `backend/app/media/qc_report.py:36`, `backend/app/publishing/services.py:166` |

### Director's desk

| Constant | Value | Where |
|---|---|---|
| `PENDING_OUTCOMES` | ASKED, BOUGHT_WAITING | `backend/app/media/director_qc.py:121` |
| `FINAL_OUTCOMES` | ACCEPTED, ACCEPT_REFUSED, REPAIRED, CLOSED + pending | `backend/app/media/director_qc.py:145` |
| `BOUGHT_WAIT_DAYS` | 3 | `backend/app/media/director_qc.py:126` |
| `LOOK_MAX_CANDIDATES` | 6 | `backend/app/media/director_qc.py:139` |
| `NOT_YOURS_CHECKS` | rights_qc, factual_qc, content_source_qc, production_path_qc | `backend/app/media/director_qc.py:151` |
| `LESSON_OVERLAP` / `LESSON_COMPARE_LIMIT` | 0.6 / 40 | `backend/app/media/director_qc.py:231-232` |
| Close lease | `film_purchase_lease` ttl 600 s | `backend/app/media/director_qc.py:1756-1759` |
| Paid redo limits shown to her | `film_max_paid_redos_per_scene` default 5 (≤ 5), `film_max_paid_redos` default 20 (≤ 20), read by the caller with a fallback of 1/2 when no settings object is passed; the Owner's extra allowance from the redo-cap card is added only where the redos are bought, not in what she is shown | `backend/app/config.py:314-315`, `backend/app/runbook/stages.py:4212-4215`, `backend/app/runbook/stages.py:4966-4968` |

### State machines

- **Director decision on one report** (`decision_state`, `backend/app/media/director_qc.py:1367-1410`):
  `none` → her decision event (`media.director_qc_decision`) with outcome ACCEPTED /
  ACCEPT_REFUSED / CLOSED (only the Owner's card now) / REPAIRED (final) or ASKED /
  BOUGHT_WAITING (pending). Pending
  resolves to `ready` (carry on her list without asking her), `look` (refused candidates wait
  for her look), `waiting`, or `lapsed` (hers again). NOTHING_DONE is not final. Each round
  without a decision writes `media.director_qc_waiting` (`tries`).
- **Still candidate** (`still_gate.decide` → `round_step` → `next_step`,
  `backend/app/media/still_gate.py:1139-1213`): PASSED → buy_motion (the passing candidate with
  the fewest minor traces); BLOCKED → compose_locally (the model's verdict) | rewrite (a
  persisting mistake on a still that shows its plan, or after one re-roll) | reroll (≤ 2, only
  with a violation code) | needs_owner (no violation code, or re-rolls spent). Before a rewrite,
  re-roll or needs_owner is acted on, a refused candidate she may see can become APPROVED by her
  second look (`approved_by` `director_look`).
- **Must-fix item** (`fix_check.open_items`, `backend/app/media/fix_check.py:450-482`): open on
  its layer (still, motion or both) from the rewrite or her REAL verdict → answered gone / minor
  / persists by the look → closed on the still layer by an APPROVED still created after it, on
  the motion layer by a clip after it that he approved or that clip QC passed (a clip her look
  kept is recorded PASSED); an item on both layers stays open on the motion layer after the
  still layer closes.
- **Clip** (`clip_retry_decision`, `backend/app/media/qc.py:2485-2564`): ACCEPT | BACK_TO_STILL |
  ESCALATE (persisting mistake on a clip that shows its plan) | RETRY (once) | ESCALATE; outcome
  PASSED | PASSED_ON_RETRY | BACK_TO_STILL | ESCALATED | ACCEPTED_BY_LOOK
  (`backend/app/media/qc.py:2567-2763`).
- **Check status values**: PASSED / FAILED / WARNING / NOT_RUN / NOT_APPLICABLE /
  NOT_IMPLEMENTED / MEASURED / OBSERVED / CARRIED_FORWARD / ADVISORY / NOT_MEASURED / DECIDED.
  Fix answers: gone / minor / persists; her second look: CONFIRMED / OVERTURNED / UNAVAILABLE.

## Modules

### `app.media.qc` — `backend/app/media/qc.py` (4204 lines)

The Phase 5 QC gate (`backend/app/media/qc.py:1-20`): the finished-film report, plus clip QC,
the fallback-scene gate used by the assembler, the delivered-file spec, the span look and
editorial QC. Why: every check is tied to an incident (see "Why it exists"); it measures from
the file, never from the renderer's own row ("trusting our own metadata would make this gate
circular", `backend/app/media/qc.py:987-988`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---:|---|---|---|
| `parse_srt` | 109 | Parses an SRT into cues; raises on malformed blocks | A caption file the platform would reject is not delivered | CODE_RULE |
| `caption_problems` | 146 | Lines > 2, > 42 chars, empty, zero-length, overlap; optional dangling-word rule | Captions must read on a phone (audit Q7 for dangling) | CODE_RULE |
| `dangling_caption_words` | 181 | Cues (but the last) ending on a function word | Phrase broken mid-way (audit Q7) | CODE_RULE |
| `probe_media_file` | 200 | ffprobe facts: size, durations (stream vs container), fps, codec, profile, colour tags, bitrate, audio | "Measured facts, never assumptions"; container length can hide a short picture | CODE_RULE (local ffprobe measurement; no vendor) |
| `still_is_degenerate` | 310 | SSIM after collapsing columns/rows; returns the reason or None | Higgs stripes approved at score 1.0 | CODE_RULE |
| `FlatBand.*` (`rows` 442, `share` 446, `picture_share` 450, `wide` 455, `soft_edge` 460, `splits_a_still` 471, `splits_the_picture` 480, `where_ro` 490, `detail_ro` 502, `soft_edge_ro` 511, `as_dict` 521) | 442-533 | The band's geometry, the soft-edge waiver, the still vs frame split rules, Romanian wording | Triptych 2026-10-09; night-sky 2026-10-10 | CODE_RULE |
| `flat_band` | 549 | Reads the picture in grey 270×480 and returns the deciding band (hard band first) | Panels are held apart by flat bands | CODE_RULE |
| `paid_vendor_names` | 635 | Names of every paid vendor adapter (cached `_paid_vendor_names`) | Detect legacy whole-film purchases | CODE_RULE |
| `rights_verdict` | 708 | `passed` (may upload) and `public_allowed` from the licence status and the manifest's `licences.missing_ro` | AR-15 licence ledger | CODE_RULE |
| `audio_mix_verdict` | 746 | Every bed/ambience track is in the Owner's library with the same sha256; bed 18-22 LU under voice (speech reading first) | Unlicensed tracks; bed balance (sound plan 2026-10-11) | CODE_RULE + OWNER (library) |
| `production_path_verdict` | 829 | From the cutover: PRODUCTION LIVE scenes need a model-written shot plan; no paid vendor bought inside the render | Second Nepal render (A12) | CODE_RULE |
| `shorts_max_seconds` | 899 | Channel's `shorts_max_seconds`, else type default, clamped | Audit PUB-15 | OWNER/CONFIG |
| `evaluate_media_qc` | 924 | The film's report: runs both vision looks first, then measures under a read session, writes `QualityControlReport` + `media.qc_evaluated` + a Video Editor memory in a short write transaction | The publish gate's evidence | CODE_RULE (aggregates LLM looks) |
| `get_media_qc` | 1475 | Newest report of an asset | GET route and readers | CODE_RULE |
| `measure_motion` | 1633 | Per-frame YDIF at 540 px (8-bit), mean, median, fps | Motion metric for clip QC and duplicates | CODE_RULE |
| `motion_fixture` | 1711 | Builds a lossless 5 s push-in or pan from the clip's first frame (4× upscale for sub-pixel motion) | Per-clip calibrated floor | CODE_RULE |
| `calibrate_floors` | 1763 | Measures fixtures; floor = ½ fixture mean; missing kinds = not measured | Same | CODE_RULE |
| `canonical_move` | 1796 | Camera move name from words via `prompt_lint.CAMERA_MOVES`; None if none or two | Floor lookup | CODE_RULE |
| `motion_check` | 1816 | PASSED/FAILED/NOT_RUN against the floor (mean and median) | Frozen B-frame clips read a high mean with a ~0 median | CODE_RULE |
| `cut_spikes` | 1885 | Times of hard cuts | A shot must be one continuous take | CODE_RULE |
| `clip_frames` | 1897 | First/middle/last frames as 1080 px PNGs | Three frames see what one cannot | CODE_RULE |
| `ClipReport.check` | 1965 | Lookup by code | — | — |
| `ClipReport.persists` | 1969 | Whether a motion-layer `must_fix` item was answered persists | A clip repeating its movement's mistake | LLM (the look's answer) |
| `ClipReport.matched_plan` | 1974 | Whether the look said `matches_plan` true (False when nobody said so) | Rewrite vs retry for a persisting mistake | LLM (the look's answer) |
| `_picture_check` | 2009 | Reads the vision verdict strictly into a ClipCheck; a persisting `must_fix` item fails it (its words first), an unanswered one makes it NOT_RUN, a minor one does not fail it | A keep contradicted by its answers fails; 2026-10-12 late evening: the clip is checked for what its movement was rewritten to fix | LLM_CHECKED_BY_CODE |
| `_faces_check` | 2078 | YuNet on three frames when faces are forbidden | Second eye on faces | CODE_RULE |
| `_panels_check` | 2120 | Flat band on three frames | Panels in clips | CODE_RULE |
| `check_clip` | 2198 | All clip checks at 0 credits; TEST downgrades local NOT_RUN to WARNING; reads the look's answers to the motion-layer `must_fix` items (`still_gate.fix_answers`), keeps them on `fixes`, turns minor ones into warnings; sets `back_to_still` (not on the model's `back_to_still` verdict when an item persists) | Redo one bad clip, not a film | CODE_RULE + LLM |
| `clip_deformed` | 2361 | Whether the fault is deformation (calmer retry) vs too little motion | «Mișcare v2» ladder | LLM_CHECKED_BY_CODE (model flags; a motion-floor failure overrides them) |
| `stronger_motion_prompt` | 2419 | Appends a firmer move sentence before the model's closing line; strips legacy stillness sentences | A clip that barely moved | CODE_RULE |
| `calmer_motion_prompt` | 2444 | Appends a moderate, form-keeping sentence | A clip that deformed | CODE_RULE |
| `retry_motion_prompt` | 2468 | Chooses firmer vs calmer | — | CODE_RULE |
| `clip_retry_decision` | 2485 | ACCEPT / BACK_TO_STILL / ESCALATE (a persisting mistake on a clip that shows its plan: no retry, «Directoarea rescrie mișcarea») / ESCALATE / RETRY (seed + 1) with cap check | One retry inside the approved cap; the same words are not bought twice for the same mistake (review of 9ac0195) | CODE_RULE |
| `look_may_overturn` | 2588 | Whether the Director's second look may be asked about a refused clip: measured whole, not back_to_still, a FAILED check, no faces/panels failure, no writing, one picture, no model-seen forbidden face | Owner 2026-10-12: hard-coded rules stay only for the bible's hard limits | CODE_RULE |
| `qc_clip_with_retry` | 2626 | Checks; asks the caller's `look` (her second look) where `look_may_overturn` allows, before the retry and after a failed retry; a look that lets the clip stand → ACCEPTED_BY_LOOK and nothing bought; otherwise buys at most one retry through the caller's `buy` (prompt from `retry_motion_prompt`, firmer or calmer; its docstring says only "firmer"), checks again; a confirmation's reason is added to the outcome | Same; «trece imaginile picate de la QC pe la Directoare» | CODE_RULE (money) + LLM (her look, 03b) |
| `FallbackNotChosen` | 2769 | Exception carrying the unchosen scenes | Stops assembly | — |
| `live_fallback_scenes` | 2782 | LIVE scenes with no motion bytes / reused take | Fallback count from the record | CODE_RULE |
| `owner_local_moves` | 2802 | Scenes the Owner set to LOCAL_MOVE (override or sheet event, last wins) | Only his choice allows a still | OWNER |
| `fallback_verdict` | 2836 | PRODUCTION: every fallback must be his choice; TEST: ceiling warns | Nepal's two stills slipped under "half the scenes" | OWNER + CODE_RULE + CONFIG |
| `require_chosen_fallbacks` | 2895 | Raises before assembling such a PRODUCTION film | Assembler gate | CODE_RULE |
| `technical_problems` | 2923 | Format failures (all environments) and delivery floors (PRODUCTION fail, TEST warn) | Encoder spec | CODE_RULE |
| `moving_spans` | 3017 | Spans of LIVE scenes with generated motion | Where duplicates are counted | CODE_RULE |
| `duplicate_share` | 3046 | Share of repeated frames in the film's moving spans | Stutter | CODE_RULE |
| `shot_duplicate_share` | 3063 | Same, on the shots beside the film (None if any missing) | Lossy film cannot separate slow clips from repeats | CODE_RULE |
| `narration_seconds_of` | 3094 | Sum of recorded `audio_seconds` | Length allowance | CODE_RULE |
| `timeline_spans` | 3124 | Every scene's place, kind, words (recorded or rebuilt) | Length budget, span look | CODE_RULE |
| `film_length_budget` | 3194 | Narration + breaths + silent cards (capped per kind) + 1 s; overruns named | QC_SPANS 2026-10-01 | CODE_RULE |
| `span_frame_numbers` | 3310 | First (after dissolve-in), middle, last frame numbers of a span | The scene's own picture, not a mix | CODE_RULE |
| `_shot_span_frames` | 3376 | Same frames cut from the scene's own shot | Frames without burnt captions | CODE_RULE |
| `span_picture_qc` | 3413 | Three frames per filmed scene: carried scenes skipped; frames from shot / film cropped / film clear / film; YuNet, flat band, vision; per-scene and overall verdict | QC_SPANS; babcf272 | LLM_CHECKED_BY_CODE |
| `picture_trace` | 3844 | One pass: YAVG, YDIF, scdet cuts at 270 px | Editorial QC | CODE_RULE |
| `editorial_cut_times` | 3934 | scdet cuts plus recorded cuts the picture confirms (≥ 2 %, 4× neighbourhood) | Punch-ins are cuts too | CODE_RULE |
| `_narration_silences` | 3998 | Inner silences of the voice track, excluding silent cards | Dead air | CODE_RULE |
| `editorial_problems` | 4040 | dead_air, black/frozen ending, long shots, static opening, dangling captions, no music bed, colour outliers; PASSED/ADVISORY/FAILED/NOT_MEASURED | Audit Q10 | CODE_RULE |
| `editorial_blocking` | 4198 | Whether editorial refuses a film | Advisory until the Owner decides (his card, `backend/app/decisions/seed.py:528-565`) | OWNER/CONFIG |

Helpers: `_srt_seconds`, `_words` (SRT time, word split); `_edge_step` (soft-edge step);
`_paid_vendor_names` (cached vendor scan); `_made_in`, `_bought_inside` (render environment,
paid vendors bought inside the render); `_lu`, `_ro_number`, `_ffmpeg_run`, `_median`,
`_is_none`; `_cut_words` (cut at a word with an ellipsis); `_persists_words` (the Romanian
refusal of a persisting item); `_still_must_change` (decides `back_to_still`; with a persisting
item only the flat band or `one_picture` false count); `_verdict_flags`; `_retry_body`,
`_with_closing`, `_camera_words` (retry prompt text); `_her_words` (her confirmation in the
reason), `_looked` (asks her look only where `look_may_overturn`); `FallbackNotChosen.__init__`;
`_moved`, `_seconds`, `_kind`; `_timeline_frame_ceiling`; `_bible_rules`, `_film_subtitles`,
`_span_subtitles`, `_captions_on_frames` (span look inputs; unreadable cues count as captions
present); `_recorded_cuts`, `_longest_run`, `_silent_beats`, `_voice_source`, `_grade_outliers`
(editorial inputs). Records: `ClipReport` 1946 (new field `fixes`), `ClipRetry` 2479,
`ClipQCOutcome` 2568 (status adds ACCEPTED_BY_LOOK, field `look`).

Data read/written: reads `MediaAsset`, `VideoRenderJob.production_json`, `Storyboard`,
`StoryboardScene`, `FactualClaim`, `ChannelRecord`, `QualityControlReport` (earlier reports),
`DomainEvent` (`SCENE_MODEL_EVENT` for LOCAL_MOVE), the film file, the SRT, shots and voice
track beside it, the music library (through `music_library.load_library`:
`STUDIO_MUSIC_LIBRARY`, else `config/music/music_library.json`, else the shipped
`config/music_library.json`), the look file (`cards.film_finish`). Writes `QualityControlReport`, event `media.qc_evaluated`
(`backend/app/media/qc.py:1428-1441`), a `HISTORICAL_EVENT` memory for the Video Editor
(`backend/app/media/qc.py:1456-1470`). External calls: ffmpeg/ffprobe subprocesses, YuNet,
the vision model (via picture_qc), and the caller's `buy` and `look` callbacks in
`qc_clip_with_retry` (a RunPod purchase made by the assembler; the Director's second look,
`fix_check.shot_second_look`). No publishing.

### `app.media.picture_qc` — `backend/app/media/picture_qc.py` (2221 lines)

"Quality control looks at the pictures before the Director does"
(`backend/app/media/picture_qc.py:1-60`): the three vision call sites, their schemas and
prompts (with the `must_fix` questions of the still and, since 2026-10-12 late evening, of the
bought clip), the clean-frame machinery (shots beside the film, caption-row cutting,
`StudioText`), the submitted-prompt reader, and the "approved stays approved" carry-forward.

| Function | Line | What it does | Why it exists | Decided by |
|---|---:|---|---|---|
| `studio_text_note` | 308 | The paragraph telling the model where frames come from and that subtitles are the studio's | babcf272 failed for its own captions | CODE_RULE |
| `film_captions` | 326 | (burnt in, headline) from the render record | Same | CODE_RULE |
| `clean_shots` | 380 | Each scene's shot beside the film, only if its sha256 matches the record | Later renders overwrite same names; shots are released after QC | CODE_RULE |
| `caption_rows` | 428 | ASS or legacy caption rows, or None | Cut only the caption rows | CODE_RULE |
| `cut_caption_rows` | 449 | Cuts a frame into "above" and "below" the caption rows (never covered, never stitched) | A covered band reads as a blank band; a seam reads as panels; a watermark below was missed by the first crop | CODE_RULE |
| `_shot_middles` | 509 | Middle frame of each shot as base64 JPEG; all or nothing | Frames never mix sources | CODE_RULE |
| `_not_applicable` | 582 | Both checks stood down with one reason | Spec 50 statuses | CODE_RULE |
| `film_scene_prompts` | 612 | The prompts the take was actually submitted with (RunPod `GenerationJob.request.prompt`), else the current storyboard, labelled | A rewritten storyboard does not change what an older take was asked to show | CODE_RULE |
| `scene_takes` | 699 | Per scene (still take, clip take) from the render | Carry-forward identity | CODE_RULE |
| `scene_state` | 720 | A report's verdict on one scene for `picture_qc` or `picture_spans_qc` (True/False/None) | Carry-forward reading | CODE_RULE |
| `EarlierPass.note_ro` / `as_dict` | 770 / 774 | Romanian note «trecută la controlul din … aceleași preluări» and record | Shown in reports | — |
| `earlier_passes` | 784 | Per scene, the newest earlier report of the same storyboard, same takes, that passed it | aa170155, Owner 2026-10-12 | CODE_RULE |
| `_all_carried` | 866 | Whole-film carried result: passed True, no model asked | Same | CODE_RULE |
| `evaluate_pictures` | 904 | **LLM call site 1** (see above) | Spec 50 picture and character gates | LLM |
| `FixAnswer.fixed` | 1499 | True when the item's status is gone (the first version's answer) | Old callers read `fixed` | — |
| `still_report_schema` | 1586 | Schema class requiring every `must_fix` answer (through `_every_fix_answered`) | Silence never reads as gone | CODE_RULE |
| `fix_items` | 1605 | The plan's `must_fix` items as the look is shown them: `finding`, `expected`, and `cause` when known; at most `MAX_FIXES` | One shape for the still's and the clip's look | CODE_RULE |
| `still_image` | 1709 | Still scaled to 1080 px JPEG base64 (≤ 40 MB source) | Faces in the lower third need 1080 px | CODE_RULE |
| `judge_still` | 1765 | **LLM call site 2** | Stills gate's vision half | LLM_CHECKED_BY_CODE (in `decide`) |
| `clip_report_schema` | 1964 | Schema class requiring every motion-layer `must_fix` answer of a clip | As for the still | CODE_RULE |
| `judge_clip` | 2074 | **LLM call site 3** | Clip QC's and the span look's vision half | LLM_CHECKED_BY_CODE (in `_picture_check`) |

Classes (schemas and records): `ScenePictureVerdict` 130, `CharacterVerdict` 144,
`PictureReport` 153, `StudioText` 243, `CleanShot` 337, `EarlierPass` 760, `FixAnswer` 1454
(validators `_legacy_fixed` 1480, `_lower` 1487, `_seen_when_left` 1491; alias `StillFix`
1505), `StillVerdict` 1508, `StillJudgeReport` 1559 (validators `_names_its_stills` 1569,
`_one_picture_answered` 1574), `StillJudgement` 1633, `ClipVerdict` 1911 (new field `fixes`),
`ClipJudgeReport` 1938 (validators `_names_its_clips` 1947, `_one_picture_answered` 1952, which
drops a volunteered `fixes` when none was asked), `ClipJudgement` 1982.

Helpers: `_sha256_of` (lru-cached file hash by path/size/mtime), `_file_sha256`, `_positive`,
`_row` (ffmpeg row expression), `_film_fps`, `_description` (bible look without blanks),
`_reference_asset_id`, `_reference_image` (portrait ≤ 4 MB as base64), `_carried_scene`,
`_every_entry_answers` (schema guard), `_report_named` (refuses a report object without its
`stills` / `clips` list, so a refused report's lone entry is not read as an empty answer),
`_every_fix_answered` (shared item guard), `_studio_words` (the studio's words for each
answered item), `_still_not_run`, `_clip_not_run`.

Data read: `MediaAsset`, `VideoRenderJob`, `Storyboard`, `StoryboardScene`, `CharacterBible`,
`SceneTake`, `QualityControlReport`, `GenerationJob` (read-only journal of RunPod requests,
no provider call: `backend/app/media/picture_qc.py:617-619`), `storyboard_cast_record`
(`app.media.services`). Writes nothing itself; each model run is recorded by `run_agent_task`.
External: ffmpeg subprocesses; the vision model (tokens). No purchases.

### `app.media.still_gate` — `backend/app/media/still_gate.py` (1213 lines)

"Nothing is animated until someone has looked at the still"
(`backend/app/media/still_gate.py:1-149`); every threshold is documented with the stills it was
measured on. Everything fails closed.

| Function | Line | What it does | Why it exists | Decided by |
|---|---:|---|---|---|
| `StillReport.matched_plan` | 342 | True unless the model's `matches_plan` false put `plan` among the violations | Rewrite vs re-roll for a persisting mistake | LLM (the look's answer) |
| `_raw_gray` | 361 | ffmpeg luma at 1080 px, optionally convolved or halved-and-restored | Measurement primitive | CODE_RULE |
| `measure_focus` | 468 | Tile sharpness (trimmed Laplacian, median of sharpest tenth) and fine-detail-kept share | Sharp subject on soft background is in focus (2026-10-09) | CODE_RULE |
| `measure_sharpness` | 498 | The sharpness part only | Compatibility | CODE_RULE |
| `measure_anisotropy` | 505 | Horizontal/vertical gradient energy ratio | Baked motion blur | CODE_RULE |
| `measure_palette` | 551 | Mean ΔE to colours the look names | Coarse look score | CODE_RULE |
| `local_checks` | 629 | The six zero-credit checks in fixed order | Nepal: check before paying for motion | CODE_RULE + OWNER (environment) |
| `fix_answers` | 855 | Per `must_fix` item, by number: the worst of its answers (gone < minor < persists), `fixed` = gone, None if unanswered; with the item's `finding` and `expected`. Used by the gate and by clip QC | Fix check, both layers | LLM (read strictly; the content is not verified) |
| `persists_reason` | 901 | The refusal of a persisting item: what QC saw, which corrected words did not correct it, the content phrase «nu arată ce cere scena după rescriere» | The ladder reads the phrase as a content refusal and rewrites, never re-rolls the same words | CODE_RULE |
| `minor_warning` | 920 | The warning of an accepted minor trace | «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!» | CODE_RULE |
| `decide` | 928 | Folds local checks and the vision verdict into PASSED/BLOCKED, outcome, violations, unmeasured, score; persists → `finding_persists`, minor → warning and `minor`; an unlooked still with `must_fix` gets an extra content reason | Fail closed; answers win over the summary | LLM_CHECKED_BY_CODE |
| `check_still` | 1075 | local_checks → judge_still → decide (always calls the model) | Convenience wrapper (tests) | LLM_CHECKED_BY_CODE |
| `choose_best` | 1109 | Passing candidate with the fewest minor traces, then the best score | Several candidates per scene | CODE_RULE |
| `may_be_overturned` | 1118 | Whether the Director's second look may be asked about a refused candidate (no hard limit, nothing unmeasured, not compose_locally) | Owner 2026-10-12: a look costs nothing, a redo costs credits | CODE_RULE |
| `positive_instruction` | 1133 | Violations → positive phrases for the image model | "Tell the model what to show" | CODE_RULE |
| `next_step` | 1139 | buy_motion / compose_locally / needs_owner (no violation code) / rewrite (a persisting mistake on a still that shows its plan, or after `PERSISTS_REROLLS`) / reroll (≤ 2) / needs_owner (re-rolls spent) | Never pushes a failing still on; never buys the same words for the same mistake twice | CODE_RULE |
| `round_step` | 1198 | The next step of a refused round, from the candidate that decides it | One decision per round | CODE_RULE |

Records: `StillPlan` 271 (scene, prompt, move, faces rule, bible rules, look, palette words,
`scene_picture`, narration, purpose, `must_fix` with `finding`, `expected`, `layer`, `source`,
`source_id`, `cause`), `CheckResult` 307, `StillReport` 316 (new fields `fixes` with `status`,
and `minor`), `NextStep` 348 (action adds `rewrite`), `Focus` 459.

Helpers: `_variance`, `_trimmed_variance`, `_tiles`, `_named_colours`, `_lab` (measurement
maths); `_unmeasured` (NOT_RUN blocking in PRODUCTION only); `_faces_check` (YuNet NOT_RUN
blocks only when faces are forbidden, and then only in PRODUCTION); `_required`; `_is_none`;
`_sha256`; `_sharpness_term`, `_score` (candidate ranking); `_excerpt`; `_fix_answers` (the
plan's items through `fix_answers`).

Data: reads only the still file; writes nothing. External: ffmpeg, YuNet, the vision model.
Money: decides whether motion is bought, whether a still is re-rolled and when the words are
sent to a rewrite instead, and which refused candidates the Director may keep before a re-roll
(the purchase and her look are in `stills_stage`).

### `app.media.director_qc` — `backend/app/media/director_qc.py` (2609 lines)

"The Director decides a film that failed quality control (2026-10-10)"
(`backend/app/media/director_qc.py:1-65`). Her desk for one failed report: what she reads, what
of her decision may be carried out, and the records and letters that follow. "Nothing here
buys, calls a vendor or answers in the Owner's name" (`backend/app/media/director_qc.py:63-64`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---:|---|---|---|
| `is_not_yours` | 196 | Finding is rights/claims/placeholder/production path, a file fault, or a music-licence fact | Things only the Owner or sources settle | CODE_RULE |
| `_check_of` | 336 | Which check wrote a finding (exact listing, prefix, contained words, scene entry, lists) | A production-path line naming a scene was taken for a picture finding | CODE_RULE |
| `report_findings` | 377 | Numbers every failure reason with check, scene and `not_yours`; adds failed checks without reasons | One verdict per finding | CODE_RULE |
| `sound_reading` | 426 | The sound plan and measured bed levels for an audio redo decision | Decide audio on numbers (2026-10-11) | CODE_RULE |
| `owner_approved_take_ids` | 518 | Takes he approved (or, `final_only`, approved as final) | Nobody retires his final approvals | OWNER |
| `film_takes` | 562 | Per scene the still/shot take ids in the film | — | CODE_RULE |
| `protected_redos` | 577 | Per scene and redo kind, his (final) takes the redo would retire | babcf272 retired his approved takes | OWNER |
| `owner_scene_choices` | 622 | His newest per-scene model choice and LOCAL_MOVE scenes | His sheet choices stand | OWNER |
| `decisions_of_film` | 678 | Her decision payloads on the film | History | CODE_RULE |
| `_earlier` | 705 | Her last 4 decisions with outcomes and his answers to their paid questions | Decide again with what came of it | CODE_RULE + OWNER |
| `film_qc_context` | 800 | Everything she reads: findings, per-scene kind/words/takes/approvals/choices/redos left/`passed_before_unchanged`, bible, captions note, limits, money note, Video Editor diagnosis, sound, earlier reviews, her looks, compact checks, redo proposals | The input of `reviews.review_film_qc` | CODE_RULE |
| `annotate_verdicts` | 1003 | Her verdicts joined to findings; `owner_choice_confirmed`; severity/cause/lesson kept | Letters and records | CODE_RULE |
| `_marks_since` | 1055 | Recorded / restored / Owner-approved events of takes in a window | A take given back is not new | CODE_RULE |
| `bought_since` | 1097 | Takes a purchase wrote since a moment (window-bounded) | BOUGHT_WAITING reading | CODE_RULE |
| `new_approved_take` | 1147 | An APPROVED take new since her REPAIR began | babcf272's three-panel still given back was read as new | CODE_RULE |
| `bought_not_in_film` | 1192 | Approved takes bought for her REPAIRs in no film yet | A REPAIR can still join them for free | CODE_RULE |
| `_bought_state` | 1314 | BOUGHT_WAITING → ready / look / waiting / lapsed | A wait never lasts forever | CODE_RULE |
| `decision_state` | 1367 | Where her work on a report stands | Watchdog and walk | CODE_RULE |
| `scene_kinds` | 1413 | Kinds from the sheet | — | CODE_RULE |
| `repair_list` | 1427 | Filters and completes her redo list | His approvals and choices stand; free fixes once; no motion against LOCAL_MOVE | LLM_CHECKED_BY_CODE + OWNER |
| `learn_from_decision` | 1609 | Stores new lessons of REAL/ACCEPTED verdicts as prompt lessons | Owner 2026-10-12: understand why defects appear | LLM (text stored as written; code only de-duplicates and limits who teaches) |
| `record_lessons` | 1646 | Same in its own transaction, right after her decision is read | The rewrite of the very scenes follows them | CODE_RULE |
| `record_decision` | 1671 | Writes `media.director_qc_decision` (+ lessons) | Record | CODE_RULE |
| `accept_film` | 1678 | New PASSED report with a `director_qc` check (verdicts, overrules, original failures); score ≥ 0.90 | The publishing QC gate lets the film through by her decision | LLM_CHECKED_BY_CODE / OWNER (card) |
| `close_film` | 1738 | Under the purchase lease, calls `_closing` | Written for her CLOSE; since her schema refuses CLOSE (2026-10-11) only the Owner's «Închide filmul» card reaches it (`backend/app/decisions/producers/redo_cap.py:340-372`) | OWNER (card) |
| `_closing` | 1762 | `close_film_books` (REJECTED, retired_by Director), withdraw paid approvals, decision event | Nothing more bought for it | CODE_RULE |
| `looks_of_film` | 1837 | Her last 6 looks | Context | CODE_RULE |
| `no_picture` | 1864 | Degenerate candidate (gate's words or re-measured) | Never hers to choose | CODE_RULE |
| `look_pictures` | 1883 | Still at 1080 px or a shot's three frames | Shown as QC shows it | CODE_RULE |
| `look_entries` | 1910 | Per waiting scene, the refused candidates offered to her and those not offered (why) | Owner 2026-10-10 20:06 | CODE_RULE |
| `record_look` | 2069 | Writes `media.director_take_look`; approves her chosen candidate (`approved_by` director, failure cleared, GenerationJob quality synced) if still valid; her choice replaces the gate's refusal, and the walk then continues to the paid motion step or the rejoin | Same | LLM_CHECKED_BY_CODE |
| `wait_for_director` | 2188 | `media.director_qc_waiting` + one inbox note; nothing redone | No model / unusable answer | CODE_RULE |
| `_outcome_line` | 2273 | Romanian outcome sentence | Letter | — |
| `director_letter` | 2318 | STATUS letter to the Owner per report/outcome/new film/purchase count | Owner informed, never asked | INFORMATIONAL |
| `look_letter` | 2423 | STATUS letter to the Owner per look | Same | INFORMATIONAL |
| `settle_inbox` | 2526 | Resolves her waiting note | — | CODE_RULE |
| `outcome_words` | 2543 | One sentence for the stage's reason | Register | INFORMATIONAL |

Helpers: `_payload`, `_short`, `_scene_of`, `_failed_entries`, `_listed`, `_compact_checks`,
`_take_view`, `_not_final` (his non-final approvals a confirmed repair may replace), `_done_of`,
`_asked_ids`, `_diagnosis_of` (Video Editor's ESCALATE letter for the report), `_picture_kinds`,
`_new_since`, `_older_than`, `_asked_state` (ASKED → ready/waiting/lapsed from his answers),
`_waiting_entries`, `_looked_by_owner`, `_her_looks`, `_owed_her_look` (refused, on disk, not
seen, not looked at by him), `_lesson_words`, `_decision_event`, `_file_sha256`,
`_choice_refused`, `_title`, `_open_inbox_notes`, `_verdict_lines`.

Data read: `QualityControlReport`, `SceneTake`, `Storyboard`, `StoryboardScene`,
`VideoRenderJob`, `DomainEvent` (take decided/recorded/restored, sheet model choices, her
decisions/looks/waits), `AgentMessage`, approvals (`services.approval_answers`), prompt lessons.
Written: `QualityControlReport` (PASSED, by `accept_film`), `SceneTake` status/approved_by
(`record_look`), events `media.director_qc_decision`, `media.director_qc_waiting`,
`media.director_take_look`, prompt lessons (`prompt_agent.record_prompt_lesson`), messages
(inbox note `director_qc_waiting`; Owner letters `owner_director_qc`, `owner_director_look`),
film closure via `runbook.stages.close_film_books` and `services.withdraw_subject_approvals`,
`providers.runpod.wiring.sync_take_quality` (generation job quality on her approval).
External: none (ffmpeg only for showing pictures). Money: none spent here; `repair_list`
decides what the caller may buy; `close_film` withdraws paid approvals.

### `app.media.qc_report` — `backend/app/media/qc_report.py` (640 lines)

The Owner's QC report "written from what was measured and nothing else"
(`backend/app/media/qc_report.py:1-19`). Pure and deterministic: no database, network or
provider.

| Function | Line | What it does | Why it exists | Decided by |
|---|---:|---|---|---|
| `RedoProposal.free` / `as_dict` | 108 / 111 | 0 credits = free; serialisation | — | — |
| `ro_number` | 118 | Romanian number format with a true minus | Owner's language | — |
| `ro_count` | 125 | "18 credite" / "200 de credite" | Romanian grammar | — |
| `measured_spend` | 153 | Credits/USD of items of kind `runway` and ElevenLabs characters, from balance deltas only (an item whose `spent` disagrees with its delta is dropped) | Nepal: 0.74 USD booked while 966 credits moved | CODE_RULE |
| `kind_from_text` | 208 | DATA_CARD / BLACK / TITLE_CARD from words | Reports before scenes carried their kind | CODE_RULE |
| `_audio_failure` | 279 | Romanian audio failure line | — | — |
| `_read` | 328 | Reads a report into failure lines, audio/encode needs, per-scene picture/motion needs, editorial notes | The basis of the proposals | CODE_RULE |
| `_paid` | 480 | A paid still/motion proposal priced from the sheet row | Priced redo | CODE_RULE |
| `redo_proposals` | 515 | Per-scene proposals, never the whole film | Nepal was bought twice | CODE_RULE |
| `proposal_line` | 566 | One proposal in words, priced or "preț necunoscut" | — | — |
| `qc_summary_ro` | 586 | The full Romanian report: verdict, failures, editorial notes, measured credits, free fixes, paid fixes, total | The Owner's report | CODE_RULE |

Helpers: `_usd`, `_quote`, `_number`, `_credits_line`, `_sheet_rows`, `_kind_of`,
`_as_report`, `_checks`, `_failed`, `_scene_number`, `_technical_failure`.

Data: none (inputs are the report dict, `production['credits_measured']`, the sheet). No
money is spent; it only prices.

### `app.media.fix_check` — `backend/app/media/fix_check.py` (793 lines)

What a scene's words were rewritten to fix, so the next still and clip are checked for it
(`backend/app/media/fix_check.py:1-38`); plus what every buyer needs the same way: the
Director's second look before a re-roll or a retry, and what a look teaches the rewrite's
lessons (`backend/app/media/fix_check.py:40-43`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---:|---|---|---|
| `observed` | 150 | The sentences of a film reason that say what was seen: a whole process note leaves nothing, a sentence matching `PROPOSAL_SENTENCE` (a purchase, redo, rewrite, credits, a prompt) is dropped | Her REPAIR proposals ride in the same list as the report's words (f06808c9) | CODE_RULE |
| `token_overlap` | 173 | Share of one text's content words found in another | Duplicate findings said twice | CODE_RULE |
| `_rewrite_items` | 313 | Her review's findings on the newest rewrite by her brief that changed the picture (still layer) and on the newest rewrite of any layer (motion layer), each on its own layer (`qc_text`, else her `finding`; `by` as `expected`); for a rewrite whose review kept no findings, the brief's `film` reasons through `observed` (picture rewrite → both layers, motion rewrite → motion) | The review of 9ac0195: findings 1 and 5 | CODE_RULE |
| `_director_qc_items` | 394 | The newest Director QC decision that judged the scene: its REAL verdicts (text, her cause) on their layer, else both | A paid redo that was not rewritten carried nothing to check | CODE_RULE (on her LLM verdicts) |
| `open_items` | 450 | Every open item of a scene, both layers: drops items whose layers are all closed (`_closed`: an APPROVED still, or a clip he approved or clip QC passed, created after the item), narrows a both-layers item to the layer still open, and keeps a finding said twice once (`DUPLICATE_OVERLAP` 0.6) | One list for both buyers | CODE_RULE |
| `open_findings` | 485 | The items of one layer (default still), ranked review → Director QC → film and own-layer matter first (`_ranked`), at most 4 | f06808c9 scene 4: nothing looked for the two women between the rewrite and the finished film | CODE_RULE |
| `fix_status` | 503 | One answer's status (gone, minor, persists) or None | — | CODE_RULE |
| `persisting` | 513 | The answers that persist | — (no caller in `backend/` or `tests/`) | CODE_RULE |
| `minor_traces` | 517 | The minor answers as `{finding, seen}` | Carried on the take | CODE_RULE |
| `review_sources` | 525 | The review runs the items came from, each once | Which provisional lessons to settle | CODE_RULE |
| `settle_lessons` | 536 | Approved with every item gone → `prompt_agent.confirm_prompt_lessons`; refused with an item persisting → `withdraw_prompt_lessons` | «la viitoarele prompturi să se asigure că nu mai sunt»: a lesson that did not correct the mistake must not teach it | CODE_RULE (on the model's fix answers) |
| `record_take_note` | 574 | Writes `media.take_quality_note` on a take: the accepted minor traces and her look when hers approved it | So the same small trace is not refused again after the money | CODE_RULE |
| `take_note` | 618 | The newest note on a take | (called only by tests) | CODE_RULE |
| `director_second_look` | 642 | Asks `second_look.second_look` (03b) and normalises the answer; UNAVAILABLE with `redo` true on no registry, no images, a missing module or any exception | «LLM-ul este pe abonament! … GENERAREA DE IMAGINI ȘI MIȘCĂRI COSTĂ!» | LLM (her verdict, 03b); normalised by code |
| `look_accepts` | 693 | Whether her look lets the take stand: OVERTURNED + none/minor, or CONFIRMED + minor + `redo` false | «DIRECTOAREA ACCEPTĂ DEFECTELE MICI!» | CODE_RULE (on her answer) |
| `look_record` | 706 | Her look as a step's entry keeps it | — | CODE_RULE |
| `shot_second_look` | 713 | Her look at a refused clip: three frames by `qc.clip_frames` in a temporary folder, `director_second_look(kind="shot")`, folder removed | Shown as clip QC saw it | CODE_RULE + LLM (03b) |
| `clip_settled` | 757 | After clip QC's last word: on the clip kept, the take note (`approved_by` `director_look` when hers kept it, else `clip_qc`); with motion items, the lessons settled (kept → confirm when all gone; not kept with an item persisting → withdraw) | The motion layer's equivalent of the stills step's settling | CODE_RULE |

Helpers: `_said`, `_cut`, `_is_process_note` (`PROCESS_NOTES`,
`backend/app/media/fix_check.py:82-86`), `_words`, `_duplicate`, `_scene_of`, `_moment`,
`_later`, `_rewrote_picture`, `_said_in` (a treating sentence of ≥ 4 words found word for word in
a prompt), `_review_layer` (an item's layer: its own, else the motion for a motion rewrite, else
where its treating sentence stands, else both), `_on`, `_approved_still_after`,
`_passing_clip_after` (reads `assembler.clip_qc_of`), `_closed`, `_item`, `_ranked` (the cap's
order), `_unavailable`.

Data read: `DomainEvent` (`assembler.SCENE_PROMPTS_REWRITTEN_EVENT`, `scene_rewrite.BRIEF_EVENT`,
`media.director_qc_decision`, `media.take_quality_note`), `SceneTake`, the clip QC record of a
take (`assembler.clip_qc_of`). Written: `media.take_quality_note` events; provisional prompt
lessons confirmed or withdrawn (`prompt_agent.confirm_prompt_lessons`,
`prompt_agent.withdraw_prompt_lessons`). The findings themselves were written by LLMs elsewhere
(the Director's review, brief and QC decision, the film QC); this module selects them. External:
the Director's second look (03b; model tokens, no purchase) and ffmpeg for a clip's frames.
Money: none spent here; a look that lets a take stand stops the purchase the caller would make.

### `app.media.faces` — `backend/app/media/faces.py` (178 lines)

The second, deterministic eye on faces (`backend/app/media/faces.py:1-25`): YuNet, pinned by
sha256, MIT licence, bundled with its licence file. Reports NOT_RUN, never "0 faces", when it
cannot look.

| Function | Line | What it does | Why it exists | Decided by |
|---|---:|---|---|---|
| `model_problem` | 86 | Missing / unreadable / wrong-hash model → Romanian reason | A swapped network is not the detector the thresholds were set for | CODE_RULE |
| `detector_available` | 112 | opencv with `FaceDetectorYN` and the pinned model present | Tests skip without it | CODE_RULE |
| `count_faces` | 117 | Decodes, scales to ≤ 1080 px, detects at score 0.6, returns count and boxes | Faces forbidden by the bible (Nepal) | CODE_RULE |

Helpers: `_not_run`, `_sha256`, `_opencv`. Data: the image file and the bundled model. No DB.

## Connections

### Who calls into this group

| Caller | Calls | Where |
|---|---|---|
| Daily QC stage | `evaluate_media_qc` (with settings, registry, ffmpeg path), then `assembler.release_after_qc` | `backend/app/runbook/stages.py:3755-3767` |
| Director's repair requalification | `evaluate_media_qc` on the repaired film | `backend/app/runbook/stages.py:5270-5280` |
| Shooting sheet assemble step | `evaluate_media_qc`, `qc_summary_ro` (its docstring at 3820 names `require_chosen_fallbacks`, which the assembler calls) | `backend/app/media/shooting_sheet.py:4041`, `backend/app/media/shooting_sheet.py:3739-3745` |
| Rehearsal (zero-credit dry run) | `local_checks`, `evaluate_media_qc`, `qc_summary_ro` | `backend/app/media/rehearsal.py:554`, `backend/app/media/rehearsal.py:1260`, `backend/app/media/rehearsal.py:1129-1139` |
| HTTP `POST /media/render/{storyboard_id}` (`start_render`) | `evaluate_media_qc` after a render | `backend/app/media/router.py:522`, `backend/app/media/router.py:692` |
| HTTP `GET /media/qc/{identifier}` | `get_media_qc` | `backend/app/media/router.py:1362-1383` |
| HTTP `POST /media/qc/{identifier}` (the Owner's re-QC) | `evaluate_media_qc` | `backend/app/media/router.py:1385-1425` |
| HTTP `GET /media/storyboards/{id}/shooting-sheet` | `count_faces` (face badge) | `backend/app/media/router.py:827-849` |
| Stills step | `local_checks`, `judge_still`, `decide`, `choose_best`, `round_step` (→ `next_step`), `may_be_overturned`, `positive_instruction`, `MAX_REROLLS`, `open_findings(layer=STILL_LAYER)`, `director_second_look`, `look_accepts`, `look_record`, `record_take_note`, `settle_lessons`, `DIRECTOR_LOOK_APPROVER` | `backend/app/media/stills_stage.py:155-179`, `backend/app/media/stills_stage.py:546-547`, `backend/app/media/stills_stage.py:912-941`, `backend/app/media/stills_stage.py:1002-1184` |
| Assembler | still redo through `stills_stage._judge_candidate` and `_settle_round`; `check_clip`/`qc_clip_with_retry`/`judge_clip` (clip QC) with `open_findings(layer=MOTION_LAYER)`, `shot_second_look`, `ACCEPTED_BY_LOOK`, `look_record`, `clip_settled`; `require_chosen_fallbacks`, `still_is_degenerate` | `backend/app/media/assembler.py:16546-16579`, `backend/app/media/assembler.py:10268-10454`, `backend/app/media/assembler.py:3622-3637`, `backend/app/media/assembler.py:2863-2983` |
| Clip plan | `still_gate.StillPlan` with the motion-layer `must_fix` (`assembler._clip_plan`) | `backend/app/media/assembler.py:10207-10242` |
| Video Editor / Director reviews | `qc_summary_ro`, `redo_proposals` (the Video Editor's reading), `film_qc_context` (named in the docstring; built by the caller), `look_entries` / `record_look` (named; built by the caller), `LOOKERS` | `backend/app/agents/reviews.py:69-77`, `backend/app/agents/reviews.py:400-452`, `backend/app/agents/reviews.py:981-988`, `backend/app/agents/reviews.py:1148-1181` |
| Director's walk (`director_decides_failed_film` and its helpers) | `film_qc_context`, `decision_state`, `record_lessons`, `annotate_verdicts`, `look_entries`, `record_look`, `look_letter`, `wait_for_director`, `record_decision`, `accept_film`, `close_film` (unreachable by a validated answer), `repair_list`, `protected_redos`, `owner_scene_choices`, `owner_approved_take_ids`, `bought_since`, `bought_not_in_film`, `new_approved_take`, `director_letter`, `settle_inbox` | `backend/app/runbook/stages.py:4041-4700`, `backend/app/runbook/stages.py:3906`, `backend/app/runbook/stages.py:4915-4916`, `backend/app/runbook/stages.py:5203` |
| Watchdog pass | `decision_state` (the docstring names `wait_for_director`, which it does not call) | `backend/app/workflows/passes/director_qc_review.py:80`, `backend/app/workflows/passes/director_qc_review.py:133` |
| Owner's decision cards | `accept_film` (`decided_by` owner), `close_film` | `backend/app/decisions/producers/redo_cap.py:292-370` |

### What it calls out to

`app.agents.structured.structured_run` → `app.agents.services.run_agent_task` (LLM);
`app.agents.vision` (`vision_agent`, `frames_at`) and `app.agents.editorial.frames_for`;
`app.factual.sanitizer.wrap_in_inert_boundary`; `app.media.toolchain` (ffmpeg/ffprobe,
`measure_loudness`, `silence_spans`, `has_filter`); `app.media.assembler` (take events,
`shot_plan_sources`, `clip_choice`, `scene_clip_context`, `SHOT_TAKE_KINDS`,
`DEGENERATE_FAILURE_CODE`); `app.media.prompt_lint` (`CAMERA_MOVES`, `bible_face_rule`,
closing lines); `app.media.cost_plan.credits_to_micros`; `app.media.music_library`;
`app.media.cards` (`film_finish`, caption geometry); `app.media.production_policy.LOCAL_MOVE`;
`app.media.shooting_sheet` (`SCENE_MODEL_EVENT`, `film_purchase_lease`, `sheet_url`,
`film_is_closed`); `app.media.stills_stage._bible_rules`; `app.media.prompt_agent`
(`prompt_lessons`, `record_prompt_lesson`, `confirm_prompt_lessons`,
`withdraw_prompt_lessons`); `app.media.scene_rewrite` (`BRIEF_EVENT`, `REWRITE_REASON`);
`app.media.assembler` (`SCENE_PROMPTS_REWRITTEN_EVENT`, `clip_qc_of`);
`app.media.second_look.second_look` (the Director's second look, 03b); `app.publishing` (`ChannelRecord`,
`channel_type_for_storyboard`, `QC_MINIMUM_SCORE`); `app.runbook.stages`
(`close_film_books`, `film_spent_micros`); `app.services` (`append_event`, `utc_now`,
`studio_environment`, `approval_answers`, `withdraw_subject_approvals`); `app.agents.messages`
(`post_message`, `resolve_message`); `app.agents.memory` (`agent_for_role`, `remember`);
`app.providers.runpod` (`GenerationJob` read, `sync_take_quality`); YuNet via opencv.

### Events

| Event | Emitted by | Consumed by |
|---|---|---|
| `media.qc_evaluated` | `evaluate_media_qc` (`backend/app/media/qc.py:1428-1441`) | event feed / register |
| `media.director_qc_decision` | `record_decision`, `accept_film`, `_closing` (`backend/app/media/director_qc.py:1655-1668`) | `decision_state`, `decisions_of_film`, `bought_not_in_film`, `fix_check._director_qc_items` (her REAL verdicts become `must_fix` items) |
| `media.take_quality_note` | `fix_check.record_take_note` (`backend/app/media/fix_check.py:574-615`), from `stills_stage._after_approval` and `fix_check.clip_settled` | `fix_check.take_note` only, which no backend module calls (tests only) |
| `media.director_second_look` | `second_look._record` (03b), for every look asked through `fix_check.director_second_look` | 03b; the events feed |
| `media.director_qc_waiting` | `wait_for_director` (`backend/app/media/director_qc.py:2205-2217`) | `decision_state` (`tries`) |
| `media.director_take_look` | `record_look` (`backend/app/media/director_qc.py:2153-2155`) | `_her_looks`, `looks_of_film`, `look_letter` |
| `agent.message_posted` | `post_message` (inbox note, Owner letters) | office / inbox |
| consumed: `media.scene_take_decided`, take recorded/restored events | assembler | `owner_approved_take_ids`, `_marks_since`, `_looked_by_owner` |
| consumed: `SCENE_MODEL_EVENT` | shooting sheet | `owner_local_moves`, `owner_scene_choices` |
| consumed: `SCENE_PROMPTS_REWRITTEN_EVENT`, `BRIEF_EVENT` | assembler / scene_rewrite | `fix_check._rewrite_items` (through `open_findings`) |
| consumed: `media.clip_qc_checked` (a take's clip QC record, through `assembler.clip_qc_of`) | assembler | `fix_check._passing_clip_after` (a clip that passed closes the motion layer's items) |

## Owner touchpoints

| Touchpoint | What the Owner decides | Where |
|---|---|---|
| Take approvals on the shooting sheet (with `final`) | Final approvals are never retired by the Director's repairs; non-final ones may be replaced (he is told) | `backend/app/media/director_qc.py:518-559`, `backend/app/media/director_qc.py:577-619`, `backend/app/media/director_qc.py:1548-1556` |
| His look at a take on the sheet | Wins over the Director's look; a take he looked at is never offered to her | `backend/app/media/director_qc.py:1295-1311`, `backend/app/media/director_qc.py:2058-2059` |
| LOCAL_MOVE choice per scene | Only way a PRODUCTION film may show a LIVE scene as a still; blocks motion redos for that scene (REJOIN instead) | `backend/app/media/qc.py:2802-2892`, `backend/app/media/director_qc.py:1540-1547` |
| Per-scene model choice on the sheet | Shown to the Director as his choice | `backend/app/media/director_qc.py:622-644` |
| Answers to paid questions (approvals) | ASKED decisions resume (`ready`) on his yes, lapse on his no / expiry | `backend/app/media/director_qc.py:1234-1250` |
| Cards «Publică filmul așa cum e» / «Închide filmul» (the paid-redo cap card) | `accept_film(decided_by=owner)`, `close_film`; the close is the only way a failed, rendered film is closed now (her CLOSE is refused by her schema) | `backend/app/decisions/producers/redo_cap.py:288-372` |
| Environment TEST / PRODUCTION (his policy row) | Whether unmeasured local checks and the delivery floors block, and whether a LIVE scene may be a still | `backend/app/services.py:232-241`, `backend/app/media/still_gate.py:592-600`, `backend/app/media/qc.py:2309-2316`, `backend/app/media/qc.py:3010-3013`, `backend/app/media/qc.py:2869-2892` |
| Setting `editorial_qc_blocking` (or look file) | Whether editing faults refuse a film (his «Controlul editorial» card guides him to the setting) | `backend/app/media/qc.py:4198-4204`, `backend/app/config.py:183-186`, `config/factual_look.json:63`, `backend/app/decisions/seed.py:528-565` |
| Setting `max_fallback_scenes` | TEST warning ceiling only | `backend/app/media/qc.py:2883-2892`, `backend/app/config.py:344-350` |
| Channel `shorts_max_seconds` | Maximum film length per channel | `backend/app/media/qc.py:899-921` |
| His music library (`config/music/music_library.json`, git-ignored, unless `STUDIO_MUSIC_LIBRARY` names another; the shipped `config/music_library.json` is empty) | Which tracks are licensed | `backend/app/media/qc.py:746-773`, `backend/app/media/music_library.py:36-58` |
| Re-QC button `POST /media/qc/{id}`; `GET /media/qc/{id}` | Re-measure a film; read the report | `backend/app/media/router.py:1362-1425` |
| Letters (STATUS, never questions) | Informed of every Director decision and look | `backend/app/media/director_qc.py:2318-2420`, `backend/app/media/director_qc.py:2423-2523` |
| The Owner's QC report text | Failures, measured credits, free vs paid fixes | `backend/app/media/qc_report.py:586-640` |
| "needs_owner" / "ESCALATE" wording | Still gate after 2 re-rolls or unmeasured; clip QC after its retry, unmeasured or over cap. Not his since 2026-10-12 late evening: a persisting mistake on a picture that shows its plan, whose words go to the Director («Directoarea le rescrie» / «Directoarea rescrie mișcarea»), although the stills step still files it as NEEDS_OWNER with a `rewrite` flag | `backend/app/media/still_gate.py:1152-1195`, `backend/app/media/qc.py:2515-2553`, `backend/app/media/stills_stage.py:1173-1181` |
| His look at a clip nobody could check | A clip whose only blocks are unmeasured is kept PAID as UNCHECKED and waits for his look on the sheet; her second look is never asked about it (something is unmeasured) | `backend/app/media/assembler.py:10447-10454`, `backend/app/media/qc.py:2594` |
| His standing rules on QC refusals (2026-10-12) | Small defects are accepted (minor answers; her look may keep a take with a minor defect); a look before a paid redo; hard-coded refusals only for the bible's hard limits. These are encoded as code rules here, not read from a setting | `backend/app/media/fix_check.py:40-43`, `backend/app/media/fix_check.py:127-130`, `backend/app/media/fix_check.py:693-703` |

## Oddities and gaps

1. `still_gate.check_still` (`backend/app/media/still_gate.py:1075-1103`) is called only by
   `tests/test_still_gate.py`; production uses `stills_stage._judge_candidate`
   (`backend/app/media/stills_stage.py:912-941`), which skips the vision call when a local check
   already blocks, while `check_still` always calls the model.
2. `qc_report._read` ignores a `picture_qc` scene whose only false answer is `one_picture`
   (`backend/app/media/qc_report.py:373-378`): no failure line and no redo proposal from that
   branch (the generic branch may still catch the scene through `picture_spans_qc`,
   `backend/app/media/qc_report.py:464-476`).
3. `qc_report._read` tests `picture_qc` status `"NOT_RUN"` (`backend/app/media/qc_report.py:359`,
   `backend/app/media/qc_report.py:370`), but `evaluate_pictures` writes NOT_APPLICABLE /
   MEASURED / CARRIED_FORWARD; those branches do not fire on reports written by the current code.
4. `qc_report._read` reads `character_drift_qc["scenes"][].passed`
   (`backend/app/media/qc_report.py:402-406`); `evaluate_pictures` writes `characters[]` with
   `matches` (`backend/app/media/picture_qc.py:1372-1383`). A character-drift failure never
   yields a per-scene redo proposal.
5. `qc_report._technical_failure` reads `measured_bitrate_bps` / `bitrate_bps`
   (`backend/app/media/qc_report.py:318`); `evaluate_media_qc` writes `video_bit_rate`
   (`backend/app/media/qc.py:1172`).
6. `qc_report._read` looks for per-scene motion entries under `clips`/`scenes` lists
   (`backend/app/media/qc_report.py:421-427`); `fallback_verdict` stores `scenes` as a count
   and the scene list as `live_fallbacks` (`backend/app/media/qc.py:2858-2868`), so PRODUCTION
   fallback scenes never become motion redo proposals.
7. `PUBLISH_SCORE` (`backend/app/media/qc_report.py:36`) duplicates
   `publishing.services.QC_MINIMUM_SCORE` (`backend/app/publishing/services.py:166`), both 0.90;
   `accept_film` takes the maximum of both (`backend/app/media/director_qc.py:1714`).
8. The QC score carries no information beyond PASSED (always 1.0) and the failure count
   (`backend/app/media/qc.py:1424`).
9. Spec drift: `docs/architecture/50_CONTENT_GATE_MATRIX.md:59-66` says the frames are "cut from
   the finished film" and the picture gate "asks two things"; the code cuts from each scene's
   own shot when it is still beside the film (`backend/app/media/picture_qc.py:1043-1058`) and
   asks three questions (`one_picture` since 2026-10-09).
10. Carry-forward reads only passes: `earlier_passes` takes the newest earlier report that
    passed the scene and skips (does not stop at) a newer report that failed the same scene with
    the same takes (`backend/app/media/picture_qc.py:818-842`). A carried verdict is itself
    carried again (`backend/app/media/picture_qc.py:736`). When every scene is carried,
    `picture_qc` reports `passed` True with `frames` 0 and `model_used` False
    (`backend/app/media/picture_qc.py:874-884`), a pass not measured in this run (the Owner's
    rule of 2026-10-12) next to spec 50's "a gate certifies only what it measured".
11. The two film looks encode a carried scene differently: `picture_qc` entry status
    `CARRIED_FORWARD` (`backend/app/media/picture_qc.py:846-856`); `picture_spans_qc` entry status
    `PASSED` with `picture.status` `CARRIED_FORWARD` (`backend/app/media/qc.py:3598-3605`).
12. Fail-closed vs fail-open: the stills gate and clip QC block when nobody looked
    (`backend/app/media/still_gate.py:965-973`, `backend/app/media/qc.py:2009-2029`), while
    the finished-film looks add no failure when they cannot run
    (`backend/app/media/qc.py:1416-1421`, per spec 50). With no registry or no seeing employee a
    film can pass QC with no vision look at all (only the free flat band and YuNet are read on
    the span frames). A clip whose only blocks are unmeasured is not discarded either: the
    assembler keeps it PAID as UNCHECKED for the Owner's look
    (`backend/app/media/assembler.py:5111-5133`, `backend/app/media/assembler.py:10447-10454`).
13. `ScenePictureVerdict` and `CharacterVerdict` booleans are plain `bool`
    (`backend/app/media/picture_qc.py:136-139`, `backend/app/media/picture_qc.py:148`), so
    pydantic's lax mode coerces strings such as "false" or "no"; `StillVerdict` and
    `ClipVerdict` use `StrictBool`.
14. The data JSON shown to the model is cut by raw slicing: 14 000 characters for the film look
    (`backend/app/media/picture_qc.py:1158`), 8000 for still and clip
    (`backend/app/media/picture_qc.py:1824`, `backend/app/media/picture_qc.py:2153`); the
    character list or bible rules at the end can be cut mid-JSON. The still's look puts its
    `must_fix` items before the look and the rules so they survive the cut
    (`backend/app/media/picture_qc.py:1809-1812`); the clip's look appends them last, after the
    prompt sources, the bible rules and the subtitles (`backend/app/media/picture_qc.py:2124-2145`),
    so a long clip plan can lose its items to the cut while `clip_report_schema` still requires
    an answer for each.
15. `evaluate_pictures` pairs the film's cut frames with scenes by position
    (`backend/app/media/picture_qc.py:1062-1074`), while `frames_for` skips scenes whose planned
    seconds are falsy (`backend/app/agents/editorial.py:351-357`); a zero-length scene would
    shift the pairing.
16. Character verdicts are matched by exact canonical name (`backend/app/media/picture_qc.py:1282-1287`);
    a model that spells the name differently produces NOT_APPLICABLE "no verdict returned".
17. Comment drift: `TEMPLATE_VERSION` comments list v2 and v3 but the value is v4
    (`backend/app/media/picture_qc.py:111-114`); same for `CLIP_TEMPLATE_VERSION`
    (`backend/app/media/picture_qc.py:1893-1897`). The still price is "9 credits" in
    `backend/app/media/still_gate.py:6` and "7 credits" in `backend/app/media/still_gate.py:1030`.
18. `director_letter` and `look_letter` post a `to_owner` STATUS letter for every decision and
    look (`backend/app/media/director_qc.py:2397-2419`, `backend/app/media/director_qc.py:2504-2522`);
    the decision log of 2026-10-12 morning says a letter reaches the Owner only for accounts,
    authorisations and security/legal standing (`docs/project/16_DECISION_LOG.md:53`).
19. Wording says the Owner decides where the 2026-10-12 rules give quality to the Director:
    `next_step` «Decide Proprietarul pe foaia de filmare» (`backend/app/media/still_gate.py:1190-1194`),
    `clip_retry_decision` «Decide Proprietarul» (`backend/app/media/qc.py:2534-2553`), and the
    status label NEEDS_OWNER carried into `stills_stage` (`backend/app/media/stills_stage.py:1173-1184`),
    which also labels NEEDS_OWNER the new `rewrite` step whose reason says the Director rewrites
    the words, marking it only with `rewrite` true (`backend/app/media/stills_stage.py:1178-1181`).
    Where those scenes actually go next is decided downstream (not in this group).
20. The model's `compose_locally` verdict alone routes a still to the COMPOSE_LOCALLY hold
    (`backend/app/media/still_gate.py:1050-1051`, `backend/app/media/still_gate.py:1145-1150`;
    hold event in `backend/app/media/stills_stage.py:1807-1828`); no code checks that the plan
    asks for a card.
21. `learn_from_decision` turns model-written `lesson` text into prompt rules read by the
    shot-prompt writer and scene rewriter, with only a word-overlap de-duplication
    (`backend/app/media/director_qc.py:1626-1643`).
22. `accept_film` does not check `not_yours` itself; the refusal lives in its caller
    (`backend/app/runbook/stages.py:4467-4477`). The Owner's card path calls it directly with
    `decided_by` owner (`backend/app/decisions/producers/redo_cap.py:288-338`).
23. `editorial_problems` "no_music_bed" states that the library has no usable licensed track
    whatever the reason the film has no bed (`backend/app/media/qc.py:4147-4152`).
24. `evaluate_media_qc` reads the whole film into memory to hash it
    (`backend/app/media/qc.py:991`); its docstring says the fallback ceiling defaults to half
    the scenes (`backend/app/media/qc.py:937-939`), which holds only in TEST
    (`backend/app/media/qc.py:2869-2892`).
25. `docs/architecture/08_VIDEO_PIPELINE.md:278-279` gives paid redo limits of 1 per scene and
    2 per film; the config defaults are 5 and 20 (`backend/app/config.py:314-315`, the Owner's
    rule of 2026-10-11), and these are the limits `film_qc_context` shows the Director.
26. `ASS_CAPTION_ROWS` starts at `CAPTION_BAND_TOP` 1320 (`backend/app/media/picture_qc.py:424`,
    `backend/app/media/cards.py:55`) while the comment measured ASS captions in rows 1365-1494
    (`backend/app/media/picture_qc.py:415-423`): a deliberate margin of 45 rows above.
27. Every film QC re-runs both vision looks (1 + N calls, each up to 2 attempts), including the
    Owner's re-QC; only scenes carried forward from an earlier pass are skipped
    (`backend/app/media/qc.py:956-975`).
28. The Director's CLOSE is dead code for her: her bound answer schema refuses CLOSE since the
    Owner's rule of 2026-10-11 (`backend/app/agents/reviews.py:865-871`; her instructions offer
    only ACCEPT or REPAIR, `backend/app/agents/reviews.py:922-951`), yet the walk keeps a CLOSE
    branch (`backend/app/runbook/stages.py:4480-4482`) and her look letter still tells the Owner
    she may «închide filmul» (`backend/app/media/director_qc.py:2491-2493`). `close_film` now runs only for the Owner's
    card, and `_closing` still books it as hers: `retired_by` Director and «Închis de Directoare
    după controlul calității» (`backend/app/media/director_qc.py:1781-1795`), the withdrawal
    reason «Directoarea a închis filmul» (`backend/app/media/director_qc.py:1797-1805`).
29. The one-frame look passes on a partial answer: `picture_qc.passed` is True when at least one
    scene was answered and none failed, while scenes the model left out or past the 8-frame cap
    are only NOT_APPLICABLE entries (`backend/app/media/picture_qc.py:1206-1219`,
    `backend/app/media/picture_qc.py:1247-1265`); duplicate entries for one scene are not
    refused, the last one wins (`backend/app/media/picture_qc.py:1204`), whereas `judge_still`
    and `judge_clip` refuse more than one entry for their scene. The span look is stricter: it
    passes only when every filmed scene passed (`backend/app/media/qc.py:3737-3741`).
30. A still the model gives `regenerate_still` while answering every question positively is
    BLOCKED with no violation code (`backend/app/media/still_gate.py:1044-1045`), so `next_step`
    answers needs_owner with the words «verificările nu au putut rula», which is not what
    happened (`backend/app/media/still_gate.py:1152-1159`); the Director's second look is not
    offered for it either, because `may_be_overturned` requires a violation code
    (`backend/app/media/still_gate.py:1126`).
31. The `scene` violation (shows_scene false, `backend/app/media/still_gate.py:1028-1034`) has no
    entry in `POSITIVE_WORDS` (`backend/app/media/still_gate.py:249-263`): a still re-rolled
    only for not showing the scene is re-rolled with no added words
    (`backend/app/media/still_gate.py:1133-1136`).
32. Her ACCEPT can pass measured failures the code holds in every environment: only
    rights/factual/content-source/production-path checks, four file faults and the music-licence
    lines are «not hers» (`backend/app/media/director_qc.py:147-205`). A wrong codec, profile,
    colour tags or frame rate, loudness out of band, broken captions, a bed outside 18-22 LU or a
    picture/character refusal can all be accepted away by her verdicts, and the PASSED report she
    writes is what the publishing gate reads (`backend/app/media/director_qc.py:1678-1735`).
33. Her look can approve a candidate a code gate refused on a measurement (flat band, sharpness,
    motion blur, YuNet faces, clip motion floor or cut): `look_entries` keeps from her only
    degenerate pictures, changed files and ineligible shots, and `record_look` clears the
    refusal (`backend/app/media/director_qc.py:1992-2011`, `backend/app/media/director_qc.py:2136-2151`).
    The paid motion step follows for an approved still.
34. The paid-redo limits she reads (`film_qc_context` `paid_redos_left`) do not include the
    Owner's extra allowance from the redo-cap card: `_redo_allowance` reads the base settings
    (`backend/app/runbook/stages.py:4212-4215`) while `_apply_repairs` adds `redo_allowance`
    (`backend/app/runbook/stages.py:4966-4968`), so after his «allow» her schema may still
    refuse a REPAIR as having no paid redo left (`backend/app/agents/reviews.py:767-771`).
35. Every paid step's measured spend is written as kind `runway` (`backend/app/media/assembler.py:3686-3693`),
    so the Owner's report says «Runway N credite» for RunPod steps too
    (`backend/app/media/qc_report.py:183-202`).
36. The take note is written but not read: `TAKE_NOTE_EVENT`'s comment says the film QC's
    context reads it so the same small trace is not refused again after the money
    (`backend/app/media/fix_check.py:121-124`), but `fix_check.take_note`
    (`backend/app/media/fix_check.py:618-626`) is called only by `tests/test_fix_is_verified.py`,
    and no backend module reads `media.take_quality_note`; the film's picture looks and
    `director_qc.film_qc_context` do not see the minor traces accepted before the money.
37. `may_be_overturned` does not exclude the measured `sharpness` and `motion_blur` violations
    or a model-named `bible` violation (`backend/app/media/still_gate.py:1118-1130`,
    `HARD_LIMITS` at `backend/app/media/fix_check.py:130`). In production a still a local check
    refused is never shown to the vision model (`backend/app/media/stills_stage.py:934-938`),
    so "vision" is unmeasured and her second look is not offered: in practice she can overturn
    only refusals made by the model's answers. Through `check_still` (tests) a sharpness or
    motion-blur refusal would be offered to her.
38. A still of a rewritten scene that the model did not look at gets the content reason «până se
    vede, se socotește că nu arată ce cere scena după rescriere» (`backend/app/media/still_gate.py:974-984`),
    including every candidate the production path did not show to the model because a local
    check had already blocked it (`backend/app/media/stills_stage.py:934-938`); the reason adds no
    violation code.
39. A refusal her second look keeps closes the layer's open items: the still is set APPROVED
    (`backend/app/media/stills_stage.py:1026-1029`) and the kept clip is recorded PASSED
    (`backend/app/media/assembler.py:10365-10373`), which is what `_approved_still_after` and
    `_passing_clip_after` read (`backend/app/media/fix_check.py:253-289`). A mistake the model
    said persists and she judged minor is then closed on that layer: a later still (or clip) of
    the scene is not checked for it unless a newer rewrite or REAL verdict names it again.
40. `observed` drops a film reason's sentence that contains any `PROPOSAL_SENTENCE` word
    anywhere, including «new still», «approved still», «the prompt», «bought» or «credits»
    (`backend/app/media/fix_check.py:93-99`, `backend/app/media/fix_check.py:157-161`), so a
    sentence describing what a new still showed is dropped like a purchase proposal (only for
    rewrites whose review kept no findings, `backend/app/media/fix_check.py:369-390`).
41. `fix_check.persisting` (`backend/app/media/fix_check.py:513-514`) and `PICTURE_LAYER`
    (`backend/app/media/fix_check.py:69`) have no caller in `backend/` or `tests/`.
    `_director_qc_items` reads every `media.director_qc_decision` event of the studio newest
    first and filters the storyboard in Python (`backend/app/media/fix_check.py:399-406`).
42. The second look is wired for stills and bought clips only. The finished film's refusals
    (`evaluate_pictures`, `span_picture_qc`) are not offered to it; the `film_scene` kind of
    `second_look` is used by `scripts/qc_audit.py` alone (03b), although `second_look`'s
    docstring names "her own film repair" among the purchases it precedes
    (`backend/app/media/second_look.py:13-16`).
