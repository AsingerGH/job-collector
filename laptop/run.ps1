# Runs the LinkedIn-heavy collector from Andrew's laptop (home internet) and pushes results to GitHub.
# Started by the "JobCollector" scheduled task; safe to run by hand:
#   powershell -ExecutionPolicy Bypass -File laptop\run.ps1
$Repo = Split-Path -Parent $PSScriptRoot
$Log = Join-Path $env:LOCALAPPDATA "job-collector.log"
$env:PYTHONUTF8 = "1"            # job titles can contain characters the Windows console can't print
Set-Location $Repo

function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Out-File -FilePath $Log -Append -Encoding utf8 }

Log "=== run start ==="
git pull --rebase -X theirs --quiet *>> $Log
& "$Repo\.venv\Scripts\python.exe" -m collector.collect --runner laptop *>> $Log
if ($LASTEXITCODE -ne 0) { Log "collector exited with code $LASTEXITCODE" }
git add data/laptop *>> $Log
git diff --cached --quiet
if ($LASTEXITCODE -ne 0) {
  git commit -qm "data: laptop run $(Get-Date -Format 'yyyy-MM-dd_HHmm')" *>> $Log
  git pull --rebase -X theirs --quiet *>> $Log
  git push --quiet *>> $Log
  if ($LASTEXITCODE -eq 0) { Log "pushed" } else { Log "PUSH FAILED - open GitHub Desktop or run 'git push' once to sign in" }
} else { Log "nothing new to push" }

# keep the log from growing forever
if ((Get-Item $Log).Length -gt 2MB) { Get-Content $Log -Tail 2000 | Set-Content $Log -Encoding utf8 }
