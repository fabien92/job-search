# careers.unido.org — URL reference

Checked 2026-11-25 (about 15 requests). Platform: SAP SuccessFactors Career Site Builder.

## robots.txt

```
User-agent: *
Disallow: /applybutton/
Disallow: /talentcommunity/
Disallow: /mobile/talentcommunity/
Disallow: /emailsubscribe/
Disallow: /email/image/
Disallow: /services/
Disallow: /preapply/
Disallow: /error
Disallow: /unsubscribe/
Disallow: /reset/
```

## Search

`GET https://careers.unido.org/search/?q=<keywords>&locationsearch=<location>`

| Param | Notes |
|-------|-------|
| `q` | loose; no match → every opening |
| `locationsearch` | free text (`Vienna`); no match → every opening |
| `startrow` | not useful: whole board (20) on one page |

Per row (`<tr class="data-row">`):

| Field | Anchor |
|-------|--------|
| id, slug, title | `span.jobTitle.hidden-phone > a[href="/job/<slug>/<id>/"]` |
| location | `td.colLocation span.jobLocation` ("Vienna, Austria") |
| category | `span.jobDepartment` |
| grade | `span.jobFacility` |
| deadline | `span.jobShifttype` ("30-Nov-2026") |
| total | `span.paginationLabel` "Results 1 – 12 of 12" |

Totals seen: all 20, Vienna 12, `zzqxvplk` 20, `project manager` 20, `"project manager"` 12,
`"manager project"` 20, `project OR manager` 20.

## Detail

`GET https://careers.unido.org/job/<any-slug>/<id>/` (`/job/<id>/` → 302 to `/errorpage/`).

| Field | Anchor |
|-------|--------|
| title | `span[itemprop=title]` |
| location | `meta[itemprop=streetAddress]` |
| posted / deadline | `meta[itemprop=datePosted]`, `meta[itemprop=validThrough]` ("Mon Nov 09 00:00:00 UTC 2026") |
| description | `span.jobdescription` (balanced on nested spans) |
| grade, category, employment type, salary | lines at the top of the description ("Grade:", "Category:", "Employment Type:", "Indicative Minimum Net Annual Salary:") |
| canonical | `link[rel=canonical]` |
