# 12 — RunPod provider: serverless endpoints, GPU sessions and guard, batches, pods, pricing, weights, setup

Mapped at commit 20abffd (first mapped at b00083c, refreshed 2026-10-12).

> Files (22, 9,788 lines, 361 functions):
> `backend/app/providers/runpod/__init__.py` (1), `adapters.py` (427), `batch.py` (2,043), `client.py` (169),
> `compute.py` (78), `config.py` (448), `endpoint.py` (392), `errors.py` (21), `gpu_guard.py` (354),
> `gpu_session.py` (1,675), `jobs.py` (218), `mock.py` (134), `models.py` (119), `pods.py` (1,372),
> `pricing.py` (137), `provider.py` (652), `router.py` (159), `s3.py` (192), `setup_steps.py` (738),
> `telemetry.py` (54), `weights.py` (321), `wiring.py` (84).
> Mapped 2026-10-12 from commit b00083c plus the working tree (no uncommitted change in these files at
> mapping time; the last commit touching them is c529061, 2026-10-12 17:04 +0300). Adversarially
> re-verified against HEAD 3d49e9a (still no uncommitted change in `backend/app/providers/runpod/`):
> line numbers, constants, gates and decided-by labels checked against the code; corrections applied.
> No commit from b00083c to 20abffd touches `backend/app/providers/runpod/`; citations into the
> media files that changed (`assembler.py`, `stills_stage.py`, `picture_qc.py`) give their 20abffd lines.

## In one paragraph

This package is the studio's only path to paid GPU media generation on RunPod. It turns the media
stages' requests (stills, the hero test shot, motion clips, one-scene redos) into **rounds**: one
RunPod Serverless `/run` job (contract `amn.batch.v1`) carrying every item of the round, sent only
inside a **GPU session** that switches the one RTX PRO 6000 worker on (`workers.max = 1`) for the
paid step and off right after (purge queue, cancel, `workers.max = 0`, verify OFF). Each item keeps
its own durable journal row (`cloud_generation_job`) and idempotency key, so a crash, a lost answer or
a retry never buys the same item twice; results are collected from the Owner's S3-compatible bucket
(manifests written by the worker) and checked by sha256 before they land under the media root. A
**GPU guard** (boot, a 60 s / 600 s loop, shutdown) forces off sessions no step will close and
switches off any endpoint found able to bill with no paid step open. The package also prices the
models (estimates from `config/runpod_models.json` at a 4.00 USD/h budget rate), checks which model
weights a worker really loaded, runs the Owner-approved one-time **copy pod** that fills the Owner's
private Hugging Face mirrors, and serves the Owner's GPU switch page, «Oprește GPU acum» button,
«RunPod pornit» switch and read-only setup checklist. **No language model is called anywhere in
these files**: every decision here is deterministic code, the Owner (button, switch, cards), config,
or a vendor answer.

## Why it exists

- **Per-second billing, «off immediately».** The Owner, 2026-10-08: «trebuie sa se opreasca imediat
  dupa, nu la 30 sec. Sunt taxat la secunda, deci trebuie oprit imediat dupa generare» (quoted in
  `backend/app/providers/runpod/config.py:6`, `batch.py:3`, `gpu_session.py:3`). This is why
  `idle_timeout_seconds` is 1 (`config.py:133`), why a round is ONE batch job so models load once
  (`batch.py:1-8`), and why every session closes in `finally` (`gpu_session.py:1186-1204`).
  Decision log: ADR-RUNPOD-SERVERLESS-ONLY, ADR-GPU-OFF-IMMEDIATELY, ADR-RUNPOD-BATCH-ROUNDS
  (`docs/project/16_DECISION_LOG.md`, section «RunPod Serverless, phase 1», line 4190 onward).
- **Off is never an autonomous act.** «Oprirea GPU-ului nu este o acțiune autonomă: nu cheltuie, doar
  oprește cheltuiala» — ADR-GPU-OFF-ALWAYS, the dated amendment in
  `docs/architecture/51_AUTONOMY_MODE_SEMANTICS.md:207`. So `force_off` and the guard never consult
  the Policy Kernel (`gpu_session.py:25-27`, `gpu_guard.py:3-8`), and the kernel answers
  `infra.gpu_off` ALLOWED before every other check (`backend/app/services.py:1479-1482`).
- **On only inside an approved paid step.** ADR-GPU-ON-IN-STEP-ONLY: the kernel's `infra.gpu_on` (T2,
  `services.py:516`) is allowed only for a paid media step that would itself run now, and only when
  the Owner accepted the card «Agenții pot porni singuri GPU-ul RunPod în pașii plătiți aprobați?»
  (`services.py:1352-1407`, `decisions/sources.py:315`).
- **RunPod forgets results after 30 minutes**, so outputs go to the Owner's bucket through presigned
  URLs (ADR-RUNPOD-BUCKET; `s3.py:1-17`, `config.py:9-10`).
- **Money incidents that shaped the refusal logic** (all 2026-10-09/10, cited in docstrings):
  - the first live stills `/run` failed in 0.12 s with no job id; the items stayed uncertain and the
    film could not move → the close-time proof `BatchRun.prove_unsent` (`batch.py:730-755`,
    ADR-RUNPOD-UNSENT-PROOF);
  - a paused-endpoint 409 «Endpoint is paused (max_workers=0)» travelled up raw at 17:24 UTC and the
    sheet booked a round RunPod never queued, writing the Owner «s-a oprit după ce a plătit» → the one
    list `refused_unqueued` and the paused retry ladder (`batch.py:32-39`, `batch.py:160-198`,
    `batch.py:1463-1477`);
  - a «database is locked» (REL-01) while reserving or waiting turned a never-sent round into a
    booked purchase → `JOURNAL_UNWRITABLE`, `WAIT_UNREADABLE`, best-effort refusal writes
    (`batch.py:1434-1446`, `batch.py:1533-1543`, `batch.py:1747-1758`);
  - a 28-minute cached-model download (unbilled by RunPod) was booked as 2,074 s / 2.3 USD while
    RunPod charged 0.27 USD → `billed_seconds` books execution + at most one cold start + idle tail
    (`batch.py:1047-1050`, ADR-RUNPOD-STILLS-GATE-BILLING-ORDER);
  - journal rows of 6.7 MB held base64 pictures → pictures kept as `{sha256, bytes, mime}`
    (`jobs.py:99-109`, ADR-JOURNAL-NO-PICTURES).
- **The Owner's stop must hold.** 2026-10-12 16:52:08 the Owner pressed «Oprește GPU acum» during a
  Director repair; 25 s later the same walk opened a new session and bought the same clip again →
  `OWNER_HOLD_EVENT` (`gpu_session.py:761-772`; `docs/project/CHANGELOG.md:5`;
  `docs/project/CURRENT_STATUS.md:41`).
- **Weights live in RunPod cached models fed from the Owner's private HF mirrors**, and RunPod's REST v2
  has no field to set or read an endpoint's cached model → the studio checks what each result says it
  loaded (`weights.py:1-25`, ADR-RUNPOD-CACHED-MODELS, ADR-RUNPOD-WEIGHTS-CHECK) and fills the mirrors
  once with a capped CPU pod started only by the Owner's card (`pods.py:1-39`,
  ADR-RUNPOD-MIRROR-COPY, ADR-RUNPOD-COPY-DISK).
- **The Owner no longer edits `.env`**: «RunPod pornit» lives on the integration row
  (`setup_steps.py:1-23`, ADR-RUNPOD-OWNER-SWITCH).
- Origin: ADR-RUNPOD-ADDITIONAL-PROVIDER (2026-10-07) — reuse the existing media interfaces, add only a
  durable submission journal (migration 0055) and translations inside `app.providers.runpod`.

## Who decides here

| Decision | Decided by | Where | Rule / check / threshold |
|---|---|---|---|
| May a paid step switch the GPU on at all (before the Owner's yes is asked)? | CODE_RULE (+ OWNER inputs) | `gpu_session.py:701-742` `precheck` | Mock passes; Owner hold → `OWNER_HOLD`; not Serverless / no endpoint for purpose → `NOT_CONFIGURED`; no bucket → `NOT_CONFIGURED`; card «Agenții pot porni…» not accepted (`allow_infra_actions`) → `BLOCKED_INFRA_DISABLED`; mirror repo/revision unknown under `cache` → `WEIGHTS_NOT_READY`; weights card open/kept off → `WEIGHTS_MISMATCH` |
| Owner's «Oprește GPU acum» holds every paid step | OWNER (button) | `router.py:66-118`; `gpu_session.py:775-808` | Newest `runpod.owner_hold` event `{on}` wins; unreadable → treated as held (fail closed, `gpu_session.py:788-790`); lifted only by the card option «Permite din nou pașii plătiți» (`decisions/producers/gpu_hold.py:85-92`) |
| Switch the GPU on for this step | CODE_RULE: Policy Kernel `infra.gpu_on` | `gpu_session.py:829-843`, `937-942`; kernel `services.py:1352-1407`, `1512-1518` | First the kernel's general refusals apply to `infra.gpu_on` (T2): STOP AUTONOMIE → `BLOCKED_STOP` (`services.py:1491-1495`), safe mode (allows only ≤ T1, `services.py:532`) → `BLOCKED_SAFE_MODE` (`1505-1510`). Then `_gpu_on_verdict`: step action must be a `PAID_MEDIA_STEPS` step; `allow_infra_actions` true; the step's own `may_act` allowed, or NEEDS_APPROVAL with the Owner's APPROVED, unexpired (or consumed) approval for that action, film and `plan_hash`, or the Owner's own press with a status in `OWNER_PRESS_PASSES` (= {`BLOCKED_MODE`, `NEEDS_APPROVAL`}, `media/services.py:1821`). Asked with `ask_owner=False`, rolled back; a refusal raises `GpuSessionRefused` with the kernel's status (default `BLOCKED_NOT_IN_STEP`) |
| «RunPod pornit» switch read at the moment of switch-on | OWNER (switch) | `gpu_session.py:811-826`, `973-986` | Integration row's `enabled` NOW (not the step's cached adapter), under the endpoint lock; unreadable config → treated as OFF (`RUNPOD_OFF`); no integration id or no `runpod` row → not read, the open goes on (`814-822`) |
| Switch «RunPod pornit» ON | OWNER, gated by CODE_RULE | `setup_steps.py:167-208` | ON only when integration status is `VERIFIED` (else HTTP 409 with the reason); OFF always allowed and runs `force_off(OWNER_OFF)` + copy-pod stop |
| One GPU at once | CODE_RULE | `gpu_session.py:943-971` | A live session on another endpoint → poll every 5 s up to `gpu_busy_wait_seconds` (600) then `GPU_BUSY`; two sessions on the same endpoint share it |
| Purge the queue before switching on | CODE_RULE | `gpu_session.py:987-1000`, `454-495` | When a session on this endpoint closed within the longest job ttl had items booked never-queued (`not_queued` rows), purge first so a late-queued job never runs on the new GPU |
| Switch-on PATCH failed | CODE_RULE / EXTERNAL | `gpu_session.py:1001-1031` | Any failure → session `FAILED_OPEN`, compensating `workers.max=0` if no other live session, step refused `COMPUTE_NOT_READY` (unsent, nothing spent) |
| Which pictures a still model receives | CONFIG (`config/runpod_models.json` `reference`) + CODE_RULE | `batch.py:320-353`; `models.py:106-119` | No binding + pictures → `REFERENCE_NOT_ACCEPTED`; more than `max` → `TOO_MANY_REFERENCES`; fewer than `min` → drawn by `text_model` (or `NEEDS_REFERENCE`) |
| Is the model one the worker knows | CODE_RULE | `batch.py:1402-1408` | Real (non-mock) rounds only: `contract.WORKFLOWS[model][0] == operation` (`backend/runpod_worker/contract.py:38-43`: Qwen-Image-2512, Qwen-Image-Edit-2511, LTX-2.5, Wan-2.2-LightX2V), else `UNKNOWN_MODEL` before anything is sent; the mock skips the check |
| SEND / RESEND / TRACK / new attempt for each item | CODE_RULE | `batch.py:456-532` | Key = sha256(target, project, scene, attempt, op, candidate); open row same payload with job id → TRACK; uncertain or reserved-never-sent → RESEND same key; proven unsent/HTTP refusal → reuse key; used-up row → next attempt (≤ 1000 tries); open row different payload → `IdempotencyConflict` → `BatchRefused IDEMPOTENCY_CONFLICT` |
| Chunking and RunPod per-job policy | CONFIG + CODE_RULE | `batch.py:402-429` | per chunk = min(32, (2400 − 120) // item budget) → 12 stills or 2 clips; `executionTimeout` = min(2400, 120 + n × budget) s (≥ 5 s); `ttl` = that + 900 s queue + 3600 s cache wait |
| Retry a `/run` answered «paused» | CODE_RULE / EXTERNAL | `batch.py:1653-1724` | Only 409 with «paused»/«max_workers»; waits 1, 2, 4, 8, 15 s then every 30 s, total ≤ `paused_wait_seconds` (180); session renewed and step stop read before and after each wait |
| Was a failed `/run` a refusal (nothing bought) or uncertain? | CODE_RULE on EXTERNAL status | `batch.py:184-198` | Proven refusal: unsent, or answered 400/401/403/404/413/422/429, or paused 409; anything unanswered or another status → `SUBMISSION_UNCERTAIN` |
| Stop sending further chunks | CODE_RULE (+ OWNER via button/stop) | `batch.py:1513-1546`, `1912-1933`, `2024-2028` | Before each chunk only the GPU session is checked (`_wait_ended(session, None, renew=False)`, `1914`): not OPEN (`GpuForcedOff`: Owner button, guard, shutdown) → `GPU_FORCED_OFF`, unreadable → `WAIT_UNREADABLE`. The step's own stop (`should_stop`) is NOT read between chunks (comment `1912-1913`); it is read by `media/gpu_batch.py` before each round (`gpu_batch.py:354-367`) and, inside a round, only during a paused-409 wait (`_post_run`, `1693`, `1702`) → `STOPPED`, which ends that chunk and sends no later chunk. The rest is marked `FAILED/UNSENT` at 0 cost; the refusal is raised only if nothing was sent and nothing is uncertain |
| Refuse the studio's own malformed request | CODE_RULE | `batch.py:1950-1965`, `1866-1867`, `1874-1897` | `contract.validate_input` fails → `REQUEST_INVALID`; a clip item without its first frame → `NO_FIRST_FRAME`; a picture upload to the bucket fails → `INPUT_UPLOAD_FAILED`; nothing sent in each case |
| Accept an item's result | CODE_RULE on EXTERNAL output | `batch.py:1283-1348`, `1228-1229` | Echoed idempotency key must match; sha256 must match; MP4 must contain `ftyp` in first 32 bytes; else `RunPodProtocolError` → item `BAD_OUTPUT` (fails alone, `batch.py:905-910`) |
| Item cost booked on the journal row | EXTERNAL (worker `gpu_seconds`) × CONFIG (rate) | `batch.py:1316-1323`, `1235-1243` | `gpu_seconds × hourly_rate / 3600` (0 in mock) |
| Round billed seconds | CODE_RULE on EXTERNAL `/status` times | `batch.py:1009-1067`, `662-691`, `1114-1125` | First job: execution + min(delayTime, cold start + unseen budgets) + idle 1 s; later chunk: execution + only the unexplained wait (≤ start + idle + unseen); an unanswered chunk with an unreadable budget makes `unseen` None and the whole wait counts; apportioned to items by GPU seconds (`billed_seconds_value` only, `cost_value` untouched) |
| Item RunPod forgot (404) with no manifest | CODE_RULE | `batch.py:1183-1190` | `EXPIRED_UNDELIVERED`, row FAILED with `cost_value "0"` |
| Item the worker's time guard skipped | EXTERNAL + CODE_RULE | `batch.py:1217-1227` | `SKIPPED_TIME`, cost 0 |
| Prove an uncertain `/run` queued nothing | CODE_RULE | `batch.py:360-391`, `730-824` | Only when: not shared, queue read before purge with inQueue = inProgress = running = 0, purge removed exactly 0, OFF verified, no other overlapping session, and the bucket holds neither `claims/<key>` nor `manifests/<key>` for any item → `FAILED/UNSENT` at 0 cost; anything less leaves them uncertain |
| Wrong weights on an endpoint | CODE_RULE on EXTERNAL worker report | `weights.py:197-225` | Error codes `MODELS_MISSING` / `WRONG_REVISION` / `MODEL_REVISION_MISMATCH`, or (under `cache`) `weights_revision` ≠ expected; no revision reported → not called wrong |
| Close the session / switch off | CODE_RULE | `gpu_session.py:1078-1183`, `576-657` | Other live session on the endpoint → only cancel own unfinished jobs, GPU stays on; else purge, cancel open jobs, PATCH max 0, verify OFF within idle + grace (61 s) |
| What counts as OFF | CODE_RULE (from RunPod's billing doc) | `endpoint.py:99-107` | `workers.max == 0` and `running == 0` and `inProgress == 0` and `inQueue == 0`; `idle` ignored |
| Tell the Owner the off was not verified | CODE_RULE | `gpu_session.py:674-695` | Event `runpod.gpu_off_unverified` + letter «GPU-ul RunPod nu a confirmat oprirea» (not for `OWNER_OFF` in `force_off`, `gpu_session.py:1345`) |
| Force off sessions nobody will close | CODE_RULE | `gpu_guard.py:103-146` | BOOT: rows of another process → `GUARD_ORPHAN`; TICK: past `expires_at` (opened + 4 h) → `GUARD_TTL` (+ letter), not renewed for `session_stale_seconds` (300) → `GUARD_STALE` |
| Endpoint found able to bill with no live session | CODE_RULE | `gpu_guard.py:162-234` | Only for an endpoint with no OPENING/OPEN session (`170-183`): purge, cancel open jobs, max 0, verify; event `runpod.gpu_guard_off`; letter «GPU-ul RunPod a fost oprit de paznic»; when the off is not verified, also `_tell_off` (event `runpod.gpu_off_unverified` + letter, `232-233`). An integration whose vault cannot be read is skipped (`299-301`) |
| Endpoint settings drifted | CODE_RULE | `gpu_guard.py:149-159`, `235-251`; `endpoint.py:288-308` | min ≠ 0, idleTimeout ≠ 1, flashboot ≠ FLASHBOOT, timeout ≠ 2,400,000 ms → PATCH baseline (always allowed, cost-reducing) |
| Owner told the guard cannot read RunPod | CODE_RULE | `gpu_guard.py:185-205` | Exactly the 3rd consecutive unreadable tick → event + letter «Nu pot verifica GPU-ul RunPod» |
| Guard cadence | CODE_RULE + CONFIG | `gpu_guard.py:325-354` | 60 s while a session is live/closing, closed < 15 min ago, or a copy pod runs; else 600 s |
| Start the copy pod | OWNER (card accept) checked by CODE_RULE | `pods.py:450-503`, `654-809` | Card `runpod_mirror_copy` must be ACCEPTED (or PENDING inside the Owner's own accept, matched by inner command id); requested caps ≤ card caps and > 0; no other live copy; key, bucket, HF token and mirror repo names present; not a simulation |
| Copy pod caps | OWNER (card cap) + CONFIG (rate estimate) / EXTERNAL (RunPod's `cost`) | `pods.py:866-873`, `1319-1360` | Terminate one guard interval before `max_minutes` (default 240) or before `max_usd` (default 5.00) at RunPod's reported rate, else 1.00 USD/h; the pod's own `not_after` deadline |
| Copy pod outcome | EXTERNAL (pod's result JSON) + CODE_RULE | `pods.py:987-996`, `1319-1360`, `1195-1227`, `1279-1294` | SUCCEEDED when every image reported a 40-hex commit; FAILED on any non-zero exit or error (`COPY_FAILED`), or when RunPod no longer has the pod / lists it EXITED, ERROR or TERMINATED (`POD_ENDED`); at BOOT/SHUTDOWN a live copy whose results do not already decide it is STOPPED, and on a TICK a copy still CREATING after 15 min is STOPPED |
| Record mirror revisions | CODE_RULE | `pods.py:999-1015` | On SUCCEEDED, writes `stills/motion_mirror_repo` and `_revision` into the integration config (version +1): this unblocks `readiness_problem` |
| Terminate stray copy pods | CODE_RULE | `pods.py:925-952`, `1243-1275` | Only names matching `^amn-mirror-copy-[0-9a-f]{8}$`, not owned by a RUNNING copy, not spared (copy < 15 min in create) |
| Price of a model | CONFIG (`config/runpod_models.json` GPU-second estimates) × CONFIG (4.00 USD/h) | `pricing.py:31-137` | Explicit `pricing` wins; else rate × GPU seconds / 3600; no finite positive forecast → no price row (no purchase); 0 allowed only for the mock |
| Mock adapter allowed / any adapter built | CONFIG (`OwnerPolicy.environment`, the policy row; the integration's `configured`) | `wiring.py:24-31` | An integration that is not `configured` (switch OFF, no key or no endpoint) returns no adapter; a mock integration returns no adapter in `PRODUCTION` |
| Lone per-request purchase on Serverless | CODE_RULE | `provider.py:100-109` | Always refused `NEEDS_GPU_ROUND` (unsent) on real Serverless (ADR-RUNPOD-NO-LONE-RUN) |
| Legacy Pod start/stop | CONFIG (`allow_infra_actions`, `auto_start`, `auto_stop`) | `compute.py:26-78`; `config.py:318-327` | Pod mode only; mutation requires `allow_infra_actions`; Pod mode is frozen per ADR-RUNPOD-SERVERLESS-ONLY |
| QA verdict copied onto the journal | CODE_RULE (a copy; the verdict itself is decided upstream by QC in other modules, partly LLM-driven) | `wiring.py:63-84` | Only COMPLETED rows matched by remote id, film and scene; `accepted` = take APPROVED (or the caller's explicit value); no control effect here |

## LLM involvement

**None.** No function in these 22 files calls `app.agents.services.run_agent_task` or any gateway
wrapper (`structured_run`, `run_with_strategy`, `reviews._run`, `media.prompt_agent._run`): a grep of
`backend/app/providers/runpod/` for those names finds nothing, and the static inventory gives every
one of the 361 functions `llm_distance = null` and `llm_call_site = false`. No function here reaches
the LLM indirectly either. The paths a name-based analysis could miss were read by hand: the injected
callbacks (`on_submitted`, which writes the stage's takes; `should_stop` / `STEP_STOP`, which is
`run_rounds`' `stop_reason`: the stage's `stopped()` or `PurchaseGuard.stop_reason`,
`media/gpu_batch.py:354-358`; `PurchaseGuard.stop_reason` has `llm_distance = null`), the letters (`app.agents.messages.post_message`,
`gpu_session.py:380-399`, a message row with no model call), the cards (`decisions.sources.ask`,
`runpod_weights_card`, `runpod_mirror_copy_card`, `decisions.producers.gpu_hold.propose_gpu_hold_card`)
and the kernel (`services.may_act` / `_gpu_on_verdict`): all have `llm_distance = null` in the
inventory and none calls a gateway. No vision call, ensemble or agent persona exists in these files.

What this package does receive that an LLM wrote upstream (as data only, never as a decision):

| Data | Arrives through | What this package does with it |
|---|---|---|
| Still / clip prompt and negative prompt (written by the studio's prompt writers in other modules) | `BatchRequest.prompt`, `.negative_prompt` (`batch.py:221-240`) | Hashed into the journal payload (`batch.py:291-317`), sent verbatim in the round body (`batch.py:1852-1862`); the only checks are the worker contract's `validate_input` (`batch.py:1951`) and, on the legacy path, `GenerationRequest` length limits (prompt ≤ 20,000 chars, `models.py:29-30`). The content is never judged here. |
| QC verdict on a take (QC is in other modules, some of it LLM-driven) | `wiring.sync_take_quality` (`wiring.py:63-84`) | Copied onto `cloud_generation_job.accepted` / `quality_result` for telemetry; no control effect in this package except that `provider.regenerate` requires `accepted is False` (`provider.py:442-443`), and that method has no caller in `backend/app`. Since 20abffd the verdict copied can also be the Director's second look (an LLM): a still the gate refused and her look let stand is synced `accepted=True` (`backend/app/media/stills_stage.py:1017-1035`), and a refused clip her look keeps is recorded PASSED and synced accepted (`backend/app/media/assembler.py:10361-10373`, `:5168-5174`). When she overturns a refusal, the re-roll or retry round it would have bought is never sent to this package (`backend/app/media/stills_stage.py:1143-1149`, `backend/app/media/qc.py:2670-2683`). |
| A Director-initiated repair (`scene_redo` step) | `StepPermit.step` (`gpu_session.py:180-195`) | Opens a GPU session like any paid step; the kernel decides. Shown to the Owner in words (`gpu_session.py:1613-1658`). |

So within this subsystem the LLM share of decisions is **0%**: spending, refusing, retrying,
stopping, accepting results and escalating to the Owner are all deterministic code reading config,
the Owner's cards/buttons, and RunPod / bucket answers.

## Hard rules and limits

### Configuration defaults (`RunPodConfig`, `config.py`; env prefix `RUNPOD_`, `.env`, or the integration row)

| Setting | Default | Line | Meaning |
|---|---|---|---|
| `mode` | `serverless` | 107 | `pod` is the frozen legacy path |
| `gpu_name`, `gpu_vram_gb` | `RTX_PRO_6000`, 96 | 114-115 | Journal label |
| `gpu_cost_per_hour` | 2.09 USD | 117 | Pod rate (frozen) |
| `serverless_cost_per_hour` | 4.00 USD | 119 | Budget rate (RunPod pages say 3.49 and 0.00111 USD/s; higher one budgeted) |
| `request_timeout` | 60 s (≤ 300) | 120 | Per HTTP request |
| `poll_interval` | 2 s | 121 | Legacy `wait` loop |
| `max_retries` | 3 (≤ 10) | 122 | Transient-retry count |
| `job_timeout` | 1800 s | 123 | Legacy local wait; also Pod readiness wait (`compute.py:78`) |
| `allow_infra_actions` | false | 125 | The Owner's card «Agenții pot porni singuri GPU-ul RunPod…» |
| `auto_start` / `auto_stop` | false / false | 126-127 | Pod mode only; require `allow_infra_actions` (`config.py:322-327`) |
| `idle_shutdown_minutes` | 15 | 128 | Pod `stop_if_idle` |
| `idle_timeout_seconds` | 1 (1..3600) | 133 | Endpoint `workers.idleTimeout` («oprit imediat») |
| `max_workers` | 1 (validator `le=1`) | 135 | Raising it is a code + ADR change |
| `cold_start_seconds` | 120 | 137 | Model load priced once per round |
| `endpoint_timeout_ms` | 2,400,000 | 139 | Endpoint execution timeout, sent explicitly |
| `flashboot` | `FLASHBOOT` | 140 | Baseline |
| `execution_timeout_cap_seconds` | 2400 | 141 | Per-job cap |
| `still_item_budget_seconds` / `clip_item_budget_seconds` | 180 / 900 | 142-143 | Item budgets in a chunk |
| `queue_wait_seconds` | 900 | 144 | Added to ttl |
| `off_grace_seconds` / `off_poll_seconds` | 60 / 2.0 | 146-147 | Verify-OFF window |
| `session_stale_seconds` | 300 | 149 | Guard forces off an unrenewed session |
| `paused_wait_seconds` | 180 (≤ 1800) | 157 | 409-paused retry budget |
| `session_max_seconds` | 14,400 (4 h) | 158 | Session `expires_at` |
| `gpu_busy_wait_seconds` | 600 | 159 | One-GPU wait |
| `guard_interval_seconds` / `guard_idle_interval_seconds` | 60 / 600 | 160-161 | Guard cadence |
| `s3_region`, `s3_prefix`, `url_ttl_seconds` | `auto`, `amn/`, 604,800 | 165-169 | Bucket |
| `model_source` | `cache` | 173 | `volume` / `baked` alternatives |
| `model_cache_wait_seconds` | 3600 | 183 | Unbilled cache-miss wait added to ttl |
| `model_wait_notice_seconds` | 60 | 185 | «aștept descărcarea modelului (neplătită)» |
| `mirror_pod_image`, `_cpu_flavor`, `_vcpus`, `_disk_gb` | `python:3.12-slim`, `cpu5c`, 4, 60 GB | 190-196 | Copy pod (disk lowered from 200 after HTTP 400, ADR-RUNPOD-COPY-DISK) |
| `mirror_pod_cost_per_hour` | 1.00 USD | 198 | Assumed until RunPod reports a cost |
| `mirror_copy_max_minutes` / `mirror_copy_max_usd` | 240 / 5.00 USD (≤ 100) | 200-201 | Card caps |
| `model_routes` | IMAGE_* → Qwen-Image-2512, VIDEO_QUALITY/HERO → LTX-2.5, VIDEO_AUTO → AUTO | 205-213 | Logical route → model |

Validators: HTTPS-only URLs without credentials/query (`config.py:81-93`, `228-249`); bucket name
3-63 chars (`config.py:43`, `251-256`); prefix lowercase ending `/` (`config.py:258-263`); HF repo
`owner/name` and 40-hex revisions (`config.py:265-277`); vCPU power of two (`config.py:291-296`);
identifiers alphanumeric/`-_` ≤ 100 (`config.py:298-303`); model validator: under `cache`,
execution cap + queue wait + cache wait must fit in `session_max_seconds` (2400 + 900 + 3600 = 6900
≤ 14,400) (`config.py:328-336`).

### Other constants

| Constant | Value | Where |
|---|---|---|
| Client retry backoff | min(30, 2^attempt) + U(0, 0.25) s; a delay > 30 s raises | `client.py:19-20`, `79-81` |
| Client retries only | GET or unsent requests, on unsent / unanswered / 429 / 500 / 502 / 503 / 504 | `client.py:72-78` |
| Request body cap | 10 MB (`client.py:53-54`); legacy payload 10 MB − 1 KB (`provider.py:118-119`) | |
| Inline image cap (legacy adapter) | 5 MB, PNG/JPEG/WebP only | `adapters.py:33-44` |
| Candidates per legacy `generate_candidates` | 1..8 | `adapters.py:362-363` |
| `GenerationRequest` limits | prompt ≤ 20,000; ≤ 8 references; attempt 1..1000; candidate 0..7; video duration ≤ 120 s; fps ≤ 120 | `models.py:25-65` |
| S3 presign lifetime | 1 s .. 604,800 s | `s3.py:36`, `69-70` |
| S3 request timeout / retries | 60 s (total 120 s) / 3, backoff 0.5 × 2^attempt ≤ 8 s | `s3.py:38-39`, `157-168` |
| Presigned PUT / GET for manifests and downloads | 900 s | `s3.py:176`, `182`; `batch.py:1309`; `provider.py:385` |
| Input picture GET lifetime | 7200 s | `batch.py:80` |
| Handler margin under `executionTimeout` | 15 s | `batch.py:82`, `1944-1946` |
| Items per chunk | ≤ `contract.MAX_ITEMS` = 32 | `batch.py:406`; `backend/runpod_worker/contract.py:30` |
| Still size / clip fps sent | 1530 × 2720 / 24 | `batch.py:1864`, `1872`; `contract.py:32`, `35` |
| Paused ladder | 1, 2, 4, 8, 15 s, then every 30 s, within 180 s | `batch.py:1468-1469` |
| `REFUSED_STATUSES` | {400, 401, 403, 404, 413, 422, 429} | `batch.py:168` |
| Job id accepted from `/run` | non-empty string ≤ 90 chars | `batch.py:1677` |
| `reserve_item` attempt search | ≤ 1000 attempts | `batch.py:468`, `532` |
| One-GPU busy poll | 5 s | `gpu_session.py:104` |
| Fresh page read throttle | 10 s per endpoint | `gpu_session.py:106` |
| Fast (window-close) requests | 2 s each, no retry; lock wait 1 s (else 120 s) | `gpu_session.py:108`, `1310` |
| Evidence read before purge | one try, 5 s (+1 s wait_for) | `gpu_session.py:113`, `597-614` |
| Guard unreadable letter | at exactly 3 consecutive ticks | `gpu_guard.py:68`, `190` |
| Guard short-interval window | 15 min after a close | `gpu_guard.py:70` |
| Guard stale default when config unknown | 300 s | `gpu_guard.py:131` |
| Copy pod create body | ≤ 90,000 bytes (RunPod refuses > 102,400) | `pods.py:93-94`, `747-749` |
| Copy pod create grace | 15 min before a tick may stop/sweep it | `pods.py:78`, `1297-1299` |
| Copy pod presign lifetime | min(7 days, max_minutes × 60 + 3600) | `pods.py:724` |
| Copy pod own deadline | max(60 s, min(time cap, usd cap / rate) − guard interval) | `pods.py:866-873` |
| Copy pod sweep window on ticks | copies created within 2 days, or an unconfirmed terminate | `pods.py:1247-1256` |
| Pod listing pages | ≤ 50 | `pods.py:431` |
| Setup checklist read | 10 s, no retry; bucket HEAD presign 300 s | `setup_steps.py:55`, `368-370`, `453-461` |

### State machines

- **GPU session** (`gpu_session` table, `gpu_session.py:85-161`): `OPENING` → `OPEN` (switch-on
  verified, `1039-1044`) → `CLOSING` (`1107`) → `CLOSED` (`1126-1133`, `1150-1159`, `1169-1178`);
  `OPENING` → `FAILED_OPEN` (`978-986`, `1010-1017`); any live or `CLOSING` → `FORCED_OFF`
  (`_mark_forced` `1418-1440`, guard `_expire_sessions` `gpu_guard.py:103-146`). Close reasons
  (CHECK constraint): `STEP_DONE`, `STEP_FAILED`, `OWNER_OFF`, `GUARD_ORPHAN`, `GUARD_STALE`,
  `GUARD_TTL`, `BOOT`, `SHUTDOWN`, `LAUNCHER_STOP`, `OPEN_FAILED` (`gpu_session.py:89-100`).
- **Journal row** (`cloud_generation_job`, `jobs.py:28-68`): `STARTING` (reserved) → `QUEUED` (job id
  saved, `batch.py:1617`) → `RUNNING` → `COMPLETED` / `FAILED` / `CANCELLED` / `TIMEOUT`
  (`models.py:12-22`). Error codes used: `UNSENT`, `SUBMISSION_UNCERTAIN`, `EXPIRED_UNDELIVERED`,
  `BAD_OUTPUT`, `SKIPPED_TIME`, `CANCELLED_BY_STUDIO`, `HTTP_<status>`, worker codes
  (`batch.py:86-88`, `998`, `1222`, `640`).
- **Item action** (`reserve_item`): `SEND` / `RESEND` / `TRACK` / bump attempt (`batch.py:456-532`).
- **Copy pod** (`runpod_copy_pod`, `pods.py:278-310`): `CREATING` → `RUNNING` → `SUCCEEDED` /
  `FAILED` / `TIMED_OUT` / `OVER_COST` / `STOPPED`; also `CREATING` → `FAILED` (`UPLOAD_FAILED`,
  `BODY_TOO_LARGE`, `CREATE_REFUSED_<n>`, `CREATE_UNCERTAIN`, `pods.py:729`, `748`, `756-758`, `770`)
  and `CREATING` → `STOPPED` (BOOT/SHUTDOWN, or a TICK once the create is older than 15 min,
  `pods.py:1201-1227`).

## Modules

### `app.providers.runpod` — `backend/app/providers/runpod/__init__.py` (1 line)

Package docstring only: «Optional RunPod generation; paid activity is disabled unless configured and
selected.» No functions.

### `app.providers.runpod.errors` — `backend/app/providers/runpod/errors.py` (21 lines)

Exception classes, no functions: `RunPodDisabled(MediaProviderNotConfigured)` (line 4),
`RunPodProtocolError(MediaProviderError)` (8), `IdempotencyConflict` (12), `SubmissionUncertain` (16,
«A durable intent has no verified remote id; never automatically submit it again»),
`InfrastructureDisabled` (20).

### `app.providers.runpod.config` — `backend/app/providers/runpod/config.py` (448 lines)

`RunPodConfig` (pydantic-settings): one integration's form values + vault secrets, or `RUNPOD_*` from
the environment / `.env`. Secrets (`api_key`, `s3_access_key_id`, `s3_secret_access_key`, `hf_token`)
come only from the vault (`SECRET_FIELDS`, line 38). `BucketConfig` (62-78) hides the secret in its
`repr`. All constants are listed under Hard rules.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_without_environment` | 53 | Context manager that makes settings ignore env/.env | So an old `.env` value never breaks pricing, the page or the GPU off | CODE_RULE |
| `BucketConfig.__repr__` | 74 | Repr without the access key or secret | A bucket config in a log or traceback never leaks a key | CODE_RULE |
| `_https_without_secrets` | 81 | HTTPS-only, no credentials/query/fragment, port 443 | Bucket URL safety | CODE_RULE |
| `RunPodConfig.settings_customise_sources` | 216 | Drops env sources inside `_without_environment` | See above | CODE_RULE |
| `secure_url`, `secure_bucket_url`, `bucket_name`, `bucket_prefix`, `mirror_repo`, `mirror_revision`, `resource_list`, `power_of_two`, `safe_identifier`, `cancellation_route` | 228-316 | Field validators (see Hard rules) | Reject malformed or unsafe values at the boundary | CODE_RULE |
| `RunPodConfig.infra_policy` | 319 | Pod auto start/stop needs `allow_infra_actions`; cache wait must fit a session | A Pod must not auto-start without permission; a session end must not cut a model download | CODE_RULE |
| `RunPodConfig.configured` | 340 | enabled and (mock, or key + endpoint for serverless / base URL for pod) | Single "may this integration be used" flag | CONFIG |
| `RunPodConfig.hourly_rate` | 357 | Serverless budget rate or Pod rate | Every estimate uses it | CONFIG |
| `RunPodConfig.endpoint_for` | 363 | Stills/motion endpoint, falling back to legacy `endpoint_id` | Two endpoints since 2026-10-08 | CONFIG |
| `RunPodConfig.mirror_for` | 368 | (repo, revision) for stills or motion | Weights check | CONFIG |
| `RunPodConfig.endpoints` | 374 | Every configured endpoint once, image first | Guard, force-off, page iterate it | CONFIG |
| `RunPodConfig.bucket` | 385 | `BucketConfig` only when URL, bucket and both keys exist | Outputs must have somewhere to go | CONFIG |
| `RunPodConfig.ready_for_generation` | 405 | configured and (mock or bucket) | `submit_round` refuses otherwise (`batch.py:1396`) | CONFIG |
| `RunPodConfig.route` | 409 | Explicit model (mapped through `model_routes`) or `<OP>_<QUALITY>` route | Legacy per-request path | CONFIG |
| `RunPodConfig.from_integration` | 418 | Build from form strings + vault secrets; on ValidationError retry without env (logged `runpod_environment_ignored`) | The integration row is the source of truth; env cannot break it | CODE_RULE |
| `RunPodConfig.connection` | 446 | Legacy wrapper | Older callers | CODE_RULE |

Data: none written. External calls: none.

### `app.providers.runpod.models` — `backend/app/providers/runpod/models.py` (119 lines)

Request schemas (`GenerationRequest`, `ImageRequest`, `VideoRequest`, `FinalizeRequest`, lines
25-65, `extra="forbid"`) and the pinned catalogue reader for `config/runpod_models.json`
(`MODELS_FILE`, line 70). At mapping time the catalogue holds Qwen-Image-2512 (stills, 60 GPU-s per
image), Qwen-Image-Edit-2511 (stills, 75 GPU-s, reference binding min 1 max 3), LTX-2.5 (motion, 24
GPU-s per video second, max 10 s), Wan-2.2-LightX2V (motion, 33 GPU-s per video second); its
`worker_images` are both `null` and its `rate_usd_per_hour` is "4.00".

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_catalogue` | 74 | LRU-cached JSON read; refuses `schema_version != 1` | Pinned catalogue, Owner decisions 2026-10-08 | CONFIG |
| `serverless_catalogue` | 81 | Whole catalogue | Health check reads `worker_images` | CONFIG |
| `serverless_models` | 86 | Models whose endpoint (stills/motion) is configured | `available_models` without any `/run` | CONFIG |
| `model_entry` | 96 | One model by id | `reference_spec` | CONFIG |
| `reference_spec` | 106 | The model's `reference` binding when it lists bindings, else None | A model without a binding never receives a picture (2511 route, 2026-10-09) | CONFIG |

### `app.providers.runpod.jobs` — `backend/app/providers/runpod/jobs.py` (218 lines)

The durable submission journal `cloud_generation_job` (`GenerationJob`, lines 28-68; unique
`idempotency_key`; migration 0056 added `batch_remote_id`, `batch_index`, `request_digest`,
`gpu_session_id`, `billed_seconds_value`). «Durable provider submission journal in the Agency DB,
never a second queue» (line 1).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `now` | 24 | UTC ISO timestamp | Row times | — |
| `GenerationJob.gpu_seconds` / `estimated_cost_usd` | 71 / 75 | Text columns as numbers | Stored as text for exact decimals | — |
| `_picture_digest` | 79 | `data:` URI → `{sha256, bytes, mime}` | 6.7 MB rows (2026-10-08) | CODE_RULE |
| `journal_request` | 99 | Replace inline pictures by digests | Same | CODE_RULE |
| `digest` | 112 | sha256 of canonical JSON | Keys and payload hashes | CODE_RULE |
| `target_identity` | 118 | Hash of mode, endpoint, base URL, mock, integration | A key is per target | CODE_RULE |
| `JobStore.__init__` | 125 | Keeps the engine | — | — |
| `JobStore.reserve` | 128 | Legacy per-request reservation under the write lock: same key + same payload → existing row; proven `UNSENT`/`HTTP_*` failure → reusable; different payload → `IdempotencyConflict`; pre-0056 rows compared by `payload_hash` or terminal status | Never two purchases for one creative attempt | CODE_RULE |
| `JobStore.read` | 195 | Row by id or remote id (optionally per target) | All readers | — |
| `JobStore.update` | 208 | Locked update; refuses unknown status | Single write path | CODE_RULE |

### `app.providers.runpod.client` — `backend/app/providers/runpod/client.py` (169 lines)

Thin HTTP client over the injectable `media_http.request` transport (so tests never reach RunPod).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `backoff_seconds` | 19 | Exponential backoff with jitter, ≤ 30 s | Shared by endpoint/pods | CODE_RULE |
| `RunPodClient.__init__` | 24 | Config + transport | — | — |
| `RunPodClient.call` | 28 | Builds `https://api.runpod.ai/v2/<endpoint_id>` (serverless) or `generation_base_url`; Bearer key; optional `Idempotency-Key`; ≤ 10 MB body; retries only safe (GET or unsent) transient failures; non-object answer → protocol error | A POST that may have been received must never be resent blindly | CODE_RULE |
| `RunPodClient.submit` | 93 | Legacy `/run` (serverless) or `/generate/<op>` (pod) with `idempotency_key` | Legacy per-request path | CODE_RULE |
| `RunPodClient.status` | 104 | `/status/<id>` or `/jobs/<id>` | Collection | EXTERNAL |
| `RunPodClient.cancel` | 108 | `/cancel/<id>`; Pod only with a declared `pod_cancel_path`, else refuses | «No speculative call to an unspecified cloud route» (115) | CODE_RULE |
| `RunPodClient.health` | 118 | `/health` | Legacy health | EXTERNAL |
| `RunPodClient.models` | 121 | `GET /models` on the control base URL | «never submit a billable job to discover its catalogue» (122-123) | CODE_RULE |
| `RunPodClient.download` | 126 | HTTPS-only (no credentials, fragment, non-443 port), public hosts only, retried on transient failures; empty → error | Output URLs come from the vendor; signed queries never logged | CODE_RULE |

### `app.providers.runpod.s3` — `backend/app/providers/runpod/s3.py` (192 lines)

Standard-library AWS SigV4 query-string presigning (no boto3), path-style URLs, `UNSIGNED-PAYLOAD`,
only `host` signed, so a URL is the whole credential and can be handed to the worker or the copy pod
(lines 1-17).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `_uri` | 42 | RFC 3986 encoding | SigV4 rule | CODE_RULE |
| `_signing_key` | 47 | HMAC chain | SigV4 | CODE_RULE |
| `presign_url` | 54 | Signed URL for one method, 1 s..7 days | The bucket is reached only through such URLs | CODE_RULE |
| `_safe_key` | 96 | Refuses empty, absolute, `..`, control chars, `\?#`, > 1024 chars | Object-key safety | CODE_RULE |
| `presign` | 108 | Path-style URL for the Owner's bucket | Wrapper | CODE_RULE |
| `_split` | 132 | Host + path?query | Transport call shape | — |
| `_send` | 137 | Sends via transport; retries transient failures of idempotent calls (PUT of content-addressed object, GET) ≤ 3 times | «The bucket costs nothing per GPU second, so this never buys anything» (165) | CODE_RULE |
| `put_bytes` | 172 | Presigned PUT (900 s) | Upload inputs, worker files | CODE_RULE |
| `get_json` | 180 | Presigned GET (900 s); 404 → None; a 403 is NOT read as missing | Manifests, claims, copy results | CODE_RULE |

External: the Owner's bucket (storage requests; no GPU money).

### `app.providers.runpod.endpoint` — `backend/app/providers/runpod/endpoint.py` (392 lines)

Management of one Serverless endpoint: REST v2 on `api.runpod.io` (GET/PATCH `/v2/serverless/{id}`)
and the queue host `api.runpod.ai` (`/health`, `/purge-queue`, `/cancel/{job}`). RunPod's facts are
cited in the docstring (lines 3-24): billing runs from worker start to full stop, so OFF is
`max == 0`, `running == 0`, `inProgress == 0`, `inQueue == 0`; `idle` is only logged.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `OffReading.as_dict` | 91 | Serialise a reading | Events, session rows | — |
| `utc_now` | 95 | Timestamp | — | — |
| `is_off` | 99 | OFF definition above | Nothing can bill | CODE_RULE |
| `_int` / `_optional_int` | 110 / 116 | Strict / lenient integer reads | Required fields never assumed | CODE_RULE |
| `parse_settings` | 122 | `workers.min/max/idleTimeout`, timeout, flashboot, image, GPU pools | Typed reading | CODE_RULE |
| `parse_health` | 144 | `jobs.inQueue/inProgress`, `workers.running/idle` | Typed reading | CODE_RULE |
| `still_on_words` | 158 | Romanian reason the endpoint is not off | Owner letters, page | CODE_RULE |
| `EndpointControl.__init__` | 173 | Validates endpoint id; per-call timeout/retry overrides | Window-close path uses 2 s, no retry | CODE_RULE |
| `EndpointControl._call` | 195 | Request with retries on unsent/unanswered/429/500/502/503/504 (all calls idempotent; backoff `client.backoff_seconds`, a delay over 30 s raises); 401/403 → `EndpointAccessDenied` | Off must survive transient failures | CODE_RULE |
| `_management` / `_queue` | 248 / 251 | Path builders | — | — |
| `EndpointControl.get` | 254 | Read settings | — | EXTERNAL |
| `EndpointControl._patch` | 261 | PATCH; reads back once if the answer lacks `workers` | Never trust a partial answer | CODE_RULE |
| `EndpointControl.set_workers` | 271 | PATCH `{min 0, max (0 or 1), idleTimeout 1}` and verify it applied (`SettingsNotApplied`) | The switch | CODE_RULE |
| `EndpointControl.apply_baseline` | 288 | PATCH resting settings: max 0, idle 1, timeout, flashboot; volume fields only under `volume` | Guard drift repair | CODE_RULE |
| `EndpointControl.health` | 310 | `/health` | — | EXTERNAL |
| `EndpointControl.purge_queue` | 315 | `/purge-queue`; keeps RunPod's `removed` count (None when missing, never 0) | The never-queued proof reads it | CODE_RULE |
| `EndpointControl.cancel` | 324 | `/cancel/<job>` (item id `<job>:<i>` → job); 404 → `NOT_FOUND` | Idempotent cancel | CODE_RULE |
| `EndpointControl.read` | 342 | settings + health | — | EXTERNAL |
| `EndpointControl.verify_off` | 345 | Poll every 2 s until OFF or idle + grace (61 s) | Verified off | CODE_RULE |
| `EndpointControl._reading` | 375 | Build `OffReading` | — | — |

### `app.providers.runpod.gpu_session` — `backend/app/providers/runpod/gpu_session.py` (1,675 lines)

The GPU session of one paid step (lines 1-32): open (kernel + one-GPU rule + PATCH max 1), the step
sends its rounds while renewing, close in `finally` (purge, cancel, max 0, verify). Also: the Owner's
hold, `force_off` (button, shutdown, launcher, guard), and the page state. Sync API: each network
sequence runs in `asyncio.run`; one `threading.Lock` per endpoint (`endpoint_lock`, 310) and a global
`_GPU_RULE_LOCK` (307). Table `gpu_session` (`GpuSessionRow`, 125-161).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `GpuSessionRefused.__init__` | 167 | Refusal, `unsent=True` | Nothing sent, nothing spent | — |
| `GpuForcedOff.__init__` | 175 | Session switched off from outside; default words `FORCED_OFF_WORDS` | The step stops; what was bought stays | — |
| `StepPermit.context` | 197 | Context dict for `infra.gpu_on` | Kernel input | — |
| `StepPermit.from_guard` | 207 | Permit from the step's `PurchaseGuard` and verdict (`owner_press = not guard.unasked`, `cost_usd` = step cap) | The kernel's inner question is the step's own | CODE_RULE |
| `GpuSession.note_uncertain` | 256 | Remember keys of a `/run` with no job id | Close then collects queue evidence | CODE_RULE |
| `GpuSession._status` / `check` | 263 / 268 | Raise `GpuForcedOff` unless row is OPEN | Owner button / guard / shutdown reach the step | CODE_RULE |
| `GpuSession.renew` | 273 | `renewed_at = now` under write lock; `GpuForcedOff` if not OPEN | Guard's stale rule | CODE_RULE |
| `GpuSession.note_job` | 282 | Append RunPod job id (optionally in caller's transaction) | Close can cancel by id | CODE_RULE |
| `endpoint_lock` | 310 | Per-endpoint lock | Open never races a close | CODE_RULE |
| `remember_reading` / `last_reading` / `forget_readings` | 325 / 341 / 347 | In-process reading cache | Page and guard; `forget_readings` is used by tests | — |
| `_now`, `_moment` | 355, 402 | Time helpers | — | — |
| `_event` / `_write_event` | 359 / 367 | `append_event` on aggregate `gpu_session`; never raises | An event never breaks the off | CODE_RULE |
| `owner_letter` | 380 | `post_message(intent=ESCALATE, to_owner=True)`; never raises | Letters to the Owner | CODE_RULE |
| `overlapping_sessions` | 412 | Other sessions on the endpoint overlapping in time (FAILED_OPEN excluded; unreadable times counted) | Shared queue makes the proof void | CODE_RULE |
| `longest_job_ttl_seconds` | 442 | 2400 + 900 (+ 3600 under cache) | How long a queued job may still wait | CONFIG |
| `booked_unsent_sessions` | 454 | Sessions on this endpoint closed within that ttl whose rows were booked `not_queued` | A late-queued job must not run on the next GPU | CODE_RULE |
| `_switch_on` | 498 | Optional purge, then `set_workers(max)` | Switch on | CODE_RULE |
| `_other_live` | 510 | Live sessions on the endpoint except own | Refcount | CODE_RULE |
| `_unfinished` | 517 | Job's journal rows not all terminal (or unknown) | Cancel set | CODE_RULE |
| `_open_jobs` | 529 | Own unfinished jobs + every non-terminal batch of this endpoint whose session is no longer live | Nothing left billing | CODE_RULE |
| `_cancel_jobs` | 553 | Cancel each, collect errors | Best effort | CODE_RULE |
| `_health_record` | 564 | Dict of counts | Evidence | — |
| `_switch_off` | 576 | Optional evidence read before purge (5 s, one try); fast: purge + max 0 concurrently; else purge (keep `removed`), cancel, max 0; optional verify | The off and the proof's evidence | CODE_RULE |
| `_unreadable` | 660 | Unverified reading with reason | — | — |
| `_tell_off` | 674 | Event verified/unverified; letter when unverified | The Owner told once | CODE_RULE |
| `precheck` | 701 | See Who decides; called before the Owner's yes is asked or spent | A yes spent on a step whose GPU cannot start is lost (ADR-RUNPOD-PRECHECK-BEFORE-YES) | CODE_RULE + OWNER inputs |
| `_refuse_held` | 745 | Raise `WEIGHTS_MISMATCH` if a weights card holds | — | OWNER (card) |
| `owner_hold_active` | 775 | Newest `runpod.owner_hold` says on; exception → True | Fail closed on money | OWNER |
| `set_owner_hold` | 795 | Write hold/lift event | Router (on) and card applier (off) | OWNER |
| `_refuse_owner_hold` | 806 | Raise `OWNER_HOLD` | — | OWNER |
| `_switched_off_now` | 811 | Integration's `enabled` read now; unreadable config → True | Switch OFF after the adapter was built (adversary 2026-10-09) | OWNER |
| `_kernel` | 829 | `may_act("infra.gpu_on", ask_owner=False)` then rollback | Kernel decides, writes nothing | CODE_RULE |
| `_insert` / `_update` | 846 / 881 | Session row writes (expires = opened + `session_max_seconds`) | — | — |
| `open_session` | 890 | Mock: OPEN row with endpoint `mock`. Real: hold → configured → bucket → weights hold → kernel → one-GPU wait → (endpoint lock) switch OFF now? → shared? → purge-if-recent + PATCH max 1 → OPEN + event `runpod.gpu_session_opened`; failure → `FAILED_OPEN`, compensating max 0, `COMPUTE_NOT_READY` | Switch the one GPU on only for an allowed step | CODE_RULE / OWNER |
| `close_session` | 1078 | Never raises; shared endpoint → cancel own unfinished jobs only; else `_switch_off(verify)` with evidence when uncertain keys exist; row `CLOSED` with `verified_off`, `off_reading`; `_tell_off` | Off right after the step | CODE_RULE |
| `gpu_session` | 1187 | Context manager (`@contextmanager` on 1186): open, yield, close with `STEP_DONE`/`STEP_FAILED` | `finally` off | CODE_RULE |
| `runpod_targets` | 1217 | Every RunPod integration with config or the reason it cannot be read | Guard, force-off, page | CONFIG |
| `controllable` | 1249 | Real Serverless with key and endpoint (ignores `enabled`) | «a disabled flag never leaves a GPU on» | CODE_RULE |
| `listed` | 1261 | Controllable, or a real Serverless whose keys cannot be read (shown, not hidden) | The page shows it as UNKNOWN; `force_off` records an unverified reading for it but cannot send an off without the key (`1304-1306`) | CODE_RULE |
| `force_off` | 1274 | Mock integrations: their live mock sessions become `FORCED_OFF` (`1297-1299`). Listed real ones whose vault is unreadable: an unverified reading only, no request sent (`1304-1306`). For every other listed endpoint (concurrently): mark live/closing sessions `FORCED_OFF`, purge, cancel (not fast), max 0, verify (not fast); event `runpod.gpu_forced_off`; `_tell_off` event + letter when unverified (not fast; no letter for `OWNER_OFF`); at `SHUTDOWN`/`LAUNCHER_STOP` (not fast) also stop copy pods. Proceeds even when the endpoint lock was not acquired within 1 s / 120 s | Off is always allowed and never consults the kernel | CODE_RULE |
| `_stop_copies` | 1353 | `pods.watch_copies(SHUTDOWN)`, errors swallowed | Nothing bills while the studio is down | CODE_RULE |
| `_off_everywhere` | 1362 | Concurrent `_switch_off` then concurrent `verify_off` | One slow endpoint never holds another's max 0 | CODE_RULE |
| `_mark_forced` | 1418 | Live/closing rows → `FORCED_OFF` with reason; returns their jobs | Steps see `GpuForcedOff` | CODE_RULE |
| `_state` | 1446 | Page state ON/OFF/UNKNOWN from a reading | — | CODE_RULE |
| `read_endpoint` | 1476 | One live read, remembered | Page "fresh" | EXTERNAL |
| `gpu_status` | 1495 | Page payload: rate, endpoints (+ model-wait words), live sessions in words, last off, owner hold, summary words | The Owner's GPU switch | CODE_RULE |
| `_session_words` | 1623 | ««<film>»: <step> — <take kind> scenei N» from SUBMITTED takes; never raises | 2026-10-12: «Ce lucrează? Pentru ce film, ce cadru?» | CODE_RULE |

Data: `gpu_session` rows; reads `cloud_generation_job`, `integration`, `domain_event`, `storyboard`,
`scene_take`; events `runpod.gpu_session_opened`, `runpod.gpu_off_verified`,
`runpod.gpu_off_unverified`, `runpod.gpu_forced_off`, `runpod.owner_hold`; letters via
`app.agents.messages.post_message`. External: RunPod management and queue APIs (switching on is the
precondition for GPU spend).

### `app.providers.runpod.batch` — `backend/app/providers/runpod/batch.py` (2,043 lines)

One paid round on RunPod Serverless (lines 1-42): reserve every item, upload pictures to the bucket
content-addressed, POST the round's chunks back to back, save each job id on its items and on the
session before any take is written or any poll, collect from bucket manifests first then `/status`,
book billed seconds, and prove "nothing queued" for uncertain `/run`s after the close. «Nothing here
switches the GPU on or off: that is `gpu_session`» (41).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `BatchRefused.__init__` | 119 | Unsent refusal with RunPod's status/detail and an `after_purchase_ro` variant | Every layer above books nothing for it | — |
| `refusal_words` | 138 | Owner's words for a stop: never «nothing bought» once the step had bought earlier | Review 2026-10-09/10 letters contradicted the books | CODE_RULE |
| `endpoint_paused` | 171 | 409 answered with «paused»/«max_workers» | Switch-on not yet seen by RunPod's queue | CODE_RULE |
| `refused_unqueued` | 184 | THE one list of "RunPod queued nothing" | Four copies disagreed (2026-10-09) | CODE_RULE |
| `step_stop` | 212 | Context manager (`@contextmanager` on 211) setting the `STEP_STOP` context var that carries the step's stop into `submit_round` | Adapter `submit_batch` has no parameter for it | CODE_RULE |
| `item_seed` | 262 | sha256(storyboard\|scene\|attempt\|candidate)[:8] as int | Deterministic seed; a re-roll is a new attempt | CODE_RULE |
| `picture_kind` / `picture_digest` | 268 / 279 | PNG/JPEG/WebP sniffing; digest | Inputs and journal | CODE_RULE |
| `supports_batch` | 285 | Adapter's `supports_batch()` | Stages choose the round path | CODE_RULE |
| `journal_payload` | 291 | Item request as journalled (pictures by digest, `reference_bindings`, video fields) | Idempotency and audit | CODE_RULE |
| `route_references` | 320 | Apply the model's reference binding (see Who decides) | 2511 route, 2026-10-09 | CONFIG + CODE_RULE |
| `_count` | 356 | Int or None (bool rejected) | Unread never taken as 0 | CODE_RULE |
| `queue_problems` | 360 | Why session evidence does NOT prove nothing queued | Proof input | CODE_RULE |
| `item_budget` / `chunk_items` / `chunk_policy` | 394 / 402 / 410 | Chunk sizes and per-job `executionTimeout` / `ttl` | Fit the execution cap; keep the worker's models loaded across chunks | CONFIG + CODE_RULE |
| `_decimal` | 432 | Finite non-negative Decimal or None | — | — |
| `_key` | 443 | Item idempotency key | Same composition as `JobStore.reserve` | CODE_RULE |
| `reserve_item` | 456 | SEND/RESEND/TRACK/new attempt under write lock; keeps a `resent` trail of uncertain sessions | Never a second purchase; a redo without verdict never reuses a spent key | CODE_RULE |
| `_with_attempt`, `_uuid` | 535, 541 | Helpers | — | — |
| `BatchRun.weights_problem` | 586 | First weights problem | Caller stops the step | CODE_RULE |
| `BatchRun.store` / `done` / `deadline_passed` | 591 / 594 / 599 | Store; all items reported; past longest ttl | Round control | CODE_RULE |
| `BatchRun.poll` | 603 | Newly terminal items, each reported once (mock or remote) | Stage loop | CODE_RULE |
| `BatchRun.cancel` | 621 | `/cancel` unfinished chunks, collect what finished, mark the rest `CANCELLED_BY_STUDIO` at 0 cost | A stop keeps what was made | CODE_RULE |
| `BatchRun.billed_seconds_estimate` | 653 | Sum of `billed_seconds` per accepted job, or None until all reported | Booking | CODE_RULE |
| `BatchRun._billed` / `_book` | 662 / 685 | Per-job billing with predecessor and unanswered-chunk budgets; book onto items | 2026-10-09 review | CODE_RULE |
| `BatchRun.settle` | 693 | Read each sent job's final `/status` once (free GET) and book | Items come from manifests, so times were otherwise never read (ADR-RUNPOD-BOOKING-NEVER-BELOW) | EXTERNAL + CODE_RULE |
| `BatchRun.prove_unsent` | 730 | Judge uncertain items against session evidence + bucket claims/manifests; event `runpod.run_queue_proof` | First live stills `/run` (2026-10-09) held a film | CODE_RULE |
| `BatchRun.mark_unsent` | 801 | Proven items → `FAILED/UNSENT` at 0, `not_queued` note | Keys reusable; a job that ran anyway is a free reuse | CODE_RULE |
| `BatchRun._worker_records` | 826 | Read claim and manifest per key; a failed read is a problem | Never «nothing there» on an error | CODE_RULE |
| `BatchRun._client` / `_operation` / `_cancel_remote` | 852 / 859 / 862 | Client for the purpose's endpoint; cancel unfinished chunks (failures logged; the close cancels again) | — | CODE_RULE |
| `BatchRun._poll` | 876 | `collect_row` per item; protocol/contract errors → item `BAD_OUTPUT`; passing network errors → retry next poll; book finished jobs | One bad item never cancels a paid batch | CODE_RULE |
| `BatchRun._note_queue` | 932 | IN_QUEUE chunks → `weights.note_queue` | «aștept descărcarea modelului (neplătită)» | CODE_RULE |
| `BatchRun._poll_mock` | 955 | First poll RUNNING, next COMPLETED with synthetic PNG/MP4, 0 cost | Offline transport | CODE_RULE |
| `_has_times` | 1001 | `delayTime` and `executionTime` numeric | — | — |
| `billed_seconds` | 1009 | See Who decides | 28-min unbilled download booked as 2.3 USD (2026-10-09) | CODE_RULE |
| `_passing` | 1070 | Retryable read (unsent, unanswered, 408/425/429/5xx) | — | CODE_RULE |
| `_bad_output` | 1078 | Row `FAILED/BAD_OUTPUT` (no cost written) | Made but untakeable | CODE_RULE |
| `_outcome_of` | 1089 | Outcome of a terminal row | — | — |
| `_write_asset` | 1099 | Atomic write under `<media root>/runpod/`, refuses symlinks / escapes | Path safety | CODE_RULE |
| `_book_batch` | 1114 | Apportion a job's billed seconds to items by GPU seconds | Start and idle tail ride on the job that started the worker | CODE_RULE |
| `collect_row` | 1128 | Manifest first (`check` weights; `validate_item_result`); else `/status` (404 → `EXPIRED_UNDELIVERED`); map IN_QUEUE/IN_PROGRESS; COMPLETED → item by index (missing → `SKIPPED_TIME`), key echo check, `_land` or FAILED with cost of its GPU seconds; FAILED/CANCELLED/TIMED_OUT mapped | Also the watchdog's path after a restart | CODE_RULE / EXTERNAL |
| `_default` | 1254 | Default transport | — | — |
| `_request_of` | 1260 | Stand-in `BatchRequest` from a row | Watchdog collection | — |
| `_land` | 1283 | Download (URL, else fresh 900 s presigned GET), sha256 check, MP4 check, write, row COMPLETED with cost and `weights_revision`; never stores the signed URL | «a signed address is a credential for 7 days» | CODE_RULE |
| `_upload` | 1354 | Content-addressed PUT of a picture, presigned GET (7200 s), cached per round | Tiny `/run` bodies (10 MB limit) | CODE_RULE |
| `submit_round` | 1372 | One operation per round; route references; ready check (`NOT_CONFIGURED`); known models (real rounds only, `UNKNOWN_MODEL`); reserve all items (`IdempotencyConflict` / `SQLAlchemyError` → unsent refusal); TRACK rows join as chunks; mock or remote submit | Entry point used by `RunPodConnection.submit_batch` | CODE_RULE |
| `_wait_ended` | 1513 | Renew (or only check) the session and read the step stop when one is passed; `GpuForcedOff` → `GPU_FORCED_OFF`, stop words → `STOPPED`, any other error → `WAIT_UNREADABLE`; never raises. Between chunks it is called with no stop (`1914`); inside the paused wait with the step's stop (`1693`, `1702`) | A STOP pressed during the paused wait must stop the next `/run` (2026-10-09 audit) | CODE_RULE / OWNER |
| `_runpod_words` | 1549 | RunPod's sanitised detail as an Owner sentence | — | — |
| `_refusal` | 1558 | `BatchRefused` with code `RUNPOD_PAUSED`/`RUNPOD_UNSENT`/`RUNPOD_HTTP_<n>`/ended code | Owner's words with RunPod's own | CODE_RULE |
| `_save_job` | 1596 | One transaction: `note_job` on session + job id, batch id/index, session id, QUEUED on every item | Before any take/poll so «Oprește GPU acum» can cancel by id | CODE_RULE |
| `_submit_mock` | 1622 | Synthetic job id, save, `on_submitted` | Offline | CODE_RULE |
| `_post_run` | 1653 | POST `/run`; paused ladder within budget, renewing the session and reading the stop | 409 paused after switch-on (live 2026-10-09: ~1 s to > 30 s) | CODE_RULE / EXTERNAL |
| `_note_pause` | 1727 | `runpod.run_paused` event, AFTER `_save_job` | A slow write must not hold an accepted job id in memory only | CODE_RULE |
| `_journal_failed` | 1747 | Log only | A refusal never turns into a purchase because a write failed | CODE_RULE |
| `_journal_answer` | 1761 | RunPod's answer on every row of a failed chunk: proven → FAILED (`UNSENT`/`HTTP_n`, 0 cost, best effort); uncertain → `SUBMISSION_UNCERTAIN` with session id (must succeed) | The sheet, takes and watchdog read why | CODE_RULE |
| `_unsent_rest` | 1802 | Remaining items FAILED/UNSENT at 0; `run.refused` set so no further round | — | CODE_RULE |
| `_submit_remote` | 1832 | Upload inputs (failure → all UNSENT, `INPUT_UPLOAD_FAILED`; a clip without first frame → `NO_FIRST_FRAME`); per chunk: session check only (forced off / unreadable; the step's own stop is not read here, `1912-1914`), build and validate body (`REQUEST_INVALID`), `_post_run`, classify failure (proven/uncertain), save job, note pause, call `on_submitted`; set deadline | The only place a GPU purchase leaves the studio | CODE_RULE |

Data: `cloud_generation_job` rows; `gpu_session.remote_job_ids`; events `runpod.run_queue_proof`,
`runpod.run_paused`; files under `<media root>/runpod/`; bucket keys `inputs/<sha>.<ext>`,
`manifests/<key>.json`, `claims/<key>.json` (worker contract). External: **RunPod `/run` (GPU spend)**,
`/status`, `/cancel`; the Owner's bucket.

### `app.providers.runpod.weights` — `backend/app/providers/runpod/weights.py` (321 lines)

Which weights a worker really loaded (lines 1-25): expected = the Owner's settings (written by the
copy pod's success) else the worker image's pin `backend/runpod_worker/mirrors.lock.json`
(`MIRRORS_LOCK`, 114). Also the unbilled-wait indicator.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `endpoint_pin_ro` | 63 | The two env variables the worker reads its pin from | Owner's console step | CODE_RULE |
| `WeightsProblem.as_dict` / `words_ro` | 88 / 91 | Problem record and Owner sentence (endpoint, expected, found, console steps) | Card and stop words | CODE_RULE |
| `_worker_pins` | 119 | Read `mirrors.lock.json` (40-hex revisions only) | Fallback expectation | CONFIG |
| `expected_weights` | 136 | (repo, revision): settings first, else worker pin (revision only when repos match) | — | CONFIG |
| `console_steps_ro` | 150 | Per endpoint: Model field and env pin values | No API for the cached-model field | CODE_RULE |
| `readiness_problem` | 167 | Under `cache`, refuse until repo and revision are known | A round would only buy a worker that cannot find its models | CODE_RULE |
| `reported_revision`, `_code` | 185, 190 | Extract revision / weights code | — | — |
| `check_result` | 197 | Weights problem from a result or error (never for mock or when no revision is reported) | ADR-RUNPOD-WEIGHTS-CHECK | CODE_RULE on EXTERNAL |
| `weights_key` | 231 | `runpod_weights:<integration>:<purpose>` | Card dedupe | — |
| `raise_weights_card` | 235 | `decisions.sources.ask(...)` with `runpod_weights_card` | The Owner's console step | CODE_RULE (raises OWNER card) |
| `_holding` | 249 | Card open, refused, or accepted with apply type `none`, AND same expected revision | A new copy releases the hold | OWNER |
| `weights_hold` | 263 | Words when the endpoint is held | `precheck` / `open_session` | OWNER |
| `note_queue` / `clear_queue` / `forget_waits` | 296 / 304 / 309 | In-process IN_QUEUE timers (`forget_waits` used by tests) | — | — |
| `model_wait` | 314 | `WAIT_WORDS_RO` once queued past the notice (60 s) | Page shows the unbilled wait | CODE_RULE |

### `app.providers.runpod.gpu_guard` — `backend/app/providers/runpod/gpu_guard.py` (354 lines)

The GPU guard (lines 1-23): not the watchdog and not a scheduled job (both are behind STOP AUTONOMIE);
runs in the process that holds the worker's lock: BOOT (60 s bound), a loop, and at shutdown via
`force_off` (`backend/app/main.py:430-470`, `636-656`, gated by `settings.runpod_guard_enabled`,
default true, `backend/app/config.py:511`).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `reset_counters` | 91 | Clear unreadable counters (tests) | — | — |
| `_count_unreadable` | 96 | Consecutive unreadable ticks per endpoint | Letter at the 3rd | CODE_RULE |
| `_expire_sessions` | 103 | BOOT orphans, TICK TTL/stale → `FORCED_OFF` | Sessions no step will close | CODE_RULE |
| `_drifted` | 149 | min, idleTimeout, flashboot, timeout vs baseline | Cost-reducing repair | CODE_RULE |
| `_check_endpoint` | 162 | Under endpoint lock: in use (OPENING/OPEN row) → skip; unreadable → count/letter at the 3rd; able to bill → off + event + guard letter (+ `_tell_off` event/letter if not verified); otherwise drift → baseline + event (drift is checked only on an endpoint already OFF) | A GPU found on with no paid step open is switched off | CODE_RULE |
| `run_gpu_guard` | 254 | One pass: copy pods, listed targets (none and not BOOT → stop), (SHUTDOWN → `force_off`), expire sessions (TTL letter), check each endpoint (errors isolated; a target whose vault is unreadable is only counted `unreadable`, never checked or switched off, `299-301`) | «Never consults the kernel's stop» | CODE_RULE |
| `_watch_copies` | 312 | `pods.watch_copies`, errors swallowed | — | CODE_RULE |
| `next_interval` | 325 | 60 s vs 600 s | Tight watch only while money can flow | CODE_RULE |
| `guard_intervals` | 344 | From the first controllable integration, else defaults | — | CONFIG |

Events: `runpod.gpu_guard_unreadable`, `runpod.gpu_guard_off`, `runpod.endpoint_settings_drift`.
Letters: «GPU-ul RunPod a fost oprit de paznic», «Nu pot verifica GPU-ul RunPod», «Un pas a ținut
GPU-ul RunPod prea mult» (lines 72-85).

### `app.providers.runpod.pods` — `backend/app/providers/runpod/pods.py` (1,372 lines)

The ONE-TIME copy pod that fills the Owner's private Hugging Face mirrors (lines 1-39). The Owner's
accept of the card «Copiez modelele în contul tău Hugging Face cu un server RunPod temporar?» IS the
press (`decisions/sources.py:1236-1260` → `start_copy`). A CPU pod runs the inline `BOOTSTRAP` script
(112-275: sha256-checks every file, pins pip, runs `runpod_worker.build mirror --execute` per image,
PUTs results to the bucket, cuts itself at `not_after`, terminates itself with its pod-scoped key —
«UNPROVEN until the paid run», 109-111). Table `runpod_copy_pod` (`CopyPodRow`, 278-310, migration
0057).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `CopyRefused.__init__` | 316 | Nothing started; Owner's reason | — | — |
| `default_transport`, `_now`, `_when`, `_decimal` | 321-346 | Helpers | — | — |
| `PodControl.__init__` / `_call` | 356 / 360 | REST v2 pods; GET/DELETE retried on transient; POST create sent once | An unanswered create is swept by name, never resent | CODE_RULE |
| `PodControl.create` | 402 | `POST /v2/pods`; answer must carry an id | **Starts a billed pod** | EXTERNAL |
| `PodControl.get` | 408 | Read; 404 → None | — | EXTERNAL |
| `PodControl.terminate` | 417 | DELETE then read: True once gone or TERMINATED | Verified end | CODE_RULE |
| `PodControl.named` | 427 | List pods by name prefix (≤ 50 pages) | Sweep | EXTERNAL |
| `_his_card` | 450 | The allowing card under the cap the Owner read | The Owner's accept is the only start | OWNER (checked by code) |
| `_worker_files` | 509 | `backend/runpod_worker` files (no pycache) | Shipped to the pod via bucket | CODE_RULE |
| `_unpinned_motion` | 519 | Motion lock entries without sha256 | Pod runs `build resolve` first | CONFIG |
| `result_key` | 535 | `<prefix>mirror-copy/<id>/<image>.json` | — | — |
| `_plan` | 539 | Upload files content-addressed, presign GET/PUT URLs, build plan with `not_after`, pip pin, pre-steps | The pod holds no bucket key | CODE_RULE |
| `_integration` | 611 | Config + vault secrets or `CopyRefused` | — | CONFIG |
| `_missing` | 628 | Mock, key, bucket, HF token, mirror repo names | Refuse with the Owner's reason | CODE_RULE |
| `_event` | 645 | Append event on `runpod_copy_pod` | — | — |
| `start_copy` | 654 | See Who decides; rows FAILED with `UPLOAD_FAILED`, `BODY_TOO_LARGE`, `CREATE_REFUSED_<n>` (with RunPod's words) or `CREATE_UNCERTAIN` (sweep); RUNNING + event `runpod.mirror_copy_started`; a copy stopped during create is terminated | ADR-RUNPOD-MIRROR-COPY | OWNER + CODE_RULE |
| `_started` | 812 | Start time, rate (RunPod's `cost` when > 0, else the configured 1.00: a PROVISIONING pod reads 0.0, `781`), event `runpod.mirror_copy_started` | — | EXTERNAL / CONFIG |
| `_SameCopy.__init__` / `_no_second_copy` | 847 / 852 | Retried accept → same copy; any live copy → refuse; checked twice (second under write lock) | Two accepts at once start one pod | CODE_RULE |
| `_cap_seconds` | 866 | Pod's own deadline | Pod ends itself if the PC is off | CODE_RULE |
| `_end_unwanted` | 876 | Terminate a pod whose copy was stopped during create | — | CODE_RULE |
| `_close` | 895 | Finish a row (status, error, verified, cost, result) | — | — |
| `_sweep` | 925 | Terminate exact-named pods not owned and not spared | Lost creates, crashed studios | CODE_RULE |
| `_vendor_reason`, `_scrubbed` | 955, 969 | RunPod's detail/issues with HF tokens cut | First accept's bare HTTP 400 (2026-10-09) | CODE_RULE |
| `_results` / `_verdict` | 976 / 987 | Read result JSONs; SUCCEEDED/FAILED/None | — | EXTERNAL |
| `_record_revisions` | 999 | Write mirror repos/revisions into the integration config | Unblocks paid steps under `cache` | CODE_RULE |
| `_console_steps` | 1018 | Console steps text for the success letter | No API for the Model field | CODE_RULE |
| `_follow_up` | 1038 | Letter (cost, cap, termination status); on non-success a fresh copy card | The Owner decides again | CODE_RULE (raises OWNER card) |
| `_finish` | 1098 | Terminate, cost = rate × lifetime, status, revisions, event `runpod.mirror_copy_finished`, follow-up | — | CODE_RULE |
| `live_copy` | 1160 | Any CREATING/RUNNING row | Guard short interval | CODE_RULE |
| `watch_copies` | 1170 | Guard pass over copies (see Who decides) and sweep | Always terminated | CODE_RULE |
| `_reported` | 1279 | At BOOT/SHUTDOWN keep a finished copy's verdict | Revisions are not thrown away | EXTERNAL |
| `_creating_now` | 1297 | Created < 15 min ago | Spare a create in progress | CODE_RULE |
| `_verify_rows` | 1302 | Ended rows whose pod is no longer listed → `terminate_verified` | — | CODE_RULE |
| `_look` | 1319 | Verdict, pod ended → FAILED, rate update, time cap, cost cap | — | CODE_RULE / EXTERNAL |

External: **RunPod pod create (CPU pod billing)**, pod list/get/delete; the Owner's bucket; Hugging
Face (inside the pod, with the Owner's token in the pod's env).

### `app.providers.runpod.provider` — `backend/app/providers/runpod/provider.py` (652 lines)

`RunPodGenerationProvider`: the per-request core used by the adapters (journal, status mapping,
download and persistence, health, catalogue). On real Serverless every purchase is refused here
(`NEEDS_GPU_ROUND`), so in production only `get_job`, `collect_batch_item`, `result_bytes`,
`persist_result`, `health` and `available_models` run.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `__init__` | 66 | JobStore, target identity, real or mock client | — | CONFIG |
| `require_enabled` | 85 | `RunPodDisabled` unless configured | — | CONFIG |
| `generate_image` / `generate_video` / `finalize_video` | 89 / 92 / 95 | `_submit` per operation (`finalize_video` has no caller in `backend/app`) | Legacy interface | — |
| `_submit` | 98 | Serverless real → `NEEDS_GPU_ROUND`; refuses mock controls on paid; routes model; ≤ 10 MB; reserve; existing row without remote id → `SubmissionUncertain`; Pod `auto_start` readiness; submit; save remote id first; failure: proven refusal → FAILED 0 cost, else `SUBMISSION_UNCERTAIN` | ADR-RUNPOD-NO-LONE-RUN; never resubmit an uncertain intent | CODE_RULE |
| `_status` | 187 | Map RunPod status, times, GPU seconds (or `executionTime`/1000), cost = seconds × rate/3600 (0 mock), allowed output fields only | — | EXTERNAL + CODE_RULE |
| `get_job` | 241 | Terminal → row; no remote id → `SubmissionUncertain`; batch item → `collect_batch_item`; else `/status` | Watchdog and adapters | CODE_RULE |
| `collect_batch_item` | 254 | Mock: stand-in `BatchRun.poll`; real: `collect_row` with a client for the purpose's endpoint | The watchdog's path after a restart | CODE_RULE |
| `storage_root` | 292 | Adapter media root or studio default | — | CONFIG |
| `recover_submission` | 300 | Attach a remote id only when RunPod's answer echoes the saved idempotency key (no caller in `backend/app`; tests only) | Explicit reconciliation | CODE_RULE |
| `stop_if_idle` | 320 | Pod mode `auto_stop` after `idle_shutdown_minutes` (no caller in `backend/app`) | Legacy Pod | CONFIG |
| `wait` | 344 | Poll until terminal within `job_timeout`; timeout → `TaskStillOpen` | Legacy image path | CODE_RULE |
| `cancel_job` | 361 | Cancel a non-terminal row with a remote id (no caller in `backend/app`) | — | CODE_RULE |
| `result_bytes` | 372 | Batch row: presigned GET of `output.key` + sha256; else URL download, image/MP4 checks, optional sha256 | — | CODE_RULE |
| `persist_result` | 402 | Cached asset if sha256 matches; else download and atomic write under `<root>/runpod/` | — | CODE_RULE |
| `record_quality` | 434 | QA verdict on a COMPLETED row (no caller in `backend/app`) | — | — |
| `regenerate` | 440 | New attempt only after QA rejection; refuses batch rows / digest pictures (no caller in `backend/app`) | «belongs to its paid step» | CODE_RULE |
| `health` | 474 | Reading dict; Serverless → `_serverless_health` | Connection check | EXTERNAL |
| `_serverless_health` | 516 | Per endpoint GET settings + `/health`: `workers.min ≠ 0` and wrong image are problems; bucket required; scaled-to-zero is healthy | Verified without any `/run` | CODE_RULE / EXTERNAL |
| `available_models` | 585 | Serverless: pinned catalogue for configured endpoints; else `/models` | Never a paid `/run` to discover models | CONFIG |
| `metrics` | 609 | `generation_metrics` (no caller in `backend/app`) | — | — |
| `get_compute_status` / `ensure_compute_available` / `start_compute` / `stop_compute` | 612 / 628 / 631 / 634 | Pod control wrappers; `stop_compute` refuses while any job is non-terminal | Frozen Pod mode | CONFIG |
| `_stand_in` | 649 | `batch._request_of` | — | — |

### `app.providers.runpod.compute` — `backend/app/providers/runpod/compute.py` (78 lines)

Opt-in control of an existing Pod via REST v2 (frozen legacy path).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `ComputeControl.__init__` | 14 | Client forced to pod mode on `https://api.runpod.io` | — | — |
| `require_resource` | 26 | Enabled, not mock, pod mode, pod id, key; mutations also need `allow_infra_actions` | Infra permission | CONFIG |
| `status` | 41 | GET pod; returns only id/status/actions/gpu/cost («never return or store» env and SSH credentials, 44) | Secret hygiene | EXTERNAL |
| `action` | 47 | start/stop only, idempotent against current state, only actions RunPod offers | **Pod start bills** | CONFIG + EXTERNAL |
| `ensure` | 66 | Running, or start if `auto_start`, wait ≤ `job_timeout` | — | CONFIG |

### `app.providers.runpod.adapters` — `backend/app/providers/runpod/adapters.py` (427 lines)

Fits RunPod into the studio's `ImageProvider` / `VideoProvider` interfaces and the SceneTake
collection protocol.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `inline_image` | 33 | PNG/JPEG/WebP ≤ 5 MB → data URI | Legacy path | CODE_RULE |
| `RunPodConnection.__init__` | 52 | Core provider, model (`AUTO` default), provider name `RUNPOD`/`RUNPOD_MOCK`, media root, mock warning | — | CONFIG |
| `bind_scene` | 85 | Film/scene/quality context (HERO when the model equals the HERO route) | Legacy request identity | CODE_RULE |
| `_request_context` | 104 | Attempt, original prompt and QA history from the latest row: pending → recovered; finished but unjudged/uncollected with same prompt and seed → reused; else next attempt with history | «a redo with no verdict never reuses a spent key (2026-10-08)» | CODE_RULE |
| `supports_batch` | 192 | Serverless and configured | Stages choose rounds | CONFIG |
| `round_overhead_usd` | 196 | (cold start + idle) × rate / 3600; 0 for mock (no caller in `backend/app`; `pricing.py:79-88` computes the same) | Round overhead | CONFIG |
| `submit_batch` | 204 | `batch.submit_round` | The round entry used by `media/gpu_batch.py:391` | CODE_RULE |
| `health_check` | 224 | HEALTHY when backend healthy and authenticated (or mock) | Connection verification (`integrations/discovery.py:457`) | EXTERNAL |
| `list_models` | 233 | Catalogue rows with `model_id` | Discovery (`integrations/discovery.py:470`) | CONFIG |
| `collect_task` | 236 | Row state → SUCCEEDED/FAILED/RUNNING; outputs bytes when COMPLETED | Watchdog / assembler `collect_task` (`media/assembler.py:10510`) | CODE_RULE |
| `_raw` | 261 | Raw response summary | — | — |
| `RunPodImageAdapter.ACCEPTS_REFERENCE_IMAGE` / `MAX_REFERENCES` | 282 / 288 | From `reference_spec` (`REFERENCE_IMAGE_VERIFIED = False`, 279) | Never claim a picture was used when the graph ignores it | CONFIG |
| `RunPodImageAdapter.generate_image` / `_image` / `generate_candidates` | 293 / 323 / 353 | Legacy per-request still (refused `NEEDS_GPU_ROUND` on real Serverless); waits, persists, returns `ImageResult`; errors after submit → `TaskStillOpen` | Legacy interface | CODE_RULE |
| `RunPodVideoAdapter.create_generation` / `get_generation_status` | 385 / 414 | Legacy per-request clip and its status | Legacy interface | CODE_RULE |

### `app.providers.runpod.wiring` — `backend/app/providers/runpod/wiring.py` (84 lines)

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `connection` | 16 | Build the adapter from an integration row + vault: None if not configured, None for a mock in `PRODUCTION`; image/video/base class by purpose; copies `ProviderResource` model metadata | Factory used by `media/factory.py`, `workflows/watchdog.py:534`, `media/shooting_sheet.py:4262` | CONFIG |
| `bind_scene` | 54 | Bind only RunPod adapters | — | — |
| `billing_name` | 59 | `runpod` or `runway` | Billing labels (`media/shooting_sheet.py:3526`, `3557`) | CODE_RULE |
| `sync_take_quality` | 63 | Copy the take's APPROVED/REJECTED onto the COMPLETED journal row («without another QA or writer») | Telemetry acceptance rates | CODE_RULE (copy of a verdict decided upstream) |

### `app.providers.runpod.pricing` — `backend/app/providers/runpod/pricing.py` (137 lines)

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `estimated_prices` | 31 | For each available model of a VERIFIED/ACCESS_VERIFIED RunPod integration: explicit price, else rate × GPU-seconds/3600; skip non-finite/negative, and 0 unless mock («No forecast => no purchase», 65); provenance `ESTIMATED`; Serverless adds the round overhead per purpose and lists the model as a round model; video max seconds; stills model from the image `ServiceSelection`'s `MediaProductionConfig` | Feeds the shooting sheet's caps (`media/shooting_sheet.py:323`) | CONFIG |

### `app.providers.runpod.telemetry` — `backend/app/providers/runpod/telemetry.py` (54 lines)

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `generation_metrics` | 12 | Per film: jobs, estimated GPU cost, jobs with unknown cost, cost per accepted scene / finished short (only when no unknown cost), GPU minutes, regenerations, acceptance by model; `estimate_only: True` | Reporting (`media/shooting_sheet.py:1770`) | CODE_RULE |

### `app.providers.runpod.mock` — `backend/app/providers/runpod/mock.py` (134 lines)

Explicit no-GPU transport; outputs are real deterministic files, 0 credits.

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `png` | 18 | Deterministic PNG (72×128) | Mock still | CODE_RULE |
| `video` | 35 | FFmpeg `testsrc2` MP4 (72×128) | Mock clip | CODE_RULE |
| `MockRunPodClient.__init__` / `submit` / `status` / `cancel` / `health` / `models` / `download` | 72-134 | First poll RUNNING then COMPLETED (FAILED when `mock_failure`), health marks `NO_GPU_MOCK`, mock catalogue | Offline tests and simulation | CODE_RULE |

### `app.providers.runpod.setup_steps` — `backend/app/providers/runpod/setup_steps.py` (738 lines)

The Owner's «RunPod pornit» switch and the read-only «Pașii configurării» checklist (lines 1-23).

| Function | Line | What it does | Why it exists | Decided by |
|---|---|---|---|---|
| `SwitchRefused.__init__` | 84 | Reason + HTTP status (409/404) | — | — |
| `_row`, `_integration`, `_stored`, `_environment`, `_not_verified_ro`, `_switch_words` | 90-158 | Row builder, integration lookup (404), stored switch, env value, words | — | — |
| `_state` | 125 | Effective `on` = stored switch, else env; `can_turn_on` = VERIFIED | — | OWNER / CONFIG |
| `switch_state` | 161 | Page state | — | — |
| `set_switch` | 167 | Owner's act: ON needs VERIFIED; writes `config.enabled`, version +1, event `runpod.switch_changed`; OFF → `_switch_off` | ADR-RUNPOD-OWNER-SWITCH | OWNER + CODE_RULE |
| `_switch_off` | 211 | `force_off(OWNER_OFF)` on this integration + `watch_copies(SHUTDOWN)` (not filtered by integration: it ends the live copy pods of every RunPod integration); records no Owner hold | OFF acts at once | CODE_RULE |
| `checklist` | 238 | Rows; with `fresh`, read endpoints and bucket and store `runpod.setup_checked` | Owner's remaining steps | CODE_RULE |
| `_live_gpu_session` | 308 | Any live session | Allowed `workers.max` | — |
| `_decision_states` | 319 | Latest status of `runpod_infra_actions`, `runpod_mirror_copy`, `runpod_bake*` cards | Checklist rows | OWNER |
| `_read` | 341 | Endpoints and bucket concurrently | — | — |
| `_api_key` | 352 | Key present | — | — |
| `_read_endpoint` | 356 | GET settings (10 s, no retry); 401/403, 404, other errors as red rows; drift check | GET only, never a write | EXTERNAL |
| `_read_words` | 405 | What RunPod actually answered | Never assume a missing field | — |
| `_drift` | 422 | min ≠ 0, max > allowed (1 only during a live session), idle, flashboot, timeout | — | CODE_RULE |
| `_read_bucket` | 444 | Presigned HEAD (300 s, 10 s timeout) | Read only | EXTERNAL |
| `_endpoint_link` | 496 | Console link | — | — |
| `_rows` | 502 | 16 rows: API key, endpoint ids, two endpoints, cached model (grey: not readable), bucket, HF token, LTX licence (grey), mirror repos, mirror revisions, three card rows, worker repo (grey), billing (grey), switch | Setup map | CODE_RULE |
| `_decision_row` | 723 | Card row words | — | — |

### `app.providers.runpod.router` — `backend/app/providers/runpod/router.py` (159 lines)

Mounted at `/api/v1` (`backend/app/main.py:993`), prefix `/runpod`, every route behind
`require_owner` (`router.py:57`).

| Function | Line | Route | What it does | Decided by |
|---|---|---|---|---|
| `_off_words` | 50 | — | Verified / unverified / no-RunPod words | — |
| `create_runpod_router` | 56 | — | Builds the router | — |
| `get_gpu` | 60 | `GET /api/v1/runpod/gpu?fresh=0\|1` | `gpu_status` | OWNER (view) |
| `post_gpu_off` | 67 | `POST /api/v1/runpod/gpu/off` | Idempotent by `command_id` (409 on conflict): records the hold BEFORE the off, `force_off(OWNER_OFF)`, proposes the hold card, remembers the answer `{readings, verified, words_ro, hold: true, card_id}` | OWNER |
| `get_setup` | 121 | `GET /api/v1/runpod/integrations/{id}/setup` | Checklist from the last check, nothing called | OWNER (view) |
| `check_setup` | 134 | `POST /api/v1/runpod/integrations/{id}/setup/check` | Checklist with fresh GET/HEAD reads | OWNER |
| `put_switch` | 147 | `PUT /api/v1/runpod/integrations/{id}/switch` | `set_switch` (`SwitchRefused` → HTTP 409 not verified / 404 no such integration) | OWNER |

Line numbers are the `def` lines (the route decorator is on the line above), as in the inventory.

## Connections

**Callers into this package** (from `backend/app`, outside it):

| Caller | Uses |
|---|---|
| `media/gpu_batch.py:54-71`, `391`, `533` | `BatchRequest`, `BatchRefused`, `refusal_words`, `step_stop`, `UNSENT`, `UNCERTAIN`, `NOT_QUEUED_*`, `gpu_session`, `precheck`, `StepPermit`, `GpuForcedOff`, `GpuSessionRefused`, `adapter.submit_batch`, `run.prove_unsent` / `mark_unsent` / `settle` / `billed_seconds_estimate` / `weights_problem`, `weights.raise_weights_card` — the round loop with the cap, the meter and the step stop |
| `media/stills_stage.py:181-189`, `1987`, `2422` | `item_seed`, `supports_batch`, `bind_scene`, `sync_take_quality`, `StepPermit`, `GpuSessionRefused` |
| `media/assembler.py:122`, `11058-16255` | motion / test shot / scene redo rounds, `supports_batch`, `StepPermit`, `UNCERTAIN`, `billing_name`, `bind_scene`, `sync_take_quality`; `collect_task` (`10510`) |
| `media/factory.py:249`, `306`, `514`, `828` | `wiring.connection`, `RunPodConfig` |
| `media/shooting_sheet.py:155`, `323`, `1770`, `3526`, `3557`, `4262` | `OVERHEAD_LINE_RO`, `pricing.estimated_prices`, `generation_metrics`, `billing_name`, `connection` |
| `media/runpod_unsent.py:96-99` | The Owner's release of a legacy uncertain hold: `PROOF_EVENT`, `UNCERTAIN`, `UNSENT`, `GpuSessionRow`, `overlapping_sessions`, `GenerationJob`, `TERMINAL` |
| `media/film_close.py:202-210` | Refuses to close a film with a live GPU session |
| `media/picture_qc.py:621`, `media/director_qc.py:2089` | `GenerationJob`, `sync_take_quality` |
| `workflows/watchdog.py:533-534` | Collects SUBMITTED RunPod takes after a restart through `wiring.connection` → `RunPodConnection.collect_task` → `get_job` → `collect_batch_item` |
| `main.py:57-59`, `430-470`, `636-656`, `993` | Guard BOOT / loop, `force_off(SHUTDOWN)` (20 s bound), router |
| `decisions/sources.py:399-500`, `1183-1260`, `1292` | Cards `runpod_infra_actions`, `runpod_weights`, `runpod_mirror_copy`; appliers `apply_runpod_infra` (sets `allow_infra_actions`), `apply_runpod_mirror_copy` (`pods.start_copy`) |
| `decisions/producers/gpu_hold.py:85-104` | Hold card; «Permite din nou» → `set_owner_hold(False)` |
| `decisions/seed.py:431-432` | Proposes cards using `RunPodConfig`, `expected_weights` |
| `integrations/discovery.py:438-470`, `599`; `integrations/services.py:56` | Connection verification (`health_check`, `list_models`) which sets VERIFIED — the precondition of the switch ON |
| `media/production_policy.py:3351` | `RunPodConfig` |
| `scripts/runpod_gpu_off.py:41-61` | Launcher off: `force_off(LAUNCHER_STOP / SHUTDOWN / OWNER_OFF, fast)` |

**Calls out to:** `app.services` (`may_act`, `_runpod_infra_allowed`, `append_event`,
`command_hash`, `recall_command`, `remember_command`, `utc_now`), `app.agents.messages.post_message`
(letters), `app.decisions.*` (cards, `_own_transaction`, `ask`, `OwnerDecision`, `_inner_command_id`,
`producers.gpu_hold.propose_gpu_hold_card` from the router), `app.media.*`
(`DEFAULT_STORAGE_ROOT`, `PurchaseGuard` type, `SceneTake`, `Storyboard`, `cost_plan`, `toolchain`),
`app.integrations.*` (`Integration`, `ProviderResource`, `ServiceSelection`, `MediaProductionConfig`,
`CredentialVault`), `app.providers.media_http` (transport, errors), `runpod_worker.contract`
(`backend/runpod_worker/contract.py`: `CONTRACT`, `MAX_ITEMS`, `WORKFLOWS`, keys, validators),
`app.db.lock_for_write`.

**Events emitted:** `runpod.gpu_session_opened`, `runpod.gpu_off_verified`,
`runpod.gpu_off_unverified`, `runpod.gpu_forced_off`, `runpod.owner_hold`, `runpod.run_queue_proof`,
`runpod.run_paused`, `runpod.gpu_guard_off`, `runpod.gpu_guard_unreadable`,
`runpod.endpoint_settings_drift`, `runpod.mirror_copy_started`, `runpod.mirror_copy_finished`,
`runpod.switch_changed`, `runpod.setup_checked`. **Events consumed:** `runpod.owner_hold` (newest
wins), `runpod.setup_checked` (cached checklist rows).

**Tables:** `cloud_generation_job` (journal), `gpu_session`, `runpod_copy_pod` (owned here);
`integration` config written by `set_switch` and `_record_revisions`.

## Owner touchpoints

| Touchpoint | Where | What the Owner decides |
|---|---|---|
| «Oprește GPU acum» button | `POST /api/v1/runpod/gpu/off`, `router.py:66-118` | Switch every RunPod GPU off now AND hold every paid step until allowed again; works under STOP AUTONOMIE |
| Hold card «Ai oprit GPU-ul: pașii plătiți stau până permiți din nou» | `decisions/producers/gpu_hold.py:40-92`; `gpu_session.py:795-803` | «Permite din nou pașii plătiți» lifts the hold |
| GPU switch page | `GET /api/v1/runpod/gpu`, `gpu_session.py:1495-1609` | Sees state, rate, what film/scene/take is being made, last off, hold |
| «RunPod pornit» switch | `PUT .../integrations/{id}/switch`, `setup_steps.py:167-208` | ON (only when VERIFIED) / OFF (always, switches that integration's GPU off and ends every live copy pod). OFF records no Owner hold: while it is OFF the integration is not `configured`, so `precheck`/`open_session` refuse (`NOT_CONFIGURED` / `RUNPOD_OFF`); switching it ON again needs no hold card |
| «Pașii configurării» checklist and «Verifică pașii» | `setup_steps.py:238-305` | Sees which setup steps are missing, with console links |
| Card «Agenții pot porni singuri GPU-ul RunPod în pașii plătiți aprobați?» | `decisions/sources.py:315`, `1183-1230`; read by `precheck` and the kernel | Whether agents may switch the GPU on inside approved paid steps |
| Approval of each paid step (yes per step and plan) | Kernel `services.py:1388-1401`, carried in `StepPermit.approval_id` | Whether that step's purchase happens at all (asked by the stages, not here) |
| Card «Endpoint-ul RunPod pentru imagini/clipuri are alte modele» | `weights.py:235-246`, `263-286` | Fix the Model field in the console («Am făcut-o») or keep that endpoint's GPU off |
| Card «Copiez modelele în contul tău Hugging Face cu un server RunPod temporar?» | `decisions/sources.py:458-500`, `1236-1260`; `pods.py:654` | Start the capped copy pod (default 5.00 USD, 240 min); a new card after a failure |
| Letters | `gpu_session.py:115-118` (off not confirmed), `gpu_guard.py:72-85` (guard off, unreadable, TTL), `pods.py:1050-1074` (copy outcome, cost, console steps) | Informational; console action when asked |
| Console steps only the Owner can take | `weights.py:57-60`, `150-164` | Set the endpoint's cached Model field and the `AMN_MIRROR_REPO` / `AMN_MIRROR_REVISION` env |
| Settings (connection form + vault) | `config.py:96-213`, `wiring.py:16-51` | API key, endpoints, bucket, HF token, mirror repos/revisions, caps |

## Oddities and gaps

- **Dead assignment in `gpu_status`**: `words` is computed for «not configured» / «mock» at
  `gpu_session.py:1571-1574` and the same two branches are computed again at `1579-1582`; the first
  block's result is always overwritten.
- **`run_gpu_guard(reason="SHUTDOWN")` branch is not used by the app**: `main.py:644-651` calls
  `force_off(..., reason="SHUTDOWN")` directly; the guard's own SHUTDOWN branch (`gpu_guard.py:276-286`)
  is reachable only from tests.
- **Provider methods with no caller in `backend/app`** (tests, plus the offline script
  `scripts/check_runpod.py:43-75` for `record_quality` and `metrics`): `recover_submission`
  (`provider.py:300`), `stop_if_idle` (320), `cancel_job` (361), `record_quality` (434), `regenerate`
  (440), `finalize_video` (95), `metrics` (609), `get_compute_status` (612), `start_compute` (631);
  `RunPodConnection.round_overhead_usd` (`adapters.py:196`) has no caller and its formula is
  duplicated in `pricing.py:79-88`.
- **Legacy client addresses the legacy endpoint field**: `RunPodClient.call` builds
  `https://api.runpod.ai/v2/` + `str(config.endpoint_id)` (`client.py:37-41`). The batch code passes a
  copy with `endpoint_id` set per purpose (`batch.py:852-857`, `1899-1902`; `provider.py:276-279`),
  but `RunPodGenerationProvider.client` uses the integration's config as is, so for an integration
  configured only with `stills_endpoint_id` / `motion_endpoint_id` the non-batch calls
  (`get_job` of a non-batch row, `cancel_job`, `recover_submission`) would address `/v2/None/...`.
- **`open_session` does not re-check weights readiness**: `weights.readiness_problem` is read only in
  `precheck` (`gpu_session.py:739-741`); `open_session` re-checks the hold, configuration, bucket,
  weights hold and kernel, but not `WEIGHTS_NOT_READY` (`gpu_session.py:923-942`).
- **`force_off` proceeds without the endpoint lock** when it is not acquired within 1 s (fast) or
  120 s (`gpu_session.py:1309-1312`): the off is sent even if an open or close holds the lock.
- **Zero cost for forgotten items**: an item whose job RunPod no longer knows (404 after 30 min) and
  that has no manifest is written `FAILED/EXPIRED_UNDELIVERED` with `cost_value "0"`
  (`batch.py:1183-1190`), although the job may have run.
- **`BAD_OUTPUT` rows carry no cost**: `_bad_output` sets status and code only (`batch.py:1085`), so
  `generation_metrics` counts them under `jobs_with_unknown_cost` and then reports no cost per
  accepted scene / finished short (`telemetry.py:17-18`, `45-49`), while the caller's comment says the
  item «was made and stays counted» (`batch.py:906-909`) and `_bad_output`'s docstring says «its GPU
  time is paid» (`batch.py:1081`). Only `billed_seconds_value` may reach such a row, through
  `_book_batch` (`batch.py:1114-1125`).
- **Job id length limits differ**: `_post_run` accepts ≤ 90 chars (`batch.py:1677`), `_submit` ≤ 100
  (`provider.py:148`); the column is 200 (`jobs.py:44`) and batch items append `:<index>`.
- **Unproduced card kind**: the checklist's bake-off row reads cards whose kind starts with
  `runpod_bake` (`setup_steps.py:336`), but no code in `backend/app` creates such a card, so the row
  always shows «Cardul pentru testul plătit nu există încă».
- **Pinned worker images are null**: `config/runpod_models.json` has `worker_images: {stills: null,
  motion: null}`, so the health check's «runs another image than the studio's pin» problem
  (`provider.py:552-556`) never fires at present.
- **Copy pod cost stays local**: `runpod_copy_pod.cost_usd`, its event and letter are the only records
  (`pods.py:1119-1155`); no other module in `backend/app` reads `CopyPodRow` or books that cost into
  a spend ledger.
- **Copy pod self-termination is unproven**: «UNPROVEN until the paid run: whether the pod-scoped key
  may terminate its own pod» (`pods.py:109-111`); the guard is the primary stop.
- **Estimates, not bills**: every price is `ESTIMATED` from the catalogue's GPU-second figures, which
  the catalogue itself calls estimates «until the paid bake-off measures them»
  (`config/runpod_models.json` `_note`; `pricing.py:1-10`); billed seconds are an upper bound and the
  booking is never lowered below the forecast (ADR-RUNPOD-BOOKING-NEVER-BELOW). Balance reads are not
  implemented («Soldul nu se poate citi prin API încă», `setup_steps.py:700-708`).
- **Decision log vs code on copy-pod disk**: ADR-RUNPOD-MIRROR-COPY states 200 GB; the code default is
  60 GB (`config.py:193-196`), as superseded by ADR-RUNPOD-COPY-DISK (same log, later entry). Not a
  contradiction in the code; readers of the first ADR alone get the old figure.
- **The Owner's hold is global**: `OWNER_HOLD_EVENT` is one aggregate (`owner_hold`) for every
  integration and endpoint (`gpu_session.py:795-803`); any real paid RunPod step is refused while it
  stands, and a mock integration is never held (`precheck` returns early for mock, `720-721`;
  `open_session` returns before the hold check for mock, `901-922`).
- **GPU_BUSY is still decided after the Owner's yes**: ADR-RUNPOD-PRECHECK-BEFORE-YES leaves it open;
  the one-GPU wait lives only in `open_session` (`gpu_session.py:943-971`).
- **Test-only helpers in production modules**: `forget_readings` (`gpu_session.py:347`),
  `reset_counters` (`gpu_guard.py:91`), `forget_waits` (`weights.py:309`), and the module attributes
  `paused_clock` / `paused_sleep` (`batch.py:1472-1473`) exist so tests can reset state or fake time.
- **The step's own stop is not read between the chunks of one round** (added on re-verification):
  `_submit_remote` calls `_wait_ended(session, None, renew=False)` before each chunk
  (`batch.py:1912-1914`), so a STOP AUTONOMIE, mode change or plan stop pressed mid-round lets the
  round's remaining chunks leave unless RunPod answers «paused» (then `_post_run` reads the stop,
  `batch.py:1693`, `1702`). The Owner's «Oprește GPU acum» is still caught (it forces the session off).
  The comment says this is intended («the chunks of one round leave back to back»); `gpu_batch` reads
  the stop before each round (`media/gpu_batch.py:354-367`).
- **An integration whose vault cannot be decrypted is never switched off and never alarms**: it is
  `listed` (`gpu_session.py:1261-1271`), but `force_off` only records an unverified reading for it
  (`1304-1306`, no request, no event, no letter) and the guard only adds it to `unreadable`
  (`gpu_guard.py:299-301`) without the 3-tick counter, so the «Nu pot verifica GPU-ul RunPod» letter
  (`gpu_guard.py:190-204`) never fires for it. The page shows it as UNKNOWN with the reason.
- **«RunPod pornit» OFF ends every integration's copy pod**: `setup_steps._switch_off` filters
  `force_off` by integration but calls `pods.watch_copies(reason="SHUTDOWN")` for all copies
  (`setup_steps.py:217-231`).
- **The catalogue's `rate_usd_per_hour` is not read**: `config/runpod_models.json` carries "4.00", but
  every price and cost uses `RunPodConfig.hourly_rate` (`serverless_cost_per_hour`, default 4.00,
  `config.py:119`, `357-361`; `pricing.py:63`; the journal's `hourly_rate`, `batch.py:491`); no code in
  `backend/app` reads the catalogue field.
