"""Regression tests for Sarah/Kael loops caused by composer-owned text.

All checks are in memory. Existing SQLite takes and bought image identities stay untouched.
"""

from app.media.prompt_agent import (
    CLOSE_PEOPLE_SENTENCE,
    PEOPLE_SENTENCE,
    _frame_placement,
    compile_prompts,
    shot_frame,
)


def test_ratio_in_camera_does_not_leak_as_broken_16_frame_fragment() -> None:
    cases = (
        "Wide establishing shot, 24mm lens: 9:16 frame: one candle on a table",
        "Wide establishing shot, 24mm lens: 16 frame: one candle on a table",
        "Wide establishing shot, 24mm lens, 9:16 frame",
        "Wide establishing shot, 9:16 frame",
    )
    for camera in cases:
        size, frame = shot_frame(camera)
        assert size == "wide"
        assert "16 frame" not in frame, (camera, frame)
        assert "9:16" not in frame, (camera, frame)
        if "24mm" in camera:
            assert "24mm lens" in frame
    assert "one candle on a table" in shot_frame(cases[0])[1].lower()
    assert "one candle on a table" in shot_frame(cases[1])[1].lower()


def test_valid_location_after_colon_is_preserved() -> None:
    camera = (
        "Medium shot, 85mm lens: the medal recipients centred in the frame, "
        "three quarters facing the camera"
    )
    size, frame = shot_frame(camera)
    assert size == "medium"
    assert "85mm lens" in frame
    assert "medal recipients centred in the frame" in frame.lower()
    assert _frame_placement("Medium shot, 85mm lens") == ""


def test_old_back_facing_rule_does_not_return_in_new_allow_bible() -> None:
    package = {
        "scene_kind": "LIVE",
        "shot_type": "MEDIUM",
        "subject": (
            "A physical timeline of the universe, one thick bar of brushed metal. "
            + CLOSE_PEOPLE_SENTENCE
        ),
        "action": "One glowing segment of the timeline.",
        "environment": "Void black deep space.",
        "camera": "Medium shot, 85mm lens",
        "lighting": "Pale blue glow from the timeline.",
    }
    compiled = compile_prompts(package, {"face_policy": "ALLOW"})
    still = compiled["still_prompt"]
    assert "timeline" in still.lower()
    assert CLOSE_PEOPLE_SENTENCE not in still
    assert PEOPLE_SENTENCE not in still
    assert "seen only from behind" not in still.lower()
    assert "the person is seen" not in still.lower()


def test_no_people_clause_is_not_forced_into_a_face_allowed_scene() -> None:
    package = {
        "scene_kind": "LIVE",
        "shot_type": "WIDE",
        "subject": "A single bright candle flame on a wooden table.",
        "action": "The flame holds a teardrop shape.",
        "environment": "A dark laboratory room.",
        "camera": "Wide establishing shot, 24mm lens: 9:16 frame: one candle on a table",
        "lighting": "The candle flame is the room's only light source.",
    }
    still = compile_prompts(package, {"face_policy": "ALLOW"})["still_prompt"]
    assert "16 frame:" not in still
    assert "24mm lens" in still
    assert "only light source" in still
    assert CLOSE_PEOPLE_SENTENCE not in still
    assert PEOPLE_SENTENCE not in still


def test_long_candle_scene_keeps_sole_light_source_even_when_subject_is_shortened() -> None:
    package = {
        "scene_kind": "LIVE",
        "shot_type": "WIDE",
        "subject": (
            "A single candle flame, a teardrop of burning gas, amber with a hard bright "
            "rim, small and burning above the wax, seated in the lower third of the frame, "
            "its edges crisp and defined, the base blue, the rest of the dark room black."
        ),
        "action": "It burns gently above pale wax, alone in the dark room.",
        "environment": (
            "A dark room at night, the candle is a physical column of wax with a lit "
            "wick standing on a flat surface, absolute darkness fills the room at "
            "every height, a still unmoving interior."
        ),
        "camera": (
            "Wide establishing shot, 24mm lens, vertical 9:16 frame: "
            "The whole frame is one dark empty room with the small flame "
            "and its surface near the lower third."
        ),
        "lighting": (
            "The flame is the only light source in the frame, a warm pool of "
            "amber glow around the wick, all shadows remaining dark, no second light."
        ),
    }
    still = compile_prompts(package, {"face_policy": "ALLOW"})["still_prompt"]
    assert "16 frame:" not in still
    assert "flame is the only light source" in still.lower(), still
    assert "dark room" in still.lower(), still
    # Legacy compiler deletes tempo words like "gently"; this test checks the
    # factual candle action, while Kael-owned final prompts preserve exact prose.
    assert "burns above pale wax" in still.lower(), still
