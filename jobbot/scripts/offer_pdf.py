#!/usr/bin/env python3
"""offre.pdf from an archived posting (SPEC §9.5) — zero tokens, no network.

    jobbot/.venv/bin/python jobbot/scripts/offer_pdf.py POSTING.md OUT.pdf [--title T --company C --url U --id ID]

The archived text (posting_guard-cleaned) is escaped character by character into a small LaTeX
document and compiled with xelatex (JOBBOT_XELATEX replaces it in tests). The `## posting_guard`
section of the archive is left out of the PDF. The text can never inject a command: every TeX
special character is escaped, and control characters are dropped.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

import build_cv_variants
import common
from i18n import t

_SPECIALS = {
    "\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$", "&": r"\&", "#": r"\#", "^": r"\^{}",
    "_": r"\_", "%": r"\%", "~": r"\textasciitilde{}", "<": r"\textless{}", ">": r"\textgreater{}",
}


ZERO_WIDTH = {chr(c) for c in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0xFE0F)}


def escape(text: str) -> str:
    out = []
    for ch in str(text or ""):
        if ch in _SPECIALS:
            out.append(_SPECIALS[ch])
        elif ch == "\t":
            out.append(" ")
        elif ord(ch) < 32 or 0x7F <= ord(ch) < 0xA0 or ch in ZERO_WIDTH:
            continue
        elif unicodedata.category(ch) in ("So", "Cs", "Co", "Cn"):  # emoji / symbols: no glyph in the font
            continue
        else:
            out.append(ch)
    return "".join(out)


def body_of(archive_text: str) -> str:
    """The posting text without the archive's trailing `## posting_guard` section."""
    head, sep, _ = archive_text.rpartition("\n## posting_guard")
    return head if sep else archive_text


def to_latex(text: str, meta: dict) -> str:
    lines = []
    for raw in body_of(text).splitlines():
        line = raw.rstrip()
        if not line.strip():
            lines.append(r"\medskip")
            continue
        stripped = line.lstrip()
        if stripped.startswith("#"):
            lines.append(r"\textbf{" + escape(stripped.lstrip("#").strip()) + r"}\par")
        elif stripped[:2] in ("- ", "* ", "• "):
            lines.append(r"\hangindent=1.2em\hangafter=1 \textbullet\ " + escape(stripped[2:]) + r"\par")
        else:
            lines.append(escape(stripped) + r"\par")
    head = [r"{\Large\bfseries " + escape(meta.get("title") or "Offre") + r"}\par"]
    sub = " · ".join(x for x in (meta.get("company"), meta.get("location")) if x)
    if sub:
        head.append(escape(sub) + r"\par")
    if meta.get("url"):
        head.append(r"{\small " + escape(meta["url"]) + r"}\par")
    note = f"Archived by JobBot #{meta['id']}" if meta.get("id") else "Archived by JobBot"
    head.append(r"{\small\itshape " + escape(f"{note} — {common.local_now().strftime('%Y-%m-%d')}") + r"}\par")
    return "\n".join([
        r"\documentclass[10pt,a4paper]{article}",
        r"\usepackage{fontspec}",
        r"\usepackage[margin=2cm]{geometry}",
        r"\setlength{\parindent}{0pt}\setlength{\parskip}{3pt}\sloppy\emergencystretch=3em",
        r"\pagestyle{plain}",
        r"\begin{document}",
        *head,
        r"\medskip\hrule\medskip",
        *lines,
        r"\end{document}",
        "",
    ])


def build(archive: Path, out_pdf: Path, meta: dict) -> tuple[bool, str | None]:
    """-> (ok, error). Compiles in a private temp dir, then moves the PDF to out_pdf."""
    try:
        text = archive.read_text(encoding="utf-8")
    except OSError as exc:
        return False, t("offer.unreadable", error=exc)
    work = Path(tempfile.mkdtemp(prefix="offre-", dir=common.cache_dir()))
    try:
        (work / "offre.tex").write_text(to_latex(text, meta), encoding="utf-8")
        env = build_cv_variants.latex_env()  # no JobBot secret, TEXMFVAR in the user's own cache
        argv = [os.environ.get("JOBBOT_XELATEX", "xelatex"), "-no-shell-escape", "-interaction=nonstopmode",
                "-halt-on-error", "-output-directory=" + str(work), "offre.tex"]
        try:
            proc = subprocess.run(argv, cwd=work, env=env, capture_output=True, text=True, timeout=180)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f"xelatex : {exc}"
        built = work / "offre.pdf"
        if proc.returncode != 0 or not built.exists():
            log = (work / "offre.log").read_text(encoding="utf-8", errors="replace") if (work / "offre.log").exists() else ""
            first = next((ln for ln in log.splitlines() if ln.startswith("! ")), f"exit {proc.returncode}")
            return False, f"xelatex : {first[:200]}"
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(built), out_pdf)
        return True, None
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("posting", type=Path)
    ap.add_argument("out", type=Path)
    for key in ("title", "company", "location", "url", "id"):
        ap.add_argument(f"--{key}")
    args = ap.parse_args(argv)
    ok, error = build(args.posting, args.out, {k: getattr(args, k) for k in ("title", "company", "location", "url", "id")})
    print("ok" if ok else error)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
