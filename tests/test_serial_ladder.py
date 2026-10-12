"""The serial rung of the Director's ladder (2026-10-12).

Live, film f06808c9 («The Zero Script Club»): the stills of scenes 3 and 4 came back as stacked
panels on every candidate and re-roll, the composer was fixed (48bbcd1), and the walk after the
restart stopped on «Directoarea nu a putut încă rescrie scenele 3, 4 … (Scena nu este una pe
care studioul o rescrie (card, serial, film închis))»: the Director's rewrite reads no serial
scene, a redo would have bought the stored words again, and the film waited for the Owner —
which his rule forbids. A serial scene's words are the composer's: said again with today's
composer when they changed, written as her decision on the scene, so the stills step buys
again on the new words; a scene whose words are already today's says so and is not rewritten.
Every provider is faked; nothing is bought.
"""

from __future__ import annotations

from uuid import uuid4

from app.media.assembler import SCENE_PROMPTS_REWRITTEN_EVENT, _scene_prompt_rewrite
from app.media.models import SceneTake, StoryboardScene
from app.media.prompt_agent import MOVE_SENTENCES, SERIAL_FACES_SENTENCE
from app.media.scene_rewrite import (
    SERIAL_RECOMPOSE_REASON,
    rewrite_failed_scene,
    serial_recomposition,
)
from app.models import DomainEvent
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_serial_look import (  # noqa: F401
    SEQUENCE_SHOT,
    fake_editor,
    models,
    scenes_of,
    serial_board,
    staffed,
)

STALE_STILL = (
    "Warm hand-drawn 2D animation like the studio's own office picture. Location: Accounting & "
    "Treasury, ground floor. Medium close-up on Nadia, a slow tilt down from her face to the "
    "ledger and back up as she speaks, ending on her eyes behind the tortoiseshell glasses. In "
    "frame, facing the viewer: Nadia: Chestnut hair in a low bun. Nadia taps the brass pen once "
    "against the green ledger, pauses before the number, then lays the pen flat."
)
STALE_MOTION = "Static camera, held steady. "


def described_board(engine, monkeypatch) -> str:
    """A serial storyboard whose shots the model described with a camera path and a chain."""
    from app.media.serial_storyboard import describe_serial_shots

    board_id = serial_board(engine, monkeypatch)
    pack = {
        "shots": [
            {"scene_index": index, "story_purpose": "SETUP", **SEQUENCE_SHOT}
            for index in range(1, 7)
        ]
    }
    fake_editor(monkeypatch, pack)
    describe_serial_shots(engine, models(), board_id, str(uuid4()))
    return board_id


def make_stale(engine, board_id: str, scene_index: int) -> None:
    """The scene's stored words as the composer of 2026-10-11 wrote them, before its fix."""
    with Session(engine) as session, session.begin():
        scene = session.scalar(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == board_id,
                StoryboardScene.scene_index == scene_index,
            )
        )
        package = dict(scene.prompt_json or {})
        package["still_prompt"] = STALE_STILL
        package["motion_prompt"] = STALE_MOTION + str(package.get("action"))
        scene.prompt_json = package
        scene.visual_prompt = STALE_STILL


def refused_by_the_gate(engine, board_id: str, scene_index: int) -> None:
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=str(uuid4()),
                storyboard_id=board_id,
                scene_number=scene_index,
                kind="still",
                prompt_hash=uuid4().hex,
                model_id="Qwen-Image-2512",
                resolution="1530:2720",
                status="REJECTED",
                failure_code="LOCAL.STILL_GATE",
                failure_detail="trei panouri suprapuse",
                path=None,
                sha256=None,
                created_at=now,
                updated_at=now,
            )
        )


def test_a_stale_serial_scene_is_composed_again_as_her_decision(engine, staffed, monkeypatch):  # noqa: F811
    board_id = described_board(engine, monkeypatch)
    make_stale(engine, board_id, 3)
    refused_by_the_gate(engine, board_id, 3)

    outcome = rewrite_failed_scene(engine, models(), board_id, 3, "c-1")

    assert outcome["rewritten"] is True and outcome["layer"] == "still"
    assert outcome["reason"] == SERIAL_RECOMPOSE_REASON
    scene = next(s for s in scenes_of(engine, board_id) if s.scene_index == 3)
    package = dict(scene.prompt_json or {})
    still = package["still_prompt"]
    assert still == scene.visual_prompt
    for path in ("tilt down", "back up", "then lays"):
        assert path not in still, (path, still)
    assert "One continuous picture fills the whole tall frame" in still
    # The move the composer chose for the shot is kept; the motion is today's composer's.
    move = package["camera_move"]
    assert move in MOVE_SENTENCES
    assert package["motion_prompt"].startswith(MOVE_SENTENCES[move])
    assert not package["motion_prompt"].startswith(STALE_MOTION)
    assert SERIAL_FACES_SENTENCE in package["motion_prompt"]
    with Session(engine) as session:
        (event,) = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == SCENE_PROMPTS_REWRITTEN_EVENT)
        ).all()
        assert event.payload["decided_by"] == "director" and event.payload["layer"] == "still"
        assert event.payload["scene_index"] == 3
        assert event.payload["old_still_prompt"] == STALE_STILL
        assert event.payload["still_prompt"] == still
        # Said again once: the words are today's now.
        assert serial_recomposition(session, board_id, 3) is None


def test_a_serial_scene_with_todays_words_is_not_rewritten_and_says_so(
    engine,
    staffed,  # noqa: F811
    monkeypatch,
):
    """Nothing refused the scene: its words are today's and nothing is made again."""
    board_id = described_board(engine, monkeypatch)

    outcome = rewrite_failed_scene(engine, models(), board_id, 2, "c-2")

    assert outcome["rewritten"] is False
    assert "cuvintele de azi" in outcome["reason"]
    assert "card, serial" not in outcome["reason"]
    with Session(engine) as session:
        assert (
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == SCENE_PROMPTS_REWRITTEN_EVENT)
            ).all()
            == []
        )


def test_a_serial_scene_with_todays_words_refused_by_quality_control_is_made_again_on_them(
    engine,
    staffed,  # noqa: F811
    monkeypatch,
):
    """2026-10-12: a serial scene whose words the composer had already said today, refused by
    the gate (or its clip by clip QC), left the rung with nothing to rewrite — and the walk
    stopped on it for good. Her decision is to make the picture (or the clip) again on the same
    words: the record carries it (the hold lifts, the attempts count again), the words stay."""
    from app.media.scene_rewrite import SERIAL_REROLL_REASON

    board_id = described_board(engine, monkeypatch)
    before = next(s for s in scenes_of(engine, board_id) if s.scene_index == 2)
    refused_by_the_gate(engine, board_id, 2)

    outcome = rewrite_failed_scene(engine, models(), board_id, 2, "c-2")

    assert outcome["rewritten"] is True and outcome["layer"] == "still"
    assert outcome["reason"] == SERIAL_REROLL_REASON
    assert "cuvintele de azi" in outcome["summary_ro"] and "altă sămânță" in outcome["summary_ro"]
    after = next(s for s in scenes_of(engine, board_id) if s.scene_index == 2)
    assert after.visual_prompt == before.visual_prompt
    assert dict(after.prompt_json or {}) == dict(before.prompt_json or {})
    with Session(engine) as session:
        (event,) = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == SCENE_PROMPTS_REWRITTEN_EVENT)
        ).all()
        assert event.payload["decided_by"] == "director" and event.payload["layer"] == "still"
        assert event.payload["reason"] == SERIAL_REROLL_REASON
        assert event.payload["refused_code"] == "LOCAL.STILL_GATE"
        assert event.payload["still_prompt"] == event.payload["old_still_prompt"]

    # A clip refused by clip QC: the clip is made again, the picture stays.
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=str(uuid4()),
                storyboard_id=board_id,
                scene_number=4,
                kind="motion",
                prompt_hash=uuid4().hex,
                model_id="LTX-2.5",
                resolution="1080p",
                status="REJECTED",
                failure_code="QC.CLIP",
                failure_detail="apare text ars în cadru",
                path=None,
                sha256=uuid4().hex,
                created_at=now,
                updated_at=now,
            )
        )
    clip = rewrite_failed_scene(engine, models(), board_id, 4, "c-4")
    assert clip["rewritten"] is True and clip["layer"] == "motion"
    assert "cadrul" in clip["summary_ro"]


def test_a_redo_of_a_serial_scene_buys_on_todays_words_not_the_stored_ones(
    engine,
    staffed,  # noqa: F811
    monkeypatch,
):
    board_id = described_board(engine, monkeypatch)
    make_stale(engine, board_id, 4)

    with Session(engine) as session:
        rewrite = _scene_prompt_rewrite(session, board_id, 4, "Qwen-Image-2512")
        assert rewrite is not None
        assert rewrite["old_still_prompt"] == STALE_STILL
        assert "tilt down" not in rewrite["still_prompt"]
        assert rewrite["package"]["camera_move"] in MOVE_SENTENCES
        assert not rewrite["motion_prompt"].startswith(STALE_MOTION)
        assert rewrite["visual_prompt"] == rewrite["still_prompt"]
        # A scene whose words are today's needs no rewrite.
        assert _scene_prompt_rewrite(session, board_id, 2, "Qwen-Image-2512") is None
