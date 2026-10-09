# Dialingo's global plugin: language detection on every speech sequence, the settings
# panel, and the scripts. Detection inserts standard language commands, so it works with any synthesizer
# that switches languages by itself, and with the add-on's language table synthesizer for the rest.

import functools
import os
import sys
import threading

import addonHandler

_addon = addonHandler.getCodeAddon()
_lib = os.path.join(_addon.path, "lib")
if _lib not in sys.path:
    sys.path.insert(0, _lib)

import config  # noqa: E402
import controlTypes  # noqa: E402
import globalPluginHandler  # noqa: E402
import globalVars  # noqa: E402
import gui  # noqa: E402
import synthDriverHandler  # noqa: E402
from logHandler import log  # noqa: E402
from speech import getCurrentLanguage  # noqa: E402
from speech.commands import LangChangeCommand  # noqa: E402
from speech.extensions import filter_speechSequence  # noqa: E402
from speech.languageHandling import getSpeechSequenceWithLangs  # noqa: E402

from mlang import leaving, pipes, policy, prosody, rename, update, voicedict, winvoices  # noqa: E402
from mlang import table as T  # noqa: E402
from mlang.detector import MODES, MODE_OFF, Detector  # noqa: E402
from mlang.hosts import DRIVER_NAME  # noqa: E402
from mlang.scripts import base  # noqa: E402
from mlang.sequence import filter_sequence, locked_sequence, untagged_sequence  # noqa: E402

from . import context, lock, settings  # noqa: E402
from .grid import GridLabels  # noqa: E402

addonHandler.initTranslation()

MODE_LABELS = {
    # Translators: A detection mode: no language switching at all, not even for text applications tag with
    # a language.
    "off": _("Off"),
    # Translators: A detection mode: text in another writing system is switched, and text applications tag
    # with a language is read in it; nothing is guessed.
    "script": _("Script and tags only"),
    # Translators: A detection mode: text in the default script is detected clause by clause too.
    "full": _("Full"),
}


def reader_words():
    """NVDA's own vocabulary as it reaches speech: role and state names, which are never scored."""
    words = set()
    for enum in (controlTypes.Role, controlTypes.State):
        # Only members with a label: displayString logs an error for the few without one.
        try:
            labels = next(iter(enum))._displayStringLabels
        except Exception:
            continue
        for member, label in labels.items():
            words.add(label.strip().lower())
            if enum is controlTypes.State:
                try:
                    words.add(member.negativeDisplayString.strip().lower())
                except Exception:
                    pass
    words.discard("")
    return words


def synth_languages():
    """The languages the current synthesizer's voices speak, plus the Windows voices' when they are in use,
    sorted, as a tuple: the detector's second tier for a script nobody configured."""
    synth = synthDriverHandler.getSynth()
    langs = set()
    try:
        if synth is not None:
            langs.update(lang for lang in synth.availableLanguages if lang)
    except Exception:
        pass
    try:
        if policy.windows_voices_wanted(config.conf):
            langs.update(winvoices.languages())
    except Exception:
        log.debugWarning("dialingo: Windows voices could not be listed", exc_info=True)
    return tuple(sorted(langs))


def symbol_names(locale):
    """Whether NVDA's symbol table for `locale` names a character at every symbol level, so a voice of that
    language reads it by name: the English table names ∑ but no Greek, Arabic, or Cyrillic letter. Read at
    each call, so an edit in NVDA's punctuation dialog counts at once. A locale with no table falls back to
    English, as NVDA's symbol processing does."""

    def named(character):
        try:
            import characterProcessing

            processors = characterProcessing._localeSpeechSymbolProcessors
            try:
                processor = processors.fetchLocaleData(locale)
            except LookupError:
                processor = processors.fetchLocaleData("en")
            symbol = processor.computedSymbols.get(character)
            return symbol is not None and bool(symbol.replacement) and symbol.level == characterProcessing.SymbolLevel.NONE
        except Exception:
            log.debugWarning("dialingo: the symbol table for %s could not be read" % locale, exc_info=True)
            return False

    return named


class Engine:
    """Owns the recognizer, the dictionary, and a detector kept in step with the configuration.

    The recognizer's model (17 MB) is loaded on a thread of its own at startup; until it is in, `current()`
    is None and speech passes through, so the first utterance is not held back by the load."""

    def __init__(self):
        self.backend = None
        self.strict_backend = None
        self.dictionary = None
        self.detector = None
        self.key = None
        self.table_raw = None
        self.table = T.Table()
        self.detected_languages = ()
        self.undetected_languages = ()
        self.table_rows = []
        self.offsets = {}
        self.offsets_key = None
        self.available = ()
        self.available_key = None
        self.failed = False
        self.words = reader_words()
        self.unit_context = None  # set by the plugin once the caret speech wrappers are installed
        self.grid = GridLabels()
        self.lock = threading.Lock()
        self.ready = threading.Event()
        threading.Thread(target=self._warm, name="dialingo-warm", daemon=True).start()

    def _warm(self):
        try:
            self._backend(bool(config.conf[T.CONFIG_SECTION]["strict"]))
        except Exception:
            log.error("dialingo: the recognizer could not be loaded; language detection is off", exc_info=True)
            self.failed = True
        finally:
            self.ready.set()

    def _backend(self, strict):
        with self.lock:
            if self.backend is None:
                from mlang import recognizers

                self.backend = recognizers.FastTextBackend()
            if not strict:
                return self.backend
            if self.strict_backend is None:
                from mlang import recognizers

                try:
                    self.strict_backend = recognizers.EnsembleBackend(self.backend)
                except Exception:
                    log.warning("dialingo: Windows language detection unavailable; strict mode ignored", exc_info=True)
                    self.strict_backend = self.backend
            return self.strict_backend

    def _sync_table(self):
        """Reparses the table when the saved JSON changed; the parsed rows serve detection and prosody alike."""
        raw = config.conf[T.CONFIG_SECTION]["table"]
        if raw != self.table_raw:
            table = T.Table.from_json(raw)
            self.table_raw = raw
            self.table = table
            self.detected_languages = tuple(table.detected())
            self.undetected_languages = tuple(table.undetected())
            self.table_rows = table.rows
            self.offsets_key = None

    def symbol_level(self, locale, level):
        """The symbol level for text NVDA speaks in `locale`: the row's own for that language, or `level`. Only
        NVDA's configured level is replaced; a level a caller asked for (all symbols when spelling) stands.
        The default language has no row, so it keeps NVDA's setting."""
        if not locale:
            return level
        try:
            if level != config.conf["speech"]["symbolLevel"] or not language_switching():
                return level
            self._sync_table()
            row = self.table.row_for(locale)
            if row is None or row.symbolLevel is None or base(locale) == base(getCurrentLanguage()):
                return level
            import characterProcessing

            return characterProcessing.SymbolLevel(row.symbolLevel)
        except Exception:
            log.debugWarning("dialingo: no symbol level for %s" % locale, exc_info=True)
            return level

    def symbol_locale(self, locale):
        """The language whose symbol names text NVDA speaks in `locale` is read with: the default's where the
        language table has no voice for `locale`, since the default voice then reads it in its own language.
        An application whose interface is French tags its English text French too, and with no French row an
        English voice would otherwise say "parenthèse gauche". Other synthesizers keep NVDA's own handling."""
        if not locale:
            return locale
        try:
            synth = synthDriverHandler.getSynth()
            if synth is None or synth.name != DRIVER_NAME:
                return locale
            default = getCurrentLanguage()
            if base(locale) == base(default) or synth.languageIsSupported(locale):
                return locale
            return default
        except Exception:
            log.debugWarning("dialingo: no symbol language for %s" % locale, exc_info=True)
            return locale

    def _dictionary(self):
        if self.dictionary is None:
            try:
                from mlang.dictionary import Dictionary

                self.dictionary = Dictionary()
            except Exception:
                log.warning("dialingo: spell checking API unavailable; dictionary evidence off", exc_info=True)
                self.dictionary = False
        return self.dictionary or None

    def language_lock(self):
        """The language lock in effect: lock.AUTOMATIC, lock.DEFAULT, or a row's language. Detection mode off
        is the default's lock: no language switches at all, not even for text an application tagged."""
        self._sync_table()
        locked = lock.stored(self.table)
        if locked == lock.AUTOMATIC and config.conf[T.CONFIG_SECTION]["mode"] == MODE_OFF:
            return lock.DEFAULT
        return locked

    def ignores_tag(self, lang):
        """Whether text an application tagged `lang` is read as untagged: the row that would speak it has
        detection off. The default language has no row."""
        self._sync_table()
        if not self.undetected_languages or not lang:
            return False
        row = self.table.row_for(lang)
        return row is not None and not row.detect and base(lang) != base(getCurrentLanguage())

    def current(self):
        """The detector for the current configuration, default language, and table; None when off, locked to
        one language, broken, or without language switching."""
        if self.failed or not self.ready.is_set() or not language_switching():
            return None
        section = config.conf[T.CONFIG_SECTION]
        mode = section["mode"]
        if mode not in MODES:
            mode = "full"
        if mode == MODE_OFF or self.language_lock():
            return None
        default = getCurrentLanguage()
        self._sync_table()
        configured = self.detected_languages
        excluded = self.undetected_languages
        strict = bool(section["strict"])
        available = self._available(section)
        key = (mode, default, configured, excluded, strict, available)
        if key != self.key:
            try:
                backend = self._backend(strict)
                if self.detector is None or self.detector.backend is not backend:
                    self.detector = Detector(backend, default, configured, self._dictionary(), mode, self.words)
                else:
                    self.detector.mode = mode
                self.detector.configure(default, configured, available, excluded, symbol_names(default))
                self.key = key
            except Exception:
                log.error("dialingo: language detection could not start", exc_info=True)
                self.failed = True
                return None
        return self.detector

    def _available(self, section):
        """synth_languages(), listed again only when the synthesizer, the table, or the Windows voices
        setting changed, not on every sequence."""
        synth = synthDriverHandler.getSynth()
        # The host's name too: a language table rebuilt around another default may reuse the old one's id.
        host = getattr(synth, "host", None) if getattr(synth, "name", None) == DRIVER_NAME else None
        key = (
            id(synth),
            getattr(synth, "name", None),
            getattr(host, "name", None),
            self.table_raw,
            bool(section["useWindowsVoices"]),
        )
        if key != self.available_key:
            self.available = synth_languages()
            self.available_key = key
        return self.available

    def filter(self, sequence):
        if not language_switching():
            # NVDA drops the language commands, so a row's prosody and dictionary would apply to the default voice.
            return sequence
        try:
            locked = self.language_lock()
        except Exception:
            log.error("dialingo: the language lock could not be read", exc_info=True)
            locked = lock.AUTOMATIC
        if locked:
            try:
                sequence = locked_sequence(sequence, lock.language(locked))
            except Exception:
                log.error("dialingo: the language lock failed on a sequence", exc_info=True)
        else:
            try:
                sequence = untagged_sequence(sequence, self.ignores_tag)
            except Exception:
                log.error("dialingo: tags for languages with detection off could not be dropped", exc_info=True)
        try:
            detector = self.current()
            if detector is not None:
                try:
                    detector.labels = self.grid.current()
                except Exception:
                    log.debugWarning("dialingo: grid labels unavailable", exc_info=True)
                try:
                    sequence = filter_sequence(
                        sequence,
                        detector,
                        detector.default_tag,
                        config.conf[T.CONFIG_SECTION]["detectInDefaultTagged"],
                        unit_language=self.unit_context.language_for if self.unit_context else None,
                        line_runs=functools.partial(self.unit_context.line_runs, detector) if self.unit_context else None,
                    )
                finally:
                    detector.labels = ()
        except Exception:
            log.error("dialingo: detection failed on a sequence", exc_info=True)
        try:
            sequence = self.with_prosody(sequence)
        except Exception:
            log.error("dialingo: applying row parameters failed on a sequence", exc_info=True)
        try:
            sequence = self.with_voice_dicts(sequence)
        except Exception:
            log.error("dialingo: applying the row voices' dictionaries failed on a sequence", exc_info=True)
        return sequence

    def with_voice_dicts(self, sequence):
        """Each row voice's own voice dictionary applies to the text in its language. NVDA applies one voice
        dictionary, the current voice's, to everything, so a row whose voice is the current one needs nothing
        here. Off while NVDA's dictionary processing is off, as when a dictionary dialog is open."""
        if not globalVars.speechDictionaryProcessing:
            return sequence
        self._sync_table()
        if not any(r.get("voice") for r in self.table_rows):
            return sequence
        synth = synthDriverHandler.getSynth()
        if synth is None:
            return sequence
        engine = getattr(synth, "host", None) if synth.name == DRIVER_NAME else synth
        try:
            # The table's voice is its host's own, not the row voice a foreign piece may have left on the host.
            current = (engine.name, synth.voice) if engine is not None else None
        except Exception:
            current = None
        table = self.table
        # The default language has no row; one for a dialect of it never speaks, so its voice's dictionary
        # stays off the default voice's text.
        default = base(getCurrentLanguage())
        found = {}  # language -> its dictionary or None, looked up once per sequence

        def dict_for(lang):
            if lang not in found:
                row = table.row_for(lang) if base(lang) != default else None
                voice = row.get("voice") if row is not None else None
                if not voice or (row.synth, voice) == current:
                    found[lang] = None
                else:
                    found[lang] = voicedict.dictionary(row.synth, voice)
            return found[lang]

        return voicedict.apply(sequence, LangChangeCommand, dict_for)

    def with_prosody(self, sequence):
        """On a synthesizer other than the language table, rows for that synthesizer set their rate, pitch,
        and volume through prosody commands; the synthesizer picks its own voice for the language."""
        synth = synthDriverHandler.getSynth()
        if synth is None or synth.name == DRIVER_NAME:
            return sequence
        self._sync_table()
        if not any(r.synth == synth.name for r in self.table_rows):
            return sequence
        # The default language has no row; one left over for it would apply only after a foreign run.
        default = base(getCurrentLanguage())
        section = config.conf["speech"].get(synth.name)
        values = {}
        for setting in prosody.COMMANDS:
            try:
                values[setting] = section[setting] if section is not None else None
            except KeyError:
                values[setting] = None
        # The offsets change only with the table, the synthesizer, its configured values, or the default.
        key = (self.table_raw, synth.name, default, tuple(sorted(values.items())))
        if key != self.offsets_key:
            rows = [r for r in self.table_rows if r.synth == synth.name and r.base != default]
            self.offsets = prosody.offsets(rows, values.get, synth.isSupported)
            self.offsets_key = key
        if not self.offsets:
            return sequence
        offsets = self.offsets
        return prosody.apply_offsets(sequence, lambda lang: prosody.offsets_for(offsets, lang))


def table_in_use():
    synth = synthDriverHandler.getSynth()
    return synth is not None and synth.name == DRIVER_NAME


def language_switching():
    """Whether language commands reach the synthesizer: always on the language table, else as NVDA's
    "Automatic language switching" is set. While they do not, the add-on leaves speech alone."""
    return table_in_use() or bool(config.conf["speech"]["autoLanguageSwitching"])


# NVDA's checks of its "Automatic language switching" setting: whether to make language commands, and whether to
# pass them to the synthesizer. The speech manager holds a reference of its own to the second.
SWITCHING_CHECKS = (
    ("speech.languageHandling", "shouldMakeLangChangeCommand"),
    ("speech.languageHandling", "shouldSwitchVoice"),
    ("speech.manager", "shouldSwitchVoice"),
)


def install_language_switching():
    """The language table gets language commands whatever "Automatic language switching" is set to, so the add-on
    never changes that setting, and it applies to every other synthesizer as the user set it."""
    import importlib

    for module_name, name in SWITCHING_CHECKS:
        module = importlib.import_module(module_name)
        original = getattr(module, name)
        if getattr(original, "_mlang_original", None) is not None:
            continue

        def check(original=original):
            try:
                if table_in_use():
                    return True
            except Exception:
                pass
            return original()

        check._mlang_original = original
        setattr(module, name, check)


def uninstall_language_switching():
    import importlib

    for module_name, name in SWITCHING_CHECKS:
        module = importlib.import_module(module_name)
        original = getattr(getattr(module, name), "_mlang_original", None)
        if original is not None:
            setattr(module, name, original)


def install_symbol_levels(engine):
    """NVDA processes symbols once per speak call, at one level, through speech.speech.processText with the
    language of each string (the language commands this add-on inserts). The wrapper gives each language its
    row's level, and text no voice of its language speaks the default's symbol names."""
    import speech.speech as speech_impl

    original = speech_impl.processText
    if getattr(original, "_mlang_original", None) is not None:
        return

    def processText(locale, text, symbolLevel, *args, **kwargs):
        locale = engine.symbol_locale(locale)
        return original(locale, text, engine.symbol_level(locale, symbolLevel), *args, **kwargs)

    processText._mlang_original = original
    speech_impl.processText = processText


def uninstall_symbol_levels():
    import speech.speech as speech_impl

    original = getattr(speech_impl.processText, "_mlang_original", None)
    if original is not None:
        speech_impl.processText = original


def return_to_table():
    """Once the add-on is back after being disabled or removed (mlang.leaving), the language table is selected
    again if it is still needed and NVDA is on its host, the synthesizer put back when the add-on left. A
    synthesizer the user picked meanwhile stays."""
    section = config.conf[T.CONFIG_SECTION]
    if not section["leftTable"]:
        return
    section["leftTable"] = False
    synth = synthDriverHandler.getSynth()
    if synth is not None and synth.name == section["defaultSynth"]:
        import wx

        # After NVDA's start, not inside it.
        wx.CallAfter(settings.follow_table)


def follow_after_update():
    """Once after an install or update (mlang.update), the synthesizer follows the table: this version may need the
    language table for rows saved before it, which the panel would only switch for on its next save. With no rows
    nothing is switched, so a first install leaves the synthesizer alone until the user sets something up."""
    if not config.conf[T.CONFIG_SECTION][update.KEY]:
        return
    update.apply_nvda(update.unmark, log)
    if T.load(config.conf).rows:
        import wx

        # After NVDA's start, not inside it.
        wx.CallAfter(settings.follow_table)


def disabled_on_restart():
    from addonHandler import AddonStateCategory, state

    return _addon.name in state[AddonStateCategory.PENDING_DISABLE]


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    def __init__(self):
        super().__init__()
        try:
            # First: the synthesizer NVDA started with may be a 32-bit one.
            pipes.install(log)
        except Exception:
            log.error("dialingo: could not make 32-bit synthesizers close their pipes once", exc_info=True)
        try:
            # Dialingo was multilanguage before 1.0; its settings move here (mlang.rename).
            rename.apply_nvda(rename.drop_old, log)
        except Exception:
            log.error("dialingo: the settings of multilanguage could not be moved", exc_info=True)
        T.ensure_spec(config.conf)
        self.engine = Engine()
        settings.engine = self.engine
        self.unit_context = context.UnitContext(self.engine)
        try:
            self.unit_context.install()
            self.engine.unit_context = self.unit_context
        except Exception:
            log.error("dialingo: could not wrap the caret speech functions; characters read in the default voice", exc_info=True)
        try:
            install_symbol_levels(self.engine)
        except Exception:
            log.error("dialingo: could not wrap symbol processing; every language uses NVDA's symbol level", exc_info=True)
        try:
            install_language_switching()
        except Exception:
            log.error("dialingo: could not pass language commands to the language table; it switches only with NVDA's automatic language switching on", exc_info=True)
        filter_speechSequence.register(self.filter)
        # NVDA's language reporter must see the commands this filter inserts, so it runs after it.
        filter_speechSequence.moveToEnd(getSpeechSequenceWithLangs, last=True)
        gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(settings.DialingoPanel)
        try:
            lock.install()
        except Exception:
            log.error("dialingo: could not add the language lock to the synth settings ring", exc_info=True)
        try:
            return_to_table()
        except Exception:
            log.error("dialingo: could not select the language table again", exc_info=True)
        try:
            follow_after_update()
        except Exception:
            log.error("dialingo: could not check the synthesizer against the table after an update", exc_info=True)

    def terminate(self):
        try:
            # NVDA has saved its configuration by now; a removal is handled by installTasks instead.
            if disabled_on_restart():
                leaving.leave_nvda(log)
        except Exception:
            log.error("dialingo: could not put the host back as NVDA's synthesizer", exc_info=True)
        lock.uninstall()
        settings.engine = None
        self.engine.unit_context = None
        self.unit_context.uninstall()
        uninstall_symbol_levels()
        filter_speechSequence.unregister(self.filter)
        uninstall_language_switching()
        try:
            gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(settings.DialingoPanel)
        except ValueError:
            pass
        pipes.uninstall()
        super().terminate()

    def filter(self, value):
        return self.engine.filter(value)
