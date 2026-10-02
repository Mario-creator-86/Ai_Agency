# The towers-by-day window, one step at a time (PREPARED 2026-09-24, NEVER RUN). Dot-source it, then
# call the steps by hand in the order of the window brief; nothing runs on load.
#
#   . "<this folder>\day_pass.ps1"
#   Preflight; Backup; Masks; HoldReport; StopStream; Pass; Merge; StartStream; ...; Release
#   (Rollback restores everything the pass touched)
#
# Rules it keeps: only the stream's own processes are stopped (by name and command line, as
# rebuild_live_hq.ps1 does); the Owner's studio (start.py / scripts\run.py on :8000) is never touched;
# a commandlet fails on a non-zero exit, on a fatal line or "Failed to compile Material" in its log,
# and on a log without "finished execution (result 0)".

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
# The repository is three folders up from this file, wherever it was cloned.
$repo = (Resolve-Path (Join-Path $here '..\..\..')).Path
$ue = "$repo\art-source\unreal"
$unrealDir = $ue
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
$out = Join-Path (Split-Path -Parent $here) 'window'
New-Item -ItemType Directory -Force $out | Out-Null
# Read at load without failing (nothing runs on load); Preflight refuses when it is missing.
$ueRoot = Get-AmnPath 'AMN_UE_ROOT' 'Unreal Engine root (the folder holding Engine\Binaries)' -Optional
$ueCmd = if ($ueRoot) { Join-Path $ueRoot 'Engine\Binaries\Win64\UnrealEditor-Cmd.exe' } else { $null }
$uproject = "$ue\AMNReference\AMNReference.uproject"
$umap = "$ue\AMNReference\Content\HQ\HQ_Dusk.umap"
$envReport = "$ue\env_report.json"
$held = "$ue\env_report.held.json"
$py = 'py.exe'

function Log($line) { Add-Content -Path "$out\commands_log.txt" -Value ('{0:HH:mm:ss} {1}' -f (Get-Date), $line) -Encoding utf8; $line }
function FreeCommit { [math]::Round((Get-CimInstance Win32_OperatingSystem).FreeVirtualMemory / 1MB, 1) }
# Every game the Owner plays on this machine (2026-09-26 he moved from Path of Exile to League of
# Legends mid-window; a check that knew only one of them would have kept the GPU busy under him).
function Games { @(Get-Process PathOfExile*, 'League of Legends', LeagueClient* -ErrorAction SilentlyContinue) }
function StreamProcs {
    Get-CimInstance Win32_Process | Where-Object {
        ($_.Name -eq 'UnrealEditor.exe' -and $_.CommandLine -match 'PixelStreamingConnectionURL') -or
        ($_.Name -eq 'node.exe' -and $_.CommandLine -match 'SignallingWebServer\\dist\\index\.js')
    }
}

function Preflight {
    if (-not $ueRoot) { $null = Get-AmnPath 'AMN_UE_ROOT' 'Unreal Engine root (the folder holding Engine\Binaries)' }
    # the pass needs >= 16 GB of free commit with the stream stopped; the stream gives back what it
    # holds (about 13 GB) when it stops
    $free = FreeCommit
    $streamGB = 0.0; StreamProcs | ForEach-Object { $streamGB += [double]$_.PrivatePageCount / 1GB }
    $projected = [math]::Round($free + $streamGB, 1)
    $games = Games
    $studio = Test-NetConnection 127.0.0.1 -Port 8000 -InformationLevel Quiet -WarningAction SilentlyContinue
    Log "PREFLIGHT free commit $free GB, stream holds $([math]::Round($streamGB,1)) GB, projected with the stream stopped $projected GB (need >= 16); games $($games.Count); studio :8000 up $studio"
    if ($games.Count -gt 0) { throw 'a game of the Owner runs: no window now' }
    if ($projected -lt 16) { throw "only $projected GB would be free with the stream stopped: no window now" }
}

function Backup([string]$Root = '') {
    # The backup folder is the operator's: -Root, else AMN_BACKUP_ROOT (environment or .env.paths).
    if (-not $Root) { $Root = Get-AmnPath 'AMN_BACKUP_ROOT' 'folder the HQ backups go to' }
    $stamp = Get-Date -Format 'yyyyMMdd_HHmm'
    $bk = Join-Path $Root "hq_before_towers_day_$stamp"
    New-Item -ItemType Directory -Force $bk | Out-Null
    robocopy "$ue\AMNReference\Content\HQ" "$bk\Content\HQ" /E /NFL /NDL /NJH /NJS | Out-Null; $a = $LASTEXITCODE
    robocopy "$ue\AMNReference\Content\AMN" "$bk\Content\AMN" /E /NFL /NDL /NJH /NJS | Out-Null; $b = $LASTEXITCODE
    foreach ($f in 'env_report.json', 'look_baseline.json', 'hq_scene.json') { if (Test-Path "$ue\$f") { Copy-Item "$ue\$f" "$bk\$f" } }
    $h1 = (Get-FileHash $umap -Algorithm SHA256).Hash; $h2 = (Get-FileHash "$bk\Content\HQ\HQ_Dusk.umap" -Algorithm SHA256).Hash
    Set-Content "$out\backup_path.txt" $bk -Encoding utf8
    Log "BACKUP $bk robocopy HQ $a AMN $b (0-7 = copied); umap $h1 backup $h2 equal $($h1 -eq $h2)"
    if ($a -ge 8 -or $b -ge 8 -or $h1 -ne $h2) { throw 'backup incomplete: no window' }
}

function Masks {
    & $py -3.11 "$here\towers_day.py" 2>&1 | Tee-Object "$out\masks.log" | Select-Object -Last 2
    if ($LASTEXITCODE -ne 0) { throw 'towers_day.py failed' }
}

function HoldReport {
    # while the report is aside the Owner's running studio sends nothing (it says so once)
    Move-Item $envReport $held -Force; Log "env_report.json held aside as env_report.held.json"
}
function Release {
    Move-Item $held $envReport -Force; Log "env_report.json back in place: the Owner's studio drives the environment from its next pass"
}

function StopStream { StreamProcs | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -Confirm:$false; Log "stopped $($_.Name) $($_.ProcessId)" } }

$Failure = @('LogPython: Error', 'Fatal error', 'Ran out of memory', 'paging file is too small', 'Unhandled Exception', 'Failed to compile Material')
function RunScript([string]$script, [string]$extra = '') {
    $name = [IO.Path]::GetFileNameWithoutExtension($script)
    $log = "$out\ue_$name.log"
    $min = FreeCommit
    $ErrorActionPreference = 'Continue'
    # Start-Process joins its arguments with spaces and quotes nothing: the project path has one
    $args2 = @("`"$uproject`"", '-run=pythonscript', "-script=$($script -replace '\\','/')", '-unattended', '-nosplash', "-abslog=$log")
    if ($extra) { $args2 += $extra }
    $p = Start-Process -FilePath $ueCmd -ArgumentList $args2 -PassThru -NoNewWindow
    while (-not $p.HasExited) { Start-Sleep -Milliseconds 2000; $f = FreeCommit; if ($f -lt $min) { $min = $f } }
    $code = $p.ExitCode
    $ErrorActionPreference = 'Stop'
    $hits = @(Select-String -LiteralPath $log -Pattern $Failure -SimpleMatch -ErrorAction SilentlyContinue | Select-Object -First 5 | ForEach-Object { $_.Line.Trim() })
    $done = [bool](Select-String -LiteralPath $log -Pattern 'finished execution \(result 0\)' -Quiet -ErrorAction SilentlyContinue)
    Select-String -LiteralPath $log -Pattern 'AMN_(TOWERS|TREES_DAY|SIGN|NANITE) ' -ErrorAction SilentlyContinue | ForEach-Object { '   ' + $_.Line.Substring($_.Line.IndexOf('AMN_')) }
    Log "RAN $name exit $code finished $done min free commit $min GB$(if ($hits) { '; ' + $hits[0] })"
    if ($code -ne 0 -or $hits.Count -gt 0 -or -not $done) { throw "$name failed (log $log): ROLLBACK" }
}

function Pass {
    if (StreamProcs) { throw 'the stream still runs: StopStream first' }
    if (Games) { throw 'a game of the Owner runs' }
    # at most four shader workers (the default is 15 on this machine): a new master's first compile
    # must not take the commit the Owner's programs live on. UNVERIFIED switch: if the log shows
    # "Using 15 local workers" it was ignored, which costs memory, not correctness.
    $cap = '-ini:Engine:[DevOptions.Shaders]:NumUnusedShaderCompilingThreads=12'
    RunScript "$here\towers_day_hq_live.py" $cap
    RunScript "$here\trees_day_hq_live.py" $cap
    RunScript "$here\sign_hq_live.py"
}

function NaniteSkylineTest {
    # names the sign's cause (see sign_hq_live.py): Nanite off on the skyline too; the next rebuild
    # restores Nanite, so this is a diagnosis unless it is made a rebuild default
    $env:AMN_NANITE_OFF = 'glow_details,skyline'
    try { RunScript "$ue\nanite_hq_live.py" } finally { $env:AMN_NANITE_OFF = $null }
}

function Merge { & $py -3.11 "$here\day_state.py" merge --env-report $held --towers-report "$here\towers_report.json"; if ($LASTEXITCODE -ne 0) { throw 'merge refused' } ; Log 'day_state merged into the held report' }
function DriveDay([double]$elevation, [switch]$Morning, [switch]$Haze) {
    $a = @("$here\day_state.py", 'drive', '--env-report', $held, '--elevation', "$elevation")
    if ($Morning) { $a += '--morning' }; if ($Haze) { $a += '--haze' }
    & $py -3.11 @a; Log "DRIVE day extras at $elevation deg morning $Morning haze $Haze exit $LASTEXITCODE"
}

function StartStream([int]$frames = 90000) {
    if (Games) { throw 'a game of the Owner runs' }
    $free = FreeCommit
    if ($free -lt 14) { throw "only $free GB free: the stream needs about 13 GB within 25 s" }
    $since = Get-Date
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$ue\live\start_live_hq.ps1" -ExtraArgs "-csvCaptureFrames=$frames"
    Log "start_live_hq.ps1 exit $LASTEXITCODE (free before $free GB); wait for endpointIdConfirm after $since"
}

function Rollback {
    $bk = Get-Content "$out\backup_path.txt" | Select-Object -First 1
    StopStream
    robocopy "$bk\Content\HQ" "$ue\AMNReference\Content\HQ" /MIR /NFL /NDL /NJH /NJS | Out-Null; $a = $LASTEXITCODE
    robocopy "$bk\Content\AMN" "$ue\AMNReference\Content\AMN" /MIR /NFL /NDL /NJH /NJS | Out-Null; $b = $LASTEXITCODE
    if (Test-Path "$bk\env_report.json") { Copy-Item "$bk\env_report.json" $envReport -Force }
    if (Test-Path $held) { Move-Item $held "$ue\env_report.rejected_towers_$(Get-Date -Format 'yyyyMMdd_HHmm').json" -Force }
    $ok = (Get-FileHash $umap -Algorithm SHA256).Hash -eq (Get-FileHash "$bk\Content\HQ\HQ_Dusk.umap" -Algorithm SHA256).Hash
    Log "ROLLBACK robocopy /MIR HQ $a AMN $b; env_report.json from the backup; umap equals backup $ok; now StartStream"
}
