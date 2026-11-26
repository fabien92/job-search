# derstandard-cli

Zero-dependency Bun CLI for jobs.derstandard.at (DER STANDARD Jobs, Austria). See
`../SKILL.md` for usage and `../url-reference.md` for the endpoints and parsing anchors.

```bash
bun install          # dev types only
bun run typecheck
bun run test         # network-free and port-free: fixtures served by a fetch preload
bun run src/cli.ts search -q "IT Delivery Manager" -l Wien --format table
```

Parsing reads the Apollo SSR payload (search) and the JSON-LD JobPosting (detail); no HTML
parsing library is needed. Description HTML goes through `visibleHtml` and every result
through `stripInvisible` (both copied from linkedin-search via karriere-search).
