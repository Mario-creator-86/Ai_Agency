"""Phase E/F read as an adversary would read it: where could money leave, or the allowlist grow?

The implementers' own tests hold what they built. These hold what an attacker — or a tired
afternoon's refactor — would break, and each one was written to fail first:

- no route anywhere in the API pays, purchases or transfers, and the two commands that let
  money be spent at all (a budget, a price) exist in one place each and are the Owner's;
- the day's money is really taken, not merely read: a second film asked after the first one
  holds the day's last dollars is refused by the real `reserve_spend`, not a stub;
- a render a vendor refused leaves a FAILED job that carries what it attempted, so the shots
  the vendor generated are charged (this one failed when it was written: the assembler kept
  `production_json` for a finished render only, and the books saw a lost render as free);
- an address that merely looks like an authorised host — a suffix, a login, a port, a
  homograph — is refused by the same check a plain foreign host is, and no search result,
  page or agent can widen the list: one function writes it, behind the Owner's door;
- one door leads to a language model, so the day's token ceiling cannot be walked around.

Every provider is faked; `tests/conftest.py` refuses any socket that is not loopback.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.economy.budget import BudgetCommand, set_budget
from app.economy.models import SpendReservation
from app.media.models import VideoRenderJob
from app.research.retrieval import RetrievalError, RetrievalPolicy, validate_url
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_daily_run_stages import (
    _approved_board,
    _autonomy_on,
    _media_stage_with_a_fake_camera,
)
from test_research_sources import (
    OWNER_TEMPLATE,
    WIKI,
    Recorder,
    StubRetriever,
    connect_search,
    search_answer,
)

BACKEND = Path(__file__).resolve().parents[1] / "backend" / "app"


@pytest.fixture
def studio(engine):
    """A staffed studio with two authorised hosts, both tested — the research tests' own
    starting point, repeated here because a fixture is not shared across test modules."""
    from app.agents.models import ModelRecord
    from app.agents.services import seed_initial_workforce
    from app.models import OwnerPolicy
    from app.research.models import ResearchAllowedHost
    from app.research.service import add_allowed_host

    seed_initial_workforce(engine)
    add_allowed_host(engine, WIKI)
    add_allowed_host(engine, "www.unesco.org")
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
        for row in session.scalars(select(ResearchAllowedHost)):
            row.last_test_status, row.last_test_at = "PASSED", utc_now()
    return {"hosts": (WIKI, "www.unesco.org")}


def _sources() -> list[tuple[Path, str]]:
    """Every application module, read once: several checks below are about the shape of the
    code — which module calls what — and not about a single run's behaviour."""
    return [(path, path.read_text(encoding="utf-8")) for path in sorted(BACKEND.rglob("*.py"))]


# ------------------------------------------------------- 1. no route pays, and who may spend --


def test_no_route_in_the_whole_api_pays_purchases_or_transfers(client):
    """The documented surface, every path and every method, read for a way out to a vendor.

    `test_phase11_economy` reads the economy's own paths; this reads all of them, including
    the operation each method carries, because a checkout added to an unrelated router would
    have passed that one.
    """
    documented = client.app.app.openapi()["paths"]
    forbidden = (
        "pay",
        "payment",
        "checkout",
        "purchase",
        "transfer",
        "withdraw",
        "topup",
        "top-up",
        "subscribe",
        "buy",
    )
    offending: list[str] = []
    for path, methods in documented.items():
        for method, operation in methods.items():
            if not isinstance(operation, dict):
                continue
            words = " ".join(
                [
                    path,
                    str(operation.get("operationId") or ""),
                    str(operation.get("summary") or ""),
                ]
            ).lower()
            # "buy" would match "buyer"; the boundary keeps the word a word.
            if any(
                re.search(rf"\b{word}\b", words.replace("_", " ").replace("-", " "))
                for word in forbidden
            ):
                offending.append(f"{method.upper()} {path}")
    assert offending == [], offending


def test_the_two_commands_that_let_money_be_spent_are_written_in_one_place_each(client):
    """A budget and a price are the only figures that decide what the studio may spend.

    The Accountant escalates and never grants: no agent, stage, watchdog or seed may call
    `set_budget`, and a price may be written only by the Owner's command or by the one
    documented seed that marks itself DOCUMENTED. Asserted over the source, because a new
    caller is exactly the change this invariant is meant to survive.
    """
    budget_callers, price_callers = [], []
    for path, text in _sources():
        where = path.relative_to(BACKEND).as_posix()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith(("def ", "#", '"', "'")) or "import" in stripped:
                continue
            if "set_budget(" in stripped and where != "economy/budget.py":
                budget_callers.append(where)
            if "set_price(" in stripped and where != "economy/prices.py":
                price_callers.append(where)
    assert set(budget_callers) == {"economy/router.py"}, budget_callers
    assert set(price_callers) == {"economy/router.py"}, price_callers
    # And the door itself is the Owner's: no credentials, no prices, and none set.
    body = {
        "command_id": str(uuid4()),
        "provider_kind": "elevenlabs",
        "resource": "*",
        "unit": "per_1k_characters",
        "usd": "0.01",
    }
    assert client.put("/api/v1/economy/prices", json=body).status_code == 401
    assert (
        client.put("/api/v1/economy/budget", json={"period": "DAILY", "limit_usd": "9"}).status_code
        == 401
    )


def test_the_same_price_command_with_another_figure_is_a_conflict_not_a_second_price(
    client, headers, engine
):
    """Idempotent by command id, and a retry that changed its mind is refused rather than
    guessed at: two prices under one identity would leave the books unable to say which
    figure costed a run."""
    from app.economy.prices import list_prices

    command_id = str(uuid4())
    body = {
        "command_id": command_id,
        "provider_kind": "elevenlabs",
        "resource": "*",
        "unit": "per_1k_characters",
        "usd": "0.22",
    }
    first = client.put("/api/v1/economy/prices", headers=headers, json=body)
    assert first.status_code == 200 and first.json()["version"] == 1
    again = client.put("/api/v1/economy/prices", headers=headers, json=body)
    assert again.json() == first.json(), "a retry set a second price"
    changed = client.put("/api/v1/economy/prices", headers=headers, json={**body, "usd": "9.99"})
    assert changed.status_code == 409, changed.text
    # A stale version is refused too, so two tabs cannot both replace version 1.
    stale = client.put(
        "/api/v1/economy/prices",
        headers=headers,
        json={
            "command_id": str(uuid4()),
            "provider_kind": "elevenlabs",
            "resource": "*",
            "unit": "per_1k_characters",
            "usd": "0.30",
            "expected_version": 7,
        },
    )
    assert stale.status_code == 409, stale.text
    assert [p["usd"] for p in list_prices(engine)] == ["0.22"]


# ---------------------------------------------------- 2. the day's last dollars, taken once --


def test_while_a_film_is_being_shot_its_money_is_gone_from_the_day(engine, settings, monkeypatch):
    """The day's last dollars, asked for twice while the camera rolls.

    The stage's own tests watch the hold before and after the render. This one asks the
    budget *during* it, from inside the camera, which is where a second film asked in the
    same second would ask: `may_spend(engine, 0)` used to answer from a snapshot with the
    film's cost nowhere in it, so both films were told the money was free. The hold must
    stand for as long as the shot lasts, and be gone the moment the film is in the books.
    """
    from app.agents.services import seed_initial_workforce
    from app.economy.budget import estimate_film_cost_micros, may_spend, reserve_spend
    from app.economy.services import format_micros
    from app.runbook import stages
    from app.services import studio_environment

    _autonomy_on(engine)
    seed_initial_workforce(engine)
    factual = _approved_board(engine, "A factual short")
    rendered: list[str] = []
    _media_stage_with_a_fake_camera(monkeypatch, rendered)
    # A budget with room for exactly one film of this plan, and no micro more.
    one = estimate_film_cost_micros(
        engine, factual, environment=studio_environment(engine), settings=settings
    )["usd_micros"]
    assert one > 0, "a film that costs nothing cannot hold anything"
    set_budget(engine, BudgetCommand(period="DAILY", limit_usd=format_micros(one)))
    asked_mid_shot: dict[str, Any] = {}

    def camera(engine_, storyboard_id, correlation_id, **kwargs):
        rendered.append(storyboard_id)
        asked_mid_shot["reading"] = may_spend(engine_, 1)
        asked_mid_shot["second_film"] = reserve_spend(engine_, one, "another film", str(uuid4()))
        return {"output_asset_id": f"asset-{storyboard_id[:8]}", "job_id": str(uuid4())}

    monkeypatch.setattr("app.media.assembler.assemble_video_job", camera)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "COMPLETED", outcome
    assert rendered == [factual], rendered
    assert not asked_mid_shot["reading"]["allowed"], "the day looked free while it was spent"
    assert "rezerva" in asked_mid_shot["reading"]["reason"], asked_mid_shot["reading"]["reason"]
    assert not asked_mid_shot["second_film"]["allowed"], "two films took the same last dollars"
    assert asked_mid_shot["second_film"]["reservation_id"] is None
    with Session(engine) as session:
        holds = list(session.scalars(select(SpendReservation)))
    assert [hold.status for hold in holds] == ["SETTLED"], [(h.purpose, h.status) for h in holds]


def test_a_hold_is_refused_when_it_would_pass_the_limit_by_one_micro(engine):
    """The boundary the budget is written on: exactly the limit is allowed, a micro past it
    is not. An off-by-one here is a day the studio overspends every day."""
    from app.economy.budget import reserve_spend
    from app.economy.services import record_provider_cost

    set_budget(engine, BudgetCommand(period="DAILY", limit_usd="10"))
    exact = reserve_spend(engine, 10_000_000, "film exact", str(uuid4()))
    assert exact["allowed"] and exact["reservation_id"]
    over = reserve_spend(engine, 1, "one micro more", str(uuid4()))
    assert not over["allowed"] and over["reservation_id"] is None
    # Exactly at the limit an unpriced plan still passes: nothing is held and nothing is
    # over. Past the limit it does not — a budget that cannot value a plan refuses it,
    # because it cannot value it.
    assert reserve_spend(engine, 0, "an unpriced film", str(uuid4()))["allowed"]
    record_provider_cost(
        engine, provider="runway", external_reference="over", status="ESTIMATED", amount="0.01"
    )
    assert not reserve_spend(engine, 0, "an unpriced film", str(uuid4()))["allowed"]


# --------------------------------------------- 3. a render the vendor refused is still a cost --


def _board_with_two_scenes(engine, title: str = "An interrupted film") -> str:
    return _approved_board(engine, title)


def test_a_render_the_vendor_refused_leaves_a_failed_job_that_carries_what_it_attempted(
    engine, tmp_path
):
    """The vendor charges for the shot it generated whether or not the film was finished.

    Written failing: a `MediaProviderError` from a scene's voice left the job RUNNING with an
    empty `production_json`, so the stage's `record_failed_render_cost` found no FAILED job,
    then no scenes, and charged nothing — the books read a lost render as a free one. The
    render must end the job the way the Owner's stop already did, and keep what it had built.
    """
    from app.media.assembler import assemble_video_job
    from app.providers.deterministic_media import DeterministicTTSAdapter
    from app.providers.media_http import MediaProviderError

    _autonomy_on(engine)
    board_id = _board_with_two_scenes(engine)

    class VoiceThenRefusal(DeterministicTTSAdapter):
        PROVIDER_NAME = "test_voice"
        model = "eleven_turbo_v2_5"
        calls = 0

        async def synthesize(self, text: str, **kwargs: Any):
            type(self).calls += 1
            if type(self).calls > 1:
                raise MediaProviderError("the vendor refused this narration")
            return await super().synthesize(text, **kwargs)

    with pytest.raises(MediaProviderError):
        assemble_video_job(
            engine,
            board_id,
            str(uuid4()),
            storage_root=tmp_path / "media",
            tts_adapter=VoiceThenRefusal(),
        )

    with Session(engine) as session:
        job = session.scalars(select(VideoRenderJob)).one()
        production = job.production_json if isinstance(job.production_json, dict) else {}
    assert job.status == "FAILED", "a refused render left its job open"
    scenes = list(production.get("scenes") or [])
    assert len(scenes) == 1, scenes
    assert scenes[0]["scene_index"] == 1
    assert scenes[0]["characters"] > 0 and scenes[0]["model_id"], scenes[0]


def test_the_books_charge_for_the_scene_the_interrupted_render_bought(engine, tmp_path):
    """And the cost reaches the books by the path the media stage walks: the job the
    assembler left, read for what it attempted and priced at the Owner's own price.

    Nothing is passed by hand here — no scene list, no connection id. The connection is the
    one the voice came from, which the render writes into its own record before the first
    scene, and the price is the one the Owner typed. This is the whole chain the day uses.
    """
    from app.economy.accountant import record_failed_render_cost
    from app.economy.budget import budget_status
    from app.economy.models import ProviderCostRecord
    from app.economy.prices import PriceCommand, set_price
    from app.integrations.services import SaveIntegration, save
    from app.integrations.vault import CredentialVault
    from app.media.assembler import assemble_video_job
    from app.providers.deterministic_media import DeterministicTTSAdapter
    from app.providers.media_http import MediaProviderError

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
            kind="elevenlabs",
            name="Voice",
            config={},
            secrets={"api_key": "k-" + connection},
        ),
    )
    _autonomy_on(engine)
    board_id = _board_with_two_scenes(engine, "A film the vendor stopped")

    class VoiceThenRefusal(DeterministicTTSAdapter):
        PROVIDER_NAME = "elevenlabs"
        model = "eleven_turbo_v2_5"
        integration_id = connection
        calls = 0

        async def synthesize(self, text: str, **kwargs: Any):
            type(self).calls += 1
            if type(self).calls > 1:
                raise MediaProviderError("the vendor refused this narration")
            return await super().synthesize(text, **kwargs)

    with pytest.raises(MediaProviderError):
        assemble_video_job(
            engine,
            board_id,
            str(uuid4()),
            storage_root=tmp_path / "media",
            tts_adapter=VoiceThenRefusal(),
        )
    with Session(engine) as session:
        job_id = session.scalars(select(VideoRenderJob.id)).one()

    charged = record_failed_render_cost(engine, job_id, correlation_id=str(uuid4()))

    assert charged["recorded"] >= 1, charged
    with Session(engine) as session:
        rows = list(session.scalars(select(ProviderCostRecord)))
    assert rows and all(row.failed and row.status == "ESTIMATED" for row in rows)
    assert all(":failed:" in row.external_reference for row in rows)
    # Counted by the day's budget like any other estimate, and never charged twice.
    assert budget_status(engine)["budgets"][0]["spent_usd_micros"] == sum(
        r.usd_micros for r in rows
    )
    assert record_failed_render_cost(engine, job_id)["recorded"] == 0


# ------------------------------------------------------ 4. the allowlist cannot be widened --


@pytest.mark.parametrize(
    ("url", "why"),
    [
        ("https://en.wikipedia.org.evil.example/wiki/X", "an authorised name as a prefix"),
        ("https://evil.example/en.wikipedia.org/wiki/X", "an authorised name in the path"),
        ("https://en.wikipedia.org@evil.example/wiki/X", "the authorised name as a login"),
        ("https://evil.example@en.wikipedia.org/wiki/X", "a login on an authorised host"),
        ("https://en.wikipedia.org:8443/wiki/X", "another port"),
        ("https://en.wikipedia.org./wiki/X", "a trailing dot"),
        ("https://en.wikipediа.org/wiki/X", "a Cyrillic letter that looks Latin"),
        ("http://en.wikipedia.org/wiki/X", "no TLS"),
        ("file:///etc/passwd", "not the web at all"),
        ("https://en.wikipedia.org\\@evil.example/", "a backslash where a slash is read"),
    ],
)
def test_an_address_that_only_looks_authorised_is_refused(url: str, why: str):
    """One membership test, on the host the URL parser says it is — never on the string.

    Each of these reads as `en.wikipedia.org` to an eye scanning a log, and none of them is.
    """
    policy = RetrievalPolicy(allowed_hosts=("en.wikipedia.org",))
    with pytest.raises(RetrievalError):
        validate_url(url, policy)


def test_a_search_result_dressed_as_an_authorised_host_is_dropped_and_never_read(
    engine, settings, studio, monkeypatch
):
    """The engine names addresses; the studio decides which of them exist for it.

    The implementers' test plants a plainly foreign host. These are the ones that would pass
    a careless filter — and the count of what was dropped must show all of them, because a
    silent drop is how nobody notices the engine has stopped being useful.
    """
    from app.providers import search as search_module
    from app.research.service import find_pages

    connect_search(engine)
    answer = (
        search_answer(
            (f"https://{WIKI}.evil.example/wiki/Real", "A suffix"),
            (f"https://evil.example@{WIKI}/wiki/Real", "A login"),
            (f"https://{WIKI}:8443/wiki/Real", "Another port"),
            (f"https://{WIKI}/wiki/Real", "The page itself"),
        ),
        b"",
        "application/json",
    )
    monkeypatch.setattr(search_module, "request", Recorder(answer))
    stub = StubRetriever({f"https://{WIKI}/wiki/Real": "A real page the studio read itself."})
    import app.research.service as service

    monkeypatch.setattr(service, "SourceRetriever", lambda policy: stub)

    report: dict = {}
    pages = find_pages(settings, engine, "Real", retriever=stub, report=report)

    assert [page["url"] for page in pages] == [f"https://{WIKI}/wiki/Real"]
    assert report["search"] == {"queries": 1, "kept": 1, "dropped": 3}, report["search"]
    assert not [url for url in stub.asked if "evil.example" in url or ":8443" in url], stub.asked


def test_an_authorised_sites_own_search_cannot_hand_the_studio_a_foreign_page(
    engine, settings, studio
):
    """The site's own search is a source of addresses too, and it is judged like the engine.

    An authorised encyclopaedia whose suggestion endpoint is compromised — or which simply
    mirrors another site — would otherwise be a way in that no one is watching, because the
    address came from a host the Owner trusts. The allowlist is a rule about the page, not
    about who named it.
    """
    from app.research.service import search_pages, set_search_template

    set_search_template(engine, WIKI, OWNER_TEMPLATE)
    answer = json.dumps(
        [
            "Real",
            ["A real page", "A page elsewhere", "A page on a look-alike"],
            ["", "", ""],
            [
                f"https://{WIKI}/wiki/Real",
                "https://evil.example/wiki/Real",
                f"https://{WIKI}.evil.example/wiki/Real",
            ],
        ]
    )
    stub = StubRetriever(search_answer=answer)

    pages = search_pages(settings, engine, WIKI, "Real", 5, stub)

    assert [page["url"] for page in pages] == [f"https://{WIKI}/wiki/Real"], pages
    # Only the search address itself was asked for; no foreign page was read to find out.
    assert all("evil.example" not in url for url in stub.asked), stub.asked


def test_one_function_writes_the_allowlist_and_it_is_behind_the_owners_door():
    """No agent, stage, research pass or search result may add a host.

    `add_allowed_host` is called in exactly one place in the application — the Owner-only
    factual router — and the research pass that discovers a site's search address writes a
    template, never a host. A second caller is the change this invariant must survive.
    """
    callers = []
    for path, text in _sources():
        where = path.relative_to(BACKEND).as_posix()
        if where == "research/service.py":
            continue
        for line in text.splitlines():
            stripped = line.strip()
            if "add_allowed_host(" in stripped and not stripped.startswith(("#", "def ")):
                callers.append((where, stripped[:60]))
    modules = {where for where, _ in callers}
    assert modules == {"factual/router.py"}, callers
    router = (BACKEND / "factual" / "router.py").read_text(encoding="utf-8")
    assert 'APIRouter(prefix="/factual", dependencies=[Depends(require_owner)])' in router


def test_the_allowlist_a_research_pass_reads_is_the_stored_one_whatever_a_page_says(
    engine, settings, studio
):
    """A page's content is data. The retrieval policy is built from the record alone, so a
    fetched page that names a host — in a link, a redirect note, a sentence — changes
    nothing about what may be fetched next."""
    from app.research.service import _policy, allowed_hosts

    before = set(allowed_hosts(settings, engine))
    policy = _policy(settings, engine)
    assert set(policy.allowed_hosts) == before
    with pytest.raises(RetrievalError):
        validate_url("https://evil.example/a-page-that-asked-to-be-read", policy)
    assert set(allowed_hosts(settings, engine)) == before


# ---------------------------------------------------------- 5. one door leads to a model --


def test_only_the_policy_kernel_asks_a_language_model_to_generate():
    """The day's token ceiling can only hold if there is one way to spend a token.

    `run_agent_task` is the single caller of an adapter's `generate`; a second one would be a
    path where the kernel's first gate — the ceiling, autonomy, capability, health — is not
    asked at all, and the 391 unpriced runs measured on the live database would come back.
    """
    callers = []
    for path, text in _sources():
        where = path.relative_to(BACKEND).as_posix()
        for number, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("#", "*", '"')):
                continue
            if re.search(r"\.generate\(", stripped) and "generate_image" not in stripped:
                callers.append((where, number, stripped[:60]))
    assert {where for where, _, _ in callers} == {"agents/services.py"}, callers
    services = (BACKEND / "agents" / "services.py").read_text(encoding="utf-8")
    gate = services.index("may_run_agent(engine")
    generate = services.index("adapter.generate(")
    assert gate < generate, "the ceiling is asked after the model was already called"


def test_a_blocked_run_is_recorded_and_costs_nothing(engine, monkeypatch):
    """A refusal past the ceiling is a row with a reason, not a silent short day: the run is
    recorded BLOCKED_BUDGET with no tokens, so tomorrow's report can count the refusals."""
    from types import SimpleNamespace

    from app.agents import services as agent_services
    from app.agents.models import Agent, AgentRun, ModelRecord
    from app.agents.services import run_agent_task, seed_initial_workforce
    from app.models import OwnerPolicy
    from app.providers.base import GenerateResult, HealthResult
    from app.providers.registry import ProviderRegistry

    class Model:
        asked = 0

        async def health_check(self):
            return HealthResult("HEALTHY")

        async def list_models(self):
            return []

        async def generate(self, model, prompt, **kwargs):
            type(self).asked += 1
            return GenerateResult("un răspuns", 10, 10, None)

    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    seed_initial_workforce(engine)
    with Session(engine) as session, session.begin():
        for record in session.scalars(select(ModelRecord)):
            record.is_available = True
    with Session(engine) as session:
        agent = session.scalars(select(Agent)).first()
        agent_id, provider_id = agent.id, agent.provider_id
    registry = ProviderRegistry()
    registry.register(provider_id, Model())
    # A ceiling of one token: the day is over before it started, whatever the run would cost.
    monkeypatch.setattr(
        agent_services, "_studio_settings", lambda: SimpleNamespace(agent_daily_token_budget=1)
    )
    with Session(engine) as session, session.begin():
        session.add(
            AgentRun(
                id=str(uuid4()),
                agent_id=agent_id,
                task_type="t",
                objective="a run earlier today",
                prompt_template_version="v1",
                model_name="a-model",
                provider_name="a-provider",
                status="SUCCEEDED",
                prompt_tokens=1,
                completion_tokens=0,
                correlation_id=str(uuid4()),
                started_at=utc_now(),
            )
        )

    blocked = run_agent_task(engine, registry, agent_id, "t", "spune ceva", "v1", str(uuid4()))

    assert blocked["status"] == "BLOCKED_BUDGET", blocked
    assert Model.asked == 0, "the model was asked after the ceiling refused the run"
    with Session(engine) as session:
        row = session.get(AgentRun, blocked["id"])
    assert not row.prompt_tokens and not row.completion_tokens, "a refused run counted tokens"
    assert row.cost_vr in (None, "0")


def test_the_media_stage_charges_the_day_for_the_render_the_vendor_stopped(
    engine, settings, tmp_path, monkeypatch
):
    """The stage's own path, end to end, against a render that really failed.

    The stage finds the job the assembler left, prices what it attempted and only then lets
    the hold go — the order matters, because the estimate must stop counting exactly when
    the real cost of the attempt starts. Before the assembler kept its record, this walked
    the whole path and charged nothing, and the day read a lost render as a free one.
    """
    from app.economy.models import ProviderCostRecord
    from app.economy.prices import PriceCommand, set_price
    from app.integrations.services import SaveIntegration, save
    from app.integrations.vault import CredentialVault
    from app.media.assembler import assemble_video_job
    from app.providers.deterministic_media import DeterministicTTSAdapter
    from app.providers.media_http import MediaProviderError
    from app.runbook import stages

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
    board_id = _approved_board(engine, "A film the vendor stopped")
    rendered: list[str] = []
    _media_stage_with_a_fake_camera(monkeypatch, rendered)

    class VoiceThenRefusal(DeterministicTTSAdapter):
        PROVIDER_NAME = "elevenlabs"
        model = "eleven_turbo_v2_5"
        integration_id = connection
        calls = 0

        async def synthesize(self, text: str, **kwargs: Any):
            type(self).calls += 1
            if type(self).calls > 1:
                raise MediaProviderError("the vendor refused this narration")
            return await super().synthesize(text, **kwargs)

    def real_camera(engine_, storyboard_id, correlation_id, **kwargs):
        # The real assembler, given a voice that refuses the second scene: what the stage
        # meets on a bad afternoon, without a vendor or a socket.
        return assemble_video_job(
            engine_,
            storyboard_id,
            correlation_id,
            storage_root=tmp_path / "media",
            tts_adapter=VoiceThenRefusal(),
        )

    monkeypatch.setattr("app.media.assembler.assemble_video_job", real_camera)

    outcome = stages._media(engine, settings, None, None)

    assert outcome["status"] == "COMPLETED", outcome
    # One render: «1 randare refuzată de furnizor» (the count agrees with its noun).
    assert "refuzată de furnizor" in outcome["reason"], outcome["reason"]
    assert outcome["artefacts"]["costs_recorded"] >= 1, outcome["artefacts"]
    with Session(engine) as session:
        job = session.scalars(select(VideoRenderJob)).one()
    assert (job.storyboard_id, job.status) == (board_id, "FAILED")
    with Session(engine) as session:
        rows = list(session.scalars(select(ProviderCostRecord)))
        holds = list(session.scalars(select(SpendReservation)))
    assert rows and all(row.failed for row in rows), [
        (r.external_reference, r.failed) for r in rows
    ]
    assert [hold.status for hold in holds] == ["RELEASED"], [h.status for h in holds]
