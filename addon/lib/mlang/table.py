"""The language table: per language, a synthesizer, a voice, and its parameters.

Stored as one JSON string in the add-on's configuration section, so NVDA's configuration profiles apply
to it like any other setting. No NVDA import here; the caller hands in `config.conf`.
"""
import json

from .scripts import base, code, normalize

CONFIG_SECTION = "multilanguage"
CONFSPEC = {
    "mode": "string(default=full)",
    "strict": "boolean(default=False)",
    "detectInDefaultTagged": "boolean(default=True)",
    "table": "string(default='')",
    # The synthesizer the language table hosts for the default language and everything not in the table;
    # empty until the table synthesizer is first selected, when it adopts the synthesizer in use.
    "defaultSynth": "string(default='')",
    # Whether a language with no row that the synthesizer in use cannot speak goes to the Windows voice
    # installed for it.
    "useWindowsVoices": "boolean(default=True)",
    # The language lock, set from NVDA's synth settings ring: empty for automatic switching, "default" for
    # all speech in the default language, or a row's language for all speech in that row's.
    "lock": "string(default='')",
}

# Settings a row can carry, in the order they are applied to a synthesizer: the voice first, because
# changing it resets parameters in some engines.
ROW_SETTINGS = ("voice", "variant", "rate", "rateBoost", "pitch", "inflection", "volume")
# What a row carries for NVDA rather than the synthesizer: the symbol level (none, some, most, all) for text
# in its language, None for NVDA's own setting; and whether detection may switch to its language. Kept out
# of the settings, so no synthesizer is sent them.
ROW_OPTIONS = ("symbolLevel", "detect")
ROW_KEYS = ("lang", "synth") + ROW_SETTINGS + ROW_OPTIONS


class Row:
    def __init__(self, lang, synth, symbolLevel=None, detect=None, **settings):
        self.lang = normalize(lang) or lang
        self.synth = synth
        self.settings = {k: v for k, v in settings.items() if k in ROW_SETTINGS and v is not None}
        try:
            self.symbolLevel = int(symbolLevel) if symbolLevel is not None else None
        except (TypeError, ValueError):
            self.symbolLevel = None
        # A row with detection off still speaks text tagged with its language, and the lock can still take it.
        self.detect = detect is None or bool(detect)

    @property
    def base(self):
        return base(self.lang)

    def get(self, key, default=None):
        return self.settings.get(key, default)

    def set(self, key, value):
        if value is None:
            self.settings.pop(key, None)
        else:
            self.settings[key] = value

    def key(self):
        """What must be applied to a synthesizer for this row; equal keys need no re-application."""
        return (self.synth,) + tuple(sorted(self.settings.items()))

    def to_dict(self):
        d = {"lang": self.lang, "synth": self.synth}
        d.update(self.settings)
        if self.symbolLevel is not None:
            d["symbolLevel"] = self.symbolLevel
        if not self.detect:
            d["detect"] = False
        return d

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict) or not d.get("lang") or not d.get("synth"):
            return None
        return cls(str(d["lang"]), str(d["synth"]), **{k: d.get(k) for k in ROW_SETTINGS + ROW_OPTIONS})

    def __repr__(self):
        level = f", symbolLevel={self.symbolLevel!r}" if self.symbolLevel is not None else ""
        detect = "" if self.detect else ", detect=False"
        return f"Row({self.lang!r}, {self.synth!r}, {self.settings!r}{level}{detect})"


class Table:
    """The rows for languages other than the default. The default language has no row: it is spoken by the
    synthesizer in use with its own settings."""

    def __init__(self, rows=()):
        self.rows = list(rows)

    # ------------------------------------------------------------ queries

    def detected(self):
        """The languages detection may switch to: those of the rows with detection on."""
        return [r.lang for r in self.rows if r.detect]

    def undetected(self):
        """The languages of the rows with detection off."""
        return [r.lang for r in self.rows if not r.detect]

    def row_for(self, lang, exact=False):
        """The row for a language: its own spelling first, then a row of the same language (code(): a
        Cantonese zh_HK row is not one for zh_TW), then any row of the same base language, so one Chinese row
        still takes all Chinese."""
        if not lang:
            return None
        wanted = lang.replace("-", "_").lower()
        for r in self.rows:
            if r.lang.replace("-", "_").lower() == wanted:
                return r
        if exact:
            return None
        c = code(lang)
        for r in self.rows:
            if code(r.lang) == c:
                return r
        b = base(lang)
        for r in self.rows:
            if r.base == b:
                return r
        return None

    def synths(self):
        out = []
        for r in self.rows:
            if r.synth not in out:
                out.append(r.synth)
        return out

    # ------------------------------------------------------------ edits

    def upsert(self, row):
        for i, r in enumerate(self.rows):
            if r.lang.lower() == row.lang.lower():
                self.rows[i] = row
                return
        self.rows.append(row)

    def remove(self, lang):
        self.rows = [r for r in self.rows if r.lang.lower() != lang.lower()]

    def rows_for_synth(self, synth):
        return [r for r in self.rows if r.synth == synth]

    # ------------------------------------------------------------ storage

    def to_json(self):
        return json.dumps({"rows": [r.to_dict() for r in self.rows]}, ensure_ascii=False)

    @classmethod
    def from_json(cls, text):
        if not text:
            return cls()
        try:
            data = json.loads(text)
        except ValueError:
            return cls()
        # Valid JSON of another shape (edited by hand, or written by another tool) is no table either.
        rows_data = data.get("rows") if isinstance(data, dict) else None
        if not isinstance(rows_data, list):
            return cls()
        rows = [r for r in (Row.from_dict(d) for d in rows_data) if r is not None]
        return cls(rows)

    def copy(self):
        return Table.from_json(self.to_json())

    def __eq__(self, other):
        return isinstance(other, Table) and self.to_json() == other.to_json()


def ensure_spec(conf):
    """Register the add-on's section with NVDA's configuration, whichever part of the add-on loads first."""
    if CONFIG_SECTION not in conf.spec:
        conf.spec[CONFIG_SECTION] = CONFSPEC


def load(conf):
    """The table from NVDA's configuration (`config.conf`)."""
    ensure_spec(conf)
    return Table.from_json(conf[CONFIG_SECTION]["table"])


def save(conf, table):
    conf[CONFIG_SECTION]["table"] = table.to_json()
    for listener in list(listeners):
        try:
            listener(table)
        except Exception:
            pass


# Callables told of a saved table: the driver rebuilds its guests, the plugin its detector.
listeners = []
