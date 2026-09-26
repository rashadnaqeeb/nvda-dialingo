"""Prosody offsets around language runs on a single synthesizer."""
import unittest

import nvda_stub  # noqa: F401
from speech.commands import LangChangeCommand, PitchCommand, RateCommand, VolumeCommand  # noqa: F401

from mlang.prosody import apply_offsets, offsets, offsets_for
from mlang.table import Row


class OffsetTests(unittest.TestCase):
    def test_offsets_relative_to_configured(self):
        rows = [Row("fr", "ibmeci", rate=60, pitch=65), Row("de", "ibmeci", volume=80)]
        table = offsets(rows, {"rate": 85, "pitch": 65, "volume": 90}.get, lambda s: True)
        self.assertEqual(table, {"fr": {"rate": -25, "pitch": 0}, "de": {"volume": -10}})

    def test_unsupported_setting_skipped(self):
        table = offsets([Row("fr", "x", rate=60, pitch=10)], {"rate": 50, "pitch": 50}.get, lambda s: s == "rate")
        self.assertEqual(table, {"fr": {"rate": 10}})

    def test_dialect_rows_keep_their_own_offsets(self):
        rows = [Row("fr_CA", "espeak", rate=80), Row("fr-fr", "espeak", rate=30)]
        table = offsets(rows, {"rate": 50}.get, lambda s: True)
        self.assertEqual(table, {"fr_CA": {"rate": 30}, "fr_FR": {"rate": -20}})
        self.assertEqual(offsets_for(table, "fr-ca"), {"rate": 30})
        self.assertEqual(offsets_for(table, "fr_FR"), {"rate": -20})
        # No row of its own spelling: the first row of its base language, as Table.row_for.
        self.assertEqual(offsets_for(table, "fr"), {"rate": 30})
        self.assertIsNone(offsets_for(table, "de"))
        self.assertIsNone(offsets_for(table, None))


class ApplyTests(unittest.TestCase):
    def setUp(self):
        self.table = {"fr": {"rate": -25, "pitch": 0}}
        self.lookup = lambda lang: self.table.get(lang.split("_")[0]) if lang else None

    def test_untouched_when_no_rows_apply(self):
        seq = [LangChangeCommand("en"), "Hello"]
        self.assertIs(apply_offsets(seq, self.lookup), seq)

    def test_run_is_wrapped_and_reset(self):
        seq = ["Hi ", LangChangeCommand("fr"), "bonjour", LangChangeCommand(None), "bye"]
        out = apply_offsets(seq, self.lookup)
        self.assertEqual(out, [
            "Hi ", LangChangeCommand("fr"), RateCommand(-25), PitchCommand(0), "bonjour",
            LangChangeCommand(None), RateCommand(0), PitchCommand(0), "bye",
        ])

    def test_reset_at_end_when_run_is_last(self):
        seq = [LangChangeCommand("fr_FR"), "bonjour"]
        out = apply_offsets(seq, self.lookup)
        self.assertEqual(out[-2:], [RateCommand(0), PitchCommand(0)])

    def test_default_reset_inside_run_keeps_row_value(self):
        seq = [LangChangeCommand("fr"), "a", RateCommand(0), "b", LangChangeCommand(None)]
        out = apply_offsets(seq, self.lookup)
        self.assertEqual(out[4], RateCommand(-25))

    def test_change_inside_run_adds_to_row_value(self):
        self.table = {"fr": {"pitch": 10}}
        seq = [LangChangeCommand("fr"), PitchCommand(30), "A", PitchCommand(), "b", LangChangeCommand(None)]
        out = apply_offsets(seq, self.lookup)
        self.assertEqual(out[1:5], [PitchCommand(10), PitchCommand(40), "A", PitchCommand(10)])

    def test_multiplier_inside_run_is_kept(self):
        self.table = {"fr": {"rate": 10}}
        seq = [LangChangeCommand("fr"), RateCommand(multiplier=2), "vite", LangChangeCommand(None)]
        out = apply_offsets(seq, self.lookup)
        self.assertEqual(out[2], RateCommand(multiplier=2))


if __name__ == "__main__":
    unittest.main()
