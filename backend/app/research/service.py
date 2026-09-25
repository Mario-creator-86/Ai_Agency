"""Owner-initiated retrieval of a public source, from the interface rather than a shell.

The retrieval policy is never built from anything a fetch request supplied. Its hosts come from
two places the Owner controls: the configuration file (`STUDIO_RESEARCH_ALLOWED_HOSTS`) and the
`research_allowed_host` table, written only through Owner-authenticated endpoints. A fetch
request that named its own host would be a request-controlled allowlist, which is no allowlist
at all; that is why the host is a separate, authenticated action with its own test.

The test matters as much as the entry: an authorised site the studio cannot actually read (a
bot wall, a script-only page, a redirect off the host) is not a source, and the Owner should
see that before a research stage silently finds nothing there.

How pages are found (measured 2026-09-18, before this revision: 14 of 36 authorised hosts
failed retrieval, only en/ro Wikipedia carried a search address, the last live run fetched 0
pages): the studio asks, in this order, the search addresses the Owner typed, the ones it
discovered on the hosts' own front pages when they were tested, and a web search API the
Owner connected — whose answers are filtered to the allowlist before anything is stored and
read by the studio's own retriever, never through the engine's copy.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.config import Settings, validate_public_host
from app.factual.models import FactualClaim, SourceSnapshot
from app.factual.services import ingest_source_snapshot
from app.integrations.models import Integration
from app.integrations.vault import CredentialVault
from app.providers.search import SearchProvider, SearchProviderError
from app.research.models import ResearchAllowedHost
from app.research.retrieval import (
    RateLimited,
    RetrievalError,
    RetrievalPolicy,
    SourceRetriever,
    validate_url,
)
from app.services import append_event, utc_now
from app.wording import count, host_test_detail, written_for_the_owner

logger = logging.getLogger("amn.research")

#: Where the words go in a site's search address.
QUERY_PLACEHOLDER = "{query}"
#: The OpenSearch placeholder for the same thing, as descriptions write it.
_OPENSEARCH_TERMS = "{searchTerms}"
_SUGGESTIONS_TYPE = "application/x-suggestions+json"

#: Whose search address a host is using. The Owner's is a decision, the discovered one a
#: finding, and a finding never overrides a decision.
TEMPLATE_ORIGIN_OWNER = "OWNER"
TEMPLATE_ORIGIN_DISCOVERED = "DISCOVERED"

#: Why a host's last test FAILED, in a closed vocabulary the preflight can show.
REASON_HTTP_403 = "HTTP_403"
REASON_HTTP_ERROR = "HTTP_ERROR"
REASON_RATE_LIMITED = "RATE_LIMITED"
REASON_SCRIPT_ONLY = "SCRIPT_ONLY"
REASON_NETWORK = "NETWORK"
REASON_OTHER = "OTHER"

#: The health report's word for whether a web search API is connected and verified.
SEARCH_PROVIDER_VERIFIED = "VERIFIED"
SEARCH_PROVIDER_NONE = "NONE"

#: The research budget the runbook spends each day, until the integrator's settings
#: (``research_candidates_per_day``, ``research_pages_per_topic``) say otherwise. Four and
#: four: the previous literal two topics of three pages left the studio with 0 pages on a
#: day when two guessed plans both failed.
DEFAULT_CANDIDATES_PER_DAY = 4
DEFAULT_PAGES_PER_TOPIC = 4
MAX_BUDGET = 12
#: A host's test is re-run after this many days; a site that was readable a week ago may
#: have grown a bot wall since, and one that failed may have dropped it.
RETEST_AFTER_DAYS = 7
#: Fewer verified claims than this in the record and a film has nothing to rest on: a
#: thirty-second short uses three to five, and a day's verification lands a handful.
MIN_CLAIMS_AVAILABLE = 10

ADDED_BY_OWNER = "owner"
ADDED_BY_ENV = "env"


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


def _rows(session: Session, settings: Settings) -> list[ResearchAllowedHost]:
    """The table's rows that count: the Owner's, and a file host's test row while the file
    still names it. A row kept for a host the Owner has since taken out of .env is a test
    result without an authorisation, and must not re-authorise the host."""
    from_file = set(settings.research_allowed_hosts)
    return [
        row
        for row in session.scalars(
            select(ResearchAllowedHost).order_by(ResearchAllowedHost.added_at)
        )
        if row.added_by != ADDED_BY_ENV or row.host in from_file
    ]


def allowed_hosts(settings: Settings, engine: Engine | None = None) -> tuple[str, ...]:
    """Every authorised host: the configuration file's, then the Owner's, without duplicates."""
    hosts = list(settings.research_allowed_hosts)
    if engine is not None:
        with Session(engine) as session:
            for row in _rows(session, settings):
                if row.host not in hosts:
                    hosts.append(row.host)
    return tuple(hosts)


def effective_search_template(row: ResearchAllowedHost) -> tuple[str | None, str | None]:
    """The address the studio searches this host with, and whose it is."""
    if row.search_template:
        return row.search_template, TEMPLATE_ORIGIN_OWNER
    if row.discovered_search_template:
        return row.discovered_search_template, TEMPLATE_ORIGIN_DISCOVERED
    return None, None


_TEST_FIELDS = (
    "last_test_at",
    "last_test_status",
    "last_test_detail",
    "last_test_reason",
    "search_template",
    "discovered_search_template",
    "discovered_at",
    "search_template_origin",
)


def allowed_host_rows(settings: Settings, engine: Engine | None) -> list[dict[str, Any]]:
    """The allowlist as the interface shows it: where each host came from and its last test."""
    rows: list[dict[str, Any]] = [
        {
            "host": host,
            "source": "env",
            "added_at": None,
            **dict.fromkeys(_TEST_FIELDS),
        }
        for host in settings.research_allowed_hosts
    ]
    if engine is None:
        return rows
    seen = {row["host"]: row for row in rows}
    with Session(engine) as session:
        for row in _rows(session, settings):
            view = _host_view(row)
            if row.host in seen:
                # Configured in both places: the file entry is shown with the test result.
                seen[row.host].update({k: v for k, v in view.items() if k in _TEST_FIELDS})
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
                host=clean, added_by=ADDED_BY_OWNER, added_at=utc_now(), event_id=event.event_id
            )
            session.add(row)
        elif row.added_by == ADDED_BY_ENV:
            # The file's host had a test row; from now on it is the Owner's entry too, and
            # stays authorised if the file drops it.
            row.added_by, row.added_at = ADDED_BY_OWNER, utc_now()
        session.flush()
        return _host_view(row)


def remove_allowed_host(engine: Engine, host: str, correlation_id: str = "") -> None:
    with Session(engine) as session, session.begin():
        row = session.get(ResearchAllowedHost, host.strip().lower())
        if row is None or row.added_by == ADDED_BY_ENV:
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


def _failure_reason(detail: str) -> str:
    """A closed-vocabulary reason from what the retriever said, for the preflight.

    Also reads a detail stored before ``last_test_reason`` existed (migration 0040): the
    Owner's studio holds sixteen «Source returned HTTP 403» rows and one Romanian «Site-ul
    limitează cererile (HTTP 429).» from 2026-09-11, each with the reason NULL.
    """
    if "HTTP 403" in detail:
        return REASON_HTTP_403
    if "HTTP 429" in detail:
        return REASON_RATE_LIMITED
    if "returned HTTP" in detail:
        return REASON_HTTP_ERROR
    if "network, TLS" in detail or "deadline" in detail:
        return REASON_NETWORK
    if "needs JavaScript" in detail or "empty, too short" in detail:
        # A page whose served HTML has no text is an application shell: everything it shows
        # a browser is drawn by scripts the studio does not run.
        return REASON_SCRIPT_ONLY
    return REASON_OTHER


SCRIPT_ONLY_DETAIL = (
    "Pagina se afișează doar cu JavaScript: HTML-ul servit nu conține text, ci un pachet de "
    "scripturi și o notă care cere activarea lor. Studioul citește HTML-ul servit."
)


def _test_words(status: str | None, reason: str | None, detail: str | None) -> tuple:
    """A FAILED row's reason and detail as the Owner reads them, whenever it was stored.

    A row tested before the reason column existed carries the retriever's English and no
    code; the code is derived from that text (`_failure_reason`) and the text said in
    Romanian (`app.wording.host_test_detail`), so the Research door and the preflight name
    the same reason. Read only: the record keeps what it had.
    """
    if status != "FAILED":
        return reason, detail
    raw = detail or ""
    code = reason or _failure_reason(raw)
    if raw and written_for_the_owner(raw):
        return code, raw
    return code, host_test_detail(code, raw)


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
    PASSED test says the site is usable as a source; a FAILED one says why it is not, with a
    reason code (``last_test_reason``) the preflight shows without parsing the detail.

    A PASSED test also looks for the host's own search address — the OpenSearch description
    its front page names, or ``/opensearch.xml`` — and records it as DISCOVERED. The Owner's
    address, when he typed one, is untouched and keeps winning.
    """
    clean = host.strip().lower()
    hosts = allowed_hosts(settings, engine)
    if clean not in hosts:
        raise HostError("Site-ul nu este autorizat; adaugă-l întâi")
    fetcher = retriever or SourceRetriever(RetrievalPolicy((clean,)))
    status, detail, reason, summary = "PASSED", "", None, {}
    # The retriever's own words, kept for whoever diagnoses the test (the event), never
    # shown to the Owner as the detail.
    raw_error: str | None = None
    discovered: str | None = None
    discovery_ran = False
    try:
        source = fetcher.fetch(f"https://{clean}/")
        if getattr(source, "scripts_required", False):
            status, reason, detail = "FAILED", REASON_SCRIPT_ONLY, SCRIPT_ONLY_DETAIL
        else:
            summary = {
                "title": source.title,
                "characters": len(source.text),
                "content_type": source.content_type,
                "url": source.url,
            }
            detail = f"Răspunde; titlu «{source.title[:80]}», {len(source.text)} caractere de text."
            discovered, discovery_ran = discover_search_template(clean, source, fetcher)
    except RateLimited as exc:
        status, reason, raw_error = "FAILED", REASON_RATE_LIMITED, str(exc)
        detail = host_test_detail(reason, raw_error, exc.retry_after)
    except RetrievalError as exc:
        status, raw_error = "FAILED", str(exc)
        reason = _failure_reason(raw_error)
        detail = (
            SCRIPT_ONLY_DETAIL
            if reason == REASON_SCRIPT_ONLY
            else host_test_detail(reason, raw_error)
        )
    except OSError as exc:
        status, reason = "FAILED", REASON_NETWORK
        raw_error = f"{type(exc).__name__}: {exc}".rstrip(": ")
        detail = host_test_detail(reason, "network, TLS")
    tested_at = utc_now()
    with Session(engine) as session, session.begin():
        row = session.get(ResearchAllowedHost, clean)
        if row is None:
            # A host from the configuration file has no row of its own; its test result and
            # its discovered address need one. Marked as the file's, so it is never shown as
            # the Owner's entry and never survives the file dropping the host.
            row = ResearchAllowedHost(host=clean, added_by=ADDED_BY_ENV, added_at=tested_at)
            session.add(row)
        row.last_test_at, row.last_test_status = tested_at, status
        row.last_test_detail, row.last_test_reason = detail[:2000], reason
        if discovery_ran:
            # What the front page says today replaces what it said last time, including
            # saying nothing: a discovered address that vanished is not kept on faith.
            row.discovered_search_template = discovered
            row.discovered_at = tested_at if discovered else None
        stored_discovery = row.discovered_search_template
        append_event(
            session,
            "research.host_tested",
            "research_allowed_host",
            clean,
            3,
            {
                "host": clean,
                "status": status,
                "reason": reason,
                "discovered_search_template": discovered is not None,
                **({"error_detail": raw_error[:500]} if raw_error else {}),
            },
            correlation_id or str(uuid4()),
        )
    return {
        "host": clean,
        "status": status,
        "reason": reason,
        "detail": detail,
        "tested_at": tested_at,
        "summary": summary,
        "discovered_search_template": stored_discovery,
    }


def retest_stale_hosts(
    engine: Engine,
    settings: Settings,
    max_age_days: int = RETEST_AFTER_DAYS,
    retriever: SourceRetriever | None = None,
    correlation_id: str = "",
) -> list[dict[str, Any]]:
    """Re-run the host test for every authorised host not tested in ``max_age_days``.

    For the daily runbook's weekly pass: each test is one front-page fetch and, when it
    passes, one or two small reads for the search address. A host tested this week is left
    alone, so the pass costs the sites nothing on the other six days.
    """
    cutoff = (datetime.now(UTC) - timedelta(days=max_age_days)).isoformat()
    results = []
    for row in allowed_host_rows(settings, engine):
        last = row["last_test_at"]
        if last is None or last < cutoff:
            results.append(
                test_allowed_host(engine, settings, row["host"], correlation_id, retriever)
            )
    return results


def _host_view(row: ResearchAllowedHost) -> dict[str, Any]:
    _, origin = effective_search_template(row)
    reason, detail = _test_words(row.last_test_status, row.last_test_reason, row.last_test_detail)
    return {
        "host": row.host,
        "source": row.added_by if row.added_by == ADDED_BY_ENV else "owner",
        "added_at": row.added_at,
        "last_test_at": row.last_test_at,
        "last_test_status": row.last_test_status,
        "last_test_detail": detail,
        "last_test_reason": reason,
        "search_template": row.search_template,
        "discovered_search_template": row.discovered_search_template,
        "discovered_at": row.discovered_at,
        "search_template_origin": origin,
    }


def _same_host_https(template: str, host: str) -> bool:
    parts = urlsplit(template.replace(QUERY_PLACEHOLDER, "probe"))
    return parts.scheme == "https" and (parts.hostname or "").lower() == host


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
        if not _same_host_https(value, clean):
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


class _OpenSearchUrls(HTMLParser):
    """The ``<Url type="application/x-suggestions+json" template=...>`` elements of a
    description. Read with the HTML parser on purpose: it takes the XML's tags and unescapes
    its attributes, and it has no entity expansion for a hostile document to exploit."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.templates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "url":
            return
        given = {key.lower(): (value or "") for key, value in attrs}
        if given.get("type", "").lower() == _SUGGESTIONS_TYPE and given.get("template", "").strip():
            self.templates.append(given["template"].strip())


def parse_opensearch_description(text: str, host: str) -> str | None:
    """The host's suggestions address from its OpenSearch description, in the studio's form.

    ``{searchTerms}`` becomes ``{query}``; optional parameters (``{count?}`` and the like)
    are dropped with their names; a template that still needs a parameter the studio cannot
    fill, or that is not https on this very host, is not an address the studio may use.
    """
    parser = _OpenSearchUrls()
    parser.feed(text[:100_000])
    for template in parser.templates:
        cleaned = re.sub(r"\{[^{}]*\?\}", "", template).replace(
            _OPENSEARCH_TERMS, QUERY_PLACEHOLDER
        )
        if QUERY_PLACEHOLDER not in cleaned:
            continue
        # The braces are plain characters to urlsplit, so the placeholder survives the
        # rebuild; parameters emptied by a dropped optional value go with their names.
        parts = urlsplit(cleaned)
        query = "&".join(pair for pair in parts.query.split("&") if pair and not pair.endswith("="))
        candidate = urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
        if (
            QUERY_PLACEHOLDER in candidate
            and not re.search(r"\{(?!query\})[^{}]*\}", candidate)
            and len(candidate) <= 500
            and _same_host_https(candidate, host)
        ):
            return candidate
    return None


def discover_search_template(host: str, page: Any, fetcher: Any) -> tuple[str | None, bool]:
    """Look for the host's own search address on its front page; (template, whether looked).

    The page's ``<link rel="search">`` addresses come first, resolved against the page and
    kept only on this host; ``/opensearch.xml`` is tried last. A retriever without
    ``describe_search`` (a stand-in built for pages alone) cannot look, and says so with
    ``False`` so the caller keeps what it had rather than clearing it.
    """
    describe = getattr(fetcher, "describe_search", None)
    if describe is None:
        return None, False
    policy = RetrievalPolicy((host,))
    candidates = [urljoin(page.url, href) for href in getattr(page, "search_links", ())]
    candidates.append(f"https://{host}/opensearch.xml")
    for address in dict.fromkeys(candidates):
        try:
            validate_url(address, policy)
        except RetrievalError:
            continue  # named on another host: not this site's own search
        try:
            described = describe(address)
        except (RetrievalError, RateLimited, OSError) as exc:
            logger.info("search_discovery_failed", extra={"host": host, "reason": str(exc)[:160]})
            continue
        template = parse_opensearch_description(described.text, host)
        if template:
            return template, True
    return None, True


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
        template = effective_search_template(row)[0] if row is not None else None
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


def _vault_for(engine: Engine) -> CredentialVault:
    # The vault sits next to the database, as main.py and the watchdog build it.
    return CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))


def _verified_search_row(session: Session) -> Integration | None:
    from app.media.factory import VERIFIED_STATUSES  # noqa: PLC0415

    return session.scalar(
        select(Integration)
        .where(Integration.kind == "search", Integration.status.in_(VERIFIED_STATUSES))
        .order_by(Integration.checked_at.desc())
    )


def verified_search_provider(
    engine: Engine, vault: CredentialVault | None = None
) -> SearchProvider | None:
    """The web search API the Owner connected and verified, or None.

    SAVED is not enough: the vendor must have accepted the key ("Verify access"), the same
    rule the media providers follow. The key is read from the vault here and nowhere else.
    """
    with Session(engine) as session:
        row = _verified_search_row(session)
        if row is None:
            return None
        config, encrypted = dict(row.config), row.encrypted_secrets
    secrets = (vault or _vault_for(engine)).decrypt(encrypted)
    try:
        return SearchProvider(config, str(secrets.get("api_key", "")))
    except SearchProviderError as exc:
        logger.warning("search_provider_misconfigured", extra={"reason": str(exc)[:160]})
        return None


def find_pages(
    settings: Settings,
    engine: Engine,
    queries: str | list[str],
    limit: int = 6,
    retriever: SourceRetriever | None = None,
    *,
    search: SearchProvider | None = None,
    report: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """Pages that exist for these words, from the sites' own searches and then the engine.

    Order: the Owner's search addresses, then the ones discovered on the hosts' front pages,
    then the verified web search API — asked only when the sites' own searches left the
    limit unfilled. Several short queries beat one long one: a site's suggestion search
    matches the start of a title, so "James Webb Space Telescope" finds pages and "How the
    James Webb Space Telescope Sees the First Galaxies" finds none. Each query is asked on
    each site until the limit is reached; the same page is never listed twice.

    The engine's results are filtered to the allowlist here, before anything downstream sees
    them; what is dropped is counted in ``report["search"]`` and logged, never fetched.
    Every page returned is an address: the text comes from the studio's own retriever.
    """
    wanted = [q for q in ([queries] if isinstance(queries, str) else list(queries)) if q]
    with Session(engine) as session:
        rows = _rows(session, settings)
        owner_hosts = [r.host for r in rows if r.search_template]
        discovered_hosts = [
            r.host for r in rows if not r.search_template and r.discovered_search_template
        ]
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    if report is not None:
        report["templates"] = 0
        report["search"] = None

    def full() -> bool:
        return len(found) >= limit

    for via, hosts in (
        (TEMPLATE_ORIGIN_OWNER, owner_hosts),
        (TEMPLATE_ORIGIN_DISCOVERED, discovered_hosts),
    ):
        if not hosts or not wanted or full():
            continue
        per_ask = max(1, limit // len(hosts))
        for query in wanted:
            for host in hosts:
                for page in search_pages(settings, engine, host, query, per_ask, retriever):
                    if page["url"] not in seen and not full():
                        seen.add(page["url"])
                        found.append({**page, "via": via.lower()})
                if full():
                    break
            if full():
                break
    if report is not None:
        report["templates"] = len(found)

    if wanted and not full():
        provider = search if search is not None else verified_search_provider(engine)
        if provider is not None:
            counts = {"queries": 0, "kept": 0, "dropped": 0}
            dropped: set[str] = set()
            policy = _policy(settings, engine)
            for query in wanted:
                counts["queries"] += 1
                try:
                    results = provider.search(query, limit=limit)
                except SearchProviderError as exc:
                    logger.info("search_provider_failed", extra={"reason": str(exc)[:160]})
                    break
                for result in results:
                    try:
                        _, host = validate_url(result.url, policy)
                    except RetrievalError:
                        # Outside the allowlist: never fetched. Counted once per address,
                        # however many queries the engine repeats it for.
                        if result.url not in dropped:
                            dropped.add(result.url)
                            counts["dropped"] += 1
                        continue
                    if result.url in seen:
                        continue
                    seen.add(result.url)
                    counts["kept"] += 1
                    found.append(
                        {
                            "url": result.url,
                            "title": result.title[:200],
                            "host": host,
                            "via": "search",
                        }
                    )
                    if full():
                        break
                if full():
                    break
            if counts["dropped"]:
                logger.info("search_results_dropped", extra=counts)
            if report is not None:
                report["search"] = counts
    return found[:limit]


def research_budget(settings: Any) -> tuple[int, int]:
    """(candidates a day, pages a topic), from the settings when they carry them.

    The two settings are the integrator's to add to ``config.py``; until then, and for a
    settings object that predates them, the documented defaults apply. Clamped so a typo
    cannot turn a research pass into a crawl.
    """
    candidates = getattr(settings, "research_candidates_per_day", DEFAULT_CANDIDATES_PER_DAY)
    pages = getattr(settings, "research_pages_per_topic", DEFAULT_PAGES_PER_TOPIC)
    return (
        max(1, min(int(candidates), MAX_BUDGET)),
        max(1, min(int(pages), MAX_BUDGET)),
    )


def research_health(engine: Engine, settings: Settings) -> dict[str, Any]:
    """How the studio stands for finding and reading pages, for the preflight and the Director.

    Computed from the record, probing nothing. Keys: ``hosts_total`` (authorised hosts,
    file and Owner), ``hosts_tested_ok`` (last test PASSED), ``hosts_with_template`` (a
    search address, the Owner's or discovered), ``hosts_failing`` (last test FAILED, each
    with its reason code and detail), ``search_provider`` (VERIFIED | NONE),
    ``claims_available`` (SUPPORTED claims in the record), and the verdict.

    DEGRADED when any of these holds, each named in ``degraded_reasons``:
    - no host is authorised, or none of the authorised hosts passed its test;
    - there is no way to find pages: no host has a search address and no web search API
      is verified (the Researcher would be back to guessing addresses that 404);
    - fewer than ``MIN_CLAIMS_AVAILABLE`` (10) SUPPORTED claims are in the record.
    Otherwise OK. A DEGRADED report is a fact for the preflight to show; it stops nothing by
    itself, because a day that finds nothing completes honestly with nothing.
    """
    rows = allowed_host_rows(settings, engine)
    tested_ok = [r for r in rows if r["last_test_status"] == "PASSED"]
    with_template = [r for r in rows if r["search_template_origin"] is not None]
    failing = [
        {
            "host": r["host"],
            "reason": r["last_test_reason"] or REASON_OTHER,
            "detail": (r["last_test_detail"] or "")[:200],
        }
        for r in rows
        if r["last_test_status"] == "FAILED"
    ]
    with Session(engine) as session:
        search_status = (
            SEARCH_PROVIDER_VERIFIED
            if _verified_search_row(session) is not None
            else SEARCH_PROVIDER_NONE
        )
        claims = int(
            session.scalar(
                select(func.count())
                .select_from(FactualClaim)
                .where(FactualClaim.status == "SUPPORTED")
            )
            or 0
        )
    reasons: list[str] = []
    if not rows:
        reasons.append("Niciun site autorizat pentru preluarea surselor.")
    elif not tested_ok:
        reasons.append("Niciun site autorizat nu a trecut testul de citire.")
    if not with_template and search_status == SEARCH_PROVIDER_NONE:
        reasons.append(
            "Studioul nu are cum să găsească pagini: niciun site nu are adresă de căutare "
            "(a ta sau descoperită) și niciun motor de căutare nu este verificat."
        )
    if claims < MIN_CLAIMS_AVAILABLE:
        reasons.append(
            "Doar "
            + count(claims, "afirmație verificată disponibilă", "afirmații verificate disponibile")
            + f" (minim {MIN_CLAIMS_AVAILABLE})."
        )
    return {
        "hosts_total": len(rows),
        "hosts_tested_ok": len(tested_ok),
        "hosts_with_template": len(with_template),
        "hosts_failing": failing,
        "search_provider": search_status,
        "claims_available": claims,
        "status": "DEGRADED" if reasons else "OK",
        "degraded_reasons": reasons,
    }


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
