#!/usr/bin/env python3
"""Zero-token pre-flight check (first step of run_scan.sh; also /health and the daily recap).

    jobbot/.venv/bin/python jobbot/scripts/preflight.py [--for scan|health|daily] [--json]

Checks, each ok / warn / fail:
  secrets      TELEGRAM_TOKEN, TELEGRAM_CHAT_ID (numeric), CLAUDE_CODE_OAUTH_TOKEN; secrets.env mode 600
               (the Claude token is not required with `scoring: rules` in schedule.yaml)
  telegram     Bot API getMe (401/404 = fail: token refused; unreachable = warn: messages are queued)
  bun          `bun --version`, and the CLI of every portal in use exists (queries_per_run > 0)
  lualatex     `lualatex --version`
  venv         jobbot/.venv imports telegram and yaml
  disk         free space on the repo and cache volumes >= min_free_disk_gb (schedule.yaml)
  whitelist    sites.yaml readable with >= 1 allowed site
  sandbox      .claude/settings.local.json and jobbot/state/scan-settings.json: valid, sandbox flags,
               protection rules (Edit deny + denyWrite + Bash), domains in sync with sites.yaml
  claude_token CLAUDE_CODE_OAUTH_TOKEN_CREATED (YYYY-MM-DD in secrets.env) + 365 days:
               < token_warning_days left = warn, expired = fail, unknown = warn
Result: jobbot/state/preflight.json. With --for scan, any fail stops the run (exit 4) and a
deduplicated Telegram alert explains why (sent once, reminded every 24 h, "recovered" when fixed).
Exit 0 when nothing failed, 4 otherwise.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import shutil
import stat
import subprocess
import sys

import common
import telegram_send as tg
from i18n import t

TOKEN_LIFETIME_DAYS = 365
PROTECTED = ["jobbot/config/sites.yaml", "jobbot/state/scan-settings.json",
             ".claude/settings.local.json", ".claude/settings.json", ".claude/settings*.json"]
BASH_RULES = ["Bash(*import_seed*)", "Bash(*gen_settings*)", "Bash(*sites.yaml*)",
              "Bash(*settings.local*)", "Bash(*scan-settings*)"]


def result(name: str, status: str, detail: str, action: str | None = None, **extra) -> dict:
    return {"name": name, "status": status, "detail": detail, "action": action, **extra}


# ------------------------------------------------------------------ checks

def uses_claude(schedule: dict | None = None) -> bool:
    """False with `scoring: rules` in schedule.yaml: no Claude account, token or prompt is needed."""
    import rule_scorer

    return not rule_scorer.enabled(schedule)


def portal_skills(schedule: dict | None = None) -> list[str]:
    """Skill folders of the portals in use: those with queries_per_run > 0 (0 turns a portal off)."""
    import prefilter

    caps = (common.load_schedule() if schedule is None else schedule).get("queries_per_run") or {}
    return [spec["skill"] for name, spec in prefilter.PORTALS.items() if int(caps.get(name, 10) or 0) > 0]


def check_secrets(secrets: dict, claude: bool = True) -> dict:
    required = ("TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID") + (("CLAUDE_CODE_OAUTH_TOKEN",) if claude else ())
    missing = [k for k in required if not secrets.get(k)]
    path = common.secrets_path()
    if missing:
        return result("secrets", "fail", t("preflight.missing", names=", ".join(missing)), t("preflight.complete", path=path))
    if not secrets["TELEGRAM_CHAT_ID"].lstrip("-").isdigit():
        return result("secrets", "fail", t("preflight.chat_id"), t("preflight.fix", path=path))
    if path.exists():
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & 0o077:
            return result("secrets", "warn", t("preflight.mode", name=path.name, mode=oct(mode)[2:]), f"chmod 600 {path}")
    return result("secrets", "ok", t("preflight.present"))


def check_telegram(secrets: dict) -> dict:
    token = secrets.get("TELEGRAM_TOKEN")
    if not token:
        return result("telegram", "fail", t("preflight.no_token"), t("preflight.see_secrets"))
    outcome, body, error = tg.api_request("getMe", {}, token, retries=False, timeout=10)
    if outcome == tg.OK:
        return result("telegram", "ok", f"bot @{(body.get('result') or {}).get('username', '?')}")
    if error and re.match(r"HTTP (401|404)\b", error):
        return result("telegram", "fail", t("preflight.token_refused", error=error[:80]), t("preflight.botfather"))
    return result("telegram", "warn", t("preflight.unreachable", error=(error or '')[:80]), None)


def _version(cmd: list[str]) -> tuple[bool, str]:
    exe = shutil.which(cmd[0])
    if not exe:
        return False, t("preflight.not_found", cmd=cmd[0], path=os.environ.get('PATH', ''))
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"{cmd[0]} : {exc}"
    if proc.returncode != 0:
        return False, f"{cmd[0]} exit {proc.returncode}"
    first = (proc.stdout or proc.stderr).strip().splitlines()
    return True, first[0][:80] if first else exe


def check_bun() -> dict:
    bun = os.environ.get("JOBBOT_BUN", "bun")
    ok, info = _version([bun, "--version"])
    if not ok:
        return result("bun", "fail", info, t("preflight.install_bun"))
    missing = [s for s in portal_skills() if not (common.ROOT / ".agents" / "skills" / s / "cli" / "src" / "cli.ts").is_file()]
    if missing:
        return result("bun", "fail", t("preflight.portal_missing", names=", ".join(missing)), t("preflight.restore_skills"))
    return result("bun", "ok", f"bun {info}")


def check_lualatex() -> dict:
    ok, info = _version([os.environ.get("JOBBOT_LUALATEX", "lualatex"), "--version"])
    if not ok:
        return result("lualatex", "fail", info, t("preflight.texbin"))
    return result("lualatex", "ok", info)


def check_venv() -> dict:
    py = common.JOBBOT / ".venv" / "bin" / "python"
    if not py.exists():
        return result("venv", "fail", t("preflight.venv_missing"), "bash jobbot/scripts/setup_venv.sh")
    try:
        proc = subprocess.run([str(py), "-c", "import telegram, yaml"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return result("venv", "fail", str(exc), "bash jobbot/scripts/setup_venv.sh")
    if proc.returncode != 0:
        return result("venv", "fail", (proc.stderr.strip().splitlines() or [t("preflight.import_failed")])[-1][:120],
                      "bash jobbot/scripts/setup_venv.sh")
    return result("venv", "ok", t("preflight.venv_ok"))


def check_disk(min_gb: float, usage=shutil.disk_usage) -> dict:
    worst = None
    for path in {common.ROOT, common.cache_dir()}:
        free_gb = usage(str(path)).free / 1024 ** 3
        if worst is None or free_gb < worst[1]:
            worst = (path, free_gb)
    path, free_gb = worst
    if free_gb < min_gb:
        return result("disk", "fail", t("preflight.disk_low", free=f"{free_gb:.1f}", path=path, min=min_gb), t("preflight.free_disk"))
    if free_gb < 2 * min_gb:
        return result("disk", "warn", t("preflight.disk_on", free=f"{free_gb:.1f}", path=path))
    return result("disk", "ok", t("preflight.disk_free", free=f"{free_gb:.1f}"))


def check_whitelist() -> dict:
    import sites

    try:
        data = sites.load()
    except Exception as exc:  # noqa: BLE001 - a YAML error must be reported, not crash the check
        return result("whitelist", "fail", t("preflight.sites_unreadable", error=type(exc).__name__), t("preflight.fix_sites"))
    if not sites.path().exists():
        return result("whitelist", "fail", t("preflight.sites_missing"), "jobbot/.venv/bin/python jobbot/scripts/import_seed.py")
    allowed = sites.allowed_domains(data)
    if not allowed:
        return result("whitelist", "fail", t("preflight.no_site"), t("preflight.import_seed"))
    return result("whitelist", "ok", t("preflight.whitelist_ok", n=len(allowed), pending=len(data['pending'])))


def protection_problems(settings: dict) -> list[str]:
    """Missing whitelist protections in one generated settings file (shared with the tests)."""
    problems = []
    deny = (settings.get("permissions") or {}).get("deny") or []
    deny_write = ((settings.get("sandbox") or {}).get("filesystem") or {}).get("denyWrite") or []
    for path in PROTECTED:
        if f"Edit(/{path})" not in deny:
            problems.append(t("preflight.rule_missing", rule=f"deny Edit(/{path})"))
        if str(common.ROOT / path) not in deny_write:
            problems.append(t("preflight.rule_missing_m", rule=f"denyWrite {path}"))
    problems += [t("preflight.rule_missing", rule=f"deny {r}") for r in BASH_RULES if r not in deny]
    return problems


def check_sandbox() -> dict:
    import gen_settings
    import sites

    expected = gen_settings.network_domains(sites.allowed_domains())
    issues = []
    files = {"settings.local.json": common.settings_local_path(), "scan-settings.json": common.state_dir() / "scan-settings.json"}
    for label, path in files.items():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            issues.append(t("preflight.file_missing", name=label))
            continue
        except (OSError, json.JSONDecodeError):
            issues.append(t("preflight.file_unreadable", name=label))
            continue
        sb = data.get("sandbox") or {}
        if sb.get("enabled") is not True or sb.get("failIfUnavailable") is not True or sb.get("allowUnsandboxedCommands") is not False:
            issues.append(t("preflight.sandbox_flags", name=label))
        if label == "scan-settings.json" and (sb.get("network") or {}).get("strictAllowlist") is not True:
            issues.append(t("preflight.strict_missing", name=label))
        if (sb.get("network") or {}).get("allowedDomains") != expected:
            issues.append(t("preflight.domains_stale", name=label))
        issues += [f"{label} : {p}" for p in protection_problems(data)]
    if issues:
        return result("sandbox", "fail", "; ".join(issues[:4]) + (f" (+{len(issues) - 4})" if len(issues) > 4 else ""),
                      t("preflight.regenerate"))
    return result("sandbox", "ok", t("preflight.sandbox_ok", n=len(expected)))


def check_claude_token(secrets: dict, warning_days: int, claude: bool = True) -> dict:
    if not claude:
        return result("claude_token", "ok", "scoring: rules (no Claude account needed)")
    if not secrets.get("CLAUDE_CODE_OAUTH_TOKEN"):
        return result("claude_token", "fail", t("preflight.oauth_missing"), t("preflight.setup_token"))
    created = (secrets.get("CLAUDE_CODE_OAUTH_TOKEN_CREATED") or "").strip()
    try:
        day = dt.date.fromisoformat(created)
    except ValueError:
        return result("claude_token", "warn", t("preflight.expiry_unknown"), t("preflight.add_created"))
    expiry = day + dt.timedelta(days=TOKEN_LIFETIME_DAYS)
    left = (expiry - common.local_now().date()).days
    if left < 0:
        return result("claude_token", "fail", t("preflight.token_expired", date=expiry.isoformat()),
                      t("preflight.renew_token"))
    if left < warning_days:
        return result("claude_token", "warn", t("preflight.expires", date=expiry.isoformat(), days=left),
                      t("preflight.renew_before"), expiring=True)
    return result("claude_token", "ok", t("preflight.expires", date=expiry.isoformat(), days=left))


# ------------------------------------------------------------------ run

def run_checks() -> dict:
    schedule = common.load_schedule()
    secrets = common.load_secrets()
    claude = uses_claude(schedule)
    checks = []
    for fn in (lambda: check_secrets(secrets, claude), lambda: check_telegram(secrets), check_bun, check_lualatex, check_venv,
               lambda: check_disk(float(schedule.get("min_free_disk_gb") or 2)), check_whitelist, check_sandbox,
               lambda: check_claude_token(secrets, int(schedule.get("token_warning_days") or 30), claude)):
        try:
            checks.append(fn())
        except Exception as exc:  # noqa: BLE001 - one broken check must not hide the others
            checks.append(result(getattr(fn, "__name__", "check"), "fail", t("preflight.internal", error=f"{type(exc).__name__}: {exc}")))
    status = "fail" if any(c["status"] == "fail" for c in checks) else "warn" if any(c["status"] == "warn" for c in checks) else "ok"
    report = {"at": common.iso(), "status": status, "checks": checks}
    common.atomic_write_json(common.state_dir() / "preflight.json", report)
    return report


ICONS = {"ok": "✅", "warn": "⚠️", "fail": "❌"}


def format_report(report: dict, title: str | None = None) -> str:
    lines = [f"<b>{tg.esc(title or t('preflight.title'))}</b> : {ICONS[report['status']]}"]
    for c in report["checks"]:
        line = f"{ICONS[c['status']]} {tg.esc(c['name'])} — {tg.esc(c['detail'])}"
        if c["status"] != "ok" and c.get("action"):
            line += f"\n    → {tg.esc(c['action'])}"
        lines.append(line)
    return "\n".join(lines)


def failures_text(report: dict) -> str:
    bad = [c for c in report["checks"] if c["status"] == "fail"]
    lines = [t("preflight.run_cancelled")]
    for c in bad:
        lines.append(f"• {tg.esc(c['name'])} : {tg.esc(c['detail'])}" + (f"\n  → {tg.esc(c['action'])}" if c.get("action") else ""))
    return "\n".join(lines)


def alert(report: dict) -> None:
    import monitor

    failed = report["status"] == "fail"
    monitor.notify("preflight", failures_text(report) if failed else None, failed,
                   recovered=t("preflight.recovered"))
    token = next((c for c in report["checks"] if c["name"] == "claude_token"), None)
    expiring = bool(token and token["status"] == "warn" and token.get("expiring"))
    monitor.notify("claude_token_expiry", t("preflight.token_alert", detail=tg.esc(token['detail']) if token else '',
                                            action=tg.esc(token.get('action') or '') if token else ''), expiring)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--for", dest="purpose", default="scan", choices=["scan", "health", "daily"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    report = run_checks()
    if args.purpose == "scan":
        alert(report)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_report(report).replace("<b>", "").replace("</b>", ""))
    return 4 if report["status"] == "fail" else 0


if __name__ == "__main__":
    sys.exit(main())
