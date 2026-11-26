#!/usr/bin/env python3
"""V3 (SPEC §10): find new target employers for one enabled region -> companies.csv as `proposed`.

    bash jobbot/scripts/discover.sh <region>          (Telegram /discover <region>)

  request (script) -> claude -p "/jobbot-discover <run>" (WebSearch + WebFetch on allowed hosts only)
  -> validation + dedup (script) -> companies.csv `proposed` -> Telegram "/companies"
Nothing proposed is ever fetched before the user's /accept, and its hosts still go through the
whitelist after that. Never proposed: companies already known (any status, rejected included),
blocked, excluded by criteria.md, or already contacted / applied at.
Test mode (JOBBOT_DRY_RUN=1): proposals go to runs/<run>-discover-proposals.json only.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import common
import companies
import postprocess
import prefilter
import scan
import sites
import telegram_send as tg
from i18n import t

TIMEOUT = 20 * 60
MAX_PROPOSALS = 25
COMMAND = "jobbot-discover"


def discover_lock():
    return common.file_lock(common.state_dir() / ".discover.lock", blocking=False)


def command_installed(name: str = COMMAND) -> bool:
    return (common.ROOT / ".claude" / "commands" / f"{name}.md").is_file()


def webfetch_rules(domains: list[str]) -> list[str]:
    """WebFetch(domain:…) for allowed whitelist entries only (groups `*.x` are not needed here)."""
    out = []
    for d in domains:
        if d.startswith("*."):
            continue
        for host in (d, f"www.{d}"):
            rule = f"WebFetch(domain:{host})"
            if rule not in out:
                out.append(rule)
    return out


def claude_argv(command: str, run_id: str, reads: list[Path], out: Path, fetch_domains: list[str],
                budget: float, model: str) -> list[str]:
    allowed = [f"Read(/{p})" for p in reads] + [f"Write(/{out})", f"Edit(/{out})", "WebSearch"]
    allowed += webfetch_rules(fetch_domains)
    return [
        os.environ.get("JOBBOT_CLAUDE_BIN", "claude"),
        "-p", f"/{command} {run_id}",
        "--permission-mode", "dontAsk",
        "--permission-prompts", "none",
        "--output-format", "json",
        "--max-budget-usd", str(budget),
        "--model", model,
        "--settings", str(common.state_dir() / "scan-settings.json"),
        "--allowedTools", ",".join(allowed),
        "--disallowedTools", "Bash,NotebookEdit,Task,Agent",
    ]


_URL = re.compile(r"^https?://[^\s<>\"']+$")


def validate(doc, region: str) -> tuple[list[dict], list[str]]:
    """-> (clean proposals, problems). Each needs a name, an https official site and a source link."""
    items = doc.get("companies") if isinstance(doc, dict) else None
    if not isinstance(items, list):
        return [], ["output has no `companies` list"]
    out, problems = [], []
    for raw in items[: MAX_PROPOSALS * 2]:
        if not isinstance(raw, dict):
            continue
        name = " ".join(str(raw.get("name") or "").split())[:120]
        website = str(raw.get("website") or "").strip().rstrip("/")
        source = str(raw.get("source_url") or "").strip()
        if not name or not companies.key_of(name):
            problems.append("name missing")
            continue
        if not website.startswith("https://") or not _URL.match(website) or not companies.website_host(website):
            problems.append(f"{name}: invalid official site")
            continue
        if not _URL.match(source):
            problems.append(f"{name}: source missing")
            continue
        out.append({"name": name, "website": website, "source": source,
                    "city": " ".join(str(raw.get("city") or "").split())[:60] or region,
                    "category": " ".join(str(raw.get("category") or "").split())[:60],
                    "reason": " ".join(str(raw.get("reason") or "").split())[:160]})
    return out, problems


def filter_new(proposals: list[dict], rows: list[dict]) -> tuple[list[dict], dict]:
    excluded = {companies.key_of(c) for c in prefilter.load_criteria()["company_exclusions"]}
    blocked = companies.blocked_keys(rows)
    contacted = companies.contacted_keys()
    known_keys = {r["key"] for r in rows}
    known_hosts = {companies.website_host(r["website"]) for r in rows if r["website"]}
    kept, dropped = [], {"known": 0, "excluded": 0, "blocked": 0, "contacted": 0}
    for p in proposals:
        key, host = companies.key_of(p["name"]), companies.website_host(p["website"])
        if key in known_keys or host in known_hosts:
            dropped["known"] += 1
        elif any(key == x or key.startswith(x + " ") for x in excluded if x):
            dropped["excluded"] += 1
        elif companies.is_blocked(p["name"], blocked):
            dropped["blocked"] += 1
        elif companies.matches_any(p["name"], contacted):
            dropped["contacted"] += 1
        else:
            kept.append(p)
            known_keys.add(key)
            known_hosts.add(host)
    return kept[:MAX_PROPOSALS], dropped


def run(region: str) -> int:
    regions = common.load_regions()["regions"]
    if region not in regions or not (regions[region] or {}).get("enabled"):
        tg.send(t("discover.bad_region", region=tg.esc(region)))
        return 1
    if not command_installed():
        tg.send(t("discover.not_installed"))
        return 1
    if not (common.state_dir() / "scan-settings.json").is_file():
        tg.send("/discover : " + t("common.whitelist_missing") + ".")
        return 1
    schedule = common.load_schedule()
    run_id = common.stamp() + ("-test" if common.dry_run() else "")
    runs = common.runs_dir()
    out = runs / f"discover-{run_id}.json"
    request = runs / f"discover-{run_id}-request.json"
    rows = companies.load()
    criteria = prefilter.load_criteria()
    common.atomic_write_json(request, {
        "run_id": run_id, "region": region, "region_names": (regions[region] or {}).get("names") or [region],
        "country": (regions[region] or {}).get("country"), "max": MAX_PROPOSALS, "output_path": str(out),
        "target_titles": (criteria["titles_en"] + criteria["titles_de"])[:40],
        "language": t("scoring.language"),
        "already_known": sorted({r["name"] for r in rows})[:600],
        "excluded": criteria["company_exclusions"],
    })
    argv = claude_argv(COMMAND, run_id, [request], out, sites.allowed_domains(),
                       float(schedule["max_budget_usd_per_discover"]), str(schedule.get("discover_model") or "sonnet"))
    code, result = scan.invoke_claude(argv, runs / f"discover-{run_id}-claude.json", TIMEOUT)
    info = postprocess.read_claude_output(Path(result))
    failure = postprocess.classify_failure(info, code)
    if failure or not out.exists():
        tg.send(t("discover.failed", region=tg.esc(region), error=tg.esc(failure or t("discover.no_file"))))
        return 1
    proposals, problems = validate(common.read_json(out, {}), region)
    with common.state_lock():
        rows = companies.load()
        kept, dropped = filter_new(proposals, rows)
        if common.dry_run():
            common.atomic_write_json(runs / f"discover-{run_id}-proposals.json", kept)
        else:
            today = common.local_now().date().isoformat()
            for p in kept:
                row, _ = companies.add(rows, p["name"], city=p["city"], region=region, website=p["website"],
                                       source=p["source"], origin=f"discover:{companies.website_host(p['source'])}"[:80])
                row["status"] = "proposed"
                row["verified"] = today
            companies.save(rows)
    prefix = "[TEST] " if common.dry_run() else ""
    lines = [prefix + t("discover.result", region=tg.esc(region), n=len(kept), **dropped)
             + (t("discover.invalid", n=len(problems)) if problems else ""),
             t("discover.cost", cost=info['total_cost_usd'])]
    if kept:
        lines.append(t("discover.validate"))
    tg.send("\n".join(lines))
    common.log(f"discover {run_id} {region}: kept={len(kept)} dropped={dropped} problems={problems[:5]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("region")
    args = ap.parse_args(argv)
    try:
        with discover_lock():
            return run(args.region.strip().lower())
    except common.LockBusy:
        tg.send(t("discover.busy_cmd"))
        return 3


if __name__ == "__main__":
    sys.exit(main())
