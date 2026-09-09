import secrets
from pathlib import Path
from uuid import uuid4

import pytest
from app.agents.models import Agent, ModelRecord
from app.agents.services import seed_initial_workforce
from app.integrations.llm import ConfiguredLLM
from app.integrations.models import Integration
from app.integrations.services import selected_youtube
from app.integrations.vault import CredentialVault
from app.main import create_app
from app.models import DomainEvent
from app.providers.base import GenerateResult, ModelInfo
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session


def command(kind="openai", **kwargs):
    return {
        "kind": kind,
        "name": "Test connection",
        "config": {},
        "secrets": {"api_key": secrets.token_urlsafe(32)},
        "expected_version": 0,
        **kwargs,
    }


def put(client, headers, payload, identifier=None):
    identifier = identifier or str(uuid4())
    result = client.put(
        f"/api/v1/settings/integrations/{identifier}", headers=headers, json=payload
    )
    return identifier, result


def test_empty_settings_require_owner_and_have_no_example_accounts(client, headers):
    assert client.get("/api/v1/settings").status_code == 401
    data = client.get("/api/v1/settings", headers=headers).json()
    assert data["integrations"] == [] and data["selections"] == {}
    assert {"youtube", "tiktok", "instagram", "facebook", "email"} <= data["catalog"].keys()


def test_secrets_encrypted_preserved_and_never_returned(client, headers, engine):
    payload = command()
    secret = payload["secrets"]["api_key"]
    identifier, result = put(client, headers, payload)
    assert result.status_code == 200, result.text
    assert secret not in result.text
    assert result.json()["secret_fields"] == ["api_key"]
    with Session(engine) as session:
        row = session.get(Integration, identifier)
        assert secret not in row.encrypted_secrets
        vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
        assert vault.decrypt(row.encrypted_secrets)["api_key"] == secret
        assert secret not in str(session.scalars(select(DomainEvent)).all())
    updated = {**payload, "secrets": {}, "expected_version": 1, "name": "Renamed"}
    assert put(client, headers, updated, identifier)[1].status_code == 200
    assert put(client, headers, updated, identifier)[1].status_code == 422
    with Session(engine) as session:
        assert (
            vault.decrypt(session.get(Integration, identifier).encrypted_secrets)["api_key"]
            == secret
        )
    assert secret not in client.get("/api/v1/settings", headers=headers).text


@pytest.mark.parametrize(
    "payload",
    [
        command(config={"api_key": "abc"}),
        command(secrets={}),
        command(kind="unknown"),
        command(config={"arbitrary": "value"}),
        command(kind="compatible", config={"base_url": "https://alice@example.org"}),
        command(kind="compatible", config={"base_url": "http://external.example.org"}),
        command(kind="compatible", config={"base_url": "https://example.org?token=hidden"}),
    ],
)
def test_invalid_config_has_no_side_effects(payload, client, headers):
    assert put(client, headers, payload)[1].status_code == 422
    assert client.get("/api/v1/settings", headers=headers).json()["integrations"] == []


def test_vault_survives_restart_and_loads_runtime_adapter(client, headers, engine, settings):
    identifier, response = put(client, headers, command())
    assert response.status_code == 200
    with TestClient(create_app(settings)) as restarted:
        data = restarted.get("/api/v1/settings", headers=headers).json()
        assert data["integrations"][0]["id"] == identifier
        assert restarted.app.app.state.registry.get(identifier) is not None


def test_verification_loads_real_response_models_and_marks_failure(client, headers, monkeypatch):
    identifier, _ = put(client, headers, command())

    async def models(self):
        return [ModelInfo("provider-returned-model", None, True)]

    monkeypatch.setattr(ConfiguredLLM, "list_models", models)
    result = client.post(f"/api/v1/settings/integrations/{identifier}/check", headers=headers)
    assert result.json()["status"] == "VERIFIED"
    data = client.get("/api/v1/settings", headers=headers).json()
    assert any(m["model_name"] == "provider-returned-model" for m in data["models"])

    async def fail(self):
        raise ValueError("secret-external-error")

    monkeypatch.setattr(ConfiguredLLM, "list_models", fail)
    result = client.post(f"/api/v1/settings/integrations/{identifier}/check", headers=headers)
    assert result.json()["status"] == "FAILED"
    assert "secret-external-error" not in result.text


def test_service_selection_clear_and_delete(client, headers):
    identifier, response = put(
        client,
        headers,
        command("elevenlabs", config={"model": "owner-model", "voice_id": "owner-voice"}),
    )
    assert response.status_code == 200

    def select_service(purpose, value, version):
        return client.put(
            f"/api/v1/settings/selections/{purpose}",
            headers=headers,
            json={"integration_id": value, "expected_version": version},
        )

    assert select_service("video", identifier, 0).status_code == 422
    assert select_service("voice", identifier, 0).status_code == 200
    assert (
        client.delete(
            f"/api/v1/settings/integrations/{identifier}?expected_version=1", headers=headers
        ).status_code
        == 409
    )
    assert select_service("voice", None, 1).status_code == 200
    assert (
        client.delete(
            f"/api/v1/settings/integrations/{identifier}?expected_version=1", headers=headers
        ).status_code
        == 200
    )


def test_youtube_selection_supplies_runtime_credentials(client, headers, engine):
    payload = command(
        "youtube",
        config={"client_id": "owner-client", "channel_id": "owner-channel"},
        secrets={
            "client_secret": secrets.token_urlsafe(32),
            "refresh_token": secrets.token_urlsafe(32),
        },
    )
    identifier, response = put(client, headers, payload)
    assert response.status_code == 200
    result = client.put(
        "/api/v1/settings/selections/youtube",
        headers=headers,
        json={"integration_id": identifier, "expected_version": 0},
    )
    assert result.status_code == 200
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    provider = selected_youtube(engine, vault)
    assert provider.is_configured
    assert provider.channel_id == "owner-channel"
    assert provider.refresh_token == payload["secrets"]["refresh_token"]


def test_agent_assignment_is_persistent_and_rejects_busy_or_stale(client, headers, engine):
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        agent = session.scalar(select(Agent))
        assert agent
        agent.runtime_state = "IDLE"
        agent_id, model_id, version = agent.id, agent.model_id, agent.version
        model = session.get(ModelRecord, model_id)
        model.is_available = True
    path = f"/api/v1/settings/agents/{agent_id}/model"
    payload = {"model_id": model_id, "expected_version": version}
    assert client.put(path, headers=headers, json=payload).status_code == 200
    assert client.put(path, headers=headers, json=payload).status_code == 422
    with Session(engine) as session, session.begin():
        agent = session.get(Agent, agent_id)
        agent.runtime_state = "THINKING"
        version = agent.version
    assert (
        client.put(path, headers=headers, json={**payload, "expected_version": version}).status_code
        == 422
    )


def test_external_probe_does_not_leak_failures(client, headers, monkeypatch):
    identifier, _ = put(client, headers, command("replicate", config={"model": "owner/model"}))
    from app.integrations import router

    def fail(*args):
        raise ValueError("upstream-secret-value")

    monkeypatch.setattr(router, "probe", fail)
    response = client.post(f"/api/v1/settings/integrations/{identifier}/check", headers=headers)
    assert response.json()["status"] == "FAILED"
    assert "upstream-secret-value" not in response.text


def test_agent_llm_test_endpoint_runs_assigned_model(client, headers, engine, monkeypatch):
    from app.models import OwnerPolicy

    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    identifier, _ = put(
        client,
        headers,
        command(
            "ollama",
            config={"base_url": "https://ollama.example.org"},
            secrets={"api_key": secrets.token_urlsafe(32)},
        ),
    )

    async def models(self):
        return [ModelInfo("cloud-model", None, True)]

    monkeypatch.setattr(ConfiguredLLM, "list_models", models)
    assert (
        client.post(f"/api/v1/settings/integrations/{identifier}/check", headers=headers).json()[
            "status"
        ]
        == "VERIFIED"
    )

    with Session(engine) as session:
        agent = session.scalar(select(Agent))
        agent_id, version = agent.id, agent.version
        model_id = session.scalar(
            select(ModelRecord.id).where(ModelRecord.provider_id == identifier)
        )
    assert model_id
    assert (
        client.put(
            f"/api/v1/settings/agents/{agent_id}/model",
            headers=headers,
            json={"model_id": model_id, "expected_version": version},
        ).status_code
        == 200
    )

    async def generate(self, model, prompt, **kwargs):
        return GenerateResult("Da, sunt funcțional.", 9, 7, None)

    monkeypatch.setattr(ConfiguredLLM, "generate", generate)
    result = client.post(f"/api/v1/settings/agents/{agent_id}/test", headers=headers)
    assert result.status_code == 200
    body = result.json()
    assert body["status"] == "SUCCEEDED"
    assert body["output_text"] == "Da, sunt funcțional."
    assert body["model_name"] == "cloud-model"
    assert body["duration_s"] >= 0
    assert (
        client.post(
            "/api/v1/settings/agents/00000000-0000-0000-0000-000000000000/test", headers=headers
        ).status_code
        == 404
    )
