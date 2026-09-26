"""The scheduler against fake guests: cutting, ordering across guests, index mapping, cancel, and pause."""
import unittest

import nvda_stub  # noqa: F401
from speech.commands import IndexCommand, LangChangeCommand

from mlang.scheduler import Scheduler, cut
from mlang.table import Row, Table


class FakeGuest:
    """Speaks synchronously into a log; reports its indexes when `finish` is called, like a real engine's callbacks."""

    def __init__(self, name):
        self.name = name
        self.spoken = []
        self.queued = []
        self.cancelled = 0
        self.paused = None
        self.applied = None

    def speak(self, items):
        self.spoken.append(list(items))
        self.queued.append(list(items))

    def cancel(self):
        self.cancelled += 1
        self.queued.clear()

    def pause(self, switch):
        self.paused = switch

    def finish(self, scheduler, count=None):
        """Report every index of the oldest `count` queued utterances, then done."""
        todo = self.queued[:count] if count else list(self.queued)
        del self.queued[: len(todo)]
        for items in todo:
            for item in items:
                if isinstance(item, IndexCommand):
                    scheduler.on_index(self, item.index)
        if not self.queued:
            scheduler.on_done(self)


class Harness:
    def __init__(self, table):
        self.table = table
        self.guests = {}
        self.indexes = []
        self.done = 0
        self.main = []
        self.scheduler = Scheduler(
            LangChangeCommand, IndexCommand, self.guest_for_row, self.apply_row,
            self.indexes.append, self.on_done, self.main.append, print,
        )

    def guest_for_row(self, row):
        if row.synth == "broken":
            return None
        return self.guests.setdefault(row.synth, FakeGuest(row.synth))

    def apply_row(self, guest, row):
        guest.applied = row.key()

    def on_done(self):
        self.done += 1

    def speak(self, seq):
        self.scheduler.speak(seq, self.table.row_for, self.table.row_for("en"))

    def run_main(self):
        while self.main:
            self.main.pop(0)()


def texts(items):
    return [i for i in items if isinstance(i, str)]


class CutTests(unittest.TestCase):
    def setUp(self):
        self.table = Table([Row("en", "A"), Row("fr", "B"), Row("de", "A")])
        self.default = self.table.row_for("en")

    def pieces(self, seq):
        return cut(seq, self.table.row_for, self.default, LangChangeCommand)

    def test_untagged_goes_to_default_with_commands_kept(self):
        seq = [LangChangeCommand("en"), "Hello", IndexCommand(1)]
        p = self.pieces(seq)
        self.assertEqual(len(p), 1)
        self.assertIs(p[0].row, self.default)
        self.assertEqual(p[0].items, seq)

    def test_matched_language_loses_its_commands(self):
        seq = [LangChangeCommand("en"), "Hello ", LangChangeCommand("fr"), "bonjour", LangChangeCommand("en"), "bye", IndexCommand(2)]
        p = self.pieces(seq)
        self.assertEqual([x.row.lang for x in p], ["en", "fr", "en"])
        self.assertEqual(p[1].items, ["bonjour"])
        self.assertEqual(p[2].items, [LangChangeCommand("en"), "bye", IndexCommand(2)])

    def test_unmatched_language_falls_to_default_with_command(self):
        seq = [LangChangeCommand("en"), "Hi ", LangChangeCommand("it"), "ciao", LangChangeCommand("en"), "bye"]
        p = self.pieces(seq)
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0].items, seq)

    def test_dialect_matches_base_row(self):
        seq = [LangChangeCommand("fr_CA"), "salut"]
        p = self.pieces(seq)
        self.assertEqual(p[0].row.lang, "fr")
        self.assertEqual(p[0].items, ["salut"])

    def test_trailing_commands_merge_into_previous_piece(self):
        seq = [LangChangeCommand("fr"), "bonjour", LangChangeCommand("en"), IndexCommand(5)]
        p = self.pieces(seq)
        self.assertEqual(len(p), 1)
        self.assertEqual(p[0].items, ["bonjour", IndexCommand(5)])

    def test_same_synth_different_rows_are_separate_pieces(self):
        seq = [LangChangeCommand("en"), "Hi ", LangChangeCommand("de"), "hallo"]
        p = self.pieces(seq)
        self.assertEqual([x.row.lang for x in p], ["en", "de"])


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.table = Table([Row("en", "A", rate=50), Row("fr", "B", rate=60), Row("de", "A", rate=70)])
        self.h = Harness(self.table)

    def test_single_piece_maps_indexes_and_reports_done(self):
        self.h.speak([LangChangeCommand("en"), "Hello", IndexCommand(7)])
        a = self.h.guests["A"]
        self.assertEqual(len(a.spoken), 1)
        self.assertEqual(texts(a.spoken[0]), ["Hello"])
        ours = [i.index for i in a.spoken[0] if isinstance(i, IndexCommand)]
        self.assertEqual(len(ours), 2)  # NVDA's 7 remapped, plus the marker
        a.finish(self.h.scheduler)
        self.assertEqual(self.h.indexes, [7])
        self.assertEqual(self.h.done, 1)

    def test_second_guest_waits_for_first(self):
        self.h.speak([LangChangeCommand("en"), "Hello ", LangChangeCommand("fr"), "bonjour", LangChangeCommand("en"), "bye", IndexCommand(1)])
        a = self.h.guests["A"]
        self.assertEqual(self.h.guests.get("B", FakeGuest("B")).spoken, [])
        a.finish(self.h.scheduler)
        self.h.run_main()
        b = self.h.guests["B"]
        self.assertEqual(texts(b.spoken[0]), ["bonjour"])
        self.assertEqual(b.applied, self.table.row_for("fr").key())
        self.assertEqual(len(a.spoken), 1)
        b.finish(self.h.scheduler)
        self.h.run_main()
        self.assertEqual(texts(a.spoken[1]), ["bye"])
        self.assertEqual(a.applied, self.table.row_for("en").key())
        a.finish(self.h.scheduler)
        self.assertEqual(self.h.indexes, [1])
        self.assertEqual(self.h.done, 1)

    def test_same_guest_same_row_pipelines(self):
        self.h.speak([LangChangeCommand("en"), "one", IndexCommand(1)])
        self.h.speak([LangChangeCommand("en"), "two", IndexCommand(2)])
        a = self.h.guests["A"]
        self.assertEqual(len(a.spoken), 2)
        a.finish(self.h.scheduler)
        self.assertEqual(self.h.indexes, [1, 2])
        self.assertEqual(self.h.done, 1)

    def test_same_guest_other_row_waits(self):
        self.h.speak([LangChangeCommand("en"), "one", LangChangeCommand("de"), "eins"])
        a = self.h.guests["A"]
        self.assertEqual(len(a.spoken), 1)
        a.finish(self.h.scheduler, count=1)
        self.h.run_main()
        self.assertEqual(len(a.spoken), 2)
        self.assertEqual(texts(a.spoken[1]), ["eins"])

    def test_cancel_clears_everything(self):
        self.h.speak([LangChangeCommand("en"), "one", LangChangeCommand("fr"), "un", IndexCommand(3)])
        a = self.h.guests["A"]
        late = [i.index for i in a.spoken[0] if isinstance(i, IndexCommand)]
        self.h.scheduler.cancel()
        self.assertEqual(a.cancelled, 1)
        self.assertTrue(self.h.scheduler.is_idle())
        # Late callbacks from the cancelled utterance, which an engine may still deliver, are ignored.
        for index in late:
            self.assertFalse(self.h.scheduler.on_index(a, index))
        self.assertFalse(self.h.scheduler.on_done(a))
        self.assertEqual((self.h.indexes, self.h.done), ([], 0))
        self.h.run_main()
        self.assertEqual(self.h.guests.get("B", FakeGuest("B")).spoken, [])

    def test_pause_holds_the_seam(self):
        self.h.speak([LangChangeCommand("en"), "one", LangChangeCommand("fr"), "un"])
        a = self.h.guests["A"]
        self.h.scheduler.pause(True)
        self.assertTrue(a.paused)
        a.finish(self.h.scheduler)
        self.h.run_main()
        self.assertEqual(self.h.guests.get("B", FakeGuest("B")).spoken, [])
        self.h.scheduler.pause(False)
        self.assertEqual(len(self.h.guests["B"].spoken), 1)

    def test_guest_done_without_marker_completes_piece(self):
        self.h.speak([LangChangeCommand("en"), "one", LangChangeCommand("fr"), "un"])
        a = self.h.guests["A"]
        self.h.scheduler.on_done(a)
        self.h.run_main()
        self.assertEqual(len(self.h.guests["B"].spoken), 1)

    def test_done_without_reaching_its_indexes_still_reports_them(self):
        self.h.speak([LangChangeCommand("en"), "one", IndexCommand(1), "two", IndexCommand(2), LangChangeCommand("fr"), "un"])
        a = self.h.guests["A"]
        self.h.scheduler.on_done(a)  # a synthesis that failed: no index reached
        self.h.run_main()
        self.assertEqual(self.h.indexes, [1, 2])
        self.assertEqual(len(self.h.guests["B"].spoken), 1)

    def test_indexes_reached_before_done_are_reported_once(self):
        self.h.speak([LangChangeCommand("en"), "one", IndexCommand(1)])
        a = self.h.guests["A"]
        a.finish(self.h.scheduler)
        self.h.scheduler.on_done(a)
        self.assertEqual(self.h.indexes, [1])

    def test_missing_guest_falls_through(self):
        table = Table([Row("en", "A"), Row("fr", "broken")])
        h = Harness(table)
        h.speak([LangChangeCommand("en"), "one", LangChangeCommand("fr"), "un", IndexCommand(1)])
        a = h.guests["A"]
        a.finish(h.scheduler)
        h.run_main()
        self.assertEqual(h.indexes, [1])
        self.assertEqual(h.done, 1)

    def test_failed_speak_reports_its_indexes(self):
        a = FakeGuest("A")

        def fail(items):
            raise RuntimeError("engine gone")

        a.speak = fail
        self.h.guests["A"] = a
        self.h.speak([LangChangeCommand("en"), "one", IndexCommand(4)])
        self.h.run_main()
        self.assertEqual(self.h.indexes, [4])
        self.assertEqual(self.h.done, 1)

    def test_guest_without_done_frees_the_seam_at_its_marker(self):
        h = Harness(self.table)
        h.scheduler.notifies_done = lambda guest: guest.name != "A"
        h.speak([LangChangeCommand("en"), "one", LangChangeCommand("fr"), "un"])
        a = h.guests["A"]
        for items in list(a.queued):
            for item in items:
                if isinstance(item, IndexCommand):
                    h.scheduler.on_index(a, item.index)
        h.run_main()
        self.assertEqual(texts(h.guests["B"].spoken[0]), ["un"])

    def test_other_guest_waits_for_done_after_marker(self):
        """Eloquence reports marks when audio is queued; the next guest must wait for done."""
        self.h.speak([LangChangeCommand("en"), "one", LangChangeCommand("fr"), "un"])
        a = self.h.guests["A"]
        for items in list(a.queued):
            for item in items:
                if isinstance(item, IndexCommand):
                    self.h.scheduler.on_index(a, item.index)
        self.h.run_main()
        self.assertEqual(self.h.guests.get("B", FakeGuest("B")).spoken, [])
        self.h.scheduler.on_done(a)
        self.h.run_main()
        self.assertEqual(texts(self.h.guests["B"].spoken[0]), ["un"])

    def test_done_reported_once_per_stream(self):
        self.h.speak([LangChangeCommand("en"), "one", IndexCommand(1)])
        a = self.h.guests["A"]
        for items in list(a.queued):
            for item in items:
                if isinstance(item, IndexCommand):
                    self.h.scheduler.on_index(a, item.index)
        self.assertEqual(self.h.done, 1)
        self.h.scheduler.on_done(a)
        self.assertEqual(self.h.done, 1)

    def test_every_send_is_handed_to_apply_row_after_a_cancel_too(self):
        """Skipping a row the guest already carries is the driver's job, which clears its mark whenever something
        else touches the guest; the scheduler hands it every send, the same row again included."""
        applied = []
        self.h.scheduler.apply_row = lambda guest, row: applied.append((guest.name, row.lang))
        self.h.speak([LangChangeCommand("en"), "one"])
        self.h.speak([LangChangeCommand("en"), "two"])
        self.h.scheduler.cancel()
        self.h.speak([LangChangeCommand("en"), "three"])
        self.assertEqual(applied, [("A", "en")] * 3)

    def test_each_piece_is_adapted_for_its_row(self):
        seen = []

        def adapt(guest, row, items):
            seen.append((guest.name, row.lang))
            return [f"{row.lang}:{i}" if isinstance(i, str) else i for i in items]

        self.h.scheduler.adapt = adapt
        self.h.speak([LangChangeCommand("en"), "Hello", LangChangeCommand("fr"), "Bonjour"])
        a = self.h.guests["A"]
        self.assertEqual(texts(a.spoken[0]), ["en:Hello"])
        a.finish(self.h.scheduler)
        self.h.run_main()
        b = self.h.guests["B"]
        self.assertEqual(texts(b.spoken[0]), ["fr:Bonjour"])
        self.assertEqual(seen, [("A", "en"), ("B", "fr")])

    def test_markers_are_told_from_nvdas_indexes(self):
        self.h.speak([LangChangeCommand("en"), "Hello", IndexCommand(7)])
        ours = [i.index for i in self.h.guests["A"].spoken[0] if isinstance(i, IndexCommand)]
        nvdas, marker = ours
        self.assertFalse(self.h.scheduler.is_marker(nvdas))
        self.assertTrue(self.h.scheduler.is_marker(marker))
        self.assertFalse(self.h.scheduler.is_marker(12345))

    def test_done_of_one_call_leaves_the_next_in_flight(self):
        """eSpeak and Vocalizer report done after each speak call, with the next one still queued."""
        self.h.speak([LangChangeCommand("en"), "one", IndexCommand(1)])
        self.h.speak([LangChangeCommand("en"), "two", IndexCommand(2), LangChangeCommand("fr"), "deux"])
        a = self.h.guests["A"]
        a.finish(self.h.scheduler, count=1)
        self.h.scheduler.on_done(a)  # the first call's done
        self.h.run_main()
        self.assertEqual(self.h.indexes, [1])
        self.assertEqual(self.h.guests.get("B", FakeGuest("B")).spoken, [])
        a.finish(self.h.scheduler)
        self.h.run_main()
        self.assertEqual(self.h.indexes, [1, 2])
        self.assertEqual(texts(self.h.guests["B"].spoken[0]), ["deux"])

    def test_done_after_a_marker_is_a_failure_for_a_guest_that_drains(self):
        self.h.scheduler.done_drains = lambda guest: True
        self.h.speak([LangChangeCommand("en"), "one", IndexCommand(1)])
        self.h.speak([LangChangeCommand("en"), "two", IndexCommand(2)])
        a = self.h.guests["A"]
        a.finish(self.h.scheduler, count=1)
        self.h.scheduler.on_done(a)  # the second failed; OneCore reports done once its queue is empty
        self.assertEqual(self.h.indexes, [1, 2])
        self.assertEqual(self.h.done, 1)

    def test_a_done_while_a_piece_is_handed_over_does_not_finish_it(self):
        self.h.speak([LangChangeCommand("en"), "one"])
        a = self.h.guests["A"]
        a.finish(self.h.scheduler)
        speak = a.speak

        def late_done_then_speak(items):
            self.h.scheduler.on_done(a)  # from the first call, arriving now
            speak(items)

        a.speak = late_done_then_speak
        self.h.speak([LangChangeCommand("en"), "two", IndexCommand(2), LangChangeCommand("fr"), "deux"])
        self.h.run_main()
        self.assertEqual(self.h.indexes, [])
        self.assertEqual(self.h.guests.get("B", FakeGuest("B")).spoken, [])
        a.finish(self.h.scheduler)
        self.h.run_main()
        self.assertEqual(self.h.indexes, [2])
        self.assertEqual(texts(self.h.guests["B"].spoken[0]), ["deux"])

    def test_a_change_of_voice_on_the_same_guest_waits_for_done(self):
        """Vocalizer stops its audio to change voice, SAPI 5 rebuilds its engine."""
        table = Table([Row("en", "A", voice="v1"), Row("de", "A", voice="v2")])
        h = Harness(table)
        h.speak([LangChangeCommand("en"), "one", LangChangeCommand("de"), "eins"])
        a = h.guests["A"]
        for item in a.queued[0]:
            if isinstance(item, IndexCommand):
                h.scheduler.on_index(a, item.index)
        h.run_main()
        self.assertEqual(len(a.spoken), 1)
        h.scheduler.on_done(a)
        h.run_main()
        self.assertEqual(texts(a.spoken[1]), ["eins"])

    def test_a_reached_marker_reports_what_the_guest_passed_without_reporting(self):
        """Acapela reports only the last mark of each block of audio."""
        self.h.speak([LangChangeCommand("en"), "one", IndexCommand(1)])
        self.h.speak([LangChangeCommand("en"), "two", IndexCommand(2), "three", IndexCommand(3)])
        a = self.h.guests["A"]
        last_marker = [i.index for i in a.spoken[1] if isinstance(i, IndexCommand)][-1]
        self.h.scheduler.on_index(a, last_marker)
        self.assertEqual(self.h.indexes, [1, 2, 3])
        self.assertTrue(self.h.scheduler.is_idle())

    def test_indexes_sent_are_even(self):
        # So Acapela's mark, written one higher, maps back down whichever number its engine returns.
        self.h.speak([LangChangeCommand("en"), "one", IndexCommand(1), "two", IndexCommand(2)])
        ours = [i.index for i in self.h.guests["A"].spoken[0] if isinstance(i, IndexCommand)]
        self.assertEqual(len(ours), 3)
        self.assertTrue(all(i % 2 == 0 for i in ours))

    def test_a_guest_that_settles_waits_for_done_on_any_change_of_row(self):
        self.h.scheduler.settles = lambda guest: True
        self.h.speak([LangChangeCommand("en"), "one", LangChangeCommand("de"), "eins"])
        a = self.h.guests["A"]
        for item in a.queued[0]:
            if isinstance(item, IndexCommand):
                self.h.scheduler.on_index(a, item.index)
        self.h.run_main()
        self.assertEqual(len(a.spoken), 1)
        self.h.scheduler.on_done(a)
        self.h.run_main()
        self.assertEqual(texts(a.spoken[1]), ["eins"])

    def test_a_serial_guest_gets_one_piece_at_a_time(self):
        self.h.scheduler.serial = lambda guest: True
        self.h.speak([LangChangeCommand("en"), "one", IndexCommand(1)])
        self.h.speak([LangChangeCommand("en"), "two", IndexCommand(2)])
        a = self.h.guests["A"]
        self.assertEqual(len(a.spoken), 1)
        a.finish(self.h.scheduler)
        self.h.run_main()
        self.assertEqual(texts(a.spoken[1]), ["two"])

    def test_foreign_indexes_are_not_ours(self):
        self.assertFalse(self.h.scheduler.on_index(FakeGuest("X"), 4242))


if __name__ == "__main__":
    unittest.main()
