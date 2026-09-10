"""Rename the studio the Owner already created, as an explicit and audited act.

Why this exists
---------------
`bootstrap_studio` writes `STUDIO_NAME` exactly once, when the studio row is first created, and
then never touches it again. That invariant is deliberate: editing an environment default must
not silently rewrite domain state that already exists, because the studio's identity is part of
the immutable history, not a configuration value read at render time.

So when the agency was named **AMN-AI (Autonomous Machine Nexus — Artificial Intelligence)**, an
existing local database kept the old name and the interface kept displaying it. Renaming is
therefore a decision the Owner takes on purpose, here, and it is recorded the same way every
other change of state is recorded: a `studio.renamed` domain event appended at the next aggregate
version, in the same transaction as the row update. Nothing is rewritten in place without a trace.

Usage::

    uv run python scripts/rename_studio.py                 # use STUDIO_NAME from .env
    uv run python scripts/rename_studio.py "AMN-AI"        # or pass the name explicitly
    uv run python scripts/rename_studio.py --dry-run       # show what would change

The script is idempotent: if the stored name already matches, it reports that and writes nothing.
It performs no provider calls and does not touch the Owner policy, agents or any other aggregate.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.config import Settings  # noqa: E402
from app.db import create_db_engine  # noqa: E402
from app.models import DomainEvent, Studio  # noqa: E402
from app.services import append_event  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

MAX_NAME_LENGTH = 100


def rename_studio(engine, new_name: str, *, dry_run: bool = False) -> str:
    """Rename studio 1 and record why. Returns a human-readable outcome."""
    name = new_name.strip()
    if not name:
        raise SystemExit("Refusing to store an empty studio name.")
    if len(name) > MAX_NAME_LENGTH:
        raise SystemExit(f"Studio name is longer than {MAX_NAME_LENGTH} characters.")

    with Session(engine) as session, session.begin():
        studio = session.get(Studio, 1)
        if studio is None:
            raise SystemExit(
                "No studio exists yet. Run `uv run python scripts/bootstrap.py` first; "
                "bootstrap writes STUDIO_NAME when it creates the studio."
            )
        previous = studio.name
        if previous == name:
            return f"Studio is already named {name!r}. Nothing was written."
        if dry_run:
            return f"Would rename {previous!r} -> {name!r} (no changes written)."

        # The next version for this aggregate: `studio.created` occupies version 1.
        current_version = session.scalar(
            select(func.max(DomainEvent.aggregate_version)).where(
                DomainEvent.aggregate_type == "studio", DomainEvent.aggregate_id == "1"
            )
        )
        next_version = (current_version or 1) + 1

        studio.name = name
        append_event(
            session,
            "studio.renamed",
            "studio",
            "1",
            next_version,
            {"previous_name": previous, "name": name, "reason": "Owner renamed the agency"},
            str(uuid4()),
        )
        return (
            f"Renamed {previous!r} -> {name!r} "
            f"(studio.renamed, version {next_version})."
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "name",
        nargs="?",
        help="The new studio name. Defaults to STUDIO_NAME from the environment/.env.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report the change without writing it."
    )
    args = parser.parse_args()

    settings = Settings()  # type: ignore[call-arg]
    engine = create_db_engine(settings.database_url)
    try:
        print(rename_studio(engine, args.name or settings.name, dry_run=args.dry_run))
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
