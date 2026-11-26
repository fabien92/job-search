import json
import os
import subprocess
from collections import namedtuple
from pathlib import Path

from _env import FakeTelegram, JobbotTestCase, apply_settings_glob_patch
import common
import gen_settings
import preflight
import sites

HERE = Path(__file__).resolve().parent
RUN_SCAN = HERE.parent / "scripts" / "run_scan.sh"
Usage = namedtuple("Usage", "total used free")


class Base(JobbotTestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeTelegram()
        self.addCleanup(self.fake.close)
        apply_settings_glob_patch(self.config)
        os.environ.update({"JOBBOT_TELEGRAM_API": self.fake.url, "JOBBOT_BUN": str(HERE / "fake_bun.py"),
                           "JOBBOT_NOW": "2026-11-24T08:00:00Z"})
        self.secrets({"TELEGRAM_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "42", "CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-x",
                      "CLAUDE_CODE_OAUTH_TOKEN_CREATED": "2026-06-01"})
        sites.save({"allowed": [{"domain": "karriere.at"}], "denied": [], "pending": []})
        gen_settings.main([])

    def secrets(self, values: dict, mode=0o600):
        path = self.tmp / "secrets.env"
        path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
        os.chmod(path, mode)

    def check(self, name):
        return next(c for c in preflight.run_checks()["checks"] if c["name"] == name)


class Checks(Base):
    def test_all_green(self):
        report = preflight.run_checks()
        self.assertEqual({c["name"]: c["status"] for c in report["checks"]},
                         {"secrets": "ok", "telegram": "ok", "bun": "ok", "lualatex": "ok", "venv": "ok", "disk": "ok",
                          "whitelist": "ok", "sandbox": "ok", "claude_token": "ok"}, report)
        self.assertEqual(report["status"], "ok")
        self.assertTrue((self.tmp / "state" / "preflight.json").is_file())

    def test_secrets(self):
        self.secrets({"TELEGRAM_TOKEN": "x", "TELEGRAM_CHAT_ID": "42"})
        self.assertEqual(self.check("secrets")["status"], "fail")
        self.secrets({"TELEGRAM_TOKEN": "x", "TELEGRAM_CHAT_ID": "me", "CLAUDE_CODE_OAUTH_TOKEN": "y"})
        self.assertIn("numérique", self.check("secrets")["detail"])
        self.secrets({"TELEGRAM_TOKEN": "x", "TELEGRAM_CHAT_ID": "1", "CLAUDE_CODE_OAUTH_TOKEN": "y"}, mode=0o644)
        self.assertEqual(self.check("secrets")["status"], "warn")

    def test_telegram(self):
        self.fake.statuses = [401]
        self.assertEqual(self.check("telegram")["status"], "fail")
        os.environ["JOBBOT_TELEGRAM_API"] = self.fake.down_url
        c = self.check("telegram")
        self.assertEqual(c["status"], "warn")
        self.assertIn("file", c["detail"])

    def test_tools(self):
        os.environ["JOBBOT_BUN"] = "/nonexistent/bun"
        self.assertEqual(self.check("bun")["status"], "fail")
        os.environ["JOBBOT_LUALATEX"] = "/nonexistent/lualatex"
        c = self.check("lualatex")
        self.assertEqual(c["status"], "fail")
        self.assertIn("introuvable", c["detail"])

    def test_disk(self):
        gb = 1024 ** 3
        self.assertEqual(preflight.check_disk(2, usage=lambda p: Usage(100 * gb, 99 * gb, int(1 * gb)))["status"], "fail")
        self.assertEqual(preflight.check_disk(2, usage=lambda p: Usage(100 * gb, 97 * gb, int(3 * gb)))["status"], "warn")
        self.assertEqual(preflight.check_disk(2, usage=lambda p: Usage(100 * gb, 50 * gb, 50 * gb))["status"], "ok")

    def test_whitelist_and_stale_sandbox(self):
        sites.save({"allowed": [{"domain": "karriere.at"}, {"domain": "new.at"}], "denied": [], "pending": []})
        c = self.check("sandbox")
        self.assertEqual(c["status"], "fail")
        self.assertIn("périmés", c["detail"])
        gen_settings.main([])
        self.assertEqual(self.check("sandbox")["status"], "ok")
        (self.config / "sites.yaml").unlink()
        self.assertEqual(self.check("whitelist")["status"], "fail")

    def test_sandbox_flags_and_protection(self):
        path = self.tmp / "settings.local.json"
        data = json.loads(path.read_text())
        data["sandbox"]["allowUnsandboxedCommands"] = True
        data["permissions"]["deny"].remove("Edit(/jobbot/config/sites.yaml)")
        path.write_text(json.dumps(data))
        c = self.check("sandbox")
        self.assertEqual(c["status"], "fail")
        self.assertIn("drapeaux", c["detail"])
        self.assertIn("sites.yaml", c["detail"])
        (self.tmp / "state" / "scan-settings.json").unlink()
        self.assertIn("scan-settings.json absent", self.check("sandbox")["detail"])

    def test_claude_token_expiry(self):
        base = {"TELEGRAM_TOKEN": "1:a", "TELEGRAM_CHAT_ID": "1", "CLAUDE_CODE_OAUTH_TOKEN": "x"}
        for created, status in (("2026-06-01", "ok"), ("2025-12-10", "warn"), ("2025-11-01", "fail"),
                                ("[AAAA-MM-JJ]", "warn"), (None, "warn")):
            values = dict(base)
            if created:
                values["CLAUDE_CODE_OAUTH_TOKEN_CREATED"] = created
            self.secrets(values)
            self.assertEqual(self.check("claude_token")["status"], status, created)


class Alerts(Base):
    def test_scan_failure_alerts_once_then_recovers(self):
        (self.config / "sites.yaml").unlink()
        self.assertEqual(preflight.main(["--for", "scan"]), 4)
        self.assertEqual(preflight.main(["--for", "scan"]), 4)
        texts = self.fake.texts()
        self.assertEqual(len([t for t in texts if "Passage annulé" in t]), 1, texts)
        self.assertIn("whitelist", texts[0])
        sites.save({"allowed": [{"domain": "karriere.at"}], "denied": [], "pending": []})
        self.assertEqual(preflight.main(["--for", "scan"]), 0)
        self.assertTrue(any("de nouveau au vert" in t for t in self.fake.texts()))

    def test_token_expiry_warning_is_sent_once(self):
        self.secrets({"TELEGRAM_TOKEN": "1:a", "TELEGRAM_CHAT_ID": "1", "CLAUDE_CODE_OAUTH_TOKEN": "x",
                      "CLAUDE_CODE_OAUTH_TOKEN_CREATED": "2025-12-10"})
        self.assertEqual(preflight.main(["--for", "scan"]), 0)
        preflight.main(["--for", "scan"])
        self.assertEqual(len([t for t in self.fake.texts() if "Jeton Claude" in t]), 1)

    def test_health_purpose_sends_nothing(self):
        (self.config / "sites.yaml").unlink()
        self.assertEqual(preflight.main(["--for", "health"]), 4)
        self.assertEqual(self.fake.texts(), [])


class RunScanStops(Base):
    def test_failed_preflight_stops_before_any_portal_or_claude_call(self):
        portals = self.tmp / "portals"
        portals.mkdir()
        (self.config / "sites.yaml").unlink()
        env = {**os.environ, "JOBBOT_FAKE_PORTALS": str(portals), "JOBBOT_CLAUDE_BIN": str(HERE / "fake_claude.py")}
        proc = subprocess.run(["bash", str(RUN_SCAN)], env=env, capture_output=True, text=True, timeout=180)
        self.assertEqual(proc.returncode, 4, proc.stdout)
        self.assertIn("pre-flight check failed", proc.stdout)
        self.assertFalse((portals / "calls.log").exists(), "no portal was queried")
        self.assertFalse((self.tmp / "state" / "runs" / "fake-claude-argv.json").exists(), "Claude was not called")
        self.assertTrue(any("Passage annulé" in t for t in self.fake.texts()))
