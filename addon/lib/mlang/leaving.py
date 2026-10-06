"""Puts the user's own synthesizer back when the add-on stops being loaded: removed, or disabled.

NVDA saves the name of the synthesizer chosen last, the language table's while it is in use. Without the add-on
NVDA cannot load it, and at every start falls back to a synthesizer of its own choosing, which it does not save.
So wherever a configuration names the language table, the base configuration and each profile, the name becomes
the table's host. Nothing else in those files is touched, so a user who saves no configuration on exit has
nothing else of theirs written.

The base configuration is also marked (`leftTable`), so that once the add-on is back, enabled again or
reinstalled, the plugin selects the language table again if the table still needs it.

No NVDA import at module level: `leave` works on plain mappings, and `leave_nvda` imports what it needs.
"""
from .hosts import DRIVER_NAME
from .table import CONFIG_SECTION

# NVDA's own default synthesizer: its usual order of synthesizers.
NVDA_DEFAULT = "auto"


def _get(section, key):
    return section.get(key) if hasattr(section, "get") else None


def put_back(profile, host):
    """Names a host in place of the language table in one configuration, where it names it: the
    configuration's own host if it has one, else `host`. Returns whether anything changed."""
    speech = profile.get("speech")
    if _get(speech, "synth") != DRIVER_NAME:
        return False
    speech["synth"] = _get(profile.get(CONFIG_SECTION), "defaultSynth") or host
    return True


def leave(base, profiles):
    """Puts the host back in the base configuration and in each profile. Returns the configurations changed:
    the base first if it is among them."""
    host = _get(base.get(CONFIG_SECTION), "defaultSynth") or NVDA_DEFAULT
    changed = []
    if put_back(base, host):
        if not hasattr(base.get(CONFIG_SECTION), "get"):
            base[CONFIG_SECTION] = {}
        base[CONFIG_SECTION]["leftTable"] = True
        changed.append(base)
    changed.extend(p for p in profiles if put_back(p, host))
    return changed


def leave_nvda(log):
    """leave over NVDA's configuration: the files on disk, and the base configuration in memory, which NVDA
    saves on exit over the file. Profiles in memory are left alone: they are written only once changed in
    this session, and then hold the user's own choice."""
    import config
    import NVDAState
    from configobj import ConfigObj
    from fileUtils import FaultTolerantFile

    if not NVDAState.shouldWriteToDisk():
        return

    def read(path):
        # As NVDA reads its own (config.ConfigManager._loadConfig).
        profile = ConfigObj(path, indent_type="\t", encoding="UTF-8", file_error=True)
        profile.newlines = "\r\n"
        return profile

    files = [read(config.conf.profiles[0].filename)]
    for name in config.conf.listProfiles():
        try:
            files.append(read(NVDAState.WritePaths.getProfileConfigFile(name)))
        except Exception:
            log.debugWarning(f"multilanguage: profile {name} could not be read", exc_info=True)
    changed = leave(files[0], files[1:])
    for profile in changed:
        with FaultTolerantFile(profile.filename) as f:
            profile.write(f)
        log.info(f"multilanguage: {profile.filename} names {profile['speech']['synth']} in place of the language table")
    if changed and changed[0] is files[0]:
        memory = config.conf.profiles[0]
        memory["speech"]["synth"] = files[0]["speech"]["synth"]
        if CONFIG_SECTION not in memory:
            memory[CONFIG_SECTION] = {}
        memory[CONFIG_SECTION]["leftTable"] = True
