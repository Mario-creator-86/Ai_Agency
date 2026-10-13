"""A subject the studio already made is not proposed again under another title (2026-10-12).

Live: «The Particle That Shouldn't Exist (But Does)» was filmed on 2026-10-09 and published on
2026-10-10 as «The Higgs Boson: The Particle That Explains Why Mass Exists»; on 2026-10-12 the
researcher proposed «The Particle That Shouldn't Exist (And Briefly Didn't)», the Director chose
it (highest composite score) and the studio filmed a second Higgs short. The duplicate check
compared the candidate's title with the ideas' titles alone (Jaccard 0.5 < 0.6), and the first
film's idea had a third title. The Owner: «Facem două shorturi la fel?». Now the check reads the
subject (title keys, title + topic keys) against every idea, script, storyboard and publication
the studio has, and the researcher's prompt lists what was made.
"""

from __future__ import annotations

from uuid import uuid4

from app.factual.models import ScriptDraft, TopicIdea
from app.media.models import MediaAsset, Storyboard
from app.publishing.models import ChannelRecord, PublicationRecord
from app.research.agent import _keys, _too_similar, existing_subjects
from app.services import utc_now
from sqlalchemy.orm import Session

PARTICLE_MADE = "The Particle That Shouldn't Exist (But Does)"
PARTICLE_AGAIN = "The Particle That Shouldn't Exist (And Briefly Didn't)"
HIGGS_TOPIC = "The fall and rise of the Higgs mechanism after the 2012 discovery"


def test_the_same_subject_under_another_title_is_a_duplicate():
    assert _too_similar(PARTICLE_AGAIN, HIGGS_TOPIC, [(PARTICLE_MADE, "")]) == PARTICLE_MADE
    assert (
        _too_similar(
            "How CERN's ATLAS Measured a Higgs Boson in Real Time",
            "ATLAS's first observation of a Higgs boson decay",
            [("How CERN Measures the Higgs Boson's Lifetime", "Higgs width constraints")],
        )
        == "How CERN Measures the Higgs Boson's Lifetime"
    )
    # Three subject words across title and topic are the same subject too.
    assert (
        _too_similar(
            "Why Your Phone Knows Where It Is",
            "GPS satellites, atomic clocks and relativity corrections",
            [
                (
                    "The Clocks in Orbit",
                    "GPS satellites carry atomic clocks corrected for relativity",
                )
            ],
        )
        == "The Clocks in Orbit"
    )


def test_a_different_subject_with_a_shared_institution_or_word_is_not():
    assert (
        _too_similar(
            "How NASA Tracks Asteroids That Could Hit Earth",
            "NASA's asteroid detection and tracking systems",
            [
                ("How NASA Keeps a Space Telescope Alive With Frozen Fuel", "Webb's fuel budget"),
                (
                    "Why Ernest Lawrence's First Cyclotron Barely Fit on a Desk",
                    "the first cyclotron",
                ),
                (PARTICLE_MADE, ""),
            ],
        )
        is None
    )
    assert _keys("Storyboard: The Particle That Shouldn't Exist") == {
        "particle",
        "shouldn",
        "exist",
    }
    assert "storyboard" not in _keys("Storyboard: anything")


def test_what_the_studio_made_counts_under_any_title(engine):
    now = utc_now()
    with Session(engine) as session, session.begin():
        topic = TopicIdea(
            id=str(uuid4()),
            title="How CERN's ATLAS Measured a Higgs Boson in Real Time",
            topic="ATLAS experiment's first observation of a Higgs boson decay",
            angle="a",
            target_audience="g",
            novelty_score=0.9,
            status="SELECTED",
            created_at=now,
        )
        session.add(topic)
        session.flush()
        script = ScriptDraft(
            id=str(uuid4()),
            topic_id=topic.id,
            title=PARTICLE_MADE,
            voiceover_full_text="text",
            claim_ids_json=[],
            status="APPROVED",
            created_at=now,
        )
        session.add(script)
        session.flush()
        session.add(
            Storyboard(
                id=str(uuid4()),
                script_draft_id=script.id,
                title=f"Storyboard: {PARTICLE_MADE}",
                status="RENDERED",
                total_scenes=5,
                visual_bible_json={},
                created_at=now,
            )
        )
    with Session(engine) as session:
        records = existing_subjects(session)
    titles = [title for title, _topic in records]
    assert PARTICLE_MADE in titles and f"Storyboard: {PARTICLE_MADE}" not in titles
    assert titles.count(PARTICLE_MADE) == 2  # the script and the storyboard, both bare
    assert _too_similar(PARTICLE_AGAIN, HIGGS_TOPIC, records) == PARTICLE_MADE
    # The publication's own title counts too.
    with Session(engine) as session, session.begin():
        channel = ChannelRecord(id=str(uuid4()), channel_name="Nexus Curiosity", created_at=now)
        asset = MediaAsset(
            id=str(uuid4()),
            asset_type="RENDERED_VIDEO",
            uri_or_path="storage/higgs.mp4",
            file_size_bytes=10,
            mime_type="video/mp4",
            width=1080,
            height=1920,
            duration_seconds=30.0,
            provider_name="SCENE_TAKES",
            license_status="PROPRIETARY_STUDIO",
            provenance_hash="1" * 64,
            created_at=now,
        )
        session.add_all([channel, asset])
        session.flush()
        session.add(
            PublicationRecord(
                id=str(uuid4()),
                channel_id=channel.id,
                media_asset_id=asset.id,
                title="The Higgs Boson: The Particle That Explains Why Mass Exists",
                description="",
                idempotency_key=str(uuid4()),
                status="PUBLISHED",
                created_at=now,
            )
        )
    with Session(engine) as session:
        assert (
            _too_similar(
                "Why the Higgs Boson Gives Particles Mass",
                "the Higgs field and mass",
                existing_subjects(session),
            )
            is not None
        )
