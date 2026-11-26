#!/usr/bin/env python3
"""SPEC §6 set-up: jobbot/config/sites-seed.md -> jobbot/config/sites.yaml, then settings.local.json.

Delete the lines you refuse in sites-seed.md, save, then run:
    jobbot/.venv/bin/python jobbot/scripts/import_seed.py [--dry-run]

Format read: `## <category>` headings, and list lines whose first token is a URL
(`- https://www.karriere.at — comment`) or a group (`- *.myworkdayjobs.com — …`).
Everything else (prose, comments, blank lines) is ignored. Idempotent: an
already allowed domain is left as is; a denied one is never re-allowed here.
A line removed from the seed after an import is NOT revoked: use /deny.
"""

from __future__ import annotations

import argparse
import re
import sys

import common
import sites

_LINE = re.compile(r"^\s*[-*]\s+(?:\[[ xX]\]\s+)?<?(\S+?)>?(?:\s+[—–-]\s+(.*))?\s*$")


def parse_seed(text: str) -> list[dict]:
    entries, category, seen = [], None, set()
    in_comment = False
    for raw in text.splitlines():
        line = raw.strip()
        if "<!--" in line:
            in_comment = "-->" not in line
            continue
        if in_comment:
            in_comment = "-->" not in line
            continue
        if line.startswith("## "):
            category = line[3:].strip()
            continue
        m = _LINE.match(raw)
        if not m:
            continue
        token = m.group(1)
        if not (token.startswith("http://") or token.startswith("https://") or token.startswith("*.")):
            continue
        domain = sites.normalize_domain(token)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        entries.append({"domain": domain, "category": category, "url": token if "://" in token else None,
                        "note": (m.group(2) or "").strip() or None})
    return entries


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seed", default=None, help="default: jobbot/config/sites-seed.md")
    ap.add_argument("--dry-run", action="store_true", help="print what would be imported, write nothing")
    ap.add_argument("--no-settings", action="store_true", help="do not regenerate .claude/settings.local.json")
    args = ap.parse_args(argv)

    seed_path = common.Path(args.seed) if args.seed else common.config_dir() / "sites-seed.md"
    if not seed_path.is_file():
        print(f"import_seed: {seed_path} not found", file=sys.stderr)
        return 1
    entries = parse_seed(seed_path.read_text(encoding="utf-8"))
    if not entries:
        print("import_seed: no site line found in the seed", file=sys.stderr)
        return 1
    today = common.local_now().date().isoformat()

    with common.state_lock():
        data = sites.load()
        added, skipped_denied, already = [], [], []
        for entry in entries:
            domain = entry["domain"]
            if any(e.get("domain") == domain for e in data["denied"]):
                skipped_denied.append(domain)
                continue
            if any(e.get("domain") == domain for e in data["allowed"]):
                already.append(domain)
                continue
            record = {"domain": domain, "category": entry["category"], "added": today, "source": "seed"}
            if entry["url"]:
                record["url"] = entry["url"]
            if entry["note"]:
                record["note"] = entry["note"]
            data["allowed"].append(record)
            data["pending"] = [p for p in data["pending"] if p.get("domain") != domain]
            added.append(domain)
        if not args.dry_run:
            sites.save(data)

    print(f"import_seed: {len(added)} added, {len(already)} already allowed, {len(skipped_denied)} denied (kept denied)"
          + (" [dry-run, nothing written]" if args.dry_run else ""))
    for domain in added:
        print(f"  + {domain}")
    if not args.dry_run and not args.no_settings:
        import gen_settings

        return gen_settings.main([])
    return 0


if __name__ == "__main__":
    sys.exit(main())
