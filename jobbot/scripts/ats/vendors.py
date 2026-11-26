"""Recruiting software registry (SPEC §6 groups, §7 V3 connectors).

Each domain below was checked on 2026-11-24 in the VENDOR'S OWN documentation, and its robots.txt
was read. Only vendors with `connector: True` are ever queried. A vendor's `groups` are proposed to
the user through the whitelist (pending, with the documentation link as note) — never added as allowed
by code. Re-check before adding or changing an entry.
"""

from __future__ import annotations

import inspect
import re

import sites

VERIFIED = "2026-11-24"

VENDORS: dict[str, dict] = {
    "personio": {
        "label": "Personio",
        "connector": True,
        "groups": ["*.jobs.personio.de"],
        "doc": "https://developer.personio.de/docs/integration-of-open-positions",
        "robots": "User-agent: * / Allow: /",
        "detect": [r"https?://([a-z0-9][a-z0-9-]*)\.jobs\.personio\.(?:de|com)\b"],
    },
    "greenhouse": {
        "label": "Greenhouse",
        "connector": True,
        "groups": ["boards-api.greenhouse.io"],
        "doc": "https://docs.greenhouse.io/job-board.html",
        "robots": "User-agent: * / Disallow: /embed/ (API /v1/boards/ allowed)",
        "detect": [r"https?://(?:job-)?boards(?:-api)?\.greenhouse\.io/(?:v1/boards/)?(?!embed\b)([A-Za-z0-9_-]+)",
                   r"greenhouse\.io/embed/job_board(?:/js)?\?for=([A-Za-z0-9_-]+)"],
    },
    "lever": {
        "label": "Lever",
        "connector": True,
        "groups": ["api.lever.co", "api.eu.lever.co"],
        "doc": "https://github.com/lever/postings-api",
        "robots": "User-agent: * / Allow: / / Crawl-delay: 1",
        # slug "eu:<site>" for the EU instance (jobs.eu.lever.co -> api.eu.lever.co)
        "detect": [r"https?://jobs\.(eu\.)?lever\.co/([A-Za-z0-9_.-]+)"],
    },
    "workday": {
        "label": "Workday", "connector": False,
        "why": "the myworkdayjobs.com domain and postings API are not documented by Workday",
        "detect": [r"https?://([a-z0-9-]+)\.wd\d+\.myworkdayjobs\.com\b"],
    },
    "successfactors": {
        "label": "SuccessFactors", "connector": False,
        "why": "robots.txt of the career sites: Disallow: / (and /*company)",
        "detect": [r"(?:career|performancemanager)\d*\.successfactors\.(?:eu|com)/career\?[^\"'\s<>]*company=([A-Za-z0-9_]+)",
                   r"https?://([a-z0-9-]+)\.(?:jobs|careers)\.successfactors\.(?:eu|com)\b"],
    },
    "smartrecruiters": {
        "label": "SmartRecruiters", "connector": False,
        "why": "robots.txt of api.smartrecruiters.com: Disallow: / (except LinkedInBot)",
        "detect": [r"https?://(?:jobs|careers)\.smartrecruiters\.com/([A-Za-z0-9_-]+)"],
    },
    "recruitee": {
        "label": "Recruitee", "connector": False,
        "why": "a per-company token is required from 2027-02-10; robots.txt not checked",
        "detect": [r"https?://([a-z0-9-]+)\.recruitee\.com\b"],
    },
    "softgarden": {
        "label": "softgarden", "connector": False, "why": "API reserved for customers (customer identifier)",
        "detect": [r"https?://([a-z0-9-]+)\.softgarden\.io\b"],
    },
    "onlyfy": {
        "label": "onlyfy (Prescreen)", "connector": False, "why": "no public documentation found",
        "detect": [r"https?://([a-z0-9-]+)\.onlyfy\.jobs\b", r"https?://([a-z0-9-]+)\.prescreenapp\.io\b"],
    },
}

_IGNORED_SLUGS = {"www", "api", "jobs", "careers", "embed", "static", "assets", "cdn"}


def detect_in(text: str) -> tuple[str, str] | None:
    """First vendor whose pattern appears in text/URL -> (vendor, slug). Connector vendors first."""
    order = sorted(VENDORS, key=lambda v: not VENDORS[v]["connector"])
    for vendor in order:
        for pattern in VENDORS[vendor]["detect"]:
            for m in re.finditer(pattern, text or "", re.IGNORECASE):
                if vendor == "lever":
                    slug = ("eu:" if m.group(1) else "") + m.group(2)
                else:
                    slug = m.group(1)
                if slug.lower() in _IGNORED_SLUGS:
                    continue
                return vendor, slug.lower() if vendor in ("personio", "workday", "recruitee", "softgarden") else slug
    return None


def hosts_for(vendor: str, slug: str) -> list[str]:
    """The API hosts a connector will call for this company."""
    if vendor == "personio":
        return [f"{slug}.jobs.personio.de"]
    if vendor == "greenhouse":
        return ["boards-api.greenhouse.io"]
    if vendor == "lever":
        return ["api.eu.lever.co" if slug.startswith("eu:") else "api.lever.co"]
    return []


def group_for(vendor: str, host: str) -> str | None:
    for group in VENDORS[vendor].get("groups") or []:
        if sites.matches(group, host):
            return group
    return None


def group_note(vendor: str) -> str:
    v = VENDORS[vendor]
    return f"{v['label']} group — official domain checked on {VERIFIED}: {v['doc']}"


def add_pending(data: dict, host: str, requested_by: str | None, today: str, note: str | None = None) -> bool:
    """sites.add_pending, passing `note` only if the installed sites.py accepts it (the extended
    version is reviewed and copied by the user themselves)."""
    if note and "note" in inspect.signature(sites.add_pending).parameters:
        return sites.add_pending(data, host, requested_by, today, note=note)
    return sites.add_pending(data, host, requested_by, today)
