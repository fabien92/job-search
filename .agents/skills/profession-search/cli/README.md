# profession-cli

Zero-dependency Bun CLI for www.profession.hu (Hungarian job board, official RSS feeds). See
`../SKILL.md` for usage and `../url-reference.md` for the parsing anchors.

```bash
bun install          # dev types only
bun run typecheck
bun run test         # network-free and port-free: fixtures served by a fetch preload
bun run src/cli.ts search -l Budapest --format table
```

HTML goes through `visibleHtml` and every result through `stripInvisible` (copied from
linkedin-search via randstad-search). `PROFESSION_CLI_DELAY_MS` sets the pause between requests
(default 2000; tests use 0).
