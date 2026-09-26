"""The row voices' dictionaries on a speech sequence: only the text in a language with a dictionary changes."""
import unittest

import nvda_stub  # noqa: F401
from speech.commands import IndexCommand, LangChangeCommand

from mlang.voicedict import apply


class Dictionary:
    def __init__(self, **replacements):
        self.replacements = replacements

    def sub(self, text):
        for pattern, replacement in self.replacements.items():
            text = text.replace(pattern, replacement)
        return text


class ApplyTest(unittest.TestCase):
    def test_only_runs_with_a_dictionary_change(self):
        arabic = Dictionary(**{"ai": "artificial intelligence"})
        dictionaries = {"ar": arabic}
        seq = ["ai here", LangChangeCommand("ar"), "ai there", IndexCommand(1), "and ai", LangChangeCommand("fr"), "ai too", LangChangeCommand(None), "ai back"]
        out = apply(seq, LangChangeCommand, dictionaries.get)
        self.assertEqual(out, [
            "ai here", LangChangeCommand("ar"), "artificial intelligence there", IndexCommand(1), "and artificial intelligence",
            LangChangeCommand("fr"), "ai too", LangChangeCommand(None), "ai back",
        ])
        self.assertIsNot(out, seq)
        self.assertEqual(seq[2], "ai there")  # the input is not modified

    def test_same_sequence_when_nothing_changes(self):
        seq = ["plain", LangChangeCommand("ar"), "plain", ""]
        self.assertIs(apply(seq, LangChangeCommand, lambda lang: Dictionary(x="y")), seq)
        self.assertIs(apply(seq, LangChangeCommand, lambda lang: None), seq)

    def test_base_language_lookup_is_the_callers(self):
        asked = []

        def dict_for(lang):
            asked.append(lang)
            return None

        apply([LangChangeCommand("ar_SA"), "a", LangChangeCommand("ar_SA"), "b"], LangChangeCommand, dict_for)
        self.assertEqual(asked, ["ar_SA", "ar_SA"])


if __name__ == "__main__":
    unittest.main()
