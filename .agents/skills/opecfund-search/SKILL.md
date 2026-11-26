---
name: opecfund-search
version: 1.0.0
description: >
  Use this skill whenever the user wants to search job openings at the OPEC Fund for
  International Development (OPEC Fund, formerly OFID) on careers.opecfund.org, find OPEC Fund
  jobs in Vienna, or look up a specific OPEC Fund vacancy. Trigger phrases: OPEC Fund jobs,
  OPEC Fund careers, OPEC Fund vacancies, development finance jobs Vienna; German: OPEC-Fonds
  Stellen, Stellenangebote OPEC Fund Wien; French: Fonds OPEP offres d'emploi, postes Fonds OPEP.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/opecfund-search/cli/src/cli.ts *)
---

# OPEC Fund Careers Search Skill

Search live openings on **careers.opecfund.org**, the OPEC Fund for International
Development's SAP SuccessFactors career site (same platform as UNIDO's). Public pages, no
authentication, **zero runtime dependencies**: it runs with just `bun`.

## Use with care

`robots.txt` (checked 2026-11-26) allows `/search/` and `/job/`; it disallows the apply,
talent-community, `/services/` and account paths, which this skill never touches. The
opecfund.org terms of use say nothing about automated access but forbid overburdening the
site: one search request per run, one detail per new opening. For one person's own job
search: never redistribute listings, no bulk use.

## Commands

### Search

```bash
bun run .agents/skills/opecfund-search/cli/src/cli.ts search [-q "<keywords>"] [-l "<location>"] [--jobage n] [--limit n] [--format json|table|plain]
```

Query syntax: filtered by the CLI, not the portal: every word must appear in the title;
quotes are ignored (no phrase match) and there is no OR. The board holds fewer than 10
openings, so prefer a location-only search.

| Flag | Description |
|------|-------------|
| `--query`, `-q` | Title keywords (client-side AND, see above). |
| `--location`, `-l` | `Vienna` / `Wien` / `Austria`; comma-separated list matches any. Unknown locations return nothing. |
| `--jobage` | Posting at most N days old (the list shows the posting date). |
| `--page` | Only 1: everything fits on one page. |
| `--limit`, `-n` | Cap results (client-side). |
| `--format` | `json` (default), `table`, `plain`. |

### Detail

```bash
bun run .agents/skills/opecfund-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

Accepts the numeric id (`1376928157`) or a `careers.opecfund.org/job/<slug>/<id>/` URL.

## Examples

```bash
bun run .agents/skills/opecfund-search/cli/src/cli.ts search -l Vienna --format table
bun run .agents/skills/opecfund-search/cli/src/cli.ts search -l Wien --jobage 14 --format plain
bun run .agents/skills/opecfund-search/cli/src/cli.ts search -q "officer" -l Vienna
bun run .agents/skills/opecfund-search/cli/src/cli.ts detail 1376928157 --format plain
```

## Output

| Format | Content |
|--------|---------|
| `json` | `{meta:{count,page,total,hasMore}, results:[{id,title,company,location,date,deadline,url,grade,category,department,employmentType,…}]}` |
| `table` | id, title, location, posted |
| `plain` | one block per opening |

Search results have `deadline`, `grade`, `category` null (not in the list). `detail` adds
`deadline`/`validThrough`, `grade` ("H1", "P4"…), `category` (Job Category), `department`,
`employmentType` (contract type · recruitment status), `contractDuration`, `description`,
`isActive`; `salary` and `applyUrl` are null.

## Notes

- The site gives only the country code `AT`; every posting is at the Vienna headquarters
  (Parkring 8), so the CLI reports `Vienna, Austria`.
- Postings state that all nationalities are eligible; nationals of member countries are
  encouraged to apply. Recruitment is "International / Local" depending on nationality and
  residence at appointment.
- Deadlines are midnight Vienna time at the end of the listed day.
- `/job/<id>/` without a slug redirects to an error page; the CLI uses `/job/job/<id>/`.
