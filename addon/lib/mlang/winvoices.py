"""The voices Windows itself installs, with their languages, read from the registry.

Windows registers its OneCore voices system-wide (Speech_OneCore\\Voices\\Tokens), each with the languages
it speaks: the voices installed for each language, without configuration. NVDA's OneCore driver speaks
them; this module names them without loading it, applying the same validity checks the driver does, so a
language with no row can be sent to the Windows voice for it.
"""
import ctypes
import functools
import os
import winreg

from .scripts import base, code

ONECORE = "oneCore"
_ROOTS = (
    (winreg.HKEY_LOCAL_MACHINE, "HKEY_LOCAL_MACHINE", r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"),
    (winreg.HKEY_CURRENT_USER, "HKEY_CURRENT_USER", r"SOFTWARE\Microsoft\Speech_OneCore\Voices\Tokens"),
)


def _locale_from_lcid(lcid):
    buf = ctypes.create_unicode_buffer(85)
    if ctypes.windll.kernel32.LCIDToLocaleName(lcid, buf, 85, 0):
        return buf.value.replace("-", "_")
    return None


def _valid(hkey):
    """NVDA's OneCore driver's test: the language data and voice files the token names must exist."""
    try:
        lang_data = winreg.QueryValueEx(hkey, "langDataPath")[0]
        voice_path = winreg.QueryValueEx(hkey, "voicePath")[0]
    except OSError:
        return False
    if not isinstance(lang_data, str) or not isinstance(voice_path, str):
        return False
    return os.path.isfile(os.path.expandvars(lang_data)) and os.path.isfile(os.path.expandvars(voice_path + ".apm"))


def voices():
    """[(voice id as NVDA's OneCore driver names it, display name, [locales])] for every installed voice."""
    out = []
    seen = set()
    for root, root_name, path in _ROOTS:
        try:
            tokens = winreg.OpenKey(root, path)
        except OSError:
            continue
        with tokens:
            index = 0
            while True:
                try:
                    token = winreg.EnumKey(tokens, index)
                except OSError:
                    break
                index += 1
                if token in seen:
                    continue
                try:
                    with winreg.OpenKey(tokens, token) as hkey:
                        if not _valid(hkey):
                            continue
                        with winreg.OpenKey(hkey, "Attributes") as attributes:
                            try:
                                name = winreg.QueryValueEx(attributes, "Name")[0]
                            except OSError:
                                name = token
                            try:
                                languages = winreg.QueryValueEx(attributes, "Language")[0]
                            except OSError:
                                continue
                except OSError:
                    continue
                locales = []
                for part in str(languages).split(";"):
                    part = part.strip()
                    if not part:
                        continue
                    try:
                        locale = _locale_from_lcid(int(part, 16))
                    except ValueError:
                        locale = None
                    if locale and locale not in locales:
                        locales.append(locale)
                if locales:
                    seen.add(token)
                    out.append((f"{root_name}\\{path}\\{token}", str(name), locales))
    return out


@functools.lru_cache(maxsize=1)
def by_language():
    """{language code (scripts.code): [(voice id, display name, locale)]}, in registry order, so the first is the one
    Windows lists first for the language."""
    table = {}
    for voice_id, name, locales in voices():
        for locale in locales:
            table.setdefault(code(locale), []).append((voice_id, name, locale))
    return table


def refresh():
    by_language.cache_clear()


def languages():
    """The locales Windows voices speak, one per voice language, for the detector's voice tier."""
    out = []
    for entries in by_language().values():
        locale = entries[0][2]
        if locale not in out:
            out.append(locale)
    return out


def voice_for(language):
    """(voice id, display name, locale) of the Windows voice for a language: an exact locale match first,
    else the first voice of the language, else of its base language (a Mandarin voice for Cantonese
    beats none); None when Windows has none."""
    entries = by_language().get(code(language))
    if not entries:
        b = base(language)
        entries = next((e for e in by_language().values() if base(e[0][2]) == b), None)
    if not entries:
        return None
    wanted = language.replace("-", "_").lower()
    for entry in entries:
        if entry[2].lower() == wanted:
            return entry
    return entries[0]
