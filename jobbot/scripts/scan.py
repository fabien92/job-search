#!/usr/bin/env python3
"""One scheduled or manual scan (SPEC §12), launched by run_scan.sh.

  lock -> prefilter.py (zero tokens) -> scoring -> postprocess.py (zero tokens) -> monitor.py -> log rotation

Scoring follows `scoring` in schedule.yaml: `claude` runs claude -p "/jobbot-scan <id>" (scoring only);
`rules` runs rule_scorer.py (keyword score from criteria.md, no AI, no Claude account).

    jobbot/.venv/bin/python jobbot/scripts/scan.py [--site all|karriere|linkedin|derstandard|uncareers|unido|osce|opecfund|hays|jobgether|randstad|profession|kariera|michaelpage|companies]

Exit 0 ok, 1 failed, 3 another scan is already running.
Test hooks: JOBBOT_CLAUDE_BIN replaces `claude`; JOBBOT_DRY_RUN=1 (SPEC §12).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import traceback

import common
import monitor
from i18n import t
import postprocess
import prefilter
import rule_scorer

CLAUDE_TIMEOUT = 20 * 60
LOG_DAYS = 30
CACHE_DAYS = 7


def claude_argv(run_id: str, schedule: dict) -> list[str]:
    scores = common.runs_dir() / f"{run_id}-scores.json"
    cache = common.cache_dir()
    allowed = [f"Read(/{cache}/**)", f"Write(/{scores})", f"Edit(/{scores})"]
    return [
        os.environ.get("JOBBOT_CLAUDE_BIN", "claude"),
        "-p", f"/jobbot-scan {run_id}",
        "--permission-mode", "dontAsk",
        "--permission-prompts", "none",
        "--output-format", "json",
        "--max-budget-usd", str(schedule["max_budget_usd_per_run"]),
        "--model", str(schedule.get("scan_model") or "sonnet"),
        "--settings", str(common.state_dir() / "scan-settings.json"),
        "--allowedTools", ",".join(allowed),
        "--disallowedTools", "Bash,WebFetch,WebSearch,NotebookEdit,Task,Agent",
    ]


def call_claude(run_id: str, schedule: dict) -> tuple[int, str]:
    out_path = common.runs_dir() / f"{run_id}-claude.json"
    return invoke_claude(claude_argv(run_id, schedule), out_path)


def invoke_claude(argv: list[str], out_path, timeout: int = CLAUDE_TIMEOUT) -> tuple[int, str]:
    """Run `claude -p …` with the OAuth token and without the bot credentials; the JSON result goes
    to out_path (a synthetic error result on timeout / start failure). Shared with go.py."""
    env = dict(os.environ)
    secrets = common.load_secrets()
    if secrets.get("CLAUDE_CODE_OAUTH_TOKEN"):
        env["CLAUDE_CODE_OAUTH_TOKEN"] = secrets["CLAUDE_CODE_OAUTH_TOKEN"]
    for leak in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"):
        env.pop(leak, None)  # Claude never needs the bot credentials
    common.log("claude: " + " ".join(argv[:3]) + " …")
    try:
        proc = subprocess.run(argv, cwd=common.ROOT, env=env, capture_output=True, text=True, timeout=timeout,
                              stdin=subprocess.DEVNULL)
        out_path.write_text(proc.stdout or "", encoding="utf-8")
        if proc.stderr.strip():
            common.log("claude stderr: " + proc.stderr.strip()[-2000:])
        return proc.returncode, str(out_path)
    except subprocess.TimeoutExpired:
        out_path.write_text(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                                        "errors": [f"timeout after {timeout}s"]}), encoding="utf-8")
        return 124, str(out_path)
    except OSError as exc:
        out_path.write_text(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                                        "errors": [f"cannot start claude: {exc}"]}), encoding="utf-8")
        return 127, str(out_path)


def rotate() -> None:
    cutoff = time.time() - LOG_DAYS * 86400
    for path in common.runs_dir().iterdir():
        if path.is_file() and path.stat().st_mtime < cutoff:
            path.unlink(missing_ok=True)
    cache_runs = common.cache_dir() / "runs"
    if cache_runs.is_dir():
        import shutil

        for path in cache_runs.iterdir():
            if path.is_dir() and path.stat().st_mtime < time.time() - CACHE_DAYS * 86400:
                shutil.rmtree(path, ignore_errors=True)


def run(site: str) -> int:
    schedule = common.load_schedule()
    run_id = common.stamp() + ("-test" if common.dry_run() else "")
    if not (common.state_dir() / "scan-settings.json").is_file():
        monitor.run(None, t("scan.no_whitelist"))
        return 1
    common.log(f"scan {run_id} site={site} dry_run={common.dry_run()}")
    pre = prefilter.run(run_id, site)
    common.log(f"prefilter: {json.dumps(pre, ensure_ascii=False)}")
    if pre["to_score"] and rule_scorer.enabled(schedule):
        out = rule_scorer.run(run_id)
        common.log("scoring: rules (no AI)")
        summary = postprocess.run(run_id, common.Path(out), 0, False)
    elif pre["to_score"]:
        code, out = call_claude(run_id, schedule)
        common.log(f"claude exit {code}")
        summary = postprocess.run(run_id, common.Path(out), code, False)
    else:
        summary = postprocess.run(run_id, None, None, True)
    common.log("summary: " + json.dumps({k: summary[k] for k in ("status", "seen", "new", "scored", "alerted",
                                                                  "total_cost_usd")}, ensure_ascii=False))
    monitor.run(summary)
    rotate()
    return 0 if summary["status"] == "ok" else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--site", default="all", choices=["all", *prefilter.PORTALS, "companies"])
    args = ap.parse_args(argv)
    try:
        with common.scan_lock():
            try:
                return run(args.site)
            except Exception as exc:  # noqa: BLE001 - any crash must reach Telegram
                common.log(traceback.format_exc())
                monitor.run(None, f"{type(exc).__name__}: {exc}")
                return 1
    except common.LockBusy:
        common.log("another scan is running — exiting")
        return 3


if __name__ == "__main__":
    sys.exit(main())
