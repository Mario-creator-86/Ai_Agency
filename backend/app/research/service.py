"""Owner-initiated retrieval of a public source, from the interface rather than a shell.

The retrieval policy itself is not built here from anything a request supplied. It is read from
the Owner's configuration, so the set of hosts the studio may reach is fixed outside the running
application: an endpoint that accepted a host alongside the URL would be a request-controlled
allowlist, which is no allowlist at all.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.factual.models import FactualClaim, SourceSnapshot
from app.factual.services import ingest_source_snapshot
from app.research.retrieval import (
    RetrievalError,
    RetrievalPolicy,
    SourceRetriever,
    validate_url,
)


class RetrievalNotConfigured(RuntimeError):
    """No host is allow-listed, so the studio may not fetch anything at all."""


class HostNotAllowed(ValueError):
    """The URL is well formed but its host is outside the Owner's allowlist."""


NOT_CONFIGURED_DETAIL = (
    "Preluarea surselor este dezactivată: nu ai autorizat niciun site. "
    "Adaugă gazdele permise în .env, la STUDIO_RESEARCH_ALLOWED_HOSTS "
    '(exemplu: STUDIO_RESEARCH_ALLOWED_HOSTS=["www.iana.org"]), apoi repornește studioul. '
    "Lista rămâne în fișierul de configurare — nici agenții, nici interfața nu o pot extinde."
)


def allowed_hosts(settings: Settings) -> tuple[str, ...]:
    return tuple(settings.research_allowed_hosts)


def _policy(settings: Settings) -> RetrievalPolicy:
    hosts = allowed_hosts(settings)
    if not hosts:
        raise RetrievalNotConfigured(NOT_CONFIGURED_DETAIL)
    return RetrievalPolicy(hosts)


def retrieve_and_ingest(
    engine: Engine,
    settings: Settings,
    url: str,
    correlation_id: str,
    topic_id: str | None = None,
    retriever: SourceRetriever | None = None,
) -> dict[str, Any]:
    """Fetch an allow-listed URL and store it as a source snapshot.

    Returns the stored snapshot together with the retrieval receipt — the resolved URL, the
    digest of the bytes that came back and of the extracted text, and the time of the fetch —
    so what is on screen can always be traced to what the studio actually downloaded.

    Nothing here judges the source. `credibility_score` stays 0 and every claim later extracted
    from it starts UNVERIFIED: fetching a page establishes that the page said something, not
    that it is true.
    """
    policy = _policy(settings)
    # Reject a host outside the allowlist before any network call, and distinguish it from a
    # source that simply did not answer, so the Owner knows which of the two happened.
    try:
        validate_url(url, policy)
    except RetrievalError as exc:
        raise HostNotAllowed(str(exc)) from exc

    source = (retriever or SourceRetriever(policy)).fetch(url)
    command = source.ingest_command(topic_id)
    snapshot = ingest_source_snapshot(
        engine,
        command.url,
        command.title,
        command.publisher,
        command.author,
        command.raw_content,
        command.credibility_score,
        correlation_id,
        topic_id=topic_id,
    )
    return {"source": snapshot, "receipt": source.receipt()}


def list_sources(engine: Engine) -> list[dict[str, Any]]:
    """Sources with a count of their claims per status, newest first."""
    with Session(engine) as session:
        counts: dict[str, dict[str, int]] = {}
        rows = session.execute(
            select(FactualClaim.source_id, FactualClaim.status, func.count()).group_by(
                FactualClaim.source_id, FactualClaim.status
            )
        ).all()
        for source_id, status, total in rows:
            counts.setdefault(source_id, {})[status] = total

        return [
            {
                "id": row.id,
                "topic_id": row.topic_id,
                "url": row.url,
                "title": row.title,
                "publisher": row.publisher,
                "author": row.author,
                "content_hash": row.content_hash,
                "credibility_score": row.credibility_score,
                "fetched_at": row.fetched_at,
                "characters": len(row.sanitized_content),
                "claim_counts": counts.get(row.id, {}),
            }
            for row in session.scalars(
                select(SourceSnapshot).order_by(SourceSnapshot.fetched_at.desc())
            )
        ]
