import json
import unittest

from _env import JobbotTestCase
import common
import gen_settings
import import_seed
import sites


class Domains(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(sites.normalize_domain("https://www.karriere.at/jobs"), "karriere.at")
        self.assertEqual(sites.normalize_domain("https://jobs.osce.org"), "jobs.osce.org")
        self.assertEqual(sites.normalize_domain("*.myworkdayjobs.com"), "*.myworkdayjobs.com")
        self.assertEqual(sites.normalize_domain("ACME.at:8443/x"), "acme.at")
        self.assertIsNone(sites.normalize_domain("not a domain"))
        self.assertIsNone(sites.normalize_domain("javascript:alert(1)"))

    def test_matches(self):
        self.assertTrue(sites.matches("karriere.at", "www.karriere.at"))
        self.assertTrue(sites.matches("karriere.at", "karriere.at"))
        self.assertFalse(sites.matches("karriere.at", "evilkarriere.at"))
        self.assertFalse(sites.matches("karriere.at", "karriere.at.evil.io"))
        self.assertTrue(sites.matches("*.myworkdayjobs.com", "acme.wd3.myworkdayjobs.com"))
        self.assertFalse(sites.matches("*.myworkdayjobs.com", "myworkdayjobs.com"))


VERIFIED_GROUPS = {"*.jobs.personio.de", "*.jobs.hr.cloud.sap", "*.jobs2web.com"}

SEED = """# title
prose line with https://ignored.example
## Portails
- https://www.karriere.at — V1
- https://www.linkedin.com
* https://www.karriere.at — duplicate
## Groupes
- *.jobs.personio.de — Personio
<!--
- https://commented.example — must be ignored
-->
- not-a-url — ignored
"""


class Seed(JobbotTestCase):
    def test_parse(self):
        entries = import_seed.parse_seed(SEED)
        self.assertEqual([e["domain"] for e in entries], ["karriere.at", "linkedin.com", "*.jobs.personio.de"])
        self.assertEqual(entries[0]["category"], "Portails")
        self.assertEqual(entries[0]["note"], "V1")

    def test_real_seed_parses(self):
        entries = import_seed.parse_seed((self.config / "sites-seed.md").read_text())
        domains = [e["domain"] for e in entries]
        self.assertIn("karriere.at", domains)
        self.assertIn("linkedin.com", domains)
        groups = {d for d in domains if d.startswith("*.")}
        self.assertLessEqual(groups, VERIFIED_GROUPS, "only vendor-documented recruiting-software groups are active")

    def test_unconfirmed_and_source_lines_are_ignored(self):
        text = """## Cat
- https://ok.at — verified
- ⚠ https://unsure.at — not confirmed
- ⚠ *.myworkdayjobs.com — not in the vendor docs
1. https://source.example/doc — numbered source line
"""
        self.assertEqual([e["domain"] for e in import_seed.parse_seed(text)], ["ok.at"])

    def test_import_is_idempotent_and_respects_denied(self):
        (self.config / "sites-seed.md").write_text(SEED)
        data = sites.load()
        data["denied"].append({"domain": "linkedin.com"})
        sites.save(data)
        self.assertEqual(import_seed.main([]), 0)
        self.assertEqual(import_seed.main([]), 0)
        data = sites.load()
        self.assertEqual([e["domain"] for e in data["allowed"]], ["karriere.at", "*.jobs.personio.de"])
        self.assertEqual(sites.status("www.linkedin.com", data), "denied")
        self.assertTrue((self.tmp / "settings.local.json").is_file())

    def test_dry_run_writes_nothing(self):
        (self.config / "sites-seed.md").write_text(SEED)
        self.assertEqual(import_seed.main(["--dry-run"]), 0)
        self.assertFalse((self.config / "sites.yaml").exists())


class PendingDecisions(JobbotTestCase):
    def test_pending_allow_deny(self):
        data = sites.load()
        self.assertTrue(sites.add_pending(data, "www.newco.at", "https://www.karriere.at/jobs/1", "2026-11-23"))
        self.assertFalse(sites.add_pending(data, "newco.at", None, "2026-11-24"))  # same domain, counted
        self.assertEqual(data["pending"][0]["count"], 2)
        self.assertTrue(sites.add_pending(data, "other.at", None, "2026-11-23"))
        self.assertEqual(sites.decide(data, ["newco.at"], "allowed", "2026-11-25"), ["newco.at"])
        self.assertEqual(sites.decide(data, ["other.at"], "denied", "2026-11-25"), ["other.at"])
        self.assertTrue(sites.is_allowed("https://jobs.newco.at/x", data))
        self.assertFalse(sites.add_pending(data, "other.at", None, "2026-11-26"), "a denied host is never re-proposed")
        self.assertEqual(data["pending"], [])


class Settings(JobbotTestCase):
    def setUp(self):
        super().setUp()
        sites.save({"allowed": [{"domain": "karriere.at"}, {"domain": "*.myworkdayjobs.com"}, {"domain": "gone.at"}],
                    "denied": [{"domain": "gone.at"}], "pending": [{"domain": "wait.at"}]})

    def test_generated_settings(self):
        self.assertEqual(gen_settings.main([]), 0)
        local = json.loads((self.tmp / "settings.local.json").read_text())
        scan = json.loads((self.tmp / "state" / "scan-settings.json").read_text())
        sb = local["sandbox"]
        self.assertTrue(sb["enabled"])
        self.assertTrue(sb["failIfUnavailable"])
        self.assertFalse(sb["allowUnsandboxedCommands"])
        self.assertTrue(sb["network"]["strictAllowlist"])
        self.assertEqual(sb["network"]["allowedDomains"], ["karriere.at", "*.karriere.at", "*.myworkdayjobs.com"])
        allow = local["permissions"]["allow"]
        for rule in ("WebFetch(domain:karriere.at)", "WebFetch(domain:*.karriere.at)", "WebFetch(domain:*.myworkdayjobs.com)",
                     "WebSearch"):
            self.assertIn(rule, allow)
        # Removed on purpose from settings.local.template.json by the user (2026-11-24): must stay absent.
        for settings in (local, scan):
            for rule in ("Bash(git remote *)", "Bash(gh repo *)"):
                self.assertNotIn(rule, settings["permissions"]["allow"])
        self.assertFalse(any("gone.at" in r or "wait.at" in r for r in allow), "denied and pending domains are never allowed")
        self.assertEqual(scan["sandbox"], sb)
        self.assertIn("Bash", scan["permissions"]["deny"])
        self.assertEqual((self.tmp / "settings.local.json").stat().st_mode & 0o777, 0o600)

    def test_claude_cannot_modify_the_whitelist(self):
        local, scan = gen_settings.build(["karriere.at"])
        for settings in (local, scan):
            deny = settings["permissions"]["deny"]
            for protected in ("jobbot/config/sites.yaml", ".claude/settings.local.json", ".claude/settings.json",
                              "jobbot/scripts/gen_settings.py", "jobbot/scripts/import_seed.py", "jobbot/state/scan-settings.json"):
                self.assertIn(f"Edit(/{protected})", deny)
                self.assertIn(str(common.ROOT / protected), settings["sandbox"]["filesystem"]["denyWrite"])
            for rule in ("Bash(*import_seed*)", "Bash(*gen_settings*)", "Bash(*sites.yaml*)"):
                self.assertIn(rule, deny)
            self.assertFalse(any(r.startswith("Edit(") and "sites" in r for r in settings["permissions"]["allow"]))


if __name__ == "__main__":
    unittest.main()


# Files Claude must never be able to write (SPEC §5/§6). Each needs, in every generated
# settings file: an Edit deny rule (Edit covers the Write/NotebookEdit tools and Bash
# redirects; a Write(path) rule would be accepted but never matched — permissions doc)
# and an absolute sandbox.filesystem.denyWrite entry (blocks sandboxed Bash writes).
PROTECTED = ["jobbot/config/sites.yaml", "jobbot/state/scan-settings.json",
             ".claude/settings.local.json", ".claude/settings.json", ".claude/settings*.json"]
BASH_RULES = ["Bash(*import_seed*)", "Bash(*gen_settings*)", "Bash(*sites.yaml*)",
              "Bash(*settings.local*)", "Bash(*scan-settings*)"]


def protection_problems(settings: dict) -> list[str]:
    problems = []
    deny = (settings.get("permissions") or {}).get("deny") or []
    deny_write = ((settings.get("sandbox") or {}).get("filesystem") or {}).get("denyWrite") or []
    for path in PROTECTED:
        if f"Edit(/{path})" not in deny:
            problems.append(f"missing permissions.deny Edit(/{path})")
        if str(common.ROOT / path) not in deny_write:
            problems.append(f"missing sandbox.filesystem.denyWrite {common.ROOT / path}")
    problems += [f"missing permissions.deny {r}" for r in BASH_RULES if r not in deny]
    sandbox = settings.get("sandbox") or {}
    if sandbox.get("enabled") is not True or sandbox.get("allowUnsandboxedCommands") is not False:
        problems.append("sandbox.enabled must be true and allowUnsandboxedCommands false")
    return problems


class FileLevelProtection(JobbotTestCase):
    def test_generator_output(self):
        local, scan = gen_settings.build(["karriere.at"])
        self.assertEqual(protection_problems(local), [])
        self.assertEqual(protection_problems(scan), [])

    def test_live_generated_files(self):
        """The files actually in use, not a fresh build: catches a stale or hand-edited copy."""
        for path in (common.ROOT / ".claude" / "settings.local.json", common.ROOT / "jobbot" / "state" / "scan-settings.json"):
            with self.subTest(path=path.name):
                if not path.is_file():
                    self.skipTest(f"{path.name} not generated yet (run import_seed.py)")
                self.assertEqual(protection_problems(json.loads(path.read_text(encoding="utf-8"))), [])
