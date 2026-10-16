"""A refused still the gate's local checks stopped is judged again by today's gate, free
(2026-10-16 06:47Z, 87c05891 scene 8: the band rule changed, the refusal stood, the brief
pinned it to the composer's sentences and the ladder never asked again — the episode could
not start, fourteen walks in a row)."""

from __future__ import annotations

from app.media import stills_stage
from app.media.faces import FaceCount
from app.media.models import SceneTake
from app.media.picture_qc import StillJudgement, StillVerdict
from app.models import DomainEvent
from app.runbook import stages
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import a_film

LOCAL_STOP = (
    "Imaginea nu e o singură fotografie: o bandă plată pe toată lățimea, jos, lipită de "
    "margine; Imaginea nu a fost privită: verificările locale au oprit-o deja (panels)"
)


def _judge(passes: bool):
    looked: list[str] = []

    def judge(engine, registry, path, plan, correlation_id, *, ffmpeg_path=None):
        looked.append(str(path))
        return StillJudgement(
            status="MEASURED",
            verdict=StillVerdict(
                scene=plan.scene,
                faces_visible=False,
                readable_text=False,
                matches_plan=passes,
                look_ok=True,
                technical_ok=True,
                bible_violations="none" if passes else "the desk is missing",
                verdict="buy_motion" if passes else "regenerate_still",
                reason="the scene as planned" if passes else "the desk the plan names is missing",
            ),
            detail_ro="" if passes else "biroul lipsește",
            run_id="run-1",
            looked_by="Video Editor",
            image_width=1080,
        )

    return judge, looked


def _no_faces(path, **_):
    return FaceCount(status="MEASURED", faces=0, boxes=(), detail_ro="0 fețe")


def _refused_by_local_checks(engine, tmp_path, board: str) -> str:
    """The film's one still of scene 1 refused by the gate's local checks, its file on disk."""
    file = tmp_path / "scene_01_refused.png"
    file.write_bytes(b"still of the desk")
    with Session(engine) as session, session.begin():
        (row,) = session.scalars(
            select(SceneTake).where(SceneTake.storyboard_id == board, SceneTake.kind == "still")
        )
        row.status = "REJECTED"
        row.approved_by = None
        row.failure_code = stills_stage.GATE_FAILURE_CODE
        row.failure_detail = LOCAL_STOP
        row.path = str(file)
        return str(row.id)


def test_a_still_the_local_checks_stopped_is_judged_again_and_approved_by_the_gate(
    engine, tmp_path
):
    board = a_film(engine, tmp_path, scenes=1)
    take_id = _refused_by_local_checks(engine, tmp_path, board)
    judge, looked = _judge(passes=True)

    approved = stills_stage.rejudge_refused_stills(
        engine, board, 1, "c", judge=judge, face_counter=_no_faces, measure=("faces",)
    )

    assert approved is True and looked == [str(tmp_path / "scene_01_refused.png")]
    with Session(engine) as session:
        row = session.get(SceneTake, take_id)
        assert row.status == "APPROVED" and row.approved_by == stills_stage.GATE_REVIEWER
        assert row.failure_code is None and row.failure_detail is None
        (event,) = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == stills_stage.REJUDGED_EVENT)
        )
        assert event.payload["scene_index"] == 1 and event.payload["decision"] == "PASSED"
        assert event.payload["take_id"] == take_id
    # Approved: nothing to judge again, and the ladder has nothing to settle or ask.
    assert stills_stage.rejudge_refused_stills(engine, board, 1, "c", judge=judge) is False
    film = {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [1]}
    assert stages._ladder_scenes(engine, board, film) == [] and "rejudged" not in film


def test_a_still_refused_again_keeps_todays_reasons_and_is_not_approved(engine, tmp_path):
    board = a_film(engine, tmp_path, scenes=1)
    take_id = _refused_by_local_checks(engine, tmp_path, board)
    judge, looked = _judge(passes=False)

    approved = stills_stage.rejudge_refused_stills(
        engine, board, 1, "c", judge=judge, face_counter=_no_faces, measure=("faces",)
    )

    assert approved is False and len(looked) == 1
    with Session(engine) as session:
        row = session.get(SceneTake, take_id)
        assert row.status == "REJECTED" and row.failure_code == stills_stage.GATE_FAILURE_CODE
        assert "verificările locale" not in str(row.failure_detail)  # today's words
        assert row.failure_detail
