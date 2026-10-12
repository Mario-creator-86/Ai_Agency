# Changelog

## 2026-10-12 — The day's goal, counted from the record, travels with the snapshot

The Owner, 14:00: «Putem urmări goal-ul de generare câte 2 pe fiecare canal, totul autonom?» — until now the tally lived in the developer's peeks of a database copy. `app.goal.goal_snapshot(session)` reads what the page reads: the publications of the day (`PublicationRecord` PUBLISHED, by channel), the films in work of the last seven days (APPROVED or RENDERED storyboards with no published asset) with where each stands from its newest walk (`runbook.film_state`: a refusal of `OWNER_DECIDES` or his open card about the film → ``blocked``, whose ``owner``; a walk waiting on one of the ladder's refusals, or a FAILED report the Director decides → ``in_work``, whose ``director``; else the studio's), the serial's newest episode with no storyboard (``next_episode``: approved and readying, or refused and waiting for its rewrite), and one Romanian line for the register (``words_ro``: «Azi (2026-10-12): shorturi 0/2, episoade 0/2 publicate; 2 în lucru; 1 așteaptă decizia ta.»). `services.snapshot` carries it as ``goal`` ({day, target_per_channel, channels: [{channel_type, channel_id, channel_name, target, published: [{title, at, url}], in_work: [{storyboard_id, title, whose, words_ro, since}], blocked: [...], next_episode}], words_ro}); an unreadable goal is ``{}`` with a warning, never a failed snapshot. The page's register is the pixel session's to show it (frontend/src). Tests: tests/test_goal_snapshot.py (2); the foundation, replay, feed and publisher suites green.

## 2026-10-12 — Her next round of a film yields the one worker when another film waits

12:32–13:37: after the restart the worker took the cyclotron's continuation first, and `director_decides_failed_film` ran its rounds inside that one task — repair (two RunPod steps, 20–35 min), render, quality control, read again, up to `DIRECTOR_QC_ROUNDS` = 4 — while the serial's after-start walk (queued 12:32:33) waited behind it for more than an hour; the one durable worker runs one task at a time. Now when the film her repair made fails quality control again and another film's continuation is QUEUED, the new report is queued as a continuation of its own (`_yield_next_round`: the review pass's key `film-continue-<film>-director-qc-<report>-0`, cause `director_qc:<report>`, so `director_qc_review` never queues it twice) and the walk ends with ``outcome["yielded"]``; the worker then serves the films in turn, one repair round each. Nobody waiting, the round runs in the same walk as before; in TEST nothing is queued and the loop stands. Test: tests/test_director_decides_qc.py (+1: with another film queued, one round, one read, the next report queued; the two-round test unchanged).

## 2026-10-12 — A still's exclusions go to the image model's negative channel

12:04, the serial's first walk with the new code: scenes 3 and 6 of «The Zero Script Club» (two-shots) were refused by the stills gate again after two re-rolls — «split into two horizontal panels stacked one above another» — their twelfth refusal each, while the positive prompt said «One continuous picture fills the whole tall frame»; scene 4 had been refused for lettering drawn on the ledger. RunPod's worker has a negative channel (`BatchRequest.negative_prompt` reaches the graph, tests/test_runpod_worker_studio_contract.py) and the stills step sent nothing in it. Now every still carries `stills_stage.STILL_NEGATIVE` — split screen, collage, panels, comic strip, stacked frames, diptych, triptych, grid of pictures, text, lettering, captions, subtitles, logo, watermark — plus «visible faces, portrait» when the bible forbids faces (`_bible_bans_faces`, the lint's `BIBLE_NO_FACES` over the bible's rules) and the plan's own `avoid` items, each once, within `NEGATIVE_CHARS` (`still_negative`, read on each `_Scene` by `_read_scenes`, sent by the batch round's `_requests`). Where a negation belongs (ADR-POSITIVE-PROMPTS-ONLY: a plan's exclusions reach a model's negative channel where it has one) and never in the positive prompt. Not part of the still's identity (`still_fields`: the words and the reference picture), so approved stills stay approved and the plan's hash does not move. Tests: tests/test_still_negative_prompt.py (2: the words, and the batch item carrying them); the stills, RunPod and seed suites green (143).

## 2026-10-12 — The paid-redo cap reached is the Owner's card, not a loop of the Director's

11:51, «The Particle That Shouldn't Exist (And Briefly Didn't)» (1c038a99): the film failed quality control on one real flaw (scene 5's picture), the Director decided REPAIR three times in eleven seconds, and each time the repair answered «Scena 5: nu se mai cumpără automat, s-a atins limita de 5 refaceri plătite pe scenă» (his cap, `Settings.film_max_paid_redos_per_scene` / `film_max_paid_redos`); the film then waited in her inbox, where `director_qc_review` would have put it before her again every hour, up to twenty-four times, with the same answer — and nothing of it reached him, though the cap is money and money is his. Now `decisions.producers.redo_cap` (a producer module: applier + condition registered from its own file): when a repair she decided bought nothing because of the cap, `runbook.stages._apply_repairs` proposes one card per film («Filmul «…» a atins limita de refaceri plătite (scena 5)», with her finding) with his four answers — **allow** (`EXTRA_REDOS` = 5 more paid redos for the film, on the record as `media.redo_allowance_granted`, read by the cap through `redo_allowance`; her repair is queued again at once), **publish** (his ACCEPT carried out as hers is, `director_qc.accept_film` with ``decided_by`` owner, the continuation queued to publish), **close** (the rendered film retired with its books, `director_qc.close_film`), **wait**. The card closes by itself (`redo_cap_cleared`) once the film is closed, published, passed by a decision, or given an allowance after it was written; `director_qc_review` does not ask her again while his card waits (`_his_card_open`). The repair's words say «ai un card». Tests: tests/test_redo_cap_card.py (5: the card and its options, allow, publish as is, close, the review pass waiting on him).

## 2026-10-12 — The live register's words travel with the snapshot and the socket; every kind of the repair loop has its sentence

The Owner's rule of 2026-10-11 (the register in human sentences, the office driven by backend events) held only for the paged record: at 10:27 the newest rows read «scene take recorded ×2 — storyboard_id: aa170155-… · scene_number: 5 · kind: still», «run paused — endpoint_id: u07hiqhesi015d · items: 2 · seconds: 1.33», «gpu session opened — endpoint_id … purpose: image · step: scene_redo», «spend reserved — purpose: sheet:scene_redo · usd: 0.84», «qc paid redo — scene_index: 4 · of_asset: c00866fc-…», while the same kinds minutes older were sentences. `services.snapshot` (the page's first twenty events) and `workflows.publisher` (the outbox's live messages, the socket's replay) served events without `events_feed.enrich`, and the page keeps the first copy of an event it receives — so the live rows, the ones watched, stayed raw. Now `snapshot`, `claim_pending_outbox` and `replay_events` carry `words_ro`/`actor`/`film_title`/`bubble_ro` too (`publisher._with_words`: a failure to find words is logged and loses no event; the outbox row keeps only the event). `events_feed` gained the sentences the Director's repair loop on RunPod writes: the GPU session opened for a step and its round sent (the Video Editor's, with a bubble), the GPU verified or forced off («nu mai costă nimic»), money put aside, estimated, settled or released by its «redo:<film>:<kind>:<scene>» or «foaie:» reference (the film by its title; «Cheltuit: 0.66 USD pe refacerea clipului scenei 3 din «…»», no more «pe pasul (released)»), the Director's brief with its layer and outcome (same prompt / the editor's rewrite landed, the editor by name), prompt rewrites incl. the serial's recomposition and re-roll, clip QC and the QC verdict, a scene's paid redo, the repair's tally (bought, waiting, requalified), intermediates released, a film re-assembled after a redo, a take refused, lost or put back, a film's day, a scheduled job; an agent starting work says it in a bubble («Lucrez la verificarea unui clip.»); a kind nobody has words for is said by its name and film alone — never an id, a hash or an endpoint («RunPod: gpu guard off.»). Tests: tests/test_events_feed.py (13; 7 new, payloads copied from today's record on a database copy), tests/test_publisher.py, tests/test_foundation.py, tests/test_replay_reads.py green. Live after the next restart. The office's own reactions (a «GPU în lucru» state, the brief's bubble, a «Se reface scena N …» headline instead of «Studioul se odihnește acum» while a paid redo is in flight) are the frontend session's, listed in CURRENT_STATUS.

## 2026-10-12 — The compiler's sentence for a scene of objects says what is there, not «no people»

From the quality audit of 10:45 (a sub-agent reading the day's briefs on a database copy): five of the Director's briefs today — Higgs-2 scenes 1, 3 and 5, the cyclotron's 4 and 5 — diagnosed the compiler's fixed sentence «There are no people in the frame.» (said for a scene of objects when the bible forbids faces): an image model reads past the negation and draws the people it names, faces came back, each brief asked for the sentence to go, and the next compile of the package put it back (ADR-POSITIVE-PROMPTS-ONLY forbade a plan's exclusions as negations; the compiler's own sentence had escaped it). `prompt_agent.NO_PEOPLE_SENTENCE` is now «The frame holds only the place and the things named.» — no word for a person in it — and `prompt_lint.NO_FACE_STATED` reads it as the bible's face rule kept (the older sentences still count for the prompts written before). Tests: tests/test_prompt_lint.py (+1), tests/test_prompt_compiler.py and tests/test_prompt_compiler_director_intent.py (the sentence). The audit's other findings stand as work to weigh: the motion prompts still ask for stillness in their world clauses and chop subject clauses into fragments (`MOTION_STILLNESS` is a WARN); the editorial judgement passes a 37/50 in the first of ten rounds and does not read the structural reviewer's «NOT addressed» notes or the title's promise.

## 2026-10-12 — A scene bought again on the same words draws a different picture or clip; the serial's rung decides a redo when its words are already today's

Found while reading the serial's road after the 09:53 restart: the ladder's serial rung (`scene_rewrite.recompose_serial_scene`) answered a quality refusal only by saying the scene's words again with today's composer; when the words were already today's it returned «se refac doar imaginile, nu cuvintele» with nothing rewritten, the walk stopped («Directoarea nu a putut încă rescrie…»), the serial rung records no brief attempt for `ladder_retry` to retry, and the episode would have waited for the next restart — and the next restart's walk would have said the same. And a scene bought again on unchanged words would have drawn the same thing: the film's one seed (`film_seed`) went on every shot and every round, with the clip-QC retry at seed + 1, so a second round made the same clip and its same retry; the stills' re-rolls were numbered from 1 in every step (`item_seed(…, attempt, candidate)`), so a second step drew the same candidates. Now: (1) `recompose_serial_scene`, when the words are already today's and the scene's newest take is quality control's refusal (`last_failure_code` in `QUALITY_CODES`), writes the Director's decision on the record with the same words (`SCENE_PROMPTS_REWRITTEN_EVENT`, reason `serial_reroll`, layer `still` for the gate's refusal, `motion` for clip QC's, `refused_code`): the hold lifts, the attempts count again, and the walk buys again — «imaginea/cadrul ei … se reface pe aceleași cuvinte, cu altă sămânță»; with no refusal it still says the words are today's and rewrites nothing. (2) `assembler._scene_seed`: a scene's motion round is bought on the film's seed moved past the clips the scene already had (`_shots_made`: PAID, APPROVED, REJECTED, LOST shots, any identity; two seeds a round), so the plan's and the step's seed stay the film's while each new round of a scene differs; a round that made nothing keeps its seed, as the technical retry does. (3) `stills_stage._Scene.rolls`: every still the scene ever had, and the batch requests' seeds are numbered past them. Tests: tests/test_reroll_seeds.py (3), tests/test_serial_ladder.py (the today's-words case split in two: nothing refused → not rewritten; refused by the gate or clip QC → made again as her decision, the words unchanged).

## 2026-10-12 — scripts/restart.py: the developer's self-restart as a repo script

The Owner, 07:40: «de acum încolo, să dai singur restart la proiect». The scratchpad script that restarted the studio at 07:49 and 08:33 is now `scripts/restart.py`: it finds the `scripts\start.py` python (the child of uv.exe), sends its console Ctrl+C (start.py's clean stop: the server's shutdown at the day's boundary, the GPU verified off, the graphics stopped) and, after `--break-after` seconds, CTRL_BREAK as the fallback; waits for every studio python/uv process (`--wait`), closes the earlier self-start's `cmd /k` console instead of waiting for it (the 08:31 attempt hung ten minutes on that window), starts again detached in a visible console from the repo root, and confirms /health/live. `--dry-run` shows the target. Windows only; nothing bought, decided or written to the database. The safe point is the operator's to check first: no OPEN GPU session, no SUBMITTED take a worker already runs.

## 2026-10-12 — A shot the step stopped before sending says nothing about its scene; a quality refusal holds a scene for the Director's rewrite, not for the Owner

08:34, seventeen seconds after the second self-restart: the walk of «The Zero Script Club» (f06808c9) stopped again «după pasul «restul mișcării», scena 6 așteaptă decizia Proprietarului», his sheet letter of 08:10 still open. Scene 6's clip had been refused by quality control on 10-11 at 20:44 (burned-in caption text, QC.CLIP); its retry was cancelled at 20:58 when the Owner stopped autonomy and recorded as a REFUSED take, RUNPOD.CANCELLED, «Nu s-a cumpărat: pasul s-a oprit înainte de acest cadru». `assembler.take_failure` read that take through `classify_failure`, which knows no CANCELLED and said UNKNOWN: the scene was held «până nu decide Proprietarul», and `scene_rewrite.last_failure_code` returned the cancelled code, so `_ladder_scenes` saw no quality refusal and the Director's ladder never ran — the whole motion stair (scenes 3–8) waited on him for a clip that was hers. Now: (1) a REFUSED take with `CANCELLED_FAILURE_CODE` that cost nothing says nothing about the scene (`take_failure` → None, as RUNPOD.NOT_QUEUED does), so the refusal before it stays the scene's newest; the step writes the code and `CANCELLED_DETAIL` from the constants. (2) `scene_memory`: a scene whose newest take (as it is now, since the Owner or the Director last decided about it) is quality control's refusal, with no hold event of the step, is held for the Director's rewrite (`_newest_quality_refusal`, `_quality_hold`: «Directoarea îl rescrie înainte de o nouă cumpărare, nu e decizia Proprietarului»); an approved sibling candidate at the same instant outranks the refusal; her rewrite (`DIRECTOR_REWRITE`) lifts it as before. Without this the next walk would have bought the same refused words again. (3) The walk's words say whose the wait is: `stages._held_words` — «scena 6 refuzată de controlul calității așteaptă rescrierea Directoarei» / «scena 2 așteaptă decizia Proprietarului pe foaia de filmare» — at both stops of `_walk_staircase`; `_quality_scenes` is shared with `_ladder_scenes`. The refusal stays NEEDS_OWNER (one of `LADDER_REFUSALS`). (4) `media.answered_letters`: a sheet letter about a state the film has since left — its newest walk (`runbook.film_state`) newer than the letter, with another status or reason — closes itself («filmul a plecat din starea despre care întreba scrisoarea; acum: …»), because the ladder writes him no newer sheet letter to move past the old one (his letter of 08:10 about scene 6 would have stayed OPEN for good). Tests: tests/test_cancelled_shot_is_nobodys_refusal.py (4), tests/test_answered_letters.py (+1); the ladder-retry, studio-defect-refusal, Director-decides-QC, stills-stage, RunPod-unsent, film-costing, RunPod-batch and serial-ladder suites green.

## 2026-10-12 — A quality refusal the ladder answers writes the Owner no sheet letter

08:10 («The Zero Script Club», scene 3 refused by the stills gate after two re-rolls): the walk ended NEEDS_OWNER and runbook.stages._sheet_letter wrote the Owner «Foaia de filmare … așteaptă decizia ta» while the Director's rung was composing the scene again. A walk stopped on one of the ladder's refusals (NEEDS_OWNER, TAKES_NOT_ACCEPTED) whose scenes quality control refused (_ladder_scenes) is the Director's — her ladder in the walk, the ladder_retry pass after it — and writes him nothing; a balance, a budget, his look at the hero or his answer still do. Test: tests/test_daily_run_stages.py (+1).

## 2026-10-12 — A serial still keeps one moment per person, before the comma that begins the next, and says its pages and screens are blank

08:01–08:04 (f06808c9, scenes 3 and 4, the stills the serial rung recomposed): the stills gate refused all four candidates again — scene 3 «split into three horizontal panels stacked one above another» / «two stacked panels showing the same office two-shot twice», scene 4 «the ledger shows visible lettering and number grids». The chain of moments was cut at «then» but not at commas («opens both hands as if starting a pitch, the gesture stalls halfway and dies, he restarts his sentence»), and «pauses before the number» had the model write numbers on the ledger. prompt_agent._still_moment now keeps each person's clause up to the comma that begins the next moment (a pronoun, «then», or a verb of motion in its first three words — a descriptive tail like «arms crossed» or «hands on hips» stays), and compose_serial_prompt adds «Pages and screens are blank.» where the beat has paper or glass (ledger, page, screen, monitor, whiteboard …). The look's prompt cap is 980 (config and default; was 900). Tests: tests/test_serial_look.py (the comma chain, the descriptive tails, no «pauses before the number», the sentence), tests/test_topic_dedup.py's publication row completed (the test committed in 0bf1a48 had failed behind a pipe that hid pytest's exit). Scene 4 passed the gate on the second round at 08:08 with the earlier words; scene 3 waits for these, which the rung composes on its next round.

## 2026-10-12 — Three fixes from the first autonomous morning: the same-prompt cue reaches the repair, letters to the Owner only for what is his, a subject already made is never proposed again

Three fixes from the first autonomous morning (2026-10-12, 07:50–08:10), after the self-restart.

1. **The same-prompt cue reaches the repair.** `scene_rewrite._rung` now carries `same_prompt` into the outcome of `rewrite_for_redo`: the cyclotron's scenes 4 and 5 were asked the same motion rewrite at 07:51 and 07:52 after the restart and refused PROMPT_NOT_CORRECTED again, because the flag set by the rewrite stopped in `_rung` (the morning's unit test faked `rewrite_for_redo` and never walked it). Test: `tests/test_director_rewrites_failed_scene.py` — a rewrite that lands, then the same words again → `same_prompt` True on the outcome and on the brief's record. With it `_correct_before_redo` turns the redo to the picture.

2. **Letters to the Owner only for what is his.** The Owner, over six «Am nevoie de decizia ta» letters about that prompt and a redo the tariff could not price: «Ar trebui să nu ajungă la mine, este la Director!». `agents/director.py`: an ESCALATE_TO_OWNER from her review stays with her unless the matter is his — his accounts and sign-ins, what only he authorises (a site, a model), security or legal standing, a thread he opened (`owners_matter`, `OWNER_MATTER_KINDS`, `OWNER_MATTER_WORDS`); otherwise it becomes her ACKNOWLEDGE with `HERS_NOTE` on the record, and a note naming a tool (`DEFECT_WORDS`) is written for the developer in her own thread, resolved at once (`developer_defect`). Her instructions say so; money is never hers to escalate (the Policy Kernel asks his card). Tests: `tests/test_mail.py` (+2; the title-hold test now holds an account's sign-in).

3. **A subject the studio made is not proposed again under another title.** «The Particle That Shouldn't Exist (And Briefly Didn't)» (2026-10-12) after «…(But Does)» (filmed 10-09, published 10-10 as «The Higgs Boson: The Particle That Explains Why Mass Exists»): the researcher's duplicate check compared the candidate's title with the ideas' titles alone (Jaccard 0.5 < 0.6; the first film's idea had a third title). `research/agent.py`: `_too_similar(title, topic, existing)` also reads the subject — two subject words shared between titles («Particle … Shouldn't», «Higgs Boson») or three across title and topic — against `existing_subjects`: every idea (title, topic) and every script, storyboard and publication title, bare of «Storyboard:»; the prompt carries `made_subjects` and says «not the same subject under another title». Tests: `tests/test_topic_dedup.py` (3). The Owner decides what becomes of today's duplicate film (a card).

## 2026-10-12 — A day cut off under the studio is resumed by itself after the start

A day cut off under the studio is resumed by itself after the start. The Owner, 2026-10-12 07:40: «de acum încolo, să dai singur restart la proiect, nu mă aștepta pe mine!» — the studio is restarted for every code change without him. A restart during the day ends it INTERRUPTED at its boundary (REL-10), and until today nothing ran it again: the clock skips a cut-off day (a whole second run would choose a second subject and buy a second film) and the Director's letter asked the Owner to press «Pornește rularea de azi»; a day cut off before its log closed left the serial without its next episode.

- `workflows/passes/resume_interrupted_day.py` (order 20): on every watchdog tick, today's newest run that ended INTERRUPTED with nothing after it (`runbook.services.resumable_run`) gets one DAILY_RUN with `resume_of` (key `daily-resume-{run}`), event `runbook.daily_run_resume_queued`; nothing while the studio stops or shuts down, in safe mode, or while a DAILY_RUN is queued or at work.
- `workflows/worker.py` `daily_run`: a `resume_of` task replays the stages the cut run COMPLETED from their record (`runbook.services.resume_runners`: status, reason with «reluată din rularea întreruptă …: etapa era încheiată, nimic refăcut», artefacts) and runs the stage it stopped in and the rest; skipped when the day passed, when the run is no longer the interrupted one or a later run exists, or when the day's attempts are used; `resumed_from` on the outcome.
- The interruption letter now says «după repornirea studioului o reiau singur de la etapa unde s-a oprit, fără să refac etapele încheiate».

Tests: `tests/test_resume_interrupted_day.py` (3: resumed from its stage with nothing done twice and the pass idempotent; nothing queued while stopping, under his stop or with a run in hands; a resume of a finished or past day is skipped), `tests/test_shutdown.py` letter wording. With it the restart is mine (memory rule): commit, green suites, a safe point (no GPU session, no purchase in flight), graceful stop, detached start, the day resumes by itself.

## 2026-10-12 — A motion rewrite that came back with the same words turns the redo to the picture

A motion rewrite that came back with the same words turns the redo to the picture. The cyclotron's scene 5, every hour through the night: the Director's brief rewrote the movement, the Video Editor's words came back unchanged («Rescrierea a dat același prompt; nimic nou de cumpărat»), the paid redo was refused PROMPT_NOT_CORRECTED, and the next hour asked the same again — while the Owner's ladder says a movement rewritten once on a picture that stays is the picture's turn (`MOTION_REWRITES_BEFORE_STILL`). Now `scene_rewrite.rewrite_failed_scene`/`rewrite_for_redo` mark such an outcome `same_prompt`; the QC repair's `_correct_before_redo` then asks for the still layer with the note «the picture itself must change now» and, when it lands, the redo buys the new still and its motion (`kinds` gains "still"); a picture that cannot be rewritten either (his approved still) keeps the refusal. The ladder's `open_layers` counts a same-prompt motion attempt like one that landed (the flag on `media.director_scene_brief` since today, the words for the attempts recorded before), so the picture opens after one. Tests: `tests/test_director_decides_qc.py` (+2), `tests/test_director_rewrites_failed_scene.py` (+1); suites green: Director decides (59), Director rewrites, scene redo rewrite, serial ladder, film costing, sheet, RunPod pipeline and money adversary (230).

## 2026-10-12 — A paid motion redo prices the RunPod profile as the sheet does; a redo that bought nothing is never told as a purchase

A paid motion redo prices the RunPod profile as the sheet does, and a redo that bought nothing is never told as a purchase. Live, the cyclotron (aa170155), from 2026-10-11 20:17 UTC through the night: the Director's QC decided a REPAIR of scenes 4 and 5, her brief rewrote the motion, and the paid redo (`_paid_redo` → `run_motion_step` → `_motion_state`) priced the scene with the raw published tariff — no row for the Owner's RunPod profile (LTX-2.5 is an estimate `price_table_for` lays over the tariff) — so the step held the scene NEEDS_OWNER «Profilul RunPod selectat nu poate filma această scenă: nu are preț publicat la 1080p; calitate 0,50 sub 0,80 cerut pentru STANDARD», while the sheet's own motion step had priced the same model the same day. The hourly `director_qc_review` pass re-asked her five times (21:45, 22:46, 23:48, 00:49, 01:51 UTC) and each walk told the Owner «s-a cumpărat (1 refacere cumpărată); preluarea nouă așteaptă aprobarea» over a redo that bought nothing.

- `assembler._motion_state`: with no table given it prices with `shooting_sheet.price_table_for(engine, None)` (the local selection at 0 credits and the RunPod estimates over the tariff), never the raw tariff; `run_motion_step` resolves a missing table with the connection's measured rows too (`price_table_for(engine, integration_id)`).
- `runbook.stages._apply_repairs`: a motion redo whose step bought no shot (`bought_shots` 0: held NEEDS_OWNER, stopped, not bought) goes to `refused` with the step's own status and reason, writes no `runbook.qc_paid_redo`, and the walk's words say so.

Tests: `tests/test_motion_redo_prices_runpod.py` (2: a plan without a table prices the mock RunPod profile; the raw tariff alone could not), `tests/test_director_decides_qc.py` (+1: a held motion redo is a refusal in the step's words, no paid-redo event, no «refacere cumpărată» in the letter; `FakeRedoPath(motion_unbought=)`). After the next restart the cyclotron's redo of scenes 4 and 5 can buy. Open: scene 5's rewrite returned the same motion prompt every hour («Rescrierea a dat același prompt») — the Director's ladder should escalate to the still layer after a motion rewrite that changed nothing, instead of asking the same again (noted in the roadmap).

## 2026-10-12 — The autonomous-day tests tell the serial's episodes apart from the factual film

Two autonomous-day tests (`tests/test_autonomous_day.py`, OVER_USD and EVERY_PAID_STEP) had failed since 3c30bc6 (2026-10-11 22:27). Bisected on a scratch worktree and traced with a throwaway test: not a double purchase. Since 3c30bc6 the serial's scenes composed from the series look are no shot-plan gap, so the serial's episodes reach the paid steps in the autonomous day beside the factual film — today's episode, walked by the day's media stage, and tomorrow's, written by `serial_next` after the close and queued for filming the same evening (e565a6b), walked by the worker. Under OVER_USD each buys its own stills and hero unasked (one more video purchase each) and waits for the Owner's look at its hero; under EVERY_PAID_STEP each asks its own stills question. The tests counted one film: they now tell the films apart by storyboard (`_split_films`, `_of_film`, `_boards_bought`) and follow the factual film's path with the serial's questions and purchases named beside it. Both pass; the eight tests of the file are green. The behaviour itself stands: buying tomorrow's episode's stills and hero the evening before is the same money a day early, not twice.

## 2026-10-12 — A stop during a restart is worded as the studio's closing, not as the Owner's switch

A stop during a restart is worded as the studio's closing, not as the Owner's switch. At 00:03 on 2026-10-12 (21:03:02 UTC) the serial's staircase wrote «Oprit de AUTONOMIE OPRITĂ. Scara filmului s-a oprit.» and its motion step «Proprietarul a oprit autonomia; nu se mai cumpără mișcare.» while his switch was off (`autonomy_stopped=0`): the process was being restarted (the next start at 00:44:43), and `stop_requested` is true on a shutdown too (`request_shutdown` in the lifespan). The runbook already recorded the day INTERRUPTED; the words did not say so and the register read as if he had stopped the studio.

- `runbook/services.py`: `SHUTDOWN_STOP_REASON` («Oprit de închiderea studioului (repornire); continuă după repornire.») and `stop_reason_words(engine)`, to be read right after `stop_requested` said True.
- `runbook/stages.py`: every stop the staircase words (between films, between the walk and the assembly, a render ended by the stop, the walk's own gate) goes through `stop_reason_words`; `OWNER_STOP_REASON` is no longer imported there.
- `media/assembler.py`: `MOTION_SHUTDOWN_REASON` / `motion_stop_reason` for the motion step's three stops («Studioul se închide (repornire); mișcarea rămasă se cumpără după repornire.»), `RENDER_SHUTDOWN_REASON` / `render_stop_reason` for the render job's two.

Tests: `tests/test_shutdown.py` (+2): the words under his switch and under a shutdown; the source rule that no staircase or paid loop names his switch beside a bare `stop_requested`. The 00:03 stop itself needs no repair: the serial's continuation is in the queue and resumes after the restart.

## 2026-10-12 — The Director's editorial judgement for both channels: five criteria, a brief to the writer, up to ten versions, the best one ships

The Director's editorial judgement, for both channels (decision e5e7004, the Owner's card: «vreau să încerce de 10 ori, ne trebuie un serial bun și un short bun, nu doar 3 runde!»). Built by a subagent, verified and committed by the lead.

- New `backend/app/agents/editorial_judgement.py`: five criteria scored 0–10 with one sentence of reason each (hook with stakes in the first two seconds, clarity for a stranger, the memorable moment, the punchline or turn, the reason to come back); the bar is a total ≥ 35/50 with no criterion under 5; below it her brief to the writer names the two weakest with her reasons and says what to keep / change / avoid (≤ 600 chars); `editorial_loop` judges, briefs, has the kind's own writer rewrite, judges again, up to `Settings.editorial_rounds` versions (default 10, `STUDIO_EDITORIAL_ROUNDS`); the best-scored eligible version ships; one `editorial.judged` event per version read; one STATUS letter to the Owner only when a version ships below the bar. She judges through `structured_run` as the Director (task `editorial_judgement`, template `editorial-judgement-v1`); a silent model never raises.
- Serial wiring (`story/review.py`, `story/services.py`, `story/serial_stage.py`): a reviewed episode is held (`held_for_judgement`), judged, rewritten via `write_episode(judged=True)` and re-reviewed; the shipped version is approved under policy and the others retired (REJECTED, `superseded_by`); a held PASS left by a stopped run is approved on the next morning or evening run under policy.
- Factual wiring (`factual/story_review.py`, `runbook/stages.py`): after `review_story` passes and before the Director's approval, `judged_story` rewrites through `agent_write_script(notes=[brief])` and reviews again; the shipped draft carries the loop in `story_json["editorial"]`, the others `superseded_by`; a superseded draft owes the room nothing (`script_work`, `_script_awaiting_owner`).
- `analytics/services.py`: the weekly review reads each film's shipped editorial total (`editorial_total`, and its mean), to be compared with views.
- The Director's seeded task types gain `editorial_judgement` (`seed_role_task_types` extends a live studio on start) and her contract names the judgement; the register (`events_feed.py`) words `editorial.judged` («a notat … 41/50 la versiunea 2; trece la filmare», «… brief la scenarist») with her portrait and bubble.

Tests: `tests/test_editorial_judgement.py` (24), `tests/test_autonomous_day_end_to_end.py` teaches the fake model the judgement prompt; green with them: `tests/test_serial_pipeline.py`, `tests/test_serial_continuation.py`, `tests/test_daily_run_stages.py`, `tests/test_editorial_quality.py`, `tests/test_script_grounding.py`, the role and contract suites. Open: `POST /episodes/{id}/review` (the manual route) still approves without the judgement; a crash mid-loop loses that loop's rounds (its events are written at the end) and the held PASS is recovered unjudged.

## 2026-10-12 — «Mișcare v2»: ample cinematic motion, eighteen camera-move families, calmer or firmer QC retries

«Mișcare v2»: ample, cinematic motion in every motion prompt, the model unchanged (LTX-2.5). The Owner, 2026-10-11: «imaginile sunt bune, dar mișcările de ce sunt așa slabe? Pe video pare doar un zoom, și mișcări mici … trebuie doar să lucrăm la prompturi». Built by a subagent, verified and committed by the lead.

- `prompt_lint.py`: `MOTION_WORDS` 25–95 (was 20–70); `CAMERA_MOVES` one key per movement family with disjoint regexes — the old ten kept, `dolly in`, `dolly out`, `tracking left/right`, `crane up/down`, `handheld drift`, `rack focus` added; `SPEED_WORDS` and `ENVIRONMENT_MOTION` widened (indoor worlds: shadows, curtains, particles, light sweeps); new `SUBJECT_MOTION`, `STILLNESS_WORDS`, `LEGACY_STILLNESS`; new `MOTION_STILLNESS` WARN in `lint_motion_prompt`.
- `qc.py`: `MOVE_FIXTURE` covers every key (dolly → push_in; tracking, crane, handheld → pan; rack focus → no fixture, passes by name, never read as static); `check_clip` keeps the look's verdict; `clip_deformed`, `stronger_motion_prompt` (also drops the legacy stillness sentences), new `calmer_motion_prompt` (one amplitude step down with the forms kept), `retry_motion_prompt` dispatcher used by `qc_clip_with_retry`; the retry reason tells the Owner «mai ferm» vs «mai lin, cu formele păstrate».
- `prompt_agent.py`: `_SHOTS_INSTRUCTIONS` ask for ample, specific movement (path with speed, start→end over the clip's seconds, the subject's verbs, the world's motion), the new camera_move list; `MOVE_SENTENCES` (tempo + path, each spells its key), `DEFAULT_MOVE`, `SIZE_MOVES` (never static/orbit/rack focus unasked), `TWO_BEAT_SECONDS=7.0`, `END_BEAT`, `AMPLE`/`MEASURED`, `MOTION_PAD`, `DEFAULT_WORLD_MOTION`; `choose_camera_move(..., avoid=)` keeps an orbit away from faceless people; `_motion_intent` stores seconds, amplitude and action clauses; `render_motion` writes two beats at ≥7 s and replaces the legacy world sentence on re-render; `compose_serial_motion` opens with the move sentence, keeps the chain, adds `SERIAL_LIFE_SENTENCE` (hands, heads, lamp light, plants), the feeling, the end beat, the closing.
- `config/film_models.json`: every documented model gets the whole vocabulary (the file's own rule; the old ten-move lists would have refused a scene given a new move — «nu face mișcarea «dolly in»»). LTX-2.5 on RunPod is not in that file and was never affected.

Tests: `tests/test_motion_v2.py` (17), `tests/test_prompt_compiler.py` reads the band from `MOTION_WORDS`; green with it: `tests/test_prompt_lint.py`, `tests/test_film_models_catalog.py`, `tests/test_film_model_lock.py`, `tests/test_clip_qc.py`, `tests/test_picture_qc.py`, `tests/test_serial_look.py`, `tests/test_prompt_compiler_director_intent.py`, `tests/test_director_rewrites_failed_scene.py` and the sheet/serial suites. Observed on the Nepal fixture (scene 4): «Gentle tilt up. Smoke drifting left to right.» became «Steady crane down from high above, descending and settling on the subject… Farmer hoeing soil. Turning earth slowly…». Known limits: `END_BEAT` yields to the 95-word budget when a long action fills it; a rewrite after a deformation does not yet set `motion_amplitude = "measured"` on the package (the compiler already reads it) — open.

## 2026-10-12 — Office presentation files formatted and typed

Housekeeping after the pixel session's takeover (2be35a6): `backend/app/office/presentation.py`, `backend/app/office/router.py` and `tests/test_office_presentation.py` were committed unformatted and with ruff findings (import order, long lines, several statements on one line) and two mypy `no-untyped-def` errors (`monitor_media`, `presentation_snapshot` took an untyped engine); `tests/test_phase_ef_closure_adversary.py` and `tests/test_phase1_agents.py` each had one unformatted line. Formatted, typed, and the tree's `ruff check`, `ruff format --check` and `mypy backend/app` are clean again. No behaviour changed; `tests/test_office_presentation.py` (13) and `tests/test_phase_ef_closure_adversary.py` (7) green.

## 2026-10-12 — The Director's ladder has a serial rung

The Director's ladder has a serial rung. Live (f06808c9, «The Zero Script Club», 2026-10-11 evening): the stills of scenes 3 and 4 came back as stacked panels on every candidate and re-roll because their stored words carried the plan's camera path and chain of moments; the composer was fixed (48bbcd1) but nothing said the stored words again, and the walk after the restart stopped on «Directoarea nu a putut încă rescrie scenele 3, 4 … (Scena nu este una pe care studioul o rescrie (card, serial, film închis))» — the Director's rewrite (`scene_rewrite.scene_context`) reads no serial scene, a redo would have bought the stored words again, and the film waited for the Owner, which his rule forbids.

- `scene_rewrite.serial_recomposition(session, storyboard_id, scene_index)`: a serial scene's prompts composed again from its stored plan with today's composer (`compose_serial_prompt`, `_serial_camera_move`, `compose_serial_motion`, the live look); None when they are already today's, when the film is not the serial's, or when the scene has no plan. Reads only; 0 credits, no model.
- `scene_rewrite.recompose_serial_scene(...)`: writes the recomposed words on the scene under the write lock and records SCENE_PROMPTS_REWRITTEN as the Director's decision on the still layer (reason `serial_recompose`), which is what `scene_memory` reads as the hold lifted; `rewrite_failed_scene` takes this branch for every serial film, so the ladder's «(card, serial, film închis)» refusal no longer applies to serial scenes. A scene whose words are already today's answers «cuvintele de azi» and is not rewritten.
- `assembler._scene_prompt_rewrite`: a serial still redo now buys today's composer's words when the stored ones are older (it used to return None for serial films and buy the stored words).
- `_REWRITE_INSTRUCTIONS` offers the Director's rewrite the whole camera-move vocabulary (`prompt_lint.CAMERA_MOVES`) instead of the old ten slow moves.

Tests: `tests/test_serial_ladder.py` (3: a stale serial scene is composed again as her decision, a scene with today's words is not rewritten and says so, a redo buys on today's words), `tests/test_scene_redo_prompt_rewrite.py` test 9 rewritten to the doctrine (the serial's bible on the board; the redo buys the serial composer's words, never the documentary compile, and keeps them once they are today's). Verified on a read-only copy of the live database: every scene of f06808c9 would be recomposed (the still gets «One continuous picture fills the whole tall frame…» and loses the camera path; the moves stay the ones chosen), the still lint says WARN STILL_LENGTH only, the motion lint WARN only. Only scenes 3 and 4 are in the ladder (6 REJECTED LOCAL.STILL_GATE each); the running process needs a restart to carry this.

## 2026-10-11 — The studio's approved cadres become a training set

- 94e2ddf — backend/app/workflows/passes/training_set.py (watchdog, order 170): every gate- or Owner-approved still and clip-QC/Owner-approved shot is written once to training/manifest.jsonl under the media root with its exact prompt, camera move, seconds, resolution, model, look version and approver; training.samples_added per batch; at 100 approved serial clips one training.milestone_reached and one letter to the Owner (the training is his card). Tests: 4, with the watchdog and paid-path scans (169) green.

## 2026-10-11 — The register speaks for people and the office says it in bubbles

- 1cf04da — backend/app/events_feed.py (new) + services.read_events: words_ro / actor / film_title / bubble_ro on every event of the page; frontend ledger.js (describeEvent, withoutName, setPortraits), main.js (sayInOffice, registerPortrait), pixel_office.js (bubbles for every employee), style.css (.ledger-portrait).

## 2026-10-11 — A serial still is one moment in a fixed frame

- 48bbcd1 — prompt_agent.compose_serial_prompt: fixed framing per shot size, SERIAL_FRAME_SENTENCE, first moment only (_still_moment), whole-clause identities (_identity, _clean_cut); the camera path and the chain of moments stay in the motion prompt.

## 2026-10-11 — A RESOLVED sheet repair walks the film on

- 942edfc — blocker_repair._finish(RESOLVED) → _continue_repaired_film: FILM_CONTINUE queued in the repair's transaction (cause sheet_repaired), once per repair, PRODUCTION only.

## 2026-10-11 — The serial passes the sheet's own gates

- 3c30bc6 — prompt_agent.shot_plan_gaps(…, sources) reads assembler.shot_plan_sources (the sheet, the walk's NEEDS_SHOT_PLAN, the repair's issues, the media stage's hold); prompt_agent._serial_camera_move gives each serial shot its own move and compose_serial_motion opens with it; tests/test_serial_sheet_gate.py's four strict xfails are tests now.

## 2026-10-11 — Sheet repair brake, serial look v2 and same-day continuation, sound plan under the voice, the Owner's final approval

- 6510d04 — config/serial_series_look.json v2: the serial's look follows the Owner's office picture (warm hand-drawn 2D, the studio house, faces seen and kept the same person; 445 characters, under half the prompt cap); shots described under v1 are described again.
- 528ec93 — backend/app/media/blocker_repair.py: `issue_key` (kind, code, scene) is what the ceiling and the back-off count on; a sheet rewritten with the same blockers is the same problem; attempts before the change still read by the old fingerprint.
- 2e20ecf — backend/app/media/sound_design.py (new), toolchain.mix_bed(levels=), assembler.film_mix/remix_film_sound/repair_audio, qc.audio_mix_verdict in speech, director_qc.sound_reading, the Voice Artist's `sound_design` task type seeded at start; the registry reaches every mix.
- e565a6b — backend/app/story/serial_stage.py, backend/app/workflows/passes/serial_unfilmed.py: an approved episode is storyboarded and queued for filming the same day; the watchdog pass picks up an episode left unfilmed.
- 5f5414c — assembler.decide_take(final=), owner_approved_among(final_only=), _retire_takes/redo_scene(director_repair=); director_qc.owner_approved_take_ids(final_only=), protected_redos(final_only=True), film_qc_context `owner_approval_final` / `owner_approved_would_be_replaced_by`; stages._apply_repairs runs her redos as `director_repair` and records `replaced_his` for the letter; reviews director-qc-v7; schemas TakeDecisionCommand.final; the sheet shows `owner_final`.

## 2026-10-11 — The characters' portraits are bible references; Google's trends read for the audience's countries

- Claim: Claude Fable 5.1 session 23d615c3. Done: 44fc998 (config/character_references.json → Agents ID and Bible/portraits/*-portrait.png cut clean from the ChatGPT sheets; watchdog pass character_references fills the empty portrait slot once per hash, never a locked look, never a slot whose asset still exists; the Owner's locks untouched), 343382d (STUDIO_TRENDS_GEO takes several codes, default US,GB,CA,AU; per-country feeds, merged lines with their countries). Both tested on fakes (42 + 40 tests). Live effect needs the running process to have the code (the Owner restarted at 21:17 local with the passes on disk) — verified from a database copy, see CURRENT_STATUS.

## 2026-10-11 — The Director's answers land: fitted to the schema, a refusal told to the model, the ladder retried by the studio

- Claim: Claude Fable 5.1 session 23d615c3 (workflow wf_0b525d07-da4, package A, adversarially reviewed READY). Done: d5c41bf (identity.parse_structured fits strings/lists/nested models/enum words before refusing; structured_run retries with the refusal quoted and thinking off when an object was refused, with native thinking only when no object came; a failed brief is recorded; passes/ladder_retry walks a film left WAITING on QC-refused scenes again after 20 min, 6 a day, PRODUCTION only), 962e4c2 (the walk's words say the studio retries). Evidence: aa170155's five QC decisions refused only for a 400-char reason; the thinking retry spent 6000 tokens for nothing. Tested on fakes (42 tests of the package); not yet proven live: the next Director QC answer on kimi-k3 after the restart.

## 2026-10-11 — The Owner's music library: 25 tracks from YouTube's Audio Library, registered beside their files

- Claim: Claude Fable 5.1 session 23d615c3. The Owner (2026-10-11): «Ai acces, fă asta pentru mine. Copiază tot ce ai nevoie pentru un studio». Done: 20 beds + 5 ambiences downloaded in his Chrome session from YouTube Studio → Bibliotecă audio (filter «Atribuirea nu este obligatorie»), registered with the new scripts/music_add.py into config/music/music_library.json (files beside it, config/music/ git-ignored); music_library.library_path prefers it when it exists; the shipped config/music_library.json stays empty; tests read the shipped one (conftest). 25 usable, 0 refused (scripts/music_add.py --check). Takes effect at the next restart (the library is read at start-up). Not yet proven in a real film mix.

## 2026-10-11 — Codex's work finished and committed; the Director's repair desk and the mail fixes land

- Claim: Claude Fable 5.1 session 23d615c3 (continuing Codex's work after it ran out of credits; the Owner: «Continuă munca la care lucra CODEX»).
- Done: 6b907b1 (the ladder's continuation locks first; plan_licence is an unpriced reader), 77b5e62 (prompt compiler: the still names its whole scene, the look's place/season/weather/daylight left to a scene that names its own, no "no X" negations in positive prompts — veo's negative channel only; Codex's intent fixture of aa170155 scenes 4-5), 536f380 (Codex: Director token multiplier ×2, director-qc-v5 maxima, finished-film QC reads the prompts a take was bought on), 54bd847 (Level 1: `app.agents.repairs` — reprice, agent_health, film_cost, threads, stale_decisions, unbilled, desk; DIRECTOR_REPAIR task), 0196aac (the agents' mail stops looping), 7520a6f (QC context tests), music research report docs/project/MUSIC_YOUTUBE_AUDIO_LIBRARY_2026-10-11.md.
- Facts behind it (database copy, 2026-10-11 UTC): the cyclotron film's five Director QC decisions were all complete REPAIR objects refused only for a repairs[].reason over 400 chars; every thinking retry hit the token cap with no output; the Director's scene brief at 14:20 was refused for a diagnosis over 800 chars. Episode 043317d3 is the serial's first APPROVED episode ever (10:43) and has no storyboard until the next morning by design. All 8 character bibles have empty reference slots while the portraits exist in «Agents ID and Bible/*.png».
- Tested on fakes only: 281 prompt-compiling tests, 333 Level-1/Codex tests, 52 Director QC tests, 21 paid-path lock tests pass. In flight: workflow wf_0b525d07-da4 (A: structured answers fitted to schema + error-carrying retry + ladder retry pass; B: serial same-day continuation; C: character portraits as bible references).

## 2026-10-11 — Director token allowance doubled; QC schema limits made explicit

- Double every explicitly bounded Director model call by default, through configurable
  `STUDIO_DIRECTOR_TOKEN_MULTIPLIER` (1..4). QC 6,000 -> 12,000 for both attempts; inbox
  24,000 -> 48,000; other roles and unspecified limits retain their behavior.
- Record requested/effective token limits and multiplier on new run contexts.
- QC prompt v5 names its existing reason/summary/list limits; structured-output failures
  log `structured_answer_invalid` instead of assuming the answer narrated reasoning.
- 9 focused regressions pass, including Director `None`; related suite remains
  123 passed / 1 live-provider skip (98.91 s),
  changed-file Ruff, four-source mypy and independent review pass. Activated by a clean
  restart at 19:24 Bucharest: new process, healthy API/worker, effective multiplier 2.
- Mark two pre-existing fictitious licence-test credentials with inline secret-scanner
  allowlist comments; values, scanner and baseline unchanged. Five licence tests pass.
- No paid model test, media redo or historical-record rewrite; a new Kimi QC success
  has not been proven. Evidence: [DIRECTOR_TOKEN_BUDGET_2026-10-11.md](DIRECTOR_TOKEN_BUDGET_2026-10-11.md).

## 2026-10-11 — The Director reads a refused scene's prompt and has it rewritten

- Claim: Claude Opus 5.5 session 23d615c3, the Owner's rule of 2026-10-11 («Deci directoarea citește promptul și după îl cere la rescriere cu informații clare, ce să evite ca să treacă la QC!»).
- Done (699bc64, f98ffc8, 32585f1): `app.media.scene_rewrite` — for a scene QC refused (QC.CLIP, LOCAL.STILL_GATE) the Director reads its package, the prompts sent, the bible and the refusals' reasons and writes a brief (diagnosis, avoid, keep, change, layer); the Video Editor rewrites that one scene (compiled, linted, stored on that scene only); letters between them, settled. Motion layer keeps the still's words; still layer rewrites the picture and its motion; after a failed motion rewrite or a still-gate refusal only the picture; a still the Owner approved is never rewritten. `scene_memory` reads her rewrite as a decision (hold lifted, attempts counted again). `_film_staircase` runs her rounds (3 a walk, then a continuation). A paid redo after a failed film QC is bought only on a corrected prompt (PROMPT_NOT_CORRECTED). CLOSE for quality refused. Paid-redo limits default 5 a scene, 20 a film.
- Tested on fakes only: tests/test_director_rewrites_failed_scene.py (5) plus 196 + 314 + 127 related tests pass. Not yet proven on a real vendor: the cyclotron film aa170155 (scenes 4, 5) is walked after the 16:41 restart.

## 2026-10-10: the Director decides a failed QC; his approved takes stay his

- The Director decides a failed film QC; the old mechanical repair is gone (7f30429).
- The Owner's approved takes are never retired by an unasked redo; empty redos give back what
  they retired; the `restore_retired_takes` watchdog pass (7f30429).
- A film whose licence is unconfirmed is uploaded private and says why (7f30429).
- Film picture QC no longer reads the studio's burnt-in captions as text (baa2a11).
- The voice licence is read from the ElevenLabs plan by API, daily (07153ad).
- A crashed slow-down filter falls back to frame repetition; films that failed before a restart
  are walked again (d271058).
- The story loop ends itself; a free Owner choice walks the film on (43c13c1).
- A clip is sized to its narration; a short one is slowed locally up to 25% (fa4038d).
- Queue writers take the write lock (WP2); refused batches book nothing (WP1); answered letters
  close themselves; registries for decision producers and watchdog passes.

## 2026-10-09 — front employee profiles and reliable backend animation updates

- Remove state/action badges from portrait images as requested; keep actual status in the
  separate inspector facts and beside each employee card picture.
- All eight profile faces look toward the viewer, with original role-specific room art.
  Identity/appearance/role binding preserves personal faces; office seating stays unchanged.
- Emit the committed aggregate version live and refresh action intent on actual state changes;
  serialize/retry bounded reads and reject stale/late authorization. Versionless older events
  repair from authenticated committed layout, without guessed frontend state.
- Employee cards use current seated pixel positions, removing false «fără birou» labels.
- 48 backend-to-page state changes, eight profile/movement cases and all recovery paths pass;
  909 units/types, 72 scoped backend/docs, eight bounded scene and one backend/page test.
  Live read-only profile/roster/phone/delivery proof; original art unchanged, no backend restart.

## 2026-10-09 — RunPod stills: a fair sharpness check, true GPU seconds, every scene first

- The sharpness check reads the sharp part of a picture: a sharp subject on a dark, soft
  background passes; blurred, downscaled or letterboxed frames still fail.
- RunPod time is booked as billed: run time, one worker start and the 1 s tail, never the
  model-download wait.
- The stills step sends every scene in its first round; re-rolls come after.
- Statuses on the shooting sheet read in Romanian.

## 2026-10-09 — a refused RunPod /run no longer strands a film

- A /run RunPod refused without a job is proven never queued (queue before the purge, the
  purge's removed count, the bucket) and costs 0; the scene is not held.
- Today's held scene becomes the Owner's card with what was recorded; his yes frees it.
- «Refă imaginea» on a RunPod model now runs one GPU round under its own cap.

## 2026-10-09 — higher individual office chairs and a living studio

- Raise all eight seats while preserving wheel/floor contacts. Nadia sits rear-left toward
  her own desk; add a physical upright monitor with correctly mapped content and a desk stand.
- Read-only backend policies authorize individual gestures and monitor power using real
  state/version. Damped upper joints, bounded contacts, wind paper/foliage and rare light dips.
- Nine screen surfaces, authenticated bounded local-video decoder and privacy player for
  confirmed YouTube films. Empty production library remains visibly empty.
- Original directional WebAudio with user-activated Sunet/volume, bounded sources and pauses.
  Fresh authenticated HTTP data keeps motion through a short socket reconnect.
- 898 frontend/types, eight bounded browser and 81 scoped backend/docs/scan cases; actual
  32 s video with sound and all eight staff/street movement verified. PIXEL_LIVING_STUDIO.md.

## 2026-10-09 — the Owner can close a stuck film («Închide filmul»)

- A film waiting on his decision held the studio: no new topic was chosen. His shooting sheet
  now has «Închide filmul» (two presses): the film is closed, nothing more is bought for it,
  what was bought stays in the books, and his open questions about it are withdrawn.
- Refused while a purchase or a GPU session is live, for a rendered film and for a serial
  episode. Every paid path, the day's assembly and the sheet repairs skip a closed film.

## 2026-10-09 — RunPod copy pod: a disk RunPod accepts, its refusal in his words

- The copy pod asks 60 GB of container disk instead of 200: RunPod gives cpu5c at most 15 GB per
  vCPU and refused the Owner's first accept with HTTP 400 (nothing started, nothing spent).
- A refused create now tells him RunPod's own reason (sanitised, token cut) on the card and in
  the log `runpod_mirror_copy_refused`.
- Saving a connection proposes its cards at once; the RunPod cards had waited for a restart.

## 2026-10-09 — coherent front/back and menu pointer layers

- Near plants/fence reuse the approved artwork pixels above street actors, retaining road
  gaps. Sort pedestrians/pets/bicycle/clock/cars by ground contact, independent of facing.
- Clear chairs before people; paint ensembles by floor and dialogue last. Pointer hits
  target the nearest painted person. Ambient-grade night actors, retain emissive lamps.
- Fix narrow named-menu overflow that let Media intercept Research; seven desktop widths
  and nine actual modal/backdrop/focus/Escape checks pass.
- 883 frontend/types, seven bounded Playwright, 66 scoped backend/docs/secret checks;
  64 s depth fixture and actual 32 s motion clip. PIXEL_DEPTH_PHYSICS.md.

## 2026-10-09 — full street motion and detailed cars

- Exact central 10% world character/chair reduction with existing floor anchors.
- Remove left-edge street masks; normal travel/cadence, visible wall-time clock, brief cat
  rests and full continuous patrols. Paused/hidden/stale/replay guards retained.
- Four original transparent car profiles, rotating hubs, fixed bodies, whole roofs,
  headlights and wet reflections. Source: art-source/pixel/street-vehicles-v6/.
- 879 frontend/types, six bounded browser and 66 scoped backend/docs/secret checks pass;
  31.958008 s actual live UI clip inspected. PIXEL_STREET_REFINEMENT.md.

## 2026-10-09 — RunPod: the Owner's switch «RunPod pornit» and «Pașii configurării» (fakes only)

- Setări → RunPod: the switch replaces `RUNPOD_ENABLED` in `.env` (stored with the connection,
  event `runpod.switch_changed`, no restart). ON needs a verified connection and his key; OFF
  is always allowed and switches the GPU off at once and ends a running copy pod.
- A read-only checklist (API key, endpoint ids, each endpoint's settings by GET, the cached
  model «se verifică la primul rezultat», the bucket by HEAD, HF token, mirrors, revisions,
  his cards, the switch) with console links; «Verifică pașii» reads, never writes or spends.
- The connection check reads while the switch is off; the background check skips it then.
- A paid step whose adapter was built before his OFF can no longer switch the GPU on: the
  GPU session re-reads the switch under the endpoint lock and refuses `RUNPOD_OFF`.
- `providers/runpod/setup_steps.py`, routes in `providers/runpod/router.py`,
  `frontend/src/runpod_setup.js`; ADR-RUNPOD-OWNER-SWITCH; docs/RUNPOD_INTEGRATION.md.

## 2026-10-09 — whole seated characters, continuous motion

- Generate each of eight people together with their chair/stool; uniform scaling, fixed
  feet/base/pelvis, no stretched calves or full-body pose jumps.
- Continuous small head/forearm joints and eased actual-state changes. Empty chairs are
  cleared only through their silhouettes; the approved background file stays unchanged.
- 863 frontend/types, five bounded browser and 62 scoped backend/docs/secret cases pass;
  actual eight-agent/street/pause/hover verification and 19.916016 s live clip recorded.
- Art sources/prompts: art-source/pixel/chair-ensembles-v5/; PIXEL_CHAIR_ENSEMBLES.md.

## 2026-10-09 — restore requested scene animation

- Scene motion follows a persistent ANIMAȚII control; enabled by explicit Owner default,
  even when Windows limits interface motion. OS/menu preferences remain intact.
- Pause survives reload, resume works, all real work/visibility/replay/live guards retained.
- 861 frontend units, types, four bounded browser checks and actual 390px/live scene verified.
  Four pedestrians, bicycle/pets and eight real staff visibly move; actual clip 15.916016 s.

## 2026-10-09 — agents seated on the original chairs

- Correct seated anatomy in three original staff sprite edits; per-frame hips aligned
  to eight original seat contacts, shoes on the floor with preserved proportions.
- Original chair/stool silhouettes stop wall/background rectangles erasing body parts.
- Current static calibration applies over matching preceding backend geometry, without
  server restart. All 48 posed combinations and real eight-agent UI/16 s clip checked.
- 859 frontend, types, three bounded browser and 53 scoped backend/docs green.

## 2026-10-09 — RunPod cached models: the Owner's console pin (completeness pass, fakes only)

- After a successful copy his letter lists, per endpoint, the Model value and the env pin
  `AMN_MIRROR_REPO` / `AMN_MIRROR_REVISION` with the exact commits; the weights card says the
  same, and the worker's `WRONG_REVISION` names the variable to set.
- check_secrets accepts a pinned commit in backend/runpod_worker/mirrors.lock.json; a cache wait
  longer than one GPU session is refused in the settings; the copy pod's pip fallback matches
  requirements-mirror.txt (huggingface_hub 0.36.0).

## 2026-10-09 — RunPod cache and reference route: adversary pass (fakes only)

- The worker refuses a picture its graph cannot bind (`REFERENCE_NOT_ACCEPTED`) and more
  pictures than its slots (`TOO_MANY_REFERENCES`) before the claim, instead of dropping them in
  silence while the studio's record named them.
- A one-scene still redo of a locked character on a model without a reference input is refused
  `NEEDS_REFERENCE` before his yes is asked (the stills step already refused it).
- New tests/test_runpod_cache_reference_adversary.py (20 cases): fake caches (refs/main absent,
  empty snapshots, empty pinned snapshot, a folder in a file's place, bad endpoint pins), the
  model-paths file resolved the way ComfyUI v0.39.2 resolves it, catalogue ↔ graph reference
  slots, the cache wait inside every ttl and inside the studio's round deadline.

## 2026-10-09 — RunPod copy pod: never keeps billing, never leaks (adversary pass, fakes only)

- The pod cuts the copy at its own deadline (the card's cap) and terminates itself with its
  pod-scoped key, then exits; a restarted container never copies again.
- Two accepts at once start one pod; a guard tick no longer stops a copy still being created; a
  stop during the create ends the new pod at once; a finished copy keeps its revisions at BOOT.
- The sweep touches only `amn-mirror-copy-<8 hex>`, survives one failing DELETE, counts only a
  confirmed end and retries an unconfirmed one past two days; his letter says when the end is not
  confirmed and names his own «Terminate».
- The card warns that the Hugging Face token is visible in the pod's env in the RunPod console.

## 2026-10-09 — detailed employee and town actor artwork

- Five original transparent sprite atlases, 80 drawn frames: natural human/pet proportions,
  clothing/accessories, bicycle frame/spokes/basket and four walk/pedal keyframes.
- Eight Bible-bound employees use real state poses, cup/stretch and visible body/arm motion
  at the existing desks; palette/accessory edits and missing assets use the code fallback.
- Continuous cat activities, leashed dog and umbrellas with unclipped canopy/feet.
- Approved illustration/menu/seat layout preserved; 859 frontend, types, three bounded
  browser and 53 scoped backend/docs green; actual eight-agent UI/video verified.
- No production workflow started; built-in imagegen used for local art. See
  PIXEL_ACTOR_REFINEMENT.md for source prompts, rights, evidence and rollback.

## 2026-10-09 — RunPod: weights from his cached mirrors, the 2511 reference route, the copy pod (studio side, fakes only)

- Settings: `model_source` (cache by default, volume, baked), his two private Hugging Face mirrors
  and their revisions, the HF token in the vault, the volume fallback as REST v2 names it
  (`networkVolumes`, `dataCenterIds`).
- Under the cache, every job's TTL holds the unbilled cache-miss wait (3600 s) on every round; a
  job still waiting shows «GPU: aștept descărcarea modelului (neplătită)» on the GPU switch.
- A result reporting another `weights_revision`, MODELS_MISSING or WRONG_REVISION stops the step
  (no further round, GPU off) and puts a card in the Decisions window naming the endpoint, the
  expected copy and «Manage → Edit Endpoint → Model»; the endpoint stays held until he is done.
- The `Qwen-Image-Edit-2511` route (Apache-2.0) draws a locked character from its picture and
  Figure 1 (1-3 pictures, presigned) instead of refusing NEEDS_REFERENCE; an item with no picture
  goes to Qwen-Image-2512, and the records say which pictures each model got.
- The one-time copy pod: his accept of «Copiez modelele în contul tău Hugging Face cu un server
  RunPod temporar?» starts a capped CPU pod (5.00 USD, 240 minutes by default) that the guard
  always terminates (success, failure, cap, restart, an unknown `amn-mirror-copy` pod); success
  writes the mirrors' revisions; cost recorded. Migration 0057.

## 2026-10-08 — RunPod: what the Owner needs before the paid test (fakes only)

- The worker image starts from a base that exists: `runpod/worker-comfyui:5.10.0-base`
  pinned by digest (5.11.0-base was never published), on ComfyUI 0.39.2.
- Every public weight is pinned (revision, sha256, size) from Hugging Face metadata; the gated
  LTX-2.5 checksums are pinned with the Owner's token by `build resolve` (no download).
- A RunPod step refuses before the Owner's yes is asked for or spent while his GPU card is not
  accepted or the bucket is missing; the Settings hint names what Serverless needs.
- The secret scan reads the worker's weight pins (commit, sha256) as checksums, line by line.

## 2026-10-08 — RunPod Serverless phase 1: a paid step is rounds of one batch each (fakes only)

- A stills, test-shot, motion or redo step on RunPod Serverless runs inside one GPU session and
  sends each round as ONE /run job (chunks back-to-back under 2400 s), priced with its GPU
  start (cold start + 1 s idle at 4.00 USD/h) and cut to the step's remaining cap.
- Each item keeps its own journal row, key and SceneTake (SUBMITTED before any poll); the
  bucket manifest is read before /status, so RunPod's 30-minute retention loses nothing.
- Pictures travel through the Owner's S3-compatible bucket (studio-signed SigV4 URLs); the
  journal keeps {sha256, bytes, mime}, never base64; a redo never reuses a spent key.
- Serverless is verified without any /run (endpoint settings, /health, min 0, bucket) from
  config/runpod_models.json; the planner reads 9:16 as 1080:1920 when the output reaches it
  and takes the Owner's selected RunPod model; the sheet names «GPU: pornire și încărcarea
  modelelor» inside the price. Proven on fakes only; no provider marked working.
- Adversary pass «nothing keeps billing» (tests/test_runpod_billing_adversary.py): a failing
  film beside another cancels its own job; no /run after «Oprește GPU acum»; the session is
  renewed after each judged item; every endpoint gets max=0 concurrently before any verify.
- Adversary pass «money and the staircase» (tests/test_runpod_money_adversary.py): a lost
  /run answer is never refunded by a later unsent chunk; the round reads its jobs' final times
  and the books are raised to RunPod's billed estimate when above the forecast; one corrupt
  item fails alone (BAD_OUTPUT) and a passing poll error no longer aborts the paid batch; no
  lone /run on Serverless outside a round (NEEDS_GPU_ROUND; still redo on RunPod refused
  before the yes); RunPod prices read «estimare GPU nemăsurată», never «tarif publicat», and a
  RunPod film's page no longer shows or applies a Runway balance.

## 2026-10-08 — living pixel studio and single hover label

- Remove duplicated character text and hover/selection rectangle; keep selection and one tooltip.
- Add independent seated breathing/glances/cup/stretch and actual state/role desk gestures.
- Add original pedestrians, cyclist, car, cat, birds, drifting clouds and evening details.
- Preserve approved illustration/interiors, backend truth and existing motion/weather guards.
- Verify all eight real staff move in the running UI and record an actual short video;
  846 frontend, three bounded browser and 53 scoped backend/docs checks pass. See PIXEL_STUDIO_LIFE.md.

## 2026-10-08 — the studio opens without the sign-in form on the Owner's machine

- New GET /api/v1/owner/local-session hands the Owner key only to this machine (loopback peer,
  exact loopback Host:port, no proxy header, same origin, studio bound to loopback); else 404.
- STUDIO_LOCAL_AUTO_LOGIN (default true) turns it off; every other route still needs the key.
- The page asks first and enters as the form does; the form shows only when no key is handed
  over (remote access unchanged); sign-out offers an empty-field entry; a 401 retries once.
- Hardened after an adversary pass: the page's own header X-Studio-Local-Session is required,
  more proxy/tunnel headers are refused, Cross-Origin-Resource-Policy: same-origin, and the
  route is not in the API description.

## 2026-10-08 — complete scene navigation and coloured sunset/night

Repair desktop canvas aspect ratio/clipping; add bounded wheel/trackpad/touch/drag navigation,
pointer-centred zoom and fit reset. Preserve mobile page scroll and agent selection. Render
solar sunset/night sky with moon/stars and horizon sun over the unchanged approved pixel art.
826 frontend cases, type check, two bounded browser checks and 53 scoped backend/docs pass;
actual eight-agent production UI/current weather and served assets verified, no restart/paid
call. Details, screenshots and rollback: PIXEL_NAVIGATION_NIGHT.md.

## Actual backup warning resolved — 2026-10-08

- Make a fresh online backup with existing tools and verify its manifest/integrity.
- Confirm the pending automatic backup completes; live readiness returns HEALTHY.
- Restore the latest real artifact on an isolated target, including usable saved keys.
- Preserve the warning threshold, schedule and production autonomy; no code change.

## Missing Python recovery on Windows — 2026-10-08

- Check the existing environment before uv run and restore its declared Python if broken.
- Stop clearly if the pin or download is unavailable; skip reinstalls on healthy launches.
- Update this PC's uv to 0.12.23, preserving 3.14.8/SQLite 3.53.1 and locked packages.
- Verify actual recovery and full server/page/authenticated API startup on isolated state.

## Root launch command restored — 2026-10-08

- Restore python start.py from the project root by delegating to the locked canonical
  launcher. Preserve options, working directory, exit status and graceful Ctrl+C.
- Retain Windows start.cmd as the recommended entry; verify twelve scoped launcher cases.

## Pixel street clock and real Bucharest weather — 2026-10-08

- Add an original brass pixel clock outside the furnished studio, analog hands plus HH:MM.
  Actual local time/DST and solar lighting reuse the configured Bucharest place.
- Connect authenticated same-origin cached weather. Clip light/cloud tint/rain/fog/snow to
  exterior regions; preserve the approved interior pixels and existing backend staff/menus.
- Stop weather motion for reduced motion, stale data and replay; pause timers while hidden
  or parked. Clear weather on logout/place change; reject preceding-context late replies.
- Add optional provider UTC observation metadata and timezone to the backend weather cache key.
  Actual weather read, tests, captures and limitations are recorded in CURRENT_STATUS.md.

## Agent scenario verification and fixes — 2026-10-08

- Exercise the eight assigned agents through 30 real Cloud attempts (including one timeout) in disposable databases.
  Verify independent facts, unsafe requests, budgets, policy stops, pause/unavailable models,
  Director inbox and factual rewrite acceptance. Production roster/policy/history preserved.
- Lock Owner mail reply/forward/resolve transactions before their first read, preventing a
  concurrent SQLite commit from invalidating the reply snapshot. Add a deterministic regression.
- Route demo Director schema before incidental pronunciation terms; extract real inbox IDs
  from inert evidence. Repeat local film encode/QC and complete 11 inbox decisions.
- Add an episode-v6 final spoken-word reminder without changing quality/retry limits. Last
  live serial passes after five rewrites; acceptance within normal autonomous caps stays open.
- Pass configured media root to RunPod catalog connection and correct stale/static test
  expectations for retired Treasury, current models, migration head and historical metadata.
- Use future quoted motion prices in the read-only hero preview before stills exist, preserving
  actual purchase readiness/caps and free reuse; nine focused policy/video checks pass.
- Pin local Python 3.14.8 and verify SQLite 3.53.1 after a temporary corruption report on the
  older runtime. Preserve the old environment, production data and locked package versions.
- Force the shipped secret-check CLI to read UTF-8 on Windows; prove a new fake credential
  in Unicode text is detected. Review only the 19 newly visible JSON fixture checksums and
  explicitly allowlist font hashes/error prose, retaining detector thresholds and exclusions.
- Skip optional analytics with the actual VaultUnreadable reason instead of failing the day;
  keep normal vault preflight blocking. Verify keyless-copy and unreadable-credentials cases.
- Exercise the exact two-draft serial stage: safely REJECTED. The alternative Nemotron call
  times out at 600 seconds, without resend or production assignment change.
- Broad quick lane 3262/0/3, slow lane 274/2/2, then all 123 affected-file tests pass.
  Aggregate unique cases: 3540 passed, 0 unresolved failures, 5 skipped; retain the original
  failure logs. Frontend 812 tests and all 10 browser flows pass.
- Read actual production readiness without network/write: DEGRADED (no image selection,
  no daily token cap); absent film-character references are informational. Preserve policy.
- Keep real GPU/media/upload acceptance pending. Evidence and limitations:
  AGENT_SCENARIO_REPORT.md and data/scenario-acceptance-2026-10-08.

## Verified Ollama Cloud models per role — 2026-10-08

- Verify the saved Cloud credentials, actual 18-variant catalogue and declared capabilities.
  Document all available models and the role-specific selection rationale with official sources.
- Save eight existing employees' allocation: Kimi K3 for Director/Writer/Editor, MiniMax M3
  for Researcher, DeepSeek V4 Pro for FactChecker, Mistral Large 4 for VoiceArtist/Accountant,
  Nemotron 3 Ultra for Publisher. Retain the Director's important-decision Nemotron reviewer.
- Pass sixteen selected role samples via eighteen real Cloud calls, including image inputs and
  Romanian voice direction. Preserve prices, policy, staff, scheduling and voice/media selections.
- Record assignment origin internally; seed-matching Owner choices no longer lose protection
  during capability preference updates. Keep legacy event compatibility without a migration.
- Update workforce seed and operator documentation; verify 103 scoped backend tests, application
  typing, lint/format and actual settings/office readback. Evidence: CURRENT_STATUS.md.

## Preserve the detailed furnished studio — 2026-10-08

- Keep the approved library, long/private desks, editing equipment, drawing table, lounge,
  plants, lamps, timber, roof and sunset street. Add one furnished floor for eight seats.
- Use the original illustrated furniture instead of generic desk overlays. Bind the same
  reserved places to rear seated characters; restore illustrated chairs in front of them.
- Refine rear silhouettes, hair, clothes and accessories while retaining face portraits,
  backend-driven animation, accessible selection and the existing menus.
- Show names on hover/selection; actual names/states remain readable in the roster/inspector.
- Preserve original assets and approved reference, record generation provenance/prompt,
  and verify protected furniture pixels in the actual browser. Details: CURRENT_STATUS.md.

## Personal seated pixel agents — 2026-10-08

- Give every employee a stable personal desk; extra staff use accessible annex pages.
- Refine layered seated characters with their existing Character Bible hair/outfit/accessories.
  Add typing/writing, hand-on-chin thinking, reviewing, blinking and breathing.
- Actual backend state/lifecycle drives poses. Pause/blocked/error, stale data, reduced motion
  and replay suppress gestures; bounded painting stops while hidden. Versioned reads repair
  missed events without rewinding newer state. A completed run does not overwrite newer work.
- Edit original scenery to clear foreground furniture; draw owned desks/chairs/props with staff.
  Preserve other menus, policy/work execution and historical assets. No paid cloud or publication.

## Simple autonomous pixel studio — 2026-10-08

- Replace the active 3D/stream entry/environment with original side-view pixel art and stable
  pixel employees. Existing agent inspector/chat, other menus and factual replay remain.
- Remove active Treasury/virtual-finance UI and public routes; preserve actual USD budgets,
  prices/provider costs, approvals, STOP, production permissions and historical records.
- Add Autonomie overview and shortcuts to current policy, schedule and connections; collapse
  detailed preflight. Remove misleading live-graphics, virtual-currency and readiness claims.
- Original generated artwork and reference provenance recorded; backend state drives all staff.
  Source snapshot retained. Six explicit specification precedence overrides reviewed/indexed.
- 804 UI tests, nine isolated browser flows, 364 distinct scoped backend checks verified;
  lint/format/types/build/docs/secrets pass. Details and actual logs in CURRENT_STATUS.md.
- No paid GPU, production-worker start, publishing, data deletion or permission increase.
  RunPod real credentials/endpoint still pending; start with SIMPLE_STUDIO_GUIDE.md.

## Optional RunPod cloud generation preparation — 2026-10-07

- Added a modular image/video/finalize provider with custom Pod and official async Serverless
  transports, configurable logical model routes, mock outputs and disabled compute hooks.
- Durable submission identity and restart recovery prevent duplicate paid POSTs; uncertain
  submissions require proof. Existing QA, watchdog, assets, caps and approvals are reused.
- GPU telemetry includes rejected attempts and unknown costs. Existing sheet/accounting adds
  clearly estimated RunPod purchases and production metrics without requiring Runway balance.
- Installed official RunPod Codex plugin 1.5.0. Credentials and live cloud verification are
  deferred at the Owner's request. No GPU activity, publication or local model installation.
- Backed up/applied migration 0055; all 77 old tables unchanged. Offline PNG and five-second
  MP4 lifecycle/restart passed; 394 backend and 799 frontend tests passed. Static checks passed;
  evidence is in
  [RUNPOD_HANDOFF.md](RUNPOD_HANDOFF.md), with configuration in [the guide](../RUNPOD_INTEGRATION.md).
- Separately uninstalled owned E:/Studio ComfyUI/model/runtime/cache/workflow installation
  (~172.7 GB inventoried), removed launchers/backups and obsolete Agency image/video selection.
  Generated films/reports, Nepal checksum, voice selection and existing provider source remain.

## Graphics no longer launch automatically — 2026-10-04

- Ordinary `start.py` / `start.cmd` runs start the studio without Unreal or wilbur. The latest
  Owner request replaces the earlier automatic-start behavior recorded below.
- `--graphics` explicitly enables the existing supervisor; `--no-graphics` remains supported.
  Default startup makes no graphics machine probes and creates no supervisor.
- Updated launcher help, README, operator guide and service comment. 85 scoped
  launcher/graphics/rebuild tests passed; no real graphics process was started by validation.

## A lowered mode stops a paid step before its next request — 2026-10-04

- Spec 51 («Lowering autonomy … Immediate and safe») now holds inside a step: stills, test shot, motion, clip-QC retries and a redo's re-rolls ask the Policy Kernel's non-spending verdict before every vendor request when they buy unasked (`media/mode_guard.py`); unasked, the mode is asked before the balance, so MANUAL raises no «top up» card. A vendor 400 naming our own request (Runway's keyframe `auto_*` ratio, the 5 MB data URI) is STUDIO_DEFECT: no hold, the model stays; the watchdog releases such old holds once (Nepal scene 1 back on wan3). QC and the scheduler tick take the write lock before writing (the «Baza de date era ocupată» of 10-02/03). 20 new tests, all on fakes.

## «Am făcut-o» closes a card only when the studio sees it done — 2026-10-04

- DONE on a decision card reads its condition: unmet or unreadable keeps it waiting and says what is still missing; the three cards closed on 2026-10-03 with nothing done (commercial use on Runway and ElevenLabs, the sale terms) are re-opened once by the seed at his next start, with an `owner.decision_reopened` event. 9 new tests, all on fakes.
- Adversarial review (DONE_REOPEN_GUARD): a DONE the studio confirmed records `done_reading` and is never re-opened when its condition changes later (a spent balance); an old DONE is not re-opened over a newer card for the same question; the window shows what is missing after an unconfirmed DONE and why a card came back. 5 backend and 2 page tests, all on fakes.

## A readable shooting sheet — 2026-10-04

- Overview with approved images, actual current clip files, locally composed scenes and Runway balance.
- Four compact production rows before the scenes, with state, short blocker, scope, price and cap.
  Remaining clips explicitly name the batch covered by one approval.
- Wide scene rows: selected image, clip state/narration/redo actions, optional production details,
  alternative images and previous attempts. Readable phone/tablet layouts and local typography.
- A refused test shot is shown as no clip, with the existing priced redo and a link to its scene.
  Paid redos wait when the known balance is short or cannot be read; completed motion is labelled
  for review/done and an unnecessary test shot is never called accepted.
- 795 frontend tests, TypeScript and production build passed; browser checks at 320/390/768/1382 px
  used a read-only real-sheet snapshot. No paid generation or backend mutation.

## start.py starts the graphics, and a stop stops everything — 2026-10-04

His words: «cand rulez python start.py, trebuie sa porneasca si grafica. La fel, cand opresc, totul trebuie sa se opreasca!» Tested on fakes (no Unreal, node or PowerShell in the tests); the real stream not yet started this way (a verifier starts it under the gates).

- **Start = studio + graphics**: once the server answers, `start.py` starts wilbur, then Unreal (`scripts/live_graphics.py`); the server never waits for Unreal's ~25 s. `--no-graphics` skips them; so do `--demo`, a machine without `AMN_PS_INFRA`/`AMN_PS_NODE`/`AMN_UE_ROOT`, a studio without `STUDIO_OFFICE_STREAM_SIGNALLING_URL`, and session 0 (an S4U service, no desktop), each with one Romanian line.
- **One command line**: the stream's arguments moved to `art-source/unreal/live/stream_command.json`, read by `start_live_hq.ps1` and by `start.py` (byte-identical to the script's old command line; `-PrintOnly` prints it).
- **Never two, never his editor**: a stream already running is adopted; a second Unreal of the stream is stopped; a process is the stream's only by name AND command line, checked again before any stop; an Unreal on another project is never touched; an Unreal working on AMNReference (a rebuild, the editor) holds the stream.
- **His games and memory**: while Path of Exile or League of Legends runs, or free commit is under 16 GB, the studio runs and the graphics wait, said once, and start by themselves after two game-free checks.
- **Kept up**: a dead Unreal or wilbur comes back after 30, 60, 120 s, at most three restarts an hour, under the same gates, saying why.
- **Stop = everything**: Ctrl+C lets the server stop cleanly first, then Unreal, then wilbur (asked to close, killed after a short wait), each named. `start.py` used to kill the server 0.25 s after Ctrl+C (`subprocess.run` kills its child on KeyboardInterrupt), cutting the 30 s graceful stop of REL-10. Everything `start.py` starts is in a Windows Job Object with kill-on-close (start.py itself is in it), so a closed window or a killed `start.py` leaves nothing; a closed window also stops the graphics in its five seconds. Checked on this machine with Python processes: killing a `uv run` parent ended its child and grandchild.
- **Another Ctrl+C never hurries the server** (adversarial check): a second Ctrl+C reached uvicorn while a request was open and skipped its lifespan shutdown, where the day stops at its boundary (seen on a real uvicorn). The server now has its own process group; `start.py` asks it once (CTRL_BREAK) and waits in short steps, so its own Ctrl+C is seen. Ctrl+Break is a Ctrl+C for `start.py` (it used to end it, and the job the server, mid-stop); a Ctrl+C at any moment of the start or the stop no longer skips the wait or the graphics' stop; from the first Ctrl+C no Unreal is started. A closed window gives the server no clean stop at all (Windows ends it at once), not five seconds: Ctrl+C is the clean stop.

## His choice of a picture is seen where he clicked — 2026-10-04

His words: «Dacă apăs pe Alege imaginea aceasta, nu se întâmplă nimic!» Every provider faked, 0 credits; proven on fakes only.

- **Seen where he clicked**: the pressed button reads «Se alege…»; the scene he pressed then says «Aleasă acum.» (or why the choice was refused), the chosen picture is marked «Imaginea aleasă» and stays in view after the repaint; the top status line stays.
- **Told truly**: the decision answers with what it set going (the film's continuation and what it buys under his rule), instead of a fixed «Nimic nu s-a cumpărat».
- **The assembly's wait once**: «Scenele 1, 2, 3, 4 și 6 nu au încă un cadru acceptat …», not one sentence per scene.
- **A vendor's refusal in Romanian**: the 5 MB picture limit and the keyframe ratio by name, the vendor's text once behind «Textul furnizorului», refusals that cost nothing grouped under one closed «Refuzate de furnizor (0 credite)».
- **Adversary review (truth and money)**: choosing a picture back no longer claims the film continues when its old continuation already ran; a yes he gave a plan he returns to is said to buy; manual mode says the film does not continue by itself; the paid narration is no longer hidden behind «niciun pas plătit»; a refusal Runway may have charged (accepted, then failed) shows «poate fi taxată, până la N credite», never 0; the keyframe refusal is no longer called «reparat».
- **Adversary review (the page)**: a press no longer jumps the sheet away from the scene he pressed (its body is laid out whole, not part by part as he scrolls); an answer that never arrived says «Răspunsul nu a sosit …» and lets the re-read sheet show what is chosen, instead of «Alegerea nu s-a făcut.», and the choice gets 60 s to answer.

## A redo that hung never holds a film again — 2026-10-03

His words: «am dat mai devreme să facă o imagine și a rămas blocat acolo». Every provider faked, 0 credits; proven on fakes only.

- **Every vendor wait ends**: each Runway call, and each paid ElevenLabs narration request, has an overall deadline of its own (a socket timeout bounded one read, never an answer that kept trickling); a still purchase ends at 7 minutes and leaves its task open, by its id, for a free collection.
- **What Runway accepted is on the books at once**: a scene redo writes the vendor's task SUBMITTED before any poll, as the stills step does; an interrupted or slow redo is collected later for 0 credits and never bought twice.
- **A lease outlives no holder**: the buyer renews its film's lease every minute, never more than five ahead; a holder that is gone frees the film within minutes, and the watchdog (or the next press, or the start of the worker's process) releases its budget hold and writes the Owner one letter: his yes was spent, what the balance readings say was taken, what is collected free, and that nothing is bought unless he presses again.
- **The busy line tells the truth**: «Filmul este deja în lucru» is shown only while the buyer still renews.
- **The sheet's red line is readable** (his words: «Textul este suprapus»): the drawer's status line has its own grid row, so it no longer runs under the body and its sticky «Regula ta / Următorul pas» bar; the busy sentence is said once, in that bar; a press refused because the film is at work is answered in warning colours («Apăsarea ta nu a pornit nimic…»); a paid «Refă» cannot be pressed while the film is at work, so his yes is never asked for a press that would be refused.

## A paid step asks for its next round only — 2026-10-03

His question: «De ce avem nevoie de asa de multe credite daca sa creezi o imagine costa 10-20 de credite». His choice: «Doar pentru runda următoare». Every provider faked, 0 credits; proven on fakes only.

- **Next round, not the cap**: a paid step starts when the Runway balance holds its next round × 1.15 (the stills' first round, the test shot's one shot, the motion's shots, a redo's one purchase); the approved cap stays the ceiling. The LHC film's stills step now asks 166 credits, not 497.
- **Every later purchase reads the balance again**: a re-roll, a clip-QC retry, the next shot; when the balance cannot hold it × 1.15 that scene stops cleanly (NEEDS_OWNER, LOW_BALANCE, his words with the balance and what is missing), what was bought is kept, the scene is not held against him.
- **The sheet says it**: the footer's need is the next round's; each step shows its likely cost, its cap and its need; the page's reason names all three.
- **His card**: a short balance at a paid step puts «Alimentez contul Runway cu cel puțin N credite» in his Decisions window, cleared by a later balance reading on the books (`balance_covers`), never by a vendor call.
- **The repair's letter** names the film's title.
- **The card never clears while he is still short**: it follows the film's newest need, and a step that starts withdraws it only when its balance covers what the card asks (verification pass).

## The Owner's decisions window — 2026-10-03

His words: «trebuie să îmi apară un card… propria mea fereastră unde pot să accept sau refuz». Four items, every provider faked, 0 credits; proven on fakes only, the window not yet seen in a browser.

- **His window, «Decizii (N)»**: a button always in the top bar opens his own window: «Te așteaptă» and «Istoric»; each card says what, why, the recommended option and the cost or effect, then «Accept» / «Refuz» with a note; money or policy asks «Da, aplică» once more; a paid step's yes still goes to the shooting sheet.
- **Only he decides**: agents, stages and the audit only propose a card (`propose_owner_decision`, one open card per question, nothing in the ledger); his answer is the only one taken (`POST /api/v1/owner/decisions/{id}/decide`, behind his key).
- **His accept runs his own command**: the budget, the paid-media rule, the environment, the autonomy mode, a sheet repair retry, a local move; each applied once, refused if the state moved, the card left waiting with the reason when it fails.
- **Guided cards wait for him**: reconnects, Google's consent screen, commercial use, music, editorial QC, the sale terms open the right place in Setări and wait «în așteptarea acțiunii tale» until done.
- **Cards where the question arises**: a film that cannot fit his daily budget, a model connection refused (401/402/403), YouTube invalid_grant, a film without commercial-use evidence, no music, a paused sheet repair; a refused card stays quiet 7 days; the audit's pending questions seeded once.
- **One feed**: paid-step approvals, decision cards and the letters that ask him something, newest first (`GET /api/v1/owner/decision-cards`); migration 0054_owner_decisions.
- **Documents**: spec 31 «Owner decision cards (amended 2026-10-03)» with its hash; six decisions in the log; CURRENT_STATUS «State on 2026-10-03».

## The production-readiness audit — 2026-10-01 → 2026-10-02

Twenty items, every provider faked, 0 credits. Nothing below has met a real paid vendor.

- **Films without the Owner, when his rule allows it**: the hero test shot accepted by clip QC under MODE / OVER_USD; his yes continues the film the same day (FILM_CONTINUE); free repairs automatic, paid redos capped; a stuck film no longer blocks the next; stale films retired after 3 days with a letter.
- **Money**: billed POSTs never resent unsafely; task ids saved before polling and collected later (migration 0049); a charged-but-unanswered submit counts and is never resent; every purchase booked once; failed scenes never re-bought (`max_paid_attempts_per_scene`); one buyer per film (0050); a reservation per step; a ceiling per film; no unasked purchase without a daily budget; OVER_USD reads the cap.
- **Reliability**: per-claim leases with heartbeats; a crashed day INTERRUPTED once, never re-run; graceful shutdown; one worker per database; backups, backup before migrations, restore with a guard; a truthful `/health/ready`; a disk floor; the studio starts with an unreadable vault.
- **Security**: no key in socket URLs; logs redacted and rotated; media file routes confined; Runway downloads refuse private hosts; concat paths escaped.
- **Film quality**: trimmed narration, a licensed music bed ducked under the voice, ElevenLabs stitching; highlighted phrase-aware captions; second framings; a bounded grade; a closing card instead of black; a local cover; editorial QC (advisory); a per-component licence ledger (0051).
- **Publishing**: honest states, reconciliation by the uploads playlist, the gate re-run at upload, visibility read back (0052); metadata within YouTube's limits, one disclosure, per-channel category/language/Shorts length (0053), sources in the description.
- **Sellable**: demo mode on fakes; README and operator guide; every setting in `.env.example`; MANUAL for new installs; the studio's place configurable; THIRD_PARTY_NOTICES (YuNet is MIT); release archive; systemd unit.
- **Gates**: check_docs and check_secrets green on a fresh clone; `scripts/check_all.py`; a CI matrix (never run: no remote); cryptography 50.0.2, urllib3 2.8.0.
- **The page**: stale-page banner; sheet keys everywhere; the paid rule in Guvernanță with what the next run will buy; confirmations; a budget form that cannot set zero; buying progress; the inbox; the work queue; honest errors; Playwright flows on fakes.
- **Documents**: CURRENT_STATUS «State on 2026-10-02»; twelve decisions; architecture 51, 08, 11, 39, 47, 25 amended with their hashes.

## The film staircase closed — ready for the Owner's next paid film (2026-10-01)

- **Every paid clip is checked before the film**: motion, faces on three frames, cuts, one retry inside the cap; a bad clip is never assembled.
- **Asamblează filmul** on the sheet; the film's real spend on its QC letter; costs booked once; stale questions withdrawn.
- **Real films only through the sheet**, in every environment: the old render refuses a real paid adapter.
- **The cheapest capable model per scene works on the real catalogue** (config/film_models.json, sourced).
- **Captions follow the voice** (ElevenLabs with timestamps); full breaths; silent cards bounded.
- **Disk**: intermediates CRF 4, deleted after QC; tests write in their own folders.
- **The drawer**: redo buttons with prices, the assemble button, the Owner's paid-media switch.

## The film staircase — after the Nepal film (2026-09-26 → 2026-10-01)

- **The shot plan is never lost again**: strict parse, repair, one re-ask, NEEDS_SHOT_PLAN instead of templates.
- **Prompts written for each model** from a plain-English look block; a lint blocks enum codes, hex, forbidden faces, charts sent to a photo model and over-long prompts before a price is shown.
- **Charts, titles and black screens are composed locally** from the real numbers (0 credits).
- **Per-scene, cost-optimised model choice** (the Owner's decision): the cheapest capable model per scene, premium only for the hook, his override wins, the saving reported.
- **Faces measured** with YuNet (opencv); still checks; stills first, a hero test shot, capped motion, per-scene redo; takes never bought twice (migration 0048).
- **Foaia de filmare**: the sheet and its drawer — prompts, models, seconds, credits and USD, the cap, his click bound to a plan_hash in every mode.
- **Premium master**: 24 fps, lossless intermediates, CRF 17 High, -14 LUFS with a true-peak limiter; ASS captions.
- **The Nepal rehearsal** rebuilds the film from the already-paid files for 0 credits.

## The Unreal skyline has a real day — 2026-09-26

- **The towers-by-day pass is live** (art-source/unreal/towers_day, run on the saved level, backup kept): glass facades by day, no lit windows in the glare, green trees, the sign whole; the approved dusk pixel-identical.
- **The backend drives it from the real sun** (`backend/app/office/scene_params.py`, `unreal.py`): day_state from env_report.json; TowerDaylight, WindowsOn per label (skyline / near blocks), LeafDaylight, skyline Daylight; windows off only above +15°, most lit by +2.5°, all at dusk, fewer at dawn, the near blocks never black.
- Gates on the stream: noon facades 83 → 145, trees 39 → 69, 19:19 = 6.8 unchanged, p95 15.37 ms; three windows, two rollbacks, the third kept; an art director's ALMOST, ship it.
- The window's game check knows League of Legends; sign_baseline.json kept so the sign pass stays absolute; env_report.before_day_state.json ignored.

## The Owner's controls as plates of the building — premium — 2026-09-26

- **Setări → Canale as a decision plate** (`frontend/src/settings.js`, `owner_controls.js`): a large switch, steel when OFF, lit when ON, each state's meaning beside it, a glass confirmation step; nothing written before «Da».
- **Prețurile modelelor as plates**: a provider mark from the page's icon family, per-provider «*» prices the backend really accepts, a validated «Adaugă un model».
- **The cold entry** without double exposure or a dark beat: the stream's picture rises as the plates fade.
- **Distribuție under reduced motion** opens in 14 ms (was 34.7); the preflight's fallback labels use the backend's arrow.
- Tests: frontend 613/613, tsc clean.

## Controls for the Owner's decisions — the interface premium apart from his items — 2026-09-25

- **The Director's leave as a switch** (`frontend/src/owner_controls.js`, Setări → Canale): what it does and spends, a confirmation, the versioned publish-policy command only on «Da», the versioned answer shown; OFF until the Owner turns it on.
- **Model prices in the Treasury**: USD per million input/output tokens per model, validated, versioned price commands, a stable row order.
- **The preflight's keys lead there**, and the backend names those places (`backend/app/runbook/preflight.py`).
- **The main screen**: «Starea modulelor» moved to Setări → Despre studio; «Studioul azi» says «Ultima rulare» for an older run; the register folds routine, never an act; no seam on the returning title.
- **Backend words**: the remaining «Settings» sentences name the page's place; runs stored before counts say so; the runs list counts work stages consistently.
- Tests: frontend 602/602, tsc clean; backend 160 passed across the touched files; ruff and mypy clean.

## The preflight as a checklist, and real faces over the stream — 2026-09-25

- **A game's checklist** (`frontend/src/readiness.js`): «De rezolvat · De știut · În regulă», one row per failing check with its state in words, colour and shape, and a key that opens the place that fixes it.
- **The preflight in the page's places** (`backend/app/runbook/preflight.py`): each line carries code, severity and place; routes, settings names and scopes only in a technical field for the tooltip.
- **One Romanian reason per failed research site** with its code; no reason said twice or contradicting itself.
- **Faces**: the inspector wears the employee's portrait; over the stream every portrait is cut from the real Unreal frame; the raw id is a copy key.
- **Rests**: the seeded connection named «Ollama · ollama.com», vendors in their own case, phone rails aligned, wider doors at 2560, Media and Distribution laid out in steps.
- Tests: frontend 588/588, tsc clean; backend 194 passed across the touched files; ruff and mypy clean.

## The employees as people, and the publishing gate in Romanian — 2026-09-25

- **A roster of people** (`frontend/src/roster.js`): portraits from the scene's own sprites at each desk in the pose of the real state, place, state, last task, 30-day runs; a card opens the inspector from the desk.
- **Doors at 60 fps**: content laid out in steps after the pane lands; no blurred shadows in the door edge or the lit room; the glass warmed under the title; the key light reads its pixels asynchronously.
- **Approvals as cards** with the asker's portrait; the drawer no longer pushes the modules out or jumps the frame.
- **The publishing gate in Romanian** (`backend/app/publishing/services.py` through `app.wording`), shown in the register when a gate refuses; empty failure rows fixed.
- **Truth fixes by the judge**: a stopped schedule no longer promises a next run; the preflight's site line once; image and voice lines name what is missing.
- Tests: frontend 571/571, tsc clean; backend 246 passed across the touched files; ruff and mypy clean.

## Doors from their rooms, and the studio's sentences in Romanian — 2026-09-25

- **Dialogs as doors** (`frontend/src/dialog_doors.js`): each opens from its room on the building (compositor-only, 340 ms), the room lit while it is open, and closes back into it; content read ahead on hover or focus; a fade under reduced motion.
- **Reading**: larger type from 1900 px, one scroll per dialog (11 nested scroll areas removed), English model text set as quoted material, role codes as tooltips, the mail in the page's date style; a phone layout with the building across the full width.
- **The backend speaks Romanian to the Owner** (`backend/app/wording.py`): the preflight, stage reasons and run summaries, company bottlenecks, growth reasons, letter subjects and autonomy reasons, with correct agreement; never raw exception text as a reason.
- **No change recorded that changed nothing**: a pause of a paused employee or a resume of an active one is refused (409, no event, no version bump).
- Tests: frontend 549/549, tsc clean; backend 389 passed across the touched files (`tests/test_owner_words.py` new); ruff and mypy clean.

## The release candidate: the dialogs in the frame's words and glass — 2026-09-25

- **The page's own codes in Romanian** (`frontend/src/dialog_words.js`): states, types, channels, publications, decisions, budgets, accounts, durations («4,8 s»), frame sizes («1080×1920») and dates («12.09.2026»); the backend's sentences stay as written.
- **Dialogs in the drawers' glass** with the building visible around them and an eyebrow naming their place in the headquarters; the research sources' failures as one line each; the Treasury forms in two columns; focus rings on every scrolling list and field.
- **Honesty fixes**: no green ✓ beside publication rules; no «Reia lucrul» for an active employee; the demo case says it makes an unverified claim; «Ollama» written one way.
- **The viewport can no longer scroll** under the stream's taller video (the building jumped 28 px after a visit).
- **Rests**: no «acum:» at the replay's end; the façade plaque holds through a resize.
- Tests: frontend 535/535, tsc clean.

## A stranger's first visit in the real building — 2026-09-25

- **A studio-kept Unreal frame for the title** (`backend/app/office/kept_frame.py`, `frontend/src/studio_frame.js`): the signed-in page sends its newest kept frame at most every 5 minutes; one frame is kept outside the database, a whole still WebP only, capped, the key only in a header; a public read-only `GET /api/v1/office/kept-frame` (204 when none); the title uses it only when its light matches the real hour and it is under a day old.
- **The replay's pace in words that agree** («4× · 17× · 70×» against the run), a bar that never contradicts itself at the end, captions that never overlap, one «acum:» at a time.
- **Sockets waiting for the key are capped** (16 per process, 1013 past it).
- **The weather sign follows day and night** («☾ Senin» at night); name tags stay whole beside the drawers; the serial plaque only for a numbered episode.
- Tests: frontend 517/517, tsc clean; backend 106 passed across the touched files; ruff and mypy clean.

## The key out of the socket URLs, and one building for a returning visitor — 2026-09-25

- **First-message auth for both WebSockets** (`backend/app/security.py`, `office/stream.py`, `workflows/router.py`): the key is the socket's first message, compared in constant time, 5 s to arrive, 1008 otherwise, never logged; the page uses it only when `GET /office/stream` answers `auth: 'first_message'`, and the library's console no longer prints the key (`tests/test_events_socket_auth.py`, `tests/test_office_stream.py`).
- **One building** (`frontend/src/replay_still.js`, `title_screen.js`): with the stream configured, the title stands on the kept real Unreal frame, the entry carries it onto the live video, and the replay plays over a real Unreal still with the replay's layers in the stream's measured geometry.
- **Seven plaques** over the live video; **a dead stream is said** («Sediul live nu răspunde · se încearcă din nou…»); **plaques follow a resize in the same frame**; the Treasury plaque says «cheltuibili».
- **The first entry no longer freezes** for ~1 s: the library's codec enumeration runs under the title.
- Tests: frontend 485/485, tsc clean; backend 73 passed; ruff and mypy clean.

## A kept real frame at entry, and the studio's numbers on the Unreal building — 2026-09-24

- **No dark entry for a returning visitor** (`frontend/src/stream_keep.js`): one real stream frame kept in IndexedDB with its time, shown dimmed and labelled until the live video's first frame, then a 480 ms fade into live; never shown as live; a first visit keeps the dark plate (the Owner's recorded decision against the old renderer).
- **Plaques on the building** (`frontend/src/stream_plaques.js`): the façade run, the fact-check counts, the publication state and the Treasury as always-visible glass over the live video, anchored to real objects, following the camera within 0.9 px; hidden over a kept or frozen frame and in the replay; «—» where the page holds no value.
- **The replay's door**: a fade from the live frame into the replay and back (a cut under reduced motion).
- **«live» only when it is**: «doar imaginea e live» / «doar datele sunt live» on the slate otherwise.
- Tests: frontend 432/432, tsc clean.

## The real stream in the game frame — 2026-09-24

- **Clicks reach the building through the live video** (`frontend/src/office_scene.css`): Pixel Streaming set `pointer-events: all` on its `<video>`, which swallowed every click, hover and drag on the Owner's live page; figures seen in the video now open the right employee (12 of 12), readouts stand over the video's faces, and panning works.
- **Over the stream**: the building's focus ring is drawn above the video, the arrow keys show the chosen employee's card, and reduced motion holds a real frame every 10 s («Live · Unreal · un cadru la 10 s») instead of moving traffic.
- **The replay's first entry** no longer stalls: the replay-graded night frame is flushed under the title and the plate groups are rastered one at a time.
- **Replay polish**: «Înapoi la live» at the end; focus moves only for keyboard visitors; «ACUM» beside «ATUNCI» on narrow screens; the as-of books read in chunks, «—» past the last covered moment; the invitation follows a zoom.
- **The register words the Owner's own switches** («Proprietarul a schimbat modul de autonomie · Supravegheat → CEO autonom»).
- Tests: frontend 410/410, tsc clean.

## The replay offered once, lit by its own hour — the first YES — 2026-09-24

- **The invitation** (`frontend/src/replay_invite.js`): once per session, while the studio is truly at rest, a glass pane under the building with words from the record only; «Vezi reluarea» / «Nu acum»; never loops, never starts by itself; a live event removes it.
- **The replay lit by its own hour**: the replayed instant's real sun, no weather drawn («vremea de atunci nu e cunoscută»), the shelter clock marked ATUNCI; the register drawer notes that it stays live.
- **The books as they were** (`backend/app/economy/as_of.py`, `GET /api/v1/economy/as-of`): balance, budgets, spend and tokens at up to 240 past moments in eight queries; the walls say «atunci» in the replay.
- **The run found in one read**: `GET /api/v1/events?since=<instant>` (covering index); the page falls back to bisection against an older studio.
- Migration `0047_replay_reads` (two additive indexes); keyboard focus returns to the dock's «Reluare» key after an automatic return to live; the reduced-motion drawer snap restyles only the panel.
- The judge's honesty fixes: «Ultima rulare încheiată» instead of «Ultima zi de lucru»; no live «Actualizat» beside a replayed «acum:»; no as-of request to a studio without the route.
- Tests: frontend 396/396, tsc clean; backend 103 passed; ruff and mypy clean.

## The day replayed from its record, and a live arrival seen across the room — 2026-09-24

- **«Reluarea zilei»** (`frontend/src/day_replay.js`, `replay_player.js`): the newest finished run played back from its recorded events only, time-compressed, with quiet stretches named and sped up; labelled at every instant (letterbox, grey-violet grade, «RELUARE» chip, «ATUNCI» clock, violet tags); play, pause, scrub by stage, 1×/4×/16×, Esc; live wins within 6 s; hidden when no run has finished. Verified against an independent reducer on two real runs: 0 differences in 889 checks.
- **A live arrival seen across the room** (`frontend/src/hq_arrivals.js`): the employee's tag for 4 s and widening rings on a live WORKING; the stage's rooms lit on `runbook.stage_started`; never for a replayed event, never under reduced motion.
- **Not read is not empty**: a failed read says «registrul nu a putut fi citit» (and the like), never «nicio rulare în registru».
- **Desk targets** of 55×62 px at 1920 (were 13×12); the façade card sits below the sign.
- **The real last task per employee** from the backend (`app.services.last_task_per_agent`, one grouped query over the new index of migration `0046_agent_run_last_task`), in the snapshot as `last_tasks`.
- **A premium Journal**: the drawers' glass, the newest episode as a poster cover, the empty thread panel folded away; the film toast uses the brightest real frame.
- Tests: frontend 383/383, tsc clean; backend 71 passed across the touched files; ruff and mypy clean.

## The building's truth is legible — 2026-09-24

- **Readouts on every face** (`frontend/src/hq_readouts.js`, `scene_readout.js`): a glass card on hover and keyboard focus for the eight bound walls and every occupied desk's monitor, from the same facts store (nothing fetched), placed in the free room and never over its face, announced once through a polite live region; Enter or a click opens the wall's room.
- **The keyboard reaches the building**: the arrows walk the employees and then the walls, with a ring drawn in the world.
- **A glint when a face's value changes live** (once, 1.4 s; never for a first value, never under reduced motion).
- **The idle building says what is true now**: the façade's next run or «programarea zilnică este oprită», never a countdown; the name tag's «ultima sarcină: …» from the register.
- **The render bay shows the brightest real frame** of the newest film (five key frames sampled once per film, no filter).
- **The slate folds to one line** instead of covering the kerb.
- **Backend** (`backend/app/runbook/services.py`): a legacy run's publish stage counts its publication (`tests/test_runbook_publish_count.py`), so the run summary no longer says no film was published for a run that published one.
- Honesty fixes by the judge: no «programarea zilnică este oprită» between two stages of a live run; a closed inspector no longer leaves its ring; the canvas label names the screens.
- Tests: frontend 347/347, tsc clean; runbook tests 88 passed; ruff and mypy clean.

## The live headquarters follows a real clear day — 2026-09-24

- **A golden hour instead of a power cut** (`backend/app/office/scene_params.py`): the key on the sun's side carries the low sun from +10° to the twilight and warms toward amber; the building darkens in order through the evening (83.8 → 80.6 → 73.5 → 66.6 → 62.1 → 47.6).
- **The front ground on the noon's budget**: the street's fill has its own measured curve, the facade light its own factor (`unreal.py` role `light:facade`); the fills are warmed by hue with their measured built colours (`FILL_BUILT_SRGB8`, read over Remote Control) and are as built again by −1°.
- **Morning is not evening**: a cooler, bluer dawn sky and key, fewer lit windows at dawn.
- **The night sky carries the city's glow** instead of a black void.
- **The weather's look is held** (`WEATHER_LOOK = False`): the deck and rain rules are written and tested but not shipped until the sky atlas has grey deck cells; the road still follows the real rain as before.
- Noon unchanged; 19:19 pixel-identical to the committed code (6.8 against the reference). Tests: 155 passed across the scene, environment bridge, routing, env report and Unreal bridge files; ruff and mypy clean.

## The building's screens tell the truth, and the frame is finished — 2026-09-24

- **Real data inside the world** (`frontend/src/hq_screens.js`, `hq_world.js`): desk monitors by each employee's runtime state, room lights by who works there, the render bay's newest real film frame, the Treasury ticker (VR$ balance, today's spend against the budget), the façade sign with the day's run, the fact-check board, the cork board's proposed topics, the writers' screen, the publication radar, today's tokens; «—» where the page holds no value. Pure rules with tests; each face cached and redrawn only when its value changes.
- **The roof under open sky**: a 48 px sky row above the world (`game_frame.js frameFloor`); the stream laid in whole (contain).
- **The dock hangs in the sky row**, off the zebra crossing; **the keyboard order follows the eye** (register, render, side drawer); **the Journal opens on the episodes**.
- **A real readout in the right drawer's empty glass** on tall screens (`frontend/src/side_readout.js`).
- **The first visit's freeze** fell from about 220 ms to about 75 ms (the workspace painted once, invisibly, under the title).
- Honesty fixes: the publication radar says SIMULAT / PROGRAMAT / NECONFIRMAT / EȘUAT instead of the backend's English codes; the register no longer says «a terminat» when an employee errs, and names tasks in Romanian.
- Tests: frontend 317/317 (new `hq_screens`, `side_readout`, `frame_sky_row`), tsc clean, build green.

## The serial made well: a voice per character, one look, its own identity — 2026-09-24

- **One voice per speaker** (`backend/app/media/speaker_voices.py`, `assembler.py`, `factory.py`): a beat's lines become takes in each character's voice (lock, then binding, then the proposal in `config/serial_voice_cast.json`, then the narrator), joined with a 0.3 s breath, captions per take; a broken lock silences the scene instead of borrowing another character's voice.
- **Narration no longer runs ahead of the pictures**: each scene's audio is padded to its shot (every film with real voices, factual ones included).
- **The series look** (`backend/app/media/series_look.py`, `config/serial_series_look.json`): one versioned style block opens every serial shot prompt, written from the beat (room, who faces the viewer, action, camera); style overrides a model adds are stripped; no written text in frame.
- **The serial's identity at publish** (`backend/app/publishing/serial_identity.py`): "<hook> | Inside The Nexus Ep. N", the logline first, the previous episode named; a Publisher answer carrying another film's title is replaced by the studio's own metadata.
- **The honest record**: an episode the Owner approves unread is recorded as his approval, without a Director's review.
- **Brief episode-v5 and review episode-review-v3**: the show's tone, full bibles only for who acts, a hook inside 3 s, a button that calls back, escalating beats, no invented letter contents.
- **The writer's day is cleaner** (`backend/app/story/projection.py`): the run's own stage reports no longer fill the day's story; a letter to the Director names her; years are no longer redacted as card numbers; a resumed episode carries the day it tells.
- Tests: serial files 233 passed, neighbours 139 passed (new `test_serial_voices`, `test_serial_look`, `test_serial_identity`, `test_serial_quality_adversary`); the opt-in two-day rehearsal on a copy passed; ruff and mypy clean.

## The workspace becomes a game frame, and the serial a writers room — 2026-09-24

- **The render is the hero** (`frontend/src/game_frame.js`, `drawers.js`, `office_engine.js`): full-bleed between the masthead and a footer strip; the register (left) and governance, approvals and module status (right) as glass drawers that close by transform to 40px rails with their real counts; the camera re-centres the building in the free room (420 ms glide, a jump under reduced motion); the page's zoom and pan act on the stream's video; the canvas paints nothing under a stream but keeps the hit boxes.
- **No hitch at sign-in**: the engine is built parked and prewarmed under the title (plates decoded, vehicle tints, one GPU read-back).
- **The scene speaks Romanian** (ledger.js labels on the canvas: «RANDARE / ÎN LUCRU», «SARCINĂ REUȘITĂ: …»); a replayed event moves the scene but no longer speaks.
- **The street follows the real city** (`hq_events.js streetRule`, `hq_traffic.js`, `hq_pedestrians.js`): hour, weekday, Romanian holidays and weather set its density; it stops when the data is lost; the UFO, fireworks and other invented events are removed.
- **The serial as a writers room** (`frontend/src/serial_room.js`, `serial_room.css`): slate, beat board, script page with speakers and directions, the Director's six-score rubric and computed checks, «Scenariul de mâine», what approval does next; `serial_next` on the run cards.
- **The Media player plays on the real server**: `media-src 'self' blob:` in the CSP (`backend/app/main.py`).
- Figures in the remaining dialogs in Romanian notation (`numbers.js`).
- Tests: frontend 285/285 (new `game_frame`, `game_frame_css`, `hq_street`, `scene_words`, `serial_room`), tsc clean, `tests/test_foundation.py` 26 passed.

## The headquarters has a real day, and the live sky follows the real sun — 2026-09-24

- **A real noon for the page's renderer** (`art-source/blender/hq/hq_day.py`, `build_hq.py --variant day`, `export_plates.py --variants day`): the city's windows off, daylight facade colours, the sun where the real one stands at 12:00, lamps and LED lines dark, a pale haze, the offices lit as by day. The nine night plates and the anchor manifest are byte-identical.
- **The real-sky Unreal level streams** (build 3): `look_hq_live.py` moves every plain, non-glowing city slot onto `M_HQ_CityDay`, which ends the white texture-less slots that failed builds 1 and 2; `tests/test_city_emissive.py` +1. Gates: build frame 6.4, p95 15.19 ms, evening −2.5° 6.8, the clock right at every instant.
- **A moving light is followed, not frozen** (`backend/app/office/unreal.py` `EnvironmentPass._eased`): a target that moves during an ease re-aims it instead of restarting it; `tests/test_office_environment_bridge.py` +2. Takes effect when the studio restarts.
- The rejected environment reports are ignored (`.gitignore`).

## The serial in one click: today's episode and tomorrow's script — 2026-09-24

- **The serial resumes instead of skipping** (`backend/app/story/serial_stage.py`): an approved episode without a storyboard is storyboarded, an unread draft is read, a draft waiting for the Owner is named; his approve button storyboards the episode at once (database rows only, no vendor).
- **The missing days are closed and the newest real day is told** (up to 7 days back), with the day named in the stage's reason.
- **The writer gets the day's story, not its tail**: 8-15 events chosen by narrative weight, English story keys, model names redacted, and a privacy leak closed (an answered letter's subject no longer reaches the public projection).
- **Showrunner brief v3** (`episode-v3`): structured lines `{speaker, text, direction}` so no label is ever read aloud, 2-4 speaking characters from those who act in the cited events, the hook → situation → turn → payoff → button structure, locations from the real rooms, the characters' voice fields; new `backend/app/story/lines.py` and `locations.py`.
- **The Director's review v2**: the cited events in her facts, a six-point rubric, computed checks for language, event concentration, words per beat and structure.
- **Tomorrow's script in the same click**: the new stage `serial_next` after the day's log; `next_episode` planned in canon and judged by the next writer. `39_DAILY_AUTONOMOUS_RUNBOOK` §7 updated and re-hashed.
- **The publication metadata guard** from 2026-09-19 finished: a refused title is asked again, and a gate-refused row no longer keeps a film out of every later run.
- Tests: 355 pass across the serial, story, runbook, publishing and whole-day files; new `tests/test_serial_one_click_adversary.py` (13) and `tests/test_publication_metadata_per_film.py`. ruff and mypy (193 files) clean.

## The page amazes a first-time visitor, wave 1 — 2026-09-24

- **Every live claim is true**: the live readout follows the real stream state, the fps names what it measures (Unreal's own statistics or the page's renderer), the «Acum» pulse goes quiet after an hour with nothing new, the event socket reconnects with backoff and replay, and the modules map no longer calls the serial or financing unimplemented (`frontend/src/live_claims.js`, new).
- **The canvas follows the real sun and weather**; the «always dusk» mode is removed.
- **A title screen and an entry into the building**: the headquarters as key art lit by the real hour, pointer parallax, the display face Oxanium (OFL, self-hosted), and a 700 ms push into the building on a real sign-in (`title_screen.js`, `title_frame.js`, `key_light.js`, new).
- **A HUD bound to real fields**: the day tracker on the slate, the pipeline in the daily run, the budget ring in the treasury (`hud_charts.js`, new), and **moments** from live events only: the chapter card for an episode, the film toast with its real poster frame (`moments.js`, `film_poster.js`, new).
- **Delivery**: hashed assets are immutable, the page revalidates, the API is never cached.
- The judge removed a simulated employee reaction to random sky events, made the office canvas honour reduced motion, named every day in the register, and formatted money (`numbers.js`, new).
- Frontend tests 236 pass (165 before); tests/test_foundation.py and tests/test_delivery_cache.py pass.

## One icon family, and the two readouts beside the render — 2026-09-23

Seven icons from seven places became one family: one 24×24 grid, one stroke, round caps and
joins, `stroke: currentColor`, no fill but a dot. Twenty-two icons, including every close button,
the refresh, the camera's plus and minus and the play control, which had been typographic
characters borrowed from the UI font. Two icons that said the wrong thing were replaced: the
daily run was a house and is now a sunrise; distribution was a circle crossed by a diagonal that
read as *forbidden* and is now an upload.

The frame rate beside the render keeps every word and stops being a heading: `--fs-micro` in the
chrome's muted ink, still mono and tabular, so **Live** leads and the figure follows. The heading
band above the render, empty since the live badge was let into the glass, was tightened from 83px
to 65px — the height the page's other section headings have always had — rather than refilled
with a readout the glass already carries.

Presentation only: no word, no behaviour, no data flow, no API call, no gate and no test contract
changed. 164 frontend tests pass unchanged; `tsc` clean; every view photographed at 1920×1080 and
1280×800 with 0 missing fixtures and 0 console errors, and every icon read at 4× and 8×.

## The interface is finished to the level he asked for — 2026-09-22/23

*Polishing pass, the same day:* the «Live window» popup on the new palette (with a test that
catches a token drift), a section rail for the research dialog, a sign-in screen standing in the
product's own world with the Settings button hidden until the key is accepted, one instrument
family let into the render's bezel, selection and hover marks drawn at a constant size on screen, a
scene that answers the keyboard, and the renderer's interface colours taken from the page's tokens
(`frontend/src/hq_palette.js`, new). Seven measured defects fixed, including a key light that had
never reached the screen and four invisible placeholders. 146 frontend tests pass; 2 853 contrast
pairs read from the real pixels, none below threshold.

Presentation only: no user-facing string, no Romanian wording, no data flow, no API call and no
gate changed. Three directions were built on the real code and photographed, a judge chose the
cinematic dark one with named grafts from the other two, and three parts built it before an
adversary measured it. `CURRENT_STATUS.md` («The interface, brought to a finish») has the figures.

- **One dark ground; the 3D render is the only heavy object on the page.** New token block in
  `frontend/src/style.css`: six grounds, three hairlines, four inks, a rationed gold, the rhythm
  and metric tokens (`--s1..--s9`, `--topbar-h`, `--hit`, `--measure`, `--rail-w`) and an eight-step
  type scale. Zero colour and zero font-size literals below the block, in `style.css`,
  `office_scene.css` and `settings.css`.
- **The page composes at every width**: the wide spread above 1560 px and its two-column form
  between 1051 and 1559 px; no horizontal overflow at 1024–2560.
- **The ledger** gains a time rail, kind rails, a one-time arrival highlight and the fold of
  consecutive identical rows (`arrivingIds`, `LEDGER_SETTLE_MS` in `frontend/src/ledger.js`).
- **The dialogs** gain one shell (fixed header, body that scrolls), a section rail for the three
  long ones (`frontend/src/dialog_rail.js`, new), section-head hairlines, figure tiles and a
  storyboard card that no longer cuts a word.
- **The detail**: four distinct button states, one tag system, one shape per empty/loading/error
  state, dialog open and close motion, `prefers-reduced-motion` honoured throughout, a field
  boundary that measures 3.4:1 and a focus ring on every field.
- **Tests**: `frontend/tests/dialog_rail.test.js` (new, 8), `frontend/tests/ledger_fold.test.js`
  (new, 7) and three new cases in `ledger.test.js`: 143 pass, `tsc` clean.
- **A harness to see the interface without the studio**: `<scratchpad>/ui/capture_fixtures.py`
  (254 answers from a copy of the database, secrets blanked, loopback-only) and `shoot.mjs`
  (every view photographed at any width, 0 missing fixtures, 0 console errors).

## After the rehearsal: the narration says what its claims say — 2026-09-19

The rehearsal's stand-in wrote a James Webb telescope script for the Nepal climate-finance topic.
The script cited a SUPPORTED Nepal claim, and it passed the factual gate, the story review and the
Director, because nothing computed compared the words with the claims. Two parts closed two of the
rehearsal's findings, under faked providers. The details and the figures are in `CURRENT_STATUS.md`
(«After the rehearsal — 2026-09-19»).

- **The narration is measured against its claims and its topic.** New module
  `backend/app/factual/grounding.py` (`measure_grounding`, `script_grounding`, `grounding_check`).
  Each cited claim must appear in the voiceover by two of its terms, the voiceover must carry two
  of the topic's terms, and it is refused when more than half of its numbers and names come from
  nowhere. It returns PASSED, REFUSED or NOT_MEASURED with Romanian reasons, and NOT_MEASURED does
  not pass. It refuses in four places:
  - the story review's new blocking check `narration_is_grounded` (REVISE, then REJECT at the last
    exchange);
  - `_director_approves` in `backend/app/runbook/stages.py`;
  - `story_gate`, before the shot descriptions and the render;
  - `gather_facts` in `backend/app/agents/editorial.py`, which also passes the measurement to the
    Director.

  Serial episodes are not measured. Measured before: the rehearsal's script 5ee7e22e was approved
  and published to the simulator. On the 31 real scripts of 2026-09-12, both approved films pass,
  and 4 of the 29 waiting for the Owner are refused.
- **Tests.** New `tests/test_script_grounding.py` (22 after the verify part).
  `tests/test_editorial.py` gains 3 tests, and its `a_film` claim now carries the facts its
  narration states. `tests/test_phase_bc_adversary.py` and `tests/test_search_step.py` now
  narrate what their claims say; both broke the writer's brief and the new check refused them.
- **Spelled-out numbers are numbers.** The verify part found a faithful narration refused for
  saying «six hundred million dollars»; the check now reads whole spelled-out numbers in English
  and Romanian, and ranks from third to tenth. The calibration is unchanged.
- **The panel says what the day made.** New module `frontend/src/day_outcome.js` (`runHeadline`,
  `runClassName`, `stageProducedWord`, `stageClassName`, `firstStop`), with 9 tests in
  `frontend/tests/day_outcome.test.js`.
  - Run cards show the backend's `summary` and each stage's `produced` count.
  - A COMPLETED run that made nothing gets `rb-empty`.
  - The preflight card puts `first_stop` above the list.
  - The ledger's «daily run finished» line carries the summary.

  `frontend/dist` is not rebuilt.
- **Documents.** `50_CONTENT_GATE_MATRIX` gains the row *Narration grounding (Channel A)* and a
  section on what it certifies. It is re-hashed (`a436dab0…` → `6750c35d…`). «Ce are Owner-ul de
  făcut» gains dated lines at steps 2 and 12, without renumbering.
- Not changed: the factual gate, the Director's verdict, the five publishing points and the other
  hard gates. There is no migration, and the head stays `0045_reconciliation`. No provider was
  called, and `data/studio.db` was never opened.
- Still open:
  - whether a real writer repairs a refused script within the exchange budget;
  - what a word count cannot hear (negation, generic words standing in for a claim), which stays
    the Director's;
  - a PARTIAL run's «etapa eșuată»;
  - `frontend/dist`.

## The rehearsal on the Owner's data — 2026-09-18

One whole scheduled day was run on a copy of the Owner's studio, through the real scheduler, worker
and runbook, with every paid vendor faked and every outside connection refused. An independent audit
re-ran it and gave the verdict FIX_FIRST. It found two defects, the limits of the fakes, what only the
Owner can change, and a migration chain that is clean on his data. Four parts fixed what code could
fix; `CURRENT_STATUS.md` («The rehearsal on the Owner's data (2026-09-18)») has the findings and the
figures.

- **A failed stage costs its dependants and nothing else.** `STAGE_PREREQUISITES`
  (`backend/app/runbook/services.py`) states what each stage needs, each edge read from what its
  runner reads, and a stage is BLOCKED only when every prerequisite it lists was lost, with the
  prerequisite and the root fault named. Measured before: a refused statistics token at performance
  intake BLOCKED the nine stages after it. The Owner's stop and a blocked preflight still block
  everything.
- **Safe mode only for a P0.** `SAFE_MODE_STAGES = (media, publish, daily_log)` plus
  `_doubts_the_record` (a database integrity error in any stage), after `21_FAILURE_RECOVERY_PLAYBOOK`.
  Any other HARD fault costs its stage, its dependants and a letter. Measured before: an HTTP 4xx
  from Google was HARD, and a HARD fault anywhere set the autonomy stop.
- **The re-attempt follows only a transient fault that cost a film** (`retryable_outcome(...,
  production_lost=)`, `PRODUCTION_STAGES`). A day whose films went through while another stage failed
  is PARTIAL.
- **The run counts what each stage produced.** Each stage record has `produced` (`PRODUCED_FROM`), and
  the run has `summary` and `stages_productive`, returned by `execute_daily_run` and `list_runs`.
- **A statistics read that cannot be made is «fără date».** `YouTubeAnalyticsProvider` raises
  `MetricsUnavailable` for a transport or authentication failure on the token refresh or the report.
  The class now lives in `providers/youtube_analytics.py` and is re-exported by `analytics.services`.
  `measure_channel_publications` stops asking after an account-level refusal, names the account to
  reconnect, and writes `youtube.token_refresh_failed` or `youtube.analytics_refused` once.
- **The books charge what was bought.** `motion_was_bought` (`bytes` or `paid_but_lost`) in
  `economy/accountant.py`, shared by `record_render_costs` and `record_failed_render_cost`; a refused
  shot teaches no price. Measured before: four ESTIMATED Runway rows, 1.44 USD, for shots never
  generated, with both holds settled against them.
- **Narration on Flash and Turbo at the documented half.** New DOCUMENTED rows `eleven_flash_*` and
  `eleven_turbo_*` at 0.11 USD per 1k characters. `price_row` reads a trailing `*` as a family and
  ranks any Owner price above every documented one. `seed_documented_prices` skips a documented row
  when the Owner has an active '*' price for that unit.
- **Tests fake every paid path.** The `no_network` guard in `tests/conftest.py` also refuses DNS and
  asyncio's `sock_connect`, and records every refusal. `VENDOR_FAKES` / `install_vendor_fakes` is one
  list of eight fakes, shared by the whole-day test and the rehearsal, and it now includes the motion
  chooser and the analytics adapter. New: `tests/test_no_paid_path_escapes.py`, a call-graph scan
  from `execute_daily_run` and `build_stage_runners` that fails on any paid adapter reachable without
  a fake; `tests/test_day_survives_a_stage.py`; and the opt-in `tests/test_rehearsal_on_a_copy.py`,
  which refuses `data/studio.db` and copies whatever it is given again before opening it.
- **The preflight says what will stop tomorrow.** New checks: `youtube_upload_access` (BLOCKING),
  `youtube_statistics_access` (DEGRADING) and `daily_budget_films` (DEGRADING, or INFORMATIONAL for
  the PRODUCTION answer in TEST). New `first_stop` in the result, and a summary that names that check.
  `run_preflight(..., now=)`. The publishing line says it reads the stored state. Three Romanian
  labels were added in `frontend/src/readiness.js`.
- **Documents.** `39_DAILY_AUTONOMOUS_RUNBOOK` gains the stage dependency table, the P0 rule, the
  re-attempt rule, the three checks and what "if available" means at §2. It is re-hashed
  (`f4d26ea2…` → `227e7604…`). Every sentence that said a failed stage costs only itself is corrected
  where it stands with a dated marker. «Ce are Owner-ul de făcut» gains what only the Owner can do,
  in the step it belongs to, without renumbering.
- Not changed: no migration (the head stays `0045_reconciliation`), no provider called, no run queued
  on the live studio, `data/studio.db` never opened. Added by another part while these documents
  were being written: `SCOPES` asks for `yt-analytics.readonly` as well, so a reconnect can grant
  statistics (`test_the_consent_asks_for_the_statistics_the_day_reads`). Still open: the uploader writes no refusal event; the hold takes the dearest voice
  price; the panel does not show the new run fields; and nothing has met a real vendor.

## Readiness for the first day, closed — 2026-09-18

The three risks the readiness section had left open, named with a file and a line each by an
adversarial reading of the Owner's own checklist: the employee who can see never arriving, a cast the
studio guessed steering a paid render, and a SUPERVISED day that stops without saying so.

- **The preference is applied where the studio learns about models.** `prefer_capable_models` gains a
  second call site in `sync_provider_models` (`backend/app/agents/services.py`), immediately after
  `apply_llm_allocation` and inside its own try/except: `record_declared` a few lines above is the only
  place in the studio that ever writes `vision` on a model, so the sync is the first moment a seeing
  model exists as a row, and the allocation must run first because it rewrites the slots of any
  employee who does not carry `agent.model_assigned` — which a preferred move deliberately does not
  write. Measured before the change: the only caller was `seed_initial_workforce`, i.e.
  `scripts/bootstrap.py`, step 1 of his morning, hours before step 9.
- **The studio's own allocation file is no longer mistaken for the Owner's hand.** The guard was the
  bare existence of `agent.model_assigned`, which `apply_llm_allocation` writes too, so the first sync
  of any studio killed the preference for a choice he never made. `_owner_chose_models` judges the last
  event that moved an employee's models — none means the seed hired her, `agent.model_preferred` means
  this function moved her last, `agent.model_assigned` is the file's only when her three slots resolve
  (through `resolve_model`) to exactly what `config/workforce_seed.json` names for her role — and reads
  a role the file does not name, and a file it cannot read, as his.
- **`RoleView.preferred_capabilities`** (`backend/app/agents/schemas.py`), filled in `list_roles` from
  the PREFERRED rows: two fields and never one list, because a preference listed as a requirement
  would tell the Owner his Video Editor cannot work without a seeing model, and she works without one.
  Additive, defaulting to `[]`.
- **A cast is what the film states; a guess is recorded and never acted on.** `_characters_named_in`
  gains a `given_names` flag rather than a second regex, and `_scene_cast`
  (`backend/app/media/services.py`) returns `(stated, guessed)`: stated is the writer's `characters`
  list read by given name plus whole canonical names in the requested picture, and only that reaches
  `character_ids_json`, which the assembler, the factory's `referenceImages` and the locked-look
  refusal all read. A bare given name in the prose — measured to cast Elena Fact-Checker from
  "Hurricane Elena made landfall" — is recorded per scene on `media.storyboard_created` as
  `guessed_cast`, read back by `storyboard_cast_record`, and never written to a scene. `cast_note` now
  distinguishes `NO_CAST_BY_DESIGN` from `NO_CAST_ONLY_GUESSED`.
- **The picture gate looks at a guess and can never fail a film for one.** `evaluate_pictures`
  (`backend/app/media/picture_qc.py`) asks about guessed names in the same single look, records them
  `status: "OBSERVED"` with `basis: "guessed"`, counts them in `characters_observed` and never in
  `characters_measured`, and attaches a stored portrait for stated characters only.
  `character_drift_qc` now reports, in order, the guessed-names line, the board's own note, "no
  character in this film could be compared with the bible", and only then the old sentence "no scene
  in this film lists a character" — which now means only what it says. This closes the readiness
  phase's open line about `picture_qc` reading the storyboard's cast note.
- **An estimate says what it could not price.** `estimate_film_cost_micros`
  (`backend/app/economy/budget.py`) returns `unpriced`, `caveat` and `complete` beside the figure, with
  `unpriced_caveat` the single wording («estimare incompletă: narația nu are preț stocat și este
  numărată ca zero») and `UNPRICED_CAVEAT_PREFIX` its first words. The media stage carries that one
  sentence to all three places the Owner can meet the figure — his question's `evidence`, the hold's
  note and the Accountant's letter — and `_cost_caveat` (accountant) and `approvalCaveat`
  (`frontend/src/readiness.js`) read it back by that prefix, yielding "" when it is absent. The
  caveat is raised only where there was something to price.
- **The letter about what is waiting leaves in the minute the question is born.**
  `waiting_approvals_letter` is called from `_media` (`backend/app/runbook/stages.py`) as soon as the
  refusal is recorded, guarded by `refusal.get("approval_id")` so a MANUAL refusal writes nothing, and
  `reconcile_day`'s call is kept: `_letter_once_a_day`'s business-date idempotency makes two callers
  safe, so the day writes exactly one letter whichever end of it notices first. Measured before the
  change: a question raised at 05:30 reached him at the run's end at best, and not at all when the run
  stopped before `_post_run` — after which it expired and the film was never made.
- **The panel says INFORMATIV and names every check it can.** New module
  `frontend/src/readiness.js` holds `RUNBOOK_CHECK_LABELS` (moved out of `main.js`, with Romanian
  lines for the five checks this phase added and for `autonomy_mode`), `checkVerdictWord`,
  `checkClassName` and `approvalCaveat`; `main.js` imports them, and `style.css` gains
  `.rb-informational` (neutral) and `.approval-caveat` (amber). A severity the page has never heard of
  is printed as it came, with no colour class, rather than rounded into DEGRADES. The module is
  separate because `main.js` touches the document on import and cannot be loaded by `node --test`.
  `youtube_channel_binding` still has no label and still shows by its code name, as before this phase.
- Measured, each figure by the part that took it and **no whole-suite run made by any of them**:
  `tests/test_seeing_employee.py` 5 (new, red first at 1/4) inside 60 with the agents, multi-LLM and
  provider-discovery suites, plus 54 and 79 across the picture-QC, workflow, factual, truthfulness,
  readiness and runbook suites; `tests/test_phase5_media.py` 30, `tests/test_picture_qc.py` 17 and
  `tests/test_character_references.py` 23 — 70 together — with 72 and 91 across the seeing-employee,
  editorial-quality, daily-run, serial-pipeline, readiness-adversary and production-policy suites;
  `tests/test_phase11_economy.py` 36, `tests/test_daily_run_stages.py` 34, `tests/test_approvals.py`
  20 and `tests/test_books_and_history.py` 17, with 234 across those and six neighbours, and
  `node --test tests/readiness.test.js` 8 (new) inside `node --test tests/*.test.js` 110 with
  `npm run check --prefix frontend` clean; `scripts/check_docs.py` and `tests/test_documentation.py`
  for the documents. No migration was taken: the head stays `0045_reconciliation` and **0046 is still
  free**. No provider was called, nothing was rendered, no run was queued, no credit was spent and
  `data/studio.db` was not opened.
- **Documents.** `CURRENT_STATUS.md` gains *Closed the same day — 2026-09-18* inside the readiness
  section and corrects in place, each with a dated marker, the three risks that section recorded as
  open plus the four sentences this work made untrue. «Ce are Owner-ul de făcut» is corrected in four
  lines and rewritten in none: step 3 (INFORMATIV in neutral grey, the new checks named, visible only
  after step 2's build), step 9 (**nothing to assign by hand after admitting a seeing model, and
  neither a second seed run nor a restart**), step 10 (a locked character refuses a film only on a
  cast the film states) and step 12 (the letter leaves when the question is born; an incomplete figure
  says so beside itself). `../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` §11 is edited a second time
  to say the letter leaves from both ends of the day, with its `sha256` re-recorded in
  `DOCUMENTATION_INDEX.json` and a decision-log entry as the reason;
  `../architecture/31_GOVERNANCE_APPROVAL_POLICY.md`, `../architecture/50_CONTENT_GATE_MATRIX.md` and
  `../architecture/24_VISUAL_CONTINUITY_ASSET_SYSTEM.md` were read against the cast change and left
  untouched, because none of them describes how a scene's cast is read.
- Still open and named: nothing here has met a real vendor or a real model; `frontend/dist` is still
  not rebuilt and no server or browser has rendered the INFORMATIV card or the amber caveat; the
  guessed cast is on the ledger event and not in `get_storyboard`'s answer; the caveat lives in the
  request's `evidence` text and not in a column; `estimate_film_cost_micros` still does not price the
  stills at all; `youtube_channel_binding` has no label; `waiting_approvals_letter` is called from
  `_media` without a try/except, matching the `budget_refusal_letter` call below it; and one defect
  in the tree belongs to nobody in this closure and is reported rather than repaired,
  `mypy backend/app/media/picture_qc.py` line 285 (`union-attr` on `board.id`, a narrowing gap and
  not a runtime fault). A second was closed in the tree while these documents were being written:
  `tests/test_phase_dg_closure_adversary.py::test_only_the_owners_command_module_reaches_an_approval_row`
  had begun to fail because its whole-tree scan for the string "ApprovalRequest" found a docstring
  line the Accountant gained in this phase, and the scan now walks the parsed module — a class
  definition, a name, an attribute, an import — instead of characters (12 passed afterwards).

## Readiness for the first day — 2026-09-18

What the studio still needs from the Owner before it is left alone on Monday morning, said by the
preflight instead of by a document; somebody who can be hired to look at the pictures, and a factual
film that records who is in it; and books that tell him what is waiting and learn what things really
cost.

- **Five preflight checks for the things only the Owner can supply.** `backend/app/runbook/preflight.py`
  gains `spending_budget` (no budget is active at all, so the reservation holds a film's money against
  no limit), `model_prices` (the models the day's employees think with, priced on both token units or
  not at all — the reason 391 `agent_run` rows carry `cost_vr` NULL), `vision_capability` (nobody's
  model declares vision, so the picture and character gates stand down on every film),
  `character_references` (which characters hold no readable reference: an asset id whose row exists and
  whose file is still on disk) and `serial_channel` (the serial's slot bound, and the Director's leave
  to approve episodes). Each reads the database only — no vendor is asked, no key is used, no job is
  queued. None of the five is BLOCKING, `serial_channel` is INFORMATIONAL always and
  `character_references` degrades only for a character whose look is *locked*, because a check must not
  refuse the day for something the Owner chose; a test holds that a studio with nothing configured
  still reports exactly `stop_autonomy` and `llm_provider` as blocking.
- **`APPROVAL_EXPIRES_AFTER_HOURS` is a setting.** `Settings.approval_expires_after_hours`
  (`STUDIO_APPROVAL_EXPIRES_AFTER_HOURS`, default 24, bounded one hour to one week) replaces the module
  constant in `backend/app/services.py`, read through a local import with a documented fallback of 24;
  the three things it decides — how long an unanswered question stands, how long a refusal stops the
  studio asking again, how long a yes can be spent — are named where it is declared. Behaviour
  unchanged.
- **A role may prefer a capability, and the Video Editor prefers vision.** `ROLE_PREFERENCES` and
  `seed_role_preferences` write the PREFERRED row; `prefer_capable_models` moves that employee onto a
  model that sees at the next start-up if the Owner has admitted one, writing `agent.model_preferred`
  and never `agent.model_assigned`, and never touching an employee whose models he saved himself.
  PREFERRED is not a gate and never becomes one. `Capability(name="vision")` is seeded as a row and
  attached to no proposed model: `SEEDED_MODEL_CAPABILITIES` now names the four text capabilities
  explicitly, because nothing in the seed contacts a vendor and a guess that a model can see would make
  the picture gate certify a look nobody took.
- **A factual scene records its cast.** `generate_storyboard_from_script` reads the scriptwriter's
  character list first, then the names in the requested picture (through one `_scene_visual`), never
  the narration, and never a first name followed by another capitalised word. A film that shows nobody
  records an empty cast and says once, in `media.storyboard_created` (`scenes_with_cast`, `cast_note`),
  that the absence is deliberate — readable through `app.media.services.storyboard_cast_note` and
  returned by `get_storyboard` as `cast_note`. Consequence: the reference sets reach the factual film,
  and a locked character with no reference now refuses a factual scene too.
- **The Accountant writes about what is waiting.** `waiting_approvals_letter` (new in
  `backend/app/economy/accountant.py`): one letter per business date, decided behind the write lock,
  naming each standing question by what it is (`APPROVAL_ACTION_LABELS`) with the request's own
  `cost_label` — «necunoscut» where nothing could compute one, never zero — and the hour the oldest
  expires; nothing is written when nothing is waiting. `reconcile_day` calls it as its first act,
  before any question is put to a model.
- **Migration `0045_reconciliation`: an estimate is replaced by what the vendor actually billed.**
  `provider_reconciliation` plus `reconciled_at` and `reconciled_by_id` on `provider_cost_record`, both
  NULL, so every existing row keeps its reading. `PUT /api/v1/economy/reconciliations` is Owner-only,
  idempotent by command id and versioned with a **required** `expected_version`, because replacing an
  invoice moves money; `GET /api/v1/economy/reconciliations` lists them. An invoice covers a period or
  one named thing (today a render, by `render_job_id`), writes the BILLED row carrying the hour of the
  last spend it pays for, stamps `reconciled_at` on the estimates it covers — which `spend_since` then
  skips — and keeps every row it could not replace on the row as data with the reason. A correction is
  a new version that reverses the previous posting and re-adopts its estimates; nothing is edited and
  nothing is deleted. The head pin in `backend/app/main.py` moves to `0045_reconciliation`; the chain
  is 0039 → 0040 → 0043 → 0044 → 0045 and **0046 is free**, because the media part needed no column.
- Measured, each figure by the part that took it and **no whole-suite run made by any of them**:
  `tests/test_readiness.py` 11 (new) and `tests/test_phase10_runbook.py` 46, with 18, 144, 70 and 5
  across the approval, daily-run, autonomy and whole-day suites; 18 + 28 + 16 + 22 + 10 across the
  workforce and storyboard part's five files with 359 in all over nineteen neighbours;
  `tests/test_reconciliation.py` 11 (new) with 17, 34, 18, 3, 188 and 5 across the economy and
  application-start suites; `scripts/check_docs.py` and `tests/test_documentation.py` for the
  documents. The 1194 passed / 1 skipped in `PROJECT_STATE.json` remains the Phase D/G closure
  verifier's measurement of 2026-09-18 and is older than the tree. No provider was called, nothing was
  rendered, no run was queued and no credit was spent.
- **Documents.** `CURRENT_STATUS.md` gains *Readiness for the first day (2026-09-18)* and corrects in
  place the two sentences this phase made untrue. **«Ce are Owner-ul de făcut» is rewritten as a
  numbered checklist for the morning of the first real day** — migrate, build, read the preflight,
  budgets, prices, token ceiling, sites and search engine, channels and their policy, a model that can
  see, the character reference sets, the fallback vendors, the autonomy mode, then the clock, and the
  invoice reconciliation after the first real spend — keeping every line it had, each now saying what
  to do, with what command or screen, and what happens if he skips it; it moves under the readiness
  section and leaves a dated pointer where it stood.
  `../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` names the five new checks and the waiting-approvals
  letter, with its `sha256` re-recorded in `DOCUMENTATION_INDEX.json` and a decision-log entry as the
  reason. `../architecture/15_SECURITY_COSTS_OBSERVABILITY.md` was read against the new books and
  deliberately left unedited: nothing in it is false, and what it does not yet say is recorded in the
  decision log instead of spending an index hash.
- Still open and named: nothing here has met a real vendor, a real model or a real invoice; `model_prices`
  covers the LLM token sides only; the Video Editor's preference reaches a running studio only at the
  next seed and is invisible in the interface; `picture_qc` does not yet read the storyboard's cast
  note; an employee's token cost never passes through `provider_cost_record`, so no invoice can
  reconcile it; the waiting-approvals letter leaves only at the day's close; and nothing renders the
  preflight's INFORMATIONAL severity, the five new checks have no labels, neither reconciliation screen
  exists and `frontend/dist` is still not rebuilt.

## Quality and governance, closed — 2026-09-18

The three things the Phase D/G section left open, closed the same day: the Owner can answer an
approval, his own render and quality control read a film the way the day reads it, and there is a page
for the mode, the approvals and the reference sets.

- **An approval is about one film, and he can answer it.** Migration `0044_approval_answered` adds
  `subject`, `note`, `decided_at` and `consumed_at` to `owner_approval_request` with an index on
  (`action`, `subject`, `result`); the head pin in `backend/app/main.py` moves to
  `0044_approval_answered` and the chain is 0039 → 0040 → 0043 → 0044. A standing request is keyed by
  the action **and** the thing it is about, which closes the defect the adversarial pass named: the
  day's second, dearer film used to reuse the first film's row.
- **`GET /api/v1/owner/approvals`** lists what waits — the action in Romanian (`APPROVAL_ACTION_LABELS`),
  the tier, the requester, the evidence, the proposed diff, the expiry and the cost, with `cost_label`
  «necunoscut» where nothing could compute one. **`POST /api/v1/owner/approvals/decision`**
  (`ApprovalDecisionCommand`) is the answer: Owner-only, versioned, idempotent by command id, behind the
  same write lock as his other commands, one `governance.approval_decided` event with the previous
  result and the new, 409 on a request already answered or expired, 404 on one that never existed.
- **The answer is spent inside `may_act`**, in the SUPERVISED T3 branch, after the stop, T4 and safe
  mode — so it converts "he must be asked" into "allowed, once" and never a refusal into a pass. Spent
  once, before the act: `consumed_at` plus a `governance.approval_consumed` event. A stop, an incident
  or a lowered mode leaves the yes unspent and still his; a channel policy version that moved after he
  answered retracts it and a fresh request naming the new policy is raised.
- **The stage wrapper asks the mode without asking the Owner** (`ask_owner=False` on `may_act` and
  `mode_refusal`), so the question is raised by the caller that can name the film. A refused film comes
  back COMPLETED with `refused_by_owner`; a film still waiting comes back SKIPPED with `awaiting_owner`;
  both carry the approval id. `owner_approval_request` joins `maintenance.HISTORY_TABLES` before
  `command_record`.
- **The Owner's own buttons read a film the way the day reads it.** Both `evaluate_media_qc` call sites
  in `backend/app/media/router.py` now pass `registry` and `settings.ffmpeg_path`, and `start_render`
  passes the plan's `image_chain` (suppressed only for an injected adapter) and `reference_for_scene`
  (always). `ReferenceRequired` is answered 422 naming the character instead of 404 "storyboard not
  found".
- **Runway can be handed a reference.** `RunwayImageAdapter` sends `referenceImages` on the documented
  `text_to_image` task as an inline data URI, refusing a path, an id or bytes that are not PNG/JPEG/WebP
  before the task is submitted, and counting `reference_images` in the attempt's raw response.
  `ACCEPTS_REFERENCE_IMAGE` True, `REFERENCE_IMAGE_VERIFIED` False until an Owner-approved live run. The
  contract refusal for a model that *requires* references now fires only when none was given.
- **A governance panel.** `frontend/src/governance.js` (new) and `frontend/tests/governance.test.js`
  (new, 14 tests): the autonomy mode with `MODE_MEMORY`'s sentence and the other two modes as versioned
  commands, a promotion refused by the page only where the snapshot can see it is impossible, the
  approvals list polled at most every thirty seconds and silenced after a 404, «Aprobă»/«Refuză», and
  the Character Bible's reference slots drawn as chips behind a two-press button that states its cost.
  `frontend/dist` was deliberately not rebuilt.
- Measured, each figure by the part that took it: 231 Python tests across the governance part's files
  and their neighbours (`tests/test_approvals.py` 18, new), 186 across the media part's four files and
  its regression set, `npm test --prefix frontend` 102 with `npm run check` clean, and
  `scripts/check_docs.py` plus `tests/test_documentation.py` for the documents. **No whole-suite run has
  been made since**, so the 1152/1 recorded on 2026-09-18 remains the last whole-tree measurement and is
  now older than the tree. No provider was called, nothing was rendered, no run was queued and no credit
  was spent.
- **Documents.** `CURRENT_STATUS.md` gains the closure block and corrects, in place and dated, every
  sentence the closure made untrue — above all that a SUPERVISED studio "records the question and never
  hears the answer" and that the Owner's own render does not see what the day sees.
  `../architecture/31_GOVERNANCE_APPROVAL_POLICY.md` gains *Answering an approval, and spending it* and
  `../architecture/51_AUTONOMY_MODE_SEMANTICS.md` has its Supervised **Not built:** paragraph corrected;
  both hashes are re-recorded in `DOCUMENTATION_INDEX.json` with a decision-log entry as the reason.
  `../architecture/50_CONTENT_GATE_MATRIX.md` was read and left unchanged.
- Still open and named: no approval has ever been answered by a real Owner against a real database; the
  Owner is not told that something is waiting; an approval cannot be withdrawn;
  `APPROVAL_EXPIRES_AFTER_HOURS = 24` now decides three things as a module constant; neither adapter's
  reference path has ever been accepted by a vendor and the size of an inline reference is not checked;
  the panel is invisible until `npm run build --prefix frontend`.

## Quality and governance — 2026-09-18

Phases D and G of running unattended, built in three parts and wired into the day: what the studio
certifies about a film before the Director sees it, the reference pictures that make a character
recognisable, and who decides the studio may act at all.

- **Quality control looks at the pictures.** `backend/app/media/picture_qc.py` (new) cuts every
  scene's middle frame from the finished film and asks, in one call for the whole film, an employee
  whose provider declares its model can see: is this a picture at all, and does it show what the
  scene's visual prompt and narration asked for — carrying in the same call the storyboard's cast
  with the Character Bible's canonical face, hair, outfit, props, role symbols, palette and, where a
  slot holds one, the stored portrait. A refusal fails the film in every environment, beside the
  degenerate-still and placeholder-footage checks. `character_drift_qc` no longer says
  NOT_IMPLEMENTED for a studio that has characters. `backend/app/agents/vision.py` (new) finds the
  employee, asking Video Editor, Director, Quality Assurance in that order and reading only the
  primary model. With no registry, no vision-capable model, no frame cut, the day's token ceiling
  reached or a model that never reached the JSON, the check is NOT_APPLICABLE with the reason,
  `passed` is None, no failure is added and the film's verdict is unchanged.
- **Reference pictures for the characters.** `POST /media/characters/{id}/reference-set` fills the
  five bible slots with real files — one prompt per slot from the bible alone, each a `MediaAsset`
  with its own SHA-256 and its bytes under `backend/storage/character_references/{character}/` — and
  a slot the vendor refused keeps what it held and is named in the answer. It is the Owner's act:
  it refuses under STOP AUTONOMY before the first request, holds the money for the whole set through
  `reserve_spend`, reports `usd: None` rather than zero when the model has no price, and no stage of
  the day names it (a test asserts that). `image_reference_for_scene` hands the render the reference
  the scene's cast has; a character whose look is locked and has no readable reference raises
  `ReferenceRequired` and refuses the film rather than inventing a face.
- **A second vendor when the first refuses.** `approved_alternatives` reads the Owner's
  `approved_fallbacks` from the production hierarchy, narrowed for a visually locked character to the
  technology an APPROVED identity change named; `image_adapter_chain` and `still_from_chain` try at
  most one alternative per purpose per scene (`MAX_FALLBACKS_PER_PURPOSE`), record the connection,
  the model, whether a reference was sent and what the attempt was worth at the recorded price, and
  re-raise the last refusal with the attempts attached. In TEST the chain is ordered cheapest-first.
  The OpenAI image adapter posts a reference to the documented multipart `/v1/images/edits` endpoint
  (`ACCEPTS_REFERENCE_IMAGE` True, `REFERENCE_IMAGE_VERIFIED` False until an Owner-approved run has
  drawn one).
- **The autonomy mode is a column, a command and a gate.** Migration `0043_autonomy_mode`
  (`owner_policy.autonomy_mode`, `owner_approval_request`) records AUTONOMOUS_CEO, which is the
  honest reading of what the code has been doing. `change_autonomy_mode` (`POST
  /api/v1/owner/autonomy-mode`) is versioned, idempotent and refuses a promotion under STOP or in
  safe mode, naming 51's acceptance criteria and burn-in as the two things it cannot check.
  `ACTION_RISK_TIERS` transcribes 31's tiers and 32's tool classes; `may_act` reads 31's authority
  hierarchy top down — stop, T4, safe mode, mode — refuses an unclassified action
  `BLOCKED_UNCLASSIFIED`, and under SUPERVISED writes an `owner_approval_request` for a T3 external
  write instead of performing it.
- **The day reads all three.** `runbook/stages.py` gains `STAGE_ACTIONS` (every stage to one action
  and one tier of 31) and `mode_refusal`, asked before each stage, again per film before the money is
  held (T3 above `paid_generation_approval_threshold_usd`, new in `config.py`, five dollars) and
  again per film before the upload, which is T3 at every visibility; a stage above the mode is
  SKIPPED with the Owner's reason and the day comes out PARTIAL. Quality control now passes the
  registry and `settings.ffmpeg_path` to `evaluate_media_qc`; the media stage passes the plan's
  `image_chain` and `reference_for_scene` into `assembler.assemble_video_job`, which draws each still
  through the chain and records the attempts; `economy/accountant.py` prices a still by the vendor
  that drew *that scene*. `runbook/preflight.py` gains an `INFORMATIONAL` severity and an
  `autonomy_mode` line, with the verdict computed over the other two severities so it can never fail
  a run.
- **A whole day under each mode.** `tests/test_autonomous_day_end_to_end.py` gains three tests:
  MANUAL fetches no page, buys no shot, uploads nothing and asks nothing; SUPERVISED films the day
  and writes exactly one `owner_approval_request` for the upload; AUTONOMOUS_CEO publishes private
  under the channel's policy with no request raised. Every vendor faked, the socket guard active.
- **Documents.** `CURRENT_STATUS.md` gains the section above and three items in «Ce are Owner-ul de
  făcut» (produce the character reference sets, choose the autonomy mode, approve the fallback
  vendors), and its migration item is corrected from 0040 to 0043. `16_DECISION_LOG.md` records
  thirty-two decisions of this phase. `13_ROADMAP_TODO.md` ticks the modes and the picture gate,
  marks two items `[~]` with what is missing named in the line, and adds the phase's own list.
  `PROJECT_STATE.json` moves to `0043_autonomy_mode`, 42 migrations, `autonomy_mode:
  AUTONOMOUS_CEO` and 1148/1. Three architecture documents are deliberately changed with their
  `sha256` re-recorded in `DOCUMENTATION_INDEX.json` and a decision-log entry each:
  `../architecture/50_CONTENT_GATE_MATRIX.md` (the picture and character gates and what each status
  certifies), `../architecture/51_AUTONOMY_MODE_SEMANTICS.md` (which of its sentences are code) and
  `../architecture/24_VISUAL_CONTINUITY_ASSET_SYSTEM.md` (who produces a reference set and what it costs).
  `../architecture/08_VIDEO_PIPELINE.md` was examined and left unchanged: the bounded chain is what it already
  prescribes.
- Suite on the integrated tree: **1148 passed, 1 skipped** (the opt-in real-Ollama test); `ruff
  check`, `ruff format --check` over 384 files, `mypy` over 143 source files and
  `scripts/check_docs.py` clean. Nothing ran against a real model, provider or platform; nothing was
  rendered outside FFmpeg on this machine; no daily run was queued and no credit was spent.
- Open, and named in `CURRENT_STATUS.md`: no vision model has ever answered the picture check and
  `seed_initial_workforce` seeds none, so the live studio will report NOT_APPLICABLE until the
  provider catalogue records one; no real render has gone through the second vendor and
  `REFERENCE_IMAGE_VERIFIED` stays False; the Owner cannot answer an approval, so SUPERVISED records
  the question and never hears the answer; `media/router.py` still measures and renders without the
  new gates, so his manual render and manual QC behave as they did yesterday; the factual storyboard
  records no cast, so the character check has nothing to compare there; 51's department-scoped
  autonomy is not implemented; and there is no frontend for any of it.

## Money and sources, closed — 2026-09-18

The four ends Phase E/F left open in files its implementers did not own.

- **Every adapter is built with the price table.** `price_lookup(engine, kind)` at the four
  construction sites — `main.register_seeded_ollama`, `integrations.services.load_registry`, the
  re-registration in `integrations/router.py` when the Owner saves a connection while the studio
  runs, and both voice doors in `media/factory.py` — so an employee's run and a narration carry a
  cost instead of NULL. `integrations/credits.py` and `integrations/discovery.py` stay unpriced on
  purpose (reading a subscription and listing voices generate nothing), and
  `tests/test_pricing_truth.py::PRICED_CONSTRUCTION_SITES` is the written-down list a fifth site
  cannot slip past.
- **`seed_documented_prices` has a caller**: `scripts/bootstrap.py`, beside
  `seed_chart_of_accounts`. One DOCUMENTED ElevenLabs row, nothing for Ollama Cloud, and never over
  a price of any provenance — a second bootstrap over a live studio leaves the Owner's own price
  standing.
- **A refused render is proved to charge the attempt and not the plan.** A three-scene film whose
  vendor refuses the third leaves a FAILED job carrying exactly scenes one and two, and two
  ESTIMATED rows flagged `failed=True` under `render:{job}:failed:scene:{n}:voice`; a second
  reading charges nothing.
- **The research report and the retest have routes, and the screens show them.** `GET
  /factual/research/health` (probes nothing, safe on every refresh) and `POST
  /factual/research/allowed-hosts/retest` (`max_age_days=0`, the Owner's "now"), both Owner-only,
  with a test pinning the 401 from the other side of the door. *Cercetare → Surse* prints whose
  search address is in force, the one discovered on the site and when, and the failure reason code
  before the site's own words; a «Test the sites» button asks for the retest. The Books office
  labels BLOCKED_BUDGET, prints the sum held for films in production, the cost of renders that
  failed midway, and how many runs have no recorded price.
- **Documents.** `../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` gains the order in which pages
  are found, the weekly retest's home inside the research stage, the media stage's money path and
  the preflight's new question — a deliberate specification change, its `sha256` re-recorded in
  `DOCUMENTATION_INDEX.json` (`70dc698c…` → `1de4ef7a…`) with the reason in the decision log.
  `PIPELINE_COVERAGE.md` follows in its research and media rows and strikes through, dated, the
  stale line about per-channel analytics. `PHASE11_ECONOMY.md` and `ACCOUNTING_AND_HISTORY.md`
  describe `provider_price`, `spend_reservation` and the hold inside `spend_since` for the first
  time. Fourteen decisions added to `16_DECISION_LOG.md`.
- Measured by the closure's implementers: 17 in `tests/test_pricing_truth.py` (six new, each
  written failing first), 19 in `tests/test_phase5_media.py` (one new), 108 across the media,
  discovery, settings and multi-LLM files, 69 across the adversary, production-policy and economy
  files, 15 across `tests/test_phase4_factual.py` and `tests/test_sources_and_readiness.py`, and 87
  frontend tests; ruff, `ruff format --check`, mypy and `tsc` clean. Every vendor faked at its
  transport: no socket left the machine and nothing was rendered, uploaded or paid for.
- Still open, and named in `CURRENT_STATUS.md`: the Owner's own prices, the live database's
  migration and bootstrap, `frontend/dist` not rebuilt, reconciliation of ESTIMATED rows against a
  vendor's invoice, and whether a render stopped by the Owner's own switch should be charged for
  the shots it had already bought.

## Money and sources — 2026-09-18

Phases E and F of running unattended, built in three parts and wired into the day: what a film
costs before it is made, where the day's pages come from, and the first test of a whole day.

- **The books hold money before it is spent.** Migration `0039_pricing_truth_and_reservations`
  (`provider_price`, `spend_reservation`, `provider_cost_record.failed`). `reserve_spend` decides
  behind the write lock and writes a RESERVED row every budget counts until `settle_reservation`
  or `release_reservation`; `estimate_film_cost_micros` prices a plan conservatively (motion at the
  ceiling that render will be given, narration at the dearest active per-thousand price over the
  storyboard's own voiceover); budget periods open at the studio's own midnight, read from the
  `studio` row, not at UTC's; `release_stale_reservations` is the watchdog's fourth sweep, at
  `STUDIO_RESERVATION_TTL_SECONDS` (six hours).
- **Prices are the Owner's.** `PUT /economy/prices` and `GET /economy/prices` (`app/economy/prices.py`),
  Owner-only, idempotent by command id, versioned, provenance OWNER | DOCUMENTED | QUOTED | BILLED;
  `seed_documented_prices` seeds one DOCUMENTED row — ElevenLabs' public Creator-plan figure — and
  nothing for Ollama Cloud. The ElevenLabs, Ollama and configured-LLM adapters take a `price_lookup`
  and cost every call from what they measured, answering None and never zero without a full price.
- **A refused render is still a cost, and a refusal is a letter.** `record_failed_render_cost`
  writes ESTIMATED rows flagged `failed=True` under their own reference, idempotent, shown as
  "ESTIMAT (randare eșuată)"; `budget_refusal_letter` and `may_run_agent` write the Accountant's
  letter to the Owner once per business date, decided behind the write lock. `may_run_agent` is the
  Policy Kernel's first gate: past `STUDIO_AGENT_DAILY_TOKEN_BUDGET` (0 = no ceiling) a run is
  recorded BLOCKED_BUDGET.
- **The studio finds its own pages.** Migration `0040_research_sources` (`discovered_search_template`,
  `discovered_at`, `last_test_reason`). A host test and the weekly `retest_stale_hosts` (7 days,
  inside the research stage) read the front page and look for the site's own OpenSearch address;
  the Owner's address keeps winning. Failures get a closed-vocabulary reason (HTTP_403, HTTP_ERROR,
  RATE_LIMITED, SCRIPT_ONLY, NETWORK, OTHER).
- **A search engine may name addresses and nothing else.** New catalog kind `search` (one HTTPS
  JSON contract, key in the vault, neutral-word probe) and `backend/app/providers/search.py`, which
  returns addresses and titles only. `find_pages` asks the Owner's addresses, then the discovered
  ones, then the verified engine, filters every result against the allowlist before anything
  downstream sees it, counts what it dropped, and reads each page with the studio's own DNS-pinned
  retriever. A guessed address is set aside when real pages were found. The day reads
  `STUDIO_RESEARCH_CANDIDATES_PER_DAY` × `STUDIO_RESEARCH_PAGES_PER_TOPIC` (4 × 4, clamped 1..12).
- **The preflight asks whether the studio can find pages.** `research_health` replaces the
  row-exists check: hosts authorised / tested / with a search address / failing and why, the
  engine's status, verified claims in hand, DEGRADED with named reasons. It probes nothing.
- **The day is wired.** `runbook/stages.py` (estimate → hold → settle or release, the refusal
  letter, the failed-render cost, the research budget and the weekly retest), `runbook/preflight.py`,
  `workflows/watchdog.py`, `agents/services.py` and four settings in `config.py`
  (`reservation_ttl_seconds`, `agent_daily_token_budget`, `research_candidates_per_day`,
  `research_pages_per_topic`).
- **The first test of a whole day.** `tests/test_autonomous_day_end_to_end.py` (new): the scheduled
  job fires, the worker runs the real runbook against a temporary database, two films are encoded
  and published private to their own channels, the serial is written and filmed, and a second tick
  starts nothing. Only the vendors are faked; the test skips without FFmpeg.
- **Documents.** `CURRENT_STATUS.md` gains the section above and the Owner's own list («Ce are
  Owner-ul de făcut»); `16_DECISION_LOG.md` records twenty-three decisions of this phase;
  `13_ROADMAP_TODO.md` ticks cost reservation and hard budgets, marks the keyword-search item
  partial and adds the phase's own list with what is still open; `PROJECT_STATE.json` moves to
  migration 0040 (41 migrations) and 1028/1 of 1029; `PIPELINE_COVERAGE.md` corrects in place,
  dated, the two sentences saying the Researcher has no search engine and that the day reads two
  candidates of four pages. No architecture document changed.
- Suite on the integrated tree: **1028 passed, 1 skipped** (the opt-in real-Ollama test), 1029
  collected; ruff, `ruff format --check` and mypy clean; `scripts/check_docs.py` passes. Nothing
  ran against a real model, provider or platform; no daily run was queued and no credits were
  spent.
- Open, and named in `CURRENT_STATUS.md`: no adapter is yet constructed with a `price_lookup` and
  `seed_documented_prices` has no caller, so agent runs still record `cost_vr` NULL and the live
  books hold no price; a FAILED render carries no scenes until `assembler._fail_job` writes them,
  so the failed-render cost honestly records nothing today; no route exposes `research_health` or
  the retest, and no screen shows the discovered address or BLOCKED_BUDGET.

## Phase B/C tried as an adversary — 2026-09-18

Seven defects measured by an adversarial pass over delivery and the serial, each with a red-first
test, and one guard that turns the Owner's rule about tests into a measurement.

- **The seven fixes.** `resolve_publish_visibility` holds an unlisted policy to PRODUCTION like
  public (it resolved unlisted in TEST, and an unlisted film is watched by anyone with the link;
  the truth-table row and two tests moved to PRODUCTION); `change_publish_policy` refuses a
  command whose resulting state is public+enabled outside PRODUCTION (the flag alone re-armed a
  policy already "public" in TEST); `select_channel_for` refuses a pinned `channel_id` that
  contradicts the storyboard's series key, both directions (a serial-keyed storyboard pinned to
  Channel A was SELECTED for Channel A while the media stage filmed it as the serial);
  `projection.py` redacts currency-first prices, scheme-less links and uppercase opaque keys
  (`_MONEY_FIRST`, `_DOMAIN`, `_OPAQUE_UPPER`; ordinary titles unchanged); the Director's privacy
  check reads the summary, the opened threads and the recurring elements with the same `leaks()`
  (a key in the summary would have entered canon and every later prompt); `_media` reads
  `stop_requested` before each film and reports BLOCKED naming the film it did not start (a stop
  set during the factual film started the serial's render); and the suite proves the Owner's rule
  instead of promising it (below).
- **Tests.** `tests/test_phase_bc_adversary.py` (new, 21 tests; 13 red first — 11 measured defects
  and 2 assertion shapes); `tests/test_publish_policy.py` and `tests/test_daily_run_stages.py`
  adapted where they had encoded the old readings (unlisted in TEST moved to PRODUCTION; three
  `_media` tests switch autonomy on first).
- **The loopback-only socket guard.** `tests/conftest.py` gained an autouse `no_network` fixture
  that refuses `socket.connect`/`connect_ex` to any address that is not loopback or a Unix-socket
  path, naming the address and the rule — the Owner's rule that no test contacts a real provider
  is now proven per run; every adapter goes through urllib or http.client, which the guard covers.
- Held without a defect: the Owner's leave per channel, one rewrite, a closed log unchanged by
  late events, the blank-frame rule for both kinds of film, loudness and captions QC naming their
  cause, the fallback gate, the per-film budget.
- **Documents.** `CURRENT_STATUS.md` gains the verifier's subsection and corrects in place, dated,
  the sentences that said only public needs PRODUCTION, that a pinned `channel_id` is followed as
  set, and that the render alone reads the stop; `16_DECISION_LOG.md` records the seven decisions
  and marks the 2026-09-17 entries they supersede in part; `13_ROADMAP_TODO.md`'s stop-polling
  line follows. No architecture document changed.
- Suite: the verifier's run 1, before its fixes, was 953 passed / 1 skipped; the changed files ran
  green after them (238, 103 and 21 passed); the whole suite on the final tree is the committer's
  run. Nothing against a real model, provider or YouTube; no daily run queued.

## The serial reaches Channel B, and the tracking documents catch up — 2026-09-18

Two measured defects still stood between an approved episode and the serial's channel, and the
documents said things the code no longer did.

- **The Director's brief has two readings.** `gather_facts` hard-rejected a script with no claims
  and her brief called a film about the studio REJECTED, so every serial film was refused before
  the publish routing saw it. A serial film is recognised by its own marks (`is_serial_film`:
  series key `office_serial`, or `story_json.kind == "office_serial_episode"`); for it the
  claims-based verdicts are not asked and the brief is the episode review's (`instructions_for`);
  a factual script with no claims is refused in the same words as before.
- **The Director's leave to approve episodes is a column of the publish policy.**
  `channel_record.director_may_approve_episodes` (default false), migration
  `0038_director_may_approve_episodes` (`main.py` pins it; run `scripts/bootstrap.py`), set only
  through `PublishPolicyCommand` with the command's versioning, idempotency and event. It was read
  from `series_rules_json`, which no command could write.
- The media route's render button and standalone QC pass `settings=request.app.state.settings`,
  like the daily run; `continuity_state` joins `HISTORY_TABLES`; `qc.py` is mypy clean;
  `YouTubeAnalyticsProvider(channel_id=…)` reads `STUDIO_YOUTUBE_*` only from a bare constructor;
  `PolicyView.public_publish_enabled` is a real bool ("any channel may publish publicly").
- **Documents to the truth.** `../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` renumbered to the order `STAGES`
  runs (§7 the serial queue, §12 the daily log), its indexed hash updated explicitly;
  `CURRENT_STATUS.md` no longer says "no real upload has ever happened" (two private uploads of
  2026-09-12, `98JltCPoOKs` and `sDEtt-WQGh8`), "eight of twelve stages" (ten are supplied, two
  are the run's own) or "every 24 hours, CATCH_UP" (05:00 local, a missed slot once, a failed day
  re-attempted); `YOUTUBE_CONNECTIONS.md` and the roadmap likewise; the roadmap unticks
  character-drift QC (`NOT_IMPLEMENTED`) and ticks captions and scheduled release now that they
  are real; the decision log records the Director's approval of scripts (2026-09-12, unrecorded
  until now) and Phase A's verifier findings; `stages.py`'s two docstrings no longer say the
  Owner approves scripts; `PROJECT_STATE.json` counts 39 migrations and 954 collected tests.
- Tests: 9 new across `test_editorial.py`, `test_publish_policy.py`, `test_phase5_media.py`,
  `test_phase7_analytics.py`, `test_reset.py`, `test_foundation.py`, each red first. Nothing
  against a real model, provider or YouTube; no daily run queued.

## Delivery and the serial — 2026-09-17

Phase B/C of running unattended: publishing by the Owner's per-channel policy, the serial
written, reviewed and filmed in the same run, captions and loudness measured. Measured before:
`_publish` took the first bound slot at a constant `private`; `scheduled_publish_time` was never
sent; the showrunner read raw payload pairs; nothing filmed an episode; `captions.srt` was never
used; nothing normalised loudness; a render ran to its end after STOP.

- **Per-channel publish policy** (migration `0037_publish_policy`): `autonomous_privacy`,
  `public_publish_enabled`, `publish_delay_minutes`, `policy_version`, `policy_changed_event_id`,
  changed only by `POST /publishing/channels/{id}/publish-policy` with `command_id` and
  `expected_version`, recorded in `publishing.channel_policy_changed`; "public" needs the switch in
  the same command and PRODUCTION. `resolve_publish_visibility` decides once; a delayed public
  release is a private upload with `publishAt`, which the YouTube adapter now sends;
  `update_visibility` exists, uncalled.
- **A film goes to its own channel or nowhere.** `select_channel_for` reads the storyboard
  (`channel_id`, series key `office_serial`, else MAIN_FACTUAL); an unbound or revoked slot is
  refused by name. A sixth gate, for a publication that would be seen, requires the channel's
  current `policy_version` stamped on it (`publication_record.policy_version`) and a visibility no
  more open than the policy allows. Analytics per channel: `analytics_provider_for_channel`,
  `measure_channel_publications`.
- **The serial** (migration `0036_serial_continuity`): `daily_studio_log.narrative_projection_json`
  — every event type classified by a table, private by default, descriptions redacted; the
  showrunner grounds beats on the projection only; `continuity_state` (episode number, threads,
  recurring elements, last summaries) advances only on approval; the Director reviews the episode
  (five computed checks, then her verdict; one rewrite); `storyboard_from_episode` turns an
  approved episode into an OFFICE_SERIAL storyboard in the factual storyboard's exact shape;
  `run_serial_stage` does it for the newest closed log. Routes under `/story/`.
- **Loudness and captions.** `media/toolchain.py`: `loudnorm` −14 LUFS / −1 dBTP, measured on the
  narration and applied as one linear gain; captions timed from the recorded narration, two lines
  of 42, SRT beside every film and burnt in above the bottom fifth (`captions_burn_in`); the
  manifest counts motion, fallback and skipped scenes. QC gained `audio_qc`, `captions_qc`,
  `motion_qc` (`max_fallback_scenes`, default half; a warning in TEST).
- **The run.** `serial_queue` between `script_and_storyboard` and `media`; `_media` films the
  factual storyboard then the serial's, asking the budget before each; yesterday's log is closed
  on the preflight line (`close_previous_day`, retried like a stage); `_publish` routes per film
  with the resolved visibility and the policy stamp; `_performance_intake` measures per channel;
  `assemble_video_job` polls the stop between scenes and before each motion shot (`RenderStopped`,
  reported BLOCKED with the Owner's reason); `ScheduledJobView` shows `run_at_local` and `timezone`.
- Settings: `STUDIO_CAPTIONS_BURN_IN` true, `STUDIO_MAX_FALLBACK_SCENES` unset (half). Run
  `scripts/bootstrap.py` (migrate) before starting this version.
- Whole suite at the commit: 945 passed, 1 skipped; ruff, mypy on the changed files and
  `scripts/check_docs.py` clean. Nothing against a real model, provider or YouTube.
- Open at the commit, closed 2026-09-18: the Director's film review refused a serial film; the
  Director's leave had no command; the runbook document's numbering. Still open: today's log is
  closed at the run's hour (a full-day log for every date needs the end-of-run close moved); one
  voice per scene; no screen for the publish policy; the first real day with Channel B bound and
  the first real scheduled upload should be watched.

## The clock, and a day that asks again — 2026-09-17

Phase A of running unattended: the studio's own clock, and the durability under it. Measured on
a copy of the live database, the daily job had never fired by itself; the one thing that had
stopped the studio for days was a single "database is locked" at the wrong second, recorded with
the weight of a bug, which opened safe mode and set the autonomy stop; no adapter retried a 503;
two renders had been RENDERING since 2026-09-12; and the worker lived only inside `start.cmd`.

- **A fault has a class.** `classify_fault` reads a stage's exception and its chain: TRANSIENT
  (timeouts, refused or reset connections, DNS, a provider's 408/425/429/5xx, SQLite's and
  SQLAlchemy's `OperationalError`, `RemoteStateUnavailable`, a runner's own `TransientStageError`)
  is retried in place three times at 20, 40, 80 s and, still failing, fails the run without safe
  mode; HARD — everything else — still opens safe mode. `daily_run.fault_class`, migration 0035.
- **A day is re-attempted.** A BLOCKED preflight or a TRANSIENT failure queues the next attempt
  half an hour on (`daily-retry-<date>-<n>`, three attempts per business date); a date that did
  work is never rerun by the clock; the Director's letter about a stopped day waits for the last
  attempt. `enqueue_task` takes `not_before`.
- **A fixed local hour.** `scheduled_job.run_at_local` and `.timezone`; `daily_main` at
  `STUDIO_DAILY_RUN_HOUR_LOCAL` (05:00) in `STUDIO_TIMEZONE`, DST-safe, still seeded dormant.
- **STOP cancels a day in flight**, between stages: the rest BLOCKED "Oprit de AUTONOMIE
  OPRITĂ.", the run PARTIAL or BLOCKED, no safe mode, no letter; `stop_requested(engine)` for
  the loops inside a stage.
- **The adapters retry.** `providers/retry.py` — `call_with_retries`, bounded exponential
  backoff with jitter, Retry-After honoured under the cap — wraps every outbound call in
  ElevenLabs, OpenAI images, Runway, Ollama, `ConfiguredLLM` and YouTube. A billed request that
  left and got no answer is not sent again; `media_http.request` says which phase failed
  (`unsent`, `unanswered`); the surfaced error keeps the vendor's class with "(after N attempts)".
- **The watchdog.** A scheduled `watchdog` job every ten minutes: renders stuck past three hours
  failed with the reason on the row, REMOTE_UNKNOWN and FAILED_RETRYABLE publications reconciled
  through the existing functions at most three times and then NEEDS_RECONCILIATION with a note
  for the Owner, lapsed leases reported. Nothing while STOP AUTONOMY is set.
- **The studio as a service.** `scripts/install_studio_service.ps1` registers the Windows
  Scheduled Task "AMN-AI Studio" (at logon and startup, three restarts, no time limit, log in
  `data/studio-service.log`); `uninstall_studio_service.ps1` removes it; README "Running as a
  service". Parsed, not run — the Owner runs them.
- Settings: `STUDIO_DAILY_RUN_HOUR_LOCAL` 05:00, `STUDIO_DAILY_MAX_ATTEMPTS` 3,
  `STUDIO_DAILY_RETRY_SECONDS` 1800, `STUDIO_STAGE_RETRY_ATTEMPTS` 3,
  `STUDIO_STAGE_RETRY_BACKOFF_SECONDS` 20, `STUDIO_WATCHDOG_INTERVAL_SECONDS` 600,
  `STUDIO_PROVIDER_RETRY_ATTEMPTS` 3, `STUDIO_PROVIDER_RETRY_MAX_SECONDS` 30,
  `STUDIO_RENDER_STUCK_AFTER_SECONDS` 10800, `STUDIO_RECONCILE_MAX_ATTEMPTS` 3. Run
  `scripts/bootstrap.py` (migrate) before starting this version.
- Open: `ScheduledJobView` does not show the hour yet; the long runners do not poll the stop
  inside a stage; a REMOTE_UNKNOWN publication with no remote id goes to the Owner rather than
  being resolved; the remote-state honesty test now takes four seconds of real retry sleeps.

## People on the pavement, and traffic that does not thin out — 2026-09-16

The Owner's goal for the live headquarters names what the picture has: trees, people, cars,
background, sky, light and clarity. The street had no people at all and its road was empty for
stretches.

- **Four passers-by.** `people/street_people.json` and `people/rig_employees.py` (which now takes
  another config through `AMN_PEOPLE_CONFIG`) build them from MetaHuman Creator presets, the same way
  the employees are built, into `/Game/AMN/People/Street`. `people/street_people.py` stands three of
  them on the terrace and sits one on the bench, each facing the viewer, with ActorCore standing and
  seated loops. They stand rather than walk because the Owner asked that every character face the
  viewer, and a walk across the frame shows a character in profile.
- **Clothes.** The MetaHuman plugin ships one garment: white underclothes. Tinting its own material
  instances left pieces of it white on three of the four, so each passer-by's garment components take
  a plain lit material (`M_HQ_Cloth`) in their own colour. At the plate's scale a dark top over darker
  legs reads as street clothes.
- **Eight vehicles instead of five.** Each crosses the frame in six to nine seconds of the traffic
  sequence's twenty-four, so five left the road empty where the picture always has traffic.
- **A road that reflects.** At roughness 0.25–0.5, traced to 0.4, the asphalt read flat. At 0.1–0.32
  traced to 0.6 the cars' lights and the shopfronts lie on it in streaks, as in the picture. The
  street's region went 7.0 → 6.0 with the fuller traffic.
- **Brighter planters and a worn crossing.** The planters' bushes were dark clumps (the picture's are
  full and lit) and the zebra crossing read as blown-out white; the bushes are lighter and denser and
  the paint is a worn grey now.
- `people/mh_retarget.py` holds the ActorCore-to-MetaHuman retarget both people scripts use.
- Mean colour distance against the picture: 6.3.

## The city, the sky and the street around the building — 2026-09-16

With the rooms close to the picture, the frame's own surroundings were the distance left: the mean
colour distance over all regions went 9.6 to **6.5**, the closest the live stream has been.

- **A dark edge of street.** The near pavement was a light, cool grey, so the frame's lowest rows read
  43, 42, 55 against the picture's 11, 20, 38. At `#31303c` those rows are 27, 29, 41 and the street
  region came 13.6 → 7.7.
- **A skyline of mostly dark towers.** Our facades had a third to a half of every window grid alight,
  a wall of yellow squares that made the city read as near. The shared facades keep half their lit
  share; the two the right-hand side alone uses keep more, because that side was already darker than
  the picture. City left 18.3 → 12.7, city right 15.7 → 13.1.
- **A cooler dusk.** Over the frame's upper half the sky read about 7 short of green and 12 short of
  blue. `compose_sky_backdrop.py --tint` (1.0, 1.10, 1.14) closes that: sky left 14.2 → **2.2**, city
  right 13.1 → 8.8, the roof sign 10.6 → 9.6.
- **A row of street trees instead of a wall of leaves.** Four tall trees on the left had grown into
  one mass that hid the city behind them; the picture has smaller trees with lit city between their
  crowns. Five smaller ones stand there now (a crown scales with its height), and the uplights that
  wash them are at 0.15 rather than 0.3: city left 12.1 → **6.6**, street 7.5 → 6.7.
- Tried: the static Megaplants trees in that row — they render as bare white branches, so the leafy
  Soul: City tree stays.
- Tried: halving the skyline's windows from the look pass (`AMN_LOOK_CITY_WINDOW_SCALE=2`); the towers
  read finer but no region moved and the mean went 9.1 → 9.4.

## The employees hold a frame that really faces the viewer — 2026-09-15

The men sat with the head bowed over the desk, which from the plate camera reads as the back of a
head — the thing the Owner asked to be rid of.

- The male hold frame was picked from the head's direction in the animation data alone. Photographed
  in the stream at nine frames of the loop (0, 2, 4, 7.25, 10, 13, 16, 19, 22 s), 7.25 s is one of
  the bowed ones; at **2 s** the head is up and the face towards the viewer. `seat_employees.py`
  holds the men there now (the women stay at 9 s). All eight were checked seat by seat afterwards.
- The bridge re-sends every seat's state every 20 s instead of every 60 (`backend/app/office/unreal.py`).
  A restarted level plays the seated loops again, so until the next resend the employees turned with
  the animation; the window is now a third as long, and a resend is three calls a seat to a local
  endpoint.
- The seating pass also clears earlier employees by label, not only by tag, so an actor from a pass
  that failed half way through cannot stay behind in the level.
- Tried: a small cool light in front of each seat for the screens' light on the face. Eight of them,
  even at 8 units over 60 cm and without shadows, lifted every room far above the picture (mean 9.6
  → 31.6), so the faces keep the room's own light.

## The rooms read like the picture's rooms — 2026-09-15

Side by side at the offices' own scale, the live rooms were emptier, colder and darker than the
Owner's picture. Four things came out of that comparison, all verified in the stream.

- **The colours of the right-hand rooms.** Fact Check had terracotta walls and Distribution green
  ones, where the picture shows one blue floor on L3 and one warm floor on L2 from end to end. Both
  now use their floor's own wall and floor material (`hq_building.py`); each room keeps its sign and
  its accent colour. The two worst regions came down at once: L3 14.7 → 7.8, L2 16.4 → 7.2, and the
  mean 10.5 → **9.2**, the closest the frame has been. L2's sofa is brown leather, like the picture's,
  where it was red.
- **The pendant lamps.** In the picture every room hangs lit shades; ours were dark cones. The shade
  was a black cone with a 1.4 cm emissive disc under it, which falls under a pixel at the plate's
  scale. The disc is now 6 cm deep and as wide as the shade, so it reads as the picture's bright band
  under a dark shell; `look_hq_live.py` tunes it (and the floor lamps and the lobby's wall bulbs) with
  `AMN_LOOK_LAMP_GLOW`. Tried first with the whole cone warm: it blew out into a white blob.
- **The pinned photographs.** `make_textures.py` drew them as blurred pastel blobs, brighter than the
  cork they hang on, which flattened the wall. They are small night photographs now (a skyline against
  a lit horizon, `snapshot()`), so each frame on L2's board and L4's shelf reads as a picture. Tried:
  raising their emission from the look pass instead (1.6, 3, 8) — the export bakes that emission, so
  the knob changed nothing and was removed.
- **The bare stretches.** `dress_hq_live.py` now places 34 small pack objects where the build leaves
  counters and benches empty (laptops, trays, folders, books, speakers, headphones, mugs, table lamps),
  a leafy frond on the bookshelf tops and in L3's corner, a rack cabinet by L1's door, and two
  armchairs around the lobby's low table, as the picture's lobby has.

## No glare on the slabs between the floors — 2026-09-15

Above every office floor the slab's face read as a light slate strip, where the Owner's picture has
a dark edge. Darkening the slab's colour did not change it (see "A dimmer line under the ceilings").

- The strip was the facade light's glare: the area light stands straight in front of those faces.
  `look_hq_live.py` now sets that light's specular share to 0 (`AMN_LOOK_FACADE_SPECULAR`). It still
  lights the frame's navy, which is its diffuse light.
- Compared in the stream: the strips' rows came down by 19–26 (L2 93 → 73 and 87 → 64, L3 89 → 68 and
  74 → 47, against the picture's 42–77). The mean held at 11.1.
- The brighter rows just below the slab, the top of L2's room (110 against the picture's 58), did not
  move: that is the room's own light, the next thing to look at.
- Tried: the small warm lights under the ceilings at 0.15 instead of 0.35. The top of L2 moved by
  about 1 (111.9 → 110.6), L4 drifted from the picture (1.5 → 3.4) and the mean went 11.1 → 11.2, so
  they stay at 0.35.
- Tried: the ceiling spots (the cones on the walls) at 0.08 instead of 0.15. The top of L2 did not move
  (111.9 → 111.7), while L3 and L4 turned darker than the picture (L3 14.6 → 20.2, L4 1.5 → 7.5) and the
  mean went 11.1 → 12.1, so they stay at 0.15. L2's bright top is none of the lights tried so far.
- Tried: L2's area fill alone at 0.3 (it hangs under the ceiling, tilted onto the back wall). It dimmed
  every row of L2 alike, by 4–7: the top stayed far brighter than the picture (107.5 against 58–80)
  while the lower rows fell below it. L2's region went 17.5 → 21.8 and the mean 11.1 → 11.4, so the
  setting was dropped. No single light of L2 makes its top bright; the room is lit evenly from floor to
  ceiling where the picture's is darker at the top.

## Every employee faces the viewer — 2026-09-15

The Owner: every character must face the viewer, never side-on or from behind. In the live stream all
eight employees sat in profile.

- Cause: `seat_employees.py` placed each MetaHuman at yaw 90, so the actor's forward axis (+X) pointed
  at the camera. But the blueprint leaves the body mesh unrotated, and a MetaHuman mesh faces its own
  +Y, so at yaw 90 every body looked across the frame.
- `people/turn_employees.py` turns the seated employees to yaw 0 in place (`AMN_SEAT_YAW`). The actors
  are rotated, not placed again, so the object paths the backend's Remote Control bridge uses stay
  valid. `seat_employees.py` now places them at the same yaw on every rebuild.
- Checked in close-ups of the stream: the employees on L4, L3 and L2 sit facing the viewer behind
  their white desks.
- The seated talking loops turned them again as they played: sampled over time, the head swings
  about 60° to either side of the body, towards the monitor, for most of each loop. Kael and Marcus
  were caught leaning over their monitors. `seat_employees.py` now records each loop's frame where
  the head looks the way the body faces (`front_s`: 7.25 s male, 9.0 s female) in
  `seat_report.json`. The Unreal bridge holds every employee shown on that frame, working or paused
  (`SetPlayRate(0)`, then `SetPosition`). `DefaultRemoteControl.ini` allows `SetPosition`.
- Seen in the stream after the backend restart: all eight face the viewer, and they hold still
  across frames. The consequence: the employees no longer animate until a seated loop that stays
  facing the viewer is available.

## A dimmer line under the ceilings — 2026-09-15

The warm line under each office ceiling (`hq_building.ceiling_cove`) shared the slab lines' material
(`edge_led_warm`, strength 3.0), so neither could be dimmed without the other.

- The line now has its own material, `cove_led`, at strength 1.2. Rebuilt with the export
  (5.3 minutes) and compared in the stream: mean 11.7 → **11.0**, the closest pass so far (ground
  floor 7.6 → 6.0, lift tower 10.6 → 8.9, roof sign 11.8 → 10.9; the street's 13.0 → 8.9 is partly the
  traffic).
- The bright band under L2's ceiling hardly moved (111 → 108, against the picture's 71). It is neither
  the line nor the rooms' lamps (see "A dimmer L2").
- Tried next: the slab faces between the floors at 0.4 of their colour. The band moved by under 1
  (108.1 → 107.6), so the slabs are not its cause either. The setting was dropped; the room signs and
  the downlights' bulbs remain to check.

## A dimmer L2 — 2026-09-15

L2 (Content and Distribution) read brighter than the Owner's picture (84 against 79).

- `look_hq_live.py` runs L2's interior lights at 0.6 of their base (0.7 before; `AMN_LEVEL_GAIN`).
  Compared in the stream: L2's region 19.1 → 17.9 and the mean 11.9 → **11.7**, the closest pass so
  far. Its lower rows now read like the picture's. The band under its ceiling (the warm line and the
  pendants) still reads brighter: 111 against 71.
- Tried: the rooms' lamps (pendants, desk and floor lamps) at 1.5 instead of 2.0. L2's ceiling band
  only came down to 105, while L4 turned darker than the picture (1.2 → 4.4) and the mean held at
  11.7. The band is the ceiling lines' doing, not the lamps', so the lamps stay at 2.0.

## Darker tree crowns on the left — 2026-09-15

After the lobby, the area left of the building was the frame's most distant region (colour distance
24.3). Its rows through the tree crowns read 87–97 where the picture's read 40–61.

- The tree uplights are not the cause. At 0.15 instead of 0.3 those rows moved by less than 1 (the
  mean's change came from the street, which varies with the traffic). The crowns' brightness is
  their leaf texture's, as the material's colour parameter had also shown.
- The green leaf texture is now made at 0.4 of its value, down from 0.6 (`green_leaves.py`'s
  default), and imported again. Compared in the stream: the crown rows came down by 4–7, the left
  region 24.3 → 18.5, and the mean 12.3 → **11.9**, the closest pass so far. The uplights stay at 0.3.

## A dimmer lobby — 2026-09-15

The ground floor was the frame's most distant region after the city (colour distance 25.7): the
lobby read brighter than the Owner's picture across the whole floor (81 against 66).

- `look_hq_live.py` runs the lobby's fills and spill lower (`AMN_LOOK_LOBBY`, 0.75 before).
  Compared in the stream:

  | Lobby | Ground region | Street | Mean |
  | --- | --- | --- | --- |
  | 0.75 | 25.7 | 16.2 | 14.4 |
  | 0.55 | 18.8 | 15.4 | 13.7 |
  | 0.4 | 12.7 | 11.5 | 12.8 |
  | 0.3 | 8.3 | 14.0 | **12.6** |

  0.3 is the new default and the closest pass so far. The lobby's spill had lit the pavement in
  front of it too. The street region moves by about ±2 with where the traffic is. The ground floor's
  lower rows now read a little darker than the picture and its upper rows a little brighter, so the
  lobby goes no lower.

## Green LEDs on the server racks: Nanite was hiding them — 2026-09-15

In the Owner's picture the S1 server racks show rows of green lights. Live they stood black, at every
size and strength tried (see "Server LEDs … tried, left off" below).

- The cause: the import makes every merged scene mesh a Nanite mesh, and Nanite's simplification
  dropped the LEDs' small separate boxes, while the long lights of the same mesh (rack bars, the
  room's grid) survived. A probe showed the small lights' mesh at 904 triangles; with Nanite off it
  has 2,586.
- `art-source/unreal/nanite_hq_live.py` turns Nanite off on that mesh (`glow_details`,
  `AMN_NANITE_OFF`). The editor subsystem that normally does it is not available in a commandlet,
  so the script sets the mesh's own Nanite setting and saves the asset. `rebuild_live_hq.ps1` runs it
  right after every level build.
- The look pass now gives the small lights their own colours by default (`AMN_LOOK_LED_GAIN=1`, the
  dots at 8 times their strength). The infra room's grid lines take 0.15 of theirs: at 0.5 their
  glow hid the "I" of the S1 INFRA sign.
- Seen in the stream: the racks show rows of green and a few amber dots, like the picture's, and
  the sign reads whole. The mean moved from 14.0 to 14.4, almost all of it the ground floor's region,
  which the new lights brighten.
- Also tried on the rooms' furniture mesh (`props`: books, desk items). It showed no visible
  change and the same mean, so only the small lights' mesh is changed.

## White desks for the employees again — 2026-09-15

In the Owner's picture every employee sits at a white desk with a lit front. The Blender scene
builds exactly that (a white top, a light front panel and a lit edge), but the live dressing
replaced each workstation with Apartment Tech Props' dark wooden desk and chair.

- `dress_hq_live.py` now keeps the scene's own workstations (`AMN_DRESS_CONSOLES=blender`, the
  default; `pack` brings the pack's desks back). Only the keyboard, mouse and desk lamp still come
  from the pack, on the same 75 cm top. The rebuild places 73 pieces instead of 89, and all eight
  employees are seated as before.
- Compared in the stream: every employee now sits at a white, lit-fronted desk like the picture's.
  The mean held at 14.0 (L3 14.6 → 13.9, L2 18.2 → 18.8).

## Lighter plants in the rooms — 2026-09-15

The scene already places 21 plants in the rooms, most of them where the Owner's picture has plants,
but in the live frame they read as dark silhouettes where the picture's are a lit green.

- Plants of 0.9 m and taller are the restaurant scene's potted frond. The pack keeps its leaves'
  colour at 0.143 (`BaseColorMultiply`), relying on subsurface light in its own brightly lit
  restaurant.
- `look_hq_live.py` puts a child instance of that material on the fronds (`MI_HQ_PlantFrond`;
  the pack's own stays untouched) with the colour at 0.6 (`AMN_LOOK_PLANT_FROND`). Compared in the
  stream: the fronds read a lighter green, the mean held (14.0 against 13.9, L4 1.2).
- They stay thinner than the picture's bushy plants: that is the model's shape, not its colour.
- Tried: Palms Pack's fuller plants for every room plant (`AMN_BIG_PLANT_CM=999`). In the stream they
  read as thin dark stems, fainter than the lightened fronds, and the mean slipped (14.0 → 14.1).
  The fronds stay.

## A warm line under every office ceiling — 2026-09-15

In the Owner's picture a warm LED line runs under each office floor's ceiling, and the tops of the
rooms glow with it. L3 and L1 had no such line in the scene; L4 and L2 had thin ones, set back at the
rear wall.

- `hq_building.ceiling_cove()` adds a warm line under each office ceiling (L1–L4), hung just behind
  the slab's face so it shows from the front, and six small warm lights beside it on each floor
  (`cove_wash`, 18 W). They reach the live level through the full rebuild with the Blender export
  (4.8 minutes); the look pass scales the lights with `AMN_LOOK_COVE`.
- Compared in the stream (mean colour distance, 14.7 before):

  | Cove lights | Mean | Seen |
  | --- | --- | --- |
  | 1.0 | 15.7 | the lines show like the picture's, but the rooms read too bright (L2 88 against 79) |
  | 0.35 | **14.5** | L4 5.5 → 3.5, L3 17.0 → 14.2; the new default |

- Two regions moved away: L1 (7.5 → 10.3) and the roof sign (10.2 → 14.2). Row by row, all of
  that change sits in the rows where the new lines fall: they burnt at 129 and 103 where the
  picture's lines read 64 and 62. They share their material with the slab lines, which the look
  pass had raised to 3 times. At 1.5 the mean is 14.1; at the imported strength
  (`AMN_LOOK_STRIP_GAIN=1`, the new default) **13.9**, the closest pass so far: L4 1.4, L1 9.2, the
  roof sign 11.8.

## Brighter ceiling strips on the live headquarters — 2026-09-15

In the Owner's picture a warm LED strip under each floor's ceiling washes the top of the walls. In
the live frame the top floor's strip is a thin line, and the floors below have none.

- `look_hq_live.py` raises the strips' emission (`edge_led_slab`, `edge_led_warm`, `edge_led`) to
  3 times the imported strength (`AMN_LOOK_STRIP_GAIN`; the imported value is recorded once, so a
  rerun stays the same). Compared in the stream: L4 came closer to the picture (7.8 → 5.5), the roof
  sign moved slightly away (9.1 → 10.2), and the mean stays at 14.7.
- L3 and L2 have no ceiling strip in the scene at all, so a factor cannot give them one. The strips
  have to be added in the Blender scene.

## Server LEDs and smaller skyline windows: tried, left off — 2026-09-15

Two more differences from the Owner's picture were tried in the stream and left off, because
neither brought the frame closer:

- **Server LEDs.** In the picture the S1 racks show rows of green lights; the live racks stand black.
  Every small light (rack LEDs, rack bars, the PCs' and speakers' LEDs, the infra room's grid) is
  baked into one shared emission texture, where it is averaged away. The look pass can give each its
  own colour again (`AMN_LOOK_LED_GAIN`, off). At the scene's strengths the rack bars and the grid
  glowed, but the LED dots did not. At 8 times their strength they still did not: each is 3 × 3 cm,
  under one pixel in the frame, and most likely lost with the imported mesh's smallest parts, while
  the grid's teal lines grew stronger than the picture's. A third try made the LEDs 9 × 5 cm in the
  Blender scene (about 3 px) and rebuilt the level: still no green dots, baked or in their own
  colours. So the cause is neither size nor strength, most likely something in front of them. The
  larger LEDs were not kept, and the LEDs are left for a closer look at the S1 room's geometry.
- **Skyline windows.** The skyline's windows are about 6 × 9 px in the frame, the picture's 2–3 px.
  Halving them through the facade textures' scale (`AMN_LOOK_CITY_WINDOW_SCALE=2`) looked finer by
  eye, but measured further from the picture (mean 14.7 → 14.9; the right-hand city 11.9 → 14.1).
  The export's size stays.

## A lit frame and city views in the rooms' windows — 2026-09-15

Two things set the live headquarters apart from the Owner's picture at a glance: the building's frame
was black where the picture's is a lit dark navy, and the rooms' windows onto the city were flat
mauve panels.

- **The frame.** `look_hq_live.py` places a facade light (`FacadeLight`): a cool area light 10 m in
  front of the building, facing it, on lighting channel 1. Only the `shell` actor also receives
  channel 1 (frame, stone, plinth, glass, roof). The rooms and their props are separate actors, so
  the light behind the open front stays as it was. Compared in the stream (mean colour distance, 15.0
  without):

  | Facade light | Mean | Seen |
  | --- | --- | --- |
  | 20,000 lm over the whole front | 39.6 | a white frame, the roof sign burnt out |
  | 3,000 lm | 20.5 | a slate-grey frame |
  | 800 lm | 15.4 | upper floors closer; ground floor and lift tower too bright |
  | 800 lm held to the floors above the ground floor | **14.6** | a dark navy frame, the new default |

  The light's bottom edge, centre, width and barn doors (5°, 10 m) hold it to the main block above
  the ground floor (`AMN_LOOK_FACADE_*`).
- **The rooms' windows.** The export bakes the windows' city images into the shared `props`
  texture, where each window gets a few texels: the average of its dusk image, mauve. The look pass
  puts the images themselves (`art-source/blender/hq/textures/window_city.png`, `window_city_b.png`)
  back on those two materials, on the model's own UVs, at emission 1.5 (`AMN_LOOK_WINDOW_VIEW`).
  The windows now show dark towers with lit windows against the dusk.

## Blue haze over the live skyline — 2026-09-15

In the Owner's picture the city fades into a blue haze towards its base; the live skyline stood as
black blocks with sharp lit windows.

- Height fog could not do it alone. Its distances count from the plate camera, 246 m in front of
  the building, and the scene's own fog (0.008 from 30 m) is also a veil that lifts the building's
  black frame, the rooms and the sky. Fog moved out to the skyline only (0.12 from 260 m, cut off
  past 330 m) hazed the towers, but the rest went dark: mean colour distance 15.6 → 29.7.
- `art-source/unreal/haze_hq_live.py` draws the haze instead: two unlit, translucent planes
  across the frame, 12 m and 27 m behind the building's front, in front of the city's layers.
  Each fades from full strength at the skyline's base to nothing towards the tower tops (material
  `M_HQ_SkylineHaze`, `AMN_HAZE_*`). The building, the street and its trees stand in front of the
  planes and are untouched. `rebuild_live_hq.ps1` runs it after the look pass.
- Compared in the stream (all regions; left city / right city): no haze 15.6 (22.2 / 20.2); opacity
  0.35 fading out at row 260, 15.3 (20.9 / 17.4); opacity 0.55 fading out at row 160, **15.0**
  (24.1 / 12.0), now the default. The towers read blue and hazy on both sides, the left a little
  lighter than the picture's.
- The building's frame renders black where the picture's is a lit grey. Its materials are 0.5–0.6
  metallic, but setting them to 0.1 changed nothing visible: the frame lacks light, not colour.
  `look_hq_live.py` keeps that setting (`AMN_LOOK_FRAME_METAL`), off.

## A lit street and darker crowns on the live headquarters — 2026-09-15

Next to the Owner's picture the live street was nearly black: the road and the near pavement came
to 15-45 of 255 where the picture's are a lit, cool grey at 55-100, and the green crowns read too
bright.

- Darker leaves: the green leaf texture is now made at 0.6 of its value and 0.95 of its saturation
  (`green_leaves.py` defaults). Measured 16.6 against the picture (17.1 before).
- Why the street was black: nothing lit it. The three street lamps (35,000 lm each) pool on the far
  pavement, and the sky light only captures a dim dusk atmosphere.
- `look_hq_live.py` now places a street fill: a wide, shadowless, cool area light 6 m up, pointing
  straight down over the road (`StreetFill`; `AMN_LOOK_STREET_FILL` lumens, `_Y`, `_DEPTH`). Each
  setting was compared in the stream (street region, 28.4 without the fill):

  | Fill | Street | Result |
  | --- | --- | --- |
  | 4,000 lm over the near pavement | 20.3 | the pale pavement turned lavender |
  | 6,000 lm over the road | 46.4 | a flat grey street |
  | 3,000 lm at y −16 m | 18.2 | |
  | 3,000 lm at y −19 m, 14 m across | 13.5 | the new default |

  With the new default the mean over all regions is 15.6, the closest pass so far (15.9 before).
- Letting Lumen trace reflections up to roughness 0.6 (`AMN_LOOK_TRACE_ROUGHNESS`; the engine's
  own limit is 0.4) brought no light streaks to the road and raised the whole ground floor by about
  4, so it stays at 0.4. The look pass also sets the wet asphalt's roughness range
  (`AMN_LOOK_ROAD_ROUGH_MIN`/`_MAX`, 0.25–0.5) and can cut the fog off past a distance
  (`AMN_LOOK_FOG_CUTOFF`), so the skyline can take haze that the sky behind it does not.

## Green leafy trees on the live street — 2026-09-15

The street's trees were the Blender export's round crowns, which read as foam next to the Owner's
picture, and Megaplants' real trees cannot show their leaves on this machine.

- Soul: City's trees, probed and compared in the stream: the aspen's leaves are a translucent
  material (poorly lit, without depth, hence bare and pale), two are pines, one is a twisted bare
  tree, two more read as bare white branches. One, `SM_S_BuildingSetA_Tree_02_OP02`, keeps a full
  crown (masked, two-sided leaves), and the capture holds with it (no recreate warning).
- Its leaves were autumn orange. The material's only colour parameter (`LitColor`) did not change
  them: the leaf texture itself is orange (leaves average RGB 102, 75, 43). `art-source/unreal/leaves/`
  makes a green copy of it: `export_leaf_texture.py` (Unreal), `green_leaves.py` (turns the leaves'
  hue from 34 to 105 degrees, alpha untouched; RGB 54, 93, 40) and `import_green_leaves.py`
  (Unreal, `/Game/HQ/Materials/T_HQ_Leaves_Green`). The generated images are not committed (pack
  content). `dress_hq_live.py` places the tree (`AMN_TREES=soul`, now the default) with the leaf
  instance `MI_HQ_TreeLeavesGreen`; the tree uplights now run at 0.3.
- Seen in the stream: green leafy crowns on both sides of the building. Measured 17.1 against the
  picture (15.9 with the foam crowns): the crowns read brighter than the picture's (the area left of
  the building 77 against 63). Darker leaves are next.

## Static copies of Megaplants trees: the stream holds, the leaves do not show yet — 2026-09-15

The live level's trees are the Blender export's round crowns, which read as foam next to the
Owner's picture. Megaplants has real trees, but every one is a skeletal mesh (25 of 25), and
skeletal trees stopped Pixel Streaming's capture on an earlier pass.

- `art-source/unreal/convert_trees_static.py` copies a tree's geometry out of the skeletal mesh
  with Geometry Script (`CopyMeshFromSkeletalMesh`) into a new Nanite static mesh under
  `/Game/HQ/Trees` (`CreateNewStaticMeshAssetFromMesh`), keeping its materials. The project now
  enables the `GeometryScripting` plugin. Four trees converted (black alder, black poplar, goat
  willow, Japanese medlar); `dress_hq_live.py` has `AMN_TREES=megastatic` for the two with round
  crowns.
- Verified in the stream: with the static trees the capture held (no "PixelCaptureMediaCapture
  will be destroyed" warning, frames delivered). But the trees rendered bare, white branches with
  no leaves, which reads worse than the foam crowns; the live level went back to its Blender trees
  (the default) while the cause is traced.
- Traced: the Megaplants trees are Nanite skeletal meshes grown by the Procedural Vegetation Editor
  as Nanite assemblies, and their leaves are assembly parts, not triangles of the mesh. A copy of
  the source model has a bark and a foliage section but no UVs; a copy of the render data
  (`AMN_TREE_LOD=RENDER_DATA`) has the bark alone. No Geometry Script copy can carry the leaves.
  The Procedural Vegetation Editor exports a tree as a static mesh with its foliage
  (`Export Mesh Type: Static Mesh`), but only from its editor, so the project now enables that
  (experimental) plugin for that export. `convert_trees_static.py` also gained `AMN_TREE_LOD`,
  `AMN_TREES_OVERWRITE` and Nanite set through `NaniteSettings` (the first copies had Nanite off).
- The export from that editor, with the leaves baked into the mesh ("Create Nanite Foliage" off,
  2,028 foliage instances), ran the editor out of memory, and the streamed game went down with it.
  The editor also warned that the project lacks Shader Model 6 and Nanite Foliage, which Nanite
  assemblies need. Enabled together in `DefaultEngine.ini`, they made the streamed game crash on
  its first frames: a D3D12 fatal error, "No command list slot was available. Too many residency
  sets are open concurrently", during the startup burst of pipeline-state compilation. Both were
  reverted and the stream came back on Shader Model 5 (live, frames delivered). A separate game
  process with Shader Model 6, `r.Nanite.Foliage=1` and `D3D12.ResidencyManagement=0` then crashed
  the GPU ten seconds in ("GPU Crashed or D3D Device Removed"), and the machine stopped responding
  and had to be restarted. That route is closed on this machine (Radeon RX 9070): Shader Model 6
  and Nanite Foliage stay off, and Megaplants' Nanite-assembly leaves cannot be used here.

## Real paintings and wet asphalt in the live headquarters — 2026-09-15

Light values alone kept the live level about as far from the Owner's picture as before (24.2 to
24.3), so the stand-ins themselves are being replaced with the packs' models and materials.

- The Unreal export (`AMN_UNREAL_PROPS=1`, set by `rebuild_live_hq.ps1`) no longer draws the rooms'
  plants and portrait pictures: `hq_lib.plant()` and `frame_picture()` record where they stand
  (`hq_scene.json` "props_m": 21 plants, 5 paintings). `dress_hq_live.py` places Palms Pack plants and
  the restaurant scene's framed paintings there. The web plates are built exactly as before.
- The road wears the bridge scene's cracked asphalt (world-space triplanar, no UVs needed), made
  wet in `/Game/HQ/Materials/MI_HQ_AsphaltWet` (roughness 0.18-0.5 instead of 0.85-1.0).
- `rebuild_live_hq.ps1` runs `look_hq_live.py` after seating the employees: a build recreates every
  light at its defaults, so the look pass is applied again each time.
- Measured against the picture after one full pass (mean colour distance, lower is closer): 16.5,
  the closest the live level has been (24.2 before). The lift tower 7.9, L1 10.0, L4 10.8. By eye:
  the paintings hang facing the camera; the plants are a step back, thin dark sprigs where the
  Blender plants were full; the lobby is too bright (82.7 against 68.2) and the street too dark
  (50.8 against 60.6).
- Second pass: only the full Palms plants (the slender `SM_Plant_07_*` dropped), the restaurant
  scene's large potted frond for plants of 160 cm and more (`AMN_BIG_PLANT_CM`), the lobby's fills
  at 0.75 of the rooms' (`AMN_LOOK_LOBBY`). Measured: 15.8; the ground floor 23.6 to 16.9, the
  lobby's two fronds leafy like the picture's. Still short: the smaller plants on L3 and L4 read
  as dark silhouettes, and the street is as dark as before (50.1 against 60.6).
- Third pass: fronds from 90 cm read leafy on L3 and L4 too, and are kept (`AMN_BIG_PLANT_CM` 90).
  A more reflective, untinted asphalt and street lamps at 0.8 did not lift the street (25.2) and
  brightened the lift tower (10.2 to 14.0) and the ground floor, so they were dropped; the street
  needs another approach than more light. The best balance so far is now each script's default
  (`look_hq_live.py`, `dress_hq_live.py`, `AMN_SKY_GAIN` 1.1 in `build_hq_scene.py`), so a rebuild
  without overrides reproduces it.

## The live headquarters compared region by region with the picture, and the look pass — 2026-09-15

The Owner asked whether the live Unreal headquarters looks like his picture, and to correct the
office, the lights, the textures and the finishes. It does not. Cut region by region against the
picture at the same scale (a 1920x1008 frame from the stream): the picture's rooms have soft warm
light (cove strips, glowing pendants), panelled walls, pinned boards, framed pictures, windows onto
the city and dense plants, where the level had hard coloured spot cones on flat walls, empty
frames and flat purple windows; the picture's street is wet asphalt with streaks of reflected light,
stone paving, bollards and people, where the level had a black road with white headlight patches;
its skyline has sparse lit windows in blue haze and a bridge, where the level had bright blocks.

- `art-source/unreal/look_hq_live.py` tunes the saved level in place (lights by kind, skyline
  emission, the asphalt's roughness and specular, fog, exposure, bloom and a cool-shadow,
  warm-highlight grade), with absolute values from `AMN_LOOK_*`, so passes can be compared without
  re-importing. Measured with `compare.py` (mean colour distance, lower is closer; 24.2 before):
  pass 1 29.6, every region brighter than the picture and the road a mirror of the shopfronts;
  pass 2 27.3, the street's colour right (1.3) but grey and hazy, the ground floor and the sky
  still too bright, the cones still on L4's wall. Tuning light alone does not close the gap: most
  of it is textures, materials and objects.
- `live/rebuild_live_hq.ps1` no longer stops at the Blender export when run by Windows PowerShell
  5.1: that shell turns a native program's stderr into error records, and under "Stop" Blender's
  first DeprecationWarning aborted the pass. The export is judged by its exit code (verified: the
  export passed, 54 meshes, 45 baked, in 115 s).
- `export_hq_scene.py` draws the skyline's window textures with fewer lit windows
  (`AMN_WINDOW_LIT_SHARE`, 0.6 of the Blender material's), each at its own brightness
  (`AMN_WINDOW_DIM_MIN`) and divided by a mullion.

## The live headquarters reaches the Owner's browser, and stops flickering — 2026-09-15

- The Owner's page kept switching between the Unreal stream and the page's own renderer. Every
  connection from his browser (Comet) ended after 13 seconds and was retried 15 seconds later;
  Unreal logged "Failed to set codec preferences: Missing codec from recv codec capabilities" for
  each. `start_live_hq.ps1` forced H.264, which that browser cannot decode. It now passes
  `-PixelStreamingWebRTCNegotiateCodecs`: Unreal offers H.264, VP8, VP9 and AV1 and the browser
  picks one. Verified: a Chromium build without H.264 received 1920x1008 video (346 frames in
  three seconds), and the Owner's next connection stayed up until the stream was stopped.
- When the stream drops after it has shown a frame (a restart of the game, a network hiccup), the
  page keeps that frame, frozen, with "Reconnecting to the live headquarters…", instead of
  uncovering its own renderer, which draws a different picture of the same building
  (`streamLayers` in `hq_stream_config.js`, a frame kept every two seconds in `hq_stream.js`).
- The Owner still saw the older picture while the level was being rebuilt ("Încă apare vechiul
  format!"): with no frame yet the page showed its renderer. With a stream configured the page
  now never shows it: before the first frame the viewport stays dark and says "Starting the live
  headquarters…" (the renderer keeps running underneath, so clicks still find the employees).
  `rebuild_live_hq.ps1` stops the stream only when Unreal is about to touch the level, after the
  Blender export, so a full pass keeps the picture live about two minutes longer.

## The MetaHuman employees seated in the live headquarters, and driven by the studio — 2026-09-15

- `backend/app/office/unreal.py`: with `STUDIO_OFFICE_UNREAL_REMOTE_URL` (the streamed game's
  Remote Control, e.g. `http://127.0.0.1:30010`) the backend reads the office layout every
  `STUDIO_OFFICE_UNREAL_SYNC_SECONDS` (5) and tells Unreal, desk by desk, what it says: an
  employee is shown only while an agent holds the desk, and held still while that agent is paused
  or suspended. Only changes are sent; everything is sent again after Unreal fails to answer and
  every minute. Unset, nothing reaches out. `tests/test_office_unreal_bridge.py`.
- `art-source/unreal/people/seat_employees.py` retargets ActorCore's seated loops onto the
  MetaHuman skeleton, seats every built employee at their desk facing the viewer, and records the
  actor, body and animation object paths in `people/seat_report.json` for the bridge. It is the last
  step of `live/rebuild_live_hq.ps1`, since a rebuilt level has no employees.
- `art-source/unreal/people/rig_in_editor.py` rigs and builds the MetaHumans unattended in the full
  editor and quits. A commandlet could not: the eighth build (Nadia) crashed twice in TextureGraph's
  groom bake at frame 0, with and without `-AllowCommandletRendering`, while the same build worked
  from an editor that had already drawn frames. `-ExecutePythonScript` closes the editor as soon as
  its file returns, so the script is started with `-ExecCmds="py …"` and waits 300 ticks.
- `Config/DefaultRemoteControl.ini` allows only the bridge's two calls. The streamed game refused
  `SkeletalMeshComponent` functions until they were listed ("not allowed by remote control
  settings"). The first entries, `FunctionName="SetPlayRate"`, opened every function of `Actor`
  and `SkeletalMeshComponent` instead: the field is optional, its value needs parentheses, and
  without them it stays unset, which means "any function". Written `FunctionName=("SetPlayRate")`,
  the game refuses the functions not listed and accepts the two that are.
- Seen live: all eight employees seated in their offices in the streamed page (1920x1008, 511
  frames, no errors); an employee hidden by hand was shown again by the bridge within its
  one-minute refresh (44 s). Mean colour distance to the picture 24.2 with a bus crossing the
  street (23.3 before the employees).
- The first seating pass recorded each body as `TRASH_SkeletalMeshComponent_8`: creating the
  retargeted animations reinstanced the blueprints after the actors were spawned, and the game has
  no such component (its body is `<actor>.Body`). The animations are now made before spawning, and
  the paths are read back after the level is saved.
- Backend tests: 776 passed, 1 skipped (a real Ollama is not configured).

## The Unreal headquarters dressed with the Fab packs, and a moving street — 2026-09-15

The Owner asked for the headquarters to be carried to the end in Unreal. The Blender stand-ins that
the packs can replace are replaced, and the street moves.

- `art-source/unreal/live/rebuild_live_hq.ps1` runs one pass: Blender export for Unreal, the level
  rebuilt, the packs placed, the traffic sequence built, the stream restarted. It stops the stream
  before touching the level: rebuilding under the running game failed to replace the sky
  material, and `build_hq_scene.py` now rebuilds that material's graph when it cannot delete it.
- The Blender export for Unreal (`AMN_UNREAL_WORKSTATIONS=1`) keeps each workstation's desk and
  chair in one object and its flat monitor and mug in another (`desk_screens`), so the live scene
  can put real furniture in place of the first and keep the studio's own screens. The web plates
  are built exactly as before.
- `dress_hq_live.py` places desks and chairs (Apartment Tech Props), keyboards, mice and desk lamps
  at the eight seats, lamp posts, the bench, the bus shelter, planters and Megaplants trees at the
  street's anchors, and City Sample Vehicles in both lanes, each scaled and grounded by its measured
  bounds at the positions the web scene uses.
- `traffic_hq_live.py` drives the vehicles with a looping level sequence that plays on start.
- MetaHuman: the Creator's 29 presets are installed but not rigged, and rigging needs the Owner's
  signed-in editor; `people/employees.json` and `people/rig_employees.py` are ready for that session.
- What the passes found, and fixed. The wind-animated Megaplants trees stopped the stream (the
  capture was recreated again and again, no frame reached the page); static trees brought it back.
  Re-importing over the previous import left the skyline's facade materials without their window
  textures (flat white towers) and piled up renamed texture copies; each build now imports into its
  own `Scene_<timestamp>` folder and deletes the old ones. The pack's arm lamps read as black crosses
  at the scene's lamp heights; the posts are now slim lanterns.
- Seen in the page (headless Chrome, 15:03): the stream is live at 1920x1008 with the lit skyline,
  the lanterns, the bench and the shelter. Mean colour distance to the picture 24.6 (the page's own
  renderer measures 11.5): the street is still far too dark, the trees are bare, the shelter's red
  edges are not the picture's, and there are no people yet.
- Second pass (15:09): the scene keeps its own leafy trees (Soul: City's rendered bare and pale),
  the shelter is the model without red neon edges, and every vehicle carries two headlights and two
  red tail lights, attached so the traffic sequence carries them: a car crossing the frame lights
  the road ahead of it. Mean colour distance 23.3. Still missing: people, a lit wet road, the roof's
  brightness.

## The office furniture, the people's animations and the MetaHuman data — 2026-09-15

The Owner asked Claude to take over the Launcher. Every pack below now loads in Unreal 5.8
(`probe_pack_assets.py`).

- **MetaHuman Creator Core Data** is installed into the engine (grooms, clothing, presets, texture
  synthesis), what the Creator needs to build the employees.
- **Apartment Tech Props**: desk, desk chair, monitor, keyboard, mouse, PC tower, printer,
  speakers, headset, phone, desk lamp, cables. The Launcher downloaded it but never copied it into
  the project; it was copied from the Launcher's download without overwriting anything: the 23
  shared Deko files that differ from City Street Props' copies were left as they are.
- **25 Office Desktop Items**: laptop, headphones, lamp, documents, cups, books (with Starter Content).
- **ActorCore Sample Motions**: male and female dummies with IK rigs and retargeters, idle, walk,
  stand-to-sit and seated-talk animations.
- **Fab plugin** is installed in the engine (`Engine/Plugins/Fab`, on by default).
- ArchViz Interior (Unreal 4.27 only) was not added: the Launcher wanted to overwrite files it
  could not show, so the copy was cancelled.

## City Sample Vehicles, the bridge and the shopfronts load — 2026-09-15

The Owner added City Sample Vehicles (13 vehicles, a city bus among them), Modular Building Set and
Automotive Bridge Scene to AMNReference.

- City Sample Vehicles needs Chaos Vehicles and virtual textures: the project enables
  `ChaosVehiclesPlugin` and `r.VirtualTextures=True` (the next launch recompiles shaders once).
- `art-source/unreal/probe_pack_assets.py` loads one asset from each pack, found by name inside the
  pack: the bus (11.3 m), a car and its blueprint, the bridge arches (39 m) and lamp, shopfront
  columns, street props, a Megaplants pine (25.7 m) and Soul: City all load in 5.8.
- Vehicle Variety Pack's meshes load, but its drivable blueprints refer to UE4 classes
  (`TireConfig`, its animation blueprint) that no longer exist; the scene uses its meshes only.

## The Fab packs are in the Unreal project — 2026-09-15

The Owner added his Fab packs to AMNReference (about 40 GB): Vehicle Variety Pack, City Street
Props, Mega Street Props, Street Props Vol.1 and Vol.2, Soul: City, Megaplants, Palms, the
photography kit, turnstiles and several interiors.

- `inventory_content.py` now reads each static mesh's size from the asset registry
  (`ApproxSize`) instead of loading every mesh, which on packs this size would exhaust memory.
  It listed 7742 assets and no load errors.
- Still missing for the picture: City Sample Vehicles, Modular Building Set, Automotive Bridge
  Scene, ArchViz Interior, Streetwear Parametric Outfit 1, the Fab plugin and the MetaHuman
  Creator data. The packs that arrived hold five cars (hatchback, pickup, sports car, SUV, box
  truck), no taxi, no bus and no people.

## The Unreal headquarters, live in the page — 2026-09-13

The Owner chose to see the headquarters rendered by Unreal Engine live in the page (Pixel
Streaming). The pipe is built end to end; the Unreal level does not have the employees and the
street life yet, so the stream is only switched on by configuration.

- **Unreal streams.** The project enables Pixel Streaming 2. `art-source/unreal/live/start_live_hq.ps1`
  starts Epic's signalling server (release UE5.8-0.1.0, built with Node 22.14.0, outside the repo
  because its scripts break on spaces) and runs `/Game/HQ/HQ_Dusk` as a game through the plate
  camera, H.264 on the RX 9070. Unreal loaded the level and joined the signalling server.
- **The backend relays.** The page may only talk to its own origin, so
  `/api/v1/office/stream/signalling` carries the signalling to `STUDIO_OFFICE_STREAM_SIGNALLING_URL`
  (Owner token, constant-time), and `GET /api/v1/office/stream` says whether a stream is
  configured. Unset or not running, the relay closes and nothing takes the stream's place.
- **The page shows it.** The office viewport lays Epic's player over its own renderer, lets clicks
  through to it, hides the video while the stream is down and retries (`scene.json`
  `live_stream`). `#scene-viewport[data-stream]` says which one is on screen.
- **Seen in the page.** Headless Chrome logged in, the viewport went `live`: 1920×1008 H.264,
  794 frames decoded in the first seconds, no console errors.
- **Remote Control on this machine only.** The running level answers Remote Control's HTTP API
  on 127.0.0.1:30010, the route for placing the employees without C++ (both installed MSVC
  versions are banned by UE 5.8). Its settings are in `Config/DefaultRemoteControl.ini`; the
  unused WebSocket server, which had opened on 0.0.0.0, stays off.
- Tests: `tests/test_office_stream.py` (relay both ways, token refused, not configured, not
  running, address check), `frontend/tests/hq_stream.test.js`.

## MetaHuman Creator enabled in the Unreal project — 2026-09-13

The employees are to be real MetaHumans, so the AMNReference project now loads the MetaHuman
Creator plugin (`MetaHumanCharacter`, which brings RigLogic, hair strands, cloth and the MetaHuman
SDK with it).

- `art-source/unreal/probe_metahuman_cloud.py` checks it headless: the scripting subsystem is there
  and a MetaHuman character asset is created.
- Two things still stand between that and a finished face and body. The auto-rig and texture
  services need an Epic login, and the headless run starts a device-code login the Owner would
  have to confirm, so rigging runs in the editor he is signed in to. The Creator's optional core
  data (texture synthesis) is not installed with the engine yet.

## Every department its own office, in its own colour — 2026-09-13

The Owner pointed at S2 on the live page: the accountant and the publisher sat side by side in one
room. His rule: separate offices, one per department, each in a different colour. He chose where
Distribution goes and that Research and Fact Check part as well.

- **L3** is two rooms with a partition: Research (blue, Aris) and Fact Check (terracotta, Elena).
- **L2** is two rooms: Content (wood, Marcus) and Distribution (teal, Vera, with her desk and the
  release radar on the wall).
- **S2** on the ground floor is the Treasury alone (burgundy, Nadia, her desk in the middle, the
  sign reads "S2 TREASURY").
- Each room has a lit sign naming its department. The backend layout has the new zones
  (`factcheck_room`, `publish_desk` on floor 2, a wider `accounting_office`) and the fact-check
  stage walks to the Fact Check room; the scene's manifest and the layout are checked against each
  other by `tests/test_office_layout_matches_scene.py`. The server needs a restart to serve them.

## The headquarters in Unreal Engine 5.8 — 2026-09-13

The Owner asked for Unreal Engine. The headquarters now renders there from the Blender build
(`art-source/unreal/`); the web page still shows the Blender plates, because the Unreal still
does not yet beat them.

- **The pipeline**: `export_hq_scene.py` (Blender → `hq_scene.glb` + lights, camera and axis
  markers in `hq_scene.json`), `compose_sky_backdrop.py` (the web page's dusk sky as an image),
  `build_hq_scene.py` (level `/Game/HQ/HQ_Dusk`: meshes, the 63 scene lights, sky backdrop, sun,
  fog, orthographic plate camera, Lumen), `render_hq_still.py` (3200×1680 still), and
  `inventory_content.py`, `probe_look.py`, `probe_materials.py` for diagnosis.
- **Four faults found and fixed on the way**, each confirmed by measurement before the fix:
  glTF dropped every procedural material (233 materials arrived untextured: white walls,
  towers and road), so materials are baked into textures and skyline facades get tiling window
  textures; an orthographic camera cannot see the sky atmosphere (black sky), so the sky is a
  backdrop; the editor took its screenshot **unlit** (exposure, lights at a third, even
  `r.ExposureOffset` rendered the identical image), so `render_hq_still.py` forces the lit view;
  lit, the interior lights were several times too strong and unequal between floors, so interior
  and exterior lights and each floor are balanced separately.
- **Measured against the picture** (mean colour distance per region): first import 36.6, unlit
  with baked materials 31.5, first lit still 134.9, balanced 28.3 (L2 8, L4 13, L1 17, ground
  floor 27, L3 42). The web page measures 8.3, so it stays in use. By eye the Unreal still has
  what the web page lacks — pools of light, a glowing lobby, lit trees and street lamps — and
  still lacks people, vehicles, a lit wet road and the picture's light on the facade.

## Everyone at their own desk, facing the Owner, always at the picture's dusk — 2026-09-13

The Owner compared the office with his picture again: two employees shared one counter in S2,
some sat with their backs turned behind white blocks, the sky and colours were wrong, and buses
drove through each other. His answers: every employee has their own desk, sits facing the viewer
with the monitor to one side, and the office always has the picture's light.

- **One workstation per employee** (`hq_building.workstation`): a light desk top with a warm LED
  under its front edge, slim legs, a keyboard, a monitor turned in from one side so it never hides
  the person, a mug, and an office chair behind them. The accountant and the publisher in S2 now
  have two desks. Every seat faces the viewer (a test checks it, and that no two share a desk).
- **New people** (`build_people.py`, replacing the chibi `build_characters.py`): adult
  proportions from metaball bodies, cloth and skin materials, faces, hair, glasses, headsets and
  earrings from the Character Bible; seated poses facing the viewer for every backend state,
  standing, reacting and walking; pedestrians from the same builder.
- **Always the picture's dusk** (`scene.json` → `"light": "reference_dusk"`): the office, the sky
  and the street are lit as in the picture at any hour; the clock, the street's daily rhythm and
  the random events keep the real time, and live rain, snow and fog still fall. Live cloud cover no
  longer greys the painted sky. `"live"` restores the real sun.
- **Tall vehicles never overlap**: a bus, truck or fire engine enters only when no tall vehicle is
  in the other lane, so two of them are never drawn one over the other.
- Honest limit: without the old lit counters the rooms measure darker than the picture (plates
  alone 4.8 → 7.3), and the Owner judged the figures, cars and buses still far from the picture.
  The next step moves the rendering to Unreal Engine 5.8 (`art-source/unreal/export_hq_scene.py`,
  `build_hq_scene.py`, `render_hq_still.py`), with content packs the Owner adds from Fab.

## A sky with clouds, like the picture's — 2026-09-13

The Owner compared the office with his picture and found the sky empty: a plain gradient, with
clouds drawn only when live weather reported them.

- **Painted cloud banks**, made by `art-source/sky/paint_clouds.py` without any image generator:
  layered noise shaped into long banks with crisp edges, lit from below at dusk (warm undersides,
  blue-grey cores, as in the picture), white by day, dim at night. Three WebP layers (330 KB in
  all) are crossfaded with the time of day (`cloudLayerWeights`).
- **Live weather still rules the sky**: real cloud cover and fog grey it over, rain, snow and
  storms are drawn on top. With the server restarted the endpoint answers, and on the day this was
  made Bucharest reported "Cloudy 16°C", which is why the live sky reads grey.

## A bridge that fans, a grey tower, notes with writing — 2026-09-13

- **The bridge is cable-stayed like the picture's**: a pylon about twice as tall over the deck,
  cables leaving it along its height with the highest reaching farthest (the first try paired
  them the other way and drew a lattice), small warm deck lights, and a thin warm line up the
  pylon so it reads against the towers behind it.
- **The lift tower's stone column is a cool grey** instead of warm mauve. A sweep of lighter
  greys, closer to how light the picture's column looks, measured worse each step (tower 9.3,
  12.0, 14.7), so the darkest stays.
- **L3's pinboard notes carry lines of writing**; measured, they change no room's score.
- Live page at the picture's light: mean colour distance 8.5 → 8.3, left sky 26.6 → 24.1; plates
  alone 4.8 (the grey stone costs the tower 0.5).

## The skyline recedes, and the slogan says TOGETHER — 2026-09-13

- **The slogan panel reads all four lines.** The classic building in front of it was 8 m deep, so
  from the camera's 10° its roof and cornices rose over the panel and hid "TOGETHER"; it is now a
  shallow lit facade, as in the picture.
- **The skyline recedes into blue**: the far haze is blue instead of pink, tower windows are
  smaller and more of them are lit, and the brightest windows are warm white instead of bluish.
- **The bridge** has warm, dim cables and deck lights instead of a glowing white fan.
- Live page at the picture's light: mean colour distance 9.1 → 8.5; right-hand city 13.3 → 11.2,
  left sky 30.5 → 26.6, street 4.9 → 3.7. Plates alone 4.8 → 4.7.
- A trial of lower desks with a wooden top and clutter on the back desks measured worse in every
  room (L4 3.0 → 4.8, L3 10.1 → 12.5) and read no closer to the picture at the canvas's scale, so
  it was not kept; only lines of writing on L3's pinboard notes stay, for the next plates.

## Rooms as bright as the picture's — 2026-09-13

Once dusk stopped borrowing light from the sunlit day plates, every room read a little darker than
the picture. Interior lights are now 3.15 times their modelled energy (was 2.8).

- Plates alone at the picture's dusk: mean colour distance 5.4 → 4.8 (L4 1.7, ground floor 2.9,
  street 4.1, L1 4.4, tower 4.8, L2 5.1, L3 8.8).
- Live page: mean 10.1 → 9.1; L4 5.7 → 2.7, L2 9.2 → 6.6, ground floor 5.9 → 3.0. The largest
  gaps left are the sky (the picture has sunset clouds, drawn here only when real weather reports
  cloud) and the right-hand skyline.

## Dusk no longer looks half like day — 2026-09-13

The lift tower, the sign and the street measured far brighter live than their own night plates.
Composing the plates the way the canvas does found why: the day plates were crossfaded in
linearly with daylight, and daylight already rises while the sun is below the horizon (the sky
needs that). At the picture's dusk, with the sun 2.5° down, 30% of a sunlit render was added.

- The day plates now follow daylight to the power 2.2 (`plateDayMix`): about 7% at that dusk,
  fully there by day. The sky keeps its own curve.
- Measured on the live page: sign 12.5 → 3.9, tower 18.8 → 9.0, street 10.7 → 5.2, mean colour
  distance 10.4 → 10.1. The rooms, which the sunlit blend had been lifting, now read slightly
  darker than the picture; the near-pavement darkening planned for that same excess is dropped.

## Street life in the evening light, a lit tower, lush trees — 2026-09-13

- **Cars, buses and pedestrians take the light of the hour.** They are rendered under neutral
  light, so at dusk a white bus glowed against the dark street. Their sheets are now multiplied
  by the outdoor light (untouched by day, dim cool blue at dusk and night, greyer under cloud) and
  cached until that light changes; lamps, light bars and the courier inside the building are not
  tinted. Street lamps also leave long warm streaks on the road after dark.
- **The lift tower** has its narrow side bay lit like the picture's, frames in steel blue and
  larger stone blocks; its shaft glows less, so it no longer outshines the picture.
- **Trees** have lighter, more translucent crowns around a dark green core and stronger warm
  uplights; the bridge's cables are fine lines instead of a glowing tent; L3's spot cones are
  narrower again, since with bloom they drew discs brighter than the picture.
- **Measured on the live page at the picture's light**: mean colour distance 11.4 → 10.4; L3
  17.0 → 10.3, street 13.8 → 10.7, L4 3.4, L1 4.9, ground floor 4.8. On the plates alone the tower
  is now 4.8, but live it still measures 18.8: something drawn over the plates brightens it, and
  that is the next thing to find.

## Floors, street and sky measured against the picture — 2026-09-13

Region by region against the Owner's picture, the building still had heavy dark bands between
floors, a pale warm road with a glowing zebra, flat skies and racks that read as green noise.

- **The dark band over every floor was a compositing fault**, not the model: each plate layer is
  rendered with the other layers invisible, and the slab's body sat in the shell layer the canvas
  draws after the rooms, so its whole top face was painted over the floors. The slab body now
  lives with the rooms; the shell keeps its navy face with a warm LED line, as in the picture.
  The lift tower's floor bands are shallow, so the lit shaft shows above them.
- **The street is dark, cool and matte where it should be**: plain grey road paint instead of
  self-lit stripes, asphalt that no longer mirrors the lit facade at the camera's grazing angle,
  matte paving (it had mirrored the S2 and S3 labels), a warm stone terrace, softer street lamps.
- **The sky is not level at dusk**: the camera looks north, so the sun sets on the left; a warm
  afterglow hugs that horizon and a lighter blue sits high across from it, as in the picture.
- **Rooms**: server racks are dark units with slot lines and steady lamps (the canvas still adds
  the blinking that follows the studio's work), the S3 vending machine has shelves of cans,
  spot cones on the back walls are wide and soft, pendant lamps are big enough to read, console
  tops no longer glow white, and L3 and L4 are as bright as the picture's.
- **Measured on the live page at the picture's light**: mean colour distance 13.0 → 11.4; L4
  11.5 → 3.5, L2 15.7 → 7.5, L1 11.3 → 5.0, ground floor 6.2 → 4.4, street 19.4 → 13.8.
  Regressions still open: L3 (13.5 → 17.0) and the lift tower (13.9 → 17.4) now come out
  brighter than the picture once bloom is added.

## Cars that read as cars — 2026-09-13

Next to the picture's rounded SUVs and sedans, the street's cars still looked like stacked boxes.

- **Bodies are lofted from side profiles**: bonnet, raked windscreen, roof and boot for the
  sedan, coupe, hatchback, SUV, EV, taxi and police car, with the glasshouse leaning in and the
  plan rounded at the bumpers; wheel arches, door seams, handles and mirrors on both flanks.
- **Lamps wrap round the corners**, so a car seen side-on shows its headlights and red tail
  lamps as the picture's cars do. The render records where each visible lamp sits and the canvas
  blooms exactly there after dark, with a faint horizontal streak on headlights.
- **Windows stay dusk-dark**: the key and fill lights no longer mirror as white squares on glass
  and bonnets; light bars on police cars and ambulances keep their red and blue.

## The headquarters, rebuilt from the Owner's picture — 2026-09-13

The Owner asked for the office to be redone so it looks like his headquarters picture, with the
studio called AMN-AI (the picture said "AMH-AI"), made with Blender or Unreal and without his
image-generation credits. The pixel-art office is gone; what replaces it is described in
`HQ_LIVING_OFFICE.md`.

- **The building** is a Cycles scene built from the picture's own measurements: sign, four
  upper floors with their labels, the audio booth and render bay, S1 Infra, the lobby with its
  stairs, S2 Operations, S3 AI Space and the glass lift tower. Plates come in layers (night and
  day) so employees sit behind their consoles and pedestrians walk behind the bollards. A
  per-region comparison with the picture went from a colour distance of 70.6 on the first
  render to 14.4 on the live page at the same light.
- **The employees** are eight chibi characters rendered from their Character Bibles, each with
  typing, thinking, idle, talking, paused, error, standing, reacting and walking frames. What
  plays is the backend state; the render bay's screen shows the video editor's real state
  instead of the picture's "RENDER 91%".
- **The city lives**: right-hand traffic from nineteen rendered vehicles (buses carrying
  AMN-AI, Nexus Curiosity and Inside The Nexus ads, taxis, vans, trucks, bicycles, scooters,
  motorcycles, and emergency vehicles with lights and sirens), pedestrians following the daily
  rhythm, a bus that serves the shelter, traffic that stops for people on the zebra.
- **Time and weather are real**: the sun's elevation for Bucharest's date and time decides day,
  dusk and night; the weather comes from a new endpoint, `GET /api/v1/office/weather`, and is not
  drawn at all when it is unknown.
- **Random events** are configuration (`world_events.json`): rarity, weight, cooldown,
  concurrency, weather and time of day, duration, priority and reaction radius — from airliners
  and crossings to fireworks and a very rare UFO. A seed replays a day exactly.
- **The interface speaks English**: the office chrome, every dialog, the ledger, settings,
  YouTube connections and the live window.
- The office layout now matches the rendered building, and a test keeps them in step.

## Watching the film: stripes, a discarded shot plan, and a disclosure it never carried — 2026-09-13

The Owner watched *How ATLAS Caught the Higgs Boson in Real Time* and named what was wrong:
text in the picture that should not be there, a weak voice, pictures that were poor and
sometimes made no sense — and he asked whether it was because the studio buys the cheapest.
Mostly it was not. The film was watched frame by frame and every fault traced to its cause.

**What the film is.** 0–4s old theory pages whose printed words are gibberish; 4–7s a light
net, two spheres colliding, a fully white frame; 7–10s a particle burst; 10–14s ATLAS drawn as
a futuristic tower in a canyon (it is a horizontal cylinder in a cavern); 14–19s abstract neon
spirals; **19–30s eleven seconds of vertical beige stripes** — the film's payoff. Quality
control scored it 1.0, and the Director approved it having seen three frames.

**Why.**
- The video editor wrote a 14,036-character shot plan — lens, light direction and colour,
  composition — and **the studio threw all of it away** because two `audio_intent` lines ran
  past 200 characters. One field failed validation, so the whole pack did, and every shot was
  rebuilt from the writer's one-line description, repeated into subject, action, environment
  and lighting.
- His visual bible went the same way for describing the palette, the light and the camera as
  objects instead of sentences; the film was shot on an empty default look.
- The writer's line for the payoff asked for *"a text overlay appears: 'Top quark or W
  boson?'"*, and the prompt passed it to the image model, which drew stripes.
- Quality control measures the file, never the picture; the Director was shown frames at 20,
  50 and 80 per cent, so two of five scenes were never seen.
- The cheap choices are real but secondary: in TEST the motion model was `seedance2_mini`
  (catalogue quality 0.6, against 0.8 for `seedance2`), and the narration was ElevenLabs'
  lowest-latency `eleven_flash_v2` on the free plan.

**What changed.**
- A model's answer is fitted to the schema instead of refused for its shape: an overlong field
  is shortened, a structured value is said as a sentence, and a shot that cannot be placed
  costs only itself. Kael's real plan now keeps all five shots.
- Pictures are never asked to draw writing: text requests are stripped from every positive
  field, and both the writer's and the editor's briefs say so. Text belongs to the edit.
- A composed prompt says each thing once.
- Every still is measured when it is made — squeezed along each axis and compared with itself
  by SSIM, with the encoder the studio already has. Real stills measured 0.18–0.76 (a plain sky
  0.89/0.91); the ATLAS stripes 0.961. Above 0.94 on one axis is stripes or bands, on both a
  blank field. A broken still is generated once more, told plainly what a picture is; still
  broken, it is recorded and **quality control fails the film** and names the scene.
- The Director is shown one frame from the middle of every scene, and told that a blank field,
  stripes, noise or garbled writing in any of them is a REJECT.

**The description.** The Owner's rule: every film says it was made with generative AI by the
AMN-AI studio pipeline, links the studio's site, and credits INSIDE THE NEXUS. It is added on
every road to YouTube — the day's publish stage, the one-click route and the Owner's own intent
— once, inside YouTube's 5,000 characters, whatever the Publisher wrote. The site
(`STUDIO_AI_DISCLOSURE_URL`, empty until it exists) and the creator channel
(`STUDIO_CREATOR_CHANNEL_TITLE=INSIDE THE NEXUS`) are configuration; the link to the channel is
read from its stored connection (`@insidethenexusai`), not written in code. The two films
already on the channel keep their old descriptions: the upload adapter cannot edit a published
video, and editing one is the Owner's call.

**The cost, from the credits.** The studio had never written a vendor balance down, so the
ATLAS render's "before" cannot be proven after the fact, and Runway's usage report does not yet
include the day. What is exact: Runway holds **1,662 credits** now; ElevenLabs counted the
render's narration **1,411 → 1,608 characters (197)**, the flash model billing half a credit
per character. From now on the media stage reads each vendor's balance immediately before and
after every render and writes the difference on the render and in the event stream, with the
dollar value of Runway credits at the Owner's recorded rate. The 30 credits on 2026-09-11 and
the six `gemini_2.5_flash` generations on the same key are not made by any code in the studio.

`uv run pytest -q` — **735 passed, 1 skipped**, including tests built from the ATLAS film's own failures. `ruff`, `mypy`, `scripts/check_docs.py` clean.

## The studio published a new film end to end, and the office showed nobody working — 2026-09-13

The first complete cycle under the corrected rules ran on the evening of 2026-09-12 and went
all the way: the Director chose *How CERN's ATLAS Measured a Higgs Boson in Real Time*, the
writer and she worked the story for seven exchanges, she passed and approved it herself, the
video editor wrote the visual bible and five shot prompts, and the media stage produced five
Runway stills, five ElevenLabs narration clips and two Runway motion clips (the TEST limit),
cut them into a 30.2-second film, QC scored it 1.0, the Director watched it and approved it,
and the Publisher uploaded it privately to Main Channel A as `sDEtt-WQGh8`. Media stage start
to publication: seven and a half minutes.

While that happened, the Owner watched the office and asked why it was stuck at Lyra. It was
not stuck. Her narration review was the last model call (THINKING, then IDLE at 20:51:30), and
for the next seven minutes her voice was recorded, the stills and shots were generated and the
film was cut — in her name and Kael's — while both showed IDLE and the ledger said nothing.
An employee's state changed only when she thought with a model; the paid part of the day ran
beside it. The office already draws `WORKING` as typing and the live window already counts it
as busy. The backend simply never said it.

- `mark_working` / `mark_idle` / `at_work` in `agents/services.py`: the employee holding a
  role is WORKING for exactly as long as a production step runs, with a detail the ledger can
  read (*vocea scenei 3*, *mișcarea scenei 2*, *montajul filmului*), and IDLE after — also when
  the vendor fails. Best effort by design: a status line that cannot be written is logged, and a
  paid render never dies because of it.
- The assembler wraps each paid step in the employee who owns it: stills, motion and the cut
  are the video editor's, narration is the voice artist's. Placeholders mark nobody.
- The stale-state sweeper no longer flips a WORKING employee to IDLE: production has no model
  run behind it by nature, and a model task may run beside it.
- The ledger read every state that was not THINKING as *a terminat* (finished) — so WORKING
  would have read "finished" at the moment work began. It reads *lucrează*, with the detail.

**Two things the cycle's books showed, recorded and not papered over.** The render's recorded
cost is 0.316 USD and it is incomplete. The ElevenLabs narration has no cost row at all:
`eleven_flash_v2` carries no price in the catalogue, so the Accountant correctly counts the
scene as unpriced rather than free — the gap is the catalogue, not the arithmetic. And both
motion shots were priced at `seedance2_mini`'s documented 0.02 USD a second, because Runway
named no credits on the prompt-only path; the render's own summary therefore says 0 USD for
motion while the books say 0.216. No price was written into code to fill either gap.

`uv run pytest -q` — **727 passed, 1 skipped**. `npm test` — **87 passed**, including the ledger's WORKING
case. `ruff`, `mypy` clean.

## Time to fix it — 2026-09-12

The run finished without crashing for the first time since the room opened, and the story was
refused at the wall anyway: five drafts, everything passing except one check, and then the
budget ran out. The Owner's answer was the right one — *it should have been given the time to
clarify and correct the problem.*

**The check was wrong.** `ending_answers_the_hook` compares the content words of the hook with
those of the payoff onward. The hook: *"This telescope was supposed to work 14 months. It
guarded Earth for over a decade instead."* The ending: *"It spent eleven years watching for
things that burn in our sky — and ended as one of them."* That ending answers that hook
exactly, and shares no word with it. Four refusals for writing it well. Whether an ending
answers its opening is a question about meaning, and nothing that counts words can decide it:
it is now an **advisory** check — still measured, still recorded, passed to the Director as a
flag to look at, and no longer able to refuse a script by itself.

**And the budget was counting the wrong thing.** It counted every rewrite of a topic, ever —
including eleven rounds caused by the studio's own faults in earlier runs. That story began
this run at exchange twelve of sixteen and hit the wall five drafts later while it was still
getting better. A budget is for a conversation going in circles, not for one doing its work:
it counts **rounds that changed nothing**, and a draft better than any before it reopens the
room. Progress is measured the only way the studio can measure it alone — how many refusing
checks are left.

**The room is twenty exchanges**, the Owner's number, and the twentieth is a decision rather
than another request. Which exchange she is in and how many went nowhere are now two separate
numbers; they had been the same one by mistake.

`uv run pytest -q` — **726 passed, 1 skipped**. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## The write that could not wait — 2026-09-12

Two watched runs died on the same statement: `UPDATE agent SET runtime_state`, "database is
locked", once in the script stage and once in `post_run`. Raising `busy_timeout` from ten
seconds to thirty did not help, which was the clue.

Measured on a scratch database: connection A opens a deferred transaction and reads; B writes
and commits and closes; A then writes and is refused **in 0.00 seconds**, with the lock free
and nobody to wait for. SQLite's deferred `BEGIN` takes a read snapshot at the first SELECT,
and no amount of waiting makes an old snapshot writable. `busy_timeout` was never going to
matter.

`BEGIN IMMEDIATE` everywhere was the obvious cure and is wrong here. The studio opens a
writing session inside an open reading session in many places — the economy suite is full of
them — and there the inner write waits on the outer read's own lock: **32.8 seconds, then the
same error**. Under that setting twenty-three tests failed, most of them the books.

So the lock is taken per transaction, by the transactions that know they will write:
`lock_for_write(session)` as the first statement, a no-op UPDATE of the policy row. From then
on the transaction is a writer, its later writes cannot be refused, and any other writer waits
its turn — which `busy_timeout` does cover. It is called in both of `run_agent_task`'s write
blocks, which is where the studio failed twice; both close before the model is called, so the
lock is held for milliseconds.

The measurements are in the code, so the next person to reach for `BEGIN IMMEDIATE` does not
have to spend the afternoon finding out.

`uv run pytest -q` — **723 passed, 1 skipped**, including one that reproduces the refusal and
shows the line that prevents it. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## A reviewer who cannot see the conversation cannot finish it — 2026-09-12

The open writers' room ran for the first time: ten exchanges on one story inside a single run,
and the story tightened as it went — 42.9s, 39.1, 31.4, 29.5, 25.3, 37.6, 36.8, 38.3, 31.0.
From the second exchange on, every computed check passed. The Director said REVISE nine times
anyway, and then the run died on `database is locked` and the studio went into safe mode.

**She was asked in a vacuum.** Each reading got the script and nothing else: no sense of which
exchange this was, no memory of what she had asked for, no moment where she had to decide. Ask
a good critic "what is wrong with this" nine times and you get nine answers, because there is
always something. She now sees the exchange number and the budget, the notes she gave last
time — with the instruction that a note the writer has acted on is settled, and that the
question is whether the film is good enough to publish, not whether it is perfect — and at the
last exchange she is told to answer PASS or REJECT. If she asks for another rewrite when there
will be no rewrite, the studio records that as REJECT and says why: a REVISE with nothing
following it is a refusal that will not say its name. Her authority is untouched; what she
refuses stays refused, and is only named.

**And the lock.** `busy_timeout` was ten seconds. A stage that spends four minutes talking to
models writes dozens of small transactions while the outbox dispatcher writes beside it once a
second and a WAL checkpoint takes the write lock for as long as it needs; ten seconds ran out
while updating one agent's runtime state. It is thirty.

`BEGIN IMMEDIATE` was tried first and reverted: it takes the write lock up front, which turns
contention into waiting rather than failing — but the studio opens a writing session inside an
open reading session in a dozen places, and under IMMEDIATE the inner write waits on the outer
read's own lock. Measured on a scratch database: **32.8 seconds, then the same "database is
locked" it was meant to cure.** The comment in `db.py` now says so, with the measurement, so
the next person to have the idea does not have to spend the afternoon on it.

`uv run pytest -q` — **722 passed, 1 skipped**. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## The writers' room stays open — 2026-09-12

Four watched cycles ended the same way: the studio wrote two drafts, the second was one note
from passing, and the day closed with nothing made. The Owner settled what the rule should be:
*"we have plenty of tokens. The day does not close after two attempts. We can have ten or
twenty exchanges until we have a film. The day closes when the short is published."*

- `MAX_REVISIONS` was **2**, on the reasoning that a third attempt on the same evidence
  produces a third version of the same weakness. That reasoning was about cost, and cost is not
  the constraint: rewriting text is the cheapest thing the studio does, while a render is where
  the money goes. It is **15** — high enough to be a real conversation, finite enough that a
  story the evidence cannot support is eventually let go of.
- The script stage no longer writes exactly two drafts. The writer and the Director work the
  story until she approves it, until the review refuses it, or until `MAX_SCRIPT_EXCHANGES`
  (16) closes the room — and on her approval the storyboard is made in the same run, so the
  film reaches the camera the same day.
- What the Owner reads says how long the conversation took: *"5 scenarii scrise în 5 schimburi,
  1 aprobate de Director, 1 storyboard-uri generate."*

`uv run pytest -q` — **720 passed, 1 skipped**. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## Does the film close, or is there a scene wearing the label — 2026-09-12

The revision loop converged for the first time: *How NASA Tracks Asteroids That Could Hit
Earth*, draft one refused on two counts, draft two — with the draft it was revising in front of
it — fixed the causal progression and kept its length. One check still refused it, twice, and
the check was wrong.

`has_ending` asked whether any scene carried the label `ENDING` or `CTA`. The draft ended on
*"after ten years defending the planet, it became a streak of fire in the sky"*, declared that
ending, and carried a CTA of its own — but the writer had spent all five scenes the brief
allows on HOOK, SETUP, DEVELOPMENT, EVIDENCE and PAYOFF, and delivered the close inside the
last of them. The film closed; only the label was missing.

- The check now asks whether the film ends: a labelled `ENDING`/`CTA` scene, **or** a declared
  ending that the last scene actually speaks. A film that just stops still fails, and so does
  one whose ending is written in the fields but never said out loud.
- The brief says the missing half plainly: the last scene closes the film, carries the ending
  and the CTA, and is labelled `ENDING` or `CTA` — do not finish on `EVIDENCE` or `PAYOFF`.

`uv run pytest -q` — **719 passed, 1 skipped**. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## A revision revises the draft — 2026-09-12

Three watched cycles in a row, on the same topic, showed the writer getting worse instead of
better. Draft two of *How NASA Keeps a Space Telescope Alive With Frozen Fuel* passed every
computed check at 39.5 seconds; the Director sent it back on taste alone, with surgical notes —
cut the second line of scene 2, tighten scene 5 to end on the mirror, fix a generic CTA, and
resolve a real topic drift she had caught (the thesis promises finite fuel, the script delivers
the sunshield). Draft three came back at 46.8 seconds with no ending at all.

The cause was in the prompt: the notes travelled on their own, followed by "write the story
again from the beginning". The writer never saw the draft he was revising. A note about scene 5
cannot be obeyed by someone who has to reinvent scene 5 first, so every revision re-rolled the
story and lost whatever had been working — and after two of those the revision budget refused
the topic, for a fault that was ours.

- `previous_draft` reads the newest draft of the topic back — title, hook, ending, CTA, and
  every scene with its purpose, narration, visual and claims.
- The revision prompt now carries it, inside the same inert boundary any other data gets, then
  the notes, then the instruction that changed: **revise this script, keep what works, change
  only what the notes name, and do not reinvent the story from zero.**
- A first draft is handed no previous one, and says so.

`uv run pytest -q` — **717 passed, 1 skipped**. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## The target is a target, not a knife — 2026-09-12

The corrected brief went out and the writer still lost a story to the duration check: 103
words, five scenes, 41.0 seconds against a 39-second ceiling. Two faults behind one refusal.

**The brief and the check were still not reading the same number.** `expected_seconds` charges
`SCENE_BEAT_SECONDS` for every scene change — the breath between shots — while the budget
priced the narration in words alone. So the brief promised a ceiling about five words looser
than the one applied, and the writer, obeying it, was refused for the difference. The budget
now settles the scene count first and prices the words against the seconds that are left.

**And the check was too strict to be right.** The Owner settled it: *"it is fine if it goes
over by a few words, not all videos are the same."* The tolerance was 0.3; it is 0.5, with the
format's own limit (`MAX_SHORT_SECONDS`, 60s) as the outer wall a tolerance may not reach over.
A 30-second target now accepts 15–45 seconds. The 41-second draft passes. Two hundred words in
a thirty-second film — the failure the check was written for, a film that ends before its
words — still does not. The brief says the same thing in the same voice: aim here, a few words
over is fine, past this it is no longer a short.

`uv run pytest -q` — **715 passed, 1 skipped**. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## The Director approves her own scripts, and the brief can be satisfied — 2026-09-12

A watched cycle produced a new film for the first time: the Director chose *How the James Webb
Space Telescope Sees the First Galaxies* over the asteroid topic on 16 supported claims, the
writer drafted it, and the story review sent it back. Twice. Then the studio stopped — and
what stopped it was four separate faults in one chain.

**The brief asked for a film its own budget could not pay for.** The writer was told "30
seconds, about 78 words" and, in the same breath, offered up to twelve scenes across eight
story purposes under a five-line beat table. Seventy-eight words over seven scenes is eleven
words a scene, which nobody writes; he wrote twenty-one, twice (57.5s, then 41.2s against a
39s ceiling). The arithmetic now lives in `narration_budget` and the brief states it: at 30
seconds, **5 scenes of 12–19 words**, 78 words in total, refused over 101 — and it says the
count is on the spoken text, not on the `duration_seconds` numbers the model fills in. The
beat table is expressed as fractions of the film's own length, so it reproduces the historic
0–3 / 3–8 / 8–18 / 18–26 / 26–30 table at 30 seconds and stays true at any other. The refusal
now names the ceiling and the target too, because "too long" is not a brief.

**The revision budget never fired.** `MAX_REVISIONS` counted the reviews of one draft row while
every rewrite wrote a new row, so each attempt was the first revision of a brand-new draft and
nothing ever escalated. It counts the story now — the topic behind the drafts.

**The studio had written itself into a corner.** The script stage skipped a topic the moment
any draft existed for it, while the topic still counted as in production, so a story sent back
twice could neither be rewritten nor got past: nothing new could be selected, and nothing would
write a third draft. `script_work` replaces that test — a topic owes work while its newest
draft has no storyboard and the review sent it back, and the reading's notes travel with the
rewrite. A REJECTED story is not retried here; its budget is spent, the letters have gone to
the departments, and it stops holding the studio up.

**Approval was in the Owner's inbox.** A script the Director had read and passed still waited
for him to press a button — "I don't have to approve the new scripts, the Director does", as he
put it. She approves what she passed, in the same decision, and the record carries `approved_by`
and the reason. The factual gate is still re-checked at approval, so she cannot approve a script
whose claim stopped being supported while it was written. The Owner keeps the same API route and
can still refuse what she allowed.

`uv run pytest -q` — **711 passed, 1 skipped**. Thirteen new checks across
`tests/test_editorial_quality.py`. `ruff`, `mypy`, `scripts/check_docs.py` clean.

One consequence worth stating: the James Webb topic has already spent its revision budget, so
under the corrected rule its next reading refuses it and the selection moves to the next topic
with verified claims. The corrected brief gets its first run on a story that has not been
refused yet, which is the honest way round.


## A film is not a file — 2026-09-12

The studio published its first video: *The Universe's Missing Pieces: Why the LHC Upgrade
Matters*, private, on Main Channel A. Watching the ledger, the Owner asked the right question
about what was left behind in the queue — and the answer was that the same film would have
gone out three more times.

One storyboard had been rendered four times during the day: a retake, a re-edit, another pass.
Each render is a new `MediaAsset` with a new id, each one passed quality control, and the
duplicate gate compared `media_asset_id` — the **file**. So three QC-passed files, all of the
same film, sat eligible on every gate. One per daily run, the channel would have received the
same video four days running. Proven on a copy of the live database before the fix: all three
returned `eligible: True`.

- **Identity is the film, not the file.** `film_identity` walks asset → render job →
  storyboard → script, and `published_films` keys what a channel already carries by both the
  script and the storyboard. A candidate matches on whichever of the two it can establish;
  when provenance cannot be walked at all the answer is "unknown", never "new".
- **The duplicate gate refuses a second render** of a script the channel already carries, and
  says which video it already has: *this film is already on the channel as “…” (remote_id: …);
  this asset is another render of the same script*.
- **Cross-posting is untouched.** The gate is per channel, so one film may go to two channels;
  what it may not do is go to the same channel twice.
- **A failed upload blocks nothing.** Only live publications count, so a retry after a refused
  upload still works.
- **The publish stage offers each film once.** The queue is collapsed to the newest render per
  film, and a film the channel already carries is not a candidate at all — so the stage walks
  on to the next real film instead of stopping on a refusal.
- Gate 4 (factual integrity) now uses the same provenance walk instead of its own copy.

Five tests in `tests/test_phase6_publishing.py` describe it: a retake refused and naming the
earlier video, a second storyboard from one script still the same film, the same film allowed
on a second channel, a failed publication not blocking, and the provenance walk itself.

`uv run pytest -q` — **698 passed, 1 skipped**. `ruff`, `mypy`, `scripts/check_docs.py` clean.


## An employee may think with more than one model — 2026-09-12

Every agent ran on exactly one model, and that single slot could not express the thing the
Owner wanted: a Director who proposes a strategic decision and then has it challenged before
she commits, a researcher who falls back when a model is unavailable, a hard question answered
independently by two models and reconciled by the employee.

So three slots and a strategy, and one rule above all of it: **no model is named in the
studio's logic**. A model in a slot is a configuration value the Owner can replace from
Settings tomorrow without a line of code changing, and a test scans the whole backend and
fails if a configured model name appears anywhere outside documentation (migration 0034).

- **Three slots per employee**, from the registry the primary already came from — no second
  registry, no second connector, no second configuration screen. Each slot is checked the way
  the primary always was: the model must exist, be available, and satisfy what the role
  requires, because a fallback onto a model that cannot do the job is not a fallback.
- **Five strategies.** SINGLE stays the normal way work is done. FALLBACK takes over only when
  the first answer does not exist, and never invents one. REVIEW has the second model look for
  what is wrong and the first decide. DEBATE asks a third model only when the two materially
  disagree. PARALLEL synthesises independent answers.
- **Extra models are not spent on routine work.** The agent's own policy and the importance
  the caller declares decide, and the reason is recorded in words: "this was strategic, at or
  above the threshold" is auditable, "a second model was called" is not.
- **The advisers advise; the employee decides.** In REVIEW, DEBATE and PARALLEL the answer the
  caller acts on is always a run on the employee's own model, with the other models' words in
  its prompt. A critic cannot publish, command a department or change a strategy, because the
  only thing it produces is text the primary model reads — and it is told so.
- **A review that could not be done is said so.** No fabricated critique: the collaboration
  closes as REVIEW_INCOMPLETE, the answer still stands, and the Director's loop drops that
  decision's confidence to low and writes why.
- **Traceability.** Each participating call stays an ordinary run with its own model and
  tokens; `llm_collaboration` joins them with the part each played, the disagreement and the
  final model. Changing a slot today cannot rewrite what yesterday was answered by.
- **The Owner's allocation is a file he can edit** (`config/workforce_seed.json`): the
  Director on her primary with a strategic critic, everyone else single. It is applied once
  per employee, at the first model sync that learns which models exist, and never over an
  existing assignment — otherwise the next sync would quietly undo a choice made in Settings.
  `scripts/apply_llm_allocation.py --force` applies it when the file is a new instruction.
- Tests: `tests/test_multi_llm.py`, the twenty-two the Owner asked for, with stand-in model
  names so no test can pass because a name looks familiar. 693 pass.
- The report is in `MULTI_LLM.md`.

## The Director runs a company, not a video — 2026-09-12

Every part of this studio was measured and no part was managed. The Director chose the day's
topic, read her inbox and watched the finished film; nobody asked where the company stood,
what was preventing growth, which department was holding up the ones after it, whether an
agent had been idle for a week, or whether last month's strategic bet had worked. A snapshot
said "10 000 views" and nothing said whether that was good.

Nothing here is a second management system. The Director is the same agent with the same role
and the same model, given a new task; assignments go through the existing mailbox, the loop
runs as a standard job on the existing scheduler, idle agents and dead letters come from
`measure_workforce`, weight changes stay `DirectorRecommendation` with its own database
constraints, and the panel is the panel that was already there (migration 0033).

- **The company has a readable state.** Environment, data maturity, each channel with the last
  seven days against the seven before them, the pipeline stage by stage with what is in flight
  and where the bottleneck is, agents with their failure rates, the ordered backlog with a
  reason per place, open decisions, anomalies, and what limits growth per channel. All of it
  from stored rows: a channel with nothing measured reports nothing, not zero.
- **Performance is normalised.** Views per hour beside the totals, subscriber conversion,
  engagement, cost and production minutes on the same row, cost per thousand views. A verdict
  needs a baseline of at least three measured films, twenty-four hours of age and a rate;
  without them the answer is INSUFFICIENT_DATA, which is a real answer.
- **A diagnosis names a department.** Click-through separates "nobody chose it" from "they
  chose it and left", and conversion separates "they watched and did not subscribe" from
  both. Four causes, four assignments. One film never condemns a category, and nothing in the
  studio can permanently ban a topic.
- **The loop's output is action.** At most three assignments per pass, each a letter with the
  observation, the evidence, the interpretation, the confidence, the decision and the review
  condition. A matter already under an open decision is not raised again. A matter assigned
  three times goes to the Owner instead of round a fourth time. STOP and SCALE are the
  Owner's, always.
- **A decision is a row with a review date.** The database refuses a decision nobody will
  check. When the films it was waiting for have been published, it comes back as a matter and
  is closed with what actually happened — so strategy itself can be learned from.
- **Idle agents get real work, and only when nothing is in flight.** With films waiting to be
  finished, finishing them is the work; inventing a task then is the definition of busywork.
- Tests: `tests/test_director_command.py`, the thirty the Owner asked for. Verified against a
  copy of the live database: it found the studio's real bottleneck — six films through quality
  control and none published — and reordered the backlog by evidence in hand. 674 pass.
- The full report is in `DIRECTOR_COMMAND.md`.

## The idea has to argue for itself — 2026-09-12

The Owner's principle, in the order it has to be enforced: a good idea, then a good story,
then a good script, then a good prompt, and only then a video. A powerful video model cannot
rescue a weak idea. The studio could research a fact, verify it, write narration that cited
it, and produce a film nobody would watch, because nothing in the pipeline ever asked *why
this video should exist* — and what reached the video model was the single line the writer had
typed under `visual`, at about 2.60 USD a shot.

Nothing here is a second pipeline. The research agent, the trusted-source registry, the
independent fact checker, the script writer, the Owner's script approval, the Director's
selection and her final viewing, the production stages and the model routing are all the ones
that existed; each gained what it was missing (migration 0032).

- **An idea now carries a thesis**: the core fact, why it matters, why now, the payoff, a
  hook, an ending, a call to action that belongs to this story, the risk and the length. It is
  scored on twelve editorial dimensions that are **weighted, not averaged** — hook, payoff,
  story and fact confidence decide — so a beautiful topic with nothing to say stops winning.
  An idea that fails the editorial rules is kept with its reasons instead of dropped.
- **A script now has a shape**: the writer is briefed on the thirty-second structure, on
  causal progression instead of "and then", on showing rather than narrating twice, and on the
  studio's own speaking rate, so thirty seconds of film no longer carries sixty seconds of
  words. Every scene declares the part it plays, and the story — one message, the takeaway,
  the hook, the ending, the CTA and its kind — is stored with the draft.
- **The story is read before anything is bought** (`story_review`). The computed checks ask
  whether the film has a hook that is not "did you know", a purpose and an attribution behind
  every scene, a payoff in the second half that answers the hook, an ending, a closing
  question about *this* story, and narration that fits the length. The Director says where
  interest would collapse, second by second. A script that is sent back is rewritten once with
  the notes. This is the first gate in this studio that runs **before** the money.
- **The prompt carries the film**: one master visual bible (style, world, palette, light,
  camera language, continuity rules, what to avoid) and a full package per shot — subject,
  action, environment, camera, lighting, composition, motion, emotion, background, continuity
  with the shot before it, audio intent, transition, negatives and story purpose. It may not
  invent a number the story never stated, may not make the film more spectacular than the
  story, and is capped in length because a thousand meaningless words bury the fields that
  matter. `visual_prompt` still holds what is sent, so the render path is untouched.
- **Prompt quality is constant across environments.** The prompt agent is never told which
  environment it is in; TEST saves money by choosing a cheaper model, never by thinking less.
- **The loop closes**: the Director's notes about the pictures become prompt lessons the next
  film's prompt agent reads, and the weekly review compares what the studio predicted about a
  film with what the audience actually did.
- Tests: `tests/test_editorial_quality.py`, the twenty-one the Owner asked for. Two real
  defects surfaced while writing them: the prompt agent was not checking the story gate, and a
  second prompt pass read its own output as the writer's line. Both fixed. 645 pass.
- The full report is in `EDITORIAL_PIPELINE.md`.

## Two environments, and a model that has to earn its place — 2026-09-12

The Owner found in one search what the studio's own steward had not: models at 0.05-0.12 USD
a second where the studio was paying 0.43. *"Seedance face video sa fie de 3 ori mai scump,
merita? Este agent, are un rol! Asta trebuie sa faca!"* And before that, the cost of not
knowing which kind of work was happening: an experiment bought the same eight shots a film
does, 21.08 USD in an afternoon.

Both are the same missing distinction. The studio now knows **which environment it is in**,
and a model now has **a standing it has to earn**.

- **The environment is the studio's own state** (migration 0031, `owner_policy.environment`,
  `POST /owner/environment`): TEST or PRODUCTION, changed by the Owner through the same
  versioned, idempotent command that stops autonomy, never by a query parameter a page could
  set. The top bar says which it is, always, and the button beside the autonomy switch
  changes it.
- **One router, two policies** (`choose_model` in `production_policy.py`). Business logic
  states a requirement — the task, the quality the scene needs, its length, what it may
  cost — and never a model name. In **TEST** the answer is the cheapest compatible model and
  the quality ranking is not consulted; its fallback is the next cheapest, never the best;
  and a shot above `STUDIO_TEST_MAX_COST_PER_GENERATION_USD` or
  `STUDIO_TEST_MAX_COST_PER_SECOND_USD` is refused rather than quietly bought. In
  **PRODUCTION** the answer is the least expensive model that reliably reaches the quality
  the scene requires, and the decision says what it did not buy and at what multiple — the
  Owner's marginal question, answered in writing.
- **The scene's part in the film sets the tier**, not the model's price: HOOK and ENDING are
  asked for more than the middle (`scene_role`, `SCENE_ROLE_TIERS`, `scene_tier`), because
  the first shot decides whether anyone watches and the last whether anyone comments.
- **A model has a life** (`app/integrations/lifecycle.py`): DISCOVERED → QUARANTINE →
  BENCHMARKING → CANDIDATE → PRODUCTION → PREFERRED, and DEPRECATED. A model the vendor
  exposed today is taken into the catalogue and kept **out of production** until its own
  results say otherwise; a model whose contract could not be read waits in quarantine rather
  than being tried on a film; a model the Owner's deny list names
  (`STUDIO_MODEL_DENY_LIST`) is retired on sight and chosen in neither environment.
- **The studio learns from its own results** (`model_outcome`): every generation is recorded
  with its environment and kind, its scene category, what it cost and whether it was
  accepted first time. A cheap functional test is recorded and **never** allowed to teach the
  studio about a model's picture; a test of a model that is not yet admitted **is** that
  model's benchmark, which is how a new model earns its way in. The daily review
  (`MODEL_REVIEW`, a standing job) promotes and demotes on that evidence and generates
  nothing, so it costs nothing.
- **A price keeps its date.** CONFIGURED, ESTIMATED and BILLED are distinguished
  (`pricing_version`, `price_verified_at`, `price_verification`, `previous_pricing_json`): a
  price is never overwritten in silence, what it was is kept, and a move past
  `STUDIO_PRICE_CHANGE_ALERT_PERCENT` is a letter from the Accountant to the Owner.
- **The vendor is asked before it is paid.** Where Runway's own published contract declares a
  task accepts a dry run, the render asks what this exact shot will cost before buying it; a
  quote that disagrees with the stored price by more than
  `STUDIO_PRICE_STALE_TOLERANCE_PERCENT` marks the stored price stale and replaces it, and a
  quote above a ceiling means the shot is not bought at all. A flag the vendor does not
  declare is never sent, because a question about a price must not become a purchase.
- **The page can say why**: under each rendered film, which model filmed each scene, in which
  environment, for how much, and the router's reason.
- Tests: `tests/test_environment_routing.py` (the eighteen the Owner asked for) and the
  render's own outcome records in `tests/test_motion.py`. 625 pass.

## Twenty-one dollars, and the guards that were missing — 2026-09-12

The Owner's credits fell to 1 878 and he asked who spent them. The answer, from Runway's own
usage: the studio generated eight `seedance2_5` shots for one film — 3 986 → 1 878 credits,
**21.08 USD** at the Owner's price of a hundred credits to the dollar. Six shots reached the
film. **Two were generated, charged for and thrown away** because the studio's own download
cap (32 MB) was smaller than a 7.6-second shot: 14.8 paid seconds, about six dollars, lost to
a bug. No agent and no worker did this; the render was started from here. Measured cost, far
from the catalogue's 0.025 USD a second: **43 credits a second — 0.43 USD — about 2.60 USD a
six-second shot.**

What was missing, now built:

- **A credit has a price** (`credit_usd` on the connection, in Settings): vendors that bill
  in credits state the credits a task costs and nothing about money. With the Owner's number
  the books convert it, so a film's cost is a figure and the daily budget can bite.
- **A ceiling per render** (`STUDIO_MOTION_BUDGET_USD`, default 12): the first shot teaches
  what a shot costs, and every shot after it is refused when what remains would not cover
  one. A film finishes with camera pushes rather than quietly spending the week.
- **A paid shot is never discarded**: a failed download is retried, and a shot that is paid
  for and still lost is recorded as `paid_but_lost` with its credits.
- **A test renders the minimum, on the cheapest model that films from words**
  (`?mode=test`, `test_motion_provider`, `cheapest_prompt_to_video`): no still bought first,
  two scenes by default. Production keeps the best model the account has, from the still the
  Director approved. The Owner's rule: test cheap, production best.
- Tests: two more in `tests/test_motion.py`.

## A premium studio, and the frame it films in — 2026-09-12

The steward read the vendor's pages, scored eighteen video models and recommended
`seedance2_fast`: "cost-efficient… acceptable quality for social media formats". The Owner's
answer was the standing instruction this studio had never been told: *"Nu facem rabat de la
cheltuieli. Nu are sens sa avem o companie de creare filme care nu poate livra filme bune."*
And the recommendation was worse than cheap — `seedance2_fast` tops out at 720×1280 for a
studio that renders 1080×1920.

- **The studio has a standing priority** (`STUDIO_PRODUCTION_PRIORITY`, default `premium`):
  it becomes the ranking's weights (quality 0.6, reliability 0.25, speed 0.1, cost 0.05) and
  a line in the steward's instructions — "recommend the best picture the account can make…
  treat price as a fact to record rather than the deciding one". `balanced` and `thrifty`
  are the other two; a channel may still override per purpose.
- **A model that cannot fill the studio's frame never outranks one that can**
  (`delivers_studio_frame`, `STUDIO_FRAME = 1080:1920`): read from each model's published
  ratios, so the 720×1280 models sort last instead of being recommended. It is a preference,
  not an exclusion — an account that offers nothing taller can still film.
- **The download cap was costing shots**: eight seconds of 1080×1920 came back near forty
  megabytes and two scenes of the first motion film were lost to a thirty-two megabyte
  limit. The cap is ninety-six now; it exists so a stray response cannot fill memory, not to
  judge a film's weight.
- Tests: one more in `tests/test_production_policy.py`.

## What a film costs reaches the books — 2026-09-12

The Owner asked what has been spent so far. The honest answer was that nothing had been
recorded: `provider_cost_record` was empty after four renders. Three reasons, each fixed:

- **The Owner's render button never asked the Accountant anything.** The day's media stage
  called `record_render_costs`; the button did not, so every render started from the page
  left the books untouched. It records now, and reports what it recorded with the render.
- **The production record named the voice provider but not its connection**, and a price
  belongs to a model on a connection — so narration could not be priced even where a price
  existed. The adapter that actually spoke is named, with its connection and model.
- **Runway bills credits, and the studio's prices are in dollars.** Runway answers every new
  task with `estimatedCost` in credits: the only number the vendor itself states about the
  money. It is kept per scene and per render (`motion.estimated_credits`), so a film that
  spent credits can be read back even while no dollar price for a credit is recorded.
- Tests: one more in `tests/test_motion.py`.

## The film plays where the film is — 2026-09-12

"Ar trebui sa pot sa il vad in Producție media, NU?" — yes, and it could not be seen: the
card drew a black rectangle labelled "9:16 Video" beside the measurements, and the endpoint
that serves the file (`GET /media/assets/{id}/stream`, there all along) was never called.

- **Redă** plays the rendered short in the card, at 9:16. The Owner's key travels in a
  header, which `<video src>` cannot send, so the bytes are fetched once with the key and
  played from a blob — the same bytes the new **Descarcă fișierul** link saves.
- Where a film lives, for the record: `backend/storage/media/<storyboard_id>/` holds the
  stills (`scene_NN.png`), the first frames sent to the motion model (`first_scene_NN.jpg`),
  the generated clips (`motion_NN.mp4`), the normalised shots (`shot_NN.mp4`), the narration
  (`voice_NN.mp3`, `master_audio.wav`) and the film (`final_short_9_16.mp4`). The MediaAsset
  row keeps the path and the SHA-256 of the bytes.
- Measured, for the question "does it take this long?": eight stills took eight and a half
  minutes, eight generated shots twenty-five — because the account's tier allows
  `maxConcurrentGenerations: 1` for every video model (and 2 for the still model), so the
  shots are made one at a time by the vendor, not by choice.

## A shot is a file, and a film is its picture — 2026-09-12

The first dissolving render looked right and was not: forty-six seconds of narration over
**six and a half seconds of picture**. One filter graph over eight inputs failed quietly
after the first dissolve, and quality control passed the file — because a container is as
long as its longest stream, and the longest stream was the audio.

- **Each shot is built and checked on its own** (`_shot_command`): one ffmpeg call per scene
  writes `shot_NN.mp4`, exactly as long as the scene, from the generated clip or from the
  still pushed in; a shot that does not come out fails the render there, named. The dissolve
  pass then works over finished files, so `_dissolve_command` has nothing left to hide.
- **The render measures the picture before recording anything** (`_video_stream_seconds`):
  a film whose video stream is more than a second shorter than its narration fails, and no
  MediaAsset is written for it.
- **Quality control measures the video stream** (`probe_media_file`): `video_duration_seconds`,
  `video_frames` and `video_fps` come from the stream itself, next to the container's
  duration, so the old "45 seconds" cannot be claimed by audio alone again.
- The Director's frame extraction asks for full range (`setrange=pc`) through `image2pipe`:
  the dissolve chain writes limited-range video, and the JPEG encoder had refused every
  frame — she was approving films she could not look at.
- Tests: three more in `tests/test_motion.py`.

## A short that moves — 2026-09-12

The Owner watched the first finished film and said what it was: "sunt doar niste imagini
lipite… Eu vreau un filmulet, cursiv." He was right. Every scene was a still held on screen
for the length of its narration, joined by hard cuts. The account has sixteen video models,
six of them priced per second, and the production hierarchy already resolved a `video`
choice for every scene — the assembler simply never asked for it.

- **A shot per scene, and the shots dissolve** (`_dissolve_command`): every scene becomes a
  clip of its own length, one ffmpeg call fades each into the next, and each dissolve
  consumes only the overlap the shot was made longer by — so shot N still starts exactly
  where scene N's words start, and the film is as long as the narration it carries.
- **The approved still is the first frame of generated motion** (`_generate_motion`): the
  scene's still goes to the scene's video model as `promptImage` with the scene's length, and
  the clip that comes back is the shot. A model that refuses leaves that scene as a slow push
  into the still — a shot, not a held frame — and the film is still made; what happened is
  recorded per scene in the render job.
- **What a scene costs is priced in its own unit**: narration by the thousand characters, the
  still by the image, motion by the second of film (`estimate_cost_usd`, `record_render_costs`).
  An adapter now carries the connection it was built from, so the Accountant can find the
  price at all; a unit with no recorded price is reported unpriced, never counted as free.
  At the account's prices a forty-five second short costs about $0.45–$1.15 in motion.
- **The first frame is sent at the size the film is made at**: a generated still came back
  as a twelve-megabyte PNG, which base64 turned into a seventeen-megabyte request and Runway
  answered 413 for every scene. The still is re-encoded to a 1080-wide JPEG (about half a
  megabyte) before it travels, and the shot is generated from it.
- Measured on the Owner's account, and worth knowing before the next render: one four-second
  shot on `seedance2_mini` — the cheapest video model there — cost 64 Runway credits, about
  sixteen a second, where the catalogue's recorded price implies far less. A forty-five
  second short of generated motion is therefore around seven hundred credits.
- Tests: `tests/test_motion.py` (4).

## The Director could not see, and nothing said so — 2026-09-12

The clean studio produced a real film: 45.6 s, 1080×1920, eight scenes on seven claims from
CERN's dark-matter page, Runway stills, an ElevenLabs voice, quality control passed on
technical, rights, source and factual checks. Then the editorial gate sent three frames of
it to the Director's model and the whole call failed: `glm-5.3` declares `completion`,
`thinking` and `tools` — not `vision`. A model that cannot see does not answer worse; it
refuses the request, so no film could ever be approved.

- **What a model can do is the provider's statement, and it is stored**: `ModelInfo` carries
  `capabilities`, the configured adapter asks Ollama's `/api/show` per model, and the model
  sync records every declared capability (creating the row for a word the studio has not
  heard before — the vocabulary is the provider's). `kimi-k3`, `qwen3.5:397b`,
  `mistral-large-3:675b`, `glm-5.3-flash`, `kimi-k2.6`, `deepseek-v4.1-flash`, `minimax-m3`
  and `gemma4:31b` declare vision; the rest of the account does not.
- **Frames go only to a model that can see** (`model_can_see`): otherwise the Director
  reviews the written film — script, claims with sources, scenes, what QC measured — and the
  prompt tells her she is judging it blind and to say if the pictures are what she needs.
- Tests: one more in `tests/test_editorial.py`.

## The studio finds pages before the Researcher names them — 2026-09-12

The first day of the clean studio, watched live: six real topics in English on authorised
sites; then nothing read. Dr. Aris named three addresses per topic from memory and every
one returned 404 — UNESCO serves its article pages only to browsers (the front page answers
the studio's honest identity; the deep pages do not), and the DeepMind, Anthropic and
Hugging Face paths did not exist. The Director, seeing a letter with no body, asked for
"raw fetch logs". A site's own search, in the OpenSearch Suggestions JSON format, answers
the studio's identity and returns pages that exist (Wikipedia's does, tested).

- **Search address per authorised site** (migration 0030 `research_allowed_host.search_template`,
  `set_search_template`, `PUT /factual/sources/allowed-hosts/{host}/search`, a field and a
  "Probează" button in the research dialog): https on the same host, `{query}` where the
  words go. Nothing is hardcoded: the Owner records it, the studio uses it.
- **`find_pages` / `search_pages`** (`backend/app/research/service.py`): the retriever asks
  for JSON (`accept_json`) under the same allowlist, SSRF, size and time rules; results are
  kept only on authorised hosts; a failed search is an empty answer.
- **The Researcher plans from pages that exist**: `gather_sources` lists the pages found in
  his prompt; when every guess of his fails, the found pages are read anyway.
- **Searches are the names in the title, not the sentence** (`search_queries`): a site's
  suggestion search matches the start of a page title, so the second clean day — with the
  whole title as the query — found nothing. Now the proper names and acronyms of the title
  and subject line ("James Webb Space Telescope", "Higgs Boson", "UNESCO") are asked, longer
  first, at most six.
- **The letter carries the evidence**: "Nicio sursă preluată" now lists each address and
  what the site answered, and says the studio fetched with its own identity.
- **A later evening pass that fails does not undo the first** (`_post_run`): the third
  review of the clean day returned no text and the stage reported the whole review refused.
- **One mistyped claim is one claim lost, not a day lost**: the third clean day read real
  pages (CERN's dark-matter page, NASA's Webb page, Wikipedia's High-Luminosity LHC page —
  the search step works), then the Researcher's claim list carried `"confidence": 0.95.0`
  in one object; the parser refused the whole list, the stage failed, the day failed and the
  studio entered safe mode. `_salvage_complete_objects` now keeps the objects that parse
  (a doubled decimal is repaired), and `_research_and_verification` counts a source whose
  answer cannot be read ("N surse fără afirmații citibile") and reads the next one.
- The same page named with and without a trailing slash is read once.
- **The fourth clean day produced a script — and refused it**: five scenes on dark matter
  cited their verified claims, five on the LHC upgrade cited nothing (no LHC claim had been
  verified: five claims a day out of thirty extracted). Now the day verifies up to
  `VERIFY_BATCH = 24` claims, CRITICAL first, and a draft with uncited scenes is sent back
  to the writer once with those scenes named ("write the film the claims allow"); the second
  draft is the one stored. The fifth clean day's rewrite still had one scene of seven with
  no fact behind it ("the LHC is getting stronger" — no page read said so): a minority of
  uncited scenes is now cut and the attributed film kept (`cut_scenes` in the result, named
  in the writer's announcement); a rewrite that still rests mostly on nothing is refused.
- **The storyboard speaks the writer's words**: the seventh clean day built eight silent
  scenes called "Scene 1"… "Scene 8" from a real script — `generate_storyboard_from_script`
  read the demo fixture's keys (`voiceover_segment`, `visual_prompt`) and not the writer's
  (`narration`, `visual_description`); the voice artist passed it ("nothing to pronounce").
  Both spellings are read now, and a scene without a stated duration lasts as long as its
  words take to say (3–9 s).
- **A provider's refusal fails the render, not the day**: Runway answered HTTP 400 and the
  media stage raised, the day failed and the studio entered safe mode. The refusal is now
  counted in the stage report ("N randări refuzate de furnizor"), the storyboard stays
  approved for tomorrow's attempt, and the day goes on.
- **One live storyboard per script**: rebuilding a storyboard supersedes an earlier one
  nobody has rendered (it is marked REJECTED), so the render stage never picks the stale
  board over the new one.
- **Why Runway refused: a model that edits pictures, not one that draws them.** The eighth
  clean day's HTTP 400 body said `referenceImages: expected array, received undefined`.
  `gen4_image_turbo` is listed under `text_to_image` and *requires* one to three reference
  images — it edits pictures it is given — and it was the studio's image default because it
  is the cheapest still model in the account. The contract parser now records
  `needs_references` per model and task, and `usable_purposes` — the one place that says
  what the API's own evidence lets a model do — no longer counts an editing task as the
  ability to serve that purpose. So the model is not offered in Settings, is not a candidate
  for automatic selection, and a stored default naming it is unusable rather than tried; the
  adapter also refuses before spending a call (`code="reference_images_required"`). Nothing
  is hardcoded: the fact comes from Runway's own published contract. `auto_configure` also
  replaces a stored default the API's evidence no longer supports (it used to keep any
  default that existed), naming the dropped model in its report. `needs_references` is
  stored with the rest of a model's public catalogue metadata at refresh, so the rule holds
  for the account as it is today, not as the code imagined it.
- Tests: `tests/test_search_step.py` (13), three more in `tests/test_script_writing.py`,
  one in `tests/test_runway_connection.py`.

## A review that fed itself, and a studio that can start over — 2026-09-12

The Owner's live evening, read from the record: after the day closed, the Director reviewed
nine times in twenty-four minutes (≈200k completion tokens). Each review escalated the same
matter to the Owner again — an escalated message stayed OPEN, so the next review found it
and wrote the same letter (nine copies of "Am nevoie de decizia ta: Nicio sursă preluată…");
each answer to an investigation was investigated again ("Investigate: Re: Investigate: …");
and every answer that landed in the inbox triggered another review.

- **Escalated is decided** (`backend/app/agents/director.py`): an ESCALATE_TO_OWNER marks
  the message ANSWERED — it waits for the Owner in its thread, not in the inbox.
- **One open letter per matter** (`backend/app/agents/messages.py`): a letter to the Owner
  whose subject is already waiting OPEN is that letter; nothing is posted twice.
- **An investigation's answer is read, not re-investigated**: a REQUEST_INVESTIGATION on a
  message whose subject already carries `Investigate:` becomes an ACKNOWLEDGE.
- **Reviews are rationed** (`REVIEWS_PER_HOUR = 3` in `backend/app/agents/mail.py`): the
  correspondence round defers the Director's review once the hour's reviews are spent; the
  letters are still answered.
- **Starting over** (`backend/app/maintenance.py`, `scripts/reset_history.py`): deletes what
  the agents did — topics, sources, claims, scripts, storyboards, renders, QC, publications,
  letters, runs, memories, day records, the outbox, the media files — and the live ledger,
  keeping the workforce, providers, credentials, channels and their YouTube bindings, bibles,
  strategy, authorised sites and the treasury. The immutability triggers are dropped for the
  one transaction and put back; foreign keys are checked before they are re-enabled. The
  script backs up `data/studio.db` to `data/backups/` first and refuses while the studio
  answers on its port. The ledger (`read_events`) starts at the `studio.history_reset` line.
- Why the Researcher "produced no ideas": on 2026-09-11 22:55 UTC he proposed five topics,
  all about IANA example domains — the demo fixture's `example.com` page was the only source
  and claim in his memory — and `www.iana.org` is not an authorised site, so all five were
  rejected. The reset removes the demo; the rule stands.
- Tests: `tests/test_reset.py` (3), three more in `tests/test_mail.py`.

## The Director watches the film before it goes out — 2026-09-12

The Owner asked how a video with no story, in Romanian, resting on one claim, could be
produced and published. From the record: the script was a demo of 2026-09-09 whose single
claim ("the system produces 9:16 video with a SHA-256 provenance hash and automatic QC")
has no source at all and was seeded SUPPORTED; the factual gate looked only at the status;
quality control measured the file (decodable, 1080×1920, real images) and nothing else; the
voice artist checked pronunciation; the Publisher checked that the title described the
content (it did); the Director read her inbox after the upload. Every gate did its narrow
job; nobody watched the film.

- **Editorial gate** (`backend/app/agents/editorial.py`, migration 0029 `editorial_review`):
  before the publish stage prepares anything, the Director reads the whole film as data —
  topic, script, every claim with its source, each scene's picture and narration, what QC
  measured, the audience language — and, when an encoder is at hand, three frames from the
  file itself go to her model (`images` on the generate call; the assigned models declare
  vision). Her verdict is a record, an event in the ledger ("vizionat și respins — …"), a
  STATUS or ESCALATE in the inbox, and a HANDOFF letter to each department her notes name.
  A REJECT closes the storyboard, keeps the film out of the queue, and lets selection move
  on. Three things are decided without a model: a claim with no source, narration not in the
  audience language, fewer than forty spoken words. The film that went out fails all three.
- `structured_run` carries `extra` (the frames) through both attempts.
- Tests: `tests/test_editorial.py` (6, one skipped without ffmpeg on PATH).

## The studio publishes in English, and the Director says what her model did — 2026-09-12

- **Audience language** (`backend/app/agents/language.py`, `STUDIO_CONTENT_LANGUAGE`, default
  `en`): the Owner's rule that everything posted is in English, whatever language the office
  works in. The script writer, the showrunner and the Publisher are told the audience
  language at the top of their prompts; on the way out, a title or description that carries
  the marks of Romanian holds the publication with the reason (`publication_language_hold`),
  so the Director sees it rather than the audience. The first real publication went out with
  a Romanian title — that is the case this closes.
- **The first structured attempt asks the provider for JSON** (`format: "json"`): a model
  that answers plainly is held to the object (qwen3.5: 133 tokens); one that narrates
  regardless still gets the native-thinking second attempt — which, live, is what let the
  Director decide twelve messages on `glm-5.3` (five minutes narrating for nothing, six
  thinking, 22k tokens, then letters to two employees). Slow and dear; the model is the
  Owner's choice.
- **When neither attempt yields decisions, the Director's letter to the Owner says what the
  model did** — how many characters of analysis, whether the second attempt thought its whole
  budget away — and that a model answering with the object directly would finish the review.
- Tests: `tests/test_language.py` (4), `tests/test_mail.py`.

## A real cycle, watched live, and what it showed — 2026-09-12

Run on a copy of the Owner's data with the worker on and publishing disabled in the copy;
the previous night's run on the live studio read the same way. Found and fixed:

- **Analysis instead of the object.** Asked not to think aloud, `glm-5.3` wrote twelve thousand
  tokens of inventory and never reached the JSON; the Accountant's close did the same at
  smaller scale. `parse_structured` now finds the first object that validates anywhere in
  the text, and `structured_run` (`backend/app/agents/structured.py`) asks once more, with
  the model's own thinking on (`think: true`) and the same budget, when the answer has no
  object — a model that narrates with thinking off answers cleanly when it may think where
  the text is not. Asked instead to "just format" its analysis, `glm-5.3` narrated again, so
  that path was dropped. The Director's review and the Accountant's close use it. Live: the
  close parsed (Nadia held unpriced runs and said why); the review's second attempt is what
  the next cycle runs.
- **A review the Director can finish.** Sixty inbox messages in one prompt were beyond her
  model in either mode (narration at 12k tokens with thinking off; nothing at all with it
  on). The review reads twelve at a time (`REVIEW_BATCH`), comes round up to three times an
  evening while more is open, has a 24k budget, and STATUS reports nobody read in three days
  are archived (`archive_stale_reports`) so the inbox holds letters, not history.
- **Limits that threw work away.** A 220-character topic sentence rejected five proposals; a
  330-character scene and a dialogue written as a list of lines rejected an episode. Text
  fields clip (`clipped`) or join (`joined`) instead of refusing; proposals are validated one
  candidate at a time. Live: five topics proposed where yesterday none were.
- **A jammed line.** Seven topics sat SELECTED behind demo-era renders whose quality control
  had failed or been invalidated; nothing could be chosen past them. `topics_in_production`
  tells work in flight from work that stalled; a stalled storyboard is rendered again once,
  with real visuals, when an image provider is READY; invalidated verdicts are measured
  again, newest file first. Live: selection moved on, one storyboard was re-rendered with
  Runway stills and ElevenLabs narration (18 s, decodable); the five demo-era files failed
  QC honestly ("moov atom not found" — they never were videos).
- **Sources that never existed.** The Researcher names deep URLs from memory and they 404
  (`nasa.gov/mission_pages/...`); the studio fetches, it cannot search. Today's guesses are
  not retried the same day, duplicates of a title share one attempt, and research reads for
  topics that still need it — but the limit stands: without a search step, only hosts with
  guessable pages (Wikipedia articles) work reliably. `www.wikipedia.org` on the allowlist is
  the portal, not the articles: `en.wikipedia.org` / `ro.wikipedia.org` must be added.
- **Watched to the end, live**: with twelve messages and a 24k budget the Director's review
  parsed (22.8k tokens): three letters of investigation (to the Accountant, the sound
  department, the Researcher), two letters to the Owner (link the YouTube account; rule on
  the unpriced runs and the Accountant's hold), two approvals, five acknowledgements. Within
  a minute the worker had the answers: the Researcher's in words; the Accountant's model
  restated the schema's example and her letter read "..." — a reply must now be words, and
  a narrated answer gets the native-thinking second attempt like every structured task; the
  sound department answered with a blocker JSON pasted into the letter — a blocker is now
  filed as an ESCALATE in words: what stops them, what they need.
- **The ledger reads letters as envelopes**: from → to, subject, first line, and how many
  letters the thread holds.
- Tests: `tests/test_cycle_fixes.py` (7), `tests/test_mail.py` (+1); backend 566/1.

## Polish pass: rhythm, hierarchy, chrome — 2026-09-12

Read from a screenshot of every view (login, workspace, research, media, publishing,
workforce, story, runbook, treasury, settings, inspector), then changed:

- **One text scale**: 13px for reading, 12px for meta, 10.5px letter-spaced labels; panels and
  dialogs share one radius and shadow; the top bar's crumb is a label, not a Tailwind class.
- **Actions sized to their words**: dialog submit buttons and the inspector's action row no
  longer span the column (the login button alone stays full-width).
- **The scene chrome is one bar in two groups**: the scene's own controls (autonomy switch,
  zoom, fit, fullscreen) on the left, the doors to each module on the right; they wrap by
  group on a narrow scene.
- **The ledger breathes**: 13px rows with hover, tabular times, filter chips that fit, and
  the production line as a status pill.
- **Settings**: titled «Setări», tabs on a segmented track, ✕ to close like every dialog,
  cards on the panel radius, inputs with the same focus ring as everywhere else.
- **Inspector**: four stat columns, the mission set apart from the contract, contract
  items with marks.
- Evidence: `scratch` before/after screenshots per view; frontend 86/86, tsc clean.

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


## HQ material usage and visual baseline — 2026-09-18, Codex

- Existing and new M_HQ_Flat parents explicitly support skeletal garments; failed
  persistence raises an error. Audited/reloaded copied assets before applying five
  backed-up .uasset files to the real project.
- Added audit_flat_materials.py; captured the existing scene through the native
  editor and saved an L2 comparison. capture_stream_frame.py is explicitly experimental.
- Validation: 36 scoped integration tests; docs hashes; UE material repair/reload
  and new creation/reuse. No claim of completed visual fidelity or measured FPS.
- Evidence and next steps: [VISUAL_AUDIT_2026-09-18.md](VISUAL_AUDIT_2026-09-18.md).


## Prevent stale HQ reconnect retries — 2026-09-18, Codex

Cancel old timers when the SDK starts/recoveries a connection and guard callbacks against reconnecting a non-offline player. Keep a still immediately when live and at disconnection. Added four lifecycle regressions and a reproducible manual browser viewer. 115 frontend tests, TypeScript/build passed; controlled real-video recovery stayed live to second 86. See STREAM_STABILITY_2026-09-18.md.

## The interface speaks Romanian — 2026-09-23, Claude

Every user-facing string the frontend owns is now Romanian, with full diacritics, in the studio's
own voice: the page and the scene in the first part, and in this one the eight dialogs, the agent
inspector and the mail window — headers, one-line purposes, section headings, rail links, field
labels, placeholders, buttons, tabs, `title` and `aria-label` attributes, and every status, intent,
empty line, confirmation and error fallback that `main.js`, `settings.js`,
`youtube_connections.js`, `mail_thread.js`, `agent_details.js` and `provider_production.js` write
themselves. Values stay values: the brand, names and role names, units and codes, enum values,
Google's own field names, and every sentence that arrives from the backend.

Also: the research form's three unlabelled inputs and its fourth box holding a bare `general` got
visible labels taken from what each control already said; the publishing gate card stopped quoting
an internal architecture filename; and `countLabel` gives a figure the agreement Romanian
requires, so «1 evenimente de povestit» is now «1 eveniment de povestit» and «92 evenimente» is
«92 de evenimente».

No behaviour, data flow, API call, gate or test contract changed, and `style.css` was not touched.
164 frontend tests pass (the same 164; forty-four assertions naming an English word were updated
in the same breath), TypeScript and the build are clean, and every view plus every dialog state
was photographed at 1920×1080 and 1280×800 against the 254 captured answers with 0 missing
fixtures and 0 console errors. See `CURRENT_STATUS.md`.
