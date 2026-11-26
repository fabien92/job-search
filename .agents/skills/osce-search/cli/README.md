# osce-cli

Zero-dependency Bun CLI for vacancies.osce.org (OSCE job board). See `../SKILL.md` for usage
and `../url-reference.md` for the parsing anchors.

```bash
bun install          # dev types only
bun run typecheck
bun run test         # network-free and port-free: fixtures served by a fetch preload
bun run src/cli.ts search -l Vienna --format table
```

HTML goes through `visibleHtml` and every result through `stripInvisible` (copied from
linkedin-search via unido-search). The detail page's labelled fields live in a hidden block:
only whitelisted labels with strictly validated values are read (`parseMeta`).
`OSCE_CLI_DELAY_MS` sets the pause between page requests (default 1500; tests use 0).
