"""Windows dictionary capability names and the install command; the install itself is not run."""
import unittest

import nvda_stub  # noqa: F401
from mlang import langpack


class LangpackTests(unittest.TestCase):
    def test_capability_names_use_the_full_locale(self):
        self.assertEqual(langpack.capability("es"), "Language.Basic~~~es-ES~0.0.1.0")
        self.assertEqual(langpack.capability("fr_FR"), "Language.Basic~~~fr-FR~0.0.1.0")
        self.assertEqual(langpack.capability("es_MX"), "Language.Basic~~~es-MX~0.0.1.0")
        self.assertEqual(langpack.capability("ar", "TextToSpeech"), "Language.TextToSpeech~~~ar-SA~0.0.1.0")

    def test_command_installs_in_order_and_stops_on_failure(self):
        names = ["Language.Basic~~~es-ES~0.0.1.0", "Language.TextToSpeech~~~es-ES~0.0.1.0"]
        command = langpack.command(names)
        self.assertTrue(command.startswith("$ErrorActionPreference = 'Stop'; "))
        self.assertLess(command.index(names[0]), command.index(names[1]))
        self.assertNotIn('"', command)


if __name__ == "__main__":
    unittest.main()
