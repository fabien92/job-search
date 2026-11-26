# Search Queries for Job Scraper


## Installed portal CLIs (primary for `/scrape`)

`/scrape` discovers every portal skill under `.agents/skills/*/SKILL.md` and runs its CLI first. None ship with AI Job Search: copy the ones for your market from [community-portals](https://github.com/ai-job-search-dev/community-portals) (e.g. `linkedin-search`, `freehire-search` under `portals/global/`), or build one with `/add-portal`. You do **not** need a matching `site:` line below for those CLIs to run.

The `site:` query templates in this file are the **WebSearch fallback** — for portals without a CLI, company career pages, or when a CLI fails.

**Language scope:** write every query category in every language listed in your CLAUDE.md Languages table (typically 1-2, sometimes more). A posting requiring a language you have *not* declared, as a job condition, is excluded before scoring; a posting requiring a *higher level* than you declared in a language you *do* work in is flagged for your own judgment, not excluded — see `04-job-evaluation.md`'s Language Gate, the single source of truth for this rule. Translate each category's keywords rather than machine-translating word-for-word (e.g. "Frontend Developer" -> "Desarrollador Frontend", not a literal word-for-word translation) if you work in more than one language.

## Search Sites

Primary:
- **linkedin.com/jobs** - covered by the installed `linkedin-search` CLI (`.agents/skills/linkedin-search/`); location Vienna, Austria
- **karriere.at** - Austria's largest job board (WebSearch fallback until a portal CLI is added)
- **stepstone.at** - StepStone Austria (WebSearch fallback)
- More boards to be added later (the user will list them; check community-portals or use `/add-portal`)

Secondary (company career pages via Google):
- Direct Google searches with `site:` filters for target companies (to be defined later)

## Query Categories

Queries are grouped by priority and written in **English and German** (the candidate's working languages for the Vienna market; French is declared but irrelevant for search there). Combine each query with location terms (Wien / Vienna) where the site supports it.

Each priority has two kinds of block. **Plain terms** blocks are what the portal CLIs consume: one term per line, one CLI call per term, no `OR`, no `site:` prefix, and no location. **WebSearch-only** blocks are Google syntax for the fallback path and are never passed to a CLI.

### Priority 1: Technical delivery & project leadership

Steering technical delivery without being a developer - strongest and most desired direction.

#### Plain terms (portal CLIs)

```
IT Delivery Manager
Technical Project Manager
Tech Lead
IT Project Manager
Delivery Lead
Technischer Projektleiter
IT Projektleiter
```

#### WebSearch-only (`site:` fallback)

```
site:karriere.at "IT Delivery Manager" Wien
site:karriere.at "Technical Project Manager" Wien
site:karriere.at "IT Projektleiter" Wien
site:stepstone.at "Technical Project Manager" Wien
site:linkedin.com/jobs "Delivery Manager" Vienna Austria
```

### Priority 2: IT production, support & service management

Run/production ownership, incident management, ITIL.

#### Plain terms (portal CLIs)

```
IT Service Delivery Manager
IT Support Manager
Application Support Manager
IT Operations Manager
Service Manager ITIL
Leiter IT Support
```

#### WebSearch-only (`site:` fallback)

```
site:karriere.at "IT Service Manager" Wien
site:karriere.at "IT Support" Teamleiter Wien
site:stepstone.at "Service Delivery Manager" Wien
site:linkedin.com/jobs "IT Operations Manager" Vienna Austria
```

### Priority 3: Technical solution & AI-adjacent roles

Adjacent roles bridging business and technology, including AI initiatives.

#### Plain terms (portal CLIs)

```
Technical Solution Manager
Solution Manager
Technical Program Manager
AI Project Manager
AI Delivery Manager
Technical Account Manager
```

#### WebSearch-only (`site:` fallback)

```
site:karriere.at "Solution Manager" Wien
site:karriere.at "AI" Projektmanager Wien
site:linkedin.com/jobs "Technical Program Manager" Vienna Austria
site:linkedin.com/jobs "AI Project Manager" Vienna Austria
```

### Priority 4: Broader - finance IT, PMO, international organisations

Wider net: domain (finance/derivatives, migrations, Oracle) and sectors (banks, UN/OSCE/IAEA/OPEC agencies in Vienna, NGOs).

#### Plain terms (portal CLIs)

```
PMO
IT Release Manager
Change Manager IT
Oracle
Scrum Master
```

#### WebSearch-only (`site:` fallback)

```
site:karriere.at "Release Manager" Wien
site:karriere.at PMO IT Wien
site:linkedin.com/jobs "IT Project Manager" bank Vienna
site:unjobs.org "Information Technology" Vienna
```

## Location Filter

Home base: Vienna (relocating there as soon as a job is signed).
- **Ideal:** Vienna (Wien) and remote/hybrid roles based in Vienna
- **Acceptable:** Vienna surroundings reachable by public transport (Schwechat, Mödling, Klosterneuburg)
- **Borderline (fallback only):** Bratislava (~1h by train/bus) - surface but flag
- **Last resort:** Budapest (~2h40) - would require a local flat; surface only if clearly a strong fit
- **Too far:** anywhere else in Austria (Graz, Linz, Salzburg...) or other countries, unless fully remote

## Language Filter

Your working languages and levels are in CLAUDE.md's Languages table. When filtering scraped results, apply `04-job-evaluation.md`'s Language Gate: a posting requiring a language you haven't declared at all is excluded; a posting requiring a higher level than you declared in a language you do work in is not excluded, flag it clearly instead (see `job-scraper/SKILL.md`'s Step 3 "Quick Fit Assessment" for how the flag surfaces in `/scrape` output). Postings simply *written* in a language you don't work in, that don't require it on the job, are fine.

## Date Filter

Only include jobs posted within the last 14 days, matching `/scrape` Step 1b.3: use a supported recency filter or filter the returned publication dates client-side. A future application deadline does not bypass this discovery window; `/rank` handles deadline expiry and urgency separately after discovery. If a posting date cannot be determined, include it but flag as "date unknown".

## Adapting Queries

If the user specifies a focus area, select queries from the matching category and also generate 2-3 custom queries for that focus. For example:
- "/scrape [focus_area]" -> relevant category queries + custom focus-specific queries
