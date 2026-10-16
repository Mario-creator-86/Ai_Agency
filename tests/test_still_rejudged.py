"""A refused still the gate's local checks stopped is judged again by today's gate, free
(2026-10-16 06:47Z, 87c05891 scene 8: the band rule changed, the refusal stood, the brief
pinned it to the composer's sentences and the ladder never asked again — the episode could
not start, fourteen walks in a row)."""

from __future__ import annotations

from uuid import uuid4

from app.media import stills_stage
from app.media.assembler import still_fields, take_hash
from app.media.faces import FaceCount
from app.media.models import SceneTake
from app.media.picture_qc import StillJudgement, StillVerdict
from app.media.scene_rewrite import CONTENT_REFUSAL, refusal_kind
from app.media.still_gate import REWRITE_PHRASE
from app.models import DomainEvent
from app.providers.runpod.jobs import GenerationJob
from app.runbook import stages
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_film_costing import a_film

LOCAL_STOP = (
    "Imaginea nu e o singură fotografie: o bandă plată pe toată lățimea, jos, lipită de "
    "margine; Imaginea nu a fost privită: verificările locale au oprit-o deja (panels)"
)


class Registry:
    """A model registry, faked: a provider is registered (the look itself is the judge's)."""

    def __init__(self, ids: tuple[str, ...] = ("ollama",)):
        self.ids = list(ids)

    def registered_ids(self) -> list[str]:
        return list(self.ids)


REGISTRY = Registry()


def _judge(passes: bool, *, panels: bool = False):
    looked: list[str] = []

    def judge(engine, registry, path, plan, correlation_id, *, ffmpeg_path=None):
        looked.append(str(path))
        return StillJudgement(
            status="MEASURED",
            verdict=StillVerdict(
                scene=plan.scene,
                faces_visible=False,
                readable_text=False,
                matches_plan=passes or panels,
                look_ok=True,
                technical_ok=True,
                one_picture=not panels,
                bible_violations="none" if passes or panels else "the desk is missing",
                verdict="buy_motion" if passes else "regenerate_still",
                reason=(
                    "the scene as planned"
                    if passes
                    else "two pictures stacked"
                    if panels
                    else "the desk the plan names is missing"
                ),
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


def _rejudged_events(engine) -> list[DomainEvent]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == stills_stage.REJUDGED_EVENT)
            )
        )


def test_a_still_the_local_checks_stopped_is_judged_again_and_approved_by_the_gate(
    engine, tmp_path
):
    board = a_film(engine, tmp_path, scenes=1)
    take_id = _refused_by_local_checks(engine, tmp_path, board)
    judge, looked = _judge(passes=True)

    approved = stills_stage.rejudge_refused_stills(
        engine,
        board,
        1,
        "c",
        registry=REGISTRY,
        judge=judge,
        face_counter=_no_faces,
        measure=("faces",),
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
    assert (
        stills_stage.rejudge_refused_stills(engine, board, 1, "c", registry=REGISTRY, judge=judge)
        is False
    )
    film = {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [1]}
    assert stages._ladder_scenes(engine, board, film) == [] and "rejudged" not in film


def test_a_still_refused_again_keeps_todays_reasons_and_is_not_approved(engine, tmp_path):
    board = a_film(engine, tmp_path, scenes=1)
    take_id = _refused_by_local_checks(engine, tmp_path, board)
    judge, looked = _judge(passes=False)

    approved = stills_stage.rejudge_refused_stills(
        engine,
        board,
        1,
        "c",
        registry=REGISTRY,
        judge=judge,
        face_counter=_no_faces,
        measure=("faces",),
    )

    assert approved is False and len(looked) == 1
    with Session(engine) as session:
        row = session.get(SceneTake, take_id)
        assert row.status == "REJECTED" and row.failure_code == stills_stage.GATE_FAILURE_CODE
        assert "verificările locale" not in str(row.failure_detail)  # today's words
        assert row.failure_detail


def test_a_still_made_on_words_rewritten_since_is_not_judged_again(engine, tmp_path):
    """The review of a0e27dc, finding 25: a still made on the scene's old words was judged
    against the new plan and APPROVED, but `usable_take` reads the take's identity and the
    walk could never use it — the ladder skipped her rung for the scene and the walk stopped
    at the same place again."""
    board = a_film(engine, tmp_path, scenes=1)
    take_id = _refused_by_local_checks(engine, tmp_path, board)
    with Session(engine) as session, session.begin():
        # Made on the words the ladder rewrote since: its identity is no longer the scene's.
        session.get(SceneTake, take_id).prompt_hash = take_hash(
            still_fields("An empty office corridor at night, its lights off.", None),
            "seedream5_pro",
        )
    judge, looked = _judge(passes=True)

    approved = stills_stage.rejudge_refused_stills(
        engine,
        board,
        1,
        "c",
        registry=REGISTRY,
        judge=judge,
        face_counter=_no_faces,
        measure=("faces",),
    )

    assert approved is False and looked == []
    with Session(engine) as session:
        row = session.get(SceneTake, take_id)
        assert row.status == "REJECTED" and row.approved_by is None
        assert row.failure_detail == LOCAL_STOP
    assert _rejudged_events(engine) == []
    film = {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [1]}
    assert stages._ladder_scenes(engine, board, film, registry=REGISTRY) == [1]
    assert "rejudged" not in film


def test_a_refusal_sent_to_her_rewrite_stays_hers_when_the_still_is_refused_again(engine, tmp_path):
    """The review of a0e27dc, finding 23 (87c05891 scenes 2/4/6/8): a still whose round had
    gone to the Director's rewrite (`REWRITE_PHRASE` first) was refused again for panels; the
    detail lost the phrase, `refusal_kind` read TECHNICAL and the serial re-rolled the very
    words her ladder held back. The take's job keeps its quality note: same verdict."""
    board = a_film(engine, tmp_path, scenes=1)
    take_id = _refused_by_local_checks(engine, tmp_path, board)
    marked = (
        f"{REWRITE_PHRASE}: runda nu se mai cumpără pe aceleași cuvinte, Directoarea le "
        f"rescrie; {LOCAL_STOP}"
    )
    remote = str(uuid4())
    with Session(engine) as session, session.begin():
        row = session.get(SceneTake, take_id)
        row.failure_detail = marked
        row.remote_task_id = remote
        session.add(
            GenerationJob(
                id=str(uuid4()),
                idempotency_key=uuid4().hex,
                payload_hash="a" * 64,
                provider="runpod",
                target="test",
                project_id=board,
                scene_id="1",
                attempt=1,
                operation="image",
                model="seedream5_pro",
                gpu="test",
                hourly_rate="0",
                remote_job_id=remote,
                status="COMPLETED",
                request={"prompt": "kept"},
                output={},
                accepted=False,
                quality_result="the gate's first refusal",
                created_at=utc_now(),
            )
        )
    judge, looked = _judge(passes=False, panels=True)

    approved = stills_stage.rejudge_refused_stills(
        engine,
        board,
        1,
        "c",
        registry=REGISTRY,
        judge=judge,
        face_counter=_no_faces,
        measure=("faces",),
    )

    assert approved is False and len(looked) == 1
    with Session(engine) as session:
        row = session.get(SceneTake, take_id)
        detail = str(row.failure_detail)
        job = session.scalar(select(GenerationJob).where(GenerationJob.remote_job_id == remote))
        assert job.quality_result == "the gate's first refusal" and job.accepted is False
    assert row.status == "REJECTED" and detail.startswith(REWRITE_PHRASE)
    assert "singură fotografie" in detail  # today's reasons follow the phrase
    assert "verificările locale" not in detail
    assert len(detail) <= 500
    assert refusal_kind(stills_stage.GATE_FAILURE_CODE, detail) == CONTENT_REFUSAL


def test_with_no_eyes_no_still_is_judged_again_and_none_loses_its_mark(engine, tmp_path):
    """The review of a0e27dc, finding 26: the shooting-sheet letter called the ladder with no
    registry; the gate's look answered «nu a fost privită», that non-answer replaced the
    still's refusal and its local-stop mark, and the still was never judged with eyes again."""
    board = a_film(engine, tmp_path, scenes=1)
    take_id = _refused_by_local_checks(engine, tmp_path, board)

    def unseen(engine, registry, path, plan, correlation_id, *, ffmpeg_path=None):
        return StillJudgement(
            status="NOT_RUN",
            verdict=None,
            detail_ro="nu a fost privită: niciun angajat nu are un model care vede",
            run_id=None,
            looked_by=None,
            image_width=None,
        )

    for registry, judge in (
        (None, stills_stage.judge_still),  # the real look, with no registry
        (Registry(ids=()), stills_stage.judge_still),
        (REGISTRY, unseen),  # a registry, and nobody with a model that sees
    ):
        approved = stills_stage.rejudge_refused_stills(
            engine,
            board,
            1,
            "c",
            registry=registry,
            judge=judge,
            face_counter=_no_faces,
            measure=("faces",),
        )
        assert approved is False
        with Session(engine) as session:
            row = session.get(SceneTake, take_id)
            assert row.status == "REJECTED" and row.failure_detail == LOCAL_STOP
    assert _rejudged_events(engine) == []

    # With eyes, the still is judged after all.
    judge, looked = _judge(passes=True)
    assert stills_stage.rejudge_refused_stills(
        engine,
        board,
        1,
        "c",
        registry=REGISTRY,
        judge=judge,
        face_counter=_no_faces,
        measure=("faces",),
    )


def test_the_days_registry_reaches_every_ladder_call_the_letter_included(
    engine, tmp_path, settings, monkeypatch
):
    """Finding 26's wiring: the walk and the shooting-sheet letter call the ladder with the
    day's registry and settings, never without them."""
    board = a_film(engine, tmp_path, scenes=1)
    calls: list[dict] = []

    def ladder(engine, storyboard_id, film, *, registry=None, settings=None):
        calls.append({"registry": registry, "settings": settings})
        return [1]

    monkeypatch.setattr(stages, "sheet_wiring", lambda *a: {})
    monkeypatch.setattr(
        stages,
        "_film_staircase",
        lambda *a: {
            "status": "WAITING",
            "refusal": "NEEDS_OWNER",
            "scenes": [1],
            "step": "stills",
            "reason": "Scena 1: controlul calității a refuzat imaginea.",
            "bought": [],
            "sheet": {"title": "Un film", "sheet_hash": "a" * 64, "steps": {}},
        },
    )
    monkeypatch.setattr(stages, "_ladder_scenes", ladder)

    stages._media_staircase(engine, settings, None, REGISTRY, [board], [], set(), "TEST")

    assert len(calls) >= 2, calls  # the summary's and the letter's
    assert all(call["registry"] is REGISTRY for call in calls), calls
    assert all(call["settings"] is settings for call in calls), calls
