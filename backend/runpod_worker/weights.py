"""Where the worker's weights are, checked before ComfyUI starts (Owner's cards, 2026-10-09).

The weights live in RunPod **cached models**, one per endpoint: the stills endpoint caches the
Owner's private Hugging Face mirror of the stills files, the motion endpoint the mirror of the
motion files (``mirrors.lock.json``; each file's place in its mirror is ``mirror_path`` in
``models.lock.json``). RunPod downloads a cached model before the worker starts, unbilled, and
lays it out the Hugging Face cache way (https://docs.runpod.io/serverless/endpoints/
model-caching): ``/runpod-volume/huggingface-cache/hub/models--<org>--<name>/snapshots/<rev>/``
with ``refs/main`` naming the revision it fetched.

:func:`prepare` finds the snapshot of the mirror revision the lock pins (never "the first
snapshot there is", never whatever ``refs/main`` says), checks that every locked file is there
at its locked size, and writes ComfyUI's model paths for every folder the graphs read
(``extra_model_paths.amn.yaml``, given to ComfyUI with ``--extra-model-paths-config``). What it
finds is a :class:`WeightsReport`; a wrong one fails every item with ``MODELS_MISSING`` or
``WRONG_REVISION`` and ComfyUI is never started on it (amn_handler.main).

Checks are cheap on purpose: the time between the container start and the first item is
billed GPU time. The pinned mirror revision is a git commit, which covers each file's LFS
pointer and so its sha256; with the sizes that is the default check. Hashing every file
(``AMN_WEIGHTS_SHA256=1``) reads ~40-60 GB and is for the bake-off to price. How RunPod names
the cache's blobs is UNPROVEN (the docs only say "Hugging Face cache conventions"): whether a
blob is named by its sha256 is recorded per file and never decides anything.

``baked`` is the last resort (backend/runpod_worker/Dockerfile): the weights inside the image
under /comfyui/models, where ComfyUI looks by itself.

Standard library only.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

HERE = Path(__file__).resolve().parent
#: RunPod's cached-model folder (docs.runpod.io/serverless/endpoints/model-caching).
DEFAULT_CACHE_ROOT = Path("/runpod-volume/huggingface-cache/hub")
DEFAULT_COMFY_DIR = Path("/comfyui")
YAML_NAME = "extra_model_paths.amn.yaml"
SOURCES = ("cache", "baked")
IMAGES = ("stills", "motion")
MODELS_MISSING = "MODELS_MISSING"
WRONG_REVISION = "WRONG_REVISION"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
#: A Hugging Face repo id: <owner>/<name>.
REPO_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.\-]{0,95}$")
CHUNK = 8 * 1024 * 1024


@dataclass(frozen=True)
class FileCheck:
    """One locked file as found: ``path`` is its place under the model root."""

    path: str
    ok: bool
    problem: str | None
    sha256_checked: bool
    #: The cache blob the snapshot entry links to (None for a plain file).
    blob: str | None
    #: True/False when the blob's name is/is not the locked sha256; None when unknown.
    #: UNPROVEN naming: recorded for the bake-off, never a gate.
    blob_named_by_sha256: bool | None


@dataclass(frozen=True)
class WeightsReport:
    image: str
    source: str
    repo: str | None
    root: Path | None
    #: The snapshot revision in use ("baked" for weights inside the image).
    revision: str | None
    #: None, MODELS_MISSING or WRONG_REVISION: the code every item fails with.
    error: str | None
    problems: tuple[str, ...]
    #: Wall seconds the check took (billed: it runs after the container started).
    seconds: float
    files: tuple[FileCheck, ...]
    #: The model-paths file ComfyUI must be started with (cache source only).
    yaml_path: Path | None

    @property
    def ok(self) -> bool:
        return self.error is None

    def summary(self) -> dict[str, Any]:
        """Plain data for the worker log: no secret is ever part of a report."""
        return {
            "image": self.image,
            "source": self.source,
            "repo": self.repo,
            "revision": self.revision,
            "error": self.error,
            "problems": list(self.problems[:20]),
            "seconds": round(self.seconds, 3),
            "files": len(self.files),
            "blobs_named_by_sha256": sorted(
                {str(check.blob_named_by_sha256) for check in self.files}
            ),
        }


# ------------------------------------------------------------------------------------- locks


def load_entries(image: str, lock_path: Path | None = None) -> list[dict[str, Any]]:
    entries = json.loads((lock_path or HERE / "models.lock.json").read_text(encoding="utf-8"))
    return [dict(entry) for entry in entries if entry.get("image") == image]


def load_mirror(image: str, path: Path | None = None) -> dict[str, Any]:
    """The Owner's mirror of ``image``: repo id, pinned revision (null until the copy ran)."""
    mirrors = json.loads((path or HERE / "mirrors.lock.json").read_text(encoding="utf-8"))
    mirror = mirrors.get(image) if isinstance(mirrors, dict) else None
    return dict(mirror) if isinstance(mirror, dict) else {}


def cache_folder(repo: str) -> str:
    """The hub cache's folder for a model repo (Hugging Face's ``repo_folder_name``)."""
    return "models--" + repo.replace("/", "--")


def mirror_folder(entry: Mapping[str, Any]) -> str:
    return str(PurePosixPath(str(entry["mirror_path"])).parts[0])


def _safe_relative(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts and "\\" not in value


# ------------------------------------------------------------------------------------ checks


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def check_file(
    root: Path, relative: str, entry: Mapping[str, Any], *, verify_sha256: bool
) -> FileCheck:
    path = root / relative
    blob: str | None = None
    named: bool | None = None
    expected_sha = entry.get("sha256")
    known = isinstance(expected_sha, str) and bool(HEX64.fullmatch(expected_sha))
    if path.is_symlink():
        try:
            blob = Path(os.readlink(path)).name
        except OSError:
            blob = None
        if blob is not None and known:
            named = blob == expected_sha
    try:
        size = path.stat().st_size  # follows the snapshot's link to its blob
    except OSError:
        return FileCheck(relative, False, f"{relative}: missing", False, blob, named)
    if size != entry.get("size_bytes"):
        problem = f"{relative}: {size} bytes, the lock says {entry.get('size_bytes')}"
        return FileCheck(relative, False, problem, False, blob, named)
    if verify_sha256 and known:
        if _sha256(path) != expected_sha:
            problem = f"{relative}: sha256 differs from the lock"
            return FileCheck(relative, False, problem, True, blob, named)
        return FileCheck(relative, True, None, True, blob, named)
    return FileCheck(relative, True, None, False, blob, named)


def model_paths_yaml(root: Path, folders: Sequence[str]) -> str:
    """ComfyUI's extra model paths (utils/extra_config.py): one section whose ``base_path``
    is the snapshot and one key per models folder. Strings are JSON-quoted, which YAML reads
    as double-quoted scalars, so no YAML library is needed."""
    lines = [
        "# Written by runpod_worker.weights before ComfyUI starts; do not edit.",
        "amn_mirror:",
        f"    base_path: {json.dumps(str(root))}",
        "    is_default: true",
    ]
    lines += [f"    {folder}: {json.dumps(folder + '/')}" for folder in sorted(set(folders))]
    return "\n".join(lines) + "\n"


def _snapshot(base: Path, repo: str, revision: str) -> tuple[Path | None, str | None, str | None]:
    """(snapshot, error, problem) for the pinned revision; never any other snapshot."""
    if not base.is_dir():
        return (
            None,
            MODELS_MISSING,
            f"the cached model {repo} is not on this worker (the endpoint's Model field)",
        )
    pinned = base / "snapshots" / revision
    if pinned.is_dir():
        return pinned, None, None
    try:
        main = (base / "refs" / "main").read_text(encoding="utf-8").strip()
    except OSError:
        main = ""
    present = sorted(p.name for p in (base / "snapshots").glob("*") if p.is_dir())
    if not main and not present:
        return None, MODELS_MISSING, f"the cached model {repo} holds no snapshot"
    seen = main or ", ".join(present)
    return None, WRONG_REVISION, f"the cache holds {seen}, the lock pins {revision}"


def prepare(
    image: str | None = None,
    *,
    source: str | None = None,
    env: Mapping[str, str] | None = None,
    cache_root: Path | None = None,
    comfy_dir: Path | None = None,
    entries: Sequence[Mapping[str, Any]] | None = None,
    mirror: Mapping[str, Any] | None = None,
    verify_sha256: bool | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> WeightsReport:
    """Find and check ``image``'s weights; write ComfyUI's model paths when they are right.

    Anything not passed comes from the endpoint environment: ``AMN_WORKER_IMAGE`` (set by the
    Dockerfile), ``AMN_MODEL_SOURCE`` (``cache``, the default, or ``baked``),
    ``AMN_HF_CACHE`` (RunPod's cache folder), ``COMFY_DIR`` and ``AMN_WEIGHTS_SHA256``.
    ``AMN_MIRROR_REPO`` / ``AMN_MIRROR_REVISION``, when set, pin the mirror over ``mirror``
    (or the image's ``mirrors.lock.json``); an empty one unpins it (refused).
    """
    started = clock()
    values = os.environ if env is None else env
    name = str(image if image is not None else values.get("AMN_WORKER_IMAGE", ""))
    kind = str(source if source is not None else values.get("AMN_MODEL_SOURCE") or "cache")
    comfy = comfy_dir or Path(values.get("COMFY_DIR", str(DEFAULT_COMFY_DIR)))
    if verify_sha256 is None:
        verify_sha256 = values.get("AMN_WEIGHTS_SHA256", "0") == "1"
    repo: str | None = None

    def done(
        error: str | None = None,
        problems: Sequence[str] = (),
        *,
        root: Path | None = None,
        revision: str | None = None,
        files: Sequence[FileCheck] = (),
        yaml_path: Path | None = None,
    ) -> WeightsReport:
        return WeightsReport(
            image=name,
            source=kind,
            repo=repo,
            root=root,
            revision=revision,
            error=error,
            problems=tuple(problems),
            seconds=max(0.0, clock() - started),
            files=tuple(files),
            yaml_path=yaml_path,
        )

    if name not in IMAGES:
        return done(MODELS_MISSING, ["AMN_WORKER_IMAGE must be stills or motion"])
    if kind not in SOURCES:
        return done(MODELS_MISSING, [f"AMN_MODEL_SOURCE must be one of {SOURCES}"])
    locked = [dict(entry) for entry in (entries if entries is not None else load_entries(name))]
    if not locked:
        return done(MODELS_MISSING, [f"models.lock.json lists nothing for {name}"])

    if kind == "baked":
        checks = [
            check_file(
                comfy,
                f"{entry['target_dir']}/{PurePosixPath(str(entry['file'])).name}",
                entry,
                verify_sha256=verify_sha256,
            )
            for entry in locked
        ]
        problems = [check.problem for check in checks if check.problem]
        error = MODELS_MISSING if problems else None
        return done(error, problems, root=comfy, revision="baked", files=checks)

    # The endpoint's environment (the Owner types it in the console from the studio's letter;
    # the studio never PATCHes it, an env change is a RunPod release) pins the mirror over the
    # image's own mirrors.lock.json, so a new mirror commit needs no new image.
    pinned = dict(mirror) if mirror is not None else load_mirror(name)
    for key, variable in (("repo", "AMN_MIRROR_REPO"), ("revision", "AMN_MIRROR_REVISION")):
        if variable in values:
            pinned[key] = values[variable].strip() or None
    wanted_repo, revision = pinned.get("repo"), pinned.get("revision")
    if not isinstance(wanted_repo, str) or not REPO_ID.fullmatch(wanted_repo):
        return done(
            WRONG_REVISION,
            [f"no mirror repo pinned for {name}: set AMN_MIRROR_REPO on the endpoint"],
        )
    repo = wanted_repo
    if not isinstance(revision, str) or not HEX40.fullmatch(revision):
        return done(
            WRONG_REVISION,
            [f"no revision pinned for {repo}: set AMN_MIRROR_REVISION on the endpoint"],
        )
    unsafe = [e.get("name") for e in locked if not _safe_relative(str(e.get("mirror_path") or ""))]
    if unsafe:
        return done(MODELS_MISSING, [f"{entry}: no safe mirror_path" for entry in unsafe])
    hub = cache_root or Path(values.get("AMN_HF_CACHE", str(DEFAULT_CACHE_ROOT)))
    snapshot, error, problem = _snapshot(hub / cache_folder(repo), repo, revision)
    if snapshot is None:
        return done(error, [problem or "no snapshot"])
    checks = [
        check_file(snapshot, str(entry["mirror_path"]), entry, verify_sha256=verify_sha256)
        for entry in locked
    ]
    problems = [check.problem for check in checks if check.problem]
    if problems:
        return done(MODELS_MISSING, problems, root=snapshot, revision=revision, files=checks)
    yaml_path = comfy / YAML_NAME
    text = model_paths_yaml(snapshot, [mirror_folder(entry) for entry in locked])
    try:
        yaml_path.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        problem = f"cannot write {yaml_path}: {type(exc).__name__}"
        return done(MODELS_MISSING, [problem], root=snapshot, revision=revision, files=checks)
    return done(root=snapshot, revision=revision, files=checks, yaml_path=yaml_path)
