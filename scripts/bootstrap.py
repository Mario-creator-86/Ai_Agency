"""Create local credentials and migrate/initialize state; never perform provider calls."""

import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agents.services import seed_initial_workforce  # noqa: E402
from app.analytics.services import seed_default_strategy  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import create_db_engine, migrate  # noqa: E402
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
    finally:
        engine.dispose()
    print("Foundation database ready. Owner token is in .env (never share or commit it).")
    print(
        "To build the frontend and start the studio in one step, run start.cmd "
        "(or: uv run python scripts/start.py)."
    )


if __name__ == "__main__":
    main()
