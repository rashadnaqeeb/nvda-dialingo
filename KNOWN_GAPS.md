# Known gaps

Things found and deliberately left alone, with the reason. When one is fixed, delete it.

## Left by decision

- One configured Latin-script language takes all Latin text it is detected in. Left as designed.
- Latin names inside non-Latin text (a French name in Russian) often go to the English row. Part of the item above.
- Close neighbours in a non-Latin script without a Windows spelling dictionary (Serbian and Russian, Hindi and Marathi) are sometimes confused. Measured; there is no dictionary to check against.
- A single Japanese word is often a single kana and is not switched. By design: one character is too little to tell.
- A single word switches on the dictionaries alone, so a configured language with no dictionary installed loses its shared words to one that has one: with Spanish installed and Portuguese not, "inválida" and "títulos" as buttons go to Spanish. Installing the dictionary fixes it; the panel offers to.
- With only French and Spanish configured, NVDA's "numLock numpad 0" to "9" switch to Spanish: "numLock" is not taken for an identifier in a clause of two words. Seen before the lone-word rule; not yet looked into.
- A clause the dictionaries call Spanish stays in the default when fastText's free guess prefers a language nobody configured: "amigo mío" is Chavacano to it. Letting the dictionaries overrule that check was measured: with Spanish configured, Portuguese sentences read as Spanish went from 178 to 208 of 1,000, Esperanto from 42 to 56, and Italian from 19 to 26, for 1.6 points on Spanish word pairs. The check is what keeps unconfigured neighbours out of a configured voice.
- With German configured and its dictionary installed, a rare English word or name standing alone that the English dictionary rejects and the German one knows switches to German by the lone-word rule: "interwest", and "Romanow" in Title Case, 1 and 2 of Lingua's 1,000 English single words. Neither is a common English word.
- A short Spanish clause made of words the English dictionary also knows ("Hola amigos" alone) needs 0.98 and scores 0.977. That bar is what keeps English clauses from switching. Inside a longer Spanish line it follows the line.
- A synthesizer that reports only Chinese (AiSound) sends English to a Windows voice when Windows voices are on, although it reads English itself. A row for English on that synthesizer keeps English there.

## Speech: could stall until the next keypress

- A synthesizer that fails silently, with neither an index nor done afterwards, holds all speech until the next cancel. Seen in the code of RHVoice (a message it cannot start) and Sonata (its helper process failing). A watchdog per piece would recover it, but a long line at a slow rate can legitimately run a long time without an index, so a watchdog could cut off good speech. Left until it is seen to happen.
- A synthesizer the add-on does not know, which reports done only once it is idle and fails right after a successful piece, has that done taken for the done of the successful piece. OneCore, Eloquence, and SAPI 4 are known and excluded. Rare.

## Speech: audible but not blocking

- 32-bit SAPI 5 voices, when the add-on's own driver cannot be loaded in NVDA's 32-bit synth driver host (NVDA's driver is then used, as without the add-on): the add-on cannot see the player in the other process, so it waits for SAPI 5 to report a piece's end marker a second time, once its audio has played. Its first reports, and its done, come when synthesis ends. SAPI 5 holds back the first 50 ms of audio and may let a mark play just before the audio ahead of it, so the next voice can still start a few tens of milliseconds early. A short piece reports its end marker only once, before its audio has played, so after it the next voice waits 0.45 seconds from SAPI 5's done, the most audio its player can still hold, even when less is left. A change of voice between two rows, and a change to another synthesizer, wait about a second.
- 64-bit SAPI 5: each row's voice has an instance of its own, so a change of voice is a change of synthesizer. The default and rows without a voice share one instance; after a preview in the settings dialog has changed its voice, the next piece on it waits once for its done, about a second after the speech.
- Online Neural voices (SAPI 5): the next piece goes to them while the voice ahead speaks, so their trip to the server is hidden only as far as that voice's piece lasts. After a short piece ("sì") on another synthesizer, the seam into one is still 0.2 to 0.25 seconds. Only one piece goes ahead at a time.
- 32-bit SAPI 5 voices: each voice a row gives it is an instance of its own, and each instance is a process of NVDA's 32-bit synth driver host, about 30 MB. A piece cannot go ahead to it while another voice speaks (the table cannot hold its audio in the other process), so an online voice through it would be heard waiting for its server.
- NVDA's own 32-bit SAPI 5 (sapi5_32 chosen as NVDA's synthesizer, or loaded by the table when the add-on's 32-bit driver cannot be): NVDA's bridge closes each pipe to its host process twice when it is shut down, the second time when the handle may already be another's. NVDA logs "Exception ignored in: <_io.BufferedReader>" (and BufferedWriter), Bad file descriptor, when the handle was free, and can crash when it was not: switching from it to the table, which starts processes of its own at once, crashed NVDA twice in three tries. The table's own instances are started with handles that are closed once each (sapi5host._launch). A fix belongs in NVDA.
- 64-bit SAPI 5: the queue takes a sample above 32 of 32767 (about -60 dB) as sound, close to the silence of the voices measured (0 for David and Zira, at most 16 for Aria) so that a quiet final consonant is not taken for silence. A voice whose silence is louder than that (dithered, or recorded noise) is found to end only with its audio, so after it the next voice waits as it did before the queue, about a second; and a piece with no sound above the bar frees SAPI 5 only once all of its audio has played.
- Over NVDA's 32-bit bridge (SAPI 4, SAPI 5, AiSound), inflection cannot be set; the row's inflection is ignored. NVDA's gap.
- Any 32-bit synthesizer in the table keeps NVDA's audio ducking off for as long as the language table is in use, not just while that row speaks. Loading it only when needed would delay the first utterance by the start of a process.
- A break at the very start of a piece on another synthesizer is trimmed as leading silence by NVDA's audio player.
- Sonata: two Sonata voices in the table (the default and a row, or two rows) reload a model on NVDA's main thread at every switch between them, freezing NVDA briefly.
- Sonata: a narrow window where the done of a cancelled utterance can land after the next one starts.
- eSpeak's rate multiplier is approximate, as in NVDA itself.
- Eloquence: the language and voice annotations it emits stay in effect on the instance into its next piece; only its memory of the last language is reset, on a change of voice.
- Acapela: a change of voice queues a stop on the driver's own thread, which every cancel ends and restarts, so in a rare order the stop could run while the next piece is starting and silence it. Read from the code only; not seen.

## Settings side effects

- Sonata remembers the last variant used per voice in its own settings; a Sonata row's variant is written there, so using that voice outside the table opens it in the row's variant.
- Vocalizer and Acapela: a row that carries no rate, pitch, or volume speaks at that voice's own engine values (Acapela resets all three on every change of voice). Rows made in the dialog always carry them.
- Vocalizer: its own settings panel re-initializes its engine when Vocalizer is not the synthesizer in use, which it is not while hosted. Expected to be harmless; not verified.
- Vocalizer: voices added while it is hosted are not seen until the table is rebuilt, and removing its licence does not switch away from it while hosted.
- eSpeak pitch and inflection 50 read back as 51, so the value is set again at each row switch. Harmless.
- With several Windows voices for one language, the implicit Windows row uses the first in registry order. A row picks another.
- With NVDA's "Automatic language switching" off, the language table still switches, but two things NVDA reads that setting for directly stay off: the language marks of Word documents read through Word's object model, which are not fetched (detection still judges the text), and the report of a language the synthesizer cannot speak. There is no check of NVDA's to wrap there.

## Not supported

- Code Factory's Vocalizer and Eloquence pack, the older Vocalizer Expressive driver, the original Sonata, and Dual Voice cannot load in NVDA 2026 (32-bit code in a 64-bit NVDA, or too old for its add-on API).
- WorldVoice is refused as a row and as the default: it is a language table itself and breaks an eSpeak guest and NVDA's index tracking.
- Acapela's own driver before 1.9.5 cannot load in NVDA 2026 (32-bit).

## Acapela driver that plays through its engine

Handled from its code alone, without running it. To check once it can be run:

- Whether its engine queues a second call or cuts the first short. It is sent one piece at a time either way, which costs nothing NVDA does not do itself.
- Whether its engine reports the end of a call cancelled by a reset. If it does, that done can finish the next piece early.
- Which number its engine reports for a mark it was given one higher; either is handled.
- It reports every notification for its newest instance, not the one speaking. The add-on keeps one instance, taking over the settings dialog's; a second one would get the first's notifications.
- It ignores pitch and volume commands, so a capital letter is not raised, and it resolves a rate command against a fixed value rather than its own rate. NVDA sends rate commands only from SSML, which is rare.
- It reports no language for its voices, so the language table cannot tell which language a row's voice speaks; the row's language is what the user entered.
