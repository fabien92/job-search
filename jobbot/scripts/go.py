#!/usr/bin/env python3
"""/go circuit (SPEC §9, V2): prepare one application — Claude only when the scoring said `adapt: oui`.

    bash jobbot/scripts/go.sh <ID>            (what the Telegram /go command launches)
    jobbot/.venv/bin/python jobbot/scripts/go.py <ID> [--force]

  1. the scored job (ledger, or the dry-run alerts for a T-ID) and its archived posting;
  2. adaptation non -> copy documents/cv/jobbot/pdf/<variant>.pdf (zero tokens);
     adaptation oui -> claude -p "/jobbot-go <ID>" writes ONLY cv_overrides.tex -> texguard ->
     build_cv_variants (own jobname: several /go run in parallel) -> 2 pages + text layer
     (+ tools/verify_layout.py when Poppler is installed). Any failure falls back to the plain
     variant PDF and says why: Claude is never asked twice;
  3. offre.pdf from the archived posting (offer_pdf.py), job_posting.md as /apply archives it;
  4. documents/applications/<company>_<role>/, tracker row `drafted`, pending.json, events.jsonl;
  5. Telegram: summary + CV + offre.pdf, as replies to the alert message, files named
     ID_entreprise_poste_*.pdf. No cover letter, ever (the user's decision, 2026-11-24).
A T-ID (test scan) runs in test mode: [TEST] messages, nothing written to the tracker, the ledger
or pending.json (see applications.py). Exit 0 ok, 1 failed, 3 this ID is already being prepared.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

import applications as apps
import build_cv_variants
import common
import offer_pdf
import postprocess
import rule_scorer
import scan
import telegram_send as tg
import texguard
from i18n import t

GO_TIMEOUT = 10 * 60
DEFAULT_VARIANT = "delivery"


def default_variant() -> str:
    """`default_variant` of schedule.yaml when that variant exists, else the first one of the block CV."""
    known = build_cv_variants.variants()
    wanted = str(common.load_schedule().get("default_variant") or DEFAULT_VARIANT).strip()
    return wanted if wanted in known or not known else sorted(known)[0]


def go_lock(short_id: str):
    return common.file_lock(common.state_dir() / f".go-{short_id}.lock", blocking=False)


def is_running(short_id: str) -> bool:
    """Read-only probe: never takes the lock, so it cannot make a starting /go give up."""
    return common.lock_held(common.state_dir() / f".go-{short_id}.lock")


def command_installed() -> bool:
    return (common.ROOT / ".claude" / "commands" / "jobbot-go.md").is_file()


def claude_argv(short_id: str, request: Path, posting: Path, out: Path, schedule: dict,
                reads: tuple[Path, ...] = ()) -> list[str]:
    # Every file the command reads is allowed by its exact path (profile, default macros, variant):
    # the run does not depend on what the session may read by default.
    allowed = [f"Read(/{p})" for p in dict.fromkeys((request, posting, *reads))]
    allowed += [f"Write(/{out})", f"Edit(/{out})"]
    return [
        os.environ.get("JOBBOT_CLAUDE_BIN", "claude"),
        "-p", f"/jobbot-go {short_id}",
        "--permission-mode", "dontAsk",
        "--permission-prompts", "none",
        "--output-format", "json",
        "--max-budget-usd", str(schedule["max_budget_usd_per_go"]),
        "--model", str(schedule.get("go_model") or "sonnet"),
        "--settings", str(common.state_dir() / "scan-settings.json"),
        "--allowedTools", ",".join(allowed),
        "--disallowedTools", "Bash,WebFetch,WebSearch,NotebookEdit,Task,Agent",
    ]


def verify_layout(pdf: Path) -> str:
    """Upstream tools/verify_layout.py: 'clean' | 'problems: …' | 'indisponible' (no Poppler)."""
    try:
        proc = subprocess.run([sys.executable, str(common.TOOLS / "verify_layout.py"), str(pdf)],
                              capture_output=True, text=True, timeout=120, cwd=common.ROOT)
    except (OSError, subprocess.TimeoutExpired):
        return "indisponible"
    if proc.returncode == 0:
        return "clean"
    if proc.returncode == 1:
        return "problems: " + " ".join(proc.stdout.split("LAYOUT PROBLEMS:", 1)[-1].split())[:300]
    return "indisponible"


def adapt_cv(short_id: str, job: dict, variant: str, posting: Path, appdir: Path, cv_out: Path,
             schedule: dict) -> tuple[bool, str, float]:
    """-> (adapted, note, cost). On any failure the caller copies the plain variant."""
    if not command_installed():
        return False, t("go.not_installed"), 0.0
    if not (common.state_dir() / "scan-settings.json").is_file():
        return False, t("common.whitelist_missing"), 0.0
    runs = common.runs_dir()
    out = runs / f"go-{short_id}-cv_overrides.tex"
    out.unlink(missing_ok=True)
    request = runs / f"go-{short_id}-request.json"
    root = build_cv_variants.cv_dir()
    common.atomic_write_json(request, {
        "id": short_id, "title": job.get("title"), "company": job.get("company"),
        "posting_path": str(posting), "variant": variant,
        "variant_path": str(root / "variants" / f"{variant}.tex"),
        "content_path": str(root / "blocks" / "content.tex"),
        "adapt_reason": job.get("adapt_reason"), "output_path": str(out),
    })
    reads = (common.profile_file(), root / "blocks" / "content.tex", root / "variants" / f"{variant}.tex")
    code, result_path = scan.invoke_claude(claude_argv(short_id, request, posting, out, schedule, reads),
                                           runs / f"go-{short_id}-claude.json", GO_TIMEOUT)
    info = postprocess.read_claude_output(Path(result_path))
    cost = info["total_cost_usd"]
    failure = postprocess.classify_failure(info, code)
    if failure:
        return False, t("go.claude_failed", error=f"{failure}: {info.get('error') or code}"), cost
    if not out.exists():
        return False, t("go.no_overrides"), cost
    try:
        texguard.check_file(out)
    except texguard.Refused as exc:
        return False, t("go.overrides_refused", error=exc), cost
    overrides = appdir / "cv_overrides.tex"
    shutil.copyfile(out, overrides)
    try:
        result = build_cv_variants.compile_application(variant, overrides, f"go-{short_id}", cv_out)
    except ValueError as exc:  # e.g. a path TeX cannot take (space, ~, #...): plain variant instead
        common.log(f"go {short_id}: cannot compile the adapted CV: {exc}")
        result = {"ok": False, "errors": [str(exc)]}
    if not result.get("ok"):
        cv_out.unlink(missing_ok=True)
        return False, t("go.compile", errors="; ".join(result.get("errors") or [t("go.failed")])[:300]), cost
    layout = verify_layout(cv_out)
    note = t("go.adapted_note")
    if layout.startswith("problems"):
        note += t("go.layout_check", problems=layout[10:])
    elif layout == "indisponible":
        note += t("go.layout_unavailable")
    return True, note, cost


def summary_text(short_id: str, job: dict, variant: str, adapted: bool, note: str, offer_ok: bool,
                 offer_err: str | None) -> str:
    lines = [f"<b>📄 #{tg.esc(short_id)} · {tg.esc(job.get('company') or '?')} · {tg.esc(job.get('title') or '?')}</b>",
             t("go.summary_cv_adapted" if adapted else "go.summary_cv_plain", variant=tg.esc(variant))]
    if note:
        lines.append(f"<i>{tg.esc(note)}</i>")
    if not offer_ok:
        lines.append(t("go.offer_missing", error=tg.esc(offer_err)))
    if job.get("url"):
        lines.append(tg.link(job["url"], t("go.apply_link")))
    lines.append(t("go.after", id=tg.esc(short_id)))
    return "\n".join(lines)


def send_files(short_id: str, files: list[tuple[Path, str]], reply_to: int | None) -> tuple[list[dict], list[str]]:
    """-> (sent [{message_id, sent, file, name}], errors)."""
    sent, errors = [], []
    for path, name in files:
        mid, err = tg.send_document(path, name, reply_to=reply_to)
        if mid:
            sent.append({"message_id": mid, "sent": common.iso(), "file": str(path), "name": name})
        else:
            errors.append(f"{name} : {err}")
    return sent, errors


def run(short_id: str, force: bool = False) -> int:
    schedule = common.load_schedule()
    job = apps.find_job(short_id)
    if not job:
        tg.send(t("go.unknown_id", id=tg.esc(short_id)) + (t("go.no_test_alert") if apps.is_test_id(short_id) else ""))
        return 1
    existing = apps.get_pending(short_id)
    if existing and not force:
        tg.send(t("go.already_ready", id=tg.esc(short_id)),
                reply_to=job.get("message_id"))
        return 0
    posting = apps.posting_path(short_id)
    if not posting.exists():
        tg.send(t("go.no_posting", id=tg.esc(short_id), name=tg.esc(posting.name)), reply_to=job.get("message_id"))
        return 1

    fallback = default_variant()
    variant = job.get("variant") if job.get("variant") in build_cv_variants.variants() else fallback
    company, title = job.get("company") or "entreprise", job.get("title") or "poste"
    appdir = apps.application_dir(short_id, company, title)
    appdir.mkdir(parents=True, exist_ok=True)
    (appdir / ".jobbot-id").write_text(short_id + "\n", encoding="utf-8")
    stem = apps.file_stem(short_id, company, title)
    cv_out = appdir / f"{stem}_CV.pdf"

    adapted, note, cost = False, "", 0.0
    if job.get("adapt") and not rule_scorer.enabled(schedule):  # scoring: rules never calls Claude
        adapted, note, cost = adapt_cv(short_id, job, variant, posting, appdir, cv_out, schedule)
        if not adapted:
            note = t("go.adapt_dropped", note=note)
    elif not job.get("variant"):
        note = t("go.no_variant", variant=fallback)
    if not adapted:
        source = build_cv_variants.variant_pdf(variant)
        if not source.exists():
            tg.send(t("go.variant_missing", id=tg.esc(short_id), name=tg.esc(source.name)),
                    reply_to=job.get("message_id"))
            return 1
        shutil.copyfile(source, cv_out)

    offer = appdir / "offre.pdf"
    offer_ok, offer_err = offer_pdf.build(posting, offer, {
        "title": title, "company": company, "location": job.get("location"), "url": job.get("url"), "id": short_id})
    archived = appdir / "job_posting.md"
    if not archived.exists():  # /apply Step 6b.7: an existing archive is what was submitted — keep it
        shutil.copyfile(posting, archived)

    reply_to = job.get("message_id")
    summary_id = tg.send(summary_text(short_id, job, variant, adapted, note, offer_ok, offer_err), reply_to=reply_to)
    files = [(cv_out, f"{stem}_CV.pdf")] + ([(offer, f"{stem}_offre.pdf")] if offer_ok else [])
    sent, errors = send_files(short_id, files, reply_to or summary_id)
    if errors:
        tg.send(t("go.incomplete", errors=tg.esc("; ".join(errors)), id=tg.esc(short_id)),
                reply_to=reply_to)

    rel_cv = str(cv_out.relative_to(common.ROOT)) if cv_out.is_relative_to(common.ROOT) else str(cv_out)
    malformed = None
    with common.state_lock():
        try:
            tracker = apps.tracker_drafted(short_id, job, rel_cv)
        except apps.TrackerMalformed as exc:  # the files are sent: keep the application pending, say what to repair
            tracker, malformed = "malformed", exc
        pending = apps.load_pending(apps.is_test_id(short_id))
        previous = pending.get(short_id) or {}
        pending[short_id] = {
            "id": short_id, "company": company, "title": title, "url": job.get("url"), "site": job.get("site"),
            "score": job.get("score"), "variant": variant, "adapted": adapted, "note": note,
            "dir": str(appdir), "cv": str(cv_out), "offer": str(offer) if offer_ok else None,
            "go_at": previous.get("go_at") or common.iso(), "alert_message_id": reply_to,
            "telegram": (previous.get("telegram") or []) + sent, "test": apps.is_test_id(short_id),
        }
        apps.save_pending(apps.is_test_id(short_id), pending)
        if not apps.is_test_id(short_id):
            apps.set_ledger_status(short_id, "drafted", go_at=common.iso())
        apps.log_event("go", short_id, adapted=adapted, cost_usd=cost)
    if malformed is not None:
        tg.send(t("bot.tracker_malformed", line=malformed.line, company=tg.esc(malformed.company)), reply_to=reply_to)
    common.log(f"go {short_id}: variant={variant} adapted={adapted} files={len(sent)} tracker={tracker} cost={cost}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("id")
    ap.add_argument("--force", action="store_true", help="prepare again even if already pending")
    args = ap.parse_args(argv)
    short_id = apps.norm_id(args.id)
    if not short_id:
        print(f"go: invalid ID {args.id!r}", file=sys.stderr)
        return 2
    if apps.is_test_id(short_id):
        os.environ["JOBBOT_DRY_RUN"] = "1"  # T-IDs come from a test scan: test mode end to end
    try:
        with go_lock(short_id):
            try:
                return run(short_id, args.force)
            except Exception as exc:  # noqa: BLE001 - any crash must reach Telegram
                common.log(traceback.format_exc())
                tg.send(t("go.crashed", id=tg.esc(short_id), error=f"{tg.esc(type(exc).__name__)}: {tg.esc(str(exc)[:300])}"))
                return 1
    except common.LockBusy:
        common.log(f"go {short_id}: already running")
        return 3


if __name__ == "__main__":
    sys.exit(main())
