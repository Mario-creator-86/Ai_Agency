# 06 — Media execution: stills stage, media services, factory, toolchain, GPU batching, rehearsal, unsent RunPod work, storage

> Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).
>
> Files (line counts at `20abffd`):
> `backend/app/media/stills_stage.py` (2544), `backend/app/media/services.py` (2160),
> `backend/app/media/factory.py` (1005), `backend/app/media/toolchain.py` (1162),
> `backend/app/media/gpu_batch.py` (544), `backend/app/media/rehearsal.py` (1292),
> `backend/app/media/runpod_unsent.py` (961), `backend/app/media/local_media.py` (106),
> `backend/app/media/disk.py` (126), `backend/app/media/storage.py` (55),
> `backend/app/media/models.py` (436), `backend/app/media/schemas.py` (185),
> `backend/app/media/__init__.py` (1). Total 10,577 lines, 243 functions. Of these files only
> `stills_stage.py` changed between `b00083c` and `20abffd`.

## In one paragraph

This group is where the studio actually buys and assembles pictures and sound. `stills_stage`
is the first paid stair of a film's "money staircase": it prices every LIVE scene's still,
refuses before anything is asked or bought when the plan is stale, unpriced, un-linted, the disk
is full, the balance is short or a locked character has no reference, then (only under the
Policy Kernel's `media.stills_purchase` verdict, normally the Owner's yes bound to the plan's
sha256) buys two candidates per scene, judges each one with deterministic local checks and,
when those pass, one vision-model look, and approves the best. Since `5fc7468` a round the gate
refused whole is shown to the Director before anything more is bought for it: her second look
(a vision-model call, free in credits) may approve a candidate refused only on the look's
readings, and then nothing is bought. Otherwise the scene is re-rolled at most twice, its words
are sent to her rewrite ladder when a corrected mistake shows again, it goes to the local
compositor, or it is held for the Owner. On RunPod Serverless the purchase runs as rounds of one
batch each inside one GPU session (`gpu_batch.run_rounds`), switched off right after the last result, with
the meter raised to measured GPU seconds and given back for items RunPod provably never made;
`runpod_unsent` releases scenes held by a /run that got no job id, either by a later proof or by
the Owner's card. `factory` decides which vendor adapter may be used at all (selected and
verified connections only) and keeps paid vendors off the legacy whole-film render; `services`
builds storyboards from approved scripts under a content gate (scene kinds, card numbers checked
against SUPPORTED claims, cast stated not guessed) and buys character reference sets on the
Owner's press; `toolchain` masters and mixes audio to fixed loudness rules; `rehearsal` rebuilds
a film from files already paid for at 0 credits; `disk` and `storage` guard free space and which
files may be served. No function in these 13 files calls a language model directly; the model
enters only through the stills gate's vision look (`picture_qc.judge_still`, injected as the
`judge` callback), through the Director's second look (`fix_check.director_second_look` →
`second_look.second_look` → `second_look._look`, called from `_director_looks`), through the
callers' `on_outcome` and `next_round` callbacks that `gpu_batch.run_rounds` runs inside the GPU
session (the stills gate and her look here, clip QC for the assembler's motion rounds), and
through LLM-written inputs (prompts, scripts, sound plans, the Director's rewrites) that code
here checks, clamps or refuses.

## Why it exists

| Problem / incident | What it shaped here | Source |
|---|---|---|
| The Nepal film (2026-09-26): twelve clips bought before anyone looked at a still; three stills showed forbidden faces, a bar chart came back as a woman, a black screen as a landscape; the whole film was then bought a second time with the same prompts (> 1000 credits). | Stills bought first, alone, judged before motion is priced; one approval per plan_hash; a scene with an APPROVED take is never bought again; charts/titles/black screens composed locally; the zero-credit rehearsal. | `backend/app/media/stills_stage.py:3-8`; `backend/app/media/rehearsal.py:3-6`; `backend/app/media/models.py:182-187`; `backend/app/media/services.py:794-801`; `docs/project/16_DECISION_LOG.md` "The film staircase" (lines 4022-4060); `docs/architecture/51_AUTONOMY_MODE_SEMANTICS.md:75-98` |
| Legacy whole-film render showed no price and asked nothing; in TEST it could buy a whole film from the real Runway connection. | `PaidVendorRefused`, module-based default-deny paid-vendor detection. | `backend/app/media/factory.py:41-53`; `docs/project/16_DECISION_LOG.md:4080` |
| The Owner, 2026-10-08: «Sunt taxat la secunda, deci trebuie oprit imediat dupa generare». | One GPU session per step, rounds of one batch, GPU off in `finally`. | `backend/app/media/gpu_batch.py:4-14`; `docs/project/16_DECISION_LOG.md:4196`, `:4212` |
| Film babcf272 (2026-10-09): a stills /run failed in 0.12 s with no job id; scene 1 held, the whole step blocked, RunPod showed no job and $0. | Proof of never-queued at GPU-off; `runpod_unsent` release by proof or by the Owner's card. | `backend/app/media/runpod_unsent.py:1-57`; `docs/project/16_DECISION_LOG.md:4248` |
| The Owner, 2026-10-03: a film waited on LOW_BALANCE because the start check asked for the whole cap × 1.15. | Start on the first round × margin; re-read the balance before every request. | `backend/app/media/stills_stage.py:2015-2023`, `:2183-2192`; `docs/project/16_DECISION_LOG.md:4155-4157` |
| 2026-10-04: the LHC stills step bought scenes 4-9 (108 credits) after the Owner lowered the mode to MANUAL. | `PurchaseGuard` asks the kernel again before every request/round (spec 51 «Lowering autonomy»). | `backend/app/media/stills_stage.py:2049-2062`, `:2159-2164`; `docs/project/16_DECISION_LOG.md:4186`; `docs/architecture/51_AUTONOMY_MODE_SEMANTICS.md:185-194` |
| 2026-10-09: scene 1 re-rolled alone for three rounds on a model that never reads Figure 1; scenes 2-5 never bought. | Only a scene whose request would really carry Figure 1 waits for it; round 1 carries every other scene; a cut keeps first tries before re-rolls. | `backend/app/media/stills_stage.py:1397-1404`; `backend/app/media/gpu_batch.py:112-123`; `docs/project/16_DECISION_LOG.md:4251` |
| 2026-10-11/12: serial two-shots drawn as stacked panels twelve times each. | Fixed negative prompt (`STILL_NEGATIVE`). | `backend/app/media/stills_stage.py:196-222`; `docs/project/16_DECISION_LOG.md:33` |
| 2026-10-12: the gate's "scene" was the compiled prompt again, so a prompt that lost its subject matched itself. | `_scene_picture` prefers the scriptwriter's `writer_visual` for a factual film. | `backend/app/media/stills_stage.py:437-457` |
| 2026-10-12, f06808c9 scene 1 (review of 9ac0195, finding 4): `writer_visual` said «Marcus alone at his desk» while the composed beat put Marcus and Sarah in frame, so every correct still was refused as «not the scene». | For an episode of the serial the gate is shown the composed beat (room, people in frame, first moment of the action), never the writer's line. | `backend/app/media/stills_stage.py:404-434`, `:451-452`, `:496-498` |
| 2026-10-12, the Owner: «trece imaginile picate de la QC pe la Directoare…» and «LLM-ul este pe abonament! NU COSTĂ BANI SĂ TRECEM PE LA EI! GENERAREA DE IMAGINI ȘI MIȘCĂRI COSTĂ!»: a round the gate refused whole had been bought again on the gate's word alone. | `_settle_round` / `_director_looks`: before a re-roll, a rewrite or a hold, the Director looks at the refused candidates the bible's hard limits did not stop; one her look lets stand is approved by her and nothing is bought. | `backend/app/media/stills_stage.py:40-45`, `:977-984`, `:1038-1077`, `:1110-1184`; `backend/app/media/second_look.py:1-33` |
| 2026-10-12 (review of 9ac0195, finding 3): two more re-rolls on corrected words that did not correct a mistake were up to four paid stills of the same mistake. | A still that shows its plan and repeats the corrected mistake (or repeats it after one re-roll) ends the scene for the Director's rewrite; the review's lessons are withdrawn. | `backend/app/media/still_gate.py:1160-1183`, `:199`; `backend/app/media/stills_stage.py:1150-1159` |
| Scenes bought again on every run (fakes: image requests 3/6/9 over three days). | Scene memory, holds, `max_paid_attempts_per_scene`. | `docs/project/16_DECISION_LOG.md:4106`; `backend/app/media/stills_stage.py:66-71` |
| 2026-09-18: factual storyboards wrote `character_ids_json=[]` on every scene; a joined cast list dropped a stated character. | Stated vs guessed cast, read per entry. | `backend/app/media/services.py:1248-1256`, `:768-775` |
| MONEY-13 (2026-10-02): reference sets bypassed the Policy Kernel. | `media.character_reference_set` via `may_act`; balance read; every produced slot booked. | `backend/app/media/services.py:1891-1896`; `docs/architecture/24_VISUAL_CONTINUITY_ASSET_SYSTEM.md:40-66` |
| Nepal failed QC at -0.93 dBTP; ElevenLabs takes at -23..-25 LUFS made loudnorm fall back to dynamic mode. | Two-pass linear loudnorm at -14 LUFS / -2.0 dBTP, pre-limiter, AAC once. | `backend/app/media/toolchain.py:126-150`, `:381-386`; `docs/project/16_DECISION_LOG.md:1886`, `:4043-4047` |
| Rehearsal audit Q1/Q4 (2026-10-01): 0.28-0.61 s of digital silence at every cut, nothing under the narration; the Owner 2026-10-11 on music «să nu acopere vocea». | Silence measurement, ducked bed 20 LU under the voice, plan levels clamped. | `backend/app/media/toolchain.py:571-627` |
| REL-08: 299 GiB in the repo's media folder, no free-space check before a paid step. | `disk_refusal` (LOW_DISK). | `backend/app/media/disk.py:1-13` |
| SEC-06: take/asset routes served whatever path a row held. | `media_file_inside`. | `backend/app/media/storage.py:1-6` |
| 2026-10-11: a published film shown only as "randat · QC: a trecut"; two storyboards for one film. | `films_now`, `_newest_publications`, replaced boards hidden. | `backend/app/media/services.py:1587-1589`, `:1620-1622`, `:1706-1708` |

## Who decides here

Vocabulary: LLM, LLM_CHECKED_BY_CODE, CODE_RULE, OWNER, CONFIG, EXTERNAL.

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| Whether the stills step may buy at all (the yes) | OWNER (through the Policy Kernel's `paid_media_approval` rule; MODE hands it to the autonomy mode) | `backend/app/media/stills_stage.py:2025-2048` | `may_act('media.stills_purchase', cost_usd=cap_usd, context={plan_hash, cap_credits})`; `EVERY_PAID_STEP` (the default) asks the Owner in every mode, `OVER_USD` compares his threshold with the cap, `MODE` leaves it to the autonomy mode (`docs/architecture/51_AUTONOMY_MODE_SEMANTICS.md:75-98`); not allowed → `StillsStageRefused(status, approval_id)`; NEEDS_APPROVAL is HTTP 202 (`backend/app/media/stills_stage.py:323-325`), every other refusal 409. Asked whether `unasked` is True or False: the Owner's own press is not exempt here |
| The yes is bound to exactly the plan shown | CODE_RULE | `backend/app/media/stills_stage.py:703`, `:1897-1905` | sha256 of the canonical plan (scenes, prompts, model, ratio, candidates, re-roll limit, reused shas, credits); mismatch → STALE_PLAN |
| An unasked step (day's staircase, FILM_CONTINUE) refused before the balance is read | CODE_RULE (Policy Kernel, `mode_guard.unasked_refusal`) | `backend/app/media/stills_stage.py:1999-2011` | kernel refuses outright → refusal with the kernel's status; no low-balance card raised |
| Lowered mode / stricter rule stops buying mid-step | OWNER (mode) via CODE_RULE guard | `backend/app/media/stills_stage.py:2050-2062`, `:2159-2164`; `backend/app/media/gpu_batch.py:354-370` | `PurchaseGuard.stop_reason` before every request (per-request path) or every round (RunPod) |
| STOP AUTONOMY stops buying | OWNER | `backend/app/media/stills_stage.py:2155-2158`, `:2463-2467` | `runbook.services.stop_requested(engine)` → NOT_BOUGHT, «Proprietarul a oprit autonomia» |
| A still with no published price is never bought | CODE_RULE + CONFIG (price table) | `backend/app/media/stills_stage.py:1892-1896` | `UnpricedError` → UNPRICED |
| A film with a locked character lacking a reference is bought for no scene | CODE_RULE on the Owner's lock | `backend/app/media/stills_stage.py:654-658`, `:1906-1911`; `backend/app/media/services.py:2139-2149` | `ReferenceRequired` when `identity_locks_json['visual']` and no reference asset → NEEDS_REFERENCE |
| In PRODUCTION every LIVE scene's prompt must come from the model's shot plan (or the serial's approved look) | CODE_RULE | `backend/app/media/stills_stage.py:1928-1941` | `scene.source` must be in `assembler.shot_plan_sources` → else NEEDS_SHOT_PLAN |
| Prompt lint BLOCK refuses the step | CODE_RULE | `backend/app/media/stills_stage.py:1942-1956` | `prompt_lint.lint_film` + `has_block` → LINT_BLOCKED |
| A locked face is never drawn from words by an adapter that cannot take a reference | CODE_RULE | `backend/app/media/stills_stage.py:1960-1977` | `factory.accepts_reference_image(adapter)` false for a required reference → NEEDS_REFERENCE |
| Disk too full → nothing bought | CONFIG (`STUDIO_MIN_FREE_GB`, default 20 GB; 0 = off) | `backend/app/media/stills_stage.py:1978-1983`; `backend/app/media/disk.py:27`, `:119-126` | free < minimum → LOW_DISK; an unreadable disk refuses nothing |
| RunPod: GPU could not start → refuse before the yes is asked/spent | OWNER (his «Oprește GPU acum» hold, card `allow_infra_actions`) + CONFIG (endpoint, bucket) + EXTERNAL (endpoint weights) | `backend/app/media/stills_stage.py:1987-1998`; `backend/app/media/gpu_batch.py:87-97`; `backend/app/providers/runpod/gpu_session.py:701-753` | `gpu_session.precheck` raises `GpuSessionRefused`: OWNER_HOLD (his GPU stop holds; unreadable counts as held), NOT_CONFIGURED (no Serverless endpoint for the purpose, or no bucket), BLOCKED_INFRA_DISABLED (card not accepted), WEIGHTS_NOT_READY, WEIGHTS_MISMATCH; a mock (simulation) passes. GPU_BUSY is not covered (see Oddities) |
| Balance enough to start | CODE_RULE + CONFIG (`settings.paid_step_balance_margin`, default 1.15) + EXTERNAL (vendor balance) | `backend/app/media/stills_stage.py:2012-2023`, `:841-852`; `backend/app/media/balance_rule.py:52-58` | a balance read that raises → LOW_BALANCE; balance < ceil(first round × margin) → LOW_BALANCE. A reader that answers no number (Runway's `creditBalance` absent → None) is treated as read with no balance and the check is skipped; an adapter with no reader (RunPod, ComfyUI) is not checked at all |
| Which scenes are bought | CODE_RULE | `backend/app/media/stills_stage.py:636-658` | LIVE, no APPROVED take of the same identity, not pending, not held, no missing reference; none at all while scene 1 is held or any reference is missing |
| The step's cap | CODE_RULE | `backend/app/media/stills_stage.py:659-671` | cost = per-scene price × scenes (+ round overhead × series on RunPod); cap = cost × (1 + MAX_REROLLS) (+ overhead × series × 3) |
| Next request would exceed the cap | CODE_RULE | `backend/app/media/stills_stage.py:2171-2177`; `backend/app/media/gpu_batch.py:371-383` | STOPPED_AT_CAP; RunPod rounds cut by `fit_round`, empty round stops |
| Balance before each further request | CODE_RULE + EXTERNAL | `backend/app/media/stills_stage.py:2178-2192` | balance < ceil(price × margin) → scene NEEDS_OWNER `failure_kind` LOW_BALANCE, nothing more bought, hold `holds: false` (`:2399`) |
| Account lost more than the step counted | CODE_RULE + EXTERNAL | `backend/app/media/stills_stage.py:2193-2197`; `backend/app/media/assembler.py:8315`, `:8350-8355` | drop − committed > 0.5 credits → step stops |
| A scene is bought no more after N paid attempts since the Owner's last decision | CONFIG (`STUDIO_MAX_PAID_ATTEMPTS_PER_SCENE`, default 3) | `backend/app/media/stills_stage.py:2073`, `:2165-2170`, `:1497-1502`; `backend/app/media/assembler.py:8543-8551` | requests ≥ limit → NEEDS_OWNER (`attempts_reason`). The count restarts at the Owner's act on the scene or at the Director's rewrite of its still (`scene_rewrite`, `decided_by='director'`, `layer='still'`; `backend/app/media/assembler.py:8459-8462`, `:8786-8796`) |
| A scene left to the Owner earlier is not bought | CODE_RULE (scene memory) | `backend/app/media/stills_stage.py:572-591`, `:2098-2102` | `assembler.scene_memory(...).hold_ro`; a hold is lifted only by the Owner's acts (scene model set, take decided, REDO.* retirement, new words) or by the Director's still rewrite (an LLM agent's decision; `backend/app/media/assembler.py:8455-8462`, `:8786-8796`), and by `runpod_unsent` releases |
| Later scenes wait for scene 1's approved still (Figure 1) | CODE_RULE | `backend/app/media/stills_stage.py:2131-2137` (per request); `:1757-1769`, `:1709-1725` (RunPod: only when the request would carry Figure 1) | scene 1 ends without approval → later scenes NOT_BOUGHT (`FIGURE_ONE_MISSING`) |
| What pictures go with a request | CODE_RULE + EXTERNAL (adapter capability) | `backend/app/media/stills_stage.py:795-824` | character reference first (only to an adapter that declares `ACCEPTS_REFERENCE_IMAGE`), Figure 1 second (to any adapter, scene 1 excepted), truncated to the adapter's `MAX_REFERENCES` when it declares one (see Oddities: Figure 1 and adapters that take no reference) |
| The scene's written picture the gate judges `shows_scene` against | CODE_RULE | `backend/app/media/stills_stage.py:437-457`, `:404-434`, `:496-498`, `:539` | an episode of the serial (`editorial.is_serial_film`, or a package with `in_frame` and `shot_size`) → the composed beat (room, short names of the people in frame, first moment of the action); a factual film → the scriptwriter's `writer_visual`, else `visual_prompt` when it differs from the still prompt, else nothing |
| Which corrections a still is checked for (`must_fix`) | CODE_RULE | `backend/app/media/stills_stage.py:543-548`; `backend/app/media/fix_check.py:485-497`, `:61` | open findings of the still layer only (items marked `still` or `both`), ranked, at most `MAX_ITEMS` = 4; a finding treated in the motion's words is left to clip QC |
| Whether one candidate passes | LLM_CHECKED_BY_CODE | `backend/app/media/stills_stage.py:912-941`; `backend/app/media/still_gate.py:928-1072` | local checks first; vision model only if none blocks; any blocking check, an unmeasured look, or any bad answer blocks (fail closed). Each `must_fix` item is answered gone / minor / persists: persists blocks (`finding_persists`), minor is accepted as a warning carried on the take (`:999-1006`), an unanswered item counts as unmeasured |
| Which passing candidate is APPROVED by the gate | CODE_RULE | `backend/app/media/still_gate.py:1109-1115`, `:828-840`; `backend/app/media/stills_stage.py:944-974`, `:1126-1133` | among PASSED, fewest minor traces first (a count of the vision look's `minor` answers, so the model's answers rank first), then the highest `score` (0.5 × sharpness term + 0.3 × palette term, 0.15 when the palette is unmeasured, + 0.2 when the vision verdict says `look_ok`; every PASSED candidate has `look_ok`, so the score ranking is set by the local measurements), then sha256; `approved_by = "still_gate"` (`GATE_REVIEWER`, `:261`); a passing runner-up stays PAID for the Owner's pick |
| Which refused candidates the Director may look at | CODE_RULE | `backend/app/media/still_gate.py:1118-1130`; `backend/app/media/fix_check.py:130`; `backend/app/media/stills_stage.py:1050-1053`, `:1143`, `:1253-1260`, `:1634-1638` | only in a round with no passing candidate; in `_settle_round` only when the next step would be a re-roll, a rewrite or the Owner (never compose_locally), while the settlement of collected candidates (`_settle_pending`) asks whenever none passes, without the step (see Oddities); a RunPod round that was uncertain, cancelled or empty is refused without her look (`_StillRounds._decide`); a candidate is offered when BLOCKED with measured violations, nothing unmeasured (so never one the local checks stopped, which the vision model did not see), none of `HARD_LIMITS` (`faces`, `readable_text`, `panels`, `degenerate`) and not `compose_locally`; fewest violations first, one look per picture, until one is accepted |
| A refused candidate approved by the Director's second look; nothing more bought for the scene | LLM (within the set code allows; the answer is checked for consistency only) | `backend/app/media/stills_stage.py:1038-1077`, `:1143-1149`, `:1017-1035`, `:1250-1260`; `backend/app/media/fix_check.py:642-703`; `backend/app/media/second_look.py:88-135` | `fix_check.look_accepts`: OVERTURNED with severity none or minor (a CONFIRMED-minor-without-redo branch exists but the answer model forbids it, see Oddities) → take APPROVED with `approved_by = "director_look"`, failure cleared, a `media.take_quality_note` written; CONFIRMED or UNAVAILABLE (no registry, no Director, no seeing model, two invalid answers, an error) → the refusal stands. Used in the per-request path, the RunPod rounds, the paid still redo (`backend/app/media/assembler.py:16571`) and the settlement of collected candidates |
| Re-roll, rewrite, compose locally or the Owner (after her look) | CODE_RULE on the gate's reports (the vision verdict feeds them) | `backend/app/media/still_gate.py:1198-1213`, `:1139-1195`, `:196-199`; `backend/app/media/stills_stage.py:1134-1184`, `:2371-2392`, `:1671-1696` | `round_step` picks the deciding candidate (one that shows its plan and repeats a corrected mistake, else the first with violations, else the first); `next_step`: compose_locally (below); no violation code (only "unmeasured", or a refusal by the model's `verdict` field alone with every other answer good, `backend/app/media/still_gate.py:1044-1045`, which the Owner then reads as «verificările nu au putut rula», see `03_media_quality_control.md` oddity 30) → Owner, with no look of hers since `may_be_overturned` needs a violation code; `finding_persists` with the plan shown, or after `PERSISTS_REROLLS` = 1 re-roll → `rewrite` (the scene ends NEEDS_OWNER with `rewrite: true`, «Directoarea le rescrie»; her ladder rewrites the words); violations and < `MAX_REROLLS` = 2 re-rolls → re-roll with `positive_instruction` (words from code, built from the violation codes; her CONFIRMED reasons recorded as `director_confirmed`); else Owner. A round with no candidate at all → Owner («nicio imagine») |
| The rewrite's provisional lessons confirmed or withdrawn | CODE_RULE on the vision look's item answers | `backend/app/media/stills_stage.py:1080-1107`, `:1150-1159`; `backend/app/media/fix_check.py:536-571` | an approved take whose every `must_fix` item is gone confirms the review's lessons (`prompt_agent.confirm_prompt_lessons`); a round refused with an item that persists, ending in anything but a re-roll, withdraws them (`withdraw_prompt_lessons`). A take her look approves although an item persists neither confirms nor withdraws them (`settle_lessons` with `approved=True`, `persisted=False`, `backend/app/media/stills_stage.py:1104-1107`; `backend/app/media/fix_check.py:555-571`): they stay provisional. Lessons are STRATEGY memory rows (`backend/app/media/prompt_agent.py:3516-3560`) |
| A blocked candidate's scene ends as COMPOSE_LOCALLY (no re-roll, no look, held) | LLM (the vision verdict's `verdict` field, acted on as is once code has already blocked the candidate) | `backend/app/media/still_gate.py:1047-1053`, `:1145-1150`; `backend/app/media/stills_stage.py:1171-1172`, `:2392`, `:1695`, `:2395-2418` | `verdict == "compose_locally"` on the deciding BLOCKED report → `next_step` returns compose_locally before the re-roll test; the Director is not asked; the scene is held (hold event) and nothing more is bought for it in the step. It can only stop spending, never start it |
| Vendor refusal handling | CODE_RULE on EXTERNAL failure codes | `backend/app/media/stills_stage.py:2247-2298` | `classify_vendor_failure`: TRANSIENT/BAD_OUTPUT retried once per scene on the same words; STUDIO_DEFECT → NOT_BOUGHT and the step stops (scene not held); every other kind → NEEDS_OWNER, «aceleași cuvinte nu se trimit din nou», and a `stop_step` kind (ACCOUNT, or a second CONTRACT refusal in a row; `backend/app/media/production_policy.py:2246-2247`, `:2257-2370`) also stops the step |
| A request that may have been charged without an answer | CODE_RULE | `backend/app/media/stills_stage.py:2250-2280`; `backend/app/media/assembler.py:8318-8347` | counted against the cap, never resent automatically (MONEY-01), scene NEEDS_OWNER UNANSWERED, step stops |
| Accepted but not delivered | EXTERNAL → CODE_RULE | `backend/app/media/stills_stage.py:2235-2246` | `TaskStillOpen` → takes stay SUBMITTED with task ids, IN_FLIGHT, step stops; collected later by a free GET |
| Whether a failed scene is held for the Owner | CODE_RULE | `backend/app/media/stills_stage.py:2396-2402`, `:1807-1811` | not held when `failure_kind` is LOW_BALANCE, or a free kind (TRANSIENT/TECHNICAL/ACCOUNT) that cost nothing; a `rewrite` outcome is held like any other NEEDS_OWNER (the Director's still rewrite lifts it, `backend/app/media/assembler.py:8786-8796`) |
| Credits booked per request | CODE_RULE + EXTERNAL (vendor quote) | `backend/app/media/stills_stage.py:2300` | `max(per_request, vendor's last_estimated_credits)` |
| Measured credits per image | EXTERNAL (balance before/after) | `backend/app/media/stills_stage.py:2482-2512` | `(before − after) / images` written on each take; MEASURED prices recorded when `integration_id` is given |
| Unsettled candidates judged without buying or asking | CODE_RULE (+ the vision look and the Director's look) | `backend/app/media/stills_stage.py:1284-1345`, `:1202-1281` | `settle_stills` / `_settle_pending`: collect SUBMITTED tasks (free GET) and judge UNJUDGED PAID candidates; a collected set refused whole is shown to the Director first (`:1253-1260`), and else the scene is planned again on the sheet |
| A RunPod round's content when the cap is short | CODE_RULE | `backend/app/media/gpu_batch.py:100-123`, `:378-383` | sort by (attempt, scene, candidate), pop from the end until it fits; scenes cut out whole go ahead of next round's re-rolls |
| A round RunPod queued nothing of | EXTERNAL → CODE_RULE | `backend/app/media/gpu_batch.py:392-412` | price given back; nothing bought before → refusal raised (BLOCKED_MODE/BLOCKED_NO_BUDGET kept as the Owner's decision, `:131-142`); else the step ends on what it bought |
| Stopping a running round | OWNER («Oprește GPU acum», STOP, mode) / EXTERNAL (deadline, wrong weights) | `backend/app/media/gpu_batch.py:421-469` | cancel unfinished jobs; what finished is kept; after a halt at most four more polls (three waits of the poll interval) before the loop leaves the rest to the session close |
| Books raised to measured GPU seconds | EXTERNAL + CODE_RULE | `backend/app/media/gpu_batch.py:482-491` | measured credits > kept → meter raised; never lowered below the estimate |
| A /run with no job id | EXTERNAL → CODE_RULE | `backend/app/media/gpu_batch.py:492-512`, `:217-275` | the step stops; after the session close the proof (`BatchRun.prove_unsent`) decides whether credits go back and takes become not queued |
| Wrong weights on the endpoint | EXTERNAL → OWNER card | `backend/app/media/gpu_batch.py:435-444`, `:531-537` | stop, cancel, `raise_weights_card` after the close |
| A held scene released without the Owner | CODE_RULE on EXTERNAL proof | `backend/app/media/runpod_unsent.py:854-883` | every row PROVEN by a later round's proof and nothing billed |
| Whether the Owner is asked about a held scene | CODE_RULE | `backend/app/media/runpod_unsent.py:738-745`, `:606-614`, `:542-583` | card only when not all proven and no blocker (answered since, being sent, jobs accepted, off not verified, counts ≠ 0, shared endpoint, SIGN in the proof, billed) |
| Release of a held scene on the card | OWNER | `backend/app/media/runpod_unsent.py:909-947` | re-checked under the write lock; rows FAILED/UNSENT at 0 cost, takes RUNPOD.NOT_QUEUED; idempotent by command id |
| One card per hold, ever | CODE_RULE | `backend/app/media/runpod_unsent.py:149-151`, `:748-756`, `:899-901` | dedupe key `runpod_unsent:<hold event>`; a "no" is never asked again |
| Which adapter serves a purpose | OWNER (ServiceSelection) + CONFIG (MediaProductionConfig) + EXTERNAL (verified status, discovered resource) | `backend/app/media/factory.py:202-209`, `:241-291`, `:348-381` | connection selected and VERIFIED/ACCESS_VERIFIED, model discovered (`production_resource`); else None (placeholder path) |
| The legacy render may not touch a paid vendor | CODE_RULE (default deny by module) | `backend/app/media/factory.py:57-118`, `:121-175` | any class in the adapter's MRO defined under `app.providers` outside `FREE_PROVIDER_MODULES` → `PaidVendorRefused` |
| Motion model per scene | CODE_RULE (`production_policy.choose_model`) + OWNER (forced model) + CONFIG (environment) | `backend/app/media/factory.py:543-623` | card kinds get no model; TEST asks prompt-to-video, PRODUCTION image-to-video |
| Image vendor order | CODE_RULE + OWNER (approved alternatives) | `backend/app/media/factory.py:898-936` | resolved selection first; in TEST cheapest recorded price first, unpriced last |
| Locked voice unusable | CODE_RULE | `backend/app/media/factory.py:686-702` | the scene gets no real voice; never another voice for a locked character |
| Commercial-use evidence of a component | OWNER | `backend/app/media/factory.py:415-440` | `commercial_use` True only when the connection's config says exactly "da" |
| Storyboard may be built | CODE_RULE | `backend/app/media/services.py:1261-1283` | autonomy not stopped, script APPROVED, no unverified claims |
| Scene kind (LIVE vs composed) | CODE_RULE over the LLM writer's declaration | `backend/app/media/services.py:1051-1076` | composed kinds kept; chart/black/title phrases or two comparable amounts carried by claims → composed |
| Card numbers | CODE_RULE | `backend/app/media/services.py:1104-1158`, `:1344-1350`, `:1214-1223`, `:1351` | every bar's value+unit carried by a SUPPORTED claim (rounding as written); any card text number must be carried; else the storyboard is refused. A DATA_CARD/TITLE_CARD scene with no card at all is not refused: it is stored as that kind with `card_json` None and listed in the event's `cards_missing` (numbers are never invented) |
| Who is on screen | CODE_RULE | `backend/app/media/services.py:748-791`, `:1450` | stated cast only (writer's list by given name, prose by whole canonical name); guesses only recorded on the event |
| Earlier unrendered boards of the same script | CODE_RULE | `backend/app/media/services.py:1288-1299` | APPROVED boards with no COMPLETED render → REJECTED |
| Reference set purchase | OWNER (press) + CODE_RULE (kernel stop/safe mode, budget, balance) | `backend/app/media/services.py:1904-1969`, `:1845-1870` | `may_act('media.character_reference_set', requester='owner', ask_owner=False)`; BLOCKED_STOP refuses; BLOCKED_MODE/NEEDS_APPROVAL pass, any other refusal refuses; a balance read that raises → LOW_BALANCE; balance ≥ credits × slots × 1.15 is compared only when the price came from the published credits table (a catalogue USD price, or a non-number balance, skips the comparison); `reserve_spend` of the USD estimate (0 when unpriced) |
| Who may adopt paid files in a rehearsal | OWNER (or "test" in TEST) | `backend/app/media/rehearsal.py:299-308` | anything else → `RehearsalRefused` |
| Rehearsal: still adopted / clip usable / film assembled | CODE_RULE | `backend/app/media/rehearsal.py:525-589`, `:592-631`, `:693-706`, `:1229-1236` | local checks; first-frame SSIM ≥ 0.90; clip ≥ shot span; every scene has recorded narration |
| Bed level against the Voice Artist's plan | LLM_CHECKED_BY_CODE | `backend/app/media/toolchain.py:933-1162`, `:771-793`, `:923-927` | levels only from {under 0, soft −6, lift +8 dB}; lift only inside measured silences; fades clamped 0.3-4.0 s; bed corrected to 20 LU under the voice where it speaks; correction outside −60..+30 dB refused |
| Which files the media routes may serve | CODE_RULE | `backend/app/media/storage.py:33-55` | regular file, not a link, resolved inside a media root |

## LLM involvement

**Direct LLM call sites in these 13 files: none.** Verified by reading every file and by a
search for `run_agent_task`, `structured_run`, `run_with_strategy`, `reviews._run` and
`prompt_agent._run`: there is no hit. `stills_stage` names `prompt_agent` only in docstrings
(`backend/app/media/stills_stage.py:406`, `:415`, `:447`) and in the import of two
deterministic text helpers, `_short_name` and `_still_moment` (`:420`;
`backend/app/media/prompt_agent.py:1571`, `:1741`). The Director's second look is reached through
`fix_check.director_second_look` (`:1056`), a wrapper that is not a gateway; the call site behind
it is `second_look._look` (`backend/app/media/second_look.py:653`, `structured_run` at `:720`).
Static share: 10 of 243 functions (4.1 %) have a static path to the gateway; their bodies are
1,276 of 10,577 lines (12.1 %). At runtime nine of them (all in `stills_stage`) can call a model;
`rehearse` does not (below).

### Functions here that reach the LLM indirectly

| Function | Path | Call site reached | Runtime |
|---|---|---|---|
| `run_stills_stage` (`backend/app/media/stills_stage.py:1837`, distance 3) | `_judge_candidate` (`:912`) / `_StillRounds.landed` (`:1526`) → `judge` parameter, default `picture_qc.judge_still`; `_settle_round` (`:1110`) and `_settle_pending` (`:1202`) → `_director_looks` (`:1038`) | `picture_qc.judge_still` (`backend/app/media/picture_qc.py:1765`) → `structured_run` (`:1829`); `second_look._look` (`backend/app/media/second_look.py:653`) → `structured_run` (`:720`) | yes: one vision look per candidate the local checks did not stop, and one look of the Director per offered candidate of a round refused whole (at most `STILL_CANDIDATES` = 2 per round, `backend/app/media/cost_plan.py:53`) |
| `settle_stills` (`backend/app/media/stills_stage.py:1284`, distance 3) | `_settle_pending` → `_judge_candidate` → `judge_still`; `_settle_pending` → `_director_looks` | both | yes, for collected or unjudged candidates; no money, no yes asked |
| `_settle_pending` (`backend/app/media/stills_stage.py:1202`, distance 6) | injected `judge`; `_director_looks` when the collected set is refused whole (`:1253-1260`) | both | yes |
| `_settle_round` (`backend/app/media/stills_stage.py:1110`, distance 6) | `_director_looks` (`:1144`) | `second_look._look` | yes, when no candidate passed and the next step is a re-roll, a rewrite or the Owner |
| `_director_looks` (`backend/app/media/stills_stage.py:1038`, distance 5) | `fix_check.director_second_look` (`backend/app/media/fix_check.py:642`) → `second_look.second_look` (`backend/app/media/second_look.py:583`) → `_look` | `second_look._look` | yes, once per offered candidate until one is accepted |
| `_StillRounds._decide` (`backend/app/media/stills_stage.py:1628`, distance 8), `._settled` (`:1671`, 7), `.next_round` (`:1698`, 9), `.run` (`:1730`, 9) | → `_settle_round` | `second_look._look` | yes; `next_round` runs while the GPU session is open (`backend/app/media/gpu_batch.py:513`) and `run` also decides the last rounds after it closed (`backend/app/media/stills_stage.py:1795-1797`) |
| `rehearse` (`backend/app/media/rehearsal.py:1181`, distance 4) | `qc.evaluate_media_qc` → `picture_qc.evaluate_pictures` and friends; `assembler.assemble_from_takes` → `assemble_video_job` → `film_mix` → `sound_design.sound_plan` | `picture_qc.evaluate_pictures` (`backend/app/media/picture_qc.py:904`); `sound_design.sound_plan` (`backend/app/media/sound_design.py:379`) | **no**: `registry=None` is passed to QC (`backend/app/media/rehearsal.py:1260-1267`), which then reports the picture checks NOT_APPLICABLE (`backend/app/media/qc.py:942-947`), and `assemble_from_takes` is given no `registry` (`backend/app/media/rehearsal.py:1239-1248`), so the sound plan is the deterministic one (`backend/app/media/assembler.py:6281`, `:7302-7314`) |

Runtime paths the static analysis cannot see (calls through injected callables or attributes;
the inventory gives these `llm_distance` null):

| Function | How it reaches a model at runtime |
|---|---|
| `_judge_candidate` (`backend/app/media/stills_stage.py:912`), `_StillRounds.landed` (`:1526`) | call the injected `judge` (default `picture_qc.judge_still`), once per candidate the local checks did not stop |
| `gpu_batch.run_rounds` (`backend/app/media/gpu_batch.py:278`) | calls the caller's `on_outcome` for every item while the round polls (`backend/app/media/gpu_batch.py:422-428`): the stills gate (`_StillRounds.landed`) here, clip QC for the assembler's motion rounds (`backend/app/media/assembler.py:11112`, `:11209-11224`, `_check_shot`); the GPU session is renewed after each judgement because "a judgement may take minutes" (`backend/app/media/gpu_batch.py:425-428`). After each round it calls the caller's `next_round` (`backend/app/media/gpu_batch.py:513`), which for stills decides every touched scene and so may ask the Director's look (`_StillRounds.next_round` → `_decide` → `_settle_round`); no session renewal follows those looks before the next round is sent (`backend/app/media/gpu_batch.py:366-391`). No model answer changes what `run_rounds` itself buys; the caller's `next_round` does |

### Model look 1: the stills gate's vision verdict

- **Speaker**: an ACTIVE employee whose primary model has the VISION capability, preferring
  roles in order `VideoEditor`, `Director`, `QualityAssurance` (`LOOKERS`); with none of those,
  the earliest-hired seeing employee of any role (`backend/app/media/picture_qc.py:119`, `:1789`;
  `backend/app/agents/vision.py:116-141`).
- **Task type and template**: `still_qc` (`backend/app/media/picture_qc.py:1400`); template
  `still-qc-v3`, or `still-qc-v3-fixes2` when the scene's words were rewritten to fix findings
  (`:1407`, `:1414`, `:1835`). `temperature=0.1`, `max_tokens = 800 + 150 × fixes` (`:1848-1849`).
- **What it asks**: one image at 1080 px (`STILL_WIDTH`, `:1420`) plus a JSON block inside an
  inert boundary, cut at 8000 characters: scene number, the still prompt (the plan), the scene's
  written picture (`stills_stage._scene_picture`: the writer's line for a factual film, the
  composed beat for the serial; `backend/app/media/stills_stage.py:437-457`), narration, story
  purpose, the `must_fix` items before the rest (`fix_check.open_findings`, still layer), look
  block, camera move, whether faces are forbidden, the bible's rules
  (`backend/app/media/picture_qc.py:1801-1825`). The plan is built in one place, `_still_plan`
  (`backend/app/media/stills_stage.py:460-478`).
- **Answer shape**: `StillJudgeReport` / `still_report_schema(n)` with `stills: [StillVerdict]`
  (`backend/app/media/picture_qc.py:1508-1602`): `scene` (StrictInt), `faces_visible`,
  `readable_text`, `matches_plan`, `look_ok`, `technical_ok`, `one_picture`, `shows_scene` (all
  StrictBool and required of the model), `bible_violations` (str, 1-300), `verdict` ∈ {`buy_motion`,
  `regenerate_still`, `compose_locally`}, `reason`, and `fixes: [FixAnswer{item, finding, status
  gone | minor | persists, seen}]` for every must-fix item (`seen` required unless gone; a legacy
  `fixed` true/false reads as gone/persists; `:1454-1501`). `structured_run` validates and
  retries once.
- **What the code does with it (trust: CHECKED_BY_CODE, fail closed)**:
  `still_gate.decide` (`backend/app/media/still_gate.py:928-1072`) folds the verdict with the
  local checks. The model can only add reasons to refuse: faces when the bible forbids them,
  readable text, not one picture, not matching the plan, not showing the scene, look, technical,
  any bible violation, any must-fix item that persists or is unanswered, any verdict other than
  `buy_motion`. A must-fix item answered minor is accepted and carried as a warning
  (`:1004-1006`; `minor_defects` on the scene's entry and a `media.take_quality_note` on the take,
  `backend/app/media/stills_stage.py:1012-1013`, `:1093-1103`). A candidate passes only when no
  local check blocks, every required local check ran (in PRODUCTION), the look was MEASURED for
  exactly this scene, and every answer is good. Code chooses between passing candidates, but its
  first key is the model's: `choose_best` takes the fewest minor traces (the count of the look's
  `minor` answers), then the highest `score` (`backend/app/media/still_gate.py:1109-1115`), whose
  only model term (+0.2 for `look_ok`, `:838-839`) is the same for every passing candidate, so
  among candidates with as many minor traces the local measurements rank them. In
  each must-fix answer the `finding` text is replaced by the studio's own words
  (`backend/app/media/picture_qc.py:1872-1874`, `:1622-1629`); the model's `reason` and
  `bible_violations` are quoted verbatim into the refusal reasons
  (`backend/app/media/still_gate.py:986`, `:1042`, `:1045`), which land on the REJECTED take's
  `failure_detail`, the hold event and the Director's second look (informational: the
  Director's ladder classifies them by the gate's own phrases). Content answers
  (`matches_plan`, `shows_scene`, a must-fix status) cannot be verified by code: a "yes" or a
  "gone" there is trusted, but only together with passing local checks. The model's steering
  power beyond "refuse" is `compose_locally` (a blocked candidate whose verdict says so ends the
  scene as COMPOSE_LOCALLY, held, with no re-roll and no look of the Director;
  `backend/app/media/still_gate.py:1050-1051`, `:1145-1150`;
  `backend/app/media/stills_stage.py:1171-1172`) and `persists` with `matches_plan` true (the
  scene ends as `rewrite` instead of a re-roll; `backend/app/media/still_gate.py:1160-1183`).
- **If the model fails, refuses or returns junk**: `judge_still` returns NOT_RUN («nu a fost
  privită»: no registry, no seeing employee, no image, unusable answer, wrong or duplicate
  scene; `backend/app/media/picture_qc.py:1786-1870`). `decide` records it as unmeasured and
  blocks; with `must_fix` items it adds the content phrase that sends the scene to the
  Director's ladder (`backend/app/media/still_gate.py:974-984`). With no measured violation
  `next_step` sends the scene to the Owner without a re-roll
  (`backend/app/media/still_gate.py:1152-1159`), because "another still would be judged by the
  same missing eye"; such a candidate is never offered to the Director's look. The candidate
  stays REJECTED with the reason on the take.
- **Can it lead to spending money?** Yes, indirectly. A refusal with violations, once the
  Director's look has not accepted a candidate, triggers a re-roll: another paid request of 2
  candidates (at most `MAX_REROLLS` = 2 per scene per step, `backend/app/media/still_gate.py:196`),
  still under the approved cap, the attempt limit and the per-request balance and mode checks.
  An approval of the first LIVE scene's still makes it Figure 1 and releases the purchase of the
  later scenes waiting for it (`backend/app/media/stills_stage.py:2381-2382`, `:1709-1715`).
  An approval unlocks pricing of the motion step, which is a separate paid approval. The look
  itself spends tokens (through `run_agent_task`'s daily token ceiling and USD budget), never
  vendor credits.

### Model look 2: the Director's second look at a refused still (since `5fc7468`)

- **Speaker**: the active Director (`agent_for_role(session, "Director")`,
  `backend/app/media/second_look.py:682`) on a seeing model chosen by `seeing_model` (`:686`):
  her own model when it sees, else her second or third slot that sees, else the model of the
  studio's seeing employee, `LOOKERS` roles first; the run is hers whichever model answers
  (`backend/app/agents/vision.py:162-185`). With no Director or no seeing model the look is
  UNAVAILABLE.
- **Task type and template**: `director_second_look`, template `director-second-look-v1`
  (`backend/app/media/second_look.py:68-69`), through `structured_run` (`:720`), `max_tokens`
  2000 (`:731`).
- **What it asks**: called by `_director_looks` with kind `still`, the refused candidate's file,
  the gate's refusal reasons (`report.reasons_ro`) and the take id
  (`backend/app/media/stills_stage.py:1056-1066`); `second_look._look` adds the scene's intent
  (`scene_intent`, `backend/app/media/second_look.py:211`, which also carries the bible's rules
  through `stills_stage._bible_rules`, `:224`) and her last three looks at the scene
  (`earlier_looks`, `:304`, `EARLIER_LOOKS_SHOWN` `:81`; read at `:676-677`), inside an inert boundary cut at 12,000
  characters (`:703-718`).
- **Answer shape**: `SecondLook` (`backend/app/media/second_look.py:88-135`): `verdict` ∈
  {CONFIRMED, OVERTURNED}, `severity` ∈ {none, minor, serious}, `redo` (bool), `reason_ro`
  (1-600). Validated for consistency only: serious only with CONFIRMED; OVERTURNED never redoes;
  CONFIRMED always redoes and names a defect. `fix_check.director_second_look` normalises the
  answer and never raises (`backend/app/media/fix_check.py:642-690`).
- **What the code does with it (trust: FINAL within the set code offers)**: code decides which
  candidates she sees (`still_gate.may_be_overturned`, `backend/app/media/still_gate.py:1118-1130`:
  no hard limit, nothing unmeasured, not `compose_locally`). When `fix_check.look_accepts`
  holds (`backend/app/media/fix_check.py:693-703`), `_approve_by_look` sets the take APPROVED
  with `approved_by = "director_look"` and clears its failure
  (`backend/app/media/stills_stage.py:1017-1035`), `_after_approval` writes the take note and
  confirms the rewrite's lessons when every item is gone (`:1080-1107`), and the scene's entry
  carries `approved_by`, `director_look` and `minor_defects` (`:1002-1014`); a scene-1 still
  becomes Figure 1 (`:1684-1685`, `:2381-2382`). A CONFIRMED reason is recorded as
  `director_confirmed` on the entry and appended to the Owner's reason
  (`:1075-1076`, `:1160-1162`, `:1182-1183`, `:1691-1693`, `:2388-2390`).
- **If the model fails**: UNAVAILABLE (no registry, no Director, no seeing model, no picture,
  a refused run, two invalid answers, any error; `backend/app/media/second_look.py:571-581`;
  `backend/app/media/fix_check.py:632-640`, `:659-680`): the refusal stands and the step goes on
  as before her look existed. Every look writes a `media.director_second_look` event and an
  AGENT_OPINION memory (`backend/app/media/second_look.py:515-569`).
- **Can it lead to spending money?** Yes, indirectly, within the cap the Owner's yes already
  approved. An accepted look ends the scene's own purchase, and a CONFIRMED or UNAVAILABLE look
  lets the re-roll go on under the unchanged gates (cap, attempt limit, balance, guard). But
  when she approves the first LIVE scene's candidate, that still becomes Figure 1, and the later
  scenes that were waiting for it are bought in the same step: per request the next scenes pass
  the Figure 1 test (`backend/app/media/stills_stage.py:2381-2382`, `:2131-2137`; in the
  settlement `:2121-2122`), and on RunPod `next_round` sends the waiting scenes at once
  (`:1684-1685`, `:1709-1715`). Without her approval a round that ends in a rewrite or the
  Owner leaves those scenes NOT_BOUGHT (`FIGURE_ONE_MISSING`, `:1716-1725`). A still she
  approves also unlocks pricing of the motion step, a separate paid approval. The look itself
  spends tokens only.

### LLM-written inputs that code here buys, checks or clamps (not call sites)

| Input (author) | Consumed by | What code does |
|---|---|---|
| Each LIVE scene's `still_prompt`, `look_block`, `camera_move`, `avoid` (the shot-prompt writer, `prompt_agent`) | `_read_scenes` (`backend/app/media/stills_stage.py:510-542`), `_prompt` (`:779-792`), `still_negative` (`:239-257`) | **These words are what is bought.** Gates: PRODUCTION requires a model-written source (`:1928-1941`), lint BLOCK refuses (`:1942-1956`), the plan hash binds the Owner's yes to the exact words (`:703`), `avoid` items enter the negative channel only if ≤ 60 chars and within 400 chars total (`:245-256`) |
| The scriptwriter's `writer_visual` line (factual films) | `_scene_picture` (`backend/app/media/stills_stage.py:437-457`) | shown to the vision gate as the scene's written picture; not bought |
| A serial beat's room, people in frame and action, composed into the scene's package by `prompt_agent._serial_package` (`backend/app/media/prompt_agent.py:1626`, `:1684-1697`): the room and the people are the episode beat's (the episode writer), the action is the shot-prompt model's restyled action, else the beat's own line | `serial_scene_picture` (`backend/app/media/stills_stage.py:412-434`) | reduced by code to the room, the short names of the people in frame and the first moment of the action (`prompt_agent._still_moment`); shown to the vision gate as the scene's written picture instead of `writer_visual`; not bought |
| The script's scenes (`ScriptDraft.scenes_json`: kind, visual, narration, claim ids, card) | `generate_storyboard_from_script` (`backend/app/media/services.py:1237-1456`); `factual.agent_pipeline._scene_kinds` (`backend/app/factual/agent_pipeline.py:915-956`) | `classify_scene_kind` overrides a LIVE declaration (`backend/app/media/services.py:1051-1076`); `card_problems` refuses any number not carried by a SUPPORTED claim (`:1104-1158`); cast from stated names only (`:748-791`) |
| The Voice Artist's sound plan (levels, fades, ambience; `sound_design.sound_plan` via `structured_run`) | `toolchain.mix_bed` (`backend/app/media/toolchain.py:933-1162`) | clamped: levels outside {under, soft, lift} count as 0 dB (`:780`), lift only inside measured voice silences ≥ 0.8 s with 0.1 s guards (`:785-792`), fades clamped to 0.3-4.0 s (`:979-981`), bed always corrected to 20 LU under the voice (`:1052`), corrections beyond −60/+30 dB refused (`:923-927`) |
| `must_fix` findings (QC's words, the Director's brief and rewrite review) | `_read_scenes` → `StillPlan.must_fix` (`backend/app/media/stills_stage.py:543-548`) | only the still layer's open items, at most 4 (`backend/app/media/fix_check.py:485-497`); asked of the vision look item by item; an item that persists or is not answered blocks the candidate, a minor trace is accepted as a warning |
| The rewrite review's provisional lessons (stored by `prompt_agent.record_prompt_lesson` with the review's run as source) | `_after_approval`, `_settle_round` (`backend/app/media/stills_stage.py:1080-1107`, `:1150-1159`) via `fix_check.settle_lessons` (`backend/app/media/fix_check.py:536-571`) | confirmed when a take is approved with every item gone; withdrawn when a round ends (not in a re-roll) with an item that persists |
| The Director's second-look verdict on a refused candidate | `_director_looks` (`backend/app/media/stills_stage.py:1038-1077`) | acted on as FINAL within the candidates `still_gate.may_be_overturned` offers (see Model look 2) |
| The Director's rewrite of a scene's still (`scene_rewrite`, event payload `decided_by='director'`, `layer='still'`) | `assembler.scene_memory`, read by `_read_scenes` (`backend/app/media/stills_stage.py:572-591`) | counts as a decision about the scene: lifts its hold and restarts its paid-attempt count (`backend/app/media/assembler.py:8459-8462`, `:8786-8796`); the new words are a new identity, so a new plan and plan_hash, and they still pass the PRODUCTION source check, the lint and the Policy Kernel's gate |
| The writer's prompt (factual pipeline) and the story reviewer's prompt | `local_media.writer_constraints` (`backend/app/media/local_media.py:28-63`) | appends a deterministic constraint (shot length, words per scene) computed from the selected ComfyUI model's `max_seconds` to the writer's prompt (`backend/app/factual/agent_pipeline.py:721-723`) and to the reviewer's (`backend/app/factual/story_review.py:606-608`) |

## Hard rules and limits

| Constant / rule | Value | Where |
|---|---|---|
| Policy action of the stills step | `media.stills_purchase` (T2) | `backend/app/media/stills_stage.py:192` |
| Still ratio | `1530:2720` (priced as 2K) | `backend/app/media/stills_stage.py:195` |
| Default stills model / resolution / candidates | `seedream5_pro` / `2K` / 2 | `backend/app/media/cost_plan.py:51-53` |
| Re-rolls per scene per step | `MAX_REROLLS = 2` | `backend/app/media/still_gate.py:196` |
| Re-rolls on words whose corrected mistake persists (the plan missed too) | `PERSISTS_REROLLS = 1`; with the plan shown, none (`rewrite` at once) | `backend/app/media/still_gate.py:199`, `:1160-1183` |
| Refusals the Director's look never overturns | `HARD_LIMITS = {faces, readable_text, panels, degenerate}`, plus anything unmeasured and `compose_locally` | `backend/app/media/fix_check.py:130`; `backend/app/media/still_gate.py:1118-1130` |
| Who approved a still | `still_gate` (`GATE_REVIEWER`) or `director_look` (`DIRECTOR_LOOK_APPROVER`) | `backend/app/media/stills_stage.py:261`; `backend/app/media/fix_check.py:126` |
| Corrections checked per still | at most 4 (`fix_check.MAX_ITEMS`), still layer only | `backend/app/media/fix_check.py:61`, `:485-497` |
| The Director's second look | task `director_second_look`, template `director-second-look-v1`, 2000 tokens, last 3 looks shown, one look per offered candidate (≤ 2 per bought round; in the settlement one per collected candidate), until one is accepted | `backend/app/media/second_look.py:68-69`, `:81`, `:731`; `backend/app/media/stills_stage.py:1050-1077` |
| Failure code of a candidate the gate refused | `LOCAL.STILL_GATE` (cleared when her look approves it) | `backend/app/media/stills_stage.py:279`, `:967`, `:1028-1029` |
| Local checks | `degenerate, panels, sharpness, motion_blur, palette, faces` | `backend/app/media/still_gate.py:201` |
| Retry once on the same words | failure kinds `TRANSIENT`, `BAD_OUTPUT` | `backend/app/media/stills_stage.py:281` |
| Free failure kinds (no hold when nothing was spent) | `TRANSIENT, TECHNICAL, ACCOUNT` | `backend/app/media/assembler.py:8476` |
| Paid attempts per scene since the Owner's last decision | 3 (setting `STUDIO_MAX_PAID_ATTEMPTS_PER_SCENE`, ≥ 1) | `backend/app/media/assembler.py:8474`, `:8543-8551` |
| Balance margin | 1.15 (`settings.paid_step_balance_margin`) | `backend/app/media/balance_rule.py:39`; `backend/app/media/stills_stage.py:277`, `:1985` |
| Uncounted balance drop tolerance | 0.5 credits | `backend/app/media/assembler.py:8315` |
| Negative prompt | 14 fixed terms (+ "visible faces", "portrait" when the bible bans faces), ≤ 400 chars, plan `avoid` items ≤ 60 chars each | `backend/app/media/stills_stage.py:203-221`, `:245-256` |
| Pending still statuses (never bought again, only collected/judged) | `SUBMITTED`, `PAID` with `COLLECTED.UNJUDGED` | `backend/app/media/stills_stage.py:284`, `:595-615` |
| Still takes counted for re-roll seeds | `PAID, APPROVED, REJECTED, LOST` | `backend/app/media/stills_stage.py:330`, `:560-570`, `:1475-1480` |
| SceneTake states | `QUOTED → SUBMITTED → PAID → APPROVED / REJECTED`, `REFUSED`, `LOST` | `backend/app/media/models.py:29-37`, `:182-188` |
| SceneTake identity | unique (storyboard, scene, kind, prompt_hash, sha256) | `backend/app/media/models.py:195-202` |
| RunPod round price | items × per-image + one round overhead (cold start + idle tail) | `backend/app/media/stills_stage.py:1492-1494`; `backend/app/media/gpu_batch.py:348` |
| Drain after a halt | `drains > 3` → leave: at most four more polls, three waits of `poll_interval` (default 2 s) | `backend/app/media/gpu_batch.py:349`, `:447-454` |
| Statuses kept as "the Owner's decision" | `BLOCKED_MODE`, `BLOCKED_NO_BUDGET` | `backend/app/media/gpu_batch.py:131` |
| Disk minimum | 20 GB (`STUDIO_MIN_FREE_GB`, 0 = off) | `backend/app/media/disk.py:27`, `:36-42` |
| Reference set framings / size / margin | 5 slots (`portrait, full_body, front, side, back`), 1024×1536, × 1.15 | `backend/app/media/services.py:1749-1768`, `:1826` |
| Storyboard page | 20 (max 100) | `backend/app/media/services.py:1579-1580` |
| Scene duration when unstated | words / 2.5, clamped 3-9 s | `backend/app/media/services.py:1421-1423` |
| Rehearsal first-frame match | SSIM ≥ 0.90 at 270×480 grey | `backend/app/media/rehearsal.py:97-98` |
| Loudness target / true peak target / LRA | −14 LUFS / −2.0 dBTP / 11 LU | `backend/app/media/toolchain.py:129`, `:134`, `:138` |
| QC loudness band / true-peak ceiling | −16..−12 LUFS / −1.0 dBTP | `backend/app/media/toolchain.py:144-145` |
| Sample limiter / master rate / codec | 0.79 FS / 48 kHz / AAC-LC 256k stereo | `backend/app/media/toolchain.py:150-168` |
| Pre-limiter | limit `10^((−2.0−0.5)/20)` ≈ 0.75, tolerance 0.3 LU, ≤ 3 rounds | `backend/app/media/toolchain.py:375-378` |
| Silence at edges / for a lift | −45 dB ≥ 0.05 s / −35 dB ≥ 0.8 s, 0.1 s guard | `backend/app/media/toolchain.py:581-582`, `:610-612` |
| Bed under voice | 20 LU (QC band 18-22), fades 0.3/0.8 s, ducking `sidechaincompress threshold=0.03 ratio=6 attack=15 release=350` | `backend/app/media/toolchain.py:590-596` |
| Plan levels | under 0, soft −6, lift +8 dB; ramp 0.4 s; fades 0.3-4.0 s | `backend/app/media/toolchain.py:604-614` |
| Level correction bounds / mix ceiling | −60..+30 dB / 0.97 FS | `backend/app/media/toolchain.py:624-627` |
| Measurement timeout | 300 s (filters probe 60 s) | `backend/app/media/toolchain.py:171`, `:304-310` |

## Modules

### `app.media.stills_stage` — `backend/app/media/stills_stage.py` (2544 lines)

The stills step of one film: plan, refusals, the Owner's gate, the purchase (per request or
in RunPod rounds), judging, the Director's second look, re-rolls, rewrites, holds, settlement.
Its 79-line module docstring (`:1-79`; item 6 on her look, `:38-48`) is the authoritative
summary; the code follows it, with the exceptions noted under Oddities. `_settle_round` is the
one judgement of a round shared by the per-request path, the RunPod rounds and the assembler's
paid still redo (`backend/app/media/assembler.py:16571`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `still_negative` | 239 | Builds the negative prompt: `STILL_NEGATIVE`, faces when the bible bans them (`_bible_bans_faces`, `:224`), the plan's `avoid` items, ≤ 400 chars. | Panels/lettering refusals of 2026-10-11/12 said in the negative channel (ADR-POSITIVE-PROMPTS-ONLY); not part of the still's identity so approved stills stay approved (`:196-202`). | CODE_RULE |
| `StillsStageRefused` (`__init__` 307, `http_status` 324) | 300 | The step bought nothing: status, Romanian reason, approval id, lint findings, plan. 202 for NEEDS_APPROVAL else 409. | The route answers with the reason the Owner reads. | CODE_RULE |
| `is_serial_package` | 404 | Whether a scene's package was composed by the serial composer: `in_frame` is a list and `shot_size` is set. | Lets `_scene_picture` (and clip QC's `assembler._clip_plan`) recognise a serial scene from its package alone. | CODE_RULE |
| `serial_scene_picture` | 412 | A serial scene's written picture: «<room>. In frame: <short names>. <first moment of the action>.» built with `prompt_agent._short_name` and `_still_moment`. | 2026-10-12, f06808c9 scene 1: the writer's line «Marcus alone at his desk» against a beat with Marcus and Sarah in frame refused every correct still (`:417-419`). | CODE_RULE |
| `_scene_picture` | 437 | The scene's written picture for the gate: for the serial (`serial=True` or a serial package) the composed beat; else `writer_visual`, else `visual_prompt` when it differs from the still prompt, else "". | 2026-10-12: `visual_prompt` equals the compiled prompt on several boards (`:446-450`). | CODE_RULE |
| `_still_plan` | 460 | The single builder of the `StillPlan` the gate judges against (words, look, move, bible, picture, narration, purpose, must_fix). | So no path (per request, rounds, redo) can leave the fix check out. | CODE_RULE |
| `_read_scenes` | 481 | Reads every scene: whether the film is an episode of the serial (`editorial.is_serial_film`, `:496-498`), kind, words, identity (`still_fields(visual, reference)`), reference picture (or `ReferenceRequired` text), negative, written picture, the still layer's open `must_fix` items (`:543-548`), reusable APPROVED take, pending takes, roll count, then scene memory (attempts, hold). | The step's one reading of the film; identity is what `assemble_from_takes` looks for. | CODE_RULE |
| `_pending_takes` | 595 | SUBMITTED takes and unjudged PAID candidates of the scene's current identity. | Such a scene is collected/judged, never bought again. | CODE_RULE |
| `stills_plan` | 618 | The plan the Owner is shown and its `plan_hash`: to_buy/pending/held/needs_reference, per-scene credits, cost, cap (with RunPod round overhead × series), USD figures, price source. 0 credits, no network. | One yes per exact plan; any change is a new plan. | CODE_RULE + CONFIG (price table) |
| `needs_reference_reason` | 714 | Romanian sentence for a film whose locked character lacks a reference. | Used by the step and by `shooting_sheet`/`assembler`. | CODE_RULE |
| `attempts_reason` | 726 | Romanian sentence for the paid-attempt limit. | ADR-SCENE-MEMORY. | CODE_RULE |
| `_scene_status` | 739 | COMPOSED / APPROVED / NEEDS_REFERENCE / PENDING / NEEDS_OWNER / TO_BUY / WAITING per scene. | The plan's line per scene. | CODE_RULE |
| `_references` | 795 | Pictures sent with a request: character reference first (only to an adapter with `ACCEPTS_REFERENCE_IMAGE`), Figure 1 second (not for scene 1; not gated by `ACCEPTS_REFERENCE_IMAGE`), truncated to `MAX_REFERENCES` when the adapter declares one. | Face from the reference, light from scene 1; never report a reference the model did not bind. | CODE_RULE + EXTERNAL (adapter declaration) |
| `references_sent` | 827 | List of roles actually sent (`character`, `figure_one`), recorded on the scene. | Record of what the model was handed (2026-10-09). | CODE_RULE |
| `_read_balance` | 841 | (read, balance, problem) from the adapter's `credit_balance()`; adapters without it are not read; a reader that raises gives a problem; a non-number answer (None) gives (True, None, None), which the callers treat as "no balance to compare". | Balance rule; a read that fails stops the purchase. | EXTERNAL |
| `_buy` | 866 | One request: `generate_candidates` (with `on_submitted` when supported) or N × `generate_image`; returns candidates and the vendor's quoted credits. | **Spends money** (vendor call). | EXTERNAL |
| `_judge_candidate` | 912 | Local checks; if none blocks, the injected `judge` (default `judge_still`, the vision model); `still_gate.decide`. | Local checks are free; the model sees only what they did not stop. | LLM_CHECKED_BY_CODE |
| `_set_verdicts` | 944 | Writes APPROVED (chosen, `approved_by='still_gate'`), PAID (passing runner-up) or REJECTED (`LOCAL.STILL_GATE` + reasons) under the write lock; clears the UNJUDGED mark; syncs RunPod quality. | One place for the gate's verdicts on takes. | CODE_RULE |
| `_RoundEnd` (`approved` 1002) | 987 | What a judged round leads to: an approved take (by the gate or her look), another round with an instruction, or an outcome; `approved()` gives the scene's entry, with `approved_by`, `director_look` and `minor_defects` when they apply. | One result shape for the three buyers. | CODE_RULE |
| `_director_looks` | 1038 | Her second look at each refused candidate `still_gate.may_be_overturned` allows, fewest violations first, one `fix_check.director_second_look` per picture; returns the first `look_accepts` keeps, else the CONFIRMED reasons. Buys nothing. | The Owner, 2026-10-12: the LLM is on subscription, images cost (`:977-984`). | LLM (within the set code allows) |
| `_after_approval` | 1080 | For an approved take: `fix_check.record_take_note` (minor traces, her look) and, when the scene had `must_fix` items, `settle_lessons` (confirms the review's lessons when every item is gone). | What was accepted travels with the take; a lesson is confirmed only by a clean still. | CODE_RULE |
| `_settle_round` | 1110 | One judged round: `choose_best` → APPROVED; else `round_step`, her look first for reroll / rewrite / needs_owner (approve by look → APPROVED), lessons withdrawn when a corrected mistake persists and the step is not a re-roll, then a re-roll instruction, COMPOSE_LOCALLY, or NEEDS_OWNER (with `rewrite: true` for a rewrite and `director_confirmed`); no candidate → NEEDS_OWNER «nicio imagine». | The same judgement in the per-request path, the RunPod rounds and the paid still redo. | CODE_RULE + LLM (her look) on LLM-fed reports |
| `_claim_intent` | 1187 | Matches a delivered candidate to the SUBMITTED take of its task. | Candidates land on the row written when the vendor accepted. | CODE_RULE |
| `_settle_pending` | 1202 | For a scene not bought this step: judge collected/unjudged candidates (0 credits); if none passes, her look first (`:1253-1260`); else report NOT_BOUGHT / IN_FLIGHT. | A paid candidate is judged before anything is bought again. | LLM_CHECKED_BY_CODE + LLM (her look) |
| `settle_stills` | 1284 | Collects SUBMITTED still tasks (free GET), judges every unjudged PAID candidate; emits `media.stills_settled`. No purchase, no yes asked. | A film whose only open scene holds such candidates would otherwise never be looked at (2026-10-02, A7). | CODE_RULE (+ LLM looks) |
| `_StillRounds._prepare` | 1436 | Fixes a scene's references for its rounds; marks reference use unverified when the adapter's `REFERENCE_IMAGE_VERIFIED` is false. | Record what was sent. | CODE_RULE |
| `_StillRounds._carries_figure` | 1450 | Whether the scene's request would carry Figure 1 with this adapter. | Only such scenes wait for scene 1 (2026-10-09 starvation). | CODE_RULE |
| `_StillRounds._requests` | 1458 | Builds `BatchRequest`s: one per candidate, seed `item_seed(board, scene, rolls+attempt, candidate)`, negative prompt, references, price in USD. | Re-rolls are new throws; the same keys make a resend a free reuse. | CODE_RULE |
| `_StillRounds.price` | 1492 | Round credits = per-image × items + overhead. | Price a round before sending. | CODE_RULE |
| `_StillRounds._send` | 1496 | Applies the attempt limit, counts the request, returns its batch items. | Attempt limit per scene. | CONFIG |
| `_StillRounds.submitted` | 1509 | Records the SUBMITTED take with RunPod's item id before any poll. | Money on the books before waiting. | CODE_RULE |
| `_StillRounds.landed` | 1526 | A COMPLETED item: write file, record PAID+UNJUDGED take, judge at once. A failed item: REFUSED take (`VENDOR.UNANSWERED` with credits when uncertain). | Judge while the worker makes the next one. | LLM_CHECKED_BY_CODE / EXTERNAL |
| `_StillRounds.unsent` | 1602 | Items the GPU-off proof showed never queued: takes recoded not queued; a fully proven scene is no longer uncertain. | Nothing bought → nothing held. | EXTERNAL proof → CODE_RULE |
| `_StillRounds._decide` | 1628 | After a round: a passing candidate → `_settled` (even in an uncertain or cancelled round, `:1632-1633`); an uncertain, cancelled or empty round refuses its candidates without her look (`:1634-1638`), then UNANSWERED stop, NOT_BOUGHT (proven unsent / cancelled), one retry when the worker made nothing; else `_settled`. | Same ladder as the per-request path. | CODE_RULE (on LLM-fed reports) + LLM (her look, through `_settled`) |
| `_StillRounds._settled` | 1671 | Calls `_settle_round`; sets Figure 1 when scene 1 is approved, counts a re-roll and records `director_confirmed`, or keeps the outcome. | One judgement for every buyer. | CODE_RULE + LLM (her look) |
| `_StillRounds.next_round` | 1698 | Next round = scenes sent back + the waiting scenes once Figure 1 exists; waiting scenes NOT_BOUGHT when scene 1 ended unapproved. Runs inside the GPU session, so her looks happen there. | Never buy blind. | CODE_RULE |
| `_StillRounds.run` | 1730 | Builds round 1, calls `gpu_batch.run_rounds` with callbacks, decides undecided scenes (her look may run here after the session closed), writes hold events (`STILL_HOLD_EVENT`, with RunPod hold items). | RunPod Serverless purchase path. | CODE_RULE |
| `run_stills_stage` | 1837 | The step: refusals (UNPRICED, STALE_PLAN, NEEDS_REFERENCE, NEEDS_SHOT_PLAN, LINT_BLOCKED, LOW_DISK, GPU precheck, unasked kernel refusal, LOW_BALANCE), `may_act`, `PurchaseGuard`, the per-scene loop (STOP, guard, attempts, cap, balance, uncounted drop, buy, failure handling, judging, `_settle_round`), RunPod rounds, measured credits, summary event `media.stills_step_finished`. | The first, cheapest paid stair; the only place stills are bought. | OWNER (yes) + CODE_RULE + LLM_CHECKED_BY_CODE + LLM (her look) |

Helpers: `_bible_bans_faces` (224, bible text mentions no faces), `_Ledger.committed` (388,
committed credits live on the caller's `SpendMeter`), `_usd_ro` (395, «2,16 USD»), `_canonical`
(400, sorted compact JSON for the hash), `_palette_words` (757, colour words of the look),
`_bible_rules` (768, continuity rules for the gate), `_prompt` (779, words + re-roll
instruction + figure sentences), `_event` (834, append one storyboard event), `_hears_submits`
(855, does the vendor method accept `on_submitted`), `_not_looked_at` (901, a NOT_RUN judgement),
`_approve_by_look` (1017, the take APPROVED by `director_look`, failure cleared, RunPod quality
synced as accepted).

Data read: `Storyboard`, `StoryboardScene` (`prompt_json`, `character_ids_json`,
`voiceover_segment`, `story_purpose`), `ScriptDraft` (serial or not), `SceneTake`, character
references via `assembler.scene_reference`, scene memory events, fix-check events (layered
findings). Data written: `SceneTake` rows (SUBMITTED/PAID/APPROVED/REJECTED/REFUSED,
`approved_by` `still_gate` or `director_look`, measured credits), still files under
`<storage>/<board>/stills/`, events `media.still_needs_owner` (`STILL_HOLD_EVENT`),
`media.stills_settled`, `media.stills_step_finished`, `media.take_quality_note`
(`fix_check.record_take_note`), `media.director_second_look` and her AGENT_OPINION memory (through
`second_look._record`), confirmed or withdrawn prompt lessons (`fix_check.settle_lessons`),
measured prices (`economy.credits.record_measured_prices`). External calls: image vendor
(`_buy`, **money**), RunPod batch (via `gpu_batch`, **money**), vendor balance reads, vision
model (tokens) for the gate and for the Director's look.

### `app.media.gpu_batch` — `backend/app/media/gpu_batch.py` (544 lines)

A paid step on RunPod Serverless as rounds of one batch inside one GPU session, switched off in
`finally`. Used by the stills step and by the assembler's motion step and still redo.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `gpu_precheck` | 87 | Calls `gpu_session.precheck` before the Owner's yes is asked or spent; raises `GpuSessionRefused` (unsent): OWNER_HOLD, NOT_CONFIGURED, BLOCKED_INFRA_DISABLED, WEIGHTS_NOT_READY, WEIGHTS_MISMATCH (`backend/app/providers/runpod/gpu_session.py:701-753`); a mock passes. | ADR-RUNPOD-PRECHECK-BEFORE-YES: a card not yet accepted must not cost a yes. | OWNER (GPU stop, card) + CONFIG + EXTERNAL (weights) |
| `fit_round` | 112 | Sorts by (attempt, scene, candidate) and pops from the end until the price fits the cap left. | First tries before re-rolls (2026-10-09). | CODE_RULE |
| `_stop_status` | 134 | Keeps BLOCKED_MODE / BLOCKED_NO_BUDGET as the refusal status when the guard recorded them and RunPod answered paused. | The day reads it as the Owner's decision, not a film fault. | CODE_RULE |
| `_bought` | 145 | Whether the step's meter holds a purchase. | Decides refuse-unsent vs end-on-what-was-bought. | CODE_RULE |
| `_refusal_record` | 151 | {code, http_status, detail ≤ 300 chars} of the refusal. | RunPod's own words on the sheet. | EXTERNAL |
| `_gpu_for_rounds` | 163 | Opens `gpu_session`; if it refuses after something was bought elsewhere, yields None and records the refusal. | Review 2026-10-10: a purchase must not leave the books. | CODE_RULE |
| `_keep_alive` | 190 | Renews the session; returns the forced-off words on `GpuForcedOff`. | The Owner's «Oprește GPU acum» or the guard. | OWNER / CODE_RULE |
| `_settle_earlier_holds` | 199 | After a proof, releases earlier holds the proof covered (`runpod_unsent.settle_proven_holds`); failures only logged. | A redo's proof also proves the earlier /run. | CODE_RULE |
| `_prove_unsent` | 217 | After the close, asks `run.prove_unsent(session)`; if proven, calls `on_unsent`, marks rows unsent, gives back the whole round (no job accepted) or the proven items' share, rewrites the stop words. | ADR-RUNPOD-UNSENT-PROOF: never-queued is proven, not assumed. | EXTERNAL → CODE_RULE |
| `run_rounds` | 278 | Loop: stop/guard check → fit to cap → book the round's price → `adapter.submit_batch` (**money**) → poll, `on_outcome` each item (the caller's judging: a vision-model look per still, clip QC per motion clip), renew the session, stop on forced-off/weights/deadline/STOP/mode → give back unmade items → settle → raise meter to measured GPU seconds → stop on uncertain or refused → `next_round`. After the session: proof, refusal words, weights card. | ADR-RUNPOD-BATCH-ROUNDS, ADR-GPU-OFF-IMMEDIATELY, ADR-RUNPOD-BOOKING-NEVER-BELOW. | CODE_RULE + EXTERNAL + OWNER (stops) |

Helpers: `_order` (100, the sort key (attempt, scene number, scene id, candidate) that
`fit_round` cuts by).

Data written: the caller's `SpendMeter` (`committed`, `attempts`), RunPod journal rows (through
`providers.runpod.batch`), the weights card (`providers.runpod.weights.raise_weights_card`).
External calls: RunPod `/run` (money), status polls, purge/cancel/off (through `gpu_session`).

### `app.media.runpod_unsent` — `backend/app/media/runpod_unsent.py` (961 lines)

Finds scenes held by a RunPod /run that got no job id, classifies the journal rows the hold
rests on, releases them on proof or on the Owner's card. Nothing is sent or bought here.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `card_key` | 149 | `runpod_unsent:<hold event id>`. | One card per hold, ever; a "no" stands. | CODE_RULE |
| `Candidate.rows_in`, `.all_proven` | 179, 183 | Rows by class; whether every row is PROVEN. | Release-by-proof test. | CODE_RULE |
| `_row_class` | 240 | OPEN / ELSEWHERE / PROVEN / OWNER / UNSENT_AT_SEND / IN_FLIGHT / CHANGED. | What became of each row since the hold. | CODE_RULE |
| `_hold_rows` | 284 | Rows of a hold: named in the event (since 2026-10-09), else the session proof's items, else rows created while the session was open (+ reused unnamed uncertain rows). | Holds from before row naming existed. | CODE_RULE |
| `_hold_takes` | 349 | The hold's REFUSED `VENDOR.UNANSWERED` takes (named, or same correlation and before the hold). | Takes to recode on release. | CODE_RULE |
| `_hold_shape` | 386 | (scene, purpose, take kinds) of a still/motion hold whose `failure_kind` is UNANSWERED and that holds. | Filters the holds this module handles. | CODE_RULE |
| `_superseded` | 403 | True when, since the hold, a take of the scene was retired by the Owner (`_OWNER_RETIRED_CODES`), decided (`TAKE_DECIDED_EVENT`), approved (by anyone), or a model was set for the scene (`SCENE_MODEL_SET_EVENT`, motion only). | Do not ask about a question already answered. | CODE_RULE (reads past decisions) |
| `_candidate` | 453 | Matches a hold to its closed GPU session, rows and takes; refuses (logs `runpod_unsent_hold_unmapped`) when counts disagree. | Every uncertain item must have its refused take. | CODE_RULE |
| `candidates` | 518 | Every unreleased, unsuperseded hold of this kind. | Input of the passes. | CODE_RULE |
| `recorded_problems` | 542 | Problems that make the record unclean: jobs accepted, off not verified, non-zero counts, shared endpoint, purge removed jobs, non-gap proof problems, overlapping sessions, billed rows. | A card is offered only on a clean record. | CODE_RULE (on EXTERNAL readings) |
| `_record_ro` | 633 | What the close and the in-step proof recorded and what they could not (queue before purge, purge count, bucket), built from the record; `LEGACY_GAP_RO` for sessions with no evidence. | The card says what is known and what is missing, never assumed (2026-10-09 review). | CODE_RULE |
| `release_card` | 672 | The Owner's card: what was recorded, what it does not prove (`_record_ro`, 633), where to check in the RunPod console, options release/keep. | ADR-RUNPOD-UNSENT-PROOF: a legacy hold is the Owner's card. | CODE_RULE (wording) |
| `release_cards` | 738 | Cards for clean, not-all-proven holds (used by the boot seed and the watchdog). | | CODE_RULE |
| `_release` | 762 | In the caller's transaction: on the Owner's card OPEN rows → FAILED/UNSENT at 0 cost; takes recoded RUNPOD.NOT_QUEUED; event `media.runpod_unsent_hold_released`. | Release in one transaction. | OWNER / CODE_RULE |
| `settle_proven_holds` | 854 | Releases, without the Owner, holds whose rows a later proof all covered and nothing billed; re-checked under the write lock. | A redo's proof covers the earlier /run. | CODE_RULE |
| `propose_release_cards` | 886 | Watchdog pass: settle proven holds, then propose clean cards never asked before (`propose_owner_decision`). | | CODE_RULE |
| `apply_release` | 909 | The Owner's accept: idempotent by command id; re-checks hold, supersession and blockers under the write lock; releases or raises `DecisionApplyFailed`. | A hold that changed meanwhile is not released. | OWNER |
| `hold_cleared` | 950 | Whether the card's question went away (released, superseded, or a row answered since). | Withdraws the open card. | CODE_RULE |

Helpers: `_moment` (189), `_count` (197), `_output` (201), `_uncertain_row` (205),
`_resent_uncertain` (214), `_was_uncertain` (223), `_unnamed_uncertain` (233), `_rows_by_id`
(259), `_proof_payloads` (268, `batch.PROOF_EVENT` payloads), `_holding_take` (340), `_is_gap`
(538), `_billed` (586, a row that cannot be read counts as billed), `_nonzero` (596, an
unreadable amount counts as something), `_blockers` (606), `_when_ro` (620), `_first_upper`
(628), `_ever_asked` (748), `_hold_event` (848).

Data read: `DomainEvent` (holds, proofs, decisions, model sets), `GpuSessionRow`,
`GenerationJob`, `SceneTake`, `OwnerDecision`, `CommandRecord`. Data written: `GenerationJob`
(status, error code, cost "0", `output.not_queued`), `SceneTake` (recode), events, Owner
decision cards, command records. External calls: none.

### `app.media.services` — `backend/app/media/services.py` (2160 lines)

Character bibles, storyboard generation under the content gate, scene-kind and card checks,
storyboard listings, and the Owner-pressed purchase of character reference sets.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `seed_default_character_bibles` | 579 | Inserts the 8 default characters (`DEFAULT_CHARACTERS`, `:47-568`) if missing; fills empty persona fields and an empty `employee_id` from the active agent of the role; never overwrites. | Idempotent seed safe on every read. | CODE_RULE (defaults held in code) |
| `list_character_bibles` | 643 | All bibles as `CharacterBibleView`. | API read. | — |
| `get_character_bible` | 651 | One bible. | API read. | — |
| `_character_keys` | 678 | (given name, full forms) of a canonical name, skipping titles (`dr`, `mr`, ...). | Scripts write "Sarah", "Aris". | CODE_RULE |
| `_characters_named_in` | 697 | Characters a text names, case-sensitive, whole names always, bare given names only when asked and not followed by another capitalised word. | "Vera Rubin Observatory" is not the Publisher; "Hurricane Elena" was measured as a false hit. | CODE_RULE |
| `_scene_visual` | 733 | `visual_prompt` / `visual_cue` / `visual_description` / `Scene N`. | One reading of what a scene shows. | CODE_RULE |
| `_scene_cast` | 748 | (stated, guessed): the writer's cast list per entry + whole canonical names in the visual; guesses = bare given names in the visual. Narration not read. | A cast steers a paid render and refuses a locked look: never on a guess. | CODE_RULE |
| `_read_unit` | 926 | (kind, scale, currency, word) from the up to four words after a number: percent words, scales (thousand…trilioane), currency words, `_NOT_UNITS` stop words, word units (km, t, people). | Romanian and English claims and cards read alike. | CODE_RULE |
| `claim_quantities` | 962 | Every number in a sentence with its unit (percent, money+currency, word unit, plain, scale). | Card numbers checked against claims. | CODE_RULE |
| `card_unit` | 993 | A card's unit text read as a unit of 1. | | CODE_RULE |
| `classify_scene_kind` | 1051 | Composed kinds kept; LIVE/unknown overruled by kind phrases (`prompt_lint.classify_kind_phrase`) or by two comparable percent/money amounts the claims carry → DATA_CARD. Returns (kind, forced_by). | SCENE_KINDS (2026-09-27): a chart or black screen never reaches a photographic model. | CODE_RULE over LLM |
| `card_problems` | 1104 | Romanian problems of a composed card: missing data card, invalid spec, bars citing unknown / non-SUPPORTED claims, values not carried with the unit, numbers in the card's words not carried. | "The studio never makes them up." | CODE_RULE |
| `card_claim_ids` | 1161 | Claim ids named by a card's bars. | | CODE_RULE |
| `_board_scene_kinds` | 1178 | Per scene: kind, card, problems, re-reading claim statuses now. | A claim refuted after the script must not put its number on screen. | CODE_RULE |
| `generate_storyboard_from_script` | 1237 | Content gate (autonomy stop, APPROVED, no unverified claims), supersede unrendered boards, fallback single scene, cast, kinds/cards (refuse on problems), event `media.storyboard_created`, Storyboard APPROVED, scenes with stated cast only. | The handover from research to production; no money. | CODE_RULE |
| `list_scripts_awaiting_storyboard` | 1459 | APPROVED scripts with no storyboard. | The handover had been a demo fixture only. | CODE_RULE |
| `storyboard_cast_record` | 1491 | Reads the creation event's `cast_note` and `guessed_cast`. | "Nobody said" vs "nobody is in it". | — |
| `storyboard_cast_note` | 1524 | The note alone. | | — |
| `get_storyboard` | 1533 | View + scene kinds/cards + cast note + newest render's motion decisions. | So the Owner can read which model filmed each scene and why, instead of taking it on trust (`:1554-1556`). | — |
| `_newest_publications` | 1583 | Newest publication per board (status, YouTube visibility, link, channel). | 2026-10-11 published film not shown. | EXTERNAL (recorded YouTube data) |
| `films_now` | 1616 | Board status + newest publication for given boards. | A day's record is not updated after a later finish. | — |
| `list_storyboards` | 1650 | One page (≤ 100) of summary rows with scene count, newest finished asset, QC verdict, publication; hides boards a story repair replaced; optional `qc_status` filter. | PAGE-17; one board per film in the list. | CODE_RULE |
| `ReferenceSetError.__init__` | 1775 | Closed vocabulary reason (`AUTONOMY_STOPPED`, `NO_CHARACTER`, `NO_IMAGE_PROVIDER`, `BUDGET`, plus kernel statuses and `LOW_BALANCE`). | Page matches on it. | — |
| `_reference_prompt` | 1788 | Slot prompt from the bible and the series look's rendering only. | References in the serial's style. | CODE_RULE |
| `_published_image_price` | 1829 | (USD, credits) of one picture from `shooting_sheet.price_table_for`. | Runway's seedream has no catalogue price. | CONFIG (price table) |
| `_refuse_on_low_balance` | 1845 | Reads the balance before the first slot (adapters without a reader are not asked); a read that raises, or a balance < credits × slots × 1.15, → `ReferenceSetError(LOW_BALANCE)`; no credit price or a non-number balance → no comparison. | One round, never re-rolled. | CODE_RULE + EXTERNAL |
| `generate_character_reference_set` | 1873 | Owner press only: kernel (`media.character_reference_set`, `ask_owner=False`), adapter (`image_provider`), price, balance, `reserve_spend`, one `generate_image` per slot (**money**), assets + events, slot ids, `record_provider_cost` ESTIMATED per slot, settle or release the reservation. | MONEY-13; spec 24 "Producing a reference set". | OWNER + CODE_RULE |
| `image_reference_for_scene` | 2118 | Walks the scene's characters in the writer's order: an unlocked one without a stored reference is skipped, a locked one without one raises `ReferenceRequired`, the first with a reference (slot order) is returned and the walk stops. Called only through `factory.reference_payload` (`backend/app/media/factory.py:880`). | A locked face is never invented. | CODE_RULE on OWNER lock |

Helpers: `_to_float` (908, "83,3", "1.000"), `_unit_words` (922),
`_same_number` (1000, rounding as written: 83 stands for 83.3, 84 does not), `_same_unit`
(1013), `_carries` (1023), `_comparable_numbers` (1031), `_card_text_numbers` (1079),
`_scene_narration` (1172).

Data read: `CharacterBible`, `Agent`/`Role`, `ScriptDraft`, `FactualClaim`, `Storyboard`,
`StoryboardScene`, `VideoRenderJob`, `QualityControlReport`, `PublicationRecord`,
`ChannelRecord`, `DomainEvent`, `OwnerPolicy`, `Integration`. Data written: `CharacterBible`,
`Storyboard`, `StoryboardScene`, `MediaAsset`, events `media.storyboard_created`,
`media.character_reference_generated`, budget reservations, provider cost rows. Files:
`backend/storage/character_references/<id>/<slot>.<ext>` (`REFERENCE_STORAGE_ROOT`, `backend/app/media/services.py:1763`).
External calls: image vendor and its balance (reference sets only).

### `app.media.factory` — `backend/app/media/factory.py` (1005 lines)

Which media adapter may be used: only selected and verified connections with discovered
models; paid vendors kept off the legacy whole-film render; the production hierarchy's
per-scene plan; the image vendor chain.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `PaidVendorRefused.__init__` | 81 | Names the vendors and the Owner's Romanian message «Folosește foaia de filmare… Nimic nu a fost cumpărat». | | — |
| `is_paid_vendor_class` | 96 | True if any class in the MRO is defined under `app.providers` outside `FREE_PROVIDER_MODULES`. | Default deny: a new vendor is paid until listed free in review. | CODE_RULE |
| `is_paid_vendor_adapter` | 106 | Same for an instance; None, fakes and local stand-ins are not paid. | | CODE_RULE |
| `paid_vendors_of` | 116 | Names of the paid vendors among adapters. | | CODE_RULE |
| `legacy_render_vendors` | 121 | Every paid vendor the whole-film render would be handed (image, chain, voice, per-scene voices and speakers). Calls none. | Checked before any render job exists. | CODE_RULE |
| `guard_motion_chooser` | 160 | Wraps the render's motion chooser to raise `PaidVendorRefused` before a paid video adapter is used. | Motion is chosen per scene inside the render. | CODE_RULE |
| `abandon_unfinished_renders` | 178 | Fails a board's renders started since a moment and left unfinished by the refusal. | No job stays RUNNING. | CODE_RULE |
| `image_provider` | 241 | Adapter for the "image" purpose: RunPod (`wiring.connection`), ComfyUI, Runway (model from catalog), OpenAI; None otherwise. | Selected and verified only. | OWNER + CONFIG + EXTERNAL |
| `image_provider_for` | 294 | Same for one resolved selection. | Production hierarchy. | OWNER + CONFIG |
| `tts_provider` | 348 | ElevenLabs adapter when model and voice resources exist; else None. | | OWNER + CONFIG |
| `pronunciation_locators` | 384 | The Owner's ElevenLabs dictionaries from a voice binding (≤ 3, via `checked_locators`). | The studio never writes to the Owner's account. | OWNER |
| `vendor_licence` | 418 | {vendor, terms, commercial_use True only on "da", source}. | AR-15: public only with commercial-use evidence. | OWNER |
| `connection_of_model` | 443 | The connection a model belongs to (selected one first). | Books price by model's connection. | CODE_RULE |
| `tts_provider_for` | 463 | ElevenLabs adapter for a valid resolved voice, with settings and the character's dictionaries. | | OWNER + CONFIG |
| `video_provider_for` | 498 | RunPod / ComfyUI / Runway video adapter with the model's contract, only for a discovered model. | | OWNER + CONFIG + EXTERNAL |
| `motion_for_scene` | 543 | Card kinds → no model; else `production_policy.choose_model` with a `SceneRequirement` (TEST prompt-to-video, PRODUCTION image-to-video), honouring `forced_model` and `exclude`. Returns adapter + decision. | Model chosen by requirement, decision travels with the adapter. | CODE_RULE + OWNER override |
| `render_plan` | 626 | Resolves the storyboard plan (`resolve_storyboard_plan`, `plan_speakers`), builds cached voice/video adapters per scene, per-speaker takes (a broken locked voice leaves the scene voiceless), the image chain, reference loader. | Legacy render and TEST media stage. | CODE_RULE |
| `describe` | 744 | Image and voice provider names, no probing. | Preflight / page. | — |
| `media_readiness` | 780 | Per purpose (image, voice): READY / NO_SELECTION / NOT_VERIFIED / NO_DEFAULT / NO_ADAPTER with the Owner's next step (RunPod image also needs the result bucket). | Names the missing step instead of "no verified provider". | CODE_RULE |
| `accepts_reference_image` | 858 | `ACCEPTS_REFERENCE_IMAGE` attribute, default False. | Silence is not a capability. | CODE_RULE |
| `reference_payload` | 868 | Reference with its bytes (cached); unreadable required reference → `ReferenceRequired`. | | CODE_RULE |
| `image_adapter_chain` | 898 | Resolved selection then fallbacks; TEST orders by recorded price, unpriced last. | Second vendor when the first refuses. | CODE_RULE + OWNER (approved alternatives) |
| `still_from_chain` | 939 | Tries each adapter's `generate_image` (**money**) until one answers; records attempts with estimated USD (None when unpriced); drops a reference for adapters that cannot take one; raises the last refusal with attempts. | Lost stills were left out of the day's spending. | EXTERNAL |

Helpers: `_vendor_name` (112), `_selected` (202, selected + verified), `_runway_metadata`
(212), `_from_connection` (224, marks `integration_id` for the books), `_binding_of` (397).

Data read: `ServiceSelection`, `Integration` (decrypted secrets through the vault),
`MediaProductionConfig`, `ProviderResource`, `CharacterBible`, `VideoRenderJob`. Data written:
`VideoRenderJob` (abandon). External calls: image vendors in `still_from_chain` (money).

### `app.media.toolchain` — `backend/app/media/toolchain.py` (1162 lines)

Finds ffmpeg/ffprobe; the one loudness reading both the renderer and QC use; the audio master;
silence measurement; the ducked music bed mix. No money, no model.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `find_ffmpeg` | 87 | Configured path if it is a file, else PATH. | | CONFIG (`STUDIO_FFMPEG_PATH`) |
| `find_ffprobe` | 95 | Configured, PATH, or beside ffmpeg. | WinGet puts only ffmpeg on PATH; REL-13 `.env` reading. | CONFIG |
| `parse_loudnorm_json` | 176 | Reads loudnorm's JSON report from stderr. | Never a number from chatter. | CODE_RULE |
| `loudnorm_filter` | 225 | Two-pass linear filter from a usable measurement, else one pass with `linear=true`. | One-pass breathes on speech. | CODE_RULE |
| `measure_loudness` | 256 | Runs loudnorm into null; None when it cannot measure. | Same filter for renderer and QC. | CODE_RULE |
| `has_filter` | 294 | Whether the encoder has a filter (cached). | Record what could not be done. | EXTERNAL (binary) |
| `limiter_filter` | 329 | `alimiter limit=0.79 level=0`. | `level` default would undo loudness. | CODE_RULE |
| `master_audio_filter` | 338 | loudnorm → 48 kHz → limiter → pad/trim to duration. | | CODE_RULE |
| `loudnorm_warning` | 356 | Romanian warning when loudnorm used dynamic mode. | The Owner should hear it before publication. | CODE_RULE |
| `prelimit_gain` | 381 | Gain needed when one linear gain would push peaks over −2 dBTP. | ElevenLabs takes −23..−25 LUFS. | CODE_RULE |
| `_channels` | 401 | Channel count of the first audio stream via ffprobe; None when unreadable. | Mono is upmixed at full level before limiting/mixing (BS.1770 reads it 3.01 LU louder, `MONO_TO_STEREO_LU`, `:398`). | EXTERNAL (tool) |
| `_prelimit` | 432 | Raises a quiet narration by the gain with a fast look-ahead limiter at `PRELIMIT_LIMIT`, re-measures, corrects the gain up to 3 rounds until within 0.3 LU; writes 24-bit WAV; raises `AudioMasterError` on failure. | Keep the master pass one linear gain. | CODE_RULE |
| `encode_master_audio` | 490 | Measure, optional pre-limit, master pass, AAC encode once, re-measure delivered file. | Nepal −0.93 dBTP. | CODE_RULE |
| `silence_spans` | 638 | silencedetect spans. | Dead air at cuts. | CODE_RULE |
| `speech_edges` | 703 | Leading/trailing silence of a take. | Cut before scene lengths are computed. | CODE_RULE |
| `merge_spans`, `complement_spans` | 727, 740 | Span arithmetic. | | CODE_RULE |
| `speech_and_gaps` | 753 | Speech and silences of the voice (−35 dB ≥ 0.8 s); unreadable → whole film speech. | Lifts only where nobody speaks. | CODE_RULE |
| `level_segments` | 771 | Plan levels → (start, end, gain) with lifts clipped to measured gaps. | Bound the Voice Artist's plan. | CODE_RULE over LLM plan |
| `level_expression` | 796 | `volume` expression of trapezoid ramps. | | CODE_RULE |
| `measure_loudness_in` | 817 | Loudness inside spans (≥ 0.5 s; > 120 spans → whole file). | Bed judged where the words are. | CODE_RULE |
| `mix_bed` | 933 | Voice to stereo; bed looped/trimmed, set under, shaped, ducked, faded, corrected (in speech when planned), ambience placed 16 LU under; sum under 0.97. Returns paths and measurements. | Audit Q1/Q4; the Owner 2026-10-11. | CODE_RULE (clamps LLM plan) |

Helpers: `_read_setting` (63), `_configured_ffmpeg` (70), `_configured_ffprobe` (80),
`_measured_is_usable` (214), `_selection` (811), `_run_mix` (860), `_integrated` (879),
`_integrated_in` (887), `_loudness_in` (897), `_level_counts` (907), `_stereo` (915),
`_correction` (923). Classes: `_EncoderSetting` (47), `AudioMasterError` (325), `AudioMixError`
(634). Files written: mastered track, `*.prelimit.wav` (deleted), mix stems under `work_dir`.

### `app.media.rehearsal` — `backend/app/media/rehearsal.py` (1292 lines)

Rebuilds a film from files already paid for, on a copy, at 0 credits; quality control without
a vision model; the Owner's priced report of what still needs credits.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `ReusedVoice` (`__init__` 162, `health_check` 169, `list_voices` 172, `synthesize` 175) | 150 | A TTS adapter that plays back a recorded file only for the exact words it recorded; other text → `MediaProviderError`. | Narration reused, never bought. | CODE_RULE |
| `first_frame_similarity` | 248 | SSIM of a clip's first frame vs a still (grey 270×480). | Clips filmed from overwritten stills are rejected. | CODE_RULE |
| `_probe` | 210 | ffprobe width/height/duration. | | EXTERNAL (tool) |
| `_authorise` | 299 | Only `owner`, or `test` in TEST. | An agent, AUTORUN or parameter cannot adopt. | OWNER |
| `_check_folders` | 311 | Rehearsal root must not be or contain or be inside the original. | Original is never written. | CODE_RULE |
| `_decide_kinds` | 338 | Kinds by `classify_scene_kind`, cards from the command or the row, `card_problems`; LIVE given a card refused; any problem → `RehearsalError`. | No card without verified numbers. | CODE_RULE |
| `_legacy_manifests` | 398 | Production manifests of COMPLETED renders, newest first, excluding rehearsal renders. | Which model made each file. | CODE_RULE |
| `_still_take` | 525 | Card scene → REJECTED; else local checks (`degenerate, sharpness, motion_blur, faces`); clean → APPROVED by `owner`; flagged → PAID (or APPROVED "doar repetiția" on the Owner's choice). | Adoption is the Owner's act; failures listed with a price. | CODE_RULE + OWNER choice |
| `_motion_verdict` | 592 | Card → REJECTED; unmeasured or SSIM < 0.90 → REJECTED; else PAID (carrying a flagged still's code). | | CODE_RULE |
| `foreseen_spans` | 634 | Scene and shot lengths by the assembler's own formulas. | The sheet used an outdated timeline. | CODE_RULE |
| `_motion_take` | 659 | Clip take and sheet row; `used` only when PAID and ≥ the shot span. | A frozen tail is not motion. | CODE_RULE |
| `_adopt` | 713 | Authorise, check folders, read board/claims/kinds/manifests, need ffmpeg+ffprobe, copy stills/clips/voices byte-for-byte under `legacy/`, build takes, one transaction writing kinds, takes and `media.existing_files_adopted`, then the sheet. | | CODE_RULE |
| `still_redo_words` | 486 | «necesită o imagine nouă (N credite)», or «preț necunoscut»; never 0. | An unknown price is never shown as free. | CODE_RULE |
| `scene_line` | 928 | The Owner's Romanian line per scene and the credits it still needs. | | CODE_RULE |
| `_upsert_take` | 975 | One adopted file → one take; never lowers APPROVED/REJECTED; the Owner's full approval never narrowed; credits unknown (None). | | CODE_RULE |
| `adopt_existing_files` | 1050 | Public adoption only. | Route `render=false`. | OWNER |
| `_redo_prices` | 1089 | Prices for the report: still at the stills tier, motion at 1080p on the scene's model. | | CONFIG (price table) |
| `owner_report` | 1126 | `qc_report.qc_summary_ro` priced; on a writer failure, the verdict and reasons with the failure named. | | CODE_RULE |
| `rehearse` | 1181 | Adopt; refuse to assemble when any scene lacks recorded narration; `assemble_from_takes` with only `ReusedVoice` adapters; QC with `registry=None`; summary and event `media.rehearsal_rendered` / `_not_rendered`. | The first step of the Nepal fix costs nothing. | OWNER + CODE_RULE |

Helpers: `_sha256` (202), `_film_claims` (324), `_scene_entry` (425), `_still_model` (432),
`_motion_origin` (442), `_recorded_characters` (451), `_check_dicts` (458), `_still_price`
(471, stills-tier price or all None), `_voice_row` (507, adopted only when readable and the
recorded character count equals the narration's length), `_needs_still` (912), `_sentence` (919), `_lines_from_film` (1157). Command
schema `AdoptExistingFilesCommand` (130, `extra="forbid"`).

### `app.media.local_media` — `backend/app/media/local_media.py` (106 lines)

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `is_local` | 22 | Whether an adapter is a `ComfyConnection`. | | CODE_RULE |
| `writer_constraints` | 28 | When the video selection is ComfyUI with a discovered `max_seconds` > 1: a prompt paragraph telling the writer the shot limit, scene count and words per scene. | The writer writes for the local model's real limit. | OWNER (video selection) + EXTERNAL (discovered `max_seconds`) |
| `local_prices` | 66 | Replaces price rows of verified, available ComfyUI resources with 0-credit DOCUMENTED rows; sets the local stills model when ComfyUI is the image selection. | Local models cost 0 credits. | CONFIG |

### `app.media.disk` — `backend/app/media/disk.py` (126 lines)

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `media_root` | 45 | `settings.media_root` else `assembler.DEFAULT_STORAGE_ROOT`. | REL-08. | CONFIG (`STUDIO_MEDIA_ROOT`) |
| `min_free_gb` | 55 | Settings' value, else `.env`/environment, else 20. | | CONFIG (`STUDIO_MIN_FREE_GB`) |
| `free_bytes` | 75 | `shutil.disk_usage` of the nearest existing folder (`_existing`, 66). | | EXTERNAL (OS) |
| `gb_words` | 80 | «12,5 GB». | | — |
| `disk_reading` | 87 | OK / LOW / UNKNOWN / OFF with the Romanian reason. | Preflight and operations page. | CONFIG + EXTERNAL |
| `disk_refusal` | 119 | Reason only when LOW. | Paid steps refuse before buying. | CODE_RULE |

### `app.media.storage` — `backend/app/media/storage.py` (55 lines)

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `media_roots` | 15 | `state.media_storage_root` (set from `settings.media_root`, `backend/app/main.py:687`), the default media folder, the character references folder. | SEC-06. | CONFIG |
| `media_file_inside` | 33 | The resolved regular file inside a root, not a link; else None. | A bad row must not serve any file. | CODE_RULE |

### `app.media.models` — `backend/app/media/models.py` (436 lines)

ORM tables. One function, `_in` (40), builds CHECK constraints. Tables: `CharacterBible` (44:
looks, persona fields that "may not change what an agent is allowed to do" `:60-61`, reference
slots, voice binding, identity locks, approved fallbacks), `Storyboard` (91), `StoryboardScene`
(132: `scene_kind` LIVE / DATA_CARD / TITLE_CARD / BLACK, only LIVE reaches a model `:160-165`),
`SceneTake` (174: the money ledger of pictures; statuses and identity above), `FilmPurchaseLease`
(254: one buyer per film, taken over after `expires_at`), `MediaAsset` (279), `VideoRenderJob`
(310), `QualityControlReport` (341), `CharacterIdentityChange` (361: only APPROVED rewrites a
locked field; "a newer or cheaper model is never a reason for the system to take this path on its
own" `:364-367`), `EditorialReview` (408: the Director's verdict, `model_used` flag).

### `app.media.schemas` — `backend/app/media/schemas.py` (185 lines)

Pydantic views and commands, no functions: `CharacterBibleView` (11),
`CreateCharacterBibleCommand` (37), `StoryboardSceneView` (56), `StoryboardView` (78),
`GenerateStoryboardCommand` (94), `MediaAssetView` (101), `RenderJobView` (118), `QCReportView`
(134), `SheetStepCommand` (146: `plan_hash` 64 hex, `allow_over_budget` = the Owner's explicit
consent to exceed the daily budget/film ceiling for one step, `command_id` for safe replay
MONEY-04), `SceneModelCommand` (166: model id, `LOCAL_MOVE` or null), `TakeDecisionCommand`
(176: APPROVED/REJECTED, `final` marks the Owner's approval as final, 2026-10-11).

### `app.media.__init__` — `backend/app/media/__init__.py` (1 line)

Package docstring only.

## Connections

**Who calls into this group**

| Caller | Uses |
|---|---|
| `app.media.shooting_sheet` | `stills_plan` (`backend/app/media/shooting_sheet.py:1170`), `run_stills_stage` (`:3455`, with `unasked`, `margin`, `meter`, `plan_hash_of`), `settle_stills` (`:3155`), `local_prices`, `paid_vendors_of` (`:3907`), `video_provider_for` (`:4285`), `needs_reference_reason` |
| `app.media.assembler` | `_StillRounds`/`stills_stage` helpers for the still redo (`backend/app/media/assembler.py:16244-16251`, `:16365`, `:16684`), including `_settle_round` (`:16571`, the Director's look before the redo's re-roll), `_scene_picture`, `_palette_words` and `_bible_rules` for clip QC's plan (`_clip_plan`, `:10233-10236`), `settle_stills` (`:15669`), `run_rounds` for motion (`:11335-11344`), `gpu_precheck` (`:11421`, `:16001`), `still_from_chain` (`:2861`, `:2903`), `is_paid_vendor_adapter` (`:3024`), `vendor_licence`/`connection_of_model` (`:6066`), `reference_payload` (`:8408-8410`, the only caller path of `services.image_reference_for_scene`), `accepts_reference_image` (`:15965`), `needs_reference_reason` (`:15960`), toolchain mastering and mixing (`:91`, `mix_bed` at `:5774`, `:5967`), `disk_refusal` (`:11576`, `:15148`) |
| `app.media.router` | routes for character bibles, storyboards, scripts awaiting storyboard, `from-script` (`backend/app/media/router.py:368`), legacy `render` (`:522`, `legacy_render_vendors`, `guard_motion_chooser`, `abandon_unfinished_renders`, `render_plan`), `adopt-existing-files` (`:762`), `reference-set` (`:1241`), take/asset file serving (`media_file_inside`, `media_roots`) |
| `app.runbook.stages` / `preflight` / `services` | `generate_storyboard_from_script` (`backend/app/runbook/stages.py:1119`), legacy TEST media stage (`render_plan`, `tts_provider`, `motion_for_scene`, guards; `:2633-2680`, `:3086-3473`), `media_readiness` (`backend/app/runbook/preflight.py:1582`, `backend/app/runbook/stages.py:1288`, `backend/app/runbook/services.py:1350`), `describe` (`backend/app/runbook/preflight.py:35`), `disk_reading` (`:1285`), `find_ffprobe` (`:1472`), `films_now` (`backend/app/runbook/services.py:2012`) |
| `app.decisions.seed` / `services` / `sources`; `app.workflows.watchdog` | `release_cards`, `settle_proven_holds` (boot), `apply_release`, `hold_cleared`, `propose_release_cards` (`backend/app/workflows/watchdog.py:929-931`), `vendor_licence` |
| `app.factual.agent_pipeline`, `app.factual.story_review` | `classify_scene_kind`, `card_problems` on the LLM writer's scenes (`backend/app/factual/agent_pipeline.py:915-956`); `writer_constraints` (`:721-723`; `backend/app/factual/story_review.py:606-608`) |
| `app.media.qc`, `app.media.sound_design`, `app.media.picture_qc`, `app.media.director_qc`, `app.media.second_look` | loudness/mix constants and measurements; `storyboard_cast_record`; `_bible_rules` (`backend/app/media/director_qc.py:1928`, `backend/app/media/second_look.py:224`) |
| `app.media.sheet_story_repair` | `generate_storyboard_from_script` (`backend/app/media/sheet_story_repair.py:258`) |
| `app.office`, `app.operations`, `app.publishing.licence_release`, `app.integrations`, `app.demo` | file serving, disk reading, licences, `VERIFIED_STATUSES`, demo fixtures |

**What this group calls out to**: `app.media.assembler` (take recording, scene memory, vendor
failure classification, collection, seeds), `app.media.still_gate` (local checks, decide,
`choose_best`, `may_be_overturned`, `round_step`), `app.media.picture_qc` (the gate's vision
look), `app.media.fix_check` (open findings by layer, `director_second_look` → `app.media.second_look`
for the Director's look, `look_accepts`, take notes, lessons), `app.media.prompt_agent`
(`_short_name`, `_still_moment`; lesson confirmation and withdrawal through `fix_check`),
`app.agents.editorial.is_serial_film`, `app.media.prompt_lint`, `app.media.balance_rule`, `app.media.cost_plan`, `app.media.mode_guard`,
`app.media.production_policy`, `app.media.cards`, `app.media.qc`, `app.media.qc_report`,
`app.media.series_look`, `app.media.speaker_voices`, `app.providers.runpod.*` (batch, GPU
session, wiring, weights, jobs), `app.providers.{runway,openai_media,elevenlabs,comfyui,media_http}`,
`app.services.may_act`/`append_event`/`studio_environment`, `app.runbook.services.stop_requested`,
`app.economy` (budget reservations, provider costs, measured prices, price lookup),
`app.decisions.services` (cards, `DecisionApplyFailed`).

**Events emitted**: `media.stills_step_finished`, `media.stills_settled`,
`media.still_needs_owner` (holds), `media.take_quality_note` and `media.director_second_look`
(through `fix_check` and `second_look`), take events via `assembler.record_take`/`_record_intent`,
`media.storyboard_created`, `media.character_reference_generated`,
`media.existing_files_adopted`, `media.scene_take_recorded`, `media.rehearsal_rendered` /
`media.rehearsal_not_rendered`, `media.runpod_unsent_hold_released`, Owner decision cards
(`runpod_unsent_release`), weights cards.

**Events consumed**: `media.still_needs_owner` / `media.motion_needs_owner` (holds),
`batch.PROOF_EVENT`, take-decided and scene-model-set events, `runbook.film_retired` (hidden
replaced boards), `media.storyboard_created` (cast record), fix-check rewrite events (read by
layer), the Director's earlier `media.director_second_look` events (shown to her look).

## Owner touchpoints

| Touchpoint | What the Owner decides | Where |
|---|---|---|
| Paid-step approval of the stills plan (shooting sheet, Decisions window) | Whether this exact plan (hash, cap) is bought; NEEDS_APPROVAL answers 202 with `approval_id` | `backend/app/media/stills_stage.py:2025-2048` |
| Paid-media rule (`EVERY_PAID_STEP` / `OVER_USD` / `MODE`) and autonomy mode | Whether unasked steps run and when a mode change stops them | `backend/app/media/stills_stage.py:1999-2011`, `:2050-2062`; `docs/architecture/51_AUTONOMY_MODE_SEMANTICS.md:75-98` |
| Owner's own press vs unasked | With `unasked=False` (his press) the step skips the pre-balance kernel refusal and the per-request guard goes on through BLOCKED_MODE and NEEDS_APPROVAL (`OWNER_PRESS_PASSES`); the step's own `may_act` must still answer allowed (his yes for this plan), else NEEDS_APPROVAL (202). The reference set, his press only, goes on through both statuses at its single kernel read | `backend/app/media/stills_stage.py:1866-1871`, `:1999`, `:2025-2048`; `backend/app/media/mode_guard.py:208-217`; `backend/app/media/services.py:1821`, `:1913-1919` |
| STOP AUTONOMY | Stops every further purchase; refuses storyboards and reference sets | `backend/app/media/stills_stage.py:2155-2158`; `backend/app/media/services.py:1263-1265`, `:1913-1917` |
| Holds on the shooting sheet (NEEDS_OWNER) | What happens to a scene the gate, a refusal, the attempt limit or an unanswered request left (his decision lifts the hold; so does the Director's still rewrite, `backend/app/media/assembler.py:8786-8796`). Since `5fc7468` the Director looks before a gate refusal becomes a hold: a candidate she lets stand is approved by her and never reaches him, and her confirmation is appended to the reason he reads; a `rewrite` outcome is held too, though its words say the Director rewrites them | `backend/app/media/stills_stage.py:2395-2418`, `:1807-1829`, `:1143-1149`, `:1160-1162`, `:1178-1181` |
| The Owner's rule of 2026-10-12 (the LLM is on subscription, images cost; small defects are accepted) | Set, in conversation, the policy that her free look comes before any paid re-roll and that minor traces pass; it is code, not a setting, so there is no runtime switch for him, and a still her look approves never reaches him | `backend/app/media/stills_stage.py:977-984`; `backend/app/media/fix_check.py:126-130`, `:693-703` |
| Runner-up candidates (PAID) on the contact sheet | Picking another passing candidate (`TakeDecisionCommand`) | `backend/app/media/stills_stage.py:963-964`; `backend/app/media/schemas.py:176-185` |
| Top-up of the vendor balance | Lets a LOW_BALANCE scene continue (not a hold) | `backend/app/media/stills_stage.py:2183-2192`, `:2399` |
| Settings | `paid_step_balance_margin`, `max_paid_attempts_per_scene`, `STUDIO_MIN_FREE_GB`, `STUDIO_MEDIA_ROOT`, `STUDIO_FFMPEG_PATH`, `STUDIO_FFPROBE_PATH` | `backend/app/media/stills_stage.py:1985`; `backend/app/media/assembler.py:8543`; `backend/app/media/disk.py:27-42`; `backend/app/media/toolchain.py:47-84` |
| RunPod card «Agenții pot porni singuri GPU-ul…» and «Oprește GPU acum» | Whether a GPU may start inside an approved step (his stop also refuses a step before its yes, OWNER_HOLD); switching it off mid-round | `backend/app/media/gpu_batch.py:87-97`, `:190-196`, `:421-434`; `backend/app/providers/runpod/gpu_session.py:722-723`, `:767-808` |
| RunPod weights card | Fixing the endpoint's cached model in the console | `backend/app/media/gpu_batch.py:531-537` |
| RunPod unsent release card | «Da, eliberez scena N» or keep held; asked once per hold | `backend/app/media/runpod_unsent.py:672-735`, `:909-947` |
| Character visual locks and reference sets | A locked face without a reference refuses the film; the Owner presses the reference-set route | `backend/app/media/services.py:2118-2160`, `:1873-2115`; `backend/app/media/router.py:1241-1265` |
| Connections | Selection, verification, default models/voices, approved alternatives, licence terms and «da» for commercial use, ElevenLabs pronunciation dictionaries | `backend/app/media/factory.py:202-209`, `:415-440`, `:384-394`, `:898-936` |
| Studio environment TEST / PRODUCTION | Whether the shot plan is required, motion task type, image chain ordering, legacy render behaviour | `backend/app/media/stills_stage.py:1928`; `backend/app/media/factory.py:594-596`, `:921` |
| Rehearsal route | Adopting paid files, cards for charts, `keep_flagged_for_rehearsal` | `backend/app/media/rehearsal.py:130-144`, `:299-308`; `backend/app/media/router.py:762-825` |

## Oddities and gaps

- **Hard-coded "Runway" in vendor-neutral code**: `_read_balance`'s problem text says «soldul
  Runway» for any adapter with a balance reader (`backend/app/media/stills_stage.py:849`), and
  measured prices are always recorded as `{"kind": "runway"}` when an `integration_id` and a
  balance drop exist (`:2497-2512`).
- **Module docstring narrower than the code**: the stills docstring names the model
  `seedream5_pro` and a "Runway balance" (`backend/app/media/stills_stage.py:12-23`); the step
  uses the adapter's own model (`:1891`) and RunPod adapters have no balance reader, so no
  balance rule applies to them (consistent with `docs/project/16_DECISION_LOG.md:4216`).
- **Misleading fallback reason after rounds**: a scene still undecided after `run_rounds`
  gets `self.stop or summary["cap_stop"] or FIGURE_ONE_MISSING` (`backend/app/media/stills_stage.py:1795-1804`).
  When the rounds ended UNCERTAIN (and the close's proof did not turn the stop into
  NOT_QUEUED, `backend/app/media/gpu_batch.py:273-275`), `self.stop` is not set from the summary
  (`backend/app/media/stills_stage.py:1793-1794`) but only when the uncertain scene itself is
  decided (`:1639-1642`); `run_rounds` breaks before `next_round`
  (`backend/app/media/gpu_batch.py:507-512`), so a scene iterated before the uncertain one whose
  final `_decide` asks for a re-roll gets the Figure 1 sentence although it did not wait for
  Figure 1. Since `5fc7468` that final `_decide` (`backend/app/media/stills_stage.py:1795-1797`)
  can also run the Director's look after the GPU session closed: a candidate she accepts is
  approved, and a CONFIRMED reason is recorded as `director_confirmed` on an entry whose re-roll
  is then never bought (`:1688-1694`, `:1798-1804`).
- **A retry counts as a paid attempt**: in the per-request path `requests += 1` happens before
  the vendor call (`backend/app/media/stills_stage.py:2228-2229`), so a TRANSIENT retry
  (`:2281-2283`) consumes one of the scene's `max_paid_attempts_per_scene`.
- **Raw price table when none is passed**: `stills_plan` and `run_stills_stage` fall back to
  `load_price_table()` (`backend/app/media/stills_stage.py:632`, `:1890`), and the rehearsal
  always uses it (`backend/app/media/rehearsal.py:474`, `:1096`), whereas the reference set uses
  `shooting_sheet.price_table_for` (`backend/app/media/services.py:1835-1837`), which applies the
  0-credit local rows (`local_prices`). `shooting_sheet` does pass its table
  (`backend/app/media/shooting_sheet.py:1170`, `:3455-3471`).
- **Rehearsal identity differs from the stills step's**: adopted stills are hashed with
  `still_fields(scene.visual_prompt, None)` (`backend/app/media/rehearsal.py:541`) while the stills
  step's identity includes the character reference (`backend/app/media/stills_stage.py:527`); for a
  scene with a reference, an adopted APPROVED still is not the identity the stills step reuses.
- **Rehearsal still checks are a subset**: `degenerate, sharpness, motion_blur, faces`
  (`backend/app/media/rehearsal.py:565`), not `panels` or `palette` from `ALL_CHECKS`
  (`backend/app/media/still_gate.py:201`); no vision look (`backend/app/media/rehearsal.py:893-896`).
- **Rehearsal matches a clip to its render by byte size only** (`backend/app/media/rehearsal.py:442-448`).
- **Static vs runtime LLM reach**: the inventory marks `rehearse` as reaching the LLM (4 hops),
  but it passes `registry=None` to QC (`backend/app/media/rehearsal.py:1265`) and no registry to
  `assemble_from_takes` (`:1239-1248`), so no model is called. The other way round, the
  inventory gives `gpu_batch.run_rounds`, `_judge_candidate` and `_StillRounds.landed` no LLM
  path, yet each runs the gate's vision look at runtime through an injected callable (`judge`,
  `on_outcome`), and `run_rounds` also reaches the Director's look through `next_round`. The
  inventory's paths for `_settle_pending`, `_settle_round` and `_StillRounds._decide`/`._settled`/
  `.next_round`/`.run` (distances 6-9) are the Director's look only; the gate's vision look in
  them is again invisible to it.
- **Open point stated in code**: when a hold is released, the ESTIMATED provider cost booked for
  that round stays in the books; "an ESTIMATED provider cost has no correction entry yet"
  (`backend/app/media/runpod_unsent.py:62-64`; card text `:707-708`).
- **Open point from the decision log**: GPU_BUSY is decided only by `open_session`, after the
  Owner's yes was spent (`docs/project/16_DECISION_LOG.md:4218`); `gpu_precheck` does not cover it
  (`backend/app/media/gpu_batch.py:87-97`).
- **Reference sets differ from paid steps**: fixed margin `REFERENCE_BALANCE_MARGIN = 1.15`
  instead of the Owner's `paid_step_balance_margin` setting (`backend/app/media/services.py:1826`;
  documented as intentional in `docs/project/16_DECISION_LOG.md:4157`); no disk check and no film
  lease; an unpriced model reserves 0 µUSD (`:1958-1967`); the balance is read (and an unreadable
  one refuses) even when no credit price is known (`:1845-1860`).
- **`media_readiness` and `describe` cover only image and voice** (`backend/app/media/factory.py:744-751`,
  `:787`), not the video purpose the motion step buys from.
- **Duplicated adapter construction**: `image_provider` and `image_provider_for` repeat the same
  per-kind logic (`backend/app/media/factory.py:241-345`); `toolchain.ROOT` recomputes the
  repository root that `app.config.ROOT` holds (`backend/app/media/toolchain.py:37-38`), and
  `_EncoderSetting` and `disk._DiskSetting` each read `.env` separately
  (`backend/app/media/toolchain.py:47-60`; `backend/app/media/disk.py:36-42`).
- **Style defaults contradict per-scene kinds**: `GenerateStoryboardCommand.visual_style`
  defaults to `MOTION_GRAPHIC` (`backend/app/media/schemas.py:97`), so a board built through the
  route records that style (only a blank value gives `PER_SCENE`, `backend/app/media/services.py:1352`);
  `Storyboard.visual_style` and `StoryboardScene.visual_type` also default to `MOTION_GRAPHIC`
  (`backend/app/media/models.py:101`, `:143`). Scenes are written with their own kind
  (`backend/app/media/services.py:1438-1439`).
- **Stale comments**: `SceneTake.kind`'s comment lists `still | motion | test_shot`
  (`backend/app/media/models.py:213`) while `SCENE_TAKE_KINDS` also has `narration` (`:28`); the
  comment "Narrative fields the seed may complete on an entry that predates them" sits above the
  append of the eighth character (`backend/app/media/services.py:499-500`); the services module
  docstring names only Character Bible and Storyboard generation (`:1`); the comment on
  `_Scene.picture` still says the written picture is the scriptwriter's line
  (`backend/app/media/stills_stage.py:361-363`), while for the serial it is the composed beat
  (`:451-452`).
- **Listing reads everything**: `list_storyboards` loads every storyboard and every
  `runbook.film_retired` event and paginates in Python (`backend/app/media/services.py:1672-1676`,
  `:1709-1717`, `:1733`), although its docstring speaks of "three aggregate reads".
- **Fallback scenes**: a script with empty `scenes_json` becomes one LIVE scene
  «Opening scene illustrating: {title}» (`backend/app/media/services.py:1301-1314`); a scene with no
  visual text is `Scene N` (`:744`).
- **Two reference layouts**: the paid reference route writes
  `<REFERENCE_STORAGE_ROOT>/<character_id>/<slot>.<ext>` with
  `REFERENCE_STORAGE_ROOT = backend/storage/character_references`
  (`backend/app/media/services.py:1763`, `:1972-1994`); the free portrait pass writes
  `<media_root or REFERENCE_STORAGE_ROOT>/references/<character_id>/portrait.png`
  (`backend/app/workflows/passes/character_references.py:66`, `:273-279`). Both roots are served
  (`backend/app/media/storage.py:15-30`).
- **Drain limit**: after a halt `run_rounds` polls at most four more times (three waits) and
  leaves whatever has not reported to the session close (`backend/app/media/gpu_batch.py:447-454`).
- **Figure 1 is handed to adapters that take no reference**: `_references` gates only the
  character reference by `ACCEPTS_REFERENCE_IMAGE`; Figure 1 is appended for every later scene
  unless the adapter declares `MAX_REFERENCES` (`backend/app/media/stills_stage.py:807-824`),
  although its docstring says a vendor that does not take a reference is not handed one
  (`:801-802`). `ComfyImageAdapter` declares neither and refuses any reference
  (LOCAL_REFERENCE_UNSUPPORTED, `backend/app/providers/comfyui.py:327-332`, `:348-353`), and the
  per-request path always makes later scenes wait for Figure 1
  (`backend/app/media/stills_stage.py:2131-2137`). By reading, a
  local (ComfyUI) stills step of several scenes would have every scene after scene 1 refused
  once scene 1 is approved; `tests/test_local_media_routing.py` exercises only one-scene redos.
- **Only characters up to the first referenced one are checked**: `image_reference_for_scene`
  stops at the first character with a stored reference (`backend/app/media/services.py:2135-2159`),
  so a locked character named after it with no reference neither refuses the film nor is drawn
  from its sheet. Spec 24 says both that such a character refuses the film and that "the first
  character the writer named decides the reference"
  (`docs/architecture/24_VISUAL_CONTINUITY_ASSET_SYSTEM.md:62-67`); the code resolves that
  tension in favour of the second sentence for every character after the first one with a
  reference.
- **A balance stated as nothing is not fail-closed**: `_read_balance` returns (True, None, None)
  when the reader answers no number (`backend/app/media/stills_stage.py:850-851`; Runway's
  `credit_balance` returns None when `creditBalance` is absent or not a number, `backend/app/providers/runway.py:596-604`, `:119-131`);
  the start check (`backend/app/media/stills_stage.py:2018`), the per-request check (`:2183`)
  and the uncounted-drop check
  (`backend/app/media/assembler.py:8350-8353`) are then skipped, while ADR-NEXT-ROUND-BALANCE says
  a balance that cannot be read stops the step (`docs/project/16_DECISION_LOG.md:4157`).
- **The `rewrite` flag is written and never read**: `_settle_round` sets `rewrite: true` on a
  scene whose corrected mistake persists, with the comment that this is not the Owner's to decide
  (`backend/app/media/stills_stage.py:1178-1181`); no backend code reads the flag (a search of
  `20abffd` finds only that line). The scene still gets a hold event with `holds: true` and no
  rewrite marker (`:2395-2418`, `:1807-1829`) and is listed in the step's `needs_owner`
  (`:2514-2516`). The Director's ladder reaches it through the content phrase in the refused
  take's reasons (`backend/app/media/still_gate.py:901-917`).
- **One acceptance branch cannot be reached**: `fix_check.look_accepts` also accepts CONFIRMED
  with severity minor and `redo` false (`backend/app/media/fix_check.py:703`), but `SecondLook`
  refuses a CONFIRMED answer without redo (`backend/app/media/second_look.py:126-130`), so only
  OVERTURNED with severity none or minor approves a still.
- **Refused before she looks, in another transaction**: `_set_verdicts` writes every candidate of
  a refused round REJECTED (`LOCAL.STILL_GATE`) before her look (`backend/app/media/stills_stage.py:1128`,
  `:1249`), and only a later transaction turns the one she accepts into APPROVED (`:1017-1035`).
  By reading, a process that stops during her look (a model call) leaves the candidates REJECTED,
  which are not pending (`PENDING_STATUSES`, `:284`), so the next plan buys the scene again
  without her look at them.
- **The settlement path asks her without the round's step**: `_settle_pending` offers the
  collected candidates to her whenever none passes (`backend/app/media/stills_stage.py:1250-1260`),
  without `round_step`; `_settle_round` asks only when the step is a re-roll, a rewrite or the
  Owner (`:1143`), so a collected set whose deciding candidate says `compose_locally` still has its
  other candidates offered there. No lesson is withdrawn on that path (`:1150-1159` has no
  counterpart in `_settle_pending`).
- **Her looks run inside the GPU session without a renewal**: for RunPod rounds she is asked from
  `next_round` (`backend/app/media/stills_stage.py:1698-1701`), which `run_rounds` calls with the
  session open (`backend/app/media/gpu_batch.py:513`); the session is renewed after each
  `on_outcome` (`:424-428`, whose comment says a judgement may take minutes) and on each poll
  of a round (`:458-464`), but nothing renews it between `next_round`'s return and the next
  round's `/run` (`:366-391`). Up to two looks per scene touched in the round run there.
- **A still approved by her look reports a score of 0**: a BLOCKED report's score is 0.0
  (`backend/app/media/still_gate.py:1068`), and `_RoundEnd.approved` copies it into the scene's
  entry (`backend/app/media/stills_stage.py:1007`).
- **Two ways of knowing a serial scene**: the stills gate uses `editorial.is_serial_film` or the
  package (`backend/app/media/stills_stage.py:496-498`, `:451`), clip QC's plan only the package
  (`backend/app/media/assembler.py:10236`, no `serial=`). By reading, a serial board whose scene
  package lacks `in_frame` or `shot_size` shows the stills gate the composed beat (empty when the
  package has no room, people or action) and clip QC the writer's line.
