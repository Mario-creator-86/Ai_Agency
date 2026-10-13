"""Delete the studio's history and start from zero; the configuration stays.

Run it with the studio stopped::

    uv run python scripts/reset_history.py            (asks nothing; backs up first)
    uv run python scripts/reset_history.py --dry-run  (only says what it would delete)

The database is copied to data/backups/studio-<timestamp>.db before anything is deleted,
and the script refuses to run while the studio still answers on its port — a worker in the
middle of a task would write into a history that no longer exists.
"""

from __future__ import annotations

import argparse
import socket
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.db import create_db_engine  # noqa: E402
from app.maintenance import HISTORY_TABLES, reset_history  # noqa: E402
from app.media.assembler import DEFAULT_STORAGE_ROOT  # noqa: E402


def studio_is_running(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except OSError:
        return False


def database_path(url: str) -> Path | None:
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        return None
    return Path(url[len(prefix) :])


def backup(path: Path) -> Path:
    folder = path.parent / "backups"
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = folder / f"{path.stem}-{stamp}{path.suffix}"
    with sqlite3.connect(path) as source, sqlite3.connect(target) as copy:
        source.backup(copy)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="count, delete nothing")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    settings = Settings()  # type: ignore[call-arg]
    path = database_path(settings.database_url)
    if path is None or not path.is_file():
        print(f"No SQLite database at {settings.database_url}; nothing to reset.")
        return 1
    if studio_is_running(args.host, args.port):
        print(f"The studio still answers on {args.host}:{args.port}. Stop it, then run this.")
        return 2

    engine = create_db_engine(settings.database_url)
    if args.dry_run:
        with sqlite3.connect(path) as connection:
            for table in HISTORY_TABLES + ("domain_event",):
                count = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                if count:
                    print(f"  {table}: {count}")
        print("Dry run: nothing deleted.")
        return 0

    saved = backup(path)
    print(f"Backup: {saved}")
    result = reset_history(engine, media_root=DEFAULT_STORAGE_ROOT)
    engine.dispose()
    for table, count in result["deleted"].items():
        if count:
            print(f"  {table}: {count} deleted")
    print(f"  media folders emptied: {result['media_folders']}")
    print("The history is gone; the configuration stayed. Start the studio again.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
