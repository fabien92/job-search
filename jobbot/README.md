# JobBot

An unattended job-search assistant that runs on a Mac and talks to you on Telegram. It scans job
portals and company career pages every few hours, filters and scores what it finds, shows you the good
postings one at a time, and prepares your CV when you say `/go`. **It never applies for you**: you send
the application yourself.

JobBot is an addition to [AI Job Search](https://github.com/ai-job-search-dev/ai-job-search), the
Claude Code framework this repository is forked from. The framework's own commands (`/setup`, `/scrape`,
`/rank`, `/apply`, `/interview`, `/outcome`…) keep working as described in the root `README.md`.

**Install it:** follow [`INSTALL.md`](INSTALL.md), step by step.

**Contents:** [How it works](#how-it-works) · [Free mode, without Claude](#free-mode-without-a-claude-subscription) ·
[Telegram](#telegram-your-own-bot) · [Language](#language-of-the-messages) · [Commands](#commands) ·
[Portals and connectors](#portals-and-connectors-included) · [Adding a portal](#adding-a-portal) ·
[Configuration](#what-you-configure) · [Safety](#safety)

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

## Free mode: without a Claude subscription

JobBot runs entirely without Claude, at no cost. In `config/schedule.yaml` set:

```yaml
scoring: rules
```

| | `scoring: claude` | `scoring: rules` (free) |
|---|---|---|
| Needs | Claude Pro or Max, Claude Code | nothing: no account, no token |
| Scanning, filtering, de-duplication | yes | yes, identical |
| Score | Claude reads the posting against your profile | keywords from `criteria.md` (below) |
| Reason shown with the alert | one sentence written by Claude | the title and keywords that matched |
| Contract, remote, salary details | read from the posting | salary only when the portal gives it |
| Rules learnt with `/no <ID> <reason>` | applied by Claude | stored, not applied (use the `Reject` line below) |
| CV on `/go` | variant chosen per posting, text optionally adapted | the `default_variant`, unchanged |
| `/discover`, `/spont` | available | unavailable |
| Queue, `/sent`, reminders, recaps, backup | yes | yes, identical |

The keyword score, out of 100: 35 to start, +30 when the posting's title contains every word of one of
your target titles, +6 for each `Strong` keyword found in the posting (4 at most), +2 for each
`Secondary` keyword (5 at most). A posting whose title matches a target title therefore passes the
default alert threshold of 60. You write those lists, and two optional ones, in `config/criteria.md`:

```markdown
## Scoring profile
- Strong : IT delivery · CI/CD · project manager
- Secondary : python · jira

## Rules mode
- Reject : verhandlungssicher · native German · freelance
- Flag : fließend · befristet
```

A `Reject` term found in a posting rejects it; a `Flag` term keeps it and adds a warning to the alert.
You can switch between the two modes at any time; nothing else changes. Without Claude you also skip
the framework's `/setup`: fill in `private/candidate.yaml`, `private/identity.tex` and the example CV by
hand (`INSTALL.md`, steps 7 and 10).

## Telegram: your own bot

There is no shared bot. Each user creates their own bot with Telegram's **@BotFather** (free, two
minutes) and talks to it in their own chat; nothing passes through anyone else's bot or account. The
bot's token and your chat id go into one file on your Mac, never in the repository:

```
~/.config/jobbot/secrets.env

TELEGRAM_TOKEN=...            the password of your bot, given by @BotFather
TELEGRAM_CHAT_ID=...          the chat the bot writes to and obeys (private chat, or a group of yours)
TELEGRAM_USER_ID=...          optional: the only person obeyed in that chat (recommended in a group)
CLAUDE_CODE_OAUTH_TOKEN=...   only with scoring: claude
```

`INSTALL.md` step 5 shows how to get each value. After changing this file, restart the bot
(`sudo launchctl kickstart -k system/com.jobbot.telegram`, admin account). Messages the bot cannot
deliver (no network, Telegram down) are kept and sent later.

## Language of the messages

The bot speaks English by default. Send it:

```
/lang fr      French
/lang en      English
/lang         shows the current language and the available ones
```

The choice is remembered and also applies to the command menu, the daily recap and, in Claude mode, the
one-line reasons Claude writes. Both names of the four renamed commands always work (`/queue` = `/file`,
`/show` = `/voir`, `/rejects` = `/rejets`, `/company` = `/firma`).

To add a language, copy `locales/en.yaml` to `locales/<code>.yaml` (for example `de.yaml`), translate
the texts on the right of each line, keep the `{placeholders}` as they are, and restart the bot:
`/lang de` then works. A text missing from your file falls back to English.

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

The shipped configuration is a working example for IT delivery roles in Vienna, Bratislava and
Budapest. For another job or another country, change `criteria.md` and `regions.yaml`, turn off the
portals you do not need and add your own (next two sections).

## Portals and connectors included

**Job portals** — one small command-line tool each, in `.agents/skills/<name>/` (its `SKILL.md` says
what the site's `robots.txt` and terms allow). The key is the name used in `queries_per_run`
(`config/schedule.yaml`) and in `/search <key>`.

| Key | Site | Covers | How it is read |
|---|---|---|---|
| `karriere` | karriere.at | Austria | keyword search, per city |
| `derstandard` | jobs.derstandard.at | Austria | keyword search, per city |
| `hays` | hays.at | Austria (staffing agency) | one walk of the listing, filtered by region |
| `randstad` | randstad.at | Austria (staffing agency) | IT listing of the enabled cities |
| `michaelpage` | michaelpage.at | Austria (recruitment agency) | IT listing of Vienna |
| `kariera` | kariera.zoznam.sk | Slovakia | IT listings of the enabled regions |
| `profession` | profession.hu | Hungary | official RSS feed of the IT category |
| `uncareers` | careers.un.org | United Nations, by duty station | one query per city |
| `unido` | careers.unido.org | UNIDO | one query per city |
| `osce` | vacancies.osce.org | OSCE | one walk of the board |
| `opecfund` | careers.opecfund.org | OPEC Fund | one request |
| `jobgether` | jobgether.com | remote jobs open to Europe | one query per English title |
| `linkedin` | linkedin.com | any region, and remote | public listings, low volume, limited runs per day |

Turn a portal off with `0` under `queries_per_run`. Several are specific to IT listings: read the
portal's `SKILL.md` before pointing it at another field.

**Career-page connectors** — for the companies of your list (`companies-seed.md`, `/discover`,
`/accept`). JobBot detects which recruiting software a company's career page uses and, when a connector
exists, reads its postings from the vendor's public feed. The key `companies` (`/search companies`)
runs them.

| Recruiting software | Status |
|---|---|
| Personio | connector (public XML feed of `<company>.jobs.personio.de`) |
| Greenhouse | connector (public job-board API) |
| Lever | connector (public postings API, including the EU instance) |
| Workday, SAP SuccessFactors, SmartRecruiters, Recruitee, softgarden, onlyfy | detected and reported, **no connector**: no documented public feed, or `robots.txt` forbids it (reasons in `scripts/ats/vendors.py`) |

Not included, on purpose: willhaben (its `robots.txt` forbids all automated access), AMS (no read API)
and profesia.sk.

## Adding a portal

A portal has two parts: the command-line tool that reads the site, and its registration in JobBot.

**1. The tool.** With Claude Code, start `claude` in the repository and run the framework's command:

```
/add-portal
```

It asks for the site, checks `robots.txt` and the terms first (and stops if automated access is
forbidden), then writes `.agents/skills/<name>-search/` with a `search` and a `detail` command and tests
that run without the network. Without Claude, copy an existing portal folder that reads a similar site
(a keyword search: `karriere-search`; a plain listing: `randstad-search`; an RSS feed:
`profession-search`) and adapt its `cli/src/` files. Check it by hand:

```bash
bun run .agents/skills/<name>-search/cli/src/cli.ts search --format table
```

**2. The registration.** JobBot must know the portal's name, which countries it covers and how to query
it. These are the places, all short; the way an existing portal is registered is the model:

| File | What to add |
|---|---|
| `jobbot/scripts/prefilter.py` | an entry in `PORTALS` (skill folder, domain, countries); a branch in `plan_queries` (which queries to run for the enabled regions) and one in `search_args` (the tool's arguments) |
| `jobbot/scripts/common.py` | a default number of queries in `SCHEDULE_DEFAULTS["queries_per_run"]` |
| `jobbot/config/schedule.yaml` | the same key under `queries_per_run` |
| `jobbot/bot/logic.py` | the key in `PORTAL_NAMES`, so that `/search <key>` accepts it |
| `jobbot/tests/` | a fixture in `fake_bun.py` and a case in `test_prefilter.py` |

With Claude Code you can paste this instead of doing it by hand:

```
Read jobbot/SPEC.md §7 and how the portal "randstad" is registered in jobbot/scripts/prefilter.py,
jobbot/scripts/common.py, jobbot/config/schedule.yaml, jobbot/bot/logic.py and jobbot/tests/.
Register the portal .agents/skills/<name>-search the same way, with network-free tests. Plan first.
```

**3. The whitelist.** Approve the portal's domain, or JobBot skips it: add a line for it to
`config/sites-seed.md` and run the import of `INSTALL.md` step 9 again, yourself.

**4. Try it.** `JOBBOT_DRY_RUN=1 bash jobbot/scripts/run_scan.sh --site <key>` sends `[TEST]` alerts only.

Adding a career-page connector for another recruiting software works the same way in
`jobbot/scripts/ats/` (`vendors.py` for the detection, `connectors.py` for the feed), provided the
vendor documents a public feed and its `robots.txt` allows it.

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
