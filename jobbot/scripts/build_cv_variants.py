#!/usr/bin/env python3
"""Compile every CV variant of the block CV (SPEC §9) and check it — zero tokens.

    jobbot/.venv/bin/python jobbot/scripts/build_cv_variants.py [variant ...]
    jobbot/.venv/bin/python jobbot/scripts/build_cv_variants.py --variant delivery \\
        --overrides /abs/cv_overrides.tex --jobname go-123 --out /abs/123_acme_it_cv.pdf

Block CV directory: $JOBBOT_CV_DIR or documents/cv/jobbot/ (gitignored, backed up nightly):
  cv.tex, blocks/*.tex, variants/<name>.tex  ->  pdf/<name>.pdf
Each variant is compiled through a generated wrapper (\\def\\cvvariant{<name>}\\input{cv.tex}) with
the moncv-awesome command (lualatex, build/ redirect). Per application (/jobbot-go, V2) the wrapper
also sets \\cvoverridesfile to that application's cv_overrides.tex; each application has its own
jobname, so several /go compile in parallel without sharing a file.
Checks per PDF:
  * exactly 2 pages (from the LaTeX log);
  * if pypdf is installed: text layer extracted, email and phone (private/candidate.yaml, else
    jobbot/config/candidate.example.yaml) present as literal text,
    no soft hyphen (U+00AD) or replacement character.
Visual inspection stays a human/Claude step. Exit 0 if every variant passes, 1 otherwise.
JOBBOT_LUALATEX replaces `lualatex` (tests).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import common

PAGES = 2
JOBNAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,60}")


def cv_dir() -> Path:
    return common.cv_dir()


def variants(root: Path | None = None) -> list[str]:
    root = root or cv_dir()
    return sorted(p.stem for p in (root / "variants").glob("*.tex") if p.stem != "base")


def variant_pdf(name: str) -> Path:
    return cv_dir() / "pdf" / f"{name}.pdf"


def _tex_path(path: Path) -> str:
    text = str(path.resolve())
    if re.search(r"[\s{}%#\\$&^~]", text):
        raise ValueError(f"path not usable in TeX: {text}")
    return text


SECRET_ENV = ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_USER_ID", "CLAUDE_CODE_OAUTH_TOKEN")


def latex_env() -> dict:
    """Environment of the LaTeX subprocesses (lualatex here, xelatex in offer_pdf.py): no JobBot
    secret (LuaTeX can read the environment), and a TEXMFVAR inside the user's own cache directory
    when none is set — never a shared, predictable place such as /tmp."""
    env = {k: v for k, v in os.environ.items() if k not in SECRET_ENV}
    if not env.get("TEXMFVAR"):
        texmf_var = common.cache_dir() / "texmf-var"
        texmf_var.mkdir(mode=0o700, parents=True, exist_ok=True)
        env["TEXMFVAR"] = str(texmf_var)
    return env


def _compile(root: Path, jobname: str, wrapper_text: str, out_pdf: Path, variant: str) -> dict:
    if not JOBNAME_RE.fullmatch(jobname):
        raise ValueError(f"bad jobname {jobname!r}")
    wrapper = root / f"{jobname}.tex"
    wrapper.write_text(wrapper_text, encoding="utf-8")
    (root / "build").mkdir(exist_ok=True)
    env = latex_env()
    result = {"variant": variant, "jobname": jobname, "ok": False, "pages": None, "errors": [], "text": None,
              "pdf": None}
    try:
        proc = subprocess.run([os.environ.get("JOBBOT_LUALATEX", "lualatex"), "-no-shell-escape",
                               "-interaction=nonstopmode", "-output-directory=build", wrapper.name],
                              cwd=root, env=env, capture_output=True, text=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as exc:
        wrapper.unlink(missing_ok=True)
        result["errors"].append(f"lualatex: {exc}")
        return result
    log = root / "build" / f"{jobname}.log"
    log_text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    built = root / "build" / f"{jobname}.pdf"
    errors = re.findall(r"^! .*", log_text, re.M)
    if errors:
        result["errors"] += errors[:5]
    m = re.search(r"Output written on .*?\((\d+) pages?", log_text)
    if m:
        result["pages"] = int(m.group(1))
    if proc.returncode != 0 or not built.exists():
        result["errors"].append(f"lualatex exit {proc.returncode}")
        built.unlink(missing_ok=True)
        wrapper.unlink(missing_ok=True)
        return result
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(built), out_pdf)
    wrapper.unlink(missing_ok=True)
    result["pdf"] = str(out_pdf)
    if result["pages"] != PAGES:
        result["errors"].append(f"{result['pages']} pages, expected {PAGES}")
    result["text"] = check_text(out_pdf)
    if result["text"] and result["text"].get("problems"):
        result["errors"] += result["text"]["problems"]
    result["ok"] = not result["errors"]
    return result


def compile_variant(root: Path, name: str) -> dict:
    pdf = root / "pdf" / f"{name}.pdf"
    pdf.unlink(missing_ok=True)
    return _compile(root, name, f"\\def\\cvvariant{{{name}}}\\input{{cv.tex}}\n", pdf, name)


def compile_application(variant: str, overrides: Path, jobname: str, out_pdf: Path, root: Path | None = None) -> dict:
    """One application's CV: variant + its own cv_overrides.tex (already validated by texguard)."""
    root = root or cv_dir()
    if variant not in variants(root):
        return {"variant": variant, "jobname": jobname, "ok": False, "errors": [f"unknown variant {variant}"]}
    wrapper = (f"\\def\\cvvariant{{{variant}}}\\def\\cvoverridesfile{{{_tex_path(overrides)}}}"
               f"\\input{{cv.tex}}\n")
    return _compile(root, jobname, wrapper, out_pdf, variant)


def check_text(pdf: Path) -> dict | None:
    try:
        from pypdf import PdfReader  # optional: pip install pypdf in jobbot/.venv
    except ImportError:
        return {"skipped": "pypdf not installed"}
    try:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(pdf)).pages)
    except Exception as exc:  # noqa: BLE001 - a broken PDF is a check failure, not a crash
        return {"chars": 0, "problems": [f"text layer unreadable: {type(exc).__name__}"]}
    problems = []
    who = common.candidate()
    email = str(who.get("email") or "")
    phone_digits = re.sub(r"\D", "", str(who.get("phone") or ""))
    if not email or email not in text:
        problems.append("email not in the text layer")
    if not phone_digits or phone_digits not in re.sub(r"\D", "", text):
        problems.append("phone not in the text layer")
    if "\u00ad" in text:
        problems.append("soft hyphen (U+00AD) in the text layer")
    if "\ufffd" in text or "(cid:" in text:
        problems.append("unmapped glyphs in the text layer")
    return {"chars": len(text), "problems": problems}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("names", nargs="*", help="variants to compile (default: all)")
    ap.add_argument("--variant")
    ap.add_argument("--overrides", type=Path)
    ap.add_argument("--jobname")
    ap.add_argument("--out", type=Path)
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)
    root = cv_dir()
    if args.overrides:
        if not (args.variant and args.jobname and args.out):
            ap.error("--overrides needs --variant, --jobname and --out")
        results = [compile_application(args.variant, args.overrides, args.jobname, args.out, root)]
    else:
        results = [compile_variant(root, n) for n in (args.names or variants(root))]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
