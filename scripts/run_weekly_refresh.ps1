<#
.SYNOPSIS
  Runs the dashboard database refresh (python -m ingestion.run_backfill) and
  appends everything it prints to ingestion_refresh.log.

.DESCRIPTION
  This is what the "WhaleDatabaseRefresh" scheduled task runs (see
  register_weekly_refresh_task.ps1) -- a wrapper rather than the task calling
  python directly because a scheduled run has no console: without it, a
  failed refresh would leave no trace at all. Safe to run by hand too.

  stdout and stderr are captured separately and appended in two labelled
  sections. Redirecting a native command's stderr with 2>&1 under Windows
  PowerShell 5.1 wraps every line in a NativeCommandError record, which
  would bury the useful INFO lines in noise.

  run_backfill is idempotent (dedupes on source + external ID), so a missed,
  repeated, or half-finished run is harmless.
#>

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python      = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Log         = Join-Path $ProjectRoot "ingestion_refresh.log"
$OutTmp      = Join-Path $env:TEMP "whale_refresh_stdout.tmp"
$ErrTmp      = Join-Path $env:TEMP "whale_refresh_stderr.tmp"

$env:PYTHONIOENCODING = "utf-8"
Set-Location $ProjectRoot

"=== $(Get-Date -Format s) weekly refresh starting ===" | Add-Content -Path $Log -Encoding utf8

$proc = Start-Process -FilePath $Python -ArgumentList "-m", "ingestion.run_backfill" `
    -WorkingDirectory $ProjectRoot -NoNewWindow -Wait -PassThru `
    -RedirectStandardOutput $OutTmp -RedirectStandardError $ErrTmp

"--- log output ---"  | Add-Content -Path $Log -Encoding utf8
Get-Content -Path $ErrTmp -Encoding utf8 -ErrorAction SilentlyContinue | Add-Content -Path $Log -Encoding utf8
"--- printed output ---" | Add-Content -Path $Log -Encoding utf8
Get-Content -Path $OutTmp -Encoding utf8 -ErrorAction SilentlyContinue | Add-Content -Path $Log -Encoding utf8
"=== $(Get-Date -Format s) finished (exit code $($proc.ExitCode)) ===" | Add-Content -Path $Log -Encoding utf8
"" | Add-Content -Path $Log -Encoding utf8

Remove-Item $OutTmp, $ErrTmp -ErrorAction SilentlyContinue
exit $proc.ExitCode
