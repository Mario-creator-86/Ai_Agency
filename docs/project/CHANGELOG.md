# Changelog

## 2026-10-13 — Prompt path repair: static stills, planned markings, the resumed redo

- The still (image) prompt carries no movement: a clause of the plan that moves the camera is
  left out of the still (its moment stays), a tempo or a span of the clip leaves its clause,
  the serial's first moment the same; the motion prompt keeps all of it. New lint
  `STILL_MOTION` (WARN). The shot writer's and the rewrite's instructions say the rule.
- New `backend/app/media/markings.py`: the objects a plan names that carry their own markings
  (thermometer, gauge, dial, clock, ruler, graduated glass, instrument panel, keyboard…).
  Writing on such an object is no hard limit of the bible: the Director overturns it in one
  look (`second_look`), the stills gate leaves the refusal to her look (`may_be_overturned`),
  clip QC's `look_may_overturn` too, the vision checks are told the instrument keeps its scale
  (`judge_still`, `judge_clip`, the film's picture QC), a re-roll keeps it
  (`positive_instruction`), her rewrite review does not anchor the finding serious
  (`scene_rewrite.hard_limit`), and the still prompt ends «The thermometer keeps its own scale
  and markings; no caption, no logo.» instead of «No text, no logo.».
- A paid redo corrected under the Owner's ask-me rule is bought on his yes: the resumed walk
  no longer corrects (or looks at) the scene again before spending it
  (`runbook.stages._corrected_for_film`).
- Tests: `test_still_prompt_is_static.py`, `test_planned_markings.py`,
  `test_rewritten_still_reaches_the_model.py`, `test_rewritten_motion_reaches_the_model.py`,
  `test_redo_resume_spends_his_yes.py`; `test_director_rewrites_failed_scene.py` now asserts
  the exact rewritten motion prompt reaches the vendor fake. Offline only; nothing proves a
  live vendor or model.

## 2026-10-13 — Private source publication

 prepared a clean source snapshot for a private GitHub repository. Excluded local environments, credentials, databases, storage, caches, outputs, scratch tools, rejected artwork drafts and model weights. Sanitized production-derived fixtures and replaced private operational history with source-focused summaries. Preserved the original application without modifying it. Added CLAUDE.md and a cloud setup guide. Publication validation is recorded in GITHUB_PUBLICATION.md; historical production outcomes are not included.

This summary replaces private operational records only in the GitHub copy.
