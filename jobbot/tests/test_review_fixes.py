"""Regression tests for the pre-publication review (bot, Telegram sender, queue, tracker, contacts)."""
import asyncio
import http.client
import json
import os
from unittest import mock

from _env import FakeTelegram, JobbotTestCase
import applications as apps
import common
import companies
import contacts
import dedup
import followup
import i18n
import logic
import offer_queue as oq
import spontaneous
import telegram_send as tg
from test_offer_queue import make
from test_spontaneous import Base as SpontBase, output


def tracker_rows():
    return apps.read_tracker()[1]


class Tracker(JobbotTestCase):
    def test_go_12_then_go_1_keeps_two_rows(self):
        job12 = {"company": "Acme", "title": "IT Manager", "url": "https://a.example/12", "score": 80}
        job1 = {"company": "Beta", "title": "Tech Lead", "url": "https://b.example/1", "score": 70}
        self.assertEqual(apps.tracker_drafted("12", job12, "cv12.pdf"), "added")
        self.assertEqual(apps.tracker_drafted("1", job1, "cv1.pdf"), "added")
        rows = tracker_rows()
        self.assertEqual([(r["company"], r["cv_file"], r["notes"]) for r in rows],
                         [("Acme", "cv12.pdf", "jobbot #12"), ("Beta", "cv1.pdf", "jobbot #1")])
        self.assertEqual(apps.tracker_set_status("1", job1, "applied", ("drafted",)), "drafted")
        self.assertEqual([r["status"] for r in tracker_rows()], ["drafted", "applied"])
        self.assertEqual(apps.tracker_drafted("1", job1, "cv1b.pdf"), "updated")
        self.assertEqual(tracker_rows()[0]["cv_file"], "cv12.pdf")

    def test_formula_cells_are_neutralised_and_still_match(self):
        job = {"company": "=HYPERLINK(\"http://x\")", "title": "+Lead", "url": "https://a.example/3", "score": 80}
        apps.tracker_drafted("3", job, "cv.pdf")
        raw = common.tracker_path().read_text(encoding="utf-8")
        self.assertIn("'=HYPERLINK", raw)
        self.assertIn("'+Lead", raw)
        self.assertNotIn("\n=", raw)
        row = tracker_rows()[0]
        self.assertEqual((row["company"], row["role"]), (job["company"], "+Lead"), "read back as written")
        # matched by company + role (no marker): the same open row is refreshed, not duplicated
        self.assertEqual(apps.tracker_drafted("4", job, "cv4.pdf"), "updated")
        self.assertEqual(len(tracker_rows()), 1)

    def test_contacts_csv_is_neutralised_and_round_trips(self):
        rows = [{"id": "S1", "company": "@cme", "contact": "=cmd|' /C calc'!A0", "email": "+x@acme.at",
                 "status": "sent"}]
        with common.state_lock():
            contacts.save(rows)
        raw = contacts.path(False).read_text(encoding="utf-8")
        for cell in ("'@cme", "'=cmd", "'+x@acme.at"):
            self.assertIn(cell, raw)
        row = contacts.get("S1")
        self.assertEqual((row["company"], row["email"]), ("@cme", "+x@acme.at"))
        self.assertIsNotNone(contacts.already_contacted(contacts.load(), "+X@acme.at", None))

    def test_overflow_row_aborts_the_rewrite(self):
        path = common.tracker_path()
        original = (",".join(apps.TRACKER_HEADER) + "\n"
                    "2026-11-20,Acme,,IT Manager,,portal,drafted,,80,jobbot #7,cv.pdf,,https://a.example/7,,extra,cells\n")
        path.write_text(original, encoding="utf-8")
        with self.assertRaises(apps.TrackerMalformed) as ctx:
            apps.tracker_set_status("7", {"company": "Acme", "title": "IT Manager"}, "applied", ("drafted",))
        self.assertEqual(path.read_text(encoding="utf-8"), original, "nothing rewritten, nothing lost")
        text = logic.error_text(ctx.exception)
        self.assertIn("ligne 2", text)
        self.assertIn("Acme", text)


class NoTwice(JobbotTestCase):
    def test_second_no_does_not_add_a_rule(self):
        ledger = dedup.Ledger()
        entry = make(ledger, 80)
        ledger.save()
        sid = entry["short_id"]
        self.assertIn("rejetée", logic.cmd_no(f"{sid} trop loin"))
        rules = (self.config / "rejection-rules.md").read_text()
        self.assertIn("déjà rejetée", logic.cmd_no(f"{sid} trop loin vraiment"))
        self.assertEqual((self.config / "rejection-rules.md").read_text(), rules)


class Auth(JobbotTestCase):
    @staticmethod
    def update(chat, user, edited=False):
        from telegram import Chat, Message, Update, User
        import datetime as dt

        msg = Message(1, dt.datetime(2026, 11, 26, tzinfo=dt.timezone.utc), Chat(chat, "group"),
                      from_user=User(user, "x", False), text="/status")
        return Update(1, edited_message=msg) if edited else Update(1, message=msg)

    def test_user_id_restricts_commands_and_edits_never_run(self):
        import bot

        anyone = bot.chat_filter("-100", None, edited=False)
        self.assertTrue(anyone.check_update(self.update(-100, 7)))
        self.assertTrue(anyone.check_update(self.update(-100, 8)), "unset: chat-id behaviour unchanged")
        self.assertFalse(anyone.check_update(self.update(-200, 7)))
        self.assertFalse(anyone.check_update(self.update(-100, 7, edited=True)), "an edit is not a command")
        owner = bot.chat_filter("-100", "7", edited=False)
        self.assertTrue(owner.check_update(self.update(-100, 7)))
        self.assertFalse(owner.check_update(self.update(-100, 8)))
        self.assertFalse(owner.check_update(self.update(-100, 7, edited=True)))

    def test_handlers_carry_the_user_and_refuse_edits(self):
        import bot
        from telegram.ext import CommandHandler

        app = bot.build("123:abc", "-100", "7")
        cmds = [h for h in app.handlers[0] if isinstance(h, CommandHandler)]
        self.assertTrue(cmds)
        for h in cmds:
            self.assertEqual((h.filters.only_user, h.filters.edited), (7, False), h.commands)
            self.assertFalse(h.check_update(self.update(-100, 8)))

    def test_button_from_another_user_is_ignored(self):
        import bot

        class Chat:
            id = -100

        class User:
            id = 8

        class Query:
            data = "purge:S1"

            async def answer(self):
                raise AssertionError("another user must be ignored before answering")

        class Upd:
            effective_chat = Chat()
            effective_user = User()
            callback_query = Query()

        asyncio.run(bot.button_handler("-100", "7")(Upd(), None))

    def test_start_up_checks(self):
        import bot

        common.secrets_path().write_text("TELEGRAM_TOKEN=123:abc\nTELEGRAM_CHAT_ID=-100\nTELEGRAM_USER_ID=me\n")
        with self.assertLogs("jobbot.bot", "ERROR"):
            self.assertEqual(bot.main(), 1, "a mistyped user id never means 'everyone'")
        common.secrets_path().write_text("TELEGRAM_TOKEN=123:abc\nTELEGRAM_CHAT_ID=-100\n")
        app = mock.Mock()
        with mock.patch.object(bot, "build", return_value=app) as build, self.assertLogs("jobbot.bot", "WARNING") as logs:
            self.assertEqual(bot.main(), 0)
        build.assert_called_once_with("123:abc", "-100", None)
        self.assertTrue(any("every member" in line for line in logs.output))
        self.assertEqual(common.load_secrets().get("TELEGRAM_USER_ID"), None)
        os.environ["TELEGRAM_USER_ID"] = "7"
        self.addCleanup(lambda: os.environ.pop("TELEGRAM_USER_ID", None))
        self.assertEqual(common.load_secrets()["TELEGRAM_USER_ID"], "7")


class Sender(JobbotTestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeTelegram()
        self.addCleanup(self.fake.close)
        os.environ.update({"TELEGRAM_TOKEN": "123456:SECRET-token", "TELEGRAM_CHAT_ID": "42",
                           "JOBBOT_NOW": "2026-11-24T08:00:00Z"})

    def state_text(self):
        return "".join(p.read_text(encoding="utf-8", errors="replace")
                       for p in common.state_dir().rglob("*") if p.is_file())

    def test_token_never_reaches_the_outbox(self):
        os.environ["JOBBOT_TELEGRAM_API"] = "no-scheme.example"  # urllib names the whole URL in its error
        self.assertEqual(tg.send_status("hello"), (None, tg.QUEUED))
        self.assertIn("hello", tg.queue_path().read_text())
        self.assertNotIn("SECRET-token", self.state_text())
        self.assertEqual(tg.redact("x/bot123456:SECRET-token/y", "123456:SECRET-token"), "x/bot<token>/y")

    def test_broken_replies_are_queued_not_raised(self):
        os.environ["JOBBOT_TELEGRAM_API"] = "http://127.0.0.1:9"
        for error in (http.client.IncompleteRead(b""), http.client.InvalidURL("bad /bot123456:SECRET-token/"),
                      json.JSONDecodeError("x", "<html>", 0)):
            with mock.patch("urllib.request.urlopen", side_effect=error):
                outcome, _, text = tg.api_request("sendMessage", {"text": "x"}, "123456:SECRET-token")
            self.assertEqual(outcome, tg.RETRYABLE)
            self.assertNotIn("SECRET-token", text)
        with mock.patch("urllib.request.urlopen", side_effect=http.client.IncompleteRead(b"")):
            self.assertEqual(tg.send_status("later"), (None, tg.QUEUED))

    def test_busy_outbox_never_raises(self):
        os.environ["JOBBOT_TELEGRAM_API"] = self.fake.down_url
        with mock.patch.object(tg, "_lock", side_effect=common.LockBusy("x")):
            self.assertEqual(tg.send_status("lost?"), (None, tg.DROPPED))
        self.assertIn("lost?", (common.state_dir() / "telegram_dropped.log").read_text())
        with mock.patch.object(tg, "_chunks", side_effect=RuntimeError("boom")):
            self.assertIsNone(tg.send("x"))

    def test_statuses(self):
        os.environ["JOBBOT_TELEGRAM_API"] = self.fake.url
        mid, status = tg.send_status("ok")
        self.assertTrue(mid)
        self.assertEqual(status, tg.SENT)
        self.fake.statuses = [400]
        self.assertEqual(tg.send_status("<b>broken"), (None, tg.DROPPED))


class QueueRetry(JobbotTestCase):
    def setUp(self):
        super().setUp()
        self.tg = FakeTelegram()
        self.addCleanup(self.tg.close)
        os.environ.update({"JOBBOT_TELEGRAM_API": self.tg.url, "TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT_ID": "1",
                           "JOBBOT_NOW": "2026-11-26T09:00:00Z"})

    def test_refused_alert_goes_back_and_does_not_block_the_queue(self):
        ledger = dedup.Ledger.load()
        best, other = make(ledger, 90), make(ledger, 70)
        ledger.save()
        oq.enqueue([best, other], False)
        self.tg.statuses = [400]
        self.assertIsNone(oq.pump(False))
        q = oq.load(False)
        self.assertIsNone(q["current"], "the user saw nothing: no offer is 'shown'")
        self.assertEqual(set(q["waiting"]), {best["short_id"], other["short_id"]})
        self.assertTrue(q["advance"])
        oq.advance()  # the next command retries: the other offer goes first
        q = oq.load(False)
        self.assertEqual(q["current"]["id"], other["short_id"])
        self.assertIn(f"#{other['short_id']} · 70/100", self.tg.texts()[-1])
        self.assertEqual(set(q["waiting"]), {best["short_id"]})

    def test_queued_alert_stays_shown(self):
        ledger = dedup.Ledger.load()
        entry = make(ledger, 90)
        ledger.save()
        oq.enqueue([entry], False)
        os.environ["JOBBOT_TELEGRAM_API"] = self.tg.down_url
        self.assertIsNone(oq.pump(False))
        self.assertEqual(oq.load(False)["current"]["id"], entry["short_id"], "it will be delivered from the outbox")


class Reminders(JobbotTestCase):
    def setUp(self):
        super().setUp()
        os.environ["JOBBOT_NOW"] = "2026-12-10T09:00:00Z"
        with common.state_lock():
            contacts.save([{"id": "S1", "company": "ACME GmbH", "contact": "Anna Muster", "email": "a@acme.at",
                            "status": "sent", "sent": "2026-11-20T09:00:00Z"}])

    def test_marked_only_once_delivered(self):
        seen = []
        self.assertEqual(followup.send_reminders(False, lambda item: seen.append(item["id"]) or False), 0)
        self.assertEqual(seen, ["S1"])
        self.assertEqual(followup.load_state(False)["reminded"], {}, "refused message: retried at the next run")

        def crash(item):
            raise RuntimeError("killed before sending")

        with self.assertRaises(RuntimeError):
            followup.send_reminders(False, crash)
        self.assertEqual(followup.load_state(False)["reminded"], {})
        self.assertEqual(followup.send_reminders(False, lambda item: True), 1)
        self.assertIn("S1", followup.load_state(False)["reminded"])
        self.assertEqual(followup.send_reminders(False, lambda item: True), 0, "one reminder per quiet period")


class CorruptState(JobbotTestCase):
    def test_language_survives_a_corrupt_settings_file(self):
        i18n.settings_path().write_text("{\"lang\": ")
        self.assertEqual(i18n.lang(), "fr")  # JOBBOT_LANG of the tests
        self.assertIn("Erreur", logic.t("bot.error", name="X"))
        i18n.set_lang("en")
        self.assertEqual(i18n.lang(), "en")

    def test_corrupt_queue_or_pending_names_the_file(self):
        for path, command in ((oq.queue_path(False), logic.cmd_file), (apps.pending_path(False), logic.cmd_pending)):
            path.write_text("")
            with self.assertRaises(common.CorruptState) as ctx:
                command()
            text = logic.error_text(ctx.exception)
            self.assertIn(path.name, text)
            self.assertIn("illisible", text)
            path.unlink()

    def test_bot_reports_a_corrupt_queue_after_the_reply(self):
        import bot

        oq.queue_path(False).write_text("{")
        sent = []

        class Message:
            async def reply_text(self, text, **kw):
                sent.append(text)

        class Upd:
            effective_message = Message()

        class Ctx:
            args = []

        asyncio.run(bot.handler(logic.cmd_help, False)(Upd(), Ctx()))
        self.assertEqual(len(sent), 2)
        self.assertIn("offer_queue.json", sent[1])

    def test_atomic_write_syncs_before_replacing(self):
        calls = []
        real = os.replace
        with mock.patch.object(os, "fsync", side_effect=lambda fd: calls.append("fsync")), \
                mock.patch.object(os, "replace", side_effect=lambda a, b: (calls.append("replace"), real(a, b))):
            common.atomic_write_json(common.state_dir() / "x.json", {"a": 1})
        self.assertEqual(calls, ["fsync", "replace"])


class ScanProbe(JobbotTestCase):
    def test_probe_sees_a_scan_without_taking_its_lock(self):
        self.assertFalse(common.scan_running())
        with common.scan_lock():
            pid = (common.state_dir() / ".scan.lock").read_text()
            self.assertTrue(common.scan_running())
            self.assertEqual((common.state_dir() / ".scan.lock").read_text(), pid, "the probe never writes")
            self.assertIn("en cours", logic.cmd_search("all", spawn=lambda argv: self.fail("must not spawn")))
        self.assertFalse(common.scan_running())

    def test_a_starting_scan_waits_out_a_probe(self):
        import fcntl
        import threading

        path = common.state_dir() / ".scan.lock"
        probe = open(path, "a+")
        fcntl.flock(probe, fcntl.LOCK_SH)  # a probe caught in the middle of its check
        threading.Timer(0.3, probe.close).start()
        with common.scan_lock():  # the old non-blocking lock gave up here: the scan was skipped
            pass


class SpontDraft(SpontBase):
    def test_crash_leaves_no_draft_row(self):
        with mock.patch.object(spontaneous, "validate", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                self.spont(output())
        self.assertEqual(contacts.load(), [])
        self.assertNotIn("déjà contactée", logic.cmd_spont("ACME GmbH", spawn=lambda argv: None))

    def test_unreadable_output_is_reported_not_raised(self):
        os.environ["FAKE_V3_OUTPUT"] = "{not json"
        self.assertEqual(spontaneous.run("ACME GmbH", fetcher=self.fetcher()), 1)
        self.assertEqual(contacts.load(), [])
        self.assertIn("ACME GmbH", self.texts())

    def test_leftover_draft_row_does_not_mark_the_company_contacted(self):
        with common.state_lock():
            contacts.save([{"id": "S1", "company": "ACME GmbH", "status": "draft"}])
        self.assertNotIn(companies.key_of("ACME GmbH"), companies.contacted_keys())
        self.assertEqual(self.spont(output()), 0)
        self.assertEqual(contacts.get("S2")["status"], "prepared")
