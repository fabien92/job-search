# careers.opecfund.org — URL reference

Checked 2026-11-26 (about 10 requests). Platform: SAP SuccessFactors Career Site Builder (same
markup family as careers.unido.org). opecfund.org itself has no robots.txt (404); its careers
page links to `https://careers.opecfund.org/go/VACANCIES/818602/`.

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

`GET https://careers.opecfund.org/search/?q=&locationsearch=` — the whole board (7 openings on
2026-11-26) on one page; the CLI filters client-side.

Per row (`<tr class="data-row">`):

| Field | Anchor |
|-------|--------|
| id, slug, title | `a.jobTitle-link[href="/job/<slug>/<id>/"]` |
| location | `span.jobLocation` ("AT" only) |
| posted | `span.jobDate` ("Nov 26, 2026") |
| total | `span.paginationLabel` "Results 1 – 7 of 7" |

## Detail

`GET https://careers.opecfund.org/job/<any-slug>/<id>/`.

| Field | Anchor |
|-------|--------|
| title | `h1#job-title[itemprop=title]` |
| location | `meta[itemprop=streetAddress]` ("AT") |
| posted / deadline | `meta[itemprop=datePosted]`, `meta[itemprop=validThrough]` ("Sun Dec 06 23:00:00 UTC 2026") |
| description | `span[itemprop=description].jobdescription` (balanced on nested spans) |
| header fields | first table of the description: cell 1 = labels ("Department/Unit:", "Date of Issuance:", "Deadline of Applications:", "Required Languages:", "Contract Type:", "Grade:", "Job Category:", "Recruitment Status:", "Contract Duration:"), cell 2 = values in the same order; paired only if both have the same count |
| canonical | `link[rel=canonical]` |
