#!/usr/bin/env python3
"""SPEC §5/§6 — sites.yaml -> .claude/settings.local.json and jobbot/state/scan-settings.json.

Run by import_seed.py and by the Telegram bot after /allow or /deny — never by Claude
(the generated deny rules forbid it; the sandbox denies writes to these paths).

Two outputs, because Claude Code ignores `sandbox.network.strictAllowlist` in
project settings (.claude/settings*.json); it is honoured only in user, managed
or `--settings` files:
  * .claude/settings.local.json  — sandbox on for every session in this repo,
    WebFetch(domain:…) rules, protective deny rules (SPEC §5 as written);
  * jobbot/state/scan-settings.json — the same plus strictAllowlist, passed with
    `--settings` to the scheduled `claude -p` run (run_scan.sh).

WebFetch(domain:x) matches x only, so each allowed domain yields both
`domain:x` and `domain:*.x`; a `*.x` group yields only the wildcard. Same for
sandbox.network.allowedDomains.
"""

from __future__ import annotations

import argparse
import json
import sys

import common
import sites


def template() -> dict:
    return json.loads((common.config_dir() / "settings.local.template.json").read_text(encoding="utf-8"))


def network_domains(domains: list[str]) -> list[str]:
    out: list[str] = []
    for domain in domains:
        forms = [domain] if domain.startswith("*.") else [domain, f"*.{domain}"]
        for form in forms:
            if form not in out:
                out.append(form)
    return out


def build(domains: list[str]) -> tuple[dict, dict]:
    tpl = template()
    net = network_domains(domains)
    protected = [str(common.ROOT / p) for p in tpl.get("protectedPaths", [])]
    allow = list(tpl["permissions"]["allow"]) + [f"WebFetch(domain:{d})" for d in net]
    deny = list(tpl["permissions"]["deny"]) + [f"Edit(/{p})" for p in tpl.get("protectedPaths", [])
                                                if f"Edit(/{p})" not in tpl["permissions"]["deny"]]
    sandbox = {
        "enabled": True,
        "failIfUnavailable": True,
        "allowUnsandboxedCommands": False,
        "network": {"strictAllowlist": True, "allowedDomains": net},
        "filesystem": {"denyWrite": protected},
    }
    local = {
        "_generated": "jobbot/scripts/gen_settings.py from jobbot/config/sites.yaml — do not edit by hand",
        "permissions": {"allow": allow, "deny": deny},
        "sandbox": sandbox,
    }
    scan = {
        "_generated": "jobbot/scripts/gen_settings.py — passed with --settings by run_scan.sh",
        "permissions": {"allow": allow, "deny": deny + ["Bash"], "denyInsteadOfPrompting": True},
        "sandbox": sandbox,
    }
    return local, scan


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--print", action="store_true", help="print the settings, write nothing")
    args = ap.parse_args(argv)
    domains = sites.allowed_domains()
    local, scan = build(domains)
    if args.print:
        print(json.dumps({"settings.local.json": local, "scan-settings.json": scan}, indent=2, ensure_ascii=False))
        return 0
    common.atomic_write_json(common.settings_local_path(), local, mode=0o600)
    common.atomic_write_json(common.state_dir() / "scan-settings.json", scan, mode=0o600)
    print(f"gen_settings: {len(domains)} allowed domains -> {common.settings_local_path()} and state/scan-settings.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
