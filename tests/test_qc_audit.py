"""The Owner's test (2026-10-12): every picture quality control refused today, shown to the
Director on a COPY of the studio's database — «vreau să treci imaginile picate de la QC pe la
Directoare și să decidă dacă au picat sau nu corect și dacă trebuie să fie refăcute».

On the babcf272 film of tests/test_director_decides_qc.py (its QC FAILED on every scene), with
a still the stills gate refused and a clip the clip QC refused beside it:

- ``--dry-run`` lists the refused stills, clips and film scenes with quality control's words and
  what would be shown, asks no model, never reads the vault, and leaves the source database's
  bytes as they were;
- a run with a scripted Director (faked at the registry; no vendor, no credit) records her
  verdicts in the copy, never in the source, and counts the redo bought after a refusal she
  overturned, with its quoted credits — and not a take bought once the scene was settled.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from app.media.models import SceneTake
from app.media.toolchain import find_ffmpeg
from app.services import utc_now
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_director_decides_qc import CAPTIONS, PANELS, _take, failed_film
from test_second_look import (
    MINOR,
    SERIOUS,
    LookingDirector,
    give_vision,
    her_registry,
    seeded_studio,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures" / "nepal_1d530880"
GATE_WORDS = "YuNet a găsit 1 față în imagine; biblia vizuală interzice fețele"
CLIP_WORDS = "Scena 2: privit la 1080 px: nu arată ce cere planul"

requires_ffmpeg = pytest.mark.skipif(find_ffmpeg() is None, reason="ffmpeg not installed")


@pytest.fixture
def studio(engine):
    return seeded_studio(engine)


@pytest.fixture
def qc_audit():
    spec = importlib.util.spec_from_file_location("qc_audit", ROOT / "scripts" / "qc_audit.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["qc_audit"] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop("qc_audit", None)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def database_bytes(settings) -> dict[str, str | None]:
    """The source database's files, as bytes on disk (with its WAL and SHM when present)."""
    db = Path(str(settings.database_url).removeprefix("sqlite:///"))
    return {
        suffix: (_sha(path) if (path := db.with_name(db.name + suffix)).exists() else None)
        for suffix in ("", "-wal", "-shm")
    }


def refused(
    session, board: str, scene: int, kind: str, code: str, words: str, path: Path, at: str
) -> str:
    take_id = _take(session, board, scene, kind, None)
    row = session.get(SceneTake, take_id)
    row.status, row.approved_by = "REJECTED", None
    row.failure_code, row.failure_detail = code, words
    row.path, row.sha256 = str(path), _sha(path)
    row.credits_quoted = 7.0 if kind == "still" else 24.0
    row.created_at = row.updated_at = at
    return take_id


#: The one-frame look's verdict on scene 5 (and a character it found unlike the bible).
ONE_FRAME = {
    "picture_qc": {
        "status": "MEASURED",
        "passed": False,
        "scenes": [
            {
                "scene": 5,
                "status": "MEASURED",
                "is_a_picture": True,
                "one_picture": False,
                "shows_the_scene": True,
                "reason": "three stacked panels",
            }
        ],
    },
    "character_drift_qc": {
        "characters": [
            {
                "scene": 5,
                "character": "Nadia",
                "status": "MEASURED",
                "matches": False,
                "reason": "red hair",
            }
        ]
    },
}


def the_day(engine, tmp_path: Path, *, clip: bool) -> dict[str, Any]:
    """The film whose QC failed, a still the gate refused on scene 3 at 00:00:05 today and, with
    ``clip``, a clip the clip QC refused on scene 2."""
    film = failed_film(engine, extra_checks=ONE_FRAME)
    day = utc_now()[:10]
    still = tmp_path / "scene_03_c1.jpg"
    shutil.copyfile(FIXTURES / "scene_03.jpg", still)
    motion = tmp_path / "motion_02.mp4"
    if find_ffmpeg() is not None:
        subprocess.run(
            [
                str(find_ffmpeg()),
                "-v",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=s=270x480:r=24:d=2",
                "-pix_fmt",
                "yuv420p",
                str(motion),
            ],
            check=True,
            capture_output=True,
        )
    else:
        motion.write_bytes(b"not a clip without an encoder")
    with Session(engine) as session, session.begin():
        film["refused_still"] = refused(
            session,
            film["board"],
            3,
            "still",
            "LOCAL.STILL_GATE",
            GATE_WORDS,
            still,
            f"{day}T00:00:05+00:00",
        )
        if clip:
            film["refused_clip"] = refused(
                session,
                film["board"],
                2,
                "motion",
                "QC.CLIP",
                f"Controlul clipului: {CLIP_WORDS}",
                motion,
                f"{day}T00:00:06+00:00",
            )
    film["day"] = day
    return film


def report_of(capsys) -> tuple[dict[str, Any], Path]:
    out = capsys.readouterr().out
    table = Path(out.strip().splitlines()[-1].removeprefix("Raportul: ").strip())
    data = table.with_suffix(".json")
    return json.loads(data.read_text(encoding="utf-8")), table


def test_the_dry_run_lists_every_refusal_and_never_touches_the_source(
    engine, settings, tmp_path, monkeypatch, capsys, qc_audit
):
    film = the_day(engine, tmp_path, clip=True)
    engine.dispose()  # a checkpoint on close would change the bytes; nothing writes after this
    before = database_bytes(settings)
    monkeypatch.setattr(qc_audit, "director_registry", lambda *a: pytest.fail("vault read"))
    monkeypatch.setattr(
        "app.media.second_look.second_look", lambda *a, **k: pytest.fail("a model was asked")
    )
    source = str(settings.database_url).removeprefix("sqlite:///")

    code = qc_audit.main(
        ["--database", source, "--work", str(tmp_path / "work"), "--day", film["day"], "--dry-run"]
    )

    assert code == 0
    report, table = report_of(capsys)
    assert database_bytes(settings) == before
    copy = Path(report["meta"]["database_copy"])
    assert copy.is_file() and copy.resolve() != Path(source).resolve()
    assert copy.parent.parent == table.parent
    rows = report["rows"]
    assert [row["kind"] for row in rows] == ["still", "shot"] + ["film_scene"] * 5
    still, shot, *scenes = rows
    assert still["take_ids"] == [film["refused_still"]] and still["scene_index"] == 3
    assert still["refusal"] == GATE_WORDS.split("; ")
    assert still["images"] == [str(tmp_path / "scene_03_c1.jpg")]
    assert shot["take_ids"] == [film["refused_clip"]] and shot["refusal"] == [CLIP_WORDS]
    if find_ffmpeg() is not None:
        assert len(shot["images"]) == 3 and shot["frames_from"] == "CLIP"
    assert [scene["scene_index"] for scene in scenes] == [1, 2, 3, 4, 5]
    assert all(CAPTIONS in " ".join(scene["refusal"]) for scene in scenes[:4])
    assert scenes[4]["refusal"] == [
        f"Cadrele scenei din film: {PANELS}",
        "Privirea pe un cadru al scenei: nu este o singură imagine — three stacked panels",
        "Personajul Nadia nu seamănă cu biblia — red hair",
    ]
    assert scenes[0]["take_ids"] == [film["takes"][1]["still"], film["takes"][1]["motion"]]
    # The film and its takes are not on disk: nothing can be shown of those scenes, and why.
    assert all(scene["images"] == [] and scene["reason_ro"] for scene in scenes)
    assert {row["verdict"] for row in rows} == {None}
    assert report["totals"]["refusals"] == 7 and report["totals"]["dry_run"] is True
    assert report["totals"]["by_kind"] == {"still": 1, "shot": 1, "film_scene": 5}
    text = table.read_text(encoding="utf-8")
    assert "| Film | Scena | Tip | Preluare | Ce a spus controlul |" in text
    assert "Rulare de probă" in text and "scenă din film" in text


def test_limit_caps_the_refusals_looked_at(
    engine, settings, tmp_path, monkeypatch, capsys, qc_audit
):
    film = the_day(engine, tmp_path, clip=False)
    source = str(settings.database_url).removeprefix("sqlite:///")

    qc_audit.main(
        [
            "--database",
            source,
            "--work",
            str(tmp_path / "work"),
            "--day",
            film["day"],
            "--dry-run",
            "--limit",
            "2",
        ]
    )

    report, _table = report_of(capsys)
    assert [row["kind"] for row in report["rows"]] == ["still", "film_scene"]


@requires_ffmpeg
def test_her_verdicts_are_recorded_in_the_copy_and_the_redo_she_overturned_is_counted(
    engine, settings, studio, tmp_path, monkeypatch, capsys, qc_audit
):
    from app.models import DomainEvent

    film = the_day(engine, tmp_path, clip=False)
    give_vision(engine, studio["agents"]["Director"].model_id)
    day = film["day"]
    # After the refusal: a redo still approved at 00:00:30 (it settles the scene) and, later
    # that day, one more still for scene 3 that no longer answers the refusal.
    with Session(engine) as session, session.begin():
        redo = _take(session, film["board"], 3, "still", "still_gate")
        later = _take(session, film["board"], 3, "still", "still_gate")
        for take_id, at in ((redo, "00:00:30"), (later, "00:00:40")):
            row = session.get(SceneTake, take_id)
            row.credits_quoted = 7.0
            row.created_at = row.updated_at = f"{day}T{at}+00:00"
        # Scene 5's still, on disk: the film scene she is shown when nothing else is there.
        five = tmp_path / "scene_05.jpg"
        shutil.copyfile(FIXTURES / "scene_05.jpg", five)
        row = session.get(SceneTake, film["takes"][5]["still"])
        row.path, row.sha256 = str(five), _sha(five)
    engine.dispose()
    before = database_bytes(settings)

    # She overturns the still (a minor defect) and confirms the film's scene 5.
    model = LookingDirector(lambda prompt: MINOR if '"kind": "still"' in prompt else SERIOUS)
    monkeypatch.setattr(
        qc_audit,
        "director_registry",
        lambda engine, live: (
            her_registry(studio, model),
            {"model": "fake-seeing-model", "registered": True, "connections_not_read": 0},
        ),
    )
    source = str(settings.database_url).removeprefix("sqlite:///")

    code = qc_audit.main(["--database", source, "--work", str(tmp_path / "work"), "--day", day])

    assert code == 0
    report, table = report_of(capsys)
    assert database_bytes(settings) == before
    rows = {(row["kind"], row["scene_index"]): row for row in report["rows"]}
    still = rows[("still", 3)]
    assert (still["verdict"], still["severity"], still["redo"]) == ("OVERTURNED", "minor", False)
    assert [take["take_id"] for take in still["bought_after"]] == [redo]
    scene_five = rows[("film_scene", 5)]
    assert scene_five["frames_from"] == "STILL" and scene_five["verdict"] == "CONFIRMED"
    assert rows[("film_scene", 1)]["verdict"] == "NOT_SHOWN"
    assert len(model.looked) == 2  # the still and scene 5: nothing else could be shown
    totals = report["totals"]
    assert (totals["confirmed"], totals["overturned"], totals["not_shown"]) == (1, 1, 4)
    assert (totals["redos_for_overturned"], totals["redo_credits_for_overturned"]) == (1, 7.0)
    text = table.read_text(encoding="utf-8")
    assert "refuz greșit" in text and "defect mic" in text and "7 credite" in text
    # Her looks are in the copy, never in the source.
    copy = report["meta"]["database_copy"]
    from app.db import create_db_engine

    for url, expected in ((f"sqlite:///{copy}", 2), (settings.database_url, 0)):
        other = create_db_engine(url)
        try:
            with Session(other) as session:
                looks = session.scalars(
                    select(DomainEvent).where(
                        DomainEvent.event_type == "media.director_second_look"
                    )
                ).all()
            assert len(looks) == expected
        finally:
            other.dispose()
