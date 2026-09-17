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
    assert {"tiktok", "instagram", "facebook", "email"} <= data["catalog"].keys()
    # YouTube is deliberately absent: a channel is connected by OAuth, and offering a catalog
    # form beside it would put back the hand-typed refresh token the flow exists to remove.
    assert "youtube" not in data["catalog"]


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


def test_service_selection_clear_and_delete(client, headers, elevenlabs_api):
    identifier, response = put(
        client,
        headers,
        command("elevenlabs"),
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
            f"/api/v1/settings/integrations/{identifier}?expected_version=2", headers=headers
        ).status_code
        == 409
    )
    assert select_service("voice", None, 1).status_code == 200
    assert (
        client.delete(
            f"/api/v1/settings/integrations/{identifier}?expected_version=2", headers=headers
        ).status_code
        == 200
    )


def test_youtube_credentials_come_from_the_oauth_connection(engine, connect_youtube):
    """Publishing credentials are whatever the grant produced, never a typed-in row."""
    identifier, vault = connect_youtube(
        name="Canal unic", channel_id="UC_only_one", title="Canal unic"
    )
    provider = selected_youtube(engine, vault)
    assert provider.is_configured
    # The channel id was read back from the API during authorisation, not entered anywhere.
    assert provider.channel_id == "UC_only_one"
    assert provider.refresh_token == "test-refresh-UC_only_one"
    assert selected_youtube(engine, vault, identifier).channel_id == "UC_only_one"


def test_a_second_connected_channel_makes_the_studio_ask_which_one(engine, connect_youtube):
    """Two channels and no binding is ambiguous, and publishing to the wrong one is not a
    recoverable mistake, so the studio refuses instead of picking."""
    connect_youtube(name="Canal unu", channel_id="UC_first", title="Canal unu")
    second, vault = connect_youtube(name="Canal doi", channel_id="UC_second", title="Canal doi")
    with pytest.raises(ValueError, match="Leagă canalul"):
        selected_youtube(engine, vault)
    # Naming the connection removes the ambiguity.
    assert selected_youtube(engine, vault, second).channel_id == "UC_second"


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


def test_a_restricted_elevenlabs_key_is_told_which_permissions_it_lacks(
    client, headers, elevenlabs_api
):
    """A key created with restricted scopes answers 401 missing_permissions on /v1/user. The
    Owner must be told that, not just that "the key could not be verified"."""
    from app.providers.media_http import MediaProviderError

    def refuse(path):
        if path.startswith("/v1/user"):
            raise MediaProviderError(
                "api.elevenlabs.io refused the request (HTTP 401)",
                code="missing_permissions",
                http_status=401,
            )

    elevenlabs_api.fail = refuse
    identifier, response = put(client, headers, command("elevenlabs"))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FAILED"
    assert "permisiuni restrânse" in body["message"]
    assert "User (Read)" in body["message"] and "Voices (Read)" in body["message"]
    assert body["catalog"]["discovery"]["status"] == "ERROR"
    assert body["catalog"]["models"] == [] and body["catalog"]["voices"] == []

    # Once the key can read the account but not the catalogue, the message says so too.
    def refuse_lists(path):
        if path.startswith("/v1/models"):
            raise MediaProviderError(
                "api.elevenlabs.io refused the request (HTTP 401)",
                code="missing_permissions",
                http_status=401,
            )

    elevenlabs_api.fail = refuse_lists
    retry = client.post(
        f"/api/v1/settings/integrations/{identifier}/refresh-resources", headers=headers
    )
    assert retry.status_code == 200
    assert retry.json()["status"] == "VERIFIED"
    assert "Models (Read)" in retry.json()["message"]

    # An invalid key is a different message: no permissions advice for a key that is not one.
    def invalid(path):
        raise MediaProviderError(
            "api.elevenlabs.io refused the request (HTTP 401)",
            code="invalid_api_key",
            http_status=401,
        )

    elevenlabs_api.fail = invalid
    again = client.post(
        f"/api/v1/settings/integrations/{identifier}/refresh-resources", headers=headers
    )
    assert again.json()["status"] == "FAILED"
    assert "invalidă sau a fost revocată" in again.json()["message"]


# --- the configured adapter retries a vendor that says "not now" (2026-09-17) --------------


class ScriptedConnection:
    """One scripted `http.client` exchange per connection, in the order the test lists."""

    script: list = []
    opened: int = 0

    def __init__(self, host, port=None, timeout=None):
        ScriptedConnection.opened += 1
        self.sent = None

    def request(self, method, path, body, headers):
        step = self.script[0]
        if step.get("connect") is not None:
            self.script.pop(0)
            raise step["connect"]
        self.sent = (method, path)

    def getresponse(self):
        step = self.script.pop(0)
        if step.get("read") is not None:
            raise step["read"]
        from unittest.mock import MagicMock

        resp = MagicMock()
        resp.status = step["status"]
        resp.read = MagicMock(return_value=step.get("body", b"{}"))
        resp.getheader = lambda name, default=None: step.get("headers", {}).get(name, default)
        return resp

    def close(self):
        pass


@pytest.fixture
def llm_script(monkeypatch):
    import http.client

    from app.providers import retry

    ScriptedConnection.script = []
    ScriptedConnection.opened = 0
    monkeypatch.setattr(http.client, "HTTPSConnection", ScriptedConnection)
    monkeypatch.setattr(retry, "sleep", lambda _: None)
    return ScriptedConnection.script


def _llm() -> ConfiguredLLM:
    return ConfiguredLLM("openai", {}, {"api_key": "k"})


def test_the_configured_adapter_lists_models_after_a_503(llm_script):
    import asyncio

    llm_script.extend([{"status": 503}, {"status": 200, "body": b'{"data": [{"id": "m1"}]}'}])
    models = asyncio.run(_llm().list_models())
    assert [m.model_name for m in models] == ["m1"]
    assert ScriptedConnection.opened == 2


def test_the_configured_adapter_does_not_repeat_a_400(llm_script):
    llm_script.append({"status": 400})
    with pytest.raises(ValueError, match="HTTP 400"):
        _llm().request("GET", "/models")
    assert ScriptedConnection.opened == 1


def test_the_configured_adapter_gives_up_after_the_configured_attempts(llm_script):
    llm_script.extend([{"status": 502}, {"status": 503}, {"status": 502}])
    with pytest.raises(ValueError, match="3 attempts") as excinfo:
        _llm().request("GET", "/models")
    assert ScriptedConnection.opened == 3
    assert excinfo.value.http_status == 502


def test_the_configured_adapter_waits_the_retry_after_it_is_given(monkeypatch, llm_script):
    from app.providers import retry

    slept: list[float] = []
    monkeypatch.setattr(retry, "sleep", slept.append)
    llm_script.extend(
        [{"status": 429, "headers": {"Retry-After": "2"}}, {"status": 200, "body": b"{}"}]
    )
    assert _llm().request("GET", "/models") == {}
    assert slept == [2.0]


def test_a_generation_that_left_and_got_no_answer_is_not_billed_twice(llm_script):
    """A cloud model answering slowly is still answering; the tokens are spent either way."""
    llm_script.append({"read": TimeoutError("timed out")})
    with pytest.raises(OSError):
        _llm().request("POST", "/chat/completions", {"model": "m"})
    assert ScriptedConnection.opened == 1


def test_a_generation_whose_request_never_left_is_sent_again(llm_script):
    llm_script.extend(
        [{"connect": ConnectionRefusedError("refused")}, {"status": 200, "body": b"{}"}]
    )
    assert _llm().request("POST", "/chat/completions", {"model": "m"}) == {}
    assert ScriptedConnection.opened == 2
