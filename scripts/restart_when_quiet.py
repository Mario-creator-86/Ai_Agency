"""Restart the studio in the first quiet window, without the Owner («dai singur restart»).

Quiet means two things at once: the newest RunPod GPU event is «off verified» (no GPU session
open, nothing being bought), AND the durable worker holds no film task (no FILM_CONTINUE
CLAIMED). The second condition is from 2026-10-12, 15:19: the watcher restarted between two GPU
steps of one repair round of the serial — the GPU read off for a few seconds — and the stop
cancelled scene 4's two stills (RUNPOD.CANCELLED, 14 credits of GPU overhead) and emptied
scene 7's motion; both rounds were written as paid redos. A stop between two steps of one round
is a stop inside the round.

Reads a fresh COPY of the database (``data/studio.db`` + WAL + SHM copied to ``--copy``, opened
read-only; the live file is never opened), every 10 s; when the local API is readable
(GET /api/v1/events, paged by sequence) its stream is read too, but the worker's state always
comes from the copy. Runs ``scripts/restart.py`` once, then exits (0: restarted; 3: no quiet
window within ``--max-minutes``, or too close to the deadline for a restart to be watched).

Usage: uv run --locked python -X utf8 scripts\\restart_when_quiet.py http://127.0.0.1:8000/api/v1
       [--max-minutes 120] [--poll 10] [--copy <dir>]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OPENED, OFF = "runpod.gpu_session_opened", "runpod.gpu_off_verified"
GPU_KINDS = (OPENED, OFF)
RESTART = ["uv", "run", "--locked", "python", "-X", "utf8", "scripts/restart.py", "--wait", "600"]
#: A restart takes up to ~4 minutes: one is never started that this watch cannot see through.
RESTART_MINUTES = 5
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)


def api_events(base: str, after: int) -> list[dict] | None:
    """One page of the studio's events after ``after``, or None when the API is not readable
    (no token, the server down): the copy is then the only source."""
    url = f"{base}/events?after={after}&limit=300"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - localhost
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - the copy is read instead
        print("api unreadable:", type(exc).__name__)
        return None
    items = data.get("events") if isinstance(data, dict) else data
    return items if isinstance(items, list) else None


def refresh_copy(copy: Path) -> Path:
    """A fresh read-only copy of the live database (with its WAL and SHM), never the live file."""
    copy.mkdir(parents=True, exist_ok=True)
    for name in ("studio.db", "studio.db-wal", "studio.db-shm"):
        source = REPO / "data" / name
        if source.exists():
            shutil.copyfile(source, copy / name)
    return copy / "studio.db"


def _read(copy: Path, sql: str, params: tuple = ()) -> tuple | None:
    con = sqlite3.connect(f"file:{refresh_copy(copy).as_posix()}?mode=ro", uri=True)
    try:
        return con.execute(sql, params).fetchone()
    finally:
        con.close()


def newest_gpu(copy: Path) -> tuple[int, str] | None:
    """The newest GPU event (sequence, kind): OFF means no session is open now."""
    row = _read(
        copy,
        "select sequence, event_type from domain_event where event_type in (?, ?) "
        "order by sequence desc limit 1",
        GPU_KINDS,
    )
    return (int(row[0]), str(row[1])) if row else None


def worker_busy(copy: Path) -> bool:
    """Whether the worker is inside a film's task now (a FILM_CONTINUE CLAIMED)."""
    row = _read(
        copy,
        "select count(*) from task_queue where task_type = 'FILM_CONTINUE' and status = 'CLAIMED'",
    )
    return bool(row and int(row[0]) > 0)


def restart() -> int:
    print("quiet window at", time.strftime("%H:%M:%S"), "- restarting")
    result = subprocess.run(
        RESTART,
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    print(result.stdout[-3000:])
    if result.stderr.strip():
        print("stderr:", result.stderr[-800:])
    print("restart exit", result.returncode)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--max-minutes", type=float, default=120)
    parser.add_argument("--poll", type=float, default=10)
    parser.add_argument(
        "--copy",
        default=str(Path(tempfile.gettempdir()) / "amn_restart_when_quiet"),
        help="where the read-only copy of the database is written (never under data/)",
    )
    args = parser.parse_args()
    copy = Path(args.copy)
    deadline = time.monotonic() + args.max_minutes * 60

    def time_for_a_restart() -> bool:
        return time.monotonic() + RESTART_MINUTES * 60 < deadline

    print("quiet = GPU off verified AND no FILM_CONTINUE claimed; polling every", args.poll, "s")
    last_gpu: tuple[int, str] | None = None
    print("start marker read at the first poll")
    said_busy = False
    while time.monotonic() < deadline:
        try:
            gpu = newest_gpu(copy)
            busy = worker_busy(copy)
        except (OSError, sqlite3.Error) as exc:
            # A copy taken while SQLite holds a byte-range lock on the live file reads
            # «Permission denied» on Windows (2026-10-12, 16:46: the watcher died of it). The
            # next poll reads again; nothing is decided on a copy that could not be made.
            print(time.strftime("%H:%M:%S"), "copy not readable now:", type(exc).__name__)
            time.sleep(args.poll)
            continue
        if gpu and gpu != last_gpu:
            print(time.strftime("%H:%M:%S"), "gpu", gpu)
            last_gpu = gpu
        if busy != said_busy:
            print(
                time.strftime("%H:%M:%S"),
                "worker inside a film task; waiting" if busy else "worker free of film tasks",
            )
            said_busy = busy
        if (gpu is None or gpu[1] == OFF) and not busy:
            return restart() if time_for_a_restart() else 3
        time.sleep(args.poll)
    print("no quiet window within", args.max_minutes, "minutes")
    return 3


if __name__ == "__main__":
    sys.exit(main())
