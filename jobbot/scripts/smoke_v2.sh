#!/bin/bash
# V2 real test in TEST MODE (SPEC §12-13): real portals, real Claude, real LaTeX, real Telegram ([TEST]).
# Nothing definitive is written: T-IDs only (no tracker, no ledger, no pending.json, no documents/applications).
#   bash jobbot/scripts/smoke_v2.sh            # scan karriere (test mode), then /go, /pending, resend, /firma, /sent
#   bash jobbot/scripts/smoke_v2.sh --no-scan  # reuse the T-IDs of the last test scan
set -uo pipefail
export PATH="$HOME/.local/bin:$HOME/.bun/bin:/Library/TeX/texbin:/usr/bin:/bin:/usr/sbin:/sbin"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO" || exit 1
PY="$REPO/jobbot/.venv/bin/python"
export JOBBOT_DRY_RUN=1

if [ "${1:-}" != "--no-scan" ]; then
  echo "== 1. test run (karriere)"
  bash jobbot/scripts/run_scan.sh --site karriere
  echo "   log: $(ls -t jobbot/state/runs/scan-*.log | head -1)"
fi

echo "== 2. test postings alerted"
IDS=$("$PY" - <<'EOF'
import sys; sys.path[:0] = ["jobbot/scripts"]
import applications as apps
jobs = apps._test_alerts()
for sid, j in sorted(jobs.items(), key=lambda kv: int(kv[0][1:])):
    print(f"   {sid} · {j.get('score')} · {j.get('company')} · {j.get('title')} · variante={j.get('variant')} adapt={j.get('adapt')}", file=sys.stderr)
no = next((s for s, j in jobs.items() if not j.get("adapt") and not apps.get_pending(s)), "")
yes = next((s for s, j in jobs.items() if j.get("adapt") and not apps.get_pending(s)), "")
print(no, yes)
EOF
)
read -r NO YES <<<"$IDS"
[ -z "${NO}${YES}" ] && { echo "   no test posting available (no alert, or /go already done)"; exit 1; }

for sid in $NO $YES; do
  echo "== 3. /go $sid"
  "$PY" jobbot/scripts/go.py "$sid"; echo "   exit $?"
  tail -3 "jobbot/state/runs/go-$(TZ=Europe/Vienna date +%Y%m%d).log" 2>/dev/null
done
[ -z "$YES" ] && echo "   (no posting with adaptation in this run: the Claude path is not tested for real)"

echo "== 4. /pending, renvoi, /firma, /sent"
"$PY" - "$NO" "$YES" <<'EOF'
import re, sys; sys.path[:0] = ["jobbot/scripts", "jobbot/bot"]
import applications as apps, logic
plain = lambda t: re.sub(r"<[^>]+>", "", t)
ids = [s for s in sys.argv[1:] if s]
text, buttons = logic.cmd_pending_view()
print(plain(text)); print("   boutons :", [b[0] for b in buttons])
first = ids[0]
print(plain(logic.resend_files(first)))
company = (apps.get_pending(first) or {}).get("company") or "x"
print(plain(logic.cmd_firma(company.split()[0])))
for sid in ids:
    print(plain(logic.cmd_sent(sid)))
print(plain(logic.cmd_pending()))
EOF

echo "== 5. bilan hebdomadaire ([TEST] sur Telegram)"
"$PY" jobbot/scripts/weekly.py && echo "   sent"
echo "== fichiers : $HOME/Library/Caches/jobbot/test-applications/"
ls -R "$HOME/Library/Caches/jobbot/test-applications/" 2>/dev/null | head -30
