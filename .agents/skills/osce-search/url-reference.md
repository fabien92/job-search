# vacancies.osce.org — URL reference

Checked 2026-11-25 (about 15 requests). Platform: "Social Sourcing" job board (jQuery front
end); applications go to talent.osce.org (Taleo), never touched.

## robots.txt

```
User-agent: *
Disallow:
Sitemap:https://vacancies.osce.org/sitemap-seo
```

TLS: curl on macOS fails with "unable to get local issuer certificate"; Bun's fetch verifies
the chain fine. Never disable verification.

## Search

`GET https://vacancies.osce.org/jobs/search/` → 302 to a fresh saved search
`/jobs/search/<jsid>` (page 1). Next pages: `GET /jobs/search/<jsid>/page<n>` (from
`job_list.js`: `'/jobs/search/' + job_search_id + '/page' + page`). 10 rows per page.

Keyword and facet filters are applied by AJAX calls that change the saved search
(`/ajax/jobs/<jsid>/add/location/<id>`…): not used, filtering is client-side.

Per row (`<div id="job_list_<id>" class="job_list_row …">`, up to `<!-- jlr_content -->`):

| Field | Anchor |
|-------|--------|
| id, slug, title | `a.job_link[href="https://vacancies.osce.org/jobs/<slug>-<id>"]` |
| location | `span.location` ("SEC - OSCE Secretariat, Vienna") |
| category | `span.category` (often empty) |
| snippet | `p.jlr_description` |
| total | `span.total_results` |
| current page | `#jPaginateCurrPage` |

Totals seen: all 43 (5 pages); location facet "SEC - OSCE Secretariat, Vienna (13)", plus
the Representative on Freedom of the Media in Vienna (14 Vienna rows in all).

## Detail

`GET https://vacancies.osce.org/jobs/<id>` (slug optional; unknown id → 404 "Invalid Request").

| Field | Anchor |
|-------|--------|
| title | `h1.title` |
| location | `h4.primary_location` (minus `span.loc_icon`) |
| description | `div.job_description`, up to `<!-- TEC-19749` / `div#jJobInsideInfo` |
| canonical | `link[rel=canonical]` |
| labelled fields | `div#jJobInsideInfo` (**display:none**) `<li><label id="…">Name: value</label></li>` |

Labels read (whitelist, each value checked against a strict pattern): Issued by, Requisition
ID, Contract Type, Grade, Job Level, Job Type, Location, Issue Date / Closing Date
("Dec 9, 2026"), Employee Status, Schedule. Others seen and ignored: Number of posts,
Education Level, Job Field, Target Start Date.

Salary: sentence "Monthly remuneration … is around EUR 4,160 …" in the description
(contracted posts; seconded posts have none).
