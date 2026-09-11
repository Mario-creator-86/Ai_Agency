import secrets
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentRun, ModelRecord
from app.agents.services import run_agent_task, seed_initial_workforce
from app.factual.schemas import ExtractClaimItem
from app.factual.services import (
    FactualGateError,
    approve_script_draft,
    extract_claims,
    generate_script_draft,
    ingest_source_snapshot,
    propose_topic_idea,
    verify_claim,
)
from app.models import OwnerPolicy
from app.providers.registry import ProviderRegistry
from app.publishing.services import seed_default_channels
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session


@pytest.mark.parametrize(
    "available,state,expected",
    [
        (False, "IDLE", "BLOCKED_PROVIDER"),
        (True, "THINKING", "BLOCKED_POLICY"),
    ],
)
def test_unverified_or_busy_agent_never_calls_provider(engine, available, state, expected):
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        agent = session.scalar(select(Agent))
        agent.runtime_state = state
        session.get(ModelRecord, agent.model_id).is_available = available
        agent_id, provider_id = agent.id, agent.provider_id
        if state == "THINKING":
            # Busy means a run genuinely in flight; a THINKING flag with no run behind it
            # is stale and is cleared, not obeyed.
            session.add(
                AgentRun(
                    id=str(uuid4()),
                    agent_id=agent_id,
                    task_type="plan",
                    objective="in flight",
                    prompt_template_version="v1",
                    model_name="m",
                    provider_name="p",
                    status="RUNNING",
                    correlation_id=str(uuid4()),
                    started_at=utc_now(),
                    context_json={},
                )
            )

    class Provider:
        async def generate(self, *args, **kwargs):
            pytest.fail("Blocked tasks must never reach the provider")

    registry = ProviderRegistry()
    registry.register(provider_id, Provider())
    result = run_agent_task(
        engine, registry, agent_id, "test", "test objective", "v1", str(uuid4())
    )
    assert result["status"] == expected
    with Session(engine) as session:
        assert session.get(Agent, agent_id).runtime_state == state


def test_repeat_approval_rechecks_refuted_evidence(engine):
    correlation = str(uuid4())
    topic = propose_topic_idea(
        engine, "Test topic", "Test subject", "Explanation", "General", correlation
    )
    source = ingest_source_snapshot(
        engine,
        "https://example.org/source",
        "Test source",
        "example.org",
        None,
        "Text representing a test source.",
        0,
        correlation,
        topic["id"],
    )
    claim = extract_claims(
        engine, source["id"], [ExtractClaimItem(claim_text="Test claim text")], correlation
    )[0]
    verify_claim(engine, claim["id"], "SUPPORTED", 0.9, "Test setup", "Test evidence", correlation)
    draft = generate_script_draft(
        engine,
        topic["id"],
        "Test draft",
        50,
        "A long enough voiceover for this test.",
        [],
        [claim["id"]],
        correlation,
    )
    assert approve_script_draft(engine, draft["id"], correlation)["status"] == "APPROVED"
    verify_claim(
        engine, claim["id"], "REFUTED", 0.9, "Revised evidence", "Test evidence", correlation
    )
    with pytest.raises(FactualGateError):
        approve_script_draft(engine, draft["id"], correlation)


def test_channel_binding_requires_a_connected_channel_and_can_be_removed(
    client, headers, engine, connect_youtube
):
    seed_default_channels(engine)

    # A connection that exists but was never authorised cannot back a channel.
    unauthorised = client.post(
        "/api/v1/youtube/connections",
        headers=headers,
        json={
            "command_id": str(uuid4()),
            "name": "Neconectat",
            "client_id": "unauthorised.apps.googleusercontent.com",
            "client_secret": secrets.token_urlsafe(32),
            "redirect_uri": "http://127.0.0.1:8000/auth/youtube/callback",
        },
    ).json()
    channel = client.get("/api/v1/settings", headers=headers).json()["channels"][0]
    path = f"/api/v1/settings/channels/{channel['id']}"
    payload = {"connection_id": unauthorised["id"], "expected_event_id": channel["event_id"]}
    assert client.put(path, json=payload, headers=headers).status_code == 422

    identifier, _ = connect_youtube(name="Canal real", channel_id="UC_bound", title="Canal real")
    payload = {"connection_id": identifier, "expected_event_id": channel["event_id"]}
    assert client.put(path, json=payload, headers=headers).status_code == 200
    assert client.put(path, json=payload, headers=headers).status_code == 409
    channel = client.get("/api/v1/settings", headers=headers).json()["channels"][0]
    assert channel["credentials_ref"] == "youtube_connection:" + identifier
    # The remote id came from the grant, so a channel record cannot claim an unowned account.
    assert channel["remote_channel_id"] == "UC_bound"
    assert (
        client.put(
            path,
            json={"connection_id": None, "expected_event_id": channel["event_id"]},
            headers=headers,
        ).status_code
        == 200
    )
