"""The media list says a film was uploaded (2026-10-11).

«The Particle That Shouldn't Exist (But Does)» went up private on Main Channel A the evening
before, and its card still read «randat · QC: a trecut». The Owner: «Este publicat! Ar trebui
să apară asta!». Each summary row now carries its film's newest upload.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.media.models import VideoRenderJob
from app.media.services import list_storyboards
from app.publishing.models import PublicationRecord
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_daily_run_stages import _seeded_channels
from test_phase6_publishing import _create_verified_asset_bundle


def test_a_rendered_film_carries_its_newest_upload_and_others_none(engine, tmp_path: Path):
    asset_id = _create_verified_asset_bundle(engine, tmp_path)["asset_id"]
    channel = _seeded_channels(engine)["MAIN_FACTUAL"]
    with Session(engine) as session:
        storyboard_id = session.scalars(
            select(VideoRenderJob.storyboard_id).where(VideoRenderJob.output_asset_id == asset_id)
        ).one()
    row = next(r for r in list_storyboards(engine)["storyboards"] if r["id"] == storyboard_id)
    assert row["asset_id"] == asset_id and row["publication"] is None

    with Session(engine) as session, session.begin():
        session.add(
            PublicationRecord(
                id=str(uuid4()),
                channel_id=channel["id"],
                media_asset_id=asset_id,
                title="The Particle That Shouldn't Exist (But Does)",
                description="d",
                tags_json=[],
                privacy_status="private",
                status="PUBLISHED",
                idempotency_key=str(uuid4()),
                remote_video_id="fixture0001",
                remote_url="https://youtube.com/shorts/fixture0001",
                remote_privacy_status="private",
                created_at=utc_now(),
                published_at=utc_now(),
            )
        )
    row = next(r for r in list_storyboards(engine)["storyboards"] if r["id"] == storyboard_id)
    assert row["publication"] == {
        "status": "PUBLISHED",
        "privacy": "private",
        "url": "https://youtube.com/shorts/fixture0001",
        "channel": channel["channel_name"],
        "published_at": row["publication"]["published_at"],
    }
