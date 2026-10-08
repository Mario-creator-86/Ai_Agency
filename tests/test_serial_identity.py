"""S10: the serial's identity at publish, the honest record of who read it, and its tone.

What was measured before this step (2026-09-24), on the code:

- the Publisher was handed an episode as "Storyboard: <title>" and its scenes, nothing else:
  no series, no episode number, no logline, no previous episode, so the rehearsal published
  the episode under the factual film's title and a returning viewer had nothing to follow;
- an episode the Owner approved straight from DRAFT, which the Director never read, was put
  on the story gate's record as her PASS, with her as the reviewer;
- the showrunner's brief never named the serial's comic engine or its tone, and carried all
  eight character bibles in full (about 16.5k characters) although two to four people speak.

Every provider is faked here; nothing is bought and no real run starts.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.agents.models import Agent, ModelRecord, Role
from app.agents.reviews import approved_metadata, prepare_publication
from app.factual.models import StoryReview
from app.factual.story_review import latest_review, story_gate
from app.media.models import CharacterBible, Storyboard
from app.media.serial_storyboard import OWNER_ONLY_NOTE, storyboard_from_episode
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.publishing.models import ChannelRecord, PublicationRecord
from app.publishing.serial_identity import hook_of, series_title
from app.publishing.services import create_publication_intent, publication_metadata_refusals
from app.services import utc_now
from app.story.lines import NameBook
from app.story.models import DailyStudioLog, StoryEpisode
from app.story.review import review_episode
from app.story.services import (
    EPISODE_TEMPLATE_VERSION,
    SHOW_TONE,
    _who_they_are,
    acting_cast,
    bibles_for_roster,
    decide_episode,
    write_episode,
)
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from test_publication_metadata_per_film import _rendered
from test_serial_pipeline import (
    KAEL,
    NEXT,
    SARAH,
    a_day,
    a_factual_storyboard,
    allow_director_approval,
    beats_for,
    fake_director,
    fake_showrunner,
    letters_day,
    registry,
    roster_names,
)

EP_TITLE = "The Cut Runs Long"
LOGLINE = "Kael's cut runs long, and Sarah wants it short before anyone says good morning."
SUMMARY = "Sarah asked for a shorter cut. Kael defended every frame, then cut one."
SERIES = "Inside The Nexus"


@pytest.fixture
def staffed(engine):
    """The staffed studio of the serial tests: workforce, bibles, channels, autonomy on."""
    from app.agents.services import seed_initial_workforce
    from app.media.services import seed_default_character_bibles
    from app.models import OwnerPolicy
    from app.publishing.services import seed_default_channels

    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    return engine


def answer(ids: list[str], names: list[str], title: str = EP_TITLE, **extra) -> str:
    body = {
        "title": title,
        "beats": beats_for(ids, names),
        "summary": SUMMARY,
        "logline": LOGLINE,
        "next_episode": NEXT,
    }
    body.update(extra)
    return json.dumps(body)


def an_episode(
    engine,
    monkeypatch,
    when: datetime | None = None,
    title: str = EP_TITLE,
    seen: list[str] | None = None,
    **extra,
) -> dict:
    """A day of letters between Sarah and Kael, written as an episode (a DRAFT)."""
    log, ids = letters_day(engine, when)
    fake_showrunner(monkeypatch, answer(ids, [SARAH, KAEL], title=title, **extra), seen)
    return write_episode(engine, registry(), log["id"], str(uuid4()))["episode"]


def gate_record(engine, board_id: str) -> StoryReview:
    with Session(engine) as session:
        board = session.get(Storyboard, board_id)
        review = latest_review(session, board.script_draft_id)
        assert review is not None
        session.expunge(review)
        return review


def director_id(engine) -> str:
    with Session(engine) as session:
        return session.scalars(
            select(Agent.id).join(Role, Agent.role_id == Role.id).where(Role.name == "Director")
        ).one()


# ---------------------------------------------------------------------------
# The honest record: who read the episode before it was filmed
# ---------------------------------------------------------------------------


def test_an_episode_the_director_never_read_is_recorded_as_the_owners_approval(
    engine, staffed, monkeypatch
):
    episode = an_episode(engine, monkeypatch)
    decide_episode(engine, episode["id"], True, "")  # straight from DRAFT, never reviewed

    board_id = storyboard_from_episode(engine, episode["id"], str(uuid4()))
    record = gate_record(engine, board_id)

    # The gate still lets his approval through: PASS is the value it accepts.
    assert record.verdict == "PASS"
    # And nothing on the row says the Director read it.
    assert record.reviewer_agent_id is None and record.run_id is None
    assert record.checks_json == {}
    assert record.notes_json["source"] == "owner_approval"
    assert record.notes_json["approved_by"] == "owner"
    assert record.notes_json["director_review"] is None
    assert record.notes_json["notes"] == [OWNER_ONLY_NOTE]
    assert "fără recenzia Directorului" in OWNER_ONLY_NOTE
    with Session(engine) as session:
        board = session.get(Storyboard, board_id)
        assert story_gate(session, board.script_draft_id) == (True, "")


def test_the_production_package_says_who_approved_the_story(engine, staffed, monkeypatch):
    """The Owner's audit view read "story_review: PASS" for an episode nobody reviewed; it
    now names who approved it and whether the Director read it."""
    from app.media.prompt_agent import production_package

    unread = an_episode(engine, monkeypatch)
    decide_episode(engine, unread["id"], True, "")
    approval = production_package(
        engine, storyboard_from_episode(engine, unread["id"], str(uuid4()))
    )["approval"]
    assert approval["story_review"] == "PASS"
    assert approval["story_review_source"] == "owner_approval"
    assert approval["approved_by"] == "owner"
    assert approval["director_review"] is None
    assert approval["story_review_notes"] == [OWNER_ONLY_NOTE]

    read = an_episode(engine, monkeypatch, when=datetime.now(UTC) + timedelta(days=1))
    fake_director(monkeypatch, "PASS")
    review_episode(engine, registry(), read["id"], str(uuid4()))
    decide_episode(engine, read["id"], True, "")
    approval = production_package(
        engine, storyboard_from_episode(engine, read["id"], str(uuid4()))
    )["approval"]
    assert approval["story_review_source"] == "story.episode_review"
    assert approval["director_review"] == "PASS"
    assert approval["approved_by"] == "owner"


def test_an_episode_the_director_passed_keeps_her_reading_whoever_approved_it(
    engine, staffed, monkeypatch
):
    episode = an_episode(engine, monkeypatch)
    fake_director(monkeypatch, "PASS")
    reviewed = review_episode(engine, registry(), episode["id"], str(uuid4()))
    assert reviewed["verdict"] == "PASS" and reviewed["status"] == "DRAFT"
    decide_episode(engine, episode["id"], True, "")

    record = gate_record(engine, storyboard_from_episode(engine, episode["id"], str(uuid4())))

    assert record.verdict == "PASS"
    assert record.reviewer_agent_id == director_id(engine)
    # Her run is linked while its row exists; the faked run here wrote none, so the link is
    # left empty rather than dangling (the rule the storyboard already had).
    assert record.checks_json == reviewed["checks"]
    assert record.notes_json["source"] == "story.episode_review"
    assert record.notes_json["director_review"] == "PASS"
    assert record.notes_json["approved_by"] == "owner"


def test_an_episode_the_director_approved_under_the_policy_is_hers(engine, staffed, monkeypatch):
    allow_director_approval(engine)
    episode = an_episode(engine, monkeypatch)
    fake_director(monkeypatch, "PASS")
    assert review_episode(engine, registry(), episode["id"])["status"] == "APPROVED"

    record = gate_record(engine, storyboard_from_episode(engine, episode["id"], str(uuid4())))

    assert record.reviewer_agent_id == director_id(engine)
    assert record.notes_json["approved_by"] == "director"
    assert record.notes_json["source"] == "story.episode_review"


def test_the_story_gate_is_as_strict_as_it_was(engine, staffed, monkeypatch):
    """The honest record changes no gate: no record, or a record that is not a PASS, still
    stops the film before anything is bought."""
    episode = an_episode(engine, monkeypatch)
    decide_episode(engine, episode["id"], True, "")
    board_id = storyboard_from_episode(engine, episode["id"], str(uuid4()))
    with Session(engine) as session, session.begin():
        script_id = session.get(Storyboard, board_id).script_draft_id
        session.get(StoryReview, gate_record(engine, board_id).id).verdict = "REVISE"
    with Session(engine) as session:
        assert story_gate(session, script_id)[0] is False
    with Session(engine) as session, session.begin():
        session.execute(delete(StoryReview).where(StoryReview.script_id == script_id))
    with Session(engine) as session:
        assert story_gate(session, script_id)[0] is False


# ---------------------------------------------------------------------------
# The brief: the show's tone, and the bibles of those who act
# ---------------------------------------------------------------------------


def cast_block(prompt: str) -> str:
    return prompt.split("CAST ON", 1)[1].split("LOCATIONS (", 1)[0]


def test_the_brief_states_the_shows_tone_and_asks_for_a_logline(engine, staffed, monkeypatch):
    seen: list[str] = []
    episode = an_episode(engine, monkeypatch, seen=seen)

    (prompt,) = seen
    assert "THE SHOW\n" + SHOW_TONE in prompt
    assert "deadpan workplace comedy" in SHOW_TONE and "take their jobs" in SHOW_TONE
    assert '"logline":' in prompt
    assert episode["continuity"]["template_version"] == EPISODE_TEMPLATE_VERSION == "episode-v6"
    assert episode["continuity"]["logline"] == LOGLINE


def test_only_those_who_act_in_the_days_events_get_their_whole_bible(engine, staffed, monkeypatch):
    """A day two days back: the seeded workforce's own hiring (today) is not in it, so the
    people who act are the two who wrote the letters."""
    seen: list[str] = []
    an_episode(engine, monkeypatch, when=datetime.now(UTC) - timedelta(days=2), seen=seen)

    (prompt,) = seen
    block = cast_block(prompt)
    with Session(engine) as session:
        log = session.get(DailyStudioLog, _newest_log(session))
        bibles = bibles_for_roster(session, list(log.roster_json))
        acting = acting_cast(log.narrative_projection_json, NameBook(log.roster_json, bibles))
        whole = {name: _who_they_are(name, bible) for name, bible in bibles.items()}
    assert len(whole) == 8
    assert acting == [SARAH, KAEL]
    for name, text in whole.items():
        # Everyone is on the cast list, by name; those who act are described in full.
        assert f"- {name} — " in block
        if name in acting:
            assert text in block, name
        else:
            assert text not in block, name
            assert bibles[name].face_hair_desc not in block, name
    # Measured, not guessed: the whole eight against what this brief carries.
    full = sum(len(text) for text in whole.values())
    assert len(block) < full / 2, (len(block), full)


def test_a_day_nobody_acts_in_gives_every_bible_whole(engine, staffed, monkeypatch):
    """With fewer than two people in the events the writer casts from anyone, so everyone
    is described in full, as before v4."""
    log, ids = a_day(engine, datetime.now(UTC) - timedelta(days=2))
    names = roster_names(engine, log["id"])
    seen: list[str] = []
    fake_showrunner(monkeypatch, answer(ids, names), seen)
    write_episode(engine, registry(), log["id"], str(uuid4()))

    (prompt,) = seen
    with Session(engine) as session:
        row = session.get(DailyStudioLog, log["id"])
        bibles = bibles_for_roster(session, list(row.roster_json))
        acting = acting_cast(row.narrative_projection_json, NameBook(row.roster_json, bibles))
        assert len(acting) < 2, acting
        assert len(bibles) == 8
        for bible in session.scalars(select(CharacterBible)):
            assert bible.face_hair_desc in cast_block(prompt), bible.canonical_name


def _newest_log(session) -> str:
    return session.scalars(
        select(DailyStudioLog.id).order_by(DailyStudioLog.business_date.desc())
    ).first()


# ---------------------------------------------------------------------------
# The identity at publish
# ---------------------------------------------------------------------------


class Publisher:
    """Answers the Publisher by which film the prompt carries, and keeps every prompt."""

    def __init__(self, for_episode: dict, for_factual: dict) -> None:
        self.for_episode, self.for_factual = for_episode, for_factual
        self.prompts: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.prompts.append(prompt)
        body = self.for_episode if f'"series": "{SERIES}"' in prompt else self.for_factual
        return GenerateResult(json.dumps(body), 10, 40, None)


#: What a stand-in answered every prompt with: another film's metadata.
STAND_IN = {
    "verdict": "READY",
    "title": "Infrared light and what it shows",
    "description": "What a telescope sees when it looks in infrared.",
    "tags": ["space", "astronomy"],
    "hold_reasons": [],
}
HOOK = {
    "verdict": "READY",
    "title": "Kael defends every frame",
    "description": "A morning at the studio, one cut too long.",
    "tags": ["office serial", "studio life"],
    "hold_reasons": [],
}


@pytest.fixture
def films(engine, staffed, monkeypatch):
    with Session(engine) as session, session.begin():
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        provider_id = session.scalars(
            select(Agent.provider_id).join(Role, Agent.role_id == Role.id)
        ).first()
        channels = {c.channel_type: c.id for c in session.scalars(select(ChannelRecord))}
    episode = an_episode(engine, monkeypatch)
    decide_episode(engine, episode["id"], True, "")
    serial_board = storyboard_from_episode(engine, episode["id"], str(uuid4()))
    return {
        "provider_id": provider_id,
        "channels": channels,
        "episode": episode,
        "episode_asset": _rendered(engine, serial_board),
        "factual_asset": _rendered(engine, a_factual_storyboard(engine)["id"]),
    }


def prepare(engine, films, model: Publisher, which: str = "episode") -> dict:
    provider = ProviderRegistry()
    provider.register(films["provider_id"], model)
    channel = films["channels"]["OFFICE_SERIAL" if which == "episode" else "MAIN_FACTUAL"]
    return prepare_publication(engine, provider, films[f"{which}_asset"], channel, str(uuid4()))


def facts_of(prompt: str) -> dict:
    block = prompt.split("<untrusted_source_evidence", 1)[1].split(">", 1)[1]
    return json.loads(block.split("</untrusted_source_evidence>", 1)[0].strip())


def test_the_publishers_facts_carry_the_series_and_the_episode(engine, films):
    model = Publisher(for_episode=HOOK, for_factual=STAND_IN)

    prepare(engine, films, model)

    (prompt,) = model.prompts
    facts = facts_of(prompt)
    assert facts["series"] == SERIES
    assert facts["episode_number"] == 1
    assert facts["episode_title"] == facts["script_title"] == EP_TITLE
    assert facts["logline"] == LOGLINE
    assert facts["previous_episode"] is None  # the first episode has none
    assert facts["title_format"] == "<hook> | Inside The Nexus Ep. 1"
    assert "Storyboard:" not in prompt


def test_a_ready_title_takes_the_series_format_and_the_logline_opens_the_description(engine, films):
    result = prepare(engine, films, Publisher(for_episode=HOOK, for_factual=STAND_IN))

    assert result["verdict"] == "READY" and result["metadata_source"] == "publisher"
    assert result["title"] == "Kael defends every frame | Inside The Nexus Ep. 1"
    assert result["description"].startswith(LOGLINE + "\n\n" + HOOK["description"])
    assert result["tags"][0] == SERIES and "office serial" in result["tags"]
    with Session(engine) as session:
        assert approved_metadata(session, films["episode_asset"]) == {
            "title": result["title"],
            "description": result["description"],
            "tags": result["tags"],
        }


@pytest.mark.parametrize(
    "written",
    [
        "Kael defends every frame | Inside The Nexus Ep. 1",
        "Inside The Nexus Ep. 1: Kael defends every frame",
        "Kael defends every frame - Inside the Nexus, Episode 1",
        "Storyboard: Kael defends every frame",
    ],
)
def test_the_format_is_written_once_whatever_the_model_wrote(engine, films, written):
    result = prepare(engine, films, Publisher({**HOOK, "title": written}, STAND_IN))

    assert result["title"] == "Kael defends every frame | Inside The Nexus Ep. 1"


def test_another_films_metadata_is_refused_and_the_episode_goes_under_its_own(engine, films):
    """The stand-in's mistake on a real model: the factual film's metadata for the episode.
    The guard refuses it as before; the studio's own title, from the episode, goes instead,
    and the refusal stays on the record."""
    model = Publisher(for_episode=STAND_IN, for_factual=STAND_IN)
    assert prepare(engine, films, model, "factual")["verdict"] == "READY"

    result = prepare(engine, films, model)

    assert result["verdict"] == "READY" and result["metadata_source"] == "studio_fallback"
    assert result["title"] == f"{EP_TITLE} | Inside The Nexus Ep. 1"
    assert result["description"].startswith(LOGLINE)
    assert STAND_IN["title"] not in result["description"]
    assert set(result["tags"]) >= {SERIES, "Sarah", "Kael"}
    reasons = " ".join(result["refusals"])
    assert "cuvânt cu cuvânt" in reasons and "niciun cuvânt comun" in reasons
    with Session(engine) as session:
        metadata = approved_metadata(session, films["episode_asset"])
        assert metadata["title"] == result["title"]
        # The upload's own gate, which reads the same guard, lets the fallback through.
        assert (
            publication_metadata_refusals(
                session,
                films["episode_asset"],
                films["channels"]["OFFICE_SERIAL"],
                metadata["title"],
                metadata["tags"],
            )
            == []
        )


def test_a_hold_the_publisher_gave_herself_stays_a_hold(engine, films):
    held = {**HOOK, "verdict": "HOLD", "hold_reasons": ["The joke may read as a real outage."]}

    result = prepare(engine, films, Publisher(held, STAND_IN))

    assert result["verdict"] == "HOLD" and result["metadata_source"] == "publisher"
    assert result["hold_reasons"] == held["hold_reasons"]
    # Formatted even while held, so a Director's lift hands the upload a series title.
    assert result["title"] == "Kael defends every frame | Inside The Nexus Ep. 1"


def test_the_series_name_is_no_word_of_the_episodes_own(engine, films):
    """Every episode's title carries "Inside The Nexus"; the word check reads the hook, so an
    episode that says "Nexus" does not let another film's title through on it."""
    with Session(engine) as session, session.begin():
        row = session.get(StoryEpisode, films["episode"]["id"])
        row.continuity_json = {**row.continuity_json, "summary": "Inside the Nexus, a long cut."}
    with Session(engine) as session:
        reasons = publication_metadata_refusals(
            session,
            films["episode_asset"],
            films["channels"]["OFFICE_SERIAL"],
            series_title(STAND_IN["title"], 1),
            STAND_IN["tags"],
        )
    assert any("niciun cuvânt comun" in reason for reason in reasons), reasons


def test_the_copy_check_reads_the_hook_under_the_series_name(engine, films):
    with Session(engine) as session, session.begin():
        session.add(
            PublicationRecord(
                id=str(uuid4()),
                channel_id=films["channels"]["MAIN_FACTUAL"],
                media_asset_id=films["factual_asset"],
                title=HOOK["title"],
                description="",
                tags_json=list(HOOK["tags"]),
                privacy_status="private",
                status="PUBLISHED_SIMULATED",
                idempotency_key=str(uuid4()),
                created_at=utc_now(),
            )
        )
    from app.publishing.services import PublishingGateError

    with pytest.raises(PublishingGateError) as refused:
        create_publication_intent(
            engine,
            films["channels"]["OFFICE_SERIAL"],
            films["episode_asset"],
            series_title(HOOK["title"], 1),
            "",
            list(HOOK["tags"]),
            "private",
            None,
            str(uuid4()),
        )
    assert any("cuvânt cu cuvânt" in reason for reason in refused.value.reasons)


def test_the_second_episode_names_the_first(engine, staffed, monkeypatch, films):
    """A returning viewer is told what came before (07_STORY_ENGINE.md, 'episode metadata
    linking prior related episode'); the first episode here is the fixture's."""
    second = an_episode(
        engine,
        monkeypatch,
        when=datetime.now(UTC) + timedelta(days=1),
        title="The Second Cut",
        logline="Sarah finally asks for a longer cut, and Kael has none left.",
    )
    decide_episode(engine, second["id"], True, "")
    asset = _rendered(engine, storyboard_from_episode(engine, second["id"], str(uuid4())))
    model = Publisher(for_episode={**HOOK, "title": "No frames left"}, for_factual=STAND_IN)
    provider = ProviderRegistry()
    provider.register(films["provider_id"], model)

    result = prepare_publication(
        engine, provider, asset, films["channels"]["OFFICE_SERIAL"], str(uuid4())
    )

    facts = facts_of(model.prompts[-1])
    assert facts["episode_number"] == 2
    assert facts["previous_episode"] == {"episode_number": 1, "title": EP_TITLE}
    assert result["title"] == "No frames left | Inside The Nexus Ep. 2"
    assert result["description"].endswith(f"Previously on {SERIES}: Ep. 1, “{EP_TITLE}”.")


def test_an_episode_written_before_the_logline_is_described_from_its_summary(engine, films):
    """Old episodes stay readable: no logline, the summary's first sentence opens it."""
    with Session(engine) as session, session.begin():
        row = session.get(StoryEpisode, films["episode"]["id"])
        continuity = dict(row.continuity_json)
        continuity.pop("logline")
        continuity["template_version"] = "episode-v3"
        row.continuity_json = continuity
    model = Publisher(for_episode=HOOK, for_factual=STAND_IN)

    result = prepare(engine, films, model)

    assert facts_of(model.prompts[0])["logline"] == SUMMARY.split(". ")[0] + "."
    assert result["description"].startswith(SUMMARY.split(". ")[0] + ".")


def test_the_factual_film_has_no_series_and_no_storyboard_label(engine, films):
    model = Publisher(for_episode=HOOK, for_factual=STAND_IN)

    result = prepare(engine, films, model, "factual")

    (prompt,) = model.prompts
    facts = facts_of(prompt)
    assert facts["script_title"] == "Apa de pe GJ 486 b"
    assert "series" not in facts and "Storyboard:" not in prompt
    assert SERIES not in prompt
    assert result["title"] == STAND_IN["title"] and result["tags"] == STAND_IN["tags"]


def test_hook_of_reads_the_hook_back():
    assert hook_of("Storyboard: The Cut Runs Long") == "The Cut Runs Long"
    assert hook_of("A | Inside The Nexus Ep. 12") == "A"
    title = series_title("word " * 40, 7)
    assert len(title) <= 100 and title.endswith(" | Inside The Nexus Ep. 7")
