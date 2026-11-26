# jobgether-cli

Zero-dependency Bun CLI for Jobgether remote job offers, through the public JSON API for AI
agents (`/astroapi/ai/jobs.json`). See `../SKILL.md` for usage and `../url-reference.md` for the
API notes.

```bash
bun install          # dev types only
bun run typecheck
bun run test         # network-free and port-free: fixtures served by a fetch preload
bun run src/cli.ts search -q "delivery manager" -l austria --strict --format table
```

Every result goes through `stripInvisible` (copied from linkedin-search) and API strings are
flattened to one line. The offer pages are never fetched (terms of use): `description` is built
from the listing fields. `JOBGETHER_CLI_DELAY_MS` sets the pause between page requests
(default 1100, API rate limit 60/min; tests use 0).
