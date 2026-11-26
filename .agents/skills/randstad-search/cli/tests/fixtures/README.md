# Fixtures

Captured from www.randstad.at on 2026-11-26 and trimmed to what the parser reads:

- `list-wien-page1.html` — `/jobs/wien/wien/`: the `sortbar__count` heading with the total set to
  33 (two pages; the site said 39), 3 real cards (47720442, 47569632, 47607006); a zero-width
  space added to 47720442's title, a `display:none` instruction inside 47569632's teaser, one
  malformed card (no link) appended.
- `list-wien-page2.html` — `/jobs/wien/wien/page-2/`: 2 real cards (47815606, 47730596).
- `detail-47720442.html` — `/jobs/senior-project-manager-mit-fokus-implementierung-mwd_wien_47720442/`
  with scripts, styles and SVG icons removed: the header (h1, dates) and the job-details block
  (summary box, both copies of the text), with an HTML comment and a `display: none` instruction
  inserted before "Ihr Profil".
- `list-it-wien.html` — `/jobs/s-edv-it/wien/wien/` captured 2026-11-26:
  the Berufsfeld heading "2 EDV &amp; IT Jobs in Wien, Wien für Sie gefunden" and its 2 real cards
  (47716226, 47730596), scripts removed.
