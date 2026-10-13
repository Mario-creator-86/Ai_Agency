"""A shot the step stopped before sending says nothing about its scene; a scene quality
control refused waits for the Director's rewrite, not for the Owner (2026-10-12).

«The Zero Script Club» (f06808c9), scene 6: its clip was refused by quality control at 20:44:56
on 10-11 (burned-in caption text, QC.CLIP); the step's retry was cancelled at 20:58:59 when the
Owner stopped autonomy, and recorded as a REFUSED take, RUNPOD.CANCELLED, «Nu s-a cumpărat:
pasul s-a oprit înainte de acest cadru.» The next morning the walk read that take as the scene's
newest word: `classify_failure` knew no CANCELLED and said UNKNOWN, so the scene was held «până
nu decide Proprietarul», and `last_failure_code` returned the cancelled code, so the Director's
ladder saw no quality refusal and never ran. The film waited for him with a letter about a clip
that was hers to rewrite. Nothing here buys; every provider faked, 0 credits.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.media import assembler
from app.media.assembler import (
    CANCELLED_DETAIL,
    CANCELLED_FAILURE_CODE,
    DIRECTOR_REWRITE,
    SCENE_PROMPTS_REWRITTEN_EVENT,
    scene_memory,
    take_failure,
    take_hash,
)
from app.media.models import SceneTake
from app.media.scene_rewrite import last_failure_code, quality_refused
from app.runbook import stages
from app.services import append_event
from sqlalchemy.orm import Session
from test_film_costing import a_film

MODEL = "LTX-2.5"
SHOT = {"kind": "shot", "motion_prompt": "Slow push-in across the office.", "seconds": 5}
STILL = {"kind": "still", "prompt": "The office at night.", "resolution": "1530:2720"}


def at(seconds: int) -> str:
    return (datetime(2026, 10, 11, 20, 0, tzinfo=UTC) + timedelta(seconds=seconds)).isoformat()


def a_take(
    engine,
    storyboard_id: str,
    scene: int,
    *,
    status: str,
    when: int,
    kind: str = "motion",
    fields: dict = SHOT,
    code: str | None = None,
    detail: str | None = None,
    made: bool = False,
) -> str:
    """One take of the scene as it is now; ``made`` gives it a file (a paid, judged result)."""
    take_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            SceneTake(
                id=take_id,
                storyboard_id=storyboard_id,
                scene_number=scene,
                kind=kind,
                prompt_hash=take_hash(fields, MODEL),
                model_id=MODEL,
                resolution="1080p" if kind != "still" else "1530:2720",
                status=status,
                failure_code=code,
                failure_detail=detail,
                path=None,
                sha256=uuid4().hex if made else None,
                created_at=at(when),
                updated_at=at(when),
            )
        )
    return take_id


def scene_six_as_on_the_eleventh(engine, tmp_path) -> str:
    storyboard_id = a_film(engine, tmp_path, scenes=6)
    a_take(
        engine,
        storyboard_id,
        6,
        status="REJECTED",
        when=44 * 60 + 56,
        code="QC.CLIP",
        detail="Controlul clipului: apare text sau un logo",
        made=True,
    )
    a_take(
        engine,
        storyboard_id,
        6,
        status="REFUSED",
        when=58 * 60 + 59,
        code=CANCELLED_FAILURE_CODE,
        detail=CANCELLED_DETAIL,
    )
    return storyboard_id


def test_a_shot_the_step_stopped_before_sending_says_nothing_about_the_scene():
    cancelled = SceneTake(
        id="t",
        storyboard_id="s",
        scene_number=6,
        kind="motion",
        prompt_hash="h",
        model_id=MODEL,
        resolution="1080p",
        status="REFUSED",
        failure_code=CANCELLED_FAILURE_CODE,
        failure_detail=CANCELLED_DETAIL,
    )
    assert take_failure(cancelled) is None
    # A refusal the vendor charged for is still a refusal (nothing cancelled is charged).
    charged = SceneTake(
        id="t2",
        storyboard_id="s",
        scene_number=6,
        kind="motion",
        prompt_hash="h",
        model_id=MODEL,
        resolution="1080p",
        status="REFUSED",
        failure_code=CANCELLED_FAILURE_CODE,
        failure_detail=CANCELLED_DETAIL,
        credits_quoted=36.0,
    )
    assert take_failure(charged) is not None


def test_the_refusal_before_it_stays_the_scenes_newest_and_is_the_directors(engine, tmp_path):
    storyboard_id = scene_six_as_on_the_eleventh(engine, tmp_path)

    with Session(engine) as session:
        assert last_failure_code(session, storyboard_id, 6) == "QC.CLIP"
    assert quality_refused(engine, storyboard_id, [6]) == [6]

    memory = scene_memory(engine, storyboard_id, "shot", {6: SHOT})[6]
    assert memory.attempts == 1  # the refused clip was paid; the cancelled shot was not
    assert [record.kind for record in memory.failures] == ["QUALITY"]
    assert memory.hold_ro is not None
    assert "controlul calității" in memory.hold_ro and "QC.CLIP" in memory.hold_ro
    assert "Directoarea îl rescrie" in memory.hold_ro
    assert "decide Proprietarul" not in memory.hold_ro
    assert "RUNPOD.CANCELLED" not in memory.hold_ro


def test_her_rewrite_lifts_the_hold_and_her_ladder_is_named_in_the_walks_words(engine, tmp_path):
    storyboard_id = scene_six_as_on_the_eleventh(engine, tmp_path)
    # Scene 2: a vendor's safety refusal, charged — the Owner's as before, not hers.
    a_take(
        engine,
        storyboard_id,
        2,
        status="REFUSED",
        when=50 * 60,
        code="SAFETY.CONTENT",
        detail="refused for safety",
        made=True,
    )

    words = stages._held_words(engine, storyboard_id, "restul mișcării", [2, 6])
    assert words == (
        "după pasul «restul mișcării», scena 6 refuzată de controlul calității așteaptă "
        "rescrierea Directoarei; scena 2 așteaptă decizia Proprietarului pe foaia de filmare; "
        "nu se cumpără din nou până atunci."
    )
    hers = stages._held_words(engine, storyboard_id, "restul mișcării", [6])
    assert hers.endswith(
        "așteaptă rescrierea Directoarei; nu se cumpără din nou până nu o rescrie ea."
    )
    assert "Proprietar" not in hers
    his = stages._held_words(engine, storyboard_id, "restul mișcării", [2])
    assert his == (
        "după pasul «restul mișcării», scena 2 așteaptă decizia Proprietarului pe foaia de "
        "filmare; nu se cumpără din nou până nu decide el."
    )

    # Her rewrite decides about the scene: the hold is lifted, the attempts count again.
    with Session(engine) as session, session.begin():
        append_event(
            session,
            SCENE_PROMPTS_REWRITTEN_EVENT,
            "storyboard",
            storyboard_id,
            1,
            {"scene_index": 6, "layer": "motion", "decided_by": DIRECTOR_REWRITE},
            str(uuid4()),
        )
    memory = scene_memory(engine, storyboard_id, "shot", {6: SHOT})[6]
    assert memory.hold_ro is None and memory.attempts == 0


def test_an_approved_sibling_at_the_same_moment_outranks_the_gates_refusal(engine, tmp_path):
    """The stills gate judges a request's candidates together: one REJECTED, one APPROVED at
    the same instant is a scene with a picture, not a refused one."""
    storyboard_id = a_film(engine, tmp_path, scenes=3)
    a_take(
        engine,
        storyboard_id,
        3,
        status="REJECTED",
        when=0,
        kind="still",
        fields=STILL,
        code="LOCAL.STILL_GATE",
        detail="două panouri",
        made=True,
    )
    a_take(
        engine, storyboard_id, 3, status="APPROVED", when=0, kind="still", fields=STILL, made=True
    )

    memory = scene_memory(engine, storyboard_id, "still", {3: STILL})[3]
    assert memory.hold_ro is None
    assert assembler._newest_quality_refusal([]) is None
