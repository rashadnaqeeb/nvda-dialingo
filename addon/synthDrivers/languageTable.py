# The language table synthesizer of the multilanguage add-on.
#
# Hosts NVDA's real synthesizer drivers. The default synthesizer, adopted from the one in use when this
# driver is first selected, speaks the default language and everything the table has no row for, and its
# settings are this driver's settings: NVDA's voice settings and the synth settings ring show the host's
# own voice, rate, and options, so selecting this driver changes nothing the user can hear or see until a
# row of the table is used. Each row speaks its language with its synthesizer, voice, and parameters. An
# utterance is cut at every language command and played on the guests in turn; their index and done
# notifications are re-emitted under this driver's name, so NVDA's speech manager keeps tracking the
# caret and say all.
#
# The settings are stored in the host's own configuration section, never in this driver's. NVDA's
# SynthDriver would keep a copy under this driver's name and fill the host from it on every load, and a
# value missing from that copy, which NVDA never writes when it equals the setting's default, would come
# back as that default: every numeric setting at 50. So initSettings, loadSettings, and saveSettings are
# this driver's own, and this driver's section holds only what NVDA keeps per synthesizer name itself, such
# as the capital pitch change. The voice dictionary NVDA loads on each voice change is the host's too.

import os
import sys
import threading
from collections import OrderedDict

import addonHandler

_lib = os.path.join(addonHandler.getCodeAddon().path, "lib")
if _lib not in sys.path:
    sys.path.insert(0, _lib)

import config  # noqa: E402
import queueHandler  # noqa: E402
import synthDriverHandler  # noqa: E402
from logHandler import log  # noqa: E402
from speech.commands import (  # noqa: E402
    BreakCommand,
    CharacterModeCommand,
    IndexCommand,
    LangChangeCommand,
    PitchCommand,
    RateCommand,
    VolumeCommand,
)
from synthDriverHandler import VoiceInfo, synthDoneSpeaking, synthIndexReached  # noqa: E402

from mlang import hosts, policy, winvoices  # noqa: E402
from mlang import trace as tr  # noqa: E402
from mlang import table as T  # noqa: E402
from mlang.scheduler import Scheduler  # noqa: E402
from mlang.scripts import code  # noqa: E402

addonHandler.initTranslation()

# The voice dictionary NVDA loads for this driver is the host's, so the user's dictionary for the default
# synthesizer's voice keeps applying while it is hosted.
try:
    hosts.redirect_voice_dict()
except Exception:
    log.error("multilanguage: the voice dictionary could not be redirected to the default synthesizer", exc_info=True)

# Settings whose values are the host's, read and written through this driver. The standard ones have
# properties on the base class and are forwarded explicitly below; any other setting a host declares
# (Eloquence's head size, OneCore's rate boost) is forwarded by __getattr__ and __setattr__.
STANDARD = ("voice", "variant", "rate", "rateBoost", "pitch", "inflection", "volume")

PROSODY = {RateCommand: "rate", PitchCommand: "pitch", VolumeCommand: "volume"}


def _prosody_form(item):
    """(offset, multiplier) as a prosody command was built. NVDA's offset and multiplier properties turn
    one form into the other against the configured value of the synthesizer in use, this driver's, and
    raise when its section lacks the setting."""
    return getattr(item, "_offset", 0), getattr(item, "_multiplier", 1)


# NVDA's settings kept per synthesizer name, which follow the default synthesizer into this driver's section
# and back, so selecting this driver or leaving it keeps how capitals and spelling sound.
PER_SYNTH = ("capPitchChange", "sayCapForCapitals", "beepForCapitals", "useSpellingFunctionality")


# Guests known to report done only once their queue is empty; see the scheduler's notes.
DONE_DRAINS = {"oneCore", "ibmeci", "sapi4_32"}

# Guests that must be done before any new row is applied to them; see the scheduler. Both Acapela drivers:
# the one with a queue of its own reports its end marker while still synthesizing and sets parameters
# without the lock its synthesis holds; the one that plays through its engine changes the engine's speed
# and volume at once, under what it is still playing.
SETTLES = {"AcaTTS"}


def _queues_itself(synth):
    """Acapela's own driver (1.9.5) queues calls on a thread of its own and reports done twice, the second
    time once its queue is empty. The other Acapela driver, which hands each call to its engine to play,
    reports done once per call, and its engine may cut a call short with the next."""
    return hasattr(synth, "speakQueue")


def _done_drains(guest):
    if guest.name == "AcaTTS":
        # The first of the two dones is dropped in _on_guest_done.
        return _queues_itself(guest)
    return guest.name in DONE_DRAINS


def _serial(guest):
    return guest.name == "AcaTTS" and not _queues_itself(guest)

# Settings with which a driver switches voice by itself on the languages or scripts it detects (Vocalizer),
# which inside a row's piece would take the text from the row's voice. Off for rows; the default synthesizer
# keeps the user's.
AUTO_SWITCHING = ("enableUnicodeLanguageSwitching",)


def _is_sapi5(synth):
    """NVDA's SAPI 5 driver or one built on it, such as the Microsoft Speech Platform's."""
    return any(c.__module__ == "synthDrivers.sapi5" for c in type(synth).__mro__)


def _reports_before_playing(synth):
    """SAPI 5 reports the end of a stream when its synthesis ends, while the audio is still in its player."""
    return _is_sapi5(synth) and getattr(synth, "player", None) is not None


def _more_queued(synth):
    """Whether eSpeak, which reports done after each speak call, and after one a cancel cut short, still holds
    a later call in its queue. Or whether Acapela's own driver is still in a call: it reports done once when
    its synthesis of a call ends, with the audio still to play, and again once its queue is empty and the audio
    played."""
    name = getattr(synth, "name", None)
    if name == "AcaTTS":
        try:
            return synth.speakQueue.unfinished_tasks > 0
        except Exception:
            return False
    if name != "espeak":
        return False
    try:
        from synthDrivers import _espeak

        q = _espeak.bgQueue
        with q.mutex:
            return any(item[0] is _espeak._speak for item in q.queue)
    except Exception:
        return False


def _done_early(synth):
    """NVDA's 32-bit SAPI 5, in another process: with its audio on WASAPI, which NVDA's bridge cannot turn off, it
    reports every mark not yet played and then done when its synthesis ends, while up to its player's buffer
    (0.4 seconds) is still to play, and reports each mark again once the audio before it has played. That second
    report of a piece's end marker frees it (on_played); its done does not."""
    return getattr(synth, "name", None) == "sapi5_32"


# How long a guest held after an early done may go without the report that its audio played before it is
# freed anyway: longer than the most audio it can still hold when it reports done.
PLAYED_TIMEOUT = 1.0


def _after_playing(synth, func):
    """Call `func` when what the guest has fed its player so far has played, as SAPI 5 does for its bookmarks.
    Never from inside one of the player's callbacks, which SAPI 5's marks are reported from: NVDA's player runs
    them while walking its list of pending callbacks, and a feed inside one adds to that list and corrupts it,
    which crashes NVDA."""
    try:
        synth.player.feed(None, 0, onDone=func)
    except Exception:
        func()


def _eloquence(synth):
    """The engine module of the IBMTTS Eloquence driver (ibmeci), which holds its audio player, or None.
    Eloquence reports each mark once the audio before it is fed to its player, from the thread that feeds it,
    and done from a timer started 0.3 seconds after its synthesis ends."""
    if getattr(synth, "name", None) != "ibmeci":
        return None
    engine = getattr(sys.modules.get(type(synth).__module__), "_ibmeci", None)
    if getattr(engine, "player", None) is None or not all(hasattr(engine, a) for a in ("idleTimer", "speaking")):
        return None
    return engine


def _settings_dialog_open():
    """Whether one of NVDA's settings dialogs is open. Its panels change settings live, save them on OK, and
    reload them from the configuration on Cancel, so nothing may be stored before then. True when it
    cannot be told, which only defers storing to NVDA's next configuration save."""
    try:
        from gui.settingsDialogs import SettingsDialog

        created = SettingsDialog.DialogState.CREATED
        return any(state == created for state in list(SettingsDialog._instances.values()))
    except Exception:
        return True


class SynthDriver(synthDriverHandler.SynthDriver):
    name = hosts.DRIVER_NAME
    # Translators: Name of the synthesizer that speaks each language with its own synthesizer and voice.
    description = _("Language table (multilanguage)")

    supportedCommands = {
        IndexCommand,
        CharacterModeCommand,
        LangChangeCommand,
        BreakCommand,
        PitchCommand,
        RateCommand,
        VolumeCommand,
    }
    supportedNotifications = {synthIndexReached, synthDoneSpeaking}

    @classmethod
    def check(cls):
        """Listed in NVDA's synthesizer dialog only when something needs it: a row on another synthesizer
        than the one in use, or a Windows voice for a language the one in use cannot speak. Rows on the
        synthesizer in use work through prosody commands without this driver. Always available once it
        is the selected one."""
        try:
            T.ensure_spec(config.conf)
            if config.conf["speech"]["synth"] == cls.name:
                return True
            return policy.needs_table(config.conf)
        except Exception:
            log.debugWarning("multilanguage: language table availability check failed", exc_info=True)
            return True

    def __init__(self):
        # Set before super().__init__ so __getattr__/__setattr__ have their bearings.
        self.__dict__["host"] = None
        self.__dict__["_defaults"] = {}
        super().__init__()
        T.ensure_spec(config.conf)
        self.table = T.load(config.conf)
        self.guests = {}
        self._failed = set()
        self._windows_rows = {}  # language code -> implicit row on a Windows voice, or None
        self.scheduler = Scheduler(
            LangChangeCommand,
            IndexCommand,
            self._guest_for_row,
            self._apply_row,
            self._notify_index,
            self._notify_done,
            lambda func: queueHandler.queueFunction(queueHandler.eventQueue, func),
            log.debugWarning,
            notifies_indexes=lambda guest: synthIndexReached in guest.supportedNotifications,
            notifies_done=lambda guest: synthDoneSpeaking in guest.supportedNotifications,
            adapt=self._adapt_prosody,
            done_drains=_done_drains,
            settles=lambda guest: guest.name in SETTLES,
            serial=_serial,
            done_early=_done_early,
        )
        self._load_host()
        if self.host is None:
            for guest in list(self.guests.values()):
                hosts.dispose(guest)
            raise RuntimeError("no synthesizer could be loaded to host for the language table")
        for name in self.table.synths():
            self.guest(name)
        if self._windows_voices_needed():
            self.guest(winvoices.ONECORE)
        synthIndexReached.register(self._on_guest_index)
        synthDoneSpeaking.register(self._on_guest_done)
        T.listeners.append(self._on_table_saved)

    def terminate(self):
        try:
            T.listeners.remove(self._on_table_saved)
        except ValueError:
            pass
        synthIndexReached.unregister(self._on_guest_index)
        synthDoneSpeaking.unregister(self._on_guest_done)
        self.scheduler.cancel()
        # The scheduler holds this driver's bound methods; without it the instance is freed as soon as NVDA
        # lets go of it, not by a later garbage collection, when NVDA's voice panel, whose weak reference
        # refreshes it on that moment, may already be gone.
        self.__dict__.pop("scheduler", None)
        # Not super().terminate(): that would save this driver's settings under its own name.
        self._unregisterConfigSaveAction()
        host = self.__dict__.get("host")
        for name, guest in list(self.guests.items()):
            if guest is host:
                # The default synthesizer keeps what the user set while it was hosted: its own values,
                # not a row's, go into its own section, so switching back to it changes nothing heard.
                # Its own terminate may save too; it then finds the same values on the instance.
                try:
                    # The whole default, the settings no row carries too, which a row's variant may have reset.
                    guest._mlangApplied = None
                    self._apply_row(guest, self.default_row())
                    guest.cancel()
                    self.saveSettings()
                    guest.terminate()
                except Exception:
                    log.debugWarning("multilanguage: could not hand the host its settings back", exc_info=True)
                    hosts.dispose(guest)
            else:
                hosts.dispose(guest)
        self.guests.clear()
        self.__dict__["host"] = None

    # ------------------------------------------------------------ host and guests

    def _load_host(self):
        """The default synthesizer: the configured one, else the one in use when this driver was selected,
        else NVDA's defaults. The choice is stored once made; a stand-in for a configured one that failed to
        load this time (a 32-bit synthesizer whose process did not start) is not, so it is tried again next time.
        Never silence, which reports no language and would send every tagged text to a Windows voice."""
        section = config.conf[T.CONFIG_SECTION]
        configured = section["defaultSynth"]
        candidates = [configured, config.conf["speech"]["synth"]] + list(synthDriverHandler.defaultSynthPriorityList)
        for name in candidates:
            if not name or name in (self.name, "auto", "silence"):
                continue
            guest = self.guest(name)
            if guest is None:
                continue
            self.__dict__["host"] = guest
            self.__dict__["host_name"] = name
            if not configured or configured in (self.name, "auto", "silence"):
                section["defaultSynth"] = name
                log.info(f"multilanguage: language table hosts {name} as the default synthesizer")
            elif name != configured:
                log.warning(f"multilanguage: {configured} could not be loaded; {name} stands in as the default synthesizer")
            self._snapshot_defaults()
            return

    def _snapshot_defaults(self, configured=False):
        """The host's own values, restored after a row of another language used the same synthesizer: every
        setting it keeps in the configuration, since a row's variant can reset the ones no row carries
        (Eloquence copies a preset voice, head size and roughness included).

        `configured`: the host was just loaded from its section, whose numbers and switches are then taken as
        they are stored. eSpeak, busy, queues the new values and reports the old ones until its queue is done,
        so after a profile switch during speech the snapshot would keep the previous profile's."""
        defaults = {}
        section = None
        if configured:
            try:
                section = config.conf["speech"][self.host.name]
            except Exception:
                section = None
        settings = [s.id for s in self.host.supportedSettings if getattr(s, "useConfig", True)]
        for setting in list(T.ROW_SETTINGS) + [s for s in settings if s not in T.ROW_SETTINGS]:
            try:
                if not self.host.isSupported(setting):
                    continue
                value = hosts.read(self.host, setting)
                if section is not None and isinstance(value, (int, bool)):
                    try:
                        stored = section[setting]
                    except KeyError:
                        stored = None
                    if type(stored) is type(value):
                        value = stored
                defaults[setting] = value
            except Exception:
                pass
        self.__dict__["_defaults"] = defaults
        self.__dict__["_default_row"] = None
        self._snapshot_language()

    def _snapshot_language(self):
        """The host's language while it carries its own voice, for a voice that reports none of its own, and
        its variants, which some synthesizers list per voice (Sonata gives each the voice's language)."""
        try:
            self.__dict__["_default_language"] = self.host.language
        except Exception:
            self.__dict__["_default_language"] = None
        try:
            variants = OrderedDict(self.host.availableVariants) if self.host.isSupported("variant") else None
        except Exception:
            variants = None
        self.__dict__["_default_variants"] = variants

    def guest(self, name):
        """The guest instance for a synthesizer name, created on first use; None when it cannot load.
        A failure is remembered until the table changes, so speech is not slowed by retrying it."""
        if name in self.guests:
            return self.guests[name]
        if name in self._failed:
            return None
        guest = hosts.create(name, log)
        if guest is not None:
            self.guests[name] = guest
        else:
            self._failed.add(name)
        return guest

    def default_row(self):
        row = self.__dict__.get("_default_row")
        if row is None:
            row = T.Row(self.language or "en", self.host_name, **self._defaults)
            self.__dict__["_default_row"] = row
        return row

    def _row_for_lang(self, lang):
        # The default's own language is the default voice's in any dialect: NVDA opens an utterance with the
        # default's tag ("en_US"), and a row for "en_GB" would otherwise take all speech.
        if lang and code(lang) == code(self.language or ""):
            return None
        row = self.table.row_for(lang)
        if row is not None:
            return row if self.guest(row.synth) is not None else None
        return self._windows_row(lang)

    def _windows_voices_needed(self):
        """Whether a Windows voice speaks a language the host cannot, so the OneCore guest is wanted up
        front rather than built inside the first utterance that needs it."""
        if not policy.windows_voices_wanted(config.conf) or self.host_name == winvoices.ONECORE:
            return False
        try:
            return any(not hosts.supports(self.host, lang) for lang in winvoices.languages())
        except Exception:
            log.debugWarning("multilanguage: Windows voices could not be checked against the host", exc_info=True)
            return False

    def _windows_row(self, lang):
        """An implicit row on the Windows voice for a language no row covers and the host cannot speak.
        None sends the text to the host."""
        if not policy.windows_voices_wanted(config.conf) or self.host_name == winvoices.ONECORE:
            return None
        key = winvoices.code(lang)
        if key in self._windows_rows:
            return self._windows_rows[key]
        row = None
        try:
            if not hosts.supports(self.host, lang):
                voice = winvoices.voice_for(lang)
                if voice is not None and self.guest(winvoices.ONECORE) is not None:
                    # The user's OneCore settings, or the shared guest keeps whatever the last OneCore row set.
                    own = {}
                    for setting in ("rate", "rateBoost", "pitch", "volume"):
                        try:
                            own[setting] = config.conf["speech"][winvoices.ONECORE][setting]
                        except Exception:
                            pass
                    row = T.Row(voice[2], winvoices.ONECORE, voice=voice[0], **own)
                    log.info(f"multilanguage: {lang} goes to the Windows voice {voice[1]}")
        except Exception:
            log.debugWarning(f"multilanguage: no Windows voice for {lang}", exc_info=True)
        self._windows_rows[key] = row
        return row

    def _guest_for_row(self, row):
        return self.guest(row.synth) or self.host

    def _apply_row(self, guest, row):
        if getattr(guest, "_mlangApplied", None) == row.key():
            return
        start = tr.now()
        tr.trace(f"apply {row.lang}/{row.synth} to {tr.name(guest)}")
        hosts.apply_row(guest, row, log)
        default = guest is self.host and row.key() == self.default_row().key()
        if not default:
            for setting in AUTO_SWITCHING:
                try:
                    if guest.isSupported(setting) and getattr(guest, setting):
                        setattr(guest, setting, False)
                except Exception:
                    log.debugWarning(f"multilanguage: could not turn off {setting} on {guest.name}", exc_info=True)
        if default:
            # Settings no row carries, which a row's variant may have reset on the shared instance.
            for setting, value in self._defaults.items():
                if setting in T.ROW_SETTINGS:
                    continue
                try:
                    if hosts.read(guest, setting) != value:
                        setattr(guest, setting, value)
                except Exception:
                    log.debugWarning(f"multilanguage: could not restore {setting} on {guest.name}", exc_info=True)
        tr.trace(f"applied {row.lang}/{row.synth} to {tr.name(guest)} in {tr.ms(start)}")

    def _adapt_prosody(self, guest, row, items):
        """NVDA resolves a rate, pitch, or volume command against the configured value of the synthesizer in
        use, this driver's, which is not the value the piece is spoken at: the capital pitch change of +30
        must land on the default voice's own pitch, or on the row's in a row's piece, and the reset after it
        back there. Each such command is replaced by one that reaches that value in the form the guest reads
        (hosts.prosody_mode). Commands the guest does not support are left out, as NVDA leaves them out for
        the synthesizer in use; NVDA sends them here because this driver supports them all (SAPI 5 fails on a
        pitch command to a SAPI 4 voice without pitch, and the whole piece is lost)."""
        try:
            supported = tuple(guest.supportedCommands)
            items = [i for i in items if isinstance(i, (str, IndexCommand)) or type(i) in supported]
        except Exception:
            pass
        mode = hosts.prosody_mode(guest)
        if mode in ("native", "offset"):
            # An offset added to the guest's own value, the row's, is what NVDA means by it.
            return items
        try:
            section = config.conf["speech"][self.name]
        except Exception:
            return items
        out = list(items)
        for i, item in enumerate(out):
            setting = PROSODY.get(type(item))
            if setting is None:
                continue
            if mode == "relative":
                out[i] = self._relative(guest, row, setting, item)
                continue
            offset, multiplier = _prosody_form(item)
            target = row.get(setting)
            try:
                if target is None:
                    target = config.conf["speech"][guest.name][setting]
                start = section[setting]
                if target is None or start is None:
                    continue
                target, start = int(target), int(start)
            except Exception:
                continue
            # A multiplier applies to the value the piece is spoken at, as an offset adds to it.
            wanted = int(target * multiplier) if not offset and multiplier != 1 else target + offset
            out[i] = type(item)(offset=wanted - start) if wanted != start else type(item)()
        return out

    @staticmethod
    def _relative(guest, row, setting, item):
        """A command for a guest that applies the multiplier to its own current value, the row's: an offset
        becomes the multiplier that reaches that value plus the offset, and a reset stays a reset."""
        if setting == "rate" and _is_sapi5(guest) and getattr(guest, "rateBoost", False):
            # Boosted SAPI 5 applies a rate multiplier twice, in its markup and in its speed-up.
            return type(item)()
        offset = _prosody_form(item)[0]
        if not offset:
            # A reset, or a multiplier the guest applies to the row's value itself.
            return item
        try:
            # The row's value, which the guest was just given: eSpeak, still busy, reports its old one.
            current = row.get(setting)
            if current is None:
                current = hosts.read(guest, setting)
            current = int(current)
        except Exception:
            return item
        if current <= 0:
            return item
        return type(item)(multiplier=(current + offset) / current)

    def prune_guests(self):
        """Terminate the guests nothing needs: those the settings dialog loaded to list a synthesizer's voices."""
        wanted = set(self.table.synths()) | {self.host_name}
        if self._windows_voices_needed():
            wanted.add(winvoices.ONECORE)
        for name in wanted:
            self.guest(name)
        for name in list(self.guests):
            if name not in wanted:
                guest = self.guests.pop(name)
                self.scheduler.forget(guest)
                hosts.dispose(guest)

    def _rebuild_later(self):
        """Rebuild this driver around another default synthesizer, if it is still the one in use by then."""

        def rebuild():
            if synthDriverHandler.getSynth() is self:
                synthDriverHandler.setSynth(self.name)

        queueHandler.queueFunction(queueHandler.eventQueue, rebuild)

    def update_row(self, row):
        """A row's values changed from the synth settings ring: its next piece applies them, since the row's
        key changed. Unlike a saved table, no guest is rebuilt and speech goes on."""
        self.table.upsert(row)

    def _on_table_saved(self, table):
        section = config.conf[T.CONFIG_SECTION]
        if section["defaultSynth"] and section["defaultSynth"] != self.host_name:
            # Another default synthesizer: this driver is rebuilt around it; the settings panel switches to
            # the new default itself when nothing needs the table.
            self._rebuild_later()
            return
        if synthDriverHandler.getSynth() is self:
            # Through NVDA, so its speech manager resets too; a bare cancel would leave it waiting for indexes.
            import speech

            speech.cancelSpeech()
        else:
            self.scheduler.cancel()
        self.table = table.copy()
        self._failed.clear()
        self._windows_rows.clear()
        winvoices.refresh()
        for guest in self.guests.values():
            guest._mlangApplied = None
            # NVDA caches a driver's voice list for the life of the instance; a Windows voice installed since
            # is in the registry the implicit rows are read from, and OneCore would refuse it as unknown.
            guest.__dict__.pop("_availableVoices", None)
        self.prune_guests()
        hosts.restore_current()

    # ------------------------------------------------------------ settings storage: the host's section

    def initSettings(self):
        """Called by NVDA once this driver is built. The host loaded its own section when it was created,
        so nothing is loaded here; this driver's section is created for what NVDA keeps per synthesizer
        name, and NVDA's settings ring and voice dictionary are pointed at this driver, as NVDA's own
        version does through changeVoice."""
        section = config.conf["speech"]
        if not section.isSet(self.name):
            section[self.name] = {}
        section[self.name].spec.update(self.getConfigSpec())
        self._share_per_synth(to_host=False)
        self._snapshot_defaults()
        synthDriverHandler.changeVoice(self, None)

    def loadSettings(self, onlyChanged=False):
        """A configuration profile switched: the host reloads its own section, and the table may differ."""
        host = self.__dict__.get("host")
        if host is None:
            return
        try:
            host.loadSettings(onlyChanged=onlyChanged)
        except Exception:
            log.debugWarning(f"multilanguage: {self.host_name} could not reload its settings", exc_info=True)
        host._mlangApplied = None
        self._snapshot_defaults(configured=True)
        # The host's reload pointed NVDA's settings ring and voice dictionary at it; back to this driver.
        hosts.restore_current()
        # A configuration profile may carry another default synthesizer. The host is reloaded first all the
        # same: the rebuild terminates this driver, which saves the host's values into this profile. One
        # that already failed to load, for which a stand-in is hosting, is not retried on every switch.
        wanted = config.conf[T.CONFIG_SECTION]["defaultSynth"]
        if wanted and wanted not in (self.name, "auto", "silence", self.host_name) and wanted not in self._failed:
            self._rebuild_later()
            return
        # A configuration profile may carry another table.
        table = T.load(config.conf)
        if table != self.table:
            self._on_table_saved(table)

    def saveSettings(self):
        """The host's own values go into the host's own section: the snapshot for the settings a row can
        change, so a save while a row is applied does not make the row's parameters the user's, and the
        host's live values for the rest, which no row touches."""
        host = self.__dict__.get("host")
        if host is None:
            return
        section = config.conf["speech"][host.name]
        for setting, value in hosts.own_values(host.supportedSettings, self._defaults, lambda name: getattr(host, name)):
            try:
                section[setting] = value
            except Exception:
                log.debugWarning(f"multilanguage: could not save {setting} for {host.name}", exc_info=True)
        self._share_per_synth(to_host=True)

    def _share_per_synth(self, to_host):
        """NVDA's settings kept per synthesizer name (PER_SYNTH), copied from the host's section into this
        driver's when it is built, and back whenever its settings are saved, which terminate does too."""
        try:
            speech = config.conf["speech"]
            ours, theirs = speech[self.name], speech[self.host_name]
        except Exception:
            return
        source, dest = (ours, theirs) if to_host else (theirs, ours)
        for setting in PER_SYNTH:
            try:
                dest[setting] = source[setting]
            except Exception:
                log.debugWarning(f"multilanguage: could not share {setting} with {self.host_name}", exc_info=True)

    # ------------------------------------------------------------ speech

    def speak(self, speechSequence):
        self.scheduler.speak(speechSequence, self._row_for_lang, self.default_row())

    def cancel(self):
        self.scheduler.cancel()

    def pause(self, switch):
        self.scheduler.pause(switch)

    def _on_guest_index(self, synth=None, index=None):
        if synth is None or synth is self:
            return
        if getattr(synth, "name", None) == "AcaTTS" and isinstance(index, int) and index % 2:
            # Acapela writes each mark one higher than it is given; the scheduler gives only even ones.
            index -= 1
        engine = _eloquence(synth) if self.scheduler.is_marker(index) else None
        if not self.scheduler.on_index(synth, index):
            if _done_early(synth):
                # A mark reported again once the audio before it has played: the end marker of the guest's
                # last piece frees it.
                self.scheduler.on_played(synth, index)
            return
        if engine is not None:
            # The end of a piece, its audio fed and still playing: the next guest may start when it has played
            # rather than on Eloquence's done, 0.3 seconds later. This runs on the thread that feeds the
            # player, so nothing of the piece is fed after the request.
            try:
                engine.player.feed(None, 0, onDone=lambda: self._on_eloquence_played(synth, engine, index))
            except Exception:
                log.debugWarning("multilanguage: Eloquence's player could not report the end of a piece", exc_info=True)

    def _on_eloquence_played(self, synth, engine, marker):
        tr.trace(f"Eloquence's player played up to {marker}")
        if self.scheduler.on_played(synth, marker) and not engine.speaking:
            # Its done, from before a piece sent to it next, would end that piece while it still speaks.
            # Its player idles by itself.
            engine.idleTimer.cancel()

    def _on_guest_done(self, synth=None):
        if synth is None or synth is self:
            return
        if getattr(synth, "_speakRequests", None) or _more_queued(synth):
            # SAPI 5 reports done after each request, with more of them still to speak; eSpeak after each call;
            # Acapela inside each call.
            tr.trace(f"done from {tr.name(synth)}: ignored, more of its calls queued")
            return
        queued = getattr(synth, "_queuedSpeech", None)
        if queued and any(isinstance(item, str) for item in queued):
            # OneCore's done from before a cancel, arriving after the next piece was queued.
            tr.trace(f"done from {tr.name(synth)}: ignored, from before a cancel")
            return
        if _reports_before_playing(synth):
            # Reported from its speaking thread, outside its player's callbacks. Changes of guest and voice wait
            # for it, so it is held until the audio has played; its marks need no holding, since a change of row
            # alone waits only until the text before them is synthesized.
            tr.trace(f"done from {tr.name(synth)}: held until its player has played")
            _after_playing(synth, lambda: self.scheduler.on_done(synth))
            return
        held = self.scheduler.holding(synth)
        self.scheduler.on_done(synth)
        token = self.scheduler.holding(synth)
        if token is not None and token is not held:
            self._release_later(self.scheduler, synth, token)

    def _release_later(self, scheduler, synth, token):
        """Free a guest held after its early done if the report that its audio played never comes: the end
        marker of its piece may have played before its synthesis ended, so that it was reported only once, or
        its synthesis failed."""
        def release():
            if scheduler.paused:
                # Its audio is paused too; the wait starts over.
                self._release_later(scheduler, synth, token)
            else:
                scheduler.release(synth, token)

        timer = threading.Timer(PLAYED_TIMEOUT, release)
        timer.daemon = True
        timer.start()

    def _notify_index(self, index):
        synthIndexReached.notify(synth=self, index=index)

    def _notify_done(self):
        synthDoneSpeaking.notify(synth=self)

    # ------------------------------------------------------------ settings: the host's, as this driver's

    def _get_supportedSettings(self):
        host = self.__dict__.get("host")
        return list(host.supportedSettings) if host is not None else []

    def _host_get(self, setting, fallback=None):
        """The host's own value: a row on the host's synthesizer leaves its values on the instance until the
        next default piece, and NVDA must never read those as the user's (the settings ring would step the
        row's rate and store it as the default)."""
        host = self.__dict__.get("host")
        if host is None:
            return fallback
        if setting in self._defaults:
            return self._defaults[setting]
        return getattr(host, setting)

    def _host_set(self, setting, value):
        host = self.__dict__.get("host")
        if host is None:
            return
        resets = setting in ("voice", "variant")
        if resets:
            # A voice or variant can reset the other settings (Eloquence copies a preset voice): set it on the
            # default's own values, not a row's, and take what it leaves as the default's.
            try:
                self._apply_row(host, self.default_row())
            except Exception:
                log.debugWarning("multilanguage: could not put the default back before a voice change", exc_info=True)
        setattr(host, setting, value)
        if setting in T.ROW_SETTINGS or setting in self._defaults:
            self._defaults[setting] = value
            self.__dict__["_default_row"] = None
        changed = {setting: value}
        if resets:
            for other in list(self._defaults):
                if other == setting:
                    continue
                try:
                    now = hosts.read(host, other)
                except Exception:
                    continue
                if now != self._defaults[other]:
                    self._defaults[other] = now
                    changed[other] = now
            self._snapshot_language()
        host._mlangApplied = None
        if not _settings_dialog_open():
            for name, now in changed.items():
                self._store(host, name, now)

    def _store(self, host, setting, value):
        """A change made outside NVDA's settings dialog (the synth settings ring) into the host's own section
        at once, as NVDA stores one for a synthesizer of its own. NVDA writes it to this driver's section,
        which nothing reads, and a configuration profile switch reloads the host from its own section and
        would put back the value from before."""
        for s in host.supportedSettings:
            if s.id != setting:
                continue
            if getattr(s, "useConfig", True):
                try:
                    config.conf["speech"][host.name][setting] = value
                except Exception:
                    log.debugWarning(f"multilanguage: could not store {setting} for {host.name}", exc_info=True)
            return

    def __getattr__(self, name):
        # Only reached for names no class attribute answers: a host's own settings and their choices.
        host = self.__dict__.get("host")
        if host is not None and (name.startswith("available") or host.isSupported(name)):
            # The default's own value, as _host_get gives for the standard settings: a row's variant may have
            # left another on the instance.
            defaults = self.__dict__.get("_defaults", {})
            if name in defaults:
                return defaults[name]
            return getattr(host, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        host = self.__dict__.get("host")
        if host is not None and name not in STANDARD and not hasattr(type(self), name) and host.isSupported(name):
            self._host_set(name, value)
            return
        super().__setattr__(name, value)

    def _get_voice(self):
        return self._host_get("voice", "")

    def _set_voice(self, value):
        self._host_set("voice", value)

    def _get_availableVoices(self):
        host = self.__dict__.get("host")
        if host is None:
            return OrderedDict()
        try:
            return host.availableVoices
        except Exception:
            return OrderedDict(table=VoiceInfo("table", self.description, None))

    def _get_variant(self):
        return self._host_get("variant")

    def _set_variant(self, value):
        self._host_set("variant", value)

    def _get_availableVariants(self):
        # The default voice's, not those of a row voice still on the host.
        variants = self.__dict__.get("_default_variants")
        if variants is not None:
            return variants
        return self._host_get("availableVariants", OrderedDict())

    def _get_rate(self):
        return self._host_get("rate", 50)

    def _set_rate(self, value):
        self._host_set("rate", value)

    def _get_rateBoost(self):
        return self._host_get("rateBoost", False)

    def _set_rateBoost(self, value):
        self._host_set("rateBoost", value)

    def _get_pitch(self):
        return self._host_get("pitch", 50)

    def _set_pitch(self, value):
        self._host_set("pitch", value)

    def _get_inflection(self):
        return self._host_get("inflection", 50)

    def _set_inflection(self, value):
        self._host_set("inflection", value)

    def _get_volume(self):
        return self._host_get("volume", 100)

    def _set_volume(self, value):
        self._host_set("volume", value)

    def _get_language(self):
        """The default voice's language, never that of a row voice still on the host after a foreign piece.
        With "trust voice's language" on, NVDA takes this as the default language and tags every utterance
        with it; the row's language there sends the whole next utterance to that row, which leaves the row's
        voice on the host again, and all speech stays in that language."""
        host = self.__dict__.get("host")
        if host is None:
            return None
        # The variant's first: Sonata's multilingual voices have one variant per language, and the voice
        # reports its first variant's. The default voice's variants, since the host's own list may be a row
        # voice's.
        for setting, available in (("variant", "availableVariants"), ("voice", "availableVoices")):
            try:
                value = self._defaults.get(setting)
                if value is not None:
                    info = getattr(self if setting == "variant" else host, available).get(value)
                    if info is not None and getattr(info, "language", None):
                        return info.language
            except Exception:
                pass
        language = self.__dict__.get("_default_language")
        if not language:
            # A synthesizer that gives its voices no language (the Acapela driver that plays through its
            # engine) is taken to speak NVDA's, as NVDA takes it when trusting the voice's language.
            import languageHandler

            language = languageHandler.getLanguage()
        return language

    def _get_availableLanguages(self):
        """The languages this driver speaks: its rows whose synthesizer loaded, the Windows voices', and the
        host's own."""
        host = self.__dict__.get("host")
        if host is None:
            return set()
        langs = {r.lang for r in self.table.rows if self.guest(r.synth) is not None}
        if policy.windows_voices_wanted(config.conf) and self.host_name != winvoices.ONECORE:
            try:
                langs.update(winvoices.languages())
            except Exception:
                pass
        try:
            langs.update(self._host_get("availableLanguages", set()))
        except Exception:
            pass
        return langs

    def languageIsSupported(self, lang):
        """Whether a language has somewhere to go: a row whose synthesizer loaded, a Windows voice, or the
        host. NVDA's own answers from availableLanguages, and announces a language it misses as not supported
        before every switch to it."""
        host = self.__dict__.get("host")
        if lang is None or host is None:
            return True
        try:
            return self._row_for_lang(lang) is not None or hosts.supports(host, lang)
        except Exception:
            return True
