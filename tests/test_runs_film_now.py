"""A day's run says where its film stands now (2026-10-11).

The 05:00 run left the NASA film waiting; the studio finished it and put it up at 13:31, and
«Filmul zilei» still read the run's own «așteaptă decizia ta pe foaia de filmare». The Owner:
«Dacă este finalizat și urcat filmul, de ce îmi apare aici?». Each listed run carries its
films as they stand now (`films_now`).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from app.media.models import VideoRenderJob
from app.publishing.models import PublicationRecord
from app.runbook.models import DailyRun
from app.runbook.services import list_runs
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_daily_run_stages import _seeded_channels
from test_phase6_publishing import _create_verified_asset_bundle


def test_a_run_carries_its_films_as_they_stand_now(engine, tmp_path: Path):
    asset_id = _create_verified_asset_bundle(engine, tmp_path)["asset_id"]
    channel = _seeded_channels(engine)["MAIN_FACTUAL"]
    with Session(engine) as session:
        storyboard_id = session.scalars(
            select(VideoRenderJob.storyboard_id).where(VideoRenderJob.output_asset_id == asset_id)
        ).one()
    with Session(engine) as session, session.begin():
        session.add(
            DailyRun(
                id=str(uuid4()),
                business_date="2026-10-11",
                preflight_status="READY",
                preflight_json={},
                status="COMPLETED",
                started_at=utc_now(),
                finished_at=utc_now(),
                stages_total=1,
                stages_completed=1,
                stages_json=[
                    {
                        "stage": "media",
                        "status": "COMPLETED",
                        "artefacts": {
                            "films": [{"storyboard_id": storyboard_id, "status": "WAITING"}]
                        },
                    }
                ],
            )
        )
    (run,) = list_runs(engine)
    assert run["films_now"][storyboard_id]["publication"] is None

    with Session(engine) as session, session.begin():
        session.add(
            PublicationRecord(
                id=str(uuid4()),
                channel_id=channel["id"],
                media_asset_id=asset_id,
                title="How NASA Keeps Webb Alive With Frozen Fuel",
                description="d",
                tags_json=[],
                privacy_status="private",
                status="PUBLISHED",
                idempotency_key=str(uuid4()),
                remote_video_id="0mxS0dZF4uQ",
                remote_url="https://youtube.com/shorts/0mxS0dZF4uQ",
                remote_privacy_status="private",
                created_at=utc_now(),
                published_at=utc_now(),
            )
        )
    (run,) = list_runs(engine)
    now = run["films_now"][storyboard_id]
    assert now["publication"]["status"] == "PUBLISHED"
    assert now["publication"]["privacy"] == "private"
    assert now["publication"]["channel"] == channel["channel_name"]
