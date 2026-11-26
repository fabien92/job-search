#!/usr/bin/env python3
"""Weekly report (launchd com.jobbot.weekly, schedule.yaml weekly_report): SPEC §11, V2 — zero tokens.

    jobbot/.venv/bin/python jobbot/scripts/weekly.py

Last 7 days: postings seen / kept (alerted) / /go / sent / cancelled, answers (tracker statuses —
plus this week's /reply answers and logged follow-ups, V5), sites that bring nothing, sites down, estimated
cost (scans + /go). Test runs (-test) and T-IDs are left out. Always sends.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from collections import Counter

import applications as apps
import common
import telegram_send as tg
from i18n import t

DAYS = 7
ANSWERS = {"interview", "offer", "hired", "rejected", "offer_declined", "offer declined"}


def runs_since(cutoff: dt.datetime) -> list[dict]:
    out = []
    for path in common.runs_dir().glob("2*.json"):
        if not re.fullmatch(r"\d{8}T\d{6}", path.stem):
            continue
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        fin = common.parse_iso(s.get("finished"))
        if fin and fin >= cutoff:
            out.append(s)
    return out


def site_health(today: dt.date) -> tuple[list[str], list[str]]:
    """-> (sites with 0 results over the week, sites with at least one day where every query failed)."""
    stats = common.read_json(common.state_dir() / "site_stats.json", {}) or {}
    days = {(today - dt.timedelta(days=i)).isoformat() for i in range(DAYS)}
    empty, down = [], []
    for site, per_day in sorted(stats.items()):
        week = {d: v for d, v in per_day.items() if d in days}
        queries = sum(int(v.get("queries") or 0) for v in week.values())
        if not queries:
            continue
        if sum(int(v.get("results") or 0) for v in week.values()) == 0:
            empty.append(site)
        bad = sum(1 for v in week.values() if int(v.get("queries") or 0) and int(v.get("errors") or 0) >= int(v["queries"]))
        if bad:
            down.append(t("weekly.down_days", site=site, n=bad))
    return empty, down


def collect() -> dict:
    now = common.now()
    cutoff = now - dt.timedelta(days=DAYS)
    runs = runs_since(cutoff)
    events = [e for e in apps.read_events() if (common.parse_iso(e.get("at")) or cutoff) > cutoff]
    kinds = Counter(e.get("kind") for e in events)
    _, rows = apps.read_tracker()
    answers = Counter((r.get("status") or "").strip() for r in rows if (r.get("status") or "").strip() in ANSWERS)
    empty, down = site_health(common.local_now().date())
    scan_cost = round(sum(float(s.get("total_cost_usd") or 0) for s in runs), 2)
    go_cost = round(sum(float(e.get("cost_usd") or 0) for e in events if e.get("kind") == "go"), 2)
    return {
        "runs": len(runs), "failed": sum(1 for s in runs if s.get("status") != "ok"),
        "seen": sum(int(s.get("seen") or 0) for s in runs), "new": sum(int(s.get("new") or 0) for s in runs),
        "scored": sum(int(s.get("scored") or 0) for s in runs), "alerted": sum(int(s.get("alerted") or 0) for s in runs),
        "go": kinds["go"], "adapted": sum(1 for e in events if e.get("kind") == "go" and e.get("adapted")),
        "sent": kinds["sent"], "cancelled": kinds["cancel"], "answers": dict(answers),
        "replies": {"yes": sum(1 for e in events if e.get("kind") == "reply" and e.get("answer") == "yes"),
                    "no": sum(1 for e in events if e.get("kind") == "reply" and e.get("answer") == "no"),
                    "followups": kinds["followup"]},
        "pending": len(apps.load_pending(False)), "empty_sites": empty, "down_sites": down,
        "scan_cost": scan_cost, "go_cost": go_cost,
    }


def build(data: dict | None = None) -> str:
    d = data or collect()
    end = common.local_now()
    start = end - dt.timedelta(days=DAYS)
    lines = [t("weekly.title", start=start.strftime('%d/%m'), end=end.strftime('%d/%m/%Y')),
             t("weekly.runs", runs=d['runs'], failed=d['failed']),
             t("weekly.offers", seen=d['seen'], new=d['new'], scored=d['scored'], alerted=d['alerted']),
             t("weekly.applications_one" if d['adapted'] <= 1 else "weekly.applications_many", go=d['go'],
               adapted=d['adapted'], sent=d['sent'], cancelled=d['cancelled'], pending=d['pending'])]
    if d["answers"]:
        detail = ", ".join(f"{k} {v}" for k, v in sorted(d["answers"].items()))
        lines.append(t("weekly.answers", detail=tg.esc(detail)))
    else:
        lines.append(t("weekly.no_answers"))
    r = d.get("replies") or {}
    if any(r.values()):
        lines.append(t("weekly.replies", yes=r.get("yes", 0), no=r.get("no", 0), followups=r.get("followups", 0)))
    none = t("common.none_m")
    lines.append(t("weekly.empty_sites", sites=tg.esc(", ".join(d["empty_sites"])) if d["empty_sites"] else none))
    lines.append(t("weekly.down_sites", sites=tg.esc(", ".join(d["down_sites"])) if d["down_sites"] else none))
    total = round(d["scan_cost"] + d["go_cost"], 2)
    lines.append(t("weekly.cost", total=total, scan=d['scan_cost'], go=d['go_cost']))
    return "\n".join(lines)


def main() -> int:
    tg.send(build())
    return 0


if __name__ == "__main__":
    sys.exit(main())
