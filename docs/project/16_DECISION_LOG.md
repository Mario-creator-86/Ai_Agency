# Architecture decisions for the published source

The source remains local-first, single-owner and loopback-bound. SQLite records, workflow state and committed domain events are authoritative. Durable leases, outbox events, idempotent commands, credentials encryption and Owner STOP/approval/budget rules remain required. The active presentation is the side-view pixel studio; legacy 3D sources remain archival. Treasury and virtual financing are retired from the active interface. Paid vendors are optional existing adapters, never automatic replacements for local integrations. Film QC, research provenance and rights gates remain mandatory. New architectural decisions must document reason, alternatives, compatibility, migration, tests and rollback. The private operational decision history remains only in the original application; this publication summary does not change the indexed normative architecture.

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
