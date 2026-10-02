"""The pipes of NVDA's 32-bit synth driver host, each closed once (mlang.pipes), against stand-ins for NVDA's
launcher and rpyc's stream over real pipes."""
import sys
import types
import unittest

import fake_bridge as fb
import nvda_stub  # noqa: F401

from mlang import pipes


def forget(conn):
    """A connection whose stream still closes its file objects' handles: only the file objects are closed, once."""
    fb.made.remove(conn)
    for pipe in conn.stream._keepalive:
        pipe.close()


class PipesTest(unittest.TestCase):
    def setUp(self):
        fb.install(self)

    def test_unfixed_the_stream_closes_the_handles_its_file_objects_close_again(self):
        # NVDA's fault, which the stand-ins reproduce: the other tests would fail without the fix.
        conn = fb.launch()
        fb.made.remove(conn)
        conn.close()
        for pipe in conn.stream._keepalive:
            with self.assertRaises(OSError):
                pipe.close()

    def test_a_connection_made_once_installed_closes_each_handle_once(self):
        self.assertTrue(pipes.install())
        conn = fb.launch()
        self.assertTrue(fb.owns_its_handles(conn))
        conn.close()  # the stream's own handles: it would raise on one already closed
        self.assertEqual([pipe.closed for pipe in conn.stream._keepalive], [True, True])

    def test_the_current_synthesizers_connections_are_fixed_when_installed(self):
        conn = fb.launch()
        fb.install(self, synth=types.SimpleNamespace(_heldConnections=[conn]))
        self.assertTrue(pipes.install())
        self.assertTrue(fb.owns_its_handles(conn))
        conn.close()
        self.assertEqual([pipe.closed for pipe in conn.stream._keepalive], [True, True])

    def test_the_table_installs_it_before_it_makes_a_guest(self):
        # At NVDA's start the language table makes its guests before the global plugin is loaded.
        class Proxy:
            name = "sapi4_32"

            @classmethod
            def check(cls):
                return True

            def __init__(self):
                self.conn = fb.launch()

            def initSettings(self):
                pass

            def _unregisterConfigSaveAction(self):
                pass

        sys.modules["synthDriverHandler"]._getSynthDriver = lambda name: Proxy
        for name, module in (("globalVars", types.SimpleNamespace(settingsRing=None)),
                             ("speechDictHandler", types.SimpleNamespace(loadVoiceDict=lambda synth: None))):
            previous = sys.modules.get(name)
            sys.modules[name] = module
            self.addCleanup(lambda name=name, previous=previous: sys.modules.pop(name) if previous is None
                            else sys.modules.__setitem__(name, previous))
        from mlang import hosts

        guest = hosts.create("sapi4_32")
        self.assertTrue(fb.owns_its_handles(guest.conn))

    def test_a_connection_already_fixed_is_left_alone(self):
        pipes.install()
        conn = fb.launch()
        incoming = conn.stream.incoming
        pipes.uninstall()
        fb.install(self, synth=types.SimpleNamespace(_heldConnections=[conn]))
        pipes.install()
        self.assertEqual(conn.stream.incoming, incoming)

    def test_a_stream_of_another_class_is_left_alone(self):
        class Fixed(fb.Win32PipeStream):
            """A later NVDA's own fix: it closes its file objects."""

            def close(self):
                for pipe in self._keepalive:
                    pipe.close()

        pipes.install()
        conn = fb.launch(Fixed)
        self.assertFalse(fb.owns_its_handles(conn))

    def test_uninstall_gives_the_launcher_back_nvdas_connection(self):
        self.assertTrue(pipes.install())
        self.assertTrue(pipes.install())
        self.assertIsNot(fb.launcher.Connection, fb.Connection)
        self.assertTrue(issubclass(fb.launcher.Connection, fb.Connection))
        pipes.uninstall()
        self.assertIs(fb.launcher.Connection, fb.Connection)
        conn = fb.launch()
        self.assertFalse(fb.owns_its_handles(conn))
        forget(conn)

    def test_a_launcher_that_makes_connections_with_a_function_is_left_alone(self):
        fb.launcher.Connection = lambda *args, **kwargs: fb.Connection(*args, **kwargs)
        self.assertFalse(pipes.install())
        conn = fb.launch()
        self.assertFalse(fb.owns_its_handles(conn))
        forget(conn)


if __name__ == "__main__":
    unittest.main()
