"""V3 (SPEC §10): jobbot/state/contacts.csv — spontaneous applications, one row per prepared contact.

IDs: S<n> (real) / TS<n> (JOBBOT_DRY_RUN=1, stored apart in contacts-test.csv, never in the real file).
Only what is strictly needed is kept (GDPR): who, professional address, where it was found, dates.
Retention is decided by the user when the answer / follow-up comes (V5, followup.py): "keep" dates the
row (`kept`), "purge" blanks the personal fields and keeps only a SHA-256 fingerprint of the address and
of the LinkedIn profile (`email_hash`, `linkedin_hash`), so a purged contact is still never proposed again.
Callers hold common.state_lock().
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from pathlib import Path

import common

HEADER = ["id", "company", "contact", "role", "email", "email_source", "linkedin", "linkedin_source", "variant",
          "folder", "prepared", "sent", "followup", "response", "status", "kept", "email_hash", "linkedin_hash"]
PERSONAL = ("contact", "role", "email", "email_source", "linkedin", "linkedin_source")
ID_RE = re.compile(r"T?S\d{1,6}")


def norm_id(value) -> str | None:
    text = str(value or "").strip().lstrip("#").upper()
    return text if ID_RE.fullmatch(text) else None


def is_test_id(cid: str) -> bool:
    return str(cid).startswith("T")


def path(test: bool) -> Path:
    return common.state_dir() / ("contacts-test.csv" if test else "contacts.csv")


def load(test: bool = False) -> list[dict]:
    p = path(test)
    if not p.exists():
        return []
    with p.open(encoding="utf-8", newline="") as fh:
        return [{k: (common.csv_plain(row.get(k)) or "") for k in HEADER} for row in csv.DictReader(fh)]


def load_all() -> list[dict]:
    """Real contacts only: test rows never hide a company from the real 20:00 list."""
    return load(False)


def save(rows: list[dict], test: bool = False) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=HEADER, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: common.csv_safe(row.get(k) or "") for k in HEADER})
    common.atomic_write_text(path(test), buf.getvalue(), mode=0o600)


def next_id(rows: list[dict], test: bool) -> str:
    prefix = "TS" if test else "S"
    numbers = [int(r["id"][len(prefix):]) for r in rows if r["id"].startswith(prefix) and r["id"][len(prefix):].isdigit()]
    return f"{prefix}{max(numbers, default=0) + 1}"


def get(cid: str) -> dict | None:
    return next((r for r in load(is_test_id(cid)) if r["id"] == cid), None)


def _norm_email(value) -> str:
    return str(value or "").strip().lower()


def _norm_linkedin(value) -> str:
    return str(value or "").strip().lower().rstrip("/")


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


def already_contacted(rows: list[dict], email: str | None, linkedin: str | None) -> dict | None:
    """Never propose a contact twice: same e-mail address or same LinkedIn profile, whatever the status
    (a purged row is matched on its fingerprints)."""
    email, linkedin = _norm_email(email), _norm_linkedin(linkedin)
    for row in rows:
        if email and (_norm_email(row["email"]) == email or row["email_hash"] == fingerprint(email)):
            return row
        if linkedin and (_norm_linkedin(row["linkedin"]) == linkedin or row["linkedin_hash"] == fingerprint(linkedin)):
            return row
    return None


def purge_row(row: dict) -> None:
    """GDPR: keep only what prevents a second contact (company, dates, answer, fingerprints)."""
    if row["email"]:
        row["email_hash"] = fingerprint(_norm_email(row["email"]))
    if row["linkedin"]:
        row["linkedin_hash"] = fingerprint(_norm_linkedin(row["linkedin"]))
    for key in PERSONAL:
        row[key] = ""
    row["status"] = "purged"


def set_status(cid: str, status: str, **fields) -> dict | None:
    test = is_test_id(cid)
    rows = load(test)
    row = next((r for r in rows if r["id"] == cid), None)
    if row is None:
        return None
    row["status"] = status
    row.update({k: v for k, v in fields.items() if k in HEADER})
    save(rows, test)
    return row
