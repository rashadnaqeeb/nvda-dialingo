# Install tasks of the multilanguage add-on.
# NVDA removes an add-on at the start of the session after the user asked for it, before any synthesizer is
# loaded, and runs onUninstall then. It runs it for the old copy on an update as well.

import os
import sys

import addonHandler
from addonHandler import AddonStateCategory, state
from logHandler import log


def _leaving():
    """mlang.leaving from this copy's library. The modules imported for it are dropped again, so that a copy of the
    add-on loaded later, an update or the same library under another name, imports its own."""
    lib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
    before = set(sys.modules)
    sys.path.insert(0, lib)
    try:
        from mlang import leaving

        return leaving
    finally:
        sys.path.remove(lib)
        for name in set(sys.modules) - before:
            if name == "mlang" or name.startswith("mlang."):
                del sys.modules[name]


def onUninstall():
    """Puts the language table's host back as NVDA's synthesizer (mlang.leaving)."""
    if addonHandler.getCodeAddon().name in state[AddonStateCategory.PENDING_INSTALL]:
        return  # an update: the new copy has the language table too
    _leaving().leave_nvda(log)
