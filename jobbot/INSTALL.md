# JobBot — installation guide (macOS)

Follow the steps in order. Every command block can be pasted as is; lines you must adapt are marked
`# <- change`. Time needed: about one hour, most of it waiting for downloads.

Two accounts are used:

- **admin** — your usual macOS account (it can use `sudo`);
- **jobbot** — a dedicated standard (non-admin) account that runs everything. You can use another name:
  the guide says where it matters.

What you need before starting:

| Need | Required? | Why |
|---|---|---|
| A Mac that stays on | yes | Scheduling uses launchd. Linux and Windows are not supported. |
| A Telegram account | yes | The bot is the only user interface. |
| A Claude subscription (Pro or Max) with [Claude Code](https://code.claude.com/docs/en/setup) | **no** | AI scoring of postings and CV adaptation. Without it, choose the rules mode (step 6): JobBot still scans, filters, alerts and builds your CV, with a keyword score instead of an AI judgement. |
| A LaTeX CV | no | A fictional example CV is shipped; replace its content with yours. |

---

## 1. System checks (admin)

```bash
git --version && python3 --version
```

Python must be 3.10 or newer. If a command is missing: `xcode-select --install`.

LaTeX must be visible to every user of the Mac. Check:

```bash
ls -d /Library/TeX/texbin && /Library/TeX/texbin/lualatex --version | head -1
```

If the folder does not exist, install [MacTeX](https://tug.org/mactex/): the full version already has
every package. With the smaller BasicTeX, add the packages the CV template uses:

```bash
sudo /Library/TeX/texbin/tlmgr update --self
sudo /Library/TeX/texbin/tlmgr install fontawesome6 sourcesans roboto tcolorbox tikzfill pdfcol enumitem ragged2e xifthen ifmtarg xstring setspace unicode-math lualatex-math accsupp parskip bookmark ulem
```

If a compile later reports another missing package, the bot tells you its name: install it the same way.

Keep the Mac awake:

```bash
sudo pmset -a sleep 0 disksleep 0 womp 1 autorestart 1
```

The screen may turn off; the Mac must not sleep. With FileVault on, nothing runs after a power cut until
someone types the disk password.

## 2. Create the dedicated user (admin)

```bash
sudo sysadminctl -addUser jobbot -fullName "Job Bot" -password -
id jobbot | grep -q "(admin)" && echo "WARNING: admin" || echo "OK: standard user"
```

Open a terminal as that user. **Steps 3 to 10 are all run in this session:**

```bash
su - jobbot
```

## 3. Tools (jobbot)

```bash
curl -fsSL https://bun.sh/install | bash
cat >> ~/.zshrc <<'EOF'
export PATH="$HOME/.local/bin:$HOME/.bun/bin:/Library/TeX/texbin:$PATH"
EOF
source ~/.zshrc
bun --version && lualatex --version | head -1
```

Only if you have a Claude subscription:

```bash
curl -fsSL https://claude.ai/install.sh | bash
claude --version
```

## 4. Get the code (jobbot)

```bash
cd ~
git clone https://github.com/fabien92/job-search.git ai-job-search
cd ~/ai-job-search
git remote add upstream https://github.com/ai-job-search-dev/ai-job-search.git
python3 tools/install_portal_clis.py
bash jobbot/scripts/setup_venv.sh
```

The last line must print `venv OK`.

If you want to keep your own changes on GitHub, create a **private** repository and push there. Your
profile, CV and applications are gitignored, but never publish a copy you have personalised.

## 5. Telegram bot and secrets (jobbot)

JobBot does not come with a shared bot. **You create your own Telegram bot and use your own chat**, and
you (optionally) use your own Claude account: nothing goes through the author's bot, chat or
subscription. Your tokens live in one file on your Mac, `~/.config/jobbot/secrets.env`:

| Line | What it is | Where it comes from |
|---|---|---|
| `TELEGRAM_TOKEN` | the password of *your* bot | @BotFather, below |
| `TELEGRAM_CHAT_ID` | the chat the bot writes to and obeys | your private chat with the bot, or a group of yours |
| `TELEGRAM_USER_ID` | optional: the only person obeyed in that chat | your own Telegram user id |
| `CLAUDE_CODE_OAUTH_TOKEN` | only with `scoring: claude` | `claude setup-token`, below |

1. In Telegram, open **@BotFather**, send `/newbot`, choose a name and an identifier ending in `bot`.
   Copy the token it shows.
2. Open your new bot and send it any message (for example `hello`).
3. Read your chat id. The command asks for the token without showing it or saving it in the shell
   history (paste it, press Enter):

```bash
read -rs TOKEN && curl -s "https://api.telegram.org/bot${TOKEN}/getUpdates" | python3 -m json.tool | grep -A3 '"chat"'; unset TOKEN
```

   The number after `"id":` is your chat id.

4. Write the secrets file. It lives outside the repository and must never be committed:

```bash
mkdir -p ~/.config/jobbot
cat > ~/.config/jobbot/secrets.env <<'EOF'
TELEGRAM_TOKEN=paste-the-telegram-token
TELEGRAM_CHAT_ID=paste-your-chat-id
EOF
chmod 600 ~/.config/jobbot/secrets.env
nano ~/.config/jobbot/secrets.env
```

   Replace the two values, save (Ctrl+O, Enter) and quit (Ctrl+X).

The simplest chat is your **private** chat with the bot. A group of your own works too: add the bot to
the group, send `/help@your_bot_name` in it, and run the command of point 3 again; the group's id is the
negative number shown for that chat. The bot obeys whoever writes in the configured chat, so in a group
also add a line `TELEGRAM_USER_ID=your-own-telegram-user-id` (the `"from": {"id": …}` number in the same
output) so that only you are obeyed.

**With a Claude subscription only** — log in once, create a long-lived token and add it to the file:

```bash
cd ~/ai-job-search && claude          # log in, then type /exit
claude setup-token                    # copy the token it prints (valid one year)
cat >> ~/.config/jobbot/secrets.env <<EOF
CLAUDE_CODE_OAUTH_TOKEN=paste-the-claude-token
CLAUDE_CODE_OAUTH_TOKEN_CREATED=$(date +%Y-%m-%d)
EOF
nano ~/.config/jobbot/secrets.env     # replace paste-the-claude-token
```

JobBot warns you on Telegram 30 days before that token expires.

## 6. Choose the scoring mode (jobbot)

Open `jobbot/config/schedule.yaml` and set the `scoring` line:

```bash
nano ~/ai-job-search/jobbot/config/schedule.yaml
```

| `scoring:` | Needs | What you get |
|---|---|---|
| `claude` (default) | Claude subscription | Each posting is read and scored against your profile, with a one-line justification, contract and remote details, a CV variant chosen per posting, and optional adaptation of the CV text on `/go`. `/discover` and `/spont` work. |
| `rules` | nothing | A keyword score from `criteria.md`: title match, then your strong and secondary keywords found in the posting. Hard exclusions (titles, companies, language level, contract) still apply. `/go` sends the CV variant named by `default_variant`, unchanged. `/discover` and `/spont` are unavailable. No AI is called, nothing is billed. |

Set `timezone` in the same file to the Mac's time zone.

## 7. Your identity and profile (jobbot)

Personal data lives only in `private/`, which is gitignored. Tracked files are fictional (Jane Doe) and
serve as fallbacks.

```bash
cd ~/ai-job-search
mkdir -p private
cp jobbot/config/candidate.example.yaml private/candidate.yaml
cp templates/identity_example.tex private/identity.tex
nano private/candidate.yaml      # name, e-mail, phone, LinkedIn, city
nano private/identity.tex        # the same identity, for the LaTeX CV
```

**With Claude:** start `claude` in `~/ai-job-search` and run `/setup`. It interviews you, or imports an
existing CV placed in `documents/`, and writes your profile under `private/`. The scoring reads it.

**In rules mode** no profile is needed: the score uses `criteria.md` only.

## 8. Search criteria (jobbot)

The shipped values are an example for IT delivery roles in Vienna. Edit them:

```bash
nano ~/ai-job-search/jobbot/config/criteria.md
nano ~/ai-job-search/jobbot/config/regions.yaml
```

| File | Content |
|---|---|
| `criteria.md` | Titles searched, keywords, title/type/company exclusions, location, language and contract rules, strong and secondary keywords for the score. Keep the `##` headings as they are: the scripts read them. |
| `regions.yaml` | Cities and countries, each on or off. Also from Telegram: `/region on <name>`. |
| `schedule.yaml` | Scoring mode, scan frequency, alert threshold, budget caps, recap times, queries per portal (0 turns a portal off). |
| `rejection-rules.md` | Starts empty. `/no <ID> <reason>` adds a rule. |

With Claude, also read the three prompts in `jobbot/commands/`. They contain a few rules written for the
original author's search (language-level rejects, the list of CV variants, the kind of companies to
look for). Adapt them, then copy them where Claude Code reads them:

```bash
cd ~/ai-job-search && cp jobbot/commands/jobbot-*.md .claude/commands/
```

## 9. Site whitelist and companies (jobbot)

JobBot only reaches the sites you approve. Open the seed list, delete every line you do not want, and
check the links:

```bash
nano ~/ai-job-search/jobbot/config/sites-seed.md
nano ~/ai-job-search/jobbot/config/companies-seed.md
```

Then import (the first command of each pair only shows what would happen):

```bash
cd ~/ai-job-search
jobbot/.venv/bin/python jobbot/scripts/import_seed.py --dry-run
jobbot/.venv/bin/python jobbot/scripts/import_seed.py
jobbot/.venv/bin/python jobbot/scripts/import_companies.py --dry-run
jobbot/.venv/bin/python jobbot/scripts/import_companies.py
```

This writes `.claude/settings.local.json` and `jobbot/state/scan-settings.json` (sandbox on, strict
network allow-list). Later, new sites arrive as proposals in Telegram: `/sites`, `/allow`, `/deny`.
Always run these two scripts yourself: Claude is denied write access to the whitelist on purpose.

## 10. Your CV (jobbot)

`/go` builds the CV from a "block CV" in `documents/cv/jobbot/`. Start from the shipped example:

```bash
cd ~/ai-job-search
mkdir -p documents/cv/jobbot && cp -R jobbot/examples/cv/. documents/cv/jobbot/
jobbot/.venv/bin/python jobbot/scripts/build_cv_variants.py
open documents/cv/jobbot/pdf/delivery.pdf
```

Every variant must report `"ok": true` and 2 pages. Then replace the example content with yours:
`blocks/*.tex` hold the facts (experience, education, skills), `variants/*.tex` hold what changes per
type of role. `documents/cv/jobbot/README.md` explains each file. Rebuild after every change.

With Claude you can have it done for you. Put your current CV (PDF or LaTeX) in `documents/`, start
`claude` in `~/ai-job-search` and paste:

```
Read jobbot/SPEC.md §9 and documents/cv/jobbot/README.md. Replace the fictional content of the block CV
in documents/cv/jobbot/ (blocks/ and variants/) with my real CV from documents/. Keep the file
structure, the macro names and the layout unchanged. Ask me what should differ in each variant, then run
jobbot/.venv/bin/python jobbot/scripts/build_cv_variants.py until every variant is exactly 2 pages.
```

## 11. Test run (jobbot)

```bash
cd ~/ai-job-search
JOBBOT_DRY_RUN=1 bash jobbot/scripts/run_scan.sh
```

You should receive `[TEST]` messages in Telegram within a few minutes. If not, read the log named on the
last line of the output. Then start the bot by hand:

```bash
bash jobbot/scripts/bot.sh
```

In Telegram send `/health` (checks secrets, Telegram, Bun, LaTeX, disk space, the whitelist and the
Claude token), then `/status` and `/help`. Stop the bot with Ctrl+C.

## 12. Install the services

As **jobbot**, generate the six service files for your user and path:

```bash
cd ~/ai-job-search
jobbot/.venv/bin/python jobbot/scripts/gen_launchd.py --user "$(whoami)" --repo "$PWD"
exit
```

As **admin**, read each generated file (it must run only scripts of `jobbot/scripts/` under the
dedicated user), then install them:

```bash
REPO=/Users/jobbot/ai-job-search      # <- change if your user or folder differs
for f in "$REPO"/jobbot/launchd/com.jobbot.*.plist; do echo "== $f"; plutil -p "$f"; done
sudo cp "$REPO"/jobbot/launchd/com.jobbot.*.plist /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/com.jobbot.*.plist
sudo chmod 644 /Library/LaunchDaemons/com.jobbot.*.plist
for f in /Library/LaunchDaemons/com.jobbot.*.plist; do sudo launchctl bootstrap system "$f"; done
sudo launchctl list | grep com.jobbot
```

Six lines must appear. The bot now runs permanently and the first scan starts within
`scan_every_hours`. Details, updates and removal: `jobbot/launchd/INSTALL-LAUNCHD.md`.

## 13. Backup (optional, jobbot)

Every night `documents/`, the application tracker and `jobbot/state/` are copied to `~/jobbot-data`.
To also keep them off the Mac, make that folder a clone of a **private** repository of yours:

```bash
cd ~ && git clone git@github.com:YOUR_GITHUB_USER/jobbot-data.git   # <- change
```

The backup holds your applications and recruiter contacts in clear text, and git keeps deleted lines in
its history. Never make that repository public.

---

## Day-to-day

- **Stop everything** (admin): `for f in /Library/LaunchDaemons/com.jobbot.*.plist; do sudo launchctl bootout system "$f"; done`
- **Restart the bot** after editing `secrets.env` (admin): `sudo launchctl kickstart -k system/com.jobbot.telegram`
- **Changed a time or frequency in `schedule.yaml`:** redo step 12 (bootout first, see `INSTALL-LAUNCHD.md`).
- **Logs:** `jobbot/state/runs/` (`scan-YYYYMMDD.log`, `launchd-*.log`).
- **Renew the Claude token** before one year: `claude setup-token`, update both Claude lines in
  `secrets.env`, restart the bot.
- **Update from upstream** (jobbot):

```bash
cd ~/ai-job-search
git fetch upstream --tags
python3 tools/check_upstream_updates.py
git merge upstream/master
```

- **Run the tests:**

```bash
cd ~/ai-job-search
jobbot/.venv/bin/python -m unittest discover -s jobbot/tests -p 'test_*.py'
python3 -m unittest discover -s tests
python3 tools/security_guards.py
```

## Troubleshooting

| Symptom | What to check |
|---|---|
| No Telegram message at all | `bash jobbot/scripts/bot.sh` by hand and read the error; token and chat id in `secrets.env`; you sent the bot a first message. |
| "pre-flight check failed" | Send `/health`: each failed line says what to do. |
| Scan runs, no postings | `/status` and `/rejects` show what was dropped and why; lower `alert_threshold`; check `criteria.md` titles and enabled regions. |
| A site is never read | It is not approved: `/sites`, then `/allow <n>`. |
| CV does not compile | `jobbot/.venv/bin/python jobbot/scripts/build_cv_variants.py` prints the LaTeX error; a missing package is installed with `sudo tlmgr install <name>` (admin). |
| Services do not start after a reboot | FileVault is waiting for the disk password; or the plists still contain another user's paths (redo step 12). |
