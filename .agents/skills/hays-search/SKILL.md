---
name: hays-search
version: 1.0.0
description: >
  Use this skill whenever the user wants to search job offers from the recruitment agency Hays
  in Austria on www.hays.at (IT, finance, engineering, life sciences; permanent placements and
  freelance/contracting projects), or look up a specific Hays posting by reference number.
  Trigger phrases: Hays jobs Austria, Hays Vienna jobs, Hays IT contracting Wien, recruitment
  agency jobs Vienna; German: Hays Stellenangebote, Hays Jobs Wien, Personalberatung Hays
  Österreich, freiberufliche Projekte Hays; French: offres Hays Autriche, cabinet de recrutement
  Vienne.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/hays-search/cli/src/cli.ts *)
---

# Hays Austria Search Skill

Search live openings that **Hays Austria** (www.hays.at) lists in Austria: permanent placements
with a client ("Permanent employment with our customer"), freelance projects ("Freiberuflich
für ein Projekt") and temporary assignments. Public pages, no authentication, **zero runtime
dependencies**: it runs with just `bun`. Applying happens on the Hays site, which this skill
never touches.

## ⚠️ Use with care

- `robots.txt` (checked 2026-11-26) disallows `/web/`, `/tinyurl/`, `/login/`,
  `/c/portal/login` and `/*?doAsUserId=`, and asks **`Crawl-delay: 10`**. The search and
  detail paths used here are allowed; the CLI waits **10 s between its own requests**, so a
  full walk of Austria (~4 pages) takes about 30-60 s.
- The terms of use (www.hays.at/en/terms-of-use) say nothing about automated access; they
  forbid interfering with or overburdening the site. For one person's own job search only:
  a few runs a day, never redistribute listings, no bulk use. Your own responsibility.

## Commands

### Search

```bash
bun run .agents/skills/hays-search/cli/src/cli.ts search [-q "<keywords>"] [-l "<place>"] [--jobage n] [--page n] [--limit n] [--format json|table|plain]
```

Query syntax: sent to Hays; all words must match ("project manager" 132 results vs "project"
1046). Double quotes inside the argument make an exact phrase, word order included ("project
manager" 27, "manager project" 0); single quotes are ignored; no OR ("project OR manager" 21,
fewer than the bare words). Checked 2026-11-26 on the totals the site reports.

| Flag | Description |
|------|-------------|
| `--query`, `-q` | Keywords (see above), at most 100 characters. Without it, every opening in Austria. |
| `--location`, `-l` | Place, client-side substring match on the card location; `Vienna`/`Wien` match each other (and "Bundesland Wien", "Himberg bei Wien", "Wien und remote"); comma-separated list matches any (`Vienna,Graz`). |
| `--jobage` | Max days since "Online since" (client-side; every page is still read: the order is only roughly newest first). |
| `--page` | One page of 20 (1-indexed). Default: every page (at most 6). |
| `--limit`, `-n` | Cap results (client-side). |
| `--format` | `json` (default), `table`, `plain`. |

Only openings in **Austria** are searched (Hays country filter). Hays.at also lists Germany,
Switzerland, Denmark and Great Britain, but not Slovakia or Hungary.

### Detail

```bash
bun run .agents/skills/hays-search/cli/src/cli.ts detail <ref|url> [--format json|plain]
```

Accepts the reference number (`903672-1` or `903672/1`) or a www.hays.at posting URL
(`/jobsuche/stellenangebote-jobs-detail-<slug>-903672/1` or `…-detail?prospectNr=903672/1`).
A closed opening redirects to "Jobangebot nicht verfügbar": exit 1, `NOT_FOUND`.

## Examples

```bash
bun run .agents/skills/hays-search/cli/src/cli.ts search -l Vienna --jobage 14 --format table
bun run .agents/skills/hays-search/cli/src/cli.ts search -q "project manager" -l Wien
bun run .agents/skills/hays-search/cli/src/cli.ts search -q '"service delivery"' --format plain
bun run .agents/skills/hays-search/cli/src/cli.ts search -l "Vienna,Graz,Linz" --limit 10
bun run .agents/skills/hays-search/cli/src/cli.ts detail 901080-1 --format plain
```

## Output

| Format | Content |
|--------|---------|
| `json` | `{meta:{count,page,total,hasMore}, results:[{id,title,company,recruiter,location,date,url,employmentType,homeOffice,salary,summary}]}` |
| `table` | id, date, title, location |
| `plain` | one block per opening |

`company` is always **null**: Hays does not name its client. `recruiter` is `"Hays"`.
`detail` adds `industry` (the client's sector, e.g. "Versicherungen"), `startDate`, `salary`
(the "Salary information" section when there is one), `description` (sections About the
company / Responsibilities / Profile / Benefits / Salary information, preceded by one line
saying the posting comes from Hays for an unnamed client), `employmentType` with the JSON-LD
types (`FULL_TIME, PERMANENT` or `FULL_TIME, CONTRACTING`); `applyUrl` and `validThrough` are
null (the JSON-LD `validThrough` is a placeholder two years ahead).

## Notes

- Postings are in German or English; contract types are often German even on `/en/` pages.
- Freelance projects ("Freiberuflich für ein Projekt", JSON-LD `CONTRACTING`) are self-employed
  contracts, not jobs: decide on them explicitly.
- The page language depends on `Accept-Language`: with it, "Online since: 25.11.26"; without,
  "Online since: Tue Nov 24 15:11:24 CET 2026". Both are parsed.
- `/p/<n>/` with a trailing slash answers 301; the CLI uses `/p/<n>`.
- Ids are `<number>-<suffix>` from the Hays reference number "903672/1".
