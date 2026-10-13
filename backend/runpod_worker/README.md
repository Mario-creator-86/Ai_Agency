# AMN RunPod worker (`backend/runpod_worker`)

The GPU work server the studio's RunPod Serverless endpoints run. It is **not** part of the
studio process: it lives in a Docker image built on the official
[`runpod/worker-comfyui`](https://github.com/runpod-workers/worker-comfyui) base, next to a
local ComfyUI. The studio imports only `runpod_worker.contract` (standard library only).

Status: **UNPROVEN.** Proven on fakes only (`tests/test_runpod_worker.py`,
`tests/test_runpod_worker_weights.py`: a fake ComfyUI, a fake bucket, a loopback ComfyUI
server, a fake boto3 client, a fake Hugging Face cache tree, a fake `huggingface_hub`, one tiny
real FFmpeg encode). No image has been built, no weight downloaded, no mirror filled, nothing
sent to RunPod, Hugging Face or GitHub. The four graphs follow the official ComfyUI templates
(`Comfy-Org/workflow_templates`: `image_qwen_Image_2512`, `image_qwen_image_edit_2511`,
`utility_seedvr2_7b_int8_upscale_image`, `video_ltx2_5_i2v`, `video_wan2_2_14B_i2v`,
`utility_video_frame_interpolation`) and use ComfyUI **core** nodes only; every `class_type`,
input name and output slot was checked against the source of ComfyUI **v0.39.2** (commit
`3c1b7a17fdf239d35ce98cc777756f572d089795`) on 2026-10-08/09, and the model file names against
the Hugging Face repo trees (the table is pinned in the test, `COMFY_NODES`). They have never
run: running them, the timings and the quality are the paid bake-off's.

Pinned (public metadata only, nothing downloaded): the base `runpod/worker-comfyui:5.10.0-base`
by its OCI index digest (5.11.0 has a GitHub tag but no published image), ComfyUI `0.39.2`, and
every public weight's revision, sha256 and size from the Hugging Face repo trees. The gated
LTX-2.5 files have their revision and size pinned; their sha256 stays `null` with
`"sha256_status": "PIN_AFTER_GATE"` until the Owner's token pins it from the LFS metadata
(`build resolve`, below). Weights: ~60.3 GB for `stills` (with the reference route), ~77.8 GB
for `motion`, ~138 GB in all.

## Where the weights live (Owner's cards, 2026-10-09)

- **Primary: RunPod cached models.** One cached model per endpoint
  (https://docs.runpod.io/serverless/endpoints/model-caching): the stills endpoint caches the
  Owner's **private** Hugging Face mirror of the stills files, the motion endpoint his private
  mirror of the motion files (HF PRO). Each mirror holds only the locked files, at their
  `mirror_path` (`models.lock.json`, ComfyUI folder layout: `diffusion_models/`,
  `text_encoders/`, `vae/`, `loras/`, `latent_upscale_models/`, `frame_interpolation/`), plus
  `LICENSES/`, a README and `MIRROR_MANIFEST.json`. RunPod downloads it before the worker
  starts, unbilled; a cache miss can happen on **any** round (no free host with the model), so
  the unbilled wait always belongs inside the job TTL (the studio's side).
- **The worker checks it before ComfyUI starts** (`weights.py`): it opens
  `/runpod-volume/huggingface-cache/hub/models--<org>--<name>/snapshots/<revision>/` for the
  **pinned** mirror revision only (never "the first snapshot there is", never just `refs/main`),
  checks every locked file's size (sha256 too with `AMN_WEIGHTS_SHA256=1`: ~60 GB of billed
  reading, off by default; the pinned commit already covers each file's LFS sha256), and writes
  `extra_model_paths.amn.yaml` (passed to ComfyUI with `--extra-model-paths-config`) for every
  folder the graphs read. A wrong or missing snapshot fails every item `WRONG_REVISION` or
  `MODELS_MISSING` before its claim, and ComfyUI is never started on it. Every item result (and
  the job output) carries `weights_revision` and `model_load_seconds`.
- **Which mirror:** the endpoint environment `AMN_MIRROR_REPO` / `AMN_MIRROR_REVISION`, else
  `mirrors.lock.json` in the image. Both null means refused (`WRONG_REVISION`, naming the
  variable to set). The Owner types the two values in the console («Manage → Edit Endpoint →
  Environment Variables») from the studio's letter after the copy; the studio never PATCHes
  the endpoint's env (that is a RunPod release). A new mirror commit then needs no new image.
- **UNPROVEN, measured at the bake-off:** how fast a ~40 GB snapshot loads from the cache;
  whether RunPod names the cache blobs by their sha256 (recorded per file as
  `blob_named_by_sha256`, never a gate); whether RTX PRO 6000 hosts hold the cached model.
- **Last resort: the baked image** (`Dockerfile`, `AMN_MODEL_SOURCE=baked`): the weights inside
  the image under `/comfyui/models`. One 39-78 GB fetch layer: GHCR refuses layers over 10 GB
  and ECR over ~54 GB, and the GitHub integration caps an image at 80 GB and a build at 30 min.
  Kept documented, not planned.

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
2. **refusals before any GPU work**: wrong weights (`MODELS_MISSING`, `WRONG_REVISION`), a
   reference route item without its reference (`NEEDS_REFERENCE`), more pictures than its
   graph has slots (`TOO_MANY_REFERENCES`) or a picture for a graph that binds none
   (`REFERENCE_NOT_ACCEPTED`): a picture is never dropped in silence (adversary 2026-10-09);
3. **time guard**: not enough of `time_budget_seconds` left for one item (the larger of the
   item budget and the slowest *warm* item; the first prompt also loads the models, which
   the studio budgets apart as `cold_start_seconds`): `SKIPPED_TIME`;
4. **claim**: `<prefix>claims/<key>.json` with `If-None-Match: *` (falls back to HEAD then
   PUT on a store that answers 501, safe only because `workers.max` is 1); another job's
   younger claim gives `CLAIMED_ELSEWHERE`;
5. **generate**: inputs fetched from their presigned URLs and sha256-checked, uploaded into
   ComfyUI, the workflow template filled through its `bindings`, the declared **Save** node's
   file read (never a `temp` preview);
6. **deliver**: exact size (Pillow for stills; FFmpeg for clips: a portrait 1088 crops to
   1080, H.264 yuv420p, audio dropped, metadata kept), sha256, upload to
   `<prefix>outputs/<key>.<ext>`, then the manifest (written last).

One item's failure is that item's `FAILED` with an error code (`MODELS_MISSING`,
`WRONG_REVISION`, `NEEDS_REFERENCE`, `TOO_MANY_REFERENCES`, `REFERENCE_NOT_ACCEPTED`,
`COMFY_FAILED`, `COMFY_TIMEOUT`, `COMFY_REJECTED`,
`NO_OUTPUT`, `INPUT_DOWNLOAD_FAILED`, `INPUT_SHA256_MISMATCH`, `POSTPROCESS_FAILED`,
`UPLOAD_FAILED`, `STORAGE_FAILED`, `WORKFLOW_INVALID`, `WORKER_ERROR`); ComfyUI unreachable
fails the remaining items `COMFY_DOWN`; a contract error fails the job.

**Provenance.** The LTX-2.x Community Licence forbids removing metadata, watermarking or
content provenance. The worker starts ComfyUI **without** `--disable-metadata` (the stock
start script uses it), keeps PNG text chunks and MP4 metadata, and lists every C2PA/`uuid`/
JUMBF box it found in `provenance_boxes`, plus `lost:<box>` for any its re-encode could not
carry over. The bake-off decides what to do with a lost box; nothing is stripped silently.

**References.** Only a workflow that declares `references` receives an item's
`reference_images`: the Qwen-Image-Edit-2511 route (`qwen_image_edit_2511_ref_seedvr2`) binds
the first three, in the studio's order (the character's identity sheet first), to
`reference_image`, `reference_image_2` and `reference_image_3`; each is fetched from its
presigned URL and sha256-checked; the LoadImage of an empty slot is pruned with its links. The
Qwen-Image-2512 route is text-to-image and ignores them.

## Models (licence-checked 2026-10-08/09)

| Image | Model | Licence |
| --- | --- | --- |
| stills | Qwen-Image-2512 (fp8) at 928x1664, scaled to 1530x2720, restored by SeedVR2-7B (int8, ComfyUI core nodes) | Apache-2.0 |
| stills | Qwen-Image-Edit-2511 (fp8mixed) + Lightning 4-step LoRA, 1-3 reference pictures, empty 9:16 latent at 928x1664, then the same SeedVR2 stage to 1530x2720 (reference route for locked characters; identity hold UNPROVEN) | Apache-2.0 |
| motion | LTX-2.5 distilled I2V (route 1): two stages 544x960 then x2 latent upsampler to 1088x1920; audio latent sampled (the model needs it), never decoded | LTX-2.x Community Licence: free under 10M USD revenue, AI disclosure, never strip provenance, no product competing with Lightricks without a separate licence; **gated: the Owner accepted it (2026-10-09); his mirror carries the licence with its Attachment A** |
| motion | Wan 2.2 I2V-A14B + LightX2V 4-step LoRA at 720x1280, 16 fps, + core RIFE v4.26 x2 (route 2) | Apache-2.0 (RIFE: MIT) |

Excluded on licence grounds: FLUX dev, Qwen-Image-2.1, Hunyuan*, MiniMax, and the
InsightFace-based identity adapters (research-only face models).

`models.lock.json` lists every weight by its real repo path with its pinned `revision`,
`sha256`, `size_bytes`, `licence_id` (the licence text the mirror copies) and `mirror_path`.
`mirrors.lock.json` names each private mirror (`repo`, `revision`: null until the copy).
`custom_nodes.lock.json` is empty: SeedVR2 and RIFE are ComfyUI core nodes since the verified
release.

## The small images (RunPod's GitHub integration)

`Dockerfile.stills` and `Dockerfile.motion`: no weights, no Hugging Face secret, one image per
file (no multi-stage target), with the base digest and `COMFYUI_VERSION` written in as defaults
(the integration documents only a branch and a "Dockerfile Path": no build args, secrets or
targets). Their context is the worker folder as a repository root:

```
python -m runpod_worker.export_repo --dest <a folder outside the studio>
```

writes that repository (the two Dockerfiles, the handler and its modules, the graphs, the
locks, a README in Romanian with the Owner's steps, `EXPORT_MANIFEST.json`; never the baked
`Dockerfile`). The Owner creates the **private** GitHub repository and pushes it himself; each
endpoint names its Dockerfile path; RunPod rebuilds only on a GitHub **release**. The first
RunPod build and its "Testing" phase are UNPROVEN.

## The mirror copy (one-time copy pod, the Owner's paid card)

```
python -m runpod_worker.build mirror --image stills --repo <owner>/<name>            # plan
python -m runpod_worker.build mirror --image stills --repo <owner>/<name> --execute  # pod only
```

The plan prints every file with its upstream source and its mirror path, and the licence files.
`--execute` refuses unless `AMN_MIRROR_HOST=pod` and `HF_TOKEN` (the Owner's write token, from
the environment, sent to huggingface.co only, never printed) are set; it needs
`pip install -r requirements-mirror.txt` (`huggingface_hub`). Per file: download, sha256 and
size against the lock, upload to the private mirror, the Hub's own sha256 confirmed, the file
deleted from the pod's disk before the next. A file already mirrored is skipped (resumable per
file; a second run uploads nothing). Then `LICENSES/` (Apache-2.0; for motion the LTX-2.x
licence with its Attachment A and the RIFE MIT text, each pinned by commit and sha256), the
README and `MIRROR_MANIFEST.json`; it prints the mirror revision to pin. It refuses a public
repo, and refuses `motion` until the LTX-2.5 checksums are pinned:

```
HF_TOKEN=... python -m runpod_worker.build resolve --image motion   # metadata only
```

## Last resort: the baked image (a build host with Docker; ~70 GB and ~90 GB images)

`Dockerfile` (multi-stage `stills` / `motion`, the weights fetched in one `RUN` with the token
as a BuildKit secret). `python -m runpod_worker.build plan <stills|motion> --registry
<host>/<namespace> --tag <tag>` prints the commands; they run only with `--execute` **and**
`AMN_BUILD_I_ACCEPT_60GB=1`, and push only with `--push`. `fetch`/`nodes` refuse outside their
image's build stage (`AMN_WORKER_IMAGE`). Set `AMN_MODEL_SOURCE=baked` on such an endpoint.

## Endpoint settings (RunPod console, one endpoint per image)

- GPU: **RTX PRO 6000** (96 GB). Read the pool id from `GET /v2/catalog/gpus`.
- Workers: **min 0, max 0** (the studio raises `max` to 1 only while a paid step runs and sets
  it back to 0 right after), **idleTimeout 1** second (the documented minimum, `workers.
  idleTimeout` 1..3600).
- **FlashBoot** on; execution `timeout` **2400000** ms (40 min; each job also carries its own
  `policy.executionTimeout`).
- **Model** (cached model, Manage → Edit Endpoint): the Owner's private mirror for that
  endpoint, with his Hugging Face token. Not settable or readable through the documented REST
  API: the studio checks the `weights_revision` each result reports instead.
- No network volume (a volume pins the GPU to one data centre; the cache does not).
- Endpoint environment (RunPod **secrets** for the keys):
  - `AMN_S3_ENDPOINT_URL` (https, e.g. `https://<account>.r2.cloudflarestorage.com`)
  - `AMN_S3_BUCKET`
  - `AMN_S3_REGION` (`auto` for R2)
  - `AMN_S3_ACCESS_KEY_ID`
  - `AMN_S3_SECRET_ACCESS_KEY`
  - `AMN_MIRROR_REPO`, `AMN_MIRROR_REVISION` (the mirror the cache must hold)
  - `COMFY_HOST` (default `127.0.0.1:8188`; must stay loopback)
  - optional: `AMN_START_COMFY=0` (a ComfyUI already running), `AMN_COMFY_EXTRA_ARGS`,
    `AMN_LOG_LEVEL`, `AMN_WEIGHTS_SHA256=1`, `AMN_HF_CACHE` (another cache folder).

The bucket key should be limited to this one bucket. The studio uploads inputs and reads
manifests with its own copy of the same bucket settings (Integrations window).

## What the paid bake-off must prove here

That the pinned ComfyUI runs all four graphs end to end (the node table was read from the
source, never executed; the int8 convrot and fp8 formats on the RTX PRO 6000); that LTX-2.5
renders portrait 1088x1920 (the card's examples are landscape); whether 2511 holds a
character's identity on an empty 9:16 latent (versus padding picture 1) and with the 4-step
Lightning LoRA; the GPU seconds per still and per clip; the cold start of each image from the
cache (`model_load_seconds`); the cache's blob naming; whether LTX outputs carry provenance
boxes and what the encode loses; whether the bucket honours `If-None-Match: *`; that per-item
manifests appear while the batch is still `IN_PROGRESS`.
