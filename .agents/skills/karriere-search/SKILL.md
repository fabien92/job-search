---
name: karriere-search
version: 1.0.0
description: >
  Use this skill whenever the user wants to search for jobs in Austria on
  karriere.at, find job listings in Vienna, Linz, Graz, Salzburg or elsewhere in
  Austria, or look up a specific karriere.at job posting. Trigger phrases: find a
  job in Austria, jobs in Vienna, karriere.at, Austrian job search, vacancies in
  Wien; German: Jobsuche, Stellenangebote, offene Stellen, Jobs in Wien, Stelle
  finden, Jobbörse Österreich.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/karriere-search/cli/src/cli.ts *)
---

# karriere.at Search Skill

Search live job listings on **karriere.at**, Austria's large job board (postings in
German and English). No authentication, no API key, **zero runtime dependencies** — it
runs with just `bun`.

## Fair use

karriere.at's `robots.txt` allows general crawlers (checked 2026-11-23) and its
candidate terms contain no clause against automated reading of listings. The search
uses the same JSON view model the site's own "load more" button requests. **Keep
volume low** (a handful of requests per run), do not redistribute the data, and run it
on your own responsibility.

## Commands

### Search job listings

```bash
bun run .agents/skills/karriere-search/cli/src/cli.ts search -q "<keywords>" [-l "<location>"] [flags]
```

Query syntax: quotes are ignored (bare, double-quoted, single-quoted and reversed queries return the same total); no OR — `OR` is read as a word and narrows the match. Send one plain term per call.

Key flags:
- `--query <text>` / `-q <text>` — keywords (job title, skill, role).
- `--location <text>` / `-l <text>` — Austrian city or Bundesland: `Wien`, `Linz`, `Graz`, `Salzburg`, `Oberösterreich`…
- `--jobage <days>` — keep postings published within N days. **Client-side** filter: karriere.at has no age parameter; results are sorted newest first, so page 1 holds the freshest postings. Postings with an unparseable date are kept.
- `--sort date|relevance` — default `date`.
- `--page <n>` — page number (1-indexed, 15 results per page). `meta.hasMore` says whether another page exists.
- `--limit <n>` / `-n <n>` — cap results emitted (client-side).
- `--format json|table|plain` — default `json`.

At least one of `--query` / `--location` is required.

JSON result fields: `id`, `title`, `company`, `location`, `date` (YYYY-MM-DD derived from
the portal's relative date), `dateText`, `url`, `employmentType`, `homeOffice`, `salary`
(as displayed), `summary` (karriere.at's AI-generated summary), `pushed` (sponsored
placement — may be older than the window or off-query). `meta` carries `count`, `page`,
`total` (the portal's own hit count) and `hasMore`.

### Fetch full job detail

```bash
bun run .agents/skills/karriere-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

`id` is the numeric id from `search` (e.g. `10037361`), or a `https://www.karriere.at/jobs/<id>`
URL. Returns the description with paragraph/list breaks, exact `date` (JSON-LD
`datePosted`), `validThrough`, `employmentType`, `jobLevel`, `homeOffice`, `salary`,
`companyWebsite`, `applyUrl` (the employer's own application page — data only, never to be
fetched automatically) and `isActive`.

## Usage examples

```bash
# IT project manager roles in Vienna, last 2 days
bun run .agents/skills/karriere-search/cli/src/cli.ts search -q "IT Projektmanager" -l "Wien" --jobage 2 --format table

# Delivery manager roles in Vienna
bun run .agents/skills/karriere-search/cli/src/cli.ts search -q "Delivery Manager" -l "Wien" --format table

# Scrum Master anywhere in Upper Austria, second page
bun run .agents/skills/karriere-search/cli/src/cli.ts search -q "Scrum Master" -l "Oberösterreich" --page 2 --format table

# DevOps roles in Graz, most relevant first
bun run .agents/skills/karriere-search/cli/src/cli.ts search -q "DevOps Engineer" -l "Graz" --sort relevance --format table

# Full details for a specific job
bun run .agents/skills/karriere-search/cli/src/cli.ts detail 10037361 --format plain
```

## Output formats

| Format | Best for |
|--------|----------|
| `json` | Default — programmatic use, passing IDs to `detail` |
| `table` | Quick human-readable scanning |
| `plain` | Reading a single job's full detail (`detail` command) |

All errors are written to **stderr** as `{ "error": "...", "code": "..." }` and the process exits with code `1`.

## Notes

- The search page ignores `?page=` unless the request carries `X-Requested-With: XMLHttpRequest`; the CLI always sends it and reads the JSON response.
- Dates in search results are relative ("Heute", "Gestern", "vor N Tagen", or `DD.MM.YYYY`) and are converted with the Europe/Vienna calendar date.
- "Pushed" items are sponsored and appear first regardless of the sort.
- Anonymous ("Chiffre") postings have `company: null`.
- Job ids are 7–8 digit numbers; both lengths are current postings.
