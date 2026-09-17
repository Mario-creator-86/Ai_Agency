"""The watchdog: what notices when a day was interrupted.

Measured on a copy of the live database: two `video_render_job` rows had been RENDERING since
2026-09-12 with `finished_at` NULL, and `reconcile_publication` had no caller outside the tests,
so a publication in REMOTE_UNKNOWN stayed unknown for as long as the studio ran. These tests
drive one watchdog pass by hand and hold it to what makes it safe:

  * a render with no progress past the threshold is failed, with the reason and an event;
  * a render still inside the threshold is left alone;
  * an uncertain publication goes through the existing reconciliation, never a second one;
  * a retry goes through the existing retry path, which asks the platform before uploading;
  * a platform that cannot be asked is asked a bounded number of times, then the row is
    handed to the Owner instead of being asked forever;
  * a lapsed task lease is reported and left to the queue, which re-claims it itself;
  * while the Owner's autonomy stop is set, nothing changes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

from app.media.models import Storyboard, VideoRenderJob
from app.models import DomainEvent, OwnerPolicy
from app.providers.deterministic_pub import DeterministicPublishingAdapter
from app.providers.publishing_base import RemoteStateUnavailable
from app.publishing.models import PublicationRecord
from app.publishing.services import (
    create_publication_intent,
    list_channels,
    seed_default_channels,
)
from app.workflows.services import claim_task, enqueue_task
from app.workflows.watchdog import (
    WATCHDOG,
    WATCHDOG_JOB_NAME,
    run_watchdog,
)
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_phase6_publishing import _create_verified_asset_bundle


def _autonomy(engine, stopped: bool) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = stopped


def _render_job(engine, tmp_path, *, started_ago: timedelta) -> str:
    """A RENDERING row the way the assembler leaves one when the process dies mid-render."""
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    job_id = str(uuid4())
    with Session(engine) as session, session.begin():
        storyboard = session.scalars(
            select(Storyboard).where(Storyboard.script_draft_id == bundle["script_id"])
        ).one()
        session.add(
            VideoRenderJob(
                id=job_id,
                storyboard_id=storyboard.id,
                output_asset_id=None,
                status="RENDERING",
                render_engine="FFMPEG",
                command_args_json=[],
                execution_log="Assembly started...",
                started_at=(datetime.now(UTC) - started_ago).isoformat(),
                finished_at=None,
            )
        )
    return job_id


def _publication(engine, tmp_path, *, status: str, remote_video_id: str | None = None) -> str:
    bundle = _create_verified_asset_bundle(engine, tmp_path)
    seed_default_channels(engine)
    channel_id = list_channels(engine)[0]["id"]
    publication = create_publication_intent(
        engine,
        channel_id=channel_id,
        media_asset_id=bundle["asset_id"],
        title="A film whose upload was interrupted",
        description="The watchdog must ask the platform, not guess.",
        tags=["#test"],
        privacy_status="private",
        idempotency_key=str(uuid4()),
        correlation_id=str(uuid4()),
    )
    with Session(engine) as session, session.begin():
        record = session.get(PublicationRecord, publication["id"])
        record.status = status
        record.remote_video_id = remote_video_id
    return publication["id"]


def _events(engine, aggregate_id: str, event_type: str) -> list[DomainEvent]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(DomainEvent).where(
                    DomainEvent.aggregate_id == aggregate_id,
                    DomainEvent.event_type == event_type,
                )
            )
        )


class SilentPlatform(DeterministicPublishingAdapter):
    """A platform that cannot be reached, with a counter proving nothing was uploaded."""

    def __init__(self) -> None:
        super().__init__()
        self.uploads = 0
        self.questions = 0

    async def get_video_status(self, remote_video_id: str) -> Any:
        self.questions += 1
        raise RemoteStateUnavailable("the channel could not be reached")

    async def reconcile_upload(self, idempotency_key: str, expected_title: str) -> Any:
        self.questions += 1
        raise RemoteStateUnavailable("the channel's uploads could not be searched")

    async def upload_video(self, file_path, **kwargs: Any) -> Any:
        self.uploads += 1
        return await super().upload_video(file_path, **kwargs)


# ------------------------------------------------------------------------ the contract --


def test_the_job_is_named_for_the_worker_to_register():
    assert WATCHDOG == "WATCHDOG"
    assert WATCHDOG_JOB_NAME == "watchdog"


# ------------------------------------------------------------------------ stuck renders --


def test_a_render_with_no_progress_past_the_threshold_is_failed_with_the_reason(
    engine, settings, tmp_path
):
    _autonomy(engine, False)
    job_id = _render_job(engine, tmp_path, started_ago=timedelta(hours=4, minutes=10))

    result = run_watchdog(engine, settings, correlation_id=str(uuid4()))

    assert result["status"] == "COMPLETED"
    assert result["renders"]["failed"] == 1
    assert job_id in result["renders"]["failed_ids"]
    with Session(engine) as session:
        job = session.get(VideoRenderJob, job_id)
        assert job.status == "FAILED"
        assert job.finished_at is not None
        assert "Blocat: fără progres de 4 ore" in (job.execution_log or "")
    failed = _events(engine, job_id, "media.render_failed")
    assert len(failed) == 1
    assert failed[0].payload["reason"] == "Blocat: fără progres de 4 ore"
    assert failed[0].payload["watchdog"] is True


def test_a_render_still_inside_the_threshold_is_left_alone(engine, settings, tmp_path):
    _autonomy(engine, False)
    job_id = _render_job(engine, tmp_path, started_ago=timedelta(minutes=20))

    result = run_watchdog(engine, settings, correlation_id=str(uuid4()))

    assert result["renders"]["failed"] == 0
    assert result["renders"]["rendering"] == 1
    with Session(engine) as session:
        job = session.get(VideoRenderJob, job_id)
        assert job.status == "RENDERING"
        assert job.finished_at is None
    assert _events(engine, job_id, "media.render_failed") == []


def test_the_threshold_is_read_from_the_settings_when_they_have_one(engine, tmp_path):
    _autonomy(engine, False)
    job_id = _render_job(engine, tmp_path, started_ago=timedelta(minutes=20))
    # Ten minutes: a studio the Owner tuned tighter than the default three hours.
    settings = SimpleNamespace(render_stuck_after_seconds=600)

    run_watchdog(engine, settings, correlation_id=str(uuid4()))

    with Session(engine) as session:
        assert session.get(VideoRenderJob, job_id).status == "FAILED"


# ----------------------------------------------------------------------- publications --


def test_a_remote_unknown_publication_is_reconciled_through_the_existing_function(
    engine, settings, tmp_path
):
    _autonomy(engine, False)
    publication_id = _publication(engine, tmp_path, status="REMOTE_UNKNOWN", remote_video_id="v1")
    platform = DeterministicPublishingAdapter()
    # The platform holds the video: the upload had landed, only the answer was lost.
    platform._published_videos["v1"] = {"privacy_status": "private", "idempotency_key": "x"}

    result = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: platform
    )

    assert result["publications"]["reconciled_published"] == 1
    with Session(engine) as session:
        record = session.get(PublicationRecord, publication_id)
        assert record.status == "PUBLISHED_SIMULATED"
        assert record.published_at is not None
    # The existing function's own event, which is how one knows no second one was written.
    assert len(_events(engine, publication_id, "publishing.reconciled_published")) == 1


def test_a_retryable_publication_goes_through_the_retry_path_and_does_not_upload_twice(
    engine, settings, tmp_path
):
    _autonomy(engine, False)
    publication_id = _publication(engine, tmp_path, status="FAILED_RETRYABLE")
    with Session(engine) as session:
        key = session.get(PublicationRecord, publication_id).idempotency_key
    platform = DeterministicPublishingAdapter()
    # The first attempt had landed under this key; the retry must find it, not upload again.
    platform._published_videos["already"] = {"privacy_status": "private", "idempotency_key": key}

    result = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: platform
    )

    assert result["publications"]["retry_reconciled"] == 1
    with Session(engine) as session:
        record = session.get(PublicationRecord, publication_id)
        assert record.status == "PUBLISHED_SIMULATED"
        assert record.remote_video_id == "already"
    assert len(_events(engine, publication_id, "publishing.retry_reconciled")) == 1


def test_a_platform_that_cannot_be_asked_is_asked_a_bounded_number_of_times(engine, tmp_path):
    _autonomy(engine, False)
    publication_id = _publication(engine, tmp_path, status="REMOTE_UNKNOWN", remote_video_id="v2")
    platform = SilentPlatform()
    settings = SimpleNamespace(reconcile_max_attempts=2)

    first = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: platform
    )
    second = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: platform
    )
    third = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: platform
    )

    assert first["publications"]["still_unknown"] == 1
    assert second["publications"]["still_unknown"] == 1
    # Two attempts were allowed; the third pass hands the row over instead of asking again.
    assert third["publications"]["handed_to_owner"] == 1
    assert platform.questions == 2
    assert platform.uploads == 0
    with Session(engine) as session:
        record = session.get(PublicationRecord, publication_id)
        assert record.status == "NEEDS_RECONCILIATION"
        assert "2 încercări" in (record.error_detail or "")
    assert len(_events(engine, publication_id, "publishing.reconcile_exhausted")) == 1
    # A fourth pass finds nothing left to do: the row is the Owner's now.
    fourth = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: platform
    )
    assert fourth["publications"]["checked"] == 0
    assert platform.questions == 2


def test_an_unknown_publication_with_no_remote_id_is_handed_to_the_owner(
    engine, settings, tmp_path
):
    """YouTube's UNKNOWN result carries no video id (the stream was interrupted), and the
    existing reconciliation can only ask about an id. Rather than stay REMOTE_UNKNOWN forever,
    the row is named as one a person must look at."""
    _autonomy(engine, False)
    publication_id = _publication(engine, tmp_path, status="REMOTE_UNKNOWN", remote_video_id=None)
    platform = DeterministicPublishingAdapter()

    result = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: platform
    )

    assert result["publications"]["handed_to_owner"] == 1
    with Session(engine) as session:
        record = session.get(PublicationRecord, publication_id)
        assert record.status == "NEEDS_RECONCILIATION"
        assert record.error_detail


def test_a_channel_with_no_publisher_is_reported_and_its_publication_left_as_it_was(
    engine, settings, tmp_path
):
    _autonomy(engine, False)
    publication_id = _publication(engine, tmp_path, status="REMOTE_UNKNOWN", remote_video_id="v3")

    # The default resolver: no YouTube connection is bound to the seeded channel slot.
    result = run_watchdog(engine, settings, correlation_id=str(uuid4()))

    assert result["publications"]["no_publisher"] == 1
    assert result["publications"]["reasons"]
    with Session(engine) as session:
        assert session.get(PublicationRecord, publication_id).status == "REMOTE_UNKNOWN"


# ------------------------------------------------------------------------------ leases --


def test_a_lapsed_lease_is_reported_and_the_queue_reclaims_it_itself(engine, settings):
    _autonomy(engine, False)
    queued = enqueue_task(engine, task_type="ANY", payload={}, idempotency_key=str(uuid4()))
    claimed = claim_task(engine, "worker_that_died", lease_duration_seconds=1)
    assert claimed is not None and claimed["id"] == queued["id"]
    from app.workflows.models import TaskQueueItem

    with Session(engine) as session, session.begin():
        task = session.get(TaskQueueItem, queued["id"])
        task.lease_expires_at = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()

    result = run_watchdog(engine, settings, correlation_id=str(uuid4()))

    assert result["leases"]["expired"] == 1
    assert queued["id"] in result["leases"]["task_ids"]
    # The watchdog changed nothing: the lease token of the dead worker is still on the row...
    with Session(engine) as session:
        task = session.get(TaskQueueItem, queued["id"])
        assert task.status == "CLAIMED"
        assert task.lease_token == "worker_that_died"
    # ...and the queue's own claim takes it over, as it was designed to.
    reclaimed = claim_task(engine, "worker_after_restart", lease_duration_seconds=60)
    assert reclaimed is not None and reclaimed["id"] == queued["id"]
    assert reclaimed["lease_token"] == "worker_after_restart"


# -------------------------------------------------------------------------- the stop --


def test_nothing_happens_while_the_autonomy_stop_is_set(engine, settings, tmp_path):
    _autonomy(engine, False)
    job_id = _render_job(engine, tmp_path, started_ago=timedelta(hours=9))
    publication_id = _publication(engine, tmp_path, status="REMOTE_UNKNOWN", remote_video_id="v4")
    platform = DeterministicPublishingAdapter()
    platform._published_videos["v4"] = {"privacy_status": "private", "idempotency_key": "y"}
    _autonomy(engine, True)

    result = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: platform
    )

    assert result["status"] == "SKIPPED"
    assert "oprit" in result["reason"]
    with Session(engine) as session:
        assert session.get(VideoRenderJob, job_id).status == "RENDERING"
        assert session.get(PublicationRecord, publication_id).status == "REMOTE_UNKNOWN"
    assert _events(engine, job_id, "media.render_failed") == []
