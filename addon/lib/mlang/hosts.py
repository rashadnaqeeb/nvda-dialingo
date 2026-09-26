"""Guest synthesizer instances: creation, configuration from a table row, and the side effects to undo.

NVDA is imported inside the functions, so the module loads under the tests; nothing here runs there.

A driver instance carries state NVDA expects to be unique: creating one calls changeVoice, which points
the synth settings ring and the voice dictionary at the new instance, and it registers itself to save
its settings on every configuration save. A guest must do none of that to the user's setup, so after
creating one the current synthesizer's ring and dictionary are restored and the save hook removed.
"""
DRIVER_NAME = "languageTable"

# Synthesizers that cannot be hosted. WorldVoice is a language table of its own: it re-raises its engines'
# notifications as the synthesizer in use, patches NVDA while any instance of it exists, and starts NVDA's
# eSpeak inside itself, which takes over the eSpeak engine another guest speaks with.
REFUSED = {"WorldVoice"}


def create(name, log=None):
    """A fresh, initialized instance of the named synthesizer driver, or None when it cannot load. The
    settings dialog's temporary instance of it, when there is one, is taken over instead: some drivers keep
    their engine in module globals (eSpeak, Vocalizer), which a second instance re-initializes."""
    if name == DRIVER_NAME:
        return None
    if name in REFUSED:
        if log:
            log.warning(f"multilanguage: {name} cannot be hosted by the language table")
        return None
    import synthDriverHandler

    temp = _temps.pop(name, None)
    if temp is not None:
        try:
            # A row preview may have left its values on it.
            temp.loadSettings()
            temp._mlangApplied = None
            restore_current()
            return temp
        except Exception:
            if log:
                log.debugWarning(f"multilanguage: could not take over the settings dialog's {name}", exc_info=True)
            dispose(temp)
    guest = None
    try:
        cls = synthDriverHandler._getSynthDriver(name)
        if not cls.check():
            return None
        guest = cls()
        guest.initSettings()
        guest._unregisterConfigSaveAction()
        if hasattr(guest, "MAX_CONSECUTIVE_SPEECH_FAILURES"):
            # OneCore replaces the synthesizer in use after five failures in a row; a guest's failures must not
            # replace the language table.
            guest.MAX_CONSECUTIVE_SPEECH_FAILURES = 1 << 30
        if all(hasattr(guest, name) for name in ("_handleSpeechFailure", "_isProcessing", "_player", "_queuedSpeech")):
            _complete_failures(guest)
        _quiet_panel_updates(guest)
        if name == "AcaTTS" and hasattr(guest, "speakQueue"):
            _cancel_queued(guest)
    except Exception:
        if log:
            log.error(f"multilanguage: could not load synthesizer {name}", exc_info=True)
        if guest is not None:
            # Created but not set up: its engine runs, and creating it pointed the ring and dictionary at it.
            dispose(guest)
            restore_current()
        return None
    restore_current()
    return guest


def _complete_failures(guest):
    """OneCore, when an utterance fails before it ever made an audio player, returns from its failure handling
    still marked as speaking, with nothing queued: it never speaks or reports done again, and the language
    table waits on it. The failure is completed here, as OneCore does it once it has a player: the instance
    is freed and its done reported."""
    original = guest._handleSpeechFailure

    def handleSpeechFailure():
        original()
        if guest._isProcessing and guest._player is None and not guest._queuedSpeech:
            import synthDriverHandler

            guest._isProcessing = False
            synthDriverHandler.synthDoneSpeaking.notify(synth=guest)

    guest._handleSpeechFailure = handleSpeechFailure


def _cancel_queued(guest):
    """Acapela's cancel stops what it is speaking but leaves the calls queued behind it, which it then speaks,
    and whose done lands on the next piece. The queue is emptied first, as the calls taken off it."""
    import queue

    original = guest.cancel

    def cancel():
        q = guest.speakQueue
        try:
            while True:
                q.get_nowait()
                q.task_done()
        except (queue.Empty, ValueError):
            pass
        original()

    guest.cancel = cancel


def _quiet_panel_updates(guest):
    """Sonata, on every voice or variant change, fills the voice lists of NVDA's open speech settings panel
    with its own, whichever synthesizer the panel shows. A guest's changes (a row, a preview) must leave the
    panel alone; the synthesizer in use still updates it."""
    import sys

    module = sys.modules.get(type(guest).__module__)
    original = getattr(module, "update_displaied_params_on_voice_change", None)
    if original is None or hasattr(original, "_mlang_original"):
        return

    def update(synth, *args, **kwargs):
        import synthDriverHandler

        if synth is synthDriverHandler.getSynth():
            return original(synth, *args, **kwargs)

    update._mlang_original = original
    module.update_displaied_params_on_voice_change = update


def restore_current():
    """Point the settings ring and voice dictionary back at the current synthesizer."""
    import globalVars
    import speechDictHandler
    import synthDriverHandler

    current = synthDriverHandler.getSynth()
    if current is None:
        return
    try:
        if globalVars.settingsRing:
            globalVars.settingsRing.updateSupportedSettings(current)
        speechDictHandler.loadVoiceDict(current)
    except Exception:
        pass


def redirect_voice_dict():
    """NVDA loads the voice dictionary for the synthesizer in use from a file named after the synthesizer
    and its voice, on every voice change. For the language table that would be a dictionary of its own,
    and the default synthesizer's, the one the user edits as "Voice dictionary" when that synthesizer is
    in use, would go unused while it is hosted. So a load for the language table is sent to its host,
    and the dictionary is the host's for its current voice, as without this driver. Installed once."""
    import speechDictHandler

    original = speechDictHandler.loadVoiceDict
    if getattr(original, "_mlang_redirect", False):
        return

    def loadVoiceDict(synth):
        if getattr(synth, "name", None) == DRIVER_NAME:
            host = getattr(synth, "host", None)
            if host is not None:
                # The host with the table's voice, its own: the instance may still carry a row's voice.
                synth = _HostVoice(host, synth.voice)
        return original(synth)

    loadVoiceDict._mlang_redirect = True
    loadVoiceDict._mlang_original = original
    loadVoiceDict.__doc__ = original.__doc__
    speechDictHandler.loadVoiceDict = loadVoiceDict
    definitions = getattr(speechDictHandler, "definitions", None)
    if definitions is not None and getattr(definitions, "loadVoiceDict", None) is original:
        definitions.loadVoiceDict = loadVoiceDict


class _HostVoice:
    """A host as NVDA's voice dictionary sees it, with the voice given rather than the instance's."""

    def __init__(self, host, voice):
        self.__dict__["_host"] = host
        self.__dict__["voice"] = voice

    def __getattr__(self, name):
        return getattr(self.__dict__["_host"], name)


def dispose(guest):
    """Terminate a guest without persisting the parameters a row applied to it."""
    try:
        guest.cancel()
    except Exception:
        pass
    try:
        # terminate() saves the instance's settings to its own config section; reload them first
        # so what it saves is what the user had.
        guest.loadSettings()
    except Exception:
        pass
    try:
        guest.terminate()
    except Exception:
        pass


def own_values(settings, defaults, live):
    """(setting id, value) pairs to store as a host's own: `defaults` (the values snapshotted before any
    row was applied) for the settings it has, the live value from `live(id)` for every other setting.
    Settings NVDA does not keep in the configuration, and ones whose live value cannot be read, are left out.
    Pure, so the tests cover it."""
    out = []
    for setting in settings:
        if not getattr(setting, "useConfig", True):
            continue
        if setting.id in defaults:
            out.append((setting.id, defaults[setting.id]))
            continue
        try:
            out.append((setting.id, live(setting.id)))
        except Exception:
            continue
    return out


# OneCore keeps a requested rate, pitch, or volume and hands it to the engine only with the next utterance;
# until then its getters report the engine's old value.
_PENDING = {"rate": "_rate", "pitch": "_pitch", "volume": "_volume"}


def read(guest, setting):
    """A synthesizer's value of a setting as last set, not as its engine last reported it."""
    name = getattr(guest, "name", None)
    if name == "oneCore" and setting in _PENDING:
        pending = guest.__dict__.get(_PENDING[setting])
        if pending is not None:
            return pending
    if name == "AcaTTS" and setting == "pitch" and guest.__dict__.get("pitchFlag"):
        # The Acapela driver that plays through its engine keeps a pitch for its next utterance.
        return guest.__dict__.get("pitchValue")
    return getattr(guest, setting)


def speaks_declared(guest):
    """Whether a synthesizer says which languages its voices speak. One that gives none (the Acapela driver
    that plays through its engine) is taken to speak every language, rather than none."""
    try:
        return any(getattr(v, "language", None) for v in guest.availableVoices.values())
    except Exception:
        return True


def supports(guest, language):
    """Whether a synthesizer can speak a language by itself; see speaks_declared."""
    if not speaks_declared(guest):
        return True
    try:
        return guest.languageIsSupported(language)
    except Exception:
        return False


def prosody_mode(guest):
    """How a synthesizer reads NVDA's rate, pitch, and volume commands: "absolute" (newValue, from the
    configured value of the synthesizer in use, as Eloquence does), "relative" (the multiplier, on its own
    current value, as OneCore, SAPI 5, and eSpeak do), "offset" (the offset alone, added to its own current
    value, as Vocalizer does), or "native" (a 32-bit synthesizer in another process, which receives the
    command as NVDA made it and resolves it against its own values there)."""
    cls = type(guest)
    mode = _modes.get(cls)
    if mode is None:
        mode = _prosody_mode(cls)
        _modes[cls] = mode
    return mode


_modes = {}


def _prosody_mode(cls):
    import sys

    if any(c.__module__.startswith("_bridge") for c in cls.__mro__):
        return "native"
    names = set()
    ssml = False
    for module in {sys.modules.get(c.__module__) for c in cls.__mro__ if c.__module__.startswith("synthDrivers")}:
        if module is not None:
            names.update(_names_in(vars(module).values(), module.__name__))
            ssml = ssml or _converts_with_speech_xml(vars(module).values(), module.__name__)
    if "newValue" in names:
        return "absolute"
    if "multiplier" in names or ssml:
        # NVDA's SSML converter, which RHVoice builds on, writes the multiplier as a percentage.
        return "relative"
    if "offset" in names:
        return "offset"
    return "absolute"


def _converts_with_speech_xml(values, module_name):
    """Whether a module defines a class built on one of NVDA's speechXml converters."""
    return any(
        isinstance(v, type) and getattr(v, "__module__", None) == module_name
        and any(c.__module__ == "speechXml" for c in v.__mro__[1:])
        for v in values
    )


def _names_in(values, module_name):
    """Every global and attribute name the functions and classes of a module use, nested code included."""
    import types

    stack = []
    own = [v for v in values if getattr(v, "__module__", None) == module_name]
    classes = [v for v in own if isinstance(v, type)]
    for v in own + [w for c in classes for w in vars(c).values()]:
        v = getattr(v, "fget", None) or getattr(v, "__func__", None) or v
        code = getattr(v, "__code__", None)
        if isinstance(code, types.CodeType):
            stack.append(code)
    names = set()
    while stack:
        code = stack.pop()
        names.update(code.co_names)
        stack += [k for k in code.co_consts if isinstance(k, types.CodeType)]
    return names

# The order a row's settings are set in. Rate boost before rate: a driver's rate boost setter re-applies the
# rate it reads back, and eSpeak, busy, reads the engine's old one while the rate set before it waits in its
# queue; the rate set after it is the one that stands.
APPLY_ORDER = ("voice", "variant", "rateBoost", "rate", "pitch", "inflection", "volume")


def apply_row(guest, row, log=None):
    """Set a guest's voice and parameters from a row; only settings the guest supports are touched."""
    for setting in APPLY_ORDER:
        value = row.get(setting)
        if value is None:
            continue
        try:
            if not guest.isSupported(setting):
                continue
            if read(guest, setting) == value:
                continue
            setattr(guest, setting, value)
            if setting == "voice" and log and getattr(guest, "voice", value) != value:
                # SAPI 5 ignores a voice it does not have; the row then speaks in the voice last used.
                log.debugWarning(f"multilanguage: {guest.name} has no voice {value!r}")
            if setting == "voice" and isinstance(getattr(guest, "speakingLanguage", None), str):
                # Eloquence remembers the language its last language command switched to and skips a command
                # for that language again; a new voice is a new language, so the next command must be sent.
                guest.speakingLanguage = ""
        except Exception:
            if log:
                log.debugWarning(f"multilanguage: setting {setting}={value!r} on {guest.name} failed", exc_info=True)
    guest._mlangApplied = row.key()


# ---------------------------------------------------------------- instances for the settings dialog

_temps = {}


def instance(name):
    """An instance of a synthesizer for the settings dialog to enumerate voices and preview rows:
    the language table's own guest when it is the current synthesizer, the current synthesizer when it is
    the one asked for, a temporary instance otherwise (released by `release`)."""
    import synthDriverHandler

    current = synthDriverHandler.getSynth()
    if current is not None:
        if current.name == DRIVER_NAME:
            return current.guest(name)
        if current.name == name:
            return current
    if name not in _temps:
        guest = create(name)
        if guest is None:
            return None
        _temps[name] = guest
    return _temps[name]


def existing(name):
    """An instance of a synthesizer that already exists, for the speech path, which must never load one:
    the language table's guest, the current synthesizer, or the settings dialog's temporary instance."""
    import synthDriverHandler

    current = synthDriverHandler.getSynth()
    if current is not None:
        if current.name == DRIVER_NAME:
            guest = current.guests.get(name)
            if guest is not None:
                return guest
        elif current.name == name:
            return current
    return _temps.get(name)


def own_value(guest, setting):
    """A synthesizer's own value of a setting, the user's rather than a row's, for the row dialog's
    starting values: the language table's snapshot for its host, the configuration for its other guests,
    which carry the last row they spoke, and the instance otherwise, since a row on the synthesizer in use
    is spoken through prosody commands and leaves its settings alone. None when it cannot be read."""
    import config
    import synthDriverHandler

    current = synthDriverHandler.getSynth()
    if current is not None and current.name == DRIVER_NAME:
        if guest is getattr(current, "host", None):
            defaults = getattr(current, "_defaults", {})
            if setting in defaults:
                return defaults[setting]
        try:
            value = config.conf["speech"][guest.name][setting]
            if value is not None:
                return value
        except Exception:
            pass
    try:
        return read(guest, setting)
    except Exception:
        return None


def is_live(guest):
    import synthDriverHandler

    return synthDriverHandler.getSynth() is guest


def release():
    """Terminate the settings dialog's temporary instances, and the language table's guests it loaded."""
    import synthDriverHandler

    current = synthDriverHandler.getSynth()
    in_use = set()
    if current is not None:
        in_use.add(current.name)
        if current.name == DRIVER_NAME:
            in_use.update(getattr(current, "guests", None) or ())
    for name, guest in list(_temps.items()):
        if name in in_use:
            # Loaded again since, as the synthesizer in use or a guest of it: some drivers keep their engine in
            # module globals (eSpeak), and terminating this instance would stop that one. It is only dropped.
            continue
        dispose(guest)
    _temps.clear()
    if current is not None and current.name == DRIVER_NAME:
        try:
            current.prune_guests()
        except Exception:
            pass
    restore_current()
