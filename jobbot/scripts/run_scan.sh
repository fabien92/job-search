#!/bin/bash
# JobBot scan (SPEC §12): launchd com.jobbot.scan every 4 h, or /search from Telegram.
#   bash jobbot/scripts/run_scan.sh [--site all|karriere|linkedin|derstandard|uncareers|unido|osce|opecfund|hays|jobgether|randstad|profession|kariera|michaelpage|companies]
#   JOBBOT_DRY_RUN=1 bash jobbot/scripts/run_scan.sh      # test mode: [TEST] messages, no definitive writes
# Steps (in scan.py): lock -> prefilter (scripts) -> claude -p "/jobbot-scan <id>"
#   --permission-mode dontAsk --permission-prompts none --output-format json
#   --max-budget-usd <schedule.yaml> -> postprocess (scripts) -> Telegram -> monitoring.
set -uo pipefail

# launchd gives a minimal PATH: always set it explicitly (SPEC §1).
export PATH="$HOME/.local/bin:$HOME/.bun/bin:/Library/TeX/texbin:/usr/bin:/bin:/usr/sbin:/sbin"
export LANG="${LANG:-en_US.UTF-8}" LC_ALL="${LC_ALL:-en_US.UTF-8}"

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO" || exit 1
PY="$REPO/jobbot/.venv/bin/python"

SECRETS="${JOBBOT_SECRETS:-$HOME/.config/jobbot/secrets.env}"
if [ -f "$SECRETS" ]; then
  mode=$(stat -f '%Lp' "$SECRETS" 2>/dev/null || echo 600)
  [ "$mode" = "600" ] || echo "run_scan: warning: $SECRETS has mode $mode, expected 600" >&2
  set -a
  # shellcheck disable=SC1090
  . "$SECRETS"
  set +a
else
  echo "run_scan: warning: $SECRETS not found" >&2
fi

if [ ! -x "$PY" ]; then
  echo "run_scan: $PY missing — run jobbot/scripts/setup_venv.sh" >&2
  exit 1
fi

STATE="${JOBBOT_STATE_DIR:-$REPO/jobbot/state}"
mkdir -p "$STATE/runs"
LOG="$STATE/runs/scan-$(TZ=Europe/Vienna date +%Y%m%d).log"
# Zero-token pre-flight: secrets, Telegram getMe, bun, lualatex, venv, disk, whitelist and
# sandbox settings, Claude token expiry. A failure stops the run here (exit 4) with a Telegram alert.
"$PY" "$REPO/jobbot/scripts/preflight.py" --for scan >>"$LOG" 2>&1
code=$?
if [ $code -ne 0 ]; then
  echo "run_scan: pre-flight check failed (exit $code) - run cancelled (log: $LOG)"
  exit $code
fi

"$PY" "$REPO/jobbot/scripts/scan.py" "$@" >>"$LOG" 2>&1
code=$?
echo "run_scan: exit $code (log: $LOG)"
exit $code
