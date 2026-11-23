#!/bin/bash
# Runs the LinkedIn-heavy collector from Andrew's Mac (home internet) and pushes results.
# Installed by mac/install.sh as a launchd job; safe to run by hand: ./mac/run.sh
set -euo pipefail
cd "$(dirname "$0")/.."
LOG="$HOME/Library/Logs/job-collector.log"
{
  echo "=== $(date) ==="
  git pull --rebase -X theirs --quiet || true
  ./.venv/bin/python -m collector.collect --runner mac
  git add data/mac
  git diff --cached --quiet || git commit -qm "data: mac run $(date +%F_%H%M)"
  git pull --rebase -X theirs --quiet && git push --quiet
  echo "pushed"
} >>"$LOG" 2>&1
