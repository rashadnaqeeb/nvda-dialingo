# The column headers of the focused grid row, as labels for the detector. NVDA's Outlook module reads a
# message list row as one string that joins each header to its cell ("From Erik Holm, Subject
# specialpedagog på skolan"), and judged whole, the English header pulls the Swedish subject toward English.
# The detector reads each header as its own clause in the default language and each cell alone.

import api
import config
import controlTypes
import UIAHandler
from config.configFlags import ReportTableHeaders
from logHandler import log
from UIAHandler.utils import createUIAMultiPropertyCondition

ROWS = {
    controlTypes.Role.TABLEROW,
    controlTypes.Role.DATAITEM,
    controlTypes.Role.LISTITEM,
    controlTypes.Role.TREEVIEWITEM,
}


def headers(element):
    """The names of the column headers of a UIA row's text cells, as NVDA's Outlook module collects them."""
    request = UIAHandler.handler.baseCacheRequest.clone()
    request.addProperty(UIAHandler.UIA_TableItemColumnHeaderItemsPropertyId)
    request.TreeScope = UIAHandler.TreeScope_Children
    # Text cells only: Outlook fails to cache any children in conversation view otherwise.
    request.treeFilter = createUIAMultiPropertyCondition(
        {UIAHandler.UIA_ControlTypePropertyId: [UIAHandler.UIA_TextControlTypeId]},
    )
    children = element.buildUpdatedCache(request).getCachedChildren()
    names = set()
    for index in range(children.length if children else 0):
        try:
            items = children.getElement(index).getCachedPropertyValueEx(
                UIAHandler.UIA_TableItemColumnHeaderItemsPropertyId,
                True,
            )
            if not items:
                continue
            items = items.QueryInterface(UIAHandler.IUIAutomationElementArray)
            for k in range(items.length):
                name = (items.getElement(k).currentName or "").strip()
                if any(c.isalpha() for c in name):
                    names.add(name)
        except Exception:
            continue
    return tuple(names)


class GridLabels:
    """The labels for the current focus, read once each time the focus enters a kind of row in a window (a
    message list's rows, not its window's folder tree), so a column added or renamed while away is picked up
    on return."""

    def __init__(self):
        self.key = None
        self.labels = ()

    def current(self):
        if config.conf["documentFormatting"]["reportTableHeaders"] not in (
            ReportTableHeaders.ROWS_AND_COLUMNS,
            ReportTableHeaders.COLUMNS,
        ):
            self.key = None
            return ()
        obj = api.getFocusObject()
        element = getattr(obj, "UIAElement", None)
        if element is None or obj.role not in ROWS:
            self.key = None
            return ()
        key = (obj.windowHandle, element.cachedClassName)
        if key != self.key:
            self.key = key
            try:
                self.labels = headers(element)
            except Exception:
                log.debugWarning("multilanguage: no column headers for the focused row", exc_info=True)
                self.labels = ()
        return self.labels
