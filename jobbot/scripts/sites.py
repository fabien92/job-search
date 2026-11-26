"""SPEC §6 — the site whitelist (jobbot/config/sites.yaml).

Written only by deterministic code run outside Claude (import_seed.py, the
Telegram bot, postprocess.py for `pending`), always under the state lock.
Claude never writes it: see gen_settings.py for the deny rules.

Entry forms:
  domain: karriere.at          -> karriere.at and every subdomain (www.karriere.at …)
  domain: "*.myworkdayjobs.com" -> subdomains only (a recruiting-software group, §6)
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

import common

HEADER = """\
# JobBot — site whitelist (SPEC §6).
# Written ONLY by import_seed.py and the Telegram bot (/allow, /deny), never by Claude.
# After every change, .claude/settings.local.json is regenerated (gen_settings.py).
#   domain: example.at          -> example.at and all its subdomains
#   domain: "*.example.com"     -> subdomains only (group of a recruiting software vendor)
"""

_DOMAIN = re.compile(r"^(\*\.)?(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def path():
    return common.config_dir() / "sites.yaml"


def normalize_domain(value: str) -> str | None:
    """A URL, host or *.group -> canonical domain string, or None if invalid."""
    if not isinstance(value, str):
        return None
    value = value.strip().lower()
    wildcard = value.startswith("*.")
    if wildcard:
        value = value[2:]
    if "://" in value:
        try:
            value = urlsplit(value).hostname or ""
        except ValueError:
            return None
    else:
        value = value.split("/")[0].split(":")[0]
    value = value.strip(".")
    if not wildcard and value.startswith("www."):
        value = value[4:]
    domain = ("*." if wildcard else "") + value
    return domain if _DOMAIN.match(domain) else None


def host_of(url: str) -> str | None:
    try:
        host = urlsplit(url.strip()).hostname
    except (ValueError, AttributeError):
        return None
    return host.lower().strip(".") if host else None


def matches(domain: str, host: str) -> bool:
    host = host.lower().strip(".")
    if domain.startswith("*."):
        return host.endswith("." + domain[2:])
    return host == domain or host.endswith("." + domain)


def load() -> dict:
    data = common.load_yaml(path(), {}) or {}
    return {key: list(data.get(key) or []) for key in ("allowed", "denied", "pending")}


def save(data: dict) -> None:
    body = common.dump_yaml({key: data.get(key) or [] for key in ("allowed", "denied", "pending")})
    common.atomic_write_text(path(), HEADER + "\n" + body)


def _find(entries: list, host: str):
    for entry in entries:
        if isinstance(entry, dict) and entry.get("domain") and matches(entry["domain"], host):
            return entry
    return None


def status(host: str, data: dict | None = None) -> str:
    """allowed | denied | pending | unknown. Denied wins over allowed."""
    data = data or load()
    if _find(data["denied"], host):
        return "denied"
    if _find(data["allowed"], host):
        return "allowed"
    if _find(data["pending"], host):
        return "pending"
    return "unknown"


def is_allowed(url_or_host: str, data: dict | None = None) -> bool:
    host = host_of(url_or_host) if "://" in url_or_host else url_or_host
    return bool(host) and status(host, data) == "allowed"


def add_pending(data: dict, host: str, requested_by: str | None, today: str, note: str | None = None) -> bool:
    """Record an unknown host or a recruiting-software group ("*.jobs.personio.de").
    Returns True if it is newly pending. Never re-proposes a denied host.
    note: one line shown in the pending list (V3: the vendor documentation that proves the group
    is the software's official domain). Pending only — never allowed by code."""
    domain = normalize_domain(host)
    if not domain or status(domain, data) in ("allowed", "denied"):
        return False
    note = " ".join(str(note).split())[:300] if note else None
    existing = next((e for e in data["pending"] if e.get("domain") == domain), None)
    if existing:
        existing["count"] = int(existing.get("count") or 1) + 1
        existing["last_seen"] = today
        if requested_by and not existing.get("requested_by"):
            existing["requested_by"] = requested_by
        if note and not existing.get("note"):
            existing["note"] = note
        return False
    entry = {"domain": domain, "requested_by": requested_by, "first_seen": today, "last_seen": today, "count": 1}
    if note:
        entry["note"] = note
    data["pending"].append(entry)
    return True


def decide(data: dict, domains: list[str], verdict: str, today: str, source: str = "telegram") -> list[str]:
    """Move pending domains to allowed/denied. Returns the domains moved."""
    assert verdict in ("allowed", "denied")
    moved = []
    for domain in domains:
        entry = next((e for e in data["pending"] if e.get("domain") == domain), None)
        if entry is None:
            continue
        data["pending"].remove(entry)
        target = data[verdict]
        if not any(e.get("domain") == domain for e in target):
            record = {"domain": domain, "added": today, "source": source}
            if entry.get("requested_by"):
                record["requested_by"] = entry["requested_by"]
            if entry.get("note"):
                record["note"] = entry["note"]
            target.append(record)
        if verdict == "denied":
            data["allowed"] = [e for e in data["allowed"] if e.get("domain") != domain]
        moved.append(domain)
    return moved


def allowed_domains(data: dict | None = None) -> list[str]:
    data = data or load()
    denied = {e.get("domain") for e in data["denied"]}
    out = []
    for entry in data["allowed"]:
        domain = entry.get("domain") if isinstance(entry, dict) else None
        if domain and domain not in denied and domain not in out:
            out.append(domain)
    return out
