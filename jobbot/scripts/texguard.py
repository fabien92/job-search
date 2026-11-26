#!/usr/bin/env python3
"""Validate a cv_overrides.tex written by Claude before lualatex sees it (SPEC §9.3) — zero tokens.

    jobbot/.venv/bin/python jobbot/scripts/texguard.py FILE      # exit 0 ok, 1 refused (reasons on stdout)

Claude wrote the file after reading an untrusted posting, and lualatex can run Lua (\\directlua),
write files (\\write, \\openout) or read others (\\input). So the file is parsed, not pattern-matched:
it may only contain

  * comments and whitespace;
  * \\cvphotofalse / \\cvphototrue;
  * \\renewcommand{\\<macro>}{<body>} for the macros of the contract (documents/cv/jobbot/README.md),
    each body brace-balanced, using only the text commands of TEXT_COMMANDS.

Everything else is refused: other control sequences, ^^ escapes, parameters (#), an unescaped %
inside a macro body (it would comment out the closing brace), optional arguments,
\\def/\\let/\\catcode..., layout commands, unbalanced braces, over-long texts.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

TEXT_TARGETS = {
    "cvHeadline": 80,
    "cvProfileText": 750,
    "cvAchievementOne": 420,
    "cvAchievementTwo": 420,
    "cvAchievementThree": 420,
}
SKILL_TARGETS = {f"ts{c}": "skillcell" for c in "ABCDEFGHI"} | {f"fs{c}": "funcell" for c in "ABCD"}
ORDER_TARGET = "expCurrentBlocks"
ORDER_BLOCKS = ("expMgmt", "expTech", "expProj")
SWITCHES = {"cvphotofalse", "cvphototrue"}
TEXT_COMMANDS = {"textbf", "textit", "emph", "textbullet", "textasciitilde", "ldots", "textendash", "textemdash"}
CELL_MAX = 160          # characters per skill-cell argument
MAX_FILE = 12000
# Control symbols (\ + one non-letter) that only print a character or a space.
SAFE_SYMBOLS = set("&%$#_{} ,-/")

_CS = re.compile(r"\\([A-Za-z@]+|.)", re.S)


class Refused(ValueError):
    pass


def _skip_space_comments(text: str, i: int) -> int:
    while i < len(text):
        if text[i].isspace():
            i += 1
        elif text[i] == "%":
            nl = text.find("\n", i)
            i = len(text) if nl < 0 else nl + 1
        else:
            break
    return i


def _group(text: str, i: int) -> tuple[str, int]:
    """Read a {...} group starting at text[i] == '{' -> (inner, index after '}')."""
    if i >= len(text) or text[i] != "{":
        raise Refused(f"'{{' expected at position {i}")
    depth, j = 0, i
    while j < len(text):
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[i + 1:j], j + 1
        j += 1
    raise Refused("unbalanced braces")


def _check_body(body: str, allowed: set[str], where: str) -> None:
    if "^^" in body:
        raise Refused(f"{where}: ^^ sequence forbidden")
    if "#" in body.replace("\\#", ""):
        raise Refused(f"{where}: # forbidden")
    # A bare % starts a TeX comment: it would swallow the rest of the line, closing brace included.
    if "%" in re.sub(r"\\.", "", body, flags=re.S):
        raise Refused(f"{where}: unescaped % (write \\% for a percent sign; no comments inside a macro body)")
    for m in _CS.finditer(body):
        name = m.group(1)
        if len(name) == 1 and not name.isalpha():
            if name not in SAFE_SYMBOLS:
                raise Refused(f"{where}: \\{name} forbidden")
            continue
        if name not in allowed:
            raise Refused(f"{where}: command \\{name} forbidden")
    depth = 0
    plain = re.sub(r"\\.", "", body)
    for ch in plain:
        depth += ch == "{"
        depth -= ch == "}"
        if depth < 0:
            raise Refused(f"{where}: unbalanced braces")
    if depth:
        raise Refused(f"{where}: unbalanced braces")


def _visible_len(body: str) -> int:
    return len(" ".join(re.sub(r"\\[A-Za-z]+|[{}\\]", "", body).split()))


def _check_cell(name: str, body: str) -> None:
    cmd = SKILL_TARGETS[name]
    body = body.strip()
    prefix = "\\" + cmd
    if not body.startswith(prefix):
        raise Refused(f"\\{name} must be \\{cmd}{{Title}}{{list}}")
    i = _skip_space_comments(body, len(prefix))
    title, i = _group(body, i)
    i = _skip_space_comments(body, i)
    items, i = _group(body, i)
    if body[i:].strip():
        raise Refused(f"\\{name}: text after \\{cmd}{{…}}{{…}}")
    for part in (title, items):
        _check_body(part, TEXT_COMMANDS, f"\\{name}")
        if _visible_len(part) > CELL_MAX:
            raise Refused(f"\\{name}: text too long")


def check(text: str) -> dict:
    """-> {"macros": [...], "switches": [...]} or raises Refused."""
    if len(text) > MAX_FILE:
        raise Refused("fichier trop long")
    if "^^" in text:
        raise Refused("^^ sequence forbidden")
    seen: list[str] = []
    switches: list[str] = []
    i = _skip_space_comments(text, 0)
    while i < len(text):
        m = _CS.match(text, i)
        if not m:
            raise Refused(f"text outside \\renewcommand at position {i}: {text[i:i + 30]!r}")
        name = m.group(1)
        i = m.end()
        if name in SWITCHES:
            switches.append(name)
        elif name == "renewcommand":
            i = _skip_space_comments(text, i)
            target, i = _group(text, i)
            target = target.strip()
            if not re.fullmatch(r"\\[A-Za-z]+", target):
                raise Refused(f"cible invalide : {target[:40]!r}")
            target = target[1:]
            i = _skip_space_comments(text, i)
            if i < len(text) and text[i] == "[":
                raise Refused(f"\\{target} : arguments interdits")
            body, i = _group(text, i)
            if target in TEXT_TARGETS:
                _check_body(body, TEXT_COMMANDS, f"\\{target}")
                if _visible_len(body) > TEXT_TARGETS[target]:
                    raise Refused(f"\\{target} : texte trop long ({_visible_len(body)} > {TEXT_TARGETS[target]})")
                if target == "cvHeadline" and "\n\n" in body:
                    raise Refused("\\cvHeadline : une seule ligne")
            elif target in SKILL_TARGETS:
                _check_cell(target, body)
            elif target == ORDER_TARGET:
                blocks = re.findall(r"\\([A-Za-z]+)", body)
                if sorted(blocks) != sorted(ORDER_BLOCKS) or re.sub(r"\\[A-Za-z]+|\s", "", body):
                    raise Refused("\\expCurrentBlocks : exactement \\expMgmt, \\expTech, \\expProj dans un ordre")
            else:
                raise Refused(f"macro hors contrat : \\{target}")
            if target in seen:
                raise Refused(f"\\{target} redefined twice")
            seen.append(target)
        else:
            raise Refused(f"commande \\{name} interdite hors \\renewcommand")
        i = _skip_space_comments(text, i)
    if not seen and not switches:
        raise Refused("aucune surcharge")
    return {"macros": seen, "switches": switches}


def check_file(path: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise Refused(f"illisible : {exc}") from None
    return check(text)


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print("usage: texguard.py FILE", file=sys.stderr)
        return 2
    try:
        print(check_file(Path(argv[0])))
        return 0
    except Refused as exc:
        print(f"refused: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
