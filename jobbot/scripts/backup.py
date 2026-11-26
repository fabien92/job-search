#!/usr/bin/env python3
"""Nightly backup (SPEC §11): rsync personal data to ~/jobbot-data, commit, push to its existing remote.

    jobbot/.venv/bin/python jobbot/scripts/backup.py        (launchd com.jobbot.backup via backup.sh)

Copied (under the state lock, so no writer is mid-file):
  job_scraper/            -> ~/jobbot-data/job_scraper/
  job_search_tracker.csv  -> ~/jobbot-data/job_search_tracker.csv
  documents/              -> ~/jobbot-data/documents/
  jobbot/state/           -> ~/jobbot-data/jobbot-state/   (locks excluded)
The upstream .gitignore is not touched. JOBBOT_DRY_RUN=1: rsync --dry-run, no commit, no push.
A failure sends a Telegram alert.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import common
import telegram_send as tg
from i18n import t

# Every lock file: .lock, .scan.lock, .telegram.lock, .discover.lock, .go-<ID>.lock...
EXCLUDES = ["*.lock", "*.tmp", ".DS_Store", "__pycache__/"]


def dest() -> Path:
    return Path(os.environ.get("JOBBOT_BACKUP_DIR", str(Path.home() / "jobbot-data"))).expanduser()


def sources() -> list[tuple[Path, str]]:
    root = common.ROOT
    return [
        (root / "job_scraper", "job_scraper"),
        (common.tracker_path(), "job_search_tracker.csv"),
        (root / "documents", "documents"),
        (common.state_dir(), "jobbot-state"),
    ]


def sh(argv: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, timeout=600)


def run() -> str:
    target = dest()
    is_repo = (target / ".git").is_dir()
    dry = common.dry_run()
    if not is_repo and not dry:
        target.mkdir(parents=True, exist_ok=True)  # plain local copy: no git, nothing leaves the Mac
    with common.state_lock(timeout=600):
        for src, name in sources():
            if not src.exists():
                continue
            argv = ["rsync", "-a", "--delete", *[f"--exclude={e}" for e in EXCLUDES]]
            if dry:
                argv.append("--dry-run")
            if src.is_dir():
                argv += [f"{src}/", f"{target / name}/"]
            else:
                argv += [str(src), str(target / name)]
            proc = sh(argv)
            if proc.returncode != 0:
                raise RuntimeError(f"rsync {name}: {proc.stderr.strip()[-300:]}")
    if dry:
        return "dry-run: rsync simulated, no commit"
    if not is_repo:
        return f"copied to {target} (not a git repository: nothing committed or pushed)"
    sh(["git", "add", "-A"], cwd=target)
    if sh(["git", "diff", "--cached", "--quiet"], cwd=target).returncode == 0:
        return "no change"
    msg = f"backup {common.local_now().strftime('%Y-%m-%d %H:%M')}"
    proc = sh(["git", "-c", "user.name=jobbot", "-c", "user.email=jobbot@localhost", "commit", "-q", "-m", msg], cwd=target)
    if proc.returncode != 0:
        raise RuntimeError(f"git commit: {proc.stderr.strip()[-300:]}")
    if "origin" not in sh(["git", "remote"], cwd=target).stdout.split():
        return f"committed (no remote: nothing pushed): {msg}"
    branch = sh(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=target).stdout.strip() or "main"
    proc = sh(["git", "push", "-q", "origin", f"HEAD:{branch}"], cwd=target)
    if proc.returncode != 0:
        raise RuntimeError(f"git push: {proc.stderr.strip()[-300:]}")
    return f"committed and pushed: {msg}"


def main() -> int:
    try:
        result = run()
    except Exception as exc:  # noqa: BLE001
        common.log(f"backup failed: {exc}")
        tg.send(t("backup.failed", error=tg.esc(exc)))
        return 1
    common.log(f"backup: {result}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
