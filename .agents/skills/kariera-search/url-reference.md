# kariera.zoznam.sk — URL reference

Checked 2026-11-26 (about 12 requests). `www.kariera.sk` redirects to `kariera.zoznam.sk`.
Server-rendered HTML, no JSON-LD; applying goes through `/reaguj-na-ponuku/<id>` (never touched).

## robots.txt (excerpt)

```
User-agent: *
Disallow: /de/  /en/  /cs/  /pl/  /hu/  /ua/  /ro/  /ru/
Disallow: /rss/
Disallow: /export/
Disallow: /cv/
Disallow: /*?q=*
Disallow: /sk/
Disallow: /*?page=offer_reply&offer_id=
Disallow: /redirect.php
Disallow: /job-offers$  /job-offers/  /job-offer/  /company-offers/ …
```

No Crawl-delay. `/pracovne-ponuky/…` (including `?od=`) and `/pracovna-ponuka/…` are allowed
(`tools/robots_check.py`).

## Terms

`/obchodne-podmienky`: services for candidates and employers; the "Databáza" copyright clauses
cover the CV database built from candidates' data. No clause on automated access to listings.

## Listing (search)

`GET https://kariera.zoznam.sk/pracovne-ponuky/<category>/<region>[?od=<offset>]`

| Part | Values |
|------|--------|
| `<category>` | `informatika-sprava-systemov`, `informatika-software`, `telekomunikacie`, `bankovnictvo`, … (links on the home page) |
| `<region>` | `bratislavsky-kraj`, `trnavsky-kraj`, `nitriansky-kraj`, `trenciansky-kraj`, `zilinsky-kraj`, `banskobystricky-kraj`, `presovsky-kraj`, `kosicky-kraj` (also `vsetky/<region>` for every category) |
| `od` | offset, 30 per page: `?od=30` = page 2 |

30 cards per page, newest first. No total count on the page. Pager:
`<ul class="paginator">…<li class="current"><a …>1</a></li><li><a href="…?od=30">2</a></li>…</ul>`;
absent when everything fits on one page.

Card anchors (one `<div class="offer">` each):

| Field | Anchor |
|-------|--------|
| id, url | `h2.offer-title > a[href="pracovna-ponuka/<id>/<slug>"]` (relative) |
| title | text of that link |
| company | `div.offer-employer` (a link to `ponuky-spolocnosti/<slug>`) |
| location | `div.offer-locality` ("Bratislava", "Senec", "Bratislavský kraj") |
| salary | `ul.offer-info > li` ("1800 - 2800 EUR/Mesiac") |
| date | `span.date` (DD.MM.YYYY) |

`<div class="offer highlight">` cards are a sponsored carousel (`div.offer-title`, links through
`redirect.php`, disallowed): not offers of the listing.

## Detail

`GET https://kariera.zoznam.sk/pracovna-ponuka/<id>` → 200 whatever the slug; `<link
rel="canonical">` gives `/pracovna-ponuka/<id>/<slug>`.

Inside `<div class="offer-detail-content">`:

| Field | Anchor |
|-------|--------|
| title | `h1` |
| company | `div.offer-company` |
| place, salary, employment type | `ul.offer-detail-info > li`, label `div.offer-label` ("Miesto práce:", "Ponúkaný plat (základná mzda):", "Druh pracovného pomeru:"), value in `a.category_link` or `div.offer-info` |
| description | `h2`/`h3` + `p` blocks after `ul.offer-detail-info`, up to `ul.offer-detail-buttons` |
| publication date | `div.offer-date`: "Dátum zverejnenia: DD.MM.YYYY" |
| categories | `div.offer-date a.category_link` |
| end date | "Dátum ukončenia ponuky: DD.MM.YYYY" in the text (labour-office offers) |
| source | link to `sluzbyzamestnanosti.gov.sk` = taken over from the Úrady práce |
