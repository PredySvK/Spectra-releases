"""The `machine` section of the Benchmark report, from the stdlib only (ADR §1.132)."""

import functools
import os
import platform
import socket
import subprocess
import sys
import time
from typing import Any, Dict, Iterable, Optional

import numpy
import scipy

from signal_processing.dsp.steps.frame_fft import FFT_WORKERS

UNKNOWN = "unknown"


def read_machine_info(input_paths: Iterable[str]) -> Dict[str, Any]:
    return {
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "cpu_model": _cpu_model(),
        "cpu_cores": _physical_cores(),
        "cpu_threads": os.cpu_count(),
        "ram_gb": _ram_gb(),
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "scipy": scipy.__version__,
        "blas": _blas(),
        "fft_workers": FFT_WORKERS,
        "cpu_clock_step_ms": _cpu_clock_step_ms(),
        "input_disks": {path: _disk_of(path) for path in input_paths},
        "display": "none",
    }


def _cpu_clock_step_ms() -> float:
    """The smallest CPU time the OS reports (15.6 ms on Windows): CPU ms below a few steps are noise."""
    def next_tick(since):
        while (now := time.process_time()) == since:
            pass
        return now
    start = next_tick(time.process_time())  # the first tick may come after part of a step
    return round((next_tick(start) - start) * 1000, 3)


def _blas() -> str:
    try:
        blas = numpy.show_config(mode="dicts")["Build Dependencies"]["blas"]
        return f"{blas.get('name', UNKNOWN)} {blas.get('version', '')}".strip()
    except Exception:
        return UNKNOWN


def _cpu_model() -> str:
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError:
            return platform.processor() or UNKNOWN
    for line in _read_lines("/proc/cpuinfo"):
        if line.lower().startswith(("model name", "cpu model")):
            return line.split(":", 1)[1].strip()
    return platform.processor() or platform.machine() or UNKNOWN


def _physical_cores() -> Optional[int]:
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.GetLogicalProcessorInformationEx.argtypes = [
            ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
        size = wintypes.DWORD(0)
        kernel32.GetLogicalProcessorInformationEx(0, None, ctypes.byref(size))  # 0 = RelationProcessorCore
        buffer = ctypes.create_string_buffer(size.value)
        if not kernel32.GetLogicalProcessorInformationEx(0, buffer, ctypes.byref(size)):
            return None
        cores, offset = 0, 0
        while offset < size.value:  # variable-size records: Relationship, Size, ...
            cores += 1
            offset += int.from_bytes(buffer.raw[offset + 4:offset + 8], "little")
        return cores
    pairs, physical_id = set(), "0"
    for line in _read_lines("/proc/cpuinfo"):
        key, _, value = line.partition(":")
        if key.strip() == "physical id":
            physical_id = value.strip()
        elif key.strip() == "core id":
            pairs.add((physical_id, value.strip()))
    # ARM /proc/cpuinfo has no core ids; one thread per core there.
    return len(pairs) or os.cpu_count()


def _ram_gb() -> Optional[float]:
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            class _Status(ctypes.Structure):
                _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD)] + [
                    (field, ctypes.c_uint64) for field in (
                        "ullTotalPhys", "ullAvailPhys", "ullTotalPageFile", "ullAvailPageFile",
                        "ullTotalVirtual", "ullAvailVirtual", "ullAvailExtendedVirtual")]

            status = _Status()
            status.dwLength = ctypes.sizeof(status)
            if not ctypes.WinDLL("kernel32").GlobalMemoryStatusEx(ctypes.byref(status)):
                return None
            total = status.ullTotalPhys
        else:
            total = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        return round(total / 2**30, 1)
    except (OSError, ValueError, AttributeError):
        return None


def _disk_of(path: str) -> Dict[str, str]:
    """Where the input file lives: `location` local | network, `media` ssd | hdd."""
    path = os.path.abspath(path)
    try:
        if sys.platform == "win32":
            return _windows_disk(path)
        return _linux_disk(path)
    except Exception:
        return {"location": UNKNOWN, "media": UNKNOWN}


def _windows_disk(path: str) -> Dict[str, str]:
    import ctypes
    drive = os.path.splitdrive(path)[0]
    if drive.startswith("\\\\"):
        return {"location": "network", "media": UNKNOWN}
    drive_type = ctypes.WinDLL("kernel32").GetDriveTypeW(drive + "\\")
    location = {3: "local", 2: "local", 4: "network"}.get(drive_type, UNKNOWN)
    media = UNKNOWN
    if location == "local" and drive[:1].isalpha():
        media = _windows_media(drive[0].upper())
    return {"location": location, "media": media}


@functools.lru_cache(maxsize=None)
def _windows_media(drive_letter: str) -> str:
    """ssd | hdd | unknown; a drive's media does not change while the process runs."""
    # ponytail: one PowerShell call (~1 s) per drive letter; the stdlib has no
    # other route to the media type on Windows.
    script = (f"$n = (Get-Partition -DriveLetter {drive_letter}).DiskNumber; "
              "(Get-PhysicalDisk | Where-Object DeviceId -eq $n).MediaType")
    result = subprocess.run(["powershell", "-NoProfile", "-Command", script],
                            capture_output=True, text=True, timeout=20)
    return {"SSD": "ssd", "HDD": "hdd"}.get(result.stdout.strip(), UNKNOWN)


_NETWORK_FILESYSTEMS = ("nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "9p")


def _linux_disk(path: str) -> Dict[str, str]:
    mount, fs_type = "", ""
    for line in _read_lines("/proc/mounts"):
        parts = line.split()
        if len(parts) >= 3 and (path == parts[1] or path.startswith(parts[1].rstrip("/") + "/")) \
                and len(parts[1]) >= len(mount):
            mount, fs_type = parts[1], parts[2]
    if fs_type in _NETWORK_FILESYSTEMS:
        return {"location": "network", "media": UNKNOWN}
    device = os.stat(path).st_dev
    block = os.path.realpath(f"/sys/dev/block/{os.major(device)}:{os.minor(device)}")
    for candidate in (block, os.path.dirname(block)):  # a partition's parent is the disk
        rotational = os.path.join(candidate, "queue", "rotational")
        if os.path.exists(rotational):
            with open(rotational) as handle:
                return {"location": "local", "media": "hdd" if handle.read().strip() == "1" else "ssd"}
    return {"location": "local", "media": UNKNOWN}


def _read_lines(path: str):
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read().splitlines()
    except OSError:
        return []


def read_process_rss_mb() -> Optional[float]:
    """Current resident memory of this process in MB, or None where unknown.
    The reader the Benchmark stopwatches sample the per-step RAM peak with."""
    try:
        if sys.platform == "win32":
            return _windows_working_set()() / 2**20
        if os.path.exists("/proc/self/statm"):
            with open("/proc/self/statm") as handle:
                return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2**20
        # ponytail: no stdlib route to the current RSS on macOS; the lifetime peak stands in.
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20
    except (OSError, ValueError, AttributeError, ImportError):
        return None


@functools.lru_cache(maxsize=1)
def _windows_working_set():
    """A callable giving the process working set in bytes, built once."""
    import ctypes
    from ctypes import wintypes

    class _Counters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
            (field, ctypes.c_size_t) for field in (
                "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage",
                "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]

    kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    process = kernel32.GetCurrentProcess()

    def read() -> int:
        counters = _Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
            raise OSError("GetProcessMemoryInfo failed")
        return counters.WorkingSetSize

    return read
