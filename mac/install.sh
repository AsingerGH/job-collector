#!/bin/bash
# One-time Mac setup. Run from inside the cloned repo:  bash mac/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
command -v python3 >/dev/null || { echo "Install Python 3.12+ first: https://www.python.org/downloads/"; exit 1; }
python3 -m venv .venv
./.venv/bin/pip install -q -r requirements.txt
chmod +x mac/run.sh
PLIST="$HOME/Library/LaunchAgents/com.andrew.jobcollector.plist"
cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.andrew.jobcollector</string>
  <key>ProgramArguments</key><array><string>$REPO/mac/run.sh</string></array>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>7</integer><key>Minute</key><integer>5</integer></dict>
    <dict><key>Hour</key><integer>19</integer><key>Minute</key><integer>5</integer></dict>
  </array>
  <key>RunAtLoad</key><false/>
</dict></plist>
EOF
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "Installed. Runs at 7:05 AM and 7:05 PM when the Mac is awake (missed runs fire on wake)."
echo "Test now with: ./mac/run.sh   then check: tail -50 ~/Library/Logs/job-collector.log"
