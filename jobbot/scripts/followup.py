"""V5 (SPEC §8, §10): follow-up reminders, /reply, keep or purge a contact — zero tokens.

Plugged into the upstream /outcome command without changing it:
  - tracker statuses = /outcome's vocabulary; only `status` and `notes` of the row are written, notes dated
    and free of commas, quotes and line breaks (/outcome Step 4);
  - a follow-up is logged as `followed up YYYY-MM-DD` in `notes`, the marker /outcome counts (Step 2b);
  - days quiet = from the latest of the `date` column and the dates written in `notes` (/outcome Step 1.3),
    so a follow-up or an interview update recorded by /outcome or /gmail-sync resets the clock here too;
  - 10 days (`followup_days`), at most 2 follow-ups (`followup_max`); after that, no third reminder: the
    user records `no_response` with /outcome (never closed automatically, as /outcome Step 2b);
  - the follow-up itself is drafted by `/outcome followup <company>` in Claude Code (interactive).

Reminders only for sendings confirmed by /sent and still unanswered:
  - postings (numeric ID): `sent_at` in the ledger (written by /sent) and tracker row `jobbot #<ID>` still `applied`
    (`interview` and final statuses are answers, `drafted` was never sent);
  - spontaneous (S…): contacts.csv status `sent`, no `response`.
One reminder per quiet period: state/followups.json remembers the anchor date each reminder was sent for.
Test IDs (T…, TS…): /sent T… registers the sending in followups-test.json; nothing touches the tracker.
"""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import applications as apps
import common
import contacts

DATE_RE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})(?!\d)")
FOLLOWED_RE = re.compile(r"followed up (\d{4}-\d{2}-\d{2})")
YES = {"oui", "yes", "y", "o", "ja", "1", "+"}
NO = {"non", "no", "n", "nein", "0", "-"}


def settings() -> tuple[int, int]:
    schedule = common.load_schedule()
    return int(schedule.get("followup_days") or 10), int(schedule.get("followup_max") or 2)


def today() -> dt.date:
    return common.local_now().date()


def parse_answer(word) -> str | None:
    word = str(word or "").strip().lower()
    return "yes" if word in YES else "no" if word in NO else None


# ------------------------------------------------------------------ state

def state_path(test: bool) -> Path:
    return common.state_dir() / ("followups-test.json" if test else "followups.json")


def load_state(test: bool) -> dict:
    data = common.read_json(state_path(test), {}) or {}
    data.setdefault("reminded", {})
    if test:
        data.setdefault("sent", {})
    return data


def save_state(test: bool, data: dict) -> None:
    common.atomic_write_json(state_path(test), data)


def register_test_sent(short_id: str, entry: dict) -> None:
    """/sent T…: the test sending, so the whole circuit can be tried without the tracker. Takes the lock."""
    if not apps.is_test_id(short_id):
        return
    with common.state_lock():
        data = load_state(True)
        data["sent"][short_id] = {"company": entry.get("company") or "", "title": entry.get("title") or "",
                                  "url": entry.get("url") or "", "date": today().isoformat(), "notes": "",
                                  "status": "applied"}
        save_state(True, data)


def forget_test(short_id: str) -> None:
    """/cancel T…: the test sending is closed (withdrawn)."""
    if not apps.is_test_id(short_id):
        return
    with common.state_lock():
        data = load_state(True)
        if short_id in data["sent"]:
            data["sent"][short_id]["status"] = "withdrawn"
            save_state(True, data)


# ------------------------------------------------------------------ the /outcome clock

def _date(value) -> dt.date | None:
    match = DATE_RE.search(str(value or ""))
    if not match:
        return None
    try:
        return dt.date.fromisoformat(match.group(1))
    except ValueError:
        return None


def anchor(date_value, notes) -> dt.date | None:
    """Latest of the row date and every date in notes (/outcome Step 1.3); None if nothing parses."""
    dates = [d for d in [_date(date_value)] + [_date(m) for m in DATE_RE.findall(str(notes or ""))] if d]
    return max(dates) if dates else None


def followups_sent(notes) -> int:
    return len(FOLLOWED_RE.findall(str(notes or "")))


def _note(notes: str, text: str) -> str:
    text = re.sub(r'[,"\r\n]', " ", text).strip()
    return f"{notes}; {text}" if notes else text


# ------------------------------------------------------------------ open sendings

def _item(kind, sid, company, title, url, anchor_date, count, contact="") -> dict:
    return {"kind": kind, "id": sid, "company": company or "", "title": title or "", "url": url or "",
            "anchor": anchor_date.isoformat(), "days": (today() - anchor_date).days, "followups": count,
            "contact": contact, "test": sid.startswith("T")}


def offer_items(test: bool) -> list[dict]:
    out = []
    if test:
        for sid, e in load_state(True)["sent"].items():
            a = anchor(e.get("date"), e.get("notes"))
            if e.get("status") == "applied" and a:
                out.append(_item("offer", sid, e.get("company"), e.get("title"), e.get("url"), a,
                                 followups_sent(e.get("notes"))))
        return out
    import dedup

    ledger = dedup.Ledger.load()
    _, rows = apps.read_tracker()
    for row in rows:
        m = re.search(r"jobbot #(\d+)", row.get("notes") or "")
        if not m or (row.get("status") or "").strip() != "applied":
            continue
        found = ledger.find_short(m.group(1))
        if not found or not found[1].get("sent_at"):
            continue  # not confirmed by /sent
        a = anchor(row.get("date"), row.get("notes"))
        if a is None:
            common.log(f"followup: #{m.group(1)}: no parsable date, skipped")
            continue
        out.append(_item("offer", m.group(1), row.get("company"), row.get("role"), row.get("source"), a,
                         followups_sent(row.get("notes"))))
    return out


def _contact_dates(row: dict) -> list[dt.date]:
    return [d for d in (_date(x) for x in DATE_RE.findall(row.get("followup") or "")) if d]


def spont_items(test: bool) -> list[dict]:
    out = []
    for row in contacts.load(test):
        if row["status"] != "sent" or row["response"]:
            continue
        sent = common.parse_iso(row["sent"])
        dates = ([sent.astimezone(common.tz()).date()] if sent else []) + _contact_dates(row)
        if not dates:
            continue
        out.append(_item("spont", row["id"], row["company"], row["role"], "", max(dates), len(_contact_dates(row)),
                         contact=row["contact"] or row["email"] or row["linkedin"]))
    return out


def open_items(test: bool) -> list[dict]:
    return offer_items(test) + spont_items(test)


def due_items(test: bool) -> list[dict]:
    """Quiet for followup_days or more: `exhausted` once followup_max follow-ups stayed unanswered."""
    days, cap = settings()
    out = []
    for item in open_items(test):
        if item["days"] >= days:
            item["exhausted"] = item["followups"] >= cap
            out.append(item)
    return sorted(out, key=lambda i: (-i["days"], i["id"]))


def pending_reminders(test: bool) -> list[dict]:
    """Due items not yet reminded for their current quiet period (read only)."""
    items = due_items(test)
    data = load_state(test)
    return [i for i in items if data["reminded"].get(i["id"], {}).get("anchor") != i["anchor"]]


def mark_reminded(test: bool, items: list[dict]) -> None:
    """Takes the lock."""
    if not items:
        return
    with common.state_lock():
        data = load_state(test)
        for i in items:
            data["reminded"][i["id"]] = {"anchor": i["anchor"], "followups": i["followups"], "at": common.iso()}
        save_state(test, data)


def send_reminders(test: bool, deliver) -> int:
    """One reminder per item newly due. deliver(item) sends it and returns True once the message is
    delivered or in the Telegram outbox; only then is the item marked reminded, so a refused message
    or a crash in between is retried at the next run instead of being lost. -> reminders sent."""
    count = 0
    for item in pending_reminders(test):
        if deliver(item):
            mark_reminded(test, [item])
            count += 1
    return count


def take_reminders(test: bool) -> list[dict]:
    """Due items not yet reminded, marked reminded at once, before anything is sent: prefer
    send_reminders(), which marks each item only after its message went out."""
    with common.state_lock():
        new = pending_reminders(test)
    mark_reminded(test, new)
    return new


# ------------------------------------------------------------------ actions (each takes the lock)

def _offer_row(rows: list[dict], sid: str) -> dict | None:
    marker = f"jobbot #{sid}"
    return next((r for r in rows if re.search(re.escape(marker) + r"(?!\d)", r.get("notes") or "")), None)


def log_followup(sid: str) -> dict:
    """'Follow-up sent' -> {"ok", "status", "count", "date", "item"}; idempotent for the same day
    (/outcome Step 2b may already have logged it)."""
    days, cap = settings()
    date = today().isoformat()
    marker = f"followed up {date}"
    with common.state_lock():
        if contacts.norm_id(sid):
            test = contacts.is_test_id(sid)
            rows = contacts.load(test)
            row = next((r for r in rows if r["id"] == sid), None)
            if row is None:
                return {"ok": False, "status": "unknown"}
            if row["status"] != "sent" or row["response"]:
                return {"ok": False, "status": row["status"] if not row["response"] else "replied"}
            if date in (row["followup"] or ""):
                return {"ok": False, "status": "today", "count": len(_contact_dates(row))}
            row["followup"] = f"{row['followup']} {date}".strip()
            contacts.save(rows, test)
            count, company = len(_contact_dates(row)), row["company"]
        elif apps.is_test_id(sid):
            data = load_state(True)
            e = data["sent"].get(sid)
            if not e:
                return {"ok": False, "status": "unknown"}
            if e.get("status") != "applied":
                return {"ok": False, "status": e.get("status")}
            if marker in e.get("notes", ""):
                return {"ok": False, "status": "today", "count": followups_sent(e["notes"])}
            e["notes"] = _note(e.get("notes", ""), marker)
            save_state(True, data)
            count, company = followups_sent(e["notes"]), e.get("company")
        else:
            header, rows = apps.read_tracker()
            row = _offer_row(rows, sid)
            if row is None:
                return {"ok": False, "status": "unknown"}
            if (row.get("status") or "") != "applied":
                return {"ok": False, "status": row.get("status") or "?"}
            if marker in (row.get("notes") or ""):
                return {"ok": False, "status": "today", "count": followups_sent(row["notes"])}
            row["notes"] = _note(row.get("notes") or "", marker)
            apps.write_tracker(header, rows)
            count, company = followups_sent(row["notes"]), row.get("company")
            apps.log_event("followup", sid, n=count)
        if contacts.norm_id(sid) and not contacts.is_test_id(sid):
            apps.log_event("followup", sid, n=count)
    return {"ok": True, "status": "logged", "count": count, "max": cap, "days": days, "date": date,
            "company": company or ""}


def reply(sid: str, answer: str) -> dict:
    """/reply <ID> yes|no. Postings: applied -> interview (yes) / rejected (no); interview -> rejected (no).
    -> {"ok", "status", "old", "new", "company", "title", "kind"}."""
    date = today().isoformat()
    note = f"reply {answer} {date}"
    with common.state_lock():
        if contacts.norm_id(sid):
            test = contacts.is_test_id(sid)
            rows = contacts.load(test)
            row = next((r for r in rows if r["id"] == sid), None)
            if row is None:
                return {"ok": False, "status": "unknown"}
            base = {"kind": "spont", "company": row["company"], "title": "", "old": row["status"],
                    "contact": row["contact"] or row["email"] or row["linkedin"]}
            if row["response"]:
                return {**base, "ok": False, "status": "already", "response": row["response"]}
            if row["status"] != "sent":
                return {**base, "ok": False, "status": "not_sent"}
            row["response"] = f"{answer} {date}"
            row["status"] = "replied"
            contacts.save(rows, test)
            if not test:
                apps.log_event("reply", sid, answer=answer)
            return {**base, "ok": True, "status": "done", "new": "replied", "kept": row["kept"]}

        new = "interview" if answer == "yes" else "rejected"
        if apps.is_test_id(sid):
            data = load_state(True)
            e = data["sent"].get(sid)
            if not e:
                return {"ok": False, "status": "unknown"}
            base = {"kind": "offer", "company": e.get("company"), "title": e.get("title"), "old": e.get("status")}
            verdict = _transition(e.get("status") or "", new)
            if verdict != "done":
                return {**base, "ok": False, "status": verdict}
            e["status"], e["notes"] = new, _note(e.get("notes", ""), note)
            save_state(True, data)
            return {**base, "ok": True, "status": "done", "new": new}

        header, rows = apps.read_tracker()
        row = _offer_row(rows, sid)
        job = apps.find_job(sid) or {}
        if row is None:
            return {"ok": False, "status": "unknown" if not job else "missing"}
        base = {"kind": "offer", "company": row.get("company"), "title": row.get("role"), "old": row.get("status")}
        if not job.get("sent_at") and (row.get("status") or "") in ("", "drafted"):
            return {**base, "ok": False, "status": "not_sent"}
        verdict = _transition((row.get("status") or "").strip(), new)
        if verdict != "done":
            return {**base, "ok": False, "status": verdict}
        row["status"] = new
        row["notes"] = _note(row.get("notes") or "", note)
        apps.write_tracker(header, rows)
        apps.set_ledger_status(sid, "replied", reply=answer, replied_at=common.iso())
        apps.log_event("reply", sid, answer=answer)
        return {**base, "ok": True, "status": "done", "new": new}


def _transition(old: str, new: str) -> str:
    if old == "drafted":
        return "not_sent"
    if old in apps.FINAL_STATUSES:
        return "closed"
    if old == new or (old in ("offer",) and new == "interview"):
        return "already"
    if old in ("applied", "interview", "offer"):
        return "done"
    return "closed"


def keep_contact(cid: str) -> dict:
    with common.state_lock():
        test = contacts.is_test_id(cid)
        rows = contacts.load(test)
        row = next((r for r in rows if r["id"] == cid), None)
        if row is None:
            return {"ok": False, "status": "unknown"}
        if row["status"] == "purged":
            return {"ok": False, "status": "purged", "company": row["company"]}
        if row["status"] not in ("sent", "replied"):
            return {"ok": False, "status": "not_sent", "company": row["company"], "old": row["status"]}
        if row["kept"]:
            return {"ok": False, "status": "already", "company": row["company"], "date": row["kept"]}
        row["kept"] = today().isoformat()
        contacts.save(rows, test)
    return {"ok": True, "status": "kept", "company": row["company"]}


def purge_contact(cid: str) -> dict:
    """Blank the personal fields (fingerprints kept) and delete the e-mail / LinkedIn drafts that hold them.
    The CV and the folder stay."""
    import spontaneous

    with common.state_lock():
        test = contacts.is_test_id(cid)
        rows = contacts.load(test)
        row = next((r for r in rows if r["id"] == cid), None)
        if row is None:
            return {"ok": False, "status": "unknown"}
        if row["status"] == "purged":
            return {"ok": False, "status": "purged", "company": row["company"]}
        if row["status"] not in ("sent", "replied"):
            return {"ok": False, "status": "not_sent", "company": row["company"], "old": row["status"]}
        removed = []
        folder = Path(row["folder"]) if row["folder"] else None
        root = spontaneous.root_dir(test).resolve()
        if folder and folder.resolve().is_relative_to(root) and folder.resolve() != root:
            for name in ("email.txt", "linkedin.txt"):
                path = folder / name
                if path.is_file():
                    path.unlink()
                    removed.append(name)
        contacts.purge_row(row)
        contacts.save(rows, test)
        if not test:
            apps.log_event("contact_purged", cid)
    return {"ok": True, "status": "purged", "company": row["company"], "removed": removed}
