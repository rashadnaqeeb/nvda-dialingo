# Install tasks of Dialingo.
# NVDA runs onInstall as the add-on is installed, in the session that installs it. It removes an add-on at the start
# of the session after the user asked for it, before any synthesizer is loaded, and runs onUninstall then; it runs
# it for the old copy on an update as well.

import importlib
import os
import sys

import addonHandler
from addonHandler import AddonStateCategory, state
from logHandler import log


def _ours(module):
    return module == "mlang" or module.startswith("mlang.")


def _mlang(name):
    """A module of mlang from this copy's library. At install, the running copy's mlang, or the old multilanguage's,
    is already loaded and would answer the import; it is set aside meanwhile and put back after. The modules imported
    here are dropped again, so that a copy of the add-on loaded later imports its own."""
    lib = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib")
    running = {module: sys.modules.pop(module) for module in list(sys.modules) if _ours(module)}
    sys.path.insert(0, lib)
    try:
        return importlib.import_module(f"mlang.{name}")
    finally:
        sys.path.remove(lib)
        for module in [module for module in sys.modules if _ours(module)]:
            del sys.modules[module]
        sys.modules.update(running)


def onInstall():
    """Dialingo was multilanguage before 1.0 (mlang.rename): its settings are copied, and the old copy is removed
    at the restart that installs this one, since both would load the language table."""
    rename = _mlang("rename")
    rename.apply_nvda(rename.copy_old, log)
    for addon in addonHandler.getAvailableAddons():
        if addon.name == rename.OLD_NAME and not addon.isPendingRemove:
            addon.requestRemove()
            log.info(f"dialingo: {rename.OLD_NAME} will be removed at the restart, replaced by Dialingo")


def onUninstall():
    """Puts the language table's host back as NVDA's synthesizer (mlang.leaving)."""
    if addonHandler.getCodeAddon().name in state[AddonStateCategory.PENDING_INSTALL]:
        return  # an update: the new copy has the language table too
    _mlang("leaving").leave_nvda(log)
