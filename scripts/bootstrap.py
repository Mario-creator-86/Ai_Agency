"""Create local credentials and migrate/initialize state; never perform provider calls."""

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.services import seed_initial_workforce  # noqa: E402
from app.analytics.services import seed_default_strategy  # noqa: E402
from app.backup import backup_before_migration, backup_folder, database_file  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import create_db_engine, migrate  # noqa: E402
from app.decisions.seed import seed_owner_decisions  # noqa: E402
from app.economy.prices import seed_documented_prices  # noqa: E402
from app.economy.services import seed_chart_of_accounts  # noqa: E402
from app.media.services import seed_default_character_bibles  # noqa: E402
from app.publishing.services import seed_default_channels  # noqa: E402
from app.services import bootstrap_studio  # noqa: E402


def main() -> None:
    env = ROOT / ".env"
    if not env.exists():
        template = (ROOT / ".env.example").read_text(encoding="utf-8")
        # str.write takes a single argument; the previous two-argument call raised TypeError
        # on every first-time bootstrap.
        content = template.replace(
            "STUDIO_OWNER_TOKEN=\n", f"STUDIO_OWNER_TOKEN={secrets.token_urlsafe(48)}\n"
        )
        with env.open("x", encoding="utf-8") as handle:
            handle.write(content)
        env.chmod(0o600)
    settings = Settings()  # type: ignore[call-arg]
    made = prepare_database(settings)
    if made is not None:
        print(
            f"Backup before the migration: {made['path']} "
            f"(revision {made['revision']}, sha256 {str(made['sha256'])[:12]}...)."
        )
    print("Foundation database ready. Owner token is in .env (never share or commit it).")
    print(
        "To build the frontend and start the studio in one step, run start.cmd "
        "(or: uv run python scripts/start.py)."
    )


def migration_head() -> str:
    """The head of the migration chain, read from the migrations themselves."""
    from alembic.config import Config  # noqa: PLC0415
    from alembic.script import ScriptDirectory  # noqa: PLC0415

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/migrations"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if not head:
        raise RuntimeError("The migration chain has no single head")
    return str(head)


def prepare_database(settings: Settings) -> dict | None:
    """Back up a studio's database that is about to be migrated, migrate it and seed it.

    start.py runs this on every start (the scheduled service included), so a database at an
    older revision used to be migrated in place with no copy (REL-04). Now a non-empty
    database below the head is copied first (`app.backup`, tag ``premigrare``, beside the
    other backups); a new or current database is not. A copy that cannot be made stops here:
    nothing is migrated without one. Returns the copy's manifest, or None.
    """
    database = database_file(str(settings.database_url))
    made = backup_before_migration(database, backup_folder(settings, database), migration_head())
    engine = create_db_engine(settings.database_url)
    try:
        migrate(engine)
        bootstrap_studio(engine, settings)
        seed_initial_workforce(engine)  # roles, agents, and their work contracts
        seed_default_character_bibles(engine)  # linked to the employees holding each role
        seed_default_channels(engine)
        # The virtual books need their accounts before anything can be posted. Seeding creates
        # the structure only; the ledger stays empty until real evidence is recorded.
        seed_chart_of_accounts(engine)
        # The one figure a vendor publishes for every model of its kind (ElevenLabs), marked
        # DOCUMENTED so nobody reads it as the Owner's plan. Without it a studio where he has
        # typed no price costs narration at nothing, which is worse than the gap the
        # Accountant reports. It never overrides a price of any provenance, so running
        # bootstrap again over a live studio changes nothing he has set.
        seed_documented_prices(engine)
        # Neutral v1 editorial strategy per channel; it expresses no preference until real
        # analytics snapshots produce a recommendation the Owner applies.
        seed_default_strategy(engine)
        # The audit's open questions to the Owner, as cards in his decisions window; each
        # once, never again after he answered it (app.decisions.seed).
        seed_owner_decisions(engine, settings)
    finally:
        engine.dispose()
    return made


if __name__ == "__main__":
    main()
