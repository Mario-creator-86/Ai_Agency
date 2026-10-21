"""Safe recompile of existing composer-defect scenes; no SQLite writes."""

import pytest

from scripts.repair_dark_energy_6_22 import _plan, _validate_take_states

BIBLE = {"face_policy": "ALLOW"}


def _rows() -> list[dict]:
    return [
        {
            "scene_index": 6,
            "scene_kind": "LIVE",
            "shot_type": "WIDE",
            "visual_prompt": "old 16 frame still",
            "prompt_json": {
                "subject": (
                    "A single candle flame, a solid teardrop of luminous burning gas, "
                    "warm amber with a hard bright rim, small above pale cream wax "
                    "and its lit wick, the base glowing cool blue."
                ),
                "action": "It burns gently above the pale wax, alone in the dark room.",
                "environment": (
                    "A dark room at night, a column of cream wax on a dark flat "
                    "surface, absolute darkness in every other part of the room."
                ),
                "camera": (
                    "Wide establishing shot, 24mm lens, vertical 9:16 frame: "
                    "The whole frame is one dark empty room and the flame and "
                    "the surface are the only objects."
                ),
                "lighting": (
                    "The flame is the only light source in the frame, a warm pool "
                    "of amber light around the wick; the rest of the room is darker."
                ),
                "still_prompt": "old 16 frame still",
            },
        },
        {
            "scene_index": 22,
            "scene_kind": "LIVE",
            "shot_type": "MEDIUM",
            "visual_prompt": "old faceless person still",
            "prompt_json": {
                "subject": (
                    "A single thick bar of dark graphite-grey brushed metal "
                    "with crisp edges across the upper two thirds of the frame."
                ),
                "action": "Its right end glows with faint cyan light.",
                "environment": "Void black deep space.",
                "camera": "Medium shot, 50mm lens.",
                "lighting": "Lit by the bar's own faint cyan glow.",
                "still_prompt": (
                    "The person is seen only from behind, the face turned away."
                ),
            },
        },
    ]


def test_scene_six_and_twenty_two_recompile_from_original_fields() -> None:
    rows = _rows()
    results = _plan(rows, BIBLE)
    assert [item["scene"] for item in results] == [6, 22]
    six, twenty_two = results
    assert "16 frame:" not in six["new_visual"].lower()
    assert "the flame is the only light source" in six["new_visual"].lower()
    assert "the person is seen only from behind" not in twenty_two["new_visual"].lower()
    assert six["old_fingerprint"] != six["new_fingerprint"]
    assert twenty_two["old_fingerprint"] != twenty_two["new_fingerprint"]
    assert rows[0]["prompt_json"]["still_prompt"] == "old 16 frame still"


@pytest.mark.parametrize(
    "statuses",
    [
        [(6, "still", "APPROVED")],
        [(22, "motion", "REJECTED")],
        [(6, "still", "SUBMITTED")],
        [(6, "still", "PAID")],
    ],
)
def test_repair_never_changes_prompt_if_a_paid_or_motion_identity_exists(statuses):
    with pytest.raises(RuntimeError):
        _validate_take_states(statuses)


def test_repair_preserves_already_rejected_still_takes_for_future_rejudging():
    _validate_take_states([(6, "still", "REJECTED"), (22, "still", "REJECTED")])
