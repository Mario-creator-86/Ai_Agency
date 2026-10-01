"""The zero-credit Nepal rehearsal: the film rebuilt from the files already paid for.

The Nepal film cost over 1,000 credits and failed quality control. Its stills, one usable
clip and its narration are on disk, paid for. The first step of the fix costs nothing: adopt
those files as takes, compose the chart and the black screen locally from the verified numbers,
master the sound and encode again, and run quality control on what comes out.

What is asserted here, with no provider reachable (conftest refuses every non-loopback socket,
and every place a vendor could be reached from is replaced by a spy that fails when asked):
  - adopting a copy of the media folder writes one take per paid file, each with its sha256:
    the clean stills APPROVED, the clip that starts from its still PAID, the clip that starts
    from a picture no longer on disk REJECTED, the stills of the two card scenes REJECTED;
  - the film is then assembled from those takes with zero vendor calls; scenes 5 and 6 are
    composed cards, the chart carrying the claim numbers 100 and 83;
  - a still with faces (the bible forbids them) is not approved: the sheet lists its scene as
    'necesită o imagine nouă (18 credite)' and nothing is bought;
  - only a copy is written: the original folder and data/studio.db are never touched;
  - POST /api/v1/media/storyboards/{id}/adopt-existing-files is the Owner's and costs 0.

The stills are the delivered Nepal pictures (tests/fixtures/nepal_1d530880, 540x960), scaled to
1080x1920 and lightly sharpened so the sharpness floor reads them as the full-size originals
read (592-893); the face detector is the real YuNet, which counts 3 faces in scene 3 and 1 in
scene 4 here, as it does on the delivered PNGs.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from app.factual.models import FactualClaim, ScriptDraft, TopicIdea
from app.media.faces import detector_available
from app.media.models import (
    MediaAsset,
    SceneTake,
    Storyboard,
    StoryboardScene,
    VideoRenderJob,
)
from app.media.toolchain import find_ffmpeg, find_ffprobe
from app.models import DomainEvent, OwnerPolicy
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[1]
LIVE_DB = ROOT / "data" / "studio.db"
FIXTURES = Path(__file__).parent / "fixtures" / "nepal_1d530880"
SCRIPT = json.loads((FIXTURES / "script.json").read_text(encoding="utf-8"))
PROMPTS = json.loads((FIXTURES / "prompts.json").read_text(encoding="utf-8"))
NEPAL_ID = "1d530880-c94a-48a1-baf5-6ad7c1796a6d"
#: The chart the new writer gives scene 5: 100 promised, 83 delivered, each from its claim.
CARD = SCRIPT["writer_answer"]["scenes"][4]["card"]
#: Short scenes, so a test film renders in seconds; the shape is the Nepal film's.
PLANNED_SECONDS = 2.0
VOICE_SECONDS = 1.6
STILL_REDO = "necesită o imagine nouă (18 credite)"

requires_ffmpeg = pytest.mark.skipif(
    find_ffmpeg() is None or find_ffprobe() is None, reason="ffmpeg/ffprobe not installed"
)
requires_yunet = pytest.mark.skipif(
    not detector_available(), reason="the YuNet face detector is not installed"
)


# ----------------------------------------------------------------------------- fixtures


def _ffmpeg(*args: str) -> None:
    subprocess.run(
        [str(find_ffmpeg()), "-nostdin", "-v", "error", "-y", *args],
        check=True,
        capture_output=True,
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def media_folder(base: Path) -> Path:
    """A stand-in for backend/storage/media/<Nepal id>, shaped like the real one.

    scene_0N.png are the six delivered stills; motion_01.mp4 starts from scene_01 (render 2's
    hero shot); motion_02.mp4 starts from another picture (render 1's clip, whose still the
    second render overwrote); voice_0N.mp3 are the six narrations; captions.srt is there too.
    """
    folder = base / NEPAL_ID
    folder.mkdir(parents=True)
    for n in range(1, 7):
        _ffmpeg(
            "-i",
            str(FIXTURES / f"scene_{n:02d}.jpg"),
            "-vf",
            "scale=1080:1920:flags=lanczos,unsharp=5:5:1.5",
            str(folder / f"scene_{n:02d}.png"),
        )
    for name, picture in (("motion_01.mp4", "scene_01.png"), ("motion_02.mp4", "scene_05.png")):
        _ffmpeg(
            "-loop",
            "1",
            "-i",
            str(folder / picture),
            "-vf",
            "scale=540:960,zoompan=z='1+0.0008*on':d=72:s=540x960:fps=24",
            "-frames:v",
            "72",
            "-pix_fmt",
            "yuv420p",
            "-c:v",
            "libx264",
            str(folder / name),
        )
    for n in range(1, 7):
        _ffmpeg(
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={180 + 40 * n}:duration={VOICE_SECONDS}",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(folder / f"voice_{n:02d}.mp3"),
        )
    (folder / "captions.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nNepal\n", "utf-8")
    return folder


def nepal_board(engine, folder: Path) -> str:
    """The Nepal storyboard as it is in the Owner's database: six LIVE scenes (it predates
    scene kinds), the template prompts as they were sent, the director's bible that forbids
    faces, the six SUPPORTED claims, and the render whose files are in ``folder``."""
    now = utc_now()
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        if policy:
            policy.autonomy_stopped = False
        session.add(
            TopicIdea(
                id=SCRIPT["topic_id"],
                title=SCRIPT["title"],
                topic="climate",
                angle="Nepal pays a bill it did not run up",
                target_audience="general",
                novelty_score=0.9,
                status="SELECTED",
                created_at=now,
            )
        )
        for claim in SCRIPT["claims"]:
            session.add(
                FactualClaim(
                    id=claim["id"],
                    topic_id=SCRIPT["topic_id"],
                    claim_text=claim["claim_text"],
                    claim_type=claim["claim_type"],
                    importance=claim["importance"],
                    status=claim["status"],
                    confidence=0.95,
                    created_at=now,
                )
            )
        session.add(
            ScriptDraft(
                id=SCRIPT["script_id"],
                topic_id=SCRIPT["topic_id"],
                version=1,
                title=SCRIPT["title"],
                target_duration_seconds=SCRIPT["target_duration_seconds"],
                voiceover_full_text=" ".join(s["narration"] for s in SCRIPT["stored_scenes"]),
                scenes_json=SCRIPT["stored_scenes"],
                status="APPROVED",
                claim_ids_json=[c["id"] for c in SCRIPT["claims"]],
                unverified_claim_ids_json=[],
                created_at=now,
            )
        )
        session.flush()
        session.add(
            Storyboard(
                id=NEPAL_ID,
                script_draft_id=SCRIPT["script_id"],
                title=PROMPTS["title"],
                visual_style="MOTION_GRAPHIC",
                aspect_ratio="9:16",
                target_duration_seconds=30,
                status="APPROVED",
                total_scenes=6,
                visual_bible_json=PROMPTS["visual_bible"],
                created_at=now,
            )
        )
        session.flush()
        for scene in PROMPTS["scenes"]:
            session.add(
                StoryboardScene(
                    id=str(uuid4()),
                    storyboard_id=NEPAL_ID,
                    scene_index=scene["scene_index"],
                    visual_prompt=scene["still_prompt"],
                    visual_type="MOTION_GRAPHIC",
                    duration_seconds=PLANNED_SECONDS,
                    voiceover_segment=scene["narration"],
                    shot_type="MEDIUM",
                    transition_in="CUT",
                    claim_ids_json=scene["claim_ids"],
                    story_purpose=scene["story_purpose"],
                    scene_kind="LIVE",
                    card_json=None,
                    created_at=now,
                )
            )
        # The render that delivered the files: which model drew and filmed each scene, and
        # how many bytes each clip was when it landed.
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=NEPAL_ID,
                output_asset_id=None,
                status="COMPLETED",
                render_engine="FFMPEG",
                command_args_json=[],
                execution_log="render 2",
                started_at=now,
                finished_at=now,
                production_json={
                    "image": {"provider": "RUNWAY_IMAGES", "model": "seedream5_pro"},
                    "voice": {"provider": "ELEVENLABS", "model": "eleven_flash_v2"},
                    "scenes": [
                        {
                            "scene_index": scene["scene_index"],
                            "characters": len(scene["narration"]),
                            "image": {"model": "seedream5_pro"},
                            "motion": (
                                {
                                    "model": "seedance2_5",
                                    "bytes": (folder / "motion_01.mp4").stat().st_size,
                                }
                                if scene["scene_index"] == 1
                                else {"model": "seedance2", "refused": "HTTP 400"}
                            ),
                        }
                        for scene in PROMPTS["scenes"]
                    ],
                },
            )
        )
        session.add(
            VideoRenderJob(
                id=str(uuid4()),
                storyboard_id=NEPAL_ID,
                output_asset_id=None,
                status="COMPLETED",
                render_engine="FFMPEG",
                command_args_json=[],
                execution_log="render 1",
                started_at="2026-09-26T14:44:16+00:00",
                finished_at="2026-09-26T15:12:58+00:00",
                production_json={
                    "image": {"provider": "RUNWAY_IMAGES", "model": "seedream5_pro"},
                    "scenes": [
                        {
                            "scene_index": 2,
                            "motion": {
                                "model": "seedance2",
                                "bytes": (folder / "motion_02.mp4").stat().st_size,
                            },
                        }
                    ],
                },
            )
        )
    return NEPAL_ID


@pytest.fixture
def vendors(monkeypatch):
    """Every way the studio could reach a paid vendor, replaced by a spy that fails the test."""
    asked: list[str] = []

    def spy(name: str):
        def refuse(*args, **kwargs):
            asked.append(name)
            raise AssertionError(f"the rehearsal reached a paid vendor through {name}")

        return refuse

    import app.media.assembler as assembler
    import app.media.factory as factory
    import app.media.picture_qc as picture_qc

    for name in (
        "still_from_chain",
        "motion_for_scene",
        "render_plan",
        "tts_provider",
        "tts_provider_for",
        "image_provider",
        "image_provider_for",
        "video_provider_for",
    ):
        if hasattr(factory, name):
            monkeypatch.setattr(factory, name, spy(f"factory.{name}"))
    monkeypatch.setattr(assembler, "_generate_motion", spy("assembler._generate_motion"))
    monkeypatch.setattr(assembler, "_quote_motion", spy("assembler._quote_motion"))
    for name in ("judge_still", "vision_agent"):
        if hasattr(picture_qc, name):
            monkeypatch.setattr(picture_qc, name, spy(f"picture_qc.{name}"))
    return asked


def takes_of(engine, storyboard_id: str) -> dict[tuple[int, str], list[SceneTake]]:
    found: dict[tuple[int, str], list[SceneTake]] = {}
    with Session(engine) as session:
        for take in session.scalars(
            select(SceneTake).where(SceneTake.storyboard_id == storyboard_id)
        ):
            session.expunge(take)
            found.setdefault((take.scene_number, take.kind), []).append(take)
    return found


def snapshot(folder: Path) -> dict[str, tuple[int, int, str]]:
    return {
        str(path.relative_to(folder)): (path.stat().st_size, path.stat().st_mtime_ns, _sha256(path))
        for path in sorted(folder.rglob("*"))
        if path.is_file()
    }


def _stamp(path: Path) -> tuple[int, int] | None:
    return (path.stat().st_size, path.stat().st_mtime_ns) if path.exists() else None


# --------------------------------------------- 1. the paid files become takes, for nothing


@requires_ffmpeg
@requires_yunet
def test_adopting_a_copy_writes_approved_legacy_takes_with_sha256_and_calls_no_vendor(
    engine, tmp_path, vendors
):
    from app.media.rehearsal import adopt_existing_files

    folder = media_folder(tmp_path / "media")
    storyboard_id = nepal_board(engine, folder)
    root = tmp_path / "rehearsal"

    adopted = adopt_existing_files(
        engine, storyboard_id, folder, rehearsal_root=root, issued_by="owner", cards={5: CARD}
    )

    assert vendors == []
    assert adopted["credits"] == 0
    takes = takes_of(engine, storyboard_id)
    # Every paid file is one take with the sha256 of the copy it points at, inside the copy.
    for (_scene, _kind), rows in takes.items():
        assert len(rows) == 1
        take = rows[0]
        assert take.path and Path(take.path).is_file()
        assert Path(take.path).resolve().is_relative_to(root.resolve())
        assert take.sha256 == _sha256(Path(take.path))
        assert take.credits_quoted is None and take.credits_measured is None
    assert set(takes) == {
        (1, "still"),
        (2, "still"),
        (3, "still"),
        (4, "still"),
        (5, "still"),
        (6, "still"),
        (1, "motion"),
        (2, "motion"),
    }

    # The clean stills are approved by the Owner's adoption; the source picture is the same.
    for n in (1, 2):
        still = takes[(n, "still")][0]
        assert (still.status, still.approved_by, still.model_id) == (
            "APPROVED",
            "owner",
            "seedream5_pro",
        )
        assert still.sha256 == _sha256(folder / f"scene_{n:02d}.png")
        assert still.resolution == "1080:1920"
    # A still with faces is paid for, never approved by default.
    for n in (3, 4):
        still = takes[(n, "still")][0]
        assert still.status == "PAID" and still.approved_by is None
        assert still.failure_code == "LOCAL.FACES"
        assert "biblia vizuală interzice fețele" in (still.failure_detail or "")
    # The card scenes' stills were paid for, and are never used: their scenes are composed.
    for n in (5, 6):
        assert takes[(n, "still")][0].status == "REJECTED"
        assert takes[(n, "still")][0].failure_code == "LOCAL.COMPOSED_SCENE"

    # The hero clip starts from its still: kept, PAID, on the model that filmed it.
    hero = takes[(1, "motion")][0]
    assert (hero.status, hero.model_id) == ("PAID", "seedance2_5")
    assert hero.seconds == pytest.approx(3.0, abs=0.05)
    # Render 1's clip starts from a picture the second render overwrote: never used as if it
    # started from today's still.
    old = takes[(2, "motion")][0]
    assert (old.status, old.failure_code, old.model_id) == (
        "REJECTED",
        "LOCAL.FIRST_FRAME_MISMATCH",
        "seedance2",
    )

    # The two card scenes are now cards: the chart with its verified numbers, the black screen.
    with Session(engine) as session:
        scenes = {
            s.scene_index: s
            for s in session.scalars(
                select(StoryboardScene).where(StoryboardScene.storyboard_id == storyboard_id)
            )
        }
        assert [scenes[n].scene_kind for n in range(1, 7)] == ["LIVE"] * 4 + ["DATA_CARD", "BLACK"]
        assert [bar["value"] for bar in scenes[5].card_json["bars"]] == [100, 83]
        events = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type == "media.existing_files_adopted")
        ).all()
        assert len(events) == 1 and events[0].payload["credits"] == 0


@requires_ffmpeg
@requires_yunet
def test_adopting_twice_keeps_one_take_per_file_and_never_lowers_an_approval(
    engine, tmp_path, vendors
):
    from app.media.rehearsal import adopt_existing_files

    folder = media_folder(tmp_path / "media")
    storyboard_id = nepal_board(engine, folder)
    adopt_existing_files(
        engine,
        storyboard_id,
        folder,
        rehearsal_root=tmp_path / "r1",
        issued_by="owner",
        cards={5: CARD},
    )
    adopt_existing_files(
        engine,
        storyboard_id,
        folder,
        rehearsal_root=tmp_path / "r2",
        issued_by="owner",
        cards={5: CARD},
    )
    takes = takes_of(engine, storyboard_id)
    assert all(len(rows) == 1 for rows in takes.values())
    assert takes[(1, "still")][0].status == "APPROVED"
    assert Path(takes[(1, "still")][0].path).resolve().is_relative_to((tmp_path / "r2").resolve())
    assert vendors == []


# ----------------------------------------------- 2. assembled from the takes, for nothing


@requires_ffmpeg
@requires_yunet
def test_the_film_is_assembled_from_the_takes_with_no_vendor_and_cards_carry_100_and_83(
    engine, tmp_path, vendors
):
    from app.media.rehearsal import REUSED_VOICE_PROVIDER, rehearse

    folder = media_folder(tmp_path / "media")
    storyboard_id = nepal_board(engine, folder)

    result = rehearse(
        engine,
        storyboard_id,
        folder,
        rehearsal_root=tmp_path / "rehearsal",
        issued_by="owner",
        cards={5: CARD},
        keep_flagged_for_rehearsal=True,
    )

    assert vendors == []
    assert result["credits"] == 0
    film = result["film"]
    assert film is not None, result.get("not_rendered")
    assert Path(film["file_path"]).is_file()
    assert film["visual_source"] == "SCENE_TAKES"
    production = film["production"]
    assert production["voice"]["provider"] == REUSED_VOICE_PROVIDER
    scenes = {entry["scene_index"]: entry for entry in production["scenes"]}

    # Every LIVE still is its adopted take, reused; nothing was drawn.
    for n in (1, 2, 3, 4):
        assert scenes[n]["still_take"]["status"] == "APPROVED"
        assert scenes[n]["still_take"]["reused"] is True
        assert scenes[n]["image"] is None
    # The hero clip is the one already paid for; the others stay stills (no motion bought).
    assert scenes[1]["motion"]["reused_take"] is True
    assert scenes[1]["motion"]["model"] == "seedance2_5"
    assert scenes[2]["motion"]["model"] is None

    # Scenes 5 and 6 are composed cards, 0 credits, from the chart's verified numbers.
    assert scenes[5]["card"]["kind"] == "DATA_CARD"
    assert scenes[6]["card"]["kind"] == "BLACK"
    for n in (5, 6):
        card = scenes[n]["card"]
        assert (card["provenance"], card["credits"]) == ("composed", 0)
        assert Path(card["path"]).is_file()
    with Session(engine) as session:
        chart = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 5
            )
        ).one()
        bars = chart.card_json["bars"]
        assert [(b["value"], b["unit"]) for b in bars] == [(100, "mld. USD"), (83, "mld. USD")]
        assert [b["claim_id"] for b in bars] == [
            "c4a0e6c8-c71f-48d4-93c3-089148a27790",
            "d3561aea-dcaa-4f19-aa4a-23b80a1c52ef",
        ]
        asset = session.get(MediaAsset, film["output_asset_id"])
        assert asset is not None

    # The sound is mastered again from the narration already recorded.
    loudness = production["audio"]["loudness"]
    assert loudness["true_peak_target_dbtp"] == -2.0
    # Quality control ran on the rehearsal film, and the Owner's report is written.
    assert result["qc"] is not None
    assert "Repetiția nu a apelat niciun furnizor" in result["summary_ro"]
    # The flagged stills are kept only because the Owner chose to see them in the rehearsal,
    # and the sheet still says they need a new picture before a real film.
    rows = {row["scene_index"]: row for row in result["adoption"]["sheet"]["scenes"]}
    assert STILL_REDO in rows[3]["line_ro"] and STILL_REDO in rows[4]["line_ro"]
    assert "doar pentru repetiție" in rows[3]["line_ro"]
    # The sheet says what the film did with the paid clip, as the manifest records it.
    assert rows[1]["motion"]["used"] is True
    assert "(seedance2_5, 3,00 s) se folosește" in rows[1]["line_ro"]
    assert "pornește din altă imagine" in rows[2]["line_ro"]
    assert ".." not in result["summary_ro"]


@requires_ffmpeg
@requires_yunet
def test_a_paid_clip_shorter_than_its_scene_is_named_and_never_claimed_used(
    engine, tmp_path, vendors
):
    """The Nepal hero clip lasts 4,06 s and its scene asks 4,40 s: the render leaves it out,
    and the sheet must say so instead of claiming the paid clip is in the film.

    2026-10-01 (TIMELINE_24_CAPTIONS): a scene lasts its words plus a breath, not its plan,
    so the fixture's 3.0 s clip is made shorter than its scene by the scene's words: a 4.2 s
    narration on scene 1."""
    import re

    from app.media.rehearsal import rehearse

    folder = media_folder(tmp_path / "media")
    _ffmpeg(
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=220:duration=4.2",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        str(folder / "voice_01.mp3"),
    )
    storyboard_id = nepal_board(engine, folder)
    with Session(engine) as session, session.begin():
        scene = session.scalars(
            select(StoryboardScene).where(
                StoryboardScene.storyboard_id == storyboard_id, StoryboardScene.scene_index == 1
            )
        ).one()
        scene.duration_seconds = 4.0

    result = rehearse(
        engine,
        storyboard_id,
        folder,
        rehearsal_root=tmp_path / "rehearsal",
        issued_by="owner",
        cards={5: CARD},
        keep_flagged_for_rehearsal=True,
        run_qc=False,
    )
    assert vendors == []
    hero = result["film"]["production"]["scenes"][0]["motion"]
    assert hero.get("reused_take") is not True
    row = result["adoption"]["sheet"]["scenes"][0]
    assert row["motion"]["used"] is False
    # The shot the clip had to fill: the scene's words (4.2 s) on whole frames.
    shot = re.search(r"e mai scurt decât scena \((\d+),(\d\d) s\)", row["line_ro"])
    assert shot is not None, row["line_ro"]
    assert 4.2 <= float(f"{shot.group(1)}.{shot.group(2)}") <= 4.4
    assert "se folosește" not in row["line_ro"]


def test_the_owners_letter_is_written_even_for_a_report_shape_the_writer_does_not_know():
    """Measured on the real Nepal rehearsal (2026-10-01): its motion check failed with
    'scenes' as a count, and the letter writer stopped on it. The verdict and the control's
    own reasons still reach the Owner."""
    from app.media.rehearsal import owner_report

    qc = {
        "status": "FAILED",
        "score": 0.75,
        "checks_json": {
            "motion_qc": {
                "passed": False,
                "scenes": 6,
                "fallback_scenes": 4,
                "max_fallback_scenes": 0,
            }
        },
        "failure_reasons_json": ["Motion QC: 4 of 6 scenes are stills"],
    }
    adoption = {
        "kinds": {"1": "LIVE", "5": "DATA_CARD"},
        "sheet": {
            "scenes": [
                {"scene_index": 1, "kind": "LIVE"},
                {"scene_index": 5, "kind": "DATA_CARD"},
            ],
            "still_price": {"credits": 18, "source": "tarif publicat 27.09", "credit_usd": 0.01},
        },
    }
    letter = owner_report(qc, adoption, [])
    assert "0,75" in letter
    assert "Mișcare" in letter or "Motion QC: 4 of 6 scenes are stills" in letter


# ------------------------------------------- 3. a still with faces is listed, not bought


@requires_ffmpeg
@requires_yunet
def test_stills_failing_the_face_check_are_listed_for_a_new_still_and_nothing_is_bought(
    engine, tmp_path, vendors
):
    from app.media.rehearsal import adopt_existing_files, rehearse

    folder = media_folder(tmp_path / "media")
    storyboard_id = nepal_board(engine, folder)

    adopted = adopt_existing_files(
        engine,
        storyboard_id,
        folder,
        rehearsal_root=tmp_path / "rehearsal",
        issued_by="owner",
        cards={5: CARD},
    )
    sheet = adopted["sheet"]
    rows = {row["scene_index"]: row for row in sheet["scenes"]}
    for n in (3, 4):
        assert STILL_REDO in rows[n]["line_ro"]
        assert rows[n]["still"]["status"] == "PAID"
        assert rows[n]["credits_needed"] == 18
        assert any("față" in reason or "fețe" in reason for reason in rows[n]["still"]["reasons"])
    for n in (1, 2):
        assert STILL_REDO not in rows[n]["line_ro"]
        assert rows[n]["credits_needed"] == 0
    for n in (5, 6):
        assert "compus local · 0 credite" in rows[n]["line_ro"]
        assert rows[n]["credits_needed"] == 0
    assert sheet["needs_new_still"] == [3, 4]
    assert sheet["credits_spent"] == 0
    assert sheet["credits_needed_for_stills"] == 36

    before = takes_of(engine, storyboard_id)
    # Without the Owner's choice to see them anyway, the film is not assembled around them.
    result = rehearse(
        engine,
        storyboard_id,
        folder,
        rehearsal_root=tmp_path / "rehearsal-2",
        issued_by="owner",
        cards={5: CARD},
    )
    assert result["film"] is None
    assert "Scena 3" in result["not_rendered"] and "Scena 4" in result["not_rendered"]
    assert vendors == []
    after = takes_of(engine, storyboard_id)
    assert sorted(after) == sorted(before)
    assert all(t.status != "QUOTED" for rows_ in after.values() for t in rows_)
    with Session(engine) as session:
        assert (
            session.scalars(
                select(VideoRenderJob).where(VideoRenderJob.status != "COMPLETED")
            ).all()
            == []
        )


# ------------------------------------------------ 4. only a copy is ever written to


@requires_ffmpeg
@requires_yunet
def test_only_a_copy_is_written_and_the_owners_database_is_never_opened(engine, tmp_path, vendors):
    from app.media.rehearsal import RehearsalError, rehearse

    folder = media_folder(tmp_path / "media")
    storyboard_id = nepal_board(engine, folder)
    original = snapshot(folder)
    live_db = _stamp(LIVE_DB)

    # A rehearsal folder inside the original (or the original itself) is refused before
    # anything is copied or written.
    for bad in (folder, folder / "rehearsal"):
        with pytest.raises(RehearsalError, match="copie"):
            rehearse(
                engine,
                storyboard_id,
                folder,
                rehearsal_root=bad,
                issued_by="owner",
                cards={5: CARD},
            )
    assert takes_of(engine, storyboard_id) == {}

    root = tmp_path / "rehearsal"
    result = rehearse(
        engine,
        storyboard_id,
        folder,
        rehearsal_root=root,
        issued_by="owner",
        cards={5: CARD},
        keep_flagged_for_rehearsal=True,
    )
    assert result["film"] is not None
    assert snapshot(folder) == original, "the original media folder was written to"
    assert _stamp(LIVE_DB) == live_db, "data/studio.db was touched"
    assert Path(engine.url.database).resolve() != LIVE_DB.resolve()
    assert Path(result["film"]["file_path"]).resolve().is_relative_to(root.resolve())
    for rows in takes_of(engine, storyboard_id).values():
        for take in rows:
            path = Path(take.path)
            assert path.resolve().is_relative_to(root.resolve())
            assert take.sha256 == original[path.name][2], "the copy differs from the original"


def test_an_agent_cannot_adopt_files_and_test_is_not_the_owner_in_production(
    engine, tmp_path, vendors
):
    from app.media.rehearsal import RehearsalRefused, adopt_existing_files

    for who in ("director", "video_editor", "agent", "autorun", ""):
        with pytest.raises(RehearsalRefused):
            adopt_existing_files(
                engine, NEPAL_ID, tmp_path, rehearsal_root=tmp_path / "r", issued_by=who
            )
    with Session(engine) as session, session.begin():
        session.get(OwnerPolicy, 1).environment = "PRODUCTION"
    with pytest.raises(RehearsalRefused):
        adopt_existing_files(
            engine, NEPAL_ID, tmp_path, rehearsal_root=tmp_path / "r", issued_by="test"
        )
    assert not (tmp_path / "r").exists()


@requires_ffmpeg
@requires_yunet
def test_a_chart_without_its_verified_numbers_is_refused_before_anything_is_written(
    engine, tmp_path, vendors
):
    from app.media.rehearsal import RehearsalError, adopt_existing_files

    folder = media_folder(tmp_path / "media")
    storyboard_id = nepal_board(engine, folder)
    with pytest.raises(RehearsalError, match="Scena 5"):
        adopt_existing_files(
            engine, storyboard_id, folder, rehearsal_root=tmp_path / "r", issued_by="owner"
        )
    wrong = json.loads(json.dumps(CARD))
    wrong["bars"][1]["value"] = 89
    wrong["bars"][1]["claim_id"] = "c4a0e6c8-c71f-48d4-93c3-089148a27790"
    with pytest.raises(RehearsalError, match="Scena 5"):
        adopt_existing_files(
            engine,
            storyboard_id,
            folder,
            rehearsal_root=tmp_path / "r",
            issued_by="owner",
            cards={5: wrong},
        )
    assert takes_of(engine, storyboard_id) == {}
    assert not (tmp_path / "r").exists()
    with Session(engine) as session:
        kinds = session.scalars(
            select(StoryboardScene.scene_kind).where(StoryboardScene.storyboard_id == storyboard_id)
        ).all()
        assert set(kinds) == {"LIVE"}


# ----------------------------------------------------- 5. the Owner's route, 0 credits


class _Spy:
    """An adapter left on app.state, as a test or a stale wiring could: never to be asked."""

    PROVIDER_NAME = "SPY"
    model = "spy"

    def __init__(self) -> None:
        self.asked = 0

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)

        def call(*args, **kwargs):
            self.asked += 1
            raise AssertionError(f"the rehearsal asked the adapter left on app.state: {name}")

        return call


@requires_ffmpeg
@requires_yunet
def test_the_route_is_the_owners_and_costs_nothing(client, engine, headers, tmp_path, vendors):
    storage = tmp_path / "media"
    folder = media_folder(storage)
    storyboard_id = nepal_board(engine, folder)
    client.app.app.state.media_storage_root = storage
    image, voice = _Spy(), _Spy()
    client.app.app.state.image_adapter = image
    client.app.app.state.tts_adapter = voice
    url = f"/api/v1/media/storyboards/{storyboard_id}/adopt-existing-files"
    body = {"cards": {"5": CARD}, "keep_flagged_for_rehearsal": True}
    original = snapshot(folder)

    assert client.post(url, json=body).status_code == 401
    with Session(engine) as session:
        assert session.scalars(select(SceneTake)).all() == []

    missing = client.post(
        f"/api/v1/media/storyboards/{uuid4()}/adopt-existing-files", headers=headers, json=body
    )
    assert missing.status_code == 404

    no_card = client.post(url, headers=headers, json={})
    assert no_card.status_code == 422
    assert "Scena 5" in json.dumps(no_card.json(), ensure_ascii=False)

    response = client.post(url, headers=headers, json=body)
    assert response.status_code == 200, response.text
    answer = response.json()
    assert answer["credits"] == 0
    assert answer["film"] is not None
    assert (image.asked, voice.asked) == (0, 0)
    assert vendors == []
    assert snapshot(folder) == original
    rehearsal = Path(answer["adoption"]["rehearsal_root"]).resolve()
    assert rehearsal.is_relative_to(storage.resolve())
    assert not rehearsal.is_relative_to(folder.resolve())
    with Session(engine) as session:
        # Nothing went into the books: a rehearsal spends nothing.
        economy = session.scalars(
            select(DomainEvent).where(DomainEvent.event_type.like("economy.%"))
        ).all()
        assert economy == []
        assert {t.status for t in session.scalars(select(SceneTake))} <= {
            "APPROVED",
            "PAID",
            "REJECTED",
        }


# --------------------------------------- opt-in: the real Nepal film, from a database copy


@pytest.mark.skipif(
    not os.environ.get("STUDIO_NEPAL_REHEARSAL_DB"),
    reason="opt-in: set STUDIO_NEPAL_REHEARSAL_DB to a COPY of the Owner's database",
)
def test_the_real_nepal_film_rehearses_from_a_copy(tmp_path, settings):  # pragma: no cover - opt-in
    import shutil

    from app.db import create_db_engine, migrate
    from app.media.rehearsal import rehearse

    source_db = Path(os.environ["STUDIO_NEPAL_REHEARSAL_DB"]).resolve()
    assert source_db != LIVE_DB.resolve(), "name a copy, never data/studio.db itself"
    media = Path(
        os.environ.get("STUDIO_NEPAL_MEDIA", ROOT / "backend" / "storage" / "media" / NEPAL_ID)
    )
    copy = tmp_path / "studio.db"
    for suffix in ("", "-wal", "-shm"):
        if Path(f"{source_db}{suffix}").exists():
            shutil.copyfile(f"{source_db}{suffix}", f"{copy}{suffix}")
    engine = create_db_engine(f"sqlite:///{copy.as_posix()}")
    migrate(engine)
    original = snapshot(media)
    out = Path(os.environ.get("STUDIO_NEPAL_REHEARSAL_OUT", tmp_path / "rehearsal"))
    # The film is narrated in English, so its chart speaks English; the numbers are the claims'.
    english = {
        "title": "Climate finance: promised vs delivered",
        "bars": [
            {**CARD["bars"][0], "label": "Promised", "unit": "billion USD"},
            {**CARD["bars"][1], "label": "Delivered", "unit": "billion USD"},
        ],
        "highlight": "Delivered",
    }
    result = rehearse(
        engine,
        NEPAL_ID,
        media,
        rehearsal_root=out,
        issued_by="owner",
        cards={5: english},
        keep_flagged_for_rehearsal=True,
        settings=settings,
    )
    print(json.dumps(result["adoption"]["sheet"], ensure_ascii=False, indent=1))
    print(result["summary_ro"])
    assert snapshot(media) == original
    assert result["credits"] == 0
    engine.dispose()
