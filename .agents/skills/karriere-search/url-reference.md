# karriere.at — URL reference

Reconnaissance: 2026-11-23, User-Agent `Mozilla/5.0 (compatible; karriere-cli/1.0)` (accepted).

## robots.txt

```
User-agent: BLEXBot   Disallow: /
User-agent: AhrefsBot Disallow: /
User-agent: *         Disallow:        (empty: everything allowed)
```

## Search

`GET https://www.karriere.at/jobs?keywords=<text>&locations=<text>&sort=date&page=<n>`

Headers: `X-Requested-With: XMLHttpRequest`, `Accept: application/json` → JSON
`{ "data": <view model> }`. Without the header the server returns HTML (the same view model
is embedded as `window.VUE_INITIAL_STATE = {...}`) and **ignores `page`**.

The slug form `/jobs/<keyword-slug>/<location-slug>` also works; the query-string form is used
because it needs no slugging.

| Parameter | Meaning |
|---|---|
| `keywords` | free text; quotes ignored, no operators |
| `locations` | city or Bundesland name (`Wien`, `Linz`, `Oberösterreich`) |
| `sort=date` | newest first (default order is relevance) |
| `page` | 1-indexed, 15 items per page (XHR only) |

No posting-age parameter exists (none in the search form's filters: `jobFields`,
`employmentTypes`, `jobLevels`, `salary`, radius). Age is filtered client-side.

### Response paths (`data.` prefix)

| Field | Path |
|---|---|
| total hits | `jobsSearchList.jobsListHeader.count` (string, e.g. `"38"`) |
| more pages | `jobsSearchList.loadMoreJobsButton.active` / `.next` |
| items | `jobsSearchList.activeItems.items[]` — job items have `jobsItem`; others are disruptors |
| id | `jobsItem.id` (string) |
| title | `jobsItem.title` |
| company | `jobsItem.company.name` (`company.isChiffre` = anonymous) |
| location | `jobsItem.locations[].name` |
| date | `jobsItem.date` — relative German text |
| url | `jobsItem.link` = `https://www.karriere.at/jobs/<id>` |
| other | `employmentTypes`, `isHomeOffice`, `salary`, `summary` (AI summary), `pushedJob` |

## Detail

`GET https://www.karriere.at/jobs/<id>` (HTML, ~450 KB).

- `<script type="application/ld+json">` with `@type: JobPosting`: `title`, `description` (HTML),
  `datePosted` (ISO), `validThrough` (when present), `employmentType[]`, `jobLocation[].address`,
  `baseSalary`, `hiringOrganization.name/.sameAs`, `identifier.value` (= id).
- `window.VUE_INITIAL_STATE.jobDetailContent`:
  - `jobHeader.job.{id,title,isInactive}`, `jobHeader.company.name`
  - `keyfactBox.job.{locations,employmentTypes,jobLevel,salaryRange,isHomeOffice,isChiffre}`
  - `jobContent.text` — description HTML (preferred); `jobContent.html` — branded full layout
  - `applyAction.applyButton.applyUrl` — employer's application URL (often with `referrer=karriere_at`)
  - `jobDetail.isInactive`

The XHR variant of the detail URL returns the view model without the JSON-LD block (no exact
`datePosted`), so the CLI fetches the HTML page.
