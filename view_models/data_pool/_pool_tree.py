# =====================================================================
# FILE: view_models/data_pool/_pool_tree.py
# =====================================================================
"""
The Data Pool tree as plain nodes, without Qt.

Decides every row the tree shows -- which exist, in which order, their text
with the channel-type icon, their tooltip and their marker kind -- so the
panel only turns nodes into Qt rows. A new measurement state is one change
here, not in the widget.
"""

import os
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple

from core.models import READING_IMPORTED_RESULT, READING_UNREADABLE, resolve_channel_reading
from core.units import strip_channel_name_prefix
from io_modules.measurement_files import canonical_path

from ._group_by_setup import UNASSIGNED_SETUP, group_by_setup


NODE_SETUP = "setup"
NODE_MEASUREMENT = "measurement"
NODE_SHEET = "sheet"
NODE_CHANNEL = "channel"
NODE_UNREADABLE_FOLDER = "unreadable_folder"
NODE_UNREADABLE_FILE = "unreadable_file"

# What the panel styles a row by; the colours behind them stay GUI tokens.
MARKER_NONE = ""
MARKER_MISSING = "missing"
MARKER_PARTIALLY_READ = "partially_read"
MARKER_IMPORTED_RESULT = "imported_result"
MARKER_UNREADABLE = "unreadable"
MARKER_UNASSIGNED = "unassigned"

_CHANNEL_ICONS = {
    "tacho": "🔄",
    "voltage": "⚡",
    "microphone": "🔊",
    "general_dynamic": "📐",
}
_DEFAULT_CHANNEL_ICON = "📊"


@dataclass(frozen=True, eq=False)
class PoolTreeNode:
    """
    One row of the Data Pool tree and the domain object it stands for.

    `key` names the node across redraws -- never by its text, which carries
    markers and counts -- so an open node can be re-opened. Only the fields of
    its kind are set: `setup_label` on a setup, `run` on a measurement and its
    sheets and channels, `channel` and `unique_label` on a channel, `sheet` on
    a sheet, `directory` on an unreadable folder, `unreadable` on its files.
    """

    kind: str
    text: str
    key: tuple
    tooltip: str = ""
    marker: str = MARKER_NONE
    children: Tuple["PoolTreeNode", ...] = ()
    setup_label: Optional[str] = None
    run: Any = None
    channel: Any = None
    unique_label: Optional[str] = None
    sheet: Optional[str] = None
    directory: Optional[str] = None
    unreadable: Any = None


@dataclass(frozen=True)
class PoolTree:
    """The Data Pool tree's top-level nodes in display order."""

    roots: Tuple[PoolTreeNode, ...] = ()


def build_pool_tree(
    setup_labels: Iterable[str],
    runs: Iterable[Any],
    entries_by_path: Optional[Mapping[str, Any]] = None,
    unreadable_by_folder: Iterable[Tuple[str, Sequence[Any]]] = (),
    missing_paths: frozenset = frozenset(),
) -> PoolTree:
    """
    The Data Pool tree for a pool: setups in the order they were defined with
    the Unassigned bucket last, then one heading per folder holding Unreadable
    files.

    `entries_by_path` maps canonical paths to source location entries (their
    `setup_label` files a measurement under a setup); `missing_paths` are the
    canonical paths of the pool's Missing measurements.
    """
    roots = [
        _setup_node(label, setup_runs, missing_paths)
        for label, setup_runs in group_by_setup(setup_labels, runs, entries_by_path).items()
    ]
    roots.extend(
        _unreadable_folder_node(directory, files)
        for directory, files in unreadable_by_folder if files
    )
    return PoolTree(roots=tuple(roots))


def _setup_node(label, runs, missing_paths) -> PoolTreeNode:
    seen = set()
    folders = []
    for run in runs:
        file_path = getattr(run, "file_path", None)
        if not file_path:
            continue
        folder = os.path.dirname(file_path)
        key = canonical_path(folder)
        if key not in seen:
            seen.add(key)
            folders.append(folder)
    tooltip = "\n".join(folders) if label is not UNASSIGNED_SETUP else ""
    return PoolTreeNode(
        kind=NODE_SETUP,
        text=f"🧪 {label}  ({len(runs)})",
        # The sentinel itself, so a setup the user named "Unassigned" keys apart.
        key=(NODE_SETUP, label),
        tooltip=tooltip,
        marker=MARKER_UNASSIGNED if label is UNASSIGNED_SETUP else MARKER_NONE,
        children=tuple(_measurement_node(run, missing_paths) for run in runs),
        setup_label=label,
    )


def _measurement_node(run, missing_paths) -> PoolTreeNode:
    path = canonical_path(run.file_path)
    if path in missing_paths:  # the project still lists it, but it is not on disk any more
        text = f"⚠ {run.file_name}"
        marker = MARKER_MISSING
        tooltip = (f"Not found on disk:\n{run.file_path}\n\n"
                   f"Right-click to locate it. Its metadata and results are still in the project.")
    elif run.lost_parts:  # a Partially read measurement: the healthy channels stay usable
        lost = "\n".join(f"  {part.describe()}" for part in run.lost_parts)
        text = f"◐ {run.file_name}"
        marker = MARKER_PARTIALLY_READ
        tooltip = (f"Incomplete: part of this file could not be read.\n{lost}\n\n"
                   "The channels shown are complete and can be used.")
    else:
        text, marker, tooltip = run.file_name, MARKER_NONE, ""

    return PoolTreeNode(
        kind=NODE_MEASUREMENT,
        text=text,
        key=(NODE_MEASUREMENT, path),
        tooltip=tooltip,
        marker=marker,
        children=_measurement_children(run, path),
        run=run,
    )


def _measurement_children(run, path) -> Tuple[PoolTreeNode, ...]:
    """The channels of a run, grouped under one heading per workbook sheet (#639)."""
    # Each entry is (sheet, channels): a sheet heading, or one channel outside
    # any sheet (sheet None), in the order the channels come.
    groups = []
    by_sheet = {}
    for unique_label, channel in run.available_channels.items():
        node = _channel_node(run, path, unique_label, channel)
        sheet = getattr(channel, "sheet", None)
        if not sheet:
            groups.append((None, [node]))
        elif sheet in by_sheet:
            by_sheet[sheet].append(node)
        else:
            by_sheet[sheet] = [node]
            groups.append((sheet, by_sheet[sheet]))

    children = []
    for sheet, nodes in groups:
        if sheet is None:
            children.extend(nodes)
            continue
        children.append(PoolTreeNode(
            kind=NODE_SHEET,
            text=f"📄 {sheet}",
            key=(NODE_SHEET, path, sheet),
            children=tuple(nodes),
            run=run,
            sheet=sheet,
        ))
    return tuple(children)


def _channel_node(run, path, unique_label, channel) -> PoolTreeNode:
    icon = _CHANNEL_ICONS.get(channel.type, _DEFAULT_CHANNEL_ICON)
    unit = channel.unit if channel.unit else "unassigned"

    reading = resolve_channel_reading(channel)
    if reading == READING_IMPORTED_RESULT:
        marker = MARKER_IMPORTED_RESULT
        tooltip = "Imported result. Drag or double-click to open in Order Tracking."
    elif reading == READING_UNREADABLE:
        # A non-time-response UNV dataset (func_type != 1) is listed so the
        # file's contents stay visible, but no reader can turn it into a
        # waveform -- mark it rather than let a drop fail from inside a plot.
        marker = MARKER_UNREADABLE
        tooltip = ("Not a time-domain waveform (UNV func_type != 1, e.g. a spectrum "
                   "or cross-spectrum). Listed so you can see the file contains it, "
                   "but it cannot be dropped onto a plot.")
    else:
        marker, tooltip = MARKER_NONE, ""

    return PoolTreeNode(
        kind=NODE_CHANNEL,
        text=f"{icon} {strip_channel_name_prefix(channel.name)} [{unit}]",
        key=(NODE_CHANNEL, path, unique_label),
        tooltip=tooltip,
        marker=marker,
        run=run,
        channel=channel,
        unique_label=unique_label,
    )


def _unreadable_folder_node(directory, files) -> PoolTreeNode:
    """A heading with one row per file the last scan of `directory` could not read."""
    folder_name = os.path.basename(os.path.normpath(directory)) or directory
    rows = tuple(
        PoolTreeNode(
            kind=NODE_UNREADABLE_FILE,
            text=f"✖ {os.path.basename(unreadable.path)}",
            key=(NODE_UNREADABLE_FILE, canonical_path(unreadable.path)),
            tooltip=(f"Could not be read:\n{unreadable.path}\n\n{unreadable.reason}\n\n"
                     f"It is tried again on the next scan of this folder."),
            marker=MARKER_UNREADABLE,
            unreadable=unreadable,
        )
        for unreadable in files
    )
    return PoolTreeNode(
        kind=NODE_UNREADABLE_FOLDER,
        text=f"📁 {folder_name}  ({len(files)} unreadable)",
        key=(NODE_UNREADABLE_FOLDER, canonical_path(directory)),
        tooltip=f"{directory}\n\nFiles in this folder that could not be read.",
        marker=MARKER_UNREADABLE,
        children=rows,
        directory=directory,
    )
