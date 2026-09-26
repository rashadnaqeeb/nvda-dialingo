"""The Windows spelling dictionary a configured language needs, and its installation.

The detector's dictionary rules need the language's spelling dictionary, which Windows installs as the
"Basic typing" feature of its language pack: a Windows capability that only an administrator can add.
Installing runs Add-WindowsCapability in an elevated Windows PowerShell: Windows asks for consent through
UAC, then downloads the feature from Windows Update. Nothing here runs on the speech path.
"""
import ctypes
import threading

from .scripts import windows_tag

BASIC = "Basic"  # the spelling dictionary ("Basic typing")

SEE_MASK_NOCLOSEPROCESS = 0x00000040
SW_SHOWNORMAL = 1
INFINITE = 0xFFFFFFFF


def full_tag(language):
    """Windows' full locale for a language ('es-ES' for 'es', 'ar-SA' for 'ar'), as capability names need."""
    tag = windows_tag(language)
    kernel32 = getattr(ctypes, "windll", None) and ctypes.windll.kernel32
    if kernel32 is None:
        return tag
    buf = ctypes.create_unicode_buffer(85)
    if kernel32.ResolveLocaleName(tag, buf, 85) and buf.value:
        return buf.value
    return tag


def capability(language, feature=BASIC):
    """The Windows capability name of the dictionary (or another language feature) for a language."""
    return f"Language.{feature}~~~{full_tag(language)}~0.0.1.0"


def command(names):
    """The PowerShell command that installs the named capabilities, stopping at the first failure."""
    steps = "; ".join(f"Add-WindowsCapability -Online -Name '{name}'" for name in names)
    return f"$ErrorActionPreference = 'Stop'; {steps}"


class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_ulong),
        ("hIconOrMonitor", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


def install(names, on_done):
    """Installs the named capabilities in an elevated PowerShell window.

    Returns False, without calling on_done, when Windows did not start it: the UAC prompt was declined or
    the launch failed. Otherwise on_done(exit_code) is called from a worker thread when the window closes;
    0 means every feature installed.
    """
    parameters = f'-NoProfile -ExecutionPolicy Bypass -Command "{command(names)}"'
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(info)
    info.fMask = SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "runas"
    info.lpFile = "powershell.exe"
    info.lpParameters = parameters
    info.nShow = SW_SHOWNORMAL
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)) or not info.hProcess:
        return False
    handle = info.hProcess

    def wait():
        kernel32 = ctypes.windll.kernel32
        code = None
        try:
            kernel32.WaitForSingleObject(handle, INFINITE)
            value = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(value)):
                code = value.value
        finally:
            kernel32.CloseHandle(handle)
        on_done(code)

    threading.Thread(target=wait, name="multilanguage-langpack", daemon=True).start()
    return True
