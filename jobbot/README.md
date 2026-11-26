# JobBot

An unattended job-search assistant that runs on a Mac and talks to you on Telegram. It scans job
portals and company career pages every few hours, filters and scores what it finds, shows you the good
postings one at a time, and prepares your CV when you say `/go`. **It never applies for you**: you send
the application yourself.

JobBot is an addition to [AI Job Search](https://github.com/ai-job-search-dev/ai-job-search), the
Claude Code framework this repository is forked from. The framework's own commands (`/setup`, `/scrape`,
`/rank`, `/apply`, `/interview`, `/outcome`…) keep working as described in the root `README.md`.

**Install it:** follow [`INSTALL.md`](INSTALL.md), step by step.

## How it works

```
 every 4 h (launchd)                                                     you, on Telegram
┌──────────────┐   ┌───────────┐   ┌──────────────┐   ┌─────────────┐   ┌───────────────────────┐
│ portal CLIs  │──▶│ pre-filter│──▶│   scoring    │──▶│ post-process│──▶│ one posting at a time │
│ career pages │   │ + de-dup  │   │ Claude/rules │   │  + queue    │   │ /go  /no  /sent       │
└──────────────┘   └───────────┘   └──────────────┘   └─────────────┘   └───────────────────────┘
   scripts            scripts        the only AI step      scripts          CV PDF + posting PDF
```

1. **Scan.** Small command-line tools (one per job board, in `.agents/skills/`) and connectors for
   common recruiting systems (Personio, Greenhouse, Lever) list new postings. Only sites you approved
   are contacted, and a portal is skipped when its `robots.txt` forbids automated access.
2. **Pre-filter.** Scripts drop excluded titles, companies, regions, internships, old postings and
   duplicates (including the same job reposted under a slightly different title). No AI is involved.
3. **Score.** Each remaining posting gets a score from 0 to 100, in one of two modes
   (`scoring` in `config/schedule.yaml`):

   | Mode | Needs | How |
   |---|---|---|
   | `claude` | a Claude subscription and Claude Code | A sandboxed, budget-capped `claude -p` run reads each posting and scores it against your profile and your rejection rules. It cannot run commands or reach the web. |
   | `rules` | nothing | A keyword score from `config/criteria.md`. Free, no account, no AI. |

4. **Alert.** Postings above `alert_threshold` go to a queue; the bot shows the best one. You answer
   `/go` (prepare it), `/no` (reject, optionally with a reason that becomes a rule) or let it wait.
5. **Prepare.** `/go <ID>` compiles the CV variant chosen for the posting and sends it with a PDF copy
   of the posting. In `claude` mode the headline, profile and skill order may be adapted to the
   posting, inside strict limits (see "Safety").
6. **Follow up.** After `/sent <ID>` the application is recorded in the tracker; you get a reminder
   after 10 days without an answer, a daily recap and a weekly report. State is backed up every night.

## Commands

| Command | Effect |
|---|---|
| `/go <ID> [ID…]` | Prepare the application: CV PDF + posting PDF |
| `/sent <ID>` | You applied: tracker updated, next posting shown |
| `/no <ID> [reason]` | Reject; the reason, if any, becomes a rejection rule |
| `/cancel <ID>` | Give up a prepared application |
| `/reply <ID> yes\|no` | An answer arrived; reminders stop |
| `/queue`, `/show <n>` | Postings waiting; show one of them now |
| `/pending` | Prepared but not sent yet |
| `/company <name>` | Your applications at one company |
| `/search <site\|all>` | Scan now |
| `/sites`, `/allow <n>`, `/deny <n>` | Approve or refuse newly proposed sites |
| `/discover <region>`, `/companies`, `/accept`, `/reject` | Find and approve target employers (Claude mode) |
| `/spont <company>` | Draft a spontaneous application, never sent (Claude mode) |
| `/block <company>`, `/blocked`, `/unblock <n>` | Exclude a company from every search |
| `/region on\|off <name>`, `/regions` | Search area |
| `/rules`, `/rule del <n>` | Your rejection rules |
| `/status`, `/health`, `/rejects` | Last run, self-check, what was dropped |
| `/lang en\|fr` | Language of the bot's messages |
| `/help` | The full list |

The bot's messages exist in English and French (`locales/`). Everything else — code, configuration
and documentation — is in English.

## What you configure

| File | Content |
|---|---|
| `config/criteria.md` | Titles, keywords, exclusions, language/contract rules, scoring keywords |
| `config/regions.yaml` | Cities and countries, on or off |
| `config/schedule.yaml` | Scoring mode, frequency, threshold, budgets, queries per portal, times |
| `config/rejection-rules.md` | Your own rules, grown by `/no <ID> <reason>` |
| `config/sites-seed.md` → `config/sites.yaml` | The sites JobBot may contact |
| `config/companies-seed.md` | Starting list of target employers |
| `commands/jobbot-*.md` | The prompts of the Claude runs |
| `~/.config/jobbot/secrets.env` | Telegram and Claude tokens (outside the repository) |
| `private/` | Your identity and profile (gitignored) |
| `documents/cv/jobbot/` | Your CV in blocks (gitignored); example in `examples/cv/` |

The shipped configuration is a working example for IT delivery roles in Vienna, Bratislava and Budapest
with thirteen portals: karriere.at, derStandard, Hays, Randstad and Michael Page Austria, Kariéra.sk,
Profession.hu, UN Careers, UNIDO, OSCE, OPEC Fund, Jobgether and LinkedIn. For another market, build
portals with the framework's `/add-portal` command, register them in `scripts/prefilter.py` (`PORTALS`)
and set the others to `0` under `queries_per_run`.

## Safety

- **One owner.** The bot obeys a single Telegram chat (optionally a single user) and ignores everyone else.
- **Nothing is sent to employers.** JobBot prepares files; you apply.
- **Site whitelist.** Scripts and Claude can only reach approved domains. Only you can change the list:
  Claude is denied write access to it, and new sites wait for your `/allow`.
- **Confined AI.** Scheduled Claude runs use `--permission-mode dontAsk`, a spending cap, no shell, and no
  web access for scoring and CV adaptation. Secrets are removed from their environment.
- **Postings are untrusted.** Every posting passes `tools/posting_guard.py` (hidden text, instructions
  aimed at an AI) before scoring, and the prompts treat posting content as data, never as instructions.
- **Guarded LaTeX.** A CV adaptation may only redefine a fixed list of text macros. It is parsed against
  a command whitelist before LaTeX runs, shell escape is off, and a failure falls back to the unmodified
  variant.
- **Your data stays local.** Profile, CV, applications and bot state are gitignored. The optional
  nightly backup goes to a repository you own: keep it private.

Using a job board through a script is your responsibility: read each portal's `SKILL.md` for what its
terms allow, keep the volumes low, and never redistribute listings.

## Layout

```
jobbot/
  INSTALL.md            installation guide
  SPEC.md               full specification
  bot/                  Telegram bot (long polling)
  scripts/              scan pipeline, scoring, CV build, queue, follow-ups, backup, monitoring
  scripts/ats/          career-page connectors (Personio, Greenhouse, Lever)
  commands/             prompts of the headless Claude runs (copied to .claude/commands/)
  config/               your criteria, regions, schedule, whitelist
  examples/cv/          fictional block CV to start from
  launchd/              service files and how to install them
  locales/              bot messages (en, fr)
  tests/                unit tests, no network needed
  state/                runtime state (gitignored)
```

## Tests

```bash
jobbot/.venv/bin/python -m unittest discover -s jobbot/tests -p 'test_*.py'
```

## Limits

- macOS only (launchd, a few macOS tools in the shell wrappers).
- The rules mode ranks by keywords: it cannot read a posting's real requirements, judge seniority, or
  spot a language requirement you did not list under `Reject` in `criteria.md`.
- Portals break when a site changes its pages; `/status` and the daily recap report a portal that
  returns nothing for several days.

## Licence and credits

MIT, like the framework. Framework © Mads Lorentzen and the AI Job Search contributors; JobBot was
built on top of it with Claude Code, from the specification in `SPEC.md`.
