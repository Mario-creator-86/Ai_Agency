"""The live headquarters optionally started with scripts/start.py --graphics.

The Owner's latest instruction, 2026-10-04, disables graphics on ordinary studio starts.
When explicitly enabled, graphics are Epic's signalling server (wilbur,
node.exe, streamer 8888 / player 8890) and Unreal streaming /Game/HQ/HQ_Dusk into it over Pixel
Streaming 2, with Remote Control on 127.0.0.1:30010. The studio relays the signalling and drives
the scene; the page draws its own building while there is no stream.

His rules, which every decision here follows:

* Never two streams. A stream left running (by start_live_hq.ps1, a rebuild, an earlier start)
  is adopted, not doubled; a second Unreal of the stream is stopped.
* Never his own editor or his programs. A process is the stream's only by name AND command line:
  UnrealEditor.exe with AMNReference.uproject and -PixelStreamingConnectionURL, node.exe with
  SignallingWebServer\\dist\\index.js and wilbur.config.json. (A bare command-line filter once
  matched the PowerShell running it and killed it.) A pid is checked again before it is stopped.
* While one of his games runs, or free commit is under 16 GB, the studio runs and the graphics
  wait, then start by themselves once no game has run for two checks and the memory is there
  (his card of 2026-10-03: «Singur, când închizi jocul»). Another Unreal working on the stream's
  project (a rebuild, the editor) holds the stream too.
* A stream that dies comes back after a growing pause, a bounded number of times per hour, under
  the same gates, saying why; never in a loop.
* Stop: Unreal, then wilbur; each asked to close, then ended after a short wait.

The decisions take a `System` (the machine) so that every one of them is tested on fakes; the
real machine is `WindowsSystem` (scripts/win_processes.py, ctypes).
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / "art-source" / "unreal" / "live"
#: The stream's command lines: start_live_hq.ps1 reads the same file (one list, never a copy).
STREAM_COMMAND = LIVE / "stream_command.json"
PATHS_FILE = ROOT / "art-source" / "unreal" / ".env.paths"
MACHINE_PATHS = ("AMN_PS_INFRA", "AMN_PS_NODE", "AMN_UE_ROOT")

UNREAL = "unreal"
WILBUR = "wilbur"
LABEL = {UNREAL: "Unreal", WILBUR: "wilbur"}
GIB = 1024**3

#: His games (2026-09-26). RiotClientServices runs all the time and is not a game.
GAME_PREFIXES = ("pathofexile", "league of legends", "leagueclient")

#: Remote Control's own clock: answers only when the streamed game runs and listens.
RC_PROBE = {
    "objectPath": "/Script/Engine.Default__GameplayStatics",
    "functionName": "GetTimeSeconds",
    "parameters": {"WorldContextObject": None},
}


@dataclass(frozen=True)
class Proc:
    pid: int
    name: str
    command_line: str


def _low(text: str) -> str:
    return text.replace("/", "\\").lower()


def is_stream_unreal(p: Proc) -> bool:
    command = _low(p.command_line)
    return (
        p.name.lower() == "unrealeditor.exe"
        and "amnreference.uproject" in command
        and "-pixelstreamingconnectionurl" in command
    )


def is_stream_wilbur(p: Proc) -> bool:
    command = _low(p.command_line)
    return (
        p.name.lower() == "node.exe"
        and "signallingwebserver\\dist\\index.js" in command
        and "wilbur.config.json" in command
    )


def is_project_unreal(p: Proc) -> bool:
    """Another Unreal on the stream's project (a rebuild's commandlet, the editor opened on
    AMNReference): the stream waits for it. His own project is not this one."""
    name = p.name.lower()
    return (
        name.startswith("unrealeditor")
        and name.endswith(".exe")
        and "amnreference.uproject" in _low(p.command_line)
        and not is_stream_unreal(p)
    )


def game_name(p: Proc) -> str | None:
    name = p.name.lower()
    if name.startswith(GAME_PREFIXES) and not name.startswith("riotclient"):
        return p.name.removesuffix(".exe").removesuffix(".EXE")
    return None


def wants_command_line(name: str) -> bool:
    """Only these names need their command line read to be told apart."""
    low = name.lower()
    return low == "node.exe" or low.startswith("unrealeditor")


# ------------------------------------------------------------------------- the command lines


def machine_paths(environ: Mapping[str, str], paths_file: Path = PATHS_FILE) -> dict[str, str]:
    """AMN_PS_INFRA, AMN_PS_NODE, AMN_UE_ROOT: the environment first, then the machine's
    art-source/unreal/.env.paths (KEY=VALUE, ignored by Git), as start_live_hq.ps1 reads them."""
    found = {key: environ[key] for key in MACHINE_PATHS if environ.get(key)}
    if paths_file.is_file():
        for line in paths_file.read_text(encoding="utf-8").splitlines():
            key, sep, value = line.strip().partition("=")
            key, value = key.strip(), value.strip().strip('"')
            if sep and key in MACHINE_PATHS and value and key not in found:
                found[key] = value
    return found


@dataclass(frozen=True)
class StreamSetup:
    unreal_exe: Path
    node_exe: Path
    wilbur_dir: Path
    unreal_command: str
    wilbur_command: str
    repo: Path


def load_stream_command(path: Path = STREAM_COMMAND) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def unreal_arguments(
    command: Mapping[str, Any],
    *,
    uproject: Path,
    streamer_port: str,
    res_x: int | None = None,
    res_y: int | None = None,
    windowed: bool = False,
) -> list[str]:
    values = {
        "streamer_port": str(streamer_port),
        "res_x": str(res_x or command["res_x"]),
        "res_y": str(res_y or command["res_y"]),
    }
    args = [f'"{uproject}"', str(command["map"])]
    for arg in command["unreal_args"]:
        for key, value in values.items():
            arg = arg.replace("{" + key + "}", value)
        args.append(arg)
    args += list(command["windowed_args" if windowed else "offscreen_args"])
    return args


def command_line(exe: Path, args: list[str]) -> str:
    """Exactly what Start-Process built: the exe quoted, then the arguments as written (each
    carries its own quotes). Unreal reads -ExecCmds="a b" only in that form."""
    return f'"{exe}" ' + " ".join(args)


def stream_setup(
    repo: Path = ROOT,
    environ: Mapping[str, str] | None = None,
    paths_file: Path | None = None,
) -> StreamSetup | str:
    """The two command lines on this machine, or one line saying what is missing."""
    live = repo / "art-source" / "unreal" / "live"
    paths = machine_paths(
        os.environ if environ is None else environ,
        paths_file or repo / "art-source" / "unreal" / ".env.paths",
    )
    missing = [key for key in MACHINE_PATHS if key not in paths]
    if missing:
        return (
            "căile mașinii nu sunt setate (" + ", ".join(missing) + ": variabile de mediu sau "
            "art-source/unreal/.env.paths)"
        )
    command = load_stream_command(live / "stream_command.json")
    config = json.loads((live / str(command["wilbur_config"])).read_text(encoding="utf-8"))
    infra = Path(paths["AMN_PS_INFRA"])
    node_exe = Path(paths["AMN_PS_NODE"]) / "node.exe"
    unreal_exe = Path(paths["AMN_UE_ROOT"]) / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
    wilbur_js = infra / Path(str(command["wilbur_script"]))
    wilbur_config = live / str(command["wilbur_config"])
    uproject = repo / Path(str(command["uproject"]))
    for needed in (node_exe, unreal_exe, wilbur_js, uproject):
        if not needed.is_file():
            return f"lipsește {needed}"
    wilbur = command_line(node_exe, [f'"{wilbur_js}"', "--config_file", f'"{wilbur_config}"'])
    unreal = command_line(
        unreal_exe,
        unreal_arguments(command, uproject=uproject, streamer_port=str(config["streamer_port"])),
    )
    return StreamSetup(
        unreal_exe=unreal_exe,
        node_exe=node_exe,
        wilbur_dir=infra / "SignallingWebServer",
        unreal_command=unreal,
        wilbur_command=wilbur,
        repo=repo,
    )


def skip_reason(
    *,
    no_graphics: bool,
    demo: bool,
    platform: str,
    session: int | None,
    signalling_url: str | None,
) -> str | None:
    """Why the graphics do not start with this studio, in one line for the Owner; None when
    they do."""
    if no_graphics:
        return "Grafica live nu pornește: ai cerut --no-graphics."
    if demo:
        return "Grafica live nu pornește în demo: pagina își desenează singură clădirea."
    if platform != "win32":
        return "Grafica live (Unreal) rulează doar pe Windows: pagina își desenează clădirea."
    if session == 0:
        # A Scheduled Task registered with -RunWhenLoggedOff (S4U) runs in session 0, which has
        # no desktop: Unreal has never been seen rendering there. The default, interactive task
        # runs in the Owner's own session; graphics still require an explicit --graphics.
        return (
            "Grafica live nu pornește în sesiunea 0 (serviciu fără utilizator conectat): "
            "Unreal nu are ecran acolo. Pornește studioul cu sarcina interactivă sau cu start.cmd."
        )
    if not signalling_url:
        return (
            "Grafica live nu pornește: pagina nu este legată de stream "
            "(STUDIO_OFFICE_STREAM_SIGNALLING_URL lipsește din .env)."
        )
    return None


# --------------------------------------------------------------------------- the supervisor


class System(Protocol):
    def processes(self) -> list[Proc]: ...
    def free_commit(self) -> int | None: ...
    def spawn(self, kind: str, command: str, cwd: Path) -> int: ...
    def assign(self, pid: int) -> bool: ...
    def post_close(self, pid: int) -> int: ...
    def kill(self, pid: int) -> bool: ...
    def wait_exit(self, pid: int, timeout: float) -> bool: ...
    def remote_control_answers(self) -> bool: ...


@dataclass(frozen=True)
class Policy:
    #: Unreal needs about 13 GB of commit within 25 s to start (machine note 2026-09-19).
    min_free_commit_bytes: int = 16 * GIB
    #: Checks in a row without a game before the graphics start.
    game_free_checks: int = 2
    check_seconds: float = 15.0
    ready_poll_seconds: float = 0.5
    #: The pause before the 1st, 2nd, 3rd... restart of a process that died within the hour.
    backoff_seconds: tuple[float, ...] = (30.0, 60.0, 120.0)
    max_restarts_per_hour: int = 3
    unreal_close_wait: float = 10.0
    wilbur_close_wait: float = 3.0
    #: A closing console gives start.py about five seconds in all: a fast stop asks and
    #: waits this long, and waits as long again after the kill.
    fast_close_wait: float = 0.5
    kill_wait: float = 5.0


HOUR = 3600.0


@dataclass
class _Kind:
    deaths: list[float] = field(default_factory=list)
    restarts: list[float] = field(default_factory=list)


class Supervisor:
    """Starts, adopts, restarts and stops the stream's two processes; one `check()` per pass."""

    def __init__(
        self,
        setup: StreamSetup,
        system: System,
        *,
        policy: Policy | None = None,
        say: Callable[[str], None] = print,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.setup = setup
        self.system = system
        self.policy = policy or Policy()
        self._say = say
        self.clock = clock
        self.owned: dict[str, int | None] = {UNREAL: None, WILBUR: None}
        self.history = {UNREAL: _Kind(), WILBUR: _Kind()}
        self.games_absent = self.policy.game_free_checks
        self.live_said = False
        self.stopped = False
        self.outside_job: set[int] = set()
        self._waiting: str | None = None
        self._lock = threading.RLock()

    def say(self, line: str) -> None:
        # A console being closed may refuse the line; the stop it reports must still happen.
        try:
            self._say(f"[grafica] {line}")
        except (OSError, ValueError):
            pass

    # ------------------------------------------------------------------------- one pass

    def check(self) -> None:
        with self._lock:
            if self.stopped:
                return
            procs = self.system.processes()
            now = self.clock()
            running = {
                UNREAL: [p.pid for p in procs if is_stream_unreal(p)],
                WILBUR: [p.pid for p in procs if is_stream_wilbur(p)],
            }
            self._notice_deaths(running, now)
            self._adopt(running)
            games = [g for g in (game_name(p) for p in procs) if g]
            self.games_absent = 0 if games else self.games_absent + 1
            self._start_missing(procs, games, now)
            probe = self.owned[UNREAL] if not self.live_said else None
        # Remote Control is asked outside the lock (up to 2 s): a stop is never kept waiting.
        if probe is not None and self.system.remote_control_answers():
            with self._lock:
                if self.owned[UNREAL] == probe and not self.live_said and not self.stopped:
                    self.live_said = True
                    self.say("Grafica e live: Unreal răspunde pe Remote Control (127.0.0.1:30010).")

    def _notice_deaths(self, running: dict[str, list[int]], now: float) -> None:
        for kind, pid in self.owned.items():
            if pid is not None and pid not in running[kind]:
                self.owned[kind] = None
                self.live_said = self.live_said and kind != UNREAL
                history = self.history[kind]
                history.deaths = [t for t in history.deaths if now - t < HOUR] + [now]
                recent = [t for t in history.restarts if now - t < HOUR]
                if len(recent) >= self.policy.max_restarts_per_hour:
                    self.say(f"{LABEL[kind]} s-a oprit singur (pid {pid}).")
                else:
                    self.say(
                        f"{LABEL[kind]} s-a oprit singur (pid {pid}); îl repornesc peste "
                        f"{self._backoff(kind):.0f} s, dacă jocurile și memoria permit."
                    )

    def _adopt(self, running: dict[str, list[int]]) -> None:
        adopted = []
        for kind in (UNREAL, WILBUR):
            pids = running[kind]
            if self.owned[kind] is None and pids:
                self.owned[kind] = pids[0]
                adopted.append(kind)
                if not self.system.assign(pids[0]):
                    self.outside_job.add(pids[0])
            for extra in pids:
                if extra != self.owned[kind]:
                    self._end(kind, extra, wait=self.policy.fast_close_wait)
                    self.say(
                        f"Un al doilea {LABEL[kind]} al streamului (pid {extra}) a fost oprit: "
                        "nu rulează niciodată două."
                    )
        if adopted:
            names = ", ".join(f"{LABEL[k]} pid {self.owned[k]}" for k in adopted)
            self.say(f"Grafica rula deja: o preiau ({names}); nu pornesc a doua.")
            outside = [self.owned[k] for k in adopted if self.owned[k] in self.outside_job]
            if outside:
                self.say(
                    f"Procesele {outside} nu au putut fi legate de start.py: le opresc eu la "
                    "Ctrl+C sau la închiderea ferestrei, dar dacă start.py e oprit forțat "
                    "rămân pornite."
                )

    def _backoff(self, kind: str) -> float:
        deaths = len(self.history[kind].deaths)
        steps = self.policy.backoff_seconds
        return steps[min(max(deaths - 1, 0), len(steps) - 1)]

    def _restart_allowed(self, kind: str, now: float) -> tuple[bool, str | None]:
        """A start after a death waits for its pause and for the hour's budget."""
        history = self.history[kind]
        history.deaths = [t for t in history.deaths if now - t < HOUR]
        history.restarts = [t for t in history.restarts if now - t < HOUR]
        if not history.deaths:
            return True, None
        if len(history.restarts) >= self.policy.max_restarts_per_hour:
            minutes = max(1, int((history.restarts[0] + HOUR - now) / 60) + 1)
            return False, (
                f"{LABEL[kind]} a căzut de {len(history.deaths)} ori în ultima oră: nu îl "
                f"mai repornesc în următoarele {minutes} minute; pagina își desenează clădirea."
            )
        if now < history.deaths[-1] + self._backoff(kind):
            return False, None
        return True, None

    def _gate(self, procs: list[Proc], games: list[str]) -> tuple[str, str] | None:
        """Why Unreal may not start now: (key, line), or None."""
        busy = [p.pid for p in procs if is_project_unreal(p)]
        if busy:
            return "project", (
                f"Un alt Unreal lucrează pe proiectul AMNReference (pid {busy[0]}: o reconstruire "
                "sau editorul): grafica așteaptă să termine și pornește singură."
            )
        if games or self.games_absent < self.policy.game_free_checks:
            game = games[0] if games else "jocul"
            return "game", (
                f"Rulează {game}: studioul e pornit, grafica așteaptă și pornește singură "
                "când închizi jocul."
            )
        free = self.system.free_commit()
        if free is not None and free < self.policy.min_free_commit_bytes:
            need = self.policy.min_free_commit_bytes / GIB
            return "memory", (
                f"Memorie liberă {free / GIB:.1f} GB, sub cei {need:.0f} GB de care are nevoie "
                "Unreal: grafica așteaptă și pornește singură când se eliberează."
            )
        return None

    def _wait(self, key: str | None, line: str | None) -> None:
        if key != self._waiting and line:
            self.say(line)
        self._waiting = key

    def _start_missing(self, procs: list[Proc], games: list[str], now: float) -> None:
        start: list[str] = []
        unreal_running = self.owned[UNREAL] is not None
        if not unreal_running:
            allowed, budget_line = self._restart_allowed(UNREAL, now)
            if not allowed:
                self._wait("budget:unreal" if budget_line else self._waiting, budget_line)
                return
            gate = self._gate(procs, games)
            if gate is not None:
                self._wait(*gate)
                return
            start.append(UNREAL)
        if self.owned[WILBUR] is None:
            allowed, budget_line = self._restart_allowed(WILBUR, now)
            if not allowed:
                self._wait("budget:wilbur" if budget_line else self._waiting, budget_line)
                return
            start.insert(0, WILBUR)
        self._waiting = None
        if not start:
            return
        started = []
        for kind in start:
            history = self.history[kind]
            restart = bool(history.deaths)
            try:
                pid = self._spawn(kind)
            except OSError as exc:
                # A start Windows refuses counts as a death: the same pause and hourly limit.
                history.deaths.append(now)
                if restart:
                    history.restarts.append(now)
                self.say(
                    f"Nu am putut porni {LABEL[kind]} ({exc}); reîncerc peste "
                    f"{self._backoff(kind):.0f} s."
                )
                break
            if restart:
                history.restarts.append(now)
            started.append(f"{LABEL[kind]} pid {pid}")
        if not started:
            return
        detail = ", ".join(started)
        if UNREAL in start and self.owned[UNREAL] is not None:
            self.say(f"Pornesc grafica ({detail}); imaginea apare în pagină în ~25 s.")
        else:
            self.say(f"Pornesc {detail}.")

    def _spawn(self, kind: str) -> int:
        if kind == UNREAL:
            pid = self.system.spawn(UNREAL, self.setup.unreal_command, self.setup.repo)
        else:
            pid = self.system.spawn(WILBUR, self.setup.wilbur_command, self.setup.wilbur_dir)
        self.owned[kind] = pid
        if not self.system.assign(pid):
            self.outside_job.add(pid)
            self.say(
                f"{LABEL[kind]} (pid {pid}) nu a putut fi legat de start.py: îl opresc eu la "
                "Ctrl+C sau la închiderea ferestrei, dar dacă start.py e oprit forțat "
                "rămâne pornit."
            )
        return pid

    # --------------------------------------------------------------------------- stopping

    def _end(self, kind: str, pid: int, *, wait: float, kill_wait: float | None = None) -> bool:
        """Ask, wait, then kill one process - only if it is still the stream's own."""
        is_kind = is_stream_unreal if kind == UNREAL else is_stream_wilbur
        current = {p.pid: p for p in self.system.processes()}
        if pid not in current or not is_kind(current[pid]):
            return False
        if self.system.post_close(pid) and self.system.wait_exit(pid, wait):
            return True
        self.system.kill(pid)
        self.system.wait_exit(pid, self.policy.kill_wait if kill_wait is None else kill_wait)
        return True

    def stop(self, *, fast: bool = False) -> list[str]:
        """Unreal, then wilbur: everything of the stream that runs, owned or started meanwhile.
        Returns what was stopped; says it in one line. Idempotent."""
        with self._lock:
            if self.stopped:
                return []
            self.stopped = True
            stopped: list[str] = []
            procs = self.system.processes()
            for kind in (UNREAL, WILBUR):
                is_kind = is_stream_unreal if kind == UNREAL else is_stream_wilbur
                pids = [self.owned[kind]] + [p.pid for p in procs if is_kind(p)]
                if fast:
                    wait = self.policy.fast_close_wait
                elif kind == UNREAL:
                    wait = self.policy.unreal_close_wait
                else:
                    wait = self.policy.wilbur_close_wait
                for pid in dict.fromkeys(p for p in pids if p is not None):
                    if self._end(kind, pid, wait=wait, kill_wait=wait if fast else None):
                        stopped.append(f"{LABEL[kind]} (pid {pid})")
                self.owned[kind] = None
            if stopped:
                self.say("Grafica oprită: " + ", ".join(stopped) + ".")
            return stopped

    # ------------------------------------------------------------------------------ loop

    def run(self, ready: Callable[[], bool], stop_event: threading.Event) -> None:
        """Wait until the studio answers, then check every `check_seconds` until stopped. A
        failing pass is said and the loop goes on: the studio never falls with its picture."""
        while not stop_event.is_set() and not ready():
            stop_event.wait(self.policy.ready_poll_seconds)
        while not stop_event.is_set():
            try:
                self.check()
            except Exception as exc:  # noqa: BLE001 - the studio must not fall with its picture
                self.say(f"Verificarea graficii a eșuat ({type(exc).__name__}: {exc}).")
            stop_event.wait(self.policy.check_seconds)


# ------------------------------------------------------------------------- the real machine


class WindowsSystem:
    """The supervisor's machine on Windows (scripts/win_processes.py)."""

    #: CREATE_NO_WINDOW: wilbur gets a console of its own without a window, so the studio's
    #: Ctrl+C and closed window reach start.py, which stops it in order, not wilbur at once.
    CREATE_NO_WINDOW = 0x08000000
    CREATE_NEW_PROCESS_GROUP = 0x00000200

    def __init__(self, job: Any = None, remote_control_url: str | None = None) -> None:
        import win_processes  # noqa: PLC0415 - Windows only, imported where it is used

        self.wp = win_processes
        self.job = job
        self.remote_control_url = (remote_control_url or "http://127.0.0.1:30010").rstrip("/")

    def processes(self) -> list[Proc]:
        return [Proc(*row) for row in self.wp.list_processes(wants_command_line)]

    def free_commit(self) -> int | None:
        free: int | None = self.wp.free_commit_bytes()
        return free

    def spawn(self, kind: str, command: str, cwd: Path) -> int:
        import subprocess  # noqa: PLC0415

        flags = self.CREATE_NEW_PROCESS_GROUP
        if kind == WILBUR:
            flags |= self.CREATE_NO_WINDOW
        # A string is handed to CreateProcess as it is: the quoting is the script's own.
        process = subprocess.Popen(  # noqa: S603
            command,
            cwd=str(cwd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        return int(process.pid)

    def assign(self, pid: int) -> bool:
        return bool(self.job is not None and self.job.assign(pid))

    def post_close(self, pid: int) -> int:
        return int(self.wp.post_close(pid))

    def kill(self, pid: int) -> bool:
        return bool(self.wp.kill(pid))

    def wait_exit(self, pid: int, timeout: float) -> bool:
        return bool(self.wp.wait_exit(pid, timeout))

    def remote_control_answers(self) -> bool:
        request = urllib.request.Request(
            f"{self.remote_control_url}/remote/object/call",
            data=json.dumps(RC_PROBE).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=2) as response:
                return bool(response.status == 200)
        except OSError:
            return False
