"""The voice's commercial licence is read from the vendor's account (2026-10-10).

Film babcf272 could only go private: five narrations «nicio confirmare de folosire comercială»,
because the evidence was a «da» the Owner had to type on the ElevenLabs connection. His card:
«Da, citește singur». The studio reads the plan (a GET; faked here, never the network) and
records the licence when the plan is paid and active; a free or unknown plan records nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.integrations.models import Integration
from app.integrations.plan_licence import record_plan_licences
from app.media.factory import vendor_licence
from app.models import DomainEvent
from app.services import append_event
from sqlalchemy import select
from sqlalchemy.orm import Session


class Vault:
    def decrypt(self, _blob):
        return {"api_key": "xi-test-key"}  # pragma: allowlist secret - test fixture


def connection(engine, *, status="VERIFIED", config=None) -> str:
    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        saved = append_event(
            session, "settings.integration_saved", "integration", identifier, 1, {}, str(uuid4())
        )
        session.add(
            Integration(
                id=identifier,
                kind="elevenlabs",
                name="AMN-AI",
                config=dict(config or {}),
                encrypted_secrets="sealed",  # pragma: allowlist secret - test fixture
                secret_fields=["api_key"],
                version=1,
                status=status,
                event_id=saved.event_id,
            )
        )
    return identifier


def licence(engine, identifier: str) -> dict:
    with Session(engine) as session:
        return vendor_licence(session, identifier)


def test_a_paid_active_plan_records_the_commercial_licence_with_its_evidence(engine):
    identifier = connection(engine)
    asked: list[str] = []

    def plan(key):
        asked.append(key)
        return {"tier": "creator", "status": "active", "character_count": 10}

    result = record_plan_licences(engine, Vault(), read_plan=plan)

    assert result["recorded"] == [identifier] and asked == ["xi-test-key"]
    found = licence(engine, identifier)
    assert found["commercial_use"] is True
    assert "creator" in found["terms"] and "prin API" in found["terms"]
    with Session(engine) as session:
        events = list(
            session.scalars(
                select(DomainEvent).where(DomainEvent.event_type == "integrations.licence_recorded")
            )
        )
    assert len(events) == 1 and events[0].payload["tier"] == "creator"

    # Recorded: never read again.
    assert record_plan_licences(engine, Vault(), read_plan=plan) == {"recorded": [], "checked": []}
    assert asked == ["xi-test-key"]


def test_a_free_or_inactive_plan_records_nothing_and_is_read_again_only_an_hour_later(engine):
    free = connection(engine)
    calls: list[str] = []

    def plan(_key):
        calls.append("read")
        return {"tier": "free", "status": "active"}

    now = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)
    first = record_plan_licences(engine, Vault(), read_plan=plan, now=now)
    assert first["recorded"] == [] and first["checked"][0]["tier"] == "free"
    assert licence(engine, free)["commercial_use"] is None

    record_plan_licences(engine, Vault(), read_plan=plan, now=now + timedelta(minutes=40))
    assert calls == ["read"], "a free plan is not read again within the hour"
    record_plan_licences(engine, Vault(), read_plan=plan, now=now + timedelta(minutes=61))
    assert calls == ["read", "read"]


def test_a_cancelled_paid_plan_an_unknown_tier_and_a_failed_read_record_nothing(engine):
    cancelled = connection(engine)
    record_plan_licences(
        engine, Vault(), read_plan=lambda _k: {"tier": "pro", "status": "canceled"}
    )
    assert licence(engine, cancelled)["commercial_use"] is None

    unknown = connection(engine)
    record_plan_licences(engine, Vault(), read_plan=lambda _k: {"tier": "mystery"})
    assert licence(engine, unknown)["commercial_use"] is None

    def boom(_key):
        raise RuntimeError("vendor down")

    failing = connection(engine)
    assert record_plan_licences(engine, Vault(), read_plan=boom)["recorded"] == []
    assert licence(engine, failing)["commercial_use"] is None


def test_a_paid_plan_is_known_by_its_name_with_a_billing_suffix_and_free_never_is():
    from app.integrations.plan_licence import is_paid_tier

    assert all(is_paid_tier(t) for t in ("starter", "Creator", "creator_annual", "pro_2024"))
    assert not any(is_paid_tier(t) for t in ("", "free", "free_2024", "mystery", "creatorx"))


def test_a_connection_the_owner_already_answered_or_not_verified_is_never_read(engine):
    connection(engine, config={"commercial_use": "da"})
    connection(engine, status="FAILED")

    def never(_key):
        raise AssertionError("read a connection that needs no reading")

    assert record_plan_licences(engine, Vault(), read_plan=never) == {"recorded": [], "checked": []}
