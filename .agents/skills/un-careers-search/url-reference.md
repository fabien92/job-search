# UN Careers — URL and API reference

Checked 2026-11-25 (reconnaissance through ~11 requests; endpoints read from the site's
Angular bundle `main-*.js`).

## Access

- `https://careers.un.org/robots.txt` returns the app shell (HTML), not a robots file:
  nothing disallowed.
- No login for search or detail. Applying happens on `inspira.un.org`.
- UN terms of use (`un.org/en/about-us/terms-of-use`): not readable by automated fetch (403).

## Endpoints

| Use | Method | URL |
|-----|--------|-----|
| Search | POST | `https://careers.un.org/api/public/opening/jo/list/filteredV2/en` |
| Detail | GET | `https://careers.un.org/api/public/opening/joV2/<jobId>/en` |
| Filter values | GET | `https://careers.un.org/api/public/opening/jo-filter/list/v2/en` |
| **Never** | PUT | `/api/public/opening/jo/<jobId>/<lang>` — increments the view counter |

Public posting page (for humans): `https://careers.un.org/jobSearchDescription/<jobId>?language=en`.

## Search body

```json
{"filterConfig": {"keyword": "information technology", "ds": ["VIENNA"], "span": ["7"]},
 "pagination": {"page": 0, "itemPerPage": 100, "sortBy": "startDate", "sortDirection": -1}}
```

| Key | Meaning | Values |
|-----|---------|--------|
| `keyword` | phrase match | plain text; quotes/OR literal |
| `ds` | duty station | codes from the `jl` ("Job Locations") filter list, e.g. `VIENNA`, `BUDAPEST` (not the 4-digit Inspira code `0300`, which is ignored) |
| `span` | date posted | `"1"`, `"7"`, `"30"` |
| others | `aoe`, `aoi`, `el`, `ct`, `jn`, `jf`, `jc`, `jle`, `dept`, `recrtype` | see the filter list |

Response: `{status: 1, message: "Success.", data: {list: [...], count: <total>}}`.

## Item fields

| Field | Path |
|-------|------|
| id | `jobId` (number) |
| title | `postingTitle` (fallback `jobTitle`) |
| entity | `dept.name` |
| duty station | `dutyStation[].description` (upper case, e.g. `NEW YORK`) |
| posted | `startDate` (ISO, NY midnight in UTC) |
| deadline | `endDate` |
| grade | `jl.name` (`P-3`, `G-5`, `CON`, `I-1`) |
| category | `jc.name` |
| recruitment type | `recrttype.name` |
| job family | `jf.Name` |
| description | `jobDescription` (HTML: `div.jobPostingItem` > `jobPostingItemTitle` / `jobPostingItemContent`) |
| apply link | `inspiraURL` (detail only) |

## Query-syntax test (2026-11-25, totals reported by `data.count`)

| Query | Total |
|-------|-------|
| (none) | 456 |
| `information technology` | 14 |
| `zzqxvplk` | 0 |
| `project manager` | 1 |
| `"project manager"` | 0 |
| `"manager project"` | 0 |
| `project OR manager` | 0 |
