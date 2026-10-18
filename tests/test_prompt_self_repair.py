"""No media spent in the bounded factual prompt self-repair loop.

The editor must fix only the violating shot before saving; Sarah/Kael cannot
restart the same two-round dialogue without new words or a new failed take.
"""

from __future__ import annotations

from app.media.prompt_agent import ShotPrompt, _preflight_findings
from app.media.scene_rewrite import (
    _repeated_review_refusals,
    _source_words_fingerprint,
)
from app.media.prompt_lint import BLOCK


SCENE = {
    "scene_index": 19,
    "story_purpose": "EVIDENCE",
    "narration": "Three scientists accepted medals at the ceremony.",
    "writer_visual": "Three scientists receiving medals.",
    "shot_type": "MEDIUM",
    "seconds": 5.0,
    "characters": [],
}
BIBLE = {"face_policy": "ALLOW"}


def test_physical_medal_defect_detected_before_any_vendor_call() -> None:
    shot = ShotPrompt(
        scene_index=19,
        subject="Three people seen from behind receiving medals at their chests.",
        action="The scientists stand with backs to the camera, medals at their chests.",
        environment="An award ceremony hall.",
        camera="Medium shot, 85mm lens",
        camera_move="crane up",
        motion="Warm stage lights catch the medals.",
        lighting="Warm spotlights.",
    )
    findings, compiled = _preflight_findings(
        shot, SCENE, BIBLE, SCENE["narration"], "", [], "MEDIUM",
    )
    assert any(
        item.code == "PHYSICAL_MEDAL_ORIENTATION" and item.severity == BLOCK
        for item in findings
    )
    assert "still_prompt" in compiled and "motion_prompt" in compiled


def test_valid_frontal_medals_are_not_blocked() -> None:
    shot = ShotPrompt(
        scene_index=19,
        subject="Three scientists face the camera with medals at their chests.",
        action="The scientists hold the medals in front of their jackets.",
        environment="An award ceremony hall.",
        camera="Medium shot, 85mm lens",
        camera_move="crane up",
        motion="Warm stage lights glint across the medals.",
        lighting="Warm spotlights.",
    )
    findings, _compiled = _preflight_findings(
        shot, SCENE, BIBLE, SCENE["narration"], "", [], "MEDIUM",
    )
    assert not any(item.code == "PHYSICAL_MEDAL_ORIENTATION" for item in findings)


def test_review_loop_stops_after_two_consecutive_misses_with_unchanged_input() -> None:
    source = {
        "package": {"subject": "same still", "motion_prompt": "same movement"},
        "visual_prompt": "same still",
        "scene_index": 4,
    }
    fingerprint = _source_words_fingerprint(source)
    other = _source_words_fingerprint({**source, "visual_prompt": "changed still"})
    assert fingerprint != other
    attempts = [
        {
            "source_words_fingerprint": fingerprint,
            "_event_timestamp": "2026-10-18T11:05:00+00:00",
            "not_treating": True,
            "review_verdict": "MISSES",
        },
        {
            "source_words_fingerprint": fingerprint,
            "_event_timestamp": "2026-10-18T11:00:00+00:00",
            "not_treating": True,
            "review_verdict": "MISSES",
        },
    ]
    assert not _repeated_review_refusals(attempts[:1], fingerprint)
    assert _repeated_review_refusals(attempts, fingerprint)
    assert not _repeated_review_refusals(
        attempts, fingerprint, newer_take_than="2026-10-18T11:07:00+00:00"
    )
    assert not _repeated_review_refusals(attempts, other)
    assert not _repeated_review_refusals(
        [{**attempts[0], "rewritten": True}, attempts[1]], fingerprint
    )
    assert not _repeated_review_refusals(
        [attempts[0], {**attempts[1], "source_words_fingerprint": other}],
        fingerprint,
    )
