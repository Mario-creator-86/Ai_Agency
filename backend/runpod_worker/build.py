"""Build plan, weight fetch and the Owner's weight mirrors for the two AMN worker images.

Never run by the studio. Where the weights live (Owner's cards, 2026-10-09): RunPod cached
models, one per endpoint, each the Owner's PRIVATE Hugging Face mirror holding only the
locked files (``mirror`` below; the worker checks it with ``runpod_worker.weights``). The
small images (``Dockerfile.stills``, ``Dockerfile.motion``, no weights) are built by RunPod's
GitHub integration from the standalone repository ``export_repo.py`` writes. Everything
below about ``plan`` and ``fetch`` is the baked image (``Dockerfile``): the documented last
resort only (one 39-78 GB layer: GHCR refuses a layer over 10 GB, ECR one over ~54 GB).

``python -m runpod_worker.build mirror --image <stills|motion> --repo <owner/name>`` prints
the copy plan: every locked file with its upstream source and its path in the mirror, and the
licence files that go with them. With ``--execute`` (only on the one-time copy pod, where
``AMN_MIRROR_HOST=pod`` and ``HF_TOKEN`` are set) it downloads each file, checks its sha256
and size against the lock, uploads it to the private mirror with ``huggingface_hub``
(``requirements-mirror.txt``), adds the licences (Apache-2.0 copies; the LTX-2.x licence with
its Attachment A for motion), a README and ``MIRROR_MANIFEST.json``, and prints the mirror's
revision for ``mirrors.lock.json``. It is resumable per file (a file the mirror already holds
with its locked sha256 is skipped) and a second run uploads nothing. The token is read from
the environment, sent to huggingface.co only, and never printed.

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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal
from urllib.parse import urlencode, urlsplit

from runpod_worker.weights import REPO_ID

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
#: ``mirror --execute`` runs only where this is "pod" (the one-time copy pod), never on the
#: Owner's PC: it moves ~60-78 GB.
MIRROR_HOST_ENV = "AMN_MIRROR_HOST"
DEFAULT_SCRATCH = Path("/workspace/amn-mirror")
#: The licence texts' sha256 (checksums of public files, not credentials).
_APACHE_SHA256 = (
    "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30"  # pragma: allowlist secret
)
_LTX_SHA256 = (
    "be75acae5c99b0fb16ed6cfbf8f731e5121a729bef112d20337699407e796451"  # pragma: allowlist secret
)
_RIFE_SHA256 = (
    "7932fb49341512b959b1744a6d9cbb39e5a1ec89da438a34d0454d5d8df9fecd"  # pragma: allowlist secret
)
#: The licence texts each mirror carries, by the lock's ``licence_id``: pinned by commit (or
#: the canonical Apache URL) and by sha256, read on 2026-10-09. The LTX-2.x text holds its
#: Attachment A (Use Restrictions) at the end, which must travel with every copy (§3).
LICENCES: dict[str, dict[str, str]] = {
    "Apache-2.0": {
        "url": "https://www.apache.org/licenses/LICENSE-2.0.txt",
        "sha256": _APACHE_SHA256,
        "path": "LICENSES/Apache-2.0.txt",
        "must_contain": "Apache License",
    },
    "LTX-2.x": {
        "url": (
            "https://raw.githubusercontent.com/Lightricks/LTX-2/"
            "a95ab856bf29407b6b066ede0abe1846050db56c/LICENSE-2_x"
        ),
        "sha256": _LTX_SHA256,
        "path": "LICENSES/LTX-2.x-Community-License.txt",
        "must_contain": "Attachment A",
    },
    "MIT-Practical-RIFE": {
        "url": (
            "https://raw.githubusercontent.com/hzwer/Practical-RIFE/"
            "7840e88fec61ada933b0d27775867b5851b64b44/LICENSE"
        ),
        "sha256": _RIFE_SHA256,
        "path": "LICENSES/MIT-Practical-RIFE.txt",
        "must_contain": "MIT License",
    },
}

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


def _download(
    entry: Mapping[str, Any], target: Path, *, token: str | None, open_url: Callable[..., Any]
) -> int:
    """One locked weight to ``target``, verified against its sha256 and size; nothing is left
    behind when it does not match. Returns the bytes written."""
    url = entry.get("url") or (
        f"https://huggingface.co/{entry['repo']}/resolve/{entry['revision']}/{entry['file']}"
    )
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
    return size


def fetch(
    image: Target,
    dest: Path,
    *,
    token_path: Path = TOKEN_PATH,
    opener: Callable[..., Any] | None = None,
) -> list[Path]:
    """Download and verify every locked weight of ``image`` under ``dest`` (the ComfyUI
    folder). Refuses before any download while one entry is unresolved, or outside the
    image's build stage. The baked last resort only (Dockerfile)."""
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
        target = dest / str(entry["target_dir"]) / Path(str(entry["file"])).name
        size = _download(entry, target, token=token, open_url=open_url)
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
        entry.pop("sha256_status", None)  # the gate is passed: the checksum is pinned
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


# ------------------------------------------------------------------- the Owner's mirrors


@dataclass(frozen=True)
class MirrorPlan:
    image: str
    repo: str
    files: tuple[dict[str, Any], ...]
    licences: tuple[str, ...]

    @property
    def total_bytes(self) -> int:
        return sum(int(entry["size_bytes"]) for entry in self.files)

    def lines(self) -> list[str]:
        out = [
            f"mirror {self.image} -> https://huggingface.co/{self.repo} (private), "
            f"{len(self.files)} files, {self.total_bytes / 1e9:.2f} GB"
        ]
        for entry in self.files:
            out.append(
                f"  {entry['mirror_path']}  <- {entry['repo']}@{entry['revision']}:"
                f"{entry['file']}  {entry['size_bytes']} B  sha256 {entry['sha256']}"
            )
        for licence_id in self.licences:
            licence = LICENCES[licence_id]
            out.append(f"  {licence['path']}  <- {licence['url']}")
        out.append("  README.md, MIRROR_MANIFEST.json (written by the copy)")
        return out


def _safe_mirror_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts and "\\" not in value


def mirror_plan(image: str, repo: str) -> MirrorPlan:
    """The copy of ``image``'s locked files into the Owner's mirror ``repo``; ValueError while
    a file is unpinned (the LTX-2.5 checksums until the gate) or the repo id is not one."""
    target = _target(image)
    if not REPO_ID.fullmatch(repo):
        raise ValueError("repo must be a Hugging Face repo id <owner>/<name>")
    entries = [entry for entry in load_models_lock() if entry.get("image") == target]
    if not entries:
        raise ValueError(f"models.lock.json lists nothing for {target}")
    problems = [problem for entry in entries if (problem := _weight_problem(entry))]
    seen: set[str] = set()
    for entry in entries:
        place = str(entry.get("mirror_path") or "")
        if not _safe_mirror_path(place) or place in seen:
            problems.append(f"{entry.get('name')}: mirror_path missing, unsafe or repeated")
        seen.add(place)
        if entry.get("licence_id") not in LICENCES:
            problems.append(f"{entry.get('name')}: licence_id has no licence text to copy")
    if problems:
        raise ValueError("refused, not pinned yet: " + "; ".join(problems))
    licences = tuple(sorted({str(entry["licence_id"]) for entry in entries}))
    return MirrorPlan(target, repo, tuple(dict(entry) for entry in entries), licences)


def _git_blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _lfs_sha256(info: Any) -> str | None:
    lfs = getattr(info, "lfs", None)
    if lfs is None:
        return None
    value = lfs.get("sha256") if isinstance(lfs, Mapping) else getattr(lfs, "sha256", None)
    return str(value) if value else None


def _remote(api: Any, repo: str, paths: Sequence[str]) -> dict[str, Any]:
    found = api.get_paths_info(repo, list(paths), expand=True, repo_type="model")
    return {str(info.path): info for info in found if getattr(info, "path", None)}


def _holds_weight(info: Any, entry: Mapping[str, Any]) -> bool:
    return (
        info is not None
        and _lfs_sha256(info) == entry["sha256"]
        and getattr(info, "size", None) == entry["size_bytes"]
    )


def _holds_small(info: Any, data: bytes) -> bool:
    if info is None:
        return False
    if _lfs_sha256(info) == hashlib.sha256(data).hexdigest():
        return True
    return getattr(info, "blob_id", None) == _git_blob_sha1(data)


def _fetch_licence(licence_id: str, open_url: Callable[..., Any], token: str | None) -> bytes:
    licence = LICENCES[licence_id]
    url = licence["url"]
    headers = {"Authorization": f"Bearer {token}"} if token and _token_host(url) else {}
    with open_url(urllib.request.Request(url, headers=headers), timeout=60) as response:
        data = bytes(response.read(4 * 1024 * 1024))
    if hashlib.sha256(data).hexdigest() != licence["sha256"]:
        raise ValueError(f"{licence_id}: the licence text at {url} is not the pinned one")
    if licence["must_contain"] not in data.decode("utf-8", "replace"):
        raise ValueError(f"{licence_id}: the licence text lacks {licence['must_contain']}")
    return data


def _mirror_readme(plan: MirrorPlan) -> bytes:
    lines = [
        f"# AMN {plan.image} weights (private mirror `{plan.repo}`)",
        "",
        "A private copy of the weights the AMN worker's "
        f"`{plan.image}` endpoint loads as its RunPod cached model. Every file is a",
        "byte-for-byte copy of the upstream file below, checked against its sha256 before",
        "upload (`MIRROR_MANIFEST.json`). Written by `python -m runpod_worker.build mirror`.",
        "",
        "| File | Upstream | Licence |",
        "| --- | --- | --- |",
    ]
    for entry in plan.files:
        lines.append(
            f"| `{entry['mirror_path']}` | `{entry['repo']}@{entry['revision'][:12]}` "
            f"`{entry['file']}` | {entry['licence_id']} ({entry['licence_url']}) |"
        )
    lines += ["", "Licence texts: " + ", ".join(LICENCES[i]["path"] for i in plan.licences)]
    if "LTX-2.x" in plan.licences:
        lines += [
            "",
            "LTX-2.x Community License: this copy carries the licence and its Attachment A",
            "(section 3). Content made with LTX-2.x is disclosed as machine generated (AI);",
            "metadata, watermarks and provenance are never removed; the licence is free below",
            "USD 10M annual revenue and excludes products that compete with Lightricks.",
        ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def _mirror_manifest(plan: MirrorPlan) -> bytes:
    body = {
        "image": plan.image,
        "repo": plan.repo,
        "made_by": "python -m runpod_worker.build mirror",
        "files": [
            {
                "mirror_path": entry["mirror_path"],
                "upstream_repo": entry["repo"],
                "upstream_revision": entry["revision"],
                "upstream_file": entry["file"],
                "sha256": entry["sha256"],
                "size_bytes": entry["size_bytes"],
                "licence_id": entry["licence_id"],
            }
            for entry in plan.files
        ],
        "licences": [
            {
                "id": licence_id,
                "path": LICENCES[licence_id]["path"],
                "source_url": LICENCES[licence_id]["url"],
                "sha256": LICENCES[licence_id]["sha256"],
            }
            for licence_id in plan.licences
        ],
    }
    return (json.dumps(body, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def mirror_execute(
    plan: MirrorPlan,
    *,
    api: Any,
    scratch: Path,
    token: str,
    opener: Callable[..., Any] | None = None,
) -> str:
    """Fill the Owner's private mirror from the plan (on the copy pod). Each weight is
    downloaded, verified, uploaded, confirmed by the Hub's own sha256 and deleted from the
    pod's disk before the next; a file the mirror already holds is skipped. Returns the
    mirror's revision (its commit) for ``mirrors.lock.json``."""
    open_url = opener or urllib.request.build_opener(TokenSafeRedirect()).open
    api.create_repo(plan.repo, repo_type="model", private=True, exist_ok=True)
    if not getattr(api.repo_info(plan.repo, repo_type="model"), "private", False):
        raise ValueError(f"refused: {plan.repo} is not private; the mirrors stay private")
    remote = _remote(api, plan.repo, [str(entry["mirror_path"]) for entry in plan.files])
    for entry in plan.files:
        place = str(entry["mirror_path"])
        if _holds_weight(remote.get(place), entry):
            print(f"already mirrored {place}")
            continue
        local = scratch / place
        try:
            _download(entry, local, token=token, open_url=open_url)
            api.upload_file(
                path_or_fileobj=str(local),
                path_in_repo=place,
                repo_id=plan.repo,
                repo_type="model",
                commit_message=f"AMN mirror: {entry['name']}",
            )
        finally:
            local.unlink(missing_ok=True)  # the pod's disk holds one weight at a time
        if not _holds_weight(_remote(api, plan.repo, [place]).get(place), entry):
            raise ValueError(f"{place}: the Hub does not confirm the locked sha256 and size")
        print(f"mirrored {place} ({entry['size_bytes']} bytes)")
    small: list[tuple[str, bytes]] = [
        (LICENCES[licence_id]["path"], _fetch_licence(licence_id, open_url, token))
        for licence_id in plan.licences
    ]
    small += [("README.md", _mirror_readme(plan)), ("MIRROR_MANIFEST.json", _mirror_manifest(plan))]
    remote = _remote(api, plan.repo, [place for place, _data in small])
    for place, data in small:
        if _holds_small(remote.get(place), data):
            continue
        api.upload_file(
            path_or_fileobj=data,
            path_in_repo=place,
            repo_id=plan.repo,
            repo_type="model",
            commit_message=f"AMN mirror: {place}",
        )
    revision = str(api.repo_info(plan.repo, repo_type="model").sha)
    print(f"mirror revision {revision}: pin it as {plan.image}.revision in mirrors.lock.json")
    return revision


def _hf_api(token: str) -> Any:
    """The Hub client, on the copy pod only (``pip install -r requirements-mirror.txt``)."""
    from huggingface_hub import HfApi  # type: ignore[import-not-found,unused-ignore]

    return HfApi(token=token)


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
    mirror_cmd = commands.add_parser(
        "mirror", help="plan (or, on the copy pod with --execute, run) the Owner's mirror copy"
    )
    mirror_cmd.add_argument("--image", choices=TARGETS, required=True)
    mirror_cmd.add_argument("--repo", required=True, help="the Owner's <owner>/<name>")
    mirror_cmd.add_argument("--execute", action="store_true")
    mirror_cmd.add_argument("--scratch", type=Path, default=DEFAULT_SCRATCH)
    args = parser.parse_args(argv)
    if args.command == "mirror":
        return _mirror_main(args)
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


def _mirror_main(args: argparse.Namespace) -> int:
    try:
        copy = mirror_plan(args.image, args.repo)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    for line in copy.lines():
        print(line)
    if not args.execute:
        print("plan only: the copy runs with --execute on the copy pod")
        return 0
    if os.environ.get(MIRROR_HOST_ENV) != "pod":
        print(f"not executed: runs only on the copy pod ({MIRROR_HOST_ENV}=pod)", file=sys.stderr)
        return 3
    token = os.environ.get("HF_TOKEN", "").strip()
    if not token:
        print("not executed: set HF_TOKEN (the Owner's Hugging Face write token)", file=sys.stderr)
        return 3
    try:
        mirror_execute(copy, api=_hf_api(token), scratch=args.scratch, token=token)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
