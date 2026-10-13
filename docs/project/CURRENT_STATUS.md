# CURRENT STATUS — State on 2026-10-13

Current proof: this publication was checked offline and proven on fakes only for provider-dependent paths. AGENT_SCENARIO_ACCEPTANCE is a historical acceptance category, not a claim of live production success in this source copy.

## Private source publication (2026-10-13)

This is a source-only publication snapshot. The application is a local, single-owner FastAPI/SQLite media studio with a Vite pixel-office frontend. Existing Director QC and media-repair work needs an audit against the current source and tests. Other development worktrees and their unmerged commits are not included. Production health, balances, credentials, film history and configured accounts are intentionally absent. Do not treat historical mock acceptance as live vendor acceptance.

## Office serial: recommendations and honest signatures (2026-10-13)

Working (proven offline): a beat outside the 8-22 spoken-word band no longer refuses the
episode or re-asks the showrunner; the Director reads it with the measure and decides
(`story.review.failed_rules` / `outside_recommendations`). A rejection the computed rules gave
without her reading is signed by the checks (`reviewed_by: checks`) on the row, the event, the
journal's cover, the episode list and the event feed. Not proven: a live Director's reading of
such an episode (model-dependent).

## Prompt path audit and repair (2026-10-13, branch `claude/compassionate-clarke-qqb9g7`)

Task claim: the Owner's three questions on the media repair loop, read on the source and on
offline fakes (no vendor, no model, no production database): (1) does the prompt the Director
had rewritten after a refused still or clip reach the image and the video model; (2) a still
refused for the digits of the thermometer the scene asks for; (3) movement indications in the
image prompt. Subsystem: `backend/app/media/` (prompt_agent, prompt_lint, scene_rewrite,
still_gate, stills_stage, picture_qc, second_look, qc, assembler), `backend/app/runbook/stages.py`.

Working (proven offline):
- The rewritten still and motion prompts are the ones handed to the vendor fakes on the stills
  step, the test-shot step, the motion step, the paid scene redo and the RunPod batch path;
  take identity, holds, STALE_PLAN refusals and approval hashes all follow the new words
  (`tests/test_rewritten_still_reaches_the_model.py`,
  `tests/test_rewritten_motion_reaches_the_model.py`, the strengthened
  `tests/test_director_rewrites_failed_scene.py`).
- Fixed: a paid redo corrected under the Owner's ask-me rule was corrected again by the walk
  that resumed after his yes, so the approved redo was refused (same words) or asked again
  (new words) and never bought. `stages._corrected_for_film` now spends his yes on the words
  it was asked on (`tests/test_redo_resume_spends_his_yes.py`).
- Fixed: the still prompt is one frozen moment. A clause that moves the camera leaves it (the
  subject's moment stays), a tempo or a span of the clip leaves its clause, the serial's first
  moment the same; the motion prompt keeps all of it. Lint `STILL_MOTION` (WARN) names a
  stored still prompt that still moves; the Video Editor's and the rewrite's instructions say
  the rule (`tests/test_still_prompt_is_static.py`).
- Fixed: writing that belongs to the object the plan asks for (`backend/app/media/markings.py`:
  a thermometer's scale, a gauge, a clock, a ruler…) is no hard limit of the bible. The
  Director decides it in one look, the stills gate hands such a refusal to her look instead of
  a blind re-roll, the vision checks are told the instrument keeps its scale, a re-roll keeps it,
  her rewrite review does not anchor it serious, and the still prompt says «The thermometer
  keeps its own scale and markings» instead of «No text». Writing elsewhere, faces and panels
  are unchanged (`tests/test_planned_markings.py`).

Not implemented / limits: nothing here proves a live vendor, a seeing model or the Owner's
production state; the YuNet model is absent, so face measurement stays NOT_RUN in this copy.
`uv run mypy` reports 32 pre-existing errors in 9 files, identical on the untouched base;
none in the lines changed here.

Tests run: `uv run ruff check .`, `uv run ruff format --check .`, `scripts/check_docs.py`,
`scripts/check_secrets.py`, the changed subsystems' test files and the new ones (all passed),
`uv run pytest -m "not slow"` and the frontend check/test/build — outcomes in the changelog.

Exact next task: watch the first real films on these rules (the Kelvin thermometer scene
first); if the Owner wants the subject's own verbs of motion («wind bends the rice») out of
the still too, that is a policy change of the compiler, not a bug.

This summary replaces private operational records only in the GitHub copy.
