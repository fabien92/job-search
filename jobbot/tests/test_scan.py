import datetime as dt
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from _env import FakeTelegram, JobbotTestCase, apply_settings_glob_patch
import common
import dedup
import gen_settings
import monitor
import sites

HERE = Path(__file__).resolve().parent
RUN_SCAN = HERE.parent / "scripts" / "run_scan.sh"


class Monitor(JobbotTestCase):
    def setUp(self):
        super().setUp()
        self.tg = FakeTelegram()
        self.addCleanup(self.tg.close)
        os.environ.update({"JOBBOT_TELEGRAM_API": self.tg.url, "TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT_ID": "1",
                           "JOBBOT_NOW": "2026-11-23T10:00:00Z"})

    def ok(self, **kw):
        return {"run_id": "r", "status": "ok", "sites": {"karriere": {"queries": 2, "results": 5, "errors": 0}},
                "claude": {"status": "ok"}, **kw}

    def test_failure_transition_reminder_recovery(self):
        failed = self.ok(status="failed", claude={"failure": "auth_or_quota", "error": "Invalid API key"})
        r = monitor.run(failed)
        self.assertEqual(sorted(r["sent"]), ["claude_auth_quota", "run_failed"])
        self.assertEqual(monitor.run(failed)["sent"], [], "no repeat within 24 h")
        os.environ["JOBBOT_NOW"] = "2026-11-24T10:30:00Z"
        self.assertEqual(sorted(monitor.run(failed)["sent"]), ["claude_auth_quota", "run_failed"], "24 h reminder")
        r = monitor.run(self.ok())
        self.assertIn("run_failed", r["resolved"])
        self.assertTrue(any("rétablis" in t for t in self.tg.texts()))
        self.assertEqual(monitor.load_alerts(), {})
        health = json.loads((self.tmp / "state" / "health.json").read_text())
        self.assertEqual((health["last_status"], health["consecutive_failures"]), ("ok", 0))

    def test_zero_results_and_site_down(self):
        stats = {"karriere": {d: {"results": 0, "queries": 3} for d in ("2026-11-21", "2026-11-22", "2026-11-23")},
                 "linkedin": {"2026-11-23": {"results": 0}}}
        common.atomic_write_json(self.tmp / "state" / "site_stats.json", stats)
        r = monitor.run(self.ok(sites={"linkedin": {"queries": 0, "errors": 3, "results": 0}}))
        self.assertEqual(sorted(r["active"]), ["site_down:linkedin", "zero:karriere"])
        self.assertTrue(any("0 offre depuis 3 jours" in t for t in self.tg.texts()))

    def test_crash_does_not_clear_other_alerts(self):
        common.atomic_write_json(monitor.alerts_path(), {"zero:karriere": {"since": "x", "last_sent": common.iso(), "text": "t"}})
        monitor.run(None, "boom")
        self.assertIn("zero:karriere", monitor.load_alerts())
        self.assertIn("run_failed", monitor.load_alerts())

    def test_cap_silent_during_initial_stock(self):
        capped = self.ok(cap_reached=True, deferred=192)
        for _ in range(3):  # the backlog takes several runs to drain
            r = monitor.run(capped)
            self.assertTrue(r["initial_stock"])
            self.assertNotIn("cap_reached", r["active"])
        self.assertFalse(any("Plafond" in t for t in self.tg.texts()))
        r = monitor.run(self.ok(cap_reached=False))  # first run under the cap: stock drained
        self.assertTrue(r["initial_stock"])
        health = json.loads((self.tmp / "state" / "health.json").read_text())
        self.assertIn("initial_stock_drained", health)
        r = monitor.run(capped)
        self.assertFalse(r["initial_stock"])
        self.assertEqual(r["sent"], ["cap_reached"])
        self.assertTrue(any("192 offres reportées" in t for t in self.tg.texts()))

    def test_failed_run_does_not_end_initial_stock(self):
        monitor.run(self.ok(status="failed", cap_reached=False))
        health = json.loads((self.tmp / "state" / "health.json").read_text())
        self.assertNotIn("initial_stock_drained", health)

    def test_blocked_hosts_message(self):
        monitor.run(self.ok(new_pending_hosts=["careers.newco.at"]))
        self.assertTrue(any("careers.newco.at" in t and "/allow" in t for t in self.tg.texts()))


class EndToEnd(JobbotTestCase):
    """run_scan.sh -> scan.py -> prefilter (fake bun) -> fake claude -> postprocess -> fake Telegram. No network."""

    def setUp(self):
        super().setUp()
        self.tg = FakeTelegram()
        self.addCleanup(self.tg.close)
        self.fake = self.tmp / "portals"
        self.fake.mkdir()
        cards = [{"id": "5000001", "title": "IT Delivery Manager (m/w/d)", "company": "ACME GmbH", "location": "Wien",
                  "date": "2026-11-23", "url": "https://www.karriere.at/jobs/5000001", "salary": "ab 65.000 € jährlich"},
                 {"id": "5000002", "title": "Release Manager", "company": "Beta", "location": "Wien", "date": "2026-11-22",
                  "url": "https://www.karriere.at/jobs/5000002"},
                 {"id": "5000003", "title": "Head of IT", "company": "Gamma", "location": "Wien", "date": "2026-11-23",
                  "url": "https://www.karriere.at/jobs/5000003"}]
        (self.fake / "karriere-search-search.json").write_text(json.dumps({"meta": {}, "results": cards}))
        for c in cards[:2]:
            (self.fake / f"karriere-search-detail-{c['id']}.json").write_text(json.dumps({**c, "description": "Job text",
                                                                                         "isActive": True}))
        (self.tmp / "secrets.env").write_text("TELEGRAM_TOKEN=tok\nTELEGRAM_CHAT_ID=77\nCLAUDE_CODE_OAUTH_TOKEN=fake\n")
        os.chmod(self.tmp / "secrets.env", 0o600)
        (self.config / "schedule.yaml").write_text((self.config / "schedule.yaml").read_text()
                                                   + "queries_per_run: {karriere: 1, linkedin: 1}\n")
        sites.save({"allowed": [{"domain": "karriere.at"}], "denied": [], "pending": []})
        apply_settings_glob_patch(self.config)
        gen_settings.main([])
        self.env = {**os.environ, "JOBBOT_BUN": str(HERE / "fake_bun.py"), "JOBBOT_FAKE_PORTALS": str(self.fake),
                    "JOBBOT_CLAUDE_BIN": str(HERE / "fake_claude.py"), "JOBBOT_TELEGRAM_API": self.tg.url,
                    "JOBBOT_REQUEST_DELAY": "0", "JOBBOT_NOW": "2026-11-23T10:00:00Z"}
        for k in ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"):
            self.env.pop(k, None)

    def scan(self, **extra):
        return subprocess.run(["bash", str(RUN_SCAN), "--site", "karriere"], env={**self.env, **extra},
                              capture_output=True, text=True, timeout=120)

    def summaries(self):
        return [json.loads(p.read_text()) for p in sorted((self.tmp / "state" / "runs").glob("2*.json"))
                if "-" not in p.stem or p.stem.endswith("-test")]

    def test_dry_run_full_pass(self):
        proc = self.scan(JOBBOT_DRY_RUN="1")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr + self.log())
        texts = self.tg.texts()
        # fake scores 90 and 60 (threshold 60 inclusive): V5 shows the best one, the other waits in the test queue
        self.assertEqual(len(texts), 1, texts)
        self.assertTrue(all(t.startswith("[TEST] ") for t in texts))
        self.assertIn('href="https://www.karriere.at/jobs/5000001"', texts[0])
        self.assertIn("📥 1 autre(s) en attente", texts[0])
        queue = json.loads((self.tmp / "state" / "offer_queue-test.json").read_text())
        self.assertEqual((queue["current"]["id"], len(queue["waiting"])), ("T2", 1))
        self.assertFalse((self.tmp / "state" / "offer_queue.json").exists(), "the real queue is untouched")
        self.assertFalse((self.tmp / "seen_jobs.json").exists())
        self.assertFalse((self.tmp / "state" / "seen_index.json").exists())
        argv = json.loads((self.tmp / "state" / "runs" / "fake-claude-argv.json").read_text())
        for flag in ("--permission-mode", "dontAsk", "--permission-prompts", "none", "--output-format", "json",
                     "--max-budget-usd", "2.0", "--settings"):
            self.assertIn(flag, argv)
        self.assertIn("Bash,WebFetch,WebSearch", argv[argv.index("--disallowedTools") + 1])
        summary = [s for s in self.summaries() if s.get("dry_run")][0]
        self.assertEqual((summary["new"], summary["scored"], summary["rejected_by_reason"]), (3, 2, {"title_excluded": 1}))
        # a second dry run sees the same jobs again: nothing definitive was written
        self.assertEqual(self.scan(JOBBOT_DRY_RUN="1").returncode, 0)

    def test_rules_mode_scores_without_claude(self):
        """`scoring: rules`: no Claude token, the fake claude is never started, postings are still alerted."""
        (self.config / "schedule.yaml").write_text((self.config / "schedule.yaml").read_text() + "scoring: rules\n")
        (self.tmp / "secrets.env").write_text("TELEGRAM_TOKEN=tok\nTELEGRAM_CHAT_ID=77\n")
        os.chmod(self.tmp / "secrets.env", 0o600)
        proc = self.scan(JOBBOT_DRY_RUN="1", JOBBOT_CLAUDE_BIN="/nonexistent/claude")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr + self.log())
        self.assertFalse((self.tmp / "state" / "runs" / "fake-claude-argv.json").exists())
        summary = [s for s in self.summaries() if s.get("dry_run")][0]
        self.assertEqual((summary["status"], summary["scored"], summary["total_cost_usd"]), ("ok", 2, 0.0))
        texts = self.tg.texts()
        self.assertEqual(len(texts), 1, texts)  # both titles match a target title: the best is shown, one waits
        self.assertIn("Rules: title:", texts[0])

    def test_real_pass_then_nothing_twice(self):
        self.assertEqual(self.scan().returncode, 0, self.log())
        ledger = dedup.Ledger.load()
        self.assertEqual(len(ledger.jobs), 3)
        seen = json.loads((self.tmp / "seen_jobs.json").read_text())["seen"]
        self.assertEqual(len(seen), 3)
        first = len(self.tg.texts())
        self.assertGreaterEqual(first, 1)
        self.env["JOBBOT_NOW"] = "2026-11-23T14:00:00Z"
        self.assertEqual(self.scan().returncode, 0, self.log())
        self.assertEqual(len(self.tg.texts()), first, "an offer is never presented twice (SPEC §0.5)")
        self.assertFalse(any(p.name.endswith("-batch.json") and json.loads(p.read_text())["jobs"]
                             for p in (self.tmp / "state" / "runs").glob("*T14*-batch.json")))

    def test_claude_auth_failure_alerts(self):
        proc = self.scan(FAKE_CLAUDE_MODE="auth")
        self.assertEqual(proc.returncode, 1)
        texts = self.tg.texts()
        self.assertTrue(any("authentification ou quota" in t for t in texts), texts)
        self.assertEqual(dedup.Ledger.load().jobs.keys() - set(), {"karriere:5000003"},
                         "only the rule-rejected job is recorded; unscored ones come back")

    def test_whitelist_not_initialised(self):
        """Missing scan-settings.json is now caught by the pre-flight check (exit 4), before scan.py."""
        (self.tmp / "state" / "scan-settings.json").unlink()
        self.assertEqual(self.scan().returncode, 4)
        texts = self.tg.texts()
        self.assertTrue(any("Passage annulé" in t and "scan-settings.json absent" in t for t in texts), texts)
        self.assertFalse((self.fake / "calls.log").exists(), "no portal was queried")

    def test_scan_py_still_refuses_without_scan_settings(self):
        """Second line of defence if scan.py is started without run_scan.sh."""
        import scan

        (self.tmp / "state" / "scan-settings.json").unlink()
        os.environ.update({"JOBBOT_TELEGRAM_API": self.tg.url, "TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"})
        self.assertEqual(scan.main([]), 1)
        self.assertTrue(any("import_seed" in t for t in self.tg.texts()))

    def log(self):
        logs = sorted((self.tmp / "state" / "runs").glob("scan-*.log"))
        return logs[-1].read_text()[-3000:] if logs else "(no log)"


if __name__ == "__main__":
    unittest.main()
