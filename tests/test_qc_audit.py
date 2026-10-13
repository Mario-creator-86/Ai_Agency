"""The Owner's test (2026-10-12): every picture quality control refused today, shown to the
Director on a COPY of the studio's database — «vreau să treci imaginile picate de la QC pe la
Directoare și să decidă dacă au picat sau nu corect și dacă trebuie să fie refăcute».

On the babcf272 film of tests/test_director_decides_qc.py (its QC FAILED on every scene), with
a still the stills gate refused and a clip the clip QC refused beside it:

- ``--dry-run`` lists the refused stills, clips and film scenes with quality control's whole
  words (a still's from the gate's recorded verdict, never the truncated detail cut at «; »
  inside a parenthesis) and what would be shown, asks no model, never reads the vault, leaves
  the source database's bytes as they were, and prints a short table per film;
- a run with a scripted Director (faked at the registry; no vendor, no credit) records her
  verdicts in the copy, never in the source, and counts the redo bought after a refusal she
  overturned, with its quoted credits — and not a take bought once the scene was settled;
- what a refusal she overturned bought is read from the takes' history: a take approved then
  (retired since) settles the scene with its whole batch counted, a take the vendor never ran
  is listed apart, unpaid, and the storyboard's next film QC ends the window;
- a film scene refused by several reports is shown at the frames of the report that recorded
  them.
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
from uuid import uuid4

import pytest
from app.media.models import QualityControlReport, SceneTake
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
FIXTURES = Path(__file__).parent / "fixtures" / "factual_sample"
GATE_WORDS = "YuNet a găsit 1 față în imagine; biblia vizuală interzice fețele"
CLIP_WORDS = "Scena 2: privit la 1080 px: nu arată ce cere planul"
TITLE = "The Particle That Shouldn't Exist (But Does)"
#: The gate's whole verdict on a still (2026-10-12, f06808c9 and 1c038a99 on the database copy),
#: as `sync_take_quality` keeps it on the take's generation job; its ``failure_detail`` is the
#: same text cut at 500 characters.
BAND = (
    "Imaginea nu e o singură fotografie: o bandă plată pe toată lățimea, la mijloc, între două "
    "imagini (rândurile 394-465 din 480, 15% din înălțime; prag 15%)"
)
RULE = (
    "Imaginea încalcă biblia vizuală: «No written words, letters or logos anywhere; Pages and "
    "screens are blank»"
)
LOOKED = (
    "Modelul de vedere a văzut text lizibil în imagine «The still shows Nadia facing the viewer "
    "with Sarah leaning in, but the green ledger displays visible ruled lines and text at the "
    "bottom, violating the blank pages rule.» " + "Și încă ceva văzut pe registru. " * 8
)
WHOLE_VERDICT = [BAND, GATE_WORDS, RULE, LOOKED.strip()]

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


def bought(
    session,
    board: str,
    scene: int,
    at: str,
    *,
    kind: str = "still",
    status: str = "PAID",
    code: str | None = None,
    approved_by: str | None = None,
    remote: str | None = None,
    credits: float | None = 7.0,
) -> str:
    """A take bought for ``scene`` at ``at`` (UTC time of the test's day), as it stands now."""
    take_id = _take(session, board, scene, kind, approved_by)
    row = session.get(SceneTake, take_id)
    row.status, row.failure_code, row.remote_task_id = status, code, remote
    row.credits_quoted = credits
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


def report_of(capsys) -> tuple[dict[str, Any], Path, str]:
    out = capsys.readouterr().out
    line = next(line for line in out.splitlines() if line.startswith("Raportul: "))
    table = Path(line.removeprefix("Raportul: ").strip())
    data = table.with_suffix(".json")
    return json.loads(data.read_text(encoding="utf-8")), table, out


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
    report, table, out = report_of(capsys)
    assert database_bytes(settings) == before
    copy = Path(report["meta"]["database_copy"])
    assert copy.is_file() and copy.resolve() != Path(source).resolve()
    assert copy.parent.parent == table.parent
    rows = report["rows"]
    assert [row["kind"] for row in rows] == ["still", "shot"] + ["film_scene"] * 5
    still, shot, *scenes = rows
    assert still["take_ids"] == [film["refused_still"]] and still["scene_index"] == 3
    # One sentence of the gate, kept whole: «biblia vizuală interzice fețele» continues it.
    assert still["refusal"] == [GATE_WORDS]
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
    assert scenes[0]["reports"] == [
        {"report_id": film["report"], "media_asset_id": film["asset"], "frame_numbers": []}
    ]
    # The film and its takes are not on disk: nothing can be shown of those scenes, and why.
    assert all(scene["images"] == [] and scene["reason_ro"] for scene in scenes)
    assert {row["verdict"] for row in rows} == {None}
    assert report["totals"]["refusals"] == 7 and report["totals"]["dry_run"] is True
    assert report["totals"]["by_kind"] == {"still": 1, "shot": 1, "film_scene": 5}
    text = table.read_text(encoding="utf-8")
    assert "| Film | Scena | Tip | Preluare | Ce i s-a arătat | Ce a spus controlul |" in text
    assert "Rulare de probă" in text and "scenă din film" in text
    # The short table per film, printed at the end.
    tail = out[out.index("Rezumat pe filme") :]
    assert f"| {TITLE} | 7 | — | — | — |" in tail and "| **Total** | 7 |" in tail


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

    report, _table, _out = report_of(capsys)
    assert [row["kind"] for row in report["rows"]] == ["still", "film_scene"]


def test_a_stills_refusal_is_read_whole_from_the_gates_recorded_verdict(
    engine, settings, tmp_path, capsys, qc_audit
):
    from app.providers.runpod.jobs import GenerationJob

    film = the_day(engine, tmp_path, clip=False)
    whole = "; ".join(WHOLE_VERDICT)
    assert len(whole) > 500
    with Session(engine) as session, session.begin():
        take = session.get(SceneTake, film["refused_still"])
        take.remote_task_id = "job-1-e2:3"
        take.failure_detail = whole[:500]
        session.add(
            GenerationJob(
                id=str(uuid4()),
                idempotency_key=uuid4().hex,
                payload_hash=uuid4().hex,
                provider="runpod",
                target="image",
                project_id=film["board"],
                scene_id="3",
                attempt=1,
                operation="still",
                model="Qwen-Image-2512",
                gpu="RTX PRO 6000",
                hourly_rate="1.89",
                remote_job_id="job-1-e2:3",
                status="COMPLETED",
                request={},
                created_at=utc_now(),
                accepted=False,
                quality_result=whole,
            )
        )
    source = str(settings.database_url).removeprefix("sqlite:///")

    qc_audit.main(
        ["--database", source, "--work", str(tmp_path / "work"), "--day", film["day"], "--dry-run"]
    )

    report, _table, _out = report_of(capsys)
    assert report["rows"][0]["refusal"] == WHOLE_VERDICT


def test_quality_controls_sentences_split_only_where_one_ends(qc_audit):
    assert qc_audit.split_reasons("; ".join(WHOLE_VERDICT)) == WHOLE_VERDICT
    # A detail cut inside a quote keeps the rest whole rather than inventing a sentence.
    cut = "Imaginea încalcă biblia vizuală: «No written words; Pages and"
    assert qc_audit.split_reasons(f"{GATE_WORDS}; {cut}") == [GATE_WORDS, cut]
    assert qc_audit.split_reasons("") == []


def test_a_film_scene_refused_twice_is_shown_at_the_frames_of_the_report_that_recorded_them(
    qc_audit,
):
    def scene(report: str, asset: str, frames: list[int], words: str) -> dict[str, Any]:
        return {
            "kind": "film_scene",
            "storyboard_id": "board",
            "film": "f",
            "scene_index": 5,
            "take_ids": ["still", "clip"],
            "refusal": [words],
            "report_ids": [report],
            "media_asset_id": asset,
            "frame_numbers": frames,
            "reports": [{"report_id": report, "media_asset_id": asset, "frame_numbers": frames}],
            "round_ends_at": f"{report}-next",
        }

    (merged,) = qc_audit.same_picture_once(
        [
            scene("b298cec6", "film-1", [], "Privirea pe un cadru al scenei: nu arată scena"),
            scene("879e57fa", "film-2", [561, 645, 729], "Cadrele scenei din film: un tunel"),
        ]
    )

    assert merged["frame_numbers"] == [561, 645, 729] and merged["media_asset_id"] == "film-2"
    assert merged["report_ids"] == ["b298cec6", "879e57fa"]
    assert [entry["report_id"] for entry in merged["reports"]] == ["b298cec6", "879e57fa"]
    assert len(merged["refusal"]) == 2 and merged["round_ends_at"] == "879e57fa-next"


def test_what_a_refusal_bought_is_read_from_the_takes_history(engine, qc_audit):
    film = failed_film(engine)
    day = utc_now()[:10]

    def at(clock: str) -> str:
        return f"{day}T{clock}+00:00"

    with Session(engine) as session, session.begin():
        # The storyboard's next film QC came at 00:00:50.
        session.get(QualityControlReport, film["report"]).verified_at = at("00:00:50")
        refused_still = bought(
            session, film["board"], 3, at("00:00:05"), status="REJECTED", code="LOCAL.STILL_GATE"
        )
        never = bought(
            session,
            film["board"],
            3,
            at("00:00:20"),
            status="REFUSED",
            code="RUNPOD.CANCELLED",
            credits=None,
        )
        # One round of three candidates: the gate approved the second, retired since (REDO).
        batch = [
            bought(
                session,
                film["board"],
                3,
                at(clock),
                status=status,
                code=code,
                approved_by=approver,
                remote=f"job-a-e2:{index}",
            )
            for index, (clock, status, code, approver) in enumerate(
                [
                    ("00:00:30", "REJECTED", "LOCAL.STILL_GATE", None),
                    ("00:00:30", "REJECTED", "REDO.OWNER", "still_gate"),
                    ("00:00:31", "REJECTED", "LOCAL.STILL_GATE", None),
                ]
            )
        ]
        after_settled = bought(session, film["board"], 3, at("00:00:40"), remote="job-b-e2:0")
        # A clip refused on scene 2 at 00:00:06 that nothing approved again: its window ends at
        # the film QC of 00:00:50, so the film repair's still of 00:01:00 is not its redo.
        refused_clip = bought(
            session,
            film["board"],
            2,
            at("00:00:06"),
            kind="motion",
            status="REJECTED",
            code="QC.CLIP",
            credits=24.0,
        )
        for_the_clip = bought(session, film["board"], 2, at("00:00:45"), remote="job-c-e2:0")
        repair = bought(
            session, film["board"], 2, at("00:01:00"), status="APPROVED", approved_by="still_gate"
        )
    with Session(engine) as session:
        still_row = {
            "kind": "still",
            "storyboard_id": film["board"],
            "scene_index": 3,
            "take_ids": [refused_still],
            "bought_at": at("00:00:05"),
            "refused_at": at("00:00:05"),
            "round_ends_at": qc_audit.next_film_qc(session, film["board"], at("00:00:05")),
        }
        clip_row = {
            **still_row,
            "kind": "shot",
            "scene_index": 2,
            "take_ids": [refused_clip],
            "bought_at": at("00:00:06"),
            "refused_at": at("00:00:06"),
        }
        counted: set[str] = set()
        still_bought, still_cancelled = qc_audit.bought_for(session, still_row, day, counted)
        clip_bought, clip_cancelled = qc_audit.bought_for(session, clip_row, day, counted)

    assert still_row["round_ends_at"] == at("00:00:50")
    # The round that settled it, whole; not the take bought after it; the cancelled one apart.
    assert sorted(take["take_id"] for take in still_bought) == sorted(batch)
    assert after_settled not in [take["take_id"] for take in still_bought]
    assert [take["take_id"] for take in still_cancelled] == [never]
    assert still_cancelled[0]["credits_quoted"] is None
    assert [take["take_id"] for take in clip_bought] == [for_the_clip]
    assert repair not in [take["take_id"] for take in clip_bought] and clip_cancelled == []


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
    report, table, out = report_of(capsys)
    assert database_bytes(settings) == before
    rows = {(row["kind"], row["scene_index"]): row for row in report["rows"]}
    still = rows[("still", 3)]
    assert (still["verdict"], still["severity"], still["redo"]) == ("OVERTURNED", "minor", False)
    assert (still["cause"], still["layer"]) == (MINOR["cause"], "still")
    assert [take["take_id"] for take in still["bought_after"]] == [redo]
    scene_five = rows[("film_scene", 5)]
    assert scene_five["frames_from"] == "STILL" and scene_five["verdict"] == "CONFIRMED"
    assert scene_five["view"]["source"] == "STILL"
    assert rows[("film_scene", 1)]["verdict"] == "NOT_SHOWN"
    assert len(model.looked) == 2  # the still and scene 5: nothing else could be shown
    # She was told what she looked at: the still the scene was filmed from.
    film_prompt = next(prompt for prompt, *_ in model.looked if '"kind": "film_scene"' in prompt)
    assert "the still the scene was filmed from" in film_prompt
    totals = report["totals"]
    assert (totals["confirmed"], totals["overturned"], totals["not_shown"]) == (1, 1, 4)
    assert (totals["redos_for_overturned"], totals["redo_credits_for_overturned"]) == (1, 7.0)
    assert report["films"] == [
        {
            "film": TITLE,
            "refusals": 6,
            "confirmed": 1,
            "overturned": 1,
            "redos": 1,
            "credits": 7.0,
            "cancelled": 0,
        }
    ]
    text = table.read_text(encoding="utf-8")
    assert "refuz greșit" in text and "defect mic" in text and "7 credite" in text
    assert MINOR["cause"] in text
    tail = out[out.index("Rezumat pe filme") :]
    assert f"| {TITLE} | 6 | 1 | 1 | 7 (1 preluări) |" in tail
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
