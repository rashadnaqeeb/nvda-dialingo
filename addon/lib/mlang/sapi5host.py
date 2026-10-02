"""NVDA's SAPI 5 driver as a guest of the language table: a subclass that puts a queue in front of its audio player
(playqueue), and reports when the speech of each piece has played (onSpeechEnded, with the piece's end marker).
Only the language table's instances are made from it; NVDA's own driver is untouched.

With the queue, SAPI 5 ends a request long before its audio has played. NVDA's driver reports, at the end of a
request, every bookmark of it not reported yet, which would now be before their audio has played; the subclass
reports them instead once the request's audio has played, after each one's own report from the player.

It relies on how NVDA 2026 builds the driver: its audio goes through `player`, made in `_initWasapiAudio`, its
speaking thread appends each request's bookmarks to `_bookmarkLists` as it starts it, and calls `_onEndStream`
once the request's audio is all written. When any of that is missing, the driver is hosted as it is, with its
done freeing it as before. NVDA is imported inside the functions, so the module loads under the tests."""
import os
import threading
from collections import deque

from .playqueue import QueuedPlayer

_classes = {}


class _Requests(deque):
    """The driver's list of bookmark lists, one per request; `current` is a copy of the bookmarks of the request its
    speaking thread started last, taken before any of them is reported. Its last is the end marker of the piece."""

    current = ()

    def append(self, bookmarks):
        self.current = tuple(bookmarks)
        super().append(bookmarks)

    def clear(self):
        self.current = ()
        super().clear()


def _usable(cls):
    import sys

    module = sys.modules.get("synthDrivers.sapi5")
    if module is None or not isinstance(cls, type) or not issubclass(cls, module.SynthDriver):
        return False
    return all(callable(getattr(cls, name, None)) for name in ("_initWasapiAudio", "_onEndStream", "_speakThread"))


def hosted(cls, log=None):
    """`cls`, or for a driver built on NVDA's SAPI 5 one (the Microsoft Speech Platform's too), its hosted subclass."""
    if cls in _classes:
        return _classes[cls]
    result = cls
    if _usable(cls):

        class Hosted(cls):
            onSpeechEnded = None  # set by the language table: called with the end marker of a piece

            def __init__(self, *args, **kwargs):
                # Before NVDA's init, which makes the first player.
                self._mlangHoldLock = threading.Lock()
                self._mlangHeld = False
                super().__init__(*args, **kwargs)
                if isinstance(self._bookmarkLists, deque) and not self._bookmarkLists:
                    self._bookmarkLists = _Requests()

            def _initWasapiAudio(self):
                with self._mlangHoldLock:
                    super()._initWasapiAudio()
                    if self.player is not None:
                        self.player = QueuedPlayer(self.player, log.debugWarning if log else None)
                        if self._mlangHeld:
                            # A change of voice while holding a piece sent ahead: the new player holds it too.
                            self.player.hold()

            def mlangHold(self, held):
                """Hold what is sent to the player (QueuedPlayer.hold), or let it play: a state of the instance,
                which a new player made for a change of voice keeps."""
                with self._mlangHoldLock:
                    self._mlangHeld = held
                    player = self.player
                    if isinstance(player, QueuedPlayer):
                        if held:
                            player.hold()
                        else:
                            player.unhold()

            def _initTts(self, *args, **kwargs):
                """A change of voice makes a new engine and player, stopping the old player with the reports of
                what it was still to play (the end of speech, NVDA's indexes, done), which NVDA's own driver
                would have made by then. They are made once the new player is in place."""
                old = getattr(self, "player", None)
                if not isinstance(old, QueuedPlayer):
                    return super()._initTts(*args, **kwargs)
                old.salvage()
                try:
                    super()._initTts(*args, **kwargs)
                finally:
                    for call in old.salvaged():
                        try:
                            call()
                        except Exception:
                            if log:
                                log.debugWarning("multilanguage: a report of SAPI 5's failed", exc_info=True)

            def _onEndStream(self):
                player = self.player
                lists = self._bookmarkLists
                if not isinstance(player, QueuedPlayer) or not isinstance(lists, _Requests):
                    return super()._onEndStream()
                bookmarks = lists.current
                if lists:
                    # Reported once played, below: NVDA would report them now.
                    lists[-1].clear()
                try:
                    callback = self.onSpeechEnded
                    if callback is not None and bookmarks:
                        player.mark_speech_end(lambda marker=bookmarks[-1]: callback(marker))
                    if bookmarks:
                        player.feed(None, 0, onDone=lambda: self._reportPlayed(bookmarks))
                except Exception:
                    if log:
                        log.debugWarning("multilanguage: could not mark the end of SAPI 5's speech", exc_info=True)
                super()._onEndStream()

            def _reportPlayed(self, bookmarks):
                """The request's audio has played: its bookmarks are reached, whether or not the player reported
                them; the language table ignores one reported twice."""
                from synthDriverHandler import synthIndexReached

                for index in bookmarks:
                    synthIndexReached.notify(synth=self, index=index)

        Hosted.__name__ = Hosted.__qualname__ = cls.__name__
        result = Hosted
    elif _usable32(cls):

        class Hosted32(cls):
            """NVDA's 32-bit SAPI 5 runs in a process of its own, NVDA's 32-bit synth driver host, which reports
            only indexes and done back. This proxy has the host load the add-on's driver (DRIVER32) instead of
            NVDA's: NVDA's, hosted there as above, which reports the end of each piece's speech as its end marker
            plus SPEECH_END, and its done once the request's audio has played. When it cannot load, NVDA's own
            driver is loaded, as without the add-on."""

            synthDriver32Path = DRIVERS32
            synthDriver32Name = DRIVER32
            speechEndOffset = SPEECH_END

            def __init__(self, *args, **kwargs):
                try:
                    super().__init__(*args, **kwargs)
                except Exception:
                    if log:
                        log.debugWarning("multilanguage: the 32-bit SAPI 5 of the language table did not load; "
                                         "NVDA's is used", exc_info=True)
                    self.synthDriver32Path = cls.synthDriver32Path
                    self.synthDriver32Name = cls.synthDriver32Name
                    self.speechEndOffset = None
                    super().__init__(*args, **kwargs)

        Hosted32.__name__ = Hosted32.__qualname__ = cls.__name__
        result = Hosted32
    _classes[cls] = result
    return result


# The end of a piece's speech, from the language table's 32-bit SAPI 5: its end marker plus this. The scheduler's
# markers stay far below it.
SPEECH_END = 1_000_000
# The folder of the add-on's 32-bit drivers, and the one NVDA's 32-bit synth driver host loads for the table.
DRIVERS32 = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "synthDrivers32")
DRIVER32 = "mlang_sapi5"


def _usable32(cls):
    """NVDA's 32-bit SAPI 5 proxy, with the add-on's driver for the host in place."""
    return (isinstance(cls, type) and getattr(cls, "name", None) == "sapi5_32"
            and getattr(cls, "synthDriver32Name", None) == "sapi5" and hasattr(cls, "synthDriver32Path")
            and os.path.isfile(os.path.join(DRIVERS32, DRIVER32 + ".py")))
