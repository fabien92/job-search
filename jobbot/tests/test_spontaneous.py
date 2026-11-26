import json
import os
import socket
import unittest
from pathlib import Path
from unittest import mock

from _env import FakeTelegram, JobbotTestCase
import applications as apps
import common
import companies
import contacts
import discover
import logic
import sites
import spont_list
import spontaneous
from ats import web
from test_companies import FakeWeb, no_socket

HERE = Path(__file__).resolve().parent
VARIANTS = ("delivery", "techlead", "international-orgs", "support-it-manager")
BODY = ("Dear Ms Muster,\n\nI am an IT Delivery Manager based in Vienna with ten years of production and release "
        "governance for a critical derivatives platform. " * 3 + "\n\nKind regards,\nJane Doe")
IMPRESSUM = "<html><p>ACME GmbH, 1010 Wien</p><p>E-Mail: jobs (at) acme.at</p></html>"


def output(**over):
    doc = {"id": "S1", "contact": {"name": "Jane Muster", "role": "Head of IT", "email": "jobs@acme.at",
                                   "email_source_url": "https://www.acme.at/impressum",
                                   "linkedin_url": "https://www.linkedin.com/in/jane-muster",
                                   "linkedin_source_url": "https://www.google.com/search?q=x"},
           "variant": "techlead", "email": {"subject": "Spontaneous application — IT Delivery Manager", "body": BODY},
           "linkedin_message": "Hello Jane, I lead IT delivery for a critical banking platform and am moving to Vienna."}
    for k, v in over.items():
        if k in doc["contact"]:
            doc["contact"][k] = v
        else:
            doc[k] = v
    return doc


class Base(JobbotTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(socket.socket, "connect", no_socket)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tg = FakeTelegram()
        self.addCleanup(self.tg.close)
        os.environ.update({"JOBBOT_TELEGRAM_API": self.tg.url, "TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT_ID": "42",
                           "JOBBOT_NOW": "2026-11-24T19:00:00Z", "JOBBOT_CLAUDE_BIN": str(HERE / "fake_claude.py")})
        self.addCleanup(lambda: os.environ.pop("FAKE_V3_OUTPUT", None))
        cv = self.tmp / "cv"
        for sub in ("variants", "blocks", "pdf"):
            (cv / sub).mkdir(parents=True)
        for name in VARIANTS:
            (cv / "variants" / f"{name}.tex").write_text(f"% {name}\n")
            (cv / "pdf" / f"{name}.pdf").write_bytes(b"%PDF-1.4 " + name.encode())
        (common.state_dir() / "scan-settings.json").write_text("{}")
        patcher = mock.patch.object(discover, "command_installed", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        sites.save({"allowed": [{"domain": "acme.at"}, {"domain": "linkedin.com"}], "denied": [], "pending": []})
        rows = []
        for name, site in (("ACME GmbH", "https://www.acme.at"), ("Beta AG", "https://beta.at"),
                           ("Gamma GmbH", "https://gamma.at"), ("Delta Bank AG", "https://delta.at")):
            companies.add(rows, name, city="Wien", region="wien", website=site, source="https://ccfa.at/m")
        companies.save(rows)
        self.web = FakeWeb({"https://www.acme.at/impressum": IMPRESSUM})

    def fetcher(self):
        return web.Fetcher(sites.load(), opener=self.web, delay=0)

    def spont(self, doc, name="ACME GmbH"):
        os.environ["FAKE_V3_OUTPUT"] = json.dumps(doc) if doc is not None else ""
        return spontaneous.run(name, fetcher=self.fetcher())

    def texts(self):
        return "\n".join(self.tg.texts())


class Spontaneous(Base):
    def test_full_flow_never_sends_and_sent_closes(self):
        self.assertEqual(self.spont(output()), 0)
        row = contacts.get("S1")
        self.assertEqual((row["status"], row["email"], row["variant"]), ("prepared", "jobs@acme.at", "techlead"))
        self.assertEqual(row["email_source"], "https://www.acme.at/impressum")
        folder = common.spontaneous_dir() / "acme_gmbh"
        email = (folder / "email.txt").read_text()
        self.assertIn("To: jobs@acme.at", email)
        self.assertIn("Address found on: https://www.acme.at/impressum", email)
        self.assertIn("/sent S1", email)
        li = (folder / "linkedin.txt").read_text()
        self.assertIn("Profile: https://www.linkedin.com/in/jane-muster", li)
        self.assertRegex(li, r"Message \(\d+/300 characters\)")
        self.assertTrue((folder / "S1_acme_gmbh_CV.pdf").read_bytes().startswith(b"%PDF"))
        methods = [m for m, _ in self.tg.calls]
        self.assertEqual(methods.count("sendDocument"), 3)
        self.assertIn("Rien n'est envoyé", self.texts())
        argv = json.loads((common.runs_dir() / "fake-claude-argv.json").read_text())
        tools = argv[argv.index("--allowedTools") + 1]
        self.assertIn("WebFetch(domain:acme.at)", tools)
        self.assertNotIn("WebFetch(domain:linkedin.com)", tools, "WebFetch limited to the official site")
        self.assertIn("Bash", argv[argv.index("--disallowedTools") + 1])
        # /sent S1 -> sent, files removed from Telegram, company never listed again
        reply = logic.cmd_sent("S1")
        self.assertIn("S1 envoyée", reply)
        self.assertEqual(contacts.get("S1")["status"], "sent")
        self.assertIn("déjà en statut sent", logic.cmd_sent("S1"))
        self.assertNotIn("ACME GmbH", [r["name"] for r in spont_list.pick(common.load_schedule())])
        self.assertIn("déjà contactée", logic.cmd_spont("ACME GmbH"))

    def test_guessed_address_is_dropped(self):
        self.assertEqual(self.spont(output(email="jane.muster@acme.at")), 0)
        row = contacts.get("S1")
        self.assertEqual(row["email"], "", "address absent from the source page")
        self.assertEqual(row["linkedin"], "https://www.linkedin.com/in/jane-muster")
        self.assertFalse((common.spontaneous_dir() / "acme_gmbh" / "email.txt").exists())
        self.assertIn("adresse non confirmée", self.texts())

    def test_source_outside_official_site_is_dropped(self):
        self.web.pages["https://www.firmenabc.at/acme"] = IMPRESSUM
        self.spont(output(email_source_url="https://www.firmenabc.at/acme"))
        self.assertEqual(contacts.get("S1")["email"], "")
        self.assertNotIn("https://www.firmenabc.at/acme", self.web.calls)

    def test_nothing_verified_nothing_prepared(self):
        self.assertEqual(self.spont(output(email="x@acme.at", linkedin_url="")), 1)
        self.assertEqual(contacts.load(), [], "reserved ID released")
        self.assertIn("rien de préparé", self.texts())
        self.assertEqual(self.spont(None), 1)

    def test_linkedin_message_limit(self):
        self.spont(output(email="", linkedin_message="x" * 301))
        self.assertIn("rien de préparé", self.texts())
        self.assertIn("trop long", self.texts())

    def test_same_contact_never_twice(self):
        self.spont(output())
        rows = companies.load()
        companies.find(rows, "Beta")["website"] = "https://www.acme.at/beta"  # same official host
        companies.save(rows)
        self.assertEqual(self.spont(output(), name="Beta AG"), 1)
        self.assertIn("contact déjà sollicité (S1)", self.texts())

    def test_site_not_allowed_goes_pending_without_claude(self):
        self.assertEqual(spontaneous.run("Beta AG", fetcher=self.fetcher()), 2)
        self.assertEqual(sites.status("beta.at"), "pending")
        self.assertFalse((common.runs_dir() / "fake-claude-argv.json").exists())
        self.assertEqual([e["domain"] for e in sites.load()["allowed"]], ["acme.at", "linkedin.com"])

    def test_refusals(self):
        logic.cmd_block("Gamma")
        for name, why in (("Gamma GmbH", "blocked"), ("Unknown", "inconnue")):
            self.assertIn(why, logic.cmd_spont(name))
        apps.write_tracker(apps.TRACKER_HEADER, [{"company": "Delta Bank AG", "role": "IT PM", "status": "applied"}])
        self.assertIn("déjà contactée", logic.cmd_spont("Delta Bank"))
        spawned = []
        self.assertIn("Préparation lancée", logic.cmd_spont("ACME", spawn=spawned.append))
        self.assertEqual(spawned[0][-1], "ACME GmbH")

    def test_dry_run_keeps_real_contacts_clean(self):
        os.environ["JOBBOT_DRY_RUN"] = "1"
        self.spont(output())
        self.assertEqual(contacts.load(False), [])
        self.assertEqual(contacts.load(True)[0]["id"], "TS1")
        self.assertTrue((common.cache_dir() / "test-spontaneous" / "acme_gmbh" / "email.txt").exists())
        self.assertIn("[TEST]", self.texts())
        os.environ.pop("JOBBOT_DRY_RUN")
        self.assertIn("ACME GmbH", [r["name"] for r in spont_list.pick(common.load_schedule())],
                      "a test contact never hides a company from the real list")

    def test_cancel(self):
        self.spont(output())
        self.assertIn("abandonnée", logic.cmd_cancel("S1"))
        self.assertEqual(contacts.get("S1")["status"], "cancelled")
        self.assertIn("ID inconnu", logic.cmd_sent("S9"))


class EveningList(Base):
    def test_excludes_contacted_blocked_applied_and_rotates(self):
        os.environ["FAKE_V3_OUTPUT"] = ""
        with common.state_lock():
            contacts.save([{"id": "S1", "company": "Beta AG", "status": "sent"},
                           {"id": "S2", "company": "Gamma", "status": "cancelled"}])
        apps.write_tracker(apps.TRACKER_HEADER, [{"company": "Delta Bank", "role": "x", "status": "interview"}])
        names = [r["name"] for r in spont_list.pick(common.load_schedule())]
        self.assertEqual(names, ["ACME GmbH"])
        spont_list.main()
        self.assertIn("/spont ACME GmbH", self.texts())
        self.assertEqual(spont_list.pick(common.load_schedule()), [], "listed today: not again for 14 days")
        os.environ["JOBBOT_NOW"] = "2026-12-09T19:00:00Z"
        self.assertEqual([r["name"] for r in spont_list.pick(common.load_schedule())], ["ACME GmbH"])
        logic.cmd_block("ACME")
        self.assertEqual(spont_list.pick(common.load_schedule()), [])
        spont_list.main()
        self.assertIn("aucune entreprise", self.texts())

    def test_allowed_sites_first(self):
        rows = companies.load()
        names = [r["name"] for r in spont_list.pick({**common.load_schedule(), "spont_list_size": 4})]
        self.assertEqual(names[0], "ACME GmbH")
        self.assertIn("site à autoriser", spont_list.build(spont_list.pick({**common.load_schedule(), "spont_list_size": 4})))


class Discovery(Base):
    def proposals(self, *items):
        return {"run_id": "x", "companies": list(items)}

    def test_proposed_then_accept_reject(self):
        with common.state_lock():
            contacts.save([{"id": "S1", "company": "Contacted GmbH", "status": "sent"}])
        logic.cmd_block("Blockd")
        os.environ["FAKE_V3_OUTPUT"] = json.dumps(self.proposals(
            {"name": "Neu GmbH", "city": "Wien", "website": "https://neu.at", "source_url": "https://neu.at/impressum"},
            {"name": "Zwei AG", "website": "https://zwei.at", "source_url": "https://wko.at/zwei"},
            {"name": "ACME GmbH", "website": "https://www.acme.at", "source_url": "https://x.at"},
            {"name": "Accenture GmbH", "website": "https://accenture.at", "source_url": "https://x.at"},
            {"name": "Contacted GmbH", "website": "https://contacted.at", "source_url": "https://x.at"},
            {"name": "Blockd GmbH", "website": "https://blockd.at", "source_url": "https://x.at"},
            {"name": "Sans source", "website": "https://s.at"},
            {"name": "Http only", "website": "http://h.at", "source_url": "https://x.at"}))
        self.assertEqual(discover.run("wien"), 0)
        rows = companies.load()
        proposed = [r["name"] for r in companies.proposed(rows)]
        self.assertEqual(proposed, ["Neu GmbH", "Zwei AG"])
        self.assertEqual(companies.find(rows, "Neu")["origin"], "discover:neu.at")
        self.assertIn("déjà contactées 1", self.texts())
        self.assertIn("Fais d'abord /companies", logic.cmd_accept("1"))
        text = logic.cmd_companies()
        self.assertIn('1. <b>Neu GmbH</b> · Wien · <a href="https://neu.at">neu.at</a>', text)
        self.assertIn("1 entreprise(s) ajoutée(s)", logic.cmd_accept("1"))
        self.assertIn("écartée", logic.cmd_reject("2"))
        self.assertIn("déjà traitées", logic.cmd_accept("1-2"))
        rows = companies.load()
        self.assertEqual((companies.find(rows, "Neu")["status"], companies.find(rows, "Zwei")["status"]),
                         ("active", "rejected"))
        # a rejected company is never proposed again
        discover.run("wien")
        self.assertEqual(companies.proposed(companies.load()), [])
        self.assertEqual(sites.status("neu.at"), "unknown", "discovery never touches the whitelist")

    def test_region_must_be_enabled(self):
        self.assertIn("région activée", logic.cmd_discover("graz"))
        self.assertEqual(discover.run("graz"), 1)
        spawned = []
        self.assertIn("Découverte lancée", logic.cmd_discover("wien", spawn=spawned.append))
        self.assertEqual(spawned[0][-1], "wien")

    def test_webfetch_limited_to_allowed_hosts(self):
        os.environ["FAKE_V3_OUTPUT"] = json.dumps(self.proposals())
        discover.run("wien")
        argv = json.loads((common.runs_dir() / "fake-claude-argv.json").read_text())
        tools = argv[argv.index("--allowedTools") + 1].split(",")
        fetch = sorted(t for t in tools if t.startswith("WebFetch"))
        self.assertEqual(fetch, ["WebFetch(domain:acme.at)", "WebFetch(domain:linkedin.com)",
                                 "WebFetch(domain:www.acme.at)", "WebFetch(domain:www.linkedin.com)"])
        self.assertNotIn("WebFetch", [t for t in tools if "(" not in t])

    def test_dry_run_writes_no_company(self):
        os.environ["JOBBOT_DRY_RUN"] = "1"
        os.environ["FAKE_V3_OUTPUT"] = json.dumps(self.proposals(
            {"name": "Neu GmbH", "website": "https://neu.at", "source_url": "https://neu.at/i"}))
        discover.run("wien")
        self.assertEqual(companies.proposed(companies.load()), [])
        self.assertIn("[TEST]", self.texts())


class Wiring(unittest.TestCase):
    def test_handlers(self):
        import bot
        from telegram.ext import CommandHandler

        app = bot.build("123:abc", "42")
        names = {c for g in app.handlers.values() for h in g if isinstance(h, CommandHandler) for c in h.commands}
        self.assertTrue({"spont", "discover", "companies", "accept", "reject", "block", "blocked", "unblock",
                         "rules", "rule"} <= names)

    def test_launchd_has_evening_list(self):
        import gen_launchd

        plists = gen_launchd.build("jobbot", Path("/Users/jobbot/ai-job-search"), common.load_schedule())
        self.assertEqual(plists["com.jobbot.spont"]["StartCalendarInterval"], {"Hour": 20, "Minute": 0})
        self.assertTrue(plists["com.jobbot.spont"]["ProgramArguments"][-1].endswith("spont_list.sh"))


if __name__ == "__main__":
    unittest.main()
