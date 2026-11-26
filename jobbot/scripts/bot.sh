#!/bin/bash
# Telegram bot (launchd com.jobbot.telegram, KeepAlive). See jobbot/bot/bot.py.
set -uo pipefail
export PATH="$HOME/.local/bin:$HOME/.bun/bin:/Library/TeX/texbin:/usr/bin:/bin:/usr/sbin:/sbin"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO" || exit 1
SECRETS="${JOBBOT_SECRETS:-$HOME/.config/jobbot/secrets.env}"
if [ -f "$SECRETS" ]; then set -a; . "$SECRETS"; set +a; fi
STATE="${JOBBOT_STATE_DIR:-$REPO/jobbot/state}"; mkdir -p "$STATE/runs"
exec "$REPO/jobbot/.venv/bin/python" "$REPO/jobbot/bot/bot.py" >>"$STATE/runs/telegram-$(TZ=Europe/Vienna date +%Y%m).log" 2>&1
