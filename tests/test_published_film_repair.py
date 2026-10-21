"""Published assets must not re-enter prompt repair or purchases; no real providers."""

# ruff: noqa: F811 -- imported pytest fixture is intentionally injected by name
from uuid import uuid4

import pytest
from app.media import blocker_repair as repair
from app.media.models import MediaAsset, Storyboard, VideoRenderJob
from app.media.shooting_sheet import FilmClosed, film_is_closed, film_purchase_lease
from app.publishing.models import ChannelRecord, PublicationRecord
from app.services import utc_now
from sqlalchemy.orm import Session
from test_sheet_blocker_repair import film, sheet, task  # noqa: F401 - fixtures/helpers


def published(engine, board, *, status="PUBLISHED", privacy="public", remote=True):
    asset_id, channel_id, publication_id = (str(uuid4()) for _ in range(3))
    now = utc_now()
    with Session(engine) as session, session.begin():
        session.add(
            ChannelRecord(id=channel_id, channel_name="Offline test channel", created_at=now)
        )
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path="offline.mp4",
                mime_type="video/mp4",
                provider_name="TEST",
                created_at=now,
                provenance_hash="0" * 64,
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=board,
                output_asset_id=asset_id,
                status="COMPLETED",
                started_at=now,
                finished_at=now,
            )
        )
        session.add(
            PublicationRecord(
                id=publication_id,
                channel_id=channel_id,
                media_asset_id=asset_id,
                title="Different published title",
                description="Offline test",
                status=status,
                privacy_status=privacy,
                remote_video_id="test-remote" if remote else None,
                idempotency_key=publication_id,
                published_at=now if status == "PUBLISHED" else None,
                created_at=now,
            )
        )
    return publication_id


@pytest.mark.parametrize("privacy", ["public", "private", "unlisted"])
def test_a_confirmed_upload_is_closed_for_production_regardless_of_board_label(
    engine, film, privacy
):
    published(engine, film, privacy=privacy)
    with Session(engine) as session:
        assert session.get(Storyboard, film).status == "APPROVED"
        assert film_is_closed(session, film)


@pytest.mark.parametrize(
    "status,remote", [("VALIDATED", False), ("FAILED_RETRYABLE", True), ("PUBLISHED", False)]
)
def test_an_unconfirmed_or_failed_publication_does_not_pretend_the_film_was_uploaded(
    engine, film, status, remote
):
    published(engine, film, status=status, remote=remote)
    with Session(engine) as session:
        assert not film_is_closed(session, film)


def test_the_published_board_is_excluded_from_sheet_scans_before_reading_a_sheet(
    engine, film, monkeypatch
):
    published(engine, film)
    monkeypatch.setattr(repair, "build_sheet", lambda *_a, **_k: pytest.fail("published scan"))
    assert repair.scan_sheet_issues(engine)["reported"] == []


def test_a_report_from_before_publication_cannot_enqueue_more_repair(engine, film):
    reading = sheet(engine, film)
    published(engine, film)
    result = repair.submit_sheet_issues(engine, reading)
    assert result["status"] == "FILM_CLOSED"
    assert task(engine) is None


def test_a_repair_queued_before_upload_stops_without_any_llm_call(engine, film, monkeypatch):
    repair.submit_sheet_issues(engine, sheet(engine, film))
    queued = task(engine)
    published(engine, film)
    monkeypatch.setattr(
        repair, "director_assignment", lambda *_a, **_k: pytest.fail("published LLM")
    )
    monkeypatch.setattr(repair, "build_sheet", lambda *_a, **_k: pytest.fail("published sheet"))
    result = repair.process_sheet_repair(engine, object(), queued.payload, correlation_id=queued.id)
    assert result["status"] == "STALE"
    assert result["remaining"] == []
    assert "continue_task_id" not in result
    with Session(engine) as session:
        from app.agents.models import AgentMessage

        report = session.get(AgentMessage, queued.payload["message_id"])
        assert report.status == "RESOLVED"
        assert report.body_json["repair_result"]["status"] == "STALE"


def test_a_published_film_cannot_acquire_a_new_purchase_lease(engine, film):
    published(engine, film)
    with pytest.raises(FilmClosed):
        with film_purchase_lease(engine, film, holder="offline-test", step="stills"):
            pytest.fail("a new purchase must not start")


def test_a_published_film_cannot_rewrite_its_initial_prompt_package(engine, film):
    from app.media.prompt_agent import PromptError, write_shot_prompts

    published(engine, film)
    with pytest.raises(PromptError):
        write_shot_prompts(engine, object(), film)
