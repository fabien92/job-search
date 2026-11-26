---
name: un-careers-search
version: 1.0.0
description: >
  Use this skill whenever the user wants to search United Nations Secretariat job openings
  on UN Careers (careers.un.org, Inspira): UN jobs in Vienna (UNOV, UNODC, UNOOSA,
  UNCITRAL…), Geneva, New York, Bonn or any duty station, or look up a specific UN job
  opening. Trigger phrases: UN jobs, United Nations careers, UN vacancies, Inspira, UN job
  opening, international organisation jobs Vienna; German: UNO Jobs, Stellen bei den
  Vereinten Nationen, UNO-City Wien Stellenangebote; French: offres d'emploi ONU, postes
  aux Nations Unies.
context: fork
enabled: true  # set to false to keep this portal installed but have /scrape skip it
allowed-tools: Bash(bun run .agents/skills/un-careers-search/cli/src/cli.ts *)
---

# UN Careers Search Skill

Search live job openings of the **UN Secretariat** on **careers.un.org** (the public face of
Inspira): headquarters, offices away from headquarters (UNOV/UNODC in Vienna), regional
commissions and field missions. It reads the same public JSON API as the site. No
authentication, no API key, **zero runtime dependencies** — it runs with just `bun`.

Not covered: UN agencies with their own recruitment systems (IAEA, UNIDO, CTBTO, UNHCR,
UNICEF, UNDP…).

## Use with care

careers.un.org serves no robots.txt (the path returns the app shell), so nothing is
disallowed. The UN website terms of use could not be read during reconnaissance (HTTP 403
to automated fetches) — read them yourself before relying on this skill. This skill is for one
person's own job search: **keep volume low** (a few requests per run), never redistribute
listings, no commercial or bulk use. It only reads: it never calls the endpoint that counts
page views, and applying happens on inspira.un.org with your own account.

## Commands

### Search job openings

```bash
bun run .agents/skills/un-careers-search/cli/src/cli.ts search [-q "<keywords>"] [-l "<duty station>"] [flags]
```

Query syntax: the keyword is matched as one phrase as typed; double quotes and `OR` are taken
literally (both returned 0 results in testing), so send one plain term per call.

| Flag | Description |
|------|-------------|
| `--query`, `-q` | Keyword phrase, e.g. `"information technology"`. |
| `--location`, `-l` | Duty station: `Vienna` / `Wien`, `Geneva`, `New York`, `Bonn`… |
| `--jobage <days>` | Posted within N days: portal filter (1/7/30 days) plus an exact client-side check. |
| `--page <n>` | 1-indexed; 100 results per page, newest first. |
| `--limit`, `-n` | Cap results emitted (client-side). |
| `--format` | `json` (default), `table`, `plain`. |

At least one of `--query` / `--location` is required. The whole board holds a few hundred
openings, so a location-only search (`-l Vienna`) is the usual call.

### Job opening detail

```bash
bun run .agents/skills/un-careers-search/cli/src/cli.ts detail <jobId|url> [--format json|plain]
```

Accepts a numeric id (`289094`) or a `careers.un.org/jobSearchDescription/<id>` URL.

## Examples

```bash
# Every open UN Secretariat job in Vienna
bun run .agents/skills/un-careers-search/cli/src/cli.ts search -l Vienna --format table
# IT openings in Vienna posted this week
bun run .agents/skills/un-careers-search/cli/src/cli.ts search -q "information technology" -l Wien --jobage 7
# Project management roles anywhere
bun run .agents/skills/un-careers-search/cli/src/cli.ts search -q "project management" --format plain
# Geneva, newest 10
bun run .agents/skills/un-careers-search/cli/src/cli.ts search -l Geneva --limit 10
# Full posting
bun run .agents/skills/un-careers-search/cli/src/cli.ts detail 289094 --format plain
```

## Output

| Format | Content |
|--------|---------|
| `json` | `{meta:{count,page,total,hasMore}, results:[{id,title,company,location,date,deadline,url,grade,category,contract,jobFamily,…}]}` |
| `table` | id, title, grade, entity, duty station, posted, deadline |
| `plain` | one block per opening |

`company` is `United Nations – <department/office>`; `date` and `deadline` are Vienna
calendar dates (a New York midnight deadline shows as the next day). `detail` adds
`description`, `applyUrl` (inspira.un.org only), `validThrough`, `isActive`.

## Notes

- Grades: `P-x` professional, `G-x` general service (local recruitment), `NO-x` national
  officer, `CON` consultant / individual contractor, `I-1` internship.
- General Service (G) posts in Vienna usually require local residence or recruitment;
  P posts are international.
- Postings are in English (some also in French).
- The API answers `{status:1, data:…}`; any other status is reported as an error.
