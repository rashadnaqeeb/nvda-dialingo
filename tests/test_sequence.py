"""The sequence filter over a fake detector: tags inserted and restored, spelling and reader words left alone."""
import unittest

import nvda_stub  # noqa: F401
from speech.commands import CharacterModeCommand, IndexCommand, LangChangeCommand

from mlang.sequence import filter_sequence


class FakeDetector:
    mode = "full"

    def tagged(self, text):
        if "bonjour" in text:
            head, _, tail = text.partition("bonjour")
            return [(None, head), ("fr", "bonjour"), (None, tail)]
        return [(None, text)]

    def verified(self, text, tag):
        if "About this result" in text:
            return [(None, text)]
        return [(tag, text)]


class SequenceTests(unittest.TestCase):
    def setUp(self):
        self.det = FakeDetector()

    def test_untouched_sequence_is_returned_as_is(self):
        seq = ["Hello there", IndexCommand(1)]
        self.assertIs(filter_sequence(seq, self.det, "en"), seq)

    def test_foreign_run_is_wrapped_and_tag_restored(self):
        seq = ["Say bonjour now", IndexCommand(1)]
        out = filter_sequence(seq, self.det, "en")
        self.assertEqual(out, ["Say ", LangChangeCommand("fr"), "bonjour", LangChangeCommand(None), " now", IndexCommand(1)])

    def test_default_tagged_text_is_detected_and_tag_restored(self):
        seq = [LangChangeCommand("en_US"), "bonjour", LangChangeCommand(None)]
        out = filter_sequence(seq, self.det, "en")
        self.assertEqual(out, [LangChangeCommand("en_US"), LangChangeCommand("fr"), "bonjour", LangChangeCommand("en_US"), LangChangeCommand(None)])

    def test_default_tagged_text_left_alone_keeps_its_dialect(self):
        seq = [LangChangeCommand("en_US"), "Hello there", LangChangeCommand(None)]
        self.assertIs(filter_sequence(seq, self.det, "en_GB"), seq)
        seq = [LangChangeCommand("en_US"), "Say bonjour now", LangChangeCommand(None)]
        out = filter_sequence(seq, self.det, "en_GB")
        self.assertEqual(out, [LangChangeCommand("en_US"), "Say ", LangChangeCommand("fr"), "bonjour", LangChangeCommand("en_US"), " now", LangChangeCommand(None)])

    def test_default_tagged_text_trusted_when_option_off(self):
        seq = [LangChangeCommand("en"), "bonjour"]
        self.assertIs(filter_sequence(seq, self.det, "en", detect_in_default_tagged=False), seq)

    def test_foreign_tag_dropped_where_text_contradicts(self):
        seq = [LangChangeCommand("fr"), "About this result", LangChangeCommand(None)]
        out = filter_sequence(seq, self.det, "en")
        self.assertEqual(out, [LangChangeCommand("fr"), LangChangeCommand(None), "About this result", LangChangeCommand("fr"), LangChangeCommand(None)])

    def test_character_mode_is_left_alone(self):
        seq = [CharacterModeCommand(True), "bonjour", CharacterModeCommand(False)]
        self.assertIs(filter_sequence(seq, self.det, "en"), seq)

    def test_unit_at_caret_takes_its_line_language(self):
        unit = lambda text: "fr" if text.strip() == "é" else None  # noqa: E731
        seq = [CharacterModeCommand(True), "é", CharacterModeCommand(False)]
        out = filter_sequence(seq, self.det, "en", unit_language=unit)
        self.assertEqual(out, [CharacterModeCommand(True), LangChangeCommand("fr"), "é", LangChangeCommand(None), CharacterModeCommand(False)])
        word = lambda text: "fr" if text.strip() == "Bonjour" else None  # noqa: E731
        out = filter_sequence(["Bonjour", "bold"], self.det, "en", unit_language=word)
        self.assertEqual(out, [LangChangeCommand("fr"), "Bonjour", LangChangeCommand(None), "bold"])

    def test_unit_tagged_with_default_language_takes_its_line_language(self):
        unit = lambda text: "fr" if text.strip() == "é" else None  # noqa: E731
        seq = [LangChangeCommand("en_US"), "é", LangChangeCommand(None)]
        out = filter_sequence(seq, self.det, "en", unit_language=unit)
        self.assertEqual(out, [LangChangeCommand("en_US"), LangChangeCommand("fr"), "é", LangChangeCommand("en_US"), LangChangeCommand(None)])
        # With default-tagged text trusted, the application's tag stands.
        self.assertIs(filter_sequence(seq, self.det, "en", detect_in_default_tagged=False, unit_language=unit), seq)

    def test_unit_in_default_language_line_is_left_alone(self):
        seq = ["a"]
        self.assertIs(filter_sequence(seq, self.det, "en", unit_language=lambda text: None), seq)

    def test_unit_in_the_default_language_is_not_detected(self):
        # A word typed on a keyboard of the default language stays with the default voice.
        seq = ["bonjour"]
        self.assertIs(filter_sequence(seq, self.det, "en_GB", unit_language=lambda text: "en_US"), seq)
        seq = [LangChangeCommand("en_US"), "bonjour"]
        self.assertIs(filter_sequence(seq, self.det, "en", unit_language=lambda text: "en"), seq)

    def test_mode_off_passes_through(self):
        self.det.mode = "off"
        seq = ["bonjour"]
        self.assertIs(filter_sequence(seq, self.det, "en"), seq)
        self.det.mode = "full"


if __name__ == "__main__":
    unittest.main()
