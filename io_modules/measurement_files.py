"""
Measurement files on disk: which ones count, how they are identified, and
which reader opens them.

Every fact about one reader -- its suffixes, how its header is recognised,
whether it reads a simulation, what its amplitude is taken to be -- lives in
its `ReaderDescription` in `READER_DESCRIPTIONS`; the dispatch and every
question about a file ask that description, so a new reader is one entry here
and a case in the reader contract test.

The identity helpers (`canonical_path`, `file_stamp`, `folder_fingerprint`) are
here rather than beside the cache that consumes them, because half the callers
never scan anything -- they only need to key a path the same way everything
else does.
"""

import dataclasses
import functools
import hashlib
import glob
import importlib
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Protocol, Tuple, Union

from core.data_block import NVHDataBlock, RawChannel
from core.import_template import DATA_KIND_TIME_SIGNAL
from core.models import MeasurementRunIndex
from core.source_amplitude import SOURCE_AMPLITUDE_PEAK, SOURCE_AMPLITUDE_RMS


def _lazy(module: str, name: str) -> Callable:
    """
    A call of `module.name` that imports the module only when called, so the
    registry costs no reader import and a monkeypatched name is still seen.
    """
    def call(*args):
        return getattr(importlib.import_module(module), name)(*args)
    call.__qualname__ = f"{module}.{name}"
    return call


@dataclass(frozen=True)
class ReaderDescription:
    """
    Everything the program knows about one reader without opening a file.

    `name` is the reader's class name, the key an Add groups its Source
    amplitude question by. `recognise` reads a file's header to tell whether
    the reader owns it; None means the suffix alone decides. A reader with
    `imported_result` set hands back a finished block of its kind (§1.189),
    any other a waveform's parts. A reader whose `asks_source_amplitude` is set reads an Imported result whose amplitude the
    user states once per Add (§1.157); `default_source_amplitude` is what it is
    taken to be until the project says otherwise (blank: RMS).
    """
    name: str
    suffixes: Tuple[str, ...]
    open_reader: Callable[[str], "MeasurementReader"]
    recognise: Optional[Callable[[str], bool]] = None
    simulated: bool = False
    imported_result: bool = False
    asks_source_amplitude: bool = False
    default_source_amplitude: str = ""
    label: str = ""
    discard_caches: Optional[Callable[[], None]] = None


# One entry per reader, in the order SUPPORTED_EXTENSIONS lists them. ANSYS
# and MASTA export Peak (MASTA's plain "Amplitude" is Peak, beside its "RMS
# Amplitude" and "Peak-to-Peak Amplitude", §1.220), processed measurements are
# RMS; that default is also the answer for a project written before the
# question existed. `label` is the Pairing tab's word for the reader.
READER_DESCRIPTIONS: Tuple[ReaderDescription, ...] = (
    ReaderDescription(
        name="AccReaderUnv", suffixes=(".unv", ".uff"),
        open_reader=_lazy("io_modules.reader_unv", "AccReaderUnv")),
    ReaderDescription(
        name="AccReaderAsc", suffixes=(".asc",),
        open_reader=_lazy("io_modules.reader_asc", "AccReaderAsc"),
        discard_caches=_lazy("io_modules.reader_asc", "discard_asc_caches")),
    ReaderDescription(
        name="AccReaderLdsf", suffixes=(".ldsf",),
        open_reader=_lazy("io_modules.reader_ldsf", "AccReaderLdsf")),
    ReaderDescription(
        name="AccReaderHdf", suffixes=(".hdf",),
        open_reader=_lazy("io_modules.reader_hdf", "AccReaderHdf")),
    ReaderDescription(
        name="AccReaderMasta", suffixes=(".xlsx",),
        open_reader=_lazy("io_modules.reader_masta", "AccReaderMasta"),
        recognise=_lazy("io_modules.reader_masta", "is_masta_file"),
        simulated=True, imported_result=True, asks_source_amplitude=True,
        default_source_amplitude=SOURCE_AMPLITUDE_PEAK, label="MASTA",
        discard_caches=_lazy("io_modules.reader_masta", "discard_masta_caches")),
    ReaderDescription(
        name="AccReaderProcessedMeasurement", suffixes=(".txt",),
        open_reader=_lazy("io_modules.reader_processed_measurement", "AccReaderProcessedMeasurement"),
        recognise=_lazy("io_modules.reader_processed_measurement", "is_processed_measurement_file"),
        imported_result=True, asks_source_amplitude=True,
        default_source_amplitude=SOURCE_AMPLITUDE_RMS, label="Processed measurement"),
    ReaderDescription(
        name="AccReaderAnsys", suffixes=(".csv",),
        open_reader=_lazy("io_modules.reader_ansys", "AccReaderAnsys"),
        recognise=_lazy("io_modules.reader_ansys", "is_ansys_file"),
        simulated=True, imported_result=True, asks_source_amplitude=True,
        default_source_amplitude=SOURCE_AMPLITUDE_PEAK, label="ANSYS"),
)


# What every file read by an Import template shares; the rest comes from the
# project's copy of the template (`_describe_template_reader`). Add never asks
# its Source amplitude: the template states it (§1.221).
_TEMPLATE_READER = ReaderDescription(
    name="AccReaderImportTemplate", suffixes=(),
    open_reader=_lazy("io_modules.import_template", "AccReaderImportTemplate"),
    discard_caches=_lazy("io_modules.import_template", "discard_import_template_caches"))


_DESCRIPTIONS_BY_SUFFIX: Dict[str, ReaderDescription] = {
    suffix: description for description in READER_DESCRIPTIONS for suffix in description.suffixes
}

# Single source of truth for which measurement files the workspace recognizes.
# Both the directory scan and the startup cache validation read this, so the two
# can never drift apart and disagree about what belongs in a workspace.
SUPPORTED_EXTENSIONS = tuple(f"*{suffix}" for suffix in _DESCRIPTIONS_BY_SUFFIX)

_MEASUREMENT_SUFFIXES = frozenset(_DESCRIPTIONS_BY_SUFFIX)

# Suffixes too generic to trust: the metadata Excel, a README or notes share
# them, so such a file is a measurement only if its header says so (§1.134).
_RECOGNISED_BY_HEADER = frozenset(
    suffix for suffix, description in _DESCRIPTIONS_BY_SUFFIX.items() if description.recognise is not None)

_log = logging.getLogger(__name__)


def has_measurement_suffix(name: str) -> bool:
    """True if the name ends in a suffix a measurement file can have -- no disk access."""
    return os.path.splitext(name)[1].lower() in _MEASUREMENT_SUFFIXES


def is_measurement_file(path: str, templates: Optional[Tuple[Any, ...]] = None) -> bool:
    """
    True if the file is one the workspace treats as a measurement: by suffix,
    or for a generic suffix by a reader recognising its header.

    `templates` are the Import templates that may recognise it; None means the
    installed ones (the open project's copies). A plan for an Add passes the
    templates it adds with, which the project takes only once the run reads.
    """
    if not has_measurement_suffix(path):
        return False
    if os.path.splitext(path)[1].lower() not in _RECOGNISED_BY_HEADER:
        return True
    stamp = file_stamp(path)
    if stamp is None:
        return False
    if templates is None:
        from io_modules.import_template import resolve_installed_signature
        recognised = _is_recognised(path, stamp["mtime_ns"], stamp["size"], resolve_installed_signature())
    else:
        recognised = _is_recognised(path, stamp["mtime_ns"], stamp["size"], None, tuple(templates))
    if not recognised:
        _log.debug("Not a measurement, no reader recognises its header: %s", path)
    return recognised


@functools.lru_cache(maxsize=1024)
def _is_recognised(path: str, _mtime_ns: int, _size: int, _signature: Optional[str],
                   templates: Optional[Tuple[Any, ...]] = None) -> bool:
    """
    Keyed by stamp and by the Import templates (the installed ones by their
    signature, a given set by itself), so a folder fingerprint re-reads a
    workbook only when it or the templates changed.
    """
    from io_modules.import_template import resolve_installed_templates, read_template_match
    if templates is None:
        templates = tuple(resolve_installed_templates().values())
    if any(read_template_match(path, template) for template in templates):
        return True
    return _DESCRIPTIONS_BY_SUFFIX[os.path.splitext(path)[1].lower()].recognise(path)


def _describe_template_reader(import_template: str, file_path: str) -> ReaderDescription:
    """The template reader as the project's copy of `import_template` describes it."""
    from io_modules.import_template import resolve_installed_template
    template = resolve_installed_template(import_template)
    if template is None:
        raise ValueError(f"Unknown Import template '{import_template}' assigned to {file_path}.")
    return dataclasses.replace(
        _TEMPLATE_READER,
        open_reader=lambda path: _TEMPLATE_READER.open_reader(path, template),
        simulated=template.simulated,
        imported_result=template.data_kind != DATA_KIND_TIME_SIGNAL,
        default_source_amplitude=template.source_amplitude,
    )


def resolve_reader_description(file_path: str, import_template: str = "") -> Optional[ReaderDescription]:
    """
    The description of the reader that opens this file, or None when none does.
    The one choice every opener goes through (scan, channel read, Imported-result
    and Simulated/Measured questions).

    `import_template` is what the file's Data Pool source assigns; it decides
    when set; a name the project holds no copy of raises ValueError (opening a
    file cannot go on, the classifying helpers below answer None instead).
    Blank (no assignment) leaves the decision to the suffix. No disk access.
    """
    if import_template:
        return _describe_template_reader(import_template, file_path)
    return _DESCRIPTIONS_BY_SUFFIX.get(os.path.splitext(file_path)[1].lower())


def resolve_named_reader_description(reader_name: str) -> Optional[ReaderDescription]:
    """The description of the fixed reader called `reader_name`, or None."""
    return next((description for description in READER_DESCRIPTIONS if description.name == reader_name), None)


def _classify(file_path: str, import_template: str) -> Optional[ReaderDescription]:
    """The reader's description, or None when none opens the file -- including an assignment nobody holds."""
    try:
        return resolve_reader_description(file_path, import_template)
    except ValueError:
        return None


def resolve_imported_result_reader(file_path: str, import_template: str = "") -> Optional[str]:
    """
    The name of the reader whose Imported result an Add asks the Source
    amplitude of, or None for a time signal or a file read by an Import
    template. No disk access.
    """
    description = _classify(file_path, import_template)
    return description.name if description is not None and description.asks_source_amplitude else None


def is_simulated_result_file(file_path: str, import_template: str = "") -> bool:
    """True when the reader that opens this file reads a simulation (#511)."""
    description = _classify(file_path, import_template)
    return description is not None and description.simulated


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

    def read_run_index(self) -> MeasurementRunIndex: ...

    def read_single_channel_data(self, dataset_index: int) -> Union[RawChannel, NVHDataBlock]: ...


def open_measurement_reader(file_path: str, import_template: str = "") -> MeasurementReader:
    """
    The reader for a measurement file, chosen by `resolve_reader_description`:
    the assigned Import template, else the extension.

    Single dispatch point: the scan worker and DataAccessor both used to spell
    out `if ext == ".asc" ... else UNV`, so adding a third format meant editing
    three places, and an unsupported extension that slipped past
    is_measurement_file was silently handed to the UNV parser -- which fails
    somewhere inside the SDRC-58 block parse rather than saying the format is
    not supported.
    """
    description = resolve_reader_description(file_path, import_template)
    if description is None:
        suffix = os.path.splitext(file_path)[1].lower()
        raise ValueError(
            f"Unsupported measurement format '{suffix or file_path}'. "
            f"Supported: {', '.join(sorted(_DESCRIPTIONS_BY_SUFFIX))}."
        )
    return description.open_reader(file_path)


def discard_reader_caches() -> None:
    """Forget what the readers keep of a parsed file between reads."""
    for description in READER_DESCRIPTIONS + (_TEMPLATE_READER,):
        if description.discard_caches is not None:
            description.discard_caches()

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

def discover_measurement_files(directory_path: str, templates: Optional[Tuple[Any, ...]] = None) -> List[str]:
    """
    Lists every supported measurement file in a directory, case-insensitively.

    Here rather than in scan_cache because the project indexer needs the same
    answer without scanning anything. `templates` as for `is_measurement_file`.

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
    return sorted(path for path in set(discovered_files) if is_measurement_file(path, templates))


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
