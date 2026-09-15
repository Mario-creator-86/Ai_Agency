# One pass of the live headquarters, end to end:
#   1. Blender export for Unreal (workstations and desk screens as their own objects)
#   2. /Game/HQ/HQ_Dusk rebuilt from the export (build_hq_scene.py)
#   3. the Fab packs placed (dress_hq_live.py) and the street set moving (traffic_hq_live.py)
#   4. the stream restarted on the new level (start_live_hq.ps1), waiting until Unreal joins
#
#   powershell -File art-source/unreal/live/rebuild_live_hq.ps1 [-SkipExport] [-SkipBuild] [-NoStream]
#
# Logs go to -LogDir (default: art-source/unreal/renders/logs, ignored by Git). Every step stops the
# pass on failure. Only processes this pass started (by name and command line) are restarted.

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

function RunUnrealScript([string]$script) {
    $log = Join-Path $LogDir ("ue_" + [IO.Path]::GetFileNameWithoutExtension($script) + ".log")
    & $ueCmd "$uproject" -run=pythonscript "-script=$((Join-Path $unrealDir $script) -replace '\\', '/')" -unattended -nosplash "-abslog=$log" | Out-Null
    $errors = Select-String -Path $log -Pattern "LogPython: Error" -ErrorAction SilentlyContinue
    Select-String -Path $log -Pattern "AMN_(UE|DRESS|TRAFFIC) " -ErrorAction SilentlyContinue | Select-Object -Last 6 | ForEach-Object { "   " + $_.Line.Substring($_.Line.IndexOf("AMN_")) }
    if ($errors) {
        $errors | Select-Object -First 8 | ForEach-Object { "   " + $_.Line }
        throw "$script reported Python errors (log: $log)"
    }
}

function StopStream {
    Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -eq "UnrealEditor.exe" -and $_.CommandLine -match "PixelStreamingConnectionURL") -or
        ($_.Name -eq "node.exe" -and $_.CommandLine -match "SignallingWebServer\\dist\\index\.js")
    } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false }
}

# The streamed game holds the level's packages open; rebuilding them while it runs fails to replace
# assets (the sky material could not be deleted and recreated). Stop it first, start it at the end.
if (-not $NoStream) { StopStream }

if (-not $SkipExport) {
    Step "Blender export for Unreal" {
        $env:AMN_UNREAL_WORKSTATIONS = "1"
        $log = Join-Path $LogDir "blender_export.log"
        & $blender -b --factory-startup --python (Join-Path $unrealDir "export_hq_scene.py") *> $log
        if ($LASTEXITCODE -ne 0) { throw "Blender export failed (log: $log)" }
        Select-String -Path $log -Pattern "AMN_EXPORT" | ForEach-Object { "   " + $_.Line }
    }
}
if (-not $SkipBuild) {
    Step "Level rebuilt from the export" { RunUnrealScript "build_hq_scene.py" }
}
Step "Fab packs placed" { RunUnrealScript "dress_hq_live.py" }
Step "Street traffic" { RunUnrealScript "traffic_hq_live.py" }

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
