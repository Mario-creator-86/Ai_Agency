# Architectural / Product Decision Log v5

## The budget is for images and motion; a first attempt bounds the thinking; a restart ends its runs (2026-10-15)

**The budget is for images and motion.** The books priced every LLM run and the period summed them into the day's spend; a 3,90 USD stills step was refused over 14,22 USD of tokens the Owner pays by subscription («LLM-ul este pe abonament! NU COSTĂ BANI»). Decision: the spend a budget counts is the vendors' cost records; the priced runs stay in the period's figures as information. Rejected: pricing subscription models at zero (the usage would vanish from the books) and a separate token budget against money (he has `STUDIO_AGENT_DAILY_TOKEN_BUDGET` for tokens).

**A first attempt bounds the thinking.** This morning's rule left Cloud to think natively; a long review on deepseek-v4.1-flash then reasoned to its output limit and answered nothing, twice, twelve minutes each. Decision: a structured first attempt asks for JSON with thinking off, and only the models the probe showed narrating without thinking (glm) are asked nothing; the second attempt thinks natively for all. Rejected: a per-task output cap on Cloud (the cap ends the reasoning without an answer) and a smaller model for reviews (the Owner chooses her model).

**A process restart ends its runs.** A RUNNING row older than the process is not in progress; it is closed as abandoned and the employee is free. Rejected: a shorter stale limit (a real long call must be allowed its time).

## Writing and motion are the Director's; a sent-back scene comes back to her; no regeneration without her review (2026-10-15)

**Writing in the picture is hers.** Since 2026-10-12 «readable or garbled writing» was a hard limit of the bible: quality control's word «text» sent a still she had approved back to the gate, nobody looked at the clip, and the scene was about to buy a new still and a new clip — for ruled lines on papers in the background and a zoom. The Owner, who watched the clip: «este acceptabilă … scrisul, ea trebuie să hotărască; dacă e în spate pe o carte, rămâne; pe termometru, rămâne; pe o foaie pe care scria, e normal; important e să nu fie scris pe imagine ca subtitrare sau logo-uri». Decision: no words of a refusal bind her on writing; her brief names what is serious (text laid over the picture, a logo, a watermark, or writing that says what the story must not) and what is the scene's own; faces where the bible forbids them and panels stay hard. Rejected: a per-object allow-list (the thermometer rule of 2026-10-13 was the first of an endless series) and a detector for overlays (none measures it; she sees the frames).

**A motion fault is weighed by the story.** «Nu-i de ajuns să zică quality control că e de la mișcare, că nu e același cadru.» Decision: a move or pace other than the plan's is minor while the scene tells the same thing, with its cause for the next prompt; serious only when it changes what the scene says.

**A scene sent back for its clip comes back to her.** Decision: before a new still is bought for a scene clip QC sent back to its still, she looks at the clip; her yes restores still and clip as hers (the clip's note written), nothing is bought; her no leaves the scene as it was. Rejected: restoring by the Owner's word in the UI only (he said she decides) and re-running clip QC (the same reading again).

**No regeneration without her review of the prompt.** «Întotdeauna promptul este cel care trebuie corectat, revizuit și aprobat.» Verified rather than rebuilt: the stills stage's re-rolls, technical ones included, already go through her ladder (the review of 2026-10-12), and the clip retry in production always carries her look and then her brief, the Editor's rewrite and her review; a caller check keeps it so.

## Complete is not everything: a work task carries the asks, the inbox tasks carry the inbox (2026-10-15)

**Complete is not everything.** The night's «complete messages» (2026-10-14) put every open message addressed to an employee, with its whole thread, into every call: the Director's 152 (105 status reports nobody resolves) made 1.6 million characters, and the model answered nothing after reasoning to its output limit. Decision: what rides in a call rides whole, but a work task chooses what rides — the asks of it (handoff, request, challenge), the newest twenty; reports and the full inbox belong to the tasks whose work is the inbox. Rejected: shortening messages (his rule), a character budget that drops the oldest mid-thread (a cut thread says half), and a model with a bigger window (the reasoning, not the window, was the limit). Open: the inbox must be resolved by the loop that reads it, so that it stays an inbox and not an archive.

## The Owner's model stays; a blocked writer goes back to research; a sentence's first word; motion weighed by meaning (2026-10-15)

**His model stays.** The Director's model-switch repair had moved Marcus twice without the Owner (the night's outage, then the hourly session's hand); he said «modelele de LLM, dacă au fost alese de mine, rămân; nu se schimbă singur». Decision: the model he set (`owner_home_model`, assignment_origin OWNER) is never switched by a repair; when it fails while another model answers, the card is his; when every probe fails, it is the provider's outage and nobody's decision. Rejected: switching with a letter afterwards (he would read it after the fact) and a per-agent lock flag (the assignment's origin already says whose choice it is). Kimi-K3 is denied by his words («prea scump»): `STUDIO_MODEL_DENY_LIST`, the existing place for his refusals.

**A blocked writer is not a format fault.** The identity contract tells every employee to answer `{"blocker": {...}}` when the work cannot be done honestly; the script parser read that as «the format is wrong» and the day moved on, the topic SELECTED forever on claims about the wrong subject. Decision: a blocker is its own refusal, in the writer's words; the topic goes back to PROPOSED with a note to the Director, and research reads for it again, counting only the pages fetched after the note. Rejected: deleting the off-subject claims (the record stays; the writer cites only what fits) and a letter to the Owner (quality and sourcing are the Director's).

**The first word of a sentence.** `search_queries` took any capitalised word for a proper name; a topic line that begins «Discovery that…» found the album and the channel, and the rule «a found page beats a guess» read them. Decision: a sentence-initial word is a name only when it is capitalised inside a sentence too, is an acronym, or opens a run of names. The found-beats-guess rule stays (its measurement holds: guessed addresses 404).

**A motion fault is weighed by meaning.** «Generarea costă bani. Dacă a fost generat un video greșit, promptul nu e bun. Schimbă sensul poveștii? Dacă nu, trece!» Decision: in the Director's QC brief a camera move or pace other than the plan's, while the scene still tells the same thing, is minor and bought again for nothing; a content fault (writing where the bible forbids it, the wrong subject) is a prompt fault, fixed in the prompt before one re-buy. Her judgement stays hers.

## 2026-10-15 — Final Cloud correction (Codex): the output sentinel is dropped

2026-10-15 final Cloud correction: -1 sentinel rejected live, removed; omitted num_predict returns OK in a short paid probe (0.00001 VR). Actual DeepSeek-v4.1-flash max output393216, so480000 invalid. Technical probes not film progress. Backend15596 ready; Owner objects to further parameter changes, no more probes. See corrected SARAH_MARCUS_CLOUD_RESPONSE report.

## 2026-10-15 — Native Cloud output and incremental response

Owner asks to preserve complete messages and fix Sarah/Marcus failures. Context multipliers do not define the vendor output ceiling: Cloud agency calls defer it to the native provider instead of sending 480000. Full input remains. Streaming retains every visible chunk and waits for completion; unsent/unanswered retry distinctions remain. Old HTTP 400 has no retained vendor reason and is not retroactively classified. No policy, architecture or production verdict change. See SARAH_MARCUS_CLOUD_RESPONSE_2026-10-15.md.


## 2026-10-15 — ADR-REFERENCE-COMPATIBILITY-AND-PARTIAL-VISIBILITY

Owner explicitly asks reference generation when portraits are available. Resolve the compatible reference sibling declared by the selected RunPod text model family, only from the same verified/discovered connection, before pricing/approval. Do not change persisted settings or invent a vendor, price or reference. Preserve partial visibility without introducing a face; require canonical wardrobe and explicit image-QA conditions. Recipient Owner does not imply a required reply for STATUS. No architecture/database migration or policy/paid-call change.

## 2026-10-14 — ADR-TASK-SPECIFIC-DIRECTOR-FAILURE-ROUTING

Film-QC findings select visual rewrite even when a newer take failed delivery. Clear the task routing flag, preserve history and do not release any purchase. The independent delivery ladder still requires terminal journal evidence and explicit retry_delivery. Brief v4 includes the action contract. No database/spec migration; no paid call or production mutation.

## ADR-CURRENT-REVIEWED-PROMPT-AND-DELIVERED-REDO (2026-10-14)

Approval authorizes the complete exact current reviewed text. Old TREATS metadata cannot
bypass integrity checks; incomplete legacy fields return to the existing Director/agent
rewrite route. Free replacement requires actual current prompt/reference identity and a
verified accepted file. Owner cancellation without delivery cannot advance bought/waiting
production progress; uncertain purchases and delivered QC failures remain tracked. Financial
history is preserved. No production mutation, restart or paid call; no schema migration.
Handoff: LIVE_PROMPT_APPROVAL_AND_ABORTED_REDO_2026-10-14.md.

## ADR-BUDGET-CHANGE-AND-COMPLETE-LLM-EVIDENCE (2026-10-14)

Owner supersedes the unset 15.24 USD film fallback when an active daily budget exists:
the daily sum becomes the implicit film ceiling, while every common daily/monthly hold,
cost and explicit film cap remains enforced. This does not reset historical spend.
Re-evaluate cached financial outcomes under changed budget versions/periods/film ceilings/
paid-media approval rules; retain history, avoid invalidation on ordinary spend, and keep
free minor acceptance independent of purchase funds. A changed budget is no fabricated approval.

Owner requires x10 internal LLM allowances and complete messages. Preserve all selected
text/JSON/list evidence and rewrite history, expand response/selection allowances and retain
semantic validation. No prefix fitting may turn an invalid response into an approval.
Keep declared media/platform transport limits and report actual provider length stops.
No production policy/take mutation or service/GPU/model activation. No schema migration.
Rollback only this task's hunks; preserve earlier uncommitted prompt and batching work.
Evidence: BUDGET_AND_COMPLETE_CONTEXT_2026-10-14.md and its proof/changes JSON.

## ADR-PREPARE-APPROVED-GPU-BUNDLES (2026-10-14)

Owner requests ready image/video work to leave together after preparation and approval.
Director repairs now complete all scene corrections before purchase, then prepare the image
layer and eligible video layer separately. Cooperative purchase flows suspend at the GPU
boundary while retaining the original guards, lease and individual budget holds; compatible
requests share one batch/session. The synchronous public APIs retain their behavior. The
outer film lease stays held until every nested purchase settles. Only genuinely prepared
purchases occupy redo quota; an unanswered approval cannot starve an approved later scene.

Every participating permit is checked by the infrastructure kernel. Shared startup is priced
once and allocated; scene caps cannot borrow from each other. Refunds/proven-unsent jobs and
measured overages remain attributed to their own purchases. Input reservation/upload/validation
of every chunk precedes GPU-on, exact prepared prompts are dispatched without rebuilding,
model work is contiguous, queue/input TTLs include the work ahead and applicable waits.
Abandoned preparation cannot clear an earlier uncertain purchase. STOP is rechecked after
preparation, before GPU-on and before dispatch. Published/closed films and final Owner takes
retain their guards. Automatic grouping is scoped to the current film's stage/repair; the
executor also supports multiple film identities when the caller retains all required leases.

No DB migration, external worker deployment, GPU start, paid LLM call, production DB write or
server activation. Four old Director integration fixtures failed under HEAD because they
did not answer Nadia's newer mandatory gate; give those fixtures an explicit simulated
APPROVE, retaining dedicated refusal/discussion tests. Architecture hashes unchanged.
Evidence and activation instructions: APPROVED_GPU_BATCHES_2026-10-14.md and CURRENT_STATUS.md.

## ADR-SERIAL-PROMPT-ROUTE-LIMIT (2026-10-14)

Owner rejects the serial's 980-character local ceiling. Use the existing GPU request/worker
allowance of 20,000 characters, with serial look version 3; remove the loader's 2,000 clamp.
Keep complete character identity, first-frame action and other scene fields. Oversized
candidates are held by model-aware lint, never silently cut. Explicit vendor caps retain
priority; the native worker counts characters, legacy Runway counts UTF-16 units. This is
a transport allowance, not a claimed optimum or proof of image quality. The pinned Qwen
ComfyUI source and both workflow bindings were checked without GPU execution. Eight current
serial scenes recompose with 13 required-content losses reduced to zero. Two older motion
loss regressions were also repaired without splitting shared object/negative lists.
No DB migration, policy/spending change, provider call or server restart. Proof, activation
and rollback: SERIAL_PROMPT_MODEL_LIMIT_2026-10-14.md / .json. Architecture hashes unchanged.

## ADR-AGENCY-REPAIR-PROGRESS-MUST-BE-OBSERVABLE (2026-10-14)

Use the exact publication/render asset relationship to retire production work, regardless
of title/privacy or storyboard label. Recover previous-worker agent calls only with the
exclusive queue lock, known pre-start correlated text task and preserved retry accounting.
A provider reply is not a usable shot plan. Scope indices explicitly and retain all evidence;
learn output allowance from assigned-model/provider outcomes within existing budget gates.
Whole comma lists retain their predicate and negation scope, preventing positive ghosts.
Sarah compared real failed/successful work and selected a verified replacement for Kael via
versioned DIRECTOR_REPAIR assignment. Test scene writes stay in copies; production costs
and model calls remain truthful. Do not equate text review with visual media acceptance.
Owner requests commit and stop; no automatic studio restart or monitoring wakeups.
Evidence and rollback inputs: AGENCY_LOOP_DIAGNOSIS_2026-10-14.md and its proof JSON.

## ADR-PROMPT-REPAIR-LAYER-AND-CURRENT-EVIDENCE (2026-10-14)

Nine recorded candidate losses reveal compiler omissions and contradictory shot fields.
Keep visible ending clauses beside unusable scene pointers and the first action after an
identity/position introduction. The editorial 95-word target must not lose mandatory serial
motion that fits the native cap. A declared motionless world receives no invented movement.
Check composition on the layer being bought: an unchanged accepted still is visual evidence,
not a reason to force a new picture because its historical words omit a minimum identity.
Real QC rejection of that picture still routes to the still layer. Keep complete current
finding/cause/correction/negative context and both prompt versions in correspondence; bounded
historical summaries remain. Nine frozen offline proposals are review data only, never copied
to production or treated as Director approval; narrative/scientific conflicts stay with the
appropriate agents. No migration or policy/spend/runtime change. Rollback and proof:
PROMPT_CONTRACT_FOLLOWUP_2026-10-14.md. Original architecture hashes are unchanged.

## ADR-PROMPT-CONTRACT-COMPLETENESS (2026-10-14)

Owner prioritizes first-generation and repair prompts, complete QC feedback and autonomous
editorial repair. Required endpoints, actor/wardrobe constraints and findings must survive
composition/context transport; otherwise the sheet blocks before purchase and the editor
gets the specific loss. Large initial plans batch whole scenes with claims/bibles intact.
Recorded examples exposed 57 stored scenes with missing conditions; the deterministic audit
covers 85 LIVE scenes/14 boards, including history; nine candidate packages still need editing.
Connect input_guard to RunPod stage submissions/new reservations: seed changes do not fix
rejected content. Remove daily editorial ceilings (sheet five, ladder six, shot-plan two days)
and truncated evidence; keep cooldowns, single continuation, provider pauses, paid caps and
Owner STOP/approvals. An intentional static camera is advisory for variety. Prompt/QC/mail
versions change explicitly. No DB migration, model calls, runtime restart or paid generation.
Validation, limitations and rollback: PROMPT_CONTRACT_AUDIT_2026-10-14.md. Real visual quality
and runtime activation remain unverified. This supersedes older editorial retry ceilings,
not Owner spending or platform capability limits; architecture hashes remain unchanged.

## ADR-REGENERATION-REQUIRES-REVIEWED-WORDS (2026-10-14)

Owner requires Sarah to verify replacement prompts before every regeneration. The old
candidate's second look is not such a review: Kelvin's 23:56 generic calmer retry ignored
her face/camera diagnosis and failed again. Production image/video rerolls now enter the
existing brief → Editor rewrite → Sarah TREATS review ladder before any replacement purchase.
Take selection receives the same complete character/shot facts used by QC. Serial agents
receive exact composer limits instead of repeatedly adding corrections the composer drops.
Free backlog work shares the one worker during GPU waits; its five-minute configurable
cadence also updates the existing Director schedule without activating paused schedules.
Rejected: another queue worker, unreviewed generic rerolls, database verdict overrides and
raising Owner budgets. No migration of takes. Tests, limitations and rollback are in
DIRECTOR_REGENERATION_REVIEW_2026-10-14.md; architecture document hashes remain unchanged.

## ADR-TERMINAL-DELIVERY-IS-DIRECTOR-WORK (2026-10-13)

Owner: Kelvin scene 2 must go to Sarah, not wait for his decision. The ladder existed
but admitted only visual QC failures; a terminal expired delivery became UNKNOWN/Owner.
Reuse its typed brief: retry_delivery only for RUNPOD.EXPIRED_UNDELIVERED verified in
the terminal provider journal without an asset. Keep prompts and paid-attempt counts;
release only the affected step hold and let the existing staircase enforce money,
approval and STOP. An in-flight/ambiguous submission is never equated with this terminal
failure. QC still requires its reviewed rewrite. Rollback: revert the selective delivery
routing/release and report changes; keep the original takes and costs as evidence.
Tests/proof: DIRECTOR_DELIVERY_ROUTING_2026-10-13.md.

## ADR-DIRECTOR-JUDGES-QC — every QC refusal passes the Director before money is spent; her looks may pass a film to publication; no quality question reaches the Owner (2026-10-12)

Context: the Owner, 2026-10-12 16:30–23:10, after a day of paid redos that repeated the same defect: «Trebuie să le facem când știm că ceea ce facem este bine! Nu putem permite loopuri pe bani și picarea QC dacă deja a fost aprobată»; «Directoarea acceptă defectele mici! Dar trebuie să înțeleagă de ce apar»; «LLM-ul este pe abonament! Nu costă bani… Generarea de imagini și mișcări costă!»; «după ce se uită directoarea, trebuie să aibă și puterea de a trece de QC și merge mai departe cu publicarea»; and, relayed 22:50, «Dacă "decide Proprietarul" înseamnă că nu este o agenție autonomă».

Decision: (1) A model call is free and is made whenever it can save a purchase: before any paid redo, re-roll or retry the Director looks again at the refused picture, at QC's own frames (`media/second_look.py`), and says CONFIRMED (serious, redo), ACCEPTED_MINOR or OVERTURNED, with the defect's cause, layer and lesson. (2) A measured serious defect (a hard limit of the bible, YuNet faces, panels, lettering) is dropped only when her look finds no defect at all. (3) When her looks clear every real finding of a failed film, her REPAIR becomes her ACCEPT in the same walk and the film goes on to publication. (4) What she learns is a lesson for every later prompt of that kind of film, corrected by her when a later picture contradicts it. (5) A rewrite is bought only when her review finds that it treats every serious finding. (6) Quality never reaches the Owner: a free fix spent three times is a developer_defect note; only money over a cap, accounts, authorisations and security are his cards. Rejected: the Owner deciding stalled quality (contradicts autonomy); more code thresholds instead of her judgement (they produced today's loops); buying first and judging after (costs the money the rule protects).

## ADR-REDO-ROUNDS-BY-PICTURES — a paid round is counted by what it made, inside its own window; a cap card raised on a wrong count is moot; a new still keeps its unchanged motion words (2026-10-12)

Context: the Owner, 2026-10-12 15:05 and 15:30 — «5 refaceri? Pentru o poză în mișcare? Costă! … Nu ai cum să faci de 5 ori aceeași greșeală!», «Cum să lași de 5 ori refacerea scenei? Nu este clar că este o problemă?». The audit of 1c038a99's scene 5 (read-only, on a database copy): the five «rounds» were five `runbook.qc_paid_redo` events, not five pictures — two rounds killed by restarts before anything was asked, one cancelled after 1.3 s (14 credits of GPU overhead, no picture), one still + clip (69 credits), one clip (41). `_paid_redo_rounds` read a round as delivered when ANY take of the scene came after it began (`assembler._delivered_since` had no upper bound), so the fourth round's still delivered the three empty rounds before it, the cap of five fell on two real redos, and the Owner's card («scena 5: 5 din 5») asked him a question that was not his. The same hour the 15:19 restart cancelled the serial's scene 4 stills (RUNPOD.CANCELLED) and emptied scene 7's motion, and both rounds were written as paid redos. And the cyclotron's scenes 4 and 5 lost their approved, never-animated stills (bought the day before) to the «same prompt» escalation: the Director's motion brief came back with the same words, the code took that as the picture's turn and bought new stills and clips (269 credits) while she had written «alătur imaginile aprobate, nu cumpăr nimic».

Decision: (1) every paid round of a scene is read inside its own window — from when it began (`started_at`, else its correlation's first event) to when the scene's next round began (`_round_windows`); `_round_delivered(..., until)`, `assembler._delivered_since(until=)`, `director_qc.bought_since(until=)` (`_marks_since`, `_new_since` bounded alike); `_paid_redo_rounds` counts a round only when a take of the scene with its file (or still at the vendor) was made in that window, `_open_still_rounds` opens a still round for its motion only on the same reading. A round cancelled, refused by the gate without a picture, or killed by a stop counts for nothing: his cap counts pictures, the economy's books count the money. (2) The card's condition `redo_cap_cleared` reads the count again (`cap_still_reached`: the card's scenes, kept in its `clears_when`, against his limits plus his allowances; without settings the limits cannot be read and the card is kept): a card whose rounds, counted by what they made, are below the cap is moot and closes by itself; the film goes on under his original limits at the Director's next decision (the hourly review pass). (3) A motion whose rewrite came back with the same words on a scene whose approved still is not the failed film's (`_still_newer_than_film`) is bought as it is from the new still; the escalation to the picture (MOTION_REWRITES_BEFORE_STILL) is for a picture that stays. (4) A restart is quiet only when the GPU is off AND no film task is claimed (the developer's watcher); a stop between two GPU steps of one round is a stop inside the round.

Rejected: counting rounds by money spent (the cap would then stop a scene the gate protected cheaply, and the budgets already hold the money); leaving the card for the Owner to answer with his «allow» (he gave his OK in chat, but the card's premise was false and the studio must not spend his word on its own miscount); keeping the escalation for new stills (a new picture is what the escalation would buy). Consequence: the Higgs-2 card closes as moot at the next refresh and the film's repair resumes (two of five rounds spent); the serial's scene 4 stands at one round, not three.

## ADR-REWRITE-REVIEWED-BEFORE-PURCHASE — no redo is bought on words the Director has not checked against the finding; the serial's words change on a content refusal; a still blamed by clip QC leaves the film (2026-10-12)

Context: the Owner, 15:05 — «Dacă se reface ceva, trebuie să ne asigurăm că promptul de regenerare este impecabil. Adică, tratează problema? Promptul trebuie revizuit.» The audit of 1c038a99's scene 5: three briefs in a row diagnosed a fixed compiler sentence the refusal never named and a face QC never saw; the rewrites' sentence diffs were empty or beside the finding; each was bought. The serial's scene 4: the finding named two women face to face where the plan asked a single on Nadia; the serial path never read it and re-rolled the same words. The cyclotron's scene 1 (15:56, 16:08): clip QC said the fault was in the still («aceeași imagine nu se mai animă»), the still stayed APPROVED, and the next two repairs bought a clip from it again (36 credits each).

Decision: (1) After the Video Editor's rewrite passes the lint and before it is stored, the Director reviews it against the findings (`scene_rewrite.review_rewrite`, `RewriteReview`): every finding is named with the new sentence that treats it; a finding is treated only when the new prompt changes the words that invited it or names in their place what the scene asks for; MISSES stores nothing and buys nothing, and the next brief is shown why; a review nobody could make stores nothing either. The gate still proves the picture (ADR of 2026-10-12, «A still is judged against the scene»): the review proves only that the words changed where the finding points — a necessary condition, at the price of one model call, never a purchase. (2) Her brief diagnoses only what the refusal names, and a diagnosis that already failed the same way is wrong: the approach changes (what is in frame and where, what is named first, the shot's size), not the tone. (3) A serial scene's words are still the composer's — but on a content refusal (the gate's «nu arată ce cere scena/planul», readable text, a face, the bible, the look; a clip-QC block; the film QC's findings) the Director's brief and the Video Editor's rewrite of the fields the composer reads (action, emotion, background, continuity, ending frame, camera move; on the motion layer only camera move, ending frame and a `motion_emotion`) are said again by the serial composer, reviewed like a factual scene's; a technical refusal (panels, blur, a degenerate or unmeasured picture) re-rolls the same words; stale words are said again by today's composer first, at 0 credits. The serial's clip now says where the shot ends (`compose_serial_motion`, the plan's `ending_frame`). This amends «A serial scene's words are the composer's … never rewritten by a model» (below): the composer still writes every sentence; the model writes the beat's fields. (4) When clip QC finds the fault in the picture (`back_to_still`), the still the clip was made from is REJECTED with the gate's code and the clip's reason (`media.still_sent_back`) and the scene reads NEEDS_STILL: nobody animates it again and the Director's still redo buys a new picture; a still the Owner approved himself stays his.

Rejected: a text-only check without the model (a diff can be non-empty and still beside the point — Higgs-2's round 4 added «metallic surfaces» while the picture stayed a tower); letting the review fail open (a redo bought on unverified words is the mistake the Owner named); keeping the serial's words untouchable (the goal is two episodes a day, and a refusal that names the words needs other words); re-rolling a still-blamed clip's motion (the same picture animated again is the same fault at 36 credits).

## Today's duplicate Higgs short is repaired and published; the subject check prevents the next one (2026-10-12)

The Owner, 2026-10-12 08:40 (card): «Îl las: se repară și se publică (al doilea Higgs)» — today's factual film «The Particle That Shouldn't Exist (And Briefly Didn't)» (1c038a99), the same subject as the short published on 10-10, stays in the Director's repair loop and is published when it passes quality control; no second run today. The subject check (research/agent.py, 0bf1a48) keeps the researcher from proposing a subject the studio already made, from the next run on.

## A still is judged against the scene before a clip is bought for it (2026-10-12)

Decision: the stills gate asks the vision model the film's question — does the still show what the scene asks for, its written picture and the narration over it — beside the prompt's question, and refuses a still that shows another thing before the motion is bought; the same model answers both, on the same look at the picture. Reason: the Owner, 2026-10-12 15:05, on five paid rounds of one scene («nu ai cum să faci de 5 ori aceeași greșeală»): the gate judged a still against its prompt, the film's QC against the scene, and a prompt that had lost the scene's subject passed one and failed the other at the price of a clip and an assembly each round. Rejected: a text check of the redo's prompt against the finding (words cannot prove a picture); making the film's QC cheaper (it needs the film); asking a second model (one look, two questions costs nothing more).

## The films take turns on the one worker: a repair round, then the next film (2026-10-12)

Decision: the Director's review of a failed film runs one repair round per walk when another film's continuation waits — the repaired film's new report is queued as its own continuation (the review pass's key) and the walk ends; the rounds stay in one walk when nobody waits. Reason: the one durable worker runs one task at a time, and a film's rounds (two RunPod cold starts each) held it for an hour on 2026-10-12 while the serial episode — the goal's second film — waited queued; serving the films in turn costs no credits and no quality, only the order. Rejected: a second worker (the worker, the leases and the GPU session were built single-threaded; a change for a quiet day, with its own tests); fewer rounds for every film (a lone film loses nothing by its rounds); priorities by channel (the Owner wants both channels; turn-taking is fair to both).

## A still's exclusions are said in the model's negative channel (2026-10-12)

Decision: on an image model with a negative channel (RunPod's worker), every still carries a fixed negative — the stills gate's own refusals (panels, collages, split screens, stacked frames; text, lettering, captions, logos, watermarks), the faces when the bible forbids them, and the plan's `avoid` items — and the positive prompt stays positive. Reason: ADR-POSITIVE-PROMPTS-ONLY sent a plan's exclusions to the negative channel where a model has one, and the stills step had none wired, so the serial's two-shots were drawn as stacked panels twelve times each on 2026-10-11/12 with nothing in the request against it. Rejected: stronger positive wording alone (tried on 10-12 morning: «One continuous picture fills the whole tall frame», refused again); making the negative part of the still's identity (every approved still would have been bought again).

## The paid-redo cap reached is the Owner's card (2026-10-12)

Decision: when a repair the Director decided can buy nothing because of the Owner's paid-redo cap (per scene, per film), the studio asks him once per film, as a card (`decisions.producers.redo_cap`): more paid redos (five, on the film's record, moving his cap for that film only), publish as it is (his ACCEPT, carried out as hers), close, or wait; the Director is not asked again while the card waits. Reason: his rules — a film is never left waiting for quality, only money stops it, and what is his (money) reaches him as a card; the cap is money, and on 2026-10-12 it stopped a film in a loop of her REPAIRs that reached nobody. Rejected: raising the cap in the settings (the schema bounds it at 5 and 20, his figures for every film); letting the Director accept or close on her own when the cap is reached (publishing a film with the flaw she found, or losing what he paid for, is his choice once his money is the stop); a letter instead of a card (a letter asks nothing he can press).

## ADR-POSITIVE-PROMPTS-ONLY reaches the compiler's own sentences (2026-10-12)

Decision: the compiler's fixed sentences obey the rule the plan's exclusions obey — a positive prompt names what is there, never what is not. The sentence for a scene of objects under a faceless bible is «The frame holds only the place and the things named.» (was «There are no people in the frame.»), and the linter accepts it as the face rule kept. Reason: five Director briefs on 2026-10-12 found the negation drawing the people it named, asked for it to go, and the compile put it back — the loop paid redo rounds for a sentence of our own. Rejected: letting the Director's «avoid» list strip the compiler's sentences (the sentence is the bible's rule said for the scene; it must be said, positively), and «No text, no logo.» changed on the same day (no brief named it; the serial's «Pages and screens are blank.» is the positive form where lettering was drawn).

## A scene's later rounds move past the film's seed; the serial's rung decides a redo when the words are already today's (2026-10-12)

Decision: the film's seed (`assembler.film_seed`) stays the plan's and every scene's first round's, but a scene's next motion round is bought on the seed moved past the clips the scene already had (`_scene_seed`, two seeds a round, a round that made nothing keeps its seed), and the stills' re-rolls are numbered past every still the scene ever had (`stills_stage._Scene.rolls`); and the serial's rung, when a scene's words are already today's and quality control refused its picture or clip, writes the Director's decision to make it again on the same words (`serial_reroll`) instead of leaving the walk with nothing rewritten. Reason: the Owner's rule — redone until it passes, only money stops it — needs each round to be a new throw: with the film's one seed on every round, the same words made the same clip and the same retry, and a serial scene whose composer's words could not change was left waiting for a restart that would have said the same. Rejected: a random seed per round (the sheet the Owner approves and the step that buys must hash the same, and a round must be repeatable from the record); rewriting serial words with a model (the serial's words are the composer's, decision of 2026-10-12 earlier); a cap on the rounds beyond money (his rule names money as the only stop; the film's ceiling and the daily budget stand).

## A shot cancelled before it was sent is nobody's refusal; a quality refusal waits for the Director's rewrite, never for the Owner (2026-10-12)

The Owner, 2026-10-12 08:45, after the card: «Dacă tot l-am plătit, publicul. Dar te rog pune regula pentru a nu mai crea același subiect» — the subject check above is that standing rule (every idea, script, storyboard and publication title is read; a shared subject, not only a similar title, is a duplicate). At 08:34, seventeen seconds after the second self-restart, the serial's walk stopped «scena 6 așteaptă decizia Proprietarului» for a clip quality control had refused on 10-11 at 20:44: the retry his stop cancelled at 20:58 was recorded as a REFUSED take (RUNPOD.CANCELLED, nothing paid), `classify_failure` knew no such kind and said UNKNOWN, so `take_failure` held the scene for him and `last_failure_code` hid the quality refusal from the Director's ladder; the whole motion stair waited on him with a letter. Decision: (1) a take the step stopped before sending says nothing about its scene — it neither holds the scene nor stands before the refusal that came before it (`assembler.take_failure`, `CANCELLED_FAILURE_CODE`); (2) a scene whose newest take quality control refused, with no hold event of the step, is held for the Director's rewrite (`scene_memory`, `_quality_hold`) — her ladder runs in the same walk and her rewrite lifts the hold — never bought again on the same words; (3) the walk's words say whose the wait is (`stages._held_words`: «refuzată de controlul calității așteaptă rescrierea Directoarei» / «așteaptă decizia Proprietarului pe foaia de filmare»). Reason: his rules of 10-11 and 10-12 — a film is never left waiting for quality, only money stops it; a wait or a letter reaches him only for what is his. Rejected: teaching `classify_failure` a CANCELLED kind (the take is not a vendor failure at all; the rule belongs where the scene's takes are read); letting the walk buy the refused words again without her rewrite (the same clip, 36 credits); a new refusal name in place of NEEDS_OWNER (the ladder, the letter guard and the passes key on `LADDER_REFUSALS`; only the words change).

## The Director decides everything but his accounts, authorisations and security; a subject already made is never proposed again; the goal is two shorts and two episodes published alone (2026-10-12)

Decisions (the Owner, 2026-10-12 morning). (a) «Ar trebui să nu ajungă la mine, este la Director!» — the Director decides quality, prompts, tools, schedules and the agents' work; a letter reaches the Owner only for his accounts and sign-ins, what only he authorises (a site, a model) and the studio's security or legal standing; money is asked by the studio's cards, never by a letter; a tool that fails is noted for the developer (`developer_defect`), not sent to him. (b) «Facem două shorturi la fel?» — no: a subject the studio already filmed or published is never proposed again, whatever its new title; the researcher reads what was made and the duplicate check reads the subject, not the title. (c) The goal, set the same morning: two shorts and two serial episodes published end-to-end by the agency alone — subject, accounting, pictures, motion, publication — with no intervention; a publication that needed a hand does not count.

## The developer session restarts the studio itself; a day cut off by the restart resumes by itself (2026-10-12)

Decision (the Owner, 2026-10-12 07:40, after a restart card had waited hours for him): «de acum încolo, să dai singur restart la proiect, nu mă aștepta pe mine!». The developer session restarts the studio process itself after every tested, committed change, at a safe point (no GPU session open, no purchase in flight), with a graceful stop (the day ends at its boundary) and a detached start. Consequence for the product: a day INTERRUPTED by a shutdown or a crash is resumed by the studio itself after the start — the stages it completed are replayed from their record, never done again (no second subject, no second film), and the stage it stopped in and the rest run; his «Pornește rularea de azi» stays for a second day's production, which remains his decision (REL-03). The clock still never re-runs a cut-off day whole.

## The studio asks for ample, cinematic motion; the camera vocabulary grows to eighteen families; the model stays LTX-2.5 (2026-10-12)

Decision (2026-10-12, the Owner's words of 2026-10-11 and his card «Poți să te apuci de toate reparațiile și de teste. Nu trebuie să aștepți până mâine!»): the studio asks its video models for ample, cinematic, continuous motion — one clear camera move with a path and a tempo over the clip's seconds, the subject's actions as verbs, the world in motion — and never for stillness; the model stays LTX-2.5 (the Owner: «modelele cred că sunt foarte bune, trebuie doar să lucrăm la prompturi»). The camera vocabulary grows from ten slow moves to eighteen families (`prompt_lint.CAMERA_MOVES`), every documented model in `config/film_models.json` gets the whole list, and the Director's rewrite is offered the same list. Clip QC answers a deformed clip with a calmer retry (forms kept) and a barely-moving clip with a firmer one. Judged by the weekly comparison with views, like the editorial scores.

## A serial scene's words are the composer's: said again with today's composer, never rewritten by a model (2026-10-12)

Decision (2026-10-12, from the Owner's rules of 2026-10-11: «Directoarea ar trebui să depisteze singură asta și să refacă ce este stricat» and «Poți să te apuci de toate reparațiile și de teste»): a serial scene's words are the composer's, not a model's rewrite. When the stills gate refuses a serial scene and its stored prompts differ from what the serial composer writes today (the composer was fixed, the look changed), the Director's ladder says the words again with today's composer and records that as her decision on the still layer; the stills step then buys on the new words. A model rewrite from a brief stays the factual films' rung; a serial scene whose words are already today's is not rewritten and the ladder says so («cuvintele de azi»). A still redo of a serial scene buys today's composer's words, never the stored older ones and never the documentary compile. Consequence: no serial film waits for the Owner over a composer fix; the recomposition costs nothing and is idempotent.

## The LTX training set is collected from now; a LoRA after ~100 clips (2026-10-11)

- The Owner (2026-10-11, 23:50, card), after the session read the LTX-2 trainer (packages/ltx-trainer: LoRA / full fine-tune; T2V, I2V, video extension, IC-LoRA with depth/pose/style references; 80 GB GPU recommended, INT8 config for 32 GB; datasets of short captioned clips in resolution buckets; LTX-2 Community License): «Strângem setul de date de acum, antrenăm după ~100 de clipuri». Zero cost now: every still the gate approves and every clip the clip QC passes is written to a training manifest with its exact prompt (ours, not an auto caption), its camera move, seconds, resolution, model, look version and who approved it; at ~100 good serial clips a card with the training cost (~20–40 USD a run, estimate) comes to him. Why: an image-to-video LoRA on our own approved cadres is the path to the serial's character and look consistency; IC-LoRA with camera references rendered from the Unreal office is the later path to controlled cinematic motion. Not for today's weak motion (the prompts asked for stillness: «Mișcare v2», in progress) and not for the factual stills (Qwen-Image is another model).

## The Director's editorial judgement, up to ten rounds; the channels' descriptions name the agency (2026-10-11)

- The Owner (2026-10-11, 23:30, card), after reading «The Zero Script Club» and the shorts' scripts with the session's honest critique (the episode: a clever meta idea, clean lines, one good line, but a status meeting — no stake, no conflict, one dry register, no hook for a stranger; the cyclotron short: a good contrast hook and the title's promise kept; ATLAS/Higgs: jargon without an image, a CTA for experts): build the Director's EDITORIAL JUDGEMENT for both channels — a score on five criteria (a hook with a stake in the first two seconds, clarity for a stranger, one memorable moment, a punchline or reversal at the end, a reason to follow), below the threshold a brief to the Scriptwriter naming the two weakest criteria, a rewrite, scored again — «vreau să încerce de 10 ori, ne trebuie un serial bun și un short bun, nu doar 3 runde» — then the best version ships (his rule: publish, do not churn); the scores are kept and compared with the views in the weekly review. Built after the human live register and the living office (in progress), with tests on fakes. Why: today the Director checks only facts, privacy, length, words per beat and cast — all structural; nothing judges whether a stranger would watch to the end.
- Same evening: both channels' descriptions now say they are made by AMN-AI Agency, that the agency's work will soon be watchable LIVE, and each links to the other (@nexuscuriositytv ↔ @insidethenexusai); done in his YouTube Studio at his request.

## A GPU session shared per model across films, tomorrow; the cold flow stays; 4-6 posts a day (2026-10-11)

- The Owner (2026-10-11, 22:55, card): build «a GPU session shared per model across films» — a film whose next step is ready to buy on the same model (sheet gates passed, his money rule lets the step buy, its lease free) joins the session already loaded, before it closes; tomorrow, after today's production, tests on fakes, in at the first idle restart. Why: measured today, every paid step of every film opens its own RunPod session and loads its model again (~10–16 min each: stills sessions 11:43→11:54, 13:50→13:59, 22:29→22:45 first delivery; motion 6.5–12.5 min); tonight the serial and the cyclotron's redo would load Qwen-Image twice and LTX-2.5 twice. The money rule stays per step and per film, the purchase lease per film; only the loaded GPU is shared. He keeps the cold serverless flow otherwise (1 worker, GPU off right after the step): «Nu vreau să pierd calitatea! … Nu vreau nici să plătesc în plus» — no fp8 weights, no warm worker. Target he named: 4–6 posts a day.

## The same blockers; the serial's look; music under the voice; the Owner's final approval (2026-10-11)

- «The same blockers» for the sheet repair's ceiling and back-off are the blockers' kind, code and scene, never their wording or the sheet's hash (528ec93). Why: the Owner's safety of 2026-10-03 did not engage on 2026-10-11 because every rewrite changed the fingerprint; a loop without progress ran every five minutes. Consequence: fewer or other blockers start again from zero; the same ones under rewritten prompts do not.
- The serial's look is the Owner's own office picture (6510d04), a proposal he may change; faces are allowed in the serial and must stay the same person (the bibles' reference portraits). Why: «acesta este biroul; serialul ar trebui să păstreze oarecum o tematică» and «aici sunt permise și fețele … să nu pice la QC».
- Music is mixed by a plan the Voice Artist writes per film (2e20ecf): the bed 20 LU under the voice measured where the words are, lifts only in silences, the Director reads the plan and re-asks a refused mix. Why: the Owner, 2026-10-11: «mare grijă totuși să nu acopere vocea», and his loop rule (Director → agent → repair → QC → her accept).
- The Director's confirmed repair may replace a take the Owner approved; only an approval he marked «final» stands against it (5f5414c). Why: his card of 2026-10-11 on the cyclotron film («Trebuie să fie în lucru să îl refacă, nu?» → «Directoarea poate reface și ce am aprobat eu»): a film is never left failed because his earlier look chose a take QC later measured as defective. Consequence: `director_repair` redos retire non-final approvals and tell him; every other unasked redo keeps the 2026-10-10 rule (nobody retires what he approved); the «Aprobat (final)» option is the API's `final` (the sheet's button is the pixel session's).

## ADR-POSITIVE-PROMPTS-ONLY — a plan's exclusions never enter a positive prompt as negations (2026-10-11)

- Decision (2026-10-11): the compiled still and motion prompts never say "no X"; a plan's `avoid` items stay in the package and reach only a model's negative channel (veo). The look block keeps rendering, palette, lens and grain; its place, season, weather and daylight are left unsaid where the scene names its own. Reason: image and video models read the words of a negation; config/factual_look.json's note and the lint already refused them; Codex's half-done rework had put FORBIDDEN_FACES blocks on every Nepal prompt. Evidence: aa170155 scene 4 (daylight and a beige lamp drawn over a lamp-lit night desk; people improvised when the motion prompt named nothing).

## ADR-DIRECTOR-TOKEN-BUDGET-X2 — role-scoped generation allowance (2026-10-11)

**Status:** Accepted by the Owner; implementation verified offline and runtime activated.

**Context.** The cyclotron QC review at 18:11 first produced an object whose four repair
reasons exceeded 400 characters, then returned no visible answer after consuming the
6,000-token completion allowance. The recorded counts do not prove a private-reasoning
token split. The Owner asks for twice the Director's allowance.

**Decision.** Scale explicit output limits once in `run_agent_task`, based on the resolved
`Role.name == "Director"`, rather than on model names or a single task. Configure
`STUDIO_DIRECTOR_TOKEN_MULTIPLIER` / `Settings.director_token_multiplier` with default 2
and bounds 1..4. Both structured QC attempts receive 12,000; the inbox receives 48,000.
Other roles and unspecified limits retain their behavior. Record requested/effective
limits and multiplier in each executed run's context. QC prompt v5 communicates the
existing schema bounds and logs invalid structured output accurately.

**Alternatives rejected.** Increasing only the QC call-site constant (leaves other
Director tasks unchanged); changing the studio's daily-token or USD limits (separate
Owner policy); weakening validation or retrying the historical film as a test.

**Impact and proof.** No migration or architecture-package change. USD/daily-token/STOP
gates, attempt count, private-reasoning handling and workflow history are preserved.
Nine focused regressions pass, including Director `None`; related suite remains
123 passed / 1 live skip. Ruff, mypy and
independent review pass. Controlled restart at 19:24 Bucharest: new server PID 2096,
live/ready 200 HEALTHY, worker OK, effective multiplier 2 verified. A larger allowance
can increase cost/latency and still return an invalid or empty answer; live-model QC
success is not claimed. Set multiplier 1 and perform the normal controlled restart
to restore the earlier allowance.
Detailed evidence: [DIRECTOR_TOKEN_BUDGET_2026-10-11.md](DIRECTOR_TOKEN_BUDGET_2026-10-11.md).

## ADR-DIRECTOR-PROMPT-LADDER — redo until QC passes, on corrected prompts (2026-10-11)

- Claim: Claude Opus 5.5 session 23d615c3, the Owner's rule of 2026-10-11 («Deci directoarea citește promptul și după îl cere la rescriere cu informații clare, ce să evite ca să treacă la QC!»).
- Done (699bc64, f98ffc8, 32585f1): `app.media.scene_rewrite` — for a scene QC refused (QC.CLIP, LOCAL.STILL_GATE) the Director reads its package, the prompts sent, the bible and the refusals' reasons and writes a brief (diagnosis, avoid, keep, change, layer); the Video Editor rewrites that one scene (compiled, linted, stored on that scene only); letters between them, settled. Motion layer keeps the still's words; still layer rewrites the picture and its motion; after a failed motion rewrite or a still-gate refusal only the picture; a still the Owner approved is never rewritten. `scene_memory` reads her rewrite as a decision (hold lifted, attempts counted again). `_film_staircase` runs her rounds (3 a walk, then a continuation). A paid redo after a failed film QC is bought only on a corrected prompt (PROMPT_NOT_CORRECTED). CLOSE for quality refused. Paid-redo limits default 5 a scene, 20 a film.
- Tested on fakes only: tests/test_director_rewrites_failed_scene.py (5) plus 196 + 314 + 127 related tests pass. Not yet proven on a real vendor: the cyclotron film aa170155 (scenes 4, 5) is walked after the 16:41 restart.

## ADR-2026-10-10 — the Director decides a failed film QC; only the budget reaches the Owner (2026-10-10)

**Status:** Accepted (Owner, 2026-10-10). **Commits:** 07153ad, baa2a11, 7f30429.

**Context.** The day's mechanical QC repair of film babcf272 redid the Owner's approved scenes 1
and 2 unasked and, with the GPU forced off, left both scenes with nothing to assemble. The Owner:
«ESTE DIRECTOR! ESTE RESPONSABILĂ DE PRODUCTIVITATE! La mine ajunge doar dacă este depășit
bugetul!» and «Scopul este să ajungem să publicăm, NU să facem reparații».

**Decision.**
- A failed film QC is decided by the Director: each finding real, false or the Owner's own
  choice; ACCEPT (a PASSED report), CLOSE, or REPAIR of the scenes she lists. Rights, the music
  licence and the production path are never hers to accept away.
- An unasked redo never retires a take the Owner approved (OWNER_APPROVED), unless he said yes
  to that plan; a redo that delivered nothing gives back what it retired, words included.
- A paid round that delivered nothing does not count toward the film's paid-redo limit.
- The voice licence is read from the ElevenLabs plan by API («Da, citește singur»); a film whose
  licence is unconfirmed is uploaded private rather than refused.
- Only an exceeded budget (his paid-media rule, the daily budget, the film ceiling) asks him;
  money gates (`may_act`, budgets, ceiling) are unchanged.

**Alternatives rejected.** Keeping the mechanical repair with a guard list (it would still
redo by rule what the Director should judge); asking the Owner on every failed QC (against his
operating model).

## ADR-PIXEL-PROFILES — front portraits and version-bound immediate action reads (2026-10-09)

The Owner's inspector screenshot requests front-facing faces with profile backgrounds. Keep
separate original front portrait art for all eight identity-bound employees; office ensembles
continue to face their monitors. Require exact identity, saved appearance and allowed role;
unknown/changed profiles use their own frontal authored fallback. One original built-in
imagegen output, copied unchanged. Provenance: art-source/pixel/front-portraits-v10/README.md.

A real disposable backend rehearsal exposed missing aggregate_version in live outbox payloads:
the page showed WORKING but retained version 1, refusing policy version 2. Include committed
aggregate_version in future live events. Read-only presentation policy refresh is now debounced
on scalar state/version/lifecycle changes, serialized across in-flight reads, Owner-epoch-bound
and retried only within configured timing. Mismatched/stale policies authorize no gestures.
Older event payloads trigger a coalesced authenticated committed-layout repair, without guessed
frontend versions. This also works against the current running backend without restarting it.

No schema migration or domain/Owner-policy change. Existing history remains immutable. The
bounded acceptance lane uses fresh disposable DB identities, real commits/outbox/WebSocket/HTTP,
faked paid vendors and denied outbound sockets. No production state commands. Original heavy
owner-flow game guard remains intact. Rollback source files from evidence before/ and rebuild;
retaining the additive event version field is compatible. Tests/report:
PIXEL_BACKEND_ANIMATION_ACCEPTANCE.md.

## ADR-PIXEL-LIVING — grounded ensemble, authoritative actions and bounded room life (2026-10-09)

Owner requests desk ergonomics, office chairs for everybody, Nadia angled toward her monitor,
varied backend-driven activity and a living office with sound. Original v8 art includes each
person/chair; fixed lower-body/caster layer plus registered upper poses prevents chair jumps.
Raise seat/pelvis over a longer stem, retaining wheel anchors and the existing 0.9 scale.
Per-seat floor/soles/furniture/gaze and per-screen corners are configured, not guessed each
frame. Nadia's rear-left chair mask and upright monitor glass are calibrated individually. The Owner
rejected the slanted board overlay: v9 locally replaces that board with original drawn LCD/
pedestal art. Only the registered repair polygon changes; screen content follows its glass.
Panel/desktop intersections are now refused, with an actual close-up and pixel-locality proof.

Read-only presentation endpoint phases actions from actual lifecycle/runtime/version.
Frontend springs blend only authorized actions; mismatch/expiry/stale main data rejects them.
A finite fresh authenticated HTTP snapshot bridges temporary socket loss. Physics is bounded
2D joint/contact/paper motion, not a claimed full 3D rigid-body scene. Room props stay limited,
cached and tied to actual available weather. No task/status/policy writes for cosmetic life.

Decode one eligible local film inside existing authenticated media roots with a 64 MiB cap;
map its pixels onto nine actual screen planes. Confirmed public/unlisted processed YouTube
films open in a correctly sized privacy player, with narrow CSP frame permission. Never read
cross-origin video pixels or insert fixture media into production. Current empty library is
reported honestly. Original WebAudio needs a user click and follows motion/state/contact.
Primary game presentation informed cadence/depth; no game sprites/audio copied and no claim
to enumerate every game animation. Source/proof/limits/rollback: PIXEL_LIVING_STUDIO.md.

## ADR-PIXEL-DEPTH — ground contact and native foreground silhouettes (2026-10-09)

Owner requests front/back throughout the UI; screenshot has traffic over near flowers.
Use floor/base depth independently of facing and roster order. Include dog/leash, cats,
bicycle, clock and vehicles in one street queue. Restore bounded original near foliage/
fence pixels above it, with transparent road gaps and cached matching light. Preserve the
approved PNG and personal seating. Clear empty chairs first, sort ensembles by floor,
paint dialogue last, choose nearest pointer target first. Configured night actor grading
keeps lamps emissive. Fix the independently reproduced narrow room-menu overflow without
changing its actions. Pixel/motion/weather/DOM/live proof: PIXEL_DEPTH_PHYSICS.md.

## ADR-PIXEL-STREET-REFINEMENT — proportional actors and full-width travel (2026-10-09)

Owner requests Playwright inspection, 10% smaller characters, normal street motion,
unblocked cat routes/left pedestrians and replacement car graphics. Central world-only
factor 0.9 preserves body/chair proportions and original floor anchors. Remove the x=147/156
street exclusions; configure route/cadence bounds. Cosmetic travel follows live visible
elapsed time without the paint-lag cap, retaining all pause/data/replay/hidden guards.
Two cats walk full independent patrols with short endpoint rests. Four original imagegen
vehicle silhouettes replace the old schematic; register uniform scale and rotate only
clipped hubs. Change model beyond the viewport; keep actual weather/lighting inputs.
No backend/identity/policy change. Actual and fixture proof: PIXEL_STREET_REFINEMENT.md.

## ADR-PIXEL-CHAIR-ENSEMBLES — whole seating assets and fixed lower body (2026-10-09)

Owner: «o mai buna abordare ar fi sa ii generzi cu tot cu scaun». This supersedes the separate
upper-body/shin/shoe fitting in ADR-PIXEL-SEAT-CONTACT. Generate the eight established Bible
identities together with their corresponding chair/stool. Register one uniform ensemble
with a floor anchor; no independent lower-body deformation. Keep a stable source ensemble
and continuously ease small head/forearm joints from the actual runtime state. Other drawn
state variations are source art, not directly swappable animation frames; retire automatic
cup/overhead-stretch switching. Remove the original empty chair only via its traced silhouette
and a generated clean plate. Original approved background remains unchanged; original
furniture/fallback returns if the ensemble or plate is unavailable. Keep all desk IDs/slots,
menus, motion/live/lifecycle/replay guards and actual status projection. No backend migration
or production policy change. Tests/evidence/provenance: PIXEL_CHAIR_ENSEMBLES.md.

## ADR-PIXEL-SCENE-MOTION — explicit animation preference (2026-10-09)

Owner: «si de ce nu se misca ? Oamenii pe strada nu se misca ?». Windows disables
client-area animation; inherited browser reduced-motion stops the entire illustrated
scene even when backend data are live. The Owner has repeatedly explicitly requested
living animated characters. Set the scene's configurable default to on and give it a
persistent local ANIMAȚII pause/resume control. Preserve system preference for menu/UI
transitions; do not change Windows. Cosmetic permission cannot override backend runtime,
lifecycle, stale/disconnect, replay, hidden or signed-out guards. Actual reduced-motion
browser regression and live recording pass. PIXEL_MOTION_RESUME.md records proof/limits.

## ADR-PIXEL-SEAT-CONTACT — pelvis and furniture silhouettes (2026-10-09)

Owner: «te rog sa ii asezi cum trebuie pe scaun!». Head alignment alone cannot put the
pelvis on the illustrated seat across poses. Register a per-frame hip and a per-desk
seat/floor contact; fit upper body/shins separately and retain shoe aspect. Three original
art edits make seated anatomy less crouched. Replace rectangular background restoration
with traced original chair/stool silhouettes. Preserve reserved slots/IDs/coordinates
and all furniture pixels. Reuse current painting calibration when the running backend
returns the preceding same-position desk config; browser regression covers it. No schema
or permission migration. All 48 poses visually reviewed, actual eight-agent seated UI
verified. PIXEL_ACTOR_REFINEMENT.md contains provenance, tests and rollback.

## ADR-PIXEL-ACTOR-ATLASES — detailed original frames at existing desks (2026-10-09)

The Owner rejected the crude actor study. Use five original generated RGBA sheets instead
of increasing schematic polygons indefinitely. Retain the original building/furniture and
code-drawn fallback; no downloaded game sprites or copied characters. Numeric source
registration normalises frame size/head alignment and fixes feet; Canvas composites raised
hands around the existing chair pixels. A generated staff appearance is used only for its
employee_id and matching Bible skin/outfit/hair/accessories. New or changed staff keep the
live fallback. Real runtime and lifecycle drive poses; cosmetic movement never creates work.
Four drawn walking/pedalling keyframes are held across eight ticks. Five sheets are cached
locally, with graceful fallback on failure and the existing motion/data/replay guards.
No schema or product permission change. Verification: 859 frontend/type checks, three
bounded browser, 53 scoped backend/docs and actual eight-agent UI video. Rollback only
this task's files and rebuild the combined current sources. PIXEL_ACTOR_REFINEMENT.md
records generated source/terms/prompts and exact evidence; paid acceptance stays separate.

## ADR-PIXEL-STUDIO-LIFE — one label and truthful cosmetic movement

Use one native name/effective-state tooltip, retain agent selection and remove canvas text
and outline. Role/state-driven keyboard/mouse/paper/headset gestures never change backend
runtime; waiting staff may breathe, look away, sip and stretch. Identity offsets avoid
lockstep phases. Draw foreground hands after the original chair pixels for visible motion.
Original procedural pedestrians/cyclist/car/cat/birds and clipped cached cloud drift enliven
the city without becoming employees/events. Actual weather controls umbrellas/reflections.
One capped cosmetic clock freezes when data/motion/lifecycle guards prohibit animation.
Approved art and fixed personal desks are unchanged. Actual production video proves eight
waiting staff move; fixtures test work/review/think separately. Preserve concurrent page-entry
changes during build and rollback. Research/provenance and verification: PIXEL_STUDIO_LIFE.md.

## ADR-LOCAL-AUTO-LOGIN — the key is handed to his own machine, the form stays for the rest

The Owner, 2026-10-08, with a screenshot of the title's key form: «Te rog sa elimini pagina de
logare, nu trebuie momentan». Decision: keep the Owner key on every route (require_owner and the
sockets' first message are unchanged) and remove only the typing of it on his machine. A public
GET /api/v1/owner/local-session answers {"token": <key>} only when all hold: the setting
STUDIO_LOCAL_AUTO_LOGIN is on (default true); STUDIO_HOST is loopback (bound to 0.0.0.0 or a LAN
address, a proxy or another machine could reach it with a loopback peer); the TCP peer is
127.0.0.1, ::1 or ::ffff:127.0.0.1; no Forwarded/X-Forwarded-*/X-Real-IP header (a reverse
proxy on this machine would make every remote visitor loopback); the Host header is exactly
localhost, 127.0.0.1 or [::1] with the studio's port (a DNS-rebinding page keeps its own name in
Host, so it is refused); an Origin, if sent, is http://<that Host>, and Sec-Fetch-Site, if sent,
is same-origin or none. The answer has no CORS header (another origin cannot read it) and is
Cache-Control: no-store; each refusal is the 404 of an unknown path; each hand-over is one INFO
log line without the key. The page asks first (same origin, no credentials, no cache, 4 s), keeps
the form hidden under «Se deschide studioul…», and enters through the same function as the form;
on any failure the form shows as before, so remote access is unchanged. The key stays in page
memory only. After a sign-out the form offers an empty-field entry; a later 401 signs out and
retries automatically at most once per page load. Accepted risk: any program already running as
a local user can read the key (as it could read .env); the boundary is this machine, as in
40_THREAT_MODEL's auth and least-privilege lines, which stay unchanged. Rejected: dropping
require_owner (any page on the LAN or a rebinding site could act as the Owner); a cookie session
(CSRF surface for every route); storing the key in localStorage (outlives the tab, readable by
any script on the origin). Off: STUDIO_LOCAL_AUTO_LOGIN=false.
Adversary review, same day: the request must also carry the page's own header
X-Studio-Local-Session: 1, so an <img>, <script>, frame, form, link, typed address, a no-cors
load from a browser that sends no Origin/Sec-Fetch-Site, or a program's plain GET is refused
without relying on browser metadata (a cross-origin fetch adding the header needs a CORS
preflight the studio never answers). The proxy list also refuses Via, X-Forwarded-Proto/Port/
Server, CF-Connecting-IP, True-Client-IP, X-Client-IP, X-Cluster-Client-IP and
X-Original-Forwarded-For (tunnels that add no X-Forwarded-For); the answer is
Cross-Origin-Resource-Policy: same-origin and nosniff; the route is left out of the API
description (docs and openapi.json are already off). Sockets and require_owner are unchanged.

## ADR-PIXEL-NAVIGATION-NIGHT — keep the frame, navigate the enlarged artwork

Preserve the fixed desktop menu layout; repair the pixel aspect-ratio override rather than
changing menu architecture. Fit shows all art; wheel/drag pan only when it exceeds the frame.
Do not capture native page scroll at fit/edges. Cache a connected sky-colour mask from the
unchanged approved illustration to retain roof/plants/cloud contours while hiding its fixed
sun at night. Existing solar calculation and real weather remain authoritative; stylised moon
is a night indicator, not an astronomical ephemeris. Actual signed-in UI verified separately
from bounded fixture weather tests. No backend/policy/migration/provider change.
Rollback and implementation evidence: PIXEL_NAVIGATION_NIGHT.md and its before/ backup.

## ADR-BACKUP-STALE-RECOVERY — refresh evidence instead of hiding the alert

A real stale backup is an operational recovery, not a reason to relax its 36-hour alarm.
Use the existing online-copy tool and inspect the existing scheduled task. It was queued
after restart and subsequently completed, so no scheduler refactor or policy override is
needed. Verify the real latest copy by restoration on an isolated target with its saved key.
Keep production autonomy and data in place; UI re-load reads the healthy current status.

## ADR-PYTHON-RUNTIME-RECOVERY — restore the declared base before project discovery

A Windows venv can remain after its managed base disappears. Probe it before uv run can
fail, restore only the .python-version target through uv (no registry/bin changes), then
probe again. Do not delete/recreate a healthy venv, downgrade SQLite or regenerate uv.lock.
Missing pin or restoration failure stops; restore needs internet and current uv metadata.
The installed uv 0.11.0 cannot download 3.14.8; upgrade its existing pip installation to
0.12.23 with binary backup. Actual fixture recovery and isolated complete server lifecycle
prove the fix; production data/policy and paid jobs remain unchanged. No architecture change.
Rollback: restore start.cmd and the prior uv installation from the task evidence backup.

## ADR-ROOT-START-COMPATIBILITY — one launcher, two entry paths

Root python start.py was missing; keep scripts/start.py authoritative and add only a thin
standard-library uv --locked wrapper. Avoid importing the application through the global
Python or duplicating bootstrap/server logic. Preserve argv, cwd, exit code and graceful
shared-console shutdown. start.cmd also uses --locked. No DB or architecture migration.
Twelve scoped cases and help probes verify delegation; no live worker is started by testing.
Rollback: remove the root shim and restore start.cmd from the task backup.

## ADR-PIXEL-OUTDOOR-CLOCK-WEATHER — actual Bucharest conditions on the existing painting

**Status:** Implemented locally, 2026-10-08; current verification limits in CURRENT_STATUS.md.

Reason: the Owner requests a pixel street clock, current time and real Bucharest lighting /
rain / fog / snow, preserving the approved furnished three-floor scene. Reuse the existing
office weather route, provider cache, timezone and solar helpers. Original procedural clock
and bounded particles need no external art or GPU. Mask all furnished interiors so live
outside effects do not erase approved room pixels. Make unknown/stale/historical weather
explicit rather than inventing a seasonal animation. Cancel timers/polling while hidden or
signed out, and discard late responses from the old authentication/location context.

Alternatives: a fixed dusk/season preset would contradict the requested current conditions;
a new browser-direct service would duplicate caching and conflict with same-origin CSP;
rewriting the painting would risk its approved details. No weather control or debug preset
is added to the production UI.

Migration: optional observed_at_utc metadata and timezone-inclusive cache key; no schema or
permission migration. Existing Open-Meteo host and București settings are retained. The
README/master/UI scope paragraphs deliberately clarify the weather exception; update only
their current SHA-256 entries, retaining every original hash and inventory item.

Validation: live read-only provider receipt, timestamp/owner-only/cache regressions, frontend
unit/type checks and isolated actual Canvas rendering. Full owner browser flows retain their
game guard; report any skipped run explicitly. Saved scene captures distinguish actual
provider observations from simulated rain/fog/snow/night cases. See CURRENT_STATUS.md.

Rollback: source/config/specification copies and served frontend backup are retained in
data/pixel-weather-2026-10-08/before. Restore the corresponding current documentation hashes
deliberately. No production DB/model/policy changes, worker, GPU or publishing job started.

## ADR-AGENT-SCENARIO-ACCEPTANCE — actual model decisions and independent backend gates

**Status:** Bounded live scenarios completed, 2026-10-08; external production acceptance pending.

Use existing services on disposable databases, retaining the original vault key only for
internal authenticated Ollama calls. The registry exposes LLM only, with no paid media/upload
adapter or production worker. Treat a safe refusal as a negative scenario success, never as
successful production. Preserve all failed attempts and harness corrections. First probes
kept the copied PRODUCTION policy because an environment attribute was unmapped; subsequent
probes use persisted TEST. Actual production fingerprint remains unchanged.

ADR-MAIL-WRITE-LOCK: reply, forward and resolve acquire the existing SQLite write lock before
reading. A competing commit after the read otherwise causes SQLITE_BUSY_SNAPSHOT. No provider
call is held inside the locked transaction. An event-driven concurrent-writer test fails
before the change and passes after it; no permission or message-schema change.

ADR-DEMO-DIRECTOR-SCHEMA: the requested Director decision schema wins over vocabulary in an
inbox report. Extract IDs from the inert inbox payload, not the JSON format example. This is
demo correctness and proves no live Director/vendor quality by itself.

ADR-SERIAL-SPOKEN-LENGTH: episode-v6 restates the measured spoken-word contract after inert
events/refused drafts. Keep all computed gates and existing autonomous retry caps. Real Kimi
sample finally passes at 124 spoken words after one draft and five rewrites; two last rewrites
include explicit test clarification. This is a successful bounded sample, not proof of normal
autonomous reliability. Track SERIAL_NORMAL_RETRY_ACCEPTANCE separately from safe refusals.

ADR-HERO-COST-PREVIEW: keep the executable motion plan unchanged; read-only sheet previews
use its existing whole-film quotes for scenes waiting on stills. Include pending quoted
motion in the implicit hero gate cap, retaining explicit caps and genuinely free reuse.
Five focused policy/cost cases and all four staircase dry runs pass (9/9). No approval is
created or spent by a preview and no scene is made ready through this projection.

ADR-SQLITE-RUNTIME: a temporary test DB reported corruption on SQLite 3.50.4. Its cause was
not conclusively reproduced; production integrity is good. That version predates the
[documented WAL concurrency fix](https://www.sqlite.org/wal.html#walreset). Use managed Python
3.14.8/SQLite 3.53.1 for the local project, verified directly and pinned in .python-version;
retain the prior environment and all locked packages. Repeat broad regressions after the
runtime change. Do not silently retry database corruption or label the known bug its proven cause.

ADR-SECRET-UTF8: detect-secrets opens text using the Python default encoding and silently
skips decoding failures. Force UTF-8 in the shipped CLI on Windows; a new fake key next to
Unicode punctuation fails the gate before any values are printed. Individually review 19
newly visible SHA-256 fixture hashes, explicitly annotate two font hashes and error prose.
Keep all detectors, thresholds and exclusions; do not regenerate an unreviewed baseline.

ADR-OPTIONAL-ANALYTICS-VAULT: VaultUnreadable while building a statistics adapter reports the
actual unavailable-credentials reason and skips only that channel, without API calls or
metrics. Do not weaken the mandatory daily preflight for a missing vault key. A keyless
two-day rehearsal proves a safe block, not completed autonomous production.

The exact normal serial stage made two Kimi drafts and safely rejected both. An isolated
Nemotron alternative timed out at the existing 600-second ceiling; no resend or promotion.
The production Writer stays on Kimi, with normal-retry serial acceptance still pending.

Correct stale tests without changing Owner authority, costs or publication protections.
Planning may import only pure RunPod configuration, never runtime provider adapters; scans
recognise both import forms and media constructors by their actual class name. Architecture
inventory and hashes are unchanged. Report: AGENT_SCENARIO_REPORT.md; receipts/logs:
data/scenario-acceptance-2026-10-08. No production GPU/media, upload, commit or push.

## ADR-OLLAMA-ROLE-ALLOCATION — current Cloud models and explicit assignment origin

**Status:** Saved and verified, 2026-10-08; evidence in CURRENT_STATUS.md.

Choose role models from the authenticated current Cloud catalogue and official capabilities,
then verify bounded role tasks before saving through existing policy/versioned commands.
Use Kimi K3 for direction, scripts and visual editing; MiniMax M3 for research; independent
DeepSeek V4 Pro for fact checking; Mistral Large 4 for multilingual voice direction and financial
document reasoning; Nemotron 3 Ultra for procedural publishing and the Director's existing
important-decision critic. Actual voice/media services and authoritative budgets remain separate.
Record the catalogue, sources and limits of this role-selection judgment; do not call sixteen
synthetic samples a comprehensive benchmark or infer all eighteen models were generation-tested.

Update only workforce configuration and existing assignment handling. Events explicitly
distinguish OWNER from SEED_ALLOCATION; an Owner choice matching the file must stay protected
when role preferences or seed data change. Keep minimal legacy Owner events protected and
retain the old slot comparison for legacy ensemble events with no origin. No new public
field, schema migration, architecture-specification change or capability hardcoding is needed.
All eight human-authorized choices are recorded explicitly and read back from actual UI services.
Backups and receipts live in data/model-routing-2026-10-08. Product permissions, prices,
budgets, staff, media selections and production scheduling are preserved.

## ADR-PRESERVE-DETAILED-STUDIO — retain approved furniture and add one floor

**Status:** Implemented locally, 2026-10-08; verification recorded in CURRENT_STATUS.md.

The Owner supplies 94139.jpg, approves its rich details and explicitly permits another floor
and back-facing employees. This supersedes clearing foreground furniture in the earlier
personal-desk refinement. Preserve studio.png, studio-desks.png and a project-bound copy of
the approved reference; edit the original studio through built-in image generation to add
one furnished floor. Keep the lower library/long desk/private office and editing/drawing/
lounge layout, plants, lamps, timber, roof, street and sunset. The active asset is
studio-detailed.png; the full generation prompt and provenance are recorded in
PIXEL_STUDIO_ASSETS.md and art-source/pixel/studio-detailed-prompt.md.

Bind the same eight reserved slots to eight actual illustrated seats across three floors.
Draw rear seated sprites, then restore configured chair/foreground pixels from the original
illustration at runtime. Remove generic code-drawn desks/screens and permanent nameplates;
hover/selection, the accessible roster and the existing inspector convey identity/state.
Retain face portraits, actual backend poses, stable reservations, annex pages and other menus.
No backend schema/permissions or production staff changes are required.

Review only the added Owner refinement in architecture/05_UI_UX_2D_OFFICE.md and update its
LF-normalized current SHA-256. Original inventory, original hashes and checker remain intact.
Verify actual browser pixels in protected library/lounge/monitor regions as well as seat
selection, committed state transitions, animation, stale/reduced-motion behavior and mobile.
Back up before editing: data/pixel-details-backup/before-details.zip. No production worker,
paid GPU generation, publication, commit or push is part of this local UI refinement.

## ADR-PERSONAL-PIXEL-DESKS — seated characters follow actual agent state

**Status:** Implemented locally, 2026-10-08; verification recorded in CURRENT_STATUS.md.

The Owner requests a personal desk for every employee, seated poses, finer characters and life
through animation. Reserve seats by immutable hiring order across all retained agent records;
the first known role holder gets its illustrated station, later employees get annex stations.
Pause, runtime updates and departures cannot compact this order or move surviving staff. A
shared JSON geometry drives the browser and backend. No schema migration or role permission change.

Layered original seated pixel sprites bind real Character Bible details by employee_id, with a
deterministic fallback. Runtime/lifecycle events select typing/writing, thinking/reviewing and
still pause/error/blocked poses. Idle blink/breath/glance is expressly cosmetic, never fabricated
work. Reduced motion, replay, lost/stale data and hidden pages suppress character animation.
Cache sprite frames and bound paints. Refresh authoritative versioned office rows every 15 seconds
and on reconnection/staff changes; older reads/events cannot rewind newer state. A run-completed
receipt does not override the employee's current runtime state, since newer work can overlap it.

Original scenery edited through built-in image generation removes foreground furniture so each
workstation is drawn with its seated owner. Previous artwork/source remains in the backup.
Review the Owner refinement in 05_UI_UX_2D_OFFICE and update only its LF-normalized current SHA-256;
do not change inventory count, original hashes or the checker. Existing menus and backend jobs
are retained. Browser state probes exist only in scripts/e2e_server.py's disposable, authenticated,
worker-disabled test server, with no external sockets; there is no production probe endpoint.
Evidence, actual browser captures and asset provenance: CURRENT_STATUS.md and PIXEL_STUDIO_ASSETS.md.

## ADR-SIMPLE-PIXEL-STUDIO — Owner scope supersedes Treasury and 3D headquarters

**Status:** Implemented locally, 2026-10-08; external RunPod authentication/paid acceptance pending.

The Owner explicitly requests simplification, retirement of Treasury, and replacement of
agents/environment with a stylish pixel interface inspired by A Space for the Unbound, while
retaining the other menus. Choose one browser Canvas, one original illustrated background and
deterministic original pixel employees. The scene loads no old HQ plates/weather/stream and
requires no GPU process. Backend states determine selection, portraits and working animation;
stale data and reduced motion suppress animation. Existing inspector/chat and factual replay remain.

Retire public Treasury, funding, minting, FX, virtual-ledger and financing module claims.
Keep actual USD budgets/prices/provider costs and existing internal accounting/historical data.
Replace its menu with Autonomie: current mode, environment, STOP, next scheduled run, links
to existing policy/scheduler/provider controls, costs and collapsed detailed preflight. Existing
versioned commands and permissions remain authoritative; no production policy is enabled here.

The Owner's instruction deliberately supersedes conflicting visual and virtual-economy specs.
Review/update only 00_MASTER_PROMPT, architecture README, 05_UI_UX_2D_OFFICE, 66_VIRTUAL_REAL_ECONOMY_ENGINE,
68_TREASURY_FINANCING_CAPITAL_STRUCTURE and 72_ECONOMY_STORY_WORLD_INTEGRATION. Prepend explicit
scope precedence, preserve historical text, and update only their LF-normalized SHA-256 index
records. Do not relax the integrity checker or alter original_sha256/inventory count.

Dirty source preserved before edits in data/simplification-backup/source-before-simple-pixel-studio.zip.
Old integration assertions are archived there; revised tests assert the active product contract.
Art references/origin: PIXEL_STUDIO_ASSETS.md. Operator entry point: SIMPLE_STUDIO_GUIDE.md.
Current verification evidence: CURRENT_STATUS.md. No paid GPU, publishing, production worker,
schema migration, permission increase or historical data deletion is part of this change.

## ADR-RUNPOD-ADDITIONAL-PROVIDER — reuse the Agency media pipeline

**Status:** Local implementation verified offline, 2026-10-07; real authentication/GPU tests pending.

The Owner requests RunPod as an additional premium image/video engine, with credentials and
endpoint to follow. Keep the existing provider interfaces, queued work, QA, VideoEditor,
SceneTake/MediaAsset, watchdog and financial gates. Add only a durable provider submission and
telemetry journal (migration 0055) and translations inside app.providers.runpod.

Official Serverless does not document an idempotency-header guarantee. Persist intent before
POST, recover saved IDs, retry only reads/proven unsent writes, and reconcile ambiguous outcomes
using backend proof. QA rejection alone creates a new creative attempt with feedback/history.
Forecast GPU USD feeds existing caps/accounting as ESTIMATED; never claim invoice/credit balance
or real model availability from a mock. Infra start/stop is optional and disabled by default.

The latest Owner instruction separately removes local ComfyUI/models. Preserve generated assets,
reports, voice selection and existing provider source; remove the installed runtime and obsolete
connection. This supersedes the earlier local-generation install/default milestone. No normative
architecture document was changed. Evidence/remaining external validation: RUNPOD_HANDOFF.md.

## ADR-GRAPHICS-OPT-IN — Ordinary startup excludes live graphics
**Status:** Implemented, 2026-10-04; supersedes the automatic launch in ADR-START-WITH-GRAPHICS

The Owner now asks for graphics to stop launching with the project. Make the launcher default
return before graphics setup, process probes or supervisor creation. `--graphics` explicitly
enables the existing lifecycle; retain `--no-graphics` for old commands and reject both flags
together. This covers start.cmd and the scheduled task, which use the same launcher.

A local-only --no-graphics shortcut would leave ordinary python starts unchanged; removing
the graphics subsystem would unnecessarily discard manual use. No schema, API or normative
architecture change. Tests cover default/explicit disabling without probes, opt-in supervisor
creation, conflicting flags, demo exclusion and the existing lifecycle: 85 scoped tests pass.
Rollback: restore launcher/tests from `output/graphics-opt-in-20261004/before/`, or explicitly
use `--graphics` for the previous startup behavior. An older running launcher must be restarted
to load edited code. No live stream was present in the read-only process inventory.

## ADR-SHEET-UI-002 — Production order and actual file state
**Status:** Implemented and visually checked, 2026-10-04

The Owner asked for a cleaner, correct shooting sheet with better placement. Four tall action
columns after dense scene cards hid the next action; a refused request could appear in a list
labelled bought clips. Use a compact overview, four production rows and full-width scene rows.
Keep technical information, alternatives, previous attempts and detailed budgets in disclosures.
Count current PAID/APPROVED takes only when a usable file exists; LOCAL motion/composed cards
keep separate labels. Recover a held hero through the existing priced redo plan, never a new
zero-price purchase. Price/cap, sheet/redo hashes, approval flow and backend checks stay authoritative.

No schema/API/spec migration. The alternative of a new generation endpoint was unnecessary.
10 new UI regression cases plus the full 795-test frontend suite, TypeScript/build and a read-only
real-sheet browser review pass. No provider call proves generation. Rollback: restore the three
frontend sources from this task's before-edit backups and rebuild; preserve unrelated edits.

## ADR-UI-ICONS-001 — One icon family, drawn once
**Status:** Implemented, 2026-09-23

The interface had no icon family. The seven room links under the render carried seven icons of
different construction and density, and every other icon in the product was a typographic
character borrowed from the UI font — `✕` for close, `↻` for refresh, `+` and `−` for the camera
keys, `▶` for play — at a different weight, a different measure and a different baseline from
the drawn ones.

Decided: every icon in the product is drawn on one 24×24 grid inside 4..20 of it, at one stroke
(`--icon-stroke`, stated once in the token block and read in the SVG's own user space), with
round caps and round joins, with no fill but the one dot a shape needs, and with
`stroke: currentColor` so an icon never states an ink and always inherits the control's — which
is what makes the hover, the disabled state and the alert triple work without a rule per icon.
The base is `.ui-icon` in `frontend/src/style.css`; the room icons stay inline in `index.html`
as they were; the four an ordinary script draws live in `frontend/src/icons.js`.

Two icons were replaced because they said the wrong thing rather than because they looked wrong:
the daily run was a house and is now the sun over a horizon (rejected: a play triangle — the
mark already means «a film» in the same row, and this dialog starts nothing), and distribution
was a circle crossed by a diagonal, which reads as a prohibition, and is now an upload.

Rejected: an icon font, and a sprite sheet. Both put the product's drawing outside the sheet
that states its measures, and neither can be checked by reading the markup.

Rollback is reverting `index.html`, `src/icons.js`, `src/style.css` and `src/office_scene.css`.
No behaviour, no id, class, `aria` role or test hook changed; 164 frontend tests pass unchanged.

## ADR-YOUTUBE-AVATARS-001 — API thumbnail identity and narrow image CSP
**Status:** Implemented and live verified, 2026-09-11

The connection snapshot already stored a URL, but the browser's same-origin-only image policy
blocked it. Select `snippet.thumbnails.high.url`, then medium, then default, skipping missing or
empty URLs. Keep the URL unchanged in the existing per-connection JSON snapshot. Authorization
and Verify already commit fresh snapshots; completed Reconnect uses the authorization callback.
The existing channel request includes snippet/statistics plus id/contentDetails so the stored
uploads-playlist metadata continues to work.

Allow only `https://yt3.ggpht.com` and `https://yt3.googleusercontent.com` in addition to the existing
image sources. Reject a broad `https:`/wildcard policy and an unnecessary backend image proxy.
Use a neutral CSS silhouette only when there is no API thumbnail, not to mask a failed image load.
No schema migration or channel-specific logic is needed. Rollback is a source rebuild/server
restart; snapshots remain compatible. Regression tests cover quality fallback, per-connection
refresh and CSP; live Chromium loaded both existing channel images at 800×800 after Verify.

## ADR-FOUNDATION-001 — Local modular monolith
**Status:** Implemented, 2026-09-09

Problem: the repository contained specifications only. Build the documented Phase 0 before integrations.
Choice: Python/FastAPI, SQLAlchemy, explicit Alembic migrations and file-backed SQLite; HTML/Tailwind/JS
with Vite. SQLite gives a Windows-friendly no-service setup. PostgreSQL and durable worker technology
remain later decisions and must pass their own tests. Synchronous DB endpoints run in FastAPI's thread
pool; later network adapters can use async I/O. No worker or queue is falsely implied.

State updates and domain events commit together. The initial event store is read directly; a durable
outbox publisher/WebSocket layer remains Phase 2. Immutable DB triggers protect event/command history.
Tests: migrations/schema comparison, rollback-on-error, race/idempotency and restart.
Migration: new empty schema only. Rollback: stop application and restore a verified backup; destructive
schema downgrade is deliberately absent.

References checked: [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/),
[SQLAlchemy SQLite transaction control](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html),
[Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html).

## ADR-FOUNDATION-002 — Early Owner control without premature autonomy
**Status:** Implemented, 2026-09-09

The Owner STOP flag is introduced early as a tested foundation primitive. A generated backend secret
authenticates Owner APIs; the browser keeps it only in memory. Clearing STOP does not promote autonomy:
mode remains Manual, advanced features remain unavailable. No provider, publish or payment route exists.
Phase 1 must reuse this policy boundary; Phase 2 must enforce it on admission and execution/cancellation.
Tests: unauthorized access, forbidden input, idempotency, stale versions, persistence and browser flow.

## ADR-FOUNDATION-003 — Authoritative documentation separated from source
**Status:** Implemented per Owner request, 2026-09-09

Move the 78 architecture/review Markdown files to `../architecture/`; keep the five original live
tracking files in this directory. Preserve source content, change only cross-folder document references,
and record original/current hashes in DOCUMENTATION_INDEX.json. Add root AGENTS/README entrypoints.
Local/CI checks reject missing documents and unreviewed architecture changes. Tracking files evolve
with implementation. No competing copies remain in the root. Any deliberate spec edit needs a logged
decision plus explicit hash update; automated checks never rewrite hashes.

## ADR-FOUNDATION-004 — Resolve inherited documentation identifiers
**Status:** Accepted, 2026-09-09

The inherited roadmap reuses phase 11–14 across v3/v4/v5; SRS also repeats FR numbers. Preserve original
normative text and use IMPLEMENTATION_PLAN.md's canonical phases 0–21. Reference repeated requirements
by document + section + title. This is naming/traceability repair, not a scope reduction.
V5's authorized provider-usage allowance does not grant outbound checkout/real-loan authority.

## ADR-FOUNDATION-005 — Lateral Cutaway Skyscraper Office & Procedural Animated Characters
**Status:** Implemented per Owner direction, 2026-09-09

Problem: The initial blueprint top-down circle avatar presentation did not provide depth, seniority hierarchy, or engaging character animation.
Choice: Switched 2D Office projection to a side-view cutaway multi-floor tower (cross-section architecture), inspired by simulation/pixel-art games (Space Haven, Anomaly President, Tiny Tower).
Hierarchical floors stacked from top to bottom by corporate seniority:
- Floor 4 (Penthouse / Executive Suite): Director / CEO (Sarah) with panoramic glass view, mahogany desk, and executive awards.
- Floor 3 (Research & Fact-Check Lab): Lead Researcher (Dr. Aris) and Fact Checker (Elena) with holographic network projection.
- Floor 2 (Creative Writing & Narrative Studio): Script Writer (Marcus) with cork storyboard and screenplay drafts.
- Floor 1 (Media Lab & Production Bay): Voice Artist (Lyra) in acoustic foam vocal booth & Video Editor (Kael) with triple monitors.
- Ground Floor / Level 0 (Infrastructure, Distribution & Lounge): Ollama & Cloud server racks with animated LEDs, Coffee lounge with rising steam, Release console (Vera), and working transparent elevator shaft with moving cabin.
Animated Characters (Personaje): Procedural sprite rendering with idle breathing, eye blinking, rapid typing when WORKING, glowing lightbulbs/sparks when THINKING, and responsive interactive click inspection.
Invariants: Visuals remain 100% data-driven projections of real SQLite state and live WebSocket domain events with zero simulated/fabricated state and strict CSP compliance.



## ADR-001 — Backend is the source of truth
**Status:** Accepted  
2D office is a projection of committed backend state/events.

## ADR-002 — Dynamic workforce
**Status:** Accepted  
Agents, roles, rooms and desks are data-driven.

## ADR-003 — Two-channel strategy
**Status:** Accepted  
Channel A = factual Shorts. Channel B = prior-day office serial.

## ADR-004 — Director as CEO
**Status:** Accepted  
Director manages operations within Owner-controlled guardrails.

## ADR-005 — Provider-agnostic integrations
**Status:** Accepted  
LLM/video/image/TTS/search/publishing are adapters.

## ADR-006 — Economy implementation is phased, architecture is core
**Status:** Superseded/Updated by V5  
The original economy placeholder has evolved into the core VR$ Treasury/Procurement architecture. Full implementation may follow the content MVP, but data contracts and hard money boundaries are first-class.

## ADR-007 — Multi-AI developer continuity
**Status:** Accepted  
Living documentation and explicit handoff are mandatory.

## ADR-008 — Intent/Capability/Outcome separation
**Status:** Accepted  
LLM statements never directly prove actions happened.

## ADR-009 — Durable workflow before full autonomy
**Status:** Accepted  
State, scheduler, retries and idempotency must be persistent.

## ADR-010 — Transactional event delivery
**Status:** Accepted  
Use outbox/equivalent to keep DB truth and UI events consistent.

## ADR-011 — Live dialogue vs serial dialogue separation
**Status:** Accepted  
Dramatized sitcom dialogue cannot enter operational logs.

## ADR-012 — Director cannot self-escalate
**Status:** Accepted  
Owner policy remains a higher immutable authority.

## ADR-013 — Local and always-on deployment modes
**Status:** Accepted  
Local PC is not assumed to run 24/7.

## ADR-014 — External web content is untrusted
**Status:** Accepted  
Prompt-injection/security boundary applies to research.

## ADR-015 — Media rights/provenance are first-class
**Status:** Accepted  
Assets need source/license/generation provenance.

## ADR-016 — Owner Policy Kernel
**Status:** Accepted  
Hard guardrails and approval rules are enforced outside Director prompts.

## ADR-017 — No hidden chain-of-thought dependency
**Status:** Accepted  
Store/display structured decision summaries, evidence and receipts, not private scratchpad reasoning.

## ADR-018 — Bounded multi-agent communication
**Status:** Accepted  
Agent message hops/rework loops have explicit limits and escalation.

## ADR-019 — Daily autonomous preflight
**Status:** Accepted  
Autonomous cycles check health, auth, quotas, budget, incidents and required providers before starting.

## ADR-020 — Admission control/backpressure
**Status:** Accepted  
Scheduler/orchestrator does not launch work beyond system/provider/budget capacity.

## ADR-021 — Public projection is separate
**Status:** Accepted  
Future fan UI consumes sanitized public projections, never raw internal event streams.

## ADR-022 — Technical identity separate from public character brand
**Status:** Accepted  
Provider/model names need not be public character names.

## ADR-023 — World Builder uses schema, not arbitrary UI code
**Status:** Accepted  
Director can evolve office only through supported backend world assets/layout operations.

## ADR-024 — Deterministic media fallback
**Status:** Accepted  
The studio must have a provider-independent fallback video format for resilient automation.

## ADR-025 — Multi-objective optimization
**Status:** Accepted  
Growth is optimized inside hard quality/rights/security/cost constraints.

## ADR-026 — CI/release pipeline outside content-agent autonomy
**Status:** Accepted  
Agents may optimize prompts/config but cannot autonomously deploy source-code changes.

## ADR-027 — Explicit privacy/data classification
**Status:** Accepted  
Internal/public/secret data boundaries are modeled and enforced.

## ADR-028 — Transfer-ready architecture
**Status:** Accepted  
Business assets/config should be exportable without personal credentials.


## ADR-V4-001 — Dynamic departments
**Status:** Accepted

The company may create/merge/dissolve departments through backend organization state; org chart is not hardcoded.

## ADR-V4-002 — Marketing becomes first-class future department
**Status:** Accepted

Marketing owns cross-platform communication and truthful teaser generation.

## ADR-V4-003 — Operational identity separate from narrative persona
**Status:** Accepted

Personality/birthday/relationships cannot modify permissions or factual standards.

## ADR-V4-004 — Company world events are separate truth category
**Status:** Accepted

Team building/birthdays can be committed in-universe events without being confused with physical operational facts.

## ADR-V4-005 — Organizational growth must resist bloat
**Status:** Accepted

CEO must justify new roles/departments using workload/value/cost evidence.


## ADR-V5-001 — VR$ is a one-to-one market-anchored virtual currency
**Status:** Accepted

Eligible verified USD inflows mint VR$ 1:1; actual USD operating costs and market-priced virtual purchases are represented 1:1. The studio does not autonomously spend real money.

## ADR-V5-002 — Three financial truth layers
**Status:** Accepted

External evidence, VR ledger, and forecasts are separate. Forecasts never directly become spendable cash.

## ADR-V5-003 — VendorShop uses market evidence but performs virtual purchases only
**Status:** Accepted

Procurement can research specific real products and prices, but checkout is never executed externally.

## ADR-V5-004 — Financing is virtual and reference-backed
**Status:** Accepted

CEO may use virtual financing with real-market reference terms, Finance/Legal/governance controls and real debt-service consequences inside the VR ledger.

## ADR-V5-005 — Asset Architect is downstream of purchase approval
**Status:** Accepted

A purchased product may become a persistent office-world asset only through an auditable specification and world-builder pipeline.

## ADR-PHASE1-001 — Ollama-first LLM adapter; stdlib HTTP; no async runtime
**Status:** Implemented, 2026-09-09

**Problem:** Phase 1 requires a real LLM connection. The project must not assume any particular provider.

**Choice:** Implemented Ollama as the first LLM adapter using Python stdlib `urllib.request` (synchronous HTTP). Async interface (`async def`) is used to satisfy the abstract contract, but the actual HTTP call is synchronous. `asyncio.run()` bridges the sync call from the synchronous service layer. This avoids introducing `httpx` or `aiohttp` as new dependencies before the durable worker layer (Phase 2) justifies them. The Ollama adapter returns `OFFLINE` (real status) if the process is not running — never a fabricated result.

**Alternatives rejected:**
- `httpx` async: adds dependency before Phase 2 worker needs it.
- `requests`: sync-only, no async interface.
- Mock-only path: violates "never mark as working based on mocks" rule.

**Migration:** When Phase 2 introduces an async worker, adapters can switch to async HTTP without interface changes (interface is already `async def`).

**Test impact:** `test_ollama_adapter.py` mocks `urlopen` for unit tests; real provider test is skip-marked until `STUDIO_OLLAMA_URL` is set.

**Rollback:** Remove `backend/app/providers/` and `backend/app/agents/` directories; revert migration to 0001_foundation.

## ADR-PHASE1-002 — Policy Kernel enforces all gates before every LLM run
**Status:** Implemented, 2026-09-09

**Choice:** A single `_assert_policy_allows_run()` function in `agents/services.py` enforces the complete gate sequence (autonomy_stop → lifecycle → capabilities → provider health) before any adapter call. Blocked runs are **persisted** in `agent_run` with a BLOCKED_* status — they are never silently dropped. This makes every policy decision auditable.

**Key invariant:** Director/Owner prompts cannot override the kernel; it runs in Python before the adapter is called.

**Test impact:** Tests directly verify each gate independently and verify the persisted blocked run record.

## ADR-PHASE2-001 — Durable Automation with Leases, Backoff, and Transactional Outbox
**Status:** Implemented, 2026-09-09

**Problem:** Unattended content production requires workflows and tasks that survive backend restarts, recover from crashed workers without duplicate side effects, route exhausted failures to a dead-letter queue, and stream events to clients reliably without ghost events on rollback.

**Choice:**
1. **Workflow State Machine:** Persisted in `workflow` & `workflow_step` tables tracking the 17 normative pipeline stages from `../architecture/47_STATE_MACHINE_SPECIFICATIONS.md`. Invalid transitions raise `InvalidStateTransitionError`.
2. **Task Queue with Time-Bounded Leases:** Workers acquire tasks atomically setting `lease_token` and `lease_expires_at`. Crashed workers' tasks are automatically reclaimed by other workers after lease expiry. Heartbeat extends active leases.
3. **Exponential Backoff & Dead-Letter Queue:** Retryable errors calculate exponential backoff (`backoff_seconds * 2^(attempts-1)`). Max attempts exhausted transition tasks to `DEAD_LETTER`. Operator intervention can revive them.
4. **Transactional Outbox:** Events are written with `append_event_with_outbox()` inside the active business transaction. Rollback discards both `domain_event` and `outbox_record`. Dispatcher pushes to WebSockets and marks `PUBLISHED`.
5. **WebSocket Gateway with Replay Protocol:** `/api/v1/ws` authenticates with Owner token, handles live push, and processes `replay` commands with `after_sequence` cursors so clients never lose state on reconnection.

**Test impact:** `tests/test_phase2_workflows.py` verifies all 10 automation capabilities.

## ADR-PHASE2-002 — Ollama Cloud Models & Dynamic Discovery
**Status:** Implemented, 2026-09-09

**Problem:** Ollama can run and proxy cloud-backed models (e.g. `glm-5.2:cloud`, `kimi-k2.6:cloud`, `qwen3-coder:480b-cloud`) in addition to local models. Newly available models must be continuously discoverable.

**Choice:**
1. `OllamaProvider` supports optional Bearer API key authentication and tags cloud models with `is_cloud=True`.
2. Added `sync_provider_models(engine, registry, provider_id)` service and `POST /api/v1/providers/{provider_id}/sync-models` endpoint.
3. Discovered models are recorded in `model_record`, automatically linked with `text_generation` capabilities, and emit `provider.model_discovered` domain events for auditability.
4. Models that are removed or unavailable are marked `is_available = False` rather than deleting historical records.

## ADR-PHASE3-001 — Lightweight 2D Canvas Office Rendering Engine
**Status:** Implemented, 2026-09-09

**Problem:** The Studio requires an interactive top-down 2D office visualization showing zones, desks, server racks with real-time blinking LEDs, agent avatars with state rings, and live speech bubbles, within strict resource limits (target <100MB RAM, 60fps, minimal bundle size). Heavy game frameworks would bloat the bundle size and introduce complex external dependencies.

**Choice:**
1. **Lightweight Canvas 2D Engine (`OfficeEngine`):** Pure HTML5 Canvas 2D implementation with custom `Viewport` supporting pan, smooth zoom (0.4x to 2.5x), DPI awareness (`devicePixelRatio`), and `fitToOffice()`. Total JS bundle remains tiny (~19 kB).
2. **Zero Simulated State:** Office state (`OfficeState`) strictly mirrors backend state retrieved from `GET /api/v1/office/layout` and updates via the live WebSocket `/api/v1/ws` event stream (`agent.state_changed`, `agent.paused`, `agent.resumed`, `agent.message_sent`, `workflow.*`).
3. **Data-Driven Zone & Desk Configuration:** Backend defines the 8 canonical production zones (`DIRECTOR`, `RESEARCH`, `SCRIPT`, `AUDIO`, `VIDEO`, `PUBLISH`, `SERVER`, `LOUNGE`) with fixed coordinate boundaries and desk positions.
4. **Direct Operator Controls:** Agent Inspector modal allows the Owner to inspect agent metrics, issue single tasks, and pause/resume agents via `POST /api/v1/agents/{id}/pause` and `POST /api/v1/agents/{id}/resume`.

**Test impact:** `tests/test_phase3_office.py` (backend layout, pause/resume) and `frontend/tests/office_engine.test.js` (viewport, office state) verify end-to-end functionality.

## ADR-PHASE4-001 — Factual Verification Matrix, Content Gate Hard-Stop, and Zone D Isolation
**Status:** Implemented, 2026-09-09

**Problem:** Content generated by autonomous AI agents easily suffers from hallucinated statistics, outdated facts, or prompt injection attacks embedded inside untrusted web sources. In addition, production channels must avoid spammy, repetitive content.

**Choice:**
1. **Zone D Sanitization & Inert Tag Boundary:** External web content is treated as untrusted (Zone D). Delimiters (`<|im_start|>`, `### System:`, etc.) are stripped, adversarial injection patterns (`ignore previous instructions`, `reveal system prompt`) are neutralized, and content is encapsulated within `<untrusted_source_evidence hash="...">` tags.
2. **Immutable Source Snapshots & SHA-256 Hashes:** Every ingested research document receives an immutable SHA-256 digest (`content_hash`) in `source_snapshot` to guarantee provenance and auditability.
3. **Atomic Claim Extraction & Verification Matrix:** Facts are extracted as individual `FactualClaim` records with explicit importance (`CRITICAL`, `SUPPORTING`, `FLAVOR`) and initial status `UNVERIFIED`. Fact Checkers independently verify each claim to `SUPPORTED` or `REFUTED`.
4. **Normative Content Gate:** In accordance with `../architecture/50_CONTENT_GATE_MATRIX.md`, the backend hard-blocks script generation (`FactualGateError`) whenever any referenced claim is `UNVERIFIED` or `REFUTED`. Blocked attempts are recorded as `BLOCKED_UNVERIFIED_CLAIMS` with domain event `factual.script_blocked_by_gate` for complete operator visibility.
5. **Deduplication Novelty Scoring:** Candidate topics are evaluated against recent historical topics (`../architecture/44_CONTENT_DEDUPLICATION_NOVELTY.md`) to compute a novelty score (0.1 to 1.0) and prevent repetitive content loops.
6. **Hook Optimization:** Formulates opening hook variations classified by proven psychological techniques (`CURIOSITY_GAP`, `CONTRARIAN`, `STATISTIC_SHOCK`, `STORY_IN_MEDIA_RES`) with estimated retention scores.

**Test impact:** `tests/test_phase4_factual.py` verifies all 8 factual intelligence invariants and endpoints.

## ADR-PHASE5-001 — Media Production Pipeline, Deterministic Synthesis, 9:16 Video Assembly, and 4-Tier QC Engine
**Status:** Implemented, 2026-09-09

**Problem:** The Studio must transform verified factual scripts into vertical 9:16 video shorts/reels (1080x1920) with synchronized speech, visual prompts, and subtitles, without depending on paid third-party media APIs during local testing, while strictly preventing visual factual errors and character drift.

**Choice:**
1. **Character Bible Foundation (`character_bible`):** Pre-seeded 7 core canonical studio employees (Sarah, Dr. Aris, Elena, Marcus, Lyra, Kael, Vera) with immutable visual descriptors, distinct hex color palettes, signature role symbols, and voice profiles.
2. **Deterministic Media Synthesis:** Developed `DeterministicVisualAdapter` (generating valid 1080x1920 SVG visual cards) and `DeterministicTTSAdapter` (synthesizing valid RIFF/WAVE audio bytes with exact duration and word alignment) to enable 100% reproducible, zero-paywall testing.
3. **Strict Content Gate Enforcement:** Storyboard generation strictly blocks unapproved scripts or scripts with unverified claims (`FactualGateError`), upholding normative truth invariants.
4. **Synchronized Subtitle Engine:** Formats scene cues and durations into standard SRT subtitle tracks for on-screen captioning.
5. **Video Assembly Engine & Cryptographic Provenance:** Assembles scene assets into vertical 9:16 MP4 containers via local FFmpeg (or standard ISO Base Media File container fallback) and computes an immutable SHA-256 digest (`provenance_hash`) recorded in `media_asset` and domain event `media.video_rendered`.
6. **Automated 4-Tier Quality Control (QC) Engine (`quality_control_report`):**
   - *Technical QC:* Verifies 1080x1920 resolution, 9:16 aspect ratio, non-zero duration, valid file size, and presence of SHA-256 provenance hash.
   - *Rights QC:* Verifies studio proprietary licensing and approved synthesis engines.
   - *Factual QC:* Verifies 100% of claims referenced across all scenes remain in `SUPPORTED` status.
   - *Character Drift QC:* Verifies characters adhere to Character Bible visual profiles without prohibited deviations.
7. **Frontend Media Production Modal (`#media-modal`):** Responsive dark-theme UI providing Storyboard pipeline inspection, interactive 9:16 video player preview, QC scorecard breakdown, and Character Bible viewer.

**Test impact:** `tests/test_phase5_media.py` (7 tests) and Playwright E2E verification test suite (`scratch/verify_phase5_e2e.mjs`) pass with 0 errors and 0 CSP violations.

## ADR-PHASE6-001 — Autonomous Publishing & Distribution, 5-Point Publishing Gate, Default Private Upload, and Idempotent Reconciliation
**Status:** Implemented, 2026-09-09

**Problem:** Autonomous AI Studio must publish finished 9:16 vertical video assets to official distribution channels (YouTube Shorts) without human intervention while strictly guaranteeing:
1. No unverified, un-QC'd, or policy-stopped content ever reaches public platforms.
2. Default upload privacy must remain `private` to avoid premature public exposure without human Owner policy clearance.
3. Zero duplicate uploads on network dropouts, retries, or server restarts.
4. No external paywalls or live credentials required for local CI test suites.

**Choice:**
1. **Channel Records & Brand Assets (`channel_record`, `channel_brand_asset`):** Pre-seeded Channel A (`MAIN_FACTUAL`) and Channel B (`OFFICE_SERIAL`) with canonical channel IDs and brand taglines, defaulting `upload_privacy_default="private"`.
2. **5-Point Publishing Gate Hard-Stop (`evaluate_publishing_gate`):**
   - *Autonomy Gate:* Blocks upload if Global Autonomy Stop is active (`OwnerPolicy.autonomy_stopped == True`).
   - *Disk Existence Gate:* Blocks upload if target file does not exist on disk or has 0 bytes.
   - *Quality Control Gate:* Blocks upload if `QualityControlReport` is missing or status is not `PASSED` (score < 0.90).
   - *Factual Integrity Gate:* Blocks upload if any factual claim associated with the video script is not in `SUPPORTED` status.
   - *Duplicate Protection Gate:* Blocks upload if media asset has already been published or is in-flight on the target channel.
3. **Official YouTube Data API v3 Adapter (`YouTubeProvider`):** Implements Google OAuth2 token refresh, resumable upload chunk protocol, synthetic media declaration flag, remote status polling, and title/idempotency key reconciliation before retry.
4. **Deterministic Publishing Adapter (`DeterministicPublishingAdapter`):** Provides zero-paywall simulated YouTube Shorts upload and status querying for reproducible local verification and CI.
5. **State Machine & Idempotency Guarantee (`publication_record`):**
   - Transition states: `DRAFT_INTENT` -> `VALIDATED` -> `STARTED` -> `REMOTE_CONFIRMED` -> `PUBLISHED` (with `REMOTE_UNKNOWN` and `FAILED_RETRYABLE`).
   - Hard DB Unique Constraint `uq_channel_idempotency` (`channel_id`, `idempotency_key`) prevents concurrent duplicate upload records.
   - Ambiguous timeouts (`REMOTE_UNKNOWN`) require reconciliation query against remote channel before any retry attempt is permitted.
6. **Frontend Distribution Hub Modal (`#publishing-modal`):** Responsive UI inside the 2D Office skyscraper providing channel inspection, 5-point gate status, 1-click private upload execution, and publication history with clickable YouTube Shorts links.

**Test impact:** `tests/test_phase6_publishing.py` (6 tests) and Playwright E2E UI verification suite (`scratch/verify_phase6_e2e.mjs`) pass with 100% success and 0 console errors.


---

## D-AUDIT-001 — Post-audit truthfulness remediation (2026-09-09)

**Problem:** An independent audit (`AUDIT_2026-09-09_EXTERNAL.md`) found that the system reported
external state it had invented. Specifically: channel slots were seeded with fabricated
`remote_channel_id` values and a hardcoded `CONFIGURED` status; a missing OAuth configuration fell
back silently to the simulator, which returned `https://youtube.com/shorts/yt_sim_…` and was stored
as `PUBLISHED`; the renderer wrote an `ftyp` header plus JSON to a `.mp4` file when FFmpeg was
absent; QC verified the resolution and duration that the renderer itself had written to the
database, so the fabricated file passed with score 1.0; the character-drift check returned a
hardcoded pass; and `POST /media/storyboards/sample` inserted a `SUPPORTED` factual claim with an
invented evidence URL. Together these satisfied the entire publishing gate with evidence the
application had authored for itself, violating `AGENTS.md` ("never mark a provider integration or
production feature working based on mocks") and `../architecture/26_MASTER_ACCEPTANCE_CRITERIA.md` §A, §E and §G.

**Choice — refuse rather than simulate.** Every layer now fails loudly instead of substituting a
plausible artefact:

1. **Channel identity is derived, never assumed.** Seeding creates *slots* with no remote ID, no
   credentials and status `NOT_CONFIGURED`. `derive_channel_status()` is the only writer of that
   field: `NOT_CONFIGURED` -> `AUTH_REQUIRED` (real remote ID present) -> `AUTHENTICATED`
   (credential reference present).
2. **No provider fallback at runtime.** `get_active_publisher()` returns the official adapter or
   raises 503 `PublisherNotConfigured` naming the three settings required. The simulator is
   reachable only through explicit injection (`app.state.publishing_provider`) in tests.
3. **Simulated results are structurally distinguishable.** `UploadResult.simulated`,
   `PublishingProvider.IS_SIMULATED`, `sim:` identifiers, empty platform URL, terminal state
   `PUBLISHED_SIMULATED`, event `publishing.video_published_simulated`. The UI links only genuine
   `youtube.com` URLs and labels a simulated run "SIMULAT (nepublicat)".
4. **A render either encodes or fails.** The placeholder-MP4 fallback is deleted. Scenes are
   rasterised to PPM frames and encoded by FFmpeg into a real H.264 1080x1920 file; without FFmpeg
   the job is recorded `FAILED` and `RenderEngineUnavailable` surfaces as 503. No `MediaAsset` is
   created for a failed render, so no gate can pass on a non-existent video.
5. **QC measures, it does not trust.** Technical QC reads the file with `ffprobe` (video stream,
   resolution, duration) and recomputes the SHA-256 provenance digest, and fails when declared and
   measured values disagree. A new content-source check fails assets built from placeholder
   visuals. Character drift reports `NOT_IMPLEMENTED` with `passed: null` rather than `true`.
6. **No self-authored evidence.** `POST /media/storyboards/sample` is replaced by
   `POST /media/storyboards/demo-fixture`, which creates the claim as `UNVERIFIED` and the script as
   `DRAFT`. A claim reaches `SUPPORTED` only through explicit verification.
7. **A refusal is an audit record.** `create_publication_intent` commits the `BLOCKED_GATE` row and
   its `publishing.gate_failed` event before raising, instead of raising inside the transaction and
   discarding both.

**Consequence, accepted deliberately:** with no image/TTS provider and no OAuth credentials, the
studio currently cannot publish anything. That is the true state of the system; the previous
behaviour concealed it behind a green demo.

**Test impact:** `tests/test_truthfulness_gates.py` (10 tests) locks each invariant above.
`test_phase5_media.py` skips render tests when FFmpeg is absent rather than certifying a fallback;
`test_phase6_publishing.py` asserts the 503 refusal and the simulated terminal state. Suite: 87
passed with FFmpeg, 85 passed / 3 skipped without it.

## D-AUDIT-002 — Corrections to the Phase 6 decision record (2026-09-09)

The Phase 6 entry above described behaviour the code did not have. For the record:

- "Pre-seeded … with canonical channel IDs" — those IDs (`UC_main_factual_studio_01`,
  `UC_office_serial_studio_02`) were invented and correspond to no YouTube channel. Superseded by
  D-AUDIT-001 §1.
- "score < 0.90" — the gate checked only `status == PASSED`; the score threshold was never
  evaluated. It is now enforced (`QC_MINIMUM_SCORE`).
- "resumable upload chunk protocol" — the adapter read the whole file into memory and issued a
  single `PUT` with no `Content-Range` and no 308 handling. Chunked resume is now implemented.
- "synthetic media declaration flag" — no such field was sent. `containsSyntheticMedia` plus a
  disclosure line in the description are now sent.
- "reconciliation … before any retry attempt is permitted" — `reconcile_upload()` was defined but
  never called from anywhere. It is now invoked before retrying a `FAILED_RETRYABLE` publication.
- "5-Point Publishing Gate" per `../architecture/50_CONTENT_GATE_MATRIX.md` — the matrix's publish column also
  requires rights on the final package, platform policy, novelty on final metadata, brand strategy,
  budget, and Channel B continuity and narrative privacy. Those remain unimplemented and the UI now
  says so.

## D-AUDIT-003 — Script approval as an explicit, re-checked step (2026-09-09)

**Problem:** `generate_script_draft()` writes `VERIFIED_PASS`; `generate_storyboard_from_script()`
accepts only `APPROVED`. No code path moved a draft between the two, so a script created through
the real API could never be storyboarded. The media pipeline was reachable only through the
fixture endpoint that wrote `APPROVED` directly alongside a self-authored `SUPPORTED` claim.

**Choice:** add `approve_script_draft()` and `POST /api/v1/factual/scripts/{id}/approve`. Approval
is an explicit Owner command, and it **re-evaluates the factual gate at approval time** rather than
trusting the verdict recorded when the draft was written — a claim may have been refuted since
(`../architecture/50_CONTENT_GATE_MATRIX.md`, gate immutability). A failed re-check moves the draft back to
`BLOCKED_UNVERIFIED_CLAIMS` and emits `factual.script_blocked_by_gate` with `at: "approval"`.

## D-AUDIT-004 — WebSocket dependency (2026-09-09)

**Problem:** the `/api/v1/ws` gateway was implemented and unit-tested, but the locked dependency set
contained no WebSocket library, so the running server answered every handshake with 404. The
feature was documented as working; in the browser it never once connected.

**Choice:** `websockets>=13,<16` is a first-class runtime dependency, not an optional extra. Adding
it to `pyproject.toml` and `uv.lock` makes the shipped configuration match the documented
behaviour. Verified in a real browser: the handshake succeeds and the console is clean.

## D-DESIGN-001 — One colour system for the whole interface (2026-09-09)

**Problem:** the application shipped two unrelated visual languages. The original template is a warm
editorial palette (paper `#f5f4ef`, forest `#172927`/`#254e43`, gold `#ddae6a`); every screen added
after Phase 3 — the agent inspector, research, media and publishing dialogs, the camera toolbar —
was written in a Tailwind slate/sky palette (`#0f172a`, `#1e293b`, `#38bdf8`, plus purple and
magenta accents). The stylesheet held 97 distinct colour literals with no tokens, so each new
feature invented its own.

**Choice:**

1. **Tokens are the only source of colour.** `:root` defines paper, ink, brand, semantic-state and
   scene tokens derived from the template. Component rules reference tokens; a new literal in a
   component is a defect, because that is exactly how the interface drifted apart.
2. **Dialogs use the page surface.** They are cards on the same paper as `.panel`, not a dark
   overlay theme. Verified in the browser: all three dialogs compute the same background colour as
   the panels behind them.
3. **Semantic colours carry meaning, not decoration.** Success / warning / alert / info exist as
   background+border+ink triples so that "published", "simulated", "blocked" and "validated" stay
   distinguishable at a glance — the honesty work of D-AUDIT-001 depends on that distinction being
   visible.
4. **The 2D office stays dark but joins the family.** It is a night-time interior, so it keeps its
   darkness; its structural literals were retinted from slate blue to the brand's deep greens and it
   is framed like the template's office scene. Per-department accents (research screens, storyboard
   cork, audio meter, distribution console) and character details were deliberately left alone:
   they encode which floor you are looking at.
5. **No pictographic icons.** The emoji added to buttons, headings and badges were removed; only the
   template's typographic glyphs remain, and they inherit token colours. Labels were rewritten in
   sentence case.
6. **Contrast is measured, not assumed.** `scratch/verify_design.mjs` reads computed styles from the
   running page and fails below WCAG AA (4.5:1). Three tokens were darkened when it caught them.

**Test impact:** `scratch/verify_design.mjs` — 14/14 checks pass, worst pairing 4.87:1.
`scratch/verify_post_audit_e2e.mjs` — 27/27 unchanged. TypeScript check, Vite build and the six
frontend tests pass.

## D-DESIGN-002 — Office renderer rebuilt (2026-09-09)

**Problem:** the 2D office was thin: flat rooms, a handful of props, characters with almost no
individuality, and a scene that stopped at the building's edge. It also carried 82 ad-hoc colour
literals from the pre-audit palette.

**Choice:** `frontend/src/office_engine.js` was rewritten around four ideas.

1. **The backend stays the truth.** The renderer draws the zones, desks and agents the API
   reports, and posture comes only from `runtime_state` and `lifecycle`: WORKING types, THINKING
   holds a thought, PAUSED sleeps, everything else idles. Idle characters breathe, blink, sip and
   stretch — cosmetic motion that deliberately never includes typing, so no viewer can read
   activity into an idle studio. Screens, VU meters and the ON AIR lamp light up only for zones
   that actually contain a working agent.
2. **Scenery is labelled scenery.** Sky, skyline, traffic, trees and pedestrians are generated
   from fixed seeds and are wired to nothing. A passing car reports no event. This is stated at
   the top of the file so the next contributor does not attach data to it.
3. **Deterministic variety.** Every face, outfit, lit window and leaning tree comes from a hash of
   a stable id, so the studio looks rich but identical on each reload, and `Math.random()` appears
   nowhere. Seven agents produce seven distinct people from the same code path.
4. **Crisp pixels and a predictable frame cost.** The world is drawn once at 1:1 into an offscreen
   buffer and blitted with image smoothing disabled, so zooming enlarges pixels instead of
   blurring them. Static art (sky, skyline, building shell, furniture) is rasterised once into
   cached layers; only moving things are redrawn. Clouds are composited between the sky layer and
   the building layer, which is what stops them drifting through the offices.

The building now stands on a street: the horizon is derived from the backend building box rather
than fixed, which is what previously drew the road through the ground floor.

**Test impact:** `scratch/verify_design.mjs` 14/14, `scratch/verify_fullscreen.mjs` 10/10,
`scratch/verify_post_audit_e2e.mjs` 27/27, frontend unit tests 6/6, no console errors.

## D-DESIGN-003 — Scene corrections: scale, street, lift and the shop unit (2026-09-09)

Four defects reported against the first renderer pass, and what each one required.

**1. Pedestrians walked through the ground floor.** The pavement was drawn at the horizon while
the building's base also sat there, so passers-by overlapped the studio. The street is now a
stack below the base course — plinth, pavement, kerb, carriageway, far pavement — and the
standing line is placed so the tallest pedestrian clears the building entirely. The rule is
enforced by `streetGeometry()`, which is exported and unit-tested rather than checked by eye.

**2. The lift moved with nobody in it.** The cab used to sweep the shaft on a sine wave, which
showed motion the backend had never reported. It is now parked with its doors shut and reads
IDLE. It travels only when a workflow token changes to a stage on a different floor — the
project physically moving between departments — then waits at the delivery floor and returns to
the ground floor. With no workflow running, the lift never moves.

**3. Vehicles were half-scale.** A person is 34px tall in this scene, so a car is about 90px long
and 30px tall, a van taller, a bus 168px. Wheels, glazing and lamps were resized with them, and
the carriageway was deepened to 118px to hold two lanes. Street lamps were also cut back to the
building's flanks: a column across the open cutaway hid the studio behind it.

**4. Names were unreadable.** Nameplates now draw the name at double scale on an opaque plate
with a drop shadow, with the backend state in small type beneath it.

**Ground floor.** Made double height (200px, backend layout) and re-divided to add `ad_shop`, a
street-facing unit for selling advertising space: glazed front, awning, rate boards, counter.
It has no desks, so the renderer places no character in it — the shop is not staffed until the
backend says it is. The building grew to 740px and the layout to 1000px tall; the office layout
test now also asserts that zones on a floor do not overlap and that every desk stands on its
own zone's slab.

## D-DOC-001 — Documentation identifiers made unique (2026-09-10)

**Problem:** two documentation defects blocked unambiguous references. (1) `16_DECISION_LOG.md`
carried a byte-identical duplicate of the whole ADR-001…ADR-V5-003 block (an edit accident), so
every early decision appeared twice. (2) In `../architecture/02_SRS.md` the "v3 Additional
Functional Requirements" block reused identifiers FR-037…FR-066 that already exist in the base
list, so a citation like "FR-037" was ambiguous (base "Untrusted web content" vs v3 "Policy
Kernel"). ADR-FOUNDATION-004 had recorded the collision and prescribed citing by document +
section + title; the Owner then directed the collision be removed outright.

**Choice:**

1. **Decision log deduplicated.** The second copy of ADR-001…ADR-V5-003 was deleted verbatim
   (verified byte-identical before removal); ADR-V5-004/005 and all later entries were single
   occurrences and are untouched.
2. **SRS v3 block namespaced, not renumbered.** The v3 additional FRs are now
   `FR-V3-037…FR-V3-066`, mirroring the established `FR-V4-…` and `FR-ECON-…` namespaces in the
   same file while preserving the numeric suffix, so the historical mapping stays readable.
   Base FR-001…068 are untouched and now unique. NFR-013…021 never collided and keep their
   numbers. The normative text of every requirement is unchanged.
3. **Cross-references updated.** `../architecture/V3_FILE_BY_FILE_REVIEW.md` notes the rename next to its
   historical "Added FR-037–060" record; `../project/IMPLEMENTATION_PLAN.md` marks the recorded
   conflict resolved.
4. **Indexed hashes updated explicitly** for the two deliberately edited architecture documents
   (`../architecture/02_SRS.md`, `../architecture/V3_FILE_BY_FILE_REVIEW.md`) in `../project/DOCUMENTATION_INDEX.json`, per
   AGENTS.md; `original_sha256` values are preserved.

**Alternatives rejected:** renumbering the v3 block sequentially from FR-069 (breaks the visible
correspondence with the v3 revision record and collides with nothing today but reads as new
requirements rather than renamed ones); renumbering the base list (every existing citation in
tracking documents would silently change meaning).

**Test impact:** `scripts/check_docs.py` and `tests/test_documentation.py` pass with the updated
index; no requirement text changed, so no product tests are affected.

## D-TRUTH-002 — The seed may write intent, never observation (2026-09-10)

**Problem:** an independent re-audit of the whole tree found the original falsehood pattern
still alive in one place the earlier audit had not reached. `seed_initial_workforce` wrote,
at bootstrap and without contacting anything:

- `provider_record`: `local-ollama` at `http://127.0.0.1:11434` with `status = 'HEALTHY'` and
  `last_health_check = <now>`;
- `model_record`: `glm-5.2:cloud`, `kimi-k2.6:cloud`, `qwen3-coder:480b-cloud` with
  `is_available = 1`, `last_verified = <now>` and `discovery_method = 'DECLARED_BY_PROVIDER'`.

Nothing in that function makes a network call, so on a machine where Ollama is not installed
the studio still displayed a healthy provider health-checked at a precise timestamp and three
models verified at a precise timestamp. This is the same defect the Owner originally reported
as "it says the YouTube channel is configured, but it is not", reproduced against a different
subsystem. It was verified by inspection of a freshly bootstrapped database on a host with no
Ollama: the rows above were present exactly as described.

Two consequences made it worse than a cosmetic lie. The seeded provider had no adapter
registered at startup — `load_registry` only registers Settings integrations — so both the
health check and the model sync failed with "no adapter registered", and the Owner had **no
way at all** to replace the seeded claim with a measured one. And any agent assigned to those
"available" models failed at run time with the same message, while the interface said the
model was ready.

**Choice:**

1. **The seed records intent only.** The provider is written `NOT_CONFIGURED` with
   `last_health_check = NULL`; the models are written `is_available = False`,
   `last_verified = NULL` and `discovery_method = 'SEEDED_UNVERIFIED'` — a new value that says
   what is true, namely that this list came from configuration and not from the provider.
2. **`sync_provider_models` is the only path to a positive claim.** It is the only code that
   calls the endpoint, so it is now the only code that may set `provider.status = 'HEALTHY'`,
   stamp `last_verified`, or promote a row to `DECLARED_BY_PROVIDER`. It raises on failure,
   so reaching those lines means the endpoint answered.
3. **The Owner gets a working control.** `register_seeded_ollama` registers a live adapter for
   every seeded OLLAMA provider at startup (registering an adapter asserts nothing about
   whether the service is running), `GET /settings` returns those providers as
   `legacy_providers`, and Settings renders a card for each with a "Verifică și încarcă
   modelele" button. Until it is pressed the card states plainly that the endpoint has never
   been contacted and its models cannot be assigned yet.
4. **A failure says what failed.** `POST /providers/{id}/sync-models` maps a connection error
   to HTTP 503 with "Furnizorul nu a răspuns, deci nu s-a înregistrat niciun model" instead of
   a generic 500, and the frontend now shows the server's own detail for `/providers` as it
   already did for `/settings`.
5. **Migration `0009_unverified_seeded_provider`** withdraws the claim from databases that
   already carry it, in the conservative direction: an owner whose Ollama really is running
   restores the true state with one click, whereas leaving the row alone would keep asserting
   something false on every machine where it is not. Rows the provider genuinely declared
   during a sync are left untouched.

**Alternatives rejected:** probing Ollama during bootstrap (bootstrap must not depend on the
network, and a slow or hanging endpoint would block first start); leaving the models available
and merely relabelling the provider (the availability flag is what the Settings dropdown reads,
so the lie would survive where it actually matters); deleting the seeded rows entirely (the
Owner would lose the record of which models the studio expects, and the agents' assignments
with it).

**Test impact:** six new governance tests in `tests/test_truthfulness_gates.py` — the seed
claims neither health nor availability; a model becomes available only after the provider names
it, and only that model; a failed sync upgrades nothing; the seeded provider is checkable; an
unreachable provider reports 503 with an actionable message. `scratch/verify_provider_honesty.mjs`
checks the same rules through the running interface (8/8).

## D-P7-001 — Phase 7 analytics wired, with the simulator removed (2026-09-10)

**Problem:** roughly 40 KB of analytics code sat on disk passing ruff, mypy and pytest while
never executing: `main.py` did not mount the router, the models were absent from
`Base.metadata`, and no migration created the tables. Wiring it as it stood would have been
worse than leaving it dead. `get_analytics_provider()` fell back to
`DeterministicAnalyticsAdapter`, which manufactures 1,500–65,000 views, 40–75% retention and
3.5–11% CTR by hashing a video id. `ingest_publication_metrics` then took
`pub.remote_video_id or pub.id`, so a publication that was never uploaded would have been
"measured" under its internal row id. The numbers would not merely have been displayed: the
learning loop reads them back, turns them into Director recommendations, and those change the
topic and hook weights the studio writes to. A fabricated view count would have steered real
editorial decisions.

**Choice:**

1. **The simulator is gone.** `backend/app/providers/deterministic_analytics.py` was deleted,
   and a test asserts the module cannot be imported. Analytics report what a platform
   measured; there is no local substitute for that, so there is no fallback to reach for.
2. **No provider means HTTP 503**, with the same shape as publishing: `get_analytics_provider`
   returns the YouTube Analytics adapter built from a **VERIFIED** YouTube connection (or the
   pre-Settings environment credentials) and otherwise refuses, saying in the response that the
   studio does not estimate or simulate audience figures. Tests inject their own adapter
   through `app.state.analytics_provider`; production has no such door.
3. **Nothing is measured that does not exist.** Ingestion refuses (409) unless the publication
   is `PUBLISHED` and carries a real `remote_video_id`; the internal-id fallback is removed.
   A provider failure is a 502 and stores nothing.
4. **The YouTube adapter stopped ignoring the window.** It used to send a fixed
   2024-01-01…2026-12-31 range for every query, so a report stored as "24h" or "7d" covered all
   time. Each window now maps to the date range actually requested. Impressions and CTR come
   from the `impressions` and `impressionClickThroughRate` metrics; when the account does not
   return them the adapter retries with the core metrics and reports zero with
   `raw["impressions_reported"] = false`, instead of back-computing impressions from views as
   before. `total_videos` is no longer guessed from the row count, and the channel report's
   subscriber figure is labelled in `raw` as the net change over the window, which is what it is.
5. **`seed_default_strategy` fixed and called.** It pointed at two hardcoded channel ids that
   no database ever had, so the strategy would have been orphaned; it now looks channels up by
   `channel_type`, and `scripts/bootstrap.py` runs it. Every seeded weight is 1.0: the baseline
   expresses no preference because nothing has been measured.
6. **Migration `0010_phase7_analytics`** creates the four tables with the invariants as database
   constraints, not only service checks: a snapshot cannot store a negative count or a retention
   outside 0–100, and a recommendation cannot exist with fewer than three observations or a
   weight change beyond ±0.20.

**Alternatives rejected:** keeping the deterministic adapter behind a flag (a flag that can be
turned on is a fabrication that will eventually be believed, and this data feeds a control
loop); leaving the module unwired (the Owner cannot see the analytics they were promised, and
dead code drifts); shipping a UI panel in the same change (there is nothing true to show until
a channel is connected).

**Test impact:** `tests/test_phase7_analytics.py`, 11 tests. Total 163 passed, 1 skipped.

## D-UI-004 — The lift carries a visible courier; the ground floor got its volume (2026-09-10)

**Problem:** three defects in the same part of the scene.

1. The cab moved between floors with nobody in it and its **doors parted while travelling** —
   backwards from how a lift behaves.
2. The **ground floor read as emptier than the floors above** despite holding four departments.
   It is 200px tall against 130px upstairs, but every fixture stopped at desk height, leaving
   the top two thirds of a double-height volume bare.
3. `STAGE_COORDINATES` in `office_state.js` was a table of **hardcoded pixel positions that no
   longer matched the building**. After the rebuild, `RESEARCH` at y=140 landed in the executive
   suite, everything from asset generation to QC landed in the script room, and
   `READY_TO_PUBLISH` at x=1010 sat outside the wall, in the lift shaft. This was not only
   cosmetic: the lift is dispatched by which zone a token lands in, so the wrong coordinates
   sent the cab to the wrong floor.

**Choice:**

1. **The token's journey is drawn as a journey.** A floor change now runs a four-stage
   delivery: `summon` (the cab comes to the floor the work is on while a runner walks to the
   doors), `board` (doors open, the runner steps into the shaft), `travel` (doors shut, the cab
   carries the runner, visible through the glass), `alight` (doors open, the runner walks the
   work to where the token now sits). Doors part only while the cab is standing at a floor.
   The runner is not an agent and carries no name — it holds the same crate the token is drawn
   as, and the token is not drawn twice. Every stage descends from the one backend fact that a
   token changed floor; with no workflow running the cab still stands still with its doors shut.
   A second floor change is not started until the current delivery finishes.
2. **The tall ground floor is built.** `drawTallVolume` adds what a double-height street-level
   volume actually has above head height: exposed ducting on hanger straps, a service mezzanine
   with a railing, and pendant lights on their drops. `drawTallVolumeSign` mounts one fixture
   per department above the rail — a rack status wall for infra, a clock and corkboard for the
   commons, a dispatch board for publishing, an empty hoarding reading "YOUR AD HERE" over the
   shopfront. All of it is architecture: no fixture displays a figure, because a board showing
   numbers here would assert something the backend has not said.
3. **Stage placement asks the layout.** `STAGE_ZONES` maps each stage to a department *by the
   zone id the backend serves*, and the position is computed from that zone's own desks. A
   token is not placed at all until a layout has arrived — a guessed position is worse than
   none.

**Test impact:** six new frontend tests (17 total) covering the still cab, the full delivery
cycle, doors shut in transit, one delivery at a time, every stage landing inside a real
department, and no placement before the layout. `scratch/verify_lift_courier.mjs` drives the
running page through a real delivery and reads the engine's own trip state back (9/9).

## D-P4-002 — The research loop is reachable, and verification is independent (2026-09-10)

**Problem:** the whole Phase 4 chain existed in the backend and could not be driven by the
Owner. Sources could only be fetched by a shell script (`scripts/research_source.py`); there
was no endpoint to retrieve one, no way to list stored sources, and the Research panel showed
topics only. Verification had no interface at all. The first product milestone — manual topic →
real research → verified claims → script — was therefore unreachable through the product.

A separate defect sat inside the same area. `VerifyClaimCommand` takes a verdict, so any
"verify" control has to supply one. The obvious design — a single button that marks a claim
checked — would be a verdict with nothing behind it, and FR-038 asks the fact-check path to be
independent of the research path. Nothing recorded who extracted a claim, so that independence
could be asserted in a docstring but never enforced or audited.

**Choice:**

1. **The allowlist is configuration, not application state.** `STUDIO_RESEARCH_ALLOWED_HOSTS`
   in `.env`, empty by default, which disables retrieval entirely rather than meaning
   "anywhere". No endpoint, form or agent can extend it, and the retrieve command deliberately
   carries no host field — a request-supplied allowlist is not an allowlist. Both the settings
   validator and `RetrievalPolicy` now also refuse an entry naming this machine or a private
   range, so a mistyped or hostile configuration fails at start-up instead of turning the
   research feature into a reader of internal services.
2. **`POST /factual/sources/retrieve` and `GET /factual/sources`.** Each failure is reported as
   itself: 503 with no allowlist, 422 for a host outside it, 429 for a rate limit that is
   respected rather than worked around, 502 when the source does not answer. In every one of
   them nothing is stored. A stored source carries `credibility_score = 0` and a receipt with
   the digests of the bytes received and the text extracted, so any figure on screen can be
   traced to what was actually downloaded.
3. **Claim attribution (migration `0011`).** `extracted_by_agent_id` and
   `verified_by_agent_id`, both nullable, because a claim the Owner judged has no agent behind
   it and a placeholder id would be a fabricated record.
4. **`POST /factual/claims/{id}/verify-with-agent`.** A second agent — never the one that
   extracted the claim — reads the stored source and returns a verdict. Two things make it a
   check rather than a formality: the studio refuses (409) when no independent agent exists,
   instead of letting an agent confirm its own reading; and a SUPPORTED or REFUTED verdict must
   quote the source verbatim, matched against the stored text on words rather than formatting.
   **A verdict whose quote is not in the source is rejected whole and the claim stays
   UNVERIFIED** — a fluent verdict resting on invented evidence is indistinguishable from an
   invention, so it is thrown away rather than stored with a caveat. UNCERTAIN was added as a
   real outcome so a checker that finds nothing can say so instead of guessing.
5. **The panel offers both honest routes** — the agent fact-check, and the Owner's own recorded
   verdict with notes and an optional quote — and no single "mark verified" control. Each claim
   shows its status, the evidence under it, and whether an agent or the Owner decided.

**Alternatives rejected:** letting the request name an allowed host (the allowlist would be
whatever the caller says); a one-click verify (a verdict with no reasoning, and the content gate
downstream would then be gating on nothing); accepting a paraphrased quote (paraphrase is where
an invention hides); storing a rejected verdict with a warning flag (a stored SUPPORTED is read
back by the gate, and a caveat in a neighbouring column does not travel with it).

**Test impact:** `tests/test_research_ingestion.py` (19) and `tests/test_claim_verification.py`
(15). Total 199 passed, 1 skipped. `scratch/verify_research_loop.mjs` drives the panel through
refusal, retrieval, extraction and verdict (18/18).

## D-UI-005 — The agent inspector showed a model nobody had assigned (2026-09-10)

**Problem:** reported by the Owner — choosing a model per agent in Settings changed nothing in
the agent's panel. Two independent causes.

1. `index.html` carried `<strong id="inspector-model">glm-5.2:cloud</strong>` and `showInspector`
   never touched that element. Every agent displayed the same hardcoded string forever,
   whatever was assigned. The office layout did not carry a model at all, so there was nothing
   truthful to display even if the field had been filled.
2. `loadOfficeLayout()` ran once, at login. Even a correct field would have shown the state from
   before the change until the page was reloaded.

**Choice:** each office assignment now carries `model_id`, `model_name`, `provider_name` and
`model_is_available`, and the inspector renders three distinct states — no model assigned, a
model assigned on a provider that has never answered ("· neverificat"), and a model the provider
confirmed. Only the last enables the run button, because only the last can actually run.
Settings calls back into the app after every successful change and on close, so the office
reloads.

A third defect surfaced while testing this: `api()` replaced the server's explanation with
"Conexiunea nu a putut fi verificată" for every path except `/settings` and `/providers`. Every
refusal this backend writes is a sentence meant for the Owner — which host is not authorised,
why a provider did not answer — so the server's own detail is now preferred wherever there is
one, with the generic wording as the fallback.

**Test impact:** two tests in `tests/test_phase3_office.py` asserting each assignment carries its
own model and that availability is reported as the provider left it;
`scratch/verify_agent_model.mjs` opens all seven agents in the running page and compares each
against the backend (9/9).

## D-P4-003 — Scripts are written from verified claims, and cite them scene by scene (2026-09-10)

**Problem:** the last link of the Phase 4 chain was unreachable. `POST /factual/scripts/generate`
requires the full voiceover text and a list of claim ids, so the only way to produce a script was
to write it by hand and pass the ids by `curl`. Nothing in the product drafted one, nothing
displayed one, and the approval endpoint — which re-runs the factual gate — had no control at
all. With phases 0–3 usable and verification now reachable, this was the single step still
standing between the Owner and the Master Prompt's first product milestone.

The interesting question was not how to call an LLM for the text. It was what stops the text from
containing facts the evidence does not carry. A model writing "Hubble, launched in 1990 at a cost
of 4.7 billion dollars" from a claim about the launch year produces one true clause and one
invented one, in the same sentence, and the factual gate downstream cannot see it: the gate
checks the claim ids a draft cites, not the prose.

**Choice:**

1. **Only SUPPORTED claims reach the writer.** `agent_write_script` selects the topic's claims
   with status SUPPORTED and refuses (409) when there are none — a topic whose claims are all
   unverified has nothing truthful to write from, and a draft written anyway would only be
   blocked later, after the Owner had read it.
2. **Every scene names the claims it rests on.** The agent returns scenes, each with its
   narration and a `claim_ids` list, and the schema refuses a scene with an empty one. A framing
   sentence attaches to the claim it frames; there is no "non-factual scene" escape hatch,
   because that is precisely where an unsourced assertion would live.
3. **A citation that was not supplied rejects the whole draft.** Not the offending scene — the
   whole draft. An identifier the writer did not receive means that scene's narration came from
   somewhere other than the evidence, and there is no way to tell how far that reaches into the
   sentences around it. Nothing is stored, and the message names the scene.
4. **The stored voiceover is assembled from the scene narrations**, so the text the studio will
   speak is exactly the text that carries an attribution. It is not a separate field the model
   could fill with something else.
5. **The draft cites only the claims it used**, not every claim it was given: citing the whole
   catalogue regardless of use would make the attribution decorative.
6. **The panel shows a script scene by scene** with its citation counts and status, and offers
   approval only on a draft that has passed the gate. Approval re-runs the gate, and its refusal
   now says how many claims stopped being supported instead of returning a raw exception string.

**Alternatives rejected:** dropping an unattributable scene and keeping the rest (the remaining
prose was written by the same pass, under the same misapprehension); letting the model return a
free-form voiceover and attributing it afterwards (attribution reconstructed after the fact is a
guess); allowing scenes with no claims for hooks and outros (the hook is the most-watched
sentence in a short, and the least supervised place to put an invention).

**Test impact:** `tests/test_script_writing.py`, 12 tests. Total 211 passed, 1 skipped.
`scratch/verify_script_loop.mjs` drives the chain in the running page: no supported claim → no
script, gate blocks a draft citing an unverified claim, a fully supported draft passes, and
approval fails once a cited claim is refuted (11/11).

## D-P5-002 — Media adapters built ahead of the credentials, with the placeholder label intact (2026-09-10)

**Context:** the Owner will supply media credentials themselves, later. The work that can be
done before then is the part that decides what happens once they arrive, and that is where the
truthfulness risk sits — not in the HTTP calls.

**Problem:** `assemble_video_job` constructed `DeterministicVisualAdapter` and
`DeterministicTTSAdapter` directly, so a render was always placeholder content no matter what the
Owner configured, and the media entries in the Settings catalogue said as much ("Generarea nu este
încă conectată"). Wiring providers in naively would have created two new ways to lie: an adapter
that returned a plausible substitute when a vendor failed, and a render that kept the
placeholder label after real frames were used, or lost it before they were.

**Choice:**

1. **Adapters return what arrived, or raise.** `ElevenLabsTTSAdapter` and `OpenAIImageAdapter`
   call documented endpoints over HTTPS with bounded response sizes. A failure raises; there is
   no fallback asset, because a substitute would enter the pipeline and be reasoned about by QC
   and the publishing gate as though a vendor had produced it.
2. **Every number is measured from the bytes.** An MP3's duration is counted by walking its
   frame headers (`mp3_duration_seconds`), a WAV's from its own header, and an image's size is
   read from the PNG header — not taken from what was requested. The assembler cuts video to
   those durations, so a length estimated from the word count would desynchronise picture and
   voice while looking like a measurement. Where a vendor genuinely offers nothing — ElevenLabs
   returns no word alignment on this endpoint, the Images API takes no seed — the adapter
   reports nothing rather than echoing the request back as if it had applied.
3. **A URL-only image response raises** instead of being followed: fetching it would be a second,
   unvalidated request to whatever host the response named.
4. **Only a verified *and* selected provider is used.** `app/media/factory.py` resolves the
   integration chosen for the "image" and "voice" purposes and uses it only at `VERIFIED` or
   `ACCESS_VERIFIED` — the same rule publishing and analytics follow. `SAVED` means the key was
   typed in, not that the vendor accepted it, and a render started on unaccepted credentials
   would fail mid-pipeline after the Owner had been told it was under way. A catalogued vendor
   with no adapter yet (Runway) resolves to no provider: that is "no generator", not a silent
   substitution.
5. **The recorded provider name is the generator that actually made the frames.** One value
   drives the asset's `provider_name`, the `media.video_rendered` event and the QC report. With
   no provider the render still happens — a video to look at — and is labelled placeholder, so
   `content_source_qc` blocks it from publication exactly as before.
6. **Provider narration is joined by ffmpeg, not by byte surgery.** The placeholder path can
   splice raw WAV bodies because it produced them; a vendor's audio is whatever it encoded, and
   concatenating that by hand would corrupt a differing format silently.
7. **`GET /media/providers`** reports which generators a render would use, and states plainly
   that renders are not publishable without a verified image provider. It probes nothing, so it
   never asserts reachability — only what the Owner selected and verified.

**Alternatives rejected:** falling back to a placeholder when a vendor call fails (the render
would appear to have succeeded and the label would be the only trace); reporting the requested
image size (a provider may return another, and the asset would carry a measurement nobody took);
estimating narration duration from the text (the figure feeds the cut).

**Test impact:** `tests/test_media_providers.py` (18) and `tests/test_media_selection.py` (12),
including a full render proving that the placeholder block lifts only when a real generator made
the frames, and that the asset names it. Total 241 passed, 1 skipped.

## D-P5-003 — Research hands work to production, and the render says what it will be (2026-09-10)

**Problem:** with Phase 4 usable end to end, the chain stopped at approval. An Owner who had just
approved a real script — sources fetched, claims verified by a second agent, citations checked —
opened Producție media and found no way to carry it forward. The only creation control there was
"Creează fixture demo", which builds test data with a deliberately unverified claim. The two
halves of the studio were joined by a fixture.

A second, quieter problem sat next to it. Renders are placeholder content until the Owner
configures a media provider, and QC blocks placeholder content from publication. That is correct,
but the Owner only discovered it *after* pressing Randare and reading a failed QC report.

**Choice:**

1. **`GET /media/scripts/awaiting-storyboard`** lists approved drafts no storyboard has been
   built from, and the Media panel shows them as the first thing in the pipeline, with the scene
   count and the number of verified claims each rests on. Only APPROVED drafts appear: approval
   is what passing the factual gate means, and offering a draft that had not passed would invite
   starting production on unverified claims. A script leaves the queue as soon as its storyboard
   exists, so nothing is produced twice by accident.
2. **The storyboard is built from the panel**, through the same endpoint and the same gate as
   before. A refusal is shown as it comes back — the gate runs again at this step, and a claim
   refuted since approval must stop production here too.
3. **The render says what it will be before it is asked for.** The panel reads
   `GET /media/providers` on open and states plainly, as a warning, that without a verified image
   provider the output is placeholder content that QC will block. Learning that from a failed QC
   report is a worse way to learn it, and the fact is knowable in advance.
4. Approving a script in Cercetare now refreshes the production queue, so the handover is visible
   without reloading.

**Alternatives rejected:** letting production pick up any script and relying on the gate to stop
it later (the Owner would have built a storyboard, waited for a render and read a QC failure to
learn something the studio knew at the start); hiding the demo fixture (it is genuinely useful
for exercising the factual gate, and it is labelled as a fixture).

**Test impact:** three tests in `tests/test_media_selection.py` — only approved scripts are
offered, a script in production leaves the queue, and the endpoint is reachable. Total 244
passed, 1 skipped. `scratch/verify_production_handover.mjs` drives approval → queue → storyboard
→ render in the running page and confirms the asset is labelled placeholder and blocked by QC
(11/11).

## D-P8-001 — The studio may recommend changes to its own staff, and nothing more (2026-09-10)

**Problem:** Phase 8 asks for evidence-driven workforce changes. This is the most consequential
thing the studio can recommend, and the two obvious ways to build it are both wrong. Asking a
model what it thinks of an employee produces a fluent judgement with nothing under it. Letting
the studio act on its own conclusion makes an unaudited recommendation into a decision.

**Choice:**

1. **Evidence is counted, never asked for.** `measure_workforce` reads rows the studio already
   has — agent runs and their outcomes over a 30-day window, task queue backlog, dead-lettered
   tasks. No model is consulted about a colleague. The same call at the same moment always
   yields the same numbers, so a proposal can be re-derived from them.
2. **An unmeasured agent is unmeasured, not perfect.** An agent with no runs has
   `failure_rate: None`, not `0.0`. Zero would read as a flawless record and could support a
   favourable judgement nobody earned; the panel says "nicio rulare în fereastră".
3. **A small sample never becomes a recommendation.** Fewer than five runs in the window
   produces nothing, at any failure rate — four failures out of four is a bad day. The service
   refuses to build such a proposal and a CHECK constraint refuses to store one, so the rule
   survives a future caller that forgets it.
4. **The proposal carries its own evidence.** `evidence_json` holds the counts, the window and
   the status breakdown as they were read, and the panel displays them rather than only the
   conclusion. "The studio recommended it" is not something anyone can audit six weeks later.
5. **Failure proposes suspension, not termination.** A run fails for reasons that are usually
   the model or the provider rather than the person doing the work, and suspension is
   reversible. Termination exists but is not something the measurements reach for.
6. **The Owner decides, and `decide_proposal` will not let a caller pass for the Owner by
   omission.** It takes an explicit `owner_decision` flag and raises `AutonomousChangeBlocked`
   when a non-Owner approves — raised, not quietly downgraded to a pending proposal, so a caller
   that expected the change cannot continue as though it happened. Rejection requires a written
   reason: an applied change leaves its own trail in the event log, a refusal leaves none.
7. **Employment is a record, not a column.** `employment_record` gives each period of work its
   own row. `../architecture/47_STATE_MACHINE_SPECIFICATIONS.md` forbids TERMINATED becoming ACTIVE by editing
   state; a rehire opens a new period and leaves the closed one closed, so a return is an event
   with a history and not a flipped field.
8. **A hire is approved but not carried out here.** Which role, on which model, is a decision
   the studio cannot make for the Owner, so approval is recorded and the Owner completes it in
   Settings. Guessing would put an agent on a model nobody chose.

**Alternatives rejected:** an LLM performance review (a judgement with no measurement under it,
about a colleague, that would then be cited as evidence); proposing termination on a high
failure rate (the evidence does not distinguish a bad agent from a broken provider); letting the
studio suspend an agent autonomously while the `autonomous_firing_enabled` flag is off (the flag
would be decorative).

**Test impact:** `tests/test_phase8_workforce.py`, 19 tests, most of them about what is *not*
proposed. Total 263 passed, 1 skipped. `scratch/verify_workforce.mjs` checks in the running page
that an unmeasured agent is shown as such, that nothing is proposed without evidence, and that
the server — not just the form — requires a reason for a rejection (9/9).

## D-P9-001 — The serial is grounded in the day it dramatises (2026-09-10)

**Problem:** Phase 9 asks the studio to turn its own operating day into an ongoing workplace
serial. `../architecture/07_STORY_ENGINE.md` separates Operational Truth from the Narrative
Layer, permits dramatisation — jokes, pauses, compressed dialogue, comic framing — and forbids a
specific list of fabrications: a hire or departure that did not happen, a success or failure that
did not happen, invented view counts, an invented provider outage, a decision attributed to the
wrong person, staff who were not there.

Read closely, those are one failure with several faces: a beat about something the event stream
never recorded. So the design question was not "how do we write an episode" but "what makes a
beat checkable".

**Choice:**

1. **The log is counted, never narrated.** `close_daily_log` reads the domain event stream for
   one business date in the studio's own timezone and records what is in it — counts per event
   type, the roster, and the events worth dramatising. No model writes any part of it. The log is
   what every episode is checked against, so a narrative inside it would make the check circular.
2. **A closed day does not change.** Re-closing returns the stored log untouched, and the date is
   unique in the schema. Letting a log drift would let an episode become grounded after the fact,
   and having two logs for one date would give an episode a choice of records to be grounded
   against — which is no grounding at all.
3. **Every beat cites its events, and a citation that is not in that day fails the whole
   episode.** Not the beat: the prose around an invented citation was written under the same
   misapprehension, and there is no way to tell how far it reaches. The forbidden-fabrication
   list is enforced by this one rule — an invented outage or a fake hire has no event to cite.
4. **The cast is the day's roster.** A character named in a beat must have been employed that
   day. Putting someone in a room the record says they were not in is the same failure as citing
   an event that did not happen.
5. **A quiet day produces no episode.** `NothingHappened` is raised and the panel marks the day
   rather than offering a button that would fail. Manufacturing a story from an empty log is
   exactly the fabrication the spec forbids, dressed as productivity.
6. **The claim can be re-checked later.** `GET /story/episodes/{id}/grounding` re-reads a stored
   episode against its log and names any citation that is not there, so grounding is audited
   rather than trusted — including if a row were ever written past the check.
7. **Only narratable event types are offered as material.** A heartbeat is not a story beat, and
   a shorter list of real material is better than a long one that invites padding. Everything
   still counts towards the day's totals.

**Alternatives rejected:** letting the showrunner write freely and checking afterwards
(attribution reconstructed after the fact is a guess); dropping an ungrounded beat and keeping
the episode; summarising the day with a model before handing it over (the summary would become
the thing the episode is checked against, and it would already contain interpretation).

**Test impact:** `tests/test_phase9_story.py`, 21 tests. Total 284 passed, 1 skipped.
`scratch/verify_story.mjs` drives the panel and confirms a quiet day is reported as a fact, a day
is closed once, and no episode is stored when the writing fails (11/11).

## D-P10-001 — A run reports what it did, not what it was for (2026-09-10)

**Problem:** Phase 10 asks for the daily autonomous runbook from
`../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md`: a preflight, twelve stages in order, and abort
behaviour when something fails. Every earlier phase guarded against inventing a fact about the
world. Nothing in a daily run does that — and that is what makes this phase easy to get wrong.
The falsehood available here is quieter: a run that *reports* more than it did. A stage that
never ran because a provider is missing, left out of the list, reads as a stage that succeeded.
A preflight that rounds a missing capability up to READY produces a failure that arrives hours
after the Owner stopped watching. Neither needs a single false sentence to mislead.

**Choice:**

1. **The preflight never rounds up, and it probes nothing.** Each check reports one capability as
   present or absent, with the severity that follows from it; the verdict is the worst of them.
   Missing media providers *degrade* — the studio can still work, the output is unpublishable —
   while a stopped autonomy gate, no verified model, or no FFmpeg *block*. The DEGRADED summary
   says in words that stages will be skipped and output will be unpublishable, because the word
   "DEGRADED" alone invites being read as "fine for now". Nothing is called over the network: a
   preflight that made outbound calls would be slow, would fail for unrelated reasons, and would
   still only describe the instant it ran.
2. **The run's status is derived from its stages, never asserted.** `_derive_status` computes
   FAILED > BLOCKED > PARTIAL > COMPLETED from what the stages actually recorded. A stage
   returning COMPLETED cannot make the day completed while another was skipped.
3. **Every stage appears in the record, including the ones that never ran.** A stage with no
   implementation connected is recorded SKIPPED with that reason; the stages after a stop are
   recorded BLOCKED naming where the run stopped. A page listing three stages when the runbook
   has twelve would mislead by the arrangement of the page alone.
4. **A blocked preflight closes nothing.** The daily log is closed on a partial day — a partial
   day is still a day — but not on a day the studio never started. Writing a log for a blocked
   preflight would put an entry in the record for work that did not happen, and tomorrow's
   episode is checked against that record.
5. **A failed stage enters safe mode and stops autonomy.** An unattended studio must not carry on
   into the next day with an unexamined fault behind it. A second failure does not open a second
   record, because that would obscure when the incident began. Superseded in part 2026-09-17 (a
   transient fault fails the run without safe mode) and 2026-09-18: safe mode opens only for a P0 —
   a hard fault in media, publish or the day's log, or a database integrity error anywhere — see
   "Safe mode is for a P0, as the playbook defines one".
6. **Leaving safe mode requires a note and does not restart autonomy.** The note is kept.
   Examining an incident and deciding the studio should act again are separate decisions, and
   folding them into one click would let the second happen by accident while making the first.

**Alternatives rejected:** probing providers during preflight (slow, flaky, and still only true
for an instant); omitting unimplemented stages from the run record (the honest-looking version of
the same lie); letting a caller pass the run's status; auto-clearing safe mode on the next
schedule; restarting autonomy when the incident is closed.

**A note on the test fixture.** A freshly bootstrapped studio ships with the STOP gate closed, so
its preflight is correctly BLOCKED and no run starts. The Phase 10 tests were written assuming
the opposite and failed for that reason; the fixture now opens the gate explicitly, because these
tests are about what happens *after* the Owner has made that decision. The product default was
not changed to make tests pass.

**Test impact:** `tests/test_phase10_runbook.py`, 20 tests. Total 304 passed, 1 skipped.
`scratch/verify_runbook.mjs` drives the panel: the preflight names every check it made and its
verdict in words, reading it starts nothing, the run button follows the verdict, and a recorded
run shows all twelve stages with the skipped ones and their reasons (16/16 including the run
branch, which needs a verified model and is covered against a throwaway database — the script's
header says how, and that flag never means a provider answered).

## 2026-09-10 — Bucharest as scene timezone

Owner requested an outdoor electronic clock showing Bucharest time in 24-hour format. Use Intl Europe/Bucharest (h23), not a fixed UTC offset. Align street day/hour with this clock to avoid contradictory rhythms when the device is elsewhere. HH:mm refreshes each minute, with DST handled by the runtime timezone database. No schema change. 35 frontend tests and browser checks passed.

## 2026-09-10 — External street clock and CSP-safe scene CSS

Owner references call for a freestanding street display rather than a facade plaque. Place it outside the building on the right, preserving HH:mm Europe/Bucharest. Force Vite to emit the dynamically attached scene stylesheet via ?no-inline: its previous data URL was blocked by style-src, making the live controls appear at the top. Preserve CSP and concurrent dashboard controls. No migration; browser verifies loaded same-origin stylesheet and bottom dock geometry.

## 2026-09-10 — Resolve inspector assignments independently of legacy scene projections

Observed live layout lacks model fields even though Settings and agent records contain real assignments. Read agent and provider model catalogs when opening the inspector; never infer no assignment from missing scene fields. Distinguish failures and guard response ordering. Avoid unnecessary backend restart while concurrent development is active. No migrations or credential changes. 38 frontend tests and all 7 live agent comparisons passed without writes/provider runs. See `INSPECTOR_MODEL_FIX.md`.

## 2026-09-10 — Pixel office v2: design in Figma, render procedurally, never trade truth for polish

Owner asked for a commercial-grade pixel-art rebuild of the 2D agency with Figma as the design tool. Decision: the design system (palette variables, department material stories, HUD components, character sheet) lives in Figma and is mirrored one-to-one in `frontend/src/office_palette.js`; the room art itself stays procedural in Canvas 2D because a floor is tens of thousands of pixels and the backend layout decides geometry at runtime. The quality bar is one finished floor (Research, level 3) rendered from the same code that ships, uploaded to Figma at 4x. Rules kept: no backend change, no hardcoded data, posture from backend state only (typing only on WORKING, sleep only on PAUSED), lift only on token trips, street purely decorative. Static art is baked into cached layers so the target stays 60 FPS (measured 60 FPS, ~6 ms/frame). Character sprites are compiled from letter rows with an automatic hue-shifted outline; the same agent id always yields the same look and the role decides the costume. See `PIXEL_OFFICE_V2.md`.

## 2026-09-10 — AMN-AI: the stored studio name is domain state, not configuration

The agency was named AMN-AI (Autonomous Machine Nexus — Artificial Intelligence) and the name and logo had to be introduced across the product. Configuration, packaging, markup and documentation were simply updated. The studio row was not: `bootstrap_studio` writes `STUDIO_NAME` only at creation and never again, because the studio's identity belongs to the immutable history rather than to an environment variable read at render time — an existing database therefore kept displaying the old name in the workspace H1. Rejected: making bootstrap reconcile the row with `STUDIO_NAME` on every start, which would let an env edit silently rewrite domain state and would contradict the invariant the foundation tests protect. Chosen: `scripts/rename_studio.py`, an explicit Owner act that updates the row and appends a `studio.renamed` event (aggregate `studio`, next version, carrying `previous_name`) in one transaction, idempotent and refusing empty or over-long names. Applied once locally. Logo assets are derived from one source: the cube mark at icon sizes because the wordmark is illegible below ~120px, the full lockup only on the sign-in screen, quantised from 1.16 MB to ~8 kB per page load; the previous brand's unreferenced `favicon.svg` was deleted so no old identity is served. Distribution names became `amn-ai` and `amn-ai-ui` with both lockfiles regenerated and dependency resolution proven unchanged. See `BRAND_AMN_AI.md`.

## 2026-09-10 — Phase 11: the ledger records evidence, and refuses everything else

The economy had to start somewhere, and the choice was between building the treasury dashboard people can see (Phase 12) or the books underneath it. Built the books, because a dashboard over an unsound ledger is a more convincing lie than no dashboard. Decisions taken at implementation time, which the architecture audit left open: money is integer micros rather than cents, since provider usage bills in fractions of a cent and cents would round it away; only SETTLED revenue mints and only a BILLED invoice posts, keeping the two sides symmetric and the ledger a record of what happened rather than of what is expected; estimates are reported beside the books rather than accrued, because accrual needs a true-up path that has no reader yet; a treasury deficit is reported rather than blocked, because nothing spends VR$ yet and a freeze would have nothing to stop — enforcement belongs with procurement in Phase 13; and no command-idempotency table was added, because the unique evidence and invoice references already make every money-creating operation idempotent, which is the property that matters. Rejected: letting an agent mint (the spec calls minting a controlled ledger event, so the routes are Owner-only and no agent-facing path exists), and converting a foreign amount at a fetched-but-unrecorded rate (a conversion must be able to cite the snapshot that produced it). The demo script uses a throwaway database on a port it binds first: recording invented payouts in the Owner's real books and reversing them afterwards would still leave fabricated history in an append-only audit trail. See `PHASE11_ECONOMY.md`.

## 2026-09-11 — A YouTube connection proves itself; it is not described

The Owner asked to stop typing a refresh token and a channel id. The deeper reason to agree: those two fields let a connection be described correctly and be wrong. A pasted token carries no proof that whoever pasted it controls the channel, and a typed channel id is an unverified claim about which account that token opens; the publishing pipeline could not tell the difference. Decision: four manual fields (name, client id, client secret, redirect URI) and one button, with the Authorization Code flow issuing the refresh token directly to the studio and `channels.list` reading the identity back, so a row cannot name an account its grant does not open. `prompt=consent` is sent only when no refresh token is stored or the Owner pressed Reconnect — always sending it re-prompts a working connection, never sending it means a re-authorisation returns no refresh token at all. Secrets are not columns: the client secret and refresh token live in one Fernet blob, with a `secret_fields` list so a view can report CONNECTED without decrypting anything and no view model has a branch that could leak one. The callback route is public because Google redirects a browser to it, and its whole defence is a 43-character single-use state that dies in ten minutes. Failure states are written in their own transaction, after a test caught the first version setting `status = ERROR` inside the transaction whose rollback then erased it. Disconnect forgets the token locally before revoking it at Google, because the local half is the half the studio controls. Editing the client id drops the stored token rather than keeping a connection that reports CONNECTED and cannot mint an access token. Nothing is special-cased per channel: AMN-AI's two channels are not named anywhere in the code, and a test greps for hardcoded channel ids, client ids, secrets, tokens and account names. Verified in a browser against a throwaway studio driven through the real service functions with only the transport to Google stubbed, which is also how two defects were found: `window.open(..., 'noopener')` returns null, so the consent tab silently became a navigation of the studio's own tab; and `.secondary`, the affirmative button class used in roughly fifteen places across the admin surface, had never been defined in any stylesheet. See `YOUTUBE_CONNECTIONS.md`.

## 2026-09-11 — One way to connect a channel, not two

The OAuth section shipped beside the settings catalog, which still carried a `youtube` entry asking for a refresh token and an ID canal YouTube. The Owner saw it in the browser within minutes. Adding a good path next to a bad one leaves the bad one reachable, and a credential form is not a matter of taste: whichever form is filled in decides what the publisher believes about who owns the channel. Decision: delete the catalog entry and repoint every consumer at the connection — publishing credentials, channel binding, the analytics provider, the runbook preflight, and the purpose selections. Channel binding now takes a `connection_id` and copies the remote channel id from the grant, so a channel record cannot claim an account its credentials do not open; the API contract changed name because `integration_id` pointing at a connection would be a lie in the schema. Where more than one channel is connected and nothing names which, `selected_youtube` raises rather than returning the first row: AMN-AI runs several channels and publishing to the wrong one is not a recoverable mistake. Rejected: keeping the catalog entry with the two offending fields removed, which would leave two ways to describe the same channel and no way to tell which the pipeline used. A pre-existing bug fell out of the same change — the verification route branched llm → stored → else, and the else built a YouTube provider, so verifying an ElevenLabs or OpenAI media key raised, was swallowed by a bare except and reported FAILED every time; media and stored now share the vendor probe that always covered both. Verified in a browser: the social catalog offers TikTok, Instagram, Facebook and e-mail, and no label anywhere in the section reads Refresh token or ID canal. See `YOUTUBE_CONNECTIONS.md`.

## 2026-09-11 — An unanswered question is not a negative answer

The audit's central finding is one shape repeated in four places, and it is worth stating as a rule rather than as four fixes. Code is written for the answer arriving; the branch that runs when the question fails inherits the optimistic reading of the branch beside it. `get_video_status` returned "the video does not exist" when YouTube could not be reached. `reconcile_upload` returned "no previous upload" for the same reason, and its caller's next act is to upload. The factual gate, unable to trace an asset back to a script, fell through to a check reading "Asset has verified factual provenance" and passed. The same gate loaded the claim rows that existed and compared only those, so a claim id with no row behind it simply vanished from the comparison. Decision: a failed question raises `RemoteStateUnavailable` rather than returning a value that reads as an answer; an unresolvable provenance chain fails the gate and names the missing link; a dangling reference fails and is named. `../architecture/50_CONTENT_GATE_MATRIX.md` already made this distinction — NOT_APPLICABLE records a reason, it does not pass — and the code had collapsed it. Rejected: keeping the permissive behaviour behind a configuration flag, which would leave the studio one setting away from publishing a duplicate. Also decided: money-creating commands honour their `command_id` through the existing CommandRecord table, because the Phase 11 claim that unique external references made every such operation idempotent was true of evidence and invoices and false of Owner funding, which carries no reference; and the FFmpeg toolchain gets exactly one resolver, because three of them disagreeing is how a studio comes to report that an encoder it is configured to use does not exist. See `AUDIT_2026-09-11_INTERNAL.md`.

## 2026-09-11 — The clock is the Owner's to start

A scheduler existed that could be ticked and a queue that could be claimed, and nothing in the process did either on its own; "autonomous" meant a button pressed daily. The background worker closes that gap, and three decisions shape it. **The daily job is seeded dormant.** The Owner's studio has its autonomy stop cleared, so a job seeded active would have begun a real day — agents on paid tokens, a render, a closed log — within thirty seconds of the first restart, on a decision nobody took. The schedule exists from the first start-up; starting its clock is a recorded Owner act, `workflow.job_activated`, of the same weight as clearing the stop. Waking a dormant job whose slot is in the past sets the clock from now rather than firing on the spot, for the same reason. **A missed slot fires once under either policy.** `../architecture/09_CHANNELS_AND_AUTOMATION.md` forbids a backlog explosion after an offline period; SKIP and CATCH_UP differ only in the cadence afterwards, one re-anchored to now and one kept on the original anchor. The field had been decorative. **The slot names the task.** A fired job enqueues a task keyed on the job id and the slot it was due for, so a restart that puts the slot back — or a second scheduler leader after a lapsed lease — finds the queued work rather than duplicating it; the tick had created a workflow row and enqueued nothing, so nothing could have run it. Also decided: the scheduled daily run happens at most once per business date, because a second run on the same day is the Owner continuing after an approval, not the clock; and a task with no handler is dead-lettered with that reason rather than retried into the ground. The worker is off under test, where a loop that starts the day on its own would make every other test's timing a coincidence; it has its own tests, driven by hand, and a demo that starts the real server process and waits for a run to appear without touching anything. Rejected: a fixed local hour for the daily job, which is the right shape and needs a column; the interval-based schedule with CATCH_UP holds the anchor until then.


The runbook walked twelve stages and asked `app.state.stage_runners` for the work of each; nothing in the application ever set that attribute, so every run in production recorded preflight and eleven SKIPPED. The framework was honest and idle. Decisions taken while connecting real work to it. **COMPLETED means the stage ran to its end; SKIPPED means it could not run.** A research stage that finds no sources has completed — it looked, and there was nothing; one with no language model configured has been skipped. Collapsing the two is how a runbook comes to imply work it never did, so every stage reports a count as well as a reason. **A refusal is not a failure.** A model that writes narration it cannot attribute to a verified claim has its draft rejected and nothing stored, which is the pipeline working; the first version let that raise, and because the runbook stops the day at the first FAILED stage, one unusable draft left the daily log unclosed and every later stage BLOCKED. Rejected scripts and rejected episodes are now counted and reported by a stage that completes. **Where a person decides, the studio stops.** Clearing the autonomy stop is what authorises a run at all, but it is not approval of a particular script: a draft is left at VERIFIED_PASS, storyboarding requires an APPROVED one, and publication still passes the five-point gate that re-checks the stop, the file, quality control, factual provenance and duplication. **Two stages stay unwired on purpose.** `idea_generation` has no implementation — topics are proposed by the Owner — and `post_run` has no defined work; naming them with an invented body would be worse than the runbook reporting that nothing is connected. Added `select_topic`, the missing verb: a topic enters production only if at least one claim about it is SUPPORTED, because selecting one whose claims are all unverified only moves the refusal a stage later while implying the day had work. Quality control selects files by mime type rather than by asset label, after the renderer's `RENDERED_VIDEO` went unmeasured by a stage looking for `VIDEO_COMPOSED` — an unmeasured file is exactly what the publishing gate exists to stop. Verified by `scripts/demo_daily_run.py`, which runs two days in a throwaway studio with an Owner approval between them and produces a real MP4 that quality control measures and fails for the right reasons. Superseded in part 2026-09-18: the runbook no longer stops the day at the first FAILED stage — a failed stage blocks only the stages that take their input from it (`STAGE_PREREQUISITES`, see "A failed stage blocks only the stages that take their input from it").

## 2026-09-11 — The Owner authorises sites from the interface, and each one is tested

The allowlist for source retrieval lived in `.env` on the reasoning that an allowlist an agent could add to would not be an allowlist. That reasoning stands; the conclusion drawn from it — no endpoint, no form — did not. The Owner saw "Niciun site autorizat" in the preflight and could act on it only by editing a file and restarting the studio, and even then had no way to learn whether the studio could read the site at all: a bot wall or a script-only page is an authorised host that yields nothing, discovered one research stage later as a quiet empty result. Decision: hosts are added and removed through Owner-authenticated endpoints and stored in `research_allowed_host`, next to the `.env` list, under the same rule (bare lowercase public DNS name, never this machine or a private range); no agent has a tool that reaches these endpoints, which is what keeps the list the Owner's. Every host can be tested: the studio fetches its front page through the same DNS-pinned, size-bounded retriever it uses for real sources, stores nothing, and records PASSED or the exact reason it could not read the page. The preflight counts the tested ones, and the research modal shows origin and last test beside each host. Rejected: letting the retrieve request carry its host (still a request-controlled allowlist), and a test that only resolves DNS (it would pass for a site that then answers 403 to the studio's user agent).

Also decided today: a preflight that says "no verified provider" when the key is verified sends the Owner to the wrong place. `media_readiness()` distinguishes no selection, unverified, no default chosen, and no adapter, and the check reports which; the Owner's studio was in the third state for both voice and image. And a connection that makes two kinds of media keeps a default per kind (`image_model_id`), because Runway's account lists video and still models in one inventory and one default cannot name both.

## 2026-09-17 — A transient fault is not a P0, and the clock gets a second chance

The playbook always distinguished retryable from non-retryable (`../architecture/18_AUTOMATION_ORCHESTRATION.md`: network timeout, 429, transient 5xx on one side; invalid credential, policy violation, invalid configuration on the other; `../architecture/21_FAILURE_RECOVERY_PLAYBOOK.md`: a P2 is retried, a P0 stops autonomy), and the runbook had collapsed both into one FAILED that opened safe mode. Measured on a copy of the live database, that is what had stopped the studio for days: one "database is locked" at the wrong second, treated as a P0. **Decision: a stage's fault has a class, read from the exception's shape and its chain, never from a stage's optimism, and the default for anything unrecognised is HARD** — retrying an unknown fault is how a studio spends a night repeating a bug — with `TransientStageError` as the one door a runner may open when only it can tell. A TRANSIENT fault is retried in place (`stage_retry_attempts` counts retries after the first failure, four tries by default, because that is what the name says) and, still failing, fails the run and does not open safe mode: nothing about the studio is wrong. **What still opens SAFE_MODE is a HARD fault** — a run that ends FAILED with `fault_class` HARD enters safe mode and sets the autonomy stop exactly as before, and the Owner clears it with a note; a `MediaProviderNotConfigured` is HARD on purpose, because no key is a configuration fact and waiting will not produce one. Rejected: retrying every exception a bounded number of times, which would have spent generation credits on a bug three times before stopping. **Same-day re-attempts count runs, not intent**: a clock-fired run is refused only by a date that did work or by `daily_max_attempts` spent; a manual run counts toward the attempts, and a manual run that fails transiently is also re-attempted, because the Owner pressed the button to have a day, not to have one try. A waiting retry does not refuse the Owner's button — when its time comes it finds the day done and skips itself — and a retry left over from another day skips itself too. **The letter waits for the last attempt**, so a provider down at five does not write to the Owner three times before it is up at six. **The fixed local hour stores its timezone on the row.** The entry of 2026-09-11 rejected a fixed hour for the daily job only because it needed a column and said so; this is that column, and it turned out to be two, because the activation route calls `set_job_active(engine, job_id, active, command_id)` with no settings in hand, the tick has none either, and `../architecture/18_AUTOMATION_ORCHESTRATION.md` says a stored schedule stores its timezone. The hour is the one thing an existing seeded job follows from configuration on start-up — following the hour is not starting the clock, so `is_active` is never touched and the job stays dormant until the Owner's `workflow.job_activated`. Rejected: plumbing `settings.timezone` through `worker_pass` and the router, which would have left the row unable to explain its own next slot. **The Owner's stop between stages is neither failure nor refusal**: PARTIAL if the studio did some of the day, BLOCKED if none, the log closed only when work was done, and no letter — the Owner knows, he did it.

## 2026-09-17 — A retry is a question the studio may ask twice, not a purchase it may make twice

The architecture's retry table classifies by what the vendor answered; the adapters needed a second axis, because the same silence means two different things. A read timeout on `GET /v1/tasks/{id}` is a poll that can be repeated for free; the same timeout on `POST /v1/text-to-speech` is a narration the vendor may already have synthesised and billed, and the "one 503 per scene" problem must not be fixed by paying for two scenes. **Decision: every call declares whether it is `repeatable`.** A refusal (429, 5xx) and a request that never left this machine are always retried; a request that left and got no answer is retried only when repeatable. Reads and Google's resumable chunks (Content-Range keeps one copy) are repeatable; TTS, image generation, Runway task submission and LLM generations are not, and their silence is raised at once. To make this honest the HTTPS boundary had to say which phase failed, so `MediaProviderError` gained `unsent`, `unanswered` and `retry_after`, and `ConfiguredLLM` raises `ProviderHTTPError(ValueError)` and `ProviderUnreachable(OSError)` — subclasses of what callers already catch. Also decided: a Retry-After beyond `provider_retry_max_seconds` is a refusal for now and is raised immediately rather than slept through (the worker's lease is an hour; a ten-minute wait inside one scene would spend it), and it is honoured as given up to the cap, not clamped, because being refused after waiting less than asked is the same as not honouring it; the final error keeps its own class with the attempt count appended, because a wrapper exception would hide which vendor answered what from `explain_key_error` and the Owner; and Runway's estimated credits are recorded once, from the answer that succeeded, so a retried call is never billed twice locally. Rejected: retrying health checks less than real calls (a transient blip flipping a VERIFIED provider to FAILED is exactly what retries are for), and a retry loop in the runbook instead of the adapters (the runbook cannot know which request left the machine). Not attempted: reconciling a POST the vendor answered 5xx after doing the work — there is no task id to reconcile with, and the policy assumes, with `../architecture/18_AUTOMATION_ORCHESTRATION.md`, that a 5xx answer means the request was not served.

## 2026-09-17 — Repair is bounded, and a row nobody can answer for is the Owner's

The watchdog reuses the two reconciliation functions the publishing module already had rather than asking the platform its own way, and that choice fixed what it may do. **Attempts are bounded by the record, not a column.** A platform that cannot be reached is asked `reconcile_max_attempts` times, counted from the watchdog's own `publishing.watchdog_reconcile` events per publication; after that the row is moved to NEEDS_RECONCILIATION — the status the model already declared for the manual repair queue — with the count in the Owner's note, and is not asked again. A retry loop with no bound is how a studio spends its quota asking a dead endpoint the same question every ten minutes. Rejected: a schema change for a counter, because the events are already the audit of each attempt. **An unknown publication with no remote id is handed over at once.** YouTube's UNKNOWN result carries no video id (the stream was interrupted before the platform named it), and `reconcile_publication` can only ask about an id, so such a row would stay REMOTE_UNKNOWN for as long as the studio ran; naming it as a person's to look at is the honest state, and the watchdog does not write a second reconcile-by-key path to avoid it. Left for the publishing module: `execute_publication` could admit REMOTE_UNKNOWN-without-id to its existing reconcile-by-idempotency-key branch, which would let the watchdog resolve these rows itself. **Lapsed leases are reported, never reclaimed.** `claim_task` already re-claims an expired lease; a second mechanism doing the same would be two owners of one row. **A stuck render is failed the way the assembler fails one**, with the reason on the row and the same event, so the ledger does not learn a second vocabulary for the same fact. **The service is a Scheduled Task, not a Windows service.** A task runs under the Owner's own account with the user profile loaded, which the DPAPI-wrapped credential key requires, and needs no service wrapper or password stored; `-RunWhenLoggedOff` uses an S4U logon for the same reason, and whether that logon can open the key on this machine is the one thing the Owner must confirm once. The task starts the studio, not the day: the daily job stays dormant until the Owner's `workflow.job_activated`.

## 2026-09-12 — The Director approves the scripts she passes (recorded 2026-09-18)

Recorded late: commit `c8fb3f6` of 2026-09-12 moved script approval from the Owner's inbox to the Director without an entry here, and the module docstring of `backend/app/runbook/stages.py` and `_script_and_storyboard`'s still said the Owner approves until 2026-09-18. One watched cycle had made a new film and then stopped, because the approval sat in an inbox nobody was going to read that day. **Decision: a script the Director has read and passed is approved in the same breath (`_director_approves`), recorded with who decided and on what reading, and the factual gate is re-checked inside `approve_script_draft`, so her approval cannot carry a claim that stopped being supported while the script was written; a PASS the gate refuses is logged and the script is left, and the day goes on.** The Owner said so, and the Owner can still refuse what she allowed. The writer and the Director work the story for up to `MAX_SCRIPT_EXCHANGES` exchanges in the same run, because text is the cheapest thing the studio produces and the render is where the money is. Rejected: keeping VERIFIED_PASS as a waiting state for the Owner's button, which left a day's production one click behind the Owner's attention.

## 2026-09-17 — The close of the day is a stage, and a slot is an instant

From Phase A's adversarial verification (the whole suite run twice, 863 passed, 0 failed, 1 skipped), two defects with a red-then-green test each. **Closing the daily log goes through the same fault classification and retry as a stage, because a locked database at the close lost a whole day's log** — the day's work was done and its record was the one write not retried. **The next local occurrence of an hour is compared in UTC instants, because comparing aware datetimes across a DST change put a slot twice or never**: two aware datetimes sharing one tzinfo compare as wall-clock time, and on the day the clocks go back the wall clock reads the same hour twice, so a slot inside the repeated hour read as still ahead and fired on every tick.

## 2026-09-17 — A channel's visibility is the Owner's versioned command, not a column a form fills

`upload_privacy_default` already existed on the channel and could be set through `configure_channel` with a plain field; nothing read it, and had something read it, an unversioned field with no ledger event would have let a film go public on a write nobody could later attribute. **Decision: the publish policy is a second set of fields (`autonomous_privacy`, `public_publish_enabled`, `publish_delay_minutes`, `policy_version`, `policy_changed_event_id`, migration 0037) changed only by an Owner command shaped like the environment command** — write lock, `CommandRecord` idempotency, `expected_version`, NO_CHANGE without a trace, a `publishing.channel_policy_changed` event with old and new values and the environment the decision was taken in. Two refusals live in the command rather than the resolver: "public" needs `public_publish_enabled=true` in the same command, so a page cannot flip one switch and forget the other, and "public" is never set while the studio is in TEST, because the environment says what a film may cost and a public release is the one cost that cannot be refunded. The old field is left as it is and still unread rather than repurposed, because a field with two histories is worse than a dead one. Rejected: recording the policy change in agent memory as `change_environment` does, because the runbook hands visibility to the Publisher explicitly and a memory would be a second, unversioned copy of the decision. Refined 2026-09-18: the TEST refusal is judged on the state the command would leave, not on the field it names — see "The command is judged on the state it leaves, not the field it names".

## 2026-09-17 — A scheduled release is a private upload with a date, and the resolver says so

YouTube has no "public in forty-five minutes"; it has a private upload carrying `status.publishAt`, which the platform makes public at that time, and it refuses a publishAt on anything not private. **Decision: `resolve_publish_visibility` returns the pair the platform understands — `privacy_status="private"`, `publish_at`, `release_privacy="public"` — and every reader downstream (the gate, the adapter, the event payload) treats the pair as the public release it is.** The delay applies to public releases only: an unlisted film has no premiere to wait for. The adapter checks the timestamp's form and refuses a publishAt on a non-private upload before any request leaves, because a 400 from Google is a wrong request, not a wrong moment, and the retry policy would otherwise have nothing to classify. The publication keeps status PUBLISHED after a scheduled upload rather than the model's declared SCHEDULED, because the video exists on the channel from that moment and the watchdog, reconciliation and analytics all key on PUBLISHED; the schedule is on the row and in the event. Left for a later part: reading `publishAt` back at reconciliation to mark the moment it went public. Reversed in part 2026-09-18: the unlisted/TEST row of the resolver's truth table — an unlisted policy resolving unlisted while the studio is in TEST — is reversed by the entry "An unlisted release exists only in PRODUCTION"; unlisted now needs PRODUCTION like public.

## 2026-09-17 — The sixth gate asks two things: which policy, and whether it allowed this

A visible publication must carry the policy version that authorised it, so an audit can say which policy published what. A stamp alone would let a request name a policy that never allowed it: an unlisted intent on a channel whose policy says private, stamped with that policy's current version, would read as authorised by it. **Decision: `POLICY_AUTHORISATION_GATE` passes only when the stamp is the channel's current `policy_version` and the requested visibility (a scheduled release counted as public) is no more open than what `resolve_publish_visibility` yields for the studio's environment.** The five checks before it are untouched and a private upload still gets exactly five. The Owner's own intent endpoint stamps the policy in force and is held to the same rule, so visibility is decided in one place for hand-made and autonomous publications alike; the one-click `publish-asset` route stays private and needs no stamp. Rejected: a gate that checks the stamp only, and a gate that runs for private uploads — a private upload authorises nothing and would only make the five-check tests lie.

## 2026-09-17 — A film is routed by its storyboard, and an unbound slot is a refusal

`ready[0]` was the first bound slot whatever film it held. `Storyboard.channel_id` existed since 0021 and nothing in production set it; `series_key` was the only signal the serial pipeline could plausibly carry. **Decision: `select_channel_for` reads the storyboard — `channel_id` when set, else series key `office_serial` → OFFICE_SERIAL, else MAIN_FACTUAL — and returns SELECTED with the bound connection or SKIPPED with a Romanian reason; a binding whose connection is no longer CONNECTED is not a binding; there is no fallback to another slot, because the wrong channel is the one mistake no later check can undo.** A film with no storyboard behind it is SKIPPED with `channel_id=None` rather than sent to the main channel by default, for the same reason the factual gate refuses an unresolvable provenance chain: an unanswered question is not an answer. Rejected: routing by the film's script topic or by the connection's title, both guesses about an intent the storyboard states directly. Superseded in part 2026-09-18: the reading "`channel_id` when set, else series key" is replaced by the entry "A storyboard's pin must agree with its key" — a pinned `channel_id` whose channel type contradicts the series key is SKIPPED, not followed.

## 2026-09-17 — Analytics for a channel come from that channel's account, never from the environment

`YouTubeAnalyticsProvider.from_verified_settings` falls through to environment credentials when the bound connection is not exactly one CONNECTED row. On the Owner's machine those may name an account that is not this channel's, and the intake would attribute the serial's retention to the main channel with a straight face. **Decision: `analytics_provider_for_channel` builds the adapter from the slot's bound connection row and the vault only, refusing with the reason an unbound slot, a missing row and a revoked grant, and never calling the fallback; `measure_channel_publications` filters publications by `channel_id`, status PUBLISHED and a remote id.** Rejected at the time: editing the adapter's constructor from the publishing part, which another part owned; the closure of 2026-09-18 gave the adapter its `channel_id` parameter and the whole-or-nothing reading of explicit credentials (below).

## 2026-09-17 — Two heads on 0035: chained after the serial's migration rather than merged

While the publishing part was being written the serial part added `0036_serial_continuity.py` on the same parent. Two heads make `migrate()` fail for everyone with "Multiple head revisions", so leaving them for a merge revision would have blocked every test in the tree until the integrator acted. **Decision: the publishing migration is `0037_publish_policy` with `down_revision = "0036_serial_continuity"`, `main.py` pins 0037, and the serial's migration, written first, stays where it is; one linear chain, no merge revision.** The chain was verified in an isolated copy of the tree while the serial's migration still raised `ValueError: Constraint must have a name` (unnamed foreign keys inside `batch_alter_table` on `story_episode`), which its author fixed before the phase closed; the audio part verified against a scratch copy carrying names for those two constraints only, never by editing a sibling's file.

## 2026-09-17 — Loudness is normalised twice-measured, once applied

The joined narration is measured with `loudnorm` first and the encode applies one linear gain from that measurement (`linear=true`), falling back to the single-pass dynamic mode only when the measurement is unusable (a silent track reads −inf). **Reason: the one-pass filter normalises with a three-second window and audibly breathes on speech; a linear gain leaves the narrator's dynamics as recorded.** `LOUDNESS_RANGE_LU` is 11 rather than loudnorm's default 7 because the filter abandons linear mode whenever the input's range exceeds the target and narration measures 5–9 LU. The target stays −14 LUFS / −1 dBTP as specified; QC's band is −16..−12 LUFS because the film is measured after the AAC encode, which moves the reading a little. The output reading in the manifest is the encode's own loudnorm report, free from the same pass, with a second measurement of the finished film only when the log lost the report.

## 2026-09-17 — Captions are timed from the recorded narration, and never invented

`caption_cues` reads `audio_seconds`, written per scene by the assembler after synthesis, and clamps it to the scene's duration so words never spill into the next scene; a scene without words has no cue, which removes the old behaviour of captioning a visual prompt in brackets. Sentences split on terminal punctuation followed by a space so decimals and initials stay whole; a sentence too long for two lines becomes consecutive cues; lines are re-wrapped at the width that shares a sentence evenly across the lines it needs, so a two-line cue reads as two lines rather than a line and a crumb. **The SRT is written after the voice pass, not before it as it was.** The captions rule numbers (42 characters, 2 lines) are declared in `qc.py` again rather than imported from the assembler, so that reading a film never imports the machinery that makes one; the two test files hold both copies to the same values through the same cues. `format_srt_timestamp` rounds once to whole milliseconds, because the old fraction-then-round could carry 999.6 ms to a printed 1000.

## 2026-09-17 — The burnt caption sits above the bottom fifth

The task's phrasing put the safe area at the bottom 20 % of the frame; the platforms' own controls and auto-caption occupy that band. **Decision: the text's baseline is placed at the top of it (MarginV=58 in libass's 288-unit script resolution, measured at 387 px on a rendered 1920-high frame).** FontSize 7.5 (50 px) was chosen after a frame at bold 11 wrapped a 42-character line into two; at 7.5 regular a 31-character line takes about 680 px, so 42 fit inside the 1024 px between the side margins. The SRT is referenced by a name relative to the encode's working directory because the subtitles filter's option parser reads a colon as a separator and an absolute Windows path would need escaping twice.

## 2026-09-17 — Fallback is counted as asked-and-not-delivered, and a check that cannot be made fails

`fallback_scenes` counts scenes a model was asked for that produced no clip (refused, failed, or quoted past a ceiling); scenes no model was asked for — a test's scene limit, a spent budget, no model — are `skipped_scenes`, because those are policy, not a model refusing. **QC reads the environment through `studio_environment(engine)` before its own transaction opens — the studio's state, never a parameter — and fails only a PRODUCTION film; in TEST the same count is recorded as `motion_qc.warning`, because two motion scenes are policy there.** The default ceiling is half the scenes and `settings.max_fallback_scenes` overrides it. The audio and caption checks fail rather than pass when they cannot be made, matching the existing rule that a missing ffprobe fails technical QC: no encoder with loudnorm, no audio stream, an unmeasurable film, or a missing or unparsable SRT each add a failure reason; a film already missing or undecodable skips the measurement with an error field and no second reason, since technical QC has already named the cause.

## 2026-09-17 — The privacy check and the truth check are one check

The spec asks for a `NarrativeProjection` and for grounding, and they were built as one mechanism rather than two. **`write_episode` grounds beats against `narrative_projection_json` alone: an event that is in the day's operational record but not in its PUBLIC_SAFE projection is, to the showrunner, an event that did not happen, and citing it fails the whole episode the way an invented id does.** Rejected: a second pass that strips private citations from a stored episode — the prose around a private citation was written from private material. The projection is stored on the closed log at close time, derived from the same committed events, so the public face of a day is frozen with the day; a log closed before the column existed is filled once, from those same events, recorded as backfill of a derived column, not a change to the record (counts, roster and notable events never move). Classification is a table in code, private by default: an event type nobody classified cannot leak by being new. Redaction is regex and over-redacts on purpose (a year in a title, a four-digit count), because a lost word in a title is cheaper than a key on a channel.

## 2026-09-17 — The Owner's words are a fact, not content

**A letter to or from the Owner (`for_owner`, `owner_attention`, or "Owner" as a party) is projected as "X wrote to the Owner" and nothing else.** The subject and excerpt of any other letter pass through redaction like every description. An agent's own report (`agent.message_sent`) is projected as the task it reported on, never its text, because that text is the model's working output and quotes whatever it was given. `agent.model_assigned` and everything under `provider.`, `settings.`, `youtube.`, `economy.` and `research.` stay OWNER_PRIVATE by omission from the table.

## 2026-09-17 — Canon moves only on approval, and once per episode

**`continuity_state` is one versioned row and advances in `advance_continuity` only from an APPROVED episode — the Owner's `decide_episode` or the Director's PASS under policy — and is idempotent by episode id, so the two paths cannot count one episode twice.** A rejected draft and a draft awaiting the Owner leave no trace in canon; the next draft is still "episode n+1" until one is approved. Rejected: deriving the episode number from the count of episode rows, which would number rejected drafts. Threads are ids the showrunner is handed and must answer for (`threads_continued`, `threads_closed`), and the episode's own declaration is what advances them; nothing infers a thread's fate from prose.

## 2026-09-17 — The Director's approval of an episode is a channel policy, default off

**A Director PASS approves an episode only under `director_may_approve_episodes` on the OFFICE_SERIAL channel, read by `app.story.review.director_may_approve_episodes` and never written by the story module; default off keeps today's behaviour — the Owner decides — with the review already on the episode.** (Where the flag lives changed on 2026-09-18: a column of the publish policy, below.) The checks that need no model decide first and the Director is not asked about an episode they refuse; when they pass, her verdict is the verdict, as in `editorial_review`. One rewrite with her notes, then REJECTED: the second FAIL is the review working, and a third draft on the same day would be the same day told a third time. A log whose drafts were all rejected is finished with for the stage's purposes.

## 2026-09-17 — The factual claim gate does not apply to a dramatisation

An episode makes no claims about the world: it dramatises committed events of a closed log, and its truth is the grounding check. **So the `ScriptDraft` behind a serial storyboard has no claims (`claim_ids_json=[]`, `story_json.kind="office_serial_episode"`, `factual_gate: not applicable`), which the five-point publishing gate already reads as "the script references no factual claims; none to verify".** The `StoryReview` the media stage's `story_gate` requires is written PASS from the Director's episode review rather than from the factual story checks, because asking a comedy about its hook and its attributed claim is asking the wrong questions; the reading that actually happened is the one recorded. The storyboard is built in exactly `generate_storyboard_from_script`'s shape (tested field for field) so render, narration review, QC and publish run unchanged; the rows that shape forces — a `TopicIdea` of status SERIAL, which the factual selection never picks and never counts as in production — say what they are. Rejected: making `storyboard.script_draft_id` nullable, which would have broken `film_identity` and the publishing gate's provenance walk.

## 2026-09-17 — Voices come from the bibles, through the scene's character ids

**Each serial scene lists the bible ids of the characters in its beat, in the beat's order, and the existing production policy binds the first locked character's voice where a bible has a `voice_binding_json`; otherwise the narrator speaks.** No new voice plumbing: the assembler synthesises one voiceover per scene, so one voice per scene is the granularity available, and a beat with two speakers is voiced by the first. Multi-voice inside one scene is left open. The visual prompt quotes `face_hair_desc`, `outfit_desc` and `props_desc` verbatim, as the prompt agent does, so the look is the bible's.

## 2026-09-17 — Yesterday is closed on the preflight line, retried like a stage, and never ends the day

`close_previous_day` closes the previous business date with every event of that date; it runs after a non-blocked preflight and before any stage, with `_run_with_retries`; a fault after the retries is logged and recorded on the preflight stage as `previous_day_log.error` with its fault class, and the day goes on. **Reason: yesterday's record is not today's work — a run that stopped over a bookkeeping write about a finished day would cost a day's production for nothing, and the serial stage, finding no closed log, reports a quiet day rather than lying.** A date already closed is returned as it is: a closed log never changes. Known consequence, recorded as open: today's close at the end of the run is kept as instructed, so a date whose run completes is frozen at the run's hour and tomorrow's `close_previous_day` returns it as it is; a full-day log for every date needs that end-of-run close moved, which is the runbook's decision. A blocked preflight closes nothing, for the same reason it was never a day.

## 2026-09-17 — The serial queue runs before the media stage, and the day's log stays last

`STAGES` had `serial_queue` after `daily_log`, matching the runbook's §12 numbering, and the stage wrote text nobody filmed; the media stage of the next run would have picked the storyboard up a day later, and only if nothing factual was ahead of it. **Decision: `serial_queue` moves between `script_and_storyboard` and `media`, so the same run writes, films, measures and routes the episode.** This does not change what the stage does — it still prepares Channel B's production from the *previous* day's safe narrative events, whose log is closed at the start of the run — only when in the day it runs; `daily_log` remains the last stage, and `STAGES[:6]` is unchanged. Rejected: rendering the serial from inside the serial stage by calling `_media` a second time, which would have left quality control and publication a day behind and put two camera calls in one run under two different budget readings.

## 2026-09-17 — The budget is asked per film, and a refusal after the first film names the film

`_media` asked `may_spend` once for the day and rendered one storyboard. With two films in a run the second check would have been the first's stale reading: what the factual film spent is in the books by the time the serial is asked about. **Decision: `may_spend(engine, 0)` before each film; a refusal before anything was made keeps the old SKIPPED with the budget's reason, a refusal afterwards records the film in `skipped_for_budget` and the reason says "serialul" or "filmul factual".** Order factual first, serial second, because the factual channel is the studio's product and the serial is its diary. The serial is recognised by its storyboard's series key through the same mapping the publish routing uses, so the film the media stage calls the serial's is the film the publish stage sends to Channel B.

## 2026-09-17 — The render reads the Owner's switch between scenes, whoever asked for the render

**`stop_requested` is polled inside `assemble_video_job` itself — before every scene after the first, and before every motion shot — rather than through a callback the stage passes in.** Reason: the stop outranks everything, and `generate_storyboard_from_script` already refuses under it, so a manual render from the media route stopping between scenes with the same Romanian reason is the studio's existing stance, not a new one. The first scene is not preceded by a poll because the stage read the switch a moment before. The stop is a failed job with `STOP_REASON` in its log and a `media.render_failed` event, and `RenderStopped` is distinct from `RenderEngineUnavailable` so the stage can report it BLOCKED (the Owner's decision) instead of SKIPPED. Note 2026-09-18: with two films per stage the stage's read "a moment before" was true for the first film only; `_media` now reads the switch before each film — see "The media stage reads the stop before each film".

## 2026-09-17 — A publish stage with no bound slot is still SKIPPED before it looks for films

The per-film routing made the up-front binding check look redundant, and removing it turned "no slot bound, no film waiting" into COMPLETED "nothing waiting" — which `tests/test_pipeline_coverage.py` rightly refused: a stage that cannot publish anything has not completed. **Decision: the old refusal ("Niciun slot de canal nu este legat…") stays, before the queue is read; which slot a particular film needs is then decided per film, and a connected account no slot names is never guessed to be a channel's.** Aggregation rule when nothing went out: a content outcome (the Director's refusal, a HOLD, the gate's reasons) makes the stage COMPLETED with that outcome's artefacts, as before; only a stage that could not work at all (unbound slot, no model, no account) is SKIPPED. Also from the integration, mechanical: the fake `evaluate_media_qc` in `tests/test_cycle_fixes.py` gained `**kwargs` because the stage now passes `settings=`, and the loudness report's `output` in `assembler.py` is used only when it is a dict, else the film is measured.

## 2026-09-18 — The Director's brief has two readings, chosen by the film's own marks

`gather_facts` refused every serial film for having no claims and the one brief told the Director that a film about the studio is REJECTED. **Decision: the film's kind is read from the marks the serial storyboard already carries — `Storyboard.series_key == "office_serial"` (the same mapping the publish routing and the media stage use through `channel_type_for_storyboard`) or `ScriptDraft.story_json["kind"] == "office_serial_episode"` (what `storyboard_from_episode` writes); either is enough, so a storyboard that lost one mark is still judged as what it is.** The brief is one template with the judgement, the nature sentence and the story question swapped by kind (`instructions_for`), so the frames rule, the language rule and the JSON shape cannot drift apart between the two readings. Rejected: importing `is_serial_storyboard` from `app.runbook.stages` (stages imports editorial; a cycle), and a per-channel lookup of the storyboard's `channel_id` (a serial storyboard built before the channel was seeded has none). Consequence recorded: a serial script that somehow carries claims is not asked about their sources either — its truth is the grounding check of the episode review, not a source.

## 2026-09-18 — A factual film without claims stays rejected in the same words

The exception for the serial could have been written as "a script with no claims is a dramatisation". **It was not: a factual script that rests on nothing is the film the Owner asked about on 2026-09-16, and it is still refused before any model with "scenariul nu se sprijină pe nicio afirmație".** A test holds both the words and the fact that the factual brief still says a film about the studio itself is REJECTED, so the exception cannot widen by accident.

## 2026-09-18 — The Director's leave to approve episodes is a column of the publish policy, not a key in the series rules

`director_may_approve_episodes` was read from `series_rules_json`, whose validator (`_check_selection_shape`) allows only `{series_key: {purpose: selection}}`; the two commands that touch that JSON would have refused or silently dropped a boolean there. **Decision: a real column (migration 0038, default false), part of `policy_snapshot`, set only by `change_publish_policy` under the rules the other policy fields already obey — stale `expected_version` refused, idempotent by command id, NO_CHANGE without an event when nothing changes, a change bumping `policy_version` and recorded with old and new in `publishing.channel_policy_changed`.** Reason: whether the studio films an episode on its own is the Owner's decision of the same weight as whether a film can be seen, so it lives in the same versioned, recorded command and not in a production-technology setting. Rejected: exempting the key inside the production-policy validator (two commands writing one JSON with two shapes), and a studio-wide flag on `OwnerPolicy` (the serial is one channel's product; the flag is read on the OFFICE_SERIAL row only, and a grant on the factual channel changes nothing, tested). A grant on a channel bumps that channel's `policy_version`, so a publication stamped with the previous version is refused by the sixth gate until re-resolved — the same consequence any policy change has, kept on purpose. The pipeline tests set the column directly as a fixture, because they test the stage and the review, not the command; the command's versioning, idempotency, NO_CHANGE, revocation and per-channel reading have their own test in `tests/test_publish_policy.py`.

## 2026-09-18 — Explicit analytics credentials are one account's, whole or not at all

`YouTubeAnalyticsProvider.__init__` completed each None argument from `STUDIO_YOUTUBE_*`, which meant an adapter built from a channel's bound connection (client id, client secret, refresh token) still inherited `STUDIO_YOUTUBE_ACCESS_TOKEN` from the Owner's machine, and `_refresh_access_token` uses a present access token before it refreshes: the serial channel's retention would have been asked of whatever account that token named. **Decision: the constructor reads the environment only when no credential at all was given, and an explicit set is taken as it is, gaps included, so a connection missing its secret is honestly `is_configured() == False` rather than silently completed from another account.** The environment path is kept for a bare constructor because `from_verified_settings` still falls back to it, and that fallback is that method's decision, not the constructor's. `channel_id` became a constructor parameter so the per-channel builder no longer sets an attribute the class did not declare. Rejected: an `allow_environment` flag, because the presence of any explicit credential already says which path the caller is on.

## 2026-09-18 — The studio view sums the channels' switches rather than lying or disappearing

`PolicyView.public_publish_enabled: Literal[False]` was true when no route could publish publicly; after the Owner's per-channel publish policy it was a constant contradicting a channel's own view. **Decision, the smallest honest change: the field is a `bool` computed as "any channel row has `public_publish_enabled`" inside `policy_view(policy, session)`, with the session every caller already holds (`change_environment`, `change_stop`, `snapshot`), and a bare `policy_view(policy)` answers False, the safe reading.** The per-channel truth stays on `ChannelView`; the studio view only says whether a page should expect public releases anywhere. Rejected: dropping the field, which every consumer of the snapshot would have had to be checked for; and computing it in the router, which would have left the `PolicyResult` a command returns saying False after the very command that enabled it.

## 2026-09-18 — The Owner's render button hands the camera the same settings as the day

The daily run passed `settings=` to `assemble_video_job` and `evaluate_media_qc` (captions burn-in, the fallback ceiling) and the media route did not, so the same storyboard produced two different films depending on who pressed render, and the Owner's `max_fallback_scenes` was read by nobody on the manual path. **Decision: all three call sites pass `request.app.state.settings`, and the test asserts identity with the settings object the app was built from, faking the assembler and quality control at `app.media.router`'s import boundary so no encoder runs.** `continuity_state` goes into `HISTORY_TABLES` beside `story_episode`: its only foreign key is to `domain_event`, whose rows are deleted after the history tables, so its position among them is free, and the reset test now seeds a canon row and asserts it is counted and gone.

## 2026-09-18 — The runbook document states the execution order, and its hash is re-indexed

`../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` numbered the serial queue §12 after the daily log §11 while `STAGES` had run it before the media stage since 2026-09-17. **Decision, a deliberate specification change: the document is renumbered to the order the code runs — §7 the next-day serial queue, §8 media, §9 edit/QC, §10 publish, §11 post-run, §12 the daily studio log — with one sentence saying why the serial runs before media and that it still prepares Channel B from the previous day's closed log, its sections' content otherwise unchanged, and its `sha256` in `DOCUMENTATION_INDEX.json` updated explicitly (`cbad740d…` → `70dc698c…`).** `PIPELINE_COVERAGE.md`'s stage table follows the same numbering. Rejected: leaving the document at the old order with a footnote, which would have had the specification and the code disagree on the one thing the runbook exists to state.

## 2026-09-18 — An unlisted release exists only in PRODUCTION

`resolve_publish_visibility` honoured "unlisted" in TEST, and the publishing part's truth table (`tests/test_publish_policy.py`) said so. **Decision: unlisted is held to the environment like public — an unlisted film is a release anyone with the link can watch, and TEST means nothing leaves the studio visibly; the policy may still be set to unlisted in TEST and takes effect when the Owner moves the studio to PRODUCTION.** This reverses one row of the 2026-09-17 truth table, deliberately. Rejected: refusing the command itself in TEST, which would make the policy and the environment two switches for one thing.

## 2026-09-18 — The command is judged on the state it leaves, not the field it names

The 2026-09-17 rule read only `autonomous_privacy == "public"`, so with the privacy already public from a PRODUCTION day the flag alone re-armed a public policy in TEST — `public_publish_enabled=true` was COMMITTED. **Decision: `change_publish_policy` refuses any command whose resulting policy is public+enabled outside PRODUCTION when the previous one was not, in the same words as the refusal of the word "public"; a policy already public is left as it is, and its other fields remain settable.**

## 2026-09-18 — A storyboard's pin must agree with its key

The media stage and `is_serial_storyboard` know a film by its series key; the 2026-09-17 decision let the id win, so the same film could be filmed as the serial and sent to Channel A. **Decision: `select_channel_for` refuses a `channel_id` whose channel type differs from `channel_type_for_storyboard(board)`, with no fallback; a pin that agrees routes as before.** Supersedes the "`channel_id` when set, else series key" sentence of the 2026-09-17 entry "A film is routed by its storyboard, and an unbound slot is a refusal". Rejected: letting the key win silently (a pin nobody meant is still a contradiction worth a refusal).

## 2026-09-18 — Canon is checked for leaks like the beats

The Director's privacy check read the title, the scenes and the dialogue only, while `_previously` hands the episode's summary, opened threads and recurring elements to every later showrunner prompt; a key in the summary would have entered canon. **Decision: the Director's privacy check reads the episode's summary, opened threads and recurring elements with the same `leaks()` as the dialogue; a leak fails the episode before any model.** Over-redaction (a year in a summary) is the accepted cost the beats already pay.

## 2026-09-18 — The media stage reads the stop before each film

The assembler skips the poll before a film's first scene because "the stage just asked", which stopped being true when the stage started filming two: a stop set during the factual film started the serial's render. **Decision: `_media` polls `stop_requested` at the top of its film loop and reports BLOCKED with the Owner's reason and the film it did not start.** Consequence: a direct call of `_media` on a bootstrapped (stopped) studio is BLOCKED; three tests that did so now switch autonomy on first, as the runbook would have.

## 2026-09-18 — Three redaction shapes added, chosen by measurement

A currency-first price ("USD 12.50"), a scheme-less link ("studio.example.com/invoices") and an uppercase opaque key ("AKIAIOSFODNN7EXAMPLE") planted in a *safe* title reached the projection and the showrunner prompt: prices were matched amount-first, links by scheme, keys by prefix. **Decision: `_MONEY_FIRST`, `_DOMAIN` and `_OPAQUE_UPPER` join `_PATTERNS`; a phone-number pattern was rejected (not named by the rule; dates and counts would pay for it).** Probed unchanged: "Apa de pe GJ 486 b", "Ep. 3", "1080x1920", "AMN-AI HQ", "COVID19".

## 2026-09-18 — The suite proves the Owner's rule instead of promising it

A grep of the tests for provider hosts found them only inside fake transports and error strings, which says nothing about a fake wired one call short. **Decision: an autouse fixture in `tests/conftest.py` refuses non-loopback sockets for every test** — `socket.connect` and `connect_ex` to anything but 127.*, localhost, ::1 or a Unix-socket path are refused with a message naming the address and the rule; every adapter goes through urllib or http.client, which the guard covers. Rejected: a grep-only check (it found nothing, but a fake wired one call short is exactly what a grep cannot see). Known edges, recorded: an async client on Windows' proactor loop would connect through ConnectEx and bypass the guard, so one introduced later needs a second hook; `tests/test_ollama_adapter.py::test_real_ollama_health_and_generate` (opt-in via `STUDIO_OLLAMA_URL`) now passes only for a loopback Ollama, which is the rule and not a bug.


## 2026-09-18 — Repair shared garment material usage without rebuilding HQ

The runtime reported SkeletalMesh material fallback for four HQ garments. Repair
the shared parent's skeletal usage, retaining colours and geometry. Verify copied
assets in a separate UE project and independent reload before replacing only the
five affected packages with backup. Keep the existing procedural/GLB scene pipeline.
Use a native still for artistic diagnosis, but do not treat editor colour metrics
as game/player performance or as a percentage of reference fidelity. L2 is the
next bounded art pass; backend room identities remain authoritative.


## 2026-09-18 — A budget period begins when the studio's day begins, and the zone is the studio's own row

The DAILY window opened at UTC midnight while the studio's day is Europe/Bucharest, so a cost at 22:30 UTC on the 17th was counted against the 17th's budget while the daily log had already closed the 17th. **Decision: `studio_timezone(session)` reads `Studio.timezone` — which bootstrap writes from `STUDIO_TIMEZONE` — and `_period_start` opens the day and the month on that calendar, so the period the books count is the same business date `story.services.business_date` closes.** UTC is used only for a database with no studio row, which is not a studio. Rejected: threading `settings` through `may_spend` and `budget_status`, which would have changed the signature of every caller — the router, the stages and four test files — for a value the database already holds.

## 2026-09-18 — A reservation is a ledger row decided behind the write lock, and `may_spend` stays a reading

The race is read-then-decide: two films asked in the same second were both told the last ten dollars were free, because nothing between the reading and the spending said the money was promised. **Decision: `reserve_spend` takes `lock_for_write` before it reads the period and writes a RESERVED `spend_reservation` row that every budget counts as `reserved_usd_micros` until `settle_reservation` or `release_reservation`; `may_spend` keeps its old contract as a reading and is unchanged for its other callers.** A reservation of zero — an unpriced plan — is checked and holds nothing, because there is nothing to hold and an exceeded budget still refuses it. The Romanian refusal names what is held rather than pretending it was spent, and `spend_since` reports held and spent apart. Stale holds are released, never settled, by `release_stale_reservations`: a process that died under a hold made no film.

## 2026-09-18 — The day's remaining budget is read before the film's own hold, and other films' holds still count

`_budget_left_usd` feeds the per-film motion ceiling and now subtracts reservations. Measured after the hold, a PRODUCTION film that had just reserved its 12 USD would have been handed the ceiling of what was left after its own 12 were set aside — nothing — and would have rendered stills for a day with money in it. **Decision: the ceiling is read one line before `reserve_spend`, so a film never counts its own hold against itself while every other film's hold still counts against it.** This is the single place where a reservation changes what a render is allowed to buy, and the order is load-bearing.

## 2026-09-18 — Settle only after the cost rows are in; release on every other path out of a render

A settlement is a statement that the books now carry the truth. **Decision: `settle_reservation` follows `record_render_costs` and names the job (`render:{job_id}`); every other exit — the Owner's stop read between two scenes, an encoder that will not run, a vendor's refusal — releases the hold at once rather than leaving the day's money pledged until the watchdog's six hours are up.** Between the render and the settlement the film is counted twice rather than not at all, which is the error a budget may make. `_release` swallows its own failure and logs it: the watchdog is the backstop, and a second fault must not take the stage down on top of the first.

## 2026-09-18 — A price is a callable inside an adapter, not an engine

An adapter that costs its own call needs a price, and a price lives in the database. **Decision: `PriceLookup = Callable[[str, str], int | None]`, so `providers/elevenlabs.py`, `providers/ollama.py` and `integrations/llm.py` stay free of the database and a test can hand an adapter a dict; `price_lookup(engine, provider_kind)` does one short read per call, so a price the Owner types this afternoon costs this evening's runs without a restart.** Resource `"*"` prices every model of a kind that has no row of its own, and a model's own row outranks it.

## 2026-09-18 — Half a price is no price, and a cost row is never a float

**Decision: `llm_cost_vr` returns None unless both per-million prices exist and both token counts were reported, and `tts_cost_vr` prices the characters actually sent, rounding half up on the last micro.** A run priced on one side would be read by the budget as cheaper than it was, and a gap the Accountant reports as `unpriced_agent_runs` is honest where a half-cost is not. Zero tokens on one side is a zero, not an unknown. Money is integer micros end to end, because a cost row is money.

## 2026-09-18 — The only seeded price is ElevenLabs' public one, and it says it is not the Owner's plan

All nine live ElevenLabs models carried `pricing {}`, so narration was read as free, and the Owner's plan is not in the code. **Decision: `DOCUMENTED_PRICES` carries exactly one row — elevenlabs, `*`, per 1 000 characters, 0.22 USD (Creator plan, 22 USD for 100 000 credits, one credit a character; Flash and Turbo bill half, so the figure is the dearer one) — seeded by `seed_documented_prices` with provenance DOCUMENTED and a note saying it is the public list and not his invoice; it never overrides a row of any provenance and adds nothing on a second run, and the Owner's own price outranks it the moment he types it.** Rejected: seeding Ollama Cloud, whose price is the plan he bought — a guess in the books is worse than a gap the Accountant reports.

## 2026-09-18 — A failed render's cost is a row with a different reference, not a different table

The vendor charges for the shot it generated whether or not the film was finished, and a `MediaProviderError` recorded nothing. **Decision: `record_failed_render_cost` reuses `_priced_scene_costs` with the reference tag `failed:scene`, so a finished and a failed reading of the same job can never charge the same scene twice, a re-run charges nothing (the unique `(provider, external_reference)` refuses it), and the rows are ESTIMATED with `failed=True`, counted by the budgets like any estimate and labelled "ESTIMAT (randare eșuată)" in the books.** `failed=True` is refused for a BILLED row: a bill is what the vendor charged. Rejected: reconstructing the attempt from the plan inside the media stage — that would charge for shots the vendor may never have generated, and an invented entry is worse than the honest zero the stage records until `assembler._fail_job` writes the scenes it had already built.

## 2026-09-18 — One letter a day, decided behind the write lock

A budget refusal was a SKIPPED stage in a report nobody reads, and a stage refused twice in a minute would have written the Owner two letters. **Decision: `_letter_once_a_day` keys idempotency on the letter's `kind` and the business `date`, scanning that day's Owner-addressed messages, and takes the write lock, so `budget_refusal_letter` and `may_run_agent` each write to the Owner once a day whatever refused; the Accountant signs, the Director signs when the studio has no Accountant, and with neither the function reports `written=False` rather than inventing an author.**

## 2026-09-18 — The token ceiling is the Policy Kernel's first gate, and a refusal is a row, not an exception

391 agent runs went through the Director's loop and the mail rounds under no ceiling at all. **Decision: `may_run_agent` is asked before `run_agent_task` opens its write transaction — the Accountant's letter writes in a transaction of its own, and two writers on one SQLite connection are a lock, not a policy — and the verdict is raised inside the kernel's own `try` as `PolicyKernelError(..., "BLOCKED_BUDGET")`, so the existing handler writes the `AgentRun` exactly as it does for BLOCKED_POLICY and BLOCKED_PROVIDER.** Twenty call sites keep reading a status and none of them learns a new exception. It is the first of the six checks because it is the only one that costs money to learn the hard way. The ceiling counts every token of every run since local midnight whatever its outcome — an empty answer was billed like a good one — and `STUDIO_AGENT_DAILY_TOKEN_BUDGET` 0 means no ceiling, as the studio has run until now.

## 2026-09-18 — `run_agent_task` reads the settings the way the vendors' retry policy does

None of its twenty callers carries a settings object, and threading one through all of them to read a single integer would have been a larger change than the feature. **Decision: `_studio_settings()` is an `lru_cache`d `Settings()` that answers None when there is no usable `.env` — the shortcut `app.providers.retry` and `app.integrations.autoconfig` already take — and every ceiling is read through `getattr` with the code's own default, which for the token budget is 0.** A test overrides the function, not the environment.

## 2026-09-18 — The film's estimate is conservative on purpose

**Decision: `estimate_film_cost_micros` takes the motion at the ceiling that render will be given (`motion_budget_usd` in PRODUCTION, `test_max_cost_per_generation_usd` × `test_motion_scenes` in TEST) and the narration at the dearest active per-thousand price over the storyboard's own voiceover, and reports `narration_priced=False` when no voice price exists.** A film that costs less settles for less; a film let through on a hopeful estimate spends the week.

## 2026-09-18 — A discovered search address is a finding, the Owner's is a decision, and a finding never overrides a decision

Page discovery ran only through the OpenSearch address the Owner had typed per host, and only the two Wikipedias carried one. **Decision: every PASSED host test reads the front page through the same DNS-pinned retriever and looks for the site's own search address (`<link rel="search" type="application/opensearchdescription+xml">`, then `/opensearch.xml`), stores it in `discovered_search_template` (migration 0040) and never touches it from `set_search_template`; `effective_search_template` returns the Owner's address first and the discovered one only in its absence.** Discovery re-runs on every PASSED test and replaces what was stored, including with nothing: an address that vanished from the front page is not kept on faith, because a stale address that 404s is the failure this work removes. A retriever stand-in with no `describe_search` cannot look and says so (`discovery_ran=False`), so the caller keeps what it had rather than clearing it.

## 2026-09-18 — The OpenSearch description is read with the HTML parser, and a template that still needs a parameter is refused

The description is XML from a host the studio does not control. **Decision: `_OpenSearchUrls` extends the standard HTML parser — it takes the XML tags and unescapes attributes and has no entity expansion for a hostile document to exploit — and only the `application/x-suggestions+json` template is taken: `{searchTerms}` becomes `{query}`, optional parameters are dropped with their names, and a template that still needs a parameter the studio cannot fill, exceeds 500 characters, or is not HTTPS on the very host being tested is rejected.** The description's own address is validated under a one-host policy before it is fetched, so a front page naming another host's search cannot make the studio read that host.

## 2026-09-18 — A search engine may name addresses and nothing else, and the allowlist is applied by the studio, not by the engine

The Owner authorises hosts; an engine answers with whatever it indexes, and its answer carries cached copies, snippets and "answers" of its own. **Decision: `providers/search.py` returns addresses and titles only and knows nothing about the allowlist, and `find_pages` validates every result under the studio's own `RetrievalPolicy`, keeps the ones on authorised hosts, counts the rest as dropped (once per address, however many queries repeat it) and logs the count without the addresses; every kept page is then fetched by the studio's own DNS-pinned retriever.** Both halves are the decision. Reading an engine's copy, snippet or answer would be fetching through a third party exactly what the studio would not fetch itself, which is how an allowlist is widened without anyone deciding to widen it; and an adapter that knew the allowlist would be a second place where the list lives, which is a second place for it to be wrong. No agent, no request and no result can add a host: the list is the Owner's rows, and a name the engine returns is either already on it or dropped and counted. One documented HTTPS JSON contract (endpoint, key header, results path, field names) was chosen over a per-vendor adapter, so any engine that answers a GET with a key in a header and a list of `{url, title}` can be connected without new code; a bearer token is composed only for the `Authorization` header. `MAX_RESULTS` 50 and `MAX_URL_CHARS` 1000 bound what a hostile answer can make the caller iterate. Rejected: asking the engine first and the sites afterwards (a Wikipedia day would pay the vendor for nothing), and trusting the engine's own "site:" filter, which is the vendor's promise and not the studio's rule.

## 2026-09-18 — A search connection counts only when it is verified, and a verification does not look like a research query

**Decision: the catalog declares kind `search` with runtime `search` and group `social` — the bucket for accounts that are not language or media models, shared with e-mail — so the integrations check route sends it to `probe()`; the probe sends one neutral word (`PROBE_QUERY` "encyclopedia"), checks the shape of the answer and stores nothing, and `verified_search_provider` uses a connection only when its status is VERIFIED or ACCESS_VERIFIED, decrypting the key from the vault there and nowhere else.** SAVED is not enough, the same rule the media providers follow. The neutral word is deliberate: a verification should not appear in the vendor's logs as the studio's research.

## 2026-09-18 — When the studio found pages, a guessed address is set aside rather than fetched

Measured on the clean studio's first days: every address the Researcher guessed returned 404 and every page a site's own search returned existed, so a guess next to a real page is a page not read. **Decision: when discovery or the engine found pages, the Researcher's plan is a choice among them — a guessed address is not fetched, and its being set aside is recorded in the run's failed list as GUESS_SET_ASIDE in Romanian for the Director to read, not raised as an escalation; when nothing was found, his addresses are tried exactly as before and the escalation letter now also says that the site searches and the engine found nothing.** The pages found are read up to the day's limit whether or not the Researcher chose them.

## 2026-09-18 — The day's reading is four candidates of four pages, and the ceiling is the code's

Two topics of three pages left the studio with 0 pages on a day when both guessed plans failed. **Decision: `DEFAULT_CANDIDATES_PER_DAY` and `DEFAULT_PAGES_PER_TOPIC` are 4 and 4; `research_budget(settings)` reads `research_candidates_per_day` and `research_pages_per_topic` when the settings object carries them and clamps both to 1..12, and `MAX_URLS` in the Researcher's plan rises from 4 to 8 and becomes the ceiling under the Owner's setting rather than the setting itself.** A typo in the environment cannot turn a research pass into a crawl.

## 2026-09-18 — A script-only shell is a host failure with a name, and the heuristic is measured on fixtures

14 of the 36 authorised hosts failed retrieval, and the reason was a sentence nobody could act on. **Decision: `last_test_reason` is a closed vocabulary — HTTP_403, HTTP_ERROR, RATE_LIMITED, SCRIPT_ONLY, NETWORK, OTHER — and the retriever keeps `<noscript>` text apart from the page text and marks `scripts_required` when the visible text is under 500 characters and mentions JavaScript; a shell with under 10 characters of text raises a `RetrievalError` naming JavaScript, and a shell with a little text is PASSED by the retriever and FAILED by the host test on the flag.** The 500-character threshold was measured on the shells of the hosts that failed — a title, an empty root element and a one-line notice, never a paragraph — and is proven on fixture HTML modelled on them, not on live pages, because no test may open a socket. Recorded as such: the first weekly retest on the live database is the measurement.

## 2026-09-18 — The health report is computed from the record and probes nothing

A preflight that asked whether a row existed passed on 36 authorised hosts of which 14 were unreadable and none had a search address, and the day then fetched nothing. **Decision: `research_health(engine, settings)` answers "can the studio find pages" from the record alone — hosts authorised, tested, with a search address, failing and why, whether an engine is VERIFIED, how many SUPPORTED claims are in hand — and is DEGRADED with named Romanian reasons when no host passed, when there is no way to find pages at all, or when fewer than `MIN_CLAIMS_AVAILABLE` (10) verified claims remain; it opens no connection, so the preflight may call it on every run.** Ten is a day's margin: a thirty-second short spends three to five claims and a day's verification lands a handful. A DEGRADED report stops nothing by itself — a day that finds nothing completes honestly with nothing — and the counts are in the check's `detail` as well as its message, because the run the Owner needs them for is the one where the check failed.

## 2026-09-18 — The weekly host retest lives inside the research stage, not in a scheduled job of its own

A site readable a week ago may have grown a bot wall since, and one that failed may have dropped it. **Decision: `retest_stale_hosts` touches only hosts whose last test is missing or older than `RETEST_AFTER_DAYS` (7) and runs inside the research stage, wrapped in a broad `except` and logged — on the other six days it fetches nothing and costs the sites nothing.** Rejected: a scheduled job of its own, which would have added a row to the scheduler, a handler to the worker and a second thing behind the autonomy stop to reason about, for a pass that already decides for itself when to do nothing. A site that cannot be reached is a fact about the site: under Phase A's rule such a failure costs the stage, never the studio — here, not even the stage. Corrected 2026-09-18: under Phase A's rule a failed stage blocked every stage after it, so "costs the stage" meant the rest of the day, and a hard fault in any stage opened safe mode; since 2026-09-18 a failed stage costs only its dependants. A host authorised by the `.env` file has no row of its own, so its result and discovered address are stored on a row marked `added_by="env"`, which never re-authorises the host once the file drops it.

## 2026-09-18 — The end-to-end test fakes the vendors and nothing else

The project had every stage tested and no test of a day. **Decision: `tests/test_autonomous_day_end_to_end.py` fires the scheduled job, lets the worker execute the real runbook with the real stage runners against a temporary database, and asserts the whole day — twelve stages under a `scheduled:` idempotency key, a claim extracted and verified by a second employee, a script the Director passed, two films encoded by FFmpeg and measured by quality control, both published private through the five gates to their own channels, the serial episode grounded in yesterday's events — then a second tick that starts nothing; only the vendors are faked, and the docstring says so.** The picture is a small PNG of noise rather than a flat card, because quality control refuses a still that survives being flattened along either axis, and a fixture that could only pass by disabling that check would prove the wrong thing. The film is asserted PUBLISHED_SIMULATED and not PUBLISHED: a studio that wrote "published" for a film no platform received would be lying in its own books. The model stand-in fills each schema from what the prompt itself carries — the claim ids the writer was given, the day's event ids, the cast read from the cast section alone — so the studio's own checks are what make its answers usable, exactly as with a real model. The test skips where FFmpeg is absent, by the convention `tests/test_phase5_media.py` already uses.

## 2026-09-18 — Migration numbering: economy 0039, research 0040

Two implementers needed a schema change in the same tree. **Decision: `0039_pricing_truth_and_reservations` (economy) first, `0040_research_sources` (research) chained after it with `down_revision = "0039_pricing_truth_and_reservations"`, and `main.py` pins `0040_research_sources` as the head.** Both are additive — two tables and a column for the economy, three nullable columns for research, plain `ADD COLUMN` as 0030 did — and every existing row keeps its meaning. `scripts/bootstrap.py` must run against the live database before the server starts on this version, and no test touches it.

## 2026-09-18 — A price table is passed at construction, never fetched at the call site

The three adapters already took `price_lookup: PriceLookup | None = None` and no construction site
passed one, so every `agent_run.cost_vr` was NULL and every narration unpriced whatever the Owner
had typed. **Decision: the four places that build an adapter hand it `price_lookup(engine, kind)`
— the seeded Ollama endpoint (`main.register_seeded_ollama`), the language connections loaded at
start-up (`integrations.services.load_registry`), the one re-registered when the Owner saves a
connection while the studio runs (`integrations/router.py`), and both doors into a voice
(`media.factory.tts_provider` and `tts_provider_for`) — rather than handing each adapter an
`Engine` and letting it read the table itself.** The alternative would have put the database inside
`elevenlabs.py`, `ollama.py` and `integrations/llm.py`, which is exactly what the callable was
designed to avoid. The consequence is that the engine must be in hand where the adapter is built,
and it is at all four: two take one as a parameter, the settings router reads
`request.app.state.engine`, and both voice doors already take `engine` as their first argument. No
signature changed. One short read per call, so a price typed this afternoon costs this evening's
runs without a restart; a model with no row still reports None, never zero.

## 2026-09-18 — The connection re-registered by the router carries the same table as the one start-up registered

`PUT /settings/integrations/{id}` replaces the adapter in the live registry for any connection
whose runtime is `llm`. **Decision: wire the router's re-registration as well as `load_registry`,
and prove each by its own test.** Wiring only start-up would have meant that a connection the Owner
edited at noon ran the rest of the day reporting `cost_vr` NULL while an untouched one was priced —
the kind of asymmetry that is discovered months later in the books rather than in a test.

## 2026-09-18 — `credits.py` and `discovery.py` build an ElevenLabs adapter and are deliberately left unpriced

Those two construct one to read the subscription balance and to list the models and voices a
connection offers. **Decision: neither is given a price table, because neither call generates
audio, so neither has characters to price and `tts_cost_vr` would answer None for them anyway; and
rather than leave that as a silent omission, the list of priced construction sites is written down
in `tests/test_pricing_truth.py::PRICED_CONSTRUCTION_SITES` with the reason beside it.** The scan
that walks the list fails on a fifth site added later without a table, and also fails if a listed
module stops building an adapter at all, so it can never pass by finding nothing to look at.

## 2026-09-18 — The documented seed goes in bootstrap alone, because there are no start-up seeds

The economy implementer offered `scripts/bootstrap.py` "or the start-up seeds in `main.py`".
**Decision: `seed_documented_prices(engine)` is called from bootstrap, beside
`seed_chart_of_accounts`, and from nowhere else.** `main.py` has no seeds — its lifespan migrates
nothing and seeds nothing, it loads the registry and registers the seeded endpoint — and a seed
that wrote a price row on every server start would be a write the Owner did not ask for at a moment
he is not watching. The test therefore *reads* `scripts/bootstrap.py` rather than running it:
bootstrap writes `.env` and migrates the database named in it, which is the Owner's own, and no
test may open that.

## 2026-09-18 — The failed-render test plans three scenes and stops at the third, so the plan and the attempt cannot be confused

The existing adversary test refuses the second of two, which a job writing the *plan* minus its last
scene would also pass. **Decision: the new test plans three scenes and has the vendor refuse the
third, and asserts the exact scene list `[1, 2]` and exactly two ESTIMATED cost rows named by their
references, rather than a count a third row would still satisfy.** With three planned and two made,
a `production_json` carrying the plan would charge the day for a shot the vendor was never asked
for — the opposite error to the one this work fixed, and just as wrong in the books. The fix itself
was already in the committed tree (the assembler wraps its scene loop and `_fail_job` writes the
production it had built); what was missing was the proof that it writes the attempt and not the
plan, and a second reading charges nothing.

## 2026-09-18 — The research health report and the forced retest are the Owner's, on the factual router

The research half computed a health report and a forced retest that nothing called. **Decision:
both get a route on the factual router — `GET /api/v1/factual/research/health` and
`POST /api/v1/factual/research/allowed-hosts/retest` — rather than a research router of their own,
because that is where `/sources/allowed-hosts` already lives and the router's
`dependencies=[Depends(require_owner)]` is what makes them his.** The retest fetches front pages
and the report names every failing site and every site the studio can read, which is a map of the
studio's reach that an unauthenticated caller has no business reading. A test pins the 401 on both,
from the other side of the door. The health route probes nothing, so the screen may ask for it on
every refresh.

## 2026-09-18 — The retest route takes no body and forces the pass with `max_age_days=0`

**Decision: the route accepts no parameters; `max_age_days=0` is hard-coded, which is what makes it
"now", and the retriever is taken from `app.state.source_retriever` the way the existing per-host
test route takes it.** A parameter would have been a way for a caller to widen what the button
does, and the weekly age is the runbook's decision, not the interface's: the route is the Owner's
"now" after he has fixed something, and nothing else. The retriever hand-off is what lets a test
drive it with a stub — `tests/conftest.py` refuses every non-loopback socket, so without it the
route could not be tested at all without spending someone's bandwidth.

## 2026-09-18 — The discovered search address is shown even where the Owner has typed his own

**Decision: *Cercetare → Surse* prints, for every authorised site, whose address is in force
(marking the discovered one «not used, yours wins» where the Owner typed his), the address the
studio found on the site itself and when it found it, and «Try it» resolves whichever address is in
force, because `search_pages` resolves it the same way.** Hiding the discovered address where the
Owner has his own would have been tidier and wrong: his address is a decision and the discovered one
a finding, and he can only judge whether his decision is still the better one if he can see what the
site now offers. For the same reason the badge names whose address is in force rather than merely
saying «search», and «Try it» is offered wherever any address exists, including on a site that came
from `.env` and has no row of his to edit.

## 2026-09-18 — A failure reason is printed as a label from a closed list, with the site's own words after it

**Decision: the screen prints `last_test_reason` through a fixed label map and the site's own detail
after it, and an unknown code falls through to itself rather than to a friendly guess.** The code is
the same word on every host and can be compared down a column; the detail is what actually came back
and cannot be. A bot wall and a script-only shell are two different jobs for the Owner rather than
one paragraph of Romanian. A reason the backend adds later shows as the backend's own word instead
of silently reading as something else.

## 2026-09-18 — The budget card prints what is held apart from what was spent, and names the unpriced runs

**Decision: a budget card prints the held sum only when there is one, as «held for films in
production» rather than folded into what was spent; and the day prints what is held, what was paid
for renders that failed midway, and how many runs have no recorded price, named.** The percentage on
that card is already of spent plus held — that is how the backend computes it — so a card printing
only what was paid would leave the Owner reading a ratio he could not reconstruct and believing the
day has room it does not have. The unpriced-run line says in words that the total is lower than the
real spend, because a zero that means "not known" is the one number this studio must never present
as a fact. A run blocked by the day's token ceiling reads as a sentence instead of the raw word
BLOCKED_BUDGET.

## 2026-09-18 — The two changed screens are pinned at the API that feeds them, not by a DOM harness invented for them

`frontend/package.json` runs `node --test` over `frontend/tests`, and `main.js` touches the document
at import, so it cannot be imported there. **Decision: no DOM harness was invented for one screen;
what the screens render is pinned instead at the API — a Python test asserts that a failing host
comes back with `last_test_reason` SCRIPT_ONLY and a Romanian detail, and that the Owner's address
wins `search_template_origin` — and the file itself is kept honest by `tsc`, which type-checks
`src/*.js` with `checkJs`.** The honest next step, if the screens themselves are to be tested, is to
lift `renderAllowedHosts`, `budgetCard` and the run-status map into a module that takes data and
returns HTML; that is a refactor of `main.js` and not a test, and it was not this part's work.

## 2026-09-18 — The daily runbook is edited and its index hash re-recorded

The runbook still described the budget check, the research stage and the preflight as they were
before Phases E and F, and an architecture document that contradicts the code is worse than one that
is silent. **Decision: this is a deliberate specification change under ADR-FOUNDATION-003 — §1 now
states that the research check answers whether the studio can find pages at all; §4 states the order
in which pages are found (the Owner's search address, then the one the studio discovered on the
site, then a verified search engine filtered to the allowlist, every page read by the studio's own
DNS-pinned retriever and never the engine's copy) and that the weekly retest of authorised hosts
lives inside the research stage rather than in a scheduled job; §8 states the money path (the film
priced and the sum held before a frame is made, settled after the real cost rows are written,
released on every path where the film was not made, and a hold left by a dead process released by
the watchdog after six hours) — and the document's `sha256` in `DOCUMENTATION_INDEX.json` is updated
in the same change (`70dc698c…` → `1de4ef7a…`), with this entry as the recorded
reason.** Nothing was removed: every line the runbook already carried is still there, and each addition is dated in place so a reader can see what
the stage was before. No other architecture document was touched, and the check was not bypassed.

## 2026-09-18 — PIPELINE_COVERAGE's research and media rows follow the code, and its analytics line is corrected in place

**Decision: the stage table's rows 4 and 8 now say what those stages do and refuse today — the
retest and the three-tier page search, every engine result dropped and counted before anything
downstream sees it; the plan estimated and reserved behind the write lock before a frame is made —
and the stale limitation "Analytics measures through the first bound slot; per-channel measurement
needs one call per binding" is struck through with a dated correction rather than deleted.**
`measure_channel_publications` has measured per channel since Phase B/C, so the line was untrue; the
document already corrects in place with a dated marker, and striking it through keeps what the
document once claimed visible beside what is true now, which is the property that makes a coverage
audit readable a year later. What survives the correction is narrower and stated: a channel whose
slot is unbound is still not measured at all.

## 2026-09-18 — The economy's own documents name `provider_price`, `spend_reservation` and the hold inside `spend_since`

`PHASE11_ECONOMY.md` and `ACCOUNTING_AND_HISTORY.md` described a ledger that recorded what a vendor
had charged and a budget measured only from what was already recorded; neither mentioned the two
tables migration 0039 added. **Decision: both gain a dated section in their own voice — what a
RESERVED row is, that it is settled only when the real cost rows replace it and released on every
path where the film was not made or by the watchdog after six hours, that `spend_since` reports the
held sum apart from the spent one and every budget counts spent plus held, and that a price is the
Owner's with its provenance recorded (OWNER, DOCUMENTED, QUOTED, BILLED) and never a figure the
studio discovered for itself.** Both are project documents and neither is hashed, so no index entry
changed. The two documents' stale limitations are corrected in place, dated, rather than deleted: a
run and a narration are priced now, image and video generation still are not, and a model the Owner
has not priced is still reported as unpriced usage instead of as free.

## 2026-09-18 — The shots bought before the Owner pressed STOP are charged to the day

The verification of the Phase E/F closure left one open question from the previous pass: the media
stage's `except RenderStopped` branch released the film's hold and recorded no cost, although the
assembler now writes `production_json` for the Owner's stop exactly as for a vendor's refusal. A
test written against that branch found a stopped film whose FAILED job carried scene 1, whose hold
was RELEASED, and whose day was charged nothing. **Decision: the stop branch calls
`_record_failed_attempt` before `_release`, in the order the refusal branch already uses — the
estimate stops counting exactly when the real cost of the attempt starts.** The Owner's switch is a
decision about whether the studio keeps working; it is not a decision about whether a vendor has
already been paid. A shot generated in the minute before STOP was bought exactly as one the vendor
then refused, and a film the Owner stopped after one scene read in the books as a film that cost
nothing. Nothing is reconstructed from the plan: the attempt is read from the job's own record, so a
render that stopped before it made anything still charges nothing, and `record_failed_render_cost`
remains idempotent per job and scene, so a re-read charges nothing twice. `_record_failed_attempt`'s
docstring, which still said the assembler kept `production_json` for a finished render only, was
corrected to what the code does.

## 2026-09-18 — Every construction of a priced adapter is scanned, not four named files

The closure proved its price wiring with a scan of the four files it had changed. **Decision: the
verification replaces that list with a walk of all 183 application modules
(`tests/test_phase_ef_closure_adversary.py`), matching attribute calls as well as bare names, and
requires every site it finds to be either a priced one or a documented exception.** A whitelist
passes for whatever is on it, and the invariant is about the studio and not about four modules: a
fifth construction site would most likely arrive in a module nobody thought to list. The two
exceptions are named with their reason — `economy/credits.py` reads a subscription balance and
`integrations/discovery.py` lists models and voices, and neither generates anything to price. The
scan was run against a deliberately incomplete list first and named `economy/credits.py`, which is
how it is known to bite.

## 2026-09-18 — The roadmap and PROJECT_STATE are ticked against the closure

`13_ROADMAP_TODO.md` still carried open boxes for the price lookups, the documented seed's caller,
the failed-render record and the routes and screens, and `PROJECT_STATE.json` carried the matching
`known_blockers` and a `next_task` describing work already done. **Decision: the five closed boxes
are ticked with the date and the evidence, and the blockers are replaced by what is actually open —
the Owner's own prices, a bundle that is not rebuilt, and the reconciliation of ESTIMATED rows
against a vendor's invoice, which still has a vocabulary and no function.** A tracking document that
keeps listing closed work teaches the next reader to stop reading it, and the cost of leaving it is
that the work is done twice.

## 2026-09-18 — A picture the model refuses fails the film in both environments

The picture gate was asked to follow the fallback-scene gate, which is conditional on PRODUCTION.
**Decision: it follows `content_integrity_qc` and `content_source_qc` instead, and fails
unconditionally.** The existing gates do not all work one way, and the difference has a reason:
`motion_qc` is conditional because in TEST two motion scenes are the studio's own policy and the
rest push by design, so the count it measures is expected there. Nothing in TEST policy
deliberately produces a blank scene or a stranger in a character's clothes. The degenerate-still
check already fails unconditionally for exactly this defect measured on the still instead of on the
film, and the placeholder-footage check blocks unconditionally; the picture check belongs beside
those two.

## 2026-09-18 — One vision call for the whole film, carrying both questions

The pictures and the characters could have been two calls with two schemas, which would keep a
NOT_APPLICABLE character check from sharing a run with a measured picture check. **Decision: one
call — a `scenes` array and a `characters` array in one object, the scene frames followed by at most
four reference portraits, the prompt saying which are which and in what order — because the frames
are the expensive part of the payload and sending them twice doubles the image tokens for an answer
about the same images.** The record still separates the two verdicts: `picture_qc` and
`character_drift_qc` carry their own status, their own `passed` and their own run id, so a character
check that could not run never drags the picture check down with it. A film costs one call, two when
the model must be asked again with its own thinking on, and none when the check stands down.

## 2026-09-18 — Nothing in the vision answer has a default that reads as a pass

**Decision: `is_a_picture`, `shows_the_scene` and `matches` are required fields of the parsed
object, so a model that omits them fails validation and the whole check stands down rather than
passing a scene by silence.** A scene the model simply leaves out of its array is recorded
NOT_APPLICABLE with `no verdict was returned for this scene` and does not count towards the pass.
The same rule covers the frame cap: the Director's `frames_for` cuts at most eight frames, so a
ninth scene is recorded `no frame was cut for this scene`, never as looked at and approved. A gate
that certifies what it did not measure is worse than no gate, because the report then carries the
studio's signature on it.

## 2026-09-18 — The looking happens before quality control opens its write transaction

**Decision: `evaluate_pictures` is called next to where `studio_environment` is already read, before
the report's transaction, and it reads the storyboard out into plain values and closes its own
session before the call.** A vision call is an agent run; `run_agent_task` reads the day's token
ceiling outside a transaction by design and writes its own rows, so doing it inside the report's
transaction would put two writers on one SQLite connection. For the same reason no detached ORM row
and no held connection survives into the wait.

## 2026-09-18 — The employee who looks is found by department, and only the primary model counts

**Decision: `app.agents.vision.vision_agent` asks in the order Video Editor, Director, Quality
Assurance, and reads only the primary model slot.** The department that made the pictures answers
for them, and the Director's own model (glm-5.3) declares completion, thinking and tools and no
vision at all — a gate that asked her first would never run. A second or third model slot is the
Owner's configuration for other work and a run here would not use it, so counting it would let the
gate claim a capability the run cannot reach. `model_can_see` and `frames_for` were not moved: they
are the Director's, and `vision.py` imports them so callers have one door.

## 2026-09-18 — A Character Bible slot holds a stored asset id or nothing

**Decision: the slots are read exactly as the model documents them — a value that is not a string is
ignored, a portrait whose row or file is missing is simply not attached, and a description is never
accepted as standing in for an image.** A character with a description is compared against the
description; one with a portrait and no description against the portrait; one with neither is
recorded NOT_APPLICABLE for that scene with the reason and is never sent to the model, because there
is nothing to compare the frame with. The writing half follows the same rule:
`generate_character_reference_set` writes a `MediaAsset` per produced slot — bytes on disk, size and
dimensions measured from what the adapter returned, SHA-256 provenance, `license_status =
ORIGINAL_AI_GENERATED`, `provider_name` from the adapter — and only then writes that asset id into
`reference_assets_json`. A slot whose generation failed keeps its previous value and appears in
`failed` with the reason.

## 2026-09-18 — Producing a reference set is an Owner command, not a stage of the day

**Decision: it lives behind `POST /media/characters/{id}/reference-set` on the Owner-only media
router, reads STOP AUTONOMY before the first request (`AUTONOMY_STOPPED`, HTTP 409), and
`tests/test_character_references.py::test_the_days_run_never_produces_a_reference_set` asserts that
`runbook/stages.py`, `runbook/services.py` and `workflows/services.py` do not name the function.** It
costs one image credit per slot, and a studio that regenerated references on its own would spend a
budget on pictures nobody asked for. The route also refuses when no verified image provider is
selected, rather than drawing five placeholder cards and calling them references.

## 2026-09-18 — The money for a reference set is asked for once, before the first slot

**Decision: `reserve_spend` holds the estimate for the whole set behind the studio's write lock,
exactly as the media stage holds a film's cost; the hold is settled when at least one picture was
produced and released when none was.** The estimate is `estimate_cost_usd(..., images=1)` times the
number of slots; a model with no recorded price estimates to None, the hold is of nothing, and the
answer reports `cost.usd = None` and `priced = False`. An exceeded budget still refuses a request it
cannot value — that is the existing `reserve_spend` behaviour, and the reason the refusal is asked
for rather than computed at the route.

## 2026-09-18 — A locked look with no readable reference is a refusal, not a warning

**Decision: `image_reference_for_scene` returns None for a character with no lock and no reference —
the scene is drawn from its prompt as it always was — but raises `ReferenceRequired` when a character
whose `identity_locks_json['visual']` is set has no reference asset, or one whose file cannot be
read.** Drawing that scene anyway would invent a face for a character whose face is fixed, which is
the thing the lock exists to prevent. The first character the writer named decides the reference, so
a still is never drawn from two faces at once.

## 2026-09-18 — The studio asks an adapter whether it can take a reference

**Decision: `factory.accepts_reference_image` reads a class attribute and treats silence as no;
`still_from_chain` drops `extra['reference_image']` for an adapter that cannot take it and records
`reference_image: False` on that attempt.** A render must never report a continuity it did not have.
The OpenAI adapter implements the documented multipart `/v1/images/edits` path and sets
`ACCEPTS_REFERENCE_IMAGE = True`, which is a statement about the code; `REFERENCE_IMAGE_VERIFIED =
False` is the statement about the account and stays False until an Owner-approved run has actually
drawn a scene that way, because no test may buy one. A reference given as a path, an id or a
description is refused before the vendor is called rather than posted as a form field.

## 2026-09-18 — A second vendor is the Owner's, never the studio's

**Decision: `approved_alternatives` reads the `approved_fallbacks` list a level of the hierarchy
holds for a purpose — a new `SELECTION_KEYS` entry validated as a list of `{integration_id,
model_id}` objects, and also a `TECHNOLOGY_KEYS` entry so a consistency-locked channel does not let
an episode swap it in — and where a scene has a visually locked character the chain is narrowed to
entries in that character's `approved_fallbacks_json`, the list an APPROVED `CharacterIdentityChange`
writes.** Approval is the evidence that the technology keeps the character recognisable, and the
studio cannot produce that evidence about itself. Every alternative goes through the same `_validate`
as the first vendor, so an approval naming an unverified connection is dropped with a note rather
than tried.

## 2026-09-18 — The fallback chain is one alternative long

**Decision: `MAX_FALLBACKS_PER_PURPOSE = 1`, and when every approved vendor refuses,
`still_from_chain` re-raises the last `MediaProviderError` with the attempts attached as
`exc.attempts`.** A render that kept trying vendors would spend a film's budget on one shot, and the
second refusal is usually the same refusal — a prompt both vendors decline, not an account that is
down. Re-raising means the caller does exactly what it did before a chain existed, and a failed
render can still be priced for what was tried.

## 2026-09-18 — In TEST the chain is ordered cheapest-first; in PRODUCTION the Owner's order stands

**Decision: in TEST the alternatives are ordered by the price the studio has recorded, cheapest
first, with unpriced models keeping their place behind the priced ones; in PRODUCTION the resolved
vendor comes first and the alternative after.** The Owner's rule is that a test takes the cheapest
model that can do the job, and an approved alternative does not create an exception to it. A model
nobody priced can never be proven cheapest, so it is never promoted ahead of one that can.

## 2026-09-18 — The autonomy mode is recorded as AUTONOMOUS_CEO, because that is what the code does

**Decision: migration `0043_autonomy_mode` writes AUTONOMOUS_CEO on existing and new rows, and says
in its docstring that it records the mode rather than granting it.** The code is unambiguous:
`runbook/services.py` walks twelve stages in one call with no Owner approval between them,
`stages.py::_director_approves` approves a script in the same breath the Director reads it, the media
stage reserves budget and pays a vendor, `_publish_one` writes to YouTube — and nothing in the tree
executes a T4 action autonomously. That is 51's sentence for Autonomous CEO word for word. Choosing
MANUAL would have been the more cautious-looking answer and the false one: it would have described a
studio that does not exist and refused every stage of the run the Owner has been watching work. 51's
own example seals it — AUTONOMOUS CEO with `public_publish_enabled=false` is a studio that can create
final content automatically but not publish publicly, which is exactly this studio, TEST by default
with no channel set public. `change_autonomy_mode` remains the only thing that can promote.

## 2026-09-18 — A promotion is refused on what the database can read; the rest is said, not simulated

51 requires four things before a higher mode: acceptance criteria, a burn-in, no unresolved P0, and
the Owner's action. **Decision: the two that are readable here are enforced — an open
`safe_mode_record` is an unresolved P0 and `autonomy_stopped` is the Owner saying the studio should
not act, and a promotion is refused on either, in Romanian, with no event written and the version
untouched — and the two that are not are named in the refusal instead of being approximated.**
Acceptance criteria and burn-in are judgements about evidence outside the database; nothing here
measures them, so the refusal names them to the Owner and the docstring says plainly that the command
does not verify them. This is the rule the quality gates follow: a check that could not run says so
and never reports a pass. Lowering the mode is allowed unconditionally — 51 calls it immediate and
safe, and a safety state that blocked the safer choice would be the wrong shape of safety.

## 2026-09-18 — The risk-tier table is transcribed from 31 and 32, and it fails closed

**Decision: every entry in `ACTION_RISK_TIERS` is one of 31's own examples, named as the code names
the operation, with 32's tool risk classes deciding where the boundary between T2 and T3 falls; an
action the table does not know and the caller does not classify is refused `BLOCKED_UNCLASSIFIED`,
and a caller's own tier is only ever taken upward.** T0 is read-only, T1 reversible internal, T2
material internal plus EXTERNAL_READ and the paid generation that stays inside the Owner's budget
(31 reserves T3 for "paid generation beyond threshold"), T3 external, financial and public, T4 the
Owner's alone. The order inside `may_act` is 31's authority hierarchy read top down — stop, then T4,
then safe mode, then the mode — so no mode can ever be the thing that lets a lower layer past a
higher one, and an agent cannot downgrade the risk of its own action.

## 2026-09-18 — SUPERVISED writes an Approval rather than refusing, so the row had to exist

There was no Approval object anywhere in the tree, although 31 specifies its fields. **Decision:
`owner_approval_request` carries them (action, requester, risk tier, evidence, proposed diff, cost,
reversibility, expiry, approver, result); `cost_usd` is nullable on purpose, because a cost the
studio cannot compute is None and never zero; a request is reused while it stands rather than
duplicated; and an expired request is marked EXPIRED and a new one raised, because 31 says an expired
approval cannot be reused and saying so in the row is part of the record.** Answering a request is
deliberately not implemented in this phase: a half-built approval route that nothing calls would be
worse than an honest gap, and the gap is named in CURRENT_STATUS.

## 2026-09-18 — The Policy Kernel asks the mode gate for the run itself, at T1, and calls it `agent.run`

**Decision: `_assert_policy_allows_run` asks `may_act(session, "agent.run", "T1")`, immediately after
the stop check and before the lifecycle check.** An LLM call is a reversible internal write — 31's
"create draft" — which every mode allows, so the question changes no behaviour today; it is added
anyway, because a mode that nothing consults is a label, and this is what will refuse a run if the
Owner ever takes the studio below MANUAL's floor or if safe mode opens under a run in flight. It is
`agent.run` and not `script.draft`, which was the first wiring: from a prompt the kernel cannot tell
what the answer will be used for, and calling every run a script draft would have described the
Accountant's letter and an analytics read as drafting. The tier of what an agent then *does* with the
answer — a page fetched, a shot bought, a film uploaded — is asked by the stage that does it.

## 2026-09-18 — A mode refusal is SKIPPED, not BLOCKED

The runbook's vocabulary is exact: COMPLETED means the stage ran to its end, SKIPPED means it could
not run, and BLOCKED is what the Owner's STOP does — `execute_daily_run` stops the day at the first
BLOCKED stage and marks the rest blocked behind it. **Decision: the mode gate returns SKIPPED with
the Owner's Romanian reason, and the tier, the mode and the approval id in the artefacts.** A MANUAL
studio is not a stopped studio: it may not buy a shot or upload a film, but it may still draft,
storyboard, write the serial's episode and measure what it already has. Recording the refusal as
BLOCKED would have ended the day at the research stage and thrown away the internal work the mode
explicitly permits. The day then comes out PARTIAL, which is what it was.
Superseded in part 2026-09-18: `execute_daily_run` no longer stops the day at the first BLOCKED
or FAILED stage; a stage lost blocks only the stages that depend on it, and the Owner's STOP alone
still blocks everything after it. SKIPPED stays the mode's word, and a skipped stage blocks nothing.

## 2026-09-18 — The upload is T3 at every visibility, and the tier is not read off the channel policy

The tempting version tiers the publish stage by what the film will be: private upload T2, public T3.
**Decision: the tier is fixed at T3 and the channel policy decides afterwards who may see what was
uploaded.** It is wrong twice otherwise. A private upload is still a write to the platform under the
studio's account, which is 32's EXTERNAL_WRITE, and the visibility is a setting the same day's policy
command could change — so the day's riskiest act would have had its risk decided by the thing most
likely to move. It also breaks the mode's shape: SUPERVISED is 51's "configurable T2/T3 actions
create Approval; publishing usually requires approval initially", and a T2 private upload would
publish without ever asking.

## 2026-09-18 — The stop is deliberately not re-read in the mode gate

`may_act` answers BLOCKED_STOP first, and `mode_refusal` treats that answer as "not my refusal" and
returns None. **Decision: the stop stays where it already is — read by the runbook before every
stage, by the media stage before every film, by the render between scenes, by the publishing gate's
five points and by the Policy Kernel — and the wrapper does not become a sixth reader.** A sixth
would add nothing except a new single place where somebody could later think the stop lives, and it
would have changed what a dozen existing tests measure about *other* refusals: a stage called
directly with the stop on would have reported the stop instead of the missing model it was written to
expose. What this gate asks is the question none of the five ask — whether the mode the Owner set
lets the studio attempt the thing at all. The reason is written in the code beside the return.

## 2026-09-18 — Two layers, on purpose: the stage and the act

**Decision: `STAGE_ACTIONS` maps each stage to one action and one tier, tested against
`ACTION_RISK_TIERS` so the two tables cannot drift, and the stages that spend or publish ask again
per film.** The table is what makes "the day's stages mapped to tiers" readable — one line per
stage. The act-level calls are where the answer is specific: `_media` asks again per film with that
film's estimate as the cost on the Owner's question, and with `media.paid_generation_over_threshold`
when the estimate passes his line, so the approval he reads names a figure; `_publish_one` asks again
per film after the Director has approved it and the five-point gate has passed it, so he is asked
about a film that is otherwise ready to go rather than about a hypothetical. `request_approval`
reuses a standing request for the same action, so the two layers cannot bury him under duplicates —
the SUPERVISED end-to-end day writes exactly one row.

## 2026-09-18 — The paid-generation threshold is a setting, because a tier boundary with no number cannot be moved

31 says "paid generation beyond threshold" and names no figure. **Decision: the figure is the
Owner's — `paid_generation_approval_threshold_usd`, default five dollars — read by
`runbook/stages.py::_media` against the film's own `estimate_film_cost_micros`.** Five, because a
six-second shot on `seedance2_5` costs about 2.60 USD on his account and two shots is where one
film's spend stops looking like routine. It changes nothing in AUTONOMOUS_CEO, where both tiers are
allowed: it is the line that decides which question SUPERVISED asks, not a second budget. The
per-film ceiling he already has (`motion_budget_usd`) stays what it is — what a film may spend, not
who decides that it may.

## 2026-09-18 — The preflight's third severity is structural, not polite

**Decision: `INFORMATIONAL` exists as a severity and the preflight's verdict is computed over the
other two only, so an informational line cannot reach `blocking_failures` or `degrading_failures`
even if it reported `ok=False`.** The mode had to appear where the Owner reads the studio before a
run, and it must never fail one: MANUAL is his answer, and a preflight that called it DEGRADED would
be asking him to repair his own decision. A check that is simply always `ok=True` would hold only as
long as nobody edited it. One existing assertion (`test_every_check_says_what_it_found`, which
enumerated the two severities) was widened by one word; nothing else in the tree reads severity.

## 2026-09-18 — `ReferenceRequired` is caught beside the vendor's refusal and settled in the same order

It is a `ValueError`, not a `MediaProviderError`, so the assembler's existing handler would have let
it escape with the job left RENDERING — a render nobody could price afterwards. **Decision: it fails
the job like any unfinished render, which is what lets `record_failed_render_cost` read what was
already bought, and is re-raised as itself; the media stage costs the attempt first and releases the
hold second, the same order and for the same reason as a vendor's refusal.** The estimate stops
counting exactly when the real cost of the attempt starts. It is not a fault and opens no safe mode:
tomorrow's run tries the film again, and producing the character's reference set is the Owner's act.

## 2026-09-18 — The assembler and the Accountant were edited by the integrator, and are named here

`backend/app/media/assembler.py` and `backend/app/economy/accountant.py` were outside the file list
of the implementer who built the chain, and nothing works without them: passing `image_chain` into an
assembler that does not accept it is a keyword error, and recording per-attempt costs that
`_priced_scene_costs` never reads leaves a scene the alternative drew charged to the first vendor's
model. **Decision: the integrator made exactly the two changes the report specified — the two new
keyword parameters and the per-scene attempt records in the assembler, and `scene["image"]` before
the film-level `production["image"]` in the Accountant — and they are called out in the change list
rather than folded in silently.** Both files were untouched in the working tree, so no other
session's work was overwritten.

## 2026-09-18 — Migration numbering: 0041 and 0042 were reserved and not used; 0043 is the head

Three implementers were given 0041, 0042 and 0043 in order. **Decision: the first two took no
migration and said so — the picture and character verdicts live in the existing
`quality_control_report.checks_json`, and the reference set and the approved-fallback lists live in
columns and JSON that already existed — so `0043_autonomy_mode` chains onto `0040_research_sources`,
its docstring records that 0041 and 0042 are free, and `backend/app/main.py` pins 0043 as the head.**
A migration written only to hold a number would be a schema change nobody needed, and a gap in the
numbering that the head pin and the docstring both explain costs a reader one sentence.

## 2026-09-18 — `50_CONTENT_GATE_MATRIX` names the two gates that now exist, and its hash is re-indexed

The matrix listed "Visual factual QC" and a continuity row as gates of the pipeline, and the code had
neither: `character_drift_qc` reported NOT_IMPLEMENTED on every film ever made and nothing anywhere
looked at a frame. **Decision: this is a deliberate specification change under ADR-FOUNDATION-003 —
the gate table gains the two rows the code now runs (`picture_qc` and `character_drift_qc`, at
render and before publish), the gate-behavior section states what each status certifies and that
NOT_APPLICABLE and NOT_IMPLEMENTED carry a reason and a `passed` of None, and a new section states
what the picture gate measures and the four ways it stands down — and the document's `sha256` in
`DOCUMENTATION_INDEX.json` is updated in the same change (`f7da10d8…` → `a436dab0…`), with this
entry as the recorded reason.**
Nothing was removed: every row and rule the matrix carried is still there, and each addition is dated
in place so a reader can see what the matrix claimed before.

## 2026-09-18 — `51_AUTONOMY_MODE_SEMANTICS` says which of its sentences are code and which are not

51 described three modes, a transition rule and a department scoping, and the studio had a constant.
**Decision: this is a deliberate specification change under ADR-FOUNDATION-003 — each mode section
gains a dated line naming the column, the command and the tier the code actually allows; the
transition section states that two of its four requirements are enforced and two are named in the
refusal because nothing in this database can measure them; the department section is marked as not
implemented rather than left reading as current behaviour; and the STOP and SAFE_MODE sections name
where they are enforced — and the document's `sha256` in `DOCUMENTATION_INDEX.json` is updated
(`17cb4169…` → `33f42c6c…`) with this entry as the reason.** A specification that is silent about which of its sentences are built is
the way a reader comes to trust none of them.

## 2026-09-18 — `24_VISUAL_CONTINUITY_ASSET_SYSTEM` says who produces a reference set and what it costs

24 listed portrait, full-body and front/side/back references as properties of a Character Bible and
said nothing about where they come from, while every slot was null in every studio that ever ran.
**Decision: this is a deliberate specification change under ADR-FOUNDATION-003 — the Character Bible
section states that a slot holds a stored asset id or nothing and never a description standing in for
an image; a new dated section states that reference sets are produced by an Owner-triggered route
that spends image credits, refuses under STOP AUTONOMY, holds the money for the whole set before the
first slot, and is named by no stage of the day; the provider-capability and degraded-mode sections
name the reference-image capability the code queries and the one approved alternative per purpose;
and the QC-checks section points at the gate that now measures face, hair, outfit and wrong-employee
drift and at what it cannot see — and the document's `sha256` in `DOCUMENTATION_INDEX.json` is
updated (`8a5d4396…` → `73d5c9cd…`) with this entry as the reason.**

## 2026-09-18 — `08_VIDEO_PIPELINE` was examined and deliberately left unchanged

The second vendor was the one change of this phase that could have made the video pipeline document
untrue. **Decision: it does not, and 08 is not edited.** 08 already says that autonomy must not
depend on one generative video vendor, that IMAGE_PROVIDER has a "reference/edit if supported"
method, that a provider that cannot preserve a character means "change provider" or fail continuity
QC, and that repeated generation failure should simplify, switch provider, fall back or block —
which is the chain the code now implements, bounded at one alternative and ending on the placeholder
still QC blocks. Editing a document to restate what it already says would spend an index hash on
nothing and teach the next reader that the hashes move for cosmetic reasons.

## 2026-09-18 — The roadmap, the changelog and PROJECT_STATE are ticked against this phase

`13_ROADMAP_TODO.md` carried `character drift QC` as flatly unimplemented and
`Manual/Supervised/Autonomous` as "STOP flag plus a dormant-by-default schedule", and
`PROJECT_STATE.json` carried `autonomy_mode: "MANUAL"`, migration 0040 and 1067 tests. **Decision:
the closed boxes are ticked with the date and the evidence, the two that are only half closed are
marked `[~]` with what is missing named in the same line — a picture gate that stands down in the
live studio because no employee's model declares vision, an approval that is written and cannot be
answered — and `PROJECT_STATE.json` moves to `0043_autonomy_mode`, 42 migrations, AUTONOMOUS_CEO and
1148/1.** A tracking document that keeps listing closed work teaches the next reader to stop reading
it; one that ticks a box the studio cannot actually exercise teaches him worse.

## 2026-09-18 — A request is keyed by the action and the subject, and the subject is an identifier the studio already has

The adversarial pass left one defect standing because nothing could yet exploit it: `request_approval`
deduped a standing request by its `action` alone, so under SUPERVISED the second, dearer film of a day
reused the first film's row, carrying the first film's evidence and the first film's price. An
answering route on top of that would have let a yes to a four-dollar film authorise a forty-dollar one.
The candidates for a key were the evidence string, the channel and the film. **Decision: the key is the
action plus `subject`, a new column on `owner_approval_request` (migration `0044_approval_answered`)
holding the identifier of the thing the question is about — the media asset for an upload, the
storyboard for a paid render.** The evidence is prose for the Owner to read; it changes when the
Publisher rewrites the title and is truncated to fit, and a key that moves when the wording moves is
not a key. The channel is too coarse in the other direction: two films reach one channel across two
days and one answer would cover both. The film is what he is actually being asked about and what the
act itself writes, and the channel derives from it, so keying by the film keys by the channel for free.
A re-render produces a new asset id and therefore a new question, which is the conservative reading and
the right one: he approved the film he was shown. An action with no subject keeps the old behaviour
under an empty string, because an action about the studio itself has one answer by nature.

## 2026-09-18 — The daily run's stage wrapper asks the mode and does not ask the Owner

The same defect existed one level above `request_approval`, where nothing had looked.
`build_stage_runners` asked `may_act` for the publish stage before the stage ran, with no film on the
request: under SUPERVISED that answer skipped the stage outright, so `_publish_one`'s own per-film gate
was unreachable code, one answer would have authorised every film of the day, and a studio with nothing
in the publish queue still put a question in the Owner's inbox. **Decision: `may_act` and `mode_refusal`
gain `ask_owner=False`, and the wrapper uses it — the mode is asked without anything being written and
without any answer of his being spent, and the caller that can name the film does the asking.** A mode
that refuses outright — MANUAL on a T3, safe mode, T4 — still refuses at the wrapper, so nothing above
the mode moved. The proof changed with the fix: the end-to-end SUPERVISED day used to record one
request for the whole day and now records two, one for the factual short and one for the serial's
episode, each with its own subject.

## 2026-09-18 — The Owner's answer is spent inside `may_act`, not beside it

The publish stage could have looked for an APPROVED row itself and then skipped the gate. **Decision:
the answer is read in exactly one place, the SUPERVISED T3 branch of `may_act`, after the unclassified
refusal, the stop, T4 and safe mode have each had their say.** Reading it beside the gate would have
put his yes *above* the authority hierarchy of 31 instead of inside it, and the first thing anyone
would then have had to re-derive is what a stop means for a film that was already approved. Inside, the
whole of 31's order comes for nothing: an approval can only ever convert the one verdict it is about —
"he would have to be asked" becomes "allowed, once" — it can never reach a refusal above it, and every
one of those refusals leaves the yes unspent, which is the behaviour a stop should have. It pauses the
studio; it does not retract what he decided.

## 2026-09-18 — A column is the lock, the ledger is the record, and the yes is spent before the act

**Decision: `consumed_at` on the row is what the gate reads, `governance.approval_consumed` is written
beside it, and the spending happens before the act it authorises rather than after.** A gate that had to
walk the event history for every film would make the day's riskiest decision depend on a scan, and the
index (`action`, `subject`, `result`) is exactly the query the publish stage makes once per film; the
event is written anyway, because the column alone would leave "the film went out on the Owner's yes" as
a nullable timestamp nobody reads. Spending it first is the conservative direction: an upload that then
fails costs him one more question tomorrow, where the alternative costs him an upload he only agreed to
once.

## 2026-09-18 — What a stop, an incident, a lowered mode and a moved policy version each do to an answer he has already given

**Decision, written into the code and now into 31: a STOP AUTONOMY and a SAFE_MODE refuse before his
answer is looked for at all, so the yes is still there, unspent, when he lifts the stop or the incident
closes — neither of them is him changing his mind. A channel policy version that moved after he
answered does retract it, because he said yes to this film going out at that visibility under that
version: the proposed diff he was shown is compared at the moment of spending, the stale yes is left on
the record unspent, and a fresh request naming the new policy is raised. Lowering the mode to MANUAL
refuses too, and never looks for the answer: MANUAL is him asking to be asked about everything, and an
answer given under a more permissive mode must not be the way past the mode he chose to replace it.**
This is 31's "gate immutability" read for approvals — an approval applies to an exact version, never to
an idea — and it is now specified there rather than living only in the order of four branches.

## 2026-09-18 — A refusal is COMPLETED, an unanswered question is SKIPPED

The publish stage's vocabulary was already exact: SKIPPED means the studio could not do the work,
COMPLETED means the work was done and the answer was no, which is how the Director's refusal and the
Publisher's HOLD are already recorded. **Decision: the Owner's refusal is an answer, so the stage
reports COMPLETED with `refused_by_owner` and the approval id, and the status is deliberately spelled
`REFUSED_BY_OWNER` and not `BLOCKED_OWNER_REFUSED` — the studio was permitted to ask and got an answer,
which is not a block.** A question still standing stays SKIPPED with `awaiting_owner` and the approval
id, as it was. The film keeps the verdict quality control gave it, because he said no to sending it out
and not that anything is wrong with the film, and nothing asks again until his decision expires — the
same 24-hour clock that decides how long an unanswered request stands.

## 2026-09-18 — The decision command carries no `expected_version`

The Owner's other commands guard `owner_policy.version`, because that row is edited by several commands
and a page can read it minutes before it writes. **Decision: `ApprovalDecisionCommand` carries a command
id and no expected version, because the row it answers has no version to be stale about.** An approval
request's whole life is one transition, PENDING to answered, made by one command; the only thing that
can go wrong is answering twice, and that is refused directly with 409 and the result the row already
carries. A version column would have been a guard against a race that does not exist, and a schema
change to express it. An expired request is refused the same way and is deliberately left PENDING on the
way out — it is filtered out of everything that reads it by its own expiry, and a command that fails
must not be the thing that changes state. A request the studio never made is 404, because that is what
it is: a stale page, not a governance conflict.

## 2026-09-18 — Nothing is written into the agents' memory when the Owner answers

The mode, the environment and the stop each write an `OWNER_POLICY` memory every agent reads, because
each is a standing rule about how the studio works. **Decision: an approval writes none, and
`decide_approval`'s comment says why the pattern is broken here on purpose.** An approval is about one
film. A letter to every agent for every upload would be the noise that makes the standing rules
unreadable, so the answer lives in the row, in the ledger and in the stage's own report.

## 2026-09-18 — The Owner's two buttons are measured by the day's rules, not by their own

A film read twice — once by the stage and once by the Owner — disagreed about which gates had run at
all: the stage handed quality control the registry and the encoder, the route handed neither, and
`picture_qc` and `character_drift_qc` came back NOT_APPLICABLE with a reason that was true of the caller
and not of the film. **Decision: both `evaluate_media_qc` call sites in `backend/app/media/router.py`
pass `registry` and `ffmpeg_path`, read from where the app already holds them, so the Owner's reading of
a film is the reading the day would have given it.** This does mean his Quality Control button may now
make one vision call and cut frames with FFmpeg inside the request, where before it only probed the
container — it is his act, on his provider, and it is the same single call per film the stage makes.
With no vision-capable model, no registry or no encoder it is still NOT_APPLICABLE with the reason and
the verdict is exactly what the other gates left it: nothing there passes by absence.

## 2026-09-18 — An injected adapter stays the only vendor; the character's reference travels regardless

`app.state.image_adapter` is how a test says "this vendor draws this film". **Decision: `start_render`
passes the plan's `image_chain` only when nothing was injected, and passes `reference_for_scene`
unconditionally.** Handing the assembler the studio's resolved vendors in front of an injected adapter
would break what injection means, and the route already applied that rule to the injected voice. The
reference is not a statement about a vendor: it resolves which character's stored sheet a scene must be
drawn from and refuses a film whose locked character has none. Suppressing it for an injected adapter
would let exactly the render that is easiest to run invent a face the Owner locked.

## 2026-09-18 — A missing reference is a refusal with its own answer, not a lost storyboard

`app.media.services.ReferenceRequired` subclasses `ValueError`, and `start_render` answered every
`ValueError` with 404 and the exception's text, so the studio declining to invent a locked character's
look was reported to the Owner as "storyboard not found" about a storyboard sitting in front of him.
**Decision: it is caught before the `MediaProviderError` handler and answered 422 with
`error: ReferenceRequired`, a Romanian message telling him to produce the character's reference set
first, and the refusal's own text naming the character.** It is deliberately not a 502: the vendor did
nothing wrong.

## 2026-09-18 — Runway is given the picture in the field its own contract publishes

`RunwayImageAdapter` could not be handed a reference at all, so `accepts_reference_image` read False for
it, the chain dropped the sheet, and a Runway-drawn still of a locked character was honestly recorded as
drawn from the words. **Decision: the adapter sends `referenceImages` on the documented `text_to_image`
task as an array of one object whose single required member is a `uri`, built as an inline data URI by
the same helper that has always validated an image-to-video first frame — so a reference given as a
path, an id, or bytes that are not a PNG, JPEG or WebP is refused before the task is submitted — and the
result's raw response counts `reference_images` 0 or 1.** The studio holds the bytes of the sheet it
produced and not an address anybody else can fetch, which is why it is the inline form. No `tag` is sent
with the reference: a tag means something to Runway only when the prompt names it as `@tag`, and
inventing one would change the words the Director approved. The per-attempt count is what makes a
render's record able to say whether a character's face came from their sheet or from the words.

## 2026-09-18 — The contract refusal for a model that requires references was about the missing picture all along

The adapter refused any model whose published contract lists `referenceImages` as required —
gen4_image_turbo, which answered HTTP 400 to every scene of a day drawn from words alone. **Decision:
that refusal now fires only when no reference was given**, because with a character's sheet in hand the
stated reason, that the model cannot generate a still from a prompt alone, is no longer true. The
catalog still keeps such a model out of the `image` purpose, so nothing in the studio chooses one for a
storyboard whose scenes may have nobody in them; the path exists for a model the Owner names by hand and
it has never been run.

## 2026-09-18 — What the code builds and what the account has answered are two statements, and both are recorded

**Decision: `ACCEPTS_REFERENCE_IMAGE` is True on the Runway image adapter because the code builds the
documented field, `REFERENCE_IMAGE_VERIFIED` stays False as it does on the OpenAI adapter until an
Owner-approved live run has actually drawn a scene this way, and a test asserts the second flag is
False so nobody can flip it on mock evidence.** No test may spend a credit to find out. Neither
adapter's reference path has ever been accepted by a vendor, and an HTTP 400 on the first real render is
the thing to watch: that is how the last unread contract detail announced itself.

## 2026-09-18 — The autonomy mode is shown where the studio's state is shown, and the page refuses only what it can see

The autonomy switch, the environment banner and the module list are the three things that say what the
studio is; the mode is the fourth. **Decision: the governance panel lives in the ledger column under
`modules-panel`, inside `#workspace` so it is invisible until the Owner has a key, and it refuses a
promotion it can already see is impossible while never refusing one it cannot see.**
`promotionBlockedReason` reads only the stop, which is in the snapshot, and says so in his language
before spending a request; SAFE_MODE is not in the snapshot, so the page does not infer it, does not
grey the button out on a guess, and prints the server's own 409 sentence when it arrives. A blocked
mode button therefore stays pressable, because pressing it answers *why* and a disabled button cannot.
An unconfirmed mode command is resent only when its `autonomy_mode` is the one now being asked for and
replaced otherwise, because with three modes a slow network is one decision and a change of mind is a
different one — the two-state switches of the stop and the environment could keep a single pending
command and this cannot.

## 2026-09-18 — The approvals list is read on a slower clock, a missing route is said once, and every card repeats what an approval is not

An approval stands for a day. **Decision: the panel reads `GET /api/v1/owner/approvals` at most every
thirty seconds, immediately after any decision and whenever the Owner presses refresh; a backend that
answers 404 is recorded as not having the route and stops being asked, with one sentence saying the
requests exist in the database while the route that shows them does not.** Fetching a list nobody
answered sixty times an hour, or repeating a 404 every five seconds, teaches its Owner to ignore the
panel. **And every request card carries, in Romanian, the sentence that an approval lets a permitted
action happen and never turns a hard gate's refusal into a pass** — 31 says a hard gate's result cannot
be overridden, and the most likely misreading of a green «Aprobă» button is that it makes something
pass.

## 2026-09-18 — A cost nothing could compute stays «necunoscut» on the page, and a reference set takes two presses

**Decision: `approvalCostText` returns «necunoscut» for anything that is not a finite number and
`0.00 USD` only for an actual zero, the panel prefers the server's own `cost_label` when the row carries
one, and the same function labels the reference set's price.** A page that formatted `cost_usd` itself
would show "0 USD" for a question nobody can price, which is the one number the books are written never
to invent. **And the reference-set button states its cost on the first press and generates nothing until
the second**: the slots are drawn as chips rather than summed into a ratio, because "3/5" does not tell
him which slot is missing — and a missing reference is exactly the reason a locked character's scene is
refused.

## 2026-09-18 — The panel's judgements were put in a module so that they could be tested

`main.js` touches the document at import, so `node --test` cannot load it. **Decision: rather than
invent a DOM harness, the decisions that matter — what a mode means, whether a promotion is possible,
how a request's cost and expiry read, which slots a character has, what shape each command takes — moved
to `frontend/src/governance.js` and are tested there (14 tests, 102 in the frontend suite, `tsc`
clean).** What remains untested is the wiring: which element the text lands in, and that a click reaches
the right function. That is recorded as untested rather than covered by a harness that would have proved
something else.

## 2026-09-18 — `31_GOVERNANCE_APPROVAL_POLICY` is edited and re-hashed; 51 is corrected; 50 is left alone

31 specified the Approval object and stopped there: it said an expired approval cannot be reused and
said nothing about how one is answered, how it is consumed, that one approval authorises exactly one
action, or what a STOP, a SAFE_MODE or a policy-version change does to one already given. The code now
answers all four. **Decision: 31 gains one dated section, *Answering an approval, and spending it*, as a
deliberate specification change under ADR-FOUNDATION-003, with its `sha256` re-recorded in
`DOCUMENTATION_INDEX.json` (`c788e9bc…` → `b4aedc31…`) and this entry as the reason.**
`51_AUTONOMY_MODE_SEMANTICS` carried two sentences this closure makes untrue — a **Not built:**
paragraph saying nothing answers a request, and "writes exactly one request" for a whole SUPERVISED day
— so its Supervised section is corrected in place, dated, with its `sha256` re-recorded as well
(`33f42c6c…` → `f5f96f18…`). **`50_CONTENT_GATE_MATRIX` was read and deliberately left unedited, its
hash unchanged:** the picture and character gates it describes are unchanged by this closure, and the
Owner's route now running them is a fact about a caller, not about a gate. Editing a document to restate
what it already says spends an index hash on nothing.

## 2026-09-18 — The closure's recorded figures are attributed rather than invented

No whole-suite run has been made since the three closure parts landed, and the brief for this part
forbids running one. **Decision: the last whole-tree figure (1152 passed, 1 skipped) is left standing in
CURRENT_STATUS and PROJECT_STATE as what it is — the adversarial verifier's measurement, now older than
the tree — and every figure this closure adds is written with the part that measured it beside it:** 231
Python tests across the files the governance part owns and their neighbours, 186 across the media part's
four files and its regression set, 102 frontend tests with 14 new, and `check_docs.py` plus
`tests/test_documentation.py` for this part. `javascript_passed` moves 87 → 102 because that figure *is*
a whole-suite measurement of its suite; `python_passed` does not move, because inventing a number for a
run nobody made is the one thing these documents exist to prevent.

## ADR-PREFLIGHT-003 — The preflight reports what only the Owner can supply
**Status:** Implemented, 2026-09-18

Problem: the preflight answered "can the day start" and nothing answered "is the day worth having".
Five things decide whether the first real day produces a quality film, every one of them was measured
as absent on the live copy, and the Owner had no single place that told him: no active budget, no
price for the models the employees run on, no employee whose model declares vision, five reference
slots null in every studio that has ever run, and a serial channel with no leave for the Director.
Choice: five more checks in `app.runbook.preflight`, each reading the database only —
`app.economy.budget.budget_status`, `app.economy.prices.price_for` on both token units,
`app.agents.vision.vision_agent`, `CharacterBible.reference_assets_json` against `MediaAsset`, and the
OFFICE_SERIAL `ChannelRecord` with `channel_bindings`. Rejected: probing a vendor to confirm a price
or a model's vision (a preflight that made outbound calls would be slow, would fail for reasons
unrelated to the studio, and under the Owner's rule of 2026-09-17 would cost money to answer a
question the record already answers), and reading a vendor's published price to fill a gap in the
price table (a guessed price in the books is worse than the gap the Accountant reports). No schema
change: every fact these checks need is already a column.

## ADR-PREFLIGHT-004 — A check never blocks the day for something the Owner chose
**Status:** Implemented, 2026-09-18

Problem: a budget the Owner has not set while the studio is in TEST, and a serial channel he has not
created, are answers of his, not capabilities the studio is missing. A preflight that refused the day
over either would be asking him to repair his own decision, which is the same mistake `autonomy_mode`
avoided by being INFORMATIONAL. Choice: none of the five is BLOCKING; `serial_channel` is
INFORMATIONAL always, and `character_references` is DEGRADING only where a character whose look is
*locked* has no readable reference — that case really does refuse a film
(`image_reference_for_scene` raises rather than invent a face), so it is a blocked day the Owner can
prevent in advance; an unlocked character with no picture is a line he reads. The verdict is computed
over BLOCKING and DEGRADING only, so this holds structurally rather than by the checks happening to
pass, and a test asserts that a studio with nothing configured still reports exactly `stop_autonomy`
and `llm_provider` as blocking.

## ADR-GOVERNANCE-006 — How long an approval stands is the Owner's setting
**Status:** Implemented, 2026-09-18

Problem: `APPROVAL_EXPIRES_AFTER_HOURS = 24` was a module constant in `backend/app/services.py`. One
number decides three things — how long an unanswered question stands, how long a refusal keeps the
studio from asking again, and how long a yes can be spent — and the Owner could not reach any of them
without a source edit. Choice: `approval_expires_after_hours` on `Settings` (default 24, `ge=1`,
`le=168`, `STUDIO_APPROVAL_EXPIRES_AFTER_HOURS`), with the bounds stated as what they protect: below
an hour a question could expire before he reads it, above a week a yes could be spent long after the
film it was asked about. `services.py` reads it through `approval_expires_after_hours()`, a local
import of `Settings` with `getattr` and a documented fallback of 24 — the shortcut `providers.retry`
and `integrations.autoconfig` already take, because this module is called from inside a session and
has no handle on the application, and a studio whose settings cannot be built must still be able to
ask the Owner a question rather than raise while asking it. Behaviour unchanged;
`tests/test_approvals.py` (18) and `tests/test_autonomy_modes.py` pass untouched.

## 2026-09-18 — PREFERRED was honoured nowhere, so it was implemented in the hiring path and not by making it REQUIRED

`RoleCapability.requirement_level` accepted any string, but the only readings in the whole codebase
were `== "REQUIRED"` in `_check_required_capabilities` (`backend/app/agents/services.py`) and,
indirectly, in `assign_agent`. The "PREFERRED" in `backend/app/integrations/lifecycle.py` is the last
step of a model's life (DISCOVERED → … → PREFERRED), not a requirement level, so there was no
precedent for a preference in assignment at all. **Decision: implement it where the role is owned —
`seed_role_preferences` writes the PREFERRED row on the Video Editor's role, idempotently at every
start-up so that it also reaches a studio whose roles were created earlier, and
`prefer_capable_models` acts on it.** Making the capability REQUIRED was rejected: it would have
blocked the role in a studio with no seeing model, which is exactly what the brief forbids. The move
writes `agent.model_preferred`, never `agent.model_assigned`: the second event is the proof of the
Owner's choice and `apply_llm_allocation` reads it as "already configured", so writing it here would
make the next start-up read the studio's own move as his and stop applying his allocation file. A
candidate must be available and declare everything the role *requires*, not only what it prefers,
otherwise the move would trade a working employee for one the Policy Kernel blocks. `list_roles`
still returns REQUIRED capabilities only — the field is called `required_capabilities`, and listing a
preference there would tell the Owner the Video Editor needs a seeing model to work at all, which is
false.

## 2026-09-18 — `vision` is a row in the table, not a claim about any model

The seed now creates `Capability(name="vision")`, because a role can only prefer a capability the
studio has by name. **Decision: attach it to no proposed model.** `SEEDED_MODEL_CAPABILITIES` names
the four text capabilities explicitly, replacing the loop that wrote "every capability" onto every
proposed model. Nothing in the seed contacts a provider, so a seeded guess that a model can see would
make the picture gate certify a look nobody took; `sync_provider_models` attaches `vision` where the
vendor itself declares it, which is the only evidence that exists.

## 2026-09-18 — A factual scene's cast is read from the scene itself, in two readings, in the order of the evidence

**Decision: the scriptwriter's `characters` list first (the shape the serial's script already uses),
then the names in the requested picture (`visual_prompt`/`visual_description`, read through one
`_scene_visual` so the cast and the scene cannot disagree about what the picture says). The narration
is not read at all:** in a factual film it is the narrator's voice, and a name spoken over a
photograph of a mirror does not put that person in frame. Matching is on the full canonical name or
the first name — the rule `app.story.services.bibles_for_roster` already uses to match a cast member,
without the title that rule keeps by mistake ("Aris", not "Dr.") — capitalised as in the bible, and
never on a first name followed by another capitalised word, so that the observer "Vera Rubin" stays a
telescope. The cost of that last rule is a Title Case scene whose character is missed; the cost of
dropping it would have been an invented cast, and a gate comparing a film against a cast nobody put
in it certifies nothing.

## 2026-09-18 — "No cast, by design" is written in the storyboard's creation event, not in a new column

The ledger is where the studio already keeps facts of this kind (`agent.model_assigned` is exactly
such a fact), and what is needed here is a record, not a lock. **Decision: `media.storyboard_created`
carries `scenes_with_cast` and `cast_note`, read back by
`app.media.services.storyboard_cast_note(session, storyboard_id)` and returned by `get_storyboard` as
`cast_note`.** So migration 0046 was not taken and the revision chain keeps one head, the one the
economy moved with 0045. A storyboard written before this revision, or one whose scenes do list
characters, answers None: "nobody said" and "somebody is in it" are both not this.

## 2026-09-18 — The letter about what is waiting is one a day, not one a question, and does not exist when nothing waits

The pattern followed is `_letter_once_a_day` exactly: idempotent on the studio's business date,
decided behind the write lock, so two stages of the same day cannot write two letters. **Decision:
one letter per day naming every standing question, and nothing at all when nothing is standing.** A
letter per approval request would have buried the single decision he has to make under duplicates —
the mistake `request_approval` already avoids by keeping one request per (action, subject). The
silence is meaningful: a day with no letter means nothing is being asked of him. The questions are
ordered as the day raised them (by `created_at`), so the first line is the oldest and the deadline in
the last line is its deadline. The cost of a question is read from the request itself
(`approval_view.cost_label`, «necunoscut» where `cost_usd` is None) and never recomputed, so the
governance page and the mailbox cannot say two different things about the same question; the
model-written evidence enters the text cut at 120 characters, because it is what the panel shows
beside the same question and a long title may not become the whole letter. `reconcile_day` calls it
as its first act rather than its last: a close that fails because a model never produced the report
must not swallow the only letter saying he has decisions standing.

## 2026-09-18 — Reconciliation marks the estimate, it does not subtract it

The obvious variant — subtracting the estimated sum from the period — would have required
`spend_since` to know about invoices and would have left the books with a figure that can no longer
be reconstructed from the rows. **Decision: the estimate is kept whole, because it is the document of
what the studio believed a film would cost, and is stamped `reconciled_at`; `spend_since` skips it.**
The BILLED row the invoice writes carries the hour of the last spend it pays for, so it falls in the
same period as the estimates it replaced. The exact consequence: after a reconciliation a period
counts the billed sum once, plus any row in the period the invoice did not cover, and
`treasury_snapshot.unbilled_provider_costs` falls the same way, because an estimate that has been
paid is no longer an obligation coming. **An invoice over an already reconciled period is refused
without `expected_version`, unlike a price:** `set_price` accepts a command with no version and
replaces what stands, which here would let an inattentive command reverse a ledger posting. The
correction, when it comes with the right version, posts the mirror of the previous transaction
(`reverses_transaction_id`, as `reverse_transaction` does), stamps `reconciled_at` on the invoice it
replaces so it stops being counted, and re-adopts the estimates the first one covered. The ledger
stays append-only and the balance stays closed.

## 2026-09-18 — What could not be matched is reported, never dropped and never kept quiet

`unmatched_json` sits on the reconciliation row and not only in the HTTP answer, because a spend the
invoice does not explain is the finding, not a detail of one request. Three kinds: a row already
reconciled by another invoice (it cannot be paid twice), a row already billed directly (it is not an
estimate to replace), and the case where the invoice covers no estimate in the books at all — the sum
is still recorded, with the reason, because the vendor billed whether or not the studio can explain
it. The difference between what the vendor billed and what the studio estimated is reported as a
figure (`difference_vr`) rather than melted into the total: that distance is the price of an
assumption.

## 2026-09-18 — The migration head moved to 0045 in `main.py`, and 0046 stayed free

`backend/app/main.py` is not the economy's file, but every test that starts the application fails at
start-up if the database revision is not the pinned one, so one line and the comment that says why
were changed there. The brief reserved 0045 for the economy and 0046 for the media part; the media
part needed no column and took neither. **Decision recorded here so the next phase does not have to
rediscover it: the chain is 0039 → 0040 → 0043 → 0044 → 0045, `main.py` pins `0045_reconciliation`,
and 0046 is free.** If a future part needs a cast column on `storyboard`, that is the number to take.

## 2026-09-18 — `39_DAILY_AUTONOMOUS_RUNBOOK` is edited and re-hashed

The runbook's preflight section listed the checks the day makes, and five were added on 2026-09-18
that it did not name — including two that report a state no severity in the document had, because
they never fail the day. Its post-run section said "reconcile cost" and nothing about the letter the
day now sends the Owner before it closes. **Decision: 39 gains two dated paragraphs — the five new
checks with their severities and the rule that none of them blocks, and the waiting-approvals letter
as the first act of the close — as a deliberate specification change under ADR-FOUNDATION-003, with
its `sha256` re-recorded in `DOCUMENTATION_INDEX.json` (`1de4ef7a…` → `226397b6…`) and this entry
as the reason.**

## 2026-09-18 — `15_SECURITY_COSTS_OBSERVABILITY` was read against the new books and deliberately left unedited

The question asked was whether that document still describes the books truthfully now that a
reconciliation exists. It does: its *Cost controls* section already requires recording "estimate
before action; reserved amount; actual/reconciled amount", and its financial metrics already list
"reconciliation backlog" — sentences that were aspirational when written and are now met by
`reserve_spend`, `record_render_costs` and `provider_reconciliation`. Nothing in it is false, and its
hard boundary (no ordinary agent's tool may hold outbound payment authority) is untouched by a route
that is Owner-only through `require_owner`. **Decision: report it as incomplete rather than edit it,
and spend no index hash.** What it does not say, and what a later editor of that document should add
if it is opened for another reason: that reconciliation is the Owner's act alone because only he sees
the invoice; that the estimate is kept and marked rather than replaced, so a period counts the
estimate until the invoice arrives and the invoice afterwards, never both; and that an employee's
token cost is computed in `agent_run` and never passes through `provider_cost_record`, so it is the
one spend no invoice can yet reconcile. Editing a document to restate what it already says spends an
index hash on nothing.

## 2026-09-18 — «Ce are Owner-ul de făcut» becomes an ordered checklist, and keeps every line it had

The section had grown by accretion: eleven bullets in the order the phases that needed them landed,
inside the Money-and-sources section, which is not the order a person does them in on the morning of
the first real day. **Decision: rewrite it as a numbered checklist — migrate, build, read the
preflight, budgets, prices, token ceiling, sites and search engine, channels and their policy, a
model that can see, the character reference sets, the fallback vendors, the autonomy mode, and only
then the clock — move it under the readiness section, and leave a dated pointer where it stood.**
Every existing bullet's content is kept and each line now carries three things: what to do, with what
command or screen, and what happens if he skips it. Activating the daily job and installing the
scheduled task are last on purpose: the Owner's rule of 2026-09-17 is that video generation costs
money and happens only after everything is proven, and steps 1 to 12 are what "everything" means.
Reconciling a vendor's invoice is step 14 because it cannot be done before there is a real spend to
reconcile.

## 2026-09-18 — The readiness phase's figures are attributed, and the suite figure is left for the verifier

No whole-suite run was made by any of the four parts of this phase, and the brief for the documents
forbids running one. **Decision: every figure recorded for this phase is written with the part that
measured it beside it — 11 + 46 and its neighbours for the preflight part, 359 across five owned and
nineteen neighbouring files for the workforce and storyboard part, 11 + 17 + 34 + 18 and its
neighbours for the economy part, `check_docs.py` and `tests/test_documentation.py` for this one — and
`PROJECT_STATE.json` keeps 1194 passed / 1 skipped as what it is: the Phase D/G closure's adversarial
verifier's measurement of 2026-09-18, now older than the tree.** The whole-suite figure for this
phase lands when the verifier takes it, after these documents. Inventing a number for a run nobody
made is the one thing these documents exist to prevent.

## 2026-09-18 — The preference is applied where the studio learns about models, not only where it hires

The adversarial reading of the first-day checklist measured that `prefer_capable_models` ran once, at
seed time, hours before the Owner admits a seeing model, so the whole quality story of the first day
rested on him also assigning that model to an employee by hand. **Decision: call it a second time
from `sync_provider_models`, immediately after `apply_llm_allocation` and before the models are read
back, inside its own try/except, so a preference that cannot be applied is reported and the models
the sync did record are kept — exactly the rule the allocation call above it already follows.** The
position is not a matter of taste: `record_declared`, in the same function, is the only code in the
studio that ever writes `vision` on a model, so the sync is the first instant a seeing model exists
at all; and the allocation applies `config/workforce_seed.json` to any employee who does not yet
carry `agent.model_assigned`, which is precisely what a preferred move leaves unwritten, so a
preference applied before it would be undone by the file in the same call. No other call site was
added: the start-up path (`backend/app/main.py`) only registers the Ollama adapter and syncs nothing,
and the daily job at 05:00 syncs nothing either. The consequence worth stating: a studio whose seeing
model entered the catalogue through a sync made *before* this preference existed is moved by its next
sync or its next `scripts/bootstrap.py` run, not by a restart.

## 2026-09-18 — The studio's own allocation file is not the Owner's hand, and the record now says which is which

`prefer_capable_models` protected his choice by refusing to move any employee with an
`agent.model_assigned` event. Measured on this tree, that event is written by his command in Settings
*and* by `apply_llm_allocation`, which applies the studio's own file through that same command — so
the first model sync of any studio wrote it for the Video Editor, on the primary the file names for
her, and the preference was dead from that moment. **Decision: judge the last event that moved her
models rather than the existence of one — no event means the seed hired her; `agent.model_preferred`
means this function moved her last; `agent.model_assigned` is the file's only when her primary,
secondary and tertiary slots resolve to exactly the models the file names for her role, and his
otherwise — and read the two undecidable cases, a role the file does not name and a file that cannot
be read, as his.** The slots are compared through `resolve_model`, not by name, because the file may
spell a model the way the Owner types it and the registry the way the vendor returns it (":cloud",
"-cloud"). One case the record genuinely cannot decide is an Owner who assigns an employee by hand to
exactly the three models his own file already gives her; that is read as the file's, and the
consequence is bounded: the move only ever goes to a model declaring everything the role requires as
well as what it prefers, and it writes `agent.model_preferred`, never his event, so his next
assignment wins and stays won. Closing that corner properly would mean marking the assignment's
origin in the `agent.model_assigned` payload, written in `backend/app/integrations/services.py`,
which is an event-payload change deserving its own decision.

## 2026-09-18 — A role's preference is a second field on the projection, not a longer list of requirements

The Owner's page had `required_capabilities` and nothing else, and `frontend/src/settings.js` filters
the model list by it, so folding `vision` into that list would have hidden every model that cannot
see from the Video Editor's model picker and told him she needs eyes to work at all. **Decision: add
`preferred_capabilities` to `RoleView` as its own field, filled in `list_roles` from the PREFERRED
rows in role order, and leave `required_capabilities` reading REQUIRED exactly as before.** PREFERRED
remains a word no gate reads — `_check_required_capabilities` enforces REQUIRED alone — and the new
field exists so that the page can explain a placement the studio made (`agent.model_preferred`)
without a reader having to open the database to find out why. The field is additive and defaults to
`[]`, so every existing reader keeps its reading.

## 2026-09-18 — A cast is what the film states, not what its prose spells; a guess is recorded and never acted on

The adversary offered two repairs — narrow the given-name reading to the scene's own characters list
and leave the picture to whole canonical names, or record which reading produced a cast so a locked
character can never be refused on an inference — and observed that either is another regex with its
own opposite cost. They stopped being alternatives once the question became what a cast is *for*. A
recorded character does three things: it steers a paid render towards a stored portrait, it is what
the character gate compares the frame with, and it refuses the film when the look is locked and no
reference exists. The first and the third spend the Owner's money or kill his day's only film, so
they must follow evidence, not inference; only the second is free and reversible. **Decision: take
both repairs, each where it belongs.** `_characters_named_in` gained a `given_names` flag rather than
a second regex, so there is one matcher with two readings and they cannot drift apart. `_scene_cast`
returns `(stated, guessed)`: stated is the writer's `characters` list read by given name plus whole
canonical names in the requested picture; guessed is a bare given name in that same prose.
`character_ids_json` carries the stated cast only. The cost of this choice, stated rather than
hidden: a factual scene whose picture writes "Sarah at the studio window" and states nothing is no
longer cast from prose, and the reference the Owner paid for is not used unless the writer lists her.
That is the right cost — the studio may miss a portrait it could have used, and may not buy one for
somebody nobody said was there.

## 2026-09-18 — The guess is kept on the storyboard's creation event, not in a column and not thrown away

Throwing it away would leave the same prose re-read later by a second regex that could disagree with
the first, and would hide from the Owner what the studio read. A column would have needed migration
0046 and would make the guess indistinguishable, downstream, from the film's own word — exactly the
confusion being removed. **Decision: `media.storyboard_created` carries `guessed_cast` ({scene index
as a string: [character id]}) beside `scenes_with_cast` and `cast_note`, the way the same event
already carries why a film has no cast, and `storyboard_cast_record` reads it back.**
`storyboard_cast_note` remains, now a thin reader over that record, so every existing caller is
unchanged. No schema change was needed; the head stays `0045_reconciliation` and 0046 stays free.
The serial's own board (`backend/app/media/serial_storyboard.py`) writes no `guessed_cast`, correctly
— its cast comes from the episode roster and is always stated — which means `storyboard_cast_record`
answers the empty record for serial boards, and a later reader must not take that emptiness for
"nobody is in it".

## 2026-09-18 — A guessed name may inform the picture gate's comparison and may never refuse a film

**Decision: `evaluate_pictures` reads the board's record and asks the seeing employee about guessed
names as well as stated ones — a line in the question, no extra call, still one look per film — and
records the verdict with `status: "OBSERVED"` and `basis: "guessed"`.** It is not added to
`characters_measured`, never enters `character_failures`, and cannot move `character_drift_qc.passed`,
which stays None when only guesses were looked at. A guessed name also pulls no stored portrait into
the question: reference images are attached for stated characters only, so a guess buys nothing and
shows nothing anywhere in the studio. This keeps the standing rule that a check certifies only what
it measured, while the Owner can still read, in the report, what the prose suggested and what the
model made of it.

## 2026-09-18 — The character check says what the record says

`character_drift_qc` printed one sentence, "no scene in this film lists a character", for every
reason there could be. **Decision: report, in order, the guessed-names line when only guesses were
looked at; otherwise the board's own note, which for a film of landscapes is the design sentence and
for a film whose prose named somebody is the guess sentence (`NO_CAST_ONLY_GUESSED`); otherwise "no
character in this film could be compared with the bible" when characters were present but
uncomparable; and only then the old sentence, which now means what it says.** Where the bible holds
no characters at all the check stays NOT_IMPLEMENTED, as before. This closes the line the readiness
phase left open — `picture_qc` reading the storyboard's cast note — and closes it with a record that
distinguishes two facts the single sentence had merged.

## 2026-09-18 — `estimate_film_cost_micros` returns what it could not price, and the figure carries that sentence everywhere the Owner meets it

The figure is produced once and read three times: in the reservation's note, in the question he
answers, and in the Accountant's letter about that question. It used to be complete in none of them
and caveated in one — the note — so the two he actually reads said «estimat 4.20 USD» about a film
whose narration had been counted as nothing. **Decision: the estimate returns `unpriced`, `caveat`
and `complete` beside the figure, and the media stage carries that one sentence to all three
places.** `unpriced_caveat` (`backend/app/economy/budget.py`) is the single wording, «estimare
incompletă: narația nu are preț stocat și este numărată ca zero», and `UNPRICED_CAVEAT_PREFIX` is its
first words so a reader can find it inside a longer line without parsing the sentence.
`narration_priced` is kept unchanged beside them, because the decision log and CURRENT_STATUS
document it. The caveat is raised only where there was something to price: a storyboard with no
voiceover costs nothing for narration whatever the books hold, and a caveat on every film would teach
him to read past the one that matters. What the caveat deliberately does not claim: the stills are
not priced by the estimate at all, so a film's image spend is outside the figure rather than counted
as zero inside it, and naming that in the caveat would be a claim the function cannot measure.

## 2026-09-18 — The caveat travels in the request's `evidence` line, and both the Accountant and the panel read it back by its first words

`ApprovalRequest` and `ApprovalView` have a `cost_usd`, a `cost_label` and an `evidence` line, and no
column for "this figure is not the whole film"; `backend/app/services.py` and
`backend/app/schemas.py` were out of scope for that part, and inventing a column without a migration
would have been worse than the read-back. **Decision: `_cost_caveat` (accountant) and
`approvalCaveat` (`frontend/src/readiness.js`) find the sentence by `UNPRICED_CAVEAT_PREFIX` and
yield "" when it is absent, so nothing ever invents a doubt about a figure that was whole.** Where
the letter clips the evidence to 120 characters the caveat is removed from the clip first, because
that clip cut it mid-sentence («…nu are preț stocat și est») and a half-said caveat is the one thing
worse than none; it is then said once, in full, beside the cost. A column is the right shape: if a
later phase takes migration 0046 or later for it, three readers move onto it together — `_cost_caveat`
in `accountant.py`, `approvalCaveat` in `readiness.js`, and the `evidence=` string the media stage
writes in `backend/app/runbook/stages.py`.

## 2026-09-18 — The letter about what waits is written where the question is born as well as at the day's close

**Decision: call `waiting_approvals_letter` from `_media` immediately after the refusal is recorded,
guarded by `refusal.get("approval_id")` so a MANUAL refusal — which raises no question — writes
nothing, and keep `reconcile_day`'s call.** `_letter_once_a_day`'s idempotency (the business date in
the letter's body, decided behind the write lock) is what makes two callers safe: one letter a day
however many films stop and whichever end of the day notices first. The alternative — moving the
close's call earlier in the runbook — would still have left a run that fails before that stage
silent, and the point of the change is precisely that the Owner must not depend on the day reaching
its last stage to hear that it stopped at its fifth. The call is unguarded by try/except, matching
the existing unguarded `budget_refusal_letter` call four lines below it: if the Accountant's desk
ever raised from inside it the media stage would fail instead of returning SKIPPED. The two were left
consistent rather than one of them guarded; whether both should be guarded belongs to whoever owns
that stage's failure semantics.

## 2026-09-18 — A check's severity decides its word and its colour, and an unknown severity is shown rather than rounded

`frontend/src/main.js` printed every failing check as BLOCKING or DEGRADES, which was true while
those were the only two severities; `serial_channel` and an unlocked `character_references` are
INFORMATIONAL and can fail, so the Owner read red about something that costs him nothing.
**Decision: `checkVerdictWord` and `checkClassName` (`frontend/src/readiness.js`) map the three
severities the preflight emits to BLOCHEAZĂ / DEGRADEAZĂ / INFORMATIV and to `rb-blocking` /
`rb-degrading` / `rb-informational`, and a severity the page has never heard of is printed as it came
with no colour class at all** — rounding a new severity into DEGRADES would be this same defect
again, one severity later. `RUNBOOK_CHECK_LABELS` moves into the same module and gains a Romanian
line for the five checks this phase added and for `autonomy_mode`. It does not gain one for
`youtube_channel_binding`, which `run_preflight` also emits and which showed by its code name before
this work and still does; anyone adding a check to `backend/app/runbook/preflight.py` should add a
line there, since an unlabelled name is shown as its code name and an unknown severity renders
neutral rather than alarming, which is safe but not good. The module is separate from `main.js` for
the reason `governance.js` already gives in its own header: `main.js` touches the document on import
and cannot be loaded by `node --test`, and every one of these is a word the Owner reads.

## 2026-09-18 — `39_DAILY_AUTONOMOUS_RUNBOOK` is edited a second time and re-hashed: the letter now leaves from both ends of the day

§11 of the runbook said "The close writes the Owner one letter about the approval requests still
standing, as its first act". After this closure that sentence is false for the case it was written
for: on a SUPERVISED day the media stage writes the letter at the hour it stops, and the close then
writes nothing, because `_letter_once_a_day` already holds that business date. **Decision: edit §11's
paragraph with a dated sentence saying the letter leaves from the stage that raises the question as
well as from the close, and that the day still writes exactly one — a deliberate specification change
under ADR-FOUNDATION-003, with its `sha256` re-recorded in `DOCUMENTATION_INDEX.json` (`226397b6…` →
`f4d26ea2…`) and this entry as the reason.** §1's preflight paragraph was read again and left alone:
the five checks and their severities are unchanged by this work, and the third severity's *rendering*
is a fact about `frontend/src`, not about the runbook. `31_GOVERNANCE_APPROVAL_POLICY`,
`50_CONTENT_GATE_MATRIX` and `24_VISUAL_CONTINUITY_ASSET_SYSTEM` were read against the cast change
and are untouched by it: none of them describes how a scene's cast is read, and the gates they
specify are unchanged — the character gate still certifies only what it measured, and now says so
about guesses too.

## 2026-09-18 — «Ce are Owner-ul de făcut» is corrected in four lines and rewritten in none

The checklist was re-read against this closure with the rule that only what is now untrue may change.
**Decision: correct step 3 (a merely informational check now reads INFORMATIV in neutral grey instead
of a red "DEGRADES", the five new checks and `autonomy_mode` have names in his language, and
`youtube_channel_binding` still does not — all of it visible only after step 2's build), step 9 (he
has nothing to assign by hand after admitting a seeing model, and needs neither a second seed run nor
a restart: the sync that brings the model moves the Video Editor), step 10 (the refusal by a locked
character follows a cast the film *states*, never a given name its prose merely spelled) and step 12
(the letter leaves in the minute the question is born, and a figure the studio could not complete
says so beside itself) — and change nothing else, drop no line and keep the order.** The old sentence
is left standing in each case with the correction dated after it, which is how this document has
recorded corrections since 2026-09-09: a reader who remembers the old promise finds it, and finds
what replaced it.

## 2026-09-18 — The closure's figures are attributed, and two defects in the tree are reported rather than fixed

No whole-suite run was made by any of the three parts of this closure, and the brief for the
documents forbids running one. **Decision: every figure is written with the part that measured it
beside it — 5 (new) + 60 and its neighbours for the seeing-employee part, 70 across three owned files
with 72 and 91 across their neighbours for the cast part, 36 + 34 + 20 + 17 with 234 in all and
`node --test` 8 inside 110 for the letter-and-panel part, `check_docs.py` and
`tests/test_documentation.py` for this one — and `PROJECT_STATE.json` keeps 1194 passed / 1 skipped
as what it is: the Phase D/G closure verifier's measurement of 2026-09-18, now older than the tree
twice over.** One defect lives in the tree and is named here rather than repaired, because it
belongs to a file no part of this closure owns: `uv run mypy backend/app/media/picture_qc.py` reports
one `union-attr` error at line 285 (`board.id`, where the narrowing that makes it safe is `scenes`
being non-empty — a type-narrowing gap, not a runtime fault). A second was recorded as open here and
closed in the tree before these documents were finished, which is itself worth the line:
`tests/test_phase_dg_closure_adversary.py::test_only_the_owners_command_module_reaches_an_approval_row`
had begun to fail because its whole-tree scan for the string "ApprovalRequest" found a docstring line
the Accountant gained in this phase — the invariant was written in prose that its own test could not
distinguish from code. **The scan now walks the parsed module and counts a class definition, a name,
an attribute or an import rather than characters**, so the invariant stays unbypassable while
remaining explicable; measured on this tree afterwards, that file is 12 passed. Reporting both is the
point: a document that recorded this closure as clean would be the first thing these documents exist
to prevent.


## 2026-09-18 — A fallback reconnect cannot supersede a recovered stream

Epic's SDK can reconnect before the application fallback timer. Cancel that timer on status transitions and check the offline state inside its callback. Do not rebuild traffic to treat stream loss. A single-viewer browser test verifies recovery without restarting the user's Unreal runtime; the active Owner page must load the new bundle before evaluating the fix.


## 2026-09-18 — A failed stage blocks only the stages that take their input from it

A rehearsal on a copy of the Owner's studio ran one scheduled day with every vendor faked and every
outside connection refused. Performance intake failed on a refused statistics token, and the runbook
then BLOCKED the nine stages after it, because any failure blocked everything later: the day had
nothing researched, written or filmed over a read that no film needs. **Decision: a runbook decision,
recorded in `39_DAILY_AUTONOMOUS_RUNBOOK` §*Abort behavior* and implemented as `STAGE_PREREQUISITES`
beside `STAGES` in `backend/app/runbook/services.py`. A stage whose every listed prerequisite FAILED
or was BLOCKED is BLOCKED itself, with the prerequisite and the root fault named in Romanian; every
other stage runs.** Each edge was read from what the runner in `app.runbook.stages` actually reads,
not from the order of `STAGES`:
- performance_intake needs nothing. It reads the channel slots and their PUBLISHED rows, nothing of
  today.
- idea_generation needs nothing. It reads the topic pool and the cohorts of every snapshot ever
  stored (`research.agent._signals`, "empty when unknown").
- research_and_verification needs nothing. It reads the whole backlog: the pool, every unextracted
  source and every UNVERIFIED claim, whichever day wrote them.
- selection needs research_and_verification, because it chooses only among topics with SUPPORTED
  claims, which verification writes. The day does not choose a subject past an unexamined fault in
  the step that turns a page into a claim a film may cite.
- script_and_storyboard needs selection. It writes for the SELECTED topic.
- serial_queue needs nothing. It reads the previous day's log, which is closed on the preflight line
  and is not a stage.
- media needs script_and_storyboard or serial_queue. Each gives an approved storyboard, and either
  one is a film, so media is blocked only when both are lost.
- edit_and_qc needs media, because it measures the files media rendered. publish needs edit_and_qc,
  because it uploads what quality control passed.
- post_run and daily_log need nothing. They are the report and the record of whatever happened.

A SKIPPED prerequisite blocks nothing, as before. The Owner's stop outranks the table and still blocks
every stage after it, and a BLOCKED preflight still blocks all stages. Rejected: keeping "stop at the
first failure" and making performance intake unable to fail. That would have fixed the one stage the
rehearsal met and left the same cliff behind every other stage no film depends on.

## 2026-09-18 — Safe mode is for a P0, as the playbook defines one

`21_FAILURE_RECOVERY_PLAYBOOK` names four P0s: a risk of duplicate publish, uncontrolled spend, a
secret leak, and corrupted audit state. `36_RELIABILITY_SLO_RUNBOOK` gives safe mode and STOP
AUTONOMY to P0 alone. It files "production blocked, provider unavailable" as P1: pause what is
affected and notify. The runbook opened safe mode and set the autonomy stop on a HARD fault in any
stage. The rehearsal's audit measured that `classify_fault` reads an HTTP 4xx from Google
(`invalid_grant`, or a 403 from the Analytics API) as HARD, so one expired read-only token would have
halted the studio until the Owner cleared it. **Decision: `SAFE_MODE_STAGES = (media, publish,
daily_log)`. A HARD fault opens safe mode only in media, where the studio no longer knows what it
spent; in publish, where it no longer knows what it uploaded; and in daily_log, the audit record.
`_doubts_the_record` also opens it for a non-Operational `DatabaseError` or `IntegrityError` in any
stage. A HARD fault anywhere else, a refused token or a bug in selection, costs that stage and its
dependants and one letter from the Director.** A transient fault still never opens safe mode (Phase A).
The classification itself is unchanged: a 4xx is still HARD, and a HARD fault is still not retried in
place.

## 2026-09-18 — The same-day re-attempt follows only a transient fault that cost a film

A re-attempt re-runs the whole day. With stages that no longer stop the day, re-attempting after a
failed report would make selection choose a new subject and the media stage buy a second film, only
to recover the report. **Decision: `retryable_outcome(..., production_lost=)` is True only in two
cases: a BLOCKED preflight, or a FAILED run whose failures behind a lost `PRODUCTION_STAGES` stage
(selection, script_and_storyboard, serial_queue, media, edit_and_qc, publish) were all TRANSIENT. A
day where only a non-production stage failed is PARTIAL, not FAILED, unless the failure was in
daily_log, which stays FAILED because the day's own record failed.** PARTIAL is already one of the
worker's `DAY_DONE_STATES`, so neither the clock nor a stray retry runs that day again. The run keeps
the stage's fault class. The Director's letter then says the stage failed and that the day's films did
not depend on it, not that "the day stopped". `production_lost` defaults to True, the old reading, for
a caller that cannot tell.

## 2026-09-18 — A statistics read that cannot be made is «fără date», never the stage's failure

The rehearsal's defect 1 began in the analytics adapter. `_refresh_access_token` called `urlopen`
outside the `try` its report had. `_report` turned an `HTTPError` into a bare `RuntimeError`.
`measure_channel_publications` caught only `MetricsUnavailable`. **Decision: `YouTubeAnalyticsProvider`
raises `MetricsUnavailable` in these cases. On the token refresh and on the report: a `URLError`,
`OSError`, `HTTPException`, unreadable JSON or a missing access token. On the token refresh only: a
4xx (`auth_refused`, keeping only Google's short error word, such as `invalid_grant`). On the report:
a 401 or 403 (`auth_refused`, meaning the scope is missing or was withdrawn). The exception carries
`during`, `auth_refused`, `error_class`, `http_status` and `oauth_error`, and never a token or a
secret. After an account-level refusal, `measure_channel_publications` stops asking Google and records
every remaining publication with the same Romanian reason. That reason names the account and the
slot and says to press Reconectează. The refusal is also written once to the ledger
(`youtube.token_refresh_failed`, or `youtube.analytics_refused` when the report refused a good token)
for the preflight to read.** The class moved into the adapter module so that the provider layer does
not import the domain service; `app.analytics.services.MetricsUnavailable` is the same object. The
adapter still retries a 400 once without impressions, as before. Consequence, recorded and not
changed: the manual ingest route (`analytics/router.py`) now answers 409 with the reason instead of
502 for a transport or authentication failure.

## 2026-09-18 — The run's headline counts what each stage produced

Run 96b08fd8 on the rehearsal copy read COMPLETED 12/12. In that run the ideas were refused on
schema, research verified nothing, the Director's review decided nothing and the Accountant's line
was SKIPPED. **Decision: every stage record carries `produced`, counted by `PRODUCED_FROM` from the
artefacts its runner already returns: measured; proposed; pages_fetched + sources_read +
claims_verified; topic_id; scripts + storyboards; written + storyboard_id; assets; passed + failed;
published; applied. Nothing is inferred from the status. `run_summary` writes the Romanian headline,
for example «10 din 10 etape au rulat până la capăt; 7 au produs ceva. Fără rezultat: «…». Filme
publicate: 2.», or «Ziua nu a produs nimic.» `execute_daily_run` and `list_runs` return it with
`stages_productive`, and it is stored in `runbook.daily_run_finished`.** The preflight and the day's
log are not counted, because "produced something" is about the ten stages of work between them. No
column was needed: the counts live in `stages_json`, and a run stored before this is counted from the
same artefacts when it is read.

## 2026-09-18 — A motion shot is charged only when it was bought

The rehearsal's defect 2: the books wrote four ESTIMATED Runway rows, 1.44 USD, for shots the vendor
could not be reached for, and settled both films' holds against them. **Decision: one predicate,
`motion_was_bought(motion) = bytes or paid_but_lost` (`backend/app/economy/accountant.py`), decides
whether a scene's motion seconds and credits are charged. `record_render_costs` (a finished render)
and `record_failed_render_cost` (a lost one) share it, and a refused shot no longer teaches a
measured price.** The predicate was checked against every place `media.assembler` writes a scene's
`motion` entry:
- A shot that came home carries `bytes`, plus `estimated_credits` when the vendor named them.
- A shot generated but not brought home carries `refused`, `estimated_credits` and `paid_but_lost`.
- A shot the vendor refused, or could not be reached for, carries `refused` only.
- A shot the price gate refused carries `refused`, `quoted_credits`, `quoted_usd` and sometimes
  `price_was_stale`.
- A scene never asked for has no motion entry.

A quote is not a purchase, so `quoted_credits` never prices anything. The still is charged in every
shape. Rejected: "charge whatever lacks `refused`". On today's shapes it gives the same answer, but it
would charge a record that shows no evidence of a purchase, and the books charge what was bought and
nothing else.

## 2026-09-18 — A film whose every shot was refused settles its hold against what was bought

**Decision: the reservation is still SETTLED with `settled_reference` `render:<job>`. Its
`usd_micros` keeps the sum it held (1.30472 USD on the rehearsal copy) as history, and stops counting
against the period, as every settled hold does. The day's spend is then only the books: the stills and
narration that were priced, and no motion row.** On the rehearsal copy that would have been 0 USD for
both films, because the test picture and voice adapters carry no integration id. Asserted in
`tests/test_phase11_economy.py`. Releasing the hold instead was not taken, because a film was made
and its stills and voice were bought.

## 2026-09-18 — Documented prices per model family, and any price the Owner typed outranks every documented one

The one DOCUMENTED ElevenLabs figure ('*', 0.22 USD per 1k characters, the Creator plan) priced the
Owner's `eleven_flash_v2` at the multilingual rate. The row's own note cites the price list's line
that Flash and Turbo bill half. **Decision: `integrations.catalog.DOCUMENTED_PRICES` gains
`eleven_flash_*` and `eleven_turbo_*` at 0.11 USD per 1k characters. That is the cited Creator figure
(22 USD per 100,000 credits) at the half credit per character the same list states, and no other
number was introduced. A resource ending in `*` is a family prefix, which the Owner can also type.
`price_row` ranks provenance first, so any non-DOCUMENTED row beats every DOCUMENTED one, then
specificity: the exact id, then the longest family, then '*'. `seed_documented_prices` skips a
documented row when the Owner already has an active '*' price for that unit, because that row could
never be read.** Provenance comes first because a documented family row is more specific than his '*'
and would otherwise overrule the plan he typed. The live studio receives the two rows at its next
start, when `start.py` runs bootstrap. That is data seeding, not a migration. Not used: the vendor's
own `model_rates` / `token_cost_factor`, which discovery stores when ElevenLabs sends them. Whether his
live catalogue holds them can be read only from `data/studio.db`, and a seed cannot depend on that.
Left open: the film's hold still takes the dearest active voice price (`estimate_film_cost_micros`),
so it holds Flash narration at about twice its cost.

## 2026-09-18 — DNS is refused like a socket, and asyncio's `sock_connect` as well

The suite's autouse guard refused only `socket.connect` and `connect_ex`. A public name was therefore
resolved before the refusal came. On Windows the proactor event loop connects through ConnectEx, so
an async client went round the guard entirely: a new test made a real connection attempt to 192.0.2.1,
which ended in WinError 121. **Decision: `no_network` in `tests/conftest.py` also refuses
`getaddrinfo`, `gethostbyname` and `gethostbyname_ex` for anything but localhost or a loopback literal,
and asyncio's proactor and selector `sock_connect`. It stays loud: it raises `AssertionError`, which no
vendor client treats as a network fault. It records every refusal, with the studio frames that made
it, on the fixture it returns.** A test that fakes `getaddrinfo` itself still can, because its patch
applies after the guard's. The fix for a test that relied on real DNS is to fake that boundary, never
to loosen the guard.

## 2026-09-18 — The whole-day test and the rehearsal share one list of fakes

The rehearsal kept private copies of the fakes and of the guard, and that is how a boundary went
missing. **Decision: one list, `VENDOR_FAKES`, and one installer, `install_vendor_fakes`
(`tests/test_autonomous_day_end_to_end.py`), whose dictionary must name exactly the list. It holds
eight fakes: image, voice, render plan, the motion chooser, the publisher, the analytics adapter, the
vendor balance reads and the search engine. Each is patched where the day reads it:
`selected_youtube` and `analytics_provider_for_channel` on `app.runbook.stages`, which imports them at
the top of the module, and the others on the module that defines them, because the stage imports those
inside the function.** A future paid boundary on the day's path goes into both, on the module where the
day reads it.

## 2026-09-18 — The motion chooser's fake keeps the decision and replaces only the vendor

**Decision: the fake reads the selected video connection. It calls the studio's own `choose_model`
with the real TEST task, tier, ceilings and exclusions, and returns an adapter that makes a local
test-pattern clip. That adapter names its credits as the catalogue's per-second price in the
connection's credits, the way Runway states `estimatedCost`.** A day with a video connection is thus
held to the Owner's TEST terms and his books, and nothing is bought. A studio with no video connection
gets the answer the real chooser gives. Measured with a Runway-shaped connection, as on his copy:
three shots asked in total, two at 0.204 USD each for film 1 and one at 0.372 USD for film 2, whose
second shot did not fit the 0.60 USD film ceiling. The books recorded exactly three motion rows, and the
guard recorded no refusal.

## 2026-09-18 — A source scan checks the list of fakes

A hand-written list of fakes certifies only the paths someone remembered. **Decision:
`tests/test_no_paid_path_escapes.py` walks a call graph from `execute_daily_run` and
`build_stage_runners` over `backend/app`. It follows bare names through each module's imports,
`module.attr` through the named module, and `obj.method` to every method of that name; the last rule
over-approximates on purpose. It fails on any reachable site that constructs or calls a paid adapter
with no fake in front of it. A fake counts only where the patch is really seen. A paid module is every
`app/providers` module not on an explicit free list, so a new vendor module is paid until someone
reviews it.** Against the list as it stood before 2026-09-18 it named exactly five sites: the four
unfaked boundaries the rehearsal met, and `verified_search_provider` → `SearchProvider`, which it
never met. A pass certifies only that no statically visible paid site is reachable from those two
roots without a fake. The scan cannot see `getattr` by string, `importlib` or code built at run time,
and the network guard is the backstop for those. The other scheduled entry points (the watchdog, the
Director's loop, the model review, the catalogue refresh) and the API routes are not roots yet.

## 2026-09-18 — The rehearsal fakes the YouTube Analytics adapter as well

**Decision: the rehearsal's analytics fake runs the slot's real binding lookup first, and every video
then comes back `MetricsUnavailable`, so no number is invented.** On the Owner's copy the rehearsal
therefore gets past performance intake and reaches media, quality control and publish. The cost is
stated. The rehearsal no longer meets the real Google token refresh, so defect 1's fix is proven by
the failure-and-analytics part's own tests with faked transports (`tests/test_phase7_analytics.py`,
`tests/test_day_survives_a_stage.py`). Only a free real read, Verify or Reconnect in Settings, proves
the Owner's tokens.

## 2026-09-18 — A refusal of the YouTube token is BLOCKING for the day, not only for publishing

**Decision: `youtube_upload_access` is BLOCKING. It fails when Google's recorded scopes lack
`youtube.upload`, or when a refusal of the slot's token (`youtube.token_refresh_failed` with
`auth_refused`) still stands. A later reconnect (`connected_at`) or a successful verification
(`last_checked_at`) answers the refusal.** The upload refreshes the same refresh token the statistics
read was refused. A day that films, spends and then cannot upload has spent money on nothing, even in
TEST, where the upload is private. A refusal is only what Google answered: the analytics stage's
`auth_refused` flag is taken as written, and a failure with no answer from Google (the network) is
kept apart, because it says nothing about the token. A refused statistics report
(`youtube.analytics_refused`: the token was fine but the scope was missing) only degrades the day
(`youtube_statistics_access`, DEGRADING), because the films do not depend on statistics. Recorded as
open: the uploader writes no such event. An upload-side refusal therefore reaches this check only
after the statistics read meets the same dead token, and the first day with a dead token still films
and pays before the upload fails.

## 2026-09-18 — The seven-day Testing-mode expiry is a caveat, never a verdict

The studio cannot see whether the Owner's Google OAuth app is in Testing or In production. **Decision:
both YouTube checks give each grant's age and what a seven-day Testing-mode token life would mean, and
fail only on a refusal Google actually gave. A connection whose scopes were never recorded is
«necunoscute», not refused.** A check certifies only what it measured. His two grants are seven days
old on the rehearsal copy, and the line says «tokenul poate fi deja expirat» and no more.

## 2026-09-18 — The daily-budget line asks the media stage's own estimate

**Decision: `daily_budget_films` calls `estimate_film_cost_micros` with an empty storyboard, so the
motion part is exactly the hold the media stage will take: 12 USD in PRODUCTION, and 2 × 0.60 USD in
TEST. The narration is named as extra rather than guessed. The factual short is held first and the
serial second (`_media`), so the serial episode is the film the line names as refused.** In TEST, the
PRODUCTION answer is INFORMATIONAL: switching is his decision, and today's TEST day loses nothing. The
line names the two numbers he can change: the DAILY budget, to at least 24 USD for two films, and the
per-film motion ceiling, to at most 7.5 USD in 15. The audit's own figure is about 2.9 USD for the
first film's cost above which the second is refused, with the narration's roughly 0.1 USD inside it.
The line says 3 USD, because it names the narration rather than pricing it.

## 2026-09-18 — The preflight summary names the first line that would stop the day or lose a film

The run records the preflight's summary as its stop reason. On the rehearsal copy «Studioul poate
rula» stood above a record that foresaw the day stopping at stage 2. **Decision: the summary names the
first BLOCKING failure, or else the first failure in `EMPTIES_THE_DAY` (today only
`daily_budget_films`). The result carries its name as `first_stop`.** A statistics failure is
deliberately not in the set: performance intake now records «fără date» instead of stopping the day.
If that change is ever reverted, `youtube_statistics_access` must join the set.

## 2026-09-18 — `39_DAILY_AUTONOMOUS_RUNBOOK` is edited a third time and re-hashed: which stage needs which

The runbook's *Abort behavior* listed what a fault leads to and not what it costs. Its §4 said a failed
retest "costs this stage and never the studio, by the Phase A fault rule", but under that rule a
failed stage blocked every stage after it. **Decision: four changes, as a deliberate
specification change under ADR-FOUNDATION-003, with the `sha256` re-recorded in
`DOCUMENTATION_INDEX.json` (`f4d26ea2…` → `227e7604…`) and this entry as the reason:**
- *Abort behavior* gains a dated section. It gives the stage dependency table with the reason for each
  edge, and says that a failed stage blocks only its dependants, that SAFE_MODE follows the
  playbook's P0 and nothing else, that the same-day re-attempt follows only a transient fault that
  cost the films, that a day whose films went through is PARTIAL, and that the headline counts what
  each stage produced.
- §1 gains a dated paragraph for the three new checks and the summary's first stop.
- §2 says what "if available" means.
- §4's sentence keeps standing, with its dated correction.

The original four-line abort list is kept as it was: it states the rule, and the new section states
what the rule costs.

## 2026-09-18 — The documents correct every sentence that promised a failed stage costs only itself, and the Owner's list grows without renumbering

**Decision: every sentence that said a failed stage costs only itself, or that the day survives a
fault, is corrected where it stands with a dated marker, and the old wording is left in place. It was
untrue until this change. The corrected places are:**
- `39_DAILY_AUTONOMOUS_RUNBOOK` §4.
- The Phase A retest entry of this log.
- Phase A's fault-class and re-attempt paragraphs and «Running on its own» in `CURRENT_STATUS.md`.
- Phase A's fault-class tick in the roadmap.

Three entries of this log that described the old cliff as the rule are marked superseded in part:
D-P10-001's decision 5 (2026-09-10), the stage-wiring paragraph under "The clock is the Owner's to
start" (2026-09-11), and "A mode refusal is SKIPPED, not BLOCKED". The changelog is left as it was, because each entry there records what a change did on
its own date. What the rehearsal found that only the Owner can do is added to «Ce are Owner-ul de
făcut» in the step it belongs to, each addition marked «Adăugat 2026-09-18 după repetiție»:
- step 1: the migration is done, by his own start;
- step 3: the three new checks;
- step 5: the unpriced Ollama models and the Flash price;
- step 8: the two YouTube connections to verify or reconnect granting statistics access, the Google
  OAuth app out of Testing, and that a reconnect grants statistics only since `SCOPES` asks for them
  (added by another part while these documents were being written);
- step 10: the 40 images and their cost;
- step 12: the mode written by 0043, and the 29 scripts of 2026-09-12 waiting for him;
- step 13: the environment written by 0031, and in PRODUCTION one film in 15 USD, not two;
- step 14: the audit's verdict.

Renumbering was rejected: the steps are cited by number in `PROJECT_STATE.json`, in the roadmap, in
this log and in the rehearsal's own report. One measured correction rides along. `youtube_channel_binding`
has had a label, «Sloturi de canal legate de YouTube», since `frontend/src/readiness.js` was created.
Three sentences that said it had none are corrected with the same dated marker.

## 2026-09-18 — The rehearsal's figures are attributed, and the newest whole-suite run is older than the fixes

**Decision: every figure is written with the part that measured it.**
- The rehearsal: 1 passed on a fresh copy, with the day stopping at stage 2.
- The audit: 1 passed on its own fresh copy, and the whole suite at 1265 passed and 2 skipped on the
  tree as it stood at the rehearsal.
- The failure-and-analytics part: 18, 14, 124, and 202 with 1 skipped.
- The books part: 13, 22 and 158.
- The fakes part: 14 with 1 skipped, 340 with 1 skipped, and the rehearsal 1 passed on the
  scratchpad copy.
- The preflight part: 30, 130, and `node --test` 8.
- The documentation part: `check_docs.py` and `tests/test_documentation.py`.

`PROJECT_STATE.json` records the audit's 1265 / 2 as what it is, the newest whole-suite measurement,
taken before any of the fixes. No part made a whole-suite run, and the verifier's figure lands after
these documents.

## 2026-09-19 — A computed check asks whether the narration says what its claims say

The factual gate passed the rehearsal's telescope script on the Nepal topic. The gate checks that
the cited claims exist and are SUPPORTED, not that the narration says them. **Decision: a computed
grounding check (`app.factual.grounding`) runs in four places, all but the last before any money is
spent:**
- the story review, as the blocking check `narration_is_grounded`;
- `_director_approves`;
- `story_gate`, before the shot descriptions and the render;
- the Director's last look at the film (`gather_facts`).

Every one only adds refusals. None changes the factual gate, the Director's verdict, the publishing
points or the other hard gates. A factual script it cannot measure (no claims, a missing claim, no
narration) is NOT_MEASURED and does not pass. Episodes of the office serial are not measured. They
are recognised by `story_json.kind == office_serial_episode` or by a topic with status SERIAL, the
same marks `is_serial_film` reads.

## 2026-09-19 — Words, numbers and names are measured, not meaning, and two of a claim's terms say it

**Decision: the check compares words, numbers and names, and a claim counts as said when two of its
terms are in the narration.**
- **Words** match on their stem. Diacritics are folded, and two words are the same when they share
  their first five letters, or when the shorter is a prefix of the longer with at most two letters
  left over. That covers paraphrase, word endings and the cognates between English and Romanian.
- **Numbers** are normalised: «7,000», «7.000» and «7 000» are all 7000, and a decimal matches its
  rounded whole («about 83 billion» matches 83.3).
- **Number words** are read in both languages, including «twenty-six» and «decade».

Numbers and names are what survive translation from a source's language into the audience language
(`content_language`, English by the Owner's rule).

Two alternatives were rejected:
- **A stricter rule** that required each claim's own distinctive words. It refused the Owner's
  approved LHC film, which says «doesn't glow, doesn't absorb light» for «does not interact with
  the electromagnetic force». The only words shared with that claim are «dark» and «matter».
- **A prefix slack of three letters.** It was lowered to two after «bill» matched «billion».

The known limit is stated in the module. A narration that repeats two of a claim's words while
contradicting it passes. That judgement stays with the Director, who now receives the measurement.

## 2026-09-19 — A grounding failure asks for a rewrite, and the count of foreign facts reads numbers and names

**Decision: a grounding failure sends the script back for a rewrite (REVISE), not closed
(REJECT).** Rewriting text costs nothing, and the note tells the writer which claim went unsaid and
which of its terms are missing. It becomes REJECT only at the last exchange, as the budget already
does.

**Decision: the count of facts from elsewhere uses numbers and names, not all content words.** The
whole-day test's single-claim infrared film is legitimate, yet about three quarters of its content
words appear in no claim. Its numbers and names all come from its claim and its topic. On the
scripts of 2026-09-12, the highest share of numbers and names from nowhere was 0.40, against a
limit of 0.5. The rehearsal's script measured 1.0.

## 2026-09-19 — A fixture that broke the writer's brief is corrected, not the check

The fixture narration of `a_film` in `tests/test_editorial.py` states a year, a telescope and a
distance that its one claim did not carry. The writer's brief forbids exactly that («Nu adăuga
niciun fapt, cifră, dată, nume ... care nu apare în ele»), so refusing that film is the check
working. **Decision: the claim text of the fixture changes, not the check.** The claim now carries
what the narration says.

## 2026-09-19 — The panel never reads a missing count as zero

**Decision: a count the page does not have is never read as zero.**
- A run without `stages_productive` is not marked empty.
- A stage record without a `produced` key reads «nenumărat» and is not called idle.
- Only an explicit `produced: null`, which is the backend saying «not counted», shows nothing.

The reason: `list_runs` recomputes the run's summary for older records, but returns their stage
records as stored. Those older stages have no `produced` field, and calling them idle would claim
something the page never measured.

## 2026-09-19 — The panel shows the backend's sentences as written, and adds only labels

**Decision: the run's sentence and the check messages appear exactly as the backend wrote them.**
The panel adds only short Romanian labels of its own:
- «a produs N», «nu a produs nimic» and «nenumărat»;
- «Primul punct blocant»;
- «Ziua nu ajunge întreagă», which follows the backend's own preflight wording;
- «N etape au produs ceva», which follows `run_summary`.

The ledger's head line mixes these Romanian words into its existing English phrasing. The rest of
`ledger.js` was not translated, because that was outside the task. It is display only: nothing here
changes a gate, a verdict or a button's permission, and the Start button still follows the
preflight status.

## 2026-09-19 — `50_CONTENT_GATE_MATRIX` names the narration grounding gate, and is re-hashed

The matrix listed the claim factual verification row, and nothing in it said that this row
certifies the claims and not the words of the film. It also had no row for the gate that now reads
the words. Its *Gate behavior* section says a check that could not run carries `passed: null` and
adds no failure. The new check's NOT_MEASURED carries `passed: false` and refuses. Left
unexplained, that would read as the code breaking the matrix's rule.

**Decision: a deliberate specification change under ADR-FOUNDATION-003.**
- The gate table gains the row *Narration grounding (Channel A)*: No before the script, Script
  before media, Yes before publish.
- A new dated section, *Narration grounding (built 2026-09-19)*, states:
  - what the claim gate measures and what it never read;
  - the three counts;
  - the four places the check refuses, and that it only adds refusals;
  - its limit: words and not meaning;
  - why its NOT_MEASURED is not the stand-down of the rule above. The check needs nothing but the
    script and its rows, so it cannot measure only when the script lacks what every factual script
    must carry. The defect is then the script's, and the claim gate refuses two of those three
    cases already.
- The document's `sha256` in `DOCUMENTATION_INDEX.json` is re-recorded in the same change
  (`a436dab0…` → `6750c35d…`), with this entry as the reason.

Nothing was removed. Every row and rule the matrix carried still stands.

Two other documents were read and deliberately left unedited, with their hashes unchanged:
- `39_DAILY_AUTONOMOUS_RUNBOOK` §6 says «Run claim/visual consistency checks». That is now more
  true than before, not less.
- `08_VIDEO_PIPELINE`'s «Fact-check not only narration» is unchanged in meaning.

## 2026-09-19 — The documents place both parts' work, and correct two stale sentences where they stand

**Decision: the work goes into the newest section about the rehearsal, as a dated subsection.** It
is not a new top-level section, because both parts close findings of that rehearsal. The findings
stay as they were found. Two sentences of that section's «Not finished» paragraph became untrue,
and each is corrected in place with a dated marker, the old wording left:
- the panel does not read the run's new fields;
- only a real day could show whether reviewers catch narration its claims do not support.

«Ce are Owner-ul de făcut» grows by two dated lines without renumbering:
- **step 2:** what the panel now shows, and that it is seen only after the build;
- **step 12:** the 4 of the 29 waiting scripts that the check refuses, each with the claim it
  leaves unsaid.

Every figure is written with the part that measured it:
- **The grounding part:** 15, 16, and 352 passed with 1 skipped.
- **The panel part:** red first at 0 and 1, then 9, 124, and tsc clean.
- **This documentation part:** `check_docs.py` passed, and `tests/test_documentation.py` 3 passed.

The audit's 1265 passed, 2 skipped is still recorded as the newest whole-suite figure, and it is
older than every fix. One defect is reported rather than fixed, because code is outside this part:
the module docstring of `backend/app/factual/grounding.py` says a prefix may have «at most three
letters to spare», while `SUFFIX_SLACK` is 2, with its own comment saying why.

## 2026-09-19 — Spelled-out numbers are numbers, and fixtures that break the brief are corrected, not the check

The verify part tried to break the grounding check from both sides. A faithful narration that
spelled its numbers out, as a voiceover is written, was refused: «six hundred million dollars»
read as a 6 and a 100 that no claim carries. **Decision: the check reads a whole spelled-out
number in English and Romanian, and ranks from third to tenth on both sides.** «First» and
«second» are left out, because they are ordinary words far more often than ranks. The
recalibration on the copied scripts of 2026-09-12 gives the same result as before.

The whole suite showed two more fixtures the check refuses: a factual film narrating the serial's
dialogue under a Webb claim, and a film citing a claim that does not exist. **Decision: both
fixtures now narrate what their claims say.** Each broke the writer's brief, as the editorial
fixture did; weakening the check to keep them would let a real script do the same.

Not adopted, measured on the real scripts: requiring two matched terms that are not topic terms,
or one of the claim's own numbers or names. Both refuse the Owner's approved LHC and ATLAS films.
What a word count cannot hear (negation, generic words standing in for a claim) stays the
Director's, and she receives the measurement.

## 2026-09-19 — A whole-suite run is a machine-wide load, and it is read with the machine's state

The committing session's whole run gave 1518 passed and 14 failed or errored. All 14 were the
machine out of commit memory (Windows logged it three times in fifteen minutes), and their seven
files passed when run again, 169 of 169. The same shortage stopped the Owner's live stream at
14:23. **Decision: a failure is recorded with the memory state it happened in, and re-run before it
is called a defect or called flaky.** A whole-suite run is not started while free commit is
below what the live stream needs to restart (about 14 GB), because on this machine the test run,
the Owner's other programs and the stream share one commit limit.

## 2026-09-22/23 — The interface goes dark, because the render is the product

The Owner asked for an interface «ca jocurile moderne din 2026 AAA». **Decision: the page becomes
one continuous dark ground and the 3D headquarters is the only object on it with real weight.**
Three directions were built on the real code and photographed before the choice: A (cinematic
dark), B (broadcast charcoal), C (the best possible light room). A judge chose A on three measured
grounds: it is the only one that changed the substance of the screen rather than its skin; dense
data became readable (the daily run became a dashboard, the ledger a register); and in C's own
words a light page puts a ~17:1 luminance step at the glass, so the night render reads as a hole
cut in a lightbox. C's page architecture, scene console, chip scale, figure treatment and section
rule and B's dialog rail, row rhythm and storyboard header were grafted by name.

The previous identity (warm paper, deep forest, muted gold) is not discarded: the forest band and
the rationed gold survive as the chrome and the one accent. Gold is spent only on what is live or
what waits for the Owner.

## 2026-09-23 — A routine that ran seventeen times is one row, and it is proven so

**Decision: consecutive ledger entries that are identical in kind, route and text fold into one
row carrying ×N and the span they cover.** Nothing is reworded and nothing is dropped;
correspondence never folds, because every letter is its own thread. Measured before: the column
opened with eleven repetitions of «routine job started / watchdog» and the studio's actual
correspondence was below the fold.

This is the one place the interface changes *what* is on screen rather than how it looks, so it is
the one place that must be proven: `frontend/tests/ledger_fold.test.js` (7 cases) shows that single
rows plus the sum of every count equals the number of events, that a run interrupted by a letter is
not welded across it, that three identical letters stay three rows, and that a filter hides rows
rather than folding them into another row's count.

## 2026-09-23 — The interface is judged from photographs of the real page, not from opinions

**Decision: no look is accepted until it has been photographed on the real markup with the
Owner's own data.** The studio was not running, so the harness under the session's scratchpad
copies `data/studio.db`, blanks every encrypted column in the copy, serves the built page and
answers every request from 254 captured answers behind a loopback-only guard, then photographs
eleven views at any width. Every claim in this work — no overflow at four widths, 655 contrast
pairs, focus on every stop, zero console errors — is a measurement taken that way. What could not
be measured is named: the scrollbar (this browser hides it) and the interface over the live Unreal
stream (never photographed).

## 2026-09-23 — The interface speaks Romanian

**Decision, taken by the Owner's own convention: every user-facing string the frontend owns is
Romanian, in the studio's own voice.** The studio already spoke Romanian everywhere it computed
a sentence — the preflight's reasons, the day's summary, the approvals, the refusals — while the
interface's older static text was still English, so one row read «Automatizare» above «Fact
research» and the treasury labelled six tiles in two languages. A stranger does not read that as
a bilingual product; they read it as a product where nobody decided.

What this decision does *not* cover, and why: a value is not a label. The brand, the employees'
names and role names as the data gives them, units and codes (`VR$`, `fps`, `9:16`, `QC`, `API`,
`OAuth`), enum values, Google's own field names, and every sentence that arrives from the backend
stay exactly as they are — the backend's sentences are already Romanian and are not the
interface's to reword. Loanwords Romanian technical speech actually uses are kept (`live`,
`storyboard`, `prompt`, `token`, `slot`, `analytics`); the pairs, the ones kept and the places the
translator hesitated are written down in the session's glossary and were followed rather than
improvised, including the measurement that decided «Discuții» over the shorter «Vorbe» and
«Reîncarcă» over «Reîmprospătează».

Two consequences worth naming. The research form's three unlabelled inputs and its fourth box
holding a bare `general` now carry visible labels taken from what each control already said, using
the field-label pair the stylesheet already had — the decision to translate forced the decision to
label. And the publishing gate card no longer quotes an internal architecture filename at the
Owner: it says which checks do not exist yet, in Romanian, naming no file he does not open.

## 2026-09-24 — The page amazes a first-time visitor, wave 1

2026-09-24. The canvas fallback's 'reference_dusk' light mode was removed, not merely switched off. The Owner ruled on 2026-09-18/19 that the sky follows the real Bucharest sun and weather and is never 'always dusk', so the page keeps no code path that could hold it at dusk again. Clouds are weather, so they are drawn only as much as the real cover the backend reports, and not at all when the weather is unavailable. «Acum» uses the backend's worker task lease (3600 s) as its quiet threshold rather than a new constant, so the page never says 'now' for longer than the studio itself would consider a silent task alive.

2026-09-24:
- The title screen may move only for three reasons: the pointer (parallax), the real sun (the light, once a minute), and an accepted key (the entry). There is no load-time reveal, because a reveal on page load would be motion that answers nothing.
- Before the key the title draws no weather, since the weather route requires the Owner and a sky drawn without it would be invented.
- The display face is Oxanium: variable, 22 KB, Romanian coverage verified, and its figures are tabular. It is limited to the few big words so the measured widths of the working UI do not move.
- The key light keeps the frame's hue but is clamped by contrast, not by taste: the faintest text on the page ground keeps 4.5:1 whatever the sky does.

2026-09-24:
- A moment is played only by an event the socket delivered as it happened and whose own timestamp is under ten minutes old. History (replay, backfill, a restart's outbox backlog) never plays one, so a celebration can never be a re-run of old news.
- The film toast's picture is decoded from the rendered file itself with WebCodecs, not played through <video>. The page's CSP forbids blob: media, and the backend keeps no poster, so the only honest picture is a frame of that exact file, or none.
- The pipeline is drawn as bars on one scale, not as a tapering funnel, because the studio's counts do not narrow monotonically.
- The day tracker takes the newer of the register's events and the runbook's own run record, and «Acum» obeys the record's finish time, so the register's 400-event window can no longer make the page claim that a finished day is still running.

## The serial in one click: today's episode and tomorrow's script (2026-09-24)

2026-09-24, reversible, taken for the Owner by the S0/S1 workflow): (1) The serial resumes unfinished episodes only from the last 7 days (RESUME_WINDOW_DAYS), so the 2026-09-12 DRAFT on his data, never reviewed, is left for his hand and does not hold the serial. (2) A draft passed and waiting for his approval stops new episodes from being written (for up to 7 days), because the episode number is fixed only on approval. (3) One resumed action per run, because the media stage films one episode a day. (4) His approve button builds the storyboard immediately; this is database rows only, and filming stays with the next run he starts. (5) The episode-metadata check is computed and cannot be overridden: lifting a HOLD asks the Publisher again rather than letting the refused title out. (6) BLOCKED_GATE rows are an audit record, not a publication, and do not keep a film out of the queue. None of this touches director_may_approve_episodes.

2026-09-24, reversible, taken for the Owner by the S2/S3 workflow): (1) Departure from 07_STORY_ENGINE 'Load prior DailyStudioLog'. The serial tells the newest closed day with public-safe events within 7 days, not only the prior day. Reason, measured on his data: the prior day is often empty (no event after 2026-09-19 13:43), and 'prior day only' made the Owner's one click produce no episode while a real day sat unused. The spec's intent, a real day dramatised the next production day, is kept by the grounding. Only the 'which day' changes, and the stage names the day it chose. Reverse by setting CLOSE_WINDOW_DAYS and RESUME_WINDOW_DAYS to 1. (2) The run's start closes every missing past date up to 7 days back, never before the first recorded event. (3) Canon runs forward: no day older than the newest day already told is told later. (4) A day of routine only is a quiet day. Otherwise the writer gets 8-15 lines chosen by the weights in projection.STORY_WEIGHTS, and a failure or refusal verdict always counts as story. (5) A refuted claim's text and the first reason of a verdict are public material, redacted. An answered letter's subject is not, because its event cannot tell an Owner letter apart. (6) Model names on record and known model families are redacted from anything public, and the marker is '[redacted]'. None of this touches director_may_approve_episodes.

2026-09-24, reversible, taken for the Owner by the S4 workflow): (1) The cast rule: 2-4 speakers per episode, each the actor of, or named in, an event the episode cites. When the cited events name fewer than two people, those named speak and the rest may come from the day's roster. Everyone else is silent background. (2) Cast count, structure and rooms are computed review checks (FAIL, then one rewrite with notes). Schema, names, citations, placeholders and thread ids are refused at writing time. (3) A refused answer spends one of the day's two drafts, and the retry sees the reason and the refused answer; refused answers are not stored, so a later run may try the day again. (4) Names are normalised to the roster (short name, bible name, role); a spelling two people share maps to nobody; a label is only 'Name:' with a colon. (5) An unlabelled v2-shaped answer is refused; a fully labelled one is converted to lines. (6) 'none'/'nothing' in thread lists means empty; format placeholders are refused; thread ids must be open threads. (7) Locations are the 11 HQ rooms plus the room table. (8) v2 episodes keep their old review rules and are filmed without labels. (9) role_contracts.json v4 adds the serial line, but seeded contracts are not overwritten, so his live ScriptWriter keeps v3 unless he edits it. None of this touches director_may_approve_episodes.

2026-09-24, reversible, taken for the Owner by the S5 workflow): (1) The Director scores hook, situation, turn, payoff, voices and button 1-5. A PASS must carry all six, or it is not a verdict and the draft is read again next run. A PASS with any score below 3 (RUBRIC_FLOOR) is her FAIL. A FAIL needs no scores. (2) Concentration: no event may be cited by more than half the beats unless the day's public projection has exactly one event, because the one episode on his data cites one event in all eight beats. (3) Words per beat, 8-22 spoken, is a hard check for v3 episodes; v2 episodes are measured but legacy. (4) Language: title and every spoken line must pass the Publisher's English guard, checked only when the studio publishes in English. (5) No computed check passes by absence; grounding now fails zero citations. (6) The review facts are fitted to 14,000 characters by shedding measured details, older summaries, voice phrases, long scenes, long event texts, summaries and voices, in that order. Beats, lines and citations are never shed. (7) The 'outcome not in the cited event' rule is the Director's judgement from the facts, not a computed check. (8) The Director's role contract v5 adds the review lines; seeded contracts are not overwritten. None of this touches director_may_approve_episodes.

2026-09-24, reversible, taken for the Owner by the S6 workflow): (1) Specification change to 39_DAILY_AUTONOMOUS_RUNBOOK §7, hash re-recorded. The run gains serial_next after §12: it writes, reviews and approves under policy tomorrow's episode from today's log at the run's hour, and makes no storyboard. The reason is his done-condition: one click films an episode and writes the next, and nothing of an unfinished day is bought. The spec already named the step ('Showrunner chooses tomorrow episode', 39 V4 loop). (2) serial_next needs daily_log. The plan said no prerequisites, but the table's rule is that a stage needs what it reads, and a failed close must not look like a quiet day. (3) The media stage films a serial episode only after its day is over, including one the Owner approved the same day; his approval still builds the storyboard at once. (4) No script is written beside an episode waiting for his approval or the Director's reading (the S1 rule, since the number is fixed on approval). With his current policy (director_may_approve_episodes off), tomorrow's script therefore waits for his approval of the episode before it. (5) The next-episode plan is required, and a missing or copied one is refused within the day's two drafts. The writer's word on keeping the previous plan is recorded as given (kept, dropped, unsaid) and not required. On the next approval the plan is marked KEPT, DROPPED or UNSAID, the one write an earlier episode's narrative record receives. (6) The plan is held to the privacy check like canon. It is not published and not language-checked. Reverse (1)-(3) by removing serial_next from STAGES and serial_films_due from _media. Nothing here touches director_may_approve_episodes.

## The headquarters has a real day, and the live sky follows the real sun (2026-09-24)

2026-09-24 - How a change of light reaches the live headquarters. Decision: a change that finds a value at rest eases over 30 s from what is on screen (as before); a target that moves while an ease is under way re-aims that ease, which still lands 30 s after it began. Why: restarting the ease on every change held every continuously moving value (the sun, the twilight keys, the city's emission) at its first value, so the real sky did not follow the real sun. A first-order smoothing was rejected because it never arrives and would lag a step change further than the 30 s the Owner's page was built around. Reverse by restoring the previous _eased in backend/app/office/unreal.py. Also decided: the Blender day plates were rendered from the scene scripts of 08d07e1 plus hq_day.py, so the night plates and the anchor manifest stay byte-identical; a full night+day rebuild from today's scripts waits for the Owner's eye on the night look.

## The workspace becomes a game frame, and the serial a writers room (2026-09-24)

2026-09-24 - The street in the page's renderer is ambience of the real city, never an event. Decision (taken for the Owner, reversible): the UFO, fireworks, hot-air balloon, delivery drone, helicopter and shooting star are removed (hq_events.js REMOVED_EVENTS); the ordinary street keeps a seeded source for which car or pedestrian appears, but its density follows real inputs - the Bucharest hour, the day of the week, Romanian public holidays (Orthodox Easter computed), the real weather - and it holds still when the page has lost its data; no emergency vehicle drives unless the backend says an emergency exists. Also decided: a replayed (historical) event moves the scene's state but puts up no speech bubble; only a live event speaks. Why: the Owner's first rule, nothing in the office view is simulated. Reverse by emptying REMOVED_EVENTS and passing live = true for every event in main.js onEvent. The buses' AMN liveries and the shelter's ads stay as his art choice.

## The serial made well: a voice per character, one look, its own identity (2026-09-24)

2026-09-24 (S7): the serial's default voices are a proposal in config/serial_voice_cast.json, not rows in his database. The eight ids are from the 21 ElevenLabs premade voices his connection already lists: Sarah Executive = Sarah, Dr. Aris = George, Elena = Alice, Marcus = Liam, Lyra = Lily, Kael = Charlie, Vera = Matilda, Nadia = Bella. The narrator stays his Organization default, Roger, which no character uses. The proposal is used by default because choosing a voice id is free configuration and the price per character is the same. A binding he makes in the character bible always wins, and setting use_until_the_owner_binds to false returns every unbound character to the narrator. An unlocked binding is now honoured for a speaker's lines. A consistency-locked channel without voice locks narrates instead of refusing, because the proposal and the narrator are both fixed across episodes. Captions carry no speaker prefix, because the house caption style has none.

2026-09-24 (S8): the serial's look is a proposal file, config/serial_series_look.json, next to the S7 voice cast, not a row in his channel's series_rules_json. The production-policy validator only accepts purpose keys there, and writing a style block is free configuration he changes by editing the file. The block is versioned: a new version has every serial shot written again before filming, and switching it off returns the serial to the image model's default style. It fixes no time of day, because his HQ rule is that the sky follows real conditions. Serial prompts are capped at 900 characters (factual prompts stay at 1400). The spoken lines are never put in a picture prompt, because a generator draws quoted words as writing. Shot sizes follow the beat's part: an establishing opener, two-shots while people talk, a single for the turn and a close-up for the button.

2026-09-24 (S10): an episode's metadata the guard refuses is replaced by the studio's own, built from the episode and judged by the same guard, instead of holding the film for the Director. The refused answer and the reasons are kept. A HOLD the Publisher gives herself stays a HOLD. The Owner's approval of an episode the Director never read is recorded as PASS, because PASS is the only verdict the story gate and its table constraint accept. The truth is carried by the rest of the row (no reviewer, no run, no checks, source owner_approval, and the reason) rather than by a new verdict that would need a migration. The title format is '<hook> | Inside The Nexus Ep. N'. The previous episode's link is given only when that episode is public or unlisted. The show's tone is one constant (SHOW_TONE) written from 07_STORY_ENGINE.md, and it is the Owner's taste call.

2026-09-24 (S12): the end-of-run stage reports (one STATUS letter per stage to the Director's desk, subject '<stage>: <STATUS> — <reason>') are routine for the serial's story. They say what runbook.stage_finished already says, and a failed stage is still story through its own event. They stay in the Director's mail unchanged. A letter to the Director's desk is projected as a letter to the day's Director by name, and one she posts there herself as a note. A year standing alone (19xx or 20xx) is not redacted as an account number; any other run of four or more digits still is. For the Owner: on his data the Director's leave is still off. The same one-day harness on the same copy writes 09-19's episode and waits for his approval, films nothing, and writes no script for tomorrow; granting the leave is his act. Also for the Owner: a day's log is frozen at the run's hour and never reopened, so the serial tells each date's run (05:00) and nothing that happens after it. Keeping this, closing a PARTIAL log in full the next morning, or moving serial_next to an evening job is his call and a §7 runbook change.

## The live headquarters follows a real clear day (2026-09-24)

2026-09-24, real day rounds 1-3, rules decided. (a) Front-ground budget: from noon down to -2 deg the front pavement and the road median are never brighter than under the noon sun (+3/255 margin; measured budgets 73.7 and 50.6). StreetFill and WalkWash follow STREET_CLEAR_ANCHORS (-2 0.4, -0.7 0.5, +2.7 0.62, +7.1 0.44, +11.9 0.5, +14.1 0.48, +45 0) and rise to their built level with the lamps between -2 and -2.5 deg as a fade. FacadeLight has its own factor (plan lights.facade, role light:facade) on FACADE_CLEAR_ANCHORS, so the building keeps its evening order with every step at least 3. Both curves are calibrated on level build 3 and must be remeasured after a rebuild. (b) Fill colours: fills are exactly their built colour at and below -1 deg and warm only as the sun rises to +1 (FILL_WARM_RISE -1..+1). No sun-coloured light after sunset. (c) Overcast: the deck lights foliage through the sky light (DECK_SKY_LIGHT_LIFT 20 by day, greyed to neutral, RAIN_SKY_LIGHT_LOSS 0.25), and OVERCAST_FILL_SHARE is 0.44. Held back from shipping, because the lift washes the black sign panel to slate and the daytime deck sky stays blue until the atlas gains overcast cells. (d) Rain: while rain falls the road uses roughness 0.08-0.24, below the level's 0.5 trace limit, so it reflects. Rain in the last 3 h alone keeps the built 0.14-0.38. Held back together with the overcast branch until the sky can show the deck. (e) Clear-only shipping means overcast_weight is 0 for every real weather. A partial weight already appears on partly cloudy days (0.05 at 57 % cloud).

## The day replayed from its record, and a live arrival seen across the room (2026-09-24)

2026-09-24, the replay's honesty rules (W13, confirmed and tightened in W14). A replay is the record played back, never a simulation. (a) The source is only the newest finished run in /runbook/runs and the events the studio wrote while it ran, cut by the run's own start and finish events. Nothing is added, reordered or invented. (b) The world at a moment is a fold over the events up to that moment, by the live page's own rules (office_state.js). The only inference allowed is that someone whose first change in the run ends work was working when it began. (c) A value the record does not carry at that moment is «—» (treasury, budget, tokens, serial, schedule); the present is never shown as the past. (d) Every replayed mark is labelled as the replay's: the corner chip RELUARE, the ATUNCI clock, the letterbox and grade, captions stamped «RELUARE · hh:mm:ss», and since W14 the tags, rings and room chips in the replay's violet, a colour used for nothing else. Inside the letterbox (the slate included) everything is the replay's; outside it (the drawers, the register, «actualizat») everything is live and says so. (e) Live wins: a live event that changes the world ends the replay within 6 s, and the world is never live and replayed at once. (f) Nothing is fetched per frame; the record is read once when the replay starts. (g) Under reduced motion the replay steps from stage to stage with no flourish.

## The replay offered once, lit by its own hour: the first YES (2026-09-24)

2026-09-24, W16, decisions taken for the Owner, all reversible. First, the replay's invitation and the façade card name the replayed day «ultima rulare încheiată», not «ultima zi de lucru». The register beside them shows work after 12.09, and the dock's title already used that name. To revert, restore the three strings in replay_invite.js, hq_readouts.js and replay_player.js and the glossary's W16 amendment. Second, the live snapshot's «Actualizat hh:mm:ss» is hidden inside the replay's letterbox, so no live hour sits beside the replayed run's «acum»; drop one CSS rule in office_scene.css to revert. Third, the page does not ask a studio for its books at past moments unless that studio read its log by time, since the two routes ship together; a studio without them shows «—» on the walls as before. Left for the Owner: whether a film uploaded privately to YouTube should be called «publicat» on the invitation, and whether the ambient street should move during a replay whose weather the page says is unknown.

## A kept real frame at entry, and the studio's numbers on the Unreal building (2026-09-24)

2026-09-24, W20, taken for the Owner, reversible: (1) An earlier visit's kept frame waits for the live video's first presented frame and fades off it; nothing is copied over it before then. Reason: the Owner's rule that nothing on the plate is called what it is not; the copy had put this visit's frame under «ultimul cadru live · <earlier hour>». (2) The kept frame's badge is hidden for the whole fade, so «Live» and «pornește sediul live…» are never shown together. (3) Deliberately left untouched: with no kept frame the plate stays dark (his 2026-09-15 rule «Încă apare vechiul format!»), and the Treasury plaque's words (the W19 glossary); both are listed for him in the next wave.

## The key out of the socket URLs, and one building for a returning visitor (2026-09-25)

2026-09-25, W23, decisions taken for the Owner (reversible). (a) The browser's first video-codec enumeration (about 1 s, synchronous) is spent under the title, at page load, when the stream is configured and no key has been given. A first visit's entry then reaches the live building at 0.8 s with no frozen second and no black plate; the cost moves to the page's first 1.6 s, where the title is still decoding. (b) Over the replay in the Unreal building the plaques step aside for every mark (captions, tags, chips), not only captions, even if they move a little more often (16 → 21 set changes per 60 s at 1920). The replay's own marks come first. (c) A replayed tag slides sideways rather than cover a caption's «RELUARE · hh:mm:ss», because that label is what keeps a caption from being read as happening now. (d) Every Pixel Streaming library log line has its token= values blanked, because on a backend that still takes the key in the URL the library printed it on every connect. Not decided, left to the Owner: deleting the old output/*.log files with key-bearing lines, rotating STUDIO_OWNER_TOKEN, and restarting his backend.

## A stranger's first visit in the real building (2026-09-25)

2026-09-25 (W25), decisions taken for the Owner. (1) The public kept frame accepts only a whole still WebP picture from a canvas (VP8X/ICCP/ALPH plus one VP8 or VP8L, no metadata, no animation, at most 4096 px), so a leaked key cannot publish arbitrary bytes on the studio's origin. (2) The weather icon on the glass follows the observed day or night (☾ for a clear night, no sun icon at night); the weather words are unchanged. (3) Of the lit rooms, only the most recent says «acum: …», because a run's stages follow one another. (4) Tags and replay captions stay inside the part of the building the frame shows, and a tag stays within its own width of its speaker. Left open for the Owner: whether a stranger may learn from the public frame when the Owner last watched live (the X-Captured-At time and «ultimul cadru live · azi hh:mm»), and see Unreal's seated figures; whether a night frame up to 24 h old, possibly with other weather, may stand on tonight's title; and a per-peer socket limit if the studio is ever exposed beyond localhost.

## Doors from their rooms, and the studio's sentences in Romanian (2026-09-25)

2026-09-25: (1) Codes leave the Owner's sentences and move to structured fields rather than being deleted. The preflight gains `value` because the page prints `message · detail` side by side, so `detail` must be words too. Stages gain error_class and error_detail; letters keep codes in body_json. (2) The vocabulary is one backend module mirroring the frontend's words, so the page and the backend never name a stage or a state two ways. (3) An exception's message is said as written only when it is already a Romanian sentence the studio wrote. Otherwise it is described by its kind (database busy, HTTP status, timeout, provider refusal) and the raw text goes to error_detail. (4) Model-written text and instructions to models (actions handed to employees, memory rows, prompts) stay as they are, under the Owner's rule that prompts stay English and the serial's words stay English. (5) A pause or resume that would change nothing is a 409 conflict, not a success, and a terminated employee is a conflict, not a 404. Refusal sentences use invariable forms because the employees' genders differ. No architecture specification was changed.

2026-09-25, W29, decisions the judge took for the Owner, each reversible in one place. (1) The fixtures under ui/fixtures were replaced by a capture from a fresh copy of data/studio.db (with -wal and -shm; the original never opened; secrets blanked in the copy). The previous set is kept as ui/fixtures_w28_prev, so the page is judged on what the new backend says. (2) The register's wrapped filter chips stand 8 px apart instead of 4 px, so each chip's 34 px hit area is its own (style.css, two rules; tests/chip_targets.test.js). No sentence the backend writes was changed, no glossary term was changed, and no architecture specification was changed. Left for the Owner, in order: restarting his studio; whether stored history is rewritten once through app.wording with its codes kept; Romanian for the models' Owner-facing fields; the English identity contracts and channel names; one title for Sarah; the storyboard prompt builder's repeated slots (it changes what paid vendors receive); keeping the gold edge of an opened room as a page mark.

## The preflight as a checklist, and real faces over the stream (2026-09-25)

2026-09-25, preflight places vocabulary. A preflight line names where the Owner fixes it by an id from a small fixed vocabulary (backend/app/runbook/preflight.py PLACES): the seven masthead doors (research, media, publishing, workforce, story, runbook, treasury — the id of open-<id>-btn), the four Settings tabs (settings:llm, settings:agents, settings:media, settings:social — settings.js sections), autonomy_switch (the dock's AUTONOMIE), machine (installed on the studio's computer), and not_on_page (the API accepts it, the page has no control yet). Why: W31 judged the Rularea zilei door NO because the preflight printed API routes and settings names. A place that has no control is never named as the fix; the sentence says the page has none yet. tests/test_preflight_places.py checks the vocabulary against frontend/index.html and frontend/src/settings.js, so a renamed room or tab fails a test instead of drifting silently. The technical detail is kept whole in `technical`, for the page's tooltips.

2026-09-25, legacy research rows are read in Romanian, not migrated. Rows tested before migration 0040 carry last_test_reason NULL and the retriever's English. They are read with the reason their text implies and a Romanian sentence, and never rewritten, so the Owner's record keeps what it measured. A data migration was rejected: it would rewrite his database at startup for a display-only difference.

## The Unreal skyline has a real day (2026-09-26)

2026-09-26): the towers' lit windows follow the art director's reading of run 2, not the 09-24 reading in the pass: windows switch off only in the day's glare (above about +15 deg of sun), most are lit by +2 to +3 deg, all at and below the reference dusk; the dawn's fewer windows are a ceiling (0.45 of the dusk's, the existing city rule) on that curve, never a second dimming; the near blocks keep a floor of half their windows while the sun is below +6 deg. Recorded as constants WINDOWS_OFF_ABOVE 15, WINDOWS_MOST_AT 2.5, WINDOWS_MOST 0.7, NEAR_WINDOWS_FLOOR 0.5, NEAR_WINDOWS_FLOOR_FADE (10, 6) in backend/app/office/scene_params.py; the level pass itself (M_HQ_TowerDay, the ranks, the gate) is unchanged and kept as run 2 built it.

2026-09-26): a window that must stop the live stream is not attempted piecemeal when the stop itself is refused: no partial copy into open packages, no preview on the wrong level, the stream left running and the Owner told. The stop of the stream's own processes (by command line: PixelStreamingConnectionURL, SignallingWebServer\dist\index.js) is the one action a towers window needs that the tool's classifier now blocks; a permission rule for it is the Owner's call.

2026-09-26 17:14): run 3 kept with a stated failed gate. The 18:50 frame's distance from the dusk reference (27.5, limit 26.6) was exceeded by the level pass itself (run 2: 27.0), which the art director had ordered kept; the curve's own effect on that score is +0.5 and every defect he named is repaired, so the subagent kept rather than roll the Owner's stream back to dark daytime towers. sign_baseline.json was restored beside the re-applied level (sign_hq_live.py records the built location only when the file is absent). The rollback path stays a copy by hash from the backup, about four minutes of black page.

2026-09-26, the windows rule, art director): the towers' windows follow the sun, not the clock. WindowsOn is 0 only while the sun is high enough for glare to hide the windows (above about +15 deg), rises through the last hour of sun to about 0.7 at +2.5 deg, and is 1 at and below the reference dusk (-2.5 deg) so 19:19 stays the reference to the tenth; on the sunrise side the same curve is capped at 0.45 so dawn has fewer lights than dusk but is never empty; the near blocks are residential and keep their own share so a lit near block never goes black (floor 0.5 now, to be raised to about 0.95 below +3 deg after the run 3 probes). The dusk-reference score is a gate only at and below the reference dusk; for sun-up instants the gates are lit_px against BEFORE, the near block lit, and the day-lit facades of the kept level pass. Run 3 shipped on this rule with the near block called out as the one patch thinner than BEFORE.

## The film staircase — after the Nepal film (2026-09-26 → 2026-10-01)

2026-09-27 (a), the Owner's paid-media rule): `owner_policy.paid_media_approval` (EVERY_PAID_STEP by
default, OVER_USD x, MODE) is read inside `may_act` for media.stills_purchase T2, media.test_shot T3,
media.motion_purchase T3 and media.scene_redo T3, after the unclassified check, STOP, T4 and SAFE_MODE
and before the mode's ALLOWED return, so it asks the Owner in every mode, AUTONOMOUS_CEO included.
Answers are bound to plan_hash, step and cap_credits and spent once; a request without a plan gets
BLOCKED_NO_PLAN. Only the Owner's SetPaidMediaApproval command (POST /api/v1/owner/paid-media-approval)
changes it. Stricter than 51's modes by the Owner's own policy (31's hierarchy). Why: the Nepal film
was bought twice with no question asked. Spec change: 51 got a dated section (hash
175261efc524867d87519109f3bed5d0aa97ab48db6121150803cc82182e7d57) and 31's "read in one place only"
sentence names the rule (hash 970fcce0e0cbcde9c2b6b99852fe3b81d2f9f68f97feb92c76d3f3ba41734f06). Known cost: under EVERY_PAID_STEP every film waits for him,
which conflicts with "autonomous from day two"; only he can loosen it.

2026-09-27 (b), dependencies): opencv-python-headless (with numpy) and the hash-pinned YuNet
face_detection_yunet_2023mar.onnx (Apache-2.0, sha256 8f2383e4…52fa4) for face checks on stills and
clips; the Inter Bold and Regular fonts (OFL 1.1) for the composed cards and captions. Installed
2026-10-01 from PyPI and the opencv Hugging Face repository (opencv-python-headless 5.0.0.93,
numpy 2.5.3); the model's sha256 verified. Without the detector a face check is NOT_RUN and blocks
in PRODUCTION.

2026-09-27 (c), the master): -14 LUFS with a true-peak target of -2.0 dBTP — two-pass loudnorm
linear, aresample 48000, alimiter, AAC once; the QC ceiling stays -1.0 dBTP measured after the AAC
encode. A mono narration is pre-limited and gain-corrected so loudnorm never falls back to dynamic
mode (found on real ElevenLabs takes at -23 to -25 LUFS). Why: Nepal failed at -0.93 dBTP; a limiter
fixes it for 0 credits.

2026-09-27 (d), the Owner's decision, replacing the proposed "one model per film"): "Nu trebuie un
singur model pe tot filmul! Trebuie să optimizăm costurile!" There is no model lock. Each scene
declares its needs (kind, tier HERO or STANDARD, camera move, people/water/fast motion, seconds);
the studio picks the cheapest model in his allowed set whose documented or measured capability
covers them, using the price table, the vendor contract and the failure history per model and kind.
His per-scene override on the sheet wins. The film's expected cost and cap are the sums of its
scenes, with the saving against premium-everywhere reported. Consistency comes from the look block,
stills first with one image model and references, and a colour match — not from one model. A SAFETY
or CONTRACT failure moves only that scene to its next-cheapest capable model; nothing is bought
twice, never a whole-film re-render.

2026-09-27 (e), the timeline): the vendor's native 24 fps with dithered 10-to-8-bit conversion;
lossless x264 intermediates (-qp 0), one lossy final encode: libx264 High 4.2, preset slow, CRF 17,
maxrate 14M, BT.709 limited range, +faststart; cards render at 24; ASS captions of 2-5 words.

2026-10-01 (f), shot plans): a factual film's scene is bought only from a model-written shot
(prompt_json.source == "model"); the parse repairs and re-asks once and otherwise holds the film with
NEEDS_SHOT_PLAN. The office serial's scenes composed from its fixed, Owner-approved series look
(source "series_look") count as a plan too; until the stills and motion steps accept them (next
workflow) a serial episode in PRODUCTION is held with NEEDS_SHOT_PLAN.

## The film staircase closed — ready for the Owner's next paid film (2026-10-01)

2026-10-01 CLIP_QC_WIRING. (1) What counts as an accepted clip: the Owner's APPROVED take, or a PAID take whose clip QC passed. A clip QC could not measure (only NOT_RUN blocks, e.g. no vision model) is kept PAID and UNCHECKED rather than rejected or re-bought: a retry cannot repair a measurement, and the clip was paid for. It enters a PRODUCTION film only after the Owner's look; TEST may use it. (2) The PRODUCTION rule 'no still without the Owner's LOCAL_MOVE' applies to the legacy assemble_video_job too, for any real-stills film, whatever the caller; its default environment stays PRODUCTION (fail closed). (3) The office serial accepts its series-look scenes as a shot plan; a factual film does not. (4) A step's measured spend is booked once per step event, whichever film first assembles it.

2026-10-01, MODEL_CATALOG. Decision: research on a motion model counts only when it is measured or names its sources. In ProviderResource.capabilities, a row with basis 'measured' (or the studio's own judged shots) outranks a steward's sourced research, which outranks config/film_models.json (basis 'documented', with sources), which outranks an unsourced annotation. Reason: the live catalogue held a steward's unsourced quality guesses, some plainly wrong ('4-second clips' for seedance2), and the Owner requires that the next paid film be right ('trebuie sa fim 100% sigur…'). Letting the guesses decide would have filmed landscapes on veo3.1_fast, which the public silent boards rank 16th. The Owner owns 'allowed', 'hero_threshold' and 'premium_reference' in that file; the planner never buys outside 'allowed', and his per-scene override still wins.

2026-10-01, narration timing and money. Narration is bought on /with-timestamps because the vendor documents the same per-character billing and its pricing page lists no surcharge for timing; captions get the real word clock at no extra cost. A narration is never bought twice. The plain /v1/text-to-speech/{voice_id} endpoint is tried only when the timed one is refused as a shape it does not serve (HTTP 404, 405 or 422: no audio was made), and only once; any other refusal is the error. Once audio has come back, nothing in the answer (a bad alignment, bare audio, a missing clock) triggers a second request: the audio is kept and only the timing is dropped. A billed request that got no answer is not resent on either endpoint. The existing retry policy (503/429 with Retry-After, three attempts) and the sanitised vendor errors are unchanged.

2026-10-01 QC_SPANS. Decision 1: a film may run as long as narration + planned breaths + silent composed cards + 1.0 s, not narration + 1.0 s. Reason: the old line forced the timeline to shrink six 0.35 s breaths to about 0.11 s each, so the cuts felt rushed. It also counted a deliberate black end card as an error. Decision 2: the silent maximums come from the writer's spec and the card renderer. BLACK is 'a silence or the closing call to action', so it gets one beat: 2.0 s; a looping short with more black reads as a broken file. TITLE_CARD gets 2.5 s: fade-in, reading, hold. DATA_CARD gets 4.0 s because the four-bar animation needs 3.75 s. Decision 3: the film-level picture check judges each filmed scene on three frames of its own span at 1080 px with the clip checklist, plus YuNet when faces are forbidden. A refusal or a face fails in every environment. A face count that could not run fails in PRODUCTION (fail closed, as clip QC does). A look that did not happen certifies nothing and changes no verdict (rule 50).

2026-10-01 — real paid media is bought only through the shooting sheet's steps, in every environment. The legacy whole-film path (POST /media/render/{id} and the TEST daily media stage) refuses with 409 'Folosește foaia de filmare', or is held, whenever it would hand a real paid vendor adapter to the render. The image, its chain, the voices and each scene's voices are checked before any job exists; the per-scene motion model is refused where it is chosen, before any use. Fakes and local stand-ins keep working. The detection is the module an adapter class comes from (`factory.is_paid_vendor_class`), default-deny: any class in an adapter's MRO defined under app.providers outside FREE_PROVIDER_MODULES is a paid vendor. A new vendor module is therefore paid until it is listed as free in review. A per-class flag that each vendor had to remember to set was rejected.

2026-10-01 — the assemble step's narration is gated through may_act with the sheet's plan_hash, under the existing narration actions (`media.paid_generation` T2, `media.paid_generation_over_threshold` T3 above the Owner's threshold or when unpriced). It is not a PAID_MEDIA_STEPS action, because adding one requires a change to 51_AUTONOMY_MODE_SEMANTICS.md. Consequence: the Owner's EVERY_PAID_STEP rule does not yet cover the narration (AUTONOMOUS_CEO voices it unasked), and MANUAL refuses a priced narration. The proposed spec change, which awaits the Owner's decision: add `media.narration_purchase` to PAID_MEDIA_STEPS and to 51.

2026-10-01, DISK_AND_BREATHS. Shot and card intermediates are lossy-but-visually-lossless x264 High CRF 4 instead of lossless -qp 0, and they are deleted once the film's QC report is recorded; a redo re-derives them from the takes at 0 credits. Why: lossless intermediates were about 1.1 GB a film and were kept for ever, and 321 GB of test films had piled up in the studio folder. CRF 4 halves them at a cost of at most 0.55 dB / 0.25 VMAF on the final, and keeps QC's repeated-frame count exact: the threshold moves to 0.03, between 0.013 (repeats) and 0.097 (the slowest real clip). CRF 6 and above lost repeats, and no-B-frame or fixed-QP encodes were larger. Films rendered before this change record no shot source and keep their intermediates. In the same item the timeline keeps every 0.35 s breath, since QC now budgets them.

In the drawer, a redo is a priced plan bought under its own plan_hash (POST /media/storyboards/{id}/redo through the Owner's approval), never a rejected still as before. «Asamblează filmul» is offered only when no paid step is left on the sheet (steps.assemble.paid_steps_left empty) and no filmed scene is blocked. Reason: the drawer is the paid path of a PRODUCTION film, and assembling before the motion is bought would voice a narration over still frames; in TEST the backend could still assemble from stills, but the drawer does not offer it.

## Gates that hold on a fresh clone (2026-10-02)

2026-10-02 GATES_AND_CI — explicit index hash update, as AGENTS.md requires. Decision: an architecture document's recorded `sha256` in `docs/project/DOCUMENTATION_INDEX.json` is the SHA-256 of its text with CRLF folded to LF (`scripts/check_docs.py` `document_sha256`), no longer of the raw checkout bytes. No document content changed: for each of the 78 documents the LF-folded working copy was checked byte for byte against the HEAD blob before the hashes were re-recorded (77 values changed, 02_SRS's was already the LF one); `original_sha256` values are untouched. Reason: git stores every document with LF, but a Windows checkout with core.autocrlf writes CRLF and Linux writes LF, so the raw-byte check failed on every fresh clone (measured on a clone of 15d2f96: 77 documents failed with autocrlf=false or on Linux, 02_SRS failed with autocrlf=true), and the README's first verification step and CI could never pass for a buyer. `.gitattributes` now keeps `* text=auto` and `docs/architecture/*.md text eol=lf`. No renormalising git command was run; the index already held LF for every text file.

2026-10-02 GATES_AND_CI — the secret scan reads what git would ship (`git ls-files --cached --others --exclude-standard`; outside a git checkout, a walk that skips `.git`, `.claude`, `data`, `.venv`, `node_modules` and the other generated folders, and never opens `.env` or a credentials key). It also scans `.mjs`, `.ps1`, `.ts`, `.yaml`, `.txt`, `.cfg`, `.cmd` and `.patch`. It fails only on a finding missing from the reviewed `.secrets.baseline` (detect-secrets format, matched on file, detector and hashed value, so a moved line stays reviewed and a copy in another file does not), and prints locations only. Every baseline entry was reviewed as a non-secret (pinned SHA-256 digests, AWS's documented example key, Unreal asset paths, runtime-built or placeholder test keys). Rule for later work: a new fake key in a test carries an inline `# pragma: allowlist secret`; the baseline is regenerated (`scripts/check_secrets.py --write-baseline`) only after a reviewer has read every new entry.

## The production-readiness audit (2026-10-01 → 2026-10-02)

The Owner asked on 2026-10-01 for a complete audit: the whole project production ready and ready to sell, films made automatically, quality 10 out of 10. Ten audits scored it (autonomy 3/10, quality 5, security 7, reliability 5, money 5, publishing 6, page 5, sellable 3.5, tests 6, architecture 5) and twenty items were implemented test-first with every provider faked, 0 credits spent. The decisions below are the ones that change how the studio behaves; each names its reason. None of them was tested against a real paid vendor.

**ADR-HERO-CLIP-QC — the hero test shot can be accepted by clip QC (HERO_AUTO_ACCEPT).** Decision: the rest of the motion follows the hero when `assembler.hero_gate` finds the hero PAID, its latest clip-QC report PASSED, and a dry `may_act("media.motion_purchase", cost_usd=<motion cap>, ask_owner=False)` ALLOWED. The acceptance is the event `media.hero_accepted_by_clip_qc`; the take stays PAID and APPROVED remains the Owner's alone. Under EVERY_PAID_STEP, SUPERVISED and MANUAL nothing changes: he looks at the hero. Reason: the gate accepted only his APPROVED, so under his own MODE rule every day ended WAITING HERO_NOT_APPROVED and no film could be made without him, which contradicted the rule he chose. Reusing the kernel's answer for the motion (not a new action) keeps STOP, SAFE_MODE, T4, the mode, his rule and the budget in one place. Rejected: a new risk-tier action `media.hero_accept`, which would have been a second place to read the rule.

**ADR-OVER-USD-CAP — OVER_USD compares the step's cap (GATES_BEFORE_BUYING).** Decision: the paid steps hand `may_act` the step's credit cap in USD; the question says «plafon X USD». Reason: the estimate is not what the step may spend; with clip-QC retries inside the cap the real spend can reach the cap, so his threshold must be compared with the most the step may cost.

**ADR-DAILY-BUDGET-REQUIRED — no unasked purchase without a daily budget (GATES_BEFORE_BUYING).** Decision: in PRODUCTION, when MODE or OVER_USD would let a paid step through unasked and the mode allows its tier, `may_act` answers BLOCKED_NO_BUDGET unless an active DAILY SpendingBudget exists; a monthly budget alone is not enough; the preflight line `spending_budget` is BLOCKING in exactly that case. Reason: measured on fakes, a fresh install with no budget let a $10,000 hold through. A missing limit must stop spending, not remove the limit.

**ADR-FILM-CEILING — a ceiling per film (GATES_BEFORE_BUYING).** Decision: `film_budget_usd` (STUDIO_FILM_BUDGET_USD); unset, it is `motion_budget_usd` plus the stills cap of a six-scene film at the published price (15.24 USD with the defaults). Books plus the step's cap above the ceiling is refused OVER_FILM_BUDGET in PRODUCTION; his allow_over_budget passes it with an event. Reason: daily budgets alone let one stuck film be bought again day after day. Known consequence, left to the Owner: a four-scene film of 10 s scenes on seedance2_5 has a 27.20 USD motion cap, above the default ceiling, so under MODE such a film waits OVER_FILM_BUDGET after its hero until he raises STUDIO_FILM_BUDGET_USD.

**ADR-SCENE-MEMORY — per-scene failure memory and `max_paid_attempts_per_scene` (NO_REBUY_RECOVERY_REFERENCES).** Decision: a scene the gate sent to the Owner, refused for safety, lost, unanswered, or that reached `max_paid_attempts_per_scene` (default 3, 1-20) paid attempts is held NEEDS_OWNER and is never bought again until his act (a model change, a decision on its takes, an approved redo, new words). A refusal that cost nothing (vendor or account absent) holds nothing. Reason: measured on fakes, failed scenes were bought again on every run (image requests 3/6/9, video POSTs 2/4/6 over three days).

**ADR-FILM-RETIREMENT — `film_wait_days` (DAY_FLOW_NO_STALL).** Decision: an unrendered factual film that stood still for `film_wait_days` (default 3, 1-60) business days is set REJECTED by the Director with one letter listing what was bought and booked, and its topic frees. Never retired: a film with a pending question of his, a film asked that day, a film waiting on his money or budget. The walk also passes over a film stopped for its own reason so the films behind it move. Reason: the daily run took only the oldest film, so one stuck film blocked every later one for ever.

**ADR-FILM-CONTINUE — his yes continues the film the same day; paid-media questions last 48 h (CONTINUE_REDOS_E2E).** Decision: in PRODUCTION an APPROVED paid-media question, or an APPROVED take other than narration, queues one FILM_CONTINUE task (priority 4, one attempt, idempotent per approval) that walks only that film through the same staircase, every purchase again behind may_act; paid-media questions expire after `paid_media_approval_expires_hours` (48, 1-168). Reason: his yes took effect only at the next 05:00 run and expired after 24 h, so under EVERY_PAID_STEP a film climbed one stair per day and a yes given in the evening could expire unused.

**ADR-AUTOMATIC-REDOS — free repairs applied automatically, paid redos capped (CONTINUE_REDOS_E2E).** Decision: a film that fails QC is repaired free first (re-encode from the same takes, card recompose, sound remaster), then by paid scene redos only through `redo_scene` with the redo plan's plan_hash (may_act, budgets, the ceiling, the lease), at most `film_max_paid_redos_per_scene` (1) and `film_max_paid_redos` (2); every failed film gets one deterministic Romanian letter. Reason: QC's proposals were read by a model and left to the Owner, so a fixable film stood still; the caps bound what the repair may spend.

**ADR-MANUAL-DEFAULT — a new install starts MANUAL (SELLABLE).** Decision: `services.bootstrap_studio` sets `NEW_STUDIO_AUTONOMY_MODE = "MANUAL"` only on a studio row it creates; an existing row, the Owner's included, is never changed. A new studio also starts STOPPED, in TEST and with the daily job inactive. Reason: a buyer's first start must not be able to spend; promotion stays his recorded act.

**ADR-NO-SCHEDULED-WORKFLOWS — scheduled jobs no longer create Workflow rows (QUEUE_LEASE_SHUTDOWN).** Decision: a scheduled fire writes the outbox event `workflow.job_fired` and a task with no workflow; the 47 content pipeline is implemented as DailyRun stages; manual workflows and their routes stay; the 665 dead rows in the Owner's database are left as they are. Reason: every fire created a Workflow row that never moved (665 CREATED/DISCOVERY rows) and whose cancel route stopped nothing — a control that does nothing is worse than none.

**ADR-COMPONENT-LICENCES — a licence ledger per component (FILM_AUDIO_AND_RIGHTS).** Decision: migration 0051 adds `licence_vendor`, `licence_terms`, `commercial_use` to scene_take; a film is LICENSED only when every component (still, clip, voice, font, music track) carries commercial-use evidence, from the Owner's own answer on each connection (Setări, «Planul tău permite folosire comercială?»); otherwise NEEDS_REVIEW, which QC passes for a private upload and RIGHTS_GATE refuses for unlisted, public or scheduled. Music comes only from his licensed library, each entry with a licence and a SHA-256. Reason: assets were stamped PROPRIETARY_STUDIO by the studio itself, which a buyer could not defend. Older assets keep their old stamp (not re-judged).

**ADR-NO-SOCKET-TOKEN — the key never travels in a socket URL (SECURITY_STARTUP_LOGGING).** Decision: any WebSocket whose query has a `token` parameter is closed 1008 before accept, on `/api/v1/ws` and the stream relay; the page sends the key as the first message only, and does not open the stream when first-message auth is unavailable; uvicorn's access log redacts `token=`. Reason: a key in a URL reaches access logs and history; first-message auth has existed since 2026-09-25, so the legacy path only kept the leak alive.

**Explicit architecture hash entries (DOCS_AND_STATUS), as AGENTS.md requires.** Each amendment below is additive and dated «amended 2026-10-02»; no earlier sentence was removed. Hashes are the LF-folded SHA-256 (`scripts/check_docs.py` `document_sha256`), recorded in `docs/project/DOCUMENTATION_INDEX.json`; `original_sha256` values are untouched; check_docs passes.
- `../architecture/51_AUTONOMY_MODE_SEMANTICS.md` → `d55b7434c4502fe9dface54ca4ac8a9326bd30a0cfb952e63afbd992082bbfc5` (was `ebde6e5f2480c0eb…`). Reason: finding A17/AR-13, the paragraph "Not built at this writing" was false since 2026-10-01; the new subsection «The staircase as built» names the callers, the cap rule, BLOCKED_NO_BUDGET, the hero rule, FILM_CONTINUE and the narration's status.
- `../architecture/08_VIDEO_PIPELINE.md` → `57d3f9c2289c307a12c544a1a5c8339ed0a5edd17563127fec924c87a22ff463` (was `fdf41c8590434a5d…`). Reason: AR-13, the only real paid path (sheet, lint, prices and cap, stills, hero, motion, clip QC, takes with intent and recovery, failure memory, booking, assembly, music bed, QC and repair, cover) was absent from the pipeline spec; new section «Paid staircase».
- `../architecture/11_DATA_MODEL.md` → `3708f1e49dec4af0f9468df87b7f162e50e965aa056c9b5613827bd210dd521b` (was `718be7248068761f…`). Reason: AR-13, scene_take (with remote_task_id, SUBMITTED, LOST, narration and the licence columns), film_purchase_lease, spending_budget, spend_reservation, daily_run, task_queue leases, publication remote state and channel upload settings were in no document.
- `../architecture/39_DAILY_AUTONOMOUS_RUNBOOK.md` → `cb20789f3dfd0b309bbee506bebc7fc35d1e79c333a30b450a187c0a3e6f346a` (was `ea0b33c4df411dff…`). Reason: AR-13, §8 said the media stage reserves one hold per film; it now climbs the staircase with a reservation per stair, the lease, the film ceiling, the walk, retirement and FILM_CONTINUE.
- `../architecture/47_STATE_MACHINE_SPECIFICATIONS.md` → `2f92aceb3b6feab20561559e934b94d2d77ae70da370bab36ff31ceccc7e794b` (was `d2171c1e9e291129…`). Reason: AR-14, the content pipeline is implemented as DailyRun stages (RUNNING → COMPLETED/PARTIAL/BLOCKED/FAILED, INTERRUPTED at most once), the scene_take states, and Workflow rows no longer made for scheduled jobs.
- `../architecture/25_DEPLOYMENT_BACKUP_OPERATIONS.md` → `76933e75b562d910aef200f7f9439ec3bc7b570da6975633e98133420c12d5ee` (was `b9c8eb49b790d26f…`). Reason: AR-08, the backup, backup before migrations, restore guard, disk floor, health thresholds, one worker per database and the state of CI as built.

**Pending — the Owner's decisions, not written into the architecture.** (1) `narration_purchase`: whether the narration becomes a fifth paid step under his paid-media rule; today it follows the studio's mode (`media.paid_generation`, T2/T3) and the page says so. (2) LOCAL_MOVE: whether a scene may be filmed as a local push-in instead of a paid clip beyond the cases he picks per scene. (3) always-on: whether the studio moves to an always-on host (25's «Always-On Studio»); today it is a Windows PC that must be signed in for the DPAPI key. Also his: a git remote or self-hosted runner for CI (TS-04), the film ceiling's figure, the daily budget, the commercial-use answers on Runway and ElevenLabs, a licensed music library, STUDIO_DISPLAY_NAME for the AI disclosure, the YouTube reconnects (both invalid_grant since 2026-09-26) and the Ollama Cloud connection (every model call of his 2026-10-02 catch-up day failed).

## The Owner's decisions window (2026-10-03)

The Owner, 2026-10-03: «Dacă sunt decizii pe care eu ca owner trebuie să le iau, trebuie să îmi apară un card. Trebuie să am propria mea fereastră unde pot să accept sau refuz ce îmi este recomandat sau trimis.» Offered the shapes on a card, he chose «Fereastră Decizii separată»: a «Decizii (N)» button always visible at the top of the page opens his own window with every card (paid-step approvals, recommendations from agents and from the audit, letters that ask him something); each card says what, why, the recommended option and the cost or effect, then «Accept» / «Refuz» with an optional note; his accept applies through his own Owner command, a refusal is recorded, and the history of his answers stays in the window. Four items (DECISIONS_CORE, DECISION_SOURCES, DECISIONS_WINDOW, DOCS_AND_STATUS), each test-first with every provider faked, 0 credits, no run started, his studio on :8000 never stopped. Proven on fakes only: the window has not yet been seen in a browser and its Playwright flow has not run.

**ADR-OWNER-DECISION-CARDS — one kind of card for every question that is his (DECISIONS_CORE).** Decision: migration `0054_owner_decisions` adds the `owner_decision` table (kind, subject, `title_ro` / `why_ro` / `effect_ro`, options and `clears_when` as JSON, source, `dedupe_key`, status PENDING / ACCEPTED / REFUSED / WAITING_FOR_OWNER_ACTION / WITHDRAWN / EXPIRED, the chosen option, his note, `decided_by` / `decided_at`, what was applied, `apply_error_ro`, `expires_at`, `version`, `event_id`); a partial unique index allows one open card (PENDING or WAITING) per `dedupe_key`. `GET /api/v1/owner/decision-cards` returns three sources in one card shape, newest first, with `count` (the button's N), `counts` and `history`: the paid-step approvals (answered through the existing `POST /api/v1/owner/approvals/decision`, whose logic is not duplicated), the decision cards, and the open letters to him whose intent is REQUEST_INFO, REQUEST_REVIEW, CHALLENGE or ESCALATE (answered through the letters' own reply and resolve routes). Reason: his questions were scattered across the approvals list, the letters, Settings and the audit's prose, and a question he never sees is never decided. Rejected: folding the new questions into ApprovalRequest. An approval authorises exactly one act on one thing and is read by `may_act`; a budget figure or a reconnect is not that, and a card stored as an approval could be read as authority by the gate.

**ADR-ONLY-OWNER-DECIDES — an agent proposes, never decides (DECISIONS_CORE, DECISION_SOURCES).** Decision: `propose_owner_decision(session, …)` and `withdraw_owner_decision(session, …)` are the only verbs open to agents, stages and the seed. A proposal is idempotent per open `dedupe_key` (a savepoint plus an IntegrityError fallback for races), validates its options (at most one recommended, put first; a guided option must name a place) and writes nothing to the ledger: it is not an act. `decide_owner_decision` accepts only `issued_by="owner"`; `DecideCommand` forbids extra fields, so no body can name an issuer; it is versioned (`expected_version`) and idempotent by command id. The route `POST /api/v1/owner/decisions/{id}/decide` is behind `require_owner` and answers 404 for a missing card, 409 for a stale or closed one, 403 for another issuer and 422 for a failed apply or an invalid option. Reason: his standing rule that only the Owner decides; a service that took «decided by» from its caller would let an agent pass for him.

**ADR-APPLY-THROUGH-OWNER-COMMANDS — his accept runs his own command (DECISIONS_CORE, DECISION_SOURCES).** Decision: ACCEPT runs the chosen option (the recommended one by default) through the `APPLIERS` registry, each entry an existing Owner command: `set_budget(set_by="owner")`, `change_paid_media_approval(issued_by="owner")`, `change_environment`, `change_autonomy_mode`, and, for a paused sheet repair, `blocker_repair.allow_repair_retry` (new, Owner-only, idempotent by correlation id, event `media.sheet_repair_retry_allowed`) and the shooting sheet's `set_scene_model(…, LOCAL_MOVE, issued_by="owner")`. The inner command id is uuid5 of the card, its version and the option, so a retried answer never applies twice. An option's `expect` refuses the apply when the state moved since the card was written. A failed apply commits nothing, keeps the card PENDING with `apply_error_ro` and writes `owner.decision_apply_failed`. Every answer writes one `owner.decision_decided` event carrying `applied_event_id`. Option types `none` and `record` are recorded only. New apply types go through `register_applier`, new clear conditions into `CONDITIONS`. Reason: the same audited path runs whether he moves a setting himself or accepts it on a card: the command's own validation, policy version and ledger event, and no second writer of his policy. Rejected: writing the policy or budget rows from the decisions service.

**ADR-GUIDED-DECISIONS — what only he can do stays his act (DECISIONS_CORE).** Decision: a guided option (reconnect a connection; Google's consent screen «In production» and the YouTube API audit; commercial use on the Runway and ElevenLabs connections; licensed music in `config/music_library.json`; editorial QC blocking, a `.env` setting; the sale terms) records his choice with its place in Setări (`place_ro`, `steps_ro`) and moves the card to WAITING_FOR_OWNER_ACTION («în așteptarea acțiunii tale»), or straight to ACCEPTED when its condition has already cleared. DONE («Am făcut-o») completes it, and `refresh_owner_decisions` completes it when its `clears_when` reads true (`integration_verified`, `youtube_connected`, `youtube_channel_connected`, `commercial_use`, `music_library_has_music`, `daily_budget_at_least`, `paid_media_approval_is_not`, `setting_is_set`, `media_folders_below`, `file_exists`, `sheet_repair_resumed`, `never`). A PENDING card whose condition clears is WITHDRAWN; a PENDING card past `expires_at` is EXPIRED. Reason: these are his accounts, his licences and his legal terms; the studio may name the place and check the result, never act in his name. Left open: commercial use and editorial QC stay guided because no connection-config or setting applier was registered; that is a later choice of his.

**ADR-DECISION-SOURCES — the studio asks through one door (DECISION_SOURCES, DECISIONS_CORE).** Decision: `app.decisions.sources` proposes a card where the question arises, with shared keys and card builders: a film's paid step waiting OVER_DAILY_BUDGET or BLOCKED_NO_BUDGET whose cap can never fit a day under the active limit (`daily_budget:film:{storyboard}`: raise to the larger of the step cap and the film cap, rounded up to 5 USD, or keep); a model run FAILED with HTTP 401, 402 or 403 on a Settings integration (`reconnect:{integration}`, withdrawn by the next successful run; 404, 429 and 5xx give no card); YouTube `invalid_grant` or refused upload authorisation (`reconnect_youtube:{connection}`, withdrawn by authorisation or verification); a film whose licence ledger is NEEDS_REVIEW (`commercial_use:{integration}`); a film with no music bed and an empty library (`music_library`); a paused sheet repair (`sheet_repair_paused:{storyboard}:{cause}`: retry now, local move for LIVE blocked scenes, or wait; the letter stays). A card he REFUSED is not proposed again for `REFUSAL_QUIET_DAYS` (7). Every producer runs in a savepoint or its own transaction, so a card failure is logged and never fails the run, upload or film that called it. `app.decisions.seed` proposes the audit's pending questions idempotently at bootstrap and at start-up, each only while the studio's state says it still stands; a key that ever had a card is never seeded again, even after a refusal. The budget card prices the studio's real cheapest capable film. Measured on a copy of his database (copied with -wal/-shm and migrated in the scratchpad, never opened in place): the cheapest capable 4-scene film on his Runway connection is wan3 at 8.72 USD expected and an 11.44 USD cap, so his 15 USD/day holds a film and no budget card is seeded (the audit's ~28 USD was a seedance-only film); Ollama Cloud and both YouTube channels were reconnected on 2026-10-03, so no reconnect cards; his window would open with 9 decision cards and 3 letters. Reason: one card per question, whoever notices it first.

**ADR-DECISIONS-WINDOW — his own window, «Decizii (N)» (DECISIONS_WINDOW).** Decision: a «Decizii» button first in the top bar's right cluster, its badge the feed's `count` («99+» above 99, plural through `countWords`); a modal dialog along the right edge (Esc closes, focus returns) with the tabs «Te așteaptă» and «Istoric». Each card shows its kind and source in his words, what, why, the effect or cost, the options with the recommended one first and marked «Recomandat», then «Accept» / «Refuz» and an optional note. An option that spends money or changes his policy (budget, paid-media rule, environment, autonomy mode, an approval that is not a paid step) asks once more («Da, aplică» / «Nu acum») before anything is sent. A paid-step approval's Accept is «Accept pe foaia de filmare» and opens the film's shooting sheet, because the paid yes is given on the sheet bound to its `plan_hash` (PAGE-03); its Refuz goes through the approvals route. Letters are answered through their own routes. Only paths under `/api/v1/` are called. Until his restart his studio answers 404 on the feed: the window says so and the badge falls back to approvals plus open letters. Reason: his words, and the shape he chose on the card.

**Explicit architecture hash entry (DOCS_AND_STATUS), as AGENTS.md requires.** The amendment is additive and dated «amended 2026-10-03»; no earlier sentence was removed. The hash is the LF-folded SHA-256 (`scripts/check_docs.py` `document_sha256`), recorded in `docs/project/DOCUMENTATION_INDEX.json`; `original_sha256` is untouched; check_docs passes.
- `../architecture/31_GOVERNANCE_APPROVAL_POLICY.md` → `67ef4c69f19371869637ea7dc11f459a3cd913d0f664f64fcc75f1ac15c7b4ce` (was `ad5ade9db67471e9…`). Reason: 31 specified only the Approval object; the new section «Owner decision cards (amended 2026-10-03)» states what a card is and is not: anyone proposes, only the Owner decides, his accept runs his own command, a card is never an approval and never reaches past a hard gate, and a guided step stays his act.

**Pending — his decisions, not written into the architecture.** (1) Narration as a paid step under EVERY_PAID_STEP (`narration_purchase`) is on a card as option type `record` only; the spec 51 amendment and the code change are not done. (2) A real «scene to card» Owner command (a LIVE scene turned into a DATA_CARD or TITLE_CARD) needs a spec decision; the sheet-repair card offers LOCAL_MOVE meanwhile. (3) Whether commercial use is set on accept (a connection-config applier) instead of guided. (4) Whether a newly proposed card writes a ledger event (today a proposal writes none, so a new card reaches the window on its poll, not over the socket).

## A paid step asks for its next round only (2026-10-03)

The Owner, 2026-10-03: «De ce avem nevoie de asa de multe credite daca sa creezi o imagine costa 10-20 de credite». His LHC film (storyboard 4d0da5d9) waited WAITING_OWNER on LOW_BALANCE with 316 credits: its stills step buys 8 LIVE scenes × 2 candidates × 9 credits = 144 credits, but the start check asked the balance for the step's whole cap (432: the first round plus two re-roll rounds) × 1.15 = 497. Offered the choices on a card, he chose «Doar pentru runda următoare».

**ADR-NEXT-ROUND-BALANCE — the balance holds the next purchase, the cap stays the ceiling (NEXT_ROUND_BALANCE).** Decision: one rule in `app.media.balance_rule`, used by the stills step, the shooting sheet, the motion staircase and the scene redo. To START a paid step the balance must hold the cost of its next round only × the margin (`settings.paid_step_balance_margin`, 1.15, rounded up once): the stills step's first round (every scene it buys, two candidates each), the test shot's one shot, the motion step's shots, a redo's one purchase. BEFORE EACH FURTHER purchase (a stills request, a re-roll round, a clip-QC retry, the next motion shot, a redo's re-roll) the balance is read again and must hold that purchase's price × the margin; when it does not, that scene stops cleanly — NEEDS_OWNER, `failure_kind` LOW_BALANCE, a Romanian reason naming the balance, the price, the need and what is missing — what was bought is kept, nothing half-done is charged, nothing more is bought in the step, and the scene's hold event says `holds: false` (a top-up, not a decision on the sheet, lets it go on). The cap he approved stays the absolute ceiling of the step (STOPPED_AT_CAP unchanged), and a balance that cannot be read or that the vendor refuses still stops the step (fail closed). The sheet's footer shows the next-round need (`balance_needed_credits`) and, per step, the likely cost, the cap and the need (`balance_rule`). Reason: his words; the cap is the most a step may spend with its re-rolls, not what it spends, and asking for it up front kept a film waiting on credits it would likely never use. The per-purchase check keeps what the old rule protected: no purchase is sent on a balance it could exhaust. Rejected: asking the cap at the start (the old rule, his question), and asking no margin at all (a request could be sent on a balance it empties half-way). Not changed: character reference sets (`REFERENCE_BALANCE_MARGIN`): a set is one round, each slot bought once and never re-rolled, so its check already asks that round × 1.15.

**ADR-LOW-BALANCE-CARD — a short balance at a paid step is his card (NEXT_ROUND_BALANCE).** Decision: when a paid step of the sheet does not start on the balance, or stops a scene on it, `decisions.sources.film_low_balance` proposes one card per film (`low_balance:film:{storyboard}`): «Alimentez contul Runway cu cel puțin N credite» (guided, Setări → Video și sunet, N the amount missing for the next purchase) or «Aștept». It clears through the new condition `balance_covers`: the newest balance reading a paid step recorded (`media.paid_step_balance_read`, written by `run_sheet_step` at every start check and at every stop on the balance) after the card was written covers the need it names. The feed that refreshes the cards never calls the vendor. A step of the film that starts withdraws the card. The day's letter stays. The sheet repair's letter to him («Foaia necesită intervenție: …») now names the film by its title, not by eight characters of its id. Reason: a top-up is his act on his account; the studio says how much and sees when it is done.

## A redo that hung, and a film held «în lucru» for hours (2026-10-03)

The Owner, 2026-10-03: his «Refă» on the still of scene 3 of the Nepal film (storyboard 81438d13) spent his yes, was charged 18 credits by Runway and recorded nothing; the film's three-hour purchase lease then refused every press «acum 144 de minute» after the process had been stopped. Root cause in CURRENT_STATUS (REDO_HANG).

**ADR-VENDOR-WAIT-ENDS — every vendor wait has an overall end (REDO_HANG).** Decision: `media_http.request` takes `total_seconds`, reads the body in pieces and raises as unanswered once it has passed (a purchase is never resent on it); every Runway call passes one (organization 30 s, submit 90 s, poll 45 s, still download 120 s, shot download 600 s), and one still purchase ends at `IMAGE_PURCHASE_DEADLINE_SECONDS` (420 s) with TaskStillOpen and its task id. Reason: a socket timeout bounds one read, not an answer; a poll or a download that kept trickling held a paid redo for as long as the vendor liked. Rejected: a thread-level timeout around the purchase (Python cannot stop the blocked thread; the wait would go on unseen). Amended 2026-10-04 (completeness pass): the paid ElevenLabs narration POSTs carry `NARRATION_TOTAL_SECONDS` (180 s) too; they run inside the leased assemble step, whose live holder would otherwise keep the film «în lucru» up to the lease ceiling.

**ADR-REDO-TASK-ON-THE-BOOKS — a redo writes what the vendor accepted before it waits (REDO_HANG).** Decision: the still redo records each accepted task SUBMITTED with the vendor's id the moment it is accepted (as the stills step since 2026-10-01); candidates land on that row; TaskStillOpen stops the redo IN_FLIGHT, books what was committed and is never retried; the watchdog and the stills settlement collect it for free; a redo plan of a scene with a SUBMITTED still is not buyable. Reason: Runway lists no tasks; an id kept in memory is lost with the process, and with it the money.

**ADR-FILM-LEASE-RENEWED — a film's purchase lease lives only while its holder renews it (REDO_HANG).** Decision: the holder's process renews the lease every 60 s, never more than 300 s ahead and never past `film_purchase_lease_seconds` from its start (now the ceiling of one purchase, not its standing time). A lapsed lease is taken back by the watchdog, by the next buyer, and - at the start of the process that holds the worker lock - a lease from before that start that stands further ahead than any renewing holder writes (the old three-hour rows). Taking one back releases the film's `sheet:*` holds taken under it, records `media.film_purchase_lease_reclaimed`, and writes the Owner one letter (kind `film_purchase_abandoned`): his yes was spent, what the balance readings before and after say (and what the books do not explain), what is collected free, and that nothing is bought unless he presses again. Nothing is re-bought for him. Reason: a lease that outlived a dead holder by hours blocked the film and hid a spent yes; a renewing holder is the only proof of life that works across two studio processes on one database. Rejected: releasing the lease by process id (a second studio process serves the same database; pids are reused); a card in his Decisions window (there is nothing to decide: the letter states what happened and his next press asks him again). Known limit: a holder whose renewals fail for five minutes in a row (the database locked that long, the machine asleep) can be taken over while it still runs.


## start.py starts the graphics, and a stop stops everything (2026-10-04)

The Owner, 2026-10-04: «cand rulez python start.py, trebuie sa porneasca si grafica. La fel, cand opresc, totul trebuie sa se opreasca!» Until then `start.py` started only the server; the live headquarters (wilbur and Unreal) were started by hand with `start_live_hq.ps1`, outlived everything, and a stop of the studio left them running.

**ADR-START-WITH-GRAPHICS — start = studio + graphics (START_WITH_GRAPHICS).** Decision: `scripts/start.py` (not `--demo`) starts the graphics with the server: once the server's address answers, a supervisor thread (`scripts/live_graphics.py`) starts wilbur, then Unreal, and checks them every 15 s. The server never waits for Unreal. The stream's arguments live in `art-source/unreal/live/stream_command.json`, read by both `start_live_hq.ps1` and `start.py` (one list; the script's old command line reproduced byte for byte). The graphics are skipped, with one Romanian line, under `--no-graphics`, in `--demo`, off Windows, without the machine paths (`AMN_PS_INFRA`, `AMN_PS_NODE`, `AMN_UE_ROOT`), without `STUDIO_OFFICE_STREAM_SIGNALLING_URL` (the page could not show them), in session 0, and when the studio's address already answers before the server starts (another studio owns the picture). Session 0: the default Interactive scheduled task runs in his own session, where Unreal renders as from `start.cmd`, so it starts the graphics; an S4U task (`-RunWhenLoggedOff`) runs in session 0, without a desktop, where Unreal has never been seen rendering, so it does not. Reason: his words.

**ADR-STREAM-GATES — the graphics follow his rules, not the other way round (START_WITH_GRAPHICS).** Decision: (1) never two streams: a stream left running is adopted (its processes put in start.py's job when Windows allows, else stopped explicitly at the stop, and said); a second Unreal of the stream is stopped; (2) a process is the stream's only by name AND command line (`UnrealEditor.exe` with `AMNReference.uproject` and `-PixelStreamingConnectionURL`; `node.exe` with `SignallingWebServer\dist\index.js` and `wilbur.config.json`), checked again just before it is stopped, so a reused pid, his own editor or a shell quoting the patterns is never touched; (3) another Unreal on AMNReference (a rebuild's commandlet, the editor opened on it) holds the stream; (4) while one of his games runs (`PathOfExile*`, `League of Legends`, `LeagueClient*`; not `RiotClientServices`) or free commit is under 16 GB, the studio runs and the graphics wait, said once, and start by themselves after two game-free checks (his card of 2026-10-03: «Singur, când închizi jocul»); (5) a dead Unreal or wilbur comes back after 30, 60 then 120 s, at most three restarts an hour, under the same gates, each death and the hour's limit said. wilbur's own restart is not held by the game and memory gates (it is ~50 MB and only follows a running Unreal); a stream already running is not stopped when a game starts. Rejected: restarting adopted leftovers to own them (a 25 s outage and a 13 GB spike for nothing); judging Unreal dead by a silent Remote Control (a slow frame would kill the picture in a loop).

**ADR-STOP-STOPS-EVERYTHING — a stop leaves nothing running (START_WITH_GRAPHICS).** Decision: Ctrl+C reaches the server from the console and `start.py` waits for it however many Ctrl+C come (`subprocess.run` killed it 0.25 s after the first one, cutting REL-10's 30 s graceful stop), then stops Unreal, then wilbur: each asked to close (WM_CLOSE) and ended after 10 s / 3 s, naming each. wilbur runs without a console window of its own and Unreal in its own process group, so Ctrl+C reaches only the server and the order holds. `start.py` puts itself in a Windows Job Object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` (ctypes, `scripts/win_processes.py`) before its first step, so every process it starts, and theirs, is in the job from its first instruction (nested under `uv run`'s or the terminal's job); when `start.py` ends however it ends, Windows ends them. A console control handler on CTRL_CLOSE/LOGOFF/SHUTDOWN stops the graphics within Windows' five seconds and gives the server what is left. Reason: his words. Known limits: a closed window gives the server about five seconds, not 30 (Ctrl+C is the clean stop); a process Windows refuses to nest is said and stopped explicitly, but survives a forced kill of `start.py`.

**ADR-STOP-SERVER-OWN-GROUP — the server is asked once, and no other Ctrl+C reaches it (START_WITH_GRAPHICS, adversarial check 2026-10-04).** Supersedes the first sentence of ADR-STOP-STOPS-EVERYTHING. Found: with the server in `start.py`'s console group, a second Ctrl+C reached uvicorn (0.52.4) while it waited for an open connection and set its `force_exit`, so the lifespan shutdown - where the day stops at its boundary, REL-10 - never ran (seen with a real uvicorn and a request in flight). Decision: the server is started with CREATE_NEW_PROCESS_GROUP; at the first Ctrl+C (or Ctrl+Break, now a Ctrl+C for `start.py`) `start.py` stops its supervisor's starts and sends CTRL_BREAK once to the server's group (uvicorn handles SIGBREAK as its graceful stop), retrying at the next Ctrl+C only if the send failed; it waits in 0.5 s steps, because on Windows `Popen.wait()` without a timeout cannot be interrupted. An exit of 3 after that request (uvicorn re-raises SIGBREAK) or 0xC000013A (a console event) is a stop, not a failed start. Corrected limit: a closed window gives the server no clean stop at all - Windows ends it as soon as its own console handler returns (seen: no lifespan shutdown); the graphics and the rest go with the job. Ctrl+C is the only clean stop. Rejected: forwarding later Ctrl+C (uvicorn would force-exit); `subprocess.Popen.wait()` without a timeout.

**ADR-DONE-READS-CONDITION — his «Am făcut-o» closes a card only when the studio sees it done (DONE_READS_CONDITION, 2026-10-04).** Decision: DONE on a decision card reads its `clears_when` (`condition_reading`). When it reads true, or when nothing the studio can read clears it (`never`, or no condition), the card closes as before (ACCEPTED, completed by him). When it reads false, or cannot be read (fail closed), the card stays WAITING_FOR_OWNER_ACTION, his press is recorded (`owner.decision_decided` with `still_missing_ro`) and `apply_error_ro` says in Romanian what is still missing. The seed re-opens, once per card (`reopened_at`), a guided card an earlier DONE closed while its condition does not read true, on its own row, with an `owner.decision_reopened` event, never while another open card holds the key; refusals and «keep it as it is» answers are never re-opened. Reason: on 2026-10-03 his DONE closed commercial use on Runway and ElevenLabs and the sale terms with nothing done; the page said done while the licence gate still refused, and «a key is never seeded twice» meant forever. ADR-GUIDED-DECISIONS says the studio may name the place and check the result; spec 31 («until its condition clears or he marks it done») is read as: his DONE asks the studio to check, and it closes the card when the check passes. Rejected: refusing the press with an error (his press would leave no trace and the card would not say what is missing); a new card beside the old one (the old one would still say «Ai marcat-o făcută»). Left open: whether spec 31's sentence should be amended to say this explicitly. Amended the same day (DONE_REOPEN_GUARD, adversarial review): the re-open repairs only DONEs taken before the fix; a DONE that closes a card records `done_reading` (MET or ONLY_OWNER) and is never re-opened when its condition changes later (a balance spent, a «da» taken back), and an old DONE is never re-opened over a newer card for the same key (his answer there stands).

**ADR-POLICY-READ-PER-REQUEST — a paid step bought unasked reads his policy before every vendor request (MODE_REDUCTION_STOPS_PURCHASE, 2026-10-04).** Decision: spec 51 («Lowering autonomy. Immediate and safe: … active workflow external writes respect current policy at execution time») is applied per vendor request, not per step: before each stills request, re-roll, shot, clip-QC retry and redo re-roll, a step nobody pressed asks `may_act(..., ask_owner=False)` again (nothing written, no yes read or spent). It goes on when the answer is ALLOWED, or NEEDS_APPROVAL for a step that spent his yes for this plan (the question he already answered; `may_act` lets EVERY_PAID_STEP + his yes buy under MANUAL too); his own press goes on through `OWNER_PRESS_PASSES`. Anything else stops the step before the request; what was bought is kept and booked; `media.paid_step_stopped_by_mode` records it once with «Modul de autonomie a fost coborât la manual la HH:MM … restul nu s-a cumpărat». Unasked, a step the kernel refuses outright is refused before the balance is read (no low-balance card under MANUAL); a question still waits for the balance. Reason: on 2026-10-04 the LHC stills step bought scenes 4-9 (108 credits) after he lowered the mode to MANUAL at 05:08:27 UTC. Rejected: stopping a step bought on his yes for this plan when the kernel only says he would be asked (it would refuse what `may_act` itself allows).

**ADR-STUDIO-DEFECT — a vendor 400 that names our own request's parameters is the studio's defect (2026-10-04).** Decision: a 400/422 whose text matches `production_policy.STUDIO_DEFECT_PATTERNS` (Runway's «must use `auto_480p`…» keyframe ratio; «Data URI is too large») is classified STUDIO_DEFECT: the step stops (the next request would carry the same defect), the scene is not held for the Owner, the model is not dropped (`take_failure` ignores such a take), nothing is suggested to him. Holds such refusals left earlier as CONTRACT are released once by the watchdog (`release_studio_defect_holds`, `media.studio_defect_hold_released`, read by `scene_memory`), buying nothing. A generic «Validation of body failed» stays CONTRACT. Reason: the Nepal test shot (81438d13 scene 1, wan3 0.98) was held since 2026-10-03 20:56 with seedance2_5 at 0.75 offered as his «choice» only because our request carried a fixed ratio. Known limit: a defect that is not yet fixed is tried again (uncharged 400) on the next run; nothing escalates it to the team yet.

## RunPod Serverless, phase 1: the GPU on only inside an approved paid step, off right after (2026-10-08)

The Owner's cards of 2026-10-08, after the investigation of 2026-10-08 (official RunPod pages re-read the same day; RunPod's pages carry an «Agent Instructions» block that was treated as data). Everything below is proven on fakes only: nothing called RunPod, Hugging Face, a registry or a bucket, and no image was built. No provider integration is marked working until the paid bake-off card.

**ADR-RUNPOD-SERVERLESS-ONLY — all stills and video on RunPod Serverless, one RTX PRO 6000, budgeted at 4.00 USD/h (RUNPOD_PHASE1).** Decision: `RunPodConfig.mode` defaults to `serverless` (the Pod stays possible, frozen); `stills_endpoint_id` / `motion_endpoint_id` (the old `endpoint_id` is the fallback of both); `max_workers` is 1 and its validator allows only 1 (raising it is a code + ADR change); `hourly_rate` is `serverless_cost_per_hour` 4.00 in Serverless, the Pod's 2.09 otherwise. Reason: RunPod's own pages disagree (pricing page 3.49 USD/h; Serverless settings page 0.00111 USD/s = 4.00 USD/h); the higher figure is the budget until a real bill settles it (bake-off item). Alternatives rejected: a Pod (billed while idle, disk billed while stopped, may come back with zero GPUs, keeps billing if the studio dies). Migration: 0056 (below). Rollback: `RUNPOD_MODE=pod` or deselect RunPod; Runway is untouched.

**ADR-GPU-OFF-IMMEDIATELY — off one second after the last result (RUNPOD_PHASE1).** The Owner: «trebuie sa se opreasca imediat dupa, nu la 30 sec. Sunt taxat la secunda, deci trebuie oprit imediat dupa generare». Decision: `idleTimeout` = 1 s, the documented minimum of `EndpointWorkers.idleTimeout` (1..3600, inside `workers`; https://docs.runpod.io/api-reference-v2/serverless/update-a-serverless-endpoint.md); a paid round is ONE batch job (or chunk jobs POSTed back-to-back) so models load once per round; when the step ends the session closes in `finally`: purge-queue, cancel what is left, `PATCH workers {min 0, max 0, idleTimeout 1}`, verify OFF = `workers.max == 0` and `workers.running == 0` and `jobs.inProgress == 0` and `jobs.inQueue == 0`. `workers.idle` is logged, never alarmed: an Idle worker is scaled down and not billed, FlashBoot may keep it above 0 (the skeptic's correction). RunPod's own «after 7 days max set to 0» is a normal OFF. A close that cannot verify never breaks the step: CLOSED with `verified_off` false, event `runpod.gpu_off_unverified`, one letter «Am trimis oprirea GPU-ului RunPod, dar nu a confirmat că s-a oprit; verific din nou la fiecare minut.», and the guard retries. Code: `providers/runpod/endpoint.py` (EndpointControl: GET/PATCH on api.runpod.io, health/purge/cancel on api.runpod.ai, idempotent calls retried on unsent/429/5xx, 401/403 = EndpointAccessDenied), `providers/runpod/gpu_session.py`.

**ADR-GPU-ON-IN-STEP-ONLY — agents switch the GPU on only inside a paid step already approved, under its cap (RUNPOD_PHASE1).** Decision: Policy Kernel action `infra.gpu_on` (T2), read after the stop, T4 and safe mode and never by the mode's own ALLOWED: `context.step_action` must be one of `PAID_MEDIA_STEPS` (stills, test shot, motion, scene redo), the RunPod connection's `allow_infra_actions` must be true (the Owner's card), and the step itself must run now: `may_act(step_action, {plan_hash}, cost_usd, ask_owner=False)` allowed; or NEEDS_APPROVAL with `approval_id` naming his APPROVED answer of that action, film and plan (unexpired, or already spent by the step); or his own press and a status in `OWNER_PRESS_PASSES`. Else BLOCKED_NOT_IN_STEP / BLOCKED_INFRA_DISABLED. It never asks him, never spends a yes, writes nothing. `open_session` asks it; a refusal (or a failed PATCH) refuses the step before anything is sent (GpuSessionRefused, `unsent`), so nothing is bought and the journal keys stay reusable. One GPU at once: a session on another endpoint makes the step wait `gpu_busy_wait_seconds`, then GPU_BUSY; two sessions on one endpoint share it (the last close switches it off). `StepPermit` gained an optional `cost_usd` (the step's cap, default None) so the inner question is the one the step asked. The card (kind `runpod_infra_actions`, dedupe `runpod_infra_actions:<integration>`): «Agenții pot porni singuri GPU-ul RunPod în pașii plătiți aprobați?», options «Da, doar în pașii aprobați» (applies `runpod_infra`: config `allow_infra_actions` = "true", version bump, event `runpod.infra_actions_enabled`, idempotent by the inner command id) and «Nu încă»; it clears when the flag is true. A save of the connection form keeps his answer (it is not a form field, and the form refuses it). The guided card `runpod_ltx_licence`: the LTX-2.5 gate on Hugging Face is accepted on his own account, with an HF token as a build secret. Rollback: refuse the card, or set the flag false; every step then refuses BLOCKED_INFRA_DISABLED before sending.

**ADR-GPU-OFF-ALWAYS — switching the GPU off is never an autonomous act (RUNPOD_PHASE1; amends 51).** Decision: `infra.gpu_off` (T0) is answered ALLOWED by `may_act` as its FIRST check, before the unclassified check, STOP AUTONOMY, T4 and safe mode: «Oprirea GPU-ului nu este o acțiune autonomă: nu cheltuie, doar oprește cheltuiala». `force_off` (the Owner's «Oprește GPU acum», the guard, the shutdown, the launcher) never consults the kernel. docs/architecture/51_AUTONOMY_MODE_SEMANTICS.md gains a dated amendment under «STOP AUTONOMY»; its index hash moves d55b7434c4502fe9dface54ca4ac8a9326bd30a0cfb952e63afbd992082bbfc5 → fd7af4e4a25bad8b9f0d94cab4e36e32337f3efe3e49e14615bb53941fbfd62f. Reason: a stop that also stopped the off would keep a per-second bill running. Alternative rejected: putting the guard in the watchdog or a scheduled job (both are behind the stop by spec: «It changes nothing while the Owner's autonomy stop is set»).

**ADR-GPU-GUARD — a GPU found on with no paid step open is switched off (RUNPOD_PHASE1).** Decision: `providers/runpod/gpu_guard.py`, run only in the process that holds the worker's lock (beside `reclaim_abandoned_leases`) when `STUDIO_RUNPOD_GUARD_ENABLED` (default true): BOOT (60 s bound; every live session of another process becomes FORCED_OFF GUARD_ORPHAN), a loop every `guard_interval_seconds` (60) while a session is open or closed less than 15 minutes ago, else every `guard_idle_interval_seconds` (600): sessions not renewed for `session_stale_seconds` → GUARD_STALE, past `expires_at` (opened + 4 h) → GUARD_TTL with a letter; each endpoint with no live session is read and, if anything can bill, purged, cancelled, set to max 0 and verified, with event `runpod.gpu_guard_off` and one letter «GPU-ul RunPod a fost găsit pornit fără niciun pas plătit deschis și a fost oprit.»; a drift from the resting settings (min, idleTimeout, flashboot, timeout) is PATCHed back (`apply_baseline`, cost-reducing); three unreadable ticks in a row are one event and the letter «Nu pot verifica GPU-ul RunPod (cheie sau rețea). Verifică în consola RunPod că 0 workeri rulează.». At shutdown, after the worker has ended, `force_off(SHUTDOWN)` (20 s bound). `scripts/start.py` then runs `scripts/runpod_gpu_off.py --reason LAUNCHER_STOP` (same interpreter, 45 s; on a closing window `--fast` first: purge + PATCH only, 2 s a request, 4 s in all), which always exits 0 and prints one Romanian line, silent without RunPod. Table `gpu_session` (migration 0056) records every session and how it ended. Crash bound: a batch already sent runs at most its execution timeout (≤ 2400 s, ≤ 2.67 USD at 4 USD/h, one GPU) and then scales to zero by RunPod's own idle rule; the BOOT guard sets max 0. Balance reads are not in phase 1 (RunPod's billing API field unconfirmed): the cap, the one-GPU rule and prepaid credit without auto-pay are the backstop.

**ADR-RUNPOD-ANYWAY — «Totul pe RunPod oricum» (RUNPOD_PHASE1).** Decision: if RunPod's quality is below Runway's, everything still goes to RunPod: no per-scene Runway fallback by default; Runway stays installed and selectable by the Owner; the planner takes the selected RunPod model (selected_default branch) although its quality is unmeasured until the bake-off.

**ADR-RUNPOD-MODELS — the open models, licence-checked (RUNPOD_PHASE1).** Decision: stills Qwen-Image-2512 (Apache-2.0) at its native 928x1664 plus SeedVR2 (Apache-2.0) upscale to exactly 1530x2720; motion LTX-2.5 distilled image-to-video as route 1 (LTX-2.x Community Licence: free under 10M USD revenue, the AI disclosure stays on, metadata/watermark/provenance never stripped, gated on Hugging Face — the Owner accepts it himself) and Wan 2.2 I2V-A14B + LightX2V 4-step (Apache-2.0) as route 2. Excluded: FLUX dev and Qwen-Image-2.1 (non-commercial), Hunyuan* and MiniMax (licence not valid in the EU). `model_routes`: VIDEO_QUALITY and VIDEO_HERO → LTX-2.5. Worker image (backend/runpod_worker, WORKER): our own handler reads the Save node's output file (the stock handler skips `temp` outputs), every weight sha256-pinned and fetched with a build secret, `BASE_DIGEST` and `COMFYUI_VERSION` required, nothing built or pushed by the studio; the workflows are UNPROVEN until the bake-off.

**ADR-RUNPOD-BUCKET — outputs in the Owner's S3-compatible bucket (RUNPOD_PHASE1).** Decision: RunPod keeps a /run result 30 minutes, so the worker writes every output, manifest and claim to a bucket the Owner creates (e.g. Cloudflare R2), read through SigV4 presigned URLs (7 days at most = 604800 s); any S3-compatible HTTPS endpoint; its two keys live in the RunPod connection's vault (`s3_access_key_id`, `s3_secret_access_key`), never in .env for his studio. A step is refused before any GPU switch while the bucket is not configured.

**ADR-JOURNAL-NO-PICTURES — the journal keeps a picture's fingerprint, not the picture (RUNPOD_PHASE1).** Decision: migration 0056 replaces every `data:<mime>;base64,…` in a journal row's `request` (`reference_images[]`, `source_image`) by {"sha256", "bytes", "mime"} (batched, idempotent; `payload_hash` unchanged), and adds `batch_remote_id` (indexed), `batch_index`, `request_digest`, `gpu_session_id`, `billed_seconds_value` to `cloud_generation_job`, and the `gpu_session` table. Reason: 6.7 MB rows. Downgrade drops the table and columns and cannot restore the pictures (documented). Never run on data/studio.db by an agent; the test migrates a temporary database holding a fat 0055 row.

**ADR-RUNPOD-BATCH-ROUNDS — a paid step on RunPod is rounds of one batch each, priced with their overhead (RUNPOD_PHASE1, STEPS).** Decision: round 1 buys every item of the step in one batch; later rounds only what QC sent back; each round is priced before it is sent (items + one round overhead = (cold start 120 s + idle 1 s) × rate) and must fit the step's remaining cap; the Owner's yes and `may_act`'s `cost_usd` cover the worst case of every round with its overhead. The mode guard is read before each round and polled while it runs; a stop cancels the unfinished chunks, keeps what finished, and records the rest «nu s-a cumpărat». Each item keeps its own journal row and SceneTake SUBMITTED before any poll; collection reads the bucket manifest first.

**ADR-RUNPOD-BOOKING-NEVER-BELOW — the books are raised to what RunPod used, never lowered below the forecast (RUNPOD_PHASE1, adversary «money and the staircase», 2026-10-08).** Decision: after each round the studio reads its jobs' final /status once (`BatchRun.settle`; items normally arrive through the bucket manifests, so the times were otherwise never read) and, when (delayTime + executionTime)/1000 + idleTimeout per job × the budget rate exceeds what the meter kept for the round, raises the meter (the step's booking, and the cap left for its next rounds) to it (`gpu_batch.run_rounds(credits_for_seconds=…)`, `assembler.gpu_seconds_to_credits`). A measure below the forecast never lowers the booking: the Owner approved the forecast, and only a billing read (phase 2) settles it downward. The figure is an upper bound (queue and throttled time are counted, back-to-back chunks count the wait of the second). Also: a round whose first chunk's /run answer was lost is never refunded or refused as «nothing sent» because a later chunk could not leave; one item whose result cannot be taken (checksum, manifest, echoed key) fails alone as BAD_OUTPUT and stays counted; a passing read error while polling leaves the item pending (the round's deadline bounds it) instead of cancelling the paid batch.

**ADR-RUNPOD-NO-LONE-RUN — on Serverless nothing is bought outside a round and its GPU session (RUNPOD_PHASE1, adversary, 2026-10-08).** Decision: `RunPodGenerationProvider._submit` refuses every per-request purchase in Serverless (not the mock) before anything is written or sent (MediaProviderError NEEDS_GPU_ROUND, unsent). Reason: outside a session workers.max is 0, so a lone /run waits in RunPod's queue and is served, and billed, by the next step's worker; and the studio's worker reads only `amn.batch.v1`. The still redo was still per-request: on a RunPod Serverless image adapter it is refused NEEDS_GPU_ROUND before the Owner's yes is asked or spent; a round-based still redo is left to build (the stills step re-buys a scene meanwhile). Prices from config/runpod_models.json are provenance ESTIMATED and read «estimare GPU nemăsurată dd.mm», never «tarif publicat»; a RunPod film's page shows «RunPod GPU» and applies no Runway balance rule (the backend's `local_step` already skipped it). Left open: a step's yes is spent before `open_session` asks `infra.gpu_on`, so a refusal there (card not accepted, GPU busy) uses up the yes with nothing bought.

**ADR-RUNPOD-PRECHECK-BEFORE-YES — a RunPod step refuses before the Owner's yes when its GPU could not start (RUNPOD_PHASE1, completeness check, 2026-10-08).** Decision: the stills step and the motion step (test shot, motion, scene redo) on a batch adapter call `gpu_batch.gpu_precheck` (`gpu_session.precheck`) before they ask for or spend his approval: Serverless configured for the purpose, the bucket configured, and his card «Agenții pot porni singuri GPU-ul RunPod în pașii plătiți aprobați?» accepted (`allow_infra_actions`); else the step is refused with `NOT_CONFIGURED` or `BLOCKED_INFRA_DISABLED` and his words, nothing asked, nothing spent, nothing sent. A simulation passes. Reason: the open item of ADR-RUNPOD-NO-LONE-RUN: the yes was spent before `open_session` asked `infra.gpu_on`, so a card not yet accepted cost him a yes with nothing bought. Left open: GPU_BUSY (a second film on the other endpoint) is still decided only by `open_session`, after the yes; with one film at a time it does not arise.

**ADR-RUNPOD-WORKER-PINNED — the worker image is pinned to what exists (RUNPOD_PHASE1, completeness check, 2026-10-08).** Decision: the base is `runpod/worker-comfyui:5.10.0-base` at `sha256:e9d18d3db15839ebb10c10c824109fc2956f31ef7bf21916220c008855b0d538` (the OCI index the registry served on 2026-10-08); `5.11.0-base` has a GitHub tag but the registry answers 404. `COMFYUI_VERSION` is 0.39.2, the release whose source every graph node was checked against. Every public weight's revision, sha256 and size come from Hugging Face's repo tree at that revision (metadata, no download). The gated LTX-2.5 files keep `sha256` null until `python -m runpod_worker.build resolve --image motion` reads `paths-info` with the Owner's `HF_TOKEN` (metadata only; the size must equal the pinned one, else nothing is written). The Dockerfile's ComfyUI checkout is sound: the base installs ComfyUI with comfy-cli 1.13.0, which runs `git clone`. Reason: `build plan` refused everything, and the base it would have used does not exist. Rollback: set the pins back to null; the build refuses again.


## RunPod weights in cached models, the reference route and the copy pod — studio side (2026-10-09)

The Owner's cards of 2026-10-09, answered after the research of the same day (official RunPod and Hugging Face pages; RunPod's «Agent Instructions» blocks treated as data) and its skeptic's corrections, which win over the recommendation. His answers: «Unde stau modelele (≈138 GB)?» → **Cache RunPod**; «Ce model face pozele cu personajele tale, pornind de la poze de referință?» → **Qwen Edit 2511**; «Unde ținem cele două copii pe Hugging Face?» → **HF PRO, private**; «LTX-2.5 … Permiți o copie privată în contul tău, cu licența inclusă?» → **Da, cu licența** (LICENSE + Attachment A kept with the copy; the AI disclosure stays on; free under 10M USD revenue; not inside a product competing with Lightricks without a separate licence — not legal advice); «Cine construiește programul mic?» → **RunPod din GitHub** (a private repo holding only the worker; the worker's change). Still for later cards (money): the one-time copy pod's run (below: his accept of its card) and the paid bake-off. Everything here is proven on fakes only; nothing called RunPod, Hugging Face, GitHub, a registry or a bucket; no provider is marked working.

**ADR-RUNPOD-CACHED-MODELS — the weights live in RunPod's cached models, one per endpoint, fed from his private mirrors (RUNPOD_CACHE_STUDIO).** Decision: `RunPodConfig.model_source` = `cache` (default) | `volume` (fallback) | `baked` (last resort); per endpoint `stills_mirror_repo`/`stills_mirror_revision` and `motion_mirror_repo`/`motion_mirror_revision`; `hf_token` is a vault secret of the RunPod connection that only the copy pod receives. What the studio expects is his settings first, else the worker image's own pin (`backend/runpod_worker/mirrors.lock.json`, `weights.expected_weights`). The fallback's fields are named as REST v2 names them, `networkVolumes` and `dataCenterIds` (not `networkVolumeIds`, the skeptic's correction), and `apply_baseline` sends them only under `volume`. Under `cache` a paid step refuses `WEIGHTS_NOT_READY` before his yes until the mirror's repo and revision are known. Reason: the image pull and cached-model downloads are not billed and the cache does not pin a data centre; the volume costs ~9.8 USD/month and bills its read on every round. Rollback: `model_source=volume` (with the volume fields) or `baked`.

**ADR-RUNPOD-CACHE-WAIT-IN-TTL — the unbilled cache wait is always inside the job's TTL (RUNPOD_CACHE_STUDIO; the skeptic's correction).** Decision: a cache miss can happen on ANY round (RunPod «tries» a host holding the model, else delays the worker until the download ends, unbilled), and the TTL counts from submission; so under `cache` every chunk's `ttl` = executionTimeout + `queue_wait_seconds` + `model_cache_wait_seconds` (3600 s), never only after a change, and the billed executionTimeout never grows with it. A job still IN_QUEUE past `model_wait_notice_seconds` (60 s) is shown on the GPU switch as «aștept descărcarea modelului (neplătită)». Rejected: adding the wait only on the first round after a mirror change (the recommendation).

**ADR-RUNPOD-WEIGHTS-CHECK — the studio checks what each result says it loaded, because the cached-model field has no API (RUNPOD_CACHE_STUDIO).** Decision: the worker reports `weights_revision` and the codes `MODELS_MISSING` / `WRONG_REVISION` (read with `MODEL_REVISION_MISMATCH` as the same). A result with another revision, or either code (any source), stops the step: what is left is cancelled, no further round is sent, the session's close sets workers.max=0, and the card «Endpoint-ul RunPod pentru imagini/clipuri are alte modele» (kind `runpod_weights`, dedupe `runpod_weights:<integration>:<purpose>`) says which endpoint, what is expected (repo + revision) and the console step «Manage → Edit Endpoint → Model»; options «Pun modelul corect în consola RunPod» (guided; his «Am făcut-o» closes it) and «Las GPU-ul acestui endpoint oprit». While it is open or kept off, `precheck` and `open_session` refuse `WEIGHTS_MISMATCH` before his yes; a new expected revision releases it. A worker reporting no revision is not called wrong. Reason: the REST v2 schema has no model/cache field (research: «Confirmat»), so the field can be neither set nor read by the studio.

**ADR-RUNPOD-REFERENCE-2511 — locked characters are drawn on RunPod by Qwen-Image-Edit-2511 from 1-3 pictures (RUNPOD_CACHE_STUDIO).** Decision: config/runpod_models.json gains `Qwen-Image-Edit-2511` (Apache-2.0; workflow `qwen_image_edit_2511_ref_seedvr2`; 75 GPU-s a still, an UNPROVEN estimate) with a `reference` binding (`reference_image`, `_2`, `_3`; min 1, max 3; `text_model` Qwen-Image-2512). A RunPod image adapter accepts a picture only when its selected model declares such a binding (`ACCEPTS_REFERENCE_IMAGE`, `MAX_REFERENCES`); the stills step sends the character's picture first and Figure 1 second (presigned URLs) and records `references_sent`; the journal records `reference_bindings`; an item with no picture is drawn by the text model and its row says so; pictures for a model without a binding, or more than it binds, are refused unsent. Consequence: Qwen-Image-2512 is no longer handed Figure 1 (its graph never read it). `REFERENCE_IMAGE_VERIFIED` stays false until the bake-off measures the identity hold. Rejected (licence): Qwen-Image-2.1 (research-only), HunyuanImage 3.0 (EU excluded), FLUX.1 Kontext dev / FLUX.2 dev, InsightFace-based routes.

**ADR-RUNPOD-MIRROR-COPY — the one-time copy pod starts on his accept of its card, capped, and is always terminated (RUNPOD_CACHE_STUDIO).** Decision: the card «Copiez modelele în contul tău Hugging Face cu un server RunPod temporar?» (kind `runpod_mirror_copy`, proposed by the audit seed while a cache endpoint misses its mirror revision; options «Da, pornește copia acum (plafon 5.00 USD, 240 minute)» and «Nu încă»; clears when every endpoint knows its revision). His accept IS the press: `apply_runpod_mirror_copy` → `pods.start_copy`, which re-reads the card (a PENDING card counts only under its own inner command id; a retried accept finds the same copy) and refuses, with his reason and nothing started, a missing token, repo, bucket or key, a simulation, a second copy, or a cap above the card's. The pod: a CPU pod (`cpu5c`, 4 vCPU, 200 GB, `python:3.12-slim`) named `amn-mirror-copy-<id>`, the worker's files and result addresses through his bucket as presigned URLs (it holds no bucket key), `HF_TOKEN` only in its env, `build.py mirror --execute` per image. The guard terminates it on success, failure, one tick before the time or dollar cap (RunPod's reported cost per hour, else 1.00 USD/h), and at BOOT or SHUTDOWN, plus any `amn-mirror-copy` pod no running copy owns; success writes both mirrors' revisions into his settings. Table `runpod_copy_pod`, migration 0057 (downgrade drops it). Why one step and not «Pornește copia» on the settings page: the same consent asked twice, and a button can be pressed for a cap he never read, while the card carries the cap he reads. Left open: pinning the copied commit where the worker reads it (mirrors.lock.json + a release, or the endpoint's env) is his/the worker's step; the studio does not PATCH endpoint env (that makes a release).

## The Owner's RunPod switch and setup checklist (2026-10-09)

**ADR-RUNPOD-OWNER-SWITCH — «RunPod pornit» on the connection replaces RUNPOD_ENABLED in .env (his card, 2026-10-09).** The Owner asked the studio to do the whole RunPod setup and to ask him only for accounts and logins, and approved on a card: a switch in Setări → RunPod instead of editing `.env` (which no agent may open). Decision: the switch is stored with the RunPod integration (`config["enabled"]` "true"/"false", version bump, event `runpod.switch_changed` {on, before, by: owner}); effective `RunPodConfig.enabled` = the switch when set, else `RUNPOD_ENABLED` from the environment/.env, else false; every reader builds its config from the row per call, so no restart. ON is his act (`require_owner`, a second press on the page) and needs the connection VERIFIED, else 409 with his reason; OFF is always allowed and runs the existing GPU off at once (`force_off` OWNER_OFF on the connection's endpoints: purge, cancel, workers.max=0, verified) and ends a running copy pod by the existing shutdown rule (`watch_copies` SHUTDOWN, results kept). The form neither shows nor sets it, and a form save keeps it. Consequences: the connection check reads with `enabled` forced on (GET-only; otherwise the switch could never meet its own precondition), and the periodic background check skips a RunPod connection that is switched off. A read-only checklist «Pașii configurării» (GET/HEAD only, results kept as `runpod.setup_checked`, no secret returned) shows his remaining steps with console links. Rejected: a settings field in `.env` written by the studio (agents may not open `.env`; a restart would be needed); an ON without verification (a switch that promises a GPU the connection cannot reach). Rollback: press «Oprește RunPod», or remove `enabled` from the connection's config to fall back to `RUNPOD_ENABLED`. Proven on fakes only; nothing called RunPod, a bucket, Hugging Face, Cloudflare or GitHub.


**ADR-RUNPOD-COPY-DISK — the copy pod's disk fits RunPod's CPU rule; refusals carry RunPod's words; a save proposes its cards (2026-10-09).** Context: the Owner's first accept of «Copiez modelele» met `POST /v2/pods` → HTTP 400 with no reason kept, so neither he nor the studio could tell a bad field from a full data center. Decision: `mirror_pod_disk_gb` 200 → 60 (cpu5c gives at most 15 GB of container disk per vCPU, docs.runpod.io/flash/configuration/cpu-types; `build.py mirror` keeps one weight on disk at a time, the largest 21.5 GB); a 4xx create puts RunPod's sanitised `detail` and per-field `issues` (the HF token cut again, 300 characters) in his refusal and in the warning `runpod_mirror_copy_refused`; `PUT /settings/integrations/{id}` runs `seed_owner_decisions` after a successful save (each card still proposed once; a failure is logged and never fails the save). Rejected: raising vCPUs to 16 to keep 200 GB (4x the price for disk the copy does not use); guessing the cause without RunPod's reason. Proven on fakes; the live retry is his accept after a restart.


**ADR-OWNER-CLOSE-FILM — the Owner closes a film; a closed film holds nothing and buys nothing (2026-10-09).** Context: a film waiting only on his decision is never retired (`retire_stale_films`) and keeps its topic live, so `_selection` chose nothing new for days (three films waited). Decision: `POST /api/v1/media/storyboards/{id}/close` (Owner, schema_version, command id; same id → same answer, a new id on a closed film → `already_closed`, no second event) takes the film's purchase lease, re-checks, sets the storyboard REJECTED and records `runbook.film_retired` with `retired_by: Owner` (the books part of the Director's retirement is now one shared helper); it withdraws his PENDING approvals about the film through the Policy Kernel (`withdraw_subject_approvals`, EXPIRED + `governance.approval_withdrawn`), the decision cards whose subject is the film, and the asking letters that name it (money and ledger alerts stay). Closed = REJECTED with no finished render; `film_purchase_lease` refuses every step but `close` for it, so stills, test shot, motion, assemble (the day's assembly now runs under the lease), redo, take choice, sheet repairs and shot-plan writers all refuse or skip. Refused: a live GPU session, a claimed/running FILM_CONTINUE or render (FILM_BUSY), a rendered or published film (FILM_RENDERED: publishing works from the file; QC, viewing or publication end it) and a serial episode (SERIAL_EPISODE: nothing would write that day again). Submitted takes are still collected (a free GET). Rejected: letting a new topic start while old films wait on him (more films in flight, more paid questions at once); a Director auto-retirement of films waiting on him (his question would vanish unanswered). Proven on fakes.


**ADR-RUNPOD-UNSENT-PROOF — never-queued is proven, not assumed; a legacy hold is his card (2026-10-09).** Context: the first live stills /run failed in 0.12 s without a job id and without RunPod's reason; the items stayed SUBMISSION_UNCERTAIN, scene 1 was held for the Owner and no action of his could free it (decide_take refuses REFUSED takes; the RunPod still redo refused). Decision: on an uncertain /run the session's close reads /health once (5 s, no retry) before the purge, keeps RunPod's purge `removed`, verifies off and lists overlapping sessions; the items become FAILED/UNSENT at 0 cost (keys reusable, never resent automatically) only if that queue evidence is clean AND the bucket holds no worker claim or manifest for any key; otherwise they stay uncertain and held. A hold whose evidence was not recorded (today's) is proposed to him as a card with exactly what was recorded and what was not; his yes recodes the rows and takes (RUNPOD.NOT_QUEUED) and releases the hold. After a never-queued close, the next switch-on purges the endpoint's queue before PATCH max=1 so a late-accepted job cannot run. The still redo on a RunPod model runs through the stills rounds (one session, its cap, GPU off after). Rejected: trusting /health completed/failed counters (undocumented window); treating any 5xx as unsent. Proven on fakes; the live retry follows a restart.


**ADR-RUNPOD-STILLS-GATE-BILLING-ORDER — what the first live RunPod round taught (2026-10-09).** Context: the first live stills round re-rolled scene 1 three times because the global sharpness gate rejected five good frames (dark tunnel, sharp subject, soft background), never sent scenes 2-5, and booked the 28-minute cached-model download as billed time. Decision: (1) the gate scores sharpness on tiles with the strongest 5% of pixels removed, read at the 6th sharpest of 112 tiles (floor 30), with a second «fine detail kept» reading (max 48% of tile energy left after a halve-and-restore) so a blurred frame with one hard line, a letterbox or an upscale fails; thresholds measured on the five real stills and their degraded copies (numbers in still_gate.py and its tests); (2) RunPod Serverless time is booked per round as execution + one worker start (the first accepted job's delayTime capped at cold_start_seconds, plus the execution budgets of unanswered chunks before it) + the 1 s idle tail; a later chunk books only a second start it can show; (3) the stills first round carries every scene to buy; re-rolls follow; a scene a cap cut left out goes ahead of re-rolls. Rejected: lowering the global floor (passes blur); booking delayTime whole (charges unbilled downloads to the cap). Kept for his card: the Qwen-Image-Edit-2511 route still waits for scene 1's approved still. Proven on fakes and on the five real stills.

## 2026-10-15 — The model thinks where the vendor keeps it; a picture that exists is not re-judged; an outage is nobody's decision

Three days without a publication, and every cause was the studio talking to itself wrong, not a
provider or a budget. **Thinking.** The adapter told every Ollama model not to think, to keep
`num_predict` for the answer. On Cloud, `num_predict` is no longer sent at all, so the reason for
the flag was gone — and the flag itself broke one model: glm-5.3-flash, told not to think, wrote
its reasoning into the visible answer and never reached the JSON (tens of thousands of tokens,
four episodes and three scripts refused). Probed on the Owner's account, every model asked
natively put its reasoning in the separate `thinking` field and answered the object, in JSON mode
too. Decision: Cloud is asked nothing about thinking; the local endpoint keeps the flag; a caller
that must say so still can. Codex's note of the night («the Owner objects to further parameter
changes») is replaced by the Owner's request of this morning: «problemele cu LLM-uri, parametri
de rezolvat». Rejected: a per-model list of «narrating» models (the studio would learn each one
by losing a day) and keeping the flag with a retry (two long narrations instead of one answer).
**A picture that exists.** The motion step linted every scene's still prompt before buying
motion, including the prompt of a still already bought and approved; a new wardrobe rule then
blocked scene 4 of the serial on the words of a picture nobody was going to buy again, thirteen
walks running. Decision: an approved still's words are judged when the still is bought, not again
when motion is; a scene without an approved still is judged as before. **An outage.** When the
provider refused every model for four minutes, the Director's model-switch probed three
candidates, found all down, and asked the Owner to choose a model — three cards, all refused by
him; the choice of a model is hers and an outage is nobody's decision. Decision: every probe
failing at the provider is declined with «reîncerc la trecerea următoare» and no card. Also
decided: an upload that raises (a row changed under the gate, a file the hash cannot read) is that
film's SKIPPED, not the studio's safe mode; a film that passed quality control and waits unpublished
three days stops holding the next topic; and the night's «no silent shortening» holds only if the
schemas stop refusing what the validators no longer cut — candidates and episodes are validated
through the relaxed schema, the same one structured answers already use. **The route it is bought on.** The night's «never cut a serial prompt to fit» holds only
where the route allows the complete prompt: production's GPU worker does (20 000 characters),
Runway's legacy figure does not (1 000), and a test world on the legacy figure refused every
serial LINT_BLOCKED. Decision: the linter keeps one table of what each connected route allows,
by model id (`prompt_lint.ALLOWANCES`, the worker's workflows seeded with its MAX_PROMPT); a
vendor that allows more declares it there; a model nobody declared keeps the legacy figure.
Rejected: threading a vendor attribute through the sheet, the stills step, the still redo and
the motion state (five lint sites, a dozen signatures, for the same fact).
