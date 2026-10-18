"""No media spent in the bounded factual prompt self-repair loop.

The editor must fix only the violating shot before saving; Sarah/Kael cannot
restart the same two-round dialogue without new words or a new failed take.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.media import prompt_agent
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


def test_preflight_repairs_only_the_failed_factual_scene_without_paid_calls(monkeypatch) -> None:
    """One model repair, then an independent lint look, no scene_take writes."""
    original = ShotPrompt(
        scene_index=19,
        subject="Three people seen from behind, medals at their chests.",
        action="People stand with backs to the camera and medals at their chests.",
        environment="Ceremony hall",
        camera="Medium shot",
        camera_move="crane up",
        motion="Medals glint softly",
        lighting="Warm spotlights",
    )
    corrected = original.model_copy(update={
        "subject": "Three people face the camera with medals at their chests.",
        "action": "The medal recipients hold the medals in front of their jackets.",
    })
    packets = {19: original}
    reads = []

    class FakeSession:
        def __init__(self, engine):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def scalars(self, query):
            reads.append(query)
            if len(reads) == 1:
                return [
                    SimpleNamespace(
                        scene_index=19,
                        shot_type="MEDIUM",
                        prompt_json={},
                        scene_kind="LIVE",
                    ),
                ]
            return []  # no already-paid take in the film

    requests = []

    def fake_run(*args, **kwargs):
        requests.append((args, kwargs))
        return {"id": "test-run", "output_text": json.dumps({
            "shots": [corrected.model_dump()],
        })}

    monkeypatch.setattr(prompt_agent, "Session", FakeSession)
    monkeypatch.setattr(prompt_agent, "_run", fake_run)
    failed, repaired, run_ids, protected = prompt_agent._preflight_repair_factual_shots(
        object(),
        object(),
        "editor",
        "film",
        "correlation",
        BIBLE,
        {"scenes": [SCENE]},
        packets,
        None,
        prompt_agent.ShotGenerationProfile(2500),
    )
    assert not failed
    assert not protected
    # parse_shot_plan returns the validated ShotPromptCompiled subtype. Compare
    # the actual repair rather than Pydantic's exact model class identity.
    assert packets[19].scene_index == corrected.scene_index
    assert packets[19].subject == corrected.subject
    assert packets[19].action == corrected.action
    assert packets[19].camera_move == corrected.camera_move
    assert packets[19].environment == corrected.environment
    assert repaired == [{"scene_index": 19, "rounds": 1}]
    assert run_ids == ["test-run"]
    assert len(requests) == 1


def test_preflight_refuses_repeat_answer_after_one_spent_llm_run(monkeypatch) -> None:
    original = ShotPrompt(
        scene_index=19, subject="Three people seen from behind at their chests.",
        action="They have medals at their chests, with backs to camera.",
        environment="Award hall", camera="Medium shot", camera_move="crane up",
        motion="Medals glint.", lighting="Warm spotlights.",
    )
    packets = {19: original}

    class FakeSession:
        def __init__(self, engine):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            return False
        def scalars(self, query):
            self.count = getattr(self, "count", 0) + 1
            if self.count == 1:
                return [SimpleNamespace(
                    scene_index=19, shot_type="MEDIUM",
                    prompt_json={}, scene_kind="LIVE",
                )]
            return []

    calls = []
    def same_reply(*args, **kwargs):
        calls.append(1)
        return {"id": "same-run", "output_text": "{}"}

    monkeypatch.setattr(prompt_agent, "Session", FakeSession)
    monkeypatch.setattr(prompt_agent, "_run", same_reply)
    failed, repaired, run_ids, protected = prompt_agent._preflight_repair_factual_shots(
        object(), object(), "editor", "film", "correlation", BIBLE,
        {"scenes": [SCENE]}, packets, None, prompt_agent.ShotGenerationProfile(2500),
    )
    assert 19 in failed
    assert not repaired
    assert not protected
    assert run_ids == ["same-run"]
    assert packets[19] is original
    assert len(calls) == 1
