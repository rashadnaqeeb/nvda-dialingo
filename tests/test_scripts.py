"""Script runs, language codes, and the recognizers' code mapping and strict cap, without the model or ELS."""
import unittest

import nvda_stub  # noqa: F401
from mlang import detector, recognizers
from mlang import scripts as S

CJK_AND_LATIN = frozenset(("Latn", "Hani", "Hira", "Kana"))


class CommonModifierLetterTests(unittest.TestCase):
    def runs(self, text, scripts):
        return [(script, text[start:end]) for script, start, end in S.letter_runs(text, scripts)]

    def test_long_vowel_mark_stays_in_the_katakana_word(self):
        self.assertEqual(self.runs("I like コーヒー very much.", CJK_AND_LATIN),
                         [("Latn", "I"), ("Latn", "like"), ("Kana", "コーヒー"), ("Latn", "very"), ("Latn", "much")])
        self.assertEqual(self.runs("Menu: コンピューター", CJK_AND_LATIN)[-1], ("Kana", "コンピューター"))
        self.assertEqual(self.runs("ｺｰﾋｰ", CJK_AND_LATIN), [("Kana", "ｺｰﾋｰ")])

    def test_foreign_segment_covers_the_whole_katakana_word(self):
        text = "I like コーヒー very much."
        foreign = [text[a:b] for scripts, a, b in S.segments(text, "Latn", CJK_AND_LATIN) if scripts]
        self.assertEqual(foreign, ["コーヒー"])

    def test_apostrophe_letter_and_tatweel_stay_in_their_words(self):
        self.assertEqual(self.runs("мʼясо", {"Latn", "Cyrl"}), [("Cyrl", "мʼясо")])
        self.assertEqual(self.runs("مـرحبا", {"Latn", "Arab"}), [("Arab", "مـرحبا")])

    def test_modifier_letter_never_starts_a_run(self):
        self.assertEqual(self.runs("ー", CJK_AND_LATIN), [])
        self.assertEqual(self.runs("a ー b", CJK_AND_LATIN), [("Latn", "a"), ("Latn", "b")])

    def test_unlisted_script_run_keeps_its_modifier_letter(self):
        self.assertEqual(self.runs("мʼясо", {"Latn"}), [("other", "мʼясо")])

    def test_cjk_sentence_end_still_splits(self):
        text = "我喜欢喝茶。コーヒーも好き"
        segs = [scripts for scripts, _, _ in S.segments(text, "Hani", CJK_AND_LATIN, ("Hani",))]
        self.assertEqual(len(segs), 2)


class CodeTests(unittest.TestCase):
    def test_recognizer_aliases_map_to_windows_codes(self):
        self.assertEqual(S.code("no"), "nb")
        self.assertEqual(S.code("no_NO"), "nb")
        self.assertEqual(S.code("nb-NO"), "nb")
        self.assertEqual(S.code("tl"), "fil")
        self.assertEqual(S.code("fil_PH"), "fil")
        self.assertEqual(S.code("fr_FR"), "fr")

    def test_chinese_of_hong_kong_and_macau_is_cantonese(self):
        self.assertEqual(S.code("zh_HK"), "yue")
        self.assertEqual(S.code("zh-MO"), "yue")
        self.assertEqual(S.code("zh_Hant_HK"), "yue")
        self.assertEqual(S.code("yue"), "yue")
        self.assertEqual(S.code("zh_TW"), "zh")
        self.assertEqual(S.code("zh_CN"), "zh")

    def test_cantonese_is_written_in_han(self):
        self.assertEqual(S.scripts_of("yue"), frozenset({"Hani"}))
        self.assertEqual(S.scripts_of("yue_HK"), frozenset({"Hani"}))
        self.assertEqual(S.scripts_of("zh_HK"), frozenset({"Hani"}))


class FakeModel:
    def __init__(self, labels):
        self.labels = labels
        self.seen = []

    def predict(self, text, k):
        text.encode("utf-8")  # fasttext_pybind raises on what UTF-8 cannot encode
        self.seen.append(text)
        return self.labels, [0.8, 0.2][:len(self.labels)]


class FastTextMappingTests(unittest.TestCase):
    def backend(self, labels):
        b = recognizers.FastTextBackend.__new__(recognizers.FastTextBackend)
        b.model = FakeModel(labels)
        b.cache = {}
        return b

    def test_labels_come_back_as_windows_codes(self):
        b = self.backend(["__label__no", "__label__da"])
        self.assertEqual(b.constrained("Det er en fin dag", ["nb", "fr"]), ("nb", 1.0))
        self.assertEqual(b.free("Det er en fin dag"), ("nb", 0.8))

    def test_lone_surrogate_reaches_the_model_replaced(self):
        b = self.backend(["__label__en"])
        text = "abc \ud83d def"
        self.assertEqual(b.free(text), ("en", 0.8))
        self.assertEqual(b.model.seen, ["abc � def"])
        self.assertIn(text, b.cache)


class FakeBackend:
    def __init__(self, answer):
        self.answer = answer

    def constrained(self, text, languages):
        return self.answer


class StrictCapTests(unittest.TestCase):
    def ensemble(self, ft, els):
        e = recognizers.EnsembleBackend.__new__(recognizers.EnsembleBackend)
        e.ft = FakeBackend(ft)
        e.els = FakeBackend(els)
        return e

    def test_disagreed_guess_is_below_every_floor(self):
        for els in (("ca", 1.0), None):
            for p in (0.5, 0.95):
                lang, conf = self.ensemble(("fr", p), els).constrained("tant pis", ["en", "fr"])
                self.assertEqual(lang, "fr")
                self.assertLess(conf, detector.DICTIONARY_FLOOR)
                self.assertLess(conf, detector.SCRIPT_FLOOR)

    def test_agreed_guess_keeps_its_probability(self):
        self.assertEqual(self.ensemble(("fr", 0.95), ("fr", 1.0)).constrained("x", ["en", "fr"]), ("fr", 0.95))

    def test_guess_under_the_cap_is_returned_as_is(self):
        self.assertEqual(self.ensemble(("fr", 0.3), ("ca", 1.0)).constrained("x", ["en", "fr"]), ("fr", 0.3))


if __name__ == "__main__":
    unittest.main()
