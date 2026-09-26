"""Per-language rate, pitch, and volume on the synthesizer in use, through NVDA's prosody commands.

NVDA's RateCommand, PitchCommand, and VolumeCommand take an offset from the user's configured value and
synthesizers apply them in order with the text, so a row's rate for French becomes "configured rate plus
(row rate minus configured rate)" at the start of each French run and a plain reset at its end. Voices
cannot be chosen this way; the synthesizer picks its own voice for the language, as it does for tagged
text without this add-on. Hosting another synthesizer needs the language table driver.

Imports speech.commands, so it runs inside NVDA or under the test stub.
"""
from speech.commands import LangChangeCommand, PitchCommand, RateCommand, VolumeCommand

from .scripts import base

COMMANDS = {"rate": RateCommand, "pitch": PitchCommand, "volume": VolumeCommand}


def apply_offsets(seq, offsets_for_lang):
    """`seq` with prosody commands around each language run that `offsets_for_lang` has offsets for.

    offsets_for_lang(lang or None) -> {"rate": offset, ...} for a language with a row, else None.
    Any prosody command inside such a run is rebased on the run's own offset: a capital letter's pitch change
    of +30 in a run at +10 becomes +40, and the reset NVDA emits after it becomes +10, so the run keeps its
    parameters.
    """
    out = []
    active = {}
    changed = False
    for item in seq:
        if isinstance(item, LangChangeCommand):
            out.append(item)
            wanted = offsets_for_lang(item.lang) or {}
            for setting, cls in COMMANDS.items():
                if setting in wanted:
                    if active.get(setting) != wanted[setting]:
                        out.append(cls(offset=wanted[setting]) if wanted[setting] else cls())
                        changed = True
                elif setting in active:
                    out.append(cls())
                    changed = True
            active = dict(wanted)
            continue
        for setting, cls in COMMANDS.items():
            # The multiplier form (offset 0) is left alone: NVDA ignores the multiplier once there is an offset.
            if isinstance(item, cls) and setting in active and active[setting] and (item.offset or item.multiplier == 1):
                item = cls(offset=active[setting] + item.offset)
                changed = True
                break
        out.append(item)
    if active:
        for setting in active:
            out.append(COMMANDS[setting]())
        changed = True
    return out if changed else seq


def offsets(rows, configured, supported):
    """{row language: {setting: offset}} for rows of the synthesizer in use; see offsets_for.

    configured(setting) -> the user's configured value of the setting, or None.
    supported(setting) -> whether the synthesizer has the setting.
    """
    table = {}
    for row in rows:
        entry = {}
        for setting in COMMANDS:
            value = row.get(setting)
            if value is None or not supported(setting):
                continue
            current = configured(setting)
            if current is None:
                continue
            entry[setting] = int(value) - int(current)
        if entry:
            table[row.lang] = entry
    return table


def offsets_for(table, lang):
    """A language's offsets from `offsets`, found as Table.row_for finds its row: its own spelling first,
    then any row of the same base language, so two dialect rows keep their own."""
    if not lang:
        return None
    wanted = lang.replace("-", "_").lower()
    for row_lang, entry in table.items():
        if row_lang.replace("-", "_").lower() == wanted:
            return entry
    b = base(lang)
    for row_lang, entry in table.items():
        if base(row_lang) == b:
            return entry
    return None
