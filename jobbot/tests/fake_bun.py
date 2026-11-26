#!/usr/bin/env python3
"""Stands in for `bun` in tests: `fake_bun.py run <.../<skill>/cli/src/cli.ts> search|detail ...`.

Serves JSON from $JOBBOT_FAKE_PORTALS/<skill>-search.json (all queries) and
<skill>-detail-<id>.json (a detail URL is served by its last path segment); logs every call to $JOBBOT_FAKE_PORTALS/calls.log.
A missing file -> exit 1 with the portal error convention. Never touches the network.
"""
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
if args == ["--version"]:
    print("1.4.5-fake")
    sys.exit(0)
root = Path(os.environ["JOBBOT_FAKE_PORTALS"])
with open(root / "calls.log", "a", encoding="utf-8") as fh:
    fh.write(json.dumps(args) + "\n")
skill = Path(args[1]).parts[-4]
cmd = args[2]
name = f"{skill}-search.json" if cmd == "search" else f"{skill}-detail-{args[3].rstrip('/').rsplit('/', 1)[-1]}.json"
path = root / name
if not path.is_file():
    sys.stderr.write(json.dumps({"error": f"no fixture {name}", "code": "NOT_FOUND"}) + "\n")
    sys.exit(1)
sys.stdout.write(path.read_text(encoding="utf-8"))
