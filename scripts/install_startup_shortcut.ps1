# Puts the VyralX autopilot in the current user's Startup folder so it comes
# back after a reboot. No administrator rights needed.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install_startup_shortcut.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install_startup_shortcut.ps1 -Uninstall
param(
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$target = Join-Path $root "scripts\start_autopilot.cmd"
$startup = [Environment]::GetFolderPath("Startup")
$link = Join-Path $startup "VyralX Autopilot.lnk"

if ($Uninstall) {
    Remove-Item -Force $link -ErrorAction SilentlyContinue
    Write-Host "Removed startup shortcut: $link"
    exit 0
}

if (-not (Test-Path $target)) { throw "Launcher not found at $target" }

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($link)
$shortcut.TargetPath = $target
$shortcut.WorkingDirectory = $root
$shortcut.WindowStyle = 7
$shortcut.Description = "VyralX viral autopilot - produces and uploads unlisted Shorts"
$shortcut.Save()

Write-Host "Installed startup shortcut: $link"
Write-Host "  target: $target"
