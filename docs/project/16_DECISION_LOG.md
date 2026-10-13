# Architecture decisions for the published source

The source remains local-first, single-owner and loopback-bound. SQLite records, workflow state and committed domain events are authoritative. Durable leases, outbox events, idempotent commands, credentials encryption and Owner STOP/approval/budget rules remain required. The active presentation is the side-view pixel studio; legacy 3D sources remain archival. Treasury and virtual financing are retired from the active interface. Paid vendors are optional existing adapters, never automatic replacements for local integrations. Film QC, research provenance and rights gates remain mandatory. New architectural decisions must document reason, alternatives, compatibility, migration, tests and rollback. The private operational decision history remains only in the original application; this publication summary does not change the indexed normative architecture.

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
