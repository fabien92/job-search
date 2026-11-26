#!/usr/bin/env python3
"""Scan stage 3 (zero tokens): validate Claude's scores, record every job seen, alert, summarise.

    jobbot/.venv/bin/python jobbot/scripts/postprocess.py --run-id <id> [--claude-output FILE] [--claude-exit N] [--no-claude]

Records (skipped with JOBBOT_DRY_RUN=1, SPEC §12):
  * jobbot/state/seen_index.json  — every job seen (rule rejects, Claude rejects, low scores, alerts) + reason
  * job_scraper/seen_jobs.json    — same jobs, via upstream tools/scrape_state.py `store` (atomic upstream write)
  * jobbot/state/site_stats.json  — results per site per day (zero-results monitoring)
  * jobbot/config/sites.yaml      — `pending` hosts (blocked portal domains, denied WebFetch hosts)
  * jobbot/state/telegram_msgs.json — message id of each alert (written when the queue shows it)
  * jobbot/state/offer_queue.json — V5: alerts wait there, one shown at a time (offer_queue.py)
  * jobbot/state/postings/<ID>.md   — cleaned posting of every job Claude kept (for /go, V2)
In dry run, alerted jobs go to jobbot/state/runs/<id>-alerts.json (T-IDs, for a /go test) and
their postings to <cache>/test-postings/.
Always writes jobbot/state/runs/<id>.json (marked dry_run when testing) and sends the Telegram alerts.
Jobs Claude did not score are not recorded: they come back next run.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
import tempfile
from collections import Counter
from pathlib import Path

import applications
import common
import dedup
import offer_queue
import sites
from ats import vendors
import telegram_send as tg

if str(common.TOOLS) not in sys.path:
    sys.path.insert(0, str(common.TOOLS))

REJECT_REASONS = {
    "german_level", "contract_short", "freelance", "internship", "title_excluded", "company_excluded", "location",
    "remote_region", "pure_developer", "not_it", "expired", "duplicate", "rejection_rule", "other",
}
# Fixed scoring codes (the bot translates them for display: locales/*.yaml, `values`).
CONTRACTS = {"permanent", "fixed_term_long", "fixed_term_short", "fixed_term_unknown", "part_time", "freelance", "unknown"}
REMOTES = {"onsite", "hybrid", "remote", "unknown"}
# Codes written before the vocabulary was switched to English: still accepted, stored as the new ones.
# State files written earlier keep the old values; the locale files translate both.
LEGACY_CODES = {
    "CDI": "permanent", "CDD ≥ 12 mois": "fixed_term_long", "CDD < 12 mois": "fixed_term_short",
    "CDD durée inconnue": "fixed_term_unknown", "temps partiel": "part_time", "inconnu": "unknown",
    "présentiel": "onsite", "hybride": "hybrid", "100 % télétravail": "remote",
}
DEFAULT_VARIANTS = ("delivery", "techlead", "international-orgs", "support-it-manager")


def known_variants() -> set[str]:
    """CV variants Claude may pick (SPEC §9.1): those of the block CV, else the shipped four."""
    import build_cv_variants

    found = build_cv_variants.variants() if (common.cv_dir() / "variants").is_dir() else []
    return set(found or DEFAULT_VARIANTS)
AUTH_OR_QUOTA = re.compile(
    r"rate.?limit|usage limit|quota|credit balance|billing|overloaded|authenticat|unauthori[sz]ed|invalid api key|"
    r"oauth|log ?in|token (?:has )?expired|\b401\b|\b403\b|\b429\b", re.IGNORECASE)


def _text(value, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    value = " ".join(value.split())
    return value[:limit] or None


def _choice(value, allowed, default):
    """value when it is one of the allowed strings, else default. A list or an object written by the
    model in place of a string is simply not a valid choice (testing it against a set would raise)."""
    if isinstance(value, str):
        value = LEGACY_CODES.get(value, value)
    return value if isinstance(value, str) and value in allowed else default


def validate_scores(doc, refs: set[str]) -> tuple[dict[str, dict], list[str]]:
    """-> ({ref: clean score}, problems). Invalid entries are dropped (left unscored), never guessed.
    Never raises on the model's output: a wrongly typed field is a problem line or a default value."""
    problems: list[str] = []
    if not isinstance(doc, dict) or not isinstance(doc.get("scores"), list):
        return {}, ["scores file has no `scores` list"]
    out: dict[str, dict] = {}
    variants = known_variants()
    for i, raw in enumerate(doc["scores"]):
        if not isinstance(raw, dict) or not isinstance(raw.get("ref"), str) or raw["ref"] not in refs:
            problems.append(f"entry {i}: unknown or missing ref")
            continue
        score = raw.get("score")
        if isinstance(score, float) and score.is_integer():
            score = int(score)
        if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
            problems.append(f"{raw['ref']}: score must be an integer 0-100")
            continue
        reason = raw.get("reject_reason")
        if reason is not None:
            reason = _choice(reason, REJECT_REASONS, "other")
        flags = [f for f in (_text(x, 40) for x in (raw["flags"] if isinstance(raw.get("flags"), list) else [])) if f][:6]
        dup = raw.get("duplicate_of")
        out[raw["ref"]] = {
            "score": score,
            "reject_reason": reason,
            "flags": flags,
            "duplicate_of": str(dup).lstrip("#") if isinstance(dup, (str, int)) and str(dup).strip() else None,
            "contract": _choice(raw.get("contract"), CONTRACTS, "unknown"),
            "remote": _choice(raw.get("remote"), REMOTES, "unknown"),
            "salary": _text(raw.get("salary"), 80),
            "justification": _text(raw.get("justification"), 200),
            # SPEC §9.1: chosen in the same scoring call. Unknown variant -> None (go.py falls back).
            "variant": _choice(raw.get("variant"), variants, None),
            "adapt": raw.get("adapt") is True or str(raw.get("adapt")).strip().lower() in ("oui", "yes", "true"),
            "adapt_reason": _text(raw.get("adapt_reason"), 160),
        }
    return out, problems


def read_claude_output(path: Path | None) -> dict:
    info = {"ran": path is not None, "is_error": False, "subtype": None, "total_cost_usd": 0.0, "error": None,
            "permission_denials": []}
    if path is None:
        return info
    try:
        raw = path.read_text(encoding="utf-8").strip()
        doc = json.loads(raw.splitlines()[-1] if raw and not raw.startswith("{") else raw or "{}")
    except (OSError, json.JSONDecodeError, IndexError) as exc:
        info.update(is_error=True, error=f"unreadable claude output: {exc}")
        return info
    if isinstance(doc, list):  # stream-style array: take the result message
        doc = next((m for m in reversed(doc) if isinstance(m, dict) and m.get("type") == "result"), {})
    info["is_error"] = bool(doc.get("is_error"))
    info["subtype"] = doc.get("subtype")
    try:
        info["total_cost_usd"] = round(float(doc.get("total_cost_usd") or 0.0), 4)
    except (TypeError, ValueError):
        info["total_cost_usd"] = 0.0
    if info["is_error"] or (info["subtype"] and info["subtype"] != "success"):
        errors = doc.get("errors") or []
        info["error"] = _text(" | ".join(map(str, errors)) or str(doc.get("result") or info["subtype"]), 500)
    info["permission_denials"] = [d for d in (doc.get("permission_denials") or []) if isinstance(d, dict)]
    return info


def classify_failure(info: dict, exit_code: int | None) -> str | None:
    """None when Claude succeeded; else budget | auth_or_quota | error."""
    if not info["ran"]:
        return None
    if info["subtype"] == "error_max_budget_usd":
        return "budget"
    failed = info["is_error"] or (exit_code not in (None, 0)) or (info["subtype"] not in (None, "success"))
    if not failed:
        return None
    if AUTH_OR_QUOTA.search(info.get("error") or ""):
        return "auth_or_quota"
    return "error"


def denied_hosts(info: dict) -> list[dict]:
    out = []
    for denial in info["permission_denials"]:
        if denial.get("tool_name") != "WebFetch":
            continue
        url = (denial.get("tool_input") or {}).get("url")
        host = sites.host_of(url) if isinstance(url, str) else None
        if host:
            out.append({"host": host, "requested_by": url})
    return out


def fit_band(score: int | None, threshold: int) -> str:
    if score is None:
        return "low"
    return "high" if score >= threshold else "medium" if score >= 40 else "low"


format_alert = offer_queue.format_alert  # V5: moved to offer_queue.py (the queue rebuilds alerts)


def store_upstream(entries: list[dict], today: str) -> dict:
    """Write through upstream scrape_state.run() so seen_jobs.json keeps its atomic upstream writer."""
    import scrape_state

    jobs = [{
        "title": e["title"], "company": e.get("company"), "url": e["url"], "location": e.get("location"),
        "first_seen": today, "posted_date": e.get("date"), "deadline": e.get("valid_through"),
        "fit": e["fit"], "status": "skipped" if e["status"] in ("rejected", "duplicate") else "new",
        "portal": f"{e['site']}-search", "source": "cli",
        "jobbot_id": e["short_id"], "jobbot_reason": e.get("reason"), "jobbot_score": e.get("score"),
    } for e in entries]
    if not jobs:
        return {"added": []}
    with tempfile.NamedTemporaryFile("w", suffix=".json", dir=common.state_dir(), delete=False, encoding="utf-8") as fh:
        json.dump(jobs, fh, ensure_ascii=False)
        tmp = Path(fh.name)
    try:
        ns = argparse.Namespace(command="store", results=tmp, state=common.upstream_seen_path(), tracker=common.tracker_path())
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            scrape_state.run(ns)
        return json.loads(out.getvalue() or "{}")
    finally:
        tmp.unlink(missing_ok=True)


def archive_postings(entries: list[dict], texts: dict[int, dict]) -> int:
    """Copy the cleaned posting of each kept job out of the 7-day cache (for /go). Never fatal."""
    count = 0
    for e in entries:
        job = texts.get(id(e))
        if not job or not job.get("text_path"):
            continue
        try:
            text = Path(job["text_path"]).read_text(encoding="utf-8")
            applications.archive_posting(e["short_id"], job, text)
            count += 1
        except OSError as exc:
            common.log(f"postprocess: posting {e['short_id']} not archived: {exc}")
    return count


def prune_site_stats(stats: dict, retention_days: int, today: str) -> int:
    """Drop the per-day counters older than the ledger retention window. -> days removed."""
    if retention_days <= 0:
        return 0
    try:
        cutoff = (common.dt.date.fromisoformat(today) - common.dt.timedelta(days=retention_days)).isoformat()
    except ValueError:
        return 0
    removed = 0
    for site in list(stats):
        per_day = stats[site]
        if not isinstance(per_day, dict):
            continue
        for day in [d for d in per_day if isinstance(d, str) and d < cutoff]:
            del per_day[day]
            removed += 1
        if not per_day:
            del stats[site]
    return removed


def run(run_id: str, claude_output: Path | None, claude_exit: int | None, no_claude: bool) -> dict:
    schedule = common.load_schedule()
    threshold = int(schedule["alert_threshold"])
    runs = common.runs_dir()
    pre = common.read_json(runs / f"{run_id}-prefilter.json")
    if pre is None:
        raise ValueError(f"{run_id}-prefilter.json missing — prefilter did not run")
    to_score = pre.get("to_score") or []
    refs = {j["ref"] for j in to_score}

    info = read_claude_output(None if no_claude else claude_output)
    failure = classify_failure(info, claude_exit)
    scores, problems = {}, []
    scores_path = runs / f"{run_id}-scores.json"
    if refs and not no_claude:
        # A truncated or invalid file (budget or timeout reached while writing it) is the same case as
        # a missing one: nothing is scored, the run is reported as failed, the postings come back.
        try:
            doc = common.read_json(scores_path) if scores_path.exists() else None
        except (OSError, ValueError) as exc:
            doc = None
            problems.append(f"scores file unreadable: {str(exc)[:200]}")
        if doc is None:
            problems = problems or ["scores file missing"]
        else:
            scores, problems = validate_scores(doc, refs)

    now_iso = common.iso()
    today = common.local_now().date().isoformat()
    dry = common.dry_run()
    entries: list[dict] = []

    def entry_for(job: dict, status: str, reason: str | None, extra: dict | None = None) -> dict:
        e = {k: job.get(k) for k in ("site", "id", "key", "title", "company", "location", "date", "valid_through", "url",
                                     "url_clean", "employer_url", "triple", "query", "region")}
        e.update({"first_seen": now_iso, "status": status, "reason": reason, "run_id": run_id})
        e.update(extra or {})
        return e

    for job in pre.get("rejected") or []:
        extra = {"score": None, "fit": "low", "by": "rules"}
        if job.get("republished_of"):  # V4: the posting this one repeats
            extra["republished_of"] = job["republished_of"]
        entries.append(entry_for(job, "rejected", job.get("reason"), extra))
    unscored = 0
    texts: dict[int, dict] = {}  # id(entry) -> job, for the posting archive
    for job in to_score:
        s = scores.get(job["ref"])
        if s is None:
            unscored += 1
            continue
        if s["reject_reason"]:
            status = "duplicate" if s["reject_reason"] == "duplicate" else "rejected"
        else:
            status = "alerted" if s["score"] >= threshold else "low"
        entries.append(entry_for(job, status, s["reject_reason"], {
            **s, "fit": fit_band(s["score"], threshold), "by": "claude",
            "salary": s["salary"] or job.get("salary"), "guard_alarm": (job.get("guard") or {}).get("alarm", False)}))
        if status in ("alerted", "low"):
            texts[id(entries[-1])] = job

    blocked = list(pre.get("blocked_hosts") or []) + denied_hosts(info)

    with common.state_lock():
        ledger = dedup.Ledger.load()
        for e in entries:
            e["short_id"] = ("T" if dry else "") + ledger.allocate_id()
            if not dry:
                ledger.add(e["key"], e)
        if dry:
            store_result = {"added": [], "skipped": "dry_run"}
        else:
            try:
                store_result = store_upstream(entries, today)
            except (ValueError, OSError, SystemExit) as exc:  # the JobBot ledger still records the run
                store_result = {"added": [], "error": str(exc)[:300]}
                common.log(f"postprocess: upstream store failed: {exc}")
        archived = archive_postings(entries, texts)
        new_pending = []
        pruned = 0
        if not dry:
            retention_days, circumstantial_days = dedup.retention_settings(schedule)
            pruned = ledger.prune(retention_days, circumstantial_days)
            ledger.save()
            stats_path = common.state_dir() / "site_stats.json"
            stats = common.read_json(stats_path, {}) or {}
            for site, s in (pre.get("sites") or {}).items():
                day = stats.setdefault(site, {}).setdefault(today, {"results": 0, "queries": 0, "errors": 0})
                for k in ("results", "queries", "errors"):
                    day[k] += int(s.get(k) or 0)
            prune_site_stats(stats, retention_days, today)
            common.atomic_write_json(stats_path, stats)
            if blocked:
                data = sites.load()
                for b in blocked:  # V3: recruiting-software groups carry the vendor documentation as note
                    if vendors.add_pending(data, b["host"], b.get("requested_by"), today, b.get("note")):
                        new_pending.append(b["host"])
                sites.save(data)
                with open(common.state_dir() / "blocked_hosts.log", "a", encoding="utf-8") as fh:
                    for b in blocked:
                        fh.write(f"{now_iso}\t{b['host']}\t{b.get('requested_by') or ''}\t{run_id}\n")

    alerts = sorted((e for e in entries if e["status"] == "alerted"), key=lambda e: -e["score"])
    if dry and alerts:
        common.atomic_write_json(runs / f"{run_id.removesuffix('-test')}-test-alerts.json", {"run_id": run_id, "jobs": {
            e["short_id"]: {**e, "message_id": None} for e in alerts}})
    # V5: one offer at a time. The alerts join the queue; the best is shown if none is, otherwise one short note.
    shown = 0
    if alerts:
        queued = offer_queue.enqueue(alerts, dry)
        if queued["busy"]:
            if queued["new"]:
                tg.send(offer_queue.arrival_note(queued["new"], queued["waiting"]))
        elif offer_queue.pump(dry):
            shown = 1

    rejected_by = Counter(e["reason"] or "?" for e in entries if e["status"] in ("rejected", "duplicate"))
    claude_status = "skipped" if (no_claude or not refs) else ("failed" if failure else "ok")
    status = "ok"
    if failure or (refs and not no_claude and problems and not scores):
        status = "failed"
    summary = {
        "run_id": run_id,
        "dry_run": dry,
        "site": pre.get("site"),
        "started": pre.get("started"),
        "finished": common.iso(),
        "status": status,
        "sites": pre.get("sites") or {},
        "skipped_sites": pre.get("skipped_sites") or [],
        "seen": sum(int(s.get("results") or 0) for s in (pre.get("sites") or {}).values()),
        "new": len(pre.get("rejected") or []) + len(to_score),
        "duplicates": pre.get("duplicates") or {},
        "scored": len(scores),
        "unscored": unscored,
        "alerted": len(alerts),
        "alerts_sent": shown,  # V5: offers shown now; the others wait in the queue (/file)
        "low": sum(1 for e in entries if e["status"] == "low"),
        "rejected_by_reason": dict(rejected_by),
        "deferred": pre.get("deferred", 0),
        "cap_reached": pre.get("cap_reached", False),
        "blocked_hosts": blocked,
        "new_pending_hosts": new_pending,
        "errors": pre.get("errors") or [],
        "score_problems": problems[:20],
        "postings_archived": archived,
        "ledger_pruned": pruned,
        "upstream_store": {k: (len(v) if isinstance(v, list) else v) for k, v in store_result.items()},
        "claude": {"status": claude_status, "failure": failure, "subtype": info["subtype"], "error": info["error"]},
        "total_cost_usd": info["total_cost_usd"],
    }
    common.atomic_write_json(runs / f"{run_id}.json", summary)
    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--claude-output", type=Path)
    ap.add_argument("--claude-exit", type=int)
    ap.add_argument("--no-claude", action="store_true", help="nothing was sent to Claude (empty batch)")
    args = ap.parse_args(argv)
    try:
        summary = run(args.run_id, args.claude_output, args.claude_exit, args.no_claude)
    except (OSError, ValueError) as exc:
        print(f"postprocess: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({k: summary[k] for k in ("status", "seen", "new", "scored", "alerted", "total_cost_usd")}))
    return 0 if summary["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
