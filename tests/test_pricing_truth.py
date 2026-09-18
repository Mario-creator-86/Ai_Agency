"""Prices the Owner supplies, and the costs the adapters compute from them — never invented.

Measured on a copy of the live database (2026-09-18): 391 `agent_run` rows on Ollama Cloud
with `cost_vr` NULL, nine ElevenLabs models with `pricing {}`, so a day's tokens and
narration were "unpriced" in every budget and the Accountant closed on a figure that was
missing them. What is asserted here: a price exists only because the Owner typed it (or a
public price list documents it, marked so); with a price the adapters cost every call from
what they measured — tokens counted, characters sent — and without one they say None, as
before, never zero. Every vendor is faked at its transport; nothing here costs money.
"""

from __future__ import annotations

import ast
import asyncio
import io
import json
from pathlib import Path
from uuid import uuid4

import pytest
from app.agents.models import ProviderRecord
from app.economy.models import ProviderCostRecord, ProviderPrice
from app.economy.prices import (
    PriceCommand,
    list_prices,
    llm_cost_vr,
    price_lookup,
    seed_documented_prices,
    set_price,
    tts_cost_vr,
)
from app.economy.services import EconomyError
from app.integrations.llm import ConfiguredLLM
from app.integrations.models import (
    Integration,
    MediaProductionConfig,
    ProviderResource,
    ServiceSelection,
)
from app.integrations.services import SaveIntegration, load_registry, save
from app.integrations.vault import CredentialVault
from app.providers.elevenlabs import ElevenLabsTTSAdapter
from app.providers.ollama import OllamaProvider
from app.providers.registry import ProviderRegistry
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

# --------------------------------------------------------------------------- helpers


def price(engine, kind, resource, unit, usd, **kw):
    return set_price(
        engine,
        PriceCommand(
            command_id=uuid4(), provider_kind=kind, resource=resource, unit=unit, usd=usd, **kw
        ),
    )


class _Response:
    """What `urlopen` hands the seeded Ollama adapter: a readable, closable body."""

    def __init__(self, body: dict) -> None:
        self._raw = io.BytesIO(json.dumps(body).encode())

    def read(self) -> bytes:
        return self._raw.read()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# --------------------------------------------------------------------------- the arithmetic


def test_the_cost_arithmetic_needs_every_unit_the_call_used_or_says_nothing():
    """Half a price is not a price: a run whose output is priced and input is not stays unpriced."""
    table = {("m", "per_1m_input_tokens"): 2_000_000, ("m", "per_1m_output_tokens"): 10_000_000}
    lookup = lambda resource, unit: table.get((resource, unit))  # noqa: E731
    # 1000 input tokens at 2 USD a million, 500 output at 10: 0.002 + 0.005.
    assert llm_cost_vr(lookup, "m", 1000, 500) == "0.007"
    assert llm_cost_vr(lookup, "other-model", 1000, 500) is None
    assert llm_cost_vr(lookup, "m", None, 500) is None, "an uncounted side cannot be priced"

    def only_output(resource, unit):
        return table.get((resource, unit)) if "output" in unit else None

    assert llm_cost_vr(only_output, "m", 1000, 500) is None
    # No tokens on one side is a zero, not an unknown: a prompt with an empty answer costs
    # its prompt.
    assert llm_cost_vr(lookup, "m", 1000, 0) == "0.002"
    voice = lambda resource, unit: 300_000 if unit == "per_1k_characters" else None  # noqa: E731
    assert tts_cost_vr(voice, "v2", 1500) == "0.45"
    assert tts_cost_vr(voice, "v2", 0) is None
    assert tts_cost_vr(lambda r, u: None, "v2", 1500) is None


# --------------------------------------------------------------------------- the LLM adapters


def test_a_configured_llm_run_is_costed_from_the_owners_prices_and_unpriced_without_them(
    engine, monkeypatch
):
    def request(self, method, path, body=None):
        assert path == "/api/generate"
        return {"response": "ok", "prompt_eval_count": 1000, "eval_count": 500, "done": True}

    monkeypatch.setattr(ConfiguredLLM, "request", request)
    adapter = ConfiguredLLM(
        "ollama",
        {"base_url": "https://ollama.com"},
        {"api_key": "k"},
        price_lookup=price_lookup(engine, "ollama"),
    )
    model = f"cloud-model-{uuid4().hex[:6]}:cloud"

    before = asyncio.run(adapter.generate(model, "Why?"))
    assert before.cost_vr is None, "no price typed, no cost invented"

    price(engine, "ollama", model, "per_1m_input_tokens", "2")
    assert asyncio.run(adapter.generate(model, "Why?")).cost_vr is None, "input alone is half"
    price(engine, "ollama", model, "per_1m_output_tokens", "10")
    after = asyncio.run(adapter.generate(model, "Why?"))
    assert after.cost_vr == "0.007" and (after.prompt_tokens, after.completion_tokens) == (
        1000,
        500,
    )
    # Another model of the same kind has no row of its own and stays unpriced.
    assert asyncio.run(adapter.generate("another-model", "Why?")).cost_vr is None
    # The adapter built without a lookup — as the tests always built it — still says None.
    plain = ConfiguredLLM("ollama", {"base_url": "https://ollama.com"}, {"api_key": "k"})
    assert asyncio.run(plain.generate(model, "Why?")).cost_vr is None


def test_an_openai_style_run_is_costed_the_same_way(engine, monkeypatch):
    def request(self, method, path, body=None):
        return {
            "choices": [{"message": {"content": "fine"}}],
            "usage": {"prompt_tokens": 250_000, "completion_tokens": 100_000},
        }

    monkeypatch.setattr(ConfiguredLLM, "request", request)
    adapter = ConfiguredLLM(
        "openai", {}, {"api_key": "k"}, price_lookup=price_lookup(engine, "openai")
    )
    price(engine, "openai", "gpt-test", "per_1m_input_tokens", "1.25")
    price(engine, "openai", "gpt-test", "per_1m_output_tokens", "10")
    # 0.25M × 1.25 + 0.1M × 10 = 0.3125 + 1 = 1.3125
    assert asyncio.run(adapter.generate("gpt-test", "hi")).cost_vr == "1.3125"


def test_the_seeded_ollama_adapter_costs_a_cloud_model_only_at_a_typed_price(engine, monkeypatch):
    body = {"response": "The sky is blue.", "prompt_eval_count": 10, "eval_count": 5, "done": True}
    monkeypatch.setattr("app.providers.ollama.urlopen", lambda req, timeout=None: _Response(body))
    adapter = OllamaProvider(price_lookup=price_lookup(engine, "ollama"))
    assert asyncio.run(adapter.generate("llama:cloud", "Why?")).cost_vr is None
    price(engine, "ollama", "llama:cloud", "per_1m_input_tokens", "100")
    price(engine, "ollama", "llama:cloud", "per_1m_output_tokens", "200")
    # 10 × 100 / 1M + 5 × 200 / 1M = 0.001 + 0.001
    assert asyncio.run(adapter.generate("llama:cloud", "Why?")).cost_vr == "0.002"
    assert asyncio.run(OllamaProvider().generate("llama:cloud", "Why?")).cost_vr is None


# --------------------------------------------------------------------------- the voice adapter


def test_narration_is_costed_by_the_characters_sent_at_the_per_thousand_price(engine, monkeypatch):
    from app.providers import elevenlabs

    sent: list[dict] = []

    def transport(host, method, path, headers, body=None, **kwargs):
        sent.append(json.loads(body))
        return None, b"ID3fake-audio", "audio/mpeg"

    monkeypatch.setattr(elevenlabs, "request", transport)
    monkeypatch.setattr(elevenlabs, "mp3_duration_seconds", lambda audio: 1.5)
    adapter = ElevenLabsTTSAdapter(
        "key", voice_id="v1", model="voice-model", price_lookup=price_lookup(engine, "elevenlabs")
    )
    narration = "Hubble was launched in 1990."  # 28 characters

    unpriced = asyncio.run(adapter.synthesize(narration))
    assert unpriced.cost_vr is None and unpriced.raw_response["characters"] == 28

    price(engine, "elevenlabs", "voice-model", "per_1k_characters", "0.30")
    priced = asyncio.run(adapter.synthesize(narration))
    assert priced.cost_vr == "0.0084", "28 characters at 0.30 a thousand"
    assert sent[-1]["text"] == narration, "the characters priced are the characters sent"

    # A price for every model of the kind ("*") covers a model with no row of its own.
    price(engine, "elevenlabs", "*", "per_1k_characters", "0.20")
    other = ElevenLabsTTSAdapter(
        "key", voice_id="v1", model="other-model", price_lookup=price_lookup(engine, "elevenlabs")
    )
    assert asyncio.run(other.synthesize(narration)).cost_vr == "0.0056"
    # The model's own row outranks the wildcard.
    assert asyncio.run(adapter.synthesize(narration)).cost_vr == "0.0084"


# --------------------------------------------------------------------------- the command


def test_a_price_is_versioned_kept_and_replaced_never_edited(engine):
    first = price(engine, "ollama", "m", "per_1m_input_tokens", "2", notes="the plan's page")
    assert (first["version"], first["provenance"], first["usd"]) == (1, "OWNER", "2")
    second = price(engine, "ollama", "m", "per_1m_input_tokens", "2.50")
    assert second["version"] == 2 and second["active"] is True
    with Session(engine) as session:
        rows = session.scalars(
            select(ProviderPrice)
            .where(ProviderPrice.resource == "m")
            .order_by(ProviderPrice.version)
        ).all()
        assert [(r.version, r.active, r.usd_micros) for r in rows] == [
            (1, False, 2_000_000),
            (2, True, 2_500_000),
        ]
        assert rows[0].replaced_at is not None and rows[1].event_id is not None
    assert [p["usd"] for p in list_prices(engine, provider_kind="ollama")] == ["2.5"]
    # The Owner may say which version he is replacing; a stale expectation is refused.
    with pytest.raises(EconomyError):
        price(engine, "ollama", "m", "per_1m_input_tokens", "3", expected_version=1)
    third = price(engine, "ollama", "m", "per_1m_input_tokens", "3", expected_version=2)
    assert third["version"] == 3


def test_a_replayed_price_command_sets_the_price_once(engine):
    command = PriceCommand(
        command_id=uuid4(),
        provider_kind="elevenlabs",
        resource="*",
        unit="per_1k_characters",
        usd="0.22",
    )
    first = set_price(engine, command)
    assert set_price(engine, command) == first
    assert len(list_prices(engine, provider_kind="elevenlabs")) == 1
    from app.services import CommandConflict

    with pytest.raises(CommandConflict):
        set_price(engine, command.model_copy(update={"usd": "0.30"}))


def test_a_price_command_refuses_what_is_not_a_price():
    with pytest.raises(ValueError):
        PriceCommand(
            command_id=uuid4(), provider_kind="ollama", resource="m", unit="per_pound", usd="1"
        )
    with pytest.raises(ValueError):
        PriceCommand(
            command_id=uuid4(), provider_kind="ollama", resource="m", unit="per_second", usd="-1"
        )
    with pytest.raises(ValueError):
        PriceCommand(
            command_id=uuid4(),
            provider_kind="ollama",
            resource="m",
            unit="per_second",
            usd="1",
            provenance="GUESSED",
        )


# --------------------------------------------------------------------------- the documented seed


def test_the_documented_seed_is_marked_and_never_overrides_the_owner(engine):
    seeded = seed_documented_prices(engine)
    assert seeded["seeded"] >= 1
    rows = list_prices(engine)
    assert rows and all(r["provenance"] == "DOCUMENTED" for r in rows)
    assert all(r["provider_kind"] == "elevenlabs" for r in rows), "Ollama Cloud is never guessed"
    assert all("price list" in (r["notes"] or "") for r in rows)
    # Seeding again adds nothing; the Owner's own price then outranks the documented one.
    assert seed_documented_prices(engine)["seeded"] == 0
    price(engine, "elevenlabs", "*", "per_1k_characters", "0.10")
    assert seed_documented_prices(engine)["seeded"] == 0
    active = [
        r
        for r in list_prices(engine, provider_kind="elevenlabs")
        if r["unit"] == "per_1k_characters"
    ]
    assert [(r["resource"], r["provenance"], r["usd"]) for r in active] == [
        ("*", "OWNER", "0.1"),
        ("eleven_flash_*", "DOCUMENTED", "0.11"),
        ("eleven_turbo_*", "DOCUMENTED", "0.11"),
    ]
    # The documented family rows stay listed, and his '*' is what every model is read at.
    assert _per_1k(engine, "eleven_flash_v2") == 100_000


# --------------------------------------------------------------------------- the books


def test_a_render_is_costed_at_the_owners_price_when_the_catalogue_has_none(
    engine, tmp_path, elevenlabs_api, client, headers
):
    """Nine live ElevenLabs models carry `pricing {}`; the Owner's per-thousand price costs them."""
    from app.economy.accountant import record_render_costs
    from app.integrations.models import ProviderResource
    from app.media.models import VideoRenderJob
    from app.services import append_event, utc_now
    from test_production_policy import make_storyboard

    identifier = str(uuid4())
    saved = client.put(
        f"/api/v1/settings/integrations/{identifier}",
        headers=headers,
        json={"kind": "elevenlabs", "name": "Voice", "secrets": {"api_key": f"k-{uuid4()}"}},
    )
    assert saved.status_code == 200
    model_id = elevenlabs_api.models[0]["model_id"]
    with Session(engine) as session:
        resource = session.scalar(
            select(ProviderResource).where(ProviderResource.remote_id == model_id)
        )
        assert resource.pricing in ({}, None), "the catalogue row carries no price, as live"
    price(engine, "elevenlabs", model_id, "per_1k_characters", "0.30")
    storyboard_id = make_storyboard(engine, tmp_path)
    job_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "media.render_started", "video_render_job", job_id, 1, {}, str(uuid4())
        )
        session.add(
            VideoRenderJob(
                id=job_id,
                storyboard_id=storyboard_id,
                status="COMPLETED",
                started_at=utc_now(),
                finished_at=utc_now(),
                production_json={
                    "voice": {"integration_id": identifier},
                    "scenes": [
                        {"scene_index": 1, "model_id": model_id, "characters": 1000},
                        {"scene_index": 2, "model_id": "unpriced-model", "characters": 400},
                    ],
                },
                event_id=event.event_id,
            )
        )
    outcome = record_render_costs(engine, job_id)
    assert (outcome["recorded"], outcome["unpriced_scenes"]) == (1, 1)
    with Session(engine) as session:
        row = session.scalar(select(ProviderCostRecord))
        assert (row.provider, row.usd_micros, row.failed) == ("elevenlabs", 300_000, False)
        assert row.attribution_json["price_provenance"] == "OWNER"


def test_settings_are_not_needed_to_read_a_price(engine):
    """The lookup an adapter holds is a plain callable: resource and unit in, micros out."""
    lookup = price_lookup(engine, "anthropic")
    assert lookup("claude-x", "per_1m_input_tokens") is None
    price(engine, "anthropic", "claude-x", "per_1m_input_tokens", "3")
    assert lookup("claude-x", "per_1m_input_tokens") == 3_000_000
    assert lookup("claude-x", "per_1m_output_tokens") is None


# ------------------------------------------------------------------- the construction sites

#: The repository root, for the one test that reads the studio's own source.
ROOT = Path(__file__).resolve().parents[1]

#: Every module where the studio itself builds an adapter that can cost money, and the class
#: it builds there. `integrations/credits.py` and `integrations/discovery.py` are deliberately
#: absent: they build an ElevenLabs adapter to read a subscription or list voices, calls that
#: generate nothing and so have nothing to price.
PRICED_CONSTRUCTION_SITES = {
    "backend/app/main.py": "OllamaProvider",
    "backend/app/integrations/services.py": "ConfiguredLLM",
    "backend/app/integrations/router.py": "ConfiguredLLM",
    "backend/app/media/factory.py": "ElevenLabsTTSAdapter",
}


def _priced_calls(path: str) -> list[ast.Call]:
    """Every call in `path` that builds that module's priced adapter."""
    source = (ROOT / path).read_text(encoding="utf-8")
    wanted = PRICED_CONSTRUCTION_SITES[path]
    return [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == wanted
    ]


def _elevenlabs_connection(engine, vault) -> str:
    """A verified ElevenLabs connection with its production model and voice discovered —
    what both doors in `media.factory` require before they will build a voice at all."""
    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", identifier, 1, {}, str(uuid4())
        )
        session.add(
            Integration(
                id=identifier,
                kind="elevenlabs",
                name="Voice",
                config={"voice_id": "v-narrator", "model": "test-model"},
                encrypted_secrets=vault.encrypt({"api_key": "k-" + identifier}),
                secret_fields=["api_key"],
                version=1,
                status="ACCESS_VERIFIED",
                checked_at=None,
                event_id=event.event_id,
            )
        )
        session.flush()
        session.add(
            MediaProductionConfig(
                integration_id=identifier,
                model_id="test-model",
                voice_id="v-narrator",
                version=1,
                updated_at=utc_now(),
            )
        )
        for resource_type, remote_id in (("MODEL", "test-model"), ("VOICE", "v-narrator")):
            session.add(
                ProviderResource(
                    id=str(uuid4()),
                    integration_id=identifier,
                    resource_type=resource_type,
                    remote_id=remote_id,
                    name=remote_id,
                    api_available=True,
                    last_seen_at=utc_now(),
                    api_metadata={"can_do_text_to_speech": True}
                    if resource_type == "MODEL"
                    else {},
                )
            )
        selection_event = append_event(
            session, "settings.service_selected", "service_selection", "voice", 1, {}, str(uuid4())
        )
        session.merge(
            ServiceSelection(
                purpose="voice",
                integration_id=identifier,
                version=1,
                event_id=selection_event.event_id,
            )
        )
    return identifier


def test_no_place_the_studio_builds_a_priced_adapter_is_left_without_the_price_table():
    """The adapters could cost a call from the day the price table existed; nothing handed
    them one.

    Measured before this: `grep -rn price_lookup backend/` found the keyword in the three
    adapters and in `economy/prices.py`, and at no construction site — so every `agent_run`
    carried `cost_vr` NULL and every narration was unpriced, whatever the Owner had typed.
    A behavioural test per site follows; this one refuses a fifth site added later without one.
    """
    unpriced = [
        f"{path}:{call.lineno} {call.func.id}"
        for path in PRICED_CONSTRUCTION_SITES
        for call in _priced_calls(path)
        if not any(keyword.arg == "price_lookup" for keyword in call.keywords)
    ]
    assert not unpriced, f"adapters the studio builds without a price table: {unpriced}"
    # And each named module still builds one: a module that stopped would make the scan
    # above pass by finding nothing to look at.
    assert all(_priced_calls(path) for path in PRICED_CONSTRUCTION_SITES)


def test_the_seeded_ollama_endpoint_is_registered_with_the_price_table(engine, monkeypatch):
    """The endpoint bootstrap seeds is the one the employees run on, so it costs what it spends."""
    from app.main import register_seeded_ollama

    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.provider_seeded", "provider_record", identifier, 1, {}, str(uuid4())
        )
        session.add(
            ProviderRecord(
                id=identifier,
                name="ollama-" + identifier[:8],
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

    body = {"response": "blue", "prompt_eval_count": 1000, "eval_count": 500, "done": True}
    monkeypatch.setattr("app.providers.ollama.urlopen", lambda req, timeout=None: _Response(body))
    assert asyncio.run(adapter.generate("llama:cloud", "Why?")).cost_vr is None
    price(engine, "ollama", "llama:cloud", "per_1m_input_tokens", "2")
    price(engine, "ollama", "llama:cloud", "per_1m_output_tokens", "10")
    assert asyncio.run(adapter.generate("llama:cloud", "Why?")).cost_vr == "0.007"


def test_the_connections_the_studio_loads_at_start_up_carry_the_price_table(engine, monkeypatch):
    """A saved language connection is registered once, at start-up, and priced from then on."""
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    identifier = str(uuid4())
    save(
        engine,
        vault,
        identifier,
        SaveIntegration(
            kind="openai", name="Writer", config={}, secrets={"api_key": "k-" + identifier}
        ),
    )

    registry = ProviderRegistry()
    load_registry(engine, vault, registry)
    adapter = registry.get(identifier)
    assert isinstance(adapter, ConfiguredLLM)

    def request(self, method, path, body=None):
        return {
            "choices": [{"message": {"content": "fine"}}],
            "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 0},
        }

    monkeypatch.setattr(ConfiguredLLM, "request", request)
    assert asyncio.run(adapter.generate("gpt-test", "hi")).cost_vr is None
    price(engine, "openai", "gpt-test", "per_1m_input_tokens", "1.25")
    price(engine, "openai", "gpt-test", "per_1m_output_tokens", "10")
    assert asyncio.run(adapter.generate("gpt-test", "hi")).cost_vr == "1.25"


def test_a_connection_saved_while_the_studio_runs_is_registered_with_the_price_table(
    client, headers, engine
):
    """The other half of the same registry: the connection the Owner types in today, which
    replaces the adapter start-up registered and must not lose its prices doing it."""
    identifier = str(uuid4())
    answer = client.put(
        f"/api/v1/settings/integrations/{identifier}",
        headers=headers,
        json={
            "kind": "openai",
            "name": "Writer",
            "config": {},
            "secrets": {"api_key": "k-" + identifier},
            "expected_version": 0,
        },
    )
    assert answer.status_code == 200, answer.text

    # `.app.app` is the FastAPI inside the trusted-host middleware, as the other tests reach it.
    adapter = client.app.app.state.registry.get(identifier)
    assert isinstance(adapter, ConfiguredLLM)
    assert adapter.price_lookup is not None, "saved, registered, and unable to cost a run"
    price(engine, "openai", "gpt-test", "per_1m_input_tokens", "3")
    assert adapter.price_lookup("gpt-test", "per_1m_input_tokens") == 3_000_000


def test_the_voice_a_render_is_given_costs_the_narration_it_speaks(engine, tmp_path, monkeypatch):
    """Both doors into a voice — the one the Owner selected and the one a scene's policy
    resolves — hand the render an adapter that can price what it says."""
    from app.media.factory import tts_provider, tts_provider_for
    from app.providers import elevenlabs

    vault = CredentialVault(tmp_path / "voice.credentials.key")
    identifier = _elevenlabs_connection(engine, vault)

    def transport(host, method, path, headers, body=None, **kwargs):
        return None, b"ID3fake-audio", "audio/mpeg"

    monkeypatch.setattr(elevenlabs, "request", transport)
    monkeypatch.setattr(elevenlabs, "mp3_duration_seconds", lambda audio: 1.5)
    narration = "Hubble was launched in 1990."  # 28 characters

    selected = tts_provider(engine, vault)
    resolved = tts_provider_for(
        engine,
        vault,
        {
            "valid": True,
            "integration_id": identifier,
            "voice_id": "v-narrator",
            "model_id": "test-model",
        },
    )
    assert isinstance(selected, ElevenLabsTTSAdapter)
    assert isinstance(resolved, ElevenLabsTTSAdapter)
    assert asyncio.run(selected.synthesize(narration)).cost_vr is None, "no price, no cost"

    price(engine, "elevenlabs", "test-model", "per_1k_characters", "0.30")
    assert asyncio.run(selected.synthesize(narration)).cost_vr == "0.0084"
    assert asyncio.run(resolved.synthesize(narration)).cost_vr == "0.0084"


# ------------------------------------------------------------------ the seed has a caller now


def test_bootstrap_seeds_the_documented_price_beside_the_chart_of_accounts(engine):
    """`seed_documented_prices` had no caller outside this file, so a studio where the Owner
    had typed no price read narration as free.

    The source is read rather than run: bootstrap writes `.env` and migrates the database
    named in it, which is the Owner's own, and no test may open it. What is asserted is
    that `main` calls the seed, in the company of the seeds that make the books usable.
    """
    source = (ROOT / "scripts" / "bootstrap.py").read_text(encoding="utf-8")
    main = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    called = {
        node.func.id
        for node in ast.walk(main)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "seed_documented_prices" in called, "the documented seed still has no caller"
    assert "seed_chart_of_accounts" in called, "read beside the seed it belongs with"

    # And what the caller gets: the one published figure, never Ollama Cloud, and a second
    # bootstrap over a price the Owner typed in between leaves his price standing.
    assert seed_documented_prices(engine)["seeded"] == 3
    assert [
        (row["provider_kind"], row["resource"], row["provenance"]) for row in list_prices(engine)
    ] == [
        ("elevenlabs", "*", "DOCUMENTED"),
        ("elevenlabs", "eleven_flash_*", "DOCUMENTED"),
        ("elevenlabs", "eleven_turbo_*", "DOCUMENTED"),
    ]
    price(engine, "elevenlabs", "*", "per_1k_characters", "0.12")
    assert seed_documented_prices(engine)["seeded"] == 0
    assert [(row["usd"], row["provenance"]) for row in list_prices(engine)] == [
        ("0.12", "OWNER"),
        ("0.11", "DOCUMENTED"),
        ("0.11", "DOCUMENTED"),
    ]
    assert _per_1k(engine, "eleven_turbo_v2_5") == 120_000, "his price, not the price list's"


def test_a_price_makes_an_estimate_and_only_the_invoice_makes_it_the_truth(engine):
    """The last figure in this file that was never checked against a vendor.

    A price the Owner typed produces an ESTIMATED row the moment the studio spends, which is
    the whole point of the table above — but it stays the studio's own arithmetic until the
    vendor's invoice arrives. Measured before the reconciliation existed: `spend_since`
    counted the estimate and the bill, so a day priced at 3.00 and billed at 3.30 read 6.30.
    """
    from uuid import uuid4 as _uuid4

    from app.economy.budget import spend_since
    from app.economy.services import (
        ReconciliationCommand,
        reconcile_provider_invoice,
        record_provider_cost,
        seed_chart_of_accounts,
    )

    seed_chart_of_accounts(engine)
    set_price(
        engine,
        PriceCommand(
            command_id=_uuid4(),
            provider_kind="elevenlabs",
            resource="*",
            unit="per_1k_characters",
            usd="1.50",
            provenance="OWNER",
        ),
    )
    estimated = record_provider_cost(
        engine,
        provider="elevenlabs",
        external_reference="render:p:scene:1:voice",
        status="ESTIMATED",
        amount="3.00",
        attribution={"render_job_id": "p", "price_provenance": "OWNER"},
    )
    with Session(engine) as session:
        before = spend_since(session, "2000-01-01T00:00:00+00:00")
    assert before["spent_usd"] == "3", "the Owner's price, believed until it is checked"

    invoice = reconcile_provider_invoice(
        engine,
        ReconciliationCommand(
            command_id=_uuid4(),
            provider="elevenlabs",
            external_reference="EL-2026-09",
            amount="3.30",
            scope="CORRELATION",
            correlation="p",
        ),
    )
    assert invoice["matched"] == 1 and invoice["difference_vr"] == "0.3"
    with Session(engine) as session:
        after = spend_since(session, "2000-01-01T00:00:00+00:00")
        row = session.get(ProviderCostRecord, estimated["id"])
    assert after["spent_usd"] == "3.3", "what the vendor charged, and not it plus the guess"
    assert row.status == "ESTIMATED" and row.reconciled_at, (
        "the estimate is kept whole — it is the record of what the studio believed"
    )


# ------------------------------------------------------------ the documented price, per family


def _per_1k(engine, model: str) -> int | None:
    from app.economy.prices import price_for

    with Session(engine) as session:
        return price_for(session, "elevenlabs", model, "per_1k_characters")


def test_the_documented_voice_price_is_half_for_the_models_the_price_list_bills_half(engine):
    """The audit of 2026-09-18: the one DOCUMENTED ElevenLabs figure (resource '*', 0.22 USD
    a thousand characters) priced the Owner's eleven_flash_v2 at the multilingual rate,
    although the very row's note says Flash and Turbo bill half a credit a character, so his
    narration read about twice its cost in the books. The figure per family comes from that
    same cited price list, and nothing else is invented: every other model keeps the '*'."""
    from app.integrations.catalog import DOCUMENTED_PRICES

    seed_documented_prices(engine)
    everything = next(e for e in DOCUMENTED_PRICES if e["resource"] == "*")
    for family in ("eleven_flash_*", "eleven_turbo_*"):
        entry = next(e for e in DOCUMENTED_PRICES if e["resource"] == family)
        assert float(entry["usd"]) * 2 == float(everything["usd"]), family
        assert "price list" in entry["notes"] and "half" in entry["notes"], family

    assert _per_1k(engine, "eleven_flash_v2") == 110_000
    assert _per_1k(engine, "eleven_flash_v2_5") == 110_000
    assert _per_1k(engine, "eleven_turbo_v2_5") == 110_000
    assert _per_1k(engine, "eleven_multilingual_v2") == 220_000
    assert _per_1k(engine, "eleven_v3") == 220_000
    # The adapter reads the same lookup: 1 000 characters on Flash cost 0.11, not 0.22.
    assert tts_cost_vr(price_lookup(engine, "elevenlabs"), "eleven_flash_v2", 1000) == "0.11"


def test_any_price_the_owner_types_outranks_every_documented_one(engine):
    """A documented family row is more specific than the Owner's '*', and must still lose to
    it: his plan's figure is the price, the price list only a stand-in until he types it."""
    seed_documented_prices(engine)
    price(engine, "elevenlabs", "*", "per_1k_characters", "0.10")
    assert _per_1k(engine, "eleven_flash_v2") == 100_000
    assert _per_1k(engine, "eleven_multilingual_v2") == 100_000
    # Among his own prices the most specific wins: the model, then its family, then '*'.
    price(engine, "elevenlabs", "eleven_flash_*", "per_1k_characters", "0.05")
    assert _per_1k(engine, "eleven_flash_v2_5") == 50_000
    price(engine, "elevenlabs", "eleven_flash_v2", "per_1k_characters", "0.04")
    assert _per_1k(engine, "eleven_flash_v2") == 40_000
    assert _per_1k(engine, "eleven_flash_v2_5") == 50_000
    assert _per_1k(engine, "eleven_multilingual_v2") == 100_000


def test_a_documented_row_the_owners_wildcard_already_covers_is_not_seeded(engine):
    """A studio where the Owner typed his plan before the family rows existed gets nothing
    new: a documented row his '*' outranks would never be read, only listed."""
    price(engine, "elevenlabs", "*", "per_1k_characters", "0.10")
    assert seed_documented_prices(engine)["seeded"] == 0
    assert [(r["resource"], r["provenance"]) for r in list_prices(engine)] == [("*", "OWNER")]


def test_a_render_on_flash_is_charged_at_the_flash_figure(engine, tmp_path, client, headers):
    """The books, not only the adapter: the Accountant prices a scene the catalogue has no
    price for from the same table, so a Flash narration is charged at the Flash figure."""
    from app.economy.accountant import record_render_costs
    from app.media.models import VideoRenderJob
    from test_production_policy import make_storyboard

    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "settings.integration_saved", "integration", identifier, 1, {}, "c"
        )
        session.add(
            Integration(
                id=identifier,
                kind="elevenlabs",
                name="Voice",
                config={},
                encrypted_secrets=CredentialVault(
                    Path(str(engine.url.database)).with_suffix(".credentials.key")
                ).encrypt({"api_key": "k"}),
                secret_fields=["api_key"],
                version=1,
                status="VERIFIED",
                checked_at=utc_now(),
                event_id=event.event_id,
            )
        )
    seed_documented_prices(engine)
    storyboard_id = make_storyboard(engine, tmp_path)
    job_id = str(uuid4())
    with Session(engine) as session, session.begin():
        event = append_event(
            session, "media.render_started", "video_render_job", job_id, 1, {}, str(uuid4())
        )
        session.add(
            VideoRenderJob(
                id=job_id,
                storyboard_id=storyboard_id,
                status="COMPLETED",
                started_at=utc_now(),
                finished_at=utc_now(),
                production_json={
                    "voice": {"integration_id": identifier},
                    "scenes": [
                        {"scene_index": 1, "model_id": "eleven_flash_v2", "characters": 1000},
                        {
                            "scene_index": 2,
                            "model_id": "eleven_multilingual_v2",
                            "characters": 1000,
                        },
                    ],
                },
                event_id=event.event_id,
            )
        )
    assert record_render_costs(engine, job_id)["recorded"] == 2
    with Session(engine) as session:
        rows = {
            r.attribution_json["model_id"]: (r.usd_micros, r.attribution_json["price_provenance"])
            for r in session.scalars(select(ProviderCostRecord))
        }
    assert rows == {
        "eleven_flash_v2": (110_000, "DOCUMENTED"),
        "eleven_multilingual_v2": (220_000, "DOCUMENTED"),
    }
