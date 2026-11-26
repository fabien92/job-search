#!/bin/bash
# /go <ID> from Telegram (SPEC §9, V2): one process per ID, several may run in parallel. See go.py.
#   bash jobbot/scripts/go.sh <ID> [--force]
set -uo pipefail
# The bot inherits launchd's minimal PATH: set it explicitly (SPEC §1) — lualatex/xelatex, claude.
export PATH="$HOME/.local/bin:$HOME/.bun/bin:/Library/TeX/texbin:/usr/bin:/bin:/usr/sbin:/sbin"
export LANG="${LANG:-en_US.UTF-8}" LC_ALL="${LC_ALL:-en_US.UTF-8}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO" || exit 1
SECRETS="${JOBBOT_SECRETS:-$HOME/.config/jobbot/secrets.env}"
if [ -f "$SECRETS" ]; then set -a; . "$SECRETS"; set +a; fi   # CLAUDE_CODE_OAUTH_TOKEN for adaptation: oui
STATE="${JOBBOT_STATE_DIR:-$REPO/jobbot/state}"; mkdir -p "$STATE/runs"
exec "$REPO/jobbot/.venv/bin/python" "$REPO/jobbot/scripts/go.py" "$@" >>"$STATE/runs/go-$(TZ=Europe/Vienna date +%Y%m%d).log" 2>&1
