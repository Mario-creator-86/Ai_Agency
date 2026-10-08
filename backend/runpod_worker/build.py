"""Build plan for the two AMN worker images (``stills`` and ``motion``). Never run by the studio.

``python -m runpod_worker.build plan stills --registry <host/ns> --tag <tag>`` only PRINTS the
docker commands. It executes them only with ``--execute`` AND the environment switch
``AMN_BUILD_I_ACCEPT_60GB=1`` (each image is 40-75 GB of weights), and pushes only with
``--push``. It refuses while anything is unpinned: the base image digest, the ComfyUI
version, or any weight's revision/sha256/size or custom node's commit (pinning them is a
bake-off step; null means "not resolved yet").

Inside the image build (Dockerfile), two more subcommands run:
``fetch --image <stills|motion> --dest /comfyui`` downloads every locked weight for that
image with the Hugging Face token mounted as a build secret (/run/secrets/hf_token, never in
a layer, never in ENV, never in a URL; sent to huggingface.co only and dropped on any
redirect to another host) and verifies each file's sha256 and size;
``nodes --image <...> --dest /comfyui/custom_nodes`` clones each locked custom node at its
pinned commit. Both refuse outside their image's build stage (the Dockerfile sets
``AMN_WORKER_IMAGE``), so neither downloads anything when run by hand.

``resolve --image motion`` (by hand, before the motion build) pins the sha256 of the gated
LTX-2.5 files from Hugging Face's metadata with the Owner's ``HF_TOKEN``: metadata only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

HERE = Path(__file__).resolve().parent
#: The newest published base image (Docker Hub, 2026-10-08): 5.11.0 has a GitHub tag only.
BASE_IMAGE = "runpod/worker-comfyui:5.10.0-base"
#: The base image's manifest digest ("sha256:<64 hex>"): the 5.10.0-base OCI index, read from
#: registry-1.docker.io on 2026-10-08 (``docker-content-digest`` of the tag's manifest).
BASE_DIGEST: str | None = "sha256:e9d18d3db15839ebb10c10c824109fc2956f31ef7bf21916220c008855b0d538"
#: The ComfyUI release the graphs were checked against (core LTX-2.5, SeedVR2 and
#: frame-interpolation nodes; tests/test_runpod_worker.py COMFY_NODES). Another release needs
#: the node check re-run first.
COMFYUI_VERSION: str | None = "0.39.2"
TARGETS = ("stills", "motion")
EXECUTE_SWITCH = "AMN_BUILD_I_ACCEPT_60GB"
#: Set by each Dockerfile stage (stills / motion); fetch and nodes run only under it.
STAGE_ENV = "AMN_WORKER_IMAGE"
#: The only host the Hugging Face token is ever sent to.
TOKEN_HOST = "huggingface.co"
TOKEN_PATH = Path("/run/secrets/hf_token")
REGISTRY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.\-]*(:[0-9]+)?(/[a-z0-9][a-z0-9._\-]*)*$")
TAG_PATTERN = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}$")
DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
CHUNK = 8 * 1024 * 1024

Target = Literal["stills", "motion"]


def load_models_lock() -> list[dict[str, Any]]:
    return list(json.loads((HERE / "models.lock.json").read_text(encoding="utf-8")))


def load_nodes_lock() -> list[dict[str, Any]]:
    return list(json.loads((HERE / "custom_nodes.lock.json").read_text(encoding="utf-8")))


def _target(value: str) -> Target:
    if value == "stills":
        return "stills"
    if value == "motion":
        return "motion"
    raise ValueError(f"target must be one of {TARGETS}")


def _weight_problem(entry: dict[str, Any]) -> str | None:
    name = entry.get("name", "?")
    if not entry.get("revision") and not entry.get("url"):
        return f"{name}: revision (or url) not pinned"
    if entry.get("revision") and not HEX40.fullmatch(str(entry["revision"])):
        return f"{name}: revision must be a 40-hex commit"
    if not entry.get("repo") and not entry.get("url"):
        return f"{name}: no repo and no url"
    if not HEX64.fullmatch(str(entry.get("sha256") or "")):
        return f"{name}: sha256 not pinned"
    size = entry.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        return f"{name}: size_bytes not pinned"
    target_dir = str(entry.get("target_dir") or "")
    if not target_dir or ".." in Path(target_dir).parts or Path(target_dir).is_absolute():
        return f"{name}: target_dir must be a relative path inside the ComfyUI folder"
    return None


def unresolved(target: Target) -> list[str]:
    """Everything that still blocks a build of ``target`` (empty when it may be built)."""
    problems: list[str] = []
    if not BASE_DIGEST or not DIGEST_PATTERN.fullmatch(BASE_DIGEST):
        problems.append("BASE_DIGEST not pinned")
    if not COMFYUI_VERSION or not VERSION_PATTERN.fullmatch(COMFYUI_VERSION):
        problems.append("COMFYUI_VERSION not pinned")
    for entry in load_models_lock():
        if entry.get("image") == target:
            problem = _weight_problem(entry)
            if problem:
                problems.append(problem)
    for node in load_nodes_lock():
        if node.get("image") == target and not HEX40.fullmatch(str(node.get("commit") or "")):
            problems.append(f"{node.get('name', node.get('repo'))}: commit not pinned")
    return problems


def plan(target: Target, registry: str, tag: str, *, push: bool = False) -> list[list[str]]:
    """The docker commands for one image; ValueError while anything is unpinned."""
    target = _target(target)
    if not REGISTRY_PATTERN.fullmatch(registry):
        raise ValueError("registry must look like host[:port]/namespace, without a scheme")
    if not TAG_PATTERN.fullmatch(tag):
        raise ValueError("tag must be a docker tag")
    problems = unresolved(target)
    if problems:
        raise ValueError("refused, not pinned yet: " + "; ".join(problems))
    reference = f"{registry}/amn-{target}:{tag}"
    commands = [
        [
            "docker",
            "buildx",
            "build",
            "--platform",
            "linux/amd64",
            "--target",
            target,
            "--build-arg",
            f"BASE_IMAGE={BASE_IMAGE}",
            "--build-arg",
            f"BASE_DIGEST={BASE_DIGEST}",
            "--build-arg",
            f"COMFYUI_VERSION={COMFYUI_VERSION}",
            # The token comes from the builder's environment into one RUN step only.
            "--secret",
            "id=hf_token,env=HF_TOKEN",
            "--tag",
            reference,
            "--file",
            str(HERE / "Dockerfile"),
            str(HERE),
        ]
    ]
    if push:
        commands.append(["docker", "push", reference])
    return commands


def run_command(args: list[str]) -> None:
    subprocess.run(args, check=True)


# ------------------------------------------------------------------- inside the image build


def _read_token(token_path: Path) -> str | None:
    try:
        token = token_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def _in_stage(image: Target) -> None:
    """Only inside the image's own build stage: a hand run never downloads 40-75 GB."""
    if os.environ.get(STAGE_ENV) != image:
        raise ValueError(f"refused: runs only inside the {image} image build ({STAGE_ENV})")


def _token_host(url: str) -> bool:
    return (urlsplit(url).hostname or "").lower() == TOKEN_HOST


class TokenSafeRedirect(urllib.request.HTTPRedirectHandler):
    """urllib copies every header to a redirect's target; Hugging Face answers a weight with
    a redirect to its storage CDN, which must never receive the token (and rejects a second
    credential next to its signed URL)."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        moved = super().redirect_request(req, fp, code, msg, headers, newurl)
        if moved is not None and not _token_host(newurl):
            for name in list(moved.headers):
                if name.lower() == "authorization":
                    del moved.headers[name]
            moved.unredirected_hdrs.pop("Authorization", None)
        return moved


def fetch(
    image: Target,
    dest: Path,
    *,
    token_path: Path = TOKEN_PATH,
    opener: Callable[..., Any] | None = None,
) -> list[Path]:
    """Download and verify every locked weight of ``image`` under ``dest`` (the ComfyUI
    folder). Refuses before any download while one entry is unresolved, or outside the
    image's build stage."""
    image = _target(image)
    _in_stage(image)
    entries = [entry for entry in load_models_lock() if entry.get("image") == image]
    problems = [problem for entry in entries if (problem := _weight_problem(entry))]
    if problems:
        raise ValueError("refused, not pinned yet: " + "; ".join(problems))
    open_url = opener or urllib.request.build_opener(TokenSafeRedirect()).open
    token = _read_token(token_path)
    written: list[Path] = []
    for entry in entries:
        url = entry.get("url") or (
            f"https://huggingface.co/{entry['repo']}/resolve/{entry['revision']}/{entry['file']}"
        )
        target = dest / str(entry["target_dir"]) / Path(str(entry["file"])).name
        target.parent.mkdir(parents=True, exist_ok=True)
        # The token goes to Hugging Face only, never to another host (a pinned `url`).
        headers = {"Authorization": f"Bearer {token}"} if token and _token_host(url) else {}
        request = urllib.request.Request(str(url), headers=headers)
        partial = target.with_name(target.name + ".part")
        digest = hashlib.sha256()
        size = 0
        try:
            with open_url(request, timeout=600) as response, partial.open("wb") as out:
                while chunk := response.read(CHUNK):
                    digest.update(chunk)
                    size += len(chunk)
                    out.write(chunk)
            if digest.hexdigest() != entry["sha256"] or size != entry["size_bytes"]:
                raise ValueError(f"{entry['name']}: sha256 or size does not match the lock")
            partial.replace(target)
        finally:
            partial.unlink(missing_ok=True)
        written.append(target)
        print(f"verified {entry['name']} ({size} bytes)")
    return written


def resolve(
    image: Target,
    *,
    token: str | None = None,
    lock_path: Path | None = None,
    opener: Callable[..., Any] | None = None,
) -> list[str]:
    """Pin the sha256 of ``image``'s weights that are still unpinned (the gated LTX-2.5 files:
    Hugging Face masks their checksum until the account accepted the licence) from Hugging
    Face's own metadata, with the Owner's token (``HF_TOKEN``). Metadata only: one
    ``paths-info`` POST per file, never a ``/resolve/`` download. The size must equal the one
    already pinned from the public tree, else nothing is written. Returns the names pinned."""
    image = _target(image)
    path = lock_path or HERE / "models.lock.json"
    entries: list[dict[str, Any]] = list(json.loads(path.read_text(encoding="utf-8")))
    todo = [e for e in entries if e.get("image") == image and not e.get("sha256")]
    if not todo:
        return []
    secret = os.environ.get("HF_TOKEN", "") if token is None else token
    if not secret.strip():
        raise ValueError("refused: set HF_TOKEN (the Owner's Hugging Face read token)")
    open_url = opener or urllib.request.build_opener(TokenSafeRedirect()).open
    pinned: list[str] = []
    for entry in todo:
        revision, repo, file = entry.get("revision"), entry.get("repo"), entry.get("file")
        if not (repo and file and HEX40.fullmatch(str(revision or ""))):
            raise ValueError(f"{entry.get('name')}: pin the repo, file and revision first")
        url = f"https://{TOKEN_HOST}/api/models/{repo}/paths-info/{revision}"
        body = urlencode({"paths": file, "expand": "true"}).encode()
        request = urllib.request.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {secret.strip()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with open_url(request, timeout=60) as response:
            answer = json.loads(response.read() or b"[]")
        found = next((i for i in answer if isinstance(i, dict) and i.get("path") == file), None)
        lfs = found.get("lfs") if isinstance(found, dict) else None
        oid = str(lfs.get("oid") or "") if isinstance(lfs, dict) else ""
        size = lfs.get("size") if isinstance(lfs, dict) else None
        if not HEX64.fullmatch(oid):
            name = entry.get("name")
            raise ValueError(f"{name}: Hugging Face gave no sha256 (licence accepted?)")
        if entry.get("size_bytes") is not None and size != entry["size_bytes"]:
            raise ValueError(f"{entry.get('name')}: size {size} differs from the lock")
        entry["sha256"] = oid
        entry["size_bytes"] = size
        entry["note"] = (
            "sha256 pinned from Hugging Face's metadata (paths-info at this revision) with the "
            "Owner's token; no weight downloaded."
        )
        pinned.append(str(entry.get("name")))
    text = json.dumps(entries, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")
    return pinned


def install_nodes(
    image: Target, dest: Path, *, run: Callable[[list[str]], Any] = run_command
) -> list[Path]:
    """Clone each locked custom node of ``image`` at its pinned commit."""
    image = _target(image)
    _in_stage(image)
    nodes = [node for node in load_nodes_lock() if node.get("image") == image]
    missing = [node.get("name") for node in nodes if not HEX40.fullmatch(str(node.get("commit")))]
    if missing:
        raise ValueError(f"refused, commit not pinned: {missing}")
    folders: list[Path] = []
    for node in nodes:
        folder = dest / str(node["name"])
        run(["git", "clone", "--filter=blob:none", str(node["repo"]), str(folder)])
        run(["git", "-C", str(folder), "checkout", str(node["commit"])])
        requirements = folder / "requirements.txt"
        if requirements.is_file():
            run([sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", str(requirements)])
        folders.append(folder)
    return folders


# ---------------------------------------------------------------------------------- the CLI


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="runpod_worker.build", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan_cmd = commands.add_parser("plan", help="print (or, with both switches, run) the build")
    plan_cmd.add_argument("target", choices=TARGETS)
    plan_cmd.add_argument("--registry", required=True)
    plan_cmd.add_argument("--tag", required=True)
    plan_cmd.add_argument("--push", action="store_true")
    plan_cmd.add_argument("--execute", action="store_true")
    fetch_cmd = commands.add_parser("fetch", help="inside the image build: download weights")
    fetch_cmd.add_argument("--image", choices=TARGETS, required=True)
    fetch_cmd.add_argument("--dest", type=Path, required=True)
    nodes_cmd = commands.add_parser("nodes", help="inside the image build: custom nodes")
    nodes_cmd.add_argument("--image", choices=TARGETS, required=True)
    nodes_cmd.add_argument("--dest", type=Path, required=True)
    resolve_cmd = commands.add_parser(
        "resolve", help="pin the gated weights' sha256 from metadata with HF_TOKEN (no download)"
    )
    resolve_cmd.add_argument("--image", choices=TARGETS, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "resolve":
            for name in resolve(_target(args.image)):
                print(f"pinned {name}")
            return 0
        if args.command == "fetch":
            fetch(_target(args.image), args.dest)
            return 0
        if args.command == "nodes":
            install_nodes(_target(args.image), args.dest)
            return 0
        steps = plan(_target(args.target), args.registry, args.tag, push=args.push)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for step in steps:
        print(shlex.join(step))
    if not args.execute:
        return 0
    if os.environ.get(EXECUTE_SWITCH) != "1":
        print(
            f"not executed: set {EXECUTE_SWITCH}=1 as well (each image is 40-75 GB)",
            file=sys.stderr,
        )
        return 3
    for step in steps:
        run_command(step)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
