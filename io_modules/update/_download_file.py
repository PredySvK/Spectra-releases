"""Open the reserved Update download so shutdown can still delete it."""

import os
from pathlib import Path
import sys


def open_download_file(destination: Path):
    """Allow shutdown to unlink even while a Windows network read is blocked.

    Open only the reserved file: removal before a queued worker starts must
    never let that worker recreate it. Windows' default Python file sharing
    denies deletion until close, so opt into FILE_SHARE_DELETE here.
    """
    if sys.platform != "win32":
        return destination.open("r+b")
    import ctypes
    from ctypes import wintypes
    import msvcrt

    create_file = ctypes.WinDLL("kernel32", use_last_error=True).CreateFileW
    create_file.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                           wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                           wintypes.HANDLE]
    create_file.restype = wintypes.HANDLE
    # GENERIC_WRITE, all three sharing modes, OPEN_EXISTING, normal attributes.
    handle = create_file(str(destination), 0x40000000, 0x7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
    except BaseException:
        ctypes.windll.kernel32.CloseHandle(wintypes.HANDLE(handle))
        raise
    return os.fdopen(descriptor, "wb")
