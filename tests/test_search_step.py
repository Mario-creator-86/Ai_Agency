"""The studio finds pages before the Researcher names them.

What is asserted: a site's search address is the Owner's to record and must be https on
the same host with ``{query}`` in it; a search answer in OpenSearch JSON becomes pages on
authorised hosts only, and a failed search is an empty answer; the Researcher's prompt
lists the pages found, and when every guess of his fails the found pages are read anyway;
the letter about a topic with no readable page carries each address and what the site
answered; a later evening pass that fails does not undo the first.
"""

from __future__ import annotations

import hashlib
import json
from uuid import uuid4

import pytest
from app.agents.models import Agent, AgentMessage, ModelRecord, Role
from app.agents.services import seed_initial_workforce
from app.factual.models import SourceSnapshot, TopicIdea
from app.media.services import seed_default_character_bibles
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.research.agent import gather_sources, search_queries
from app.research.retrieval import RetrievalError, RetrievedSource
from app.research.service import (
    HostError,
    add_allowed_host,
    find_pages,
    search_pages,
    set_search_template,
)
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

WIKI = "https://en.wikipedia.org/w/api.php?action=opensearch&search={query}&limit=5&format=json"
ANSWER = json.dumps(
    [
        "endangered languages",
        ["Endangered language", "Atlas of the World's Languages in Danger"],
        ["", ""],
        [
            "https://en.wikipedia.org/wiki/Endangered_language",
            "https://en.wikipedia.org/wiki/Atlas_of_the_World%27s_Languages_in_Danger",
        ],
    ]
)


class StubRetriever:
    """Answers a search with OpenSearch JSON and pages with text; 404s what it does not know."""

    def __init__(self, pages: dict[str, str], search_answer: str = ANSWER):
        self.pages = pages
        self.search_answer = search_answer
        self.asked: list[tuple[str, bool]] = []

    def fetch(self, url, *, accept_json=False):
        self.asked.append((url, accept_json))
        if accept_json:
            text = self.search_answer
            if text == "fail":
                raise RetrievalError("Source returned HTTP 500")
        elif url in self.pages:
            text = self.pages[url]
        else:
            raise RetrievalError("Source returned HTTP 404")
        return RetrievedSource(
            requested_url=url,
            url=url,
            title="A page" if not accept_json else "search",
            publisher="en.wikipedia.org",
            text=text,
            retrieved_at=utc_now(),
            body_sha256=hashlib.sha256(text.encode()).hexdigest(),
            content_sha256=hashlib.sha256(text.encode()).hexdigest(),
            content_type="application/json" if accept_json else "text/html",
        )


class ScriptedModel:
    def __init__(self, answer):
        self.answer = answer
        self.calls: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.calls.append(prompt)
        return GenerateResult(self.answer(prompt), 10, 40, None)


@pytest.fixture
def studio(engine, settings):
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    add_allowed_host(engine, "en.wikipedia.org")
    add_allowed_host(engine, "www.unesco.org")
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    from app.research.models import ResearchAllowedHost

    with Session(engine) as session, session.begin():
        for row in session.scalars(select(ResearchAllowedHost)):
            row.last_test_status = "PASSED"
    with Session(engine) as session:
        provider_id = session.scalar(select(Agent.provider_id))
        roles = {
            role.name: agent.id
            for agent, role in session.execute(
                select(Agent, Role).join(Role, Agent.role_id == Role.id)
            ).all()
        }
    return {"provider_id": provider_id, "roles": roles}


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


def test_the_search_address_is_the_owners_and_must_be_the_sites_own(engine, studio):
    view = set_search_template(engine, "en.wikipedia.org", WIKI)
    assert view["search_template"] == WIKI
    for bad in (
        "https://en.wikipedia.org/w/api.php?search=words",  # no {query}
        "http://en.wikipedia.org/w/api.php?search={query}",  # not https
        "https://www.unesco.org/search?q={query}",  # another host
    ):
        with pytest.raises(HostError):
            set_search_template(engine, "en.wikipedia.org", bad)
    with pytest.raises(HostError):
        set_search_template(engine, "nobody.example", WIKI)
    assert set_search_template(engine, "en.wikipedia.org", None)["search_template"] is None


def test_a_search_answer_becomes_pages_on_authorised_hosts_only(engine, settings, studio):
    set_search_template(engine, "en.wikipedia.org", WIKI)
    off = json.dumps(
        [
            "q",
            ["Fine", "Off the list"],
            ["", ""],
            ["https://en.wikipedia.org/wiki/Fine", "https://evil.example/page"],
        ]
    )
    stub = StubRetriever({}, search_answer=off)
    pages = search_pages(settings, engine, "en.wikipedia.org", "fine  words", retriever=stub)
    assert pages == [
        {"url": "https://en.wikipedia.org/wiki/Fine", "title": "Fine", "host": "en.wikipedia.org"}
    ]
    assert stub.asked[0][0].endswith("search=fine%20words&limit=5&format=json")
    assert stub.asked[0][1] is True
    # A host without an address, and a search that fails, are empty answers — not errors.
    assert search_pages(settings, engine, "www.unesco.org", "words", retriever=stub) == []
    failing = StubRetriever({}, search_answer="fail")
    assert search_pages(settings, engine, "en.wikipedia.org", "words", retriever=failing) == []
    assert find_pages(settings, engine, "endangered languages", retriever=stub)[0]["host"] == (
        "en.wikipedia.org"
    )


def test_the_researcher_sees_the_pages_found_and_they_are_read_when_his_guesses_fail(
    engine, settings, studio, monkeypatch
):
    set_search_template(engine, "en.wikipedia.org", WIKI)
    atlas = "https://en.wikipedia.org/wiki/Atlas_of_the_World%27s_Languages_in_Danger"
    stub = StubRetriever(
        {
            "https://en.wikipedia.org/wiki/Endangered_language": "An endangered language is one "
            "that is at risk of disappearing as its speakers die out or shift to other languages.",
            atlas: "The Atlas of the World's Languages in Danger is a UNESCO publication.",
        }
    )
    import app.research.service as service

    monkeypatch.setattr(service, "SourceRetriever", lambda policy: stub)

    registry = ProviderRegistry()
    model = ScriptedModel(
        lambda prompt: json.dumps(
            {"urls": [{"url": "https://www.unesco.org/en/endangered-languages", "why": "guess"}]}
        )
    )
    registry.register(studio["provider_id"], model)

    topic_id = a_topic(engine)
    result = gather_sources(engine, registry, settings, topic_id, str(uuid4()), limit=3)

    # The prompt listed what the studio found; the guess failed; the found pages were read.
    assert "Endangered_language" in model.calls[0] and "prefer them" in model.calls[0]
    assert [f["url"] for f in result["failed"]] == [
        "https://www.unesco.org/en/endangered-languages"
    ]
    assert {f["url"] for f in result["fetched"]} == {
        "https://en.wikipedia.org/wiki/Endangered_language",
        atlas,
    }
    assert len(result["found"]) == 2
    with Session(engine) as session:
        stored = session.scalars(
            select(SourceSnapshot).where(SourceSnapshot.topic_id == topic_id)
        ).all()
        assert len(stored) == 2
        # Pages were read: no letter says nothing could be.
        assert (
            session.scalar(
                select(AgentMessage).where(AgentMessage.subject.like("Nicio sursă preluată%"))
            )
            is None
        )


def test_the_letter_about_a_topic_with_no_readable_page_carries_the_evidence(
    engine, settings, studio, monkeypatch
):
    stub = StubRetriever({}, search_answer=json.dumps(["q", [], [], []]))
    import app.research.service as service

    monkeypatch.setattr(service, "SourceRetriever", lambda policy: stub)
    registry = ProviderRegistry()
    registry.register(
        studio["provider_id"],
        ScriptedModel(
            lambda prompt: json.dumps(
                {
                    "urls": [
                        {"url": "https://www.unesco.org/en/endangered-languages", "why": "a"},
                        {"url": "https://www.unesco.org/en/articles/atlas", "why": "b"},
                    ]
                }
            )
        ),
    )
    topic_id = a_topic(engine)
    result = gather_sources(engine, registry, settings, topic_id, str(uuid4()), limit=3)
    assert result["fetched"] == [] and len(result["failed"]) == 2
    with Session(engine) as session:
        letter = session.scalar(
            select(AgentMessage).where(AgentMessage.subject.like("Nicio sursă preluată%"))
        )
        assert letter is not None and letter.body_text is not None
        assert "https://www.unesco.org/en/endangered-languages — Source returned HTTP 404" in (
            letter.body_text
        )
        assert "AutonomousAIStudio-SourceRetriever" in letter.body_text


def test_the_owner_records_and_tries_a_search_address_through_the_api(
    client, headers, engine, studio, monkeypatch
):
    stub = StubRetriever({})
    client.app.app.state.source_retriever = stub  # the app behind TrustedHostMiddleware
    put = client.put(
        "/api/v1/factual/sources/allowed-hosts/en.wikipedia.org/search",
        json={"template": WIKI},
        headers=headers,
    )
    assert put.status_code == 200 and put.json()["search_template"] == WIKI
    bad = client.put(
        "/api/v1/factual/sources/allowed-hosts/en.wikipedia.org/search",
        json={"template": "https://elsewhere.example/?q={query}"},
        headers=headers,
    )
    assert bad.status_code == 422
    listed = client.get("/api/v1/factual/sources/allowed-hosts", headers=headers).json()["hosts"]
    assert next(h for h in listed if h["host"] == "en.wikipedia.org")["search_template"] == WIKI
    tried = client.post(
        "/api/v1/factual/sources/allowed-hosts/en.wikipedia.org/search/test",
        json={"query": "endangered languages"},
        headers=headers,
    )
    assert tried.status_code == 200
    assert [p["title"] for p in tried.json()["found"]] == [
        "Endangered language",
        "Atlas of the World's Languages in Danger",
    ]


def test_a_later_evening_pass_that_fails_does_not_undo_the_first(monkeypatch, engine):
    from app.runbook import stages

    calls = {"n": 0}

    def review(engine_, registry, correlation, outcomes):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"reviewed": 12, "applied": [1] * 12, "left_open": 5}
        raise stages.DirectorError("The Director produced no usable review (EMPTY_OUTPUT)")

    monkeypatch.setattr(stages, "director_review", review)
    monkeypatch.setattr(stages, "letter_to_owner", lambda *a, **k: pytest.fail("no letter"))
    monkeypatch.setattr(stages, "archive_stale_reports", lambda engine_: 0)
    monkeypatch.setattr(stages, "file_stage_reports", lambda *a, **k: ["r"] * 9)
    monkeypatch.setattr(stages, "reconcile_day", lambda *a, **k: {"error": "no accountant"})
    monkeypatch.setattr(stages, "_has_language_model", lambda registry: True)
    outcome = stages._post_run(engine, ProviderRegistry(), {})
    assert calls["n"] == 2
    assert "a revizuit 12 mesaje" in outcome["reason"]


def test_the_searches_are_the_names_in_the_title_not_the_sentence():
    """A suggestion search matches the start of a page title: the whole sentence finds
    nothing, the proper names in it find pages. Longer names first, a long name also as
    its first two words, never more than six."""
    title = "How the James Webb Space Telescope Sees the First Galaxies"
    queries = search_queries(title, "JWST's detection of early-universe galaxies at redshift z>10")
    assert queries[0] == "James Webb Space Telescope"
    assert "James Webb" in queries and "First Galaxies" in queries and "JWST" in queries
    assert title not in queries and "How" not in queries and len(queries) <= 6
    cern = search_queries("How CERN Measures the Higgs Boson's Lifetime")
    assert cern[0] == "Higgs Boson Lifetime" and "Higgs Boson" in cern and "CERN" not in cern[0]
    assert "UNESCO" in search_queries("How UNESCO Tracks Endangered Languages in Real Time")
    assert search_queries("a tale of nothing in particular") == []


def test_pages_are_found_query_by_query_and_never_listed_twice(engine, settings, studio):
    set_search_template(engine, "en.wikipedia.org", WIKI)

    class ByQuery(StubRetriever):
        def fetch(self, url, *, accept_json=False):
            self.asked.append((url, accept_json))
            if "search=Higgs%20Boson" in url:
                text = json.dumps(
                    [
                        "q",
                        ["Higgs boson", "Higgs field"],
                        ["", ""],
                        [
                            "https://en.wikipedia.org/wiki/Higgs_boson",
                            "https://en.wikipedia.org/wiki/Higgs_field",
                        ],
                    ]
                )
            elif "search=CERN" in url:
                text = json.dumps(
                    [
                        "q",
                        ["CERN", "Higgs boson"],
                        ["", ""],
                        [
                            "https://en.wikipedia.org/wiki/CERN",
                            "https://en.wikipedia.org/wiki/Higgs_boson",
                        ],
                    ]
                )
            else:
                text = json.dumps(["q", [], [], []])
            return RetrievedSource(
                url,
                url,
                "search",
                "en.wikipedia.org",
                text,
                utc_now(),
                "0" * 64,
                "0" * 64,
                "application/json",
            )

    stub = ByQuery({})
    pages = find_pages(settings, engine, ["Higgs Boson Lifetime", "Higgs Boson", "CERN"], 6, stub)
    assert [p["url"].rsplit("/", 1)[1] for p in pages] == ["Higgs_boson", "Higgs_field", "CERN"]
    assert len(stub.asked) == 3


def test_one_mistyped_claim_is_skipped_and_the_others_kept():
    """ "confidence": 0.95.0 in one object of the third clean day's answer stopped the whole
    run and put the studio in safe mode. One broken object is one claim lost."""
    from app.factual.agent_pipeline import _parse_claims

    raw = (
        '[{"claim_text": "Dark matter makes up about 27% of the universe.", '
        '"claim_type": "SCIENTIFIC_FACT", "importance": "CRITICAL", "confidence": 0.95}, '
        '{"claim_text": "Dark energy makes up approximately 68% of the universe.", '
        '"claim_type": "SCIENTIFIC_FACT", "importance": "CRITICAL", "confidence": 0.95.0}, '
        '{"claim_text": "Normal matter is five percent.", "claim_type": "SCIENTIFIC_FACT", '
        '"importance": "SUPPORTING", "confidence": 0.9}]'
    )
    items = _parse_claims(raw)
    assert [i.claim_text[:11] for i in items] == ["Dark matter", "Dark energy", "Normal matt"]
    with pytest.raises(ValueError):
        _parse_claims("no list here at all")


def test_a_source_whose_claims_cannot_be_read_does_not_stop_the_day(
    engine, settings, studio, monkeypatch
):
    from app.runbook import stages

    with Session(engine) as session, session.begin():
        for index in range(2):
            session.add(
                SourceSnapshot(
                    id=str(uuid4()),
                    url=f"https://en.wikipedia.org/wiki/Page_{index}",
                    title=f"Page {index}",
                    publisher="en.wikipedia.org",
                    content_hash=str(index) * 64,
                    raw_content="text",
                    sanitized_content="text",
                    credibility_score=0.0,
                    fetched_at=utc_now(),
                )
            )
    calls: list[str] = []

    def extract(engine_, registry, source_id, correlation):
        calls.append(source_id)
        if len(calls) == 1:
            raise ValueError("Răspunsul agentului nu este o listă JSON validă")

    monkeypatch.setattr(stages, "agent_extract_claims", extract)
    monkeypatch.setattr(stages, "_gather_for_candidates", lambda *a, **k: [])
    monkeypatch.setattr(stages, "_has_language_model", lambda registry: True)
    outcome = stages._research_and_verification(engine, ProviderRegistry(), settings)
    assert outcome["status"] == "COMPLETED" and len(calls) == 2
    assert (
        "1 surse citite" in outcome["reason"]
        and "1 surse fără afirmații citibile" in (outcome["reason"])
    )


def test_a_storyboard_speaks_the_writers_narration_and_shows_his_pictures(engine, studio):
    """The seventh clean day built a storyboard of eight silent scenes called "Scene 1"…
    "Scene 8" from a real script: the builder read the demo fixture's keys, not the
    writer's. The narration and the picture come from the script; a scene lasts as long
    as its words take to say."""
    from app.factual.models import ScriptDraft
    from app.media.services import generate_storyboard_from_script

    topic_id = a_topic(engine)
    script_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title="The Universe's Missing Pieces",
                target_duration_seconds=50,
                voiceover_full_text="Look around. Everything you see is five percent.",
                scenes_json=[
                    {
                        "scene_number": 1,
                        "narration": "Look around. Everything you see is five percent of the "
                        "universe, and the rest has never been seen.",
                        "visual_description": "A starry sky with a small silhouette.",
                        "claim_ids": ["c1"],
                    },
                    {
                        "scene_number": 2,
                        "narration": "The rest is dark.",
                        "visual_description": "A galaxy with an invisible halo.",
                        "claim_ids": ["c1"],
                    },
                ],
                status="APPROVED",
                claim_ids_json=["c1"],
                unverified_claim_ids_json=[],
                created_at=utc_now(),
            )
        )
    board = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    scenes = sorted(board["scenes"], key=lambda s: s["scene_index"])
    assert scenes[0]["voiceover_segment"].startswith("Look around.")
    assert scenes[0]["visual_prompt"] == "A starry sky with a small silhouette."
    assert scenes[0]["duration_seconds"] == 7.2 and scenes[1]["duration_seconds"] == 3.0


def test_a_providers_refusal_fails_the_render_not_the_day(engine, settings, studio, monkeypatch):
    """Runway answered HTTP 400 on the seventh clean day; the media stage raised, the day
    failed and the studio entered safe mode. A refusal is that render's failure: the
    storyboard stays approved for tomorrow and the report says who refused."""
    from app.factual.models import FactualClaim, ScriptDraft
    from app.media import assembler, factory
    from app.media.services import generate_storyboard_from_script
    from app.providers.media_http import MediaProviderError
    from app.runbook import stages

    script_id = str(uuid4())
    topic_id = a_topic(engine)
    narration = "UNESCO's atlas lists about 2,500 endangered languages."
    with Session(engine) as session, session.begin():
        # The film says what its claim says: the gate before the render measures that now
        # (`app.factual.grounding`), and a film citing a claim that does not exist is held
        # there, before the refusal this test is about could happen.
        session.add(
            FactualClaim(
                id="c1",
                topic_id=topic_id,
                claim_text=(
                    "UNESCO's Atlas of the World's Languages in Danger lists about 2,500 "
                    "endangered languages."
                ),
                claim_type="STATISTIC",
                importance="CRITICAL",
                status="SUPPORTED",
                confidence=0.9,
                created_at=utc_now(),
            )
        )
        session.flush()
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title="A film",
                target_duration_seconds=50,
                voiceover_full_text=narration,
                scenes_json=[
                    {
                        "scene_number": 1,
                        "narration": narration,
                        "visual_description": "A picture.",
                        "claim_ids": ["c1"],
                    }
                ],
                status="APPROVED",
                claim_ids_json=["c1"],
                unverified_claim_ids_json=[],
                created_at=utc_now(),
            )
        )
    generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    # The story was read and passed before production; without that the render stage holds
    # the film rather than buying shots for a story nobody judged.
    with Session(engine) as session, session.begin():
        from app.factual.models import StoryReview

        session.add(
            StoryReview(
                id=str(uuid4()),
                script_id=script_id,
                verdict="PASS",
                checks_json={},
                retention_json={},
                scores_json={},
                notes_json={},
                estimated_seconds=30.0,
                created_at=utc_now(),
            )
        )

    def refuse(*args, **kwargs):
        raise MediaProviderError("api.dev.runwayml.com refused the request (HTTP 400)")

    monkeypatch.setattr(assembler, "assemble_video_job", refuse)
    monkeypatch.setattr(factory, "image_provider", lambda engine_, vault: object())
    monkeypatch.setattr(factory, "tts_provider", lambda engine_, vault: object())
    monkeypatch.setattr(
        factory,
        "render_plan",
        lambda engine_, vault, board: {
            "image": None,
            "tts_for_scene": lambda *a: None,
            "video_for_scene": lambda *a: None,
            "plan": {},
        },
    )
    outcome = stages._media(engine, settings, None, None)
    assert outcome["status"] == "COMPLETED"
    assert "1 randări refuzate de furnizor: api.dev.runwayml.com refused" in outcome["reason"]
    with Session(engine) as session:
        from app.media.models import Storyboard

        assert session.scalar(select(Storyboard.status)) == "APPROVED"


def test_rebuilding_a_storyboard_supersedes_the_unrendered_one(engine, studio):
    from app.factual.models import ScriptDraft
    from app.media.models import Storyboard
    from app.media.services import generate_storyboard_from_script

    script_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=a_topic(engine),
                version=1,
                title="A film",
                target_duration_seconds=50,
                voiceover_full_text="Words.",
                scenes_json=[
                    {"scene_number": 1, "narration": "Words that carry.", "claim_ids": ["c1"]}
                ],
                status="APPROVED",
                claim_ids_json=["c1"],
                unverified_claim_ids_json=[],
                created_at=utc_now(),
            )
        )
    first = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    second = generate_storyboard_from_script(engine, script_id, "MOTION_GRAPHIC", "9:16", "c")
    with Session(engine) as session:
        status = {b.id: b.status for b in session.scalars(select(Storyboard))}
    assert status == {first["id"]: "REJECTED", second["id"]: "APPROVED"}
