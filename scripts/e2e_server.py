"""The studio on fakes, for the page's Playwright flows (PAGE-15).

Starts the real app in TEST on 127.0.0.1 on a free port (never 8000, the Owner's studio), with
a database, a media folder, logs and backups in a throwaway folder, every paid vendor replaced
(app.demo.demo_vendors), the test suite's spies on the shooting sheet's seams, and no socket
allowed beyond this machine (app.demo.no_outbound_network). It serves a page built into a
scratch folder (``--dist``) and refuses the studio's own frontend/dist.

On start it prints one JSON line: {"url", "token", "storyboard_id", "folder"}. The token is
generated for this run and lives only in this process and that line. Stop it with Ctrl+C or by
ending the process; nothing it wrote is outside ``--folder``.

    uv run python scripts/e2e_server.py --dist <scratch>/dist

It uses the test suite's fixtures (tests/), so it runs from a checkout with the dev group.
"""

from __future__ import annotations

import argparse
import json
import secrets
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))

#: The Owner's studio listens here; the flows never take it.
FORBIDDEN_PORTS = frozenset({8000})
#: Folders that belong to the Owner's studio; the flows never write into them.
FORBIDDEN_FOLDERS = (ROOT / "data", ROOT / "backend" / "storage", ROOT / "frontend" / "dist")


class E2ERefused(SystemExit):
    """The server will not start like this; the reason is printed."""


def free_port() -> int:
    """A port nothing listens on, on the loopback interface only."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _inside(path: Path, folder: Path) -> bool:
    try:
        path.resolve().relative_to(folder.resolve())
    except ValueError:
        return False
    return True


def check_places(dist: Path, folder: Path, port: int) -> None:
    """Refuse the Owner's port, his studio's folders and a page that was never built."""
    if port in FORBIDDEN_PORTS:
        raise E2ERefused(f"Portul {port} este al studioului; alege altul (sau 0, unul liber).")
    for forbidden in FORBIDDEN_FOLDERS:
        if _inside(folder, forbidden):
            raise E2ERefused(
                f"Folderul de lucru {folder} este în {forbidden}; alege unul temporar."
            )
    if _inside(dist, ROOT / "frontend" / "dist"):
        raise E2ERefused(
            "Pagina testelor se construiește într-un folder temporar (vite build --outDir), "
            "niciodată în frontend/dist, pe care îl servește studioul."
        )
    if not (dist / "index.html").is_file():
        raise E2ERefused(f"{dist} nu conține o pagină construită (index.html lipsește).")


def build_settings(folder: Path, token: str) -> Any:
    from app.config import Settings
    from app.demo import demo_settings

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        owner_token=token,
        database_url=f"sqlite:///{(folder / 'e2e.db').as_posix()}",
        allowed_hosts=["127.0.0.1", "localhost"],
        worker_enabled=False,
        provider_catalog_refresh_enabled=False,
        log_to_file=False,
        media_root=folder / "media",
        backup_dir=folder / "backups",
        min_free_gb=0,
    )
    # every switch that would reach the network off (trends, weather, the Unreal stream, ...)
    return demo_settings(settings)


def prepare_studio(settings: Any, folder: Path) -> str:
    """The database, a released stop in TEST, the channels and one planned film."""
    from app.db import create_db_engine, migrate
    from app.models import OwnerPolicy
    from app.publishing.services import seed_default_channels
    from app.services import bootstrap_studio
    from sqlalchemy.orm import Session
    from test_film_dry_run import planned_film

    engine = create_db_engine(settings.database_url)
    migrate(engine)
    bootstrap_studio(engine, settings, autonomy_mode="AUTONOMOUS_CEO")
    with Session(engine) as session, session.begin():
        policy = session.get(OwnerPolicy, 1)
        policy.autonomy_stopped = False
        policy.environment = "TEST"
        policy.version += 1
    seed_default_channels(engine)
    films = folder / "fixtures"
    films.mkdir(parents=True, exist_ok=True)
    storyboard_id = planned_film(engine, films)
    engine.dispose()
    return storyboard_id


def serve_page(inner: Any, dist: Path) -> None:
    """Serve the scratch-built page at /, in place of the studio's own frontend/dist."""
    from app.main import PageFiles
    from starlette.routing import Mount

    routes = [r for r in inner.router.routes if getattr(r, "name", "") != "frontend"]
    routes.append(Mount("/", app=PageFiles(directory=dist, html=True), name="frontend"))
    inner.router.routes[:] = routes


def wire_fakes(inner: Any) -> None:
    """The shooting sheet's seams, as the suite's tests set them on ``app.state``."""
    from test_film_costing import SEEDANCE, VEO_FAST, Account, Models, SpyVideo
    from test_stills_stage import SpyStills

    account = Account(10_000)
    inner.state.scene_model_capabilities = [SEEDANCE, VEO_FAST]
    inner.state.image_adapter = SpyStills()
    inner.state.runway_account = account
    inner.state.video_adapter_for_model = Models(
        SpyVideo("seedance2_5", account), SpyVideo("veo3.1_fast", account)
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dist", required=True, type=Path, help="the page built to a scratch folder"
    )
    parser.add_argument(
        "--folder", type=Path, default=None, help="throwaway folder (default: new temp)"
    )
    parser.add_argument("--port", type=int, default=0, help="0 = a free port")
    args = parser.parse_args(argv)

    folder = args.folder or Path(tempfile.mkdtemp(prefix="amn_e2e_"))
    folder.mkdir(parents=True, exist_ok=True)
    port = args.port or free_port()
    check_places(args.dist, folder, port)

    import uvicorn
    from app.demo import demo_vendors, no_outbound_network
    from app.main import create_app

    token = secrets.token_urlsafe(48)
    settings = build_settings(folder, token)
    with no_outbound_network(), demo_vendors():
        storyboard_id = prepare_studio(settings, folder)
        app = create_app(settings)
        inner = app.app  # create_app wraps the FastAPI app in TrustedHostMiddleware
        serve_page(inner, args.dist.resolve())
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
        )

        def announce() -> None:
            while not server.started:
                time.sleep(0.05)
            wire_fakes(inner)
            print(
                json.dumps(
                    {
                        "url": f"http://127.0.0.1:{port}",
                        "token": token,
                        "storyboard_id": storyboard_id,
                        "folder": str(folder),
                    }
                ),
                flush=True,
            )

        threading.Thread(target=announce, daemon=True).start()
        server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
