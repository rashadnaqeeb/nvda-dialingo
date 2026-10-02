"""The queue in front of SAPI 5's player: the end of speech, stops, and idling, against a fake player."""
import threading
import time
import unittest
from array import array

import nvda_stub  # noqa: F401

from mlang.playqueue import MARGIN, QueuedPlayer, last_loud
from mlang.sapi5host import _Requests

RATE = 1000  # samples per second, mono 16-bit: 2000 bytes a second, a 10-byte window, a 100-byte margin


def audio(*runs):
    """16-bit mono audio from (sample value, sample count) runs."""
    samples = array("h")
    for value, count in runs:
        samples.extend([value] * count)
    return samples.tobytes()


class FakePlayer:
    channels = 1
    bitsPerSample = 16
    samplesPerSec = RATE

    def __init__(self):
        self.calls = []
        self.open = threading.Event()
        self.open.set()
        self.entered = threading.Event()  # set when a feed is in the player
        self.lock = threading.Lock()

    def feed(self, data, size=None, onDone=None):
        self.entered.set()
        self.open.wait(5)
        with self.lock:
            self.calls.append(("feed", data, onDone))

    def idle(self):
        with self.lock:
            self.calls.append(("idle",))

    def sync(self):
        pass

    def stop(self):
        with self.lock:
            self.calls.append(("stop",))
        self.open.set()

    def pause(self, switch):
        pass

    def close(self):
        pass


def settle(q):
    """Wait until the queue's thread has handed everything to the player."""
    for _ in range(500):
        with q.cond:
            empty = not q.queue
        if empty and q.feeding.acquire(blocking=False):
            q.feeding.release()
            return
        time.sleep(0.002)
    raise AssertionError("the queue did not drain")


class LastLoudTests(unittest.TestCase):
    def test_silence_has_none(self):
        self.assertIsNone(last_loud(audio((0, 100), (20, 50), (-20, 50)), 2, 10))

    def test_a_quiet_final_consonant_is_speech(self):
        # A vowel, then a "th" peaking at 250 for 100 ms: the end of speech is after it.
        self.assertEqual(last_loud(audio((8000, 100), (250, 100), (0, 200)), 2, 10), 400)

    def test_offset_is_after_the_last_loud_window(self):
        self.assertEqual(last_loud(audio((2000, 40), (0, 60)), 2, 10), 80)

    def test_negative_samples_are_loud(self):
        self.assertEqual(last_loud(audio((0, 10), (-2000, 10), (0, 80)), 2, 10), 40)


class QueuedPlayerTests(unittest.TestCase):
    def setUp(self):
        self.player = FakePlayer()
        self.q = QueuedPlayer(self.player)
        self.ended = []

    def tearDown(self):
        self.player.open.set()
        self.q.close()

    def fed(self):
        """The player's feeds as ("audio", bytes) and ("mark", callback) items, in order."""
        out = []
        for call in self.player.calls:
            if call[0] == "feed":
                out.append(("audio", call[1]) if call[1] else ("mark", call[2]))
            else:
                out.append(call)
        return out

    def kinds(self):
        return [k for k, *_ in self.fed()]

    def play(self, n):
        """Call the callback of the player's nth mark, as the player does once the audio before it has played."""
        marks = [call[1] for call in self.fed() if call[0] == "mark"]
        marks[n]()

    def test_a_probe_follows_the_last_loud_sound_of_a_chunk(self):
        speech = audio((2000, 100), (0, 400))
        self.q.feed(speech)
        settle(self.q)
        fed = self.fed()
        self.assertEqual(self.kinds(), ["audio", "mark", "audio"])
        self.assertEqual(len(fed[0][1]), 200 + int(2 * RATE * MARGIN))
        self.assertEqual(fed[0][1] + fed[2][1], speech)
        self.q.mark_speech_end(lambda: self.ended.append(1))
        self.assertEqual(self.ended, [])
        self.play(0)
        self.assertEqual(self.ended, [1])

    def test_a_probe_played_already_ends_the_speech_at_once(self):
        self.q.feed(audio((2000, 100), (0, 400)))
        settle(self.q)
        self.play(0)
        self.q.mark_speech_end(lambda: self.ended.append(1))
        self.assertEqual(self.ended, [1])

    def test_the_margin_is_carried_into_the_next_quiet_chunk(self):
        self.q.feed(audio((2000, 100), (0, 10)))  # 220 bytes: the margin runs 20 past it
        self.q.feed(audio((0, 500)))
        self.q.mark_speech_end(lambda: self.ended.append(1))
        settle(self.q)
        fed = self.fed()
        self.assertEqual(self.kinds(), ["audio", "mark", "audio", "mark", "audio"])
        self.assertEqual([len(fed[i][1]) for i in (0, 2, 4)], [220, 20, 980])
        self.play(0)
        self.assertEqual(self.ended, [])
        self.play(1)
        self.assertEqual(self.ended, [1])

    def test_no_speech_ends_after_everything(self):
        self.q.feed(audio((0, 10)))
        self.q.feed(audio((20, 300)))
        self.q.mark_speech_end(lambda: self.ended.append(1))
        settle(self.q)
        self.assertEqual(self.kinds(), ["audio", "audio", "mark"])
        self.play(0)
        self.assertEqual(self.ended, [1])

    def test_each_end_takes_only_the_speech_fed_since_the_last(self):
        self.q.feed(audio((2000, 50)))
        self.q.mark_speech_end(lambda: None)
        self.q.feed(audio((0, 500)))
        self.q.mark_speech_end(lambda: self.ended.append(2))
        settle(self.q)
        self.assertEqual(self.kinds(), ["audio", "mark", "audio", "mark"])
        self.play(0)
        self.assertEqual(self.ended, [])
        self.play(1)
        self.assertEqual(self.ended, [2])

    def test_drop_silence_drops_only_the_queued_silence_after_speech(self):
        self.player.open.clear()
        self.q.feed(audio((0, 10)))
        self.assertTrue(self.player.entered.wait(1))
        self.q.feed(audio((2000, 100)))
        self.q.feed(audio((0, 300)))
        self.q.feed(audio((0, 300)))
        self.q.mark_speech_end(lambda: None)
        self.q.feed(None, 0, onDone=lambda: None)
        self.q.drop_silence()
        self.q.feed(audio((2000, 20)))  # the next piece
        self.q.drop_silence()  # nothing to drop since the last end of speech
        self.player.open.set()
        settle(self.q)
        fed = self.fed()
        self.assertEqual(self.kinds(), ["audio", "audio", "mark", "audio", "mark", "mark", "audio", "mark"])
        self.assertEqual(len(fed[3][1]), int(2 * RATE * MARGIN))
        self.assertEqual(len(fed[6][1]), 40)

    def test_drop_silence_stops_the_player_when_it_was_fed_some(self):
        self.q.feed(audio((2000, 100)))
        self.q.feed(audio((0, 300)))
        self.q.mark_speech_end(lambda: None)
        settle(self.q)
        self.q.drop_silence()
        self.assertEqual(self.kinds()[-2:], ["stop", "stop"])
        self.q.drop_silence()  # once only
        self.assertEqual(self.kinds().count("stop"), 2)

    def test_drop_silence_played_only_keeps_the_pause_while_the_speech_plays(self):
        self.q.feed(audio((2000, 100)))
        self.q.feed(audio((0, 300)))
        self.q.mark_speech_end(lambda: None)
        settle(self.q)
        self.play(0)
        self.q.drop_silence(played_only=True)  # the margin, carried into the quiet chunk, is still to play
        self.assertNotIn("stop", self.kinds())
        # That pause is now ahead of the piece sent: kept, it is not stopped later, in that piece's audio.
        self.play(1)
        self.q.drop_silence(played_only=True)
        self.assertNotIn("stop", self.kinds())

    def test_drop_silence_played_only_drops_once_the_speech_has_played(self):
        self.q.feed(audio((2000, 100)))
        self.q.feed(audio((0, 300)))
        self.q.mark_speech_end(lambda: None)
        settle(self.q)
        self.play(0)
        self.play(1)  # the end of speech
        self.q.drop_silence(played_only=True)
        self.assertEqual(self.kinds().count("stop"), 2)

    def test_drop_silence_leaves_the_player_alone_when_none_was_fed(self):
        self.player.open.clear()
        self.q.feed(audio((2000, 10)))
        self.assertTrue(self.player.entered.wait(1))
        self.q.feed(audio((0, 300)))
        self.q.mark_speech_end(lambda: None)
        self.q.drop_silence()
        self.player.open.set()
        settle(self.q)
        self.assertNotIn("stop", self.kinds())

    def test_nothing_reaches_the_player_while_held(self):
        self.q.hold()
        self.q.feed(audio((2000, 100), (0, 400)))
        self.q.feed(None, 0, onDone=lambda: None)
        time.sleep(0.05)
        self.assertEqual(self.fed(), [])
        self.q.unhold()
        settle(self.q)
        self.assertEqual(self.kinds(), ["audio", "mark", "audio", "mark"])

    def test_a_stop_ends_a_hold(self):
        self.q.hold()
        self.q.feed(audio((2000, 50)))
        self.q.stop()
        self.q.feed(audio((2000, 30)))
        settle(self.q)
        self.assertEqual(self.kinds(), ["stop", "stop", "audio", "mark"])
        self.assertEqual(len(self.fed()[2][1]), 60)

    def test_stop_drops_what_is_queued(self):
        self.player.open.clear()
        self.q.feed(audio((2000, 10)))
        self.assertTrue(self.player.entered.wait(1))
        self.q.feed(audio((2000, 20)))
        self.q.feed(None, 0, onDone=lambda: None)
        self.q.stop()
        settle(self.q)
        self.assertEqual([k for k, *_ in self.fed()], ["stop", "audio", "stop"])
        self.q.feed(audio((2000, 30)))
        settle(self.q)
        self.assertEqual(self.kinds()[-2:], ["audio", "mark"])
        self.assertEqual(len(self.fed()[-2][1]), 60)

    def test_a_callback_in_the_player_is_not_called_after_a_stop(self):
        called = []
        self.q.feed(None, 0, onDone=lambda: called.append(1))
        settle(self.q)
        self.q.stop()
        self.play(0)  # were the stopped player to call it
        self.assertEqual(called, [])

    def test_callbacks_a_stop_drops_while_salvaging_are_handed_back_once_in_order(self):
        called = []
        self.q.feed(audio((2000, 100), (0, 400)))
        self.q.mark_speech_end(lambda: called.append("end"))
        self.q.feed(None, 0, onDone=lambda: called.append("reports"))
        settle(self.q)  # in the player, not played
        self.q.hold()
        self.q.feed(None, 0, onDone=lambda: called.append("done"))  # still queued
        self.q.salvage()
        self.q.stop()
        calls = self.q.salvaged()
        self.assertEqual(called, [])
        for call in calls:
            call()
        self.assertEqual(called, ["end", "reports", "done"])
        self.play(0)
        self.play(1)
        self.assertEqual(called, ["end", "reports", "done"])
        self.q.feed(None, 0, onDone=lambda: None)
        self.q.stop()
        self.assertEqual(self.q.salvaged(), [])  # salvaging ended

    def test_callbacks_drop_silence_stopped_are_not_handed_back_later(self):
        self.q.feed(audio((2000, 100)))
        self.q.feed(audio((0, 300)))
        self.q.mark_speech_end(lambda: None)
        self.q.feed(None, 0, onDone=lambda: None)
        settle(self.q)
        self.q.drop_silence()
        self.q.salvage()
        self.q.stop()
        self.assertEqual(self.q.salvaged(), [])

    def test_idle_is_skipped_when_audio_follows(self):
        self.player.open.clear()
        self.q.feed(audio((0, 10)))
        self.q.idle()
        self.q.feed(audio((0, 10)))
        self.q.idle()
        self.player.open.set()
        settle(self.q)
        self.assertEqual([k for k, *_ in self.fed()], ["audio", "audio", "idle"])

    def test_callback_feed_does_not_wait_for_a_full_queue(self):
        self.player.open.clear()
        self.q.limit = 10
        self.q.feed(audio((0, 10)))  # taken
        self.q.feed(audio((0, 10)))  # queued, at the limit
        done = threading.Event()
        threading.Thread(target=lambda: (self.q.feed(None, 0, onDone=lambda: None), done.set()), daemon=True).start()
        self.assertTrue(done.wait(1))
        self.player.open.set()


class RequestsTests(unittest.TestCase):
    def test_current_is_a_copy_of_the_bookmarks_of_the_request_started_last(self):
        r = _Requests()
        r.append([3, 5])
        bookmarks = [7, 9]
        r.append(bookmarks)
        bookmarks.clear()  # reported, as NVDA's driver removes them
        self.assertEqual(r.current, (7, 9))
        r.append([])
        self.assertEqual(r.current, ())
        r.append([9])
        r.clear()
        self.assertEqual(r.current, ())
        self.assertEqual(len(r), 0)


if __name__ == "__main__":
    unittest.main()
