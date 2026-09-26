"""Cuts an utterance at language commands and plays the pieces on the right guest synthesizers in turn.

Pure logic: the driver hands in the command classes, a way to find and configure a guest for a row, the
notifications to raise as itself, and a way to run a callable on NVDA's main thread. Guests report
progress through their own index and done notifications, which the driver forwards here.

Every piece ends in a private index marker, as NVDA's speech manager ends each utterance, and every NVDA
index inside a piece is remapped to a private one, so progress is known per piece whatever a guest's
done-speaking semantics are. Two waits govern the seams:

- A change of row on the same guest waits for the previous piece's marker: an engine reports a mark once
  the text before it is synthesized, so parameters set afterwards cannot land on that text.
- A change of guest waits for the previous guest's done notification as well: some engines (Eloquence)
  report marks when audio is queued rather than played, and done is the signal that the audio has ended.
  The next guest would otherwise talk over the previous one's tail. So does a change of voice on the same
  guest: some drivers stop their audio, or rebuild their engine, to change voice (Vocalizer, SAPI 5).

Most drivers report done once their queue is empty, but several report it after each speak call, with the
next call still queued (eSpeak, Vocalizer, SAPI 5 without WASAPI). A done that arrives after one of the
guest's markers, while a later piece of it is still in flight, is taken as the done of the finished call.
One that arrives with none of its markers reached is a failed synthesis and finishes the pieces in flight.

Consecutive pieces on the same guest and row are sent without waiting, so a single-language stream loses
nothing to this driver.
"""
import threading
from collections import deque

MAX_INDEX = 9999


class Piece:
    __slots__ = ("row", "items", "guest", "marker", "indexes", "sent")

    def __init__(self, row):
        self.row = row
        self.items = []
        self.guest = None
        self.marker = None
        self.indexes = []  # ours for NVDA's indexes in the piece, once sent
        self.sent = False  # handed to the guest: in flight from before, but a done can only be for it after

    def has_text(self):
        return any(isinstance(i, str) and i for i in self.items)


def cut(seq, row_for_lang, default_row, LangChangeCommand):
    """Pieces of `seq`, one per run of items spoken by the same row.

    A language with a row of its own is spoken by that row with the language commands removed, since the
    row's voice is the user's choice for it. Anything else goes to the default row with its commands kept,
    so the default synthesizer switches by itself where it can, as it does without this driver.
    Command-only pieces merge into their neighbor, so no guest is asked to speak nothing.
    """
    pieces = []
    current = Piece(default_row)
    for item in seq:
        if isinstance(item, LangChangeCommand):
            row = row_for_lang(item.lang) if item.lang else None
            target = row or default_row
            if target is not current.row:
                pieces.append(current)
                current = Piece(target)
            if target is default_row:
                current.items.append(item)
            continue
        current.items.append(item)
    pieces.append(current)
    merged = []
    carry = []
    for piece in pieces:
        if not piece.items:
            continue
        if not piece.has_text():
            if merged:
                merged[-1].items.extend(piece.items)
            else:
                carry.extend(piece.items)
            continue
        if carry:
            piece.items = carry + piece.items
            carry = []
        merged.append(piece)
    if carry:
        if merged:
            merged[-1].items.extend(carry)
        else:
            piece = Piece(default_row)
            piece.items = carry
            merged.append(piece)
    for piece in merged:
        if piece.row is not default_row:
            piece.items = [i for i in piece.items if not isinstance(i, LangChangeCommand)]
    return merged


class Scheduler:
    def __init__(self, LangChangeCommand, IndexCommand, guest_for_row, apply_row, notify_index, notify_done,
                 run_on_main, log=None, notifies_indexes=lambda guest: True, notifies_done=lambda guest: True,
                 adapt=None, done_drains=lambda guest: False, settles=lambda guest: False,
                 serial=lambda guest: False):
        self.LangChangeCommand = LangChangeCommand
        self.IndexCommand = IndexCommand
        self.guest_for_row = guest_for_row
        self.apply_row = apply_row
        self.notify_index = notify_index
        self.notify_done = notify_done
        self.run_on_main = run_on_main
        self.notifies_indexes = notifies_indexes
        self.notifies_done = notifies_done
        # Whether a guest is known to report done only once its queue is empty (OneCore, Eloquence): its
        # done after a reached marker, with a piece still in flight, is then a failure after all.
        self.done_drains = done_drains
        # Whether a guest must be done before any new row is applied to it, not only one that changes its
        # voice: Acapela reports its end marker while still synthesizing, and its setters call the engine
        # without the lock its synthesis holds.
        self.settles = settles
        # Whether a guest is sent one piece at a time, the next once the previous one's marker is reached, as
        # NVDA sends the synthesizer in use one utterance at a time: for an engine not known to queue a second
        # call rather than cut the first short.
        self.serial = serial
        # adapt(guest, row, items) -> the items as the guest is to be sent them (prosody rebased on the row).
        self.adapt = adapt or (lambda guest, row, items: items)
        self.log = log or (lambda msg: None)
        self.lock = threading.RLock()
        self.pending = deque()
        self.inflight = {}  # marker index -> piece
        self.index_map = {}  # our index -> NVDA index, or None for a marker
        self.counter = 0
        self.current_guest = None  # the guest the last piece went to
        self.current_key = None  # (guest id, row key) applied to it
        self.current_voice = None  # the voice the last piece set on current_guest, when its row gives one
        self.busy_guest = None  # a guest that was sent speech and has not reported done since
        self.reached = {}  # id(guest) -> markers it reached whose calls have not reported done
        self.speaking = False  # whether NVDA is owed a done notification
        self.paused = False

    # ------------------------------------------------------------ NVDA side

    def speak(self, seq, row_for_lang, default_row):
        pieces = cut(seq, row_for_lang, default_row, self.LangChangeCommand)
        with self.lock:
            self.pending.extend(pieces)
        self.pump()

    def cancel(self):
        with self.lock:
            guests = {p.guest for p in self.inflight.values() if p.guest is not None}
            for guest in (self.current_guest, self.busy_guest):
                if guest is not None:
                    guests.add(guest)
            self.pending.clear()
            self.inflight.clear()
            self.index_map.clear()
            self.busy_guest = None
            self.reached.clear()
            self.current_key = None
            self.speaking = False
            self.paused = False
        for guest in guests:
            try:
                guest.cancel()
            except Exception as e:
                self.log(f"cancel on {guest!r} failed: {e}")

    def pause(self, switch):
        with self.lock:
            self.paused = switch
            guest = self.busy_guest
        if guest is not None:
            try:
                guest.pause(switch)
            except Exception as e:
                self.log(f"pause on {guest!r} failed: {e}")
        if not switch:
            self.pump()

    def is_idle(self):
        with self.lock:
            return not self.pending and not self.inflight

    def forget(self, guest):
        """A guest was terminated: nothing may wait on it or cancel it any more."""
        with self.lock:
            if self.current_guest is guest:
                self.current_guest = None
                self.current_key = None
                self.current_voice = None
            if self.busy_guest is guest:
                self.busy_guest = None
            self.reached.pop(id(guest), None)

    # ------------------------------------------------------------ guest side

    def is_marker(self, index):
        """Whether an index is the end-of-piece marker of a piece in flight, rather than one of NVDA's."""
        with self.lock:
            return index in self.index_map and self.index_map[index] is None

    def on_index(self, guest, index):
        """A guest reached one of its indexes: ours are mapped back, others are not for us."""
        with self.lock:
            if index not in self.index_map:
                return False
            nvda_index = self.index_map.pop(index)
            passed = []
            if nvda_index is None:
                piece = self.inflight.get(index)
                if piece is not None:
                    # Its end reached, the piece's indexes were passed too, whether or not the guest reported
                    # them (Acapela reports only the last mark of each block of audio), and so were the guest's
                    # pieces sent before it, whose markers were lost the same way.
                    for marker in list(self.inflight):
                        earlier = self.inflight[marker]
                        if earlier.guest is not piece.guest:
                            continue
                        del self.inflight[marker]
                        self.index_map.pop(marker, None)
                        self.reached[id(guest)] = self.reached.get(id(guest), 0) + 1
                        passed += [self.index_map.pop(ours) for ours in earlier.indexes if ours in self.index_map]
                        if earlier is piece:
                            break
                # A guest that never reports done is free once its last marker is reached; waiting for
                # its done would hold the next guest's piece forever.
                if (self.busy_guest is guest and not self.notifies_done(guest)
                        and not any(p.guest is guest for p in self.inflight.values())):
                    self.busy_guest = None
        if nvda_index is not None:
            self.notify_index(nvda_index)
        else:
            for passed_index in passed:
                self.notify_index(passed_index)
            self._progress()
        return True

    def on_done(self, guest):
        """A guest drained its queue: it is free for another guest to follow, and any of its pieces still
        counted in flight are finished. Unless it is only the done of one call (see the module's notes)."""
        with self.lock:
            mine = [m for m, p in self.inflight.items() if p.guest is guest]
            markers = [m for m in mine if self.inflight[m].sent]
            if markers and self.reached.get(id(guest), 0) > 0 and not self.done_drains(guest):
                # The done of a call whose marker was reached, with a later call still queued on the guest.
                self.reached[id(guest)] -= 1
                return False
            self.reached.pop(id(guest), None)
            # A piece being handed to the guest right now is not finished by a done from before it.
            was_busy = self.busy_guest is guest and len(markers) == len(mine)
            if was_busy:
                self.busy_guest = None
            unreported = []
            for m in markers:
                piece = self.inflight.pop(m, None)
                self.index_map.pop(m, None)
                # A guest done without reaching them (a synthesis that failed): NVDA's indexes in the piece
                # are still owed to its speech manager, which waits for them.
                for ours in piece.indexes if piece is not None else ():
                    if ours in self.index_map:
                        unreported.append(self.index_map.pop(ours))
        if not was_busy and not markers:
            return False
        for index in unreported:
            self.notify_index(index)
        self._progress()
        return True

    def _progress(self):
        """After a piece finished or a guest went quiet: report done to NVDA when everything is spoken,
        or continue on the main thread when more is waiting."""
        with self.lock:
            if self.inflight:
                return
            if self.pending:
                more = True
                done = False
            else:
                more = False
                done = self.speaking
                self.speaking = False
        if done:
            self.notify_done()
        elif more:
            self.run_on_main(self.pump)

    # ------------------------------------------------------------ internals

    def _next_index(self):
        """Even numbers only: Acapela writes a mark one higher than it is given, and whether its engine gives
        that number back or the one it was given cannot be read from its code; with only even numbers sent,
        the driver maps an odd one back down (languageTable), and either way is right."""
        for _ in range(MAX_INDEX // 2):
            self.counter = self.counter % (MAX_INDEX - 1) + 2
            if self.counter not in self.index_map:
                return self.counter
        raise RuntimeError("no free index")

    def pump(self):
        """Send pieces while the way is clear: always onto the same guest and row, onto another row of the
        same guest once its pieces are finished, and once it is done too when the row changes its voice,
        onto another guest once the previous one is done."""
        while True:
            dropped = None
            with self.lock:
                if self.paused or not self.pending:
                    return
                piece = self.pending[0]
                guest = self.guest_for_row(piece.row)
                if guest is None:
                    # Dropped in order, once what is ahead of it is spoken, so NVDA's indexes in it are
                    # reported where they fall: its speech manager waits for them.
                    if self.inflight or self.busy_guest is not None:
                        return
                    self.pending.popleft()
                    self.log(f"no synthesizer for row {piece.row!r}; piece dropped")
                    dropped = [i.index for i in piece.items if isinstance(i, self.IndexCommand)]
                    finished = not self.pending and (self.speaking or bool(dropped))
                    if finished:
                        self.speaking = False
                else:
                    key = (id(guest), piece.row.key())
                    if self.inflight and key != self.current_key:
                        return
                    if self.serial(guest) and any(p.guest is guest for p in self.inflight.values()):
                        return
                    if self.busy_guest is not None and self.busy_guest is not guest:
                        return
                    voice = piece.row.get("voice")
                    if guest is not self.current_guest:
                        self.current_voice = None
                    changes_voice = voice is not None and self.current_voice is not None and voice != self.current_voice
                    changes_row = key != self.current_key and self.settles(guest)
                    if (changes_voice or changes_row) and self.busy_guest is guest and self.notifies_done(guest):
                        return
                    self.pending.popleft()
                    piece.guest = guest
                    if voice is not None:
                        self.current_voice = voice
                    items = []
                    for item in piece.items:
                        if isinstance(item, self.IndexCommand):
                            ours = self._next_index()
                            self.index_map[ours] = item.index
                            piece.indexes.append(ours)
                            items.append(self.IndexCommand(ours))
                        else:
                            items.append(item)
                    marker = self._next_index()
                    self.index_map[marker] = None
                    piece.marker = marker
                    items.append(self.IndexCommand(marker))
                    self.inflight[marker] = piece
                    self.current_guest = guest
                    self.current_key = key
                    self.busy_guest = guest
                    self.speaking = True
            if dropped is not None:
                for index in dropped:
                    self.notify_index(index)
                if finished:
                    self.run_on_main(self.notify_done)
                continue
            # Every send: the driver skips it when the guest already carries the row, and anything that
            # touched the guest meanwhile (a preview from the settings dialog) has cleared that mark.
            try:
                self.apply_row(guest, piece.row)
            except Exception as e:
                self.log(f"applying row {piece.row!r} to {guest!r} failed: {e}")
            try:
                guest.speak(self.adapt(guest, piece.row, items))
                reports = self.notifies_indexes(guest)
            except Exception as e:
                self.log(f"speak on {guest!r} failed: {e}")
                reports = False
            with self.lock:
                piece.sent = True
            if not reports:
                # A guest that never reports progress (NVDA's silence driver), or one that failed to take
                # the piece, is done as soon as it is asked; NVDA's indexes in the piece are reported, since
                # its speech manager waits for them.
                for item in items:
                    if isinstance(item, self.IndexCommand):
                        self.on_index(guest, item.index)
                self.on_done(guest)
