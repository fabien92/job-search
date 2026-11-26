---
name: profession-search
version: 1.0.0
description: >
  Use this skill whenever the user wants to list job offers from Profession.hu, the largest
  Hungarian job board (IT and other categories, Budapest or the whole of Hungary), or look up a
  specific Profession.hu posting by job id.
  Trigger phrases: Profession.hu jobs, Budapest IT jobs, jobs in Hungary;
  Hungarian: állás Budapest, informatikai állások, Profession állásajánlatok;
  French: offres Profession.hu, emploi Budapest, offres IT Hongrie.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/profession-search/cli/src/cli.ts *)
---

# Profession.hu Search Skill

List the newest openings that **Profession.hu** publishes in one category, through the board's
own **RSS feeds** (one per category, linked from the home page footer), and read single postings.
Public pages, no authentication, **zero runtime dependencies**: it runs with just `bun`. Applying
happens on Profession.hu, which this skill never touches.

Each feed holds the **20 newest openings for the whole of Hungary**. The IT feed is mostly
hands-on technical roles (developers, system administrators, SRE, SAP); postings are largely in
Hungarian, some in English.

## ⚠️ Use with care

- `robots.txt` (checked 2026-11-26) disallows the account, application (`/jelentkezes/`),
  employer and candidate areas, `/en/`, `/impresszum`, the terms PDFs and `*?rss$` (the search
  pages' RSS variant). The category feeds (`/partner/files/rss-<category>.rss`) and the postings
  (`/allas/`) are allowed. No Crawl-delay; the CLI waits 2 s between its own requests.
- Terms of use (felhasznalasifeltetelek_20201008.pdf, §V.3): the content may be read, displayed,
  saved and printed **for personal, non-commercial use only**; §VIII.1.d: no program that
  endangers the service. No clause on automated access. For one person's own job search only: a
  few runs a day, never redistribute listings. Your own responsibility.
- There is **no keyword search**: filter the titles yourself (or let the caller's rules do it).

## Commands

### Search

```bash
bun run .agents/skills/profession-search/cli/src/cli.ts search [-c <category>] [-l "<place>"] [--lookups n] [--limit n] [--format json|table|plain]
```

| Flag | Description |
|------|-------------|
| `--category`, `-c` | Feed: `it` (default), `adminisztracio`, `bank`, `egeszsegugy`, `ertekesites`, `hr`, `jog`, `marketing`, `mernok`, `oktatas`, `szakmunka`, `szamvitel`, `ugyfelszolgalat`, `vendeglatas`. |
| `--location`, `-l` | Hungarian town(s), comma-separated, accents optional (`Budapest`, `Gyor`). Cards whose link names another town are dropped; cards whose link names none are placed by reading their posting; a posting without an address but flagged remote is kept. Any place the CLI does not know is refused (`BAD_ARG`). Without it, the whole feed. |
| `--lookups` | At most n postings read to place cards (default 10); the rest are dropped and counted in `meta.unresolved`. |
| `--limit`, `-n` | Cap results (client-side). |
| `--format` | `json` (default), `table`, `plain`. |

Query syntax: none — there is no keyword search (the category feed is read as is); filter the
titles yourself (or let the caller's rules do it).

The feed has **no posting date** (`date` is null): `detail` gives it.

### Detail

```bash
bun run .agents/skills/profession-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

Accepts the job id (`3058862`) or a www.profession.hu posting URL (`/allas/<slug>-3058862`, with
or without `/optimum` and the feed's `/p/569`). The CLI requests `/allas/<id>`. A missing posting
answers 404: exit 1, `NOT_FOUND`.

## Examples

```bash
bun run .agents/skills/profession-search/cli/src/cli.ts search -l Budapest --format table
bun run .agents/skills/profession-search/cli/src/cli.ts search -c bank --format plain
bun run .agents/skills/profession-search/cli/src/cli.ts detail 3058862 --format plain
```

## Output

| Format | Content |
|--------|---------|
| `json` | `{meta:{count,page,total,hasMore,unresolved}, results:[{id,title,company,location,date,url,employmentType,homeOffice,salary,summary}]}` |
| `table` | id, title, company, location |
| `plain` | one block per opening |

`company` is the feed's "Hirdető cég" (the advertiser: sometimes a recruitment agency such as
Karrier Hungária). `detail` reads the page's JSON-LD `JobPosting` and adds `country`,
`experience` ("1-3 év tapasztalat"), `education`, `hours`, `category`, `validThrough`,
`homeOffice` ("remote" when flagged TELECOMMUTE), `salary` (when published) and `description`
(the posting's sections, `## <title>` each); `applyUrl` is null. A remote posting without an
address has the location `Magyarország (távmunka)`.

## Notes

- `employmentType` is Hungarian: "Alkalmazotti jogviszony" = employee; empty on some postings.
- `isActive` is false once `validThrough` has passed.
- The feed's `<pubDate>` is the feed's generation time, the same for every item: not used.
