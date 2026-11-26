#!/usr/bin/env python3
"""V3 (SPEC §10): prepare one spontaneous application — never sends anything.

    bash jobbot/scripts/spont.sh "<company name>"          (Telegram /spont <entreprise>)

  checks (script) -> claude -p "/jobbot-spontaneous <ID>" (WebFetch on the company's allowed official
  site, WebSearch) -> validation (script): the e-mail address must appear on the source page, which
  must be on the official site (re-fetched through the whitelist + robots.txt) -> files:
      documents/spontaneous/<company>/email.txt      draft e-mail (To, Subject, address source, body)
      documents/spontaneous/<company>/linkedin.txt   short LinkedIn message (≤ 300 characters) + profile link
      documents/spontaneous/<company>/<ID>_<company>_CV.pdf
  -> contacts.csv (prepared) -> Telegram (summary + files). The user sends, then /sent S<n>.
Test mode (JOBBOT_DRY_RUN=1): IDs TS<n>, contacts-test.csv, files under <cache>/test-spontaneous/.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import applications as apps
import build_cv_variants
import common
import companies
import contacts
import discover
import postprocess
import scan
import sites
import telegram_send as tg
from ats import vendors
from ats.web import Fetcher, FetchError
from i18n import t

TIMEOUT = 15 * 60
COMMAND = "jobbot-spontaneous"
DEFAULT_VARIANT = "delivery"
LINKEDIN_MAX = 300
_EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,24}$")
_LINKEDIN = re.compile(r"^https://(?:[a-z]{2,3}\.|www\.)?linkedin\.com/in/[A-Za-z0-9_%\-]{2,100}/?$")


def spont_lock(key: str):
    return common.file_lock(common.state_dir() / f".spont-{key.replace(' ', '_')[:60]}.lock", blocking=False)


def pending_path(test: bool) -> Path:
    return common.state_dir() / ("spontaneous-pending-test.json" if test else "spontaneous-pending.json")


def root_dir(test: bool) -> Path:
    return (common.cache_dir() / "test-spontaneous") if test else common.spontaneous_dir()


# ------------------------------------------------------------------ eligibility (shared with the bot)

def eligible(name: str) -> tuple[dict | None, str | None]:
    """-> (company row, refusal). Active, not blocked, never contacted / applied at."""
    rows = companies.load()
    row = companies.find(rows, name)
    if row is None:
        return None, t("spont.unknown_company")
    if row["status"] != "active" or companies.is_blocked(row["name"], companies.blocked_keys(rows)):
        return None, t("spont.company_status", status=row['status'] if row['status'] != 'active' else 'blocked')
    if companies.matches_any(row["name"], companies.contacted_keys()):
        return None, t("spont.already_contacted")
    if not row["website"]:
        return None, t("spont.no_website")
    return row, None


def official_hosts(row: dict) -> set[str]:
    return {h for h in (companies.website_host(row["website"]), companies.website_host(row["careers_url"])) if h}


def _on_official_site(url: str, hosts: set[str]) -> bool:
    host = companies.website_host(url)
    return bool(host) and any(host == h or host.endswith("." + h) for h in hosts)


def _deobfuscate(text: str) -> str:
    text = re.sub(r"\s*[\(\[\{]\s*(?:at|ät|@)\s*[\)\]\}]\s*", "@", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*[\(\[\{]\s*(?:dot|punkt|\.)\s*[\)\]\}]\s*", ".", text, flags=re.IGNORECASE)
    return text.replace("&#64;", "@").replace("&#46;", ".").lower()


def email_on_page(email: str, url: str, fetcher: Fetcher) -> tuple[bool, str]:
    """The address must literally appear (or lightly obfuscated) on the source page — never guessed."""
    try:
        _, body = fetcher.get(url, accept="text/html")
    except FetchError as exc:
        return False, t("spont.source_unreadable", reason=exc.reason)
    return (email.lower() in _deobfuscate(body)), t("spont.email_not_on_page")


# ------------------------------------------------------------------ validation of Claude's output

def validate(doc, row: dict, fetcher: Fetcher, variants: list[str]) -> tuple[dict | None, list[str]]:
    notes: list[str] = []
    if not isinstance(doc, dict):
        return None, [t("spont.output_unreadable")]
    c = doc.get("contact") if isinstance(doc.get("contact"), dict) else {}
    clean = lambda v, n: " ".join(str(v or "").split())[:n]  # noqa: E731
    out = {"contact": clean(c.get("name"), 120), "role": clean(c.get("role"), 120),
           "email": "", "email_source": "", "linkedin": "", "linkedin_source": "",
           "variant": doc.get("variant") if doc.get("variant") in variants else DEFAULT_VARIANT,
           "subject": clean((doc.get("email") or {}).get("subject"), 160),
           "body": str((doc.get("email") or {}).get("body") or "").strip()[:5000],
           "linkedin_message": " ".join(str(doc.get("linkedin_message") or "").split())}
    email, source = str(c.get("email") or "").strip(), str(c.get("email_source_url") or "").strip()
    if email:
        if not _EMAIL.match(email):
            notes.append(t("spont.email_invalid"))
        elif not source.startswith("https://") or not _on_official_site(source, official_hosts(row)):
            notes.append(t("spont.email_no_source"))
        else:
            ok, why = email_on_page(email, source, fetcher)
            if ok:
                out["email"], out["email_source"] = email, source
            else:
                notes.append(t("spont.email_unconfirmed", why=why))
    li, li_source = str(c.get("linkedin_url") or "").strip(), str(c.get("linkedin_source_url") or "").strip()
    if li:
        if _LINKEDIN.match(li) and li_source.startswith("https://"):
            out["linkedin"], out["linkedin_source"] = li.rstrip("/"), li_source
        else:
            notes.append(t("spont.linkedin_invalid"))
    if out["linkedin"] and len(out["linkedin_message"]) > LINKEDIN_MAX:
        notes.append(t("spont.linkedin_too_long", n=len(out['linkedin_message']), max=LINKEDIN_MAX))
        out["linkedin_message"] = ""
    if out["email"] and (not out["subject"] or len(out["body"]) < 200):
        notes.append(t("spont.email_incomplete"))
        out["email"] = ""
    if not out["email"] and not (out["linkedin"] and out["linkedin_message"]):
        return None, notes + [t("spont.no_contact")]
    return out, notes


# ------------------------------------------------------------------ files

def write_files(cid: str, row: dict, v: dict, folder: Path, cv_name: str) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    files = []
    if v["email"]:
        text = (f"To: {v['email']}\n"
                f"Contact: {v['contact'] or '?'}{' — ' + v['role'] if v['role'] else ''}\n"
                f"Address found on: {v['email_source']}\n"
                f"Subject: {v['subject']}\n"
                f"Attachment: {cv_name}\n"
                f"After sending: /sent {cid}\n"
                "----------------------------------------------------------------\n\n"
                f"{v['body']}\n")
        path = folder / "email.txt"
        common.atomic_write_text(path, text)
        files.append(path)
    if v["linkedin"] and v["linkedin_message"]:
        text = (f"Profile: {v['linkedin']}\n"
                f"Contact: {v['contact'] or '?'}{' — ' + v['role'] if v['role'] else ''}\n"
                f"Profile found on: {v['linkedin_source']}\n"
                f"Message ({len(v['linkedin_message'])}/{LINKEDIN_MAX} characters):\n"
                "----------------------------------------------------------------\n\n"
                f"{v['linkedin_message']}\n")
        path = folder / "linkedin.txt"
        common.atomic_write_text(path, text)
        files.append(path)
    return files


def summary(cid: str, row: dict, v: dict, notes: list[str], test: bool) -> str:
    lines = [t("spont.summary_title", tag="[TEST] " if test else "", id=tg.esc(cid), name=tg.esc(row['name'])),
             t("spont.summary_contact", contact=tg.esc(v['contact'] or '?')) + (f" — {tg.esc(v['role'])}" if v["role"] else "")]
    if v["email"]:
        lines.append(t("spont.summary_email", email=tg.esc(v['email']), source=tg.link(v['email_source'], t("common.source"))))
    if v["linkedin"]:
        lines.append(t("spont.summary_linkedin", profile=tg.link(v['linkedin'], t("spont.profile")),
                       source=tg.link(v['linkedin_source'], t("common.source")))
                     + ("" if v["linkedin_message"] else t("spont.no_message")))
    lines.append(t("spont.summary_cv", variant=tg.esc(v['variant']), site=tg.link(row['website'])))
    lines += [f"<i>{tg.esc(n)}</i>" for n in notes]
    lines.append(t("spont.summary_after", id=tg.esc(cid)))
    return "\n".join(lines)


# ------------------------------------------------------------------ main flow

def _read_output(out: Path):
    """Claude's output file, or None when it is missing or not JSON (validate() then reports it)."""
    try:
        return common.read_json(out, None)
    except (ValueError, OSError):
        return None


def _release_draft(cid: str, test: bool) -> None:
    """The ID reserved by run() is given back when nothing was prepared — also after a crash: a
    leftover `draft` row would mark the company as already contacted for ever."""
    try:
        with common.state_lock():
            rows = contacts.load(test)
            kept = [r for r in rows if not (r["id"] == cid and r["status"] == "draft")]
            if len(kept) != len(rows):
                contacts.save(kept, test)
    except Exception as exc:  # noqa: BLE001 — cleanup must not hide the original error
        common.log(f"spont {cid}: could not remove the draft row ({type(exc).__name__})")


def run(name: str, fetcher: Fetcher | None = None) -> int:
    test = common.dry_run()
    row, refusal = eligible(name)
    if refusal:
        tg.send(t("spont.refused", name=tg.esc(name), why=tg.esc(refusal)))
        return 1
    whitelist = sites.load()
    host = companies.website_host(row["website"])
    if not sites.is_allowed(host, whitelist):
        with common.state_lock():
            data = sites.load()
            vendors.add_pending(data, host, row["source"] or row["website"], common.local_now().date().isoformat())
            sites.save(data)
        tg.send(t("spont.site_not_allowed", name=tg.esc(row['name']), site=tg.link(row['website'], host)))
        return 2
    if not discover.command_installed(COMMAND):
        tg.send(t("spont.not_installed"))
        return 1
    if not (common.state_dir() / "scan-settings.json").is_file():
        tg.send("/spont : " + t("common.whitelist_missing") + ".")
        return 1
    variants = build_cv_variants.variants() or [DEFAULT_VARIANT]
    with common.state_lock():
        rows = contacts.load(test)
        cid = contacts.next_id(rows, test)
        rows.append({"id": cid, "company": row["name"], "status": "draft", "prepared": common.iso()})
        contacts.save(rows, test)  # reserve the ID; removed again if nothing is prepared

    prepared = False
    try:
        schedule = common.load_schedule()
        runs = common.runs_dir()
        out, request = runs / f"spont-{cid}.json", runs / f"spont-{cid}-request.json"
        cv_root = build_cv_variants.cv_dir()
        variant_files = [cv_root / "variants" / f"{v}.tex" for v in variants]
        common.atomic_write_json(request, {
            "id": cid, "company": row["name"], "city": row["city"], "website": row["website"],
            "careers_url": row["careers_url"] or None, "official_hosts": sorted(official_hosts(row)),
            "variants": variants, "variant_paths": [str(p) for p in variant_files], "profile_path": str(common.profile_file().relative_to(common.ROOT)),
            "linkedin_max": LINKEDIN_MAX, "output_path": str(out),
        })
        fetch = [d for d in sites.allowed_domains(whitelist) if any(sites.matches(d, h) for h in official_hosts(row))]
        argv = discover.claude_argv(COMMAND, cid, [request, common.profile_file(), *variant_files], out, fetch,
                                    float(schedule["max_budget_usd_per_spont"]), str(schedule.get("spont_model") or "sonnet"))
        code, result = scan.invoke_claude(argv, runs / f"spont-{cid}-claude.json", TIMEOUT)
        info = postprocess.read_claude_output(Path(result))
        failure = postprocess.classify_failure(info, code)
        valid, notes = (None, [t("go.claude_failed", error=failure)]) if failure else \
            validate(_read_output(out), row, fetcher or Fetcher(whitelist), variants)

        with common.state_lock():
            rows = contacts.load(test)
            dup = valid and contacts.already_contacted([r for r in rows if r["id"] != cid], valid["email"], valid["linkedin"])
            if not valid or dup:
                contacts.save([r for r in rows if r["id"] != cid], test)
        if not valid or dup:
            why = t("spont.duplicate", id=dup["id"]) if dup else "; ".join(notes)
            tg.send(t("spont.nothing", name=tg.esc(row['name']), why=tg.esc(why)))
            return 1

        folder = root_dir(test) / apps.folder_name(row["name"], "")
        stem = f"{cid}_{apps.folder_name(row['name'], '')[:50]}"
        cv_name = f"{stem}_CV.pdf"
        source_pdf = build_cv_variants.variant_pdf(valid["variant"])
        if not source_pdf.exists():
            with common.state_lock():
                contacts.save([r for r in contacts.load(test) if r["id"] != cid], test)
            tg.send(t("spont.variant_missing", name=tg.esc(source_pdf.name)))
            return 1
        drafts = write_files(cid, row, valid, folder, cv_name)
        cv = folder / cv_name
        shutil.copyfile(source_pdf, cv)

        summary_id = tg.send(summary(cid, row, valid, notes, test))
        sent = []
        for path, label in [(p, f"{stem}_{p.name}") for p in drafts] + [(cv, cv_name)]:
            mid, err = tg.send_document(path, label, reply_to=summary_id)
            if mid:
                sent.append({"message_id": mid, "sent": common.iso(), "file": str(path), "name": label})
        with common.state_lock():
            rows = contacts.load(test)
            for r in rows:
                if r["id"] == cid:
                    r.update({"contact": valid["contact"], "role": valid["role"], "email": valid["email"],
                              "email_source": valid["email_source"], "linkedin": valid["linkedin"],
                              "linkedin_source": valid["linkedin_source"], "variant": valid["variant"],
                              "folder": str(folder), "prepared": common.iso(), "status": "prepared"})
            contacts.save(rows, test)
            prepared = True
            pend = common.read_json(pending_path(test), {}) or {}
            pend[cid] = {"id": cid, "company": row["name"], "dir": str(folder), "telegram": sent,
                         "summary_message_id": summary_id, "prepared": common.iso()}
            common.atomic_write_json(pending_path(test), pend)
        common.log(f"spont {cid} {row['name']}: email={bool(valid['email'])} linkedin={bool(valid['linkedin'])} "
                   f"cost={info['total_cost_usd']}")
        return 0

    finally:
        if not prepared:
            _release_draft(cid, test)

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("company", nargs="+")
    args = ap.parse_args(argv)
    name = " ".join(" ".join(args.company).split())
    try:
        with spont_lock(companies.key_of(name) or "x"):
            return run(name)
    except common.LockBusy:
        tg.send(t("spont.running_cmd", name=tg.esc(name)))
        return 3


if __name__ == "__main__":
    sys.exit(main())
