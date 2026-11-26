#!/bin/bash
# /spont <entreprise> from Telegram (SPEC §10, V3). See spontaneous.py.
set -uo pipefail
export PATH="$HOME/.local/bin:$HOME/.bun/bin:/Library/TeX/texbin:/usr/bin:/bin:/usr/sbin:/sbin"
export LANG="${LANG:-en_US.UTF-8}" LC_ALL="${LC_ALL:-en_US.UTF-8}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO" || exit 1
SECRETS="${JOBBOT_SECRETS:-$HOME/.config/jobbot/secrets.env}"
if [ -f "$SECRETS" ]; then set -a; . "$SECRETS"; set +a; fi   # CLAUDE_CODE_OAUTH_TOKEN
STATE="${JOBBOT_STATE_DIR:-$REPO/jobbot/state}"; mkdir -p "$STATE/runs"
exec "$REPO/jobbot/.venv/bin/python" "$REPO/jobbot/scripts/spontaneous.py" "$@" >>"$STATE/runs/spont-$(TZ=Europe/Vienna date +%Y%m).log" 2>&1
