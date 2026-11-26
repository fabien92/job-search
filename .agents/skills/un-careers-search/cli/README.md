# un-careers-cli

Zero-dependency Bun CLI for the UN Careers public JSON API (careers.un.org). See
`../SKILL.md` for usage and `../url-reference.md` for the endpoints and fields.

```bash
bun install          # dev types only
bun run typecheck
bun run test         # network-free and port-free: fixtures served by a fetch preload
bun run src/cli.ts search -l Vienna --format table
```

Description HTML goes through `visibleHtml` and every result through `stripInvisible`
(both copied from linkedin-search via derstandard-search).
