"""
Measurement files on disk: which ones count, how they are identified, and
which reader opens them.

The identity helpers (`canonical_path`, `file_stamp`, `folder_fingerprint`) are
here rather than beside the cache that consumes them, because half the callers
never scan anything -- they only need to key a path the same way everything
else does.
"""

import functools
import hashlib
import glob
import logging
import os
from typing import Dict, List, Optional, Protocol, Union

from core.data_block import NVHDataBlock, RawChannel
from core.models import MeasurementRunIndex
from core.source_amplitude import SOURCE_AMPLITUDE_PEAK, SOURCE_AMPLITUDE_RMS
from io_modules.reader_unv import AccReaderUnv


# Single source of truth for which measurement files the workspace recognizes.
# Both the directory scan and the startup cache validation read this, so the two
# can never drift apart and disagree about what belongs in a workspace.
SUPPORTED_EXTENSIONS = ("*.unv", "*.uff", "*.asc", "*.ldsf", "*.hdf", "*.xlsx", "*.txt", "*.csv")

_MEASUREMENT_SUFFIXES = frozenset(ext.replace("*", "").lower() for ext in SUPPORTED_EXTENSIONS)

# Suffixes too generic to trust: the metadata Excel, a README or notes share
# them, so such a file is a measurement only if its header says so (§1.134).
_RECOGNISED_BY_HEADER = frozenset({".xlsx", ".txt", ".csv"})

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
    from io_modules.import_template import resolve_installed_signature
    recognised = _is_recognised(canonical_path(path), stamp["mtime_ns"], stamp["size"],
                                resolve_installed_signature())
    if not recognised:
        _log.debug("Not a measurement, no reader recognises its header: %s", path)
    return recognised


@functools.lru_cache(maxsize=1024)
def _is_recognised(path: str, _mtime_ns: int, _size: int, _templates: str) -> bool:
    """
    Keyed by stamp and by the installed Import templates, so a folder fingerprint
    re-reads a workbook only when it or the templates changed.
    """
    from io_modules.import_template import resolve_installed_templates, read_template_match
    if any(read_template_match(path, template) for template in resolve_installed_templates().values()):
        return True
    from io_modules.reader_ansys import is_ansys_file
    from io_modules.reader_masta import is_masta_file
    from io_modules.reader_processed_measurement import is_processed_measurement_file
    suffix = os.path.splitext(path)[1].lower()
    if suffix == ".txt":
        return is_processed_measurement_file(path)
    if suffix == ".csv":
        return is_ansys_file(path)
    return is_masta_file(path)


# Which reader owns which extension. Kept next to SUPPORTED_EXTENSIONS because the
# two are one decision: a suffix listed there but missing here is a file the
# browser offers, the scan accepts and no parser understands.
_READERS_BY_SUFFIX = {
    ".unv": "AccReaderUnv",
    ".uff": "AccReaderUnv",
    ".asc": "AccReaderAsc",
    ".ldsf": "AccReaderLdsf",
    ".hdf": "AccReaderHdf",
    ".xlsx": "AccReaderMasta",
    ".txt": "AccReaderProcessedMeasurement",
    ".csv": "AccReaderAnsys",
}


# Readers of simulation results; every other reader reads a measurement.
_SIMULATED_READERS = {"AccReaderMasta", "AccReaderAnsys"}


# What an Imported result's amplitude is taken to be until the project says
# otherwise: ANSYS and MASTA export Peak (MASTA's plain "Amplitude" is Peak,
# beside its "RMS Amplitude" and "Peak-to-Peak Amplitude", §1.220), processed
# measurements are RMS. Also the answer for a project written before the
# question existed.
_DEFAULT_SOURCE_AMPLITUDE = {
    "AccReaderMasta": SOURCE_AMPLITUDE_PEAK,
    "AccReaderProcessedMeasurement": SOURCE_AMPLITUDE_RMS,
    "AccReaderAnsys": SOURCE_AMPLITUDE_PEAK,
}


# Reader name by a fixed Import template name; empty because every template is
# read by AccReaderImportTemplate from the project's copy (the registry).
_READERS_BY_TEMPLATE: Dict[str, str] = {}

_TEMPLATE_READER = "AccReaderImportTemplate"


def resolve_reader_name(file_path: str, import_template: str = "") -> Optional[str]:
    """
    The name of the reader that opens this file, or None when none does. The one
    choice every opener goes through (scan, channel read, Imported-result and
    Simulated/Measured questions).

    `import_template` is what the file's Data Pool source assigns; it decides
    when set; a name the project holds no copy of raises ValueError (opening a
    file cannot go on, the classifying helpers below answer None instead).
    Blank (no assignment) leaves the decision to the suffix. No disk access.
    """
    if import_template:
        if import_template in _READERS_BY_TEMPLATE:
            return _READERS_BY_TEMPLATE[import_template]
        from io_modules.import_template import resolve_installed_template
        if resolve_installed_template(import_template) is None:
            raise ValueError(f"Unknown Import template '{import_template}' assigned to {file_path}.")
        return _TEMPLATE_READER
    return _READERS_BY_SUFFIX.get(os.path.splitext(file_path)[1].lower())


def _classify_reader_name(file_path: str, import_template: str) -> Optional[str]:
    """The reader name, or None when none opens the file -- including an assignment nobody holds."""
    try:
        return resolve_reader_name(file_path, import_template)
    except ValueError:
        return None


def resolve_imported_result_reader(file_path: str, import_template: str = "") -> Optional[str]:
    """
    The name of the Imported-result reader that opens this file, or None for a
    time signal (`.unv`, `.uff`, `.asc`, `.ldsf`, `.hdf`). No disk access.
    """
    reader_name = _classify_reader_name(file_path, import_template)
    return reader_name if reader_name in _DEFAULT_SOURCE_AMPLITUDE else None


def resolve_default_source_amplitude(reader_name: str) -> str:
    """The Source amplitude an Imported-result reader is assumed to deliver; RMS for any other."""
    return _DEFAULT_SOURCE_AMPLITUDE.get(reader_name, SOURCE_AMPLITUDE_RMS)


def is_simulated_result_file(file_path: str, import_template: str = "") -> bool:
    """True when the reader that opens this file reads a simulation (#511)."""
    reader_name = _classify_reader_name(file_path, import_template)
    if reader_name == _TEMPLATE_READER:
        from io_modules.import_template import resolve_installed_template
        return resolve_installed_template(import_template).simulated
    return reader_name in _SIMULATED_READERS


class MeasurementReader(Protocol):
    """
    What open_measurement_reader hands out, whatever the format.

    No part of the file is left out in silence. A part a call
    cannot read either makes that call raise -- the file, or the channel, is
    then not read at all -- or goes into `run_index.lost_parts`, which makes the
    measurement Partially read. The blank cells below a column that has ended
    are not a part of the file.
    """
    file_path: str

    def scan_file_structure(self) -> MeasurementRunIndex: ...

    def load_channels_on_demand(self, run_index: MeasurementRunIndex) -> None: ...

    def read_single_channel_data(self, dataset_index: int) -> Union[RawChannel, NVHDataBlock]: ...


def open_measurement_reader(file_path: str, import_template: str = "") -> MeasurementReader:
    """
    The reader for a measurement file, chosen by `resolve_reader_name`: the
    assigned Import template, else the extension.

    Single dispatch point: the scan worker and DataAccessor both used to spell
    out `if ext == ".asc" ... else UNV`, so adding a third format meant editing
    three places, and an unsupported extension that slipped past
    is_measurement_file was silently handed to the UNV parser -- which fails
    somewhere inside the SDRC-58 block parse rather than saying the format is
    not supported.
    """
    reader_name = resolve_reader_name(file_path, import_template)
    if reader_name is None:
        suffix = os.path.splitext(file_path)[1].lower()
        raise ValueError(
            f"Unsupported measurement format '{suffix or file_path}'. "
            f"Supported: {', '.join(sorted(_READERS_BY_SUFFIX))}."
        )

    if reader_name == "AccReaderAsc":
        from io_modules.reader_asc import AccReaderAsc
        return AccReaderAsc(file_path)
    if reader_name == "AccReaderLdsf":
        from io_modules.reader_ldsf import AccReaderLdsf
        return AccReaderLdsf(file_path)
    if reader_name == "AccReaderHdf":
        from io_modules.reader_hdf import AccReaderHdf
        return AccReaderHdf(file_path)
    if reader_name == "AccReaderMasta":
        from io_modules.reader_masta import AccReaderMasta
        return AccReaderMasta(file_path)
    if reader_name == "AccReaderAnsys":
        from io_modules.reader_ansys import AccReaderAnsys
        return AccReaderAnsys(file_path)
    if reader_name == "AccReaderProcessedMeasurement":
        from io_modules.reader_processed_measurement import AccReaderProcessedMeasurement
        return AccReaderProcessedMeasurement(file_path)
    if reader_name == _TEMPLATE_READER:
        from io_modules.import_template import AccReaderImportTemplate, resolve_installed_template
        return AccReaderImportTemplate(file_path, resolve_installed_template(import_template))
    if reader_name == "AccReaderUnv":
        return AccReaderUnv(file_path)
    raise ValueError(f"No reader named '{reader_name}' for {file_path}.")


def discard_reader_caches() -> None:
    """Forget what the readers keep of a parsed file between reads."""
    from io_modules.reader_asc import discard_asc_caches
    discard_asc_caches()
    from io_modules.reader_masta import discard_masta_caches
    discard_masta_caches()
    from io_modules.import_template import discard_import_template_caches
    discard_import_template_caches()


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


def scan_cache_basename(directory_path: str) -> str:
    """
    File name for a folder's scan cache when it lives in a shared cache folder
    (a project's cache/scan/, or the Untitled temp area) rather than beside the
    data.

    The folder's own basename is kept for readability ("setup1-a1b2c3d4.json");
    the short canonical-path hash keeps two roots with the same basename from
    colliding in one cache folder. Both halves are derived from canonical_path,
    so the same folder spelled with either separator or any case resolves to
    exactly one cache file -- the label is lower-cased as a side effect, which
    is a fair price for that guarantee.
    """
    canonical = canonical_path(directory_path)
    digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:8]
    raw_base = os.path.basename(canonical.rstrip("/\\")) or "folder"
    safe_base = "".join(c if c.isalnum() or c in "-_" else "_" for c in raw_base)[:40]
    return f"{safe_base}-{digest}.json"


def file_exists(file_path: str) -> bool:
    """Whether a path currently points at a file on disk."""
    return os.path.isfile(file_path)


def find_missing_files(file_paths) -> tuple:
    """
    The paths among `file_paths` that are not a file on disk, in the order given.

    One stat per path, so its time grows with the number of measurements and
    with how slow the drive is: callers run it on a worker.
    """
    return tuple(path for path in file_paths if not os.path.isfile(path))


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

    Here rather than in scan_cache because the project indexer needs the same
    answer without scanning anything.

    The directory is glob-escaped because only the extension is meant to be a
    pattern. A perfectly ordinary folder name like "Run [2024]" was otherwise
    read by glob as a character class and matched nothing at all -- the folder
    came back empty here, which made the index pass report every measurement in
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
    root with per-run subfolders) expand into one entry per leaf folder,
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
