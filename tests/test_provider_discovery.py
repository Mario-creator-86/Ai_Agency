"""Local integration tests with stubbed HTTPS; not evidence of live ElevenLabs access."""

import asyncio
import json
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from app.db import create_db_engine, migrate
from app.integrations.discovery import refresh_catalog, refresh_due_catalogs
from app.integrations.models import (
    Integration,
    MediaProductionConfig,
    ProviderDiscovery,
    ProviderResource,
)
from app.integrations.services import SaveIntegration, save
from app.integrations.vault import CredentialVault
from app.main import create_app
from app.media.factory import tts_provider
from app.providers.elevenlabs import ElevenLabsTTSAdapter
from app.providers.media_http import MediaProviderError
from app.services import bootstrap_studio
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session


@pytest.fixture
def connected(client, headers, elevenlabs_api):
    identifier = str(uuid4())
    key = f"test-key-{uuid4()}"
    response = client.put(
        f"/api/v1/settings/integrations/{identifier}",
        headers=headers,
        json={
            "kind": "elevenlabs",
            "name": "Test ElevenLabs",
            "secrets": {"api_key": key},
        },
    )
    assert response.status_code == 200, response.text
    return identifier, key, response.json()


def vault_for(engine):
    return CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))


def catalog(client, headers, identifier):
    return client.get("/api/v1/settings", headers=headers).json()["provider_catalogs"][identifier]


def test_save_key_only_verifies_discovers_all_pages_and_survives_restart(
    connected, client, headers, engine, settings, elevenlabs_api
):
    identifier, key, saved = connected
    assert saved["status"] == "VERIFIED"
    assert saved["config"] == {}
    fields = client.get("/api/v1/settings", headers=headers).json()["catalog"]["elevenlabs"][
        "fields"
    ]
    assert [field["key"] for field in fields] == ["api_key"]
    assert saved["catalog"]["production"] == {
        "model_id": None,
        "voice_id": None,
        "image_model_id": None,
        "allow_production_override": True,
        "version": 0,
    }
    assert {r["remote_id"] for r in saved["catalog"]["models"]} == {
        elevenlabs_api.models[0]["model_id"]
    }
    assert {r["remote_id"] for r in saved["catalog"]["voices"]} == {
        v["voice_id"] for v in elevenlabs_api.voices
    }
    assert any("next_page_token=second-page" in path for path in elevenlabs_api.calls)
    assert key not in json.dumps(saved)
    with Session(engine) as session:
        row = session.get(Integration, identifier)
        assert key not in row.encrypted_secrets
        assert vault_for(engine).decrypt(row.encrypted_secrets)["api_key"] == key
    with TestClient(create_app(settings)) as restarted:
        assert catalog(restarted, headers, identifier) == catalog(client, headers, identifier)


def test_auth_failure_is_saved_truthfully_without_resource_ids(client, headers, elevenlabs_api):
    def fail(path):
        raise MediaProviderError("sensitive-vendor-response")

    elevenlabs_api.fail = fail
    response = client.put(
        f"/api/v1/settings/integrations/{uuid4()}",
        headers=headers,
        json={
            "kind": "elevenlabs",
            "name": "Bad key",
            "secrets": {"api_key": "test-invalid"},  # pragma: allowlist secret
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "FAILED"
    assert response.json()["catalog"]["models"] == []
    assert response.json()["catalog"]["voices"] == []
    assert "sensitive-vendor-response" not in response.text


def test_empty_successful_lists_are_not_replaced_by_defaults(
    connected, client, headers, elevenlabs_api
):
    identifier = connected[0]
    elevenlabs_api.models = []
    elevenlabs_api.voices = []
    result = client.post(
        f"/api/v1/settings/integrations/{identifier}/refresh-resources", headers=headers
    )
    assert result.json()["status"] == "VERIFIED"
    assert result.json()["discovery_status"] == "READY"
    current = catalog(client, headers, identifier)
    assert not any(r["available"] for r in current["models"] + current["voices"])


@pytest.mark.parametrize("malformed", [[{}], [{"model_id": ""}], {"models": []}])
def test_malformed_discovery_does_not_replace_last_success(
    connected, client, headers, elevenlabs_api, malformed
):
    identifier = connected[0]
    before = catalog(client, headers, identifier)
    elevenlabs_api.models = malformed
    result = client.post(
        f"/api/v1/settings/integrations/{identifier}/refresh-resources", headers=headers
    ).json()
    assert result["status"] == "VERIFIED"  # auth is independent of discovery
    assert result["discovery_status"] == "ERROR"
    after = catalog(client, headers, identifier)
    assert after["models"] == before["models"]
    assert after["voices"] == before["voices"]
    assert after["discovery"]["last_success_at"] == before["discovery"]["last_success_at"]


def test_late_voice_page_failure_keeps_whole_previous_catalog(
    connected, client, headers, elevenlabs_api
):
    identifier = connected[0]
    before = catalog(client, headers, identifier)

    def fail(path):
        if "next_page_token" in path:
            raise MediaProviderError("HTTP 429")

    elevenlabs_api.fail = fail
    response = client.post(
        f"/api/v1/settings/integrations/{identifier}/refresh-resources", headers=headers
    )
    assert response.json()["discovery_status"] == "ERROR"
    after = catalog(client, headers, identifier)
    assert after["models"] == before["models"] and after["voices"] == before["voices"]


def test_production_is_optional_and_only_accepts_discovered_compatible_resources(
    connected, client, headers, engine, elevenlabs_api
):
    identifier, _, saved = connected
    client.put(
        "/api/v1/settings/selections/voice",
        headers=headers,
        json={"integration_id": identifier, "expected_version": 0},
    )
    assert tts_provider(engine, vault_for(engine)) is None
    path = f"/api/v1/settings/integrations/{identifier}/production"
    assert (
        client.put(
            path, headers=headers, json={"model_id": "invented", "expected_version": 0}
        ).status_code
        == 422
    )
    model = elevenlabs_api.models[0]["model_id"]
    voice = elevenlabs_api.voices[0]["voice_id"]
    response = client.put(
        path, headers=headers, json={"model_id": model, "voice_id": voice, "expected_version": 0}
    )
    assert response.status_code == 200
    provider = tts_provider(engine, vault_for(engine))
    assert provider.model == model and provider.voice_id == voice
    with Session(engine) as session:
        row = session.get(Integration, identifier)
        assert row.status == "VERIFIED" and row.version == saved["version"] and row.config == {}
    assert client.put(path, headers=headers, json={"expected_version": 0}).status_code == 422
    elevenlabs_api.models[0]["can_do_text_to_speech"] = False
    client.post(f"/api/v1/settings/integrations/{identifier}/check", headers=headers)
    assert tts_provider(engine, vault_for(engine)) is None
    assert (
        client.put(
            path, headers=headers, json={"model_id": model, "expected_version": 1}
        ).status_code
        == 422
    )


def test_account_isolation_and_removed_voice_blocks_production(
    connected, client, headers, elevenlabs_api, engine
):
    first = connected[0]
    old_voice = elevenlabs_api.voices[0]["voice_id"]
    elevenlabs_api.voices = [{"voice_id": f"other-{uuid4()}", "name": "Other account voice"}]
    other = str(uuid4())
    client.put(
        f"/api/v1/settings/integrations/{other}",
        headers=headers,
        json={
            "kind": "elevenlabs",
            "name": "Other",
            "secrets": {"api_key": "other-test-key"},  # pragma: allowlist secret
        },
    )
    assert (
        client.put(
            f"/api/v1/settings/integrations/{other}/production",
            headers=headers,
            json={"voice_id": old_voice, "expected_version": 0},
        ).status_code
        == 422
    )
    before = catalog(client, headers, other)
    client.post(f"/api/v1/settings/integrations/{first}/refresh-resources", headers=headers)
    assert catalog(client, headers, other) == before
    assert not next(
        v for v in catalog(client, headers, first)["voices"] if v["remote_id"] == old_voice
    )["available"]


def test_research_fields_survive_refresh_and_cannot_invent_api_availability(
    connected, client, headers, elevenlabs_api, engine
):
    identifier = connected[0]
    resource = catalog(client, headers, identifier)["models"][0]
    path = f"/api/v1/settings/resources/{resource['id']}/metadata"
    payload = {
        "expected_version": 0,
        "pricing": {"amount": "0.25", "currency": "USD", "unit": "test-unit"},
        "capabilities": {"reviewed": True},
        "availability_override": False,
        "source": "https://example.invalid/accounting-evidence",
    }
    assert client.patch(path, json=payload).status_code == 401
    assert client.patch(path, headers=headers, json=payload).status_code == 200
    client.post(f"/api/v1/settings/integrations/{identifier}/refresh-resources", headers=headers)
    current = catalog(client, headers, identifier)["models"][0]
    assert (
        current["pricing"] == payload["pricing"]
        and current["capabilities"] == payload["capabilities"]
    )
    assert not current["available"] and current["api_available"]
    assert client.patch(path, headers=headers, json=payload).status_code == 422
    elevenlabs_api.models = []
    client.post(f"/api/v1/settings/integrations/{identifier}/refresh-resources", headers=headers)
    client.patch(
        path,
        headers=headers,
        json={
            "expected_version": 1,
            "availability_override": True,
            "source": "https://example.invalid/review",
        },
    )
    assert not catalog(client, headers, identifier)["models"][0]["available"]


def test_periodic_cache_retry_and_crash_lease_recovery(connected, engine, elevenlabs_api):
    identifier = connected[0]
    vault = vault_for(engine)
    elevenlabs_api.calls.clear()
    refresh_due_catalogs(engine, vault, interval_seconds=600, retry_seconds=60)
    assert elevenlabs_api.calls == []
    with Session(engine) as session, session.begin():
        state = session.get(ProviderDiscovery, identifier)
        state.next_refresh_at = state.lease_until = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
        state.lease_token, state.status = str(uuid4()), "SYNCING"
    refresh_due_catalogs(engine, vault, interval_seconds=600, retry_seconds=60)
    assert "/v1/models" in elevenlabs_api.calls
    with Session(engine) as session:
        state = session.get(ProviderDiscovery, identifier)
        assert state.status == "READY" and state.lease_token is None


def test_active_refresh_lease_suppresses_duplicate_requests(connected, engine, elevenlabs_api):
    identifier = connected[0]
    elevenlabs_api.calls.clear()
    with Session(engine) as session, session.begin():
        state = session.get(ProviderDiscovery, identifier)
        state.lease_until = (datetime.now(UTC) + timedelta(minutes=1)).isoformat()
    refresh_catalog(
        engine, vault_for(engine), identifier, interval_seconds=600, retry_seconds=60, force=True
    )
    assert elevenlabs_api.calls == []


def test_key_change_discards_inflight_results(connected, engine, elevenlabs_api):
    identifier = connected[0]

    def change(path):
        if path == "/v1/models":
            with Session(engine) as session:
                version = session.get(Integration, identifier).version
            save(
                engine,
                vault_for(engine),
                identifier,
                SaveIntegration(
                    kind="elevenlabs",
                    name="Changed",
                    secrets={"api_key": "replacement"},  # pragma: allowlist secret
                    expected_version=version,
                ),
            )

    elevenlabs_api.before_response = change
    with pytest.raises(ValueError, match="schimbat"):
        refresh_catalog(
            engine,
            vault_for(engine),
            identifier,
            interval_seconds=600,
            retry_seconds=60,
            force=True,
        )
    with Session(engine) as session:
        assert session.get(Integration, identifier).status == "SAVED"
        assert not any(session.scalars(select(ProviderResource.api_available)))


def test_voice_pagination_refuses_repeated_tokens(monkeypatch):
    from app.providers import elevenlabs

    def request(*args, **kwargs):
        return {"voices": [], "has_more": True, "next_page_token": "same"}, b"", "application/json"

    monkeypatch.setattr(elevenlabs, "request", request)
    with pytest.raises(MediaProviderError, match="pagination"):
        asyncio.run(ElevenLabsTTSAdapter("test-key").list_voices())


def test_synthesis_requires_an_explicit_model_without_calling_vendor(elevenlabs_api):
    from app.providers.media_http import MediaProviderNotConfigured

    with pytest.raises(MediaProviderNotConfigured, match="model ElevenLabs de producție"):
        asyncio.run(ElevenLabsTTSAdapter("test-key", voice_id="test-voice").synthesize("Narration"))
    assert elevenlabs_api.calls == []


def test_catalog_refresh_loop_runs_without_production_worker(engine, settings, monkeypatch):
    import app.main

    called = threading.Event()

    def refresh(*args, **kwargs):
        assert kwargs["interval_seconds"] == settings.provider_catalog_refresh_seconds
        called.set()

    monkeypatch.setattr(app.main, "refresh_due_catalogs", refresh)
    with TestClient(
        create_app(settings.model_copy(update={"provider_catalog_refresh_enabled": True}))
    ):
        assert called.wait(timeout=5)


def test_new_key_cannot_keep_previous_account_availability(
    connected, client, headers, elevenlabs_api
):
    identifier, _, saved = connected

    def fail(path):
        if path == "/v1/models":
            raise MediaProviderError("restricted key")

    elevenlabs_api.fail = fail
    response = client.put(
        f"/api/v1/settings/integrations/{identifier}",
        headers=headers,
        json={
            "kind": "elevenlabs",
            "name": "Changed key",
            "secrets": {"api_key": str(uuid4())},
            "expected_version": saved["version"],
        },
    )
    assert response.json()["status"] == "VERIFIED"
    assert response.json()["discovery_status"] == "ERROR"
    assert not any(r["available"] for r in response.json()["catalog"]["models"])
    assert not any(r["available"] for r in response.json()["catalog"]["voices"])


def test_migration_preserves_legacy_choices_without_claiming_discovery(settings):
    old = create_db_engine(settings.database_url)
    migrate(old, "0018_audit_gaps")
    bootstrap_studio(old, settings)
    from app.services import append_event, utc_now

    identifier = str(uuid4())
    with Session(old) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", identifier, 1, {}, str(uuid4())
        )
        session.add(
            Integration(
                id=identifier,
                kind="elevenlabs",
                name="Legacy",
                config={"model": "legacy-model", "voice_id": "legacy-voice"},
                encrypted_secrets="unchanged",  # pragma: allowlist secret
                secret_fields=["api_key"],
                version=1,
                status="ACCESS_VERIFIED",
                event_id=event.event_id,
            )
        )
    migrate(old)
    with Session(old) as session:
        production = session.get(MediaProductionConfig, identifier)
        assert production.model_id == "legacy-model" and production.voice_id == "legacy-voice"
        assert session.get(Integration, identifier).config == {}
        assert session.scalar(select(func.count()).select_from(ProviderResource)) == 0
        assert session.get(ProviderDiscovery, identifier).next_refresh_at <= utc_now()
    old.dispose()
