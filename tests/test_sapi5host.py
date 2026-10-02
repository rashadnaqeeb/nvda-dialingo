"""The table's 32-bit SAPI 5 proxy (sapi5host.Hosted32) against a stand-in for NVDA's: the add-on's driver loaded in
the host, the fallback to NVDA's when it cannot be, the pipes to the host each closed once, and the word that the
silence after its last piece may go."""
import ctypes
import msvcrt
import os
import sys
import types
import unittest
from ctypes import wintypes

import nvda_stub  # noqa: F401
from speech.commands import IndexCommand

from mlang.sapi5host import DRIVER32, DROP_SILENCE, SPEECH_END, hosted

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


class PipeStream:
    """rpyc's Win32PipeStream: it closes the raw handles of the file objects it was made from."""

    def __init__(self, incoming, outgoing):
        self._keepalive = (incoming, outgoing)
        self.incoming = msvcrt.get_osfhandle(incoming.fileno())
        self.outgoing = msvcrt.get_osfhandle(outgoing.fileno())

    def close(self):
        for handle in (self.incoming, self.outgoing):
            if not kernel32.CloseHandle(handle):
                raise OSError(f"handle {handle} was closed already")


class Connection:
    """NVDA's bridge connection, as its launcher makes one for each host process it starts."""

    def __init__(self, stream):
        self.stream = stream
        self.closed = False

    def close(self):
        self.closed = True
        self.stream.close()


launcher = types.ModuleType("_bridge.clients.synthDriverHost32.launcher")
launcher.Connection = Connection
made = []


class Proxy32:
    """NVDA's sapi5_32: its init starts a host and loads the named driver there, which fails for `broken`."""

    name = "sapi5_32"
    synthDriver32Path = "nvda/_synthDrivers32"
    synthDriver32Name = "sapi5"
    broken = ()

    def __init__(self):
        r, w = os.pipe()
        made.append(launcher.Connection(PipeStream(open(r, "rb"), open(w, "wb"))))
        if self.synthDriver32Name in self.broken:
            raise RuntimeError(f"no module named {self.synthDriver32Name}")
        self.loaded = self.synthDriver32Name
        self.spoken = []

    def speak(self, speechSequence):
        self.spoken.append(list(speechSequence))

    def terminate(self):
        self.terminated = True


class Hosted32Test(unittest.TestCase):
    def setUp(self):
        names = ["_bridge", "_bridge.clients", "_bridge.clients.synthDriverHost32"]
        for name in names:
            sys.modules[name] = types.ModuleType(name)
        sys.modules["_bridge.clients.synthDriverHost32"].launcher = launcher
        sys.modules[launcher.__name__] = launcher
        self.addCleanup(lambda: [sys.modules.pop(n, None) for n in names + [launcher.__name__]])
        made.clear()
        self.addCleanup(self.close_all)

    def close_all(self):
        # Each handle once: the stream's, then the file objects', which raise if theirs was the stream's.
        for conn in made:
            if not conn.closed:
                conn.close()
            for pipe in conn.stream._keepalive:
                pipe.close()

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
        self.assertFalse(made[0].closed)

    def test_nvdas_driver_is_loaded_when_the_tables_is_not_and_the_first_host_is_closed(self):
        synth = self.proxy(broken=(DRIVER32,))
        self.assertEqual(synth.loaded, "sapi5")
        self.assertIsNone(synth.speechEndOffset)
        self.assertEqual([c.closed for c in made], [True, False])
        self.assertTrue(self.pipes_closed(made[0]))
        self.assertIs(launcher.Connection, Connection)

    def test_both_hosts_are_closed_when_neither_driver_loads(self):
        with self.assertRaises(RuntimeError):
            self.proxy(broken=(DRIVER32, "sapi5"))
        self.assertEqual([c.closed for c in made], [True, True])
        self.assertTrue(self.pipes_closed(made[0]) and self.pipes_closed(made[1]))
        self.assertIs(launcher.Connection, Connection)

    def test_the_pipes_to_the_host_are_closed_once_each(self):
        synth = self.proxy()
        conn = made[0]
        synth.terminate()
        self.assertTrue(synth.terminated)
        self.assertTrue(self.pipes_closed(conn))
        conn.close()  # the stream's own handles: it would raise on one the file objects closed

    def test_a_stream_given_no_handles_of_its_own_closes_the_file_objects_handles(self):
        # The stand-in itself, as NVDA's stream is without the fix: the test above would fail.
        r, w = os.pipe()
        stream = PipeStream(open(r, "rb"), open(w, "wb"))
        stream.close()
        with self.assertRaises(OSError):
            stream._keepalive[0].close()
        with self.assertRaises(OSError):
            stream._keepalive[1].close()

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
