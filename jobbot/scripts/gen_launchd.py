#!/usr/bin/env python3
"""schedule.yaml -> jobbot/launchd/com.jobbot.*.plist (LaunchDaemons run as one non-admin user).

    jobbot/.venv/bin/python jobbot/scripts/gen_launchd.py [--user NAME] [--repo PATH] [--home DIR] [--group NAME]

Defaults: --user is the current user, --repo this repository, the home directory and the group come
from the user database (the account's home and primary group). The tracked plists are the documented
example (`--user jobbot --repo /Users/jobbot/ai-job-search`): regenerate them for your own account.

Re-run after changing scan_every_hours, daily_recap, weekly_report, backup or spont_list in schedule.yaml,
then reinstall with the commands of jobbot/launchd/INSTALL-LAUNCHD.md.
launchd uses the Mac's system time zone for StartCalendarInterval.
"""

from __future__ import annotations

import argparse
import grp
import os
import plistlib
import pwd
import sys
from pathlib import Path

import common

PATH = "{home}/.local/bin:{home}/.bun/bin:/Library/TeX/texbin:/usr/bin:/bin:/usr/sbin:/sbin"


def hhmm(value: str) -> dict:
    hour, minute = str(value).split(":")
    return {"Hour": int(hour), "Minute": int(minute)}


WEEKDAYS = {"sunday": 0, "monday": 1, "tuesday": 2, "wednesday": 3, "thursday": 4, "friday": 5, "saturday": 6,
            "dimanche": 0, "lundi": 1, "mardi": 2, "mercredi": 3, "jeudi": 4, "vendredi": 5, "samedi": 6}


def weekly(value) -> dict:
    """schedule.yaml weekly_report {day, time} -> launchd {Weekday (0 = Sunday), Hour, Minute}."""
    value = value or {}
    day = str(value.get("day") or "sunday").strip().lower()
    if day not in WEEKDAYS:
        raise ValueError(f"unknown weekly_report.day: {day!r}")
    return {"Weekday": WEEKDAYS[day], **hhmm(value.get("time") or "18:00")}


def current_user() -> str:
    return pwd.getpwuid(os.getuid()).pw_name


def account(user: str) -> tuple[str, str]:
    """-> (home directory, primary group name) of a local account, from the user database."""
    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        raise ValueError(f"unknown user {user!r}: create the account first, or pass --home and --group") from None
    try:
        group = grp.getgrgid(entry.pw_gid).gr_name
    except KeyError:
        group = str(entry.pw_gid)
    return entry.pw_dir, group


def build(user: str, repo: Path, schedule: dict, home: str | None = None, group: str | None = None) -> dict[str, dict]:
    if home is None or group is None:
        found_home, found_group = account(user)
        home, group = home or found_home, group or found_group
    logs = repo / "jobbot" / "state" / "runs"

    def base(label: str, script: str) -> dict:
        return {
            "Label": label,
            "UserName": user,
            "GroupName": group,
            "ProgramArguments": ["/bin/bash", str(repo / "jobbot" / "scripts" / script)],
            "WorkingDirectory": str(repo),
            "EnvironmentVariables": {"HOME": home, "USER": user, "PATH": PATH.format(home=home),
                                     "LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"},
            "StandardOutPath": str(logs / f"launchd-{label.split('.')[-1]}.log"),
            "StandardErrorPath": str(logs / f"launchd-{label.split('.')[-1]}.log"),
            "ProcessType": "Background",
        }

    return {
        "com.jobbot.telegram": {**base("com.jobbot.telegram", "bot.sh"), "RunAtLoad": True, "KeepAlive": True,
                                "ThrottleInterval": 30},
        "com.jobbot.scan": {**base("com.jobbot.scan", "run_scan.sh"), "RunAtLoad": False,
                            "StartInterval": int(float(schedule["scan_every_hours"]) * 3600)},
        "com.jobbot.backup": {**base("com.jobbot.backup", "backup.sh"), "StartCalendarInterval": hhmm(schedule["backup"])},
        "com.jobbot.daily": {**base("com.jobbot.daily", "daily.sh"), "StartCalendarInterval": hhmm(schedule["daily_recap"])},
        "com.jobbot.weekly": {**base("com.jobbot.weekly", "weekly.sh"),
                              "StartCalendarInterval": weekly(schedule.get("weekly_report"))},
        "com.jobbot.spont": {**base("com.jobbot.spont", "spont_list.sh"),
                             "StartCalendarInterval": hhmm(schedule.get("spont_list") or "20:00")},
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--user", default=current_user(), help="account the services run as (default: the current user)")
    ap.add_argument("--repo", type=Path, default=common.ROOT, help="repository path on the target Mac")
    ap.add_argument("--home", help="home directory of --user (default: from the user database)")
    ap.add_argument("--group", help="GroupName (default: the primary group of --user)")
    ap.add_argument("--out", type=Path, default=common.JOBBOT / "launchd")
    args = ap.parse_args(argv)
    try:
        plists = build(args.user, args.repo.resolve(), common.load_schedule(), args.home, args.group)
    except ValueError as exc:
        print(f"gen_launchd: {exc}", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    for label, plist in plists.items():
        (args.out / f"{label}.plist").write_bytes(plistlib.dumps(plist, sort_keys=False))
        print(f"wrote {args.out / (label + '.plist')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
