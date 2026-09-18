"""Starting over deletes what the agents did and keeps what the Owner configured.

What is asserted: the history tables are empty and the media folders gone; the workforce,
channels, character bibles, authorised sites and policy are untouched; no foreign key is
left dangling; the ledger read through the API starts at the reset line and shows nothing
from before it; the backup made by the script is a readable copy.
"""

from __future__ import annotations

import sqlite3
from uuid import uuid4

from app.agents.memory import remember
from app.agents.messages import letters_for_owner, open_messages, post_message
from app.agents.models import Agent, AgentMessage, AgentRun, MemoryRecord, Role
from app.agents.services import seed_initial_workforce
from app.factual.models import TopicIdea
from app.maintenance import RESET_EVENT, ledger_floor, reset_history
from app.media.models import CharacterBible
from app.media.services import seed_default_character_bibles
from app.models import ApprovalRequest, DomainEvent, OwnerPolicy
from app.publishing.models import ChannelRecord
from app.publishing.services import seed_default_channels
from app.research.models import ResearchAllowedHost
from app.services import read_events, request_approval, utc_now
from app.story.models import ContinuityState
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session


def a_studio_with_history(engine, tmp_path):
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    media = tmp_path / "media"
    (media / "board-1").mkdir(parents=True)
    (media / "board-1" / "final_short_9_16.mp4").write_bytes(b"0" * 64)
    with Session(engine) as session, session.begin():
        sarah = session.scalar(
            select(Agent).join(Role, Agent.role_id == Role.id).where(Role.name == "Director")
        )
        post_message(
            session,
            intent="STATUS",
            subject="media: COMPLETED — 1 videoclip randat",
            body_text="Gata. Kael",
            from_agent_id=sarah.id,
        )
        post_message(
            session,
            intent="ESCALATE",
            subject="Am nevoie de decizia ta: prețul modelului",
            body_text="Cât costă o rulare? Sarah",
            from_agent_id=sarah.id,
            to_owner=True,
        )
        remember(
            session,
            memory_class="AGENT_OPINION",
            content="The film had no story.",
            source_type="run",
            agent_id=sarah.id,
        )
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=sarah.id,
                task_type="director_review",
                objective="review",
                prompt_template_version="v1",
                model_name="m",
                provider_name="p",
                status="SUCCEEDED",
                correlation_id=str(uuid4()),
                started_at=utc_now(),
                context_json={},
            )
        )
        # The serial's memory: a canon summary that names an episode the reset deletes.
        session.add(
            ContinuityState(
                id=1,
                version=2,
                canon_episode_number=1,
                threads_json=[{"id": "T1", "text": "Who moved the plant?", "opened_in": 1}],
                recurring_json=["the plant"],
                summaries_json=[{"episode_number": 1, "episode_id": str(uuid4())}],
                updated_at=utc_now(),
            )
        )
        # What the agents asked the Owner while the studio was SUPERVISED. It is their
        # request, not his configuration, so it goes with the films it was about.
        request_approval(
            session,
            "publishing.public_publish",
            "T3",
            "publisher",
            subject="a-film-that-will-not-exist",
            evidence="Un film → Canal A (private)",
        )
        session.add(
            TopicIdea(
                id=str(uuid4()),
                title="Descoperire Robotică Autonomă",
                topic="demo",
                angle="a",
                target_audience="g",
                novelty_score=0.5,
                status="SELECTED",
                created_at=utc_now(),
            )
        )
    return media


def test_the_history_goes_and_the_configuration_stays(engine, tmp_path):
    media = a_studio_with_history(engine, tmp_path)
    with Session(engine) as session:
        before = {
            "agents": session.scalar(select(func.count(Agent.id))),
            "channels": session.scalar(select(func.count(ChannelRecord.id))),
            "bibles": session.scalar(select(func.count(CharacterBible.id))),
            "hosts": session.scalar(select(func.count()).select_from(ResearchAllowedHost)),
            "events": session.scalar(select(func.count(DomainEvent.sequence))),
        }
        assert before["events"] > 10 and session.scalar(select(func.count(AgentMessage.id))) == 2

    result = reset_history(engine, media_root=media)

    assert result["deleted"]["agent_message"] == 2
    assert result["deleted"]["agent_run"] == 1 and result["deleted"]["topic_idea"] == 1
    assert result["deleted"]["memory_record"] == 1 and result["media_folders"] == 1
    # A yes about a film that no longer exists is an authority nothing should be able to
    # spend, so the questions go with the history they were about.
    assert result["deleted"]["owner_approval_request"] == 1
    # Canon goes with the episodes it summarises, or the serial would remember a day
    # whose episode no longer exists.
    assert result["deleted"]["continuity_state"] == 1
    assert not any(media.iterdir())
    with Session(engine) as session:
        for model in (
            AgentMessage,
            AgentRun,
            MemoryRecord,
            TopicIdea,
            ContinuityState,
            ApprovalRequest,
        ):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert session.scalar(select(func.count(Agent.id))) == before["agents"] == 8
        assert session.scalar(select(func.count(ChannelRecord.id))) == before["channels"] == 2
        assert session.scalar(select(func.count(CharacterBible.id))) == before["bibles"]
        assert (
            session.scalar(select(func.count()).select_from(ResearchAllowedHost)) == before["hosts"]
        )
        # The guards are back: the running studio still cannot delete its history.
        assert {
            row[0]
            for row in session.execute(
                text("SELECT name FROM sqlite_master WHERE type='trigger'")
            ).all()
        } >= {"domain_event_no_delete", "command_record_no_delete", "tool_receipt_no_delete"}
        assert session.get(OwnerPolicy, 1) is not None
        assert all(a.runtime_state == "IDLE" for a in session.scalars(select(Agent)))
        assert open_messages(session, inbox=True) == []
        assert session.execute(text("PRAGMA foreign_key_check")).fetchall() == []
        # The events configuration rows cite are still there, behind the reset line; the
        # rest of the history is not.
        remaining = session.scalar(select(func.count(DomainEvent.sequence)))
        assert 0 < remaining < before["events"]
        assert ledger_floor(session) == session.scalar(select(func.max(DomainEvent.sequence)))
    assert letters_for_owner(engine) == []


def test_the_ledger_read_through_the_api_starts_at_the_reset_line(
    client, headers, engine, tmp_path
):
    media = a_studio_with_history(engine, tmp_path)
    reset_history(engine, media_root=media)

    page = read_events(engine, 0, 50)
    assert [e["event_type"] for e in page["events"]] == [RESET_EVENT]
    assert page["events"][0]["payload"]["messages"] == 2 and page["has_more"] is False
    # The page reads the same ledger, from the same line, and a cursor before it is ignored.
    listed = client.get("/api/v1/events?after=0&limit=50", headers=headers).json()
    assert [e["event_type"] for e in listed["events"]] == [RESET_EVENT]
    with Session(engine) as session, session.begin():
        sarah = session.scalar(
            select(Agent).join(Role, Agent.role_id == Role.id).where(Role.name == "Director")
        )
        post_message(session, intent="STATUS", subject="A fresh start", from_agent_id=sarah.id)
    after = read_events(engine, listed["next_cursor"], 50)
    assert [e["event_type"] for e in after["events"]] == ["agent.message_posted"]


def test_the_script_backs_the_database_up_as_a_readable_copy(tmp_path):
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "reset_history_script",
        Path(__file__).resolve().parents[1] / "scripts" / "reset_history.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    source = tmp_path / "studio.db"
    with sqlite3.connect(source) as db:
        db.execute("CREATE TABLE t (x INTEGER)")
        db.execute("INSERT INTO t VALUES (7)")
    saved = module.backup(source)
    assert saved.parent == tmp_path / "backups" and saved.name.startswith("studio-")
    with sqlite3.connect(saved) as copy:
        assert copy.execute("SELECT x FROM t").fetchone() == (7,)
    assert module.database_path("sqlite:///data/studio.db") == Path("data/studio.db")
    assert module.database_path("postgresql://x") is None
    assert module.studio_is_running("127.0.0.1", 1) is False
