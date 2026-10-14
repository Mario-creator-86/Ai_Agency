"""Kelvin's undelivered test shot is Sarah's work, with normal purchase gates retained."""

from uuid import uuid4

import pytest
from app.agents.models import AgentMessage
from app.media import assembler, scene_rewrite
from app.media.models import SceneTake
from app.models import DomainEvent
from app.providers.runpod.jobs import GenerationJob
from app.runbook import stages
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_director_rewrites_failed_scene import (  # noqa: F401 - fixture
    BRIEF,
    Agents,
    a_planned_film,
    agents_say,
    scene,
)
from test_director_rewrites_failed_scene import (
    studio as studio,
)


def failed_delivery(engine, tmp_path, *, with_hold=True):
    from test_film_costing import SEEDANCE

    board = a_planned_film(engine, tmp_path)
    state = assembler._motion_state(engine, board, capabilities=[SEEDANCE])
    with Session(engine) as session, session.begin():
        take = SceneTake(
            id=str(uuid4()),
            storyboard_id=board,
            scene_number=1,
            kind="test_shot",
            prompt_hash=assembler.take_hash(state["fields"][1], "seedance2_5"),
            model_id="seedance2_5",
            resolution="1080:1920",
            status="REFUSED",
            failure_code="RUNPOD.EXPIRED_UNDELIVERED",
            failure_detail="No clip delivered.",
            remote_task_id=str(uuid4()),
            credits_quoted=1,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(take)
        take_id = take.id
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
                operation="video",
                model=take.model_id,
                gpu="test",
                hourly_rate="0",
                remote_job_id=take.remote_task_id,
                status="FAILED",
                request={"prompt": "kept"},
                output={},
                error_code="EXPIRED_UNDELIVERED",
                created_at=utc_now(),
            )
        )
        if with_hold:
            append_event(
                session,
                assembler.MOTION_HOLD_EVENT,
                "storyboard",
                board,
                1,
                {
                    "scene_number": 1,
                    "holds": True,
                    "failure_kind": "UNKNOWN",
                    "reason": "Furnizorul nu a livrat clipul.",
                },
                str(uuid4()),
            )
    return board, take_id


def test_an_expired_take_goes_to_sarah_even_if_the_step_died_before_recording_its_hold(
    engine, tmp_path
):
    from test_film_costing import SEEDANCE

    board, _take = failed_delivery(engine, tmp_path, with_hold=False)
    state = assembler._motion_state(engine, board, capabilities=[SEEDANCE])
    assert state["memory"][1].hold_ro and "Directoarea" in state["memory"][1].hold_ro


def test_a_terminal_undelivered_clip_enters_the_existing_director_ladder(engine, tmp_path):
    board, _take = failed_delivery(engine, tmp_path)
    film = {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [1]}
    assert stages._ladder_scenes(engine, board, film) == [1]
    words = stages._held_words(engine, board, "cadrul de probă", [1])
    assert "Directoare" in words and "decizia Proprietarului" not in words
    film.update(step="test_shot", reason=words, sheet={"title": "Kelvin", "steps": {}})
    assert stages._sheet_letter(engine, board, film, None, str(uuid4())) is None
    with Session(engine) as session:
        assert not list(
            session.scalars(
                select(AgentMessage).where(
                    AgentMessage.to_agent_id.is_(None), AgentMessage.status == "OPEN"
                )
            )
        )


def test_sarah_authorizes_delivery_retry_without_inventing_a_prompt_rewrite(
    engine, tmp_path, studio
):
    board, take_id = failed_delivery(engine, tmp_path)
    before = scene(engine, board).prompt_json
    with Session(engine) as session:
        held_count = assembler._paid_attempts(
            list(
                session.scalars(
                    select(SceneTake).where(
                        SceneTake.storyboard_id == board, SceneTake.kind == "test_shot"
                    )
                )
            ),
            "shot",
        )
    agents = Agents(
        brief={
            **BRIEF,
            "action": "retry_delivery",
            "diagnosis": "No clip was delivered. This is a terminal delivery error, not visual QC.",
            "summary_ro": "Kael reia livrarea scenei; nu există încă un clip de judecat.",
        }
    )
    result = scene_rewrite.director_ladder(engine, agents_say(studio, agents), board, [1])
    assert result["rewritten"] == []
    assert result["recovered"][0]["resumed"] is True
    assert agents.briefs and not agents.rewrites
    assert scene(engine, board).prompt_json == before
    with Session(engine) as session:
        events = list(
            session.scalars(
                select(DomainEvent).where(
                    DomainEvent.event_type == assembler.DELIVERY_RETRY_EVENT,
                    DomainEvent.aggregate_id == board,
                )
            )
        )
        assert events and events[0].payload["take_id"] == take_id
        assert events[0].payload["decided_by"] == "director"
        assert session.get(SceneTake, take_id).status == "REFUSED"
        assert events[0].payload["paid_attempts"] == held_count
    # The expired row remains evidence, and her decision does not reset paid-attempt counts.
    before_memory = assembler.motion_plan(engine, board, capabilities=[])["scenes"][0]
    assert "decide Proprietarul" not in str(before_memory)


def test_the_staircase_resumes_to_the_normal_spending_approval_after_sarahs_decision(
    engine, tmp_path, studio, settings
):
    from test_film_costing import SEEDANCE, Account, Models, SpyVideo

    board, _take = failed_delivery(engine, tmp_path)
    account = Account(10_000)
    spy = SpyVideo("seedance2_5", account)
    agents = Agents(brief={**BRIEF, "action": "retry_delivery"})
    film = stages._film_staircase(
        engine,
        settings,
        agents_say(studio, agents),
        board,
        {
            "integration_id": None,
            "capabilities": [SEEDANCE],
            "image_adapter": None,
            "account": account,
            "adapter_for_model": Models(spy),
            "resolution": "1080p",
            "storage_root": tmp_path / "media",
        },
        "TEST",
        str(uuid4()),
    )
    assert film["director_ladder"][0]["recovered"][0]["resumed"]
    # TEST and the ask-me rule still require the existing spending approval.
    assert film["status"] == "ASKED", film
    assert film["approval_id"]
    assert account.shots == 0


def test_an_unanswered_submission_is_not_released_as_an_expired_delivery(engine, tmp_path):
    board, take_id = failed_delivery(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.get(SceneTake, take_id).failure_code = assembler.UNANSWERED_FAILURE_CODE
    assert (
        stages._ladder_scenes(
            engine, board, {"status": "WAITING", "refusal": "NEEDS_OWNER", "scenes": [1]}
        )
        == []
    )


def test_retry_delivery_cannot_bypass_a_quality_rewrite():
    schema = scene_rewrite.brief_schema(("motion",))
    with pytest.raises(ValueError):
        schema.model_validate({**BRIEF, "action": "retry_delivery"})


def test_the_register_names_delivery_recovery_without_claiming_a_prompt_rewrite():
    from app.events_feed import _brief_words

    words, _bubble = _brief_words(
        {"scene_index": 2, "action": "retry_delivery", "resumed": True},
        "Sarah",
        " din Kelvin",
        "Kael",
    )
    assert "livrării" in words and "rescriere" not in words


def test_an_in_flight_journal_never_authorizes_a_duplicate(engine, tmp_path, studio):
    board, take_id = failed_delivery(engine, tmp_path)
    with Session(engine) as session, session.begin():
        session.scalar(
            select(GenerationJob).where(GenerationJob.project_id == board)
        ).status = "RUNNING"
    agents = Agents(brief={**BRIEF, "action": "retry_delivery"})
    result = scene_rewrite.director_ladder(engine, agents_say(studio, agents), board, [1])
    assert not result["recovered"]
    assert "jurnalul" in result["not_rewritten"][0]["reason"]
    with Session(engine) as session:
        assert not list(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == assembler.DELIVERY_RETRY_EVENT)
            )
        )


def test_the_media_summary_waits_for_the_director_instead_of_asking_the_owner(
    engine, tmp_path, settings, monkeypatch
):
    board, _take = failed_delivery(engine, tmp_path)
    monkeypatch.setattr(stages, "sheet_wiring", lambda *a: {})
    monkeypatch.setattr(
        stages,
        "_film_staircase",
        lambda *a: {
            "status": "WAITING",
            "refusal": "NEEDS_OWNER",
            "scenes": [1],
            "step": "test_shot",
            "reason": "Directoarea preia livrarea scenei 1.",
            "bought": [],
            "sheet": {"title": "Kelvin", "steps": {}},
        },
    )
    result = stages._media_staircase(engine, settings, None, None, [board], [], set(), "TEST")
    assert "Directoarea preia" in result["reason"]
    assert "așteaptă Proprietarul" not in result["reason"]


def test_the_old_technical_owner_question_closes_but_a_spending_approval_stays(
    engine, tmp_path, studio
):
    from app.agents.messages import post_message

    board, _take = failed_delivery(engine, tmp_path)
    ids = []
    with Session(engine) as session, session.begin():
        for approval in (None, "real-spending-approval"):
            message = post_message(
                session,
                intent="REQUEST_REVIEW",
                subject=str(uuid4()),
                from_agent_id=studio["agents"]["Director"],
                to_agent_id=None,
                body={
                    "kind": "owner_shooting_sheet",
                    "storyboard_id": board,
                    "step": "test_shot",
                    "status": "NEEDS_OWNER",
                    "approval_id": approval,
                },
                body_text="Foaia de filmare așteaptă decizia ta.",
            )
            ids.append(message.id)
    agents = Agents(brief={**BRIEF, "action": "retry_delivery"})
    scene_rewrite.director_ladder(engine, agents_say(studio, agents), board, [1])
    with Session(engine) as session:
        assert session.get(AgentMessage, ids[0]).status == "RESOLVED"
        assert session.get(AgentMessage, ids[1]).status == "OPEN"


def test_a_changed_prompt_during_her_brief_leaves_the_delivery_held(engine, tmp_path, studio):
    from app.media.models import StoryboardScene

    board, _take = failed_delivery(engine, tmp_path)

    class ChangingAgents(Agents):
        async def generate(self, model, prompt, **kwargs):
            if '"scene-brief"' in prompt:
                with Session(engine) as session, session.begin():
                    row = session.scalar(
                        select(StoryboardScene).where(StoryboardScene.storyboard_id == board)
                    )
                    row.prompt_json = {**row.prompt_json, "subject": "a changed scene"}
            return await super().generate(model, prompt, **kwargs)

    agents = ChangingAgents(brief={**BRIEF, "action": "retry_delivery"})
    result = scene_rewrite.director_ladder(engine, agents_say(studio, agents), board, [1])
    assert not result["recovered"]
    assert "Promptul scenei s-a schimbat" in result["not_rewritten"][0]["reason"]
