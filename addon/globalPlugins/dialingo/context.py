# A character or word read at the caret is spoken in the language its line reads in at that spot.
#
# A single character or word cannot be detected on its own, and the detector never guesses one. Instead
# the line is detected once and kept, and the unit's untagged text takes the language of the run it falls
# in. NVDA hands the speech functions the unit alone, with no line or offset, so this module wraps the
# speech functions that the caret and review scripts call for character and word units, works the line
# context out from the TextInfo, and holds it while the wrapped call runs. Inside that window, the
# spelling helpers get the context language as their locale when they were given none, which gives the
# character's description in that language too, and the sequence filter tags the unit's text.
#
# Text an application tagged with another language keeps its tag. A tag with the default language (a web
# page's or a document's own language, which most carry) is treated like no tag, as the sequence filter
# treats it: the character description NVDA builds from that locale would otherwise come out in the
# default language, and be spoken by the default voice, after the character itself was read in the
# line's language. The "detect in default-tagged text" setting turns that off along with the rest.
#
# Typing echo follows the keyboard layout: a typed character, one deleted with backspace, and a typed word
# are read in the keyboard's language where a row or a voice speaks it. A letter of a script the keyboard
# does not write goes to the language of its script, a word to detection.
#
# A line read at the caret is often part of a sentence: wrapped text ends a line on a sentence's first word
# ("lake. A") or puts a paragraph's last word on a line of its own. Detected alone, such an edge stays with
# the default voice. While a line is spoken its TextInfo is held, and a string of it whose edge the detector
# cannot decide alone, and which is in the line's own text (not NVDA's "level 2"), is read among the text
# around the line, two lines either side, fetched once for the line. A line whose edges are decided fetches
# nothing more. A character or word takes its language from its line read the same way. Say all needs none
# of this: it does not speak through speakTextInfo, and NVDA holds its text back to the last sentence end
# (speechWithoutPauses), so the filter gets whole sentences.

import contextlib
import logging
import time

import config
import keyboardHandler
import languageHandler
import speech
import speech.speech as speech_impl
import textInfos
from logHandler import log

from mlang import table as T
from mlang.scripts import base
from mlang.sequence import LineStrings

from . import lock

# Lines of text fetched on each side of a line read alone, for the sentences it cuts.
LINES_AROUND = 2


def line_of(info):
    """The line's TextInfo: `info` itself, expanded to its line where it is collapsed."""
    line = info.copy()
    if line.isCollapsed:
        line.expand(textInfos.UNIT_LINE)
    return line


def surroundings(info, text=None):
    """(text around the line, the line's start in it, its end) for a line's TextInfo: two lines on either
    side, fetched as one range. `text` is the line's, where the caller has it. None where the line is not
    found in it."""
    line = line_of(info)
    if text is None:
        text = line.text
    if not text:
        return None
    around = line.copy()
    around.move(textInfos.UNIT_LINE, -LINES_AROUND, endPoint="start")
    around.move(textInfos.UNIT_LINE, LINES_AROUND, endPoint="end")
    around_text = around.text
    start = UnitContext.offset_in(around, around_text, line)
    if around_text[start:start + len(text)] != text:
        return None
    return around_text, start, start + len(text)


def keyboard_language():
    """The language of the focused window's keyboard layout, as NVDA spells it, or None."""
    try:
        return languageHandler.windowsLCIDToLocaleName(keyboardHandler.getInputHkl() & 0xFFFF)
    except Exception:
        log.debugWarning("dialingo: the keyboard layout's language could not be read", exc_info=True)
        return None


def describes(locale, character):
    """Whether NVDA's character descriptions for `locale` (or its language) describe `character`."""
    import characterProcessing

    try:
        data = characterProcessing._charDescLocaleDataMap.fetchLocaleData(locale)
    except LookupError:
        return False
    return bool(data.getCharacterDescription(character.lower()))


class UnitContext:
    def __init__(self, engine):
        self.engine = engine
        self.language = None  # the context language while a wrapped call runs, None otherwise
        self.unit_text = None
        self.keyboard = None  # the keyboard layout's language while NVDA echoes typing
        self.last_runs = None
        self.last_key = None  # (line text, text around it, the engine's configuration key) of last_runs
        self.line_info = None  # the TextInfo of the line being spoken, while a wrapped call runs
        self.line_strings = None  # the strings of its sequence so far, a LineStrings
        self.line_text = None  # its text once fetched, False where it cannot be had
        self.line_place = None  # surroundings() of it once fetched, False where they cannot be had
        self.originals = {}

    # ------------------------------------------------------------ install

    def install(self):
        self._patch("speakTextInfo", self._speakTextInfo)
        self._patch("spellTextInfo", self._spellTextInfo)
        self._patch("speakTypedCharacters", self._speakTypedCharacters)
        self._patch("speakSpelling", self._speakSpelling)
        self._patch("getSpellingSpeech", self._getSpellingSpeech)
        self._patch("getSingleCharDescription", self._getSingleCharDescription)

    def uninstall(self):
        for name, original in self.originals.items():
            setattr(speech_impl, name, original)
            if hasattr(speech, name):
                setattr(speech, name, original)
        self.originals.clear()

    def _patch(self, name, wrapper):
        self.originals[name] = getattr(speech_impl, name)
        setattr(speech_impl, name, wrapper)
        if hasattr(speech, name):
            setattr(speech, name, wrapper)

    # ------------------------------------------------------------ wrappers

    def _speakTextInfo(self, info, *args, **kwargs):
        unit = kwargs.get("unit", args[2] if len(args) > 2 else None)
        if unit in (textInfos.UNIT_CHARACTER, textInfos.UNIT_WORD):
            with self.context(info):
                return self.originals["speakTextInfo"](info, *args, **kwargs)
        if unit == textInfos.UNIT_LINE:
            with self.line_context(info):
                return self.originals["speakTextInfo"](info, *args, **kwargs)
        return self.originals["speakTextInfo"](info, *args, **kwargs)

    def _spellTextInfo(self, info, *args, **kwargs):
        try:
            short = len(info.text.split()) <= 1
        except Exception:
            short = False
        if short:
            with self.context(info):
                return self.originals["spellTextInfo"](info, *args, **kwargs)
        return self.originals["spellTextInfo"](info, *args, **kwargs)

    def _speakTypedCharacters(self, ch, *args, **kwargs):
        """Typing echo: the word NVDA echoes when a word ends is read in the keyboard's language too."""
        self.keyboard = keyboard_language()
        try:
            return self.originals["speakTypedCharacters"](ch, *args, **kwargs)
        finally:
            self.keyboard = None

    def _speakSpelling(self, text, locale=None, *args, **kwargs):
        """A lone character spelled outside any context, as one typed or deleted with backspace, is spoken
        in the keyboard's language, or by its script where the keyboard does not write it."""
        language = None
        if self.unit_text is None and (locale is None or self.overrides(locale)):
            language = self.echo_language(text)
        if language is None:
            return self.originals["speakSpelling"](text, locale, *args, **kwargs)
        self.language, self.unit_text = language, text.strip()
        try:
            return self.originals["speakSpelling"](text, locale, *args, **kwargs)
        finally:
            self.language, self.unit_text = None, None

    def echo_language(self, text):
        """The language a typed or deleted character is echoed in, None for the default."""
        if not isinstance(text, str) or len(text.strip()) != 1:
            return None
        detector = self.engine.current()
        if detector is None:
            return None
        try:
            ch = text.strip()
            language = detector.keyboard(ch, self.keyboard or keyboard_language()) or detector.character(ch)
        except Exception:
            log.debugWarning("dialingo: no echo language for a spelled character", exc_info=True)
            return None
        return language if language and base(language) != base(detector.default_tag) else None

    def typed_word_language(self, text):
        """The keyboard's language for a typed word, the default's own tag when it is the default, or None
        where the keyboard does not write the word, which is then detected."""
        detector = self.engine.current()
        if detector is None:
            return None
        try:
            return detector.keyboard(text, self.keyboard)
        except Exception:
            log.debugWarning("dialingo: no keyboard language for a typed word", exc_info=True)
            return None

    def _getSpellingSpeech(self, text, locale=None, *args, **kwargs):
        locale = self.locale_for(text, locale)
        if args and args[0] and self.undescribed(locale, text):
            args = (False,) + args[1:]
        elif kwargs.get("useCharacterDescriptions") and self.undescribed(locale, text):
            kwargs["useCharacterDescriptions"] = False
        return self.originals["getSpellingSpeech"](text, locale, *args, **kwargs)

    def _getSingleCharDescription(self, text, locale=None, *args, **kwargs):
        locale = self.locale_for(text, locale)
        if self.undescribed(locale, text):
            return iter(())
        return self.originals["getSingleCharDescription"](text, locale, *args, **kwargs)

    def undescribed(self, locale, text):
        """Whether a character spoken in a language other than the default has no description of its own in
        that language. NVDA would read the English one, in that language's voice; nothing is read instead,
        or, where the description was asked for by spelling, the character alone."""
        if not locale or base(locale) == "en" or not isinstance(text, str) or len(text) != 1:
            return False
        from . import language_switching

        if not language_switching():
            return False
        try:
            return base(locale) != base(speech.getCurrentLanguage()) and not describes(locale, text)
        except Exception:
            log.debugWarning("dialingo: character descriptions for %s could not be checked" % locale, exc_info=True)
            return False

    # ------------------------------------------------------------ context

    def locale_for(self, text, locale):
        """The locale a spelling helper should use for `text`: the caller's, unless the context language
        stands in for it (no locale, or the default language's tag when that is detected through). Under the
        language lock, the locked language, None for the default. A tag for a language with detection off is
        no locale. Without language switching, the caller's."""
        from . import language_switching

        if not language_switching():
            return locale
        try:
            locked = self.engine.language_lock()
        except Exception:
            log.debugWarning("dialingo: the language lock could not be read", exc_info=True)
            locked = lock.AUTOMATIC
        if locked:
            return lock.language(locked)
        try:
            if locale is not None and self.engine.ignores_tag(locale):
                locale = None
        except Exception:
            log.debugWarning("dialingo: whether the locale's row detects could not be read", exc_info=True)
        if self.language is None:
            return locale
        if locale is not None and not self.overrides(locale):
            return locale
        return self.language_for(text) or locale

    def overrides(self, tag):
        """Whether a tag is the default language's, which the line's detected language stands in for."""
        try:
            if not config.conf[T.CONFIG_SECTION]["detectInDefaultTagged"]:
                return False
            return base(tag) == base(speech.getCurrentLanguage())
        except Exception:
            return False

    def language_for(self, text):
        """The context language for a string spoken while a context is held: the unit's own text only.
        While NVDA echoes typing, a word's keyboard language."""
        if not isinstance(text, str):
            return None
        stripped = text.strip()
        if not stripped:
            return None
        if self.language is None:
            if self.keyboard is not None and self.unit_text is None:
                return self.typed_word_language(stripped)
            return None
        if self.unit_text is not None and stripped != self.unit_text and stripped not in self.unit_text:
            return None
        return self.language

    @contextlib.contextmanager
    def context(self, info):
        language = None
        unit_text = None
        try:
            unit_text = info.text.strip()
            if unit_text:
                language = self.language_at(info)
        except Exception:
            log.debugWarning("dialingo: no line context for the unit", exc_info=True)
        self.language, self.unit_text = language, unit_text
        try:
            yield
        finally:
            self.language, self.unit_text = None, None

    @contextlib.contextmanager
    def line_context(self, info):
        saved = (self.line_info, self.line_strings, self.line_text, self.line_place)
        self.line_info, self.line_strings, self.line_text, self.line_place = info, LineStrings(), None, None
        try:
            yield
        finally:
            self.line_info, self.line_strings, self.line_text, self.line_place = saved

    def line_runs(self, detector, text, detected):
        """For the sequence filter, bound to its detector: the runs of a string of the line being spoken, read
        among the text around the line where the detector cannot decide an edge of it alone; None otherwise.
        Called for each string in order, detected or not, so the strings before it place it in the line."""
        if self.line_info is None:
            return None
        self.line_strings.add(text)
        if not detected or detector.labels:
            # A grid row read with its column headers is its cells, each read alone.
            return None
        try:
            if not detector.undecided_edge(text):
                return None
            # Only the line's own text is worth the text around it: NVDA's "level 2" before a heading is not.
            line_text = self.text_of_line()
            if not line_text or text.strip() not in line_text:
                return None
            reader_words = detector.reader_words
            return self.read_in_context(
                detector, text, self.place_of_line,
                lambda place: self.line_strings.place_last(place[0], place[1], place[2], reader_words),
            )
        except Exception:
            log.debugWarning("dialingo: a line could not be read in context", exc_info=True)
            return None

    def text_of_line(self):
        """The text of the line being spoken, fetched once for it; None where it cannot be had."""
        if self.line_text is None:
            self.line_text = False
            try:
                self.line_text = line_of(self.line_info).text or False
            except Exception:
                log.debugWarning("dialingo: no text for the line", exc_info=True)
        return self.line_text or None

    def place_of_line(self):
        """surroundings() of the line being spoken, fetched once for it; None where they cannot be had."""
        if self.line_place is None:
            self.line_place = False
            try:
                self.line_place = surroundings(self.line_info, self.text_of_line()) or False
            except Exception:
                log.debugWarning("dialingo: no text around the line", exc_info=True)
        return self.line_place or None

    def read_in_context(self, detector, text, fetch, locate):
        """The runs of `text`, a string of a line with an undecided edge, read among the text around the line:
        fetch() gives surroundings(), and locate(them) the string's (start, text as found there) in them. None
        where either has none. The time each part took goes to the log at debug level."""
        started = time.perf_counter()
        place = fetch()
        fetched = time.perf_counter()
        if place is None:
            return None
        found = locate(place)
        if found is None:
            return None
        start, core = found
        runs = detector.in_context(core, place[0], start, undecided=True)
        if core != text:
            # Found stripped: the spaces around it go with the runs beside them.
            lead = text[:len(text) - len(text.lstrip())]
            trail = text[len(text.rstrip()):]
            runs = [(runs[0][0], lead)] + runs + [(runs[-1][0], trail)]
            runs = [(lang, piece) for lang, piece in runs if piece]
        if log.isEnabledFor(logging.DEBUG):
            log.debug("dialingo: line read in context, fetch %.1f ms, detection %.1f ms"
                      % ((fetched - started) * 1000, (time.perf_counter() - fetched) * 1000))
        return runs

    def runs_of_line(self, detector, line, text):
        """The runs of a unit's line, read in context as a line at the caret is, and kept for the next unit:
        by the line's text where it is decided alone, and by the text around it too where it is not, since
        two lines of the same text ("garden.") in different paragraphs read differently."""
        place = None
        if detector.undecided_edge(text):
            try:
                place = surroundings(line, text)
            except Exception:
                log.debugWarning("dialingo: no text around the unit's line", exc_info=True)
        key = (text, place[0] if place else None, self.engine.key)
        if key == self.last_key:
            return self.last_runs
        runs = None
        if place is not None:
            runs = self.read_in_context(detector, text, lambda: place, lambda found: (found[1], text))
        if runs is None:
            runs = detector.tagged(text)
        self.last_key, self.last_runs = key, runs
        return runs

    def language_at(self, info):
        """The language the unit's line reads in at the unit's offset, or None for the default."""
        detector = self.engine.current()
        if detector is None:
            return None
        line = info.copy()
        line.expand(textInfos.UNIT_LINE)
        text = line.text
        if not text or not any(c.isalpha() for c in text):
            return None
        offset = self.offset_in(line, text, info)
        runs = self.runs_of_line(detector, line, text)
        end = 0
        language = None
        for lang, piece in runs:
            end += len(piece)
            language = lang
            if offset < end:
                break
        return language

    @staticmethod
    def offset_in(line, text, info):
        """The unit's offset in its line. Offset-based TextInfos (edit controls, browse mode) hold it already;
        the others (UIA) give it through the text before the unit, a second fetch."""
        start_offset = getattr(info, "_startOffset", None)
        line_offset = getattr(line, "_startOffset", None)
        if isinstance(start_offset, int) and isinstance(line_offset, int):
            offset = start_offset - line_offset
            # Offsets count in the TextInfo's encoding, UTF-16 units for most, where an emoji is two.
            encoding = getattr(line, "encoding", None)
            if encoding is not None and offset > 0:
                try:
                    import textUtils

                    offset = textUtils.getOffsetConverter(encoding)(text).encodedToStrOffsets(offset, offset)[0]
                except Exception:
                    offset = -1
            if 0 <= offset <= len(text):
                return offset
        start = line.copy()
        start.setEndPoint(info, "endToStart")
        return len(start.text)
