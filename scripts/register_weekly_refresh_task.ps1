<#
.SYNOPSIS
  Registers a Windows Scheduled Task that refreshes the dashboard database
  once a week (scripts/run_weekly_refresh.ps1 -> ingestion.run_backfill).

.DESCRIPTION
  Nothing refreshed the dashboard database automatically before this -- the
  30-minute WhaleAlertMonitor task only sends notifications and never writes
  to it, so the dashboard drifted out of date (it was a month stale once).

  Sundays at 03:00. StartWhenAvailable means a run missed because the PC was
  off or asleep happens as soon as it's next on, and RunOnlyIfNetworkAvailable
  keeps it from failing against Acartia/NOAA with no connection. Runs as you,
  only while you're logged on (no stored credentials), so no elevation should
  be needed. Uses the PowerShell ScheduledTasks module rather than
  schtasks.exe, which fails silently on this project's path containing spaces.

  Safe to re-run -- replaces any existing task of the same name.
#>

$ErrorActionPreference = "Stop"

$TaskName    = "WhaleDatabaseRefresh"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Wrapper     = Join-Path $PSScriptRoot "run_weekly_refresh.ps1"

if (-not (Test-Path $Wrapper)) { throw "Could not find $Wrapper" }

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "Replacing existing '$TaskName' task..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Wrapper`"" `
    -WorkingDirectory $ProjectRoot

$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 3:00AM

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -RunOnlyIfNetworkAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Weekly refresh of the whale dashboard database (ingestion.run_backfill)." `
    | Out-Null

Write-Host "Registered '$TaskName': Sundays at 03:00 (runs on next wake if missed)."
Write-Host ""
Write-Host "Run it now:        Start-ScheduledTask -TaskName $TaskName"
Write-Host "Check last result: Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "Read the log:      Get-Content '$ProjectRoot\ingestion_refresh.log' -Tail 30"
Write-Host "Remove it:         Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
