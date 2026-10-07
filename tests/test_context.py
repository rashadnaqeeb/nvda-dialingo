"""The line context in context.py over a fake offset-based text control: a line spoken at the caret is held, the
text around it fetched only for a string of the line whose edge is undecided, and each string placed in its line
after the strings before it."""
import functools
import importlib.util
import os
import sys
import types
import unittest

import nvda_stub  # noqa: F401
from speech.commands import LangChangeCommand

from mlang.sequence import filter_sequence

UNIT_CHARACTER, UNIT_WORD, UNIT_LINE, UNIT_READINGCHUNK = "character", "word", "line", "readingChunk"


def _stub_nvda():
    def module(name, **attrs):
        m = sys.modules.get(name) or types.ModuleType(name)
        for k, v in attrs.items():
            setattr(m, k, v)
        sys.modules[name] = m
        return m

    class Log:
        def debug(self, *a, **k):
            pass

        debugWarning = warning = error = debug

        def isEnabledFor(self, level):
            return True

    module("config", conf={})
    module("keyboardHandler", getInputHkl=lambda: 0)
    module("languageHandler", windowsLCIDToLocaleName=lambda lcid: None)
    module("speech.speech")
    sys.modules["speech"].speech = sys.modules["speech.speech"]
    module("textInfos", UNIT_CHARACTER=UNIT_CHARACTER, UNIT_WORD=UNIT_WORD, UNIT_LINE=UNIT_LINE,
           UNIT_READINGCHUNK=UNIT_READINGCHUNK)
    module("logHandler", log=Log())
    here = os.path.dirname(os.path.abspath(__file__))
    package_dir = os.path.join(here, "..", "addon", "globalPlugins", "dialingo")
    package = module("dialingo")
    package.__path__ = [package_dir]
    package.lock = module("dialingo.lock", AUTOMATIC="")
    spec = importlib.util.spec_from_file_location("dialingo.context", os.path.join(package_dir, "context.py"))
    context = importlib.util.module_from_spec(spec)
    sys.modules["dialingo.context"] = context
    spec.loader.exec_module(context)
    return context


context = _stub_nvda()


class Story:
    """Text wrapped into lines, as an edit control shows it; counts the text fetched."""

    def __init__(self, text, lines):
        self.text = text
        self.lines = lines  # (start, end) of each line, the end past the space it broke at
        self.fetches = 0
        self.moves = 0

    def line_of(self, offset):
        for i, (s, e) in enumerate(self.lines):
            if s <= offset < e:
                return i
        return len(self.lines) - 1


class Info:
    """An offset-based TextInfo over a Story."""

    def __init__(self, story, start, end):
        self.story, self._startOffset, self._endOffset = story, start, end

    def copy(self):
        return Info(self.story, self._startOffset, self._endOffset)

    @property
    def isCollapsed(self):
        return self._startOffset == self._endOffset

    @property
    def text(self):
        self.story.fetches += 1
        return self.story.text[self._startOffset:self._endOffset]

    def expand(self, unit):
        assert unit == UNIT_LINE
        self._startOffset, self._endOffset = self.story.lines[self.story.line_of(self._startOffset)]

    def move(self, unit, direction, endPoint=None):
        assert unit == UNIT_LINE
        self.story.moves += 1
        lines = self.story.lines
        if endPoint == "start":
            i = max(0, self.story.line_of(self._startOffset) + direction)
            self._startOffset = lines[i][0]
        else:
            i = min(len(lines) - 1, self.story.line_of(max(self._startOffset, self._endOffset - 1)) + direction)
            self._endOffset = lines[i][1]
        return direction

    def setEndPoint(self, other, which):
        assert which == "endToStart"
        self._endOffset = other._startOffset


class Detector:
    """Undecided where a string ends in " A" or is "A"; records what in_context is asked."""

    mode = "full"
    labels = ()
    reader_words = {"link"}

    def __init__(self):
        self.asked = []

    def undecided_edge(self, text):
        text = text.rstrip()
        return text == "A" or text.endswith(" A")

    def in_context(self, line, text, start, undecided=None):
        self.asked.append((line, text, start))
        return [("es_ES" if "Spanish" in text else "en_US", line)]

    def tagged(self, text):
        return [(None, text)]


class Engine:
    key = 1

    def __init__(self, detector):
        self.detector = detector

    def current(self):
        return self.detector


TEXT = "A label reading this. We walked along the path by the side of the lake. A row of trees marks the edge."


def story():
    lines, start = [], 0
    for line in ("A label reading this. ", "We walked along the path ", "by the side of the lake. A ", "row of trees marks the edge."):
        lines.append((start, start + len(line)))
        start += len(line)
    return Story(TEXT, lines)


class LineContextTests(unittest.TestCase):
    def setUp(self):
        self.detector = Detector()
        self.unit = context.UnitContext(Engine(self.detector))
        self.spoken = []

        def speak(info, *args, **kwargs):
            # NVDA's speakTextInfo builds the line's sequence and speaks it, which runs the filter.
            pieces = kwargs.pop("pieces", None) or [info.text]
            line_runs = functools.partial(self.unit.line_runs, self.detector)
            self.spoken.append(filter_sequence(pieces, self.detector, "sv_SE", line_runs=line_runs))

        self.unit.originals["speakTextInfo"] = speak

    def line(self, s, number):
        start, end = s.lines[number]
        return Info(s, start, end)

    def test_an_undecided_line_is_read_among_the_lines_around_it(self):
        s = story()
        self.unit._speakTextInfo(self.line(s, 2), unit=UNIT_LINE)
        ((line, around, start),) = self.detector.asked
        self.assertEqual(line, "by the side of the lake. A ")
        self.assertEqual(around, TEXT)  # two lines either side reach the whole story
        self.assertEqual(around[start:start + len(line)], line)
        self.assertEqual(self.spoken[0], [LangChangeCommand("en_US"), line, LangChangeCommand(None)])

    def test_a_decided_line_fetches_nothing_more(self):
        s = story()
        self.unit._speakTextInfo(self.line(s, 1), unit=UNIT_LINE)
        self.assertEqual(self.detector.asked, [])
        self.assertEqual((s.fetches, s.moves), (1, 0))  # the one fetch is the speech's own

    def test_a_say_all_chunk_is_not_held(self):
        # Say all speaks whole sentences through speechWithoutPauses; a chunk reaching speakTextInfo is not a line.
        self.unit._speakTextInfo(self.line(story(), 2), None, None, UNIT_READINGCHUNK)
        self.assertEqual(self.detector.asked, [])

    def test_nvda_s_own_string_not_in_the_line_fetches_nothing_around_it(self):
        s = story()
        self.unit._speakTextInfo(self.line(s, 1), unit=UNIT_LINE, pieces=["level A", "We walked along the path "])
        self.assertEqual(self.detector.asked, [])
        self.assertEqual(s.moves, 0)

    def test_identical_lines_in_different_paragraphs_keep_their_own_language(self):
        text = "English one. \nA\nx\ny\nz\nSpanish one. \nA\n"
        lines, start = [], 0
        for line in text.splitlines(keepends=True):
            lines.append((start, start + len(line)))
            start += len(line)
        s = Story(text, lines)
        first, second = text.index("A\n"), text.rindex("A\n")
        self.assertEqual(self.unit.language_at(Info(s, first, first + 1)), "en_US")
        self.assertEqual(self.unit.language_at(Info(s, second, second + 1)), "es_ES")
        self.assertEqual(self.unit.language_at(Info(s, first, first + 1)), "en_US")

    def test_other_units_are_not(self):
        self.unit._speakTextInfo(self.line(story(), 2), unit=None)
        self.assertEqual(self.detector.asked, [])
        self.assertIsNone(self.unit.line_info)

    def test_a_string_is_placed_after_the_strings_before_it(self):
        # Browse mode splits a line at its fields: the "A" spoken last is the line's last, not the first in TEXT.
        s = story()
        info = self.line(s, 2)
        self.unit._speakTextInfo(info, unit=UNIT_LINE, pieces=["by the side of the lake. ", "link", "A "])
        ((line, around, start),) = self.detector.asked
        self.assertEqual(line, "A ")
        self.assertEqual(start, TEXT.index("lake. A") + len("lake. "))

    def test_the_text_around_is_fetched_once_for_the_line(self):
        s = story()
        self.unit._speakTextInfo(self.line(s, 2), unit=UNIT_LINE, pieces=["by the side of the lake. A", "A"])
        moves = s.moves
        self.assertEqual(moves, 2)
        self.assertEqual(len(self.detector.asked), 1)  # the second "A" is not in the line after the first

    def test_a_grid_row_with_labels_is_left_alone(self):
        self.detector.labels = ("Subject",)
        self.unit._speakTextInfo(self.line(story(), 2), unit=UNIT_LINE)
        self.assertEqual(self.detector.asked, [])

    def test_a_character_takes_its_language_from_its_line_read_in_context(self):
        s = story()
        offset = TEXT.index("lake. A") + len("lake. ")
        self.assertEqual(self.unit.language_at(Info(s, offset, offset + 1)), "en_US")
        self.assertEqual(self.detector.asked[0][0], "by the side of the lake. A ")


if __name__ == "__main__":
    unittest.main()
