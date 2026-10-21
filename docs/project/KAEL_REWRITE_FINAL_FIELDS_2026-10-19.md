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


## Activation and interrupted session

Scoped source commit44fe99e. Added36 structured/audit and33 sheet-repair checks after the seven-suite run:200 relevant tests passed total. Online backup studio-20261019T053043Z.db (244137984 bytes, SHA2566b1245fdb0e3338aad1a5abb627246d59b1a81e57a175ddf17be0fb0afc44402). First controlled stop finished08:34:10 Europe/Bucharest; normal hidden launcher32224 started08:34:26 with the fix. Worker resumed serialb74270c6 scene20 before Supernova. A second controlled stop requested while GPU verified off/no submitted takes drained that model call, then ended08:57:14. No force/CTRL_BREAK fallback. The voice turn was interrupted before the planned repair/start, so the server stayed stopped until the next Owner status request at09:23. This was an unfinished maintenance sequence, not evidence of production running.

At09:24 the Owner-requested real corrections were started under the exclusive worker lock and film lease, using the unchanged normal Director→Kael→Sarah→transaction services, scoped to motion scenes15/23. No evaluation or model probe, manual final text, direct SQL mutation, policy/budget change or paid media/publication action. The maintenance wrapper always starts the normal hidden launcher in finally, including a failed repair, so conversation interruption does not leave the stop without its paired restart. At09:25 the actual v8 scene15 rewrite is RUNNING; acceptance is pending. No scheduled monitoring was re-enabled.

Operational artifacts: output/kael-rewrite-contract-2026-10-19/{pre-activation.json,start.json,live-progress.json,repair_requested_scenes.py,repair_and_restart.py,requested-repairs.json,restored-server.json}. Some receipts appear only when the corresponding stage completes. Preserve current execution rather than re-running either driver.


## Completed — real acceptance, 19 October 2026

Both Owner-requested motion corrections completed through normal production services, not test actors:
- Scene15: saved09:25:48 Europe/Bucharest, event41602; rewrite2ef418c8-57be-40e2-9284-121cbd238ea9, Sarah38776107-5098-482d-9a5b-8090019c8d34, verdictTREATS.
- Scene23: saved09:29:30, event41617; rewrite183f231f-3615-49b3-beaf-3efadcb764c9, Sarah36e857a8-aa33-4d64-bbfd-f5aee228d722, verdictTREATS.

Both actual rewrite runs use scene-prompt-rewrite-v8, both saved packages are editor_final_v1, each motion changed, both paid stills match their pre-activation SHA256 byte-for-byte. No manual prompt/approval/data patch. Maintenance wrapper exited0 and started normal hidden launcher20084 automatically at09:29:30 (06:29:30UTC). At11:12 fresh /health/live200 and /health/ready200 HEALTHY/BUSY, no problems. No background monitor was enabled.

The exact two-scene defect is complete, claim released. Production publication remains unconfirmed: Supernova has40 approved still scenes and no newer motion takes; last continuation at10:08:50 recorded WAITING/"ladder did not finish". Scene8's audit requested a camera contradiction correction, and its newest saved prompt now explicitly uses static camera; a fresh purchase audit/continuation has not yet accepted that current corrected prompt. Do not report the older rejected tracking text as still current. The worker is currently auditing the other serialb74270c6 motion prompts. No reliable publication ETA follows from the two repaired prompts. Evidence accepted-scenes.json and restored-server.json.
