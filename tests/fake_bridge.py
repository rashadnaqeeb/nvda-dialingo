"""Stand-ins for NVDA's bridge to its 32-bit synth driver host, over real pipes: rpyc's Win32PipeStream, NVDA's
Connection, its launcher module, and synthDriverHandler.getSynth, installed for the length of a test."""
import ctypes
import msvcrt
import os
import sys
import types
from ctypes import wintypes

import nvda_stub  # noqa: F401

from mlang import pipes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)


class Win32PipeStream:
    """rpyc's: it closes the raw handles of the file objects it was made from."""

    def __init__(self, incoming, outgoing):
        self._keepalive = (incoming, outgoing)
        self.incoming = msvcrt.get_osfhandle(incoming.fileno())
        self.outgoing = msvcrt.get_osfhandle(outgoing.fileno())

    def close(self):
        for handle in (self.incoming, self.outgoing):
            if not kernel32.CloseHandle(handle):
                raise OSError(f"handle {handle} was closed already")


class Connection:
    """NVDA's: closing it closes its stream."""

    def __init__(self, stream, localService=None, name="unknown"):
        self._conn = types.SimpleNamespace(_channel=types.SimpleNamespace(stream=stream))
        self.stream = stream
        self._closed = False

    @property
    def closed(self):
        return self._closed

    def close(self):
        if not self._closed:
            self._closed = True
            self.stream.close()


launcher = types.ModuleType("_bridge.clients.synthDriverHost32.launcher")
launcher.Connection = Connection
made = []


def stream(cls=Win32PipeStream):
    r, w = os.pipe()
    return cls(open(r, "rb"), open(w, "wb"))


def launch(cls=Win32PipeStream):
    """A connection to a new host, as the launcher makes it."""
    conn = launcher.Connection(stream(cls), None, name="synthDriverHost32")
    made.append(conn)
    return conn


def close_all():
    """What the test left open, each handle once: the connections, then the file objects, which raise if theirs
    was closed by the stream. Everything is closed before the first error is raised."""
    conns = list(made)
    made.clear()
    errors = []
    for conn in conns:
        for close in (conn.close, *(pipe.close for pipe in conn.stream._keepalive)):
            try:
                close()
            except Exception as e:
                errors.append(e)
    if errors:
        raise errors[0]


def install(test, synth=None):
    """The fake modules, for the length of `test`; `synth` is the current synthesizer."""
    modules = {
        "_bridge": types.ModuleType("_bridge"),
        "_bridge.clients": types.ModuleType("_bridge.clients"),
        "_bridge.clients.synthDriverHost32": types.ModuleType("_bridge.clients.synthDriverHost32"),
        launcher.__name__: launcher,
        "rpyc": types.ModuleType("rpyc"),
        "rpyc.core": types.ModuleType("rpyc.core"),
        "rpyc.core.stream": types.ModuleType("rpyc.core.stream"),
        "synthDriverHandler": types.ModuleType("synthDriverHandler"),
    }
    modules["_bridge.clients.synthDriverHost32"].launcher = launcher
    modules["rpyc.core.stream"].Win32PipeStream = Win32PipeStream
    modules["synthDriverHandler"].getSynth = lambda: synth
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)

    def restore():
        try:
            close_all()
        finally:
            pipes.uninstall()
            launcher.Connection = Connection
            for name, module in previous.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module

    test.addCleanup(restore)


def owns_its_handles(conn):
    """Whether a connection's stream closes handles of its own, not its file objects'."""
    s = conn.stream
    return [msvcrt.get_osfhandle(f.fileno()) for f in s._keepalive] != [s.incoming, s.outgoing]
