"""Telegram message language: one dictionary per language (jobbot/locales/*.yaml), /lang, English default."""
import ast
import asyncio
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _env import JobbotTestCase
import i18n
import logic

JOBBOT = Path(__file__).resolve().parents[1]
CODE = sorted((JOBBOT / "bot").glob("*.py")) + sorted((JOBBOT / "scripts").glob("*.py"))
# Keys built at run time: t(f"go.closed.{status}"), t(f"rejets.reason.{reason}"), t(f"menu.{name}").
DYNAMIC = {"go.closed": ("sent", "cancelled", "rejected"), "rejets.reason": logic.REJECT_REASONS, "menu": logic.MENU,
           "command": tuple(logic.ALIASES.values())}


def used_keys() -> set[str]:
    keys = set()
    for path in CODE:
        text = path.read_text(encoding="utf-8")
        keys |= set(re.findall(r"""\bt\(\s*["']([a-z_]+(?:\.[a-z_]+)+)["']""", text))
        for a, b in re.findall(r"""\bt\(\s*["']([a-z_.]+)["']\s+if\b[^,()]*?\belse\s+["']([a-z_.]+)["']""", text):
            keys |= {a, b}  # t("a.x" if cond else "a.y", …)
    keys.discard("section.key")  # the i18n.py docstring example
    for prefix, names in DYNAMIC.items():
        keys |= {f"{prefix}.{n}" for n in names}
    return keys


class Catalogs(unittest.TestCase):
    def test_every_language_has_the_same_keys_and_placeholders(self):
        en = i18n.catalog("en")
        self.assertGreater(len(en), 300)
        for code in i18n.available():
            cat = i18n.catalog(code)
            self.assertEqual(sorted(set(en) - set(cat)), [], f"{code}.yaml: missing keys")
            self.assertEqual(sorted(set(cat) - set(en)), [], f"{code}.yaml: keys unknown to en.yaml")
            for key, text in cat.items():
                self.assertEqual(i18n.placeholders(text), i18n.placeholders(en[key]), f"{code}.yaml {key}")

    def test_every_key_used_in_the_code_exists(self):
        en = i18n.catalog("en")
        self.assertEqual(sorted(used_keys() - set(en)), [])

    def test_code_passes_exactly_the_placeholders_of_each_text(self):
        """t("key", a=…, b=…): the keyword names must be the text's {placeholders} (else KeyError at run time)."""
        en = i18n.catalog("en")
        checked = 0
        for path in CODE:
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "t"):
                    continue
                if not node.args or any(k.arg is None for k in node.keywords):
                    continue  # t(**values): checked by the tests that render those messages
                first = node.args[0]
                keys = [first.value] if isinstance(first, ast.Constant) else \
                    [first.body.value, first.orelse.value] if isinstance(first, ast.IfExp) \
                    and isinstance(first.body, ast.Constant) and isinstance(first.orelse, ast.Constant) else []
                given = {k.arg for k in node.keywords}
                for key in keys:
                    self.assertIn(key, en, f"{path.name}:{node.lineno}")
                    self.assertEqual(given, i18n.placeholders(en[key]), f"{path.name}:{node.lineno} {key}")
                    checked += 1
        self.assertGreater(checked, 250)

    def test_no_hard_coded_french_left_in_telegram_code(self):
        """French string literals (docstrings aside) may remain only in file contents and CLI output, never
        in Telegram messages: email.txt / linkedin.txt drafts, offre.pdf, rejection-rules.md, criteria.md
        section names, the scoring vocabulary, the one-time backfill CLI and texguard's diagnostics."""
        allowed = {
            "logic.py": ("Règles de rejet", "vide au départ"),
            "spontaneous.py": ("À : ", "Pièce jointe", "Après envoi", "caractères) :"),  # email.txt / linkedin.txt
            "offer_pdf.py": ("Archivée par JobBot",),
            "offer_queue.py": ("Aperçu", "à ajouter", "ajoutée(s)", "à la file", "affichée sur Telegram", "déjà affichée"),
            "postprocess.py": ("CDD", "présentiel", "télétravail"),
            "prefilter.py": ("Intitulés recherchés", "Exclusions d'intitulé", "Mots-clés métier"),
            "rules.py": ("## Règles",),
            "sites.py": ("liste blanche des sites",),  # header of the whitelist file itself
        }
        skip = {"texguard.py", "import_seed.py", "i18n.py"}
        for path in CODE:
            if path.name in skip:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docs = {id(n.body[0].value) for n in ast.walk(tree)
                    if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs \
                        and re.search(r"[éèàêçùûôîÉÀ]", node.value) \
                        and not any(a in node.value for a in allowed.get(path.name, ())):
                    self.fail(f"{path.name}:{node.lineno}: {node.value[:80]!r}")

    def test_menu_is_plain_text_within_telegram_limits(self):
        for code in i18n.available():
            for name, desc in [(n, i18n.t(f"menu.{n}", code)) for n in logic.MENU]:
                self.assertRegex(name, r"^[a-z0-9_]{1,32}$")
                self.assertTrue(0 < len(desc) <= 256 and "<" not in desc, (code, name, desc))

    def test_scoring_values_are_translated(self):
        self.assertEqual(i18n.tv("contract", "CDI", "en"), "permanent")
        self.assertEqual(i18n.tv("remote", "hybride", "en"), "hybrid")
        self.assertEqual(i18n.tv("remote", "hybride", "fr"), "hybride")
        self.assertEqual(i18n.tv("contract", "Werkvertrag", "en"), "Werkvertrag")  # unknown -> as is


class Fallback(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="jobbot-locales-"))
        (self.dir / "en.yaml").write_text('a:\n  b: "Hello {name}"\n  c: "only in en"\n  d: "{{literal}}"\n', encoding="utf-8")
        (self.dir / "xx.yaml").write_text('a:\n  b: "Salut {name}"\n', encoding="utf-8")
        self.patch = mock.patch.object(i18n, "LOCALES", self.dir)
        self.patch.start()
        i18n._cache.clear()

    def tearDown(self):
        self.patch.stop()
        i18n._cache.clear()
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_missing_key_falls_back_to_english_then_to_the_key(self):
        self.assertEqual(i18n.t("a.b", "xx", name="Ana"), "Salut Ana")
        self.assertEqual(i18n.t("a.c", "xx"), "only in en")
        self.assertEqual(i18n.t("a.d", "xx"), "{literal}")
        self.assertEqual(i18n.t("a.zzz", "xx"), "a.zzz")


class Language(JobbotTestCase):
    def test_english_by_default(self):
        os.environ.pop("JOBBOT_LANG", None)
        self.assertEqual(i18n.lang(), "en")
        self.assertIn("<b>JobBot — commands</b>", logic.cmd_help())
        self.assertIn("karriere, linkedin", logic.cmd_help())
        self.assertIn("Language: <b>English</b> (en)", logic.cmd_lang(""))

    def test_lang_command_switches_and_persists(self):
        os.environ.pop("JOBBOT_LANG", None)
        self.assertIn("Français", logic.cmd_lang("FR"))
        self.assertEqual(i18n.lang(), "fr")
        self.assertIn('"lang": "fr"', (self.tmp / "state" / "settings.json").read_text())
        self.assertIn("<b>JobBot — commandes</b>", logic.cmd_help())
        os.environ["JOBBOT_LANG"] = "en"  # the saved choice wins over the environment
        self.assertEqual(i18n.lang(), "fr")
        self.assertIn("English", logic.cmd_lang("en"))
        self.assertEqual(logic.cmd_voir(""), "Refused: /show needs a number from /queue. Example: /show 2")
        self.assertEqual(logic.cmd_voir("1"), "Run /queue first to get the numbered list.")

    def test_unknown_language_changes_nothing(self):
        self.assertIn("Langue inconnue : de", logic.cmd_lang("de"))
        self.assertEqual(i18n.lang(), "fr")
        self.assertFalse((self.tmp / "state" / "settings.json").exists())

    def test_english_alert_and_status(self):
        import offer_queue as oq

        os.environ["JOBBOT_LANG"] = "en"
        text = oq.format_alert({"short_id": "12", "score": 81, "url": "https://x.at/j/1", "title": "IT Delivery Manager",
                                "company": "ACME", "location": "Wien", "contract": "CDI", "remote": "hybride",
                                "site": "karriere", "variant": "delivery", "adapt": True})
        self.assertIn("Contract: permanent · Remote: hybrid · Salary: not shown", text)
        self.assertIn("CV: delivery · tailoring yes", text)
        self.assertIn("/go 12 · /no 12 [reason]", text)
        self.assertIn("<b>JobBot status</b>", logic.cmd_status())
        self.assertIn("No run recorded.", logic.cmd_status())

    def test_bot_registers_lang_and_publishes_the_menu(self):
        import bot
        from telegram.ext import CommandHandler

        app = bot.build("123:abc", "42")
        by_name = {c: h for h in app.handlers[0] if isinstance(h, CommandHandler) for c in h.commands}
        names = set(by_name)
        self.assertIn("lang", names)
        self.assertTrue(set(logic.MENU) <= names, set(logic.MENU) - names)
        for alias, name in logic.ALIASES.items():  # same command under both names
            self.assertIn(alias, names)
            self.assertIn(42, by_name[alias].filters.chat_ids)
        for code in i18n.available():  # every name shown in a menu is a registered command
            os.environ["JOBBOT_LANG"] = code
            self.assertTrue({n for n, _ in logic.menu_commands()} <= names, code)
        os.environ["JOBBOT_LANG"] = "fr"

        published = []

        class FakeBot:
            async def set_my_commands(self, commands):
                published.append([(c.command, c.description) for c in commands])

        asyncio.run(bot.publish_commands(FakeBot()))
        self.assertIn(("file", "Offres en attente, numérotées"), published[0])
        self.assertEqual(published[0][0][0], "accept")  # alphabetical
        os.environ["JOBBOT_LANG"] = "en"
        asyncio.run(bot.publish_commands(FakeBot()))
        self.assertIn(("queue", "Waiting postings, numbered"), published[1])
        names = [n for n, _ in published[1]]
        self.assertEqual(names, sorted(names))
        self.assertIn(("rejects", "IT postings dropped in the last run"), published[1])

    def test_scoring_batch_carries_the_language(self):
        import prefilter

        for code, language, flag in (("en", "English", "German to check"), ("fr", "French", "allemand à vérifier")):
            os.environ["JOBBOT_LANG"] = code
            fields = {"language": i18n.t("scoring.language"),
                      "flag_labels": {k: i18n.t(f"scoring.flag.{k}") for k in prefilter.SCORING_FLAGS}}
            self.assertEqual(fields["language"], language)
            self.assertEqual(fields["flag_labels"]["german_check"], flag)
        src = (JOBBOT / "scripts" / "prefilter.py").read_text(encoding="utf-8")
        self.assertIn('"language": t("scoring.language")', src)
        prompt = (JOBBOT / "commands" / "jobbot-scan.md").read_text(encoding="utf-8")
        self.assertIn("in the batch's `language`", prompt)
        self.assertNotIn("in French", prompt)


if __name__ == "__main__":
    unittest.main()
