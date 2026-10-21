"""Recorded partial Sarah framing and selection before purchase, with no cloud calls."""

import json
from pathlib import Path

from app.media import prompt_agent, stills_stage

FIXTURE = Path(__file__).parent / "fixtures" / "live_serial_scene4_2026-10-14.json"


def partial_package():
    package = json.loads(FIXTURE.read_text(encoding="utf-8"))["package"]
    package["in_frame"] = package["characters"][:1]
    package["continuity"] = "Nadia remains seated; Sarah is cropped at the edge."
    package["action"] = (
        "Nadia seated at her ledger desk; Sarah's right shoulder and upper arm only "
        "at the right frame edge, her face off camera."
    )
    return package


def test_partial_visible_person_keeps_wardrobe_without_asking_for_a_face():
    from app.media.series_look import load_series_look

    package = partial_package()
    text = prompt_agent.compose_serial_prompt(package, load_series_look())
    assert "crisp navy two-piece executive blazer" in text.lower()
    assert "white collared shirt" in text.lower()
    assert "sky-blue tie" in text.lower()
    assert "professional bob" not in text.lower()
    assert "Sarah's right shoulder and upper arm only" in text
    assert "face off camera" in text


def test_qc_picture_carries_partial_wardrobe_and_framing():
    text = stills_stage.serial_scene_picture(partial_package())
    assert "navy" in text.lower()
    assert "face off camera" in text


def test_existing_portrait_selects_discovered_edit_route_before_pricing(
    engine, tmp_path, monkeypatch
):
    from app.integrations.discovery import ProductionCommand, save_production
    from app.integrations.services import select_service
    from app.media.factory import image_provider, reference_image_adapter
    from test_runpod_pipeline import serverless_connection
    from test_serial_references import a_character, cast
    from test_stills_stage import a_film

    vault, integration, _result, _calls = serverless_connection(engine, monkeypatch)
    save_production(
        engine,
        integration,
        ProductionCommand(expected_version=0, model_id="LTX-2.5", image_model_id="Qwen-Image-2512"),
    )
    select_service(engine, "image", integration, 0)
    board = a_film(engine, tmp_path)
    character = a_character(engine, tmp_path, referenced=True, locked=False)
    cast(engine, board, character, (1,))
    original = image_provider(engine, vault)
    assert original.model == "Qwen-Image-2512"
    selected = reference_image_adapter(engine, board, original)
    assert selected.model == "Qwen-Image-Edit-2511"
    assert selected.ACCEPTS_REFERENCE_IMAGE
    assert selected.integration_id == integration
    assert original.model == "Qwen-Image-2512"
    assert reference_image_adapter(engine, board, original) is selected
    scene = stills_stage._read_scenes(engine, board)[1][0]
    references, with_character, _ = stills_stage._references(scene, None, selected, first=True)
    assert with_character and references == [scene.reference["bytes"]]


def test_without_a_portrait_the_default_route_stays_selected(engine, tmp_path, monkeypatch):
    from app.media.factory import image_provider, reference_image_adapter
    from test_runpod_pipeline import connect
    from test_stills_stage import a_film

    vault, _integration = connect(engine, tmp_path, monkeypatch)
    board = a_film(engine, tmp_path)
    original = image_provider(engine, vault)
    assert reference_image_adapter(engine, board, original) is original


def test_old_prompt_missing_partial_wardrobe_is_not_ready_for_animation():
    from app.media.series_look import load_series_look

    package = partial_package()
    package["still_prompt"] = "Nadia in her plum blouse; Sarah's shoulder at the edge."
    assert any(
        "Sarah" in issue and "lipsește" in issue
        for issue in prompt_agent.incomplete_plan_fields(package, layers=("still",))
    )
    package["still_prompt"] = prompt_agent.compose_serial_prompt(package, load_series_look())
    assert not any(
        "ținuta vizibilă" in issue
        for issue in prompt_agent.incomplete_plan_fields(package, layers=("still",))
    )


def test_partial_framing_and_unruled_pages_are_explicit_visual_checks():
    from app.media.series_look import load_series_look
    from app.media.stills_stage import _Scene, _still_plan

    package = partial_package()
    words = prompt_agent.compose_serial_prompt(package, load_series_look())
    words += " Every page is blank and unruled."
    scene = _Scene(
        index=4,
        kind="LIVE",
        words=words,
        identity={},
        look_block="",
        camera_move="static",
        source="model",
        picture=stills_stage.serial_scene_picture(package),
    )
    plan = _still_plan(scene, faces_forbidden=False, rules=())
    assert any("face" in i["finding"].lower() for i in plan.must_fix)
    assert any("unruled" in i["finding"].lower() for i in plan.must_fix)


def test_recomposed_partial_wardrobe_is_checked_against_the_new_candidate():
    from app.media.series_look import load_series_look

    package = partial_package()
    package["still_prompt"] = "Nadia; Sarah's shoulder at the right edge."
    new = prompt_agent.compose_serial_prompt(package, load_series_look())
    issues = prompt_agent.composition_issues(package, new, "", layers=("still",))
    assert not any("ținuta vizibilă" in issue for issue in issues)


def test_old_owner_report_is_informative_without_mutating_its_record():
    from app.agents.messages import message_view
    from app.agents.models import AgentMessage

    row = AgentMessage(
        id="notice",
        intent="STATUS",
        subject="Filmul așteaptă aprobarea preluării noi",
        body_json={"to": "Owner", "kind": "owner_director_qc", "outcome": "BOUGHT_WAITING"},
        status="OPEN",
        created_at="2026-10-14T20:20:35+00:00",
    )
    original = row.subject
    view = message_view(row, {})
    assert not view["requires_owner_response"]
    assert "așteaptă aprobarea" not in view["subject"]
    assert row.subject == original


def test_hidden_face_does_not_erase_visible_shoulders_wardrobe():
    from app.media.series_look import load_series_look

    package = partial_package()
    package["action"] = package["action"].replace("face off camera", "face not visible")
    text = prompt_agent.compose_serial_prompt(package, load_series_look())
    assert "sky-blue tie" in text.lower()
    assert "face not visible" in text
