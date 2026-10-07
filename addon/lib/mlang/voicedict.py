"""The voice dictionaries of the rows' voices, applied to the text those voices speak.

NVDA keeps a voice dictionary per synthesizer and voice, but loads only the current voice's and applies it
to everything spoken. A row's voice has its own file among NVDA's voice dictionaries (the same file NVDA
would load if that voice were the current one), edited from the Dialingo panel with NVDA's dictionary
dialog. Its entries apply to the runs in the row's language, in the add-on's filter, ahead of NVDA's own
dictionaries. The files are reread when they change. NVDA is imported inside the functions, so `apply` runs
under the tests.
"""
import os

_dictionaries = {}  # path -> (modification time or None, SpeechDict)
_names = {}  # (synthesizer, voice id) -> the voice's display name, which names the file


def path_for(synth, voice_name):
    """NVDA's voice dictionary file for a synthesizer's voice."""
    from NVDAState import WritePaths
    from speechDictHandler import dictFormatUpgrade

    return os.path.join(WritePaths.voiceDictsDir, synth, dictFormatUpgrade.createVoiceDictFileName(synth, voice_name))


def current_path():
    """The file of the voice dictionary NVDA has loaded for the current voice; None when unknown."""
    try:
        from speechDictHandler import definitions
        from speechDictHandler.types import DictionaryType

        return definitions._getDictionaryDefinition(DictionaryType.VOICE).path
    except Exception:
        return None


def is_current(path):
    current = current_path()
    return bool(current) and os.path.normcase(os.path.abspath(current)) == os.path.normcase(os.path.abspath(path))


def voice_name(synth, voice):
    """A voice's display name from a synthesizer instance that already exists; None when none does, so
    speech never waits for a synthesizer to load."""
    key = (synth, voice)
    name = _names.get(key)
    if name is not None:
        return name
    from . import hosts

    guest = hosts.existing(synth)
    if guest is None:
        return None
    try:
        info = guest.availableVoices.get(voice)
        name = info.displayName if info is not None else None
    except Exception:
        name = None
    if name:
        _names[key] = name
    return name


def load(path):
    """The dictionary in a file, reread when the file changed; empty when there is none."""
    from speechDictHandler.types import SpeechDict

    try:
        mtime = os.stat(path).st_mtime
    except OSError:
        mtime = None
    cached = _dictionaries.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    dictionary = SpeechDict()
    if mtime is not None:
        try:
            dictionary.load(path)
        except Exception:
            from logHandler import log

            log.debugWarning(f"dialingo: voice dictionary {path} could not be read", exc_info=True)
    _dictionaries[path] = (mtime, dictionary)
    return dictionary


def dictionary(synth, voice):
    """The dictionary of a synthesizer's voice, or None when it has none or the voice cannot be named."""
    name = voice_name(synth, voice)
    if not name:
        return None
    loaded = load(path_for(synth, name))
    return loaded if loaded else None


def apply(seq, LangChangeCommand, dict_for_lang):
    """`seq` with each text item passed through the dictionary of its language's row voice.

    dict_for_lang(lang) -> an object with `sub(text)` for a language whose row voice has entries, else None.
    Text before the first language command is the default language's and is left alone. The same sequence
    comes back when nothing changed.
    """
    out = None
    lang = None
    for index, item in enumerate(seq):
        if isinstance(item, LangChangeCommand):
            lang = item.lang
            continue
        if not lang or not isinstance(item, str) or not item:
            continue
        dictionary = dict_for_lang(lang)
        if dictionary is None:
            continue
        text = dictionary.sub(item)
        if text != item:
            if out is None:
                out = list(seq)
            out[index] = text
    return out if out is not None else seq
