"""Minimal stand-ins for the NVDA modules the shared library imports, so tests run on plain Python."""
import sys
import types

lib = __import__("os").path.join(__import__("os").path.dirname(__file__), "..", "addon", "lib")
if lib not in sys.path:
    sys.path.insert(0, lib)


class SpeechCommand:
    pass


class SynthCommand(SpeechCommand):
    pass


class IndexCommand(SynthCommand):
    def __init__(self, index):
        self.index = index

    def __repr__(self):
        return f"IndexCommand({self.index})"

    def __eq__(self, other):
        return isinstance(other, IndexCommand) and other.index == self.index


class LangChangeCommand(SynthCommand):
    def __init__(self, lang):
        self.lang = lang
        self.isDefault = not lang

    def __repr__(self):
        return f"LangChangeCommand({self.lang!r})"

    def __eq__(self, other):
        return isinstance(other, LangChangeCommand) and other.lang == self.lang


class CharacterModeCommand(SynthCommand):
    def __init__(self, state):
        self.state = state

    def __repr__(self):
        return f"CharacterModeCommand({self.state})"

    def __eq__(self, other):
        return isinstance(other, CharacterModeCommand) and other.state == self.state


class BreakCommand(SynthCommand):
    def __init__(self, time=0):
        self.time = time


class BaseProsodyCommand(SynthCommand):
    def __init__(self, offset=0, multiplier=1):
        self._offset = offset
        self._multiplier = multiplier
        self.isDefault = offset == 0 and multiplier == 1

    @property
    def offset(self):
        return self._offset

    @property
    def multiplier(self):
        return self._multiplier

    def __eq__(self, other):
        return type(other) is type(self) and other._offset == self._offset and other._multiplier == self._multiplier

    def __repr__(self):
        return f"{type(self).__name__}(offset={self._offset})"


class RateCommand(BaseProsodyCommand):
    pass


class PitchCommand(BaseProsodyCommand):
    pass


class VolumeCommand(BaseProsodyCommand):
    pass


speech = types.ModuleType("speech")
commands = types.ModuleType("speech.commands")
for cls in (SpeechCommand, SynthCommand, IndexCommand, LangChangeCommand, CharacterModeCommand, BreakCommand, BaseProsodyCommand, RateCommand, PitchCommand, VolumeCommand):
    setattr(commands, cls.__name__, cls)
speech.commands = commands
sys.modules.setdefault("speech", speech)
sys.modules.setdefault("speech.commands", commands)
