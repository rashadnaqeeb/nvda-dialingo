"""mlang.leaving: when the add-on is removed or disabled, each configuration that names the language table names its
host instead, and the base configuration is marked so the plugin selects the table again once it is back."""
import contextlib
import sys
import types
import unittest
from unittest import mock

import nvda_stub  # noqa: F401

from mlang.leaving import leave, leave_nvda


class Leave(unittest.TestCase):
    def test_base_gets_its_host_and_the_mark(self):
        base = {"speech": {"synth": "languageTable"}, "dialingo": {"defaultSynth": "ibmeci"}}
        self.assertEqual(leave(base, []), [base])
        self.assertEqual(base["speech"]["synth"], "ibmeci")
        self.assertIs(base["dialingo"]["leftTable"], True)

    def test_no_host_gives_nvda_default(self):
        base = {"speech": {"synth": "languageTable"}, "dialingo": {"table": "[]"}}
        leave(base, [])
        self.assertEqual(base["speech"]["synth"], "auto")

    def test_no_section_gives_nvda_default_and_makes_one_for_the_mark(self):
        base = {"speech": {"synth": "languageTable"}}
        leave(base, [])
        self.assertEqual(base["speech"]["synth"], "auto")
        self.assertIs(base["dialingo"]["leftTable"], True)

    def test_other_synthesizer_left_alone(self):
        base = {"speech": {"synth": "espeak"}, "dialingo": {"defaultSynth": "ibmeci"}}
        self.assertEqual(leave(base, []), [])
        self.assertEqual(base, {"speech": {"synth": "espeak"}, "dialingo": {"defaultSynth": "ibmeci"}})

    def test_profile_with_its_own_host(self):
        base = {"speech": {"synth": "espeak"}, "dialingo": {"defaultSynth": "ibmeci"}}
        profile = {"speech": {"synth": "languageTable"}, "dialingo": {"defaultSynth": "oneCore"}}
        self.assertEqual(leave(base, [profile]), [profile])
        self.assertEqual(profile["speech"]["synth"], "oneCore")
        self.assertNotIn("leftTable", base["dialingo"])

    def test_profile_takes_the_base_host(self):
        base = {"speech": {"synth": "languageTable"}, "dialingo": {"defaultSynth": "ibmeci"}}
        profile = {"speech": {"synth": "languageTable"}}
        self.assertEqual(leave(base, [profile]), [base, profile])
        self.assertEqual(profile["speech"]["synth"], "ibmeci")
        self.assertNotIn("dialingo", profile)

    def test_profile_without_speech_left_alone(self):
        base = {"speech": {"synth": "ibmeci"}}
        profile = {"keyboard": {"speakTypedCharacters": "False"}}
        self.assertEqual(leave(base, [profile]), [])


class Files(dict):
    """Configuration files on disk, by path, each a dict."""


class FakeConfigObj(dict):
    def __init__(self, path, files, **kwargs):
        super().__init__({k: dict(v) for k, v in files[path].items()})
        self.filename = path
        self.files = files

    def write(self, f):
        f.append({k: dict(v) for k, v in self.items()})


class LeaveNvda(unittest.TestCase):
    def run_leave(self, files, memory, profiles=(), writes_to_disk=True):
        written = {}

        @contextlib.contextmanager
        def tolerant(name):
            out = []
            yield out
            written[name] = out[-1]

        conf = types.SimpleNamespace(profiles=[memory], listProfiles=lambda: iter(profiles))
        modules = {
            "config": types.SimpleNamespace(conf=conf),
            "NVDAState": types.SimpleNamespace(
                shouldWriteToDisk=lambda: writes_to_disk,
                WritePaths=types.SimpleNamespace(getProfileConfigFile=lambda name: f"profiles/{name}.ini"),
            ),
            "configobj": types.SimpleNamespace(ConfigObj=lambda path, **kw: FakeConfigObj(path, files, **kw)),
            "fileUtils": types.SimpleNamespace(FaultTolerantFile=tolerant),
        }
        with mock.patch.dict(sys.modules, modules):
            leave_nvda(mock.Mock())
        return written

    def test_files_and_memory(self):
        files = {
            "nvda.ini": {"speech": {"synth": "languageTable"}, "dialingo": {"defaultSynth": "ibmeci"}},
            "profiles/Word.ini": {"speech": {"synth": "languageTable"}},
            "profiles/Excel.ini": {"speech": {"synth": "espeak"}},
        }
        memory = FakeConfigObj("nvda.ini", files)
        written = self.run_leave(files, memory, profiles=["Word", "Excel"])
        self.assertEqual(sorted(written), ["nvda.ini", "profiles/Word.ini"])
        self.assertEqual(written["nvda.ini"]["speech"]["synth"], "ibmeci")
        self.assertIs(written["nvda.ini"]["dialingo"]["leftTable"], True)
        self.assertEqual(written["profiles/Word.ini"]["speech"]["synth"], "ibmeci")
        self.assertEqual(memory["speech"]["synth"], "ibmeci")
        self.assertIs(memory["dialingo"]["leftTable"], True)

    def test_only_a_profile_leaves_memory_alone(self):
        files = {
            "nvda.ini": {"speech": {"synth": "ibmeci"}},
            "profiles/Word.ini": {"speech": {"synth": "languageTable"}},
        }
        memory = FakeConfigObj("nvda.ini", files)
        written = self.run_leave(files, memory, profiles=["Word"])
        self.assertEqual(sorted(written), ["profiles/Word.ini"])
        self.assertEqual(memory, {"speech": {"synth": "ibmeci"}})

    def test_secure_mode_writes_nothing(self):
        files = {"nvda.ini": {"speech": {"synth": "languageTable"}}}
        memory = FakeConfigObj("nvda.ini", files)
        self.assertEqual(self.run_leave(files, memory, writes_to_disk=False), {})
        self.assertEqual(memory["speech"]["synth"], "languageTable")


if __name__ == "__main__":
    unittest.main()
