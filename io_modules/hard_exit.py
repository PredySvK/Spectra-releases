"""End the process at once, leaving a window or its worker threads unfinished."""

import ctypes
import os
import sys
from typing import NoReturn


def exit_hard(code: int) -> NoReturn:
    """Flush the output and end the process with `code`, running no shutdown code.

    On Windows `os._exit` still detaches the DLLs, and Shiboken's shutdown then walks
    the wrappers of a Python that was never finalized and sometimes crashes (§1.274).
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:  # no console in the installed app, or a closed pipe
            pass
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        kernel32.TerminateProcess(kernel32.GetCurrentProcess(), code)
    os._exit(code)
