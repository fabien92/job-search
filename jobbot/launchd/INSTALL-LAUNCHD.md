# Installing the JobBot services (launchd)

Six LaunchDaemons, run as the user `jobbot` (`UserName = jobbot`): no open session is needed.

**The tracked `.plist` files are examples** generated for the user `jobbot` and the repository
`/Users/jobbot/ai-job-search`. With any other user name or repository path, regenerate them first, from the
repository root, in a session of the dedicated user:

```bash
jobbot/.venv/bin/python jobbot/scripts/gen_launchd.py --user "$(whoami)" --repo "$PWD"
```

This rewrites the six `jobbot/launchd/com.jobbot.*.plist` files with that user (`UserName`, `HOME` =
`/Users/<user>`, `PATH`) and that repository (script paths, `WorkingDirectory`, log paths). The labels and file
names stay `com.jobbot.*`.

| Service | Program | When |
|---|---|---|
| `com.jobbot.telegram` | `jobbot/scripts/bot.sh` → `jobbot/bot/bot.py` | permanently (`KeepAlive`, restarts by itself) |
| `com.jobbot.scan` | `jobbot/scripts/run_scan.sh` | every 4 h (`StartInterval` 14400, from `scan_every_hours`) |
| `com.jobbot.backup` | `jobbot/scripts/backup.sh` | every night at 02:30 (`backup`) |
| `com.jobbot.daily` | `jobbot/scripts/daily.sh` | every day at 08:00 (`daily_recap`) |
| `com.jobbot.weekly` | `jobbot/scripts/weekly.sh` | weekly report, Sunday 18:00 (`weekly_report`) |
| `com.jobbot.spont` | `jobbot/scripts/spont_list.sh` | V3: list of companies for spontaneous applications, every day at 20:00 (`spont_list`) |

The `.plist` files are generated from `jobbot/config/schedule.yaml` by
`jobbot/.venv/bin/python jobbot/scripts/gen_launchd.py` (`jobbot` session). Schedule times follow the **Mac's
system time zone** (System Settings → General → Date & Time); set `timezone` in `jobbot/config/schedule.yaml`
to the same zone.
Logs: `~/ai-job-search/jobbot/state/runs/launchd-*.log` (+ the scripts' own logs in the same folder).

## 0. Prerequisites (`jobbot` session)

```bash
cd ~/ai-job-search
ls jobbot/.venv/bin/python                       # otherwise: bash jobbot/scripts/setup_venv.sh
ls -l ~/.config/jobbot/secrets.env               # must be -rw------- (600)
ls jobbot/state/scan-settings.json               # otherwise: jobbot/.venv/bin/python jobbot/scripts/import_seed.py
JOBBOT_DRY_RUN=1 bash jobbot/scripts/run_scan.sh # a test run must work before installing
```

## 1. Review the plists (admin account)

Check in each file: `UserName` = `jobbot` (or your dedicated user), `ProgramArguments` = `/bin/bash` + a script
from `$REPO/jobbot/scripts/`, nothing else.

The admin-account commands below use the shell variable `REPO`. It is set once here; run the following blocks
in the same terminal, or set it again first in a new one.

```bash
REPO=/Users/jobbot/ai-job-search   # change to your repository path
for f in "$REPO"/jobbot/launchd/com.jobbot.*.plist; do echo "== $f"; plutil -p "$f"; done
```

## 2. Install (admin account)

```bash
sudo cp "$REPO"/jobbot/launchd/com.jobbot.telegram.plist \
        "$REPO"/jobbot/launchd/com.jobbot.scan.plist \
        "$REPO"/jobbot/launchd/com.jobbot.backup.plist \
        "$REPO"/jobbot/launchd/com.jobbot.daily.plist \
        "$REPO"/jobbot/launchd/com.jobbot.weekly.plist \
        "$REPO"/jobbot/launchd/com.jobbot.spont.plist \
        /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/com.jobbot.*.plist
sudo chmod 644 /Library/LaunchDaemons/com.jobbot.*.plist
for f in /Library/LaunchDaemons/com.jobbot.*.plist; do sudo plutil -lint "$f"; done
for f in /Library/LaunchDaemons/com.jobbot.*.plist; do sudo launchctl bootstrap system "$f"; done
```

## 3. Verify (admin account)

```bash
sudo launchctl print system/com.jobbot.telegram | grep -E "state|pid|last exit"
sudo launchctl print system/com.jobbot.scan     | grep -E "state|run interval|last exit"
sudo launchctl list | grep com.jobbot
```

On Telegram: `/help`, `/status`, `/regions` must answer.

Start a run right away (without waiting 4 h):

```bash
sudo launchctl kickstart system/com.jobbot.scan
```

## 4. After a change

- **Code or config** (scripts, `schedule.yaml` other than frequencies): nothing to do for scan/backup/daily;
  for the bot: `sudo launchctl kickstart -k system/com.jobbot.telegram`.
- **Token** (`secrets.env` updated, e.g. yearly renewal of `claude setup-token`):
  `sudo launchctl kickstart -k system/com.jobbot.telegram` (the other services re-read the file at each launch).
- **Frequencies / times** (`scan_every_hours`, `daily_recap`, `weekly_report`, `backup`, `spont_list`): regenerate the plists (`jobbot` session:
  `jobbot/.venv/bin/python jobbot/scripts/gen_launchd.py`, with the same `--user` / `--repo` arguments as above
  if you are not using the example values), then from the admin account, for each modified service:

```bash
sudo launchctl bootout system/com.jobbot.scan
sudo cp "$REPO"/jobbot/launchd/com.jobbot.scan.plist /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/com.jobbot.scan.plist && sudo chmod 644 /Library/LaunchDaemons/com.jobbot.scan.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.jobbot.scan.plist
```

## 5. Stop / uninstall (admin account)

```bash
for s in telegram scan backup daily weekly spont; do sudo launchctl bootout system/com.jobbot.$s; done
sudo rm /Library/LaunchDaemons/com.jobbot.*.plist
```

Temporarily stopping a single service: `sudo launchctl bootout system/com.jobbot.scan`
(to re-enable it: `sudo launchctl bootstrap system /Library/LaunchDaemons/com.jobbot.scan.plist`).

## 6. Adding the weekly report to a V1 installation (admin account)

```bash
sudo cp "$REPO"/jobbot/launchd/com.jobbot.weekly.plist /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/com.jobbot.weekly.plist
sudo chmod 644 /Library/LaunchDaemons/com.jobbot.weekly.plist
sudo plutil -lint /Library/LaunchDaemons/com.jobbot.weekly.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.jobbot.weekly.plist
sudo launchctl print system/com.jobbot.weekly | grep -E "state|last exit"
sudo launchctl kickstart -k system/com.jobbot.telegram   # the bot loads /go /sent /cancel /pending /firma
```

## 7. Adding the 20:00 list (V3) to a V2 installation (admin account)

```bash
sudo cp "$REPO"/jobbot/launchd/com.jobbot.spont.plist /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/com.jobbot.spont.plist
sudo chmod 644 /Library/LaunchDaemons/com.jobbot.spont.plist
sudo plutil -lint /Library/LaunchDaemons/com.jobbot.spont.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/com.jobbot.spont.plist
sudo launchctl print system/com.jobbot.spont | grep -E "state|last exit"
sudo launchctl kickstart -k system/com.jobbot.telegram   # the bot loads /rules /rule /block /blocked /unblock /discover /companies /accept /reject /spont
```
