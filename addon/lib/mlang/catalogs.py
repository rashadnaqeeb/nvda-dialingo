"""Strings of NVDA's and the add-on's translation catalogs in a language other than NVDA's own, for the synth
settings ring while the language lock holds a row: its words are spoken by that row's voice, which reads
another language's poorly.

A string is traced back to its original through the catalog of the language in use, then looked up in the
other language's catalog. No NVDA import here; the caller hands in the catalogs, msgid -> msgstr dicts as
gettext keeps them, with a context joined to its msgid by "\\x04".
"""

SEPARATOR = "\x04"


def catalog(translation):
    """A gettext translation's catalog: empty for none, or for one without a catalog (NVDA's English)."""
    return getattr(translation, "_catalog", None) or {}


class Catalog:
    """One domain's catalogs. current: the language in use, which the strings arrive in; target: the language
    wanted; english: whether that is English, which has no catalog and is the originals themselves."""

    def __init__(self, current, target, english=False):
        self.current = current
        self.target = target
        self.english = english
        self._reverse = None

    def originals(self, text):
        """The keys `text` is the translation of in the language in use, or None."""
        if self._reverse is None:
            reverse = {}
            for key, value in self.current.items():
                if key and isinstance(key, str) and isinstance(value, str) and value:
                    reverse.setdefault(value, []).append(key)
            self._reverse = reverse
        return self._reverse.get(text)

    def get(self, text, context=None):
        """`text` in the target language, or None where this domain does not know it."""
        keys = self.originals(text)
        if keys and context:
            # The key in the context asked for first: "Volume" is both a label and a synth setting.
            keys = sorted(keys, key=lambda k: not k.startswith(context + SEPARATOR))
        if self.english:
            return keys[0].rpartition(SEPARATOR)[2] if keys else None
        if not keys:
            # Not translated in the language in use, so it is the original.
            keys = ([context + SEPARATOR + text] if context else []) + [text]
        for key in keys:
            found = self.target.get(key)
            if found:
                return found
        return None


class Words:
    """A string in the target language from the first catalog that knows it, else as it came."""

    def __init__(self, *catalogs):
        self.catalogs = catalogs

    def __call__(self, text, context=None):
        if not isinstance(text, str) or not text:
            return text
        for c in self.catalogs:
            found = c.get(text, context)
            if found:
                return found
        return text
