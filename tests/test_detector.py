"""Detector rules that need no real recognizer: typing echo by keyboard, a lone character by its script,
Cantonese beside Mandarin, and the clause rules over a recognizer answering from a table."""
import unittest

import nvda_stub  # noqa: F401

from mlang.detector import Detector, clauses, common_words


class NoRecognizer:
    """Fails the test if the detector asks: one letter is never guessed."""

    def constrained(self, text, languages):
        raise AssertionError(f"recognizer asked about {text!r}")

    free = probability = constrained


def detector(default, configured, available=()):
    d = Detector(NoRecognizer(), default, configured)
    d.configure(default, configured, available)
    return d


class CharacterTests(unittest.TestCase):
    def test_letter_of_a_configured_script_takes_its_language(self):
        d = detector("en_US", ["ru_RU", "zh_CN"])
        self.assertEqual(d.character("ж"), "ru_RU")
        self.assertEqual(d.character("我"), "zh_CN")

    def test_letter_of_the_default_script_stays_default(self):
        d = detector("en_US", ["fr_FR", "ru_RU"])
        self.assertIsNone(d.character("é"))
        self.assertIsNone(d.character("a"))
        self.assertIsNone(d.character("5"))

    def test_latin_letter_under_another_default_takes_the_latin_row(self):
        self.assertEqual(detector("ru_RU", ["en_US"]).character("a"), "en_US")

    def test_first_configured_language_of_a_shared_script_wins(self):
        self.assertEqual(detector("en_US", ["uk_UA", "ru_RU"]).character("ж"), "uk_UA")

    def test_kana_goes_to_japanese_and_han_to_chinese(self):
        d = detector("en_US", ["ja_JP", "zh_CN"])
        self.assertEqual(d.character("あ"), "ja_JP")
        self.assertEqual(d.character("我"), "zh_CN")

    def test_script_the_default_writes_stays_default(self):
        # A lone kanji beside a Japanese default, a Cyrillic letter beside a Serbian one.
        self.assertIsNone(detector("ja_JP", ["zh_CN"]).character("我"))
        self.assertIsNone(detector("sr_RS", ["ru_RU"]).character("ж"))

    def test_voice_languages_stand_in_for_an_unconfigured_script(self):
        self.assertEqual(detector("en_US", [], available=["en_US", "el_GR"]).character("λ"), "el_GR")

    def test_script_nobody_speaks_is_left_to_the_default(self):
        self.assertIsNone(detector("en_US", ["fr_FR"]).character("ж"))

    def test_off_mode_never_tags(self):
        d = detector("en_US", ["ru_RU"])
        d.mode = "off"
        self.assertIsNone(d.character("ж"))


class KeyboardTests(unittest.TestCase):
    def test_echo_follows_a_keyboard_a_row_speaks(self):
        d = detector("en_US", ["fr_FR"])
        self.assertEqual(d.keyboard("e", "fr_FR"), "fr_FR")
        self.assertEqual(d.keyboard(",", "fr_FR"), "fr_FR")
        self.assertEqual(d.keyboard("chat", "fr_FR"), "fr_FR")

    def test_keyboard_dialect_takes_the_configured_spelling(self):
        self.assertEqual(detector("en_US", ["fr_FR"]).keyboard("e", "fr_CA"), "fr_FR")

    def test_keyboard_of_the_default_gives_the_default(self):
        d = detector("en_US", ["fr_FR"])
        self.assertEqual(d.keyboard("é", "en_GB"), "en_US")
        self.assertEqual(d.keyboard("bonjour", "en_US"), "en_US")

    def test_keyboard_a_voice_speaks_counts(self):
        self.assertEqual(detector("en_US", [], available=["en_US", "de_DE"]).keyboard("ß", "de_DE"), "de_DE")

    def test_keyboard_nobody_speaks_is_ignored(self):
        self.assertIsNone(detector("en_US", ["fr_FR"]).keyboard("e", "de_DE"))

    def test_letter_of_a_script_the_keyboard_does_not_write_is_left_to_its_script(self):
        d = detector("en_US", ["fr_FR", "ru_RU"])
        self.assertIsNone(d.keyboard("ж", "fr_FR"))
        self.assertEqual(d.character("ж"), "ru_RU")

    def test_exact_row_is_taken_over_another_dialect(self):
        d = detector("en_US", ["zh_CN", "zh_TW"])
        self.assertEqual(d.keyboard("我", "zh_TW"), "zh_TW")
        self.assertEqual(d.keyboard("我", "zh_CN"), "zh_CN")
        self.assertEqual(d.keyboard("我", "zh_SG"), "zh_CN")

    def test_hong_kong_keyboard_reaches_the_cantonese_row(self):
        d = detector("en_US", ["zh_CN", "zh_HK"])
        self.assertEqual(d.keyboard("我", "zh_HK"), "zh_HK")
        self.assertEqual(d.keyboard("我", "zh_TW"), "zh_CN")


class Recognizer:
    """Answers constrained() from a table of (language, probability) by text."""

    def __init__(self, answers):
        self.answers = answers

    def constrained(self, text, languages):
        return self.answers.get(text)

    def free(self, text):
        return self.answers.get(text)

    def probability(self, text, language):
        return 0.0


class ChineseTests(unittest.TestCase):
    def detector(self, configured, answers):
        d = Detector(Recognizer(answers), "en_US", configured)
        d.configure("en_US", configured)
        return d

    def test_cantonese_and_mandarin_rows_are_two_languages(self):
        d = self.detector(["zh_HK", "zh_CN"], {"我哋去食飯啦": ("yue", 1.0), "我們去吃飯吧": ("zh", 1.0)})
        self.assertEqual(d.tagged("我哋去食飯啦"), [("zh_HK", "我哋去食飯啦")])
        self.assertEqual(d.tagged("我們去吃飯吧"), [("zh_CN", "我們去吃飯吧")])

    def test_unclear_chinese_goes_to_mandarin_whatever_the_order(self):
        d = self.detector(["zh_HK", "zh_CN"], {"多謝": ("yue", 0.8), "睇": None})
        self.assertEqual(d.tagged("多謝"), [("zh_CN", "多謝")])
        self.assertEqual(d.tagged("睇"), [("zh_CN", "睇")])

    def test_one_chinese_row_takes_all_chinese(self):
        d = self.detector(["zh_HK"], {})
        self.assertEqual(d.tagged("我們去吃飯吧"), [("zh_HK", "我們去吃飯吧")])
        d = self.detector(["zh_CN"], {})
        self.assertEqual(d.tagged("我哋去食飯啦"), [("zh_CN", "我哋去食飯啦")])

    def test_lone_character_goes_to_mandarin_first(self):
        self.assertEqual(self.detector(["zh_HK", "zh_CN"], {}).character("我"), "zh_CN")

    def test_a_yue_row_is_written_in_han(self):
        d = self.detector(["yue", "zh_CN"], {"我哋去食飯啦": ("yue", 1.0)})
        self.assertEqual(d.tagged("我哋去食飯啦"), [("yue", "我哋去食飯啦")])


class ClauseTests(unittest.TestCase):
    def detector(self, configured, answers):
        d = Detector(Recognizer(answers), "en_US", configured)
        d.configure("en_US", configured)
        return d

    def test_a_spaced_hyphen_splits_clauses(self):
        text = "Wormhole - Einfache"
        self.assertEqual([text[s:e] for s, e, _ in clauses(text)], ["Wormhole", "Einfache"])

    def test_a_hyphen_inside_or_against_a_word_does_not(self):
        for text in ["e-mail address", "from -5 to 5", "well-known -- maybe"]:
            self.assertEqual(len(clauses(text)), 2 if "--" in text else 1, text)

    def test_a_noun_is_counted_where_a_name_is_not(self):
        self.assertEqual(common_words("private Dateifreigabe"), ["private"])
        self.assertEqual(common_words("private Dateifreigabe", lambda w: w == "Dateifreigabe"), ["private", "Dateifreigabe"])

    def test_german_nouns_need_a_german_row_and_a_near_certain_guess(self):
        answers = {"Dateifreigabe": ("de", 0.998), "Berlin": ("de", 0.79)}
        d = self.detector(["de_DE"], answers)
        self.assertTrue(d.is_noun("Dateifreigabe"))
        self.assertFalse(d.is_noun("Berlin"))
        self.assertFalse(self.detector(["es_ES"], answers).is_noun("Dateifreigabe"))

    def test_an_installed_german_dictionary_must_know_the_noun(self):
        class Dictionary:
            known = {"en_US": set(), "de_DE": {"Dateifreigabe"}}

            def rejects_a_word(self, text, language):
                return text not in self.known[language]

        answers = {"Dateifreigabe": ("de", 0.998), "Hreinlæti": ("de", 0.99)}
        d = Detector(Recognizer(answers), "en_US", ["de_DE"], Dictionary())
        self.assertTrue(d.is_noun("Dateifreigabe"))
        self.assertFalse(d.is_noun("Hreinlæti"))

    def test_an_opening_mark_goes_with_the_clause_after_it(self):
        d = self.detector(["es_ES"], {"Hello everyone": ("en", 1.0), "Cómo estás amigo": ("es", 1.0)})
        self.assertEqual(d.tagged("Hello everyone. ¿Cómo estás amigo?"),
                         [(None, "Hello everyone. "), ("es_ES", "¿Cómo estás amigo?")])

    def test_a_sentence_of_short_clauses_is_scored_whole(self):
        answers = {"Soy encantado": ("es", 1.0), "Hola": ("es", 0.99), "Soy": ("es", 1.0), "encantado": ("es", 1.0)}
        d = self.detector(["es_ES"], answers)
        self.assertEqual(d.tagged("¡Hola! Soy Alberto, encantado."), [("es_ES", "¡Hola! Soy Alberto, encantado.")])

    def test_a_name_opening_a_later_clause_does_not_count(self):
        d = self.detector(["es_ES"], {"Hola Pedro": ("es", 1.0), "Hola": ("es", 0.99), "Pedro": ("es", 0.99)})
        self.assertEqual(d.tagged("Hola, Pedro."), [(None, "Hola, Pedro.")])

    def test_a_one_word_sentence_needs_the_line_to_agree(self):
        answers = {"Thanks": ("en", 0.9), "Hola amigo": ("es", 1.0), "Hola": ("es", 0.99), "amigo": ("es", 0.99)}
        d = self.detector(["es_ES"], answers)
        self.assertEqual(d.tagged("Thanks. Hola, amigo."), [(None, "Thanks. "), ("es_ES", "Hola, amigo.")])


if __name__ == "__main__":
    unittest.main()
