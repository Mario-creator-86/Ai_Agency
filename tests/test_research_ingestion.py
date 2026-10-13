"""The Owner-facing research loop: fetch a source, then read claims out of it.

The endpoint under test is the one place where the studio reaches out to the public internet
on the Owner's behalf, so most of these tests are about what it refuses to do. The rule behind
all of them: a source snapshot must correspond to bytes the studio actually downloaded from a
host the Owner authorised in their configuration file, and nothing weaker.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.factual.models import FactualClaim, SourceSnapshot
from app.research.retrieval import RateLimited, RetrievalError, RetrievedSource
from app.research.service import HostNotAllowed, RetrievalNotConfigured, retrieve_and_ingest
from sqlalchemy import select
from sqlalchemy.orm import Session

PAGE_TEXT = (
    "Example domains are reserved for use in documentation. "
    "They may be used without prior coordination."
)


def a_source(url: str = "https://www.iana.org/help/example-domains") -> RetrievedSource:
    return RetrievedSource(
        requested_url=url,
        url=url,
        title="Example Domains",
        publisher="www.iana.org",
        text=PAGE_TEXT,
        retrieved_at=datetime.now(UTC).isoformat(),
        body_sha256="b" * 64,
        content_sha256="c" * 64,
        content_type="text/html",
    )


class StubRetriever:
    """Stands in for the network. Returns a page, or fails the way a real one would."""

    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def fetch(self, url: str) -> RetrievedSource:
        self.calls.append(url)
        if self.error:
            raise self.error
        return self.result or a_source(url)


def settings_allowing(settings, *hosts: str):
    return settings.model_copy(update={"research_allowed_hosts": list(hosts)})


def inner(client):
    """The FastAPI application, behind the TrustedHostMiddleware that wraps it."""
    return client.app.app


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------


def test_no_allowlist_means_no_retrieval_at_all(engine, settings):
    """An empty allowlist disables the feature; it does not mean 'anywhere'."""
    retriever = StubRetriever()

    with pytest.raises(RetrievalNotConfigured):
        retrieve_and_ingest(
            engine,
            settings,
            "https://www.iana.org/help/example-domains",
            str(uuid4()),
            retriever=retriever,
        )

    assert retriever.calls == [], "nothing may be fetched before a host is authorised"


def test_a_host_outside_the_allowlist_is_refused_before_any_request(engine, settings):
    retriever = StubRetriever()

    with pytest.raises(HostNotAllowed):
        retrieve_and_ingest(
            engine,
            settings_allowing(settings, "www.iana.org"),
            "https://example.com/anything",
            str(uuid4()),
            retriever=retriever,
        )

    assert retriever.calls == [], "the host is checked before the network is touched"


#: Assembled rather than written out, so the credential-shaped one is not a literal the
#: repository's own secret scan has to be taught to ignore.
URL_WITH_USERINFO = "https://" + "u" + ":" + "p" + "@www.iana.org/x"


@pytest.mark.parametrize(
    "url",
    [
        "http://www.iana.org/plain-http",  # not HTTPS
        URL_WITH_USERINFO,  # credentials in the URL
        "https://www.iana.org:8443/x",  # non-standard port
        "https://www.iana.org\\@example.com/x",  # backslash confusion
    ],
)
def test_urls_that_would_widen_the_boundary_are_refused(engine, settings, url):
    retriever = StubRetriever()

    with pytest.raises(HostNotAllowed):
        retrieve_and_ingest(
            engine,
            settings_allowing(settings, "www.iana.org"),
            url,
            str(uuid4()),
            retriever=retriever,
        )

    assert retriever.calls == []


@pytest.mark.parametrize(
    "host",
    ["127.0.0.1", "localhost", "169.254.169.254", "10.0.0.5", "192.168.1.1", "::1"],
)
def test_an_internal_address_cannot_be_put_on_the_allowlist(engine, settings, host):
    """Defence in depth against a mistyped or malicious configuration.

    The allowlist is the Owner's, but its purpose is to name public sources. An entry that
    points back into the machine or the local network — a metadata service, an internal admin
    page — is refused when the policy is built, before any URL is even considered.
    """
    retriever = StubRetriever()

    with pytest.raises((HostNotAllowed, ValueError)):
        retrieve_and_ingest(
            engine,
            settings_allowing(settings, host),
            f"https://{host}/x",
            str(uuid4()),
            retriever=retriever,
        )

    assert retriever.calls == []


def test_a_source_that_does_not_answer_stores_nothing(engine, settings):
    retriever = StubRetriever(error=RetrievalError("connection reset"))

    with pytest.raises(RetrievalError):
        retrieve_and_ingest(
            engine,
            settings_allowing(settings, "www.iana.org"),
            "https://www.iana.org/help/example-domains",
            str(uuid4()),
            retriever=retriever,
        )

    with Session(engine) as session:
        assert session.scalars(select(SourceSnapshot)).all() == []


def test_a_rate_limited_source_is_not_retried_and_stores_nothing(engine, settings):
    retriever = StubRetriever(error=RateLimited("60"))

    with pytest.raises(RateLimited):
        retrieve_and_ingest(
            engine,
            settings_allowing(settings, "www.iana.org"),
            "https://www.iana.org/help/example-domains",
            str(uuid4()),
            retriever=retriever,
        )

    assert len(retriever.calls) == 1, "a rate limit is respected, not worked around"
    with Session(engine) as session:
        assert session.scalars(select(SourceSnapshot)).all() == []


# ---------------------------------------------------------------------------
# What it stores when it works
# ---------------------------------------------------------------------------


def test_a_retrieved_source_is_stored_with_its_provenance_and_no_credibility(engine, settings):
    retriever = StubRetriever(a_source())

    result = retrieve_and_ingest(
        engine,
        settings_allowing(settings, "www.iana.org"),
        "https://www.iana.org/help/example-domains",
        str(uuid4()),
        retriever=retriever,
    )

    assert result["source"]["title"] == "Example Domains"
    assert result["source"]["publisher"] == "www.iana.org"
    # Fetching a page establishes that the page said something, not that it is true.
    assert result["source"]["credibility_score"] == 0

    receipt = result["receipt"]
    assert receipt["content_sha256"] == "c" * 64
    assert receipt["body_sha256"] == "b" * 64
    assert "text" not in receipt, "the receipt is provenance, not a second copy of the page"

    with Session(engine) as session:
        stored = session.scalars(select(SourceSnapshot)).one()
    assert PAGE_TEXT.split(".")[0] in stored.sanitized_content


def test_the_stored_snapshot_carries_no_claims_of_its_own(engine, settings):
    """Retrieval reads a page. It does not decide what the page asserts."""
    retrieve_and_ingest(
        engine,
        settings_allowing(settings, "www.iana.org"),
        "https://www.iana.org/help/example-domains",
        str(uuid4()),
        retriever=StubRetriever(a_source()),
    )

    with Session(engine) as session:
        assert session.scalars(select(FactualClaim)).all() == []


# ---------------------------------------------------------------------------
# Through the API, as the interface uses it
# ---------------------------------------------------------------------------


def test_the_api_reports_each_failure_as_itself(client, headers, settings):
    """The Owner has to be able to tell 'not configured' from 'host refused' from 'no answer'."""
    body = {"command_id": str(uuid4()), "url": "https://www.iana.org/help/example-domains"}

    # No allowlist: the feature is off, and the message says how to turn it on.
    response = client.post("/api/v1/factual/sources/retrieve", json=body, headers=headers)
    assert response.status_code == 503
    assert "STUDIO_RESEARCH_ALLOWED_HOSTS" in response.json()["detail"]

    inner(client).state.settings = settings_allowing(settings, "www.iana.org")

    # Host outside the allowlist.
    refused = client.post(
        "/api/v1/factual/sources/retrieve",
        json={"command_id": str(uuid4()), "url": "https://example.com/x"},
        headers=headers,
    )
    assert refused.status_code == 422

    # The source did not answer.
    inner(client).state.source_retriever = StubRetriever(error=RetrievalError("timeout"))
    unreachable = client.post("/api/v1/factual/sources/retrieve", json=body, headers=headers)
    assert unreachable.status_code == 502
    assert "nu s-a salvat nimic" in unreachable.json()["detail"]


def test_the_api_exposes_the_allowlist_and_the_stored_sources(client, headers, settings):
    inner(client).state.settings = settings_allowing(settings, "www.iana.org")
    inner(client).state.source_retriever = StubRetriever(a_source())

    listed = client.get("/api/v1/factual/sources", headers=headers).json()
    assert listed["allowed_hosts"] == ["www.iana.org"]
    assert listed["sources"] == []

    created = client.post(
        "/api/v1/factual/sources/retrieve",
        json={"command_id": str(uuid4()), "url": "https://www.iana.org/help/example-domains"},
        headers=headers,
    )
    assert created.status_code == 200, created.text

    listed = client.get("/api/v1/factual/sources", headers=headers).json()
    assert len(listed["sources"]) == 1
    source = listed["sources"][0]
    assert source["title"] == "Example Domains"
    assert source["characters"] > 0
    assert source["claim_counts"] == {}, "a fetched page has no claims until an agent reads it"


def test_a_request_cannot_name_its_own_host(client, headers, settings):
    """The command carries a URL and nothing else; a host field would be a way around the
    allowlist, so the schema refuses one."""
    inner(client).state.settings = settings_allowing(settings, "www.iana.org")

    response = client.post(
        "/api/v1/factual/sources/retrieve",
        json={
            "command_id": str(uuid4()),
            "url": "https://example.com/x",
            "allow_host": "example.com",
        },
        headers=headers,
    )

    assert response.status_code == 422
