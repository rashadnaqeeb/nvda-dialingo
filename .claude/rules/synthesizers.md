---
paths:
  - "addon/synthDrivers/**"
  - "addon/synthDrivers32/**"
  - "addon/lib/mlang/scheduler.py"
  - "addon/lib/mlang/hosts.py"
  - "addon/lib/mlang/sapi5host.py"
  - "addon/lib/mlang/playqueue.py"
  - "addon/lib/mlang/pipes.py"
  - "addon/lib/mlang/prosody.py"
  - "addon/lib/mlang/policy.py"
  - "addon/lib/mlang/winvoices.py"
  - "tests/test_scheduler.py"
  - "tests/test_hosts.py"
  - "tests/test_sapi5host.py"
  - "tests/test_playqueue.py"
  - "tests/test_pipes.py"
  - "tests/test_prosody.py"
  - "tests/fake_bridge.py"
---

# The Language table and its guests

Most of this is also in the code's docstrings, next to what it explains. Keep both in step.

## Host and settings

- The host is the synthesizer in use when the driver is first selected, stored as `defaultSynth`. After that only the panel changes it; a synthesizer picked in NVDA's own dialog is not adopted.
- The driver keeps no settings of its own. `initSettings`, `loadSettings`, and `saveSettings` use the host's config section. NVDA's inherited versions would refill the host from the driver's section, and since NVDA never writes a value equal to the default, missing keys come back as 50 (Eloquence at volume 50, roughness 50).
- The synth settings ring writes to the driver's section, which nothing reads, so changes made outside NVDA's settings dialog are written to the host's section at once. Inside the dialog nothing is written before OK, so Cancel still works.
- No guest saves settings on terminate, the host included. OneCore reports its engine's rate, pitch, and volume, which change only with the next utterance, so a OneCore guest that never spoke would store the engine defaults over the user's.
- A snapshot of the host's values is the default row; driver reads (and `language`) come from the snapshot, never from the last row run. Otherwise the ring would save a row's rate as the user's, and with "trust voice's language" a row's language would capture all speech. The snapshot covers every saved setting, because a row's variant can reset others (Eloquence copies a preset voice). After a profile switch the snapshot is read from the host's section, because eSpeak reports old values while busy.
- A row whose language is the default's in another dialect is ignored, since NVDA opens every utterance with the default's tag.
- Leaving the table writes the host's current values to the host's own section, so nothing heard changes.

## Guests (`hosts.py`)

- Guests are NVDA driver instances created with `initSettings()` and detached from the config-save hook.
- Creating a driver instance repoints the synth settings ring and the voice dictionary; both are restored afterwards. `speechDictHandler.loadVoiceDict` is wrapped so a load for the table loads the host's dictionary for the host's voice.
- The settings dialog's temporary instance is taken over rather than a second created, because eSpeak and Vocalizer keep their engine in module globals that a second instance re-initializes.
- Vocalizer's own switching by script is turned off for rows. Sonata fills NVDA's open voice settings lists on every voice change, so only the synthesizer in use may. The default language is read from the default variant first (Sonata's multilingual voices have a variant per language).
- WorldVoice is refused as guest and as default: it is a language table itself, re-raises its engines' notifications as the synthesizer in use, patches NVDA, and starts NVDA's eSpeak inside itself.
- A default synthesizer that fails to load is stood in for that time only, never by silence. An empty or broken table falls back to NVDA's default synthesizer order.

## Selection (`policy.py`)

- The table is needed when a saved row names another engine than the one speaking, or a row on that engine carries a setting prosody commands can't (voice, variant, rate boost, inflection) other than the engine's saved value, or Windows voices are on and an installed Windows voice speaks a language the engine can't. Without the table the engine picks its own voice per tag: Vocalizer Expressive takes the first voice whose language starts with the tag, so an es_CO row voice gets `es` and `es_CO` but not `es_MX`, which falls to the default voice. Right after the default changes, the new engine is judged, loaded for the question if needed.
- Saving the panel switches to or from the table. NVDA's start does not, so a synthesizer the user picked in NVDA's dialog stays. The one exception is the first start after an install or update with rows saved (`update.py`), since a new version may need the table where the old one did not: 1.0.1 made a row with its own voice need it, and rows saved before stayed on the bare synthesizer until the next save. `check()` lists the driver only while it is needed or selected.
- `winvoices.py` reads OneCore voice tokens from the registry with the same validity checks as NVDA's OneCore driver, so OneCore isn't loaded just to ask. Unconfigured languages go to an implicit row on OneCore.

## Scheduling (`scheduler.py`)

- Cut at every language command that changes the row. A row's piece has its language commands removed; anything else goes to the default row with commands kept. Command-only pieces merge into a neighbour.
- Every piece ends in a private index marker; NVDA's indexes inside are remapped to private ones. The driver re-emits NVDA's indexes and done as itself, because the speech manager only honours the current synthesizer's notifications.
- Same guest and row: sent without waiting. Row change on one guest: waits for the previous piece's marker. Guest change: also waits for done, because Eloquence reports marks when audio is queued. Voice change on one guest also waits for done (Vocalizer stops its audio, SAPI 5 rebuilds its engine).
- Rows are reapplied on every send, skipped when the guest already carries that row. A new voice clears Eloquence's memory of its last language.
- Done semantics: OneCore, Eloquence, SAPI 4 report done when their queue is empty. eSpeak, Vocalizer, RHVoice, SAPI 5 report after each call with the next still queued, so a done after one of the guest's markers while a later piece is in flight is taken as that call's. A done with none of the guest's markers reached is a failed synthesis. eSpeak's done is also checked against its queue (a cancelled utterance's done can arrive late).
- A guest that never reports done is freed at its last marker. A piece with no guest, a failed `speak`, or no progress (silence driver) is treated as done, and its NVDA indexes are still reported in order. OneCore whose first utterance fails stays marked speaking forever; on the add-on's instances that is completed.
- Cancel cancels every guest with pieces in flight and drops index maps. Pause goes to the speaking guest and holds the seam.

## Freeing a guest early

- Eloquence (IBMTTS) signals done from a timer 0.3 s after synthesis ends. Its player is asked to report when audio up to each end marker has played (`on_played`), which frees it; its pending done is cancelled.
- OneCore reports each mark once the audio before it has played, and done 0.2 s after the end marker. Another guest may follow at the end marker. A voice change on it, or its own piece after another guest's, would wait for that silence, so its player is stopped once the end marker has played (`cuts_silence`). One engine per process: no instance per voice. Mark to Zira: 60 to 130 ms, from 190 to 320.
- SAPI 5 places marks in the audio itself, inaccurately (Zira's end marker 0.5 to 0.7 s early; David's after the pause). The table hosts it as a subclass (`sapi5host.py`) whose audio goes through a queue fed to NVDA's player by its own thread (`playqueue.py`). Each chunk with speech is cut after its last loud sample (above 32 of 32767), plus 20 ms carried into a quiet next chunk, and a probe callback goes there. The request's last probe is the end of speech. Bookmarks NVDA's driver would report at request end are reported after their audio plays.
- SAPI 5 and the Speech Platform keep an instance per row voice (a voice change is then a guest change): David to Zira 75 to 205 ms, from 0.8 to 1 s. No other engine can: OneCore runs one engine per process, eSpeak and Vocalizer use module globals, Acapela reports for its newest instance, Sonata reloads its model per utterance.
- When a piece goes back to SAPI 5 after another guest's, the silence left of its previous piece is dropped from the queue and player.
- SAPI 5 done is held until the player has played what it was fed. Its marks are not held: they come from inside the player's callbacks, and feeding the player there corrupts its callback list and crashes NVDA.
- Look-ahead: while one guest speaks, the next piece may go to an idle SAPI 5 instance with its queue held, so an online voice's server trip (0.3 to 0.6 s for Edge voices via NaturalVoiceSAPIAdapter) overlaps. One piece ahead at a time; cancel drops it; a guest sent a piece in turn always plays. Aria to Guy 65 to 100 ms, from 295 to 600.
- If NVDA's SAPI 5 driver lacks what the subclass relies on, it is hosted unmodified.

## 32-bit SAPI 5

- Runs in NVDA's 32-bit synth driver host. The table's proxy (`sapi5host.Hosted32`) makes it load `synthDrivers32/mlang_sapi5.py`, with the same queue. The host reports only indexes and done, so end of speech comes back as the end marker plus 1,000,000. A piece after another voice's starts with an index telling the driver to drop leftover silence. Its done can't be told from a later one, so a cancel stops any guest whose done is pending. IBMTTS and 32-bit Zira: 70 to 110 ms, from about 1 s.
- If the add-on's driver fails to load there, NVDA's own is used and the host process started for it is closed.
- On WASAPI (which the bridge can't turn off) it reports every unplayed mark then done at synthesis end, then each mark again once played; the second report of the last end marker frees it. A short piece's end marker is reported only once, early, so it is freed 0.45 s after done.
- NVDA's bridge closes each pipe to the host twice at shutdown, which can close another NVDA handle and crash it (NVDA issue 20933). While the add-on runs, every connection to a 32-bit host gives its stream duplicate handles and closes the originals itself (`pipes.py`). Switching NVDA's own synthesizers every 0.8 s crashed 3 runs of 6 without it, none with it.

## Acapela

- Reports only the last mark of each audio block, so an end marker also reports the unreported NVDA indexes and earlier lost markers.
- Writes each mark one higher than given; the scheduler hands out only even numbers and takes an odd one down.
- Cancel leaves queued calls, so they are dropped first. Setters bypass the synthesis lock and its end marker comes mid-synthesis, so any row change waits for done. Reports done twice (synthesis end, ignored; queue empty, used).
- The other Acapela driver of the same name has no queue, reports done per call, and may be cut short by the next call, so it gets one piece at a time. Its voices give no language, so it is taken to speak every language.

## Prosody (`prosody.py`, and rewriting in the scheduler)

- On the synthesizer in use, a row's runs are wrapped in `RateCommand(offset=...)` and the like; NVDA's own prosody commands inside are rebased on the row's offset (capital +30 in a run at +10 becomes +40, reset becomes +10).
- In the table, NVDA computes commands from the driver's config values, not the piece's, so each is rewritten for the row in the guest's form: Eloquence reads absolute values; OneCore, SAPI 5, and eSpeak read the multiplier (computed from the row's value, since eSpeak reports old values while busy); RHVoice uses NVDA's SSML converter (multiplier); Vocalizer adds the offset to its own current value, so it passes unchanged, as do the 32-bit drivers (SAPI 4, SAPI 5, AiSound). The form is decided by what the driver's code reads.
- A command the guest doesn't support is dropped (a SAPI 4 voice without pitch fails the whole piece on one). Rate boost is set before rate, because its setter re-applies the rate it reads back.
