---
paths:
  - "addon/globalPlugins/**"
  - "addon/lib/mlang/table.py"
  - "addon/lib/mlang/catalogs.py"
  - "addon/lib/mlang/voicedict.py"
  - "addon/lib/mlang/langpack.py"
  - "tests/test_table.py"
  - "tests/test_catalogs.py"
  - "tests/test_voicedict.py"
  - "tests/test_langpack.py"
---

# The plugin's hooks into NVDA

## Speech filter

- Registered on `speech.extensions.filter_speechSequence`, which runs at the top of `speech.speak()`, before symbol processing and NVDA's language handling. NVDA's `getSpeechSequenceWithLangs` is moved after it so "report language changes" names detected languages.
- Steps: detection (`sequence.py`), prosody for rows on the synthesizer in use (`prosody.py`), row voice dictionaries (`voicedict.py`, applied ahead of NVDA's own, files reread on change). Each is wrapped separately.
- NVDA drops language commands unless automatic language switching is on. The plugin wraps `shouldMakeLangChangeCommand` and `shouldSwitchVoice` in `speech.languageHandling`, and the speech manager's own reference to the second, so they answer yes while the Language table is in use. On other synthesizers, with the setting off, the filter, symbol levels, and caret context all stand down, since a row's prosody or dictionary would land on the default voice.
- Say all speaks through `speechWithoutPauses`, which holds text to the last sentence end, so the filter gets whole sentences.
- The model loads on a background thread; until then speech passes undetected.

## Symbol levels

- Each row's level is applied by wrapping `speech.speech.processText`, which NVDA calls once per string with its language. Only NVDA's configured level is replaced; a level a caller asks for (all, when spelling) stands.

## Rows and the table (`table.py`)

- Settings live in `[multilanguage]`: `mode`, `strict`, `detectInDefaultTagged`, `useWindowsVoices`, `defaultSynth`, `lock`, `table` (JSON rows: language, synthesizer, optional voice, variant, rate, rateBoost, pitch, inflection, volume, symbol level, and `detect` written only when off).
- Row languages use NVDA's spelling (`fr_FR`), because NVDA's descriptions and symbol files fall back to `fr` only on the underscore. The row dialog rejects anything that isn't a language code.
- `Table.row_for` resolves a tag by exact match, then same language (`scripts.code`), then base language.
- A row with `detect` off is never chosen by any route: not as a stand-in for an unconfigured script, not by a free guess, not by typing echo, unless another row of the same language has detection on. Application tags reaching it are replaced with the default before detection. The lock still offers it.
- The voice is applied first, since changing it resets parameters in some engines.

## Language lock (`lock.py`, `catalogs.py`)

- NVDA rebuilds the ring from `supportedSettings` in `SynthSettingsRing.updateSupportedSettings` on every synthesizer or voice change. The plugin wraps it and appends the lock and detection entries to every ring, keeping the ring's place on them across rebuilds. The lock is NVDA's `SynthSetting` with values and storage replaced.
- Values: Automatic, the default, and each row except a dialect of the default.
- Locked: detection is skipped and every language command is replaced by one for the locked language at the start (none for the default). Caret context and typing echo stand down; spelling helpers get the locked locale. On a synthesizer other than the table, a lock on a row needs NVDA's automatic language switching. Mode off with lock on Automatic is treated as locked to the default (`Engine.language_lock`); the ring still shows Automatic.
- Locked to a row, the ring's other entries are the row's settings, built from existing instances only (the ring is rebuilt from inside synthesizer loading). Changes are written to the config table and handed to the driver with `update_row`, not a full table save, which would cancel speech and rebuild guests on every keypress. The ring is rebuilt after the running script finishes, because NVDA announces a ring rebuilt mid-script as having lost its place.
- The ring speaks the locked language: switching NVDA's language at run time wouldn't reach it, since setting names are translated at import. Each entry is renamed through a stand-in `DriverSetting`; `catalogs.py` traces each string back through the catalog in use and looks it up in the locked language's catalog of the same domain, the add-on's first, with NVDA's "synth setting" context first for names. Unknown strings, voice names included, stay as they are.
- The detection entry: on Automatic or the default it is `mode`; locked to a row it is that row's `detect`, written to config and passed with `update_row`.

## Dictionary install (`langpack.py`)

- `ShellExecuteEx` with `runas` on `powershell.exe`, waited on a thread, then the dictionary list is refreshed and the result reported.
