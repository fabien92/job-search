import re
import asyncio
import json
import os
import unittest

from _env import FakeTelegram, JobbotTestCase
import common
import dedup
import logic
import sites


class Selection(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(logic.parse_selection("1 3-5", 6), [1, 3, 4, 5])
        self.assertEqual(logic.parse_selection("2,1", 3), [1, 2])
        self.assertEqual(logic.parse_selection("all", 3), [1, 2, 3])
        for bad in ("", "0", "7", "3-1", "x", "1-9"):
            self.assertIsNone(logic.parse_selection(bad, 6), bad)


class Commands(JobbotTestCase):
    def setUp(self):
        super().setUp()
        sites.save({"allowed": [{"domain": "karriere.at"}], "denied": [], "pending": [
            {"domain": "careers.a.at", "requested_by": "https://www.karriere.at/jobs/1", "first_seen": "2026-11-20"},
            {"domain": "b.com", "first_seen": "2026-11-21"},
            {"domain": "c.io", "first_seen": "2026-11-22"}]})

    def test_allow_deny_with_recap_numbering(self):
        text = logic.pending_list_text(refresh=True)
        self.assertIn('1. <a href="https://careers.a.at">careers.a.at</a>', text)
        self.assertIn('href="https://www.karriere.at/jobs/1"', text)
        self.assertIn("2 site(s) autorisé(s)", logic.cmd_allow("1 3"))
        data = sites.load()
        self.assertEqual(sorted(e["domain"] for e in data["allowed"]), ["c.io", "careers.a.at", "karriere.at"])
        self.assertIn("1 site(s) refusé", logic.cmd_deny("2"))
        self.assertEqual(sites.status("b.com"), "denied")
        local = json.loads((self.tmp / "settings.local.json").read_text())
        self.assertIn("WebFetch(domain:careers.a.at)", local["permissions"]["allow"])
        self.assertNotIn("WebFetch(domain:b.com)", local["permissions"]["allow"])
        self.assertIn("déjà été traités", logic.cmd_allow("2"))
        self.assertIn("Sélection invalide", logic.cmd_allow("9"))

    def test_allow_all_sees_hosts_queued_after_the_recap(self):
        logic.pending_list_text(refresh=True)  # recap numbers careers.a.at, b.com, c.io
        logic.cmd_allow("all")
        data = sites.load()
        data["pending"] += [{"domain": "hays.at", "requested_by": "portal hays", "first_seen": "2026-11-26"}]
        sites.save(data)
        reply = logic.cmd_allow("all")  # old recap fully decided: show the new list, decide nothing unseen
        self.assertIn("La liste numérotée a changé", reply)
        self.assertIn('1. <a href="https://hays.at">hays.at</a>', reply)
        self.assertEqual(sites.status("hays.at"), "pending")
        self.assertIn("1 site(s) autorisé(s)", logic.cmd_allow("all"))
        self.assertEqual(sites.status("hays.at"), "allowed")

    def test_no_requires_id_and_enriches_rules(self):
        self.assertIn("exige un ID", logic.cmd_no(""))
        self.assertIn("ID inconnu", logic.cmd_no("12 trop loin"))
        ledger = dedup.Ledger()
        sid = ledger.allocate_id()
        j = dedup.annotate({"site": "karriere", "id": "9", "title": "SAP Consultant", "company": "X", "location": "Wien",
                            "url": "https://www.karriere.at/jobs/9"})
        ledger.add(j["key"], {**j, "short_id": sid, "status": "alerted"})
        ledger.save()
        reply = logic.cmd_no(f"#{sid} pas de postes SAP <b>")
        self.assertIn("rejetée", reply)
        rules = (self.config / "rejection-rules.md").read_text()
        self.assertRegex(rules, r"- \d{4}-\d{2}-\d{2} · pas de postes SAP ‹b› · \(example : #1 https://www.karriere.at/jobs/9\)\n$")
        self.assertNotIn("<!-- vide au départ -->", rules)
        self.assertEqual(dedup.Ledger.load().jobs["karriere:9"]["status"], "rejected")

    def test_no_without_reason_rejects_without_rule(self):
        self.assertIn("ID inconnu", logic.cmd_no("12"))
        ledger = dedup.Ledger()
        sid = ledger.allocate_id()
        j = dedup.annotate({"site": "karriere", "id": "8", "title": "Scrum Master", "company": "Y", "location": "Wien",
                            "url": "https://www.karriere.at/jobs/8"})
        ledger.add(j["key"], {**j, "short_id": sid, "status": "alerted"})
        ledger.save()
        rules = self.config / "rejection-rules.md"
        before = rules.read_text() if rules.exists() else None
        reply = logic.cmd_no(f"#{sid}")
        self.assertIn("rejetée", reply)
        self.assertIn("aucune règle", reply)
        self.assertEqual(rules.read_text() if rules.exists() else None, before, "no rule learnt without a reason")
        entry = dedup.Ledger.load().jobs["karriere:8"]
        self.assertEqual((entry["status"], entry["reason"], entry["user_reason"]), ("rejected", "user", None))

    def test_regions(self):
        self.assertIn("✅ <code>wien</code>", logic.cmd_regions())
        reply = logic.cmd_region("on bratislava")
        self.assertIn("activée", reply)
        text = (self.config / "regions.yaml").read_text()
        self.assertIn("bratislava: { enabled: true,", text)
        self.assertIn("# Search regions. Edit by hand", text, "comments preserved")
        self.assertTrue(common.load_regions()["regions"]["bratislava"]["enabled"])
        logic.cmd_region("off remote")
        self.assertFalse(common.load_regions()["remote_worldwide"])
        self.assertIn("inconnue", logic.cmd_region("on mars"))
        self.assertIn("Usage", logic.cmd_region("maybe wien"))

    def test_search_spawns_once(self):
        calls = []
        self.assertIn("lancée", logic.cmd_search("karriere", spawn=calls.append))
        self.assertEqual(calls[0][-2:], ["--site", "karriere"])
        self.assertIn("inconnu", logic.cmd_search("monster", spawn=calls.append))
        with common.scan_lock():
            self.assertIn("déjà en cours", logic.cmd_search("all", spawn=calls.append))
        self.assertEqual(len(calls), 1)

    def test_status(self):
        self.assertIn("Aucun passage", logic.cmd_status())
        common.atomic_write_json(common.runs_dir() / "20261123T110000.json", {
            "status": "ok", "finished": "2026-11-23T10:05:00Z", "seen": 30, "new": 5, "scored": 4, "alerted": 2,
            "total_cost_usd": 0.4})
        common.atomic_write_json(common.runs_dir() / "20261123T120000-test.json", {"status": "failed"})
        common.atomic_write_json(common.state_dir() / "alerts.json", {"zero:karriere": {"text": "🕳 karriere : 0 offre"}})
        text = logic.cmd_status()
        self.assertIn("Dernier passage : 23/11 11:05 — ok", text)
        self.assertIn("Prochain passage prévu vers : 23/11 15:05", text)
        self.assertIn("karriere : 0 offre", text)
        self.assertIn("3 site(s) en attente", text)


class BotWiring(JobbotTestCase):
    def test_only_the_configured_chat_is_handled(self):
        import bot
        from telegram.ext import CommandHandler, MessageHandler

        app = bot.build("123:abc", "42")
        handlers = app.handlers[0]
        cmds = [h for h in handlers if isinstance(h, CommandHandler)]
        self.assertTrue(cmds)
        for h in cmds:
            self.assertIn(42, h.filters.chat_ids)
        names = {c for h in cmds for c in h.commands}
        self.assertTrue({"search", "no", "allow", "deny", "region", "regions", "status", "rejets", "help", "file", "voir"} <= names)
        stranger = [h for h in handlers if isinstance(h, MessageHandler) and h.callback is bot.ignore_stranger]
        self.assertEqual(len(stranger), 1)


class Rejets(JobbotTestCase):
    def setUp(self):
        super().setUp()
        rid = "20261124T120000"
        common.atomic_write_json(common.runs_dir() / f"{rid}.json", {"run_id": rid, "status": "ok",
                                                                    "finished": "2026-11-24T11:05:00Z"})
        job = lambda ref, title, **kw: {"ref": ref, "title": title, "company": "ACME GmbH", "location": "Wien",
                                        "url": f"https://www.karriere.at/jobs/{ref}", **kw}
        common.atomic_write_json(common.runs_dir() / f"{rid}-prefilter.json", {
            "to_score": [job("b1", "Account Delivery Manager (w/m/d) Applikationsbetrieb & Infrastruktur"),
                         job("b2", "Küchenverkäufer (m/w/d)"), job("b3", "IT Delivery Manager")],
            "rejected": [job("r1", "Head of Team ICT Platform Management (m/w/d)", reason="title_excluded"),
                         job("r2", "Head of Finance", reason="title_excluded"),
                         job("r3", "Internship: Training Coordination & Content Development", reason="internship"),
                         job("r4", "IT Delivery Manager – Senior", reason="republished",
                             republished_of={"key": "karriere:1", "short_id": "7", "title": "Senior IT Delivery Manager"})]})
        common.atomic_write_json(common.runs_dir() / f"{rid}-scores.json", {"scores": [
            {"ref": "b1", "score": 60, "reject_reason": "german_level", "justification": "« Deutsch C1 » " + "x" * 200},
            {"ref": "b2", "score": 1, "reject_reason": "not_it", "justification": "Vendeur"},
            {"ref": "b3", "score": 80, "reject_reason": None, "justification": "ok"}]})

    def test_it_rejects_only_and_phone_sized(self):
        text = logic.cmd_rejets()
        self.assertIn("2 affichée(s) · 3 hors IT masquée(s)", text)
        self.assertIn("Account Delivery Manager Applikationsbetrieb", text)
        self.assertNotIn("(w/m/d)", text, "gender tags stripped to save width")
        self.assertIn("Head of Team ICT Platform Management", text)
        for gone in ("Küchenverkäufer", "Head of Finance", "Content Development", "IT Delivery Manager<",
                     "IT Delivery Manager – Senior", "karriere.at/jobs/r4"):  # V4: republication, silent and uncounted
            self.assertNotIn(gone, text)
        self.assertIn('<a href="https://www.karriere.at/jobs/b1">', text)
        for line in text.splitlines():
            visible = re.sub(r"<[^>]+>", "", line)
            self.assertLessEqual(len(visible), logic.WHY_MAX + 8, line)

    def test_no_run(self):
        for p in common.runs_dir().glob("*.json"):
            p.unlink()
        self.assertIn("Aucun passage", logic.cmd_rejets())

    def test_long_reply_splits_on_lines(self):
        import telegram_send

        text = "\n".join(f'<a href="https://x.at/{i}">offre {i}</a>' for i in range(400))
        for chunk in telegram_send._chunks(text):
            self.assertLessEqual(len(chunk), telegram_send.MAX_LEN)
            self.assertEqual(chunk.count("<a "), chunk.count("</a>"))


class Daily(JobbotTestCase):
    def test_recap(self):
        tg = FakeTelegram()
        self.addCleanup(tg.close)
        os.environ.update({"JOBBOT_TELEGRAM_API": tg.url, "TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT_ID": "1",
                           "JOBBOT_NOW": "2026-11-23T07:00:00Z"})
        sites.save({"allowed": [], "denied": [], "pending": [{"domain": "x.at", "requested_by": "https://y.at/1"}]})
        common.atomic_write_json(common.runs_dir() / "20261123T030000.json", {
            "status": "ok", "finished": "2026-11-23T02:05:00Z", "seen": 10, "new": 3, "scored": 2, "alerted": 1,
            "total_cost_usd": 0.25})
        import daily

        daily.main()
        text = tg.texts()[0]
        self.assertIn("1 passage(s)", text)
        self.assertIn('1. <a href="https://x.at">x.at</a>', text)
        self.assertEqual(json.loads((self.tmp / "state" / "pending_numbering.json").read_text()), ["x.at"])


class Health(JobbotTestCase):
    def test_health_reports_every_check(self):
        from pathlib import Path

        from _env import apply_settings_glob_patch
        import gen_settings

        tg = FakeTelegram()
        self.addCleanup(tg.close)
        apply_settings_glob_patch(self.config)
        os.environ.update({"JOBBOT_TELEGRAM_API": tg.url, "TELEGRAM_TOKEN": "1:a", "TELEGRAM_CHAT_ID": "1",
                           "CLAUDE_CODE_OAUTH_TOKEN": "x", "JOBBOT_BUN": str(Path(__file__).with_name("fake_bun.py"))})
        sites.save({"allowed": [{"domain": "karriere.at"}], "denied": [], "pending": []})
        gen_settings.main([])
        text = logic.cmd_health()
        for name in ("secrets", "telegram", "bun", "lualatex", "venv", "disk", "whitelist", "sandbox", "claude_token"):
            self.assertIn(name, text)
        self.assertIn("⚠️ claude_token", text)  # CLAUDE_CODE_OAUTH_TOKEN_CREATED unknown
        self.assertIn("→ ajouter CLAUDE_CODE_OAUTH_TOKEN_CREATED", text)
        self.assertEqual(tg.texts(), [], "/health replies in the chat; it sends no alert")
        self.assertIn("/health", logic.cmd_help())


class DailyHeartbeat(JobbotTestCase):
    def setUp(self):
        super().setUp()
        self.tg = FakeTelegram()
        self.addCleanup(self.tg.close)
        os.environ.update({"JOBBOT_TELEGRAM_API": self.tg.url, "TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT_ID": "1",
                           "JOBBOT_NOW": "2026-11-24T07:00:00Z"})
        sites.save({"allowed": [], "denied": [], "pending": []})

    def test_sent_even_with_nothing_new(self):
        import daily

        daily.main()
        text = self.tg.texts()[-1]
        self.assertIn("aucun passage depuis 24 h", text)
        self.assertIn("Contrôle :", text)

    def test_quiet_day_is_a_sign_of_life(self):
        import daily

        common.atomic_write_json(common.runs_dir() / "20261124T030000.json", {
            "status": "ok", "finished": "2026-11-24T02:05:00Z", "seen": 40, "new": 0, "scored": 0, "alerted": 0,
            "total_cost_usd": 0})
        daily.main()
        text = self.tg.texts()[-1]
        self.assertIn("✅ <b>JobBot actif</b>", text)
        self.assertIn("Aucune nouvelle offre depuis hier.", text)
        self.assertIn("Dernier passage : 24/11 03:05", text)

    def test_initial_stock_pending_line(self):
        import daily

        run = {"status": "ok", "finished": "2026-11-24T02:05:00Z", "seen": 400, "new": 230, "scored": 38,
               "alerted": 3, "total_cost_usd": 0.4, "cap_reached": True, "deferred": 192}
        common.atomic_write_json(common.runs_dir() / "20261124T030000.json", run)
        daily.main()
        self.assertIn("offres en attente de notation : 192", self.tg.texts()[-1])
        common.atomic_write_json(self.tmp / "state" / "health.json", {"initial_stock_drained": "2026-11-24T06:00:00Z"})
        daily.main()
        self.assertNotIn("en attente de notation", self.tg.texts()[-1], "stock drained: the cap alert takes over")

    def test_queued_messages_are_reported(self):
        import daily
        import telegram_send

        os.environ["JOBBOT_TELEGRAM_API"] = self.tg.down_url
        telegram_send.send("lost for now")
        os.environ["JOBBOT_TELEGRAM_API"] = self.tg.url
        daily.main()
        recap = next(t for t in self.tg.texts() if "Récapitulatif" in t)
        self.assertIn("1 message(s) Telegram en file d'attente", recap)
        self.assertTrue(any("lost for now" in t for t in self.tg.texts()), "the queued message was delivered after the recap")


if __name__ == "__main__":
    unittest.main()


RULES_FILE = (
    "# Règles de rejet\r\n\n"
    "Texte d'en-tête conservé.\n\n"
    "## Règles\n"
    "- 2026-11-20 · allemand C1 exigé · (exemple : #3 https://www.karriere.at/jobs/3)\n"
    "<!-- commentaire de l'utilisateur -->\n"
    "- pas de SAP (ligne écrite à la main)\n"
    "- 2026-11-21 · trop loin · (exemple : #7 https://www.karriere.at/jobs/7)\n"
    "- 2026-11-21 · trop loin · (exemple : #7 https://www.karriere.at/jobs/7)\n"
    "- 2026-11-22 · que du dev · (exemple : #9 https://www.linkedin.com/jobs/view/9)\n\n"
    "## Notes\n"
    "- pas une règle\n"
    "fin sans saut de ligne")


class Rules(JobbotTestCase):
    def setUp(self):
        super().setUp()
        self.path = self.config / "rejection-rules.md"
        self.path.write_bytes(RULES_FILE.encode("utf-8"))

    def confirm_token(self, args):
        text, buttons = logic.cmd_rule_view(args)
        self.assertEqual([b[1].split(":")[0] for b in buttons], ["ruledel", "ruleno"], text)
        return text, buttons[0][1].split(":", 1)[1]

    def test_list_numbered_with_links(self):
        text = logic.cmd_rules()
        self.assertIn("Règles de rejet : 5", text)
        self.assertIn('1. 2026-11-20 · allemand C1 exigé · <a href="https://www.karriere.at/jobs/3">#3</a>', text)
        self.assertIn("2. pas de SAP (ligne écrite à la main) <i>(format libre)</i>", text)
        self.assertNotIn("pas une règle", text, "only the ## Règles section is listed")

    def test_requires_listing_and_valid_selection(self):
        self.assertIn("Fais d'abord /rules", logic.cmd_rule_view("del 1")[0])
        logic.cmd_rules()
        for bad in ("", "del", "del 0", "del 6", "del x", "del all", "remove 1"):
            text, buttons = logic.cmd_rule_view(bad)
            self.assertEqual(buttons, [], bad)
            self.assertRegex(text, "Usage|Sélection invalide")
        self.assertEqual(self.path.read_bytes().decode(), RULES_FILE)

    def test_nothing_deleted_without_confirmation(self):
        logic.cmd_rules()
        _, token = self.confirm_token("del 1 3")
        self.assertEqual(self.path.read_bytes().decode(), RULES_FILE)
        self.assertIn("annulée", logic.rule_cancel(token))
        self.assertIn("expirée ou déjà utilisée", logic.rule_confirm(token))
        self.assertEqual(self.path.read_bytes().decode(), RULES_FILE)

    def test_delete_only_selected_lines_byte_for_byte(self):
        logic.cmd_rules()
        text, token = self.confirm_token("del 1 3 5")
        self.assertIn("Supprimer 3 règle(s)", text)
        reply = logic.rule_confirm(token)
        self.assertIn("3 règle(s) supprimée(s)", reply)
        expected = RULES_FILE.replace(
            "- 2026-11-20 · allemand C1 exigé · (exemple : #3 https://www.karriere.at/jobs/3)\n", "", 1).replace(
            "- 2026-11-21 · trop loin · (exemple : #7 https://www.karriere.at/jobs/7)\n", "", 1).replace(
            "- 2026-11-22 · que du dev · (exemple : #9 https://www.linkedin.com/jobs/view/9)\n", "", 1)
        self.assertEqual(self.path.read_bytes().decode(), expected)
        self.assertIn("Règles de rejet : 2", reply, "the new list follows")
        self.assertIn("expirée ou déjà utilisée", logic.rule_confirm(token), "token is single-use")

    def test_duplicates_are_distinct(self):
        logic.cmd_rules()
        _, token = self.confirm_token("del 3-4")
        logic.rule_confirm(token)
        self.assertNotIn("trop loin", self.path.read_text())

    def test_changed_line_is_not_deleted(self):
        logic.cmd_rules()
        _, token = self.confirm_token("del 1 5")
        edited = RULES_FILE.replace("allemand C1 exigé", "allemand C2 exigé")
        self.path.write_bytes(edited.encode())
        reply = logic.rule_confirm(token)
        self.assertIn("1 règle(s) supprimée(s)", reply)
        self.assertIn("non supprimée", reply)
        self.assertIn("allemand C2 exigé", self.path.read_text())
        self.assertNotIn("que du dev", self.path.read_text())

    def test_new_rule_from_no_between_listing_and_confirm_is_kept(self):
        logic.cmd_rules()
        _, token = self.confirm_token("del 2")
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write("\n- 2026-11-24 · nouvelle · (exemple : #12 https://x.at/12)\n")
        logic.rule_confirm(token)
        text = self.path.read_text()
        self.assertNotIn("pas de SAP", text)
        self.assertIn("nouvelle", text)

    def test_expired_confirmation(self):
        os.environ["JOBBOT_NOW"] = "2026-11-24T10:00:00Z"
        logic.cmd_rules()
        _, token = self.confirm_token("del 1")
        os.environ["JOBBOT_NOW"] = "2026-11-24T10:11:00Z"
        self.assertIn("expirée", logic.rule_confirm(token))
        self.assertEqual(self.path.read_bytes().decode(), RULES_FILE)

    def test_lock_busy_refuses(self):
        from unittest import mock

        logic.cmd_rules()
        _, token = self.confirm_token("del 1")
        lock = common.state_dir() / ".lock"
        short = lambda timeout=60.0: common.file_lock(lock, timeout=0.2)  # flock: per open file, conflicts in-process
        with common.file_lock(lock), mock.patch.object(common, "state_lock", short):
            with self.assertRaises(common.LockBusy):
                logic.rule_confirm(token)
        self.assertEqual(self.path.read_bytes().decode(), RULES_FILE)

    def test_buttons_registered_and_chat_checked(self):
        import bot
        from telegram.ext import CallbackQueryHandler, CommandHandler

        app = bot.build("123:abc", "42")
        handlers = app.handlers[0]
        names = {c for h in handlers if isinstance(h, CommandHandler) for c in h.commands}
        self.assertTrue({"rules", "rule"} <= names)
        cb = [h for h in handlers if isinstance(h, CallbackQueryHandler)]
        self.assertTrue(cb[0].pattern.match("ruledel:abc") and cb[0].pattern.match("ruleno:abc"))
        logic.cmd_rules()
        _, token = self.confirm_token("del 1")

        class Chat:
            id = 666

        class Query:
            data = f"ruledel:{token}"

            async def answer(self):
                raise AssertionError("stranger must be ignored before answering")

        class Upd:
            effective_chat = Chat()
            callback_query = Query()

        asyncio.run(bot.button_handler("42")(Upd(), None))
        self.assertEqual(self.path.read_bytes().decode(), RULES_FILE)


class Blocking(JobbotTestCase):
    def setUp(self):
        super().setUp()
        import companies

        self.companies = companies
        rows = []
        companies.add(rows, "Erste Group Bank AG", city="Wien", website="https://www.erstegroup.com")
        companies.add(rows, "ACME GmbH", city="Wien", website="https://acme.at")
        companies.save(rows)

    def test_block_list_unblock_one(self):
        self.assertIn("exige un nom", logic.cmd_block(""))
        reply = logic.cmd_block("Erste")
        self.assertIn("Erste bloquée", reply)
        self.assertIn("Couvre aussi : Erste Group Bank AG", reply)
        self.assertIn("déjà bloquée", logic.cmd_block("erste"))
        logic.cmd_block("ACME GmbH")
        text = logic.cmd_blocked()
        self.assertIn("Entreprises bloquées : 2", text)
        self.assertIn('1. ACME GmbH · <a href="https://acme.at">acme.at</a>', text)
        self.assertIn("2. Erste", text)
        for bad in ("", "1 2", "1-2", "all", "ACME"):
            self.assertIn("un seul numéro", logic.cmd_unblock(bad), bad)
        self.assertIn("Numéro invalide", logic.cmd_unblock("9"))
        self.assertIn("ACME GmbH débloquée", logic.cmd_unblock("1"))
        self.assertEqual(self.companies.find(self.companies.load(), "ACME")["status"], "active")
        self.assertEqual(self.companies.find(self.companies.load(), "Erste")["status"], "blocked", "only one unblocked")
        self.assertIn("Entreprises bloquées : 1", logic.cmd_blocked())

    def test_unblock_needs_listing_and_detects_changes(self):
        logic.cmd_block("ACME")
        self.assertIn("Fais d'abord /blocked", logic.cmd_unblock("1"))
        logic.cmd_blocked()
        rows = self.companies.load()
        self.companies.unblock(self.companies.find(rows, "ACME"))
        self.companies.save(rows)
        self.assertIn("plus bloquée", logic.cmd_unblock("1"))

    def test_block_unknown_company_creates_row(self):
        logic.cmd_block("Neue Firma GmbH")
        row = self.companies.find(self.companies.load(), "Neue Firma")
        self.assertEqual((row["status"], row["origin"]), ("blocked", "telegram /block"))
