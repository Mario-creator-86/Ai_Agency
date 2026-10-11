"""The signals the studio adapts to: what people search for, what measured, what vendors say.

Local tests; nothing reaches Google or a vendor. What is asserted: the trends feed is parsed
into records and kept once a day, a feed that does not answer is recorded as such; the
Researcher's proposal prompt carries the trends and the measured cohorts; the weekly digest
lists the week's trends; and a steward reads vendor pages the studio fetched, scores the
account's models where the production hierarchy reads scores, recommends one, changes a
default the Owner left as a fallback and leaves a locked one alone.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentMessage, ModelRecord, Role
from app.agents.services import seed_initial_workforce
from app.analytics.models import TrendSnapshot
from app.analytics.trends import (
    TrendsUnavailable,
    is_fresh,
    parse_trends_rss,
    refresh_trends,
    trending_now,
    trends_as_text,
)
from app.integrations.discovery import ProductionCommand, save_production
from app.integrations.models import MediaProductionConfig, ProviderResource
from app.integrations.services import select_service
from app.media.model_research import (
    ModelResearchError,
    research_all,
    research_models,
    vendor_hosts,
)
from app.media.production_policy import rank_candidates
from app.media.services import seed_default_character_bibles
from app.models import DomainEvent, OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.research.agent import propose_topics
from app.research.service import add_allowed_host
from app.runbook.weekly import _digest_as_text, weekly_digest
from sqlalchemy import select
from sqlalchemy.orm import Session

RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">
<channel><title>Daily Search Trends</title>
<item><title>eclipsa de luna</title><ht:approx_traffic>200,000+</ht:approx_traffic>
<pubDate>Fri, 12 Sep 2026 06:00:00 -0700</pubDate>
<ht:news_item><ht:news_item_title>Eclipsa totala vizibila din Romania</ht:news_item_title>
<ht:news_item_url>https://example.org/eclipsa</ht:news_item_url><ht:news_item_source>Example</ht:news_item_source></ht:news_item>
</item>
<item><title>simona halep</title><ht:approx_traffic>50,000+</ht:approx_traffic></item>
<item><title></title></item>
</channel></rss>"""


class ScriptedModel:
    def __init__(self, answer):
        self.answer = answer
        self.prompts: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.prompts.append(prompt)
        return GenerateResult(self.answer(prompt), 10, 40, None)


@pytest.fixture
def studio(engine):
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        agents = {
            role.name: agent
            for agent, role in session.execute(
                select(Agent, Role).join(Role, Agent.role_id == Role.id)
            ).all()
        }
        provider_id = next(iter(agents.values())).provider_id
        session.expunge_all()
    return {"agents": agents, "provider_id": provider_id}


def registry_with(studio, answer):
    registry = ProviderRegistry()
    model = ScriptedModel(answer)
    registry.register(studio["provider_id"], model)
    return registry, model


def events_of(engine, event_type):
    with Session(engine) as session:
        return session.scalars(
            select(DomainEvent)
            .where(DomainEvent.event_type == event_type)
            .order_by(DomainEvent.sequence)
        ).all()


# --------------------------------------------------------------------------- trends


def test_the_feed_is_parsed_into_records_by_local_name():
    items = parse_trends_rss(RSS)
    assert [i["title"] for i in items] == ["eclipsa de luna", "simona halep"]
    assert items[0]["approx_traffic"] == 200000 and items[1]["approx_traffic"] == 50000
    assert items[0]["news"][0]["title"] == "Eclipsa totala vizibila din Romania"
    assert items[0]["published_at"].startswith("Fri, 12 Sep 2026")
    with pytest.raises(TrendsUnavailable):
        parse_trends_rss(b"<html>not a feed")


def test_trends_are_kept_once_a_day_and_a_feed_that_does_not_answer_is_recorded(engine, settings):
    settings.trends_geo = "RO"
    first = refresh_trends(engine, settings, fetcher=lambda geo: RSS)
    assert first == {"status": "COMPLETED", "geo": "RO", "count": 2, "seen": 2}
    again = refresh_trends(engine, settings, fetcher=lambda geo: RSS)
    assert again["count"] == 0 and again["seen"] == 2
    with Session(engine) as session:
        assert len(session.scalars(select(TrendSnapshot)).all()) == 2
    assert is_fresh(engine, "RO") and not is_fresh(engine, "US")
    now = trending_now(engine, "RO")
    assert [t["title"] for t in now] == ["eclipsa de luna", "simona halep"]
    assert "~200,000 căutări" in trends_as_text(now, "RO")
    assert trends_as_text([], "RO").endswith("nimic înregistrat încă.")

    def broken(geo):
        raise TrendsUnavailable("HTTP 503")

    failed = refresh_trends(engine, settings, fetcher=broken)
    assert failed["status"] == "FAILED" and "503" in failed["reason"]
    assert events_of(engine, "trends.unavailable")[-1].payload["geo"] == "RO"
    assert len(events_of(engine, "trends.snapshot_recorded")) == 2

    settings.trends_enabled = False
    assert refresh_trends(engine, settings, fetcher=lambda geo: RSS)["status"] == "SKIPPED"


def test_the_researcher_is_told_what_is_trending_and_what_measured(engine, settings, studio):
    add_allowed_host(engine, "www.iana.org")
    with Session(engine) as session, session.begin():
        from app.research.models import ResearchAllowedHost

        session.get(ResearchAllowedHost, "www.iana.org").last_test_status = "PASSED"
    refresh_trends(engine, settings, fetcher=lambda geo: RSS)
    registry, model = registry_with(studio, lambda prompt: json.dumps({"candidates": []}))

    propose_topics(engine, registry, settings, str(uuid4()))

    prompt = model.prompts[-1]
    assert '"trending_now"' in prompt and "eclipsa de luna" in prompt
    assert '"searches": 200000' in prompt
    assert "no measured performance yet" in prompt
    assert "a trend is a hook, not a source" in prompt


def test_the_weekly_digest_lists_the_weeks_trends(engine, settings):
    settings.trends_geo = (
        "RO"  # the digest below asks for RO; the default is the audience's countries
    )
    refresh_trends(engine, settings, fetcher=lambda geo: RSS)
    digest = weekly_digest(engine, geo="RO")
    assert [t["title"] for t in digest["trends"]] == ["eclipsa de luna", "simona halep"]
    assert weekly_digest(engine)["trends"] == []
    # Nothing published: the text says so and still names the trends the Director should read.
    text = _digest_as_text({**digest, "anything_published": True, "videos": [], "per_channel": {}})
    assert "Tendințe acum (săptămâna aceasta)" in text and "eclipsa de luna" in text


# --------------------------------------------------------------------------- model research


def test_vendor_hosts_are_the_documentation_host_and_its_parents():
    assert vendor_hosts("runway") == ("docs.dev.runwayml.com", "dev.runwayml.com", "runwayml.com")
    assert vendor_hosts("elevenlabs") == ("elevenlabs.io",)
    assert vendor_hosts("nothing") == ()


class FakeReader:
    """The retriever, with the vendor's pages already in hand."""

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.fetched: list[str] = []

    def fetch(self, url):
        self.fetched.append(url)
        if url not in self.pages:
            from app.research.retrieval import RetrievalError

            raise RetrievalError("no such page")
        return SimpleNamespace(url=url, text=self.pages[url])


@pytest.fixture
def runway(client, headers, engine, runway_api):
    identifier = str(uuid4())
    saved = client.put(
        f"/api/v1/settings/integrations/{identifier}",
        headers=headers,
        json={"kind": "runway", "name": "Runway", "secrets": {"api_key": "k"}},
    )
    assert saved.status_code == 200 and saved.json()["status"] == "VERIFIED"
    select_service(engine, "video", identifier, 0)
    return identifier


def test_a_steward_reads_the_vendor_pages_scores_the_models_and_chooses(
    engine, settings, studio, runway, runway_api
):
    kael = studio["agents"]["VideoEditor"]
    models = list(runway_api.video_models)
    chosen, other = models[0], models[-1]
    pages = {
        "https://docs.dev.runwayml.com/": "Runway API docs. See /pricing and /models.",
        "https://docs.dev.runwayml.com/pricing": (
            f"Pricing. {chosen}: $0.05 per second. {other}: $0.25 per second."
        ),
    }
    reader = FakeReader(pages)

    def answer(prompt):
        if "vendor-docs-index" in prompt:
            return json.dumps(
                {"urls": ["https://docs.dev.runwayml.com/pricing", "https://evil.example/x"]}
            )
        return json.dumps(
            {
                "models": [
                    {
                        "remote_id": chosen,
                        "quality_score": 0.8,
                        "reliability_score": 0.9,
                        "latency_score": 0.7,
                        "price_usd": 0.05,
                        "price_unit": "per second",
                        "notes": "Cheap and fast; fine for shorts.",
                        "evidence_url": "https://docs.dev.runwayml.com/pricing",
                    },
                    {
                        "remote_id": other,
                        "quality_score": 0.9,
                        "reliability_score": 0.9,
                        "latency_score": 0.4,
                        "price_usd": 0.25,
                        "price_unit": "per second",
                        "evidence_url": "https://docs.dev.runwayml.com/pricing",
                    },
                    {"remote_id": "not-on-the-account", "quality_score": 1.0},
                ],
                "recommendation": {
                    "remote_id": chosen,
                    "reason": "Five times cheaper at similar quality for vertical shorts.",
                },
            }
        )

    registry, model = registry_with(studio, answer)
    result = research_models(engine, registry, settings, "video", retriever=reader)

    assert result["status"] == "COMPLETED" and result["steward"] == kael.display_name
    assert result["recommended"] == chosen and result["changed"] is True
    assert result["annotated"] == 2
    # The studio fetched the index and the page the steward named; never the foreign host.
    assert reader.fetched == [
        "https://docs.dev.runwayml.com/",
        "https://docs.dev.runwayml.com/pricing",
    ]
    assert "account-models" in model.prompts[-1] and "vendor-page-1" in model.prompts[-1]
    with Session(engine) as session:
        row = session.scalar(
            select(ProviderResource).where(
                ProviderResource.integration_id == runway, ProviderResource.remote_id == chosen
            )
        )
        assert row.capabilities["quality_score"] == 0.8
        assert row.capabilities["judged_by"] == kael.display_name
        assert row.pricing == {"per_second_usd": 0.05, "unit": "per second"}
        assert row.metadata_source == "https://docs.dev.runwayml.com/pricing"
        ranked = rank_candidates(session, runway, "MODEL", None, "video")
        assert ranked[0]["remote_id"] == chosen and ranked[0]["annotated"]
        assert session.get(MediaProductionConfig, runway).model_id == chosen
        letter = session.scalar(select(AgentMessage).where(AgentMessage.from_agent_id == kael.id))
        assert letter.subject.startswith("Cercetare de modele (video)")
        assert "Five times cheaper" in letter.body_text
    event = events_of(engine, "media.model_research_recorded")[-1]
    assert event.payload["recommended"] == chosen and event.payload["changed"] is True


def test_a_default_the_owner_locked_is_reported_on_but_not_changed(
    engine, settings, studio, runway, runway_api
):
    models = list(runway_api.video_models)
    owners_choice, steward_choice = models[-1], models[0]
    save_production(
        engine,
        runway,
        ProductionCommand(
            model_id=owners_choice,
            image_model_id=runway_api.image_model,
            allow_production_override=False,
            expected_version=0,
        ),
    )
    reader = FakeReader({"https://docs.dev.runwayml.com/": "docs"})

    def answer(prompt):
        if "vendor-docs-index" in prompt:
            return json.dumps({"urls": []})
        return json.dumps(
            {
                "models": [{"remote_id": steward_choice, "quality_score": 0.9, "price_usd": 0.1}],
                "recommendation": {"remote_id": steward_choice, "reason": "Better."},
            }
        )

    registry, _ = registry_with(studio, answer)
    result = research_models(engine, registry, settings, "video", retriever=reader)
    assert result["recommended"] == steward_choice and result["changed"] is False
    with Session(engine) as session:
        assert session.get(MediaProductionConfig, runway).model_id == owners_choice
        letter = session.scalar(
            select(AgentMessage).where(AgentMessage.subject.like("Cercetare de modele%"))
        )
        assert "blocat de Owner" in letter.body_text


def test_a_vendor_whose_documentation_does_not_answer_is_reported_not_guessed(
    engine, settings, studio, runway
):
    registry, model = registry_with(studio, lambda p: "{}")
    result = research_models(engine, registry, settings, "video", retriever=FakeReader({}))
    assert result["status"] == "SKIPPED" and model.prompts == []
    with Session(engine) as session:
        letter = session.scalar(select(AgentMessage))
        assert "nu a putut fi citită" in letter.subject


def test_research_all_skips_purposes_without_a_chosen_catalogue_service(engine, settings, studio):
    registry, model = registry_with(studio, lambda p: "{}")
    results = research_all(engine, registry, settings)
    assert set(results) == {"voice", "image", "video"}
    assert all(r["status"] == "SKIPPED" for r in results.values())
    assert model.prompts == []
    with pytest.raises(ModelResearchError):
        research_models(engine, registry, settings, "music")


def test_several_countries_are_read_one_by_one_and_merged_for_the_prompt(engine, settings):
    """The Owner, 2026-10-11: the channels speak English to the world and a month of Romanian
    trends had been read for them; STUDIO_TRENDS_GEO names the audience's countries."""
    from app.analytics.trends import geos_of, is_fresh

    settings.trends_geo = " us, gb ,US"
    assert settings.trends_geos == ["US", "GB"]
    assert geos_of("US,GB") == ["US", "GB"] and geos_of(["gb", "GB"]) == ["GB"]
    answers = {"US": RSS, "GB": RSS.replace(b"simona halep", b"a british trend")}

    result = refresh_trends(engine, settings, fetcher=lambda geo: answers[geo])

    assert result["status"] == "COMPLETED" and result["geo"] == " us, gb ,US"
    assert result["count"] == 4 and result["seen"] == 4
    assert [item["geo"] for item in result["by_geo"]] == ["US", "GB"]
    assert is_fresh(engine, settings.trends_geo) and is_fresh(engine, ["US"])
    assert not is_fresh(engine, "US,CA")
    now = trending_now(engine, settings.trends_geo)
    by_title = {item["title"]: item for item in now}
    # A trend both countries search for is one line carrying both.
    assert by_title["eclipsa de luna"]["geos"] == ["US", "GB"]
    assert by_title["a british trend"]["geos"] == ["GB"]
    assert by_title["simona halep"]["geos"] == ["US"]
    text = trends_as_text(now, settings.trends_geo)
    assert text.startswith("Tendințe acum (US, GB)")
    assert "- eclipsa de luna [US, GB]" in text and "- a british trend [GB]" in text
    # One country answers as it always did: no per-country list, no country tags.
    settings.trends_geo = "US"
    single = refresh_trends(engine, settings, fetcher=lambda geo: RSS)
    assert single == {"status": "COMPLETED", "geo": "US", "count": 0, "seen": 2}
    assert "[US]" not in trends_as_text(trending_now(engine, "US"), "US")
    # A country whose feed does not answer is recorded; the others still count.
    settings.trends_geo = "US,FR"

    def partial(geo):
        if geo == "FR":
            raise TrendsUnavailable("no answer")
        return RSS

    mixed = refresh_trends(engine, settings, fetcher=partial)
    assert mixed["status"] == "COMPLETED" and [i["status"] for i in mixed["by_geo"]] == [
        "COMPLETED",
        "FAILED",
    ]
    assert events_of(engine, "trends.unavailable")[-1].payload["geo"] == "FR"


def test_the_shipped_default_reads_the_audiences_countries():
    from app.config import Settings

    config = Settings(_env_file=None, owner_token="test-owner-token-for-budget-check")
    assert config.trends_geos == ["US", "GB", "CA", "AU"]
