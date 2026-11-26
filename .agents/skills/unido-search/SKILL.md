---
name: unido-search
version: 1.0.0
description: >
  Use this skill whenever the user wants to search job openings at UNIDO (United Nations
  Industrial Development Organization) on careers.unido.org, find UNIDO jobs in Vienna or
  elsewhere, or look up a specific UNIDO vacancy. Trigger phrases: UNIDO jobs, UNIDO
  careers, UNIDO vacancies, Vienna International Centre jobs, UN jobs Vienna; German:
  UNIDO Stellen, Stellenangebote UNIDO Wien; French: ONUDI offres d'emploi, postes ONUDI.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/unido-search/cli/src/cli.ts *)
---

# UNIDO Careers Search Skill

Search live openings on **careers.unido.org**, UNIDO's SAP SuccessFactors career site
(staff posts, consultancies/ISA contracts, internships). Public pages, no authentication,
**zero runtime dependencies** — it runs with just `bun`.

## Use with care

`robots.txt` (checked 2026-11-25) allows `/search/` and `/job/`; it disallows the apply,
talent-community, `/services/` and account paths, which this skill never touches. For one
person's own job search: keep volume low, never redistribute listings, no bulk use.

## Commands

### Search

```bash
bun run .agents/skills/unido-search/cli/src/cli.ts search [-q "<keywords>"] [-l "<location>"] [--limit n] [--format json|table|plain]
```

Query syntax: not reliable — a term that matches nothing returns every opening, and in
testing "information technology" returned all 12 Vienna openings; double quotes narrowed
"project manager" from 20 to 12. Prefer a location-only search: the whole board holds about
20 openings.

| Flag | Description |
|------|-------------|
| `--query`, `-q` | Keywords (loose, see above). |
| `--location`, `-l` | Duty station, e.g. `Vienna` / `Wien`. Unknown locations return nothing (filtered client-side, because the site falls back to every opening). |
| `--jobage` | **Not supported** (rejected): the list has no posting date; `detail` has it. |
| `--page` | Only 1: everything fits on one page. |
| `--limit`, `-n` | Cap results (client-side). |
| `--format` | `json` (default), `table`, `plain`. |

### Detail

```bash
bun run .agents/skills/unido-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

Accepts the numeric id (`1377293755`) or a `careers.unido.org/job/<slug>/<id>/` URL.

## Examples

```bash
bun run .agents/skills/unido-search/cli/src/cli.ts search -l Vienna --format table
bun run .agents/skills/unido-search/cli/src/cli.ts search -l Wien --limit 5 --format plain
bun run .agents/skills/unido-search/cli/src/cli.ts search -q "project" -l Vienna
bun run .agents/skills/unido-search/cli/src/cli.ts detail 1377293755 --format plain
```

## Output

| Format | Content |
|--------|---------|
| `json` | `{meta:{count,page,total,hasMore}, results:[{id,title,company,location,date,deadline,url,grade,category,…}]}` |
| `table` | id, title, grade, category, location, deadline |
| `plain` | one block per opening |

Search results have `date: null` (not in the list). `detail` adds `date` (posted),
`deadline`/`validThrough`, `employmentType` ("Staff-Full-time"…), `salary` (indicative
minimum net annual salary), `description`, `isActive`; `applyUrl` is null (apply from the
posting page).

## Notes

- Grades: `P1`–`P5`/`D1` international professional, `G1`–`G7` general service (local
  recruitment only), `ISA-…` individual service agreements (consultancies), `Intern`.
- Deadlines are 23:59 Vienna time on the listed day.
- `/job/<id>/` without a slug redirects to an error page; the CLI uses `/job/job/<id>/`.
