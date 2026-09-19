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
import shutil
import subprocess
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------- a step that dies is a failed step
#
# 2026-09-19: build_hq_scene.py saved the level, then ran out of memory while deleting the old scene
# folder. Its log had no "LogPython: Error" line, the script looked for nothing else, and the pass
# went on. These fixtures are that log's own lines (trimmed) and the lines of a step that finished.
# The script's own functions run on them in PowerShell, parsed out of the file so that nothing else
# of it runs (running it would take the stream down).

LEVEL_SAVED = (
    "[2026.09.19-05.53.27:444][  0]LogPython: AMN_UE level saved /Game/HQ/HQ_Dusk\n"
    "[2026.09.19-05.53.48:085][  0]LogPython: AMN_UE old scene folder "
    "/Game/HQ/Scene_20260916_214231 NOT deleted (still referenced?)\n"
)
OOM_AFTER_SAVE = LEVEL_SAVED + (
    "[2026.09.19-05.54.27:663][  0]LogMemory: Warning: Freeing 33554432 bytes (32.0 MiB) from "
    "backup pool to handle out of memory.\n"
    "[2026.09.19-05.54.27:663][  0]LogMemory: Warning: MemoryStats:\n"
    "\tAvailablePhysical 10305536 (0.01 GiB)\n"
    "\t AvailableVirtual 47915008 (0.04 GiB)\n"
    "\t     UsedPhysical 7217242112 (6.72 GiB)\n"
    "\t PeakUsedPhysical 11993243648 (11.17 GiB)\n"
    "\t      UsedVirtual 27041193984 (25.18 GiB)\n"
    "\t  PeakUsedVirtual 27112116224 (25.25 GiB)\n"
    "[2026.09.19-05.54.27:667][  0]LogWindows: Error: appError called: Fatal error: "
    "[File:GenericPlatformMemory.cpp] [Line: 300] \n"
    "Ran out of memory allocating 67108864 (64.0 MiB) bytes with alignment 0. Last error msg: "
    "The paging file is too small for this operation to complete..\n"
    "[2026.09.19-05.54.34:193][  0]LogWindows: Error: Unhandled Exception: 0x0000c000\n"
    "[2026.09.19-05.54.34:288][  0]LogCore: Engine exit requested (reason: Win RequestExit)\n"
)
FINISHED = (
    "[2026.09.19-05.56.22:154][  0]LogCore: Engine exit requested (reason: Commandlet "
    "PythonScriptCommandlet_0 finished execution (result 0))\n"
    "[2026.09.19-05.56.23:229][  0]Log file closed, 09/19/26 08:56:23\n"
)
CLEAN = "[2026.09.19-05.56.04:927][  0]LogPython: AMN_LOOK lights tuned {}\n" + FINISHED
# each line alone fails a step, even in a log that says it finished, even after "level saved"
FATAL_LINES = {
    "fatal": "[..][  0]LogWindows: Error: Fatal error: [File:GenericPlatformMemory.cpp] [Line: 3]",
    "oom": "Ran out of memory allocating 67108864 (64.0 MiB) bytes with alignment 0.",
    "paging": "Last error msg: The paging file is too small for this operation to complete..",
    "unhandled": "[..][  0]LogWindows: Error: Unhandled Exception: 0x0000c000",
    "python": "[..][  0]LogPython: Error: Traceback (most recent call last):",
    # a material the pass built that does not compile renders as the default material in the game:
    # the look pass's window view and near-block day master, the clock's display
    "material": "[..][  0]LogMaterial: Warning: Failed to compile Material "
    "/Game/HQ/Materials/M_HQ_WindowView_M_Default_v1 for platform PCD3D_SM6, "
    "Default Material will be used in game.",
}
DEFINED = ("Test-UnrealLog", "RunUnrealScript", "Get-LastRebuildPeakGB", "Test-RebuildMemory")
SCRIPT_VARIABLES = ("UnrealFailurePatterns", "UnrealFinishedPattern", "MeasuredRebuildPeakGB")


def _powershell() -> str | None:
    return shutil.which("powershell") or shutil.which("pwsh")


needs_powershell = pytest.mark.skipif(_powershell() is None, reason="no PowerShell here")

HARNESS = """$ErrorActionPreference = "Stop"
$t = $null; $e = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('SCRIPT', [ref]$t, [ref]$e)
if ($e.Count -gt 0) { throw "parse errors: $($e.Count)" }
foreach ($s in $ast.EndBlock.Statements) {
    if ($s -is [System.Management.Automation.Language.AssignmentStatementAst] -and
        @(VARIABLES) -contains $s.Left.VariablePath.UserPath) {
        . ([scriptblock]::Create($s.Extent.Text))
    }
}
$defs = $ast.FindAll({
    param($n) $n -is [System.Management.Automation.Language.FunctionDefinitionAst]
}, $true)
foreach ($f in $defs) {
    if (@(NAMES) -contains $f.Name) { . ([scriptblock]::Create($f.Extent.Text)) }
}
"""


def run_functions(tmp_path: Path, body: str) -> str:
    """Define the script's own functions and the variables they read, then run body."""
    harness = tmp_path / "harness.ps1"
    prelude = (
        HARNESS.replace("SCRIPT", str(SCRIPT))
        .replace("VARIABLES", ",".join(f"'{n}'" for n in SCRIPT_VARIABLES))
        .replace("NAMES", ",".join(f"'{n}'" for n in DEFINED))
    )
    harness.write_text(prelude + body, encoding="utf-8")
    done = subprocess.run(
        [_powershell(), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(harness)],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return done.stdout


def failures_of(tmp_path: Path, text: str) -> list[str]:
    log = tmp_path / "step.log"
    log.write_text(text, encoding="utf-8")
    body = f"@(Test-UnrealLog '{log}') | ForEach-Object {{ 'HIT ' + $_ }}\n'END'\n"
    out = run_functions(tmp_path, body)
    assert out.rstrip().endswith("END")
    return [ln[4:] for ln in out.splitlines() if ln.startswith("HIT ")]


@needs_powershell
def test_the_crash_after_the_level_was_saved_fails_the_step(tmp_path):
    hits = failures_of(tmp_path, OOM_AFTER_SAVE)
    assert hits, "the 2026-09-19 crash passed as a finished step"
    assert "Fatal error" in hits[0]
    assert any("paging file is too small" in h for h in hits)
    assert any("Unhandled Exception" in h for h in hits)


@needs_powershell
def test_a_step_that_finished_cleanly_passes(tmp_path):
    assert failures_of(tmp_path, CLEAN) == []


@needs_powershell
@pytest.mark.parametrize("kind", sorted(FATAL_LINES))
def test_each_fatal_line_fails_even_in_a_log_that_says_it_finished(tmp_path, kind):
    hits = failures_of(tmp_path, LEVEL_SAVED + FATAL_LINES[kind] + "\n" + FINISHED)
    assert hits and FATAL_LINES[kind] in hits[0]


@needs_powershell
def test_a_log_that_never_says_the_commandlet_finished_fails(tmp_path):
    hits = failures_of(tmp_path, LEVEL_SAVED)
    assert hits and "finished execution (result 0)" in hits[0]


@needs_powershell
def test_a_missing_log_fails(tmp_path):
    missing = tmp_path / "none.log"
    out = run_functions(
        tmp_path, f"@(Test-UnrealLog '{missing}') | ForEach-Object {{ 'HIT ' + $_ }}\n"
    )
    assert "HIT no log was written" in out


FAKE_UE = """$arg = $args | Where-Object { "$_" -like '-abslog=*' } | Select-Object -First 1
$log = "$arg" -replace '^-abslog=', ''
Copy-Item -LiteralPath 'FIXTURE' -Destination $log
exit CODE
"""


def run_step(tmp_path: Path, log_text: str, exit_code: int) -> str:
    """RunUnrealScript against a stand-in for UnrealEditor-Cmd.exe that writes log_text where the
    step asks (-abslog=...) and exits with exit_code."""
    fixture = tmp_path / "fixture.log"
    fixture.write_text(log_text, encoding="utf-8")
    fake = tmp_path / "fake_ue.ps1"
    fake.write_text(
        FAKE_UE.replace("FIXTURE", str(fixture)).replace("CODE", str(exit_code)), encoding="utf-8"
    )
    body = (
        f"$ueCmd = '{fake}'; $uproject = 'AMNReference.uproject'\n"
        f"$unrealDir = '{tmp_path}'; $LogDir = '{tmp_path}'\n"
        "try { RunUnrealScript 'build_hq_scene.py'; 'CARRIED ON' }\n"
        "catch { 'STOPPED ' + $_.Exception.Message }\n"
    )
    return run_functions(tmp_path, body)


@needs_powershell
def test_the_pass_stops_on_the_crash_even_with_exit_code_zero(tmp_path):
    out = run_step(tmp_path, OOM_AFTER_SAVE, 0)
    assert "CARRIED ON" not in out
    assert "STOPPED build_hq_scene.py failed: exit code 0; " in out
    assert "Fatal error" in out  # the log line is printed where the pass stops


@needs_powershell
def test_the_pass_stops_on_a_non_zero_exit_code_with_a_clean_log(tmp_path):
    out = run_step(tmp_path, CLEAN, 3)
    assert "STOPPED build_hq_scene.py failed: exit code 3" in out
    assert "CARRIED ON" not in out


@needs_powershell
def test_a_clean_step_carries_on(tmp_path):
    out = run_step(tmp_path, CLEAN, 0)
    assert "CARRIED ON" in out and "STOPPED" not in out


@needs_powershell
def test_a_step_that_writes_no_log_is_not_passed_on_the_last_runs_log(tmp_path):
    """A clean log from the previous rebuild stands at the step's log path. An editor that exits 0
    without writing its own (it never started) must not pass on that stale log's last word."""
    (tmp_path / "ue_build_hq_scene.log").write_text(CLEAN, encoding="utf-8")
    fake = tmp_path / "fake_ue.ps1"
    fake.write_text("exit 0\n", encoding="utf-8")
    body = (
        f"$ueCmd = '{fake}'; $uproject = 'AMNReference.uproject'\n"
        f"$unrealDir = '{tmp_path}'; $LogDir = '{tmp_path}'\n"
        "try { RunUnrealScript 'build_hq_scene.py'; 'CARRIED ON' }\n"
        "catch { 'STOPPED ' + $_.Exception.Message }\n"
    )
    out = run_functions(tmp_path, body)
    assert "CARRIED ON" not in out
    assert "no log was written" in out
    # the old log is kept beside it, as the editor itself keeps its backups
    assert list(tmp_path.glob("ue_build_hq_scene-backup-*.log"))


def test_every_unreal_step_goes_through_the_checked_runner():
    text = "\n".join(code())
    runner = text[text.index("function RunUnrealScript") :]
    runner = runner[: runner.index("\n}") + 2]
    assert "$code = $LASTEXITCODE" in runner
    assert "Test-UnrealLog $log" in runner
    assert "$code -ne 0 -or $failure.Count -gt 0" in runner
    assert "throw" in runner
    assert text.count("& $ueCmd") == 1  # no Unreal step is started any other way
    for pattern in ("Fatal error", "Ran out of memory", "paging file is too small"):
        assert f'"{pattern}"' in text
    assert '"Unhandled Exception"' in text


# ---------------------------------------------------------------- memory before the pass


@needs_powershell
def test_the_last_rebuilds_peak_is_read_from_its_logs(tmp_path):
    (tmp_path / "ue_build_hq_scene.log").write_text(OOM_AFTER_SAVE, encoding="utf-8")
    out = run_functions(tmp_path, f"'PEAK ' + (Get-LastRebuildPeakGB '{tmp_path}')\n")
    # 27112116224 bytes = 25.25 GiB, under the 25.3 kept for the 64 MiB it still asked for
    assert re.search(r"PEAK 25[.,]3\b", out), out
    bigger = OOM_AFTER_SAVE.replace("27112116224", str(32 * 1024**3))
    (tmp_path / "ue_build_hq_scene.log").write_text(bigger, encoding="utf-8")
    out = run_functions(tmp_path, f"'PEAK ' + (Get-LastRebuildPeakGB '{tmp_path}')\n")
    assert re.search(r"PEAK 32\b", out), out


@needs_powershell
def test_the_warning_speaks_when_memory_is_short_and_not_otherwise(tmp_path):
    # 2026-09-19 at the build's start: 15834 MB of commit free against the 25.25 GiB it used
    body = (
        "'SHORT ' + (Test-RebuildMemory 15.5 25.3)\n"
        "$ok = Test-RebuildMemory 40 25.3; if ($null -eq $ok) { 'ROOM' }\n"
    )
    out = run_functions(tmp_path, body)
    assert "SHORT only" in out and "2026-09-19" in out
    assert "ROOM" in out


def test_the_memory_check_comes_before_anything_is_stopped():
    warn = first(r"Write-Warning \$short")
    assert first(r"^\$memory = Get-FreeMemoryGB") < warn
    assert warn < first(r"if \(-not \$NoStream\) \{ StopStream \}")
    assert warn < first(r'RunUnrealScript "build_hq_scene\.py"')
