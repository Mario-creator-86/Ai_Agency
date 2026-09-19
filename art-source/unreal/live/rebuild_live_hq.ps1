# One pass of the live headquarters, end to end:
#   0. the pictures drawn outside Unreal: the sky atlas (compose_sky_backdrop.py --atlas, one cell per
#      sun elevation) and the shelter clock's digits (clock_hq_live.py --atlas)
#   1. Blender export for Unreal (workstations and desk screens as their own objects)
#   2. /Game/HQ/HQ_Dusk rebuilt from the export (build_hq_scene.py)
#   3. the Fab packs placed (dress_hq_live.py) and the street set moving (traffic_hq_live.py)
#   4. the built MetaHuman employees seated at their desks (people/seat_employees.py) and the
#      passers-by standing on the pavement (people/street_people.py)
#   5. the look pass (look_hq_live.py: lights, street fill, grade, fog, the room windows' dusk and day
#      pictures), the real surfaces (surfaces_hq_live.py: tiling detail over the baked atlas) and the
#      skyline's haze (haze_hq_live.py)
#   6. the shelter clock's live display over the baked digits (clock_hq_live.py)
#   7. the environment report (env_report_hq_live.py): label -> object path for everything the
#      backend drives, read from the level as the passes above saved it. It runs last, and a missing
#      label stops the pass here, before the stream comes back on a level the bridge cannot drive
#   8. the stream restarted on the new level (start_live_hq.ps1), waiting until Unreal joins
#
#   powershell -File art-source/unreal/live/rebuild_live_hq.ps1 [-SkipExport] [-SkipBuild] [-NoStream]
#
# -SkipExport rebuilds from the hq_scene.glb already exported (the real-sky phase changes nothing in
# Blender, so its rebuild runs with it and the baked atlases stay as they are).
#
# Logs go to -LogDir (default: art-source/unreal/renders/logs, ignored by Git). Every step stops the
# pass on failure: an Unreal step fails on a non-zero exit code, on a fatal line in its log (out of
# memory, a crash, a Python error) even after the level was saved, and on a log that never says the
# commandlet finished (Test-UnrealLog). Before anything is stopped the pass warns when free memory
# is under what the last rebuild used. Only processes this pass started (by name and command line)
# are restarted.

param(
    [switch]$SkipExport,
    [switch]$SkipBuild,
    [switch]$NoStream,
    [string]$LogDir = ""
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$unrealDir = Resolve-Path (Join-Path $here "..")
$repo = Resolve-Path (Join-Path $here "..\..\..")
$blender = if ($env:AMN_BLENDER) { $env:AMN_BLENDER } else { "E:\Program Files\Blender Foundation\Blender 5.2\blender.exe" }
$ueRoot = if ($env:AMN_UE_ROOT) { $env:AMN_UE_ROOT } else { "E:\Program Files\Epic Games\UE_5.8" }
$ueCmd = Join-Path $ueRoot "Engine\Binaries\Win64\UnrealEditor-Cmd.exe"
$uproject = Join-Path $unrealDir "AMNReference\AMNReference.uproject"
if (-not $LogDir) { $LogDir = Join-Path $unrealDir "renders\logs" }
New-Item -ItemType Directory -Force $LogDir | Out-Null

function Step([string]$name, [scriptblock]$body) {
    $t = Get-Date
    Write-Output "== $name"
    & $body
    Write-Output ("   done in {0:N0} s" -f ((Get-Date) - $t).TotalSeconds)
}

# What ends a commandlet step. On 2026-09-19 build_hq_scene.py saved the level ("level saved"), then
# ran out of memory while force-deleting the old Scene_20260916_214930 folder: "Fatal error ... Ran
# out of memory allocating 67108864 (64.0 MiB) bytes ... The paging file is too small for this
# operation to complete", then "Unhandled Exception: 0x0000c000". It left no "LogPython: Error"
# line, which was all this script looked for, so the pass went on as if the step had finished. A
# step now fails on any of these lines, wherever they stand in the log (a "level saved" before them
# proves nothing), on a non-zero exit code, and on a log without the commandlet's own last word:
# every one of the 646 step logs in renders/logs that finished carries "finished execution (result
# 0)", and the only two without it are that crash and a run that ended "result -1".
$UnrealFailurePatterns = @(
    "LogPython: Error",
    "Fatal error",
    "Ran out of memory",
    "paging file is too small",
    "Unhandled Exception",
    # a material a pass built that does not compile is drawn as the engine's default material in
    # the game (the window views' copied master, the near blocks' M_HQ_CityDay, the clock display):
    # MaterialEditingLibrary.recompile_material returns nothing to check, the log is where it shows.
    # None of the 648 step logs in renders/logs up to 2026-09-19 carries it.
    "Failed to compile Material"
)
$UnrealFinishedPattern = "finished execution \(result 0\)"

function Test-UnrealLog([string]$Path) {
    # The lines that fail a commandlet's log, first ones first; none when the step finished cleanly.
    if (-not (Test-Path -LiteralPath $Path)) { return @("no log was written at $Path") }
    $hits = @(Select-String -LiteralPath $Path -Pattern $UnrealFailurePatterns -SimpleMatch | Select-Object -First 8 | ForEach-Object { $_.Line.Trim() })
    if ($hits.Count -gt 0) { return $hits }
    if (-not (Select-String -LiteralPath $Path -Pattern $UnrealFinishedPattern -Quiet)) {
        return @("the commandlet never logged 'finished execution (result 0)': it did not run to its end")
    }
    return @()
}

function RunUnrealScript([string]$script) {
    $log = Join-Path $LogDir ("ue_" + [IO.Path]::GetFileNameWithoutExtension($script) + ".log")
    # the last rebuild's log goes aside first, named as the editor names its own backups: an editor
    # that never started writes no log, and the old one's "finished execution (result 0)" must not
    # pass for this run's
    if (Test-Path -LiteralPath $log) { Move-Item -LiteralPath $log -Destination ($log -replace '\.log$', ("-backup-" + (Get-Date -Format "yyyy.MM.dd-HH.mm.ss.fff") + ".log")) -Force }
    # the exit code is read the way the Blender step reads its own: under "Stop" a line on stderr would
    # end the pass before the code could be read, and the code is what says the editor died
    $ErrorActionPreference = "Continue"
    & $ueCmd "$uproject" -run=pythonscript "-script=$((Join-Path $unrealDir $script) -replace '\\', '/')" -unattended -nosplash "-abslog=$log" | Out-Null
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    # (a missing log is said by Test-UnrealLog below, not by a path error here)
    if (Test-Path -LiteralPath $log) { Select-String -LiteralPath $log -Pattern "AMN_(UE|DRESS|TRAFFIC|SEAT|STREET|LOOK|SURF|HAZE|CLOCK|ENV) " -ErrorAction SilentlyContinue | Select-Object -Last 6 | ForEach-Object { "   " + $_.Line.Substring($_.Line.IndexOf("AMN_")) } }
    $failure = @(Test-UnrealLog $log)
    if ($code -ne 0 -or $failure.Count -gt 0) {
        $failure | ForEach-Object { "   " + $_ }
        # a throw ends the pass here: nothing after it runs, the stream is not restarted on a
        # half-built level, and the runbook's ROLLBACK restores the backup
        throw "$script failed: exit code $code$(if ($failure.Count -gt 0) { '; ' + $failure[0] }) (log: $log)"
    }
}

# Memory before a rebuild. The same 2026-09-19 build logged, at its start, 7988 MB of physical memory
# free and 15834 MB of commit (physical plus page file) free, with Market Signals, Codex and other
# processes running; at its crash the editor alone had used PeakUsedVirtual 27112116224 bytes
# (25.25 GiB) and wanted 64 MiB more. So the pass warns before it stops anything when free physical
# memory plus free page file, counting back what the stream's own processes will give up when they
# stop, is under what the last rebuild used: the largest PeakUsedVirtual any step log in -LogDir
# records, and never less than the 25.3 GiB measured then.
$MeasuredRebuildPeakGB = 25.3

function Get-LastRebuildPeakGB([string]$Dir) {
    $peak = $MeasuredRebuildPeakGB
    Get-ChildItem -LiteralPath $Dir -Filter "ue_*.log" -File -ErrorAction SilentlyContinue | ForEach-Object {
        Select-String -LiteralPath $_.FullName -Pattern "PeakUsedVirtual (\d+)" -ErrorAction SilentlyContinue | ForEach-Object {
            $gb = [double]$_.Matches[0].Groups[1].Value / 1GB
            if ($gb -gt $peak) { $peak = $gb }
        }
    }
    return [math]::Round($peak, 2)
}

function Get-FreeMemoryGB {
    # free physical memory plus the free part of every page file, plus what the stream's own
    # processes hold (StopStream gives it back before Unreal starts); GB, and what each part was
    $os = Get-CimInstance Win32_OperatingSystem
    $physical = [double]$os.FreePhysicalMemory * 1KB / 1GB
    $page = 0.0
    Get-CimInstance Win32_PageFileUsage -ErrorAction SilentlyContinue | ForEach-Object {
        $page += ([double]$_.AllocatedBaseSize - [double]$_.CurrentUsage) * 1MB / 1GB
    }
    $stream = 0.0
    Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -eq "UnrealEditor.exe" -and $_.CommandLine -match "PixelStreamingConnectionURL") -or
        ($_.Name -eq "node.exe" -and $_.CommandLine -match "SignallingWebServer\\dist\\index\.js")
    } | ForEach-Object { $stream += [double]$_.PrivatePageCount / 1GB }
    return [pscustomobject]@{ Total = $physical + $page + $stream; Physical = $physical; PageFile = $page; Stream = $stream }
}

function Test-RebuildMemory([double]$FreeGB, [double]$NeededGB) {
    # the warning to print, or nothing when there is room
    if ($FreeGB -ge $NeededGB) { return $null }
    return ("only {0:N1} GB of memory is free (physical plus page file) where the last rebuild used {1:N1} GB: " +
            "build_hq_scene.py ran out of memory like this on 2026-09-19. Close Market Signals, Codex and " +
            "other heavy programs, or enlarge the page file, before going on.") -f $FreeGB, $NeededGB
}

function StopStream {
    Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -eq "UnrealEditor.exe" -and $_.CommandLine -match "PixelStreamingConnectionURL") -or
        ($_.Name -eq "node.exe" -and $_.CommandLine -match "SignallingWebServer\\dist\\index\.js")
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
}

# Pre-flight, before anything is stopped: a warning, not a stop (the Owner's window may still go on
# with more memory freed), printed where whoever runs the pass reads it first.
$memory = Get-FreeMemoryGB
$needed = Get-LastRebuildPeakGB $LogDir
Write-Output ("== Memory: {0:N1} GB free ({1:N1} physical, {2:N1} page file, {3:N1} from the stream); the last rebuild used {4:N1} GB" -f $memory.Total, $memory.Physical, $memory.PageFile, $memory.Stream, $needed)
$short = Test-RebuildMemory $memory.Total $needed
if ($short) { Write-Warning $short }

# The sky first, export or not: compose_sky_backdrop.py --atlas writes sky_atlas.png (one cell per sun
# elevation, the -2.5 cell being the dusk plate the stream has shown since 2026-09-16) and its
# sky_atlas.json, and the level build imports both. Until 2026-09-16 this pass never composed the
# sky, so every change to its tint, clouds or glow stayed in the code and the stream kept the plate
# last composed by hand.
if (-not $SkipBuild) {
    Step "Sky atlas composed" {
        $log = Join-Path $LogDir "sky_backdrop.log"
        & py -3.11 (Join-Path $unrealDir "compose_sky_backdrop.py") --atlas *> $log
        if ($LASTEXITCODE -ne 0) { throw "compose_sky_backdrop.py --atlas failed (log: $log)" }
        Select-String -Path $log -Pattern "AMN_SKY atlas" | ForEach-Object { "   " + $_.Line }
    }
}
# The clock's digits are drawn with numpy, which the editor's own Python does not carry; the clock
# pass below imports the picture. Cheap, so drawn on every pass, build or not.
Step "Clock digits drawn" {
    $log = Join-Path $LogDir "clock_atlas.log"
    & py -3.11 (Join-Path $unrealDir "clock_hq_live.py") --atlas *> $log
    if ($LASTEXITCODE -ne 0) { throw "clock_hq_live.py --atlas failed (log: $log)" }
    Select-String -Path $log -Pattern "AMN_CLOCK" | ForEach-Object { "   " + $_.Line }
}
if (-not $SkipExport) {
    Step "Blender export for Unreal" {
        $env:AMN_UNREAL_WORKSTATIONS = "1"
        # plants and portrait pictures are left to pack models (dress_hq_live.py)
        $env:AMN_UNREAL_PROPS = "1"
        $log = Join-Path $LogDir "blender_export.log"
        # Windows PowerShell 5.1 turns a native program's stderr into error records; under "Stop" the
        # first Blender warning on stderr (a DeprecationWarning) aborted the pass. Judge by exit code.
        $ErrorActionPreference = "Continue"
        & $blender -b --factory-startup --python (Join-Path $unrealDir "export_hq_scene.py") *> $log
        $code = $LASTEXITCODE
        $ErrorActionPreference = "Stop"
        if ($code -ne 0) { throw "Blender export failed with exit code $code (log: $log)" }
        Select-String -Path $log -Pattern "AMN_EXPORT" | ForEach-Object { "   " + $_.Line }
    }
}
# The streamed game holds the level's packages open; rebuilding them while it runs fails to replace
# assets (the sky material could not be deleted and recreated). Stop it just before Unreal touches
# the level (the Blender export does not), and start it at the end: the page shows no live picture
# in between.
if (-not $NoStream) { StopStream }
# The backend drives the scene by the object paths in env_report.json, and every rebuild renames
# them (the sky backdrop was StaticMeshActor_223 on 2026-09-18). A report left from the level being
# replaced would aim the sky's, the haze's and the road's parameters at whatever carries those names
# next, so it goes before Unreal touches the level: until this pass writes a new one the backend
# sends nothing and says so once (office_unreal_env_report_missing).
$envReport = Join-Path $unrealDir "env_report.json"
$passStarted = Get-Date
if (Test-Path $envReport) { Remove-Item -LiteralPath $envReport -Force }
if (-not $SkipBuild) {
    Step "Level rebuilt from the export" { RunUnrealScript "build_hq_scene.py" }
    # The import makes every merged mesh Nanite, and Nanite drops the small lights' separate boxes
    # (the S1 racks' LEDs): the small lights' mesh is turned back into a regular mesh (AMN_NANITE_OFF).
    Step "Nanite off on the small lights" { RunUnrealScript "nanite_hq_live.py" }
}
Step "Fab packs placed" { RunUnrealScript "dress_hq_live.py" }
Step "Street traffic" { RunUnrealScript "traffic_hq_live.py" }
# Rebuilding the level removes every actor, the employees too: seat the built MetaHumans again
# (employees not yet rigged and built are skipped and reported).
Step "Employees seated" { RunUnrealScript "people/seat_employees.py" }

Step "Passers-by on the pavement" { RunUnrealScript "people/street_people.py" }
# The build recreates every light and the post-process at their defaults: the look pass goes on
# again each time (its values come from AMN_LOOK_*).
Step "Look pass" { RunUnrealScript "look_hq_live.py" }
# The export bakes every material into a flat-colour atlas: this pass keeps that atlas and multiplies
# a tiling detail colour, normal and roughness over it (hq_surfaces.json), so the walls, floors and
# pavements carry grain instead of reading as painted card.
Step "Real surfaces" { RunUnrealScript "surfaces_hq_live.py" }
# the skyline's blue haze: translucent planes behind the building (AMN_HAZE_*)
Step "Skyline haze" { RunUnrealScript "haze_hq_live.py" }
# the baked 15:18 hidden and the live display placed over it (it reads --:-- until the backend's first
# clock sync)
Step "Shelter clock" { RunUnrealScript "clock_hq_live.py" }
# Last, after every pass has saved the level: the object paths change with each rebuild, and the
# backend reads them from here. A missing label throws, so the stream does not come back undrivable.
Step "Environment report" { RunUnrealScript "env_report_hq_live.py" }
# A crash of the editor leaves no "LogPython: Error" line to find: the report this pass wrote is the
# proof that the last step ran to its end, so the stream does not come back without one.
if (-not (Test-Path $envReport) -or (Get-Item -LiteralPath $envReport).LastWriteTime -lt $passStarted) {
    throw "env_report.json was not written by this pass: the level may be half built (restore the backup)"
}

if (-not $NoStream) {
    Step "Stream restarted" {
        StopStream
        $since = Get-Date
        & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $here "start_live_hq.ps1")
        $infra = if ($env:AMN_PS_INFRA) { $env:AMN_PS_INFRA } else { "E:\AMN_PixelStreaming\PixelStreamingInfrastructure-UE5.8-0.1.0" }
        $logs = Join-Path $infra "SignallingWebServer\logs"
        $deadline = (Get-Date).AddMinutes(30)
        do {
            [Threading.Thread]::Sleep(10000)
            $f = Get-ChildItem $logs -File -Filter "*.log" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
            $joined = [bool](Select-String -Path $f.FullName -Pattern "endpointIdConfirm" | Where-Object {
                $_.Line -match '"timestamp":"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)' -and ([datetime]$Matches[1]) -gt $since
            })
        } until ($joined -or (Get-Date) -gt $deadline)
        if (-not $joined) { throw "Unreal did not join the signalling server within 30 minutes" }
        Write-Output "   Unreal joined the signalling server"
    }
}
