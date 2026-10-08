"""When the language table synthesizer is needed, so the add-on selects it itself and hides it otherwise.

NVDA speaks through one synthesizer object, so a language spoken by another engine than the one in use
needs the hosting driver. That is the case for a row on another synthesizer, for a row on the one in use
with a voice or another setting of its own beyond rate, pitch, and volume, and, with Windows voices in use,
for any language a Windows voice speaks that the synthesizer in use cannot. NVDA is imported inside the
functions, so the module loads under the tests.
"""
from .hosts import DRIVER_NAME
from .prosody import COMMANDS
from .table import CONFIG_SECTION, load


def current_engine(conf):
    """The name of the engine actually speaking: the synthesizer in use, or the table's host."""
    import synthDriverHandler

    synth = synthDriverHandler.getSynth()
    name = synth.name if synth is not None else conf["speech"]["synth"]
    if name == DRIVER_NAME:
        return conf[CONFIG_SECTION]["defaultSynth"] or None
    return name


def _engine(conf):
    """(instance of the engine actually speaking, whether it was created for the question and must be
    disposed). When the table's default synthesizer was just changed, that is the new one, not the host
    still loaded, which the table is rebuilt around only afterwards."""
    import synthDriverHandler

    from . import hosts

    synth = synthDriverHandler.getSynth()
    if synth is None or synth.name != DRIVER_NAME:
        return synth, False
    host = getattr(synth, "host", None)
    engine = current_engine(conf)
    if not engine or (host is not None and host.name == engine):
        return host, False
    existing = hosts.existing(engine)
    if existing is not None:
        return existing, False
    if host is not None and engine in getattr(synth, "_failed", ()):
        # The configured default could not load and another synthesizer stands in; it is the one speaking,
        # and loading the configured one again would only fail again.
        return host, False
    return hosts.create(engine), True


def engine_supports(conf, language, synth=None):
    """Whether the engine actually speaking can switch to a language by itself."""
    temporary = False
    if synth is None:
        synth, temporary = _engine(conf)
    if synth is None:
        return False
    from . import hosts

    try:
        return hosts.supports(synth, language)
    finally:
        if temporary:
            from . import hosts

            hosts.dispose(synth)


def windows_voices_wanted(conf):
    return bool(conf[CONFIG_SECTION]["useWindowsVoices"])


def windows_languages_beyond_engine(conf):
    """The languages Windows voices speak that the engine in use cannot; empty unless Windows voices are
    in use or the engine is OneCore itself, which speaks them without help."""
    if not windows_voices_wanted(conf):
        return []
    from . import winvoices

    if current_engine(conf) == winvoices.ONECORE:
        return []
    synth, temporary = _engine(conf)
    if synth is None:
        # Not engine_supports with no instance: each call would try to load the engine again.
        return list(winvoices.languages())
    try:
        return [lang for lang in winvoices.languages() if not engine_supports(conf, lang, synth)]
    finally:
        if temporary:
            from . import hosts

            hosts.dispose(synth)


def _beyond_prosody(conf, row, engine):
    """Whether a row on the engine in use carries a setting prosody commands cannot: a voice, variant, rate
    boost, or inflection other than the engine's own. On the synthesizer in use, the synthesizer picks its own
    voice for a tag by rules of its own, which may miss the row's voice (Vocalizer Expressive takes the first
    voice whose language starts with the tag, so an es_CO voice for "es" and "es_CO", none for "es_MX")."""
    try:
        section = conf["speech"][engine]
    except KeyError:
        section = None
    for setting, value in row.settings.items():
        if setting in COMMANDS:
            continue
        try:
            own = section[setting] if section is not None else None
        except KeyError:
            own = None
        if own is None or str(own) != str(value):
            return True
    return False


def needs_table(conf):
    engine = current_engine(conf)
    if engine is None:
        return False
    if any(row.synth != engine or _beyond_prosody(conf, row, engine) for row in load(conf).rows):
        return True
    return bool(windows_languages_beyond_engine(conf))
