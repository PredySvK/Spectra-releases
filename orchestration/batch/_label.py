# =====================================================================
# FILE: orchestration/batch/_label.py
# =====================================================================
"""
Default result set labeling for batch workflows.

When a workflow run or batch is executed without an explicit user-given label,
a default folder name is derived from the terminal block's parameters and the
channels in the measurement selection.

All internal documentation strings and variable labels are standardly written
in English.
"""
from typing import AbstractSet, Optional

from core.block_kinds import KIND_ORDER_CUT
from core.channel_types import (
    CHANNEL_TYPE_ACCELEROMETER,
    CHANNEL_TYPE_MICROPHONE,
    MAIN_INPUT_CHANNEL_TYPES,
)
from core.filter_card_config import COLUMN_CHANNEL, COLUMN_DIRECTION
from core.measurement_selection import MODE_EXPLICIT, MeasurementSelection
from core.workflow_graph import Workflow
from io_modules.result_cache import (
    build_channel_component,
    build_kind_result_set_label,
    build_result_set_label,
    sanitize_result_set_label,
)
from signal_processing.workflow import sole_terminal_block, spec_for
from selection.source_facets import EMPTY_FACET_VALUE


_CHANNEL_TYPE_COMPONENTS = {
    CHANNEL_TYPE_ACCELEROMETER: "Accelerometer",
    CHANNEL_TYPE_MICROPHONE: "Microphone",
}


def data_pool_channel_component(channel_types: AbstractSet[str]) -> str:
    """
    The channel part of a Data Pool result set's name: the one sensor type it
    holds ("Accelerometer"), or "All_Channels" for both.
    """
    types = frozenset(channel_types)
    if types >= MAIN_INPUT_CHANNEL_TYPES:
        return "All_Channels"
    return "_".join(
        _CHANNEL_TYPE_COMPONENTS.get(channel_type, channel_type.title())
        for channel_type in sorted(types)
    )


def default_result_set_label(workflow: Workflow, selection: MeasurementSelection, *,
                             channel_component: Optional[str] = None) -> str:
    """
    What to call the result set when the caller did not name the run.

    A result set is a folder on disk, so the name is what the user navigates by
    -- "Spectrogram_2048_All_Channels" rather than the workflow's working title.
    Order cuts keep the spelling they have always had (§1.21).

    The channel part comes from the selection: its explicit pairs, else its
    Channel column constraint; one sensor names the folder after itself,
    several are counted ("5_Channels"), none means "All_Channels".

    `channel_component` names the channel part outright -- a Data Pool run
    names the sensor type it holds -- and wins over the selection.
    """
    workflow_block = sole_terminal_block(workflow)
    kind = spec_for(workflow_block.block_type).produces

    channel_identities = selection.channel_identities if selection.mode == MODE_EXPLICIT else None
    if channel_identities is not None:
        base_directions = {}
        for base, direction in channel_identities:
            base_directions.setdefault(base, []).append(direction)
        bases = tuple(base_directions)
    else:
        bases = selection.column_values.get(COLUMN_CHANNEL)
        directions = selection.column_values.get(COLUMN_DIRECTION, ())
        base_directions = {
            base: [None if direction == EMPTY_FACET_VALUE else direction for direction in directions]
            for base in bases or ()
        }
    # How many sensors were available is not known here, so several picked
    # ones are counted (0), never called "All_Channels".
    if channel_component is None:
        channel_component = (
            "All_Channels" if bases is None else
            build_channel_component(base_directions, 0)
        )
    if kind == KIND_ORDER_CUT:
        return build_result_set_label(
            workflow_block.params.get("orders_to_extract") or [], base_directions,
            0, channel_component=channel_component,
        )
    return build_kind_result_set_label(kind, workflow_block.params, channel_component)


def selection_result_set_label(workflow: Workflow, selection: MeasurementSelection) -> str:
    """
    What to call a result set computed over a saved Selection:
    `{Selection}_{Kind}_{param}` ("Rozbeh_3st_Spectrum_4096"), Order Tracking
    `{Selection}_Order_Tracking_{orders}`. The Selection already says what the
    set holds, so there is no channel part.
    """
    kind_part = default_result_set_label(workflow, selection, channel_component="").rstrip("_")
    name = sanitize_result_set_label(selection.name)
    return f"{name}_{kind_part}" if name else kind_part
