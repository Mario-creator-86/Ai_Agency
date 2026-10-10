"""Uploads held private for their licence alone are made public once it is confirmed (2026-10-10).

Film babcf272 went up private to «Main Channel A - Factual Shorts» (YouTube IxQIzIulLBU): its
narrations came from ElevenLabs and the connection had no commercial-use evidence, so its
licence was NEEDS_REVIEW and the gate's rights check lets such a film up private only. The Owner
upgrades his plan and the studio records the licence; the watchdog then makes the film public,
under the channel's policy as it is then (YouTube faked here, never the network). Nothing else is
touched: an upload private for another reason, a channel whose policy is private or unlisted, a
stopped studio, safe mode, a mode that asks him, public not permitted on the channel.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from app.integrations.models import Integration
from app.integrations.vault import CredentialVault
from app.media.models import MediaAsset, VideoRenderJob
from app.models import ApprovalRequest, DomainEvent, OwnerPolicy
from app.providers.publishing_base import RemoteStateUnavailable, RemoteVideoStatus, UploadResult
from app.providers.registry import ProviderRegistry
from app.publishing.licence_release import (
    HELD_EVENT,
    LICENCE_CONFIRMED_EVENT,
    RELEASE_FAILED_EVENT,
    RELEASED_EVENT,
    licence_held_uploads,
    mark_held_for_licence,
    release_licence_held_uploads,
)
from app.publishing.models import PublicationRecord
from app.publishing.schemas import PublishPolicyCommand
from app.publishing.services import change_publish_policy
from app.runbook.models import DailyRun, SafeModeRecord
from app.runbook.stages import build_stage_runners
from app.services import append_event, utc_now
from app.workflows.passes import registered_passes
from app.workflows.watchdog import run_watchdog
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_daily_run_stages import _bound, _connected, _seeded_channels
from test_phase6_publishing import _create_verified_asset_bundle
from test_publish_policy import _to_production

VIDEO = "IxQIzIulLBU"
VOICE_MISSING = "narațiunea scenei 1 (elevenlabs): nicio confirmare de folosire comercială"


class FakeYouTube:
    """The Owner's channel account, faked: a real (not simulated) upload, and every visibility
    change it is asked for, remembered."""

    IS_SIMULATED = False

    def __init__(self, *, failures: int = 0, keeps_private: bool = False) -> None:
        self.failures = failures
        self.keeps_private = keeps_private
        self.uploads: list[str] = []
        self.changes: list[tuple[str, str, bool]] = []

    async def upload_video(self, file_path: Any, **kwargs: Any) -> UploadResult:
        self.uploads.append(kwargs["privacy_status"])
        return UploadResult(
            remote_video_id=VIDEO,
            remote_url=f"https://youtube.com/shorts/{VIDEO}",
            status="CONFIRMED",
            privacy_status=kwargs["privacy_status"],
            upload_status="uploaded",
        )

    async def get_video_status(self, remote_video_id: str) -> RemoteVideoStatus:
        return RemoteVideoStatus(
            remote_video_id=remote_video_id,
            exists=True,
            privacy_status="private",
            upload_status="processed",
        )

    async def update_visibility(
        self, remote_video_id: str, privacy_status: str, *, made_for_kids: bool = False
    ) -> RemoteVideoStatus:
        self.changes.append((remote_video_id, privacy_status, made_for_kids))
        if self.failures:
            self.failures -= 1
            raise RemoteStateUnavailable("YouTube could not be asked to change the visibility.")
        return RemoteVideoStatus(
            remote_video_id=remote_video_id,
            exists=True,
            privacy_status="private" if self.keeps_private else privacy_status,
            upload_status="processed",
        )


# ------------------------------------------------------------------------------- helpers --


def _voice_connection(engine, *, encrypted_secrets: str = "sealed") -> str:
    """An ElevenLabs connection with no commercial-use evidence, as babcf272's was."""
    identifier = str(uuid4())
    with Session(engine) as session, session.begin():
        saved = append_event(
            session, "settings.integration_saved", "integration", identifier, 1, {}, str(uuid4())
        )
        session.add(
            Integration(
                id=identifier,
                kind="elevenlabs",
                name="AMN-AI",
                config={},
                encrypted_secrets=encrypted_secrets,
                secret_fields=["api_key"],
                version=1,
                status="VERIFIED",
                event_id=saved.event_id,
            )
        )
    return identifier


def _record_licence(engine, integration_id: str) -> None:
    """The licence recorded on the connection (`integrations.plan_licence` writes this)."""
    with Session(engine) as session, session.begin():
        row = session.get(Integration, integration_id)
        row.config = {**dict(row.config or {}), "commercial_use": "da"}


def _main_channel(engine, *, privacy: str = "public", public_enabled: bool = True) -> str:
    """Main Channel A, bound to a connected account, its policy the Owner's, in PRODUCTION."""
    main = _seeded_channels(engine)["MAIN_FACTUAL"]["id"]
    _bound(engine, main, _connected(engine, "Main Channel A"))
    _to_production(engine)
    change_publish_policy(
        engine,
        main,
        PublishPolicyCommand(
            command_id=uuid4(),
            expected_version=1,
            autonomous_privacy=privacy,
            public_publish_enabled=public_enabled,
        ),
    )
    return main


def _change_policy(engine, channel_id: str, **policy: Any) -> None:
    from app.publishing.models import ChannelRecord

    with Session(engine) as session:
        version = int(session.get(ChannelRecord, channel_id).policy_version)
    change_publish_policy(
        engine,
        channel_id,
        PublishPolicyCommand(command_id=uuid4(), expected_version=version, **policy),
    )


def _film(engine, tmp_path: Path, integration_id: str) -> str:
    """A QC-passed film whose narration's licence is not confirmed: NEEDS_REVIEW, with the
    ledger naming the connection its evidence was read from."""
    asset_id = _create_verified_asset_bundle(engine, tmp_path)["asset_id"]
    with Session(engine) as session, session.begin():
        session.get(MediaAsset, asset_id).license_status = "NEEDS_REVIEW"
        job = session.scalars(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == asset_id)
        ).one()
        job.production_json = {
            "licences": {
                "status": "NEEDS_REVIEW",
                "components": [
                    {
                        "component": "narration",
                        "scene_index": 1,
                        "take_id": None,
                        "vendor": "elevenlabs",
                        "integration_id": integration_id,
                        "terms": None,
                        "commercial_use": None,
                        "source": "connection",
                    },
                    {"component": "fonts", "vendor": "Inter", "commercial_use": True},
                ],
                "missing_ro": [VOICE_MISSING],
            }
        }
    return asset_id


def _upload(
    engine, channel_id: str, asset_id: str, *, held: bool = True, created_at: str | None = None
) -> str:
    """The film on the channel, private, as `_publish_one` leaves a licence-held upload."""
    publication_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            PublicationRecord(
                id=publication_id,
                channel_id=channel_id,
                media_asset_id=asset_id,
                title="The Particle That Shouldn't Exist (But Does)",
                description="d",
                tags_json=[],
                privacy_status="private",
                status="PUBLISHED",
                idempotency_key=str(uuid4()),
                remote_video_id=VIDEO,
                remote_url=f"https://youtube.com/shorts/{VIDEO}",
                policy_version=2,
                remote_privacy_status="private",
                created_at=created_at or utc_now(),
                published_at=utc_now(),
            )
        )
        if held:
            mark_held_for_licence(
                session,
                publication_id,
                "încărcat privat: licența filmului nu este confirmată (…)",
                [VOICE_MISSING],
            )
    return publication_id


def _held_film(engine, tmp_path: Path, **channel: Any) -> dict[str, str]:
    integration_id = _voice_connection(engine)
    channel_id = _main_channel(engine, **channel)
    asset_id = _film(engine, tmp_path, integration_id)
    return {
        "integration_id": integration_id,
        "channel_id": channel_id,
        "asset_id": asset_id,
        "publication_id": _upload(engine, channel_id, asset_id),
    }


def _release(engine, youtube: FakeYouTube, **kwargs: Any) -> dict[str, Any]:
    return release_licence_held_uploads(engine, lambda _channel: youtube, str(uuid4()), **kwargs)


def _events(engine, event_type: str, aggregate_id: str | None = None) -> list[DomainEvent]:
    with Session(engine) as session:
        query = select(DomainEvent).where(DomainEvent.event_type == event_type)
        if aggregate_id is not None:
            query = query.where(DomainEvent.aggregate_id == aggregate_id)
        return list(session.scalars(query))


def _publication(engine, publication_id: str) -> PublicationRecord:
    with Session(engine) as session:
        row = session.get(PublicationRecord, publication_id)
        session.expunge(row)
        return row


def _owner_notes(engine) -> list[Any]:
    from app.agents.models import AgentMessage

    with Session(engine) as session:
        return [
            (row.intent, row.subject, row.body_text)
            for row in session.scalars(select(AgentMessage))
            if (row.body_json or {}).get("kind") == "publication_released"
        ]


# ------------------------------------------------------------- the film goes public, once --


def test_a_licence_held_upload_goes_public_once_the_licence_is_recorded(
    engine, settings, tmp_path, monkeypatch
):
    """The publish stage uploads the NEEDS_REVIEW film private and marks why; while the licence
    is missing nothing happens; once it is recorded the video is made public through YouTube's
    videos.update, the record says public under the channel's current policy version, the
    film is LICENSED, the event is written once and the Owner gets one note."""
    integration_id = _voice_connection(engine)
    _main_channel(engine)
    asset_id = _film(engine, tmp_path, integration_id)
    youtube = FakeYouTube()
    monkeypatch.setattr("app.runbook.stages.selected_youtube", lambda *a, **k: youtube)
    monkeypatch.setattr(
        "app.runbook.stages.latest_editorial",
        lambda session, asset: type("Review", (), {"verdict": "APPROVE", "reasons_json": []})(),
    )
    monkeypatch.setattr(
        "app.runbook.stages.approved_metadata",
        lambda session, asset: {
            "title": "The Particle That Shouldn't Exist (But Does)",
            "description": "A particle physics short.",
            "tags": ["physics"],
        },
    )
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    runners = build_stage_runners(engine, settings, vault, ProviderRegistry())

    outcome = runners["publish"]()

    assert outcome["status"] == "COMPLETED", outcome
    assert youtube.uploads == ["private"]
    (publication,) = (p["publication_id"] for p in outcome["artefacts"]["published"])
    (held,) = _events(engine, HELD_EVENT, publication)
    assert held.payload["missing_ro"] == [VOICE_MISSING]
    assert held.payload["reason"].startswith("încărcat privat: licența filmului nu este")

    waiting = _release(engine, youtube)

    assert youtube.changes == []
    assert waiting["released"] == [] and waiting["waiting"][0]["why"] == "licence"
    assert VOICE_MISSING in waiting["waiting"][0]["reason"]
    assert _publication(engine, publication).privacy_status == "private"

    _record_licence(engine, integration_id)
    released = _release(engine, youtube)

    assert released["released"] == [publication]
    assert youtube.changes == [(VIDEO, "public", False)]
    row = _publication(engine, publication)
    assert row.privacy_status == "public" and row.remote_privacy_status == "public"
    assert row.policy_version == 2  # the version of the Owner's public policy
    (event,) = _events(engine, RELEASED_EVENT, publication)
    assert event.payload["held_known_by"] == "marked"
    assert row.event_id == event.event_id
    with Session(engine) as session:
        assert session.get(MediaAsset, asset_id).license_status == "LICENSED"
        job = session.scalars(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == asset_id)
        ).one()
        assert job.production_json["licences"]["missing_ro"] == []
    assert len(_events(engine, LICENCE_CONFIRMED_EVENT, asset_id)) == 1
    ((intent, subject, text),) = _owner_notes(engine)
    assert intent == "STATUS"
    assert "este acum public pe Main Channel A - Factual Shorts" in subject
    assert "fusese încărcat privat doar din cauza ei" in text and VIDEO in text

    again = _release(engine, youtube)

    assert again == {"released": [], "kept_private": [], "failed": [], "waiting": []}
    assert len(youtube.changes) == 1
    assert len(_events(engine, RELEASED_EVENT)) == 1 and len(_owner_notes(engine)) == 1


def test_the_watchdog_records_the_licence_and_releases_the_film_in_the_same_pass(
    engine, settings, tmp_path, monkeypatch
):
    """`licence_release` runs after `vendor_plan_licence`: the pass that reads the Owner's paid
    plan (faked) also makes the held film public, through the account bound to the channel."""
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    integration_id = _voice_connection(engine, encrypted_secrets=vault.encrypt({"api_key": "x"}))
    main = _main_channel(engine)
    publication = _upload(engine, main, _film(engine, tmp_path, integration_id))
    youtube = FakeYouTube()
    monkeypatch.setattr(
        "app.integrations.plan_licence._read_plan",
        lambda key: {"tier": "creator", "status": "active"},
    )
    monkeypatch.setattr("app.integrations.services.selected_youtube", lambda *a, **k: youtube)

    result = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda _c: youtube
    )

    order = [entry.name for entry in registered_passes()]
    assert order.index("vendor_plan_licence") < order.index("licence_release")
    assert result["vendor_plan_licence"]["recorded"] == [integration_id]
    assert result["licence_release"]["released"] == [publication]
    assert youtube.changes == [(VIDEO, "public", False)]


def test_nothing_is_opened_while_no_upload_is_held(engine, settings, monkeypatch):
    """A studio with no held upload: the pass reads and returns; no account is opened."""

    def no_account(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("no account is opened for nothing")

    monkeypatch.setattr("app.workflows.watchdog._default_publisher_for", no_account)
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False

    result = run_watchdog(
        engine, settings, correlation_id=str(uuid4()), publisher_for=lambda _c: None
    )

    assert result["licence_release"] == {
        "released": [],
        "kept_private": [],
        "failed": [],
        "waiting": [],
    }


# ------------------------------------------------------------------- what is never touched --


def test_an_upload_private_for_another_reason_is_never_touched(engine, tmp_path):
    """Private because the channel's policy was private when it went up: no marker, no walk or
    day that said «licence». The licence confirmed and the policy public now change nothing."""
    integration_id = _voice_connection(engine)
    main = _main_channel(engine)
    asset_id = _film(engine, tmp_path, integration_id)
    publication = _upload(engine, main, asset_id, held=False)
    _record_licence(engine, integration_id)
    youtube = FakeYouTube()

    assert licence_held_uploads(engine) == []
    assert _release(engine, youtube) == {
        "released": [],
        "kept_private": [],
        "failed": [],
        "waiting": [],
    }
    assert youtube.changes == []
    assert _publication(engine, publication).privacy_status == "private"


@pytest.mark.parametrize(
    "policy",
    [
        {"autonomous_privacy": "private"},
        {"autonomous_privacy": "unlisted"},
        {"public_publish_enabled": False},
    ],
    ids=["private", "unlisted", "public-not-permitted"],
)
def test_a_channel_policy_that_does_not_release_publicly_keeps_it_as_it_is(
    engine, tmp_path, policy
):
    held = _held_film(engine, tmp_path)
    _record_licence(engine, held["integration_id"])
    _change_policy(engine, held["channel_id"], **policy)
    youtube = FakeYouTube()

    result = _release(engine, youtube)

    assert youtube.changes == []
    assert [item["why"] for item in result["waiting"]] == ["policy"]
    assert _publication(engine, held["publication_id"]).privacy_status == "private"
    assert _events(engine, RELEASED_EVENT) == []


def _stopped(engine) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = True


def _safe_mode(engine) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            SafeModeRecord(
                id=str(uuid4()),
                reason="Un test ține studioul în SAFE_MODE.",
                trigger="STAGE_FAILURE",
                run_id=None,
                entered_at=utc_now(),
                cleared_at=None,
                cleared_notes=None,
                event_id=None,
            )
        )


def _supervised(engine) -> None:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_mode = "SUPERVISED"


@pytest.mark.parametrize(
    "state", [_stopped, _safe_mode, _supervised], ids=["stopped", "safe-mode", "supervised"]
)
def test_a_stopped_studio_safe_mode_or_a_mode_that_asks_him_keeps_it_private(
    engine, tmp_path, state
):
    held = _held_film(engine, tmp_path)
    _record_licence(engine, held["integration_id"])
    state(engine)
    youtube = FakeYouTube()

    result = _release(engine, youtube)

    assert youtube.changes == []
    assert [item["why"] for item in result["waiting"]] == ["mode"]
    assert _publication(engine, held["publication_id"]).privacy_status == "private"
    with Session(engine) as session:
        # Nothing of his is asked or spent: the mode is only read.
        assert session.scalars(select(ApprovalRequest)).all() == []


# ------------------------------------------------------------------ a call that fails, later --


def test_a_failed_change_is_asked_again_later_and_the_release_is_written_once(engine, tmp_path):
    held = _held_film(engine, tmp_path)
    _record_licence(engine, held["integration_id"])
    youtube = FakeYouTube(failures=1)

    first = _release(engine, youtube)

    assert first["failed"] == [held["publication_id"]]
    (failure,) = _events(engine, RELEASE_FAILED_EVENT, held["publication_id"])
    assert failure.payload["attempt"] == 1
    assert _publication(engine, held["publication_id"]).privacy_status == "private"

    soon = _release(engine, youtube)

    assert len(youtube.changes) == 1  # not asked again before the back-off has passed
    assert [item["why"] for item in soon["waiting"]] == ["backoff"]

    later = _release(engine, youtube, now=datetime.now(UTC) + timedelta(minutes=16))

    assert later["released"] == [held["publication_id"]]
    assert len(youtube.changes) == 2
    assert _publication(engine, held["publication_id"]).privacy_status == "public"
    assert len(_events(engine, RELEASED_EVENT, held["publication_id"])) == 1
    assert _release(engine, youtube, now=datetime.now(UTC) + timedelta(hours=2))["released"] == []
    assert len(_events(engine, RELEASED_EVENT)) == 1 and len(_owner_notes(engine)) == 1


def test_youtube_keeping_the_video_private_is_recorded_with_the_letter_and_not_retried(
    engine, tmp_path
):
    """An unaudited Google Cloud project: YouTube answers private whatever was asked. The
    record keeps YouTube's answer, the Owner gets the letter the upload path writes, and the
    studio does not ask again (he makes it visible from YouTube Studio)."""
    held = _held_film(engine, tmp_path)
    _record_licence(engine, held["integration_id"])
    youtube = FakeYouTube(keeps_private=True)

    result = _release(engine, youtube)

    assert result["kept_private"] == [held["publication_id"]]
    row = _publication(engine, held["publication_id"])
    assert row.privacy_status == "public" and row.remote_privacy_status == "private"
    assert len(_events(engine, "publishing.visibility_locked_private")) == 1
    assert _owner_notes(engine) == []
    assert _release(engine, youtube)["kept_private"] == []
    assert len(youtube.changes) == 1


# ------------------------------------------------- uploads made before the marker existed --


def test_an_upload_whose_walk_said_licence_is_released_like_a_marked_one(engine, tmp_path):
    """babcf272 went up before the marker existed: the walk that uploaded it
    (`runbook.film_continued`) said «încărcat privat: licența filmului nu este confirmată»."""
    from app.publishing.services import film_identity

    integration_id = _voice_connection(engine)
    main = _main_channel(engine)
    asset_id = _film(engine, tmp_path, integration_id)
    publication = _upload(engine, main, asset_id, held=False)
    with Session(engine) as session, session.begin():
        _script, storyboard_id = film_identity(session, asset_id)
        append_event(
            session,
            "runbook.film_continued",
            "storyboard",
            str(storyboard_id),
            1,
            {
                "status": "COMPLETED",
                "reason": "Pe Main Channel A - Factual Shorts: publicat (privat; încărcat "
                "privat: licența filmului nu este confirmată (narațiunea scenei 1); devine "
                "public doar după ce licența este confirmată).",
                "cause": "director_qc:d4ea68d2",
                "refusal": None,
            },
            str(uuid4()),
        )
    assert licence_held_uploads(engine) == [(publication, "walk")]
    _record_licence(engine, integration_id)
    youtube = FakeYouTube()

    assert _release(engine, youtube)["released"] == [publication]
    assert youtube.changes == [(VIDEO, "public", False)]
    (event,) = _events(engine, RELEASED_EVENT, publication)
    assert event.payload["held_known_by"] == "walk"


def test_an_upload_whose_day_said_licence_is_released_and_an_older_walk_is_not_read(
    engine, tmp_path
):
    """The day's publish stage keeps ``private_until_licensed`` per publication; a walk event
    written before the publication existed is not the walk that uploaded it."""
    from app.publishing.services import film_identity

    integration_id = _voice_connection(engine)
    main = _main_channel(engine)
    asset_id = _film(engine, tmp_path, integration_id)
    with Session(engine) as session, session.begin():
        _script, storyboard_id = film_identity(session, asset_id)
        append_event(
            session,
            "runbook.film_continued",
            "storyboard",
            str(storyboard_id),
            1,
            {
                "status": "COMPLETED",
                "reason": "încărcat privat: licența filmului nu este confirmată",
            },
            str(uuid4()),
        )
    later = (datetime.now(UTC) + timedelta(seconds=5)).isoformat()
    publication = _upload(engine, main, asset_id, held=False, created_at=later)
    assert licence_held_uploads(engine) == []

    with Session(engine) as session, session.begin():
        session.add(
            DailyRun(
                id=str(uuid4()),
                business_date=later[:10],
                preflight_status="READY",
                preflight_json={},
                status="COMPLETED",
                stages_json=[
                    {
                        "stage": "publish",
                        "status": "COMPLETED",
                        "reason": "Pe Main Channel A - Factual Shorts: publicat (privat).",
                        "artefacts": {
                            "published": [
                                {"publication_id": publication, "private_until_licensed": True}
                            ]
                        },
                    }
                ],
                stages_total=1,
                stages_completed=1,
                started_at=later,
            )
        )
    assert licence_held_uploads(engine) == [(publication, "day")]
    _record_licence(engine, integration_id)

    assert _release(engine, FakeYouTube())["released"] == [publication]
