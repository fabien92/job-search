#!/usr/bin/env python3
"""Rule-based scoring: the `scoring: rules` mode of schedule.yaml — no AI, no Claude account.

    jobbot/.venv/bin/python jobbot/scripts/rule_scorer.py --run-id <id>

Reads jobbot/state/runs/<id>-batch.json (written by prefilter.py) and writes <id>-scores.json in
the exact shape the `/jobbot-scan` prompt asks Claude for, so postprocess.py handles both modes
the same way. The hard exclusions (titles, types, companies, regions, age, duplicates) were
already applied by the pre-filter; this step only ranks what is left.

Score (0-100), from jobbot/config/criteria.md:
    35                                     base
  + 30  the posting title contains every word of one target title ("Target titles", EN or DE)
  + 15  else: the posting title contains one of the "Keywords"
  +  6  per "Strong" keyword of "Scoring profile" found in the title or text (4 at most)
  +  2  per "Secondary" keyword found (5 at most)
A posting whose title matches a target title therefore reaches 65, above the default alert
threshold of 60; one that does not needs keywords from the text to get there.

Optional section "## Rules mode" of criteria.md:
    Reject : term · term      the posting is rejected when its title or text contains one of them
    Flag : term · term        the posting is kept, with a flag naming the term found
The CV variant is always `default_variant` (schedule.yaml) and the CV is never adapted.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import common
import prefilter

BASE, TITLE_MATCH, KEYWORD_IN_TITLE = 35, 30, 15
STRONG_POINTS, STRONG_MAX = 6, 4
SECONDARY_POINTS, SECONDARY_MAX = 2, 5
PROFILE_SECTION = ("Scoring profile",)
RULES_SECTION = ("Rules mode",)
STRONG_LABELS = ("Strong", "Strong points")
SECONDARY_LABELS = ("Secondary",)
_NOTE = re.compile(r"\s*\([^)]*\)\s*")  # "Strong (raise the score) : a · b" -> "Strong : a · b"
_WORD = re.compile(r"[\w+#.]+", re.UNICODE)


def enabled(schedule: dict | None = None) -> bool:
    """True when schedule.yaml says `scoring: rules` (no AI). Anything else means Claude."""
    schedule = common.load_schedule() if schedule is None else schedule
    return str(schedule.get("scoring") or "claude").strip().lower() in ("rules", "rule", "none", "off")


def _labelled(block: str, labels: tuple[str, ...]) -> list[str]:
    """Items of the "<label> : a · b" lines of a section; bold markers and bracketed notes are ignored."""
    cleaned = "\n".join(_NOTE.sub(" ", line.replace("**", "")) for line in block.splitlines())
    items: list[str] = []
    for label in labels:
        for item in prefilter._dot_list(cleaned, label):
            if item and item not in items:
                items.append(item)
    return items


def load_rules() -> dict:
    """Everything the score needs from criteria.md."""
    text = (common.config_dir() / "criteria.md").read_text(encoding="utf-8")
    criteria = prefilter.load_criteria()
    profile = prefilter._section(text, PROFILE_SECTION)
    rules = prefilter._section(text, RULES_SECTION)
    return {
        "titles": criteria["titles_en"] + criteria["titles_de"],
        "keywords": criteria["keywords"],
        "strong": _labelled(profile, STRONG_LABELS),
        "secondary": _labelled(profile, SECONDARY_LABELS),
        "reject": _labelled(rules, ("Reject",)),
        "flag": _labelled(rules, ("Flag",)),
    }


def _words(value: str) -> list[str]:
    return [w.casefold() for w in _WORD.findall(value or "")]


def _contains(haystack: str, term: str) -> bool:
    """Whole-word, case-insensitive search of a term (one or several words)."""
    term = term.strip()
    if not term:
        return False
    return re.search(r"(?<![\w])" + re.escape(term) + r"(?![\w])", haystack, re.IGNORECASE) is not None


def title_matches(job_title: str, targets: list[str]) -> str | None:
    """The first target title whose every word appears in the posting title, else None."""
    have = set(_words(job_title))
    for target in targets:
        words = [w for w in _words(target) if len(w) > 1]
        if words and all(w in have for w in words):
            return target
    return None


def score_job(job: dict, text: str, rules: dict, variant: str | None) -> dict:
    title = str(job.get("title") or "")
    body = f"{title}\n{text}"
    parts: list[str] = []
    score = BASE
    target = title_matches(title, rules["titles"])
    if target:
        score += TITLE_MATCH
        parts.append(f"title: {target}")
    else:
        keyword = next((k for k in rules["keywords"] if _contains(title, k)), None)
        if keyword:
            score += KEYWORD_IN_TITLE
            parts.append(f"keyword in title: {keyword}")
    strong = [k for k in rules["strong"] if _contains(body, k)][:STRONG_MAX]
    secondary = [k for k in rules["secondary"] if _contains(body, k)][:SECONDARY_MAX]
    score += STRONG_POINTS * len(strong) + SECONDARY_POINTS * len(secondary)
    if strong:
        parts.append("strong: " + ", ".join(strong))
    if secondary:
        parts.append("secondary: " + ", ".join(secondary))
    rejected = next((k for k in rules["reject"] if _contains(body, k)), None)
    flags = [f"check: {k}"[:40] for k in rules["flag"] if _contains(body, k)][:4]
    if job.get("detail_failed"):
        flags.append("posting text unavailable")
    if (job.get("guard") or {}).get("alarm"):
        flags.append("suspicious text")
    if rejected:
        justification = f"Rules: contains \"{rejected}\""
    else:
        justification = "Rules: " + (" · ".join(parts) if parts else "no target title or keyword found")
    return {
        "ref": job["ref"],
        "score": max(0, min(100, score)),
        "reject_reason": "rejection_rule" if rejected else None,
        "flags": flags,
        "duplicate_of": None,
        "contract": "unknown",
        "remote": "unknown",
        "salary": job.get("salary") if isinstance(job.get("salary"), str) else None,
        "justification": justification[:160],
        "variant": None if rejected else variant,
        "adapt": False,
        "adapt_reason": None,
    }


def default_variant(schedule: dict) -> str | None:
    import postprocess

    wanted = str(schedule.get("default_variant") or "").strip()
    known = postprocess.known_variants()
    if wanted in known:
        return wanted
    return sorted(known)[0] if known else None


def _read_text(path) -> str:
    try:
        return Path(str(path)).read_text(encoding="utf-8", errors="replace") if path else ""
    except OSError:
        return ""


def run(run_id: str) -> Path:
    """Score the batch; returns the path of a result file shaped like `claude -p --output-format json`."""
    runs = common.runs_dir()
    batch = json.loads((runs / f"{run_id}-batch.json").read_text(encoding="utf-8"))
    rules = load_rules()
    variant = default_variant(common.load_schedule())
    scores = []
    for job in batch.get("jobs") or []:
        try:
            scores.append(score_job(job, _read_text(job.get("text_path")), rules, variant))
        except Exception as exc:  # noqa: BLE001 - one posting must not stop the run: it stays unscored
            common.log(f"rule_scorer: {job.get('ref')}: {type(exc).__name__}: {exc}")
    common.atomic_write_json(runs / f"{run_id}-scores.json", {"run_id": run_id, "scores": scores})
    out = runs / f"{run_id}-claude.json"
    out.write_text(json.dumps({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0.0,
                               "result": f"{len(scores)} postings scored by rules (no AI)"}), encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", required=True)
    args = ap.parse_args(argv)
    print(run(args.run_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
