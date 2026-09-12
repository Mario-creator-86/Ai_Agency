"""Apply the model allocation in `config/workforce_seed.json` to this studio's employees.

The studio applies it on its own the first time it learns which models exist, and never
afterwards: an Owner's choice from Settings is not overwritten by a file. Run this when the
allocation in the file is a new instruction and should replace what is configured now.

    uv run python scripts/apply_llm_allocation.py           # only unassigned employees
    uv run python scripts/apply_llm_allocation.py --force   # over existing assignments

Nothing here contacts a vendor. A model the studio has not discovered and verified cannot be
assigned, and is reported instead.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.agents.ensemble import apply_llm_allocation  # noqa: E402
from app.config import Settings  # noqa: E402
from app.db import create_db_engine  # noqa: E402


def main() -> int:
    force = "--force" in sys.argv[1:]
    settings = Settings()  # type: ignore[call-arg]
    engine = create_db_engine(settings.database_url)
    try:
        result = apply_llm_allocation(engine, force=force)
    finally:
        engine.dispose()
    for row in result["applied"]:
        extra = " + ".join(filter(None, [row["secondary"], row["tertiary"]]))
        print(
            f"{row['role']:16} {row['primary']}"
            + (f"  [{row['strategy']}: {extra}]" if extra else "  [SINGLE]")
        )
    for row in result["skipped"]:
        print(f"{row['role']:16} netrimis: {row['why']}")
    if not result["applied"]:
        print("Nimic aplicat. Modelele trebuie descoperite și verificate întâi (Settings).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
