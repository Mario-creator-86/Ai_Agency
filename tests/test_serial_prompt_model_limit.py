"""Serial stills keep required content through the actual GPU request contract."""

from __future__ import annotations

import json

import pytest
from app.media import prompt_agent as words
from app.media import prompt_lint as lint
from app.media import scene_rewrite as repair
from app.media.series_look import load_series_look
from app.providers.runpod.models import ImageRequest
from pydantic import ValidationError
from runpod_worker.amn_handler import bind, load_workflow
from runpod_worker.contract import MAX_PROMPT


def scene_package() -> dict:
    return {
        "shot_size": "two_shot",
        "location": "Executive Penthouse (Director / CEO), floor 4",
        "in_frame": [
            {
                "name": "Marcus Scriptwriter",
                "face_hair": "Tousled wavy dark hair; creative focused gaze; slight stubble",
                "outfit": "Comfortable royal purple fleece hoodie over grey crew tee",
            },
            {
                "name": "Sarah Executive",
                "face_hair": "Brunette professional bob with warm highlights; brown eyes",
                "outfit": "Crisp navy two-piece executive blazer, white shirt, sky-blue tie",
            },
        ],
        "action": "Marcus leans in the doorway, hoodie zipped, counting on his fingers "
        "as he speaks, defensive; Sarah sits measured at her desk, answering him, "
        "her posture composed",
    }


def test_shipped_serial_limit_is_the_worker_allowance():
    assert load_series_look()["max_prompt_chars"] == MAX_PROMPT


def test_a_route_limit_above_two_thousand_is_not_clamped(tmp_path):
    path = tmp_path / "look.json"
    path.write_text(json.dumps({"max_prompt_chars": MAX_PROMPT}), encoding="utf-8")
    assert load_series_look(path)["max_prompt_chars"] == MAX_PROMPT


def test_both_people_and_their_whole_first_moments_survive_composition():
    package = scene_package()
    prompt = words.compose_serial_prompt(package, load_series_look())
    assert len(prompt) > 980
    assert words._still_moment(package["action"]) in prompt
    assert "sky-blue tie" in prompt
    assert not words.composition_issues(package, prompt, "", layers=("still",))


def test_an_overlong_required_moment_is_held_instead_of_silently_cut():
    package = scene_package()
    package["action"] = "Sarah holds " + "a distinct brass object " * 1000 + "beside Marcus"
    prompt = words.compose_serial_prompt(package, load_series_look())
    assert words._still_moment(package["action"]) in prompt
    findings = lint.lint_scene(
        lint.LintScene(1, still_prompt=prompt, contract={"still_model_id": "Qwen-Image-2512"})
    )
    assert any(f.code == "OVER_CAP" and f.severity == lint.BLOCK for f in findings)


def test_a_long_background_condition_is_not_silently_discarded():
    package = scene_package()
    package["background"] = "Sarah's shoulder stays visible beside " + "a wooden prop " * 1600
    prompt = words.compose_serial_prompt(package, load_series_look())
    assert (
        "Behind them, " + package["background"][:1].lower() + package["background"][1:].strip()
    ) in prompt
    findings = lint.lint_still_prompt(
        prompt, scene=2, contract={"still_model_id": "Qwen-Image-2512"}
    )
    assert any(f.code == "OVER_CAP" for f in findings)


@pytest.mark.parametrize("model", ["Qwen-Image-2512", "Qwen-Image-Edit-2511"])
def test_qwen_still_validation_uses_the_worker_limit(model):
    prompt = words.compose_serial_prompt(scene_package(), load_series_look())
    assert lint.prompt_cap({"still_model_id": model}, "still") == MAX_PROMPT
    assert not any(
        f.code == "OVER_CAP"
        for f in lint.lint_still_prompt(prompt, scene=2, contract={"still_model_id": model})
    )


def test_an_explicit_other_provider_limit_is_preserved():
    assert lint.prompt_cap({"still_model_id": "seedream5_pro"}, "still") == 1000
    assert lint.prompt_cap({"still_model_id": "Qwen-Image-2512", "prompt_max": 800}, "still") == 800


def test_the_serial_rewrite_is_not_refused_by_the_old_runway_cap():
    package = scene_package()
    prompt = words.compose_serial_prompt(package, load_series_look())
    context = {
        "serial": True,
        "look": load_series_look(),
        "scene_index": 2,
        "bible": {},
        "package": {**package, "still_prompt": "A room.", "motion_prompt": ""},
        "visual_prompt": "A room.",
    }
    blocks = repair._lint_blocks(context, {**package, "motion_prompt": ""}, prompt)
    assert not any("limita de 1000" in block for block in blocks)


@pytest.mark.parametrize("name", ["qwen_image_2512_seedvr2", "qwen_image_edit_2511_ref_seedvr2"])
def test_full_prompt_reaches_both_qwen_workflows(name):
    prompt = words.compose_serial_prompt(scene_package(), load_series_look())
    request = ImageRequest(project_id="serial", scene_id="2", prompt=prompt)
    workflow = load_workflow(name)
    graph = bind(workflow, {"prompt": request.prompt})
    for node, _, field in workflow.bindings["prompt"]:
        assert graph[node]["inputs"][field] == prompt
        assert "Sarah sits measured at her desk" in graph[node]["inputs"][field]


def test_the_request_accepts_the_exact_worker_boundary_and_refuses_overflow():
    request = ImageRequest(project_id="serial", scene_id="2", prompt="x" * MAX_PROMPT)
    assert len(request.prompt) == MAX_PROMPT
    with pytest.raises(ValidationError):
        ImageRequest(project_id="serial", scene_id="2", prompt="x" * (MAX_PROMPT + 1))


def test_the_worker_character_limit_does_not_count_an_emoji_twice():
    text = "🌙" * (MAX_PROMPT // 2 + 1)
    assert len(ImageRequest(project_id="serial", scene_id="2", prompt=text).prompt) < MAX_PROMPT
    findings = lint.lint_still_prompt(text, scene=2, contract={"still_model_id": "Qwen-Image-2512"})
    assert not any(f.code == "OVER_CAP" for f in findings)


@pytest.mark.parametrize("model", ["Qwen-Image-2512", "Qwen-Image-Edit-2511"])
def test_the_actual_stills_stage_does_not_restore_the_old_cap(engine, tmp_path, model):
    from dataclasses import replace

    from app.media.cost_plan import STILLS_RESOLUTION, load_price_table
    from app.media.models import StoryboardScene
    from app.media.stills_stage import StillsStageRefused, stills_plan
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from test_stills_stage import SpyJudge, SpyStills, a_film, run

    board = a_film(engine, tmp_path)
    with Session(engine) as session, session.begin():
        scene = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == board, StoryboardScene.scene_index == 2
            )
        )
        prompt = scene.visual_prompt + " The wooden surface has fine grain." * 60
        assert len(prompt) > 2000
        scene.visual_prompt = prompt
        scene.prompt_json = {**scene.prompt_json, "still_prompt": prompt}
    adapter = SpyStills()
    adapter.model = model
    prices = load_price_table()
    image_row = replace(prices.row(SpyStills.model, STILLS_RESOLUTION), model_id=model)
    prices = replace(prices, rows=(*prices.rows, image_row), stills_model=model)
    plan = stills_plan(engine, board, model_id=model, table=prices)
    with pytest.raises(StillsStageRefused) as refused:
        run(engine, board, tmp_path, adapter, SpyJudge(), plan_hash=plan["plan_hash"], table=prices)
    assert refused.value.status == "NEEDS_APPROVAL", refused.value.reason_ro
    assert adapter.asked == [], "The test stops at approval; no vendor generation is called."
