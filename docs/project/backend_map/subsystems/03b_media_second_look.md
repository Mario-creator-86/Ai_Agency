# 03b — The Director's second look at refused pictures

> Files:
> - `backend/app/media/second_look.py` — 763 lines (16 functions, 1 LLM call site), new in
>   commit `20abffd`
> - Integration points, mapped here only where they touch the look (line counts at `20abffd`):
>   `backend/app/media/fix_check.py` (793), `backend/app/media/still_gate.py` (1213),
>   `backend/app/media/stills_stage.py` (2544), `backend/app/media/qc.py` (4204),
>   `backend/app/media/assembler.py` (16 716), `backend/app/events_feed.py` (1377), and the
>   offline script `scripts/qc_audit.py` (772)
> - History: the wiring in `fix_check`, `still_gate`, `stills_stage`, `qc` and `assembler`
>   arrived one commit earlier, in `5fc7468`, where `second_look.py` did not exist yet: the lazy
>   import in `fix_check.director_second_look` failed and every look was UNAVAILABLE
>   («privirea a doua a Directoarei nu este instalată», `backend/app/media/fix_check.py:663-666`)
>   until `20abffd` added the module and the audit script.
>
> Mapped at commit 20abffd. Every `file:line` below is a line of `20abffd`
> (`git show 20abffd:<path>`); `:N` repeats the file named just before. Read-only: nothing was
> run, no model was asked. The surrounding code is mapped at `b00083c` elsewhere: the stills
> gate and clip QC in `03_media_quality_control.md`, the stills step in
> `06_media_execution.md`, the assembler's clip QC in `02_media_assembler_part2.md`, the
> Director's earlier look at her repair's candidates in `11_agents_reviews_repairs.md`, the
> register in `17_app_core.md`.
>
> **After this map's commit:** `d4335c6` (2026-10-12 19:30) changed `qc.py`, `picture_qc.py`,
> `director_qc.py`, `agents/reviews.py` and `runbook/stages.py`, and wires the kind `film_scene`
> into the Director's film REPAIR (`runbook.stages._second_look_before_redo`,
> `backend/app/runbook/stages.py:5034` at `d4335c6`). That wiring is not described here; at
> `20abffd` only the offline audit uses `film_scene`.

## In one paragraph

Before `20abffd`, a picture refused by quality control bought its own replacement: the stills
gate's refusal bought up to two re-rolls, clip QC's refusal bought one retry, and nobody checked
whether the refusal itself was right. `second_look.second_look` (`backend/app/media/second_look.py:583`)
is the check. It shows the Director the refused picture (one still at 1080 px, or the first,
middle and last frames of a clip) with quality control's own sentences, the scene's intent
(narration, the scriptwriter's picture, the serial's beat, the plan, the bible's rules) and her
own earlier looks at the scene. She answers through one LLM call (`_look`, `:653`; the call at
`:720`) on her seeing model: CONFIRMED (the refusal is right and the scene must be made again)
or OVERTURNED (the defect is not there, or it is minor and the picture can be used). The answer
schema `SecondLook` (`:88-135`) checks only that the answer is consistent. Code decides which
refusals she may see: never a face where the bible forbids faces, writing, panels, a degenerate
picture, an unmeasured check or a compose-locally verdict (`fix_check.HARD_LIMITS`,
`backend/app/media/fix_check.py:130`; `still_gate.may_be_overturned`,
`backend/app/media/still_gate.py:1118`; `qc.look_may_overturn`, `backend/app/media/qc.py:2588`).
Within that set her OVERTURNED is final. The still is set APPROVED with
`approved_by = "director_look"` (`backend/app/media/stills_stage.py:1017-1035`), or the clip
is kept as ACCEPTED_BY_LOOK (`backend/app/media/qc.py:2671-2683`), and no re-roll or retry is
bought for it; no code re-checks her verdict against the picture. A CONFIRMED verdict changes
nothing that is bought; her reason is only added to the step's text or entry. Any failure (no Director, no seeing model, no registry, no picture, a blocked
run, two invalid answers, any exception) gives UNAVAILABLE and the refusal stands as before
(`second_look.py:571-580`). Every call of `second_look` writes one `media.director_second_look`
event, and a real verdict also becomes her AGENT_OPINION memory (`_record`, `:515-568`). The
module buys nothing.

## Why it exists

| When | Incident or Owner rule | What it produced | Source |
|---|---|---|---|
| 2026-10-10, 20:06 | babcf272 scene 5: the stills gate refused every candidate of her REPAIR on a local reading (a night sky read as a band between panels), and her decision waited for the Owner's look. The Owner: «Directorul ce face? El ar trebui să hotărască dacă poza este bună sau nu.» | Her first look, limited to the candidates of her film REPAIR (`director_qc.record_look`, `reviews.review_bought_pictures`); the second look follows its model choice and prompt style | `backend/app/media/director_qc.py:1826-1834`, `backend/app/media/second_look.py:8-9`, `:30-33` |
| 2026-10-12, 16:47 | 19.50 USD of RunPod in one day, 11.05 USD of it on redos (Higgs-2 3.90, serial 2.20, cyclotron 4.95), and all three films still failed QC. The Owner stopped the studio | The redo spend this look is meant to cut | `docs/project/CURRENT_STATUS.md:41`, `backend/app/media/second_look.py:3-5` |
| 2026-10-12, 16:55 (the Owner's card) | «Directoarea acceptă defectele mici, dar trebuie să înțeleagă de ce apar…» | OVERTURNED also covers a real but minor defect; the prompt tells her the Owner accepts small defects | `docs/project/CURRENT_STATUS.md:41`, `backend/app/media/second_look.py:18-19`, `:150-152` |
| 2026-10-12, same afternoon | The refusals behind the redos were readings, read on the database copy: 42 stills refused by the stills gate (YuNet faces on 1c038a99's faceless bible, «lettering» on f06808c9 scene 4's ledger), 3 clips by clip QC, 17 film scenes by the film's picture checks (f06808c9 scene 7: «a small sketched mark…») | The look's purpose: check the refusal before money follows it | `backend/app/media/second_look.py:3-10` |
| 2026-10-12 | The Owner: «trece imaginile picate de la QC pe la Directoare și să decidă dacă au picat corect sau nu și dacă trebuie refăcute», and the standing rule «LLM-ul este pe abonament! NU COSTĂ BANI SĂ TRECEM PE LA EI! GENERAREA DE IMAGINI ȘI MIȘCĂRI COSTĂ!» | `second_look`; the look before every still re-roll and every clip retry | `backend/app/media/second_look.py:10-16`, `backend/app/media/fix_check.py:40-43`, `backend/app/media/stills_stage.py:977-984`, `backend/app/media/qc.py:2646-2652` |
| 2026-10-12 | The Owner: «LLM-urile pot raționa, pot lua decizii și pot hotărî!» | Code gathers the evidence and records the verdict; it validates consistency only | `backend/app/media/second_look.py:24-28` |
| 2026-10-12 | The Owner: hard-coded rules stay only where money or the bible's hard limits are at stake | `HARD_LIMITS` = faces, readable_text, panels, degenerate: never shown to her | `backend/app/media/fix_check.py:127-130` |
| 2026-10-12 | The Owner: «pornește agenți care să testeze: vreau să treci imaginile picate de la QC pe la Directoare…» | `scripts/qc_audit.py`: her look at every refusal of a day, on a copy of the database | `scripts/qc_audit.py:1-15` |

Not recorded elsewhere: at `20abffd` neither `docs/project/16_DECISION_LOG.md` nor
`docs/project/CURRENT_STATUS.md` mentions the second look (a search for "second look",
"second_look" and "a doua privire" finds nothing), and no document in `docs/architecture/`
names it. The Owner's words exist only in the code's docstrings.

## Who decides here

Vocabulary: LLM, LLM_CHECKED_BY_CODE, CODE_RULE, OWNER, CONFIG, EXTERNAL (see the group brief).

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| Which refused still candidates she may be shown | CODE_RULE | `backend/app/media/still_gate.py:1118-1130`, `backend/app/media/fix_check.py:127-130` | The report is BLOCKED, carries at least one violation code, has nothing unmeasured (no blocking NOT_RUN check — a NOT_RUN local check blocks only in PRODUCTION, `backend/app/media/still_gate.py:590-598`, `:950-954` — and no missing vision answer), has no code in `HARD_LIMITS` {faces, readable_text, panels, degenerate}, and its outcome is not compose_locally. Left to her: `sharpness` and `motion_blur` (local measurements, `backend/app/media/still_gate.py:701-766`, `:950-952`) and `plan`, `scene`, `look`, `technical`, `bible`, `finding_persists` (the vision model's answers, `:999-1043`) |
| When the stills step asks her | CODE_RULE | `backend/app/media/stills_stage.py:1126-1149`, `:1250-1260` | Only when no candidate of the round passed. In `_settle_round`, only when `round_step` says reroll, rewrite or needs_owner (not compose_locally, not a round with no candidate, `:1135-1141`). In `_settle_pending`, whenever every collected candidate was refused |
| Order and number of still looks | CODE_RULE | `backend/app/media/stills_stage.py:1050-1077` | Fewest violations first, then fewest reasons; one look per candidate; the loop stops at the first look that lets a candidate stand |
| Which refused clips she may be shown | CODE_RULE | `backend/app/media/qc.py:2588-2606` | Not passed, nothing unmeasured, not `back_to_still`; at least one blocking FAILED check, and neither `faces` nor `panels` among them; the vision flags show no `readable_text`, `one_picture` not false, and no `faces_visible` where the faces check applies (status not NOT_APPLICABLE). Left to her: `motion` (the measured floor), `cuts`, and `picture` (plan, look, technical, same_shot, bible, a persisting finding; `backend/app/media/qc.py:2009-2075`) |
| When the clip look is asked | CODE_RULE | `backend/app/media/qc.py:2655-2671`, `:2734-2738`, `:2515-2553` | After the first check fails and is not BACK_TO_STILL: before the retry is bought and also before an ESCALATE (over the cap, no retry allowed, or a corrected mistake repeated on a clip that shows its plan, which goes to her rewrite). Again after a failed retry, unless that one is BACK_TO_STILL. Each time only where `look_may_overturn` allows (`:2616-2623`) |
| Whether a look can happen at all | CODE_RULE + OWNER + CONFIG | `backend/app/media/fix_check.py:659-666`, `:735-741`, `backend/app/media/second_look.py:682-702`, `backend/app/agents/services.py:608-679`, `:779-781`, `:819-831` | A registry; for a clip, at least one frame cut by `shot_second_look`; an ACTIVE employee in the role Director (`agent_for_role`, `backend/app/agents/memory.py:161-168`); a seeing model; at least one picture prepared; and the policy kernel: the Owner's autonomy stop and mode, lifecycle, model availability, the Director not busy with a live run, provider health, the daily token ceiling and USD budget (OWNER policy and settings) |
| Which model looks | CODE_RULE over the Owner's model configuration | `backend/app/agents/vision.py:162-185`, `backend/app/media/picture_qc.py:119` | Her primary, secondary, then tertiary model, the first that is VISION-capable and available. Else the primary model of the seeing employee `vision_agent` picks (VideoEditor, Director, QualityAssurance first, else the earliest hired), only if that model is available. The run stays hers. In the live configuration recorded by the map her own `kimi-k3` sees, and it is also the model of Kael, the Video Editor, whose `judge_still` and `judge_clip` made the refusal (`docs/project/backend_map/LLM_ROUTING.md:92`, `:97`) |
| CONFIRMED or OVERTURNED, severity, redo, reason | LLM | `backend/app/media/second_look.py:720-760` | Only consistency is validated (`SecondLook._consistent`, `:114-135`). What she sees, and whether the defect is minor, is hers |
| Whether her look lets the take stand | LLM (code maps her verdict; it limited beforehand which refusals she sees) | `backend/app/media/fix_check.py:693-703` | OVERTURNED with severity none or minor; or CONFIRMED, minor, redo false. The second branch cannot occur (Oddities 1) and OVERTURNED is never serious, so `look_accepts` is `verdict == OVERTURNED`: her word alone, not checked against the picture by any code |
| Approving the still the gate refused | LLM (code carries out her OVERTURNED) | `backend/app/media/stills_stage.py:1017-1035`, `:1145-1148`, `:1258-1260` | SceneTake set APPROVED, `approved_by` "director_look", failure code and detail cleared, quality synced as accepted with her reason (≤ 4000 chars). Then a take note, and the rewrite's lessons are confirmed if every `must_fix` item is gone (`:1080-1107`, `backend/app/media/fix_check.py:536-560`) |
| Keeping the clip clip QC refused (no retry bought, no escalation) | LLM (code carries out her OVERTURNED) | `backend/app/media/qc.py:2671-2683`, `:2738-2751`, `backend/app/media/assembler.py:10361-10401`, `:10454-10460`, `:5211-5216` | ACCEPTED_BY_LOOK. The last report's record is set to PASSED with `accepted_by` "director_look" and her look; the take stays PAID; `clip_accepted` reads the PASSED record as accepted |
| What a confirmation does | CODE_RULE | `backend/app/media/stills_stage.py:1075-1076`, `:1160-1184`, `:1691-1693`, `:2388-2390`, `backend/app/media/assembler.py:16586-16587`, `backend/app/media/qc.py:2609-2613` | Nothing changes. The re-roll, retry, rewrite or hold is what the code had decided. Her reason is added to the outcome's text («Directoarea a privit și confirmă refuzul: …») of a hold or a clip outcome, and stored as `director_confirmed` on a still entry; `_settle_pending` drops it (only the event keeps it) |
| UNAVAILABLE | CODE_RULE | `backend/app/media/second_look.py:571-580`, `backend/app/media/fix_check.py:632-639` | `redo` True, severity none: the refusal stands exactly as before the look existed |
| Normalising an answer from the shared contract | CODE_RULE | `backend/app/media/fix_check.py:681-690` | Unknown verdict → UNAVAILABLE; unknown severity → serious; missing `redo` → true unless OVERTURNED; reason cut to 500 chars |
| Which frames show a film scene (audit only at `20abffd`) | CODE_RULE | `backend/app/media/second_look.py:438-475` | The scene's caption-free shot (sha256-verified by `clean_shots`) → the bought clip (sha256 matches) → the film's frames by the numbers QC recorded, else by the render's timeline span → the still take (sha256 matches) → nothing |
| Recording | CODE_RULE | `backend/app/media/second_look.py:515-568` | One `media.director_second_look` event per call of `second_look`; an AGENT_OPINION memory when a Director exists and she gave a verdict |

## LLM involvement

One call site in this group: **`app.media.second_look._look`**
(`backend/app/media/second_look.py:653`, the gateway call `structured_run` at `:720`).

- **Speaker.** The Director (`agent_for_role(session, "Director")`, `:682`; Sarah in the live
  studio, `docs/project/backend_map/LLM_ROUTING.md:92`). The model is
  `seeing_model(session, director_id, *LOOKERS)` (`:686`, `backend/app/agents/vision.py:162-185`):
  her own model or slot when it sees, else a LOOKERS employee's model (the Video Editor first,
  `backend/app/media/picture_qc.py:119`). `run_agent_task` records the run as hers, with the
  model that answered (`backend/app/agents/services.py:759-762`, `:810-825`).
- **Task type.** `director_second_look`, template `director-second-look-v1`
  (`backend/app/media/second_look.py:68-69`). A second attempt carries the suffix `+again`
  (her refused answer's errors quoted) or `+think` (native thinking when no object could be
  read) (`backend/app/agents/structured.py:109-119`, `:56-57`).
- **When.** Live: before a still re-roll, a rewrite or a needs_owner hold in every round the
  stills gate refused whole, through `stills_stage._director_looks`
  (`backend/app/media/stills_stage.py:1038`). This covers the per-request stills step
  (`:2371`), the RunPod rounds (`:1674`), the paid still redo (`backend/app/media/assembler.py:16571`)
  and candidates collected after their step (`backend/app/media/stills_stage.py:1255`). Also
  before a clip retry or a clip ESCALATE, through `assembler._check_shot`'s `look`
  (`backend/app/media/assembler.py:10334-10346`). Offline: for every refusal of a day in
  `scripts/qc_audit.py:542`.
- **What it asks.** `_SECOND_LOOK_INSTRUCTIONS` (`backend/app/media/second_look.py:138-165`)
  tells her that QC's checks are measurements and readings, and that readings can be wrong (a
  face counter taking a shadow or a statue for a face, a band reader taking a night sky for a
  band, a vision model calling a texture lettering). It asks her to say what she actually
  sees, then decide. It defines a serious defect: the picture misses the scene's subject or the
  narration; a face where the bible forbids faces; readable or garbled writing; panels, a
  collage or a blank band; a deformed person; for a clip, a broken, melting or frozen picture.
  Attached: one still, or three frames in order (`_LAYOUT`, `:171-179`; for a film scene, a note
  that the subtitles are the studio's own). Inside `wrap_in_inert_boundary(…, "second-look")`
  (`:716-718`) is the JSON `shown` (`:703-713`), cut at 12 000 chars:
  - `refused_by`: the stills gate, the clip QC or the film's quality control;
  - `refusal`: QC's own sentences, at most 12, each at most 400 chars (`:509-512`, `:78-79`);
  - `scene`: `scene_intent` (`:211-301`): film title, serial or not, scene kind, narration
    (≤ 600), purpose (≤ 200), the scriptwriter's picture (`visual_description`, else the
    package's `writer_visual`, else `visual_prompt` when it differs from the still prompt; ≤
    600); for the serial the beat (part, location, who is in frame, action, up to 6 lines,
    background); the plan (still prompt ≤ 900, motion prompt ≤ 500, camera move, look ≤ 400);
    the bible (faces forbidden by `bible_face_rule`, up to 12 rules from
    `stills_stage._bible_rules`, up to 12 avoid items);
  - `your_earlier_looks`: her last 3 non-UNAVAILABLE looks at this scene of this storyboard,
    any kind (`:304-328`).

  Her identity, memories included, is the system prompt (`backend/app/agents/services.py:790`,
  `backend/app/agents/identity.py:287`).
- **Pictures.** `_prepared` (`backend/app/media/second_look.py:478-503`): each still or frame
  as a base64 JPEG scaled to 1080 px (`picture_qc.still_image`,
  `backend/app/media/picture_qc.py:1709`, `:1420`; files over 40 MB are skipped, `:1422`). A
  video path is cut into its first, middle and last frame (`frames_of`,
  `backend/app/media/second_look.py:341-364`, through `qc.clip_frames`,
  `backend/app/media/qc.py:1897`). A string longer than 256 chars made only of base64
  characters is sent as it is. At most `MAX_IMAGES` = 6 (`backend/app/media/second_look.py:76`).
  They travel in `extra={"images": …}` (`:732`).
- **Answer shape.** `SecondLook` (`:88-135`), extra keys ignored:
  `verdict` ∈ {CONFIRMED, OVERTURNED} (upper-cased first, `:104-107`); `severity` ∈ {none,
  minor, serious} (lower-cased first, `:109-112`); `redo: bool`; `reason_ro` 1–600 chars,
  clipped rather than refused (`:101-102`, `backend/app/agents/identity.py:377-389`). The
  consistency validator `_consistent` (`backend/app/media/second_look.py:114-135`) refuses
  four shapes, each with a sentence that `structured_run` quotes back to her on the second
  attempt:
  1. serious but not CONFIRMED;
  2. OVERTURNED with `redo` true;
  3. CONFIRMED with `redo` false;
  4. CONFIRMED with severity none.

  So the valid answers are OVERTURNED/none/false, OVERTURNED/minor/false,
  CONFIRMED/minor/true and CONFIRMED/serious/true.
- **Token budget and sampling.** `max_tokens` 2000 (`backend/app/media/second_look.py:731`),
  multiplied for the Director by `director_token_multiplier` (CONFIG, default 2, range 1–4;
  `backend/app/config.py:11`, `:425`; `backend/app/agents/services.py:793-798`), so 4000 by
  default. Temperature 0.1 (`backend/app/agents/structured.py:89`). The first attempt asks for
  JSON (`{"format": "json"}`, `:48`, `:133`). At most two attempts. The second comes only after
  a SUCCEEDED run whose text did not validate; a failed, blocked or empty run is not retried
  (`:109-154`, `:138-140`).
- **Use of the answer — trust: FINAL** within the refusals code lets her see. The content is
  not checked by code. OVERTURNED (always none or minor) passes `fix_check.look_accepts`, and
  the still is APPROVED by her or the clip is kept as hers; nothing is bought for that refusal.
  CONFIRMED (always `redo` true) fails `look_accepts`; the purchase or hold the code had already
  chosen goes ahead with her reason in its text. Severity has no effect on what happens
  (Oddities 1). Either verdict is written as an event and as her memory, and is shown to her
  in the next look at the scene.
- **If the model fails, refuses or returns junk.** `parsed` is None. `_look` names why: a
  structured blocker in her text (`blocker_of`, `backend/app/agents/identity.py:659-662`), «not
  the required shape a second time» when the run SUCCEEDED, or the run's status or error
  detail (`backend/app/media/second_look.py:743-752`). A `PolicyKernelError` raised by
  `run_agent_task` (a slot model unavailable or lacking a capability,
  `backend/app/agents/services.py:819-824`) gives UNAVAILABLE with the block reason
  (`backend/app/media/second_look.py:735-740`). Kernel blocks recorded as runs (autonomy stop,
  mode, Director busy, token ceiling, budget, provider health; `backend/app/agents/services.py:827-856`)
  come back as non-SUCCEEDED runs and also give UNAVAILABLE. Any other exception is caught in
  `second_look` (`backend/app/media/second_look.py:635-637`). UNAVAILABLE carries `redo` True:
  the refusal stands and the code's purchase or hold goes ahead unchanged. An event is still
  written, with the Romanian why; no memory is written.
- **Can it lead to spending money? Indirectly, yes; directly, no.** The module buys nothing,
  and CONFIRMED or UNAVAILABLE leave the money path exactly as it was. OVERTURNED withholds a
  re-roll (`backend/app/media/stills_stage.py:1163-1170`) or a clip retry
  (`backend/app/media/qc.py:2696-2697`). But an approved still is what the scene's motion is
  bought on (`backend/app/media/still_gate.py:141-142`; the RunPod rounds even send the rest of
  the film once scene 1 has its still, `backend/app/media/stills_stage.py:1709-1715`). So when
  the look replaces a needs_owner hold (after `MAX_REROLLS` = 2, `backend/app/media/still_gate.py:1190-1195`)
  or a rewrite, her OVERTURNED moves the scene on to its paid motion step without the Owner's
  look or the rewrite ladder. That motion is then bought under its own step's plan, cap and
  policy gates. A kept clip likewise goes into the film instead of waiting for the Owner
  (`backend/app/media/assembler.py:10425-10460`). The look itself spends LLM tokens under the
  daily ceiling and USD budget of `run_agent_task`; the Owner treats these model calls as
  subscription, not credits (`backend/app/media/second_look.py:11-13`).

### Functions that reach the LLM (statically or through a callback)

| Function | Through | Notes |
|---|---|---|
| `app.media.second_look.second_look` (`backend/app/media/second_look.py:583`) | `_look` | Never raises; always records (`:614-650`) |
| `app.media.fix_check.director_second_look` (`backend/app/media/fix_check.py:642`) | `second_look` (lazy import, `:663-666`) | `llm_distance` 4 in the inventory |
| `app.media.fix_check.shot_second_look` (`backend/app/media/fix_check.py:713`) | `director_second_look` | Cuts the clip's frames into its own temporary folder, removed afterwards (`:737-754`) |
| `app.media.stills_stage._director_looks` (`backend/app/media/stills_stage.py:1038`) | `fix_check.director_second_look` | One model run (up to two attempts) per offered candidate |
| `app.media.stills_stage._settle_round` / `_settle_pending` / `_StillRounds._settled`, `run_stills_stage`, `settle_stills`, `assembler._StillRedoBuyer.run` | `_director_looks` | Static paths (`docs/project/backend_map/inventory.json`) |
| `app.media.qc.qc_clip_with_retry` (`backend/app/media/qc.py:2626`) | the `look` callback | Invisible to static analysis (`llm_distance` None); bound in `assembler._check_shot` (`backend/app/media/assembler.py:10334-10359`) |
| `app.media.assembler._check_shot` (`backend/app/media/assembler.py:10245`) and its callers `check_unchecked_shots` (`:10821`), `_ShotRounds._check` (`:11209`), `run_motion_step` (`:11426`) | `fix_check.shot_second_look` (and `picture_qc.judge_clip`) | |
| `scripts/qc_audit.py` `audit` (`scripts/qc_audit.py:506`) | `second_look` | Outside `backend/app`, not in the inventory |

### How much is LLM and how much is rule

- 1 of the module's 16 functions is a call site. `_look` holds 111 of the 553 function lines
  (20 %); with `second_look` (68 lines), which reaches it, 179 lines (32 %) reach a model
  (`docs/project/backend_map/inventory.json`, module `app.media.second_look`). The other 14
  functions gather evidence (scene intent, earlier looks, frames, sha256 checks), prepare
  pictures and record.
- The model answers one content question, whether QC's refusal is right. Code decides which
  refusals she may see, how her verdict is carried out, and that anything going wrong leaves
  the old behaviour in place. The integration functions in `fix_check`, `still_gate`,
  `stills_stage`, `qc` and `assembler` contain no model call of their own for the look.
- Asymmetry: her OVERTURNED overrides a refusal QC made (in part a deterministic measurement:
  sharpness, motion blur, the clip's motion floor and cuts). Her CONFIRMED adds nothing to what
  code already does.

## Hard rules and limits

| Constant / rule | Value | Where |
|---|---|---|
| `SECOND_LOOK_EVENT` | `media.director_second_look` (aggregate `storyboard`) | `backend/app/media/second_look.py:67`, `:532-537` |
| `SECOND_LOOK_TASK`, `SECOND_LOOK_TEMPLATE_VERSION` | `director_second_look`, `director-second-look-v1` | `:68-69` |
| `KINDS` | still, shot, film_scene; any other kind raises inside the try and becomes UNAVAILABLE | `:71`, `:621-622` |
| Verdicts | CONFIRMED, OVERTURNED, UNAVAILABLE (the last given only by code) | `:73`, `backend/app/media/fix_check.py:132` |
| `SEVERITIES` | none, minor, serious (declared; the schema's `Literal` is what validates) | `backend/app/media/second_look.py:74`, `:99` |
| `MAX_IMAGES` | 6 pictures per look | `:76`, `:501-503` |
| `MAX_REFUSALS`, `REFUSAL_CHARS` | 12 sentences, 400 chars each | `:78-79`, `:509-512` |
| `EARLIER_LOOKS_SHOWN` | 3 (UNAVAILABLE looks skipped) | `:81`, `:316`, `:328` |
| Data JSON cut | 12 000 chars | `:717` |
| Title in the prompt / summary | 80 / 60 chars | `:715`, `:730` |
| `reason_ro` | 1–600 chars, clipped; 500 after `director_second_look`; ≤ 600 in UNAVAILABLE | `:101-102`, `backend/app/media/fix_check.py:688`, `backend/app/media/second_look.py:578` |
| Memory content | ≤ 2000 chars | `:562` |
| `VIDEO_SUFFIXES` | .mp4 .mov .webm .mkv .m4v: a video is shown as three frames whatever the look's kind | `:82`, `:360-364` |
| Prepared-picture recognition | > 256 chars and only `[A-Za-z0-9+/=\s]` | `:85`, `:499-500` |
| Frame folder | `<tmp>/amn_second_look/<sha256(key)[:16]>` unless a `work_dir` is given | `:334-338` |
| `HARD_LIMITS` (stills) | faces, readable_text, panels, degenerate | `backend/app/media/fix_check.py:130` |
| Clip hard limits | failed `faces` or `panels`; flags `readable_text`, `one_picture` false, `faces_visible` where faces are checked | `backend/app/media/qc.py:2597-2606` |
| `DIRECTOR_LOOK_APPROVER` | `director_look` (distinct from the Owner's `owner` and her repair look's `director`) | `backend/app/media/fix_check.py:126`, `backend/app/media/director_qc.py:112`, `:137` |
| `ACCEPTED_BY_LOOK` | clip QC outcome status | `backend/app/media/qc.py:2585` |
| Still re-rolls the look stands before | `MAX_REROLLS` = 2, `PERSISTS_REROLLS` = 1 | `backend/app/media/still_gate.py:196`, `:199` |
| Effective tokens | 2000 × `director_token_multiplier` (default 2) | `backend/app/media/second_look.py:731`, `backend/app/config.py:425` |

States: `second_look` returns a verdict and writes no state of its own beyond the event and the
memory. The take changes are made by the callers: still `REJECTED` (written by `_set_verdicts`
before the look, `backend/app/media/stills_stage.py:965-968`) → `APPROVED` / `director_look`
(`:1026-1029`); clip `PAID` stays `PAID` with a PASSED clip-QC record instead of becoming
`REJECTED` (`backend/app/media/assembler.py:5161-5167`, `:10365-10373`).

## Modules

### `app.media.second_look` — `backend/app/media/second_look.py` (763 lines)

The Director's second look at a picture QC refused, before a redo is bought
(`backend/app/media/second_look.py:1-33`). Why: the redos of 2026-10-12 were bought on
readings that nobody checked, and a look costs no credits.

| Function | Line | What it does | Why it exists | Decided by |
|---|---:|---|---|---|
| `SecondLook` (class) | 88 | Her answer: `verdict`, `severity`, `redo`, `reason_ro`; extra keys ignored | The shared contract every caller reads | LLM (shape only) |
| `SecondLook._clip_reason` | 102 | Before-validator: `reason_ro` cut to 600 chars (`clipped`) | A long reason never discards the look | CODE_RULE |
| `SecondLook._upper` | 106 | Upper-cases a string verdict before validation | «confirmed» counts | CODE_RULE |
| `SecondLook._lower` | 111 | Lower-cases a string severity | «Minor» counts | CODE_RULE |
| `SecondLook._consistent` | 115 | Refuses serious-not-CONFIRMED, OVERTURNED-with-redo, CONFIRMED-without-redo, CONFIRMED-with-none | «a serious defect is never waved through, an overturned refusal never buys» (`:25-27`) | CODE_RULE (consistency) |
| `_short` | 206 | Collapses whitespace, cuts at `limit` with «…» | Bounded prompt fields | CODE_RULE |
| `scene_intent` | 211 | Reads the storyboard, the scene row, the script entry and the bible into the scene's intent (see LLM involvement); a missing board gives only the index | She reads QC's words beside what the scene is meant to show; the scriptwriter's line, not the compiled prompt (overwritten 2026-10-12, `:214-217`) | CODE_RULE (read-only) |
| `earlier_looks` | 304 | Her non-UNAVAILABLE looks at this scene of the storyboard, oldest to newest, last 3 | So she stays consistent | CODE_RULE |
| `_work_dir` | 334 | Frame folder by sha256 of a key | Stable, separate folders per file | CODE_RULE |
| `frames_of` | 341 | A picture as it is; a video's first, middle and last frame (1080 px PNG, `qc.clip_frames`); empty when the file is missing or no encoder | Shown as QC cut it; empty means «not looked at», never a pass | CODE_RULE |
| `_file_sha256` | 367 | sha256 of a file in 1 MiB chunks, None on OSError | A take shown must be the one bought | CODE_RULE |
| `film_scene_frames` | 378 | A finished film's scene as frames: SHOT → CLIP → FILM → STILL, each verified (see Who decides); `([], None)` when nothing can be prepared | Her look at a film-QC finding (the audit; her REPAIR after `d4335c6`) | CODE_RULE |
| `_prepared` | 478 | Turns paths into base64 JPEGs at 1080 px, keeps prepared base64 as it is, ≤ 6 | What the seeing model is sent | CODE_RULE |
| `_refusal` | 509 | QC's sentences, non-empty, ≤ 12 × 400 chars | Bounded refusal in the prompt and the event | CODE_RULE |
| `_record` | 515 | One event (storyboard, scene, kind, take ids, refusal, verdict, severity, redo, reason, run id) and, for a real verdict with a Director, her AGENT_OPINION memory with the run as source; a failure is logged, never raised | Every look is visible to the register and to her next look | CODE_RULE |
| `_unavailable` | 571 | The UNAVAILABLE outcome: severity none, `redo` True, Romanian «Directoarea nu s-a putut uita la … Refuzul controlului rămâne.» | The refusal stands as before | CODE_RULE |
| `second_look` | 583 | Public entry: normalises inputs, checks the kind, calls `_look`, catches every exception into UNAVAILABLE, records, returns the outcome | A look never stops the caller's work | CODE_RULE (wraps the LLM) |
| `_look` | 653 | Intent and history (errors tolerated), Director, seeing model, registry, pictures, prompt, `structured_run`, then outcome or UNAVAILABLE with why | **The LLM call site** | LLM |

Data read: `Storyboard`, `StoryboardScene`, `ScriptDraft`, `DomainEvent`, `MediaAsset`,
`VideoRenderJob`, `SceneTake`, files on disk. Data written: `DomainEvent`
(`media.director_second_look`), `MemoryRecord` (AGENT_OPINION), and through `run_agent_task`
an `AgentRun` row per attempt. It writes no take.

### Integration points in other files (only what concerns the look)

| Function | File:line | What it does for the look | Decided by |
|---|---|---|---|
| `HARD_LIMITS` | `backend/app/media/fix_check.py:130` | The still violations she never overturns | CODE_RULE (the Owner's rule in the comment, `:127-129`) |
| `_unavailable` | `backend/app/media/fix_check.py:632` | UNAVAILABLE outcome without calling the module | CODE_RULE |
| `director_second_look` | `backend/app/media/fix_check.py:642` | The shared entry for buyers. UNAVAILABLE without calling `second_look` when there is no registry, no image, the module is missing or it raises; otherwise calls it and normalises the answer | CODE_RULE |
| `look_accepts` | `backend/app/media/fix_check.py:693` | Whether the look lets the take stand (OVERTURNED none/minor; CONFIRMED minor without redo) | CODE_RULE over LLM |
| `look_record` | `backend/app/media/fix_check.py:706` | Her look as a step entry keeps it (five keys) | CODE_RULE |
| `shot_second_look` | `backend/app/media/fix_check.py:713` | Cuts a refused clip's three frames (`qc.clip_frames`) into a temporary folder, asks `director_second_look` with kind shot, removes the folder | CODE_RULE |
| `record_take_note` | `backend/app/media/fix_check.py:574` | Writes `media.take_quality_note` on the take: minor traces and her look when hers approved it | CODE_RULE |
| `take_note` | `backend/app/media/fix_check.py:618` | Reads the newest note of a take (read only by tests; Oddities 6) | CODE_RULE |
| `clip_settled` | `backend/app/media/fix_check.py:757` | On the clip kept: a note with `approved_by` director_look when her look kept it, else clip_qc; settles the motion rewrite's lessons | CODE_RULE |
| `may_be_overturned` | `backend/app/media/still_gate.py:1118` | Which refused still candidates she may see | CODE_RULE |
| `_RoundEnd` / `.approved` | `backend/app/media/stills_stage.py:988`, `:1002` | A round's end; an approval by her look adds `approved_by` and `director_look` to the scene's entry | CODE_RULE |
| `_approve_by_look` | `backend/app/media/stills_stage.py:1017` | The APPROVED write with `approved_by` director_look, failure cleared, quality synced | CODE_RULE (carries out LLM) |
| `_director_looks` | `backend/app/media/stills_stage.py:1038` | Offers the overturnable candidates in order, one look each, returns the first accepted or her confirmations | CODE_RULE (asks LLM) |
| `_after_approval` | `backend/app/media/stills_stage.py:1080` | Take note and lesson confirmation for an approved still, hers included | CODE_RULE |
| `_settle_round` | `backend/app/media/stills_stage.py:1110` | One judged round, the same for every buyer: the gate's best, else her look, else the next step with her confirmations in the reason | CODE_RULE |
| `_settle_pending` | `backend/app/media/stills_stage.py:1202` | Collected candidates: the gate's best, else her look; approved with 0 credits, else NOT_BOUGHT | CODE_RULE |
| `_StillRounds._settled` | `backend/app/media/stills_stage.py:1671` | RunPod rounds: `_settle_round`; confirmations added to the entry when a re-roll follows | CODE_RULE |
| `ClipQCOutcome.look` | `backend/app/media/qc.py:2581-2582` | Her look at the last refused clip | — |
| `look_may_overturn` | `backend/app/media/qc.py:2588` | Which refused clips she may see | CODE_RULE |
| `_her_words` | `backend/app/media/qc.py:2609` | «Directoarea a privit și confirmă refuzul: …» for a CONFIRMED look | CODE_RULE |
| `_looked` | `backend/app/media/qc.py:2616` | Calls the `look` callback only where `look_may_overturn` allows | CODE_RULE |
| `qc_clip_with_retry` | `backend/app/media/qc.py:2626` | Asks the look after a first refusal and after a failed retry; ACCEPTED_BY_LOOK buys nothing more | CODE_RULE |
| `_check_shot` | `backend/app/media/assembler.py:10245` | Binds `look` to `fix_check.shot_second_look` with QC's `blocks_ro` and the last checked take; marks the kept clip's record PASSED with `accepted_by` director_look; `clip_settled` with her look | CODE_RULE |
| `_StillRedoBuyer.run` | `backend/app/media/assembler.py:16364` | The paid still redo judged through `stills._settle_round` (`:16571-16588`); confirmations returned as `director_confirmed` by `_redo_still` (`:16199`) | CODE_RULE |
| `_second_look_words` | `backend/app/events_feed.py:589` | The register's sentence and bubble for the event | CODE_RULE |
| `prepare`, `audit` | `scripts/qc_audit.py:399`, `:506` | Offline: frames with `frames_of` / `film_scene_frames`, then `second_look` on a copy of the database | CODE_RULE (asks LLM) |

## Connections

### Who calls into this group

| Caller | Calls | Where |
|---|---|---|
| Stills step, per-request path (`run_stills_stage`) | `_settle_round` → `_director_looks` → `fix_check.director_second_look` (kind still) | `backend/app/media/stills_stage.py:2371-2392`, `:1056-1066` |
| Stills step, RunPod rounds (`_StillRounds`) | `_settled` → `_settle_round` | `backend/app/media/stills_stage.py:1674-1696` |
| Candidates collected after their step (`settle_stills`, `run_stills_stage`) | `_settle_pending` → `_director_looks` | `backend/app/media/stills_stage.py:1326`, `:2106`, `:1255-1260` |
| Paid still redo (`assembler._redo_still` → `_StillRedoBuyer.run`) | `stills._settle_round` | `backend/app/media/assembler.py:16571-16588` |
| Motion step, per-request purchase (`run_motion_step`) | `_check_shot` with a real `buy_retry` | `backend/app/media/assembler.py:12284-12304` |
| Motion step, RunPod rounds (`_ShotRounds._check`) | `_check_shot` with `defer` (the retry is bought in the next batch round, only if the look did not keep the clip) | `backend/app/media/assembler.py:11209-11240` |
| Unchecked paid shots (`check_unchecked_shots`, from `run_motion_step` and the shooting sheet) | `_check_shot` with cap 0 (no retry is ever bought; the look replaces the Owner's wait) | `backend/app/media/assembler.py:10875-10898`, `:11561-11572`, `backend/app/media/shooting_sheet.py:3176` |
| Offline audit | `frames_of`, `film_scene_frames`, `_file_sha256`, `second_look` | `scripts/qc_audit.py:404-430`, `:519-556` |
| Tests at `20abffd` | the module and its wiring | `tests/test_second_look.py:202-436`, `tests/test_fix_is_verified.py:1563-1795`, `tests/test_qc_audit.py:184-258`, `tests/test_events_feed.py:1270` |

### What it calls out to

`app.agents.memory.agent_for_role` and `remember` (`backend/app/agents/memory.py:161`, `:42`);
`app.agents.vision.seeing_model` (`backend/app/agents/vision.py:162`) and `frames_at` (`:55`);
`app.agents.structured.structured_run` (`backend/app/agents/structured.py:76`) →
`app.agents.services.run_agent_task` (`backend/app/agents/services.py:733`), `PolicyKernelError`
(`:511`); `app.agents.identity.blocker_of` and `clipped` (`backend/app/agents/identity.py:659`,
`:377`); `app.factual.sanitizer.wrap_in_inert_boundary` (`backend/app/factual/sanitizer.py:104`);
`app.media.picture_qc` `LOOKERS`, `still_image`, `clean_shots` (`backend/app/media/picture_qc.py:119`,
`:1709`, `:380`); `app.media.qc` `clip_frames`, `timeline_spans`, `span_frame_numbers`,
`DEFAULT_TIMELINE_FPS` (`backend/app/media/qc.py:1897`, `:3124`, `:3310`, `:1568`);
`app.media.toolchain.find_ffmpeg` (`backend/app/media/toolchain.py:87`);
`app.media.prompt_lint.bible_face_rule` (`backend/app/media/prompt_lint.py:617`);
`app.media.stills_stage._bible_rules` (`backend/app/media/stills_stage.py:768`);
`app.agents.editorial.is_serial_film` (`backend/app/agents/editorial.py:159`);
`app.services.append_event` (`backend/app/services.py:62`). No provider adapter, no media
vendor, no ledger, no decision card.

### Events and records

| Record | Written by | Read by |
|---|---|---|
| `media.director_second_look` (aggregate storyboard; payload storyboard_id, scene_index, kind, take_ids, refusal, verdict, severity, redo, reason_ro, run_id) | `second_look._record` (`backend/app/media/second_look.py:532-551`) | `earlier_looks` (`:304-328`); the register: `_runs_named` attaches the run to the film (`backend/app/events_feed.py:764-765`), `_words` → `_second_look_words` (`:1180-1181`, `:589-620`); `scripts/qc_audit.py` reports (via the copy) |
| `AgentRun` (task `director_second_look`, summary «Mă uit eu la …») | `run_agent_task` via `structured_run` | the register's task names (`backend/app/events_feed.py:166`, `:201`) |
| `MemoryRecord` AGENT_OPINION («Second look at the … of scene N of “title” …: VERDICT (severity) — reason») | `_record` (`backend/app/media/second_look.py:552-566`) | her identity at every later run (`recall`, `backend/app/agents/identity.py:287`) |
| `media.take_quality_note` (aggregate scene_take) with `director_look` | `fix_check.record_take_note` (`backend/app/media/fix_check.py:592-615`) from `stills_stage._after_approval` (`backend/app/media/stills_stage.py:1093-1103`) and `fix_check.clip_settled` (`backend/app/media/fix_check.py:774-785`) | `fix_check.take_note` — tests only |
| `media.clip_qc_checked` with `verdict` PASSED, `accepted_by`, `director_look` | `assembler._keep_clip_report` (`backend/app/media/assembler.py:5175-5190`) from `_check_shot` (`:10376-10385`) | `clip_qc_of` → `clip_accepted` (`:5193`, `:5213-5216`) |
| `SceneTake` APPROVED / `director_look` | `stills_stage._approve_by_look` (`backend/app/media/stills_stage.py:1026-1035`) | the motion step and the film (any APPROVED still) |
| Step entries `director_look`, `approved_by`, `director_confirmed` | `stills_stage` (`:1009-1011`, `:1183`, `:1693`, `:2390`), `assembler._redo_still` (`backend/app/media/assembler.py:16199`) | nothing in `backend/app` reads `director_confirmed` |

The Director's other look, at the candidates bought for her film REPAIR
(`runbook.stages._director_looks`, `backend/app/runbook/stages.py:4370`, through
`reviews.review_bought_pictures`, `backend/app/agents/reviews.py:1148`), shares the name
`_director_looks` but is a different mechanism. It writes `media.director_take_look`, sets
`approved_by` "director" (`backend/app/media/director_qc.py:2146`) and writes a letter to the
Owner. It is mapped in `11_agents_reviews_repairs.md`.

## Owner touchpoints

| Touchpoint | What the Owner decides | Where |
|---|---|---|
| The rule itself | The Owner's words of 2026-10-12 set the mechanism. No setting turns it on or off: `second_look.py` reads no configuration | `backend/app/media/second_look.py:10-16` |
| The Director's model slots | Whether she looks with her own model (primary, secondary or tertiary slot, as the Owner configured them) or borrows the Video Editor's | `backend/app/agents/vision.py:165-185` |
| Policy kernel: autonomy stop, autonomy mode, daily token ceiling, USD budget | A blocked run makes the look UNAVAILABLE; the purchase or hold goes on as before the look existed | `backend/app/agents/services.py:619-632`, `:779-830` |
| The needs_owner wait | After two re-rolls, and for a clip with no retry within the cap (or never checked), her OVERTURNED settles what the Owner would otherwise decide on the shooting sheet | `backend/app/media/stills_stage.py:1143-1148`, `backend/app/media/still_gate.py:1190-1195`, `backend/app/media/qc.py:2670-2683`, `backend/app/media/assembler.py:10425-10445` |
| Shooting sheet approvals | A still approved by her look carries `approved_by` director_look, not owner, so it is not protected as the Owner's own approval (`owner_approved_take_ids` reads `approved_by` owner) | `backend/app/media/director_qc.py:518-534` |
| What the Owner reads | The register: «Sarah s-a uitat la imaginea scenei N din «…»: refuzul controlului e greșit — se acceptă, nu se reface (…)», or «… nu s-a putut uita … refuzul controlului rămâne»; the run's Romanian summary; her reason in the step outcome («Directoarea a privit și confirmă refuzul: …», «… îl păstrează …»). No letter or message is written for a second look | `backend/app/events_feed.py:589-620`, `backend/app/media/second_look.py:187-200`, `backend/app/agents/services.py:807-808`, `backend/app/media/stills_stage.py:1160-1162`, `backend/app/media/qc.py:2609-2613`, `:2679-2680` |
| The audit | Run by hand; asks the Director's seeing model on a copy of the database; Romanian Markdown table and JSON in the work folder, with the credits of redos bought that day for refusals she overturned | `scripts/qc_audit.py:30-36`, `:573-594`, `:673-695` |

## Oddities and gaps

1. **Severity and `redo` never change what happens; only the verdict does.** `look_accepts`
   also accepts CONFIRMED + minor + `redo` false (`backend/app/media/fix_check.py:703`), and the
   register has sentences for CONFIRMED without redo and OVERTURNED with redo
   (`backend/app/events_feed.py:610-614`). The schema refuses both shapes
   (`backend/app/media/second_look.py:121-130`) and `_unavailable` never says CONFIRMED
   (`:571-580`), so these branches are reached only by fakes in tests. Because OVERTURNED is
   never serious (`:116-120`), `look_accepts(look)` is the same as `verdict == OVERTURNED`.
2. **The film repair named in the docstring is not wired at `20abffd`.** The module says the
   look comes before «her own film repair is bought» (`backend/app/media/second_look.py:14`),
   and it has a `film_scene` kind with its own frame source (`:378-475`). No backend caller
   passes `film_scene`; only `scripts/qc_audit.py:542` does. The stills bought for her repair
   are looked at, because the paid still redo uses `_settle_round`
   (`backend/app/media/assembler.py:16571`), but the film-QC refusal that triggers the repair
   is not. The wiring arrived in `d4335c6`.
3. **"Every look writes one event" holds only when `second_look` is reached.**
   `fix_check.director_second_look` returns UNAVAILABLE without calling it when there is no
   registry, no image, no module, or it raises (`backend/app/media/fix_check.py:659-666`,
   `:679-680`). `shot_second_look` does the same without a registry or when no frame can be cut
   (`:735-748`). In those cases nothing is recorded and the refusal stands silently, against
   `backend/app/media/second_look.py:30` and `:612-613`. Inside `_record`, the event and the
   memory share one transaction, so a failing `remember` rolls back the event too; this is only
   logged (`:530-568`).
4. **A busy or capped Director lets the money go.** A kernel block (autonomy stop, the Director
   THINKING on another live run, token ceiling, USD budget, provider health;
   `backend/app/agents/services.py:619-656`, `:827-856`) becomes UNAVAILABLE, and the re-roll
   or retry is bought as before (`backend/app/media/second_look.py:743-752`). The look is best
   effort; nothing waits or retries for it.
5. **Measurements are overturned from pictures that cannot show them.** `may_be_overturned`
   leaves the local `sharpness` and `motion_blur` measurements to her
   (`backend/app/media/still_gate.py:1124-1130`; they are measured codes, `:701-766`).
   `look_may_overturn` leaves the measured `motion` floor and `cuts` to her
   (`backend/app/media/qc.py:2596-2597`). For a clip she sees three still frames
   (`backend/app/media/fix_check.py:739-741`), which cannot show how much the camera moved or
   whether there is a cut. The docstrings call all of these "a reading"
   (`backend/app/media/still_gate.py:1119-1123`, `backend/app/media/qc.py:2589-2593`).
6. **The take note nobody reads.** `TAKE_NOTE_EVENT` is documented as read by the film QC's
   context «so the same small trace is not refused again after the money»
   (`backend/app/media/fix_check.py:121-124`). At `20abffd`, `take_note`
   (`:618-626`) is called only by tests (`tests/test_fix_is_verified.py:1063`, `:1592`,
   `:1741`). After her look approves a still, the finished film's picture QC is not told and
   can refuse the same thing again after the clip is bought.
7. **Her confirmations are stored but unused.** `director_confirmed`
   (`backend/app/media/stills_stage.py:1183`, `:1693`, `:2390`;
   `backend/app/media/assembler.py:16199`) is read by nothing in `backend/app`. A confirmed
   refusal's re-roll uses the fixed phrases of the violation codes
   (`backend/app/media/stills_stage.py:1163-1170`), and the clip retry's prompt does not include
   her reason (`backend/app/media/qc.py:2696`). What she saw does not reach the next purchase.
8. **Borrowed eyes can be the same eyes.** When none of her slots sees, `seeing_model` borrows
   the Video Editor's model first (`backend/app/agents/vision.py:179-185`,
   `backend/app/media/picture_qc.py:119`). That is the employee whose model `judge_still` and
   `judge_clip` use for the refusal, so the "second look" can be the same model reading the same
   picture with a different prompt, recorded as the Director's run. In the recorded live
   configuration her own `kimi-k3` sees (`docs/project/backend_map/LLM_ROUTING.md:92`). If the
   preferred borrowed model is unavailable, `seeing_model` returns None and does not try the
   next seeing employee (`backend/app/agents/vision.py:182-184`).
9. **It can stand in for the Owner.** Her look is asked when the next step is needs_owner
   after two re-rolls (`backend/app/media/stills_stage.py:1143-1148`). It is also asked for
   unchecked shots with a cap of 0, whose docstring still says «a shot measured wrong goes to
   the Owner» (`backend/app/media/assembler.py:10821-10839`, `:10885-10888`). There her
   OVERTURNED approves or keeps the picture, the scene moves on to its paid motion step or into
   the film, and the Owner is not asked. This is the one way the look leads to spending.
10. **The audit measures a wider policy than the studio runs.** `scripts/qc_audit.py` shows her
    every refusal of the day, faces, writing and panels included. It applies neither
    `may_be_overturned` nor `look_may_overturn` (`scripts/qc_audit.py:197-245`), so its
    OVERTURNED totals and "redos bought for refusals she overturned" (`:573-594`) are not the
    live behaviour. "Offline" means the live database and media vendors are untouched. A real
    model is asked, on the provider of the Director's seeing model
    (`:131-165`); runs, events and memories go to the copy only.
11. **Not recorded in the project documents.** No ADR and no CURRENT_STATUS entry describes the
    second look at `20abffd` (see "Why it exists"), although `AGENTS.md` asks for both. One more
    place lets a model's judgement override a QC refusal (compare
    `docs/project/backend_map/LLM_VS_RULES.md:254-256`), and one more writer of APPROVED
    besides the Owner, the stills gate and her repair look (compare
    `docs/project/backend_map/subsystems/01_media_assembler_part1.md:104`).
12. Small things. The data JSON is cut at 12 000 chars and can end mid-JSON inside the
    boundary (`backend/app/media/second_look.py:717`). `SEVERITIES` is declared but not used
    (`:74`). Frames cut by `frames_of` without a `work_dir` stay under the system temp folder
    (`:334-338`; only `shot_second_look` removes its own folder,
    `backend/app/media/fix_check.py:737-754`). `earlier_looks` reads every second-look event of
    the storyboard and filters in Python (`backend/app/media/second_look.py:307-317`). With
    several refused candidates in a round, each gets its own model run (up to two attempts),
    with no cap besides the round's size (`backend/app/media/stills_stage.py:1055-1076`).
