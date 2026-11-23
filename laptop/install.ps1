# One-time setup on Andrew's Windows laptop. From inside the cloned repo folder, run:
#   powershell -ExecutionPolicy Bypass -File laptop\install.ps1
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
Set-Location $Repo

# Python check (install with:  winget install Python.Python.3.12)
$py = Get-Command py -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python -ErrorAction SilentlyContinue }
if (-not $py) { Write-Host "Python not found. Run:  winget install Python.Python.3.12   then reopen PowerShell and rerun this." -ForegroundColor Red; exit 1 }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Write-Host "Git not found. Run:  winget install Git.Git   then reopen PowerShell and rerun this." -ForegroundColor Red; exit 1 }

& $py.Source -m venv .venv
& "$Repo\.venv\Scripts\python.exe" -m pip install -q --upgrade pip
& "$Repo\.venv\Scripts\python.exe" -m pip install -q -r requirements.txt

# Scheduled task: 7:05 AM and 7:05 PM. If the laptop was asleep or off, it runs as soon as it's back.
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Repo\laptop\run.ps1`""
$triggers = @(
  (New-ScheduledTaskTrigger -Daily -At 7:05AM),
  (New-ScheduledTaskTrigger -Daily -At 7:05PM)
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "JobCollector" -Action $action -Trigger $triggers -Settings $settings `
  -Description "Andrew's job collector (LinkedIn/Indeed from home internet)" -Force | Out-Null

Write-Host "Installed. Windows will run the collector at 7:05 AM and 7:05 PM (missed runs start when the laptop wakes)." -ForegroundColor Green
Write-Host "Test it now:  powershell -ExecutionPolicy Bypass -File laptop\run.ps1"
Write-Host "Then check:   Get-Content `"$env:LOCALAPPDATA\job-collector.log`" -Tail 40"
