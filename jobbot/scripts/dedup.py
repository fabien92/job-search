"""SPEC §4 — deduplication, zero tokens, before Claude reads anything.

Order, cheapest first:
  1. site id key            `<site>:<id>`             (e.g. karriere:10037361)
  2. employer URL, cleaned   tracking params dropped (utm_*, click ids — never `ref`, `src`, `source`,
                             `from`…, which some career sites use as the job reference), no trailing
                             "/", host lowercased, route-like fragments ("#/job/12") kept
  3. company + title + city  normalised (NFKC, casefold, accents folded, gender
                             markers and legal forms removed, punctuation removed,
                             Wien = Vienna = Vienne)
plus the upstream history (job_scraper/seen_jobs.json, via the upstream helpers
rank_state.norm / job_key.make_key, so a job upstream `store` would refuse is
refused here first), the tracker (job_search_tracker.csv) and the current batch.

V4 (§4, §13): republication check — same company and same city, title slightly reworded
("Senior IT Delivery Manager (m/w/d)" -> "IT Delivery Manager – Senior"), compared only with
the same company's postings of the last N days (thresholds in schedule.yaml `republish`).
Two employers are never compared with each other. EN/DE across sites stays with the scorer.

The ledger (jobbot/state/seen_index.json) keeps every job JobBot has seen,
kept or rejected, with the reason. Written under the state lock only.
It is pruned by postprocess.py (Ledger.prune): postings never alerted are dropped after
`seen_retention_days` (schedule.yaml, default 365), circumstantial rejects (too old, region
switched off…) after `circumstantial_retention_days` (default 14).
"""

from __future__ import annotations

import re
import sys
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import common

if str(common.TOOLS) not in sys.path:
    sys.path.insert(0, str(common.TOOLS))

from job_key import make_key  # noqa: E402  (upstream)
from rank_state import norm as upstream_norm  # noqa: E402  (upstream)

# ------------------------------------------------------------------ normalisation

_GENDER_TOKEN = r"(?:m|w|f|d|x|i|v|h|divers|diverse|all|gn|mwd|fmd|wmd|mfd|wmx)"
_GENDER_PAREN = re.compile(
    r"[\(\[]\s*(?:" + _GENDER_TOKEN + r"\s*[/|,*]\s*)+" + _GENDER_TOKEN + r"\s*[\)\]]"
    r"|[\(\[]\s*(?:all\s+genders?|alle\s+geschlechter|gn\*?|m/w/d|any\s+gender)\s*[\)\]]",
    re.IGNORECASE,
)
_GENDER_BARE = re.compile(r"(?<![\w/])(?:[mwfdx]\s*/\s*){2,}[mwfdx](?![\w/])", re.IGNORECASE)
# German gender suffixes: Projektmanager:in, Entwickler*innen, Berater_in, Leiter/-in, LeiterIn
_GENDER_SUFFIX = re.compile(r"(?<=[a-zäöüß])(?:[:*_]|/-?)in(?:nen)?\b|(?<=[a-zäöüß])In(?:nen)?\b")

_LEGAL_FORMS = [
    r"gmbh\s*&\s*co\.?\s*kg", r"gmbh\s*&\s*co\.?\s*og", r"ges\.?\s*m\.?\s*b\.?\s*h\.?", r"gmbh", r"ag", r"se", r"kg", r"og",
    r"e\.\s*u\.?", r"ltd\.?", r"limited", r"inc\.?", r"llc", r"s\.\s*r\.\s*o\.?", r"a\.\s*s\.?", r"kft\.?", r"zrt\.?",
    r"nyrt\.?", r"plc", r"co\.?", r"corp\.?", r"b\.?v\.?", r"s\.?a\.?", r"spol\.?",
]
_LEGAL = re.compile(r"(?<![\w.])(?:" + "|".join(_LEGAL_FORMS) + r")(?![\w])", re.IGNORECASE)
_PUNCT = re.compile(r"[^\w+#]+", re.UNICODE)
_UNDERSCORE = re.compile(r"_+")


def fold_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return folded.replace("ß", "ss").replace("ø", "o").replace("æ", "ae").replace("œ", "oe").replace("ł", "l").replace("đ", "d")


def _base(text) -> str:
    return unicodedata.normalize("NFKC", str(text or ""))


def _finish(text: str) -> str:
    text = fold_accents(text.casefold())
    text = _UNDERSCORE.sub(" ", _PUNCT.sub(" ", text))
    return " ".join(text.split())


def norm_title(title) -> str:
    text = _base(title)
    text = _GENDER_PAREN.sub(" ", text)
    text = _GENDER_BARE.sub(" ", text)
    text = _GENDER_SUFFIX.sub("", text)
    return _finish(text)


def norm_company(company) -> str:
    text = _base(company)
    for _ in range(2):  # "Foo Holding GmbH & Co KG" -> two passes catch stacked forms
        text = _LEGAL.sub(" ", text)
    return _finish(text)


_POSTCODE = re.compile(r"\b(?:[A-Z]{1,2}-)?\d{4,5}\b")


def city_aliases(regions: dict | None = None) -> dict[str, str]:
    """alias (normalised) -> canonical region key, from regions.yaml names."""
    if regions is None:
        regions = common.load_regions()["regions"]
    aliases: dict[str, str] = {}
    for key, region in (regions or {}).items():
        for name in [key, *((region or {}).get("names") or [])]:
            aliases[_finish(_base(name))] = key
    return aliases


def norm_city(location, aliases: dict[str, str] | None = None) -> str:
    """First recognised city of a location string, canonicalised; else the first segment."""
    if aliases is None:
        aliases = city_aliases()
    raw = _POSTCODE.sub(" ", _base(location))
    segments = [s for s in re.split(r"[,;/|·•]| - |\(|\)", raw) if s.strip()]
    for segment in segments:
        normalised = _finish(segment)
        if normalised in aliases:
            return aliases[normalised]
        for word in normalised.split():
            if word in aliases:
                return aliases[word]
    return _finish(segments[0]) if segments else ""


def triple_key(company, title, location, aliases=None) -> str:
    return "|".join((norm_company(company), norm_title(title), norm_city(location, aliases)))


# ------------------------------------------------------------------ URLs

# Tracking parameters only: click ids and campaign/referrer tags. Generic names (ref, src, source, from,
# channel, origin, feed, share…) are NOT stripped: career sites use them as the job reference, and
# stripping them merged distinct postings of one employer into a single employer URL.
_TRACKING = {
    "trk", "trkid", "trackingid", "refid", "rcm", "referrer", "referer", "gclid", "gclsrc", "gbraid", "wbraid",
    "fbclid", "msclkid", "yclid", "dclid", "twclid", "ttclid", "li_fat_id", "mc_cid", "mc_eid", "_hsenc", "_hsmi",
    "igshid", "cmpid", "spm",
}


def clean_url(url) -> str | None:
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower()
    scheme = parts.scheme.lower()
    if parts.port and not ((scheme == "http" and parts.port == 80) or (scheme == "https" and parts.port == 443)):
        host = f"{host}:{parts.port}"
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING
    ]
    path = parts.path.rstrip("/")
    # A fragment that looks like a route ("#/job/12", "#!/offer/7") identifies the posting on
    # single-page career sites; a plain anchor ("#top") does not.
    fragment = parts.fragment.rstrip("/") if "/" in parts.fragment.rstrip("/") else ""
    return urlunsplit((parts.scheme.lower(), host, path, urlencode(query), fragment))


def site_key(site: str, job_id) -> str:
    return f"{site}:{job_id}"


# ------------------------------------------------------------------ ledger

LEDGER_NAME = "seen_index.json"
PRUNABLE_STATUSES = {"rejected", "duplicate", "low"}
# schedule.yaml keys (defaults here; common.SCHEDULE_DEFAULTS need not list them)
RETENTION_DEFAULTS = {"seen_retention_days": 365, "circumstantial_retention_days": 14}


def retention_settings(schedule: dict | None = None) -> tuple[int, int]:
    """-> (seen_retention_days, circumstantial_retention_days) from schedule.yaml, else the defaults."""
    out = []
    for key, default in RETENTION_DEFAULTS.items():
        value = (schedule or {}).get(key)
        try:
            out.append(default if value is None or isinstance(value, bool) else int(value))
        except (TypeError, ValueError):
            out.append(default)
    return out[0], out[1]


class Ledger:
    """jobbot/state/seen_index.json: {version, next_id, jobs: {site:id -> entry}}."""

    def __init__(self, data: dict | None = None, aliases: dict[str, str] | None = None):
        data = data or {}
        self.version = 1
        self.next_id = int(data.get("next_id") or 1)
        self.jobs: dict[str, dict] = dict(data.get("jobs") or {})
        self.aliases = aliases
        self._index()

    @classmethod
    def path(cls) -> Path:
        return common.state_dir() / LEDGER_NAME

    @classmethod
    def load(cls, aliases=None) -> "Ledger":
        return cls(common.read_json(cls.path(), {}) or {}, aliases)

    def save(self) -> None:
        common.atomic_write_json(self.path(), {"version": self.version, "next_id": self.next_id, "jobs": self.jobs})

    def _index(self) -> None:
        self.by_url: dict[str, str] = {}
        self.by_triple: dict[str, str] = {}
        self.by_short: dict[str, str] = {}
        for key, entry in self.jobs.items():
            self._index_one(key, entry)

    def _index_one(self, key: str, entry: dict) -> None:
        for field in ("employer_url", "url"):
            if entry.get(field):
                self.by_url.setdefault(entry[field], key)
        if entry.get("triple"):
            self.by_triple.setdefault(entry["triple"], key)
        if entry.get("short_id"):
            self.by_short[str(entry["short_id"])] = key

    def allocate_id(self) -> str:
        value = self.next_id
        self.next_id += 1
        return str(value)

    def add(self, key: str, entry: dict) -> None:
        self.jobs[key] = entry
        self._index_one(key, entry)

    def prune(self, retention_days: int, circumstantial_days: int) -> int:
        """Drop old entries so the ledger does not grow without bound. -> number removed.

        Only postings the user never acted on are removed (status rejected / duplicate / low); alerted
        postings and anything the bot wrote stay, so an old #ID keeps working. Circumstantial rejects
        (too old, region switched off…) say nothing about the content and expire sooner. An entry without
        a readable first_seen is kept. 0 or less disables the corresponding window."""
        now = common.now().timestamp()
        drop = []
        for key, entry in self.jobs.items():
            if entry.get("status") not in PRUNABLE_STATUSES:
                continue
            seen = common.parse_iso(entry.get("first_seen"))
            if not seen:
                continue
            days = circumstantial_days if entry.get("reason") in _CIRCUMSTANTIAL else retention_days
            if days > 0 and now - seen.timestamp() > days * 86400:
                drop.append(key)
        for key in drop:
            del self.jobs[key]
        if drop:
            self._index()
        return len(drop)

    def find_short(self, short_id) -> tuple[str, dict] | None:
        key = self.by_short.get(str(short_id).lstrip("#"))
        return (key, self.jobs[key]) if key else None


# ------------------------------------------------------------------ upstream history

class Upstream:
    """Read-only view of job_scraper/seen_jobs.json and the tracker, using upstream normalisation."""

    def __init__(self, seen: dict | None = None, tracker_pairs: set | None = None):
        self.seen = seen or {}
        self.tracker = tracker_pairs or set()
        self.urls: set[str] = set()
        self.pairs: set[tuple[str, str]] = set()
        self.ignored_keys: set[str] = set()
        for key, entry in self.seen.items():
            if not isinstance(entry, dict):
                continue
            # A posting JobBot rejected only for circumstances (region switched off, too old…) was never
            # shown: it must not hide the same title elsewhere or later. The ledger alone decides for it.
            if entry.get("jobbot_reason") in _CIRCUMSTANTIAL:
                self.ignored_keys.add(key)
                continue
            if isinstance(entry.get("url"), str):
                self.urls.add(entry["url"].rstrip("/"))
            self.pairs.add((upstream_norm(entry.get("company")), upstream_norm(entry.get("title"))))

    @classmethod
    def load(cls) -> "Upstream":
        import csv
        import json

        seen = {}
        path = common.upstream_seen_path()
        if path.is_file():
            doc = json.loads(path.read_text(encoding="utf-8"))
            seen = doc.get("seen", doc) if isinstance(doc, dict) else {}
        pairs = set()
        tracker = common.tracker_path()
        if tracker.is_file():
            with tracker.open(encoding="utf-8-sig", newline="") as fh:
                for row in csv.DictReader(fh):
                    company = upstream_norm(row.get("company"))
                    if company:
                        pairs.add((company, upstream_norm(row.get("role"))))
        return cls(seen if isinstance(seen, dict) else {}, pairs)

    def check(self, job: dict) -> str | None:
        url = (job.get("url") or "").rstrip("/")
        pair = (upstream_norm(job.get("company")), upstream_norm(job.get("title")))
        if pair in self.tracker:
            return "already_applied"
        if url and url in self.urls:
            return "dup_upstream"
        if pair in self.pairs and pair[0]:
            return "dup_upstream"
        if not pair[0]:
            # No company (staffing agencies, some LinkedIn cards): the upstream key would be
            # "unknown-company_<title>", i.e. a title-only match that merges different employers.
            return None
        try:
            key = make_key(job.get("company"), job.get("title") or "", job.get("url") or "")
            if key in self.seen and key not in self.ignored_keys:
                return "dup_upstream"
        except Exception:  # noqa: BLE001 - make_key must never break a run
            pass
        return None


# ------------------------------------------------------------------ the check

class Batch:
    """Identities already accepted in the current run."""

    def __init__(self):
        self.keys: set[str] = set()
        self.urls: set[str] = set()
        self.triples: set[str] = set()
        self.jobs: list[dict] = []  # V4: same-run republication check

    def add(self, job: dict) -> None:
        self.keys.add(job["key"])
        if job.get("url_clean"):
            self.urls.add(job["url_clean"])
        if job.get("employer_url"):
            self.urls.add(job["employer_url"])
        if job.get("triple"):
            self.triples.add(job["triple"])
        self.jobs.append({k: job.get(k) for k in ("key", "triple", "title", "site")})


def annotate(job: dict, aliases=None) -> dict:
    """Add key / url_clean / triple (and employer_url if apply_url is known) to a job dict."""
    job["key"] = site_key(job["site"], job["id"])
    job["url_clean"] = clean_url(job.get("url"))
    if job.get("apply_url"):
        job["employer_url"] = clean_url(job["apply_url"])
    job["triple"] = triple_key(job.get("company"), job.get("title"), job.get("location"), aliases)
    return job


def check_search_hit(job: dict, ledger: Ledger, upstream: Upstream, batch: Batch, revivable=None) -> str | None:
    """Stage A (search results, before any detail fetch): site id, triple, upstream, batch.

    revivable(entry) -> bool (optional): a ledger entry for which it returns True no longer hides the
    posting (prefilter: rejected for a region that has been switched on since)."""
    def hides(key) -> bool:
        entry = ledger.jobs.get(key)
        return entry is not None and not (revivable and revivable(entry))

    if hides(job["key"]):
        return "dup_site_id"
    if job.get("url_clean") and hides(ledger.by_url.get(job["url_clean"])):
        return "dup_url"
    if job["triple"].split("|")[0] and hides(ledger.by_triple.get(job["triple"])):
        return "dup_company_title_location"
    reason = upstream.check(job)
    if reason:
        return reason
    if job["key"] in batch.keys or (job.get("url_clean") and job["url_clean"] in batch.urls):
        return "dup_in_run"
    if job["triple"] in batch.triples and job["triple"].split("|")[0]:
        return "dup_in_run"
    return None


def check_employer_url(job: dict, ledger: Ledger, batch: Batch) -> str | None:
    """Stage B (after the detail fetch, before Claude): the cleaned employer URL."""
    url = job.get("employer_url")
    if not url:
        return None
    if url in ledger.by_url:
        return "dup_employer_url"
    if url in batch.urls:
        return "dup_in_run"
    return None


def same_company_recent(ledger: Ledger, company, days: int = 30, limit: int = 15) -> list[dict]:
    """Jobs from the same (normalised) company seen within `days`: §4 residual EN/DE check, for the scorer."""
    target = norm_company(company)
    if not target:
        return []
    cutoff = common.now().timestamp() - days * 86400
    out = []
    for entry in ledger.jobs.values():
        if entry.get("triple", "").split("|")[0] != target:
            continue
        seen = common.parse_iso(entry.get("first_seen"))
        if seen and seen.timestamp() >= cutoff:
            out.append({k: entry.get(k) for k in ("short_id", "site", "title", "location", "first_seen", "status")})
    out.sort(key=lambda e: e.get("first_seen") or "", reverse=True)
    return out[:limit]


# ------------------------------------------------------------------ V4: republications

REPUBLISH_DEFAULTS = {"enabled": True, "window_days": 30, "min_common_words": 2, "min_overlap": 0.8,
                      "min_similarity": 0.75}
# Small words that carry no identity ("Manager for IT" = "IT Manager").
_STOPWORDS = {
    "and", "or", "the", "a", "an", "of", "for", "in", "at", "to", "with", "on",
    "und", "oder", "der", "die", "das", "den", "dem", "des", "fur", "im", "in", "am", "zum", "zur", "mit", "bei", "von",
    "et", "de", "du", "des", "la", "le", "les", "en", "pour",
}
# Seniority markers: two titles with different markers on both sides are two jobs (Junior / Senior).
_LEVELS = {
    "junior": "junior", "jr": "junior", "einsteiger": "junior", "graduate": "junior", "entry": "junior",
    "senior": "senior", "sr": "senior", "erfahren": "senior", "experienced": "senior",
    "lead": "lead", "leitend": "lead", "principal": "principal", "staff": "staff", "chief": "chief",
    "i": "l1", "ii": "l2", "iii": "l3", "iv": "l4",
}
# An original rejected only for circumstances (age, region switched off at the time) was never seen
# by the user and says nothing about the content: a fresh copy of it must not be hidden.
_CIRCUMSTANTIAL = {"too_old", "expired", "location_outside_regions", "remote_region", "location"}


def republish_settings(schedule: dict | None = None) -> dict:
    cfg = dict(REPUBLISH_DEFAULTS)
    cfg.update((schedule or {}).get("republish") or {})
    return cfg


def title_words(title_normalised: str) -> list[str]:
    return [w for w in title_normalised.split() if w not in _STOPWORDS]


def _levels(words) -> set[str]:
    return {_LEVELS[w] for w in words if w in _LEVELS}


def title_similarity(a: str, b: str) -> tuple[int, float, float]:
    """(words in common, overlap = common / shorter title, similarity of the word-sorted titles 0..1).
    Inputs are norm_title() outputs. Word order does not count: "senior it delivery manager" =
    "it delivery manager senior"."""
    wa, wb = set(title_words(a)), set(title_words(b))
    if not wa or not wb:
        return 0, 0.0, 0.0
    common_words = len(wa & wb)
    overlap = common_words / min(len(wa), len(wb))
    ratio = SequenceMatcher(None, " ".join(sorted(wa)), " ".join(sorted(wb))).ratio()
    return common_words, overlap, ratio


_BRACKETED = re.compile(r"\([^)]*\)|\[[^\]]*\]")
_TITLE_SEPARATOR = re.compile(r"\s[–—|/-]\s|,\s")


def core_words(raw_title) -> set[str]:
    """Words of the main part of a raw title: brackets and whatever follows a separator (" – ", " | ",
    ", ") left out. "Senior IT Delivery Manager (Cloud) – Vienna" -> {senior, it, delivery, manager}."""
    text = _BRACKETED.sub(" ", _base(raw_title))
    text = _TITLE_SEPARATOR.split(text, maxsplit=1)[0]
    return set(title_words(norm_title(text)))


def adds_qualifier(a: str, b: str, raw_a=None, raw_b=None) -> bool:
    """True when one title is the other plus a qualifying word written in its main part:
    "Solution Architect" / "Solution Architect SAP" are two jobs. A seniority marker is not a
    qualifier, nor is an addition in brackets or after a separator ("(Cloud)", "– Agile"): those
    stay rewordings. Without the raw title of the longer one, every extra word counts."""
    wa, wb = set(title_words(a)), set(title_words(b))
    if wa == wb or not (wa < wb or wb < wa):
        return False
    longer, shorter, raw = (wb, wa, raw_b) if wa < wb else (wa, wb, raw_a)
    extra = {w for w in longer - shorter if w not in _LEVELS}
    if not extra:
        return False
    return bool(extra & core_words(raw)) if raw else True


def is_reworded(a: str, b: str, cfg: dict, raw_a=None, raw_b=None) -> bool:
    """True when two normalised titles of the same employer and city are the same job reworded.
    raw_a / raw_b: the titles as published (optional), used by adds_qualifier()."""
    if not a or not b:
        return False
    if a == b:
        return True
    la, lb = _levels(title_words(a)), _levels(title_words(b))
    if la and lb and la != lb:
        return False
    if adds_qualifier(a, b, raw_a, raw_b):
        return False
    common_words, overlap, ratio = title_similarity(a, b)
    return (common_words >= int(cfg["min_common_words"]) and overlap >= float(cfg["min_overlap"])
            and ratio >= float(cfg["min_similarity"]))


def check_republished(job: dict, ledger: Ledger, batch: Batch | None = None, cfg: dict | None = None) -> dict | None:
    """Stage A bis, after check_search_hit: the job (annotated) is a republication of a posting of the
    same company and city seen within window_days (ledger) or earlier in this run (batch).
    Returns {"key", "short_id", "title"} of the original, else None. Zero tokens, no network."""
    cfg = cfg or republish_settings()
    if not cfg.get("enabled", True):
        return None
    parts = (job.get("triple") or "").split("|")
    if len(parts) != 3 or not parts[0]:
        return None  # no company: never compared (two employers are never confused)
    company, title, city = parts
    cutoff = common.now().timestamp() - int(cfg["window_days"]) * 86400
    best = None
    for key, entry in ledger.jobs.items():
        other = (entry.get("triple") or "").split("|")
        if len(other) != 3 or other[0] != company or other[2] != city or key == job.get("key"):
            continue
        if entry.get("reason") in _CIRCUMSTANTIAL:
            continue
        seen = common.parse_iso(entry.get("first_seen"))
        if not seen or seen.timestamp() < cutoff:
            continue
        if is_reworded(title, other[1], cfg, job.get("title"), entry.get("title")):
            original = entry.get("republished_of") or {"key": key, "short_id": entry.get("short_id"),
                                                       "title": entry.get("title")}
            if best is None or (entry.get("first_seen") or "") < best[0]:
                best = (entry.get("first_seen") or "", original)
    if best:
        return best[1]
    for other_job in (batch.jobs if batch else []):
        other = (other_job.get("triple") or "").split("|")
        if len(other) == 3 and other[0] == company and other[2] == city and other_job.get("key") != job.get("key") \
                and is_reworded(title, other[1], cfg, job.get("title"), other_job.get("title")):
            return {"key": other_job.get("key"), "short_id": None, "title": other_job.get("title")}
    return None
