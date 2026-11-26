# Fixtures

Captured from jobs.derstandard.at on 2026-11-25 (low-volume manual reconnaissance, see
`../../../url-reference.md`) and reduced to what the parser reads:

- `search-wien-delivery-manager.html` — `/suche/wien/delivery manager`: the Apollo SSR
  transport scripts with the first 3 real edges, plus one malformed edge, one null edge,
  invisible characters in a title and a bare `undefined` (as the live page has).
- `detail-417ad32a.html` — `/detail/417ad32a-…`: the real JobPosting JSON-LD block, with a
  `display:none` instruction and an HTML comment appended to the description to test that
  hidden markup never reaches the output.
