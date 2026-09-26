"""Rows as stored: what reaches a synthesizer and what stays with NVDA."""
import unittest

import nvda_stub  # noqa: F401

from mlang.table import Row, Table


class SymbolLevelTest(unittest.TestCase):
    def test_round_trips_and_stays_out_of_the_synthesizer_settings(self):
        row = Row("fr_FR", "ibmeci", symbolLevel=300, voice="196608", rate=50)
        table = Table.from_json(Table([row]).to_json())
        back = table.rows[0]
        self.assertEqual(back.symbolLevel, 300)
        self.assertEqual(back.settings, {"voice": "196608", "rate": 50})
        self.assertEqual(back.key(), Row("fr_FR", "ibmeci", voice="196608", rate=50).key())

    def test_absent_or_invalid_is_nvdas_own(self):
        self.assertIsNone(Row.from_dict({"lang": "fr", "synth": "espeak"}).symbolLevel)
        self.assertIsNone(Row.from_dict({"lang": "fr", "synth": "espeak", "symbolLevel": "most"}).symbolLevel)
        self.assertNotIn("symbolLevel", Row("fr", "espeak").to_dict())


class MalformedTest(unittest.TestCase):
    def test_stored_values_of_the_wrong_shape_are_an_empty_table(self):
        for text in ("not json", "[]", "5", '{"rows": 5}', '{"rows": null}', '{"rows": {"lang": "fr"}}'):
            self.assertEqual(Table.from_json(text).rows, [], text)
        rows = Table.from_json('{"rows": [7, {"lang": "fr", "synth": "espeak"}]}').rows
        self.assertEqual([r.lang for r in rows], ["fr"])


if __name__ == "__main__":
    unittest.main()
