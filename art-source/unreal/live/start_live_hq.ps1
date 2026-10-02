# Starts the live, streamed headquarters: Epic's signalling server (wilbur) with the AMN config,
# then Unreal running /Game/HQ/HQ_Dusk as a game that streams into it over Pixel Streaming 2.
# The web page connects to ws://localhost:<player_port> (wilbur.config.json) and shows the video.
#
#   powershell -File art-source/unreal/live/start_live_hq.ps1 [-ResX 1920] [-ResY 1080] [-Windowed]
#
# Paths come from the parameters, else the environment (AMN_PS_INFRA, AMN_PS_NODE, AMN_UE_ROOT), else
# art-source\unreal\.env.paths; with none of them the script stops and says which to set. Epic's
# scripts break on spaces in paths, so the infrastructure lives outside the repository in a folder
# without spaces.

param(
    # The page frames the scene at 1600:840; the stream keeps that shape so clicks line up.
    [int]$ResX = 1920,
    [int]$ResY = 1008,
    [switch]$Windowed,
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
$wilburDist = Join-Path $infra "SignallingWebServer\dist\index.js"
if (-not (Test-Path $wilburDist)) { throw "wilbur is not built: $wilburDist" }

$logs = Join-Path $infra "SignallingWebServer\logs"
New-Item -ItemType Directory -Force $logs | Out-Null
$wilbur = Start-Process -FilePath (Join-Path $node "node.exe") `
    -ArgumentList "`"$wilburDist`"", "--config_file", "`"$(Join-Path $here 'wilbur.config.json')`"" `
    -WorkingDirectory (Join-Path $infra "SignallingWebServer") -PassThru -WindowStyle Hidden  # a minimized console still took the focus
Write-Output "wilbur pid $($wilbur.Id): streamer port $($config.streamer_port), player port $($config.player_port)"

$uproject = Join-Path $repo "art-source\unreal\AMNReference\AMNReference.uproject"
$ueArgs = @(
    "`"$uproject`"", "/Game/HQ/HQ_Dusk", "-game",
    "-PixelStreamingConnectionURL=ws://127.0.0.1:$($config.streamer_port)",
    # Offer every codec (H.264, VP8, VP9, AV1) and let the browser pick one it can decode. Forced to
    # H.264, a browser built without it got no video: Unreal logged "Missing codec
    # from recv codec capabilities", the page gave up after 13 s and retried every 15 s.
    "-PixelStreamingWebRTCNegotiateCodecs",
    # Remote Control's HTTP API (localhost only): the backend moves the scene's people from studio state.
    "-RCWebControlEnable",
    # A development binary prints engine warnings over the picture; the stream must not show them.
    # The game otherwise starts at scalability level 3 (High): the quality groups are asked for Epic
    # here, where they apply to the streamed game only, and the tonemapper sharpens a little to hold
    # detail through the stream's own compression.
    # The encoder's own quality. Everything here runs on one machine over the loopback, so there is
    # no network to spare: the picture may as well be encoded at the highest quality the codec has.
    # At the defaults (MinQP 0 but a start bitrate of 1 Mbit and a 20 Mbit ceiling) WebRTC settles
    # low and the stream softens every edge - the Owner reads that as a lack of clarity.
    "-PixelStreamingWebRTCStartBitrate=40000000", "-PixelStreamingWebRTCMaxBitrate=100000000",
    "-PixelStreamingWebRTCMinBitrate=20000000", "-PixelStreamingEncoderMaxQP=18",
    "-ExecCmds=`"DisableAllScreenMessages,sg.ViewDistanceQuality 4,sg.AntiAliasingQuality 4,sg.ShadowQuality 4,sg.GlobalIlluminationQuality 4,sg.ReflectionQuality 4,sg.PostProcessQuality 4,sg.TextureQuality 4,sg.EffectsQuality 4,sg.FoliageQuality 4,sg.ShadingQuality 4,r.Tonemapper.Sharpen 0.6,r.ScreenPercentage 150,r.MotionBlurQuality 0,PixelStreaming.Encoder.MaxQP 18,PixelStreaming.WebRTC.MaxBitrate 100000000,PixelStreaming.WebRTC.StartBitrate 40000000,PixelStreaming.WebRTC.MinBitrate 20000000`"",
    "-ResX=$ResX", "-ResY=$ResY", "-ForceRes", "-nosplash", "-unattended"
)
if (-not $Windowed) { $ueArgs += "-RenderOffScreen" } else { $ueArgs += "-windowed" }
$ueArgs += $ExtraArgs
$ue = Start-Process -FilePath (Join-Path $ueRoot "Engine\Binaries\Win64\UnrealEditor.exe") -ArgumentList $ueArgs -PassThru
Write-Output "unreal pid $($ue.Id): streaming /Game/HQ/HQ_Dusk at ${ResX}x${ResY}"
