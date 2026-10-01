"""The ring's words in the locked language, from catalogs as gettext keeps them."""
import unittest

import nvda_stub  # noqa: F401

from mlang.catalogs import SEPARATOR, Catalog, Words

RATE = "synth setting" + SEPARATOR + "Rate"
SPANISH = {RATE: "Velocidad", "Rate": "Velocidad de lectura", "on": "activado", "Volume": "Volumen"}
GERMAN = {RATE: "Geschwindigkeit", "on": "eingeschaltet"}


class CatalogTests(unittest.TestCase):
    def test_from_english_the_context_is_tried_first(self):
        c = Catalog({}, SPANISH)
        self.assertEqual(c.get("Rate", "synth setting"), "Velocidad")
        self.assertEqual(c.get("Rate"), "Velocidad de lectura")
        self.assertEqual(c.get("on"), "activado")

    def test_from_another_language_the_string_is_traced_to_its_original(self):
        c = Catalog(GERMAN, SPANISH)
        self.assertEqual(c.get("Geschwindigkeit", "synth setting"), "Velocidad")
        self.assertEqual(c.get("eingeschaltet"), "activado")

    def test_a_string_untranslated_in_use_is_its_own_original(self):
        self.assertEqual(Catalog(GERMAN, SPANISH).get("Volume"), "Volumen")

    def test_english_wanted_gives_the_original(self):
        c = Catalog(GERMAN, {}, english=True)
        self.assertEqual(c.get("Geschwindigkeit", "synth setting"), "Rate")
        self.assertIsNone(c.get("Anna"))

    def test_unknown_is_none(self):
        self.assertIsNone(Catalog({}, SPANISH).get("Anna"))


class WordsTests(unittest.TestCase):
    def test_the_first_catalog_that_knows_wins_and_the_rest_stay(self):
        ours = Catalog({}, {"Off": "Desactivada"})
        nvda = Catalog({}, {"Off": "desactivado", "on": "activado"})
        words = Words(ours, nvda)
        self.assertEqual(words("Off"), "Desactivada")
        self.assertEqual(words("on"), "activado")
        self.assertEqual(words("50"), "50")
        self.assertEqual(words("Microsoft Helena"), "Microsoft Helena")


if __name__ == "__main__":
    unittest.main()
