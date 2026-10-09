"""
Measurement files on disk: which ones count, how they are identified, and
which reader opens them.

The identity helpers (`canonical_path`, `file_stamp`, `folder_fingerprint`) are
here rather than beside the cache that consumes them, because half the callers
never scan anything -- they only need to key a path the same way everything
else does.
"""

import functools
import glob
import logging
import os
from typing import List, Optional

from io_modules.reader_unv import AccReaderUnv


# Single source of truth for which measurement files the workspace recognizes.
# Both the directory scan and the startup cache validation read this, so the two
# can never drift apart and disagree about what belongs in a workspace.
SUPPORTED_EXTENSIONS = ("*.unv", "*.uff", "*.asc", "*.xlsx", "*.txt")

_MEASUREMENT_SUFFIXES = frozenset(ext.replace("*", "").lower() for ext in SUPPORTED_EXTENSIONS)

# Suffixes too generic to trust: the metadata Excel, a README or notes share
# them, so such a file is a measurement only if its header says so (§1.134).
# A further format under one of these (ANSYS) is one more recogniser here.
_RECOGNISED_BY_HEADER = frozenset({".xlsx", ".txt"})

_log = logging.getLogger(__name__)


def has_measurement_suffix(name: str) -> bool:
    """True if the name ends in a suffix a measurement file can have -- no disk access."""
    return os.path.splitext(name)[1].lower() in _MEASUREMENT_SUFFIXES


def is_measurement_file(path: str) -> bool:
    """
    True if the file is one the workspace treats as a measurement: by suffix,
    or for a generic suffix by a reader recognising its header.
    """
    if not has_measurement_suffix(path):
        return False
    if os.path.splitext(path)[1].lower() not in _RECOGNISED_BY_HEADER:
        return True
    stamp = file_stamp(path)
    if stamp is None:
        return False
    recognised = _is_recognised(canonical_path(path), stamp["mtime_ns"], stamp["size"])
    if not recognised:
        _log.debug("Not a measurement, no reader recognises its header: %s", path)
    return recognised


@functools.lru_cache(maxsize=1024)
def _is_recognised(path: str, _mtime_ns: int, _size: int) -> bool:
    """Keyed by stamp, so a folder fingerprint re-reads a workbook only when it changed."""
    from io_modules.reader_masta import is_masta_file
    from io_modules.reader_processed_measurement import is_processed_measurement_file
    return (is_processed_measurement_file(path) if os.path.splitext(path)[1].lower() == ".txt"
            else is_masta_file(path))


# Which reader owns which extension. Kept next to SUPPORTED_EXTENSIONS because the
# two are one decision: a suffix listed there but missing here is a file the
# browser offers, the scan accepts and no parser understands.
_READERS_BY_SUFFIX = {
    ".unv": "AccReaderUnv",
    ".uff": "AccReaderUnv",
    ".asc": "AccReaderAsc",
    ".xlsx": "AccReaderMasta",
    ".txt": "AccReaderProcessedMeasurement",
}


# Readers of simulation results; every other reader reads a measurement.
_SIMULATED_READERS = {"AccReaderMasta"}


def is_simulated_result_file(file_path: str) -> bool:
    """True when the reader that opens this file reads a simulation (#511)."""
    suffix = os.path.splitext(file_path)[1].lower()
    return _READERS_BY_SUFFIX.get(suffix) in _SIMULATED_READERS


def open_measurement_reader(file_path: str):
    """
    The reader for a measurement file, chosen by extension.

    Single dispatch point: the scan worker and DataAccessor both used to spell
    out `if ext == ".asc" ... else UNV`, so adding a third format meant editing
    three places, and an unsupported extension that slipped past
    is_measurement_file was silently handed to the UNV parser -- which fails
    somewhere inside the SDRC-58 block parse rather than saying the format is
    not supported.
    """
    suffix = os.path.splitext(file_path)[1].lower()
    reader_name = _READERS_BY_SUFFIX.get(suffix)
    if reader_name is None:
        raise ValueError(
            f"Unsupported measurement format '{suffix or file_path}'. "
            f"Supported: {', '.join(sorted(_READERS_BY_SUFFIX))}."
        )

    if reader_name == "AccReaderAsc":
        from io_modules.reader_asc import AccReaderAsc
        return AccReaderAsc(file_path)
    if reader_name == "AccReaderMasta":
        from io_modules.reader_masta import AccReaderMasta
        return AccReaderMasta(file_path)
    if reader_name == "AccReaderProcessedMeasurement":
        from io_modules.reader_processed_measurement import AccReaderProcessedMeasurement
        return AccReaderProcessedMeasurement(file_path)
    return AccReaderUnv(file_path)


def discard_reader_caches() -> None:
    """Forget what the readers keep of a parsed file between reads."""
    from io_modules.reader_asc import discard_asc_caches
    discard_asc_caches()


def canonical_path(file_path: str) -> str:
    """
    The form a path is keyed by in the cache.

    Windows takes both separators and ignores case, so the same file arrives
    spelled several ways: Qt's directory chooser hands back forward slashes,
    glob and os.path hand back backslashes. The cache compared these raw, so a
    folder opened through the dialog produced keys like
    'D:/data\\run.unv' that never matched the 'D:\\data\\...'
    form used to look them up -- every entry missed and the folder was silently
    re-parsed on every open, whatever its stamps said.
    """
    return os.path.normcase(os.path.abspath(file_path))


def file_exists(file_path: str) -> bool:
    """Whether a path currently points at a file on disk."""
    return os.path.isfile(file_path)


def file_stamp(file_path: str) -> Optional[dict]:
    """
    Cheap identity for a file: modification time and size.

    Used to tell a cached entry apart from the file it was built from. Nanosecond
    mtime is stored rather than the float seconds, because the float loses
    precision through JSON and can make a genuinely re-written file look
    unchanged. Returns None when the file cannot be stat'ed, which callers treat
    as "cannot be trusted".
    """
    try:
        stat_result = os.stat(file_path)
    except OSError:
        return None
    return {"mtime_ns": stat_result.st_mtime_ns, "size": stat_result.st_size}

def discover_measurement_files(directory_path: str) -> List[str]:
    """
    Lists every supported measurement file in a directory, case-insensitively.

    Module-level rather than a method because the project indexer needs the same
    answer without owning a MeasurementScanner; MeasurementScanner keeps a thin
    delegate so existing callers are unaffected.

    The directory is glob-escaped because only the extension is meant to be a
    pattern. A perfectly ordinary folder name like "Run [2024]" was otherwise
    read by glob as a character class and matched nothing at all -- the folder
    came back empty here, which made index_root() report every measurement in
    it as missing and emptied it out of the Data Pool.
    """
    escaped_directory = glob.escape(directory_path)
    discovered_files = []
    for ext in SUPPORTED_EXTENSIONS:
        discovered_files.extend(glob.glob(os.path.join(escaped_directory, ext)))
        discovered_files.extend(glob.glob(os.path.join(escaped_directory, ext.upper())))
    return sorted(path for path in set(discovered_files) if is_measurement_file(path))


def discover_measurement_folders(root_path: str) -> List[str]:
    """
    Every directory at or below root_path that directly holds at least one
    supported measurement file.

    Lets a single "Add to Data Pool" click on a parent folder (e.g. a dataset
    root with per-run subfolders) expand into one entry per leaf folder --
    the same shape build_ingest_folder_map() already produces for a manual multi-select,
    so a parent-folder pick and hand-picking every child folder behave
    identically downstream. A folder is only listed if it has files directly
    in it; an empty organizational folder (no measurements anywhere below it)
    contributes nothing, same as today's non-recursive scan of an empty folder.
    """
    return sorted(
        dirpath for dirpath, _dirnames, _filenames in os.walk(root_path)
        if discover_measurement_files(dirpath)
    )


def holds_measurement_suffix(directory: str) -> bool:
    """
    Whether a folder directly holds a file with a measurement suffix.

    One directory listing, by suffix only (no header reads, no recursion), so it
    is cheap enough for the GUI thread after the user has picked a folder.
    """
    try:
        with os.scandir(directory) as found:
            return any(has_measurement_suffix(entry.name) and entry.is_file() for entry in found)
    except OSError:
        return False


def folder_fingerprint(directory: str) -> tuple:
    """
    What the measurement files in a folder look like right now.

    Deliberately only the supported measurement files, and only their name,
    size and modification time -- the same cheap identity the folder cache
    already trusts. Anything else in the folder, the cache file included, is
    invisible to this and therefore cannot trigger a refresh.

    By suffix only, never by header: the folder watcher calls this on the GUI
    thread (#507). A changed README.txt is then a refresh that adds nothing.
    """
    entries = []
    try:
        with os.scandir(directory) as found:
            for entry in found:
                if not has_measurement_suffix(entry.name):
                    continue
                try:
                    if not entry.is_file():
                        continue
                    stat_result = entry.stat()
                except OSError:
                    continue
                entries.append((entry.name.lower(), stat_result.st_size, stat_result.st_mtime_ns))
    except OSError:
        return ()
    return tuple(sorted(entries))
