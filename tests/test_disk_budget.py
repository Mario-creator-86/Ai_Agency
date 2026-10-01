"""A film's disk: compact intermediates, released once quality control has read them.

Measured 2026-10-01: a lossless shot intermediate (x264 -qp 0) was about 235 MB per 8.6 s shot
at 1080x1920, about 1.1 GB a film, and the suite had left about 1,080 test films (321 GB) in
the studio's real media folder. In production every render kept its intermediates forever.

- a shot (and a composed card's clip) is a compact, visually lossless intermediate (x264
  High, CRF 4; test_encode_spec.py measures it), about half a lossless one;
- once a film's quality-control report is recorded, its intermediates (each scene's shot and
  each card clip) are deleted; the vendor takes, the stills, the film, its captions and its
  sound stay;
- a per-scene redo or a rejoin re-derives the shots it needs from the takes they were made
  from, at 0 credits, with no adapter asked;
- a typical film test (six scenes, every vendor faked) writes at most about 150 MB, and
  nothing under the studio's own backend/storage/media.

Every provider is faked: spy adapters count their calls. No socket is opened (conftest refuses
them).
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import uuid4

import pytest
from app.media import assembler
from app.media.assembler import (
    assemble_video_job,
    redo_scene,
    release_intermediates,
    release_reviewed_intermediates,
)
from app.media.models import VideoRenderJob
from app.media.qc import evaluate_media_qc
from app.media.toolchain import ROOT, find_ffmpeg
from app.models import DomainEvent
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from test_motion import a_clip
from test_scene_redo import a_rendered_nepal_film, approvals, takes
from test_scene_takes import SpyImages, SpyMotion, nepal_like

pytestmark = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")

#: The studio's real media folder, never the per-test one conftest patches in.
STUDIO_MEDIA = ROOT / "backend" / "storage" / "media"
#: What a typical six-scene film test may write, all of it.
FILM_TEST_BUDGET_BYTES = 150 * 1024 * 1024


def sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def written(folder: Path) -> int:
    return sum(path.stat().st_size for path in folder.rglob("*") if path.is_file())


def names(folder: Path) -> set[str]:
    return {path.name for path in folder.iterdir() if path.is_file()}


def job_of(engine, asset_id: str) -> VideoRenderJob:
    with Session(engine) as session:
        job = session.scalar(
            select(VideoRenderJob).where(VideoRenderJob.output_asset_id == asset_id)
        )
        session.expunge_all()
        return job


def released_events(engine) -> list[DomainEvent]:
    with Session(engine) as session:
        rows = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.intermediates_released")
        ).all()
        session.expunge_all()
        return list(rows)


def intermediates(folder: Path) -> set[str]:
    return {name for name in names(folder) if name.startswith("shot_") or name.startswith("card_")}


# ------------------------------------------------------------ 1. what a film test writes


@pytest.mark.parametrize("moving", [True, False], ids=["vendor_clips", "stills_pushed_in"])
def test_a_six_scene_film_test_writes_at_most_150_mb_and_nothing_in_the_studio_folder(
    engine, tmp_path, moving
):
    before = sorted(p.name for p in STUDIO_MEDIA.iterdir()) if STUDIO_MEDIA.is_dir() else []
    if moving:
        storyboard_id, render, _images, _motion = a_rendered_nepal_film(engine, tmp_path)
    else:
        # The heaviest intermediates: every LIVE scene a real Nepal still given the push-in.
        storyboard_id = nepal_like(engine, tmp_path)
        render = assemble_video_job(
            engine,
            storyboard_id,
            str(uuid4()),
            storage_root=tmp_path / "media",
            image_adapter=SpyImages(),
            environment="TEST",
        )

    media = tmp_path / "media"
    assert Path(render["file_path"]).is_relative_to(media)
    assert written(media) <= FILM_TEST_BUDGET_BYTES, written(media)
    assert not (STUDIO_MEDIA / storyboard_id).exists()
    after = sorted(p.name for p in STUDIO_MEDIA.iterdir()) if STUDIO_MEDIA.is_dir() else []
    assert after == before, "a film test wrote into the studio's own media folder"

    # Every shot is the compact intermediate, never a lossless one.
    folder = Path(render["file_path"]).parent
    for record in render["production"]["shots"]:
        data = (folder / record["file"]).read_bytes()
        assert b" crf=4.0 " in data and b" qp=0 " not in data, record["file"]


# --------------------------------------- 2. the intermediates go once QC has read them


def test_the_intermediates_go_once_the_qc_report_is_recorded_and_the_rest_stays(engine, tmp_path):
    storyboard_id, render, _images, _motion = a_rendered_nepal_film(engine, tmp_path)
    folder = Path(render["file_path"]).parent
    asset_id = render["output_asset_id"]
    shots = {record["file"] for record in render["production"]["shots"]}
    cards = {
        Path(entry["card"]["path"]).name
        for entry in render["production"]["scenes"]
        if isinstance(entry.get("card"), dict)
    }
    assert len(shots) == 6 and cards == {"card_05.mp4", "card_06.mp4"}
    assert shots | cards <= names(folder)
    kept_before = names(folder) - shots - cards

    # Nothing goes before quality control has read the film: QC reads the shots.
    early = release_intermediates(engine, asset_id, str(uuid4()))
    assert early["status"] == "NO_QC_REPORT" and early["files"] == []
    assert shots | cards <= names(folder)

    evaluate_media_qc(engine, asset_id, str(uuid4()))
    size_before = written(folder)
    result = release_intermediates(engine, asset_id, str(uuid4()))

    assert result["status"] == "RELEASED"
    assert set(result["files"]) == shots | cards
    assert intermediates(folder) == set()
    assert names(folder) == kept_before
    assert result["bytes"] == size_before - written(folder) > 0
    # Kept: the film, its captions, its sound (the joined voice and the master), the stills
    # and the vendor clips (the faked voice here is the placeholder: no voice takes).
    kept = names(folder)
    assert Path(render["file_path"]).name in kept
    assert {
        "captions.srt",
        "captions.ass",
        assembler.VOICE_TRACK_NAME,
        assembler.MASTERED_TRACK_NAME,
    } <= kept
    assert {f"motion_{n:02d}.mp4" for n in range(1, 5)} <= kept
    for take in takes(engine, storyboard_id):
        assert Path(str(take.path)).is_file(), take.kind

    (event,) = released_events(engine)
    assert event.aggregate_id == asset_id
    assert sorted(event.payload["files"]) == sorted(shots | cards)
    assert event.payload["bytes"] == result["bytes"]

    # Once released, a second call finds nothing more and records nothing more.
    again = release_intermediates(engine, asset_id, str(uuid4()))
    assert again["status"] == "ALREADY_RELEASED" and again["files"] == []
    assert len(released_events(engine)) == 1


def test_the_next_render_releases_every_reviewed_film_and_the_sweep_runs_once(engine, tmp_path):
    _first_id, first, _images, _motion = a_rendered_nepal_film(engine, tmp_path)
    first_folder = Path(first["file_path"]).parent
    evaluate_media_qc(engine, first["output_asset_id"], str(uuid4()))
    assert intermediates(first_folder), "nothing to release"

    # Another film is rendered: the studio sweeps every reviewed film's intermediates first.
    second_id = nepal_like(engine, tmp_path / "second")
    second = assemble_video_job(
        engine,
        second_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=SpyImages(),
        video_adapter_for_scene=lambda scene: SpyMotion(a_clip(tmp_path)),
    )
    assert intermediates(first_folder) == set()
    # The new film has not been read by QC yet: its shots stay.
    assert intermediates(Path(second["file_path"]).parent)
    assert [e.aggregate_id for e in released_events(engine)] == [first["output_asset_id"]]

    assert release_reviewed_intermediates(engine, str(uuid4())) == []
    evaluate_media_qc(engine, second["output_asset_id"], str(uuid4()))
    (swept,) = release_reviewed_intermediates(engine, str(uuid4()))
    assert swept["asset_id"] == second["output_asset_id"] and swept["status"] == "RELEASED"
    assert intermediates(Path(second["file_path"]).parent) == set()


def test_a_newer_film_waiting_for_qc_keeps_the_shots_it_shares(engine, tmp_path):
    storyboard_id, first, images, motion = a_rendered_nepal_film(engine, tmp_path)
    # The same storyboard rendered again from the same takes: the same shot files, rebuilt.
    second = assemble_video_job(
        engine,
        storyboard_id,
        str(uuid4()),
        storage_root=tmp_path / "media",
        image_adapter=images,
        video_adapter_for_scene=lambda scene: motion,
    )
    folder = Path(second["file_path"]).parent
    shared = {record["file"] for record in second["production"]["shots"]}
    evaluate_media_qc(engine, first["output_asset_id"], str(uuid4()))

    result = release_intermediates(engine, first["output_asset_id"], str(uuid4()))

    assert result["status"] == "RELEASED"
    assert shared <= names(folder), "a film QC has not read yet lost its shots"
    assert {item["file"] for item in result["kept"]} >= shared
    assert all(item["reason"] for item in result["kept"])


def test_a_film_whose_shots_cannot_be_rederived_keeps_them(engine, tmp_path):
    """A render from before this change recorded no source for its shots: deleting them would
    leave a redo nothing to rejoin, so they stay."""
    _storyboard_id, render, _images, _motion = a_rendered_nepal_film(engine, tmp_path)
    folder = Path(render["file_path"]).parent
    with Session(engine) as session, session.begin():
        job = session.get(VideoRenderJob, render["job_id"])
        for record in job.production_json["shots"]:
            record.pop("source", None)
        flag_modified(job, "production_json")
    evaluate_media_qc(engine, render["output_asset_id"], str(uuid4()))

    result = release_intermediates(engine, render["output_asset_id"], str(uuid4()))

    shots = {record["file"] for record in render["production"]["shots"]}
    assert shots <= names(folder)
    assert shots <= {item["file"] for item in result["kept"]}


# ------------------------------------- 3. a redo after the release re-derives, for nothing


def test_a_card_redo_after_the_release_rederives_every_other_shot_at_zero_credits(engine, tmp_path):
    storyboard_id, render, images, motion = a_rendered_nepal_film(engine, tmp_path)
    folder = Path(render["file_path"]).parent
    recorded = {int(r["scene_index"]): r["sha256"] for r in render["production"]["shots"]}
    evaluate_media_qc(engine, render["output_asset_id"], str(uuid4()))
    release_intermediates(engine, render["output_asset_id"], str(uuid4()))
    assert intermediates(folder) == set()
    asked_before = (len(images.asked), len(motion.asked))
    takes_before = len(takes(engine, storyboard_id))

    result = redo_scene(engine, storyboard_id, str(uuid4()), kind="card", scene_index=5)

    assert result["credits"] == 0
    assert (len(images.asked), len(motion.asked)) == asked_before, "a vendor was asked"
    assert len(takes(engine, storyboard_id)) == takes_before
    assert approvals(engine) == []
    film = result["film"]
    assert film["reused_shots"] == [1, 2, 3, 4, 6] and film["rebuilt_shots"] == [5]
    assert film["rederived_shots"] == [1, 2, 3, 4, 6]
    assert Path(film["file_path"]).is_file()
    job = job_of(engine, film["output_asset_id"])
    assert job.production_json["remaster"]["rederived_shots"] == [1, 2, 3, 4, 6]
    shots = {int(r["scene_index"]): r for r in job.production_json["shots"]}
    for n in (1, 2, 3, 4, 6):
        path = folder / shots[n]["file"]
        assert path.is_file() and sha(path) == shots[n]["sha256"]
        # Re-derived from the same takes by the same encoder: the very bytes it had.
        assert shots[n]["sha256"] == recorded[n], f"shot {n} came back different"
        assert shots[n]["source"], f"shot {n} lost its source"
    assert shots[5]["source"]["card"] is True

    # The rejoined film is itself released once QC has read it, and can be redone again.
    evaluate_media_qc(engine, film["output_asset_id"], str(uuid4()))
    assert release_intermediates(engine, film["output_asset_id"], str(uuid4()))["files"]
    again = redo_scene(engine, storyboard_id, str(uuid4()), kind="card", scene_index=6)
    assert again["film"]["rederived_shots"] == [1, 2, 3, 4, 5]


def test_a_rejoin_whose_source_is_gone_is_refused_in_romanian(engine, tmp_path):
    storyboard_id, render, _images, _motion = a_rendered_nepal_film(engine, tmp_path)
    folder = Path(render["file_path"]).parent
    evaluate_media_qc(engine, render["output_asset_id"], str(uuid4()))
    release_intermediates(engine, render["output_asset_id"], str(uuid4()))
    shot_2 = next(r for r in render["production"]["shots"] if r["scene_index"] == 2)
    clip = Path(shot_2["source"]["clip"])
    clip = clip if clip.is_absolute() else folder / clip
    clip.write_bytes(b"not the clip the shot was cut from")
    # The take it was copied from is gone too.
    for take in takes(engine, storyboard_id):
        if take.scene_number == 2 and take.kind in ("motion", "test_shot"):
            Path(str(take.path)).write_bytes(b"gone")

    with pytest.raises(assembler.SceneRedoRefused) as refused:
        redo_scene(engine, storyboard_id, str(uuid4()), kind="card", scene_index=5)

    assert refused.value.status == "NO_SHOTS"
    assert "Scena 2" in refused.value.reason_ro or "scenei 2" in refused.value.reason_ro
