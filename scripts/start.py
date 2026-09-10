"""One command to bring AMN-AI up: dependencies, database, frontend, server.

Run it with::

    start.cmd                      (Windows)
    uv run python scripts/start.py (any platform)

Every step is idempotent, so this is also the normal way to restart after a code change.
The script refuses to start on a failed step rather than continuing with a half-built studio,
and it prints a preflight report stating exactly which integrations are configured — it never
claims a capability the environment does not have.

Options:
    --skip-frontend   do not touch npm (use the already built frontend/dist)
    --skip-sync       do not run `uv sync` (use the current environment as-is)
    --rebuild         force a frontend rebuild even if it looks current
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DIST_INDEX = FRONTEND / "dist" / "index.html"


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


def preflight_report() -> None:
    """State what is actually configured. No step here changes anything."""
    sys.path.insert(0, str(ROOT / "backend"))
    from app.config import Settings  # noqa: PLC0415  (import after .env exists)

    settings = Settings()  # type: ignore[call-arg]

    ffmpeg = settings.ffmpeg_path or tool_path("ffmpeg")
    ffprobe = os.environ.get("STUDIO_FFPROBE_PATH") or tool_path("ffprobe")

    say("Preflight")
    print(f"    Database          : {settings.database_url}")
    print(f"    Listening on      : http://{settings.host}:{settings.port}")

    if ffmpeg:
        print(f"    Video encoder     : ffmpeg at {ffmpeg}")
    else:
        print("    Video encoder     : NOT FOUND — rendering returns HTTP 503.")
        print("                        Install ffmpeg or set STUDIO_FFMPEG_PATH in .env.")
        print("                        The studio does not write a placeholder file instead.")

    if not ffprobe:
        print("    Media inspection  : ffprobe NOT FOUND — quality control cannot measure a")
        print("                        render, so every QC report will FAIL. Install ffmpeg.")

    if settings.youtube_credentials_present:
        print("    YouTube publishing: credentials present (official API will be used).")
    else:
        print("    YouTube publishing: DISABLED — no credentials. Publishing endpoints return")
        print("                        HTTP 503. Set STUDIO_YOUTUBE_CLIENT_ID,")
        print("                        STUDIO_YOUTUBE_CLIENT_SECRET and")
        print("                        STUDIO_YOUTUBE_REFRESH_TOKEN in .env to enable it.")
        print("                        Nothing is simulated in their absence.")

    print("\n    Owner key: in .env, at STUDIO_OWNER_TOKEN (paste it on the login screen).")


def main() -> int:
    parser = argparse.ArgumentParser(description="Start AMN-AI (Autonomous Machine Nexus).")
    parser.add_argument("--skip-frontend", action="store_true")
    parser.add_argument("--skip-sync", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()

    try:
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
            run([npm, "run", "build"], cwd=FRONTEND, step="npm run build")

        # 4. Report the real state, then hand over to the server.
        preflight_report()

        say("Starting the studio — press Ctrl+C to stop")
        run([sys.executable, str(ROOT / "scripts" / "run.py")], cwd=ROOT, step="Server")

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
