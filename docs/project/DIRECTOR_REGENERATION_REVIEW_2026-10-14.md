# Director: review replacement words before regenerating — 14 October 2026

## Live diagnosis

Kelvin scene 2: the 23:39 request reused the expired request's motion prompt, as a
delivery retry. Once delivered it failed clip QC: the camera revealed a distorted
close-up face instead of keeping the researcher seen from behind. Sarah confirmed that
cause at 23:56:51. The 23:56:52 request added only this automatic sentence:

> The camera's tracking left stays smooth and moderate, and every shape and edge keeps its form from the first frame to the last.

This was a different prompt, but not a prompt reviewed against Sarah's diagnosis.
It also failed QC at 00:01:32: a ghost face, changing apparatus and a profile close-up.
Request IDs: old `62c300bb-777d-418e-9880-5f685cb3a39a`, generic retry
`3c9e1376-b663-414a-a7e6-589d2ea36e64`. Exact recorded request texts are retained in the
auxiliary workspace's `output/kelvin-exact-prompts.json`. Do not call that generic
suffix a successful Sarah/Kael corrective rewrite.

The Zero Script Club scene 4: Sarah approved still `7e4ec124-207e-4915-90a2-dc42356ae06a`
at 00:02:45; motion was submitted at 00:03:11. The JPEG first frame's SHA-256 exactly
matches the request's recorded `source_image.sha256`:
`1f9b63754ac268e49a3ef81cf4269310231a8d662cfc2d04e3852544b056bb05`.
Thus this request did have an approved source image. The approval itself was inconsistent:
Sarah's take look called Nadia's green shirt correct, while later QC read the character
bible's plum blouse and dark violet cardigan. `director_qc.look_entries` provided the
truncated picture prompt, but omitted the scene's complete character bible and shot plan.

Serial rewrites also misunderstood the composer: a Sarah-presence sentence appended after
`then` in Nadia's clause disappeared from the still; long action clauses crowded out the
wardrobe; camera instructions appended to `ending_frame` made that ending ineligible.
The subsequent reviews rejected these compiled prompts before another purchase. At 00:18,
the editor and Director additionally received provider HTTP 429. A provider quota failure
is not evidence that an agent ignored instructions, nor permission to approve a bad prompt.

Director waiting: 111 OPEN messages were found in her inbox, including old October 3
records. OPEN does not by itself prove each letter is answerable: sender/thread turn,
worker-owned tool tasks, prior decisions and model backoff apply. The general Director
job was scheduled every six hours and was overdue during a long GPU walk. Correspondence
was processed only after the worker's group of tasks. No second queue worker was launched.

## Implemented

- `media/qc.py`: the production caller's Director look no longer leads to a mechanical
  firmer/calmer retry. A refusal enters the existing scene-rewrite ladder, including an
  unavailable or ineligible second look. Accepted takes and back-to-still routing remain.
- `media/stills_stage.py`: every proposed reroll of refused stills goes to the same
  brief/editor/review ladder, including technical faults and hard limits. Missing QC
  measurements and vendor non-delivery keep their own outcomes. A hard rule need not be
  overturned to have its prompt diagnosed and corrected.
- The existing ladder requires Sarah's TREATS review before storing replacement prompts,
  releases the hold only on the reviewed package, and checks the generated result for the
  original defect. MISSES, unavailable reviews and unchanged rewrites buy nothing.
- `media/director_qc.py`: take selection now receives the full character bible, in-frame
  cast and subject/action/camera/ending plan beside the candidate and gate reasons.
- `media/scene_rewrite.py`: serial writer/reviewer data states the actual character budget
  and the required action/ending format, with explicit examples that survive composition.
  The global style, length limits and accepted pictures are not silently changed.
- `workflows/director_upkeep.py`, `media/gpu_batch.py`, assembler/still batch callers:
  during an outstanding GPU request, the same worker periodically runs existing free
  Director management and answers one eligible letter. It claims no other paid task,
  respects autonomy STOP/shutdown and existing mail model backoff, and does not turn a
  failure of free work into a failed GPU purchase.
- `config.py`, `main.py`, `workflows/services.py`: regular Director checks and GPU-wait
  upkeep use `STUDIO_DIRECTOR_CHECK_INTERVAL_SECONDS` (default 300). Existing Director
  schedule follows the new interval without activating a paused schedule.

## Verification and activation

New focused regressions: nine regeneration tests, including exact equality between the
motion text shown in Sarah's review and the captured generator request, and seven upkeep
tests, including one real batch-adapter flow on a fake cloud and inactive schedule
preservation. Providers in tests are fakes and no credits are spent.

Workflow, rewrite, register, second-look and motion suites: 312 passed before the upkeep
extension. Upkeep/mail/scheduler/serial/RunPod and Director-look suite: 182 passed.
The latest cadence-specific verification and live restart outcome are recorded in
CURRENT_STATUS.md. Two older scheduler-copy assertions were confirmed to fail on HEAD
and updated to the existing automatic-resume behavior; the real-path picture fixture now
answers the already-existing accountant repurchase gate instead of returning empty JSON.

Do not claim real image/video quality from these tests. Load these changes only with no
outstanding generation. Then read live brief → editor rewrite → Sarah review → actual
provider request → QC. Do not rewrite database decisions or launch a manual paid reroll.

Rollback: remove these new wait-work hooks and the cadence-following argument, restore
the two automatic-reroll branches and the additional take-look/serial composition data.
Keep the earlier terminal-delivery-routing fix unless separately reverted. This task does
not commit, push, publish, change Owner STOP or raise spending limits.
