"""List the film folders in the media root that no film in the studio's database owns.

Measured 2026-10-01 (REL-08): the studio's media folder held 299 GiB in 1,084 folders, most of
them left by test runs before the suite was given a folder of its own. A folder is named after
its film's storyboard id; one whose id is not in the database belongs to no film the studio
knows.

A dry run by default: it reads the database (read-only) and the folder sizes, prints what it
found and changes nothing. Only ``--delete``, which the Owner runs himself, deletes the folders
listed under «Fără film în baza de date» — never a folder whose name is not a storyboard id
(a rehearsal's copy, anything he put there), and never one the database knows.

Usage::

    uv run python scripts/media_inventory.py                 (the studio's own settings)
    uv run python scripts/media_inventory.py --database data/studio.db --media-root D:/films
    uv run python scripts/media_inventory.py --delete        (deletes the orphans listed)
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

GB = 1024**3


def folder_bytes(folder: Path) -> int:
    """Bytes held under ``folder``; links are not followed."""
    total = 0
    for path in folder.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except OSError:
            continue
    return total


def is_storyboard_id(name: str) -> bool:
    try:
        return str(UUID(name)) == name.lower()
    except ValueError:
        return False


def known_storyboards(database: Path) -> set[str]:
    """Every storyboard id in the studio's database, read through a read-only connection."""
    uri = f"file:{database.resolve().as_posix()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        return {str(row[0]).lower() for row in connection.execute("SELECT id FROM storyboard")}


def inventory(database: Path, media_root: Path) -> dict[str, list[dict[str, object]]]:
    """The media root's folders in three lists: ``films`` the database knows, ``orphans``
    named like a storyboard and unknown to it, and ``other`` folders that are not films."""
    known = known_storyboards(database)
    found: dict[str, list[dict[str, object]]] = {"films": [], "orphans": [], "other": []}
    if not media_root.is_dir():
        return found
    for folder in sorted(media_root.iterdir()):
        if not folder.is_dir() or folder.is_symlink():
            continue
        entry: dict[str, object] = {
            "name": folder.name,
            "path": folder,
            "bytes": folder_bytes(folder),
        }
        if not is_storyboard_id(folder.name):
            found["other"].append(entry)
        elif folder.name.lower() in known:
            found["films"].append(entry)
        else:
            found["orphans"].append(entry)
    return found


def size(value: object) -> str:
    return f"{int(str(value)) / GB:.2f} GB".replace(".", ",")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--database", type=Path, help="the studio's database file")
    parser.add_argument("--media-root", type=Path, help="the folder the films are written to")
    parser.add_argument(
        "--delete",
        action="store_true",
        help="delete the folders listed under «Fără film în baza de date» (the Owner's act)",
    )
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        # Romanian words on a console or a pipe in another code page: never a crash.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")

    database, media_root = args.database, args.media_root
    if database is None or media_root is None:
        from app.config import Settings  # noqa: PLC0415 - only without explicit paths
        from app.media.disk import media_root as configured_root  # noqa: PLC0415
        from sqlalchemy.engine import make_url  # noqa: PLC0415

        settings = Settings()  # type: ignore[call-arg]
        if database is None:
            path = Path(str(make_url(settings.database_url).database))
            database = path if path.is_absolute() else ROOT / path
        if media_root is None:
            media_root = configured_root(settings)
    if not database.is_file():
        print(f"Baza de date nu există: {database}", file=sys.stderr)
        return 2

    found = inventory(database, media_root)
    print(f"Dosarul filmelor: {media_root}")
    print(
        f"Filme din baza de date: {len(found['films'])}, "
        f"{size(sum(int(str(e['bytes'])) for e in found['films']))}"
    )
    print(f"Dosare care nu sunt filme (nu se șterg niciodată): {len(found['other'])}")
    for entry in found["other"]:
        print(f"    {entry['name']}  {size(entry['bytes'])}")
    orphan_bytes = sum(int(str(e["bytes"])) for e in found["orphans"])
    print(f"Fără film în baza de date: {len(found['orphans'])} dosare, {size(orphan_bytes)}")
    for entry in found["orphans"]:
        print(f"    {entry['name']}  {size(entry['bytes'])}")

    if not args.delete:
        print("Nu s-a șters nimic (rulare de probă). Cu --delete se șterg dosarele de mai sus.")
        return 0
    failed = 0
    for entry in found["orphans"]:
        try:
            shutil.rmtree(Path(str(entry["path"])))
            print(f"Șters: {entry['name']}")
        except OSError as exc:
            failed += 1
            print(f"Nu s-a putut șterge {entry['name']}: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
