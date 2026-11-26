"""V5: follow-up reminders, /reply, keep or purge a contact (followup.py) — network-free."""
import asyncio
import os
import unittest
from unittest import mock

from _env import FakeTelegram, JobbotTestCase
import applications as apps
import common
import contacts
import daily
import dedup
import followup
import logic
import weekly


def at(day: str) -> None:
    os.environ["JOBBOT_NOW"] = f"{day}T07:00:00Z"


class FollowupBase(JobbotTestCase):
    def setUp(self):
        super().setUp()
        at("2026-11-25")
        self.tg = FakeTelegram()
        self.addCleanup(self.tg.close)
        os.environ.update({"JOBBOT_TELEGRAM_API": self.tg.url, "TELEGRAM_TOKEN": "x", "TELEGRAM_CHAT_ID": "1"})

    def seed_offer(self, company="ACME GmbH", title="IT Delivery Manager", job_id="1") -> str:
        """An alerted posting, /go done (drafted + pending), ready for /sent."""
        ledger = dedup.Ledger.load()
        sid = ledger.allocate_id()
        job = dedup.annotate({"site": "karriere", "id": job_id, "title": title, "company": company, "location": "Wien",
                              "url": f"https://www.karriere.at/jobs/{job_id}"})
        ledger.add(job["key"], {**job, "short_id": sid, "status": "drafted", "score": 80})
        ledger.save()
        apps.tracker_drafted(sid, {**job, "score": 80}, "cv.pdf")
        pending = apps.load_pending(False)
        pending[sid] = {"id": sid, "company": company, "title": title, "url": job["url"],
                        "dir": str(self.tmp / "applications" / "x"), "telegram": []}
        apps.save_pending(False, pending)
        return sid

    def row(self, sid):
        return next(r for r in apps.read_tracker()[1] if f"jobbot #{sid}" in r["notes"])

    def seed_contact(self, cid="S1", status="sent", sent="2026-11-25T08:00:00Z", test=False):
        folder = (self.tmp / "cache" / "test-spontaneous" if test else self.tmp / "spontaneous") / "beta"
        folder.mkdir(parents=True, exist_ok=True)
        for name in ("email.txt", "linkedin.txt", f"{cid}_beta_CV.pdf"):
            (folder / name).write_text("x")
        contacts.save([{"id": cid, "company": "Beta AG", "contact": "Anna Muster", "role": "CIO",
                        "email": "Anna@Beta.at", "email_source": "https://beta.at/impressum",
                        "linkedin": "https://www.linkedin.com/in/anna/", "linkedin_source": "https://beta.at/team",
                        "folder": str(folder), "prepared": "2026-11-24T08:00:00Z", "sent": sent, "status": status}],
                      test)
        return folder


class OfferReminders(FollowupBase):
    def test_only_sent_and_unanswered_after_ten_days(self):
        sent, drafted = self.seed_offer(job_id="1"), self.seed_offer(company="Other", job_id="2")
        logic.cmd_sent(sent)
        self.assertEqual(self.row(sent)["status"], "applied")
        at("2026-12-04")  # 9 days
        self.assertEqual(followup.due_items(False), [])
        at("2026-12-05")
        due = followup.due_items(False)
        self.assertEqual([i["id"] for i in due], [sent])  # the drafted one is never chased
        self.assertEqual((due[0]["days"], due[0]["followups"], due[0]["exhausted"]), (10, 0, False))
        self.assertNotIn(drafted, [i["id"] for i in due])

    def test_applied_by_hand_without_sent_gets_no_reminder(self):
        sid = self.seed_offer()
        header, rows = apps.read_tracker()
        rows[0]["status"] = "applied"  # e.g. /outcome, without /sent
        apps.write_tracker(header, rows)
        at("2026-12-30")
        self.assertEqual(followup.due_items(False), [])
        self.assertTrue(sid)

    def test_one_reminder_per_quiet_period_and_outcome_resets_the_clock(self):
        sid = self.seed_offer()
        logic.cmd_sent(sid)
        at("2026-12-05")
        self.assertEqual(daily.send_reminders(), 1)
        msg = [p for m, p in self.tg.calls if m == "sendMessage"][-1]
        self.assertIn(f"/outcome followup ACME GmbH", msg["text"])
        self.assertIn(f"/reply {sid} oui|non", msg["text"])
        datas = [b["callback_data"] for row in msg["reply_markup"]["inline_keyboard"] for b in row]
        self.assertEqual(datas, [f"fu:{sid}", f"reply:{sid}:yes", f"reply:{sid}:no"])
        self.assertEqual(daily.send_reminders(), 0)  # same period: not again
        self.assertIn(f"#{sid}", "\n".join(daily.followup_lines()))  # but still listed in the recap
        # /outcome followup logs it in its own format: clock reset, no reminder for 10 days
        header, rows = apps.read_tracker()
        rows[0]["notes"] += "; followed up 2026-12-06"
        apps.write_tracker(header, rows)
        at("2026-12-15")
        self.assertEqual(daily.send_reminders(), 0)
        at("2026-12-16")
        items = followup.take_reminders(False)
        self.assertEqual([(i["followups"], i["exhausted"]) for i in items], [(1, False)])

    def test_follow_up_button_logs_the_outcome_marker_and_caps_at_two(self):
        sid = self.seed_offer()
        logic.cmd_sent(sid)
        at("2026-12-05")
        self.assertIn("1/2", logic.followup_done(sid))
        self.assertIn("déjà notée", logic.followup_done(sid))  # idempotent the same day
        notes = self.row(sid)["notes"]
        self.assertIn("followed up 2026-12-05", notes)
        self.assertNotIn(",", notes)
        at("2026-12-15")
        self.assertIn("la dernière", logic.followup_done(sid))
        self.assertEqual(followup.followups_sent(self.row(sid)["notes"]), 2)
        at("2026-12-25")
        items = followup.take_reminders(False)
        self.assertEqual([i["exhausted"] for i in items], [True])
        text, rows = logic.reminder_message(items[0])
        self.assertIn("Plus aucun rappel", text)
        self.assertIn("/outcome ACME GmbH", text)
        self.assertNotIn("fu:", str(rows))
        self.assertEqual(followup.take_reminders(False), [])
        self.assertEqual(daily.followup_lines(), [])  # exhausted: no longer counted as due
        self.assertEqual(self.row(sid)["status"], "applied")  # never closed automatically


class Reply(FollowupBase):
    def test_requires_id_and_answer(self):
        for bad in ("", "12", "12 maybe", "oui", "1 2 oui"):
            self.assertIn("/reply", logic.cmd_reply(bad), bad)
        self.assertIn("ID inconnu", logic.cmd_reply("99 oui"))

    def test_yes_moves_to_interview_and_stops_reminders(self):
        sid = self.seed_offer()
        self.assertIn("/sent", logic.cmd_reply(f"{sid} oui"))  # drafted: never sent
        logic.cmd_sent(sid)
        header_before = apps.read_tracker()[0]
        text = logic.cmd_reply(f"{sid} oui")
        self.assertIn("applied → interview", text)
        self.assertIn("/outcome ACME GmbH", text)
        row = self.row(sid)
        self.assertEqual(row["status"], "interview")
        self.assertIn("reply yes 2026-11-25", row["notes"])
        self.assertEqual(apps.read_tracker()[0], header_before)
        self.assertEqual(dedup.Ledger.load().find_short(sid)[1]["status"], "replied")
        self.assertEqual([e["answer"] for e in apps.read_events() if e["kind"] == "reply"], ["yes"])
        at("2026-12-30")
        self.assertEqual(followup.due_items(False), [])
        self.assertIn("déjà", logic.cmd_reply(f"{sid} yes"))
        self.assertIn("interview → rejected", logic.cmd_reply(f"{sid} non"))
        self.assertIn("close", logic.cmd_reply(f"{sid} oui"))

    def test_no_moves_to_rejected_and_weekly_counts_it(self):
        sid = self.seed_offer()
        logic.cmd_sent(sid)
        text, buttons = logic.reply_button(f"{sid}:no")
        self.assertIn("applied → rejected", text)
        self.assertEqual(buttons, [])
        self.assertEqual(weekly.collect()["replies"], {"yes": 0, "no": 1, "followups": 0})
        self.assertIn("refus 1", weekly.build())

    def test_test_ids_never_touch_the_tracker(self):
        pending = apps.load_pending(True)
        pending["T5"] = {"id": "T5", "company": "Beta", "title": "Tech Lead", "url": "https://x.at/5", "telegram": [],
                         "dir": str(self.tmp / "cache" / "x")}
        apps.save_pending(True, pending)
        common.atomic_write_json(common.runs_dir() / "20261124T090000-test-alerts.json",
                                 {"jobs": {"T5": {"short_id": "T5", "title": "Tech Lead", "company": "Beta"}}})
        logic.cmd_sent("T5")
        at("2026-12-05")
        items = followup.take_reminders(True)
        self.assertEqual([i["id"] for i in items], ["T5"])
        self.assertTrue(logic.reminder_message(items[0])[0].startswith("[TEST] "))
        self.assertIn("1/2", logic.followup_done("T5"))
        self.assertIn("[TEST]", logic.cmd_reply("T5 oui"))
        self.assertFalse(common.tracker_path().exists())
        self.assertEqual(apps.read_events(), [])
        self.assertEqual(followup.due_items(True), [])


class Contacts(FollowupBase):
    def test_spont_reminder_asks_keep_question(self):
        self.seed_contact()
        at("2026-12-05")
        items = followup.take_reminders(False)
        self.assertEqual([(i["id"], i["kind"]) for i in items], [("S1", "spont")])
        text, rows = logic.reminder_message(items[0])
        self.assertIn("Garder ce contact", text)
        self.assertIn("Anna Muster", text)
        self.assertEqual([b[1] for b in rows[-1]], ["keep:S1", "purge:S1"])
        self.assertIn("1/2", logic.followup_done("S1"))
        self.assertEqual(contacts.get("S1")["followup"], "2026-12-05")
        self.assertEqual(followup.due_items(False), [])

    def test_prepared_contact_is_never_chased(self):
        self.seed_contact(status="prepared", sent="")
        at("2026-12-30")
        self.assertEqual(followup.due_items(False), [])
        self.assertIn("rien à décider", logic.contact_purge("S1"))

    def test_reply_then_keep(self):
        self.seed_contact()
        text, buttons = logic.cmd_reply_view("S1 oui")
        self.assertIn("Garder ce contact", text)
        self.assertEqual([b[1] for b in buttons], ["keep:S1", "purge:S1"])
        row = contacts.get("S1")
        self.assertEqual((row["status"], row["response"]), ("replied", "yes 2026-11-25"))
        self.assertIn("gardé", logic.contact_keep("S1"))
        self.assertEqual(contacts.get("S1")["kept"], "2026-11-25")
        self.assertIn("déjà gardé", logic.contact_keep("S1"))
        self.assertIn("déjà", logic.cmd_reply("S1 non"))
        at("2026-12-30")
        self.assertEqual(followup.due_items(False), [])

    def test_purge_keeps_fingerprints_and_never_proposes_again(self):
        folder = self.seed_contact()
        text = logic.contact_purge("S1")
        self.assertIn("email.txt, linkedin.txt", text)
        row = contacts.get("S1")
        for key in contacts.PERSONAL:
            self.assertEqual(row[key], "", key)
        self.assertEqual((row["status"], row["company"]), ("purged", "Beta AG"))
        raw = contacts.path(False).read_text()
        self.assertNotIn("anna", raw.lower())
        self.assertEqual(sorted(p.name for p in folder.iterdir()), ["S1_beta_CV.pdf"])
        rows = contacts.load(False)
        self.assertIsNotNone(contacts.already_contacted(rows, " anna@beta.AT ", None))
        self.assertIsNotNone(contacts.already_contacted(rows, None, "https://www.linkedin.com/in/anna"))
        self.assertIsNone(contacts.already_contacted(rows, "other@beta.at", None))
        self.assertIn("déjà purgé", logic.contact_purge("S1"))
        self.assertIn("déjà purgé", logic.contact_keep("S1"))
        self.assertEqual([e["kind"] for e in apps.read_events()], ["contact_purged"])

    def test_purge_never_deletes_outside_the_spontaneous_folder(self):
        self.seed_contact()
        rows = contacts.load(False)
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        (outside / "email.txt").write_text("keep me")
        rows[0]["folder"] = str(outside)
        contacts.save(rows, False)
        logic.contact_purge("S1")
        self.assertTrue((outside / "email.txt").exists())

    def test_test_contacts_stay_apart(self):
        self.seed_contact(cid="TS1", test=True)
        self.assertIn("[TEST]", logic.contact_purge("TS1"))
        self.assertFalse(contacts.path(False).exists())
        self.assertEqual(apps.read_events(), [])


class BotWiring(FollowupBase):
    def test_reply_command_and_buttons(self):
        import bot
        from telegram.ext import CallbackQueryHandler, CommandHandler

        app = bot.build("123:abc", "42")
        handlers = app.handlers[0]
        self.assertIn("reply", {c for h in handlers if isinstance(h, CommandHandler) for c in h.commands})
        cb = [h for h in handlers if isinstance(h, CallbackQueryHandler)][0]
        for data in ("fu:12", "reply:12:yes", "keep:S1", "purge:S1"):
            self.assertTrue(cb.pattern.match(data), data)
        self.assertIn("reply", logic.MENU)
        for lang in ("en", "fr"):
            os.environ["JOBBOT_LANG"] = lang
            names = [n for n, _ in logic.menu_commands()]
            self.assertEqual(names, sorted(names), lang)
            self.assertIn("reply", names)
        os.environ["JOBBOT_LANG"] = "fr"

        self.seed_contact()
        mine = mock.MagicMock()
        mine.effective_chat.id = 42
        mine.callback_query.data = "reply:S1:no"
        mine.callback_query.answer = mock.AsyncMock()
        mine.callback_query.edit_message_reply_markup = mock.AsyncMock()
        mine.callback_query.message.reply_text = mock.AsyncMock()
        asyncio.run(bot.button_handler("42")(mine, None))
        mine.callback_query.edit_message_reply_markup.assert_awaited()  # one-shot: buttons removed
        kwargs = mine.callback_query.message.reply_text.await_args.kwargs
        datas = [b.callback_data for row in kwargs["reply_markup"].inline_keyboard for b in row]
        self.assertEqual(datas, ["keep:S1", "purge:S1"])
        self.assertEqual(contacts.get("S1")["response"], "no 2026-11-25")


if __name__ == "__main__":
    unittest.main()
