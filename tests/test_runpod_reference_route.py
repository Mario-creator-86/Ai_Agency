"""The reference route on RunPod (the Owner's card, 2026-10-09): Qwen-Image-Edit-2511 with the
Lightning 4-step LoRA, Apache-2.0, 1-3 reference pictures. A RunPod image adapter takes a
reference only when the selected model of config/runpod_models.json declares a reference
binding; the stills step then sends the character's picture first and the film's Figure 1
second (presigned bucket URLs), so a locked character is drawn from its picture instead of
being refused NEEDS_REFERENCE. An item with no picture goes to the route's text model on the
same endpoint, and the journal says which model and which pictures each item really got.
Every RunPod and bucket call is faked."""

from __future__ import annotations

import json
from dataclasses import replace
from uuid import uuid4

import pytest
from app.media import cost_plan
from app.media.factory import accepts_reference_image
from app.providers.runpod import batch as batch_module
from app.providers.runpod.adapters import RunPodImageAdapter
from app.providers.runpod.jobs import GenerationJob
from app.providers.runpod.mock import png
from app.providers.runpod.models import model_entry, reference_spec
from runpod_worker import contract
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_runpod_batch import (  # noqa: F401 - the fixture is used by name
    Cloud,
    PictureCloud,
    Session_,
    fake_session,
    request,
    serverless,
)

ROUTE = "Qwen-Image-Edit-2511"
WORKFLOW = "qwen_image_edit_2511_ref_seedvr2"


@pytest.fixture(autouse=True)
def the_worker_knows_the_route(monkeypatch):
    """The worker's contract names the route (its own change, made beside this one)."""
    monkeypatch.setitem(contract.WORKFLOWS, ROUTE, ("image", WORKFLOW))


def route_adapter(engine, tmp_path, cloud, model=ROUTE, **values):
    made = RunPodImageAdapter(serverless(**values), engine, model=model, storage_root=tmp_path)
    made.core.transport = made.core.client.transport = cloud
    return made


# ------------------------------------------------------------------------- the catalogue


def test_the_catalogue_declares_the_route_with_its_licence_and_bindings():
    entry = model_entry(ROUTE)
    assert entry is not None
    assert entry["licence"] == "Apache-2.0" and entry["endpoint"] == "stills"
    assert entry["workflow"] == WORKFLOW and entry["output"] == [1530, 2720]
    assert "text_to_image" in entry["tasks"] and "reference_to_image" in entry["tasks"]
    spec = reference_spec(ROUTE)
    assert spec is not None
    assert spec["bindings"] == ["reference_image", "reference_image_2", "reference_image_3"]
    assert spec["max"] == 3 and spec["min"] == 1 and spec["text_model"] == "Qwen-Image-2512"
    assert "NEDOVEDIT" in entry["gpu_seconds_source"]
    assert reference_spec("Qwen-Image-2512") is None
    assert reference_spec("no-such-model") is None


def test_only_a_model_with_a_reference_binding_accepts_a_reference(engine, tmp_path):
    route = route_adapter(engine, tmp_path, Cloud())
    plain = route_adapter(engine, tmp_path, Cloud(), model="Qwen-Image-2512")
    auto = route_adapter(engine, tmp_path, Cloud(), model="AUTO")
    assert accepts_reference_image(route) and route.MAX_REFERENCES == 3
    assert not accepts_reference_image(plain) and plain.MAX_REFERENCES == 0
    assert not accepts_reference_image(auto)
    # What a picture really did is proven by the paid test, never by this declaration.
    assert route.REFERENCE_IMAGE_VERIFIED is False


# --------------------------------------------------------------------------- the batch


def test_pictures_travel_as_presigned_urls_and_the_journal_names_their_bindings(engine, tmp_path):
    cloud = Cloud()
    made = route_adapter(engine, tmp_path, cloud)
    portrait, figure = png(variation=3), png(variation=4)
    made.submit_batch(
        [request("2", 0, model=ROUTE, references=(portrait, figure))],
        session=Session_(),
        on_submitted=lambda item: None,
    )
    (item,) = cloud.jobs["job-1"]["input"]["items"]
    assert item["model"] == ROUTE and item["workflow"] == WORKFLOW
    assert [
        ref["url"].startswith("https://account.r2.example/") for ref in item["reference_images"]
    ] == [
        True,
        True,
    ]
    assert "base64" not in json.dumps(cloud.jobs["job-1"])
    with Session(engine) as s:
        row = s.scalars(select(GenerationJob)).one()
        assert row.model == ROUTE
        assert row.request["reference_bindings"] == ["reference_image", "reference_image_2"]
        assert len(row.request["reference_images"]) == 2


def test_an_item_without_a_picture_goes_to_the_route_text_model(engine, tmp_path):
    cloud = Cloud()
    made = route_adapter(engine, tmp_path, cloud)
    run = made.submit_batch(
        [request("1", 0, model=ROUTE)], session=Session_(), on_submitted=lambda item: None
    )
    (item,) = cloud.jobs["job-1"]["input"]["items"]
    assert item["model"] == "Qwen-Image-2512" and item["reference_images"] == []
    assert run.items[0].request.model == "Qwen-Image-2512"
    with Session(engine) as s:
        row = s.scalars(select(GenerationJob)).one()
        assert row.model == "Qwen-Image-2512" and "reference_bindings" not in row.request


def test_a_picture_for_a_model_that_cannot_take_one_is_refused_unsent(engine, tmp_path):
    cloud = Cloud()
    made = route_adapter(engine, tmp_path, cloud, model="Qwen-Image-2512")
    with pytest.raises(batch_module.BatchRefused) as refused:
        made.submit_batch(
            [request("1", 0, references=(png(),))],
            session=Session_(),
            on_submitted=lambda item: None,
        )
    assert refused.value.code == "REFERENCE_NOT_ACCEPTED" and refused.value.unsent
    assert not cloud.calls


def test_more_pictures_than_the_model_takes_are_refused_unsent(engine, tmp_path):
    cloud = Cloud()
    made = route_adapter(engine, tmp_path, cloud)
    pictures = tuple(png(variation=n) for n in range(4))
    with pytest.raises(batch_module.BatchRefused) as refused:
        made.submit_batch(
            [request("1", 0, model=ROUTE, references=pictures)],
            session=Session_(),
            on_submitted=lambda item: None,
        )
    assert refused.value.code == "TOO_MANY_REFERENCES" and not cloud.calls


# ----------------------------------------------------------------------- the stills step


def route_table():
    table = cost_plan.load_price_table()
    return replace(
        table,
        rows=(
            *table.rows,
            cost_plan.PriceRow(
                ROUTE, "image", "*", "estimate", "2026-10-09", "DOCUMENTED", credits_per_image=8
            ),
        ),
        overhead_credits_per_round={"image": 13.4},
        round_models=frozenset({ROUTE}),
    )


def test_a_locked_character_is_drawn_from_its_picture_on_the_route(
    engine,
    tmp_path,
    fake_session,  # noqa: F811 - the fixture imported from test_runpod_batch
):
    from app.media.stills_stage import StillsStageRefused, run_stills_stage, stills_plan
    from test_approvals import answer
    from test_serial_references import PORTRAIT, a_character, cast
    from test_stills_stage import NO_FACE, SpyJudge, a_film, faces_in

    storyboard_id = a_film(engine, tmp_path)
    character_id = a_character(engine, tmp_path, referenced=True, locked=True)
    cast(engine, storyboard_id, character_id, (1, 3))
    cloud = PictureCloud(lambda prompt: NO_FACE[0].read_bytes())
    made = route_adapter(engine, tmp_path, cloud)
    table = route_table()

    def go():
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

    with pytest.raises(StillsStageRefused) as asked:
        go()
    assert asked.value.status == "NEEDS_APPROVAL"  # not NEEDS_REFERENCE any more
    answer(engine, asked.value.approval_id, "APPROVED", note="Da, imaginile.")
    result = go()

    import hashlib

    portrait = hashlib.sha256(PORTRAIT).hexdigest()
    items = {
        (int(it["scene_id"]), it["model"], len(it["reference_images"])): it
        for job in sorted(cloud.jobs)
        for it in cloud.jobs[job]["input"]["items"]
    }
    scene_one = [it for key, it in items.items() if key[0] == 1]
    assert scene_one and all(it["model"] == ROUTE for it in scene_one)
    assert all(it["reference_images"][0]["sha256"] == portrait for it in scene_one)
    scene_three = [it for key, it in items.items() if key[0] == 3]
    assert all(len(it["reference_images"]) == 2 for it in scene_three)
    assert all(it["reference_images"][0]["sha256"] == portrait for it in scene_three)
    by_scene = {entry["scene_index"]: entry for entry in result["scenes"]}
    assert by_scene[1]["references_sent"] == ["character"]
    assert by_scene[2]["references_sent"] == ["figure_one"]
    assert by_scene[3]["references_sent"] == ["character", "figure_one"]
    assert result["reference_unverified"] is True
