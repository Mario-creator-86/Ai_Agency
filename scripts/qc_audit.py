"""The Director looks again at every picture quality control refused on one day — offline.

The Owner, 2026-10-12, after a day of 19.50 USD on RunPod (11.05 USD of it on redos) and three
films that all still failed QC: «pornește agenți care să testeze: vreau să treci imaginile picate
de la QC pe la Directoare și să decidă dacă au picat sau nu corect și dacă trebuie să fie
refăcute», and «LLM-ul este pe abonament, nu costă bani să trecem pe la ei». This is that test.

It never touches the live studio. It copies ``data/studio.db`` (with its ``-wal`` and ``-shm``,
retrying while SQLite holds a file) into a folder of its own under ``--work`` and opens only the
COPY. The model registry is built as the studio builds it at start (`integrations.services.
load_registry` with the credential vault, then `main.register_seeded_ollama`); the vault's key
stays where it is, beside the live database — it is never copied and never printed. Of that
registry only the provider of the Director's seeing model (`agents.vision.seeing_model`) is
kept, so no other model can be asked anything, and no media vendor is ever in it: nothing is
bought, RunPod is never called, the live database is never written.

For every take quality control refused on ``--day`` (UTC, default today) —

- a still the stills gate refused (``LOCAL.STILL_GATE``), its file on disk, with the gate's whole
  words (the take's verdict as the gate recorded it, `cloud_generation_job.quality_result`; the
  take's ``failure_detail``, cut at 500 characters, only when there is none);
- a clip the clip QC refused (``QC.CLIP``), shown as its first, middle and last frame;
- a scene a FAILED film QC report found at fault (``picture_spans_qc`` / ``picture_qc``), shown as
  quality control judged it (`media.second_look.film_scene_view`: the scene's shot or the film's
  frames at the very frames QC looked at, else the bought clip cut at the span's own times)

— the Director is asked (`media.second_look.second_look`) whether the refusal is right, how serious
the defect is, whether the scene must be made again, and why the defect appears. The report (JSON,
and a Markdown table in Romanian) lists each refusal with what QC said and what she decided, and
the totals: how many refusals she confirmed and overturned, and how many redos were actually
bought that day for the refusals she overturned, with their credits (``scene_take.credits_quoted``;
a take the vendor never ran — cancelled, expired, never charged — is listed apart, «anulate,
neplătite», and not counted). At the end a short table per film is printed.

``--dry-run`` lists what would be shown and asks no model (the vault is not even read).
``--limit N`` caps the refusals looked at.

Usage::

    uv run --locked python -X utf8 scripts/qc_audit.py [--day 2026-10-12] [--dry-run]
        [--limit 20] [--work <folder>] [--database data/studio.db]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

#: The database's own files, copied together so the copy holds every committed write.
DB_SUFFIXES = ("", "-wal", "-shm")
#: SQLite on Windows can hold a file for a moment while it checkpoints: the copy is tried again.
COPY_TRIES = 40
COPY_WAIT_SECONDS = 0.25
STILL_GATE_CODE = "LOCAL.STILL_GATE"
CLIP_QC_CODE = "QC.CLIP"
SHOT_KINDS = ("motion", "test_shot")
#: The film checks whose scene verdicts are pictures she can look at.
FILM_CHECKS = ("picture_spans_qc", "picture_qc")
#: A sibling candidate approved within this long of a refused one was bought in the same round:
#: the round settled the scene, so nothing bought afterwards answers this refusal.
SAME_ROUND = timedelta(minutes=2)
#: Takes with no vendor batch of their own, made this close together, were one purchase.
SAME_BATCH = timedelta(seconds=5)
#: Who approved a still in its own round (`stills_stage.GATE_REVIEWER`).
GATE_REVIEWER = "still_gate"
#: The events that say when a take was approved after its round: her choice on a film's repair
#: (`director_qc.LOOK_EVENT`), the note on a take she or a look approved
#: (`fix_check.TAKE_NOTE_EVENT`), and clip QC passing a clip (`assembler.CLIP_QC_EVENT`).
DIRECTOR_TAKE_LOOK_EVENT = "media.director_take_look"
TAKE_NOTE_EVENT = "media.take_quality_note"
CLIP_QC_EVENT = "media.clip_qc_checked"
#: A take the vendor never ran: refused with one of these, or with no credits quoted.
NEVER_RAN_CODES = ("RUNPOD.CANCELLED", "RUNPOD.EXPIRED_UNDELIVERED")

KIND_RO = {"still": "imagine", "shot": "clip", "film_scene": "scenă din film"}
VERDICT_RO = {
    "CONFIRMED": "refuz corect",
    "OVERTURNED": "refuz greșit",
    "UNAVAILABLE": "nu s-a putut uita",
    "NOT_SHOWN": "nu i s-a putut arăta",
    None: "— (probă, nu a fost întrebată)",
}
SEVERITY_RO = {"none": "fără defect", "minor": "defect mic", "serious": "defect serios"}
LAYER_RO = {"still": "imaginea", "motion": "mișcarea"}
SOURCE_RO = {
    "SHOT": "cadrul scenei, înainte de subtitrări",
    "FILM": "filmul",
    "FILM_CROPPED": "filmul, fără rândurile subtitrărilor",
    "FILM_CLEAR": "filmul, fără subtitrări pe ecran",
    "CLIP": "clipul, tăiat ca în film",
    "STILL": "imaginea",
}
#: What a refused clip is shown as: its own first, middle and last frame, as clip QC judged it.
SHOT_SOURCE_RO = "clipul cumpărat (primul, mijlocul și ultimul cadru)"


def source_ro(kind: str, source: str | None) -> str:
    """Where the pictures she was shown came from, in the Owner's words."""
    if not source:
        return "—"
    if kind == "shot":
        return SHOT_SOURCE_RO
    if kind == "film_scene" and source == "STILL":
        return "imaginea din care s-a filmat scena"
    return SOURCE_RO.get(source, source)


_PICTURE_QC_WORDS = {
    "is_a_picture": "nu este o imagine",
    "one_picture": "nu este o singură imagine",
    "shows_the_scene": "nu arată scena",
}


# ----------------------------------------------------------------------------- the copy


def copy_database(
    source: Path, folder: Path, *, tries: int = COPY_TRIES, wait: float = COPY_WAIT_SECONDS
) -> Path:
    """Copy the studio's database (and its WAL and SHM when they exist) into ``folder``; the
    copy's path. The live files are only read, by `shutil.copyfile`, never opened as a database.
    A file SQLite holds for a moment (PermissionError) is tried again ``tries`` times."""
    if not source.is_file():
        raise FileNotFoundError(f"Baza de date nu există: {source}")
    folder.mkdir(parents=True, exist_ok=True)
    for suffix in DB_SUFFIXES:
        live = source.with_name(source.name + suffix)
        target = folder / (source.name + suffix)
        if not live.exists():
            target.unlink(missing_ok=True)
            continue
        for attempt in range(tries):
            try:
                shutil.copyfile(live, target)
                break
            except PermissionError:
                if attempt == tries - 1:
                    raise
                time.sleep(wait)
    return folder / source.name


def live_database(argument: str | None) -> Path:
    """The live database: ``--database``, else the studio's own settings, else data/studio.db."""
    if argument:
        path = Path(argument)
        return path if path.is_absolute() else ROOT / path
    try:
        from app.config import Settings  # noqa: PLC0415 - only without an explicit path
        from sqlalchemy.engine import make_url  # noqa: PLC0415

        path = Path(str(make_url(Settings().database_url).database))  # type: ignore[call-arg]
        return path if path.is_absolute() else ROOT / path
    except Exception:  # noqa: BLE001 - no usable settings: the studio's default place
        return ROOT / "data" / "studio.db"


def director_registry(engine: Any, live_db: Path) -> tuple[Any, dict[str, Any]]:
    """The registry holding only the Director's seeing model's provider, built the way the
    studio builds its registry at start; and what was found (model name, provider, how many
    connections could not be read). The vault's key is read where the studio keeps it, beside
    the LIVE database (`main.create_app`: the database path with ``.credentials.key``)."""
    from app.agents.memory import agent_for_role  # noqa: PLC0415
    from app.agents.models import ModelRecord  # noqa: PLC0415
    from app.agents.vision import seeing_model  # noqa: PLC0415
    from app.integrations.services import load_registry  # noqa: PLC0415
    from app.integrations.vault import CredentialVault  # noqa: PLC0415
    from app.main import register_seeded_ollama  # noqa: PLC0415
    from app.media.picture_qc import LOOKERS  # noqa: PLC0415
    from app.providers.registry import ProviderRegistry  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    vault = CredentialVault(live_db.with_suffix(".credentials.key"))
    every = ProviderRegistry()
    skipped = load_registry(engine, vault, every)
    register_seeded_ollama(engine, every)
    with Session(engine) as session:
        director = agent_for_role(session, "Director")
        model_id = seeing_model(session, director.id, *LOOKERS) if director else None
        record = session.get(ModelRecord, model_id) if model_id else None
        found = {
            "director": director.display_name if director is not None else None,
            "model": record.model_name if record is not None else None,
            "provider_id": record.provider_id if record is not None else None,
            "connections_not_read": len(skipped),
        }
    only = ProviderRegistry()
    adapter = every.get(found["provider_id"]) if found["provider_id"] else None
    if adapter is not None:
        only.register(found["provider_id"], adapter)
    found["registered"] = adapter is not None
    return only, found


# ------------------------------------------------------------------------ what was refused


def _when(text: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def _on_day(text: Any, day: str) -> bool:
    return str(text or "").startswith(day)


_OPENERS = {"(": ")", "[": "]", "«": "»", "“": "”", "„": "”"}
_CLOSERS = frozenset(_OPENERS.values())


def split_reasons(text: Any) -> list[str]:
    """Quality control's reasons as it wrote them, one sentence each, from their «; » join: a
    «; » splits only outside parentheses, brackets and quotes, and only before a sentence that
    starts with a capital — so «(rândurile 394-465 din 480, 15% din înălțime; prag 15%)», a
    quoted bible rule «No written words …; Pages and screens are blank» and «YuNet a găsit 1
    față în imagine; biblia vizuală interzice fețele» each stay whole (review of 2026-10-12)."""
    said = " ".join(str(text or "").split())
    parts: list[str] = []
    current: list[str] = []
    expected: list[str] = []
    index = 0
    while index < len(said):
        char = said[index]
        if char in _OPENERS:
            expected.append(_OPENERS[char])
        elif char in _CLOSERS and char in expected:
            while expected and expected.pop() != char:
                pass
        rest = said[index + 2 :]
        if (
            char == ";"
            and not expected
            and said[index + 1 : index + 2] == " "
            and rest[:1].isalpha()
            and rest[:1].isupper()
        ):
            parts.append("".join(current).strip())
            current = []
            index += 2
            continue
        current.append(char)
        index += 1
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def _title(session: Any, storyboard_id: str, titles: dict[str, str]) -> str:
    from app.media.models import Storyboard  # noqa: PLC0415

    if storyboard_id not in titles:
        board = session.get(Storyboard, storyboard_id)
        words = str(board.title if board is not None else "") or storyboard_id[:8]
        titles[storyboard_id] = words.removeprefix("Storyboard: ").strip() or storyboard_id[:8]
    return titles[storyboard_id]


def still_gate_words(session: Any, take: Any) -> list[str]:
    """The stills gate's whole words for a refused still: the verdict it recorded on the take's
    generation job in the same transaction (`runpod.wiring.sync_take_quality`, up to 4,000
    characters), else the take's ``failure_detail`` (cut at 500), split into its sentences."""
    from app.providers.runpod.jobs import GenerationJob  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    recorded = None
    if take.remote_task_id:
        recorded = session.scalars(
            select(GenerationJob.quality_result)
            .where(
                GenerationJob.remote_job_id == take.remote_task_id,
                GenerationJob.project_id == take.storyboard_id,
                GenerationJob.scene_id == str(take.scene_number),
            )
            .limit(1)
        ).first()
    words = str(recorded or "").strip()
    if not words or words in ("PASSED", "REJECTED"):
        words = str(take.failure_detail or "")
    return split_reasons(words)


def next_film_qc(session: Any, storyboard_id: str, after: Any) -> str | None:
    """The storyboard's next film QC report (any verdict, any day) after ``after``: a film made
    since then answers whatever came before it, so a refusal's window of purchases ends there."""
    from app.media.models import QualityControlReport, VideoRenderJob  # noqa: PLC0415
    from sqlalchemy import func, select  # noqa: PLC0415

    if not after:
        return None
    return session.scalar(
        select(func.min(QualityControlReport.verified_at))
        .join(
            VideoRenderJob,
            VideoRenderJob.output_asset_id == QualityControlReport.media_asset_id,
        )
        .where(
            VideoRenderJob.storyboard_id == storyboard_id,
            QualityControlReport.verified_at > str(after),
        )
    )


def refused_takes(session: Any, day: str, titles: dict[str, str]) -> list[dict[str, Any]]:
    """The stills the gate refused and the clips the clip QC refused on ``day``, oldest first."""
    from app.media.assembler import clip_qc_of  # noqa: PLC0415 - a large module
    from app.media.models import SceneTake  # noqa: PLC0415
    from sqlalchemy import or_, select  # noqa: PLC0415

    rows = session.scalars(
        select(SceneTake)
        .where(
            SceneTake.failure_code.in_((STILL_GATE_CODE, CLIP_QC_CODE)),
            SceneTake.status == "REJECTED",
            or_(SceneTake.updated_at.like(f"{day}%"), SceneTake.created_at.like(f"{day}%")),
        )
        .order_by(SceneTake.created_at, SceneTake.id)
    ).all()
    items: list[dict[str, Any]] = []
    for row in rows:
        shot = row.failure_code == CLIP_QC_CODE
        if shot and row.kind not in SHOT_KINDS:
            continue
        if not shot and row.kind != "still":
            continue
        if shot:
            record = clip_qc_of(session, row.id) or {}
            blocks = [str(text) for text in record.get("blocks_ro") or [] if str(text).strip()]
            refusal = blocks or split_reasons(
                str(row.failure_detail or "").removeprefix("Controlul clipului: ")
            )
        else:
            refusal = still_gate_words(session, row)
        items.append(
            {
                "kind": "shot" if shot else "still",
                "storyboard_id": row.storyboard_id,
                "film": _title(session, row.storyboard_id, titles),
                "scene_index": int(row.scene_number),
                "take_ids": [row.id],
                "take_kind": row.kind,
                "refusal": refusal or ["(fără motiv scris)"],
                "bought_at": row.created_at,
                "refused_at": row.updated_at,
                "file": row.path,
                "sha256": row.sha256,
                "credits_quoted": row.credits_quoted,
                "round_ends_at": next_film_qc(session, row.storyboard_id, row.updated_at),
            }
        )
    return items


def _picture_qc_words(entry: Mapping[str, Any], checks: Mapping[str, Any]) -> list[str]:
    """The one-frame look's words for a scene it refused: which of its questions failed and
    why, and each character it found unlike the bible (`picture_qc.scene_state` reads both)."""
    said = [words for key, words in _PICTURE_QC_WORDS.items() if entry.get(key) is False]
    reason = " ".join(str(entry.get("reason") or "").split())
    out = []
    if said:
        tail = f" — {reason}" if reason else ""
        out.append(f"Privirea pe un cadru al scenei: {', '.join(said)}{tail}")
    drift = checks.get("character_drift_qc")
    for person in (drift.get("characters") if isinstance(drift, Mapping) else None) or []:
        if (
            isinstance(person, Mapping)
            and person.get("scene") == entry.get("scene")
            and person.get("status") == "MEASURED"
            and person.get("matches") is False
        ):
            why = " ".join(str(person.get("reason") or "").split())
            out.append(
                f"Personajul {person.get('character') or '?'} nu seamănă cu biblia"
                + (f" — {why}" if why else "")
            )
    return out or [f"Privirea pe un cadru al scenei: nu a trecut — {reason or 'fără motiv'}"]


def refused_film_scenes(session: Any, day: str, titles: dict[str, str]) -> list[dict[str, Any]]:
    """Every scene a FAILED film QC report of ``day`` found at fault on its pictures, with the
    checks' own words, the frame numbers the span look recorded, and the takes it was cut from."""
    from app.media.models import QualityControlReport, VideoRenderJob  # noqa: PLC0415
    from app.media.picture_qc import scene_state, scene_takes  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    reports = session.scalars(
        select(QualityControlReport)
        .where(
            QualityControlReport.status == "FAILED",
            QualityControlReport.verified_at.like(f"{day}%"),
        )
        .order_by(QualityControlReport.verified_at, QualityControlReport.id)
    ).all()
    jobs = {
        job.output_asset_id: job
        for job in session.scalars(
            select(VideoRenderJob).where(
                VideoRenderJob.output_asset_id.in_([r.media_asset_id for r in reports])
            )
        )
    }
    items: list[dict[str, Any]] = []
    for report in reports:
        job = jobs.get(report.media_asset_id)
        if job is None:
            continue
        checks = report.checks_json if isinstance(report.checks_json, dict) else {}
        production = job.production_json if isinstance(job.production_json, dict) else {}
        takes = scene_takes(production)
        found: dict[int, dict[str, Any]] = {}
        spans = checks.get("picture_spans_qc")
        for entry in (spans.get("scenes") if isinstance(spans, Mapping) else None) or []:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("scene_index"), int):
                continue
            if entry.get("passed") is not False and entry.get("status") != "FAILED":
                continue
            scene = found.setdefault(int(entry["scene_index"]), {"refusal": [], "frames": []})
            reason = " ".join(str(entry.get("reason") or "").split())
            scene["refusal"].append(
                "Cadrele scenei din film: " + (reason or "scena nu a trecut controlul")
            )
            scene["frames"] = [
                int(frame["frame"])
                for frame in entry.get("frames") or []
                if isinstance(frame, Mapping) and isinstance(frame.get("frame"), int)
            ]
        looks = checks.get("picture_qc")
        for entry in (looks.get("scenes") if isinstance(looks, Mapping) else None) or []:
            if not isinstance(entry, Mapping) or not isinstance(entry.get("scene"), int):
                continue
            index = int(entry["scene"])
            if scene_state(checks, "picture_qc", index) is not False:
                continue
            scene = found.setdefault(index, {"refusal": [], "frames": []})
            scene["refusal"] += _picture_qc_words(entry, checks)
        # The storyboard's next film QC (any verdict, any day) closes this report's repair round.
        later = next_film_qc(session, job.storyboard_id, report.verified_at)
        for index in sorted(found):
            still_id, clip_id = takes.get(index, (None, None))
            items.append(
                {
                    "kind": "film_scene",
                    "storyboard_id": job.storyboard_id,
                    "film": _title(session, job.storyboard_id, titles),
                    "scene_index": index,
                    "take_ids": [take for take in (still_id, clip_id) if take],
                    "refusal": found[index]["refusal"],
                    "bought_at": None,
                    "refused_at": report.verified_at,
                    "report_ids": [report.id],
                    "media_asset_id": report.media_asset_id,
                    "frame_numbers": found[index]["frames"],
                    "reports": [
                        {
                            "report_id": report.id,
                            "media_asset_id": report.media_asset_id,
                            "frame_numbers": found[index]["frames"],
                        }
                    ],
                    "round_ends_at": later,
                }
            )
    return same_picture_once(items)


def same_picture_once(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One look per picture: a scene refused by several film reports while cut from the very
    same still and clip (2026-10-12 on the database copy: «The Zero Script Club» scene 4 was
    refused by three films and scene 7 by two, the same takes each time) is shown to her once,
    with every report's words. Its round runs from the first refusal to the film QC after the
    last one: until then the scene's picture did not change, so whatever was bought for it
    answered these refusals. Every report is kept (``reports``) and the frames she is shown are
    a report's that recorded the frames it judged (review of 2026-10-12: 1c038a99 scene 5 merged
    b298cec6, which recorded none, with 879e57fa, which did, and kept the empty list)."""
    merged: dict[tuple[str, int, tuple[str, ...]], dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for item in items:
        if not item["take_ids"]:
            out.append(item)
            continue
        key = (str(item["storyboard_id"]), int(item["scene_index"]), tuple(item["take_ids"]))
        first = merged.get(key)
        if first is None:
            merged[key] = item
            out.append(item)
            continue
        first["report_ids"] += item["report_ids"]
        first.setdefault("reports", [])
        first["reports"] += item.get("reports") or []
        first["refusal"] += [words for words in item["refusal"] if words not in first["refusal"]]
        first["round_ends_at"] = item["round_ends_at"]
        if not first.get("frame_numbers") and item.get("frame_numbers"):
            first["frame_numbers"] = item["frame_numbers"]
            first["media_asset_id"] = item["media_asset_id"]
    return out


def collect(engine: Any, day: str) -> list[dict[str, Any]]:
    """Every refusal of ``day``: stills, then clips, then film scenes, each oldest first."""
    from sqlalchemy.orm import Session  # noqa: PLC0415

    titles: dict[str, str] = {}
    with Session(engine) as session:
        takes = refused_takes(session, day, titles)
        films = refused_film_scenes(session, day, titles)
    stills = [item for item in takes if item["kind"] == "still"]
    shots = [item for item in takes if item["kind"] == "shot"]
    return stills + shots + films


def prepare(
    engine: Any, item: Mapping[str, Any], *, work_dir: Path, ffmpeg_path: str | None
) -> tuple[list[str], str | None, str | None, dict[str, Any] | None]:
    """What she would be shown of one refusal: (local picture paths, where they came from, why
    nothing can be shown, what each picture is for a film scene). Cutting frames is local and
    free; nothing is bought or asked. A film scene is cut from the film of the first report
    that recorded the frames it judged, else of any of its reports."""
    from app.media.second_look import (  # noqa: PLC0415
        _file_sha256,
        film_scene_view,
        frames_of,
    )

    if item["kind"] == "film_scene":
        reports = list(item.get("reports") or []) or [
            {
                "media_asset_id": item.get("media_asset_id"),
                "frame_numbers": item.get("frame_numbers") or [],
            }
        ]
        reports.sort(key=lambda entry: 0 if entry.get("frame_numbers") else 1)
        for entry in reports:
            if not entry.get("media_asset_id"):
                continue
            images, view = film_scene_view(
                engine,
                str(entry["media_asset_id"]),
                int(item["scene_index"]),
                work_dir=work_dir,
                ffmpeg_path=ffmpeg_path,
                frame_numbers=entry.get("frame_numbers") or (),
            )
            if images and view is not None:
                return images, str(view["source"]), None, view
        return [], None, "nici filmul, nici preluările scenei nu mai sunt pe disc", None
    file = Path(str(item.get("file") or ""))
    if not item.get("file") or not file.is_file():
        return [], None, "fișierul preluării nu mai este pe disc", None
    if item.get("sha256") and _file_sha256(file) != item["sha256"]:
        return [], None, "fișierul de pe disc nu mai este cel cumpărat", None
    frames = frames_of(file, item["kind"], work_dir=work_dir, ffmpeg_path=ffmpeg_path)
    if not frames:
        return [], None, "cadrele clipului nu au putut fi tăiate (lipsește codorul)", None
    return frames, ("STILL" if item["kind"] == "still" else "CLIP"), None, None


# ------------------------------------------------------------------- the money it answered


def _redo_layers(kind: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(what a redo of this refusal buys, the layer whose approval settles the scene)."""
    if kind == "still":
        return ("still",), ("still",)
    return ("still", *SHOT_KINDS), SHOT_KINDS


def approval_moments(session: Any, takes: Sequence[Any]) -> dict[str, datetime]:
    """When each take was approved, as the records say — whatever it is now (a retired take is
    REJECTED and keeps its ``approved_by``): a still the gate approved, in its own round (its
    ``created_at``); one approved later, when her choice or the note on it was written
    (`media.director_take_look`, `media.take_quality_note`), else its ``updated_at``; a clip,
    also when clip QC first passed it (`media.clip_qc_checked`). Absent: never approved."""
    from app.models import DomainEvent  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    ids = [str(take.id) for take in takes]
    if not ids:
        return {}
    chosen: dict[str, datetime] = {}
    noted: dict[str, datetime] = {}
    passed: dict[str, datetime] = {}

    def keep(into: dict[str, datetime], take_id: str, moment: datetime | None) -> None:
        if moment is not None and (take_id not in into or moment < into[take_id]):
            into[take_id] = moment

    for event in session.scalars(
        select(DomainEvent).where(DomainEvent.event_type == DIRECTOR_TAKE_LOOK_EVENT)
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        take_id = str(payload.get("chosen_take_id") or "")
        if take_id in ids and payload.get("approved") is not False:
            keep(chosen, take_id, _when(event.timestamp))
    for event in session.scalars(
        select(DomainEvent).where(
            DomainEvent.event_type.in_((TAKE_NOTE_EVENT, CLIP_QC_EVENT)),
            DomainEvent.aggregate_id.in_(ids),
        )
    ):
        payload = event.payload if isinstance(event.payload, dict) else {}
        if event.event_type == TAKE_NOTE_EVENT and payload.get("approved_by"):
            keep(noted, event.aggregate_id, _when(event.timestamp))
        elif event.event_type == CLIP_QC_EVENT and payload.get("verdict") == "PASSED":
            keep(passed, event.aggregate_id, _when(event.timestamp))
    out: dict[str, datetime] = {}
    for take in takes:
        moments: list[datetime] = []
        if take.approved_by == GATE_REVIEWER:
            moments.append(_when(take.created_at) or datetime.max.replace(tzinfo=UTC))
        elif take.approved_by:
            found = [chosen.get(take.id), noted.get(take.id)]
            known = [moment for moment in found if moment is not None]
            moments += known or [_when(take.updated_at) or datetime.max.replace(tzinfo=UTC)]
        if take.kind in SHOT_KINDS and take.id in passed:
            moments.append(passed[take.id])
        if moments:
            out[str(take.id)] = min(moments)
    return out


def _batch(take: Any) -> str | None:
    """The vendor batch a take was bought in (RunPod's «<job>:<item>»), when it says."""
    remote = str(take.remote_task_id or "")
    return remote.rsplit(":", 1)[0] if ":" in remote else None


def same_batch(one: Any, other: Any) -> bool:
    """Whether two takes were one purchase: the same vendor batch, else made within
    `SAME_BATCH` of each other."""
    first, second = _batch(one), _batch(other)
    if first and second:
        return first == second
    a, b = _when(one.created_at), _when(other.created_at)
    return a is not None and b is not None and abs(a - b) <= SAME_BATCH


def never_ran(take: Any) -> bool:
    """A take the vendor never ran (cancelled, expired undelivered, or refused with no credits
    quoted): nothing was paid for it."""
    return take.status == "REFUSED" and (
        take.failure_code in NEVER_RAN_CODES or not take.credits_quoted
    )


def bought_for(
    session: Any, row: Mapping[str, Any], day: str, counted: set[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(the takes bought on ``day`` because of this refusal, the takes ordered for it that the
    vendor never ran). For the same scene, after the refusal, of what its redo buys (a still:
    stills; a clip or a film scene: stills and clips), until the storyboard's next film QC
    (a film made since answers whatever came before it) and, for a still or a clip, until the
    scene's layer got a take approved — approved as the records say at the time, not as it is
    now (`approval_moments`: a take retired since is still the one that settled it) — whose
    whole purchase (every candidate of its batch, `same_batch`) is counted. Nothing when a
    sibling candidate of the refused one's own round was approved by then: the round settled
    the scene. Each take is attributed once (``counted``). A quote is not a purchase."""
    from app.media.models import SceneTake  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415

    buys, settles = _redo_layers(str(row["kind"]))
    since = _when(row.get("refused_at"))
    if since is None:
        return [], []
    takes = session.scalars(
        select(SceneTake)
        .where(
            SceneTake.storyboard_id == row["storyboard_id"],
            SceneTake.scene_number == int(row["scene_index"]),
            SceneTake.kind.in_(buys),
        )
        .order_by(SceneTake.created_at, SceneTake.id)
    ).all()
    approved = approval_moments(session, takes)
    film = row["kind"] == "film_scene"
    bought_at = _when(row.get("bought_at"))
    if not film and bought_at is not None:
        for take in takes:
            moment = _when(take.created_at)
            settled = approved.get(str(take.id))
            if (
                take.id not in row["take_ids"]
                and take.kind in settles
                and moment is not None
                and settled is not None
                and bought_at - SAME_ROUND <= moment <= since
                and settled <= since
            ):
                return [], []
    until = _when(row.get("round_ends_at"))
    bought: list[dict[str, Any]] = []
    cancelled: list[dict[str, Any]] = []
    settling: Any = None
    settled_at: datetime | None = None
    for take in takes:
        moment = _when(take.created_at)
        if moment is None or moment <= since or not _on_day(take.created_at, day):
            continue
        if until is not None and moment >= until:
            break
        if (
            settling is not None
            and settled_at is not None
            and moment > settled_at
            and not same_batch(take, settling)
        ):
            break
        if take.id in row["take_ids"] or take.status == "QUOTED":
            continue
        unpaid = never_ran(take)
        if take.id not in counted:
            counted.add(take.id)
            (cancelled if unpaid else bought).append(
                {
                    "take_id": take.id,
                    "kind": take.kind,
                    "status": take.status,
                    "failure_code": take.failure_code,
                    "credits_quoted": None if unpaid else take.credits_quoted,
                    "created_at": take.created_at,
                }
            )
        if settling is None and not film and not unpaid and take.kind in settles:
            when = approved.get(str(take.id))
            if when is not None:
                settling, settled_at = take, max(when, moment)
    return bought, cancelled


# ----------------------------------------------------------------------------- the audit


def audit(
    engine: Any,
    registry: Any | None,
    items: list[dict[str, Any]],
    *,
    day: str,
    dry_run: bool,
    work_dir: Path,
    ffmpeg_path: str | None = None,
    echo: Callable[[str], None] = print,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Show each refusal to the Director (or, in a dry run, only list what would be shown);
    (the rows, the totals). Her looks of this run are never shown to her as earlier looks: she
    is asked every candidate of a scene in a row, and her verdict on one is not the next one's."""
    from app.media.second_look import second_look  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    correlation = f"qc_audit:{day}:{uuid4()}"
    rows: list[dict[str, Any]] = []
    for number, item in enumerate(items, start=1):
        images, source, why, view = prepare(
            engine, item, work_dir=work_dir / "frames", ffmpeg_path=ffmpeg_path
        )
        row: dict[str, Any] = {
            **item,
            "images": images,
            "frames_from": source,
            "view": view,
            "verdict": None,
            "severity": None,
            "redo": None,
            "reason_ro": why,
            "run_id": None,
            "cause": None,
            "lesson": None,
            "layer": None,
        }
        if not dry_run:
            if not images:
                row["verdict"] = "NOT_SHOWN"
            else:
                look = second_look(
                    engine,
                    registry,
                    storyboard_id=str(item["storyboard_id"]),
                    scene_index=int(item["scene_index"]),
                    kind=item["kind"],
                    images=images,
                    refusal=list(item["refusal"]),
                    correlation_id=correlation,
                    take_ids=list(item["take_ids"]),
                    ffmpeg_path=ffmpeg_path,
                    work_dir=work_dir / "frames",
                    view=view,
                    earlier_looks_skip=correlation,
                )
                row.update(
                    {
                        key: look.get(key)
                        for key in (
                            "verdict",
                            "severity",
                            "redo",
                            "reason_ro",
                            "run_id",
                            "cause",
                            "lesson",
                            "layer",
                        )
                    }
                )
        rows.append(row)
        echo(
            f"[{number}/{len(items)}] «{row['film'][:50]}» scena {row['scene_index']} "
            f"({KIND_RO[row['kind']]}"
            + (
                f"; i se arată {source_ro(row['kind'], source)}, {len(images)} "
                + ("imagine" if len(images) == 1 else "imagini")
                if images
                else ""
            )
            + "): "
            + (VERDICT_RO.get(row["verdict"], str(row["verdict"])))
            + (f", {SEVERITY_RO.get(row['severity'], row['severity'])}" if row["severity"] else "")
        )
    counted: set[str] = set()
    with Session(engine) as session:
        for row in rows:
            bought, cancelled = (
                bought_for(session, row, day, counted)
                if row["verdict"] == "OVERTURNED"
                else ([], [])
            )
            row["bought_after"] = bought
            row["cancelled_after"] = cancelled
    return rows, totals(rows, dry_run=dry_run)


def totals(rows: list[dict[str, Any]], *, dry_run: bool) -> dict[str, Any]:
    by_kind = {kind: sum(1 for row in rows if row["kind"] == kind) for kind in KIND_RO}
    verdicts = {
        verdict: sum(1 for row in rows if row["verdict"] == verdict)
        for verdict in ("CONFIRMED", "OVERTURNED", "UNAVAILABLE", "NOT_SHOWN")
    }
    redos = [take for row in rows for take in row.get("bought_after") or []]
    cancelled = [take for row in rows for take in row.get("cancelled_after") or []]
    return {
        "dry_run": dry_run,
        "refusals": len(rows),
        "by_kind": by_kind,
        "shown": sum(1 for row in rows if row["images"]),
        **{verdict.lower(): count for verdict, count in verdicts.items()},
        "overturned_minor": sum(
            1 for row in rows if row["verdict"] == "OVERTURNED" and row["severity"] == "minor"
        ),
        "redos_for_overturned": len(redos),
        "redo_credits_for_overturned": round(
            sum(float(take["credits_quoted"] or 0) for take in redos), 2
        ),
        "redos_without_quote": sum(1 for take in redos if take["credits_quoted"] is None),
        "cancelled_unpaid_for_overturned": len(cancelled),
    }


def per_film(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per film, in the order its first refusal came: refusals seen, confirmed, overturned, and
    the credits bought that day on redos of the refusals she overturned."""
    films: dict[str, dict[str, Any]] = {}
    for row in rows:
        film = films.setdefault(
            str(row["storyboard_id"]),
            {
                "film": row["film"],
                "refusals": 0,
                "confirmed": 0,
                "overturned": 0,
                "redos": 0,
                "credits": 0.0,
                "cancelled": 0,
            },
        )
        film["refusals"] += 1
        film["confirmed"] += row["verdict"] == "CONFIRMED"
        film["overturned"] += row["verdict"] == "OVERTURNED"
        film["redos"] += len(row.get("bought_after") or [])
        film["credits"] += sum(
            float(t["credits_quoted"] or 0) for t in row.get("bought_after") or []
        )
        film["cancelled"] += len(row.get("cancelled_after") or [])
    for film in films.values():
        film["credits"] = round(film["credits"], 2)
    return list(films.values())


def summary_table(rows: list[dict[str, Any]], summary: Mapping[str, Any], day: str) -> str:
    """The short table per film, in Romanian, as the run prints it at the end."""
    dry = bool(summary["dry_run"])
    lines = [
        f"Rezumat pe filme — refuzurile controlului din {day}"
        + (" (probă: Directoarea nu a fost întrebată)" if dry else "")
        + ":",
        "",
        "| Film | Refuzuri văzute | Confirmate de ea | Răsturnate de ea | Credite cheltuite azi "
        "pe refaceri ale refuzurilor răsturnate |",
        "|---|---:|---:|---:|---:|",
    ]
    films = per_film(rows)
    for film in films:
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(film["film"], 60),
                    str(film["refusals"]),
                    "—" if dry else str(film["confirmed"]),
                    "—" if dry else str(film["overturned"]),
                    "—" if dry else f"{film['credits']:g} ({film['redos']} preluări)",
                ]
            )
            + " |"
        )
    lines.append(
        "| **Total** | "
        + " | ".join(
            [
                str(summary["refusals"]),
                "—" if dry else str(summary["confirmed"]),
                "—" if dry else str(summary["overturned"]),
                "—"
                if dry
                else f"{summary['redo_credits_for_overturned']:g} "
                f"({summary['redos_for_overturned']} preluări)",
            ]
        )
        + " |"
    )
    if not dry and summary.get("cancelled_unpaid_for_overturned"):
        lines += [
            "",
            f"Anulate, neplătite (nu se numără): {summary['cancelled_unpaid_for_overturned']}.",
        ]
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------------- the report


def _cell(text: Any, limit: int = 300) -> str:
    words = " ".join(str(text if text is not None else "").split()).replace("|", "/")
    return words if len(words) <= limit else words[: limit - 1].rstrip() + "…"


def markdown(
    rows: list[dict[str, Any]], summary: Mapping[str, Any], meta: Mapping[str, Any]
) -> str:
    """The report in Romanian: one row per refusal, then the totals and the table per film."""
    lines = [
        f"# A doua privire a Directoarei — refuzurile controlului din {meta['day']}",
        "",
        (
            "Rulare de probă: Directoarea nu a fost întrebată; tabelul arată ce i s-ar arăta."
            if summary["dry_run"]
            else f"Directoarea s-a uitat cu modelul {meta.get('model') or '—'}, pe o copie a "
            "bazei de date; nu s-a cumpărat nimic și nu s-a scris nimic în baza studioului."
        ),
        "",
        "| Film | Scena | Tip | Preluare | Ce i s-a arătat | Ce a spus controlul | Verdictul ei | "
        "Gravitate | Se reface? | Motivul ei | De ce apare / lecția |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        redo = "—" if row["redo"] is None else ("da" if row["redo"] else "nu")
        cause = " ".join(
            part
            for part in (
                f"[{LAYER_RO[row['layer']]}]" if row.get("layer") in LAYER_RO else "",
                str(row.get("cause") or ""),
                f"Lecția: {row['lesson']}" if row.get("lesson") else "",
            )
            if part
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _cell(row["film"], 60),
                    str(row["scene_index"]),
                    KIND_RO[row["kind"]],
                    _cell(", ".join(take[:8] for take in row["take_ids"]) or "—", 40),
                    source_ro(row["kind"], row.get("frames_from")),
                    _cell("; ".join(row["refusal"]), 300),
                    VERDICT_RO.get(row["verdict"], str(row["verdict"])),
                    SEVERITY_RO.get(row["severity"], "—") if row["severity"] else "—",
                    redo,
                    _cell(row["reason_ro"] or "—", 400),
                    _cell(cause or "—", 400),
                ]
            )
            + " |"
        )
    kinds = summary["by_kind"]
    lines += [
        "",
        "## Totaluri",
        "",
        f"- Refuzuri găsite: {summary['refusals']} (imagini {kinds['still']}, clipuri "
        f"{kinds['shot']}, scene din filme {kinds['film_scene']}); arătate Directoarei: "
        f"{summary['shown']}.",
    ]
    if not summary["dry_run"]:
        lines += [
            f"- Refuzuri confirmate de ea: {summary['confirmed']}.",
            f"- Refuzuri răsturnate de ea: {summary['overturned']} (din care cu un defect mic "
            f"acceptat: {summary['overturned_minor']}).",
            f"- Nu s-a putut uita: {summary['unavailable']}; nu i s-au putut arăta: "
            f"{summary['not_shown']}.",
            f"- Refaceri cumpărate în {meta['day']} pentru refuzurile pe care ea le-a răsturnat: "
            f"{summary['redos_for_overturned']}, {summary['redo_credits_for_overturned']:g} "
            "credite (prețul cotat al fiecărei preluări"
            + (
                f"; {summary['redos_without_quote']} fără preț cotat"
                if summary["redos_without_quote"]
                else ""
            )
            + "). Se numără, pentru aceeași scenă, preluările cumpărate după refuz până la "
            "următorul control al filmului și, pentru o imagine sau un clip, până când scena a "
            "primit o preluare aprobată atunci (chiar dacă a fost retrasă de atunci), cu toată "
            "runda ei; nimic, dacă o altă variantă din aceeași rundă fusese aprobată.",
            f"- Anulate, neplătite (comandate, dar nerulate de furnizor; nu se numără): "
            f"{summary['cancelled_unpaid_for_overturned']}.",
        ]
    lines += ["", "## Pe filme", "", summary_table(rows, summary, str(meta["day"]))]
    return "\n".join(lines) + "\n"


def write_report(
    folder: Path, rows: list[dict[str, Any]], summary: Mapping[str, Any], meta: Mapping[str, Any]
) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"qc_audit_{meta['day']}" + ("_proba" if summary["dry_run"] else "")
    data = folder / f"{stem}.json"
    table = folder / f"{stem}.md"
    data.write_text(
        json.dumps(
            {
                "meta": dict(meta),
                "totals": dict(summary),
                "films": per_film(rows),
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    table.write_text(markdown(rows, summary, meta), encoding="utf-8")
    return data, table


# ------------------------------------------------------------------------------- main


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--day", default=datetime.now(UTC).date().isoformat(), help="YYYY-MM-DD")
    parser.add_argument("--database", help="the studio's database (default: its settings)")
    parser.add_argument(
        "--work",
        default=str(Path(tempfile.gettempdir()) / "amn_qc_audit"),
        help="the folder the copy, the frames and the report are written to",
    )
    parser.add_argument("--dry-run", action="store_true", help="list only; ask no model")
    parser.add_argument("--limit", type=int, default=0, help="look at the first N refusals only")
    parser.add_argument("--ffmpeg", help="the encoder's path (default: the studio's own search)")
    args = parser.parse_args(list(argv) if argv is not None else None)
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    try:
        datetime.strptime(args.day, "%Y-%m-%d")
    except ValueError:
        print(f"Ziua nu este de forma AAAA-LL-ZZ: {args.day}", file=sys.stderr)
        return 2

    from app.db import create_db_engine  # noqa: PLC0415

    source = live_database(args.database)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.work) / f"qc_audit_{args.day}_{stamp}"
    try:
        copy = copy_database(source, run_dir / "db")
    except OSError as exc:
        print(f"Baza de date nu a putut fi copiată: {exc}", file=sys.stderr)
        return 2
    print(f"Copia bazei de date: {copy}")
    engine = create_db_engine(f"sqlite:///{copy.as_posix()}")
    try:
        items = collect(engine, args.day)
        if args.limit and args.limit > 0:
            items = items[: args.limit]
        meta: dict[str, Any] = {
            "day": args.day,
            "database_copy": str(copy),
            "made_at": datetime.now(UTC).isoformat(),
            "limit": args.limit or None,
        }
        registry = None
        if not args.dry_run:
            registry, found = director_registry(engine, source)
            meta.update(found)
            if not found["registered"]:
                print(
                    "Directoarea nu are un model care vede, sau conexiunea lui nu a putut fi "
                    "citită: fiecare refuz va fi «nu s-a putut uita».",
                    file=sys.stderr,
                )
            else:
                print(f"Directoarea se uită cu modelul {found['model']}.")
        print(f"Refuzuri din {args.day}: {len(items)}")
        rows, summary = audit(
            engine,
            registry,
            items,
            day=args.day,
            dry_run=args.dry_run,
            work_dir=run_dir,
            ffmpeg_path=args.ffmpeg,
        )
        data, table = write_report(run_dir, rows, summary, meta)
    finally:
        engine.dispose()
    print(f"Raportul (JSON): {data}")
    print(f"Raportul: {table}")
    print()
    print(summary_table(rows, summary, args.day), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
