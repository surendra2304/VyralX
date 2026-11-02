# Registers the VyralX viral autopilot as a Windows scheduled task so the
# channel keeps producing and publishing unlisted Shorts after a reboot.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_autopilot_task.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_autopilot_task.ps1 -Uninstall
param(
    [switch]$Uninstall,
    [string]$TaskName = "VyralX Viral Autopilot"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"
$runner = Join-Path $root "scripts\run_viral_autopilot.py"

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task: $TaskName"
    exit 0
}

if (-not (Test-Path $python)) { throw "Python venv not found at $python" }
if (-not (Test-Path $runner)) { throw "Autopilot script not found at $runner" }

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "`"$runner`" --loop" `
    -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Produces and uploads unlisted VyralX Shorts in the channel's four proven formats." `
    -Force | Out-Null

Write-Host "Registered scheduled task: $TaskName"
Write-Host "  runs: $python `"$runner`" --loop"
Write-Host "  start: at logon, restart every 2 minutes on failure"
