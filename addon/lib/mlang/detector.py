"""The language detector: clause and script rules over a pluggable recognizer.

Script first: a run in a script the default language does not write goes to the configured language of
that script with no recognizer involved. Then, in full mode, the text left in the default script is
guessed clause by clause among the default language and the configured ones written in its script, and a
run in a script several configured languages write is guessed clause by clause among those.
A tag an application supplied is distrusted when the text contradicts it, in both directions.

Languages are base codes ('fr') inside the detector; `tagged` returns the caller's configured spelling.
"""
import re
import unicodedata

from . import scripts as S

FLOOR = 0.9
EMBEDDED_FLOOR = 0.98
SCRIPT_FLOOR = 0.5
DICTIONARY_FLOOR = 0.5
UNCONFIGURED_MARGIN = 3.0
LONE_WORD_LETTERS = 4
# Arabic, Devanagari, Armenian, Ethiopic, and full-width marks as well as the Latin ones.
CLAUSE_ENDS = set('"“”«»,;:()!?.—–\n。，¿¡،؛؟।॥։።፣፤！？；：、')
SENTENCE_ENDS = set('.!?。\n؟।॥։።！？')
DASHES = set('—–')
JOINERS = set("'’-")
# Inside a word: the joiners Persian and the Indic scripts write between letters.
ZERO_WIDTH = set("\u200c\u200d")
SEPARATOR = "  "

MODE_OFF, MODE_SCRIPT, MODE_FULL = "off", "script", "full"
MODES = (MODE_OFF, MODE_SCRIPT, MODE_FULL)


# ---------------------------------------------------------------- word rules

def is_mark(c):
    return unicodedata.category(c).startswith("M")


def word(piece):
    first = next((i for i, c in enumerate(piece) if c.isalpha() or c.isdigit()), None)
    if first is None:
        return None
    last = max(i for i, c in enumerate(piece) if c.isalpha() or c.isdigit())
    # A vowel sign, virama, or haraka after the last letter is part of it: "है", "كِتَابٌ".
    while last + 1 < len(piece) and is_mark(piece[last + 1]):
        last += 1
    core = piece[first:last + 1]
    return core if all(c.isalpha() or c in JOINERS or c in ZERO_WIDTH or is_mark(c) for c in core) else None


_SPLIT = re.compile(r"[\s—–]+")


def words(text):
    return [w for w in (word(p) for p in _SPLIT.split(text)) if w]


def common_words(text):
    """Words that are not names or abbreviations: a capital word of fewer than five letters is an
    abbreviation in any position; a capitalized word after the first is a name unless shouted. A word of a
    script without case (Arabic, Hebrew, Devanagari) is neither."""
    out = []
    for index, w in enumerate(words(text)):
        capitals = any(c.isupper() for c in w) and not any(c.islower() for c in w)
        if capitals and len(w) < 5:
            continue
        if index > 0 and w[0].isupper():
            if capitals:
                out.append(w)
            continue
        out.append(w)
    return out


def headline(text):
    """Whether a clause is a headline, where case says nothing of names or abbreviations: two or more words
    in capitals ("MOST VAGY SOHA"), or three or more that all start with one ("Az Európai Autóipar Halála").
    Two capitalized words alone are as often a name ("Mario Moreno")."""
    ws = [w for w in words(text) if any(c.isupper() or c.islower() for c in w)]
    if len(ws) < 2 or not all(w[0].isupper() for w in ws):
        return False
    return len(ws) >= 3 or not any(c.islower() for w in ws for c in w)


def scored_words(text):
    """The words a clause is judged by: in a headline all of them, lowercased, since the recognizer reads
    capitals poorly; elsewhere the common ones."""
    if headline(text):
        return [w.lower() for w in words(text)]
    return common_words(text)


def is_text(piece):
    return sum(1 for c in piece if c.isalpha()) >= 2


def clauses(chunk):
    out = []
    sentence = 0
    start = 0
    previous = None
    n = len(chunk)

    def close(end):
        first = start
        while first < end and chunk[first].isspace():
            first += 1
        last = end
        while last > first and chunk[last - 1].isspace():
            last -= 1
        if first < last:
            out.append([first, last, sentence])

    i = 0
    while i < n:
        ch = chunk[i]
        dash = ch == "-" and previous == "-"
        spaced = (i + 1 == n) or chunk[i + 1].isspace()
        separates = spaced if (ch in DASHES or dash) else (ch in CLAUSE_ENDS)
        if separates:
            close(max(start, i - 1) if dash else i)
            if ch in SENTENCE_ENDS:
                sentence += 1
            start = i + 1
        previous = ch
        i += 1
    close(n)
    return out


def merge(runs):
    out = []
    for lang, text in runs:
        if not text:
            continue
        if out and out[-1][0] == lang:
            out[-1] = (lang, out[-1][1] + text)
        else:
            out.append((lang, text))
    return out


# ---------------------------------------------------------------- detector

class Detector:
    """
    backend: a recognizer (recognizers.py).
    default: the default voice's language, any spelling.
    configured: the languages with a voice configured, any spelling; the detector answers in these spellings.
    dictionary: a dictionary.Dictionary, or None for no spelling evidence.
    mode: off, script, or full.
    reader_words: lowercased strings that are the reader's own vocabulary, never scored.
    """

    def __init__(self, backend, default="en", configured=(), dictionary=None, mode=MODE_FULL, reader_words=()):
        self.backend = backend
        self.mode = mode
        self.dictionary = dictionary
        self.reader_words = set(reader_words)
        self.calls = 0
        self.configure(default, configured)

    def configure(self, default, configured, available=()):
        """default: the default voice's language; configured: the languages with a row; available: the
        languages the synthesizer's voices speak, the second tier for a script nobody configured."""
        self.default_tag = default
        self.default = S.code(default)
        self.default_script = S.primary_script(default)
        self.spelling = {}  # base code -> configured spelling, the default first
        for tag in [default] + list(configured):
            self.spelling.setdefault(S.code(tag), S.normalize(tag))
        self.spoken = list(self.spelling)
        # Languages of the default script are the clause candidates; the others are reached by script.
        self.script_languages = {}
        for code in self.spoken:
            for script in S.scripts_of(self.spelling[code]):
                self.script_languages.setdefault(script, []).append(code)
        self.clause_candidates = [c for c in self.spoken if self.default_script in S.scripts_of(self.spelling[c])]
        if self.default not in self.clause_candidates:
            self.clause_candidates.insert(0, self.default)
        # The voices' languages, by script, for scripts no configured language writes.
        self.voice_spelling = {}
        self.voice_languages = {}
        for tag in available:
            if not tag:
                continue
            code = S.code(tag)
            if code in self.spelling or code in self.voice_spelling:
                continue
            self.voice_spelling[code] = S.normalize(tag)
            for script in S.scripts_of(tag):
                if script not in self.script_languages:
                    self.voice_languages.setdefault(script, []).append(code)
        self.foreign_scripts = frozenset(
            s for s in set(self.script_languages) | set(self.voice_languages) if s != self.default_script
        )
        # Detectors for the clauses of a foreign-script piece, by the piece's pick and its script's languages.
        self._within = {}

    # ------------------------------------------------------------ recognizer

    def is_near_certain(self, scored, language):
        """Whether `scored`, judged between `language` and the default alone, is in `language` at the embedded floor."""
        if not is_text(scored):
            return False
        self.calls += 1
        g = self.backend.constrained(self._scored(scored), [self.default, language])
        return bool(g) and g[0] == language and g[1] >= EMBEDDED_FLOOR

    def _scored(self, text):
        """The text as the recognizer sees it: straight apostrophes, and hyphens as spaces, since fastText
        splits on whitespace alone and knows "vas" and "tu" where it may not know "vas-tu"."""
        return text.replace("’", "'").replace("-", " ")

    def is_embedded(self, text, language):
        """Whether a foreign clause beside default-language clauses of its sentence keeps its tag: the
        near-certain two-way guess, or the two dictionaries agreeing it is foreign. The embedded floor
        exists for English clauses mistaken for another language, which the English dictionary spells."""
        if self.dictionaries_decide(text, language):
            return True
        return self.is_near_certain(" ".join(scored_words(text)), language)

    def survives_dictionaries(self, text, language):
        """A clause the default dictionary accepts whole switches only if the guess's own dictionary accepts it
        too and the guess is near certain between the two languages; a clause the default rejects a word of stands."""
        if self.dictionary is None:
            return True
        scored = self._scored(" ".join(scored_words(text)))
        if self.dictionary.rejects_a_word(scored, self.default_tag) is not False:
            return True
        if self.dictionary.rejects_a_word(scored, self.spelling.get(language, language)) is True:
            return False
        return self.is_near_certain(scored, language)

    def hypothesis(self, text, counting_names=False, candidates=None):
        ws = words(text) if counting_names else scored_words(text)
        scored = self._scored(" ".join(ws))
        if not is_text(scored):
            return None
        self.calls += 1
        candidates = candidates or self.clause_candidates
        guess = self.backend.constrained(scored, candidates)
        if guess is None:
            return None
        lang, conf = guess
        if conf >= FLOOR and lang != self.default:
            # A confident foreign guess that is the constraints' doing: left free, the recognizer prefers a
            # language nobody configured (Italian forced to Spanish). fastText's free guess on a short
            # clause is rarely confident in itself, so it is enough that the unconfigured language
            # outranks the chosen one clearly. A sibling edging it out (Galician over
            # Spanish on a word pair) is not that: Italian over Spanish on "Dio mi l'ha dato" is 0.73 to 0.005.
            free = self.backend.free(scored)
            if free and free[0] not in self.spoken and free[0] != lang:
                chosen = self.backend.probability(scored, lang)
                if free[1] >= FLOOR or free[1] > UNCONFIGURED_MARGIN * chosen:
                    return None
        return guess

    def dictionaries_decide(self, text, language):
        """Whether the spelling dictionaries alone call `text` foreign: the default language's rejects a
        word of it and the guessed language's accepts every word. Both dictionaries must be installed.
        fastText scores "Dieu me la donne" at 0.76, short of the floor, and the two dictionaries settle
        what the recognizer cannot."""
        if self.dictionary is None:
            return False
        scored = self._scored(" ".join(scored_words(text)))
        if self.dictionary.rejects_a_word(scored, self.default_tag) is not True:
            return False
        return self.dictionary.rejects_a_word(scored, self.spelling.get(language, language)) is False

    def switches(self, text, guess):
        """Whether a scored clause's guess switches it: a confident foreign guess that survives the
        dictionaries, or a leading foreign guess the dictionaries decide for."""
        if not guess or guess[0] == self.default:
            return False
        lang, conf = guess
        if headline(text):
            # Names are scored in a headline, so it switches only near certain, never on the dictionaries alone.
            return conf >= EMBEDDED_FLOOR and self.survives_dictionaries(text, lang)
        if conf >= FLOOR:
            return self.survives_dictionaries(text, lang)
        return conf >= DICTIONARY_FLOOR and self.dictionaries_decide(text, lang)

    def foreign(self, text):
        h = self.hypothesis(text)
        return h[0] if self.switches(text, h) else None

    def is_default(self, text, counting_names=False, candidates=None):
        h = self.hypothesis(text, counting_names, candidates)
        return bool(h) and h[1] >= FLOOR and h[0] == self.default

    # ------------------------------------------------------------ entry points

    def tagged(self, text):
        """Untagged text as (language or None, text) runs, languages in their configured spelling."""
        if self.mode == MODE_OFF or not text or not any(c.isalpha() for c in text):
            return [(None, text)]
        if text.strip().lower() in self.reader_words:
            return [(None, text)]
        out = []
        for lang, piece in self.by_script(text):
            if lang == self.default:
                out.append((None, piece))
            elif lang is not None or self.mode != MODE_FULL:
                out.append((lang, piece))
            else:
                out += self.by_clause(piece)
        return merge([(self.tag_of(l) if l else None, t) for l, t in out])

    def verified(self, text, tag):
        """Text an application tagged `tag`, as it is read: the tag dropped and the text detected as untagged
        where it is in a script the tag's language is not written in, so "PDF" keeps an English tag and the
        Russian around it on a Russian page wrongly declared English does not; in full mode, the tag dropped
        too from each clause that reads as the default language. Runs are (language or None, text), where
        the language is `tag` itself where it is kept."""
        if self.mode == MODE_OFF or not text:
            return [(tag, text)]
        tag_base = S.code(tag)
        tag_scripts = S.scripts_of(tag)
        if is_text(text) and not self._holds_letter(text, tag_scripts):
            return self.tagged(text)
        runs = []
        for piece, foreign in self._by_tag_script(text, tag, tag_scripts):
            if foreign:
                runs += self.tagged(piece)
            elif self.mode != MODE_FULL or S.primary_script(tag) != self.default_script or tag_base == self.default:
                runs.append((tag, piece))
            else:
                runs += self.by_clause_against_tag(piece, tag, tag_base)
        return merge(runs)

    def _by_tag_script(self, text, tag, tag_scripts):
        """(piece, foreign) for tagged text: foreign where the piece holds no script the tag's language writes,
        or a script of the CJK family it does not (kana under a Chinese tag). A lone borrowed letter is not."""
        if "Latn" in tag_scripts and not S.may_leave_latin(text):
            return [(text, False)]
        known = self.foreign_scripts | set(tag_scripts) | {self.default_script}
        out = []
        for scripts_here, start, end in S.segments(text, S.primary_script(tag), known, tag_scripts):
            piece = text[start:end]
            foreign = (
                scripts_here is not None
                and S.is_text(piece)
                and (not (scripts_here & tag_scripts) or bool((scripts_here & S.CJK) - tag_scripts))
            )
            if out and out[-1][1] == foreign:
                out[-1] = (out[-1][0] + piece, foreign)
            else:
                out.append((piece, foreign))
        return out

    def _holds_letter(self, text, scripts):
        if "Latn" in scripts and any(c.isalpha() and ord(c) < 0x300 for c in text):
            return True
        return any(s != "other" for s, _, _ in S.letter_runs(text, scripts))

    # ------------------------------------------------------------ script mode

    def by_script(self, text):
        """(base language or None, piece) runs by script alone; None is the default script, and the default's own
        code a piece in another script it writes that its clause pass settled as the default."""
        if self.default_script == "Latn" and not S.may_leave_latin(text):
            return [(None, text)]
        runs = []
        known = self.foreign_scripts | {self.default_script}
        for scripts_here, start, end in S.segments(text, self.default_script, known, S.scripts_of(self.default_tag)):
            piece = text[start:end]
            if scripts_here is None or not S.is_text(piece):
                runs.append((None, piece))
                continue
            lang = self.language_for(scripts_here, piece)
            if lang is None:
                runs.append((None, piece))
                continue
            last = max(i for i, c in enumerate(piece) if c.isalpha()) + 1
            # A mark after the last letter (a virama, a separate accent) belongs to that letter.
            while last < len(piece) and unicodedata.category(piece[last]).startswith("M"):
                last += 1
            # The default's code, not None, where its script's own clause pass settled it: tagged() then
            # leaves it with the default voice without scoring it again.
            runs += self.within_script(scripts_here, piece[:last], lang)
            runs.append((None, piece[last:]))
        return merge(runs)

    def within_script(self, scripts_here, piece, lang):
        """A foreign-script piece, in full mode, clause by clause among the configured languages of its
        script, as text in the default script is among the default and its own: the piece's pick stands in
        for the default, so a Ukrainian sentence after a Russian one in English prose switches to Ukrainian
        where the piece as a whole reads Russian. The default leads when it writes the script too (Serbian in
        Cyrillic beside Russian). Words run together in Han and kana, so a piece in those is left whole."""
        if self.mode != MODE_FULL or "other" in scripts_here or scripts_here & S.CJK:
            return [(lang, piece)]
        options = []
        for script in scripts_here:
            for code in self.script_languages.get(script, ()):
                if (code != self.default or lang == self.default) and code not in options:
                    options.append(code)
        if lang not in options or len(options) < 2:
            return [(lang, piece)]
        key = (lang, tuple(options))
        sub = self._within.get(key)
        if sub is None:
            others = [self.spelling[c] for c in options if c != lang]
            sub = Detector(self.backend, self.spelling[lang], others, self.dictionary, MODE_FULL, self.reader_words)
            # The piece's script, not the lead's primary one: Serbian's is Latin, and Russian writes no Latin.
            sub.clause_candidates = [lang] + [c for c in options if c != lang]
            self._within[key] = sub
        before = sub.calls
        runs = sub.by_clause(piece)
        self.calls += sub.calls - before
        return [(found or lang, text) for found, text in runs]

    def language_for(self, scripts_here, piece):
        """The language to speak a foreign-script piece in: the one configured language of its script, the
        recognizer's confident pick among several, its free guess when nobody configured the script."""
        if "other" in scripts_here:
            return self._free_guess(piece, scripts_here)
        options = []
        for table in (self.script_languages, self.voice_languages):
            for script in scripts_here:
                for code in table.get(script, ()):
                    if code not in options:
                        options.append(code)
            if options:
                break
        if scripts_here & S.CJK:
            if "Hira" in scripts_here or "Kana" in scripts_here:
                options = [c for c in options if "Hira" in S.scripts_of(self.tag_of(c))] or options
            elif "Hang" in scripts_here:
                options = [c for c in options if "Hang" in S.scripts_of(self.tag_of(c))] or options
            else:
                # Pure Han: a Chinese voice before a Japanese or Korean one.
                order = {c: i for i, c in enumerate(list(self.spoken) + list(self.voice_spelling))}
                options.sort(key=lambda c: (S.scripts_of(self.tag_of(c)) != {"Hani"}, order.get(c, 999)))
        if self.default in options:
            if len(options) == 1:
                return None
            if scripts_here & S.CJK:
                # Han the default writes too (Chinese beside a Japanese or Korean default): switched only on a
                # near-certain guess, since kanji-only headings and names are common in Japanese.
                self.calls += 1
                g = self.backend.constrained(piece, options)
                return g[0] if g and g[0] != self.default and g[1] >= FLOOR else None
            # Another script the default writes: its clauses are detected with the default leading.
            return self.default
        if not options:
            return self._free_guess(piece, scripts_here)
        if len(options) == 1:
            return options[0]
        self.calls += 1
        g = self.backend.constrained(piece, options)
        if g and g[1] >= SCRIPT_FLOOR:
            return g[0]
        return options[0]

    def tag_of(self, code):
        return self.spelling.get(code) or self.voice_spelling.get(code) or code

    def _free_guess(self, piece, scripts_here):
        self.calls += 1
        g = self.backend.free(piece)
        if not g or g[0] == self.default:
            return None
        # By the text's script: many languages share Latin, few share another script. The guess's own
        # script would not do, since Windows knows no script for some of the recognizer's codes (arz, yue).
        latin = "Latn" in scripts_here or any(s == "Latn" for s, _, _ in S.letter_runs(piece, ("Latn",)))
        floor = FLOOR if latin else SCRIPT_FLOOR
        # Tagged whether or not any voice can speak it: NVDA's "report when switching to
        # language is not supported" setting then names the language before the attempt, which beats
        # silence from a voice handed a script it cannot read.
        if g[1] < floor:
            return None
        return g[0]

    # ------------------------------------------------------------ full mode

    def by_clause(self, text):
        lone = self.lone_word(text)
        if lone:
            return [(lone, text)]
        runs = []
        for index, chunk in enumerate(text.split(SEPARATOR)):
            if index > 0:
                runs.append((runs[-1][0] if runs else None, SEPARATOR))
            runs += self.clause_runs(chunk)
        return merge(runs)

    def lone_word(self, text):
        """The language of text that is one word alone, as a button or a link is, or None. The recognizer
        cannot tell one word, so the dictionaries do: the default's rejects it in every installed region and
        exactly one configured language's accepts it. Against a configured language with no dictionary the
        recognizer arbitrates, but never against the default, whose dictionary has spoken: it calls "Cancelar"
        English at 0.89 and "fraser" at 0.60. "Keresés" beside an English default is Hungarian; "Spotify",
        which the English dictionary knows, is not, nor "paris", which it knows capitalized, nor "numLock"."""
        if self.dictionary is None:
            return None
        ws = words(text)
        if len(ws) != 1 or len(ws[0]) < LONE_WORD_LETTERS or not any(c.islower() for c in ws[0]):
            return None
        w = ws[0]
        if any(a.islower() and b.isupper() for a, b in zip(w, w[1:])):
            return None  # an identifier
        scored = self._scored(w)
        if self.dictionary.rejects_everywhere(scored, self.default_tag) is not True:
            return None
        if w.islower() and self.dictionary.rejects_a_word(scored.capitalize(), self.default_tag) is False:
            return None  # a name, written small
        accepting, unknown = [], []
        for code in self.clause_candidates:
            if code != self.default:
                verdict = self.dictionary.rejects_a_word(scored, self.spelling[code])
                if verdict is False:
                    accepting.append(code)
                elif verdict is None:
                    unknown.append(code)
        if len(accepting) != 1:
            return None
        if not unknown:
            return accepting[0]
        self.calls += 1
        g = self.backend.constrained(scored, accepting + unknown)
        return accepting[0] if g and g[0] == accepting[0] and g[1] >= DICTIONARY_FLOOR else None

    def clause_runs(self, chunk):
        if not any(c.isalpha() for c in chunk):
            return [(None, chunk)]
        cls = clauses(chunk)
        langs = [None] * len(cls)
        guesses = {}

        def guess(i):
            if i not in guesses:
                guesses[i] = self.hypothesis(chunk[cls[i][0]:cls[i][1]])
            return guesses[i]

        scored = set()
        for i, (s, e, _) in enumerate(cls):
            if len(scored_words(chunk[s:e])) >= 2:
                scored.add(i)
                g = guess(i)
                if self.switches(chunk[s:e], g):
                    langs[i] = g[0]
        leanings = {guess(i)[0] for i in scored if guess(i)}
        agreed = None
        if len(leanings) == 1:
            leaning = next(iter(leanings))
            if leaning in self.spoken and leaning != self.default and any(langs[i] == leaning for i in scored):
                agreed = leaning
        if agreed:
            # A clause whose hypothesis was withheld, because a language no row speaks outranked the
            # constrained pick, stays untagged rather than following the line.
            for i in scored:
                if langs[i] is None and guess(i):
                    langs[i] = agreed
        # A foreign clause beside a scored default clause of its sentence, with no foreign neighbor, is embedded
        # in default-language speech and keeps its tag only at the embedded floor.
        for i in sorted(scored):
            if langs[i] is None:
                continue
            neighbors = [j for j in (i - 1, i + 1) if 0 <= j < len(cls) and cls[j][2] == cls[i][2]]
            embedded = all(langs[j] is None for j in neighbors) and any(j in scored for j in neighbors)
            if embedded and not self.is_embedded(chunk[cls[i][0]:cls[i][1]], langs[i]):
                langs[i] = None
        settled = False
        while not settled:
            settled = True
            for i in range(len(cls)):
                if langs[i] is not None or i in scored:
                    continue
                neighbors = [langs[j] for j in (i - 1, i + 1) if 0 <= j < len(cls) and cls[j][2] == cls[i][2] and langs[j]]
                if not neighbors:
                    continue
                g = guess(i)
                if not g or g[0] not in self.spoken:
                    continue
                if g[0] not in neighbors:
                    continue
                # A near-certain guess, the line's agreed language, or, as for a scored clause, a leading
                # guess the dictionaries decide for: "demain" between two commas is French at 0.62, and
                # the English dictionary rejects it where the French one knows it.
                joins = g[1] >= FLOOR or g[0] == agreed
                if not joins and g[1] >= DICTIONARY_FLOOR:
                    joins = self.dictionaries_decide(chunk[cls[i][0]:cls[i][1]], g[0])
                if joins:
                    langs[i] = g[0]
                    settled = False
        runs = []
        cursor = 0
        for i, (s, e, _) in enumerate(cls):
            runs.append((runs[-1][0] if runs else None, chunk[cursor:s]))
            if langs[i]:
                runs += self.peeled(chunk[s:e], langs[i])
            else:
                runs.append((None, chunk[s:e]))
            cursor = e
        runs.append((runs[-1][0] if runs else None, chunk[cursor:]))
        return runs

    def peeled(self, clause, language):
        return self.split(clause, language) or [(language, clause)]

    def split(self, clause, language):
        ws = clause.split(" ")
        if len(ws) < 4:
            return None

        def default_end(end):
            # The longest end that reads as the default. Stopping at the first length that does not
            # suits a recognizer whose confidence grows with the text; fastText dips on a two-word
            # fragment ("Orthodox army" scored 0.89 between "Russian army" at 0.999 and "the army" at 0.98),
            # so every length is tried and the rest is still held to the foreign and embedded floors.
            # Two words at least, counted as words: "mesterei 😂" is one, and a lone word is never judged.
            found = None
            for length in range(2, len(ws) - 1):
                if len(words(end(length))) >= 2 and self.is_default(end(length)):
                    found = length
            return found

        def rest(text):
            return language if self.foreign(text) == language and self.is_embedded(text, language) else None

        length = default_end(lambda n: " ".join(ws[len(ws) - n:]))
        if length:
            head = " ".join(ws[:len(ws) - length])
            found = rest(head)
            if found:
                return [(found, head), (None, " " + " ".join(ws[len(ws) - length:]))]
        length = default_end(lambda n: " ".join(ws[:n]))
        if length:
            tail = " ".join(ws[length:])
            found = rest(tail)
            if found:
                return [(None, " ".join(ws[:length]) + " "), (found, tail)]
        return None

    # ------------------------------------------------------------ tag distrust

    def by_clause_against_tag(self, text, tag, tag_base):
        """The tag dropped from each clause of two or more words that reads as the default language on a
        near-certain guess, names counted: for a tagged clause the question is whether it is not the tag's
        language, and a name is evidence of that."""
        candidates = list(self.clause_candidates)
        if tag_base not in candidates:
            candidates.append(tag_base)
        runs = []
        carried = tag
        for index, chunk in enumerate(text.split(SEPARATOR)):
            if index > 0:
                runs.append((carried, SEPARATOR))
            cursor = 0
            for s, e, _ in clauses(chunk):
                runs.append((carried, chunk[cursor:s]))
                clause = chunk[s:e]
                kept = len(words(clause)) < 2 or not self.is_default(clause, counting_names=True, candidates=candidates)
                carried = tag if kept else None
                runs.append((carried, clause))
                cursor = e
            runs.append((carried, chunk[cursor:]))
        return merge(runs)
