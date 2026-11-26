---
name: kariera-search
version: 1.0.0
description: >
  Use this skill whenever the user wants to list job offers from Kariéra.sk (kariera.zoznam.sk),
  a Slovak job board (IT categories by default, Bratislava or another Slovak region), or look up a
  specific Kariéra.sk posting by offer id.
  Trigger phrases: Kariera.sk jobs, Bratislava IT jobs, jobs in Slovakia;
  Slovak: pracovné ponuky Bratislava, práca v IT, ponuky práce Kariéra;
  French: offres Kariera.sk, emploi Bratislava, offres IT Slovaquie.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/kariera-search/cli/src/cli.ts *)
---

# Kariéra.sk Search Skill

List the offers that **Kariéra.sk** (kariera.zoznam.sk) shows in its public **category listings
for one Slovak region**, and read single postings. Public pages, no authentication, **zero
runtime dependencies**: it runs with just `bun`. Applying happens on Kariéra.sk, which this skill
never touches.

By default the two IT categories are read: `informatika-sprava-systemov` (infrastructure and
system administration) and `informatika-software`. On 2026-11-26 the Bratislava region listed 19
and more than 60 offers there; many come from recruitment agencies (Grafton, Manpower) and many are in
Slovak. Some are taken over from the Slovak labour offices (Úrady práce).

## ⚠️ Use with care

- `robots.txt` (checked 2026-11-26) disallows the portal's keyword search (`/*?q=*`), `/rss/`,
  `/export/`, `/sk/`, `/en/` and the English pages (`/job-offers/`, `/job-offer/`…),
  `/redirect.php` and the account pages. The listings `/pracovne-ponuky/<category>/<region>`
  (with `?od=` pagination) and the postings `/pracovna-ponuka/` are allowed. No Crawl-delay; the
  CLI waits 2 s between its own requests.
- Terms (`/obchodne-podmienky`): no clause on automated access; the database rights clauses cover
  the CV database (employers). For one person's own job search only: a few runs a day, never
  redistribute listings. Your own responsibility.
- **No portal keyword search** is ever sent: `--query` filters the titles client-side.

## Commands

### Search

```bash
bun run .agents/skills/kariera-search/cli/src/cli.ts search -l "<place>" [-c <categories>] [-q "<words>"] [--jobage n] [--page n] [--max-pages n] [--limit n] [--format json|table|plain]
```

Query syntax: client-side title filter, not a portal search: every word must appear in the title
(accents and case ignored, any order); quotes are ignored, no phrase match, no OR.

| Flag | Description |
|------|-------------|
| `--location`, `-l` | Required. Slovak region town(s) or region names, comma-separated, accents optional: `Bratislava`, `Trnava`, `Nitra`, `Trenčín`, `Žilina`, `Banská Bystrica`, `Prešov`, `Košice`, `Bratislavský kraj`… The whole region's listing is read (Senec, Pezinok… included). Any other place is refused (`BAD_ARG`). |
| `--category`, `-c` | Listing categories, comma-separated. Default `informatika-sprava-systemov,informatika-software`; also `telekomunikacie`, `bankovnictvo`, `ekonomika-financie-uctovnictvo`, `vrcholovy-manazment`, `manazment-kvality`, `zakaznicka-podpora`. |
| `--query`, `-q` | Client-side title filter (see Query syntax). |
| `--jobage` | Keep cards dated within n days; the next page of a category is read only while a whole page is that fresh. |
| `--page` | First listing page, 1-indexed, 30 cards each (default 1). |
| `--max-pages` | Pages per category at most with `--jobage` (default 3). |
| `--limit`, `-n` | Cap results (client-side). |
| `--format` | `json` (default), `table`, `plain`. |

### Detail

```bash
bun run .agents/skills/kariera-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

Accepts the offer id (`1559635`) or a posting URL (`kariera.zoznam.sk/pracovna-ponuka/1559635/<slug>`).
The CLI requests `/pracovna-ponuka/<id>`. A missing posting answers 404: exit 1, `NOT_FOUND`.

## Examples

```bash
bun run .agents/skills/kariera-search/cli/src/cli.ts search -l Bratislava --jobage 2 --format table
bun run .agents/skills/kariera-search/cli/src/cli.ts search -l Bratislava -q "project manager" --format table
bun run .agents/skills/kariera-search/cli/src/cli.ts search -l Bratislava -c bankovnictvo,vrcholovy-manazment --format plain
bun run .agents/skills/kariera-search/cli/src/cli.ts search -l "Trnava,Nitra" --jobage 7 --limit 20
bun run .agents/skills/kariera-search/cli/src/cli.ts detail 1559635 --format plain
```

## Output

| Format | Content |
|--------|---------|
| `json` | `{meta:{count,page,total,hasMore,requests}, results:[{id,title,company,location,date,url,employmentType,homeOffice,salary,summary,categories}]}` |
| `table` | id, date, title, company, location |
| `plain` | one block per offer |

`total` counts the distinct offers read before the `--jobage`/`--query` filters; `hasMore` is true
when a listing had further pages that were not read. `date` is the card date (publication or
last refresh: agencies refresh their offers often); `detail` gives `date` = "Dátum zverejnenia"
(first publication), plus `employmentType` ("plný úväzok" = full time), `salary`, `category`,
`description` (sections as `## <title>`), `source` ("Úrady práce" for labour-office offers),
`validThrough` ("Dátum ukončenia ponuky", labour-office offers only) and `isActive`; `applyUrl`
is null.

## Notes

- Sponsored carousel cards (`offer highlight`, through `/redirect.php`) are skipped.
- An offer listed in several categories appears once, with every category in `categories`.
- Salary is shown as on the card ("od 1050 EUR/Mesiac" = from 1050 EUR a month).
