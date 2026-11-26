# Fixtures

Captured from careers.opecfund.org on 2026-11-26 and trimmed to what the parser reads:

- `search-all.html` — `/search/?q=&locationsearch=`: the pagination label (7 results) and 3
  real rows; a zero-width space added to row 1's title, a `display:none` instruction inside
  row 2's location, and one malformed row (no link) appended.
- `detail-1376928157.html` — `/job/job/1376928157/` (Head of Loan Management): canonical link,
  microdata, title and the real description, with an HTML comment and a `display:none`
  instruction inserted after "Job Profile:".
