"""Detector rules that need no real recognizer: typing echo by keyboard, a lone character by its script,
Cantonese beside Mandarin, the clause rules, and lines read among their sentences, over a recognizer
answering from a table."""
import unittest

import nvda_stub  # noqa: F401

from mlang.detector import Detector, clauses, common_words, sentence_window, slice_runs


class NoRecognizer:
    """Fails the test if the detector asks: one letter is never guessed."""

    def constrained(self, text, languages):
        raise AssertionError(f"recognizer asked about {text!r}")

    free = probability = constrained


def detector(default, configured, available=(), excluded=()):
    d = Detector(NoRecognizer(), default, configured)
    d.configure(default, configured, available, excluded)
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


def by_script(default, configured, available=(), named=None):
    d = Detector(NoRecognizer(), default, configured, mode="script")
    d.configure(default, configured, available, (), named)
    return d


class LoneLetterTests(unittest.TestCase):
    """A letter standing alone in a script the default does not write: read by its script's voice where
    there is one, unless the default language's symbol table names it."""

    def test_letter_in_a_line_takes_its_scripts_voice(self):
        d = by_script("en_US", [], available=["en_US", "ar_SA"])
        self.assertEqual(d.tagged("Is it س?"), [(None, "Is it "), ("ar_SA", "س"), (None, "?")])
        self.assertEqual(d.tagged("س"), [("ar_SA", "س")])

    def test_only_the_letter_and_its_marks_switch(self):
        d = by_script("en_US", ["ar_SA"])
        self.assertEqual(d.tagged("(ب) 5"), [(None, "("), ("ar_SA", "ب"), (None, ") 5")])
        self.assertEqual(d.tagged("سَ."), [("ar_SA", "سَ"), (None, ".")])

    def test_letter_without_a_voice_stays_with_the_default(self):
        self.assertEqual(by_script("en_US", ["fr_FR"]).tagged("Is it س?"), [(None, "Is it س?")])

    def test_letter_the_default_table_names_stays_with_the_default(self):
        d = by_script("en_US", [], available=["en_US", "el_GR"], named=lambda c: c == "π")
        self.assertEqual(d.tagged("π = 3.14"), [(None, "π = 3.14")])
        self.assertEqual(d.tagged("ε 0"), [("el_GR", "ε"), (None, " 0")])
        self.assertIsNone(d.character("π"))
        self.assertEqual(d.character("ε"), "el_GR")

    def test_modifier_letter_alone_stays_with_the_default(self):
        d = by_script("en_US", ["ja_JP"])
        for mark in ("々", "ヽ", "ー"):
            self.assertIsNone(d.character(mark), mark)
            self.assertEqual(d.tagged(f"A {mark} B"), [(None, f"A {mark} B")], mark)
        self.assertEqual(d.character("あ"), "ja_JP")

    def test_letter_in_tagged_text_takes_its_scripts_voice(self):
        d = by_script("en_US", ["ar_SA"])
        self.assertEqual(d.verified("Is it س?", "en_US"), [("en_US", "Is it "), ("ar_SA", "س"), ("en_US", "?")])
        self.assertEqual(by_script("en_US", ["fr_FR"]).verified("Is it س?", "en_US"), [("en_US", "Is it س?")])


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


class NeighbourTests(unittest.TestCase):
    """A clause the recognizer splits between configured neighbours, Spanish beside Portuguese, with an English
    word in it, as Discord's reaction buttons are: "Haz clic para reaccionar con heart"."""

    REACT = "Haz clic para reaccionar con heart"
    SHARES = {"en": 0.01, "es": 0.675, "it": 0.02, "pt": 0.295}

    class Shares:
        def __init__(self, shares, free):
            self.shares, self.frees = shares, free

        def constrained(self, text, languages):
            pairs = sorted(((c, self.shares.get(c, 0.0)) for c in languages), key=lambda p: -p[1])
            total = sum(p for _, p in pairs)
            return (pairs[0][0], pairs[0][1] / total) if total else None

        def free(self, text):
            return self.frees

        def probability(self, text, language):
            return self.shares.get(language, 0.0)

    class Dictionary:
        known = {
            "en_US": {"heart", "con", "para"},
            "es_ES": {"haz", "clic", "para", "reaccionar", "con"},
            "it_IT": {"con", "per"},
            "pt_BR": {"para", "com"},
        }

        def __init__(self, installed=("en_US", "es_ES", "it_IT", "pt_BR")):
            self.installed = installed

        def has(self, language):
            return language in self.installed

        def rejects_a_word(self, text, language):
            if language not in self.installed:
                return None
            return any(w.lower() not in self.known[language] for w in text.split())

        rejects_everywhere = rejects_a_word

    def tagged(self, text, shares=None, free=("es", 0.58), dictionary=None):
        configured = ["es_ES", "it_IT", "pt_BR"]
        d = Detector(self.Shares(shares or self.SHARES, free), "en_US", configured, dictionary or self.Dictionary())
        d.configure("en_US", configured)
        return d.tagged(text)

    def test_a_clause_split_between_neighbours_goes_to_the_leader(self):
        self.assertEqual(self.tagged(self.REACT), [("es_ES", self.REACT)])

    def test_not_while_a_neighbour_has_no_dictionary(self):
        dictionary = self.Dictionary(installed=("en_US", "es_ES", "it_IT"))
        self.assertEqual(self.tagged(self.REACT, dictionary=dictionary), [(None, self.REACT)])

    def test_not_with_a_word_neither_dictionary_knows(self):
        text = "Haz clic para reaccionar con thumbsup"
        self.assertEqual(self.tagged(text), [(None, text)])

    def test_not_where_the_free_guess_names_another_language(self):
        self.assertEqual(self.tagged(self.REACT, free=("ca", 0.6)), [(None, self.REACT)])

    def test_not_where_the_default_holds_more_than_a_confident_guess_leaves_it(self):
        shares = {"en": 0.2, "es": 0.5, "it": 0.05, "pt": 0.25}
        self.assertEqual(self.tagged(self.REACT, shares=shares), [(None, self.REACT)])

    def test_not_under_three_words(self):
        self.assertEqual(self.tagged("reaccionar heart"), [(None, "reaccionar heart")])


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
        text = "Filebox - Einfache"
        self.assertEqual([text[s:e] for s, e, _ in clauses(text)], ["Filebox", "Einfache"])

    def test_a_hyphen_inside_or_against_a_word_does_not(self):
        for text in ["e-mail address", "from -5 to 5", "well-known -- maybe"]:
            self.assertEqual(len(clauses(text)), 2 if "--" in text else 1, text)

    def test_a_point_comma_or_colon_between_digits_does_not_split(self):
        for text in ["about 2.6 metres", "omkring 2,6 meter", "at 8:05 tonight", "1,000 people"]:
            self.assertEqual([text[s:e] for s, e, _ in clauses(text)], [text], text)
        text = "Lesson 2. Then 3, and 4: done"
        self.assertEqual([text[s:e] for s, e, _ in clauses(text)], ["Lesson 2", "Then 3", "and 4", "done"])
        self.assertEqual([sentence for _, _, sentence in clauses("about 2.6 miles. Next")], [0, 1])

    def test_a_slash_splits_clauses_but_not_between_digits(self):
        text = "fantastico/a fantastic"
        self.assertEqual([text[s:e] for s, e, _ in clauses(text)], ["fantastico", "a fantastic"])
        text = "vorrebbe / he would like"
        self.assertEqual([text[s:e] for s, e, _ in clauses(text)], ["vorrebbe", "he would like"])
        for text in ["on 10/03/2026", "half is 1/2"]:
            self.assertEqual([text[s:e] for s, e, _ in clauses(text)], [text], text)

    def test_a_slash_in_an_abbreviation_or_a_unit_does_not_split(self):
        for text in ["International Trade Centre UNCTAD/WTO", "SAP R/3 system", "at 100 km/h", "2,29 g/l"]:
            self.assertEqual([text[s:e] for s, e, _ in clauses(text)], [text], text)
        text = "vorrebbe / he/she"
        self.assertEqual([text[s:e] for s, e, _ in clauses(text)], ["vorrebbe", "he", "she"])

    def test_a_one_word_clause_goes_by_the_dictionaries(self):
        class Dictionary:
            known = {"en_US": {"Marco"}, "it_IT": {"Chiedi", "Marco"}}

            def rejects_a_word(self, text, language):
                return text not in self.known[language]

            rejects_everywhere = rejects_a_word

        answers = {"Where is it": ("en", 0.99), "see you": ("en", 0.99)}
        d = Detector(Recognizer(answers), "en_US", ["it_IT"], Dictionary())
        self.assertEqual(d.tagged("INSTRUCTOR: Chiedi “Where is it?”"),
                         [(None, "INSTRUCTOR: "), ("it_IT", "Chiedi “"), (None, "Where is it?”")])
        # A name the default's dictionary knows stays with its sentence.
        self.assertEqual(d.tagged("Marco, see you."), [(None, "Marco, see you.")])

    def test_an_end_the_default_dictionary_rejects_is_not_peeled(self):
        class Dictionary:
            def rejects_a_word(self, text, language):
                return language.startswith("sv")

        answers = {"the row of trees marks the edge": ("en", 0.99), "the row of trees marks": ("en", 0.99),
                   "the edge": ("sv", 0.94)}
        clause = "the row of trees marks the edge"
        d = Detector(Recognizer(answers), "sv_SE", ["en_US"])
        self.assertEqual(d.tagged(clause), [("en_US", "the row of trees marks"), (None, " the edge")])
        d = Detector(Recognizer(answers), "sv_SE", ["en_US"], Dictionary())
        self.assertEqual(d.tagged(clause), [("en_US", clause)])

    def test_an_end_both_dictionaries_reject_stays_with_its_clause(self):
        # The trade-off in KNOWN_GAPS.md: "via npm" is read by the French voice, as no dictionary knows "npm".
        class Dictionary:
            def rejects_a_word(self, text, language):
                return "npm" in text

        answers = {"le paquet est installé via npm": ("fr", 0.99), "le paquet est installé": ("fr", 0.99),
                   "via npm": ("en", 0.95)}
        clause = "le paquet est installé via npm"
        d = Detector(Recognizer(answers), "en_US", ["fr_FR"], Dictionary())
        self.assertEqual(d.tagged(clause), [("fr_FR", clause)])

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

    def test_an_opening_bracket_goes_with_what_it_encloses(self):
        d = self.detector(["fr_FR"], {"Salut tout le monde": ("fr", 1.0), "I am new here": ("en", 1.0)})
        self.assertEqual(d.tagged("Salut tout le monde! (I am new here)"),
                         [("fr_FR", "Salut tout le monde! "), (None, "(I am new here)")])

    def test_a_sentence_of_short_clauses_is_scored_whole(self):
        answers = {"Soy encantado": ("es", 1.0), "Hola": ("es", 0.99), "Soy": ("es", 1.0), "encantado": ("es", 1.0)}
        d = self.detector(["es_ES"], answers)
        self.assertEqual(d.tagged("¡Hola! Soy Marcos, encantado."), [("es_ES", "¡Hola! Soy Marcos, encantado.")])

    def test_a_name_opening_a_later_clause_does_not_count(self):
        d = self.detector(["es_ES"], {"Hola Pedro": ("es", 1.0), "Hola": ("es", 0.99), "Pedro": ("es", 0.99)})
        self.assertEqual(d.tagged("Hola, Pedro."), [(None, "Hola, Pedro.")])

    def test_a_withheld_clause_is_judged_with_its_sentence(self):
        # Left free, fastText calls "non tu" Interlingua, and the whole sentence Italian.
        class Free(Recognizer):
            def __init__(self, answers, free):
                super().__init__(answers)
                self.frees = free

            def free(self, text):
                return self.frees.get(text)

        answers = {"non tu": ("it", 0.9999), "No non tu lei": ("it", 0.999), "lei": ("it", 0.6)}
        d = Detector(Free(answers, {"non tu": ("ia", 0.71), "No non tu lei": ("it", 0.95)}), "en_US", ["it_IT"])
        self.assertEqual(d.tagged("No, non tu, lei."), [(None, "No, "), ("it_IT", "non tu, lei.")])
        # A sentence that a language nobody configured outranks whole stays with the default.
        d = Detector(Free(answers, {"non tu": ("ia", 0.71), "No non tu lei": ("ia", 0.9)}), "en_US", ["it_IT"])
        self.assertEqual(d.tagged("No, non tu, lei."), [(None, "No, non tu, lei.")])

    def test_a_withheld_clause_s_sentence_is_not_switched_by_the_dictionaries_alone(self):
        # A guess short of the floor is never checked against the free one, so it may not switch the sentence.
        class Free(Recognizer):
            def free(self, text):
                return ("cbk", 0.9)

        class Dictionary:
            # English knows "gracias", so it does not switch alone as a one-word clause.
            known = {"en_US": {"gracias"}, "es_ES": {"amigo", "mío", "gracias"}}

            def rejects_a_word(self, text, language):
                return any(w not in self.known[language] for w in text.split())

            rejects_everywhere = rejects_a_word

        answers = {"amigo mío": ("es", 0.95), "amigo mío gracias": ("es", 0.7)}
        d = Detector(Free(answers), "en_US", ["es_ES"], Dictionary())
        self.assertEqual(d.tagged("amigo mío, gracias."), [(None, "amigo mío, gracias.")])

    def test_a_withheld_headline_s_sentence_needs_the_headline_bar(self):
        class Free(Recognizer):
            def free(self, text):
                return ("ia", 0.9) if text == "la casa rossa" else ("it", 0.95)

        answers = {"la casa rossa": ("it", 0.95), "la casa rossa bella": ("it", 0.95)}
        d = Detector(Free(answers), "en_US", ["it_IT"])
        self.assertEqual(d.tagged("LA CASA ROSSA, BELLA."), [(None, "LA CASA ROSSA, BELLA.")])

    def test_a_one_word_sentence_needs_the_line_to_agree(self):
        answers = {"Thanks": ("en", 0.9), "Hola amigo": ("es", 1.0), "Hola": ("es", 0.99), "amigo": ("es", 0.99)}
        d = self.detector(["es_ES"], answers)
        self.assertEqual(d.tagged("Thanks. Hola, amigo."), [(None, "Thanks. "), ("es_ES", "Hola, amigo.")])


class Asked(Recognizer):
    """A table recognizer that records what it is asked."""

    def __init__(self, answers):
        super().__init__(answers)
        self.asked = []

    def constrained(self, text, languages):
        self.asked.append(text)
        return super().constrained(text, languages)


class ContextTests(unittest.TestCase):
    """A line read alone, its undecided edges settled by the sentences it cuts."""

    TEXT = "We walked along the path. A row of trees marks the edge of the field."
    ANSWERS = {"We walked along the path": ("en", 0.99), "row of trees marks the edge of the field": ("en", 0.99)}

    def detector(self, answers=None):
        d = Detector(Asked(answers or self.ANSWERS), "sv_SE", ["en_US"])
        d.configure("sv_SE", ["en_US"])
        return d

    def test_a_sentence_s_first_word_ending_a_line_follows_its_sentence(self):
        line = "We walked along the path. A"
        d = self.detector()
        self.assertEqual(d.tagged(line), [("en_US", "We walked along the path. "), (None, "A")])
        self.assertEqual(d.in_context(line, self.TEXT, 0), [("en_US", line)])

    def test_a_last_word_alone_on_its_line_follows_its_sentence(self):
        start = self.TEXT.index("field.")
        self.assertEqual(self.detector().in_context("field.", self.TEXT, start), [("en_US", "field.")])

    def test_a_decided_line_reads_nothing_around_it(self):
        line = "We walked along the path."
        d = self.detector()
        self.assertFalse(d.undecided_edge(line))
        self.assertEqual(d.in_context(line, self.TEXT, 0), [("en_US", line)])
        self.assertNotIn("row of trees marks the edge of the field", d.backend.asked)

    def test_a_paragraph_s_end_is_not_crossed(self):
        text = "We walked along the path\nA"
        self.assertEqual(self.detector().in_context("A", text, len(text) - 1), [(None, "A")])

    def test_a_line_not_where_it_is_said_to_be_is_read_alone(self):
        self.assertEqual(self.detector().in_context("field.", self.TEXT, 0), [(None, "field.")])

    def test_a_grid_row_with_labels_is_read_alone(self):
        d = self.detector()
        d.labels = ("Subject",)
        self.assertEqual(d.in_context("We walked along the path. A", self.TEXT, 0)[-1], (None, "A"))

    def test_a_withheld_edge_guess_is_undecided(self):
        # "hazier blue" is English between Swedish and English, Italian left free.
        class Free(Recognizer):
            def free(self, text):
                return ("it", 0.86) if text == "hazier blue" else super().free(text)

        answers = {"fades to a lighter": ("en", 0.99), "hazier blue": ("en", 0.99)}
        d = Detector(Free(answers), "sv_SE", ["en_US"])
        self.assertTrue(d.undecided_edge("fades to a lighter, hazier blue"))
        self.assertFalse(d.undecided_edge("fades to a lighter"))

    def test_sentence_window(self):
        text = "One two three. Four five six seven. Eight nine"
        start = text.index("five")
        end = text.index("seven") + len("seven")
        self.assertEqual(text[slice(*sentence_window(text, start, end))], "Four five six seven.")
        start = text.index("Eight")
        self.assertEqual(text[slice(*sentence_window(text, start, len(text)))], "Eight nine")
        # A line ending its sentence in the space it wrapped at, or at a newline, is not widened.
        self.assertEqual(sentence_window(text, 0, len("One two three. ")), (0, len("One two three. ")))
        self.assertEqual(sentence_window("One two\nThree four", 0, 8), (0, 8))
        # At most `limit` characters each side, cut back to a space: "five" fits, "seven." does not.
        start = text.index("six")
        self.assertEqual(text[slice(*sentence_window(text, start, start + 3, limit=5))], "five six")

    def test_slice_runs(self):
        runs = [("en", "abc "), (None, "def"), ("en", " gh")]
        self.assertEqual(slice_runs(runs, 2, 9), [("en", "c "), (None, "def"), ("en", " g")])


class ExcludedTests(unittest.TestCase):
    """A row with detection off: its language is never switched to, by any route."""

    def test_a_voice_of_the_language_does_not_stand_in(self):
        d = detector("en_US", [], available=["en_US", "el_GR"], excluded=["el_GR"])
        self.assertIsNone(d.character("λ"))
        self.assertIsNone(d.keyboard("λ", "el_GR"))

    def test_the_free_guess_is_not_taken(self):
        class Constrained(Recognizer):
            def constrained(self, text, languages):
                g = self.answers.get(text)
                return g if g and g[0] in languages else None

        text = "Привет мир"
        answers = {text: ("ru", 0.99)}
        d = Detector(Constrained(answers), "en_US", [])
        d.configure("en_US", [])
        self.assertEqual(d.tagged(text), [("ru", text)])
        d.configure("en_US", [], excluded=["ru_RU"])
        self.assertEqual(d.tagged(text), [(None, text)])

    def test_another_row_of_the_language_that_detects_keeps_it(self):
        d = detector("en_US", ["pt_BR"], excluded=["pt_PT"])
        self.assertEqual(d.keyboard("ã", "pt_PT"), "pt_BR")

    def test_the_default_is_never_excluded(self):
        self.assertEqual(detector("en_US", ["fr_FR"], excluded=["en_GB"]).keyboard("e", "en_US"), "en_US")


if __name__ == "__main__":
    unittest.main()
