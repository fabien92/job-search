---
name: osce-search
version: 1.0.0
description: >
  Use this skill whenever the user wants to search vacancies at the OSCE (Organization for
  Security and Co-operation in Europe) on vacancies.osce.org, find OSCE jobs at the Vienna
  Secretariat or a field operation, or look up a specific OSCE vacancy. Trigger phrases: OSCE
  jobs, OSCE vacancies, OSCE careers, OSCE Secretariat Vienna jobs, international organisation
  jobs Vienna; German: OSZE Stellen, Stellenangebote OSZE Wien; French: OSCE offres d'emploi,
  postes OSCE Vienne.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/osce-search/cli/src/cli.ts *)
---

# OSCE Vacancies Search Skill

Search live openings on **vacancies.osce.org**, the OSCE's public job board (Secretariat in
Vienna, institutions, field operations). Public pages, no authentication, **zero runtime
dependencies**: it runs with just `bun`. Applying happens on talent.osce.org, which this
skill never touches.

## Use with care

`robots.txt` (checked 2026-11-25) has an empty `Disallow:`, so nothing is blocked. The OSCE
terms of use (osce.org/about/terms-of-use) say nothing about automated access; the copyright
policy allows personal use with credit to the OSCE. For one person's own job search: one run
a day, a pause between requests (1.5 s by default), never redistribute listings, no bulk use.

## Commands

### Search

```bash
bun run .agents/skills/osce-search/cli/src/cli.ts search [-q "<keywords>"] [-l "<location>"] [--page n] [--limit n] [--format json|table|plain]
```

Query syntax: filtered by the CLI, not the portal: every word must appear in the title,
snippet, location or category; quotes are ignored (no phrase match) and there is no OR. The
whole board holds about 45 openings, so prefer a location-only search.

| Flag | Description |
|------|-------------|
| `--query`, `-q` | Keywords (client-side AND, see above). |
| `--location`, `-l` | Duty station, e.g. `Vienna` / `Wien` / `Warsaw`; comma-separated list matches any (`Vienna,Bratislava`); client-side substring match. |
| `--jobage` | **Not supported** (rejected): the list has no dates; `detail` has them. |
| `--page` | One page of 10 (1-indexed). Default: the whole board (about 5 requests). |
| `--limit`, `-n` | Cap results (client-side). |
| `--format` | `json` (default), `table`, `plain`. |

### Detail

```bash
bun run .agents/skills/osce-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

Accepts the numeric id (`5169`) or a `vacancies.osce.org/jobs/<slug>-<id>` URL.

## Examples

```bash
bun run .agents/skills/osce-search/cli/src/cli.ts search -l Vienna --format table
bun run .agents/skills/osce-search/cli/src/cli.ts search -l Wien --limit 5 --format plain
bun run .agents/skills/osce-search/cli/src/cli.ts search -q "information" -l Vienna
bun run .agents/skills/osce-search/cli/src/cli.ts search -l "Vienna,Bratislava,Budapest"
bun run .agents/skills/osce-search/cli/src/cli.ts detail 5169 --format plain
```

## Output

| Format | Content |
|--------|---------|
| `json` | `{meta:{count,page,total,hasMore}, results:[{id,title,company,location,date,deadline,url,grade,category,jobType,employmentType,…}]}` |
| `table` | id, title, location |
| `plain` | one block per opening |

Search results have `date`, `deadline`, `grade` and `jobType` null (not in the list).
`detail` adds `date` (Issue Date), `deadline`/`validThrough` (Closing Date), `grade`,
`jobType` (Contracted / Seconded / Intern / Consultant), `employmentType` ("Local
Contracted", "International Secondment …"), `salary` (monthly amount when the posting states
one), `issuedBy`, `requisitionId`, `description`, `isActive`; `applyUrl` is null.

## Notes

- **Seconded posts** (`jobType: Seconded`, grades `S`, `S1`–`S4`) are filled through a
  nomination by the candidate's own participating State; `employmentType` says so. Contracted
  posts (`P`/`G` grades) are open to direct applications from nationals of participating States.
- `G` grades are local recruitment (residence in the duty-station country expected).
- Interns and consultancies (`SSA`) are on the same board; filter on `jobType` from `detail`.
- Closing dates are inclusive (Vienna calendar day).
- Each search request makes the site create a new saved search (`/jobs/search/<jsid>`); the
  CLI reuses that one id for the following pages.
