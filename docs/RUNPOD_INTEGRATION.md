# RunPod image and video integration

Implementation guide, 2026-10-07. This adds a provider to the existing Agency; it does not
implement or deploy the cloud generation server. Authentication, endpoint setup and real GPU
tests are deferred at the Owner's request. Automated verification uses offline mocks only.

## Phase 1 — RunPod Serverless, one GPU, rounds of batches (2026-10-08)

Proven on fakes only: nothing in phase 1 called RunPod, Hugging Face, a registry or a bucket,
and no worker image was built. The Owner's decisions and their reasons are the ADRs of
[16_DECISION_LOG.md](project/16_DECISION_LOG.md), section «RunPod Serverless, phase 1»; the
worker image (contract `amn.batch.v1`, ComfyUI workflows, model locks, Dockerfile, build plan)
is documented in [backend/runpod_worker/README.md](../backend/runpod_worker/README.md).

- **Mode.** `RUNPOD_MODE` defaults to `serverless` (the Pod stays possible). Stills go to
  `stills_endpoint_id`, video to `motion_endpoint_id` (the old `endpoint_id` is the fallback of
  both). RTX PRO 6000 96 GB, budgeted at 4.00 USD/h (`serverless_cost_per_hour`).
- **GPU on/off** (`providers/runpod/endpoint.py`, `gpu_session.py`, `gpu_guard.py`): switched on
  (workers.max=1) only inside an approved paid step through the kernel's `infra.gpu_on`, and off
  in the step's `finally` (purge, cancel, workers {min 0, max 0, idleTimeout 1}, verify OFF);
  off is always allowed, including under STOP AUTONOMIE; the Owner's «Oprește GPU acum».
- **Rounds** (`media/gpu_batch.py`, `providers/runpod/batch.py`): a paid step on a Serverless
  adapter (`supports_batch`) buys in rounds. Round 1 is every item the step buys (stills: scene
  1 alone while the film has no Figure 1, then the rest); a later round is what QC sent back
  (still re-rolls; one clip-QC retry per shot). Each round is ONE `POST /run` whose input lists
  every item; a round longer than the executionTimeout cap (2400 s = 120 s cold start + item
  budgets of 180 s a still, 900 s a clip) is cut into chunks POSTed back-to-back before any poll,
  each with `policy.executionTimeout` and `policy.ttl` (+ the 900 s queue wait). Before a round
  is sent it is priced whole (items + one GPU start: (cold start + idleTimeout) × rate) and cut,
  scene by scene, to what is left of the step's cap; the mode guard and the stop are read once
  before each round and polled while it runs; a stop or the Owner's off cancels the unfinished
  jobs, keeps and books what finished, and records the rest «nu s-a cumpărat».
- **Durable items.** Each item reserves its own journal row and key before `/run`; the answer's
  job id is saved on every item row (`remote_job_id` "<job>:<index>", `batch_remote_id`,
  `batch_index`, `gpu_session_id`) and on the GPU session in one transaction, then each take is
  written SUBMITTED, all before any poll. A lost `/run` answer leaves its items
  SUBMISSION_UNCERTAIN: the step stops, and the same keys go out again in a later step, where the
  worker's manifest/claim makes it a free reuse. A spent key (collected, judged, failed) is never
  reused: the item moves to the next attempt.
- **Bucket** (`providers/runpod/s3.py`): pictures go to `inputs/<sha256>.<ext>` of the Owner's
  S3-compatible bucket through a presigned PUT (SigV4 signed by the studio, standard library,
  path-style, AWS's published example pinned in tests) and travel as 2-hour presigned GETs; the
  journal keeps {sha256, bytes, mime}, never base64. An item is collected from
  `manifests/<key>.json` first, then from `GET /status/<job>`; a 404 with no manifest is
  EXPIRED_UNDELIVERED. Outputs are checked by sha256 and kept under the media root; the journal
  keeps the bucket key, never a signed URL. A step is refused before any GPU switch while the
  bucket is not configured.
- **Prices** (`providers/runpod/pricing.py`, `config/runpod_models.json`): a still is its GPU
  seconds × rate/3600 (estimate 60 s), a clip its GPU seconds per video second × seconds × rate
  (estimates 24 s LTX-2.5, 33 s Wan-2.2-LightX2V); each round adds its GPU start
  (`PriceTable.overhead_credits_per_round`, only for the RunPod models of the table). Stills:
  cost = items + one start (two when scene 1 goes first), cap = items × (1 + re-rolls) + every
  round's start. Motion: cost = shots + one start, cap = 2 × shots + 2 starts. The sheet names
  «GPU: pornire și încărcarea modelelor» inside the step's price. The billed estimate per job is
  (delayTime + executionTime)/1000 + idleTimeout, shared over its items by their GPU seconds.
- **Verification without /run.** Health reads each configured endpoint's settings and /health
  (workers.min must be 0; a pinned worker image must match) and requires the bucket; a
  scaled-to-zero endpoint is healthy. The models are the pinned catalogue for the endpoints that
  exist. Media readiness needs the selected model and the bucket.
- **Planner.** Ratios are compared reduced ("9:16" = "1080:1920" = "720:1280") and a frame is
  delivered when the model's declared output reaches it; the Owner's selected RunPod model is
  taken unasked by quality («Totul pe RunPod oricum»): «Profil RunPod selectat de Proprietar: …;
  calitatea se verifică pe clip». Every clip still goes through clip QC.
- **Not in phase 1:** RunPod balance/billing reads (field unconfirmed), and every measurement of
  the paid bake-off card (rate, cold start, idleTimeout honoured, GPU seconds, quality, LTX
  provenance boxes, Restricted-key access, the bucket's If-None-Match).

### Before the first paid test (completeness check, 2026-10-08)

- **Pinned:** the worker base is `runpod/worker-comfyui:5.10.0-base` by digest (the
  `5.11.0-base` the sources named was never published), ComfyUI 0.39.2, and every public
  weight's revision/sha256/size from Hugging Face's own metadata. The gated LTX-2.5 checksums
  are pinned with the Owner's token by `python -m runpod_worker.build resolve --image motion`
  (metadata only). `build plan stills` prints a complete plan today; `motion` waits for resolve.
- **His yes is never spent on a GPU that cannot start:** a RunPod step checks the connection,
  the bucket and his card «Agenții pot porni singuri GPU-ul RunPod …» before it asks for or
  spends his approval (`gpu_session.precheck`, called through `gpu_batch.gpu_precheck`).
- **Still his:** `RUNPOD_ENABLED=true` in `.env` (the form has no switch for it); where the two
  images (~39 GB and ~78 GB of weights) are built and pushed; the registry credentials in
  RunPod; the endpoints; the bucket; the Hugging Face licence and token; the card.
- **Known limits for the test:** Qwen-Image-2512 is text-to-image, so a character with a locked
  look is refused (NEEDS_REFERENCE) and Figure 1 is uploaded but not used by the model; no
  per-scene still redo on RunPod yet; no RunPod balance read (phase 2); `check_runpod.py
  --live` makes read-only GETs only.

## Existing paths reused

`backend/app/providers/runpod/` contains configuration, typed requests, transports, the durable
submission journal, adapters, mock output, compute hooks, pricing and telemetry.

- `RunPodImageAdapter` implements the existing `ImageProvider` and candidates/callback contract.
- `RunPodVideoAdapter` implements the existing asynchronous `VideoProvider`.
- `RunPodGenerationProvider` owns image/video/finalize submission, status, cancellation,
  downloads, health and model inventory. Cloud translation stays in this package.
- Settings uses the existing Integration/vault, discovered ProviderResource catalogue and
  MediaProductionConfig. Factory selection still requires a verified connection and a usable
  model. Selecting a model explicitly admits a CANDIDATE; it does not invent quality scores.
- The existing shooting sheet, Owner approvals, film purchase lease, scene caps, budgets,
  still gate, clip QC, VideoEditor and FFmpeg assembly remain in charge of production.
- SceneTake callbacks persist the remote ID before polling. The existing watchdog collects
  interrupted jobs using their originating integration, even if selections changed later.

Migration `0055_cloud_generation_jobs` adds `cloud_generation_job` to the Agency database.
It is a submission/telemetry journal, not a second worker or queue. Normal Agency startup
applies the additive migration. Back up the database before upgrading an existing checkout.
On this workstation it was also applied to the existing studio.db after a SQLite backup;
all 77 existing tables remained identical and foreign-key validation passed.

## Configuration and credentials

All RunPod placeholders in `.env.example` are empty. Defaults below live in the typed
configuration. Empty environment values use those defaults.

| Variable | Default / meaning |
|---|---|
| RUNPOD_ENABLED | false; blocks cloud calls and factory activation |
| RUNPOD_MOCK | false; explicit offline simulation, excluded from PRODUCTION |
| RUNPOD_MODE | serverless (phase 1, 2026-10-08); pod stays possible |
| RUNPOD_STILLS_ENDPOINT_ID / RUNPOD_MOTION_ENDPOINT_ID | empty; the stills and motion endpoints (fallback: RUNPOD_ENDPOINT_ID) |
| RUNPOD_SERVERLESS_COST_PER_HOUR | 4.00 USD; the budget rate of the RTX PRO 6000 Serverless worker |
| RUNPOD_COLD_START_SECONDS / RUNPOD_IDLE_TIMEOUT_SECONDS | 120 / 1; priced once per round |
| RUNPOD_S3_ENDPOINT_URL, _S3_BUCKET, _S3_REGION, _S3_PREFIX | the Owner's output bucket (keys in the vault) |
| RUNPOD_API_KEY | empty SecretStr; required for real calls |
| RUNPOD_ENDPOINT_ID | empty; real Serverless endpoint |
| RUNPOD_GENERATION_BASE_URL | empty; HTTPS custom API base, without credentials/query |
| RUNPOD_GPU_NAME | RTX_PRO_6000; configured estimate label, not detected hardware |
| RUNPOD_GPU_VRAM_GB | 96; configured capability, not measured availability |
| RUNPOD_GPU_COST_PER_HOUR | 2.09 USD; editable estimate, not verified vendor billing |
| RUNPOD_REQUEST_TIMEOUT | 60 seconds per HTTP call, including its overall deadline |
| RUNPOD_POLL_INTERVAL | 2 seconds |
| RUNPOD_MAX_RETRIES | 3 infrastructure retries after the first safe request |
| RUNPOD_JOB_TIMEOUT | 1800 seconds of local waiting; remote job remains recoverable |
| RUNPOD_ALLOW_INFRA_ACTIONS | false |
| RUNPOD_AUTO_START | false |
| RUNPOD_AUTO_STOP | false |
| RUNPOD_IDLE_SHUTDOWN_MINUTES | 15 |
| RUNPOD_POD_ID | empty; only needed for optional Pod control |
| RUNPOD_POD_CANCEL_PATH | empty; optional documented custom route containing `{job_id}` |
| RUNPOD_MODEL_ROUTES | optional JSON mapping overriding logical routes |

Copy the environment example to the ignored `.env` and fill only real values. Alternatively,
save the API key through Settings → RunPod; the existing credential vault encrypts it. Public
connection fields can override mode, endpoint, backend URL and mock mode; the global enable
switch remains an environment setting. Never put a key in a URL, repository file or screenshot.
`.env`, credential stores and runtime data are excluded by Git.

The Agency sends Bearer authentication. The custom API must enforce that authentication on
its control and generation routes. Use a key restricted to the endpoint operations actually
needed. Pod read/start/stop permissions are only needed if those optional hooks are enabled;
the ordinary generation path never creates, terminates or provisions resources.

The official RunPod Codex plugin 1.5.0 was installed from
[RunPod's marketplace](https://github.com/runpod/runpod-plugins-official). Its bundled MCP
configuration uses `https://mcp.getrunpod.io/`. Codex login/MCP authentication is distinct from
the Agency's environment/vault. Authentication is pending; no account access was verified.
Reload plugin tooling in Codex when connecting it later. No API key has been printed or saved
in this guide.

## Pod transport and custom cloud contract

Set `RUNPOD_MODE=pod`, supply the backend URL/key, and enable RunPod. The Agency calls this
contract over HTTPS, accepting JSON HTTP 200 or 202 for control responses:

| Method / route | Contract |
|---|---|
| POST /generate/image | ImageRequest plus idempotency_key; return job_id and status |
| POST /generate/video | VideoRequest plus idempotency_key; return job_id and status |
| POST /finalize/video | FinalizeRequest plus idempotency_key; return job_id and status |
| GET /jobs/{job_id} | Return status, output and GPU execution data when available |
| GET /health | Health status and authenticated=true after validating the key; optional GPU status |
| GET /models | Read-only models array, with real installed capabilities and estimates |

Common request fields: project_id, scene_id, prompt, negative_prompt, aspect_ratio (9:16),
seed, quality, model, reference_images, attempt_number, candidate_index, original_prompt,
previous_seed, previous_model, qa_reason, qa_feedback and generation_history.

Image requests add width, height and style; QUALITY/HERO are supported. Video requests add
source_image, duration (default 5), fps (24), resolution (1080x1920), motion_strength and
camera_motion; QUALITY/HERO/AUTO are supported. Finalization adds source_video and options.
Agency assembly continues using its existing FFmpeg path; finalization is an optional provider
operation and is not silently added to every film.

Example backend job response:

```json
{
  "job_id": "backend-job-id",
  "status": "COMPLETED",
  "idempotency_key": "the-request-key",
  "gpu_seconds": 120,
  "model": "LTX-2.5",
  "output": {
    "url": "https://your-public-output-host/clip.mp4",
    "model": "LTX-2.5",
    "seed": 42,
    "sha256": "optional-sha256-of-the-delivered-file"
  }
}
```

Use real publicly downloadable HTTPS output URLs, PNG/JPEG/WebP images and MP4 video.
The backend must persist its idempotency key → remote job mapping durably and return the same
job for the same key/payload. A different payload under that key must be refused. Echo the
key in status (or Serverless output) so a lost submit can be reconciled with proof.
An HTTP 200 from a public Pod health route does not prove authentication. Without an explicit
authenticated=true, the Agency reports the endpoint reachable but authentication unverified.

`/models` returns `{"models": [...]}`. Each entry needs a stable id, name, purpose (image/video)
and tasks, such as text_to_image or image_to_video. Supply actual ratios and durations in the
existing catalogue format, e.g. `{"image_to_video":{"min":1,"max":5}}`, plus max_seconds.
Forecast pricing may use per_image_usd/per_second_usd or measured gpu_seconds_per_image /
gpu_seconds_per_video_second. Missing prices are unpriced and cannot be silently treated as
free. The backend must validate source references and enforce remote execution limits.

Custom cancellation has no assumed route in the initial contract. Configure
RUNPOD_POD_CANCEL_PATH only after the backend implements and documents it; cancellation must
return a recognized job state. Without it the provider reports that capability unavailable.

## Serverless transport

Set mode=serverless and supply the real API key/endpoint ID. Submission uses the official
asynchronous `POST https://api.runpod.ai/v2/{endpoint_id}/run`, wrapping the request in
`{"input":{"operation":"image|video|finalize", ...}}`. Status uses GET /status/{id},
cancellation POST /cancel/{id}, and queue health GET /health on that same endpoint.

IN_QUEUE maps to QUEUED, IN_PROGRESS to RUNNING and TIMED_OUT to TIMEOUT. executionTime is
converted from milliseconds to seconds for estimates. The handler's output must conform
to the same URL/model/checksum contract. The reported selected model is retained for AUTO.

Phase 1 (2026-10-08) replaces the per-job serverless path for paid steps by rounds of
`amn.batch.v1` batch jobs (see «Phase 1» above); the per-job path stays for the Pod. Serverless
is verified from the endpoints' settings and /health plus the pinned catalogue
(config/runpod_models.json); no custom base URL is needed and discovery never submits a job.
A /run result expires after 30 minutes; the bucket manifests keep every finished item.

The official API does not document an idempotency-header guarantee for /run. The local journal
prevents resubmission; the handler should still deduplicate its input idempotency_key. A lost
/run response needs remote reconciliation and is never automatically POSTed again.

Sources checked for this implementation:
[Serverless requests](https://docs.runpod.io/serverless/endpoints/send-requests),
[operation reference](https://docs.runpod.io/serverless/endpoints/operation-reference).

## Lifecycle, retry and restart

QUEUED → STARTING/RUNNING → UPLOADING → COMPLETED, or FAILED/CANCELLED/TIMEOUT.
The submission intent is committed before any generation POST. Identity includes the
destination/integration, project, scene, creative attempt, operation and candidate index.
Canonical payload hashes reject accidental reuse with changed intent.

- Repeating the same saved request returns the existing remote job.
- A process that stops after receiving an ID recovers it from the journal/SceneTake.
- A local poll timeout does not assert that the GPU stopped. It raises TaskStillOpen and
  leaves the remote job collectable; the existing production step stops further purchases.
- Poll/download outages after submission also leave the saved task open for collection.
- GETs and POSTs proven unsent can retry with bounded exponential backoff and jitter.
- POST connection establishment is separated from writing the body. A partial send, timeout
  after sending, 502/503 response or missing remote ID can mean work already started.
  The journal remains uncertain; no automatic second purchase is made.
- A proven unsent request or definite non-billable 400/401/403/404/413/422 refusal can reuse the
  same creative attempt/key on a later corrected call. This is infrastructure recovery.
- `recover_submission(local_id, remote_id)` verifies the backend's echoed key before attaching
  an ID to an uncertain intent. An unproved ID is rejected. Do not delete uncertain records.

No background coroutine is installed separately. Asynchronous provider methods run from the
Agency's existing queued/background media work and watchdog. HTTP operations and polling
have bounded timeouts; the web request does not start a second GPU queue.

## QA and output persistence

The existing still gate, clip QC and Owner take decisions write acceptance/rejection into the
RunPod journal in their own short database transaction. A creative retry gets a new attempt
and retains the previous seed/model, original prompt, reason and generation history. Corrective
instructions are passed in the normal prompt and explicit QA feedback. Infrastructure retry
does not consume a new creative attempt. No additional QA agent is installed.

Sources are sent as inline image data from the existing approved assets. One source image is
limited to 5 MB; the complete cloud JSON request is limited to 10 MB. Oversized input is refused
before a generation intent is created. Remote sources/finalization URLs can also be represented
in the typed contract; local filesystem paths do not transfer files to a cloud server.

Successful outputs are downloaded into `STUDIO_MEDIA_ROOT/runpod/` (or the existing media root),
validated by MIME/signature and optional backend checksum, atomically written and journaled
with a local SHA-256. Subsequent reads reuse the verified local copy. Existing stages then keep
the output as their normal SceneTake/MediaAsset. API credentials are never forwarded to output
hosts. Download DNS is checked for public addresses and the socket is pinned; redirects to
another/private host are not followed. The existing media response size cap is 96 MB.

## Models, prices and metrics

Default logical routes:

| Logical route | Cloud model |
|---|---|
| IMAGE_QUALITY / IMAGE_HERO | Qwen-Image-2512 |
| VIDEO_QUALITY | LTX-2.5 (Wan-2.2-LightX2V by explicit model id) |
| VIDEO_HERO | LTX-2.5 |
| VIDEO_AUTO | AUTO; the backend chooses |

Override these through RUNPOD_MODEL_ROUTES JSON. Explicit discovered model choices stay
explicit. Workflow graphs and local ComfyUI nodes are not exposed to Agency agents.

Cloud forecasts are translated into the existing shooting sheet's internal budget units so
the same approvals/caps work. These are not RunPod account credits: the balance is explicitly
not applicable. Purchased steps and redos are booked as ESTIMATED RunPod expenses through the
existing accounting service. No GPU estimate is marked BILLED or used to mint/consume real
treasury cash as a verified bill. Existing providers and explicit paid fallback rules remain.

Per-job telemetry retains provider, GPU label, model, scene, attempt, observed start/finish,
GPU seconds, rate snapshot, estimated USD, status and quality verdict. Missing GPU execution
data stays unknown. `generation_metrics()` / provider.metrics() includes every rejected
attempt in total production cost and reports cost per accepted scene, completed Short cost,
GPU minutes per completed Short, regenerations and acceptance by model. If video jobs exist,
a scene counts as accepted when its video passes. Finish metrics use the existing completed
VideoRenderJob when exposed through the shooting sheet.

The existing sheet's budget disclosure displays these metrics, distinguishing mocks and
unknown costs. This is a GPU execution estimate, not a RunPod invoice: idle Pod time, cold
starts, storage/network charges and actual Serverless pricing can differ. Reconcile actual
bills through the existing accountant workflow.

## Optional compute hooks

ensure_compute_available(), get_compute_status(), start_compute(), stop_compute() and
stop_if_idle() target an existing configured Pod, using the official REST v2
GET /v2/pods/{id} and POST /v2/pods/{id}/action with start/stop. They never create/terminate a
Pod. Returned Pod data is restricted to status/actions/GPU/cost; env and SSH details are discarded.

Mutations require enabled real Pod mode, a key, Pod ID and RUNPOD_ALLOW_INFRA_ACTIONS=true.
AUTO_START additionally permits starting before a fresh generation. AUTO_STOP enables the idle
hook for an explicitly coordinated existing scheduler; no new timer is registered. stop_compute
refuses while journaled generation is nonterminal. Unknown submissions also prevent shutdown.
Keep these flags false until infrastructure automation has been tested against the real account.
Generation readiness failure does not cause a duplicate generation submission.

Sources: [Pod status](https://docs.runpod.io/api-reference-v2/pods/get-a-pod),
[state transitions](https://docs.runpod.io/api-reference-v2/pods/trigger-a-pod-state-transition).

## Checks and activation

```text
uv run --locked python scripts/check_runpod.py --mock
uv run --locked pytest tests/test_runpod_generation.py tests/test_runpod_pipeline.py -q
uv run --locked python scripts/check_runpod.py
```

The first command forces offline mode regardless of cloud environment switches and saves
synthetic image/video, a restart/QA exercise and report under ignored data/runpod-mock-check.
These are test patterns, not Qwen/LTX output. The last command makes only health/models GETs
when configured. Before credentials exist it reports disabled/unconfigured without a cloud call.

When the real server is ready: fill key and Pod backend URL, or key + Serverless endpoint ID +
read-only backend URL; enable RunPod; run the read-only check; verify/discover the connection
in Settings; select its real available image/video models and existing production purposes.
Voice remains on the existing connection. Model rights/quality and normal Owner policy still apply.

After authenticated health/models succeed, paid validation still requires the Owner's explicit
approval: **PREIA TU ACUM - READY FOR PAID GPU TEST**. State the proposed one-image and subsequent
one 5-second I2V test and estimate time/cost from real backend forecasts; do not invent runtimes.
Run nothing paid before that approval. Validate submit/status, downloads/local hashes, costs,
logs and existing QA handoff. This has not been performed during local implementation.

To disable new RunPod activity, set RUNPOD_ENABLED=false, MOCK=false, ALLOW_INFRA_ACTIONS=false,
AUTO_START=false and AUTO_STOP=false, then reload the Agency. Remove/deselect its image/video
selections if desired. Disabling does not terminate work already running remotely; reconcile
or explicitly cancel existing work through its configured transport before disabling access.
Do not enable paid fallback as part of a disable/connection failure.

## Local ComfyUI cleanup

The separately authorized uninstall removed the E:/Studio ComfyUI installation, local model
weights, Python environment/runtime, nodes, caches, startup shortcuts, workflows and obsolete
software backups. Approximately 172.7 GB of inventoried files were removed. Generated films,
outputs, benchmark videos and written reports were preserved. The Nepal film's SHA-256 stayed
unchanged. The old Agency ComfyUI connection and its image/video selections were removed;
voice selection was preserved. Adapter source/tests remain for compatibility with the existing
codebase, while the local application/models are uninstalled. See project/RUNPOD_HANDOFF.md.
