# syntax=docker/dockerfile:1.7
#
# LAST RESORT ONLY (Owner's cards, 2026-10-09): the endpoints take their weights from RunPod
# cached models and run the small images (Dockerfile.stills, Dockerfile.motion, README.md
# "Where the weights live"). This baked recipe puts 39-78 GB in one layer, which GHCR (10 GB)
# and ECR (~54 GB) refuse; it stays documented, not planned. AMN_MODEL_SOURCE=baked makes the
# worker check the weights under /comfyui/models instead of the cache.
#
# AMN GPU work server for RunPod Serverless: two images, `stills` (Qwen-Image-2512 + SeedVR2)
# and `motion` (LTX-2.5 distilled + Wan 2.2 LightX2V + RIFE), on the official worker-comfyui
# base. Nothing in the studio builds or pushes this: see README.md and
# `python -m runpod_worker.build`. The graphs use ComfyUI core nodes only, checked against the
# source of ComfyUI v0.39.2; UNPROVEN until the paid bake-off runs them. The ComfyUI version
# and every weight are pinned (models.lock.json, build.py) before the first build.
#
# Build context: this folder (backend/runpod_worker). The weights are fetched at build time
# with the Hugging Face token mounted as a BuildKit secret: it is never in a layer, an ENV or a
# URL, and every file is sha256-verified against models.lock.json.

# The newest PUBLISHED base (Docker Hub, read 2026-10-08): 5.11.0 has a GitHub tag but no image.
ARG BASE_IMAGE=runpod/worker-comfyui:5.10.0-base
# Required, no default: the base image's manifest digest (sha256:...), so the base never moves
# (build.py passes the pinned one: the 5.10.0-base OCI index digest, read from the registry).
ARG BASE_DIGEST
# Required, no default: the ComfyUI release the graphs were checked against (0.39.2: core
# LTX-2.5, SeedVR2 and frame-interpolation nodes); another one needs the node check re-run.
ARG COMFYUI_VERSION

FROM ${BASE_IMAGE}@${BASE_DIGEST} AS base
ARG COMFYUI_VERSION
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN test -n "${COMFYUI_VERSION}" || { echo "COMFYUI_VERSION is required" >&2; exit 1; }

# ffmpeg for the clip encode, git for the pinned ComfyUI and custom nodes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg git \
    && rm -rf /var/lib/apt/lists/*

# Move the base's ComfyUI to the pinned release. /comfyui is a full git clone: the base installs
# it with comfy-cli 1.13.0 (`comfy --workspace /comfyui install`, which runs `git clone`; read
# in comfy_cli/command/install.py on 2026-10-08). `python` is the base's /opt/venv.
RUN cd /comfyui \
    && git fetch --depth 1 origin "refs/tags/v${COMFYUI_VERSION}:refs/tags/v${COMFYUI_VERSION}" \
    && git checkout "v${COMFYUI_VERSION}" \
    && python -m pip install --no-cache-dir -r requirements.txt

COPY requirements.txt /opt/amn/requirements.txt
RUN python -m pip install --no-cache-dir -r /opt/amn/requirements.txt

COPY . /opt/amn/runpod_worker/
ENV PYTHONPATH=/opt/amn \
    PYTHONUNBUFFERED=1 \
    COMFY_DIR=/comfyui \
    COMFY_HOST=127.0.0.1:8188

# Our handler replaces the stock /start.sh + handler.py: it starts ComfyUI itself (without
# --disable-metadata, see comfy.start_server) and serves amn.batch.v1 jobs.
CMD ["python", "-u", "-m", "runpod_worker.amn_handler"]

FROM base AS stills
ENV AMN_WORKER_IMAGE=stills AMN_MODEL_SOURCE=baked
RUN python -m runpod_worker.build nodes --image stills --dest /comfyui/custom_nodes
RUN --mount=type=secret,id=hf_token \
    python -m runpod_worker.build fetch --image stills --dest /comfyui

FROM base AS motion
ENV AMN_WORKER_IMAGE=motion AMN_MODEL_SOURCE=baked
RUN python -m runpod_worker.build nodes --image motion --dest /comfyui/custom_nodes
RUN --mount=type=secret,id=hf_token \
    python -m runpod_worker.build fetch --image motion --dest /comfyui
