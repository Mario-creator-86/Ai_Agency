# Registers AMN-AI as a Windows Scheduled Task named "AMN-AI Studio", so the studio — and with it
# the background worker that runs the day — starts at logon and at startup, and is restarted if it
# fails, without anyone keeping a terminal open. Until now the worker lived only inside the
# foreground uvicorn process that scripts/start.py launches: a reboot or a closed window ended
# autonomy silently. This is the Owner's script to run, from an elevated PowerShell; it is not run
# by the studio or by any agent.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_studio_service.ps1 [-RunWhenLoggedOff]
#
# The task runs the same command scripts/start.py runs, with --skip-frontend (the bundle in
# frontend/dist is used as it is; build it once with start.cmd before installing). Registering
# again replaces the task in place, so this is also how a changed path or option is applied.
#
# -RunWhenLoggedOff makes the task run whether the Owner is signed in or not (S4U logon: no
# password is stored). Without it the task runs in the signed-in session and the startup trigger
# only takes effect once the Owner signs in. The daily job stays dormant either way: starting the
# studio's clock is the Owner's recorded act from the panel, not something this task does.

param(
    [string]$TaskName = "AMN-AI Studio",
    [switch]$RunWhenLoggedOff
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = (Resolve-Path (Join-Path $here "..")).Path

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) {
    throw "uv was not found on PATH. Install it from https://docs.astral.sh/uv/ and run this script again."
}
if (-not (Test-Path (Join-Path $repo "frontend\dist\index.html"))) {
    throw "frontend\dist\index.html does not exist. Run start.cmd once to build the frontend, then install the task."
}

# Everything the studio prints goes to a file the Owner can read, since a scheduled task has no
# window. data\ is ignored by Git, like the database beside it.
$logDir = Join-Path $repo "data"
New-Item -ItemType Directory -Force $logDir | Out-Null
$log = Join-Path $logDir "studio-service.log"

# cmd.exe carries the redirection; the task itself cannot. The start script is what start.cmd
# runs, minus the frontend build.
$command = "`"`"$($uv.Source)`" run python `"$repo\scripts\start.py`" --skip-frontend >> `"$log`" 2>&1`""
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $command" -WorkingDirectory $repo

$triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn),
    (New-ScheduledTaskTrigger -AtStartup)
)

# No execution time limit (the default stops a task after three days), three restarts one minute
# apart when the process exits with an error, one instance at a time, and the machine's power
# state left alone: a laptop on battery still runs its studio.
$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd

$user = "$env:USERDOMAIN\$env:USERNAME"
if ($RunWhenLoggedOff) {
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType S4U -RunLevel Limited
} else {
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -ne $existing) {
    # A running instance keeps the old command line until it exits; replacing the definition
    # underneath it is harmless, but the Owner should know which one is running.
    $state = (Get-ScheduledTaskInfo -TaskName $TaskName).LastTaskResult
    Write-Output "Task '$TaskName' already exists (last result $state); replacing its definition."
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggers `
    -Settings $settings -Principal $principal -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
Write-Output ""
Write-Output "Registered scheduled task '$($task.TaskName)'"
Write-Output "  Runs as          : $($task.Principal.UserId) ($($task.Principal.LogonType))"
Write-Output "  Command          : cmd.exe $($task.Actions[0].Arguments)"
Write-Output "  Working directory: $($task.Actions[0].WorkingDirectory)"
Write-Output "  Triggers         : at logon, at startup"
Write-Output "  On failure       : restart up to 3 times, 1 minute apart; no execution time limit"
Write-Output "  Output           : $log"
Write-Output ""
Write-Output "Check it with:   schtasks /Query /TN `"$TaskName`" /V /FO LIST"
Write-Output "Start it now:    Start-ScheduledTask -TaskName `"$TaskName`""
Write-Output "Stop it:         Stop-ScheduledTask -TaskName `"$TaskName`""
Write-Output "Remove it:       powershell -ExecutionPolicy Bypass -File scripts\uninstall_studio_service.ps1"
