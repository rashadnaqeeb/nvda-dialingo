"""A queue in front of NVDA's audio player, for a SAPI 5 guest: SAPI 5 writes into it without waiting, and a thread
of its own feeds the player. With SAPI 5 no longer held to the pace of playback, its synthesis of a piece ends
long before the piece has played, and when it ends, where its speech ended is known: the last loud sample before
the silence it ends with.

Its engine places the marks itself, and some voices (Zira) put the end of a piece half a second or more before
their speech ends, so the end marker cannot tell when the next voice may start. Its done comes when synthesis
ends, and at the pace of playback that is about a second after the speech, once the silence after it is written.

The thread hands audio to the player as soon as it can, and the player takes a second of it at once, so a callback
cannot be put into audio once the end of the piece is known: it may be with the player already. So each chunk with
speech in it is cut just after its last loud sample (plus a margin, carried into the next chunk when it is quiet),
and a probe goes in there: a callback telling that the audio up to it has played. The last probe before the end
of a piece is its end of speech. Nothing is held back from the player, so a voice slower than playback is played
as it comes.

The player's interface is kept: feed, idle, sync, stop, pause, close, and anything else is the player's own.
Callback-only feeds never wait, since some come from inside the player's callbacks. Pure Python, so the tests
cover it with a fake player."""
import ctypes
import threading
from array import array
from collections import deque

# A sample louder than this (of 32767) is speech; the silence SAPI 5 ends a stream with is below it. It is close
# to that silence, not to speech: a final consonant (the "th" of "fifth", an "s" at a low volume) peaks at 100 to
# 300 for over 100 ms, and taken as silence it would be talked over and cut (drop_silence). Measured: David's and
# Zira's silence is 0, Aria's at most 16; at 32, nothing above 40 is left after the end of speech at volumes 25 to
# 100. A voice whose silence is louder is found to end only with its audio, as without the queue.
LOUD = 32
# Speech is looked for in windows of this many seconds, from the end of each chunk.
WINDOW = 0.005
# The end of speech is put this long after the last loud window, for the fading end of the last sound. With the
# bar near the silence, the cut lands 25 to 60 ms after the last sample above 100 in the recordings measured.
MARGIN = 0.02
# Audio held in the queue at most, in seconds, before a feed waits; SAPI 5 writes far faster than this plays.
LIMIT = 30


class _Item:
    __slots__ = ("gen", "data", "onDone", "idle", "taken", "fed", "ran")

    def __init__(self, gen, data=b"", onDone=None, idle=False):
        self.gen = gen
        self.data = data
        self.onDone = onDone
        self.idle = idle
        self.taken = False  # off the queue
        self.fed = False  # handed to the player
        self.ran = False  # its onDone was called, or dropped by a stop


class _Probe:
    """A point just after speech: whether the audio up to it has played, and what to call once it has."""

    __slots__ = ("played", "callback")

    def __init__(self):
        self.played = False
        self.callback = None


def as_bytes(data, size):
    """The audio of a feed as bytes: NVDA's players take bytes, or a ctypes buffer with its size."""
    if isinstance(data, (bytes, bytearray)):
        return bytes(data if size is None else data[:size])
    try:
        return ctypes.string_at(ctypes.addressof(data), size)
    except TypeError:
        return ctypes.string_at(data, size)


def last_loud(data, block, window):
    """The byte offset just after the last loud window of 16-bit audio, or None when none is loud."""
    samples = array("h")
    samples.frombytes(data[: len(data) - len(data) % 2])
    count = len(samples)
    step = max(1, window // 2)
    end = count
    while end > 0:
        start = max(0, end - step)
        part = samples[start:end]
        if max(part) > LOUD or min(part) < -LOUD:
            offset = end * 2
            return offset - offset % block
        end = start
    return None


class QueuedPlayer:
    def __init__(self, player, log=None):
        self.player = player
        self.log = log or (lambda msg: None)
        self.block = max(1, player.channels * player.bitsPerSample // 8)
        rate = player.samplesPerSec * self.block
        self.window = max(self.block, int(rate * WINDOW) // self.block * self.block)
        self.margin = int(rate * MARGIN) // self.block * self.block
        self.limit = rate * LIMIT
        self.cond = threading.Condition()
        # Held while the thread hands an item to the player, so a stop can wait out a feed already past its check.
        self.feeding = threading.Lock()
        self.queue = deque()
        self.queued = 0  # bytes of audio in the queue
        self.gen = 0  # raised by every stop; items of an older one are dropped
        self.probe = None  # the last probe since the end of speech was last marked
        self.margin_left = 0  # bytes of the margin after that probe's speech still to come from the next chunk
        self.after = []  # the audio fed since that probe: the silence after the speech, when it is the last
        self.tail = []  # the audio fed after the last end of speech, as `after` was when it was marked
        self.holding = False  # nothing is handed to the player, audio or callback, until unhold or stop
        self.calls = deque()  # the items with a callback, in order, until it has run
        self.salvaging = None  # while the player is rebuilt (salvage): the callbacks a stop would drop
        self.closing = False
        self.thread = threading.Thread(target=self._run, name="multilanguage SAPI 5 feeder", daemon=True)
        self.thread.start()

    def __getattr__(self, name):
        return getattr(self.__dict__["player"], name)

    # ------------------------------------------------------------ the player's interface

    def feed(self, data, size=None, onDone=None):
        with self.cond:
            gen = self.gen
            if data is None or size == 0:
                self._put(_Item(gen, onDone=onDone))
                self.cond.notify_all()
                return
        audio = as_bytes(data, size)
        offset = last_loud(audio, self.block, self.window)
        with self.cond:
            while self.queued >= self.limit and self.gen == gen and not self.closing:
                self.cond.wait()
            if self.gen != gen or self.closing:
                return
            if offset is not None:
                cut = offset + self.margin
                self.margin_left = max(0, cut - len(audio))
            elif self.probe is not None and self.margin_left:
                # The margin after the last speech reaches into this quiet chunk: the end of speech moves there.
                cut = min(self.margin_left, len(audio))
                self.margin_left -= cut
            else:
                cut = None
            if cut is None:
                self._append(_Item(gen, audio, onDone))
            else:
                cut = min(cut, len(audio))
                if cut:
                    self._append(_Item(gen, audio[:cut], None if cut < len(audio) else onDone))
                probe = _Probe()
                self._put(_Item(gen, onDone=lambda: self._played(probe)))
                self.probe = probe
                self.after = []
                if cut < len(audio):
                    self._append(_Item(gen, audio[cut:], onDone))
            self.cond.notify_all()

    def _put(self, item):
        self.queue.append(item)
        if item.onDone is not None:
            while self.calls and self.calls[0].ran:
                self.calls.popleft()
            self.calls.append(item)

    def _append(self, item):
        self._put(item)
        self.queued += len(item.data)
        self.after.append(item)

    def idle(self):
        """Queued: the player idles once what is ahead of it has played, unless more audio follows by then."""
        with self.cond:
            self.queue.append(_Item(self.gen, idle=True))
            self.cond.notify_all()

    def sync(self):
        with self.cond:
            gen = self.gen
            while self.queue and self.gen == gen and not self.closing:
                self.cond.wait()
        with self.feeding:
            self.player.sync()

    def stop(self):
        with self.cond:
            self.gen += 1
            self.queue.clear()
            self.queued = 0
            self.probe = None
            self.margin_left = 0
            self.after = []
            self.tail = []
            self.holding = False
            self._drop_calls(self.calls)
            self.calls = deque()
            self.cond.notify_all()
        # The first stop ends a feed the thread is blocked in; the second, once that feed has returned, the
        # audio of one that passed its check just before the queue was dropped.
        self.player.stop()
        with self.feeding:
            self.player.stop()

    def salvage(self):
        """From now until `salvaged`, the callbacks a stop drops are kept: the player is being replaced (SAPI 5
        makes a new one to change voice), and what it cut short still counts as played, as NVDA's own driver
        reports a request's bookmarks, and done, when the request ends."""
        with self.cond:
            self.salvaging = []

    def salvaged(self):
        """The callbacks kept since `salvage`, in the order they were fed, none of them called."""
        with self.cond:
            calls, self.salvaging = self.salvaging or [], None
        return calls

    def _drop_calls(self, items):
        """Under the lock: the callbacks of `items` will not be called by the player (stopped)."""
        for item in items:
            if not item.ran:
                item.ran = True
                if self.salvaging is not None:
                    self.salvaging.append(item.onDone)

    def _call(self, item):
        """The player calls an item's callback through this, so it is called once, and not after a stop."""
        with self.cond:
            if item.ran:
                return
            item.ran = True
        item.onDone()

    def pause(self, switch):
        self.player.pause(switch)

    def hold(self):
        """Hand nothing to the player until unhold (or a stop): a piece sent ahead, while another voice still
        speaks, is synthesized and queued meanwhile. Its reports are callbacks in the queue, so they wait too."""
        with self.cond:
            self.holding = True

    def unhold(self):
        with self.cond:
            self.holding = False
            self.cond.notify_all()

    def close(self):
        self.stop()
        with self.cond:
            self.closing = True
            self.cond.notify_all()
        self.thread.join(2)
        self.player.close()

    # ------------------------------------------------------------ the end of speech

    def mark_speech_end(self, callback):
        """Call `callback` once the speech fed since the last call has played: at the last probe, at once when it
        has played already, or after everything queued when none of it was loud."""
        with self.cond:
            probe, self.probe = self.probe, None
            self.margin_left = 0
            self.tail, self.after = self.after, []
            if probe is None:
                self.tail = []
                self._put(_Item(self.gen, onDone=callback))
                self.cond.notify_all()
                return
            if not probe.played:
                probe.callback = callback
                return
        callback()

    def _played(self, probe):
        with self.cond:
            probe.played = True
            callback, probe.callback = probe.callback, None
        if callback is not None:
            callback()

    def drop_silence(self):
        """Drop the silence after the last end of speech, so the next piece does not wait for it: another voice
        has spoken since. Everything after the end of speech is quiet, or the end would be later. What of it is
        still queued is dropped, and callbacks there stay. What the player has been fed already is stopped: no
        audio of a later piece has been fed by then, so the player holds only that silence, and the callbacks
        fed after it, which are SAPI 5's late reports for the piece, all of them reported by its end of speech.
        The bytes dropped from the queue."""
        with self.cond:
            items, self.tail = self.tail, []  # held, so no other item can take one of their ids
            tail = set(map(id, items))
            if not tail:
                return 0
            kept = deque()
            dropped = 0
            for item in self.queue:
                if id(item) in tail and not item.taken:
                    dropped += len(item.data)
                else:
                    kept.append(item)
            self.queue = kept
            self.queued -= dropped
            fed = any(item.taken for item in items)
            self.cond.notify_all()
        if fed:
            # As in stop: the first ends a feed of the silence the thread is blocked in, the second the rest.
            self.player.stop()
            with self.feeding:
                with self.cond:
                    # In the player now, and dropped by the stop; the feeding lock keeps any other from going in.
                    lost = [item for item in self.calls if item.fed]
                self.player.stop()
                with self.cond:
                    self._drop_calls(lost)
        return dropped

    # ------------------------------------------------------------ the thread

    def _run(self):
        while True:
            with self.cond:
                while (not self.queue or self.holding) and not self.closing:
                    self.cond.wait()
                if self.closing:
                    return
                item = self.queue.popleft()
                item.taken = True
                self.queued -= len(item.data)
                follows = bool(self.queue)
                self.cond.notify_all()
            with self.feeding:
                if item.gen != self.gen:
                    continue
                onDone = None if item.onDone is None else (lambda item=item: self._call(item))
                item.fed = True
                try:
                    if item.idle:
                        if not follows:
                            self.player.idle()
                    elif item.data:
                        self.player.feed(item.data, onDone=onDone)
                    else:
                        self.player.feed(None, 0, onDone=onDone)
                except Exception as e:
                    self.log(f"multilanguage: feeding SAPI 5's player failed: {e!r}")
