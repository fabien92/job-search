#!/usr/bin/env python3
"""SPEC §7 surveillance — Telegram alerts, deduplicated through jobbot/state/alerts.json.

Called by scan.py after each run (or with --failure when the run crashed before
writing its summary). Alerts:
  * run_failed         a scan failed (sent on the transition, reminded every 24 h, "recovered" on recovery)
  * claude_auth_quota  Claude authentication / quota / rate-limit failure
  * claude_budget      --max-budget-usd reached
  * cap_reached        more postings than max_scored_per_run (rest deferred) — silent during the
                       initial stock: until the first successful run that stays under the cap
                       (health.json "initial_stock_drained"), deferring is expected, not alarming
  * zero:<site>        0 results on a site for zero_results_alert_days days in a row
  * site_down:<site>   every query to a site failed in this run
  * blocked hosts      newly pending hosts (listed once; then in the daily recap)
Active alerts feed /status and the daily recap. Dry-run: messages are sent ([TEST]), state is not persisted.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import common
import telegram_send as tg
from i18n import t

REMIND_HOURS = 24


def alerts_path() -> Path:
    return common.state_dir() / "alerts.json"


def load_alerts() -> dict:
    return common.read_json(alerts_path(), {}) or {}


def zero_result_sites(stats: dict, days: int, today: dt.date) -> list[str]:
    """Sites whose last `days` local days all exist in stats and all have 0 results."""
    out = []
    for site, per_day in (stats or {}).items():
        window = [(today - dt.timedelta(days=i)).isoformat() for i in range(days)]
        if all(d in per_day for d in window) and all(int(per_day[d].get("results") or 0) == 0 for d in window):
            out.append(site)
    return sorted(out)


def evaluate(summary: dict | None, failure: str | None, stats: dict, schedule: dict, today: dt.date,
             initial_stock: bool = False) -> dict[str, str]:
    """-> {alert_key: message text} for every condition currently true.
    initial_stock: the backlog present at install time is still draining; the cap is expected to bite."""
    active: dict[str, str] = {}
    if summary is None:
        active["run_failed"] = t("monitor.crashed", error=tg.esc(failure or t("monitor.unknown_error")))
        return active
    rid = tg.esc(summary.get("run_id"))
    claude = summary.get("claude") or {}
    if claude.get("failure") == "auth_or_quota":
        active["claude_auth_quota"] = t("monitor.claude_auth", run=rid, error=tg.esc(claude.get('error')))
    elif claude.get("failure") == "budget":
        active["claude_budget"] = t("monitor.claude_budget", run=rid, cost=summary.get('total_cost_usd'))
    if summary.get("status") != "ok":
        detail = claude.get("error") or "; ".join(summary.get("score_problems") or []) or t("monitor.see_log")
        active["run_failed"] = t("monitor.run_failed", run=rid, detail=tg.esc(detail)[:600])
    if summary.get("cap_reached") and not initial_stock:
        active["cap_reached"] = t("monitor.cap_reached", run=rid, n=summary.get('deferred'))
    for site, s in (summary.get("sites") or {}).items():
        if int(s.get("errors") or 0) and not int(s.get("queries") or 0):
            active[f"site_down:{site}"] = t("monitor.site_down", site=tg.esc(site), run=rid)
    days = int(schedule.get("zero_results_alert_days") or 3)
    for site in zero_result_sites(stats, days, today):
        active[f"zero:{site}"] = t("monitor.zero", site=tg.esc(site), days=days)
    return active


def run(summary: dict | None, failure: str | None = None) -> dict:
    schedule = common.load_schedule()
    now = common.now()
    today = common.local_now().date()
    stats = common.read_json(common.state_dir() / "site_stats.json", {}) or {}
    health_path = common.state_dir() / "health.json"
    initial_stock = not (common.read_json(health_path, {}) or {}).get("initial_stock_drained")
    current = evaluate(summary, failure, stats, schedule, today, initial_stock)
    stored = load_alerts()
    sent = []

    for key, text in current.items():
        prev = stored.get(key)
        last = common.parse_iso(prev.get("last_sent")) if prev else None
        if prev is None or last is None or (now - last).total_seconds() >= REMIND_HOURS * 3600:
            tg.send(text if prev is None else t("monitor.reminder", text=text))
            sent.append(key)
            stored[key] = {"since": prev.get("since") if prev else common.iso(now), "last_sent": common.iso(now), "text": text}
        else:
            stored[key]["text"] = text

    # Resolved: run-level alerts clear on the next successful run; zero/site alerts when no longer true.
    resolved = []
    for key in list(stored):
        if key in current:
            continue
        if summary is None:
            continue  # a crashed run proves nothing about the other conditions
        run_level = key in ("run_failed", "claude_auth_quota", "claude_budget", "cap_reached")
        if not run_level or summary.get("status") == "ok":
            resolved.append(key)
            stored.pop(key)
    if "run_failed" in resolved:
        tg.send(t("monitor.recovered"))

    hosts = (summary or {}).get("new_pending_hosts") or []
    if hosts:
        tg.send(t("monitor.blocked_hosts") + "\n" + "\n".join(f"• {tg.esc(h)}" for h in hosts))

    if not common.dry_run():
        with common.state_lock():
            common.atomic_write_json(alerts_path(), stored)
            health = common.read_json(health_path, {}) or {}
            ok = summary is not None and summary.get("status") == "ok"
            health.update({"last_run": common.iso(now), "last_status": "ok" if ok else "failed",
                           "last_run_id": (summary or {}).get("run_id")})
            health["consecutive_failures"] = 0 if ok else int(health.get("consecutive_failures") or 0) + 1
            if ok:
                health["last_ok"] = common.iso(now)
                if not summary.get("cap_reached") and not health.get("initial_stock_drained"):
                    health["initial_stock_drained"] = common.iso(now)  # from now on the cap alert is live
            common.atomic_write_json(health_path, health)
    return {"active": sorted(current), "sent": sent, "resolved": resolved, "initial_stock": initial_stock}


def notify(key: str, text: str | None, active: bool, *, recovered: str | None = None) -> bool:
    """Deduplicated alert outside a scan (preflight…): send when `key` becomes active, remind every
    REMIND_HOURS, clear (optionally announcing `recovered`) when inactive. Returns True if a message went out."""
    now = common.now()
    stored = load_alerts()
    prev = stored.get(key)
    sent = False
    if active:
        last = common.parse_iso(prev.get("last_sent")) if prev else None
        if prev is None or last is None or (now - last).total_seconds() >= REMIND_HOURS * 3600:
            tg.send(text if prev is None else t("monitor.reminder", text=text))
            sent = True
            stored[key] = {"since": prev.get("since") if prev else common.iso(now), "last_sent": common.iso(now), "text": text}
        else:
            stored[key]["text"] = text
    elif prev is not None:
        stored.pop(key)
        if recovered:
            tg.send(recovered)
            sent = True
    else:
        return False
    if not common.dry_run():
        with common.state_lock():
            current = load_alerts()
            if key in stored:
                current[key] = stored[key]
            else:
                current.pop(key, None)
            common.atomic_write_json(alerts_path(), current)
    return sent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--summary", type=Path)
    ap.add_argument("--failure")
    args = ap.parse_args(argv)
    summary = common.read_json(args.summary) if args.summary else None
    print(json.dumps(run(summary, args.failure)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
