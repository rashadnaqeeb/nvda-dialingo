"""The voice dictionaries of the rows' voices, applied to the text those voices speak.

NVDA keeps a voice dictionary per synthesizer and voice, but loads only the current voice's and applies it
to everything spoken. A row's voice has its own file among NVDA's voice dictionaries (the same file NVDA
would load if that voice were the current one), edited from the Dialingo panel with NVDA's dictionary
dialog. Its entries apply to the runs in the row's language, in the add-on's filter, ahead of NVDA's own
dictionaries. The files are reread when they change. NVDA is imported inside the functions, so `apply` runs
under the tests.

NVDA's own pass applies the current voice's dictionary to every string, whatever its language. A run a row
voice reads is not the current voice's, so `install` wraps that pass to leave the current voice's dictionary
out while `without_current_voice` is in effect; the default and temporary dictionaries still apply.
"""

import contextlib
import os
import threading

_dictionaries = {}  # path -> (modification time or None, SpeechDict)
_names = {}  # (synthesizer, voice id) -> the voice's display name, which names the file
_state = threading.local()  # skip_voice: whether NVDA's pass on this thread leaves out the voice dictionary


def path_for(synth, voice_name):
	"""NVDA's voice dictionary file for a synthesizer's voice."""
	from NVDAState import WritePaths
	from speechDictHandler import dictFormatUpgrade

	return os.path.join(
		WritePaths.voiceDictsDir, synth, dictFormatUpgrade.createVoiceDictFileName(synth, voice_name)
	)


def voice_definition(definitions):
	"""NVDA's definition of the current voice's dictionary among `definitions` (speechDictHandler.definitions).
	NVDA 2026.3 marks it by its class, with the lookup by type public; 2026.1 had the lookup only, private."""
	from speechDictHandler import types

	cls = getattr(types, "VoiceSpeechDictDefinition", None)
	if cls is not None:
		for definition in definitions._speechDictDefinitions:
			if isinstance(definition, cls):
				return definition
	lookup = getattr(definitions, "getDictionaryDefinition", None) or definitions._getDictionaryDefinition
	return lookup(types.DictionaryType.VOICE)


def current_path():
	"""The file of the voice dictionary NVDA has loaded for the current voice; None when unknown."""
	try:
		from speechDictHandler import definitions

		return voice_definition(definitions).path
	except Exception:
		return None


def is_current(path):
	current = current_path()
	return bool(current) and os.path.normcase(os.path.abspath(current)) == os.path.normcase(
		os.path.abspath(path)
	)


def voice_name(synth, voice):
	"""A voice's display name from a synthesizer instance that already exists; None when none does, so
	speech never waits for a synthesizer to load."""
	key = (synth, voice)
	name = _names.get(key)
	if name is not None:
		return name
	from . import hosts

	guest = hosts.existing(synth)
	if guest is None:
		return None
	try:
		info = guest.availableVoices.get(voice)
		name = info.displayName if info is not None else None
	except Exception:
		name = None
	if name:
		_names[key] = name
	return name


def load(path):
	"""The dictionary in a file, reread when the file changed; empty when there is none."""
	from speechDictHandler.types import SpeechDict

	try:
		mtime = os.stat(path).st_mtime
	except OSError:
		mtime = None
	cached = _dictionaries.get(path)
	if cached is not None and cached[0] == mtime:
		return cached[1]
	dictionary = SpeechDict()
	if mtime is not None:
		try:
			dictionary.load(path)
		except Exception:
			from logHandler import log

			log.debugWarning(f"dialingo: voice dictionary {path} could not be read", exc_info=True)
	_dictionaries[path] = (mtime, dictionary)
	return dictionary


def dictionary(synth, voice):
	"""The dictionary of a synthesizer's voice, or None when it has none or the voice cannot be named."""
	name = voice_name(synth, voice)
	if not name:
		return None
	loaded = load(path_for(synth, name))
	return loaded if loaded else None


def apply(seq, LangChangeCommand, dict_for_lang):
	"""`seq` with each text item passed through the dictionary of its language's row voice.

	dict_for_lang(lang) -> an object with `sub(text)` for a language whose row voice has entries, else None.
	Text before the first language command is the default language's and is left alone. The same sequence
	comes back when nothing changed.
	"""
	out = None
	lang = None
	for index, item in enumerate(seq):
		if isinstance(item, LangChangeCommand):
			lang = item.lang
			continue
		if not lang or not isinstance(item, str) or not item:
			continue
		dictionary = dict_for_lang(lang)
		if dictionary is None:
			continue
		text = dictionary.sub(item)
		if text != item:
			if out is None:
				out = list(seq)
			out[index] = text
	return out if out is not None else seq


@contextlib.contextmanager
def without_current_voice(skip=True):
	"""While in effect, and `skip` is true, NVDA's dictionary pass on this thread leaves out the current
	voice's dictionary."""
	previous = getattr(_state, "skip_voice", False)
	_state.skip_voice = bool(skip)
	try:
		yield
	finally:
		_state.skip_voice = previous


def process_without_voice(text, definitions, voice):
	"""NVDA's dictionary pass (speechDictHandler.processText) with the voice dictionary `voice` left out: every
	other enabled dictionary, in NVDA's order."""
	for definition in definitions:
		if definition is voice or not definition.enabled:
			continue
		text = definition.sub(text)
	return text


def install():
	"""Wraps NVDA's dictionary pass so `without_current_voice` can leave the current voice's dictionary out.
	NVDA's speech looks the pass up on the module at each call. Installed once; a failure inside runs NVDA's
	own pass."""
	import speechDictHandler

	original = speechDictHandler.processText
	if getattr(original, "_mlang_original", None) is not None:
		return

	def processText(text):
		if getattr(_state, "skip_voice", False):
			try:
				import globalVars
				from speechDictHandler import definitions

				if not globalVars.speechDictionaryProcessing:
					return text
				voice = voice_definition(definitions)
				return process_without_voice(text, definitions._speechDictDefinitions, voice)
			except Exception:
				from logHandler import log

				log.debugWarning("dialingo: the voice dictionary could not be left out", exc_info=True)
		return original(text)

	processText._mlang_original = original
	processText.__doc__ = original.__doc__
	speechDictHandler.processText = processText


def uninstall():
	import speechDictHandler

	original = getattr(speechDictHandler.processText, "_mlang_original", None)
	if original is not None:
		speechDictHandler.processText = original
