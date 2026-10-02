"""The media room's list is one request of summary rows, newest first, a page at a time (PAGE-17).

Opening «Producție media» used to fetch every storyboard and then, for each of them, its
production package, its detail and its QC report: 3N+1 requests on every opening, about 1,100
a year at one film a day. The list now carries what the closed card shows (the scene count,
the QC verdict and the film's asset id) and the page loads a card's detail when he opens it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.factual.models import ScriptDraft, TopicIdea
from app.media.models import (
    MediaAsset,
    QualityControlReport,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from sqlalchemy.orm import Session

BASE = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def _at(days: int) -> str:
    return (BASE + timedelta(days=days)).isoformat()


def _board(engine, title: str, *, day: int, scenes: int = 2) -> str:
    topic_id, script_id, board_id = str(uuid4()), str(uuid4()), str(uuid4())
    with Session(engine) as session, session.begin():
        session.add(
            TopicIdea(
                id=topic_id,
                title=title,
                topic="t",
                angle="a",
                target_audience="general",
                novelty_score=0.5,
                status="SELECTED",
                created_at=_at(day),
            )
        )
        session.flush()
        session.add(
            ScriptDraft(
                id=script_id,
                topic_id=topic_id,
                version=1,
                title=title,
                target_duration_seconds=12,
                voiceover_full_text="One line.",
                scenes_json=[],
                status="APPROVED",
                claim_ids_json=[],
                unverified_claim_ids_json=[],
                created_at=_at(day),
            )
        )
        session.flush()
        session.add(
            Storyboard(
                id=board_id,
                script_draft_id=script_id,
                title=title,
                visual_style="PER_SCENE",
                aspect_ratio="9:16",
                target_duration_seconds=12,
                status="APPROVED",
                total_scenes=scenes,
                created_at=_at(day),
            )
        )
        session.flush()
        for index in range(1, scenes + 1):
            session.add(
                StoryboardScene(
                    id=str(uuid4()),
                    storyboard_id=board_id,
                    scene_index=index,
                    visual_prompt=f"scene {index}",
                    visual_type="GENERATED_IMAGE",
                    duration_seconds=6.0,
                    voiceover_segment="One line.",
                    shot_type="MEDIUM",
                    transition_in="CUT",
                    character_ids_json=[],
                    claim_ids_json=[],
                    created_at=_at(day),
                )
            )
    return board_id


def _rendered(engine, board_id: str, *, day: int, verdicts: tuple[str, ...]) -> str:
    asset_id = str(uuid4())
    with Session(engine) as session, session.begin():
        session.get(Storyboard, board_id).status = "RENDERED"
        session.add(
            MediaAsset(
                id=asset_id,
                asset_type="RENDERED_VIDEO",
                uri_or_path=f"films/{asset_id}.mp4",
                file_size_bytes=10,
                mime_type="video/mp4",
                width=1080,
                height=1920,
                duration_seconds=12.0,
                provider_name="test",
                license_status="LICENSED",
                provenance_hash="0" * 64,
                created_at=_at(day),
            )
        )
        session.flush()
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=board_id,
                output_asset_id=asset_id,
                status="COMPLETED",
                render_engine="FFMPEG",
                command_args_json=[],
                production_json={},
                started_at=_at(day),
                finished_at=_at(day),
            )
        )
        session.flush()
        for minute, verdict in enumerate(verdicts):
            session.add(
                QualityControlReport(
                    id=str(uuid4()),
                    media_asset_id=asset_id,
                    status=verdict,
                    score=1.0,
                    checks_json={},
                    failure_reasons_json=[],
                    verified_at=(BASE + timedelta(days=day, minutes=minute)).isoformat(),
                )
            )
    return asset_id


def test_the_list_is_paged_newest_first_with_its_total(client, headers, engine):
    oldest = _board(engine, "Cel mai vechi", day=1)
    middle = _board(engine, "Din mijloc", day=2)
    newest = _board(engine, "Cel mai nou", day=3)

    first = client.get("/api/v1/media/storyboards?limit=2", headers=headers).json()
    assert [row["id"] for row in first["storyboards"]] == [newest, middle]
    assert first["total"] == 3
    assert first["next_offset"] == 2

    second = client.get("/api/v1/media/storyboards?limit=2&offset=2", headers=headers).json()
    assert [row["id"] for row in second["storyboards"]] == [oldest]
    assert second["next_offset"] is None


def test_a_row_carries_what_the_closed_card_shows(client, headers, engine):
    board = _board(engine, "Randat", day=1, scenes=4)
    asset = _rendered(engine, board, day=1, verdicts=("FAILED", "PASSED"))
    plain = _board(engine, "Doar aprobat", day=2)

    rows = {
        row["id"]: row
        for row in client.get("/api/v1/media/storyboards", headers=headers).json()["storyboards"]
    }

    assert rows[board]["scene_count"] == 4
    assert rows[board]["asset_id"] == asset
    assert rows[board]["qc_status"] == "PASSED"  # the newest verdict of the newest film
    assert rows[plain]["scene_count"] == 2
    assert rows[plain]["asset_id"] is None
    assert rows[plain]["qc_status"] is None
    # summary rows: no scene list rides along
    assert "scenes" not in rows[board] or rows[board]["scenes"] == []


def test_the_newest_film_that_passed_qc_is_one_query(client, headers, engine):
    """Quick publish asks the studio for its film instead of one QC request per storyboard."""
    passed_old = _board(engine, "Trecut, vechi", day=1)
    _rendered(engine, passed_old, day=1, verdicts=("PASSED",))
    passed_new = _board(engine, "Trecut, nou", day=2)
    asset = _rendered(engine, passed_new, day=2, verdicts=("PASSED",))
    failed = _board(engine, "Picat", day=3)
    _rendered(engine, failed, day=3, verdicts=("PASSED", "FAILED"))
    _board(engine, "Nerandat", day=4)

    answer = client.get(
        "/api/v1/media/storyboards?qc_status=PASSED&limit=1", headers=headers
    ).json()

    assert [row["id"] for row in answer["storyboards"]] == [passed_new]
    assert answer["storyboards"][0]["asset_id"] == asset
    assert answer["storyboards"][0]["title"] == "Trecut, nou"
    assert answer["total"] == 2


def test_a_page_too_large_is_refused(client, headers):
    assert client.get("/api/v1/media/storyboards?limit=500", headers=headers).status_code == 422
    assert client.get("/api/v1/media/storyboards?offset=-1", headers=headers).status_code == 422
