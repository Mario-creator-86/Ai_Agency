"""start.py starts the studio AND its graphics, and stopping it stops everything (2026-10-04).

The Owner's words: «cand rulez python start.py, trebuie sa porneasca si grafica. La fel, cand
opresc, totul trebuie sa se opreasca!» The graphics are the live streamed headquarters: Epic's
signalling server (wilbur, node.exe) and Unreal streaming /Game/HQ/HQ_Dusk. Every process here
is faked: no Unreal, node or PowerShell runs in these tests, and nothing reaches a socket.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest
from app.config import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
import live_graphics as lg  # noqa: E402
import start  # noqa: E402

sys.path.remove(str(ROOT / "scripts"))

GIB = 1024**3

HIS_EDITOR = lg.Proc(
    501,
    "UnrealEditor.exe",
    r'"E:\Program Files\Epic Games\UE_5.8\Engine\Binaries\Win64\UnrealEditor.exe" '
    r'"C:\Users\mario\OneDrive\Documents\Unreal Projects\AMN_AI\AMN_AI.uproject"',
)
#: A shell whose command line names everything the stream's do (it once matched a bare
#: command-line filter and was killed): never the stream's, whatever its text says.
SHELL = lg.Proc(
    502,
    "powershell.exe",
    "powershell -c Get-CimInstance | ? CommandLine -match 'AMNReference.uproject "
    "-PixelStreamingConnectionURL SignallingWebServer\\dist\\index.js wilbur.config.json'",
)


# ------------------------------------------------------------------------------- the machine


def machine(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    """A fake machine: the repository's stream files and the three installed folders."""
    repo = tmp_path / "repo"
    live = repo / "art-source" / "unreal" / "live"
    live.mkdir(parents=True, exist_ok=True)
    (live / "wilbur.config.json").write_text(
        (ROOT / "art-source/unreal/live/wilbur.config.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (live / "stream_command.json").write_text(
        lg.STREAM_COMMAND.read_text(encoding="utf-8"), encoding="utf-8"
    )
    project = repo / "art-source" / "unreal" / "AMNReference"
    project.mkdir(parents=True, exist_ok=True)
    (project / "AMNReference.uproject").write_text("{}", encoding="utf-8")
    infra = tmp_path / "infra"
    (infra / "SignallingWebServer" / "dist").mkdir(parents=True, exist_ok=True)
    (infra / "SignallingWebServer" / "dist" / "index.js").write_text("", encoding="utf-8")
    node = tmp_path / "node"
    node.mkdir(exist_ok=True)
    (node / "node.exe").write_text("", encoding="utf-8")
    ue = tmp_path / "UE_5.8"
    (ue / "Engine" / "Binaries" / "Win64").mkdir(parents=True, exist_ok=True)
    (ue / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe").write_text("", encoding="utf-8")
    env = {"AMN_PS_INFRA": str(infra), "AMN_PS_NODE": str(node), "AMN_UE_ROOT": str(ue)}
    return repo, env


def setup_for(tmp_path: Path) -> lg.StreamSetup:
    repo, env = machine(tmp_path)
    setup = lg.stream_setup(repo, env)
    assert isinstance(setup, lg.StreamSetup), setup
    return setup


class FakeSystem:
    """The machine as the supervisor sees it; records every act."""

    def __init__(self, procs=(), free_gb: float = 30.0) -> None:
        self.procs: list[lg.Proc] = list(procs)
        self.free: int | None = int(free_gb * GIB)
        self.calls: list[tuple] = []
        self.next_pid = 1000
        self.assign_ok = True
        self.windows: dict[int, int] = {}
        self.closes_on_request = True
        self.rc = False

    def pids(self) -> set[int]:
        return {p.pid for p in self.procs}

    def processes(self) -> list[lg.Proc]:
        return list(self.procs)

    def free_commit(self) -> int | None:
        return self.free

    def spawn(self, kind: str, command: str, cwd: Path) -> int:
        pid = self.next_pid
        self.next_pid += 1
        name = "UnrealEditor.exe" if kind == lg.UNREAL else "node.exe"
        self.procs.append(lg.Proc(pid, name, command))
        self.calls.append(("spawn", kind, pid))
        return pid

    def assign(self, pid: int) -> bool:
        self.calls.append(("assign", pid))
        return self.assign_ok

    def post_close(self, pid: int) -> int:
        self.calls.append(("close", pid))
        count = self.windows.get(pid, 0)
        if count and self.closes_on_request:
            self.die(pid)
        return count

    def kill(self, pid: int) -> bool:
        self.calls.append(("kill", pid))
        self.die(pid)
        return True

    def wait_exit(self, pid: int, timeout: float) -> bool:
        self.calls.append(("wait", pid, timeout))
        return pid not in self.pids()

    def remote_control_answers(self) -> bool:
        return self.rc

    def die(self, pid: int) -> None:
        self.procs = [p for p in self.procs if p.pid != pid]

    def spawned(self) -> list[str]:
        return [c[1] for c in self.calls if c[0] == "spawn"]


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def supervisor(tmp_path, system, **policy) -> tuple[lg.Supervisor, list[str], Clock]:
    lines: list[str] = []
    clock = Clock()
    sup = lg.Supervisor(
        setup_for(tmp_path), system, policy=lg.Policy(**policy), say=lines.append, clock=clock
    )
    return sup, lines, clock


def stream_unreal(setup: lg.StreamSetup, pid: int) -> lg.Proc:
    return lg.Proc(pid, "UnrealEditor.exe", setup.unreal_command)


def stream_wilbur(setup: lg.StreamSetup, pid: int) -> lg.Proc:
    return lg.Proc(pid, "node.exe", setup.wilbur_command)


# ------------------------------------------------------------- which processes are the stream's


def test_the_streams_processes_are_known_by_name_and_command_line(tmp_path):
    setup = setup_for(tmp_path)
    assert lg.is_stream_unreal(stream_unreal(setup, 1))
    assert lg.is_stream_wilbur(stream_wilbur(setup, 2))
    # his own editor, on his own project, is never the stream's
    assert not lg.is_stream_unreal(HIS_EDITOR)
    assert not lg.is_project_unreal(HIS_EDITOR)
    # a shell quoting every pattern is not the stream's (name AND command line)
    assert not lg.is_stream_unreal(SHELL) and not lg.is_stream_wilbur(SHELL)
    assert not lg.is_project_unreal(SHELL)
    # another node program is not wilbur
    assert not lg.is_stream_wilbur(
        lg.Proc(3, "node.exe", '"node" "C:\\x\\@playwright\\mcp\\cli.js"')
    )


def test_another_unreal_on_the_streams_project_is_a_rebuild_not_the_stream():
    rebuild = lg.Proc(
        7,
        "UnrealEditor-Cmd.exe",
        r'"E:\UE\UnrealEditor-Cmd.exe" '
        r'"E:\repo\art-source\unreal\AMNReference\AMNReference.uproject"'
        r" -run=pythonscript -script=build_hq_scene.py",
    )
    assert lg.is_project_unreal(rebuild)
    assert not lg.is_stream_unreal(rebuild)


@pytest.mark.parametrize(
    "name, game",
    [
        ("PathOfExile_x64.exe", True),
        ("PathOfExileSteam.exe", True),
        ("League of Legends.exe", True),
        ("LeagueClient.exe", True),
        ("LeagueClientUx.exe", True),
        ("RiotClientServices.exe", False),
        ("pycharm64.exe", False),
    ],
)
def test_his_games(name, game):
    assert (lg.game_name(lg.Proc(9, name, "")) is not None) is game


# ------------------------------------------------------------ one command line, never forked


def test_the_unreal_command_line_is_the_one_start_live_hq_ps1_always_ran(tmp_path):
    setup = setup_for(tmp_path)
    repo = tmp_path / "repo"
    uproject = repo / "art-source" / "unreal" / "AMNReference" / "AMNReference.uproject"
    exe = tmp_path / "UE_5.8" / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe"
    # The command line the script built before the argument list moved to stream_command.json.
    legacy = (
        f'"{exe}" "{uproject}" /Game/HQ/HQ_Dusk -game '
        "-PixelStreamingConnectionURL=ws://127.0.0.1:8888 -PixelStreamingWebRTCNegotiateCodecs "
        "-RCWebControlEnable -PixelStreamingWebRTCStartBitrate=40000000 "
        "-PixelStreamingWebRTCMaxBitrate=100000000 -PixelStreamingWebRTCMinBitrate=20000000 "
        '-PixelStreamingEncoderMaxQP=18 -ExecCmds="DisableAllScreenMessages,'
        "sg.ViewDistanceQuality 4,sg.AntiAliasingQuality 4,sg.ShadowQuality 4,"
        "sg.GlobalIlluminationQuality 4,sg.ReflectionQuality 4,sg.PostProcessQuality 4,"
        "sg.TextureQuality 4,sg.EffectsQuality 4,sg.FoliageQuality 4,sg.ShadingQuality 4,"
        "r.Tonemapper.Sharpen 0.6,r.ScreenPercentage 150,r.MotionBlurQuality 0,"
        "PixelStreaming.Encoder.MaxQP 18,PixelStreaming.WebRTC.MaxBitrate 100000000,"
        "PixelStreaming.WebRTC.StartBitrate 40000000,PixelStreaming.WebRTC.MinBitrate 20000000"
        '" -ResX=1920 -ResY=1008 -ForceRes -nosplash -unattended -RenderOffScreen'
    )
    assert setup.unreal_command == legacy
    infra = tmp_path / "infra"
    config = repo / "art-source" / "unreal" / "live" / "wilbur.config.json"
    assert setup.wilbur_command == (
        f'"{tmp_path / "node" / "node.exe"}" '
        f'"{infra / "SignallingWebServer" / "dist" / "index.js"}" --config_file "{config}"'
    )
    assert setup.wilbur_dir == infra / "SignallingWebServer"


def test_the_powershell_script_reads_the_same_argument_list():
    script = (ROOT / "art-source/unreal/live/start_live_hq.ps1").read_text(encoding="utf-8")
    assert "stream_command.json" in script
    # no argument of the list is written into the script any more
    assert "PixelStreamingWebRTCNegotiateCodecs" not in script
    assert "sg.ViewDistanceQuality" not in script


def test_machine_paths_come_from_the_environment_first_then_the_paths_file(tmp_path):
    paths = tmp_path / ".env.paths"
    paths.write_text(
        '# comment\nAMN_PS_INFRA="D:\\infra"\nAMN_PS_NODE=D:\\node\nAMN_UE_ROOT=D:\\ue\n',
        encoding="utf-8",
    )
    found = lg.machine_paths({"AMN_UE_ROOT": "E:\\UE"}, paths)
    assert found == {
        "AMN_PS_INFRA": "D:\\infra",
        "AMN_PS_NODE": "D:\\node",
        "AMN_UE_ROOT": "E:\\UE",
    }


def test_a_machine_without_the_paths_gets_one_line_naming_what_is_missing(tmp_path):
    repo, env = machine(tmp_path)
    reason = lg.stream_setup(repo, {"AMN_PS_INFRA": env["AMN_PS_INFRA"]}, tmp_path / "none")
    assert isinstance(reason, str)
    assert "AMN_PS_NODE" in reason and "AMN_UE_ROOT" in reason
    (tmp_path / "UE_5.8" / "Engine" / "Binaries" / "Win64" / "UnrealEditor.exe").unlink()
    reason = lg.stream_setup(repo, env)
    assert isinstance(reason, str) and "UnrealEditor.exe" in reason


# --------------------------------------------------------------------- when the graphics skip


def test_the_graphics_start_by_default_and_skip_with_one_romanian_line():
    ok = {
        "no_graphics": False,
        "demo": False,
        "platform": "win32",
        "session": 1,
        "signalling_url": "ws://127.0.0.1:8890",
    }
    assert lg.skip_reason(**ok) is None
    for change, word in [
        ({"no_graphics": True}, "--no-graphics"),
        ({"demo": True}, "demo"),
        ({"platform": "linux"}, "Windows"),
        ({"session": 0}, "sesiunea 0"),
        ({"signalling_url": None}, "STUDIO_OFFICE_STREAM_SIGNALLING_URL"),
    ]:
        line = lg.skip_reason(**{**ok, **change})
        assert line and word in line and "\n" not in line
        assert "grafica" in line.lower()


def test_start_offers_no_graphics():
    parser = start.build_parser()
    assert parser.parse_args(["--no-graphics"]).no_graphics is True
    assert parser.parse_args([]).no_graphics is False


# ------------------------------------------------------------------------------- starting


def test_a_free_machine_starts_wilbur_then_unreal_and_ties_both_to_start_py(tmp_path):
    system = FakeSystem()
    sup, lines, _ = supervisor(tmp_path, system)
    sup.check()
    assert system.spawned() == [lg.WILBUR, lg.UNREAL]
    wilbur_pid, unreal_pid = 1000, 1001
    assert ("assign", wilbur_pid) in system.calls and ("assign", unreal_pid) in system.calls
    assert sup.owned == {lg.UNREAL: unreal_pid, lg.WILBUR: wilbur_pid}
    assert any("Pornesc grafica" in line for line in lines)
    # the next check starts nothing more
    sup.check()
    assert system.spawned() == [lg.WILBUR, lg.UNREAL]


def test_the_stream_answering_is_said_once(tmp_path):
    system = FakeSystem()
    sup, lines, _ = supervisor(tmp_path, system)
    sup.check()
    system.rc = True
    sup.check()
    sup.check()
    assert sum("live" in line for line in lines) == 1


def test_left_over_stream_processes_are_adopted_never_a_second_one(tmp_path):
    setup = setup_for(tmp_path)
    system = FakeSystem([stream_unreal(setup, 77), stream_wilbur(setup, 78), HIS_EDITOR])
    sup, lines, _ = supervisor(tmp_path, system)
    sup.check()
    assert system.spawned() == []
    assert sup.owned == {lg.UNREAL: 77, lg.WILBUR: 78}
    assert ("assign", 77) in system.calls and ("assign", 78) in system.calls
    assert any("preiau" in line for line in lines)


def test_a_second_stream_unreal_is_stopped_and_his_editor_is_never_touched(tmp_path):
    setup = setup_for(tmp_path)
    system = FakeSystem(
        [stream_unreal(setup, 77), stream_unreal(setup, 79), stream_wilbur(setup, 78), HIS_EDITOR]
    )
    sup, lines, _ = supervisor(tmp_path, system)
    sup.check()
    assert system.spawned() == []
    assert 79 not in system.pids() and 77 in system.pids()
    assert HIS_EDITOR.pid in system.pids()
    touched = {c[1] for c in system.calls if c[0] in ("close", "kill")}
    assert HIS_EDITOR.pid not in touched and SHELL.pid not in touched


def test_an_adopted_process_outside_the_job_is_said_and_kept(tmp_path):
    setup = setup_for(tmp_path)
    system = FakeSystem([stream_unreal(setup, 77), stream_wilbur(setup, 78)])
    system.assign_ok = False
    sup, lines, _ = supervisor(tmp_path, system)
    sup.check()
    assert sup.owned == {lg.UNREAL: 77, lg.WILBUR: 78}
    assert any("start.py" in line and "forțat" in line for line in lines)


def test_unreal_without_wilbur_gets_only_wilbur(tmp_path):
    setup = setup_for(tmp_path)
    system = FakeSystem([stream_unreal(setup, 77)])
    sup, _, _ = supervisor(tmp_path, system)
    sup.check()
    assert system.spawned() == [lg.WILBUR]


# ------------------------------------------------------------------------------ the gates


def test_while_he_plays_the_studio_runs_and_the_graphics_wait_two_game_free_checks(tmp_path):
    game = lg.Proc(300, "PathOfExile_x64.exe", "")
    system = FakeSystem([game, lg.Proc(301, "RiotClientServices.exe", "")])
    sup, lines, _ = supervisor(tmp_path, system)
    sup.check()
    sup.check()
    assert system.spawned() == []
    waiting = [line for line in lines if "PathOfExile" in line]
    assert len(waiting) == 1 and "singur" in waiting[0]
    system.die(300)
    sup.check()  # the first check without a game
    assert system.spawned() == []
    sup.check()  # the second
    assert system.spawned() == [lg.WILBUR, lg.UNREAL]


def test_riot_client_services_alone_is_not_a_game(tmp_path):
    system = FakeSystem([lg.Proc(301, "RiotClientServices.exe", "")])
    sup, _, _ = supervisor(tmp_path, system)
    sup.check()
    assert system.spawned() == [lg.WILBUR, lg.UNREAL]


def test_under_16_gb_of_free_commit_the_graphics_wait_and_start_by_themselves(tmp_path):
    system = FakeSystem(free_gb=12.0)
    sup, lines, _ = supervisor(tmp_path, system)
    sup.check()
    sup.check()
    assert system.spawned() == []
    assert sum("16 GB" in line for line in lines) == 1
    system.free = 20 * GIB
    sup.check()
    assert system.spawned() == [lg.WILBUR, lg.UNREAL]


def test_a_rebuild_on_the_project_holds_the_stream(tmp_path):
    rebuild = lg.Proc(
        7,
        "UnrealEditor-Cmd.exe",
        r'"E:\UE\UnrealEditor-Cmd.exe" "E:\r\AMNReference\AMNReference.uproject" -run=x',
    )
    system = FakeSystem([rebuild])
    sup, lines, _ = supervisor(tmp_path, system)
    sup.check()
    assert system.spawned() == []
    assert any("AMNReference" in line for line in lines)
    system.die(7)
    sup.check()
    assert system.spawned() == [lg.WILBUR, lg.UNREAL]


# ------------------------------------------------------------------------- keeping it up


def test_a_dead_unreal_comes_back_after_a_backoff_and_never_in_a_loop(tmp_path):
    system = FakeSystem()
    sup, lines, clock = supervisor(
        tmp_path, system, backoff_seconds=(30.0, 60.0, 120.0), max_restarts_per_hour=3
    )
    sup.check()
    restarts = 0
    for backoff in (30.0, 60.0, 120.0):
        system.die(sup.owned[lg.UNREAL])
        sup.check()  # sees the death, does not restart at once
        assert system.spawned().count(lg.UNREAL) == 1 + restarts
        assert any("s-a oprit" in line for line in lines)
        clock.now += backoff - 1
        sup.check()
        assert system.spawned().count(lg.UNREAL) == 1 + restarts
        clock.now += 2
        sup.check()
        restarts += 1
        assert system.spawned().count(lg.UNREAL) == 1 + restarts
    # the fourth death in the hour: no more restarts, said once
    system.die(sup.owned[lg.UNREAL])
    for _ in range(5):
        clock.now += 300
        sup.check()
    assert system.spawned().count(lg.UNREAL) == 4
    assert sum("ultima oră" in line for line in lines) == 1
    # an hour after those restarts, it may try again
    clock.now += 3600
    sup.check()
    assert system.spawned().count(lg.UNREAL) == 5
    assert system.spawned().count(lg.WILBUR) == 1


def test_a_restart_waits_for_the_same_gates(tmp_path):
    system = FakeSystem()
    sup, _, clock = supervisor(tmp_path, system)
    sup.check()
    system.die(sup.owned[lg.UNREAL])
    system.procs.append(lg.Proc(300, "League of Legends.exe", ""))
    sup.check()
    clock.now += 600
    sup.check()
    assert system.spawned().count(lg.UNREAL) == 1


def test_a_start_windows_refuses_is_retried_after_a_pause_not_every_check(tmp_path):
    system = FakeSystem()
    refusals = []
    real_spawn = system.spawn

    def refusing(kind, command, cwd):
        if kind == lg.UNREAL and len(refusals) < 10:
            refusals.append(kind)
            raise OSError("The system cannot find the file specified")
        return real_spawn(kind, command, cwd)

    system.spawn = refusing
    sup, lines, clock = supervisor(tmp_path, system)
    sup.check()
    assert len(refusals) == 1
    assert any("Nu am putut porni Unreal" in line for line in lines)
    for _ in range(5):
        clock.now += 1
        sup.check()
    assert len(refusals) == 1
    for _ in range(40):
        clock.now += 60
        sup.check()
    # 30, 60, 120 s apart, then the hour's limit: never a retry on every check
    assert len(refusals) == 4


def test_a_dead_wilbur_comes_back_alone(tmp_path):
    system = FakeSystem()
    sup, _, clock = supervisor(tmp_path, system)
    sup.check()
    system.die(sup.owned[lg.WILBUR])
    sup.check()
    clock.now += 31
    sup.check()
    assert system.spawned() == [lg.WILBUR, lg.UNREAL, lg.WILBUR]


# ------------------------------------------------------------------------------- stopping


def test_stop_closes_unreal_then_wilbur_asking_first_then_killing(tmp_path):
    system = FakeSystem()
    sup, lines, _ = supervisor(tmp_path, system, unreal_close_wait=10.0, wilbur_close_wait=3.0)
    sup.check()
    wilbur_pid, unreal_pid = 1000, 1001
    system.windows = {unreal_pid: 1}
    system.closes_on_request = False  # it does not close when asked
    system.calls.clear()
    stopped = sup.stop()
    acts = [c for c in system.calls if c[0] in ("close", "kill", "wait")]
    assert acts[0] == ("close", unreal_pid)
    assert acts[1] == ("wait", unreal_pid, 10.0)
    assert acts[2] == ("kill", unreal_pid)
    order = [c[1] for c in acts if c[0] == "kill"]
    assert order == [unreal_pid, wilbur_pid]
    assert system.pids() == set()
    assert stopped == [f"Unreal (pid {unreal_pid})", f"wilbur (pid {wilbur_pid})"]
    assert any("oprit" in line and str(unreal_pid) in line for line in lines)
    # nothing restarts after a stop, and a second stop does nothing
    sup.check()
    assert system.spawned() == []
    assert sup.stop() == []


def test_a_window_that_closes_when_asked_is_not_killed(tmp_path):
    system = FakeSystem()
    sup, _, _ = supervisor(tmp_path, system)
    sup.check()
    system.windows = {1001: 1}
    sup.stop()
    assert ("kill", 1001) not in system.calls and ("kill", 1000) in system.calls


def test_stop_never_kills_a_reused_pid(tmp_path):
    system = FakeSystem()
    sup, _, _ = supervisor(tmp_path, system)
    sup.check()
    # Unreal died and Windows gave its pid to another program
    system.die(1001)
    system.procs.append(lg.Proc(1001, "UnrealEditor.exe", HIS_EDITOR.command_line))
    sup.stop()
    assert ("kill", 1001) not in system.calls and ("close", 1001) not in system.calls
    assert 1001 in system.pids()


def test_stop_also_takes_a_stream_process_started_meanwhile(tmp_path):
    setup = setup_for(tmp_path)
    system = FakeSystem()
    sup, _, _ = supervisor(tmp_path, system)
    sup.check()
    system.procs.append(stream_unreal(setup, 4242))
    sup.stop()
    assert 4242 not in system.pids() and HIS_EDITOR.pid not in {c[1] for c in system.calls}


def test_a_fast_stop_waits_less(tmp_path):
    system = FakeSystem()
    sup, _, _ = supervisor(tmp_path, system, fast_close_wait=1.0)
    sup.check()
    system.windows = {1001: 1}
    system.closes_on_request = False
    sup.stop(fast=True)
    assert ("wait", 1001, 1.0) in system.calls


def test_the_supervisor_waits_for_the_server_before_touching_anything(tmp_path):
    system = FakeSystem()
    sup, _, _ = supervisor(tmp_path, system, check_seconds=0.01, ready_poll_seconds=0.01)
    stop = threading.Event()
    ready = threading.Event()
    thread = threading.Thread(target=sup.run, args=(ready.is_set, stop))
    thread.start()
    try:
        stop.wait(0.1)
        assert system.calls == []
        ready.set()
        for _ in range(200):
            if system.spawned():
                break
            stop.wait(0.01)
        assert system.spawned() == [lg.WILBUR, lg.UNREAL]
    finally:
        stop.set()
        thread.join(5)
    assert not thread.is_alive()


# ------------------------------------------------------- start.py: server first, then graphics


class FakeServer:
    def __init__(self, interrupts: int = 0, code: int = 0) -> None:
        self.pid = 4000
        self.interrupts = interrupts
        self.code = code
        self.events: list[str] = []
        self.running = True

    def wait(self, timeout=None):
        if self.interrupts:
            self.interrupts -= 1
            raise KeyboardInterrupt
        self.events.append("server exited")
        self.running = False
        return self.code

    def poll(self):
        return None if self.running else self.code


class FakeSupervisor:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.stops: list[bool] = []

    def run(self, ready, stop_event) -> None:
        stop_event.wait(5)

    def stop(self, *, fast: bool = False) -> list[str]:
        self.events.append("graphics stopped")
        self.stops.append(fast)
        return []


def test_ctrl_c_lets_the_server_finish_before_the_graphics_stop(monkeypatch):
    server = FakeServer(interrupts=2)
    graphics = FakeSupervisor(server.events)
    assigned: list[int] = []
    code = start.serve(
        ["python", "run.py"],
        graphics=graphics,
        popen=lambda *a, **k: server,
        port_busy=lambda: False,
        port_open=lambda: True,
        assign=assigned.append,
        install_close_handler=lambda callback: None,
    )
    assert code == 0
    assert server.events == ["server exited", "graphics stopped"]
    assert assigned == [server.pid]


def test_a_port_already_served_leaves_the_graphics_untouched():
    server = FakeServer(code=1)
    graphics = FakeSupervisor(server.events)
    code = start.serve(
        ["python", "run.py"],
        graphics=graphics,
        popen=lambda *a, **k: server,
        port_busy=lambda: True,
        port_open=lambda: True,
        assign=lambda pid: None,
        install_close_handler=lambda callback: None,
    )
    assert code == 1
    assert graphics.stops == []


def test_closing_the_window_stops_the_graphics_fast_and_waits_for_the_server():
    server = FakeServer()
    graphics = FakeSupervisor(server.events)
    handlers = []
    start.serve(
        ["python", "run.py"],
        graphics=graphics,
        popen=lambda *a, **k: server,
        port_busy=lambda: False,
        port_open=lambda: True,
        assign=lambda pid: None,
        install_close_handler=handlers.append,
    )
    assert len(handlers) == 1
    graphics.stops.clear()
    handlers[0]()
    assert graphics.stops == [True]


# A second Ctrl+C reaching uvicorn while it waits for open connections (the page's sockets, a
# request in flight) sets its force_exit, and the lifespan shutdown - the day stopping at its
# boundary, REL-10 - is skipped. Seen on uvicorn 0.52.4 on 2026-10-04 with a real server in its
# own console. So the server gets its own process group: the console's Ctrl+C reaches start.py
# only, which asks the server once (CTRL_BREAK, a graceful stop for uvicorn).


def serve_with(server, graphics=None, **overrides):
    calls: dict[str, list] = {"popen": [], "interrupt": []}

    def popen(*args, **kwargs):
        calls["popen"].append(kwargs)
        return server

    def interrupt(target):
        calls["interrupt"].append(list(server.events))
        return True

    options = {
        "graphics": graphics,
        "popen": popen,
        "port_busy": lambda: False,
        "port_open": lambda: True,
        "assign": lambda pid: None,
        "install_close_handler": lambda callback: None,
        "interrupt": interrupt,
    }
    options.update(overrides)
    code = start.serve(["python", "run.py"], **options)
    return code, calls


def test_the_server_has_its_own_process_group_and_is_asked_to_stop_once():
    server = FakeServer(interrupts=3)
    graphics = FakeSupervisor(server.events)
    code, calls = serve_with(server, graphics)
    assert code == 0
    if sys.platform == "win32":
        assert calls["popen"][0]["creationflags"] & start.CREATE_NEW_PROCESS_GROUP
    # asked once, before it exited; the second and third Ctrl+C never reach it
    assert calls["interrupt"] == [[]]
    assert server.events == ["server exited", "graphics stopped"]


def test_start_py_waits_in_short_steps_so_its_ctrl_c_is_seen_while_the_server_runs():
    # Popen.wait() without a timeout is WaitForSingleObject(INFINITE) on Windows: Python only
    # raises the Ctrl+C after the server has ended, and the server - in its own process group -
    # never got it. Seen with a real server on 2026-10-04: Ctrl+C did nothing.
    import subprocess

    class Server(FakeServer):
        def __init__(self) -> None:
            super().__init__()
            self.timeouts: list[float | None] = []

        def wait(self, timeout=None):
            self.timeouts.append(timeout)
            assert timeout is not None, "an endless wait cannot be interrupted"
            if len(self.timeouts) < 4:
                raise subprocess.TimeoutExpired("run.py", timeout)
            return super().wait(timeout)

    server = Server()
    code, _ = serve_with(server)
    assert code == 0 and len(server.timeouts) == 4
    assert all(0 < t <= 1 for t in server.timeouts)


def test_a_server_stopped_by_ctrl_break_is_a_clean_stop():
    for code in (3, 0xC000013A):
        stopped, _ = serve_with(FakeServer(interrupts=1, code=code))
        assert stopped == 0
    # not asked to stop: 3 is a failure
    failed, _ = serve_with(FakeServer(code=3))
    assert failed == 3
    # a closed window: Windows ends the server first (STATUS_CONTROL_C_EXIT), sometimes before
    # start.py's own handler has run (seen 2026-10-04); not a failed start
    closed, _ = serve_with(FakeServer(code=0xC000013A))
    assert closed == 0


def test_a_ctrl_c_before_the_wait_still_waits_for_the_server_then_stops_the_graphics():
    server = FakeServer()
    graphics = FakeSupervisor(server.events)

    def assign(pid):
        raise KeyboardInterrupt

    code, calls = serve_with(server, graphics, assign=assign)
    assert code == 0
    assert calls["interrupt"] == [[]]
    assert server.events == ["server exited", "graphics stopped"]


def test_the_first_ctrl_c_ends_the_supervisors_pass_while_the_server_stops():
    seen: list[bool] = []

    class Supervisor(FakeSupervisor):
        def run(self, ready, stop_event) -> None:
            self.stop_event = stop_event
            stop_event.wait(5)

    server = FakeServer(interrupts=1)
    graphics = Supervisor(server.events)
    real_wait = server.wait

    def wait(timeout=None):
        if not server.interrupts:
            # the server is still stopping: no new Unreal may start meanwhile
            seen.append(graphics.stop_event.is_set())
        return real_wait(timeout)

    server.wait = wait
    serve_with(server, graphics)
    assert seen == [True]


def test_a_stop_that_cannot_be_sent_is_tried_again_at_the_next_ctrl_c():
    server = FakeServer(interrupts=2)
    sent: list[bool] = []

    def interrupt(target):
        sent.append(True)
        return len(sent) > 1

    code, _ = serve_with(server, interrupt=interrupt)
    assert code == 0 and len(sent) == 2


def test_ctrl_c_during_the_stop_does_not_skip_it():
    attempts: list[int] = []

    def flaky() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise KeyboardInterrupt
        return "done"

    assert start.uninterrupted(flaky) == "done" and len(attempts) == 3


@pytest.mark.skipif(sys.platform != "win32", reason="Ctrl+Break is Windows only")
def test_ctrl_break_is_a_ctrl_c_for_start_py(monkeypatch):
    import signal

    handlers: dict[int, object] = {}
    monkeypatch.setattr(signal, "signal", lambda sig, handler: handlers.__setitem__(sig, handler))
    start.catch_ctrl_break()
    # by default Ctrl+Break ends start.py at once, and the job then ends the server mid-stop
    assert handlers == {signal.SIGBREAK: signal.default_int_handler}


# ------------------------------------------------------------- the Windows layer, read-only


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows API")


@windows_only
def test_this_process_is_listed_with_its_command_line():
    import os

    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import win_processes as wp
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    mine = [p for p in wp.list_processes(lambda name: True) if p[0] == os.getpid()]
    assert len(mine) == 1
    pid, name, command_line = mine[0]
    assert name.lower().startswith("python") and "pytest" in command_line.lower()
    assert wp.free_commit_bytes() > 0
    assert isinstance(wp.session_id(), int)


@windows_only
def test_a_kill_on_close_job_can_be_made():
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import win_processes as wp
    finally:
        sys.path.remove(str(ROOT / "scripts"))
    job = wp.KillOnCloseJob.create()
    assert job is not None
    try:
        assert job.kill_on_close()
    finally:
        job.close()
