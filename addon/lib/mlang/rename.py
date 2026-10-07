"""Dialingo was called multilanguage before 1.0, and NVDA takes the two names for two add-ons.

Installing Dialingo removes the old copy (installTasks.onInstall), and the settings come along. They are copied
to Dialingo's section at install, so that the language table, which loads before any plugin, finds them at the
next start; the old section is dropped once Dialingo runs. Profiles too, since the table follows configuration
profiles. The language table keeps its driver name, so a user on it stays on it.

No NVDA import at module level: the steps work on plain mappings, and `apply_nvda` goes through nvdaconf, which
imports what it needs.
"""
from . import nvdaconf
from .table import CONFIG_SECTION

OLD_NAME = "multilanguage"


def _section(profile, name):
    section = profile.get(name)
    return section if hasattr(section, "get") else None


def copy_old(profile):
    """Copies the old section into a configuration that has no section of Dialingo's. Returns whether anything
    changed."""
    old = _section(profile, OLD_NAME)
    if old is None or _section(profile, CONFIG_SECTION) is not None:
        return False
    profile[CONFIG_SECTION] = dict(old)
    return True


def drop_old(profile):
    """Drops the old section, moving it first where Dialingo has none. Returns whether anything changed."""
    old = _section(profile, OLD_NAME)
    if old is None:
        return False
    new = _section(profile, CONFIG_SECTION)
    if new is None:
        profile[CONFIG_SECTION] = dict(old)
    elif str(old.get("leftTable")) == "True":
        # The old copy put the host back as it was removed (leaving.py), after its settings were copied: the
        # table returns with Dialingo.
        new["leftTable"] = True
    del profile[OLD_NAME]
    return True


def apply_nvda(step, log):
    """`step` over the base configuration in memory and every configuration file on disk."""
    step(nvdaconf.memory())
    for profile in nvdaconf.files(log):
        if step(profile):
            nvdaconf.write(profile)
            log.info(f"dialingo: {profile.filename}: settings of {OLD_NAME} carried over to {CONFIG_SECTION}")
