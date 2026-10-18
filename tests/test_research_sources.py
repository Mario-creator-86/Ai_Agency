"""Pages are found every day, inside the allowlist, and nothing is read through a third party.

Measured before this work: discovery ran only through the search address the Owner typed per
host, and only en/ro Wikipedia carried one; 14 of 36 authorised hosts failed retrieval; the
latest live run fetched 0 pages and verified 0 claims. What is asserted here:

- a host's own front page names its search address (``<link rel="search">`` or
  ``/opensearch.xml``) and the studio reads it when the host is tested; the Owner's address
  wins whenever both exist;
- a host that answers 403 or serves a script-only page is FAILED with a reason the preflight
  can show; the weekly retest touches stale hosts only;
- a search provider behind the allowlist returns addresses only: a result on a host outside
  the allowlist is dropped and counted, never fetched and never stored, and the page that is
  stored carries the text the studio's own retriever read, not the engine's copy;
- ``find_pages`` asks the Owner's addresses, then the discovered ones, then the search
  provider; when any of them returned pages the Researcher's guesses are not fetched;
- the health report is computed from the temp database and says DEGRADED when there is no
  way to find pages.

Every transport is faked: the pinned connection of the retriever, the search provider's
HTTPS request, and the language model. ``tests/conftest.py`` refuses any other socket.
"""

from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentMessage, ModelRecord
from app.agents.services import seed_initial_workforce
from app.factual.models import FactualClaim, SourceSnapshot, TopicIdea
from app.factual.schemas import ExtractClaimItem
from app.factual.services import extract_claims, ingest_source_snapshot, verify_claim
from app.integrations.catalog import CATALOG
from app.integrations.models import Integration
from app.integrations.services import SaveIntegration, save
from app.integrations.vault import CredentialVault
from app.models import OwnerPolicy
from app.providers import search as search_module
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.providers.search import SearchProvider, SearchProviderError
from app.research import retrieval as research
from app.research.agent import MAX_URLS, gather_sources
from app.research.models import ResearchAllowedHost
from app.research.retrieval import RetrievalError, RetrievedSource
from app.research.service import (
    DEFAULT_CANDIDATES_PER_DAY,
    DEFAULT_PAGES_PER_TOPIC,
    SEARCH_PROVIDER_NONE,
    SEARCH_PROVIDER_VERIFIED,
    add_allowed_host,
    allowed_host_rows,
    find_pages,
    parse_opensearch_description,
    research_budget,
    research_health,
    retest_stale_hosts,
    set_search_template,
)
from app.research.service import test_allowed_host as host_test  # not a test of ours
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

WIKI = "en.wikipedia.org"
OWNER_TEMPLATE = f"https://{WIKI}/w/api.php?action=opensearch&search={{query}}&limit=5&format=json"
DISCOVERED_TEMPLATE = f"https://{WIKI}/w/api.php?action=opensearch&search={{query}}&namespace=0"

FRONT_PAGE_WITH_LINK = (
    "<html><head><title>Wikipedia, the free encyclopedia</title>"
    '<link rel="search" type="application/opensearchdescription+xml" '
    'href="/w/opensearch_desc.php" title="Wikipedia (en)">'
    "</head><body><p>Welcome to Wikipedia, the free encyclopedia that anyone can edit."
    "</p></body></html>"
)
FRONT_PAGE_WITHOUT_LINK = (
    "<html><head><title>A plain site</title></head><body><p>Articles about the natural "
    "world, written for anyone who reads.</p></body></html>"
)
SCRIPT_ONLY_PAGE = (
    '<html><head><title>App</title><script src="/bundle.js"></script></head><body>'
    '<div id="root"></div><noscript>You need to enable JavaScript to run this app.'
    "</noscript></body></html>"
)
OPENSEARCH_XML = (
    '<?xml version="1.0"?>'
    '<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">'
    "<ShortName>Wikipedia (en)</ShortName>"
    '<Url type="text/html" method="get" '
    f'template="https://{WIKI}/w/index.php?title=Special:Search&amp;search={{searchTerms}}"/>'
    '<Url type="application/x-suggestions+json" method="get" '
    f'template="https://{WIKI}/w/api.php?action=opensearch&amp;search={{searchTerms}}'
    '&amp;namespace=0"/>'
    "</OpenSearchDescription>"
)


# --- the retriever's transport, faked the way tests/test_research_retrieval.py fakes it ---


class Response:
    def __init__(self, body: bytes, status: int = 200, content_type: str = "text/html") -> None:
        self.status = status
        self.headers = Message()
        self.headers["Content-Type"] = content_type + "; charset=utf-8"
        self.stream = io.BytesIO(body)
        self.length = None

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, limit):
        return self.stream.read(limit)


@pytest.fixture
def transport(monkeypatch):
    """Answers the pinned HTTPS connection with scripted responses; records what was asked."""
    monkeypatch.setattr(
        research.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.215.14", 443))]
    )
    responses: list[Response] = []
    asked: list[str] = []

    def connect(host, address, timeout):
        connection = MagicMock()

        def request(method, target, headers):
            asked.append(f"https://{host}{target}")

        connection.request.side_effect = request
        connection.getresponse.side_effect = lambda: responses.pop(0)
        return connection

    monkeypatch.setattr(research, "_PinnedHTTPS", connect)
    return SimpleNamespace(responses=responses, asked=asked)


def a_source(
    url: str, text: str = "Example domains are reserved for documentation."
) -> RetrievedSource:
    return RetrievedSource(
        requested_url=url,
        url=url,
        title="A page",
        publisher=url.split("/")[2],
        text=text,
        retrieved_at=datetime.now(UTC).isoformat(),
        body_sha256=hashlib.sha256(text.encode()).hexdigest(),
        content_sha256=hashlib.sha256(text.encode()).hexdigest(),
        content_type="text/html",
    )


class StubRetriever:
    """The older stand-in, with ``fetch(url)`` only: discovery must cope with it."""

    def __init__(self, pages: dict[str, str] | None = None, search_answer: str = "[]") -> None:
        self.pages = pages or {}
        self.search_answer = search_answer
        self.asked: list[str] = []

    def fetch(self, url: str, *, accept_json: bool = False) -> RetrievedSource:
        self.asked.append(url)
        if accept_json:
            return a_source(url, self.search_answer)
        if url in self.pages:
            return a_source(url, self.pages[url])
        raise RetrievalError("Source returned HTTP 404")


class Recorder:
    """Stands in for the search provider's HTTPS request, the way test_media_providers does."""

    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, host, method, path, headers, body=None, *, timeout=120, expect_json=True):
        self.calls.append({"host": host, "method": method, "path": path, "headers": headers})
        if not self.responses:
            raise AssertionError("the adapter made more requests than the test expected")
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class ScriptedModel:
    def __init__(self, answer) -> None:
        self.answer = answer
        self.calls: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.calls.append(prompt)
        return GenerateResult(self.answer(prompt), 10, 40, None)


SEARCH_CONFIG = {
    "endpoint": "https://api.search.test/v1/web",
    "auth_header": "X-Subscription-Token",
    "results_path": "web.results",
}


def search_answer(*items: tuple[str, str]) -> dict:
    """What a web search API answers: addresses, titles, and a cached copy the studio ignores."""
    return {
        "web": {
            "results": [
                {"url": url, "title": title, "content": "THE ENGINE'S COPY OF THE PAGE"}
                for url, title in items
            ]
        }
    }


def vault_for(engine) -> CredentialVault:
    return CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))


def connect_search(engine, status: str = "ACCESS_VERIFIED") -> str:
    """A search connection saved through the real flow, then marked as the check would."""
    identifier = str(uuid4())
    save(
        engine,
        vault_for(engine),
        identifier,
        SaveIntegration(
            kind="search",
            name="Web search",
            config=SEARCH_CONFIG,
            secrets={"api_key": "test-key-" + identifier},
        ),
    )
    with Session(engine) as session, session.begin():
        row = session.get(Integration, identifier)
        row.status, row.checked_at = status, utc_now()
    return identifier


@pytest.fixture
def studio(engine, settings):
    seed_initial_workforce(engine)
    add_allowed_host(engine, WIKI)
    add_allowed_host(engine, "www.unesco.org")
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
        for row in session.scalars(select(ResearchAllowedHost)):
            row.last_test_status, row.last_test_at = "PASSED", utc_now()
    with Session(engine) as session:
        provider_id = session.scalar(select(Agent.provider_id))
    return {"provider_id": provider_id}


def a_topic(engine, title="How UNESCO Tracks Endangered Languages", hosts=("www.unesco.org",)):
    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=identifier,
                title=title,
                topic="languages",
                angle="how the atlas is kept",
                target_audience="general",
                novelty_score=0.8,
                status="PROPOSED",
                created_at=utc_now(),
                source_plan_json=list(hosts),
            )
        )
    return identifier


def host_row(engine, host: str) -> dict:
    return next(
        r
        for r in allowed_host_rows(SimpleNamespace(research_allowed_hosts=[]), engine)
        if r["host"] == host
    )


# --- 1. template discovery ---------------------------------------------------------------


def test_the_front_page_names_its_search_address_and_the_test_records_it(
    engine, settings, transport
):
    add_allowed_host(engine, WIKI)
    transport.responses.extend(
        [
            Response(FRONT_PAGE_WITH_LINK.encode()),
            Response(OPENSEARCH_XML.encode(), content_type="application/opensearchdescription+xml"),
        ]
    )
    result = host_test(engine, settings, WIKI)
    assert result["status"] == "PASSED" and result["reason"] is None
    assert result["discovered_search_template"] == DISCOVERED_TEMPLATE
    # The description was read from the address the page named, resolved on the same host.
    assert transport.asked == [f"https://{WIKI}/", f"https://{WIKI}/w/opensearch_desc.php"]
    row = host_row(engine, WIKI)
    assert row["discovered_search_template"] == DISCOVERED_TEMPLATE
    assert row["search_template"] is None
    assert row["search_template_origin"] == "DISCOVERED"
    assert row["discovered_at"] is not None


def test_without_a_link_the_studio_tries_opensearch_xml_and_a_404_leaves_nothing(
    engine, settings, transport
):
    add_allowed_host(engine, "www.nature.test")
    transport.responses.extend(
        [
            Response(FRONT_PAGE_WITHOUT_LINK.encode()),
            Response(b"not here", status=404),
        ]
    )
    result = host_test(engine, settings, "www.nature.test")
    assert result["status"] == "PASSED" and result["discovered_search_template"] is None
    assert transport.asked[1] == "https://www.nature.test/opensearch.xml"
    assert host_row(engine, "www.nature.test")["search_template_origin"] is None


def test_the_owners_address_stays_the_owners_and_wins(engine, settings, transport):
    add_allowed_host(engine, WIKI)
    set_search_template(engine, WIKI, OWNER_TEMPLATE)
    transport.responses.extend(
        [
            Response(FRONT_PAGE_WITH_LINK.encode()),
            Response(OPENSEARCH_XML.encode(), content_type="application/opensearchdescription+xml"),
        ]
    )
    host_test(engine, settings, WIKI)
    row = host_row(engine, WIKI)
    assert row["search_template"] == OWNER_TEMPLATE
    assert row["discovered_search_template"] == DISCOVERED_TEMPLATE
    assert row["search_template_origin"] == "OWNER"
    # The search itself asks the Owner's address, not the discovered one.
    stub = StubRetriever(
        search_answer=json.dumps(["q", ["Fine"], [""], [f"https://{WIKI}/wiki/Fine"]])
    )
    assert (
        find_pages(settings, engine, "fine", retriever=stub)[0]["url"]
        == f"https://{WIKI}/wiki/Fine"
    )
    assert stub.asked == [OWNER_TEMPLATE.replace("{query}", "fine")]


@pytest.mark.parametrize(
    "xml, why",
    [
        (
            OPENSEARCH_XML.replace(f"https://{WIKI}/w/api.php", "https://evil.example/api"),
            "another host",
        ),
        (OPENSEARCH_XML.replace("https://", "http://"), "not https"),
        (OPENSEARCH_XML.replace("application/x-suggestions+json", "text/html"), "no suggestions"),
        ("<html>not a description at all</html>", "not a description"),
    ],
)
def test_a_description_that_is_not_the_hosts_own_suggestions_yields_nothing(xml, why):
    assert parse_opensearch_description(xml, WIKI) is None, why


def test_optional_parameters_are_dropped_and_the_words_placeholder_becomes_query():
    xml = OPENSEARCH_XML.replace(
        "{searchTerms}", "{searchTerms}&amp;count={count?}&amp;start={startIndex?}"
    )
    assert parse_opensearch_description(xml, WIKI) == (
        f"https://{WIKI}/w/api.php?action=opensearch&search={{query}}&namespace=0"
    )


def test_a_403_and_a_script_only_page_are_failed_with_a_reason(engine, settings, transport):
    add_allowed_host(engine, "www.walled.test")
    add_allowed_host(engine, "app.scripted.test")
    transport.responses.append(Response(b"forbidden", status=403))
    walled = host_test(engine, settings, "www.walled.test")
    assert walled["status"] == "FAILED" and walled["reason"] == "HTTP_403"

    transport.responses.append(Response(SCRIPT_ONLY_PAGE.encode()))
    scripted = host_test(engine, settings, "app.scripted.test")
    assert scripted["status"] == "FAILED" and scripted["reason"] == "SCRIPT_ONLY"
    assert "JavaScript" in scripted["detail"]
    # Nothing beyond the front page was asked of a host that cannot be read.
    assert transport.asked == ["https://www.walled.test/", "https://app.scripted.test/"]

    rows = {r["host"]: r for r in allowed_host_rows(settings, engine)}
    assert rows["www.walled.test"]["last_test_reason"] == "HTTP_403"
    assert rows["app.scripted.test"]["last_test_reason"] == "SCRIPT_ONLY"


def test_a_host_from_the_configuration_file_keeps_its_test_result_too(engine, settings, transport):
    env = settings.model_copy(update={"research_allowed_hosts": ["www.iana.org"]})
    transport.responses.append(Response(FRONT_PAGE_WITHOUT_LINK.encode()))
    transport.responses.append(Response(b"no", status=404))
    assert host_test(engine, env, "www.iana.org")["status"] == "PASSED"
    row = next(r for r in allowed_host_rows(env, engine) if r["host"] == "www.iana.org")
    assert row["source"] == "env" and row["last_test_status"] == "PASSED"
    # Still the file's entry: the interface cannot remove it.
    from app.research.service import HostError, remove_allowed_host

    with pytest.raises(HostError):
        remove_allowed_host(engine, "www.iana.org")


def test_the_weekly_retest_touches_stale_hosts_only(engine, settings):
    for host in ("fresh.test", "stale.test", "never.test"):
        add_allowed_host(engine, host)
    with Session(engine) as session, session.begin():
        session.get(ResearchAllowedHost, "fresh.test").last_test_at = utc_now()
        session.get(ResearchAllowedHost, "fresh.test").last_test_status = "PASSED"
        session.get(ResearchAllowedHost, "stale.test").last_test_at = (
            datetime.now(UTC) - timedelta(days=8)
        ).isoformat()
        session.get(ResearchAllowedHost, "stale.test").last_test_status = "PASSED"
    stub = StubRetriever({"https://stale.test/": "Some text.", "https://never.test/": "More."})
    results = retest_stale_hosts(engine, settings, retriever=stub)
    assert sorted(r["host"] for r in results) == ["never.test", "stale.test"]
    assert all(r["status"] == "PASSED" for r in results)
    assert "https://fresh.test/" not in stub.asked
    # The older stand-in cannot answer XML; discovery says so and leaves no template.
    assert host_row(engine, "stale.test")["discovered_search_template"] is None


# --- 2. the search provider behind the allowlist ---------------------------------------


def test_the_search_kind_is_declared_like_the_other_keyed_services():
    spec = CATALOG["search"]
    assert spec["runtime"] == "search"
    keys = {f["key"]: f for f in spec["fields"]}
    assert keys["api_key"]["secret"] and keys["endpoint"]["kind"] == "url"
    assert {"auth_header", "results_path"} <= set(keys)
    # The catalog says what the adapter guarantees: addresses only, read by the studio itself.
    assert "site-urile autorizate" in spec["help"]


def test_the_adapter_returns_addresses_only_and_the_probe_asks_one_word(monkeypatch):
    recorder = Recorder(
        (
            search_answer(("https://en.wikipedia.org/wiki/Hubble", "Hubble")),
            b"",
            "application/json",
        ),
        (search_answer(), b"", "application/json"),
        SearchProviderError("api.search.test refused the request (HTTP 401)"),
    )
    monkeypatch.setattr(search_module, "request", recorder)
    provider = SearchProvider(SEARCH_CONFIG, "k-1")
    results = provider.search("Hubble telescope", limit=5)
    assert [(r.url, r.title) for r in results] == [
        ("https://en.wikipedia.org/wiki/Hubble", "Hubble")
    ]
    assert not hasattr(results[0], "content"), "the engine's copy of a page is never carried"
    call = recorder.calls[0]
    assert call["host"] == "api.search.test" and call["path"].startswith(
        "/v1/web?q=Hubble%20telescope"
    )
    assert call["headers"]["X-Subscription-Token"] == "k-1"
    assert provider.probe() is True
    assert provider.probe() is False


def test_the_probe_is_wired_into_the_integrations_check(monkeypatch):
    from app.integrations.probes import probe

    recorder = Recorder((search_answer(), b"", "application/json"))
    monkeypatch.setattr(search_module, "request", recorder)
    assert probe("search", SEARCH_CONFIG, {"api_key": "k"}) is True
    assert recorder.calls[0]["headers"]["X-Subscription-Token"] == "k"


def test_a_bearer_header_carries_the_key_as_a_bearer_token(monkeypatch):
    recorder = Recorder((search_answer(), b"", "application/json"))
    monkeypatch.setattr(search_module, "request", recorder)
    SearchProvider({**SEARCH_CONFIG, "auth_header": "Authorization"}, "k-2").search("x")
    assert recorder.calls[0]["headers"]["Authorization"] == "Bearer k-2"


def test_a_result_off_the_allowlist_is_dropped_counted_and_never_fetched_or_stored(
    engine, settings, studio, monkeypatch
):
    connect_search(engine)
    answer = (
        search_answer(
            (f"https://{WIKI}/wiki/Endangered_language", "Endangered language"),
            ("https://evil.example/endangered", "Off the list"),
            ("http://en.wikipedia.org/wiki/Plain", "Not https"),
        ),
        b"",
        "application/json",
    )
    # One answer for the direct call below, then one per name the topic yields ("UNESCO
    # Tracks Endangered Languages", "UNESCO Tracks", "UNESCO"): the engine repeats itself.
    recorder = Recorder(answer, answer, answer, answer)
    monkeypatch.setattr(search_module, "request", recorder)
    stub = StubRetriever(
        {f"https://{WIKI}/wiki/Endangered_language": "UNESCO tracks endangered languages. An endangered language is one at risk."}
    )
    import app.research.service as service

    monkeypatch.setattr(service, "SourceRetriever", lambda policy: stub)

    report: dict = {}
    pages = find_pages(settings, engine, "Endangered language", report=report)
    assert [p["url"] for p in pages] == [f"https://{WIKI}/wiki/Endangered_language"]
    assert pages[0]["via"] == "search"
    assert report["search"] == {"queries": 1, "kept": 1, "dropped": 2}

    registry = ProviderRegistry()
    model = ScriptedModel(
        lambda prompt: json.dumps(
            {"urls": [{"url": f"https://{WIKI}/wiki/Endangered_language", "why": "found"}]}
        )
    )
    registry.register(studio["provider_id"], model)
    result = gather_sources(engine, registry, settings, a_topic(engine), str(uuid4()))
    assert [f["url"] for f in result["fetched"]] == [f"https://{WIKI}/wiki/Endangered_language"]
    assert result["found_via"]["search"]["dropped"] == 2
    # The dropped address was never asked of the retriever and is nowhere in the record.
    assert not any("evil.example" in url for url in stub.asked)
    with Session(engine) as session:
        stored = session.scalars(select(SourceSnapshot)).all()
        assert [s.url for s in stored] == [f"https://{WIKI}/wiki/Endangered_language"]
        # The page's text is what the studio read, not what the engine cached.
        assert "at risk" in stored[0].sanitized_content
        assert "ENGINE'S COPY" not in stored[0].sanitized_content


def test_without_a_verified_search_connection_no_search_request_is_made(
    engine, settings, studio, monkeypatch
):
    connect_search(engine, status="SAVED")
    recorder = Recorder()
    monkeypatch.setattr(search_module, "request", recorder)
    report: dict = {}
    assert find_pages(settings, engine, "anything", retriever=StubRetriever(), report=report) == []
    assert recorder.calls == [] and report["search"] is None


def test_find_pages_asks_owner_addresses_then_discovered_ones_then_the_search_provider(
    engine, settings, studio, monkeypatch
):
    set_search_template(engine, WIKI, OWNER_TEMPLATE)
    with Session(engine) as session, session.begin():
        session.get(
            ResearchAllowedHost, "www.unesco.org"
        ).discovered_search_template = "https://www.unesco.org/api/suggest?q={query}"
    connect_search(engine)
    recorder = Recorder(
        (
            search_answer((f"https://{WIKI}/wiki/From_search", "From search")),
            b"",
            "application/json",
        )
    )
    monkeypatch.setattr(search_module, "request", recorder)

    class ByHost(StubRetriever):
        def fetch(self, url, *, accept_json=False):
            self.asked.append(url)
            host = url.split("/")[2]
            page = f"https://{host}/page-{len(self.asked)}"
            return a_source(url, json.dumps(["q", ["T"], [""], [page]]))

    stub = ByHost()
    pages = find_pages(settings, engine, "words", limit=6, retriever=stub)
    assert [p["via"] for p in pages] == ["owner", "discovered", "search"]
    assert stub.asked[0].startswith(f"https://{WIKI}/w/api.php")
    assert stub.asked[1].startswith("https://www.unesco.org/api/suggest")
    assert pages[2]["url"] == f"https://{WIKI}/wiki/From_search"


def test_the_search_provider_is_not_asked_when_the_sites_own_searches_filled_the_limit(
    engine, settings, studio, monkeypatch
):
    set_search_template(engine, WIKI, OWNER_TEMPLATE)
    connect_search(engine)
    recorder = Recorder()
    monkeypatch.setattr(search_module, "request", recorder)
    answer = json.dumps(
        ["q", ["A", "B"], ["", ""], [f"https://{WIKI}/wiki/A", f"https://{WIKI}/wiki/B"]]
    )
    assert (
        len(
            find_pages(
                settings, engine, "words", limit=2, retriever=StubRetriever(search_answer=answer)
            )
        )
        == 2
    )
    assert recorder.calls == []


# --- 3. the Researcher does not guess when pages were found; the budget is a setting -----


def test_the_researcher_does_not_guess_when_pages_were_found(engine, settings, studio, monkeypatch):
    set_search_template(engine, WIKI, OWNER_TEMPLATE)
    found = f"https://{WIKI}/wiki/Endangered_language"
    stub = StubRetriever(
        {found: "UNESCO tracks endangered languages. An endangered language is at risk of disappearing."},
        search_answer=json.dumps(["q", ["Endangered language"], [""], [found]]),
    )
    import app.research.service as service

    monkeypatch.setattr(service, "SourceRetriever", lambda policy: stub)
    registry = ProviderRegistry()
    guess = "https://www.unesco.org/en/endangered-languages"
    model = ScriptedModel(lambda prompt: json.dumps({"urls": [{"url": guess, "why": "guess"}]}))
    registry.register(studio["provider_id"], model)

    result = gather_sources(engine, registry, settings, a_topic(engine), str(uuid4()))
    assert [f["url"] for f in result["fetched"]] == [found]
    assert result["failed"] == [{"url": guess, "why": result["failed"][0]["why"]}]
    assert "ghicit" in result["failed"][0]["why"]
    assert guess not in stub.asked, "a guess is not fetched when real pages exist"
    assert "prefer them" in model.calls[0] and "not fetched" in model.calls[0]
    with Session(engine) as session:
        assert session.scalar(select(AgentMessage).where(AgentMessage.intent == "ESCALATE")) is None


def test_with_nothing_found_the_researcher_still_names_pages_and_they_are_tried(
    engine, settings, studio, monkeypatch
):
    stub = StubRetriever({"https://www.unesco.org/en/atlas": "UNESCO tracks endangered languages in the atlas of languages in danger."})
    import app.research.service as service

    monkeypatch.setattr(service, "SourceRetriever", lambda policy: stub)
    registry = ProviderRegistry()
    registry.register(
        studio["provider_id"],
        ScriptedModel(
            lambda prompt: json.dumps(
                {"urls": [{"url": "https://www.unesco.org/en/atlas", "why": "a"}]}
            )
        ),
    )
    result = gather_sources(engine, registry, settings, a_topic(engine), str(uuid4()), limit=2)
    assert [f["url"] for f in result["fetched"]] == ["https://www.unesco.org/en/atlas"]


def test_the_budget_comes_from_settings_with_the_documented_defaults(settings):
    assert (DEFAULT_CANDIDATES_PER_DAY, DEFAULT_PAGES_PER_TOPIC) == (4, 4)
    assert research_budget(settings) == (4, 4)
    tuned = SimpleNamespace(research_candidates_per_day=6, research_pages_per_topic=3)
    assert research_budget(tuned) == (6, 3)
    assert MAX_URLS >= DEFAULT_PAGES_PER_TOPIC


def test_the_page_limit_is_read_from_settings_when_not_passed(
    engine, settings, studio, monkeypatch
):
    stub = StubRetriever(
        {f"https://www.unesco.org/en/p{i}": f"Page {i}: UNESCO tracks endangered languages in the atlas." for i in range(6)}
    )
    import app.research.service as service

    monkeypatch.setattr(service, "SourceRetriever", lambda policy: stub)
    registry = ProviderRegistry()
    registry.register(
        studio["provider_id"],
        ScriptedModel(
            lambda prompt: json.dumps(
                {"urls": [{"url": f"https://www.unesco.org/en/p{i}", "why": "a"} for i in range(6)]}
            )
        ),
    )
    tuned = settings.model_copy()
    object.__setattr__(tuned, "research_pages_per_topic", 3)
    result = gather_sources(engine, registry, tuned, a_topic(engine), str(uuid4()))
    assert len(result["fetched"]) == 3


# --- 4. the health report ----------------------------------------------------------------


def test_the_health_report_is_computed_from_the_record(engine, settings):
    env = settings.model_copy(update={"research_allowed_hosts": ["www.iana.org"]})
    empty = research_health(engine, env)
    assert empty["hosts_total"] == 1 and empty["hosts_tested_ok"] == 0
    assert empty["hosts_with_template"] == 0 and empty["hosts_failing"] == []
    assert empty["search_provider"] == SEARCH_PROVIDER_NONE and empty["claims_available"] == 0
    assert empty["status"] == "DEGRADED"
    assert any("găs" in reason for reason in empty["degraded_reasons"])

    add_allowed_host(engine, WIKI)
    add_allowed_host(engine, "www.walled.test")
    set_search_template(engine, WIKI, OWNER_TEMPLATE)
    with Session(engine) as session, session.begin():
        wiki = session.get(ResearchAllowedHost, WIKI)
        wiki.last_test_status, wiki.last_test_at = "PASSED", utc_now()
        walled = session.get(ResearchAllowedHost, "www.walled.test")
        walled.last_test_status, walled.last_test_at = "FAILED", utc_now()
        walled.last_test_reason, walled.last_test_detail = "HTTP_403", "Source returned HTTP 403"
    source = ingest_source_snapshot(
        engine,
        f"https://{WIKI}/wiki/Hubble",
        "Hubble",
        WIKI,
        None,
        "The Hubble Space Telescope was launched in 1990.",
        0,
        str(uuid4()),
    )
    claims = extract_claims(
        engine,
        source["id"],
        [ExtractClaimItem(claim_text=f"Claim {i} about Hubble.") for i in range(12)],
        str(uuid4()),
    )
    for claim in claims[:10]:
        verify_claim(
            engine, claim["id"], "SUPPORTED", 0.9, "test", "launched in 1990", str(uuid4())
        )
    verify_claim(engine, claims[10]["id"], "REFUTED", 0.9, "test", "launched in 1990", str(uuid4()))

    report = research_health(engine, env)
    assert report["hosts_total"] == 3 and report["hosts_tested_ok"] == 1
    assert report["hosts_with_template"] == 1
    # The retriever's English, stored as it was, is read back in Romanian (W31).
    assert report["hosts_failing"] == [
        {
            "host": "www.walled.test",
            "reason": "HTTP_403",
            "detail": "Site-ul a refuzat cererea studioului (HTTP 403); cât timp o refuză, nu "
            "poate fi sursă.",
        }
    ]
    assert report["search_provider"] == SEARCH_PROVIDER_NONE
    assert report["claims_available"] == 10
    assert report["status"] == "OK" and report["degraded_reasons"] == []

    connect_search(engine)
    assert research_health(engine, env)["search_provider"] == SEARCH_PROVIDER_VERIFIED
    with Session(engine) as session, session.begin():
        session.get(ResearchAllowedHost, WIKI).search_template = None
        for claim in session.scalars(select(FactualClaim)):
            claim.status = "UNCERTAIN"
    degraded = research_health(engine, env)
    # A search provider is a way to find pages; too few verified claims still degrades.
    assert degraded["hosts_with_template"] == 0 and degraded["status"] == "DEGRADED"
    assert degraded["claims_available"] == 0
    assert len(degraded["degraded_reasons"]) == 1
