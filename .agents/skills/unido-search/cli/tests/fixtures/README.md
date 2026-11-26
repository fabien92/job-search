# Fixtures

Captured from careers.unido.org on 2026-11-25 and trimmed to what the parser reads:

- `search-vienna.html` — `/search/?q=&locationsearch=Vienna`: the pagination label and the
  first 3 real rows; a zero-width space added to row 2's title, a `display:none` instruction
  inside row 3's category, and one malformed row (no link) appended.
- `detail-1376269755.html` — `/job/Vienna-Administrative-Innovation-Assistant/1376269755/`:
  canonical link, microdata, title and the real description, with an HTML comment and a
  `display:none` instruction inserted to test that hidden markup never reaches output.
