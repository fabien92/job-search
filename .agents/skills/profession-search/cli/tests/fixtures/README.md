# Fixtures

Captured from www.profession.hu on 2026-11-26 and trimmed to what the parser reads:

- `rss-it.rss` — `/partner/files/rss-it.rss` (served from stat.profession.hu): 5 real items
  (3059519 Dunakeszi, 3058862 Budapest, 3059477 no town in the slug, 3047267 Budapest, 3055291 no
  town), a zero-width space added to 3059519's title, one item without a link and one with a
  foreign link appended.
- `detail-3058862.html` — `/allas/3058862`: the canonical link, the JSON-LD `@graph` and the
  content boxes only; an HTML comment and a `display:none` instruction inserted in the tasks box.
- `detail-3059477.html` — `/allas/3059477` (premium "optimum" layout): same trimming; a remote
  posting (TELECOMMUTE) without `jobLocation`.
