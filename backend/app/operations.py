"""What keeps the studio running, read for /health/ready and the page's banner (REL-07, AR-18).

Until 2026-10-02 /health/ready ran ``SELECT version FROM owner_policy`` and nothing else. A
worker whose passes had stopped, a media disk with nothing left, an FFmpeg that was
uninstalled and a backup that had not run for a week all answered 200 HEALTHY, and the page had
no way to say «the worker has not worked for 14 minutes». Document 25 asks for alerts on a
worker down, a scheduler down, a disk low and a backup failed.

The running process keeps `new_operations()` on ``app.state.operations``; the worker loop
records each pass (`record_pass_start`, `record_pass_end`, `record_pass_failure`). The reading
(`operations_reading`) adds what the database and the machine say: a task whose lease is live
(a day can run for hours inside one pass, renewing its lease), the media disk, FFmpeg and
FFprobe, and the newest backup. Three failed passes in a row are one event and one letter.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.backup import backup_status, database_file
from app.media.disk import disk_reading
from app.media.toolchain import find_ffmpeg, find_ffprobe

logger = logging.getLogger("studio.operations")

#: A worker whose last pass is older than this many intervals, with no task holding a live
#: lease, is not working.
STALE_PASSES = 3
#: Failed passes in a row that make one event and one letter.
FAILING_PASSES = 3
WORKER_FAILING_EVENT = "operations.worker_failing"
WORKER_FAILING_LETTER = "worker_failing"


def _now() -> datetime:
    return datetime.now(UTC)


def _parse(stamp: Any) -> datetime | None:
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def new_operations() -> dict[str, Any]:
    """The running process's own record of its worker, kept on ``app.state.operations``."""
    return {
        "started_at": _now().isoformat(),
        "last_pass_at": None,
        "pass_started_at": None,
        "in_pass": False,
        "current_task": None,
        "last_error_class": None,
        "consecutive_failures": 0,
    }


def record_pass_start(ops: dict[str, Any]) -> None:
    ops["pass_started_at"] = _now().isoformat()
    ops["in_pass"] = True


def record_pass_end(ops: dict[str, Any]) -> None:
    """A pass that finished: the streak of failures ends."""
    ops["last_pass_at"] = _now().isoformat()
    ops["in_pass"] = False
    ops["current_task"] = None
    ops["consecutive_failures"] = 0
    ops["last_error_class"] = None


def record_pass_failure(engine: Engine, ops: dict[str, Any], exc: BaseException) -> None:
    """A pass that raised. At exactly `FAILING_PASSES` in a row, one event and one letter to
    the Owner; the streak's later failures are counted, not told again."""
    ops["in_pass"] = False
    ops["current_task"] = None
    ops["consecutive_failures"] = int(ops.get("consecutive_failures") or 0) + 1
    ops["last_error_class"] = type(exc).__name__
    if ops["consecutive_failures"] != FAILING_PASSES:
        return
    try:
        _tell_worker_failing(engine, ops)
    except Exception:  # noqa: BLE001 - the database may be the very thing that is failing
        logger.error("worker_failing_not_recorded", extra={"error": type(exc).__name__})


def _tell_worker_failing(engine: Engine, ops: dict[str, Any]) -> None:
    from app.agents.memory import agent_for_role  # noqa: PLC0415 - agents import a lot
    from app.agents.messages import post_message  # noqa: PLC0415
    from app.services import append_event  # noqa: PLC0415

    count = int(ops["consecutive_failures"])
    error = str(ops.get("last_error_class") or "necunoscută")
    subject = f"Lucrătorul studioului a eșuat {count} treceri la rând"
    with Session(engine) as session, session.begin():
        append_event(
            session,
            WORKER_FAILING_EVENT,
            "worker",
            "worker_main",
            1,
            {"consecutive_failures": count, "error_class": error},
            f"worker-failing-{ops.get('started_at')}",
        )
        director = agent_for_role(session, "Director")
        post_message(
            session,
            intent="ESCALATE",
            subject=subject,
            body={"kind": WORKER_FAILING_LETTER, "error_class": error, "passes": count},
            body_text=(
                f"{subject} (eroarea: {error}). Cât timp eșuează, nu pornește nicio sarcină "
                "programată: nici ziua, nici paznicul, nici copia de siguranță. Cauza este în "
                "jurnalul studioului (data/logs/studio.log); o trecere reușită oprește alerta."
            ),
            from_agent_id=director.id if director else None,
            to_owner=True,
            correlation_id=f"worker-failing-{ops.get('started_at')}",
        )


# ------------------------------------------------------------------------- the reading


def _minutes(seconds: float) -> str:
    minutes = max(1, int(seconds // 60))
    if minutes == 1:
        return "1 minut"
    return f"{minutes} minute" if minutes % 100 < 20 else f"{minutes} de minute"


def _live_task(engine: Engine, moment: datetime) -> dict[str, Any] | None:
    """A task a worker is running now: CLAIMED or RUNNING with a lease that has not lapsed
    (the worker renews it every half lease while the handler runs)."""
    from app.workflows.models import TaskQueueItem  # noqa: PLC0415 - workflows import a lot

    with Session(engine) as session:
        row = session.scalars(
            select(TaskQueueItem)
            .where(
                TaskQueueItem.status.in_(["CLAIMED", "RUNNING"]),
                TaskQueueItem.lease_expires_at > moment.isoformat(),
            )
            .order_by(TaskQueueItem.updated_at.desc())
        ).first()
        if row is None:
            return None
        return {"id": row.id, "task_type": row.task_type, "since": row.updated_at}


def worker_reading(
    engine: Engine, ops: dict[str, Any] | None, settings: Any, running: bool, moment: datetime
) -> dict[str, Any]:
    """``status``: OFF (this process runs no worker: the settings turn it off), ELSEWHERE
    (enabled, but another process on the database holds the worker), STARTING, OK, BUSY (a
    pass is long because a task is running with a live lease), STALE (no pass for
    `STALE_PASSES` intervals and no live lease)."""
    ops = ops or {}
    base = {
        "last_pass_at": ops.get("last_pass_at"),
        "current_task": ops.get("current_task"),
        "consecutive_failures": int(ops.get("consecutive_failures") or 0),
        "last_error_class": ops.get("last_error_class"),
        "reason_ro": "",
    }
    if not running:
        enabled = bool(getattr(settings, "worker_enabled", False))
        return {**base, "status": "ELSEWHERE" if enabled else "OFF"}
    interval = float(getattr(settings, "worker_interval_seconds", 30) or 30)
    limit = STALE_PASSES * interval
    last = _parse(ops.get("last_pass_at"))
    started = _parse(ops.get("pass_started_at")) or _parse(ops.get("started_at"))
    reference = last if not ops.get("in_pass") else started
    if reference is None:
        reference = _parse(ops.get("started_at"))
    if reference is None or (moment - reference).total_seconds() <= limit:
        return {**base, "status": "OK" if last else "STARTING"}
    live = _live_task(engine, moment)
    if live is not None:
        return {**base, "status": "BUSY", "current_task": ops.get("current_task") or live}
    idle = (moment - (last or reference)).total_seconds()
    return {
        **base,
        "status": "STALE",
        "reason_ro": (
            f"Lucrătorul nu a mai lucrat de {_minutes(idle)}: nicio trecere terminată și nicio "
            "sarcină în lucru. Ziua, paznicul și copia de siguranță nu pornesc."
        ),
    }


def toolchain_reading(settings: Any) -> dict[str, Any]:
    ffmpeg = find_ffmpeg(getattr(settings, "ffmpeg_path", None))
    ffprobe = find_ffprobe(
        getattr(settings, "ffmpeg_path", None), configured=getattr(settings, "ffprobe_path", None)
    )
    missing = [name for name, found in (("ffmpeg", ffmpeg), ("ffprobe", ffprobe)) if not found]
    reason = ""
    if missing:
        words = " și ".join({"ffmpeg": "FFmpeg", "ffprobe": "FFprobe"}[name] for name in missing)
        verb = "lipsește" if len(missing) == 1 else "lipsesc"
        reason = (
            f"{words} {verb} de pe calculatorul studioului: filmele nu se pot randa sau măsura."
        )
    return {
        "status": "MISSING" if missing else "OK",
        "ffmpeg": bool(ffmpeg),
        "ffprobe": bool(ffprobe),
        "missing": missing,
        "reason_ro": reason,
    }


def _studio_created_at(engine: Engine) -> str | None:
    from app.models import Studio  # noqa: PLC0415

    with Session(engine) as session:
        studio = session.get(Studio, 1)
        return studio.created_at if studio else None


def operations_reading(
    engine: Engine,
    settings: Any,
    ops: dict[str, Any] | None,
    *,
    worker_running: bool,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Everything that keeps the studio running, with the problems in the Owner's words.

    ``problems`` is a list of {code, reason_ro}; ``status`` DEGRADED when there is one;
    ``banner_ro`` the first problem's words, for the page.
    """
    moment = now or _now()
    problems: list[dict[str, str]] = []
    worker = worker_reading(engine, ops, settings, worker_running, moment)
    if worker["status"] == "STALE":
        problems.append({"code": "WORKER_STALE", "reason_ro": worker["reason_ro"]})
    disk = disk_reading(None, settings)
    if disk["status"] == "LOW":
        problems.append({"code": "DISK_LOW", "reason_ro": str(disk["reason_ro"])})
    toolchain = toolchain_reading(settings)
    for name in toolchain["missing"]:
        problems.append({"code": f"{name.upper()}_MISSING", "reason_ro": toolchain["reason_ro"]})
    backups = backup_status(
        settings,
        database=database_file(engine),
        studio_created_at=_studio_created_at(engine),
        now=moment,
    )
    if backups["status"] in ("STALE", "MISSING"):
        problems.append({"code": f"BACKUP_{backups['status']}", "reason_ro": backups["reason_ro"]})
    return {
        "status": "DEGRADED" if problems else "HEALTHY",
        "checked_at": moment.isoformat(),
        "problems": problems,
        "banner_ro": problems[0]["reason_ro"] if problems else "",
        "worker": worker,
        "disk": disk,
        "toolchain": toolchain,
        "backup": backups,
    }


def public_health(reading: dict[str, Any]) -> dict[str, Any]:
    """The same reading for the unauthenticated probe: statuses and codes, no paths and no
    sentences about the studio."""
    toolchain = reading["toolchain"]
    return {
        "worker": reading["worker"]["status"],
        "disk": reading["disk"]["status"],
        "toolchain": toolchain["status"],
        "backup": reading["backup"]["status"],
        "problems": [problem["code"] for problem in reading["problems"]],
    }
