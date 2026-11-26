# www.profession.hu — URL reference

Checked 2026-11-26 (about 10 requests). Server-rendered pages; applying goes through
`/jelentkezes/<id>` (disallowed by robots.txt, never touched).

## robots.txt (excerpt)

```
User-agent: *
Disallow: */account/
Disallow: */jelentkezes/
Disallow: */munkaado/
Disallow: */munkavallalo/
Disallow: /en/
Disallow: /impresszum
Disallow: /job/send
Disallow: */allas-ajanlas/
Disallow: *felhasznalasi*feltetelek*.pdf
…
Disallow: *?rss$
```

No Crawl-delay, no Sitemap line. `/allas/` and `/partner/files/` are not disallowed.

## Category feeds (search)

`GET https://www.profession.hu/partner/files/rss-<category>.rss` → 301 →
`https://stat.profession.hu/partner/files/rss-<category>.rss` (RSS 2.0, ~8 KB).

Categories linked from the home page: adminisztracio, bank, egeszsegugy, ertekesites, hr, it, jog,
marketing, mernok, oktatas, szakmunka, szamvitel, ugyfelszolgalat, vendeglatas.

```xml
<item>
<title>SAP rendszerüzemeltető</title>
<link>https://www.profession.hu/allas/sap-rendszeruzemelteto-semmelweis-egyetem-informatikai-foigazgatosag-budapest-3058862/p/569</link>
<description>SAP rendszerüzemeltető,
Hirdető cég: Semmelweis Egyetem Informatikai Főigazgatóság</description>
<category>Jobs</category>
<pubDate>Thu, 26 Nov 2026 09:16:09 +0100</pubDate>
</item>
```

- 20 items, the newest openings of the category for the whole of Hungary.
- `pubDate` = the feed's generation time (identical on every item), not the posting date.
- Link: `/allas/<slug>-<id>[/optimum]/p/569`; `/optimum` marks a premium layout, `/p/569` is the
  feed's partner tag. The canonical URL is `/allas/<slug>-<id>`.
- The slug usually ends with the town before the id (`…-budapest-3058862`,
  `…-szekesfehervar-es-kornyeke-laurel-kft-3055411`); some carry no town at all
  (`…-magyar-posta-zrt-3055291`).

## Posting (detail)

`GET https://www.profession.hu/allas/<id>` → 200 with `<link rel="canonical" href="…/allas/<slug>-<id>">`.

- One `<script type="application/ld+json">` with an `@graph`; its `JobPosting` node has `title`,
  `hiringOrganization.name`, `jobLocation.address` (`addressLocality`, `postalCode`,
  `addressCountry`), `datePosted` (YYYY-MM-DD), `validThrough`, `employmentType`,
  `experienceRequirements`, `educationRequirements`, `workHours`, `occupationalCategory`,
  `jobLocationType` ("TELECOMMUTE" on remote postings, which may have no `jobLocation`) and a
  `description` whose list items are run together (not used when the boxes are present).
- Text: `<div id="box_<section>" class="box-container">` blocks, each an
  `<h2 class="advertisement-content-title"><span class="title">…</span></h2>` and an
  `itemprop` div (`tasks`, `requirements`, `offer`, `c_info`, …). Section titles follow the
  posting's language ("Feladatok", "Main responsibilities, tasks:").

## Terms of use

`https://www.profession.hu/docs/felhasznalasifeltetelek_20201008.pdf` (linked from
`/adatkezeles/`), §V.3: reading, display, saving and printing for personal, non-commercial use;
anything else needs written permission. §VIII.1.d: no application that endangers the service.
