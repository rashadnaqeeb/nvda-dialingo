"""Probe the Windows Spell Checking API (ISpellCheckerFactory) for installed language dictionaries."""
import time
import comtypes
import comtypes.client
from comtypes import GUID, COMMETHOD, HRESULT, IUnknown
from ctypes import POINTER, c_wchar_p, c_ulong, c_int, byref
from ctypes.wintypes import BOOL


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


def enum_strings(e):
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


def rejects_a_word(checker, text):
    errors = checker.Check(text)
    try:
        err = errors.Next()
    except Exception:
        return False
    return bool(err)


def main():
    factory = comtypes.client.CreateObject(CLSID_SpellCheckerFactory, interface=ISpellCheckerFactory)
    langs = enum_strings(factory.SupportedLanguages)
    print("Supported spell-check languages (%d):" % len(langs), " ".join(langs))
    for tag in ["en-US", "fr-FR", "es-ES", "de-DE", "it-IT", "pt-BR", "ru-RU"]:
        print(f"  IsSupported({tag}) = {bool(factory.IsSupported(tag))}")
    checkers = {}
    for tag in ["en-US", "fr-FR", "es-ES"]:
        try:
            checkers[tag] = factory.CreateSpellChecker(tag)
        except Exception as e:
            print(f"  CreateSpellChecker({tag}) failed: {e}")
    if not checkers:
        return
    samples = ["Closed till Fri", "Contact info", "mon cher", "malgre la haute estime que je professe pour",
               "la naranja", "el escritorio", "Hola buenos dias", "Prince son", "Send message", "Guardar", "Oui", "Hola",
               "Tape position error at end of medium"]
    for text in samples:
        row = []
        for tag, checker in checkers.items():
            t0 = time.perf_counter()
            try:
                r = rejects_a_word(checker, text)
            except Exception as e:
                r = f"err {e}"
            row.append(f"{tag}: rejects={r} ({(time.perf_counter()-t0)*1000:.2f} ms)")
        print(f"{text!r:50} " + " | ".join(row))


if __name__ == "__main__":
    main()
