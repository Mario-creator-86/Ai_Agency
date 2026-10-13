# Starts the live, streamed headquarters: Epic's signalling server (wilbur) with the AMN config,
# then Unreal running /Game/HQ/HQ_Dusk as a game that streams into it over Pixel Streaming 2.
# The web page connects to ws://localhost:<player_port> (wilbur.config.json) and shows the video.
#
#   powershell -File art-source/unreal/live/start_live_hq.ps1 [-ResX 1920] [-ResY 1008] [-Windowed] [-PrintOnly]
#
# scripts/start.py starts the same two processes with the studio (scripts/live_graphics.py), from
# the same stream_command.json, and stops them with it; this script is for a stream on its own.
#
# Paths come from the parameters, else the environment (AMN_PS_INFRA, AMN_PS_NODE, AMN_UE_ROOT), else
# art-source\unreal\.env.paths; with none of them the script stops and says which to set. Epic's
# scripts break on spaces in paths, so the infrastructure lives outside the repository in a folder
# without spaces.

param(
    # 0 = the size in stream_command.json (1920x1008: the page frames the scene at 1600:840).
    [int]$ResX = 0,
    [int]$ResY = 0,
    [switch]$Windowed,
    # Print the two command lines and start nothing.
    [switch]$PrintOnly,
    # Appended to the game's command line, for a measurement only: the phase gate's frame time is the
    # engine's CSV profiler (-csvCaptureFrames=N, written under AMNReference/Saved/Profiling/CSV).
    [string[]]$ExtraArgs = @(),
    # Epic's PixelStreamingInfrastructure folder, the folder holding node.exe, and the engine's root.
    [string]$InfraPath = "",
    [string]$NodePath = "",
    [string]$UeRoot = ""
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Resolve-Path (Join-Path $here "..\..\..")
$unrealDir = Resolve-Path (Join-Path $here "..")
# Machine paths (SELL-11): the environment first, then art-source\unreal\.env.paths (KEY=VALUE lines,
# ignored by Git, written once per machine), else a refusal that names both. No tracked file names a
# drive of the first studio's PC. -Optional returns $null instead, for a path only one step needs.
function Get-AmnPath([string]$Name, [string]$What, [switch]$Optional) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if (-not $value) {
        $file = Join-Path $unrealDir ".env.paths"
        if (Test-Path -LiteralPath $file) {
            foreach ($line in Get-Content -LiteralPath $file -Encoding UTF8) {
                if ($line -match '^\s*([A-Z_][A-Z0-9_]*)\s*=\s*"?([^"]*?)"?\s*$' -and $Matches[1] -eq $Name) { $value = $Matches[2] }
            }
        }
    }
    if (-not $value -and -not $Optional) {
        throw "Set $Name to the $What (an environment variable, or a line $Name=<path> in art-source\unreal\.env.paths), or pass its -Path parameter."
    }
    return $value
}
$infra = if ($InfraPath) { $InfraPath } else { Get-AmnPath "AMN_PS_INFRA" "PixelStreamingInfrastructure folder" }
$node = if ($NodePath) { $NodePath } else { Get-AmnPath "AMN_PS_NODE" "folder holding node.exe" }
$ueRoot = if ($UeRoot) { $UeRoot } else { Get-AmnPath "AMN_UE_ROOT" "Unreal Engine root (the folder holding Engine\Binaries)" }

$config = Get-Content (Join-Path $here "wilbur.config.json") -Raw | ConvertFrom-Json
# The argument lists live in stream_command.json, which scripts/start.py reads too (it starts the
# stream with the studio): one list for both, never a copy. Its "_why" says why each argument is there.
$command = Get-Content (Join-Path $here "stream_command.json") -Raw -Encoding UTF8 | ConvertFrom-Json
if (-not $ResX) { $ResX = [int]$command.res_x }
if (-not $ResY) { $ResY = [int]$command.res_y }
$wilburDist = Join-Path $infra ($command.wilbur_script -replace '/', '\')
$wilburConfig = Join-Path $here $command.wilbur_config
$nodeExe = Join-Path $node "node.exe"
$wilburArgs = @("`"$wilburDist`"", "--config_file", "`"$wilburConfig`"")

$uproject = Join-Path $repo ($command.uproject -replace '/', '\')
$ueArgs = @("`"$uproject`"", $command.map)
foreach ($arg in $command.unreal_args) {
    $ueArgs += ($arg -replace '\{streamer_port\}', $config.streamer_port -replace '\{res_x\}', $ResX -replace '\{res_y\}', $ResY)
}
if (-not $Windowed) { $ueArgs += $command.offscreen_args } else { $ueArgs += $command.windowed_args }
$ueArgs += $ExtraArgs
$ueExe = Join-Path $ueRoot "Engine\Binaries\Win64\UnrealEditor.exe"

if ($PrintOnly) {
    Write-Output "`"$nodeExe`" $($wilburArgs -join ' ')"
    Write-Output "`"$ueExe`" $($ueArgs -join ' ')"
    return
}
if (-not (Test-Path $wilburDist)) { throw "wilbur is not built: $wilburDist" }

$logs = Join-Path $infra "SignallingWebServer\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$wilbur = Start-Process -FilePath $nodeExe -ArgumentList $wilburArgs `
    -WorkingDirectory (Join-Path $infra "SignallingWebServer") -PassThru -WindowStyle Hidden  # a minimized console still took the focus
Write-Output "wilbur pid $($wilbur.Id): streamer port $($config.streamer_port), player port $($config.player_port)"

$ue = Start-Process -FilePath $ueExe -ArgumentList $ueArgs -PassThru
Write-Output "unreal pid $($ue.Id): streaming $($command.map) at ${ResX}x${ResY}"
