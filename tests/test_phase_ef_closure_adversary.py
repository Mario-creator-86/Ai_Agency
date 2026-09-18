"""What the Phase E/F closure left open, attacked from the outside.

The closure wired the price table into the four places the studio builds an adapter, gave
`seed_documented_prices` a caller, and put the research health report and the forced retest
behind the Owner's door. Each of those was proved by its own author, from the inside. These
tests take the other side:

- the price wiring is proved by a *whole-tree* scan rather than a list of four files, so a
  fifth construction site added later cannot pass by not being on the list;
- an unpriced model is followed past the adapter into the books, because "cost None" is only
  half the invariant — the other half is that the Owner sees the gap named;
- the new search adapter's own transport is held against the loopback guard, with an address
  that needs no DNS, so the proof costs nothing and touches nobody;
- the forced retest is driven through the route with the real DNS-pinned retriever behind a
  scripted transport, and asked to swallow a foreign search address.

Nothing here contacts a provider, renders, uploads or spends: every vendor is faked at its
transport and `tests/conftest.py` refuses every non-loopback socket.
"""

from __future__ import annotations

import ast
import asyncio
import io
import json
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentRun, ProviderRecord
from app.agents.services import seed_initial_workforce
from app.economy.budget import budget_status
from app.economy.prices import list_prices, seed_documented_prices
from app.providers.ollama import OllamaProvider
from app.providers.registry import ProviderRegistry
from app.providers.search import SearchProvider
from app.research import retrieval as research
from app.research.service import add_allowed_host, allowed_host_rows, set_search_template
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
APPLICATION = ROOT / "backend" / "app"

#: The adapters that can turn a call into money. Building one without a price table is a run
#: the books cannot value, which is why every construction of them is accounted for below.
PRICED_ADAPTERS = {"ElevenLabsTTSAdapter", "ConfiguredLLM", "OllamaProvider"}

#: Where the studio builds one to do work a vendor bills for. Each must carry a price table.
PRICED_CONSTRUCTION_SITES = {
    "backend/app/main.py",
    "backend/app/integrations/services.py",
    "backend/app/integrations/router.py",
    "backend/app/media/factory.py",
}

#: Where it builds one for a call that generates nothing, with the reason. `credits.py` reads
#: the subscription balance and `discovery.py` lists the models and voices a connection
#: offers: neither sends characters, so neither has anything to price.
UNPRICED_ON_PURPOSE = {
    "backend/app/economy/credits.py": "reads the subscription balance; generates nothing",
    "backend/app/integrations/discovery.py": "lists models and voices; generates nothing",
}


def _construction_sites() -> dict[str, list[tuple[int, str, bool]]]:
    """Every call in the application that builds a priced adapter: file -> (line, class, priced).

    The whole tree is walked rather than a list of files read, and an attribute call
    (`elevenlabs.ElevenLabsTTSAdapter(...)`) counts as much as a bare name, because a fifth
    site would most likely arrive in a module nobody thought to list.
    """
    found: dict[str, list[tuple[int, str, bool]]] = {}
    for path in sorted(APPLICATION.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr
                if isinstance(node.func, ast.Attribute)
                else None
            )
            if name not in PRICED_ADAPTERS:
                continue
            relative = path.relative_to(ROOT).as_posix()
            priced = any(keyword.arg == "price_lookup" for keyword in node.keywords)
            found.setdefault(relative, []).append((node.lineno, name, priced))
    return found


def test_no_construction_of_a_priced_adapter_anywhere_is_unaccounted_for():
    """The closure's own scan reads four named files; this one reads all of them.

    A list of construction sites passes for whatever is on it. The invariant is about the
    studio, not about four modules: wherever it builds an adapter that can cost money, either
    a price table goes with it or the reason it cannot cost anything is written down here.
    """
    sites = _construction_sites()
    accounted = PRICED_CONSTRUCTION_SITES | set(UNPRICED_ON_PURPOSE)
    assert set(sites) - accounted == set(), (
        "an adapter that can cost money is built somewhere nobody has accounted for: "
        f"{ {path: sites[path] for path in set(sites) - accounted} }"
    )
    # Every site that does the work a vendor bills for carries the table.
    unpriced = [
        f"{path}:{line} {name}"
        for path in PRICED_CONSTRUCTION_SITES
        for line, name, priced in sites.get(path, [])
        if not priced
    ]
    assert not unpriced, f"built without a price table: {unpriced}"
    # And the listed sites still build one. A module that stopped would let the scan above
    # pass by finding nothing to look at.
    assert set(sites) == accounted, (
        f"a listed site no longer builds an adapter: {accounted - set(sites)}"
    )


def test_a_model_the_owner_never_priced_is_unknown_in_the_books_and_not_free(engine, monkeypatch):
    """Half the invariant is that the adapter reports None; the other half is that the Owner
    sees the gap named rather than reading a day that spent nothing.

    The documented seed is deliberately silent about Ollama Cloud, so this is the state the
    studio is actually in until the Owner types his prices: the run happened, the tokens were
    counted, the cost is unknown, and `budget_status` says so in a number of its own.
    """
    # The ElevenLabs figure and its Flash and Turbo halves, all from the cited price list.
    assert seed_documented_prices(engine)["seeded"] >= 1
    assert {row["provider_kind"] for row in list_prices(engine)} == {"elevenlabs"}, (
        "a price the Owner never typed was invented"
    )

    from app.main import register_seeded_ollama

    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.provider_seeded", "provider_record", identifier, 1, {}, str(uuid4())
        )
        session.add(
            ProviderRecord(
                id=identifier,
                name="ollama-cloud",
                provider_type="OLLAMA",
                base_url="http://127.0.0.1:11434",
                status="UNKNOWN",
                last_health_check=None,
                adapter_version="1.0.0",
                notes="",
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
    registry = ProviderRegistry()
    register_seeded_ollama(engine, registry)
    adapter = registry.get(identifier)
    assert isinstance(adapter, OllamaProvider)

    class _Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    body = {"response": "blue", "prompt_eval_count": 4000, "eval_count": 900, "done": True}
    monkeypatch.setattr(
        "app.providers.ollama.urlopen",
        lambda req, timeout=None: _Answer(json.dumps(body).encode()),
    )
    result = asyncio.run(adapter.generate("glm-5.2:cloud", "Why is the sky blue?"))
    assert result.cost_vr is None, "a model with no price must cost None, never zero"

    seed_initial_workforce(engine)
    with Session(engine) as session:
        employee = session.scalars(select(Agent)).first()
        assert employee is not None
        employee_id = employee.id

    started = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=employee_id,
                task_type="research",
                objective="Why is the sky blue?",
                prompt_template_version=1,
                model_name="glm-5.2:cloud",
                provider_name="ollama-cloud",
                status="SUCCEEDED",
                output=None,
                output_text="blue",
                error_detail=None,
                cost_vr=result.cost_vr,
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                correlation_id=str(uuid4()),
                started_at=started,
                finished_at=utc_now(),
                event_id=None,
                context_json={},
            )
        )

    today = budget_status(engine)["today"]
    assert today["unpriced_agent_runs"] == 1, (
        "the Owner cannot see the usage the books cannot value"
    )
    assert today["agent_usd_micros"] == 0 and today["spent_usd_micros"] == 0
    assert today["prompt_tokens"] == 4000, "the tokens are counted even where the money is not"


def test_the_loopback_guard_covers_the_new_search_adapters_transport():
    """Invariant seven, for the vendor Phase F added.

    The address is TEST-NET-3 (RFC 5737), so nothing is resolved and nothing is reached: the
    point is only that the adapter's transport goes through the socket the guard holds, and
    that an unfaked call fails loudly with the address it tried rather than quietly reaching
    a vendor. A `SearchProviderError` here would mean the guard had been swallowed as an
    ordinary network failure and a real key could have gone out on a real run.
    """
    adapter = SearchProvider({"endpoint": "https://203.0.113.9/search"}, "k-never-sent")
    with pytest.raises(AssertionError, match="must be faked at its transport"):
        adapter.search("hubble")


@pytest.fixture
def pinned_transport(monkeypatch):
    """The retriever's pinned HTTPS connection, answered from a script; records what was asked.

    Copied from tests/test_research_sources.py so the *real* `SourceRetriever` runs — the
    point of the test below is that the route uses it, not a stand-in.
    """
    monkeypatch.setattr(
        research.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("93.184.215.14", 443))]
    )
    responses: list[_Response] = []
    asked: list[str] = []

    def connect(host, address, timeout):
        connection = MagicMock()
        connection.request.side_effect = lambda method, target, headers: asked.append(
            f"https://{host}{target}"
        )
        connection.getresponse.side_effect = lambda: responses.pop(0)
        return connection

    monkeypatch.setattr(research, "_PinnedHTTPS", connect)
    return type("Scripted", (), {"responses": responses, "asked": asked})()


class _Response:
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


FRONT_PAGE = (
    "<html><head><title>NASA</title>"
    '<link rel="search" type="application/opensearchdescription+xml" '
    'href="https://evil.example/opensearch_desc.xml" title="Elsewhere">'
    '<link rel="search" type="application/opensearchdescription+xml" '
    'href="/opensearch_desc.php" title="NASA">'
    "</head><body><p>The National Aeronautics and Space Administration publishes mission "
    "reports, instrument data and the history of its flights, written for anyone who reads "
    "them. This paragraph is long enough that the retriever does not read the page as an "
    "empty shell waiting for its scripts to run, which is a different failure with a "
    "different reason code and a different job for the Owner.</p></body></html>"
)

#: The site's own description, naming a search address on somebody else's host.
FOREIGN_DESCRIPTION = (
    '<?xml version="1.0"?>'
    '<OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">'
    "<ShortName>NASA</ShortName>"
    '<Url type="application/x-suggestions+json" method="get" '
    'template="https://evil.example/api?action=opensearch&amp;search={searchTerms}"/>'
    "</OpenSearchDescription>"
)


def test_a_forced_retest_cannot_widen_the_allowlist_or_take_a_foreign_search_address(
    client, headers, engine, settings, pinned_transport
):
    """The Owner's button reaches the network; it must not be a way into it.

    The existing tests drive the route through a stand-in with no `describe_search`, so
    discovery never runs and the one thing the route newly touches — a site's own words about
    where its search lives — is never exercised through it. Here the real retriever runs
    behind a scripted transport and the site says two untrue things: that its search
    description lives on another host, and, in the description it does serve, that its search
    address is on that other host. Neither may become anything the studio keeps.
    """
    app = client.app.app
    app.state.settings = settings.model_copy(update={"research_allowed_hosts": []})
    app.state.source_retriever = None  # the route must build the real, DNS-pinned one
    add_allowed_host(engine, "www.nasa.gov")
    owner_template = "https://www.nasa.gov/search?q={query}&format=json"
    set_search_template(engine, "www.nasa.gov", owner_template)

    pinned_transport.responses.extend(
        [
            _Response(FRONT_PAGE.encode()),
            _Response(
                FOREIGN_DESCRIPTION.encode(),
                content_type="application/opensearchdescription+xml",
            ),
            _Response(b"not found", status=404),  # /opensearch.xml, tried last
        ]
    )

    answer = client.post("/api/v1/factual/research/allowed-hosts/retest", headers=headers)
    assert answer.status_code == 200, answer.text
    assert [(r["host"], r["status"]) for r in answer.json()["tested"]] == [
        ("www.nasa.gov", "PASSED")
    ]

    # Only the authorised host was ever reached: the description named on evil.example was
    # refused before a connection, not after reading it.
    assert pinned_transport.asked == [
        "https://www.nasa.gov/",
        "https://www.nasa.gov/opensearch_desc.php",
        "https://www.nasa.gov/opensearch.xml",
    ]
    rows = {row["host"]: row for row in allowed_host_rows(app.state.settings, engine)}
    assert set(rows) == {"www.nasa.gov"}, "a retest added a host to the Owner's list"
    row = rows["www.nasa.gov"]
    assert row["discovered_search_template"] is None, "a search address on another host was kept"
    assert row["search_template"] == owner_template, "the Owner's own address was overwritten"
    assert row["search_template_origin"] == "OWNER"


def test_the_shots_bought_before_the_owner_pressed_stop_are_charged_to_the_day(
    engine, settings, tmp_path, monkeypatch
):
    """The Owner's stop is his decision; the shot the vendor had already made is still money.

    Written failing. The assembler's `_fail_job` now writes what a render had built on every
    path that ends it, the Owner's stop included — so the stopped job carries exactly the
    scene whose narration was bought. The media stage read that record for a vendor's refusal
    and not for the stop: the hold was released and nothing was charged, and a film the Owner
    stopped after one scene read in the books as a film that cost nothing. A shot generated in
    the minute before the switch was bought exactly as one the vendor then refused.
    """
    from app.economy.budget import BudgetCommand, set_budget
    from app.economy.models import ProviderCostRecord, SpendReservation
    from app.economy.prices import PriceCommand, set_price
    from app.integrations.services import SaveIntegration, save
    from app.integrations.vault import CredentialVault
    from app.media.assembler import assemble_video_job
    from app.media.models import VideoRenderJob
    from app.models import OwnerPolicy
    from app.providers.deterministic_media import DeterministicTTSAdapter
    from app.runbook import stages
    from app.runbook.services import OWNER_STOP_REASON
    from test_daily_run_stages import (
        _approved_board,
        _autonomy_on,
        _media_stage_with_a_fake_camera,
    )

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="10"))
    set_price(
        engine,
        PriceCommand(
            command_id=uuid4(),
            provider_kind="elevenlabs",
            resource="*",
            unit="per_1k_characters",
            usd="0.30",
        ),
    )
    connection = str(uuid4())
    save(
        engine,
        CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key")),
        connection,
        SaveIntegration(
            kind="elevenlabs", name="Voice", config={}, secrets={"api_key": "k-" + connection}
        ),
    )
    _autonomy_on(engine)
    board_id = _approved_board(engine, "A film the Owner stopped")
    _media_stage_with_a_fake_camera(monkeypatch, [])

    class VoiceThenStop(DeterministicTTSAdapter):
        PROVIDER_NAME = "elevenlabs"
        model = "eleven_turbo_v2_5"
        integration_id = connection
        calls = 0

        async def synthesize(self, text: str, **kwargs):
            type(self).calls += 1
            result = await super().synthesize(text, **kwargs)
            # The Owner presses STOP while the first scene is being recorded; the render
            # reads the switch before the second one and ends there.
            with Session(engine) as session, session.begin():
                session.get(OwnerPolicy, 1).autonomy_stopped = True
            return result

    def real_camera(engine_, storyboard_id, correlation_id, **kwargs):
        return assemble_video_job(
            engine_,
            storyboard_id,
            correlation_id,
            storage_root=tmp_path / "media",
            tts_adapter=VoiceThenStop(),
        )

    monkeypatch.setattr("app.media.assembler.assemble_video_job", real_camera)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "BLOCKED", outcome
    assert OWNER_STOP_REASON in outcome["reason"]
    with Session(engine) as session:
        job = session.scalars(select(VideoRenderJob)).one()
        scenes = list((job.production_json or {}).get("scenes") or [])
        rows = list(session.scalars(select(ProviderCostRecord)))
        holds = list(session.scalars(select(SpendReservation)))
    assert (job.storyboard_id, job.status) == (board_id, "FAILED")
    assert [scene["scene_index"] for scene in scenes] == [1], scenes
    # The hold goes back to the day at once, and what was bought is charged to it.
    assert [hold.status for hold in holds] == ["RELEASED"], [h.status for h in holds]
    assert len(rows) == 1, [(r.external_reference, r.usd_micros) for r in rows]
    assert rows[0].failed and rows[0].status == "ESTIMATED"
    assert ":failed:scene:1:" in rows[0].external_reference
    assert rows[0].usd_micros > 0, "the narration the vendor recorded was charged at nothing"
