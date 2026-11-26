"""`scoring: rules` (schedule.yaml): keyword score from criteria.md, no AI, no Claude account."""

import json
import os

from _env import JobbotTestCase
import common
import logic
import postprocess
import preflight
import rule_scorer

CRITERIA = """# Criteria

## Target titles

EN : IT Project Manager · Release Manager

DE : IT-Projektleiter

## Keywords

DORA · CI/CD

## Title exclusions

Head of

## Type exclusions

Internship

## Excluded companies

Deloitte

## Scoring profile

- Strong (raise the score) : IT delivery · CI/CD · project manager
- **Secondary** : python · jira
- Not wanted: see rejection-rules.md

## Rules mode

- Reject : verhandlungssicher · native German
- Flag : fließend
"""


class Scoring(JobbotTestCase):
    def setUp(self):
        super().setUp()
        (self.config / "criteria.md").write_text(CRITERIA, encoding="utf-8")
        self.rules = rule_scorer.load_rules()

    def score(self, title, text="", **job):
        return rule_scorer.score_job({"ref": "b1", "title": title, **job}, text, self.rules, "delivery")

    def test_rules_are_read_from_criteria(self):
        self.assertEqual(self.rules["titles"], ["IT Project Manager", "Release Manager", "IT-Projektleiter"])
        self.assertEqual(self.rules["strong"], ["IT delivery", "CI/CD", "project manager"])
        self.assertEqual(self.rules["secondary"], ["python", "jira"])
        self.assertEqual(self.rules["reject"], ["verhandlungssicher", "native German"])
        self.assertEqual(self.rules["flag"], ["fließend"])

    def test_title_match_alone_passes_the_default_threshold(self):
        s = self.score("Senior IT Project Manager (m/w/d)")
        # 35 base + 30 title + 6 ("project manager" is also a strong keyword, found in the title)
        self.assertEqual((s["score"], s["reject_reason"], s["variant"], s["adapt"]), (71, None, "delivery", False))
        self.assertGreaterEqual(s["score"], common.load_schedule()["alert_threshold"])
        self.assertIn("title: IT Project Manager", s["justification"])

    def test_keywords_add_up_and_are_capped(self):
        s = self.score("Koordinator", "IT delivery with CI/CD, Python and Jira. CI/CD again.")
        self.assertEqual(s["score"], 35 + 2 * 6 + 2 * 2)
        s = self.score("DORA Programme Lead")
        self.assertEqual(s["score"], 35 + 15, "a keyword in the title when no target title matches")

    def test_whole_words_only(self):
        self.assertEqual(self.score("Koordinator", "pythonic jirafe")["score"], 35)

    def test_reject_and_flag_terms(self):
        s = self.score("IT Project Manager", "Deutsch verhandlungssicher erforderlich")
        self.assertEqual((s["reject_reason"], s["variant"]), ("rejection_rule", None))
        self.assertIn("verhandlungssicher", s["justification"])
        s = self.score("IT Project Manager", "Deutsch fließend von Vorteil")
        self.assertIsNone(s["reject_reason"])
        self.assertEqual(s["flags"], ["check: fließend"])

    def test_output_is_accepted_by_postprocess(self):
        clean, problems = postprocess.validate_scores({"scores": [self.score("Release Manager", salary="60k")]}, {"b1"})
        self.assertEqual(problems, [])
        self.assertEqual((clean["b1"]["score"], clean["b1"]["salary"], clean["b1"]["contract"]), (65, "60k", "unknown"))

    def test_run_writes_scores_and_a_success_result(self):
        runs = common.runs_dir()
        runs.mkdir(parents=True, exist_ok=True)
        text = self.tmp / "posting.txt"
        text.write_text("CI/CD and Jira", encoding="utf-8")
        common.atomic_write_json(runs / "r1-batch.json", {"jobs": [
            {"ref": "b1", "title": "Release Manager", "text_path": str(text)},
            {"ref": "b2", "title": "Koch", "text_path": str(self.tmp / "missing.txt")}]})
        out = rule_scorer.run("r1")
        scores = json.loads((runs / "r1-scores.json").read_text())["scores"]
        self.assertEqual([(s["ref"], s["score"]) for s in scores], [("b1", 35 + 30 + 6 + 2), ("b2", 35)])
        info = postprocess.read_claude_output(out)
        self.assertEqual((info["is_error"], info["total_cost_usd"]), (False, 0.0))
        self.assertIsNone(postprocess.classify_failure(info, 0))


class Mode(JobbotTestCase):
    def set_scoring(self, value):
        path = self.config / "schedule.yaml"
        path.write_text(path.read_text() + f"scoring: {value}\n")

    def test_default_is_claude(self):
        self.assertFalse(rule_scorer.enabled({}))
        self.assertFalse(rule_scorer.enabled({"scoring": "claude"}))
        self.assertTrue(rule_scorer.enabled({"scoring": "Rules"}))

    def test_preflight_does_not_ask_for_a_claude_token_in_rules_mode(self):
        secrets = {"TELEGRAM_TOKEN": "t", "TELEGRAM_CHAT_ID": "1"}
        self.assertEqual(preflight.check_secrets(secrets, claude=True)["status"], "fail")
        self.assertEqual(preflight.check_secrets(secrets, claude=False)["status"], "ok")
        self.assertEqual(preflight.check_claude_token(secrets, 30, claude=False)["status"], "ok")
        self.assertEqual(preflight.check_claude_token(secrets, 30, claude=True)["status"], "fail")
        self.set_scoring("rules")
        self.assertFalse(preflight.uses_claude())

    def test_a_portal_set_to_zero_queries_is_not_required(self):
        skills = preflight.portal_skills({"queries_per_run": {"karriere": 3, "linkedin": 0}})
        self.assertIn("karriere-search", skills)
        self.assertNotIn("linkedin-search", skills)

    def test_claude_only_commands_are_refused_in_rules_mode(self):
        self.set_scoring("rules")
        os.environ["JOBBOT_LANG"] = "en"
        self.assertIn("needs Claude", logic.cmd_discover("wien"))
        self.assertIn("needs Claude", logic.cmd_spont("ACME"))
