"""Dark Energy scene repair: offline, no DB mutation or vendor calls."""

from scripts.repair_dark_energy_prompts import (
    _fingerprint,
    _repair19,
    _repair20,
)
from app.media.prompt_lint import BLOCK, lint_motion_prompt, lint_still_prompt

BIBLE = {
    "face_policy": "ALLOW",
    "style": "Documentary photograph",
    "world": "Deep space for cosmic shots; formal stage for medal ceremony",
    "lighting": "Natural documentary light",
}
LOOK = "Documentary photograph, natural colour, 35mm lens, fine grain."
OLD_MEDALS = {
    "scene_kind": "LIVE",
    "subject": "Three people seen from behind, their backs to the camera",
    "action": "Pale gold medals visible at their chests",
    "environment": "A ceremony hall with dark audience",
    "camera": "Medium shot, 85mm lens",
    "camera_move": "crane up",
    "lighting": "Warm stage spotlights",
    "composition": "Vertical frame",
    "motion": "The medals catch the warm light",
    "ending_frame": "Three figures from behind",
    "writer_visual": "Three people seen from behind receiving medals.",
    "still_prompt": (
        "Three people seen from behind receiving medals at their chests, "
        "their backs to the camera."
    ),
    "look_block": LOOK,
    "source": "model",
}
COSMIC_STILL = (
    "Documentary photograph. A cosmic web of galaxy filaments in void black "
    "deep space, pure vacuum, the frame one continuous dark space."
)
OLD_COSMOS = {
    "scene_kind": "LIVE",
    "subject": "A vast cosmic web of many clustered galaxies",
    "action": "The web glows faintly",
    "environment": "Void black deep space, pure vacuum",
    "camera": "Wide shot, 24mm lens",
    "camera_move": "aerial drift forward",
    "lighting": "Cool cyan light",
    "composition": "Vertical 9:16 frame, upper two thirds",
    "motion": "The galaxy filaments ripple gently",
    "still_prompt": COSMIC_STILL,
    "motion_prompt": (
        "Steady aerial drift forward, the ground sliding beneath and "
        "the horizon opening ahead."
    ),
    "look_block": LOOK,
    "source": "model",
}


def test_medal_repair_removes_back_only_rule_without_banning_faces() -> None:
    new, visual = _repair19(OLD_MEDALS, BIBLE, "MEDIUM")
    assert new["still_prompt"] == visual
    assert "front" in new["subject"].lower()
    assert "from behind" not in visual.lower()
    assert new["camera_move"] == "crane up"
    assert not [
        issue
        for issue in lint_still_prompt(visual, scene=19, bible=BIBLE)
        if issue.severity == BLOCK
    ]
    # The old input must remain unchanged.
    assert "from behind" in OLD_MEDALS["still_prompt"]


def test_cosmic_repair_preserves_paid_still_and_rewrites_motion_only() -> None:
    original = _fingerprint(OLD_COSMOS, COSMIC_STILL)
    new, visual = _repair20(OLD_COSMOS, COSMIC_STILL, BIBLE, "WIDE")
    assert visual == COSMIC_STILL
    assert new["still_prompt"] == COSMIC_STILL
    assert new["subject"] == OLD_COSMOS["subject"]
    assert new.get("writer_visual") == OLD_COSMOS.get("writer_visual")
    assert new["camera_move"] == "dolly in"
    assert "ground sliding beneath" not in new["motion_prompt"].lower()
    assert "horizon opening ahead" not in new["motion_prompt"].lower()
    assert not [
        issue
        for issue in lint_motion_prompt(
            new["motion_prompt"], scene=20, still_prompt=COSMIC_STILL
        )
        if issue.severity == BLOCK
    ]
    assert _fingerprint(OLD_COSMOS, COSMIC_STILL) == original


def test_fingerprint_detects_prompt_change_without_touching_input() -> None:
    before = {"still_prompt": "old photo", "motion_prompt": "old camera"}
    after = {**before, "motion_prompt": "corrected camera"}
    assert _fingerprint(before, "same still") != _fingerprint(after, "same still")
