"""Restart the live studio gracefully, without the Owner (2026-10-12: «dai singur restart»).

1. Find the ``scripts\\start.py`` python process (the child of ``uv.exe``) and its console.
2. Attach to that console and send Ctrl+C: ``start.py`` asks the server for its clean stop
   (CTRL_BREAK to the server's group → the lifespan's ``request_shutdown`` → the day stops at
   its boundary, the GPU is verified off), stops the graphics, and exits. If nothing has ended
   after ``--break-after`` seconds, CTRL_BREAK is sent to the whole console as the fallback.
3. Wait until every studio python/uv process is gone (up to ``--wait`` seconds). The console
   window of an earlier self-start (``cmd /k``) outlives its python and keeps «start.py» in
   its command line: it is closed, not waited for.
4. Start again, detached, in a new visible console window, from the repo root.
5. Confirm the new process and ``/health/live``.

The day the restart cut off is resumed by the studio itself after the start
(``workflows.passes.resume_interrupted_day``); unfinished films are walked again by the
after-start passes. Nothing here buys, decides or touches the database.

Before running it: suites green and committed; ``date -u`` and a fresh look at the newest
events — no OPEN GPU session, no SUBMITTED take a worker already runs (a RunPod job queued
with no worker costs nothing to abandon). Windows only (console control events).

Usage: uv run --locked python scripts\\restart.py [--wait 600] [--break-after 90] [--dry-run]
"""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
HEALTH_URLS = (
    "http://127.0.0.1:8000/health/live",
    "http://127.0.0.1:8080/health/live",
    "http://127.0.0.1:8765/health/live",
)
START_COMMAND = "uv run --locked python scripts\\start.py"
CONSOLE_TITLE = "AMN-AI studio"
CTRL_C_EVENT, CTRL_BREAK_EVENT = 0, 1
#: A process of the studio: python.exe or uv.exe whose command line runs scripts\start.py.
STUDIO_IMAGES = ("python.exe", "uv.exe")


def studio_processes() -> list[dict]:
    """Every process whose command line runs ``scripts\\start.py`` (python, uv, old consoles)."""
    script = (
        "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and "
        "($_.CommandLine -match 'scripts.start\\.py') } | ForEach-Object { "
        "[pscustomobject]@{pid=$_.ProcessId; name=$_.Name; parent=$_.ParentProcessId; "
        "created=$_.CreationDate.ToString('yyyy-MM-dd HH:mm:ss'); cmd=$_.CommandLine} } "
        "| ConvertTo-Json -Compress"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True
    ).stdout.strip()
    if not out:
        return []
    data = json.loads(out)
    rows = data if isinstance(data, list) else [data]
    return [row for row in rows if int(row["pid"]) != 0]


def running(rows: list[dict]) -> list[dict]:
    return [row for row in rows if str(row["name"]).lower() in STUDIO_IMAGES]


def send_console_event(pid: int, event: int) -> bool:
    """A control event to the console of ``pid`` (attach, raise, detach).

    The event reaches every process on that console — this one included, once attached,
    whatever `SetConsoleCtrlHandler` says (2026-10-12 09:50: the restart died of its own
    Ctrl+C after the studio had received it, and nothing started the studio again). So the
    restart never calls this in its own process: `signal_from_a_child` runs it in a child."""
    kernel32 = ctypes.windll.kernel32
    kernel32.FreeConsole()
    if not kernel32.AttachConsole(pid):
        print(f"AttachConsole({pid}) failed: {kernel32.GetLastError()}")
        return False
    try:
        kernel32.SetConsoleCtrlHandler(None, True)
        ok = bool(kernel32.GenerateConsoleCtrlEvent(event, 0))
        time.sleep(0.5)
        return ok
    finally:
        kernel32.FreeConsole()


def signal_from_a_child(pid: int, event: str) -> None:
    """Send the console event from a child process of this script (``--signal``), so the
    event cannot end the restart itself; whether the studio heard it is read from the
    process list, not from the child's exit code."""
    result = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--signal", str(pid), event],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    said = (result.stdout or "").strip()
    if said:
        print(said)
    print(f"{event} sent to the console of {pid} (child exit {result.returncode})")


def health() -> dict | None:
    for url in HEALTH_URLS:
        try:
            with urllib.request.urlopen(url, timeout=5) as response:  # noqa: S310 - localhost
                return {"url": url, **json.loads(response.read().decode("utf-8"))}
        except Exception:  # noqa: BLE001 - not up yet
            continue
    return None


def stop(args: argparse.Namespace, before: list[dict]) -> int:
    pythons = [p for p in before if str(p["name"]).lower() == "python.exe"]
    uv_pids = {p["pid"] for p in before if str(p["name"]).lower() == "uv.exe"}
    # start.py is the python whose parent is uv.exe (the server is start.py's own child).
    target = next((p for p in pythons if p["parent"] in uv_pids), pythons[0])
    print("Ctrl+C to start.py pid", target["pid"], "started", target["created"])
    if args.dry_run:
        return 0
    signal_from_a_child(int(target["pid"]), "ctrl_c")
    deadline = time.monotonic() + args.wait
    broke = False
    started = time.monotonic()
    while time.monotonic() < deadline:
        left = running(studio_processes())
        if not left:
            break
        if not broke and time.monotonic() - started > args.break_after:
            print("still running after", args.break_after, "s: CTRL_BREAK to the console")
            signal_from_a_child(int(left[0]["pid"]), "ctrl_break")
            broke = True
        time.sleep(5)
    else:
        print("studio still running after", args.wait, "s:", running(studio_processes()))
        return 3
    print("stopped at", time.strftime("%H:%M:%S"))
    for shell in [p for p in studio_processes() if str(p["name"]).lower() == "cmd.exe"]:
        subprocess.run(["taskkill", "/PID", str(shell["pid"]), "/F"], capture_output=True)
        print("closed the old console", shell["pid"])
    return 0


def start() -> int:
    # A new, visible console on his desktop, independent of this process.
    launch = (
        "Start-Process -FilePath cmd -ArgumentList '/k','title "
        + CONSOLE_TITLE
        + " && "
        + START_COMMAND
        + "' -WorkingDirectory '"
        + str(REPO)
        + "'"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", launch], check=False)
    time.sleep(8)
    print("after:", json.dumps(running(studio_processes()), indent=1)[:1200])
    for _ in range(36):  # up to ~3 minutes: uv sync, the frontend, the server
        alive = health()
        if alive:
            print("health:", json.dumps(alive)[:300])
            return 0
        time.sleep(5)
    print("no /health/live answer within 3 minutes")
    return 4


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--wait", type=int, default=600, help="seconds to wait for the stop")
    parser.add_argument(
        "--break-after", type=int, default=90, help="seconds before CTRL_BREAK is also sent"
    )
    parser.add_argument("--dry-run", action="store_true", help="show what would be done")
    parser.add_argument(
        "--signal",
        nargs=2,
        metavar=("PID", "EVENT"),
        help="internal: send ctrl_c or ctrl_break to the console of PID and exit",
    )
    args = parser.parse_args()
    if sys.platform != "win32":
        print("Windows only: the studio is stopped with console control events.")
        return 5
    if args.signal:
        pid, event = int(args.signal[0]), str(args.signal[1]).lower()
        code = CTRL_BREAK_EVENT if event == "ctrl_break" else CTRL_C_EVENT
        return 0 if send_console_event(pid, code) else 2

    before = studio_processes()
    print("before:", json.dumps(before, indent=1)[:1500])
    if running(before):
        code = stop(args, before)
        if code:
            return code
    else:
        print("no running start.py process; starting fresh")
    if args.dry_run:
        return 0
    return start()


if __name__ == "__main__":
    sys.exit(main())
