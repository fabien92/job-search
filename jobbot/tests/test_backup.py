import os
import subprocess
from unittest import mock

from _env import JobbotTestCase
import backup


class Backup(JobbotTestCase):
    def setUp(self):
        super().setUp()
        self.remote = self.tmp / "remote.git"
        self.clone = self.tmp / "jobbot-data"
        subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(self.remote)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.remote), str(self.clone)], check=True, capture_output=True)
        os.environ["JOBBOT_BACKUP_DIR"] = str(self.clone)
        self.addCleanup(os.environ.pop, "JOBBOT_BACKUP_DIR", None)
        state = self.tmp / "state"
        (state / "runs").mkdir(parents=True)
        (state / "seen_index.json").write_text("{}")
        (state / ".lock").write_text("1")
        for name in (".scan.lock", ".telegram.lock", ".discover.lock", ".go-123.lock", ".go-T7.lock"):
            (state / name).write_text("1")
        (self.tmp / "tracker.csv").write_text("company,role\n")
        # backup.sources() takes documents/ and job_scraper/ from the real repository: point them at the
        # temp dir, so the test neither copies personal files nor changes result when they change.
        (self.tmp / "documents" / "applications").mkdir(parents=True)
        (self.tmp / "documents" / "applications" / "note.txt").write_text("x")
        patcher = mock.patch.object(backup, "sources", return_value=[
            (self.tmp / "job_scraper", "job_scraper"), (self.tmp / "tracker.csv", "job_search_tracker.csv"),
            (self.tmp / "documents", "documents"), (state, "jobbot-state")])
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_commit_push_and_idempotent(self):
        self.assertTrue(backup.run().startswith("committed and pushed"))
        self.assertTrue((self.clone / "jobbot-state" / "seen_index.json").is_file())
        self.assertFalse((self.clone / "jobbot-state" / ".lock").exists())
        self.assertEqual(sorted(p.name for p in (self.clone / "jobbot-state").glob("*.lock")), [], "no lock file backed up")
        self.assertTrue((self.clone / "job_search_tracker.csv").is_file())
        log = subprocess.run(["git", "--git-dir", str(self.remote), "log", "--oneline", "main"], capture_output=True, text=True)
        self.assertIn("backup", log.stdout)
        self.assertEqual(backup.run(), "no change")

    def test_dry_run(self):
        os.environ["JOBBOT_DRY_RUN"] = "1"
        self.assertTrue(backup.run().startswith("dry-run"))
        self.assertFalse((self.clone / "jobbot-state").exists())


class Launchd(JobbotTestCase):
    def test_plists(self):
        import plistlib
        import gen_launchd

        # home and group given: the test must not depend on a local "jobbot" account
        plists = gen_launchd.build("jobbot", gen_launchd.common.ROOT, gen_launchd.common.load_schedule(),
                                   home="/Users/jobbot", group="staff")
        self.assertEqual(set(plists), {"com.jobbot.telegram", "com.jobbot.scan", "com.jobbot.backup", "com.jobbot.daily",
                                       "com.jobbot.weekly", "com.jobbot.spont"})
        for p in plists.values():
            self.assertEqual(p["UserName"], "jobbot")
            self.assertEqual(p["ProgramArguments"][0], "/bin/bash")
            self.assertIn("/Library/TeX/texbin", p["EnvironmentVariables"]["PATH"])
            plistlib.dumps(p)
        self.assertTrue(plists["com.jobbot.telegram"]["KeepAlive"])
        self.assertEqual(plists["com.jobbot.scan"]["StartInterval"], 4 * 3600)
        self.assertEqual(plists["com.jobbot.backup"]["StartCalendarInterval"], {"Hour": 2, "Minute": 30})
        self.assertEqual(plists["com.jobbot.daily"]["StartCalendarInterval"], {"Hour": 8, "Minute": 0})

    def test_home_and_group_come_from_the_account(self):
        import grp
        import os
        import pwd
        from pathlib import Path

        import gen_launchd

        me = pwd.getpwuid(os.getuid())
        self.assertEqual(gen_launchd.current_user(), me.pw_name)
        repo = Path("/somewhere/else/ai-job-search")
        for p in gen_launchd.build(me.pw_name, repo, gen_launchd.common.load_schedule()).values():
            self.assertEqual(p["UserName"], me.pw_name)
            self.assertEqual(p["GroupName"], grp.getgrgid(me.pw_gid).gr_name)
            env = p["EnvironmentVariables"]
            self.assertEqual(env["HOME"], me.pw_dir, "home from the user database, not /Users/<name>")
            self.assertTrue(env["PATH"].startswith(f"{me.pw_dir}/.local/bin:"))
            self.assertTrue(p["ProgramArguments"][1].startswith(str(repo / "jobbot" / "scripts")))
        with self.assertRaises(ValueError):
            gen_launchd.build("no-such-user-jobbot-test", repo, gen_launchd.common.load_schedule())

    def test_tracked_plists_are_the_documented_example(self):
        import plistlib
        from pathlib import Path

        import gen_launchd

        tracked = Path(gen_launchd.__file__).resolve().parents[1] / "launchd"
        for path in sorted(tracked.glob("com.jobbot.*.plist")):
            p = plistlib.loads(path.read_bytes())
            self.assertEqual((p["UserName"], p["EnvironmentVariables"]["HOME"]), ("jobbot", "/Users/jobbot"), path.name)
            self.assertEqual(p["WorkingDirectory"], "/Users/jobbot/ai-job-search", path.name)
