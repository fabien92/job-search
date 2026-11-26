#!/usr/bin/env python3
"""V3: the 20:00 list of companies for a spontaneous application (launchd com.jobbot.spont). Zero tokens.

Picks `spont_list_size` active companies that are:
  - not blocked (/block, prefix rule included);
  - never contacted: no row in contacts.csv for them, whatever its status (prepared, sent, cancelled);
  - never applied at: no tracker row past `drafted` (applied, interview, offer, rejected…);
  - not listed in the last `spont_list_repeat_days` days (rotation).
Companies whose official site is already allowed come first (/spont can run at once).
Test mode (JOBBOT_DRY_RUN=1): [TEST] prefix, the rotation is not recorded.
"""

from __future__ import annotations

import sys

import common
import companies
import sites
import telegram_send as tg
from i18n import t


def listed_path():
    return common.state_dir() / "spont_listed.json"


def pick(schedule: dict) -> list[dict]:
    rows = companies.load()
    blocked = companies.blocked_keys(rows)
    contacted = companies.contacted_keys()
    listed = common.read_json(listed_path(), {}) or {}
    now = common.now()
    repeat = int(schedule.get("spont_list_repeat_days") or 14) * 86400
    whitelist = sites.load()
    out = []
    for r in rows:
        if r["status"] != "active" or not r["website"]:
            continue
        if companies.is_blocked(r["name"], blocked) or companies.matches_any(r["name"], contacted):
            continue
        last = common.parse_iso(listed.get(r["key"]))
        if last and (now - last).total_seconds() < repeat:
            continue
        out.append(r)
    out.sort(key=lambda r: (not sites.is_allowed(companies.website_host(r["website"]), whitelist),
                            listed.get(r["key"]) or "", r["name"].casefold()))
    return out[: int(schedule.get("spont_list_size") or 5)]


def build(chosen: list[dict]) -> str:
    prefix = "[TEST] " if common.dry_run() else ""
    if not chosen:
        return prefix + t("spont_list.none")
    whitelist = sites.load()
    lines = [prefix + t("spont_list.title")]
    for i, r in enumerate(chosen, 1):
        host = companies.website_host(r["website"])
        ats = f" · {r['ats']}" if r["ats"] and r["ats"] != "unknown" else ""
        wait = "" if sites.is_allowed(host, whitelist) else t("spont_list.to_allow")
        lines.append(f"{i}. <b>{tg.esc(r['name'])}</b> · {tg.esc(r['city'] or '?')} · {tg.link(r['website'], host)}"
                     f"{tg.esc(ats)}{wait}\n   /spont {tg.esc(r['name'])}")
    lines.append(t("spont_list.hint"))
    return "\n".join(lines)


def main() -> int:
    schedule = common.load_schedule()
    chosen = pick(schedule)
    tg.send(build(chosen))
    if chosen and not common.dry_run():
        with common.state_lock():
            listed = common.read_json(listed_path(), {}) or {}
            for r in chosen:
                listed[r["key"]] = common.iso()
            common.atomic_write_json(listed_path(), listed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
