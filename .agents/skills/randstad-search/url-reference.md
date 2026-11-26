# www.randstad.at — URL reference

Checked 2026-11-26 (about 25 requests). Platform: Drupal (theme "bluex"), results rendered
server-side. Applying goes through `/jobs/bewerben/<id>` (disallowed by robots.txt, never touched).

## robots.txt

```
User-agent: *
Allow: /
Disallow: /*/km-
Disallow: /*/postcode-
Disallow: /*/sa-
Disallow: /*/qt-
Disallow: /*search=
Disallow: /*search-app/demo/jobs/
Disallow: /*jobs/mvp/
Disallow: /jobs/*,*/
Disallow: /*/sd-
Disallow: /*/sh-
Disallow: /*/sm-
Disallow: /*/?id=*
Disallow: /*/mpage-
Disallow: /*/apply/
Disallow: /*/bewerben/
…
Disallow: /node/
Sitemap: https://www.randstad.at/sitemaps/sitemap.xml
```

No Crawl-delay. Terms of use (`/nutzungsbestimmungen/`): §2 anyone may use the site and job
board free of charge; §5 the user must be a genuine job seeker and use the site for no other
purpose; no clause on robots, scraping or automated access.

## Sitemaps (not used by the CLI, useful to check coverage)

- `/sitemaps/jobs/sitemap-jobdetails.xml`: every posting URL (522 on 2026-11-26) with lastmod.
- `/sitemaps/jobs/sitemap-joblistings-<specialism>.xml`: listing pages per specialism and place
  (`/jobs/s-edv-it/`, `/jobs/s-edv-it/oberosterreich/linz/`).

## Listings

`GET https://www.randstad.at/jobs/<state>/<city>/` and `…/page-<n>/` for n ≥ 2.

| Place | Path |
|-------|------|
| Vienna | `/jobs/wien/wien/` (`/jobs/wien/` → 301 here) |
| Graz | `/jobs/steiermark/graz/` |
| Linz | `/jobs/oberosterreich/linz/` |
| Salzburg | `/jobs/salzburg/salzburg/` |
| Austria | `/jobs/` |

One Berufsfeld (checked 2026-11-26): `/jobs/s-<slug>/<state>/<city>/` (IT in Vienna:
`/jobs/s-edv-it/wien/wien/`, 2 openings), `/jobs/s-<slug>/` for Austria. Slugs: those of the
`sitemap-joblistings-<slug>.xml` files (`edv-it`, `technik-ingenieurwesen`, `sachbearbeitung`, …).
No robots.txt rule matches `/jobs/s-…/` (the `sa-`, `sd-`, `sh-`, `sm-` rules are other filters).
The heading reads `<h1 class="sortbar__count">2 EDV &amp; IT Jobs in Wien, Wien für Sie gefunden`;
an empty listing (`/jobs/s-edv-it/steiermark/graz/` that day) answers 200 with neither heading nor
cards ("keine Jobs gefunden"). The sitemap lists a Berufsfeld's city pages only part of the time
(on 2026-11-26 at 12:40 `sitemap-joblistings-edv-it.xml` named `/jobs/s-edv-it/`, Oberösterreich
and Linz, not Vienna), but the page itself is public and allowed. Further filters inside a
Berufsfeld (`…/wien/wien/festanstellung/`) are not used.

- 30 cards per page, **not in date order** (page 1 mixes October and November).
- A page past the end answers 200 with no cards: stop at `n * 30 >= total`.
- Total: `<h1 class="sortbar__count">39 Jobs gefunden in Wien, Wien</h1>`.
- Card: `<li class="cards__item bg-variant-white" data-rs-card="true">`, then
  `<a href="/jobs/<slug>_<city>_<id>/" … class="cards__link">Title<span …></span></a>`;
  `ul.cards__meta > li.cards__meta-item`, each starting with an icon whose `svg aria-label` says
  what it is: "Ort der Rolle" (place, "Wien, Wien"), "Art der Tätigkeit der Rolle"
  ("Festanstellung", "Zeitarbeit"), "Gehaltsangabe der Rolle" ("€4,500 pro monat");
  `div.cards__description` (teaser, ~400 chars, repeated in `div.cards__backside-description`);
  `span.cards__date` "veröffentlicht am 8. Oktober 2026".
- Slugs may contain `|` (`sachbearbeiter-mwd-schadenabwicklung-|-transportversicherung_wien_…`).

## Detail

`GET https://www.randstad.at/jobs/job_wien_<id>/` → 301 → `/jobs/<slug>_<city>_<id>/`
(the city in the requested path does not matter: a Linz posting redirects the same way).
`/jobs/<id>/` and `/jobs/_<id>/` answer 200 with a generic page: not used. A closed or unknown
id answers **410**.

- `h1.content-block__title` "Senior Project Manager mit Fokus Implementierung (m/w/d)." (trailing dot).
- `li.behat-calendar` "veröffentlicht am 6. November 2026", `li.behat-expirationDate` "gültig bis 4. Jänner 2027".
- Summary box: `li.behat-location`, `li.behat-salary`, `li.behat-jobType`, `li.behat-hours`,
  `li.behat-specialism` (Berufsfeld), `li.behat-referenceNumber`.
- Text: `div.body-copy.hidden--from-l > div.content` (mobile copy; the desktop copy
  `div.body-copy.hidden--until-l` is identical), ending at `span.read-more-dots`.
- No JSON-LD JobPosting.
