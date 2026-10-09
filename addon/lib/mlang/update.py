"""An update can change what needs the language table: since 1.0.1, a row on the synthesizer in use with a voice of
its own needs it. The synthesizer follows the table only when the settings panel saves a change, so a row saved
before the update would stay off the table, and the synthesizer would keep picking its own voice for each tag.

So the install marks the base configuration (`followTable`), in memory, which NVDA saves on exit, and on disk, for a
user who saves no configuration on exit. At the next start the plugin drops the mark the same way and lets the
synthesizer follow the table once. A first install has no section of Dialingo's and nothing to follow.

No NVDA import at module level: the steps work on plain mappings, and `apply_nvda` goes through nvdaconf, which
imports what it needs.
"""
from . import nvdaconf
from .table import CONFIG_SECTION

KEY = "followTable"


def _section(profile):
    section = profile.get(CONFIG_SECTION)
    return section if hasattr(section, "get") else None


def mark(profile):
    """Returns whether anything changed."""
    section = _section(profile)
    if section is None or str(section.get(KEY)) == "True":
        return False
    section[KEY] = True
    return True


def unmark(profile):
    """Returns whether anything changed."""
    section = _section(profile)
    if section is None or KEY not in section:
        return False
    del section[KEY]
    return True


def apply_nvda(step, log):
    """`step` over the base configuration in memory and its file on disk. Profiles are left alone: the mark is read
    once, at the start, from the base."""
    step(nvdaconf.memory())
    files = nvdaconf.files(log)
    if files and step(files[0]):
        nvdaconf.write(files[0])
