"""Put a backup of the studio's database back, with the restore guard.

Refused while the studio answers on its port: stop it first (Ctrl+C in its window, or
uninstall_studio_service.ps1 / Stop-ScheduledTask for the service). The copy is checked against
its manifest (sha256) and by SQLite before anything changes; the database it replaces is kept
first, as ``studio-<UTC>-prerestaurare.db`` beside the backups.

After the restore the studio starts guarded: the autonomy STOP on, the environment TEST and
the daily run's clock off. Nothing is bought or published from a restored past until the Owner
has looked at the studio and turned them back on, from the page. The connections whose keys
cannot be read with the key beside the database are listed: type them again in Setări.

Usage::

    uv run python scripts/restore.py data/backups/studio-20261002T033000Z.db
    uv run python scripts/restore.py <copy.db> --database data/studio.db --port 8000 --yes
    uv run python scripts/restore.py <copy.db> --restore-key   (same Windows account only)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.backup import RestoreRefused, database_file, restore_backup  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("copy", type=Path, help="the backup copy (studio-<UTC>.db)")
    parser.add_argument("--database", type=Path, help="the database to replace (default: settings)")
    parser.add_argument("--host", help="the studio's address (default: settings)")
    parser.add_argument("--port", type=int, help="the studio's port (default: settings)")
    parser.add_argument(
        "--restore-key",
        action="store_true",
        help="also put back the credentials key copied with the backup",
    )
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        # Romanian words on a console or a pipe in another code page: never a crash.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="replace")

    database, host, port = args.database, args.host, args.port
    if database is None or host is None or port is None:
        from app.config import Settings  # noqa: PLC0415 - only when a value is not given

        settings = Settings()  # type: ignore[call-arg]
        database = database or database_file(str(settings.database_url))
        host = host or settings.host
        port = port or settings.port

    if not args.yes:
        answer = input(
            f"Baza de date {database} va fi înlocuită cu {args.copy}. Continui? (da/nu) "
        )
        if answer.strip().lower() not in ("da", "d", "yes", "y"):
            print("Nu s-a schimbat nimic.")
            return 1
    try:
        result = restore_backup(
            args.copy, database, host=str(host), port=int(port), restore_key=args.restore_key
        )
    except RestoreRefused as exc:
        print(f"Restaurare refuzată: {exc.reason_ro}", file=sys.stderr)
        return 2
    print(f"Restaurat: {database} din {result['restored_from']['file']}")
    if result["previous"]:
        print(f"    baza de date de dinainte este păstrată în {result['previous']['path']}")
    print(f"    {result['guard']['reason_ro']}")
    if result["key_restored"]:
        print("    cheia credențialelor a fost pusă înapoi.")
    if result["credentials"]:
        print("    Conexiuni de reintrodus (cheile lor nu se pot citi):")
        for item in result["credentials"]:
            print(f"      «{item['name']}» ({item['kind']}) în {item['where']}")
    else:
        print("    Toate conexiunile salvate se citesc cu cheia de lângă baza de date.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
