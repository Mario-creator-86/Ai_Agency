"""Corrected scene intent must survive compilation; all evidence is frozen offline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from app.media.prompt_agent import ShotPrompt, compile_prompts, motion_prompt_for
from app.media.prompt_lint import BLOCK, LintScene, camera_moves, lint_film, utf16_units
from app.media.scene_rewrite import MOTION, STILL, rewritten_package

EVIDENCE = json.loads(
    (Path(__file__).parent / "fixtures/cyclotron_aa170155/corrected_intent.json").read_text(
        encoding="utf-8"
    )
)
BIBLE = EVIDENCE["bible"]
PACKAGES = EVIDENCE["packages"]


@pytest.mark.parametrize(
    ("scene", "required"),
    [
        ("4", ("gold medal", "dark forest green cloth", "green-shaded desk lamp")),
        ("5", ("pencil sketch", "grey graphite lines", "dark walnut library table")),
    ],
)
def test_corrected_still_retains_the_complete_subject_and_scene_light(scene, required):
    compiled = compile_prompts(PACKAGES[scene], BIBLE)
    still = compiled["still_prompt"].lower()
    for phrase in required:
        assert phrase in still, still
    assert "lamplight" in still or "lamp" in still
    assert "as it is today" not in still
    assert "diffuse daylight" not in still
    assert "any people" not in still
    assert "The frame holds only the place and the things named." in compiled["still_prompt"]


def test_corrected_motion_keeps_objects_and_shape_stability_not_only_the_opening_words():
    compiled = compile_prompts(PACKAGES["4"], BIBLE)
    prompt = compiled["motion_prompt"].lower()
    for phrase in ("gold medal", "dark forest green cloth", "edges stay sharp and unmoving"):
        assert phrase in prompt, prompt
    assert [move for move, _ in camera_moves(prompt)] == ["slow pull-back"]
    assert motion_prompt_for(compiled, "LTX-2.5")[0] == compiled["motion_prompt"]


def test_corrected_motion_keeps_the_later_action_and_the_stable_end_of_the_shot():
    compiled = compile_prompts(PACKAGES["5"], BIBLE)
    prompt = compiled["motion_prompt"].lower()
    assert "glowing trail of particles rises" in prompt, prompt
    assert "pencil lines staying visible" in prompt, prompt
    assert "napkin and table remain perfectly still" in prompt, prompt


def test_long_generic_subject_keeps_the_secondary_object_after_its_material_description():
    compiled = compile_prompts(
        {
            "subject": (
                "A compact polished metal instrument with a circular case and a clear glass "
                "cover over its central wheel, beside a wooden pointer resting on woven linen."
            ),
            "environment": "An indoor workbench at night",
            "lighting": "A single warm desk lamp",
            "camera": "Medium shot, 85mm lens",
            "motion": "The wheel rotates while the wooden pointer remains still.",
        },
        {"continuity_rules": ["No human faces appear"]},
    )
    assert "wooden pointer resting on woven linen" in compiled["still_prompt"].lower()


def test_object_colour_does_not_erase_its_motion_or_the_second_simultaneous_action():
    compiled = compile_prompts(
        {
            "subject": "A silver cylinder beside a brass disc",
            "camera_move": "static",
            "motion": "The silver cylinder opens while the inner brass disc rotates.",
        },
        {},
    )
    prompt = compiled["motion_prompt"].lower()
    assert "silver cylinder opens" in prompt
    assert "brass disc rotates" in prompt


@pytest.mark.parametrize("layer", [STILL, MOTION])
def test_director_correction_constraints_survive_a_full_old_avoid_list(layer):
    stored = {
        **PACKAGES["4"],
        "avoid": [f"old visual defect {index}" for index in range(10)],
        "still_prompt": "The approved instrument on a workbench.",
    }
    context = {
        "package": stored,
        "scene_index": 4,
        "scene": {"scene_index": 4, "seconds": 6.8, "characters": []},
        "bible": BIBLE,
        "allowed": "1930s 6.8 ten two",
        "previous_ending": "",
        "shot_type": "MEDIUM",
        "previous_moves": [],
    }
    corrected = rewritten_package(
        context,
        ShotPrompt.model_validate({"scene_index": 4, **PACKAGES["4"]}),
        layer,
        {"avoid": ["any person or figure", "duplicated device parts"]},
    )
    assert "any person or figure" in corrected["avoid"]
    assert "duplicated device parts" in corrected["avoid"]
    # Never said as "no ..." in a positive prompt: an image or video model reads the words,
    # not the negation (config/factual_look.json's note; the lint refuses negations on veo).
    # The exclusions reach the negative channel of a model that has one.
    for field in ("still_prompt", "motion_prompt"):
        assert "no duplicated device parts" not in corrected[field].lower(), corrected[field]
    veo = compile_prompts(corrected, BIBLE, {"model_id": "veo3.1"})
    assert "duplicated device parts" in (veo["negative_prompt"] or "")
    if layer == MOTION:
        assert corrected["still_prompt"] == stored["still_prompt"]


@pytest.mark.parametrize("scene", ["4", "5"])
def test_corrected_prompts_stay_inside_the_vendor_contract_and_existing_bible(scene):
    compiled = compile_prompts(PACKAGES[scene], BIBLE)
    for field in ("still_prompt", "motion_prompt"):
        assert utf16_units(compiled[field]) <= 1000
    findings = lint_film(
        [
            LintScene(
                scene=int(scene),
                still_prompt=compiled["still_prompt"],
                motion_prompt=compiled["motion_prompt"],
            )
        ],
        bible=BIBLE,
    )
    assert not [finding for finding in findings if finding.severity == BLOCK]
