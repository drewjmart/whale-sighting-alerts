<#
.SYNOPSIS
  Registers the /whales Discord bot (discord_bot/run_forever.py) as a
  Windows Scheduled Task that starts at boot and keeps running.

.DESCRIPTION
  Uses the PowerShell ScheduledTasks module rather than schtasks.exe --
  schtasks.exe is known (from the live alert task's own setup) to fail
  silently on a path containing spaces, which this project's path has
  ("claude project folder").

  This is a genuinely different operational shape than the 30-minute
  WhaleAlertMonitor task: that one runs once and exits every trigger.
  This one is meant to run continuously -- one trigger (at startup),
  one long-lived process, with Task Scheduler's own failure-restart
  policy as a second safety net on top of run_forever.py's internal
  backoff loop (covers the process being killed hard enough that
  run_forever.py itself doesn't get a chance to restart anything).

  Uses pythonw.exe (no console window) from this project's own venv --
  not the system Python -- since that's where discord.py is installed.

  Run only when you are logged on (no stored credentials needed) --
  if you need it to run while logged out too, that requires an
  explicit -Credential prompt, which this script deliberately doesn't
  do on your behalf.

.NOTES
  Run this from an elevated (Administrator) PowerShell prompt.
  Safe to re-run -- unregisters any existing task of the same name first.
#>

$ErrorActionPreference = "Stop"

$TaskName    = "WhaleDiscordBot"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonwExe  = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"

if (-not (Test-Path $PythonwExe)) {
    throw "Could not find $PythonwExe -- activate/create the venv and install requirements.txt first."
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing '$TaskName' task before re-registering..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$action = New-ScheduledTaskAction `
    -Execute $PythonwExe `
    -Argument "-m discord_bot.run_forever" `
    -WorkingDirectory $ProjectRoot

$trigger = New-ScheduledTaskTrigger -AtStartup

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 0)   # 0 = no time limit; this must run indefinitely

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Runs the /whales Discord slash command bot continuously (discord_bot/run_forever.py)." `
    | Out-Null

Write-Host "Registered scheduled task '$TaskName'."
Write-Host "It will start automatically at the next boot."
Write-Host ""
Write-Host "To start it right now instead of waiting for a reboot:"
Write-Host "    Start-ScheduledTask -TaskName $TaskName"
Write-Host ""
Write-Host "To check on it:"
Write-Host "    Get-ScheduledTask -TaskName $TaskName | Get-ScheduledTaskInfo"
Write-Host "    Get-Content '$ProjectRoot\discord_bot_runner.log' -Tail 20 -Wait"
Write-Host ""
Write-Host "To stop and remove it:"
Write-Host "    Unregister-ScheduledTask -TaskName $TaskName -Confirm:`$false"
