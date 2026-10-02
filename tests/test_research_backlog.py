"""Research never starves a new topic behind the studio's old, unverifiable backlog.

Found on a copy of the Owner's studio (2026-10-02, final audit): 61 claims from September sat
UNVERIFIED, refused by the Fact Checker day after day. The stage verified the 24 OLDEST every
day, so a new topic's claims never reached the Fact Checker, no topic had a SUPPORTED claim,
and the autonomous day ended "nimic adevărat de produs azi" for ever. And the sources still
to be read were found among the first 50 rows of the table, in no order: past 50 sources, a
page read for a new topic was never extracted at all.
"""

from __future__ import annotations

from uuid import uuid4

from app.factual.models import FactualClaim, SourceSnapshot, TopicIdea
from app.factual.services import ingest_source_snapshot
from app.providers.registry import ProviderRegistry
from app.runbook import stages
from app.services import utc_now
from sqlalchemy.orm import Session


class _AnyModel:
    async def health_check(self):  # pragma: no cover - never asked
        return None


def _registry() -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register("any", _AnyModel())
    return registry


def _topic(engine, title: str) -> str:
    topic_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title=title,
                topic="Astronomy",
                angle="an angle",
                target_audience="science_enthusiasts",
                novelty_score=0.5,
                status="PROPOSED",
                created_at=utc_now(),
            )
        )
    return topic_id


def _source(engine, topic_id: str, n: int) -> str:
    return ingest_source_snapshot(
        engine,
        url=f"https://www.iana.org/help/example-domains?page={n}",
        title=f"Page {n}",
        publisher="www.iana.org",
        author=None,
        raw_content=f"Page {n} says something true about the sky.",
        credibility_score=0.9,
        correlation_id=str(uuid4()),
        topic_id=topic_id,
    )["id"]


def _claim(engine, source_id: str, topic_id: str, created_at: str) -> str:
    claim_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            FactualClaim(
                id=claim_id,
                source_id=source_id,
                topic_id=topic_id,
                claim_text="The sky is observed in infrared.",
                importance="CRITICAL",
                status="UNVERIFIED",
                created_at=created_at,
            )
        )
    return claim_id


def test_a_new_topics_claims_are_verified_before_the_old_refused_backlog(engine, monkeypatch):
    old_topic = _topic(engine, "An old topic")
    old_source = _source(engine, old_topic, 0)
    backlog = [
        _claim(engine, old_source, old_topic, f"2026-09-12T08:{n:02d}:00+00:00")
        for n in range(stages.VERIFY_BATCH + 6)
    ]
    new_topic = _topic(engine, "Today's topic")
    new_source = _source(engine, new_topic, 1)
    fresh = _claim(engine, new_source, new_topic, utc_now())

    asked: list[str] = []
    monkeypatch.setattr(stages, "agent_extract_claims", lambda *a, **k: None)
    monkeypatch.setattr(
        stages, "agent_verify_claim", lambda e, r, claim_id, c: asked.append(claim_id)
    )
    monkeypatch.setattr(stages, "_gather_for_candidates", lambda *a, **k: [])

    stages._research_and_verification(engine, _registry(), None)

    assert fresh in asked, "the new topic's claim waited behind the refused backlog"
    assert len(asked) == stages.VERIFY_BATCH
    assert set(asked) - {fresh} <= set(backlog)


def test_a_source_past_the_fiftieth_row_is_still_read(engine, monkeypatch):
    topic = _topic(engine, "A topic with many pages")
    for n in range(60):
        source_id = _source(engine, topic, n)
        _claim(engine, source_id, topic, f"2026-09-12T09:{n % 60:02d}:00+00:00")
    new_source = _source(engine, _topic(engine, "Today's topic"), 99)
    with Session(engine) as session:
        assert session.query(SourceSnapshot).count() == 61

    read: list[str] = []
    monkeypatch.setattr(
        stages, "agent_extract_claims", lambda e, r, source_id, c: read.append(source_id)
    )
    monkeypatch.setattr(stages, "agent_verify_claim", lambda *a, **k: None)
    monkeypatch.setattr(stages, "_gather_for_candidates", lambda *a, **k: [])

    stages._research_and_verification(engine, _registry(), None)

    assert read == [new_source]


def _script(engine, topic_id: str, verdict: str | None) -> str:
    from app.factual.models import ScriptDraft, StoryReview

    script_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                title="A refused story",
                voiceover_full_text="Words.",
                scenes_json=[],
                status="VERIFIED_PASS",
                created_at=utc_now(),
            )
        )
        session.flush()
        if verdict is not None:
            session.add(
                StoryReview(
                    id=str(uuid4()), script_id=script_id, verdict=verdict, created_at=utc_now()
                )
            )
    return script_id


def test_the_day_never_says_a_refused_script_waits_for_the_owners_approval(engine):
    """On the Owner's copy, every day ended «Un scenariu așteaptă aprobarea ta înainte de
    storyboard» because 28 drafts of September sat VERIFIED_PASS - every one of them refused
    by the story review or superseded by a newer draft. Nothing waited for him."""
    topic = _topic(engine, "A refused topic")
    _script(engine, topic, None)  # an older draft, superseded
    _script(engine, topic, "REJECT")

    outcome = stages._script_and_storyboard(engine, _registry())

    assert "așteaptă aprobarea ta" not in outcome["reason"], outcome["reason"]


def test_a_passed_script_the_director_could_not_approve_does_wait_for_him(engine):
    topic = _topic(engine, "A passed topic")
    _script(engine, topic, "PASS")

    outcome = stages._script_and_storyboard(engine, _registry())

    assert "Un scenariu așteaptă aprobarea ta înainte de storyboard." in outcome["reason"]
