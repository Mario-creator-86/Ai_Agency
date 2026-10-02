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


def test_an_unknown_publication_with_no_remote_id_that_cannot_be_asked_goes_to_the_owner(
    engine, tmp_path
):
    """YouTube's UNKNOWN result carries no video id (the stream was interrupted). Since
    2026-10-02 the channel's own uploads are asked by title (PUB-03); a platform that cannot
    answer is asked a bounded number of times, and then the row is the Owner's."""
    _autonomy(engine, False)
    publication_id = _publication(engine, tmp_path, status="REMOTE_UNKNOWN", remote_video_id=None)
    _aged(engine, publication_id, ago=timedelta(hours=1))
    platform = SilentPlatform()
    settings = SimpleNamespace(reconcile_max_attempts=1)

    first = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: platform
    )
    second = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: platform
    )

    assert first["publications"]["still_unknown"] == 1
    assert second["publications"]["handed_to_owner"] == 1
    assert platform.uploads == 0
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
        assert task.lease_token == claimed["lease_token"]
    # ...and the queue's own claim takes it over, as it was designed to.
    reclaimed = claim_task(engine, "worker_after_restart", lease_duration_seconds=60)
    assert reclaimed is not None and reclaimed["id"] == queued["id"]
    # Each claim has its own token, the worker's id first (QUEUE_LEASE_SHUTDOWN, AR-17).
    assert reclaimed["lease_token"].startswith("worker_after_restart:")


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


# ---------------------------------------------------- paid tasks collected, never bought --
#
# The watchdog's other promise (config: `watchdog_interval_seconds`; worker: "a provider job
# never collected") was untrue until 2026-10-01: a task the vendor had accepted and the studio
# never collected stayed lost. A SUBMITTED take is now asked about by its task id, with a GET
# on the vendor's API (faked here at its transport), and nothing is ever POSTed.


class RunwayTasks:
    """Runway's HTTPS boundary, faked: GET /v1/tasks/{id} per a script, and the downloads."""

    def __init__(self, tasks: dict[str, dict]) -> None:
        self.tasks = tasks
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, host, method, path, headers, body=None, **_kwargs):
        self.calls.append((host, method, path))
        assert method == "GET", f"the watchdog sent a {method}: it must never buy"
        if host == "files.test":
            return None, b"MP4BYTES", "video/mp4"
        assert host == "api.dev.runwayml.com" and path.startswith("/v1/tasks/"), path
        return dict(self.tasks[path.rsplit("/", 1)[1]]), b"", "application/json"


def _submitted_take(engine, tmp_path, *, task_id: str, made_ago: timedelta, scene: int = 1):
    from app.media.models import SceneTake

    bundle = _create_verified_asset_bundle(engine, tmp_path)
    take_id = str(uuid4())
    made = (datetime.now(UTC) - made_ago).isoformat()
    with Session(engine) as session, session.begin():
        storyboard = session.scalars(
            select(Storyboard).where(Storyboard.script_draft_id == bundle["script_id"])
        ).one()
        session.add(
            SceneTake(
                id=take_id,
                storyboard_id=storyboard.id,
                scene_number=scene,
                kind="motion",
                prompt_hash="a" * 64,
                model_id="seedance2_5",
                resolution="1080:1920",
                seconds=5.0,
                credits_quoted=340.0,
                status="SUBMITTED",
                remote_task_id=task_id,
                created_at=made,
                updated_at=made,
            )
        )
    return take_id


def _runway(monkeypatch, tasks: dict[str, dict]):
    from app.providers import runway

    transport = RunwayTasks(tasks)
    monkeypatch.setattr(runway, "request", transport)
    return runway.RunwayVideoAdapter("key", None, {}), transport


def _take(engine, take_id: str):
    from app.media.models import SceneTake

    with Session(engine) as session:
        row = session.get(SceneTake, take_id)
        session.expunge(row)
        return row


def test_a_finished_task_is_downloaded_into_its_take_and_marked_paid(
    engine, settings, tmp_path, monkeypatch
):
    _autonomy(engine, False)
    take_id = _submitted_take(engine, tmp_path, task_id="task-ok", made_ago=timedelta(hours=2))
    adapter, transport = _runway(
        monkeypatch,
        {"task-ok": {"status": "SUCCEEDED", "output": ["https://files.test/out.mp4?sig=1"]}},
    )

    result = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), collector_for=lambda take: adapter
    )

    take = _take(engine, take_id)
    assert take.status == "PAID" and take.remote_task_id == "task-ok"
    assert open(take.path, "rb").read() == b"MP4BYTES"
    assert result["takes"]["paid"] == 1
    assert [call[1:] for call in transport.calls] == [
        ("GET", "/v1/tasks/task-ok"),
        ("GET", "/out.mp4?sig=1"),
    ]
    assert len(_events(engine, take_id, "media.scene_take_collected")) == 1


def test_a_task_the_vendor_failed_is_refused_with_its_code(engine, settings, tmp_path, monkeypatch):
    _autonomy(engine, False)
    take_id = _submitted_take(engine, tmp_path, task_id="task-bad", made_ago=timedelta(hours=1))
    adapter, _transport = _runway(
        monkeypatch,
        {"task-bad": {"status": "FAILED", "failureCode": "INTERNAL.BAD_OUTPUT.CODE01"}},
    )

    result = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), collector_for=lambda take: adapter
    )

    take = _take(engine, take_id)
    assert take.status == "REFUSED" and take.failure_code == "INTERNAL.BAD_OUTPUT.CODE01"
    assert result["takes"]["refused"] == 1


def test_a_task_still_running_is_left_and_one_too_old_is_lost_with_one_letter(
    engine, settings, tmp_path, monkeypatch
):
    from app.agents.messages import is_for_owner
    from app.agents.models import AgentMessage

    _autonomy(engine, False)
    fresh = _submitted_take(engine, tmp_path, task_id="task-new", made_ago=timedelta(hours=3))
    old = _submitted_take(engine, tmp_path, task_id="task-old", made_ago=timedelta(hours=25))
    adapter, _transport = _runway(
        monkeypatch,
        {"task-new": {"status": "RUNNING"}, "task-old": {"status": "RUNNING"}},
    )

    result = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), collector_for=lambda take: adapter
    )

    assert _take(engine, fresh).status == "SUBMITTED"
    lost = _take(engine, old)
    assert lost.status == "LOST" and lost.failure_code == "VENDOR.NOT_COLLECTED"
    assert "nu s-a cumpărat nimic din nou" in lost.failure_detail
    assert result["takes"]["lost"] == 1 and result["takes"]["waiting"] == 1
    with Session(engine) as session:
        letters = [row for row in session.scalars(select(AgentMessage)) if is_for_owner(row)]
    assert len(letters) == 1
    assert letters[0].subject.startswith("1 lucrare plătită pierdută la furnizor")
    assert "scena 1" in (letters[0].body_text or "")
    assert "Nu s-a cumpărat nimic din nou" in letters[0].body_text

    # The next pass writes no second letter about the same take: it is LOST, not asked again.
    run_watchdog(engine, settings, correlation_id=str(uuid4()), collector_for=lambda take: adapter)
    with Session(engine) as session:
        letters = [row for row in session.scalars(select(AgentMessage)) if is_for_owner(row)]
    assert len(letters) == 1


def test_no_task_is_asked_about_while_the_autonomy_stop_is_set(
    engine, settings, tmp_path, monkeypatch
):
    take_id = _submitted_take(engine, tmp_path, task_id="task-ok", made_ago=timedelta(hours=30))
    adapter, transport = _runway(monkeypatch, {"task-ok": {"status": "SUCCEEDED", "output": []}})
    _autonomy(engine, True)

    result = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), collector_for=lambda take: adapter
    )

    assert result["status"] == "SKIPPED"
    assert transport.calls == []
    assert _take(engine, take_id).status == "SUBMITTED"


# ------------------------------------------------------- publishing truth (2026-10-02) --
#
# PUB-01: STARTED was not one of the states the watchdog looked at, so a process that died
# mid-upload (or a token refusal that escaped, before this item) left the row STARTED for
# good. PUB-08: a video YouTube rejected was reconciled as PUBLISHED, and nothing looked at
# its processing after the upload. PUB-12: none of it reached the Owner.

import pytest  # noqa: E402
from app.agents.models import AgentMessage  # noqa: E402
from app.providers.publishing_base import RemoteVideoStatus  # noqa: E402


def _owner_letters(engine) -> list[AgentMessage]:
    with Session(engine) as session:
        return [
            row
            for row in session.scalars(
                select(AgentMessage).where(AgentMessage.intent == "ESCALATE")
            )
            if row.to_agent_id is None and (row.body_json or {}).get("to") == "Owner"
        ]


def _aged(engine, publication_id: str, *, ago: timedelta, published: bool = False) -> None:
    with Session(engine) as session, session.begin():
        record = session.get(PublicationRecord, publication_id)
        moment = (datetime.now(UTC) - ago).isoformat()
        record.created_at = moment
        if published:
            record.published_at = moment


class StatusPlatform(DeterministicPublishingAdapter):
    """YouTube's answers about one video, in order; every question counted."""

    def __init__(self, answers: list[RemoteVideoStatus]) -> None:
        super().__init__()
        self.answers = list(answers)
        self.questions = 0
        self.uploads = 0

    async def get_video_status(self, remote_video_id: str) -> Any:
        self.questions += 1
        return self.answers.pop(0)

    async def upload_video(self, file_path, **kwargs: Any) -> Any:
        self.uploads += 1
        return await super().upload_video(file_path, **kwargs)


def test_a_started_row_past_its_time_is_reconciled_and_found_on_the_channel(
    engine, settings, tmp_path
):
    _autonomy(engine, False)
    stale = _publication(engine, tmp_path, status="STARTED")
    _aged(engine, stale, ago=timedelta(hours=2))
    fresh = _publication(engine, tmp_path / "fresh", status="STARTED")
    with Session(engine) as session:
        key = session.get(PublicationRecord, stale).idempotency_key
    platform = DeterministicPublishingAdapter()
    # The upload had landed before the process died.
    platform._published_videos["landed"] = {"privacy_status": "private", "idempotency_key": key}

    result = run_watchdog(
        engine,
        SimpleNamespace(publish_stuck_after_seconds=3600),
        correlation_id=str(uuid4()),
        publisher_for=lambda channel_id: platform,
    )

    assert result["publications"]["stale_started"] == 1
    with Session(engine) as session:
        record = session.get(PublicationRecord, stale)
        assert record.status == "PUBLISHED_SIMULATED"
        assert record.remote_video_id == "landed"
        # A row inside its time is an upload still running: left alone.
        assert session.get(PublicationRecord, fresh).status == "STARTED"
    assert len(_events(engine, stale, "publishing.started_stale")) == 1


def test_a_started_row_the_channel_does_not_hold_becomes_retryable(engine, settings, tmp_path):
    _autonomy(engine, False)
    stale = _publication(engine, tmp_path, status="STARTED")
    _aged(engine, stale, ago=timedelta(hours=2))
    run_watchdog(
        engine,
        SimpleNamespace(publish_stuck_after_seconds=3600),
        correlation_id=str(uuid4()),
        publisher_for=lambda channel_id: DeterministicPublishingAdapter(),
    )

    with Session(engine) as session:
        record = session.get(PublicationRecord, stale)
        assert record.status == "FAILED_RETRYABLE"
        assert "nu a fost găsit" in (record.error_detail or "")


def test_an_unknown_publication_without_an_id_is_asked_by_title_once_it_has_settled(
    engine, settings, tmp_path
):
    """The upload was cut before YouTube named the video. The channel's own uploads are asked
    (by the provider's reconciliation) once the row is old enough for a finished upload to be
    listed; before that it waits, asked nothing."""
    _autonomy(engine, False)
    young = _publication(engine, tmp_path, status="REMOTE_UNKNOWN", remote_video_id=None)
    settled = _publication(engine, tmp_path / "s", status="REMOTE_UNKNOWN", remote_video_id=None)
    _aged(engine, settled, ago=timedelta(hours=1))

    result = run_watchdog(
        engine,
        settings,
        correlation_id=str(uuid4()),
        publisher_for=lambda channel_id: DeterministicPublishingAdapter(),
    )

    assert result["publications"]["waiting"] == 1
    with Session(engine) as session:
        assert session.get(PublicationRecord, young).status == "REMOTE_UNKNOWN"
        assert session.get(PublicationRecord, settled).status == "FAILED_RETRYABLE"


@pytest.mark.parametrize(
    ("upload_status", "reason"),
    [("rejected", "duplicate"), ("failed", "codec"), ("deleted", None)],
)
def test_a_video_youtube_rejected_is_failed_with_its_reason_and_one_letter(
    engine, settings, tmp_path, upload_status, reason
):
    _autonomy(engine, False)
    publication_id = _publication(engine, tmp_path, status="REMOTE_UNKNOWN", remote_video_id="r1")
    answer = RemoteVideoStatus(
        remote_video_id="r1",
        exists=True,
        privacy_status="private",
        upload_status=upload_status,
        rejection_reason=reason if upload_status == "rejected" else None,
        failure_reason=reason if upload_status == "failed" else None,
    )
    platform = StatusPlatform([answer, answer])

    run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: platform
    )
    run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: platform
    )

    with Session(engine) as session:
        record = session.get(PublicationRecord, publication_id)
        assert record.status == "FAILED_FINAL"
        assert record.remote_upload_status == upload_status
        if reason:
            assert reason in (record.error_detail or "")
    letters = _owner_letters(engine)
    assert len(letters) == 1
    assert "YouTube" in (letters[0].body_text or "")
    assert platform.uploads == 0


def _published_row(engine, tmp_path, *, ago: timedelta, remote: str = "yt-1") -> str:
    publication_id = _publication(engine, tmp_path, status="PUBLISHED", remote_video_id=remote)
    _aged(engine, publication_id, ago=ago, published=True)
    return publication_id


def test_processing_is_followed_for_six_hours_until_youtube_says_processed(
    engine, settings, tmp_path
):
    _autonomy(engine, False)
    recent = _published_row(engine, tmp_path, ago=timedelta(hours=1))
    _published_row(engine, tmp_path / "old", ago=timedelta(hours=7), remote="yt-old")

    def status(upload: str) -> RemoteVideoStatus:
        return RemoteVideoStatus(
            remote_video_id="yt-1", exists=True, privacy_status="private", upload_status=upload
        )

    platform = StatusPlatform([status("uploaded"), status("processed")])
    for _ in range(3):
        run_watchdog(
            engine,
            settings,
            correlation_id=str(uuid4()),
            publisher_for=lambda channel_id: platform,
        )

    # Two questions about the recent film, none about the old one, none after "processed".
    assert platform.questions == 2
    with Session(engine) as session:
        record = session.get(PublicationRecord, recent)
        assert record.status == "PUBLISHED"
        assert record.remote_upload_status == "processed"
        assert record.remote_privacy_status == "private"
    assert _owner_letters(engine) == []


def test_processing_that_ends_rejected_fails_the_publication_with_a_letter(
    engine, settings, tmp_path
):
    _autonomy(engine, False)
    recent = _published_row(engine, tmp_path, ago=timedelta(minutes=30))
    platform = StatusPlatform(
        [
            RemoteVideoStatus(
                remote_video_id="yt-1",
                exists=True,
                privacy_status="private",
                upload_status="rejected",
                rejection_reason="copyright",
            )
        ]
    )

    result = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: platform
    )

    assert result["processing"]["rejected"] == 1
    with Session(engine) as session:
        record = session.get(PublicationRecord, recent)
        assert record.status == "FAILED_FINAL"
        assert "copyright" in (record.error_detail or "")
    assert len(_owner_letters(engine)) == 1


def test_a_handed_over_publication_writes_the_owner_one_letter(engine, tmp_path):
    _autonomy(engine, False)
    _publication(engine, tmp_path, status="REMOTE_UNKNOWN", remote_video_id="v9")
    platform = SilentPlatform()
    settings = SimpleNamespace(reconcile_max_attempts=1)
    for _ in range(3):
        run_watchdog(
            engine,
            settings,
            correlation_id=str(uuid4()),
            publisher_for=lambda channel_id: platform,
        )
    letters = _owner_letters(engine)
    assert len(letters) == 1
    assert "Există" in (letters[0].body_text or "")


def test_the_owners_answer_that_the_film_is_not_there_gives_the_retry_its_attempts_back(
    engine, tmp_path
):
    """His «Nu există» makes the row retryable; the attempts counted before his answer were
    the studio's failure to ask, not this retry's, so the next pass retries it (asking the
    channel first) instead of handing it straight back to him with a second letter."""
    from app.publishing.services import resolve_publication  # noqa: PLC0415

    _autonomy(engine, False)
    publication_id = _publication(engine, tmp_path, status="REMOTE_UNKNOWN", remote_video_id="v9")
    settings = SimpleNamespace(reconcile_max_attempts=1)
    silent = SilentPlatform()
    for _ in range(2):
        run_watchdog(
            engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: silent
        )
    with Session(engine) as session:
        assert session.get(PublicationRecord, publication_id).status == "NEEDS_RECONCILIATION"
    assert len(_owner_letters(engine)) == 1

    resolve_publication(
        engine, publication_id, found=False, remote_video_id=None, command_id=str(uuid4())
    )
    platform = DeterministicPublishingAdapter()
    result = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda channel_id: platform
    )

    assert result["publications"]["handed_to_owner"] == 0
    assert result["publications"]["retry_uploaded"] == 1
    with Session(engine) as session:
        assert session.get(PublicationRecord, publication_id).status == "PUBLISHED_SIMULATED"
    assert len(_owner_letters(engine)) == 1
