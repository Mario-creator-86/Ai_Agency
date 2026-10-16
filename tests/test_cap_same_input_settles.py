"""A picture at the renders cap that cannot be animated again leaves its motion nothing to buy.

2026-10-16 21:45-22:07Z, film 87c05891 «Zero Scripts, Blocked Log», scene 1: three stills, all
refused by the gate, the Director kept 8b7393c4 under the cap (two renders a layer). Its one
clip (1283e81e) was refused for a fault of that picture (a flat band across its bottom, 16% of
the height against 15%). The motion step wanted a new clip from 8b7393c4: the same-input guard
refused it (SAME_INPUT_FAILED) and sent the still back to the gate; no new picture could be
bought, so the cap's choice kept 8b7393c4 again; the motion, at one render of two, never
reached its own cap, so no clip was kept and no local move made. Every walk asked her again
(Ollama tokens) and the film never assembled.

The Owner's rule (2026-10-15/16): past the cap nothing of a layer is bought, what the scene has
stands, the film publishes. Here: the picture is never sent back at the cap, the motion settles
under the cap with the clip the scene has (or her local move, 0 credits), nothing is bought,
and the scene is ready for assembly. Nothing is bought anywhere in these tests: no vendor, no
model, no network.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.media import assembler, renders_cap, stills_stage
from app.media.assembler import (
    CAP_APPROVER,
    SpendMeter,
    _ShotRounds,
    clip_qc_of,
    motion_plan,
    scene_readiness,
)
from app.media.input_guard import REFUSAL_CODE, REFUSED_EVENT
from app.media.models import SceneTake
from app.models import DomainEvent
from app.runbook import stages
from app.services import append_event
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import SEEDANCE
from test_film_costing import a_film as a_film_with_stills
from test_input_guard import bought, clip

pytestmark = pytest.mark.renders_per_layer(2)

MODEL = "seedance2_5"
#: The first frame `assembler._first_frame` sends for the still kept under the cap, and for
#: another still of the scene.
FRAME = b"\xff\xd8\xff\xe0" + b"8b7393c4: the penthouse, a flat band at the bottom " * 8
OTHER_FRAME = b"\xff\xd8\xff\xe0" + b"6bf41f6e: Sarah large in the lower two thirds " * 8
#: The words 1283e81e was bought on, and the motion words rewritten since.
OLD_WORDS = "Static camera on a fixed tripod; Sarah at the desk, the framing held."
NEW_WORDS = "Static camera on a fixed tripod; the whole room in view, Sarah's hands on the folder."
BAND = (
    "Scena 1: nu e o singură fotografie: cadrul first are o bandă plată pe toată lățimea, jos, "
    "lipită de margine (rândurile 405-479 din 480, 16% din înălțime; prag 15%)"
)


def _band_report() -> dict:
    """Clip QC's report on 1283e81e: the band splits its first frame, the still's own fault."""
    return {
        "verdict": "FAILED",
        "passed": False,
        "blocks_ro": [BAND],
        "checks": [
            {"code": "motion", "status": "PASSED", "blocking": False},
            {"code": "panels", "status": "FAILED", "blocking": True},
        ],
        "measured": {"panels": {"frames": [{"at": "first", "splits_the_picture": True}]}},
    }


def _scene_one(engine, board: str) -> SceneTake:
    with Session(engine) as session:
        row = session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == board,
                SceneTake.scene_number == 1,
                SceneTake.kind == "still",
                SceneTake.status == "APPROVED",
            )
        ).one()
        session.expunge(row)
        return row


def _picture_at_the_cap(engine, tmp_path: Path, board: str) -> str:
    """Scene 1's picture made twice (the cap), its approved still the one the Director kept
    under the cap; returns that still's id."""
    kept = _scene_one(engine, board)
    refused = tmp_path / "refused_still.png"
    refused.write_bytes(b"another still of scene 1")
    with Session(engine) as session, session.begin():
        session.get(SceneTake, kept.id).approved_by = CAP_APPROVER
        session.add(
            SceneTake(
                id=str(uuid4()),
                storyboard_id=board,
                scene_number=1,
                kind="still",
                prompt_hash=uuid4().hex,
                model_id="Qwen-Image-Edit-2511",
                resolution="1530:2720",
                status="REJECTED",
                failure_code="LOCAL.STILL_GATE",
                failure_detail="Imaginea nu arată ce cere planul scenei",
                path=str(refused),
                sha256=hashlib.sha256(refused.read_bytes()).hexdigest(),
                credits_quoted=9.0,
                remote_task_id=f"task-{uuid4().hex[:8]}",
                created_at="2026-10-16T01:29:16+00:00",
                updated_at="2026-10-16T01:46:14+00:00",
            )
        )
    with Session(engine) as session:
        assert renders_cap.renders_made(session, board, 1, "still") == 2
    return kept.id


def _refused_clip(engine, tmp_path: Path, board: str, *, frame: bytes = FRAME, on_disk=True):
    """1283e81e: one clip of scene 1, bought from ``frame`` on the old words, refused by clip
    QC for the band in its first frame (the still's fault); on disk unless told otherwise."""
    take_id = bought(
        engine,
        clip(board, words=OLD_WORDS, first_frame=frame, model=MODEL, seconds=8.0),
        status="REJECTED",
        when="2026-10-16T04:42:29+00:00",
        code="QC.CLIP",
        detail=f"Controlul clipului: {BAND}",
        report=_band_report(),
        judged="2026-10-16T04:55:22+00:00",
    )
    if on_disk:
        path = tmp_path / "motion_01_a1ff3781.mp4"
        path.write_bytes(b"the clip 1283e81e")
        with Session(engine) as session, session.begin():
            row = session.get(SceneTake, take_id)
            row.path = str(path)
            row.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
    return take_id


def _rounds(engine, tmp_path: Path, board: str) -> _ShotRounds:
    return _ShotRounds(
        engine,
        storyboard_id=board,
        correlation_id=str(uuid4()),
        take_kind="motion",
        meter=SpendMeter(),
        cap=1000.0,
        overhead=0.0,
        credit_usd=0.01,
        work_dir=tmp_path,
        environment="PRODUCTION",
        bible={},
        ffmpeg_exe=None,
        registry=None,
        clip_judge=None,
        face_counter=None,
        clip_check=None,
        charged=[],
        bought_now=[],
        over_attempts=lambda _index: False,
        attempts_reason=lambda _index: "",
        sent={},
        scene_dicts={},
        over_renders=lambda _index: False,
    )


def _shot_state(still_id: str, frame: bytes = FRAME) -> SimpleNamespace:
    """The motion step's scene 1, about to send its first clip from ``frame``."""
    return SimpleNamespace(
        index=1,
        attempt=1,
        attempts=0,
        model_id=MODEL,
        negative=None,
        seconds=8.0,
        first_frame=frame,
        price=22.0,
        still=SimpleNamespace(id=still_id),
        first_qc=None,
        outcome=None,
    )


def _events(engine, event_type: str, aggregate_id: str) -> list[DomainEvent]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == event_type,
                    DomainEvent.aggregate_id == aggregate_id,
                )
            )
        )


def _scene(plan: dict, index: int) -> dict:
    return next(item for item in plan["scenes"] if item["scene_index"] == index)


def _to_buy(plan: dict) -> list[int]:
    """What the motion plan would buy: the hero's test shot and the motion (scene 1 is the
    film's hero)."""
    return sorted({*plan["steps"]["test_shot"]["to_buy"], *plan["steps"]["motion"]["to_buy"]})


# --------------------------------------------- 1. the clip it has stands, nothing is bought


def test_the_same_input_refused_at_the_picture_cap_keeps_the_clip_and_the_scene_is_ready(
    engine, tmp_path
):
    """87c05891 scene 1 as it stood at 21:45:54Z: the guard refuses a new clip from the still
    kept under the cap. The still stays the scene's picture (never sent back), its motion has
    nothing left to buy, the one clip it has stands under the cap, nothing is bought, and the
    scene is ready for assembly in PRODUCTION; the plan reads it bought."""
    board = a_film_with_stills(engine, tmp_path, scenes=1)
    kept = _picture_at_the_cap(engine, tmp_path, board)
    clip_id = _refused_clip(engine, tmp_path, board)
    rounds = _rounds(engine, tmp_path, board)
    state = _shot_state(kept)

    assert rounds._send(state, seed=250213303, prompt=NEW_WORDS) == []

    assert state.attempts == 0 and rounds.sent == {}, "nothing was sent"
    assert state.outcome["status"] == "NOT_BOUGHT"
    assert state.outcome["failure_code"] == REFUSAL_CODE
    assert state.outcome["layer"] == "still" and state.outcome["rewrite"] is False
    assert "imaginea ei a avut deja 2 randări" in state.outcome["reason"]
    (refused,) = _events(engine, REFUSED_EVENT, board)
    assert refused.payload["take_id"] == clip_id
    with Session(engine) as session:
        still = session.get(SceneTake, kept)
        # The picture kept under the cap stays: no new one could be bought.
        assert still.status == "APPROVED" and still.approved_by == CAP_APPROVER
        assert still.failure_code is None
        kept_clip = session.get(SceneTake, clip_id)
        assert kept_clip.status == "PAID" and kept_clip.approved_by == CAP_APPROVER
        record = clip_qc_of(session, clip_id)
        assert record["verdict"] == assembler.CAP_VERDICT and record["qc_verdict"] == "FAILED"
        # Nothing bought: the motion is still at one render, the picture at its two.
        assert renders_cap.renders_made(session, board, 1, "motion") == 1
        assert renders_cap.renders_made(session, board, 1, "still") == 2
        assert renders_cap.motion_spent(session, board, 1)
        assert renders_cap.cap_local_moves(session, board) == set()
    assert _events(engine, renders_cap.STILL_SENT_BACK_EVENT, kept) == []
    (spent,) = _events(engine, renders_cap.MOTION_SPENT_EVENT, board)
    assert spent.payload["still_take_id"] == kept and spent.payload["cause"] == REFUSAL_CODE
    assert spent.payload["still_renders"] == 2 and spent.payload["motion_renders"] == 1
    (choice,) = _events(engine, "media.cap_choice", board)
    assert choice.payload["layer"] == "motion" and choice.payload["take_id"] == clip_id
    assert choice.payload["how"] == "ONLY_ONE" and choice.payload["chosen_by"] == "studio"

    reading = scene_readiness(engine, board, 1, environment="PRODUCTION")
    assert reading["ok"] and reading["how"] in ("shot", "slowed", "at_risk")
    assert reading["take_id"] == clip_id
    plan = motion_plan(engine, board, capabilities=[SEEDANCE])
    assert _scene(plan, 1)["status"] == "BOUGHT" and _scene(plan, 1)["take_id"] == clip_id
    assert _to_buy(plan) == []
    # Settled once: nothing moves on the next walk, so it never loops on it.
    assert not stills_stage.settle_scene_under_cap(engine, board, 1, "again")


# ------------------------------------------------- 2. no clip to keep: her local move, 0 credits


def test_no_usable_clip_at_the_picture_cap_is_moved_locally_and_said_truly(engine, tmp_path):
    """The refused clip is not on disk: nothing of the motion can stand, so the scene is its
    still moved locally (0 credits), read by the plan, the readiness and the fallback gate —
    and said as the picture's cap, not as a motion that had its two renders."""
    board = a_film_with_stills(engine, tmp_path, scenes=1)
    kept = _picture_at_the_cap(engine, tmp_path, board)
    _refused_clip(engine, tmp_path, board, on_disk=False)
    state = _shot_state(kept)

    assert _rounds(engine, tmp_path, board)._send(state, seed=1, prompt=NEW_WORDS) == []

    assert state.outcome["status"] == "NOT_BOUGHT"
    with Session(engine) as session:
        assert renders_cap.cap_local_moves(session, board) == {1}
        assert renders_cap.renders_made(session, board, 1, "motion") == 1
        assert session.get(SceneTake, kept).status == "APPROVED"
    (move,) = _events(engine, renders_cap.CAP_LOCAL_MOVE_EVENT, board)
    assert move.payload["spent_by"] == "still" and move.payload["renders"] == 1
    assert "imaginea ei a avut deja 2 randări" in move.payload["reason_ro"]
    assert "mișcarea ei a avut deja" not in move.payload["reason_ro"]
    reading = scene_readiness(engine, board, 1, environment="PRODUCTION")
    # `scene_readiness` counts no local move; the sheet's readiness does (`cap_local_moves`).
    assert reading is not None and not reading["ok"]
    plan = motion_plan(engine, board, capabilities=[SEEDANCE])
    scene = _scene(plan, 1)
    assert scene["status"] == "LOCAL" and scene["decided_by"] == renders_cap.CAP_LOCAL_MOVE_BY
    assert "imaginea ei a avut deja 2 randări" in scene["reason_ro"]
    assert _to_buy(plan) == []
    with Session(engine) as session:
        readings = assembler.assembly_readiness(
            session,
            board,
            [assembler.scene_view(row) for row in _rows(session, board)],
            {1: _scene_one(engine, board).sha256},
            environment="PRODUCTION",
            local_moves=renders_cap.cap_local_moves(session, board),
            cap_moves=renders_cap.cap_local_moves(session, board),
        )
    (one,) = readings
    assert one["ok"] and one["how"] == "local_move"
    assert "imaginea păstrată sub plafon nu se mai poate anima" in one["reason_ro"]
    # A motion redo on any route is past the cap too.
    capped = assembler._redo_past_cap(engine, board, 1, "motion")
    assert capped is not None and "STUDIO_RENDERS_PER_LAYER" in capped


def _rows(session: Session, board: str) -> list:
    from app.media.models import StoryboardScene  # noqa: PLC0415

    return list(
        session.scalars(
            select(StoryboardScene)
            .where(StoryboardScene.storyboard_id == board)
            .order_by(StoryboardScene.scene_index)
        )
    )


# ------------------------------------------------------------------- 3. what stays as it was


def test_a_different_picture_with_its_motion_not_spent_is_bought_as_before(engine, tmp_path):
    """The clip refused for the band was made from ANOTHER still of the scene (sent back to
    the gate then); the picture kept under the cap now is a different one. Its motion has a
    render left and nothing refuses its first frame: nothing settles, the old clip is not
    kept, the plan buys the scene's motion and the step sends it."""
    board = a_film_with_stills(engine, tmp_path, scenes=1)
    kept = _picture_at_the_cap(engine, tmp_path, board)
    old_clip = _refused_clip(engine, tmp_path, board, frame=OTHER_FRAME)
    with Session(engine) as session, session.begin():
        other = session.scalars(
            select(SceneTake).where(
                SceneTake.storyboard_id == board,
                SceneTake.kind == "still",
                SceneTake.status == "REJECTED",
            )
        ).one()
        append_event(
            session,
            renders_cap.STILL_SENT_BACK_EVENT,
            "scene_take",
            other.id,
            1,
            {"storyboard_id": board, "scene_number": 1, "failure_kind": "CLIP_QC"},
            "c",
        )
    with Session(engine) as session:
        assert not renders_cap.motion_spent(session, board, 1)
    assert not stills_stage.settle_scene_under_cap(engine, board, 1, "c", act=False)
    assert not stills_stage.settle_scene_under_cap(engine, board, 1, "c")
    with Session(engine) as session:
        assert session.get(SceneTake, old_clip).status == "REJECTED"
    plan = motion_plan(engine, board, capabilities=[SEEDANCE])
    assert _scene(plan, 1)["status"] == "PLANNED" and _to_buy(plan) == [1]
    state = _shot_state(kept, frame=FRAME)
    (request,) = _rounds(engine, tmp_path, board)._send(state, seed=2, prompt=NEW_WORDS)
    assert request.scene_id == "1" and state.outcome is None and state.attempts == 1
    assert _events(engine, renders_cap.MOTION_SPENT_EVENT, board) == []


def test_below_the_picture_cap_the_still_is_still_sent_back_for_a_new_one(engine, tmp_path):
    """The scene's picture was made once: a new one can be bought, so the guard's refusal sends
    the still back to the gate (NEEDS_STILL) exactly as before, and its motion is not spent."""
    board = a_film_with_stills(engine, tmp_path, scenes=1)
    still = _scene_one(engine, board)
    with Session(engine) as session, session.begin():
        session.get(SceneTake, still.id).approved_by = "still_gate"
    _refused_clip(engine, tmp_path, board)
    state = _shot_state(still.id)

    assert _rounds(engine, tmp_path, board)._send(state, seed=3, prompt=NEW_WORDS) == []

    assert state.outcome["status"] == "NEEDS_STILL" and state.outcome["rewrite"] is True
    with Session(engine) as session:
        row = session.get(SceneTake, still.id)
        assert row.status == "REJECTED" and row.failure_code == "LOCAL.STILL_GATE"
        assert renders_cap.renders_made(session, board, 1, "still") == 1
        assert not renders_cap.motion_spent(session, board, 1, still_take_id=still.id)
    assert len(_events(engine, renders_cap.STILL_SENT_BACK_EVENT, still.id)) == 1
    assert _events(engine, renders_cap.MOTION_SPENT_EVENT, board) == []


# ------------------------------------------------ 4. the flip-flop's guard: the live replay


def test_a_still_sent_back_and_kept_again_under_the_cap_settles_its_motion_once(engine, tmp_path):
    """The live film after a restart: 8b7393c4 was sent back three times by the guard and kept
    again by the cap each time (APPROVED by the cap now), the motion held. The walk's ladder no
    longer leaves it to a rewrite that can buy nothing: the clip stands under the cap at once,
    the stop's words say it is hers, and a second walk changes nothing."""
    board = a_film_with_stills(engine, tmp_path, scenes=1)
    kept = _picture_at_the_cap(engine, tmp_path, board)
    clip_id = _refused_clip(engine, tmp_path, board)
    with Session(engine) as session, session.begin():
        for _ in range(3):
            append_event(
                session,
                renders_cap.STILL_SENT_BACK_EVENT,
                "scene_take",
                kept,
                1,
                {
                    "storyboard_id": board,
                    "scene_number": 1,
                    "failure_kind": "CLIP_QC",
                    "failure_code": "LOCAL.STILL_GATE",
                    "reason": "Nu cumpăr din nou: … trebuie mai întâi o imagine nouă.",
                },
                "c",
            )
    plan = motion_plan(engine, board, capabilities=[SEEDANCE])
    scene = _scene(plan, 1)
    assert scene["status"] == "NEEDS_OWNER" and _to_buy(plan) == []
    said = stages._held_words(engine, board, "mișcarea", [1])
    assert "decizia Proprietarului" not in said

    film = {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [1]}
    assert stages._ladder_scenes(engine, board, film) == []
    assert film["settled_under_cap"] == [1]
    with Session(engine) as session:
        assert session.get(SceneTake, clip_id).approved_by == CAP_APPROVER
        assert clip_qc_of(session, clip_id)["accepted_under_cap"] is True
        assert renders_cap.renders_made(session, board, 1, "motion") == 1
        assert session.get(SceneTake, kept).status == "APPROVED"
    assert _scene(motion_plan(engine, board, capabilities=[SEEDANCE]), 1)["status"] == "BOUGHT"
    again = {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [1]}
    stages._ladder_scenes(engine, board, again)
    assert "settled_under_cap" not in again


def test_her_look_that_restored_a_sent_back_still_gives_its_motion_back(engine, tmp_path):
    """A still clip QC sent back and her look restored (`fix_check.restore_sent_back_scenes`:
    APPROVED as hers) is a picture she judged fine: its old send-back does not spend its
    motion."""
    board = a_film_with_stills(engine, tmp_path, scenes=1)
    kept = _picture_at_the_cap(engine, tmp_path, board)
    with Session(engine) as session, session.begin():
        session.get(SceneTake, kept).approved_by = "director_look"
        append_event(
            session,
            renders_cap.STILL_SENT_BACK_EVENT,
            "scene_take",
            kept,
            1,
            {"storyboard_id": board, "scene_number": 1, "failure_kind": "CLIP_QC"},
            "c",
        )
    with Session(engine) as session:
        assert not renders_cap.motion_spent(session, board, 1)
