"""The runbook's stages, with real work behind them.

Before this, `execute_daily_run` walked twelve stages and nothing in the application supplied the
work for any of them: every run recorded preflight and then eleven SKIPPED. The runbook was
truthful and idle.

These tests hold the wiring to two things. First, that each stage does the real operation against
the real services — a claim is verified by an agent, a file is measured by ffprobe, a publication
passes the same five-point gate as a manual one. Second, and just as important, that a stage which
cannot run says so instead of reporting a success it did not have: the distinction between
COMPLETED with a count of zero and SKIPPED with a reason is the whole difference between "we
looked and there was nothing" and "we could not look".
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from app.factual.models import FactualClaim, TopicIdea
from app.factual.services import TopicNotProducible, select_topic
from app.providers.registry import ProviderRegistry
from app.runbook.stages import build_stage_runners
from app.services import utc_now
from sqlalchemy.orm import Session


@pytest.fixture
def empty_registry() -> ProviderRegistry:
    """A registry with no language model, as a studio has before any provider is verified."""
    return ProviderRegistry()


@pytest.fixture
def runners(engine, settings, empty_registry):
    from pathlib import Path

    from app.integrations.vault import CredentialVault

    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    return build_stage_runners(engine, settings, vault, empty_registry)


def _topic(engine, *, status: str = "PROPOSED") -> str:
    topic_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title="Un subiect de probă",
                topic="Test",
                angle="Test",
                target_audience="test",
                novelty_score=0.9,
                status=status,
                created_at=utc_now(),
            )
        )
    return topic_id


def _claim(engine, topic_id: str, *, status: str) -> str:
    claim_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            FactualClaim(
                id=claim_id,
                topic_id=topic_id,
                claim_text="O afirmație de probă.",
                claim_type="SCIENTIFIC_FACT",
                importance="CRITICAL",
                status=status,
                confidence=0.9,
                created_at=utc_now(),
            )
        )
    return claim_id


# ------------------------------------------------------------------ the two outcomes --


def test_a_stage_that_cannot_run_is_skipped_with_the_reason(runners):
    """No language model means the agent stages could not look, not that they found nothing."""
    for name in ("research_and_verification", "script_and_storyboard", "serial_queue"):
        outcome = runners[name]()
        assert outcome["status"] == "SKIPPED", name
        assert "model de limbaj" in outcome["reason"], name


def test_a_stage_that_ran_and_found_nothing_is_completed_with_a_count(runners, engine):
    """Looking and finding nothing is work done, and must not read as work skipped."""
    outcome = runners["edit_and_qc"]()
    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["checked"] == 0

    selection = runners["selection"]()
    assert selection["status"] == "COMPLETED"
    assert "nimic adevărat de produs" in selection["reason"]


def test_publishing_is_skipped_when_no_channel_is_connected(runners):
    outcome = runners["publish"]()
    assert outcome["status"] == "SKIPPED"
    assert "Niciun canal YouTube conectat" in outcome["reason"]


def test_performance_intake_is_skipped_without_an_analytics_account(runners):
    outcome = runners["performance_intake"]()
    assert outcome["status"] == "SKIPPED"
    assert "analytics" in outcome["reason"]


# --------------------------------------------------------------------- the selection --


def test_selection_takes_a_topic_that_has_something_verified_to_say(runners, engine):
    topic_id = _topic(engine)
    _claim(engine, topic_id, status="SUPPORTED")

    outcome = runners["selection"]()

    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["topic_id"] == topic_id
    with Session(engine) as session:
        assert session.get(TopicIdea, topic_id).status == "SELECTED"


def test_selection_refuses_a_topic_whose_claims_are_all_unverified(engine):
    """Selecting it would only move the refusal one stage later, and imply the day had work."""
    topic_id = _topic(engine)
    _claim(engine, topic_id, status="UNVERIFIED")

    with pytest.raises(TopicNotProducible, match="SUPPORTED"):
        select_topic(engine, topic_id, str(uuid4()))


def test_selecting_the_same_topic_twice_does_not_record_a_second_decision(engine):
    from app.models import DomainEvent
    from sqlalchemy import func, select

    topic_id = _topic(engine)
    _claim(engine, topic_id, status="SUPPORTED")

    select_topic(engine, topic_id, str(uuid4()))
    select_topic(engine, topic_id, str(uuid4()))

    with Session(engine) as session:
        events = session.scalar(
            select(func.count())
            .select_from(DomainEvent)
            .where(
                DomainEvent.event_type == "factual.topic_selected",
                DomainEvent.aggregate_id == topic_id,
            )
        )
    assert events == 1


def test_selection_leaves_an_existing_production_alone(runners, engine):
    """A day that starts with work in progress does not start a second piece of work."""
    first = _topic(engine, status="SELECTED")
    second = _topic(engine)
    _claim(engine, second, status="SUPPORTED")

    outcome = runners["selection"]()

    assert outcome["artefacts"]["topic_id"] == first
    with Session(engine) as session:
        assert session.get(TopicIdea, second).status == "PROPOSED"


# ------------------------------------------------------------- research, for real --


class _ScriptedModel:
    """A language model that answers exactly what the agent pipeline asks it for.

    It is not pretending to be intelligent. It returns one extraction and one verdict, and the
    verdict's evidence quote is copied out of the source — which is the part that matters, because
    the pipeline rejects any verdict whose quote does not appear in the source verbatim. A stub
    that could not quote correctly would prove nothing about the wiring.
    """

    def __init__(self, quote: str) -> None:
        self.quote = quote
        self.prompts: list[str] = []

    async def health_check(self):
        from app.providers.base import HealthResult

        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        from app.providers.base import GenerateResult

        self.prompts.append(prompt)
        if "verdict" in prompt.lower() or "evidence_quote" in prompt:
            body = (
                '{"status": "SUPPORTED", "confidence": 0.9, "evidence_quote": '
                f'"{self.quote}", "notes": "Sursa confirma afirmatia."}}'
            )
        else:
            body = (
                '[{"claim_text": "' + self.quote + '", "claim_type": "SCIENTIFIC_FACT", '
                '"importance": "CRITICAL", "confidence": 0.9}]'
            )
        return GenerateResult(body, 10, 40, None)


def test_research_reads_a_source_and_a_second_agent_checks_the_result(engine, settings):
    """The stage runs the real pipeline: extraction, then verification with the quote check."""
    from pathlib import Path as _Path

    from app.agents.models import Agent, ModelRecord
    from app.agents.services import seed_initial_workforce
    from app.factual.services import ingest_source_snapshot
    from app.integrations.vault import CredentialVault
    from app.models import OwnerPolicy
    from sqlalchemy import select

    quote = "Telescopul observa in infrarosu."
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        provider_id = session.scalar(select(Agent)).provider_id

    ingest_source_snapshot(
        engine,
        url="https://www.iana.org/help/example-domains",
        title="Sursa de proba",
        publisher="www.iana.org",
        author=None,
        raw_content=quote,
        credibility_score=0.9,
        correlation_id=str(uuid4()),
    )

    registry = ProviderRegistry()
    model = _ScriptedModel(quote)
    registry.register(provider_id, model)

    vault = CredentialVault(_Path(str(engine.url.database)).with_suffix(".credentials.key"))
    stage = build_stage_runners(engine, settings, vault, registry)["research_and_verification"]
    outcome = stage()

    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["sources_read"] == 1
    # Called at least twice: once to extract, once to verify. Two different agents, by design.
    assert len(model.prompts) >= 2

    with Session(engine) as session:
        claims = list(session.scalars(select(FactualClaim)))
    assert claims, "the stage stored no claim"
    assert any(claim.status == "SUPPORTED" for claim in claims), [c.status for c in claims]


# ------------------------------------------------------- refusals are not failures --


def test_a_rejected_script_does_not_take_the_day_down_with_it(engine, settings, monkeypatch):
    """A model that writes unattributable narration is a content problem, not a run failure.

    Letting it raise would mark the stage FAILED, and the runbook stops the day at the first
    FAILED stage — so the daily log would never be closed and every later stage would be BLOCKED,
    over an outcome the pipeline handled exactly right by refusing to store the draft.
    """
    from pathlib import Path as _Path

    from app.factual.agent_pipeline import ScriptRejected
    from app.integrations.vault import CredentialVault

    topic_id = _topic(engine, status="SELECTED")
    _claim(engine, topic_id, status="SUPPORTED")

    registry = ProviderRegistry()
    registry.register("any", object())

    def refuse(*args: Any, **kwargs: Any) -> None:
        raise ScriptRejected("scena 1 citează afirmații care nu există")

    monkeypatch.setattr("app.runbook.stages.agent_write_script", refuse)
    vault = CredentialVault(_Path(str(engine.url.database)).with_suffix(".credentials.key"))
    outcome = build_stage_runners(engine, settings, vault, registry)["script_and_storyboard"]()

    assert outcome["status"] == "COMPLETED"
    assert outcome["artefacts"]["scripts"] == 0
    assert len(outcome["artefacts"]["rejected"]) == 1
    assert "respinse" in outcome["reason"]


def test_quality_control_selects_files_by_what_they_are_not_by_their_label(
    engine, settings, tmp_path
):
    """The renderer writes RENDERED_VIDEO and the fixtures write VIDEO_COMPOSED.

    Keying quality control to either name would leave real renders unmeasured, and an unmeasured
    file is exactly what the publishing gate is supposed to stop.
    """
    from hashlib import sha256
    from pathlib import Path as _Path

    from app.integrations.vault import CredentialVault
    from app.media.models import MediaAsset

    video = tmp_path / "render.mp4"
    video.write_bytes(b"\x00" * 4096)
    asset_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=str(video),
                file_size_bytes=video.stat().st_size,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=12.0,
                provider_name="test",
                license_status="OWNED_INTERNAL",
                provenance_hash=sha256(video.read_bytes()).hexdigest(),
                created_at=utc_now(),
            )
        )

    vault = CredentialVault(_Path(str(engine.url.database)).with_suffix(".credentials.key"))
    outcome = build_stage_runners(engine, settings, vault, ProviderRegistry())["edit_and_qc"]()

    assert outcome["status"] == "COMPLETED"
    # It was measured. Whether it passed is QC's business; that it was looked at is this test's.
    assert outcome["artefacts"]["passed"] + outcome["artefacts"]["failed"] == 1
