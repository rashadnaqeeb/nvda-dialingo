"""What the language table stores as the host's own settings: the snapshot for row settings, live values
for the rest, so a save while a row is applied never persists the row's parameters. The voice dictionary
redirect, and the values the row dialog starts from, against stand-ins for the NVDA modules they import."""
import sys
import types
import unittest

import nvda_stub  # noqa: F401

from mlang import hosts
from mlang.hosts import DRIVER_NAME, own_value, own_values


class Synth:
    def __init__(self, name, host=None, **values):
        self.name = name
        if host is not None:
            self.host = host
        self.__dict__.update(values)


class Stubbed(unittest.TestCase):
    """Installs fake NVDA modules for the duration of a test."""

    def stub(self, name, **attrs):
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        previous = sys.modules.get(name)
        sys.modules[name] = module
        self.addCleanup(lambda: sys.modules.pop(name, None) if previous is None else sys.modules.__setitem__(name, previous))
        return module


class VoiceDictRedirectTest(Stubbed):
    def test_loads_for_the_table_go_to_its_host_and_others_are_untouched(self):
        loaded = []

        def original(synth):
            loaded.append(synth)

        module = self.stub("speechDictHandler", loadVoiceDict=original)
        module.definitions = types.SimpleNamespace(loadVoiceDict=original)
        hosts.redirect_voice_dict()
        hosts.redirect_voice_dict()  # a second install does not wrap the wrapper
        self.assertTrue(module.loadVoiceDict._mlang_redirect)
        self.assertIs(module.loadVoiceDict._mlang_original, original)
        self.assertIs(module.definitions.loadVoiceDict, module.loadVoiceDict)
        # The host still carries a French row's voice; the table's voice is the host's own.
        host = Synth("ibmeci", voice="196608", availableVoices={"65536": "en", "196608": "fr"})
        table = Synth(DRIVER_NAME, host=host, voice="65536")
        module.loadVoiceDict(table)
        module.loadVoiceDict(host)
        hostless = Synth(DRIVER_NAME)
        module.loadVoiceDict(hostless)
        seen = loaded[0]
        self.assertEqual((seen.name, seen.voice, seen.availableVoices), ("ibmeci", "65536", host.availableVoices))
        self.assertEqual(loaded[1:], [host, hostless])


class OwnValueTest(Stubbed):
    def setUp(self):
        self.conf = {"speech": {"espeak": {"rate": 30, "pitch": None}, "ibmeci": {"rate": 90}}}
        self.stub("config", conf=self.conf)
        self.current = None
        self.stub("synthDriverHandler", getSynth=lambda: self.current)

    def test_synthesizer_in_use_answers_from_the_instance(self):
        # Rows on it go through prosody commands, so the instance holds the user's values.
        self.current = Synth("ibmeci", rate=85)
        self.assertEqual(own_value(self.current, "rate"), 85)

    def test_hosted_default_synthesizer_answers_from_the_snapshot(self):
        host = Synth("ibmeci", rate=50, pitch=65)  # carrying a French row at the moment
        self.current = Synth(DRIVER_NAME, host=host, _defaults={"rate": 90, "pitch": 50})
        self.assertEqual(own_value(host, "rate"), 90)
        self.assertEqual(own_value(host, "pitch"), 50)

    def test_other_guest_answers_from_its_configuration_then_the_instance(self):
        guest = Synth("espeak", rate=80, pitch=40, volume=100)  # carrying the Arabic row's rate
        self.current = Synth(DRIVER_NAME, host=Synth("ibmeci"), _defaults={})
        self.assertEqual(own_value(guest, "rate"), 30)
        self.assertEqual(own_value(guest, "pitch"), 40)  # None in the configuration: the instance
        self.assertEqual(own_value(guest, "volume"), 100)  # absent from the configuration: the instance

    def test_unreadable_is_none(self):
        self.current = Synth("ibmeci")
        self.assertIsNone(own_value(self.current, "inflection"))


class Setting:
    def __init__(self, id, useConfig=True):
        self.id = id
        self.useConfig = useConfig


class OwnValuesTest(unittest.TestCase):
    def test_snapshot_wins_over_row_values_on_the_instance(self):
        # The host carries a French row (pitch 65, volume 90) while the user's own values are 50 and 100.
        live = {"voice": "196608", "rate": 50, "pitch": 65, "volume": 90, "rgh": 0, "bth": 0}
        defaults = {"voice": "65536", "rate": 50, "pitch": 50, "volume": 100}
        settings = [Setting(k) for k in ("voice", "rate", "pitch", "volume", "rgh", "bth")]
        got = dict(own_values(settings, defaults, live.__getitem__))
        self.assertEqual(got, {"voice": "65536", "rate": 50, "pitch": 50, "volume": 100, "rgh": 0, "bth": 0})

    def test_unreadable_and_unstored_settings_are_left_out(self):
        settings = [Setting("rate"), Setting("scratch", useConfig=False), Setting("broken")]

        def live(name):
            if name == "broken":
                raise RuntimeError("engine gone")
            return 7

        self.assertEqual(own_values(settings, {}, live), [("rate", 7)])

    def test_nothing_is_invented_for_a_missing_value(self):
        # No default is ever supplied: a value absent everywhere stays absent instead of becoming 50.
        self.assertEqual(own_values([Setting("pitch")], {}, lambda name: (_ for _ in ()).throw(KeyError(name))), [])


class ReadTest(unittest.TestCase):
    def test_onecore_reports_what_was_set_not_what_its_engine_has_yet(self):
        class OneCore:
            name = "oneCore"
            rate = 50  # the engine's value until the next utterance

        guest = OneCore()
        guest._rate = 80
        self.assertEqual(hosts.read(guest, "rate"), 80)

    def test_acapela_reports_the_pitch_kept_for_its_next_utterance(self):
        guest = Synth("AcaTTS", pitch=50, pitchFlag=True, pitchValue=70)
        self.assertEqual(hosts.read(guest, "pitch"), 70)
        guest.pitchFlag = False
        self.assertEqual(hosts.read(guest, "pitch"), 50)

    def test_a_synthesizer_giving_its_voices_no_language_speaks_them_all(self):
        silent = Synth("AcaTTS", availableVoices={"Rachel": Synth("v", language=None)})
        silent.languageIsSupported = lambda lang: False
        declared = Synth("ibmeci", availableVoices={"1": Synth("v", language="en")})
        declared.languageIsSupported = lambda lang: lang == "en"
        self.assertTrue(hosts.supports(silent, "ar"))
        self.assertEqual((hosts.supports(declared, "en"), hosts.supports(declared, "ar")), (True, False))

    def test_other_synthesizers_are_read_as_they_are(self):
        guest = Synth("ibmeci", rate=90, _rate=10)
        self.assertEqual(hosts.read(guest, "rate"), 90)


class ApplyOrderTest(unittest.TestCase):
    def test_every_row_setting_is_applied_rate_boost_before_rate(self):
        from mlang.table import ROW_SETTINGS

        self.assertEqual(sorted(hosts.APPLY_ORDER), sorted(ROW_SETTINGS))
        self.assertLess(hosts.APPLY_ORDER.index("rateBoost"), hosts.APPLY_ORDER.index("rate"))


class TakeOverTest(Stubbed):
    def test_the_settings_dialogs_instance_becomes_the_guest(self):
        # eSpeak keeps its engine in module globals: a second instance would re-initialize it.
        self.stub("synthDriverHandler", getSynth=lambda: None)
        self.stub("globalVars", settingsRing=None)
        self.stub("speechDictHandler", loadVoiceDict=lambda synth: None)
        temp = Synth("espeak", _mlangApplied=("fr",), loads=0)
        temp.loadSettings = lambda: setattr(temp, "loads", temp.loads + 1)
        hosts._temps["espeak"] = temp
        self.addCleanup(hosts._temps.clear)
        self.assertIs(hosts.create("espeak"), temp)
        self.assertEqual((temp.loads, temp._mlangApplied, hosts._temps), (1, None, {}))


class NewDefaultTest(Stubbed):
    def test_windows_voices_are_judged_against_the_new_default_not_the_host_still_loaded(self):
        from mlang import policy, winvoices

        host = Synth("espeak")
        host.languageIsSupported = lambda lang: True  # eSpeak speaks Arabic
        table = Synth(DRIVER_NAME, host=host)
        self.stub("synthDriverHandler", getSynth=lambda: table)
        new = Synth("ibmeci")
        new.languageIsSupported = lambda lang: lang.startswith("en")
        created, disposed = [], []
        for name, value in (("existing", lambda name: None), ("create", lambda name: created.append(name) or new),
                            ("dispose", disposed.append)):
            self.addCleanup(setattr, hosts, name, getattr(hosts, name))
            setattr(hosts, name, value)
        self.addCleanup(setattr, winvoices, "languages", winvoices.languages)
        winvoices.languages = lambda: ["ar_SA", "en_US"]
        conf = {"speech": {"synth": DRIVER_NAME}, "multilanguage": {"defaultSynth": "ibmeci", "useWindowsVoices": True}}
        self.assertEqual(policy.windows_languages_beyond_engine(conf), ["ar_SA"])
        self.assertEqual((created, disposed), (["ibmeci"], [new]))


class FailedDefaultTest(Stubbed):
    def setUp(self):
        from mlang import winvoices

        self.host = Synth("espeak")
        self.host.languageIsSupported = lambda lang: lang.startswith("ar")
        self.table = Synth(DRIVER_NAME, host=self.host, _failed=set())
        self.stub("synthDriverHandler", getSynth=lambda: self.table)
        self.created = []
        for name, value in (("existing", lambda name: None), ("create", lambda name: self.created.append(name))):
            self.addCleanup(setattr, hosts, name, getattr(hosts, name))
            setattr(hosts, name, value)
        self.addCleanup(setattr, winvoices, "languages", winvoices.languages)
        winvoices.languages = lambda: ["ar_SA", "en_US", "fr_FR"]
        self.conf = {"speech": {"synth": DRIVER_NAME}, "multilanguage": {"defaultSynth": "sapi4_32", "useWindowsVoices": True}}

    def test_a_stand_in_for_a_default_that_failed_answers_without_loading_it_again(self):
        from mlang import policy

        self.table._failed.add("sapi4_32")
        self.assertEqual(policy.windows_languages_beyond_engine(self.conf), ["en_US", "fr_FR"])
        self.assertEqual(self.created, [])

    def test_a_default_that_cannot_load_is_tried_once(self):
        from mlang import policy

        self.assertEqual(policy.windows_languages_beyond_engine(self.conf), ["ar_SA", "en_US", "fr_FR"])
        self.assertEqual(self.created, ["sapi4_32"])


class HalfBuiltTest(Stubbed):
    def test_a_guest_that_fails_after_creation_is_terminated_and_the_current_synthesizer_restored(self):
        events = []

        class Driver:
            name = "broken"

            @classmethod
            def check(cls):
                return True

            def initSettings(self):
                raise RuntimeError("stored voice gone")

            def cancel(self):
                events.append("cancel")

            def loadSettings(self):
                events.append("loadSettings")

            def terminate(self):
                events.append("terminate")

        current = Synth("ibmeci")
        self.stub("synthDriverHandler", getSynth=lambda: current, _getSynthDriver=lambda name: Driver)
        self.stub("globalVars", settingsRing=None)
        self.stub("speechDictHandler", loadVoiceDict=lambda synth: events.append(("dictionary", synth)))
        self.assertIsNone(hosts.create("broken"))
        self.assertEqual(events, ["cancel", "loadSettings", "terminate", ("dictionary", current)])


class RingKeptTest(Stubbed):
    def test_a_guest_loaded_in_speech_leaves_the_ring_where_it_was(self):
        class Ring:
            def __init__(self):
                self.settings = ["rate", "voice", "lock"]
                self._current = 1  # stepping through a locked row's voices
                self.rebuilt = []

            def updateSupportedSettings(self, synth):
                # A bare guest's entries have no voice of the row's: the ring would land on the rate.
                self.rebuilt.append(synth)
                self.settings = ["rate", "pitch", "lock"]
                self._current = 0

        ring = Ring()

        class Driver:
            name = "sapi5"

            @classmethod
            def check(cls):
                return True

            def initSettings(self):
                ring.updateSupportedSettings(self)  # NVDA's changeVoice

            def _unregisterConfigSaveAction(self):
                pass

        table = Synth(DRIVER_NAME)
        self.stub("synthDriverHandler", getSynth=lambda: table, _getSynthDriver=lambda name: Driver)
        self.stub("globalVars", settingsRing=ring)
        self.stub("speechDictHandler", loadVoiceDict=lambda synth: None)
        self.assertIsInstance(hosts.create("sapi5"), Driver)
        self.assertEqual((ring.settings, ring._current), (["rate", "voice", "lock"], 1))
        # Disposed of when a step leaves its voice behind: reloading its settings rebuilds the ring too.
        guest = Driver()
        guest.cancel = guest.terminate = lambda: None
        guest.loadSettings = guest.initSettings
        hosts.dispose(guest)
        self.assertEqual((ring.settings, ring._current), (["rate", "voice", "lock"], 1))


class AcapelaCancelTest(unittest.TestCase):
    def test_cancel_drops_the_calls_queued_behind_the_one_speaking(self):
        import queue

        cancelled = []
        guest = Synth("AcaTTS", speakQueue=queue.Queue())
        guest.cancel = lambda: cancelled.append(guest.speakQueue.qsize())
        guest.speakQueue.put(("speak", ("one",), {}))
        guest.speakQueue.put(("speak", ("two",), {}))
        hosts._cancel_queued(guest)
        guest.cancel()
        self.assertEqual((cancelled, guest.speakQueue.unfinished_tasks), ([0], 0))


class RefusedTest(unittest.TestCase):
    def test_worldvoice_is_never_loaded(self):
        self.assertIsNone(hosts.create("WorldVoice"))


class PanelUpdateTest(Stubbed):
    def test_only_the_synthesizer_in_use_updates_nvdas_speech_panel(self):
        updated = []

        def original(synth):
            updated.append(synth)

        module = types.ModuleType("synthDrivers.fakeSonata")
        module.update_displaied_params_on_voice_change = original
        cls = type("SynthDriver", (), {"__module__": module.__name__})
        module.SynthDriver = cls
        sys.modules[module.__name__] = module
        self.addCleanup(sys.modules.pop, module.__name__, None)
        live, guest = cls(), cls()
        self.stub("synthDriverHandler", getSynth=lambda: live)
        hosts._quiet_panel_updates(guest)
        hosts._quiet_panel_updates(guest)  # a second guest does not wrap the wrapper
        module.update_displaied_params_on_voice_change(guest)
        module.update_displaied_params_on_voice_change(live)
        self.assertEqual(updated, [live])
        self.assertIs(module.update_displaied_params_on_voice_change._mlang_original, original)


class FailureTest(Stubbed):
    def guest(self, player):
        done = []
        self.stub("synthDriverHandler", synthDoneSpeaking=types.SimpleNamespace(notify=lambda synth: done.append(synth)))

        class OneCore:
            name = "oneCore"

            def __init__(self):
                self._isProcessing = True
                self._player = player
                self._queuedSpeech = []
                self.handled = 0

            def _handleSpeechFailure(self):
                self.handled += 1  # OneCore's own: with no player and nothing queued it returns as it is

        guest = OneCore()
        hosts._complete_failures(guest)
        return guest, done

    def test_a_first_utterance_that_fails_frees_the_guest_and_reports_done(self):
        guest, done = self.guest(player=None)
        guest._handleSpeechFailure()
        self.assertEqual((guest.handled, guest._isProcessing, done), (1, False, [guest]))

    def test_a_failure_onecore_completes_itself_is_left_to_it(self):
        guest, done = self.guest(player=object())
        guest._handleSpeechFailure()
        self.assertEqual((guest.handled, guest._isProcessing, done), (1, True, []))


class ProsodyModeTest(unittest.TestCase):
    def driver(self, module_name, source):
        module = types.ModuleType(module_name)
        exec(source, module.__dict__)
        sys.modules[module_name] = module
        self.addCleanup(sys.modules.pop, module_name, None)
        hosts._modes.clear()
        return module.SynthDriver()

    def test_new_value_readers_are_absolute(self):
        source = """
class SynthDriver:
    def speak(self, seq):
        return [i.newValue for i in seq]
"""
        self.assertEqual(hosts.prosody_mode(self.driver("synthDrivers.fakeEci", source)), "absolute")

    def test_multiplier_readers_are_relative_even_in_a_helper_class(self):
        source = """
class _Converter:
    def convert(self, item):
        return item.multiplier

class SynthDriver:
    def speak(self, seq):
        return _Converter()
"""
        self.assertEqual(hosts.prosody_mode(self.driver("synthDrivers.fakeOc", source)), "relative")

    def test_drivers_on_nvdas_ssml_converter_are_relative(self):
        # RHVoice: the prosody is written by speechXml's converter, whose code the scan does not see.
        speech_xml = types.ModuleType("speechXml")
        exec("class SsmlConverter:\n    pass\n", speech_xml.__dict__)
        sys.modules["speechXml"] = speech_xml
        self.addCleanup(sys.modules.pop, "speechXml", None)
        source = """
import speechXml

class SsmlConverter(speechXml.SsmlConverter):
    pass

class SynthDriver:
    def speak(self, seq):
        return SsmlConverter()
"""
        self.assertEqual(hosts.prosody_mode(self.driver("synthDrivers.fakeRh", source)), "relative")

    def test_offset_readers_add_it_to_their_own_value(self):
        source = """
class SynthDriver:
    def speak(self, seq):
        return [self.pitch + i.offset for i in seq]
"""
        self.assertEqual(hosts.prosody_mode(self.driver("synthDrivers.fakeVe", source)), "offset")

    def test_readers_of_the_raw_values_apply_them_to_their_own_value(self):
        # Eloquence64RS: base * _multiplier + _offset, read with getattr, so no attribute name shows.
        source = """
class SynthDriver:
    def speak(self, seq):
        return [self.pitch * getattr(i, "_multiplier", 1) + getattr(i, "_offset", 0) for i in seq]
"""
        self.assertEqual(hosts.prosody_mode(self.driver("synthDrivers.fakeElo", source)), "offset")

    def test_drivers_in_another_process_are_native(self):
        module = types.ModuleType("_bridge.fakeProxy")
        exec("class SynthDriverProxy:\n    pass\n", module.__dict__)
        cls = type("SynthDriver", (module.SynthDriverProxy,), {"__module__": "synthDrivers.fake32"})
        hosts._modes.clear()
        self.assertEqual(hosts.prosody_mode(cls()), "native")


if __name__ == "__main__":
    unittest.main()
