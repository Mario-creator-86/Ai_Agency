"""The Director's weekly performance review, with a scripted model.

Nothing here claims a real model answered. What is asserted is the wiring the Owner ordered:
a week with nothing published is reported as such and costs nothing; a week with published
work puts the measured numbers in front of the Director and files her answer where it does
work — HANDOFF indications to the sound and the video departments (which enter their every
run until resolved) and a STATUS report in her inbox; a week is reviewed at most once by the
clock; and the worker's dispatch table knows the task.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentMessage, AgentRun, MemoryRecord, ModelRecord, Role
from app.agents.services import seed_initial_workforce
from app.analytics.models import AnalyticsSnapshot
from app.media.models import MediaAsset
from app.media.services import seed_default_character_bibles
from app.models import OwnerPolicy
from app.providers.registry import ProviderRegistry
from app.publishing.models import ChannelRecord, PublicationRecord
from app.publishing.services import seed_default_channels
from app.runbook.weekly import WEEKLY_REVIEW_TASK, execute_weekly_review, weekly_digest
from app.services import append_event, utc_now
from app.workflows.worker import NonRetryable, build_task_handlers
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_agent_identity import ScriptedModel

REVIEW_JSON = {
    "verdict": (
        "„Test publication” a ținut publicul 62% din video, cu CTR 8% — peste pragul "
        "nostru; publicul a rămas până la capăt."
    ),
    "sound": "Păstrează vocea caldă; rarind ritmul la cifre. Fără schimbare de model.",
    "video": "Ținem modelul actual; alternativa mai ieftină are reținere mai slabă.",
    "topics": "Urmărim roboțica autonomă; scădem subiectele cu retenție sub 40%.",
    "budget_request_amount_usd": 20,
    "budget_request_justification": (
        "Planul măsurat necesită încă 20 USD pentru extrageri suplimentare de surse."
    ),
    "escalate_to_owner": "",
}
REVIEW_ANSWER = json.dumps(REVIEW_JSON, ensure_ascii=False)


@pytest.fixture
def staffed(engine):
    """The seeded studio: roles with contracts, agents, bibles linked, models available."""
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        agents = {
            role.name: agent
            for agent, role in session.execute(
                select(Agent, Role).join(Role, Agent.role_id == Role.id)
            ).all()
        }
        provider_id = next(iter(agents.values())).provider_id
        session.expunge_all()
    return {"agents": agents, "provider_id": provider_id}


def registry_with(staffed, answer):
    registry = ProviderRegistry()
    model = ScriptedModel(lambda _prompt: answer)
    registry.register(staffed["provider_id"], model)
    return registry, model


@pytest.fixture
def channel(engine):
    seed_default_channels(engine)
    with Session(engine) as session:
        channel = session.scalar(
            select(ChannelRecord).where(ChannelRecord.channel_type == "MAIN_FACTUAL")
        )
        return channel.id


def make_published(engine, channel_id, *, title="Test publication", remote="yt_real_abc"):
    """A real publication the platform is serving, with one measured snapshot."""
    publication_id = str(uuid4())
    asset_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{asset_id}/final_short_9_16.mp4",
                file_size_bytes=1024,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=45.0,
                provider_name="STUDIO_INTERNAL",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=utc_now(),
                event_id=None,
            )
        )
        session.flush()
        event = append_event(
            session,
            "publishing.intent_created",
            "publication_record",
            publication_id,
            1,
            {},
            str(uuid4()),
        )
        session.add(
            PublicationRecord(
                id=publication_id,
                channel_id=channel_id,
                media_asset_id=asset_id,
                title=title,
                description="",
                tags_json=[],
                privacy_status="private",
                status="PUBLISHED",
                idempotency_key=str(uuid4()),
                remote_video_id=remote,
                remote_url=None,
                scheduled_publish_time=None,
                published_at=utc_now(),
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
        session.add(
            AnalyticsSnapshot(
                id=str(uuid4()),
                publication_id=publication_id,
                channel_id=channel_id,
                window="LIFETIME",
                views=1000,
                watch_time_seconds=28000.0,
                average_view_percentage=62.0,
                impressions=12000,
                ctr_percentage=8.0,
                likes=120,
                comments=9,
                shares=4,
                subscribers_gained=15,
                subscribers_lost=2,
                raw_metrics_json={"provider": "TEST"},
                snapshot_at=utc_now(),
                event_id=None,
            )
        )
    return publication_id


def test_a_week_with_nothing_published_reports_it_and_costs_no_tokens(engine, staffed):
    digest = weekly_digest(engine)
    assert digest["anything_published"] is False
    registry, model = registry_with(staffed, REVIEW_ANSWER)
    result = execute_weekly_review(engine, registry)
    assert result["status"] == "SKIPPED"
    assert model.calls == []
    with Session(engine) as session:
        report = session.scalar(select(AgentMessage).where(AgentMessage.to_agent_id.is_(None)))
        assert report is not None and "nimic publicat" in report.subject


def test_the_review_reaches_the_departments_as_instructions(engine, staffed, channel):
    make_published(engine, channel)
    digest = weekly_digest(engine)
    assert digest["anything_published"] is True
    assert digest["per_channel"]["Main Channel A - Factual Shorts"]["views"] == 1000

    registry, model = registry_with(staffed, REVIEW_ANSWER)
    result = execute_weekly_review(engine, registry)
    assert result["status"] == "COMPLETED", result
    assert result["instructions_filed"] == 4
    assert result["budget_requested"] is True
    # The Director saw the measured numbers, not a summary of them.
    assert "1000 vizualizări" in model.calls[0]["prompt"]
    # The run announces itself to the office in words, never as raw JSON.
    assert not any("verdict" in call.get("bubble", "") for call in model.calls)

    with Session(engine) as session:
        sarah_id = staffed["agents"]["Director"].id
        handoffs = session.scalars(
            select(AgentMessage).where(AgentMessage.intent == "HANDOFF")
        ).all()
        by_department = {}
        for message in handoffs:
            assert message.from_agent_id == sarah_id
            assert message.status == "OPEN"
            by_department[message.to_agent_id] = message
        assert set(by_department) == {
            staffed["agents"]["VoiceArtist"].id,
            staffed["agents"]["VideoEditor"].id,
            staffed["agents"]["LeadResearcher"].id,
            staffed["agents"]["ScriptWriter"].id,
        }
        assert (
            by_department[staffed["agents"]["VoiceArtist"].id].body_json["instructions"]
            == REVIEW_JSON["sound"]
        )
        assert (
            by_department[staffed["agents"]["LeadResearcher"].id].body_json["instructions"]
            == REVIEW_JSON["topics"]
        )
        # The budget request goes to the Accountant, with the amount and the reason.
        request = session.scalar(select(AgentMessage).where(AgentMessage.intent == "REQUEST_INFO"))
        assert request is not None
        assert request.to_agent_id == staffed["agents"]["Accountant"].id
        assert request.body_json["budget_request"] is True
        assert request.body_json["amount_usd"] == 20
        assert REVIEW_JSON["budget_request_justification"] in request.body_json["justification"]
        # The review itself lands in the Director's inbox, in full.
        report = session.scalar(select(AgentMessage).where(AgentMessage.to_agent_id.is_(None)))
        assert report is not None and report.subject.startswith("Revizia săptămânală")
        assert REVIEW_JSON["verdict"] in report.body_json["review"]["verdict"]
        # A direction the Director set is strategy: it stays with her.
        strategy = session.scalar(
            select(MemoryRecord).where(MemoryRecord.memory_class == "STRATEGY")
        )
        assert strategy is not None and REVIEW_JSON["topics"][:40] in strategy.content
        run = session.scalar(select(AgentRun).where(AgentRun.task_type == WEEKLY_REVIEW_TASK))
        assert run is not None and run.status == "SUCCEEDED"

    # The clock reviews a week once; the guard is what stops the scheduled job from
    # repeating the spend within the same week. A manual re-run later goes through a new
    # week or an explicit Owner decision, not through this path.
    second = execute_weekly_review(engine, registry)
    assert second["status"] == "SKIPPED" and "deja revizuită" in second["reason"]


def test_an_answer_that_breaks_the_schema_files_nothing(engine, staffed, channel):
    make_published(engine, channel)
    registry, model = registry_with(staffed, "Am revizuit săptămâna și totul e bine, cred.")
    result = execute_weekly_review(engine, registry)
    assert result["status"] == "FAILED" and "schema" in result["reason"]
    with Session(engine) as session:
        remaining = session.scalars(select(AgentMessage)).all()
        assert remaining == []


def test_the_accountant_answers_a_budget_request_at_the_close(engine, staffed, channel):
    from app.economy.accountant import reconcile_day

    make_published(engine, channel)
    registry, _ = registry_with(staffed, REVIEW_ANSWER)
    assert execute_weekly_review(engine, registry)["status"] == "COMPLETED"

    close_registry, close_model = registry_with(
        staffed,
        json.dumps(
            {
                "summary": "Ziua e închisă.",
                "recommendations": [],
                "holds": [],
                "continue_spending": True,
            }
        ),
    )
    outcome = reconcile_day(engine, close_registry)
    assert outcome["intent"] == "ESCALATE"
    assert outcome["budget_requests"][0]["amount_usd"] == 20
    assert close_model.calls  # the Accountant ran; the request text reached her inbox earlier
    with Session(engine) as session:
        request = session.scalar(select(AgentMessage).where(AgentMessage.intent == "REQUEST_INFO"))
        assert request.status == "RESOLVED"
        assert "Numai Owner-ul stabilește bugetul" in request.resolution
        close = session.get(AgentMessage, outcome["message_id"])
        assert close.body_json["budget_requests"][0]["justification"].startswith("Planul măsurat")


def test_the_worker_dispatch_table_knows_the_weekly_review(engine, settings, staffed):
    registry, _ = registry_with(staffed, REVIEW_ANSWER)
    handlers = build_task_handlers(engine, settings, None, None, registry)
    assert WEEKLY_REVIEW_TASK in handlers

    without = build_task_handlers(engine, settings, None, None, None)
    with pytest.raises(NonRetryable):
        without[WEEKLY_REVIEW_TASK]({"id": str(uuid4()), "payload": {}})
