# The multilanguage add-on's global plugin: language detection on every speech sequence, the settings
# panel, and the scripts. Detection inserts standard language commands, so it works with any synthesizer
# that switches languages by itself, and with the add-on's language table synthesizer for the rest.

import os
import sys
import threading

import addonHandler

_lib = os.path.join(addonHandler.getCodeAddon().path, "lib")
if _lib not in sys.path:
    sys.path.insert(0, _lib)

import config  # noqa: E402
import controlTypes  # noqa: E402
import globalPluginHandler  # noqa: E402
import globalVars  # noqa: E402
import gui  # noqa: E402
import synthDriverHandler  # noqa: E402
import ui  # noqa: E402
from globalCommands import SCRCAT_SPEECH  # noqa: E402
from logHandler import log  # noqa: E402
from scriptHandler import script  # noqa: E402
from speech import getCurrentLanguage  # noqa: E402
from speech.commands import LangChangeCommand  # noqa: E402
from speech.extensions import filter_speechSequence  # noqa: E402
from speech.languageHandling import getSpeechSequenceWithLangs  # noqa: E402

from mlang import policy, prosody, voicedict, winvoices  # noqa: E402
from mlang import trace as tr  # noqa: E402
from mlang import table as T  # noqa: E402
from mlang.detector import MODES, MODE_OFF, Detector  # noqa: E402
from mlang.hosts import DRIVER_NAME, REFUSED  # noqa: E402
from mlang.scripts import base  # noqa: E402
from mlang.sequence import filter_sequence, locked_sequence  # noqa: E402

from . import context, lock, settings  # noqa: E402
from .grid import GridLabels  # noqa: E402

addonHandler.initTranslation()

MODE_LABELS = {
    # Translators: A detection mode: no language detection.
    "off": _("Off"),
    # Translators: A detection mode: only text in another writing system is switched.
    "script": _("By script only"),
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
        log.debugWarning("multilanguage: Windows voices could not be listed", exc_info=True)
    return tuple(sorted(langs))



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
        self.table_languages = ()
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
        threading.Thread(target=self._warm, name="multilanguage-warm", daemon=True).start()

    def _warm(self):
        try:
            self._backend(bool(config.conf[T.CONFIG_SECTION]["strict"]))
        except Exception:
            log.error("multilanguage: the recognizer could not be loaded; language detection is off", exc_info=True)
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
                    log.warning("multilanguage: Windows language detection unavailable; strict mode ignored", exc_info=True)
                    self.strict_backend = self.backend
            return self.strict_backend

    def _sync_table(self):
        """Reparses the table when the saved JSON changed; the parsed rows serve detection and prosody alike."""
        raw = config.conf[T.CONFIG_SECTION]["table"]
        if raw != self.table_raw:
            table = T.Table.from_json(raw)
            self.table_raw = raw
            self.table = table
            self.table_languages = tuple(table.languages())
            self.table_rows = table.rows
            self.offsets_key = None

    def symbol_level(self, locale, level):
        """The symbol level for text NVDA speaks in `locale`: the row's own for that language, or `level`. Only
        NVDA's configured level is replaced; a level a caller asked for (all symbols when spelling) stands.
        The default language has no row, so it keeps NVDA's setting."""
        if not locale:
            return level
        try:
            if level != config.conf["speech"]["symbolLevel"]:
                return level
            self._sync_table()
            row = self.table.row_for(locale)
            if row is None or row.symbolLevel is None or base(locale) == base(getCurrentLanguage()):
                return level
            import characterProcessing

            return characterProcessing.SymbolLevel(row.symbolLevel)
        except Exception:
            log.debugWarning("multilanguage: no symbol level for %s" % locale, exc_info=True)
            return level

    def _dictionary(self):
        if self.dictionary is None:
            try:
                from mlang.dictionary import Dictionary

                self.dictionary = Dictionary()
            except Exception:
                log.warning("multilanguage: spell checking API unavailable; dictionary evidence off", exc_info=True)
                self.dictionary = False
        return self.dictionary or None

    def language_lock(self):
        """The language lock in effect: lock.AUTOMATIC, lock.DEFAULT, or a row's language."""
        self._sync_table()
        return lock.stored(self.table)

    def current(self):
        """The detector for the current configuration, default language, and table; None when off, locked to
        one language, or broken."""
        if self.failed or not self.ready.is_set():
            return None
        section = config.conf[T.CONFIG_SECTION]
        mode = section["mode"]
        if mode not in MODES:
            mode = "full"
        if mode == MODE_OFF or self.language_lock():
            return None
        default = getCurrentLanguage()
        self._sync_table()
        configured = self.table_languages
        strict = bool(section["strict"])
        available = self._available(section)
        key = (mode, default, configured, strict, available)
        if key != self.key:
            try:
                backend = self._backend(strict)
                if self.detector is None or self.detector.backend is not backend:
                    self.detector = Detector(backend, default, configured, self._dictionary(), mode, self.words)
                else:
                    self.detector.mode = mode
                self.detector.configure(default, configured, available)
                self.key = key
            except Exception:
                log.error("multilanguage: language detection could not start", exc_info=True)
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
        try:
            locked = self.language_lock()
        except Exception:
            log.error("multilanguage: the language lock could not be read", exc_info=True)
            locked = lock.AUTOMATIC
        if locked:
            try:
                sequence = locked_sequence(sequence, lock.language(locked))
            except Exception:
                log.error("multilanguage: the language lock failed on a sequence", exc_info=True)
        try:
            detector = self.current()
            if detector is not None:
                try:
                    detector.labels = self.grid.current()
                except Exception:
                    log.debugWarning("multilanguage: grid labels unavailable", exc_info=True)
                try:
                    sequence = filter_sequence(
                        sequence,
                        detector,
                        detector.default_tag,
                        config.conf[T.CONFIG_SECTION]["detectInDefaultTagged"],
                        unit_language=self.unit_context.language_for if self.unit_context else None,
                    )
                finally:
                    detector.labels = ()
        except Exception:
            log.error("multilanguage: detection failed on a sequence", exc_info=True)
        try:
            sequence = self.with_prosody(sequence)
        except Exception:
            log.error("multilanguage: applying row parameters failed on a sequence", exc_info=True)
        try:
            sequence = self.with_voice_dicts(sequence)
        except Exception:
            log.error("multilanguage: applying the row voices' dictionaries failed on a sequence", exc_info=True)
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


def ensure_language_switching():
    """NVDA drops every language command unless automatic language switching is on."""
    if not config.conf["speech"]["autoLanguageSwitching"]:
        config.conf["speech"]["autoLanguageSwitching"] = True
        log.info("multilanguage: turned on automatic language switching")


def rows_apply_to_current_synth():
    synth = synthDriverHandler.getSynth()
    if synth is None:
        return False
    if synth.name == DRIVER_NAME:
        return True
    return bool(T.load(config.conf).rows_for_synth(synth.name))


def install_symbol_levels(engine):
    """NVDA processes symbols once per speak call, at one level, through speech.speech.processText with the
    language of each string (the language commands this add-on inserts). The wrapper gives each language its
    row's level."""
    import speech.speech as speech_impl

    original = speech_impl.processText
    if getattr(original, "_mlang_original", None) is not None:
        return

    def processText(locale, text, symbolLevel, *args, **kwargs):
        return original(locale, text, engine.symbol_level(locale, symbolLevel), *args, **kwargs)

    processText._mlang_original = original
    speech_impl.processText = processText


def uninstall_symbol_levels():
    import speech.speech as speech_impl

    original = getattr(speech_impl.processText, "_mlang_original", None)
    if original is not None:
        speech_impl.processText = original


class GlobalPlugin(globalPluginHandler.GlobalPlugin):
    # Translators: The name of the add-on's script category and settings panel.
    scriptCategory = _("Multilanguage")

    def __init__(self):
        super().__init__()
        T.ensure_spec(config.conf)
        self.engine = Engine()
        settings.engine = self.engine
        self.unit_context = context.UnitContext(self.engine)
        try:
            self.unit_context.install()
            self.engine.unit_context = self.unit_context
        except Exception:
            log.error("multilanguage: could not wrap the caret speech functions; characters read in the default voice", exc_info=True)
        try:
            install_symbol_levels(self.engine)
        except Exception:
            log.error("multilanguage: could not wrap symbol processing; every language uses NVDA's symbol level", exc_info=True)
        filter_speechSequence.register(self.filter)
        # NVDA's language reporter must see the commands this filter inserts, so it runs after it.
        filter_speechSequence.moveToEnd(getSpeechSequenceWithLangs, last=True)
        synthDriverHandler.synthChanged.register(self.on_synth_changed)
        gui.settingsDialogs.NVDASettingsDialog.categoryClasses.append(settings.MultilanguagePanel)
        if (
            config.conf[T.CONFIG_SECTION]["mode"] != MODE_OFF
            or rows_apply_to_current_synth()
            or lock.language(self.engine.language_lock())
        ):
            ensure_language_switching()
        settings.follow_table()
        try:
            lock.install()
        except Exception:
            log.error("multilanguage: could not add the language lock to the synth settings ring", exc_info=True)

    def terminate(self):
        lock.uninstall()
        settings.engine = None
        self.engine.unit_context = None
        self.unit_context.uninstall()
        uninstall_symbol_levels()
        filter_speechSequence.unregister(self.filter)
        synthDriverHandler.synthChanged.unregister(self.on_synth_changed)
        try:
            gui.settingsDialogs.NVDASettingsDialog.categoryClasses.remove(settings.MultilanguagePanel)
        except ValueError:
            pass
        super().terminate()

    def filter(self, value):
        start = tr.now()
        result = self.engine.filter(value)
        tr.trace(f"filter {tr.text(value) if isinstance(value, list) else ''} in {tr.ms(start)}")
        return result

    def on_synth_changed(self, synth=None, isFallback=False, **kwargs):
        # A synthesizer the user picks becomes the one the language table hosts; a fallback after another
        # failed to load is not a pick.
        name = getattr(synth, "name", None)
        if name and not isFallback and name not in (DRIVER_NAME, "silence", "auto", *REFUSED):
            config.conf[T.CONFIG_SECTION]["defaultSynth"] = name
        if rows_apply_to_current_synth():
            ensure_language_switching()

    @script(
        # Translators: Description of a script.
        description=_("Cycles language detection: off, by script only, full"),
        category=SCRCAT_SPEECH,
    )
    def script_cycleMode(self, gesture):
        section = config.conf[T.CONFIG_SECTION]
        modes = list(MODES)
        current = section["mode"] if section["mode"] in modes else "full"
        mode = modes[(modes.index(current) + 1) % len(modes)]
        section["mode"] = mode
        if mode != MODE_OFF:
            ensure_language_switching()
        # Translators: Reported when the detection mode changes; %s is the mode's name.
        ui.message(_("Language detection %s") % MODE_LABELS[mode])

    @script(
        # Translators: Description of a script.
        description=_("Toggles strict language detection"),
        category=SCRCAT_SPEECH,
    )
    def script_toggleStrict(self, gesture):
        section = config.conf[T.CONFIG_SECTION]
        section["strict"] = not section["strict"]
        # Translators: Reported when strict mode is turned on or off.
        ui.message(_("Strict detection on") if section["strict"] else _("Strict detection off"))
