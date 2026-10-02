"""Back up the studio's database now, while it runs: the copy, its check, the key beside it.

The studio makes the same backup once a day on its own (the ``backup_daily`` job, at
STUDIO_BACKUP_HOUR_LOCAL); this is the Owner's backup on demand — before an update, before
moving the studio, whenever he wants one.

What it writes, in the backup folder (STUDIO_BACKUP_DIR, else ``backups`` beside the database,
data/backups for the studio): ``studio-<UTC>.db`` (SQLite's online copy, checked with
``PRAGMA integrity_check``), ``studio-<UTC>.json`` (its manifest with the sha256),
``key/studio-<UTC>.credentials.key`` (the wrapped key: it opens only for the Windows account
that made it) and ``studio-<UTC>.media.json`` (the list of media files, not their bytes —
copy the media folder itself to another disk to keep the films).

Usage::

    uv run python scripts/backup.py
    uv run python scripts/backup.py --database data/studio.db --folder E:/studio-backups
    uv run python scripts/backup.py --list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.backup import (  # noqa: E402
    BackupError,
    backup_folder,
    database_file,
    list_backups,
    make_backup,
)


def _quiet_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        # Romanian words on a console or a pipe in another code page: never a crash.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, help="the database file (default: settings)")
    parser.add_argument("--folder", type=Path, help="the backup folder (default: settings)")
    parser.add_argument("--no-media-list", action="store_true", help="skip the media listing")
    parser.add_argument("--list", action="store_true", help="list the backups and stop")
    args = parser.parse_args(argv)
    _quiet_console()

    settings = None
    if args.database is None or args.folder is None or not args.no_media_list:
        from app.config import Settings  # noqa: PLC0415 - only when a path is not given

        settings = Settings()  # type: ignore[call-arg]
    database = args.database or database_file(str(settings.database_url))  # type: ignore[union-attr]
    folder = args.folder or backup_folder(settings, database)

    if args.list:
        copies = list_backups(folder)
        print(f"Copii de siguranță în {folder}: {len(copies)}")
        for item in copies:
            tag = f" ({item['tag']})" if item["tag"] else ""
            print(f"    {item['path'].name}{tag}")
        return 0

    media = None
    if not args.no_media_list:
        from app.media.disk import media_root  # noqa: PLC0415

        media = media_root(settings)
    try:
        made = make_backup(
            database,
            folder,
            media_root=media,
            keep_daily=int(getattr(settings, "backup_keep_daily", 14)),
            keep_weekly=int(getattr(settings, "backup_keep_weekly", 4)),
        )
    except BackupError as exc:
        print(f"Copia NU s-a făcut: {exc.reason_ro}", file=sys.stderr)
        return 1
    print(f"Copie făcută: {made['path']}")
    print(f"    sha256 {made['sha256']}, {made['bytes']} octeți, revizia {made['revision']}")
    if made.get("key"):
        print(f"    cheia credențialelor: {made['key']['path']}")
        print(f"    {made['key']['note_ro']}")
    else:
        print("    nicio cheie de credențiale lângă baza de date (nimic salvat încă).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
