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
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from test_motion import a_clip
from test_scene_redo import a_rendered_nepal_film, approvals, takes
from test_scene_takes import SpyImages, SpyMotion, nepal_like

#: The film tests need the encoder; the media root, free-space and sweep tests below do not.
needs_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")

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


@needs_ffmpeg
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


@needs_ffmpeg
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


@needs_ffmpeg
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


@needs_ffmpeg
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


@needs_ffmpeg
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


@needs_ffmpeg
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


@needs_ffmpeg
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


# ------------------------------------- 2. the media root, the free-space guard, the sweep
#
# 2026-10-02 (REL-08): the media folder was a constant inside the repository (299 GiB measured
# in backend/storage/media), nothing measured the free space before a paid step, and a render
# that failed before quality control kept its shots for ever. The tests below need no encoder.

GB = 1024**3


def low_disk(monkeypatch, free_gb: float = 5.0) -> None:
    """The media disk, as `app.media.disk` reads it, with only ``free_gb`` left."""
    from app.media import disk

    monkeypatch.setattr(disk, "free_bytes", lambda _path: int(free_gb * GB))


def test_the_media_root_setting_is_honoured_by_the_page_the_day_and_the_watchdog(
    settings, engine, tmp_path, monkeypatch
):
    from app.integrations.vault import CredentialVault
    from app.main import create_app
    from app.runbook.stages import sheet_wiring
    from app.workflows import watchdog
    from fastapi.testclient import TestClient

    films = tmp_path / "films_elsewhere"
    moved = settings.model_copy(update={"media_root": films})

    assert assembler.media_root(moved) == films
    assert assembler.media_root(settings) == assembler.DEFAULT_STORAGE_ROOT
    assert assembler.media_root(None) == assembler.DEFAULT_STORAGE_ROOT

    with TestClient(create_app(moved)) as client:
        assert client.app.app.state.media_storage_root == films
    with TestClient(create_app(settings)) as client:
        assert getattr(client.app.app.state, "media_storage_root", None) is None

    vault = CredentialVault(tmp_path / "wiring.credentials.key")
    assert sheet_wiring(engine, vault, moved)["storage_root"] == films

    seen: list = []

    def spy(_engine, **kwargs):
        seen.append(kwargs.get("storage_root"))
        return []

    monkeypatch.setattr(assembler, "collect_submitted_takes", spy)
    with engine.begin() as connection:
        connection.execute(text("UPDATE owner_policy SET autonomy_stopped = 0"))
    watchdog.run_watchdog(engine, moved, collector_for=lambda _take: None)
    assert seen == [films]


def test_a_relative_media_root_is_read_from_the_studio_folder():
    from app.config import Settings

    relative = Settings(_env_file=None, owner_token="x" * 48, media_root="films")
    assert relative.media_root == ROOT / "films"


def test_every_call_into_a_media_step_names_its_storage_root():
    """A call that leaves storage_root out writes into the default folder whatever the
    Owner set: the AST scan names it. A call that forwards **kwargs passes it on."""
    import ast

    app_dir = ROOT / "backend" / "app"
    #: function name -> the position storage_root may be passed at (None: keyword only)
    takes_root: dict[str, int | None] = {}
    trees = {}
    for path in app_dir.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        trees[path] = tree
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name != "__init__":
                positional = [a.arg for a in node.args.args]
                if "storage_root" in positional:
                    takes_root[node.name] = positional.index("storage_root")
                elif "storage_root" in [a.arg for a in node.args.kwonlyargs]:
                    takes_root[node.name] = None
            elif isinstance(node, ast.ClassDef):
                for method in node.body:
                    if not isinstance(method, ast.FunctionDef) or method.name != "__init__":
                        continue
                    positional = [a.arg for a in method.args.args][1:]
                    if "storage_root" in positional:
                        takes_root[node.name] = positional.index("storage_root")
                    elif "storage_root" in [a.arg for a in method.args.kwonlyargs]:
                        takes_root[node.name] = None
    missing = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
            if name not in takes_root:
                continue
            keywords = {k.arg for k in node.keywords}
            if "storage_root" in keywords or None in keywords:
                continue
            position = takes_root[name]
            if position is not None and len(node.args) > position:
                continue
            missing.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno} {name}")
    assert missing == [], missing


def test_the_preflight_blocks_the_day_under_the_minimum_free_space(settings, engine, monkeypatch):
    from app.runbook.preflight import run_preflight

    low_disk(monkeypatch, 5.0)
    settings = settings.model_copy(update={"min_free_gb": 20.0})
    result = run_preflight(engine, settings, None)
    line = next(check for check in result["checks"] if check["name"] == "disk_space")
    assert result["status"] == "BLOCKED"
    assert "disk_space" in result["blocking_failures"]
    assert line["ok"] is False and line["code"] == "disk_space.low"
    assert "5 GB" in line["message"] and "20 GB" in line["message"]
    assert "STUDIO_MIN_FREE_GB" in line["technical"]["settings"]

    plenty = settings.model_copy(update={"min_free_gb": 0})
    again = run_preflight(engine, plenty, None)
    assert next(c for c in again["checks"] if c["name"] == "disk_space")["ok"] is True


def test_a_paid_motion_step_buys_nothing_under_the_minimum_free_space(
    settings, engine, tmp_path, monkeypatch
):
    from app.media.assembler import MotionStepRefused
    from app.models import ApprovalRequest
    from test_film_costing import Account, Models, SpyVideo
    from test_film_costing import a_film as costing_film
    from test_film_costing import run as motion_run

    storyboard_id = costing_film(engine, tmp_path, scenes=2)
    account = Account(10_000)
    models = Models(SpyVideo("seedance2_5", account))
    low_disk(monkeypatch, 5.0)
    settings = settings.model_copy(update={"min_free_gb": 20.0})
    with pytest.raises(MotionStepRefused) as refused:
        motion_run(engine, storyboard_id, tmp_path, "test_shot", models, account, settings=settings)
    assert refused.value.status == "LOW_DISK" and refused.value.http_status == 409
    assert "GB" in refused.value.reason_ro and "spațiu" in refused.value.reason_ro
    assert models.posts() == 0
    with Session(engine) as session:
        assert session.scalars(select(ApprovalRequest)).all() == [], "he was asked anyway"


def test_a_paid_stills_step_buys_nothing_under_the_minimum_free_space(
    engine, tmp_path, monkeypatch
):
    from app.media.stills_stage import StillsStageRefused
    from test_stills_stage import SpyJudge, SpyStills
    from test_stills_stage import a_film as stills_film
    from test_stills_stage import run as stills_run

    storyboard_id = stills_film(engine, tmp_path)
    adapter = SpyStills(balance=10_000)
    low_disk(monkeypatch, 2.0)
    # The stills step is not handed the settings: it reads STUDIO_MIN_FREE_GB itself.
    monkeypatch.setenv("STUDIO_MIN_FREE_GB", "20")
    with pytest.raises(StillsStageRefused) as refused:
        stills_run(engine, storyboard_id, tmp_path, adapter, SpyJudge())
    assert refused.value.status == "LOW_DISK"
    assert adapter.asked == []


def test_the_day_waits_on_a_full_disk_and_the_next_film_would_too():
    from app.runbook.stages import ACCOUNT_WIDE, OWNER_DECIDES, _letter_headline

    assert "LOW_DISK" in OWNER_DECIDES and "LOW_DISK" in ACCOUNT_WIDE
    headline, follow = _letter_headline("WAITING", "LOW_DISK", "imaginile")
    assert "spațiu" in headline and "disc" in follow


def _failed_render(engine, storyboard_id: str, *, age_days: float, status: str = "FAILED"):
    from datetime import UTC, datetime, timedelta

    stamp = (datetime.now(UTC) - timedelta(days=age_days)).isoformat()
    with Session(engine) as session, session.begin():
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=storyboard_id,
                status=status,
                render_engine="ffmpeg",
                command_args_json=[],
                production_json={},
                started_at=stamp,
                finished_at=stamp if status == "FAILED" else None,
            )
        )


def _film_folder(root: Path, storyboard_id: str, *, age_days: float) -> Path:
    import os
    import time

    folder = root / storyboard_id
    (folder / "motion").mkdir(parents=True)
    (folder / "stills").mkdir()
    files = [
        folder / "shot_01.mp4",
        folder / "shot_02_redo_20260901.mp4",
        folder / "card_03.mp4",
        folder / "final_short_9_16.mp4",
        folder / "master_audio.wav",
        folder / "motion" / "take_01.mp4",
        folder / "stills" / "scene_01.png",
    ]
    old = time.time() - age_days * 86400
    for path in files:
        path.write_bytes(b"x" * 1000)
        os.utime(path, (old, old))
    return folder


def test_the_failed_render_sweep_is_off_until_the_owner_turns_it_on(
    settings, engine, tmp_path, private_media_storage
):
    from app.workflows.watchdog import run_watchdog

    root = private_media_storage["DEFAULT_STORAGE_ROOT"]
    storyboard_id = nepal_like(engine, tmp_path)
    folder = _film_folder(root, storyboard_id, age_days=10)
    _failed_render(engine, storyboard_id, age_days=10)
    with engine.begin() as connection:
        connection.execute(text("UPDATE owner_policy SET autonomy_stopped = 0"))

    result = run_watchdog(engine, settings, collector_for=lambda _take: None)
    assert result["intermediates"]["status"] == "OFF"
    assert (folder / "shot_01.mp4").is_file()

    on = settings.model_copy(update={"sweep_failed_intermediates": True})
    result = run_watchdog(engine, on, collector_for=lambda _take: None)
    swept = result["intermediates"]
    assert swept["status"] == "SWEPT"
    assert sorted(swept["files"]) == sorted(
        [
            f"{storyboard_id}/shot_01.mp4",
            f"{storyboard_id}/shot_02_redo_20260901.mp4",
            f"{storyboard_id}/card_03.mp4",
        ]
    )
    assert swept["bytes"] == 3000
    # Never a take, a still, the film or its sound.
    assert names(folder) == {"final_short_9_16.mp4", "master_audio.wav"}
    assert (folder / "motion" / "take_01.mp4").is_file()
    assert (folder / "stills" / "scene_01.png").is_file()
    with Session(engine) as session:
        events = session.scalars(
            select(DomainEvent).where(
                DomainEvent.event_type == assembler.FAILED_INTERMEDIATES_SWEPT_EVENT
            )
        ).all()
    assert len(events) == 1 and events[0].aggregate_id == storyboard_id


def test_the_sweep_leaves_recent_failures_and_films_still_rendering(
    settings, engine, tmp_path, private_media_storage
):
    root = private_media_storage["DEFAULT_STORAGE_ROOT"]
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    recent = nepal_like(engine, tmp_path / "a")
    rendering = nepal_like(engine, tmp_path / "b")
    recent_folder = _film_folder(root, recent, age_days=2)
    _failed_render(engine, recent, age_days=2)
    busy_folder = _film_folder(root, rendering, age_days=10)
    _failed_render(engine, rendering, age_days=10)
    _failed_render(engine, rendering, age_days=0, status="RENDERING")

    result = assembler.sweep_failed_intermediates(
        engine, storage_root=root, older_than_days=7, correlation_id="sweep"
    )
    assert result["files"] == []
    assert (recent_folder / "shot_01.mp4").is_file() and (busy_folder / "shot_01.mp4").is_file()


def _inventory():
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location(
        "media_inventory", ROOT / "scripts/media_inventory.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["media_inventory"] = module
    spec.loader.exec_module(module)
    return module


def test_the_media_inventory_is_a_dry_run_unless_the_owner_says_delete(engine, tmp_path, capsys):
    root = tmp_path / "media"
    known = nepal_like(engine, tmp_path)
    orphan = str(uuid4())
    for folder in (root / known, root / orphan, root / "rehearsal_copy"):
        folder.mkdir(parents=True)
        (folder / "final_short_9_16.mp4").write_bytes(b"x" * 2048)
    database = str(engine.url.database)
    inventory = _inventory()

    code = inventory.main(["--database", database, "--media-root", str(root)])
    out = capsys.readouterr().out
    assert code == 0
    orphans_part = out.split("Fără film în baza de date")[-1]
    assert orphan in orphans_part and known not in orphans_part
    assert "rehearsal_copy" in out  # named as not a film folder, never deleted
    assert (root / orphan).is_dir(), "a dry run deleted something"

    code = inventory.main(["--database", database, "--media-root", str(root), "--delete"])
    assert code == 0
    assert not (root / orphan).exists()
    assert (root / known).is_dir() and (root / "rehearsal_copy").is_dir()
