"""Runs the detector over an NVDA speech sequence.

Strings arrive with the language the application tagged them, as LangChangeCommand items, or untagged.
Untagged strings are detected; tagged strings are verified against their tag; text tagged with the
default language is, by choice, detected like untagged text, since a page's document language carries
no information about a foreign paragraph inside it. Spelled characters (character mode) and the reader's
own words are left alone.

Imports speech.commands, so it runs inside NVDA or under the test stub.
"""
from speech.commands import LangChangeCommand, CharacterModeCommand

from .scripts import base, is_text


def filter_sequence(seq, detector, default_language, detect_in_default_tagged=True, unit_language=None, line_runs=None):
    """A new sequence with LangChangeCommand items inserted around the runs the detector tags.

    unit_language(text) -> a language for a string that is the unit being read at the caret (a character
    or a word, which cannot be detected alone), from the language its line reads in at that spot, or a
    typed word in its keyboard's language; None otherwise. Such a string is tagged whole instead of
    detected, or left as it is when the language is the default's.

    line_runs(text, detected) is called for each string in order, so it can follow the strings' places in
    the line being read; for a string to be detected, it may return its runs as read among the text around
    the line, used in place of the string's own detection, or None.
    """
    if detector is None or detector.mode == "off":
        return seq
    out = []
    tag = None  # the application's current tag, None for the default
    default_base = base(default_language)
    character_mode = False
    changed = False
    for item in seq:
        if isinstance(item, LangChangeCommand):
            tag = item.lang or None
            out.append(item)
            continue
        if isinstance(item, CharacterModeCommand):
            character_mode = item.state
            out.append(item)
            continue
        if not isinstance(item, str) or not item.strip():
            out.append(item)
            continue
        detected = tag is None or (detect_in_default_tagged and base(tag) == default_base)
        unit = None
        if unit_language is not None and detected:
            unit = unit_language(item)
        in_line = None
        if line_runs is not None:
            in_line = line_runs(item, detected and unit is None and not character_mode)
        if unit is not None:
            # The default's own language (a typed word on a keyboard of the default) leaves the text alone.
            runs = [(tag if base(unit) == default_base else unit, item)]
        elif character_mode or (len(item.strip()) < 2 and not is_text(item)):
            out.append(item)
            continue
        elif detected:
            runs = in_line or detector.tagged(item)
            if tag is not None:
                # Text left in the default language keeps the application's own tag, dialect included.
                runs = [(lang or tag, text) for lang, text in runs]
        else:
            runs = detector.verified(item, tag)
        if len(runs) == 1 and runs[0][0] == tag:
            out.append(item)
            continue
        current = tag
        for lang, text in runs:
            if not text:
                continue
            if lang != current:
                out.append(LangChangeCommand(lang))
                current = lang
                changed = True
            out.append(text)
        if current != tag:
            out.append(LangChangeCommand(tag))
            changed = True
    return out if changed else seq


class LineStrings:
    """The strings of a line's speech sequence, as they come, placed in the text around the line once it is
    fetched. Browse mode splits a line at links and other fields and puts NVDA's own words among the pieces
    ("link", "level 2", "bold"). The line's own strings follow one another through it, so each is placed
    where the ones before it end, with nothing but spaces and marks between: an "A" ending the line is that
    one, not the first capital A of the line, and "level 2" announced before a heading is not placed at the
    heading's own "level 2". NVDA's word may still stand in the line just there ("bold" before "bold text"),
    so a string that fits nowhere else takes the place of the one before it."""

    def __init__(self):
        self.items = []
        self.cursor = None  # where the strings placed so far end
        self.placed = 0  # how many of the strings have been looked for
        self.last = None  # where the cursor stood before the last string placed

    def add(self, text):
        self.items.append(text)

    def place_last(self, around, line_start, line_end, skipped=()):
        """(start in `around`, the string as found there) for the last string added, or None where it is not
        in the line, which runs from line_start to line_end in `around`. A string is found as it is, or
        stripped; one whose lowercase stripped form is in `skipped` (the reader's own words) is passed over."""
        if self.cursor is None:
            self.cursor = line_start
        found = None
        while self.placed < len(self.items):
            item = self.items[self.placed]
            self.placed += 1
            found = None
            if item.strip().lower() in skipped:
                continue
            before = self.cursor
            found = self.next_to(around, item, before, line_end)
            if found is None and self.last is not None:
                before = self.last
                found = self.next_to(around, item, before, line_end)
            if found is not None:
                self.last = before
                self.cursor = found[0] + len(found[1])
        return found

    @staticmethod
    def next_to(around, item, cursor, line_end):
        for candidate in (item, item.strip()):
            if not candidate:
                continue
            at = around.find(candidate, cursor, line_end)
            if at >= 0 and not any(c.isalnum() for c in around[cursor:at]):
                return at, candidate
        return None


def untagged_sequence(seq, ignored):
    """The sequence with each language command whose language `ignored(language)` names replaced by one for the
    default, so its text is read as untagged and detected as such."""
    if not any(isinstance(item, LangChangeCommand) and item.lang and ignored(item.lang) for item in seq):
        return seq
    return [
        LangChangeCommand(None) if isinstance(item, LangChangeCommand) and item.lang and ignored(item.lang) else item
        for item in seq
    ]


def locked_sequence(seq, language):
    """The sequence spoken in one language, for the language lock: every language command dropped, and, for a
    language other than the default (None), one in front. NVDA repeats it before each string."""
    out = [item for item in seq if not isinstance(item, LangChangeCommand)]
    if language is not None and any(isinstance(item, str) for item in out):
        out.insert(0, LangChangeCommand(language))
    return out
