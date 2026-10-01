"""Collects the add-on's translatable strings and what NVDA's own translations already say for them.

Usage: python i18n/extract.py, with NVDA_SOURCE set to a clone of https://github.com/nvaccess/nvda, or
without it to read the compiled translations of the NVDA installed on this machine (NVDA_INSTALL overrides
its folder).
Writes i18n/messages.json: the msgids in source order with their translator comments, and, per NVDA
language, the msgstr NVDA's nvda.po gives for any msgid it has verbatim (with or without the accelerator
ampersand or a trailing colon), so the add-on's terms match NVDA's own in every language.
"""
import ast
import gettext
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NVDA_SOURCE = os.environ.get("NVDA_SOURCE")
if NVDA_SOURCE:
    NVDA_LOCALE, CATALOG = os.path.join(NVDA_SOURCE, "source", "locale"), "nvda.po"
else:
    NVDA_INSTALL = os.environ.get("NVDA_INSTALL") or os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "NVDA")
    NVDA_LOCALE, CATALOG = os.path.join(NVDA_INSTALL, "locale"), "nvda.mo"
    if not os.path.isdir(NVDA_LOCALE):
        sys.exit("Set NVDA_SOURCE to a clone of https://github.com/nvaccess/nvda, or install NVDA.")
SOURCES = [
    "addon/globalPlugins/multilanguage/__init__.py",
    "addon/globalPlugins/multilanguage/settings.py",
    "addon/globalPlugins/multilanguage/context.py",
    "addon/globalPlugins/multilanguage/lock.py",
    "addon/synthDrivers/languageTable.py",
]


def translator_comment(lines, lineno):
    """The "Translators:" comment in the block of comment lines directly above line lineno (1-based)."""
    i = lineno - 2
    while i >= 0 and lines[i].strip().startswith("#"):
        if "Translators:" in lines[i]:
            return lines[i].split("Translators:", 1)[1].strip()
        i -= 1
    return ""


def messages():
    """[(msgid, comment)] in source order. A msgid used more than once keeps its first place and takes the
    first translator comment written for any of its uses."""
    comments = {}
    for rel in SOURCES:
        path = os.path.join(ROOT, rel)
        text = open(path, encoding="utf-8").read()
        lines = text.splitlines()
        tree = ast.parse(text)
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        calls = []
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_"):
                continue
            if not node.args or not isinstance(node.args[0], ast.Constant) or not isinstance(node.args[0].value, str):
                continue
            calls.append(node)
        # ast.walk is breadth-first; source order is line and column.
        calls.sort(key=lambda node: (node.lineno, node.col_offset))
        for node in calls:
            msgid = node.args[0].value
            comment = translator_comment(lines, node.lineno)
            if not comment:
                # A call inside a statement spanning several lines has its comment above the statement.
                statement = parents.get(node)
                while statement is not None and not isinstance(statement, ast.stmt):
                    statement = parents.get(statement)
                if statement is not None and statement.lineno != node.lineno:
                    comment = translator_comment(lines, statement.lineno)
            if not comments.get(msgid):
                comments[msgid] = comment
    return list(comments.items())


def parse_po(path):
    """{msgid: msgstr} for a .po file, entries with a context and fuzzy entries skipped, as msgfmt drops
    fuzzy entries from the compiled catalogs."""
    entries = {}
    msgid = msgstr = None
    field = None
    ctxt = fuzzy = False

    def flush():
        if msgid and msgstr and not ctxt and not fuzzy:
            entries.setdefault(msgid, msgstr)

    for raw in open(path, encoding="utf-8"):
        line = raw.strip()
        if line.startswith("#,"):
            if msgid is not None:
                # A flag line starts the next entry.
                flush()
                msgid = msgstr = field = None
                ctxt = False
            fuzzy = "fuzzy" in line
        elif line.startswith("msgctxt "):
            if msgid is not None:
                flush()
                msgid = msgstr = field = None
                fuzzy = False
            ctxt = True
        elif line.startswith("msgid "):
            if msgid is not None:
                flush()
                ctxt = fuzzy = False
            msgid, msgstr, field = ast.literal_eval(line[6:]), "", "id"
        elif line.startswith("msgid_plural "):
            field = None
        elif line.startswith("msgstr "):
            msgstr, field = ast.literal_eval(line[7:]), "str"
        elif line.startswith("msgstr["):
            field = None
        elif line.startswith('"') and field:
            piece = ast.literal_eval(line)
            if field == "id":
                msgid += piece
            else:
                msgstr += piece
        elif not line:
            flush()
            msgid = msgstr = field = None
            ctxt = fuzzy = False
    flush()
    return entries


def parse_mo(path):
    """{msgid: msgstr} for a compiled catalog, entries with a context or a plural skipped."""
    with open(path, "rb") as f:
        catalog = gettext.GNUTranslations(f)._catalog
    return {
        key: value for key, value in catalog.items()
        if isinstance(key, str) and key and "\x04" not in key and isinstance(value, str) and value
    }


def parse_catalog(path):
    return parse_mo(path) if path.endswith(".mo") else parse_po(path)


def variants(msgid):
    """Spellings NVDA may have for the same label."""
    plain = msgid.replace("&", "")
    out = [msgid, plain]
    for base in (msgid, plain):
        if base.endswith(":"):
            out.append(base[:-1])
        if base.endswith("..."):
            out.append(base[:-3])
    return out


def restore(msgid, nvda_msgid, msgstr):
    """Puts back a trailing colon or ellipsis that the matched NVDA msgid lacked."""
    for suffix in (":", "..."):
        if msgid.endswith(suffix) and not nvda_msgid.endswith(suffix) and not msgstr.endswith(suffix):
            msgstr += suffix
    return msgstr


def main():
    msgs = messages()
    langs = sorted(
        name for name in os.listdir(NVDA_LOCALE)
        if os.path.isfile(os.path.join(NVDA_LOCALE, name, "LC_MESSAGES", CATALOG)) and name != "en"
    )
    reused = {}
    for lang in langs:
        po = parse_catalog(os.path.join(NVDA_LOCALE, lang, "LC_MESSAGES", CATALOG))
        # NVDA may place the accelerator elsewhere ("Rate boos&t"): match on the ampersand-free form.
        stripped = {}
        for key, value in po.items():
            stripped.setdefault(key.replace("&", ""), (key, value))
        hits = {}
        for msgid, _comment in msgs:
            for candidate in variants(msgid):
                plain = candidate.replace("&", "")
                if plain in stripped:
                    nvda_msgid, msgstr = stripped[plain]
                    hits[msgid] = restore(msgid, nvda_msgid, msgstr)
                    break
        reused[lang] = hits
    data = {
        "messages": [{"msgid": m, "comment": c} for m, c in msgs],
        "languages": langs,
        "nvda": reused,
    }
    out = os.path.join(ROOT, "i18n", "messages.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"{len(msgs)} messages, {len(langs)} languages")
    for m, _c in msgs:
        covered = sum(1 for lang in langs if m in reused[lang])
        print(f"{covered:3d}  {m}")


if __name__ == "__main__":
    sys.exit(main())
