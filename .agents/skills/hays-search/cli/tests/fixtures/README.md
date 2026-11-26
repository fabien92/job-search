# Fixtures

Captured from www.hays.at on 2026-11-26 and trimmed to what the parser reads:

- `search-page1.html` — `/en/jobsearch/job-offers/c/Austria/<id>/p/1?q=` (sent with
  Accept-Language: dates "25.11.26"): total set to 22 (two pages), 3 real cards (904003
  Vienna, 903894 Himberg bei Wien, 903199 Tirol); a zero-width space added to 903894's title,
  a `display:none` instruction inside 904003's teaser, one malformed card (no link) appended.
- `search-page2.html` — `…/p/2?q=` (sent without Accept-Language: dates
  "Thu Nov 19 08:59:46 CET 2026"): 2 real cards (902971 Graz, 901080 Wien).
- `detail-903672.html` — `/jobsuche/stellenangebote-jobs-detail-governance-…-903672/1`: the
  JSON-LD, h1, meta items and the five sections, with an HTML comment and a `display:none`
  instruction inserted in the Responsibilities section.
