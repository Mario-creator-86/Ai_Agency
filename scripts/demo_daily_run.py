"""Run one full day of the demo studio in a throwaway folder and print what each stage did.

    uv run python scripts/demo_daily_run.py [--keep] [--folder PATH]

Why a separate database: a daily run writes topics, claims, scripts, renders and a closed log.
Demonstration work in the real studio would leave invented production in an append-only
history that no later reader could tell apart from the real thing. So the day runs in a fresh
folder (a temporary one unless --folder names another), deleted afterwards unless --keep.

What is real and what is not (app.demo): the runbook, the stage wiring, the Policy Kernel, the
factual gate, the story review, FFmpeg's encode and quality control are the production code,
unchanged. The vendors are simulated: a scripted language model (DemoModel) that answers in
the schemas the pipeline requires and reads every identifier out of the prompt, local
pictures and a synthetic voice, no motion vendor, no YouTube. Nothing is bought, nothing is
published, and no socket of this process may leave the machine.

For the same demo in the page, run `uv run python scripts/start.py --demo`.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from tempfile import mkdtemp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# The Windows console defaults to cp1252, which cannot encode Romanian diacritics.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


def demo_folder_settings(folder: Path):  # type: ignore[no-untyped-def]
    """Settings for a demo studio living entirely inside ``folder``."""
    from app.config import Settings  # noqa: PLC0415

    folder.mkdir(parents=True, exist_ok=True)
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        owner_token="d" * 48,  # pragma: allowlist secret
        database_url=f"sqlite:///{(folder / 'demo.db').as_posix()}",
        media_root=folder / "media",
        backup_dir=folder / "backups",
        log_dir=folder / "logs",
        demo_mode=True,
        worker_enabled=False,
        ffmpeg_path=shutil.which("ffmpeg"),
    )


def run(folder: Path) -> dict:
    from app.db import create_db_engine, migrate  # noqa: PLC0415
    from app.demo import (  # noqa: PLC0415
        demo_registry,
        demo_settings,
        demo_vendors,
        no_outbound_network,
        prepare_demo_studio,
        run_demo_day,
    )
    from app.integrations.vault import CredentialVault  # noqa: PLC0415
    from app.media.models import MediaAsset, QualityControlReport  # noqa: PLC0415
    from app.services import bootstrap_studio  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import Session  # noqa: PLC0415

    settings = demo_settings(demo_folder_settings(folder))
    engine = create_db_engine(settings.database_url)
    try:
        migrate(engine)
        bootstrap_studio(engine, settings)
        prepare_demo_studio(engine, settings)
        vault = CredentialVault(folder / "demo.credentials.key")
        with no_outbound_network(), demo_vendors():
            result = run_demo_day(engine, settings, vault, demo_registry(engine))

        print("")
        print(
            f"Stare: {result['status']}   etape complete: "
            f"{result['stages_completed']}/{result['stages_total']}"
        )
        if result.get("stopped_at_stage"):
            print(f"Oprit la: {result['stopped_at_stage']} - {result.get('stop_reason')}")
        for stage in result["stages"]:
            print(f"  {stage['stage']:<26} {stage['status']:<10} {stage['reason'][:200]}")

        with Session(engine) as session:
            assets = list(session.scalars(select(MediaAsset)))
            reports = list(session.scalars(select(QualityControlReport)))
        print("")
        print("Produse pe disc:")
        films = []
        for asset in assets:
            path = Path(asset.uri_or_path)
            size = path.stat().st_size if path.is_file() else 0
            if asset.asset_type == "RENDERED_VIDEO" and size:
                films.append(path)
            print(f"  {asset.asset_type:<16} {size:>10} octeți  {path.name}")
        for report in reports:
            reasons = report.failure_reasons_json or []
            print(f"  QC {report.status:<8} scor {report.score}  motive: {reasons[:3]}")
        result["films"] = [str(path) for path in films]
        return result
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="O zi demonstrativă, cu furnizori simulați.")
    parser.add_argument("--folder", type=Path, default=None, help="unde se face ziua")
    parser.add_argument("--keep", action="store_true", help="păstrează folderul după rulare")
    args = parser.parse_args()
    folder = args.folder or Path(mkdtemp(prefix="amn-demo-"))
    print(f"Studio demonstrativ izolat în {folder} (furnizori simulați; nimic nu se publică).")
    try:
        result = run(folder)
    finally:
        if not args.keep and args.folder is None:
            shutil.rmtree(folder, ignore_errors=True)
    if result.get("films"):
        print("")
        print("Filmul demonstrativ: " + ", ".join(result["films"]))
        if not args.keep:
            print("(Folderul a fost șters; rulează cu --keep ca să păstrezi filmul.)")
        return 0
    print("")
    print("Ziua nu a produs niciun film: vezi motivele etapelor de mai sus.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
