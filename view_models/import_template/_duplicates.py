"""
The wizard's optional duplicate check (CONTEXT.md "Import template"): curves of
the sample that are one result exported more than once, such as the Peak,
Peak-to-Peak and RMS sheets of one MASTA run.

Two curves are duplicates when they have the same channel name, the same order
and equal values after the conversion to RMS (a small tolerance), whatever
their other metadata. The check reads only the sample the wizard holds, in the
background, and never runs at scan: what the user chooses is written into the
template as the channels it does not read (`ImportTemplate.skipped_columns`)
and whole sheets it does not read (`ImportTemplate.sheets`).
"""

import dataclasses
from dataclasses import dataclass
from typing import List, Mapping, Optional, Sequence, Tuple

import numpy as np

from core.import_template import DATA_KIND_TIME_SIGNAL, SHEETS_LISTED, ImportTemplate
from core.source_amplitude import resolve_rms_factor
from io_modules.import_template import (
    TemplateChannel, Workbook, build_template_reading, resolve_linear_values,
    resolve_read_sheets, resolve_x_factor,
)

# Values are equal when they differ by less than this share of the curve's largest value
# (exports round their numbers).
_RELATIVE_TOLERANCE = 1e-3


@dataclass(frozen=True)
class DuplicateCopy:
    """One copy of a curve: where the template reads it in the sample."""

    sheet: str
    column: int
    name: str
    source_amplitude: str


@dataclass(frozen=True)
class DuplicateGroup:
    """Two or more copies of one curve, in sample order."""

    name: str
    order: Optional[float]
    copies: Tuple[DuplicateCopy, ...]


def _rms_curve(channel: TemplateChannel, data_kind: str) -> np.ndarray:
    pairs = np.asarray(channel.pairs.pairs, dtype=np.float64).reshape(-1, 2)
    return np.column_stack((pairs[:, 0] * resolve_x_factor(data_kind, channel.x_unit),
                            resolve_linear_values(channel) * (
                                1.0 if data_kind == DATA_KIND_TIME_SIGNAL
                                else resolve_rms_factor(channel.source_amplitude))))


def _equal_curves(first: np.ndarray, second: np.ndarray) -> bool:
    if first.shape != second.shape:
        return False
    scale = np.abs(first).max(axis=0, initial=0.0)
    return bool(np.all(np.abs(first - second) <= _RELATIVE_TOLERANCE * scale))


def build_duplicate_groups(workbook: Workbook, template: ImportTemplate) -> Tuple[DuplicateGroup, ...]:
    """The duplicate curves among the channels the template reads in the workbook. Run it on a worker."""
    candidates: List[Tuple[TemplateChannel, np.ndarray]] = [
        (channel, _rms_curve(channel, template.data_kind))
        for channel in build_template_reading(workbook, template).channels
        if not channel.problem and channel.pairs.pairs]
    groups: List[Tuple[Optional[float], List[Tuple[TemplateChannel, np.ndarray]]]] = []
    for channel, curve in candidates:
        for _, members in groups:
            first, first_curve = members[0]
            if (first.name == channel.name and first.order == channel.order
                    and _equal_curves(first_curve, curve)):
                members.append((channel, curve))
                break
        else:
            groups.append((channel.order, [(channel, curve)]))
    return tuple(
        DuplicateGroup(members[0][0].name, order, tuple(
            DuplicateCopy(channel.sheet, channel.y_column, channel.name, channel.source_amplitude)
            for channel, _ in members))
        for order, members in groups if len(members) > 1)


def resolve_kept_copies(groups: Sequence[DuplicateGroup], picks: Optional[Mapping[int, int]] = None,
                        source_amplitude: str = "") -> Tuple[Optional[int], ...]:
    """
    The copy kept of each group: the one `picks` names (group number -> copy
    number), else the first copy whose Source amplitude is `source_amplitude`,
    else None (keep all).
    """
    kept: List[Optional[int]] = []
    for number, group in enumerate(groups):
        if picks and number in picks:
            kept.append(picks[number])
        elif source_amplitude:
            kept.append(next((index for index, copy in enumerate(group.copies)
                              if copy.source_amplitude == source_amplitude), None))
        else:
            kept.append(None)
    return tuple(kept)


def build_template_keeping(template: ImportTemplate, workbook: Workbook, groups: Sequence[DuplicateGroup],
                           kept: Sequence[Optional[int]]) -> ImportTemplate:
    """
    The template that reads one copy of each group (`kept`, see
    `resolve_kept_copies`) and everything else it read: the other copies are
    left out as whole sheets where a sheet has no channel left, else as channels.
    """
    dropped = {(copy.sheet, copy.column)
               for group, keep in zip(groups, kept) if keep is not None
               for index, copy in enumerate(group.copies) if index != keep}
    if not dropped:
        return template
    # What the template reads now, as the check saw it: every channel of every read sheet.
    reading = build_template_reading(workbook, template)
    left_per_sheet = {}
    for channel in reading.channels:
        if (channel.sheet, channel.y_column) not in dropped:
            left_per_sheet.setdefault(channel.sheet, []).append(channel.y_column)
    read = resolve_read_sheets(workbook.sheet_names, template)
    sheets = tuple(sheet for sheet in read if sheet in left_per_sheet)
    skipped = tuple(sorted((sheet, column) for sheet, column in dropped if sheet in sheets))
    return dataclasses.replace(
        template, sheets=sheets, sheet_rule=SHEETS_LISTED, skipped_columns=tuple(dict.fromkeys(template.skipped_columns + skipped)))
