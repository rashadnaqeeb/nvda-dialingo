# Dialingo

An NVDA add-on that reads text in the language it's written in, even when nothing marks what language that is, and lets you give each language its own synthesizer, voice, and settings.

This readme explains how it works and how to build it. If you just want to use the add-on, read the user guide, `addon/doc/en/readme.md`, which is also the help page inside the add-on. `KNOWN_GAPS.md` lists the problems that are known and have been left alone on purpose, with the reason for each.

It needs NVDA 2026.1 or later and has been tested on 2026.2. During its beta it was called multilanguage.

## The problem

NVDA can already switch languages, but only when the text says what language it's in. Web pages and documents can carry language tags, and when they do NVDA passes them on to the synthesizer. Most text doesn't have them: chat messages, ebooks, notes, and application interfaces. A French sentence in an English email gets read with the English voice.

Even when there is a tag, NVDA speaks through one synthesizer at a time. A switch to Arabic gets whatever Arabic your current synthesizer has, or nothing. There's no way to say "Eloquence for English, but the Windows Arabic voice for Arabic".

The add-on fixes both. It works out the language of untagged text, and it can play each language on a different synthesizer, switching between them in the middle of a line.

One rule shapes almost every decision below: a wrong switch is much worse than a missed one. If the add-on mistakes a button label for Spanish, you hear that mistake every time you land on the button. If it misses a Spanish sentence, the sentence just gets mispronounced once. So when the add-on isn't sure, it leaves the text with your default language. It never switches on NVDA's own words, such as "button" or "checked", and it treats names, abbreviations, and single characters very carefully.

The other constraint is speed. Detection runs inside NVDA's speech path, before every utterance, so it has to be fast. An ordinary English line takes about a third of a millisecond.

## How the add-on fits into NVDA

The add-on has two parts, and each works without the other.

- A global plugin, in `addon/globalPlugins/dialingo/`. It detects languages, applies each language's settings, and provides the settings panel.
- A synthesizer driver called Language table, in `addon/synthDrivers/languageTable.py`. It loads your other synthesizers inside itself and sends each language to the one you chose for it.

Most of the logic is in `addon/lib/mlang/`. Apart from NVDA's speech command classes, which the tests stand in for, that library only imports NVDA inside functions, so the tests and the measurement scripts run the same code outside NVDA.

Here's what happens to a piece of speech:

1. Something in NVDA calls `speech.speak()` with a speech sequence, which is a list of text strings and commands.
2. The plugin's filter, registered on `speech.extensions.filter_speechSequence`, sees the sequence first. That's before NVDA processes symbols or applies its own language handling.
3. The filter detects languages and inserts NVDA's standard language commands around the parts in other languages.
4. For a language set up on the synthesizer you're already using, it adds rate, pitch, and volume commands, and applies that language's voice dictionary.
5. NVDA carries on as usual and hands the sequence to the synthesizer.
6. If that synthesizer is the Language table, it cuts the sequence at each language change and plays the pieces on the right synthesizers in turn.

Each step is wrapped so that if it fails, it logs the error and passes the sequence on unchanged. A bug in the add-on should cost you language switching, not speech.

NVDA throws away language commands unless its "Automatic language switching" setting is on. The add-on never changes that setting. While the Language table is in use, it makes NVDA's two checks of that setting answer yes. These are `shouldMakeLangChangeCommand` and `shouldSwitchVoice`, in `speech.languageHandling`. With any other synthesizer, your setting stands. If it's off, the add-on leaves speech alone.

The language model is 17 MB and loads in the background when NVDA starts. Until it's ready, speech passes through without detection, so NVDA isn't held up at startup.

## Detecting the language

The add-on uses three kinds of evidence, from most to least reliable.

### 1. Writing system

If the text changes script, say from Latin letters to Arabic, there's usually nothing to guess. The add-on sorts letters by Unicode script, and Windows reports which scripts each language uses (`GetLocaleInfoEx` with `LOCALE_SSCRIPTS`), so no data files are needed.

Text in a script your default language doesn't use goes to:

- the one language you've set up that uses that script, if there's exactly one
- the best guess among them, if you've set up several (Russian, Ukrainian, and Bulgarian, for example), then checked clause by clause like any other text
- one of your installed voices that speaks that script, if you haven't set any up
- the model's best guess otherwise, even with no voice for it, so NVDA can say "Arabic, not supported" instead of the synthesizer mangling it or going silent

Chinese, Japanese, and Korean are handled together within a sentence. Kana means Japanese and hangul means Korean. Han characters on their own go to Chinese first. Mandarin and Cantonese are separate languages: with rows for both, Han text goes to Cantonese only when the model is nearly sure it's written Cantonese, and to Mandarin otherwise.

A single letter in another script, as in "Is it س?", goes to a voice for that script. That doesn't apply if your default language's symbol list already gives the letter a name.

This step runs in every detection mode except Off.

### 2. Language tags

When an application does tag its text, the add-on checks the tag against the text before trusting it:

- A tag for a language that doesn't use the text's script, such as a Russian tag on Latin text, is dropped, and the text is treated as untagged.
- In Full mode, a French tag on a clause that clearly reads as English is dropped from that clause.
- A tag for your default language tells you very little. Most web pages are marked English as a whole, French paragraphs included. So text tagged with the default language is checked like untagged text, unless you turn that off in the settings.

### 3. Guessing

In Full mode, text in your default language's script is split into clauses. Each clause is scored by a small language model and checked against the Windows spelling dictionaries. The only candidates are your default language and the languages you've set up that use that script.

**Clauses.** Text is split at sentence punctuation, commas, quotes, brackets, dashes, slashes, and line breaks. Numbers like "2.6", "8:05", and "10/03/2026" aren't split. The Spanish "¿" and "¡" belong to the clause they open, so the voice that reads "¿Cómo estás?" reads its "¿" too.

**Words.** Only ordinary words count. Numbers, paths, and identifiers don't. A capitalized word in the middle of a clause is taken as a name and ignored. The exception is German, which capitalizes every noun: a capitalized word counts when the model is nearly sure it's German and your default dictionary doesn't know it. A word in capitals under five letters is taken as an abbreviation. Headlines, three or more words that all start with a capital or two or more in capitals, are scored with all their words, since capitals mean nothing there. A headline only switches at 98 percent.

**Scoring.** A clause needs at least two ordinary words to be scored. It switches when the model gives another language 90 percent or more. A foreign clause sitting between two default-language clauses of the same sentence needs 98 percent.

**Short pieces.** Very short clauses can't be scored reliably, so they follow their neighbours. In "¿Tú eres Miguel? No, yo no soy Miguel." the "No" stays Spanish because the rest of the sentence is. A sentence made only of short clauses, like "Soy Marcos, encantado.", is scored as a whole.

**Trimming.** A foreign clause of four or more words can start or end with a few words in the default language. Those words are trimmed off and left with the default voice, as long as what remains still clearly reads as foreign. A word the default dictionary rejects is never trimmed off as default-language text, however it scores.

**Languages you didn't set up.** The model is also asked for its unrestricted guess. If that clearly favours a language you haven't set up, the clause stays in your default language. So with Spanish set up but not Italian, Italian text isn't read by the Spanish voice.

### The model

The model is fastText's `lid.176`, a language identification model from Facebook AI Research. It's a classifier, not a language model in the chatbot sense: it doesn't understand meaning or word order, and it doesn't generate anything. You give it text, and it gives back a probability for each of 176 languages.

It works by breaking words into short letter sequences ("Bonjour" gives "bo", "on", "nj", "jou", "our" and so on), looking up a learned set of numbers for each one, averaging them, and turning the average into probabilities. The letter sequences are why it copes with words it has never seen: "-ción" looks Spanish, "-ung" looks German. The averaging is why it's fast. It's also why it struggles with very short text, where there's little to average. The clause rules above are there to cover that weakness.

The small compressed version that Facebook publishes (916 KB) drops so much that it doesn't know common short words like "no", "Oui", or "army". The add-on ships its own compression of the full model instead, at 17 MB. `addon/lib/models/NOTICE.MD` gives the exact command. It runs through the `fasttext-predict` package, whose compiled module is in `addon/lib/`.

### The spelling dictionaries

The Windows spelling dictionaries give a second opinion that doesn't depend on the model. They come from the "Basic typing" part of a Windows language pack and are reached through the Windows Spell Checking API.

- A clause your default dictionary accepts completely needs 98 percent to switch. Rejected words are the strongest sign that text is foreign.
- A clause the model leans toward but isn't sure of switches when your default dictionary rejects one of its words and the other language's dictionary accepts all of them.
- A single word on its own, like a button or link label, never switches on the model alone. On one word the model is close to noise: it calls "Cancelar" English at 89 percent. A word switches only when your default dictionary rejects it and exactly one other language's dictionary accepts it.

The dictionaries make a big difference on short text. These were measured with English as the default and one other language set up, first without that language's dictionary and then with it. The test data was Lingua's word pairs and single words, and NVDA's translated interface strings:

- French: word pairs 67 to 82 percent, single words 0 to 64, interface strings 70 to 84
- Spanish: word pairs 65 to 74 percent, single words 0 to 60, interface strings 69 to 88
- German: word pairs 88 to 88 percent, single words 0 to 48, interface strings 62 to 87
- Italian: word pairs 80 to 92 percent, single words 0 to 76, interface strings 72 to 89

Full sentences hardly change, staying between 98 and 100 percent either way. The cost in English is small. With the French dictionary, 2 of 1,000 English single words switched: "plongeon", a French word in the English list, and "javascript". With the German one, 1 word ("interwest") and 2 of NVDA's 3,283 interface strings ("Aragonese" and "drft cmnt") switched. Spanish and Italian added none. Portuguese hasn't been measured, because its dictionary isn't installed on the test machine. The runs are in `results/dictionaries-fasttext.txt`.

That's why the add-on offers to install a missing dictionary when you add a language. Installing needs administrator rights, so it runs `Add-WindowsCapability` in an elevated PowerShell window (`mlang/langpack.py`).

### Strict mode

Strict mode asks a second recognizer before switching. That recognizer is Windows' own language detection, Extended Linguistic Services (`mlang/els.py`), and both have to agree. It switches less often, and so far it has never switched wrongly.

### Lines, characters, and typing

A guess is only as good as the text it gets, and NVDA often hands over less than a sentence.

**Lines.** When you arrow through wrapped text, NVDA reads one line at a time, and a line can start or end partway through a sentence. A line ending in "…side of the lake. A" has a one-word sentence at its end that can't be scored. When a line's edges can't be decided, the add-on fetches the text around the line and judges the cut sentences as wholes (`globalPlugins/dialingo/context.py`). Say all doesn't need this, because NVDA already gives it whole sentences.

**Characters and words.** A single letter or word can't be detected on its own. When you move by character or word, the add-on detects the whole line and uses the language at the cursor's position. That means stepping through "Bonjour" in a French sentence reads each letter, and its character description, with the French voice.

**Typing.** What you type is read in the language of your keyboard layout, as long as you have a voice for it.

### NVDA's own words

NVDA's names for roles and states, such as "button", "link", and "checked", in whatever language NVDA is running, are collected at startup and never scored.

## Speaking each language with its own voice

The user sets up a row for each language: a synthesizer, a voice, rate, pitch, volume, and a punctuation level. Your default language never has a row. It's whatever your normal synthesizer is set to.

### Rows on your normal synthesizer

If French is set up on the same synthesizer you already use, say Eloquence at a slower rate, there's no need for a second synthesizer. The plugin wraps the French text in rate, pitch, and volume commands, which every major synthesizer applies in the middle of speech. Commands NVDA adds itself, like the higher pitch for a capital letter, are adjusted so they add on top of the row's values.

### The Language table

A language set up on a different synthesizer needs the Language table driver. It loads your normal synthesizer inside itself as the host, and the synthesizers your rows use as guests.

- **You never pick it yourself.** Saving a row that uses another synthesizer switches NVDA to the Language table. Removing the last such row switches back. It only appears in NVDA's synthesizer list while it's needed (`mlang/policy.py`).
- **It looks like your normal synthesizer.** NVDA's voice settings and the settings ring show the host's settings, and changes go to the host's own configuration. If you leave the Language table, your synthesizer is exactly as you left it.
- **Guests never save settings.** A guest is a separate copy of a synthesizer, so a row's settings never overwrite your own settings for that synthesizer.
- **It always speaks.** If the table is broken or empty, it falls back to NVDA's usual order of synthesizers.

### Joining the pieces

Each utterance is cut at every change of language, and the pieces play in order across the guests (`mlang/scheduler.py`). Every piece ends with a private marker so the add-on knows when it's done. NVDA's own position markers, which keep the caret moving during say all, are passed on in order.

The hard part is the gap between pieces. Before the next synthesizer can start, the previous one has to finish playing. Every synthesizer reports "finished" differently, and most report it late. Eloquence reports done from a timer 0.3 seconds after it finishes synthesizing. SAPI 5 says it's done about a second after its speech ends, once the silence after it has played. Waiting for those reports produced pauses of up to a second at every language change.

So the add-on works out for itself when each piece's audio has actually played, and starts the next one then. SAPI 5's own markers can be half a second off, so for SAPI 5 the add-on puts its own queue in front of the audio player. It finds where the speech in each chunk ends by looking for the last loud sample, and it gets a callback when playback reaches that point. Online voices like the Edge neural voices take up to half a second to reach their server, so their next piece is sent early, and its audio is held until the voice before it finishes. Gaps between synthesizers are now typically 60 to 150 milliseconds, down from anywhere between 200 milliseconds and a full second.

Each synthesizer has its own quirks: when it reports done, how it reads rate commands, what it does when a call fails. Those are documented where they're handled, in `mlang/scheduler.py`, `mlang/hosts.py`, `mlang/sapi5host.py`, `mlang/playqueue.py`, and the driver itself.

### Windows voices

Windows has free voices for many languages. The add-on reads which ones are installed from the registry (`mlang/winvoices.py`). A language you haven't set up, which your synthesizer can't speak, goes to the Windows voice for it automatically. So with Eloquence as your synthesizer, Arabic text is read by the Windows Arabic voice with nothing to set up, as long as that voice is installed. A checkbox turns this off.

### Punctuation and voice dictionaries per language

Each row can have its own punctuation level. The add-on wraps NVDA's symbol processing so text in that row's language is processed at the row's level.

NVDA only loads the voice dictionary of the current voice. The add-on also applies each row's voice dictionary to the text in that row's language. It uses the same file NVDA would use if that voice were current, so entries are shared.

## The language lock

The language lock is an entry the add-on adds to NVDA's synth settings ring (`globalPlugins/dialingo/lock.py`). Set it to a language and everything is read in that language, with no detection. While a row's language is locked, the rest of the ring shows that row's settings instead of the synthesizer's, so you can adjust them on the fly. The ring's labels are also spoken in the locked language, using NVDA's and the add-on's translations, so the French voice isn't left reading English words.

Right after the lock is a detection entry. Normally it's the detection mode. While a row is locked, it turns detection on or off for that row's language only.

## Settings

Settings are stored in NVDA's configuration under `[dialingo]`, so configuration profiles work with them (`mlang/table.py`). Installing Dialingo removes the old multilanguage add-on and moves its settings across, profiles included (`mlang/rename.py`).

- `mode`: `off`, `script` (script and tags only), or `full`, the default
- `strict`: also require Windows' language detection to agree
- `detectInDefaultTagged`: check text tagged with the default language, on by default
- `useWindowsVoices`: use Windows voices for languages the synthesizer can't speak, on by default
- `defaultSynth`: the Language table's host
- `lock`: empty for Automatic, `default`, or a row's language
- `table`: the rows, as one JSON string

Row languages are written NVDA's way, as in `fr_FR`, never `fr-fr`. NVDA's character descriptions and symbol files only fall back from `fr_FR` to `fr` on the underscore.

## How well it works

All figures are with English as the default, unless stated otherwise. Full results are in `results/`, and the commands that produce them are under "Building and testing" below.

- **NVDA's own interface:** of NVDA's 3,283 English interface strings, with German, Spanish, French, Italian, and Portuguese set up, 1 switched by mistake ("drft cmnt", as German).
- **Sentences:** on the Lingua test set with French and Spanish set up, 99 percent of Spanish sentences and 98.5 percent of French ones were detected, with no false switches on 1,000 English sentences.
- **Short text:** two-word pairs are much harder. 72 percent were detected for Spanish and 81 percent for French, with the dictionaries installed.
- **Single words:** single words switch only through the dictionaries. About 56 percent of Spanish words and 60 percent of French words were detected, and 2 English words out of 1,000 switched.
- **Translated interfaces:** for short translated labels, German was at 85 percent and Portuguese at 46. Portuguese had no dictionary installed, and that dictionary is most of the difference.
- **Other scripts:** script-based detection is close to perfect. Russian, Ukrainian, Bulgarian, Arabic, Persian, Hindi, Chinese, Japanese, and Korean sentences were all at 97.5 percent or above when set up together, and English lines never switched.
- **Speed:** about 0.3 milliseconds for an English line, up to 3 for a Spanish sentence.

Results depend on which Windows dictionaries are installed. These runs had English, French, Spanish, German, and Italian.

## What it can't do

`KNOWN_GAPS.md` is the full list. The biggest limits come from judging a clause at a time:

- A foreign name or title inside an English sentence is read with the English voice.
- Short mixed lines like "Bonjour Pierre, comment vas-tu?" or vocabulary lists like "Orange, la naranja" can't be handled by clause rules.

Fixing those would take a model that labels each word using the words around it. Public benchmarks and training data exist for this, but it isn't planned until the current approach ships.

Whether strict mode should be the default is still an open question.

## Building and testing

Use 64-bit Python 3.13, the same version NVDA runs, so the compiled fastText module loads the way it will in NVDA. The commands below are for Git Bash. If the repository is on a network share that can't hold a virtual environment, set `UV_PROJECT_ENVIRONMENT` to a folder on a local drive.

```
export UV_PROJECT_ENVIRONMENT="${UV_PROJECT_ENVIRONMENT:-.venv}"
uv venv --python 3.13 "$UV_PROJECT_ENVIRONMENT"
uv pip install --python "$UV_PROJECT_ENVIRONMENT/Scripts/python.exe" fasttext-predict comtypes regex
export PYTHONUTF8=1
PY="$(cd "$UV_PROJECT_ENVIRONMENT" && pwd)/Scripts/python.exe"
(cd tests && "$PY" -m unittest discover)
"$PY" build.py
```

`build.py` writes `dist/dialingo-<version>.nvda-addon`. Open it with NVDA running to install it. NVDA's log at debug level shows a `dialingo:` line for anything that goes wrong.

### Measuring detection

The scripts in `harness/` run the real detector over test text:

- `"$PY" harness/harness.py fasttext`: the acceptance cases, which should all pass
- `"$PY" harness/dataset_eval.py fasttext datasets/ui-strings fr,es,de,it,pt`: NVDA's interface strings
- `"$PY" harness/dataset_eval.py fasttext datasets/lingua fr,es`: Lingua's sentences, word pairs, and single words. Add `--default ru` for another default language, and `--case title` or `--case upper` for headlines.
- `"$PY" harness/line_eval.py fasttext datasets/lingua en fr`: wrapped lines read alone, in context, and as whole paragraphs

Put `ensemble` in place of `fasttext` to measure strict mode, and set `HARNESS_NODICT=1` to turn the dictionaries off, or `HARNESS_NODICT=de` to hide one language's dictionary. `harness/model_compare.py` compares model files.

### Rebuilding the model

1. Download `lid.176.bin` from `https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin`.
2. Clone `https://github.com/facebookresearch/fastText`.
3. Compile `src\*.cc` with `cl /O2 /EHsc /std:c++17` from a Visual Studio x64 build tools prompt. On Windows on ARM, use `vcvarsarm64_amd64.bat`. Compile the files directly, because fastText's CMake setup makes two libraries with the same name on Windows.
4. Next to the model, run the quantize command from `addon/lib/models/NOTICE.MD`.

### Translations

The add-on is translated into the 63 languages NVDA supports. `i18n/extract.py` collects the add-on's strings, reusing NVDA's own translation wherever NVDA has the same string, so terms match NVDA's. The rest are in `i18n/translations/*.json`. `i18n/make_locale.py` checks them and builds the catalogs in `addon/locale/`. Don't edit those catalogs by hand.

The translations were machine-written and haven't been checked by native speakers. Corrections are welcome: fix the string in whichever `i18n/translations/*.json` file has it, then rerun both scripts.

## Repository layout

- `addon/`: the add-on as installed
  - `globalPlugins/dialingo/`: the plugin: the speech filter, settings panel, language lock, and line context
  - `synthDrivers/languageTable.py`: the Language table driver
  - `synthDrivers32/mlang_sapi5.py`: 32-bit SAPI 5 for the Language table, run in NVDA's 32-bit synthesizer host
  - `lib/mlang/`: the shared library, with detection, the scheduler, and synthesizer hosting
  - `lib/fasttext/` and the `.pyd` beside it: fasttext-predict
  - `lib/models/`: the language model
  - `doc/en/readme.md`: the user guide
  - `locale/`: generated translations
- `tests/`: unit tests, run on plain Python with NVDA stubbed out
- `harness/`: detection measurement scripts
- `datasets/`: test text from Lingua and NVDA's interface strings
- `results/`: saved measurement runs
- `i18n/`: translation sources and scripts
- `build.py`: builds the add-on package

## Licenses

Copyright (C) 2026 Rashad Naqeeb. The add-on is licensed under the GNU General Public License version 2, like NVDA; see `LICENSE`.

The language model is derived from fastText's lid.176, under Creative Commons Attribution-ShareAlike 3.0, and runs through fasttext-predict, under the MIT license. Lingua's test data is under the Apache License 2.0; see `datasets/lingua/NOTICE.md`. The NVDA translation catalogs in `datasets/ui-strings/po/` belong to NV Access and NVDA's translators, under GPL 2; see `datasets/ui-strings/NOTICE.md`.

## References

- NVDA source: `https://github.com/nvaccess/nvda`, especially `source/speech/` and `source/synthDriverHandler.py`
- fasttext-predict: `https://github.com/searxng/fasttext-predict`
- Windows Extended Linguistic Services: `https://learn.microsoft.com/en-us/windows/win32/intl/microsoft-language-detection`
- Windows Spell Checking API: `https://learn.microsoft.com/en-us/windows/win32/intl/spell-checker-api`
