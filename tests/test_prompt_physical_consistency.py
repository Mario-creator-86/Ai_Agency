"""Physical prompt contradictions checked before paid image/video generation.

The checks are narrow: faces and back views are allowed; only contradictory
object visibility and an impossible terrestrial move in vacuum block purchases.
No provider, GPU, image QC or database is used here.
"""

from app.media.prompt_lint import (
    BLOCK,
    WARN,
    LintScene,
    lint_film,
    lint_motion_prompt,
    lint_still_prompt,
)

MEDALS_BACK = (
    "Medium shot. Three people seen from behind on a stage, receiving medals, "
    "their backs to the camera, the pale gold medals catching the light at their "
    "chests. The people stand in a ceremony hall under warm lights."
)
MEDALS_FRONT = (
    "Medium shot. Three scientists facing the camera in a ceremony hall, "
    "gold medals worn visibly on the front of their jackets at their chests."
)
COSMIC_STILL = (
    "Wide shot. A vast cosmic web of clustered galaxies, filaments and bright nodes "
    "suspended in void black deep space, pure vacuum, no ground or planet in frame."
)
# For a real planetary surface, the horizon is valid and must not be lint-blocked.
PLANET_STILL = (
    "Wide shot. Earth seen from an orbiting spacecraft, the planet's curved surface "
    "and bright horizon below, and distant deep space beyond the atmosphere."
)
GROUND_MOTION = (
    "Steady aerial drift forward over the scene, the ground sliding beneath, "
    "the horizon opening ahead. Continuous, seamless shot. "
    "No subtitles, no on-screen text."
)
COSMIC_MOTION = (
    "Steady aerial drift forward among the galaxy filaments, distant galaxy "
    "clusters moving slowly across the camera's field of view. "
    "Continuous, seamless shot. No subtitles, no on-screen text."
)


def _codes(findings):
    return {item.code: item.severity for item in findings}


def test_back_view_and_visible_chest_medals_block_expensive_still() -> None:
    codes = _codes(lint_still_prompt(MEDALS_BACK, scene=19, bible={"face_policy": "ALLOW"}))
    assert codes["PHYSICAL_MEDAL_ORIENTATION"] == BLOCK
    assert "FORBIDDEN_FACES" not in codes


def test_camera_facing_scientists_and_chest_medals_are_allowed() -> None:
    codes = _codes(lint_still_prompt(MEDALS_FRONT, scene=19, bible={"face_policy": "ALLOW"}))
    assert "PHYSICAL_MEDAL_ORIENTATION" not in codes
    assert "FORBIDDEN_FACES" not in codes


def test_rear_view_with_no_front_medal_claim_is_allowed() -> None:
    still = (
        "Three scientists seen from behind at a ceremony, a medal case on the "
        "table in front of them. Warm stage lights above."
    )
    codes = _codes(lint_still_prompt(still, scene=19, bible={"face_policy": "ALLOW"}))
    assert "PHYSICAL_MEDAL_ORIENTATION" not in codes


def test_reflection_allows_front_medals_in_a_back_view() -> None:
    still = MEDALS_BACK + " A large mirror reflects the medal recipients' fronts."
    codes = _codes(lint_still_prompt(still, scene=19, bible={"face_policy": "ALLOW"}))
    assert "PHYSICAL_MEDAL_ORIENTATION" not in codes


def test_terrestrial_ground_move_blocks_cosmic_vacuum_motion() -> None:
    codes = _codes(
        lint_motion_prompt(GROUND_MOTION, scene=20, still_prompt=COSMIC_STILL)
    )
    assert codes["PHYSICAL_COSMIC_GROUND"] == BLOCK


def test_cosmic_camera_drift_without_ground_is_allowed() -> None:
    codes = _codes(
        lint_motion_prompt(COSMIC_MOTION, scene=20, still_prompt=COSMIC_STILL)
    )
    assert "PHYSICAL_COSMIC_GROUND" not in codes


def test_real_planetary_horizon_is_not_a_false_positive() -> None:
    codes = _codes(
        lint_motion_prompt(GROUND_MOTION, scene=20, still_prompt=PLANET_STILL)
    )
    assert "PHYSICAL_COSMIC_GROUND" not in codes


def test_temporal_brightening_is_warning_not_a_paid_block() -> None:
    still = (
        "The distant galaxy filaments float against void black, their cool light "
        "brightens and dims in slow waves across the web."
    )
    codes = _codes(lint_still_prompt(still, scene=20, bible={"face_policy": "ALLOW"}))
    assert codes["STILL_TEMPORAL_CHANGE"] == WARN


def test_whole_film_lint_reports_physical_blocks_before_purchase() -> None:
    findings = lint_film(
        [
            LintScene(scene=19, still_prompt=MEDALS_BACK, motion_prompt=COSMIC_MOTION),
            LintScene(
                scene=20,
                still_prompt=COSMIC_STILL,
                motion_prompt=GROUND_MOTION,
            ),
        ],
        bible={"face_policy": "ALLOW"},
    )
    by_scene = {(item.scene, item.code): item.severity for item in findings}
    assert by_scene[(19, "PHYSICAL_MEDAL_ORIENTATION")] == BLOCK
    assert by_scene[(20, "PHYSICAL_COSMIC_GROUND")] == BLOCK
