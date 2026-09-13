# Starts the live, streamed headquarters: Epic's signalling server (wilbur) with the AMN config,
# then Unreal running /Game/HQ/HQ_Dusk as a game that streams into it over Pixel Streaming 2.
# The web page connects to ws://localhost:<player_port> (wilbur.config.json) and shows the video.
#
#   powershell -File art-source/unreal/live/start_live_hq.ps1 [-ResX 1920] [-ResY 1080] [-Windowed]
#
# Paths come from the environment when set (AMN_PS_INFRA, AMN_PS_NODE, AMN_UE_ROOT), else the
# defaults this machine was set up with. Epic's scripts break on spaces in paths, so the
# infrastructure lives outside the repository in a folder without spaces.

param(
    # The page frames the scene at 1600:840; the stream keeps that shape so clicks line up.
    [int]$ResX = 1920,
    [int]$ResY = 1008,
    [switch]$Windowed
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Resolve-Path (Join-Path $here "..\..\..")
$infra = if ($env:AMN_PS_INFRA) { $env:AMN_PS_INFRA } else { "E:\AMN_PixelStreaming\PixelStreamingInfrastructure-UE5.8-0.1.0" }
$node = if ($env:AMN_PS_NODE) { $env:AMN_PS_NODE } else { "E:\AMN_PixelStreaming\node" }
$ueRoot = if ($env:AMN_UE_ROOT) { $env:AMN_UE_ROOT } else { "E:\Program Files\Epic Games\UE_5.8" }

$config = Get-Content (Join-Path $here "wilbur.config.json") -Raw | ConvertFrom-Json
$wilburDist = Join-Path $infra "SignallingWebServer\dist\index.js"
if (-not (Test-Path $wilburDist)) { throw "wilbur is not built: $wilburDist" }

$logs = Join-Path $infra "SignallingWebServer\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$wilbur = Start-Process -FilePath (Join-Path $node "node.exe") `
    -ArgumentList "`"$wilburDist`"", "--config_file", "`"$(Join-Path $here 'wilbur.config.json')`"" `
    -WorkingDirectory (Join-Path $infra "SignallingWebServer") -PassThru -WindowStyle Minimized
Write-Output "wilbur pid $($wilbur.Id): streamer port $($config.streamer_port), player port $($config.player_port)"

$uproject = Join-Path $repo "art-source\unreal\AMNReference\AMNReference.uproject"
$ueArgs = @(
    "`"$uproject`"", "/Game/HQ/HQ_Dusk", "-game",
    "-PixelStreamingConnectionURL=ws://127.0.0.1:$($config.streamer_port)",
    "-PixelStreamingEncoderCodec=H264",
    # Remote Control's HTTP API (localhost only): the backend moves the scene's people from studio state.
    "-RCWebControlEnable",
    # A development binary prints engine warnings over the picture; the stream must not show them.
    "-ExecCmds=`"DisableAllScreenMessages`"",
    "-ResX=$ResX", "-ResY=$ResY", "-ForceRes", "-nosplash", "-unattended"
)
if (-not $Windowed) { $ueArgs += "-RenderOffScreen" } else { $ueArgs += "-windowed" }
$ue = Start-Process -FilePath (Join-Path $ueRoot "Engine\Binaries\Win64\UnrealEditor.exe") -ArgumentList $ueArgs -PassThru
Write-Output "unreal pid $($ue.Id): streaming /Game/HQ/HQ_Dusk at ${ResX}x${ResY}"
