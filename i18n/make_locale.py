"""Builds addon/locale from the add-on's messages and the translations in i18n/translations/*.json.

Usage: python i18n/make_locale.py

For every NVDA language, each msgid gets NVDA's own translation when NVDA has the same string (so the
add-on's terms match NVDA's in that language), else the translation from the JSON files, keyed by the
short codes in CODES; codes in OURS_FIRST take the JSON translation first. A language entry that is the string "=xx" copies language xx. Translations whose
%s placeholders do not match the msgid are dropped and listed, as are gaps, which fall back to English.
Labels whose translation lost its accelerator, or has it on a space, are kept and listed.
Writes nvda.po and nvda.mo under addon/locale/<lang>/LC_MESSAGES and a manifest.ini with the translated
summary and description.
"""
import array
import glob
import json
import os
import re
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CODES = {
    "S0": "Off",
    "S2": "Full",
    "S5": "Toggles strict language detection",
    "S6": "Language detection %s",
    "S7": "Strict detection on",
    "S8": "Strict detection off",
    "S9": "installed",
    "S10": "installing",
    "S11": "missing",
    "S12": "You will be asked to grant administrator permission to install the Windows dictionary for %s. It is required for accurate language detection.",
    "S13": "Windows dictionary",
    "S14": "Not started: administrator permission was not given.",
    "S15": "Installing the %s dictionary. NVDA will report when done.",
    "S16": "%s dictionary installed.",
    "S17": "Language &detection:",
    "S18": "Default s&ynthesizer:",
    "S20": "Each row speaks with its own synthesizer and voice.",
    "S21": "Enter a language.",
    "S24": "Install finished, but Windows does not show the %s dictionary yet. Restart Windows.",
    "S25": "%s dictionary did not install. Check Windows Update, or see the NVDA log.",
    "S26": "Dictionary",
    "S27": "%s picks its own voice per language; its rows set rate, pitch, and volume. Rows for other synthesizers, and Windows voices, are hosted automatically.",
    "S28": "Synthesizer could not be loaded. See the NVDA log.",
    "S29": "%s is not a language code. Pick a voice or enter a code such as fr or fr_FR.",
    "S32": "&Strict: also require Windows language detection to agree",
    "S33": "Detect inside text &tagged with the default language",
    "S34": "Use &Windows voices for languages the synthesizer cannot speak",
    "S35": "The %s dictionary is installed.",
    "S36": "Edit language",
    "S37": "Add language",
    "S38": "Rate &boost",
    "S39": "&Test",
    "S40": "&Verify language pack...",
    "S42": "Language table (Dialingo)",
    "S43": "Voice dictionary for %s",
    "S44": "This row has no voice of its own, so the synthesizer's voice dictionary applies to it.",
    "S45": "Pu&nctuation/symbol level:",
    "S46": "Same as NVDA",
    "S47": "Symbols",
    "S48": "unknown",
    "S49": "Could not check the %s dictionary. See the NVDA log.",
    "S50": "There is already a row for %s. Replace it?",
    "S51": "Replace language",
    "S52": "&Languages (detected when checked; the default needs no row):",
    "S53": "Language lock",
    "S54": "Automatic",
    "S55": "Language detection",
    "S56": "%s detection",
    "S57": "on",
    "S58": "off",
    "S59": "Script and tags only",
    "S60": "Cycles language detection: off, script and tags only, full",
    # Terms NVDA usually has; here for the languages where it does not.
    "T1": "&Synthesizer:",
    "T2": "&Voice:",
    "T3": "V&ariant:",
    "T4": "&Language:",
    "T5": "Language",
    "T6": "Synthesizer",
    "T7": "Voice",
    "T8": "Rate",
    "T9": "Pitch",
    "T10": "Volume",
    "T11": "&Rate",
    "T12": "&Pitch",
    "T13": "V&olume",
    "T14": "&Inflection",
    "T15": "Error",
    "T16": "&Add...",
    "T17": "&Edit...",
    "T18": "&Remove",
    "T19": "Voice dictionary",
    "T20": "V&oice dictionary...",
}

# Codes whose translation here wins over NVDA's: NVDA has the same English word in another sense
# ("unknown window", "undefined"), not as a dictionary state beside "installed" and "missing"; and
# "Automatic" as the braille display's detection ("automatic connection"), not as the lock's switching.
OURS_FIRST = {"S48", "S54"}


def load_translations():
    merged = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "i18n", "translations", "*.json"))):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        for lang, entries in data.items():
            if isinstance(entries, str):
                merged[lang] = entries
            else:
                merged.setdefault(lang, {}).update(entries)
    # Resolve "=xx" copies.
    for lang, entries in list(merged.items()):
        if isinstance(entries, str) and entries.startswith("="):
            source = merged.get(entries[1:])
            merged[lang] = dict(source) if isinstance(source, dict) else {}
    return merged


def valid(msgid, msgstr, problems, lang, accelerators):
    """The msgstr to use, or None when its placeholders do not match. A label whose translation lost its
    accelerator, or has it before a space or at the end, where it gives no usable access key, is kept and
    listed in accelerators."""
    if msgid.count("%s") != msgstr.count("%s"):
        problems.append(f"{lang}: placeholder mismatch for {msgid!r}: {msgstr!r}")
        return None
    if "&" not in msgid:
        msgstr = strip_accelerator(msgstr)
    else:
        if msgstr.count("&") > msgid.count("&"):
            # NVDA's own catalogs have a few doubled accelerators; the first one stands.
            head, _, tail = msgstr.partition("&")
            msgstr = head + "&" + tail.replace("&", "")
        if "&" not in msgstr:
            accelerators.append(f"{lang}: no accelerator in {msgstr!r} for {msgid!r}")
        elif re.search(r"&(\s|$)", msgstr):
            accelerators.append(f"{lang}: accelerator on a space in {msgstr!r} for {msgid!r}")
    return msgstr


def strip_accelerator(text):
    """Removes an accelerator, whether inline ("&Voice") or appended in the East Asian way ("声(&V)")."""
    return re.sub(r"\s*\(&.\)", "", text).replace("&", "")


def plain(msgid):
    # The space French and others put before a colon goes with it; Amharic and Khmer write their own colons.
    return strip_accelerator(msgid).rstrip().rstrip(":：፦៖").rstrip(".").rstrip()


def derived(msgid, entries):
    """A bare term ("Synthesizer") from a labelled sibling already translated ("&Synthesizer:")."""
    if "&" in msgid or msgid.endswith(":"):
        return None
    for other, msgstr in entries.items():
        if other != msgid and plain(other) == msgid:
            return plain(msgstr)
    return None


def po_escape(text):
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def write_po(path, lang, entries, comments):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write('msgid ""\nmsgstr ""\n"Project-Id-Version: dialingo\\n"\n"MIME-Version: 1.0\\n"\n')
        f.write('"Content-Type: text/plain; charset=UTF-8\\n"\n"Content-Transfer-Encoding: 8bit\\n"\n')
        f.write(f'"Language: {lang}\\n"\n\n')
        for msgid, msgstr in entries:
            comment = comments.get(msgid)
            if comment:
                f.write(f"#. Translators: {comment}\n")
            f.write(f'msgid "{po_escape(msgid)}"\nmsgstr "{po_escape(msgstr)}"\n\n')


def write_mo(path, lang, entries):
    catalog = {"": f"Content-Type: text/plain; charset=UTF-8\nLanguage: {lang}\n"}
    catalog.update(entries)
    keys = sorted(catalog)
    ids = b""
    strs = b""
    offsets = []
    for key in keys:
        kb = key.encode("utf-8")
        vb = catalog[key].encode("utf-8")
        offsets.append((len(ids), len(kb), len(strs), len(vb)))
        ids += kb + b"\0"
        strs += vb + b"\0"
    keystart = 7 * 4 + 16 * len(keys)
    valuestart = keystart + len(ids)
    koffsets = []
    voffsets = []
    for o1, l1, o2, l2 in offsets:
        koffsets += [l1, o1 + keystart]
        voffsets += [l2, o2 + valuestart]
    output = struct.pack("Iiiiiii", 0x950412DE, 0, len(keys), 7 * 4, 7 * 4 + len(keys) * 8, 0, 0)
    output += array.array("i", koffsets + voffsets).tobytes() + ids + strs
    with open(path, "wb") as f:
        f.write(output)


def main():
    with open(os.path.join(ROOT, "i18n", "messages.json"), encoding="utf-8") as f:
        data = json.load(f)
    msgids = [m["msgid"] for m in data["messages"]]
    comments = {m["msgid"]: m["comment"] for m in data["messages"]}
    by_code = {v: k for k, v in CODES.items()}
    unknown = [m for m in msgids if m not in by_code]
    if unknown:
        print("messages without a code (add them to CODES):")
        for m in unknown:
            print("  ", repr(m))
    ours = load_translations()
    with open(os.path.join(ROOT, "addon", "manifest.ini"), encoding="utf-8") as f:
        english_summary = re.search(r'^summary\s*=\s*"([^"]*)"', f.read(), re.M).group(1)
    problems = []
    accelerators = []
    gaps = {}
    built = 0
    for lang in data["languages"]:
        mine = ours.get(lang) or {}
        reused = data["nvda"].get(lang, {})
        found = {}
        for msgid in msgids:
            msgstr = None
            code = by_code.get(msgid)
            if code in OURS_FIRST and code in mine:
                msgstr = valid(msgid, mine[code], problems, lang, accelerators)
            if msgstr is None and msgid in reused:
                msgstr = valid(msgid, reused[msgid], problems, lang, accelerators)
            if msgstr is None and code in mine:
                msgstr = valid(msgid, mine[code], problems, lang, accelerators)
            if msgstr and msgstr.strip():
                found[msgid] = msgstr
        # Bare column headers from their labelled siblings, when nothing else gave them.
        for msgid in msgids:
            if msgid not in found:
                msgstr = derived(msgid, found)
                if msgstr:
                    found[msgid] = msgstr
        entries = [(msgid, found[msgid]) for msgid in msgids if msgid in found]
        for msgid in msgids:
            if msgid not in found:
                gaps.setdefault(lang, []).append(msgid)
        if not entries:
            continue
        folder = os.path.join(ROOT, "addon", "locale", lang, "LC_MESSAGES")
        os.makedirs(folder, exist_ok=True)
        write_po(os.path.join(folder, "nvda.po"), lang, entries, comments)
        write_mo(os.path.join(folder, "nvda.mo"), lang, dict(entries))
        # The add-on store requires a summary in every translated manifest; the name is not translated.
        summary = mine.get("summary") or english_summary
        description = mine.get("description")
        if summary or description:
            with open(os.path.join(ROOT, "addon", "locale", lang, "manifest.ini"), "w", encoding="utf-8", newline="\n") as f:
                if summary:
                    f.write(f'summary = "{summary}"\n')
                if description:
                    f.write(f'description = """{description}"""\n')
        built += 1
    print(f"built {built} languages")
    for p in problems:
        print("problem:", p)
    for a in accelerators:
        print("accelerator:", a)
    for lang, missing in sorted(gaps.items()):
        print(f"gap {lang} ({len(missing)}): " + " | ".join(missing))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
