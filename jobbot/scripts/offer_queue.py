"""V5: the Telegram offer queue — one offer shown at a time, the others wait on disk (SPEC §8).

    state/offer_queue.json        real IDs
    state/offer_queue-test.json   T-IDs (JOBBOT_DRY_RUN=1 runs); fully independent of the real queue
    state/offer_queue_numbering.json   the IDs numbered by the last /file (read by /voir <n>)

    {"current": {"id", "entry", "queued_at", "shown_at", "message_id"} | null,
     "waiting": {"<id>": {"entry": {...alert...}, "queued_at": "...Z"}},
     "forced": "<id>" | null,      # /voir: shown next, before the best score
     "advance": bool,              # the shown offer was closed: the bot shows the next one after its reply
     "expired": ["#12 Title — Company", ...]}   # removed for a past deadline, reported in the next message

Only pump() sends an offer. The next one is released by /no, /cancel or /sent on the shown offer
(never by /go), or by /voir <n>. Order: best score, then oldest in the queue, then ID.
Writers hold the state lock; the *_locked functions expect the caller to hold it already.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import applications as apps
import common
import telegram_send as tg
from i18n import t, tv

STALE_DAYS = 7  # an offer that waited this long is shown with "check it is still online"
CLOSED = {"rejected", "cancelled", "sent"}


# ------------------------------------------------------------------ storage

def queue_path(test: bool) -> Path:
    return common.state_dir() / ("offer_queue-test.json" if test else "offer_queue.json")


def numbering_path() -> Path:
    return common.state_dir() / "offer_queue_numbering.json"


def load(test: bool) -> dict:
    q = common.read_json(queue_path(test), None)
    if not isinstance(q, dict):
        q = {}
    q.setdefault("current", None)
    q.setdefault("waiting", {})
    q.setdefault("forced", None)
    q.setdefault("advance", False)
    q.setdefault("expired", [])
    return q


def save(test: bool, q: dict) -> None:
    common.atomic_write_json(queue_path(test), q)


def order_key(item: dict) -> tuple:
    entry = item["entry"]
    sid = str(entry.get("short_id") or "")
    num = int(sid.lstrip("T")) if sid.lstrip("T").isdigit() else 0
    # send_failed: an alert Telegram refused goes behind the others, so it cannot block the queue
    return (int(item.get("send_failed") or 0), -int(entry.get("score") or 0), item.get("queued_at") or "", num)


def ordered(q: dict) -> list[dict]:
    return sorted(q["waiting"].values(), key=order_key)


# ------------------------------------------------------------------ alert text

def format_alert(entry: dict) -> str:
    """SPEC §8: ID · score · title · company · location · contract · remote · salary · flags · justification · link."""
    salary = entry.get("salary") or t("alert.salary_none")
    lines = [
        f"<b>#{tg.esc(entry['short_id'])} · {entry['score']}/100</b> · {tg.link(entry['url'], entry['title'])}",
        f"{tg.esc(entry.get('company') or t('alert.company_none'))} · {tg.esc(entry.get('location') or t('alert.location_none'))}",
        t("alert.terms", contract=tg.esc(tv("contract", entry.get('contract') or "unknown")),
          remote=tg.esc(tv("remote", entry.get('remote') or "unknown")), salary=tg.esc(salary)),
    ]
    if entry.get("flags"):
        lines.append("⚑ " + tg.esc(" · ".join(entry["flags"])))
    if entry.get("justification"):
        lines.append(f"<i>{tg.esc(entry['justification'])}</i>")
    if entry.get("variant"):
        adapt = t("alert.adapt_yes") if entry.get("adapt") else t("alert.adapt_no")
        reason = f" — {tg.esc(entry['adapt_reason'])}" if entry.get("adapt_reason") else ""
        lines.append(t("alert.cv", variant=tg.esc(entry['variant']), adapt=adapt, reason=reason))
    lines.append(f"{tg.link(entry['url'])}  ({tg.esc(entry['site'])})")
    lines.append(t("alert.commands", id=tg.esc(entry['short_id'])))
    return "\n".join(lines)


def label(entry: dict) -> str:
    return f"#{entry.get('short_id')} {entry.get('title') or '?'} — {entry.get('company') or '?'}"


def age_text(iso: str | None) -> str:
    when = common.parse_iso(iso)
    if not when:
        return "?"
    hours = max(0, int((common.now() - when).total_seconds() // 3600))
    return t("common.age_days", d=hours // 24, h=hours % 24) if hours >= 24 else t("common.age_hours", h=hours)


def _days(iso: str | None) -> float:
    when = common.parse_iso(iso)
    return (common.now() - when).total_seconds() / 86400 if when else 0.0


# ------------------------------------------------------------------ purge (closed / past deadline)

def deadline_passed(entry: dict) -> bool:
    """Only a deadline published by the site (validThrough) counts; most sites give none."""
    raw = str(entry.get("valid_through") or "")[:10]
    try:
        deadline = dt.date.fromisoformat(raw)
    except ValueError:
        return False
    return deadline < common.local_now().date()


def _statuses(test: bool) -> dict[str, str]:
    """short_id -> ledger status ("go" when prepared and waiting for /sent)."""
    out: dict[str, str] = {}
    if test:
        for sid, job in apps._test_alerts().items():
            out[sid] = job.get("status") or "alerted"
    else:
        import dedup

        for entry in dedup.Ledger.load().jobs.values():
            if entry.get("short_id"):
                out[str(entry["short_id"])] = entry.get("status") or ""
    for sid in apps.load_pending(test):
        out[sid] = "go"
    return out


def purge_locked(test: bool, q: dict) -> int:
    """Drop waiting offers closed meanwhile (or already in /go) and those past their deadline. -> removed count."""
    if not q["waiting"]:
        return 0
    status = _statuses(test)
    removed = 0
    for sid, item in list(q["waiting"].items()):
        st = status.get(sid)
        if st in CLOSED or st == "go":
            del q["waiting"][sid]
            removed += 1
        elif deadline_passed(item["entry"]):
            del q["waiting"][sid]
            q["expired"].append(label(item["entry"]))
            apps.log_event("queue_expired", sid, deadline=str(item["entry"].get("valid_through"))[:10])
            removed += 1
    if q.get("forced") not in q["waiting"]:
        q["forced"] = None
    return removed


def expired_note(q: dict) -> str | None:
    if not q["expired"]:
        return None
    names = "; ".join(q["expired"][:5]) + (" …" if len(q["expired"]) > 5 else "")
    return t("queue.expired", n=len(q['expired']), names=tg.esc(names))


# ------------------------------------------------------------------ transitions

def enqueue(entries: list[dict], test: bool) -> dict:
    """New alerts join the queue. -> {"new", "waiting", "busy"} (busy: an offer is already shown)."""
    now = common.iso()
    with common.state_lock():
        q = load(test)
        shown = (q["current"] or {}).get("id")
        new = 0
        for e in entries:
            sid = str(e["short_id"])
            if sid in q["waiting"] or sid == shown:
                continue
            q["waiting"][sid] = {"entry": e, "queued_at": now}
            new += 1
        save(test, q)
        return {"new": new, "waiting": len(q["waiting"]), "busy": q["current"] is not None}


def arrival_note(new: int, waiting: int) -> str:
    return t("queue.arrival", new=new, waiting=waiting)


def drop_locked(short_id: str, test: bool) -> str | None:
    """/no, /cancel, /sent: the offer leaves the queue. -> "current" (the next one will follow: advance
    is set), "waiting", or None (not in the queue)."""
    q = load(test)
    if (q["current"] or {}).get("id") == short_id:
        q["current"] = None
        q["advance"] = True
        save(test, q)
        return "current"
    if short_id in q["waiting"]:
        del q["waiting"][short_id]
        if q.get("forced") == short_id:
            q["forced"] = None
        save(test, q)
        return "waiting"
    return None


def take_waiting_locked(short_id: str, test: bool) -> bool:
    """/go on an offer still waiting: it leaves the queue (now followed by /pending); the shown offer stays."""
    if short_id not in load(test)["waiting"]:
        return False
    return drop_locked(short_id, test) == "waiting"


def is_current(short_id: str, test: bool) -> bool:
    return (load(test)["current"] or {}).get("id") == short_id


def _record_message(short_id: str, test: bool, message_id: int, sent: str) -> None:
    """The ID's alert message, so /go answers it (caller holds the lock)."""
    if test:
        for path in sorted(common.runs_dir().glob("*-test-alerts.json")):
            data = common.read_json(path, {}) or {}
            if short_id in (data.get("jobs") or {}):
                data["jobs"][short_id]["message_id"] = message_id
                common.atomic_write_json(path, data)
        return
    path = common.state_dir() / "telegram_msgs.json"
    msgs = common.read_json(path, {}) or {}
    msgs[short_id] = {"message_id": message_id, "kind": "alert", "sent": sent}
    common.atomic_write_json(path, msgs)


def pump(test: bool) -> int | None:
    """Show the next offer when none is shown. -> its message_id (None: nothing sent, or Telegram queued it)."""
    with common.state_lock():
        q = load(test)
        q["advance"] = False
        if q["current"] is not None:
            save(test, q)
            return None
        purge_locked(test, q)
        items = ordered(q)
        if not items:
            save(test, q)
            return None
        forced = q.get("forced")
        item = q["waiting"][forced] if forced in q["waiting"] else items[0]
        entry = item["entry"]
        sid = str(entry["short_id"])
        del q["waiting"][sid]
        q["forced"] = None
        q["current"] = {"id": sid, "entry": entry, "queued_at": item.get("queued_at"),
                        "shown_at": common.iso(), "message_id": None}
        lines = [format_alert(entry)]
        if _days(item.get("queued_at")) >= STALE_DAYS:
            lines.append(t("queue.stale", age=age_text(item.get('queued_at'))))
        note = expired_note(q)
        if note:
            lines.append(note)
            q["expired"] = []
        if q["waiting"]:
            lines.append(t("queue.others", n=len(q['waiting'])))
        save(test, q)
    text = "\n".join(lines)
    if test and not common.dry_run():
        text = "[TEST] " + text  # shown by the bot after a /no T… etc.; dry-run sends prefix it themselves
    mid, status = tg.send_status(text)
    if mid:
        with common.state_lock():
            q = load(test)
            if (q["current"] or {}).get("id") == sid:
                q["current"]["message_id"] = mid
                save(test, q)
            _record_message(sid, test, mid, common.iso())
    elif status == tg.DROPPED:
        # Neither delivered nor in the Telegram outbox: the user never saw this offer. Back to the
        # queue (behind the others), and the next command retries through advance().
        with common.state_lock():
            q = load(test)
            if (q["current"] or {}).get("id") == sid:
                q["waiting"][sid] = {"entry": entry, "queued_at": item.get("queued_at"),
                                     "send_failed": int(item.get("send_failed") or 0) + 1}
                q["current"] = None
                q["advance"] = True
                save(test, q)
        common.log(f"offer queue: #{sid} could not be sent, back in the queue")
    return mid


def advance() -> None:
    """Called by the bot after every command: show the next offer where the shown one was just closed."""
    for test in (False, True):
        if load(test).get("advance"):
            pump(test)


def show_locked(short_id: str, test: bool) -> dict | None:
    """/voir: the shown offer goes back to the queue (unless it is in /go: /pending follows it), the chosen
    one is shown next. -> the chosen entry, or None if it is no longer waiting. The caller then runs pump()."""
    q = load(test)
    if short_id not in q["waiting"]:
        return None
    cur = q["current"]
    if cur and cur["id"] not in apps.load_pending(test) and _statuses(test).get(cur["id"]) not in CLOSED:
        q["waiting"][cur["id"]] = {"entry": cur["entry"], "queued_at": cur.get("queued_at") or cur.get("shown_at")}
    q["current"] = None
    q["forced"] = short_id
    save(test, q)
    return q["waiting"][short_id]["entry"]


# ------------------------------------------------------------------ /file, recap

def list_locked() -> tuple[list[tuple[bool, dict]], dict[bool, dict]]:
    """Purge, then -> ([(test, item)] in display order, real queue first), {test: queue}."""
    queues, items = {}, []
    for test in (False, True):
        q = load(test)
        if purge_locked(test, q):
            save(test, q)
        queues[test] = q
        items += [(test, it) for it in ordered(q)]
    common.atomic_write_json(numbering_path(), [str(it["entry"]["short_id"]) for _, it in items])
    return items, queues


def load_numbering() -> list[str] | None:
    data = common.read_json(numbering_path(), None)
    return data if isinstance(data, list) else None


def status_lines(test: bool = False) -> list[str]:
    """One line for /status and the daily recap (read only)."""
    q = load(test)
    cur, waiting = q["current"], len(q["waiting"])
    if not cur and not waiting:
        return []
    tag = " [TEST]" if test else ""
    if cur:
        e = cur["entry"]
        head = t("queue.status_shown", tag=tag, id=tg.esc(cur['id']), company=tg.esc(e.get('company') or '?'),
                 link=tg.link(e.get('url'), e.get('title') or t("common.offer")), age=age_text(cur.get('shown_at')))
    else:
        head = t("queue.status_none", tag=tag)
    return [t("queue.status_line", head=head, n=waiting)]


# ------------------------------------------------------------------ one-time backfill (alerts sent before V5)

def backfill_candidates() -> list[dict]:
    """Real offers still "alerted" in the ledger (no /no, /sent, /cancel, not in /go) and not yet in the queue,
    nor past their deadline, in queue order. The V5 queue only receives new alerts: these were sent before it."""
    import dedup

    q = load(False)
    known = set(q["waiting"]) | {(q["current"] or {}).get("id")}
    pending = set(apps.load_pending(False))
    out = []
    for entry in dedup.Ledger.load().jobs.values():
        sid = str(entry.get("short_id") or "")
        if not sid or entry.get("status") != "alerted" or sid in known or sid in pending:
            continue
        if deadline_passed(entry):
            continue
        out.append({"entry": dict(entry), "queued_at": entry.get("first_seen") or common.iso()})
    return sorted(out, key=order_key)


def backfill(preview: bool = False) -> dict:
    """Move the pre-V5 alerts into the real queue (queued_at = first alert, so the 7-day warning stays true),
    then show the best one if none is shown. -> {"added": [labels], "waiting", "shown"}."""
    with common.state_lock():
        items = backfill_candidates()
        labels = [f"{label(it['entry'])} · {it['entry'].get('score')}/100" for it in items]
        if preview or not items:
            return {"added": labels, "waiting": len(load(False)["waiting"]), "shown": None}
        q = load(False)
        for it in items:
            q["waiting"][str(it["entry"]["short_id"])] = it
        save(False, q)
        apps.log_event("queue_backfill", None, count=len(items))
        waiting = len(q["waiting"])
    return {"added": labels, "waiting": waiting, "shown": pump(False)}


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="V5 offer queue maintenance")
    ap.add_argument("--backfill", action="store_true", help="add the pre-V5 alerts still open to the real queue")
    ap.add_argument("--preview", action="store_true", help="with --backfill: only list them, change nothing")
    args = ap.parse_args()
    if not args.backfill:
        ap.error("nothing to do: use --backfill [--preview]")
    if common.dry_run():
        ap.error("JOBBOT_DRY_RUN=1: the backfill only concerns the real queue")
    res = backfill(args.preview)
    print(("Preview — " if args.preview else "") + f"{len(res['added'])} posting(s) "
          + ("to add" if args.preview else "added") + " to the queue:")
    for line in res["added"]:
        print("  " + line)
    if not args.preview:
        print(f"Queue: {res['waiting']} waiting; posting shown on Telegram: "
              + ("yes" if res["shown"] else "no (one is already shown, or the message is in the Telegram outbox)"))
