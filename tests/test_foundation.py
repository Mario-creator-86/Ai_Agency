import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.config import Settings
from app.db import create_db_engine, migrate
from app.main import create_app
from app.models import Base, CommandRecord, DomainEvent
from app.schemas import PolicyCommand
from app.services import (
    CommandConflict,
    bootstrap_studio,
    change_stop,
    read_events,
    snapshot,
)
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


def stop_command(version=1, stopped=False):
    return PolicyCommand(command_id=uuid4(), expected_version=version, stopped=stopped)


@pytest.mark.parametrize("path", ["/api/v1/snapshot", "/api/v1/events"])
def test_owner_reads_require_auth(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401


def test_health_scope_and_host_boundary(client):
    assert client.get("/health/live").json()["status"] == "HEALTHY"
    ready = client.get("/health/ready")
    assert ready.json()["scope"] == "FOUNDATION_API_AND_DATABASE"
    assert ready.headers["X-Correlation-ID"]
    assert client.get("/health/live", headers={"Host": "evil.example"}).status_code == 400


def test_built_frontend_and_security_headers(client):
    response = client.get("/")
    assert response.status_code == 200
    assert 'id="owner-token"' in response.text
    assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    directives = {
        parts[0]: parts[1:]
        for directive in response.headers["Content-Security-Policy"].split(";")
        if (parts := directive.split())
    }
    assert set(directives["img-src"]) == {
        "'self'",
        "data:",
        "https://yt3.ggpht.com",
        "https://yt3.googleusercontent.com",
    }
    assert directives["script-src"] == ["'self'"]
    assert directives["connect-src"] == ["'self'"]
    # The brand assets the page actually references must be served, not a stale icon.
    for asset in ("/favicon.ico", "/favicon-32.png", "/apple-touch-icon.png", "/amn-ai-mark.png"):
        assert client.get(asset).status_code == 200, asset
    assert "AMN-AI" in response.text


def test_unmigrated_database_fails_closed(settings):
    with pytest.raises(Exception, match="alembic_version"):
        with TestClient(create_app(settings)):
            pass


def test_snapshot_is_real_and_no_secrets(client, headers, settings):
    response = client.get("/api/v1/snapshot", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["cursor"] == 2
    assert data["policy"]["autonomy_stopped"] is True
    assert data["modules"]["agents"] == "IMPLEMENTED"
    assert data["modules"]["media"] == "PARTIAL"
    assert data["modules"]["treasury"] == "PARTIAL"
    assert data["modules"]["procurement"] == "NOT_IMPLEMENTED"
    assert data["office"]["rooms"][0]["event_id"] == data["events"][1]["event_id"]
    assert settings.owner_token.get_secret_value() not in response.text
    assert data["captured_at"].endswith("+00:00")
    assert response.headers["Cache-Control"] == "no-store"


def test_stop_endpoint_auth_validation_and_idempotency(client, headers):
    command = stop_command().model_dump(mode="json")
    assert client.post("/api/v1/owner/autonomy-stop", json=command).status_code == 401
    result = client.post("/api/v1/owner/autonomy-stop", json=command, headers=headers)
    assert result.status_code == 200
    assert result.json()["status"] == "COMMITTED"
    assert result.json()["policy"]["autonomy_mode"] == "MANUAL"
    assert result.json()["policy"]["external_payments_enabled"] is False
    retry = client.post("/api/v1/owner/autonomy-stop", json=command, headers=headers)
    assert retry.json() == result.json()
    command["stopped"] = True
    assert (
        client.post("/api/v1/owner/autonomy-stop", json=command, headers=headers).status_code == 409
    )
    command["command_id"] = str(uuid4())
    command["stopped"] = "false"
    assert (
        client.post("/api/v1/owner/autonomy-stop", json=command, headers=headers).status_code == 422
    )
    command["stopped"] = True
    command["public_publish_enabled"] = True
    assert (
        client.post("/api/v1/owner/autonomy-stop", json=command, headers=headers).status_code == 422
    )


def test_stop_and_restart_preserve_policy(engine, settings, headers):
    first = change_stop(engine, stop_command())
    second = change_stop(engine, stop_command(first.policy.version, True))
    with TestClient(create_app(settings)) as restarted:
        current = restarted.get("/api/v1/snapshot", headers=headers).json()
    assert current["policy"]["autonomy_stopped"] is True
    assert current["policy"]["version"] == second.policy.version
    assert current["events"][-1]["event_id"] == second.event_id


def test_bootstrap_is_idempotent_and_preserves_existing_studio(engine, settings):
    settings.name = "Changed environment default"
    bootstrap_studio(engine, settings)
    assert snapshot(engine)["cursor"] == 2
    assert snapshot(engine)["studio"]["name"] == "AMN-AI"


def test_renaming_the_studio_is_explicit_idempotent_and_audited(engine):
    """Bootstrap never rewrites an existing name, so a rename is its own recorded decision."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    from rename_studio import rename_studio

    before = snapshot(engine)["cursor"]
    assert "no changes written" in rename_studio(engine, "Renamed Agency", dry_run=True)
    assert snapshot(engine)["studio"]["name"] == "AMN-AI"
    assert snapshot(engine)["cursor"] == before, "a dry run writes nothing"

    def renames():
        with Session(engine) as session:
            return session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == "studio.renamed")
            ).all()

    rename_studio(engine, "Renamed Agency")
    assert snapshot(engine)["studio"]["name"] == "Renamed Agency"
    recorded = renames()
    assert len(recorded) == 1
    assert recorded[0].payload["previous_name"] == "AMN-AI"
    assert recorded[0].aggregate_version == 2, "the rename follows studio.created at version 1"

    # Repeating it changes nothing and appends no second event.
    assert "already named" in rename_studio(engine, "Renamed Agency")
    assert len(renames()) == 1

    for refused in ("", "   ", "x" * 101):
        with pytest.raises(SystemExit):
            rename_studio(engine, refused)


def test_migration_repeat_and_schema_match(engine):
    migrate(engine)
    with engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []


def test_table_rebuild_migration_succeeds_when_rows_reference_the_table(settings):
    """A batch migration rebuilds a table; rows in other tables that point at it must not
    stop it. This is the live studio's shape: channels with brand assets bound to them.
    Migrating passed on an empty database and failed on the Owner's, so the fixture is
    the referencing row, and the engine is the real one (foreign keys enforced)."""
    old = create_db_engine(settings.database_url)
    migrate(old, "0020_character_persona")
    channel, asset = str(uuid4()), str(uuid4())
    with old.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO channel_record (id, channel_name, channel_type, platform, "
                "upload_privacy_default, status, created_at) VALUES "
                "(:id, 'Bound channel', 'MAIN_FACTUAL', 'YOUTUBE', 'PRIVATE', 'UNCONFIGURED', "
                "'2026-09-11T00:00:00+00:00')"
            ),
            {"id": channel},
        )
        connection.execute(
            text(
                "INSERT INTO channel_brand_asset (id, channel_id, asset_type, content_or_uri, "
                "created_at) VALUES (:id, :channel, 'TAGLINE', 'x', '2026-09-11T00:00:00+00:00')"
            ),
            {"id": asset, "channel": channel},
        )
    migrate(old)
    with old.connect() as connection:
        # Head moved past 0021; what matters is that the rebuild in 0021 was crossed.
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) >= (
            "0022_agent_identity_memory"
        )
        # Enforcement is back on for later work, and the rebuilt table kept its rows.
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall() == []
        assert (
            connection.scalar(
                text("SELECT channel_id FROM channel_brand_asset WHERE id = :id"), {"id": asset}
            )
            == channel
        )
        assert (
            connection.scalar(
                text("SELECT production_policy FROM channel_record WHERE id = :id"), {"id": channel}
            )
            is None
        )
    old.dispose()


def test_stale_write_conflict_and_no_change_audit(engine):
    unchanged = change_stop(engine, stop_command(stopped=True))
    assert unchanged.status == "NO_CHANGE" and unchanged.event_id is None
    change_stop(engine, stop_command())
    with pytest.raises(CommandConflict):
        change_stop(engine, stop_command())
    assert snapshot(engine)["cursor"] == 3
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(CommandRecord)) == 2


def test_concurrent_duplicate_command_commits_once(engine):
    command = stop_command()
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda _: change_stop(engine, command), range(12)))
    assert len({result.event_id for result in results}) == 1
    assert snapshot(engine)["cursor"] == 3


def test_concurrent_stale_commands_only_one_wins(engine):
    def attempt(_):
        try:
            return change_stop(engine, stop_command()).status
        except CommandConflict:
            return "CONFLICT"

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(attempt, range(4)))
    assert results.count("COMMITTED") == 1
    assert results.count("CONFLICT") == 3


def test_failed_event_rolls_back_policy_and_command(engine, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("Injected failure before commit")

    monkeypatch.setattr("app.services.append_event", fail)
    with pytest.raises(RuntimeError):
        change_stop(engine, stop_command())
    current = snapshot(engine)
    assert current["policy"]["version"] == 1
    assert current["policy"]["autonomy_stopped"] is True
    assert current["cursor"] == 2
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(CommandRecord)) == 0


@pytest.mark.parametrize("table", ["domain_event", "command_record"])
@pytest.mark.parametrize("action", ["UPDATE", "DELETE"])
def test_history_is_immutable(engine, table, action):
    change_stop(engine, stop_command())
    query = (
        f"DELETE FROM {table}"
        if action == "DELETE"
        else (
            f"UPDATE {table} SET "
            + ("schema_version=2" if table == "domain_event" else "command_type='changed'")
        )
    )
    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text(query))


def test_events_pagination_and_query_validation(client, headers, engine):
    change_stop(engine, stop_command())
    first = client.get("/api/v1/events?after=0&limit=2", headers=headers).json()
    assert first["has_more"] is True and first["next_cursor"] == 2
    second = client.get("/api/v1/events?after=2&limit=2", headers=headers).json()
    assert len(second["events"]) == 1 and second["has_more"] is False
    assert read_events(engine, 3, 2)["events"] == []
    for query in ("after=-1", "limit=0", "limit=301", "after=abc"):
        assert client.get(f"/api/v1/events?{query}", headers=headers).status_code == 422


def test_request_validation_does_not_echo_private_input(client, headers):
    value = "private-untrusted-input"
    response = client.post(
        "/api/v1/owner/autonomy-stop", headers=headers, json={"command_id": value}
    )
    assert response.status_code == 422
    assert value not in response.text


def test_database_outage_is_not_healthy(client, engine):
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE owner_policy RENAME TO unavailable_policy"))
    assert client.get("/health/ready").status_code == 503


def test_configuration_rejects_weak_secret_and_invalid_timezone():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, owner_token="short")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, owner_token="x" * 48, timezone="Invalid/Zone")
    with pytest.raises(ValueError):
        create_db_engine("sqlite:///:memory:")


def test_error_logs_do_not_contain_token_or_input(client, headers, monkeypatch, capsys):
    def fail(_):
        raise RuntimeError(headers["Authorization"])

    monkeypatch.setattr("app.main.snapshot", fail)
    result = client.get("/api/v1/snapshot?private=hidden", headers=headers)
    assert result.status_code == 500
    assert headers["Authorization"] not in result.text
    logged = capsys.readouterr().err
    assert headers["Authorization"] not in logged
