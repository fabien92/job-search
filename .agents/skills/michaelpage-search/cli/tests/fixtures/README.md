# Fixtures

Captured from www.michaelpage.at on 2026-11-26 and trimmed to what the parser reads:

- `list-it-wien-page1.html` — `/jobs/information-technology/wien-0`: 3 real cards
  (jn-112026-7140475, jn-102026-7135769, jn-052026-7014399) and the "Weitere Jobs anzeigen"
  rel=next pager; a zero-width space added to the first title, a `display:none` instruction inside
  the second teaser, one malformed card (no link) appended.
- `list-it-wien-page2.html` — `…?page=1`: 2 real cards (jn-102026-7125856, jn-082026-7086455), no pager.
- `detail-jn-112026-7140475.html` — `/job-detail/project-service-delivery-manager-wmd/ref/jn-112026-7140475`:
  the canonical link, the JSON-LD JobPosting (raw control characters kept) with an HTML comment and
  a `display:none` paragraph inserted after "Firmenprofil", and the h1.
