"""installTasks.onUninstall: removing the add-on puts the host back through mlang.leaving, loaded from the add-on's
own library and dropped from the module cache again; an update, which removes the old copy the same way, changes
nothing."""
import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "addon", "installTasks.py")


class OnUninstall(unittest.TestCase):
    def run_task(self, pending_install=()):
        addonHandler = types.ModuleType("addonHandler")
        addonHandler.AddonStateCategory = types.SimpleNamespace(PENDING_INSTALL="pendingInstall")
        addonHandler.state = {"pendingInstall": set(pending_install)}
        addonHandler.getCodeAddon = lambda: types.SimpleNamespace(name="multilanguage")
        logHandler = types.ModuleType("logHandler")
        logHandler.log = mock.Mock()
        calls = []
        path_before = list(sys.path)
        # Without mlang loaded, so the task's own import, and its cleanup, are what is tested.
        saved = {k: v for k, v in sys.modules.items() if k == "mlang" or k.startswith("mlang.")}
        for k in saved:
            del sys.modules[k]
        try:
            with mock.patch.dict(sys.modules, {"addonHandler": addonHandler, "logHandler": logHandler}):
                spec = importlib.util.spec_from_file_location("installTasks", PATH)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                real = module._leaving

                def leaving():
                    m = real()
                    m.leave_nvda = lambda log: calls.append(log)
                    return m

                module._leaving = leaving
                module.onUninstall()
            left = [k for k in sys.modules if k == "mlang" or k.startswith("mlang.")]
            self.assertEqual(sys.path, path_before)
        finally:
            sys.modules.update(saved)
        return calls, left

    def test_removal_puts_the_host_back(self):
        calls, left = self.run_task()
        self.assertEqual(len(calls), 1)
        self.assertEqual(left, [])

    def test_update_left_alone(self):
        calls, _left = self.run_task(pending_install={"multilanguage"})
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
