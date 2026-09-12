"""Owner-initiated retrieval of a public source, from the interface rather than a shell.

The retrieval policy is never built from anything a fetch request supplied. Its hosts come from
two places the Owner controls: the configuration file (`STUDIO_RESEARCH_ALLOWED_HOSTS`) and the
`research_allowed_host` table, written only through Owner-authenticated endpoints. A fetch
request that named its own host would be a request-controlled allowlist, which is no allowlist
at all; that is why the host is a separate, authenticated action with its own test.

The test matters as much as the entry: an authorised site the studio cannot actually read (a
bot wall, a script-only page, a redirect off the host) is not a source, and the Owner should
see that before a research stage silently finds nothing there.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import quote, urlsplit
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.config import Settings, validate_public_host
from app.factual.models import FactualClaim, SourceSnapshot
from app.factual.services import ingest_source_snapshot
from app.research.models import ResearchAllowedHost
from app.research.retrieval import (
    RateLimited,
    RetrievalError,
    RetrievalPolicy,
    SourceRetriever,
    validate_url,
)
from app.services import append_event, utc_now

logger = logging.getLogger("amn.research")

#: Where the words go in a site's search address.
QUERY_PLACEHOLDER = "{query}"


class RetrievalNotConfigured(RuntimeError):
    """No host is allow-listed, so the studio may not fetch anything at all."""


class HostNotAllowed(ValueError):
    """The URL is well formed but its host is outside the Owner's allowlist."""


NOT_CONFIGURED_DETAIL = (
    "Preluarea surselor este dezactivată: nu ai autorizat niciun site. "
    "Adaugă un site în Cercetare → Surse → «Site-uri autorizate» și testează-l, sau pune "
    'gazdele în .env la STUDIO_RESEARCH_ALLOWED_HOSTS (exemplu: ["www.iana.org"]). '
    "Doar Owner-ul poate extinde lista; agenții nu au nicio unealtă pentru asta."
)


class HostError(ValueError):
    """An allowlist entry that is not a bare public hostname, or does not exist."""


def allowed_hosts(settings: Settings, engine: Engine | None = None) -> tuple[str, ...]:
    """Every authorised host: the configuration file's, then the Owner's, without duplicates."""
    hosts = list(settings.research_allowed_hosts)
    if engine is not None:
        with Session(engine) as session:
            for row in session.scalars(
                select(ResearchAllowedHost).order_by(ResearchAllowedHost.added_at)
            ):
                if row.host not in hosts:
                    hosts.append(row.host)
    return tuple(hosts)


def allowed_host_rows(settings: Settings, engine: Engine | None) -> list[dict[str, Any]]:
    """The allowlist as the interface shows it: where each host came from and its last test."""
    rows: list[dict[str, Any]] = [
        {
            "host": host,
            "source": "env",
            "added_at": None,
            "last_test_at": None,
            "last_test_status": None,
            "last_test_detail": None,
            "search_template": None,
        }
        for host in settings.research_allowed_hosts
    ]
    if engine is None:
        return rows
    seen = {row["host"]: row for row in rows}
    with Session(engine) as session:
        for row in session.scalars(
            select(ResearchAllowedHost).order_by(ResearchAllowedHost.added_at)
        ):
            view = {
                "host": row.host,
                "source": "owner",
                "added_at": row.added_at,
                "last_test_at": row.last_test_at,
                "last_test_status": row.last_test_status,
                "last_test_detail": row.last_test_detail,
                "search_template": row.search_template,
            }
            if row.host in seen:
                # Configured in both places: the file entry is shown with the test result.
                seen[row.host].update(
                    {
                        k: v
                        for k, v in view.items()
                        if k.startswith("last_test") or k == "search_template"
                    }
                )
            else:
                rows.append(view)
    return rows


def add_allowed_host(engine: Engine, host: str, correlation_id: str = "") -> dict[str, Any]:
    """The Owner authorises a host. Validated like the configuration file's entries."""
    try:
        clean = validate_public_host(host.strip(), "Site-uri autorizate")
    except ValueError as exc:
        raise HostError(str(exc)) from None
    with Session(engine) as session, session.begin():
        row = session.get(ResearchAllowedHost, clean)
        if row is None:
            event = append_event(
                session,
                "research.host_authorised",
                "research_allowed_host",
                clean,
                1,
                {"host": clean},
                correlation_id or str(uuid4()),
            )
            row = ResearchAllowedHost(
                host=clean, added_by="owner", added_at=utc_now(), event_id=event.event_id
            )
            session.add(row)
        session.flush()
        return _host_view(row)


def remove_allowed_host(engine: Engine, host: str, correlation_id: str = "") -> None:
    with Session(engine) as session, session.begin():
        row = session.get(ResearchAllowedHost, host.strip().lower())
        if row is None:
            raise HostError("Site-ul nu este în lista Owner-ului (cele din .env se scot din .env)")
        append_event(
            session,
            "research.host_revoked",
            "research_allowed_host",
            row.host,
            2,
            {"host": row.host},
            correlation_id or str(uuid4()),
        )
        session.delete(row)


def test_allowed_host(
    engine: Engine,
    settings: Settings,
    host: str,
    correlation_id: str = "",
    retriever: SourceRetriever | None = None,
) -> dict[str, Any]:
    """Fetch the host's front page through the real retriever and record what happened.

    Nothing is stored as a source: this establishes whether the studio can read the site at
    all (DNS to a public address, TLS, an answer, HTML or text the extractor can use). A
    PASSED test says the site is usable as a source; a FAILED one says why it is not.
    """
    clean = host.strip().lower()
    hosts = allowed_hosts(settings, engine)
    if clean not in hosts:
        raise HostError("Site-ul nu este autorizat; adaugă-l întâi")
    fetcher = retriever or SourceRetriever(RetrievalPolicy((clean,)))
    status, detail, summary = "PASSED", "", {}
    try:
        source = fetcher.fetch(f"https://{clean}/")
        summary = {
            "title": source.title,
            "characters": len(source.text),
            "content_type": source.content_type,
            "url": source.url,
        }
        detail = f"Răspunde; titlu «{source.title[:80]}», {len(source.text)} caractere de text."
    except RateLimited as exc:
        status, detail = "FAILED", "Site-ul limitează cererile (HTTP 429)."
        if exc.retry_after:
            detail += f" Retry-After: {exc.retry_after}."
    except RetrievalError as exc:
        status, detail = "FAILED", str(exc)
    except OSError as exc:
        status, detail = "FAILED", f"Conexiunea a eșuat: {type(exc).__name__}"
    tested_at = utc_now()
    with Session(engine) as session, session.begin():
        row = session.get(ResearchAllowedHost, clean)
        if row is not None:
            row.last_test_at, row.last_test_status, row.last_test_detail = (
                tested_at,
                status,
                detail[:2000],
            )
        append_event(
            session,
            "research.host_tested",
            "research_allowed_host",
            clean,
            3,
            {"host": clean, "status": status},
            correlation_id or str(uuid4()),
        )
    return {
        "host": clean,
        "status": status,
        "detail": detail,
        "tested_at": tested_at,
        "summary": summary,
    }


def _host_view(row: ResearchAllowedHost) -> dict[str, Any]:
    return {
        "host": row.host,
        "source": "owner",
        "added_at": row.added_at,
        "last_test_at": row.last_test_at,
        "last_test_status": row.last_test_status,
        "last_test_detail": row.last_test_detail,
        "search_template": row.search_template,
    }


def set_search_template(
    engine: Engine, host: str, template: str | None, correlation_id: str = ""
) -> dict[str, Any]:
    """The Owner records a site's own search address, or clears it.

    The address is https on the same host and carries ``{query}`` where the words go. What it
    must answer is OpenSearch Suggestions JSON — ``[query, [titles], [descriptions], [urls]]``
    — the format encyclopaedias and documentation sites serve to any honest client.
    """
    clean = host.strip().lower()
    value = " ".join(str(template or "").split()) or None
    if value is not None:
        if QUERY_PLACEHOLDER not in value:
            raise HostError("Adresa de căutare trebuie să conțină {query} unde intră cuvintele")
        parts = urlsplit(value.replace(QUERY_PLACEHOLDER, "probe"))
        if parts.scheme != "https" or (parts.hostname or "").lower() != clean:
            raise HostError("Adresa de căutare trebuie să fie https, pe același site")
    with Session(engine) as session, session.begin():
        row = session.get(ResearchAllowedHost, clean)
        if row is None:
            raise HostError("Site-ul nu este în lista Owner-ului; adaugă-l întâi")
        row.search_template = value
        append_event(
            session,
            "research.search_configured",
            "research_allowed_host",
            clean,
            4,
            {"host": clean, "configured": value is not None},
            correlation_id or str(uuid4()),
        )
        session.flush()
        return _host_view(row)


def _parse_opensearch(text: str) -> list[dict[str, str]]:
    data = json.loads(text)
    if not (
        isinstance(data, list)
        and len(data) >= 4
        and isinstance(data[1], list)
        and isinstance(data[3], list)
    ):
        raise ValueError("Search answer is not OpenSearch JSON")
    return [
        {"url": url, "title": " ".join(str(title).split())}
        for title, url in zip(data[1], data[3], strict=False)
        if isinstance(url, str)
    ]


def search_pages(
    settings: Settings,
    engine: Engine,
    host: str,
    query: str,
    limit: int = 5,
    retriever: SourceRetriever | None = None,
) -> list[dict[str, str]]:
    """Ask one authorised site's search for these words; pages on authorised hosts only.

    A search that fails is an empty answer, logged, never an error: the Researcher still
    plans, from what he knows, and the letter says what was tried.
    """
    clean = host.strip().lower()
    with Session(engine) as session:
        row = session.get(ResearchAllowedHost, clean)
        template = row.search_template if row is not None else None
    words = " ".join(str(query).split())[:200]
    if not template or not words:
        return []
    policy = _policy(settings, engine)
    address = template.replace(QUERY_PLACEHOLDER, quote(words, safe=""))
    try:
        answer = (retriever or SourceRetriever(policy)).fetch(address, accept_json=True)
        found = _parse_opensearch(answer.text)
    except (RetrievalError, RateLimited, ValueError, OSError) as exc:
        logger.info("search_failed", extra={"host": clean, "reason": str(exc)[:160]})
        return []
    pages: list[dict[str, str]] = []
    for item in found:
        try:
            validate_url(item["url"], policy)
        except RetrievalError:
            continue
        pages.append({"url": item["url"], "title": item["title"][:200], "host": clean})
        if len(pages) >= limit:
            break
    return pages


def find_pages(
    settings: Settings,
    engine: Engine,
    queries: str | list[str],
    limit: int = 6,
    retriever: SourceRetriever | None = None,
) -> list[dict[str, str]]:
    """Pages that exist for these words, from every authorised site with a search address.

    Several short queries beat one long one: a site's suggestion search matches the start
    of a title, so "James Webb Space Telescope" finds pages and "How the James Webb Space
    Telescope Sees the First Galaxies" finds none. Each query is asked on each site until
    the limit is reached; the same page is never listed twice.
    """
    wanted = [queries] if isinstance(queries, str) else list(queries)
    with Session(engine) as session:
        hosts = [
            row.host
            for row in session.scalars(
                select(ResearchAllowedHost)
                .where(ResearchAllowedHost.search_template.is_not(None))
                .order_by(ResearchAllowedHost.added_at)
            )
        ]
    if not hosts or not wanted:
        return []
    per_ask = max(1, limit // len(hosts))
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for query in wanted:
        for host in hosts:
            for page in search_pages(settings, engine, host, query, per_ask, retriever):
                if page["url"] not in seen:
                    seen.add(page["url"])
                    found.append(page)
            if len(found) >= limit:
                return found[:limit]
    return found[:limit]


def _policy(settings: Settings, engine: Engine | None = None) -> RetrievalPolicy:
    hosts = allowed_hosts(settings, engine)
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
    policy = _policy(settings, engine)
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
