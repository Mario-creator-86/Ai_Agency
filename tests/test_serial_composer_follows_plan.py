"""The serial composer's fixed sentences follow the scene's plan (2026-10-16).

19:16-19:19Z, serial film 87c05891 «Zero Scripts, Blocked Log», scenes 1 and 6: the Director
refused the Video Editor's rewrites again and again, and the words she blamed were the
composer's own, which no field of his could change: «As they speak their hands gesture, heads
turn and shoulders shift, and behind them the lamp light flickers softly and the plants stir»
(the plan held both hands on the desk and the lamp steady), «Their faces stay expressive and
the same people throughout» (the plan held «brows slightly drawn, lips pressed together»), and
the establishing framing «Sarah small in the middle distance» said beside an action naming
both hands, which built a medium close-up around her. Now the people's gestures are said only
when the plan leaves them free, the room's flicker only when nothing asks for a steady room,
the plan's expression is named and held, and an establishing still leads with the room and
says its people as small figures, with no hand-by-hand detail.

The packages below are the live rows of 87c05891 (read-only, 2026-10-16 19:21Z), trimmed to
the fields the composer reads.
"""

from __future__ import annotations

import pytest
from app.media.prompt_agent import (
    SERIAL_EXPRESSION_LEAD,
    SERIAL_EXPRESSIONS_LEAD,
    SERIAL_FACES_SENTENCE,
    SERIAL_FEELING_LEAD,
    SERIAL_LIFE_SENTENCE,
    SERIAL_LISTEN_TAIL,
    SERIAL_PEOPLE_LIFE,
    SERIAL_PEOPLE_LIFE_SENTENCE,
    SERIAL_ROOM_LIFE_SENTENCE,
    _without_hand_detail,
    compose_serial_motion,
    compose_serial_prompt,
    composition_issues,
    serial_life_sentence,
    serial_still_moment,
)
from app.media.prompt_lint import MOTION_CLOSING
from app.media.scene_rewrite import (
    MOTION,
    STILL,
    _composer_sentences,
    lock_texts,
    review_schema,
    words_kept,
)
from app.media.series_look import load_series_look
from pydantic import ValidationError

SARAH = {
    "id": "6daa56a0-3ab6-4250-9e01-fad08f2e2c17",
    "name": "Sarah Executive",
    "face_hair": (
        "Brunette professional bob with warm highlights; expressive determined brown eyes."
    ),
    "outfit": "Crisp navy two-piece executive blazer, white collared shirt, and sky-blue tie.",
}
NADIA = {
    "id": "nadia",
    "name": "Nadia Accountant",
    "face_hair": "Chestnut hair in a low bun; round tortoiseshell glasses.",
    "outfit": "Plum blouse under a dark violet cardigan.",
}
LOOK_AVOID = [
    "photorealistic live-action footage",
    "glossy 3D CGI render look",
    "warped or extra hands and fingers",
    "faces or clothes changing between shots",
    "writing on walls, boards or screens",
    "unmotivated camera movement",
    "faces or bodies morphing mid-shot",
]
#: 87c05891 scene 1 (HOOK), as stored at 19:21Z.
SCENE_ONE = {
    "action": (
        "Sarah sits centred at the desk facing the viewer, her right hand resting on the closed "
        "storyboard folder, her left hand flat on the desk."
    ),
    "emotion": (
        "Brows slightly drawn, lips pressed together, gaze fixed on the viewer; her shoulders "
        "stay level and heavy, her mouth stays closed."
    ),
    "background": (
        "The room's own life seen wide, inside the wide frame: the brass lamp's warm glow on the "
        "mahogany desk, the night sky through the tall windows, the plant and the bookshelves in "
        "the dark walls."
    ),
    "continuity": (
        "Opening shot: establishes Sarah seated at the mahogany desk in the penthouse, the "
        "closed storyboard folder under her right hand, her left hand flat on the desk, the "
        "night sky behind her; scene 2 must hold the same desk, the same folder, the same night. "
        "The room, its furniture, its equipment and its light hold exactly as they are from the "
        "first frame to the last, every object in its place, its shape and its light, with "
        "nothing warping, drifting or deforming between frames."
    ),
    "ending_frame": (
        "Sarah seated at the wide mahogany desk, her right hand resting on the closed storyboard "
        "folder, her left hand flat on the desk, the tall windows and the night sky behind her — "
        "nothing has changed from the first frame to the last."
    ),
    "lighting": "the series look",
    "motion": (
        "the subject carries on with its action; shadows drift and the light shifts around it"
    ),
    "location": "Executive Penthouse (Director / CEO), floor 4",
    "shot_size": "establishing",
    "camera_move": "static",
    "seconds": 6.4,
    "in_frame": [SARAH],
    "characters": [SARAH],
    "avoid": LOOK_AVOID,
    "series_look_version": 3,
}
#: 87c05891 scene 6 (PAYOFF), as stored at 19:21Z.
SCENE_SIX = {
    **SCENE_ONE,
    "action": (
        "Sarah sits facing the viewer, her right hand resting on the closed storyboard folder, "
        "her left hand flat on the desk surface."
    ),
    "emotion": (
        "Measured and dry, the deadline and the cost: brows slightly drawn, lips pressed "
        "together, gaze fixed on the viewer, shoulders level, mouth closed — this expression "
        "holds unchanged from the first frame to the last, never opening the mouth, never "
        "smiling."
    ),
    "background": (
        "The room's own life seen inside the frame: the brass lamp's steady warm amber glow on "
        "the desk, the night sky through the tall windows, a potted plant and the bookshelves "
        "in the dark walls, the steaming espresso cup resting on the desk beside her — all "
        "holding exactly as they are from the first frame to the last."
    ),
    "continuity": "Matches scenes 1-2: Sarah seated at the same mahogany desk in the penthouse.",
    "ending_frame": (
        "The shot ends on Sarah seated at the wide mahogany desk, her right hand resting on the "
        "closed storyboard folder, her left hand flat on the desk surface, the lamp's glow "
        "steady — every object in its place, nothing changed from the first frame to the last."
    ),
    "shot_size": "single",
    "seconds": 7.2,
}
#: A free-moving dialogue two-shot: nothing held, nothing steady.
DIALOGUE = {
    "action": (
        "Nadia taps the brass pen once against the green ledger as she answers; Sarah leans in "
        "a fraction as she asks her question"
    ),
    "emotion": "Nadia composed, Sarah curious",
    "ending_frame": "Nadia's hazel eyes on Sarah, Sarah's eyebrows raised",
    "background": "the shaded lamp's warm glow over the wooden desk",
    "continuity": "",
    "lighting": "the series look",
    "location": "Accounting & Treasury, ground floor",
    "shot_size": "two_shot",
    "camera_move": "tracking left",
    "seconds": 8.0,
    "in_frame": [NADIA, SARAH],
    "characters": [NADIA, SARAH],
    "avoid": LOOK_AVOID,
}
OLD_FACES = "Their faces stay expressive and the same people throughout."


@pytest.fixture(scope="module")
def look() -> dict:
    return load_series_look()


def test_scene_one_composes_held_hands_a_named_expression_and_no_gesture(look):
    motion = compose_serial_motion(SCENE_ONE, look)
    # No gesture, no flicker: the plan holds both hands and the room (her brief, 19:16Z).
    assert SERIAL_PEOPLE_LIFE not in motion and "hands gesture" not in motion
    assert "flickers" not in motion and "plants stir" not in motion
    assert "expressive" not in motion and OLD_FACES not in motion
    # The plan's expression named and held, in the faces sentence the cap keeps.
    assert SERIAL_FACES_SENTENCE in motion
    assert (
        SERIAL_EXPRESSION_LEAD + "Brows slightly drawn, lips pressed together, gaze fixed on the "
        "viewer; her shoulders stay level and heavy, her mouth stays closed." in motion
    ), motion
    # The clip keeps the whole action, hands included, and ends where the plan ends.
    assert "her right hand resting on the closed storyboard folder" in motion
    assert "nothing has changed from the first frame to the last" in motion
    assert motion.endswith(MOTION_CLOSING)
    # Said once: the feeling is not repeated after the faces.
    assert motion.count("lips pressed together") == 1


def test_scene_one_establishing_still_leads_with_the_room_and_a_small_figure(look):
    still = compose_serial_prompt(SCENE_ONE, look)
    room = "The Executive Penthouse at the top of the studio house"
    framing = "Establishing wide shot at eye level from across the room: the whole room in view"
    small = "Sarah a small full figure in the middle distance"
    pose = "Sarah sits centred at the desk facing the viewer."
    assert room in still and framing in still and small in still and pose in still, still
    assert (
        still.index(room)
        < still.index(framing)
        < still.index(small)
        < still.index("In frame, facing the viewer: Sarah:")
        < still.index(pose)
    )
    # The framing she locked on is gone, and no sentence builds the picture around a hand.
    assert "Sarah small in the middle distance" not in still
    assert "right hand" not in still and "left hand" not in still and "hands" not in still
    # The rest of the plan's still words stay: the expression, the room's life, the continuity.
    assert "Brows slightly drawn, lips pressed together" in still
    assert "the brass lamp's warm glow on the mahogany desk" in still
    assert "establishes Sarah seated at the mahogany desk in the penthouse, the night sky" in still
    # The sheet's check reads the still's first moment as the still says it, the clip's whole.
    motion = compose_serial_motion(SCENE_ONE, look)
    assert serial_still_moment(SCENE_ONE) == "Sarah sits centred at the desk facing the viewer"
    assert composition_issues(SCENE_ONE, still, motion) == []


def test_scene_six_keeps_its_hands_and_its_room_still(look):
    motion = compose_serial_motion(SCENE_SIX, look)
    assert "hands gesture" not in motion and "flickers" not in motion
    assert "expressive" not in motion and SERIAL_FACES_SENTENCE in motion
    # A single keeps its hand detail in the picture: only a wide still drops it.
    still = compose_serial_prompt(SCENE_SIX, look)
    assert "her right hand resting on the closed storyboard folder" in still
    assert serial_life_sentence(SCENE_SIX) == ""


def test_a_free_moving_dialogue_shot_still_moves_its_people_and_its_room(look):
    motion = compose_serial_motion(DIALOGUE, look)
    assert SERIAL_LIFE_SENTENCE in motion, motion
    # Two people: their expressions named and held, a name keeping its capital.
    assert SERIAL_EXPRESSIONS_LEAD + "Nadia composed, Sarah curious." in motion
    assert "expressive" not in motion
    # Each half follows its own part of the plan.
    steady = {**DIALOGUE, "background": "the shaded lamp's steady warm glow over the desk"}
    assert serial_life_sentence(steady) == SERIAL_PEOPLE_LIFE_SENTENCE
    held = {**DIALOGUE, "ending_frame": "both hands resting on the closed ledger"}
    assert serial_life_sentence(held) == SERIAL_ROOM_LIFE_SENTENCE
    avoided = {**DIALOGUE, "avoid": [*LOOK_AVOID, "the lamp light flickering"]}
    assert serial_life_sentence(avoided) == SERIAL_PEOPLE_LIFE_SENTENCE
    wide = {**DIALOGUE, "shot_size": "establishing"}
    assert serial_life_sentence(wide) == SERIAL_ROOM_LIFE_SENTENCE
    # A feeling that changes over the shot is named as the plan says it, its chain kept.
    turning = {**DIALOGUE, "emotion": "Nadia composed, then quietly amused"}
    said = compose_serial_motion(turning, look)
    assert SERIAL_FEELING_LEAD + "Nadia composed, quietly amused." in said, said


def test_the_reaction_and_the_narrator_shots_keep_their_intent(look):
    reaction = {
        **DIALOGUE,
        "shot_size": "reaction",
        "listening": "Sarah",
        "in_frame": [SARAH],
        "beat": {"scene_number": 2, "shot": 2, "of": 3, "size": "reaction", "on": "Sarah"},
    }
    motion = compose_serial_motion(reaction, look)
    # The listener's sentence is the reaction's life, as before; no gesture, no held expression.
    assert f"Sarah {SERIAL_LISTEN_TAIL}" in motion
    assert not any(
        sentence in motion
        for sentence in (
            SERIAL_LIFE_SENTENCE,
            SERIAL_PEOPLE_LIFE_SENTENCE,
            SERIAL_ROOM_LIFE_SENTENCE,
            SERIAL_EXPRESSION_LEAD,
            SERIAL_EXPRESSIONS_LEAD,
        )
    )
    assert SERIAL_FACES_SENTENCE in motion
    # The narrator's shot: the voice in off over the room, nobody in frame speaks.
    narrator = {
        **DIALOGUE,
        "shot_size": "establishing",
        "beat": {"scene_number": 1, "shot": 1, "of": 2, "size": "establishing"},
    }
    said = compose_serial_motion(narrator, look)
    assert SERIAL_PEOPLE_LIFE not in said and SERIAL_ROOM_LIFE_SENTENCE in said
    assert serial_life_sentence({**narrator, "shot_size": "two_shot"}) == SERIAL_ROOM_LIFE_SENTENCE


def test_the_life_and_the_expression_are_his_fields_words_never_a_lock(look):
    """The locks and the attribution read the new words: the faces sentence is the
    composer's; the life sentence is the ending_frame's (a held pose or a steady room in it
    takes it out), the expression the emotion's — so her lock on «As they speak their hands
    gesture» names the field he must change instead of holding the scene."""
    package = {**DIALOGUE}
    package["still_prompt"] = compose_serial_prompt(package, look)
    package["motion_prompt"] = compose_serial_motion(package, look)
    context = {
        "serial": True,
        "package": package,
        "look": look,
        "visual_prompt": package["still_prompt"],
    }
    locks = lock_texts(context, MOTION)
    assert SERIAL_FACES_SENTENCE in locks["constants"]
    assert SERIAL_LIFE_SENTENCE not in locks["constants"]
    assert SERIAL_LIFE_SENTENCE in locks["fields"]["ending_frame"]
    (expression,) = locks["fields"]["emotion"]
    assert expression.startswith(SERIAL_EXPRESSIONS_LEAD)
    review = review_schema((1,), ("camera_move", "ending_frame", "emotion"), locks)
    finding = {
        "id": 1,
        "treated": False,
        "severity": "serious",
        "why_not": "the gesture sentence lifts the hands",
        "locked": True,
        "locked_words": "As they speak their hands gesture, heads turn and shoulders shift",
    }
    with pytest.raises(ValidationError, match="ending_frame is his to change"):
        review.model_validate(
            {"findings": [finding], "reason_ro": "Nu.", "cause": "the gesture sentence"}
        )
    # A lock on the composer's faces sentence is still the composer's.
    locked_faces = {**finding, "locked_words": SERIAL_FACES_SENTENCE}
    done = review.model_validate(
        {"findings": [locked_faces], "reason_ro": "Nu.", "cause": "the faces sentence"}
    )
    assert done.findings[0].lock_kind == "composer"
    # The still layer's constants carry today's establishing framing, not the old words.
    wide = {**SCENE_ONE}
    wide["still_prompt"] = compose_serial_prompt(wide, look)
    wide["motion_prompt"] = compose_serial_motion(wide, look)
    still_locks = lock_texts(
        {"serial": True, "package": wide, "look": look, "visual_prompt": wide["still_prompt"]},
        STILL,
    )
    assert any("Sarah a small full figure" in text for text in still_locks["constants"])
    assert not words_kept("Sarah small in the middle distance", still_locks["constants"])


def test_a_lock_on_the_old_sentences_no_longer_waits():
    """`scene_waits` holds a composer-locked scene while the composer still says the locked
    words: the old faces words and the life sentence are no longer its fixed sentences."""
    kept = _composer_sentences()
    assert not words_kept("Their faces stay expressive", kept)
    assert not words_kept("As they speak their hands gesture", kept)
    assert not words_kept("the lamp light flickers softly and the plants stir", kept)
    assert words_kept("nobody else enters or appears behind", kept)


def test_hand_detail_leaves_only_the_wide_still():
    assert _without_hand_detail(SCENE_ONE["action"]) == (
        "Sarah sits centred at the desk facing the viewer."
    )
    assert _without_hand_detail(
        "Sarah sits centred at the desk facing the viewer; her right hand rests on the closed "
        "storyboard folder; her left hand lies flat on the desk."
    ) == ("Sarah sits centred at the desk facing the viewer.")
    assert _without_hand_detail("Kael leans back with both hands behind his head") == (
        "Kael leans back"
    )
    # Two people's own clauses both stay; nothing without a hand is touched.
    assert _without_hand_detail("Sarah sits at the desk; Marcus leans on the doorframe") == (
        "Sarah sits at the desk; Marcus leans on the doorframe"
    )
    # A single's still keeps its hands: only an establishing or wide shot drops them.
    assert "right hand" in serial_still_moment(SCENE_SIX)


def test_a_tool_defect_on_the_old_composers_words_no_longer_holds(engine):
    """GUARD_VERSION 4: a TOOL_DEFECT the guard recorded before the composer followed the plan
    no longer holds the scene; one recorded today does."""
    from app.media import prompt_audit
    from app.services import append_event
    from sqlalchemy.orm import Session

    board, digest = "87c05891-ef33-4226-aa9f-1e76a93ad385", "d" * 64
    payload = {
        "storyboard_id": board,
        "scene_index": 1,
        "layer": "motion",
        "digest": digest,
        "verdict": prompt_audit.TOOL_DEFECT,
        "reason": "Their faces stay expressive",
        "instructions": prompt_audit.AUDIT_TEMPLATE,
    }
    assert prompt_audit.GUARD_VERSION == 4
    with Session(engine) as session, session.begin():
        append_event(
            session, prompt_audit.AUDIT_EVENT, "storyboard", board, 1, {**payload, "guard": 3}, "c"
        )
    with Session(engine) as session:
        assert prompt_audit.tool_defect_on(session, board, 1, "motion", digest) is None
    with Session(engine) as session, session.begin():
        append_event(
            session,
            prompt_audit.AUDIT_EVENT,
            "storyboard",
            board,
            1,
            {**payload, "guard": prompt_audit.GUARD_VERSION},
            "c",
        )
    with Session(engine) as session:
        assert prompt_audit.tool_defect_on(session, board, 1, "motion", digest) is not None
