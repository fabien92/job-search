"""Applications (V2, SPEC §9): job lookup by ID, archived postings, folders, tracker CSV, pending.json, events.

Test mode (SPEC §12): IDs allocated by a JOBBOT_DRY_RUN=1 scan start with "T". Everything about a
T-ID lives apart from the real data, so a test never writes the tracker, the ledger or pending.json:
  job            state/runs/<run>-test-alerts.json   (written by postprocess in dry run)
  posting        <cache>/test-postings/<ID>.md       (real: state/postings/<ID>.md)
  folder         <cache>/test-applications/<name>/   (real: documents/applications/<name>/)
  pending        state/pending-test.json             (real: state/pending.json)
All writes go through the state lock (SPEC §0.8); callers hold it.
"""

from __future__ import annotations

import csv
import io
import json
import re
import unicodedata
from pathlib import Path

import common

TRACKER_HEADER = ["date", "company", "sector", "role", "role_type", "channel", "status", "contact_person",
                  "fit_rating", "notes", "cv_file", "cover_letter_file", "source", "deadline"]
FINAL_STATUSES = {"hired", "rejected", "no_response", "offer_declined", "withdrawn", "no response", "offer declined"}
ID_RE = re.compile(r"T?\d{1,7}")


def norm_id(value) -> str | None:
    text = str(value or "").strip().lstrip("#").upper()
    return text if ID_RE.fullmatch(text) else None


def is_test_id(short_id: str) -> bool:
    return str(short_id).startswith("T")


# ------------------------------------------------------------------ naming (documents/README.md)

def folder_name(company, role) -> str:
    """`<company>_<role>`: lowercase, underscores for spaces, only [a-z0-9_], runs collapsed, trimmed.
    Accented letters are folded to ASCII first so "Österreich" keeps its letters."""
    def part(text) -> str:
        text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
        text = re.sub(r"\s+", "_", text.lower())
        return re.sub(r"[^a-z0-9_]", "", text)

    name = re.sub(r"_+", "_", f"{part(company)}_{part(role)}").strip("_")
    return name or "offre"


def file_stem(short_id: str, company, role) -> str:
    """Telegram / folder file names: ID_entreprise_poste (SPEC §8), kept short for phones."""
    return f"{short_id}_{folder_name(company, role)[:60].rstrip('_')}"


def applications_root(short_id: str) -> Path:
    return (common.cache_dir() / "test-applications") if is_test_id(short_id) else common.applications_dir()


def application_dir(short_id: str, company, role) -> Path:
    """documents/applications/<company>_<role>/, or <...>_<ID> when that folder belongs to another ID."""
    root = applications_root(short_id)
    base = folder_name(company, role)
    path = root / base
    marker = path / ".jobbot-id"
    if path.exists() and (not marker.exists() or marker.read_text(encoding="utf-8").strip() != short_id):
        path = root / f"{base}_{short_id}"
    return path


# ------------------------------------------------------------------ archived postings

def posting_dir(test: bool) -> Path:
    path = (common.cache_dir() / "test-postings") if test else (common.state_dir() / "postings")
    path.mkdir(parents=True, exist_ok=True)
    return path


def posting_path(short_id: str) -> Path:
    return posting_dir(is_test_id(short_id)) / f"{short_id}.md"


def archive_posting(short_id: str, job: dict, text: str) -> Path:
    """Keep the posting_guard-cleaned text (the cache is purged after 7 days) — verbatim, plus the
    guard verdict and counts only, as /apply does."""
    guard = job.get("guard") or {}
    lines = [text.rstrip("\n"), "", "## posting_guard", str(guard.get("verdict") or "?")]
    if guard.get("instruction_like"):
        lines.append(f"instruction_like: {len(guard['instruction_like'])}")
    path = posting_path(short_id)
    common.atomic_write_text(path, "\n".join(lines) + "\n")
    return path


# ------------------------------------------------------------------ job lookup

def _test_alerts() -> dict[str, dict]:
    out: dict[str, dict] = {}
    for path in sorted(common.runs_dir().glob("*-test-alerts.json")):
        data = common.read_json(path, {}) or {}
        out.update({str(k): v for k, v in (data.get("jobs") or {}).items()})
    return out


def find_job(short_id: str) -> dict | None:
    """The scored job behind an ID, with its alert message id when one was sent."""
    if is_test_id(short_id):
        job = _test_alerts().get(short_id)
        return dict(job) if job else None
    import dedup

    found = dedup.Ledger.load().find_short(short_id)
    if not found:
        return None
    job = dict(found[1])
    msgs = common.read_json(common.state_dir() / "telegram_msgs.json", {}) or {}
    if msgs.get(short_id, {}).get("message_id"):
        job["message_id"] = msgs[short_id]["message_id"]
    return job


def set_ledger_status(short_id: str, status: str, **extra) -> bool:
    """Real IDs only (caller holds the state lock)."""
    if is_test_id(short_id):
        return False
    import dedup

    ledger = dedup.Ledger.load()
    found = ledger.find_short(short_id)
    if not found:
        return False
    key, entry = found
    entry.update({"status": status, **extra})
    ledger.jobs[key] = entry
    ledger.save()
    return True


# ------------------------------------------------------------------ pending.json

def pending_path(test: bool) -> Path:
    return common.state_dir() / ("pending-test.json" if test else "pending.json")


def load_pending(test: bool) -> dict[str, dict]:
    return common.read_json(pending_path(test), {}) or {}


def save_pending(test: bool, data: dict) -> None:
    common.atomic_write_json(pending_path(test), data)


def get_pending(short_id: str) -> dict | None:
    return load_pending(is_test_id(short_id)).get(short_id)


def all_pending() -> list[dict]:
    """Real first, then test entries, oldest first within each."""
    items = []
    for test in (False, True):
        items += sorted(load_pending(test).values(), key=lambda e: e.get("go_at") or "")
    return items


# ------------------------------------------------------------------ events (weekly report)

def log_event(kind: str, short_id: str, **extra) -> None:
    if is_test_id(short_id):
        return
    with open(common.state_dir() / "events.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": common.iso(), "kind": kind, "id": short_id, **extra}, ensure_ascii=False) + "\n")


def read_events() -> list[dict]:
    path = common.state_dir() / "events.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


# ------------------------------------------------------------------ tracker CSV (upstream format, /apply rules)

def read_tracker() -> tuple[list[str], list[dict]]:
    path = common.tracker_path()
    if not path.exists():
        return list(TRACKER_HEADER), []
    text = path.read_text(encoding="utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    header = list(reader.fieldnames or TRACKER_HEADER)
    rows = [{k: common.csv_plain(v) for k, v in r.items()} for r in reader]
    if header and header[-1] != "deadline" and "deadline" not in header:
        header.append("deadline")  # /apply Step 6b.1: header only, rows read as empty deadline
    return header, rows


class TrackerMalformed(ValueError):
    """A tracker row holds more cells than the header (an unquoted comma): rewriting the file would
    silently drop the overflow, so nothing is written until the row is repaired by hand."""

    def __init__(self, line: int, company: str):
        super().__init__(f"tracker row at line {line} ({company or '?'}) has more cells than the header")
        self.line, self.company = line, company or "?"


def write_tracker(header: list[str], rows: list[dict]) -> None:
    for index, row in enumerate(rows):
        if row.get(None):  # csv.DictReader keeps the cells beyond the header under the key None
            raise TrackerMalformed(index + 2, str(row.get("company") or ""))
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=header, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: common.csv_safe(row.get(k, "") or "") for k in header})
    common.atomic_write_text(common.tracker_path(), buf.getvalue())


def _marker(short_id: str) -> str:
    return f"jobbot #{short_id}"


def _find_row(rows: list[dict], short_id: str, company: str, role: str) -> dict | None:
    exact = re.compile(re.escape(_marker(short_id)) + r"(?!\d)")  # "jobbot #1" must not match "jobbot #12"
    for row in rows:
        if exact.search(row.get("notes") or ""):
            return row
    for row in rows:
        if ((row.get("company") or "").strip().casefold() == (company or "").strip().casefold()
                and (row.get("role") or "").strip().casefold() == (role or "").strip().casefold()
                and (row.get("status") or "").strip() not in FINAL_STATUSES):
            return row
    return None


def tracker_drafted(short_id: str, job: dict, cv_file: str) -> str:
    """/apply Step 6b: append a `drafted` row, or refresh an open one without moving it backwards.
    -> "added" | "updated" | "skipped (test)"."""
    if is_test_id(short_id):
        return "skipped (test)"
    header, rows = read_tracker()
    today = common.local_now().date().isoformat()
    company, role = job.get("company") or "", job.get("title") or ""
    row = _find_row(rows, short_id, company, role)
    if row is None:
        rows.append({
            "date": today, "company": company, "role": role, "channel": "portal", "status": "drafted",
            "fit_rating": str(job.get("score") if job.get("score") is not None else ""),
            "notes": _marker(short_id), "cv_file": cv_file, "cover_letter_file": "",
            "source": job.get("url") or "", "deadline": (job.get("valid_through") or "")[:10],
        })
        result = "added"
    else:
        row["cv_file"] = cv_file
        if job.get("score") is not None:
            row["fit_rating"] = str(job["score"])
        row["source"] = job.get("url") or row.get("source") or ""
        if job.get("valid_through"):
            row["deadline"] = job["valid_through"][:10]
        notes = row.get("notes") or ""
        if not re.search(re.escape(_marker(short_id)) + r"(?!\d)", notes):
            notes = (notes + "; " if notes else "") + _marker(short_id)
        row["notes"] = notes if notes.endswith("redrafted") else notes + "; redrafted"  # undated, as /apply
        if row.get("status") == "drafted":
            row["date"] = today
        result = "updated"
    write_tracker(header, rows)
    return result


def tracker_set_status(short_id: str, job: dict, status: str, only_from: tuple[str, ...]) -> str | None:
    """Move this application's row to `status` when its current status is in only_from. -> old status."""
    if is_test_id(short_id):
        return None
    header, rows = read_tracker()
    row = _find_row(rows, short_id, job.get("company") or "", job.get("title") or "")
    if row is None or (row.get("status") or "") not in only_from:
        return None
    old = row.get("status")
    row["status"] = status
    if status == "applied":
        row["date"] = common.local_now().date().isoformat()
    write_tracker(header, rows)
    return old
