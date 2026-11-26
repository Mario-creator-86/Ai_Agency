"""Kael -> Sarah -> vendor exact-text contract, without media/API/DB writes."""

import pytest

from app.media.final_prompts import (
    EDITOR_FINAL,
    FinalPromptError,
    editor_motion_for,
    validate_final,
)
from app.media.prompt_agent import (
    ShotPrompt, _complete_editor_shot, _validated_package,
    compile_prompts, motion_prompt_for,
)
from app.media.prompt_audit import prompt_digest, prompt_text
from app.media.scene_rewrite import (
    STILL,
    MOTION,
    _direct_rewritten_package,
    layer_terms,
    lock_texts,
)


STILL_TEXT = (
    "Documentary photograph, deep indigo vacuum. Three scientists face the camera "
    "on one stage, each with a gold medal on the front of the jacket. "
    "Vertical 9:16, warm steady overhead light, continuous scene, no writing."
)
MOTION_TEXT = (
    "Steady crane up from the three medal recipients, rising toward the hall's "
    "ceiling as the medal reflections glint gently. One continuous shot."
)


def _raw() -> dict:
    return {
        "scene_kind": "LIVE",
        "prompt_format": EDITOR_FINAL,
        "still_prompt": STILL_TEXT,
        "motion_prompt": MOTION_TEXT,
        "camera_move": "crane up",
        "shot_size": "medium",
        "subject": "Medal ceremony, three scientists",
        "action": "They hold medals in front of their jackets",
        "source": "model",
        "negative_prompt": "letters, logos",
    }


def test_still_is_exact_when_compiled_not_shortened_or_reworded() -> None:
    incoming = _raw()
    out = compile_prompts(incoming, {"face_policy": "ALLOW"})
    assert out["prompt_format"] == EDITOR_FINAL
    assert out["still_prompt"] == STILL_TEXT
    assert out["motion_prompt"] == MOTION_TEXT
    assert out["motion_intent"] is None
    assert incoming["still_prompt"] == STILL_TEXT


def test_sarah_audits_exact_vendor_prompts_without_rematerialisation() -> None:
    p = _raw()
    assert prompt_text(p, "still") == STILL_TEXT
    assert prompt_text(p, "motion") == MOTION_TEXT
    assert motion_prompt_for(p, "seedance2_5") == (MOTION_TEXT, "letters, logos")
    assert editor_motion_for(p) == (MOTION_TEXT, "letters, logos")


def test_bad_or_overlong_final_text_fails_closed() -> None:
    with pytest.raises(FinalPromptError, match="still_prompt"):
        validate_final({**_raw(), "still_prompt": ""})
    # The overlength fixture must NOT also end with whitespace: the validator
    # correctly rejects that independent problem first.
    with pytest.raises(FinalPromptError, match="UTF-16"):
        validate_final({**_raw(), "still_prompt": ("word " * 250).strip()})
    with pytest.raises(FinalPromptError, match="spatii exterioare"):
        validate_final({**_raw(), "still_prompt": STILL_TEXT + " "})
    with pytest.raises(FinalPromptError, match="camera_move"):
        validate_final({**_raw(), "camera_move": "teleport camera"})
    with pytest.raises(FinalPromptError, match="motion_prompt"):
        validate_final({**_raw(), "motion_prompt": " " + MOTION_TEXT})


def test_shot_schema_retains_kaels_direct_payload() -> None:
    shot = ShotPrompt(
        scene_index=19, camera_move="crane up",
        still_prompt=STILL_TEXT, motion_prompt=MOTION_TEXT,
        negative_prompt="letters, logos",
    )
    package, notes = _validated_package(
        shot, {"scene_index": 19, "seconds": 5, "narration": "Medals awarded"},
        {"face_policy": "ALLOW"}, "", "",
    )
    assert not any("final" in note for note in notes)
    assert package["prompt_format"] == EDITOR_FINAL
    assert package["still_prompt"] == STILL_TEXT
    assert package["motion_prompt"] == MOTION_TEXT
    assert compile_prompts(package, {"face_policy": "ALLOW"})["still_prompt"] == STILL_TEXT


def test_sarah_motion_rewrite_preserves_paid_still_byte_for_byte() -> None:
    p = _raw()
    context = {
        "package": p,
        "visual_prompt": STILL_TEXT,
        "scene_index": 19,
    }
    revised = "Steady crane up above the medals; the stage remains fixed and clear."
    out = _direct_rewritten_package(
        context, {"motion_prompt": revised, "camera_move": "crane up"}, MOTION
    )
    assert out["still_prompt"] == STILL_TEXT
    assert out["motion_prompt"] == revised
    assert out["motion_intent"] is None
    assert "look_block" in out


def test_sarah_still_rewrite_keeps_editor_finals_not_composer_text() -> None:
    context = {"package": _raw(), "visual_prompt": STILL_TEXT}
    revised_still = (
        "Documentary photograph of three scientists seen three-quarters frontal, "
        "with gold medals attached to the front of their jackets. Warm stage lighting."
    )
    revised_motion = "Crane up from the medals toward the rafters, one continuous shot."
    out = _direct_rewritten_package(
        context,
        {
            "still_prompt": revised_still, "motion_prompt": revised_motion,
            "camera_move": "crane up",
        },
        STILL,
    )
    assert out["still_prompt"] == revised_still
    assert out["motion_prompt"] == revised_motion


def test_direct_layer_terms_no_longer_claim_composer_fixed_phrases() -> None:
    p = _raw()
    context = {"package": p, "visual_prompt": STILL_TEXT}
    a = layer_terms(context, "still")
    b = layer_terms(context, "motion")
    assert "still_prompt" in a["fields_he_may_change"]
    assert "motion_prompt" in b["fields_he_may_change"]
    assert b["kept_word_for_word"]["still_prompt"] == STILL_TEXT
    assert b["fixed_sentences"] == {"still": [], "motion": []}


def test_new_shot_without_complete_final_text_cannot_reach_purchase() -> None:
    assert not _complete_editor_shot(ShotPrompt(scene_index=1, camera_move="static"))
    assert not _complete_editor_shot(
        ShotPrompt(scene_index=1, camera_move="static", still_prompt=STILL_TEXT)
    )
    assert _complete_editor_shot(
        ShotPrompt(
            scene_index=1, camera_move="crane up",
            still_prompt=STILL_TEXT, motion_prompt=MOTION_TEXT,
        )
    )


def test_approval_digest_for_editor_final_is_exact_and_legacy_stays_compatible() -> None:
    assert prompt_digest("A   B", exact=True) != prompt_digest("A B", exact=True)
    assert prompt_digest("A   B") == prompt_digest("A B")


def test_editor_final_has_no_composer_locked_phrases_in_sarah_review() -> None:
    context = {"package": _raw(), "visual_prompt": STILL_TEXT}
    still_locks = lock_texts(context, "still")
    motion_locks = lock_texts(context, "motion")
    assert still_locks["constants"] == ()
    assert still_locks["picture"] == ()
    assert motion_locks["constants"] == ()
    assert motion_locks["picture"] == (STILL_TEXT,)
