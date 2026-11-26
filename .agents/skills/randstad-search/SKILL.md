---
name: randstad-search
version: 1.0.0
description: >
  Use this skill whenever the user wants to list job offers from the staffing agency Randstad in
  Austria on www.randstad.at (permanent placements and temporary staffing in Vienna, Graz, Linz,
  Salzburg or the whole of Austria), or look up a specific Randstad posting by job id.
  Trigger phrases: Randstad jobs Austria, Randstad Vienna jobs, staffing agency jobs Wien;
  German: Randstad Stellenangebote, Randstad Jobs Wien, Zeitarbeit Wien, Personalvermittlung
  Randstad Österreich; French: offres Randstad Autriche, agence d'intérim Vienne.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/randstad-search/cli/src/cli.ts *)
---

# Randstad Austria Search Skill

List live openings that **Randstad Austria** (www.randstad.at) publishes in Austria: permanent
placements with a client ("Festanstellung") and temporary staffing ("Zeitarbeit",
Arbeitskräfteüberlassung). Public pages, no authentication, **zero runtime dependencies**: it
runs with just `bun`. Applying happens on the Randstad site, which this skill never touches.

Most openings are blue-collar (construction, warehouse, production); office, IT and project
roles are a minority (Vienna: 39 openings, 6 in EDV/IT for all of Austria on 2026-11-26).

## ⚠️ Use with care

- `robots.txt` (checked 2026-11-26) allows everything except the search parameters and filters
  (`/*search=`, `/*/qt-`, `/*/km-`, `/*/postcode-`, `/*/sa-`, `/*/sd-`, `/*/sh-`, `/*/sm-`,
  `/*/?id=*`, `/*/mpage-`), `/*/apply/`, `/*/bewerben/` and `/node/`. **There is therefore no
  keyword search**: the CLI walks the public city listings (`/jobs/wien/wien/`, `…/page-2/`),
  or one Berufsfeld's listing (`/jobs/s-edv-it/wien/wien/`, allowed by robots.txt), and reads
  postings at `/jobs/<slug>_<id>/`. No Crawl-delay is
  set; the CLI waits 2 s between its own requests.
- Terms of use (www.randstad.at/nutzungsbestimmungen/ §5): visitors must be genuine job seekers
  and use the site for no other purpose; no clause on automated access. For one person's own job
  search only: a few runs a day, never redistribute listings. Your own responsibility.

## Commands

### Search

```bash
bun run .agents/skills/randstad-search/cli/src/cli.ts search [-l "<place>"] [-s <berufsfeld>] [--jobage n] [--page n] [--limit n] [--format json|table|plain]
```

| Flag | Description |
|------|-------------|
| `--location`, `-l` | `Wien` (also `Vienna`, `Vienne`), `Graz`, `Linz`, `Salzburg`; comma-separated walks each listing once. Any other place is refused (`BAD_ARG`). Without it, the whole of Austria (`/jobs/`, ~18 pages). |
| `--specialism`, `-s` | One Berufsfeld only: `edv-it` (IT) walks `/jobs/s-edv-it/wien/wien/` instead of `/jobs/wien/wien/` (2 openings instead of 39 in Vienna on 2026-11-26). Slugs as in the sitemaps (`sitemap-joblistings-<slug>.xml`); any other value is refused (`BAD_ARG`). |
| `--jobage` | Max days since "veröffentlicht am" (client-side; every page is still read: the list is not in date order). |
| `--page` | One page of 30 (1-indexed). Default: every page (at most 25 per listing). |
| `--limit`, `-n` | Cap results (client-side). |
| `--format` | `json` (default), `table`, `plain`. |

Query syntax: none — there is no `--query` (robots.txt disallows the portal's search parameters);
filter the titles yourself (or let the caller's rules do it).

### Detail

```bash
bun run .agents/skills/randstad-search/cli/src/cli.ts detail <id|url> [--format json|plain]
```

Accepts the job id (`47720442`) or a www.randstad.at posting URL (`/jobs/<slug>_<city>_47720442/`).
The CLI requests `/jobs/job_wien_<id>/`, which Randstad redirects (301) to the canonical slug
whatever the city. A closed opening answers 410: exit 1, `NOT_FOUND`.

## Examples

```bash
bun run .agents/skills/randstad-search/cli/src/cli.ts search -l Wien --jobage 14 --format table
bun run .agents/skills/randstad-search/cli/src/cli.ts search -l "Wien,Graz" --format plain
bun run .agents/skills/randstad-search/cli/src/cli.ts search -l Wien -s edv-it --format plain
bun run .agents/skills/randstad-search/cli/src/cli.ts detail 47720442 --format plain
```

## Output

| Format | Content |
|--------|---------|
| `json` | `{meta:{count,page,total,hasMore}, results:[{id,title,company,recruiter,location,date,url,employmentType,homeOffice,salary,summary}]}` |
| `table` | id, date, title, location |
| `plain` | one block per opening |

`company` is always **null**: Randstad does not name its client. `recruiter` is `"Randstad"`.
`salary` is the card's figure ("€4,500 pro monat", "€3,000 - €4,000 pro monat"). `detail` adds
`hours` ("Full-Time"), `specialism` (Berufsfeld, e.g. "Lager, Logistik & Transport"),
`reference` (Referenznummer), `validThrough` ("gültig bis") and `description` (the posting text,
preceded by one line saying it comes from Randstad for an unnamed client); `applyUrl` is null.

## Notes

- Postings are almost all in German; dates are German with Austrian month names ("Jänner").
- "Zeitarbeit" means employment by Randstad, leased to the client: decide on it explicitly.
- `/jobs/wien/` answers 301 to `/jobs/wien/wien/`; page 1 has no `page-1/` suffix.
- Randstad's own vacancies ("Karriere bei Randstad") appear in the same listings.
