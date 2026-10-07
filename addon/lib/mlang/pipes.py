"""The pipes of NVDA's 32-bit synth driver host, each closed once (NVDA issue 20933).

NVDA's launcher for the host connects to it over the host process's standard input and output, through rpyc's
Win32PipeStream, made from the file objects of those pipes. The stream closes their raw handles itself, and the
file objects close the same handles again when they are collected: "Exception ignored in: <_io.BufferedReader>",
Bad file descriptor, when the handle is still free, and another handle of NVDA's closed when Windows has given its
value to something else, which can crash NVDA or leave it silent. It happens whenever a 32-bit synthesizer is shut
down: NVDA's own (sapi5_32, sapi4_32) as much as the language table's.

While the add-on runs, every connection the launcher makes is given duplicates of the pipe handles, which its
stream closes, and closes the originals, through their file objects, when it is closed itself: each handle once.
It is installed by the global plugin, and by the language table before it makes a guest, which at NVDA's start
comes first. A connection made before either (NVDA started on a 32-bit synthesizer) is given the same then. Nothing is done unless NVDA works as described: if a later NVDA has its own fix, a stream of
another class, this does nothing. NVDA is imported inside the functions, so the module loads under the tests."""
import threading

# Held while the launcher's Connection is replaced, here and by sapi5host while it starts a host.
launching = threading.Lock()
_installed = []  # [the launcher module, its Connection before install, the subclass put in its place]


def install(log=None):
    """Have the launcher make connections that close each pipe handle once, and fix the current synthesizer's.
    Whether it is in place."""
    with launching:
        if _installed:
            return True
        try:
            from _bridge.clients.synthDriverHost32 import launcher
            from rpyc.core.stream import Win32PipeStream
        except Exception:
            if log:
                log.debugWarning("dialingo: NVDA's 32-bit synth driver host was not found; its pipes are left "
                                 "as they are", exc_info=True)
            return False
        real = launcher.Connection
        if not isinstance(real, type):
            if log:
                log.debugWarning(f"dialingo: NVDA's 32-bit launcher makes connections with {real!r}, not a "
                                 "class; its pipes are left as they are")
            return False

        class Connection(real):
            def __init__(self, stream, *args, **kwargs):
                pipes = own_handles(stream, Win32PipeStream, log)
                super().__init__(stream, *args, **kwargs)
                self._mlangPipes = pipes

            def close(self):
                try:
                    super().close()
                finally:
                    close_pipes(self.__dict__.pop("_mlangPipes", ()), log)

        Connection.__name__ = Connection.__qualname__ = real.__name__
        launcher.Connection = Connection
        _installed[:] = [launcher, real, Connection]
    _fix_current(Connection, Win32PipeStream, log)
    return True


def uninstall():
    """Let the launcher make NVDA's own connections again. Those made meanwhile keep closing their pipes once."""
    with launching:
        if not _installed:
            return
        launcher, real, ours = _installed
        if launcher.Connection is ours:
            launcher.Connection = real
        _installed.clear()


def _fix_current(Connection, Win32PipeStream, log=None):
    """The connections of the current synthesizer, when it is a 32-bit one made before install."""
    try:
        import synthDriverHandler

        synth = synthDriverHandler.getSynth()
    except Exception:
        return
    for conn in list(getattr(synth, "_heldConnections", ())):
        try:
            if not isinstance(conn, Connection.__mro__[1]) or isinstance(conn, Connection) or conn.closed:
                continue
            stream = conn._conn._channel.stream
            pipes = own_handles(stream, Win32PipeStream, log)
            if pipes:
                conn.__class__ = Connection
                conn._mlangPipes = pipes
        except Exception:
            if log:
                log.debugWarning("dialingo: the pipes of the current 32-bit synthesizer were left as they are",
                                 exc_info=True)


def own_handles(stream, Win32PipeStream, log=None):
    """Give a Win32PipeStream made from two file objects, and still closing their own handles, duplicates of those
    handles. Those file objects, for the caller to close once the stream is closed; nothing when the stream is not
    such a one, or the handles could not be duplicated (the stream is then as it was)."""
    if type(stream).close is not Win32PipeStream.close:
        return []
    files = getattr(stream, "_keepalive", None)
    handles = [getattr(stream, name, None) for name in ("incoming", "outgoing")]
    if not isinstance(files, tuple) or len(files) != 2 or not all(isinstance(h, int) for h in handles):
        return []
    import ctypes
    import msvcrt
    from ctypes import wintypes

    try:
        if [msvcrt.get_osfhandle(f.fileno()) for f in files] != handles:
            return []
    except Exception:
        return []
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.DuplicateHandle.argtypes = (wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
                                         ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    process = kernel32.GetCurrentProcess()
    copies = []
    for handle in handles:
        copy = wintypes.HANDLE()
        if not kernel32.DuplicateHandle(process, handle, process, ctypes.byref(copy), 0, False, 2):  # SAME_ACCESS
            for made in copies:
                kernel32.CloseHandle(made)
            if log:
                log.debugWarning(f"dialingo: a pipe to a 32-bit synth driver host was not duplicated: "
                                 f"{ctypes.WinError(ctypes.get_last_error())}")
            return []
        copies.append(copy.value)
    stream.incoming, stream.outgoing = copies
    return list(files)


def close_pipes(pipes, log=None):
    for pipe in pipes:
        try:
            pipe.close()
        except Exception:
            if log:
                log.debugWarning("dialingo: a pipe to a 32-bit synth driver host was not closed", exc_info=True)
