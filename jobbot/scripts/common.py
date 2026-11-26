"""Shared plumbing for the JobBot scripts: paths, locks, config, atomic writes.

Every path can be redirected by an environment variable so the tests (and the
dry-run mode) never touch the real state:

  JOBBOT_CONFIG_DIR   default jobbot/config
  JOBBOT_PRIVATE_DIR  default private/   (gitignored identity and profile; see candidate())
  JOBBOT_STATE_DIR    default jobbot/state
  JOBBOT_CACHE_DIR    default ~/Library/Caches/jobbot   (cleaned postings: outside the repo,
                                                         posting_guard.py refuses --out inside it)
  JOBBOT_SECRETS      default ~/.config/jobbot/secrets.env
  JOBBOT_SETTINGS_LOCAL default .claude/settings.local.json
  JOBBOT_UPSTREAM_SEEN  default job_scraper/seen_jobs.json
  JOBBOT_TRACKER        default job_search_tracker.csv
  JOBBOT_CV_DIR         default documents/cv/jobbot          (block CV, variants)
  JOBBOT_APPLICATIONS_DIR default documents/applications     (one folder per /go)
  JOBBOT_DRY_RUN=1    test mode (SPEC §12)
"""

from __future__ import annotations

import contextlib
import datetime as dt
import errno
import fcntl
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
JOBBOT = ROOT / "jobbot"
TOOLS = ROOT / "tools"


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def config_dir() -> Path:
    return _env_path("JOBBOT_CONFIG_DIR", JOBBOT / "config")


def private_dir() -> Path:
    """Gitignored personal data (identity, profile). The tracked counterparts are fictional examples."""
    return _env_path("JOBBOT_PRIVATE_DIR", ROOT / "private")


SKILL_DIR = ROOT / ".claude" / "skills" / "job-application-assistant"


def profile_file(name: str = "01-candidate-profile.md") -> Path:
    """Candidate profile file: private/skills/job-application-assistant/<name>, else the template."""
    private = private_dir() / "skills" / "job-application-assistant" / name
    return private if private.is_file() else SKILL_DIR / name


def candidate() -> dict:
    """Identity for the scripts (email, phone): private/candidate.yaml, else the fictional example."""
    data = load_yaml(private_dir() / "candidate.yaml", None)
    if not isinstance(data, dict):
        data = load_yaml(config_dir() / "candidate.example.yaml", {}) or {}
    return data


def state_dir() -> Path:
    path = _env_path("JOBBOT_STATE_DIR", JOBBOT / "state")
    path.mkdir(parents=True, exist_ok=True)
    return path


def runs_dir() -> Path:
    path = state_dir() / "runs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = _env_path("JOBBOT_CACHE_DIR", Path.home() / "Library" / "Caches" / "jobbot")
    path.mkdir(parents=True, exist_ok=True)
    return path


def secrets_path() -> Path:
    return _env_path("JOBBOT_SECRETS", Path.home() / ".config" / "jobbot" / "secrets.env")


def settings_local_path() -> Path:
    return _env_path("JOBBOT_SETTINGS_LOCAL", ROOT / ".claude" / "settings.local.json")


def upstream_seen_path() -> Path:
    return _env_path("JOBBOT_UPSTREAM_SEEN", ROOT / "job_scraper" / "seen_jobs.json")


def tracker_path() -> Path:
    return _env_path("JOBBOT_TRACKER", ROOT / "job_search_tracker.csv")


def cv_dir() -> Path:
    return _env_path("JOBBOT_CV_DIR", ROOT / "documents" / "cv" / "jobbot")


def applications_dir() -> Path:
    return _env_path("JOBBOT_APPLICATIONS_DIR", ROOT / "documents" / "applications")


def spontaneous_dir() -> Path:
    """V3 spontaneous applications: documents/spontaneous/<company>/ (email.txt, linkedin.txt, CV)."""
    return _env_path("JOBBOT_SPONTANEOUS_DIR", ROOT / "documents" / "spontaneous")


def dry_run() -> bool:
    return os.environ.get("JOBBOT_DRY_RUN") == "1"


# ------------------------------------------------------------------ time

def tz() -> ZoneInfo:
    return ZoneInfo(load_schedule().get("timezone") or "Europe/Vienna")


def now() -> dt.datetime:
    """Aware current time; JOBBOT_NOW (ISO) overrides it for tests."""
    forced = os.environ.get("JOBBOT_NOW")
    if forced:
        value = dt.datetime.fromisoformat(forced.replace("Z", "+00:00"))
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    return dt.datetime.now(dt.timezone.utc)


def local_now() -> dt.datetime:
    return now().astimezone(tz())


def stamp() -> str:
    """Run identifier: local time, filesystem-safe and sortable."""
    return local_now().strftime("%Y%m%dT%H%M%S")


def iso(value: dt.datetime | None = None) -> str:
    return (value or now()).astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


# ------------------------------------------------------------------ locks

class LockBusy(RuntimeError):
    pass


@contextlib.contextmanager
def file_lock(path: Path, *, timeout: float = 60.0, blocking: bool = True):
    """Exclusive fcntl lock. blocking=False raises LockBusy at once if held."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+")
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in (errno.EAGAIN, errno.EACCES):
                    raise
                if not blocking or time.monotonic() >= deadline:
                    raise LockBusy(str(path)) from None
                time.sleep(0.1)
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fh, fcntl.LOCK_UN)
        fh.close()


def state_lock(timeout: float = 60.0):
    """SPEC §0.8 / §11: every state write goes through jobbot/state/.lock."""
    return file_lock(state_dir() / ".lock", timeout=timeout)


def scan_lock():
    """One scan at a time. Waits a moment only: a second scan is refused, but a probe (lock_held, used
    by /status and /search) holding the file for an instant must never make a starting scan give up."""
    return file_lock(state_dir() / ".scan.lock", timeout=3.0)


def lock_held(path: Path) -> bool:
    """Is this lock taken by another process? Read-only probe: a shared, non-blocking attempt released
    at once, which never writes the PID file."""
    try:
        fh = open(path, "a+")
    except OSError:
        return False
    try:
        try:
            fcntl.flock(fh, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EACCES):
                return True
            raise
        fcntl.flock(fh, fcntl.LOCK_UN)
        return False
    finally:
        fh.close()


def scan_running() -> bool:
    return lock_held(state_dir() / ".scan.lock")


# ------------------------------------------------------------------ files

def atomic_write_text(path: Path, text: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())  # a power cut must leave the old file or the new one, never an empty one
        if mode is not None:
            os.chmod(tmp, mode)
        elif path.exists():
            os.chmod(tmp, path.stat().st_mode & 0o777)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def atomic_write_json(path: Path, data, mode: int | None = None) -> None:
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n", mode)


class CorruptState(ValueError):
    """A state file that cannot be parsed. `path` lets the bot name the file in its reply."""

    def __init__(self, path: Path, detail: str):
        super().__init__(f"{path} is not valid JSON: {detail}")
        self.path = Path(path)


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise CorruptState(path, str(exc)) from exc


# ------------------------------------------------------------------ CSV cells

_CSV_RISKY = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value) -> str:
    """Neutralise a cell a spreadsheet would run as a formula (posting titles, company and contact
    names are untrusted): a leading = + - @ tab or CR gets an apostrophe in front. csv_plain undoes it."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_CSV_RISKY) else text


def csv_plain(value):
    """The original cell: drops the apostrophe csv_safe added, so matching on the value still works."""
    if isinstance(value, str) and len(value) > 1 and value[0] == "'" and value[1:].startswith(_CSV_RISKY):
        return value[1:]
    return value


# ------------------------------------------------------------------ config

def _yaml():
    try:
        import yaml  # type: ignore
    except ImportError:  # pragma: no cover - venv missing
        sys.exit("PyYAML missing: run jobbot/scripts/setup_venv.sh and use jobbot/.venv/bin/python")
    return yaml


def load_yaml(path: Path, default=None):
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    data = _yaml().safe_load(text)
    return default if data is None else data


def dump_yaml(data) -> str:
    return _yaml().safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False)


SCHEDULE_DEFAULTS = {
    "timezone": "Europe/Vienna",
    "scoring": "claude",        # claude | rules (rule_scorer.py: keyword score, no AI)
    "default_variant": "delivery",
    "scan_every_hours": 4,
    "linkedin_runs_per_day": 3,
    "freshness_hours": 48,
    "alert_threshold": 60,
    "max_scored_per_run": 40,
    "max_budget_usd_per_run": 2.0,
    "scan_model": "sonnet",
    "go_model": "sonnet",
    "max_budget_usd_per_go": 1.0,
    "queries_per_run": {"karriere": 40, "linkedin": 8, "derstandard": 12, "uncareers": 3, "unido": 3, "osce": 1, "opecfund": 1, "hays": 1, "jobgether": 21, "randstad": 1, "profession": 1, "kariera": 1, "michaelpage": 1},
    "daily_recap": "08:00",
    "weekly_report": {"day": "sunday", "time": "18:00"},
    "backup": "02:30",
    "pending_reminder_hours": 24,
    "zero_results_alert_days": 3,
    "min_free_disk_gb": 2,
    "token_warning_days": 30,
    # V3 (SPEC §10)
    "companies_every_hours": 24,
    "osce_every_hours": 24,
    "companies_per_run": 30,
    "companies_detect_per_run": 10,
    "companies_max_age_days": 30,
    "discover_model": "sonnet",
    "max_budget_usd_per_discover": 1.5,
    "spont_model": "sonnet",
    "max_budget_usd_per_spont": 1.0,
    "spont_list": "20:00",
    "spont_list_size": 5,
    "spont_list_repeat_days": 14,
    # V5 (SPEC §8): follow-up reminders, the /outcome follow-up branch defaults
    "followup_days": 10,
    "followup_max": 2,
}


def load_schedule() -> dict:
    data = load_yaml(config_dir() / "schedule.yaml", {}) or {}
    merged = {**SCHEDULE_DEFAULTS, **data}
    merged["queries_per_run"] = {**SCHEDULE_DEFAULTS["queries_per_run"], **(data.get("queries_per_run") or {})}
    return merged


def load_regions() -> dict:
    data = load_yaml(config_dir() / "regions.yaml", {}) or {}
    regions = data.get("regions") or {}
    return {"remote_worldwide": bool(data.get("remote_worldwide")), "regions": regions}


def load_secrets() -> dict:
    """KEY=VALUE lines (optionally `export KEY=...`, quotes stripped). Environment wins."""
    values: dict[str, str] = {}
    path = secrets_path()
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[len("export "):]
            key, _, value = line.partition("=")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    for key in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_USER_ID", "CLAUDE_CODE_OAUTH_TOKEN"):
        if os.environ.get(key):
            values[key] = os.environ[key]
    return values


def log(message: str) -> None:
    print(f"[{local_now().strftime('%Y-%m-%d %H:%M:%S')}] {message}", file=sys.stderr, flush=True)
