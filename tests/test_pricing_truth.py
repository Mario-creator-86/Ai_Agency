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

import asyncio
import io
import json
from uuid import uuid4

import pytest
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
from app.providers.elevenlabs import ElevenLabsTTSAdapter
from app.providers.ollama import OllamaProvider
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
    assert [(r["resource"], r["provenance"], r["usd"]) for r in active] == [("*", "OWNER", "0.1")]


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
