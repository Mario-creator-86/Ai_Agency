"""Independent fact-checking: who may verify a claim, and what a verdict has to rest on.

Two rules carry this module, and both exist because a verdict is the last thing standing
between a model's fluency and a published statement of fact:

1. The agent that read a source may not be the one that confirms it (FR-038). An agent
   agreeing with its own reading is not a check.
2. A SUPPORTED or REFUTED verdict must quote the source verbatim. The quote is matched against
   the stored text before anything is written, so a confident verdict resting on invented
   evidence is thrown away rather than stored.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from app.agents.models import Agent
from app.factual.agent_pipeline import (
    NoIndependentVerifier,
    VerificationRejected,
    agent_verify_claim,
)
from app.factual.models import FactualClaim
from app.factual.schemas import ExtractClaimItem
from app.factual.services import extract_claims, ingest_source_snapshot
from sqlalchemy import select
from sqlalchemy.orm import Session

SOURCE_TEXT = (
    "The Hubble Space Telescope was launched into low Earth orbit in 1990. "
    "It remains in operation and has made more than one and a half million observations."
)
CLAIM = "The Hubble Space Telescope was launched in 1990."


@pytest.fixture
def workforce(engine):
    from app.agents.services import seed_initial_workforce

    seed_initial_workforce(engine)
    with Session(engine) as session:
        return [a.id for a in session.scalars(select(Agent))]


@pytest.fixture
def claim(engine, workforce):
    source = ingest_source_snapshot(
        engine,
        "https://example.org/hubble",
        "Hubble",
        "example.org",
        None,
        SOURCE_TEXT,
        0,
        str(uuid4()),
    )
    created = extract_claims(
        engine,
        source["id"],
        [ExtractClaimItem(claim_text=CLAIM, claim_type="HISTORICAL_EVENT", confidence=0.9)],
        str(uuid4()),
        extracted_by_agent_id=workforce[0],
    )
    return created[0]["id"]


class ScriptedRegistry:
    """Returns a fixed answer for whichever agent is asked, and records who was asked."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.asked: list[str] = []

    def install(self, engine, monkeypatch, module):
        def fake_run(_engine, _registry, agent_id, *args, **kwargs):
            self.asked.append(agent_id)
            return {
                "id": str(uuid4()),
                "status": "SUCCEEDED",
                "output_text": self.answer,
                "error_detail": None,
            }

        monkeypatch.setattr(module, "run_agent_task", fake_run)
        monkeypatch.setattr(module, "_announce", lambda *a, **k: None)


def verdict(status: str, quote: str, confidence: float = 0.9) -> str:
    return json.dumps(
        {"status": status, "confidence": confidence, "evidence_quote": quote, "notes": "n"}
    )


def run(engine, claim_id, answer, monkeypatch, agent_id=None):
    from app.factual import agent_pipeline

    registry = ScriptedRegistry(answer)
    registry.install(engine, monkeypatch, agent_pipeline)
    result = agent_verify_claim(engine, object(), claim_id, str(uuid4()), agent_id=agent_id)
    return result, registry


def stored(engine, claim_id) -> FactualClaim:
    with Session(engine) as session:
        return session.get(FactualClaim, claim_id)


# ---------------------------------------------------------------------------
# Independence
# ---------------------------------------------------------------------------


def test_the_agent_that_read_the_source_cannot_verify_its_own_claim(
    engine, claim, workforce, monkeypatch
):
    with pytest.raises(NoIndependentVerifier):
        run(
            engine,
            claim,
            verdict("SUPPORTED", "launched into low Earth orbit in 1990"),
            monkeypatch,
            agent_id=workforce[0],
        )

    assert stored(engine, claim).status == "UNVERIFIED"


def test_the_verifier_chosen_automatically_is_never_the_extractor(
    engine, claim, workforce, monkeypatch
):
    result, registry = run(
        engine, claim, verdict("SUPPORTED", "launched into low Earth orbit in 1990"), monkeypatch
    )

    assert registry.asked, "an agent must actually have been asked"
    assert registry.asked[0] != workforce[0]
    assert result["agent_id"] != workforce[0]
    assert stored(engine, claim).verified_by_agent_id == result["agent_id"]


def test_with_no_second_agent_the_studio_refuses_rather_than_pretending(
    engine, claim, workforce, monkeypatch
):
    """A single agent cannot check itself, so there is no verification to be had."""
    with Session(engine) as session, session.begin():
        for agent in session.scalars(select(Agent)):
            if agent.id != workforce[0]:
                agent.lifecycle = "TERMINATED"

    with pytest.raises(NoIndependentVerifier):
        run(engine, claim, verdict("SUPPORTED", "in 1990"), monkeypatch)

    assert stored(engine, claim).status == "UNVERIFIED"


# ---------------------------------------------------------------------------
# The evidence has to be in the source
# ---------------------------------------------------------------------------


def test_a_verdict_quoting_the_source_is_recorded(engine, claim, monkeypatch):
    result, _ = run(
        engine, claim, verdict("SUPPORTED", "launched into low Earth orbit in 1990"), monkeypatch
    )

    assert result["claim"]["status"] == "SUPPORTED"
    row = stored(engine, claim)
    assert row.status == "SUPPORTED"
    assert row.evidence_text in SOURCE_TEXT or row.evidence_text.lower() in SOURCE_TEXT.lower()
    assert row.verified_at is not None


def test_a_quote_that_differs_only_in_spacing_or_case_still_counts(engine, claim, monkeypatch):
    """Matching is on the words, not on the formatting the model happened to emit."""
    result, _ = run(
        engine,
        claim,
        verdict("SUPPORTED", "  LAUNCHED   into low earth\norbit in 1990 "),
        monkeypatch,
    )

    assert result["claim"]["status"] == "SUPPORTED"


def test_a_confident_verdict_with_invented_evidence_is_thrown_away(engine, claim, monkeypatch):
    """The failure this whole mechanism exists for: a fluent verdict citing nothing real."""
    with pytest.raises(VerificationRejected) as excinfo:
        run(
            engine,
            claim,
            verdict("SUPPORTED", "NASA confirmed the 1990 launch in its official press kit."),
            monkeypatch,
        )

    assert "nu se găsește în sursă" in str(excinfo.value)
    row = stored(engine, claim)
    assert row.status == "UNVERIFIED", "a rejected verdict must not change the claim"
    assert row.verified_by_agent_id is None
    assert row.evidence_text is None


def test_a_refutation_needs_real_evidence_too(engine, claim, monkeypatch):
    with pytest.raises(VerificationRejected):
        run(engine, claim, verdict("REFUTED", "The telescope was launched in 1993."), monkeypatch)

    assert stored(engine, claim).status == "UNVERIFIED"


def test_supported_without_any_quote_is_rejected(engine, claim, monkeypatch):
    with pytest.raises(VerificationRejected):
        run(engine, claim, verdict("SUPPORTED", ""), monkeypatch)

    assert stored(engine, claim).status == "UNVERIFIED"


def test_uncertain_is_a_real_outcome_and_needs_no_quote(engine, claim, monkeypatch):
    """A checker that cannot find support must be able to say so instead of guessing."""
    result, _ = run(engine, claim, verdict("UNCERTAIN", "", confidence=0.2), monkeypatch)

    assert result["claim"]["status"] == "UNCERTAIN"
    row = stored(engine, claim)
    assert row.status == "UNCERTAIN"
    assert row.evidence_text is None, "an uncertain verdict cites nothing, and stores nothing"


# ---------------------------------------------------------------------------
# Malformed answers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        "I think this is probably true.",
        '{"status": "MAYBE", "confidence": 0.5, "evidence_quote": "in 1990"}',
        '{"status": "SUPPORTED", "confidence": 4.0, "evidence_quote": "in 1990"}',
        '{"status": "SUPPORTED"',
        "",
    ],
)
def test_an_answer_that_is_not_a_verdict_records_nothing(engine, claim, monkeypatch, answer):
    with pytest.raises(VerificationRejected):
        run(engine, claim, answer, monkeypatch)

    assert stored(engine, claim).status == "UNVERIFIED"


def test_a_verdict_wrapped_in_a_markdown_fence_is_still_read(engine, claim, monkeypatch):
    fenced = "Sure:\n```json\n" + verdict("SUPPORTED", "in 1990") + "\n```"

    result, _ = run(engine, claim, fenced, monkeypatch)

    assert result["claim"]["status"] == "SUPPORTED"
