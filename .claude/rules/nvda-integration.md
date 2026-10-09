---
paths:
  - "addon/globalPlugins/**"
  - "addon/installTasks.py"
  - "addon/lib/mlang/leaving.py"
  - "addon/lib/mlang/rename.py"
  - "addon/lib/mlang/update.py"
  - "addon/lib/mlang/nvdaconf.py"
  - "tests/test_leaving.py"
  - "tests/test_rename.py"
  - "tests/test_update.py"
  - "tests/test_install_tasks.py"
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
- The same wrapper gives the default's locale to a language the table reports unsupported (no loaded row, no Windows voice, and the host can't speak it), since the default voice reads it. NVDA would name symbols in the tag's language, and the add-on makes language commands even with "Automatic language switching" off. Only on the table: other synthesizers' `languageIsSupported` can't be trusted.

## Rows and the table (`table.py`)

- Settings live in `[dialingo]`: `mode`, `strict`, `detectInDefaultTagged`, `useWindowsVoices`, `defaultSynth`, `lock`, `table` (JSON rows: language, synthesizer, optional voice, variant, rate, rateBoost, pitch, inflection, volume, symbol level, and `detect` written only when off).
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

## Leaving (`mlang/leaving.py`, `installTasks.py`)

- With the add-on gone, NVDA can't load the saved `languageTable` and falls back at every start without saving. So when the add-on is removed or disabled, every configuration file naming `languageTable` (base and each profile) gets its own `defaultSynth`, else the base's, else `auto`. Only that key changes on disk; the base in memory is updated too, since NVDA saves it on exit. The base is marked `leftTable`.
- Removal: `installTasks.onUninstall`, which NVDA runs at the start of the next session before any synthesizer loads, and also for the old copy on every update. Updates are skipped (the name is in `PENDING_INSTALL`). It imports `mlang` from its own `lib` and drops those modules again, so a later copy imports its own.
- Disable: the plugin's `terminate`, when the name is in `PENDING_DISABLE`. NVDA has already saved its configuration by then.
- Coming back (re-enabled or reinstalled): `return_to_table` clears `leftTable` and, if NVDA is still on the host, runs `settings.follow_table` after startup to select the table again if needed.
- Not handled: an update whose new copy then fails to install leaves the saved `languageTable`.

## After an install or update (`mlang/update.py`)

- `installTasks.onInstall` marks the base configuration (`followTable`), in memory and on disk, where it has a `[dialingo]` section. At the next start the plugin drops the mark the same way and, if the table has rows, runs `settings.follow_table` after startup. A new version may need the table where the old one did not, and the panel only switches on its next save.

## The rename from multilanguage (`mlang/rename.py`)

- Until 1.0 the add-on's ID and config section were `multilanguage`; NVDA takes Dialingo for a different add-on. `installTasks.onInstall` copies `[multilanguage]` to `[dialingo]` (memory and every file on disk) so the language table driver, which loads before plugins, finds its settings at the next start, and requests the old add-on's removal so both don't load. The plugin's `__init__` then drops `[multilanguage]`, carrying over `leftTable` if the old copy's uninstall set it.
- The driver name stays `languageTable` so `speech.synth` keeps working across the rename. Don't rename it.
- `nvdaconf.py` reads and writes NVDA's config files the way NVDA does; `leaving.py` and `rename.py` share it. Modules installTasks imports must import `nvdaconf` at module level, since installTasks drops `mlang` from `sys.modules` after importing.
