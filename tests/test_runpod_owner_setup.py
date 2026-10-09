"""What the Owner needs before his first capped paid RunPod test (2026-10-08, completeness).

- The worker image builds from a base image that exists, pinned by digest, on the ComfyUI
  release the graphs were checked against; every public weight is pinned from Hugging Face's
  own metadata, and the gated LTX-2.5 checksums are pinned by ``build resolve`` with HIS token
  (metadata only, never a download).
- A RunPod step refuses BEFORE the Owner's yes is asked or spent while the GPU could not be
  switched on anyway (his card not accepted, the bucket missing).

Every RunPod, bucket and Hugging Face call is faked; nothing is built or downloaded.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from app.media import gpu_batch
from app.models import ApprovalRequest
from runpod_worker import build
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "backend" / "runpod_worker"
#: The published base (Docker Hub runpod/worker-comfyui:5.10.0-base, an OCI index), read from
#: the registry on 2026-10-08; 5.11.0 has a GitHub tag but no published image.
BASE_TAG = "runpod/worker-comfyui:5.10.0-base"
BASE_DIGEST = "sha256:e9d18d3db15839ebb10c10c824109fc2956f31ef7bf21916220c008855b0d538"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REAL_PRECHECK = gpu_batch.gpu_precheck


def lock() -> list[dict[str, Any]]:
    return json.loads((WORKER / "models.lock.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------- the worker image


def test_the_base_image_is_a_published_tag_pinned_by_its_digest():
    text = (WORKER / "Dockerfile").read_text(encoding="utf-8")
    assert f"ARG BASE_IMAGE={BASE_TAG}" in text
    assert "5.11.0-base" not in text
    assert build.BASE_IMAGE == BASE_TAG
    assert build.BASE_DIGEST == BASE_DIGEST
    # The release whose source every node of the three graphs was checked against.
    assert build.COMFYUI_VERSION == "0.39.2"


def test_every_public_weight_is_pinned_and_the_gated_ones_wait_only_for_their_checksum():
    for entry in lock():
        assert HEX40.fullmatch(str(entry["revision"])), entry["name"]
        assert isinstance(entry["size_bytes"], int) and entry["size_bytes"] > 0, entry["name"]
        if entry["gated"]:
            # Hugging Face masks a gated file's checksum until the Owner accepts its licence.
            assert entry["sha256"] is None or HEX64.fullmatch(entry["sha256"]), entry["name"]
        else:
            assert HEX64.fullmatch(str(entry["sha256"])), entry["name"]


def test_the_stills_image_can_be_planned_and_motion_waits_for_the_ltx_checksums():
    assert build.unresolved("stills") == []
    commands = build.plan("stills", "registry.example.test/amn", "v1")
    assert f"BASE_DIGEST={BASE_DIGEST}" in commands[0]
    gated = [e["name"] for e in lock() if e["image"] == "motion" and not e["sha256"]]
    assert gated and all("LTX" in name for name in gated)
    assert build.unresolved("motion") == [f"{name}: sha256 not pinned" for name in gated]


class _Answer:
    def __init__(self, payload: Any) -> None:
        self.data = json.dumps(payload).encode()

    def __enter__(self) -> _Answer:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def read(self, *args: Any) -> bytes:
        data, self.data = self.data, b""
        return data


def _gated_lock(tmp_path: Path) -> tuple[Path, list[dict[str, Any]]]:
    entries = [
        {**entry, "sha256": None} if entry["gated"] else entry
        for entry in lock()
        if entry["image"] == "motion"
    ]
    path = tmp_path / "models.lock.json"
    path.write_text(json.dumps(entries, indent=2) + "\n", encoding="utf-8")
    return path, entries


def test_resolve_pins_the_gated_checksums_from_metadata_with_his_token_only(tmp_path):
    path, entries = _gated_lock(tmp_path)
    seen: list[Any] = []

    def opener(request: Any, timeout: float) -> _Answer:
        seen.append(request)
        file = parse_qs(request.data.decode())["paths"][0]
        entry = next(e for e in entries if e.get("file") == file)
        digest = (entry["name"].encode().hex() * 8)[:64]
        return _Answer(
            [{"type": "file", "path": file, "lfs": {"oid": digest, "size": entry["size_bytes"]}}]
        )

    pinned = build.resolve(
        "motion",
        token="hf_fake_token",  # pragma: allowlist secret
        lock_path=path,
        opener=opener,
    )
    gated = [e for e in entries if e["gated"]]
    assert sorted(pinned) == sorted(e["name"] for e in gated)
    written = json.loads(path.read_text(encoding="utf-8"))
    assert all(HEX64.fullmatch(str(e["sha256"])) for e in written)
    for request in seen:
        parts = urlsplit(request.full_url)
        assert parts.scheme == "https" and parts.hostname == "huggingface.co"
        assert "/paths-info/" in parts.path and "/resolve/" not in parts.path  # never a download
        assert "hf_fake_token" not in request.full_url
        assert request.get_header("Authorization") == "Bearer hf_fake_token"
        assert parse_qs(request.data.decode())["expand"] == ["true"]
    assert len(seen) == len(gated)


def test_resolve_refuses_a_size_that_differs_from_the_lock_and_writes_nothing(tmp_path):
    path, _entries = _gated_lock(tmp_path)
    before = path.read_text(encoding="utf-8")

    def opener(request: Any, timeout: float) -> _Answer:
        file = parse_qs(request.data.decode())["paths"][0]
        return _Answer([{"type": "file", "path": file, "lfs": {"oid": "a" * 64, "size": 1}}])

    with pytest.raises(ValueError, match="size"):
        build.resolve("motion", token="hf_fake_token", lock_path=path, opener=opener)
    assert path.read_text(encoding="utf-8") == before
    with pytest.raises(ValueError, match="HF_TOKEN"):
        build.resolve("motion", token="", lock_path=path, opener=opener)


def test_resolve_from_the_command_line_needs_the_token(monkeypatch, capsys):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    assert build.main(["resolve", "--image", "motion"]) == 2
    assert "HF_TOKEN" in capsys.readouterr().err


# --------------------------------------------- the Owner's yes is not spent on a dead GPU


@pytest.fixture
def faked_gpu(monkeypatch):
    """The GPU session faked as in test_runpod_batch (opened sessions recorded), with the
    precheck standing aside until a test puts the real one back."""
    from contextlib import contextmanager

    from test_runpod_batch import Session_

    opened: list[dict[str, Any]] = []

    @contextmanager
    def fake(engine, adapter, *, purpose, permit):
        opened.append({"purpose": purpose, "closed": False})
        try:
            yield Session_()
        finally:
            opened[-1]["closed"] = True

    monkeypatch.setattr(gpu_batch, "gpu_session", fake)
    monkeypatch.setattr(gpu_batch, "gpu_precheck", lambda *args, **kwargs: None)
    return opened


def _vault_and_runpod(engine, monkeypatch, *, allow: bool) -> str:
    from test_runpod_gpu_policy import runpod

    _vault, identifier = runpod(engine, monkeypatch, allow=allow)
    return identifier


def test_precheck_reads_the_card_and_the_bucket_and_passes_a_simulation(engine, tmp_path):
    from app.providers.runpod.gpu_session import GpuSessionRefused
    from test_runpod_batch import Cloud, adapter

    made = adapter(engine, tmp_path, Cloud())
    with pytest.raises(GpuSessionRefused) as refused:
        REAL_PRECHECK(engine, made, purpose="image")
    assert refused.value.code == "BLOCKED_INFRA_DISABLED" and refused.value.unsent
    no_bucket = adapter(engine, tmp_path, Cloud(), s3_bucket="")
    with pytest.raises(GpuSessionRefused) as refused:
        REAL_PRECHECK(engine, no_bucket, purpose="image")
    assert refused.value.code == "NOT_CONFIGURED"
    REAL_PRECHECK(engine, adapter(engine, tmp_path, Cloud(), mock=True), purpose="image")


#: His stills mirror, copied (2026-10-09): the cached model the stills endpoint reads.
MIRROR = {"stills_mirror_repo": "owner/amn-stills", "stills_mirror_revision": "a" * 40}


def test_precheck_passes_once_his_card_is_accepted(engine, tmp_path, monkeypatch):
    from test_runpod_batch import Cloud, adapter

    made = adapter(engine, tmp_path, Cloud(), **MIRROR)
    made.integration_id = _vault_and_runpod(engine, monkeypatch, allow=True)
    REAL_PRECHECK(engine, made, purpose="image")


def test_stills_refuse_before_his_yes_is_spent_while_agents_may_not_switch_the_gpu_on(
    engine, tmp_path, monkeypatch, faked_gpu
):
    from app.media.stills_stage import StillsStageRefused, run_stills_stage, stills_plan
    from test_approvals import answer
    from test_runpod_batch import PictureCloud, adapter, stills_table
    from test_stills_stage import NO_FACE, SpyJudge, a_film, faces_in

    storyboard_id = a_film(engine, tmp_path)
    cloud = PictureCloud(lambda prompt: NO_FACE[0].read_bytes())
    made = adapter(engine, tmp_path, cloud, **MIRROR)
    table = stills_table()

    def go() -> dict[str, Any]:
        return run_stills_stage(
            engine,
            storyboard_id,
            str(uuid4()),
            plan_hash=stills_plan(engine, storyboard_id, model_id=made.model, table=table)[
                "plan_hash"
            ],
            image_adapter=made,
            registry=None,
            judge=SpyJudge(),
            storage_root=tmp_path / "media",
            table=table,
            face_counter=faces_in(),
            measure=("faces",),
        )

    # His yes, given while the precheck was not there yet (or the card was accepted then).
    with pytest.raises(StillsStageRefused) as asked:
        go()
    assert asked.value.status == "NEEDS_APPROVAL"
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, imaginile.")

    monkeypatch.setattr(gpu_batch, "gpu_precheck", REAL_PRECHECK)
    with pytest.raises(StillsStageRefused) as refused:
        go()
    assert refused.value.status == "BLOCKED_INFRA_DISABLED"
    assert "fereastra Decizii" in refused.value.reason_ro
    assert not cloud.calls and not faked_gpu
    with Session(engine) as session:
        approval = session.get(ApprovalRequest, asked.value.approval_id)
        assert approval is not None and approval.consumed_at is None  # his yes is still his

    made.integration_id = _vault_and_runpod(engine, monkeypatch, allow=True)
    go()
    assert cloud.posts() and len(faked_gpu) == 1
    with Session(engine) as session:
        approval = session.get(ApprovalRequest, asked.value.approval_id)
        assert approval is not None and approval.consumed_at is not None


def test_motion_refuses_before_asking_him_while_agents_may_not_switch_the_gpu_on(
    engine, tmp_path, monkeypatch, faked_gpu
):
    from app.media.assembler import MotionStepRefused, motion_plan, run_motion_step
    from app.providers.runpod.adapters import RunPodVideoAdapter
    from test_clip_qc_wiring import ScriptedCheck
    from test_film_costing import a_film
    from test_runpod_batch import (
        Cloud,
        finishing_video,
        motion_table,
        runpod_capability,
        serverless,
    )

    monkeypatch.setattr(gpu_batch, "gpu_precheck", REAL_PRECHECK)
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    cloud = finishing_video(Cloud())
    made = RunPodVideoAdapter(serverless(), engine, model="LTX-2.5", storage_root=tmp_path)
    made.core.transport = made.core.client.transport = cloud
    capability = runpod_capability()
    table = motion_table()
    plan = motion_plan(engine, storyboard_id, capabilities=[capability], table=table)
    with pytest.raises(MotionStepRefused) as refused:
        run_motion_step(
            engine,
            storyboard_id,
            str(uuid4()),
            step="test_shot",
            plan_hash=plan["plan_hash"],
            adapter_for_model=lambda model: made if model == "LTX-2.5" else None,
            capabilities=[capability],
            table=table,
            storage_root=tmp_path / "media",
            clip_check=ScriptedCheck("PASSED"),
        )
    assert refused.value.status == "BLOCKED_INFRA_DISABLED"
    assert not cloud.inner.calls and not faked_gpu
    with Session(engine) as session:
        assert session.scalars(select(ApprovalRequest)).all() == []  # nothing asked of him


# --------------------------------------------------------------- the Settings card's words


def test_the_runpod_verify_hint_names_what_serverless_needs():
    from app.integrations.discovery import DISCOVERED_KINDS

    hint = DISCOVERED_KINDS["runpod"]["verify_hint"]
    assert "adresa cloud" not in hint
    assert "endpoint" in hint and "bucket" in hint and "RUNPOD_ENABLED=true" in hint


# ------------------------------------------- the weight pins are checksums, not credentials


def test_the_secret_scan_reads_weight_pins_as_checksums_but_still_catches_a_key(tmp_path, capsys):
    import importlib.util
    import secrets
    import string

    spec = importlib.util.spec_from_file_location(
        "check_secrets_pins", ROOT / "scripts" / "check_secrets.py"
    )
    assert spec is not None and spec.loader is not None
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    root = tmp_path / "tree"
    folder = root / "backend" / "runpod_worker"
    folder.mkdir(parents=True)
    pins = [{"name": e["name"], "revision": e["revision"], "sha256": e["sha256"]} for e in lock()]
    path = folder / "models.lock.json"
    path.write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(json.dumps({"results": {}}), encoding="utf-8")
    assert gate.main(["--baseline", str(baseline)], root=root) == 0
    capsys.readouterr()
    alphabet = string.ascii_letters + string.digits
    key = "sk-" + "".join(secrets.choice(alphabet) for _ in range(40))
    pins[0]["note"] = key
    path.write_text(json.dumps(pins, indent=2) + "\n", encoding="utf-8")
    assert gate.main(["--baseline", str(baseline)], root=root) == 1
    assert "models.lock.json" in capsys.readouterr().out
