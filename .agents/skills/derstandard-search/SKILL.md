---
name: derstandard-search
version: 1.0.0
description: >
  Use this skill whenever the user wants to search for jobs in Austria on DER STANDARD
  Jobs (jobs.derstandard.at, derStandard Karriere), find job listings in Vienna, Graz,
  Linz or elsewhere in Austria, or look up a specific jobs.derstandard.at posting.
  Trigger phrases: derStandard jobs, DER STANDARD Karriere, jobs in Vienna, Austrian job
  search; German: Jobsuche, Stellenangebote, offene Stellen, Jobs in Wien, Stelle finden,
  derStandard Stellenmarkt, Karriere derStandard.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/derstandard-search/cli/src/cli.ts *)
---

# DER STANDARD Jobs Search Skill

Search live job listings on **jobs.derstandard.at**, the job board of the Austrian daily
DER STANDARD (postings in German and English). No authentication, no API key, **zero
runtime dependencies** — it runs with just `bun`.

## ⚠️ Personal use only

`robots.txt` (checked 2026-11-25) lets every crawler read search and `/detail/` pages
(only `/wp-admin/`, `/jobsuche/c/job/` and `/jobsuche/tracking/` are disallowed). The
publisher's AGB (section VI, "Text- und Data-Mining, Crawler") **reserve commercial
text-and-data mining** (§ 42h Abs 6 UrhG) and forbid crawlers from posting content.
This skill is for one person's own job search: **keep volume low** (a handful of requests
per run, pauses between them), never redistribute or republish listings, never post
anything, no commercial or bulk use — on your own responsibility. Stop if the site
starts refusing requests.

## Commands

### Search job listings

```bash
bun run .agents/skills/derstandard-search/cli/src/cli.ts search -q "<keywords>" [-l "<location>"] [flags]
```

Query syntax: quotes are not honoured (bare, double-quoted, single-quoted and reversed queries all returned at least the bare total); no OR — `OR` is read as a word. Matching is fuzzy (related titles are included); send one plain term per call.

Key flags:
- `--query <text>` / `-q <text>` — keywords (job title, skill, role).
- `--location <text>` / `-l <text>` — Austrian city or Bundesland, turned into the portal's slug: `Wien`, `Graz`, `Linz`, `Niederösterreich`… Default: all of Austria.
- `--jobage <days>` — keep postings published within N days. **Client-side** filter: the portal has no public age parameter. Postings with an unparseable date are kept.
- `--page <n>` — only `1`. The server renders the first 20 results (relevance order) and ignores `?page=`; further results are loaded client-side, which this CLI does not use. `--page 2` exits with `PAGE_UNSUPPORTED`. `meta.hasMore` says whether the portal has more.
- `--limit <n>` / `-n <n>` — cap results emitted (client-side).
- `--format json|table|plain` — default `json`.

At least one of `--query` / `--location` is required.

JSON result fields: `id` (uuid), `title`, `company`, `location` (places, "Home-Office"
removed), `date` (Vienna calendar date of the portal's display date), `url`,
`employmentType`, `homeOffice` (`true` or `null`), `salary` ("ab 83.000 € jährlich",
the advertised minimum), `summary`, `tags` (the portal's keywords). `meta` carries
`count`, `page`, `total` (the portal's own hit count) and `hasMore`.

### Fetch full job detail

```bash
bun run .agents/skills/derstandard-search/cli/src/cli.ts detail <uuid|url> [--format json|plain]
```

`uuid` is the id from `search`, or a `https://jobs.derstandard.at/detail/<uuid>` URL (any
other host is refused). Returns the description with paragraph/list breaks, `date`
(JSON-LD `datePosted`), `validThrough`, `employmentType`, `homeOffice`, `salary` and
`isActive` (false once `validThrough` has passed). `applyUrl` is always `null`: the page
has no structured application link.

## Usage examples

```bash
# IT delivery manager roles in Vienna, last 2 days
bun run .agents/skills/derstandard-search/cli/src/cli.ts search -q "IT Delivery Manager" -l "Wien" --jobage 2 --format table

# IT project managers in Vienna
bun run .agents/skills/derstandard-search/cli/src/cli.ts search -q "IT Projektmanager" -l "Wien" --format table

# Scrum Master anywhere in Austria
bun run .agents/skills/derstandard-search/cli/src/cli.ts search -q "Scrum Master" --format table

# Project managers in Graz
bun run .agents/skills/derstandard-search/cli/src/cli.ts search -q "Projektmanager" -l "Graz" --limit 5 --format table

# Full details for a specific job
bun run .agents/skills/derstandard-search/cli/src/cli.ts detail 417ad32a-0b7b-3f3c-87a9-2404ca45b101 --format plain
```

## Output formats

| Format | Best for |
|--------|----------|
| `json` | Default — programmatic use, passing IDs to `detail` |
| `table` | Quick human-readable scanning (ids shortened to 8 characters) |
| `plain` | Reading a single job's full detail (`detail` command) |

All errors are written to **stderr** as `{ "error": "...", "code": "..." }` and the process exits with code `1`.

## Notes

- Search results are read from the Apollo SSR payload the page embeds (`ApolloSSRDataTransport`); it is JavaScript, not JSON (bare `undefined`), and is parsed with a string-aware scanner.
- Order is relevance, not date: a fresh posting with a weak match may sit beyond the first 20 results. Use precise queries.
- Matching is broad ("Delivery Manager" also returns "Sales Manager"): filter downstream.
- Many postings come from recruitment agencies (Iventa, ISG, epunkt, DIS AG…): the employer is then not named.
- The detail page's "Jetzt bewerben" button is client-side; any application link inside the description is posting text (untrusted), never a field.
