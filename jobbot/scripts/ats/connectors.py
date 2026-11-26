"""One connector per recruiting software (SPEC §7 V3), not per company.

fetch_jobs(vendor, slug, company_name, fetcher) -> list of raw jobs in the prefilter.to_job shape,
each with a ready `detail` (title, company, location, date, description…) so no second request is
needed. Feeds are untrusted data: they only become text for posting_guard, never instructions.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser

from .web import FetchError

DESCRIPTION_MAX = 20000


class _Text(HTMLParser):
    BLOCK = {"p", "br", "li", "ul", "ol", "div", "h1", "h2", "h3", "h4", "tr", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")
        if tag == "li":
            self.out.append("- ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.skip:
            self.skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_to_text(value: str) -> str:
    parser = _Text()
    parser.feed(value or "")
    parser.close()
    text = "".join(parser.out)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s*\n\s*(\n\s*)+", "\n\n", text)
    return text.strip()[:DESCRIPTION_MAX]


def _date(value) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):  # Lever: epoch milliseconds
        try:
            return dt.datetime.fromtimestamp(value / 1000, dt.timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else None


def _job(vendor, slug, jid, title, company, location, date, url, description, employment=None, remote=None) -> dict:
    return {
        "site": vendor, "id": f"{slug}:{jid}", "title": title, "company": company, "location": location,
        "date": date, "url": url, "employer_url": url, "employment_type": employment, "home_office": remote,
        "detail": {"title": title, "company": company, "location": location, "date": date,
                   "employmentType": employment, "homeOffice": remote, "description": description},
    }


# ------------------------------------------------------------------ Personio (XML feed)

_PROLOG_SKIP = re.compile(r"\s*(?:<\?.*?\?>|<!--.*?-->)", re.DOTALL)


def has_doctype(body: str) -> bool:
    """True when the XML prolog declares a DOCTYPE (the only place entities can be defined).

    The whole prolog is walked — XML declaration, processing instructions and comments of any length —
    up to the root element: a DOCTYPE pushed behind a long comment is still seen."""
    pos = 1 if body.startswith("\ufeff") else 0
    while True:
        m = _PROLOG_SKIP.match(body, pos)
        if not m:
            break
        pos = m.end()
    rest = body[pos:].lstrip()
    # After comments and PIs only the root element may follow; "<!" is a DOCTYPE (or something
    # that is not a feed at all), an unterminated comment / PI is refused as well.
    return rest.startswith(("<!", "<?"))


def personio(slug: str, company: str, fetcher) -> list[dict]:
    url = f"https://{slug}.jobs.personio.de/xml?language=en"
    _, body = fetcher.get(url, accept="application/xml")
    if has_doctype(body):
        raise FetchError(url, "XML with DOCTYPE/ENTITY refused")
    try:
        root = ET.fromstring(body.encode("utf-8"))
    except ET.ParseError as exc:
        raise FetchError(url, f"invalid XML ({exc})") from exc
    jobs = []
    for pos in root.iter("position"):
        get = lambda tag: (pos.findtext(tag) or "").strip()  # noqa: E731
        jid, title = get("id"), get("name")
        if not jid or not title:
            continue
        parts = []
        for desc in pos.iter("jobDescription"):
            name, value = (desc.findtext("name") or "").strip(), desc.findtext("value") or ""
            parts.append((f"{name}\n" if name else "") + html_to_text(value))
        extra = pos.findall("additionalOffices/office") + pos.findall("additionalOffices/additionalOffice")
        offices = [get("office")] + [(o.text or "").strip() for o in extra]
        location = ", ".join(o for o in offices if o)
        employment = " · ".join(x for x in (get("employmentType"), get("schedule"), get("seniority")) if x) or None
        jobs.append(_job("personio", slug, jid, title, get("subcompany") or company, location or None,
                         _date(get("createdAt")), f"https://{slug}.jobs.personio.de/job/{jid}",
                         "\n\n".join(parts), employment))
    return jobs


# ------------------------------------------------------------------ Greenhouse (Job Board API)

def greenhouse(slug: str, company: str, fetcher) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    _, body = fetcher.get(url, accept="application/json")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FetchError(url, "invalid JSON") from exc
    jobs = []
    for raw in data.get("jobs") or []:
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("title"):
            continue
        location = (raw.get("location") or {}).get("name")
        content = html_to_text(html.unescape(raw.get("content") or ""))  # content is HTML-escaped HTML
        jobs.append(_job("greenhouse", slug, raw["id"], raw["title"], raw.get("company_name") or company, location,
                         _date(raw.get("first_published") or raw.get("updated_at")), raw.get("absolute_url"),
                         content))
    return jobs


# ------------------------------------------------------------------ Lever (Postings API)

def lever(slug: str, company: str, fetcher) -> list[dict]:
    eu = slug.startswith("eu:")
    site = slug[3:] if eu else slug
    url = f"https://{'api.eu.lever.co' if eu else 'api.lever.co'}/v0/postings/{site}?mode=json"
    _, body = fetcher.get(url, accept="application/json")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise FetchError(url, "invalid JSON") from exc
    jobs = []
    for raw in data if isinstance(data, list) else []:
        if not isinstance(raw, dict) or not raw.get("id") or not raw.get("text"):
            continue
        cat = raw.get("categories") or {}
        locations = cat.get("allLocations") or ([cat["location"]] if cat.get("location") else [])
        parts = [raw.get("descriptionPlain") or html_to_text(raw.get("description") or "")]
        for block in raw.get("lists") or []:
            parts.append(f"{block.get('text') or ''}\n{html_to_text(block.get('content') or '')}")
        parts.append(raw.get("additionalPlain") or "")
        jobs.append(_job("lever", slug, raw["id"], raw["text"], company, ", ".join(locations) or None,
                         _date(raw.get("createdAt")), raw.get("hostedUrl"), "\n\n".join(p for p in parts if p)[:DESCRIPTION_MAX],
                         cat.get("commitment"), raw.get("workplaceType")))
    return jobs


CONNECTORS = {"personio": personio, "greenhouse": greenhouse, "lever": lever}


def fetch_jobs(vendor: str, slug: str, company: str, fetcher) -> list[dict]:
    return CONNECTORS[vendor](slug, company, fetcher)
