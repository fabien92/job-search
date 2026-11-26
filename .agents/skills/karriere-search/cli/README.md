# karriere-cli

Zero-dependency Bun CLI for karriere.at (Austria). See `../SKILL.md` for usage and
`../url-reference.md` for the endpoints and parsing anchors.

```bash
bun install          # dev types only
bun run typecheck
bun run test         # network-free: fixtures + local server, external requests blocked
bun run src/cli.ts search -q "IT Projektmanager" -l Wien --format table
```

Parsing reads the JSON view model (search) and JSON-LD + view model (detail); no HTML
parsing library is needed. Description HTML goes through `visibleHtml` and every result
through `stripInvisible` (both copied from linkedin-search).
