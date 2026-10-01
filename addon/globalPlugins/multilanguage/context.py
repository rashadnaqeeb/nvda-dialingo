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

import contextlib

import config
import keyboardHandler
import languageHandler
import speech
import speech.speech as speech_impl
import textInfos
from logHandler import log

from mlang import table as T
from mlang.scripts import base

from . import lock


def keyboard_language():
    """The language of the focused window's keyboard layout, as NVDA spells it, or None."""
    try:
        return languageHandler.windowsLCIDToLocaleName(keyboardHandler.getInputHkl() & 0xFFFF)
    except Exception:
        log.debugWarning("multilanguage: the keyboard layout's language could not be read", exc_info=True)
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
        self.last_line = None
        self.last_runs = None
        self.last_key = None  # the engine's configuration key the cached runs were made under
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
            log.debugWarning("multilanguage: no echo language for a spelled character", exc_info=True)
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
            log.debugWarning("multilanguage: no keyboard language for a typed word", exc_info=True)
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
        try:
            return base(locale) != base(speech.getCurrentLanguage()) and not describes(locale, text)
        except Exception:
            log.debugWarning("multilanguage: character descriptions for %s could not be checked" % locale, exc_info=True)
            return False

    # ------------------------------------------------------------ context

    def locale_for(self, text, locale):
        """The locale a spelling helper should use for `text`: the caller's, unless the context language
        stands in for it (no locale, or the default language's tag when that is detected through). Under the
        language lock, the locked language, None for the default."""
        try:
            locked = self.engine.language_lock()
        except Exception:
            log.debugWarning("multilanguage: the language lock could not be read", exc_info=True)
            locked = lock.AUTOMATIC
        if locked:
            return lock.language(locked)
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
