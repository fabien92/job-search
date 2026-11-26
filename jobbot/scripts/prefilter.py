#!/usr/bin/env python3
"""Scan stage 1 (zero tokens): portals -> fixed rules -> dedup -> detail -> posting_guard -> batch.

    jobbot/.venv/bin/python jobbot/scripts/prefilter.py --run-id <id> [--site all|karriere|linkedin|derstandard|uncareers|unido|osce|opecfund|hays|jobgether|randstad|profession|kariera|michaelpage|companies]

`companies` (V3): career pages of companies.csv through the recruiting-software connectors
(ats/company_scan.py), at most every `companies_every_hours` with --site all, forced with --site companies.

Writes (nothing definitive — postprocess.py records the outcome under the lock):
  jobbot/state/runs/<id>-batch.json      what Claude scores: metadata + path of each cleaned posting
  jobbot/state/runs/<id>-prefilter.json  everything else: rule rejections, duplicates, per-site counts, errors
  <cache>/runs/<id>/postings/*.txt       cleaned posting text (posting_guard.py --out refuses the repo)
Exit 0 when the stage ran (even with portal errors, which are reported), 1 on a fatal error.
Prints one JSON line: {"to_score": n, ...}.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time

import common
import companies
import dedup
import sites
from ats import company_scan
from i18n import t

SCORING_FLAGS = ("german_check", "duration_unknown", "suspicious", "detail_unavailable")  # scoring.flag.<name>

# High-volume boards queried with many titles every run: last in line when the scoring cap is reached.
BIG_BOARDS = {"karriere", "linkedin", "derstandard", "jobgether"}

PORTALS = {
    "karriere": {"skill": "karriere-search", "domain": "karriere.at", "countries": {"AT"}},
    "linkedin": {"skill": "linkedin-search", "domain": "linkedin.com", "countries": None},  # any country + remote
    # V4 (§7): page 1 only (20 results, relevance order), no age parameter -> --jobage client-side
    "derstandard": {"skill": "derstandard-search", "domain": "jobs.derstandard.at", "countries": {"AT"}},
    "uncareers": {"skill": "un-careers-search", "domain": "careers.un.org", "countries": None},  # UN Secretariat duty stations
    "unido": {"skill": "unido-search", "domain": "careers.unido.org", "countries": None},  # ~20 openings, mostly Vienna
    # ~45 openings, Vienna Secretariat + field missions; the CLI walks the whole board (~5 requests) per query
    "osce": {"skill": "osce-search", "domain": "vacancies.osce.org", "countries": None},
    # < 10 openings, all at the Vienna HQ; one request covers the board
    "opecfund": {"skill": "opecfund-search", "domain": "careers.opecfund.org", "countries": None},
    # ~70 openings in Austria (recruiter, client not named); the CLI walks all of Austria (~4 pages,
    # 10 s apart) per query; robots.txt Crawl-delay 10 also spaces the detail requests
    "hays": {"skill": "hays-search", "domain": "www.hays.at", "countries": {"AT"}, "crawl_delay": 10},
    # remote only (public API for AI agents); depends on remote_worldwide, not on the regions. The
    # API has no description: search results carry the listing fields as the detail (no request)
    "jobgether": {"skill": "jobgether-search", "domain": "jobgether.com", "countries": None},
    # ~40 openings in Vienna, ~520 in Austria (staffing agency, client not named, mostly blue-collar);
    # no keyword search (robots.txt): the CLI walks the IT (EDV & IT) listing of each city
    # (/jobs/s-edv-it/wien/wien/, a handful of openings, one page)
    "randstad": {"skill": "randstad-search", "domain": "www.randstad.at", "countries": {"AT"}},
    # Hungary: the board's official RSS feed of the IT category (20 newest openings, no posting date);
    # the CLI keeps the enabled towns. Date and address come with the detail: rules checked again then
    "profession": {"skill": "profession-search", "domain": "www.profession.hu", "countries": {"HU"},
                   "recheck_after_detail": True},
    # Slovakia: the public listings of the two IT categories for the enabled Slovak regions (30 cards
    # per page, newest first, card date); no keyword search (robots.txt disallows ?q=)
    "kariera": {"skill": "kariera-search", "domain": "kariera.zoznam.sk", "countries": {"SK"}},
    # Recruitment agency (client not named): the public IT listing of Vienna (~45 openings, 2 pages,
    # relevance order) or of Austria; no date on the list (the ref is the creation month): date,
    # address and remote status come from the detail's JSON-LD, then the rules run again. The
    # detail page needs its slug: the CLI gets the posting URL, not the ref
    "michaelpage": {"skill": "michaelpage-search", "domain": "www.michaelpage.at", "countries": {"AT"},
                    "recheck_after_detail": True, "detail_by_url": True, "crawl_delay": 3},
}
JOBGETHER_LOCATION = "austria"  # API slug: offers open to Austria (incl. Europe, EMEA, Anywhere); --strict drops Anywhere-only
OSCE_EXCLUDED_TYPES = {"Intern", "Consultant"}  # detail jobType; seconded posts stay (flagged in employment_type)
# Hays and Randstad (staffing agencies, every trade in one listing): off-target trades dropped by title
# before any token is spent (reason not_it, hidden in /rejets). German stems match inside compounds
# (Bilanzbuchhalter, Teamassistenz, Elektrotechniker); Steuer but not Steuerung (Projektsteuerung).
AGENCY_SITES = {"hays", "randstad"}
AGENCY_TITLE_EXCLUSIONS = re.compile(r"buchhalt|elektr|assisten[tz]|\bassistant\b|\blegal\b|\btax\b|steuer(?!ung)", re.IGNORECASE)
COUNTRY_NAMES = {"AT": "Austria", "SK": "Slovakia", "HU": "Hungary", "DE": "Germany", "CZ": "Czechia"}
REMOTE_LINKEDIN_LOCATION = "European Union"
CLI_TIMEOUT = 120
DETAIL_TEXT_MAX = 20000


# ------------------------------------------------------------------ criteria.md

# criteria.md sections the scripts read, by heading ("## <heading> …", matched as a prefix, case and
# apostrophe style ignored): the French heading or its English equivalent. The other sections (Lieu /
# Location, Langue / Language, Contrat / Contract, Salaire / Salary, Profil pour la notation / Scoring
# profile, Seuil) are read by the scoring model only.
SECTIONS = {
    "titles": ("Intitulés recherchés", "Target titles"),
    "keywords": ("Mots-clés métier", "Keywords"),
    "title_exclusions": ("Exclusions d'intitulé", "Title exclusions"),
    "type_exclusions": ("Exclusions de type", "Type exclusions"),
    "company_exclusions": ("Entreprises exclues", "Excluded companies"),
}
_LIST_MARK = re.compile(r"^[-*]\s+")


class CriteriaError(ValueError):
    """criteria.md cannot drive a scan (e.g. no target title found)."""


def _heading(value: str) -> str:
    return value.replace("\u2019", "'").strip().casefold()


def _section(text: str, title_prefix) -> str:
    """Body of the level-2 section whose heading starts with one of the given prefixes."""
    prefixes = [_heading(p) for p in ([title_prefix] if isinstance(title_prefix, str) else title_prefix)]
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("## "):
            inside = _heading(line[3:]).startswith(tuple(prefixes))
            continue
        if inside:
            out.append(line)
    return "\n".join(out)


def _split_items(line: str) -> list[str]:
    return [item for item in (part.strip().strip("*").strip() for part in line.split("·")) if item]


def _dot_list(block: str, prefix: str | None = None) -> list[str]:
    """Items of a "A · B · C" line.

    With a prefix ("EN", "DE"): every line "<prefix> : A · B" (a single item is fine).
    Without: the first list line of the section — the first line holding a "·", else the first plain
    line, taken as a one-item list ("Deloitte"). Notes in brackets, comments and "label: …" lines are skipped."""
    items, single = [], None
    for line in block.splitlines():
        line = _LIST_MARK.sub("", line.strip())
        if not line or line.startswith("(") or line.startswith("<!--"):
            continue
        if prefix:
            m = re.match(rf"{re.escape(prefix)}\s*:(.*)$", line, re.IGNORECASE)
            if m:
                items.extend(_split_items(m.group(1)))
            continue
        if ":" in line[:5]:
            continue
        if "·" in line:
            return _split_items(line)
        if single is None:
            single = line
    if not prefix and single is not None:
        return _split_items(single)
    return items


def load_criteria() -> dict:
    text = (common.config_dir() / "criteria.md").read_text(encoding="utf-8")
    titles = _section(text, SECTIONS["titles"])
    exclusions = []
    for item in _dot_list(_section(text, SECTIONS["title_exclusions"])):
        exclusions.extend(part.strip() for part in item.split("/") if part.strip())
    return {
        "titles_en": _dot_list(titles, "EN"),
        "titles_de": _dot_list(titles, "DE"),
        "keywords": _dot_list(_section(text, SECTIONS["keywords"])),
        "title_exclusions": exclusions,
        "type_exclusions": _dot_list(_section(text, SECTIONS["type_exclusions"])),
        "company_exclusions": _dot_list(_section(text, SECTIONS["company_exclusions"])),
    }


def require_titles(criteria: dict) -> None:
    """A scan without any target title would query nothing and report nothing: fail loudly instead."""
    if not criteria["titles_en"] and not criteria["titles_de"]:
        raise CriteriaError(
            "criteria.md: no target title found — expected a section "
            "'## Target titles' with lines 'EN : Title · Title' and/or 'DE : Titel · Titel'")


def age_days(posted, today) -> int | None:
    """Days since an ISO date (YYYY-MM-DD…); None when the value is missing or not a date."""
    try:
        return (today - common.dt.date.fromisoformat(str(posted)[:10])).days
    except (TypeError, ValueError):
        return None


# English "Intern" as a title word ("Marketing Intern", "IT Intern (m/f/d)"). Case-sensitive on purpose:
# German "intern" (internal: "IT-Consultant intern (m/w/d)", "Projektleiter IT (intern)") is written in
# lower case and must not be rejected as an internship. "Intern/Extern" is German too.
_INTERN = re.compile(r"(?<![\w/])(?:Intern|INTERN)(?![\w])(?!\s*/\s*[Ee][Xx][Tt][Ee][Rr][Nn])")


def _word_regex(terms: list[str]) -> re.Pattern | None:
    terms = [t for t in terms if t]
    if not terms:
        return None
    return re.compile(r"(?<![\w])(?:" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True)) + r")(?![\w])",
                      re.IGNORECASE)


class Rules:
    def __init__(self, criteria: dict, regions: dict, freshness_hours: int):
        self.title = _word_regex(criteria["title_exclusions"])
        # Werkstudent also as a prefix (Werkstudentin, Werkstudent:in); internship/intern/trainee as words;
        # Hungarian gyakornok (intern) also as gyakornoki (internship programme);
        # Slovak stáž (internship) also as stáže (plural/genitive) and stážista/stážistka (intern).
        # English "Intern" is matched apart (_INTERN, case-sensitive): German "intern" means internal.
        self.type = _word_regex(criteria["type_exclusions"] + ["Werkstudentin", "Praktikant", "Praktikantin", "Gyakornoki",
                                                              "Stáže", "Stážista", "Stážistka"])
        self.companies = {dedup.norm_company(c) for c in criteria["company_exclusions"]}
        self.blocked = companies.blocked_keys()  # /block (V3)
        self.max_age_days = max(1, math.ceil(freshness_hours / 24))
        self.aliases = dedup.city_aliases(regions["regions"])
        self.enabled = {key for key, r in regions["regions"].items() if (r or {}).get("enabled")}

    def check(self, job: dict, today) -> str | None:
        title = str(job.get("title") or "")
        if (self.type and self.type.search(title)) or _INTERN.search(title):
            return "internship"
        if self.title and self.title.search(title):
            return "title_excluded"
        if job.get("site") in AGENCY_SITES and AGENCY_TITLE_EXCLUSIONS.search(title):
            return "not_it"
        company = dedup.norm_company(job.get("company"))
        if company and any(company == c or company.startswith(c + " ") for c in self.companies):
            return "company_excluded"
        if company and companies.is_blocked(company, self.blocked):
            return "company_blocked"
        age = age_days(job.get("date"), today) if job.get("date") else None
        if age is not None and age > int(job.get("max_age_days") or self.max_age_days):
            return "too_old"
        if not job.get("remote_query") and job.get("location"):
            city = dedup.norm_city(job["location"], self.aliases)
            known = city in self.aliases.values()
            if known and city not in self.enabled and not self._any_enabled(job["location"]):
                return "location_outside_regions"
        return None

    def revivable(self, job: dict, today):
        """-> predicate for dedup.check_search_hit: a ledger entry rejected only because its region was
        switched off no longer hides the posting once the rules accept it (/region on). The location must
        be known now: boards that learn it from the detail page would otherwise be re-read every run."""
        def check(entry: dict) -> bool:
            return (entry.get("reason") == "location_outside_regions" and bool(job.get("location"))
                    and self.check(job, today) is None)
        return check

    def _any_enabled(self, location: str) -> bool:
        raw = dedup._finish(dedup._base(location))
        return any(alias in raw.split() or alias == raw for alias, key in self.aliases.items() if key in self.enabled)


# ------------------------------------------------------------------ portals

def bun_cmd() -> list[str]:
    return [os.environ.get("JOBBOT_BUN", "bun")]


def run_cli(portal: str, args: list[str]) -> dict:
    cli = common.ROOT / ".agents" / "skills" / PORTALS[portal]["skill"] / "cli" / "src" / "cli.ts"
    cmd = [*bun_cmd(), "run", str(cli), *args]
    try:
        proc = subprocess.run(cmd, cwd=common.ROOT, capture_output=True, text=True, timeout=CLI_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{portal}: {type(exc).__name__}: {exc}") from exc
    if proc.returncode != 0:
        detail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f"exit {proc.returncode}"
        raise RuntimeError(f"{portal}: {detail[:300]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{portal}: non-JSON output") from exc


def delay(portal: str | None = None):
    """Pause between portal requests; a portal's robots.txt Crawl-delay wins (unless delays are off: 0)."""
    seconds = float(os.environ.get("JOBBOT_REQUEST_DELAY", "1.5"))
    if seconds > 0 and portal in PORTALS:
        seconds = max(seconds, float(PORTALS[portal].get("crawl_delay") or 0))
    time.sleep(seconds)


def linkedin_location(region: dict) -> str:
    names = region.get("names") or []
    country = COUNTRY_NAMES.get(region.get("country") or "", region.get("country") or "")
    city = names[1] if len(names) > 1 else (names[0] if names else country)
    return country if city in (country, "Österreich") else f"{city}, {country}"


def un_location(region: dict) -> str:
    """English city name for UN duty stations: names[1] when given (Wien -> Vienna), else names[0]."""
    names = region.get("names") or []
    return names[1] if len(names) > 1 else (names[0] if names else "")


def osce_runs_path():
    return common.state_dir() / "osce_runs.json"


def osce_due(schedule: dict, forced: bool) -> bool:
    """The OSCE board is walked at most every `osce_every_hours` (default 24) unless forced (--site osce)."""
    if forced:
        return True
    last = common.parse_iso((common.read_json(osce_runs_path(), {}) or {}).get("last"))
    hours = float(schedule.get("osce_every_hours") or 24)
    return last is None or (common.now() - last).total_seconds() >= hours * 3600 - 600


def record_osce_run() -> None:
    if not common.dry_run():
        common.atomic_write_json(osce_runs_path(), {"last": common.iso()})


RANDSTAD_PLACES = {"wien", "vienna", "vienne", "graz", "linz", "salzburg"}  # the CLI's city listings
RANDSTAD_SPECIALISM = "edv-it"  # Berufsfeld EDV & IT: /jobs/s-edv-it/<state>/<city>/
MICHAELPAGE_VIENNA = {"wien", "vienna", "vienne"}  # the CLI's IT listings: Vienna, or all of Austria


def michaelpage_query(enabled: list) -> dict | None:
    """Vienna's IT listing when `wien` is enabled; all of Austria when the `austria` region is (Vienna included).

    Other Austrian cities have no IT listing of their own: they are covered only by the Austria one."""
    at = [(k, r) for k, r in enabled if r.get("country") == "AT"]
    if any(k == "austria" for k, _ in at):
        location = "Österreich"
    elif any(n.lower() in MICHAELPAGE_VIENNA for _, r in at for n in (r.get("names") or [])):
        location = "Wien"
    else:
        return None
    return {"portal": "michaelpage", "query": "", "location": location, "region": ",".join(k for k, _ in at), "remote": False}


def hays_query(enabled: list, portal: str = "hays") -> dict:
    """Every spelling of the enabled Austrian cities; the `austria` region (rest of Austria) lifts the filter.

    Randstad walks one listing per city and refuses other places: only the spellings it knows are sent."""
    at = [(k, r) for k, r in enabled if r.get("country") == "AT"]
    whole = any(k == "austria" for k, _ in at)
    names = [] if whole else list(dict.fromkeys(n for _, r in at for n in (r.get("names") or [])))
    if portal == "randstad":
        names = [n for n in names if n.lower() in RANDSTAD_PLACES]
    return {"portal": portal, "query": "", "location": ",".join(names), "region": ",".join(k for k, _ in at), "remote": False}


def cap_order(candidates: list[dict]) -> list[dict]:
    """Scoring order under the cap: small boards and company pages before BIG_BOARDS, newest first in each."""
    by_date = sorted(candidates, key=lambda j: str(j.get("date") or ""), reverse=True)
    return sorted(by_date, key=lambda j: j.get("site") in BIG_BOARDS)  # stable sort keeps the date order


def plan_queries(criteria: dict, regions: dict, schedule: dict, portals: list[str]) -> list[dict]:
    """(portal, query, location, remote) tuples, capped per portal by queries_per_run."""
    enabled = [(k, r) for k, r in regions["regions"].items() if (r or {}).get("enabled")]
    caps = schedule["queries_per_run"]
    plan = []
    for portal in portals:
        if portal in ("uncareers", "unido"):  # small IO boards: one location-only query per city region
            jobs = [{"portal": portal, "query": "", "location": un_location(r), "region": k, "remote": False}
                    for k, r in enabled if k != "austria"]
        elif portal in ("osce", "opecfund"):  # one fetch of the whole board, filtered on every enabled city at once
            cities = [(k, un_location(r)) for k, r in enabled if k != "austria" and un_location(r)]
            jobs = [{"portal": portal, "query": "", "location": ",".join(c for _, c in cities),
                     "region": ",".join(k for k, _ in cities), "remote": False}] if cities else []
        elif portal == "hays":  # one walk of Hays Austria, filtered on the enabled Austrian regions
            jobs = [hays_query(enabled)] if any(r.get("country") == "AT" for _, r in enabled) else []
        elif portal == "randstad":  # one walk of the IT listings of the enabled Austrian cities (or all of Austria)
            q = hays_query(enabled, "randstad")
            jobs = [q] if q["region"] and (q["location"] or "austria" in q["region"].split(",")) else []
        elif portal == "michaelpage":  # one walk of the IT listing of Vienna (or of all of Austria)
            q = michaelpage_query(enabled)
            jobs = [q] if q else []
        elif portal == "profession":  # one read of the IT feed, filtered on the enabled Hungarian towns
            hu = [(k, r) for k, r in enabled if r.get("country") == "HU"]
            names = list(dict.fromkeys(n for _, r in hu for n in (r.get("names") or [])))
            jobs = [{"portal": portal, "query": "", "location": ",".join(names),
                     "region": ",".join(k for k, _ in hu), "remote": False}] if names else []
        elif portal == "kariera":  # one walk of the IT listings of the enabled Slovak regions
            sk = [(k, r) for k, r in enabled if r.get("country") == "SK"]
            names = list(dict.fromkeys((r.get("names") or [k])[0] for k, r in sk))
            jobs = [{"portal": portal, "query": "", "location": ",".join(names),
                     "region": ",".join(k for k, _ in sk), "remote": False}] if names else []
        elif portal == "jobgether":  # remote only: EN titles, only when remote_worldwide is on
            jobs = [{"portal": portal, "query": t, "location": JOBGETHER_LOCATION, "region": "remote", "remote": True}
                    for t in criteria["titles_en"]] if regions["remote_worldwide"] else []
        elif portal in ("karriere", "derstandard"):  # Austrian boards: DE + EN titles + keywords, AT regions only
            terms = criteria["titles_de"] + criteria["titles_en"] + criteria["keywords"]
            locations = [(k, (r.get("names") or [k])[0]) for k, r in enabled if r.get("country") in PORTALS[portal]["countries"]]
            jobs = [{"portal": portal, "query": t, "location": loc, "region": k, "remote": False} for k, loc in locations for t in terms]
        else:
            terms = criteria["titles_en"]
            jobs = [{"portal": portal, "query": t, "location": linkedin_location(r), "region": k, "remote": False}
                    for k, r in enabled for t in terms]
            if regions["remote_worldwide"]:
                # Interleave remote queries so the cap does not starve them.
                remote = [{"portal": portal, "query": t, "location": REMOTE_LINKEDIN_LOCATION, "region": "remote", "remote": True}
                          for t in terms]
                mixed = []
                for i in range(max(len(jobs), len(remote))):
                    mixed.extend(x[i] for x in (jobs, remote) if i < len(x))
                jobs = mixed
        seen, capped = set(), []
        for job in jobs:
            key = (job["query"].casefold(), job["location"], job["remote"])
            if key not in seen:
                seen.add(key)
                capped.append(job)
        plan.extend(capped[: int(caps.get(portal, 10))])
    return plan


def search_args(q: dict, max_age_days: int, page: int = 1, freshness_hours: int = 48) -> list[str]:
    if q["portal"] == "karriere":
        return ["search", "-q", q["query"], "-l", q["location"], "--jobage", str(max_age_days), "--page", str(page)]
    if q["portal"] == "derstandard":  # single page: the CLI refuses --page above 1
        return ["search", "-q", q["query"], "-l", q["location"], "--jobage", str(max_age_days)]
    if q["portal"] == "uncareers":  # location only, 100 per page: one page covers a duty station
        return ["search", "-l", q["location"], "--jobage", str(max_age_days)]
    if q["portal"] == "unido":  # no posting date in the list (detail has it): no --jobage
        return ["search", "-l", q["location"]]
    if q["portal"] == "osce":  # no dates in the list either; comma-separated cities, whole board
        return ["search", "-l", q["location"]]
    if q["portal"] == "opecfund":  # whole board in one request; the list has the posting date
        return ["search", "-l", q["location"], "--jobage", str(max_age_days)]
    if q["portal"] in ("hays", "randstad"):  # whole of Austria; no -l when the rest of Austria is enabled too
        # Randstad: the IT listing only (Hays keeps the full walk: its Specialism filter would lose
        # useful openings filed under Other or Engineering)
        field = ["-s", RANDSTAD_SPECIALISM] if q["portal"] == "randstad" else []
        return ["search", *(["-l", q["location"]] if q["location"] else []), *field, "--jobage", str(max_age_days)]
    if q["portal"] == "michaelpage":  # whole IT listing (2 pages); no date on the list: no --jobage
        return ["search", "-l", q["location"]]
    if q["portal"] == "profession":  # IT feed (20 newest, no date: --jobage would be meaningless)
        return ["search", "-l", q["location"]]
    if q["portal"] == "kariera":  # both IT listings, next pages only while a whole page is fresh
        return ["search", "-l", q["location"], "--jobage", str(max_age_days)]
    if q["portal"] == "jobgether":  # newest first, stops at older offers; --strict: Europe/EMEA/Austria named
        return ["search", "-q", q["query"], "-l", q["location"], "--strict", "--jobage", str(max_age_days)]
    args = ["search", "-q", q["query"], "-l", q["location"], "--jobage-minutes", str(int(freshness_hours) * 60)]
    if q["remote"]:
        args += ["--remote", "remote"]
    return args


def to_job(portal: str, raw: dict, q: dict) -> dict | None:
    if not isinstance(raw, dict) or not raw.get("id") or not raw.get("title") or not raw.get("url"):
        return None
    if not isinstance(raw["title"], str) or not isinstance(raw["url"], str):
        return None  # scraped fields in an unexpected shape: not a posting
    return {
        "site": portal,
        "id": str(raw["id"]),
        "title": raw.get("title"),
        "company": raw.get("company"),
        "location": raw.get("location"),
        "date": raw.get("date") if isinstance(raw.get("date"), str) else None,
        "url": raw.get("url"),
        "salary": raw.get("salary"),
        "employment_type": raw.get("employmentType"),
        "home_office": raw.get("homeOffice"),
        "summary": raw.get("summary"),
        "pushed": bool(raw.get("pushed")),
        "query": q["query"],
        "region": q["region"],
        "remote_query": q["remote"],
        # Jobgether: no detail endpoint; the listing (with its built description) is the detail
        **({"detail": raw} if portal == "jobgether" else {}),
    }


# ------------------------------------------------------------------ LinkedIn quota

def linkedin_quota_ok(schedule: dict, record: bool) -> bool:
    path = common.state_dir() / "linkedin_runs.json"
    runs = common.read_json(path, []) or []
    now = common.local_now()
    today = [common.parse_iso(r) for r in runs]
    today = [t for t in today if t and t.astimezone(common.tz()).date() == now.date()]
    per_day = int(schedule.get("linkedin_runs_per_day") or 0)
    if per_day <= 0 or len(today) >= per_day:
        return False
    min_gap_h = 24 / per_day - 0.5
    if today and (now - max(today)).total_seconds() < min_gap_h * 3600:
        return False
    if record and not common.dry_run():
        recent = [r for r in runs if (common.parse_iso(r) or now) > now - common.dt.timedelta(days=7)]
        with common.state_lock():
            common.atomic_write_json(path, recent + [common.iso()])
    return True


# ------------------------------------------------------------------ posting guard

GUARD_TIMEOUT = 60
NO_TEXT_PREFIX = "posting_guard: refused (no text"  # posting_guard.NO_TEXT_VERDICT: nothing to score, ever


def guard(raw_path, clean_path) -> dict:
    try:
        proc = subprocess.run(
            [sys.executable, str(common.TOOLS / "posting_guard.py"), "--in", str(raw_path), "--text", "--json", "--out", str(clean_path)],
            capture_output=True, text=True, timeout=GUARD_TIMEOUT, cwd=common.ROOT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # one posting must not stop the run
        return {"ok": False, "verdict": f"posting_guard: {type(exc).__name__}", "alarm": False, "instruction_like": []}
    out = proc.stdout
    verdict = out.splitlines()[0].strip() if out.strip() else f"posting_guard: exit {proc.returncode}"
    findings = {}
    if "--- findings ---" in out:
        block = out.split("--- findings ---", 1)[1].split("\nsaved=", 1)[0]
        try:
            findings = json.loads(block)
        except json.JSONDecodeError:
            findings = {}
    return {
        "ok": proc.returncode == 0 and clean_path.exists(),
        "verdict": verdict,
        "alarm": "⚠" in verdict,
        "instruction_like": (findings.get("instruction_like") or [])[:5],
    }


def batch_guard(result: dict | None) -> dict:
    """What the scoring model sees of a guard result: flags only, never the flagged text."""
    result = result or {}
    return {"ok": bool(result.get("ok")), "verdict": result.get("verdict"), "alarm": bool(result.get("alarm")),
            "instruction_like_found": bool(result.get("instruction_like"))}


def detail_text(portal: str, detail: dict) -> str:
    lines = [f"Title: {detail.get('title') or ''}", f"Company: {detail.get('company') or ''}",
             f"Location: {detail.get('location') or ''}"]
    for label, key in (("Posted", "date"), ("Valid through", "validThrough"), ("Employment", "employmentType"),
                       ("Level", "jobLevel"), ("Seniority", "seniority"), ("Home office", "homeOffice"), ("Salary", "salary")):
        if detail.get(key) not in (None, ""):
            lines.append(f"{label}: {detail[key]}")
    lines += ["", (detail.get("description") or "(no description)")[:DETAIL_TEXT_MAX]]
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------ main

def run(run_id: str, site: str) -> dict:
    schedule = common.load_schedule()
    regions = common.load_regions()
    criteria = load_criteria()
    if site != "companies":  # the company feeds need no title
        require_titles(criteria)
    rules = Rules(criteria, regions, int(schedule["freshness_hours"]))
    whitelist = sites.load()
    today = common.local_now().date()
    report = {"run_id": run_id, "site": site, "dry_run": common.dry_run(), "started": common.iso(),
              "sites": {}, "errors": [], "skipped_sites": [], "rejected": [], "duplicates": {}, "blocked_hosts": [],
              "deferred": 0, "cap_reached": False}

    portals = list(PORTALS) if site == "all" else ([] if site == "companies" else [site])
    active = []
    for portal in portals:
        domain = PORTALS[portal]["domain"]
        if not sites.is_allowed(domain, whitelist):
            report["skipped_sites"].append({"site": portal, "reason": f"{domain} not allowed in sites.yaml"})
            report["blocked_hosts"].append({"host": domain, "requested_by": f"portal {portal}"})
            continue
        if portal == "linkedin" and not linkedin_quota_ok(schedule, record=True):
            report["skipped_sites"].append({"site": portal, "reason": "linkedin_runs_per_day quota"})
            continue
        if portal == "osce" and not osce_due(schedule, forced=site == "osce"):
            report["skipped_sites"].append({"site": portal, "reason": "osce_every_hours"})
            continue
        active.append(portal)

    ledger = dedup.Ledger.load(rules.aliases)
    upstream = dedup.Upstream.load()
    batch_ids = dedup.Batch()
    candidates: list[dict] = []
    republish = dedup.republish_settings(schedule)

    def failed(where: dict, exc: Exception) -> None:
        """One query, company or posting failed: reported, the run goes on."""
        report["errors"].append({**where, "error": f"{type(exc).__name__}: {exc}"[:300]})
        common.log(f"prefilter: {where}: {type(exc).__name__}: {exc}")

    def screen(job: dict, employer_stage: bool = False) -> None:
        """Dedup + fixed rules for one search hit: -> candidates, report["rejected"] or a duplicate count."""
        dedup.annotate(job, rules.aliases)
        revivable = rules.revivable(job, today)
        reason = dedup.check_search_hit(job, ledger, upstream, batch_ids, revivable)
        if not reason and employer_stage:
            reason = dedup.check_employer_url(job, ledger, batch_ids)
        if reason:
            report["duplicates"][reason] = report["duplicates"].get(reason, 0) + 1
            return
        original = dedup.check_republished(job, ledger, batch_ids, republish)
        batch_ids.add(job)
        if original:  # V4: dropped silently, recorded as seen with reason "republished"
            job.pop("detail", None)
            report["rejected"].append({**job, "reason": "republished", "republished_of": original})
            return
        reason = rules.check(job, today)
        if reason:
            job["reason"] = reason
            job.pop("detail", None)
            report["rejected"].append(job)
        else:
            candidates.append(job)

    first = True
    for q in plan_queries(criteria, regions, schedule, active):
        stats = report["sites"].setdefault(q["portal"], {"queries": 0, "results": 0, "errors": 0})
        page = 1
        while page <= 2:
            if not first:
                delay()
            first = False
            try:
                out = run_cli(q["portal"], search_args(q, rules.max_age_days, page, schedule["freshness_hours"]))
            except RuntimeError as exc:
                stats["errors"] += 1
                report["errors"].append({"site": q["portal"], "query": q["query"], "error": str(exc)})
                break
            stats["queries"] += 1
            try:
                if q["portal"] == "osce":
                    record_osce_run()
                results = out.get("results") if isinstance(out, dict) else None
                if not isinstance(results, list):
                    raise ValueError("search output has no `results` list")
                stats["results"] += len(results)
            except Exception as exc:  # noqa: BLE001 - a broken answer costs this query only
                stats["errors"] += 1
                failed({"site": q["portal"], "query": q["query"]}, exc)
                break
            for raw in results:
                try:
                    job = to_job(q["portal"], raw, q)
                    if job:
                        screen(job)
                except Exception as exc:  # noqa: BLE001 - a broken card costs this card only
                    failed({"site": q["portal"], "query": q["query"],
                            "posting": str(raw.get("id") if isinstance(raw, dict) else None)}, exc)
            meta = out.get("meta") if isinstance(out.get("meta"), dict) else {}
            ages = [age_days(r.get("date"), today) for r in results
                    if isinstance(r, dict) and r.get("date") and not r.get("pushed")]
            all_fresh = bool(ages) and all(a is not None and a <= rules.max_age_days for a in ages)
            if q["portal"] == "karriere" and meta.get("hasMore") and all_fresh:
                page += 1
                continue
            break

    if site in ("all", "companies"):
        try:
            company_jobs = company_scan.collect(rules, ledger, regions, schedule, report, forced=site == "companies")
        except Exception as exc:  # noqa: BLE001 - the company stage must not take the portals down with it
            company_jobs = []
            report["sites"].setdefault("companies", {"queries": 0, "results": 0, "errors": 0})["errors"] += 1
            failed({"site": "companies"}, exc)
        for raw in company_jobs:
            try:
                job = {k: raw.get(k) for k in ("site", "id", "title", "company", "location", "date", "url", "salary",
                                               "employment_type", "home_office", "summary", "pushed", "query", "region",
                                               "remote_query", "max_age_days", "detail")}
                job["employer_url"] = dedup.clean_url(raw.get("employer_url") or raw.get("url"))
                screen(job, employer_stage=True)
            except Exception as exc:  # noqa: BLE001
                failed({"site": "companies", "posting": str(raw.get("id") if isinstance(raw, dict) else None)}, exc)

    # Cap: small boards and company pages first, then newest first; the rest is not recorded and comes
    # back next run. The big boards (read every run, dated) would otherwise always fill the cap and starve
    # undated offers (OSCE) and boards read once a day (OSCE, companies), whose deferred offers never return.
    candidates = cap_order(candidates)
    cap = int(schedule["max_scored_per_run"])
    if len(candidates) > cap:
        report["deferred"] = len(candidates) - cap
        report["cap_reached"] = True
        candidates = candidates[:cap]

    run_cache = common.cache_dir() / "runs" / run_id / "postings"
    run_cache.mkdir(parents=True, exist_ok=True)
    to_score = []

    def reject(job: dict, reason: str, **extra) -> None:
        """Recorded as seen by postprocess.py, so the posting is not fetched again next run."""
        job.update({"reason": reason, **extra})
        report["rejected"].append(job)

    def prepare(job: dict, ref: str) -> bool:
        """Detail, employer-URL dedup, rules again, posting_guard. True when the posting goes to scoring."""
        detail = job.pop("detail", None)  # company feeds and Jobgether carry it already (no request)
        if detail is None and job["site"] in PORTALS:
            delay(job["site"])
            try:
                target = job["url"] if PORTALS[job["site"]].get("detail_by_url") else job["id"]
                detail = run_cli(job["site"], ["detail", target])
            except RuntimeError as exc:
                report["errors"].append({"site": job["site"], "detail": job["id"], "error": str(exc)})
        if detail is not None and not isinstance(detail, dict):
            raise ValueError("detail output is not an object")
        if detail:
            if job["site"] in PORTALS:  # company feeds were checked against employer URLs already
                if detail.get("applyUrl"):
                    job["apply_url"] = detail["applyUrl"]
                    job["employer_url"] = dedup.clean_url(detail["applyUrl"])
                reason = dedup.check_employer_url(job, ledger, batch_ids)
                if reason:
                    report["duplicates"][reason] = report["duplicates"].get(reason, 0) + 1
                    # Recorded (reason "duplicate"): an unrecorded drop came back every run, cost a
                    # detail request and took a place under the scoring cap each time.
                    reject(job, "duplicate", duplicate_kind=reason)
                    return False
                if job.get("employer_url"):
                    batch_ids.urls.add(job["employer_url"])
            for key, src in (("date", "date"), ("employment_type", "employmentType"), ("salary", "salary"),
                             ("home_office", "homeOffice"), ("location", "location"), ("company", "company")):
                if detail.get(src) not in (None, "") and job.get(key) in (None, ""):
                    job[key] = detail[src]
            job["valid_through"] = detail.get("validThrough")
            job["is_active"] = detail.get("isActive", True)
            if PORTALS.get(job["site"], {}).get("recheck_after_detail"):  # date and address unknown before
                reason = rules.check(job, today)
                if reason:
                    reject(job, reason)
                    return False
            if job["site"] == "osce" and detail.get("jobType") in OSCE_EXCLUDED_TYPES:
                reject(job, "osce_" + detail["jobType"].lower())  # internship / consultancy (SSA)
                return False
            text = detail_text(job["site"], detail)
        else:
            job["detail_failed"] = True
            text = f"Title: {job['title']}\nCompany: {job.get('company') or ''}\nLocation: {job.get('location') or ''}\n\n" \
                   f"(detail unavailable — search summary only)\n{job.get('summary') or ''}\n"
        raw_path = run_cache / f"{ref}.raw.txt"
        clean_path = run_cache / f"{ref}.txt"
        raw_path.write_text(text, encoding="utf-8")
        try:
            job["guard"] = guard(raw_path, clean_path)
        finally:
            raw_path.unlink(missing_ok=True)
        if not job["guard"]["ok"]:
            report["errors"].append({"site": job["site"], "guard": job["id"], "error": job["guard"]["verdict"]})
            if job["guard"]["verdict"].startswith(NO_TEXT_PREFIX):
                reject(job, "no_text")  # deterministic: recorded. Any other guard failure is retried next run.
            return False
        job["ref"] = ref
        job["text_path"] = str(clean_path)
        job["same_company_30d"] = dedup.same_company_recent(ledger, job.get("company"))
        return True

    for index, job in enumerate(candidates, 1):
        try:
            if prepare(job, f"b{index}"):
                to_score.append(job)
        except Exception as exc:  # noqa: BLE001 - one posting must not stop the run; it comes back next run
            failed({"site": job.get("site"), "posting": str(job.get("id"))}, exc)

    report["finished"] = common.iso()
    batch = {
        "run_id": run_id,
        "dry_run": common.dry_run(),
        "alert_threshold": schedule["alert_threshold"],
        "freshness_hours": schedule["freshness_hours"],
        "scores_path": f"jobbot/state/runs/{run_id}-scores.json",
        # V5 i18n: Claude writes justification, adapt_reason and flags in the Telegram language (/lang).
        "language": t("scoring.language"),
        "flag_labels": {k: t(f"scoring.flag.{k}") for k in SCORING_FLAGS},
        # `guard` without the instruction_like excerpts: they are the very text the guard flagged, and this
        # file is read by the scoring model. The excerpts stay in <id>-prefilter.json (posting archive).
        "jobs": [{**{k: job.get(k) for k in (
            "ref", "site", "id", "title", "company", "location", "date", "valid_through", "url", "salary",
            "employment_type", "home_office", "remote_query", "pushed", "detail_failed", "is_active",
            "text_path", "same_company_30d")}, "guard": batch_guard(job.get("guard"))} for job in to_score],
    }
    common.atomic_write_json(common.runs_dir() / f"{run_id}-batch.json", batch)
    common.atomic_write_json(common.runs_dir() / f"{run_id}-prefilter.json", {**report, "to_score": to_score})
    return {"to_score": len(to_score), "rejected": len(report["rejected"]), "duplicates": sum(report["duplicates"].values()),
            "errors": len(report["errors"]), "sites": report["sites"], "skipped_sites": report["skipped_sites"],
            "cap_reached": report["cap_reached"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--site", default="all", choices=["all", *PORTALS, "companies"])
    args = ap.parse_args(argv)
    if not re.fullmatch(r"[0-9T]{15}(?:-[a-z0-9]+)?", args.run_id):
        print("prefilter: bad --run-id", file=sys.stderr)
        return 1
    try:
        summary = run(args.run_id, args.site)
    except (OSError, ValueError) as exc:
        print(f"prefilter: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
