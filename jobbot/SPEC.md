# JobBot — Full specification

Job-search bot built on the `ai-job-search` repository (upstream: `ai-job-search-dev/ai-job-search`).
This file is the design reference: Claude Code must read it before changing the implementation. To install and use JobBot, read `README.md` and `INSTALL.md` in this folder.
Location: `~/ai-job-search/jobbot/SPEC.md` (macOS user `jobbot`). `jobbot` is the example name of the dedicated macOS user, used throughout this document.

---

## 0. Non-negotiable principles

1. **Token economy.** Claude only does what requires judgment: scoring a posting, choosing/adapting a CV variant, drafting a spontaneous e-mail, identifying a contact. Everything else (deduplication, LaTeX compilation, PDF conversion, filing, CSV, Telegram, backup, allowlist) is done by **deterministic scripts**, with no call to Claude.
2. **Claude writes its output to files, then stops.** The script that launched it runs the post-processing. No continuous folder watching.
3. **No e-mail or application is ever sent automatically.** The user checks and sends everything personally.
4. **No site is accessed for the first time without explicit approval** (allowlist).
5. **A posting is never presented twice.**
6. **Every link offered (posting, site, domain) is clickable in the Telegram message.**
7. **Change upstream files as little as possible.** New code goes in `jobbot/` and in `.agents/skills/<portal>/`. Upstream files that may be modified: profile (`.claude/skills/job-application-assistant/01-candidate-profile.md` etc., meant for customisation), `search-queries.md`, `.claude/settings.json` and `tools/security_guards.py` (one line per portal, as `/add-portal` requires). For everything else, create dedicated commands (`.claude/commands/jobbot-*.md`) that reuse the upstream tools.
8. **Every write to a state file goes through a lock** (one writer at a time: Telegram bot, scheduled search, backup).

---

## 1. Environment

- Mac, dedicated standard user `jobbot` (not an admin). Repository: `~/ai-job-search`.
- **Private** GitHub repositories: `ai-job-search` (code + config, `upstream` = upstream repository) and `jobbot-data` (backup of the sensitive data).
- Claude Code (subscription), non-interactive authentication through `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`, valid for 1 year). Do not use `--bare` (it ignores this token and the project commands).
- LaTeX: system installation (MacTeX, `/Library/TeX/texbin`) or TinyTeX installed for `jobbot`. `jobbot` has no `sudo`: if a LaTeX package is missing, **do not try `tlmgr`**, send a Telegram alert with the package name.
- Scripts launched by `launchd` have a minimal PATH: **always set PATH explicitly** (`$HOME/.local/bin:$HOME/.bun/bin:/Library/TeX/texbin:/usr/bin:/bin:/usr/sbin:/sbin`).
- Secrets in `~/.config/jobbot/secrets.env` (mode 600), never in Git: `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, `CLAUDE_CODE_OAUTH_TOKEN`.

---

## 2. Directory tree

```
ai-job-search/
├── jobbot/
│   ├── SPEC.md
│   ├── config/                 # versioned, editable by the user
│   │   ├── criteria.md         # search and scoring criteria
│   │   ├── regions.yaml        # enabled / disabled regions
│   │   ├── rejection-rules.md  # rejection rules, extended by /no
│   │   ├── sites.yaml          # allowlist: allowed / denied / pending
│   │   └── schedule.yaml       # frequencies, caps, time of the report
│   ├── scripts/                # deterministic scripts (Python 3, stdlib preferred)
│   ├── bot/                    # Telegram bot (python-telegram-bot, venv jobbot/.venv)
│   ├── launchd/                # .plist templates
│   └── state/                  # GITIGNORED — runtime data
│       ├── companies.csv       # target companies, recruitment software, status
│       ├── contacts.csv        # contacts for spontaneous applications
│       ├── pending.json        # postings in /go without /sent
│       ├── postings/<ID>.md    # cleaned posting archived at scoring time (for /go)
│       ├── events.jsonl        # /go, /sent, /cancel (weekly report)
│       ├── telegram_msgs.json  # ids of the messages sent (for deletion)
│       ├── offer_queue.json    # V5: posting queue (only one shown at a time); -test: T… IDs
│       ├── followups.json      # V5: follow-up reminders already sent (reference date); -test: T… sends and reminders
│       ├── blocked_hosts.log   # hosts refused by the sandbox
│       └── runs/               # JSON output of each run + logs
├── job_scraper/seen_jobs.json  # upstream — all postings seen (gitignored)
├── job_search_tracker.csv      # upstream — application tracker (gitignored)
└── documents/applications/<company>_<role>/   # upstream — archive per application
```

Add to `.gitignore`: `jobbot/state/`, `jobbot/.venv/`. Do not add a negation rule (`!…`): `security_guards.py` refuses them.

---

## 3. Criteria

Source of truth: `jobbot/config/criteria.md` and `jobbot/config/regions.yaml`. Summary:

- **Roles**: broad within IT, without overreaching. **Excluded**: Head of, Director, VP, CTO, CIO. *Leiter/Leitung* **kept** (to be observed).
- **Location**: regions enabled in `regions.yaml` (initially: Vienna only), on-site, hybrid or remote; **plus** 100% remote roles anywhere in the world **provided the posting accepts a candidate based in Europe / in Vienna**. Reject "US only", "must reside in <country outside Europe>", incompatible time zones.
- **Language**: English; German up to B2. Reject if German C1/C2, *verhandlungssicher* or *Muttersprache* is required. *Fließend* / *sehr gute Deutschkenntnisse*: keep, flag "German to check".
- **Contract**: permanent (*unbefristet*), part-time (*Teilzeit*), fixed-term ≥ 12 months (*befristet*, *Karenzvertretung*). Fixed-term with no stated duration: keep, flag "duration unknown". Fixed-term < 12 months: reject. Freelance / *Werkvertrag* / contractor: reject for now but **record with the reason `freelance`** (picked up again in V6).
- **Excluded**: internships (*Praktikum*, *Werkstudent*, internship, trainee, *gyakornok*, *stáž*); the companies Deloitte, PwC, EY, KPMG, Accenture, McKinsey, BCG, Bain.
- **Recruitment agencies Hays and Randstad (V4)**: their lists mix all professions; `prefilter.py` (class `Rules`, `AGENCY_TITLE_EXCLUSIONS`) discards, at zero tokens and for these two sites only, the non-IT titles: *Buchhalt…* (including *Bilanzbuchhalter*), *Elektr…*, *Assistenz* / *Assistent* / assistant, legal, tax, *Steuer…* except *Steuerung* (*Projektsteuerung* stays). Reason `not_it`, hidden in `/rejets`. List drawn from the review of 2026-11-26, to be extended in the code.
- **Sector**: no filter.
- **Salary**: no filter. Record the displayed amount as is. No conversion (the user handles it).
- **Freshness**: postings from the last 24–48 h, in addition to the duplicate check.
- **Scoring**: 0–100 against the profile (strengths, secondary skills, missing requirements; "required" weighs more than "nice to have"), then `rejection-rules.md`. Alert threshold in `schedule.yaml` (initially: 60), adjusted with the user.

---

## 4. Deduplication (scripts, zero tokens, BEFORE Claude reads anything)

Order, from cheapest to most expensive:
1. **Site identifier**: key `<site>:<id>` (e.g. `karriere:10037361`, `linkedin:4123…`).
2. **Employer URL** (application page at the employer / its recruitment software), cleaned: no tracking parameters (`utm_*`, `ref`, `src`, `trk`…), no trailing `/`, host in lowercase.
3. **Normalised company + title + location**:
   - lowercase, NFKC, accents kept for display but key without accents;
   - remove gender markers: `(m/w/d)`, `(w/m/x)`, `(f/m/d)`, `(m/f/d)`, `(all genders)`, `(w/m/d)`, `m/w/d`…;
   - remove legal forms: GmbH, AG, SE, KG, OG, e.U., Ltd, Limited, Inc, LLC, s.r.o., a.s., Kft., Zrt., Nyrt.;
   - remove punctuation, collapse whitespace;
   - location: normalised city (Wien = Vienna = Vienne).
4. Also checked against `job_search_tracker.csv` (upstream) and against duplicates within the same run.

Extend the upstream tools (`tools/scrape_state.py`, `rank_state.norm`) **through a jobbot module** that pre-filters, rather than rewriting their logic. All postings retrieved (kept or rejected) are stored as seen, with the rejection reason.

Residual case: the same posting in English on one site and in German on another → checked at scoring time against the postings of the same company seen over 30 days.

**Republications (V4)**: same company and same city, title slightly reworded ("Senior IT Delivery Manager (m/w/d)" then "IT Delivery Manager – Senior"). The normalised title is compared, with no network access and no tokens, to those of **the same company** seen over 30 days and to those of the same run: words in common (small words ignored), share of the words of the shorter title that are found, similarity of the titles with their words sorted; thresholds in `schedule.yaml` (`republish`). Two different levels on the two sides (Junior / Senior) = two roles. An original discarded only for its age or its region is not used as a reference. A republication is **discarded silently** (no alert, not in `/rejets`) and recorded as seen with the reason `republished` and the original posting (`republished_of`).

---

## 5. Security

- **User `jobbot`** with no admin rights, without the user's personal keychain, without Gmail, without banking access.
- **Claude Code sandbox** enabled in `.claude/settings.local.json` (gitignored):
  `sandbox.enabled: true`, `failIfUnavailable: true`, `allowUnsandboxedCommands: false`, `network.strictAllowlist: true`, `network.allowedDomains` = generated from `sites.yaml`.
- **WebFetch permissions**: `permissions.allow` with `WebFetch(domain:…)` entries generated from `sites.yaml` (the sandbox does not cover WebFetch). WebSearch allowed.
- **Non-interactive execution**: `--permission-mode dontAsk --permission-prompts none` + explicit `allow` rules. Whatever is not allowed is refused and logged.
- **Claude never modifies the allowlist.** The Telegram bot (outside Claude) writes `sites.yaml` and regenerates `settings.local.json` after `/allow`.
- **Postings = untrusted data.** Always run `tools/posting_guard.py` (upstream) before scoring. Never follow a link found in a posting. Look a company up by its name, from its official site.
- **Telegram**: the bot ignores any message whose `chat_id` ≠ `TELEGRAM_CHAT_ID`.
- **Cost cap**: `--max-budget-usd` per run + maximum number of postings scored per run (`schedule.yaml`). Beyond that: stop + alert. When the maximum number of postings is reached, small sites and career pages go before the big portals (karriere, LinkedIn, derStandard, Jobgether), then the most recent first; the rest comes back at the next run (otherwise the undated postings of the OSCE, read once per 24 h, were never scored).

---

## 6. Site allowlist

- **Setup**: the bot generates `jobbot/config/sites-seed.md` (job sites, international organisations, recruitment software, career pages), grouped by category, **with one link per line**. The user deletes the refused lines, validates, then `jobbot/scripts/import_seed.py` fills `sites.yaml`. No Telegram for this step.
- **Afterwards**: an unknown host is refused, recorded in `pending` (with the link of the page that requested it) and never accessed. Grouped recap once a day: numbered list with links. Commands `/allow 1 3-5`, `/allow all`, `/deny 4`. If the whole numbered list has already been handled but new hosts are waiting, `/allow` and `/deny` decide nothing and send back the new numbered list (never a decision on a number that was not displayed). A refused host moves to `denied` and is never offered again.
- **Groups**: the program may propose a wildcard domain (e.g. `*.jobs.personio.de`, `*.myworkdayjobs.com`) **only after checking that it is the real domain of the software** (official domain documented by the vendor). Approved or refused like a site.
- After each change: regenerate `settings.local.json` (sandbox + WebFetch).

---

## 7. Sources

- **V1**: LinkedIn (`linkedin-search` portal from `ai-job-search-dev/community-portals`, no login, low volume), karriere.at (via `/add-portal`).
- **V4**: derStandard Karriere (`jobs.derstandard.at`, connector `derstandard-search`: 1 page of 20 postings per query, relevance order; AGB VI: commercial text mining reserved → private use, low volume); willhaben Jobs **dropped** on 2026-11-25 (robots.txt: "It is expressively forbidden to use spiders, search robots or other automatic methods to access willhaben.at", plus `Disallow: /jobs/suche?*` and `/jobs/webapi/`); StepStone.at **dropped** on 2026-11-25 (Akamai 403 on a search allowed by robots.txt, terms of use §4.3.4: no circumvention); profesia.sk (Bratislava) **dropped** on 2026-11-26 (robots.txt allows the posting pages but forbids `/*search_offers*form=`, `/*export.php`, `/*ajax`; home page and public lists (`/praca/bratislavsky-kraj/`) return a CloudFront 403 to any non-browser client; terms of use not found: no circumvention); Profession.hu done (`www.profession.hu`, connector `profession-search`: official RSS feed of the IT category (`/partner/files/rss-it.rss`, redirected to `stat.profession.hu`), the 20 most recent postings for the whole of Hungary, 1 read per run, no keyword; the city comes from the link (`…-budapest-<id>`), otherwise from the detail page (at most 10 reads, 2 s apart); a posting with no address marked TELECOMMUTE is kept ("Magyarország (távmunka)"); the feed has no date (`pubDate` = generation time): date, address and contract are read from the JSON-LD of the detail page `/allas/<id>`, then the rules are applied a second time (`recheck_after_detail`); robots.txt allows `/allas/` and `/partner/files/`, forbids `*?rss$`, `/en/` and the candidate/employer areas; terms of use (felhasznalasifeltetelek_20201008.pdf §V.3): reading and saving for personal non-commercial use, nothing about automated access → private use, low volume; company named ("Hirdető cég", sometimes an agency); postings mostly in Hungarian and very technical; queried only if `budapest` is enabled in `regions.yaml`; to be stopped if relevance is insufficient); Kariéra.sk done on 2026-11-26 for Bratislava (`kariera.zoznam.sk`, connector `kariera-search`: server-rendered HTML, public lists of the two IT categories (`/pracovne-ponuky/informatika-sprava-systemov/<region>` and `…/informatika-software/<region>`, 30 postings per page, from most recent to oldest, following pages `?od=30`, read only as long as a whole page is recent enough, at most 3 pages per category), 2 s between requests; the same posting is often in both categories, merged on its id; date of the card (publication or refresh, agencies refresh often), the detail page `/pracovna-ponuka/<id>` gives the first publication ("Dátum zverejnenia"), the contract ("Druh pracovného pomeru"), the salary and, for postings taken over from the Úrady práce, the end date; robots.txt forbids keyword search (`/*?q=*`), `/rss/`, `/export/`, `/sk/`, `/en/` and `/redirect.php` (sponsored cards, ignored); terms of use (`/obchodne-podmienky`): nothing about automated access, the protection of the "Databáza" targets the CV database → private use, low volume; many agency postings (Grafton, Manpower) and in Slovak; queried only if `bratislava` is enabled; to be stopped if relevance is insufficient); international organisations in Vienna: UN/Inspira done (`careers.un.org`, connector `un-careers-search`: public JSON API, 1 request per city with no keyword), UNIDO done (`careers.unido.org`, connector `unido-search`: SuccessFactors, about twenty postings, 1 request per city with no keyword), CTBTO **dropped** (SuccessFactors `career2.successfactors.eu`, robots.txt `Disallow: /`), UNODC covered by UN Careers; OSCE done (`vacancies.osce.org`, connector `osce-search`: static HTML, ~45 postings over 5 pages crawled in full for all cities, filter on the connector side; at most once per 24 h (`osce_every_hours`); internships and consultancies (SSA) discarded after the detail page; seconded posts kept and flagged: nomination by the home state required); OPEC Fund done (`careers.opecfund.org`, connector `opecfund-search`: SuccessFactors like UNIDO, fewer than 10 postings, all at the Vienna headquarters (the site only states "AT"), 1 request per scan, with publication date, grade and contract type read from the header table of the detail page; all nationalities eligible); blocked at the reconnaissance stage (pages refused to automated reads, or TLS certificate): IAEA, OPEC, IIASA, ICMPD. Recruitment agencies: Hays Austria done (`www.hays.at`, connector `hays-search`: server-rendered Liferay HTML, ~70 postings in Austria over ~4 pages of 20, crawled in full at each run and filtered on the connector side on the enabled Austrian regions; robots.txt `Crawl-delay: 10` respected between pages and between detail pages; client never named → `company` empty, so neither deduplication by company nor the republication check for these postings; Hays.at does not cover Bratislava or Budapest). Discarded on 2026-11-26: Glassdoor (403 on a search, no circumvention), devjobs.at (Cloudflare challenge; site for developers), jobsinvienna.com (content pages, postings loaded in JavaScript), coolpeople.cz (Czech postings), globe.at (a few postings on onlyfy); how-to-austria.com and avomind.com are lists of companies or agencies (a lead for `/jobbot-discover`), not job sites. Remote work: Jobgether done (`jobgether.com`, connector `jobgether-search`: public JSON API for AI agents `/astroapi/ai/jobs.json`, allowed by robots.txt — `/api/v1/jobs?…` falls under `Disallow: /*?*`; 100% remote postings only, hence subject to the `remote_worldwide` switch and not to the regions; 1 request per EN title with `locations=austria`, sorted by date, stopping at the first postings that are too old; strict filter on the connector side: the posting must name Europe / European Union / EMEA / DACH / CET or Austria, postings with "Anywhere" alone (mostly American employers, 135 out of 199 for "project manager") are discarded; the API gives no description: scoring is done on the fields of the posting (eligibility area, contract, experience, functions, salary), with no detail-page request; the `/offer/` pages are never read (403 to an honest User-Agent, terms of use: automated extraction forbidden); to be stopped if relevance is insufficient). Randstad Austria done (`www.randstad.at`, connector `randstad-search`: server-rendered Drupal HTML; robots.txt forbids keyword search (`/*search=`, `/*/qt-` and the filters) → crawl of the public lists of the IT category ("EDV & IT") for the enabled cities, since 2026-11-26 (`/jobs/s-edv-it/wien/wien/`, connector option `-s edv-it`, allowed by robots.txt; 2 postings that day, against 39 for the full Vienna list `/jobs/wien/wien/`, all off-target in the review of 2026-11-26; the sitemap does not always list the Vienna page, which is public all the same; empty list = 200 with no posting), 30 postings per page, in no date order, 2 s between pages; detail page via `/jobs/job_wien_<id>/` (301 to the detail page, 410 if closed), absolute or relative dates ("vor 1 Tag veröffentlicht"); terms of use §5: reserved for genuine candidates, nothing about automated access; client never named → `company` empty like Hays; mostly blue-collar and temporary roles (Zeitarbeit), to be stopped if relevance is insufficient; Graz, Linz and Salzburg known to the connector, not Bratislava or Budapest). Michael Page Austria done on 2026-11-26 (`www.michaelpage.at`, connector `michaelpage-search`: server-rendered Drupal HTML; robots.txt forbids search (`/search/`), `/job-apply/`, the salary, contract and brand filters, `item_per_pages` and the three-level lists (`*/jobs/*/*/*/`) → crawl of the public IT list for Vienna (`/jobs/information-technology/wien-0`, published in the sitemap, then `?page=1`; 30 postings per page, relevance order; 43 postings on 2026-11-26, mostly senior IT roles at €50–150k: project and delivery managers, architects, SAP consultants, security) or, if the `austria` region is enabled, of the list for the whole of Austria (`…/österreich`); 3 s between requests; the list has no date (the ref. `jn-MMYYYY-…` is the month of creation, not the publication: a ref. 05/2026 published on 2026-07-17) → date, address and remote work read from the JobPosting JSON-LD of the detail page `/job-detail/<slug>/ref/<ref>`, then the rules are applied a second time (`recheck_after_detail`); the detail page requires its slug (404 otherwise, like a closed posting): the connector receives the URL, not the ref. (`detail_by_url`); terms of use ("Geistiges Eigentum"): viewing and saving to one's own disk for personal non-commercial use, no reproduction or distribution, nothing about automated access → private use, low volume; client never named → `company` empty like Hays and Randstad; the agency title rule does not apply (list already IT); first run: up to ~45 detail pages read (≈ 2–3 min), most of them then discarded as too old). Each portal is added with `/add-portal` (real test included). AMS alle jobs **dropped** on 2026-11-26: robots.txt forbids `/public/emps/`, and there is no official read API (the AMS HR-API only lets employers publish postings, through the eAMS account; data.gv.at only gives figures aggregated by district and profession). EURES (`europa.eu/eures`) not retained: the robots.txt of `europa.eu` is unreadable for `tools/fetch_page.py` (refused as a precaution), internal search engine undocumented.
- **V3**: company career pages through one connector **per recruitment software** (Personio, Workday, SuccessFactors, etc.), not per company.
- Disabled regions are not queried; 100% remote postings do not depend on the regions (own switch `remote_worldwide`).
- Frequency: every 4 h; LinkedIn 2–3 times a day at most (`schedule.yaml`).
- Monitoring: alert if a site returns 0 postings several days in a row, if a run fails, if the Claude quota is reached, if a host is blocked.

---

## 8. Telegram commands

| Command | Effect |
|---|---|
| `/search <site>` / `/search all` | Starts a search immediately |
| `/go <ID>` | Prepares the application (§9) |
| `/no <ID> [reason]` | Rejects; the optional reason extends `rejection-rules.md` (without a reason: rejection only, no rule). Posting shown → the next posting in the queue arrives; posting in the queue → removed from the queue |
| `/file` | Waiting postings, numbered in display order (score, title, company, time in the queue); the posting shown comes first (V5) |
| `/voir <n>` | Shows posting n of `/file` right away; the posting shown goes back into the queue (unless it is in `/go`: `/pending` tracks it) (V5) |
| `/rules` | Rules of `rejection-rules.md`, numbered (date, reason, link of the original posting) |
| `/rule del <n…>` | Deletes these rules (`2 5-7`), after `/rules`, with confirmation buttons (10 min); only these lines are removed, by their exact text |
| `/sent <ID>` | Application sent → CSV updated, files deleted from Telegram; posting shown → the next one arrives |
| `/cancel <ID>` | Abandoned → posting closed, never offered again; posting shown → the next one arrives |
| `/pending` | Postings in `/go` without `/sent` (ID, company, role, link, date, age, "resend the files" button) |
| `/reply <ID> yes\|no` | Reply received (yes = positive, no = rejection) → tracker status, follow-up reminders stopped; S…: "keep this contact?" (V5) |
| `/firma <name>` | Applications at this company: role, date, status, link, CV and letter sent |
| `/allow …` / `/deny …` | Allowlist (§6) |
| `/block <company>` | Excludes a company from all searches (portals, career pages, discovery, spontaneous applications); also covers longer names (`Erste` → `Erste Group Bank`) |
| `/blocked` / `/unblock <n>` | Blocked companies, numbered; unblocks a single company |
| `/discover <region>` | Looks for new companies in an enabled region → status `proposed` |
| `/companies` / `/accept 1 3-5` / `/reject 2` | Numbered proposals; `accept` → `active`, `reject` → `rejected` (never proposed again) |
| `/spont <company>` | Prepares a spontaneous application (e-mail + LinkedIn drafts, CV); `/sent S<n>`, `/cancel S<n>` |
| `/region on\|off <name>` / `/regions` | Enables, disables, lists the regions |
| `/status` | Last run, next run, current alerts |
| `/lang [en\|fr]` | Language of the Telegram messages (V5); without an argument: current language and choices |
| `/help` | Help |

**Message language (V5)** — all texts sent to Telegram are in `jobbot/locales/<code>.yaml` (one file per language, same keys; `en.yaml` = reference and fallback for any missing key), read by `scripts/i18n.py`: `t("section.key", value=…)`. No message text in the code. Language: `state/settings.json` (`/lang`), otherwise `JOBBOT_LANG`, otherwise **English**. The Telegram command menu is published by the bot at startup and after `/lang` (`setMyCommands`, `menu.*` texts, in alphabetical order of the displayed name): `/setcommands` at @BotFather is no longer needed. English aliases (same commands): `/queue` = `/file`, `/show` = `/voir`, `/rejects` = `/rejets`, `/company` = `/firma`; the menu and the English texts show the English names (`command.*`). Claude writes the justification, `adapt_reason` and the flags in the chosen language: the scoring batch carries `language` and `flag_labels` (`scoring.*`); the contract / remote-work codes stay fixed and are translated at display time (`values.*`). The following stay in their original language: the documents produced (CV, `offre.pdf`, `email.txt` / `linkedin.txt` drafts) and `rejection-rules.md`. Adding a language = adding `locales/<code>.yaml` (`tests/test_i18n.py` checks keys and parameters).

- `/sent`, `/no`, `/cancel`, `/reply` **require an ID**; without an ID → refused.
- Several `/go` in parallel are allowed. Each message carries ID + company + role; the files are sent **as a reply** to the posting's message; file names `ID_company_role`.
- Reminder of postings waiting > 24 h in the daily recap.
- Deleting files from Telegram: the 48 h limit of the Bot API is **verified** (`deleteMessage` doc: "a message can only be deleted if it was sent less than 48 hours ago"); beyond that, nothing is attempted and the user is told to delete by hand (list of the files).

**Posting queue (V5)** — `scripts/offer_queue.py`, state `state/offer_queue.json` (`T…` IDs: `offer_queue-test.json`, independent):
- **Only one posting shown at a time.** The alerts of a run enter the queue on disk (nothing is lost, restarts included). If no posting is shown, the best one goes out, with the line "📥 y more waiting · /file"; otherwise a single short message "📥 x new posting(s), y waiting".
- **Order**: best score, then oldest in the queue, then ID.
- **Next posting** after `/no`, `/sent` or `/cancel` on the posting shown (sent by the bot after its reply), or `/voir <n>`. **Never after `/go`**: the posting stays shown until `/sent` or `/cancel`. `/go` on a posting still in the queue removes it from the queue (then tracked by `/pending`) without changing the posting shown.
- **Automatic removals**, when the next posting is chosen, from `/file` and from the recap: postings closed in the meantime or already in `/go`; postings whose **published deadline** (`validThrough`) has passed — reported once ("⌛ … removed from the queue") and recorded in `events.jsonl` (`queue_expired`). Most sites publish no deadline: nothing is removed in that case; a posting that has stayed **7 days** or more in the queue is shown with "⚠️ Waiting since …: check that it is still online".
- **Test mode**: `/no T…` removes the test posting and releases the next one from the test queue, without writing a rule.
- `/status` and the daily recap give the posting shown (since when) and the number waiting; nothing is shown again.

**Follow-ups (V5)** — `scripts/followup.py`, zero tokens, plugged into `/outcome` (upstream) **without modifying it**:
- **Vocabulary and format of `/outcome`**: tracker statuses (`applied`, `interview`, `rejected`…); only the `status` and `notes` columns of the `jobbot #<ID>` row are written, dated notes with no comma, quote or line break (Step 4); a follow-up is recorded as `followed up YYYY-MM-DD` in `notes`, the marker that `/outcome` counts (Step 2b); a reply is recorded as `reply yes|no YYYY-MM-DD`.
- **Reminders only for sends confirmed by `/sent` and with no reply**: posting with `sent_at` in the registry and a row still `applied` (`interview` and final statuses = reply; `drafted` = nothing sent); spontaneous application `S…` with status `sent` and no `response`. An application moved to `applied` outside JobBot gets no reminder.
- **`/outcome` clock** (Step 1.3): days without news since the most recent of the dates (`date` column, dates in `notes`); a follow-up or an update recorded by `/outcome` or `/gmail-sync` therefore resets the counter to zero. Thresholds in `schedule.yaml`: `followup_days: 10`, `followup_max: 2` (the values of `/outcome`).
- **Reminder** (with the 08:00 recap, one message per follow-up that has become due, only once per period without news, `state/followups.json`): ID, company, role, link, days, follow-ups done; buttons "✉️ Follow-up sent" (records the follow-up, no duplicate on the same day), "Reply: yes / no"; for a posting, the line `/outcome followup <company>` to run in Claude Code for the draft (interactive branch, never launched by the bot). The text also names the commands (a message that was queued loses its buttons). The recap lists the follow-ups still due.
- **After `followup_max` follow-ups with no reply**: a last notice, with no follow-up button, suggests `/outcome <company>` to record `no_response`; nothing is ever closed automatically.
- **`/reply`**: `applied` → `interview` (yes) or `rejected` (no); `interview`/`offer` → `rejected` (no); refused if not sent (`drafted`), already closed or already replied. Registry `replied`, event `reply` (weekly report). `outcome.md` is still written by `/outcome`: the message suggests `/outcome <company>` for the details.
- **Test mode**: `/sent T…` records the send in `followups-test.json`; `[TEST]` reminders, `/reply T…` and "Follow-up sent" without touching the tracker or `events.jsonl`.

**Format of a posting alert**: ID · score · title · company · location · contract type · remote work · displayed salary · flags ("German to check", "duration unknown"…) · one line of justification · **link**.

---

## 9. `/go` flow

1. **At scoring time** (same run, no extra call), Claude states `variant` (the name of a CV variant), `adapt` (`true` or `false`) and `adapt_reason`.
2. `adapt: false` → the script copies the PDF of the variant. Zero tokens.
3. `adapt: true` → Claude writes **only** `cv_overrides.tex` (adjusted summary, order of the skills, 2–3 highlighted lines). It does not touch the layout. The script checks it (`texguard.py`: only the `\renewcommand`s of the contract), assembles it with the variant and compiles. On failure (refusal, compilation, ≠ 2 pages): the variant as it stands is sent, with the reason; Claude is never run again.
4. **No cover letter** (the user's decision, 2026-11-24): almost never requested; case by case, the user handles it. (Photo, salary: handled by the user, do not invent anything.)
5. The script: compiles (CV with `lualatex`), converts the archived posting into **`offre.pdf`** (`xelatex`), files everything in `documents/applications/<company>_<role>/`, updates the CSV (`drafted`), adds to `pending.json`, sends CV + `offre.pdf` + link to Telegram, as a reply to the posting's message.
6. Implement as a dedicated command `/jobbot-go`, which reuses the upstream tools (`posting_guard.py`, `verify_pdf.py`, `verify_layout.py`, archive) **without modifying `/apply`**.

Prerequisite: LaTeX CV in blocks + compiled variants (delivery / techlead / international-orgs / support-it-manager; finance-réglementaire dropped), in English first, German later.

Test mode: a `JOBBOT_DRY_RUN=1` run produces `T…` IDs; `/go T…`, `/sent T…`, `/cancel T…` work end to end without writing the CSV, the registry or `pending.json` (separate files: `pending-test.json`, cache).

Claude commands: `.claude/commands/` is write-denied by the sandbox; the sources are in `jobbot/commands/` and the user installs them with `cp` (see INSTALL.md).

---

## 10. Companies and spontaneous applications (V3)

- The bot builds `state/companies.csv` itself: IT employers in Vienna (then Bratislava, Budapest, other cities depending on the regions), French and others. Columns: name, city, official site, recruitment software, career URL, origin, status (`active` / `blocked`), verification date.
- Sources to try: directories of the Franco-Austrian Chamber of Commerce, Business France Vienna, WKO, Wirtschaftsagentur Wien, rankings of IT employers. Each new host goes through the allowlist.
- First time: list provided in the setup file (`sites-seed.md`), the user validates/deletes.
- **Spontaneous application**: the bot identifies the contact (IT or HR manager), their address **with the source**, drafts the e-mail in `documents/spontaneous/<company>/email.txt` with the CV PDF to attach. **No Gmail connection.** The user copies, pastes and sends, then `/sent <ID>`.
- `state/contacts.csv`: company, contact, address, source, preparation date, send date, follow-up, reply. Never propose again a contact already contacted. Retention decided by the user at the time of the reply / the reminder (GDPR: strictly necessary data only).
- **Retention (V5)**: after `/reply S…` and in each reminder for an `S…` (as long as nothing is decided), question "Keep this contact?" with two buttons. **Keep** → dated `kept` column. **Purge** → `contact`, `role`, `email`, `email_source`, `linkedin`, `linkedin_source` emptied, status `purged`, `email.txt` / `linkedin.txt` drafts deleted (the CV stays); what remains is the ID, the company, the dates, the reply and a SHA-256 fingerprint of the address and of the profile (`email_hash`, `linkedin_hash`), so that `already_contacted()` still refuses this contact and the company stays out of the 20:00 list.

**V3 implementation (2026-11-24)**
- Statuses of `companies.csv`: `active`, `blocked`, `proposed` (discovery, waiting for `/accept`), `rejected` (never proposed again). Setup: `config/companies-seed.md` → `scripts/import_companies.py`, run by the user (writes only `companies.csv`).
- Recruitment software (`scripts/ats/vendors.py`), domains verified on 2026-11-24 in the vendor's documentation, then `robots.txt`:
  - **with a connector**: Personio (`*.jobs.personio.de`, `/xml` feed), Greenhouse (`boards-api.greenhouse.io`, Job Board API), Lever (`api.lever.co`, `api.eu.lever.co`, Postings API, Crawl-delay 1);
  - **detected, no connector**: Workday (domain and API not documented by Workday), SuccessFactors (`robots.txt`: `Disallow: /`), SmartRecruiters (`robots.txt`: `Disallow: /` except LinkedInBot), Recruitee (token required from February 2027), softgarden (client identifier), onlyfy (no documentation).
- Every request made by the V3 scripts goes through `ats/web.py`: host `allowed` (otherwise `pending`, never contacted), `robots.txt`, Crawl-delay, redirects re-checked. Groups are proposed as `pending` with the documentation as a note, never allowed by the code.
- `companies` run: at most every `companies_every_hours`; postings outside the enabled regions discarded before Claude; maximum age `companies_max_age_days`.
- Spontaneous application: the contact is looked for first in the Impressum, then on the career page of the official site, then on LinkedIn. An address is retained only if it appears on the source page of the official site, re-read by the script: never a guessed address. Files: `email.txt`, `linkedin.txt` (≤ 300 characters, profile link), CV. Nothing is sent.
- 20:00 list (`com.jobbot.spont`): companies that are active, not blocked, not already contacted (any row of `contacts.csv`), not already applied to (CSV after `drafted`), and not listed again before `spont_list_repeat_days`.

---

## 11. Storage, backup, reports

- **CSV** kept (`job_search_tracker.csv`, upstream format). Writes under a lock (`fcntl.flock` on `jobbot/state/.lock`).
- `seen_jobs.json`: written only through `tools/scrape_state.py` (upstream atomic write).
- **Nightly backup**: `rsync` of `job_scraper/`, `job_search_tracker.csv`, `documents/`, `jobbot/state/` to `~/jobbot-data`, then commit + push (private repository `jobbot-data`, dedicated deploy key). The upstream `.gitignore` is not modified.
- **Daily recap**: sites waiting for approval, postings waiting > 24 h, alerts, posting queue (posting shown, number waiting, removals for a passed deadline — V5).
- **Weekly report** (V2): at the weekend, day and time in `schedule.yaml` (default Sunday 18:00): postings seen / kept / `/go` / sent / replies, sites that bring in nothing, sites that are down, estimated cost. V5: replies of the week through `/reply` (positive, rejections) and follow-ups recorded.
- Each run writes `state/runs/<timestamp>.json` (sites queried, postings seen, new, scored, alerted, rejected by reason, blocked hosts, `total_cost_usd`).

---

## 12. Execution

- **Scheduled search**: `jobbot/scripts/run_scan.sh` → pre-filter (scripts) → `claude -p "/jobbot-scan …" --permission-mode dontAsk --permission-prompts none --output-format json --max-budget-usd <cap>` → post-processing (scripts) → Telegram.
- **`launchd` services** (in `/Library/LaunchDaemons`, key `UserName = jobbot`, no open session needed):
  - `com.jobbot.telegram`: Telegram bot, `KeepAlive = true` (restarts by itself);
  - `com.jobbot.scan`: every 4 h;
  - `com.jobbot.backup`: every night;
  - `com.jobbot.daily`: daily recap; `com.jobbot.weekly`: weekly report;
  - `com.jobbot.spont`: daily list of companies for a spontaneous application (§10).
- **Test mode**: `JOBBOT_DRY_RUN=1` → full run, Telegram messages prefixed with `[TEST]`, no permanent write to `seen_jobs.json` / CSV.
- Logs: `jobbot/state/runs/*.log`, 30-day rotation.

---

## 13. Versions

- **V1** — isolation, sandbox, allowlist (setup file + `/allow` `/deny`), LinkedIn + karriere.at, criteria, regions, improved deduplication (§4), scoring + `rejection-rules.md` + `/no`, Telegram alerts with links, `/search`, `/region`, `/regions`, `/status`, `/help`, scheduling, cost cap, monitoring, backup, test mode.
- **V2** — `/go` flow (§9), `/sent`, `/cancel`, `/pending`, `/firma`, `offre.pdf`, weekly report. Prerequisite: CV in blocks + variants. No cover letter.
- **V3** — companies (§10), connectors per recruitment software, spontaneous applications, `/block`.
- **V4** — other sites and countries (§7), check for republications with a slightly modified title.
- **V5** — posting queue on Telegram (`/file`, `/voir`, §8); message language (`/lang`); follow-ups (§8): `/reply`, 10-day reminders plugged into `/outcome`, contact retention (§10).
- **V6** — scoring without AI (`scoring: rules` in `schedule.yaml`, `scripts/rule_scorer.py`): after the pre-filter, a keyword score computed from `criteria.md` replaces the `claude -p` run. Same scores file, same post-processing, same alerts. No Claude account or token is needed; `/go` sends the `default_variant` unchanged; `/discover` and `/spont` are refused. Also in V6: optional `TELEGRAM_USER_ID` (only that user is obeyed), read-only lock probes, pruning of the ledger (`seen_retention_days`, `circumstantial_retention_days`), fixed scoring codes in English (`permanent`, `hybrid`… — the former French codes are still accepted).
- **Later** — freelance (if needed).

Each version is usable on its own. Always: plan first, the user's validation, implementation, network-free tests, real test in test mode, then commit.
