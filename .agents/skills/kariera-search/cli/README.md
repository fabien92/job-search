# kariera-cli

Zero-dependency Bun CLI for kariera.zoznam.sk (Kariéra.sk, Slovak job board, public category
listings). See `../SKILL.md` for usage and `../url-reference.md` for the parsing anchors.

```bash
bun install          # dev types only
bun run typecheck
bun run test         # network-free and port-free: fixtures served by a fetch preload
bun run src/cli.ts search -l Bratislava --jobage 2 --format table
```

HTML goes through `visibleHtml` and every result through `stripInvisible` (copied from
linkedin-search via profession-search). `KARIERA_CLI_DELAY_MS` sets the pause between requests
(default 2000; tests use 0).
