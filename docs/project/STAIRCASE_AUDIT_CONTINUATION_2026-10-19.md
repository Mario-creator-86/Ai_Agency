# Prompt-audit continuation after a bounded walk — 19 October 2026

Owner: «ar trebui sa meargă mai departe nu sa se oprească la limita de pași».

## Confirmed cause

Supernova1efc3319 scene8: Sarah accepted Kael's static-camera correction at10:08:50 Europe/Bucharest, but the correction consumed the last iteration of `_walk_staircase`'s `range(len(SHEET_STEPS)+1)`. Its generic fallthrough returned WAITING without a refusal classification or continuation. The caller consequently wrote an Owner-wait letter, although it was the Director's next purchase audit that was owed. The limit counted both paid steps and successfully rewritten/rebuilt sheets.

## Change

Keep bounded walks for fairness and loop control. After valid progress exhausts the walk, classify the unfinished audit NEEDS_PROMPT_APPROVAL and persist one normal FILM_CONTINUE with `_ladder_continues`/`queue_film_continue`. The next walk rebuilds the current sheet and audits the exact current words before its ordinary purchase gate. The current Owner-letter path already suppresses letters for that Director-owned refusal; no new Owner decision is invented.

A repeated sheet hash after a claimed rewrite stops before another model call and does not queue an endless identical continuation. STOP/shutdown is checked before each iteration and before scheduling. TEST/DEMO never queue production continuation, including when a fixture's policy environment differs. Current review, budget, approval, mode, closed-film, purchase lease and render-cap rules remain unchanged.

## Verification

Six initial reproductions failed before the change, then passed. Final six-module suite:91 passed, including10 new continuation tests: persisted/replayed handoff, resumed fresh audit before purchase, no-progress loop guard, TEST/DEMO isolation, STOP and retained budget/payment/mode refusals. Existing bounded free walks remain green. Ruff check/format, scoped mypy and documentation/whitespace checks pass.

Broader tests exposed pre-existing old fixture failures:2 in test_kael_sarah_offline_flow (old positive-only digest versus current bound approval),3 encountered in test_daily_run_stages, and7 in budget/mode modules (missing current Sarah approval stops those tests before their old expected gate). All3+7 were reproduced in a separate process with the exact pre-change stages source; the2 offline failures were observed before any implementation edits. No approval gate or fixture was weakened to hide them. Baseline XMLs and final.xml are in output/staircase-continuation-2026-10-19/.

## Activation pending

Current server is producing17 serial motion clips on GPU. Do not interrupt paid generation. Activate only in a verified GPU-off/no-submitted window, using a paired graceful stop/start wrapper that restores the normal hidden launcher in finally. Queue the already-stalled Supernova through the normal durable queue service if it has no pending continuation; no live SQL patch, forced review, paid probe or manual publication. Actual queued/claimed work and fresh server health must be recorded separately from offline tests. Scheduled monitoring stays paused.
