# The Dialingo settings panel and the language row dialog.

import wx

import addonHandler
import config
import gui
import languageHandler
import synthDriverHandler
import ui
from gui import guiHelper, nvdaControls
from gui.settingsDialogs import SettingsPanel
from gui.speechDict import DictionaryDialog, VoiceDictionaryDialog
from logHandler import log

from mlang import hosts, langpack, policy, voicedict
from mlang import scripts as S
from mlang import table as T
from mlang.detector import MODES
from mlang.hosts import DRIVER_NAME

addonHandler.initTranslation()


engine = None  # the plugin's Engine, for its dictionary; set by the plugin

installing = set()  # base languages whose Windows dictionary is being installed


def dictionary_missing(language):
    """Whether Windows lacks the language's spelling dictionary; None when that cannot be told."""
    try:
        dictionary = engine._dictionary() if engine is not None else None
        return dictionary.has(language) is False if dictionary is not None else None
    except Exception:
        log.debugWarning("dialingo: dictionary check failed", exc_info=True)
        return None


def dictionary_label(language):
    """What the Dictionary column says for a language."""
    if S.base(language) in installing:
        # Translators: Shown in the languages list while the Windows dictionary is being installed.
        return _("installing")
    missing = dictionary_missing(language)
    if missing is None:
        # Translators: Shown in the languages list when whether the language's Windows dictionary is
        # installed could not be checked.
        return _("unknown")
    if missing:
        # Translators: Shown in the languages list when the language's Windows dictionary is missing.
        return _("missing")
    # Translators: Shown in the languages list when the language's Windows dictionary is installed.
    return _("installed")


def offer_install(parent, language):
    """Offers to install a language's missing Windows dictionary; returns whether the install started."""
    if dictionary_missing(language) is not True or S.base(language) in installing:
        return False
    # Translators: Asks to install the Windows dictionary; %s is a language name.
    text = _("You will be asked to grant administrator permission to install the Windows dictionary for %s. It is required for accurate language detection.") % language_label(language)
    # Translators: Title of the dialogs about the Windows dictionary install.
    if gui.messageBox(text, _("Windows dictionary"), wx.OK | wx.CANCEL | wx.ICON_INFORMATION, parent) != wx.OK:
        return False
    return start_install(parent, language)


def start_install(parent, language):
    name = langpack.capability(language)
    key = S.base(language)

    def done(code):
        wx.CallAfter(finish_install, language, code)

    try:
        started = langpack.install([name], done)
    except Exception:
        log.error("dialingo: could not start the dictionary install", exc_info=True)
        started = False
    if not started:
        # Translators: Message when the elevated install did not start.
        gui.messageBox(_("Not started: administrator permission was not given."), _("Windows dictionary"), wx.OK | wx.ICON_ERROR, parent)
        return False
    installing.add(key)
    log.info(f"dialingo: installing {name}")
    # Translators: Announced when the dictionary install starts; %s is a language name.
    ui.message(_("Installing the %s dictionary. NVDA will report when done.") % language_label(language))
    return True


def finish_install(language, code):
    installing.discard(S.base(language))
    try:
        if engine is not None and engine.dictionary:
            engine.dictionary.refresh()
    except Exception:
        log.debugWarning("dialingo: dictionary refresh after install failed", exc_info=True)
    name = language_label(language)
    if code == 0 and not dictionary_missing(language):
        # Translators: Message when the Windows dictionary finished installing; %s is a language name.
        text = _("%s dictionary installed.") % name
    elif code == 0:
        # Translators: Message when the install ended but the dictionary is still not found; %s is a language name.
        text = _("Install finished, but Windows does not show the %s dictionary yet. Restart Windows.") % name
    else:
        # Translators: Message when the install failed; %s is a language name.
        text = _("%s dictionary did not install. Check Windows Update, or see the NVDA log.") % name
    log.info(f"dialingo: dictionary install for {language} ended with code {code}")
    gui.messageBox(text, _("Windows dictionary"), wx.OK | (wx.ICON_INFORMATION if code == 0 else wx.ICON_ERROR))

def language_label(code):
    if not code:
        return ""
    description = languageHandler.getLanguageDescription(code)
    if description is None:
        try:
            description = languageHandler.getLanguageDescription(languageHandler.normalizeLanguage(code) or code)
        except Exception:
            description = None
    return f"{description} ({code})" if description and description != code else code


_synth_labels = {}


def symbol_label(level):
    """NVDA's name for a row's symbol level; empty when the row follows NVDA's setting."""
    if level is None:
        return ""
    import characterProcessing

    try:
        return characterProcessing.SPEECH_SYMBOL_LEVEL_LABELS[characterProcessing.SymbolLevel(level)]
    except Exception:
        return str(level)


def synth_label(name):
    if not _synth_labels:
        _synth_labels.update(synthDriverHandler.getSynthList())
    return _synth_labels.get(name, name)


class DialingoPanel(SettingsPanel):
    # The add-on's name, which is not translated.
    title = "Dialingo"

    def makeSettings(self, settingsSizer):
        section = config.conf[T.CONFIG_SECTION]
        self.table = T.load(config.conf)
        helper = guiHelper.BoxSizerHelper(self, sizer=settingsSizer)

        from . import MODE_LABELS

        self.mode_codes = list(MODES)
        # Translators: Label of the detection mode combo box.
        self.modeChoice = helper.addLabeledControl(_("Language &detection:"), wx.Choice, choices=[MODE_LABELS[m] for m in self.mode_codes])
        mode = section["mode"] if section["mode"] in self.mode_codes else "full"
        self.modeChoice.SetSelection(self.mode_codes.index(mode))

        self.strictCheck = helper.addItem(
            # Translators: Label of a check box.
            wx.CheckBox(self, label=_("&Strict: also require Windows language detection to agree"))
        )
        self.strictCheck.SetValue(bool(section["strict"]))

        self.defaultTaggedCheck = helper.addItem(
            # Translators: Label of a check box.
            wx.CheckBox(self, label=_("Detect inside text &tagged with the default language"))
        )
        self.defaultTaggedCheck.SetValue(bool(section["detectInDefaultTagged"]))

        self.windowsVoicesCheck = helper.addItem(
            # Translators: Label of a check box.
            wx.CheckBox(self, label=_("Use &Windows voices for languages the synthesizer cannot speak"))
        )
        self.windowsVoicesCheck.SetValue(bool(section["useWindowsVoices"]))

        current = synthDriverHandler.getSynth()
        self.current_name = current.name if current is not None else None
        self.synths = [(name, desc) for name, desc in synthDriverHandler.getSynthList() if name not in (DRIVER_NAME, "silence", *hosts.REFUSED)]
        configured_default = section["defaultSynth"] or (self.current_name if self.current_name != DRIVER_NAME else "")
        self.default_index = next((i for i, (n, _d) in enumerate(self.synths) if n == configured_default), 0)
        self.defaultChoice = helper.addLabeledControl(
            # Translators: Label of the combo box that picks the synthesizer for the default language.
            _("Default s&ynthesizer:"),
            wx.Choice,
            choices=[d for _n, d in self.synths],
        )
        if self.synths:
            self.defaultChoice.SetSelection(self.default_index)

        self.list = helper.addLabeledControl(
            # Translators: Label of the languages list. Each row has a check box: a language is detected only
            # when checked. The default language has no row.
            _("&Languages (detected when checked; the default needs no row):"),
            nvdaControls.AutoWidthColumnCheckListCtrl,
            style=wx.LC_REPORT | wx.LC_SINGLE_SEL,
        )
        # Translators: Column headers of the languages list.
        for header, width in ((_("Language"), 180), (_("Synthesizer"), 140), (_("Voice"), 160), (_("Rate"), 50), (_("Pitch"), 50), (_("Volume"), 60), (_("Symbols"), 80), (_("Dictionary"), 100)):
            self.list.AppendColumn(header, width=width)
        self.list.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.onEdit)
        self.list.Bind(wx.EVT_CHECKLISTBOX, self.onCheck)
        self.list.Bind(wx.EVT_CHAR_HOOK, self.onCharHook)

        buttons = guiHelper.ButtonHelper(orientation=wx.HORIZONTAL)
        # Translators: Buttons of the languages list.
        buttons.addButton(self, label=_("&Add...")).Bind(wx.EVT_BUTTON, self.onAdd)
        buttons.addButton(self, label=_("&Edit...")).Bind(wx.EVT_BUTTON, self.onEdit)
        buttons.addButton(self, label=_("&Remove")).Bind(wx.EVT_BUTTON, self.onRemove)
        # Translators: Button that checks whether the selected language's Windows language pack (its dictionary) is installed and offers to install it.
        buttons.addButton(self, label=_("&Verify language pack...")).Bind(wx.EVT_BUTTON, self.onInstall)
        # Translators: Button that edits the voice dictionary of the selected row's voice.
        buttons.addButton(self, label=_("V&oice dictionary...")).Bind(wx.EVT_BUTTON, self.onDictionary)
        helper.addItem(buttons)

        if self.current_name == DRIVER_NAME:
            # Translators: A note in the settings panel.
            note = _("Each row speaks with its own synthesizer and voice.")
        else:
            # Translators: A note in the settings panel; %s is the current synthesizer.
            note = _("%s picks its own voice per language; its rows set rate, pitch, and volume. Rows for other synthesizers, and Windows voices, are hosted automatically.") % synth_label(self.current_name)
        helper.addItem(wx.StaticText(self, label=note))
        self.refresh()

    # ------------------------------------------------------------ list

    def refresh(self, select=None):
        self.list.DeleteAllItems()
        for index, row in enumerate(self.table.rows):
            self.list.Append((
                language_label(row.lang),
                synth_label(row.synth),
                self.voice_label(row),
                str(row.get("rate", "")),
                str(row.get("pitch", "")),
                str(row.get("volume", "")),
                symbol_label(row.symbolLevel),
                dictionary_label(row.lang),
            ))
            self.list.CheckItem(index, row.detect)
        if self.table.rows:
            index = 0
            if select:
                index = next((i for i, r in enumerate(self.table.rows) if r.lang == select), 0)
            self.list.Select(index)
            self.list.Focus(index)

    def voice_label(self, row):
        voice = row.get("voice")
        if not voice:
            return ""
        try:
            guest = hosts.instance(row.synth)
            if guest is not None:
                info = guest.availableVoices.get(voice)
                if info is not None:
                    return info.displayName
        except Exception:
            pass
        return voice

    def selected(self):
        index = self.list.GetFirstSelected()
        return self.table.rows[index] if 0 <= index < len(self.table.rows) else None

    def onCheck(self, evt):
        index = evt.GetInt()
        if 0 <= index < len(self.table.rows):
            self.table.rows[index].detect = self.list.IsChecked(index)

    def onCharHook(self, evt):
        if evt.GetKeyCode() == wx.WXK_DELETE:
            self.onRemove(evt)
        else:
            evt.Skip()

    def onAdd(self, evt):
        self.edit(None)

    def onEdit(self, evt):
        row = self.selected()
        if row is not None:
            self.edit(row)

    def edit(self, row):
        dialog = RowDialog(self, row, self.table)
        try:
            if dialog.ShowModal() == wx.ID_OK:
                new = dialog.result
                if row is not None and row.lang.lower() != new.lang.lower():
                    self.table.remove(row.lang)
                self.table.upsert(new)
                self.refresh(select=new.lang)
                offer_install(self, new.lang)
                self.refresh(select=new.lang)
        finally:
            # Escape, Cancel, and the close button end the dialog inside wx, past any Python override.
            dialog.restore_live()
            dialog.Destroy()

    def onInstall(self, evt):
        row = self.selected()
        if row is None:
            return
        missing = dictionary_missing(row.lang)
        if missing is None:
            # Translators: Message when whether the selected language's Windows dictionary is installed could
            # not be checked; %s is its name.
            gui.messageBox(_("Could not check the %s dictionary. See the NVDA log.") % language_label(row.lang), _("Windows dictionary"), wx.OK | wx.ICON_ERROR, self)
            return
        if not missing:
            # Translators: Message when the selected language's Windows dictionary is already installed; %s is its name.
            gui.messageBox(_("The %s dictionary is installed.") % language_label(row.lang), _("Windows dictionary"), wx.OK | wx.ICON_INFORMATION, self)
            return
        offer_install(self, row.lang)
        self.refresh(select=row.lang)

    def onRemove(self, evt):
        row = self.selected()
        if row is None:
            return
        self.table.remove(row.lang)
        self.refresh()

    def onDictionary(self, evt):
        """NVDA's dictionary dialog on the voice dictionary of the selected row's voice: the file NVDA
        would use for that voice if it were the current one, so the entries are shared with plain use of
        that voice. The current voice's dictionary is NVDA's own, opened through NVDA's dialog for it."""
        row = self.selected()
        if row is None:
            return
        voice = row.get("voice")
        info = None
        if voice:
            try:
                guest = hosts.instance(row.synth)
                info = guest.availableVoices.get(voice) if guest is not None else None
            except Exception:
                log.debugWarning("dialingo: the row's voice could not be named", exc_info=True)
        if info is None:
            gui.messageBox(
                # Translators: Message when the selected row has no voice whose dictionary could be edited.
                _("This row has no voice of its own, so the synthesizer's voice dictionary applies to it."),
                # Translators: Title of the messages about a row voice's dictionary.
                _("Voice dictionary"),
                wx.OK | wx.ICON_INFORMATION,
                self,
            )
            return
        path = voicedict.path_for(row.synth, info.displayName)
        if voicedict.is_current(path):
            gui.mainFrame.popupSettingsDialog(VoiceDictionaryDialog)
            return
        from speechDictHandler.types import SpeechDict

        dictionary = SpeechDict()
        dictionary.load(path)
        # Translators: Title of the dictionary dialog for a row's voice; %s is the voice and its synthesizer.
        title = _("Voice dictionary for %s") % f"{info.displayName} ({synth_label(row.synth)})"
        gui.mainFrame.popupSettingsDialog(RowDictionaryDialog, title, dictionary)

    # ------------------------------------------------------------ save

    def onSave(self):
        section = config.conf[T.CONFIG_SECTION]
        mode = self.mode_codes[self.modeChoice.GetSelection()]
        section["mode"] = mode
        section["strict"] = self.strictCheck.IsChecked()
        section["detectInDefaultTagged"] = self.defaultTaggedCheck.IsChecked()
        changed = self.table != T.load(config.conf)
        if section["useWindowsVoices"] != self.windowsVoicesCheck.IsChecked():
            section["useWindowsVoices"] = self.windowsVoicesCheck.IsChecked()
            changed = True
        i = self.defaultChoice.GetSelection()
        # By name: a configured default missing from the list shows as the first choice without being it.
        if self.synths and 0 <= i < len(self.synths) and self.synths[i][0] != section["defaultSynth"]:
            section["defaultSynth"] = self.synths[i][0]
            self.default_index = i
            changed = True
        if changed:
            T.save(config.conf, self.table)
        hosts.release()
        if changed:
            # After the save, when it is known whether OK is closing the dialog. The panels are gathered now,
            # while the dialog surely exists; by then it may be gone.
            dialog = self.GetTopLevelParent()
            wx.CallAfter(follow_table_after_save, dialog, _refreshing_panels(dialog))

    def onDiscard(self):
        hosts.release()


class RowDictionaryDialog(DictionaryDialog):
    """NVDA's dictionary dialog on a row voice's dictionary; OK saves to the file the dictionary was loaded
    from, and the filter rereads it."""

    def __init__(self, parent, title, speechDict):
        super().__init__(parent, title, speechDict)


def follow_table():
    """The synthesizer follows the table and the installed voices: a row on another synthesizer than the
    one in use or with another voice (policy.needs_table), or a Windows voice for a language it cannot
    speak, needs the language table synthesizer,
    which hosts the one in use unchanged, so it is selected; when nothing needs it any more, the default
    synthesizer is selected again. The user never visits NVDA's synthesizer dialog for this. Only after the
    panel saves a change: a synthesizer picked in NVDA's own dialog stays in use, across restarts too.
    Returns False when a switch was needed and failed."""
    current = synthDriverHandler.getSynth()
    if current is None:
        return True
    section = config.conf[T.CONFIG_SECTION]
    needed = policy.needs_table(config.conf)
    if current.name != DRIVER_NAME and needed:
        return switch_to(DRIVER_NAME)
    if current.name == DRIVER_NAME and not needed and section["defaultSynth"]:
        return switch_to(section["defaultSynth"])
    return True


def follow_table_after_save(dialog, panels=()):
    """follow_table for the settings dialog once its save is done. NVDA's voice panel holds a weak reference
    to the synthesizer in use whose callback refreshes the panel when that synthesizer is freed, as it is
    on a switch; OK has scheduled the dialog's destruction by now, and the refresh would run on a deleted
    panel. So when the dialog is closing, its panels' callbacks are dropped first. Apply keeps the dialog,
    and the refresh then shows the new synthesizer as NVDA intends."""
    closing = True
    try:
        closing = not dialog or dialog.IsBeingDeleted() or wx.GetApp().IsScheduledForDestruction(dialog)
    except Exception:
        log.debugWarning("dialingo: could not tell whether the settings dialog is closing", exc_info=True)
    if closing:
        _drop_refresh_callbacks(panels)
    if not follow_table():
        gui.messageBox(
            # Translators: Message when a synthesizer fails to load.
            _("Synthesizer could not be loaded. See the NVDA log."),
            _("Error"),
            wx.OK | wx.ICON_ERROR,
            gui.mainFrame if closing else dialog,
        )


def _refreshing_panels(window):
    """The windows under `window` that hold a refresh-on-free reference to the synthesizer in use."""
    found = []
    stack = [window]
    while stack:
        w = stack.pop()
        if getattr(w, "_currentSettingsRef", None) is not None:
            found.append(w)
        try:
            stack.extend(w.GetChildren())
        except Exception:
            pass
    return found


def _drop_refresh_callbacks(panels):
    import weakref

    for w in panels:
        ref = getattr(w, "_currentSettingsRef", None)
        if ref is not None:
            target = ref()
            w._currentSettingsRef = weakref.ref(target) if target is not None else ref


def switch_to(name):
    if not synthDriverHandler.setSynth(name):
        return False
    import tones

    tones.terminate()
    tones.initialize()
    log.info(f"dialingo: synthesizer set to {name} to follow the language table")
    return True


class RowDialog(wx.Dialog):
    """Synthesizer, voice, language, and parameters for one row."""

    SETTINGS = ("rate", "pitch", "volume", "inflection")

    def __init__(self, parent, row, table):
        # Translators: Title of the dialog that edits a language of the table.
        super().__init__(parent, title=_("Edit language") if row else _("Add language"))
        self.row = row
        self.table = table
        self.result = None
        self.problem = None
        self.guest = None
        self.saved = None  # (synthesizer in use, its values before the first preview through it)
        self.voices = []
        self.variants = []
        self.languages = []
        self.language_typed = False
        self.synths = [(name, desc) for name, desc in synthDriverHandler.getSynthList() if name not in (DRIVER_NAME, "silence", *hosts.REFUSED)]

        main = wx.BoxSizer(wx.VERTICAL)
        helper = guiHelper.BoxSizerHelper(self, orientation=wx.VERTICAL)

        # Translators: Label of the synthesizer combo box in the language dialog.
        self.synthChoice = helper.addLabeledControl(_("&Synthesizer:"), wx.Choice, choices=[d for _n, d in self.synths])
        self.synthChoice.Bind(wx.EVT_CHOICE, self.onSynth)
        # Translators: Label of the voice combo box in the language dialog.
        self.voiceChoice = helper.addLabeledControl(_("&Voice:"), wx.Choice, choices=[])
        self.voiceChoice.Bind(wx.EVT_CHOICE, self.onVoice)
        # Translators: Label of the variant combo box in the language dialog.
        self.variantChoice = helper.addLabeledControl(_("V&ariant:"), wx.Choice, choices=[])
        # Translators: Label of the language combo box in the language dialog.
        self.langCombo = helper.addLabeledControl(_("&Language:"), wx.ComboBox, choices=[], style=wx.CB_DROPDOWN)
        self.langCombo.Bind(wx.EVT_TEXT, self.onLanguageTyped)
        self.sliders = {}
        # Translators: Labels of the parameter sliders in the language dialog.
        for setting, label in (("rate", _("&Rate")), ("pitch", _("&Pitch")), ("volume", _("V&olume")), ("inflection", _("&Inflection"))):
            slider = helper.addLabeledControl(label, nvdaControls.EnhancedInputSlider, minValue=0, maxValue=100)
            self.sliders[setting] = slider
        # Translators: Label of a check box in the language dialog.
        self.rateBoostCheck = helper.addItem(wx.CheckBox(self, label=_("Rate &boost")))
        # NVDA's own levels and their translated names; the first choice leaves NVDA's setting in charge.
        import characterProcessing

        self.symbol_levels = [None] + [int(level) for level in characterProcessing.CONFIGURABLE_SPEECH_SYMBOL_LEVELS]
        self.symbolChoice = helper.addLabeledControl(
            # Translators: Label of the combo box that picks how much punctuation and how many symbols are
            # spoken in this language.
            _("Pu&nctuation/symbol level:"),
            wx.Choice,
            # Translators: The choice that speaks this language's punctuation at NVDA's own level.
            choices=[_("Same as NVDA")] + [characterProcessing.SPEECH_SYMBOL_LEVEL_LABELS[level] for level in self.symbol_levels[1:]],
        )
        level = row.symbolLevel if row is not None else None
        self.symbolChoice.SetSelection(self.symbol_levels.index(level) if level in self.symbol_levels else 0)
        # Translators: Label of the button that speaks a sample with the chosen voice.
        self.testButton = helper.addItem(wx.Button(self, label=_("&Test")))
        self.testButton.Bind(wx.EVT_BUTTON, self.onTest)
        helper.addDialogDismissButtons(wx.OK | wx.CANCEL, separated=True)
        self.Bind(wx.EVT_BUTTON, self.onOk, id=wx.ID_OK)
        main.Add(helper.sizer, border=guiHelper.BORDER_FOR_DIALOGS, flag=wx.ALL)
        self.SetSizerAndFit(main)

        current = synthDriverHandler.getSynth()
        wanted = row.synth if row is not None else (current.name if current is not None else None)
        if wanted == DRIVER_NAME:
            wanted = config.conf[T.CONFIG_SECTION]["defaultSynth"]
        index = next((i for i, (n, _d) in enumerate(self.synths) if n == wanted), 0)
        if self.synths:
            self.synthChoice.SetSelection(index)
            self.onSynth(None)
        self.CentreOnScreen()
        self.synthChoice.SetFocus()

    # ------------------------------------------------------------ population

    def synth_name(self):
        i = self.synthChoice.GetSelection()
        return self.synths[i][0] if 0 <= i < len(self.synths) else None

    def onSynth(self, evt):
        name = self.synth_name()
        # A preview through the current synthesizer changed its voice; put the user's settings back before
        # the dialog lets go of it.
        self.restore_live()
        self.guest = hosts.instance(name) if name else None
        if self.guest is None:
            # Translators: Message when a synthesizer cannot be loaded.
            gui.messageBox(_("Synthesizer could not be loaded. See the NVDA log."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.voices = []
            self.voiceChoice.Clear()
            self.variants = []
            self.variantChoice.Clear()
            self.languages = []
            # Nothing from another synthesizer carries over, and OK refuses until one loads.
            for control in (self.voiceChoice, self.variantChoice, self.rateBoostCheck, self.testButton, *self.sliders.values()):
                control.Enable(False)
            self.langCombo.Clear()
            if self.row is not None:
                self.set_language(self.row.lang)
            return
        guest = self.guest
        row = self.row if self.row is not None and self.row.synth == name else None
        try:
            self.voices = list(guest.availableVoices.values()) if guest.isSupported("voice") else []
        except Exception:
            log.debugWarning("dialingo: voices unavailable", exc_info=True)
            self.voices = []
        self.voiceChoice.Clear()
        for info in self.voices:
            label = info.displayName
            if info.language:
                label = f"{label} ({language_label(info.language)})"
            self.voiceChoice.Append(label)
        self.voiceChoice.Enable(bool(self.voices))
        # A new row starts from the synthesizer's own values, the user's, so what the dialog shows is what
        # the row would leave unchanged.
        wanted = row.get("voice") if row else None
        if wanted is None:
            wanted = hosts.own_value(guest, "voice")
        voice_index = next((i for i, v in enumerate(self.voices) if v.id == wanted), 0)
        if self.voices:
            self.voiceChoice.SetSelection(voice_index)

        try:
            self.variants = list(guest.availableVariants.values()) if guest.isSupported("variant") else []
        except Exception:
            self.variants = []
        self.variantChoice.Clear()
        for info in self.variants:
            self.variantChoice.Append(info.displayName)
        self.variantChoice.Enable(bool(self.variants))
        variant = row.get("variant") if row else None
        if variant is None and self.variants:
            variant = hosts.own_value(guest, "variant")
        if self.variants:
            self.variantChoice.SetSelection(next((i for i, v in enumerate(self.variants) if v.id == variant), 0))

        for setting, slider in self.sliders.items():
            supported = guest.isSupported(setting)
            slider.Enable(supported)
            value = row.get(setting) if row else None
            if value is None and supported:
                value = hosts.own_value(guest, setting)
            try:
                slider.SetValue(int(value) if value is not None else 50)
            except (TypeError, ValueError):
                slider.SetValue(50)
        boost = guest.isSupported("rateBoost")
        self.rateBoostCheck.Enable(boost)
        rate_boost = row.get("rateBoost") if row else None
        if rate_boost is None and boost:
            rate_boost = hosts.own_value(guest, "rateBoost")
        self.rateBoostCheck.SetValue(bool(rate_boost))
        self.testButton.Enable(True)

        languages = []
        for info in self.voices:
            if info.language and info.language not in languages:
                languages.append(info.language)
        self.languages = languages
        self.langCombo.Clear()
        for code in languages:
            self.langCombo.Append(language_label(code))
        self.language_typed = False
        if self.row is not None:
            self.set_language(self.row.lang)
            self.language_typed = True
        else:
            self.onVoice(None)

    def onVoice(self, evt):
        if self.language_typed and evt is not None:
            return
        i = self.voiceChoice.GetSelection()
        if 0 <= i < len(self.voices) and self.voices[i].language:
            self.set_language(self.voices[i].language)
            self.language_typed = False

    def set_language(self, code):
        self.langCombo.ChangeValue(language_label(code))

    def onLanguageTyped(self, evt):
        self.language_typed = True

    # ------------------------------------------------------------ result

    def language_code(self):
        text = self.langCombo.GetValue().strip()
        for code in self.languages:
            if language_label(code) == text:
                return code
        if "(" in text and text.endswith(")"):
            return text[text.rindex("(") + 1:-1].strip()
        return text

    def build_row(self):
        """The row the dialog describes, or None with `self.problem` saying what is missing or wrong."""
        self.problem = None
        name = self.synth_name()
        lang = self.language_code()
        if not name or not lang:
            # Translators: Message when the language field is empty.
            self.problem = _("Enter a language.")
            return None
        lang = S.normalize(lang)
        if not S.is_language(lang):
            # Translators: Message when the language field holds something other than a language code; %s is the text.
            self.problem = _("%s is not a language code. Pick a voice or enter a code such as fr or fr_FR.") % lang
            return None
        settings = {}
        i = self.voiceChoice.GetSelection()
        if 0 <= i < len(self.voices):
            settings["voice"] = self.voices[i].id
        i = self.variantChoice.GetSelection()
        if self.variants and 0 <= i < len(self.variants):
            settings["variant"] = self.variants[i].id
        for setting, slider in self.sliders.items():
            if slider.IsEnabled():
                settings[setting] = slider.GetValue()
        if self.rateBoostCheck.IsEnabled():
            settings["rateBoost"] = self.rateBoostCheck.IsChecked()
        i = self.symbolChoice.GetSelection()
        level = self.symbol_levels[i] if 0 <= i < len(self.symbol_levels) else None
        # Detection is turned on and off in the languages list; an edited row keeps its state.
        detect = self.row.detect if self.row is not None else True
        return T.Row(lang, name, symbolLevel=level, detect=detect, **settings)

    def onTest(self, evt):
        row = self.build_row()
        if row is None:
            if self.problem:
                ui.message(self.problem)
            return
        if self.guest is None:
            return
        try:
            if self.saved is None and hosts.is_live(self.guest):
                self.saved = (self.guest, live_values(self.guest))
            hosts.apply_row(self.guest, row, log)
            self.guest.cancel()
            sample = language_label(row.lang)
            i = self.voiceChoice.GetSelection()
            if 0 <= i < len(self.voices):
                sample = f"{self.voices[i].displayName}. {sample}"
            self.guest.speak([sample])
            if not hosts.is_live(self.guest):
                # A guest of the language table: its next piece must put its own row back.
                self.guest._mlangApplied = None
        except Exception:
            log.error("dialingo: test speech failed", exc_info=True)

    def onOk(self, evt):
        if self.guest is None:
            # Translators: Message when a synthesizer cannot be loaded.
            gui.messageBox(_("Synthesizer could not be loaded. See the NVDA log."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.synthChoice.SetFocus()
            return
        row = self.build_row()
        if row is None:
            # Translators: Title of the message shown when the language dialog cannot be saved.
            gui.messageBox(self.problem or _("Enter a language."), _("Error"), wx.OK | wx.ICON_ERROR, self)
            self.langCombo.SetFocus()
            return
        existing = self.table.row_for(row.lang, exact=True)
        if existing is not None and (self.row is None or existing.lang.lower() != self.row.lang.lower()):
            # Translators: Asks whether a new or edited row replaces another row for the same language; %s is
            # the language's name.
            text = _("There is already a row for %s. Replace it?") % language_label(existing.lang)
            # Translators: Title of the message that asks whether to replace a language's row.
            if gui.messageBox(text, _("Replace language"), wx.YES_NO | wx.ICON_WARNING, self) != wx.YES:
                self.langCombo.SetFocus()
                return
        self.result = row
        self.restore_live()
        self.EndModal(wx.ID_OK)

    def restore_live(self):
        """Put back what a preview through the synthesizer in use changed, as it was before the first one. A
        dialog that never previewed leaves it alone, so changes not yet saved in NVDA's voice panel stay."""
        if self.saved is None:
            return
        guest, values = self.saved
        self.saved = None
        for setting, value in values.items():
            try:
                if hosts.read(guest, setting) != value:
                    setattr(guest, setting, value)
            except Exception:
                log.debugWarning(f"dialingo: could not restore {setting} after a preview", exc_info=True)
        guest._mlangApplied = None


def live_values(synth):
    """A synthesizer's current values of the settings it keeps in the configuration, voice and variant first,
    since setting those can reset the others."""
    ids = [s.id for s in synth.supportedSettings if getattr(s, "useConfig", True)]
    ids.sort(key=lambda s: (s != "voice", s != "variant"))
    values = {}
    for setting in ids:
        try:
            values[setting] = hosts.read(synth, setting)
        except Exception:
            pass
    return values
