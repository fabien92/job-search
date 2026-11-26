#!/bin/bash
# V5, one time: move the alerts sent before the offer queue (still open) into it. See offer_queue.backfill.
#   bash jobbot/scripts/queue_backfill.sh --preview   # list only
#   bash jobbot/scripts/queue_backfill.sh             # add them; the best one is shown on Telegram
set -uo pipefail
export LANG="${LANG:-en_US.UTF-8}" LC_ALL="${LC_ALL:-en_US.UTF-8}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO" || exit 1
SECRETS="${JOBBOT_SECRETS:-$HOME/.config/jobbot/secrets.env}"
if [ -f "$SECRETS" ]; then set -a; . "$SECRETS"; set +a; fi   # TELEGRAM_TOKEN / TELEGRAM_CHAT_ID
unset JOBBOT_DRY_RUN
exec "$REPO/jobbot/.venv/bin/python" "$REPO/jobbot/scripts/offer_queue.py" --backfill "$@"
