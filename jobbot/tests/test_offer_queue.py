"""V5: Telegram offer queue — one offer shown at a time (offer_queue.py, /file, /voir)."""
import json
import os
import unittest

from _env import FakeTelegram, JobbotTestCase
import applications as apps
import common
import daily
import dedup
import logic
import offer_queue as oq
import postprocess
import sites
from test_postprocess import RUN, Base, job


def make(ledger, score, title=None, company="ACME", **kw):
    sid = ledger.allocate_id()
    n = 100 + int(sid)
    j = dedup.annotate({"site": "karriere", "id": str(n), "title": title or f"Job {sid}", "company": company,
                        "location": "Wien", "url": f"https://www.karriere.at/jobs/{n}"})
    entry = {**j, "short_id": sid, "status": "alerted", "score": score, **kw}
    ledger.add(j["key"], entry)
    return entry


class Queue(JobbotTestCase):
    def setUp(self):
        super().setUp()
        self.tg = FakeTelegram()
        self.addCleanup(self.tg.close)
        os.environ.update({"JOBBOT_TELEGRAM_API": self.tg.url, "TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT_ID": "1",
                           "JOBBOT_NOW": "2026-11-26T09:00:00Z"})
        self.spawned = []

    def seed(self, *scores, test=False, **kw):
        ledger = dedup.Ledger.load()
        entries = [make(ledger, s, **kw) for s in scores]
        ledger.save()
        oq.enqueue(entries, test)
        return [e["short_id"] for e in entries]

    def queue(self, test=False):
        return oq.load(test)

    def test_best_first_then_next_after_no(self):
        a, b, c = self.seed(70, 90, 80)
        oq.pump(False)
        self.assertEqual(self.queue()["current"]["id"], b)
        texts = self.tg.texts()
        self.assertEqual(len(texts), 1)
        self.assertIn(f"#{b} · 90/100", texts[0])
        self.assertIn("📥 2 autre(s) en attente · /file", texts[0])
        msgs = json.loads((self.tmp / "state" / "telegram_msgs.json").read_text())
        self.assertIn(b, msgs, "/go replies to the alert: its message id is recorded")
        self.assertEqual(apps.find_job(b)["message_id"], msgs[b]["message_id"])
        oq.pump(False)
        self.assertEqual(len(self.tg.texts()), 1, "one offer at a time")
        reply = logic.cmd_no(b)
        self.assertIn("Offre suivante", reply)
        self.assertEqual(len(self.tg.texts()), 1, "the next offer waits for the reply (bot: advance after reply)")
        oq.advance()
        self.assertIn(f"#{c} · 80/100", self.tg.texts()[-1])
        self.assertEqual(self.queue()["current"]["id"], c)
        oq.advance()
        self.assertEqual(len(self.tg.texts()), 2, "advance only acts once")

    def test_no_on_waiting_offer_keeps_the_shown_one(self):
        a, b = self.seed(90, 60)
        oq.pump(False)
        self.assertIn("Retirée de la file", logic.cmd_no(b))
        oq.advance()
        q = self.queue()
        self.assertEqual((q["current"]["id"], q["waiting"]), (a, {}))
        self.assertEqual(len(self.tg.texts()), 1)
        self.assertEqual(dedup.Ledger.load().find_short(b)[1]["status"], "rejected")

    def test_no_on_unknown_or_unqueued_offer(self):
        self.assertIn("ID inconnu", logic.cmd_no("999"))
        ledger = dedup.Ledger.load()
        e = make(ledger, 75)
        ledger.save()
        reply = logic.cmd_no(e["short_id"])
        self.assertNotIn("file", reply)
        oq.advance()
        self.assertEqual(self.tg.texts(), [])

    def test_go_keeps_offer_shown_sent_releases_next(self):
        a, b = self.seed(90, 70)
        oq.pump(False)
        logic.cmd_go(a, spawn=self.spawned.append)
        self.assertEqual(len(self.spawned), 1)
        oq.advance()
        self.assertEqual(self.queue()["current"]["id"], a, "/go never releases the next offer")
        apps.save_pending(False, {a: {"id": a, "company": "ACME", "title": "Job 1", "go_at": common.iso(),
                                      "telegram": [], "dir": str(self.tmp / "app")}})
        reply = logic.cmd_sent(a)
        self.assertIn("envoyée", reply)
        oq.advance()
        self.assertEqual(self.queue()["current"]["id"], b)
        self.assertIn(f"#{b} · 70/100", self.tg.texts()[-1])

    def test_cancel_releases_next(self):
        a, b = self.seed(90, 70)
        oq.pump(False)
        logic.cmd_cancel(a)
        oq.advance()
        self.assertEqual(self.queue()["current"]["id"], b)

    def test_go_on_waiting_offer_leaves_the_queue(self):
        a, b = self.seed(90, 70)
        oq.pump(False)
        reply = logic.cmd_go(b, spawn=self.spawned.append)
        self.assertIn("Retirée de la file", reply)
        q = self.queue()
        self.assertEqual((q["current"]["id"], q["waiting"]), (a, {}))

    def test_file_and_voir(self):
        a, b, c = self.seed(90, 70, 80)
        oq.pump(False)
        text = logic.cmd_file()
        self.assertIn(f"Affichée : <b>#{a}</b>", text)
        self.assertLess(text.index(f"#{c}"), text.index(f"#{b}"), "display order: best score first")
        self.assertIn("1. <b>80</b>", text)
        self.assertIn("2. <b>70</b>", text)
        reply = logic.cmd_voir("2")
        self.assertIn(f"#{b} affichée", reply)
        self.assertIn(f"#{b} · 70/100", self.tg.texts()[-1])
        q = self.queue()
        self.assertEqual(q["current"]["id"], b)
        self.assertEqual(set(q["waiting"]), {a, c}, "the shown offer went back to the queue, nothing lost")
        self.assertIn("plus dans la file", logic.cmd_voir("2"), "stale numbering: the offer is shown now")
        self.assertIn("Numéro invalide", logic.cmd_voir("9"))
        self.assertIn("exige un numéro", logic.cmd_voir("x"))

    def test_voir_before_file(self):
        self.seed(90)
        self.assertIn("Fais d'abord /file", logic.cmd_voir("1"))

    def test_voir_does_not_requeue_an_offer_in_go(self):
        a, b = self.seed(90, 70)
        oq.pump(False)
        apps.save_pending(False, {a: {"id": a, "go_at": common.iso()}})
        logic.cmd_file()
        logic.cmd_voir("1")
        q = self.queue()
        self.assertEqual((q["current"]["id"], q["waiting"]), (b, {}), "/pending follows the offer in /go")

    def test_new_offers_while_one_is_shown(self):
        self.postprocess_fixtures()
        ledger_first = self.seed(95)
        oq.pump(False)
        before = len(self.tg.texts())
        to_score = [job("b1", "2", "IT Delivery Manager"), job("b2", "3", "Scrum Master", company="Beta")]
        scores = [{"ref": "b1", "score": 82, "reject_reason": None}, {"ref": "b2", "score": 75, "reject_reason": None}]
        summary = postprocess.run(RUN, self.write_run(to_score, scores=scores), 0, False)
        self.assertEqual((summary["alerted"], summary["alerts_sent"]), (2, 0))
        texts = self.tg.texts()[before:]
        self.assertEqual(texts, ["📥 2 nouvelle(s) offre(s), 2 en attente · /file"])
        self.assertEqual(self.queue()["current"]["id"], ledger_first[0])

    write_run = Base.write_run

    def postprocess_fixtures(self):
        self.runs = self.tmp / "state" / "runs"
        self.runs.mkdir(parents=True, exist_ok=True)
        sites.save({"allowed": [{"domain": "karriere.at"}], "denied": [], "pending": []})

    def test_postprocess_shows_best_when_idle(self):
        self.postprocess_fixtures()
        to_score = [job("b1", "2", "IT Delivery Manager"), job("b2", "3", "Scrum Master", company="Beta")]
        scores = [{"ref": "b1", "score": 72, "reject_reason": None}, {"ref": "b2", "score": 88, "reject_reason": None}]
        summary = postprocess.run(RUN, self.write_run(to_score, scores=scores), 0, False)
        self.assertEqual(summary["alerts_sent"], 1)
        texts = self.tg.texts()
        self.assertEqual(len(texts), 1)
        self.assertIn("Scrum Master", texts[0])
        self.assertIn("📥 1 autre(s) en attente", texts[0])

    def test_queue_survives_restart_on_disk(self):
        a, b = self.seed(90, 70)
        raw = json.loads((self.tmp / "state" / "offer_queue.json").read_text())
        self.assertEqual(set(raw["waiting"]), {a, b})
        self.assertEqual(raw["waiting"][a]["entry"]["score"], 90)

    def test_past_deadline_removed_and_reported(self):
        a, = self.seed(90)
        oq.pump(False)
        b, = self.seed(80, valid_through="2026-11-25")
        c, = self.seed(70, valid_through="2026-12-31")
        d, = self.seed(60)  # no deadline: never removed
        logic.cmd_no(a)
        oq.advance()
        text = self.tg.texts()[-1]
        self.assertIn(f"#{c} · 70/100", text)
        self.assertIn("⌛ 1 offre(s) retirée(s) de la file (date limite dépassée)", text)
        self.assertIn(f"#{b}", text)
        self.assertEqual(set(self.queue()["waiting"]), {d})
        self.assertEqual(self.queue()["expired"], [], "reported once")
        events = apps.read_events()
        self.assertEqual([(e["kind"], e["id"]) for e in events if e["kind"] == "queue_expired"], [("queue_expired", b)])

    def test_offer_waiting_long_gets_a_warning(self):
        os.environ["JOBBOT_NOW"] = "2026-11-10T09:00:00Z"
        self.seed(90)
        os.environ["JOBBOT_NOW"] = "2026-11-26T09:00:00Z"
        oq.pump(False)
        self.assertIn("⚠️ En attente depuis 16 j 0 h : vérifier qu'elle est toujours en ligne.", self.tg.texts()[-1])

    def test_closed_meanwhile_is_skipped(self):
        a, b = self.seed(90, 70)
        with common.state_lock():
            apps.set_ledger_status(a, "cancelled")
        oq.pump(False)
        self.assertEqual(self.queue()["current"]["id"], b)

    def test_test_ids_use_their_own_queue(self):
        real, = self.seed(85)
        oq.pump(False)
        entries = [{"short_id": "T1", "score": 90, "title": "Test A", "company": "X", "url": "https://x/1", "site": "karriere"},
                   {"short_id": "T2", "score": 70, "title": "Test B", "company": "Y", "url": "https://x/2", "site": "karriere"}]
        common.atomic_write_json(common.runs_dir() / f"{RUN}-test-alerts.json",
                                 {"run_id": RUN, "jobs": {e["short_id"]: e for e in entries}})
        oq.enqueue(entries, True)
        oq.pump(True)
        self.assertTrue(self.tg.texts()[-1].startswith("[TEST] "))
        rules = self.config / "rejection-rules.md"
        before = rules.read_text() if rules.exists() else None
        reply = logic.cmd_no("T1 motif de test")
        self.assertIn("aucune règle écrite", reply)
        self.assertEqual(rules.read_text() if rules.exists() else None, before)
        oq.advance()
        self.assertIn("[TEST] <b>#T2", self.tg.texts()[-1])
        self.assertEqual(self.queue()["current"]["id"], real, "the real queue did not move")
        self.assertIsNotNone(apps.find_job("T2")["message_id"], "/go T2 replies to its alert")

    def test_status_and_daily_recap(self):
        a, b = self.seed(90, 70)
        oq.pump(False)
        line = f"📬 Offre affichée : #{a} ACME"
        self.assertIn(line, logic.cmd_status())
        self.assertIn("1 en attente — /file", logic.cmd_status())
        recap = daily.build(None)
        self.assertIn(line, recap)
        self.assertEqual(len([t for t in self.tg.texts() if "/100" in t]), 1, "the recap shows nothing again")


class Backfill(Queue):
    """V5 one-time backfill: alerts sent before the queue existed, still open, join it."""

    def old_alerts(self):
        ledger = dedup.Ledger.load()
        old = [make(ledger, 70, first_seen="2026-11-24T10:00:00Z"),
               make(ledger, 85, first_seen="2026-11-25T10:00:00Z"),
               make(ledger, 90, status="rejected"),
               make(ledger, 75),  # will be in /go
               make(ledger, 95, valid_through="2026-11-20"),  # deadline passed
               make(ledger, 40, status="low")]
        ledger.save()
        apps.save_pending(False, {old[3]["short_id"]: {"short_id": old[3]["short_id"]}})
        return [e["short_id"] for e in old]

    def test_preview_changes_nothing(self):
        a, b, *_ = self.old_alerts()
        res = oq.backfill(preview=True)
        self.assertEqual(len(res["added"]), 2)
        self.assertTrue(res["added"][0].startswith(f"#{b} "), "best score first")
        self.assertFalse(oq.queue_path(False).exists())
        self.assertEqual(self.tg.texts(), [])

    def test_backfill_queues_open_alerts_and_shows_the_best(self):
        a, b, *_ = self.old_alerts()
        res = oq.backfill()
        self.assertEqual(len(res["added"]), 2)
        q = self.queue()
        self.assertEqual(q["current"]["id"], b)
        self.assertEqual(list(q["waiting"]), [a])
        self.assertEqual(q["waiting"][a]["queued_at"], "2026-11-24T10:00:00Z", "age = first alert")
        texts = self.tg.texts()
        self.assertEqual(len(texts), 1)
        self.assertIn(f"#{b} · 85/100", texts[0])
        self.assertIn("1 autre(s) en attente", texts[0])
        self.assertEqual(oq.backfill()["added"], [], "a second run adds nothing")
        self.assertEqual(len(self.tg.texts()), 1)
        logic.cmd_no(b)
        oq.advance()
        self.assertIn(f"#{a} · 70/100", self.tg.texts()[-1])

    def test_backfill_while_an_offer_is_shown(self):
        (new,) = self.seed(99)
        oq.pump(False)
        a, b, *_ = self.old_alerts()
        res = oq.backfill()
        self.assertIsNone(res["shown"])
        q = self.queue()
        self.assertEqual(q["current"]["id"], new)
        self.assertEqual(set(q["waiting"]), {a, b})
        self.assertEqual(len(self.tg.texts()), 1)


if __name__ == "__main__":
    unittest.main()
