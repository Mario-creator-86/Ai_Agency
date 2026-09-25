"""A site's failed reading test, said in Romanian with its reason code, the same in both places.

Measured on a copy of the Owner's studio (2026-09-25): sixteen authorised sites carried
«Source returned HTTP 403» (one «HTTP 401», one «Invalid or disallowed source URL», one
Romanian «Site-ul limitează cererile (HTTP 429).») with ``last_test_reason`` NULL: they were
tested on 2026-09-11, before migration 0040 added the column. The Research door printed «nu
poate fi citit · Source returned HTTP 403»; the preflight, reading NULL as OTHER, said «nu a
răspuns cu nimic utilizabil» about the same sites. What is asserted here:

- a test that fails now stores a Romanian detail (through ``app.wording``) and its reason
  code; the retriever's English goes to the event, where a person diagnosing it reads it;
- a row stored before the column existed is read with the reason its detail implies and a
  Romanian detail, so the door and the preflight say the same thing — without writing to it.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from app.integrations.vault import CredentialVault
from app.models import DomainEvent
from app.research.models import ResearchAllowedHost
from app.research.retrieval import RateLimited, RetrievalError
from app.research.service import (
    add_allowed_host,
    allowed_host_rows,
    research_health,
)
from app.research.service import test_allowed_host as host_test  # not a test of ours
from app.runbook.preflight import run_preflight
from app.services import utc_now
from app.wording import host_test_detail, written_for_the_owner
from sqlalchemy import select
from sqlalchemy.orm import Session


class Refusing:
    """A retriever whose front page answers with the given error, as the real one raises it."""

    def __init__(self, error: Exception) -> None:
        self.error = error

    def fetch(self, url: str, **_kwargs):
        raise self.error


@pytest.mark.parametrize(
    ("reason", "raw", "said"),
    [
        ("HTTP_403", "Source returned HTTP 403", "HTTP 403"),
        ("HTTP_ERROR", "Source returned HTTP 401", "HTTP 401"),
        ("HTTP_ERROR", "Source returned HTTP 500", "HTTP 500"),
        ("RATE_LIMITED", "", "HTTP 429"),
        ("NETWORK", "Source retrieval exceeded its deadline", "la timp"),
        ("NETWORK", "Source network, TLS or decoding operation failed", "Conexiunea"),
        # W33: an allowed https host is tested at https://<host>/, so these three can only be
        # an address the site sends the studio on to; never «your site breaks the rules»
        ("OTHER", "Invalid or disallowed source URL", "o formă pe care studioul nu o citește"),
        ("OTHER", "URL contains invalid characters or exceeds the length limit", "prea lungă"),
        ("OTHER", "Only configured public HTTPS hosts on port 443 are allowed", "din afara listei"),
        ("OTHER", "Compressed responses are not supported", "comprimate"),
        ("OTHER", "Source exceeds the response size limit", "mărimea"),
        ("OTHER", "something nobody wrote down", "nu a dat o pagină"),
    ],
)
def test_every_failure_is_a_romanian_sentence(reason, raw, said):
    sentence = host_test_detail(reason, raw)
    assert said in sentence
    assert written_for_the_owner(sentence), sentence
    assert "Source" not in sentence and "returned" not in sentence
    assert sentence.endswith(".")
    assert "Adresa site-ului nu respectă" not in sentence


def test_a_403_now_is_stored_in_romanian_with_its_code(engine, settings):
    add_allowed_host(engine, "www.walled.test")
    result = host_test(
        engine,
        settings,
        "www.walled.test",
        retriever=Refusing(RetrievalError("Source returned HTTP 403")),
    )
    assert result["reason"] == "HTTP_403"
    assert "Source returned" not in result["detail"] and "HTTP 403" in result["detail"]
    row = next(r for r in allowed_host_rows(settings, engine) if r["host"] == "www.walled.test")
    assert row["last_test_reason"] == "HTTP_403"
    assert row["last_test_detail"] == result["detail"]
    # The retriever's own words are kept, as data, on the ledger line of the test.
    with Session(engine) as session:
        event = session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == "research.host_tested")
            .order_by(DomainEvent.sequence.desc())
        ).first()
    assert event.payload["error_detail"] == "Source returned HTTP 403"


def test_a_rate_limit_and_a_network_fault_are_romanian_too(engine, settings):
    add_allowed_host(engine, "www.busy.test")
    busy = host_test(engine, settings, "www.busy.test", retriever=Refusing(RateLimited("60")))
    assert busy["reason"] == "RATE_LIMITED" and "Retry-After" not in busy["detail"]
    assert "60" in busy["detail"] and written_for_the_owner(busy["detail"])

    add_allowed_host(engine, "www.gone.test")
    gone = host_test(engine, settings, "www.gone.test", retriever=Refusing(ConnectionResetError()))
    assert gone["reason"] == "NETWORK" and "ConnectionResetError" not in gone["detail"]


def legacy_rows(engine) -> None:
    """The rows as the Owner's studio holds them: tested before the reason column existed."""
    with Session(engine) as session, session.begin():
        for host, detail in (
            ("www.walled.test", "Source returned HTTP 403"),
            ("www.gated.test", "Source returned HTTP 401"),
            ("www.busy.test", "Site-ul limitează cererile (HTTP 429)."),
            ("www.odd.test", "Invalid or disallowed source URL"),
        ):
            session.add(
                ResearchAllowedHost(
                    host=host,
                    added_by="owner",
                    added_at=utc_now(),
                    last_test_at=utc_now(),
                    last_test_status="FAILED",
                    last_test_detail=detail,
                    last_test_reason=None,
                )
            )


def test_a_row_from_before_the_reason_column_reads_with_its_reason_and_in_romanian(
    engine, settings
):
    legacy_rows(engine)
    rows = {r["host"]: r for r in allowed_host_rows(settings, engine)}
    assert rows["www.walled.test"]["last_test_reason"] == "HTTP_403"
    assert rows["www.gated.test"]["last_test_reason"] == "HTTP_ERROR"
    assert rows["www.busy.test"]["last_test_reason"] == "RATE_LIMITED"
    assert rows["www.odd.test"]["last_test_reason"] == "OTHER"
    for row in rows.values():
        assert written_for_the_owner(row["last_test_detail"]), row
        assert "Source" not in row["last_test_detail"]
    # The Romanian a row already had is kept as it was written.
    assert rows["www.busy.test"]["last_test_detail"] == "Site-ul limitează cererile (HTTP 429)."

    # Nothing was written: the reading derives, the record keeps what it had.
    with Session(engine) as session:
        stored = session.get(ResearchAllowedHost, "www.walled.test")
        assert stored.last_test_reason is None
        assert stored.last_test_detail == "Source returned HTTP 403"


def test_the_research_door_and_the_preflight_now_say_the_same_reason(engine, settings, tmp_path):
    legacy_rows(engine)
    failing = {h["host"]: h for h in research_health(engine, settings)["hosts_failing"]}
    assert failing["www.walled.test"]["reason"] == "HTTP_403"
    assert "Source" not in failing["www.walled.test"]["detail"]

    vault = CredentialVault(tmp_path / f"{uuid4()}.key")
    sources = next(
        c
        for c in run_preflight(engine, settings, vault)["checks"]
        if c["name"] == "research_sources"
    )
    assert "www.walled.test — a refuzat studioul (403)" in sources["detail"]
    assert "www.gated.test — a răspuns cu o eroare" in sources["detail"]
    assert "www.busy.test — limitează cererile" in sources["detail"]
    # The door names the same reasons from the same rows.
    rows = {r["host"]: r["last_test_reason"] for r in allowed_host_rows(settings, engine)}
    for host, reason in rows.items():
        assert failing[host]["reason"] == reason
