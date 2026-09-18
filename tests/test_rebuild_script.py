"""The live rebuild (art-source/unreal/live/rebuild_live_hq.ps1) never leaves the backend driving a
level by another level's object paths, and stops only the stream's own processes.

The backend drives the scene by the object paths in art-source/unreal/env_report.json, and those
paths change with every rebuild (StaticMeshActor_223 is another actor after the next one). A report
left over from the previous level would aim the sky's, the haze's and the road's parameters at
whatever now carries those names. So the old report goes before Unreal touches the level, and the
stream comes back only once this pass has written a new one. The script is not run here (it takes
the stream down); these checks read it.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "art-source" / "unreal" / "live" / "rebuild_live_hq.ps1"
START = ROOT / "art-source" / "unreal" / "live" / "start_live_hq.ps1"


def code() -> list[str]:
    return [
        ln.strip()
        for ln in SCRIPT.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def first(pattern: str) -> int:
    for i, ln in enumerate(code()):
        if re.search(pattern, ln):
            return i
    raise AssertionError(f"{pattern} not in {SCRIPT.name}")


def test_the_old_report_goes_before_unreal_touches_the_level():
    removed = first(r"Remove-Item .*\$envReport")
    assert removed < first(r'RunUnrealScript "build_hq_scene\.py"')
    assert removed < first(r'RunUnrealScript "dress_hq_live\.py"')
    assert re.search(r'env_report\.json"', "\n".join(code()))


def test_the_stream_comes_back_only_on_a_report_this_pass_wrote():
    report = first(r'RunUnrealScript "env_report_hq_live\.py"')
    fresh = first(r"LastWriteTime -lt \$passStarted")
    restart = first(r"start_live_hq\.ps1")
    assert report < fresh < restart


def test_only_the_streams_own_processes_are_stopped_by_name_and_command_line():
    text = "\n".join(code())
    stop = text[text.index("function StopStream") :]
    stop = stop[: stop.index("\n}") + 2]
    unreal = '$_.Name -eq "UnrealEditor.exe" -and $_.CommandLine -match '
    assert unreal + '"PixelStreamingConnectionURL"' in stop
    assert '$_.Name -eq "node.exe" -and $_.CommandLine -match "SignallingWebServer' in stop


def test_the_stream_can_be_started_with_the_frame_time_capture():
    # the phase gate measures p95 frame time with the engine's CSV profiler, a command-line switch
    text = START.read_text(encoding="utf-8")
    assert re.search(r"\[string\[\]\]\$ExtraArgs = @\(\)", text)
    assert "$ueArgs += $ExtraArgs" in text
