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

import contextlib

import config
import speech
import speech.speech as speech_impl
import textInfos
from logHandler import log

from mlang import table as T
from mlang.scripts import base


class UnitContext:
    def __init__(self, engine):
        self.engine = engine
        self.language = None  # the context language while a wrapped call runs, None otherwise
        self.unit_text = None
        self.last_line = None
        self.last_runs = None
        self.last_key = None  # the engine's configuration key the cached runs were made under
        self.originals = {}

    # ------------------------------------------------------------ install

    def install(self):
        self._patch("speakTextInfo", self._speakTextInfo)
        self._patch("spellTextInfo", self._spellTextInfo)
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

    def _getSpellingSpeech(self, text, locale=None, *args, **kwargs):
        return self.originals["getSpellingSpeech"](text, self.locale_for(text, locale), *args, **kwargs)

    def _getSingleCharDescription(self, text, locale=None, *args, **kwargs):
        return self.originals["getSingleCharDescription"](text, self.locale_for(text, locale), *args, **kwargs)

    # ------------------------------------------------------------ context

    def locale_for(self, text, locale):
        """The locale a spelling helper should use for `text`: the caller's, unless the context language
        stands in for it (no locale, or the default language's tag when that is detected through)."""
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
        """The context language for a string spoken while a context is held: the unit's own text only."""
        if self.language is None or not isinstance(text, str):
            return None
        stripped = text.strip()
        if not stripped:
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
            log.debugWarning("multilanguage: no line context for the unit", exc_info=True)
        self.language, self.unit_text = language, unit_text
        try:
            yield
        finally:
            self.language, self.unit_text = None, None

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
        if text == self.last_line and self.last_key == self.engine.key:
            runs = self.last_runs
        else:
            runs = detector.tagged(text)
            self.last_line, self.last_runs, self.last_key = text, runs, self.engine.key
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
