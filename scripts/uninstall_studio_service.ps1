# Removes the "AMN-AI Studio" scheduled task that scripts\install_studio_service.ps1 registered.
# A running instance is stopped first, so the studio's worker stops with it. This is the Owner's
# script to run, from an elevated PowerShell; it is not run by the studio or by any agent.
#
#   powershell -ExecutionPolicy Bypass -File scripts\uninstall_studio_service.ps1
#
# Running it when no task exists is not an error: it says so and does nothing. The database, the
# credential key and data\studio-service.log are left where they are.

param(
    [string]$TaskName = "AMN-AI Studio"
)

$ErrorActionPreference = "Stop"

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($null -eq $task) {
    Write-Output "No scheduled task named '$TaskName' is registered. Nothing to remove."
    exit 0
}

if ($task.State -eq "Running") {
    Write-Output "Stopping the running instance of '$TaskName'."
    Stop-ScheduledTask -TaskName $TaskName
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Output "Removed scheduled task '$TaskName'. The studio no longer starts on its own."
Write-Output "Start it by hand with start.cmd, or register the task again with scripts\install_studio_service.ps1."
