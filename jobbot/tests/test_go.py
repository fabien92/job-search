"""V2 (SPEC §9, §13): texguard, offre.pdf, applications, go.py, /go /sent /cancel /pending /firma,
daily reminder, weekly report. No network, no port: Telegram goes through the file:// transport,
claude / lualatex / xelatex are fakes."""
import asyncio
import csv
import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

from _env import FakeTelegram, JobbotTestCase
import applications as apps
import build_cv_variants
import common
import dedup
import go
import logic
import offer_pdf
import texguard

HERE = Path(__file__).resolve().parent
VARIANTS = ("delivery", "techlead", "international-orgs", "support-it-manager")
REAL_VARIANTS = Path(__file__).resolve().parents[2] / "documents" / "cv" / "jobbot" / "variants"


class TexGuard(unittest.TestCase):
    OK = ("% comment\n\\renewcommand{\\cvHeadline}{IT Delivery Manager \\textbullet\\ Service \\& Release}\n"
          "\\renewcommand{\\cvProfileText}{Ten years, 100\\% delivery, \\textbf{zero} incidents --- \\textasciitilde200 days.}\n"
          "\\renewcommand{\\expCurrentBlocks}{\\expProj\\expMgmt\\expTech}\n"
          "\\renewcommand{\\tsA}{\\skillcell{AI}{Claude Code, GitHub Copilot}}\n"
          "\\renewcommand{\\fsA}{\\funcell{Project \\& Delivery}{Release governance}}\n\\cvphotofalse\n")

    def test_contract_accepted(self):
        result = texguard.check(self.OK)
        self.assertEqual(result["macros"], ["cvHeadline", "cvProfileText", "expCurrentBlocks", "tsA", "fsA"])
        self.assertEqual(result["switches"], ["cvphotofalse"])

    @unittest.skipUnless(REAL_VARIANTS.is_dir(), "block CV not present")
    def test_real_variants_pass(self):
        for name in VARIANTS:
            texguard.check_file(REAL_VARIANTS / f"{name}.tex")

    def test_attacks_refused(self):
        attacks = {
            "lua": "\\renewcommand{\\cvHeadline}{x\\directlua{os.exit()}}",
            "input": "\\renewcommand{\\cvProfileText}{\\input{/etc/passwd}}",
            "write": "\\immediate\\write18{rm -rf ~}",
            "caret escape": "\\renewcommand{\\cvHeadline}{^^5cdirectlua{x}}",
            "param": "\\renewcommand{\\cvHeadline}{#1}",
            "optional arg": "\\renewcommand{\\cvHeadline}[1]{x}",
            "def": "\\def\\cvHeadline{x}",
            "other macro": "\\renewcommand{\\geometry}{x}",
            "layout": "\\renewcommand{\\cvProfileText}{a\\vspace{-5mm}b}",
            "line break": "\\renewcommand{\\cvProfileText}{a\\\\b}",
            "unbalanced": "\\renewcommand{\\cvHeadline}{x}}\\directlua{y}",
            "stray text": "hello \\renewcommand{\\cvHeadline}{x}",
            "too long": "\\renewcommand{\\cvHeadline}{" + "x" * 120 + "}",
            "cell shape": "\\renewcommand{\\tsA}{plain text}",
            "cell cmd": "\\renewcommand{\\tsA}{\\skillcell{A}{\\input{x}}}",
            "order": "\\renewcommand{\\expCurrentBlocks}{\\expMgmt\\expMgmt\\expTech}",
            "twice": "\\renewcommand{\\cvHeadline}{a}\\renewcommand{\\cvHeadline}{b}",
            "empty": "% nothing\n",
            "catcode": "\\catcode`\\@=11",
            "bare percent": "\\renewcommand{\\cvProfileText}{100% uptime}",
            "comment in body": "\\renewcommand{\\cvProfileText}{a % }\n}",
            "percent in cell": "\\renewcommand{\\tsA}{\\skillcell{AI}{Claude Code, 100% }}",
        }
        for label, text in attacks.items():
            with self.assertRaises(texguard.Refused, msg=label):
                texguard.check(text)

    def test_unescaped_percent_message(self):
        with self.assertRaises(texguard.Refused) as ctx:
            texguard.check("\\renewcommand{\\cvProfileText}{100% uptime}")
        self.assertIn("unescaped %", str(ctx.exception))
        texguard.check("% a comment between macros stays allowed\n\\renewcommand{\\cvProfileText}{100\\% uptime}\n")


class OfferPdf(unittest.TestCase):
    def test_escape_neutralises_tex(self):
        out = offer_pdf.escape("\\directlua{os.exit()} 100% $x^2$ #1 ~ _ & < > ​🚀 Ö €")
        self.assertNotIn("\\directlua", out)
        self.assertIn("\\textbackslash{}directlua\\{os.exit()\\}", out)
        for frag in ("100\\%", "\\$x\\^{}2\\$", "\\#1", "\\textasciitilde{}", "\\_", "\\&", "Ö €"):
            self.assertIn(frag, out)
        self.assertNotIn("🚀", out)
        self.assertNotIn("​", out)

    def test_guard_section_left_out(self):
        tex = offer_pdf.to_latex("Title: X\n- point\n\n## posting_guard\nverdict ok\n", {"title": "X", "id": "7"})
        self.assertIn("\\textbullet\\ point", tex)
        self.assertNotIn("verdict ok", tex)
        self.assertIn("JobBot \\#7", tex)


class Naming(unittest.TestCase):
    def test_folder_name_rule(self):
        self.assertEqual(apps.folder_name("Novo Nordisk A/S", "IT Delivery Manager (m/w/d)"),
                         "novo_nordisk_as_it_delivery_manager_mwd")
        self.assertEqual(apps.folder_name("Österreichische Post", "Tech-Lead"), "osterreichische_post_techlead")
        self.assertEqual(apps.folder_name("../..", "/"), "offre")
        self.assertEqual(apps.file_stem("12", "ACME", "IT Lead"), "12_acme_it_lead")

    def test_ids(self):
        self.assertEqual(apps.norm_id("#12"), "12")
        self.assertEqual(apps.norm_id("t5"), "T5")
        for bad in ("", "abc", "12; rm", "../1"):
            self.assertIsNone(apps.norm_id(bad), bad)


class GoBase(JobbotTestCase):
    def setUp(self):
        super().setUp()
        self.tg = FakeTelegram()
        self.addCleanup(self.tg.close)
        os.environ.update({"JOBBOT_TELEGRAM_API": self.tg.url, "TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT_ID": "42",
                           "JOBBOT_NOW": "2026-11-24T10:00:00Z",
                           "JOBBOT_LUALATEX": str(HERE / "fake_latex.py"), "JOBBOT_XELATEX": str(HERE / "fake_latex.py"),
                           "JOBBOT_CLAUDE_BIN": str(HERE / "fake_claude.py")})
        cv = self.tmp / "cv"
        for sub in ("variants", "blocks", "pdf"):
            (cv / sub).mkdir(parents=True)
        (cv / "cv.tex").write_text("% fake master\n")
        (cv / "blocks" / "content.tex").write_text("% defaults\n")
        for name in VARIANTS:
            (cv / "variants" / f"{name}.tex").write_text(f"% {name}\n")
            (cv / "pdf" / f"{name}.pdf").write_bytes(b"%PDF-1.4 variant " + name.encode())
        (common.state_dir() / "scan-settings.json").write_text("{}")
        for target, value in ((go, "command_installed"), (build_cv_variants, "check_text")):
            patcher = mock.patch.object(target, value, return_value=True if value == "command_installed" else {"problems": []})
            patcher.start()
            self.addCleanup(patcher.stop)

    def seed(self, title="IT Delivery Manager", company="ACME GmbH", adapt=False, variant="delivery", job_id="1"):
        ledger = dedup.Ledger.load()
        sid = ledger.allocate_id()
        job = dedup.annotate({"site": "karriere", "id": job_id, "title": title, "company": company, "location": "Wien",
                              "url": f"https://www.karriere.at/jobs/{job_id}"})
        ledger.add(job["key"], {**job, "short_id": sid, "status": "alerted", "score": 82, "variant": variant,
                                "adapt": adapt, "adapt_reason": "mettre ITIL en avant"})
        ledger.save()
        msgs = common.read_json(common.state_dir() / "telegram_msgs.json", {}) or {}
        msgs[sid] = {"message_id": 500 + int(sid), "kind": "alert", "sent": "2026-11-24T09:00:00Z"}
        common.atomic_write_json(common.state_dir() / "telegram_msgs.json", msgs)
        apps.archive_posting(sid, {"guard": {"verdict": "posting_guard: ok"}},
                             f"Title: {title}\nCompany: {company}\n\nRelease management, ITIL.\n")
        return sid

    def docs(self):
        return [(p, f) for m, p, f in self.calls_with_files() if m == "sendDocument"]

    def calls_with_files(self):
        path = self.tg.dir / "requests.jsonl"
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        return [(r["method"], r["payload"], r.get("files")) for r in rows]

    def tracker(self):
        with open(common.tracker_path(), encoding="utf-8") as fh:
            return list(csv.DictReader(fh))


class GoCircuit(GoBase):
    def test_no_adaptation_copies_variant_zero_token(self):
        sid = self.seed()
        self.assertEqual(go.main([sid]), 0)
        self.assertFalse((common.runs_dir() / f"go-{sid}-claude.json").exists(), "no Claude call")
        appdir = common.applications_dir() / "acme_gmbh_it_delivery_manager"
        cv = appdir / f"{sid}_acme_gmbh_it_delivery_manager_CV.pdf"
        self.assertEqual(cv.read_bytes(), b"%PDF-1.4 variant delivery")
        self.assertTrue((appdir / "offre.pdf").exists())
        self.assertIn("Release management", (appdir / "job_posting.md").read_text())
        docs = self.docs()
        self.assertEqual([f["document"]["filename"] for _, f in docs],
                         [f"{sid}_acme_gmbh_it_delivery_manager_CV.pdf", f"{sid}_acme_gmbh_it_delivery_manager_offre.pdf"])
        for payload, _ in docs:
            self.assertEqual(payload["reply_parameters"]["message_id"], 501, "files answer the alert message")
        summary = self.tg.texts()[-1]
        self.assertIn(f"#{sid} · ACME GmbH · IT Delivery Manager", summary)
        self.assertNotIn("lettre", summary.lower())
        row = self.tracker()[0]
        self.assertEqual((row["status"], row["company"], row["fit_rating"], row["cover_letter_file"]),
                         ("drafted", "ACME GmbH", "82", ""))
        self.assertIn(f"jobbot #{sid}", row["notes"])
        entry = apps.load_pending(False)[sid]
        self.assertEqual(len(entry["telegram"]), 2)
        self.assertFalse(entry["adapted"])
        self.assertEqual(dedup.Ledger.load().find_short(sid)[1]["status"], "drafted")
        self.assertEqual([e["kind"] for e in apps.read_events()], ["go"])

    def test_adaptation_writes_only_overrides_and_compiles(self):
        sid = self.seed(adapt=True, variant="techlead")
        self.assertEqual(go.main([sid]), 0)
        argv = json.loads((common.runs_dir() / "fake-claude-argv.json").read_text())
        self.assertEqual(argv[argv.index("-p") + 1], f"/jobbot-go {sid}")
        self.assertIn("Bash,WebFetch,WebSearch", argv[argv.index("--disallowedTools") + 1])
        allowed = argv[argv.index("--allowedTools") + 1]
        self.assertIn(f"Write(/{common.runs_dir() / f'go-{sid}-cv_overrides.tex'})", allowed)
        self.assertEqual(allowed.count("Write("), 1, "Claude may write one file only")
        appdir = next(common.applications_dir().iterdir())
        self.assertIn("\\cvHeadline", (appdir / "cv_overrides.tex").read_text())
        build = self.tmp / "cv" / "build"
        self.assertIn("expProj", (build / f"go-{sid}.overrides").read_text(), "compiled with this application's file")
        self.assertFalse((self.tmp / "cv" / "cv_overrides.tex").exists(), "the shared file is never used")
        self.assertTrue(apps.load_pending(False)[sid]["adapted"])
        self.assertIn("adaptée", self.tg.texts()[-1])
        self.assertEqual(apps.read_events()[-1]["cost_usd"], 0.07)

    def test_forbidden_tex_falls_back_to_variant(self):
        sid = self.seed(adapt=True)
        with mock.patch.dict(os.environ, {"FAKE_GO_MODE": "evil"}):
            self.assertEqual(go.main([sid]), 0)
        self.assertFalse(any((self.tmp / "cv" / "build").glob("*")) if (self.tmp / "cv" / "build").exists() else False)
        cv = next(common.applications_dir().glob("*/*_CV.pdf"))
        self.assertEqual(cv.read_bytes(), b"%PDF-1.4 variant delivery")
        self.assertIn("refusé", self.tg.texts()[-1])
        self.assertFalse(apps.load_pending(False)[sid]["adapted"])

    def test_three_pages_fall_back(self):
        sid = self.seed(adapt=True)
        with mock.patch.dict(os.environ, {"FAKE_LATEX_PAGES": "3"}):
            go.main([sid])
        self.assertIn("3 pages, expected 2", self.tg.texts()[-1])
        self.assertFalse(apps.load_pending(False)[sid]["adapted"])

    def test_path_tex_cannot_take_falls_back_to_variant(self):
        sid = self.seed(adapt=True)
        spaced = self.tmp / "my applications"
        with mock.patch.dict(os.environ, {"JOBBOT_APPLICATIONS_DIR": str(spaced)}):
            self.assertEqual(go.main([sid]), 0, "no crash: the plain variant is sent")
            cv = next(spaced.glob("*/*_CV.pdf"))
            self.assertEqual(cv.read_bytes(), b"%PDF-1.4 variant delivery")
            self.assertFalse(apps.load_pending(False)[sid]["adapted"])
        self.assertIn("path not usable in TeX", self.tg.texts()[-1])

    def test_claude_reads_allowed_by_exact_path(self):
        sid = self.seed(adapt=True, variant="techlead")
        self.assertEqual(go.main([sid]), 0)
        argv = json.loads((common.runs_dir() / "fake-claude-argv.json").read_text())
        allowed = argv[argv.index("--allowedTools") + 1].split(",")
        cv = self.tmp / "cv"
        for path in (common.runs_dir() / f"go-{sid}-request.json", apps.posting_path(sid), common.profile_file(),
                     cv / "blocks" / "content.tex", cv / "variants" / "techlead.tex"):
            self.assertIn(f"Read(/{path})", allowed)
        self.assertFalse([r for r in allowed if "*" in r], "exact paths only, no glob")

    def test_latex_runs_without_secrets_or_shell_escape(self):
        probe = self.tmp / "probe_latex.py"
        probe.write_text("#!/usr/bin/env python3\nimport json, os, runpy, sys\n"
                         f"rec = {str(self.tmp / 'latex-calls.jsonl')!r}\n"
                         "keys = ('TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID', 'TELEGRAM_USER_ID', 'CLAUDE_CODE_OAUTH_TOKEN')\n"
                         "open(rec, 'a').write(json.dumps({'argv': sys.argv[1:], 'texmfvar': os.environ.get('TEXMFVAR'),\n"
                         "    'secrets': [k for k in keys if k in os.environ]}) + '\\n')\n"
                         f"runpy.run_path({str(HERE / 'fake_latex.py')!r}, run_name='__main__')\n")
        probe.chmod(0o755)
        sid = self.seed(adapt=True)
        env = {"JOBBOT_LUALATEX": str(probe), "JOBBOT_XELATEX": str(probe), "TELEGRAM_USER_ID": "42",
               "CLAUDE_CODE_OAUTH_TOKEN": "secret"}
        with mock.patch.dict(os.environ, env):
            os.environ.pop("TEXMFVAR", None)
            self.assertEqual(go.main([sid]), 0)
        calls = [json.loads(line) for line in (self.tmp / "latex-calls.jsonl").read_text().splitlines()]
        self.assertEqual(len(calls), 2, "lualatex (CV) and xelatex (offre.pdf)")
        for call in calls:
            self.assertEqual(call["secrets"], [])
            self.assertIn("-no-shell-escape", call["argv"])
            self.assertEqual(call["texmfvar"], str(common.cache_dir() / "texmf-var"))
        self.assertTrue(apps.load_pending(False)[sid]["adapted"])

    def test_already_pending_and_unknown(self):
        sid = self.seed()
        go.main([sid])
        before = len(self.docs())
        go.main([sid])
        self.assertEqual(len(self.docs()), before)
        self.assertIn("déjà prête", self.tg.texts()[-1])
        self.assertEqual(go.main(["999"]), 1)
        self.assertIn("ID inconnu", self.tg.texts()[-1])

    def test_folder_of_another_id_is_not_reused(self):
        a = self.seed(job_id="1")
        b = self.seed(job_id="2")  # same company and title, another posting
        go.main([a])
        go.main([b])
        names = sorted(p.name for p in common.applications_dir().iterdir())
        self.assertEqual(names, ["acme_gmbh_it_delivery_manager", f"acme_gmbh_it_delivery_manager_{b}"])

    def test_parallel_go_different_ids_same_id_locked(self):
        ids = [self.seed(job_id=str(i), company=f"Firm{i}") for i in range(3)]
        env = dict(os.environ)
        env["PYTHONPATH"] = str(HERE.parent / "scripts")
        # patched helpers do not cross processes: install a command stub and a no-op text check via env
        cmd = self.tmp / "go_stub.py"
        cmd.write_text("import sys, go, build_cv_variants\n"
                       "go.command_installed = lambda: True\n"
                       "build_cv_variants.check_text = lambda pdf: {'problems': []}\n"
                       "sys.exit(go.main(sys.argv[1:]))\n")
        procs = [subprocess.Popen([sys.executable, str(cmd), sid], env=env, cwd=HERE.parent / "scripts")
                 for sid in ids]
        self.assertEqual([p.wait(timeout=120) for p in procs], [0, 0, 0])
        self.assertEqual(sorted(apps.load_pending(False)), sorted(ids))
        self.assertEqual(len(self.tracker()), 3)
        with go.go_lock(ids[0]):
            self.assertTrue(go.is_running(ids[0]))
            self.assertEqual(go.main([ids[0]]), 3)

    def test_test_id_never_touches_real_data(self):
        common.atomic_write_json(common.runs_dir() / "20261124T090000-test-alerts.json", {"jobs": {"T7": {
            "short_id": "T7", "title": "Tech Lead", "company": "Beta", "url": "https://x.at/7", "score": 75,
            "variant": "techlead", "adapt": False, "message_id": 77}}})
        apps.archive_posting("T7", {}, "Title: Tech Lead\n")
        self.assertEqual(go.main(["T7"]), 0)
        self.assertFalse(common.tracker_path().exists())
        self.assertEqual(apps.load_pending(False), {})
        self.assertIn("T7", apps.load_pending(True))
        self.assertFalse(common.applications_dir().exists())
        self.assertTrue(any((common.cache_dir() / "test-applications").iterdir()))
        self.assertTrue(self.tg.texts()[-1].startswith("[TEST] "))
        self.assertEqual(apps.read_events(), [])


class BotCommands(GoBase):
    def test_go_requires_id_and_spawns_one_per_id(self):
        self.assertIn("exige un ID", logic.cmd_go(""))
        a, b = self.seed(job_id="1"), self.seed(job_id="2", adapt=True)
        spawned = []
        reply = logic.cmd_go(f"{a} {b} 999 x;", spawn=spawned.append)
        self.assertEqual([argv[-1] for argv in spawned], [a, b])
        self.assertTrue(all(argv[1].endswith("go.sh") for argv in spawned))
        self.assertIn("zéro token", reply)
        self.assertIn("CV adapté par Claude", reply)
        self.assertIn("#999 : ID inconnu", reply)
        self.assertIn("ID invalide", reply)

    def test_go_refuses_pending_and_running(self):
        sid = self.seed()
        go.main([sid])
        self.assertIn("déjà prête", logic.cmd_go(sid, spawn=self.fail))
        other = self.seed(job_id="9")
        with go.go_lock(other):
            self.assertIn("déjà en cours", logic.cmd_go(other, spawn=self.fail))

    def test_sent_requires_id_updates_csv_and_deletes_files(self):
        self.assertIn("exige un ID", logic.cmd_sent(""))
        self.assertIn("un seul", logic.cmd_sent("1 2"))
        sid = self.seed()
        self.assertIn("pas en attente", logic.cmd_sent(sid))
        go.main([sid])
        reply = logic.cmd_sent(sid)
        self.assertIn("drafted → applied", reply)
        self.assertIn("Fichiers retirés de Telegram : 2", reply)
        self.assertNotIn("à la main", reply)
        deletes = [p for m, p, _ in self.calls_with_files() if m == "deleteMessage"]
        self.assertEqual(len(deletes), 2)
        self.assertEqual(self.tracker()[0]["status"], "applied")
        self.assertEqual(apps.load_pending(False), {})
        self.assertEqual(dedup.Ledger.load().find_short(sid)[1]["status"], "sent")
        self.assertIn("déjà envoyée", logic.cmd_go(sid, spawn=self.fail))

    def test_sent_after_48h_warns_manual_deletion(self):
        sid = self.seed()
        go.main([sid])
        os.environ["JOBBOT_NOW"] = "2026-11-26T10:00:01Z"  # 48 h + 1 s after the files
        reply = logic.cmd_sent(sid)
        self.assertIn("Fichiers retirés de Telegram : 0", reply)
        self.assertIn("À supprimer à la main", reply)
        self.assertIn("moins de 48 h", reply)
        self.assertIn(f"{sid}_acme_gmbh_it_delivery_manager_CV.pdf", reply)
        self.assertFalse([m for m, _, _ in self.calls_with_files() if m == "deleteMessage"], "nothing attempted")

    def test_delete_refused_by_api_is_reported(self):
        sid = self.seed()
        go.main([sid])
        self.tg.statuses = [400, 400]
        reply = logic.cmd_sent(sid)
        self.assertIn("À supprimer à la main", reply)

    def test_cancel(self):
        self.assertIn("exige un ID", logic.cmd_cancel(""))
        sid = self.seed()
        go.main([sid])
        reply = logic.cmd_cancel(sid)
        self.assertIn("plus jamais proposée", reply)
        self.assertIn("drafted → withdrawn", reply)
        self.assertIn("Fichiers retirés de Telegram : 2", reply)
        self.assertEqual(dedup.Ledger.load().find_short(sid)[1]["status"], "cancelled")
        self.assertIn("déjà abandonnée", logic.cmd_cancel(sid))
        never = self.seed(job_id="5")  # cancel without /go: the offer is closed too
        self.assertIn("abandonnée", logic.cmd_cancel(never))
        self.assertIn("abandonnée, rien à préparer", logic.cmd_go(never, spawn=self.fail))

    def test_pending_view_and_resend(self):
        self.assertIn("Aucune candidature", logic.cmd_pending())
        sid = self.seed()
        go.main([sid])
        os.environ["JOBBOT_NOW"] = "2026-11-25T13:00:00Z"
        text, buttons = logic.cmd_pending_view()
        self.assertIn(f"<b>#{sid}</b> · ACME GmbH · IT Delivery Manager", text)
        self.assertIn('href="https://www.karriere.at/jobs/1"', text)
        self.assertIn("depuis 1 j 3 h", text)
        self.assertEqual(buttons, [(f"📎 #{sid} renvoyer les fichiers", f"resend:{sid}")])
        before = len(self.docs())
        self.assertIn("2 fichier(s) renvoyé(s)", logic.resend_files(sid))
        self.assertEqual(len(self.docs()), before + 2)
        self.assertEqual(len(apps.load_pending(False)[sid]["telegram"]), 4, "resent files are deleted by /sent too")
        self.assertIn("n'est plus en attente", logic.resend_files("999"))

    def test_firma(self):
        self.assertIn("exige un nom", logic.cmd_firma(""))
        sid = self.seed(company="Erste Group Bank AG")
        go.main([sid])
        logic.cmd_sent(sid)
        text = logic.cmd_firma("erste group")
        self.assertIn("<b>IT Delivery Manager</b> · Erste Group Bank AG", text)
        self.assertIn("statut <b>applied</b>", text)
        self.assertIn(f"CV envoyé : {sid}_erste_group_bank_ag_it_delivery_manager_CV.pdf", text)
        self.assertIn("lettre : aucune", text)
        self.assertIn("Aucune candidature", logic.cmd_firma("Raiffeisen"))


class Wiring(GoBase):
    def test_handlers_and_button_chat_check(self):
        import bot
        from telegram.ext import CallbackQueryHandler, CommandHandler

        app = bot.build("123:abc", "42")
        handlers = [h for group in app.handlers.values() for h in group]
        names = {c for h in handlers if isinstance(h, CommandHandler) for c in h.commands}
        self.assertTrue({"go", "sent", "cancel", "pending", "firma"} <= names)
        for h in handlers:
            if isinstance(h, CommandHandler):
                self.assertIn(42, h.filters.chat_ids)
        self.assertEqual(len([h for h in handlers if isinstance(h, CallbackQueryHandler)]), 1)

        called = []
        with mock.patch.object(logic, "resend_files", side_effect=lambda sid: called.append(sid) or "ok"):
            stranger = mock.MagicMock()
            stranger.effective_chat.id = 666
            stranger.callback_query.data = "resend:1"
            stranger.callback_query.answer = mock.AsyncMock()
            asyncio.run(bot.button_handler("42")(stranger, None))
            self.assertEqual(called, [], "button from another chat ignored")
            mine = mock.MagicMock()
            mine.effective_chat.id = 42
            mine.callback_query.data = "resend:1"
            mine.callback_query.answer = mock.AsyncMock()
            mine.callback_query.message.reply_text = mock.AsyncMock()
            asyncio.run(bot.button_handler("42")(mine, None))
            self.assertEqual(called, ["1"])


class Scoring(GoBase):
    def test_variant_and_adapt_validated_alert_and_archive(self):
        import postprocess

        posting = common.cache_dir() / "b1.txt"
        posting.write_text("Title: IT Delivery Manager\nITIL\n")
        job = {"ref": "b1", "site": "karriere", "id": "77", "title": "IT Delivery Manager", "company": "ACME",
               "location": "Wien", "url": "https://www.karriere.at/jobs/77", "text_path": str(posting),
               "guard": {"verdict": "posting_guard: ok"}}
        job = dedup.annotate(job)
        rid = "20261124T100000"
        common.atomic_write_json(common.runs_dir() / f"{rid}-prefilter.json", {"to_score": [job, {**job, "ref": "b2", "id": "78",
                                 "key": "karriere:78", "url": "https://www.karriere.at/jobs/78"}], "sites": {}})
        common.atomic_write_json(common.runs_dir() / f"{rid}-scores.json", {"scores": [
            {"ref": "b1", "score": 85, "reject_reason": None, "variant": "techlead", "adapt": True,
             "adapt_reason": "DevOps à mettre en avant", "justification": "ok"},
            {"ref": "b2", "score": 70, "reject_reason": None, "variant": "finance-regulatory", "adapt": "oui"}]})
        postprocess.run(rid, None, None, False)
        ledger = dedup.Ledger.load()
        e1, e2 = ledger.find_short("1")[1], ledger.find_short("2")[1]
        self.assertEqual((e1["variant"], e1["adapt"], e1["adapt_reason"]), ("techlead", True, "DevOps à mettre en avant"))
        self.assertEqual((e2["variant"], e2["adapt"]), (None, True), "unknown variant dropped")
        alert = next(t for t in self.tg.texts() if "#1 ·" in t)
        self.assertIn("CV : techlead · adaptation oui — DevOps à mettre en avant", alert)
        self.assertIn("/go 1 · /no 1", alert)
        self.assertIn("ITIL", apps.posting_path("1").read_text())
        self.assertIn("## posting_guard", apps.posting_path("1").read_text())

    def test_dry_run_alerts_get_test_ids(self):
        import postprocess

        os.environ["JOBBOT_DRY_RUN"] = "1"
        posting = common.cache_dir() / "b1.txt"
        posting.write_text("Title: X\n")
        job = dedup.annotate({"ref": "b1", "site": "karriere", "id": "5", "title": "Tech Lead", "company": "B",
                              "location": "Wien", "url": "https://x.at/5", "text_path": str(posting)})
        rid = "20261124T110000-test"
        common.atomic_write_json(common.runs_dir() / f"{rid}-prefilter.json", {"to_score": [job], "sites": {}})
        common.atomic_write_json(common.runs_dir() / f"{rid}-scores.json", {"scores": [
            {"ref": "b1", "score": 90, "reject_reason": None, "variant": "techlead", "adapt": False}]})
        postprocess.run(rid, None, None, False)
        found = apps.find_job("T1")
        self.assertEqual((found["title"], found["variant"]), ("Tech Lead", "techlead"))
        self.assertTrue(found["message_id"])
        self.assertTrue(apps.posting_path("T1").exists())
        self.assertFalse((common.state_dir() / "postings" / "T1.md").exists())


class Reports(GoBase):
    def test_daily_lists_pending_over_24h(self):
        import daily
        import sites

        sites.save({"allowed": [], "denied": [], "pending": []})
        old, new = self.seed(job_id="1"), self.seed(job_id="2", company="Newco")
        go.main([old])
        os.environ["JOBBOT_NOW"] = "2026-11-25T09:00:00Z"
        go.main([new])
        os.environ["JOBBOT_NOW"] = "2026-11-25T11:00:00Z"
        text = daily.build()
        self.assertIn("Préparées, pas encore envoyées (&gt; 24 h) : 1", text)
        self.assertIn(f"#{old} ACME GmbH", text)
        self.assertNotIn(f"#{new} Newco", text)

    def test_weekly(self):
        import weekly

        for stem, seen, cost in (("20261120T080000", 100, 0.5), ("20261124T080000", 50, 0.25), ("20261110T080000", 999, 9)):
            common.atomic_write_json(common.runs_dir() / f"{stem}.json", {
                "status": "ok", "finished": f"{stem[:4]}-{stem[4:6]}-{stem[6:8]}T07:00:00Z", "seen": seen, "new": 10,
                "scored": 8, "alerted": 2, "total_cost_usd": cost})
        common.atomic_write_json(common.runs_dir() / "20261123T080000-test.json", {"finished": "2026-11-23T07:00:00Z", "seen": 7777})
        common.atomic_write_json(common.state_dir() / "site_stats.json", {
            "karriere": {"2026-11-23": {"results": 40, "queries": 10, "errors": 0}},
            "linkedin": {"2026-11-22": {"results": 0, "queries": 3, "errors": 3}, "2026-11-23": {"results": 0, "queries": 3, "errors": 0}}})
        a, b = self.seed(job_id="1"), self.seed(job_id="2", adapt=True)
        go.main([a])
        go.main([b])
        logic.cmd_sent(a)
        text = weekly.build()
        self.assertIn("Offres vues 150 · nouvelles 20 · notées 16 · retenues (alertes) 4", text)
        self.assertIn("/go 2 (dont 1 CV adapté) · envoyées 1 · abandonnées 0 · en attente 1", text)
        self.assertIn("Sites sans résultat cette semaine : linkedin", text)
        self.assertIn("Sites en panne : linkedin (1 j)", text)
        self.assertIn("Coût estimé : 0.82 USD (notation 0.75 · /go 0.07)", text)
        self.assertNotIn("7777", text)
        weekly.main()
        self.assertIn("Bilan hebdomadaire", self.tg.texts()[-1])

    def test_weekly_plist_from_schedule(self):
        import gen_launchd

        plists = gen_launchd.build("jobbot", Path("/Users/jobbot/ai-job-search"), common.load_schedule(),
                                   home="/Users/jobbot", group="staff")
        weekly = plists["com.jobbot.weekly"]
        self.assertEqual(weekly["StartCalendarInterval"], {"Weekday": 0, "Hour": 18, "Minute": 0})
        self.assertEqual(weekly["UserName"], "jobbot")
        self.assertTrue(weekly["ProgramArguments"][1].endswith("jobbot/scripts/weekly.sh"))
        self.assertEqual(gen_launchd.weekly({"day": "samedi", "time": "09:30"}), {"Weekday": 6, "Hour": 9, "Minute": 30})
        with self.assertRaises(ValueError):
            gen_launchd.weekly({"day": "someday"})


class CommandSources(unittest.TestCase):
    def test_sources_exist_and_mention_contract(self):
        cmds = Path(__file__).resolve().parents[1] / "commands"
        go_md = (cmds / "jobbot-go.md").read_text()
        for word in ("cv_overrides.tex", "\\cvHeadline", "Claude Code", "No cover letter", "untrusted"):
            self.assertIn(word, go_md)
        scan_md = (cmds / "jobbot-scan.md").read_text()
        for word in ('"variant"', '"adapt"', '"adapt_reason"', "international-orgs", "support-it-manager"):
            self.assertIn(word, scan_md)


if __name__ == "__main__":
    unittest.main()
