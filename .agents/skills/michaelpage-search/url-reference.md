# www.michaelpage.at — URL reference

Checked 2026-11-26 (about 12 requests). Platform: Drupal (theme `mp_theme`), results rendered
server-side. Applying goes through `/job-apply/…` (disallowed by robots.txt, never touched).

## robots.txt (extract)

```
User-agent: *
Disallow: /search/
Disallow: /*/search/
Disallow: /job-apply/
Disallow: /*/job-apply/
Disallow: /*?*salary_range*=
Disallow: /*?*contract=temp
Disallow: /*?*contract=permanent
Disallow: /*?*brand=MP
Disallow: /*?*item_per_pages
Disallow: */nojs/*
Disallow: */standalone/*
Allow: */browse/jobs/*/*/*/
Disallow: */jobs/*/*/*/
…
User-Agent: bingbot
Crawl-delay: 1
```

No Crawl-delay for `*`. Terms (`/allgemeine-geschäftsbedingungen`, linked from `/impressum-at`),
"Geistiges Eigentum": view on screen, store on a hard disk (not on a server or networked storage)
or print one copy for personal, non-commercial use; no reproduction, modification, copying or
distribution without written consent. Nothing on robots, scraping or automated access.

## Sitemap

`/sitemap.xml` → `/sitemap.xml?lang=de` (151 URLs: 112 job listings, 37 advice pages). IT listings:
`/jobs/information-technology`, `…/wien-0`, `…/österreich`, `…/industry-business-services`,
`…/industry-insurance`, `…/technology-telecoms`. Postings are not in the sitemap.

## Listing

`GET https://www.michaelpage.at/jobs/information-technology/wien-0` and `…?page=<n>` for n ≥ 1
(Drupal, 0-indexed). Austria: `/jobs/information-technology/%C3%B6sterreich`.

- 30 cards per page, relevance order (refs from 11/2025 to 11/2026 mixed). 43 in Vienna (30 + 13).
- No total on the page; the pager is a "show more" link: `<a href="…?page=1" title="Mehr anzeigen"
  rel="next">Weitere Jobs anzeigen</a>`, absent on the last page.
- Sort options exist (`sort_by=most_recent`, not disallowed) but are not used.
- Card: `<li class="views-row"><div about="/job-detail/<slug>/ref/<ref>" class="job-tile search-job-tile">`,
  then `div.job-title > h3 > a[href]` (title), `div.job-location` ("Wien"),
  `div.job-contract-type` ("Festanstellung"), `div.job-salary` ("63.000€ - 85.000€ p.a.", missing
  on some), `div.job-nature` ("Home Office", optional), `div.job_advert__job-summary-text` (teaser),
  `div.job_advert__job-desc-bullet-points` (2–3 bullets), and "Job speichern"/"Jobs ansehen" links.
- No date on the card. The ref `jn-MMYYYY-NNNNNNN` is the creation month (see detail).

## Detail

`GET https://www.michaelpage.at/job-detail/<slug>/ref/<ref>`; a wrong slug or a closed opening
answers **404** (canonical `/404-page-not-found`).

- `h1.job-apply-job-title > span` title.
- `<script type="application/ld+json">` JobPosting with raw control characters inside strings
  (strict JSON parsers reject it; the CLI turns them into spaces): `title`, `datePosted`
  ("2026-11-04"), `employmentType` ("FULL_TIME"), `industry`, `baseSalary.value.{minValue,maxValue,unitText}`,
  `jobLocation.address.{addressLocality,addressRegion,addressCountry}`, `jobLocationType`
  ("TELECOMMUTE"), `applicantLocationRequirements`, `hiringOrganization` (always Michael Page),
  `description` (the full posting HTML, ~4,400 chars, same text as the page).
- `datePosted` may be later than the ref month: `jn-052026-7014399` showed 2026-07-17.
