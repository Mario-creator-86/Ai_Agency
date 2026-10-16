"""The writers' frozen evaluation: the same past days, written again, judged blind — offline.

Why. The Owner, 2026-10-16, on the serial's approved episode «Zero Scripts, Blocked Log»: «Eu nu
înțeleg nimic». The studio's own judges had passed it. The quality plan of that day
(STUDIO_QUALITY_PLAN_2026-10-16, step 1) and his card «măsurăm întâi» decided that no playbook,
identity or judge change goes live until it beats today's code on a frozen set of past days,
judged by someone who is not the Director. This script is that measurement. It costs no money:
the language models are on the subscription, and no media vendor is ever reachable.

What it does, per case of the frozen case file (``config/evals/writer_cases.json``):

1. copies that case's nightly backup (``data/backups/studio-YYYYMMDDTHHMMSSZ.db``, with its
   ``-wal`` and ``-shm``) into a folder of its own under ``--work`` and opens only the COPY; the
   copy is migrated to today's schema, the copy's autonomy stop, stuck agents and dead runs are
   cleared, and a serial case written from a backup taken after its day was told gets the
   serial's memory as it stood before (``continuity_before``) — on the copy only;
2. asks today's writer, with the variant's patches installed (``--variant``, `app.evals.
   variants`; ``baseline`` is today's code): `story.services.write_episode` for a serial day,
   `factual.agent_pipeline.agent_write_script` for a factual topic. The writer's model is pinned
   through `run_agent_task`'s ``model_id`` (the case's original writer model, or
   ``--writer-model``: the Director answered on 3 models in 3 days, Marcus on 6). The Director's
   reading of new prompt lessons (`reconcile_prompt_lessons`, a model call before every serial
   writer) is switched off, and the day's budget gate (`may_run_agent`) lets the run through —
   both only inside this process; the policy kernel is checked for real, on the copy;
3. scores the draft with the studio's own free checks — `story.review.draft_checks` for an
   episode; the writer gate's citation, card, uncited-scene and length checks and the review's
   `story_checks` for a factual script;
4. asks the stranger (`app.evals.stranger`) — a bare identity on ``--judge-model`` (default
   nemotron-3-ultra, a family neither the Director nor the writer uses) — the Owner's five
   yes/no questions in three balanced orders, about the new draft and about the version the
   studio shipped (``reference``, frozen in the case file), and «which would a stranger watch to
   the end?» about the two, in both orders (a flip is a tie);
5. reads back from the copy's ``agent_run`` every call's tokens and seconds.

A ``golden_pair`` case is two past versions whose order the studio already knows (the
Director's 26/50 and 38/50 of 2026-10-14, the factual topic of thirteen drafts, the «Zero
Scripts, Blocked Log» chain): only the stranger is asked, so its verdict can be checked against
what is known.

Output: ``data/evals/<UTC stamp>-<variant>/`` (git-ignored) with ``results.json`` and
``report.md`` (Romanian tables: per case and in total, the checks passed, the stranger's score,
the pairwise result, tokens and latency per call, the brief's hashes). With the Owner's labels
(``config/evals/owner_labels.json``) the report says how often the stranger agrees with him, per
question (percent and Cohen's kappa): the research found uncalibrated judges near chance.

Modes:

- ``--discover`` scans copies of the nightly backups since ``--since`` and proposes cases
  (closed serial days, factual topics with SUPPORTED claims and a thesis, the golden pairs) to
  the case file, for review; it never asks a model;
- ``--calibration-form`` writes the Romanian form (HTML and Markdown) with the frozen texts and
  the five questions, for the Owner to answer; its button produces ``owner_labels.json``;
- ``--dry-run`` copies and prepares each case, builds the writer's brief without sending it
  (its size and hash), and lists what would be asked and on which model; it reads no vault and
  calls no model.

Safety: the live database (``data/studio.db``) is never opened — only files named like a nightly
backup are copied, and only copies are opened. The registry is built as the studio builds it
(`integrations.services.load_registry` with the vault, `main.register_seeded_ollama`) and keeps
only the writer's and the judge's providers; before any call it is asserted to hold no media
adapter (RunPod, Runway, ElevenLabs, YouTube, ComfyUI). The vault's key stays where the studio
keeps it, beside the live database; it is never copied and never printed, nor is any key. A run
is refused while the live studio holds its worker lock (``data/studio.lock``) or a
``scripts/start.py`` process runs, unless ``--allow-live-studio``: the subscription's usage
limits are shared with the Director's loop. The Owner's rule of 2026-10-15 holds here too: no
writer runs on kimi-k3.

Usage::

    uv run --locked python -X utf8 scripts/writer_eval.py --discover [--since 2026-10-11]
    uv run --locked python -X utf8 scripts/writer_eval.py --dry-run [--cases id,id] [--limit N]
    uv run --locked python -X utf8 scripts/writer_eval.py --writer-model gpt-oss:120b
        [--variant baseline] [--judge-model nemotron-3-ultra] [--work <folder>]
        [--backups data/backups] [--out data/evals] [--skip-reference] [--keep-copies]
    uv run --locked python -X utf8 scripts/writer_eval.py --calibration-form
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = Path(__file__).resolve().parent
for _path in (ROOT / "backend", SCRIPTS):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

#: The independent judge (the Owner's card of 2026-10-16): a family neither the Director
#: (deepseek-v4.1-flash) nor the writer (gpt-oss:120b) belongs to.
DEFAULT_JUDGE_MODEL = "nemotron-3-ultra"
#: The Owner, 2026-10-15: never a writer on kimi-k3 (too expensive for the subscription).
FORBIDDEN_WRITER_MODELS = ("kimi-k3",)
#: The nightly backups the plan names start on 2026-10-12; the day before is scanned too, for
#: the serial's memory as it stood before the first of them was told.
DEFAULT_SINCE = "2026-10-11"
CASE_FILE = ROOT / "config" / "evals" / "writer_cases.json"
LABELS_FILE = ROOT / "config" / "evals" / "owner_labels.json"
OUT_DIR = ROOT / "data" / "evals"
DEFAULT_BACKUPS = ROOT / "data" / "backups"
CASE_FILE_VERSION = 1
LABELS_VERSION = 1
#: Only a nightly backup is ever copied: never the live database, never a pre-migration copy.
BACKUP_NAME = re.compile(r"^studio-(\d{8}T\d{6}Z)\.db$")
DB_SUFFIXES = ("", "-wal", "-shm")
COPY_TRIES = 40
COPY_WAIT_SECONDS = 0.25
CASE_KINDS = ("serial", "factual", "golden_pair")
TEXT_KINDS = ("serial", "factual")
WRITER_TASKS = ("write_episode", "write_script")
#: Words in an adapter's class lineage or kind that mean a media or publishing vendor.
MEDIA_VENDORS = ("runpod", "runway", "elevenlabs", "youtube", "comfy", "openai_media")
JUDGE_MAX_TOKENS = 2000
JUDGE_TEMPERATURE = 0.0
STRANGER_ROLE = "EvalStranger"
STRANGER_NAME = "Stranger (evaluation)"
#: Two versions of one story the Director scored this far apart are a golden pair.
GOLDEN_GAP = 8
#: A serial day with this many drafts, or a factual topic with this many, is a chain whose
#: first draft and shipped version make a golden pair.
SERIAL_CHAIN = 3
FACTUAL_CHAIN = 10
#: About fifteen texts for the Owner to label (his card of 2026-10-16).
FORM_ITEMS = 15
#: What the Owner said of a past version, kept beside it.
OWNER_NOTES = {
    "Zero Scripts, Blocked Log": (
        "The Owner, 2026-10-16, on the approved version: «Eu nu înțeleg nimic»."
    ),
}
#: The calls a case may make, for the plan printed by --dry-run: (fewest, most). A serial
#: writer is asked once more when the review's own checks refuse the first answer; a factual
#: writer once more for an answer with no object, and twice more for uncited scenes or wrong
#: cards. Every structured judge call may be asked once more (`agents.structured`).
WRITER_CALLS = {"serial": (1, 2), "factual": (1, 6)}
STRANGER_CALLS = (3, 6)
PAIRWISE_CALLS = (2, 4)

KIND_RO = {"serial": "episod", "factual": "short factual", "golden_pair": "pereche de aur"}
STATE_RO = {
    "before_write": "copia de dinainte de scriere",
    "after_write": "copia de după scriere",
    "no_draft_yet": "nescris încă",
}
OUTCOME_RO = {
    "new": "noul",
    "reference": "cel livrat",
    "a": "A",
    "b": "B",
    "tie": "egal (s-a răsturnat)",
    "incomplete": "incomplet",
    None: "—",
}


class EvalError(RuntimeError):
    """A case or a file the harness cannot work with, in the Owner's words."""


class MediaAdapterFound(RuntimeError):
    """The registry holds something that is not a language model: nothing may be asked."""


class _DryStop(Exception):
    """Raised instead of sending a writer's brief during --dry-run (the brief is kept)."""


# ----------------------------------------------------------------------------- the copies


def stamp_of(name: str) -> datetime:
    """The moment a nightly backup was taken, from its name."""
    match = BACKUP_NAME.match(name)
    if match is None:
        raise EvalError(f"«{name}» nu este o copie de noapte (studio-AAAALLZZTHHMMSSZ.db)")
    return datetime.strptime(match.group(1), "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)


def _moment(text: Any) -> datetime | None:
    try:
        moment = datetime.fromisoformat(str(text))
    except (TypeError, ValueError):
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def backup_file(backups: Path, name: str) -> Path:
    """The path of a nightly backup; anything else (the live database above all) is refused."""
    stamp_of(name)
    path = backups / name
    live = backups.parent / "studio.db"
    if path.resolve() == live.resolve() or path.name == "studio.db":
        raise EvalError("Baza de date vie nu se deschide niciodată")
    if not path.is_file():
        raise EvalError(f"Copia de noapte nu există: {path}")
    return path


def nightly_backups(backups: Path, since: str | None = None) -> list[str]:
    """The nightly backups' names, oldest first, from ``since`` (YYYY-MM-DD) on."""
    found = []
    for path in backups.glob("studio-*.db"):
        if not BACKUP_NAME.match(path.name):
            continue
        if since and stamp_of(path.name).date().isoformat() < since:
            continue
        found.append(path.name)
    return sorted(found, key=stamp_of)


def copy_database(
    source: Path, folder: Path, *, tries: int = COPY_TRIES, wait: float = COPY_WAIT_SECONDS
) -> Path:
    """Copy a backup (and its WAL and SHM when they exist) into ``folder``; the copy's path.
    The source files are only read, by `shutil.copyfile`, never opened as a database."""
    if not source.is_file():
        raise EvalError(f"Baza de date nu există: {source}")
    folder.mkdir(parents=True, exist_ok=True)
    for suffix in DB_SUFFIXES:
        original = source.with_name(source.name + suffix)
        target = folder / (source.name + suffix)
        if not original.exists():
            target.unlink(missing_ok=True)
            continue
        for attempt in range(tries):
            try:
                shutil.copyfile(original, target)
                break
            except PermissionError:
                if attempt == tries - 1:
                    raise
                time.sleep(wait)
    return folder / source.name


def remove_copy(copy: Path) -> None:
    """Delete a copy this harness made (never anything else: only inside its own folder)."""
    for suffix in DB_SUFFIXES:
        copy.with_name(copy.name + suffix).unlink(missing_ok=True)
    for folder in (copy.parent, copy.parent.parent):
        try:
            folder.rmdir()  # only an empty folder: the copy's own, then its run's
        except OSError:
            break


def open_copy(copy: Path) -> Any:
    """An engine on the copy, migrated to the schema this code expects (on the copy only)."""
    from app.db import create_db_engine, migrate  # noqa: PLC0415
    from app.main import expected_revision  # noqa: PLC0415
    from sqlalchemy import text  # noqa: PLC0415

    engine = create_db_engine(f"sqlite:///{copy.as_posix()}")
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    if revision != expected_revision():
        migrate(engine)
    return engine


# ----------------------------------------------------------------------------- the live studio


def lock_held(path: Path) -> bool:
    """Whether a live process holds the studio's worker lock (`workflows.worker`), asked
    without taking it: on Windows the locked byte cannot be read by anyone else."""
    if not path.is_file():
        return False
    if sys.platform == "win32":
        try:
            with open(path, "rb") as handle:
                handle.read(1)
        except PermissionError:
            return True
        except OSError:
            return False
        return False
    import fcntl  # noqa: PLC0415

    with open(path, "rb") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return False


_START_SCRIPT = re.compile(r"scripts[\\/]+start\.py", re.IGNORECASE)


def studio_processes() -> list[str]:
    """The ``scripts/start.py`` processes running now (Windows; elsewhere none are seen)."""
    try:
        import win_processes  # noqa: PLC0415 - scripts/win_processes.py
    except ImportError:
        return []
    rows = win_processes.list_processes(
        lambda name: name.lower() in ("python.exe", "pythonw.exe", "uv.exe")
    )
    return [
        f"{name} (pid {pid})"
        for pid, name, command in rows
        if pid != os.getpid() and _START_SCRIPT.search(command or "")
    ]


def live_studio(lock: Path) -> list[str]:
    """Why the live studio looks alive, in the Owner's words; empty when it does not."""
    reasons = []
    if lock_held(lock):
        reasons.append(f"lacătul lucrătorului ({lock}) este ținut de un proces viu")
    reasons += [f"rulează scripts/start.py: {row}" for row in studio_processes()]
    return reasons


# ----------------------------------------------------------------------------- the registry


def assert_no_media_adapter(registry: Any) -> None:
    """Refuse a registry holding anything but a language model: a media, voice, publishing or
    analytics adapter, or a class or connection kind naming RunPod, Runway, ElevenLabs,
    YouTube or ComfyUI. Called before any model is asked."""
    from app.providers.analytics_base import AnalyticsProvider  # noqa: PLC0415
    from app.providers.base import LLMProvider  # noqa: PLC0415
    from app.providers.media_base import ImageProvider, TTSProvider, VideoProvider  # noqa: PLC0415
    from app.providers.publishing_base import PublishingProvider  # noqa: PLC0415

    media = (ImageProvider, TTSProvider, VideoProvider, PublishingProvider, AnalyticsProvider)
    for provider_id in registry.registered_ids():
        adapter = registry.get(provider_id)
        lineage = " ".join(
            f"{klass.__module__}.{klass.__qualname__}" for klass in type(adapter).__mro__
        ).lower()
        kind = str(getattr(adapter, "kind", "") or "").lower()
        vendor = next((word for word in MEDIA_VENDORS if word in lineage or word in kind), None)
        if isinstance(adapter, media) or vendor or not isinstance(adapter, LLMProvider):
            raise MediaAdapterFound(
                f"Registrul ține un adaptor care nu este un model de limbaj: "
                f"{type(adapter).__name__} ({provider_id}"
                + (f", {vendor}" if vendor else "")
                + "); nu se întreabă nimic."
            )


def llm_registry(engine: Any, vault_key: Path, provider_ids: Iterable[str]) -> tuple[Any, dict]:
    """The registry the studio would build at start (`load_registry` with the vault, then
    `register_seeded_ollama`), keeping only ``provider_ids``; asserted media-free. The vault's
    key is read where the studio keeps it and never copied or printed."""
    from app.integrations.services import load_registry  # noqa: PLC0415
    from app.integrations.vault import CredentialVault  # noqa: PLC0415
    from app.main import register_seeded_ollama  # noqa: PLC0415
    from app.providers.registry import ProviderRegistry  # noqa: PLC0415

    wanted = {str(pid) for pid in provider_ids if pid}
    every = ProviderRegistry()
    skipped = load_registry(engine, CredentialVault(vault_key), every)
    register_seeded_ollama(engine, every)
    only = ProviderRegistry()
    for provider_id in sorted(wanted):
        adapter = every.get(provider_id)
        if adapter is not None:
            only.register(provider_id, adapter)
    assert_no_media_adapter(only)
    return only, {
        "connections_not_read": len(skipped),
        "registered": only.registered_ids(),
        "missing": sorted(wanted - set(only.registered_ids())),
    }


def resolve_model(engine: Any, name: str) -> dict[str, Any] | None:
    """The model record called ``name`` in the copy (an available one first)."""
    from app.agents.models import ModelRecord  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as session:
        rows = list(session.scalars(select(ModelRecord).where(ModelRecord.model_name == name)))
    if not rows:
        return None
    chosen = sorted(rows, key=lambda row: (not row.is_available, row.id))[0]
    return {
        "id": chosen.id,
        "model_name": chosen.model_name,
        "provider_id": chosen.provider_id,
        "available": bool(chosen.is_available),
    }


def forbidden_writer(name: str | None) -> bool:
    word = str(name or "").strip().lower()
    return any(word.startswith(model) for model in FORBIDDEN_WRITER_MODELS)


# ----------------------------------------------------------------------------- the cases


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _frozen_text_ok(text: Any, where: str) -> None:
    if not isinstance(text, Mapping) or text.get("kind") not in TEXT_KINDS:
        raise EvalError(f"{where}: textul înghețat nu are un tip (serial sau factual)")
    if text.get("kind") == "serial" and not isinstance(text.get("beats"), list):
        raise EvalError(f"{where}: episodul înghețat nu are beat-uri")
    if text.get("kind") == "factual" and not isinstance(text.get("scenes"), list):
        raise EvalError(f"{where}: scenariul înghețat nu are scene")


def _reference_ok(reference: Any, where: str) -> None:
    if reference is None:
        return
    if not isinstance(reference, Mapping) or not reference.get("text_key"):
        raise EvalError(f"{where}: referința nu are cheie (text_key)")
    _frozen_text_ok(reference.get("view"), f"{where} (referința)")


def validate_case(case: Any) -> dict[str, Any]:
    """One case as the harness needs it; EvalError naming what is missing."""
    if not isinstance(case, Mapping):
        raise EvalError("Un caz nu este un obiect")
    where = f"Cazul {case.get('id')!r}"
    if not str(case.get("id") or "").strip():
        raise EvalError("Un caz nu are id")
    kind = case.get("kind")
    if kind not in CASE_KINDS:
        raise EvalError(f"{where}: tipul {kind!r} nu este unul din {', '.join(CASE_KINDS)}")
    stamp_of(str(case.get("backup") or ""))
    if kind == "serial" and not case.get("log_id"):
        raise EvalError(f"{where}: un caz de serial are nevoie de log_id (daily_studio_log)")
    if kind == "factual" and not case.get("topic_id"):
        raise EvalError(f"{where}: un caz factual are nevoie de topic_id")
    if kind in TEXT_KINDS:
        _reference_ok(case.get("reference"), where)
        target = case.get("target_seconds")
        if target is not None and (not isinstance(target, int) or not 10 <= target <= 600):
            raise EvalError(f"{where}: target_seconds este un număr de secunde (10-600) sau null")
    else:
        for side in ("a", "b"):
            _reference_ok(case.get(side), f"{where}, {side}")
            if case.get(side) is None:
                raise EvalError(f"{where}: perechea nu are textul {side}")
        if case.get("expected") not in ("a", "b", None):
            raise EvalError(f"{where}: expected este a, b sau null")
    return dict(case)


def load_cases(path: Path) -> list[dict[str, Any]]:
    """The frozen cases; EvalError when the file is missing or a case is malformed."""
    if not path.is_file():
        raise EvalError(f"Fișierul de cazuri nu există: {path}. Rulează întâi --discover.")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EvalError(f"Fișierul de cazuri nu este JSON: {exc}") from None
    if not isinstance(data, Mapping) or data.get("version") != CASE_FILE_VERSION:
        raise EvalError(f"Fișierul de cazuri nu are versiunea {CASE_FILE_VERSION}")
    cases = [validate_case(case) for case in data.get("cases") or []]
    ids = [case["id"] for case in cases]
    doubled = sorted({identifier for identifier in ids if ids.count(identifier) > 1})
    if doubled:
        raise EvalError("Id-uri de caz repetate: " + ", ".join(doubled))
    return cases


def select_cases(cases: list[dict[str, Any]], wanted: str | None, limit: int) -> list[dict]:
    """The cases ``--cases`` names (in the file's order) and at most ``--limit`` of them."""
    chosen = cases
    if wanted:
        names = [name.strip() for name in wanted.split(",") if name.strip()]
        unknown = [name for name in names if name not in {case["id"] for case in cases}]
        if unknown:
            raise EvalError("Cazuri necunoscute: " + ", ".join(unknown))
        chosen = [case for case in cases if case["id"] in names]
    return chosen[:limit] if limit and limit > 0 else chosen


def load_labels(path: Path) -> dict[str, dict[str, bool | None]]:
    """The Owner's answers per text key ({} when he has not labelled yet)."""
    from app.evals.stranger import QUESTION_KEYS, yes_or_no  # noqa: PLC0415

    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    labels = data.get("labels") if isinstance(data, Mapping) else None
    if not isinstance(labels, Mapping):
        raise EvalError(f"{path}: lipsește «labels»")
    return {
        str(key): {question: yes_or_no(answers.get(question)) for question in QUESTION_KEYS}
        for key, answers in labels.items()
        if isinstance(answers, Mapping)
    }


# ----------------------------------------------------------------------------- discovery


def _json(value: Any) -> Any:
    if isinstance(value, str) and value:
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _rows(con: sqlite3.Connection, sql: str) -> list[sqlite3.Row]:
    try:
        return list(con.execute(sql))
    except sqlite3.OperationalError:
        return []


def scan_backup(copy: Path) -> dict[str, Any]:
    """What discovery needs from one COPY of a backup, read with plain SQL (old schemas too)."""
    con = sqlite3.connect(str(copy))
    con.row_factory = sqlite3.Row
    try:
        logs = {
            row["id"]: {
                "business_date": row["business_date"],
                "status": row["status"],
                "closed_at": row["closed_at"],
                "projected": len(_json(row["narrative_projection_json"]) or []),
            }
            for row in _rows(
                con,
                "SELECT id, business_date, status, closed_at, narrative_projection_json "
                "FROM daily_studio_log",
            )
        }
        episodes = {}
        for row in _rows(
            con,
            "SELECT id, log_id, title, status, created_at, rewrite_of_id, review_json, "
            "beats_json, continuity_json FROM story_episode",
        ):
            review = _json(row["review_json"]) or {}
            continuity = _json(row["continuity_json"]) or {}
            episodes[row["id"]] = {
                "log_id": row["log_id"],
                "title": row["title"],
                "status": row["status"],
                "created_at": row["created_at"],
                "verdict": review.get("verdict") if isinstance(review, dict) else None,
                "beats": _json(row["beats_json"]) or [],
                "continuity": continuity if isinstance(continuity, dict) else {},
            }
        advanced = [
            (row["timestamp"], (_json(row["payload"]) or {}).get("episode_id"))
            for row in _rows(
                con,
                "SELECT timestamp, payload FROM domain_event "
                "WHERE event_type = 'story.continuity_advanced' ORDER BY timestamp",
            )
        ]
        drafted = {
            row["aggregate_id"]: row["correlation_id"]
            for row in _rows(
                con,
                "SELECT aggregate_id, correlation_id FROM domain_event "
                "WHERE event_type = 'story.episode_drafted'",
            )
        }
        judged: dict[str, dict[str, Any]] = {}
        for row in _rows(
            con,
            "SELECT aggregate_type, aggregate_id, payload, timestamp FROM domain_event "
            "WHERE event_type = 'editorial.judged' ORDER BY timestamp",
        ):
            payload = _json(row["payload"]) or {}
            if isinstance(payload, dict) and isinstance(payload.get("total"), int):
                judged[row["aggregate_id"]] = {
                    "total": payload["total"],
                    "kind": payload.get("kind"),
                    "shipped": bool(payload.get("shipped")),
                    "aggregate_type": row["aggregate_type"],
                }
        runs = [
            dict(row)
            for row in _rows(
                con,
                "SELECT task_type, model_name, correlation_id, started_at, status FROM agent_run "
                "WHERE task_type IN ('write_episode', 'write_script') ORDER BY started_at",
            )
        ]
        continuity_rows = _rows(
            con,
            "SELECT version, canon_episode_number, threads_json, recurring_json, summaries_json "
            "FROM continuity_state WHERE id = 1",
        )
        continuity_state = (
            {
                "version": continuity_rows[0]["version"],
                "canon_episode_number": continuity_rows[0]["canon_episode_number"],
                "threads_json": _json(continuity_rows[0]["threads_json"]) or [],
                "recurring_json": _json(continuity_rows[0]["recurring_json"]) or [],
                "summaries_json": _json(continuity_rows[0]["summaries_json"]) or [],
            }
            if continuity_rows
            else None
        )
        topics = {
            row["id"]: {
                "title": row["title"],
                "created_at": row["created_at"],
                "thesis": bool(_json(row["thesis_json"])),
                "supported": row["supported"],
            }
            for row in _rows(
                con,
                "SELECT t.id, t.title, t.created_at, t.thesis_json, (SELECT count(*) FROM "
                "factual_claim c WHERE c.topic_id = t.id AND c.status = 'SUPPORTED') AS supported "
                "FROM topic_idea t",
            )
        }
        reviews: dict[str, str] = {}
        for row in _rows(
            con, "SELECT script_id, verdict FROM story_review ORDER BY created_at, id"
        ):
            reviews[row["script_id"]] = row["verdict"]
        scripts = {
            row["id"]: {
                "topic_id": row["topic_id"],
                "version": row["version"],
                "status": row["status"],
                "created_at": row["created_at"],
                "target": row["target_duration_seconds"],
                "title": row["title"],
                "scenes": _json(row["scenes_json"]) or [],
                "verdict": reviews.get(row["id"]),
            }
            for row in _rows(
                con,
                "SELECT id, topic_id, version, status, created_at, target_duration_seconds, "
                "title, scenes_json FROM script_draft",
            )
        }
        writer = _rows(
            con,
            "SELECT m.model_name FROM agent a JOIN role r ON r.id = a.role_id "
            "JOIN model_record m ON m.id = a.model_id WHERE r.name = 'ScriptWriter' "
            "AND a.lifecycle = 'ACTIVE' LIMIT 1",
        )
    finally:
        con.close()
    return {
        "logs": logs,
        "episodes": episodes,
        "drafted": drafted,
        "advanced": [(when, str(eid)) for when, eid in advanced if eid],
        "judged": judged,
        "runs": runs,
        "continuity": continuity_state,
        "topics": topics,
        "scripts": scripts,
        "writer_model": writer[0]["model_name"] if writer else None,
    }


def _by_time(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(items, key=lambda item: str(item.get("created_at") or ""))


def _writer_model(
    scan: Mapping[str, Any], task: str, before: Any, correlation: str | None
) -> str | None:
    """The model that wrote a draft: the run of its correlation, else the last run of that task
    before the draft, else the writer's model in that backup."""
    runs = [
        run for run in scan["runs"] if run["task_type"] == task and run["status"] == "SUCCEEDED"
    ]
    if correlation:
        same = [run for run in runs if run["correlation_id"] == correlation]
        if same:
            return str(same[-1]["model_name"])
    moment = _moment(before)
    if moment is not None:
        earlier = [run for run in runs if (_moment(run["started_at"]) or moment) <= moment]
        if earlier:
            return str(earlier[-1]["model_name"])
    return scan.get("writer_model")


def _serial_text(backup: str, scan: Mapping[str, Any], episode_id: str) -> dict[str, Any]:
    from app.evals.stranger import frozen_episode  # noqa: PLC0415

    episode = scan["episodes"][episode_id]
    judged = scan["judged"].get(episode_id) or {}
    text = {
        "backup": backup,
        "kind": "serial",
        "id": episode_id,
        "text_key": f"episode:{episode_id}",
        "title": episode["title"],
        "status": episode["status"],
        "verdict": episode["verdict"],
        "editorial_total": judged.get("total"),
        "created_at": episode["created_at"],
        "view": frozen_episode(episode["title"], episode["beats"]),
    }
    if episode["title"] in OWNER_NOTES and episode["status"] == "APPROVED":
        text["owner_note"] = OWNER_NOTES[episode["title"]]
    return text


def _factual_text(backup: str, scan: Mapping[str, Any], script_id: str) -> dict[str, Any]:
    from app.evals.stranger import frozen_script  # noqa: PLC0415

    script = scan["scripts"][script_id]
    judged = scan["judged"].get(script_id) or {}
    return {
        "backup": backup,
        "kind": "factual",
        "id": script_id,
        "text_key": f"script:{script_id}",
        "title": script["title"],
        "status": script["status"],
        "verdict": script["verdict"],
        "editorial_total": judged.get("total"),
        "version": script["version"],
        "created_at": script["created_at"],
        "view": frozen_script(script["title"], script["scenes"]),
    }


def _shipped(drafts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The version that shipped: the newest APPROVED, else the newest the review passed."""
    approved = [draft for draft in drafts if draft["status"] == "APPROVED"]
    if approved:
        return approved[-1]
    passed = [draft for draft in drafts if draft.get("verdict") == "PASS"]
    return passed[-1] if passed else None


#: The serial's memory before anything was approved (`story.services._continuity_row`).
EMPTY_CANON = {
    "version": 1,
    "canon_episode_number": 0,
    "threads_json": [],
    "recurring_json": [],
    "summaries_json": [],
}


def advance_row(row: Mapping[str, Any], episode_id: str, episode: Mapping[str, Any]) -> dict:
    """``row`` moved forward by one approved episode, as `story.services.advance_continuity`
    moves it (without its events and its judging of the plan, which the caller restores)."""
    from app.story.services import CONTINUITY_SUMMARIES, _next_thread_id  # noqa: PLC0415

    continuity = dict(episode.get("continuity") or {})
    number = int(row.get("canon_episode_number") or 0) + 1
    closed = {str(thread) for thread in continuity.get("threads_closed") or []}
    threads = [dict(t) for t in row.get("threads_json") or [] if str(t.get("id")) not in closed]
    for text in continuity.get("threads_opened") or []:
        text = str(text).strip()
        if text and all(thread.get("text") != text for thread in threads):
            threads.append(
                {"id": _next_thread_id(threads), "text": text[:300], "opened_in": number}
            )
    recurring = list(row.get("recurring_json") or [])
    for item in continuity.get("recurring") or []:
        item = str(item).strip()[:120]
        if item and item not in recurring:
            recurring.append(item)
    summaries = list(row.get("summaries_json") or [])
    summaries.append(
        {
            "episode_number": number,
            "episode_id": episode_id,
            "title": episode.get("title"),
            "summary": str(continuity.get("summary") or ""),
            "business_date": continuity.get("business_date"),
        }
    )
    return {
        "version": int(row.get("version") or 1) + 1,
        "canon_episode_number": number,
        "threads_json": threads[:12],
        "recurring_json": recurring[-12:],
        "summaries_json": summaries[-CONTINUITY_SUMMARIES:],
    }


def continuity_before(
    scans: Mapping[str, Mapping[str, Any]], first_at: Any
) -> dict[str, Any] | None:
    """The serial's memory at the moment a day's first draft was asked for: the newest backup
    taken before it, moved forward by every episode canon took in between
    (``story.continuity_advanced``, read from the newest backup), the plan of the last one put
    back to PLANNED when it was judged only later. None when no backup is older."""
    moment = _moment(first_at)
    if moment is None:
        return None
    names = sorted(scans, key=stamp_of)
    older = [name for name in names if stamp_of(name) < moment]
    if not older:
        return None
    newest = scans[names[-1]]
    taken = stamp_of(older[-1])
    row: dict[str, Any] = dict(scans[older[-1]].get("continuity") or EMPTY_CANON)
    advanced = {episode_id: _moment(when) for when, episode_id in newest["advanced"]}
    steps = [
        episode_id
        for when, episode_id in newest["advanced"]
        if (at := _moment(when)) is not None and taken < at < moment
    ]
    for episode_id in steps:
        if episode_id in newest["episodes"]:
            row = advance_row(row, episode_id, newest["episodes"][episode_id])
    summaries = row.get("summaries_json") or []
    plan_from = str(summaries[-1].get("episode_id")) if summaries else None
    plan = (newest["episodes"].get(plan_from) or {}).get("continuity", {}).get("next_episode")
    if isinstance(plan, dict) and plan.get("judged_in"):
        judged_at = advanced.get(str(plan["judged_in"]))
        if judged_at is None or judged_at >= moment:
            plan = {key: value for key, value in plan.items() if key != "judged_in"}
            plan["status"] = "PLANNED"
    return {
        "from_backup": older[-1],
        "replayed": steps,
        "row": row,
        "plan_episode": {
            "id": plan_from,
            "log_id": (newest["episodes"].get(plan_from) or {}).get("log_id"),
            "title": (newest["episodes"].get(plan_from) or {}).get("title"),
            "created_at": (newest["episodes"].get(plan_from) or {}).get("created_at"),
            "next_episode": plan,
        }
        if plan_from
        else None,
    }


def _serial_cases(scans: Mapping[str, Mapping[str, Any]], since: str) -> list[dict[str, Any]]:
    names = sorted(scans, key=stamp_of)
    days: dict[str, str] = {}
    for name in names:
        for log_id, log in scans[name]["logs"].items():
            if log["status"] == "CLOSED" and log["projected"] and log["business_date"] >= since:
                days[log_id] = log["business_date"]
    cases = []
    for log_id, date in sorted(days.items(), key=lambda item: item[1]):
        holders = [name for name in names if log_id in scans[name]["logs"]]
        newest = scans[holders[-1]]
        drafts = _by_time(
            {"id": key, **value}
            for key, value in newest["episodes"].items()
            if value["log_id"] == log_id
        )
        first = drafts[0] if drafts else None
        first_at = _moment(first["created_at"]) if first else None
        before = [name for name in holders if first_at is None or stamp_of(name) < first_at]
        backup = before[-1] if before else holders[0]
        state = ("before_write" if first else "no_draft_yet") if before else "after_write"
        shipped = _shipped(drafts)
        model = (
            _writer_model(
                newest, "write_episode", first["created_at"], newest["drafted"].get(first["id"])
            )
            if first
            else scans[backup].get("writer_model")
        )
        case: dict[str, Any] = {
            "id": f"serial-{date}",
            "kind": "serial",
            "backup": backup,
            "log_id": log_id,
            "business_date": date,
            "state": state,
            "writer_model": model,
            "language": "en",
            "drafts_that_day": len(drafts),
            "reference": _serial_text(holders[-1], newest, shipped["id"]) if shipped else None,
        }
        if first is not None:
            case["continuity_before"] = continuity_before(scans, first["created_at"])
        cases.append(case)
    return cases


def _factual_cases(scans: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    names = sorted(scans, key=stamp_of)
    topics: dict[str, str] = {}
    for name in names:
        for topic_id, topic in scans[name]["topics"].items():
            if topic["thesis"] and topic["supported"]:
                topics[topic_id] = str(topic["created_at"] or "")
    cases = []
    for topic_id, _created in sorted(topics.items(), key=lambda item: item[1]):
        holders = [
            name
            for name in names
            if (scans[name]["topics"].get(topic_id) or {}).get("thesis")
            and (scans[name]["topics"].get(topic_id) or {}).get("supported")
        ]
        newest = scans[holders[-1]]
        drafts = _by_time(
            {"id": key, **value}
            for key, value in newest["scripts"].items()
            if value["topic_id"] == topic_id
        )
        first = drafts[0] if drafts else None
        first_at = _moment(first["created_at"]) if first else None
        before = [name for name in holders if first_at is None or stamp_of(name) < first_at]
        backup = before[-1] if before else holders[0]
        state = ("before_write" if first else "no_draft_yet") if before else "after_write"
        shipped = _shipped(drafts)
        cases.append(
            {
                "id": f"factual-{topic_id[:8]}",
                "kind": "factual",
                "backup": backup,
                "topic_id": topic_id,
                "topic_title": newest["topics"][topic_id]["title"],
                "state": state,
                "writer_model": _writer_model(newest, "write_script", first["created_at"], None)
                if first
                else scans[backup].get("writer_model"),
                "language": "en",
                # None: today's setting (`Settings.target_video_seconds`), the length the
                # studio writes for now; the drafts of those days aimed at another.
                "target_seconds": None,
                "original_target_seconds": first["target"] if first else None,
                "drafts_of_topic": len(drafts),
                "reference": _factual_text(holders[-1], newest, shipped["id"]) if shipped else None,
            }
        )
    return cases


def _golden_pairs(scans: Mapping[str, Mapping[str, Any]], since: str) -> list[dict[str, Any]]:
    names = sorted(scans, key=stamp_of)
    newest_name = names[-1]
    newest = scans[newest_name]
    pairs: list[dict[str, Any]] = []
    seen: set[frozenset[str]] = set()

    def add(kind: str, key: str, a: str, b: str, expected: str | None, why: str, by: str) -> None:
        if a == b or frozenset((a, b)) in seen:
            return
        seen.add(frozenset((a, b)))
        text = _serial_text if kind == "serial" else _factual_text
        first, second = text(newest_name, newest, a), text(newest_name, newest, b)
        note = " ".join(
            part for part in (why, second.get("owner_note") or first.get("owner_note")) if part
        )
        pairs.append(
            {
                "id": f"golden-{kind}-{key}-{by.removeprefix('director_')}",
                "kind": "golden_pair",
                "text_kind": kind,
                "backup": newest_name,
                "a": first,
                "b": second,
                "expected": expected,
                "expected_by": by,
                "note": note,
            }
        )

    # The Director's editorial judgement scored two versions of one story far apart.
    stories: dict[tuple[str, str], list[tuple[int, str]]] = {}
    for version_id, judged in newest["judged"].items():
        if version_id in newest["episodes"]:
            log_id = newest["episodes"][version_id]["log_id"]
            stories.setdefault(("serial", log_id), []).append((judged["total"], version_id))
        elif version_id in newest["scripts"]:
            topic_id = newest["scripts"][version_id]["topic_id"]
            stories.setdefault(("factual", topic_id), []).append((judged["total"], version_id))
    for (kind, story), scored in sorted(stories.items()):
        low, high = min(scored), max(scored)
        if high[0] - low[0] >= GOLDEN_GAP:
            key = (
                newest["logs"].get(story, {}).get("business_date", story[:8])
                if kind == "serial"
                else story[:8]
            )
            add(
                kind,
                str(key),
                low[1],
                high[1],
                "b",
                f"The Director's editorial judgement: {low[0]}/50 against {high[0]}/50.",
                "director_editorial",
            )

    # A long chain of drafts: its first draft against the version that shipped.
    for log_id, log in sorted(newest["logs"].items(), key=lambda item: item[1]["business_date"]):
        if log["business_date"] < since:
            continue
        drafts = _by_time(
            {"id": key, **value}
            for key, value in newest["episodes"].items()
            if value["log_id"] == log_id
        )
        shipped = _shipped(drafts)
        if len(drafts) >= SERIAL_CHAIN and shipped is not None:
            first = drafts[0]
            expected = "b" if first["verdict"] != "PASS" and shipped["verdict"] == "PASS" else None
            add(
                "serial",
                log["business_date"],
                first["id"],
                shipped["id"],
                expected,
                f"A chain of {len(drafts)} drafts: the first ({first['verdict']}) against the "
                f"one shipped ({shipped['status']}, {shipped['verdict']}).",
                "director_review",
            )
    for topic_id in sorted(newest["topics"]):
        drafts = _by_time(
            {"id": key, **value}
            for key, value in newest["scripts"].items()
            if value["topic_id"] == topic_id
        )
        shipped = _shipped(drafts)
        if len(drafts) >= FACTUAL_CHAIN and shipped is not None:
            first = drafts[0]
            expected = "b" if first["verdict"] != "PASS" and shipped["verdict"] == "PASS" else None
            add(
                "factual",
                topic_id[:8],
                first["id"],
                shipped["id"],
                expected,
                f"A chain of {len(drafts)} drafts: the first (review {first['verdict']}) against "
                f"the one shipped ({shipped['status']}, review {shipped['verdict']}).",
                "director_review",
            )
    return pairs


def propose_cases(scans: Mapping[str, Mapping[str, Any]], since: str) -> dict[str, Any]:
    """The case file discovery proposes from the scanned backups (pure: no copy, no model)."""
    if not scans:
        raise EvalError("Nicio copie de noapte de la " + since)
    cases = _serial_cases(scans, since) + _factual_cases(scans) + _golden_pairs(scans, since)
    return {
        "version": CASE_FILE_VERSION,
        "made_by": "scripts/writer_eval.py --discover",
        "made_at": datetime.now(UTC).isoformat(),
        "since": since,
        "backups_scanned": sorted(scans, key=stamp_of),
        "note_ro": (
            "Propunere de cazuri, de revizuit: o zi de serial închisă, un subiect factual cu "
            "afirmații SUSȚINUTE și o teză, perechile de aur. Textele «reference», «a» și «b» "
            "sunt înghețate aici: pe ele răspunde Necunoscutul și tot pe ele Proprietarul. "
            "«state» spune dacă scriitorul primește ziua din copia de dinainte de scriere "
            "(before_write) sau de după (after_write, cu memoria serialului readusă din "
            "continuity_before)."
        ),
        "cases": cases,
    }


def discover(backups: Path, work: Path, since: str, keep_copies: bool) -> dict[str, Any]:
    """Scan a COPY of every nightly backup since ``since`` and propose the cases."""
    names = nightly_backups(backups, since)
    if not names:
        raise EvalError(f"Nicio copie de noapte în {backups} de la {since}")
    folder = work / f"discover-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    scans: dict[str, dict[str, Any]] = {}
    for name in names:
        copy = copy_database(backup_file(backups, name), folder / name.removesuffix(".db"))
        print(f"Citesc copia {copy.name} …", flush=True)
        try:
            scans[name] = scan_backup(copy)
        finally:
            if not keep_copies:
                remove_copy(copy)
    return propose_cases(scans, since)


def write_case_file(path: Path, proposal: Mapping[str, Any], force: bool) -> Path:
    """The proposal in the case file; beside it (``.proposed.json``) when one exists already."""
    target = path
    if path.exists() and not force:
        target = path.with_name(path.stem + ".proposed.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(proposal, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return target


# ----------------------------------------------------------------------------- the copy's state


def _budget_allows(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
    """The day's budget gate on the copy: the copy's day is long past and an LLM call on the
    subscription costs 0 credits (the Owner, 2026-10-12)."""
    return {"allowed": True, "status": None, "reason": "", "tokens_used": 0, "ceiling": 0}


def prepare_copy(engine: Any, case: Mapping[str, Any]) -> dict[str, Any]:
    """Make the copy runnable, on the copy only: the autonomy stop lifted, agents left
    thinking by a dead process idle, runs left RUNNING closed, and a serial day written after
    its first draft given the serial's memory as it stood before (``continuity_before``)."""
    from app.agents.models import Agent, AgentRun  # noqa: PLC0415
    from app.models import OwnerPolicy  # noqa: PLC0415
    from app.services import utc_now  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    changed: dict[str, Any] = {}
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        if policy is not None and policy.autonomy_stopped:
            policy.autonomy_stopped = False
            changed["autonomy_stopped_lifted"] = True
        idle = 0
        for agent in session.scalars(
            select(Agent).where(Agent.runtime_state.not_in(("IDLE", "BLOCKED", "ERROR", "WORKING")))
        ):
            agent.runtime_state = "IDLE"
            agent.version += 1
            idle += 1
        closed = 0
        for run in session.scalars(select(AgentRun).where(AgentRun.status == "RUNNING")):
            run.status = "ABANDONED"
            run.finished_at = utc_now()
            run.error_detail = "Închis de evaluarea scenariștilor, pe copie."
            closed += 1
        changed.update({"agents_made_idle": idle, "runs_closed": closed})
        restore = case.get("continuity_before")
        if case.get("kind") == "serial" and isinstance(restore, Mapping):
            changed.update(_restore_continuity(session, restore))
    return changed


def _restore_continuity(session: Any, restore: Mapping[str, Any]) -> dict[str, Any]:
    """The serial's memory put back as it stood when the day was first written: the canon row,
    and the plan the newest canon episode left (its episode added as a stub, an approved title
    with that plan and no beats, when the copy was taken before it existed)."""
    from app.services import utc_now  # noqa: PLC0415
    from app.story.models import ContinuityState, DailyStudioLog, StoryEpisode  # noqa: PLC0415

    frozen = dict(restore.get("row") or {})
    row = session.get(ContinuityState, 1)
    if row is None:
        row = ContinuityState(id=1, version=1, canon_episode_number=0, updated_at=utc_now())
        session.add(row)
    row.version = int(frozen.get("version") or 1)
    row.canon_episode_number = int(frozen.get("canon_episode_number") or 0)
    row.threads_json = list(frozen.get("threads_json") or [])
    row.recurring_json = list(frozen.get("recurring_json") or [])
    row.summaries_json = list(frozen.get("summaries_json") or [])
    done: dict[str, Any] = {
        "continuity_restored_from": restore.get("from_backup"),
        "continuity_replayed": list(restore.get("replayed") or []),
    }
    plan = restore.get("plan_episode")
    if not isinstance(plan, Mapping) or not plan.get("id"):
        return done
    next_episode = plan.get("next_episode")
    episode = session.get(StoryEpisode, str(plan["id"]))
    if episode is None and plan.get("log_id") and session.get(DailyStudioLog, plan["log_id"]):
        episode = StoryEpisode(
            id=str(plan["id"]),
            log_id=str(plan["log_id"]),
            title=str(plan.get("title") or ""),
            beats_json=[],
            grounded_event_ids_json=[],
            continuity_json={},
            status="APPROVED",
            created_at=str(plan.get("created_at") or utc_now()),
            reviewed_by="evaluation stub",
        )
        session.add(episode)
        done["plan_episode_stub"] = str(plan["id"])
    if episode is not None and isinstance(next_episode, Mapping):
        episode.continuity_json = {
            **dict(episode.continuity_json or {}),
            "next_episode": dict(next_episode),
        }
        done["plan_restored"] = str(plan["id"])
    return done


def ensure_stranger(engine: Any, model: Mapping[str, Any]) -> str:
    """The stranger as an employee of the COPY (a role of its own, no contract, no memory, no
    bible), on the judge's model; its id."""
    from app.agents.models import Agent, Role  # noqa: PLC0415
    from app.services import append_event, utc_now  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    correlation = str(uuid4())
    with Session(engine) as session, session.begin():
        role = session.scalar(select(Role).where(Role.name == STRANGER_ROLE))
        if role is None:
            role_id = str(uuid4())
            event = append_event(
                session, "eval.stranger_role_added", "role", role_id, 1, {"copy": True}, correlation
            )
            role = Role(
                id=role_id,
                name=STRANGER_ROLE,
                mission="Answer, as a stranger, what a viewer gets of a short video.",
                allowed_task_types="stranger_judgement,stranger_pairwise",
                prohibited_actions="self_escalate,bypass_policy",
                work_contract_json={},
                memory_scope_json={},
                contract_version=0,
                created_at=utc_now(),
                event_id=event.event_id,
            )
            session.add(role)
            session.flush()
        agent = session.scalar(select(Agent).where(Agent.role_id == role.id))
        if agent is None:
            agent_id = str(uuid4())
            event = append_event(
                session, "eval.stranger_added", "agent", agent_id, 1, {"copy": True}, correlation
            )
            agent = Agent(
                id=agent_id,
                display_name=STRANGER_NAME,
                role_id=role.id,
                provider_id=str(model["provider_id"]),
                model_id=str(model["id"]),
                lifecycle="ACTIVE",
                runtime_state="IDLE",
                max_concurrent_tasks=1,
                version=1,
                hired_at=utc_now(),
                event_id=event.event_id,
            )
            session.add(agent)
        else:
            agent.model_id = str(model["id"])
            agent.provider_id = str(model["provider_id"])
            agent.lifecycle = "ACTIVE"
            agent.runtime_state = "IDLE"
        session.flush()
        return str(agent.id)


def writer_of(engine: Any, kind: str) -> str:
    """The employee today's code would ask to write (`_resolve_showrunner` / `_resolve_agent`)."""
    from app.factual.agent_pipeline import PREFERRED_WRITER_ROLE, _resolve_agent  # noqa: PLC0415
    from app.story.services import _resolve_showrunner  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as session:
        agent = (
            _resolve_showrunner(session, None)
            if kind == "serial"
            else _resolve_agent(session, None, PREFERRED_WRITER_ROLE)
        )
        return str(agent.id)


def kernel_refusal(engine: Any, registry: Any, agent_id: str, model_id: str) -> str | None:
    """What the policy kernel would refuse a run of ``agent_id`` on ``model_id`` for, asked on
    the copy and rolled back; None when it would let it run."""
    from app.agents.models import Agent  # noqa: PLC0415
    from app.agents.services import PolicyKernelError, _assert_policy_allows_run  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as session:
        try:
            agent = session.get(Agent, agent_id)
            if agent is None:
                return "angajatul nu există pe copie"
            _assert_policy_allows_run(session, agent, registry, model_id=model_id)
        except PolicyKernelError as exc:
            return f"{exc.status}: {exc.block_reason}"
        finally:
            session.rollback()
    return None


# ----------------------------------------------------------------------------- the patches


@contextmanager
def writer_patches(model_id: str | None, capture: list[str] | None = None) -> Iterator[None]:
    """For the length of a writer's call: its model pinned (``model_id`` on every writer run),
    the Director's lesson reading switched off, the day's budget gate open. With ``capture``
    the brief is kept and never sent (`_DryStop`)."""
    from app.agents import services as agent_services  # noqa: PLC0415
    from app.evals.variants import replaced  # noqa: PLC0415
    from app.factual import agent_pipeline  # noqa: PLC0415
    from app.media import prompt_agent  # noqa: PLC0415
    from app.story import services as story_services  # noqa: PLC0415

    real = agent_services.run_agent_task

    def pinned(
        engine: Any,
        registry: Any,
        agent_id: str,
        task_type: str,
        objective: str,
        *args: Any,
        **kwargs: Any,
    ) -> dict:
        if capture is not None:
            capture.append(objective)
            raise _DryStop(task_type)
        if model_id is not None and task_type in WRITER_TASKS and not kwargs.get("model_id"):
            kwargs["model_id"] = model_id
        return real(engine, registry, agent_id, task_type, objective, *args, **kwargs)

    def no_lesson_reading(*_args: Any, **_kwargs: Any) -> int:
        return 0

    with ExitStack() as stack:
        stack.enter_context(replaced(story_services, "run_agent_task", pinned))
        stack.enter_context(replaced(agent_pipeline, "run_agent_task", pinned))
        stack.enter_context(replaced(prompt_agent, "reconcile_prompt_lessons", no_lesson_reading))
        stack.enter_context(replaced(agent_services, "may_run_agent", _budget_allows))
        yield


@contextmanager
def judge_patches(stranger_id: str) -> Iterator[None]:
    """For the length of the stranger's calls: its identity bare (no memory, no inbox, no
    persona, no contract), every other employee's untouched; the budget gate open."""
    from app.agents import services as agent_services  # noqa: PLC0415
    from app.agents.identity import Identity  # noqa: PLC0415
    from app.evals.stranger import IDENTITY_VERSION, STRANGER_SYSTEM  # noqa: PLC0415
    from app.evals.variants import replaced  # noqa: PLC0415
    from app.services import utc_now  # noqa: PLC0415

    real = agent_services.compose_identity

    def bare(session: Any, agent: Any, *, task_type: str = "") -> Any:
        if agent.id != stranger_id:
            return real(session, agent, task_type=task_type)
        return Identity(
            system=STRANGER_SYSTEM,
            context={
                "identity_version": IDENTITY_VERSION,
                "profile": "BARE",
                "memory_record_ids": [],
                "open_message_ids": [],
                "system_sha256": hashlib.sha256(STRANGER_SYSTEM.encode("utf-8")).hexdigest(),
                "system_chars": len(STRANGER_SYSTEM),
                "task_type": task_type,
                "composed_at": utc_now(),
            },
        )

    with ExitStack() as stack:
        stack.enter_context(replaced(agent_services, "compose_identity", bare))
        stack.enter_context(replaced(agent_services, "may_run_agent", _budget_allows))
        yield


# ----------------------------------------------------------------------------- the writers


def target_of(case: Mapping[str, Any], override: int | None) -> int:
    """The factual film's length: ``--target-seconds``, the case's, else today's setting (the
    studio's ``.env`` when it can be read here, else the code's default)."""
    from app.config import Settings  # noqa: PLC0415

    if override:
        return int(override)
    if case.get("target_seconds"):
        return int(case["target_seconds"])
    try:
        return int(Settings().target_video_seconds)  # type: ignore[call-arg]
    except Exception:  # noqa: BLE001 - no usable .env here: the code's own default
        return int(Settings.model_fields["target_video_seconds"].default)


def write(
    engine: Any, registry: Any, case: Mapping[str, Any], correlation: str, target: int
) -> dict[str, Any]:
    """Today's writer on the copy; what it produced (``DRAFTED``) or why not (``REFUSED``)."""
    from app.factual.agent_pipeline import (  # noqa: PLC0415
        NoVerifiedClaims,
        ScriptBlocked,
        ScriptRejected,
        agent_write_script,
    )
    from app.factual.services import FactualGateError  # noqa: PLC0415
    from app.story.services import StoryError, write_episode  # noqa: PLC0415

    language = str(case.get("language") or "en")
    refusals = (StoryError, ScriptRejected, ScriptBlocked, NoVerifiedClaims, FactualGateError)
    try:
        if case["kind"] == "serial":
            written = write_episode(
                engine, registry, case["log_id"], correlation, language=language
            )
            return {
                "status": "DRAFTED",
                "episode_id": written["episode"]["id"],
                "run_id": written["run_id"],
                "attempts": written.get("attempts"),
            }
        made = agent_write_script(
            engine,
            registry,
            case["topic_id"],
            correlation,
            target_duration_seconds=target,
            language=language,
        )
        return {
            "status": "DRAFTED",
            "script_id": made["script"]["id"],
            "run_id": made["run_id"],
            "cut_scenes": made.get("cut_scenes") or [],
        }
    except refusals as exc:
        return {"status": "REFUSED", "error_type": type(exc).__name__, "reason": str(exc)[:600]}


# ----------------------------------------------------------------------------- the checks


def _check(name: str, passed: bool, reason: str = "", advisory: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "advisory": bool(advisory),
        "reason": "" if passed else " ".join(str(reason or "").split())[:400],
    }


def serial_checks(engine: Any, episode_id: str, language: str) -> list[dict[str, Any]]:
    """The review's own checks on the stored draft (`story.review.draft_checks`); the brief's
    choice of speakers and the review's recommendations are advisory, as they are for the
    writer (`story.services._measured_refusals`)."""
    from app.story.models import StoryEpisode  # noqa: PLC0415
    from app.story.review import draft_checks  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as session:
        episode = session.get(StoryEpisode, episode_id)
        if episode is None:
            return [_check("stored", False, "episodul nu este pe copie")]
        offered = list((episode.continuity_json or {}).get("speakers_offered") or [])
        checks = draft_checks(session, episode, offered, language)
        session.rollback()
    return [
        _check(
            name,
            bool(result.get("passed")),
            str(result.get("reason") or name),
            advisory=bool(result.get("advisory")) or name == "offered_speakers",
        )
        for name, result in checks.items()
    ]


def factual_checks(
    engine: Any, topic_id: str, raw: str | None, script_id: str | None, target: int
) -> list[dict[str, Any]]:
    """The writer gate's checks on the writer's final answer (an object, every scene citing a
    verified claim, the schema, the citations, the cards, the word budget, the 180 s wall) and
    the review's computed checks (`factual.editorial.story_checks`) on the stored draft."""
    from app.factual.agent_pipeline import (  # noqa: PLC0415
        ScriptBlocked,
        ScriptRejected,
        _check_citations,
        _parse_script,
        _scene_kinds,
        _script_object,
        _uncited_scenes,
    )
    from app.factual.editorial import (  # noqa: PLC0415
        MAX_SHORT_SECONDS,
        expected_seconds,
        narration_budget,
        story_checks,
    )
    from app.factual.models import FactualClaim, ScriptDraft  # noqa: PLC0415
    from app.factual.story_review import ADVISORY_CHECKS  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    rows: list[dict[str, Any]] = []
    with Session(engine) as session:
        allowed = {
            claim.id: claim.claim_text
            for claim in session.scalars(
                select(FactualClaim).where(
                    FactualClaim.topic_id == topic_id, FactualClaim.status == "SUPPORTED"
                )
            )
        }
        stored = session.get(ScriptDraft, script_id) if script_id else None
        stored_view = (
            (stored.title, list(stored.scenes_json or []), dict(stored.story_json or {}))
            if stored is not None
            else None
        )
    text = raw or ""
    rows.append(_check("answer_is_an_object", _script_object(text) is not None, "fără obiect JSON"))
    uncited = _uncited_scenes(text)
    rows.append(
        _check(
            "every_scene_cites_a_claim",
            not uncited,
            f"{len(uncited)} scene nu citează nicio afirmație verificată"
            + (f" («{uncited[0]}»)" if uncited else ""),
        )
    )
    draft = None
    try:
        draft = _parse_script(text)
        rows.append(_check("follows_the_schema", True))
    except (ScriptRejected, ScriptBlocked) as exc:
        rows.append(_check("follows_the_schema", False, str(exc)))
    if draft is not None:
        try:
            _check_citations(draft, allowed)
            rows.append(_check("cites_only_verified_claims", True))
        except ScriptRejected as exc:
            rows.append(_check("cites_only_verified_claims", False, str(exc)))
        _kinds, faults = _scene_kinds(draft, allowed)
        rows.append(_check("cards_carry_their_claims", not faults, "; ".join(faults[:3])))
        budget = narration_budget(target)
        words = sum(len(scene.narration.split()) for scene in draft.scenes)
        rows.append(
            _check(
                "within_the_word_budget",
                budget["min_words"] <= words <= budget["max_words"],
                f"{words} cuvinte rostite; bugetul la {target} s este "
                f"{budget['min_words']}-{budget['max_words']}",
            )
        )
        seconds = expected_seconds([{"narration": scene.narration} for scene in draft.scenes])
        rows.append(
            _check(
                "under_the_180_s_wall",
                seconds <= MAX_SHORT_SECONDS,
                f"{seconds:.0f} s, peste {MAX_SHORT_SECONDS:.0f} s",
            )
        )
    if stored_view is not None:
        title, scenes, story = stored_view
        for name, result in story_checks(
            title=title, scenes=scenes, story=story, target_seconds=target
        ).items():
            rows.append(
                _check(
                    f"review.{name}",
                    bool(result.get("passed")),
                    str(result.get("reason") or name),
                    advisory=name in ADVISORY_CHECKS,
                )
            )
    return rows


def checks_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """How many of the binding checks passed, and the advisory ones apart."""
    binding = [row for row in rows if not row["advisory"]]
    return {
        "passed": sum(1 for row in binding if row["passed"]),
        "total": len(binding),
        "failed": [row["name"] for row in binding if not row["passed"]],
        "advisory_failed": [row["name"] for row in rows if row["advisory"] and not row["passed"]],
    }


# ----------------------------------------------------------------------------- the stranger


def ask_stranger(
    engine: Any, registry: Any, stranger_id: str, view: Any, correlation: str, label: str
) -> dict[str, Any]:
    """The five questions about one text, in the three orders; the answers averaged."""
    from app.agents.structured import structured_run  # noqa: PLC0415
    from app.evals.stranger import (  # noqa: PLC0415
        ORDERS,
        QUESTIONS,
        STRANGER_TASK,
        TEMPLATE_VERSION,
        StrangerAnswer,
        combine,
        question_prompt,
    )

    per_order: list[dict[str, bool] | None] = []
    calls = []
    for index, order in enumerate(ORDERS, start=1):
        parsed, first, second = structured_run(
            engine,
            registry,
            stranger_id,
            STRANGER_TASK,
            question_prompt(view, order),
            TEMPLATE_VERSION,
            correlation,
            StrangerAnswer,
            "",
            summary=f"Necunoscutul răspunde la cele cinci întrebări ({label}, ordinea {index})",
            max_tokens=JUDGE_MAX_TOKENS,
            temperature=JUDGE_TEMPERATURE,
        )
        answers = parsed.by_key() if parsed is not None else None
        per_order.append({key: item.answer for key, item in answers.items()} if answers else None)
        calls.append(
            {
                "order": [QUESTIONS[position].key for position in order],
                "run_ids": [run["id"] for run in (first, second) if run],
                "answered": answers is not None,
                "refusal": (second or first).get("refusal")
                or (second or first).get("error_detail"),
                "answers": {
                    key: {"answer": item.answer, "why": item.why} for key, item in answers.items()
                }
                if answers
                else None,
            }
        )
    return {
        "text_sha256": view.sha256(),
        "seconds": view.seconds,
        "calls": calls,
        **combine(per_order),
    }


def ask_pairwise(
    engine: Any,
    registry: Any,
    stranger_id: str,
    x_view: Any,
    y_view: Any,
    correlation: str,
    *,
    x: str,
    y: str,
) -> dict[str, Any]:
    """«Which would a stranger watch to the end?» about ``x`` and ``y``, in both orders."""
    from app.agents.structured import structured_run  # noqa: PLC0415
    from app.evals.stranger import (  # noqa: PLC0415
        PAIRWISE_TASK,
        PAIRWISE_TEMPLATE_VERSION,
        PairwiseAnswer,
        pairwise_outcome,
        pairwise_prompt,
    )

    choices: list[str | None] = []
    calls = []
    for shown_first, first_view, second_view in ((x, x_view, y_view), (y, y_view, x_view)):
        parsed, first, second = structured_run(
            engine,
            registry,
            stranger_id,
            PAIRWISE_TASK,
            pairwise_prompt(first_view, second_view),
            PAIRWISE_TEMPLATE_VERSION,
            correlation,
            PairwiseAnswer,
            "",
            summary=f"Necunoscutul alege între două filme (A = {shown_first})",
            max_tokens=JUDGE_MAX_TOKENS,
            temperature=JUDGE_TEMPERATURE,
        )
        choices.append(parsed.choice if parsed is not None else None)
        calls.append(
            {
                "a_is": shown_first,
                "choice": parsed.choice if parsed is not None else None,
                "why": parsed.why if parsed is not None else None,
                "run_ids": [run["id"] for run in (first, second) if run],
            }
        )
    return {"outcome": pairwise_outcome(choices[0], choices[1], x=x, y=y), "calls": calls}


# ----------------------------------------------------------------------------- reading back


def runs_of(engine: Any, correlation: str) -> list[dict[str, Any]]:
    """Every call this case made, from the copy's ``agent_run``: tokens, seconds, hashes."""
    from app.agents.models import AgentRun  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as session:
        rows = list(
            session.scalars(
                select(AgentRun)
                .where(AgentRun.correlation_id == correlation)
                .order_by(AgentRun.started_at)
            )
        )
        found = []
        for run in rows:
            started, finished = _moment(run.started_at), _moment(run.finished_at)
            context = run.context_json if isinstance(run.context_json, dict) else {}
            found.append(
                {
                    "id": run.id,
                    "task_type": run.task_type,
                    "model": run.model_name,
                    "status": run.status,
                    "template": run.prompt_template_version,
                    "prompt_tokens": run.prompt_tokens,
                    "completion_tokens": run.completion_tokens,
                    "latency_s": round((finished - started).total_seconds(), 1)
                    if started and finished
                    else None,
                    "objective_chars": len(run.objective or ""),
                    "objective_sha256": hashlib.sha256(
                        (run.objective or "").encode("utf-8")
                    ).hexdigest(),
                    "system_chars": context.get("system_chars"),
                    "system_sha256": context.get("system_sha256"),
                    "identity_version": context.get("identity_version"),
                    "error": " ".join(str(run.error_detail or "").split())[:240] or None,
                }
            )
    return found


def _writer_raw(engine: Any, correlation: str, run_id: str | None) -> str | None:
    """The writer's final answer: the run the writer kept, else its last answer."""
    from app.agents.models import AgentRun  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as session:
        if run_id:
            run = session.get(AgentRun, run_id)
            if run is not None and run.output_text:
                return str(run.output_text)
        last = session.scalars(
            select(AgentRun)
            .where(
                AgentRun.correlation_id == correlation,
                AgentRun.task_type.in_(WRITER_TASKS),
                AgentRun.output_text.is_not(None),
            )
            .order_by(AgentRun.started_at.desc())
        ).first()
        return str(last.output_text) if last is not None else None


def new_text(engine: Any, written: Mapping[str, Any]) -> dict[str, Any] | None:
    """The draft the writer stored on the copy, kept as its view needs it."""
    from app.evals.stranger import frozen_episode, frozen_script  # noqa: PLC0415
    from app.factual.models import ScriptDraft  # noqa: PLC0415
    from app.story.models import StoryEpisode  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    with Session(engine) as session:
        if written.get("episode_id"):
            episode = session.get(StoryEpisode, written["episode_id"])
            return frozen_episode(episode.title, episode.beats_json or []) if episode else None
        if written.get("script_id"):
            script = session.get(ScriptDraft, written["script_id"])
            return frozen_script(script.title, script.scenes_json or []) if script else None
    return None


# ----------------------------------------------------------------------------- one case


def _calls_planned(case: Mapping[str, Any], skip_reference: bool) -> tuple[int, int]:
    """The fewest and the most model calls a case makes (for the dry run's plan)."""
    if case["kind"] == "golden_pair":
        texts = 2
        low = texts * STRANGER_CALLS[0] + PAIRWISE_CALLS[0]
        high = texts * STRANGER_CALLS[1] + PAIRWISE_CALLS[1]
        return low, high
    writer_low, writer_high = WRITER_CALLS[case["kind"]]
    reference = case.get("reference") is not None
    texts = 1 + (1 if reference and not skip_reference else 0)
    low = writer_low + texts * STRANGER_CALLS[0] + (PAIRWISE_CALLS[0] if reference else 0)
    high = writer_high + texts * STRANGER_CALLS[1] + (PAIRWISE_CALLS[1] if reference else 0)
    return low, high


class RunSettings:
    """What every case of one run shares."""

    def __init__(self, args: argparse.Namespace, variant: Any) -> None:
        self.args = args
        self.variant = variant
        self.backups = Path(args.backups)
        self.vault_key = (
            Path(args.vault_key)
            if args.vault_key
            else self.backups.parent / "studio.credentials.key"
        )
        self.dry_run = bool(args.dry_run)


def _case_models(
    engine: Any, case: Mapping[str, Any], settings: RunSettings
) -> tuple[dict | None, dict | None, list[str]]:
    """(the writer's model, the judge's, why the case cannot run) on this copy."""
    problems = []
    writer = None
    if case["kind"] in TEXT_KINDS:
        name = settings.args.writer_model or case.get("writer_model")
        if not name:
            problems.append("cazul nu are un model de scriitor; dă --writer-model")
        elif forbidden_writer(name):
            problems.append(
                f"modelul scriitorului {name} este interzis scriitorilor (Proprietarul, "
                "2026-10-15); dă --writer-model"
            )
        else:
            writer = resolve_model(engine, str(name))
            if writer is None:
                problems.append(f"modelul scriitorului {name} nu există pe copie")
    judge = resolve_model(engine, settings.args.judge_model)
    if judge is None:
        problems.append(f"modelul judecătorului {settings.args.judge_model} nu există pe copie")
    return writer, judge, problems


def run_case(case: Mapping[str, Any], settings: RunSettings, work: Path) -> dict[str, Any]:
    """One case on its own copy: the writer (unless a golden pair), the checks, the stranger."""
    from app.evals.stranger import view_of  # noqa: PLC0415
    from app.providers.registry import ProviderRegistry  # noqa: PLC0415

    args = settings.args
    started = time.monotonic()
    result: dict[str, Any] = {
        "id": case["id"],
        "kind": case["kind"],
        "backup": case["backup"],
        "state": case.get("state"),
        "planned_calls": list(_calls_planned(case, args.skip_reference)),
    }
    copy: Path | None = None
    engine: Any = None
    try:
        copy = copy_database(backup_file(settings.backups, case["backup"]), work / case["id"])
        engine = open_copy(copy)
        result["copy_prepared"] = prepare_copy(engine, case)
        writer_model, judge_model, problems = _case_models(engine, case, settings)
        result["writer_model"] = writer_model["model_name"] if writer_model else None
        result["judge_model"] = judge_model["model_name"] if judge_model else None
        if problems:
            result["error"] = "; ".join(problems)
            return result
        assert judge_model is not None
        stranger_id = ensure_stranger(engine, judge_model)
        providers = {judge_model["provider_id"]} | (
            {writer_model["provider_id"]} if writer_model else set()
        )
        if settings.dry_run:
            registry: Any = ProviderRegistry()
            result["registry"] = {"dry_run": "vault not read; no provider registered"}
        else:
            registry, found = llm_registry(engine, settings.vault_key, providers)
            result["registry"] = found
            if found["missing"]:
                result["error"] = (
                    "conexiunea modelului nu a putut fi citită din seif: "
                    + ", ".join(found["missing"])
                )
                return result
        writer_id = writer_of(engine, case["kind"]) if case["kind"] in TEXT_KINDS else None
        gates = {"judge": kernel_refusal(engine, registry, stranger_id, judge_model["id"])}
        if writer_id and writer_model:
            gates["writer"] = kernel_refusal(engine, registry, writer_id, writer_model["id"])
        result["kernel"] = gates
        refused = {who: why for who, why in gates.items() if why}
        if refused:
            result["error"] = "nucleul de politici refuză: " + "; ".join(
                f"{who}: {why}" for who, why in refused.items()
            )
            return result
        correlation = str(uuid4())
        result["correlation_id"] = correlation
        if case["kind"] == "golden_pair":
            _judge_pair(engine, registry, stranger_id, case, correlation, result, settings)
        else:
            assert writer_model is not None
            _write_and_judge(
                engine, registry, stranger_id, writer_model, case, correlation, result, settings
            )
        reference = case.get("reference")
        if reference is not None:
            result["reference_key"] = reference["text_key"]
            result["reference_sha256"] = view_of(reference["view"]).sha256()
        return result
    except MediaAdapterFound:
        raise
    except Exception as exc:  # noqa: BLE001 - one case's failure is reported, the run goes on
        result["error"] = f"{type(exc).__name__}: {' '.join(str(exc).split())[:400]}"
        return result
    finally:
        if engine is not None:
            if result.get("correlation_id") and not settings.dry_run:
                try:  # every call made, even by a case that failed half-way
                    result["runs"] = runs_of(engine, result["correlation_id"])
                except Exception as exc:  # noqa: BLE001 - the copy itself may be the fault
                    result["runs_error"] = type(exc).__name__
            engine.dispose()
        result["seconds"] = round(time.monotonic() - started, 1)
        if copy is not None and not args.keep_copies:
            remove_copy(copy)


def _write_and_judge(
    engine: Any,
    registry: Any,
    stranger_id: str,
    writer_model: Mapping[str, Any],
    case: Mapping[str, Any],
    correlation: str,
    result: dict[str, Any],
    settings: RunSettings,
) -> None:
    from app.evals.stranger import view_of  # noqa: PLC0415
    from app.evals.variants import fingerprint  # noqa: PLC0415

    args = settings.args
    target = target_of(case, args.target_seconds)
    if case["kind"] == "factual":
        result["target_seconds"] = target
    capture: list[str] | None = [] if settings.dry_run else None
    with settings.variant.install(), writer_patches(writer_model["id"], capture=capture):
        result["fingerprint"] = fingerprint(case["kind"])
        try:
            written = write(engine, registry, case, correlation, target)
        except _DryStop:
            written = {"status": "DRY_RUN"}
    result["writer"] = written
    reference = case.get("reference")
    reference_view = view_of(reference["view"]) if reference else None
    if settings.dry_run:
        brief = capture[0] if capture else None
        result["brief"] = (
            {
                "chars": len(brief),
                "sha256": hashlib.sha256(brief.encode("utf-8")).hexdigest(),
            }
            if brief is not None
            else None
        )
        if reference_view is not None:
            result["reference_view"] = {
                "chars": len(reference_view.render()),
                "seconds": reference_view.seconds,
                "title": reference_view.title,
            }
        return
    language = str(case.get("language") or "en")
    raw = _writer_raw(engine, correlation, written.get("run_id"))
    if case["kind"] == "serial":
        checks = (
            serial_checks(engine, written["episode_id"], language)
            if written.get("episode_id")
            else [_check("stored", False, written.get("reason") or "nimic scris")]
        )
    else:
        checks = factual_checks(engine, case["topic_id"], raw, written.get("script_id"), target)
    result["checks"] = checks
    result["checks_summary"] = checks_summary(checks)
    drafted = new_text(engine, written) if written.get("status") == "DRAFTED" else None
    result["new_text"] = drafted
    new_view = view_of(drafted) if drafted else None
    with judge_patches(stranger_id):
        if new_view is not None:
            result["stranger_new"] = ask_stranger(
                engine, registry, stranger_id, new_view, correlation, "ciorna nouă"
            )
        if reference_view is not None and not args.skip_reference:
            result["stranger_reference"] = ask_stranger(
                engine, registry, stranger_id, reference_view, correlation, "versiunea livrată"
            )
        if new_view is not None and reference_view is not None:
            result["pairwise"] = ask_pairwise(
                engine,
                registry,
                stranger_id,
                new_view,
                reference_view,
                correlation,
                x="new",
                y="reference",
            )
        elif reference_view is not None:
            result["pairwise"] = {"outcome": "reference", "why": "nicio ciornă nouă"}


def _judge_pair(
    engine: Any,
    registry: Any,
    stranger_id: str,
    case: Mapping[str, Any],
    correlation: str,
    result: dict[str, Any],
    settings: RunSettings,
) -> None:
    from app.evals.stranger import view_of  # noqa: PLC0415

    views = {side: view_of(case[side]["view"]) for side in ("a", "b")}
    result["texts"] = {
        side: {
            "key": case[side]["text_key"],
            "title": views[side].title,
            "seconds": views[side].seconds,
            "chars": len(views[side].render()),
            "sha256": views[side].sha256(),
        }
        for side in ("a", "b")
    }
    result["expected"] = case.get("expected")
    if settings.dry_run:
        return
    with judge_patches(stranger_id):
        for side in ("a", "b"):
            result[f"stranger_{side}"] = ask_stranger(
                engine, registry, stranger_id, views[side], correlation, f"textul {side.upper()}"
            )
        result["pairwise"] = ask_pairwise(
            engine, registry, stranger_id, views["a"], views["b"], correlation, x="a", y="b"
        )
    outcome = result["pairwise"]["outcome"]
    expected = case.get("expected")
    result["matches_expected"] = (
        None if expected is None or outcome in ("tie", "incomplete") else (outcome == expected)
    )


# ----------------------------------------------------------------------------- totals


def judged_texts(results: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """The stranger's majority answers per text key, for the agreement with the Owner."""
    found: dict[str, dict[str, Any]] = {}
    for result in results:
        pairs = []
        if result.get("reference_key") and result.get("stranger_reference"):
            pairs.append((result["reference_key"], result["stranger_reference"]))
        for side in ("a", "b"):
            key = (result.get("texts") or {}).get(side, {}).get("key")
            if key and result.get(f"stranger_{side}"):
                pairs.append((key, result[f"stranger_{side}"]))
        for key, judged in pairs:
            found[key] = {
                question: entry.get("majority")
                for question, entry in (judged.get("questions") or {}).items()
            }
    return found


def _mean(values: Iterable[float | None]) -> float | None:
    kept = [float(value) for value in values if value is not None]
    return round(sum(kept) / len(kept), 3) if kept else None


def totals(results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The run in numbers: drafts, checks, the stranger's scores, the pairs, the calls."""
    from app.evals.stranger import QUESTION_KEYS  # noqa: PLC0415

    writers = [result for result in results if result["kind"] in TEXT_KINDS]
    drafted = [r for r in writers if (r.get("writer") or {}).get("status") == "DRAFTED"]
    passed = sum((r.get("checks_summary") or {}).get("passed", 0) for r in writers)
    checked = sum((r.get("checks_summary") or {}).get("total", 0) for r in writers)
    all_checks = [
        r for r in drafted if r.get("checks_summary") and not r["checks_summary"]["failed"]
    ]
    outcomes = [(r.get("pairwise") or {}).get("outcome") for r in writers if r.get("pairwise")]
    golden = [r for r in results if r["kind"] == "golden_pair" and "pairwise" in r]
    runs = [run for r in results for run in r.get("runs") or []]
    per_question = {
        key: _mean(
            ((r.get("stranger_new") or {}).get("questions") or {}).get(key, {}).get("yes_rate")
            for r in writers
        )
        for key in QUESTION_KEYS
    }
    return {
        "cases": len(results),
        "errors": sum(1 for r in results if r.get("error")),
        "writer_cases": len(writers),
        "drafted": len(drafted),
        "drafts_passing_every_check": len(all_checks),
        "checks_passed": passed,
        "checks_total": checked,
        "stranger_new_mean": _mean((r.get("stranger_new") or {}).get("score") for r in writers),
        "stranger_new_mean_strict": _mean(
            (r.get("stranger_new") or {}).get("score", 0.0) if "error" not in r else None
            for r in writers
        ),
        "stranger_reference_mean": _mean(
            (r.get("stranger_reference") or {}).get("score") for r in writers
        ),
        "stranger_new_yes_rate": per_question,
        "pairwise": {
            label: outcomes.count(label) for label in ("new", "reference", "tie", "incomplete")
        },
        "golden_pairs": len(golden),
        "golden_matching": sum(1 for r in golden if r.get("matches_expected") is True),
        "golden_against": sum(1 for r in golden if r.get("matches_expected") is False),
        "calls": len(runs),
        "prompt_tokens": sum(run.get("prompt_tokens") or 0 for run in runs),
        "completion_tokens": sum(run.get("completion_tokens") or 0 for run in runs),
        "latency_s": round(sum(run.get("latency_s") or 0.0 for run in runs), 1),
    }


# ----------------------------------------------------------------------------- the report


def _cell(text: Any, limit: int = 140) -> str:
    words = " ".join(str(text if text is not None else "—").split()).replace("|", "/")
    return words if len(words) <= limit else words[: limit - 1] + "…"


def _score(value: Any) -> str:
    return "—" if value is None else f"{float(value):.2f}".replace(".", ",") + "/5"


def report_markdown(
    results: Sequence[Mapping[str, Any]], summary: Mapping[str, Any], meta: Mapping[str, Any]
) -> str:
    """The run for the Owner, in Romanian tables."""
    from app.evals.stranger import QUESTIONS  # noqa: PLC0415

    dry = bool(meta.get("dry_run"))
    rows = [
        f"# Evaluarea scenariștilor — varianta «{meta['variant']}»"
        + (" (probă: niciun model întrebat)" if dry else ""),
        "",
        f"- Făcută la: {meta['made_at']}; codul: `{meta.get('commit') or '?'}`",
        f"- Scriitorul: {meta.get('writer_model') or 'modelul original al fiecărui caz'}; "
        f"Necunoscutul: {meta['judge_model']} (identitate goală)",
        f"- Fișierul de cazuri: `{meta['case_file']}` "
        f"(sha256 `{str(meta['case_file_sha256'])[:12]}`)",
        f"- Varianta: {meta['variant_description']}",
        "",
    ]
    if dry:
        rows += [
            "## Ce s-ar întreba",
            "",
            "| Caz | Tip | Copia | Starea | Scriitor | Brief (caractere) | Referința | Apeluri "
            "| Problemă |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in results:
            brief = (r.get("brief") or {}).get("chars")
            ref = r.get("reference_view") or {}
            texts = r.get("texts") or {}
            reference = (
                f"{ref.get('title')} ({ref.get('seconds')} s)"
                if ref
                else " / ".join(f"{side.upper()}: {t['title']}" for side, t in texts.items()) or "—"
            )
            rows.append(
                f"| {r['id']} | {KIND_RO[r['kind']]} | {r['backup']} | "
                f"{STATE_RO.get(str(r.get('state')), r.get('state') or '—')} | "
                f"{r.get('writer_model') or '—'} | {brief or '—'} | {_cell(reference, 70)} | "
                f"{r['planned_calls'][0]}-{r['planned_calls'][1]} | {_cell(r.get('error'), 120)} |"
            )
        rows.append("")
        return "\n".join(rows) + "\n"
    rows += [
        "## Pe scurt",
        "",
        f"- Cazuri: {summary['cases']} ({summary['writer_cases']} de scris, "
        f"{summary['golden_pairs']} perechi de aur), cu erori: {summary['errors']}",
        f"- Ciorne scrise: {summary['drafted']} din {summary['writer_cases']}; trec toate "
        f"verificările: {summary['drafts_passing_every_check']}; verificări trecute: "
        f"{summary['checks_passed']} din {summary['checks_total']}",
        f"- Necunoscutul, media pe ciornele noi: {_score(summary['stranger_new_mean'])} "
        f"(cu ciornele lipsă la 0: {_score(summary['stranger_new_mean_strict'])}); pe versiunile "
        f"livrate: {_score(summary['stranger_reference_mean'])}",
        "- Perechea nou/livrat: "
        + ", ".join(f"{OUTCOME_RO[key]} {value}" for key, value in summary["pairwise"].items()),
        f"- Perechile de aur: {summary['golden_matching']} cum se știa, "
        f"{summary['golden_against']} invers",
        f"- Apeluri: {summary['calls']}; tokeni {summary['prompt_tokens']} în / "
        f"{summary['completion_tokens']} out; {summary['latency_s']} s",
        "",
        "## Pe întrebări (ciornele noi: cât de des «da»)",
        "",
        "| Întrebarea | «da» |",
        "|---|---|",
    ]
    for question in QUESTIONS:
        rate = summary["stranger_new_yes_rate"].get(question.key)
        rows.append(f"| {question.ro} | {'—' if rate is None else f'{rate:.0%}'} |")
    rows += [
        "",
        "## Pe cazuri",
        "",
        "| Caz | Tip | Starea | Ciorna | Verificări | Necunoscutul: nou | Necunoscutul: livrat | "
        "Perechea | Apeluri | Tokeni (în/out) | Secunde |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r["kind"] == "golden_pair":
            continue
        runs = r.get("runs") or []
        summary_row = r.get("checks_summary") or {}
        writer = r.get("writer") or {}
        draft = writer.get("status") or ("EROARE" if r.get("error") else "—")
        rows.append(
            f"| {r['id']} | {KIND_RO[r['kind']]} | {STATE_RO.get(str(r.get('state')), '—')} | "
            f"{draft} | {summary_row.get('passed', '—')}/{summary_row.get('total', '—')} | "
            f"{_score((r.get('stranger_new') or {}).get('score'))} | "
            f"{_score((r.get('stranger_reference') or {}).get('score'))} | "
            f"{OUTCOME_RO.get((r.get('pairwise') or {}).get('outcome'), '—')} | {len(runs)} | "
            f"{sum(x.get('prompt_tokens') or 0 for x in runs)}/"
            f"{sum(x.get('completion_tokens') or 0 for x in runs)} | {r.get('seconds', '—')} |"
        )
    golden = [r for r in results if r["kind"] == "golden_pair"]
    if golden:
        rows += [
            "",
            "## Perechile de aur",
            "",
            "| Pereche | A | B | Se știe | Necunoscutul alege | Scor A | Scor B | Potrivire |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in golden:
            texts = r.get("texts") or {}
            match = r.get("matches_expected")
            rows.append(
                f"| {r['id']} | {_cell((texts.get('a') or {}).get('title'), 50)} | "
                f"{_cell((texts.get('b') or {}).get('title'), 50)} | "
                f"{OUTCOME_RO.get(r.get('expected'), '—')} | "
                f"{OUTCOME_RO.get((r.get('pairwise') or {}).get('outcome'), '—')} | "
                f"{_score((r.get('stranger_a') or {}).get('score'))} | "
                f"{_score((r.get('stranger_b') or {}).get('score'))} | "
                f"{'da' if match is True else 'nu' if match is False else '—'} |"
            )
    calibration = meta.get("agreement")
    if calibration:
        rows += [
            "",
            "## Acordul cu Proprietarul",
            "",
            f"Texte etichetate de el și judecate: {len(calibration['texts'])}.",
            "",
            "| Întrebarea | Texte | Acord | Kappa (Cohen) |",
            "|---|---|---|---|",
        ]
        for question in QUESTIONS:
            entry = calibration["questions"][question.key]
            rows.append(
                f"| {question.ro} | {entry['n']} | "
                f"{'—' if entry['percent'] is None else f'{entry["percent"]}%'} | "
                f"{'—' if entry['kappa'] is None else entry['kappa']} |"
            )
        pooled = calibration["pooled"]
        rows.append(
            f"| Toate | {pooled['n']} | "
            f"{'—' if pooled['percent'] is None else f'{pooled["percent"]}%'} | "
            f"{'—' if pooled['kappa'] is None else pooled['kappa']} |"
        )
    elif meta.get("labels_file"):
        rows += ["", f"Proprietarul nu a etichetat încă textele (`{meta['labels_file']}`)."]
    rows += [
        "",
        "## Fiecare apel",
        "",
        "| Caz | Sarcina | Modelul | Starea | Tokeni în | Tokeni out | Secunde | Șablonul |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        for run in r.get("runs") or []:
            rows.append(
                f"| {r['id']} | {run['task_type']} | {run['model']} | {run['status']} | "
                f"{run['prompt_tokens'] or '—'} | {run['completion_tokens'] or '—'} | "
                f"{run['latency_s'] if run['latency_s'] is not None else '—'} | {run['template']} |"
            )
    failures = [
        r for r in results if r.get("error") or (r.get("checks_summary") or {}).get("failed")
    ]
    if failures:
        rows += ["", "## Ce nu a trecut", ""]
        for r in failures:
            if r.get("error"):
                rows.append(f"- **{r['id']}**: {_cell(r['error'], 400)}")
                continue
            for check in r.get("checks") or []:
                if not check["passed"] and not check["advisory"]:
                    rows.append(f"- **{r['id']}** — {check['name']}: {_cell(check['reason'], 300)}")
    fingerprints = {f"{r['kind']}": r["fingerprint"] for r in results if r.get("fingerprint")}
    if fingerprints:
        rows += ["", "## Ce au primit scriitorii", ""]
        for kind, print_ in sorted(fingerprints.items()):
            templates = sorted(
                {
                    run["template"]
                    for r in results
                    if r["kind"] == kind
                    for run in r.get("runs") or []
                    if run["task_type"] in WRITER_TASKS
                }
            )
            rows.append(
                f"- {KIND_RO[kind]}: brief `{print_['brief_sha256'][:16]}`, identitate "
                f"`{print_['identity_sha256'][:16]}`, șabloane: {', '.join(templates) or '—'}"
            )
    return "\n".join(rows) + "\n"


def git_commit() -> str | None:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() or None


# ----------------------------------------------------------------------------- the form


def calibration_items(cases: Sequence[Mapping[str, Any]], limit: int) -> list[dict[str, Any]]:
    """The texts the Owner labels: both sides of every golden pair first, then the shipped
    versions, serial and factual in turn, at most ``limit``; shown in an order of their own
    (by hash) so two versions of one story are not side by side."""
    golden: list[dict[str, Any]] = []
    shipped: dict[str, list[dict[str, Any]]] = {"serial": [], "factual": []}
    seen: set[str] = set()

    def item(text: Mapping[str, Any], case_id: str) -> dict[str, Any] | None:
        if text["text_key"] in seen:
            return None
        seen.add(text["text_key"])
        return {
            "key": text["text_key"],
            "kind": text["kind"],
            "case": case_id,
            "view": text["view"],
        }

    for case in cases:
        if case["kind"] == "golden_pair":
            for side in ("a", "b"):
                found = item(case[side], case["id"])
                if found:
                    golden.append(found)
    for case in cases:
        if case["kind"] in TEXT_KINDS and case.get("reference"):
            found = item(case["reference"], case["id"])
            if found:
                shipped[case["kind"]].append(found)
    chosen = golden[:limit]
    serial, factual = list(shipped["serial"]), list(shipped["factual"])
    while len(chosen) < limit and (serial or factual):
        for pool in (serial, factual):
            if pool and len(chosen) < limit:
                chosen.append(pool.pop(0))
    return sorted(chosen, key=lambda entry: hashlib.sha256(entry["key"].encode()).hexdigest())


_FORM_INTRO_RO = (
    "Mai jos sunt {count} filme scurte ale studioului, scrise așa cum le primește un spectator: "
    "ce se vede pe ecran și ce se aude, cu timpii aproximativi. Nu sunt note, scoruri sau "
    "versiuni. Pentru fiecare, răspunde cu «da» sau «nu» la cele cinci întrebări, ca un străin "
    "care nu știe nimic despre studio. Aceleași cinci întrebări le primește Necunoscutul "
    "(judecătorul automat), iar răspunsurile tale măsoară cât de des este de acord cu tine."
)


def form_markdown(items: Sequence[Mapping[str, Any]]) -> str:
    from app.evals.stranger import QUESTIONS, view_of  # noqa: PLC0415

    rows = [
        "# Etichetarea Proprietarului",
        "",
        _FORM_INTRO_RO.format(count=len(items)),
        "",
        "Răspunsurile se pun în `config/evals/owner_labels.json` (formularul HTML de alături le "
        "scrie singur).",
        "",
    ]
    for number, entry in enumerate(items, start=1):
        rows += [
            f"## Filmul {number} — {KIND_RO[entry['kind']]} (`{entry['key']}`)",
            "",
            "```text",
            view_of(entry["view"]).render(),
            "```",
            "",
        ]
        rows += [f"- [ ] da  [ ] nu — {question.ro}" for question in QUESTIONS]
        rows += ["- Observație: ", ""]
    return "\n".join(rows) + "\n"


def form_html(items: Sequence[Mapping[str, Any]]) -> str:
    """A form that works offline: radio buttons, and a button that writes owner_labels.json."""
    from app.evals.stranger import QUESTIONS, view_of  # noqa: PLC0415

    keys = [question.key for question in QUESTIONS]
    blocks = []
    for number, entry in enumerate(items, start=1):
        questions = "".join(
            f'<div class="q"><span>{html.escape(question.ro)}</span>'
            f'<label><input type="radio" name="{number}-{question.key}" value="da"> da</label>'
            f'<label><input type="radio" name="{number}-{question.key}" value="nu"> nu</label>'
            "</div>"
            for question in QUESTIONS
        )
        blocks.append(
            f'<section data-key="{html.escape(entry["key"])}" data-n="{number}">'
            f"<h2>Filmul {number} <small>{html.escape(KIND_RO[entry['kind']])}</small></h2>"
            f"<pre>{html.escape(view_of(entry['view']).render())}</pre>{questions}"
            f'<textarea name="{number}-note" placeholder="Observație (opțional)"></textarea>'
            "</section>"
        )
    script = (
        "const KEYS = " + json.dumps(keys) + ";\n"
        "function build() {\n"
        "  const labels = {};\n"
        "  document.querySelectorAll('section').forEach((s) => {\n"
        "    const n = s.dataset.n, entry = {};\n"
        "    KEYS.forEach((k) => {\n"
        "      const c = document.querySelector(`input[name='${n}-${k}']:checked`);\n"
        "      entry[k] = c ? c.value === 'da' : null;\n"
        "    });\n"
        "    entry.note = document.querySelector(`textarea[name='${n}-note']`).value;\n"
        "    labels[s.dataset.key] = entry;\n"
        "  });\n"
        "  const data = {version: " + str(LABELS_VERSION) + ", labeled_by: 'owner', "
        "labeled_at: new Date().toISOString(), labels};\n"
        "  const text = JSON.stringify(data, null, 1);\n"
        "  document.getElementById('out').value = text;\n"
        "  const link = document.getElementById('save');\n"
        "  link.href = 'data:application/json;charset=utf-8,' + encodeURIComponent(text);\n"
        "  link.style.display = 'inline-block';\n"
        "}\n"
    )
    style = (
        ":root{color-scheme:light dark;--bg:#fbfaf7;--fg:#1d1d1b;--muted:#6b6b66;--card:#fff;"
        "--line:#ddd8cc;--accent:#2f5d50}"
        "@media (prefers-color-scheme:dark){:root{--bg:#161614;--fg:#ecebe6;--muted:#a3a29b;"
        "--card:#20201d;--line:#3a3934;--accent:#8cc3b1}}"
        "body{background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif;"
        "max-width:860px;margin:0 auto;padding:16px}"
        "section{background:var(--card);border:1px solid var(--line);border-radius:10px;"
        "padding:12px 16px;margin:20px 0}"
        "pre{white-space:pre-wrap;font:14px/1.45 ui-monospace,monospace;color:var(--fg)}"
        ".q{display:flex;flex-wrap:wrap;gap:12px;align-items:center;padding:6px 0;"
        "border-top:1px solid var(--line)}.q span{flex:1 1 320px}"
        "textarea{width:100%;min-height:48px;margin-top:8px;background:var(--bg);color:var(--fg);"
        "border:1px solid var(--line);border-radius:6px}"
        "button,#save{background:var(--accent);color:var(--bg);border:0;border-radius:6px;"
        "padding:10px 16px;font-size:16px;text-decoration:none;cursor:pointer}"
        "small{color:var(--muted);font-weight:normal}#out{min-height:160px}"
    )
    return (
        '<!doctype html><html lang="ro"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Etichetarea Proprietarului</title><style>{style}</style></head><body>"
        "<h1>Etichetarea Proprietarului</h1>"
        f"<p>{html.escape(_FORM_INTRO_RO.format(count=len(items)))}</p>"
        + "".join(blocks)
        + '<p><button type="button" onclick="build()">Generează owner_labels.json</button> '
        '<a id="save" download="owner_labels.json" style="display:none">Salvează fișierul</a></p>'
        "<p>Pune fișierul în <code>config/evals/owner_labels.json</code>.</p>"
        '<textarea id="out" readonly></textarea>'
        f"<script>{script}</script></body></html>\n"
    )


def write_form(cases: Sequence[Mapping[str, Any]], out: Path, limit: int) -> tuple[Path, Path]:
    items = calibration_items(cases, limit)
    if not items:
        raise EvalError("Niciun text de etichetat: cazurile nu au versiuni livrate sau perechi")
    folder = out / f"calibration-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    folder.mkdir(parents=True, exist_ok=True)
    page = folder / "formular_proprietar.html"
    text = folder / "formular_proprietar.md"
    page.write_text(form_html(items), encoding="utf-8")
    text.write_text(form_markdown(items), encoding="utf-8")
    return page, text


# ----------------------------------------------------------------------------- main


def parse_args(argv: Iterable[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--discover", action="store_true", help="propose cases from the backups")
    mode.add_argument("--calibration-form", action="store_true", help="write the Owner's form")
    mode.add_argument("--dry-run", action="store_true", help="list and prepare; ask no model")
    parser.add_argument("--case-file", default=str(CASE_FILE))
    parser.add_argument("--labels", default=str(LABELS_FILE), help="the Owner's labels")
    parser.add_argument("--backups", default=str(DEFAULT_BACKUPS), help="the nightly backups")
    parser.add_argument("--vault-key", help="the vault key (default: beside the live database)")
    parser.add_argument("--studio-lock", help="the live worker lock (default: data/studio.lock)")
    parser.add_argument(
        "--work",
        default=str(Path(tempfile.gettempdir()) / "amn_writer_eval"),
        help="where the copies are made",
    )
    parser.add_argument("--out", default=str(OUT_DIR), help="where the run folder is written")
    parser.add_argument("--cases", help="only these case ids, comma-separated")
    parser.add_argument("--limit", type=int, default=0, help="at most N cases")
    parser.add_argument("--variant", default="baseline")
    parser.add_argument("--writer-model", help="pin every writer to this model")
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--target-seconds", type=int, help="a factual film's length")
    parser.add_argument("--skip-reference", action="store_true", help="do not judge references")
    parser.add_argument("--keep-copies", action="store_true", help="keep each case's copy")
    parser.add_argument("--allow-live-studio", action="store_true")
    parser.add_argument("--since", default=DEFAULT_SINCE, help="discovery: from this day")
    parser.add_argument("--force", action="store_true", help="discovery: overwrite the case file")
    parser.add_argument("--form-items", type=int, default=FORM_ITEMS)
    return parser.parse_args(list(argv) if argv is not None else None)


def _print_dry(results: Sequence[Mapping[str, Any]]) -> None:
    for r in results:
        brief = (r.get("brief") or {}).get("chars")
        print(
            f"- {r['id']}: {KIND_RO[r['kind']]}, copia {r['backup']}, "
            f"{STATE_RO.get(str(r.get('state')), r.get('state') or '—')}, "
            f"scriitor {r.get('writer_model') or '—'}, judecător {r.get('judge_model') or '—'}, "
            + (f"brief {brief} caractere, " if brief else "")
            + f"apeluri {r['planned_calls'][0]}-{r['planned_calls'][1]}"
            + (f" — {r['error']}" if r.get("error") else "")
        )


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")
    backups = Path(args.backups)
    work = Path(args.work)
    out = Path(args.out)
    case_file = Path(args.case_file)
    try:
        if args.discover:
            proposal = discover(backups, work, args.since, args.keep_copies)
            written = write_case_file(case_file, proposal, args.force)
            kinds = [case["kind"] for case in proposal["cases"]]
            print(f"Cazuri propuse: {len(kinds)} în {written}")
            for kind in CASE_KINDS:
                print(f"- {KIND_RO[kind]}: {kinds.count(kind)}")
            print("Copii citite: " + ", ".join(proposal["backups_scanned"]))
            return 0
        cases = load_cases(case_file)
        if args.calibration_form:
            page, text = write_form(cases, out, args.form_items)
            print(f"Formularul: {page}\nȘi ca text: {text}")
            return 0
        chosen = select_cases(cases, args.cases, args.limit)
        if args.writer_model and forbidden_writer(args.writer_model):
            raise EvalError(
                f"{args.writer_model} nu scrie: Proprietarul, 2026-10-15, l-a interzis scriitorilor"
            )
        from app.evals.variants import variant as variant_named  # noqa: PLC0415

        chosen_variant = variant_named(args.variant)
    except EvalError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    lock = Path(args.studio_lock) if args.studio_lock else backups.parent / "studio.lock"
    alive = live_studio(lock)
    if alive and not args.dry_run and not args.allow_live_studio:
        print(
            "Studioul viu rulează (" + "; ".join(alive) + "): evaluarea împarte limitele "
            "abonamentului cu bucla Directoarei. Oprește-l sau dă --allow-live-studio.",
            file=sys.stderr,
        )
        return 3
    if alive:
        print("Atenție, studioul viu rulează: " + "; ".join(alive), file=sys.stderr)
    settings = RunSettings(args, chosen_variant)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_name = f"{stamp}-{args.variant}" + ("-proba" if args.dry_run else "")
    run_dir = out / run_name
    work_dir = work / run_name
    labels_file = Path(args.labels)
    print(
        f"{len(chosen)} cazuri, varianta {args.variant}, judecătorul {args.judge_model}"
        + (", probă" if args.dry_run else ""),
        flush=True,
    )
    results = []
    try:
        for case in chosen:
            print(f"Cazul {case['id']} …", flush=True)
            results.append(run_case(case, settings, work_dir))
    except MediaAdapterFound as exc:
        print(str(exc), file=sys.stderr)
        return 4
    summary = totals(results)
    meta: dict[str, Any] = {
        "made_at": datetime.now(UTC).isoformat(),
        "commit": git_commit(),
        "variant": args.variant,
        "variant_description": chosen_variant.description,
        "writer_model": args.writer_model,
        "judge_model": args.judge_model,
        "case_file": str(case_file),
        "case_file_sha256": _sha256_file(case_file),
        "dry_run": bool(args.dry_run),
        "skip_reference": bool(args.skip_reference),
        "labels_file": str(labels_file),
        "live_studio": alive,
    }
    try:
        labels = load_labels(labels_file)
    except (EvalError, json.JSONDecodeError) as exc:
        print(f"Etichetele Proprietarului nu pot fi citite: {exc}", file=sys.stderr)
        labels = {}
    if labels and not args.dry_run:
        from app.evals.stranger import agreement  # noqa: PLC0415

        meta["agreement"] = agreement(judged_texts(results), labels)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "results.json").write_text(
        json.dumps(
            {"meta": meta, "totals": summary, "results": results},
            ensure_ascii=False,
            indent=1,
            default=str,
        ),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text(report_markdown(results, summary, meta), encoding="utf-8")
    if args.dry_run:
        _print_dry(results)
    print(f"Rezultatele: {run_dir / 'results.json'}\nRaportul: {run_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
