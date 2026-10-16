"""The Owner's renders cap in the stills stage (2026-10-16 01:46Z, 87c05891 scene 1): past
three stills of a scene, none passed and her look letting none stand, the closest candidate
is the scene's picture and the film goes on — scenes that take their look from it are bought.
"""

from __future__ import annotations

from uuid import uuid4

from app.media import stills_stage
from app.media.models import SceneTake
from app.media.still_gate import NextStep, StillReport
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import a_film


def _take(session: Session, board: str, scene: int) -> str:
    take_id = str(uuid4())
    now = utc_now()
    session.add(
        SceneTake(
            id=take_id,
            storyboard_id=board,
            scene_number=scene,
            kind="still",
            prompt_hash=uuid4().hex,
            model_id="seedream5_pro",
            resolution="1080:1920",
            status="REJECTED",
            failure_code="LOCAL.STILL_GATE",
            failure_detail="nu arată ce cere scena",
            path=f"storage/{take_id}.bin",
            sha256=uuid4().hex,
            remote_task_id=f"task-{take_id[:8]}",
            created_at=now,
            updated_at=now,
        )
    )
    return take_id


def _report(scene: int, violations: list[str], reasons: list[str], score: float) -> StillReport:
    return StillReport(
        path="still.png",
        sha256=uuid4().hex,
        scene=scene,
        checks=(),
        judgement=None,
        decision="BLOCKED",
        outcome="regenerate_still",
        reasons_ro=tuple(reasons),
        warnings_ro=(),
        faces_found=False,
        violations=tuple(violations),
        unmeasured=(),
        score=score,
    )


def test_past_three_stills_the_closest_candidate_stands_and_the_scene_goes_on(
    engine, tmp_path, monkeypatch
):
    board = a_film(engine, tmp_path, scenes=2)  # one approved still a scene already
    with Session(engine) as session, session.begin():
        ids = [_take(session, board, 1) for _ in range(3)]
        _take(session, board, 2)
    assert stills_stage._at_renders_cap(engine, board, 1)
    assert not stills_stage._at_renders_cap(engine, board, 2)  # two made: another may be bought

    worse = _report(1, ["plan", "framing"], ["prim-plan, nu cadru larg", "fereastră"], 0.3)
    closer = _report(1, ["plan"], ["prim-plan, nu cadru larg"], 0.5)
    verdicts = [(ids[0], worse), (ids[1], closer)]
    monkeypatch.setattr(stills_stage, "_set_verdicts", lambda *a, **k: None)
    monkeypatch.setattr(
        stills_stage,
        "_director_looks",
        lambda *a, **k: stills_stage._RoundEnd(confirmed=["Directoarea confirmă refuzul"]),
    )
    monkeypatch.setattr(
        stills_stage,
        "round_step",
        lambda reports, rerolls_done: NextStep("needs_owner", "", "nu arată ce cere scena"),
    )
    after: list[tuple] = []
    monkeypatch.setattr(stills_stage, "_after_approval", lambda *a, **k: after.append(a))
    scene = stills_stage._Scene(
        index=1,
        kind="LIVE",
        words="w",
        identity={},
        look_block="",
        camera_move="static",
        source=None,
    )

    end = stills_stage._settle_round(engine, None, board, scene, verdicts, "c", rerolls=0)

    assert end.take_id == ids[1] and end.approved_by == stills_stage.CAP_APPROVER
    assert end.outcome is None and not end.again
    assert end.confirmed == ["Directoarea confirmă refuzul"]
    with Session(engine) as session:
        chosen = session.get(SceneTake, ids[1])
        assert chosen.status == "APPROVED" and chosen.approved_by == stills_stage.CAP_APPROVER
        assert chosen.failure_code is None and chosen.failure_detail is None
        assert session.get(SceneTake, ids[0]).status == "REJECTED"
    assert after and after[0][3] is end
    said = end.approved()
    assert said["status"] == "APPROVED" and said["approved_by"] == stills_stage.CAP_APPROVER
    assert said["take_id"] == ids[1]

    # Under the cap not yet reached, the round ends as before: the scene waits for the rewrite.
    scene_two = stills_stage._Scene(
        index=2,
        kind="LIVE",
        words="w",
        identity={},
        look_block="",
        camera_move="static",
        source=None,
    )
    with Session(engine) as session:
        two = [
            row.id
            for row in session.scalars(
                select(SceneTake).where(
                    SceneTake.storyboard_id == board,
                    SceneTake.scene_number == 2,
                    SceneTake.status == "REJECTED",
                )
            )
        ]
    end_two = stills_stage._settle_round(
        engine, None, board, scene_two, [(two[0], closer)], "c", rerolls=0
    )
    assert end_two.take_id is None and end_two.outcome is not None
    assert end_two.outcome["status"] == "NEEDS_OWNER"
