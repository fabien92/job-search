# opecfund-cli

Zero-dependency Bun CLI for careers.opecfund.org (OPEC Fund for International Development,
SAP SuccessFactors career site). See `../SKILL.md` for usage and `../url-reference.md` for the
parsing anchors.

```bash
bun install          # dev types only
bun run typecheck
bun run test         # network-free and port-free: fixtures served by a fetch preload
bun run src/cli.ts search -l Vienna --format table
```

Adapted from unido-search (same platform). HTML goes through `visibleHtml` and every result
through `stripInvisible` (copied from linkedin-search).
