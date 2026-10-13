"""The day's headline counts the film a legacy run published.

The runbook reads a stored run back (`app.runbook.services.stored_summary`). The
publish stage has returned its films under a nested ``published`` list since Phase B/C; a run
recorded before that carries the one publication flat, as ``publication_id`` and
``publication_status``. The 12.09 run of the Owner's studio is one of those: its publication
0000010e is PUBLISHED on YouTube, yet the headline read «Niciun film publicat azi», because only
the nested key was counted. A legacy publish artefact is now read by the keys it has.
"""

from __future__ import annotations

from typing import Any

from app.runbook.services import produced_by, run_summary, stored_summary


def _publish(artefacts: dict[str, Any], status: str = "COMPLETED") -> dict[str, Any]:
    return {"stage": "publish", "status": status, "artefacts": artefacts}


LEGACY_PUBLISHED = {
    "publication_id": "00000000-0000-4000-8000-00000000010e",
    "publication_status": "PUBLISHED",
    "title": "How ATLAS Caught the Higgs Boson in Real Time",
}


def test_a_legacy_publish_artefact_counts_its_one_publication() -> None:
    assert produced_by(_publish(LEGACY_PUBLISHED)) == 1


def test_a_legacy_scheduled_or_confirmed_film_is_on_the_channel_and_counts() -> None:
    for status in ("REMOTE_CONFIRMED", "SCHEDULED"):
        assert produced_by(_publish({**LEGACY_PUBLISHED, "publication_status": status})) == 1


def test_a_legacy_publication_that_did_not_go_out_counts_nothing() -> None:
    for status in ("PUBLISHED_SIMULATED", "FAILED", "BLOCKED", "VALIDATED", "", None):
        artefacts = {**LEGACY_PUBLISHED, "publication_status": status}
        assert produced_by(_publish(artefacts)) == 0, status
    # a status with no publication behind it is not a film either
    assert produced_by(_publish({"publication_status": "PUBLISHED"})) == 0


def test_the_nested_list_of_a_current_run_is_counted_as_before_and_not_twice() -> None:
    two = [
        {"publication_id": "a", "publication_status": "PUBLISHED"},
        {"publication_id": "b", "publication_status": "SCHEDULED"},
    ]
    # the current stage also repeats the first film flat beside the list
    current = {"published": two, "publication_id": "a", "publication_status": "PUBLISHED"}
    assert produced_by(_publish(current)) == 2
    assert produced_by(_publish({"published": []})) == 0


def test_a_day_that_published_nothing_still_says_so() -> None:
    refused = {"not_published": [{"asset_id": "x", "status": "COMPLETED"}]}
    assert produced_by(_publish(refused)) == 0
    summary, _ = run_summary([{**_publish(refused), "produced": 0}])
    assert summary.endswith("Niciun film publicat azi.")


def test_the_stored_12_09_run_now_reads_true() -> None:
    """The captured newest run, as `/runbook/runs` reads it back (no stored counts).

    W34: a run stored before the counts is no longer recounted from today's artefact keys,
    which it never wrote; it says it was not counted, and keeps the one film its legacy
    publish artefact names (`tests/test_run_before_counts.py`)."""
    stages = [
        {"stage": "preflight", "status": "COMPLETED", "artefacts": {"status": "READY"}},
        {"stage": "idea_generation", "status": "COMPLETED", "artefacts": {"pool": 6}},
        {"stage": "media", "status": "COMPLETED", "artefacts": {"assets": ["000001dd"]}},
        _publish(LEGACY_PUBLISHED),
    ]
    told = stored_summary(stages)
    summary = told["summary"]
    assert "Filme publicate: 1." in summary
    assert "Niciun film publicat azi." not in summary
    assert "«publish»" not in summary
    assert summary.startswith("Rulare dinainte de numărătoare: ")
    assert told["summary_code"] == "before_counts"
    assert told["stages_productive"] is None


# ------------------------------------------------------- publishing truth (2026-10-02) --
#
# PUB-02: the publish stage returned a film as "published" whatever the upload came back as,
# so a FAILED_FINAL upload read «Filme publicate: 1.», its channel counted as served for the
# day, and the candidate query kept the film out for good (any publication row but
# BLOCKED_GATE excluded it). Only a film that is on the channel, or on its way there under a
# release time, is published; a failed one is offered again the next day.

from pathlib import Path  # noqa: E402
from uuid import uuid4  # noqa: E402

from app.models import OwnerPolicy  # noqa: E402
from app.providers.deterministic_pub import DeterministicPublishingAdapter  # noqa: E402
from app.providers.publishing_base import UploadResult  # noqa: E402
from app.publishing.models import PublicationRecord  # noqa: E402
from app.runbook import stages  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from test_daily_run_stages import (  # noqa: E402
    _bound,
    _connected,
    _director_and_publisher_agree,
    _seeded_channels,
)
from test_phase6_publishing import _create_verified_asset_bundle  # noqa: E402


def test_a_failed_upload_in_the_published_list_counts_nothing() -> None:
    failed = {
        "published": [
            {"publication_id": "a", "publication_status": "FAILED_FINAL"},
            {"publication_id": "b", "publication_status": "REMOTE_UNKNOWN"},
            {"publication_id": "c", "publication_status": "FAILED_RETRYABLE"},
        ]
    }
    assert produced_by(_publish(failed)) == 0
    summary, _ = run_summary([{**_publish(failed), "produced": produced_by(_publish(failed))}])
    assert "Filme publicate: 1." not in summary
    # The studio's own simulator in TEST is the film the test studio made, as before.
    simulated = {
        "published": [{"publication_id": "s", "publication_status": "PUBLISHED_SIMULATED"}]
    }
    assert produced_by(_publish(simulated)) == 1


class ScriptedPublisher(DeterministicPublishingAdapter):
    """The simulator, answering each upload with the next scripted status."""

    def __init__(self, outcomes: list[str]) -> None:
        super().__init__()
        self.outcomes = list(outcomes)
        self.uploads: list[str] = []

    async def upload_video(self, file_path: Path, **kwargs: Any) -> UploadResult:
        self.uploads.append(str(kwargs.get("title")))
        outcome = self.outcomes.pop(0) if self.outcomes else "CONFIRMED"
        if outcome == "CONFIRMED":
            return await super().upload_video(file_path, **kwargs)
        return UploadResult(
            remote_video_id="",
            remote_url="",
            status=outcome,
            error_detail="YouTube a refuzat încărcarea (test).",
        )


def _studio(engine, tmp_path, monkeypatch, publisher) -> str:
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).autonomy_stopped = False
    channels = _seeded_channels(engine)
    main = channels["MAIN_FACTUAL"]["id"]
    _bound(engine, main, _connected(engine, "Main account"))
    monkeypatch.setattr("app.runbook.stages.selected_youtube", lambda *a, **k: publisher)
    _director_and_publisher_agree(monkeypatch)
    return main


def _statuses(engine) -> list[str]:
    with Session(engine) as session:
        return [
            row.status
            for row in session.scalars(
                select(PublicationRecord).order_by(PublicationRecord.created_at)
            )
        ]


def test_a_failed_upload_is_not_published_and_leaves_its_channel_open(
    engine, tmp_path, monkeypatch
) -> None:
    publisher = ScriptedPublisher(["FAILED", "CONFIRMED"])
    _studio(engine, tmp_path, monkeypatch, publisher)
    _create_verified_asset_bundle(engine, tmp_path / "one")
    _create_verified_asset_bundle(engine, tmp_path / "two")

    outcome = stages._publish(engine, None)

    published = outcome["artefacts"]["published"]
    assert [p["publication_status"] for p in published] == ["PUBLISHED_SIMULATED"]
    # The channel was not served by the failure: the second film went out the same day.
    assert len(publisher.uploads) == 2
    failed = [n for n in outcome["artefacts"]["not_published"] if n.get("publication_status")]
    assert failed and failed[0]["publication_status"] == "FAILED_FINAL"
    assert "nu a urcat" in failed[0]["reason"]
    assert produced_by({"stage": "publish", **outcome}) == 1


def test_a_film_whose_upload_failed_is_offered_again_the_next_day(
    engine, tmp_path, monkeypatch
) -> None:
    publisher = ScriptedPublisher(["FAILED"])
    _studio(engine, tmp_path, monkeypatch, publisher)
    _create_verified_asset_bundle(engine, tmp_path / "one")

    first = stages._publish(engine, None)
    assert first["artefacts"].get("published", []) == []
    assert produced_by({"stage": "publish", **first}) == 0
    assert first["status"] == "COMPLETED"

    second = stages._publish(engine, None)
    assert [p["publication_status"] for p in second["artefacts"]["published"]] == [
        "PUBLISHED_SIMULATED"
    ]
    assert _statuses(engine) == ["FAILED_FINAL", "PUBLISHED_SIMULATED"]


def test_a_retryable_failure_is_the_watchdogs_and_is_not_uploaded_twice_by_the_day(
    engine, tmp_path, monkeypatch
) -> None:
    """FAILED_RETRYABLE is retried by the watchdog on the same row, after asking the channel
    whether the first attempt landed; a second intent from the day beside it could put the
    film up twice."""
    publisher = ScriptedPublisher(["RETRYABLE"])
    _studio(engine, tmp_path, monkeypatch, publisher)
    _create_verified_asset_bundle(engine, tmp_path / "one")

    stages._publish(engine, None)
    stages._publish(engine, None)

    assert len(publisher.uploads) == 1
    assert _statuses(engine) == ["FAILED_RETRYABLE"]


def test_a_film_youtube_rejected_is_not_offered_again(engine, tmp_path, monkeypatch) -> None:
    publisher = ScriptedPublisher([])
    channel_id = _studio(engine, tmp_path, monkeypatch, publisher)
    bundle = _create_verified_asset_bundle(engine, tmp_path / "one")
    from app.services import utc_now  # noqa: PLC0415

    with Session(engine) as session, session.begin():
        session.add(
            PublicationRecord(
                id=str(uuid4()),
                channel_id=channel_id,
                media_asset_id=bundle["asset_id"],
                title="Rejected",
                description="",
                tags_json=[],
                privacy_status="private",
                status="FAILED_FINAL",
                idempotency_key=str(uuid4()),
                remote_video_id="yt-rejected",
                remote_upload_status="rejected",
                error_detail="YouTube a respins videoclipul (duplicate).",
                created_at=utc_now(),
            )
        )

    stages._publish(engine, None)

    assert publisher.uploads == []
