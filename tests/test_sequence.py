"""The sequence filter over a fake detector: tags inserted and restored, spelling and reader words left alone."""
import unittest

import nvda_stub  # noqa: F401
from speech.commands import CharacterModeCommand, IndexCommand, LangChangeCommand

from mlang.sequence import LineStrings, filter_sequence, locked_sequence, untagged_sequence


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

    def test_a_tag_listing_languages_is_read_as_untagged(self):
        seq = [LangChangeCommand("es,en"), "Say bonjour now", LangChangeCommand(None)]
        out = filter_sequence(seq, self.det, "en")
        self.assertEqual(out, [LangChangeCommand(None), "Say ", LangChangeCommand("fr"), "bonjour", LangChangeCommand(None), " now", LangChangeCommand(None)])

    def test_a_tag_naming_no_one_language_is_read_as_untagged(self):
        for tag in ("mul", "und", "es, en"):
            seq = [LangChangeCommand(tag), "Hello there"]
            self.assertEqual(filter_sequence(seq, self.det, "en"), [LangChangeCommand(None), "Hello there"])

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

    def test_a_line_string_read_in_context_replaces_its_own_detection(self):
        calls = []

        def line_runs(text, detected):
            calls.append((text, detected))
            return [(None, "the lake. "), ("sv", "A")] if text == "the lake. A" else None

        seq = [LangChangeCommand("fr"), "Bonjour", LangChangeCommand(None), "link", "the lake. A"]
        out = filter_sequence(seq, self.det, "en", line_runs=line_runs)
        self.assertEqual(calls, [("Bonjour", False), ("link", True), ("the lake. A", True)])
        self.assertEqual(out[-4:], ["the lake. ", LangChangeCommand("sv"), "A", LangChangeCommand(None)])

    def test_a_line_string_declined_is_detected_as_usual(self):
        out = filter_sequence(["Say bonjour now"], self.det, "en", line_runs=lambda text, detected: None)
        self.assertEqual(out, ["Say ", LangChangeCommand("fr"), "bonjour", LangChangeCommand(None), " now"])


class LineStringsTests(unittest.TestCase):
    AROUND = "Earlier line.\nA label reading A link, then A\nNext line."

    def place(self, *strings):
        line_start = self.AROUND.index("A label")
        line_end = self.AROUND.index("\nNext")
        placed = LineStrings()
        for s in strings:
            placed.add(s)
        return placed, placed.place_last(self.AROUND, line_start, line_end, {"link"})

    def test_a_string_is_found_after_the_strings_before_it(self):
        _, found = self.place("A label reading ", "A link", "link", ", then A")
        self.assertEqual(found, (self.AROUND.index(", then A"), ", then A"))
        _, found = self.place("A label reading A link, then ", "A")
        self.assertEqual(found, (self.AROUND.index("then A") + 5, "A"))

    def test_a_string_is_found_stripped(self):
        _, found = self.place("  A label reading A link, then A\r\n")
        self.assertEqual(found, (self.AROUND.index("A label"), "A label reading A link, then A"))

    def test_the_reader_s_words_and_strings_not_in_the_line_are_passed_over(self):
        placed, found = self.place("heading level 2", "link")
        self.assertIsNone(found)
        placed.add("A label")
        self.assertEqual(placed.place_last(self.AROUND, 0, len(self.AROUND), {"link"}), (self.AROUND.index("A label"), "A label"))

    def test_text_outside_the_line_is_not_found(self):
        _, found = self.place("Next line.")
        self.assertIsNone(found)

    def test_nvda_s_word_standing_later_in_the_line_is_not_placed_there(self):
        line = "Chapter level 2 notes"
        placed = LineStrings()
        for s in ("level 2", line):
            placed.add(s)
        self.assertEqual(placed.place_last(line, 0, len(line)), (0, line))

    def test_nvda_s_word_standing_just_there_gives_its_place_back(self):
        line = "This is bold text here"
        placed = LineStrings()
        for s in ("This is ", "bold", "bold text here"):
            placed.add(s)
        self.assertEqual(placed.place_last(line, 0, len(line)), (8, "bold text here"))


class LockedSequenceTests(unittest.TestCase):
    def test_locked_to_a_language_drops_every_tag_and_leads_with_its_own(self):
        seq = ["Say ", LangChangeCommand("fr"), "bonjour", LangChangeCommand(None), IndexCommand(1)]
        out = locked_sequence(seq, "es")
        self.assertEqual(out, [LangChangeCommand("es"), "Say ", "bonjour", IndexCommand(1)])

    def test_locked_to_the_default_drops_every_tag(self):
        seq = [LangChangeCommand("fr"), "bonjour", LangChangeCommand(None)]
        self.assertEqual(locked_sequence(seq, None), ["bonjour"])

    def test_a_sequence_without_text_gets_no_tag(self):
        self.assertEqual(locked_sequence([IndexCommand(1)], "es"), [IndexCommand(1)])


class UntaggedSequenceTests(unittest.TestCase):
    def test_an_ignored_tag_becomes_the_default_and_others_stay(self):
        seq = [LangChangeCommand("fr_FR"), "Bonjour", LangChangeCommand("de"), "Hallo", LangChangeCommand(None)]
        out = untagged_sequence(seq, lambda lang: lang.startswith("fr"))
        self.assertEqual(out, [LangChangeCommand(None), "Bonjour", LangChangeCommand("de"), "Hallo", LangChangeCommand(None)])

    def test_a_sequence_with_nothing_ignored_is_returned_as_is(self):
        seq = [LangChangeCommand("de"), "Hallo"]
        self.assertIs(untagged_sequence(seq, lambda lang: False), seq)

    def test_the_text_is_then_detected_as_untagged(self):
        seq = untagged_sequence([LangChangeCommand("fr"), "Say bonjour"], lambda lang: lang == "fr")
        self.assertEqual(
            filter_sequence(seq, FakeDetector(), "en_US"),
            [LangChangeCommand(None), "Say ", LangChangeCommand("fr"), "bonjour", LangChangeCommand(None)],
        )


if __name__ == "__main__":
    unittest.main()
