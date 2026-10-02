# The language lock: all speech in one language, with no switching at all, chosen in NVDA's synth settings
# ring.
#
# The ring offers Automatic (switching as configured), the default language, and each row of the table. A
# locked language overrides detection and the tags applications put on their text alike. NVDA builds the
# ring from the synthesizer's own settings whenever the synthesizer or its voice changes, so the lock is
# added to every ring it builds, after the synthesizer's settings, whichever synthesizer is in use.
#
# Locked to a row, the ring shows that row's settings in place of the synthesizer's: its voice, rate, and
# the rest, as the row's synthesizer offers them, and a change is saved to the row and heard at once. On the
# language table synthesizer that is every setting a row carries; on the synthesizer in use, where a row
# acts through prosody commands, its rate, pitch, and volume.
#
# After the lock comes language detection: the detection mode, or, locked to a row, whether detection may
# switch to that row's language once the lock is back on Automatic.
#
# Locked to a row, the ring speaks that row's language: its entries' names and values come from NVDA's and
# the add-on's catalogs for that language, since the row's voice reads NVDA's own language poorly.

import functools
import gettext
import os

import addonHandler
import config
import globalVars
import languageHandler
import queueHandler
import synthDriverHandler
import synthSettingsRing
from autoSettingsUtils.driverSetting import BooleanDriverSetting, DriverSetting, NumericDriverSetting
from autoSettingsUtils.utils import StringParameterInfo
from logHandler import log
from speech import getCurrentLanguage

from mlang import hosts, prosody
from mlang import table as T
from mlang.catalogs import Catalog, Words, catalog
from mlang.detector import MODE_FULL, MODES
from mlang.hosts import DRIVER_NAME
from mlang.scripts import base, code, normalize

addonHandler.initTranslation()

_addon = addonHandler.getCodeAddon()

# The context NVDA translates the ring's names of synthesizer settings in.
RING_CONTEXT = "synth setting"

AUTOMATIC = ""
DEFAULT = "default"


def lockable_rows(table):
    """The rows the lock can take: a row for the default language in another dialect never speaks."""
    default = code(getCurrentLanguage())
    return [r for r in table.rows if code(r.lang) != default]


def stored(table):
    """The lock as saved, or Automatic when it names a row no longer in the table."""
    value = config.conf[T.CONFIG_SECTION]["lock"]
    if value in (AUTOMATIC, DEFAULT) or any(r.lang == value for r in lockable_rows(table)):
        return value
    return AUTOMATIC


def language(value):
    """The language a lock speaks in, None for the default."""
    return None if value == DEFAULT else value


def language_name(tag):
    return languageHandler.getLanguageDescription(languageHandler.normalizeLanguage(tag) or tag) or tag


def refresh_later():
    """Rebuilds the ring once the running script is done: NVDA announces a ring rebuilt inside a script
    that loses its place, which the lock's own entry always does."""
    queueHandler.queueFunction(queueHandler.eventQueue, refresh_ring)


class LockSetting(synthSettingsRing.SynthSetting):
    """The ring's entry for the lock. Its value is an index into the choices, as NVDA's own string settings'
    are; it is saved in the add-on's section, not the synthesizer's."""

    def __init__(self, synth):
        # Translators: The name of the language lock in the synth settings ring.
        setting = DriverSetting("multilanguageLock", _("Language lock"), availableInSettingsRing=True, useConfig=False)
        super().__init__(synth, setting)

    def _get__values(self):
        # Translators: The language lock's value when languages switch as configured.
        values = [StringParameterInfo(AUTOMATIC, _("Automatic"))]
        values.append(StringParameterInfo(DEFAULT, language_name(getCurrentLanguage())))
        values.extend(StringParameterInfo(r.lang, language_name(r.lang)) for r in lockable_rows(T.load(config.conf)))
        return values

    def _get_max(self):
        return len(self._values) - 1

    def _set_max(self, value):
        # Set by SynthSetting; always worked out from the choices.
        pass

    def _get_value(self):
        current = stored(T.load(config.conf))
        for index, value in enumerate(self._values):
            if value.id == current:
                return index
        return 0

    def _set_value(self, index):
        value = self._values[index].id
        config.conf[T.CONFIG_SECTION]["lock"] = value
        # The other entries become the locked row's, or the synthesizer's again.
        refresh_later()

    def _getReportValue(self, val):
        return self._values[val].displayName


# ------------------------------------------------------------ detection


class DetectionSetting(synthSettingsRing.SynthSetting):
    """The ring's entry for language detection, after the lock; its value is an index, saved in the add-on's
    section, not the synthesizer's."""


class ModeSetting(DetectionSetting):
    """The detection mode, as in the settings panel: off, script and tags only, or full."""

    def __init__(self, synth):
        # Translators: The name of the detection mode in the synth settings ring.
        setting = DriverSetting("multilanguageDetection", _("Language detection"), availableInSettingsRing=True, useConfig=False)
        super().__init__(synth, setting, 0, len(MODES) - 1)

    def _get_value(self):
        mode = config.conf[T.CONFIG_SECTION]["mode"]
        return MODES.index(mode if mode in MODES else MODE_FULL)

    def _set_value(self, index):
        config.conf[T.CONFIG_SECTION]["mode"] = MODES[index]

    def _getReportValue(self, val):
        from . import MODE_LABELS

        return MODE_LABELS[MODES[val]]


class RowDetection(DetectionSetting):
    """Whether detection may switch to the locked row's language."""

    def __init__(self, synth, lang):
        self.lang = lang
        # Translators: The name of the entry in the synth settings ring that turns detection of one language on
        # or off; %s is the language's name.
        setting = DriverSetting("multilanguageRowDetection", _("%s detection") % language_name(lang), availableInSettingsRing=True, useConfig=False)
        super().__init__(synth, setting, 0, 1)

    def _get_value(self):
        row = T.load(config.conf).row_for(self.lang, exact=True)
        return int(row is None or row.detect)

    def _set_value(self, value):
        table = T.load(config.conf)
        row = table.row_for(self.lang, exact=True)
        if row is None:
            return
        row.detect = bool(value)
        # Not T.save: the language table driver would cancel speech and rebuild its guests, and the row's
        # synthesizer settings are unchanged.
        config.conf[T.CONFIG_SECTION]["table"] = table.to_json()
        synth = synthDriverHandler.getSynth()
        if synth is not None and synth.name == DRIVER_NAME:
            synth.update_row(row)

    def _getReportValue(self, val):
        # Translators: The value of a language's detection entry in the synth settings ring.
        return _("on") if val else _("off")


def detection_entry(synth):
    """The detection entry for the lock as saved: a row's own switch when locked to a row, else the mode."""
    value = stored(T.load(config.conf))
    if value in (AUTOMATIC, DEFAULT):
        return ModeSetting(synth)
    return RowDetection(synth, value)


# ------------------------------------------------------------ the locked row's settings


class RowSynth:
    """The locked row standing in for a synthesizer in the ring: the row's values where it has them, its
    synthesizer's own otherwise, and that synthesizer's voice and variant lists. The row is read from the
    configuration each time, so a table saved from the settings panel is seen at once."""

    def __init__(self, lang, guest):
        self.lang = lang
        self.guest = guest
        self.name = guest.name

    def _row(self, table):
        return table.row_for(self.lang, exact=True)

    def __getattr__(self, name):
        if name not in T.ROW_SETTINGS:
            return getattr(self.__dict__["guest"], name)
        row = self._row(T.load(config.conf))
        value = row.get(name) if row is not None else None
        if value is None:
            value = hosts.own_value(self.guest, name)
        if value is None and name not in ("voice", "variant"):
            value = False if name == "rateBoost" else 50
        return value

    def store(self, setting, value):
        table = T.load(config.conf)
        row = self._row(table)
        if row is None:
            return
        # A new voice keeps the row's variant, as NVDA keeps a synthesizer's: eSpeak's apply to every voice.
        row.set(setting, value)
        config.conf[T.CONFIG_SECTION]["table"] = table.to_json()
        synth = synthDriverHandler.getSynth()
        if synth is not None and synth.name == DRIVER_NAME:
            synth.update_row(row)
        if setting == "voice":
            # The variants listed are the new voice's.
            refresh_later()


class RowNumber(synthSettingsRing.SynthSetting):
    def _set_value(self, value):
        self.synth.store(self.setting.id, value)


class RowBoolean(synthSettingsRing.BooleanSynthSetting):
    def _set_value(self, value):
        self.synth.store(self.setting.id, bool(value))


class RowString(synthSettingsRing.StringSynthSetting):
    def _get_value(self):
        value = super()._get_value()
        return value if value is not None else 0

    def _set_value(self, index):
        self.synth.store(self.setting.id, self._values[index].id)


def row_entries(synth):
    """The ring's entries for the locked row, or None when the lock is not on a row or its synthesizer is not
    loaded. Only instances already made are used: the ring is rebuilt inside the loading of a synthesizer."""
    table = T.load(config.conf)
    value = stored(table)
    if value in (AUTOMATIC, DEFAULT):
        return None
    row = table.row_for(value, exact=True)
    if row is None:
        return None
    if synth.name == DRIVER_NAME:
        guest = (synth.__dict__.get("guests") or {}).get(row.synth)
        ids = T.ROW_SETTINGS
    elif synth.name == row.synth:
        guest = synth
        ids = tuple(prosody.COMMANDS)
    else:
        return None
    if guest is None:
        return None
    proxy = RowSynth(row.lang, guest)
    entries = []
    for setting in guest.supportedSettings:
        if setting.id not in ids or not setting.availableInSettingsRing:
            continue
        if isinstance(setting, NumericDriverSetting):
            cls = RowNumber
        elif isinstance(setting, BooleanDriverSetting):
            cls = RowBoolean
        else:
            cls = RowString
        entries.append(cls(proxy, setting))
    return entries


# ------------------------------------------------------------ the ring in the locked language


@functools.lru_cache(maxsize=8)
def words_for(lang):
    """The ring's words in `lang`: the add-on's catalog first, for its own entries, whose words NVDA has in
    other senses ("Off"), then NVDA's."""
    tag = normalize(lang)
    english = base(tag) == "en"
    installed = getattr(languageHandler, "installedTranslation", None)
    current = installed() if installed is not None else None
    if current is None:
        current = gettext.translation("nvda", os.path.join(globalVars.appDir, "locale"), [languageHandler.getLanguage()], fallback=True)
    nvda = gettext.translation("nvda", os.path.join(globalVars.appDir, "locale"), [tag], fallback=True)
    ours = gettext.translation("nvda", os.path.join(_addon.path, "locale"), [tag], fallback=True)
    return Words(
        Catalog(catalog(_addon.getTranslationsInstance()), catalog(ours), english),
        Catalog(catalog(current), catalog(nvda), english),
    )


class Renamed:
    """A driver setting under another name, for one ring; everything else is the setting's own."""

    def __init__(self, setting, displayName):
        self._setting = setting
        self.displayName = displayName

    def __getattr__(self, name):
        return getattr(self.__dict__["_setting"], name)


def localize(entries, lang):
    """The ring's entries named, and their values reported, in `lang`. A name or value neither catalog has,
    such as a voice's, stays as it is."""
    words = words_for(lang)
    for entry in entries:
        try:
            if isinstance(entry, RowDetection):
                name = words("%s detection") % language_name(entry.lang)
            else:
                name = words(entry.setting.displayName, RING_CONTEXT)
            entry.setting = Renamed(entry.setting, name)
            entry._getReportValue = functools.partial(lambda report, val: words(report(val)), entry._getReportValue)
        except Exception:
            log.debugWarning(f"multilanguage: a ring entry could not be put in {lang}", exc_info=True)


def locked_row_language():
    """The language of the row the lock holds, when NVDA speaks another; else None."""
    value = stored(T.load(config.conf))
    if value in (AUTOMATIC, DEFAULT) or base(value) == base(languageHandler.getLanguage()):
        return None
    return value


# ------------------------------------------------------------ the ring


def install():
    original = synthSettingsRing.SynthSettingsRing.updateSupportedSettings
    if getattr(original, "_mlang_original", None) is not None:
        return

    def updateSupportedSettings(ring, synth):
        # This runs inside every change of synthesizer and voice, so nothing of the lock's may stop NVDA's own.
        settings = getattr(ring, "settings", None) or []
        current = ring._current
        previous = settings[current] if isinstance(current, int) and 0 <= current < len(settings) else None
        # The add-on's own entry the ring was on, which the rebuilt ring stays on.
        kept = next((cls for cls in (LockSetting, DetectionSetting) if isinstance(previous, cls)), None)
        try:
            entries = row_entries(synth)
        except Exception:
            log.error("multilanguage: the locked language's settings could not be put in the ring", exc_info=True)
            entries = None
        if entries is None:
            if kept is not None:
                # NVDA keeps the ring's place by finding the setting among the synthesizer's, where the lock is not.
                ring._current = None
            original(ring, synth)
            entries = list(ring.settings or [])
        else:
            # The same setting as before, else the rate, as NVDA starts on.
            ids = [entry.setting.id for entry in entries]
            wanted = previous.setting.id if previous is not None else None
            ring._current = ids.index(wanted) if wanted in ids else ids.index("rate") if "rate" in ids else None
        try:
            ring.settings = entries + [LockSetting(synth)]
            if kept is LockSetting or ring._current is None:
                ring._current = len(ring.settings) - 1
        except Exception:
            log.error("multilanguage: the language lock could not be added to the synth settings ring", exc_info=True)
            return
        try:
            ring.settings.append(detection_entry(synth))
            if kept is DetectionSetting:
                ring._current = len(ring.settings) - 1
        except Exception:
            log.error("multilanguage: language detection could not be added to the synth settings ring", exc_info=True)
        try:
            lang = locked_row_language()
            if lang:
                localize(ring.settings, lang)
        except Exception:
            log.error("multilanguage: the synth settings ring could not be put in the locked language", exc_info=True)

    updateSupportedSettings._mlang_original = original
    synthSettingsRing.SynthSettingsRing.updateSupportedSettings = updateSupportedSettings
    refresh_ring()


def uninstall():
    original = getattr(synthSettingsRing.SynthSettingsRing.updateSupportedSettings, "_mlang_original", None)
    if original is not None:
        synthSettingsRing.SynthSettingsRing.updateSupportedSettings = original
        refresh_ring()


def refresh_ring():
    """Rebuilds the ring NVDA already made for the synthesizer in use."""
    ring = globalVars.settingsRing
    synth = synthDriverHandler.getSynth()
    if ring is None or synth is None:
        return
    try:
        ring.updateSupportedSettings(synth)
    except Exception:
        log.error("multilanguage: the synth settings ring could not be rebuilt", exc_info=True)
