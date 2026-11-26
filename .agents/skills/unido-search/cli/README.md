# unido-cli

Zero-dependency Bun CLI for careers.unido.org (UNIDO, SAP SuccessFactors career site). See
`../SKILL.md` for usage and `../url-reference.md` for the parsing anchors.

```bash
bun install          # dev types only
bun run typecheck
bun run test         # network-free and port-free: fixtures served by a fetch preload
bun run src/cli.ts search -l Vienna --format table
```

HTML goes through `visibleHtml` and every result through `stripInvisible` (copied from
linkedin-search via derstandard-search).
