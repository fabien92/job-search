import json
import os
import socket
import unittest
from pathlib import Path
from unittest import mock

from _env import JobbotTestCase
import common
import companies
import dedup
import prefilter
import sites
from ats import company_scan, connectors, vendors, web

FIX = Path(__file__).with_name("fixtures") / "ats"

PERSONIO_XML = (FIX / "personio.xml").read_text(encoding="utf-8") if (FIX / "personio.xml").exists() else ""


def no_socket(*a, **kw):
    raise AssertionError("a test tried to open a network connection")


class FakeWeb:
    """Injected transport: url -> (status, body, headers). Unknown URL = 404. Records every call."""

    def __init__(self, pages: dict | None = None):
        self.pages = dict(pages or {})
        self.calls: list[str] = []

    def __call__(self, url, headers, timeout):
        self.calls.append(url)
        value = self.pages.get(url)
        if value is None:
            return 404, b"", {}
        if isinstance(value, tuple):
            status, body, hdrs = value
            return status, body.encode() if isinstance(body, str) else body, hdrs
        return 200, value.encode() if isinstance(value, str) else value, {}


class Base(JobbotTestCase):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(socket.socket, "connect", no_socket)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ["JOBBOT_NOW"] = "2026-11-24T10:00:00Z"

    def whitelist(self, allowed=(), denied=(), pending=()):
        sites.save({"allowed": [{"domain": d} for d in allowed], "denied": [{"domain": d} for d in denied],
                    "pending": [{"domain": d} for d in pending]})
        return sites.load()


class Web(Base):
    def test_not_allowed_host_is_never_contacted(self):
        fake = FakeWeb({"https://x.at/": "hi"})
        f = web.Fetcher(self.whitelist(), opener=fake, delay=0)
        with self.assertRaises(web.NotAllowed) as ctx:
            f.get("https://x.at/")
        self.assertEqual(ctx.exception.host, "x.at")
        self.assertEqual(fake.calls, [])

    def test_robots_disallow_and_http_only(self):
        fake = FakeWeb({"https://a.at/robots.txt": "User-agent: *\nDisallow: /private\n", "https://a.at/ok": "fine"})
        f = web.Fetcher(self.whitelist(["a.at"]), opener=fake, delay=0)
        self.assertEqual(f.get("https://a.at/ok")[1], "fine")
        with self.assertRaises(web.RobotsDenied):
            f.get("https://a.at/private/x")
        with self.assertRaises(web.FetchError):
            f.get("http://a.at/ok")
        self.assertEqual(fake.calls.count("https://a.at/robots.txt"), 1, "robots.txt cached per host")

    def test_robots_403_blocks_everything(self):
        fake = FakeWeb({"https://a.at/robots.txt": (403, "", {}), "https://a.at/ok": "fine"})
        f = web.Fetcher(self.whitelist(["a.at"]), opener=fake, delay=0)
        with self.assertRaises(web.RobotsDenied):
            f.get("https://a.at/ok")

    def test_robots_redirect_followed_through_the_whitelist(self):
        fake = FakeWeb({"https://a.at/robots.txt": (301, "", {"Location": "https://www.a.at/robots.txt"}),
                        "https://www.a.at/robots.txt": "User-agent: *\nDisallow: /private\n",
                        "https://a.at/ok": "fine", "https://a.at/private/x": "secret"})
        f = web.Fetcher(self.whitelist(["a.at"]), opener=fake, delay=0)
        self.assertEqual(f.get("https://a.at/ok")[1], "fine")
        with self.assertRaises(web.RobotsDenied):
            f.get("https://a.at/private/x")
        self.assertNotIn("https://a.at/private/x", fake.calls)

    def test_robots_redirect_that_cannot_be_followed_blocks_everything(self):
        cases = {
            "host not allowed": {"https://a.at/robots.txt": (302, "", {"Location": "https://evil.example/robots.txt"})},
            "no Location": {"https://a.at/robots.txt": (301, "", {})},
            "loop": {"https://a.at/robots.txt": (301, "", {"Location": "https://a.at/robots.txt"})},
        }
        for label, pages in cases.items():
            with self.subTest(label):
                fake = FakeWeb({**pages, "https://a.at/ok": "fine"})
                f = web.Fetcher(self.whitelist(["a.at"]), opener=fake, delay=0)
                with self.assertRaises(web.RobotsDenied):
                    f.get("https://a.at/ok")
                self.assertNotIn("https://evil.example/robots.txt", fake.calls)
                self.assertNotIn("https://a.at/ok", fake.calls)

    def test_redirect_to_unknown_host_refused(self):
        fake = FakeWeb({"https://a.at/jobs": (302, "", {"Location": "https://evil.example/jobs"})})
        f = web.Fetcher(self.whitelist(["a.at"]), opener=fake, delay=0)
        with self.assertRaises(web.NotAllowed):
            f.get("https://a.at/jobs")
        self.assertNotIn("https://evil.example/jobs", fake.calls)

    def test_real_transport_disabled_in_tests(self):
        with self.assertRaises(web.FetchError):
            web.urllib_opener("https://example.org/", {}, 1)

    def test_crawl_delay_respected(self):
        slept = []
        fake = FakeWeb({"https://api.lever.co/robots.txt": "User-agent: *\nAllow: /\nCrawl-delay: 1\n",
                        "https://api.lever.co/a": "1", "https://api.lever.co/b": "2"})
        f = web.Fetcher(self.whitelist(["api.lever.co"]), opener=fake, delay=0, sleep=slept.append)
        f.get("https://api.lever.co/a")
        f.get("https://api.lever.co/b")
        self.assertTrue(slept and slept[-1] > 0.5)


class Vendors(unittest.TestCase):
    def test_detection_patterns(self):
        cases = {
            "https://acme.jobs.personio.de/job/123": ("personio", "acme"),
            '<a href="https://acme-gmbh.jobs.personio.com/">': ("personio", "acme-gmbh"),
            "https://boards.greenhouse.io/acme/jobs/42": ("greenhouse", "acme"),
            "https://job-boards.greenhouse.io/acmeco": ("greenhouse", "acmeco"),
            '<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>': ("greenhouse", "acme"),
            "https://jobs.lever.co/acme/abc-123": ("lever", "acme"),
            "https://jobs.eu.lever.co/acme": ("lever", "eu:acme"),
            "https://acme.wd3.myworkdayjobs.com/External": ("workday", "acme"),
            "https://career5.successfactors.eu/career?company=ACMEP&career_ns=job_listing": ("successfactors", "ACMEP"),
            "https://jobs.smartrecruiters.com/Acme/7": ("smartrecruiters", "Acme"),
        }
        for text, expected in cases.items():
            self.assertEqual(vendors.detect_in(text), expected, text)
        self.assertIsNone(vendors.detect_in("https://www.acme.at/karriere"))

    def test_only_verified_vendors_have_connectors(self):
        self.assertEqual(set(connectors.CONNECTORS), {v for v, d in vendors.VENDORS.items() if d["connector"]})
        for v, d in vendors.VENDORS.items():
            if d["connector"]:
                self.assertTrue(d["doc"].startswith("https://") and d["groups"], v)
            else:
                self.assertTrue(d["why"], v)
        self.assertEqual(vendors.group_for("personio", "acme.jobs.personio.de"), "*.jobs.personio.de")
        self.assertIsNone(vendors.group_for("personio", "acme.jobs.personio.com"))


class Connectors(Base):
    def fetcher(self, pages, allowed):
        return web.Fetcher(self.whitelist(allowed), opener=FakeWeb(pages), delay=0)

    def test_personio_xml(self):
        f = self.fetcher({"https://acme.jobs.personio.de/xml?language=en": PERSONIO_XML}, ["*.jobs.personio.de"])
        jobs = connectors.personio("acme", "ACME GmbH", f)
        self.assertEqual(len(jobs), 2)
        j = jobs[0]
        self.assertEqual(j["id"], "acme:1001")
        self.assertEqual(j["url"], "https://acme.jobs.personio.de/job/1001")
        self.assertEqual(j["location"], "Wien, Remote")
        self.assertEqual(j["date"], "2026-11-20")
        self.assertIn("Run 24/7 production", j["detail"]["description"])
        self.assertNotIn("<li>", j["detail"]["description"])

    def test_personio_refuses_doctype(self):
        evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><workzag-jobs/>'
        f = self.fetcher({"https://acme.jobs.personio.de/xml?language=en": evil}, ["*.jobs.personio.de"])
        with self.assertRaises(web.FetchError):
            connectors.personio("acme", "ACME", f)

    def test_personio_refuses_doctype_anywhere_in_the_prolog(self):
        padding = "<!-- " + "x" * 5000 + " -->\n"
        for evil in ('<?xml version="1.0"?>' + padding + '<!DOCTYPE x [<!ENTITY a "b">]><workzag-jobs/>',
                     padding * 3 + "<?pi data?>\n  <!doctype x><workzag-jobs/>",
                     '\ufeff<?xml version="1.0"?><!DOCTYPE x><workzag-jobs/>',
                     '<?xml version="1.0"?><!-- never closed <!DOCTYPE x><workzag-jobs/>'):
            f = self.fetcher({"https://acme.jobs.personio.de/xml?language=en": evil}, ["*.jobs.personio.de"])
            with self.assertRaises(web.FetchError):
                connectors.personio("acme", "ACME", f)
        self.assertFalse(connectors.has_doctype('<?xml version="1.0"?>' + padding + "<workzag-jobs><x>&lt;!DOCTYPE html&gt;</x></workzag-jobs>"))
        self.assertFalse(connectors.has_doctype(PERSONIO_XML))

    def test_odd_dates_are_no_date(self):
        self.assertIsNone(connectors._date(10 ** 30))
        self.assertIsNone(connectors._date(True))
        self.assertEqual(connectors._date(1795600000000), "2026-11-25")

    def test_greenhouse_json(self):
        body = json.dumps({"jobs": [{"id": 7, "title": "IT Service Manager", "location": {"name": "Vienna, Austria"},
                                     "absolute_url": "https://boards.greenhouse.io/acme/jobs/7",
                                     "first_published": "2026-11-22T09:00:00-05:00",
                                     "content": "&lt;p&gt;Own &lt;b&gt;ITIL&lt;/b&gt; processes&lt;/p&gt;"}, {"bad": 1}]})
        f = self.fetcher({"https://boards-api.greenhouse.io/v1/boards/acme/jobs?content=true": body},
                         ["boards-api.greenhouse.io"])
        jobs = connectors.greenhouse("acme", "ACME", f)
        self.assertEqual([j["id"] for j in jobs], ["acme:7"])
        self.assertEqual(jobs[0]["detail"]["description"], "Own ITIL processes")
        self.assertEqual(jobs[0]["date"], "2026-11-22")

    def test_lever_eu_json(self):
        body = json.dumps([{"id": "abc", "text": "Tech Lead", "hostedUrl": "https://jobs.eu.lever.co/acme/abc",
                            "createdAt": 1763900000000, "categories": {"location": "Vienna", "commitment": "Full-time"},
                            "descriptionPlain": "Lead the team.", "lists": [{"text": "You bring", "content": "<li>Oracle</li>"}],
                            "workplaceType": "hybrid"}])
        f = self.fetcher({"https://api.eu.lever.co/v0/postings/acme?mode=json": body}, ["api.eu.lever.co"])
        jobs = connectors.lever("eu:acme", "ACME", f)
        self.assertEqual(jobs[0]["id"], "eu:acme:abc")
        self.assertIn("Oracle", jobs[0]["detail"]["description"])
        self.assertEqual(jobs[0]["employment_type"], "Full-time")


class PendingNote(Base):
    def test_note_passed_only_to_an_extended_sites_py(self):
        calls = []

        def extended(data, host, requested_by, today, note=None):
            calls.append(note)
            return True

        with mock.patch.object(sites, "add_pending", extended):
            vendors.add_pending({}, "*.jobs.personio.de", "https://a.at", "2026-11-24", "groupe Personio")
        self.assertEqual(calls, ["groupe Personio"])
        data = self.whitelist([])
        self.assertTrue(vendors.add_pending(data, "*.jobs.personio.de", "https://a.at", "2026-11-24", "x"))

    def test_note_shown_with_clickable_doc(self):
        import logic

        sites.save({"allowed": [], "denied": [], "pending": [
            {"domain": "*.jobs.personio.de", "first_seen": "2026-11-24", "requested_by": "https://www.acme.at/karriere",
             "note": vendors.group_note("personio")}]})
        text = logic.pending_list_text(refresh=True)
        self.assertIn("Personio group", text)
        self.assertIn('<a href="https://developer.personio.de/docs/integration-of-open-positions">', text)


class CompaniesFile(Base):
    def test_seed_parse_and_import_without_touching_whitelist(self):
        import import_companies

        sites.save({"allowed": [{"domain": "karriere.at"}], "denied": [], "pending": []})
        before = (self.config / "sites.yaml").read_bytes()
        seed = self.config / "companies-seed.md"
        seed.write_text(
            "# Entreprises\n\n## Entreprises françaises à Vienne\n"
            "- Thales Austria GmbH · Wien · https://www.thalesgroup.com/at · source : https://ccfa.at/members\n"
            "- ACME · Wien · https://acme.at/\n"
            "- Accenture GmbH · Wien · https://www.accenture.com/at · source : https://x.at\n"
            "- ligne cassée sans lien\n"
            "<!-- commentaire -->\n", encoding="utf-8")
        result = import_companies.run(seed, dry=False)
        self.assertEqual(result["added"], ["Thales Austria GmbH", "ACME"])
        self.assertEqual(result["excluded"], ["Accenture GmbH"])
        self.assertEqual(len(result["malformed"]), 1)
        rows = companies.load()
        self.assertEqual(rows[0]["region"], "wien")
        self.assertEqual(rows[0]["origin"], "seed:Entreprises françaises à Vienne")
        self.assertEqual(rows[0]["source"], "https://ccfa.at/members")
        self.assertEqual(rows[1]["website"], "https://acme.at")
        self.assertEqual((self.config / "sites.yaml").read_bytes(), before, "whitelist untouched")
        again = import_companies.run(seed, dry=False)
        self.assertEqual(again["added"], [])
        self.assertEqual(len(companies.load()), 2)

    def test_block_covers_longer_names(self):
        rows = []
        companies.add(rows, "Erste Group Bank AG", website="https://www.erstegroup.com")
        row, covered = companies.block(rows, "Erste")
        self.assertEqual(row["status"], "blocked")
        self.assertEqual(covered, ["Erste Group Bank AG"])
        keys = companies.blocked_keys(rows)
        self.assertTrue(companies.is_blocked("Erste Group Bank AG", keys))
        self.assertFalse(companies.is_blocked("Ersteller GmbH", keys))


class Stage(Base):
    """company_scan.collect inside prefilter.run: detection, proposals, connector, filters."""

    def setUp(self):
        super().setUp()
        with common.state_lock():
            rows = []
            companies.add(rows, "ACME GmbH", city="Wien", region="wien", website="https://www.acme.at",
                          source="https://ccfa.at/members")
            companies.add(rows, "Blocked Corp", city="Wien", website="https://blocked.at", ats="personio",
                          ats_slug="blocked")
            companies.save(rows)
        companies.block(rows := companies.load(), "Blocked Corp")
        companies.save(rows)
        self.pages = {
            "https://www.acme.at": '<a href="/karriere">Karriere</a>',
            "https://www.acme.at/karriere": '<iframe src="https://acme.jobs.personio.de/"></iframe>',
            "https://acme.jobs.personio.de/xml?language=en": PERSONIO_XML,
        }
        self.fake = FakeWeb(self.pages)
        real = web.Fetcher
        patcher = mock.patch.object(company_scan, "Fetcher",
                                    lambda whitelist=None: real(whitelist, opener=self.fake, delay=0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_prefilter(self):
        with mock.patch.object(prefilter, "guard", lambda raw, clean: (clean.write_text(raw.read_text()), {
                "ok": True, "verdict": "clean", "alarm": False, "instruction_like": []})[1]):
            prefilter.run("20261124T100000", "companies")
        return common.read_json(common.runs_dir() / "20261124T100000-prefilter.json")

    def test_unknown_hosts_go_pending_nothing_fetched(self):
        self.whitelist([])
        report = self.run_prefilter()
        self.assertEqual(self.fake.calls, [], "no request to a host that is not allowed")
        self.assertIn({"host": "www.acme.at", "requested_by": "https://ccfa.at/members"}, report["blocked_hosts"])
        self.assertEqual(sites.load()["allowed"], [], "prefilter never allows anything")

    def test_unknown_only_recorded_when_a_page_was_read(self):
        self.whitelist([])
        self.run_prefilter()
        row = companies.find(companies.load(), "ACME")
        self.assertEqual((row["ats"], row["verified"]), ("", ""), "host not allowed yet: nothing learnt, retried at once")
        # /allow the same day: detection runs on the next pass instead of waiting REDETECT_DAYS
        (common.state_dir() / "companies_runs.json").unlink()
        self.whitelist(["acme.at"])
        self.run_prefilter()
        self.assertEqual(companies.find(companies.load(), "ACME")["ats"], "personio")

    def test_network_error_is_not_an_answer_but_a_read_page_is(self):
        self.whitelist(["acme.at"])
        self.fake.pages = {"https://www.acme.at/robots.txt": "", "https://www.acme.at": (500, "", {})}
        self.run_prefilter()
        self.assertEqual(companies.find(companies.load(), "ACME")["ats"], "", "HTTP 500: try again next run")
        (common.state_dir() / "companies_runs.json").unlink()
        self.fake.pages = {"https://www.acme.at/robots.txt": "", "https://www.acme.at": "<p>no career link here</p>"}
        self.run_prefilter()
        row = companies.find(companies.load(), "ACME")
        self.assertEqual((row["ats"], row["verified"]), ("unknown", "2026-11-24"))

    def test_broken_feed_costs_one_company_only(self):
        with common.state_lock():
            rows = companies.load()
            companies.add(rows, "Broken AG", city="Wien", region="wien", website="https://broken.at", ats="greenhouse",
                          ats_slug="broken")
            companies.save(rows)
        self.pages["https://boards-api.greenhouse.io/v1/boards/broken/jobs?content=true"] = '["a list, not an object"]'
        self.fake.pages = dict(self.pages)
        self.whitelist(["acme.at", "*.jobs.personio.de", "boards-api.greenhouse.io"])
        report = self.run_prefilter()
        self.assertEqual([j["title"] for j in report["to_score"]], ["IT Delivery Manager (m/w/d)"], "ACME still scanned")
        broken = [e for e in report["errors"] if e.get("query") == "Broken AG"]
        self.assertEqual(len(broken), 1)
        self.assertIn("unexpected feed", broken[0]["error"])
        checked = common.read_json(common.state_dir() / "companies_runs.json")["checked"]
        self.assertIn(companies.key_of("Broken AG"), checked, "sent to the back of the line")

    def test_detect_then_propose_group_with_note(self):
        self.whitelist(["acme.at"])
        report = self.run_prefilter()
        row = companies.find(companies.load(), "ACME")
        self.assertEqual((row["ats"], row["ats_slug"]), ("personio", "acme"))
        self.assertEqual(row["careers_url"], "https://www.acme.at/karriere")
        group = [b for b in report["blocked_hosts"] if b["host"] == "*.jobs.personio.de"]
        self.assertEqual(len(group), 1)
        self.assertIn("developer.personio.de", group[0]["note"])
        self.assertNotIn("https://acme.jobs.personio.de/xml?language=en", self.fake.calls)
        self.assertEqual([e["domain"] for e in sites.load()["allowed"]], ["acme.at"], "group never allowed by code")

    def test_group_pending_through_postprocess_never_allowed(self):
        import postprocess

        data = self.whitelist(["acme.at"])
        vendors.add_pending(data, "*.jobs.personio.de", "https://www.acme.at/karriere", "2026-11-24",
                            vendors.group_note("personio"))
        sites.save(data)
        data = sites.load()
        self.assertEqual(sites.status("*.jobs.personio.de", data), "pending")
        self.assertFalse(sites.is_allowed("acme.jobs.personio.de", data))
        self.assertTrue(hasattr(postprocess, "vendors"))

    def test_jobs_from_allowed_feed_are_filtered_and_batched(self):
        self.whitelist(["acme.at", "*.jobs.personio.de"])
        report = self.run_prefilter()
        batch = common.read_json(common.runs_dir() / "20261124T100000-batch.json")
        titles = [j["title"] for j in batch["jobs"]]
        self.assertEqual(titles, ["IT Delivery Manager (m/w/d)"])
        self.assertEqual(batch["jobs"][0]["site"], "personio")
        self.assertEqual(report["companies_out_of_region"], 1, "Berlin-only job dropped before Claude")
        text = Path(batch["jobs"][0]["text_path"]).read_text()
        self.assertIn("Run 24/7 production", text)
        self.assertNotIn("https://blocked.jobs.personio.de/xml?language=en", self.fake.calls, "blocked company skipped")
        # second run: same jobs are duplicates (ledger written by postprocess in real runs; batch here)
        self.assertNotIn("detail", batch["jobs"][0])

    def test_frequency_gate(self):
        self.whitelist(["acme.at", "*.jobs.personio.de"])
        self.run_prefilter()
        report = {"sites": {}, "skipped_sites": [], "errors": [], "blocked_hosts": []}
        rules = prefilter.Rules(prefilter.load_criteria(), common.load_regions(), 48)
        out = company_scan.collect(rules, dedup.Ledger(), common.load_regions(), common.load_schedule(), report)
        self.assertEqual(out, [])
        self.assertEqual(report["skipped_sites"][0]["reason"], "companies_every_hours")

    def test_blocked_company_rejected_from_portals_too(self):
        rules = prefilter.Rules(prefilter.load_criteria(), common.load_regions(), 48)
        job = {"title": "IT Manager", "company": "Blocked Corp GmbH", "location": "Wien", "date": "2026-11-24"}
        self.assertEqual(rules.check(job, common.dt.date(2026, 11, 24)), "company_blocked")


if __name__ == "__main__":
    unittest.main()
