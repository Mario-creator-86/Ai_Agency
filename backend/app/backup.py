"""Backups of the studio's database, the copy before a migration, the restore and its guard.

Measured 2026-10-01 (REL-04, AR-08, SELL-20): no backup code existed outside
scripts/reset_history.py; data/backups held one file, from 2026-09-12; `scripts/bootstrap.py`
migrated the database in place on every start (start.py runs it each time, the scheduled
service included); and a buyer had no supported way to back up or restore anything. Document
25 asks for a backup, a restore test, a copy before a destructive migration, and a restore
guard: external writes stay off until the Owner confirms.

What one backup is, in the backup folder (``STUDIO_BACKUP_DIR``, else ``backups`` beside the
database — data/backups for the studio):

- ``studio-<UTC>.db``: SQLite's own online backup of the live database (WAL included; the
  studio keeps running), checked with ``PRAGMA integrity_check`` before it is kept;
- ``studio-<UTC>.json``: its manifest — sha256, size, integrity, the migration revision, where
  it came from, and the key copy;
- ``key/studio-<UTC>.credentials.key``: the wrapped credentials key, copied as it is. On
  Windows it is wrapped with DPAPI for the account that made it: it opens only for that
  Windows user on that machine, so a copy restored elsewhere means re-entering the keys;
- ``studio-<UTC>.media.json``: the list of media files (path, size, time), not their bytes —
  the films are hundreds of gigabytes and are the Owner's to copy to another disk.

Kept: the newest backup of each of the last 14 days and of the 4 weeks before them
(``STUDIO_BACKUP_KEEP_DAILY`` / ``_WEEKLY``), and the newest five made before a migration and
before a restore, which are kept apart.

The restore refuses while the studio answers on its port, keeps a copy of the database it
replaces, copies the backup in through the same online API, and then applies the restore
guard (`app.services.apply_restore_guard`): the autonomy stop on, the environment TEST and the
daily run's clock off, so nothing is bought or published from a restored past until the
Owner has looked at it and turned them on himself.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import socket
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, delete, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.config import ROOT

logger = logging.getLogger("studio.backup")

#: The name every backup copy carries: ``studio-20261002T033000Z[-2][-premigrare].db``. The
#: stamp is UTC; the counter separates two copies made in the same second; the tag says a copy
#: was made before a migration or a restore (and is kept apart from the daily ones).
BACKUP_NAME = re.compile(
    r"^studio-(?P<stamp>\d{8}T\d{6}Z)(?:-(?P<n>\d+))?(?:-(?P<tag>premigrare|prerestaurare))?\.db$"
)
#: The tags kept apart, and how many of each.
SPECIAL_TAGS = ("premigrare", "prerestaurare")
KEEP_SPECIAL = 5
#: The daily job, as a worker task type and a scheduled job name.
BACKUP_TASK = "BACKUP"
BACKUP_JOB_NAME = "backup_daily"
#: Events and the Owner's letter.
BACKUP_MADE_EVENT = "operations.backup_made"
BACKUP_FAILED_EVENT = "operations.backup_failed"
BACKUP_FAILED_LETTER = "backup_failed"
ROWS_PRUNED_EVENT = "operations.rows_pruned"
#: Completed tasks that are housekeeping, pruned after `prune_task_days`. A day, a film's
#: continuation and the Director's work are the studio's history and are never pruned.
HOUSEKEEPING_TASKS = ("WATCHDOG", BACKUP_TASK, "MODEL_REVIEW", "TRENDS_REFRESH")
KEY_NOTE_RO = (
    "Cheia credențialelor este încuiată cu DPAPI pentru contul Windows care a făcut copia: se "
    "deschide doar pentru acel utilizator, pe acel calculator. Restaurată în alt cont sau pe "
    "alt calculator, conexiunile se reintroduc în Setări."
)


class BackupError(RuntimeError):
    """A backup could not be made or did not check out. ``reason_ro`` is the Owner's."""

    def __init__(self, reason_ro: str) -> None:
        super().__init__(reason_ro)
        self.reason_ro = reason_ro


class RestoreRefused(RuntimeError):
    """A restore that must not run (the studio answers on its port, a copy that does not
    check out). Nothing was changed."""

    def __init__(self, reason_ro: str) -> None:
        super().__init__(reason_ro)
        self.reason_ro = reason_ro


# --------------------------------------------------------------------------- where


def database_file(source: Engine | str | Path) -> Path:
    """The database file behind an engine, a URL or a path."""
    if isinstance(source, Path):
        return source
    url = source.url if isinstance(source, Engine) else make_url(str(source))
    path = Path(str(url.database))
    return path if path.is_absolute() else ROOT / path


def backup_folder(settings: Any, database: Path | None = None) -> Path:
    """The Owner's STUDIO_BACKUP_DIR, else ``backups`` beside the database file."""
    configured = getattr(settings, "backup_dir", None)
    if configured:
        return Path(configured)
    database = database or database_file(str(settings.database_url))
    return database.parent / "backups"


def key_file(database: Path) -> Path:
    """The wrapped credentials key beside the database (as `CredentialVault` names it)."""
    return database.with_suffix(".credentials.key")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _revision(connection: sqlite3.Connection) -> str | None:
    try:
        row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.Error:
        return None
    return str(row[0]) if row else None


def database_revision_of(database: Path) -> str | None:
    """The migration revision a database file is at, read-only; None when it has none."""
    if not database.is_file() or database.stat().st_size == 0:
        return None
    uri = f"file:{database.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        return _revision(connection)


def _online_copy(source: Path, target: Path) -> None:
    """SQLite's online backup of ``source`` into ``target``: a consistent copy of a database
    other connections are reading and writing (the rows still in its WAL included)."""
    src = sqlite3.connect(str(source), timeout=30)
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _integrity(path: Path) -> str:
    with closing(sqlite3.connect(str(path))) as connection:
        row = connection.execute("PRAGMA integrity_check").fetchone()
    return str(row[0]) if row else "no answer"


def _media_listing(media_root: Path) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    total = 0
    if media_root.is_dir():
        for path in media_root.rglob("*"):
            try:
                if not path.is_file() or path.is_symlink():
                    continue
                info = path.stat()
            except OSError:
                continue
            files.append(
                {
                    "path": path.relative_to(media_root).as_posix(),
                    "bytes": info.st_size,
                    "modified": datetime.fromtimestamp(info.st_mtime, UTC).isoformat(),
                }
            )
            total += info.st_size
    return {"root": str(media_root), "files": len(files), "bytes": total, "listing": files}


# --------------------------------------------------------------------------- make


def _name(folder: Path, moment: datetime, tag: str | None) -> str:
    stamp = moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = f"-{tag}" if tag else ""
    name = f"studio-{stamp}{suffix}.db"
    n = 2
    while (folder / name).exists():
        name = f"studio-{stamp}-{n}{suffix}.db"
        n += 1
    return name


def make_backup(
    database: Path,
    folder: Path,
    *,
    tag: str | None = None,
    now: datetime | None = None,
    media_root: Path | None = None,
    keep_daily: int = 14,
    keep_weekly: int = 4,
) -> dict[str, Any]:
    """One backup of ``database`` into ``folder``: the copy, its check, its manifest, the key.

    Raises BackupError (Romanian) when the copy cannot be made or does not pass
    ``integrity_check``; nothing half-made is left behind. Retention runs after a good copy.
    Returns the manifest, with ``path`` and ``manifest_path``.
    """
    if tag is not None and tag not in SPECIAL_TAGS:
        raise ValueError(f"unknown backup tag: {tag}")
    if not database.is_file():
        raise BackupError(f"Baza de date nu există: {database}.")
    moment = now or datetime.now(UTC)
    folder.mkdir(parents=True, exist_ok=True)
    name = _name(folder, moment, tag)
    target = folder / name
    partial = folder / f".{name}.partial"
    try:
        _online_copy(database, partial)
        integrity = _integrity(partial)
        if integrity != "ok":
            raise BackupError(f"Copia nu a trecut verificarea SQLite ({integrity[:200]}).")
        os.replace(partial, target)
    except sqlite3.Error as exc:
        partial.unlink(missing_ok=True)
        raise BackupError(f"Copia bazei de date nu a putut fi făcută ({exc}).") from exc
    except OSError as exc:
        partial.unlink(missing_ok=True)
        raise BackupError(f"Copia bazei de date nu a putut fi scrisă ({exc.strerror}).") from exc
    except BackupError:
        partial.unlink(missing_ok=True)
        raise
    stem = target.stem
    with closing(sqlite3.connect(str(target))) as connection:
        revision = _revision(connection)
    manifest: dict[str, Any] = {
        "file": name,
        "created_at": moment.astimezone(UTC).isoformat(),
        "tag": tag,
        "source": str(database),
        "sha256": _sha256(target),
        "bytes": target.stat().st_size,
        "integrity": "ok",
        "revision": revision,
        "key": None,
        "media": None,
    }
    key = key_file(database)
    if key.is_file():
        keys = folder / "key"
        keys.mkdir(exist_ok=True)
        kept = keys / f"{stem}.credentials.key"
        shutil.copyfile(key, kept)
        manifest["key"] = {
            "file": f"key/{kept.name}",
            "sha256": _sha256(kept),
            "user_bound": True,
            "note_ro": KEY_NOTE_RO,
        }
    if media_root is not None:
        listing = _media_listing(Path(media_root))
        listed = folder / f"{stem}.media.json"
        listed.write_text(json.dumps(listing, ensure_ascii=False), encoding="utf-8")
        manifest["media"] = {
            "file": listed.name,
            "root": listing["root"],
            "files": listing["files"],
            "bytes": listing["bytes"],
        }
    manifest_path = folder / f"{stem}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        apply_retention(folder, keep_daily=keep_daily, keep_weekly=keep_weekly, now=moment)
    except OSError:
        logger.warning("backup_retention_failed", extra={"folder": str(folder)})
    result = {**manifest, "path": str(target), "manifest_path": str(manifest_path)}
    if manifest["key"]:
        result["key"] = {**manifest["key"], "path": str(folder / manifest["key"]["file"])}
    return result


def verify_backup(copy: Path) -> dict[str, Any]:
    """Whether a backup copy is the file its manifest describes and SQLite finds it whole."""
    manifest_path = copy.with_suffix(".json")
    if not copy.is_file():
        return {"ok": False, "reason_ro": f"Copia nu există: {copy}."}
    if not manifest_path.is_file():
        return {"ok": False, "reason_ro": f"Copia {copy.name} nu are manifest."}
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"ok": False, "reason_ro": f"Manifestul copiei {copy.name} nu se poate citi."}
    digest = _sha256(copy)
    if digest != manifest.get("sha256"):
        return {
            "ok": False,
            "reason_ro": f"Copia {copy.name} nu mai are sha256-ul din manifest: a fost "
            "schimbată după ce a fost făcută.",
            "manifest": manifest,
        }
    try:
        integrity = _integrity(copy)
    except sqlite3.Error as exc:
        integrity = str(exc)
    if integrity != "ok":
        return {
            "ok": False,
            "reason_ro": f"Copia {copy.name} nu trece verificarea SQLite ({integrity[:200]}).",
            "manifest": manifest,
        }
    return {"ok": True, "reason_ro": "", "manifest": manifest}


# --------------------------------------------------------------------------- keep


def _parsed(path: Path) -> tuple[datetime, str | None] | None:
    match = BACKUP_NAME.match(path.name)
    if match is None:
        return None
    moment = datetime.strptime(match["stamp"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
    return moment, match["tag"]


def list_backups(folder: Path) -> list[dict[str, Any]]:
    """Every backup copy in ``folder``, newest first: path, created_at, tag."""
    found: list[dict[str, Any]] = []
    if not folder.is_dir():
        return found
    for path in folder.glob("studio-*.db"):
        parsed = _parsed(path)
        if parsed is not None:
            found.append({"path": path, "created_at": parsed[0], "tag": parsed[1]})
    found.sort(key=lambda item: (item["created_at"], item["path"].name), reverse=True)
    return found


def _remove(copy: Path) -> None:
    stem = copy.stem
    for path in (
        copy,
        copy.with_suffix(".json"),
        copy.parent / f"{stem}.media.json",
        copy.parent / "key" / f"{stem}.credentials.key",
    ):
        path.unlink(missing_ok=True)


def apply_retention(
    folder: Path, *, keep_daily: int = 14, keep_weekly: int = 4, now: datetime | None = None
) -> list[str]:
    """Delete the copies the rule does not keep; the names deleted.

    Daily copies: the newest of each of the ``keep_daily`` most recent days that have one,
    then the newest of each of the ``keep_weekly`` most recent ISO weeks before those days.
    Copies made before a migration or a restore: the newest `KEEP_SPECIAL` of each tag.
    Only copies with a manifest (made here) are counted or deleted: a copy someone else put in
    the folder (the one scripts/reset_history.py made on 2026-09-12) is never touched.
    ``now`` is accepted for symmetry; a copy is never judged by the clock, only by the others.
    """
    del now
    copies = [item for item in list_backups(folder) if item["path"].with_suffix(".json").is_file()]
    keep: set[Path] = set()
    daily = [item for item in copies if item["tag"] is None]
    days: list[Any] = []
    for item in daily:
        day = item["created_at"].date()
        if day not in days and len(days) < keep_daily:
            days.append(day)
            keep.add(item["path"])
    oldest_day = min(days) if days else None
    weeks: list[tuple[int, int]] = []
    for item in daily:
        day = item["created_at"].date()
        if oldest_day is not None and day >= oldest_day:
            continue
        week = tuple(item["created_at"].isocalendar()[:2])
        if week not in weeks and len(weeks) < keep_weekly:
            weeks.append(week)  # type: ignore[arg-type]
            keep.add(item["path"])
    for tag in SPECIAL_TAGS:
        for item in [c for c in copies if c["tag"] == tag][:KEEP_SPECIAL]:
            keep.add(item["path"])
    deleted: list[str] = []
    for item in copies:
        if item["path"] not in keep:
            _remove(item["path"])
            deleted.append(item["path"].name)
    return deleted


# ------------------------------------------------------------- before a migration


def backup_before_migration(
    database: Path, folder: Path, head: str, *, now: datetime | None = None
) -> dict[str, Any] | None:
    """A copy of a studio's database before it is migrated to ``head``; None when there is
    nothing to protect (no file, no schema yet, or already at the head)."""
    revision = database_revision_of(database)
    if revision is None or revision == head:
        return None
    return make_backup(database, folder, tag="premigrare", now=now)


# ---------------------------------------------------------------- status and pruning


def backup_status(
    settings: Any,
    *,
    database: Path | None = None,
    studio_created_at: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The newest backup and its age. ``status``: OK, STALE (older than
    ``backup_max_age_hours``), MISSING (none, and the studio is older than that), NONE_YET
    (none, and the studio is younger)."""
    moment = now or datetime.now(UTC)
    max_age = float(getattr(settings, "backup_max_age_hours", 36) or 36)
    folder = backup_folder(settings, database)
    copies = [item for item in list_backups(folder) if item["tag"] is None]
    if not copies:
        created = None
        if studio_created_at:
            try:
                created = datetime.fromisoformat(studio_created_at)
            except ValueError:
                created = None
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
        old = created is not None and (moment - created).total_seconds() > max_age * 3600
        return {
            "status": "MISSING" if old else "NONE_YET",
            "last_at": None,
            "age_hours": None,
            "max_age_hours": max_age,
            "reason_ro": (
                f"Nu există nicio copie de siguranță a bazei de date, iar studioul are mai mult "
                f"de {max_age:.0f} de ore."
                if old
                else ""
            ),
        }
    newest = copies[0]["created_at"]
    age = (moment - newest).total_seconds() / 3600
    stale = age > max_age
    return {
        "status": "STALE" if stale else "OK",
        "last_at": newest.isoformat(),
        "age_hours": round(age, 1),
        "max_age_hours": max_age,
        "reason_ro": (
            f"Ultima copie de siguranță a bazei de date are {age:.0f} de ore (limita: "
            f"{max_age:.0f})."
            if stale
            else ""
        ),
    }


def prune_operational_rows(
    engine: Engine,
    *,
    now: datetime | None = None,
    task_days: int = 30,
    outbox_days: int = 7,
) -> dict[str, int]:
    """Delete completed housekeeping tasks older than ``task_days`` and outbox rows already
    sent older than ``outbox_days`` (REL-15). Events are the record and are never deleted."""
    from app.db import lock_for_write  # noqa: PLC0415
    from app.workflows.models import OutboxRecord, TaskQueueItem  # noqa: PLC0415

    moment = now or datetime.now(UTC)
    task_cutoff = (moment - timedelta(days=task_days)).isoformat()
    outbox_cutoff = (moment - timedelta(days=outbox_days)).isoformat()
    with Session(engine) as session, session.begin():
        lock_for_write(session)
        tasks = session.execute(
            delete(TaskQueueItem).where(
                TaskQueueItem.status == "COMPLETED",
                TaskQueueItem.task_type.in_(HOUSEKEEPING_TASKS),
                TaskQueueItem.updated_at < task_cutoff,
            )
        )
        outbox = session.execute(
            delete(OutboxRecord).where(
                OutboxRecord.status == "PUBLISHED",
                OutboxRecord.published_at.is_not(None),
                OutboxRecord.published_at < outbox_cutoff,
            )
        )
    return {
        "tasks": int(getattr(tasks, "rowcount", 0) or 0),
        "outbox": int(getattr(outbox, "rowcount", 0) or 0),
    }


def _tell_backup_failed(engine: Engine, reason_ro: str, day: str, correlation_id: str) -> None:
    """One letter per day a backup fails (the same subject, still open, is that letter)."""
    from app.agents.memory import agent_for_role  # noqa: PLC0415 - agents import a lot
    from app.agents.messages import post_message  # noqa: PLC0415

    subject = f"Copia de siguranță a bazei de date nu s-a făcut ({day})"
    with Session(engine) as session, session.begin():
        director = agent_for_role(session, "Director")
        post_message(
            session,
            intent="ESCALATE",
            subject=subject,
            body={"kind": BACKUP_FAILED_LETTER, "day": day, "reason": reason_ro[:300]},
            body_text=(
                f"{subject}: {reason_ro[:300]} Fără copie, o bază de date stricată nu se poate "
                "aduce înapoi. Rulează scripts/backup.py de mână și verifică discul copiilor; "
                "studioul încearcă din nou la ora copiei de mâine."
            ),
            from_agent_id=director.id if director else None,
            to_owner=True,
            correlation_id=correlation_id,
        )


def run_backup_job(
    engine: Engine,
    settings: Any,
    *,
    correlation_id: str = "",
    now: datetime | None = None,
    make: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The daily backup: the copy, then (only after a good copy) the pruning. Never a network
    call, never a cost. A failure is an event and one letter a day; it returns FAILED."""
    from app.services import append_event  # noqa: PLC0415 - services imports the world

    correlation = correlation_id or str(uuid4())
    moment = now or datetime.now(UTC)
    database = database_file(engine)
    folder = backup_folder(settings, database)
    try:
        from app.media.disk import media_root  # noqa: PLC0415

        made = (make or make_backup)(
            database,
            folder,
            now=moment,
            media_root=media_root(settings),
            keep_daily=int(getattr(settings, "backup_keep_daily", 14)),
            keep_weekly=int(getattr(settings, "backup_keep_weekly", 4)),
        )
    except BackupError as exc:
        reason = exc.reason_ro
    except Exception as exc:  # noqa: BLE001 - the Owner hears of any failure
        reason = f"{type(exc).__name__}: {exc}"[:300]
    else:
        pruned = prune_operational_rows(
            engine,
            now=moment,
            task_days=int(getattr(settings, "prune_task_days", 30)),
            outbox_days=int(getattr(settings, "prune_outbox_days", 7)),
        )
        with Session(engine) as session, session.begin():
            append_event(
                session,
                BACKUP_MADE_EVENT,
                "backup",
                str(made["file"]),
                1,
                {
                    "file": made["file"],
                    "sha256": made["sha256"],
                    "bytes": made["bytes"],
                    "revision": made["revision"],
                    "key_copied": bool(made.get("key")),
                    "pruned": pruned,
                },
                correlation,
            )
        logger.info("backup_made", extra={"file": made["file"], "pruned": pruned})
        return {"status": "COMPLETED", "backup": made, "pruned": pruned, "reason_ro": ""}
    with Session(engine) as session, session.begin():
        append_event(
            session,
            BACKUP_FAILED_EVENT,
            "backup",
            str(folder.name),
            1,
            {"reason": reason[:300], "folder": str(folder)},
            correlation,
        )
    try:
        _tell_backup_failed(engine, reason, moment.date().isoformat(), correlation)
    except Exception:  # noqa: BLE001 - the event above is the record
        logger.warning("backup_failed_letter_not_written")
    logger.error("backup_failed", extra={"reason": reason[:300]})
    return {"status": "FAILED", "backup": None, "pruned": None, "reason_ro": reason}


# ------------------------------------------------------------------------- restore


def studio_answers(host: str, port: int, timeout: float = 1.0) -> bool:
    """Whether something accepts a connection on the studio's address."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def restore_backup(
    copy: Path,
    database: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    restore_key: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Put ``copy`` back as ``database``, then apply the restore guard.

    Refused (RestoreRefused, nothing changed) while the studio answers on ``host:port``, or
    when the copy does not match its manifest or is not whole. The database it replaces is
    kept first (tag ``prerestaurare``). ``restore_key`` also puts back the credentials key
    copied with it (only useful on the same Windows account). Returns the outcome, the guard
    and the connections whose keys must be typed again.
    """
    if studio_answers(host, port):
        raise RestoreRefused(
            f"Studioul rulează încă (răspunde pe {host}:{port}): oprește-l înainte de "
            "restaurare. Nu s-a schimbat nimic."
        )
    verdict = verify_backup(copy)
    if not verdict["ok"]:
        raise RestoreRefused(str(verdict["reason_ro"]) + " Nu s-a schimbat nimic.")
    manifest = verdict["manifest"]
    folder = copy.parent
    previous = None
    if database.is_file() and database.stat().st_size > 0:
        try:
            previous = make_backup(database, folder, tag="prerestaurare", now=now)
        except BackupError as exc:
            raise RestoreRefused(
                f"Baza de date de acum nu a putut fi păstrată înainte de restaurare: "
                f"{exc.reason_ro} Nu s-a schimbat nimic."
            ) from exc
    database.parent.mkdir(parents=True, exist_ok=True)
    _online_copy(copy, database)
    key_restored = False
    if restore_key and manifest.get("key"):
        kept = folder / str(manifest["key"]["file"])
        if kept.is_file():
            shutil.copyfile(kept, key_file(database))
            key_restored = True

    from app.db import create_db_engine  # noqa: PLC0415
    from app.services import apply_restore_guard  # noqa: PLC0415

    engine = create_db_engine(f"sqlite:///{database.as_posix()}")
    try:
        guard = apply_restore_guard(
            engine, restored_from=str(manifest.get("file")), correlation_id=str(uuid4())
        )
        credentials = credentials_to_reenter(engine, key_file(database))
    finally:
        engine.dispose()
    return {
        "status": "RESTORED",
        "restored_from": manifest,
        "previous": previous,
        "key_restored": key_restored,
        "guard": guard,
        "credentials": credentials,
    }


def credentials_to_reenter(engine: Engine, key: Path) -> list[dict[str, Any]]:
    """The saved connections whose keys this studio cannot read now: what the Owner types
    again in Settings after a restore (none when the key opens them all)."""
    from app.integrations.services import vault_health  # noqa: PLC0415
    from app.integrations.vault import CredentialVault  # noqa: PLC0415
    from app.wording import settings_place  # noqa: PLC0415
    from app.youtube.models import YouTubeConnection  # noqa: PLC0415

    health = vault_health(engine, CredentialVault(key))
    found = [
        {
            "kind": item["kind"],
            "name": item["name"],
            "where": settings_place(str(item.get("tab") or "llm")),
            "code": item["code"],
        }
        for item in health["unreadable"]
    ]
    if health["code"] is not None:
        with Session(engine) as session:
            for row in session.scalars(select(YouTubeConnection)):
                found.append(
                    {
                        "kind": "youtube",
                        "name": str(row.remote_channel_title or row.id),
                        "where": settings_place("social"),
                        "code": health["code"],
                    }
                )
    return found
