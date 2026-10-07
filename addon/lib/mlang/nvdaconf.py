"""NVDA's configuration files on disk, the base configuration and each profile, read and written the way NVDA does.

For changes NVDA's own saving cannot be relied on to keep: made while the add-on is leaving or being installed,
or by a user who saves no configuration on exit. No NVDA import at module level.
"""


def read(path):
    """A configuration file, as NVDA reads its own (config.ConfigManager._loadConfig)."""
    from configobj import ConfigObj

    profile = ConfigObj(path, indent_type="\t", encoding="UTF-8", file_error=True)
    profile.newlines = "\r\n"
    return profile


def memory():
    """The base configuration in memory, which NVDA saves over its file on exit."""
    import config

    return config.conf.profiles[0]


def files(log):
    """The base configuration file and each profile file, read; empty when NVDA must not write to disk
    (secure mode, the launcher)."""
    import config
    import NVDAState

    if not NVDAState.shouldWriteToDisk():
        return []
    found = [read(memory().filename)]
    for name in config.conf.listProfiles():
        try:
            found.append(read(NVDAState.WritePaths.getProfileConfigFile(name)))
        except Exception:
            log.debugWarning(f"dialingo: profile {name} could not be read", exc_info=True)
    return found


def write(profile):
    from fileUtils import FaultTolerantFile

    with FaultTolerantFile(profile.filename) as f:
        profile.write(f)
