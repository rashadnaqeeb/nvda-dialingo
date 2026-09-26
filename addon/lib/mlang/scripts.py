"""Script detection: which writing system a run of text is in, and which languages write it.

Windows names the scripts a language is written in (GetLocaleInfoEx with LOCALE_SSCRIPTS) and the
`regex` module NVDA bundles classifies letters by Unicode script, so no data files are needed.
"""
import ctypes
import functools

import regex

LOCALE_SSCRIPTS = 0x6C

# Windows lists locale-data script codes that are not Unicode scripts; each stands for a set of them.
_EXPANSIONS = {
    "Hans": ("Hani",),
    "Hant": ("Hani",),
    "Jpan": ("Hani", "Hira", "Kana"),
    "Kore": ("Hang", "Hani"),
}

# Scripts of the East Asian family share text freely; a run of them is one segment, up to a sentence end.
CJK = frozenset(("Hani", "Hira", "Kana", "Hang"))
_CJK_SENTENCE_ENDS = set("。！？.!?")

_kernel32 = ctypes.windll.kernel32 if hasattr(ctypes, "windll") else None


def base(language):
    """'fr' for 'fr_FR', 'fr-fr', 'FR'."""
    return language.replace("-", "_").split("_")[0].lower() if language else ""


# Codes a recognizer answers where Windows, NVDA, and the synthesizers use another: fastText's 'no' is
# Norwegian Bokmål ('nb') and its 'tl' is Filipino ('fil'). Configured tags go through it too, so a row typed
# 'no' meets the recognizer's answer.
_ALIASES = {"no": "nb", "tl": "fil"}


def code(language):
    """The base code languages are compared by: base(), with a recognizer's alias mapped, 'nb' for 'no_NO'."""
    b = base(language)
    return _ALIASES.get(b, b)


def windows_tag(language):
    return language.replace("_", "-") if language else language


def normalize(language):
    """NVDA's spelling of a tag: 'fr_FR' for 'fr-fr' or 'FR-fr'. NVDA's locale data (character descriptions,
    symbols) falls back from 'fr_FR' to 'fr' on the underscore alone, so a hyphenated tag would get English."""
    if not language:
        return language
    parts = language.replace("-", "_").split("_")
    parts[0] = parts[0].lower()
    if len(parts) >= 2:
        parts[1] = parts[1].upper()
    return "_".join(parts)


_TAG_SHAPE = regex.compile(r"^[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})*$")


def is_language(language):
    """Whether a string is a language tag Windows knows, so a typed 'French' is not taken for one."""
    if not language or not _TAG_SHAPE.match(language):
        return False
    if _kernel32 is None:
        return True
    buf = ctypes.create_unicode_buffer(85)
    return bool(_kernel32.GetLocaleInfoEx(windows_tag(language), LOCALE_SSCRIPTS, buf, 85))


@functools.lru_cache(maxsize=256)
def scripts_of(language):
    """The Unicode scripts a language is written in, from the system's locale data; Latin when unknown."""
    if not language:
        return frozenset(("Latn",))
    listed = None
    if _kernel32 is not None:
        buf = ctypes.create_unicode_buffer(85)
        n = _kernel32.GetLocaleInfoEx(windows_tag(language), LOCALE_SSCRIPTS, buf, 85)
        if n:
            listed = [s for s in buf.value.split(";") if s]
    if not listed:
        listed = _FALLBACK.get(base(language), ["Latn"])
    if not _names_script(language):
        listed = list(listed) + _ALSO.get(base(language), [])
    out = set()
    for code in listed:
        out.update(_EXPANSIONS.get(code, (code,)))
    return frozenset(out)


def _names_script(language):
    """Whether a tag names its script, as 'sr_Latn_RS' does, so the language is written in that one only."""
    parts = language.replace("-", "_").split("_")[1:]
    return any(len(p) == 4 and p.isalpha() for p in parts)


# Scripts a language is also written in that Windows leaves out of an untagged locale: 'sr' and 'sr_RS' list
# Latin alone, though Serbian pages are mostly Cyrillic.
_ALSO = {"sr": ["Cyrl"], "bs": ["Cyrl"], "uz": ["Cyrl"], "az": ["Cyrl"]}

# Used only where the Windows call fails (it does not on any supported Windows).
_FALLBACK = {
    "ru": ["Cyrl"], "uk": ["Cyrl"], "bg": ["Cyrl"], "sr": ["Cyrl", "Latn"], "mk": ["Cyrl"], "be": ["Cyrl"],
    "kk": ["Cyrl"], "mn": ["Cyrl"], "ar": ["Arab"], "fa": ["Arab"], "ur": ["Arab"], "he": ["Hebr"],
    "el": ["Grek"], "hi": ["Deva"], "mr": ["Deva"], "ne": ["Deva"], "bn": ["Beng"], "pa": ["Guru"],
    "gu": ["Gujr"], "ta": ["Taml"], "te": ["Telu"], "kn": ["Knda"], "ml": ["Mlym"], "th": ["Thai"],
    "ka": ["Geor"], "hy": ["Armn"], "am": ["Ethi"], "km": ["Khmr"], "lo": ["Laoo"], "my": ["Mymr"],
    "si": ["Sinh"], "zh": ["Hani"], "ja": ["Hani", "Hira", "Kana"], "ko": ["Hang", "Hani"],
}


def primary_script(language):
    """The one script to treat as the language's own: the single listed one, else Latn if listed, else any."""
    scripts = scripts_of(language)
    if len(scripts) == 1:
        return next(iter(scripts))
    if "Hira" in scripts:
        return "Hira"
    if "Hang" in scripts:
        return "Hang"
    return "Latn" if "Latn" in scripts else sorted(scripts)[0]


def may_leave_latin(text):
    """Whether Latin-default text can hold a letter of another script at all: nothing below U+0300 is one."""
    return any(ord(c) >= 0x300 and c.isalpha() for c in text)


def is_text(piece):
    """At least two letters, or one ideograph, which is a word by itself; a lone borrowed letter is a symbol."""
    letters = 0
    for c in piece:
        if c.isalpha():
            if "一" <= c <= "鿿" or "㐀" <= c <= "䶿":
                return True
            letters += 1
            if letters >= 2:
                return True
    return False


@functools.lru_cache(maxsize=32)
def _segmenter(scripts):
    """A regex whose named groups classify every letter run by script; `other` catches unlisted scripts."""
    # A combining mark (script Inherited) stays with the letter it follows, so a decomposed accent or a
    # virama written separately never starts a run of its own. So does a modifier letter of script Common,
    # which sits inside words of several scripts: the katakana long-vowel mark, the Arabic tatweel, the
    # apostrophe letter of Ukrainian. It never starts a run either.
    common = r"[\p{Lm}&&\p{Zyyy}]"
    parts = [r"(?P<%s>\p{%s}[\p{%s}\p{M}%s]*)" % (s, s, s, common) for s in sorted(scripts)]
    excluded = "".join(r"--\p{%s}" % s for s in sorted(scripts))
    parts.append(r"(?P<other>[\p{L}%s--%s][[\p{L}\p{M}]%s]*)" % (excluded, common, excluded))
    return regex.compile("|".join(parts), regex.V1)


def letter_runs(text, scripts):
    """(script, start, end) for each run of letters, script being one of `scripts` or 'other'."""
    out = []
    for m in _segmenter(frozenset(scripts)).finditer(text):
        out.append((m.lastgroup, m.start(), m.end()))
    return out


def segments(text, default_script, scripts, default_scripts=()):
    """Split `text` into (script_set, start, end) segments: consecutive letter runs
    of one script (or of the CJK family, within a sentence) merge with the non-letter text between them;
    text before a segment's first letter belongs to it, text after a foreign segment's last letter goes to
    the default. A segment is foreign without the default's primary script, or with a script of the CJK
    family the default does not write (kana for Chinese). The script_set of a default-script segment is None."""
    runs = letter_runs(text, scripts)
    if not runs:
        return [(None, 0, len(text))]
    groups = []
    for script, start, end in runs:
        scripts_here = {script}
        if groups:
            prev = groups[-1]
            cjk = script in CJK and bool(prev[0] & CJK)
            same = (script in prev[0] or cjk) and not (
                cjk and any(c in _CJK_SENTENCE_ENDS for c in text[prev[2]:start])
            )
            if same:
                prev[0].add(script)
                prev[2] = end
                continue
        groups.append([scripts_here, start, end])
    out = []
    cursor = 0
    for i, (scripts_here, start, end) in enumerate(groups):
        foreign = default_script not in scripts_here or bool(default_scripts and (scripts_here & CJK) - set(default_scripts))
        seg_start = cursor
        if foreign:
            out.append((scripts_here, seg_start, end))
            cursor = end
        else:
            last = groups[i + 1][1] if i + 1 < len(groups) else len(text)
            out.append((None, seg_start, last))
            cursor = last
    if cursor < len(text):
        out.append((None, cursor, len(text)))
    return _merge(out)


def _merge(segs):
    out = []
    for scripts_here, start, end in segs:
        if start >= end:
            continue
        if out and out[-1][0] is None and scripts_here is None:
            out[-1] = (None, out[-1][1], end)
        else:
            out.append((scripts_here, start, end))
    return out
