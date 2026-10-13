"""The day's goal, counted from the record for the page (2026-10-12).

The Owner, 14:00: «Putem urmări goal-ul de generare câte 2 pe fiecare canal, totul autonom?».
`app.goal.goal_snapshot` reads what the page reads — the publications of the day, the films'
newest walk, their newest quality control report, his open cards — and says per channel what
was published, what is in work and where, what is blocked and whose the wait is; the snapshot
carries it as ``goal``. Every provider faked, nothing bought.
"""

from __future__ import annotations

from uuid import uuid4

from app.decisions.producers.redo_cap import propose_redo_cap_card
from app.goal import TARGET_PER_CHANNEL, goal_snapshot
from app.media.models import MediaAsset
from app.publishing.models import ChannelRecord, PublicationRecord
from app.services import append_event, snapshot, utc_now
from sqlalchemy.orm import Session
from test_director_decides_qc import failed_film
from test_serial_look import serial_board, staffed  # noqa: F401 - the serial storyboard


def _channels(engine) -> dict[str, str]:
    now = utc_now()
    ids = {"MAIN_FACTUAL": str(uuid4()), "OFFICE_SERIAL": str(uuid4())}
    with Session(engine) as session, session.begin():
        session.add(
            ChannelRecord(id=ids["MAIN_FACTUAL"], channel_name="Nexus Curiosity", created_at=now)
        )
        session.add(
            ChannelRecord(
                id=ids["OFFICE_SERIAL"],
                channel_name="Inside The Nexus",
                channel_type="OFFICE_SERIAL",
                created_at=now,
            )
        )
    return ids


def _published_today(engine, channel_id: str, title: str) -> None:
    now = utc_now()
    asset_id = str(uuid4())
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
                duration_seconds=30.0,
                provider_name="SCENE_TAKES",
                license_status="PROPRIETARY_STUDIO",
                provenance_hash="2" * 64,
                created_at=now,
            )
        )
        session.flush()
        session.add(
            PublicationRecord(
                id=str(uuid4()),
                channel_id=channel_id,
                media_asset_id=asset_id,
                title=title,
                description="d",
                status="PUBLISHED",
                idempotency_key=f"pub-{asset_id}",
                published_at=now,
                created_at=now,
            )
        )


def test_the_goal_counts_the_day_per_channel_with_whose_wait_it_is(
    engine,
    monkeypatch,
    staffed,  # noqa: F811 - the fixture
):
    ids = _channels(engine)
    today = utc_now()[:10]
    _published_today(engine, ids["MAIN_FACTUAL"], "How NASA Keeps Webb Alive With Frozen Fuel")
    # A factual film whose repair his cap stopped: his card, so his wait.
    film = failed_film(engine, local_move=False)
    propose_redo_cap_card(
        engine,
        storyboard_id=film["board"],
        report_id=film["report"],
        media_asset_id=film["asset"],
        limited=[{"scene_index": 5, "per_scene": 5, "per_film": 20}],
        rounds={5: 5},
    )
    # The serial's episode on the Director's ladder: in work, hers.
    board_id = serial_board(engine, monkeypatch)
    with Session(engine) as session, session.begin():
        append_event(
            session,
            "runbook.film_state",
            "storyboard",
            board_id,
            1,
            {
                "business_date": today,
                "status": "WAITING",
                "refusal": "NEEDS_OWNER",
                "step": "stills",
                "reason": (
                    "după pasul «imaginile», scena 6 refuzată de controlul calității așteaptă "
                    "rescrierea Directoarei; nu se cumpără din nou până nu o rescrie ea."
                ),
                "moved": True,
            },
            str(uuid4()),
        )

    with Session(engine) as session:
        goal = goal_snapshot(session, day=today)

    assert goal["day"] == today and goal["target_per_channel"] == TARGET_PER_CHANNEL
    factual, serial = goal["channels"]
    assert (
        factual["channel_type"] == "MAIN_FACTUAL" and factual["channel_id"] == ids["MAIN_FACTUAL"]
    )
    assert [item["title"] for item in factual["published"]] == [
        "How NASA Keeps Webb Alive With Frozen Fuel"
    ]
    (blocked,) = factual["blocked"]
    assert blocked["storyboard_id"] == film["board"] and blocked["whose"] == "owner"
    assert blocked["words_ro"].startswith("cardul tău: ")
    assert "limita de refaceri plătite" in blocked["words_ro"]
    assert factual["in_work"] == []
    assert serial["channel_type"] == "OFFICE_SERIAL" and serial["published"] == []
    (working,) = serial["in_work"]
    assert working["storyboard_id"] == board_id and working["whose"] == "director"
    assert "rescrierea Directoarei" in working["words_ro"]
    assert serial["blocked"] == [] and serial["next_episode"] is None
    assert goal["words_ro"] == (
        f"Azi ({today}): shorturi 1/2, episoade 0/2 publicate; 1 în lucru; 1 așteaptă decizia ta."
    )


def test_the_snapshot_carries_the_goal_and_never_fails_on_it(engine):
    reading = snapshot(engine)
    assert "goal" in reading
    assert reading["goal"].get("channels") is not None or reading["goal"] == {}
    assert reading["goal"]["words_ro"].startswith("Azi (")
    kinds = [channel["channel_type"] for channel in reading["goal"]["channels"]]
    assert kinds == ["MAIN_FACTUAL", "OFFICE_SERIAL"]
