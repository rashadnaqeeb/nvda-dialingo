"""A clock of what a guest feeds NVDA's audio player: how long the audio fed so far still has to play.

For a guest that reports done before its audio has played and never tells when it has: Eloquence C with its pauses
shortened, which reports once its last feed has returned, with up to the player's buffer (0.4 seconds) still to
play. The player cannot be asked. It keeps its list of pending callbacks without a lock, for the one thread that
feeds it: a sync from another thread walks that list while the guest's next feed changes it, and NVDA crashes
(issue 13: the second character spelled, typed, or moved over). Its callbacks run only inside a feed, sync, or
idle, so one would wait for the guest's next piece. So nothing of the player is called here: its feed, idle,
stop, and pause are followed as the guest calls them, on the guest's own threads, and the rest is arithmetic.

Audio plays in the order fed, at its own pace, starting when it is fed if the player had run dry by then. An idle
returns once everything has played, a stop drops what is left, and a pause holds it. Measured in real NVDA against
a sync on Eloquence C's player with nothing else fed to it, the clock ran out 2 to 33 ms before the sync returned,
mostly 10 to 16: the player's own position trails what it is fed by about a period of the audio device, which the
next guest's audio trails as well. The silence the player trims from the start of the first chunk after a stop or
an idle is counted as if it played, which puts the end that much later; Eloquence C starts with 0 to 4 ms of it.
Pure Python, so the tests cover it with a fake player."""

import threading
import time
import weakref

ATTRIBUTE = "_dialingoPlayClock"
_watching = threading.Lock()


class PlayClock:
	def __init__(self, bytes_per_second, playing=0.0, now=time.monotonic):
		"""`playing`: seconds of audio the player is taken to hold already, when it was fed before the clock was
		there to see it."""
		self.rate = bytes_per_second
		self.now = now
		self.lock = threading.Lock()
		self.end = now() + playing  # when what was fed so far will have played
		self.frozen = None  # while paused: the seconds left to play

	def fed(self, size, at):
		"""A feed of `size` bytes, made at `at`, has returned: its audio follows what was fed before it, or
		started at `at` if that had played by then."""
		seconds = size / self.rate
		with self.lock:
			if self.frozen is not None:
				self.frozen += seconds
			else:
				self.end = max(self.end, at) + seconds

	def emptied(self):
		"""Everything fed has played (an idle returned), or was dropped (a stop, which ends a pause too)."""
		with self.lock:
			self.end = 0.0
			self.frozen = None

	def paused(self, switch):
		with self.lock:
			if switch:
				if self.frozen is None:
					self.frozen = max(0.0, self.end - self.now())
			elif self.frozen is not None:
				self.end = self.now() + self.frozen
				self.frozen = None

	def left(self):
		"""Seconds until what was fed so far has played; 0 once it has."""
		with self.lock:
			if self.frozen is not None:
				return self.frozen
			return max(0.0, self.end - self.now())


def watched(player):
	"""The clock put on a player by `watch`, or None."""
	return getattr(player, ATTRIBUTE, None)


def watch(player, playing=0.0, warn=None, now=time.monotonic):
	"""The clock of a player, put on it on first use: its feed, idle, stop, and pause then tell the clock, and do
	what they did. They are replaced on the instance, which the guest calls them on, and reach the player's own
	through its class and a weak reference: a player holding its own bound methods would be freed only by the
	garbage collector, which NVDA reports as an error. `playing`: see PlayClock; only for a player not watched yet.
	`warn(message)`: told once if the clock cannot follow a call. Raises if the player does not give its format."""
	with _watching:
		clock = watched(player)
		if clock is not None:
			return clock
		rate = player.samplesPerSec * player.channels * (player.bitsPerSample // 8)
		if rate <= 0:
			raise ValueError("the player gives no audio format")
		clock = PlayClock(rate, playing, now)
		ref = weakref.ref(player)
		failed = []

		def tell(report, *args):
			# Never a failure of the guest's own call: the clock is then wrong, which costs a seam, not speech.
			try:
				report(*args)
			except Exception as e:
				if warn is not None and not failed:
					failed.append(e)
					warn(f"the clock of a guest's audio player could not follow it: {e!r}")

		def size_of(data, args, kwargs):
			size = args[0] if args else kwargs.get("size")
			if size is None:
				size = len(data) if data is not None else 0
			return size

		def feed(data, *args, **kwargs):
			own = ref()
			at = now()
			try:
				return type(own).feed(own, data, *args, **kwargs)
			finally:
				tell(lambda: clock.fed(size_of(data, args, kwargs), at))

		def idle(*args, **kwargs):
			own = ref()
			result = type(own).idle(own, *args, **kwargs)
			tell(clock.emptied)
			return result

		def stop(*args, **kwargs):
			own = ref()
			try:
				return type(own).stop(own, *args, **kwargs)
			finally:
				tell(clock.emptied)

		def pause(switch, *args, **kwargs):
			own = ref()
			try:
				return type(own).pause(own, switch, *args, **kwargs)
			finally:
				tell(clock.paused, switch)

		for name, method in (("feed", feed), ("idle", idle), ("stop", stop), ("pause", pause)):
			if not callable(getattr(type(player), name, None)):
				raise AttributeError(f"the player has no {name}")
		player.feed = feed
		player.idle = idle
		player.stop = stop
		player.pause = pause
		setattr(player, ATTRIBUTE, clock)
		return clock
