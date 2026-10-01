# Multilanguage speech

This add-on does two things, each usable without the other.

- It reads untagged text in the language it is written in. A French sentence inside English prose is read by the French voice, while a French name inside an English sentence is not. Text in another writing system, such as Arabic, Cyrillic, or Chinese, goes to the voice for that script's language without any guessing.
- It speaks each language with the synthesizer and voice you choose for it, switching between synthesizers in the middle of an utterance. This is the "Language table (multilanguage)" synthesizer.

The add-on depends on nothing but the voices you install. It works with the synthesizers NVDA ships with and with any synthesizer add-on.

## What a language needs

- A voice that speaks it: one of your synthesizer's, or a Windows voice (the "Text-to-speech" feature of the Windows language pack).
- Its Windows spelling dictionary (the "Basic typing" feature of the language pack). The add-on works without it, but detection is noticeably less accurate: the dictionaries settle the short clauses the recognizer cannot.

When you add a row for a language with no dictionary, the add-on offers to install it: Windows asks for administrator permission, downloads it from Windows Update in a PowerShell window, and NVDA reports when it is in. The languages list has a Dictionary column, and the "Verify language pack" button checks an existing row: it reports the dictionary as installed, or offers to install it. Your default language's dictionary matters as much; Windows installs it with the display language. The add-on installs only the dictionary, not Windows voices: a row needs a voice that is already installed.

## Setting up

Your synthesizer, with its voice and settings, speaks your default language. That never changes. In NVDA's settings, under Multilanguage, add a row for each other language: its synthesizer, its voice, and its rate, pitch, and volume. A row can also have its own punctuation/symbol level (none, some, most, or all); "Same as NVDA" uses the level in NVDA's speech settings. The language field fills in from the voice; you can type another language code. The Test button speaks a sample. A new row starts from the synthesizer's own values, so a row saved unchanged speaks as that synthesizer does on its own.

Each row in the languages list has a check box; press space to check or uncheck it. Unchecked, the language is never switched to, even where a voice speaks it or the text is in its writing system. Text an application tags with that language is read as if it had no tag, and detected among the checked languages. The row keeps its settings, and the language lock can still be set to it. A new row is checked.

Each row's voice has a voice dictionary of its own. NVDA applies the voice dictionary of your synthesizer's current voice to everything it speaks; the entries you add for a row's voice apply to the text that voice speaks. The "Voice dictionary" button in the panel opens NVDA's dictionary dialog on the selected row's voice, the same dictionary NVDA uses when that voice is your current voice, so entries made either way are shared.

There are two ways the rows are used.

- With your usual synthesizer, rows for that synthesizer apply their rate, pitch, and volume: French on Eloquence at a slower rate needs nothing else. The synthesizer picks its own voice for the language, as it does for tagged web content. Rows for other synthesizers are not used in this mode.
- A row for a different synthesizer, say a particular Arabic voice from OneCore while Eloquence is your synthesizer, is spoken through the add-on's own "Language table (multilanguage)" synthesizer, which hosts your usual synthesizer as the default, with its voice settings and options shown in NVDA's voice settings as before, its settings kept in its own configuration, and its voice dictionary in use, and adds the rows. You do not select it yourself: saving such a row switches to it, and removing the last such row switches back to your synthesizer, keeping any settings you changed in between. It only appears in NVDA's synthesizer dialog while it is needed. The default synthesizer can be changed in the Multilanguage panel.

Languages without a row are handled this way.

- A language with no row that your synthesizer cannot speak goes to the Windows voice installed for it, if there is one: with Eloquence, Arabic text is read by Windows' Arabic voice as soon as that voice is installed (the "Text-to-speech" feature of the Arabic language pack), with nothing to configure. A check box in the panel turns this off.
- Text in a script that no voice you have can speak is still tagged with its language, so NVDA announces it, "Arabic, not supported" by default, before the voice attempts it. NVDA's speech setting "Report when switching to language is not supported by synthesizer" chooses speech, a beep, or nothing.

The add-on turns on NVDA's "Automatic language switching" setting when needed; NVDA discards language commands while it is off. "Report language changes while reading" in NVDA's speech settings announces the detected language by name.

Several rows may use the same synthesizer. Changing rows on one synthesizer waits for the previous piece to be synthesized; changing synthesizers waits for the previous one to finish playing, so with Eloquence in the mix a switch to another synthesizer carries Eloquence's own short pause after speech.

A row for a dialect of the default language (British English beside American) is used only when NVDA's "Automatic dialect switching" is on; NVDA folds dialects of the default language into it otherwise.

A character or word you arrow to is spoken in the language its line reads in at that spot, with that language's character descriptions, so stepping through a French word letter by letter stays in the French voice.

Windows spelling dictionaries sharpen detection. The add-on offers to install the "Basic typing" feature of the Windows language pack when a row is added; it can also be added by hand (Settings, Time & language, Language & region, Add a language). The add-on uses the dictionaries where they exist and needs nothing else from the pack.

## Detection modes

- Off: no language switching at all. Everything is read in your default language, including text an application tags with another language. The language lock still works.
- Script and tags only: text in a writing system the default language does not use is switched, and text an application tags with a language is read in that language; text in the default script is left alone. This mode never guesses.
- Full: as above, and text in the default script is judged clause by clause among the default language and the configured languages written in that script. This is the default mode.

Strict mode asks Windows' own language detection to agree with the add-on's recognizer before switching. It switches less often and, so far, never wrongly.

"Detect languages inside text an application tagged with the default language" treats a page's document language as no information: a French paragraph on a page marked English is still detected. Turn it off to trust such tags.

## What full mode does and does not switch

- Two or more ordinary words are needed for the language to be guessed. Text that is a single word, such as a button or a link, switches only on the spelling dictionaries: the default language's dictionary must reject it and exactly one other configured language's dictionary must know it. Install the dictionary for each language you configure; the panel offers to.
- Names, abbreviations, numbers, paths, and identifiers are not counted. With German configured, a capitalized word that is clearly a German noun ("Dateifreigabe") counts, since German capitalizes every noun; a German name ("Müller", "Berlin") still does not.
- Headlines are the exception: in a line of three or more words that all start with a capital, or two or more in capitals, every word counts, and the line must be nearly certain to switch.
- A short clause follows the language of its neighbors in the same sentence: "No" in "¿Tú eres Miguel? No, yo no soy Miguel." stays Spanish.
- A sentence made only of short clauses is judged as a whole, and a one-word sentence follows the rest of its line: "¡Hola! Soy Alberto, encantado." is read in Spanish.
- The Spanish opening marks "¿" and "¡" are read by the voice of the sentence they open.
- A foreign clause between clauses of the default language must be nearly certain.
- A clause the default language's spelling dictionary accepts whole needs stronger evidence. Windows' spelling dictionaries are used where installed.
- A confident guess for a language nobody configured is left alone: Italian is not read by the Spanish voice.
- Tags from applications are distrusted when the text contradicts them: a Russian tag on Latin text is dropped, and a French tag is dropped from clauses that read as the default language.

## Chinese: Mandarin and Cantonese

A row for Chinese (Hong Kong) or Chinese (Macau), the languages Cantonese voices report, is Cantonese. With rows for both Mandarin and Cantonese, text written in spoken Cantonese is read by the Cantonese voice and all other Chinese, in simplified or traditional characters, by the Mandarin voice. With only one Chinese row, it reads all Chinese.

## Typing echo

With NVDA's typed character or typed word echo on, what you type, and a character you delete with backspace, is read in the language of your keyboard layout, as long as a language row or one of your voices speaks it. With the keyboard set to French, typed letters, punctuation, and words are read in French. A letter in a writing system the keyboard does not write, such as Chinese from an input method on another keyboard, goes to the voice for its writing system.

## Language lock

NVDA's synth settings ring has a Language lock entry, after the synthesizer's own settings. Move to it with NVDA+Control+left or right arrow (NVDA+Shift+Control on the laptop layout) and change it with NVDA+Control+up or down arrow.

- Automatic, the default, switches languages as configured.
- Your default language, or any language in the table, reads everything in that language, with its voice and settings, and switches nothing: neither detection nor the languages applications tag their text with. Characters and their descriptions are read in it too.

While a language in the table is locked, the rest of the ring shows that language's settings instead of your default voice's, and changing one saves it to that language at once. On the Language table synthesizer that is its voice, variant, rate, rate boost, pitch, inflection, and volume, as its synthesizer offers them; a language spoken by your own synthesizer has rate, pitch, and volume, since that synthesizer picks the voice. Choosing a new voice keeps the language's variant; if the new voice does not have it, pick another with the Variant entry.

While a language in the table is locked, the ring also speaks that language: its entries' names, and words such as on, off, and Automatic, come from NVDA's and the add-on's translations for it, so the language's voice is not reading another language's words. Voice names, the names of languages in the lock, and settings of synthesizer add-ons are left as they are. A language NVDA has no translation for keeps NVDA's own.

The choice is saved, and stays until you set it back to Automatic. A language later removed from the table returns the lock to Automatic.

Right after the Language lock comes a language detection entry.

- While the lock is on Automatic or your default language, it is the detection mode: Off, Script and tags only, or Full, the same setting as in the Multilanguage panel.
- While a language in the table is locked, it is that language's detection, on or off, the same as its check box in the languages list. Nothing is detected while the lock is on, so the change is heard once the lock is back on Automatic.

## Scripts
Two scripts, without default gestures, are in the Speech category of NVDA's Input Gestures dialog: one cycles the detection mode, one toggles strict mode.

## Licenses

The language recognizer is derived from fastText's lid.176 language identification model (Creative Commons Attribution-Share-Alike 3.0) through fasttext-predict (MIT). The add-on itself is GPL 2, like NVDA.
