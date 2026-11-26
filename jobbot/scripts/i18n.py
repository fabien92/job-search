"""Language of the Telegram messages: one dictionary per language, nothing hard-coded elsewhere.

    jobbot/locales/en.yaml   reference language (default, and fallback for any missing key)
    jobbot/locales/fr.yaml   same keys

Code calls t("section.key", name=value): the text is looked up in the current language, then in
English, and formatted with str.format (a literal brace is written {{ or }} in the YAML).
tv("contract", value) translates a value Claude writes in the scoring vocabulary (permanent, hybrid…);
an unknown value is shown as is.

Current language: state/settings.json {"lang": "fr"} (set by the Telegram command /lang), else the
JOBBOT_LANG environment variable (the tests use it), else "en". Adding a language = adding
jobbot/locales/<code>.yaml with the same keys (tests/test_i18n.py checks keys and placeholders).
"""

from __future__ import annotations

import string
from pathlib import Path

import common

LOCALES = Path(__file__).resolve().parents[1] / "locales"
DEFAULT = "en"
_cache: dict[str, tuple[float, dict[str, str]]] = {}


def settings_path() -> Path:
    return common.state_dir() / "settings.json"


def available() -> list[str]:
    return sorted(p.stem for p in LOCALES.glob("*.yaml"))


def _flatten(node, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in (node or {}).items():
        full = f"{prefix}{key}"
        if isinstance(value, dict):
            out.update(_flatten(value, full + "."))
        else:
            out[full] = "" if value is None else str(value)
    return out


def catalog(code: str) -> dict[str, str]:
    """Flat {dotted key: text} for one language, reloaded when its file changes (the bot runs for weeks)."""
    path = LOCALES / f"{code}.yaml"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cached = _cache.get(code)
    if cached and cached[0] == mtime:
        return cached[1]
    import yaml  # lazy: telegram_send stays importable without the venv

    data = _flatten(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    _cache[code] = (mtime, data)
    return data


def lang() -> str:
    import os

    try:
        saved = (common.read_json(settings_path(), {}) or {}).get("lang")
    except (ValueError, OSError, AttributeError):  # corrupt settings.json: every reply still has a language
        saved = None
    for code in (saved, os.environ.get("JOBBOT_LANG")):
        if code and code in available():
            return code
    return DEFAULT


def set_lang(code: str) -> None:
    with common.state_lock():
        try:
            data = common.read_json(settings_path(), {}) or {}
        except ValueError:
            data = {}  # corrupt file: rewritten from scratch
        if not isinstance(data, dict):
            data = {}
        data["lang"] = code
        common.atomic_write_json(settings_path(), data)


def t(key: str, _lang: str | None = None, **values) -> str:
    code = _lang or lang()
    text = catalog(code).get(key)
    if text is None:
        text = catalog(DEFAULT).get(key)
    if text is None:
        common.log(f"i18n: missing key {key}")
        return key
    return text.format(**values) if values else text.replace("{{", "{").replace("}}", "}")


def tv(group: str, value, _lang: str | None = None) -> str:
    """A scoring-vocabulary value (values.<group>.<value>) in the current language; unknown -> as is."""
    if value is None:
        return ""
    code = _lang or lang()
    key = f"values.{group}.{value}"
    return catalog(code).get(key) or catalog(DEFAULT).get(key) or str(value)


def placeholders(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}
