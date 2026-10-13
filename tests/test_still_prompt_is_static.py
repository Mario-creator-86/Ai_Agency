"""The still prompt is one frozen moment (the Owner, 2026-10-13: «în promptul de imagine nu
are ce să caute indicații de mișcare»).

Offline, no provider: the compiler alone. A clause of the plan that moves the camera leaves
the still (a clause that only moves it is the motion's; one that says a moment first keeps the
moment), a tempo or a span of the clip leaves its clause, and the motion prompt keeps all of
it. The lint says when a stored still prompt still carries one, and the writers are told."""

from __future__ import annotations

import pytest
from app.media.prompt_agent import (
    _SHOTS_INSTRUCTIONS,
    COMPOSITION_SENTENCE,
    NO_PEOPLE_SENTENCE,
    PEOPLE_SENTENCE,
    compile_prompts,
)
from app.media.prompt_lint import (
    WARN,
    has_block,
    lint_still_prompt,
    static_clause,
    still_motion,
    without_tempo,
)
from app.media.scene_rewrite import _REWRITE_INSTRUCTIONS

VILLAGE = {
    "scene_index": 1,
    "scene_kind": "LIVE",
    "subject": "a far village of stone houses on a terraced slope",
    "action": "thick grey cloud rolls steadily across the ridges from left to right",
    "environment": "steep Himalayan ridges under low cloud",
    "camera": "wide establishing shot, 24mm lens",
    "lighting": "soft overcast daylight",
    "motion": "thick grey cloud rolls steadily across the ridges from left to right",
    "camera_move": "slow pan right",
}
THERMOMETER = {
    "scene_index": 2,
    "scene_kind": "LIVE",
    "subject": "a mercury thermometer on a lab bench",
    "action": "the mercury rises slowly as the camera pushes in on the Celsius scale",
    "environment": "a dim laboratory, steam drifting slowly",
    "camera": "detail shot, 85mm lens, slow push-in",
    "lighting": "one cold lamp",
    "motion": "the mercury climbs steadily over the clip",
    "camera_move": "slow push-in",
}


def test_the_still_keeps_the_moment_and_leaves_the_tempo_to_the_motion():
    compiled = compile_prompts(VILLAGE, {})

    still, motion = compiled["still_prompt"], compiled["motion_prompt"]
    assert "Thick grey cloud rolls across the ridges from left to right." in still
    assert "steadily" not in still and "pan" not in still.lower()
    assert "rolls steadily across the ridges" in motion and "Slow pan right" in motion
    assert still_motion(still) == ""


def test_a_clause_that_moves_the_camera_leaves_the_still_and_the_moment_stays():
    compiled = compile_prompts(THERMOMETER, {})

    still, motion = compiled["still_prompt"], compiled["motion_prompt"]
    assert "The mercury rises." in still
    assert "camera" not in still.lower() and "push" not in still.lower()
    assert "slowly" not in still and "steadily" not in still and "over the clip" not in still
    assert "steam drifting" in still
    assert still_motion(still) == ""
    assert "Slow push-in" in motion and "climbs steadily over the clip" in motion
    assert not has_block(lint_still_prompt(still, scene=2))
    assert "STILL_MOTION" not in {f.code for f in lint_still_prompt(still, scene=2)}


@pytest.mark.parametrize(
    ("clause", "static"),
    [
        (
            "the mercury rises slowly as the camera pushes in on the Celsius scale",
            "the mercury rises slowly",
        ),
        ("the camera pushes in on the scale", ""),
        ("a slow pan right across the valley", ""),
        ("wind bends the young rice in long waves", "wind bends the young rice in long waves"),
        ("a static camera on the empty hall", "a static camera on the empty hall"),
        ("the ledger open on the desk, the camera drifting closer", "the ledger open on the desk"),
        # The subject's own moment, in words the cinema also uses (the Codex review of
        # c6dc05c): a bare «orbits» or «pulls back» moves no camera.
        ("Earth orbits the Sun", "Earth orbits the Sun"),
        ("she pulls back the curtain", "she pulls back the curtain"),
        ("the view orbits the tower", ""),
        ("a dolly in toward the ledger", ""),
        ("the hall, tracking left along the benches", "the hall"),
    ],
)
def test_the_camera_leaves_a_still_clause(clause, static):
    assert static_clause(clause) == static


@pytest.mark.parametrize(
    ("said", "kept"),
    [
        ("cloud rolls steadily across the ridges", "cloud rolls across the ridges"),
        ("the mercury rises slowly, then holds", "the mercury rises, then holds"),
        ("dust rises over the clip's seconds", "dust rises"),
        ("a quiet valley at dawn", "a quiet valley at dawn"),
    ],
)
def test_the_tempo_leaves_a_still_clause(said, kept):
    assert without_tempo(said) == kept


@pytest.mark.parametrize(
    ("prompt", "evidence"),
    [
        ("Wide shot. The camera slowly pushes in on the thermometer.", "The camera slowly pushes"),
        ("A valley at dawn, a slow pan right across the ridges.", "slow pan right"),
        ("Cloud rolls steadily across the ridges.", "steadily"),
        ("Dust rises over the clip's seconds.", "over the clip's seconds"),
    ],
)
def test_the_lint_warns_about_a_still_prompt_that_moves(prompt, evidence):
    (finding,) = [f for f in lint_still_prompt(prompt, scene=1) if f.code == "STILL_MOTION"]
    assert finding.severity == WARN and finding.evidence == evidence
    assert "un singur moment nemișcat" in finding.message_ro


@pytest.mark.parametrize(
    "prompt",
    [
        "A quiet valley at dawn, mist in the hollows, a village far below.",
        "A static camera on the empty hall, handheld grain, one cold lamp.",
        # The compiler's own sentences (2026-10-13: «the frame holds» was read as a move).
        NO_PEOPLE_SENTENCE,
        PEOPLE_SENTENCE,
        COMPOSITION_SENTENCE,
        "The shot shows the ledger open on the desk; the camera stays on it.",
        "Earth orbits the Sun, its night side dark; she pulls back the curtain.",
    ],
)
def test_a_still_that_stands_still_is_not_flagged(prompt):
    assert still_motion(prompt) == ""
    assert "STILL_MOTION" not in {f.code for f in lint_still_prompt(prompt, scene=1)}


def test_the_writers_are_told_the_still_is_one_frozen_moment():
    assert "one frozen moment" in _REWRITE_INSTRUCTIONS
    assert "everything that moves goes to motion, camera_move and ending_frame" in (
        _REWRITE_INSTRUCTIONS
    )
    assert "never a camera move, a speed or a span of the clip's seconds" in _SHOTS_INSTRUCTIONS
