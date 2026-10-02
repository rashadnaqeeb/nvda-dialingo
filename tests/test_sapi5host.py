"""The table's 32-bit SAPI 5 proxy (sapi5host.Hosted32) against a stand-in for NVDA's: the add-on's driver loaded in
the host, the fallback to NVDA's when it cannot be, the pipes to the host each closed once, and the word that the
silence after its last piece may go."""
import unittest

import fake_bridge as fb
import nvda_stub  # noqa: F401
from speech.commands import IndexCommand

from mlang.sapi5host import DRIVER32, DROP_SILENCE, SPEECH_END, hosted


class Proxy32:
    """NVDA's sapi5_32: its init starts a host and loads the named driver there, which fails for `broken`."""

    name = "sapi5_32"
    synthDriver32Path = "nvda/_synthDrivers32"
    synthDriver32Name = "sapi5"
    broken = ()

    def __init__(self):
        self.conn = fb.launch()
        if self.synthDriver32Name in self.broken:
            raise RuntimeError(f"no module named {self.synthDriver32Name}")
        self.loaded = self.synthDriver32Name
        self.spoken = []

    def speak(self, speechSequence):
        self.spoken.append(list(speechSequence))


class Hosted32Test(unittest.TestCase):
    def setUp(self):
        fb.install(self)

    def pipes_closed(self, conn):
        return [pipe.closed for pipe in conn.stream._keepalive] == [True, True]

    def proxy(self, broken=()):
        cls = type("SynthDriver", (Proxy32,), {"broken": broken})
        Hosted = hosted(cls)
        self.assertIsNot(Hosted, cls)
        return Hosted()

    def test_the_host_loads_the_tables_driver(self):
        synth = self.proxy()
        self.assertEqual(synth.loaded, DRIVER32)
        self.assertEqual(synth.speechEndOffset, SPEECH_END)
        self.assertFalse(fb.made[0].closed)

    def test_nvdas_driver_is_loaded_when_the_tables_is_not_and_the_first_host_is_closed(self):
        synth = self.proxy(broken=(DRIVER32,))
        self.assertEqual(synth.loaded, "sapi5")
        self.assertIsNone(synth.speechEndOffset)
        self.assertEqual([c.closed for c in fb.made], [True, False])
        self.assertTrue(self.pipes_closed(fb.made[0]))
        self.assertIsInstance(fb.launcher.Connection, type)

    def test_both_hosts_are_closed_when_neither_driver_loads(self):
        with self.assertRaises(RuntimeError):
            self.proxy(broken=(DRIVER32, "sapi5"))
        self.assertEqual([c.closed for c in fb.made], [True, True])
        self.assertTrue(self.pipes_closed(fb.made[0]) and self.pipes_closed(fb.made[1]))
        self.assertIsInstance(fb.launcher.Connection, type)

    def test_the_pipes_to_the_host_are_closed_once_each(self):
        self.proxy()
        conn = fb.made[0]
        self.assertTrue(fb.owns_its_handles(conn))
        conn.close()  # the stream's own handles: it would raise on one the file objects closed
        self.assertTrue(self.pipes_closed(conn))

    def test_returning_puts_the_word_to_drop_the_silence_ahead_of_the_next_piece_only(self):
        synth = self.proxy()
        synth.speak(["one"])
        synth.mlangReturning()
        synth.speak(["two"])
        synth.speak(["three"])
        first = synth.spoken[1][0]
        self.assertIsInstance(first, IndexCommand)
        self.assertEqual(first.index, DROP_SILENCE)
        self.assertEqual([synth.spoken[0], synth.spoken[1][1:], synth.spoken[2]], [["one"], ["two"], ["three"]])

    def test_nvdas_driver_is_never_sent_the_word(self):
        synth = self.proxy(broken=(DRIVER32,))
        synth.mlangReturning()
        synth.speak(["one"])
        self.assertEqual(synth.spoken, [["one"]])

    def test_the_word_is_far_from_the_schedulers_markers_and_the_ends_of_speech(self):
        from mlang.scheduler import MAX_INDEX

        self.assertGreater(DROP_SILENCE, SPEECH_END + MAX_INDEX)


if __name__ == "__main__":
    unittest.main()
