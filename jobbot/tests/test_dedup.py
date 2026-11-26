import json
import unittest

from _env import JobbotTestCase
import dedup


class Normalisation(unittest.TestCase):
    def test_gender_markers(self):
        base = "projektmanager"
        for title in ["Projektmanager (m/w/d)", "Projektmanager (w/m/x)", "Projektmanager (f/m/d)", "Projektmanager (m/f/d)",
                      "Projektmanager (all genders)", "Projektmanager m/w/d", "Projektmanager:in", "Projektmanager*in",
                      "PROJEKTMANAGER (W/M/D)", "Projektmanager_in", "ProjektmanagerIn", "Projektmanager/-in"]:
            self.assertEqual(dedup.norm_title(title), base, title)

    def test_title_keeps_identity(self):
        self.assertNotEqual(dedup.norm_title("C++ Developer"), dedup.norm_title("C Developer"))
        self.assertEqual(dedup.norm_title("Senior IT-Projektmanager*in"), "senior it projektmanager")
        self.assertEqual(dedup.norm_title("Développeur Python"), dedup.norm_title("Developpeur Python"))

    def test_legal_forms(self):
        for name in ["PORR AG", "Porr", "PORR  ag.", "porr gmbh", "Porr GmbH & Co KG", "Porr s.r.o.", "PORR Kft.", "Porr e.U.",
                     "Porr Ltd", "Porr Inc.", "Porr LLC", "Porr Zrt.", "Porr Nyrt.", "Porr a.s.", "Porr SE", "Porr OG"]:
            self.assertEqual(dedup.norm_company(name), "porr", name)
        self.assertEqual(dedup.norm_company("Erste Group Bank AG"), "erste group bank")
        self.assertEqual(dedup.norm_company("Österreichische Post AG"), "osterreichische post")

    def test_city(self):
        aliases = dedup.city_aliases({"wien": {"names": ["Wien", "Vienna", "Vienne"]}, "graz": {"names": ["Graz"]}})
        for loc in ["Wien", "Vienna", "vienne", "1010 Wien", "Vienna, Austria", "Wien, Graz, Wels", "A-1030 Wien"]:
            self.assertEqual(dedup.norm_city(loc, aliases), "wien", loc)
        self.assertEqual(dedup.norm_city("Graz", aliases), "graz")
        self.assertEqual(dedup.norm_city("Klagenfurt am Wörthersee", aliases), "klagenfurt am worthersee")
        self.assertEqual(dedup.norm_city(None, aliases), "")

    def test_triple_key_matches_across_sites(self):
        aliases = dedup.city_aliases({"wien": {"names": ["Wien", "Vienna"]}})
        a = dedup.triple_key("PORR AG", "Senior IT-Projektmanager*in", "Wien", aliases)
        b = dedup.triple_key("Porr", "Senior IT-Projektmanager (m/w/d)", "Vienna, Austria", aliases)
        self.assertEqual(a, b)


class Urls(unittest.TestCase):
    def test_clean(self):
        self.assertEqual(dedup.clean_url("https://Jobs.VBV.at/register/34/?referrer=karriere_at&utm_source=x&id=5#top"),
                         "https://jobs.vbv.at/register/34?id=5")
        # only tracking parameters go: `ref`, `src`, `source`, `from`… can be the job reference
        self.assertEqual(dedup.clean_url("https://a.example/x?trk=1&ref=2&src=3&gclid=9&fbclid=8"),
                         "https://a.example/x?ref=2&src=3")
        self.assertNotEqual(dedup.clean_url("https://jobs.x.com/apply?ref=123"), dedup.clean_url("https://jobs.x.com/apply?ref=456"))
        # a route-like fragment identifies the posting on single-page career sites; a plain anchor does not
        self.assertEqual(dedup.clean_url("https://careers.x.com/#/job/1"), "https://careers.x.com#/job/1")
        self.assertNotEqual(dedup.clean_url("https://careers.x.com/#/job/1"), dedup.clean_url("https://careers.x.com/#/job/2"))
        self.assertEqual(dedup.clean_url("https://careers.x.com/jobs#top"), "https://careers.x.com/jobs")
        self.assertEqual(dedup.clean_url("HTTPS://a.example:443/x"), "https://a.example/x")
        self.assertEqual(dedup.clean_url("https://a.example:443/x/"), "https://a.example/x")
        self.assertIsNone(dedup.clean_url("javascript:alert(1)"))
        self.assertIsNone(dedup.clean_url(""))

    def test_site_key(self):
        self.assertEqual(dedup.site_key("karriere", "10037361"), "karriere:10037361")


def hit(site, id_, title, company, location, url=None):
    return dedup.annotate({"site": site, "id": id_, "title": title, "company": company, "location": location,
                           "url": url or f"https://{site}.example/jobs/{id_}"},
                          dedup.city_aliases({"wien": {"names": ["Wien", "Vienna"]}}))


class Checks(JobbotTestCase):
    def test_order_and_reasons(self):
        ledger = dedup.Ledger()
        old = hit("karriere", "1", "Tech Lead (m/w/d)", "ACME GmbH", "Wien", "https://www.karriere.at/jobs/1")
        old["employer_url"] = "https://acme.at/jobs/42"
        ledger.add(old["key"], {**old, "status": "rejected"})
        up = dedup.Upstream()
        batch = dedup.Batch()

        self.assertEqual(dedup.check_search_hit(hit("karriere", "1", "Other", "Other", "Graz"), ledger, up, batch), "dup_site_id")
        self.assertEqual(dedup.check_search_hit(hit("linkedin", "99", "Tech Lead", "Acme", "Vienna"), ledger, up, batch),
                         "dup_company_title_location")
        fresh = hit("linkedin", "100", "Tech Lead", "Acme", "Graz")  # other city -> not a duplicate
        self.assertIsNone(dedup.check_search_hit(fresh, ledger, up, batch))
        batch.add(fresh)
        self.assertEqual(dedup.check_search_hit(hit("karriere", "200", "Tech Lead (w/m/x)", "ACME AG", "Graz"), ledger, up, batch),
                         "dup_in_run")
        b = hit("karriere", "300", "Delivery Manager", "Beta", "Wien")
        b["employer_url"] = dedup.clean_url("https://ACME.at/jobs/42/?utm_campaign=x")
        self.assertEqual(dedup.check_employer_url(b, ledger, batch), "dup_employer_url")

    def test_upstream_and_tracker(self):
        seen = {"acme_tech-lead": {"url": "https://x.example/1", "company": "ACME", "title": "Tech Lead"}}
        up = dedup.Upstream(seen, {(dedup.upstream_norm("Beta"), dedup.upstream_norm("Scrum Master"))})
        ledger, batch = dedup.Ledger(), dedup.Batch()
        self.assertEqual(dedup.check_search_hit(hit("linkedin", "5", "Tech Lead", "ACME", "Wien"), ledger, up, batch), "dup_upstream")
        self.assertEqual(dedup.check_search_hit(hit("linkedin", "6", "Scrum Master", "Beta", "Wien"), ledger, up, batch),
                         "already_applied")
        self.assertEqual(dedup.check_search_hit(hit("linkedin", "7", "X", "Y", "Wien", "https://x.example/1/"), ledger, up, batch),
                         "dup_upstream")

    def test_upstream_load_from_files(self):
        (self.tmp / "seen_jobs.json").write_text(json.dumps({"seen": {"k": {"url": "https://u/1", "company": "C", "title": "T"}}}))
        (self.tmp / "tracker.csv").write_text("company,role,status\nGamma,Architect,applied\n")
        up = dedup.Upstream.load()
        self.assertIn("https://u/1", up.urls)
        self.assertIn(("gamma", "architect"), up.tracker)

    def test_null_company_never_matches_on_triple(self):
        ledger = dedup.Ledger()
        a = hit("linkedin", "1", "Tech Lead", None, "Wien")
        ledger.add(a["key"], a)
        self.assertIsNone(dedup.check_search_hit(hit("karriere", "2", "Tech Lead", None, "Wien"), ledger, dedup.Upstream(), dedup.Batch()))

    def test_ledger_roundtrip_and_short_ids(self):
        ledger = dedup.Ledger.load()
        sid = ledger.allocate_id()
        a = hit("karriere", "1", "T", "C", "Wien")
        ledger.add(a["key"], {**a, "short_id": sid})
        ledger.save()
        again = dedup.Ledger.load()
        self.assertEqual(again.next_id, 2)
        self.assertEqual(again.find_short("#1")[0], "karriere:1")
        self.assertIsNone(again.find_short("2"))


def seen(ledger, job, first_seen="2026-11-20T08:00:00Z", **kw):
    ledger.add(job["key"], {**job, "first_seen": first_seen, "status": "low", "short_id": "7", **kw})


class Republications(JobbotTestCase):
    """V4: same company + same city, title slightly reworded."""

    def setUp(self):
        super().setUp()
        import os
        os.environ["JOBBOT_NOW"] = "2026-11-24T10:00:00Z"
        self.cfg = dedup.republish_settings({})
        self.ledger = dedup.Ledger()
        seen(self.ledger, hit("karriere", "1", "Senior IT Delivery Manager (m/w/d)", "ACME GmbH", "Wien"))

    def check(self, title, company="ACME AG", location="Vienna", site="stepstone", id_="9", batch=None):
        job = hit(site, id_, title, company, location)
        self.assertIsNone(dedup.check_search_hit(job, self.ledger, dedup.Upstream(), batch or dedup.Batch()))
        return dedup.check_republished(job, self.ledger, batch, self.cfg)

    def test_reworded_title_is_a_republication(self):
        for title in ("IT Delivery Manager – Senior", "IT Delivery Manager (Senior) (all genders)",
                      "Senior IT-Delivery-Manager:in (Cloud)", "IT Delivery Manager", "Senior Delivery Manager for IT"):
            with self.subTest(title=title):
                original = self.check(title)
                self.assertEqual(original, {"key": "karriere:1", "short_id": "7",
                                            "title": "Senior IT Delivery Manager (m/w/d)"})

    def test_different_jobs_are_kept(self):
        for title in ("IT Project Manager", "Junior IT Delivery Manager", "Senior Delivery Manager Payments Platform Team",
                      "Head of IT Delivery", "Release Manager"):
            with self.subTest(title=title):
                self.assertIsNone(self.check(title))

    def test_other_company_or_city_never_compared(self):
        self.assertIsNone(self.check("IT Delivery Manager – Senior", company="Beta GmbH"))
        self.assertIsNone(self.check("IT Delivery Manager – Senior", location="Graz"))
        self.assertIsNone(self.check("IT Delivery Manager – Senior", company=None))

    def test_window_and_circumstantial_originals(self):
        ledger = dedup.Ledger()
        seen(ledger, hit("karriere", "1", "Senior IT Delivery Manager", "ACME", "Wien"), first_seen="2026-10-20T08:00:00Z")
        job = hit("stepstone", "9", "IT Delivery Manager – Senior", "ACME", "Wien")
        self.assertIsNone(dedup.check_republished(job, ledger, None, self.cfg), "older than 30 days")
        self.assertIsNotNone(dedup.check_republished(job, ledger, None, {**self.cfg, "window_days": 40}))
        ledger = dedup.Ledger()
        seen(ledger, hit("karriere", "1", "Senior IT Delivery Manager", "ACME", "Wien"), reason="location_outside_regions")
        self.assertIsNone(dedup.check_republished(job, ledger, None, self.cfg), "the user never saw the original")
        self.assertIsNone(dedup.check_republished(hit("stepstone", "9", "IT Delivery Manager – Senior", "ACME", "Wien"),
                                                  self.ledger, None, {**self.cfg, "enabled": False}), "switch off")

    def test_same_run_and_chain(self):
        batch = dedup.Batch()
        first = hit("karriere", "50", "Scrum Master (m/w/d)", "Gamma", "Wien")
        batch.add(first)
        self.assertEqual(self.check("Scrum Master – Agile", company="Gamma", batch=batch)["key"], "karriere:50")
        # a republication of a republication points at the first posting
        ledger = dedup.Ledger()
        seen(ledger, hit("karriere", "1", "Tech Lead", "Delta", "Wien"), first_seen="2026-11-01T08:00:00Z")
        seen(ledger, hit("stepstone", "2", "Tech Lead Backend", "Delta", "Wien"),
             republished_of={"key": "karriere:1", "short_id": "3", "title": "Tech Lead"}, reason="republished")
        job = hit("willhaben", "3", "Tech Lead – Backend", "Delta", "Wien")
        self.assertEqual(dedup.check_republished(job, ledger, None, self.cfg)["key"], "karriere:1")

    def test_shipped_schedule_thresholds(self):
        import common
        cfg = dedup.republish_settings(common.load_schedule())
        self.assertEqual((cfg["window_days"], cfg["min_common_words"]), (30, 2))
        self.assertTrue(cfg["enabled"])


class UpstreamHistory(JobbotTestCase):
    """The upstream history must not merge unnamed employers, nor let a circumstantial reject hide a posting."""

    def check(self, job, seen):
        return dedup.check_search_hit(job, dedup.Ledger(), dedup.Upstream(seen), dedup.Batch())

    def test_no_title_only_match_without_a_company(self):
        title = "IT Project Manager (m/w/d)"
        key = dedup.make_key(None, title, "https://www.hays.at/x-111/1")
        self.assertTrue(key.startswith("unknown-company_"))
        seen = {key: {"title": title, "company": None, "url": "https://www.hays.at/x-111/1", "jobbot_reason": None}}
        other_client = hit("michaelpage", "jn-1", title, None, "Wien")
        self.assertIsNone(self.check(other_client, seen), "two unnamed clients with the same title are two postings")
        same_posting = hit("hays", "111", title, None, "Wien", "https://www.hays.at/x-111/1/")
        self.assertEqual(self.check(same_posting, seen), "dup_upstream", "the same URL is still the same posting")

    def test_circumstantial_reject_does_not_hide_another_city(self):
        key = dedup.make_key("Erste Group", "IT Project Manager", "https://a.example/1")
        graz = {"title": "IT Project Manager", "company": "Erste Group", "url": "https://a.example/1"}
        wien = hit("karriere", "2", "IT Project Manager", "Erste Group", "Wien", "https://a.example/2")
        for reason in ("location_outside_regions", "too_old"):
            self.assertIsNone(self.check(wien, {key: {**graz, "jobbot_reason": reason}}), reason)
        self.assertEqual(self.check(wien, {key: {**graz, "jobbot_reason": None}}), "dup_upstream",
                         "a posting that was really seen keeps hiding its company + title")
        self.assertEqual(self.check(wien, {key: {**graz, "jobbot_reason": "freelance"}}), "dup_upstream")


class Retention(JobbotTestCase):
    def setUp(self):
        super().setUp()
        import os
        os.environ["JOBBOT_NOW"] = "2026-11-24T10:00:00Z"

    def test_prune_by_age_status_and_reason(self):
        ledger = dedup.Ledger()
        def add(id_, first_seen, status, reason=None):
            job = hit("karriere", id_, f"Title {id_}", f"Company {id_}", "Wien")
            ledger.add(job["key"], {**job, "first_seen": first_seen, "status": status, "reason": reason})
        add("old-low", "2025-01-01T00:00:00Z", "low")
        add("old-alerted", "2025-01-01T00:00:00Z", "alerted")
        add("old-undated", None, "rejected", "title_excluded")
        add("recent-rejected", "2026-11-01T00:00:00Z", "rejected", "title_excluded")
        add("region-off-old", "2026-11-01T00:00:00Z", "rejected", "location_outside_regions")
        add("region-off-new", "2026-11-20T00:00:00Z", "rejected", "location_outside_regions")
        self.assertEqual(ledger.prune(365, 14), 2)
        self.assertEqual(sorted(e["id"] for e in ledger.jobs.values()),
                         ["old-alerted", "old-undated", "recent-rejected", "region-off-new"])
        self.assertNotIn(dedup.clean_url("https://karriere.example/jobs/old-low"), ledger.by_url, "indexes rebuilt")
        self.assertEqual(ledger.prune(0, 0), 0, "0 switches a window off")

    def test_settings_default_and_schedule(self):
        self.assertEqual(dedup.retention_settings({}), (365, 14))
        self.assertEqual(dedup.retention_settings({"seen_retention_days": 90, "circumstantial_retention_days": "7"}), (90, 7))
        self.assertEqual(dedup.retention_settings({"seen_retention_days": "soon"}), (365, 14))

    def test_revivable_entry_no_longer_hides(self):
        ledger = dedup.Ledger()
        old = hit("karriere", "1", "Tech Lead", "ACME", "Graz")
        ledger.add(old["key"], {**old, "status": "rejected", "reason": "location_outside_regions"})
        again = hit("karriere", "1", "Tech Lead", "ACME", "Graz")
        up, batch = dedup.Upstream(), dedup.Batch()
        self.assertEqual(dedup.check_search_hit(again, ledger, up, batch), "dup_site_id")
        region_on = lambda entry: entry.get("reason") == "location_outside_regions"
        self.assertIsNone(dedup.check_search_hit(again, ledger, up, batch, region_on))
        self.assertEqual(dedup.check_search_hit(again, ledger, up, batch, lambda entry: False), "dup_site_id")


class Qualifiers(JobbotTestCase):
    """A title plus a qualifying word in its main part is another job, not a republication."""

    def setUp(self):
        super().setUp()
        import os
        os.environ["JOBBOT_NOW"] = "2026-11-24T10:00:00Z"
        self.cfg = dedup.republish_settings({})

    def republished(self, old_title, new_title):
        ledger = dedup.Ledger()
        seen(ledger, hit("karriere", "1", old_title, "ACME GmbH", "Wien"))
        return dedup.check_republished(hit("stepstone", "9", new_title, "ACME AG", "Wien"), ledger, None, self.cfg)

    def test_extra_qualifying_word_is_another_job(self):
        for old, new in (("Solution Architect", "Solution Architect SAP"), ("Solution Architect SAP", "Solution Architect"),
                         ("IT Project Manager", "IT Project Manager Infrastructure"),
                         ("DevOps Engineer (m/w/d)", "Cloud DevOps Engineer")):
            with self.subTest(old=old, new=new):
                self.assertIsNone(self.republished(old, new))

    def test_bracketed_or_separated_additions_and_levels_stay_rewordings(self):
        for old, new in (("Solution Architect", "Solution Architect (SAP)"), ("Solution Architect", "Solution Architect – Vienna"),
                         ("Solution Architect", "Senior Solution Architect"), ("Scrum Master (m/w/d)", "Scrum Master, Agile")):
            with self.subTest(old=old, new=new):
                self.assertIsNotNone(self.republished(old, new))

    def test_without_raw_titles_every_extra_word_counts(self):
        norm = dedup.norm_title
        self.assertFalse(dedup.is_reworded(norm("Solution Architect"), norm("Solution Architect SAP"), self.cfg))
        self.assertTrue(dedup.is_reworded(norm("Solution Architect"), norm("Architect – Solution"), self.cfg))


if __name__ == "__main__":
    unittest.main()
