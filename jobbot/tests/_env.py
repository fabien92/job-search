"""Test isolation: every JobBot path points into a temp dir; network is never used."""
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
BOT = Path(__file__).resolve().parents[1] / "bot"
REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"
for p in (SCRIPTS, BOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

ENV_KEYS = ("JOBBOT_CONFIG_DIR", "JOBBOT_STATE_DIR", "JOBBOT_CACHE_DIR", "JOBBOT_SECRETS", "JOBBOT_SETTINGS_LOCAL",
            "JOBBOT_UPSTREAM_SEEN", "JOBBOT_TRACKER", "JOBBOT_DRY_RUN", "JOBBOT_NOW", "JOBBOT_TELEGRAM_API",
            "JOBBOT_TELEGRAM_RETRY_DELAY", "JOBBOT_BUN", "JOBBOT_LUALATEX", "JOBBOT_BACKUP_DIR",
            "JOBBOT_CV_DIR", "JOBBOT_APPLICATIONS_DIR", "JOBBOT_XELATEX", "JOBBOT_CLAUDE_BIN",
            "JOBBOT_NO_NETWORK", "JOBBOT_SPONTANEOUS_DIR", "JOBBOT_PRIVATE_DIR", "JOBBOT_LANG",
            "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_USER_ID", "CLAUDE_CODE_OAUTH_TOKEN")

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_PLACES = [REPO_ROOT, Path.home() / "Library" / "Caches" / "jobbot", Path.home() / ".config" / "jobbot",
               Path.home() / "jobbot-data"]


def _inside(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def redirected_paths() -> dict:
    """Every path JobBot code writes to or reads secrets from, as the code itself resolves it."""
    import common

    return {
        "config_dir (sites.yaml, regions.yaml, rejection-rules.md)": common.config_dir(),
        "state_dir (ledger, scan-settings.json, queue, alerts)": common.state_dir(),
        "cache_dir (cleaned postings)": common.cache_dir(),
        "secrets_path": common.secrets_path(),
        "settings_local_path (.claude/settings.local.json)": common.settings_local_path(),
        "upstream_seen_path (job_scraper/seen_jobs.json)": common.upstream_seen_path(),
        "tracker_path (job_search_tracker.csv)": common.tracker_path(),
        "cv_dir (documents/cv/jobbot)": common.cv_dir(),
        "applications_dir (documents/applications)": common.applications_dir(),
        "spontaneous_dir (documents/spontaneous)": common.spontaneous_dir(),
        "backup dir (~/jobbot-data)": Path(os.environ.get("JOBBOT_BACKUP_DIR", str(Path.home() / "jobbot-data"))),
    }


def assert_isolated(tmp: Path) -> None:
    """Fail the test before it runs if any JOBBOT_* path resolves into the real repository, the real
    cache, the real secrets or the real backup clone (the whitelist generators write through these)."""
    for label, path in redirected_paths().items():
        for real in REAL_PLACES:
            if _inside(path, real):
                raise AssertionError(f"test isolation broken: {label} -> {path} is inside {real}")
        if not _inside(path, tmp):
            raise AssertionError(f"test isolation broken: {label} -> {path} is outside the test temp dir {tmp}")


class JobbotTestCase(unittest.TestCase):
    """Copies the real config into a temp dir and redirects state/cache/secrets there."""

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV_KEYS}
        self.tmp = Path(tempfile.mkdtemp(prefix="jobbot-test-"))
        self.config = self.tmp / "config"
        shutil.copytree(REPO_CONFIG, self.config)
        # Start from an empty whitelist: the real sites.yaml (the user's import) must not leak into tests.
        (self.config / "sites.yaml").unlink(missing_ok=True)
        os.environ.update({
            "JOBBOT_CONFIG_DIR": str(self.config),
            "JOBBOT_STATE_DIR": str(self.tmp / "state"),
            "JOBBOT_CACHE_DIR": str(self.tmp / "cache"),
            "JOBBOT_SECRETS": str(self.tmp / "secrets.env"),
            "JOBBOT_SETTINGS_LOCAL": str(self.tmp / "settings.local.json"),
            "JOBBOT_UPSTREAM_SEEN": str(self.tmp / "seen_jobs.json"),
            "JOBBOT_TRACKER": str(self.tmp / "tracker.csv"),
            "JOBBOT_TELEGRAM_API": "file://" + str(self.tmp / "telegram-unreachable"),  # no socket, never created
            "JOBBOT_TELEGRAM_RETRY_DELAY": "0",
            "JOBBOT_BACKUP_DIR": str(self.tmp / "no-backup-dir"),
            "JOBBOT_CV_DIR": str(self.tmp / "cv"),
            "JOBBOT_APPLICATIONS_DIR": str(self.tmp / "applications"),
            "JOBBOT_SPONTANEOUS_DIR": str(self.tmp / "spontaneous"),
            "JOBBOT_PRIVATE_DIR": str(self.tmp / "private"),  # never the real identity/profile
            "JOBBOT_NO_NETWORK": "1",  # ats/web.py: the real transport refuses to open a connection
            "JOBBOT_LANG": "fr",  # the existing tests check the French texts; test_i18n.py covers English
        })
        for k in ("JOBBOT_DRY_RUN", "JOBBOT_NOW", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID", "TELEGRAM_USER_ID",
                  "CLAUDE_CODE_OAUTH_TOKEN"):
            os.environ.pop(k, None)
        assert_isolated(self.tmp)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)


class FakeTelegram:
    """Stand-in for api.telegram.org WITHOUT a socket (the Claude Code sandbox forbids binding a
    local port). Uses telegram_send's test-only file:// transport: requests land in
    <dir>/requests.jsonl, reply statuses are popped from <dir>/statuses.json (default 200,
    0 = network error). Works across processes (run_scan.sh subprocesses inherit the URL)."""

    def __init__(self):
        import json as _json

        self._json = _json
        self.dir = Path(tempfile.mkdtemp(prefix="jobbot-fake-telegram-"))
        self.url = "file://" + str(self.dir)
        self.down_url = "file://" + str(self.dir / "unreachable")  # never created

    @property
    def statuses(self):
        path = self.dir / "statuses.json"
        return self._json.loads(path.read_text()) if path.exists() else []

    @statuses.setter
    def statuses(self, values):
        (self.dir / "statuses.json").write_text(self._json.dumps(list(values)))

    @property
    def calls(self):
        path = self.dir / "requests.jsonl"
        if not path.exists():
            return []
        return [(r["method"], r["payload"]) for r in map(self._json.loads, path.read_text(encoding="utf-8").splitlines())]

    def texts(self):
        return [p.get("text", "") for m, p in self.calls if m == "sendMessage"]

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


def apply_settings_glob_patch(config_dir):
    """Test config = copy of the repo config. Until the user applies the reviewed template patch
    (scratchpad settings.local.template.proposed.json), add the .claude/settings*.json protection
    here so the generated settings match what preflight requires."""
    import json as _json

    path = config_dir / "settings.local.template.json"
    tpl = _json.loads(path.read_text(encoding="utf-8"))
    glob = ".claude/settings*.json"
    if glob not in tpl["protectedPaths"]:
        tpl["protectedPaths"].append(glob)
    path.write_text(_json.dumps(tpl, ensure_ascii=False, indent=2), encoding="utf-8")
