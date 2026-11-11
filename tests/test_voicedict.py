"""The row voices' dictionaries on a speech sequence: only the text in a language with a dictionary changes.
NVDA's own dictionary pass, which leaves the current voice's dictionary out of text a row voice reads."""

import enum
import sys
import types
import unittest

import nvda_stub  # noqa: F401
from speech.commands import IndexCommand, LangChangeCommand

from mlang import voicedict
from mlang.voicedict import apply


class Definition:
	"""A stand-in for NVDA's SpeechDictDefinition: appends its name to what it processes."""

	def __init__(self, name, enabled=True):
		self.name = name
		self.enabled = enabled

	def sub(self, text):
		return text + " " + self.name


class VoiceDefinition(Definition):
	pass


class DictionaryType(enum.Enum):
	TEMP = "temp"
	VOICE = "voice"
	DEFAULT = "default"


class Dictionary:
	def __init__(self, **replacements):
		self.replacements = replacements

	def sub(self, text):
		for pattern, replacement in self.replacements.items():
			text = text.replace(pattern, replacement)
		return text


class ApplyTest(unittest.TestCase):
	def test_only_runs_with_a_dictionary_change(self):
		arabic = Dictionary(**{"ai": "artificial intelligence"})
		dictionaries = {"ar": arabic}
		seq = [
			"ai here",
			LangChangeCommand("ar"),
			"ai there",
			IndexCommand(1),
			"and ai",
			LangChangeCommand("fr"),
			"ai too",
			LangChangeCommand(None),
			"ai back",
		]
		out = apply(seq, LangChangeCommand, dictionaries.get)
		self.assertEqual(
			out,
			[
				"ai here",
				LangChangeCommand("ar"),
				"artificial intelligence there",
				IndexCommand(1),
				"and artificial intelligence",
				LangChangeCommand("fr"),
				"ai too",
				LangChangeCommand(None),
				"ai back",
			],
		)
		self.assertIsNot(out, seq)
		self.assertEqual(seq[2], "ai there")  # the input is not modified

	def test_same_sequence_when_nothing_changes(self):
		seq = ["plain", LangChangeCommand("ar"), "plain", ""]
		self.assertIs(apply(seq, LangChangeCommand, lambda lang: Dictionary(x="y")), seq)
		self.assertIs(apply(seq, LangChangeCommand, lambda lang: None), seq)

	def test_base_language_lookup_is_the_callers(self):
		asked = []

		def dict_for(lang):
			asked.append(lang)
			return None

		apply([LangChangeCommand("ar_SA"), "a", LangChangeCommand("ar_SA"), "b"], LangChangeCommand, dict_for)
		self.assertEqual(asked, ["ar_SA", "ar_SA"])


class CurrentVoiceTest(unittest.TestCase):
	"""NVDA's pass with the current voice's dictionary left out, against stand-ins for its modules."""

	def setUp(self):
		self.temp = Definition("temp")
		self.voice = VoiceDefinition("voice")
		self.default = Definition("default")
		self.off = Definition("off", enabled=False)
		self.all = [self.temp, self.voice, self.off, self.default]

	def stub(self, name, module):
		previous = sys.modules.get(name)
		sys.modules[name] = module
		self.addCleanup(
			lambda: (
				sys.modules.pop(name, None) if previous is None else sys.modules.__setitem__(name, previous)
			)
		)

	def stub_nvda(self, voice_class=True, public_lookup=True, processing=True):
		by_type = {DictionaryType.VOICE: self.voice}
		definitions = types.SimpleNamespace(_speechDictDefinitions=self.all)
		if public_lookup:
			definitions.getDictionaryDefinition = by_type.__getitem__
		else:
			definitions._getDictionaryDefinition = by_type.__getitem__
		dict_types = types.SimpleNamespace(DictionaryType=DictionaryType)
		if voice_class:
			dict_types.VoiceSpeechDictDefinition = VoiceDefinition

		def original(text):
			for definition in self.all:
				if definition.enabled:
					text = definition.sub(text)
			return text

		package = types.ModuleType("speechDictHandler")
		package.definitions = definitions
		package.types = dict_types
		package.processText = original
		self.stub("speechDictHandler", package)
		self.stub("speechDictHandler.definitions", definitions)
		self.stub("speechDictHandler.types", dict_types)
		self.stub("globalVars", types.SimpleNamespace(speechDictionaryProcessing=processing))
		self.stub(
			"logHandler", types.SimpleNamespace(log=types.SimpleNamespace(debugWarning=lambda *a, **k: None))
		)
		return package, original

	def test_the_others_apply_in_order_without_the_voice(self):
		self.assertEqual(voicedict.process_without_voice("x", self.all, self.voice), "x temp default")

	def test_the_voice_definition_on_either_nvda(self):
		for voice_class, public_lookup in ((True, True), (False, True), (False, False)):
			with self.subTest(voice_class=voice_class, public_lookup=public_lookup):
				package, _ = self.stub_nvda(voice_class, public_lookup)
				self.assertIs(voicedict.voice_definition(package.definitions), self.voice)

	def test_the_wrapper_leaves_the_voice_out_only_while_asked(self):
		package, original = self.stub_nvda()
		voicedict.install()
		self.addCleanup(voicedict.uninstall)
		voicedict.install()  # a second install does not wrap the wrapper
		self.assertIs(package.processText._mlang_original, original)
		self.assertEqual(package.processText("x"), "x temp voice default")
		with voicedict.without_current_voice():
			self.assertEqual(package.processText("x"), "x temp default")
			with voicedict.without_current_voice(False):
				self.assertEqual(package.processText("x"), "x temp voice default")
			self.assertEqual(package.processText("x"), "x temp default")
		self.assertEqual(package.processText("x"), "x temp voice default")
		voicedict.uninstall()
		self.assertIs(package.processText, original)

	def test_nothing_applies_while_nvda_has_dictionaries_off(self):
		package, _ = self.stub_nvda(processing=False)
		voicedict.install()
		self.addCleanup(voicedict.uninstall)
		with voicedict.without_current_voice():
			self.assertEqual(package.processText("x"), "x")

	def test_a_failure_runs_nvdas_own_pass(self):
		package, _ = self.stub_nvda()
		package.definitions._speechDictDefinitions = None  # not iterable
		voicedict.install()
		self.addCleanup(voicedict.uninstall)
		with voicedict.without_current_voice():
			self.assertEqual(package.processText("x"), "x temp voice default")


if __name__ == "__main__":
	unittest.main()
