"""mlang.update: an install marks a configuration that has Dialingo's section, so the synthesizer follows the table
once at the next start, and the plugin drops the mark again."""
import unittest

import nvda_stub  # noqa: F401

from mlang.update import mark, unmark


class Mark(unittest.TestCase):
    def test_marked(self):
        profile = {"dialingo": {"table": "[...]"}}
        self.assertTrue(mark(profile))
        self.assertIs(profile["dialingo"]["followTable"], True)

    def test_first_install_left_alone(self):
        profile = {"speech": {"synth": "vocalizer_expressive2"}}
        self.assertFalse(mark(profile))
        self.assertNotIn("dialingo", profile)

    def test_already_marked(self):
        # As read from disk, before validation.
        profile = {"dialingo": {"followTable": "True"}}
        self.assertFalse(mark(profile))


class Unmark(unittest.TestCase):
    def test_dropped(self):
        profile = {"dialingo": {"table": "[...]", "followTable": True}}
        self.assertTrue(unmark(profile))
        self.assertEqual(profile, {"dialingo": {"table": "[...]"}})

    def test_nothing_to_drop(self):
        self.assertFalse(unmark({"dialingo": {"table": "[...]"}}))
        self.assertFalse(unmark({}))


if __name__ == "__main__":
    unittest.main()
