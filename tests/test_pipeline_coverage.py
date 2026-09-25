"""The day runs end to end: ideas, sources, a decision, and a channel that knows its account.

The Owner's studio had two YouTube accounts connected, a verified Runway key and a verified
ElevenLabs key, and still could not publish, measure or produce: the publishing screen
answered 500, no channel slot named an account, no service was chosen for images, no default
model or voice was set, and nothing generated ideas. These tests hold each of those closed.

Local tests with a scripted model and a stubbed retriever; nothing here reaches a vendor.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest
from app.agents.services import seed_initial_workforce
from app.factual.models import FactualClaim, SourceSnapshot, TopicIdea
from app.integrations.autoconfig import auto_configure
from app.integrations.models import MediaProductionConfig, ServiceSelection
from app.integrations.vault import CredentialVault
from app.media.services import seed_default_character_bibles
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.publishing.services import channel_bindings, seed_default_channels
from app.research.agent import NoAuthorisedHosts, ResearchAgentError, gather_sources, propose_topics
from app.research.service import add_allowed_host
from app.runbook.preflight import run_preflight
from app.services import append_event, utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

# --------------------------------------------------------------------------- helpers


def vault_for(engine):
    """The vault the app itself would build for this database."""
    return CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))


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
def studio(engine, settings):
    """A seeded studio with staff, channels and an Owner who cleared the stop."""
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        from app.agents.models import ModelRecord

        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        from app.agents.models import Agent

        provider_id = session.scalar(select(Agent.provider_id))
    return {"provider_id": provider_id}


def registry_with(studio, answer):
    registry = ProviderRegistry()
    model = ScriptedModel(answer)
    registry.register(studio["provider_id"], model)
    return registry, model


def connect_account(engine, name: str, remote_id: str, title: str) -> str:
    """A CONNECTED YouTube connection, as the OAuth flow leaves one."""
    from app.youtube.models import YouTubeConnection

    identifier = str(uuid4())
    vault = vault_for(engine)
    with Session(engine) as session, session.begin():
        event = append_event(
            session,
            "youtube.connection_saved",
            "youtube_connection",
            identifier,
            1,
            {},
            str(uuid4()),
        )
        session.add(
            YouTubeConnection(
                id=identifier,
                name=name,
                client_id="client.apps.googleusercontent.com",
                redirect_uri="http://127.0.0.1:8000/auth/youtube/callback",
                encrypted_secrets=vault.encrypt(
                    {"client_secret": "s", "refresh_token": "r"}  # pragma: allowlist secret
                ),
                secret_fields=["client_secret", "refresh_token"],
                status="CONNECTED",
                remote_channel_id=remote_id,
                remote_channel_title=title,
                channel_snapshot={},
                granted_scopes="https://www.googleapis.com/auth/youtube.upload",
                connected_at=utc_now(),
                created_at=utc_now(),
                event_id=event.event_id,
            )
        )
    return identifier


# --------------------------------------------------------------------------- channels


def test_the_publishing_screen_answers_with_two_accounts_connected_and_none_bound(
    client, headers, engine, studio
):
    """This returned 500 on the Owner's studio, and the screen blamed both panels for it."""
    first = connect_account(engine, "Nexus Curiosity", "UC-a", "NEXUS CURIOSITY")
    connect_account(engine, "Inside The Nexus", "UC-b", "INSIDE THE NEXUS")

    response = client.get("/api/v1/publishing/channels", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["channels"]) == 2
    assert {a["name"] for a in body["youtube_accounts"]} == {"Nexus Curiosity", "Inside The Nexus"}
    assert body["publisher_configured"] is False
    assert "niciun slot de canal legat" in body["binding_hint"]
    assert all(c["publisher_ready"] is False for c in body["channels"])
    assert client.get("/api/v1/publishing/publications", headers=headers).status_code == 200

    # Binding a slot is what makes it publishable, and the screen says which account it uses.
    slot = body["channels"][0]
    bound = client.put(
        f"/api/v1/settings/channels/{slot['id']}",
        headers=headers,
        json={"connection_id": first, "expected_event_id": slot["event_id"]},
    )
    assert bound.status_code == 200, bound.text
    after = client.get("/api/v1/publishing/channels", headers=headers).json()
    ready = [c for c in after["channels"] if c["publisher_ready"]]
    assert len(ready) == 1
    assert ready[0]["youtube_channel_title"] == "NEXUS CURIOSITY"
    assert ready[0]["remote_channel_id"] == "UC-a"
    assert after["publisher_configured"] is True and after["binding_hint"] == ""
    assert channel_bindings(engine)[slot["id"]]["youtube_connection_id"] == first


def test_the_preflight_names_the_binding_as_the_missing_step(engine, settings, studio):
    vault = vault_for(engine)
    connect_account(engine, "Nexus Curiosity", "UC-a", "NEXUS CURIOSITY")
    check = next(
        c
        for c in run_preflight(engine, settings, vault)["checks"]
        if c["name"] == "youtube_channel_binding"
    )
    assert check["ok"] is False and "Leagă-le în Distribuție → Sloturi de canal" in check["message"]
    assert check["place"] == "publishing" and check["place_section"] == "channels-list"


def test_publishing_refuses_to_guess_which_account_an_unbound_slot_belongs_to(
    engine, settings, studio
):
    from app.runbook.stages import build_stage_runners

    vault = vault_for(engine)
    connect_account(engine, "Nexus Curiosity", "UC-a", "NEXUS CURIOSITY")
    connect_account(engine, "Inside The Nexus", "UC-b", "INSIDE THE NEXUS")
    runners = build_stage_runners(engine, settings, vault, ProviderRegistry())
    outcome = runners["publish"]()
    assert outcome["status"] == "SKIPPED"
    assert "niciun slot de canal" in outcome["reason"].lower()


# --------------------------------------------------------------------------- auto-configure


def test_auto_configure_finishes_a_verified_connection_without_choosing_for_the_owner(
    client, headers, engine, elevenlabs_api, runway_api
):
    """The Owner's complaint: both vendors connected, the studio still called them missing."""
    eleven, runway = str(uuid4()), str(uuid4())
    for identifier, kind, name in ((eleven, "elevenlabs", "AMN-AI"), (runway, "runway", "AMN-AI")):
        saved = client.put(
            f"/api/v1/settings/integrations/{identifier}",
            headers=headers,
            json={"kind": kind, "name": name, "secrets": {"api_key": f"k-{uuid4()}"}},
        )
        assert saved.status_code == 200 and saved.json()["status"] == "VERIFIED"
    vault = vault_for(engine)

    report = auto_configure(engine, vault)
    purposes = {
        item["purpose"] for item in report["applied"] if item["action"] == "selected_service"
    }
    assert {"voice", "image", "video"} <= purposes
    with Session(engine) as session:
        assert session.get(ServiceSelection, "image").integration_id == runway
        assert session.get(ServiceSelection, "voice").integration_id == eleven
        eleven_default = session.get(MediaProductionConfig, eleven)
        runway_default = session.get(MediaProductionConfig, runway)
        assert eleven_default.model_id == elevenlabs_api.models[0]["model_id"]
        assert eleven_default.voice_id in {v["voice_id"] for v in elevenlabs_api.voices}
        # The video default has to be a model the pipeline can call from a prompt.
        assert runway_default.model_id in runway_api.video_models
        assert runway_default.image_model_id == runway_api.image_model

    # Running it again changes nothing, and says so.
    again = auto_configure(engine, vault)
    assert again["applied"] == []
    assert {item["purpose"] for item in again["already_configured"]} >= {"voice", "image", "video"}

    # An Owner's own choice is never replaced.
    client.put(
        f"/api/v1/settings/integrations/{eleven}/production",
        headers=headers,
        json={
            "model_id": elevenlabs_api.models[0]["model_id"],
            "voice_id": elevenlabs_api.voices[1]["voice_id"],
            "expected_version": 1,
        },
    )
    auto_configure(engine, vault)
    with Session(engine) as session:
        assert (
            session.get(MediaProductionConfig, eleven).voice_id
            == (elevenlabs_api.voices[1]["voice_id"])
        )


def test_auto_configure_reports_an_ambiguous_purpose_instead_of_picking(
    client, headers, engine, runway_api
):
    first, second = str(uuid4()), str(uuid4())
    for identifier in (first, second):
        client.put(
            f"/api/v1/settings/integrations/{identifier}",
            headers=headers,
            json={
                "kind": "runway",
                "name": f"Runway {identifier[:4]}",
                "secrets": {"api_key": "k"},
            },
        )
    vault = vault_for(engine)
    report = auto_configure(engine, vault)
    assert report["applied"] == []
    ambiguous = {item["purpose"] for item in report["ambiguous"]}
    assert {"image", "video"} <= ambiguous
    with Session(engine) as session:
        assert session.get(ServiceSelection, "image") is None


# --------------------------------------------------------------------------- ideas


def test_the_researcher_proposes_scored_topics_and_duplicates_are_dropped(engine, settings, studio):
    add_allowed_host(engine, "www.iana.org")
    with Session(engine) as session, session.begin():
        from app.research.models import ResearchAllowedHost

        session.get(ResearchAllowedHost, "www.iana.org").last_test_status = "PASSED"

    def answer(prompt):
        assert "www.iana.org" in prompt
        candidate = {
            "title": "Example domains and the address that is not one",
            "topic": "internet",
            "angle": "Why one domain exists to be an example",
            "target_audience": "general",
            "expected_hosts": ["www.iana.org"],
            "scores": {
                "hook_potential": 0.8,
                "curiosity": 0.8,
                "story_potential": 0.7,
                "payoff_strength": 0.8,
                "visual_potential": 0.4,
                "fact_confidence": 0.9,
                "channel_fit": 0.8,
                "originality": 0.7,
                "shareability": 0.6,
                "retention_potential": 0.7,
                "cta_opportunity": 0.6,
                "production_feasibility": 0.9,
                "source_availability": 1.0,
            },
            "thesis": {
                "core_fact": "One domain exists only to be used as an example.",
                "why_it_matters": "Everyone has typed it and nobody knows why it is reserved.",
                "why_now": "The registry page was refreshed this week.",
                "payoff": "The address is reserved by the registry so nobody can own it.",
                "hook": "There is one web address nobody is allowed to buy.",
                "ending": "Reserved on purpose, by the registry itself.",
                "cta": "Which reserved address surprised you most?",
                "cta_kind": "COMMENT",
                "channel_fit": "Short, verifiable, one idea.",
                "visual_potential": "A browser bar, a registry page, a padlock.",
                "risk": "Nothing beyond the registry's own wording.",
                "expected_seconds": 30,
            },
        }
        return json.dumps(
            {
                "candidates": [
                    candidate,
                    # The same idea said again, and one on a site nobody authorised.
                    {**candidate, "title": "The address that is not one, and example domains"},
                    {**candidate, "title": "A different story", "expected_hosts": ["evil.example"]},
                ]
            }
        )

    registry, _ = registry_with(studio, answer)
    result = propose_topics(engine, registry, settings, str(uuid4()))
    assert len(result["proposed"]) == 1
    assert {r["why"].split(":")[0] for r in result["rejected"]} == {"duplicat", "site neautorizat"}
    with Session(engine) as session:
        topic = session.scalar(select(TopicIdea).where(TopicIdea.status == "PROPOSED"))
        # Weighted, not averaged: hook, payoff, story and fact confidence decide, so a
        # topic with little to show is not sunk by its visual score alone.
        assert topic.scores_json["composite"] == pytest.approx(0.75, abs=0.001)
        assert topic.source_plan_json == ["www.iana.org"]
        assert topic.proposed_by_agent_id and topic.novelty_score == 0.7
        # And the argument for making it at all is stored with it.
        assert topic.thesis_json["payoff"].startswith("The address is reserved")
        assert topic.rejection_reasons_json == []

    # Proposing again finds the stored title and adds nothing.
    assert propose_topics(engine, registry, settings, str(uuid4()))["proposed"] == []


def test_without_an_authorised_site_the_researcher_is_not_asked_to_invent_one(
    engine, settings, studio
):
    registry, model = registry_with(studio, lambda prompt: "{}")
    with pytest.raises(NoAuthorisedHosts):
        propose_topics(engine, registry, settings, str(uuid4()))
    assert model.prompts == []


def test_proposed_pages_are_fetched_by_the_studio_and_a_bad_url_is_only_recorded(
    engine, settings, studio, monkeypatch
):
    add_allowed_host(engine, "www.iana.org")
    with Session(engine) as session, session.begin():
        from app.research.models import ResearchAllowedHost

        session.get(ResearchAllowedHost, "www.iana.org").last_test_status = "PASSED"
        identifier = str(uuid4())
        event = append_event(
            session, "factual.topic_proposed", "topic_idea", identifier, 1, {}, str(uuid4())
        )
        session.add(
            TopicIdea(
                id=identifier,
                title="Example domains",
                topic="internet",
                angle="why",
                target_audience="general",
                novelty_score=0.8,
                status="PROPOSED",
                created_at=utc_now(),
                event_id=event.event_id,
                source_plan_json=["www.iana.org"],
            )
        )

    fetched: list[str] = []

    class StubRetriever:
        def fetch(self, url):
            fetched.append(url)
            if "missing" in url:
                from app.research.retrieval import RetrievalError

                raise RetrievalError("Source returned HTTP 404")
            from app.research.retrieval import RetrievedSource

            text = "Example domains are reserved for documentation."
            return RetrievedSource(
                requested_url=url,
                url=url,
                title="Example Domains",
                publisher="www.iana.org",
                text=text,
                retrieved_at=utc_now(),
                body_sha256=hashlib.sha256(text.encode()).hexdigest(),
                content_sha256=hashlib.sha256(text.encode()).hexdigest(),
                content_type="text/html",
            )

    import app.research.service as service

    monkeypatch.setattr(service, "SourceRetriever", lambda policy: StubRetriever())

    def answer(prompt):
        return json.dumps(
            {
                "urls": [
                    {"url": "https://www.iana.org/help/example-domains", "why": "the page itself"},
                    {"url": "https://www.iana.org/missing", "why": "a guess"},
                    {"url": "https://evil.example/page", "why": "off the allowlist"},
                ]
            }
        )

    registry, _ = registry_with(studio, answer)
    result = gather_sources(engine, registry, settings, identifier, str(uuid4()), limit=3)
    assert [f["url"] for f in result["fetched"]] == ["https://www.iana.org/help/example-domains"]
    assert {f["url"] for f in result["failed"]} == {
        "https://www.iana.org/missing",
        "https://evil.example/page",
    }
    # The host outside the allowlist was refused before any request was made.
    assert "https://evil.example/page" not in fetched
    with Session(engine) as session:
        stored = session.scalars(
            select(SourceSnapshot).where(SourceSnapshot.topic_id == identifier)
        ).all()
        assert len(stored) == 1
        assert "reserved for documentation" in stored[0].sanitized_content


# --------------------------------------------------------------------------- selection


def test_the_director_chooses_between_producible_topics_and_a_bad_choice_falls_back(
    engine, settings, studio
):
    from app.runbook.stages import build_stage_runners

    ids = []
    with Session(engine) as session, session.begin():
        for index in range(2):
            identifier = str(uuid4())
            ids.append(identifier)
            event = append_event(
                session, "factual.topic_proposed", "topic_idea", identifier, 1, {}, str(uuid4())
            )
            session.add(
                TopicIdea(
                    id=identifier,
                    title=f"Candidate {index}",
                    topic="space",
                    angle="angle",
                    target_audience="general",
                    novelty_score=0.5 + index / 10,
                    status="PROPOSED",
                    created_at=utc_now(),
                    event_id=event.event_id,
                )
            )
            session.flush()
            session.add(
                FactualClaim(
                    id=str(uuid4()),
                    topic_id=identifier,
                    source_id=None,
                    claim_text=f"Claim {index}",
                    claim_type="SCIENTIFIC_FACT",
                    importance="CRITICAL",
                    status="SUPPORTED",
                    confidence=0.9,
                    created_at=utc_now(),
                )
            )

    wanted = ids[0]  # not the highest novelty: the deterministic order would pick the other
    registry, model = registry_with(
        studio, lambda prompt: json.dumps({"topic_id": wanted, "reason": "mai multe dovezi"})
    )
    vault = vault_for(engine)
    outcome = build_stage_runners(engine, settings, vault, registry)["selection"]()
    assert outcome["status"] == "COMPLETED" and outcome["artefacts"]["topic_id"] == wanted
    assert outcome["artefacts"]["decided_by"] == "Director"
    assert "Ales de Director" in outcome["reason"]
    with Session(engine) as session:
        chosen = session.get(TopicIdea, wanted)
        assert chosen.status == "SELECTED" and chosen.decided_by == "Director"
        assert chosen.decision_notes == "mai multe dovezi"


def test_a_choice_that_names_nothing_on_the_list_does_not_decide_the_day(engine, settings, studio):
    from app.runbook.stages import build_stage_runners

    ids = []
    with Session(engine) as session, session.begin():
        for index in range(2):
            identifier = str(uuid4())
            ids.append(identifier)
            event = append_event(
                session, "factual.topic_proposed", "topic_idea", identifier, 1, {}, str(uuid4())
            )
            session.add(
                TopicIdea(
                    id=identifier,
                    title=f"Candidate {index}",
                    topic="space",
                    angle="angle",
                    target_audience="general",
                    novelty_score=0.5 + index / 10,
                    status="PROPOSED",
                    created_at=utc_now(),
                    event_id=event.event_id,
                )
            )
            session.flush()
            session.add(
                FactualClaim(
                    id=str(uuid4()),
                    topic_id=identifier,
                    source_id=None,
                    claim_text=f"Claim {index}",
                    claim_type="SCIENTIFIC_FACT",
                    importance="CRITICAL",
                    status="SUPPORTED",
                    confidence=0.9,
                    created_at=utc_now(),
                )
            )

    registry, _ = registry_with(
        studio, lambda prompt: json.dumps({"topic_id": str(uuid4()), "reason": "invented"})
    )
    vault = vault_for(engine)
    outcome = build_stage_runners(engine, settings, vault, registry)["selection"]()
    assert outcome["status"] == "COMPLETED"
    # The day still runs, on the deterministic order, and nobody is recorded as having decided.
    assert outcome["artefacts"]["decided_by"] is None
    with Session(engine) as session:
        assert session.get(TopicIdea, ids[1]).status == "SELECTED"
        assert session.get(TopicIdea, ids[1]).decided_by is None


def test_the_idea_stage_stops_when_the_pool_is_already_full(engine, settings, studio):
    from app.runbook.stages import IDEA_POOL_TARGET, build_stage_runners

    with Session(engine) as session, session.begin():
        for index in range(IDEA_POOL_TARGET):
            identifier = str(uuid4())
            event = append_event(
                session, "factual.topic_proposed", "topic_idea", identifier, 1, {}, str(uuid4())
            )
            session.add(
                TopicIdea(
                    id=identifier,
                    title=f"Waiting {index}",
                    topic="space",
                    angle="angle",
                    target_audience="general",
                    novelty_score=0.5,
                    status="PROPOSED",
                    created_at=utc_now(),
                    event_id=event.event_id,
                )
            )
    registry, model = registry_with(studio, lambda prompt: "{}")
    vault = vault_for(engine)
    outcome = build_stage_runners(engine, settings, vault, registry)["idea_generation"]()
    assert outcome["status"] == "COMPLETED" and "deja în așteptare" in outcome["reason"]
    assert model.prompts == [], "a full pool is not a reason to spend a run"


def test_prose_instead_of_candidates_proposes_nothing(engine, settings, studio):
    add_allowed_host(engine, "www.iana.org")
    with Session(engine) as session, session.begin():
        from app.research.models import ResearchAllowedHost

        session.get(ResearchAllowedHost, "www.iana.org").last_test_status = "PASSED"
    registry, _ = registry_with(studio, lambda prompt: "Here are some great ideas!")
    with pytest.raises(ResearchAgentError):
        propose_topics(engine, registry, settings, str(uuid4()))
    with Session(engine) as session:
        assert session.scalar(select(TopicIdea)) is None
