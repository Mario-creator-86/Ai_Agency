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
    CLOSE_PEOPLE_SENTENCE,
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
    assert "everything that moves goes to motion_prompt" in (_REWRITE_INSTRUCTIONS)
    assert "never a camera move, a speed or a span of the clip's seconds" in _SHOTS_INSTRUCTIONS


def test_a_detail_shot_of_a_person_keeps_the_face_rule_at_its_own_scale():
    """2026-10-15 18:45Z, 7c26a7ce scene 2: a detail shot of the scientist's hands lifting
    the bar carried «Any people appear only as small distant figures seen from behind» — the
    Director refused it six rounds running and the Editor could not remove a composer
    sentence. A close or detail frame of a person says the rule at its own scale; a wide one
    says it as before; a scene of objects says the frame holds only the things named."""
    from app.media.prompt_agent import compile_prompts
    from app.media.prompt_lint import NO_FACE_STATED

    base = {
        "subject": "The scientist's hands gripping and lifting the platinum-iridium bar",
        "environment": "a windowless charcoal laboratory",
        "lighting": "one warm-red laser line raking the dark floor",
        "camera": "Detail shot, 85mm lens",
    }
    bible = {"continuity_rules": ["No human faces appear"]}
    detail = compile_prompts(base, bible)["still_prompt"]
    assert CLOSE_PEOPLE_SENTENCE in detail and PEOPLE_SENTENCE not in detail, detail
    assert NO_FACE_STATED.search(CLOSE_PEOPLE_SENTENCE)
    medium = compile_prompts({**base, "camera": "Medium shot, 50mm lens"}, bible)["still_prompt"]
    assert CLOSE_PEOPLE_SENTENCE in medium and PEOPLE_SENTENCE not in medium, medium
    wide = compile_prompts({**base, "camera": "Wide establishing shot, 24mm lens"}, bible)[
        "still_prompt"
    ]
    assert PEOPLE_SENTENCE in wide and CLOSE_PEOPLE_SENTENCE not in wide, wide
    objects = compile_prompts(
        {**base, "subject": "The platinum-iridium bar in its open glass case"}, bible
    )["still_prompt"]
    assert NO_PEOPLE_SENTENCE in objects and CLOSE_PEOPLE_SENTENCE not in objects, objects


def test_the_frame_keeps_the_plans_placement_after_its_label():
    """03:00Z, 7c26a7ce scene 1: the plan's camera said «Wide establishing shot, straight-on,
    24mm wide: the glass display case centred in the vertical frame, the bar large and
    centred inside it, the dark room around; static — the framing holds, no movement, across
    the shot's 7.6 seconds», the composer said «Wide establishing shot, 24mm lens.», and the
    Director's review refused every rewrite for «a bare label with no framing distance». The
    placement after the colon is said; the movement, the span and the exclusions are not."""
    from app.media.prompt_agent import compile_prompts, shot_frame

    size, frame = shot_frame(
        "Wide establishing shot, straight-on, 24mm wide: the glass display case centred in "
        "the vertical frame, the bar large and centred inside it, the dark room around; "
        "static — the framing holds, no movement, across the shot's 7.6 seconds."
    )
    assert size == "wide"
    assert frame == (
        "Wide establishing shot, 24mm lens: the glass display case centred in the vertical "
        "frame, the bar large and centred inside it, the dark room around."
    ), frame
    assert shot_frame("Medium shot, 50mm lens")[1] == "Medium shot, 50mm lens."
    # 03:12Z: the Editor's camera field with its own distance sentence; the negated and the
    # camera's sub-clauses leave, the placement stays.
    _size, held = shot_frame(
        "Wide establishing shot, 24mm lens, the camera standing at a wide distance across the "
        "room: the entire windowless laboratory is held in frame — its charcoal and slate blue "
        "walls, the one steel workbench and the glass display case complete in its fixed spot "
        "— with the case and the bar in the upper two thirds and the lower quarter calm and "
        "uncluttered. The camera stays at that same wide distance and does not tighten on "
        "anything at any point."
    )
    assert held.startswith("Wide establishing shot, 24mm lens: the entire windowless laboratory"), (
        held
    )
    assert "upper two thirds" in held and "tighten" not in held and "camera" not in held, held
    # A composer sentence pasted into a field is not said twice.
    pasted = compile_prompts(
        {
            "subject": (
                "The platinum-iridium bar resting inside its glass display case. The frame "
                "holds only the place and the things named."
            ),
            "environment": "the windowless measurement laboratory",
            "camera": "Wide establishing shot, 24mm lens",
        },
        {"continuity_rules": ["No human faces appear"]},
    )["still_prompt"]
    assert pasted.count("The frame holds only the place and the things named") == 1, pasted
    still = compile_prompts(
        {
            "subject": "The platinum-iridium bar resting inside its glass display case",
            "environment": "the windowless measurement laboratory, charcoal and slate blue walls",
            "camera": (
                "Wide establishing shot, straight-on, 24mm wide: the glass display case "
                "centred in the vertical frame, the bar large and centred inside it; static "
                "— the framing holds"
            ),
        },
        {"continuity_rules": ["No human faces appear"]},
    )["still_prompt"]
    assert "the bar large and centred inside it" in still, still
    assert "framing holds" not in still and "static" not in still.lower(), still


def test_the_room_is_kept_before_a_long_subject():
    """2026-10-15 19:56Z, 7c26a7ce scene 2: a 51-word subject pushed the laboratory, the
    light and the composition out of the 120-word budget, and the Director refused the words
    four rounds running for the missing room — the Editor's fields were right. The subject is
    said shorter, its later clauses taken off, until the room is in."""
    from app.media.prompt_agent import _shorter_subject, compile_prompts

    subject = (
        "The scientist's hands and forearms, seen from behind and below the shoulders: only "
        "her hands, forearms, shoulders and back are in frame, seen from behind; her face is "
        "never shown and is turned away from the camera, her right hand gripping the end of "
        "the silvery platinum-white rectangular platinum-iridium bar, her left hand under it"
    )
    environment = (
        "The windowless measurement laboratory: charcoal and slate blue walls, the steel "
        "workbench, the glass display case in the same spot, the warm-red laser line on the "
        "dark floor"
    )
    package = {
        "subject": subject,
        "action": "Her hands lift the bar clear of its glass case, raise it a little",
        "environment": environment,
        "lighting": "The thin bright warm-red laser line on the floor, the only light that moves",
        "camera": "Medium shot, 50mm lens",
    }
    still = compile_prompts(package, {"continuity_rules": ["No human faces appear"]})[
        "still_prompt"
    ]
    assert "windowless measurement laboratory" in still, still
    assert "Her hands lift the bar clear of its glass case" in still, still
    assert still.startswith("Documentary") and "The scientist's hands and forearms" in still
    from app.media.prompt_lint import STILL_WORDS

    assert len(still.split()) <= STILL_WORDS[1]
    shorter = _shorter_subject("A, B; C: D")
    assert shorter == ["A, B, C.", "A, B.", "A."]


def test_a_clause_of_the_action_the_subject_already_says_is_said_once():
    """2026-10-15 20:34Z, 7c26a7ce scene 2: «the bar lowered at her side» stood in the subject
    and again in the action; the Director: «say each movement once». The composer keeps the
    action's own clauses and drops the one the subject carries."""
    from app.media.prompt_agent import _without_clauses_said_by, compile_prompts

    subject = (
        "The scientist's hands, the silvery platinum-iridium bar held low at her side, seen "
        "from behind"
    )
    action = (
        "Her hand points along the thin warm-red laser line on the floor, the silvery "
        "platinum-iridium bar held low at her side"
    )
    assert _without_clauses_said_by(action, subject) == (
        "Her hand points along the thin warm-red laser line on the floor."
    )
    assert _without_clauses_said_by("Her hand points along the line", "The bar in its case") == (
        "Her hand points along the line."
    )
    still = compile_prompts(
        {"subject": subject, "action": action, "camera": "Medium shot, 50mm lens"},
        {"continuity_rules": ["No human faces appear"]},
    )["still_prompt"]
    assert still.count("held low at her side") == 1, still
