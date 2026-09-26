"""Language recognizers behind one interface.

constrained(text, languages) -> (language, probability among those languages) or None
free(text) -> (language, probability among all languages) or None

FastText is the recognizer that ships (the lid.176.q1m.ftz model in lib/models/, run through
fasttext-predict in lib/). Windows' Extended Linguistic Services is a second opinion with no dependencies;
the ensemble lets a foreign switch through only when both name the same language, the add-on's strict mode.
"""
import os

from .scripts import code

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(HERE, "..", "models", "lid.176.q1m.ftz")


class FastTextBackend:
    name = "fasttext"

    def __init__(self, path=None):
        import fasttext

        # MLANG_MODEL lets the harness evaluate another model file without touching the add-on.
        self.path = path or os.environ.get("MLANG_MODEL") or MODEL_PATH
        self.model = fasttext.load_model(self.path)
        self.cache = {}

    def probs(self, text):
        hit = self.cache.get(text)
        if hit is not None:
            return hit
        # A lone surrogate (text cut at a UTF-16 boundary) cannot be encoded to UTF-8, which predict needs.
        clean = text.replace("\n", " ").encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
        labels, ps = self.model.predict(clean, k=176)
        out = [(code(label[9:]), float(p)) for label, p in zip(labels, ps)]
        if len(self.cache) > 4096:
            self.cache.clear()
        self.cache[text] = out
        return out

    def constrained(self, text, languages):
        wanted = set(languages)
        pairs = [(lang, p) for lang, p in self.probs(text) if lang in wanted]
        if not pairs:
            return None
        total = sum(p for _, p in pairs) or 1.0
        lang, p = pairs[0]
        return (lang, p / total)

    def free(self, text):
        pairs = self.probs(text)
        return pairs[0] if pairs else None

    def probability(self, text, language):
        """The unconstrained probability of one language."""
        return next((p for lang, p in self.probs(text) if lang == language), 0.0)


class ELSBackend:
    """Windows language detection: a ranked list with no scores."""

    name = "els"

    def __init__(self):
        from . import els

        self.m = els
        self.service = els.get_service(els.GUID_LANGUAGE_DETECTION)
        self.cache = {}

    def ranked(self, text):
        hit = self.cache.get(text)
        if hit is not None:
            return hit
        langs = []
        try:
            for _, _, data in self.m.recognize(self.service, text):
                langs += [code(d) for d in data]
        except Exception:
            langs = []
        if len(self.cache) > 4096:
            self.cache.clear()
        self.cache[text] = langs
        return langs

    def constrained(self, text, languages):
        wanted = set(languages)
        for rank, lang in enumerate(self.ranked(text)):
            if lang in wanted:
                return (lang, 1.0 if rank == 0 else (0.9 if rank <= 2 else 0.5))
        return None

    def free(self, text):
        langs = self.ranked(text)
        return (langs[0], 1.0) if langs else None

    def probability(self, text, language):
        langs = self.ranked(text)
        return 1.0 if langs and langs[0] == language else 0.0


# Below the detector's lowest floors (DICTIONARY_FLOOR, SCRIPT_FLOOR), so a capped guess cannot switch.
STRICT_CAP = 0.49


class EnsembleBackend:
    """fastText's probability, capped below the floors unless ELS's first spoken language agrees."""

    name = "ensemble"

    def __init__(self, fasttext_backend=None):
        self.ft = fasttext_backend or FastTextBackend()
        self.els = ELSBackend()

    def constrained(self, text, languages):
        g = self.ft.constrained(text, languages)
        if g is None or g[1] <= STRICT_CAP:
            return g  # already at or under the cap: Windows' answer could not change it
        e = self.els.constrained(text, languages)
        if e is None or e[0] != g[0]:
            return (g[0], STRICT_CAP)
        return g

    def free(self, text):
        return self.ft.free(text)

    def probability(self, text, language):
        return self.ft.probability(text, language)


def make(name="fasttext", fasttext_backend=None):
    if name == "ensemble":
        return EnsembleBackend(fasttext_backend)
    if name == "els":
        return ELSBackend()
    return fasttext_backend or FastTextBackend()
