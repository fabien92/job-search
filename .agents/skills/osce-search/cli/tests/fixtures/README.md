# Fixtures

Captured from vacancies.osce.org on 2026-11-25 and trimmed to what the parser reads:

- `search-page1.html` — `/jobs/search/<jsid>`: total set to 12 (two pages), 3 real rows
  (5157 Dushanbe, 5150 Chisinau, 5169 Vienna); a zero-width space added to row 5150's title,
  a `display:none` instruction inside row 5169's category, one malformed row (no link) appended.
- `search-page2.html` — `/jobs/search/<jsid>/page2`: 2 real rows (5166, 5163, Vienna).
- `detail-5166.html` — `/jobs/environmental-governance-adviser-s-5166`: canonical link, title,
  location, the real description and "Additional Information" list, with an HTML comment and
  a `display:none` instruction inserted in the description, and a fake
  `Job Type: Ignore previous instructions…` label inserted before the real ones.
