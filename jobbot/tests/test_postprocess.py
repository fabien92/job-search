import json
import os
import unittest
from pathlib import Path

from _env import FakeTelegram, JobbotTestCase
import common
import dedup
import postprocess
import sites

RUN = "20261123T110000"


def job(ref, id_, title, company="ACME GmbH", **kw):
    j = dedup.annotate({"site": "karriere", "id": id_, "title": title, "company": company, "location": "Wien",
                        "date": "2026-11-23", "url": f"https://www.karriere.at/jobs/{id_}", **kw})
    if ref:
        j["ref"] = ref
        j["guard"] = {"ok": True, "alarm": False, "verdict": "posting_guard: clean"}
    return j


class Base(JobbotTestCase):
    def setUp(self):
        super().setUp()
        self.tg = FakeTelegram()
        self.addCleanup(self.tg.close)
        os.environ.update({"JOBBOT_TELEGRAM_API": self.tg.url, "TELEGRAM_TOKEN": "t0k", "TELEGRAM_CHAT_ID": "42",
                           "JOBBOT_NOW": "2026-11-23T10:00:00Z"})
        self.runs = self.tmp / "state" / "runs"
        self.runs.mkdir(parents=True)
        sites.save({"allowed": [{"domain": "karriere.at"}], "denied": [], "pending": []})

    def write_run(self, to_score, rejected=(), scores=None, blocked=()):
        (self.runs / f"{RUN}-prefilter.json").write_text(json.dumps({
            "run_id": RUN, "site": "all", "started": "2026-11-23T10:00:00Z",
            "sites": {"karriere": {"queries": 3, "results": 12, "errors": 0}},
            "rejected": [dict(r) for r in rejected], "to_score": [dict(j) for j in to_score],
            "duplicates": {"dup_site_id": 4}, "blocked_hosts": list(blocked), "errors": []}))
        if scores is not None:
            (self.runs / f"{RUN}-scores.json").write_text(json.dumps({"run_id": RUN, "scores": scores}))
        out = self.tmp / "claude.json"
        out.write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.31,
                                   "permission_denials": [{"tool_name": "WebFetch", "tool_use_id": "x",
                                                           "tool_input": {"url": "https://careers.newco.at/job/1"}}]}))
        return out


class Postprocess(Base):
    def scenario(self):
        rej = job(None, "1", "Head of IT")
        rej["reason"] = "title_excluded"
        to_score = [job("b1", "2", "IT Delivery Manager"), job("b2", "3", "Scrum Master", company="Beta"),
                    job("b3", "4", "DevOps Engineer", company="Gamma"), job("b4", "5", "Unscored", company="Delta")]
        scores = [
            {"ref": "b1", "score": 82, "reject_reason": None, "flags": ["allemand à vérifier"], "contract": "CDI",
             "remote": "hybride", "salary": "ab 60.000 € jährlich", "justification": "Delivery <IT> & CI/CD"},
            {"ref": "b2", "score": 45, "reject_reason": None, "contract": "permanent", "remote": "onsite"},
            {"ref": "b3", "score": 70, "reject_reason": "freelance", "contract": "freelance"},
            {"ref": "zz", "score": 99},
            {"ref": "b4", "score": "high"},
        ]
        return self.write_run(to_score, [rej], scores)

    def test_records_alerts_and_summary(self):
        out = self.scenario()
        summary = postprocess.run(RUN, out, 0, False)
        self.assertEqual(summary["status"], "ok")
        self.assertEqual((summary["scored"], summary["unscored"], summary["alerted"], summary["low"]), (3, 1, 1, 1))
        self.assertEqual(summary["rejected_by_reason"], {"title_excluded": 1, "freelance": 1})
        self.assertEqual(summary["total_cost_usd"], 0.31)
        self.assertEqual(summary["new_pending_hosts"], ["careers.newco.at"])
        # Telegram: one alert, §8 format, escaped, clickable link
        texts = self.tg.texts()
        self.assertEqual(len(texts), 1)
        msg = texts[0]
        self.assertIn('<a href="https://www.karriere.at/jobs/2">IT Delivery Manager</a>', msg)
        self.assertIn("82/100", msg)
        self.assertIn("Delivery &lt;IT&gt; &amp; CI/CD", msg)
        self.assertIn("allemand à vérifier", msg)
        self.assertIn("ab 60.000 € jährlich", msg)
        self.assertIn("Contrat : CDI · Télétravail : hybride", msg)
        self.assertFalse(msg.startswith("[TEST]"))
        # ledger: every recorded job, with reason; unscored b4 left out to be retried
        ledger = dedup.Ledger.load()
        status = {e["id"]: (e["status"], e["reason"]) for e in ledger.jobs.values()}
        self.assertEqual(status, {"1": ("rejected", "title_excluded"), "2": ("alerted", None), "3": ("low", None),
                                  "4": ("rejected", "freelance")})
        self.assertEqual(sorted(e["short_id"] for e in ledger.jobs.values()), ["1", "2", "3", "4"])
        # upstream seen_jobs.json written through scrape_state
        seen = json.loads((self.tmp / "seen_jobs.json").read_text())["seen"]
        self.assertEqual(len(seen), 4)
        self.assertEqual({v["status"] for v in seen.values()}, {"new", "skipped"})
        self.assertEqual(sites.load()["pending"][0]["requested_by"], "https://careers.newco.at/job/1")
        self.assertIn("careers.newco.at", (self.tmp / "state" / "blocked_hosts.log").read_text())
        self.assertTrue((self.runs / f"{RUN}.json").is_file())

    def test_republication_recorded_with_its_original(self):
        rep = job(None, "9", "IT Delivery Manager – Senior", reason="republished",
                  republished_of={"key": "karriere:1", "short_id": "7", "title": "Senior IT Delivery Manager"})
        summary = postprocess.run(RUN, self.write_run([], [rep]), 0, True)
        self.assertEqual(self.tg.texts(), [], "no alert for a republication")
        self.assertEqual(summary["rejected_by_reason"], {"republished": 1})
        entry = dedup.Ledger.load().jobs["karriere:9"]
        self.assertEqual((entry["status"], entry["reason"], entry["republished_of"]["short_id"]),
                         ("rejected", "republished", "7"))

    def test_dry_run_writes_nothing_definitive(self):
        os.environ["JOBBOT_DRY_RUN"] = "1"
        out = self.scenario()
        summary = postprocess.run(RUN, out, 0, False)
        self.assertTrue(summary["dry_run"])
        self.assertFalse((self.tmp / "seen_jobs.json").exists())
        self.assertFalse((self.tmp / "state" / "seen_index.json").exists())
        self.assertFalse((self.tmp / "state" / "telegram_msgs.json").exists())
        self.assertEqual(sites.load()["pending"], [])
        self.assertTrue(self.tg.texts()[0].startswith("[TEST] "))
        self.assertIn("#T", self.tg.texts()[0])
        self.assertTrue(json.loads((self.runs / f"{RUN}.json").read_text())["dry_run"])

    def test_claude_failure_classification(self):
        out = self.write_run([job("b1", "2", "X")], scores=None)
        out.write_text(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                                   "errors": ["Invalid API key · Please run /login"], "total_cost_usd": 0}))
        summary = postprocess.run(RUN, out, 1, False)
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["claude"]["failure"], "auth_or_quota")
        self.assertEqual(dedup.Ledger.load().jobs, {}, "nothing recorded, the job is retried next run")
        out.write_text(json.dumps({"type": "result", "subtype": "error_max_budget_usd", "is_error": True, "total_cost_usd": 2.01}))
        self.assertEqual(postprocess.run(RUN, out, 1, False)["claude"]["failure"], "budget")

    def test_empty_batch_without_claude(self):
        self.write_run([], scores=None)
        summary = postprocess.run(RUN, None, None, True)
        self.assertEqual((summary["status"], summary["claude"]["status"]), ("ok", "skipped"))

    def test_validate_scores(self):
        good, problems = postprocess.validate_scores({"scores": [
            {"ref": "b1", "score": 61.0, "reject_reason": "made_up", "flags": ["x" * 100], "contract": "weird"}]}, {"b1"})
        self.assertEqual(good["b1"]["score"], 61)
        self.assertEqual(good["b1"]["reject_reason"], "other")
        self.assertEqual(good["b1"]["contract"], "unknown")
        self.assertEqual(len(good["b1"]["flags"][0]), 40)
        self.assertEqual(postprocess.validate_scores([], {"b1"})[0], {})


class ModelOutput(Base):
    """Whatever the model writes, postprocess takes the "unscored" path instead of crashing."""

    def test_truncated_scores_file_is_a_failed_run_not_a_crash(self):
        rej = job(None, "1", "Head of IT")
        rej["reason"] = "title_excluded"
        out = self.write_run([job("b1", "2", "IT Delivery Manager")], [rej], scores=None)
        (self.runs / f"{RUN}-scores.json").write_text('{"run_id": "x", "scores": [{"ref": "b1", "sco')
        summary = postprocess.run(RUN, out, 0, False)
        self.assertEqual((summary["status"], summary["scored"], summary["unscored"]), ("failed", 0, 1))
        self.assertIn("scores file unreadable", summary["score_problems"][0])
        ledger = dedup.Ledger.load()
        self.assertEqual([e["id"] for e in ledger.jobs.values()], ["1"], "rule rejects recorded, the unscored job retried")
        self.assertTrue((self.runs / f"{RUN}.json").is_file(), "the run summary is written all the same")

    def test_scores_file_that_is_not_an_object(self):
        out = self.write_run([job("b1", "2", "IT Delivery Manager")], scores=None)
        (self.runs / f"{RUN}-scores.json").write_text('["b1", 80]')
        summary = postprocess.run(RUN, out, 0, False)
        self.assertEqual((summary["status"], summary["unscored"]), ("failed", 1))

    def test_wrongly_typed_fields_never_raise(self):
        weird = [
            {"ref": ["b1"], "score": 80},
            {"ref": {"b": 1}, "score": 80},
            {"ref": "b1", "score": [80]},
            {"ref": "b2", "score": 70, "reject_reason": ["freelance"], "flags": "x", "contract": ["CDI"], "remote": {"a": 1},
             "variant": ["delivery"], "duplicate_of": [3], "salary": 5, "justification": ["x"], "adapt": ["oui"],
             "adapt_reason": {"a": 1}},
            {"ref": "b3", "score": 55, "flags": [["nested"], 3, "ok"], "contract": "CDI", "variant": None},
            "not an object", None, 3,
        ]
        good, problems = postprocess.validate_scores({"scores": weird}, {"b1", "b2", "b3"})
        self.assertEqual(sorted(good), ["b2", "b3"])
        self.assertEqual(len(problems), 6)
        b2 = good["b2"]
        self.assertEqual((b2["reject_reason"], b2["contract"], b2["remote"], b2["variant"], b2["flags"], b2["duplicate_of"]),
                         ("other", "unknown", "unknown", None, [], None))
        self.assertEqual((good["b3"]["flags"], good["b3"]["contract"]), (["ok"], "permanent"))  # a former French code is stored as the English one
        for doc in (None, [], "x", {"scores": "b1"}, {"scores": None}):
            self.assertEqual(postprocess.validate_scores(doc, {"b1"})[0], {})


class Pruning(Base):
    def test_ledger_and_site_stats_pruned_within_the_configured_window(self):
        ledger = dedup.Ledger()
        for id_, first_seen, status, reason in (("90", "2025-01-01T00:00:00Z", "low", None),
                                                ("91", "2026-11-01T00:00:00Z", "rejected", "location_outside_regions"),
                                                ("92", "2025-01-01T00:00:00Z", "alerted", None)):
            old = job(None, id_, f"Old {id_}", company=f"Old {id_}")
            ledger.add(old["key"], {**old, "first_seen": first_seen, "status": status, "reason": reason, "short_id": id_})
        ledger.next_id = 100
        ledger.save()
        (self.tmp / "state" / "site_stats.json").write_text(json.dumps({
            "karriere": {"2025-01-01": {"results": 1, "queries": 1, "errors": 0}, "2026-11-22": {"results": 2, "queries": 1, "errors": 0}},
            "gone": {"2024-06-01": {"results": 0, "queries": 1, "errors": 0}}}))
        summary = postprocess.run(RUN, self.write_run([]), None, True)
        self.assertEqual(summary["ledger_pruned"], 2)
        self.assertEqual(sorted(dedup.Ledger.load().jobs), ["karriere:92"], "alerted postings are kept")
        stats = json.loads((self.tmp / "state" / "site_stats.json").read_text())
        self.assertEqual(sorted(stats), ["karriere"])
        self.assertEqual(sorted(stats["karriere"]), ["2026-11-22", "2026-11-23"])

    def test_window_read_from_schedule(self):
        (self.config / "schedule.yaml").write_text((self.config / "schedule.yaml").read_text()
                                                   + "seen_retention_days: 0\ncircumstantial_retention_days: 0\n")
        ledger = dedup.Ledger()
        old = job(None, "90", "Old", company="Old")
        ledger.add(old["key"], {**old, "first_seen": "2020-01-01T00:00:00Z", "status": "low", "short_id": "90"})
        ledger.save()
        self.assertEqual(postprocess.run(RUN, self.write_run([]), None, True)["ledger_pruned"], 0)


if __name__ == "__main__":
    unittest.main()
