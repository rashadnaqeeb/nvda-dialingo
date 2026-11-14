"""The clock of what a guest feeds its player: how long its audio still has to play, against a fake player."""

import gc
import unittest
import weakref

import nvda_stub  # noqa: F401

from mlang.playclock import PlayClock, watch, watched

RATE = 1000  # samples per second, mono 16-bit: 2000 bytes a second
SECOND = bytes(2000)


class Now:
	def __init__(self, at=100.0):
		self.at = at

	def __call__(self):
		return self.at


class FakePlayer:
	channels = 1
	bitsPerSample = 16
	samplesPerSec = RATE

	def __init__(self, now=None):
		self.calls = []
		self.now = now
		self.blocks = 0.0  # how long a feed waits for room in the player

	def feed(self, data, size=None, onDone=None):
		self.calls.append(("feed", data, size, onDone))
		if self.now is not None:
			self.now.at += self.blocks
		return "fed"

	def idle(self):
		self.calls.append(("idle",))
		return "idled"

	def stop(self):
		self.calls.append(("stop",))
		return "stopped"

	def pause(self, switch):
		self.calls.append(("pause", switch))
		return "paused"

	def close(self):
		self.stop()


class ClockTest(unittest.TestCase):
	def setUp(self):
		self.now = Now()
		self.clock = PlayClock(2000, now=self.now)

	def test_nothing_fed_has_nothing_left(self):
		self.assertEqual(self.clock.left(), 0)

	def test_audio_plays_from_when_it_is_fed(self):
		self.clock.fed(2000, self.now.at)
		self.assertAlmostEqual(self.clock.left(), 1.0)
		self.now.at += 0.4
		self.assertAlmostEqual(self.clock.left(), 0.6)
		self.now.at += 1
		self.assertEqual(self.clock.left(), 0)

	def test_a_feed_follows_the_audio_ahead_of_it(self):
		self.clock.fed(1000, self.now.at)
		self.now.at += 0.1
		self.clock.fed(1000, self.now.at)
		self.assertAlmostEqual(self.clock.left(), 0.9)

	def test_a_feed_after_the_player_ran_dry_starts_when_it_is_made(self):
		self.clock.fed(1000, self.now.at)
		self.now.at += 2
		self.clock.fed(1000, self.now.at)
		self.assertAlmostEqual(self.clock.left(), 0.5)

	def test_a_feed_that_waited_for_room_is_counted_from_its_call(self):
		at = self.now.at
		self.now.at += 0.3  # the feed returned this much later
		self.clock.fed(2000, at)
		self.assertAlmostEqual(self.clock.left(), 0.7)

	def test_emptied_leaves_nothing(self):
		self.clock.fed(2000, self.now.at)
		self.clock.emptied()
		self.assertEqual(self.clock.left(), 0)

	def test_a_pause_holds_what_is_left(self):
		self.clock.fed(2000, self.now.at)
		self.now.at += 0.25
		self.clock.paused(True)
		self.now.at += 10
		self.assertAlmostEqual(self.clock.left(), 0.75)
		self.clock.paused(True)  # twice changes nothing
		self.clock.fed(1000, self.now.at)  # fed while paused: behind what is held
		self.assertAlmostEqual(self.clock.left(), 1.25)
		self.clock.paused(False)
		self.assertAlmostEqual(self.clock.left(), 1.25)
		self.now.at += 1
		self.assertAlmostEqual(self.clock.left(), 0.25)

	def test_a_resume_without_a_pause_changes_nothing(self):
		self.clock.fed(2000, self.now.at)
		self.clock.paused(False)
		self.assertAlmostEqual(self.clock.left(), 1.0)

	def test_a_stop_ends_a_pause(self):
		self.clock.fed(2000, self.now.at)
		self.clock.paused(True)
		self.clock.emptied()
		self.assertEqual(self.clock.left(), 0)
		self.clock.fed(2000, self.now.at)
		self.now.at += 0.5
		self.assertAlmostEqual(self.clock.left(), 0.5)

	def test_a_player_fed_before_the_clock_is_taken_to_hold_audio(self):
		clock = PlayClock(2000, playing=0.45, now=self.now)
		self.assertAlmostEqual(clock.left(), 0.45)
		clock.fed(1000, self.now.at)
		self.assertAlmostEqual(clock.left(), 0.95)


class WatchTest(unittest.TestCase):
	def setUp(self):
		self.now = Now()
		self.player = FakePlayer(self.now)
		self.clock = watch(self.player, now=self.now)

	def test_the_player_still_gets_its_calls_and_gives_its_results(self):
		done = object()
		self.assertEqual(self.player.feed(SECOND, onDone=done), "fed")
		self.assertEqual(self.player.feed(SECOND, 500, done), "fed")
		self.assertEqual(self.player.pause(True), "paused")
		self.assertEqual(self.player.pause(False), "paused")
		self.assertEqual(self.player.idle(), "idled")
		self.assertEqual(self.player.stop(), "stopped")
		self.assertEqual(
			self.player.calls,
			[
				("feed", SECOND, None, done),
				("feed", SECOND, 500, done),
				("pause", True),
				("pause", False),
				("idle",),
				("stop",),
			],
		)

	def test_a_feed_counts_its_bytes_or_its_size(self):
		self.player.feed(SECOND)
		self.assertAlmostEqual(self.clock.left(), 1.0)
		self.player.feed(SECOND, 500)
		self.assertAlmostEqual(self.clock.left(), 1.25)
		self.player.feed(SECOND, size=500, onDone=None)
		self.assertAlmostEqual(self.clock.left(), 1.5)

	def test_a_feed_of_a_callback_alone_adds_nothing(self):
		self.player.feed(SECOND)
		self.player.feed(None, 0, onDone=lambda: None)
		self.assertAlmostEqual(self.clock.left(), 1.0)

	def test_a_feed_that_waited_in_the_player_is_counted_from_its_call(self):
		self.player.blocks = 0.3
		self.player.feed(SECOND)
		self.assertAlmostEqual(self.clock.left(), 0.7)

	def test_idle_and_stop_empty_it(self):
		self.player.feed(SECOND)
		self.player.idle()
		self.assertEqual(self.clock.left(), 0)
		self.player.feed(SECOND)
		self.player.stop()
		self.assertEqual(self.clock.left(), 0)

	def test_close_which_stops_empties_it(self):
		self.player.feed(SECOND)
		self.player.close()
		self.assertEqual(self.clock.left(), 0)
		self.assertEqual(self.player.calls[-1], ("stop",))

	def test_pause_holds_it(self):
		self.player.feed(SECOND)
		self.player.pause(True)
		self.now.at += 5
		self.assertAlmostEqual(self.clock.left(), 1.0)
		self.player.pause(False)
		self.now.at += 0.5
		self.assertAlmostEqual(self.clock.left(), 0.5)

	def test_watched_again_it_keeps_its_clock_and_is_followed_once(self):
		self.assertIs(watch(self.player, playing=5, now=self.now), self.clock)
		self.assertIs(watched(self.player), self.clock)
		self.player.feed(SECOND)
		self.assertEqual(len(self.player.calls), 1)
		self.assertAlmostEqual(self.clock.left(), 1.0)

	def test_a_player_never_watched_has_no_clock(self):
		self.assertIsNone(watched(FakePlayer()))

	def test_a_new_player_may_be_taken_to_hold_audio(self):
		clock = watch(FakePlayer(self.now), playing=0.45, now=self.now)
		self.assertAlmostEqual(clock.left(), 0.45)

	def test_a_call_made_through_the_class_later_is_the_one_reached(self):
		"""The player's own methods are looked up when called, so one replaced on its class since is used."""
		seen = []

		class Player(FakePlayer):
			pass

		player = Player(self.now)
		watch(player, now=self.now)
		Player.feed = lambda self, data, size=None, onDone=None: seen.append(data)
		player.feed(SECOND)
		self.assertEqual(seen, [SECOND])

	def test_a_feed_the_clock_cannot_count_still_reaches_the_player_and_is_reported_once(self):
		warnings = []
		player = FakePlayer(self.now)
		clock = watch(player, warn=warnings.append, now=self.now)
		unsized = object()
		self.assertEqual(player.feed(unsized), "fed")
		self.assertEqual(player.feed(unsized), "fed")
		self.assertEqual([c[1] for c in player.calls], [unsized, unsized])
		self.assertEqual(len(warnings), 1)
		self.assertEqual(clock.left(), 0)

	def test_a_failing_feed_is_still_counted_and_raises(self):
		class Failing(FakePlayer):
			def feed(self, data, size=None, onDone=None):
				raise OSError("no device")

		player = Failing(self.now)
		clock = watch(player, now=self.now)
		with self.assertRaises(OSError):
			player.feed(SECOND)
		self.assertAlmostEqual(clock.left(), 1.0)

	def test_a_player_without_a_format_is_refused_and_left_alone(self):
		class Bare:
			def feed(self, data, size=None, onDone=None):
				pass

		player = Bare()
		with self.assertRaises(AttributeError):
			watch(player)
		self.assertIsNone(watched(player))
		self.assertNotIn("feed", vars(player))

	def test_a_player_without_one_of_the_calls_is_refused_and_left_alone(self):
		class NoPause:
			channels = 1
			bitsPerSample = 16
			samplesPerSec = RATE

			def feed(self, data, size=None, onDone=None):
				pass

			def idle(self):
				pass

			def stop(self):
				pass

		player = NoPause()
		with self.assertRaises(AttributeError):
			watch(player)
		self.assertIsNone(watched(player))
		self.assertEqual(vars(player), {})

	def test_a_watched_player_is_freed_without_the_garbage_collector(self):
		"""NVDA reports a player that only the garbage collector could free."""
		gc.disable()
		try:
			player = FakePlayer()
			watch(player)
			ref = weakref.ref(player)
			del player
			self.assertIsNone(ref())
		finally:
			gc.enable()


if __name__ == "__main__":
	unittest.main()
