"""installTasks: mlang is loaded from the add-on's own library and dropped from the module cache again. Removing the
add-on puts the host back through mlang.leaving, and an update, which removes the old copy the same way, changes
nothing. Installing copies the settings of multilanguage and asks for that add-on's removal."""
import importlib.util
import os
import sys
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "addon", "installTasks.py")


class FakeAddon:
    def __init__(self, name, pending_remove=False):
        self.name = name
        self.isPendingRemove = pending_remove
        self.removal_requested = False

    def requestRemove(self):
        self.removal_requested = True


class Tasks(unittest.TestCase):
    def run_task(self, task, pending_install=(), installed=(), running=None):
        addonHandler = types.ModuleType("addonHandler")
        addonHandler.AddonStateCategory = types.SimpleNamespace(PENDING_INSTALL="pendingInstall")
        addonHandler.state = {"pendingInstall": set(pending_install)}
        addonHandler.getCodeAddon = lambda: types.SimpleNamespace(name="dialingo")
        addonHandler.getAvailableAddons = lambda: iter(installed)
        logHandler = types.ModuleType("logHandler")
        logHandler.log = mock.Mock()
        calls = []
        path_before = list(sys.path)
        # Without mlang loaded, so the task's own import, and its cleanup, are what is tested.
        saved = {k: v for k, v in sys.modules.items() if k == "mlang" or k.startswith("mlang.")}
        for k in saved:
            del sys.modules[k]
        sys.modules.update(running or {})
        try:
            with mock.patch.dict(sys.modules, {"addonHandler": addonHandler, "logHandler": logHandler}):
                spec = importlib.util.spec_from_file_location("installTasks", PATH)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                real = module._mlang

                def mlang(name):
                    m = real(name)
                    m.leave_nvda = lambda log: calls.append("leave")
                    m.apply_nvda = lambda step, log: calls.append(step.__name__)
                    return m

                module._mlang = mlang
                getattr(module, task)()
            left = {k: v for k, v in sys.modules.items() if k == "mlang" or k.startswith("mlang.")}
            self.assertEqual(sys.path, path_before)
        finally:
            for k in left:
                del sys.modules[k]
            sys.modules.update(saved)
        return calls, left

    def test_removal_puts_the_host_back(self):
        calls, left = self.run_task("onUninstall")
        self.assertEqual(calls, ["leave"])
        self.assertEqual(left, {})

    def test_update_left_alone(self):
        calls, _left = self.run_task("onUninstall", pending_install={"dialingo"})
        self.assertEqual(calls, [])

    def test_install_copies_settings_and_removes_multilanguage(self):
        old, other = FakeAddon("multilanguage"), FakeAddon("someOtherAddon")
        calls, left = self.run_task("onInstall", installed=[old, other])
        self.assertEqual(calls, ["copy_old"])
        self.assertEqual(left, {})
        self.assertTrue(old.removal_requested)
        self.assertFalse(other.removal_requested)

    def test_install_without_multilanguage(self):
        calls, _left = self.run_task("onInstall")
        self.assertEqual(calls, ["copy_old"])

    def test_install_leaves_a_pending_removal_alone(self):
        old = FakeAddon("multilanguage", pending_remove=True)
        self.run_task("onInstall", installed=[old])
        self.assertFalse(old.removal_requested)


    def test_install_while_another_mlang_is_loaded(self):
        # The old multilanguage is running at install, with its own mlang, which has no rename module.
        package = types.ModuleType("mlang")
        package.__path__ = []
        running = {"mlang": package, "mlang.table": types.ModuleType("mlang.table")}
        calls, left = self.run_task("onInstall", installed=[FakeAddon("multilanguage")], running=running)
        self.assertEqual(calls, ["copy_old"])
        self.assertEqual(left, running)


if __name__ == "__main__":
    unittest.main()
