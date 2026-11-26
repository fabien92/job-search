# Jobgether — URL reference

Checked 2026-11-26.

## Search (the only endpoint used)

`GET https://jobgether.com/astroapi/ai/jobs.json?<params>` — JSON, `application/json`.
Documentation (JSON): `GET https://jobgether.com/astroapi/ai/jobs/docs`. `/api/v1/jobs` is the
canonical alias (also accepts POST with a JSON body) but robots.txt `Disallow: /*?*` covers it
with a query string; `/astroapi/ai/jobs.json?*` is explicitly allowed. `/astroapi/ai/jobs`
(without `.json`) is deprecated (sunset 2026-09-28).

| Parameter | Values | Notes |
|-----------|--------|-------|
| `keyword` | free text | title, job function, skills, company, contract type, language; all words must match; quotes / order ignored; no OR |
| `locations` | slugs, comma-separated | `austria`, `vienna`, `europe`, `anywhere`… unknown -> 400 `invalid_parameter` |
| `sort` | `relevance` (default), `date` | `date` is strictly newest first |
| `page` | 1–10 | |
| `limit` | 1–25 (default 10) | |
| `contractType` | full-time, part-time, fixed-term, freelance, internships | not used by the CLI |
| `experience` | entry-level-graduate, junior-1-2-years, mid-level-2-5-years, senior-5-10-years, expert-10-years | not used |
| `remoteType` / `includeHybrid` | full-remote, remote-first, hybrid / true | no effect seen for Austria/Vienna |
| `jobReferences`, `industries`, `salaryMin`, `salaryMax`, `currency` | | not used |

Response:

```json
{"jobs":[{"id":"6ad67e28a8fae18ba2cdd2c0","title":"Delivery Manager","company":"WhiteTech",
  "url":"https://jobgether.com/offer/6ad67e28a8fae18ba2cdd2c0-delivery-manager",
  "location":"Europe","remote":"Full Remote","contractType":"Full time",
  "experience":"Senior (5-10 years)","jobFunctions":["Delivery Manager"],
  "salaryRange":"60000-80000 EUR","postedAt":"2026-10-19T20:31:36.785Z"}],
 "pagination":{"page":1,"limit":25,"hasMore":false},
 "browseOnSiteUrl":"https://jobgether.com/search-offers?...","docs":"/astroapi/ai/jobs/docs"}
```

- `salaryRange` only when given. No total, only `hasMore`.
- `id` is 24 hex characters. A republished offer has a new `id` but keeps the original's URL.
- `location` = eligible areas (countries, continents, US states "Delaware (USA)", "Anywhere").
- Headers: `ratelimit-policy: "ai-jobs";q=60;w=60` (60 requests / 60 s), `Retry-After` on 429.
- Errors: RFC 9457 `application/problem+json`
  `{"type","title","status","detail","code":"invalid_parameter","field","allowedValues"}`.

## Detail

None in the API. The offer page `https://jobgether.com/offer/<id>-<slug>` (allowed by
robots.txt) answers **403** to the CLI's honest User-Agent; it carries a JSON-LD `JobPosting`
with the full description, but the terms of use forbid extracting content by automated means,
so the CLI never fetches it. `detail <url>` re-runs the search with the slug's words.

An MCP endpoint (`/mcp`) is announced in the docs; not probed (2026-11-26).

## robots.txt

```
User-agent: *
Content-Signal: search=yes, ai-input=yes, ai-train=no
Allow: /
Allow: /astroapi/ai/jobs.json
Allow: /astroapi/ai/jobs.json?*
Disallow: /*?*
Disallow: /offer/{*}
Disallow: /offer/%7B*%7D
Disallow: /proxy/*?*
Disallow: /cdn-cgi/
Disallow: /_server-islands/
Disallow: /active-offers
```
