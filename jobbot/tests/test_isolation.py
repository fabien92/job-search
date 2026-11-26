"""The suite runs code that writes the whitelist and the sandbox settings (gen_settings.main,
import_seed.main, sites.save). These tests prove the guard in _env.JobbotTestCase stops a test
whose JOBBOT_* paths would reach the real repository, cache, secrets or backup clone."""
import os

from _env import REPO_ROOT, JobbotTestCase, assert_isolated, redirected_paths


class Isolation(JobbotTestCase):
    def test_every_path_is_in_the_temp_dir(self):
        for label, path in redirected_paths().items():
            self.assertTrue(str(path.resolve()).startswith(str(self.tmp.resolve())), f"{label}: {path}")

    def test_guard_rejects_real_locations(self):
        cases = {
            "JOBBOT_SETTINGS_LOCAL": str(REPO_ROOT / ".claude" / "settings.local.json"),
            "JOBBOT_CONFIG_DIR": str(REPO_ROOT / "jobbot" / "config"),
            "JOBBOT_STATE_DIR": str(REPO_ROOT / "jobbot" / "state"),
            "JOBBOT_UPSTREAM_SEEN": str(REPO_ROOT / "job_scraper" / "seen_jobs.json"),
            "JOBBOT_SECRETS": os.path.expanduser("~/.config/jobbot/secrets.env"),
            "JOBBOT_BACKUP_DIR": os.path.expanduser("~/jobbot-data"),
        }
        for key, real in cases.items():
            with self.subTest(key=key):
                saved = os.environ[key]
                os.environ[key] = real
                try:
                    with self.assertRaises(AssertionError):
                        assert_isolated(self.tmp)
                finally:
                    os.environ[key] = saved

    def test_guard_rejects_an_unset_override(self):
        saved = os.environ.pop("JOBBOT_SETTINGS_LOCAL")
        try:
            with self.assertRaises(AssertionError):  # default = the real .claude/settings.local.json
                assert_isolated(self.tmp)
        finally:
            os.environ["JOBBOT_SETTINGS_LOCAL"] = saved
