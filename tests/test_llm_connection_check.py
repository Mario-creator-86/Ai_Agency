"""A public model catalogue must not certify an Ollama Cloud key."""

import asyncio
import secrets
from uuid import uuid4

import pytest
from app.agents.models import ProviderRecord
from app.integrations.llm import ConfiguredLLM, ProviderHTTPError, ProviderUnreachable
from app.providers.base import ModelInfo
from sqlalchemy.orm import Session


@pytest.mark.parametrize("identity", [{"ID": str(uuid4())}, {"id": str(uuid4())}])
def test_cloud_checks_authenticated_identity_before_public_catalog(monkeypatch, identity):
    calls = []

    def request(self, method, path, body=None):
        calls.append((method, path))
        if path == "/api/me":
            return identity
        if path == "/api/tags":
            return {"models": [{"name": "vendor-model"}]}
        return {"capabilities": ["completion"]}

    monkeypatch.setattr(ConfiguredLLM, "request", request)
    adapter = ConfiguredLLM(
        "ollama", {"base_url": "https://ollama.com"}, {"api_key": secrets.token_urlsafe(32)}
    )
    models = asyncio.run(adapter.list_models())
    assert len(models) == 1
    assert calls[:2] == [("POST", "/api/me"), ("GET", "/api/tags")]


def test_rejected_cloud_key_cannot_be_certified_by_public_models(monkeypatch):
    calls = []

    def request(self, method, path, body=None):
        calls.append(path)
        if path == "/api/me":
            raise ProviderHTTPError(401)
        return {"models": [{"name": "public-model"}]}

    monkeypatch.setattr(ConfiguredLLM, "request", request)
    adapter = ConfiguredLLM(
        "ollama", {"base_url": "https://ollama.com"}, {"api_key": secrets.token_urlsafe(32)}
    )
    with pytest.raises(ProviderHTTPError):
        asyncio.run(adapter.list_models())
    assert calls == ["/api/me"]


@pytest.mark.parametrize("identity", [{}, {"error": "upstream-secret"}, {"ID": ""}, {"ID": 12}])
def test_cloud_does_not_accept_an_unrecognised_authentication_response(monkeypatch, identity):
    monkeypatch.setattr(ConfiguredLLM, "request", lambda *args: identity)
    adapter = ConfiguredLLM(
        "ollama", {"base_url": "https://ollama.com"}, {"api_key": secrets.token_urlsafe(32)}
    )
    with pytest.raises(ValueError):
        asyncio.run(adapter.list_models())


def test_missing_cloud_key_fails_before_any_request(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ConfiguredLLM, "request", lambda *args: calls.append(args) or {"models": []}
    )
    adapter = ConfiguredLLM("ollama", {"base_url": "https://ollama.com"}, {})
    with pytest.raises(ProviderHTTPError):
        asyncio.run(adapter.list_models())
    assert not calls


def test_local_ollama_without_key_is_still_tested_locally(monkeypatch):
    calls = []
    monkeypatch.setattr(
        ConfiguredLLM,
        "request",
        lambda self, method, path, body=None: calls.append(path) or {"models": []},
    )
    adapter = ConfiguredLLM("ollama", {"base_url": "http://127.0.0.1:11434"}, {})
    assert asyncio.run(adapter.list_models()) == []
    assert calls == ["/api/tags"]


def connection(client, headers):
    identifier = str(uuid4())
    response = client.put(
        f"/api/v1/settings/integrations/{identifier}",
        headers=headers,
        json={
            "kind": "ollama",
            "name": "Ollama Cloud",
            "config": {"base_url": "https://ollama.com"},
            "secrets": {"api_key": secrets.token_urlsafe(32)},
            "expected_version": 0,
        },
    )
    assert response.status_code == 200
    return identifier


def test_check_returns_and_preserves_the_scope_and_model_count(client, headers, monkeypatch):
    identifier = connection(client, headers)

    async def models(self):
        return [ModelInfo("vendor-model", None, True)]

    monkeypatch.setattr(ConfiguredLLM, "list_models", models)
    response = client.post(f"/api/v1/settings/integrations/{identifier}/check", headers=headers)
    result = response.json()
    assert result["status"] == "VERIFIED"
    assert result["models_loaded"] == 1
    assert result["generation_tested"] is False
    assert "cheia" in result["message"].lower() and "validă" in result["message"]
    assert "Generarea nu a fost testată" in result["message"]
    saved = client.get("/api/v1/settings", headers=headers).json()["integrations"][0]
    assert saved["check_result"] == result


@pytest.mark.parametrize(
    "error,code,words",
    [
        (ProviderHTTPError(401), "AUTH_REQUIRED", "Cheia API"),
        (ProviderHTTPError(403), "ACCESS_DENIED", "refuzat"),
        (ProviderHTTPError(429), "RATE_LIMITED", "limită"),
        (ProviderHTTPError(503), "SERVICE_UNAVAILABLE", "indisponibil"),
        (ProviderUnreachable("upstream-secret", unsent=True), "UNREACHABLE", "conexiunea"),
        (ValueError("upstream-secret"), "CHECK_FAILED", "Verificarea"),
    ],
)
def test_failure_tells_owner_what_failed_without_exposing_vendor_text(
    client, headers, engine, monkeypatch, error, code, words
):
    identifier = connection(client, headers)

    async def fail(self):
        raise error

    monkeypatch.setattr(ConfiguredLLM, "list_models", fail)
    response = client.post(f"/api/v1/settings/integrations/{identifier}/check", headers=headers)
    result = response.json()
    assert result["status"] == "FAILED"
    assert result["error_code"] == code
    assert words in result["message"]
    assert "upstream-secret" not in response.text
    saved = client.get("/api/v1/settings", headers=headers).json()["integrations"][0]
    assert saved["check_result"] == result
    with Session(engine) as session:
        assert session.get(ProviderRecord, identifier).status != "HEALTHY"


def test_saved_result_is_invalidated_when_key_is_edited(client, headers, monkeypatch):
    identifier = connection(client, headers)

    async def models(self):
        return []

    monkeypatch.setattr(ConfiguredLLM, "list_models", models)
    client.post(f"/api/v1/settings/integrations/{identifier}/check", headers=headers)
    item = client.get("/api/v1/settings", headers=headers).json()["integrations"][0]
    response = client.put(
        f"/api/v1/settings/integrations/{identifier}",
        headers=headers,
        json={
            "kind": "ollama",
            "name": "Ollama Cloud",
            "config": {"base_url": "https://ollama.com"},
            "secrets": {"api_key": secrets.token_urlsafe(32)},
            "expected_version": item["version"],
        },
    )
    assert response.status_code == 200
    saved = client.get("/api/v1/settings", headers=headers).json()["integrations"][0]
    assert not saved.get("check_result")
