"""V3 (SPEC §10): jobbot/state/companies.csv — target employers, their recruiting software, status.

Status:
  active    scanned by the recruiting-software connectors, proposed at 20:00 for spontaneous applications
  blocked   /block: excluded from every search (all sources), from discovery and spontaneous applications
  proposed  found by /discover, waiting for /accept or /reject (never fetched before /accept)
  rejected  /reject: never proposed again
Writes go through common.state_lock(); callers hold it.
"""

from __future__ import annotations

import csv
import io
import re
from pathlib import Path
from urllib.parse import urlsplit

import common
import dedup

HEADER = ["name", "key", "city", "region", "website", "ats", "ats_slug", "careers_url", "origin", "source",
          "status", "verified", "added"]
STATUSES = ("active", "blocked", "proposed", "rejected")


def path() -> Path:
    return common.state_dir() / "companies.csv"


def key_of(name) -> str:
    return dedup.norm_company(name) or ""


def load() -> list[dict]:
    p = path()
    if not p.exists():
        return []
    with p.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    for row in rows:
        for col in HEADER:
            row.setdefault(col, "")
            if row[col] is None:
                row[col] = ""
        if not row["key"]:
            row["key"] = key_of(row["name"])
    return rows


def save(rows: list[dict]) -> None:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=HEADER, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k) or "" for k in HEADER})
    common.atomic_write_text(path(), buf.getvalue())


def find(rows: list[dict], name) -> dict | None:
    key = key_of(name)
    return next((r for r in rows if key and r["key"] == key), None)


def website_host(url) -> str:
    try:
        host = (urlsplit(str(url or "")).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def add(rows: list[dict], name: str, **fields) -> tuple[dict, bool]:
    """Insert unless the same company (normalised name, or same website host) exists. -> (row, created)."""
    existing = find(rows, name)
    host = website_host(fields.get("website"))
    if not existing and host:
        existing = next((r for r in rows if website_host(r["website"]) == host), None)
    if existing:
        return existing, False
    row = {k: "" for k in HEADER}
    row.update({"name": " ".join(str(name).split()), "key": key_of(name), "status": "active",
                "added": common.local_now().date().isoformat()})
    row.update({k: str(v) for k, v in fields.items() if k in HEADER and v is not None})
    rows.append(row)
    return row, True


# ------------------------------------------------------------------ blocking

def _covers(block_key: str, company_key: str) -> bool:
    """Same rule as the fixed company exclusions: equal, or the blocked name followed by more words."""
    return bool(block_key) and bool(company_key) and (company_key == block_key or company_key.startswith(block_key + " "))


def blocked_keys(rows: list[dict] | None = None) -> set[str]:
    rows = load() if rows is None else rows
    return {r["key"] for r in rows if r["status"] == "blocked" and r["key"]}


def is_blocked(name, keys: set[str] | None = None) -> bool:
    keys = blocked_keys() if keys is None else keys
    key = key_of(name)
    return any(_covers(b, key) for b in keys)


def block(rows: list[dict], name: str) -> tuple[dict, list[str]]:
    """-> (blocked row, names of other companies the block also covers)."""
    row = find(rows, name)
    if row is None:
        row, _ = add(rows, name, origin="telegram /block")
    row["status"] = "blocked"
    covered = [r["name"] for r in rows if r is not row and _covers(row["key"], r["key"])]
    return row, covered


def unblock(row: dict) -> None:
    row["status"] = "active"


def blocked(rows: list[dict]) -> list[dict]:
    return sorted((r for r in rows if r["status"] == "blocked"), key=lambda r: r["name"].casefold())


def proposed(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["status"] == "proposed"]


# ------------------------------------------------------------------ "already contacted / applied"

def contacted_keys() -> set[str]:
    """Companies the user already wrote to or applied at: never in the 20:00 list, never proposed.
    Spontaneous contacts of every status (prepared, sent, and cancelled: an abandon is a decision too)
    and tracker rows past `drafted` (applied, interview, offer, rejected…)."""
    import applications as apps
    import contacts

    keys = {key_of(c["company"]) for c in contacts.load_all() if c["status"] != "draft"}  # draft: nothing prepared yet
    try:
        _, rows = apps.read_tracker()
    except (OSError, ValueError):
        rows = []
    for row in rows:
        status = (row.get("status") or "").strip().lower()
        if status and status not in ("new", "skipped", "drafted"):
            keys.add(key_of(row.get("company")))
    keys.discard("")
    return keys


def matches_any(name, keys: set[str]) -> bool:
    key = key_of(name)
    return any(_covers(k, key) or _covers(key, k) for k in keys)


# ------------------------------------------------------------------ seed file (config/companies-seed.md)

_SEED_LINE = re.compile(r"^-\s+(?P<name>[^·]+?)\s+·\s+(?P<city>[^·]+?)\s+·\s+(?P<site>https?://\S+)"
                        r"(?:\s+·\s+source\s*:\s*(?P<source>https?://\S+))?\s*$")


def parse_seed(text: str) -> tuple[list[dict], list[str]]:
    """-> (entries, malformed lines). Headings (## …) give the category; comments and blanks are skipped."""
    entries, bad, category = [], [], ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("<!--"):
            continue
        if line.startswith("#"):
            category = line.lstrip("#").strip() if line.startswith("##") else category
            continue
        if not line.startswith("- "):
            continue
        m = _SEED_LINE.match(line)
        if not m:
            bad.append(line)
            continue
        entries.append({"name": m.group("name").strip(), "city": m.group("city").strip(),
                        "website": m.group("site").rstrip("/"), "source": m.group("source") or "",
                        "category": category})
    return entries, bad


def region_of(city: str) -> str:
    """City name -> regions.yaml key ('' if unknown)."""
    aliases = dedup.city_aliases(common.load_regions()["regions"])
    region = dedup.norm_city(city, aliases)
    return region if region in set(aliases.values()) else ""
