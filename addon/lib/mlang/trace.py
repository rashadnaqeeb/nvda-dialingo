"""A timing trace of the speech path, for finding where the time goes at a change of voice: one line in NVDA's
log per event, at the info level so no change of log level is needed, each with a millisecond clock and the
thread it ran on. Diagnostic only; nothing is written under the tests, where NVDA's log is missing."""
import threading
import time

try:
    from logHandler import log

    _sink = log.info
except ImportError:
    _sink = None


def now():
    return time.perf_counter()


def ms(start):
    """Milliseconds since `start` (from now()), formatted."""
    return f"{(time.perf_counter() - start) * 1000:.1f}ms"


def name(guest):
    return getattr(guest, "name", None) or repr(guest)


def text(items, limit=40):
    """The text of a sequence, shortened, to tell utterances apart in the log."""
    joined = " ".join(i for i in items if isinstance(i, str)).strip()
    return repr(joined if len(joined) <= limit else joined[:limit] + "...")


def trace(message):
    if _sink is not None:
        _sink(f"mlang trace {time.perf_counter() * 1000:.1f} [{threading.current_thread().name}] {message}")
