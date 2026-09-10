"""Prove the background worker fires the day on its own, in an isolated studio.

The tests drive the worker by hand. This script does what no test does: it starts the real
server process with the worker enabled, activates the daily schedule through the API the panel
uses, makes the slot due, and then waits — touching nothing — for a daily run to appear in the
studio's history. If one appears, the loop in `main.py` fired it.

The isolated studio has no language model, so the run it produces blocks at preflight. That is
the correct outcome, and the point of the exercise is unchanged: nobody pressed anything.

Why a separate database: the Owner's real studio has autonomy switched on, and a worker firing
there would begin a real day on the Owner's tokens.

    uv run python scripts/demo_worker.py [--keep-running]
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    port = free_port()
    workspace = Path(mkdtemp(prefix="amn-worker-"))
    database = workspace / "demo.db"
    token = secrets.token_urlsafe(48)
    env = {
        **os.environ,
        "STUDIO_OWNER_TOKEN": token,
        "STUDIO_DATABASE_URL": f"sqlite:///{database.as_posix()}",
        "STUDIO_PORT": str(port),
        "STUDIO_ALLOWED_HOSTS": '["localhost","127.0.0.1"]',
        "STUDIO_WORKER_ENABLED": "true",
        "STUDIO_WORKER_INTERVAL_SECONDS": "5",
    }
    print(f"Studio izolat in {workspace}")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/bootstrap.py")], cwd=ROOT, env=env, check=True
    )

    server = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts/run.py")],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    def call(path: str, body: dict | None = None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/v1{path}",
            data=data,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST" if body is not None else "GET",
        )
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read())

    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/health/live", timeout=2)
                break
            except OSError:
                time.sleep(0.5)
        else:
            raise SystemExit("The isolated studio did not come up.")

        jobs = call("/scheduler/jobs")
        daily = next(job for job in jobs if job["workflow_type"] == "DAILY_RUN")
        print(f"Job la pornire: {daily['name']}  activ={daily['is_active']}  (creat dormant)")

        # The Owner's two decisions, through the same API the panel uses.
        call(
            "/owner/autonomy-stop",
            {"command_id": str(uuid4()), "expected_version": 1, "stopped": False},
        )
        woken = call(
            f"/scheduler/jobs/{daily['id']}/active", {"command_id": str(uuid4()), "active": True}
        )
        print(f"Dupa activare: activ={woken['is_active']}  urmatoarea={woken['next_run_at'][:19]}")

        # Waking sets the clock a day out on purpose. The demo owns this database, so it moves the
        # slot into the past the way a night passing would.
        due = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE scheduled_job SET next_run_at = ? WHERE id = ?", (due, daily["id"])
            )
        print("Slotul a fost adus in trecut. Astept fara sa apas nimic...")

        run = None
        for _ in range(40):
            time.sleep(1)
            runs = call("/runbook/runs")["runs"]
            if runs:
                run = runs[0]
                break
        if run is None:
            raise SystemExit("Worker-ul nu a pornit nicio rulare in 40 de secunde.")

        print("")
        print(f"Rulare aparuta singura: {run['id'][:8]}  stare={run['status']}")
        print(f"Oprita la: {run.get('stopped_at_stage')}")
        after = next(job for job in call("/scheduler/jobs") if job["id"] == daily["id"])
        print(f"Jobul dupa: ultima={str(after['last_run_at'])[:19]}")
        print(f"            urmatoarea={after['next_run_at'][:19]}")
        print("")
        print(f"Owner token: {token}")
        print(f"Open http://127.0.0.1:{port} si apasa Rulare zilnica.")
        if args.keep_running:
            server.wait()
        return 0
    finally:
        if not args.keep_running:
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
