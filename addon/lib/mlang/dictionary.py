"""The Windows Spell Checking API as evidence: whether a language's dictionary rejects a word of a text.

comtypes, which NVDA bundles, with the interfaces declared here so no type library is generated.
Every call degrades to "no evidence" (None) when the API, a dictionary, or the calling thread's COM
apartment is unavailable.
"""
import threading
import time

from ctypes import POINTER, c_wchar_p, c_ulong, c_int
from ctypes.wintypes import BOOL

import comtypes
import comtypes.client
from comtypes import GUID, COMMETHOD, HRESULT, IUnknown

from .scripts import base, windows_tag


class IEnumString(IUnknown):
    _iid_ = GUID("{00000101-0000-0000-C000-000000000046}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Next", (["in"], c_ulong, "celt"), (["out"], POINTER(c_wchar_p), "rgelt"), (["out"], POINTER(c_ulong), "pceltFetched")),
        COMMETHOD([], HRESULT, "Skip", (["in"], c_ulong, "celt")),
        COMMETHOD([], HRESULT, "Reset"),
        COMMETHOD([], HRESULT, "Clone", (["out"], POINTER(POINTER(IUnknown)), "ppenum")),
    ]


class ISpellingError(IUnknown):
    _iid_ = GUID("{B7C82D61-FBE8-4B47-9B27-6C0D2E0DE0A3}")
    _methods_ = [
        COMMETHOD(["propget"], HRESULT, "StartIndex", (["out"], POINTER(c_ulong), "value")),
        COMMETHOD(["propget"], HRESULT, "Length", (["out"], POINTER(c_ulong), "value")),
        COMMETHOD(["propget"], HRESULT, "CorrectiveAction", (["out"], POINTER(c_int), "value")),
        COMMETHOD(["propget"], HRESULT, "Replacement", (["out"], POINTER(c_wchar_p), "value")),
    ]


class IEnumSpellingError(IUnknown):
    _iid_ = GUID("{803E3BD4-2828-4410-8290-418D1D73C762}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Next", (["out"], POINTER(POINTER(ISpellingError)), "value")),
    ]


class ISpellChecker(IUnknown):
    _iid_ = GUID("{B6FD0B71-E2BC-4653-8EC5-4EA3F8B3E6E0}")
    _methods_ = [
        COMMETHOD(["propget"], HRESULT, "LanguageTag", (["out"], POINTER(c_wchar_p), "value")),
        COMMETHOD([], HRESULT, "Check", (["in"], c_wchar_p, "text"), (["out"], POINTER(POINTER(IEnumSpellingError)), "value")),
        COMMETHOD([], HRESULT, "Suggest", (["in"], c_wchar_p, "word"), (["out"], POINTER(POINTER(IEnumString)), "value")),
        COMMETHOD([], HRESULT, "Add", (["in"], c_wchar_p, "word")),
        COMMETHOD([], HRESULT, "Ignore", (["in"], c_wchar_p, "word")),
        COMMETHOD([], HRESULT, "AutoCorrect", (["in"], c_wchar_p, "from_"), (["in"], c_wchar_p, "to")),
        COMMETHOD([], HRESULT, "GetOptionValue", (["in"], c_wchar_p, "optionId"), (["out"], POINTER(c_int), "value")),
        COMMETHOD(["propget"], HRESULT, "OptionIds", (["out"], POINTER(POINTER(IEnumString)), "value")),
        COMMETHOD(["propget"], HRESULT, "Id", (["out"], POINTER(c_wchar_p), "value")),
        COMMETHOD(["propget"], HRESULT, "LocalizedName", (["out"], POINTER(c_wchar_p), "value")),
        COMMETHOD([], HRESULT, "add_SpellCheckerChanged", (["in"], POINTER(IUnknown), "handler"), (["out"], POINTER(c_ulong), "eventCookie")),
        COMMETHOD([], HRESULT, "remove_SpellCheckerChanged", (["in"], c_ulong, "eventCookie")),
        COMMETHOD([], HRESULT, "GetOptionDescription", (["in"], c_wchar_p, "optionId"), (["out"], POINTER(POINTER(IUnknown)), "value")),
        COMMETHOD([], HRESULT, "ComprehensiveCheck", (["in"], c_wchar_p, "text"), (["out"], POINTER(POINTER(IEnumSpellingError)), "value")),
    ]


class ISpellCheckerFactory(IUnknown):
    _iid_ = GUID("{8E018A9D-2415-4677-BF08-794EA61F94BB}")
    _methods_ = [
        COMMETHOD(["propget"], HRESULT, "SupportedLanguages", (["out"], POINTER(POINTER(IEnumString)), "value")),
        COMMETHOD([], HRESULT, "IsSupported", (["in"], c_wchar_p, "languageTag"), (["out"], POINTER(BOOL), "value")),
        COMMETHOD([], HRESULT, "CreateSpellChecker", (["in"], c_wchar_p, "languageTag"), (["out"], POINTER(POINTER(ISpellChecker)), "value")),
    ]


CLSID_SpellCheckerFactory = GUID("{7AB36653-1796-484B-BDFA-E74F1DB7C1DC}")
CORRECTIVE_ACTION_DELETE = 3

# Regions to try first for a bare language code; any installed region of the language serves otherwise.
PREFERRED = {"en": "en-US", "fr": "fr-FR", "es": "es-ES", "de": "de-DE", "it": "it-IT", "pt": "pt-BR",
             "nl": "nl-NL", "ru": "ru-RU", "pl": "pl-PL", "sv": "sv-SE", "da": "da-DK", "nb": "nb-NO",
             "fi": "fi-FI", "tr": "tr-TR", "cs": "cs-CZ", "el": "el-GR", "hu": "hu-HU", "ro": "ro-RO"}


def _enum_strings(e):
    out = []
    while True:
        try:
            s, fetched = e.Next(1)
        except Exception:
            break
        if not fetched or not s:
            break
        out.append(s)
    return out


class Dictionary:
    """rejects_a_word(text, language) -> True, False, or None when no dictionary for the language exists."""

    def __init__(self):
        self._local = threading.local()
        self.cache = {}
        self.calls = 0
        self.tags = None  # installed dictionary tags, filled on first use

    def _factory(self):
        # COM objects belong to the apartment of the thread that made them; one factory per thread.
        factory = getattr(self._local, "factory", None)
        if factory is None:
            factory = comtypes.client.CreateObject(CLSID_SpellCheckerFactory, interface=ISpellCheckerFactory)
            self._local.factory = factory
            self._local.checkers = {}
        return factory

    def tag_for(self, language):
        """The installed dictionary tag for a language, or None."""
        factory = self._factory()
        if self.tags is None:
            try:
                self.tags = _enum_strings(factory.SupportedLanguages)
            except Exception:
                self.tags = []
        tag = windows_tag(language)
        root = base(language)
        candidates = [tag, PREFERRED.get(root, "")] + [t for t in self.tags if base(t) == root]
        for candidate in candidates:
            if candidate and any(t.lower() == candidate.lower() for t in self.tags):
                return candidate
        try:
            if factory.IsSupported(tag):
                return tag
        except Exception:
            pass
        return None

    RETRY_SECONDS = 300  # a missing dictionary is looked for again this often: language packs install mid-session

    def checker(self, language):
        """The spell checker for a language, or None while it has none. A failure to make one, and the
        absence of a dictionary, are remembered for RETRY_SECONDS only, on this thread."""
        factory = self._factory()
        checkers = self._local.checkers
        if language in checkers:
            return checkers[language]
        missing = getattr(self._local, "missing", None)
        if missing is None:
            missing = self._local.missing = {}
        now = time.monotonic()
        if now - missing.get(language, -self.RETRY_SECONDS) < self.RETRY_SECONDS:
            return None
        checker = None
        try:
            if language in missing:
                self.tags = None  # a dictionary may have been installed since
            tag = self.tag_for(language)
            if tag:
                checker = factory.CreateSpellChecker(tag)
        except Exception:
            checker = None
        if checker is None:
            missing[language] = now
            return None
        missing.pop(language, None)
        checkers[language] = checker
        return checker

    def has(self, language):
        try:
            return self.checker(language) is not None
        except Exception:
            return False

    def refresh(self):
        """Forgets which dictionaries exist, on the calling thread: after a language feature was installed."""
        self.tags = None
        self.cache.clear()
        for name in ("checkers", "missing"):
            store = getattr(self._local, name, None)
            if store is not None:
                store.clear()

    def rejects_everywhere(self, text, language):
        """rejects_a_word in every installed region of the language: US English rejects "metres" and
        Canadian English knows it."""
        verdict = self.rejects_a_word(text, language)
        if verdict is not True:
            return verdict
        root = base(language)
        for tag in self.tags or ():
            if base(tag) == root and self.rejects_a_word(text, tag) is False:
                return False
        return True

    def rejects_a_word(self, text, language):
        key = (language, text)
        if key in self.cache:
            return self.cache[key]
        try:
            checker = self.checker(language)
            if checker is None:
                return None  # not cached: the dictionary may appear
            self.calls += 1
            errors = checker.Check(text)
            result = False
            try:
                # A repeated word ("so so" from "so-so", "très très") is an error to delete, not an unknown word.
                while not result:
                    error = errors.Next()
                    if not error:
                        break
                    result = error.CorrectiveAction != CORRECTIVE_ACTION_DELETE
            except Exception:
                result = False
        except Exception:
            return None  # a failed call is no evidence, and no memory either
        if len(self.cache) > 8192:
            self.cache.clear()
        self.cache[key] = result
        return result
