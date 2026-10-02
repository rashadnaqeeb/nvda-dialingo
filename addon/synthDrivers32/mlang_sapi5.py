"""NVDA's 32-bit SAPI 5 as the language table hosts it. This module runs in NVDA's 32-bit synth driver host, a
process of its own, which the table's sapi5_32 guest has load it (mlang.sapi5host.Hosted32); NVDA's own sapi5_32 is
untouched. The host reports only indexes and done back to NVDA, so what the 64-bit SAPI 5 guest tells the table
directly goes back as those:

- The end of each piece's speech, found by the queue in front of the player (mlang.playqueue, as for 64-bit SAPI
  5): as an index, the piece's end marker plus SPEECH_END.
- Done, once the request's audio has played, rather than when its synthesis ends, long before that.

The table cannot reach the player in this process to drop the silence left of a piece when the voice comes back
to it after another; the driver does it itself when it is sent speech after its last speech has played, which the
table waits for before sending it a piece after another voice's. A piece sent while the last still plays keeps the
silence after it: that is the pause between two pieces of the same voice.

NVDA's own 32-bit drivers are added to the package's path, and the add-on's lib to the module path, for mlang."""
import os
import sys

import globalVars
import synthDrivers
from logHandler import log
from synthDriverHandler import synthDoneSpeaking, synthIndexReached

_nvda = os.path.join(globalVars.appDir, "_synthDrivers32")
if _nvda not in synthDrivers.__path__:
    synthDrivers.__path__.append(_nvda)
_lib = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")
if _lib not in sys.path:
    sys.path.insert(0, _lib)

# NVDA's: sapi5 first, which sets up its COM interfaces and sonic for 32 bits before it loads _sapi5.
from synthDrivers import sapi5  # noqa: E402  isort: skip
from synthDrivers import _sapi5  # noqa: E402  isort: skip

from mlang.playqueue import QueuedPlayer  # noqa: E402
from mlang.sapi5host import SPEECH_END, hosted  # noqa: E402


class _DoneOncePlayed:
    """NVDA's driver reports done when a request's synthesis ends, which with the queue comes long before its audio
    has played; this reports it once it has, as a callback in the queue. A cancel drops it with the audio, as NVDA's
    driver reports no done for a request it cancels."""

    def __init__(self, real):
        self.real = real

    def notify(self, **kwargs):
        player = getattr(kwargs.get("synth"), "player", None)
        if isinstance(player, QueuedPlayer):
            player.feed(None, 0, onDone=lambda: self.real.notify(**kwargs))
        else:
            self.real.notify(**kwargs)

    def __getattr__(self, name):
        return getattr(self.real, name)


# NVDA's driver reports done through its module's name for it, and nothing else in this process uses that module.
if not isinstance(_sapi5.synthDoneSpeaking, _DoneOncePlayed):
    _sapi5.synthDoneSpeaking = _DoneOncePlayed(synthDoneSpeaking)


class SynthDriver(hosted(sapi5.SynthDriver, log)):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.onSpeechEnded = lambda marker: synthIndexReached.notify(synth=self, index=marker + SPEECH_END)

    def speak(self, speechSequence):
        player = self.player
        if isinstance(player, QueuedPlayer):
            try:
                player.drop_silence(played_only=True)
            except Exception:
                log.debugWarning("multilanguage: the silence after SAPI 5's last speech was not dropped", exc_info=True)
        super().speak(speechSequence)
