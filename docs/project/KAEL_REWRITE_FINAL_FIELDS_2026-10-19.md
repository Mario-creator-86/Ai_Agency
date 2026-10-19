# Kael rewrite final-field contract — 19 October 2026

Owner request: diagnose and fix Supernova motion scenes 15 and 23, then verify actual rewrites and Sarah review.

## Cause and evidence

The final-text validator from the legacy migration update was correct, but `_REWRITE_INSTRUCTIONS` still showed the old subject/action/motion JSON example before the final-text addendum. All scenes received those conflicting instructions. Scene15 returned four visible answers: legacy fields; then both final fields; then legacy fields again; then only still_prompt. Scene23 returned two legacy-field answers, both without either final prompt. These are actual stored `agent_run.output_text` answers, not a failure to reach the scenes. The one complete scene15 answer entered the existing lint correction path; later answers omitted the required motion_prompt again. No missing prompt has been filled from planning notes.

`shot_schema(editor_final=True)` also inherited all the legacy optional planning fields and normalized strings through `_coerce`, contrary to exact vendor-text ownership. A motion rewrite could therefore lose double spaces/newlines even in its echoed paid still.

## Change

- One compact final-text example, specialized for still, legacy motion migration or already-final motion; no competing old response example.
- Separate final-response schema with required camera_move/motion_prompt and required still_prompt only when the repair needs it. Exact strings are preserved; objects/lists cannot be flattened into vendor text. No draft-motion fallback.
- Legacy schema retained only for explicitly legacy callers. Template scene-prompt-rewrite-v8.
- Existing lint, exact paid-still check, review, transaction/stale checks, spending limits and purchase approval remain in force.

## Validation before activation

Baseline: 35 relevant tests passed. New reproductions: 9 failed and3 passed before the change. Final seven-suite run: 131 passed, including14 response-contract tests and scripted model→structured parser→Sarah review→transaction checks. Refused review stores nothing. No real model/provider call was used for tests. Ruff check/format, scoped mypy (--follow-imports=silent), docs inventory/hashes and diff whitespace passed. Ordinary mypy followed imports and reported21 existing errors in6 other modules; no scene_rewrite error.

Evidence: output/kael-rewrite-contract-2026-10-19/tests.xml.

Activation and actual scenes15/23 acceptance remain pending. Do not infer visual QC or publication from text acceptance. Scheduled monitoring remains paused.
