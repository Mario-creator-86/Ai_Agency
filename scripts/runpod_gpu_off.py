"""Switch every RunPod Serverless GPU of the studio off, and say it in one line.

Run by `scripts/start.py` after the studio has stopped (and with ``--fast`` when the console
window is closing: purge + PATCH only, 2 s per request). It reads the studio's own database and
key file, sends the off (purge the queue, cancel what is left, workers.max=0, verify OFF), and
always exits 0: a launcher that is stopping must never be held by it. Silent when the studio has
no RunPod connection. Off is always allowed, under STOP AUTONOMIE too (ADR-GPU-OFF-ALWAYS).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))

VERIFIED = "GPU RunPod: oprit și verificat."
UNVERIFIED = (
    "GPU RunPod: oprirea nu a putut fi verificată — verifică în consola RunPod sau apasă "
    "«Oprește GPU acum» la pornire."
)


def studio() -> tuple[Any, Any]:
    """The studio's engine and key vault, from its own settings (never migrated here)."""
    from app.config import Settings  # noqa: PLC0415
    from app.db import create_db_engine  # noqa: PLC0415
    from app.integrations.vault import CredentialVault  # noqa: PLC0415

    settings = Settings()  # type: ignore[call-arg]
    engine = create_db_engine(settings.database_url)
    vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
    return engine, vault


def run(engine: Any, vault: Any, *, reason: str, fast: bool, transport: Any = None) -> str | None:
    """The off for every RunPod endpoint; the line to print, or None with no RunPod."""
    from app.providers.runpod.gpu_session import force_off  # noqa: PLC0415

    readings = force_off(engine, vault, reason=reason, fast=fast, transport=transport)
    if not readings:
        return None
    return VERIFIED if all(r.off for r in readings) else UNVERIFIED


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Switch the studio's RunPod GPU off.")
    parser.add_argument(
        "--reason", default="LAUNCHER_STOP", choices=["LAUNCHER_STOP", "SHUTDOWN", "OWNER_OFF"]
    )
    parser.add_argument("--fast", action="store_true", help="purge + PATCH only (window close)")
    args = parser.parse_args(argv)
    try:
        engine, vault = studio()
        try:
            line = run(engine, vault, reason=args.reason, fast=args.fast)
        finally:
            engine.dispose()
    except Exception:  # noqa: BLE001 - a stopping launcher is never held; the guard retries
        print(UNVERIFIED, flush=True)
        return 0
    if line:
        print(line, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
