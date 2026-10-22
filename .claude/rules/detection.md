---
paths:
  - "addon/lib/mlang/detector.py"
  - "addon/lib/mlang/sequence.py"
  - "addon/lib/mlang/scripts.py"
  - "addon/lib/mlang/recognizers.py"
  - "addon/lib/mlang/dictionary.py"
  - "addon/lib/mlang/els.py"
  - "addon/globalPlugins/dialingo/context.py"
  - "harness/**"
  - "datasets/**"
  - "results/**"
  - "tests/test_detector.py"
  - "tests/test_sequence.py"
  - "tests/test_scripts.py"
  - "tests/test_context.py"
---

# Detection: rules, thresholds, and why

## Thresholds

- A scored clause switches when the top guess among the candidates (the default plus configured languages of the clause's script, renormalized) is foreign at 0.9.
- A foreign clause between default-language clauses of its sentence needs 0.98, judged between its language and the default alone.
- A clause the default's dictionary accepts whole needs the same 0.98 two-way bar.
- A confident guess stays default when its language's dictionary rejects every scored word, written as is and capitalized, and the default's knows one (`Detector.only_default_knows`): "slash enfr" closing an English sentence is Spanish at 0.99. Capitalized too, because the German dictionary rejects nouns written small ("extras optionen"); without that, German word pairs switched fell from 87.1 to 86.1 percent. As it stands, against the rule's absence: nothing changes with English as the default (acceptance, UI strings, Lingua French, Spanish, German, Italian, wrapped lines beside French, Spanish, German, and Swedish beside English); with French as the default, 2 of 1,000 Spanish word pairs stop switching, "calcula conservan", which went to English, and "personam supona".
- Dictionary-assisted switch: a guess at 0.5 or more switches when the default dictionary rejects a word and the guessed language's dictionary accepts every word. Such a clause may also be embedded without the 0.98 bar.
- Split between neighbours (`Detector.split_between_neighbours`): a clause of three or more words whose top foreign guess is under 0.9 counts as confident when the default holds at most 0.1 of the candidates' share, the free guess names the same language, its dictionary knows every word but at most one, which the default's dictionary knows, and every configured candidate has its dictionary installed. For Spanish beside Portuguese with an English word in it: "Haz clic para reaccionar con heart" is Spanish 0.68, Portuguese 0.30. Without the free-guess and dictionary guards, unconfigured neighbours were pulled in (Romanian sentences 64 to 114 per 1,000 with Spanish, Italian, and Portuguese configured).
- Headline (two or more words in capitals, or three or more all starting with a capital): every word counted and scored lowercased; switches only at 0.98, never on dictionaries alone. Two capitalized words are not a headline, because a name as its own clause ("Mario Moreno") would outvote the rest of its line.
- German noun: a capitalized word after the first counts as German when German or Luxembourgish is configured, the default dictionary rejects it, fastText on the word alone gives German 0.98, and an installed German dictionary knows it. Without the German dictionary filter, Title Case word pairs of neighbouring languages sent to German went from 45 to 105.
- Unconfigured language: a confident foreign guess is rechecked with no constraint. If the free guess names an unconfigured language and outranks the chosen one by a factor of 3, the clause stays default. A clause withheld this way is judged again with its whole sentence, which must pass the same check.
- Pure Han beside a Japanese or Korean default switches to Chinese only at 0.9. Cantonese (rows `zh_HK`, `zh_MO`, `yue`, compared as `yue`) takes pure Han only at 0.9 when a Mandarin row exists.

## Words and clauses

- Clause splits: quotes, commas, semicolons, colons, brackets, `!`, `?`, periods, spaced dashes, `--`, a hyphen spaced on both sides, slashes, newlines, and Spanish, Arabic, Devanagari, Armenian, Ethiopic, and full-width equivalents. Punctuation belongs to the clause before it, except `¿` and `¡`, which belong to the clause after.
- Inverted marks (`inverted_spans`, `Detector.inverted_language`): the clauses between a word-initial `¿` or `¡` and its closing `?` or `!`, with two letters or more and no sentence ending between (a newline, or a period before a space), take the one clause candidate in `INVERTING` (Spanish, Galician, Asturian, Aragonese), or the recognizer's pick among several, unscored and unpeeled, and count as switched for the line's agreement. Off when the default is in `INVERTING`. Untagged text only. The lone-word rule stands down for text holding such a span. With Spanish, French, Italian, and Portuguese configured, "¡Primer arrivoto!" is Italian at 0.59, "¿Dónde está?" Portuguese at 0.66, "¡Qué bien!" French at 0.65. Quotation marks were considered and not used: they follow the surrounding text's language, not the quoted text's. An abbreviation's period ends the span ("¡Hola, Sr. García!" is detected as before).
- No split: a period, comma, colon, or slash between digits; a slash against a word in capitals ("UNCTAD/WTO") or between pieces of one or two letters ("km/h").
- A word is letters with combining marks, apostrophes, hyphens, or ZWJ inside. Numbers, versions, paths, and identifiers are not words. Fewer than two letters is never guessed.
- A word repeated straight after itself in the text counts once (`unrepeated`), for scoring and for the one-word rules: "omg omg omg I love 9th wonder" was Dutch at 0.98 between English and Dutch, the Dutch dictionary knowing all three words; with one "omg" it is 0.58. Words that meet only once names are left out are not repeats ("Error de Fichero de Configuración" keeps both "de"). A word repeated alone ("cursos cursos") goes by the lone-word rule, so in a script with no Windows dictionary it stays default as the word alone does: against its absence, Lingua word pairs lose only such pairs (Persian beside an Arabic default 81.5 to 80.8 percent, Belarusian beside Russian 80.8 to 80.5); UI strings, sentences, single words, and wrapped lines unchanged.
- A capitalized word after the first is a name: not counted, not scored. A word in capitals under five letters is an abbreviation, never scored; longer ones are scored lowercased. Caseless scripts have neither.
- Short clauses (under two scored words) follow a neighbour of their sentence on a near-certain guess, or on any lean when every scored clause of the line leans that way. A short clause whose guess names no neighbour still follows the one neighbour whose dictionary knows every scored word where the default's rejects one: "Oye Pedro," is English at 0.92 to fastText, Pedro being a name. Measured on wrapped Lingua lines read alone, Spanish beside English: lines with a wrong letter 829 to 821 of 6,737, English unchanged. A sentence with no clause of two words is scored whole; a sentence with fewer than two words follows the line when all of the line leans that way. In scripts without spaces (Han, kana, Thai, Lao, Khmer, Burmese) a clause counts as one word, so these rules don't apply.
- Peeling: a foreign clause of four or more words has a default run of two or more words peeled off either end when the rest is still confidently foreign. Every length is tried and the longest taken, because fastText dips on two-word fragments ("Orthodox army" 0.89 between "Russian army" 0.999 and "the army" 0.98). A run containing a word the default dictionary rejects is never peeled ("the edge" is Swedish at 0.94 to fastText), nor is a run the clause's own language's dictionary spells whole ("dame ideas" opening a Spanish clause is English at 0.94). The latter, measured on wrapped Lingua lines read alone, Spanish beside English: lines with a wrong letter 829 to 774 of 6,737, 577 to 506 in context; UI strings' letters in their own language up 0.1 to 0.2 points per language; English unchanged everywhere.
- Preprocessing before scoring: curly apostrophes to straight, hyphens to spaces (fastText splits on whitespace only). Lowercasing everything was measured and rejected: it lost acceptance cases for a marginal dataset gain. Only headlines and words in capitals are lowercased (Title Case Spanish sentences went from 26 to 88 percent tagged, English still 0).

## Scripts

- Scripts per language come from `GetLocaleInfoEx(LOCALE_SSCRIPTS)`. Windows lists Latin only for untagged Serbian, Bosnian, Uzbek, and Azerbaijani, so Cyrillic is added for them unless the tag names a script. Windows lists Latin for `yue`; it is taken as Han.
- When the default also writes the run's script (Serbian beside Russian), the default leads the run's clause detection.
- A lone letter of a script the default doesn't write goes to the first configured language that writes it, else the first voice language, never the recognizer. It stays default when nothing writes the script, when the default's NVDA symbol table names it at every level, or when it is a modifier letter (々, ヽ). NVDA's English table names no Greek, Arabic, or Cyrillic letter.
- A foreign-script piece outside Han and kana with fewer than four letters and marks goes to the first of `script_options`, unguessed, as a lone letter does: "ogg" after a Russian file name was Italian at 0.99 between English and Italian, and pdf, png, gif, iso scattered across German, French, and Spanish. Marks count because Devanagari vowel signs are marks: counting letters alone sent Marathi single words beside Hindi from 72.9 to 57.5 percent. Against its absence: Serbian sentences beside a Russian default 90.3 to 92.6 percent (short Latin pieces go to Serbian, not English); Latin single words under Russian and Ukrainian defaults unchanged. Applying it to every one-word piece instead cost Italian single words under Russian 90.8 to 75.5.
- Digits written against a foreign piece's letters go with it (`scripts.attached_end`, `attached_start`), a hyphen allowed before them: "mp3", "x64", "3D", "COVID-19", "Ту-154". They used to go to the default voice, splitting the token between two voices. A number set apart by a space ("Windows 11") stays with the default.
- Kana means Japanese, hangul Korean; pure Han goes to Chinese before Japanese or Korean. A group holding a script the default doesn't write is foreign.

## Tags

- A tag that names no one language (a list such as WordReference's "es,en", which Chromium passes on as written; "mul"; "und") becomes the default before detection (`scripts.names_one_language`), so its text is detected as untagged. Kept, no row would match it and the default voice read everything under it.
- A tag whose language writes none of the text's scripts is dropped; in mixed-script text, only from the parts in scripts it doesn't write.
- In full mode, a tag in the default script is dropped from clauses that read as the default on a near-certain guess.
- Default-language tags are treated as untagged while `detectInDefaultTagged` is on.
- A tag for a row with detection off is replaced by the default before detection.

## Dictionaries (`dictionary.py`, `langpack.py`)

- Lone word (text that is one word, or a one-word clause no other rule settles): switches when every installed regional dictionary of the default rejects it and exactly one configured language's dictionary accepts it. The recognizer only picks between the accepting language and configured languages without a dictionary. Never: under four letters, in capitals, camelCase, or a small word the default knows capitalized ("paris"). Every region counts because en-US rejects "metres", which en-CA knows.
- A missing dictionary is looked for again every five minutes; a failed call is never cached as an answer.
- Installation: Windows capability `Language.Basic~~~<tag>~0.0.1.0`, region from `ResolveLocaleName`, installed by elevated `Add-WindowsCapability`. Presence is checked through the spell-checking API, because reading capability state also needs elevation.

## Model (`recognizers.py`)

- Shipped: `lid.176.q1m.ftz`, 17 MB, the full model quantized at cutoff 1,000,000 with character n-grams. The published 916 KB `lid.176.ftz` lacks n-grams and doesn't know "no", "Oui", "army", "Miguel". A 300,000 cutoff (5 MB) switched more English strings. The full model (139 MB in memory) and uncut quantization (19 MB file) were no better on any dataset. `MLANG_MODEL=<path>` points the harness at another model.
- Strict mode: ELS (`elscore.dll`) returns a ranked list with no scores; strict switches only when it names the same language as fastText.

## Lines read in context (`context.py`)

- A string is read in context when its first or last clause has fewer than two scored words, none of its clauses has two, or its edge guess was withheld for an unconfigured language (`Detector.undecided_edge`).
- The text two lines either side is fetched once per line as one range. The string is placed where the line's previous strings end, with only spaces and marks between (`sequence.LineStrings`), because browse mode splits lines at fields and inserts NVDA's own words.
- `Detector.in_context` detects the sentences the string cuts, at most 200 characters either side, never past a newline. Window runs are cached so arrowing back is free.
- Fetched by line because in Windows edit controls NVDA's paragraph is the wrapped line; a whole paragraph costs about 40 ms per 1,000 characters to detect.
- Cost: fetch 0.35 to 1.7 ms depending on control; detection median 3 ms, 99th percentile 20, on ARM under x64 emulation; about 30 percent of lines need context. Debug log shows both per line.

## Caret and typing (`context.py`)

- Wraps `speech.speakTextInfo` (character, word, and line units) and `speech.spellTextInfo`. The line is detected once and cached; the unit takes the run at its offset.
- A unit an application tagged with another language takes the language its line reads in under that tag (`Detector.verified`) at the unit's offset: an English message on a page tagged Spanish (Discord) drops the tag there, so its characters and words are read in English, voice and symbol names both. `UnitContext.tagged_language`; the filter asks `unit_language(text, tag)`.
- `getSpellingSpeech` and `getSingleCharDescription` get that language as locale when given none or only the default. Where NVDA would fall back to the English description for a non-default locale, the description is dropped.
- Typing echo wraps `speech.speakSpelling` and `speech.speakTypedCharacters`, using the keyboard layout's language (`keyboardHandler.getInputHkl`) when a row or voice speaks it, with an exact-dialect row preferred.

## Measuring

- Run before and after any rule change, and compare with `results/`. English lines and NVDA's English UI strings must not gain false switches.
- Commands: `harness/harness.py fasttext` (acceptance, 115/115), `harness/dataset_eval.py fasttext datasets/ui-strings fr,es,de,it,pt`, `harness/dataset_eval.py fasttext datasets/lingua fr,es` (add `--default <code>`, `--case title|upper|mixed`, `--show N`), `harness/line_eval.py fasttext datasets/lingua <default> <other>`. `ensemble` in place of `fasttext` measures strict mode; `HARNESS_NODICT=1` disables dictionary rules; `HARNESS_NODICT=de,it` hides only those languages' dictionaries (`results/dictionaries-fasttext.txt` is each language with and without its own).
- Results depend on installed Windows dictionaries; the saved runs had English, French, Spanish, German, and Italian.
- Many alternatives were measured and rejected; they are recorded in `KNOWN_GAPS.md` with their numbers.
