# randstad-cli

Zero-dependency Bun CLI for www.randstad.at (Randstad Austria job offers). See `../SKILL.md` for
usage and `../url-reference.md` for the parsing anchors.

```bash
bun install          # dev types only
bun run typecheck
bun run test         # network-free and port-free: fixtures served by a fetch preload
bun run src/cli.ts search -l Wien --jobage 14 --format table
```

HTML goes through `visibleHtml` and every result through `stripInvisible` (copied from
linkedin-search via hays-search). `RANDSTAD_CLI_DELAY_MS` sets the pause between page requests
(default 2000; tests use 0).
