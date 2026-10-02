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
                super().__init__(*args, **kwargs)
                if isinstance(self._bookmarkLists, deque) and not self._bookmarkLists:
                    self._bookmarkLists = _Requests()

            def _initWasapiAudio(self):
                super()._initWasapiAudio()
                if self.player is not None:
                    self.player = QueuedPlayer(self.player, log.debugWarning if log else None)

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
    _classes[cls] = result
    return result
