# hays-cli

Zero-dependency Bun CLI for www.hays.at (Hays Austria job offers). See `../SKILL.md` for usage
and `../url-reference.md` for the parsing anchors.

```bash
bun install          # dev types only
bun run typecheck
bun run test         # network-free and port-free: fixtures served by a fetch preload
bun run src/cli.ts search -l Vienna --jobage 14 --format table
```

HTML goes through `visibleHtml` and every result through `stripInvisible` (copied from
linkedin-search via osce-search). From the JSON-LD only short, pattern-checked fields are read.
`HAYS_CLI_DELAY_MS` sets the pause between page requests (default 10000, robots.txt
Crawl-delay; tests use 0).
