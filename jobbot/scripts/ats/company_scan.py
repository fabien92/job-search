"""Prefilter stage for V3: career pages of the companies in companies.csv, per recruiting software.

  detect   recruiting software of `active` companies without one (zero-network first: employer
           URLs already seen in the ledger; then the career page, only if its host is allowed)
  propose  the vendor's verified group/host as pending in the whitelist (with the doc as note)
  fetch    open positions through the vendor connector, only when every host is allowed
Hosts that are not allowed are never contacted: they are returned in `blocked_hosts`, with the page
that asked for them, and postprocess.py records them as pending (SPEC §6).
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit

import common
import companies
import dedup
import sites

from . import connectors, vendors
from .web import Fetcher, FetchError, NotAllowed, RobotsDenied

REDETECT_DAYS = 30
_CAREER_LINK = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.IGNORECASE)
_CAREER_WORD = re.compile(r"karriere|career|jobs?\b|stellen|join-us|joinus|offene-positionen", re.IGNORECASE)
_REMOTE = re.compile(r"remote|home ?office|telearbeit|anywhere|europe|emea", re.IGNORECASE)


def runs_path():
    return common.state_dir() / "companies_runs.json"


def due(schedule: dict, forced: bool) -> bool:
    if forced:
        return True
    last = common.parse_iso((common.read_json(runs_path(), {}) or {}).get("last"))
    hours = float(schedule.get("companies_every_hours") or 24)
    return last is None or (common.now() - last).total_seconds() >= hours * 3600 - 600


def record_run(checked: dict[str, str]) -> None:
    data = common.read_json(runs_path(), {}) or {}
    data["last"] = common.iso()
    data["checked"] = {**(data.get("checked") or {}), **checked}
    common.atomic_write_json(runs_path(), data)


def _stale(row: dict, today) -> bool:
    if not row["ats"]:
        return True
    if row["ats"] != "unknown":
        return False
    try:
        return (today - common.dt.date.fromisoformat(row["verified"][:10])).days >= REDETECT_DAYS
    except ValueError:
        return True


def detect_from_ledger(row: dict, ledger) -> tuple[str, str] | None:
    for entry in ledger.jobs.values():
        if companies.key_of(entry.get("company")) != row["key"]:
            continue
        for field in ("employer_url", "apply_url", "url"):
            found = vendors.detect_in(entry.get(field) or "")
            if found:
                return found
    return None


def _career_links(base_url: str, body: str) -> list[str]:
    out = []
    for href in _CAREER_LINK.findall(body or ""):
        if _CAREER_WORD.search(href):
            url = urljoin(base_url, href.strip())
            if url.startswith("https://") and url not in out:
                out.append(url)
    return out[:3]


def detect_online(row: dict, fetcher: Fetcher, blocked: list[dict]) -> tuple[str | None, str | None, str | None, bool]:
    """-> (vendor, slug, careers_url, answered). Fetches only allowed hosts; others go to `blocked`.

    answered: the company's pages gave an answer — a page was read, or robots.txt forbids reading it.
    False when nothing could be read (host not allowed yet, network error): "no recruiting software
    found" would then be a guess, and the caller must not record it."""
    requested_by = row["source"] or row["website"] or f"entreprise {row['name']}"
    pages = [u for u in (row["careers_url"], row["website"]) if u]
    seen: set[str] = set()
    answered = False
    while pages and len(seen) < 4:
        url = pages.pop(0)
        if url in seen:
            continue
        seen.add(url)
        found = vendors.detect_in(url)
        if found:
            return found[0], found[1], url, True
        try:
            final, body = fetcher.get(url, accept="text/html")
        except NotAllowed as exc:
            blocked.append({"host": exc.host, "requested_by": requested_by})
            continue
        except RobotsDenied:
            answered = True  # a lasting refusal: no point asking again before REDETECT_DAYS
            continue
        except FetchError:
            continue
        answered = True
        found = vendors.detect_in(final) or vendors.detect_in(body)
        if found:
            return found[0], found[1], (final if url != row["website"] else (row["careers_url"] or final)), True
        if url == row["website"] and not row["careers_url"]:
            pages = _career_links(final, body) + pages
    return None, None, row["careers_url"] or None, answered


def propose_groups(row: dict, whitelist: dict, blocked: list[dict]) -> bool:
    """True when every API host is allowed (the connector can run)."""
    ready = True
    for host in vendors.hosts_for(row["ats"], row["ats_slug"]):
        if sites.is_allowed(host, whitelist):
            continue
        ready = False
        group = vendors.group_for(row["ats"], host) or host
        blocked.append({"host": group, "requested_by": row["careers_url"] or row["website"] or row["source"],
                        "note": vendors.group_note(row["ats"])})
    return ready


def keep_location(location: str | None, rules, regions: dict) -> bool:
    """Company feeds list every office: keep enabled regions and remote jobs only (zero tokens)."""
    if not location:
        return True
    if rules._any_enabled(location):
        return True
    return bool(regions.get("remote_worldwide")) and bool(_REMOTE.search(location))


def collect(rules, ledger, regions: dict, schedule: dict, report: dict, forced: bool = False,
            fetcher: Fetcher | None = None) -> list[dict]:
    """-> raw jobs (prefilter shape + inline `detail`). Updates report[sites|errors|blocked_hosts|rejected]."""
    stats = report["sites"].setdefault("companies", {"queries": 0, "results": 0, "errors": 0})
    if not due(schedule, forced):
        report["skipped_sites"].append({"site": "companies", "reason": "companies_every_hours"})
        return []
    whitelist = sites.load()
    fetcher = fetcher or Fetcher(whitelist)
    today = common.local_now().date()
    rows = companies.load()
    blocked_keys = companies.blocked_keys(rows)
    blocked: list[dict] = []
    updates: dict[str, dict] = {}

    # 1. detection
    budget = int(schedule.get("companies_detect_per_run") or 10)
    for row in rows:
        if row["status"] != "active" or not _stale(row, today):
            continue
        try:
            found = detect_from_ledger(row, ledger)
            careers = row["careers_url"] or None
            if not found and budget > 0:
                before = fetcher.requests
                vendor, slug, careers, answered = detect_online(row, fetcher, blocked)
                if fetcher.requests != before:
                    budget -= 1  # only network use counts: a host still waiting for /allow costs nothing
                found = (vendor, slug) if vendor else None
                if not found and not answered:
                    # Nothing was read (host not allowed yet, network error): stamping "unknown" here
                    # would postpone the next attempt by REDETECT_DAYS, even after an /allow the same day.
                    continue
            elif not found:
                continue
        except Exception as exc:  # noqa: BLE001 - one company must not stop the others
            stats["errors"] += 1
            report["errors"].append({"site": "companies:detect", "query": row["name"],
                                     "error": f"{type(exc).__name__}: {exc}"[:300]})
            continue
        row["ats"], row["ats_slug"] = (found if found else ("unknown", ""))
        row["careers_url"] = careers or row["careers_url"]
        row["verified"] = today.isoformat()
        updates[row["key"]] = {k: row[k] for k in ("ats", "ats_slug", "careers_url", "verified")}

    # 2. proposals + 3. connectors, least recently checked first
    checked_before = (common.read_json(runs_path(), {}) or {}).get("checked") or {}
    ready = []
    for row in rows:
        if row["status"] != "active" or row["ats"] not in connectors.CONNECTORS or not row["ats_slug"]:
            continue
        if companies.is_blocked(row["name"], blocked_keys):
            continue
        if propose_groups(row, whitelist, blocked):
            ready.append(row)
    ready.sort(key=lambda r: checked_before.get(r["key"]) or "")
    jobs, checked = [], {}
    for row in ready[: int(schedule.get("companies_per_run") or 30)]:
        stats["queries"] += 1
        try:
            raw_jobs = connectors.fetch_jobs(row["ats"], row["ats_slug"], row["name"], fetcher)
        except NotAllowed as exc:
            blocked.append({"host": exc.host, "requested_by": row["careers_url"] or row["website"]})
            continue
        except (RobotsDenied, FetchError) as exc:
            stats["errors"] += 1
            report["errors"].append({"site": f"companies:{row['ats']}", "query": row["name"], "error": str(exc)[:300]})
            continue
        except Exception as exc:  # noqa: BLE001 - a feed in an unexpected shape costs this company only
            stats["errors"] += 1
            report["errors"].append({"site": f"companies:{row['ats']}", "query": row["name"],
                                     "error": f"unexpected feed ({type(exc).__name__}: {exc})"[:300]})
            checked[row["key"]] = common.iso()  # back of the line: it must not be the first one tried every run
            continue
        if not isinstance(raw_jobs, list):
            raw_jobs = []
        checked[row["key"]] = common.iso()
        stats["results"] += len(raw_jobs)
        for raw in raw_jobs:
            raw["company"] = raw.get("company") or row["name"]
            raw.update({"query": f"{row['ats']}:{row['name']}", "region": row["region"] or None, "remote_query": False,
                        "pushed": False, "salary": None, "summary": None,
                        "max_age_days": int(schedule.get("companies_max_age_days") or 30)})
            if not keep_location(raw.get("location"), rules, regions):
                report.setdefault("companies_out_of_region", 0)
                report["companies_out_of_region"] += 1
                continue
            jobs.append(raw)

    report["blocked_hosts"] += blocked
    report["companies"] = {"detected": len(updates), "ready": len(ready), "checked": len(checked),
                           "detect_budget_left": budget}
    if not common.dry_run():
        with common.state_lock():
            if updates:
                fresh = companies.load()
                for r in fresh:
                    if r["key"] in updates:
                        r.update(updates[r["key"]])
                companies.save(fresh)
            record_run(checked)
    return jobs
