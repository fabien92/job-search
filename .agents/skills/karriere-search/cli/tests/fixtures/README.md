# Fixtures

Captured from karriere.at on 2026-11-23 (low-volume manual reconnaissance, see
`../../../url-reference.md`) and reduced to the fields the parser reads.

- `search-page2.json` — XHR response of `GET /jobs?keywords=IT%20Projektmanager&locations=Wien&sort=date&page=2`
  with `X-Requested-With: XMLHttpRequest`; 4 job items kept, plus one synthetic
  non-job disruptor item to exercise the per-item parser.
- `detail-10037361.html` — `GET /jobs/10037361`: the JobPosting JSON-LD block and the
  `window.VUE_INITIAL_STATE` view model (branded `jobContent.html`, job suggestions and
  share links removed). Everything else on the page was dropped.
