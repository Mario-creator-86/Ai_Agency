# Kael → Sarah → provider: legacy rewrite audit, 18 October 2026

## Evidence and cause of scene 19

Read-only SQLite transaction against storyboard `1efc3319-44ac-416f-a75a-3217ca9c2070`, Supernova Surprise. No application startup, database write, provider call, paid generation or publication was initiated. Receipt: `output/scene19-readonly-proof-2026-10-18.json` (local/private).

The current bible explicitly says `face_policy=ALLOW`, but its scene-19 continuity rule still requires three people from behind. The current legacy package has no final-format marker, describes backs of heads with medals in front of chests, and accumulates mutually contradictory exclusions: rear views, frontal views, visible faces and their opposites. Narration only says three members of the teams received Nobel Prizes; it does not require a rear view.

Event `f9236e43-ef73-43be-93b8-9407f41e5c60`, `media.owner_physical_prompt_repair`, at 2026-10-18 10:26:11 UTC (13:26 Bucharest) records an **Owner-approved frontal/three-quarter correction**, with medals in front of jackets. It changed the current package but did not update the bible. A later Sarah audit explicitly rejected the frontal wording because the old plan/avoid/bible demanded rear views. Subsequent rewrites returned to backs of heads. The latest scene-19 event is a still `TOOL_DEFECT`; its reason invokes legacy compiler style and repeated-pose rules. At inspection there is one approved still and one rejected motion take.

Code causes:

1. `rewritten_package` and `serial_rewritten_package` chose direct finals only for already marked packages. Every legacy rewrite kept the legacy composition path and merged historical exclusions.
2. `_data` omitted `face_policy` from the visual bible delivered to brief/rewrite agents, while supplying old continuity and avoid prose. Rewrite review also lacked the full current policy context.
3. Legacy field-coverage validation still judged final prose against planning fields.
4. The sheet/still reader normalized whitespace; still generation added reroll/reference sentences and rebuilt negative prompts. Runway fitted/normalized prompts again. Text-to-video could prepend the picture description. These violated the final-text contract after review.
5. Approval identity covered positive words alone, allowing negative/policy changes to reuse an older positive-text approval.

## Implementation

| File | Functions / responsibility |
|---|---|
| `backend/app/media/visual_policy.py` | `effective_policy`, `orientation_conflict`, shared policy note: conservative whole-clause retirement under explicit ALLOW/REQUIRE, physical contradiction diagnosis, preserve unrelated and ambiguous artistic rules |
| `backend/app/media/scene_rewrite.py` | `scene_context`: recover existing Owner plan receipt without copying old provider prompts; `_data`, `director_brief`, `review_rewrite`: shared policy/authority and exact final fields; `shot_schema`, `_editor_rewrite`, `rewrite_scene`: require complete Kael output; `_direct_rewritten_package`, both rewrite routes: validate direct prose, migration metadata and historical still preservation; `_lint_blocks`: no legacy field-coverage requirement for finals |
| `backend/app/media/final_prompts.py` | `validate_final`, `editor_compiled`, `editor_motion_for`: exact validation, independent layer caps, generic worker ceiling versus selected vendor limit, no shortening |
| `backend/app/media/prompt_agent.py` | final-output schema accepts the worker ceiling; selected route caps applied per layer; `incomplete_plan_fields` leaves final prose to final validation |
| `backend/app/media/prompt_audit.py` | `_ask`, `final_audit_schema`: actual final prose including negative prompt, policy/authority, actionable refusals; `approval_digest`, `purchase_approval_gaps`: current words, negative and bible bound to explicit Sarah approval; repeated-refusal note no longer invents compositor blame |
| `backend/app/media/shooting_sheet.py` | `_sheet`: exact final still text, no legacy field-coverage validation |
| `backend/app/media/stills_stage.py` | `_read_scenes`, `still_negative`, `_prompt`, `_buy`: exact final prose and negative channel, no injected reroll/reference sentences; pass exact mode to supported adapters |
| `backend/app/media/assembler.py` | `motion_request`: exact final motion without prepending still; pass final-format marker |
| `backend/app/providers/runway.py` | `fit_prompt` exact mode, image and video adapters: preserve approved text and refuse an unsupported cap before submit; optional negative only on declared channel |

## Migration contract

No startup sweep or database migration. Reading an old storyboard does not mark it migrated. Only an explicitly requested open LIVE rewrite invokes the new path. Kael must provide both complete valid final prompts on the first migration, including a byte-for-byte echo of the existing still on motion-only migration. A missing historical still may use its existing `visual_prompt`, never fabricated text. A changed still on a motion-only repair is refused.

The candidate is not committed until Sarah's rewrite review returns TREATS. Closed-film and stale-package checks are repeated under the existing write lock. The existing `media.prompts_rewritten` event retains the complete original package, old/new prompt strings, brief, run and review provenance. Migration metadata records retired original restrictions and reasons. Existing takes, charges, QC, approvals and publication rows are not rewritten. Reapplying the same package transformation is idempotent. A changed prompt, negative or bible requires a new current purchase approval.

ALLOW permits faces; it does not force frontal compositions. Recognized blanket bans are neutralized in agent context and the rewrite candidate. Mixed/scene-specific artistic clauses are preserved for editorial resolution rather than deleted heuristically. A rear-view/chest-medal contradiction without an approved replacement intent returns PLAN_CONFLICT. An existing Owner plan receipt or Sarah's `editorial_visual_intent` provides the common replacement intent, and Sarah must still review Kael's actual candidate. The old bible remains historical data; the explicit current scene intent takes precedence over its superseded orientation only. Other location, people, lighting and narrative requirements remain in context.

Sarah's final audit refusal requires a concrete diagnosis, an exact offending quote or an explicitly missing requirement, change, keep, and responsible source (Kael, plan, editorial policy or code). Invented quotations fail validation. Existing safeguards hold after three repeated equivalent findings or six consecutive refusals, record TOOL_DEFECT and prohibit purchase; they do not fabricate approval or relax QC.

## Verification and limits

Tests use temporary databases and simulated model/media providers. The new suite covers migration on rewrite, incomplete output, motion-only historical still preservation, selective rule retirement, valid artistic orientation, idempotence, scene-19 contradiction and approved replacement intent, exact audit/transport, per-layer limits, approval invalidation, repeated-refusal diagnosis, existing Owner receipt propagation, and unchanged paid/cost/job/publication rows on accepted/rejected/invalid migration. Existing actor fixtures now return explicit finals and name final fields; tests that previously expected a compositor lock now require a false lock to fail closed.

Final verification: **244 passed across 12 relevant modules**, including **25 new migration/contract tests**; then **112 affected tests passed again** after the final context changes. There are 244 distinct tests across those reports, not 356. Ruff passed on all changed Python modules/tests; scoped mypy passed on four modules; whitespace and architecture/document inventory checks passed. XML: `output/legacy-final-final-tests.xml`, `output/legacy-final-current-contract-tests.xml`. Intermediate runs deliberately reproduced missing migration, synthetic fallback, legacy field validation, negative-prompt injection and transport concatenation before repair. Initial relevant baseline: 38 passed; a pre-final nine-module regression run passed 155. No full repository suite was run.

**Live acceptance remains pending.** The database still contains the old scene-19 package; this work does not apply the candidate or restart the application. The Owner-approved frontal correction is evidenced, but no current `editor_final_v1` candidate from Kael, Sarah approval of that candidate, provider delivery or visual QC has been executed here. These must occur through the normal application after controlled integration/restart. An absent/invalid model response, impossible plan, unsupported vendor cap, unavailable Sarah review, stale package or closed film remains blocked with its existing explicit reason. No claim of live visual resolution or paid-provider readiness is made from mocks.

Branch: `codex/legacy-editor-final-audit-20261018`. Rollback: revert the scoped commit before activation; do not erase historical events or restore a live database over concurrent work. No push or publication is part of this task.
