"""The page's «Creează un caz demo» never feeds the daily run's topic pool (PAGE-09).

The demo fixture used to write a PROPOSED topic with novelty 0.95: the highest score in the
pool, so the day's research spent tokens on it first and the selection would choose it the
moment one of its claims was marked SUPPORTED. Demo rows now carry their own status, DEMO,
and no stage of the day reads them.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from app.factual.models import FactualClaim, TopicIdea
from app.integrations.vault import CredentialVault
from app.providers.registry import ProviderRegistry
from app.runbook import stages
from app.runbook.stages import build_stage_runners
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session


@pytest.fixture
def runners(engine, settings):
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    return build_stage_runners(engine, settings, vault, ProviderRegistry())


def _real_topic(engine, *, novelty: float = 0.4) -> str:
    topic_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title="Un subiect real",
                topic="Test",
                angle="Test",
                target_audience="test",
                novelty_score=novelty,
                status="PROPOSED",
                created_at=utc_now(),
            )
        )
        session.add(
            FactualClaim(
                id=str(uuid4()),
                topic_id=topic_id,
                claim_text="O afirmație verificată.",
                claim_type="SCIENTIFIC_FACT",
                importance="CRITICAL",
                status="SUPPORTED",
                confidence=0.9,
                created_at=utc_now(),
            )
        )
    return topic_id


def _demo_topic(client, headers) -> str:
    response = client.post("/api/v1/media/storyboards/demo-fixture", headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["topic_id"]


def test_the_demo_fixture_is_written_as_a_demo_topic_not_a_proposal(client, headers, engine):
    topic_id = _demo_topic(client, headers)
    with Session(engine) as session:
        assert session.get(TopicIdea, topic_id).status == "DEMO"


def test_the_selection_never_chooses_a_demo_topic(client, headers, engine, runners):
    """Even with a SUPPORTED claim and the highest novelty, the demo is not produced."""
    demo = _demo_topic(client, headers)
    with Session(engine) as session, session.begin():
        for claim in session.scalars(select(FactualClaim).where(FactualClaim.topic_id == demo)):
            claim.status = "SUPPORTED"
    real = _real_topic(engine)

    outcome = runners["selection"]()

    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["topic_id"] == real
    with Session(engine) as session:
        assert session.get(TopicIdea, demo).status == "DEMO"


def test_the_research_never_gathers_pages_for_a_demo_topic(
    client, headers, engine, settings, monkeypatch
):
    demo = _demo_topic(client, headers)
    real = _real_topic(engine)
    asked: list[str] = []

    def fake_gather(_engine, _registry, _settings, topic_id, _correlation, *, limit):
        asked.append(topic_id)
        return {"topic_id": topic_id}

    monkeypatch.setattr(stages, "gather_sources", fake_gather)
    stages._gather_for_candidates(engine, ProviderRegistry(), settings)

    assert real in asked
    assert demo not in asked


def test_a_demo_topic_does_not_fill_the_idea_pool(client, headers, engine):
    """The pool count that decides whether new ideas are asked for ignores demo rows."""
    for _ in range(stages.IDEA_POOL_TARGET):
        _demo_topic(client, headers)
    with Session(engine) as session:
        pool = session.scalar(
            select(TopicIdea.id).where(TopicIdea.status.in_(("PROPOSED", "RESEARCHED"))).limit(1)
        )
    assert pool is None
