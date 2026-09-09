"""Agent-driven factual pipeline: the research agent extracts claims through its LLM.

The adapter is stubbed — these tests prove the wiring (kernel, schema validation, UNVERIFIED
status, announcements), not provider connectivity, which is verified live against the
configured provider.
"""

from uuid import uuid4

import pytest
from app.agents.models import Agent
from app.agents.services import seed_initial_workforce
from app.factual.services import ingest_source_snapshot
from app.models import DomainEvent, OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from sqlalchemy import select
from sqlalchemy.orm import Session

VALID_CLAIMS_JSON = """```json
[
  {"claim_text": "IANA menține registrul domeniilor rezervate pentru documentație și exemple.",
   "claim_type": "GENERAL", "importance": "SUPPORTING", "confidence": 0.9},
  {"claim_text": "Domeniul example.com este rezervat oficial pentru uz în documentație.",
   "claim_type": "GENERAL", "importance": "CRITICAL", "confidence": 0.95},
  {"claim_text": "Un al treilea fapt scurt extras din sursă."}
]
```"""


class _StubAdapter:
    def __init__(self, text: str) -> None:
        self.text = text

    async def health_check(self):  # pragma: no cover - kernel reads cached status
        return HealthResult("HEALTHY")

    async def list_models(self):  # pragma: no cover - not used by the pipeline
        return []

    async def generate(self, model, prompt, **kwargs):
        assert "untrusted_source_evidence" in prompt, "source must stay inside the inert boundary"
        return GenerateResult(self.text, 10, 40, None)


@pytest.fixture
def research_ready(client, engine, headers):
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    with Session(engine) as session:
        agent = session.scalar(select(Agent))
        provider_id = agent.provider_id
    snapshot = ingest_source_snapshot(
        engine,
        url="https://www.iana.org/help/example-domains",
        title="IANA Example Domains",
        publisher="www.iana.org",
        author=None,
        raw_content="Example domains: example.com is reserved for use in documentation.",
        credibility_score=0.9,
        correlation_id=str(uuid4()),
    )
    return {
        "client": client,
        "headers": headers,
        "engine": engine,
        "provider_id": provider_id,
        "source_id": snapshot["id"],
    }


def _claims_for_source(engine, source_id):
    from app.factual.models import FactualClaim

    with Session(engine) as session:
        claims = session.scalars(
            select(FactualClaim).where(FactualClaim.source_id == source_id)
        ).all()
        return [(c.claim_text, c.status) for c in claims]


def test_agent_extracts_claims_staying_unverified(research_ready):
    research_ready["client"].app.app.state.registry.register(
        research_ready["provider_id"], _StubAdapter(VALID_CLAIMS_JSON)
    )
    response = research_ready["client"].post(
        f"/api/v1/factual/sources/{research_ready['source_id']}/extract-with-agent",
        headers=research_ready["headers"],
        json={"command_id": str(uuid4())},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["claims"]) == 3
    claims = _claims_for_source(research_ready["engine"], research_ready["source_id"])
    assert len(claims) == 3
    assert all(status == "UNVERIFIED" for _, status in claims)

    # The agent announced a human summary, not its raw JSON.
    with Session(research_ready["engine"]) as session:
        messages = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "agent.message_sent")
        ).all()
    assert len(messages) == 1
    assert messages[0].payload["text"].startswith("Am extras 3 afirmații")


def test_unparseable_output_is_rejected_and_nothing_stored(research_ready):
    research_ready["client"].app.app.state.registry.register(
        research_ready["provider_id"], _StubAdapter("sorry, cannot answer that")
    )
    response = research_ready["client"].post(
        f"/api/v1/factual/sources/{research_ready['source_id']}/extract-with-agent",
        headers=research_ready["headers"],
        json={"command_id": str(uuid4())},
    )
    assert response.status_code == 422
    assert _claims_for_source(research_ready["engine"], research_ready["source_id"]) == []
    with Session(research_ready["engine"]) as session:
        messages = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "agent.message_sent")
        ).all()
    assert messages == []


def test_blocked_policy_stops_extraction_before_any_claim(research_ready):
    with Session(research_ready["engine"]) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True
    research_ready["client"].app.app.state.registry.register(
        research_ready["provider_id"], _StubAdapter(VALID_CLAIMS_JSON)
    )
    response = research_ready["client"].post(
        f"/api/v1/factual/sources/{research_ready['source_id']}/extract-with-agent",
        headers=research_ready["headers"],
        json={"command_id": str(uuid4())},
    )
    assert response.status_code == 422
    assert _claims_for_source(research_ready["engine"], research_ready["source_id"]) == []


def test_truncated_json_list_keeps_complete_claims_only(research_ready):
    """A model that hits its token cap mid-list must not lose the complete claims."""
    truncated = (
        '[{"claim_text": "Prima afirmație completă extrasă din sursă.", "claim_type": "GENERAL",'
        ' "importance": "SUPPORTING", "confidence": 0.9},'
        ' {"claim_text": "A doua afirmație completă extrasă din sursă.", "claim_type": "GENERAL",'
        ' "importance": "CRITICAL", "confidence": 0.8},'
        ' {"claim_text": "A treia afirmație ta'
    )
    research_ready["client"].app.app.state.registry.register(
        research_ready["provider_id"], _StubAdapter(truncated)
    )
    response = research_ready["client"].post(
        f"/api/v1/factual/sources/{research_ready['source_id']}/extract-with-agent",
        headers=research_ready["headers"],
        json={"command_id": str(uuid4())},
    )
    assert response.status_code == 200, response.text
    claims = _claims_for_source(research_ready["engine"], research_ready["source_id"])
    assert len(claims) == 2
    assert all(text.startswith(("Prima", "A doua")) for text, _ in claims)
