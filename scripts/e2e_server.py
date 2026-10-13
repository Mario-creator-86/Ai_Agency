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
from uuid import uuid4

from fastapi import Depends, HTTPException, Request

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
        # The flows sign in through the form, as from another machine (LOCAL_AUTO_LOGIN).
        local_auto_login=False,
    )
    # every switch that would reach the network off (trends, weather, the Unreal stream, ...)
    return demo_settings(settings)


def prepare_studio(settings: Any, folder: Path, *, scene_identities: bool = False) -> str:
    """The database, a released stop in TEST, the channels and one planned film."""
    from app.agents.services import seed_initial_workforce
    from app.db import create_db_engine, migrate
    from app.models import OwnerPolicy
    from app.publishing.services import seed_default_channels
    from app.services import bootstrap_studio
    from sqlalchemy.orm import Session
    from test_film_dry_run import planned_film

    engine = create_db_engine(settings.database_url)
    migrate(engine)
    bootstrap_studio(engine, settings, autonomy_mode="AUTONOMOUS_CEO")
    seed_initial_workforce(engine)
    if scene_identities:
        bind_scene_identities(engine, folder)
    seed_extra_desks(engine)
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


def bind_scene_identities(engine: Any, folder: Path) -> None:
    """Bind fresh test hires to the original art IDs, only in this disposable database.

    The production atlas refuses a similar name with a different employee ID. Preserve that
    guard rather than injecting a fake profile into the browser. All FK references are rekeyed
    in one deferred transaction before the test server can answer any request.
    """
    from app.agents.models import Agent
    from app.models import Base
    from app.services import append_event
    from sqlalchemy import select, update
    from sqlalchemy.orm import Session

    if not engine.url.database or not _inside(Path(engine.url.database), folder):
        raise E2ERefused("Scene identities require the disposable test database")
    bible = json.loads(
        (ROOT / "frontend/tests/fixtures/pixel_actors_bible.json").read_text(encoding="utf-8")
    )
    with Session(engine) as session, session.begin():
        agents = list(session.scalars(select(Agent)))
        if len(agents) != len(bible) or any(a.version != 1 for a in agents):
            raise E2ERefused("Scene identities require fresh seeded hires")
        session.connection().exec_driver_sql("PRAGMA defer_foreign_keys = ON")
        for character in bible:
            first = character["canonical_name"].split()[0].casefold()
            agent = next(a for a in agents if first in a.display_name.casefold().split())
            previous, current = agent.id, character["employee_id"]
            for table in Base.metadata.sorted_tables:
                for column in table.columns:
                    if any(fk.target_fullname == "agent.id" for fk in column.foreign_keys):
                        session.execute(
                            update(table).where(column == previous).values({column.name: current})
                        )
            event = append_event(
                session,
                "agent.hired",
                "agent",
                current,
                1,
                {"display_name": agent.display_name, "test_identity_binding": True},
                str(uuid4()),
            )
            session.execute(
                update(Agent)
                .where(Agent.id == previous)
                .values(id=current, event_id=event.event_id)
            )


def seed_extra_desks(engine: Any) -> None:
    """Two actual test employees exercise annex desks without changing the eight seeded roles."""
    from app.agents.models import Agent, Role
    from app.services import utc_now
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    with Session(engine) as session, session.begin():
        template = session.scalars(select(Agent)).first()
        role = Role(
            id=str(uuid4()),
            name="BrowserTestColleague",
            mission="Exercise personal seating",
            allowed_task_types="test",
            prohibited_actions="paid_work",
            created_at=utc_now(),
            event_id=template.event_id,
        )
        session.add(role)
        session.flush()
        for i in range(2):
            session.add(
                Agent(
                    id=str(uuid4()),
                    display_name=f"Test colleague {i + 1}",
                    role_id=role.id,
                    provider_id=template.provider_id,
                    model_id=template.model_id,
                    lifecycle="ACTIVE",
                    runtime_state="IDLE",
                    max_concurrent_tasks=1,
                    version=1,
                    hired_at=utc_now(),
                    event_id=template.event_id,
                )
            )


def wire_agent_state_probe(inner: Any) -> None:
    """Drive committed agent events in the disposable server only; never a production route."""
    from app.agents.models import Agent
    from app.db import lock_for_write
    from app.security import require_owner
    from app.workflows.services import append_event_with_outbox
    from sqlalchemy.orm import Session

    @inner.post("/api/v1/e2e/agent-state", dependencies=[Depends(require_owner)])
    def agent_state_probe(request: Request, command: dict[str, Any]) -> dict:
        settings = request.app.state.settings
        folder = getattr(request.app.state, "e2e_folder", None)
        database = Path(request.app.state.engine.url.database).resolve()
        if folder is None or not _inside(database, folder) or settings.worker_enabled:
            raise HTTPException(403, "Agent probe requires the isolated test server")
        mode = command.get("runtime_state")
        if not isinstance(mode, str) or mode not in {
            "IDLE",
            "WORKING",
            "THINKING",
            "REVIEWING",
            "BLOCKED",
            "ERROR",
        }:
            raise HTTPException(422, "Invalid runtime state")
        if not isinstance(command.get("agent_id"), str) or not isinstance(
            command.get("legacy_event", False), bool
        ):
            raise HTTPException(422, "Invalid test probe command")
        with Session(request.app.state.engine) as session, session.begin():
            lock_for_write(session)
            agent = session.get(Agent, command.get("agent_id"))
            if agent is None:
                raise HTTPException(404, "No such test employee")
            agent.runtime_state = mode
            agent.version += 1
            _, outbox = append_event_with_outbox(
                session,
                "agent.state_changed",
                "agent",
                agent.id,
                agent.version,
                {"runtime_state": mode, "task_type": "browser_state_probe"},
                str(uuid4()),
            )
            if command.get("legacy_event") is True:
                outbox.payload = {
                    key: value
                    for key, value in outbox.payload.items()
                    if key != "aggregate_version"
                }
            return {"agent_id": agent.id, "runtime_state": mode, "version": agent.version}


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
    parser.add_argument(
        "--scene-identities",
        action="store_true",
        help="original employee/art IDs in the fresh test database only",
    )
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
        storyboard_id = prepare_studio(settings, folder, scene_identities=args.scene_identities)
        app = create_app(settings)
        inner = app.app  # create_app wraps the FastAPI app in TrustedHostMiddleware
        inner.state.e2e_folder = folder.resolve()
        wire_agent_state_probe(inner)
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
