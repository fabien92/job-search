# www.hays.at — URL reference

Checked 2026-11-26 (about 30 requests, 10 s apart). Platform: Liferay portal, results rendered
server-side (jQuery front end). Applying goes through the posting page, never touched.

## robots.txt

```
User-agent: *
Disallow: /web/
Disallow: /tinyurl/
Disallow: /c/portal/login
Disallow: /personaldienstleistung/kontakt-formular-vakanz-melden?*
Disallow: /*?doAsUserId=
Disallow: /login/
…
User-agent: *
Crawl-delay: 10
```

Terms of use (`/en/terms-of-use`): no clause on robots or automated access.

## Search

`GET https://www.hays.at/en/jobsearch/job-offers/c/Austria/8BB21453-D8A8-11D3-AFB2-00105AB00B48/p/<n>?q=<keywords>`

- `8BB21453-…-00105AB00B48` is the Austria value of the country facet
  (`$('#countryFilter').val('…')`). Others seen: Germany `D1641BCE-D56C-11D3-AFB2-00105AB00B48`,
  Switzerland `D1641BCF-…`, Denmark `6DC89AC7-D882-…`, Great Britain `6DC89B6B-D882-…`.
- `p/<n>` is 1-indexed, 20 per page; `/p/<n>/` (trailing slash) answers 301 to `/p/<n>`.
- `q` = keywords (form field `what`, maxlength 100). The city field (`r` + `cityID`
  geocoded by an AJAX call) is not used: filtering is client-side.
- Plain `?q=…&country=<id>` gives the same list (the site rewrites it to the path form).
- Order: roughly newest first without a keyword, not strictly (page 1 mixed 2026-11-25 with
  2025-06-17); `_score` with a keyword (`sortOrder` hidden field).

Totals seen: Austria 72 (4 pages); "project manager" worldwide 132, Austria 5.

Per card (`<div class="search__result border-radius-10">`, split on that marker):

| Field | Anchor |
|-------|--------|
| id, URL | `a.search__result__link[href="https://www.hays.at/jobsuche/stellenangebote-jobs-detail-<slug>-<num>/<n>"]` |
| reference | `.search__result__prospectnumber` (d-none) "Reference number: 903672/1" (not read) |
| title | `h4.search__result__header__title` (with `span.jospositiononly` "(m/f/d)") |
| contract type | `.search__result__job__attribute__type .info-text` |
| location | `.search__result__job__attribute__location .info-text` |
| teaser | `.search__result__teaser .h-text` (first section, usually tasks) |
| date | text "Online since: 25.11.26" (or "Tue Nov 24 15:11:24 CET 2026" without Accept-Language) |
| total | `span#totalJobs` "Show 72 results" (absent when nothing matches) |

## Detail

`GET https://www.hays.at/jobsuche/stellenangebote-jobs-detail?prospectNr=<num>/<n>` (the slug
form `/jobsuche/stellenangebote-jobs-detail-<slug>-<num>/<n>` works too, any slug). Unknown or
closed → 302 to `/jobsuche/stelle-nicht-verfuegbar` ("Jobangebot nicht verfügbar").

| Field | Anchor |
|-------|--------|
| title | `h1.h-arrow-header-content-template__headline--job-detail` |
| contract type, location, start | three `div.info-text.h-job-detail__meta-item.h-job-detail__location` ("Start date: asap") |
| JSON-LD | `script[type="application/ld+json"]` JobPosting: `datePosted`, `employmentType` (array), `industry`, `identifier.value` "903672/1", `validThrough` (placeholder: +2 years, ignored); its text fields run list items together without separators: not used |
| sections | `div.h-job-detail__listing-header` → `h3.h-job-detail__listing-title` + `div.h-job-detail__listing-body.h-text` |

Section titles seen: About the company, Responsibilities, Profile, Benefits, Salary
information (English postings); Aufgaben, Profil, Benefits (German postings). Hidden inputs
`#job_specialism`, `#job_industry` duplicate the JSON-LD.
