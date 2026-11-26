"""rejection-rules.md: list the rules (numbered) and delete some of them (/rules, /rule del).

Deletion removes only the selected lines, matched by their exact text (never by position),
and leaves every other byte of the file untouched. Callers hold common.state_lock().
"""

from __future__ import annotations

import re
import secrets
from pathlib import Path

import common

SECTIONS = ("## Rules", "## Règles")  # the second one: files written before the switch to English
CONFIRM_MINUTES = 10
_RULE = re.compile(r"^- (\d{4}-\d{2}-\d{2}) · (.*) · \(exemple? : #(\S+) (\S+)\)\s*$")  # "example" or the former "exemple"


def path() -> Path:
    return common.config_dir() / "rejection-rules.md"


def numbering_path() -> Path:
    return common.state_dir() / "rules_numbering.json"


def confirm_path() -> Path:
    return common.state_dir() / "rules_delete_pending.json"


def _read() -> str:
    p = path()
    # bytes -> str without newline translation, so \r\n or a missing final newline survive
    return p.read_bytes().decode("utf-8") if p.exists() else ""


def _rule_positions(lines: list[str]) -> list[int]:
    """Indices of the '- …' lines inside the '## Rules' section (until the next heading)."""
    out, inside = [], False
    for i, raw in enumerate(lines):
        line = raw.rstrip("\r\n")
        if line.startswith("#"):
            inside = line.strip() in SECTIONS
            continue
        if inside and line.startswith("- "):
            out.append(i)
    return out


def current() -> list[dict]:
    """[{text, occ}] in file order; occ = rank among identical lines (duplicates stay distinct)."""
    lines = _read().splitlines(keepends=True)
    seen: dict[str, int] = {}
    out = []
    for i in _rule_positions(lines):
        text = lines[i].rstrip("\r\n")
        occ = seen.get(text, 0)
        seen[text] = occ + 1
        out.append({"text": text, "occ": occ})
    return out


def parse(text: str) -> dict:
    """{date, motif, id, url} for the standard /no format, else {free: text}."""
    m = _RULE.match(text)
    if not m:
        return {"free": text[2:] if text.startswith("- ") else text}
    return {"date": m.group(1), "motif": m.group(2), "id": m.group(3), "url": m.group(4)}


def save_numbering(items: list[dict]) -> None:
    common.atomic_write_json(numbering_path(), items)


def load_numbering() -> list[dict] | None:
    data = common.read_json(numbering_path(), None)
    return data if isinstance(data, list) else None


def create_confirmation(items: list[dict]) -> str:
    token = secrets.token_hex(6)
    data = common.read_json(confirm_path(), {}) or {}
    cutoff = common.now().timestamp() - CONFIRM_MINUTES * 60
    data = {k: v for k, v in data.items() if (common.parse_iso(v.get("created")) or common.now()).timestamp() >= cutoff}
    data[token] = {"created": common.iso(), "items": items}
    common.atomic_write_json(confirm_path(), data)
    return token


def take_confirmation(token: str) -> tuple[list[dict] | None, str | None]:
    """One-shot: the token is removed whatever happens. -> (items, error)."""
    data = common.read_json(confirm_path(), {}) or {}
    entry = data.pop(token, None)
    common.atomic_write_json(confirm_path(), data)
    if not entry:
        return None, "unknown"
    created = common.parse_iso(entry.get("created"))
    if not created or (common.now() - created).total_seconds() > CONFIRM_MINUTES * 60:
        return None, "expired"
    return entry.get("items") or [], None


def delete(items: list[dict]) -> tuple[list[str], list[str]]:
    """Remove exactly these lines (text + occurrence). -> (deleted texts, texts not found)."""
    raw = _read()
    lines = raw.splitlines(keepends=True)
    by_text: dict[str, list[int]] = {}
    for i in _rule_positions(lines):
        by_text.setdefault(lines[i].rstrip("\r\n"), []).append(i)
    drop, deleted, missing = set(), [], []
    for item in items:
        positions = by_text.get(item["text"], [])
        occ = int(item.get("occ") or 0)
        if occ < len(positions):
            drop.add(positions[occ])
            deleted.append(item["text"])
        else:
            missing.append(item["text"])
    if drop:
        common.atomic_write_text(path(), "".join(l for i, l in enumerate(lines) if i not in drop))
    return deleted, missing
