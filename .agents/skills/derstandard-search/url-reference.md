# jobs.derstandard.at — URL reference

Reconnaissance: 2026-11-25, User-Agent `Mozilla/5.0 (compatible; derstandard-cli/1.0)` (accepted, HTTP 200).

## robots.txt

```
User-agent: Mediatoolkitbot / ImagesiftBot / SeekportBot / SemrushBot / DataForSeoBot /
            dotbot / Bytespider / Yandexbot / AhrefsBot    Disallow: /
User-agent: *
Disallow: /wp-admin/
Disallow: /jobsuche/c/job/
Disallow: /jobsuche/tracking/
Sitemap: https://jobs.derstandard.at/sitemaps/jobs/{detailpages,locations,terms,location-term-0,...}.xml
```

Terms: https://about.derstandard.at/agb/ — section VI reserves commercial text-and-data mining
(§ 42h Abs 6 UrhG, Art. 4 Abs 3 DSM directive); crawlers must not create user content.

## Search

`GET https://jobs.derstandard.at/suche/<location-slug>/<keywords>`

| Part | Value |
|------|-------|
| `<location-slug>` | `oesterreich` (all), `wien`, `graz`, `linz`, `niederoesterreich`, `st-poelten`… (lowercase, umlauts → ae/oe/ue, ß → ss, other characters → `-`) |
| `<keywords>` | URL-encoded free text; `alle` = no keyword |
| `?page=` | **ignored** by the server (same first page returned) |

Response: HTML (Next.js). Data: `<script>(window[Symbol.for("ApolloSSRDataTransport")] ??= []).push({...})</script>`,
several per page; the object is a JS literal containing bare `undefined`. Path:
`rehydrate.<id>.data.jobListings`:

| Field | Meaning |
|-------|---------|
| `edges[].node.id` | uuid → `/detail/<uuid>` |
| `edges[].node.title` | title |
| `edges[].node.hiringOrganization.name` | company (often a recruitment agency) |
| `edges[].node.jobLocationsRaw[]` | display places, may include `Home-Office` |
| `edges[].node.displayDate` | ISO timestamp |
| `edges[].node.baseSalary` + `salaryInterval` | advertised minimum, `YEARLY`/`MONTHLY` |
| `edges[].node.employmentTypes[]` | `FULL_TIME`, `PART_TIME`… |
| `edges[].node.benefits[]` | e.g. `home_office` |
| `edges[].node.tags[]` | portal keywords |
| `edges[].node.applicationType` | `LINK_OUT` / … (not exposed) |
| `totalEntries` | total hits for the query |
| `pageInfo.hasNextPage` / `endCursor` | cursor pagination, used only by the client-side "Mehr Inserate anzeigen" GraphQL call (not used) |

20 edges per page, relevance order. The `<title>` also states the total ("48 offene Stellen").

Query-syntax test (2026-11-25, `wien`): `delivery manager` 48 · `"delivery manager"` 57 ·
`'delivery manager'` 53 · `"manager delivery"` 77 · `delivery OR manager` 50 → quotes do not narrow,
no OR operator.

## Detail

`GET https://jobs.derstandard.at/detail/<uuid>` (HTML). One `application/ld+json` `JobPosting`:
`title`, `hiringOrganization.name`, `jobLocation[].address.addressLocality`, `datePosted`,
`validThrough` (often null), `employmentType` ("Full-time"), `baseSalary.value.{value,unitText}`,
`jobBenefits` ("Home Office"), `description` (HTML). No structured apply URL (button is client-side;
links inside `description` are posting text).
