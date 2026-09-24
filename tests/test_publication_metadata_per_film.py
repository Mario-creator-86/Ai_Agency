"""Each upload is described from its own film, and an episode never goes out under another's.

What the rehearsal of 2026-09-18 measured: the factual film (to MAIN_FACTUAL) and the serial
episode (to OFFICE_SERIAL) both went up titled 'Infrared light and what it shows', tagged
space/astronomy. Read from the code, the question was whether the studio built the serial's
metadata from the wrong film, or asked correctly and the stand-in model answered every
Publisher prompt with the same fixed JSON. The first test settles it: with a model that
answers the two requests differently, each film keeps its own title and tags, and each
prompt carries only its own film. So it was the stand-in.

A real model can make the stand-in's mistake, and a wrong title on YouTube is public. The
rest hold the computed check added for that: an episode whose title and tags are word for
word another channel's film of the last day, or whose title shares no word with its own
episode, is held by the Publisher and refused at the upload, with the reason in Romanian.
The factual film is not touched by either.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from app.agents.models import Agent, ModelRecord, Role
from app.agents.reviews import approved_metadata, prepare_publication
from app.agents.services import seed_initial_workforce
from app.media.models import MediaAsset, Storyboard, VideoRenderJob
from app.media.serial_storyboard import storyboard_from_episode
from app.media.services import seed_default_character_bibles
from app.models import OwnerPolicy
from app.providers.base import GenerateResult, HealthResult
from app.providers.registry import ProviderRegistry
from app.publishing.models import ChannelRecord, PublicationRecord
from app.publishing.services import (
    PublishingGateError,
    create_publication_intent,
    publication_metadata_refusals,
    seed_default_channels,
)
from app.services import utc_now
from app.story.services import decide_episode, write_episode
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_serial_pipeline import (
    a_day,
    a_factual_storyboard,
    beats_for,
    episode_answer,
    fake_showrunner,
    roster_names,
)
from test_serial_pipeline import registry as story_registry

EPISODE_TITLE = "O zi la studio"
FACTUAL_TITLE = "Apa de pe GJ 486 b"

#: What the stand-in answered every Publisher prompt with, on both films.
STAND_IN = {
    "verdict": "READY",
    "title": "Infrared light and what it shows",
    "description": "What a telescope sees when it looks in infrared.",
    "tags": ["space", "astronomy"],
    "hold_reasons": [],
}
FACTUAL_METADATA = {
    "verdict": "READY",
    "title": "Water on a rocky planet",
    "description": "What Webb measured on GJ 486 b.",
    "tags": ["space", "planets"],
    "hold_reasons": [],
}
EPISODE_METADATA = {
    "verdict": "READY",
    "title": "Sarah asks for the number before good morning",
    "description": "A morning at the studio: Sarah wants the number, Aris brings evidence.",
    "tags": ["office serial", "studio life"],
    "hold_reasons": [],
}


class PublisherModel:
    """Answers the Publisher by which film the prompt carries, and remembers every prompt."""

    def __init__(self, for_episode: dict, for_factual: dict) -> None:
        self.for_episode, self.for_factual = for_episode, for_factual
        self.prompts: list[str] = []

    async def health_check(self):
        return HealthResult("HEALTHY")

    async def list_models(self):
        return []

    async def generate(self, model, prompt, **kwargs):
        self.prompts.append(prompt)
        answer = self.for_episode if EPISODE_TITLE in prompt else self.for_factual
        return GenerateResult(json.dumps(answer), 10, 40, None)


@pytest.fixture
def studio(engine, monkeypatch):
    seed_initial_workforce(engine)
    seed_default_character_bibles(engine)
    seed_default_channels(engine)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
        for model in session.scalars(select(ModelRecord)):
            model.is_available = True
    with Session(engine) as session:
        provider_id = session.scalars(
            select(Agent.provider_id).join(Role, Agent.role_id == Role.id)
        ).first()
        channels = {c.channel_type: c.id for c in session.scalars(select(ChannelRecord))}

    # The day's episode, approved, through the serial's own path to its storyboard.
    log, ids = a_day(engine)
    names = roster_names(engine, log["id"])
    fake_showrunner(monkeypatch, episode_answer(beats_for(ids, names), title=EPISODE_TITLE))
    episode = write_episode(engine, story_registry(), log["id"], str(uuid4()))["episode"]
    decide_episode(engine, episode["id"], True, "")
    serial_board = storyboard_from_episode(engine, episode["id"], str(uuid4()))
    factual_board = a_factual_storyboard(engine)["id"]
    return {
        "provider_id": provider_id,
        "channels": channels,
        "episode_asset": _rendered(engine, serial_board),
        "factual_asset": _rendered(engine, factual_board),
    }


def _rendered(engine, storyboard_id: str) -> str:
    """A rendered file behind the storyboard: what `film_identity` walks back from."""
    asset_id = str(uuid4())
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"storage/{asset_id}.mp4",
                file_size_bytes=10,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=40.0,
                provider_name="RUNWAY_IMAGES",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="0" * 64,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=storyboard_id,
                status="COMPLETED",
                output_asset_id=asset_id,
                started_at=now,
            )
        )
    return asset_id


def _registry(studio, model: PublisherModel) -> ProviderRegistry:
    registry = ProviderRegistry()
    registry.register(studio["provider_id"], model)
    return registry


def _prepare(engine, studio, model, which: str) -> dict:
    asset = studio[f"{which}_asset"]
    channel = studio["channels"]["OFFICE_SERIAL" if which == "episode" else "MAIN_FACTUAL"]
    return prepare_publication(engine, _registry(studio, model), asset, channel, str(uuid4()))


# ---------------------------------------------------------------------------
# What the rehearsal saw: the stand-in, not the studio
# ---------------------------------------------------------------------------


def test_each_film_is_described_from_its_own_script(engine, studio):
    model = PublisherModel(for_episode=EPISODE_METADATA, for_factual=FACTUAL_METADATA)

    factual = _prepare(engine, studio, model, "factual")
    episode = _prepare(engine, studio, model, "episode")

    assert factual["verdict"] == "READY" and factual["title"] == FACTUAL_METADATA["title"]
    assert episode["verdict"] == "READY" and episode["title"] == EPISODE_METADATA["title"]
    # Each prompt carried its own film and not the other one.
    factual_prompt, episode_prompt = model.prompts
    assert FACTUAL_TITLE in factual_prompt and EPISODE_TITLE not in factual_prompt
    assert EPISODE_TITLE in episode_prompt and FACTUAL_TITLE not in episode_prompt
    # And what the upload reads back is each film's own.
    with Session(engine) as session:
        assert approved_metadata(session, studio["factual_asset"]) == {
            "title": FACTUAL_METADATA["title"],
            "description": FACTUAL_METADATA["description"],
            "tags": FACTUAL_METADATA["tags"],
        }
        assert approved_metadata(session, studio["episode_asset"]) == {
            "title": EPISODE_METADATA["title"],
            "description": EPISODE_METADATA["description"],
            "tags": EPISODE_METADATA["tags"],
        }


# ---------------------------------------------------------------------------
# The check: what a real model could get wrong the same way
# ---------------------------------------------------------------------------


def test_the_stand_ins_answer_on_the_episode_is_held_and_the_factual_film_is_not(engine, studio):
    model = PublisherModel(for_episode=STAND_IN, for_factual=STAND_IN)

    factual = _prepare(engine, studio, model, "factual")
    episode = _prepare(engine, studio, model, "episode")

    assert factual["verdict"] == "READY" and factual["hold_reasons"] == []
    assert episode["verdict"] == "HOLD"
    reasons = " ".join(episode["hold_reasons"])
    assert "cuvânt cu cuvânt" in reasons and FACTUAL_METADATA["title"] not in reasons
    assert "niciun cuvânt comun" in reasons
    with Session(engine) as session:
        # A HOLD is not metadata the upload may take.
        assert approved_metadata(session, studio["episode_asset"]) is None
        assert approved_metadata(session, studio["factual_asset"])["title"] == STAND_IN["title"]


def test_an_episode_titled_word_for_word_like_the_other_channels_film_is_held(engine, studio):
    """The title belongs to the episode, but it is the factual film's too: held for the copy."""
    model = PublisherModel(for_episode=EPISODE_METADATA, for_factual=EPISODE_METADATA)

    assert _prepare(engine, studio, model, "factual")["verdict"] == "READY"
    episode = _prepare(engine, studio, model, "episode")

    assert episode["verdict"] == "HOLD"
    (reason,) = episode["hold_reasons"]
    assert "cuvânt cu cuvânt" in reason and "Main Channel A" in reason


def test_the_same_title_with_other_tags_is_not_a_copy(engine, studio):
    model = PublisherModel(
        for_episode=EPISODE_METADATA,
        for_factual={**EPISODE_METADATA, "tags": ["space", "planets"]},
    )

    _prepare(engine, studio, model, "factual")
    assert _prepare(engine, studio, model, "episode")["verdict"] == "READY"


def test_an_episode_whose_title_shares_no_word_with_its_story_is_held(engine, studio):
    model = PublisherModel(for_episode=STAND_IN, for_factual=FACTUAL_METADATA)

    episode = _prepare(engine, studio, model, "episode")

    assert episode["verdict"] == "HOLD"
    (reason,) = episode["hold_reasons"]
    assert "niciun cuvânt comun" in reason and STAND_IN["title"] in reason


def test_an_episode_titled_from_its_own_words_goes_whatever_the_order(engine, studio):
    model = PublisherModel(for_episode=EPISODE_METADATA, for_factual=FACTUAL_METADATA)

    assert _prepare(engine, studio, model, "episode")["verdict"] == "READY"
    assert _prepare(engine, studio, model, "factual")["verdict"] == "READY"


def test_the_factual_film_is_never_measured_by_the_episodes_check(engine, studio):
    """Prepared after the episode, with the episode's own metadata: still READY."""
    model = PublisherModel(for_episode=EPISODE_METADATA, for_factual=EPISODE_METADATA)

    assert _prepare(engine, studio, model, "episode")["verdict"] == "READY"
    factual = _prepare(engine, studio, model, "factual")
    assert factual["verdict"] == "READY" and factual["hold_reasons"] == []
    with Session(engine) as session:
        assert (
            publication_metadata_refusals(
                session,
                studio["factual_asset"],
                studio["channels"]["MAIN_FACTUAL"],
                STAND_IN["title"],
                STAND_IN["tags"],
            )
            == []
        )


def test_the_upload_refuses_a_copied_title_whoever_lifted_the_hold(engine, studio):
    """The gate on the upload's road reads the same check, so a HOLD the Director resolved,
    or a caller that never asked the Publisher, cannot put the copy on the channel."""
    with Session(engine) as session, session.begin():
        session.add(
            PublicationRecord(
                id=str(uuid4()),
                channel_id=studio["channels"]["MAIN_FACTUAL"],
                media_asset_id=studio["factual_asset"],
                title=EPISODE_METADATA["title"],
                description="",
                tags_json=list(EPISODE_METADATA["tags"]),
                privacy_status="private",
                status="PUBLISHED_SIMULATED",
                idempotency_key=str(uuid4()),
                created_at=utc_now(),
            )
        )

    with pytest.raises(PublishingGateError) as refused:
        create_publication_intent(
            engine,
            studio["channels"]["OFFICE_SERIAL"],
            studio["episode_asset"],
            EPISODE_METADATA["title"],
            "",
            [tag.upper() for tag in EPISODE_METADATA["tags"]],
            "private",
            None,
            str(uuid4()),
        )
    assert any("cuvânt cu cuvânt" in reason for reason in refused.value.reasons)
    with Session(engine) as session:
        record = session.scalars(
            select(PublicationRecord).where(
                PublicationRecord.media_asset_id == studio["episode_asset"]
            )
        ).one()
        assert record.status == "BLOCKED_GATE" and "cuvânt cu cuvânt" in record.error_detail


def test_the_upload_names_no_metadata_reason_for_an_episodes_own_title(engine, studio):
    with Session(engine) as session:
        assert (
            publication_metadata_refusals(
                session,
                studio["episode_asset"],
                studio["channels"]["OFFICE_SERIAL"],
                EPISODE_METADATA["title"],
                EPISODE_METADATA["tags"],
            )
            == []
        )


def test_an_episode_whose_words_cannot_be_read_is_refused_not_passed(engine, studio):
    """A check that cannot run says so: an episode's script emptied of every word."""
    from app.factual.models import ScriptDraft
    from app.story.models import StoryEpisode

    with Session(engine) as session, session.begin():
        job = session.scalars(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == studio["episode_asset"])
        ).one()
        board = session.get(Storyboard, job.storyboard_id)
        script = session.get(ScriptDraft, board.script_draft_id)
        episode = session.get(StoryEpisode, script.story_json["episode_id"])
        script.title, script.voiceover_full_text, script.scenes_json = "", "", []
        episode.title, episode.beats_json, episode.continuity_json = "", [], {}
    with Session(engine) as session:
        (reason,) = publication_metadata_refusals(
            session,
            studio["episode_asset"],
            studio["channels"]["OFFICE_SERIAL"],
            EPISODE_METADATA["title"],
            EPISODE_METADATA["tags"],
        )
    assert "nu poate fi citit" in reason


# ---------------------------------------------------------------------------
# A HOLD the Director lifted is not a title the upload may take
# ---------------------------------------------------------------------------


def _publishable(engine, tmp_path, asset_id: str) -> None:
    """Give the rendered episode what the five gates read: a file on disk and a QC pass."""
    from hashlib import sha256

    from app.media.models import QualityControlReport

    video = tmp_path / f"{asset_id}.mp4"
    video.write_bytes(b"an episode, rendered")
    with Session(engine) as session, session.begin():
        asset = session.get(MediaAsset, asset_id)
        asset.uri_or_path = str(video)
        asset.file_size_bytes = video.stat().st_size
        asset.provenance_hash = sha256(video.read_bytes()).hexdigest()
        asset.license_status = "OWNED_INTERNAL"
        session.add(
            QualityControlReport(
                id=str(uuid4()),
                media_asset_id=asset_id,
                status="PASSED",
                score=0.96,
                checks_json={"technical": {"passed": True}},
                failure_reasons_json=[],
                verified_at=utc_now(),
            )
        )


@pytest.fixture
def serial_slot(engine, studio, tmp_path, monkeypatch):
    """The episode, publishable, with Channel B bound and the Director's watch approved."""
    from types import SimpleNamespace

    from test_daily_run_stages import _bound, _connected, _RecordingPublisher

    _publishable(engine, tmp_path, studio["episode_asset"])
    _bound(engine, studio["channels"]["OFFICE_SERIAL"], _connected(engine, "Serial account"))
    publisher = _RecordingPublisher()
    monkeypatch.setattr("app.runbook.stages.selected_youtube", lambda *a, **k: publisher)
    monkeypatch.setattr(
        "app.runbook.stages.latest_editorial",
        lambda session, asset_id: SimpleNamespace(verdict="APPROVE", reasons_json=[]),
    )
    return publisher


def _lift_the_hold(engine, asset_id: str) -> None:
    """What the Director does with a HOLD in her inbox: resolve it."""
    from app.agents.messages import resolve_message
    from app.agents.reviews import publication_hold

    with Session(engine) as session, session.begin():
        hold = publication_hold(session, asset_id)
        assert hold is not None
        resolve_message(session, hold["message_id"], resolution="Lifted.", resolved_by="director")


def _episode_publications(engine, asset_id: str) -> list[PublicationRecord]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(PublicationRecord).where(PublicationRecord.media_asset_id == asset_id)
            )
        )


def test_a_lifted_hold_on_a_refused_title_is_prepared_again_not_blocked(
    engine, studio, serial_slot
):
    """Measured on the code of 2026-09-19: the Director resolved the Publisher's HOLD, the
    resolved HOLD's title was taken for the upload, the upload's own check refused it and
    left a BLOCKED_GATE row, and that row kept the film out of every later run. A title the
    check refuses is not metadata: the Publisher is asked again, and her new answer goes."""
    from app.runbook import stages

    asset = studio["episode_asset"]
    held = stages._publish(engine, None, _registry(studio, PublisherModel(STAND_IN, STAND_IN)))
    assert held["status"] == "COMPLETED" and serial_slot.uploads == [], held
    _lift_the_hold(engine, asset)

    model = PublisherModel(for_episode=EPISODE_METADATA, for_factual=FACTUAL_METADATA)
    outcome = stages._publish(engine, None, _registry(studio, model))

    assert outcome["status"] == "COMPLETED", outcome
    assert [u["title"] for u in serial_slot.uploads] == [EPISODE_METADATA["title"]]
    assert len(model.prompts) == 1  # asked once more, not every time
    assert [r.status for r in _episode_publications(engine, asset)] == ["PUBLISHED_SIMULATED"]


def test_a_film_the_gate_blocked_once_is_offered_again(engine, studio, serial_slot):
    """A BLOCKED_GATE row is a refusal on record, not a film on the channel: the queue used
    to count every publication row as 'published', so one refusal kept the episode out for
    good. The record stays for the audit; the film comes forward and goes."""
    from app.runbook import stages

    asset = studio["episode_asset"]
    with Session(engine) as session, session.begin():
        session.add(
            PublicationRecord(
                id=str(uuid4()),
                channel_id=studio["channels"]["OFFICE_SERIAL"],
                media_asset_id=asset,
                title=STAND_IN["title"],
                description="",
                tags_json=list(STAND_IN["tags"]),
                privacy_status="private",
                status="BLOCKED_GATE",
                idempotency_key=str(uuid4()),
                error_detail="Titlul nu are niciun cuvânt comun cu episodul.",
                created_at=utc_now(),
            )
        )
    model = PublisherModel(for_episode=EPISODE_METADATA, for_factual=FACTUAL_METADATA)

    outcome = stages._publish(engine, None, _registry(studio, model))

    assert outcome["status"] == "COMPLETED", outcome
    assert [u["title"] for u in serial_slot.uploads] == [EPISODE_METADATA["title"]]
    assert sorted(r.status for r in _episode_publications(engine, asset)) == [
        "BLOCKED_GATE",
        "PUBLISHED_SIMULATED",
    ]
