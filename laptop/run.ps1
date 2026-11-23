# Runs the LinkedIn-heavy collector from Andrew's laptop (home internet) and pushes results to GitHub.
# Started by the "JobCollector" scheduled task; safe to run by hand:
#   powershell -ExecutionPolicy Bypass -File laptop\run.ps1
#
# The laptop only ever owns data/laptop/. Everything else always matches GitHub exactly, so an
# interrupted run, a stray edit or line-ending noise can never block an update or a push.
$ErrorActionPreference = "Continue"
$Repo = Split-Path -Parent $PSScriptRoot
$Log = Join-Path $env:LOCALAPPDATA "job-collector.log"
$Keep = Join-Path $env:TEMP "job-collector-laptop-data"
$env:PYTHONUTF8 = "1"            # job titles can contain characters the Windows console can't print
Set-Location $Repo

function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Out-File -FilePath $Log -Append -Encoding utf8 }
function Invoke-Git([string[]]$a) { $out = & git @a 2>&1; $out | ForEach-Object { "$_" } | Out-File -FilePath $Log -Append -Encoding utf8; return $LASTEXITCODE }

function Sync-WithGitHub {
  # keep this laptop's newest data, take everything else from GitHub
  if (Test-Path "data\laptop") { Remove-Item $Keep -Recurse -Force -ErrorAction SilentlyContinue; Copy-Item "data\laptop" $Keep -Recurse -Force }
  Invoke-Git @("fetch", "--quiet", "origin") | Out-Null
  Invoke-Git @("reset", "--quiet", "--hard", "origin/main") | Out-Null
  if (Test-Path $Keep) { New-Item -ItemType Directory -Force "data\laptop" | Out-Null; Copy-Item "$Keep\*" "data\laptop" -Recurse -Force }
}

Log "=== run start ==="
& git config user.name "job-collector-laptop"            # commits need a name; set only for this folder
& git config user.email "laptop@job-collector.local"
Sync-WithGitHub
Log "code is at $(git rev-parse --short HEAD)"

& "$Repo\.venv\Scripts\python.exe" -m pip install -q -r requirements.txt *>> $Log   # picks up any new packages
& "$Repo\.venv\Scripts\python.exe" -m collector.collect --runner laptop *>> $Log
if ($LASTEXITCODE -ne 0) { Log "collector exited with code $LASTEXITCODE" }

$pushed = $false
for ($i = 1; $i -le 3 -and -not $pushed; $i++) {
  Sync-WithGitHub                                   # re-apply our data on top of the latest GitHub version
  Invoke-Git @("add", "data/laptop") | Out-Null
  & git diff --cached --quiet
  if ($LASTEXITCODE -eq 0) { Log "nothing new to push"; $pushed = $true; break }
  Invoke-Git @("commit", "--quiet", "-m", "data: laptop run $(Get-Date -Format 'yyyy-MM-dd_HHmm')") | Out-Null
  if ((Invoke-Git @("push", "--quiet", "origin", "HEAD:main")) -eq 0) { Log "pushed"; $pushed = $true }
  else { Log "push attempt $i rejected; retrying"; Start-Sleep -Seconds 10 }
}
if (-not $pushed) { Log "PUSH FAILED after 3 tries - send Claude the last 40 lines of this log" }

# keep the log from growing forever
if ((Get-Item $Log).Length -gt 2MB) { Get-Content $Log -Tail 2000 | Set-Content $Log -Encoding utf8 }
