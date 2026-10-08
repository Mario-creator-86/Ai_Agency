# AMN RunPod worker (`backend/runpod_worker`)

The GPU work server the studio's RunPod Serverless endpoints run. It is **not** part of the
studio process: it lives in a Docker image built on the official
[`runpod/worker-comfyui`](https://github.com/runpod-workers/worker-comfyui) base, next to a
local ComfyUI. The studio imports only `runpod_worker.contract` (standard library only).

Status: **UNPROVEN.** Proven on fakes only (`tests/test_runpod_worker.py`: a fake ComfyUI, a
fake bucket, a loopback ComfyUI server, a fake boto3 client, one tiny real FFmpeg encode).
No image has been built, no weight downloaded, nothing sent to RunPod. The three graphs
follow the official ComfyUI templates (`Comfy-Org/workflow_templates`: `image_qwen_Image_2512`,
`utility_seedvr2_7b_int8_upscale_image`, `video_ltx2_5_i2v`, `video_wan2_2_14B_i2v`,
`utility_video_frame_interpolation`) and use ComfyUI **core** nodes only; every `class_type`,
input name and output slot was checked against the source of ComfyUI **v0.39.2** (commit
`3c1b7a17fdf239d35ce98cc777756f572d089795`) on 2026-10-08, and the model file names against
the Hugging Face repo trees (the table is pinned in the test, `COMFY_NODES`). They have never
run: running them, the timings and the quality are the paid bake-off's.

Pinned on 2026-10-08 (public metadata only, nothing downloaded): the base
`runpod/worker-comfyui:5.10.0-base` by its OCI index digest (5.11.0 has a GitHub tag but no
published image), ComfyUI `0.39.2`, and every public weight's revision, sha256 and size from
the Hugging Face repo trees. The gated LTX-2.5 files have their revision and size pinned;
Hugging Face shows their sha256 only to an account that accepted the licence, so the Owner's
token pins them with `build resolve` (below). Weights: about 39 GB in `stills`, 78 GB in
`motion` (plus the ~10 GB base).

## What one job does

One RunPod job carries one **batch** (`amn.batch.v1`, see `contract.py`): every item of one
paid round of a step (stills: each scene's two candidates at exactly 1530x2720; clips: each
scene's shot at 1080x1920, 24 fps, 5-10 s). The models load once per round, and with
`idleTimeout` 1 s the worker stops being billed one second after the last item (Owner,
2026-10-08: «Sunt taxat la secunda, deci trebuie oprit imediat dupa generare»).

Per item, in index order (`amn_handler.py`):

1. **reuse**: the item's manifest (`<prefix>manifests/<key>.json`) and object exist: answered
   again with a fresh presigned URL, ComfyUI untouched (a re-sent uncertain `/run` costs
   nothing twice);
2. **time guard**: not enough of `time_budget_seconds` left for one item (the larger of the
   item budget and the slowest *warm* item; the first prompt also loads the models, which
   the studio budgets apart as `cold_start_seconds`): `SKIPPED_TIME`;
3. **claim**: `<prefix>claims/<key>.json` with `If-None-Match: *` (falls back to HEAD then
   PUT on a store that answers 501, safe only because `workers.max` is 1); another job's
   younger claim gives `CLAIMED_ELSEWHERE`;
4. **generate**: inputs fetched from their presigned URLs and sha256-checked, uploaded into
   ComfyUI, the workflow template filled through its `bindings`, the declared **Save** node's
   file read (never a `temp` preview);
5. **deliver**: exact size (Pillow for stills; FFmpeg for clips: a portrait 1088 crops to
   1080, H.264 yuv420p, audio dropped, metadata kept), sha256, upload to
   `<prefix>outputs/<key>.<ext>`, then the manifest (written last).

One item's failure is that item's `FAILED` with an error code (`COMFY_FAILED`,
`COMFY_TIMEOUT`, `COMFY_REJECTED`, `NO_OUTPUT`, `INPUT_DOWNLOAD_FAILED`,
`INPUT_SHA256_MISMATCH`, `POSTPROCESS_FAILED`, `UPLOAD_FAILED`, `STORAGE_FAILED`,
`WORKFLOW_INVALID`, `WORKER_ERROR`); ComfyUI unreachable fails the remaining items
`COMFY_DOWN`; a contract error fails the job.

**Provenance.** The LTX-2.x Community Licence forbids removing metadata, watermarking or
content provenance. The worker starts ComfyUI **without** `--disable-metadata` (the stock
start script uses it), keeps PNG text chunks and MP4 metadata, and lists every C2PA/`uuid`/
JUMBF box it found in `provenance_boxes`, plus `lost:<box>` for any its re-encode could not
carry over. The bake-off decides what to do with a lost box; nothing is stripped silently.

**References.** The Qwen-Image-2512 route is text-to-image: a still's `reference_images` are
accepted but not used until a workflow declares a `reference_image` binding.

## Models (licence-checked 2026-10-08)

| Image | Model | Licence |
| --- | --- | --- |
| stills | Qwen-Image-2512 (fp8) at 928x1664, scaled to 1530x2720, restored by SeedVR2-7B (int8, ComfyUI core nodes) | Apache-2.0 |
| motion | LTX-2.5 distilled I2V (route 1): two stages 544x960 then x2 latent upsampler to 1088x1920; audio latent sampled (the model needs it), never decoded | LTX-2.x Community Licence: free under 10M USD revenue, AI disclosure, never strip provenance; **gated on Hugging Face: the Owner accepts it with his own account** |
| motion | Wan 2.2 I2V-A14B + LightX2V 4-step LoRA at 720x1280, 16 fps, + core RIFE v4.26 x2 (route 2) | Apache-2.0 (RIFE: MIT) |

Excluded on licence grounds: FLUX dev, Qwen-Image-2.1, Hunyuan*, MiniMax.

`models.lock.json` lists every weight by its real repo path with its pinned `revision`,
`sha256` and `size_bytes` (the gated LTX-2.5 `sha256` stays `null` until `build resolve` runs
with the Owner's token). `custom_nodes.lock.json` is empty: SeedVR2 and RIFE are ComfyUI core
nodes since the verified release. `build.py` refuses to build while a weight, `BASE_DIGEST` or
`COMFYUI_VERSION` is unpinned; `COMFYUI_VERSION` is the release the graphs were checked
against (0.39.2): another one needs the node check re-run first.

## Build and push (a build host with Docker; ~50 GB and ~90 GB images)

1. The base digest, `COMFYUI_VERSION` and the public weights are pinned. Accept the LTX-2.5
   licence on Hugging Face with the Owner's account and export a read token as `HF_TOKEN` in
   the builder's shell (it reaches one `RUN` step as a BuildKit secret, nothing else; it is
   sent to `huggingface.co` only and dropped on the redirect to Hugging Face's storage CDN).
2. Pin the gated LTX-2.5 checksums (metadata only, from `backend/`):

   ```
   python -m runpod_worker.build resolve --image motion
   ```

   It refuses without `HF_TOKEN`, and refuses (writing nothing) when a size differs from the
   lock. `fetch`/`nodes` refuse to run outside their image's build stage (`AMN_WORKER_IMAGE`).
3. Print the plan (from `backend/`):

   ```
   python -m runpod_worker.build plan stills --registry <host>/<namespace> --tag <tag>
   python -m runpod_worker.build plan motion --registry <host>/<namespace> --tag <tag>
   ```

4. Run it only on purpose: add `--execute` **and** set `AMN_BUILD_I_ACCEPT_60GB=1`; add
   `--push` to push to the registry. A private registry needs its credentials in RunPod
   (Settings → Container Registry Auth) and selected on each endpoint.

## Endpoint settings (RunPod console, one endpoint per image)

- GPU: **RTX PRO 6000** (96 GB). Read the pool id from `GET /v2/catalog/gpus`.
- Workers: **min 0, max 0** (the studio raises `max` to 1 only while a paid step runs and sets
  it back to 0 right after), **idleTimeout 1** second (the documented minimum, `workers.
  idleTimeout` 1..3600).
- **FlashBoot** on; execution `timeout` **2400000** ms (40 min; each job also carries its own
  `policy.executionTimeout`).
- No network volume (outputs go to the bucket; a volume would pin the GPU to one data centre).
- Endpoint environment (RunPod **secrets** for the keys):
  - `AMN_S3_ENDPOINT_URL` (https, e.g. `https://<account>.r2.cloudflarestorage.com`)
  - `AMN_S3_BUCKET`
  - `AMN_S3_REGION` (`auto` for R2)
  - `AMN_S3_ACCESS_KEY_ID`
  - `AMN_S3_SECRET_ACCESS_KEY`
  - `COMFY_HOST` (default `127.0.0.1:8188`; must stay loopback)
  - optional: `AMN_START_COMFY=0` (a ComfyUI already running), `AMN_COMFY_EXTRA_ARGS`,
    `AMN_LOG_LEVEL`.

The bucket key should be limited to this one bucket. The studio uploads inputs and reads
manifests with its own copy of the same bucket settings (Integrations window).

## What the paid bake-off must prove here

That the pinned ComfyUI runs all three graphs end to end (the node table was read from the
source, never executed; the int8 convrot and fp8 formats on the RTX PRO 6000); that LTX-2.5
renders portrait 1088x1920 (the card's examples are landscape); the GPU seconds per still and per clip;
the cold start of each image; whether LTX outputs carry provenance boxes and what the encode
loses; whether the bucket honours `If-None-Match: *`; that per-item manifests appear while
the batch is still `IN_PROGRESS`.
