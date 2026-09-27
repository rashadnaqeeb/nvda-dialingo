# NVDA multilanguage add-on

An NVDA add-on that reads text in the language it is written in, even when nothing tags it, and speaks each language with the synthesizer, voice, and parameters the user chose for it, switching synthesizers mid-utterance when needed.

This file is the technical account: how the add-on works, how it was measured, and how to build and test it. For users:

- `GETTING_STARTED.txt` is the beta testers' introduction.
- `addon/doc/en/readme.md` is the user guide shipped inside the add-on, rendered to HTML at build time and opened from NVDA's Add-on Store.

`KNOWN_GAPS.md` lists the problems found and deliberately left alone, with the reason for each.

The project is in beta, version 0.11, targeting NVDA 2026.1 and later (tested on 2026.2), which runs 64-bit Python 3.13. The add-on depends on nothing but NVDA and the voices the user installs: the recognizer, its model, and the synthesizer hosting are all in the package.

## Design goals

- Detect the language of untagged text clause by clause, so a French sentence inside English prose is read by the French voice, while a French name inside an English sentence is not.
- Never switch on the screen reader's own words, labels, names, abbreviations, or single characters. A wrong switch is heard on every button; a missed switch is only a mispronunciation, so the rules lean toward not switching. A button in another language switches only on the spelling dictionaries' word.
- Handle other writing systems by script: Arabic, Cyrillic, Han, and the rest go to the voice for that script's language without guessing, and where several configured languages share a script (Russian, Ukrainian, and Bulgarian in English text), that text is detected clause by clause among them.
- Distrust an application's language tag when the text contradicts it, in both directions: a Russian tag on Latin text, and a French tag on an English results page.
- Let the user pick a synthesizer, voice, rate, pitch, and volume per language, and switch between synthesizers mid-utterance. NVDA cannot do this on its own.
- Stay inside the speech path's latency budget: well under a millisecond per line on ordinary text.

## Architecture

The add-on has two parts, each usable without the other.

- A global plugin, `addon/globalPlugins/multilanguage/`, which detects languages, applies per-language parameters, and owns the settings panel.
- A synthesizer driver, `addon/synthDrivers/languageTable.py`, which hosts NVDA's other synthesizer drivers and routes each language to the one configured for it.

Most of the logic lives in `addon/lib/mlang/`, a library with no NVDA imports at module level, so the unit tests and the measurement harness run the same code on plain Python.

### The speech filter

The plugin registers on `speech.extensions.filter_speechSequence`, which runs at the top of `speech.speak()`, synchronously on the calling thread, before symbol processing and before NVDA applies its own language commands. Say all delivers one reading chunk per call. Each sequence passes through three steps, each wrapped so a failure logs and passes the sequence on unchanged:

1. Detection (`mlang/sequence.py` over `mlang/detector.py`). Untagged strings are detected; tagged strings are checked against their tag; `LangChangeCommand` objects are inserted around the runs that get a language. Spelled characters (character mode) and the reader's own words are left alone.
2. Prosody (`mlang/prosody.py`). On the synthesizer in use, a row for that synthesizer wraps its language's runs in rate, pitch, and volume commands. `RateCommand(offset=...)` means "configured rate plus offset" and every major driver applies it in-stream, so a slower French row on Eloquence needs no second synthesizer. Any prosody command NVDA itself put inside the run is rebased on the row's offset: a capital letter's pitch change of +30 in a run at +10 becomes +40, and the reset after it becomes +10.
3. Voice dictionaries (`mlang/voicedict.py`). NVDA loads only the current voice's dictionary and applies it to everything. A row's voice has its own file among NVDA's voice dictionaries (the same file NVDA would load if that voice were current), and its entries are applied to the runs in that row's language, ahead of NVDA's own dictionaries. Files are reread when they change.

NVDA's own language reporter, `getSpeechSequenceWithLangs`, is moved behind the plugin's filter, so "report language changes" names the detected languages. NVDA discards every `LangChangeCommand` unless automatic language switching is on, so the plugin turns that setting on whenever detection is on or rows apply to the synthesizer in use.

The recognizer's model (17 MB) loads on a background thread at startup. Until it is in, speech passes through undetected, so the first utterance is not held back.

### Characters and words at the caret

A single character or word cannot be detected on its own, and the detector never guesses one. NVDA hands the speech functions the unit alone, with no line or offset, so `globalPlugins/multilanguage/context.py` wraps `speech.speakTextInfo` for character and word units and `speech.spellTextInfo` for single words. The wrapper expands the unit's TextInfo to its line, detects the line once (kept for the next unit on the same line), finds the run at the unit's offset, and holds that language while the wrapped call runs.

Inside that window, `getSpellingSpeech` and `getSingleCharDescription` receive the language as their locale when they were given none, or when they were given only the default language (a page's `lang="en"`, which most pages carry), so a character is both spoken and described in its line's language. Text an application tagged with another language keeps its tag. Arrowing through "Bonjour" in a French sentence therefore reads each letter, and the word, in the French voice.

### The language table synthesizer

NVDA speaks through one synthesizer object at a time. A language assigned to a different engine than the one in use needs the `languageTable` driver, which hosts real NVDA drivers as guests.

- The host. When the driver is first selected, it adopts the synthesizer in use as its default, stored as `defaultSynth` in the add-on's config and changeable in the panel. The host speaks the default language and everything without a row. The driver's `supportedSettings` are the host's and every setting is forwarded: standard ones through explicit properties, the rest (Eloquence's head size, OneCore's rate boost) through `__getattr__` and `__setattr__`. NVDA's voice settings and the synth settings ring therefore still show the host's voice, rate, and options.
- Settings storage. The driver keeps no settings of its own. Its `initSettings`, `loadSettings`, and `saveSettings` read and write the host's own config section. NVDA's inherited versions would keep a copy under the driver's name and refill the host from it on every load, and since NVDA never writes a value equal to a setting's default, a missing key comes back as that default (50 for every numeric setting). That would set Eloquence to volume 50 and roughness 50 on every load. NVDA's synth settings ring writes to the driver's own section, which nothing reads, so a change made through the driver outside NVDA's settings dialog is also written to the host's section at once; a configuration profile switch reloads the host from there and would otherwise put the old value back. Inside the dialog nothing is written before OK, so Cancel still undoes it.
- Host values versus row values. A snapshot of the host's own values serves as the default row. A row on the host's own engine leaves its values on the instance until the next default piece, so reads of the driver's settings, and its `language`, come from the snapshot, never from whatever row ran last. Otherwise the settings ring would store a row's rate as the user's, and with "trust voice's language" on, a row's language would become the default and capture all speech. The snapshot covers every setting the host saves, not only those a row carries, because a row's variant can reset the rest (Eloquence copies a preset voice, head size and roughness included); the default row puts them back. After a profile switch the snapshot takes the numbers and switches as stored in the host's section, since eSpeak, busy speaking, reports its old values until its queue is done. A row whose language is the default's in another dialect is ignored, since NVDA opens every utterance with the default's tag.
- Guests. Guests are instances of NVDA's driver classes, created with `initSettings()` and detached from NVDA's config-save hook, so a row's parameters never overwrite the user's settings for that synthesizer used on its own. Creating a driver instance repoints the synth settings ring and the voice dictionary; both are restored afterwards (`mlang/hosts.py`). `speechDictHandler.loadVoiceDict` is wrapped so a load for the language table loads the host's dictionary for the host's own voice, not a row voice still on the instance.
- Selection. The user never selects the driver. `mlang/policy.py` decides when it is needed: a saved row names another engine than the one speaking, or Windows voices are in use and some installed Windows voice speaks a language the engine cannot. Just after the default synthesizer is changed, the engine judged is the new one, loaded for the question if nothing has it yet. The panel and the plugin's startup switch to it or back to the default synthesizer accordingly. On the way back, the driver writes the host's current values into the host's own section, so nothing heard changes. Its `check()` lists it in NVDA's synthesizer dialog only while it is needed or already selected.
- Failure. An empty or broken table falls back to NVDA's default synthesizer order, so the driver always speaks.

### Scheduling pieces across guests

`mlang/scheduler.py` cuts each utterance and plays it across guests.

- Cutting. An utterance is cut at every language command that changes the row. A language with a row is spoken by that row with its language commands removed, since the row's voice is the user's choice for it. Anything else goes to the default row with its commands kept, so the host switches language by itself where it can, as it would without this driver. Command-only pieces merge into a neighbor.
- Indexes. Every piece ends in a private index marker, and every NVDA index inside it is remapped to a private one. The driver re-emits NVDA's indexes and done-speaking under its own name, since NVDA's speech manager only honors notifications from the current synthesizer; that keeps caret tracking and say all working.
- Seams. Consecutive pieces on the same guest and row are sent without waiting, so single-language speech loses nothing. A change of row on the same guest (Eloquence English at one rate, Eloquence French at another) waits for the previous piece's marker, since an engine reports a mark once the text before it is synthesized. A change of guest also waits for the previous guest's done notification, because Eloquence reports marks when audio is queued rather than played and the next guest would otherwise talk over its tail. Eloquence signals done about 0.3 seconds after its audio ends, so seams away from Eloquence carry that pause. A guest that never reports done is freed at its last marker. A row that changes the voice on the same guest waits for done too, because Vocalizer stops its audio to change voice and SAPI 5 rebuilds its engine. SAPI 5 and the Microsoft Speech Platform, which is built on it, report the end of a stream when synthesis ends, with audio still in their player, so their end marker and done are held until the player has played what it was fed.
- Done per call. OneCore, Eloquence, and SAPI 4 report done once their queue is empty. eSpeak, Vocalizer, RHVoice, and SAPI 5 report it after each speak call, with the next call still queued. So a done that arrives after one of the guest's markers, while a later piece of it is still in flight, is taken as the done of the call that finished. A done with none of the guest's markers reached is a failed synthesis and finishes its pieces. eSpeak's done is checked against its own queue as well, because the done of an utterance a cancel cut short can arrive after the next one is queued. Acapela reports done twice: once when a call's synthesis ends, with its audio still to play, which is ignored, and again once its queue is empty and the audio played.
- Acapela. It reports only the last mark of each block of audio, so a piece's end marker also reports the NVDA indexes in it that went unreported, and the guest's earlier pieces whose markers were lost. It writes each mark one higher than it is given, and its code does not show whether its engine returns that number or the one given, so the scheduler hands out only even numbers and an odd one from Acapela is taken one down. Its cancel leaves the calls queued behind the one speaking, which it would then speak, so they are dropped first. Its setters call the engine without the lock its synthesis holds, and its end marker comes while it is still synthesizing, so any new row on it waits for its done, not only one that changes the voice. Another Acapela driver, under the same name, hands each call to its engine to play: it has no queue of its own, reports done once per call, and its engine may cut a call short with the next, so it is sent one piece at a time, as NVDA sends the synthesizer in use one utterance at a time. It keeps a new pitch for its next utterance, which is read as set. Its voices give no language; a synthesizer whose voices give none is taken to speak every language, so no text goes to a Windows voice on its account, and its default language is NVDA's. SAPI 5's done after each request, while more are queued, is ignored. A done that comes while a piece is still being handed to the guest does not finish that piece.
- Rows are reapplied on every send and skipped when the guest already carries that row, so a preview from the settings dialog, which clears the mark, never leaves a guest on the wrong voice. A new voice also clears Eloquence's memory of the language it last switched to, or it would skip the next command for that language.
- Prosody. NVDA computes a rate, pitch, or volume command from the value in the configuration section of the synthesizer in use, this driver's, which is not what the piece is spoken at. Each command in a piece is rewritten to land on the row's value, or the default's, in the form the guest reads: a capital letter's +30 on Eloquence at pitch 65 gives 95, and the reset returns to 65. Eloquence reads the absolute value, so offsets are rebased on the value NVDA will resolve them against. OneCore, SAPI 5, and eSpeak read only the multiplier, which NVDA derives from the offset and applies to the guest's own current value, so an offset becomes the multiplier that reaches the row's value plus the offset, and a reset stays a reset. RHVoice builds its markup with NVDA's SSML converter, which also writes the multiplier. Vocalizer adds the offset alone to its own current value, the row's, which is what NVDA means by it, so its commands pass unchanged. So do those of the 32-bit drivers (SAPI 4, SAPI 5, AiSound), which run in another process that resolves commands against its own values. The form is found by what the driver's code reads: the absolute value, the multiplier, a class built on NVDA's SSML converter, or the offset. The multiplier is computed from the row's value, since eSpeak, while busy, reports its old value for a while after being given a new one. A command the guest does not support is left out, as NVDA leaves it out for the synthesizer in use: a SAPI 4 voice without pitch fails on a pitch command, and the whole piece would be lost. A row's rate boost is set before its rate, because a driver's rate boost setter re-applies the rate it reads back.
- Cancel cancels every guest with pieces in flight and drops the index maps, so late callbacks are ignored. Pause goes to the speaking guest and holds the seam.
- A piece with no guest, or a guest whose `speak` fails or which never reports progress (NVDA's silence driver), is treated as done, and NVDA's indexes inside it are still reported in order, because NVDA's speech manager waits for them. So are those of a piece whose guest reports done without reaching them, as after a failed synthesis. OneCore, when its first utterance fails, is left marked as speaking and never speaks again; on the add-on's instances that failure is completed, the instance freed and its done reported.
- Guests with engines of their own ideas. Vocalizer's own switching by script is turned off for rows, which would otherwise hand a row's text to another voice; the default synthesizer keeps the user's setting. Sonata fills the voice lists of NVDA's open speech settings panel on every voice change, whichever synthesizer the panel shows, so only the synthesizer in use still does. The default language is read from the default variant's language first, since Sonata's multilingual voices have one variant per language and report their first. WorldVoice is refused as a guest and as the default: it is a language table itself, re-raises its engines' notifications as the synthesizer in use, patches NVDA while any instance of it exists, and starts NVDA's eSpeak inside itself, which takes over the engine of an eSpeak guest. The settings dialog's temporary instance of a synthesizer is taken over when the language table loads it, rather than a second one created, because eSpeak and Vocalizer keep their engines in module globals that a second instance re-initializes. A default synthesizer that fails to load (a 32-bit one whose process did not start) is stood in for that time only, and never by silence.

### Windows voices

`mlang/winvoices.py` reads the OneCore voice tokens from the registry, applying the same validity checks as NVDA's OneCore driver, to learn which languages Windows' own voices speak without loading that driver. A language with no row that the engine in use cannot speak is sent to the Windows voice for it through an implicit row on the OneCore driver, so Arabic text reaches Windows' Arabic voice with nothing configured. A panel setting turns this off.

### Settings

Settings live in NVDA's config under `[multilanguage]`, so configuration profiles apply to them (`mlang/table.py`):

- `mode`: `off`, `script` (script changes only, never guesses), or `full` (the default).
- `strict`: also require Windows' own language detection to agree before switching.
- `detectInDefaultTagged`: detect inside text tagged with the default language, on by default.
- `useWindowsVoices`: send languages the engine cannot speak to Windows voices, on by default.
- `defaultSynth`: the language table's host.
- `table`: the rows, as one JSON string. Each row has a language, a synthesizer, and optionally a voice, variant, rate, rate boost, pitch, inflection, and volume, and a punctuation/symbol level. The symbol level is NVDA's, not the synthesizer's: NVDA processes symbols once per utterance at one level, through `speech.speech.processText` with each string's language, and the plugin wraps that function so text in a row's language gets the row's level. Only NVDA's configured level is replaced, so a level a caller asks for (all symbols when spelling) stands. The voice is applied first, since changing it resets parameters in some engines.

The default language has no row: it is the synthesizer in use with its own settings. The languages detection chooses among are the rows plus the default. Row languages are kept in NVDA's spelling (`fr_FR`, never `fr-fr`), because NVDA's character descriptions and symbol files fall back from `fr_FR` to `fr` on the underscore alone and would give English for a hyphenated tag. The row dialog rejects text that is not a language code.

Two scripts without default gestures sit in the Speech category of Input Gestures: one cycles the detection mode, one toggles strict mode.

## How detection works

### Scripts

Script detection runs first, in every mode except off. Letters are classified by Unicode script with the `regex` module NVDA bundles, and Windows names the scripts each language is written in (`GetLocaleInfoEx` with `LOCALE_SSCRIPTS`), so no data files are needed.

A run in a script the default language does not write is tagged as follows:

- With one configured language for that script, that language, with no recognizer involved.
- When the default writes that script too (Serbian, written in Latin and Cyrillic, beside Russian), the default leads the run's clause detection. Beside a Japanese or Korean default, pure Han switches to Chinese only at 0.9, since kanji-only headings and names are common in Japanese. Windows lists Latin alone for untagged Serbian, Bosnian, Uzbek, and Azerbaijani, so Cyrillic is added for them unless the tag names a script.
- With several, the recognizer picks among them for the run. In full mode, the run's clauses are then detected among those languages by the clause rules below, with the pick standing in for the default. This is how a Ukrainian sentence after a Russian one in English prose switches to Ukrainian.
- With none, the languages the installed voices speak (the synthesizer's and Windows') are the candidates.
- With none of those either, the recognizer's free guess is tagged whether or not any voice can speak it, so NVDA's "report when switching to language is not supported" setting names the language instead of the voice falling silent on a script it cannot read.

A lone letter borrowed as a symbol stays with the default voice. Han, kana, and hangul are grouped within a sentence: kana means Japanese, hangul means Korean, and pure Han goes to Chinese before Japanese or Korean. A group holding a script the default does not write is foreign, so a Japanese sentence with kanji in Chinese text is Japanese. Words run together in those scripts, so their runs are not split into clauses.

### Clause rules

In full mode, text in the default script is detected clause by clause among the default language and the configured languages of that script. The rules live in `mlang/detector.py`, shared by the add-on and the harness.

- Clauses. Text is split at quotes, commas, semicolons, colons, brackets, exclamation and question marks, periods, spaced dashes, double hyphens, newlines, and the Spanish, Arabic, Devanagari, Armenian, Ethiopic, and full-width equivalents. Punctuation belongs to the clause before it.
- Words. A word is a run of letters, with their vowel signs and other combining marks, and apostrophes, hyphens, or zero-width joiners inside it. Numbers, versions, paths, and identifiers are not words. A capitalized word after the first is a name and is neither counted nor scored. A capital word of fewer than five letters is an abbreviation and never scored. Scripts without case (Arabic, Hebrew, Devanagari) have neither names nor abbreviations by these rules. Text with fewer than two letters is never guessed.
- Headlines. A clause of two or more words all in capitals ("MOST VAGY SOHA"), or three or more that all start with a capital ("Az Európai Autóipar Halála"), is a headline, where case marks nothing: every word is counted and scored, lowercased, since fastText reads capitals poorly. A headline switches only at 0.98, never on the dictionaries alone. Two capitalized words are not a headline, since a name standing as its own clause ("Mario Moreno") would be scored as English and outvote the Spanish rest of its line.
- Scoring. A clause of two or more common words is scored among the default language and the configured languages of its script. It switches when the top guess is foreign at 0.9 or higher.
- Short clauses. A short clause follows a neighbor of its own sentence only on a near-certain guess of the neighbor's language, or, when every scored clause of the line leans one way, on leaning that way at all. That is how "No" in "¿Tú eres Miguel? No, yo no soy Miguel." stays Spanish.
- Embedded clauses. A foreign clause between default-language clauses of its sentence must reach 0.98, judged between its language and the default alone.
- Peeling. A foreign clause of four or more words has a default-language run of two or more words, counted as words ("mesterei 😂" is one), peeled off either end when the remainder is still confidently foreign. Every length is tried and the longest taken, rather than stopping at the first that no longer reads as the default, because fastText dips on two-word fragments ("Orthodox army" scored 0.89 between "Russian army" at 0.999 and "the army" at 0.98).
- Unconfigured languages. A confident foreign guess is checked once more with no constraint. If the free guess names a language nobody configured, and outranks the chosen one by a factor of three, the clause stays in the default: Italian among Spanish and French is nobody's to switch to ("Dio mi l'ha dato" is Italian 0.73 to Spanish 0.005). The factor exists because fastText's free guess on a short clause is rarely confident; a Spanish word pair the recognizer edges toward Galician is left alone.

### Spelling dictionaries

The Windows Spell Checking API, reached through the `comtypes` NVDA bundles (`mlang/dictionary.py`), settles what fastText cannot.

- A clause the default language's dictionary accepts whole must reach the 0.98 two-way bar before it switches. The dictionary rejecting a word is the strong evidence for a switch. Without a dictionary for the default language, this gate is open.
- A clause whose guess leads but falls short of the floor (0.5 or more) switches when the default dictionary rejects one of its words and the guessed language's dictionary accepts every word. "Dieu me la donne" is French at only 0.76.
- A clause the dictionaries call foreign that way is embedded in default-language speech without meeting the 0.98 bar ("Cousinage--dangereux voisinage" beside "she added").
- The same evidence lets a one-word clause join a foreign neighbor of its sentence, which otherwise takes a near-certain guess: "demain" between two commas is French at 0.62, the English dictionary rejects it, and the French one knows it.
- Text that is one word alone, as a button or a link is ("Keresés", "Guardar"), switches when every installed regional dictionary of the default language rejects it and exactly one configured language's dictionary accepts it. The recognizer has no say against the default, since on one word it is noise: it calls "Cancelar" English at 0.89 and "fraser" at 0.60. It only picks between the accepting language and configured languages with no dictionary. A word of fewer than four letters, one in capitals, a camelCase identifier ("numLock"), and a small word the default dictionary knows capitalized ("paris", "british") never switch this way. Every region counts because US English rejects "metres" and "Organisation", which Canadian English knows.

The last four rules need both languages' dictionaries. With the French dictionary installed, French word pairs went from 64 to 81 percent and French interface strings from 63 to 72 percent, with no English cost.

A missing dictionary is looked for again every five minutes, so one installed mid-session is picked up, and a failed call is never remembered as an answer. A dictionary comes from the "Basic typing" feature of a Windows language pack. When a row is added for a language without one, the panel offers to install it (`mlang/langpack.py`). It is a Windows capability (`Language.Basic~~~es-ES~0.0.1.0`, the region resolved by `ResolveLocaleName`) that only an administrator can add, so the add-on runs `Add-WindowsCapability` in an elevated Windows PowerShell through the UAC prompt, waits for it on a thread, then refreshes the dictionary list and reports. Presence is checked through the spell-checking API, since reading capability state also needs elevation.

### Tags from applications

- A tag whose language writes no script the text has a letter of (Russian on Latin text) is dropped, and the text is detected as untagged. Where the text mixes scripts, the tag is dropped only from the parts in a script its language does not write: on a Russian page wrongly declared English, "PDF" keeps the English tag and the Russian around it is detected.
- In full mode, a tag in the default script (French on an English page) is dropped from each clause that reads as the default language on a near-certain guess, names included.
- Text tagged with the default language itself is, by a setting that defaults on, detected like untagged text, since a page's document language says nothing about a foreign paragraph inside it.

### The reader's own words

NVDA's role and state names, in whatever language NVDA runs, are collected from `controlTypes` at startup and never scored.

### How the model guesses

The recognizer, fastText's lid.176 model, is a classifier, not a language model in the generative sense: it understands no meaning, grammar, or context, and generates nothing. Text goes in, and out comes a probability for each of 176 languages. It was released by Facebook AI Research in 2017, trained on Wikipedia, Tatoeba, and SETimes.

- It splits the text into words, and each word into short runs of letters: "Bonjour" gives "bo", "on", "nj", "jou", "our", and so on.
- Training learned a vector of numbers for every word and letter run seen often enough.
- To guess, it looks up the vectors for everything in the text, averages them, and turns the average into one probability per language.

The letter runs are what make it work on short text: an unfamiliar word still carries clues, since "-ción" looks Spanish, "-ung" German, and "qu'" French. Lookups and an average are also why it is fast, well under a millisecond a line.

The same design sets its limits. It knows nothing of word order or of the surrounding sentence, it scores each clause alone, and the less text there is, the less there is to average, so two-word clauses are the hardest case. The clause rules and the dictionaries above exist to cover for that:

1. The guess is narrowed to the default language and the configured languages, and renormalized. Fewer configured languages means fewer ways to be wrong.
2. A switch needs 0.9, and 0.98 for a clause embedded in default-language speech.
3. The model is asked again with every language allowed, and a clear win for a language nobody configured keeps the clause in the default.
4. The spelling dictionaries act as a second opinion in both directions: a clause the default dictionary knows whole needs near certainty, and a word it rejects that the other language's dictionary knows lets a lower score through.

When in doubt, the clause stays in the default language.

### The recognizer

The recognizer is fastText's lid.176 language identification model, run through the `fasttext-predict` package, whose compiled module (213 KB) is vendored in `addon/lib/` (`mlang/recognizers.py`).

The published compressed model, `lid.176.ftz` at 916 KB, is not used. It was pruned to 100,000 features with no character n-grams, so common short words ("no", "army", "Oui", "La", "Desk", "Miguel") are unknown to it and score exactly like an empty string, which loses clauses such as "Oui, oui, je suis là" and "No, yo no soy Miguel". The add-on ships `lid.176.q1m.ftz` instead (17 MB): the full 126 MB model quantized with fastText's own tool at a cutoff of 1,000,000 features, character n-grams kept. A 300,000 cutoff at 5 MB also knew every probe word but switched on more English strings. `addon/lib/models/NOTICE.MD` records the exact command.

Probabilities are filtered to the candidate set and renormalized, which gives the constrained score the rules need. Curly apostrophes become straight and hyphens become spaces before scoring, since fastText splits on whitespace alone and knows "vas" and "tu" where it may not know "vas-tu". Lowercasing before scoring was measured and rejected: it lost acceptance cases for a marginal dataset gain. Headlines are the exception (see Clause rules): lowercased, Title Case sentences in Lingua's data went from 26 to 88 percent tagged for Spanish, with English still at none.

Strict mode adds Windows' Extended Linguistic Services (`elscore.dll`, `mlang/els.py`) as a second recognizer. It returns a ranked list with no scores; strict mode switches only when it names the same language as fastText. That means fewer switches, and no false ones in any run so far.

## Measured accuracy

Every figure below is with English as the default language, except the last list, which covers other scripts and defaults. The runs are saved in `results/`, and the commands that produce them are listed at the end of this section. Figures in parentheses are the published 916 KB model's, for comparison; `harness/model_compare.py` gives both sets for any model file. The dictionary rules only fire where both dictionaries exist, so results depend on which Windows dictionaries are installed; these runs had English, French, and Spanish. Figures in parentheses are from earlier runs that had English and French only.

- Acceptance cases (the probe phrases plus script and tag-distrust cases): 88 of 89 (55 of the 78 cases before the headline and lone-word ones; the published model was not run on those). The one miss is "Guai a chi la tocchi" as Italian at 0.55, which an Italian dictionary would settle the same way.
- NVDA's own English interface strings, with German, Spanish, French, Italian, and Portuguese configured: 3,283 lines, 1 false switch ("drft cmnt" as German).
- NVDA's translated interface strings, tagged with their own language: German 52 percent (51), Spanish 78 (50), French 80 (60), Italian 61 (59), Portuguese 45 (41). These are short labels; the name rule, and single words in languages with no dictionary installed, account for most misses. With no Portuguese dictionary, 3.7 percent of the Portuguese strings are single words the Spanish dictionary accepts, and go to Spanish.
- Lingua's test data, French and Spanish configured, 1,000 lines per file: English sentences 0 false switches, English word pairs 0 (1); Spanish sentences 98.9 percent (97.6), French sentences 98.2 percent (96.6); Spanish word pairs 71.8 percent (54.5), French word pairs 80.6 percent (57.4). Single words, by the dictionaries alone: Spanish 56.1 percent, French 59.9, and 2 English words of 1,000 switched: "plongeon", a French word in Lingua's English list, and "javascript", which the French dictionary knows.
- Headlines, the same Lingua lines recased by `--case`, with French, Spanish, German, and Hungarian configured and English, French, and Spanish dictionaries installed: English lines 0 false switches in either case. Title Case sentences tagged with their own language: German 96.0 percent, Spanish 87.8, French 90.4, Hungarian 98.3; Title Case word pairs are two words, not a headline, and never switch. Capitals: sentences German 96.7, Spanish 88.8, French 92.2, Hungarian 99.3; word pairs German 65.5, Spanish 37.7, French 40.4, Hungarian 82.5. Before headlines, capitals were tagged in 5 percent of sentences or fewer, German 18, and English capitals had 3 false switches in 2,000 lines.
- The first 200,000 characters of an English translation of War and Peace, which quotes French throughout, with accents stripped and French and German configured: 28 French runs, 1 false. With strict mode, 25 runs, 0 false. The text is not in the repository. These figures are from an earlier build of the detector with the published 916 KB model, and have not been rerun with the shipped one.
- Cost: 0.3 milliseconds per English line, up to 3 milliseconds for a Spanish sentence, since the peel tries every length and the dictionary is consulted.

Other scripts, on the same Lingua data (`results/lingua-non-latin-fasttext.txt`), with no dictionary for any of these languages installed:

- English default, sentences tagged with their own language: Russian 99.5 percent, Ukrainian 99.8, Belarusian 98.1, Bulgarian 99.1, Macedonian 99.7, and Serbian 97.6 with all six configured; Arabic 100, Persian 100, and Urdu 99.5 with all three; Hindi 99.9 and Marathi 98.9 with both; Chinese 99.5, Japanese 100, and Korean 99.9 with all three. Hebrew, Greek, Georgian, Armenian, Thai, Bengali, Tamil, Telugu, Gujarati, and Punjabi are at 99.9 or 100, by script alone. English lines never switch.
- Other defaults, neighbours' sentences tagged with their own language, and the default's own lines switched: Russian default with Ukrainian 98.5 and Bulgarian 94.8, Russian lines 1.6 percent; Ukrainian default with Russian 97.1, Ukrainian lines 5.4; Serbian default with Russian 96.5, Macedonian 96.4, and Bulgarian 95.0, Serbian lines 3.0; Arabic default with Persian 99.6 and Urdu 99.0, Arabic lines 5.2; Hindi default with Marathi 96.0, Hindi lines 3.7; Chinese default with Japanese 100, Chinese lines 0; Japanese default with Chinese 98.2, Japanese lines 0. English was configured in every run except the Serbian one. In those runs, most of the default's switched lines are Latin names and terms ("Firefox", "PM") sent to the English row. The rest, and most of the Serbian run's, are close neighbours (Serbian clauses as Macedonian or Russian), which the dictionaries settle for English.
- Word pairs switch less than sentences, as in Latin script (Macedonian 47 percent under a Russian default). Single words never switch in a default's own script, by rule, and a single kana is a letter, not a word, so Lingua's Japanese single words, which are mostly single kana, are never tagged.

The commands behind these figures, run from the project folder with `PY` set as under Building and testing:

- Acceptance cases: `"$PY" harness/harness.py fasttext`, saved as `results/acceptance-fasttext-q1m.txt`.
- Interface strings: `"$PY" harness/dataset_eval.py fasttext datasets/ui-strings fr,es,de,it,pt`, saved as `results/ui-strings-fasttext-q1m.txt`.
- Lingua, French and Spanish: `"$PY" harness/dataset_eval.py fasttext datasets/lingua fr,es`, saved as `results/lingua-fasttext-q1m.txt`.
- Headlines: `"$PY" harness/dataset_eval.py fasttext datasets/lingua fr,es,de,hu --case title`, and the same with `--case upper`.
- The figures in parentheses: `"$PY" harness/model_compare.py <path to lid.176.ftz> addon/lib/models/lid.176.q1m.ftz`. `results/lingua-fasttext.txt` and `results/ui-strings-fasttext.txt` are the two dataset runs with `MLANG_MODEL` set to `lid.176.ftz`.
- Strict mode: the same commands with `ensemble` in place of `fasttext`.
- The prose sample: `"$PY" harness/harness.py fasttext <text file> --strip`, and the same with `ensemble`, saved as `results/novel-fasttext.txt` and `results/novel-ensemble.txt`.
- Other scripts, all saved together in `results/lingua-non-latin-fasttext.txt`: `"$PY" harness/dataset_eval.py fasttext datasets/lingua <languages> --show 5`, once for each of these language lists with English as the default: `ru,uk,bg,be,mk,sr`, `ar,fa,ur`, `hi,mr`, `zh,ja,ko`, and `he,el,ka,hy,th,bn,ta,te,gu,pa`. Then once for each other default, adding `--default <code>`: `uk,bg,be,mk,sr,en --default ru`, `ru,en --default uk`, `ru,bg,mk --default sr`, `fa,ur,en --default ar`, `mr,en --default hi`, `ja,en --default zh`, and `zh,en --default ja`.

## What NVDA provides and does not

- Core emits language commands only from tagged text and holds one synthesizer at a time. There is no per-language table in core.
- Each driver handles a language command alone: eSpeak switches voice itself, OneCore drops languages with no installed voice, SAPI 5 passes an LCID to the engine, and Eloquence emits its language code. The Eloquence add-on has language files for German, UK and US English, both Spanishes, French, Canadian French, Italian, Brazilian Portuguese, Finnish, Chinese, Japanese, and Korean.
- Add-ons may ship synthesizer drivers, and a driver may instantiate other driver modules directly.
- `comtypes` and `regex` are bundled with NVDA. Compiled modules must match NVDA's Python: 3.13, 64-bit, for 2026.x.

## Repository layout

- `README.md`: this file.
- `GETTING_STARTED.txt`: the beta testers' introduction.
- `KNOWN_GAPS.md`: problems found and left alone, with the reason for each.
- `LICENSE`: the GNU General Public License version 2.
- `addon/`: the add-on as installed.
  - `manifest.ini`.
  - `globalPlugins/multilanguage/__init__.py`: the plugin, the speech filter, and the scripts.
  - `globalPlugins/multilanguage/settings.py`: the settings panel and the row dialog.
  - `globalPlugins/multilanguage/context.py`: the caret character and word wrappers.
  - `synthDrivers/languageTable.py`: the hosting driver.
  - `lib/mlang/`: the shared library. `detector.py` (clause and script rules), `scripts.py` (Unicode scripts and language codes), `sequence.py` (the detector over a speech sequence), `recognizers.py` (fastText, ELS, and the strict ensemble), `els.py`, `dictionary.py`, `langpack.py`, `table.py` (config and rows), `scheduler.py`, `hosts.py` (guest creation and row application), `prosody.py`, `voicedict.py`, `winvoices.py`, `policy.py`.
  - `lib/fasttext/` and `lib/fasttext_pybind.cp313-win_amd64.pyd`: fasttext-predict, MIT.
  - `lib/models/lid.176.q1m.ftz`: the model, CC BY-SA 3.0; `NOTICE.MD` says how it was made.
  - `doc/en/readme.md`: the user guide.
  - `locale/<lang>/`: catalogs and translated manifests for the 63 languages NVDA is translated into. Generated; do not edit by hand.
- `build.py`: zips `addon/` into `dist/multilanguage-<version>.nvda-addon` and renders the user guide to HTML.
- `tests/`: unit tests for the scheduler, the sequence filter, the prosody pass, the language pack check, the host's stored settings, voice dictionaries, the config table and rows, and script runs and language codes, run on plain Python with `nvda_stub.py` standing in for `speech.commands`.
- `harness/`: measurement over the shipped detector.
  - `harness.py`: the acceptance cases, plus a paragraph runner for any plain text file.
  - `dataset_eval.py`: switch and hit rates over a directory of `<kind>/<lang>.txt` sample files.
  - `model_compare.py`: for candidate model files, the unknown-word probe, the acceptance count, and both datasets side by side. `MLANG_MODEL=<path>` points any harness run at another model.
  - `els_probe.py` and `spell_probe.py`: standalone probes of the two Windows APIs.
  - `phrases.py`: the probe phrases.
  - `build_ui_strings.py`: rebuilds `datasets/ui-strings` from the `nvda.po` files in `datasets/ui-strings/po`.
- `datasets/lingua/`: lingua's test data, from `github.com/pemistahl/lingua-py` (directory `language-testdata`), Apache License 2.0; see `LICENSE.txt` and `NOTICE.md` there.
- `datasets/ui-strings/`: English and translated NVDA interface strings, extracted from NVDA's translation catalogs in `po/`, GPL 2; see `NOTICE.md` there.
- `i18n/`: the add-on's translations (see below).
- `results/`: saved harness runs.

## Building and testing

Use Python 3.13 64-bit, the same build as NVDA, so compiled modules are exercised as NVDA will load them. The environment goes in `.venv` unless `UV_PROJECT_ENVIRONMENT` names another folder, which is needed when the repository is on a network share that cannot hold a virtual environment. `i18n/extract.py` reads NVDA's own translations from the compiled catalogs of the installed NVDA (`NVDA_INSTALL` names another installation folder), or from a clone of `https://github.com/nvaccess/nvda` when `NVDA_SOURCE` names one. From the project folder in Git Bash:

```
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-.venv}"
uv venv --python 3.13 "$UV_PROJECT_ENVIRONMENT"
uv pip install --python "$UV_PROJECT_ENVIRONMENT/Scripts/python.exe" fasttext-predict comtypes regex
export PYTHONUTF8=1
PY="$(cd "$UV_PROJECT_ENVIRONMENT" && pwd)/Scripts/python.exe"
(cd tests && "$PY" -m unittest discover)
"$PY" harness/harness.py fasttext
"$PY" harness/dataset_eval.py fasttext datasets/ui-strings fr,es,de,it,pt
"$PY" harness/dataset_eval.py fasttext datasets/lingua fr,es
"$PY" harness/dataset_eval.py fasttext datasets/lingua uk,bg,be,mk,sr,en --default ru
"$PY" i18n/extract.py
"$PY" i18n/make_locale.py
"$PY" build.py
```

- The two `i18n` steps are needed only after a translatable string or a translation changed.
- `ensemble` in place of `fasttext` measures strict mode. `HARNESS_NODICT=1` turns the dictionary rules off for comparison.
- To install, open `dist/multilanguage-<version>.nvda-addon` with NVDA running and restart NVDA when asked. NVDA's log at debug level shows `multilanguage:` lines for anything that fails to load.

### Rebuilding the model

1. Download `lid.176.bin` from `https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin`.
2. Clone `https://github.com/facebookresearch/fastText`.
3. Compile `src\*.cc` with `cl /O2 /EHsc /std:c++17` from a Visual Studio Build Tools prompt for the x64 toolset (on Windows on ARM, `vcvarsarm64_amd64.bat`). Compile directly: fastText's CMake file makes two libraries of one name on Windows.
4. Beside a copy of the model named `lid.176.bin`, run the quantize command from `addon/lib/models/NOTICE.MD`: `fasttext quantize -input none -output lid.176 -cutoff 1000000 -qnorm -dsub 2`.

## Translations

`i18n/extract.py` collects the `_()` strings from the add-on into `i18n/messages.json`, along with NVDA's own translation of any string NVDA also has ("&Voice:", "Rate &boost", the column headers), so the add-on's terms match NVDA's in each language. `i18n/translations/*.json` hold the rest, keyed by the short codes in `make_locale.py`. `make_locale.py` merges the two, checks `%s` placeholders and accelerators, derives bare headers from labelled siblings, and writes the catalogs. It lists any placeholder mismatch, any label that lost its accelerator or has one on a space, and any gap. A translation with a placeholder mismatch is dropped, and a gap falls back to English.

The translations were machine-written and have not been reviewed by native speakers. A language's strings are spread over several `i18n/translations/*.json` files. A corrected string goes into whichever file holds that string's code for the language, and the catalogs are rebuilt.

## Status

Built and unit-tested. Detection with plain Eloquence has been heard working live. Still to be heard:

- One synthesizer with a slower French row on Eloquence, on a mixed page, in say all, and arrowing by character and word through a French sentence.
- The language table with Eloquence as host, eSpeak for French, OneCore for Spanish, and Arabic through a Windows Arabic voice with no row. No Windows Arabic voice has been installed for testing yet, so that path is unheard.
- A clean NVDA 2026.2 install, before any submission to the add-on store.

## Open questions

- The audible seam between synthesizers: gap, volume mismatch, and index timing during say all. If the gap is audible, the next step is to start the next guest on the marker of the piece before the last rather than the last.
- Whether strict mode should be the default.
- The dictionary rules are measured for French only. Spanish, German, Italian, and Portuguese would each need that language pack installed on the test machine to measure.
- Context cases the rules cannot reach, such as "Bonjour Pierre, comment vas-tu?" and vocabulary lines like "Orange, la naranja", would need a trained word-level tagger that labels each word by its neighbors. Word-level language identification for code-switched text has public benchmarks (LinCE, and the 2014 and 2016 code-switching shared tasks) and public training sources (Tatoeba and OPUS sentences for spliced lines, name lists for a name class, the reader's localized strings for a reader-word class). Output would be constrained to the configured languages, with the default as the label for everything else. This is not planned until the rules ship.

## Licenses

Copyright (C) 2026 Rashad Naqeeb. Licensed under the GNU General Public License version 2; see `LICENSE`.

The add-on is GPL 2, like NVDA. The language model is derived from fastText's lid.176 (Creative Commons Attribution-ShareAlike 3.0), run through fasttext-predict (MIT). Lingua's test data is Apache License 2.0; see `datasets/lingua/NOTICE.md`. The NVDA translation catalogs in `datasets/ui-strings/po/`, and the strings extracted from them, are NV Access's and NVDA's translators', under GPL 2; see `datasets/ui-strings/NOTICE.md`.

## References

- NVDA source: `https://github.com/nvaccess/nvda`, files `source/speech/speech.py`, `source/speech/manager.py`, `source/speech/extensions.py`, `source/speech/languageHandling.py`, `source/synthDriverHandler.py`, `source/synthDrivers/espeak.py`, `source/synthDrivers/oneCore.py`.
- fasttext-predict: `https://github.com/searxng/fasttext-predict`.
- Windows Extended Linguistic Services: `https://learn.microsoft.com/en-us/windows/win32/intl/microsoft-language-detection`.
- Windows Spell Checking API: `https://learn.microsoft.com/en-us/windows/win32/intl/spell-checker-api`.
