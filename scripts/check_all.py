"""Run the README's verification chain on this machine, safely for a shared PC.

    uv run python scripts/check_all.py            # the whole chain, the full test suite
    uv run python scripts/check_all.py --quick    # pytest -m "not slow" (no film tests)
    uv run python scripts/check_all.py --dry-run  # print the plan and the machine checks

The chain: check_docs, check_secrets, ruff check, ruff format --check, mypy, pytest, the page's
type check and tests, and the page build into a scratch folder (never frontend/dist, which the
running studio serves).

Machine rules (the Owner's PC is shared with his programs and the live Unreal stream):
- it refuses to start with less than --min-free-gb of free commit (default 16 GB) or while a
  game runs (Path of Exile, League of Legends), and checks again right before pytest;
- pytest runs at Idle priority with its own short basetemp under .pytest_cache.

It prints one dated line at the end for docs/project/CURRENT_STATUS.md; it never writes a
document itself. Exit status 0 only when every step passed.
"""

import argparse
import ctypes
import datetime as dt
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIN_FREE_COMMIT_GB = 16.0
DEFAULT_BASETEMP = ".pytest_cache/basetemp_check_all"
#: Process names (lower case, without .exe) of the games the Owner may be playing.
GAME_PATTERNS = (
    re.compile(r"^pathofexile.*"),
    re.compile(r"^league of legends$"),
    re.compile(r"^leagueclient.*"),
)
IDLE_PRIORITY_CLASS = 0x00000040


@dataclass
class Step:
    name: str
    command: list[str]
    idle: bool = False
    #: Checked right before the step runs; a reason stops the chain there.
    guard: Callable[[], str | None] | None = None


@dataclass
class Outcome:
    name: str
    code: int
    seconds: float
    summary: str = ""
    refused: str | None = None

    @property
    def passed(self) -> bool:
        return self.code == 0 and self.refused is None


# ------------------------------------------------------------------------ the machine --


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def free_commit_gb() -> float | None:
    """Commit the machine can still hand out, in GB (Windows: available page file, the same
    number as Win32_OperatingSystem.FreeVirtualMemory; Linux: CommitLimit - Committed_AS)."""
    if sys.platform == "win32":
        status = _MemoryStatus()
        status.dwLength = ctypes.sizeof(_MemoryStatus)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return status.ullAvailPageFile / 1024**3
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="ascii").splitlines():
            name, _, rest = line.partition(":")
            values[name] = int(rest.split()[0])  # kB
        return (values["CommitLimit"] - values["Committed_AS"]) / 1024**2
    except (OSError, KeyError, ValueError, IndexError):
        return None


def running_process_names() -> list[str]:
    if sys.platform == "win32":
        listed = subprocess.run(
            ["tasklist", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        names = []
        for line in listed.stdout.splitlines():
            if line.startswith('"'):
                names.append(line.split('","', 1)[0].strip('"'))
        return names
    try:
        listed = subprocess.run(
            ["ps", "-eo", "comm="],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return []
    return [line.strip() for line in listed.stdout.splitlines() if line.strip()]


def games_running(names: Sequence[str]) -> list[str]:
    found = []
    for name in names:
        bare = name.lower().removesuffix(".exe")
        if any(pattern.match(bare) for pattern in GAME_PATTERNS):
            found.append(name)
    return sorted(set(found))


def machine_refusal(
    min_free_gb: float,
    *,
    free_gb: Callable[[], float | None] = free_commit_gb,
    processes: Callable[[], list[str]] = running_process_names,
) -> str | None:
    """Why the chain must not run now, or None."""
    games = games_running(processes())
    if games:
        return f"a game is running ({', '.join(games)}); try again when it is closed"
    free = free_gb()
    if free is not None and free < min_free_gb:
        return f"only {free:.1f} GB of free commit, under {min_free_gb:.0f} GB; wait and retry"
    return None


# -------------------------------------------------------------------------- the chain --


def plan(args: argparse.Namespace, build_dir: Path) -> list[Step]:
    python = sys.executable
    npm = shutil.which("npm") or "npm"
    pytest_command = [
        python,
        "-m",
        "pytest",
        "-q",
        f"--basetemp={args.basetemp}",
    ]
    if args.quick:
        pytest_command += ["-m", "not slow"]

    def before_pytest() -> str | None:
        return machine_refusal(args.min_free_gb)

    return [
        Step("check_docs", [python, "scripts/check_docs.py"]),
        Step("check_secrets", [python, "scripts/check_secrets.py"]),
        Step("ruff", [python, "-m", "ruff", "check", "."]),
        Step("ruff format", [python, "-m", "ruff", "format", "--check", "."]),
        Step("mypy", [python, "-m", "mypy"]),
        Step("pytest", pytest_command, idle=True, guard=before_pytest),
        Step("page check", [npm, "run", "check", "--prefix", "frontend"]),
        Step("page tests", [npm, "test", "--prefix", "frontend"]),
        Step(
            "page build",
            [
                npm,
                "run",
                "build",
                "--prefix",
                "frontend",
                "--",
                "--outDir",
                str(build_dir),
                "--emptyOutDir",
            ],
        ),
    ]


def _priority_options(idle: bool) -> dict[str, object]:
    if not idle:
        return {}
    if sys.platform == "win32":
        return {"creationflags": IDLE_PRIORITY_CLASS}
    return {"preexec_fn": lambda: os.nice(19)}


_PYTEST_TOTAL = re.compile(r"^=*\s*(\d+ (?:passed|failed|error).*?)\s*=*$")


def run_step(step: Step) -> Outcome:
    if step.guard is not None:
        refused = step.guard()
        if refused:
            return Outcome(step.name, 1, 0.0, refused=refused)
    print(f"\n=== {step.name}: {' '.join(step.command)}", flush=True)
    started = time.monotonic()
    last_total = ""
    with subprocess.Popen(  # noqa: S603 - argument list, no shell
        step.command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_priority_options(step.idle),
    ) as process:
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            total = _PYTEST_TOTAL.match(line.strip())
            if total:
                last_total = total.group(1)
        code = process.wait()
    return Outcome(step.name, code, time.monotonic() - started, summary=last_total)


def status_line(outcomes: Sequence[Outcome], *, when: dt.datetime, quick: bool) -> str:
    """The dated one-line result for CURRENT_STATUS."""
    verdict = "PASS" if outcomes and all(o.passed for o in outcomes) else "FAIL"
    parts = []
    for outcome in outcomes:
        if outcome.refused:
            parts.append(f"{outcome.name} REFUSED ({outcome.refused})")
            continue
        state = "ok" if outcome.code == 0 else f"FAILED (exit {outcome.code})"
        detail = f": {outcome.summary}" if outcome.summary else ""
        parts.append(f"{outcome.name} {state}{detail} in {outcome.seconds:.0f} s")
    lane = "quick lane (-m 'not slow')" if quick else "full suite"
    return f"{when:%Y-%m-%d %H:%M} check_all {verdict}, {lane}: " + "; ".join(parts) + "."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true", help="pytest -m 'not slow'")
    parser.add_argument("--min-free-gb", type=float, default=MIN_FREE_COMMIT_GB)
    parser.add_argument("--basetemp", default=DEFAULT_BASETEMP)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    refused = machine_refusal(args.min_free_gb)
    if refused:
        print(f"check_all will not start: {refused}.")
        return 2
    with tempfile.TemporaryDirectory(prefix="amn_page_build_") as build_dir:
        steps = plan(args, Path(build_dir))
        if args.dry_run:
            for step in steps:
                note = " (Idle priority)" if step.idle else ""
                print(f"{step.name}{note}: {' '.join(step.command)}")
            return 0
        outcomes = []
        for step in steps:
            outcome = run_step(step)
            outcomes.append(outcome)
            if outcome.refused:
                break
    line = status_line(outcomes, when=dt.datetime.now(), quick=args.quick)
    print("\n" + line)
    return 0 if all(o.passed for o in outcomes) and len(outcomes) == len(steps) else 1


if __name__ == "__main__":
    sys.exit(main())
