---
name: michaelpage-search
version: 1.0.0
description: >
  Use this skill whenever the user wants to list IT job offers from the recruitment agency
  Michael Page in Austria on www.michaelpage.at (Vienna or the whole of Austria: IT project and
  delivery managers, architects, consultants, SAP, security, infrastructure), or read one Michael
  Page posting. Trigger phrases: Michael Page jobs Vienna, Michael Page IT jobs Austria,
  recruitment agency IT jobs Wien; German: Michael Page Stellenangebote, Michael Page IT-Jobs
  Wien, Personalberatung IT Jobs Österreich; French: offres Michael Page Vienne, cabinet de
  recrutement IT Autriche.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/michaelpage-search/cli/src/cli.ts *)
---

# Michael Page Austria Search Skill

List live **IT** openings that **Michael Page Austria** (www.michaelpage.at, PageGroup) publishes
for its clients: the public "Information Technology" listing for Vienna (`/jobs/information-technology/wien-0`)
or for the whole of Austria. Public pages, no authentication, **zero runtime dependencies**: it
runs with just `bun`. Applying happens on the Michael Page site, which this skill never touches.

43 IT openings in Vienna on 2026-11-26 (2 pages of 30), mostly senior and salaried
(€50–150k p.a. shown on the card): project and delivery managers, architects, consultants, SAP,
security, infrastructure. The client employer is never named.

## ⚠️ Personal use only

- `robots.txt` (checked 2026-11-26) disallows the site search (`/search/`, `/*/search/`), the
  application paths (`/job-apply/`), the salary, contract, brand and `item_per_pages` filters, and
  listing paths three levels deep (`*/jobs/*/*/*/`). **There is therefore no keyword search**: the
  CLI walks the two-level IT listing (`/jobs/information-technology/wien-0`, `?page=1`), which the
  sitemap publishes, and reads postings at `/job-detail/<slug>/ref/<ref>`. No Crawl-delay for `*`
  (1 s for bingbot); the CLI waits 3 s between its own requests.
- Terms (`/allgemeine-geschäftsbedingungen`, "Geistiges Eigentum"): content may be viewed, stored
  on your own hard disk ("not on a server") and printed **for personal, non-commercial use**; no
  reproduction, modification or distribution without written consent. No clause on automated
  access. For one person's own job search only: a few runs a day, never redistribute listings,
  never store them on a server. Your own responsibility.

## Commands

### Search

```bash
bun run .agents/skills/michaelpage-search/cli/src/cli.ts search [-l "<place>"] [-q "<words>"] [--page n] [--limit n] [--format json|table|plain]
```

| Flag | Description |
|------|-------------|
| `--location`, `-l` | `Wien` (also `Vienna`, `Vienne`; the default) or `Österreich` (`Austria`, `Autriche`); comma-separated walks each listing once. Any other place is refused (`BAD_ARG`): the sitemap has no other IT listing. |
| `--query`, `-q` | Client-side: keep titles containing every word (case-insensitive). |
| `--page` | One page of 30 (1-indexed; the site's `?page=` counts from 0). Default: every page (at most 10). |
| `--limit`, `-n` | Cap results (client-side). |
| `--format` | `json` (default), `table`, `plain`. |

Query syntax: no portal-side query (robots.txt disallows `/search/`); `-q` is a client-side AND of
words on the title, no phrases, no OR. **No `--jobage`**: the list shows no date (it is refused as
an unknown flag); `detail` gives the publication date.

### Detail

```bash
bun run .agents/skills/michaelpage-search/cli/src/cli.ts detail <url> [--format json|plain]
```

Takes the posting URL from `search` (`https://www.michaelpage.at/job-detail/<slug>/ref/<ref>`):
the slug is required (a bare ref or a wrong slug answers 404). A closed opening answers 404:
exit 1, `NOT_FOUND`.

## Examples

```bash
bun run .agents/skills/michaelpage-search/cli/src/cli.ts search -l Wien --format table
bun run .agents/skills/michaelpage-search/cli/src/cli.ts search -q "delivery manager" --format plain
bun run .agents/skills/michaelpage-search/cli/src/cli.ts search -q oracle --format plain
bun run .agents/skills/michaelpage-search/cli/src/cli.ts search -l Österreich --page 1 --format table
bun run .agents/skills/michaelpage-search/cli/src/cli.ts detail https://www.michaelpage.at/job-detail/application-manager-oracle-mwd/ref/jn-082026-7090937 --format plain
```

## Output

| Format | Content |
|--------|---------|
| `json` | `{meta:{count,page,total,hasMore}, results:[{id,title,company,recruiter,location,date,url,employmentType,homeOffice,salary,summary}]}` |
| `table` | ref, title, location, salary |
| `plain` | one block per opening |

`id` is the Michael Page reference (`jn-112026-7140475`). `company` is always **null**;
`recruiter` is `"Michael Page"`. `date` is **null** in search results. `total` is the number of
cards read (null with `--page`: the site shows no total). `detail` reads the page's JSON-LD
JobPosting: `date` (datePosted), `employmentType` (`FULL_TIME`), `homeOffice`
(`Remote (TELECOMMUTE)` when jobLocationType says so), `salary` (baseSalary), `location`
("Wien, Österreich"), `industry`, `validThrough` (when given) and `description` (preceded by one
line saying it comes from Michael Page for an unnamed client); `applyUrl` is null.

## Notes

- The ref encodes the month the opening was **created** (`jn-052026-…` = May 2026), not its
  publication: `datePosted` is often later (a `05/2026` ref showed 2026-07-17). Never use the ref
  as the posting date.
- The listing is in relevance order, not by date; old openings (2025 refs) stay listed.
- Postings are in German or English; "Home Office" on the card means hybrid or remote is possible.
- "Österreich" covers openings anywhere in Austria, Vienna included.
