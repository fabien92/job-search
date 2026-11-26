---
name: jobgether-search
version: 1.0.0
description: >
  Use this skill whenever the user wants to search remote job offers on Jobgether
  (jobgether.com), the remote-work job board, through its public API for AI agents: fully
  remote roles open to candidates in Austria, Europe or worldwide, e.g. remote IT delivery
  manager, remote project manager EMEA. Trigger phrases: Jobgether jobs, remote jobs Europe,
  remote jobs open to Austria, full remote IT jobs; German: Remote-Jobs Österreich,
  Homeoffice-Stellen Europa, vollständig remote; French: offres en télétravail Europe,
  emploi 100 % à distance, Jobgether.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/jobgether-search/cli/src/cli.ts *)
---

# Jobgether Search Skill

Search **remote** job offers listed on Jobgether (jobgether.com) through the public JSON API
Jobgether publishes for AI agents (`/astroapi/ai/jobs.json`, documented at
`/astroapi/ai/jobs/docs`). No authentication, **zero runtime dependencies**: it runs with just
`bun`. Every offer is remote ("Full Remote"); the `location` field says **who may apply**, not
where an office is.

## ⚠️ Use with care

- `robots.txt` (checked 2026-11-26) explicitly allows `/astroapi/ai/jobs.json?*` and disallows
  every other URL with a query string (`/*?*`), so the canonical alias `/api/v1/jobs?…` is
  **not** used. Rate limit announced by the API: 60 requests per minute; the CLI waits 1.1 s
  between its own page requests.
- The terms of use (jobgether.com/terms-of-use) forbid extracting the platform's content by
  automated means (bots, scrapers, crawlers). The API is the channel Jobgether offers to agents;
  the CLI **never fetches the offer pages** (they answer 403 to it anyway). For one person's
  own job search only: a few runs a day, never redistribute listings.

## Commands

### Search

```bash
bun run .agents/skills/jobgether-search/cli/src/cli.ts search [-q "<keywords>"] [-l <slug,...>] [--strict] [--jobage n] [--sort date|relevance] [--page n] [--limit n] [--format json|table|plain]
```

Query syntax: every word must match ("delivery" 47 offers open to Austria, "delivery manager"
19); double or single quotes and word order change nothing ("project manager", '"project
manager"', "'project manager'", '"manager project"': 199 each); no OR ("project OR manager": 1,
OR is read as a word). The API reports no total: counted by walking every page, 2026-11-26.

| Flag | Description |
|------|-------------|
| `--query`, `-q` | Keywords, matched on title, job function, skills, company name, contract type and language. At most 100 characters. |
| `--location`, `-l` | Jobgether location slugs, comma-separated: country, continent or city (`austria`, `vienna`, `europe`, `anywhere`…). The API keeps offers open to candidates there: `austria` returns offers open to Austria, Europe, EMEA **and "Anywhere"**. An unknown slug exits 1 with `BAD_ARG`. |
| `--strict` | Client-side: keep an offer only if its `location` names Europe, European Union, EMEA, DACH or CET, or the searched place (`austria`/`vienna` → "Austria"). Drops "Anywhere"-only offers, mostly US employers (135 of 199 "project manager" offers for Austria). |
| `--jobage` | Max days since `postedAt` (client-side; with `--sort date` the walk stops at the first page that holds older offers). |
| `--sort` | `date` (default, strictly newest first) or `relevance`. |
| `--page` | One page of 25 (1-indexed, at most 10). Default: walk pages until the end (at most 10). |
| `--limit`, `-n` | Cap results (client-side). |
| `--format` | `json` (default), `table`, `plain`. |

`includeHybrid` is not offered: on 2026-11-26 it changed nothing for Vienna or Austria (every
offer stayed "Full Remote").

### Detail

```bash
bun run .agents/skills/jobgether-search/cli/src/cli.ts detail <offer-url> [--format json|plain]
```

The API has **no per-offer endpoint and no description**. `detail` takes the offer URL
(`https://jobgether.com/offer/<id>-<slug>`), searches the API again with the slug's words
(then its first three words) and returns that offer's listing fields. A bare id exits 1 with
`NEEDS_URL`; an offer the search no longer finds exits 1 with `NOT_FOUND`.

## Examples

```bash
bun run .agents/skills/jobgether-search/cli/src/cli.ts search -q "delivery manager" -l austria --strict --format table
bun run .agents/skills/jobgether-search/cli/src/cli.ts search -q "project manager" -l austria --strict --jobage 7
bun run .agents/skills/jobgether-search/cli/src/cli.ts search -q "release manager" -l europe --strict --format plain
bun run .agents/skills/jobgether-search/cli/src/cli.ts search -q "scrum master" -l vienna --strict --limit 10
bun run .agents/skills/jobgether-search/cli/src/cli.ts detail https://jobgether.com/offer/6ad67e28a8fae18ba2cdd2c0-delivery-manager --format plain
```

## Output

| Format | Content |
|--------|---------|
| `json` | `{meta:{count,page,total:null,fetched,filtered,hasMore}, results:[{id,title,company,location,date,url,remote,employmentType,seniority,salary,jobFunctions,homeOffice,summary,description,applyUrl,validThrough,isActive}]}` |
| `table` | id, date, title, company, open to |
| `plain` | one block per offer |

`description` is **built from the listing fields** (remote type, who may apply, contract,
experience, job functions, salary, date) and starts by saying that the API gives no full
description. `applyUrl` and `validThrough` are always null; `summary` too.

## Notes

- `location` lists eligible areas, often mixed: "Europe, EMEA", "Anywhere", "Austria, Delaware
  (USA)", "United States, EMEA, Europe, European Union, Austria". Even with `--strict`, an
  offer may hide residency or time-zone conditions in the description the API does not give.
- `contractType` values seen: Full time, Fixed term, Freelance, Part time, Internships.
- A republished offer keeps the URL of the original (another id in `/offer/<id>-…`): both are
  accepted, and `detail` finds it by either id.
- `salaryRange` (e.g. "60000-80000 EUR", "28800-34560 USD") appears on a minority of offers.
- Errors from the API are RFC 9457 problem documents (`code: invalid_parameter`, `timeout`…).
