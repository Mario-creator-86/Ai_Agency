"""Kael's example, response schema and saved vendor words must describe one contract."""

import json
import re
from copy import deepcopy
from types import SimpleNamespace

import pytest
from app.agents.identity import read_structured
from app.media import scene_rewrite
from app.media.final_prompts import EDITOR_FINAL
from app.media.scene_rewrite import MOTION, STILL, shot_schema
from test_legacy_final_migration import MOTION_TEXT, STILL_TEXT, context


@pytest.mark.parametrize("layer,migrating", [(MOTION, False), (MOTION, True), (STILL, False)])
def test_final_response_schema_requires_the_actual_vendor_fields(layer, migrating):
    schema = shot_schema(19, layer, editor_final=True, migrating=migrating)
    required = set(schema.model_json_schema()["required"])
    assert {"motion_prompt", "camera_move"} <= required
    assert ("still_prompt" in required) == (layer == STILL or migrating)
    assert "motion" not in schema.model_fields
    assert "subject" not in schema.model_fields


def test_final_response_does_not_normalize_the_paid_still_or_new_motion():
    schema = shot_schema(19, MOTION, editor_final=True, migrating=True)
    still = STILL_TEXT.replace("Three scientists", "Three  scientists")
    motion = MOTION_TEXT.replace("; ", ";\n")
    parsed, refusal = read_structured(
        json.dumps({"still_prompt": still, "motion_prompt": motion, "camera_move": "static"}),
        schema,
    )
    assert refusal is None
    assert parsed.still_prompt == still
    assert parsed.motion_prompt == motion


def test_final_response_never_converts_draft_motion_into_vendor_text():
    schema = shot_schema(19, MOTION, editor_final=True)
    parsed, refusal = read_structured(
        json.dumps({"motion": "A legacy planning note", "camera_move": "static"}), schema
    )
    assert parsed is None
    assert "motion_prompt" in refusal


@pytest.mark.parametrize("value", [{"text": MOTION_TEXT}, [MOTION_TEXT], None, "   "])
def test_final_response_requires_real_nonempty_text(value):
    schema = shot_schema(19, MOTION, editor_final=True)
    parsed, refusal = read_structured(
        json.dumps({"motion_prompt": value, "camera_move": "static"}), schema
    )
    assert parsed is None
    assert refusal


@pytest.mark.parametrize("layer,migrating", [(MOTION, False), (MOTION, True), (STILL, False)])
def test_rewrite_example_and_schema_ask_for_the_same_final_fields(
    engine, monkeypatch, layer, migrating
):
    ctx = {
        **deepcopy(context()),
        "storyboard_id": "board",
        "title": "Supernova",
        "story": {},
        "failures": [],
        "briefs": [],
    }
    if not migrating:
        ctx["package"]["prompt_format"] = EDITOR_FINAL
    monkeypatch.setattr(scene_rewrite, "agent_for_role", lambda *a: SimpleNamespace(id="kael"))
    monkeypatch.setattr("app.media.prompt_agent.prompt_lessons", lambda *a, **kw: [])
    captured = []

    def capture(*args, **kwargs):
        captured.append((args[4], args[7]))
        return None, {"status": "FAILED", "error_detail": "test ends before model call"}, None

    monkeypatch.setattr("app.agents.structured.structured_run", capture)
    scene_rewrite.rewrite_scene(engine, object(), ctx, {"layer": layer}, "test")
    prompt, schema = captured[0]
    instructions = prompt.split("<untrusted_source_evidence", 1)[0]
    example = re.search(r"Return only JSON with this shot: (\{[^\n]+\})", instructions)
    assert example is not None
    fields = json.loads(example.group(1))
    expected = {"scene_index", "camera_move", "motion_prompt"}
    if layer == STILL or migrating:
        expected.add("still_prompt")
    assert set(fields) == expected
    assert set(schema.model_json_schema()["required"]) <= set(fields)
    assert "fixed words each camera move" not in instructions
    assert "everything that moves goes to motion," not in instructions


@pytest.mark.parametrize("verdict", ["TREATS", "MISSES"])
def test_model_following_the_example_reaches_review_before_any_save(
    engine, tmp_path, monkeypatch, verdict
):
    from app.media.models import StoryboardScene
    from sqlalchemy import select
    from sqlalchemy.orm import Session
    from test_film_costing import a_film

    board = a_film(engine, tmp_path, scenes=1)
    ctx = {
        **deepcopy(context()),
        "storyboard_id": board,
        "scene_index": 1,
        "title": "Supernova",
        "story": {},
        "failures": [],
        "briefs": [],
    }
    old = deepcopy(ctx["package"])
    with Session(engine) as session, session.begin():
        row = session.scalar(select(StoryboardScene).where(StoryboardScene.storyboard_id == board))
        row.prompt_json = old
        row.visual_prompt = ctx["visual_prompt"]
    monkeypatch.setattr(scene_rewrite, "agent_for_role", lambda *a: SimpleNamespace(id="kael"))
    monkeypatch.setattr("app.media.prompt_agent.prompt_lessons", lambda *a, **kw: [])
    monkeypatch.setattr(scene_rewrite, "learn_from_review", lambda *a: (False, "test"))
    monkeypatch.setattr("app.agents.structured._model_name", lambda *a: None)
    calls = []

    def model(*args, **kwargs):
        instructions = args[4].split("<untrusted_source_evidence", 1)[0]
        match = re.search(r"Return only JSON with this shot: (\{[^\n]+\})", instructions)
        example = json.loads(match.group(1))
        values = {
            "scene_index": 1,
            "camera_move": "static",
            "motion_prompt": MOTION_TEXT,
            "still_prompt": ctx["visual_prompt"],
        }
        calls.append(example)
        return {
            "id": "scripted-run",
            "status": "SUCCEEDED",
            "output_text": json.dumps({k: values.get(k, "Legacy note") for k in example}),
        }

    monkeypatch.setattr("app.agents.structured.run_agent_task", model)
    reviewed = []

    def sarah(*args, **kwargs):
        reviewed.append(args[5]["motion_prompt"])
        return {"verdict": verdict, "findings": [], "reason_ro": "test", "lesson": ""}

    monkeypatch.setattr(scene_rewrite, "_reviewed", sarah)
    result = scene_rewrite.rewrite_scene(engine, object(), ctx, {"layer": MOTION}, "test")
    assert reviewed
    assert reviewed[0] == MOTION_TEXT
    assert result["rewritten"] == (verdict == "TREATS")
    with Session(engine) as session:
        row = session.scalar(select(StoryboardScene).where(StoryboardScene.storyboard_id == board))
        assert row.visual_prompt == ctx["visual_prompt"]
        if verdict == "TREATS":
            assert len(calls) == 1
            assert row.prompt_json["motion_prompt"] == MOTION_TEXT
            assert row.prompt_json["prompt_format"] == EDITOR_FINAL
        else:
            assert row.prompt_json == old
