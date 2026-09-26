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


def filter_sequence(seq, detector, default_language, detect_in_default_tagged=True, unit_language=None):
    """A new sequence with LangChangeCommand items inserted around the runs the detector tags.

    unit_language(text) -> a language for a string that is the unit being read at the caret (a character
    or a word, which cannot be detected alone), from the language its line reads in at that spot; None
    otherwise. Such a string is tagged whole instead of detected.
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
        unit = None
        if unit_language is not None and (tag is None or (detect_in_default_tagged and base(tag) == default_base)):
            unit = unit_language(item)
        if unit is not None:
            runs = [(unit, item)]
        elif character_mode or (len(item.strip()) < 2 and not is_text(item)):
            out.append(item)
            continue
        elif tag is None or (detect_in_default_tagged and base(tag) == default_base):
            runs = detector.tagged(item)
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
