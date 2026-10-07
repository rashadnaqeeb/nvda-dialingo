"""mlang.rename: the settings of multilanguage are copied into Dialingo's section at install, and the old section is
dropped once Dialingo runs, in the base configuration and in profiles alike."""
import unittest

import nvda_stub  # noqa: F401

from mlang.rename import copy_old, drop_old


class CopyOld(unittest.TestCase):
    def test_copied(self):
        profile = {"multilanguage": {"table": "[...]", "defaultSynth": "ibmeci"}}
        self.assertTrue(copy_old(profile))
        self.assertEqual(profile["dialingo"], {"table": "[...]", "defaultSynth": "ibmeci"})
        self.assertIn("multilanguage", profile)

    def test_existing_section_kept(self):
        profile = {"multilanguage": {"defaultSynth": "ibmeci"}, "dialingo": {"defaultSynth": "espeak"}}
        self.assertFalse(copy_old(profile))
        self.assertEqual(profile["dialingo"], {"defaultSynth": "espeak"})

    def test_nothing_to_copy(self):
        profile = {"speech": {"synth": "espeak"}}
        self.assertFalse(copy_old(profile))
        self.assertNotIn("dialingo", profile)


class DropOld(unittest.TestCase):
    def test_dropped_after_copy(self):
        profile = {"multilanguage": {"defaultSynth": "ibmeci"}, "dialingo": {"defaultSynth": "ibmeci"}}
        self.assertTrue(drop_old(profile))
        self.assertEqual(profile, {"dialingo": {"defaultSynth": "ibmeci"}})

    def test_moved_when_never_copied(self):
        profile = {"multilanguage": {"defaultSynth": "ibmeci"}}
        self.assertTrue(drop_old(profile))
        self.assertEqual(profile, {"dialingo": {"defaultSynth": "ibmeci"}})

    def test_left_table_carried_over(self):
        # As written to disk by the old copy's onUninstall, after the copy at install.
        profile = {"multilanguage": {"defaultSynth": "ibmeci", "leftTable": "True"}, "dialingo": {"defaultSynth": "ibmeci"}}
        drop_old(profile)
        self.assertIs(profile["dialingo"]["leftTable"], True)

    def test_nothing_to_drop(self):
        profile = {"dialingo": {"defaultSynth": "ibmeci"}}
        self.assertFalse(drop_old(profile))


if __name__ == "__main__":
    unittest.main()
