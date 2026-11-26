"""Telegram command logic, free of python-telegram-bot so it is testable offline.

Every function returns the HTML reply text. State writes go through the state lock.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import applications as apps  # noqa: E402
import common  # noqa: E402
import companies  # noqa: E402
import contacts  # noqa: E402
import dedup  # noqa: E402
import followup  # noqa: E402
import offer_queue as oq  # noqa: E402
import gen_settings  # noqa: E402
import rules as rulesmod  # noqa: E402
import sites  # noqa: E402
import telegram_send as tg  # noqa: E402
from telegram_send import esc, link  # noqa: E402
from i18n import t, tv  # noqa: E402,F401
import i18n  # noqa: E402

PORTAL_NAMES = ("karriere", "linkedin", "derstandard", "uncareers", "unido", "osce", "opecfund", "hays", "jobgether", "randstad", "profession", "kariera", "michaelpage", "companies")

def help_text() -> str:
    return t("help.text", portals=", ".join(PORTAL_NAMES))


# ------------------------------------------------------------------ helpers

def error_text(exc: BaseException) -> str:
    """The reply for a command that raised: what to repair when it is known, else the error name."""
    if isinstance(exc, common.LockBusy):
        return t("bot.busy")
    if isinstance(exc, common.CorruptState):
        return t("bot.corrupt_state", file=esc(exc.path.name))
    if isinstance(exc, apps.TrackerMalformed):
        return t("bot.tracker_malformed", line=exc.line, company=esc(exc.company))
    return t("bot.error", name=type(exc).__name__)


def parse_selection(text: str, count: int) -> list[int] | None:
    """'1 3-5' / '1,3' / 'all' -> sorted 1-based indices within 1..count; None if malformed or out of range."""
    text = (text or "").strip().lower()
    if not text:
        return None
    if text in ("all", "tout", "tous"):
        return list(range(1, count + 1))
    out: set[int] = set()
    for token in re.split(r"[\s,;]+", text):
        if not token:
            continue
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", token)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        if a > b or a < 1 or b > count:
            return None
        out.update(range(a, b + 1))
    return sorted(out) or None


def numbering_path() -> Path:
    return common.state_dir() / "pending_numbering.json"


def current_numbering(data: dict | None = None, refresh: bool = False) -> list[str]:
    """The numbered pending list shown in the last recap; refreshed when absent or asked."""
    data = data or sites.load()
    pending = [p["domain"] for p in sorted(data["pending"], key=lambda p: (p.get("first_seen") or "", p["domain"]))]
    saved = common.read_json(numbering_path(), None)
    if refresh or not isinstance(saved, list):
        common.atomic_write_json(numbering_path(), pending)
        return pending
    return saved


def pending_list_text(refresh: bool = True) -> str:
    data = sites.load()
    domains = current_numbering(data, refresh=refresh)
    if not domains:
        return t("sites.none")
    by = {p["domain"]: p for p in data["pending"]}
    lines = [t("sites.title")]
    for i, domain in enumerate(domains, 1):
        p = by.get(domain)
        if not p:
            lines.append(t("sites.done", n=i, domain=esc(domain)))
            continue
        site_url = "https://" + (domain[2:] if domain.startswith("*.") else domain)
        req = p.get("requested_by")
        via = t("sites.requested_by", link=link(req)) if req and str(req).startswith("http") else (f" — {esc(req)}" if req else "")
        lines.append(f"{i}. {link(site_url, domain)}{via} ({int(p.get('count') or 1)}×)")
        if p.get("note"):  # V3 group proposal: "Personio group — official domain checked on … : <doc>"
            note = str(p["note"])
            doc = re.search(r"https://\S+$", note)
            lines.append("   <i>" + (esc(note[:doc.start()]) + link(doc.group(0)) if doc else esc(note)) + "</i>")
    lines.append(t("sites.answer"))
    return "\n".join(lines)


# ------------------------------------------------------------------ commands

def cmd_help() -> str:
    return help_text()


# Telegram command menu (bot.py publishes it at start and after /lang); descriptions: menu.<command>.
MENU = ("file", "voir", "go", "sent", "cancel", "reply", "no", "pending", "search", "status", "rejets", "rules", "rule",
        "firma", "sites", "allow", "deny", "spont", "discover", "companies", "accept", "reject", "block", "blocked",
        "unblock", "region", "regions", "health", "lang", "help")


# English names accepted for the French-named commands (bot.py registers both; command.<name> picks the menu one).
ALIASES = {"queue": "file", "show": "voir", "rejects": "rejets", "company": "firma"}


def command_name(name: str) -> str:
    """The name shown for a command in the current language (menu, help): /queue in English, /file in French."""
    return t(f"command.{name}") if name in ALIASES.values() else name


def menu_commands() -> list[tuple[str, str]]:
    """Alphabetical on the name shown (it depends on the language: /queue in English, /file in French)."""
    return sorted(((command_name(name), t(f"menu.{name}")) for name in MENU), key=lambda c: c[0])


def cmd_lang(args: str) -> str:
    """/lang: current language and choices; /lang <code>: switch (saved in state/settings.json)."""
    code = (args or "").strip().lower()
    choices = " | ".join(i18n.available())
    if not code:
        current = i18n.lang()
        return t("lang.current", name=t("lang.self_name"), code=current, choices=choices)
    if code not in i18n.available():
        return t("lang.unknown", code=esc(code), choices=choices)
    i18n.set_lang(code)
    return t("lang.set", name=t("lang.self_name"))


def cmd_no(args: str) -> str:
    parts = (args or "").strip().split(None, 1)
    if not parts:
        return t("no.usage")
    short_id = parts[0].lstrip("#")
    motif = " ".join(parts[1].split()) if len(parts) > 1 else ""
    if len(motif) > 300 or "\n" in motif:
        return t("no.too_long")
    if apps.is_test_id(short_id):
        return _no_test(short_id)
    with common.state_lock():
        ledger = dedup.Ledger.load()
        found = ledger.find_short(short_id)
        if not found:
            return t("common.unknown_id", id=esc(short_id))
        key, entry = found
        if entry.get("status") == "rejected" and entry.get("user_rejected"):
            return t("no.already", id=esc(short_id))  # a repeated /no must not write the rule twice
        where = oq.drop_locked(short_id, False)
        safe = motif.replace("`", "'").replace("<", "‹").replace(">", "›")
        if motif:  # the reason is optional: without one the posting is just rejected, no rule is learnt
            today = common.local_now().date().isoformat()
            rules = common.config_dir() / "rejection-rules.md"
            text = rules.read_text(encoding="utf-8") if rules.exists() else "# Rejection rules\n\n## Rules\n"
            line = f"- {today} · {safe} · (example : #{short_id} {entry.get('url')})"
            for marker in ("<!-- empty at the start -->", "<!-- vide au départ -->"):
                text = text.replace(marker + "\n", "").replace(marker, "")
            common.atomic_write_text(rules, text.rstrip("\n") + "\n" + line + "\n")
        entry.update({"status": "rejected", "reason": "user", "user_reason": motif or None, "user_rejected": common.iso()})
        ledger.jobs[key] = entry
        ledger.save()
    head = t("no.done", id=esc(short_id), title=esc(entry.get('title')), company=esc(entry.get('company') or '?'))
    return head + "\n" + (t("no.rule_added", rule=esc(safe)) if motif else t("no.no_rule")) + _queue_note(where)


def _queue_note(where: str | None) -> str:
    if where == "current":
        return "\n" + t("queue.next_below")
    if where == "waiting":
        return "\n" + t("queue.removed")
    return ""


def _no_test(short_id: str) -> str:
    """/no T…: the test offer leaves the test queue; no rule is written and nothing real changes."""
    with common.state_lock():
        where = oq.drop_locked(short_id, True)
    job = apps.find_job(short_id)
    if not job and not where:
        return t("common.unknown_id", id=esc(short_id))
    job = job or {}
    return ("[TEST] " + t("no.done", id=esc(short_id), title=esc(job.get('title') or '?'), company=esc(job.get('company') or '?'))
            + "\n" + t("no.test_no_rule") + _queue_note(where))


def _decide(args: str, verdict: str) -> str:
    with common.state_lock():
        data = sites.load()
        numbering = current_numbering(data)
        pending = {p["domain"] for p in data["pending"]}
        if pending and not pending & set(numbering):
            # The numbered recap is fully decided but hosts were queued since: never decide on numbers
            # the user has not seen. Show the new numbered list and let them answer it.
            return t("sites.list_changed") + "\n" + pending_list_text(refresh=True)
        if not numbering:
            return t("sites.none")
        selection = parse_selection(args, len(numbering))
        if selection is None:
            return t("common.bad_selection", n=len(numbering), example=f"/{'allow' if verdict == 'allowed' else 'deny'} 1 3-5")
        domains = [numbering[i - 1] for i in selection]
        moved = sites.decide(data, domains, verdict, common.local_now().date().isoformat())
        sites.save(data)
        gen_settings.main([])
    if not moved:
        return t("sites.nothing_to_do")
    head = t("sites.allowed" if verdict == "allowed" else "sites.denied", n=len(moved))
    return head + "\n" + "\n".join(f"• {esc(d)}" for d in moved) + "\n" + t("sites.regenerated")


def cmd_allow(args: str) -> str:
    return _decide(args, "allowed")


def cmd_deny(args: str) -> str:
    return _decide(args, "denied")


def cmd_regions() -> str:
    regions = common.load_regions()
    lines = [t("regions.title")]
    for key, r in regions["regions"].items():
        mark = "✅" if (r or {}).get("enabled") else "⬜️"
        names = ", ".join((r or {}).get("names") or [])
        lines.append(f"{mark} <code>{esc(key)}</code> ({esc((r or {}).get('country') or '?')}) — {esc(names)}")
    lines.append(f"{'✅' if regions['remote_worldwide'] else '⬜️'} <code>remote</code> — " + t("regions.remote"))
    lines.append(t("regions.change"))
    return "\n".join(lines)


def cmd_region(args: str) -> str:
    parts = (args or "").split()
    if len(parts) != 2 or parts[0].lower() not in ("on", "off"):
        return t("region.usage")
    value = "true" if parts[0].lower() == "on" else "false"
    name = parts[1].lower()
    path = common.config_dir() / "regions.yaml"
    with common.state_lock():
        text = path.read_text(encoding="utf-8")
        if name in ("remote", "remote_worldwide"):
            pattern = re.compile(r"^(remote_worldwide:\s*)(true|false)", re.MULTILINE)
        else:
            if name not in common.load_regions()["regions"]:
                return t("region.unknown", name=esc(name))
            pattern = re.compile(r"^(\s+" + re.escape(name) + r":\s*\{\s*enabled:\s*)(true|false)", re.MULTILINE)
        new, n = pattern.subn(lambda m: m.group(1) + value, text, count=1)
        if n != 1:
            return t("region.bad_format", name=esc(name))
        common.atomic_write_text(path, new)
    return t("region.enabled" if value == "true" else "region.disabled", name=esc(name)) + "\n\n" + cmd_regions()


def latest_summary(include_test: bool = False) -> dict | None:
    runs = common.runs_dir()
    files = sorted(p for p in runs.glob("2*.json") if re.fullmatch(r"\d{8}T\d{6}(-test)?", p.stem)
                   and (include_test or not p.stem.endswith("-test")))
    for path in reversed(files):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return None


def cmd_status() -> str:
    schedule = common.load_schedule()
    summary = latest_summary()
    lines = [t("status.title")]
    if summary:
        fin = common.parse_iso(summary.get("finished"))
        when = fin.astimezone(common.tz()).strftime("%d/%m %H:%M") if fin else "?"
        lines.append(t("status.last_run", when=when, status=esc(summary.get('status')), seen=summary.get('seen', 0),
                       new=summary.get('new', 0), scored=summary.get('scored', 0), alerted=summary.get('alerted', 0),
                       cost=summary.get('total_cost_usd', 0)))
        if fin:
            nxt = fin + common.dt.timedelta(hours=float(schedule["scan_every_hours"]))
            lines.append(t("status.next_run", when=nxt.astimezone(common.tz()).strftime('%d/%m %H:%M')))
    else:
        lines.append(t("status.no_run"))
    if common.scan_running():  # read-only probe: never takes the lock a starting scan needs
        lines.append(t("status.running"))
    alerts = common.read_json(common.state_dir() / "alerts.json", {}) or {}
    if alerts:
        lines.append(t("status.alerts"))
        lines.extend(f"• {a.get('text', k)}" for k, a in alerts.items())
    else:
        lines.append(t("status.no_alerts"))
    lines += oq.status_lines(False) + oq.status_lines(True)
    pending = len(sites.load()["pending"])
    if pending:
        lines.append(t("status.sites_pending", n=pending))
    return "\n".join(lines)


# ------------------------------------------------------------------ /rejets

REJECT_REASONS = ("german_level", "contract_short", "freelance", "internship", "title_excluded", "company_excluded",
                  "company_blocked", "location_outside_regions", "location", "remote_region", "pure_developer",
                  "too_old", "expired", "rejection_rule", "other")  # labels: rejets.reason.<name> in jobbot/locales


def reject_label(reason: str) -> str:
    return t(f"rejets.reason.{reason}") if reason in REJECT_REASONS else reason

HIDDEN_REASONS = {"not_it", "duplicate"}  # not IT: of no interest; duplicates: already seen elsewhere
SILENT_REASONS = {"republished"}  # reposted posting (retouched title): dropped silently, not counted
# Rule rejects carry no IT verdict: keep those whose title looks IT. Acronyms case-sensitive, words not.
_IT_ACRONYMS = re.compile(r"(?<![A-Za-z])(?:IT|ICT|EDV|SAP|ERP|CRM|BI|AI|KI)(?![a-z])")
_IT_WORDS = re.compile(r"software|servicenow|developer|entwickler|architect|architekt|cloud|devops|\bdata|daten|"
                       r"platform|plattform|security|cyber|network|netzwerk|infrastru|system|appli|digital|"
                       r"technology|\btech\b|informati|scrum|agile|release|database|datenbank|oracle", re.I)
TITLE_MAX = 48   # iPhone: a title fits on about 2 lines
WHY_MAX = 90


def looks_it(title: str) -> bool:
    return bool(_IT_ACRONYMS.search(title or "") or _IT_WORDS.search(title or ""))


_GENDER_TAG = re.compile(r"\s*\((?:all genders|human|[mwfdxh*:]{1,2}(?:\s*[/|,]\s*[mwfdxh*:]{1,2}){1,3})\)", re.I)


def _short(text, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _reject_block(job: dict, score=None, why: str | None = None) -> str:
    head = f"<b>{score}</b> · " if score is not None else ""
    lines = [head + link(job.get("url"), _short(_GENDER_TAG.sub("", job.get("title") or ""), TITLE_MAX))]
    where = " · ".join(_short(x, 28) for x in (job.get("company"), job.get("location")) if x)
    if where:
        lines.append(esc(where))
    if why:
        lines.append(f"<i>{esc(_short(why, WHY_MAX))}</i>")
    return "\n".join(lines)


def cmd_rejets() -> str:
    """Rejected postings of the last run, short blocks for a phone screen. Claude's \"not_it\" (and duplicates)
    are hidden; rule rejects are shown only when the title looks IT (they have no IT verdict)."""
    summary = latest_summary(include_test=True)
    rid = (summary or {}).get("run_id")
    pre = common.read_json(common.runs_dir() / f"{rid}-prefilter.json") if rid else None
    if not pre:
        return t("rejets.none")
    scores_doc = common.read_json(common.runs_dir() / f"{rid}-scores.json", {}) or {}
    raw_scores = scores_doc.get("scores") if isinstance(scores_doc, dict) else None
    scores = {s.get("ref"): s for s in (raw_scores or []) if isinstance(s, dict)}

    groups: dict[str, list[tuple[int, str]]] = {}
    hidden = 0
    for job in pre.get("to_score") or []:
        s = scores.get(job.get("ref")) or {}
        reason = s.get("reject_reason")
        if not reason:
            continue
        if reason in HIDDEN_REASONS:
            hidden += 1
            continue
        score = s.get("score") if isinstance(s.get("score"), int) else 0
        groups.setdefault(reason, []).append((score, _reject_block(job, score, s.get("justification"))))
    rule_groups: dict[str, list[tuple[int, str]]] = {}
    for job in pre.get("rejected") or []:
        if job.get("reason") in SILENT_REASONS:
            continue
        if not looks_it(job.get("title")):
            hidden += 1
            continue
        rule_groups.setdefault(job.get("reason") or "other", []).append((0, _reject_block(job)))

    fin = common.parse_iso((summary or {}).get("finished"))
    when = fin.astimezone(common.tz()).strftime("%d/%m %H:%M") if fin else "?"
    shown = sum(len(v) for v in groups.values()) + sum(len(v) for v in rule_groups.values())
    lines = [t("rejets.title", when=when) + (" [TEST]" if str(rid).endswith("-test") else ""),
             t("rejets.counts", shown=shown, hidden=hidden)]
    if not shown:
        lines.append("\n" + t("rejets.empty"))
    for title, grp, note in ((t("rejets.scored"), groups, None),
                             (t("rejets.rules"), rule_groups, t("rejets.rules_note"))):
        if not grp:
            continue
        lines.append(f"\n<b>— {title} —</b>" + (f"\n<i>{note}</i>" if note else ""))
        for reason, items in sorted(grp.items(), key=lambda kv: -max(s for s, _ in kv[1])):
            lines.append(f"\n<b>{esc(reject_label(reason))} ({len(items)})</b>")
            for _, block in sorted(items, key=lambda it: -it[0]):
                lines.append("")
                lines.append(block)
    return "\n".join(lines)


def cmd_health() -> str:
    """Run the zero-token pre-flight check now and report every item (no alert, no state change
    besides jobbot/state/preflight.json)."""
    import preflight

    report = preflight.run_checks()
    text = preflight.format_report(report, t("health.title"))
    queued = __import__("telegram_send").queue_length()
    if queued:
        text += "\n" + t("health.queued", n=queued)
    return text


def cmd_search(args: str, spawn=None) -> str:
    target = (args or "all").strip().lower() or "all"
    if target not in ("all", *PORTAL_NAMES):
        return t("search.unknown", site=esc(target), choices="all, " + ", ".join(PORTAL_NAMES))
    if common.scan_running():
        return t("search.busy")
    script = common.ROOT / "jobbot" / "scripts" / "run_scan.sh"
    (spawn or _spawn)(["/bin/bash", str(script), "--site", target])
    note = t("search.linkedin_note") if target in ("all", "linkedin") else ""
    return t("search.started", site=esc(target), note=note)


def _spawn(argv: list[str]) -> None:
    subprocess.Popen(argv, cwd=common.ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


# ------------------------------------------------------------------ V2: /go /sent /cancel /pending /firma

GO_SCRIPT = common.ROOT / "jobbot" / "scripts" / "go.sh"
CLOSED = ("sent", "cancelled", "rejected")  # labels: go.closed.<status>


def _ids(args: str) -> list[str]:
    return [x for x in re.split(r"[\s,;]+", (args or "").strip()) if x]


def _age(iso: str | None) -> str:
    when = common.parse_iso(iso)
    if not when:
        return "?"
    hours = int((common.now() - when).total_seconds() // 3600)
    return t("common.age_days", d=hours // 24, h=hours % 24) if hours >= 24 else t("common.age_hours", h=hours)


def _when(iso: str | None) -> str:
    when = common.parse_iso(iso)
    return when.astimezone(common.tz()).strftime("%d/%m %H:%M") if when else "?"


def cmd_go(args: str, spawn=None) -> str:
    """Launch go.sh for each ID, in parallel (one process and one lock per ID)."""
    import go

    ids = _ids(args)
    if not ids:
        return t("go.usage")
    lines = []
    for raw in ids[:10]:
        short_id = apps.norm_id(raw)
        if not short_id:
            lines.append(t("common.invalid_id", id=esc(raw)))
            continue
        job = apps.find_job(short_id)
        if not job:
            lines.append(t("go.unknown", id=esc(short_id)))
            continue
        label = f"#{esc(short_id)} ({esc(job.get('company') or '?')} — {esc(job.get('title') or '?')})"
        if job.get("status") in CLOSED:
            lines.append(t("go.closed_nothing", label=label, status=t(f"go.closed.{job['status']}")))
        elif apps.get_pending(short_id):
            lines.append(t("go.ready", label=label))
        elif go.is_running(short_id):
            lines.append(t("go.running", label=label))
        else:
            with common.state_lock():  # V5: an offer prepared from /file leaves the queue (/pending follows it)
                from_queue = oq.take_waiting_locked(short_id, apps.is_test_id(short_id))
            (spawn or _spawn)(["/bin/bash", str(GO_SCRIPT), short_id])
            how = t("go.how_adapt") if job.get("adapt") else t("go.how_variant")
            where = t("go.where_queue") if from_queue else t("go.where_alert")
            lines.append(t("go.started", label=label, how=how, where=where))
    return "\n".join(lines)


def _delete_files(entry: dict) -> tuple[int, list[str]]:
    """Delete the /go files from Telegram. -> (deleted, [names to delete by hand])."""
    deleted, manual = 0, []
    for msg in entry.get("telegram") or []:
        ok, why = tg.delete_message(msg["message_id"], msg.get("sent"))
        if ok:
            deleted += 1
        else:
            manual.append(t("files.manual_item", name=msg.get('name') or msg['message_id'], when=_when(msg.get('sent')), why=why))
    return deleted, manual


def _files_report(deleted: int, manual: list[str]) -> list[str]:
    lines = [t("files.deleted", n=deleted)]
    if manual:
        lines.append(t("files.manual", hours=tg.DELETE_WINDOW_HOURS))
        lines += [f"• {esc(m)}" for m in manual]
    return lines


def _one_id(args: str, command: str) -> tuple[str | None, str | None]:
    ids = _ids(args)
    if len(ids) != 1:
        return None, t("common.one_id", command=command)
    short_id = apps.norm_id(ids[0])
    if not short_id:
        return None, t("common.invalid_id", id=esc(ids[0]))
    return short_id, None


def cmd_sent(args: str) -> str:
    ids = _ids(args)
    if len(ids) == 1 and contacts.norm_id(ids[0]):
        return spont_close(contacts.norm_id(ids[0]), "sent")
    short_id, error = _one_id(args, "sent")
    if error:
        return error
    test = apps.is_test_id(short_id)
    with common.state_lock():
        pending = apps.load_pending(test)
        entry = pending.get(short_id)
        if not entry:
            job = apps.find_job(short_id)
            if not job:
                return t("common.unknown_id", id=esc(short_id))
            return t("sent.not_pending", id=esc(short_id))
        job = apps.find_job(short_id) or {"company": entry.get("company"), "title": entry.get("title")}
        old = apps.tracker_set_status(short_id, job, "applied", ("drafted",))
        del pending[short_id]
        apps.save_pending(test, pending)
        apps.set_ledger_status(short_id, "sent", sent_at=common.iso())
        apps.log_event("sent", short_id)
        where = oq.drop_locked(short_id, test)
    if test:
        followup.register_test_sent(short_id, entry)
    deleted, manual = _delete_files(entry)
    lines = [t("sent.done", id=esc(short_id), company=esc(entry.get('company')), title=esc(entry.get('title'))) + (" [TEST]" if test else ""),
             "CSV : " + ("drafted → applied" if old else (t("sent.csv_test") if test else t("sent.csv_missing")))]
    return "\n".join(lines + _files_report(deleted, manual)) + _queue_note(where)


def cmd_cancel(args: str) -> str:
    ids = _ids(args)
    if len(ids) == 1 and contacts.norm_id(ids[0]):
        return spont_close(contacts.norm_id(ids[0]), "cancelled")
    short_id, error = _one_id(args, "cancel")
    if error:
        return error
    test = apps.is_test_id(short_id)
    job = apps.find_job(short_id)
    with common.state_lock():
        pending = apps.load_pending(test)
        entry = pending.pop(short_id, None)
        if not entry and not job:
            return t("common.unknown_id", id=esc(short_id))
        if not entry and job.get("status") == "cancelled":
            return t("cancel.already", id=esc(short_id))
        job = job or {"company": entry.get("company"), "title": entry.get("title")}
        old = apps.tracker_set_status(short_id, job, "withdrawn", ("drafted", "applied", "interview"))
        if entry:
            apps.save_pending(test, pending)
        apps.set_ledger_status(short_id, "cancelled", cancelled_at=common.iso())
        apps.log_event("cancel", short_id)
        where = oq.drop_locked(short_id, test)
    if test:
        followup.forget_test(short_id)
    lines = [t("cancel.done", id=esc(short_id), company=esc(job.get('company')), title=esc(job.get('title')))
             + (" [TEST]" if test else "")]
    if old:
        lines.append(f"CSV : {esc(old)} → withdrawn")
    if entry:
        lines += _files_report(*_delete_files(entry))
        lines.append(t("files.local_kept", name=esc(Path(entry['dir']).name)))
    return "\n".join(lines) + _queue_note(where)


# ------------------------------------------------------------------ V5: /file, /voir (offer queue)

def cmd_file() -> str:
    with common.state_lock():
        items, queues = oq.list_locked()
    lines = []
    for test in (False, True):
        cur = queues[test]["current"]
        if cur:
            e = cur["entry"]
            lines.append(t("file.shown", tag=" [TEST]" if test else "", id=esc(cur['id']), score=e.get('score'),
                           link=link(e.get('url'), _short(e.get('title'), TITLE_MAX)),
                           company=esc(_short(e.get('company') or '?', 28)), age=oq.age_text(cur.get('shown_at'))))
    if not items:
        return "\n".join(lines + [t("file.empty")])
    lines.insert(0, t("file.title", n=len(items)))
    test_started = False
    for n, (test, item) in enumerate(items, 1):
        if test and not test_started:
            lines.append("<b>— [TEST] —</b>")
            test_started = True
        e = item["entry"]
        extra = t("file.published", date=esc(str(e['date'])[:10])) if e.get("date") else ""
        lines.append(f"{n}. <b>{e.get('score')}</b> · {link(e.get('url'), _short(e.get('title'), TITLE_MAX))} · "
                     f"{esc(_short(e.get('company') or '?', 28))} · #{esc(e.get('short_id'))} · "
                     + t("file.queued_since", age=oq.age_text(item.get('queued_at'))) + extra)
    lines.append(t("file.show_hint"))
    return "\n".join(lines)


def cmd_voir(args: str) -> str:
    text = (args or "").strip()
    if not re.fullmatch(r"\d+", text):
        return t("voir.usage")
    with common.state_lock():
        numbering = oq.load_numbering()
        if not numbering:
            return t("common.list_first", command=command_name("file"))
        n = int(text)
        if not 1 <= n <= len(numbering):
            return t("common.bad_number", n=len(numbering))
        sid = numbering[n - 1]
        entry = oq.show_locked(sid, apps.is_test_id(sid))
    if entry is None:
        return t("voir.gone")
    oq.pump(apps.is_test_id(sid))
    return t("voir.done", id=esc(sid))


def cmd_pending_view() -> tuple[str, list[tuple[str, str]]]:
    """-> (text, [(button label, callback data)]) — the bot turns the list into an inline keyboard."""
    items = apps.all_pending()
    if not items:
        return t("pending.none"), []
    lines = [t("pending.title", n=len(items))]
    buttons = []
    for e in items:
        sid = e["id"]
        lines.append("")
        lines.append(f"<b>#{esc(sid)}</b> · {esc(e.get('company'))} · {esc(e.get('title'))}" + (" [TEST]" if e.get("test") else ""))
        lines.append(t("pending.line", link=link(e.get('url'), t("common.offer")), when=_when(e.get('go_at')),
                       age=_age(e.get('go_at')), variant=esc(e.get('variant')),
                       adapted=t("pending.adapted") if e.get('adapted') else ""))
        lines.append(f"/sent {esc(sid)} · /cancel {esc(sid)}")
        buttons.append((t("pending.button", id=sid), f"resend:{sid}"))
    return "\n".join(lines), buttons


def cmd_pending() -> str:
    return cmd_pending_view()[0]


def resend_files(short_id: str) -> str:
    """Button of /pending: send the CV and offre.pdf again, as replies to the alert."""
    short_id = apps.norm_id(short_id)
    entry = apps.get_pending(short_id) if short_id else None
    if not entry:
        return t("resend.gone", id=esc(short_id or '?'))
    stem = apps.file_stem(short_id, entry.get("company"), entry.get("title"))
    files = [(Path(entry["cv"]), f"{stem}_CV.pdf")]
    if entry.get("offer"):
        files.append((Path(entry["offer"]), f"{stem}_offre.pdf"))
    sent, errors = [], []
    for path, name in files:
        if not path.exists():
            errors.append(t("resend.missing", name=name))
            continue
        mid, err = tg.send_document(path, name, reply_to=entry.get("alert_message_id"))
        if mid:
            sent.append({"message_id": mid, "sent": common.iso(), "file": str(path), "name": name})
        else:
            errors.append(f"{name} : {err}")
    if sent:
        with common.state_lock():
            pending = apps.load_pending(apps.is_test_id(short_id))
            if short_id in pending:
                pending[short_id]["telegram"] = (pending[short_id].get("telegram") or []) + sent
                apps.save_pending(apps.is_test_id(short_id), pending)
    text = t("resend.done", id=esc(short_id), n=len(sent))
    if errors:
        text += "\n⚠️ " + esc("; ".join(errors))
    return text


def cmd_firma(args: str) -> str:
    query = " ".join((args or "").split())
    if len(query) < 2:
        return t("firma.usage")
    key = dedup.norm_company(query) or query.casefold()

    def match(name) -> bool:
        return bool(name) and key in (dedup.norm_company(name) or str(name).casefold())

    _, rows = apps.read_tracker()
    found = []
    for row in rows:
        if match(row.get("company")):
            found.append({"company": row.get("company"), "title": row.get("role"), "date": row.get("date"),
                          "status": row.get("status"), "url": row.get("source"), "cv": row.get("cv_file"),
                          "letter": row.get("cover_letter_file"), "notes": row.get("notes") or ""})
    in_tracker = {m.group(1) for f in found for m in re.finditer(r"jobbot #(T?\d+)", f["notes"])}
    for e in apps.all_pending():
        if match(e.get("company")) and e["id"] not in in_tracker:
            found.append({"company": e.get("company"), "title": e.get("title"), "date": (e.get("go_at") or "")[:10],
                          "status": "drafted" + (" [TEST]" if e.get("test") else ""), "url": e.get("url"),
                          "cv": e.get("cv"), "letter": None, "notes": f"jobbot #{e['id']}"})
    if not found:
        return t("firma.none", query=esc(query))
    lines = [t("firma.title", query=esc(query), n=len(found))]
    for f in sorted(found, key=lambda f: f.get("date") or "", reverse=True):
        sent = (f.get("status") or "").split()[0] not in ("drafted", "")
        lines.append("")
        lines.append(f"<b>{esc(f['title'])}</b> · {esc(f['company'])}")
        lines.append(t("firma.status", date=esc(f.get('date') or '?'), status=esc(f.get('status') or '?'),
                       link=link(f.get('url'), t("common.offer"))))
        cv = Path(f["cv"]).name if f.get("cv") else "—"
        letter = Path(f["letter"]).name if f.get("letter") else t("firma.no_letter")
        lines.append(t("firma.cv_sent" if sent else "firma.cv_prepared", cv=esc(cv), letter=esc(letter)))
    return "\n".join(lines)


# ------------------------------------------------------------------ /rules, /rule del

def _rule_line(n: int, text: str) -> str:
    r = rulesmod.parse(text)
    if "free" in r:
        return f"{n}. {esc(r['free'])} <i>" + t("rules.free") + "</i>"
    return f"{n}. {esc(r['date'])} · {esc(r['motif'])} · {link(r['url'], '#' + r['id'])}"


def cmd_rules() -> str:
    with common.state_lock():
        items = rulesmod.current()
        rulesmod.save_numbering(items)
    if not items:
        return t("rules.none")
    lines = [t("rules.title", n=len(items))]
    lines += [_rule_line(i, it["text"]) for i, it in enumerate(items, 1)]
    lines.append(t("rules.delete_hint"))
    return "\n".join(lines)


def cmd_rule_view(args: str) -> tuple[str, list[tuple[str, str]]]:
    """/rule del <n…>: shows the selected rules and two buttons; nothing is deleted here."""
    parts = (args or "").split(None, 1)
    if not parts or parts[0].lower() not in ("del", "delete", "suppr"):
        return t("rule.usage"), []
    with common.state_lock():
        numbering = rulesmod.load_numbering()
        if not numbering:
            return t("common.list_first", command="rules"), []
        selection = parse_selection(parts[1] if len(parts) > 1 else "", len(numbering))
        if selection is None or len(parts) < 2 or parts[1].strip().lower() in ("all", "tout", "tous"):
            return t("common.bad_selection", n=len(numbering), example="/rule del 2 5-7"), []
        items = [numbering[i - 1] for i in selection]
        token = rulesmod.create_confirmation(items)
    lines = [t("rule.confirm_title", n=len(items))]
    lines += [_rule_line(i, it["text"]) for i, it in zip(selection, items)]
    lines.append(t("rule.confirm_valid", minutes=rulesmod.CONFIRM_MINUTES))
    return "\n".join(lines), [(t("rule.confirm_button"), f"ruledel:{token}"), (t("rule.cancel_button"), f"ruleno:{token}")]


def cmd_rule(args: str) -> str:
    return cmd_rule_view(args)[0]


def rule_confirm(token: str) -> str:
    with common.state_lock():
        items, err = rulesmod.take_confirmation(token)
        if err:
            return t("rule.expired")
        deleted, missing = rulesmod.delete(items)
        rulesmod.save_numbering(rulesmod.current())
    lines = [t("rule.deleted", n=len(deleted))]
    if missing:
        lines.append(t("rule.missing", n=len(missing)))
        lines += [f"• {esc(t)}" for t in missing]
    return "\n".join(lines) + "\n\n" + cmd_rules()


def rule_cancel(token: str) -> str:
    with common.state_lock():
        rulesmod.take_confirmation(token)
    return t("rule.cancelled")


# ------------------------------------------------------------------ /block, /blocked, /unblock (V3)

def blocked_numbering_path() -> Path:
    return common.state_dir() / "blocked_numbering.json"


def _company_name(args: str, command: str) -> tuple[str | None, str | None]:
    name = " ".join((args or "").split())
    if len(name) < 2 or len(name) > 120:
        return None, t("company.usage", command=command)
    if not companies.key_of(name):
        return None, t("company.invalid", name=esc(name))
    return name, None


def cmd_block(args: str) -> str:
    name, error = _company_name(args, "block")
    if error:
        return error
    with common.state_lock():
        rows = companies.load()
        before = companies.find(rows, name)
        was = before["status"] if before else None
        row, covered = companies.block(rows, name)
        companies.save(rows)
    if was == "blocked":
        return t("block.already", name=esc(row['name']))
    lines = [t("block.done", name=esc(row['name']))]
    if covered:
        lines.append(t("block.covers", names=", ".join(esc(c) for c in covered[:10])))
    lines.append(t("block.undo"))
    return "\n".join(lines)


def cmd_blocked() -> str:
    with common.state_lock():
        rows = companies.blocked(companies.load())
        common.atomic_write_json(blocked_numbering_path(), [r["key"] for r in rows])
    if not rows:
        return t("blocked.none")
    lines = [t("blocked.title", n=len(rows))]
    for i, r in enumerate(rows, 1):
        site = f" · {link(r['website'], companies.website_host(r['website']))}" if r["website"] else ""
        lines.append(f"{i}. {esc(r['name'])}{site}")
    lines.append(t("blocked.hint"))
    return "\n".join(lines)


def cmd_unblock(args: str) -> str:
    text = (args or "").strip()
    if not re.fullmatch(r"\d+", text):
        return t("unblock.usage")
    with common.state_lock():
        numbering = common.read_json(blocked_numbering_path(), None)
        if not isinstance(numbering, list) or not numbering:
            return t("common.list_first", command="blocked")
        n = int(text)
        if not 1 <= n <= len(numbering):
            return t("common.bad_number", n=len(numbering))
        rows = companies.load()
        row = next((r for r in rows if r["key"] == numbering[n - 1]), None)
        if row is None or row["status"] != "blocked":
            return t("unblock.gone")
        companies.unblock(row)
        companies.save(rows)
        common.atomic_write_json(blocked_numbering_path(), [r["key"] for r in companies.blocked(rows)])
    return t("unblock.done", name=esc(row['name']))


# ------------------------------------------------------------------ /discover, /companies, /accept, /reject (V3)

def proposals_numbering_path() -> Path:
    return common.state_dir() / "companies_numbering.json"


def needs_claude() -> str | None:
    """The refusal text for a command that needs Claude when schedule.yaml says `scoring: rules`, else None."""
    import rule_scorer

    return t("bot.needs_claude") if rule_scorer.enabled() else None


def cmd_discover(args: str, spawn=None) -> str:
    import discover

    refusal = needs_claude()
    if refusal:
        return refusal

    region = (args or "").strip().lower()
    regions = common.load_regions()["regions"]
    enabled = [k for k, r in regions.items() if (r or {}).get("enabled")]
    if region not in enabled:
        return t("discover.usage", regions=", ".join(enabled) or t("common.none_f"))
    try:
        with discover.discover_lock():
            pass
    except common.LockBusy:
        return t("discover.busy")
    (spawn or _spawn)(["/bin/bash", str(common.ROOT / "jobbot" / "scripts" / "discover.sh"), region])
    return t("discover.started", region=esc(region))


def cmd_companies() -> str:
    with common.state_lock():
        rows = companies.proposed(companies.load())
        common.atomic_write_json(proposals_numbering_path(), [r["key"] for r in rows])
    if not rows:
        return t("companies.none")
    lines = [t("companies.title", n=len(rows))]
    for i, r in enumerate(rows, 1):
        lines.append(f"{i}. <b>{esc(r['name'])}</b> · {esc(r['city'] or '?')} · "
                     f"{link(r['website'], companies.website_host(r['website']))} · {link(r['source'], 'source')}")
    lines.append(t("companies.answer"))
    return "\n".join(lines)


def _decide_companies(args: str, status: str) -> str:
    command = "accept" if status == "active" else "reject"
    with common.state_lock():
        numbering = common.read_json(proposals_numbering_path(), None)
        if not isinstance(numbering, list) or not numbering:
            return t("common.list_first", command="companies")
        selection = parse_selection(args, len(numbering))
        if selection is None:
            return t("common.bad_selection", n=len(numbering), example=f"/{command} 1 3-5")
        rows = companies.load()
        by_key = {r["key"]: r for r in rows}
        done, skipped = [], 0
        for i in selection:
            row = by_key.get(numbering[i - 1])
            if row is None or row["status"] != "proposed":
                skipped += 1
                continue
            row["status"] = status
            row["verified"] = common.local_now().date().isoformat()
            done.append(row["name"])
        companies.save(rows)
    if not done:
        return t("companies.nothing_to_do")
    head = t("companies.accepted" if status == "active" else "companies.rejected", n=len(done))
    tail = "\n" + t("companies.skipped", n=skipped) if skipped else ""
    return head + "\n" + "\n".join(f"• {esc(n)}" for n in done) + tail


def cmd_accept(args: str) -> str:
    return _decide_companies(args, "active")


def cmd_reject(args: str) -> str:
    return _decide_companies(args, "rejected")


# ------------------------------------------------------------------ /spont, /sent S…, /cancel S… (V3)

def cmd_spont(args: str, spawn=None) -> str:
    import spontaneous

    refusal = needs_claude()
    if refusal:
        return refusal

    name, error = _company_name(args, "spont")
    if error:
        return error
    row, refusal = spontaneous.eligible(name)
    if refusal:
        return t("spont.refused", name=esc(name), why=esc(refusal))
    try:
        with spontaneous.spont_lock(row["key"]):
            pass
    except common.LockBusy:
        return t("spont.running", name=esc(row['name']))
    (spawn or _spawn)(["/bin/bash", str(common.ROOT / "jobbot" / "scripts" / "spont.sh"), row["name"]])
    return t("spont.started", name=esc(row['name']))


def spont_close(cid: str, status: str) -> str:
    import spontaneous

    test = contacts.is_test_id(cid)
    with common.state_lock():
        row = contacts.get(cid)
        if row is None:
            return t("common.unknown_id", id=esc(cid))
        if row["status"] != "prepared":
            return t("spont.already", id=esc(cid), status=esc(row['status']))
        fields = {"sent": common.iso()} if status == "sent" else {}
        contacts.set_status(cid, status, **fields)
        pend = common.read_json(spontaneous.pending_path(test), {}) or {}
        entry = pend.pop(cid, None)
        common.atomic_write_json(spontaneous.pending_path(test), pend)
    tag = " [TEST]" if test else ""
    if status == "sent":
        head = t("spont.sent", id=esc(cid), company=esc(row['company']),
                 contact=esc(row['contact'] or row['email'] or 'LinkedIn'), tag=tag)
    else:
        head = t("spont.cancelled", id=esc(cid), company=esc(row['company']), tag=tag)
    lines = [head]
    if entry:
        lines += _files_report(*_delete_files(entry))
        lines.append(t("files.local_kept", name=esc(Path(entry['dir']).name)))
    return "\n".join(lines)


# ------------------------------------------------------------------ V5: /reply, follow-up reminders, contacts

def _yes_no(answer: str) -> str:
    return t("reply.word_yes") if answer == "yes" else t("reply.word_no")


def _keep_buttons(cid: str) -> list[tuple[str, str]]:
    return [(t("contact.btn_keep"), f"keep:{cid}"), (t("contact.btn_purge"), f"purge:{cid}")]


def keep_question(cid: str, company: str, contact: str) -> str:
    return t("contact.question", id=esc(cid), company=esc(company), contact=esc(contact or "?"))


def cmd_reply_view(args: str) -> tuple[str, list[tuple[str, str]]]:
    """/reply <ID> yes|no -> (text, buttons): S… gets the "keep this contact?" question."""
    parts = (args or "").split()
    if len(parts) != 2:
        return t("reply.usage"), []
    sid = contacts.norm_id(parts[0]) or apps.norm_id(parts[0])
    if not sid:
        return t("common.invalid_id", id=esc(parts[0])), []
    answer = followup.parse_answer(parts[1])
    if not answer:
        return t("reply.usage"), []
    return _reply(sid, answer)


def cmd_reply(args: str) -> str:
    return cmd_reply_view(args)[0]


def _reply(sid: str, answer: str) -> tuple[str, list[tuple[str, str]]]:
    res = followup.reply(sid, answer)
    tag = " [TEST]" if sid.startswith("T") else ""
    status = res["status"]
    if status == "unknown":
        return t("common.unknown_id", id=esc(sid)), []
    if status == "missing":
        return t("reply.missing", id=esc(sid)), []
    if status == "not_sent":
        return t("reply.not_sent", id=esc(sid)), []
    if status == "closed":
        return t("reply.closed", id=esc(sid), status=esc(res.get("old"))), []
    if status == "already":
        return t("reply.already", id=esc(sid), status=esc(res.get("response") or res.get("old"))), []
    if res["kind"] == "spont":
        text = t("reply.spont_done", id=esc(sid), company=esc(res["company"]), answer=_yes_no(answer), tag=tag)
        if res.get("kept"):
            return text, []
        return text + "\n\n" + keep_question(sid, res["company"], res.get("contact")), _keep_buttons(sid)
    head = t("reply.done", id=esc(sid), company=esc(res["company"]), title=esc(res["title"]),
             answer=_yes_no(answer), old=esc(res["old"]), new=esc(res["new"]), tag=tag)
    return head + "\n" + t("reply.outcome_hint", company=esc(res["company"])), []


def reply_button(arg: str) -> tuple[str, list[tuple[str, str]]]:
    """Callback "reply:<ID>:yes|no" (reminder buttons)."""
    sid, _, answer = arg.partition(":")
    sid = contacts.norm_id(sid) or apps.norm_id(sid)
    answer = followup.parse_answer(answer)
    if not sid or not answer:
        return t("reply.usage"), []
    return _reply(sid, answer)


def followup_done(arg: str) -> str:
    """Callback "fu:<ID>": the user sent a follow-up (logged as /outcome does)."""
    sid = contacts.norm_id(arg) or apps.norm_id(arg)
    if not sid:
        return t("common.invalid_id", id=esc(arg))
    res = followup.log_followup(sid)
    tag = " [TEST]" if sid.startswith("T") else ""
    if res["status"] == "unknown":
        return t("common.unknown_id", id=esc(sid))
    if res["status"] == "today":
        return t("followup.already_today", id=esc(sid))
    if not res["ok"]:
        return t("followup.not_open", id=esc(sid), status=esc(res["status"]))
    if res["count"] >= res["max"]:
        return t("followup.logged_last", id=esc(sid), count=res["count"], max=res["max"], days=res["days"], tag=tag)
    return t("followup.logged", id=esc(sid), count=res["count"], max=res["max"], days=res["days"], tag=tag)


def _contact_result(cid: str, res: dict) -> str:
    tag = " [TEST]" if cid.startswith("T") else ""
    status = res["status"]
    if status == "unknown":
        return t("common.unknown_id", id=esc(cid))
    if not res["ok"] and status == "purged":
        return t("contact.already_purged", id=esc(cid))
    if status == "not_sent":
        return t("contact.not_sent", id=esc(cid), status=esc(res.get("old")))
    if status == "already":
        return t("contact.already_kept", id=esc(cid), date=esc(res.get("date")))
    if status == "kept":
        return t("contact.kept", id=esc(cid), company=esc(res["company"]), tag=tag)
    files = ", ".join(res.get("removed") or []) or t("common.none_m")
    return t("contact.purged", id=esc(cid), company=esc(res["company"]), files=esc(files), tag=tag)


def contact_keep(arg: str) -> str:
    cid = contacts.norm_id(arg)
    return _contact_result(cid, followup.keep_contact(cid)) if cid else t("common.invalid_id", id=esc(arg))


def contact_purge(arg: str) -> str:
    cid = contacts.norm_id(arg)
    return _contact_result(cid, followup.purge_contact(cid)) if cid else t("common.invalid_id", id=esc(arg))


def reminder_message(item: dict) -> tuple[str, list[list[tuple[str, str]]]]:
    """One follow-up reminder (daily.py): text + button rows. The text names the equivalent commands
    (a message queued while Telegram is down loses its buttons)."""
    sid, company = item["id"], item["company"]
    _, cap = followup.settings()
    tag = "[TEST] " if item["test"] else ""
    ref = esc(sid) if item["kind"] == "spont" else f"#{esc(sid)}"
    if item["kind"] == "spont":
        what = t("followup.spont_label")
    else:
        what = link(item["url"], item["title"] or t("common.offer")) if item["url"] else esc(item["title"] or "")
    reply_row = [(t("followup.btn_yes"), f"reply:{sid}:yes"), (t("followup.btn_no"), f"reply:{sid}:no")]
    if item.get("exhausted"):
        lines = [t("followup.exhausted", tag=tag, ref=ref, company=esc(company), what=what,
                   days=item["days"], count=item["followups"], max=cap)]
        lines.append(t("followup.exhausted_offer", company=esc(company), id=esc(sid)) if item["kind"] == "offer"
                     else t("followup.exhausted_spont", id=esc(sid)))
        rows = [reply_row]
    else:
        lines = [t("followup.title", tag=tag, ref=ref, company=esc(company), what=what),
                 t("followup.quiet", days=item["days"], count=item["followups"], max=cap)]
        lines.append(t("followup.offer_hint", company=esc(company)) if item["kind"] == "offer"
                     else t("followup.spont_hint", contact=esc(item.get("contact") or "?")))
        lines.append(t("followup.commands", id=esc(sid)))
        rows = [[(t("followup.btn_done"), f"fu:{sid}")], reply_row]
    if item["kind"] == "spont":
        row = contacts.get(sid) or {}
        if not row.get("kept"):
            lines.append("")
            lines.append(keep_question(sid, company, item.get("contact")))
            rows.append(_keep_buttons(sid))
    return "\n".join(lines), rows
