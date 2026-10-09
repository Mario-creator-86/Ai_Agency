"""Where the GPU worker's weights live (Owner's cards, 2026-10-09), proven offline only.

The weights are RunPod **cached models**: one per endpoint, each the Owner's PRIVATE Hugging
Face mirror holding only the locked files. The worker finds the mirror's pinned snapshot in
the cache, checks every locked file and writes ComfyUI's model paths before ComfyUI starts.
``build.py mirror`` fills a mirror (it plans by default; it copies only on the copy pod), and
``export_repo.py`` writes the small worker image as a standalone repository the Owner pushes
himself for RunPod's GitHub integration.

Nothing here calls RunPod, Hugging Face or GitHub: the cache is a tree in a temp folder, the
Hub is a fake ``HfApi``, every download a fake opener, and no image is built.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from runpod_worker import build, export_repo, weights
from runpod_worker.contract import WORKFLOWS
from test_runpod_worker import LOADER_FOLDERS

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "backend" / "runpod_worker"
REPO = "owner-test/amn-stills"
REV = "1" * 40
OTHER = "2" * 40

#: The reference route's pins, as the research read them from Hugging Face's metadata.
EDIT_REVISION = "f68ace85e60b4a02a323e394253731947657b7d2"  # pragma: allowlist secret
EDIT_SHA256 = (
    "c9fdc158e46d3b61ef75f21ae866ca2fe808bf4a53643120d1c1e87c19280a4e"  # pragma: allowlist secret
)
LORA_REVISION = "d74eba145674fd7e31b949324e148e21e7118abd"  # pragma: allowlist secret
LORA_SHA256 = (
    "22226e8d05d354bb356627d428809f5afd7819399b077238a2b70a82883a904f"  # pragma: allowlist secret
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def real_lock() -> list[dict[str, Any]]:
    return json.loads((WORKER / "models.lock.json").read_text(encoding="utf-8"))


def tiny(image: str = "stills") -> list[tuple[dict[str, Any], bytes]]:
    """The real lock entries of one image with tiny stand-in contents (their own checksums)."""
    out = []
    for entry in real_lock():
        if entry["image"] == image:
            data = ("weights of " + entry["name"]).encode()
            out.append(({**entry, "sha256": sha(data), "size_bytes": len(data)}, data))
    return out


def _symlinks_work(folder: Path) -> bool:
    target, link = folder / ".probe-target", folder / ".probe-link"
    try:
        target.write_text("x", encoding="utf-8")
        os.symlink(target.name, link)
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        link.unlink(missing_ok=True)
        target.unlink(missing_ok=True)


def fake_cache(
    hub: Path,
    files: list[tuple[dict[str, Any], bytes]],
    *,
    repo: str = REPO,
    revision: str = REV,
    main: str | None = REV,
    blob_name: Any = None,
) -> Path:
    """A Hugging Face hub cache as RunPod documents it: models--<org>--<name>/snapshots/<rev>,
    refs/main, files linked to blobs/ (copied where this machine cannot make symlinks)."""
    base = hub / ("models--" + repo.replace("/", "--"))
    snapshot = base / "snapshots" / revision
    hub.mkdir(parents=True, exist_ok=True)
    links = _symlinks_work(hub)
    for entry, data in files:
        blob = base / "blobs" / (blob_name(entry, data) if blob_name else sha(data))
        blob.parent.mkdir(parents=True, exist_ok=True)
        blob.write_bytes(data)
        target = snapshot / entry["mirror_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if links:
            os.symlink(os.path.relpath(blob, target.parent), target)
        else:
            shutil.copyfile(blob, target)
    if main is not None:
        (base / "refs").mkdir(parents=True, exist_ok=True)
        (base / "refs" / "main").write_text(main, encoding="utf-8")
    return snapshot


class Tick:
    def __init__(self, step: float) -> None:
        self.now = 100.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


def prepare(tmp: Path, files: list[tuple[dict[str, Any], bytes]], **kwargs: Any) -> Any:
    options: dict[str, Any] = {
        "source": "cache",
        "cache_root": tmp / "hub",
        "comfy_dir": tmp / "comfyui",
        "entries": [entry for entry, _data in files],
        "mirror": {"repo": REPO, "revision": REV, "visibility": "private"},
        "clock": Tick(2.0),
    }
    options.update(kwargs)
    (tmp / "comfyui").mkdir(exist_ok=True)
    return weights.prepare("stills", **options)


# ------------------------------------------------------------------------- the cached weights


def test_the_pinned_mirror_snapshot_is_the_model_root_and_comfyui_reads_every_folder(tmp_path):
    files = tiny("stills")
    snapshot = fake_cache(tmp_path / "hub", files)
    report = prepare(tmp_path, files)
    assert report.ok and report.error is None, report.problems
    assert report.revision == REV and report.root == snapshot
    assert report.seconds == pytest.approx(2.0)
    assert report.yaml_path == tmp_path / "comfyui" / "extra_model_paths.amn.yaml"
    loaded = yaml.safe_load(report.yaml_path.read_text(encoding="utf-8"))
    section = loaded["amn_mirror"]
    assert section["base_path"] == str(snapshot)
    assert section["is_default"] is True
    # Every folder a stills graph's loaders read is mapped onto the snapshot.
    stills_graphs = [name for operation, name in WORKFLOWS.values() if operation == "image"]
    for name in stills_graphs:
        graph = json.loads((WORKER / "workflows" / f"{name}.json").read_text(encoding="utf-8"))
        for node in graph["graph"].values():
            for field in node["inputs"]:
                folder = LOADER_FOLDERS.get((node["class_type"], field))
                if folder is not None:
                    key = folder.removeprefix("models/")
                    assert section[key] == key + "/", key
    for entry, _data in files:
        assert (snapshot / entry["mirror_path"]).is_file()
    assert {check.path for check in report.files} == {e["mirror_path"] for e, _ in files}


def test_the_motion_mirror_maps_the_ltx_upsampler_and_rife_folders(tmp_path):
    files = tiny("motion")
    repo = "owner-test/amn-motion"
    fake_cache(tmp_path / "hub", files, repo=repo)
    report = weights.prepare(
        "motion",
        source="cache",
        cache_root=tmp_path / "hub",
        comfy_dir=tmp_path,
        entries=[entry for entry, _ in files],
        mirror={"repo": repo, "revision": REV},
    )
    assert report.ok, report.problems
    section = yaml.safe_load(report.yaml_path.read_text(encoding="utf-8"))["amn_mirror"]
    for folder in (
        "diffusion_models",
        "text_encoders",
        "vae",
        "loras",
        "latent_upscale_models",
        "frame_interpolation",
    ):
        assert section[folder] == folder + "/"


def test_a_cache_on_another_revision_is_wrong_revision_and_never_a_fallback(tmp_path):
    files = tiny("stills")
    fake_cache(tmp_path / "hub", files, revision=OTHER, main=OTHER)
    report = prepare(tmp_path, files)
    assert report.error == "WRONG_REVISION" and not report.ok
    text = " ".join(report.problems)
    assert REV in text and OTHER in text
    assert report.yaml_path is None
    assert not (tmp_path / "comfyui" / "extra_model_paths.amn.yaml").exists()


def test_a_lone_other_snapshot_without_refs_is_still_wrong_revision(tmp_path):
    # RunPod's own example falls back to "the first available snapshot"; ours never does.
    files = tiny("stills")
    fake_cache(tmp_path / "hub", files, revision=OTHER, main=None)
    assert prepare(tmp_path, files).error == "WRONG_REVISION"


def test_the_pinned_snapshot_wins_over_refs_main(tmp_path):
    files = tiny("stills")
    fake_cache(tmp_path / "hub", files, revision=OTHER, main=OTHER)
    pinned = fake_cache(tmp_path / "hub", files, revision=REV, main=OTHER)
    report = prepare(tmp_path, files)
    assert report.ok and report.root == pinned and report.revision == REV


@pytest.mark.parametrize(
    "mirror",
    [
        {"repo": REPO, "revision": None},
        {"repo": None, "revision": REV},
        {"repo": REPO, "revision": "main"},
        {"repo": "not a repo", "revision": REV},
    ],
)
def test_an_unpinned_mirror_is_wrong_revision_before_any_lookup(tmp_path, mirror):
    files = tiny("stills")
    fake_cache(tmp_path / "hub", files)
    report = prepare(tmp_path, files, mirror=mirror)
    assert report.error == "WRONG_REVISION"
    assert report.yaml_path is None


def test_a_cached_model_that_is_not_there_is_models_missing(tmp_path):
    files = tiny("stills")
    (tmp_path / "hub").mkdir()
    report = prepare(tmp_path, files)
    assert report.error == "MODELS_MISSING"
    assert REPO in " ".join(report.problems)


def test_a_missing_or_short_file_is_models_missing_and_named(tmp_path):
    files = tiny("stills")
    snapshot = fake_cache(tmp_path / "hub", files)
    gone, short = files[0][0]["mirror_path"], files[1][0]["mirror_path"]
    (snapshot / gone).unlink()
    target = snapshot / short
    data = target.read_bytes()
    target.unlink()
    target.write_bytes(data[:-1])
    report = prepare(tmp_path, files)
    assert report.error == "MODELS_MISSING"
    text = " ".join(report.problems)
    assert gone in text and short in text
    assert report.yaml_path is None


def test_sha256_is_hashed_only_when_asked_and_known(tmp_path):
    files = tiny("stills")
    snapshot = fake_cache(tmp_path / "hub", files)
    target = snapshot / files[0][0]["mirror_path"]
    data = target.read_bytes()
    target.unlink()
    target.write_bytes(bytes([data[0] ^ 1]) + data[1:])  # same size, other content
    # By default the snapshot revision and the sizes decide (hashing ~60 GB is billed time).
    assert prepare(tmp_path, files).ok
    assert prepare(tmp_path, files, verify_sha256=True).error == "MODELS_MISSING"
    # A file without a pinned checksum (the gated LTX ones until the gate) is not hashed.
    unpinned = [({**files[0][0], "sha256": None}, files[0][1]), *files[1:]]
    report = prepare(tmp_path, unpinned, verify_sha256=True)
    assert report.ok
    check = next(c for c in report.files if c.path == files[0][0]["mirror_path"])
    assert check.sha256_checked is False


def test_the_blob_name_is_recorded_but_never_decides(tmp_path):
    (tmp_path / "hub").mkdir()
    if not _symlinks_work(tmp_path / "hub"):
        pytest.skip("this machine cannot make symlinks")
    files = tiny("stills")
    fake_cache(tmp_path / "hub", files, blob_name=lambda entry, data: "blob-" + entry["name"][:5])
    report = prepare(tmp_path, files)
    assert report.ok  # RunPod does not document the blob naming: UNPROVEN, never a gate
    assert all(check.blob_named_by_sha256 is False for check in report.files)
    other = tmp_path / "second"
    (other / "hub").mkdir(parents=True)
    fake_cache(other / "hub", files)
    named = prepare(other, files)
    assert all(check.blob_named_by_sha256 is True for check in named.files)


def test_the_blob_name_is_read_from_the_snapshot_link(tmp_path, monkeypatch):
    # The same check without OS symlinks (Windows without the privilege): a faked link.
    entry, data = tiny("stills")[0]
    linked = tmp_path / entry["mirror_path"]
    linked.parent.mkdir(parents=True)
    linked.write_bytes(data)
    plain_is_symlink = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda self: self == linked or plain_is_symlink(self))
    for target, named in ((entry["sha256"], True), ("some-other-blob", False)):
        monkeypatch.setattr(weights.os, "readlink", lambda path, t=target: f"../../blobs/{t}")
        check = weights.check_file(tmp_path, entry["mirror_path"], entry, verify_sha256=False)
        assert check.ok and check.blob == target and check.blob_named_by_sha256 is named


def test_a_baked_image_reads_the_comfyui_models_folder(tmp_path):
    files = tiny("stills")
    comfy = tmp_path / "comfyui"
    for entry, data in files:
        target = comfy / entry["target_dir"] / Path(entry["file"]).name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    report = prepare(tmp_path, files, source="baked")
    assert report.ok and report.revision == "baked" and report.yaml_path is None
    (comfy / files[0][0]["target_dir"] / Path(files[0][0]["file"]).name).unlink()
    assert prepare(tmp_path, files, source="baked").error == "MODELS_MISSING"


def test_the_image_and_the_source_come_from_the_endpoint_environment(tmp_path):
    files = tiny("stills")
    fake_cache(tmp_path / "hub", files)
    (tmp_path / "comfyui").mkdir()
    env = {
        "AMN_WORKER_IMAGE": "stills",
        "AMN_MODEL_SOURCE": "cache",
        "AMN_HF_CACHE": str(tmp_path / "hub"),
        "COMFY_DIR": str(tmp_path / "comfyui"),
    }
    entries = [entry for entry, _ in files]
    mirror = {"repo": REPO, "revision": REV}
    assert weights.prepare(env=env, entries=entries, mirror=mirror).ok
    for broken in ({"AMN_WORKER_IMAGE": ""}, {"AMN_MODEL_SOURCE": "network"}):
        report = weights.prepare(env={**env, **broken}, entries=entries, mirror=mirror)
        assert report.error == "MODELS_MISSING", broken
    # RunPod's documented cache path is the default.
    assert weights.DEFAULT_CACHE_ROOT == Path("/runpod-volume/huggingface-cache/hub")


def test_the_endpoint_environment_pins_the_mirror_over_the_images_lock(tmp_path):
    # The studio keeps the expected mirror in its own settings and sets it on the endpoint,
    # so a new mirror commit needs no new image; the image's mirrors.lock.json is the default.
    files = tiny("stills")
    fake_cache(tmp_path / "hub", files)
    (tmp_path / "comfyui").mkdir()
    env = {
        "AMN_WORKER_IMAGE": "stills",
        "AMN_HF_CACHE": str(tmp_path / "hub"),
        "COMFY_DIR": str(tmp_path / "comfyui"),
        "AMN_MIRROR_REPO": REPO,
        "AMN_MIRROR_REVISION": REV,
    }
    entries = [entry for entry, _ in files]
    unpinned_lock = {"repo": None, "revision": None}
    report = weights.prepare(env=env, entries=entries, mirror=unpinned_lock)
    assert report.ok and report.revision == REV and report.repo == REPO
    elsewhere = {**env, "AMN_MIRROR_REVISION": OTHER}
    assert weights.prepare(env=elsewhere, entries=entries).error == "WRONG_REVISION"
    assert (
        weights.prepare(
            env={**env, "AMN_MIRROR_REVISION": ""}, entries=entries, mirror=unpinned_lock
        ).error
        == "WRONG_REVISION"
    )


def test_the_report_summary_is_loggable_and_names_no_secret(tmp_path):
    files = tiny("stills")
    fake_cache(tmp_path / "hub", files)
    summary = prepare(tmp_path, files).summary()
    assert summary["revision"] == REV and summary["error"] is None
    json.dumps(summary)  # plain data for the worker log


# ------------------------------------------------------------------------------- the lock files


def test_every_weight_has_its_path_inside_the_owners_mirror():
    seen: set[tuple[str, str]] = set()
    for entry in real_lock():
        folder = entry["target_dir"].removeprefix("models/")
        assert entry["mirror_path"] == f"{folder}/{Path(entry['file']).name}", entry["name"]
        assert ".." not in Path(entry["mirror_path"]).parts
        key = (entry["image"], entry["mirror_path"])
        assert key not in seen, key
        seen.add(key)


def test_the_reference_route_weights_are_pinned_as_the_research_cited():
    by_file = {entry["file"]: entry for entry in real_lock()}
    edit = by_file["split_files/diffusion_models/qwen_image_edit_2511_fp8mixed.safetensors"]
    assert edit["repo"] == "Comfy-Org/Qwen-Image-Edit_ComfyUI"
    assert edit["revision"] == EDIT_REVISION
    assert edit["sha256"] == EDIT_SHA256
    assert edit["size_bytes"] == 20533762817
    assert (edit["image"], edit["target_dir"], edit["licence_id"]) == (
        "stills",
        "models/diffusion_models",
        "Apache-2.0",
    )
    lora = by_file["Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16.safetensors"]
    assert lora["repo"] == "lightx2v/Qwen-Image-Edit-2511-Lightning"
    assert lora["revision"] == LORA_REVISION
    assert lora["sha256"] == LORA_SHA256
    assert lora["size_bytes"] == 849608296
    assert (lora["image"], lora["target_dir"], lora["licence_id"]) == (
        "stills",
        "models/loras",
        "Apache-2.0",
    )
    stills = sum(e["size_bytes"] for e in real_lock() if e["image"] == "stills")
    assert 60.2e9 < stills < 60.4e9  # 38.9 GB + 2511 (20.53 GB) + the LoRA (0.85 GB)


def test_the_gated_ltx_checksums_stay_null_until_the_gate_and_say_so():
    for entry in real_lock():
        if entry["sha256"] is None:
            assert entry["gated"] and entry["name"].startswith("LTX-2.5"), entry["name"]
            assert entry["sha256_status"] == "PIN_AFTER_GATE"
            assert "build resolve" in entry["note"] or "resolve" in entry["note"]
        else:
            assert "sha256_status" not in entry, entry["name"]


def test_every_weight_names_a_licence_the_mirror_copies():
    for entry in real_lock():
        assert entry["licence_id"] in build.LICENCES, entry["name"]
        if entry["name"].startswith("LTX-2.5"):
            assert entry["licence_id"] == "LTX-2.x"
    for licence in build.LICENCES.values():
        assert licence["url"].startswith("https://")
        assert build.HEX64.fullmatch(licence["sha256"])
        assert licence["path"].startswith("LICENSES/")
    assert build.LICENCES["LTX-2.x"]["must_contain"] == "Attachment A"


def test_the_mirrors_are_private_and_wait_for_their_pins():
    mirrors = json.loads((WORKER / "mirrors.lock.json").read_text(encoding="utf-8"))
    assert set(mirrors) == {"stills", "motion"}
    for image, mirror in mirrors.items():
        assert mirror["visibility"] == "private", image
        assert mirror["repo"] is None or weights.REPO_ID.fullmatch(mirror["repo"])
        assert mirror["revision"] is None or build.HEX40.fullmatch(mirror["revision"])
        assert weights.load_mirror(image) == mirror


# ---------------------------------------------------------------------------- build.py mirror


class FakeRepo:
    def __init__(self, private: bool) -> None:
        self.private = private
        self.files: dict[str, bytes] = {}
        self.commits: list[str] = []


class FakeHfApi:
    """The huggingface_hub HfApi calls build.py makes, in memory."""

    def __init__(self) -> None:
        self.repos: dict[str, FakeRepo] = {}
        self.uploads: list[str] = []
        self.fail_upload_at: int | None = None
        self.corrupt_remote: str | None = None

    def create_repo(
        self,
        repo_id: str,
        *,
        repo_type: str | None = None,
        private: Any = None,
        exist_ok: bool = False,
    ) -> None:
        assert repo_type == "model"
        if repo_id in self.repos:
            assert exist_ok
            return
        self.repos[repo_id] = FakeRepo(bool(private))

    def repo_info(self, repo_id: str, **kwargs: Any) -> Any:
        repo = self.repos[repo_id]
        return SimpleNamespace(private=repo.private, sha=repo.commits[-1] if repo.commits else None)

    def get_paths_info(self, repo_id: str, paths: Any, *, expand: bool = False, **kw: Any) -> Any:
        repo = self.repos[repo_id]
        found = []
        for path in [paths] if isinstance(paths, str) else paths:
            if path not in repo.files:
                continue
            data = repo.files[path]
            lfs = None
            if path.endswith(".safetensors"):
                digest = sha(data) if path != self.corrupt_remote else "0" * 64
                lfs = {"sha256": digest, "size": len(data), "pointer_size": 130}
            blob = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
            found.append(SimpleNamespace(path=path, size=len(data), blob_id=blob, lfs=lfs))
        return found

    def upload_file(
        self,
        *,
        path_or_fileobj: Any,
        path_in_repo: str,
        repo_id: str,
        commit_message: str | None = None,
        **kwargs: Any,
    ) -> Any:
        if self.fail_upload_at is not None and len(self.uploads) == self.fail_upload_at:
            self.fail_upload_at = None
            raise RuntimeError("connection reset")
        if isinstance(path_or_fileobj, (bytes, bytearray)):
            data = bytes(path_or_fileobj)
        else:
            data = Path(path_or_fileobj).read_bytes()
        repo = self.repos[repo_id]
        repo.files[path_in_repo] = data
        repo.commits.append(hashlib.sha1(repr(sorted(repo.files.items())).encode()).hexdigest())
        self.uploads.append(path_in_repo)
        return SimpleNamespace(oid=repo.commits[-1])


class Answer:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def __enter__(self) -> Answer:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = len(self.data)
        chunk, self.data = self.data[:size], self.data[size:]
        return chunk


LICENCE_TEXTS = {
    "Apache-2.0": b"Apache License Version 2.0 (stand-in)\n",
    "LTX-2.x": b"LTX-2.x Community License Agreement\n...\nAttachment A\nUse Restrictions\n",
    "MIT-Practical-RIFE": b"MIT License (stand-in)\n",
}
TOKEN = "hf_fake_mirror_token"  # pragma: allowlist secret


class Upstream:
    """Hugging Face (and the licence hosts) behind a fake opener; records every request."""

    def __init__(self, files: list[tuple[dict[str, Any], bytes]]) -> None:
        self.by_url: dict[str, bytes] = {}
        self.requests: list[Any] = []
        for entry, data in files:
            url = f"https://huggingface.co/{entry['repo']}/resolve/{entry['revision']}/{entry['file']}"
            self.by_url[url] = data
        for licence_id, licence in build.LICENCES.items():
            self.by_url[licence["url"]] = LICENCE_TEXTS[licence_id]

    def __call__(self, request: Any, timeout: float) -> Answer:
        self.requests.append(request)
        return Answer(self.by_url[request.full_url])


@pytest.fixture
def mirror_env(monkeypatch):
    files = tiny("stills")
    entries = [entry for entry, _ in files]
    monkeypatch.setattr(build, "load_models_lock", lambda: entries)
    licences = {
        key: {**value, "sha256": sha(LICENCE_TEXTS[key])} for key, value in build.LICENCES.items()
    }
    monkeypatch.setattr(build, "LICENCES", licences)
    monkeypatch.setenv("AMN_MIRROR_HOST", "pod")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    return SimpleNamespace(files=files, entries=entries, api=FakeHfApi(), upstream=Upstream(files))


def run_mirror(env: Any, tmp_path: Path, image: str = "stills") -> str:
    plan = build.mirror_plan(image, REPO)
    return build.mirror_execute(
        plan, api=env.api, scratch=tmp_path / "scratch", token=TOKEN, opener=env.upstream
    )


def test_the_mirror_plan_names_every_locked_file_and_touches_nothing(monkeypatch, capsys):
    called: list[Any] = []
    monkeypatch.setattr(build, "_hf_api", lambda token: called.append(token))
    assert build.main(["mirror", "--image", "stills", "--repo", REPO]) == 0
    out = capsys.readouterr().out
    for entry in real_lock():
        if entry["image"] == "stills":
            assert entry["mirror_path"] in out
    assert "private" in out and "LICENSES/Apache-2.0.txt" in out
    assert called == []  # a plan never talks to the Hub


def test_the_mirror_plan_refuses_the_motion_copy_until_the_ltx_checksums_are_pinned(capsys):
    assert build.main(["mirror", "--image", "motion", "--repo", "owner-test/amn-motion"]) != 0
    assert "sha256 not pinned" in capsys.readouterr().err
    with pytest.raises(ValueError):
        build.mirror_plan("stills", "https://huggingface.co/owner/repo")


def test_the_copy_runs_only_on_the_copy_pod_with_a_token(monkeypatch, capsys):
    called: list[Any] = []
    monkeypatch.setattr(build, "_hf_api", lambda token: called.append(token))
    argv = ["mirror", "--image", "stills", "--repo", REPO, "--execute"]
    monkeypatch.delenv("AMN_MIRROR_HOST", raising=False)
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    assert build.main(argv) == 3
    assert "AMN_MIRROR_HOST" in capsys.readouterr().err
    monkeypatch.setenv("AMN_MIRROR_HOST", "pod")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert build.main(argv) == 3
    assert called == []


def test_the_copy_fills_a_private_mirror_with_verified_files_licences_and_a_manifest(
    mirror_env, tmp_path, capsys
):
    revision = run_mirror(mirror_env, tmp_path)
    repo = mirror_env.api.repos[REPO]
    assert repo.private is True
    for entry, data in mirror_env.files:
        assert repo.files[entry["mirror_path"]] == data
    assert repo.files["LICENSES/Apache-2.0.txt"] == LICENCE_TEXTS["Apache-2.0"]
    assert "LICENSES/LTX-2.x-Community-License.txt" not in repo.files  # stills only
    manifest = json.loads(repo.files["MIRROR_MANIFEST.json"])
    assert manifest["image"] == "stills" and manifest["repo"] == REPO
    listed = {item["mirror_path"]: item for item in manifest["files"]}
    for entry, _data in mirror_env.files:
        item = listed[entry["mirror_path"]]
        assert (item["upstream_repo"], item["upstream_revision"], item["upstream_file"]) == (
            entry["repo"],
            entry["revision"],
            entry["file"],
        )
        assert (item["sha256"], item["size_bytes"]) == (entry["sha256"], entry["size_bytes"])
    readme = repo.files["README.md"].decode()
    assert "Apache-2.0" in readme and REPO in readme
    assert revision == repo.commits[-1]
    assert revision in capsys.readouterr().out
    assert list((tmp_path / "scratch").rglob("*.safetensors")) == []  # the pod disk is freed


def test_the_token_goes_to_hugging_face_only_and_is_never_printed(mirror_env, tmp_path, capsys):
    run_mirror(mirror_env, tmp_path)
    assert mirror_env.upstream.requests
    for request in mirror_env.upstream.requests:
        assert TOKEN not in request.full_url
        host = request.full_url.split("/")[2]
        expected = f"Bearer {TOKEN}" if host == "huggingface.co" else None
        assert request.get_header("Authorization") == expected, request.full_url
    printed = capsys.readouterr()
    assert TOKEN not in printed.out and TOKEN not in printed.err


def test_a_second_copy_uploads_nothing(mirror_env, tmp_path):
    first = run_mirror(mirror_env, tmp_path)
    uploads = len(mirror_env.api.uploads)
    requests = len(mirror_env.upstream.requests)
    assert run_mirror(mirror_env, tmp_path) == first
    assert len(mirror_env.api.uploads) == uploads
    # Nothing downloaded again either (the licences are re-read; they are a few KB).
    weights_again = [
        r for r in mirror_env.upstream.requests[requests:] if "/resolve/" in r.full_url
    ]
    assert weights_again == []


def test_an_interrupted_copy_resumes_with_the_missing_files_only(mirror_env, tmp_path):
    mirror_env.api.fail_upload_at = 2
    with pytest.raises(RuntimeError):
        run_mirror(mirror_env, tmp_path)
    done = list(mirror_env.api.uploads)
    assert len(done) == 2
    run_mirror(mirror_env, tmp_path)
    again = mirror_env.api.uploads[2:]
    assert not set(again) & set(done)
    repo = mirror_env.api.repos[REPO]
    assert all(repo.files[e["mirror_path"]] == d for e, d in mirror_env.files)


def test_a_mirror_file_with_the_right_name_but_other_bytes_is_copied_again(mirror_env, tmp_path):
    # Adversary pass 2026-10-09: a resume trusts the Hub's sha256 and size, never the name.
    entry, data = mirror_env.files[0]
    other = mirror_env.files[1][0]
    repo = FakeRepo(private=True)
    repo.files[entry["mirror_path"]] = data[:-1] + bytes([data[-1] ^ 1])  # same size, other bytes
    repo.files[other["mirror_path"]] = data  # another file's bytes: wrong sha and size there
    mirror_env.api.repos[REPO] = repo
    run_mirror(mirror_env, tmp_path)
    assert mirror_env.api.uploads.count(entry["mirror_path"]) == 1
    assert mirror_env.api.uploads.count(other["mirror_path"]) == 1
    assert all(repo.files[e["mirror_path"]] == d for e, d in mirror_env.files)


def test_a_public_mirror_is_refused(mirror_env, tmp_path):
    mirror_env.api.repos[REPO] = FakeRepo(private=False)
    with pytest.raises(ValueError) as refused:
        run_mirror(mirror_env, tmp_path)
    assert "private" in str(refused.value)
    assert mirror_env.api.uploads == []


def test_a_download_that_does_not_match_the_lock_is_never_uploaded(mirror_env, tmp_path):
    entry, _data = mirror_env.files[0]
    url = f"https://huggingface.co/{entry['repo']}/resolve/{entry['revision']}/{entry['file']}"
    mirror_env.upstream.by_url[url] = b"not the weights"
    with pytest.raises(ValueError):
        run_mirror(mirror_env, tmp_path)
    assert entry["mirror_path"] not in mirror_env.api.uploads
    assert [p for p in (tmp_path / "scratch").rglob("*") if p.is_file()] == []


def test_an_upload_the_hub_does_not_confirm_stops_the_copy(mirror_env, tmp_path):
    mirror_env.api.corrupt_remote = mirror_env.files[0][0]["mirror_path"]
    with pytest.raises(ValueError) as refused:
        run_mirror(mirror_env, tmp_path)
    assert mirror_env.files[0][0]["mirror_path"] in str(refused.value)


def test_a_licence_text_that_changed_is_refused(mirror_env, tmp_path):
    mirror_env.upstream.by_url[build.LICENCES["Apache-2.0"]["url"]] = b"something else"
    with pytest.raises(ValueError) as refused:
        run_mirror(mirror_env, tmp_path)
    assert "Apache-2.0" in str(refused.value)


def test_the_motion_mirror_carries_the_ltx_licence_with_its_attachment_a(monkeypatch, tmp_path):
    files = tiny("motion")
    entries = [entry for entry, _ in files]
    monkeypatch.setattr(build, "load_models_lock", lambda: entries)
    licences = {k: {**v, "sha256": sha(LICENCE_TEXTS[k])} for k, v in build.LICENCES.items()}
    monkeypatch.setattr(build, "LICENCES", licences)
    api, upstream = FakeHfApi(), Upstream(files)
    plan = build.mirror_plan("motion", "owner-test/amn-motion")
    build.mirror_execute(plan, api=api, scratch=tmp_path, token=TOKEN, opener=upstream)
    repo = api.repos["owner-test/amn-motion"]
    ltx = repo.files["LICENSES/LTX-2.x-Community-License.txt"].decode()
    assert "Attachment A" in ltx
    assert "LICENSES/MIT-Practical-RIFE.txt" in repo.files
    readme = repo.files["README.md"].decode()
    assert "machine generated" in readme or "AI" in readme  # the disclosure duty is named
    # A LTX licence text without its Attachment A is refused even with a matching checksum.
    no_attachment = b"LTX-2.x Community License Agreement\n"
    upstream.by_url[licences["LTX-2.x"]["url"]] = no_attachment
    licences["LTX-2.x"]["sha256"] = sha(no_attachment)
    with pytest.raises(ValueError):
        build.mirror_execute(plan, api=FakeHfApi(), scratch=tmp_path, token=TOKEN, opener=upstream)


# ------------------------------------------------------------------------ the small images


@pytest.mark.parametrize("image", ["stills", "motion"])
def test_each_small_image_has_its_own_dockerfile_with_its_pins_written_in(image):
    text = (WORKER / f"Dockerfile.{image}").read_text(encoding="utf-8")
    lines = [line.strip() for line in text.splitlines()]
    assert f"ARG BASE_IMAGE={build.BASE_IMAGE}" in lines
    assert f"ARG BASE_DIGEST={build.BASE_DIGEST}" in lines
    assert f"ARG COMFYUI_VERSION={build.COMFYUI_VERSION}" in lines
    assert "FROM ${BASE_IMAGE}@${BASE_DIGEST}" in lines
    assert not any(line.startswith("FROM") and " AS " in line.upper() for line in lines)
    # No weights and no Hugging Face secret: RunPod's GitHub build has neither.
    for banned in ("--mount=type=secret", "hf_token", "HF_TOKEN", "build fetch", "fetch --image"):
        assert banned not in text, banned
    assert f"AMN_WORKER_IMAGE={image}" in text and "AMN_MODEL_SOURCE=cache" in text
    assert "COPY . /opt/amn/runpod_worker/" in text
    assert 'CMD ["python", "-u", "-m", "runpod_worker.amn_handler"]' in text


def test_the_two_small_dockerfiles_differ_only_by_their_image():
    stills = (WORKER / "Dockerfile.stills").read_text(encoding="utf-8")
    motion = (WORKER / "Dockerfile.motion").read_text(encoding="utf-8")
    assert stills.replace("stills", "IMAGE") == motion.replace("motion", "IMAGE")


def test_the_baked_recipe_is_the_documented_last_resort_and_says_where_its_weights_are():
    text = (WORKER / "Dockerfile").read_text(encoding="utf-8")
    assert "LAST RESORT" in text
    assert text.count("AMN_MODEL_SOURCE=baked") >= 2  # both stages check /comfyui/models


def test_the_build_context_ignores_the_other_dockerfiles_and_secrets():
    ignore = (WORKER / ".dockerignore").read_text(encoding="utf-8").splitlines()
    for pattern in ("Dockerfile", "Dockerfile.*", ".env", "*.key", "hf_token", "*.safetensors"):
        assert pattern in ignore, pattern


# ------------------------------------------------------------------- the standalone repository


def test_the_export_writes_the_worker_as_a_repository_root(tmp_path):
    dest = tmp_path / "amn-runpod-worker"
    written = export_repo.export(dest)
    names = {path.relative_to(dest).as_posix() for path in dest.rglob("*") if path.is_file()}
    assert names == set(written) | {"EXPORT_MANIFEST.json"}
    for wanted in (
        "Dockerfile.stills",
        "Dockerfile.motion",
        ".dockerignore",
        "README.md",
        "requirements.txt",
        "amn_handler.py",
        "weights.py",
        "contract.py",
        "models.lock.json",
        "mirrors.lock.json",
        "workflows/qwen_image_edit_2511_ref_seedvr2.json",
    ):
        assert wanted in names, wanted
    # The baked last resort needs a Hugging Face secret and build args: never in that repo.
    assert "Dockerfile" not in names and "export_repo.py" not in names
    assert not any("__pycache__" in name or name.endswith(".pyc") for name in names)
    for name in written:
        if name != "README.md":
            # Byte copies, with line endings made LF (a Windows checkout may hold CRLF; the
            # image is built on Linux from the Owner's push).
            source = (WORKER / name).read_bytes().replace(b"\r\n", b"\n")
            assert (dest / name).read_bytes() == source, name
            assert b"\r\n" not in (dest / name).read_bytes(), name
    readme = (dest / "README.md").read_text(encoding="utf-8")
    assert "Dockerfile.stills" in readme and "Dockerfile.motion" in readme
    assert "release" in readme  # RunPod rebuilds only on a GitHub release
    manifest = json.loads((dest / "EXPORT_MANIFEST.json").read_text(encoding="utf-8"))
    for name in written:
        assert manifest["files"][name] == hashlib.sha256((dest / name).read_bytes()).hexdigest()


def test_every_copy_source_of_the_small_dockerfiles_is_in_the_export(tmp_path):
    dest = tmp_path / "repo"
    export_repo.export(dest)
    for image in ("stills", "motion"):
        for line in (dest / f"Dockerfile.{image}").read_text(encoding="utf-8").splitlines():
            if line.startswith("COPY "):
                source = line.split()[1]
                assert source == "." or (dest / source).exists(), line


def test_the_exported_worker_imports_as_its_package_without_the_studio(tmp_path):
    dest = tmp_path / "repo"
    export_repo.export(dest)
    # The image copies the repository root to /opt/amn/runpod_worker (Dockerfile COPY).
    package = tmp_path / "opt" / "amn" / "runpod_worker"
    shutil.copytree(dest, package)
    code = (
        "import runpod_worker.amn_handler, runpod_worker.weights, runpod_worker.build;"
        "import sys; assert not any(m == 'app' or m.startswith('app.') for m in sys.modules)"
    )
    env = {**os.environ, "PYTHONPATH": str(tmp_path / "opt" / "amn")}
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_the_export_is_idempotent_and_refuses_a_folder_it_did_not_write(tmp_path):
    dest = tmp_path / "repo"
    export_repo.export(dest)
    (dest / "workflows" / "stale.json").write_text("{}", encoding="utf-8")
    manifest = json.loads((dest / "EXPORT_MANIFEST.json").read_text(encoding="utf-8"))
    manifest["files"]["workflows/stale.json"] = "0" * 64
    (dest / "EXPORT_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
    export_repo.export(dest)
    assert not (dest / "workflows" / "stale.json").exists()  # removed: no longer exported
    (dest / ".git").mkdir()  # the Owner's own git folder is never touched
    (dest / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    export_repo.export(dest)
    assert (dest / ".git" / "HEAD").exists()
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(ValueError):
        export_repo.export(foreign)
    with pytest.raises(ValueError):
        export_repo.export(ROOT / "exported-worker")  # never inside the studio's own repo


def test_the_export_command_prints_where_it_wrote(tmp_path, capsys):
    dest = tmp_path / "repo"
    assert export_repo.main(["--dest", str(dest)]) == 0
    assert str(dest) in capsys.readouterr().out
    assert export_repo.main(["--dest", str(ROOT / "exported-worker")]) == 2


@pytest.mark.parametrize(
    ("mirror", "variable"),
    [({"repo": None, "revision": REV}, "AMN_MIRROR_REPO"), ({"repo": REPO}, "AMN_MIRROR_REVISION")],
)
def test_an_unpinned_mirror_names_the_endpoint_variable_to_set(tmp_path, mirror, variable):
    # The studio cannot set the endpoint's env (a release): the refusal names the variable, so
    # the Owner's console step is in the worker's own words too (completeness critic 2026-10-09).
    files = tiny("stills")
    fake_cache(tmp_path / "hub", files)
    report = prepare(tmp_path, files, mirror=mirror)
    assert report.error == "WRONG_REVISION"
    assert variable in " ".join(report.problems)


def test_the_exported_readme_tells_him_the_endpoint_pin(tmp_path):
    # The worker refuses WRONG_REVISION until its endpoint carries AMN_MIRROR_REPO and
    # AMN_MIRROR_REVISION (or a re-released mirrors.lock.json): his steps must say so.
    dest = tmp_path / "worker-repo"
    export_repo.export(dest)
    readme = (dest / "README.md").read_text(encoding="utf-8")
    assert "AMN_MIRROR_REPO" in readme and "AMN_MIRROR_REVISION" in readme
    assert "Environment Variables" in readme


def test_the_copys_last_printed_commit_is_the_mirror_revision(mirror_env, tmp_path, capsys):
    # The copy pod's BOOTSTRAP (app.providers.runpod.pods) takes the LAST 40-hex string the
    # copy prints as the mirror commit; the plan prints upstream commits first. Pinned here so
    # a new print after the revision cannot silently record a wrong commit.
    import re

    revision = run_mirror(mirror_env, tmp_path)
    printed = re.findall(r"\b[0-9a-f]{40}\b", capsys.readouterr().out)
    assert printed and printed[-1] == revision
