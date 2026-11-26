#!/usr/bin/env python3
"""Stands in for lualatex / xelatex in tests: writes <output-directory>/<jobname>.pdf and a .log.

Pages from $FAKE_LATEX_PAGES (default 2); $FAKE_LATEX_FAIL=1 exits 1 without a PDF.
A wrapper that sets \\cvoverridesfile must point at an existing file (recorded in <outdir>/<job>.overrides).
"""
import os
import re
import sys
from pathlib import Path

args = sys.argv[1:]
outdir = Path(next((a.split("=", 1)[1] for a in args if a.startswith("-output-directory=")), "."))
src = Path(args[-1])
job = src.stem
outdir.mkdir(parents=True, exist_ok=True)
text = src.read_text(encoding="utf-8")
m = re.search(r"\\def\\cvoverridesfile\{([^}]*)\}", text)
if m:
    if not Path(m.group(1)).is_file():
        (outdir / f"{job}.log").write_text("! LaTeX Error: overrides file not found.\n")
        sys.exit(1)
    (outdir / f"{job}.overrides").write_text(Path(m.group(1)).read_text())
if os.environ.get("FAKE_LATEX_FAIL") == "1":
    (outdir / f"{job}.log").write_text("! Undefined control sequence.\n")
    sys.exit(1)
pages = int(os.environ.get("FAKE_LATEX_PAGES", "2"))
(outdir / f"{job}.pdf").write_bytes(b"%PDF-1.4\n% fake " + job.encode() + b"\n%%EOF\n")
(outdir / f"{job}.log").write_text(f"Output written on {job}.pdf ({pages} pages, 1234 bytes).\n")
