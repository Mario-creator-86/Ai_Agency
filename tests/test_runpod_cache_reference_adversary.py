"""Adversary pass (2026-10-09) over the RunPod cached-model weights and the reference route.

Attacks, each faked end to end (no RunPod, Hugging Face, GitHub or registry call):

* the worker's cache check: refs/main absent, an empty snapshots folder, an empty pinned
  snapshot, a locked name that is a folder, a revision pin that is not a lowercase commit;
  and the model-paths file read the way ComfyUI v0.39.2 reads it (utils/extra_config.py and
  folder_paths.get_full_path at commit 3c1b7a17), so every loader of every stills/motion graph
  finds its file in the snapshot;
* the reference route: the studio catalogue and the worker's graphs declare the SAME
  bindings, so what the journal records (``reference_bindings``) is what the graph binds; a
  worker handed a picture its graph cannot bind refuses it before its claim instead of making
  the still from the words and letting the record say "drawn from a picture";
* the unbilled cache wait is inside every chunk's ttl and inside the studio's own deadline for
  the round (the studio never gives up on a job RunPod is still allowed to start);
* a locked character is refused on a model that takes no reference, in the stills step on
  RunPod's 2512 route and in a one-scene still redo (which did not check it).
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest
import yaml
from app.media import cost_plan
from app.providers.runpod import batch as batch_module
from app.providers.runpod.adapters import RunPodImageAdapter
from app.providers.runpod.models import reference_spec, serverless_catalogue
from runpod_worker import amn_handler, contract, weights
from test_runpod_batch import (  # noqa: F401 - the fixture is used by name
    Cloud,
    PictureCloud,
    Session_,
    adapter,
    request,
    serverless,
)
from test_runpod_worker import (  # noqa: F401 - the fixture is used by name
    LOADER_FOLDERS,
    PREFIX,
    _registered_refs,
    batch,
    claim_key,
    image_item,
    ref_item,
    ref_maker,
    worker,
)
from test_runpod_worker_weights import REPO, REV, WORKER, fake_cache, prepare, tiny

ROUTE = "Qwen-Image-Edit-2511"

# ---------------------------------------------------------------- the worker's cache check


def test_refs_main_absent_is_fine_when_the_pinned_snapshot_is_there(tmp_path):
    files = tiny("stills")
    snapshot = fake_cache(tmp_path / "hub", files, main=None)
    report = prepare(tmp_path, files)
    assert report.ok, report.problems
    assert report.root == snapshot and report.revision == REV


def test_an_empty_snapshots_folder_is_models_missing_and_writes_no_paths(tmp_path):
    files = tiny("stills")
    base = tmp_path / "hub" / weights.cache_folder(REPO)
    (base / "snapshots").mkdir(parents=True)
    report = prepare(tmp_path, files)
    assert report.error == "MODELS_MISSING" and report.yaml_path is None
    assert not (tmp_path / "comfyui" / weights.YAML_NAME).exists()


def test_an_empty_pinned_snapshot_names_every_locked_file(tmp_path):
    files = tiny("stills")
    (tmp_path / "hub" / weights.cache_folder(REPO) / "snapshots" / REV).mkdir(parents=True)
    report = prepare(tmp_path, files)
    assert report.error == "MODELS_MISSING" and report.yaml_path is None
    text = " ".join(report.problems)
    assert all(entry["mirror_path"] in text for entry, _ in files)


def test_a_locked_name_that_is_a_folder_is_not_a_weight(tmp_path):
    files = tiny("stills")
    snapshot = fake_cache(tmp_path / "hub", files)
    target = snapshot / files[0][0]["mirror_path"]
    target.unlink()
    target.mkdir()
    report = prepare(tmp_path, files)
    assert report.error == "MODELS_MISSING" and report.yaml_path is None


@pytest.mark.parametrize(
    "revision",
    [REV.upper().replace("1", "A"), "../" + REV[3:], REV + "\n" + REV, " " * 40],
)
def test_an_endpoint_pin_that_is_not_a_lowercase_commit_is_refused(tmp_path, revision):
    files = tiny("stills")
    fake_cache(tmp_path / "hub", files)
    report = prepare(tmp_path, files, env={"AMN_MIRROR_REVISION": revision})
    assert report.error == "WRONG_REVISION" and report.yaml_path is None


def _comfy_full_path(yaml_text: str, folder: str, filename: str) -> str | None:
    """ComfyUI v0.39.2 (3c1b7a17): utils/extra_config.py load_extra_path_config (base_path
    joined to each folder value, normpath, is_default first) then folder_paths.get_full_path
    (the first folder whose join is a file, links followed)."""
    paths: dict[str, list[str]] = {}
    for conf in yaml.safe_load(yaml_text).values():
        conf = dict(conf)
        base = conf.pop("base_path", None)
        is_default = conf.pop("is_default", False)
        for key, value in conf.items():
            for line in str(value).split("\n"):
                if not line:
                    continue
                full = os.path.normpath(os.path.join(base, line) if base else line)
                if is_default:
                    paths.setdefault(key, []).insert(0, full)
                else:
                    paths.setdefault(key, []).append(full)
    for root in paths.get(folder, []):
        candidate = os.path.join(root, filename)
        if os.path.isfile(candidate):
            return candidate
    return None


#: folder_paths.py at 3c1b7a17, lines 25-67: the model folders ComfyUI registers.
COMFY_FOLDERS = {
    "checkpoints", "configs", "loras", "vae", "text_encoders", "diffusion_models",
    "clip_vision", "style_models", "embeddings", "diffusers", "vae_approx", "controlnet",
    "gligen", "upscale_models", "latent_upscale_models", "hypernetworks", "photomaker",
    "classifiers", "model_patches", "audio_encoders", "background_removal",
    "frame_interpolation", "geometry_estimation", "optical_flow", "detection",
}  # fmt: skip


@pytest.mark.parametrize("image", ["stills", "motion"])
def test_comfyui_resolves_every_graph_weight_inside_the_pinned_snapshot(tmp_path, image):
    files = tiny(image)
    snapshot = fake_cache(tmp_path / "hub", files)
    (tmp_path / "comfyui").mkdir(exist_ok=True)
    report = (
        prepare(tmp_path, files)
        if image == "stills"
        else weights.prepare(
            "motion",
            source="cache",
            cache_root=tmp_path / "hub",
            comfy_dir=tmp_path / "comfyui",
            entries=[entry for entry, _ in files],
            mirror={"repo": REPO, "revision": REV},
        )
    )
    assert report.ok, report.problems
    text = report.yaml_path.read_text(encoding="utf-8")
    section = yaml.safe_load(text)["amn_mirror"]
    assert set(section) - {"base_path", "is_default"} <= COMFY_FOLDERS
    operation = "image" if image == "stills" else "video"
    for _model, (op, name) in contract.WORKFLOWS.items():
        if op != operation:
            continue
        graph = json.loads((WORKER / "workflows" / f"{name}.json").read_text(encoding="utf-8"))
        for node in graph["graph"].values():
            for field, value in node["inputs"].items():
                folder = LOADER_FOLDERS.get((node["class_type"], field))
                if folder is None:
                    continue
                found = _comfy_full_path(text, folder.removeprefix("models/"), value)
                assert found is not None, (name, value)
                assert Path(found).resolve().is_relative_to(snapshot.resolve()), found


# ------------------------------------------------------ the reference route, both sides


def test_the_catalogue_and_the_worker_graphs_declare_the_same_references():
    for row in serverless_catalogue()["models"]:
        model = str(row["id"])
        operation, name = contract.WORKFLOWS[model]
        declared = amn_handler.load_workflow(name)
        spec = reference_spec(model)
        if spec is None:
            # The studio sends none: the graph must bind none either.
            assert declared.references == (), model
            continue
        assert list(declared.references) == list(spec["bindings"]), model
        assert len(spec["bindings"]) == int(spec["max"]), model
        assert declared.references_required == int(spec["min"]), model
        text_model = spec.get("text_model")
        if text_model:
            text_row = next(r for r in serverless_catalogue()["models"] if r["id"] == text_model)
            assert text_row["endpoint"] == row["endpoint"] and operation == "image"
            assert reference_spec(text_model) is None
            assert contract.WORKFLOWS[text_model][0] == operation


def test_a_picture_for_a_graph_that_binds_none_is_refused_before_its_claim(
    worker,  # noqa: F811 - the fixture imported from test_runpod_worker
):
    refs = _registered_refs(worker, 1)
    item = image_item(0, reference_images=refs)
    out = worker.run(batch([item, image_item(1)]))
    assert out["items"][0]["status"] == "FAILED"
    assert out["items"][0]["error"] == "REFERENCE_NOT_ACCEPTED"
    assert out["items"][1]["status"] == "COMPLETED"
    assert worker.bucket.downloads == []  # the picture was never even fetched
    assert claim_key(PREFIX, item["idempotency_key"]) not in worker.bucket.objects
    assert len(worker.comfy.graphs) == 1


def test_more_pictures_than_the_graph_binds_are_refused_not_silently_dropped(
    worker,  # noqa: F811 - the fixture imported from test_runpod_worker
):
    worker.comfy.make = ref_maker
    refs = _registered_refs(worker, 4)
    item = ref_item(0, refs)
    out = worker.run(batch([item]))
    assert out["items"][0]["status"] == "FAILED"
    assert out["items"][0]["error"] == "TOO_MANY_REFERENCES"
    assert worker.bucket.downloads == [] and worker.comfy.graphs == []
    assert claim_key(PREFIX, item["idempotency_key"]) not in worker.bucket.objects


def test_the_journal_names_the_bindings_the_worker_graph_really_has(engine, tmp_path):
    cloud = Cloud()
    made = RunPodImageAdapter(serverless(), engine, model=ROUTE, storage_root=tmp_path)
    made.core.transport = made.core.client.transport = cloud
    from app.providers.runpod.mock import png

    pictures = (png(variation=1), png(variation=2))
    run = made.submit_batch(
        [request("1", 0, model=ROUTE, references=pictures)],
        session=Session_(),
        on_submitted=lambda item: None,
    )
    assert run.items
    from app.providers.runpod.jobs import GenerationJob
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    with Session(engine) as s:
        row = s.scalars(select(GenerationJob)).one()
    graph = amn_handler.load_workflow(contract.WORKFLOWS[ROUTE][1])
    assert row.request["reference_bindings"] == list(graph.references[:2])
    (job,) = cloud.jobs.values()
    (sent,) = job["input"]["items"]
    assert len(sent["reference_images"]) == 2 and sent["workflow"] == graph.name


# ------------------------------------------------------------ the unbilled wait, the ttl


@pytest.mark.parametrize("operation", ["image", "video"])
def test_every_chunk_ttl_holds_the_whole_cache_wait_and_the_bill_does_not(operation):
    config = serverless()
    assert config.model_source == "cache"
    budget = batch_module.item_budget(config, operation)
    for items in range(1, contract.MAX_ITEMS + 1):
        policy = batch_module.chunk_policy(config, operation, items)
        execution = policy["executionTimeout"] // 1000
        assert execution <= config.execution_timeout_cap_seconds
        assert execution <= config.cold_start_seconds + items * budget
        assert policy["ttl"] // 1000 - execution == (
            config.queue_wait_seconds + config.model_cache_wait_seconds
        )
    # The GPU session outlives the longest ttl: the guard never ends a session whose job
    # RunPod may still start after the unbilled download.
    longest = batch_module.chunk_policy(config, operation, contract.MAX_ITEMS)["ttl"] // 1000
    assert config.session_max_seconds >= longest


def test_the_studio_waits_for_a_round_as_long_as_runpod_may_still_start_it(engine, tmp_path):
    cloud = Cloud()
    made = adapter(engine, tmp_path, cloud)
    before = time.monotonic()
    run = made.submit_batch([request("1", 0)], session=Session_(), on_submitted=lambda i: None)
    (job,) = cloud.jobs.values()
    ttl = job["policy"]["ttl"] / 1000
    assert ttl >= made.config.model_cache_wait_seconds + job["policy"]["executionTimeout"] / 1000
    assert run._deadline >= before + ttl  # never cancelled during the unbilled download
    assert not run.deadline_passed()


# --------------------------------------------------- a locked character, no reference input


def _route_table(*models: str):
    table = cost_plan.load_price_table()
    rows = [
        cost_plan.PriceRow(
            model, "image", "*", "estimate", "2026-10-09", "DOCUMENTED", credits_per_image=8
        )
        for model in models
        if not any(r.model_id == model for r in table.rows)
    ]
    return replace(
        table,
        rows=(*table.rows, *rows),
        overhead_credits_per_round={"image": 13.4},
        round_models=frozenset(models),
    )


def test_a_locked_character_on_the_runpod_text_model_is_refused_before_anything(engine, tmp_path):
    from app.media.stills_stage import StillsStageRefused, run_stills_stage, stills_plan
    from app.models import ApprovalRequest
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from test_serial_references import a_character, cast
    from test_stills_stage import NO_FACE, SpyJudge, a_film, faces_in

    storyboard_id = a_film(engine, tmp_path)
    character_id = a_character(engine, tmp_path, referenced=True, locked=True)
    cast(engine, storyboard_id, character_id, (1, 3))
    cloud = PictureCloud(lambda prompt: NO_FACE[0].read_bytes())
    made = RunPodImageAdapter(serverless(), engine, model="Qwen-Image-2512", storage_root=tmp_path)
    made.core.transport = made.core.client.transport = cloud
    assert made.ACCEPTS_REFERENCE_IMAGE is False and made.MAX_REFERENCES == 0
    table = _route_table("Qwen-Image-2512")
    plan = stills_plan(engine, storyboard_id, model_id=made.model, table=table)
    with pytest.raises(StillsStageRefused) as refused:
        run_stills_stage(
            engine,
            storyboard_id,
            str(uuid4()),
            plan_hash=plan["plan_hash"],
            image_adapter=made,
            registry=None,
            judge=SpyJudge(),
            storage_root=tmp_path / "media",
            table=table,
            face_counter=faces_in(),
            measure=("faces",),
        )
    assert refused.value.status == "NEEDS_REFERENCE"
    assert "înfățișarea blocată" in str(refused.value)
    assert cloud.calls == [] and cloud.jobs == {}
    with Session(engine) as s:
        assert s.scalars(select(ApprovalRequest)).all() == []  # his yes was never asked


def test_a_still_redo_of_a_locked_character_on_a_model_without_references_is_refused(
    engine, tmp_path
):
    from app.media.assembler import SceneRedoRefused, _redo_still
    from app.models import ApprovalRequest
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from test_serial_references import a_character, cast
    from test_stills_stage import SpyStills, a_film

    storyboard_id = a_film(engine, tmp_path)
    character_id = a_character(engine, tmp_path, referenced=True, locked=True)
    cast(engine, storyboard_id, character_id, (1,))
    images = SpyStills(balance=1_000)
    assert not getattr(images, "ACCEPTS_REFERENCE_IMAGE", False)
    with pytest.raises(SceneRedoRefused) as refused:
        _redo_still(
            engine,
            storyboard_id,
            str(uuid4()),
            {"scene_index": 1, "cap_credits": 54, "cap_usd": 1.0, "cost_usd": 0.5, "credits": 18},
            plan_hash="unused",
            image_adapter=images,
            registry=None,
            judge=None,
            face_counter=None,
            measure=None,
            environment="TEST",
            ffmpeg_path=None,
            storage_root=tmp_path / "media",
            integration_id=None,
            table=None,
            requester="video_editor",
            note=None,
            settings=None,
        )
    assert refused.value.status == "NEEDS_REFERENCE"
    assert images.asked == []
    with Session(engine) as s:
        assert s.scalars(select(ApprovalRequest)).all() == []


def test_the_reference_route_still_takes_a_locked_character(engine, tmp_path):
    made = RunPodImageAdapter(serverless(), engine, model=ROUTE, storage_root=tmp_path)
    assert made.ACCEPTS_REFERENCE_IMAGE is True and made.MAX_REFERENCES == 3
    assert isinstance(made.MAX_REFERENCES, int)
