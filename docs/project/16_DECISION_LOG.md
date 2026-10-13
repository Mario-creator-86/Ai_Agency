# Architecture decisions for the published source

The source remains local-first, single-owner and loopback-bound. SQLite records, workflow state and committed domain events are authoritative. Durable leases, outbox events, idempotent commands, credentials encryption and Owner STOP/approval/budget rules remain required. The active presentation is the side-view pixel studio; legacy 3D sources remain archival. Treasury and virtual financing are retired from the active interface. Paid vendors are optional existing adapters, never automatic replacements for local integrations. Film QC, research provenance and rights gates remain mandatory. New architectural decisions must document reason, alternatives, compatibility, migration, tests and rollback. The private operational decision history remains only in the original application; this publication summary does not change the indexed normative architecture.

## 2026-10-13 — The Owner's «Scrie episodul» runs the serial's whole ladder for the day

Reason: he pressed «Scrie episodul» in the serial room's «Zile închise»; Marcus wrote «The
Nine-Scene Rewrite» (DRAFT) and the Director never read it («De ce nu-l citește? Nu trebuie
să o facă automat?»): the button called `write_episode` alone, and the reading, the editorial
judgement, the approval under policy and the storyboard lived only in the daily run's serial
stage, which took the draft up at the next run. Decision: a route `POST
/story/logs/{log_id}/tell` and a service `serial_stage.tell_day_now` run `_tell_the_day` —
the stage's own ladder, not a copy — for the one closed day pressed: an unread DRAFT of the
day is read, a refused day is rewritten with its notes while `MAX_DRAFTS_PER_DAY` lasts, a
PASS is approved under the channel's policy and storyboarded, the filming is queued (no media
stage follows a press). The stop refuses in the studio's words; a quiet day, a day that has
its episode or used its drafts, and an episode of another day waiting for him are 409 states;
an answer refused before it was stored is 422, as the write route says it; one answer per
`command_id` (`recall_command`). The backend says where the episode ended (`words`) and the
page prints it, choosing only the tone. Alternatives: running the serial stage itself on the
press (refused: it picks its own day and resumes other days' episodes, and he pressed on one
day); the page chaining `/episodes/write`, `/review` and `/storyboard` (refused: three
requests across minutes of model time, with the editorial judgement, the rewrite and the
policy approval the page's to redo); keeping the bare write (refused: it is the reported
fault). Compatibility/migration: none; `/story/episodes/write` is unchanged and the
`command_record` table already exists. Test impact: `tests/test_serial_tell_now.py` (the
ladder, the limits, the stop, the replay, the route); `frontend/tests/serial_room.test.js`
(the words' tone). Rollback: point the button back at `/story/episodes/write` (`main.js
tellDay`), drop the route and `tell_day_now`; stored `TellDay` command records are inert.
## 2026-10-13 — Money spent again on the same picture needs the Accountant's agreement too

Reason: the Owner («ar fi bine să avem încă un prag de verificare la Nadia, după ce trece de
Director, asta doar când vine vorba de a cheltui iar bani pentru aceeași imagine sau video sau
sunet. Nadia primește: ce se cumpără cu promptul nou, ce era greșit, promptul nou. Atunci și
Sarah și Nadia trebuie să fie de acord că e necesar»; «Nadia și Sarah discută. De la
contabilitate nu ar trebui să ajungă la mine … La mine ajunge doar dacă este peste bugetul
filmului aprobat»). Decision: `economy.repurchase_gate.before_paid_redo`, called by
`_apply_repairs` for a paid redo of a layer the film already paid credits for, after the
correction and before the purchase: Nadia's structured verdict, validated; on REFUSE a
HANDOFF to the Director and her one structured decision (INSIST buys within the ceiling,
ACCEPT_MINOR reuses the overturned path of her second look, CLOSE_SCENE holds the scene);
an unreadable answer buys nothing and holds the scene; the outcome is an event keyed by
film, scene, layer and plan hash, reused by a resumed walk. The ceiling, the daily budget,
the caps, the Policy Kernel, his paid-media rule and the lease are unchanged, and the gate
steps aside where they refuse. Alternatives: a per-redo Owner card (refused: «de la
contabilitate nu ar trebui să ajungă la mine»); gating by paid-redo rounds instead of paid
takes (refused: the first paid redo of a bought still is already money spent again); a
scene-level close (deferred: none exists but his LOCAL_MOVE, which is his; CLOSE_SCENE holds
the scene and her next reading decides). Compatibility/migration: none — a new event type,
no schema change, no new setting; a film whose takes carry no credits (a local model, the
older fixtures) is never gated. Test impact: `tests/test_accountant_gates_the_repurchase.py`;
`test_redo_resume_spends_his_yes.py`, `test_director_rewrites_failed_scene.py` and
`test_director_decides_qc.py` unchanged. Rollback: delete the module and the hook in
`_apply_repairs` (the `repurchase_gate.before_paid_redo` call and its `overturned` branch);
the contracts' three new lines read as advice only.
## 2026-10-13 — The Scriptwriter is briefed on the platform, the judge, the idea and the money

Reason: the Owner («Marcus care scrie scriptul știe că trebuie să fie pentru un short pe
YouTube? Știe că trebuie să atragă vizualizări? Știe că trebuie să aibă un conținut mesajul
lui?»; «Directorul comunică cu fiecare și poate întoarce către el indicații noi? … toți
agenții trebuie să fie conștienți că trebuie să economisim bani și să avem calitate»). The
audit of 2026-10-13: the brief named the length and the claims; the platform, the audience,
the five criteria the Director scores, the thesis she chose, the cover and title rules and
the price of a filmed scene lived in other modules; her REVISE letter went to her own inbox;
the weekly direction was recalled by her alone; nothing he wrote was measured back to him.
Decision: the brief is computed from the studio's own data — the channel record, the judge's
`criteria_lines` and bar, the topic's thesis and scores (inert data), the price table and the
film ceiling (never a guess: no price line when unpriced), `story_performance` under the
analytics' own N ≥ 3 rule — and the hook window is the judge's two seconds, said once. Her
letter is a REQUEST_REVIEW to the writer, resolved on a later PASS of the story; the weekly
«topics» is studio-wide STRATEGY; a `writing` field goes to him as its own HANDOFF; a shipped
story is one AGENT_OPINION on his memory. Alternatives: a model call to summarise the measured
films (refused: the numbers are deterministic and cost nothing); resolving a REJECT letter at
once (refused: it is the reason the story closed, and the ten-newest cap bounds his prompt);
pricing the sheet's per-scene choice (deferred: no storyboard exists at brief time, so the
model `motion_clip_limit` names is priced and named in the line). Compatibility/migration:
none — new keys on `story_performance` rows and on the HANDOFF body, a new optional field
with a default on the weekly answer, contract v7 seeds only roles without a contract (an
edited contract keeps the Owner's text). Test impact: `tests/test_writer_brief.py`;
`test_weekly_review` unchanged (a review without `writing` files four letters as before);
`test_editorial_quality`'s brief tests unchanged (`_write_instructions(30)` still renders).
Rollback: revert the five sections of `_write_instructions` and its call site, the letter's
addressee and `_settle_writer_letters` in `review_story`, `remember_shipped_story`,
`agent_id=None` on the weekly STRATEGY and the `writing` handoff; stored rows keep their shape.

## 2026-10-13 — The serial's words-per-beat band is a recommendation the Director decides

Reason: the Owner («nu trebuie să fie ceva fix, este ceva recomandat, dar nici să respingi
serialul de la asta; pot lua decizii singuri, iar Directoarea este aici pentru astfel de
situații»): «The Ninth Rewrite» (13.10.2026) was REJECTED by the computed checks for a 23-word
beat before the Director read it, and the cover signed that FAIL as hers. Decision: the check
is `advisory` — measured, shown, never a refusal and never a reason to ask the writer again;
the Director is handed the measure under «recommendations» and her verdict decides. A verdict
the computed rules give without her reading is signed `reviewed_by: checks` on the row, the
event, the cover, the list and the feed. Rules of fact and form stay rules: grounding,
privacy, structure, cast, length, concentration, accessibility, language, filmable.
Alternatives: widening the band (refused: any fixed number refuses the same way); making
`length` (45-70 s) a recommendation too (deferred: the short's format, for the Owner to say).
Compatibility/migration: none — a stored review keeps its shape, `advisory` is a new key read
as false when absent, `reviewed_by: checks` appears only on new rejections. Test impact:
`tests/test_words_per_beat_is_a_recommendation.py`, `frontend/tests/serial_room.test.js`;
`test_words_per_beat_are_the_spoken_words_only` unchanged (the measure is the same). Rollback:
drop `advisory` from `_words_per_beat`, the two helpers' use in `review_episode` and
`services._ask_again`, and the `checks` signature; the words of the brief and the page follow.

## 2026-10-13 — The still prompt is one frozen moment

Reason: the Owner («în promptul de imagine nu are ce să caute indicații de mișcare»): the
image model was given camera paths and tempos written into subject, action and environment,
and drew them. Decision: the compiler leaves a clause that moves the camera out of the still
(a moment said before the move stays), takes a tempo or a span of the clip out of its clause,
and does the same for the serial's first moment; the motion prompt is unchanged. Alternatives:
a BLOCK in the lint (refused: a block on a stored prompt makes the sheet LINT_BLOCKED and the
repair orphans bought takes — the lint WARNS instead, as STILL_SEQUENCE does); rewriting the
subject's verbs of motion into states (deferred: a policy change for the Owner to decide).
Migration: none; stored prompts are recompiled only when a scene is rewritten. Test impact:
`test_still_prompt_is_static.py`; existing compiler tests unchanged. Rollback: revert
`prompt_lint.static_clause`/`without_tempo` and their use in `prompt_agent._clauses_of` and
`_still_moment`.

## 2026-10-13 — Writing that belongs to the planned object is not the bible's writing

Reason: the Owner, on the Kelvin film («Nu ai cum să ai un termometru fără scris, grade,
Celsius»): a thermometer's scale was refused as «text lizibil», fail-closed, at every gate.
Decision: `markings.planned_markings` reads the objects that carry their own markings from the
still prompt and the scene's written picture (never the narration alone); for them, writing is
a reading the Director judges — no fail-closed loop in her second look, no blind re-roll at the
stills gate, no serious anchor in her rewrite review — and the vision checks and the still
prompt are told the object keeps its scale. Alternatives: dropping the writing hard limit
altogether (refused: captions, signs, logos and invented lettering stay the bible's);
a free-text judgement by the vision model of «where the writing is» (deferred: the list is
short and literal so the rule stays auditable). Migration: none; a scene with no such object
reads exactly as before (its second-look event carries no `planned_markings` key). Test impact:
`test_planned_markings.py`. Rollback: delete `backend/app/media/markings.py` and the
`expected_markings`/`planned_markings` plumbing; every default is the old behaviour.

## 2026-10-13 — A corrected paid redo is bought on the Owner's yes

Reason: under the ask-me rule, the walk that resumed after his yes corrected the scene again
before spending it (`_correct_before_redo` runs before `redo_plan`), so the approved redo was
refused PROMPT_NOT_CORRECTED (same words) or asked again on a new plan (new words), forever.
Decision: `stages._corrected_for_film` — a director rewrite of the scene newer than the failed
film and than every take of the scene is the correction his yes was asked on; the resume
neither looks nor corrects again, and a correction that turned to the picture buys the still
and its motion as the first walk did. Alternatives: binding the approval to a correction id
(more durable, but a schema change for the approval payload — deferred). Migration: none.
Test impact: `test_redo_resume_spends_his_yes.py`. Rollback: remove the `corrected` branch in
`_apply_repairs`.

This summary replaces private operational records only in the GitHub copy.
