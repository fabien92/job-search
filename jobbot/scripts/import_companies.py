#!/usr/bin/env python3
"""config/companies-seed.md (validated by the user) -> state/companies.csv (SPEC §10, V3).

    jobbot/.venv/bin/python jobbot/scripts/import_companies.py [--seed jobbot/config/companies-seed.md] [--dry-run]

Line format:  - Name · City · https://official-site · source : https://source-page
Adds each company as `active` (origin `seed`, the `##` heading as category). Existing companies
(same normalised name or same website host) are left as they are — a blocked or rejected company
stays so. Touches neither sites.yaml nor any whitelist file: the hosts of these sites are proposed
later, one by one, when the scan needs them (pending -> /allow).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import common
import companies


def run(seed: Path, dry: bool) -> dict:
    entries, bad = companies.parse_seed(seed.read_text(encoding="utf-8"))
    excluded = set()
    try:
        import prefilter

        excluded = {companies.key_of(c) for c in prefilter.load_criteria()["company_exclusions"]}
    except Exception:  # noqa: BLE001 - criteria.md unreadable: import anyway, the scan filters again
        pass
    added, kept, refused = [], [], []
    with common.state_lock():
        rows = companies.load()
        for e in entries:
            key = companies.key_of(e["name"])
            if any(key == x or key.startswith(x + " ") for x in excluded if x):
                refused.append(e["name"])
                continue
            row, created = companies.add(rows, e["name"], city=e["city"], region=companies.region_of(e["city"]),
                                         website=e["website"], origin=f"seed:{e['category']}"[:80], source=e["source"])
            (added if created else kept).append(row["name"])
        if not dry:
            companies.save(rows)
    return {"added": added, "kept": kept, "excluded": refused, "malformed": bad}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", type=Path, default=common.config_dir() / "companies-seed.md")
    ap.add_argument("--dry-run", action="store_true", help="show what would be imported, write nothing")
    args = ap.parse_args(argv)
    if not args.seed.exists():
        print(f"import_companies: {args.seed} not found", file=sys.stderr)
        return 1
    result = run(args.seed, args.dry_run)
    print(f"import_companies: {len(result['added'])} added, {len(result['kept'])} already known, "
          f"{len(result['excluded'])} excluded by criteria.md, {len(result['malformed'])} malformed line(s)"
          + (" [dry run, nothing written]" if args.dry_run else f" -> {companies.path()}"))
    for line in result["malformed"]:
        print(f"  malformed: {line}")
    for name in result["excluded"]:
        print(f"  excluded: {name}")
    return 0 if not result["malformed"] else 2


if __name__ == "__main__":
    sys.exit(main())
