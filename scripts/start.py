"""One command to bring AMN-AI up: dependencies, database, frontend, server.

Run it with::

    start.cmd                      (Windows)
    uv run python scripts/start.py (any platform)
    uv run python scripts/start.py --demo   (the demo: simulated vendors, its own database)

Every step is idempotent, so this is also the normal way to restart after a code change.
The script refuses to start on a failed step rather than continuing with a half-built studio,
and it prints the studio's own preflight (read from its database, as the daily run reads it)
and which FFmpeg features a film would lose: it never claims a capability the machine does
not have.

Options:
    --skip-frontend   do not touch npm (use the already built frontend/dist)
    --skip-sync       do not run `uv sync` (use the current environment as-is)
    --rebuild         force a frontend rebuild even if it looks current
    --demo            start the demo studio (data/demo, port 8010): every vendor simulated,
                      nothing bought, nothing published (SELL-03, app.demo)
    --demo-dir PATH   where the demo's database, films and logs live
    --demo-port N     the demo's port (8010, so it never takes the studio's 8000)
    --no-graphics     do not start the live headquarters (wilbur + Unreal) with the studio

The live headquarters start with the studio (the Owner, 2026-10-04: «cand rulez python
start.py, trebuie sa porneasca si grafica. La fel, cand opresc, totul trebuie sa se
opreasca!»): once the server answers, scripts/live_graphics.py starts wilbur and Unreal (or
adopts the ones already running, never a second), waits while one of his games runs or memory
is short, and brings a dead one back a bounded number of times. Ctrl+C lets the server stop
cleanly first (its 30 s; a day stops at its boundary, never inside a purchase), then stops the
graphics. Everything this script starts is in a Windows Job Object that ends with it, so a
closed window or a killed start.py leaves nothing running.
"""

from __future__ import annotations

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import live_graphics
import win_processes

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DIST_INDEX = FRONTEND / "dist" / "index.html"
DEMO_DIR = ROOT / "data" / "demo"
DEMO_PORT = 8010

#: The FFmpeg filters a film uses, and what a film loses without each (SELL-18).
REQUIRED_FILTERS: dict[str, str] = {
    "subtitles": "subtitrările arse în imagine (libass)",
    "zscale": "conversia exactă a culorii la BT.709 (zimg)",
    "loudnorm": "nivelul sonor măsurat (-14 LUFS)",
    "xfade": "tranzițiile dintre scene",
    "drawtext": "textul cartoanelor",
    "zoompan": "mișcarea lentă a imaginilor fixe",
    "sidechaincompress": "coborârea muzicii sub voce",
    "silencedetect": "tăierea pauzelor din narațiune",
    "signalstats": "măsurarea imaginii (gradarea și controlul de montaj)",
}
#: The encoders the delivered file needs.
REQUIRED_ENCODERS: dict[str, str] = {
    "libx264": "codarea H.264 a filmului",
    "aac": "sunetul AAC al filmului",
}
INSTALL_FFMPEG = (
    "Instalează FFmpeg: Windows `winget install Gyan.FFmpeg` · Debian/Ubuntu "
    "`sudo apt install ffmpeg` · macOS `brew install ffmpeg`, sau setează STUDIO_FFMPEG_PATH "
    "în .env."
)


class StepFailed(RuntimeError):
    """A start-up step failed; the studio must not be reported as running."""


def say(message: str) -> None:
    print(f"\n=== {message}", flush=True)


def run(command: list[str], *, cwd: Path, step: str) -> None:
    """Run a command, streaming its output, and stop the launcher if it fails."""
    printable = " ".join(command)
    print(f"    $ {printable}", flush=True)
    try:
        result = subprocess.run(command, cwd=str(cwd), check=False)
    except FileNotFoundError as exc:
        raise StepFailed(
            f"{step}: '{command[0]}' was not found on PATH. Install it and try again."
        ) from exc
    if result.returncode != 0:
        raise StepFailed(f"{step}: `{printable}` exited with code {result.returncode}.")


def tool_path(name: str) -> str | None:
    """Locate an executable, tolerating Windows' .cmd/.exe shims."""
    return shutil.which(name)


def frontend_needs_build(force: bool) -> bool:
    if force or not DIST_INDEX.is_file():
        return True
    built_at = DIST_INDEX.stat().st_mtime
    sources = [FRONTEND / "index.html", *(FRONTEND / "src").rglob("*")]
    return any(p.is_file() and p.stat().st_mtime > built_at for p in sources)


def build_frontend(npm: str) -> None:
    """Build the page and record which sources it was built from (PAGE-01).

    The hash is taken before the build, from the sources the build reads, and written beside
    the bundle only once the build succeeded: the studio then compares it with the sources on
    disk and the page says when it is older than them."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.page_build import source_hash, write_build_record  # noqa: PLC0415

    built_from = source_hash(FRONTEND)
    run([npm, "run", "build"], cwd=FRONTEND, step="npm run build")
    write_build_record(FRONTEND, built_from)


def toolchain_paths(settings: Any) -> tuple[str | None, str | None]:
    """ffmpeg and ffprobe as the studio itself finds them: the settings (environment or
    .env), then PATH, then ffprobe beside ffmpeg. STUDIO_FFPROBE_PATH used to be read from
    the process environment only, while the preflight told the Owner to set it in .env."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.media.toolchain import find_ffmpeg, find_ffprobe  # noqa: PLC0415

    ffmpeg = find_ffmpeg(settings.ffmpeg_path)
    ffprobe = find_ffprobe(settings.ffmpeg_path, configured=settings.ffprobe_path)
    return ffmpeg, ffprobe


def has_encoder(ffmpeg: str | None, name: str) -> bool:
    """Whether this FFmpeg was built with the named encoder (asked once per name)."""
    if not ffmpeg:
        return False
    try:
        result = subprocess.run(  # noqa: S603 - argument list, no shell
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return any(
        len(parts) > 1 and parts[1] == name
        for parts in (line.split() for line in result.stdout.splitlines())
    )


def toolchain_report(
    ffmpeg: str | None,
    *,
    has_filter: Callable[[str | None, str], bool] | None = None,
    has_encoder: Callable[[str | None, str], bool] = has_encoder,
) -> list[str]:
    """What a film can and cannot be made with on this machine, one line each (Romanian)."""
    if not ffmpeg:
        return [
            "FFmpeg NU a fost găsit: studioul refuză să randeze (HTTP 503) și nu scrie niciun "
            "fișier fals în loc.",
            INSTALL_FFMPEG,
        ]
    if has_filter is None:
        sys.path.insert(0, str(ROOT / "backend"))
        from app.media.toolchain import has_filter as studio_has_filter  # noqa: PLC0415

        has_filter = studio_has_filter
    lost = [
        f"lipsește filtrul `{name}`: se pierde {what}"
        for name, what in REQUIRED_FILTERS.items()
        if not has_filter(ffmpeg, name)
    ] + [
        f"lipsește encoderul `{name}`: se pierde {what}"
        for name, what in REQUIRED_ENCODERS.items()
        if not has_encoder(ffmpeg, name)
    ]
    if not lost:
        return ["FFmpeg are toate filtrele și encoderele de care are nevoie un film."]
    return [*lost, INSTALL_FFMPEG + " O versiune completă (de ex. Gyan full) le are pe toate."]


def preflight_report(settings: Any | None = None) -> None:
    """State what is actually configured, read from the studio's own database the way the
    daily run reads it (runbook.preflight). Nothing here changes anything or calls a vendor."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import Settings  # noqa: PLC0415  (import after .env exists)

    settings = settings or Settings()  # type: ignore[call-arg]
    ffmpeg, ffprobe = toolchain_paths(settings)

    say("Verificare înainte de pornire")
    print(f"    Baza de date      : {settings.database_url}")
    print(f"    Adresa            : http://{settings.host}:{settings.port}")
    if getattr(settings, "demo_mode", False):
        print("    MOD DEMO          : furnizori simulați, nimic nu se publică sau se plătește.")
    print(f"    FFmpeg            : {ffmpeg or 'NEGĂSIT'}")
    print(f"    FFprobe           : {ffprobe or 'NEGĂSIT (controlul calității nu poate măsura)'}")
    for line in toolchain_report(ffmpeg):
        print(f"      - {line}")

    try:
        from app.db import create_db_engine  # noqa: PLC0415
        from app.integrations.vault import CredentialVault  # noqa: PLC0415
        from app.runbook.preflight import run_preflight  # noqa: PLC0415

        engine = create_db_engine(settings.database_url)
        try:
            vault = CredentialVault(Path(str(engine.url.database)).with_suffix(".credentials.key"))
            report = run_preflight(engine, settings, vault)
        finally:
            engine.dispose()
    except Exception as exc:  # noqa: BLE001 - the launcher reports, it does not stop here
        print(f"    Studioul nu a putut fi citit ({type(exc).__name__}); pornesc oricum.")
    else:
        print(f"    Starea zilei      : {report['status']} ({report['summary']})")
        for check in report["checks"]:
            if check["ok"]:
                continue
            mark = "OPRIT  " if check["severity"] == "BLOCKING" else "atenție"
            where = f" → {check['place_label']}" if check.get("place_label") else ""
            print(f"      [{mark}] {check['message']}{where}")
        print(
            "    Conturile se conectează din pagină: Setări → Furnizori AI (modelele de limbaj), "
            "Setări → Video și sunet (Runway, ElevenLabs), Setări → Conturi și e-mail (YouTube). "
            "Cheile stau criptate lângă baza de date, niciodată în .env."
        )

    print("\n    Cheia Proprietarului: în .env, la STUDIO_OWNER_TOKEN (o lipești la intrare).")


def demo_environment(demo_dir: Path, port: int) -> dict[str, str]:
    """The variables the demo's processes run with: its own database, films, backups, logs
    and port, and every switch that would reach the network off (app.demo reads them again)."""
    folder = demo_dir.resolve()
    if folder == (ROOT / "data").resolve() or folder == ROOT.resolve():
        raise SystemExit(
            "Demo-ul are nevoie de un folder al lui (implicit data/demo), nu de folderul "
            "studioului."
        )
    return {
        "STUDIO_DEMO_MODE": "true",
        "STUDIO_DATABASE_URL": f"sqlite:///{(demo_dir / 'demo.db').as_posix()}",
        "STUDIO_MEDIA_ROOT": str(demo_dir / "media"),
        "STUDIO_BACKUP_DIR": str(demo_dir / "backups"),
        "STUDIO_LOG_DIR": str(demo_dir / "logs"),
        "STUDIO_OFFICE_KEPT_FRAME_DIR": str(demo_dir / "office"),
        "STUDIO_PORT": str(port),
        "STUDIO_TRENDS_ENABLED": "false",
        "STUDIO_PROVIDER_CATALOG_REFRESH_ENABLED": "false",
    }


def prepare_demo() -> None:
    """Seed the demo studio (topic, source, workforce) once; it changes nothing after."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import Settings  # noqa: PLC0415
    from app.db import create_db_engine  # noqa: PLC0415
    from app.demo import prepare_demo_studio  # noqa: PLC0415

    settings = Settings()  # type: ignore[call-arg]
    engine = create_db_engine(settings.database_url)
    try:
        prepare_demo_studio(engine, settings)
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start AMN-AI (Autonomous Machine Nexus).")
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--demo", action="store_true", help="the demo, on simulated vendors")
    parser.add_argument("--demo-dir", type=Path, default=DEMO_DIR)
    parser.add_argument("--demo-port", type=int, default=DEMO_PORT)
    parser.add_argument(
        "--no-graphics",
        action="store_true",
        help="do not start the live headquarters (wilbur + Unreal) with the studio",
    )
    return parser


def utf8_console() -> None:
    """Print Romanian on any console: a redirected stdout (the Windows service writes it to a
    file) is cp1252 by default, which cannot encode ș or ț and would end the launcher."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


#: What the console-close handler needs alive for as long as the process lives.
_KEEP_ALIVE: list[Any] = []


def port_answers(host: str, port: int) -> bool:
    """Whether something already accepts connections on the studio's address."""
    target = "127.0.0.1" if host in ("", "0.0.0.0") else host  # noqa: S104 - a connect target
    try:
        with socket.create_connection((target, port), timeout=0.5):
            return True
    except OSError:
        return False


#: The server runs in a process group of its own, so the console's Ctrl+C reaches start.py
#: only. A second Ctrl+C reaching uvicorn while it waits for open connections (the page's
#: sockets) sets its force_exit and skips the lifespan shutdown, where the day stops at its
#: boundary (REL-10): seen on uvicorn 0.52.4, 2026-10-04. start.py asks the server once.
CREATE_NEW_PROCESS_GROUP = 0x00000200
#: How a server asked with CTRL_BREAK ends: uvicorn re-raises SIGBREAK after its clean stop and
#: the C runtime exits with 3; before uvicorn listens, Windows ends it with STATUS_CONTROL_C_EXIT.
STATUS_CONTROL_C_EXIT = 0xC000013A
STOPPED_BY_BREAK = frozenset({3, STATUS_CONTROL_C_EXIT})
#: start.py waits for the server in steps this long, so that its own Ctrl+C is seen.
WAIT_STEP_SECONDS = 0.5


def ask_server_to_stop(server: Any) -> bool:
    """Ask the server once for its clean stop: CTRL_BREAK to its own process group on Windows
    (uvicorn handles SIGBREAK like the first Ctrl+C), SIGINT elsewhere."""
    try:
        if sys.platform == "win32":
            os.kill(server.pid, signal.CTRL_BREAK_EVENT)
        else:
            server.send_signal(signal.SIGINT)
    except OSError:
        return False
    return True


def catch_ctrl_break() -> None:
    """Ctrl+Break is a Ctrl+C for start.py: by default it ends start.py at once, and its job
    would then end the server in the middle of its clean stop."""
    if sys.platform == "win32":
        signal.signal(signal.SIGBREAK, signal.default_int_handler)


def uninterrupted(step: Callable[[], Any]) -> Any:
    """Run a step of the stop to its end, however many Ctrl+C come meanwhile."""
    while True:
        try:
            return step()
        except KeyboardInterrupt:
            continue


def wait_for_server(server: Any, on_interrupt: Callable[[], None] = lambda: None) -> int:
    """Wait for the server to end, however many Ctrl+C come: each one calls `on_interrupt`
    (which asks the server once) and the wait goes on; the server stops cleanly in its own time
    (scripts/run.py, 30 s; a day stops at its boundary). subprocess.run used to kill it 0.25 s
    after the first Ctrl+C.

    The wait is taken in short steps: on Windows Popen.wait() without a timeout cannot be
    interrupted, so a Ctrl+C would only be seen once the server had ended - and the server,
    in its own process group, never gets one."""
    pending = False
    while True:
        try:
            if pending:
                pending = False
                on_interrupt()
            return int(server.wait(timeout=WAIT_STEP_SECONDS))
        except subprocess.TimeoutExpired:
            continue
        except KeyboardInterrupt:
            pending = True


def serve(
    command: list[str],
    *,
    graphics: Any = None,
    popen: Callable[..., Any] = subprocess.Popen,
    port_busy: Callable[[], bool] = lambda: False,
    port_open: Callable[[], bool] = lambda: True,
    assign: Callable[[int], Any] = lambda pid: None,
    install_close_handler: Callable[[Callable[[], None]], Any] = lambda callback: None,
    interrupt: Callable[[Any], bool] = ask_server_to_stop,
) -> int:
    """Run the server; beside it, once it answers, the graphics' supervisor. Stop order: the
    server (asked once by start.py at the first Ctrl+C), then the graphics (Unreal, then
    wilbur). From the first Ctrl+C on, the supervisor starts nothing more."""
    if graphics is not None and port_busy():
        print(
            "    [grafica] Adresa studioului răspunde deja (un alt studio pornit?): "
            "grafica nu este atinsă de această pornire.",
            flush=True,
        )
        graphics = None
    flags = CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    server = popen(command, cwd=str(ROOT), creationflags=flags)
    stop_event = threading.Event()
    state = {"told": False, "asked": False, "stopping": False}

    def interrupted() -> None:
        state["stopping"] = True
        stop_event.set()
        if not state["told"]:
            state["told"] = True
            print(
                "\n=== Oprire cerută: serverul se oprește curat (până la 30 s; o zi în lucru "
                "se oprește la granița ei, niciodată în mijlocul unei plăți), apoi grafica. "
                "Alte Ctrl+C nu îl grăbesc.",
                flush=True,
            )
        if not state["asked"]:
            state["asked"] = bool(interrupt(server))
            if not state["asked"]:
                print(
                    "    Nu am putut cere serverului oprirea; încerc din nou la următorul Ctrl+C.",
                    flush=True,
                )

    def window_closed() -> None:
        # Windows ends every process of a closing console within about five seconds, and the
        # server - which gets the same close - at once, without its clean stop: the graphics
        # go first, fast; the Job Object takes whatever is left when start.py ends.
        state["stopping"] = True
        stop_event.set()
        if graphics is not None:
            graphics.stop(fast=True)
        try:
            server.wait(timeout=2.5)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            pass

    thread = None
    try:
        try:
            assign(server.pid)
            _KEEP_ALIVE.append(install_close_handler(window_closed))
            if graphics is not None:
                thread = threading.Thread(
                    target=graphics.run,
                    args=(lambda: server.poll() is None and port_open(), stop_event),
                    name="live-graphics",
                    daemon=True,
                )
                thread.start()
        except KeyboardInterrupt:
            interrupted()
        code = wait_for_server(server, interrupted)
        # STATUS_CONTROL_C_EXIT: a console event ended it (a closed window reaches the server
        # first, sometimes before start.py's own handler runs): a stop, not a failed start.
        if code == STATUS_CONTROL_C_EXIT or (state["stopping"] and code in STOPPED_BY_BREAK):
            code = 0
        print(f"    Serverul studioului (pid {server.pid}) s-a oprit (cod {code}).", flush=True)
    finally:
        stop_event.set()
        if thread is not None:
            joining = thread
            uninterrupted(lambda: joining.join(timeout=30))
        if graphics is not None:
            uninterrupted(graphics.stop)
    return code


def prepare_graphics(args: argparse.Namespace, settings: Any, job: Any) -> Any:
    """The graphics' supervisor for this start, or None with one line saying why not."""
    reason = live_graphics.skip_reason(
        no_graphics=args.no_graphics,
        demo=args.demo,
        platform=sys.platform,
        session=win_processes.session_id(),
        signalling_url=getattr(settings, "office_stream_signalling_url", None),
    )
    setup: Any = None
    if reason is None:
        setup = live_graphics.stream_setup()
        if isinstance(setup, str):
            reason = f"Grafica live nu pornește: {setup}."
    if reason is not None:
        print(f"    [grafica] {reason}", flush=True)
        return None
    system = live_graphics.WindowsSystem(
        job=job, remote_control_url=getattr(settings, "office_unreal_remote_url", None)
    )
    return live_graphics.Supervisor(setup, system)


def tie_to_this_window() -> Any:
    """Everything start.py starts from here on lives in one Job Object that ends with it
    (closed window, killed start.py). start.py itself goes in, so its children and theirs are
    in from their first instruction; the job is never closed by hand (that would end start.py)."""
    job = win_processes.KillOnCloseJob.create()
    if job is None:
        if win_processes.WINDOWS:
            print("    Atenție: nu am putut lega procesele pornite de această fereastră.")
        return None
    if not job.assign_current():
        print(
            "    Atenție: start.py nu a putut intra în propriul job Windows; leg serverul și "
            "grafica unul câte unul.",
            flush=True,
        )
    _KEEP_ALIVE.append(job)
    return job


def main() -> int:
    utf8_console()
    args = build_parser().parse_args()
    catch_ctrl_break()
    job = tie_to_this_window()

    try:
        if args.demo:
            # Set before anything reads the settings: the bootstrap, the preflight and the
            # server all run on the demo's own folder from here on.
            os.environ.update(demo_environment(args.demo_dir, args.demo_port))
            args.demo_dir.mkdir(parents=True, exist_ok=True)
            say(f"MOD DEMO în {args.demo_dir} — furnizori simulați, nimic nu se publică")

        # 1. Python dependencies, exactly as locked.
        if args.skip_sync:
            say("Skipping dependency sync (--skip-sync)")
        elif tool_path("uv"):
            say("Syncing Python dependencies (uv sync --locked)")
            run(["uv", "sync", "--locked"], cwd=ROOT, step="Dependency sync")
        else:
            say("uv not found — using the current Python environment")
            print("    Install uv (https://docs.astral.sh/uv/) for a reproducible environment.")

        # 2. Database: .env, migrations, seed data. Idempotent.
        say("Preparing database and local credentials")
        run([sys.executable, str(ROOT / "scripts" / "bootstrap.py")], cwd=ROOT, step="Bootstrap")
        if args.demo:
            prepare_demo()

        # 3. Frontend bundle.
        if args.skip_frontend:
            say("Skipping frontend build (--skip-frontend)")
            if not DIST_INDEX.is_file():
                raise StepFailed(
                    "Frontend build skipped but frontend/dist/index.html does not exist."
                )
        elif not frontend_needs_build(args.rebuild):
            say("Frontend bundle is current — nothing to build")
        else:
            npm = tool_path("npm")
            if not npm:
                raise StepFailed(
                    "Frontend needs a build but npm was not found on PATH. Install Node.js, "
                    "or pass --skip-frontend to run the bundle that is already in frontend/dist."
                )
            if not (FRONTEND / "node_modules").is_dir():
                say("Installing frontend dependencies (npm ci)")
                run([npm, "ci"], cwd=FRONTEND, step="npm ci")
            say("Building frontend bundle (npm run build)")
            build_frontend(npm)

        # 4. Report the real state, then hand over to the server.
        preflight_report()

        sys.path.insert(0, str(ROOT / "backend"))
        from app.config import Settings  # noqa: PLC0415

        settings = Settings()  # type: ignore[call-arg]
        say("Starting the studio — press Ctrl+C to stop (the studio, then its graphics)")
        graphics = prepare_graphics(args, settings, job)
        server_command = [sys.executable, str(ROOT / "scripts" / "run.py")]
        print(f"    $ {' '.join(server_command)}", flush=True)
        code = serve(
            server_command,
            graphics=graphics,
            port_busy=lambda: port_answers(settings.host, settings.port),
            port_open=lambda: port_answers(settings.host, settings.port),
            assign=lambda pid: job.assign(pid) if job is not None else None,
            install_close_handler=win_processes.install_close_handler,
        )
        if code != 0:
            raise StepFailed(f"Server: `{' '.join(server_command)}` exited with code {code}.")
        print("\n=== Tot ce a pornit start.py este oprit.")

    except StepFailed as exc:
        print(f"\nSTART FAILED — {exc}", file=sys.stderr)
        print("The studio was not started.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
