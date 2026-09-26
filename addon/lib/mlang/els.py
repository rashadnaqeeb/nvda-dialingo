"""Windows Extended Linguistic Services (elscore.dll) language detection through ctypes.

Used by the strict mode as a second recognizer. Importing fails cleanly (OSError) where the DLL is missing.
"""
import ctypes
import unicodedata
from ctypes import wintypes, POINTER, Structure, c_size_t, c_uint, c_void_p, byref

LPWSTR = wintypes.LPWSTR
DWORD = wintypes.DWORD
WORD = wintypes.WORD


class GUID(Structure):
    _fields_ = [("Data1", DWORD), ("Data2", WORD), ("Data3", WORD), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def from_string(cls, s):
        s = s.strip("{}")
        parts = s.split("-")
        g = cls()
        g.Data1 = int(parts[0], 16)
        g.Data2 = int(parts[1], 16)
        g.Data3 = int(parts[2], 16)
        tail = bytes.fromhex(parts[3] + parts[4])
        for i, b in enumerate(tail):
            g.Data4[i] = b
        return g


class MAPPING_ENUM_OPTIONS(Structure):
    _fields_ = [
        ("Size", c_size_t),
        ("pszCategory", LPWSTR),
        ("pszInputLanguage", LPWSTR),
        ("pszOutputLanguage", LPWSTR),
        ("pszInputScript", LPWSTR),
        ("pszOutputScript", LPWSTR),
        ("pszInputContentType", LPWSTR),
        ("pszOutputContentType", LPWSTR),
        ("pGuid", POINTER(GUID)),
        ("OnlineService", c_uint, 2),
        ("ServiceType", c_uint, 2),
    ]


class MAPPING_SERVICE_INFO(Structure):
    _fields_ = [
        ("Size", c_size_t),
        ("pszCopyright", LPWSTR),
        ("wMajorVersion", WORD),
        ("wMinorVersion", WORD),
        ("wBuildVersion", WORD),
        ("wStepVersion", WORD),
        ("dwInputContentTypesCount", DWORD),
        ("prgInputContentTypes", POINTER(LPWSTR)),
        ("dwOutputContentTypesCount", DWORD),
        ("prgOutputContentTypes", POINTER(LPWSTR)),
        ("dwInputLanguagesCount", DWORD),
        ("prgInputLanguages", POINTER(LPWSTR)),
        ("dwOutputLanguagesCount", DWORD),
        ("prgOutputLanguages", POINTER(LPWSTR)),
        ("dwInputScriptsCount", DWORD),
        ("prgInputScripts", POINTER(LPWSTR)),
        ("dwOutputScriptsCount", DWORD),
        ("prgOutputScripts", POINTER(LPWSTR)),
        ("guid", GUID),
        ("pszCategory", LPWSTR),
        ("pszDescription", LPWSTR),
        ("dwPrivateDataSize", DWORD),
        ("pPrivateData", c_void_p),
        ("pContext", c_void_p),
        ("IsOneToOneLanguageMapping", c_uint, 1),
        ("HasSubservices", c_uint, 1),
        ("OnlineOnly", c_uint, 1),
        ("ServiceType", c_uint, 2),
    ]


class MAPPING_DATA_RANGE(Structure):
    _fields_ = [
        ("dwStartIndex", DWORD),
        ("dwEndIndex", DWORD),
        ("pszDescription", LPWSTR),
        ("dwDescriptionLength", DWORD),
        ("pData", c_void_p),
        ("dwDataSize", DWORD),
        ("pszContentType", LPWSTR),
        ("prgActionIds", POINTER(LPWSTR)),
        ("dwActionsCount", DWORD),
        ("prgActionDisplayNames", POINTER(LPWSTR)),
    ]


class MAPPING_PROPERTY_BAG(Structure):
    _fields_ = [
        ("Size", c_size_t),
        ("prgResultRanges", POINTER(MAPPING_DATA_RANGE)),
        ("dwRangesCount", DWORD),
        ("pServiceData", c_void_p),
        ("dwServiceDataSize", DWORD),
        ("pCallerData", c_void_p),
        ("dwCallerDataSize", DWORD),
        ("pContext", c_void_p),
    ]


els = ctypes.WinDLL("elscore.dll")
els.MappingGetServices.restype = ctypes.HRESULT
els.MappingGetServices.argtypes = [POINTER(MAPPING_ENUM_OPTIONS), POINTER(POINTER(MAPPING_SERVICE_INFO)), POINTER(DWORD)]
els.MappingRecognizeText.restype = ctypes.HRESULT
els.MappingRecognizeText.argtypes = [POINTER(MAPPING_SERVICE_INFO), wintypes.LPCWSTR, DWORD, DWORD, c_void_p, POINTER(MAPPING_PROPERTY_BAG)]
els.MappingFreePropertyBag.restype = ctypes.HRESULT
els.MappingFreePropertyBag.argtypes = [POINTER(MAPPING_PROPERTY_BAG)]
els.MappingFreeServices.restype = ctypes.HRESULT
els.MappingFreeServices.argtypes = [POINTER(MAPPING_SERVICE_INFO)]

GUID_LANGUAGE_DETECTION = GUID.from_string("{CF7E00B1-909B-4d95-A8F4-611F7C377702}")
GUID_SCRIPT_DETECTION = GUID.from_string("{2D64B439-6CAF-4f6b-B688-E5D0F4FAA7D7}")


def get_service(guid):
    opts = MAPPING_ENUM_OPTIONS()
    opts.Size = ctypes.sizeof(opts)
    opts.pGuid = ctypes.pointer(guid)
    services = POINTER(MAPPING_SERVICE_INFO)()
    count = DWORD()
    hr = els.MappingGetServices(byref(opts), byref(services), byref(count))
    if hr != 0 or count.value == 0:
        raise RuntimeError(f"MappingGetServices hr=0x{hr & 0xFFFFFFFF:08x} count={count.value}")
    return services


def wide_list(ptr, size_bytes):
    """Decode a double-null-terminated UTF-16 list."""
    raw = ctypes.string_at(ptr, size_bytes)
    text = raw.decode("utf-16-le", errors="replace")
    return [s for s in text.split("\x00") if s]


def recognize(service, text):
    text = unicodedata.normalize("NFC", text)
    bag = MAPPING_PROPERTY_BAG()
    bag.Size = ctypes.sizeof(bag)
    # The length is in UTF-16 units: a character beyond the Basic Multilingual Plane counts twice.
    hr = els.MappingRecognizeText(service, text, len(text.encode("utf-16-le")) // 2, 0, None, byref(bag))
    if hr != 0:
        raise RuntimeError(f"MappingRecognizeText hr=0x{hr & 0xFFFFFFFF:08x}")
    out = []
    try:
        for i in range(bag.dwRangesCount):
            r = bag.prgResultRanges[i]
            data = wide_list(r.pData, r.dwDataSize) if r.pData and r.dwDataSize else []
            out.append((r.dwStartIndex, r.dwEndIndex, data))
    finally:
        els.MappingFreePropertyBag(byref(bag))
    return out
