#!/usr/bin/env python3
"""Daily recap (launchd com.jobbot.daily, schedule.yaml daily_recap): SPEC §6 / §11.

    jobbot/.venv/bin/python jobbot/scripts/daily.py

Sends: sites awaiting validation (numbered, with links — the numbers /allow and
/deny use), active alerts, last-24 h activity (runs, seen, new, alerts, cost), and the
applications prepared by /go but not /sent for more than pending_reminder_hours (pending.json, V2),
and the offer queue (shown offer, waiting count, offers removed for a past deadline — V5).
V5: then one message per follow-up newly due (followup.py, buttons handled by the bot), and a recap line
with every follow-up still due.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "bot"))

import applications as apps  # noqa: E402
import common  # noqa: E402
import logic  # noqa: E402
import telegram_send as tg  # noqa: E402
from i18n import t  # noqa: E402


def last_24h() -> dict:
    cutoff = common.now() - dt.timedelta(hours=24)
    agg = {"runs": 0, "failed": 0, "seen": 0, "new": 0, "scored": 0, "alerted": 0, "cost": 0.0}
    for path in common.runs_dir().glob("2*.json"):
        if not re.fullmatch(r"\d{8}T\d{6}", path.stem):
            continue
        try:
            s = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        fin = common.parse_iso(s.get("finished"))
        if not fin or fin < cutoff:
            continue
        agg["runs"] += 1
        agg["failed"] += s.get("status") != "ok"
        for k in ("seen", "new", "scored", "alerted"):
            agg[k] += int(s.get(k) or 0)
        agg["cost"] += float(s.get("total_cost_usd") or 0)
    agg["cost"] = round(agg["cost"], 2)
    return agg


def initial_stock_pending(last: dict | None) -> int:
    """Postings deferred by the cap in the last run, while the initial stock is draining
    (health.json has no initial_stock_drained yet — see monitor.py). 0 otherwise."""
    health = common.read_json(common.state_dir() / "health.json", {}) or {}
    if health.get("initial_stock_drained") or not last or not last.get("cap_reached"):
        return 0
    return int(last.get("deferred") or 0)


def heartbeat(a: dict, report: dict | None) -> list[str]:
    """First lines of the recap: sent every day, even with nothing new, as a sign of life."""
    lines = []
    last = logic.latest_summary()
    fin = common.parse_iso(last.get("finished")) if last else None
    if a["runs"] == 0:
        lines.append(t("daily.alive_no_run"))
    else:
        lines.append(t("daily.alive"))
    if fin:
        nxt = fin + common.dt.timedelta(hours=float(common.load_schedule()["scan_every_hours"]))
        lines.append(t("daily.last_run", when=fin.astimezone(common.tz()).strftime('%d/%m %H:%M'),
                       status=tg.esc(last.get('status')), next=nxt.astimezone(common.tz()).strftime('%H:%M')))
    if report:
        bad = [c for c in report["checks"] if c["status"] != "ok"]
        icon = {"ok": "✅", "warn": "⚠️", "fail": "❌"}[report["status"]]
        detail = "; ".join(f"{c['name']} : {c['detail']}" for c in bad[:3]) if bad else t("daily.all_green")
        lines.append(t("daily.check", icon=icon, detail=tg.esc(detail)))
    deferred = initial_stock_pending(last)
    if deferred:
        lines.append(t("daily.initial_stock", n=deferred))
    queued = tg.queue_length()
    if queued:
        lines.append(t("daily.tg_queued", n=queued))
    return lines


def stale_pending() -> list[str]:
    """SPEC §8/§11: applications waiting for /sent longer than pending_reminder_hours (real ones only)."""
    hours = float(common.load_schedule()["pending_reminder_hours"])
    cutoff = common.now() - dt.timedelta(hours=hours)
    items = [e for e in apps.load_pending(False).values()
             if (common.parse_iso(e.get("go_at")) or common.now()) <= cutoff]
    if not items:
        return []
    lines = ["\n" + t("daily.stale_title", hours=f"{hours:g}", n=len(items))]
    for e in sorted(items, key=lambda e: e.get("go_at") or ""):
        age = logic._age(e.get("go_at"))
        lines.append(t("daily.stale_item", id=tg.esc(e['id']), company=tg.esc(e.get('company')),
                       link=tg.link(e.get('url'), e.get('title') or t("common.offer")), age=age))
    lines.append(t("daily.stale_hint"))
    return lines


def offer_queue_lines() -> list[str]:
    """V5: the shown offer and the queue length (an ignored offer holds the queue: keep it visible), and the
    waiting offers removed for a past deadline since the last message. Nothing is shown again here."""
    import offer_queue as oq

    with common.state_lock():
        q = oq.load(False)
        oq.purge_locked(False, q)
        note = oq.expired_note(q)
        q["expired"] = []
        oq.save(False, q)
    lines = oq.status_lines(False)
    if note:
        lines.append(note)
    return (["", *lines] if lines else [])


def followup_lines() -> list[str]:
    """V5: follow-ups still due (not exhausted), real and test, so an ignored reminder stays visible."""
    import followup

    items = [i for test in (False, True) for i in followup.due_items(test) if not i["exhausted"]]
    if not items:
        return []
    ids = ", ".join(("#" if not i["id"].lstrip("T").startswith("S") else "") + i["id"] for i in items)
    return ["", t("daily.followups", n=len(items), ids=tg.esc(ids))]


def send_reminders() -> int:
    """V5: one message per follow-up newly due (one per quiet period). -> messages sent."""
    import followup

    def deliver(item: dict) -> bool:
        text, rows = logic.reminder_message(item)
        return tg.send_status(text, buttons=rows)[1] != tg.DROPPED

    # A reminder is marked as sent only once it went out or was queued: a refused message comes back next day.
    return sum(followup.send_reminders(test, deliver) for test in (False, True))


def build(report: dict | None = None) -> str:
    a = last_24h()
    lines = [t("daily.title", date=common.local_now().strftime('%d/%m/%Y'))]
    lines += heartbeat(a, report)
    lines.append(t("daily.last_24h", **a))
    if a["new"] == 0 and a["runs"]:
        lines.append(t("daily.nothing_new"))
    lines += stale_pending()
    lines += offer_queue_lines()
    lines += followup_lines()
    alerts = common.read_json(common.state_dir() / "alerts.json", {}) or {}
    if alerts:
        lines.append("\n" + t("status.alerts"))
        lines.extend(f"• {v.get('text', k)}" for k, v in alerts.items())
    with common.state_lock():
        pending = logic.pending_list_text(refresh=True)
    lines.append("")
    lines.append(pending)
    return "\n".join(lines)


def main() -> int:
    """Always sends, even with no news (sign of life). A failing check never prevents the recap."""
    try:
        import preflight

        report = preflight.run_checks()
    except Exception as exc:  # noqa: BLE001
        common.log(f"daily: preflight failed: {exc}")
        report = None
    tg.send(build(report))
    try:
        send_reminders()
    except Exception as exc:  # noqa: BLE001 — the recap is already out; the next day retries
        common.log(f"daily: follow-up reminders failed: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
