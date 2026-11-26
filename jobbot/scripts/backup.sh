#!/bin/bash
# Nightly backup (launchd com.jobbot.backup). See backup.py.
set -uo pipefail
export PATH="$HOME/.local/bin:$HOME/.bun/bin:/Library/TeX/texbin:/usr/bin:/bin:/usr/sbin:/sbin"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO" || exit 1
SECRETS="${JOBBOT_SECRETS:-$HOME/.config/jobbot/secrets.env}"
if [ -f "$SECRETS" ]; then set -a; . "$SECRETS"; set +a; fi
unset CLAUDE_CODE_OAUTH_TOKEN
STATE="${JOBBOT_STATE_DIR:-$REPO/jobbot/state}"; mkdir -p "$STATE/runs"
exec "$REPO/jobbot/.venv/bin/python" "$REPO/jobbot/scripts/backup.py" >>"$STATE/runs/backup-$(TZ=Europe/Vienna date +%Y%m).log" 2>&1
